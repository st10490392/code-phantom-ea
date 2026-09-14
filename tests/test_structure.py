from strategy.structure import (
    Candle,
    detect_swing_highs,
    detect_swing_lows,
    detect_bos,
    detect_liquidity_sweeps,
)


candles = [
    Candle(100, 102, 99, 101),
    Candle(101, 104, 100, 103),
    Candle(103, 107, 102, 106),
    Candle(106, 105, 101, 102),
    Candle(102, 103, 99, 100),
    Candle(100, 101, 97, 98),
    Candle(98, 100, 95, 96),
    Candle(96, 102, 97, 101),
    Candle(101, 104, 99, 103),
    Candle(103, 106, 101, 105),
]


swing_highs = detect_swing_highs(candles)
swing_lows = detect_swing_lows(candles)


print("\n=== SWING HIGHS ===")

for swing in swing_highs:
    print(
        f"Index: {swing.index} | "
        f"Price: {swing.price} | "
        f"Type: {swing.kind}"
    )


print("\n=== SWING LOWS ===")

for swing in swing_lows:
    print(
        f"Index: {swing.index} | "
        f"Price: {swing.price} | "
        f"Type: {swing.kind}"
    )


bos_events = detect_bos(
    candles,
    swing_highs,
    swing_lows
)


print("\n=== BOS EVENTS ===")

for event in bos_events:
    print(
        f"Index: {event.index} | "
        f"Direction: {event.direction} | "
        f"Level: {event.level}"
    )


sweep_events = detect_liquidity_sweeps(
    candles,
    swing_highs,
    swing_lows
)


print("\n=== LIQUIDITY SWEEPS ===")

for event in sweep_events:
    print(
        f"Index: {event.index} | "
        f"Direction: {event.direction} | "
        f"Level: {event.level}"
    )