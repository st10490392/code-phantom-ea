from strategy.structure import (
    Candle,
    SwingPoint,
    classify_structure,
    detect_bos,
    detect_liquidity_sweeps,
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


def test_classify_structure_ignores_unconfirmed_swings():
    swings = [
        SwingPoint(index=0, price=10.0, kind="high", confirmed_at=None),
        SwingPoint(index=1, price=11.0, kind="high", confirmed_at=3),
    ]

    assert classify_structure(swings) == [
        SwingPoint(index=1, price=11.0, kind="high", structure="internal", confirmed_at=3)
    ]


def test_internal_structure_classification():
    swings = [
        SwingPoint(index=0, price=10.0, kind="high", confirmed_at=0),
        SwingPoint(index=2, price=10.5, kind="high", confirmed_at=2),
        SwingPoint(index=4, price=10.3, kind="high", confirmed_at=4),
    ]

    classified = classify_structure(swings)

    assert [s.structure for s in classified] == ["internal", "external", "internal"]


def test_external_structure_classification():
    swings = [
        SwingPoint(index=0, price=10.0, kind="high", confirmed_at=0),
        SwingPoint(index=2, price=11.0, kind="high", confirmed_at=2),
        SwingPoint(index=4, price=12.0, kind="high", confirmed_at=4),
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


def test_duplicate_bos_events_are_prevented_for_same_level():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(10, 12, 9, 11),
        Candle(11, 13, 10, 12),
        Candle(12, 14, 11, 13),
        Candle(13, 15, 12, 14),
        Candle(14, 16, 13, 15),
    ]
    highs = [
        SwingPoint(index=3, price=13.0, kind="high", structure="external", confirmed_at=3),
        SwingPoint(index=5, price=13.0, kind="high", structure="external", confirmed_at=5),
    ]

    bos_events = detect_bos(candles, highs, [])

    assert len(bos_events) == 1
    assert bos_events[0].index == 4


def test_same_price_swings_at_different_indexes_do_not_duplicate_bos():
    candles = [
        Candle(10, 10.5, 9.5, 10),
        Candle(10.1, 10.6, 9.4, 9.9),
        Candle(9.8, 11.0, 9.6, 10.9),
    ]
    highs = [
        SwingPoint(index=0, price=10.5, kind="high", structure="external", confirmed_at=0),
        SwingPoint(index=2, price=10.5, kind="high", structure="external", confirmed_at=2),
    ]

    bos_events = detect_bos(candles, highs, [])

    assert len(bos_events) == 1
    assert bos_events[0].direction == "bullish"


def test_bos_rejects_unconfirmed_swing():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(10, 12, 9, 11),
        Candle(11, 13, 10, 12),
    ]
    highs = [
        SwingPoint(index=2, price=12.0, kind="high", structure="external", confirmed_at=20),
    ]

    assert detect_bos(candles, highs, []) == []


def test_bullish_structure_shift():
    candles = [
        Candle(9.5, 10.0, 8.5, 9.0),
        Candle(9.0, 9.2, 7.8, 7.9),
        Candle(7.8, 11.2, 7.6, 11.1),
    ]
    lows = [
        SwingPoint(index=0, price=8.5, kind="low", structure="external", confirmed_at=0),
    ]
    highs = [
        SwingPoint(index=0, price=10.0, kind="high", structure="external", confirmed_at=0),
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


def test_insufficient_history_does_not_create_mss():
    candles = [
        Candle(10, 11, 9, 10.2),
        Candle(10.5, 12.0, 9.0, 9.4),
    ]
    highs = [
        SwingPoint(index=0, price=11.0, kind="high", structure="external", confirmed_at=0),
    ]

    assert detect_structure_shift(candles, highs, []) == []


def test_market_bias_uses_latest_confirmed_state():
    bos_events = [
        type("Event", (), {"index": 1, "direction": "bearish"})(),
        type("Event", (), {"index": 4, "direction": "bullish"})(),
    ]

    assert determine_market_bias(bos_events) == "bullish"


def test_liquidity_sweep_before_confirmation_is_rejected():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(10, 12, 9, 11),
        Candle(11, 13, 10, 12),
    ]
    highs = [
        SwingPoint(index=2, price=12.0, kind="high", structure="external", confirmed_at=10),
    ]

    assert detect_liquidity_sweeps(candles, highs, []) == []


def test_confirmation_works_on_exact_confirmed_at():
    candles = [
        Candle(10, 11, 9, 10),
        Candle(10, 12, 9, 11),
        Candle(11, 13, 10, 12),
        Candle(12, 14, 11, 13),
    ]
    highs = [
        SwingPoint(index=2, price=12.0, kind="high", structure="external", confirmed_at=2),
    ]

    assert len(detect_bos(candles[:3], highs, [])) == 0
    assert len(detect_bos(candles[:4], highs, [])) == 1


def test_basic_small_internal_fluctuation_stays_internal():
    swings = [
        SwingPoint(index=0, price=10.00, kind="high", confirmed_at=0),
        SwingPoint(index=1, price=10.05, kind="high", confirmed_at=1),
        SwingPoint(index=2, price=10.04, kind="high", confirmed_at=2),
    ]

    classified = classify_structure(swings)

    assert [s.structure for s in classified] == ["internal", "external", "internal"]
