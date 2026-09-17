from dataclasses import FrozenInstanceError

import pytest

from backtest.simulator import (HypotheticalLevels, SimulationResult,
                                calculate_metrics, simulate_candidates)
from strategy.confluence import Evidence, ResearchSignal
from strategy.engine import EngineConfig, SequentialResearchEngine
from strategy.structure import Candle
from strategy.timeframes import ContextSeries, align_completed_candle


def c(o, h, l, close):
    return Candle(o, h, l, close)


def signal(index=0, direction="bullish"):
    return ResearchSignal(index, direction, (
        Evidence("candidate setup", True, "audited", index=index),
    ))


def relaxed_config():
    return EngineConfig(
        swing_window=1, displacement_lookback=1,
        displacement_range_multiple=1, displacement_body_ratio=.5,
        require_htf_bias=False, require_liquidity_event=False,
        require_pd_array=False, require_price_zone=False,
    )


BASE = (
    c(9, 10, 8, 9), c(9, 9.5, 7, 8), c(8, 11, 8, 10),
    c(10, 10.5, 6, 6.5), c(6.5, 12, 6.2, 11.5),
)


def test_mtf_exact_equality_visible_one_unit_later_invisible():
    execution = ContextSeries((c(1, 2, 0, 1),), "exec", (10,))
    htf = ContextSeries((c(1, 2, 0, 1), c(1, 100, -100, 50)),
                        "htf", (10, 11))
    alignment = align_completed_candle(execution, htf, 0)
    assert alignment.higher_timeframe_index == 0
    assert alignment.higher_timeframe_timestamp == 10


def test_future_htf_append_cannot_change_complete_snapshot():
    execution = ContextSeries(BASE, "exec", (2, 4, 6, 8, 10))
    past_htf = ContextSeries((c(10, 11, 9, 10),), "htf", (10,))
    future_htf = ContextSeries(
        (c(10, 11, 9, 10), c(10, 1000, -1000, 900)), "htf", (10, 11)
    )
    past = SequentialResearchEngine(execution, past_htf, relaxed_config()).run()[-1]
    future = SequentialResearchEngine(execution, future_htf, relaxed_config()).run()[-1]
    assert past == future


def test_future_execution_cannot_change_stopped_snapshot_or_complete_signal():
    prefix = ContextSeries(BASE, "exec", (1, 2, 3, 4, 5))
    complete = ContextSeries(
        BASE + (c(20, 50, 1, 40), c(40, 60, -10, 0)),
        "exec", (1, 2, 3, 4, 5, 6, 7),
    )
    expected = SequentialResearchEngine(prefix, config=relaxed_config()).run()[-1]
    engine = SequentialResearchEngine(complete, config=relaxed_config())
    actual = tuple(engine.advance() for _ in range(len(BASE)))[-1]
    assert actual == expected
    assert actual.signal == expected.signal
    assert actual.evidence == expected.evidence


def test_timestamp_duplicates_unsorted_and_execution_reversal_rejected():
    candle_pair = (c(1, 2, 0, 1),) * 2
    for timestamps in ((1, 1), (2, 1)):
        with pytest.raises(ValueError, match="strictly increasing"):
            ContextSeries(candle_pair, "exec", timestamps)
        with pytest.raises(ValueError, match="strictly increasing"):
            ContextSeries(candle_pair, "htf", timestamps)


def test_original_execution_and_htf_lists_cannot_mutate_snapshot():
    execution_candles = list(BASE)
    execution_times = [1, 2, 3, 4, 5]
    htf_candles = [c(10, 11, 9, 10)]
    htf_times = [5]
    execution = ContextSeries(execution_candles, "exec", execution_times)
    htf = ContextSeries(htf_candles, "htf", htf_times)
    engine = SequentialResearchEngine(execution, htf, relaxed_config())
    snapshot = engine.run()[-1]
    preserved = snapshot
    execution_candles.append(c(0, 100, -100, 50))
    execution_times.append(6)
    htf_candles.append(c(0, 100, -100, 50))
    htf_times.append(6)
    assert snapshot == preserved
    assert len(engine.snapshots) == len(BASE)
    assert isinstance(snapshot.evidence, tuple)
    with pytest.raises((AttributeError, TypeError)):
        snapshot.evidence.append(Evidence("x", True, "x"))
    with pytest.raises(FrozenInstanceError):
        snapshot.signal.index = 100


