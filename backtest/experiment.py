import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

from backtest.simulator import (HypotheticalLevels, ResearchMetrics,
                                SimulationResult, calculate_metrics,
                                simulate_candidates)
from data.historical import (DataValidationError, DatasetQualityReport,
                             HistoricalDataset, aggregate_timeframe,
                             dataset_fingerprint, quality_report)
from strategy.confluence import ResearchSignal
from strategy.engine import EngineConfig, EngineSnapshot, SequentialResearchEngine
from strategy.timeframes import ContextSeries


RESEARCH_SCHEMA_VERSION = "3.0"


def _finite_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class SimulationConfig:
    risk_distance: float = 1.0
    reward_risk: float = 1.0
    same_candle_policy: str = "conservative"
    max_bars: int | None = None

    def __post_init__(self):
        if not _finite_number(self.risk_distance) or self.risk_distance <= 0:
            raise ValueError("risk_distance must be positive")
        if not _finite_number(self.reward_risk) or self.reward_risk <= 0:
            raise ValueError("reward_risk must be positive")
        if self.same_candle_policy not in ("conservative", "optimistic"):
            raise ValueError("invalid same_candle_policy")
        if self.max_bars is not None and (
                not isinstance(self.max_bars, int) or isinstance(self.max_bars, bool)
                or self.max_bars < 1):
            raise ValueError("max_bars must be at least 1 or None")


