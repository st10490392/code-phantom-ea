from strategy.entries import find_setups
from strategy.fvg import detect_displacement, detect_fvgs, detect_ifvgs
from strategy.structure import Candle


def test_fvg_and_ifvg_direction_flips_after_invalidation():
    candles = [
        Candle(100, 101, 99, 100),
        Candle(100, 106, 100, 105),
        Candle(105, 110, 107, 109),
        Candle(109, 108, 98, 99),
    ]

    fvgs = detect_fvgs(candles)
    ifvgs = detect_ifvgs(candles, fvgs)

    assert fvgs[0].direction == "bullish"
    assert ifvgs[0].direction == "bearish"
    assert ifvgs[0].source_index == fvgs[0].index


def test_displacement_requires_large_decisive_range():
    candles = [
        Candle(100, 102, 99, 101),
        Candle(101, 103, 100, 102),
        Candle(102, 104, 101, 103),
        Candle(103, 110, 102, 109),
        Candle(109, 110, 108, 109),
    ]

    events = detect_displacement(candles, lookback=3, range_multiple=1.5)

    assert [event.index for event in events] == [3]


def test_pipeline_returns_no_partial_setup():
    candles = [Candle(100, 101, 99, 100)] * 12

    assert find_setups(candles) == []