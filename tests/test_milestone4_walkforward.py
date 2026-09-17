import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from backtest.experiment import ExperimentConfig
from backtest.walkforward import (WalkForwardConfig, WalkForwardRunner,
                                  build_walk_forward_windows)
from data.historical import HistoricalCandle, HistoricalDataset
from strategy.engine import EngineConfig


def dataset(count=18, mutation=None):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = []
    for index in range(count):
        close = 100 + (index % 4) - 1
        values = (close, close + 2, close - 2, close + .5)
        if mutation and index == mutation[0]:
            values = mutation[1]
        candles.append(HistoricalCandle(start + timedelta(minutes=5 * (index + 1)),
                                        *values))
    return HistoricalDataset(tuple(candles), "walk-data")


def experiment():
    return ExperimentConfig(
        "walk", "walk-data", "5m",
        engine=EngineConfig(require_htf_bias=False, require_liquidity_event=False,
                            require_mss=False, require_displacement=False,
                            require_pd_array=False, require_price_zone=False),
    )


def test_rolling_and_anchored_windows_are_deterministic_and_half_open():
    source = dataset()
    rolling = build_walk_forward_windows(source, WalkForwardConfig(6, 3, 3))
    assert [(d.start_index, d.end_index, e.start_index, e.end_index)
            for d, e in rolling] == [(0, 6, 6, 9), (3, 9, 9, 12),
                                     (6, 12, 12, 15), (9, 15, 15, 18)]
    anchored = build_walk_forward_windows(source, WalkForwardConfig(6, 3, 3, True))
    assert [(d.start_index, d.end_index) for d, _ in anchored] == [
        (0, 6), (0, 9), (0, 12), (0, 15)]
    assert rolling == build_walk_forward_windows(source, WalkForwardConfig(6, 3, 3))
    assert rolling[0][0].last_timestamp < rolling[0][1].first_timestamp


def test_explicit_overlapping_evaluations_and_holdout_exclusion():
    pairs = build_walk_forward_windows(dataset(), WalkForwardConfig(5, 4, 2,
                                                                    holdout_length=3))
    assert [(e.start_index, e.end_index) for _, e in pairs] == [
        (5, 9), (7, 11), (9, 13), (11, 15)]
    assert all(e.end_index <= 15 for _, e in pairs)


@pytest.mark.parametrize("kwargs", [
    {"development_length": 0, "evaluation_length": 1, "step_length": 1},
    {"development_length": 1, "evaluation_length": -1, "step_length": 1},
    {"development_length": 1, "evaluation_length": 1, "step_length": 0},
    {"development_length": 1, "evaluation_length": 1, "step_length": 1,
     "holdout_length": -1},
])
def test_configuration_validation(kwargs):
    with pytest.raises(ValueError):
        WalkForwardConfig(**kwargs)
    with pytest.raises(ValueError, match="insufficient"):
        build_walk_forward_windows(dataset(5), WalkForwardConfig(4, 2, 1))
    with pytest.raises(ValueError, match="entire"):
        build_walk_forward_windows(dataset(5), WalkForwardConfig(1, 1, 1,
                                                                  holdout_length=5))


def test_results_are_immutable_reproducible_and_serialization_is_deterministic():
    config = WalkForwardConfig(6, 3, 3, holdout_length=3)
    first = WalkForwardRunner(dataset(), experiment(), config).run()
    second = WalkForwardRunner(dataset(), experiment(), config).run()
    assert first == second
    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json())["configuration"] == config.to_dict()
    assert len(first.development_results) == len(first.evaluation_results) == 3
    assert first.holdout_result.window.role == "holdout"
    with pytest.raises(FrozenInstanceError):
        first.evaluation_results[0].candidate_count = 9


def test_future_and_holdout_changes_cannot_affect_completed_earlier_windows():
    config = WalkForwardConfig(6, 3, 3, holdout_length=3)
    baseline = WalkForwardRunner(dataset(), experiment(), config).run()
    future_changed = WalkForwardRunner(
        dataset(mutation=(17, (500, 510, 490, 505))), experiment(), config).run()
    assert future_changed.development_results == baseline.development_results
    assert future_changed.evaluation_results == baseline.evaluation_results
    assert future_changed.holdout_result != baseline.holdout_result

    # A change in a later development span cannot alter already completed pair zero.
    later_changed = WalkForwardRunner(
        dataset(mutation=(10, (200, 210, 190, 205))), experiment(), config).run()
    assert later_changed.development_results[0] == baseline.development_results[0]
    assert later_changed.evaluation_results[0] == baseline.evaluation_results[0]


def test_appending_future_candles_does_not_change_existing_completed_pairs():
    config = WalkForwardConfig(6, 3, 3)
    prefix = WalkForwardRunner(dataset(15), experiment(), config).run()
    full = WalkForwardRunner(dataset(18), experiment(), config).run()
    assert full.development_results[:len(prefix.development_results)] == prefix.development_results
    assert full.evaluation_results[:len(prefix.evaluation_results)] == prefix.evaluation_results


def test_report_distinguishes_roles_and_describes_evaluation_statistics():
    report = WalkForwardRunner(dataset(), experiment(),
                               WalkForwardConfig(6, 3, 3, holdout_length=3)).run()
    assert all(item.window.role == "development" for item in report.development_results)
    assert all(item.window.role == "evaluation" for item in report.evaluation_results)
    assert report.holdout_result.window.role == "holdout"
    stats = report.evaluation_statistics
    assert stats.window_count == len(report.evaluation_results)
    assert stats.positive_windows + stats.negative_windows + stats.flat_windows == stats.window_count
    assert stats.resolved_observations == sum(item.metrics.resolved
                                              for item in report.evaluation_results)
