from dataclasses import replace
from itertools import permutations

import pytest

from strategy.confluence import Evidence, ResearchSignal, build_candidate_signal
from strategy.context import DealingRange, ote_band
from strategy.delivery import detect_delivery_legs
from strategy.fvg import detect_displacement, detect_fvgs, detect_ifvgs
from strategy.imbalance import Gap, evolve_gap, gap_lifecycle
from strategy.liquidity_v2 import LiquidityPool, build_swing_pools, track_liquidity
from strategy.structure import Candle, SwingPoint, detect_bos, structural_state


def c(o, h, l, close):
    return Candle(o, h, l, close)


def test_swing_availability_is_prefix_causal_at_exact_confirmation():
    swing = SwingPoint(1, 10, "high", "external", 3)
    candles = [c(9, 9, 8, 9), c(9, 10, 8, 9), c(9, 12, 8, 11), c(9, 12, 8, 11)]
    assert structural_state([swing], 2).external_high is None
    assert structural_state([swing], 3).external_high == swing
    assert detect_bos(candles[:3], [swing], []) == []
    assert detect_bos(candles, [swing], [])[0].index == 3


def test_equal_price_swings_keep_identity_and_each_break_only_once():
    first = SwingPoint(0, 10, "high", "external", 0)
    second = SwingPoint(2, 10, "high", "external", 2)
    candles = [c(9, 10, 8, 9), c(9, 11, 8, 10.5), c(10, 10, 9, 9.5),
               c(9.5, 11, 9, 10.5), c(10.5, 12, 10, 11)]
    events = detect_bos(candles, [first, second], [])
    assert [(e.index, e.broken_swing_index) for e in events] == [(1, 0), (3, 2)]


def test_liquidity_zero_window_breaks_at_penetration_without_future_data():
    pool = LiquidityPool("low", "sell_side", 10, (0,), 0)
    events = track_liquidity([c(10, 10, 10, 10), c(10, 10.1, 9.5, 9.7)],
                             [pool], max_reclaim_window=0)
    assert [e.event_type for e in events] == ["breach", "structural_break"]
    assert events[-1].index == events[-1].confirmation_index == 1
    with pytest.raises(ValueError):
        track_liquidity([], [pool], max_reclaim_window=-1)


def test_liquidity_window_two_remains_pending_then_reclaims_on_boundary():
    pool = LiquidityPool("low", "sell_side", 10, (0,), 0)
    prefix = [c(10, 10, 10, 10), c(10, 10.1, 9.5, 9.7), c(9.7, 9.9, 9.4, 9.6)]
    assert [e.event_type for e in track_liquidity(prefix, [pool], 2)] == ["breach"]
    complete = prefix + [c(9.6, 10.2, 9.5, 10.1)]
    assert track_liquidity(complete, [pool], 2)[-1].event_type == "reclaim_sweep"
    assert track_liquidity(complete, [pool], 2)[-1].confirmation_index == 3


def test_exact_level_close_is_not_a_wick_sweep_and_consumed_pool_is_ignored():
    pool = LiquidityPool("high", "buy_side", 10, (0,), 0)
    candles = [c(10, 10, 10, 10), c(9.8, 10.5, 9.5, 10)]
    events = track_liquidity(candles, [pool])
    assert len(events) == 1 and events[0].state == "touched"
    assert track_liquidity(candles, [replace(pool, state="consumed")]) == []


def test_liquidity_cannot_be_consumed_on_its_source_candle():
    pool = LiquidityPool("high", "buy_side", 10, (0,), 0)
    assert track_liquidity([c(9, 11, 8, 9)], [pool]) == []


def test_equal_pool_tolerance_is_absolute_and_zero_means_exact_only():
    highs = [SwingPoint(0, 100, "high", confirmed_at=1),
             SwingPoint(2, 100.01, "high", confirmed_at=3)]
    assert len(build_swing_pools(highs, [], 0)) == 2
    assert len(build_swing_pools(highs, [], .01)) == 1
    with pytest.raises(ValueError):
        build_swing_pools(highs, [], -.01)


@pytest.mark.parametrize("direction", ["bullish", "bearish"])
def test_gap_lifecycle_symmetry_boundaries_and_depth(direction):
    gap = Gap(0, direction, 10, 12)
    untouched = [c(0, 13, 12.1, 13)] if direction == "bullish" else [c(0, 9.9, 9, 9)]
    partial = c(12, 13, 11, 12) if direction == "bullish" else c(10, 11, 9, 10)
    full = c(11, 12, 10, 11) if direction == "bullish" else c(11, 12, 10, 11)
    invalid = c(11, 12, 9, 9) if direction == "bullish" else c(11, 13, 10, 13)
    assert evolve_gap(untouched, gap).state == "active"
    assert evolve_gap(untouched + [partial], gap).mitigation_fraction == .5
    assert evolve_gap(untouched + [full], gap).mitigation_fraction == 1
    invalidated = evolve_gap(untouched + [invalid], gap)
    assert invalidated.state == "invalidated" and invalidated.invalidated_at == 1
    assert all(0 <= state.mitigation_fraction <= 1 for state in gap_lifecycle(untouched + [partial], gap))


def test_gap_and_ifvg_exact_close_boundary_are_not_invalidation():
    bullish = [c(10, 10, 9, 9.5), c(10, 12, 10, 11.5), c(11, 13, 11, 12),
               c(11, 12, 9, 10)]
    gap = detect_fvgs(bullish)[0]
    assert detect_ifvgs(bullish, [gap]) == []
    assert evolve_gap(bullish, Gap(gap.index, gap.direction, gap.lower, gap.upper)).state == "mitigated"
    assert detect_ifvgs(bullish + [c(10, 10, 8, 9.9)], [gap])[0].index == 4
    with pytest.raises(ValueError):
        Gap(0, "bullish", 10, 10)


def test_zero_range_delivery_and_displacement_are_safe_and_deterministic():
    candles = [c(10, 10, 10, 10), c(10, 10, 10, 10), c(10, 11, 9, 10.8)]
    assert detect_displacement(candles, lookback=2) == []
    assert detect_delivery_legs(candles, min_candles=1) == detect_delivery_legs(candles, min_candles=1)


def test_context_rejects_malformed_values_and_ote_is_symmetric():
    with pytest.raises(ValueError):
        DealingRange(10, 10)
    rng = DealingRange(0, 100)
    with pytest.raises(ValueError):
        rng.position(50, -.1)
    with pytest.raises(ValueError):
        ote_band(rng, "bullish", .8, .2)
    assert ote_band(rng, "bullish", .2, .4) == (60, 80)
    assert ote_band(rng, "bearish", .2, .4) == (20, 40)


def test_duplicate_evidence_order_is_permutation_independent_and_non_executable():
    evidence = (Evidence("displacement", True, "z", index=4, source_id="b"),
                Evidence("displacement", True, "a", index=4, source_id="a"),
                Evidence("HTF context", True, "context", index=1))
    results = {build_candidate_signal(5, "bullish", order).evidence
               for order in permutations(evidence)}
    assert len(results) == 1
    signal = build_candidate_signal(5, "bullish", evidence)
    duplicate = Evidence("PD array", True, "same", index=4, source_id="gap")
    duplicated = build_candidate_signal(5, "bullish", (duplicate, duplicate))
    assert duplicated.evidence == (duplicate, duplicate)
    assert isinstance(signal, ResearchSignal)
    assert not hasattr(signal, "execute") and not hasattr(signal, "order")
