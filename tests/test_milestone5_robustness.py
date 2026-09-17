from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from backtest.experiment import ExperimentConfig
from backtest.robustness import Hypothesis, RobustnessRunner, hypothesis_fingerprint
from backtest.walkforward import WalkForwardConfig
from data.historical import HistoricalCandle, HistoricalDataset
from strategy.engine import EngineConfig


def dataset(count=18, last_close=None):
    start = datetime(2026, 2, 1, tzinfo=UTC)
    candles = []
    for index in range(count):
        center = 100 + (index % 5)
        close = center + .5 if last_close is None or index != count - 1 else last_close
        candles.append(HistoricalCandle(start + timedelta(minutes=5 * index),
                                        center, max(center + 2, close),
                                        min(center - 2, close), close))
    return HistoricalDataset(tuple(candles), "robust-data")


def config(name="base", **engine_changes):
    engine = EngineConfig(require_htf_bias=False, require_liquidity_event=False,
                          require_mss=False, require_displacement=False,
                          require_pd_array=False, require_price_zone=False)
    return ExperimentConfig(name, "robust-data", "5m",
                            engine=replace(engine, **engine_changes))


def hypotheses():
    return (
        Hypothesis("baseline", config()),
        Hypothesis("liquidity-required", config("liquidity", require_liquidity_event=True)),
        Hypothesis("displacement-required", config("displacement",
                                                    require_displacement=True)),
    )


def test_hypotheses_are_immutable_and_identifiers_are_validated():
    item = Hypothesis("h", config())
    with pytest.raises(FrozenInstanceError):
        item.identifier = "changed"
    with pytest.raises(ValueError, match="empty"):
        Hypothesis("", config())
    with pytest.raises(ValueError, match="unique"):
        RobustnessRunner(dataset(), (item, item), WalkForwardConfig(6, 3, 3),
                         baseline_identifier="h")
    with pytest.raises(ValueError, match="baseline"):
        RobustnessRunner(dataset(), (item,), WalkForwardConfig(6, 3, 3),
                         baseline_identifier="missing")


def test_identical_configurations_have_identical_fingerprints_without_deduplication():
    first = Hypothesis("first", config())
    second = Hypothesis("second", config())
    assert first.configuration_fingerprint == second.configuration_fingerprint
    report = RobustnessRunner(dataset(), (first, second), WalkForwardConfig(6, 3, 3),
                              baseline_identifier="first").run()
    assert len(report.results) == 2
    assert report.results[1].baseline_difference.candidate_count_difference == 0


def test_strategy_parameter_change_changes_configuration_fingerprint():
    assert hypothesis_fingerprint(config()) != hypothesis_fingerprint(
        config("changed", swing_window=3))


def test_comparison_is_deterministic_ordered_and_reports_neutral_baseline_differences():
    runner = RobustnessRunner(dataset(), hypotheses(), WalkForwardConfig(6, 3, 3),
                              baseline_identifier="baseline")
    first, second = runner.run(), runner.run()
    assert first == second
    assert first.to_json() == second.to_json()
    assert [item.identifier for item in first.results] == [item.identifier
                                                          for item in hypotheses()]
    assert first.results[0].baseline_difference is None
    difference = first.results[1].baseline_difference
    assert difference.baseline_identifier == "baseline"
    assert difference.compared_window_count == 4


def test_holdout_and_future_changes_do_not_affect_prior_comparisons():
    windows = WalkForwardConfig(6, 3, 3, holdout_length=3)
    original = RobustnessRunner(dataset(), hypotheses(), windows,
                                baseline_identifier="baseline").run()
    changed = RobustnessRunner(dataset(last_close=500), hypotheses(), windows,
                               baseline_identifier="baseline").run()
    for left, right in zip(original.results, changed.results):
        assert left.report.development_results == right.report.development_results
        assert left.report.evaluation_results == right.report.evaluation_results


def test_predefined_sensitivity_is_descriptive_and_exposes_no_selection():
    report = RobustnessRunner(dataset(), hypotheses(), WalkForwardConfig(6, 3, 3),
                              baseline_identifier="baseline").run()
    assert not hasattr(report, "best")
    assert not hasattr(report, "winner")
    for result in report.results[1:]:
        difference = result.baseline_difference
        assert 0 <= difference.matching_window_sign_count <= difference.compared_window_count
