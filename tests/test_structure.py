from strategy.structure import (
    Candle,
    SwingPoint,
    classify_structure,
    detect_bos,
    detect_swing_highs,
    detect_swing_lows,
    detect_structure_shift,
    determine_market_bias,
)


def test_detect_swing_highs():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(10, 12, 9, 11),
        Candle(11, 13, 10, 12),
        Candle(12, 14, 11, 13),
        Candle(13, 13.5, 12, 13),
        Candle(13, 12.5, 11.5, 12.0),
    ]

    highs = detect_swing_highs(candles, window=2)

    assert len(highs) == 1
    assert highs[0].index == 3
    assert highs[0].price == 14
    assert highs[0].kind == "high"
    assert highs[0].confirmed_at == 5


def test_detect_swing_lows():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(9, 10, 8, 9),
        Candle(8, 9, 7, 8),
        Candle(7, 8, 6, 7),
        Candle(8, 9, 7, 8),
        Candle(9, 10, 8, 9),
    ]

    lows = detect_swing_lows(candles, window=2)

    assert len(lows) == 1
    assert lows[0].index == 3
    assert lows[0].price == 6
    assert lows[0].kind == "low"
    assert lows[0].confirmed_at == 5


def test_swing_confirmation_timing():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(10, 12, 9, 11),
        Candle(11, 13, 10, 12),
        Candle(12, 14, 11, 13),
        Candle(13, 13.5, 12, 13),
        Candle(13, 12.5, 11.5, 12.0),
    ]

    highs = detect_swing_highs(candles, window=2)

    assert highs[0].confirmed_at == 5
    assert detect_bos(candles, highs, []) == []


def test_internal_structure_classification():
    swings = [
        SwingPoint(index=0, price=10.0, kind="high", structure="internal"),
        SwingPoint(index=2, price=9.5, kind="high", structure="internal"),
        SwingPoint(index=4, price=9.8, kind="high", structure="internal"),
    ]

    classified = classify_structure(swings)

    assert [s.structure for s in classified] == ["internal", "internal", "internal"]


def test_external_structure_classification():
    swings = [
        SwingPoint(index=0, price=10.0, kind="high", structure="internal"),
        SwingPoint(index=2, price=11.0, kind="high", structure="internal"),
        SwingPoint(index=4, price=12.0, kind="high", structure="internal"),
    ]

    classified = classify_structure(swings)

    assert [s.structure for s in classified] == ["internal", "external", "external"]


def test_bullish_bos_after_confirmed_high_is_closed_above():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(10, 12, 9, 11),
        Candle(11, 13, 10, 12),
        Candle(12, 14, 11, 13),
        Candle(13, 15, 12, 14),
    ]
    highs = [
        SwingPoint(index=3, price=13.0, kind="high", structure="external", confirmed_at=3)
    ]

    bos_events = detect_bos(candles, highs, [])

    assert len(bos_events) == 1
    assert bos_events[0].direction == "bullish"
    assert bos_events[0].level == 13.0
    assert bos_events[0].structure == "external"


def test_bearish_bos_after_confirmed_low_is_closed_below():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(10, 12, 9, 11),
        Candle(9, 10, 8, 9),
        Candle(8, 9, 7, 8),
        Candle(8, 9, 6, 7),
    ]
    lows = [
        SwingPoint(index=3, price=8.0, kind="low", structure="external", confirmed_at=3)
    ]

    bos_events = detect_bos(candles, [], lows)

    assert len(bos_events) == 1
    assert bos_events[0].direction == "bearish"
    assert bos_events[0].level == 8.0
    assert bos_events[0].structure == "external"


def test_wick_through_level_without_close_break_does_not_create_bos():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(10, 12, 9, 11),
        Candle(11, 13, 10, 12),
        Candle(12, 13.5, 11.5, 11.8),
    ]
    highs = [
        SwingPoint(index=2, price=12.0, kind="high", structure="external", confirmed_at=2)
    ]

    bos_events = detect_bos(candles, highs, [])

    assert bos_events == []


def test_duplicate_bos_events_are_prevented():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(10, 12, 9, 11),
        Candle(11, 13, 10, 12),
        Candle(12, 14, 11, 13),
        Candle(13, 15, 12, 14),
        Candle(14, 16, 13, 15),
    ]
    highs = [
        SwingPoint(index=3, price=13.0, kind="high", structure="external", confirmed_at=3)
    ]

    bos_events = detect_bos(candles, highs, [])

    assert len(bos_events) == 1
    assert bos_events[0].index == 4


def test_bullish_structure_shift():
    candles = [
        Candle(10.0, 11.0, 9.0, 10.0),
        Candle(10.2, 10.6, 8.3, 8.6),
        Candle(8.8, 12.0, 8.5, 12.1),
    ]
    lows = [
        SwingPoint(index=0, price=9.0, kind="low", structure="external", confirmed_at=0),
    ]
    highs = [
        SwingPoint(index=0, price=11.0, kind="high", structure="external", confirmed_at=0),
    ]

    shifts = detect_structure_shift(candles, highs, lows)

    assert shifts
    assert shifts[0].direction == "bullish"
    assert shifts[0].previous_state == "bearish"


def test_bearish_structure_shift():
    candles = [
        Candle(10.0, 10.5, 8.5, 10.2),
        Candle(10.3, 11.4, 7.0, 11.3),
        Candle(11.0, 11.6, 6.8, 6.9),
    ]
    highs = [
        SwingPoint(index=0, price=10.5, kind="high", structure="external", confirmed_at=0),
    ]
    lows = [
        SwingPoint(index=1, price=7.0, kind="low", structure="external", confirmed_at=1),
    ]

    shifts = detect_structure_shift(candles, highs, lows)

    assert shifts
    assert shifts[0].direction == "bearish"
    assert shifts[0].previous_state == "bullish"


def test_market_bias_is_neutral_when_information_is_insufficient():
    assert determine_market_bias([]) == "neutral"
    assert determine_market_bias([
        type("Event", (), {"direction": "bullish"})(),
        type("Event", (), {"direction": "bearish"})(),
    ]) == "neutral"


def test_no_future_candle_information_is_used_before_confirmation():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(10, 12, 9, 11),
        Candle(11, 13, 10, 12),
        Candle(12, 14, 11, 13),
    ]
    highs = [
        SwingPoint(index=2, price=12.0, kind="high", structure="external", confirmed_at=4)
    ]

    assert detect_bos(candles, highs, []) == []
