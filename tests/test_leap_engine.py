from strategy.structure import Candle, SwingPoint
from strategy.delivery import detect_delivery_legs, detect_cisd
from strategy.liquidity_v2 import build_swing_pools, track_liquidity
from strategy.imbalance import detect_gaps, evolve_gap
from strategy.context import DealingRange, ote_band
from strategy.confluence import Evidence, ResearchSignal


def c(o, h, l, cl):
    return Candle(o, h, l, cl)


def test_delivery_leg_does_not_need_fractal_pivot():
    candles = [
        c(10, 11.2, 9.8, 11),
        c(11, 12.4, 10.9, 12.2),
        c(12.2, 13.5, 12, 13.2),
        c(13.2, 14.5, 13, 14.3),
    ]
    legs = detect_delivery_legs(candles)
    assert len(legs) == 1
    assert legs[0].direction == "bullish"
    assert legs[0].start == 0 and legs[0].end == 3


def test_bullish_cisd_reclaims_bearish_run_open():
    candles = [
        c(10, 10.1, 9.2, 9.4),
        c(9.4, 9.5, 8.8, 9.0),
        c(9.0, 10.4, 8.9, 10.2),
    ]
    events = detect_cisd(candles)
    assert any(e.direction == "bullish" and e.index == 2 and e.reference_open == 10 for e in events)


def test_wick_sweep_and_body_reclaim_are_distinct():
    low = SwingPoint(0, 10.0, "low", confirmed_at=0)
    pools = build_swing_pools([], [low])
    wick = [c(10.2, 10.4, 9.8, 10.1)]
    assert track_liquidity(wick, pools)[0].state == "wick_swept"

    body_then_reclaim = [
        c(10.2, 10.3, 9.7, 9.8),
        c(9.8, 10.3, 9.7, 10.2),
    ]
    states = [e.state for e in track_liquidity(body_then_reclaim, pools)]
    assert states == ["body_breached", "reclaimed"]


def test_body_acceptance_is_not_relabelled_as_sweep():
    low = SwingPoint(0, 10.0, "low", confirmed_at=0)
    pools = build_swing_pools([], [low])
    candles = [
        c(10.1, 10.2, 9.7, 9.8),
        c(9.8, 9.9, 9.4, 9.5),
    ]
    assert [e.state for e in track_liquidity(candles, pools)] == ["body_breached", "accepted_beyond"]


def test_fvg_lifecycle():
    candles = [
        c(10, 10.5, 9.8, 10.4),
        c(10.4, 12, 10.3, 11.8),
        c(11.8, 12.2, 11.0, 12.0),
        c(12.0, 12.1, 10.7, 11.2),
    ]
    gap = detect_gaps(candles)[0]
    evolved = evolve_gap(candles, gap)
    assert gap.direction == "bullish"
    assert evolved.state in {"partial", "mitigated"}


def test_dealing_range_geometry():
    rng = DealingRange(100, 200)
    assert rng.equilibrium == 150
    assert rng.position(125) == "discount"
    assert rng.position(175) == "premium"
    low, high = ote_band(rng, "bullish")
    assert 100 <= low < high <= 200


def test_signal_explains_itself():
    signal = ResearchSignal(
        10,
        "bullish",
        (
            Evidence("sell-side liquidity", True, "pool reclaimed"),
            Evidence("displacement", False, "body expansion insufficient"),
        ),
    )
    assert signal.score == 1
    assert signal.possible_score == 2
    assert signal.explanation[0].startswith("PASS")
