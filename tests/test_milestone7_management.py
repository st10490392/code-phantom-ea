from datetime import UTC, datetime, timedelta

import pytest

from backtest.management import (ManagementConfig, PartialObjective,
                                 simulate_managed_candidates)
from backtest.simulator import HypotheticalLevels
from strategy.confluence import ResearchSignal
from strategy.structure import Candle


def signal(index=0, direction="bullish"):
    return ResearchSignal(index, direction, ())


def levels(item):
    return (HypotheticalLevels(100, 99, 102) if item.direction == "bullish"
            else HypotheticalLevels(100, 101, 98))


def candles(*values):
    return tuple(Candle(*item) for item in values)


def test_partial_then_objective_fractional_r():
    history = candles((100, 100.2, 99.8, 100), (100, 101.2, 99.9, 101),
                      (101, 102.2, 100.8, 102))
    result = simulate_managed_candidates(
        history, (signal(),), levels,
        ManagementConfig(2, PartialObjective(1, .5)))[0]
    assert result.outcome == "win"
    assert result.normalized_r == 1.5
    assert [item.reason for item in result.realized_fractions] == [
        "partial_objective", "objective"]


def test_partial_then_invalidation_and_break_even():
    history = candles((100, 100.2, 99.8, 100), (100, 101.2, 99.9, 101),
                      (101, 101.1, 98.8, 99))
    partial_loss = simulate_managed_candidates(
        history, (signal(),), levels, ManagementConfig(2, PartialObjective(1, .5)))[0]
    assert partial_loss.normalized_r == 0.0
    break_even = simulate_managed_candidates(
        history, (signal(),), levels,
        ManagementConfig(2, PartialObjective(1, .5), True))[0]
    assert break_even.normalized_r == .5


def test_conservative_same_candle_never_chooses_favorable_path():
    history = candles((100, 100, 100, 100), (100, 102.1, 98.9, 100))
    conservative = simulate_managed_candidates(
        history, (signal(),), levels, ManagementConfig(2))[0]
    favorable = simulate_managed_candidates(
        history, (signal(),), levels, ManagementConfig(2,
                                                       ambiguity_policy="favorable"))[0]
    assert conservative.normalized_r == -1
    assert favorable.normalized_r == 2


def test_trailing_uses_completed_close_only_on_next_candle():
    history = candles((100, 100, 100, 100), (100, 101.8, 99.5, 101.5),
                      (101.5, 101.6, 100.4, 100.5))
    result = simulate_managed_candidates(
        history, (signal(),), levels, ManagementConfig(3, trailing_distance_r=.5))[0]
    assert result.outcome == "win"
    assert result.normalized_r == 1.0  # stop moved to 101 after candle 1 completed
    assert result.resolved_index == 2


def test_expiry_and_tp1_only_are_deterministic():
    history = candles((100, 100, 100, 100), (100, 101.1, 99.8, 101),
                      (101, 101.2, 100.5, 101))
    result = simulate_managed_candidates(
        history, (signal(),), levels,
        ManagementConfig(3, PartialObjective(1, .25), max_bars=2))[0]
    assert result.outcome == "expired"
    assert result.normalized_r == .25
    assert result.bars_elapsed == 2


def test_bullish_bearish_symmetry_and_gaps():
    bullish = candles((100, 100, 100, 100), (102.5, 102.5, 102.2, 102.4))
    bearish = candles((100, 100, 100, 100), (97.5, 97.8, 97.5, 97.6))
    config = ManagementConfig(2)
    assert simulate_managed_candidates(bullish, (signal(),), levels,
                                       config)[0].normalized_r == 2
    assert simulate_managed_candidates(bearish, (signal(direction="bearish"),), levels,
                                       config)[0].normalized_r == 2


def test_daily_controls_skip_later_same_day_and_reset_next_day():
    history = candles((100, 100, 100, 100), (100, 102.1, 99.9, 102),
                      (100, 100, 100, 100), (100, 102.1, 99.9, 102),
                      (100, 100, 100, 100), (100, 102.1, 99.9, 102))
    start = datetime(2026, 1, 1, 10, tzinfo=UTC)
    times = tuple(start + timedelta(minutes=5 * i) for i in range(4)) + (
        datetime(2026, 1, 2, 10, tzinfo=UTC),
        datetime(2026, 1, 2, 10, 5, tzinfo=UTC))
    results = simulate_managed_candidates(
        history, (signal(0), signal(2), signal(4)), levels,
        ManagementConfig(2, daily_gain_boundary_r=2), timestamps=times)
    assert [item.outcome for item in results] == ["win", "skipped", "win"]


def test_signal_candle_and_future_data_do_not_move_historical_trailing_stop():
    prefix = candles((100, 500, 1, 100), (100, 101.8, 99.5, 101.5),
                     (101.5, 101.6, 100.4, 100.5))
    first = simulate_managed_candidates(prefix, (signal(),), levels,
                                        ManagementConfig(3, trailing_distance_r=.5))[0]
    extended = prefix + candles((100, 1000, 1, 999),)
    second = simulate_managed_candidates(extended, (signal(),), levels,
                                         ManagementConfig(3, trailing_distance_r=.5,
                                                          max_bars=2))[0]
    assert first == second


def test_invalid_management_configuration_and_daily_timestamps():
    with pytest.raises(ValueError):
        PartialObjective(1, 1)
    with pytest.raises(ValueError):
        ManagementConfig(1, PartialObjective(1, .5))
    with pytest.raises(ValueError):
        ManagementConfig(1, ambiguity_policy="unknown")
    with pytest.raises(ValueError, match="timestamps"):
        simulate_managed_candidates(candles((100, 100, 100, 100)), (signal(),),
                                    levels, ManagementConfig(2, daily_loss_boundary_r=1))
