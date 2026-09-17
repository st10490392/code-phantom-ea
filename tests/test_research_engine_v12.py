from strategy.confluence import Evidence, build_candidate_signal
from strategy.context import DealingRange, ote_band
from strategy.delivery import detect_delivery_legs
from strategy.imbalance import detect_gaps, gap_lifecycle
from strategy.liquidity_v2 import build_swing_pools, track_liquidity
from strategy.structure import (Candle, SwingPoint, classify_structure, detect_bos,
                                detect_structure_shift, structural_state)

def c(o, h, l, close):
    return Candle(o, h, l, close)

def test_internal_swing_does_not_replace_external_extreme():
    swings = [SwingPoint(0, 10, "high", confirmed_at=0),
              SwingPoint(2, 15, "high", confirmed_at=2),
              SwingPoint(4, 12, "high", confirmed_at=4),
              SwingPoint(6, 14, "high", confirmed_at=6)]
    classified = classify_structure(swings)
    assert [s.structure for s in classified] == ["internal", "external", "internal", "internal"]
    assert structural_state(classified, 7).external_high.index == 2

def test_exact_confirmation_boundary_has_no_lookahead():
    high = SwingPoint(1, 10, "high", "external", confirmed_at=3)
    candles = [c(8, 9, 7, 8), c(8, 10, 7, 9), c(9, 12, 8, 11), c(9, 12, 8, 11)]
    assert detect_bos(candles[:3], [high], []) == []
    assert detect_bos(candles, [high], [])[0].index == 3

def test_large_four_candle_leg_retains_displacement_evidence():
    candles = [c(10, 10.5, 9.8, 10.3), c(10.3, 10.8, 10.2, 10.7),
               c(10.7, 12.5, 10.6, 12.3), c(12.3, 13, 12.2, 12.9)]
    leg = detect_delivery_legs(candles, displacement_lookback=2)[0]
    assert leg.candle_count == 4 and round(leg.net_movement, 8) == 2.9
    assert leg.displacement_indices == (2,)

def test_bos_audits_exact_swing_identity_and_side():
    candles = [c(10, 11, 9, 10), c(10, 12, 9, 11), c(11, 13, 10, 12)]
    high = SwingPoint(0, 11, "high", "external", 0)
    low = SwingPoint(0, 9, "low", "external", 0)
    events = detect_bos(candles, [high], [low])
    assert (events[0].broken_swing_index, events[0].broken_side) == (0, "high")

def test_valid_mss_breaks_relevant_side_not_unrelated_level():
    candles = [c(10, 10.5, 8.5, 10), c(10, 10.2, 7.5, 8), c(8, 11.5, 7.8, 11)]
    high = SwingPoint(0, 10.5, "high", "external", 0)
    low = SwingPoint(0, 8.5, "low", "external", 0)
    shift = detect_structure_shift(candles, [high], [low])[0]
    assert shift.direction == "bullish" and shift.broken_side == "high"
    assert shift.broken_level == 10.5 and shift.broken_swing_index == 0

def test_no_shift_without_prior_opposing_structural_break():
    candles = [c(9, 9.5, 8, 9), c(9, 11, 8.5, 10.8)]
    high = SwingPoint(0, 9.5, "high", "external", 0)
    assert detect_structure_shift(candles, [high], []) == []

def test_wick_reclaim_break_and_no_repeated_consumption():
    low = SwingPoint(0, 10, "low", "external", 0)
    pool = build_swing_pools([], [low])
    source = c(10, 10, 10, 10)
    wick = track_liquidity([source, c(10.2, 10.3, 9.7, 10.1), c(10.1, 10.2, 9.6, 10.1)], pool)
    assert len(wick) == 1 and wick[0].event_type == "wick_sweep"
    reclaim = track_liquidity([source, c(10.2, 10.3, 9.7, 9.8), c(9.8, 10.2, 9.7, 10.1)], pool)
    assert reclaim[-1].event_type == "reclaim_sweep" and reclaim[-1].confirmation_index == 2
    broken = track_liquidity([source, c(10.2, 10.3, 9.7, 9.8), c(9.8, 9.9, 9.5, 9.6)], pool)
    assert broken[-1].event_type == "structural_break"

def test_equal_high_and_low_pools_use_explicit_tolerance():
    highs = [SwingPoint(0, 10, "high", confirmed_at=1), SwingPoint(2, 10.04, "high", confirmed_at=3)]
    lows = [SwingPoint(1, 5, "low", confirmed_at=2), SwingPoint(3, 5.03, "low", confirmed_at=4)]
    pools = build_swing_pools(highs, lows, tolerance=0.05)
    assert sorted(len(p.source_indices) for p in pools) == [2, 2]

def test_fvg_lifecycle_is_causal_and_deterministic():
    candles = [c(10, 10.5, 9.8, 10.4), c(10.4, 12, 10.3, 11.8),
               c(11.8, 12.2, 11, 12), c(12, 12.1, 10.7, 11.2),
               c(11.2, 11.3, 10.3, 10.4)]
    gap = detect_gaps(candles)[0]
    states = [snapshot.state for snapshot in gap_lifecycle(candles, gap)]
    assert states[0] == "new" and "partial" in states and states[-1] in {"mitigated", "invalidated"}
    assert gap_lifecycle(candles, gap) == gap_lifecycle(candles, gap)

def test_context_boundaries_and_configurable_ote():
    rng = DealingRange(100, 200)
    assert rng.position(150) == "equilibrium"
    assert rng.position(149.99) == "discount" and rng.position(150.01) == "premium"
    assert ote_band(rng, "bullish", .5, .75) == (125, 150)

def test_evidence_pipeline_has_canonical_order_and_is_deterministic():
    evidence = [Evidence("displacement", True, "expanded", index=8),
                Evidence("HTF context", True, "bullish", index=2),
                Evidence("liquidity event", True, "reclaimed", index=6),
                Evidence("candidate setup", True, "complete", index=10)]
    first = build_candidate_signal(10, "bullish", evidence)
    second = build_candidate_signal(10, "bullish", evidence)
    assert [e.name for e in first.evidence] == ["HTF context", "liquidity event", "displacement", "candidate setup"]
    assert first == second