@pytest.mark.parametrize(("direction", "levels", "objective", "invalidation"), (
    ("bullish", HypotheticalLevels(10, 9, 11), c(10, 11.5, 9.5, 11), c(10, 10.5, 8.5, 9)),
    ("bearish", HypotheticalLevels(10, 11, 9), c(10, 10.5, 8.5, 9), c(10, 11.5, 9.5, 11)),
))
def test_objective_first_and_invalidation_first_are_directionally_symmetric(
        direction, levels, objective, invalidation):
    base = c(10, 10, 10, 10)
    win = simulate_candidates((base, objective, invalidation),
                              (signal(direction=direction),), lambda _: levels)[0]
    loss = simulate_candidates((base, invalidation, objective),
                               (signal(direction=direction),), lambda _: levels)[0]
    assert (win.outcome, win.resolved_index, win.bars_elapsed) == ("win", 1, 1)
    assert (loss.outcome, loss.resolved_index, loss.bars_elapsed) == ("loss", 1, 1)


@pytest.mark.parametrize(("direction", "levels"), (
    ("bullish", HypotheticalLevels(10, 9, 11)),
    ("bearish", HypotheticalLevels(10, 11, 9)),
))
def test_signal_and_prior_candles_are_never_outcome_candles(direction, levels):
    extreme = c(10, 20, 0, 10)
    quiet = c(10, 10.5, 9.5, 10)
    result = simulate_candidates(
        (extreme, extreme, quiet), (signal(1, direction),), lambda _: levels
    )[0]
    assert result.outcome == "unresolved" and result.bars_elapsed == 1


@pytest.mark.parametrize(("direction", "levels", "both"), (
    ("bullish", HypotheticalLevels(10, 9, 11), c(10, 12, 8, 10)),
    ("bearish", HypotheticalLevels(10, 11, 9), c(10, 12, 8, 10)),
))
def test_both_touched_defaults_to_loss_and_optimism_is_explicit(direction, levels, both):
    candles = (c(10, 10, 10, 10), both)
    default = simulate_candidates(candles, (signal(direction=direction),), lambda _: levels)[0]
    explicit = simulate_candidates(
        candles, (signal(direction=direction),), lambda _: levels,
        same_candle_policy="optimistic",
    )[0]
    assert default.outcome == "loss" and default.normalized_r == -1
    assert explicit.outcome == "win"


@pytest.mark.parametrize(("direction", "levels", "objective_gap", "invalidation_gap"), (
    ("bullish", HypotheticalLevels(10, 9, 11), c(12, 13, 12, 12.5), c(8, 8, 7, 7.5)),
    ("bearish", HypotheticalLevels(10, 11, 9), c(8, 8, 7, 7.5), c(12, 13, 12, 12.5)),
))
def test_open_gaps_use_completed_ohlc_thresholds_symmetrically(
        direction, levels, objective_gap, invalidation_gap):
    base = c(10, 10, 10, 10)
    objective = simulate_candidates((base, objective_gap),
                                    (signal(direction=direction),), lambda _: levels)[0]
    invalidation = simulate_candidates((base, invalidation_gap),
                                       (signal(direction=direction),), lambda _: levels)[0]
    assert objective.outcome == "win"
    assert invalidation.outcome == "loss"


@pytest.mark.parametrize(("direction", "levels", "gap_then_both"), (
    ("bullish", HypotheticalLevels(10, 9, 11), c(12, 13, 8, 10)),
    ("bearish", HypotheticalLevels(10, 11, 9), c(8, 12, 7, 10)),
))
def test_open_beyond_objective_does_not_override_conservative_both_touch(
        direction, levels, gap_then_both):
    result = simulate_candidates(
        (c(10, 10, 10, 10), gap_then_both),
        (signal(direction=direction),), lambda _: levels,
    )[0]
    assert result.outcome == "loss" and result.normalized_r == -1