@dataclass(frozen=True)
class ExperimentConfig:
    experiment_name: str
    dataset_identifier: str
    execution_timeframe: str
    execution_interval_seconds: int | None = None
    higher_timeframe_seconds: int | None = None
    retain_incomplete_final_htf: bool = False
    ote_lower_fraction: float = 0.62
    ote_upper_fraction: float = 0.79
    engine: EngineConfig = EngineConfig()
    simulation: SimulationConfig = SimulationConfig()

    def __post_init__(self):
        if not isinstance(self.experiment_name, str) or not self.experiment_name:
            raise ValueError("experiment_name cannot be empty")
        if not isinstance(self.dataset_identifier, str) or not self.dataset_identifier:
            raise ValueError("dataset_identifier cannot be empty")
        if not isinstance(self.execution_timeframe, str) or not self.execution_timeframe:
            raise ValueError("execution_timeframe cannot be empty")
        for name, value in (("execution_interval_seconds", self.execution_interval_seconds),
                            ("higher_timeframe_seconds", self.higher_timeframe_seconds)):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)
                                      or value <= 0):
                raise ValueError(f"{name} must be a positive integer or None")
        ote_values = (self.ote_lower_fraction, self.ote_upper_fraction)
        if (any(not _finite_number(value) for value in ote_values)
                or not 0 <= self.ote_lower_fraction <= self.ote_upper_fraction <= 1):
            raise ValueError("OTE fractions must satisfy 0 <= lower <= upper <= 1")
        if not isinstance(self.retain_incomplete_final_htf, bool):
            raise ValueError("retain_incomplete_final_htf must be boolean")
        if not isinstance(self.engine, EngineConfig):
            raise TypeError("engine must be EngineConfig")
        if not isinstance(self.simulation, SimulationConfig):
            raise TypeError("simulation must be SimulationConfig")
        integer_engine_fields = (self.engine.swing_window, self.engine.reclaim_window,
                                 self.engine.displacement_lookback)
        if any(not isinstance(value, int) or isinstance(value, bool)
               for value in integer_engine_fields):
            raise ValueError("engine count/window parameters must be integers")
        numeric_engine_fields = (
            self.engine.liquidity_tolerance,
            self.engine.displacement_range_multiple,
            self.engine.displacement_body_ratio,
            self.engine.equilibrium_tolerance,
        )
        if any(not _finite_number(value) for value in numeric_engine_fields):
            raise ValueError("engine numeric parameters must be finite numbers")
        requirement_fields = (
            self.engine.require_htf_bias, self.engine.require_liquidity_event,
            self.engine.require_mss, self.engine.require_displacement,
            self.engine.require_pd_array, self.engine.require_price_zone,
        )
        if any(not isinstance(value, bool) for value in requirement_fields):
            raise ValueError("engine candidate requirement fields must be boolean")

    def to_dict(self) -> dict[str, Any]:
        engine = asdict(self.engine)
        for name in ("liquidity_tolerance", "displacement_range_multiple",
                     "displacement_body_ratio", "equilibrium_tolerance"):
            engine[name] = float(engine[name])
        return {
            "dataset_identifier": self.dataset_identifier,
            "engine": engine,
            "execution_interval_seconds": self.execution_interval_seconds,
            "execution_timeframe": self.execution_timeframe,
            "experiment_name": self.experiment_name,
            "higher_timeframe_seconds": self.higher_timeframe_seconds,
            "ote_lower_fraction": float(self.ote_lower_fraction),
            "ote_upper_fraction": float(self.ote_upper_fraction),
            "retain_incomplete_final_htf": self.retain_incomplete_final_htf,
            "simulation": {
                "max_bars": self.simulation.max_bars,
                "reward_risk": float(self.simulation.reward_risk),
                "risk_distance": float(self.simulation.risk_distance),
                "same_candle_policy": self.simulation.same_candle_policy,
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          allow_nan=False)

    @classmethod
    def from_json(cls, payload: str) -> "ExperimentConfig":
        def strict_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate configuration field: {key}")
                result[key] = value
            return result
        try:
            data = json.loads(payload, object_pairs_hook=strict_object)
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError("malformed experiment configuration JSON") from error
        if not isinstance(data, dict):
            raise ValueError("experiment configuration must be a JSON object")
        expected = {item.name for item in fields(cls)}
        _require_exact_keys(data, expected, "experiment configuration")
        engine_data = data["engine"]
        simulation_data = data["simulation"]
        if not isinstance(engine_data, dict) or not isinstance(simulation_data, dict):
            raise ValueError("engine and simulation configuration must be objects")
        _require_exact_keys(engine_data, {item.name for item in fields(EngineConfig)},
                            "engine configuration")
        _require_exact_keys(simulation_data,
                            {item.name for item in fields(SimulationConfig)},
                            "simulation configuration")
        try:
            data["engine"] = EngineConfig(**engine_data)
            data["simulation"] = SimulationConfig(**simulation_data)
            return cls(**data)
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid experiment configuration: {error}") from error


def _require_exact_keys(data: dict, expected: set[str], label: str) -> None:
    actual = set(data)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        raise ValueError(f"unknown {label} fields: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"missing {label} fields: {', '.join(missing)}")


def experiment_fingerprint(config: ExperimentConfig, dataset_hash: str,
                           schema_version: str = RESEARCH_SCHEMA_VERSION) -> str:
    payload = json.dumps({
        "configuration": config.to_dict(),
        "dataset_fingerprint": dataset_hash,
        "schema_version": schema_version,
    }, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def _quality_dict(report: DatasetQualityReport) -> dict[str, Any]:
    return {
        "candle_count": report.candle_count,
        "chronological": report.chronological,
        "duplicate_count": report.duplicate_count,
        "expected_interval_seconds": report.expected_interval_seconds,
        "first_timestamp": _iso(report.first_timestamp),
        "gaps": [{
            "missing_intervals": gap.missing_intervals,
            "next_timestamp": _iso(gap.next_timestamp),
            "previous_timestamp": _iso(gap.previous_timestamp),
        } for gap in report.gaps],
        "interval_consistent": report.interval_consistent,
        "invalid_rows": list(report.invalid_rows),
        "last_timestamp": _iso(report.last_timestamp),
        "observed_interval_seconds": report.observed_interval_seconds,
    }


@dataclass(frozen=True)
class ExperimentResult:
    experiment_fingerprint: str
    dataset_fingerprint: str
    configuration: ExperimentConfig
    schema_version: str
    first_timestamp: datetime
    last_timestamp: datetime
    quality: DatasetQualityReport
    snapshots: tuple[EngineSnapshot, ...]
    candidates: tuple[ResearchSignal, ...]
    simulations: tuple[SimulationResult, ...]
    metrics: ResearchMetrics
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [{
                "direction": signal.direction,
                "evidence": [asdict(item) for item in signal.evidence],
                "index": signal.index,
            } for signal in self.candidates],
            "configuration": self.configuration.to_dict(),
            "dataset_fingerprint": self.dataset_fingerprint,
            "experiment_fingerprint": self.experiment_fingerprint,
            "metrics": asdict(self.metrics),
            "quality": _quality_dict(self.quality),
            "schema_version": self.schema_version,
            "simulations": [{
                "bars_elapsed": item.bars_elapsed,
                "candidate_index": item.candidate_index,
                "direction": item.direction,
                "entry_reference": item.entry_reference,
                "invalidation_reference": item.invalidation_reference,
                "normalized_r": item.normalized_r,
                "objective_reference": item.objective_reference,
                "outcome": item.outcome,
                "resolved_index": item.resolved_index,
            } for item in self.simulations],
            "time_range": {
                "first": _iso(self.first_timestamp), "last": _iso(self.last_timestamp),
            },
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          allow_nan=False)

    def candidate_csv(self) -> str:
        stream = StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("candidate_index", "direction", "entry_reference",
                         "invalidation_reference", "objective_reference", "outcome",
                         "bars_elapsed", "normalized_r", "resolved_index", "evidence"))
        simulations = {item.candidate_index: item for item in self.simulations}
        for signal in self.candidates:
            item = simulations.get(signal.index)
            writer.writerow((
                signal.index, _csv_safe(signal.direction),
                "" if item is None else item.entry_reference,
                "" if item is None else item.invalidation_reference,
                "" if item is None else item.objective_reference,
                "unresolved" if item is None else item.outcome,
                "" if item is None else item.bars_elapsed,
                "" if item is None or item.normalized_r is None else item.normalized_r,
                "" if item is None or item.resolved_index is None else item.resolved_index,
                _csv_safe(json.dumps([asdict(e) for e in signal.evidence],
                                     sort_keys=True, separators=(",", ":"))),
            ))
        return stream.getvalue()

    def write_json(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json() + "\n", encoding="utf-8")

    def write_candidate_csv(self, path: str | Path) -> None:
        Path(path).write_text(self.candidate_csv(), encoding="utf-8", newline="")


def _csv_safe(value: str) -> str:
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


class ExperimentRunner:
    """Offline orchestration over canonical immutable historical data."""

    def __init__(self, dataset: HistoricalDataset, config: ExperimentConfig):
        if dataset.identifier != config.dataset_identifier:
            raise ValueError("dataset identifier does not match experiment configuration")
        self.dataset = HistoricalDataset(dataset.candles, dataset.identifier)
        self.config = config

    def run(self) -> ExperimentResult:
        config = self.config
        execution = self.dataset.context_series(config.execution_timeframe)
        higher = None
        warnings = []
        if config.higher_timeframe_seconds is not None:
            try:
                aggregated = aggregate_timeframe(
                    self.dataset, timedelta(seconds=config.higher_timeframe_seconds),
                    retain_incomplete_final=config.retain_incomplete_final_htf,
                    timeframe_label=f"{config.higher_timeframe_seconds}s",
                )
                higher = aggregated.context_series(
                    f"{config.higher_timeframe_seconds}s"
                )
            except DataValidationError as error:
                if "no completed candles" not in str(error):
                    raise
                warnings.append("no completed higher-timeframe candle available")
                higher = ContextSeries((), f"{config.higher_timeframe_seconds}s", ())
        engine = SequentialResearchEngine(execution, higher, config.engine)
        snapshots = engine.run()
        candidates = tuple(snapshot.signal for snapshot in snapshots if snapshot.signal)
        simulation = config.simulation

        def levels(signal: ResearchSignal) -> HypotheticalLevels:
            entry = execution.candles[signal.index].close
            risk = simulation.risk_distance
            reward = risk * simulation.reward_risk
            if signal.direction == "bullish":
                return HypotheticalLevels(entry, entry - risk, entry + reward)
            return HypotheticalLevels(entry, entry + risk, entry - reward)

        simulations = simulate_candidates(
            execution.candles, candidates, levels,
            same_candle_policy=simulation.same_candle_policy,
            max_bars=simulation.max_bars,
        )
        quality = quality_report(
            self.dataset.candles,
            None if config.execution_interval_seconds is None else
            timedelta(seconds=config.execution_interval_seconds),
        )
        if quality.gaps:
            warnings.append(f"{len(quality.gaps)} expected-interval gap(s) detected")
        data_hash = dataset_fingerprint(self.dataset)
        return ExperimentResult(
            experiment_fingerprint(config, data_hash), data_hash, config,
            RESEARCH_SCHEMA_VERSION, self.dataset.candles[0].timestamp,
            self.dataset.candles[-1].timestamp, quality, snapshots, candidates,
            simulations, calculate_metrics(simulations), tuple(warnings),
        )
