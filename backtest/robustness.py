"""Deterministic comparison of caller-defined research hypotheses."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from backtest.experiment import ExperimentConfig
from backtest.walkforward import WalkForwardConfig, WalkForwardReport, WalkForwardRunner
from data.historical import HistoricalDataset, dataset_fingerprint


ROBUSTNESS_SCHEMA_VERSION = "1.0"


def hypothesis_fingerprint(config: ExperimentConfig) -> str:
    payload = json.dumps(config.to_dict(), sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class Hypothesis:
    identifier: str
    configuration: ExperimentConfig

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            raise ValueError("hypothesis identifier cannot be empty")
        if not isinstance(self.configuration, ExperimentConfig):
            raise TypeError("configuration must be ExperimentConfig")

    @property
    def configuration_fingerprint(self) -> str:
        return hypothesis_fingerprint(self.configuration)


@dataclass(frozen=True)
class BaselineDifference:
    baseline_identifier: str
    candidate_count_difference: int
    resolved_count_difference: int
    average_r_difference: float
    cumulative_r_difference: float
    drawdown_difference: float
    matching_window_sign_count: int
    compared_window_count: int


@dataclass(frozen=True)
class HypothesisResult:
    identifier: str
    configuration_fingerprint: str
    report: WalkForwardReport
    baseline_difference: BaselineDifference | None

    def to_dict(self) -> dict:
        return {
            "baseline_difference": (None if self.baseline_difference is None
                                    else asdict(self.baseline_difference)),
            "configuration_fingerprint": self.configuration_fingerprint,
            "identifier": self.identifier,
            "walk_forward": self.report.to_dict(),
        }


@dataclass(frozen=True)
class RobustnessReport:
    baseline_identifier: str
    dataset_fingerprint: str
    schema_version: str
    results: tuple[HypothesisResult, ...]

    def to_dict(self) -> dict:
        return {
            "baseline_identifier": self.baseline_identifier,
            "dataset_fingerprint": self.dataset_fingerprint,
            "results": [item.to_dict() for item in self.results],
            "schema_version": self.schema_version,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          allow_nan=False)


def _difference(report: WalkForwardReport, baseline: WalkForwardReport,
                baseline_identifier: str) -> BaselineDifference:
    current = report.evaluation_statistics
    reference = baseline.evaluation_statistics
    current_candidates = sum(item.candidate_count for item in report.evaluation_results)
    baseline_candidates = sum(item.candidate_count for item in baseline.evaluation_results)
    pairs = zip(report.evaluation_results, baseline.evaluation_results)
    matching = sum((left.metrics.cumulative_r > 0) == (right.metrics.cumulative_r > 0)
                   and (left.metrics.cumulative_r < 0) == (right.metrics.cumulative_r < 0)
                   for left, right in pairs)
    return BaselineDifference(
        baseline_identifier, current_candidates - baseline_candidates,
        current.resolved_observations - reference.resolved_observations,
        current.average_r - reference.average_r,
        current.cumulative_r - reference.cumulative_r,
        current.maximum_drawdown_r - reference.maximum_drawdown_r,
        matching, len(report.evaluation_results),
    )


class RobustnessRunner:
    """Compare an explicit ordered collection without searching or ranking it."""

    def __init__(self, dataset: HistoricalDataset,
                 hypotheses: tuple[Hypothesis, ...] | list[Hypothesis],
                 windows: WalkForwardConfig, *, baseline_identifier: str):
        self.dataset = HistoricalDataset(dataset.candles, dataset.identifier)
        self.hypotheses = tuple(hypotheses)
        self.windows = windows
        self.baseline_identifier = baseline_identifier
        if not self.hypotheses:
            raise ValueError("at least one hypothesis is required")
        identifiers = [item.identifier for item in self.hypotheses]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("hypothesis identifiers must be unique")
        if baseline_identifier not in identifiers:
            raise ValueError("baseline identifier must name a supplied hypothesis")
        if any(item.configuration.dataset_identifier != dataset.identifier
               for item in self.hypotheses):
            raise ValueError("all hypotheses must reference the supplied dataset")

    def run(self) -> RobustnessReport:
        reports = tuple(WalkForwardRunner(self.dataset, item.configuration,
                                          self.windows).run()
                        for item in self.hypotheses)
        baseline_index = next(index for index, item in enumerate(self.hypotheses)
                              if item.identifier == self.baseline_identifier)
        baseline = reports[baseline_index]
        results = tuple(HypothesisResult(
            hypothesis.identifier, hypothesis.configuration_fingerprint, report,
            None if index == baseline_index else
            _difference(report, baseline, self.baseline_identifier),
        ) for index, (hypothesis, report) in enumerate(zip(self.hypotheses, reports)))
        return RobustnessReport(self.baseline_identifier,
                                dataset_fingerprint(self.dataset),
                                ROBUSTNESS_SCHEMA_VERSION, results)
