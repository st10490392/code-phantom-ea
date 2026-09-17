"""Deterministic chronological out-of-sample research windows.

This module coordinates existing offline experiments.  It deliberately does
not tune parameters or choose a preferred configuration.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from backtest.experiment import ExperimentConfig, ExperimentResult, ExperimentRunner
from backtest.simulator import ResearchMetrics, SimulationResult, calculate_metrics
from data.historical import HistoricalDataset, dataset_fingerprint


WindowRole = Literal["development", "evaluation", "holdout"]


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class WalkForwardConfig:
    development_length: int
    evaluation_length: int
    step_length: int
    anchored: bool = False
    holdout_length: int = 0

    def __post_init__(self) -> None:
        for name in ("development_length", "evaluation_length", "step_length"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (isinstance(self.holdout_length, bool)
                or not isinstance(self.holdout_length, int)
                or self.holdout_length < 0):
            raise ValueError("holdout_length must be a non-negative integer")
        if not isinstance(self.anchored, bool):
            raise ValueError("anchored must be boolean")

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "anchored": self.anchored,
            "development_length": self.development_length,
            "evaluation_length": self.evaluation_length,
            "holdout_length": self.holdout_length,
            "step_length": self.step_length,
        }


@dataclass(frozen=True)
class DatasetWindow:
    identity: str
    role: WindowRole
    start_index: int
    end_index: int
    first_timestamp: datetime
    last_timestamp: datetime

    def __post_init__(self) -> None:
        if self.role not in ("development", "evaluation", "holdout"):
            raise ValueError("invalid window role")
        if self.start_index < 0 or self.end_index <= self.start_index:
            raise ValueError("window must be a non-empty forward half-open range")

    @property
    def candle_count(self) -> int:
        return self.end_index - self.start_index


@dataclass(frozen=True)
class WindowResult:
    window: DatasetWindow
    dataset_fingerprint: str
    experiment_fingerprint: str
    candidate_count: int
    simulation_count: int
    metrics: ResearchMetrics

    def to_dict(self) -> dict:
        return {
            "candidate_count": self.candidate_count,
            "dataset_fingerprint": self.dataset_fingerprint,
            "experiment_fingerprint": self.experiment_fingerprint,
            "metrics": asdict(self.metrics),
            "simulation_count": self.simulation_count,
            "window": {
                "candle_count": self.window.candle_count,
                "end_index": self.window.end_index,
                "first_timestamp": _iso(self.window.first_timestamp),
                "identity": self.window.identity,
                "last_timestamp": _iso(self.window.last_timestamp),
                "role": self.window.role,
                "start_index": self.window.start_index,
            },
        }


@dataclass(frozen=True)
class WalkForwardStatistics:
    window_count: int
    resolved_observations: int
    average_r: float
    cumulative_r: float
    win_rate: float
    maximum_drawdown_r: float
    positive_windows: int
    negative_windows: int
    flat_windows: int


@dataclass(frozen=True)
class WalkForwardReport:
    configuration: WalkForwardConfig
    source_dataset_fingerprint: str
    development_results: tuple[WindowResult, ...]
    evaluation_results: tuple[WindowResult, ...]
    holdout_result: WindowResult | None
    evaluation_statistics: WalkForwardStatistics

    def to_dict(self) -> dict:
        return {
            "configuration": self.configuration.to_dict(),
            "development_results": [item.to_dict() for item in self.development_results],
            "evaluation_results": [item.to_dict() for item in self.evaluation_results],
            "evaluation_statistics": asdict(self.evaluation_statistics),
            "holdout_result": (None if self.holdout_result is None
                               else self.holdout_result.to_dict()),
            "source_dataset_fingerprint": self.source_dataset_fingerprint,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          allow_nan=False)


def build_walk_forward_windows(dataset: HistoricalDataset,
                               config: WalkForwardConfig
                               ) -> tuple[tuple[DatasetWindow, DatasetWindow], ...]:
    """Return chronological development/evaluation pairs.

    Indices are half-open.  The holdout suffix is excluded from all generated
    pairs.  Evaluation windows may overlap only when the caller explicitly
    chooses ``step_length < evaluation_length``.
    """
    usable_end = len(dataset.candles) - config.holdout_length
    if usable_end <= 0:
        raise ValueError("holdout consumes the entire dataset")
    if config.development_length + config.evaluation_length > usable_end:
        raise ValueError("insufficient data for one development/evaluation pair")
    pairs = []
    evaluation_start = config.development_length
    sequence = 0
    while evaluation_start + config.evaluation_length <= usable_end:
        development_start = 0 if config.anchored else evaluation_start - config.development_length
        development_end = evaluation_start
        evaluation_end = evaluation_start + config.evaluation_length
        development = _window(dataset, f"wf-{sequence}:development", "development",
                              development_start, development_end)
        evaluation = _window(dataset, f"wf-{sequence}:evaluation", "evaluation",
                             evaluation_start, evaluation_end)
        pairs.append((development, evaluation))
        sequence += 1
        evaluation_start += config.step_length
    return tuple(pairs)


def _window(dataset: HistoricalDataset, identity: str, role: WindowRole,
            start: int, end: int) -> DatasetWindow:
    if not 0 <= start < end <= len(dataset.candles):
        raise ValueError("window boundaries are outside the dataset")
    return DatasetWindow(identity, role, start, end,
                         dataset.candles[start].timestamp,
                         dataset.candles[end - 1].timestamp)


def _slice(dataset: HistoricalDataset, window: DatasetWindow) -> HistoricalDataset:
    return HistoricalDataset(dataset.candles[window.start_index:window.end_index],
                             dataset.identifier)


def _summarize(window: DatasetWindow, result: ExperimentResult) -> WindowResult:
    return WindowResult(window, result.dataset_fingerprint,
                        result.experiment_fingerprint, len(result.candidates),
                        len(result.simulations), result.metrics)


def _statistics(results: tuple[WindowResult, ...],
                simulations: tuple[SimulationResult, ...]) -> WalkForwardStatistics:
    metrics = calculate_metrics(simulations)
    cumulative = [item.metrics.cumulative_r for item in results]
    return WalkForwardStatistics(
        len(results), metrics.resolved, metrics.average_r, metrics.cumulative_r,
        metrics.win_rate, metrics.maximum_drawdown_r,
        sum(value > 0 for value in cumulative),
        sum(value < 0 for value in cumulative),
        sum(value == 0 for value in cumulative),
    )


class WalkForwardRunner:
    """Run one fixed experiment configuration across chronological windows."""

    def __init__(self, dataset: HistoricalDataset, experiment: ExperimentConfig,
                 windows: WalkForwardConfig):
        if dataset.identifier != experiment.dataset_identifier:
            raise ValueError("dataset identifier does not match experiment configuration")
        self.dataset = HistoricalDataset(dataset.candles, dataset.identifier)
        self.experiment = experiment
        self.windows = windows

    def run(self) -> WalkForwardReport:
        development_results = []
        evaluation_results = []
        evaluation_simulations: list[SimulationResult] = []
        for development, evaluation in build_walk_forward_windows(self.dataset, self.windows):
            development_run = ExperimentRunner(_slice(self.dataset, development),
                                               self.experiment).run()
            evaluation_run = ExperimentRunner(_slice(self.dataset, evaluation),
                                              self.experiment).run()
            development_results.append(_summarize(development, development_run))
            evaluation_results.append(_summarize(evaluation, evaluation_run))
            evaluation_simulations.extend(evaluation_run.simulations)
        holdout_result = None
        if self.windows.holdout_length:
            start = len(self.dataset.candles) - self.windows.holdout_length
            holdout = _window(self.dataset, "holdout", "holdout", start,
                              len(self.dataset.candles))
            holdout_result = _summarize(
                holdout, ExperimentRunner(_slice(self.dataset, holdout), self.experiment).run()
            )
        evaluations = tuple(evaluation_results)
        return WalkForwardReport(
            self.windows, dataset_fingerprint(self.dataset),
            tuple(development_results), evaluations, holdout_result,
            _statistics(evaluations, tuple(evaluation_simulations)),
        )
