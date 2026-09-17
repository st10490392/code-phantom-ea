from dataclasses import FrozenInstanceError

import pytest

from backtest.simulator import (HypotheticalLevels, SimulationResult,
                                calculate_metrics, simulate_candidates)
from strategy.confluence import Evidence, ResearchSignal
from strategy.engine import EngineConfig, SequentialResearchEngine
from strategy.structure import Candle
from strategy.timeframes import (ContextSeries, align_completed_candle)


def c(o, h, l, close):
    return Candle(o, h, l, close)


BULLISH_MSS = (
    c(9, 10, 8, 9),
    c(9, 9.5, 7, 8),
    c(8, 11, 8, 10),
    c(10, 10.5, 6, 6.5),
    c(6.5, 12, 6.2, 11.5),
)


def mirror(candles, pivot=20):
    return tuple(c(pivot-x.open, pivot-x.low, pivot-x.high, pivot-x.close)
                 for x in candles)


def candidate_config():
    return EngineConfig(
        swing_window=1, displacement_lookback=1,
        displacement_range_multiple=1.0, displacement_body_ratio=.5,
        require_htf_bias=False, require_liquidity_event=False,
        require_pd_array=False, require_price_zone=False,
    )


def test_alignment_uses_only_latest_completed_htf_boundary():
    execution = ContextSeries((c(0, 1, 0, 1),) * 3, "exec", (1, 2, 3))
    htf = ContextSeries((c(0, 1, 0, 1),) * 2, "higher", (2, 4))
    assert align_completed_candle(execution, htf, 0).higher_timeframe_index is None
    assert align_completed_candle(execution, htf, 1).higher_timeframe_index == 0
    assert align_completed_candle(execution, htf, 2).higher_timeframe_index == 0


def test_mtf_rejects_missing_or_unsorted_timestamps():
    execution = ContextSeries((c(0, 1, 0, 1),), "exec")
    htf = ContextSeries((c(0, 1, 0, 1),), "higher", (1,))
    with pytest.raises(ValueError, match="timestamps"):
        SequentialResearchEngine(execution, htf)
    with pytest.raises(ValueError, match="strictly increasing"):
        ContextSeries((c(0, 1, 0, 1),) * 2, timestamps=(1, 1))


def test_context_series_freezes_mutable_caller_inputs():
    candles = [c(0, 1, 0, 1)]
    timestamps = [1]
    series = ContextSeries(candles, "exec", timestamps)
    candles.append(c(1, 2, 1, 2))
    timestamps.append(2)
    assert len(series.candles) == len(series.timestamps) == 1
    assert isinstance(series.candles, tuple) and isinstance(series.timestamps, tuple)


def test_neutral_htf_is_not_fabricated():
    execution = ContextSeries((c(1, 2, 0, 1),), "exec", (2,))
    htf = ContextSeries((c(1, 2, 0, 1),), "higher", (2,))
    snapshot = SequentialResearchEngine(execution, htf).advance()
    assert snapshot.htf_context.bias == "neutral"
    assert snapshot.htf_context.most_recent_event is None


@pytest.mark.parametrize(("candles", "direction"),
                         ((BULLISH_MSS, "bullish"), (mirror(BULLISH_MSS), "bearish")))
def test_bullish_and_bearish_candidates_are_symmetric_and_auditable(candles, direction):
    series = ContextSeries(candles, "exec")
    snapshots = SequentialResearchEngine(series, config=candidate_config()).run()
    signal = snapshots[-1].signal
    assert signal is not None and signal.direction == direction and signal.index == 4
    assert [item.name for item in signal.evidence][-1] == "candidate setup"
    assert any(item.name == "structural shift" and item.passed for item in signal.evidence)
    with pytest.raises(FrozenInstanceError):
        signal.index = 99
    with pytest.raises(FrozenInstanceError):
        snapshots[-1].execution_index = 99


def test_no_candidate_before_required_mss_and_evidence_is_deterministic():
    engine = SequentialResearchEngine(ContextSeries(BULLISH_MSS, "exec"),
                                      config=candidate_config())
    snapshots = engine.run()
    assert all(snapshot.signal is None for snapshot in snapshots[:-1])
    again = SequentialResearchEngine(ContextSeries(BULLISH_MSS, "exec"),
                                     config=candidate_config()).run()
    assert snapshots == again


