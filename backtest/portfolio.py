"""Independent multi-instrument offline research orchestration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from statistics import pstdev

from backtest.experiment import ExperimentConfig, ExperimentResult, ExperimentRunner
from backtest.simulator import ResearchMetrics, calculate_metrics
from data.historical import HistoricalDataset


@dataclass(frozen=True)
class InstrumentExperiment:
    instrument: str
    dataset: HistoricalDataset
    configuration: ExperimentConfig

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, str) or not self.instrument.strip():
            raise ValueError("instrument identity cannot be empty")
        if self.dataset.identifier != self.configuration.dataset_identifier:
            raise ValueError("instrument dataset and configuration identifiers differ")


@dataclass(frozen=True)
class InstrumentResearchResult:
    instrument: str
    candle_count: int
    candidate_frequency: float
    experiment: ExperimentResult

    def to_dict(self) -> dict:
        return {
            "candidate_frequency": self.candidate_frequency,
            "candle_count": self.candle_count,
            "experiment": self.experiment.to_dict(),
            "instrument": self.instrument,
        }


@dataclass(frozen=True)
class PortfolioResearchReport:
    instruments: tuple[InstrumentResearchResult, ...]
    aggregate_metrics: ResearchMetrics
    aggregate_candidate_count: int
    aggregate_candle_count: int
    aggregate_candidate_frequency: float
    cumulative_r_dispersion: float

    def to_dict(self) -> dict:
        return {
            "aggregate_candidate_count": self.aggregate_candidate_count,
            "aggregate_candidate_frequency": self.aggregate_candidate_frequency,
            "aggregate_candle_count": self.aggregate_candle_count,
            "aggregate_metrics": asdict(self.aggregate_metrics),
            "cumulative_r_dispersion": self.cumulative_r_dispersion,
            "instruments": [item.to_dict() for item in self.instruments],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          allow_nan=False)


class MultiInstrumentRunner:
    """Run isolated engines sequentially and aggregate observations afterward."""

    def __init__(self, experiments: tuple[InstrumentExperiment, ...] |
                 list[InstrumentExperiment]):
        copied = tuple(experiments)
        if not copied:
            raise ValueError("at least one instrument experiment is required")
        identities = [item.instrument for item in copied]
        if len(set(identities)) != len(identities):
            raise ValueError("instrument identities must be unique")
        # Copy each candle tuple now so caller collection mutation cannot cross runs.
        self.experiments = tuple(InstrumentExperiment(
            item.instrument,
            HistoricalDataset(item.dataset.candles, item.dataset.identifier),
            item.configuration,
        ) for item in copied)

    def run(self) -> PortfolioResearchReport:
        results = []
        all_simulations = []
        candle_count = 0
        candidate_count = 0
        for item in self.experiments:
            result = ExperimentRunner(item.dataset, item.configuration).run()
            count = len(item.dataset.candles)
            candidates = len(result.candidates)
            results.append(InstrumentResearchResult(
                item.instrument, count, candidates / count, result))
            candle_count += count
            candidate_count += candidates
            all_simulations.extend(result.simulations)
        cumulative_values = [item.experiment.metrics.cumulative_r for item in results]
        dispersion = pstdev(cumulative_values) if len(cumulative_values) > 1 else 0.0
        return PortfolioResearchReport(
            tuple(results), calculate_metrics(tuple(all_simulations)), candidate_count,
            candle_count, candidate_count / candle_count, dispersion,
        )