@pytest.mark.parametrize(("direction", "values"), (
    ("bullish", ((10, 10, 11), (10, 9, 10))),
    ("bearish", ((10, 10, 9), (10, 11, 10))),
))
def test_level_equality_rejected(direction, values):
    for entry, invalidation, objective in values:
        with pytest.raises(ValueError, match="strictly between"):
            HypotheticalLevels(entry, invalidation, objective).validate(direction)


@pytest.mark.parametrize("bad", (float("nan"), float("inf"), float("-inf")))
@pytest.mark.parametrize("field", ("entry", "invalidation", "objective"))
def test_every_non_finite_level_field_is_rejected(bad, field):
    values = {"entry": 10, "invalidation": 9, "objective": 11}
    values[field] = bad
    with pytest.raises(ValueError, match="finite"):
        HypotheticalLevels(**values).validate("bullish")


def test_malformed_direction_and_policy_are_rejected():
    with pytest.raises(ValueError, match="direction"):
        HypotheticalLevels(10, 9, 11).validate("sideways")
    with pytest.raises(ValueError, match="same_candle_policy"):
        simulate_candidates((), (), lambda _: HypotheticalLevels(10, 9, 11),
                            same_candle_policy="unknown")


def result(outcome, r, index):
    return SimulationResult(index, "bullish", 10, 9, 11, outcome, 1, r,
                            None if outcome == "unresolved" else index + 1,
                            signal(index))


def test_metrics_all_wins_all_losses_zero_resolved_and_initial_baseline():
    all_wins = calculate_metrics((result("win", 2, 0), result("win", 1, 2)))
    assert all_wins.cumulative_r == 3 and all_wins.average_r == 1.5
    assert all_wins.expectancy_r == 1.5 and all_wins.maximum_drawdown_r == 0
    assert all_wins.longest_win_streak == 2 and all_wins.longest_loss_streak == 0
    all_losses = calculate_metrics((result("loss", -1, 0), result("loss", -1, 2)))
    assert all_losses.cumulative_r == -2 and all_losses.average_r == -1
    assert all_losses.maximum_drawdown_r == 2  # initial equity peak is zero
    assert all_losses.longest_loss_streak == 2 and all_losses.longest_win_streak == 0
    unresolved = calculate_metrics((result("unresolved", None, 0),))
    assert unresolved.resolved == 0 and unresolved.unresolved == 1
    assert unresolved.win_rate == unresolved.average_r == unresolved.expectancy_r == 0


def test_unresolved_excluded_and_drawdown_hand_calculation():
    sequence = (
        result("win", 2, 0), result("unresolved", None, 2),
        result("loss", -1, 4), result("loss", -1, 6), result("win", 1, 8),
    )
    metrics = calculate_metrics(sequence)
    assert metrics.resolved == 4 and metrics.unresolved == 1
    assert metrics.cumulative_r == 1 and metrics.average_r == metrics.expectancy_r == .25
    assert metrics.maximum_drawdown_r == 2
    assert metrics.longest_win_streak == 1 and metrics.longest_loss_streak == 2


def test_complete_outputs_are_repeatably_deterministic():
    execution = ContextSeries(BASE, "exec", (1, 2, 3, 4, 5))
    htf = ContextSeries((c(10, 11, 9, 10),), "htf", (5,))
    first = SequentialResearchEngine(execution, htf, relaxed_config()).run()
    second = SequentialResearchEngine(execution, htf, relaxed_config()).run()
    assert first == second and first[-1].signal == second[-1].signal
    candidates = tuple(snapshot.signal for snapshot in first if snapshot.signal)
    levels = lambda item: (HypotheticalLevels(10, 9, 11)
                           if item.direction == "bullish"
                           else HypotheticalLevels(10, 11, 9))
    candles = execution.candles + (c(10, 12, 8, 10),)
    simulations_a = simulate_candidates(candles, candidates, levels)
    simulations_b = simulate_candidates(candles, candidates, levels)
    assert simulations_a == simulations_b
    assert calculate_metrics(simulations_a) == calculate_metrics(simulations_b)