def test_mss_can_be_explicitly_optional_without_hidden_requirement():
    config = EngineConfig(
        displacement_lookback=1, displacement_range_multiple=1,
        displacement_body_ratio=.5, require_htf_bias=False,
        require_liquidity_event=False, require_mss=False,
        require_pd_array=False, require_price_zone=False,
    )
    candles = (c(10, 10.5, 9.5, 10), c(10, 12, 9.8, 11.8))
    signal = SequentialResearchEngine(ContextSeries(candles), config=config).run()[-1].signal
    assert signal is not None and signal.direction == "bullish"
    structural = next(e for e in signal.evidence if e.name == "structural shift")
    assert not structural.passed


def test_prefix_invariance_with_future_execution_and_htf_data():
    execution = ContextSeries(BULLISH_MSS + (c(12, 30, 1, 25),), "exec",
                              (1, 2, 3, 4, 5, 6))
    htf = ContextSeries((c(10, 11, 9, 10), c(10, 50, 1, 40)), "higher", (3, 9))
    full = SequentialResearchEngine(execution, htf, candidate_config()).run()
    for index, expected in enumerate(full):
        prefix = execution.prefix(index)
        actual = SequentialResearchEngine(prefix, htf, candidate_config()).run()[-1]
        assert actual == expected


def test_empty_engine_is_safe():
    assert SequentialResearchEngine(ContextSeries((), "exec")).run() == ()


def signal(index=0, direction="bullish"):
    return ResearchSignal(index, direction,
                          (Evidence("candidate setup", True, "research only", index=index),))


def test_same_candle_policy_defaults_conservative_and_is_symmetric():
    candles = (c(10, 10, 10, 10), c(10, 12, 8, 10))
    bullish_levels = lambda _: HypotheticalLevels(10, 9, 11)
    conservative = simulate_candidates(candles, (signal(),), bullish_levels)
    optimistic = simulate_candidates(candles, (signal(),), bullish_levels,
                                     same_candle_policy="optimistic")
    assert conservative[0].outcome == "loss" and conservative[0].normalized_r == -1
    assert optimistic[0].outcome == "win" and optimistic[0].normalized_r == 1
    bearish = simulate_candidates(
        candles, (signal(direction="bearish"),),
        lambda _: HypotheticalLevels(10, 11, 9),
    )
    assert bearish[0].outcome == "loss"


def test_simulation_starts_after_candidate_and_can_remain_unresolved():
    candles = (c(10, 20, 1, 10), c(10, 10.5, 9.5, 10))
    result = simulate_candidates(
        candles, (signal(),), lambda _: HypotheticalLevels(10, 9, 11)
    )[0]
    assert result.outcome == "unresolved" and result.bars_elapsed == 1
    assert result.resolved_index is None and result.normalized_r is None


def test_malformed_hypothetical_levels_and_limits_are_rejected():
    candles = (c(10, 10, 10, 10),)
    with pytest.raises(ValueError, match="strictly between"):
        simulate_candidates(candles, (signal(),),
                            lambda _: HypotheticalLevels(10, 11, 12))
    with pytest.raises(ValueError, match="max_bars"):
        simulate_candidates(candles, (), lambda _: HypotheticalLevels(10, 9, 11),
                            max_bars=0)
    with pytest.raises(ValueError, match="finite"):
        simulate_candidates(candles, (signal(),),
                            lambda _: HypotheticalLevels(10, 9, float("inf")))


def test_metrics_and_empty_metrics_are_deterministic():
    item = signal()
    results = (
        SimulationResult(0, "bullish", 10, 9, 12, "win", 1, 2.0, 1, item),
        SimulationResult(2, "bullish", 10, 9, 12, "loss", 1, -1.0, 3, item),
        SimulationResult(4, "bullish", 10, 9, 11, "loss", 1, -1.0, 5, item),
        SimulationResult(6, "bullish", 10, 9, 11, "win", 1, 1.0, 7, item),
        SimulationResult(8, "bullish", 10, 9, 11, "unresolved", 2, None, None, item),
    )
    metrics = calculate_metrics(results)
    assert (metrics.total_candidates, metrics.resolved, metrics.unresolved) == (5, 4, 1)
    assert (metrics.wins, metrics.losses, metrics.win_rate) == (2, 2, .5)
    assert metrics.average_r == metrics.expectancy_r == .25
    assert metrics.cumulative_r == 1 and metrics.maximum_drawdown_r == 2
    assert metrics.longest_win_streak == 1 and metrics.longest_loss_streak == 2
    empty = calculate_metrics(())
    assert empty.total_candidates == empty.resolved == 0
    assert empty.win_rate == empty.average_r == empty.maximum_drawdown_r == 0
