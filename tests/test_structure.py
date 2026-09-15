from strategy.structure import (
    Candle,
    detect_swing_highs,
    detect_swing_lows,
    classify_structure,
    detect_bos,
    detect_liquidity_sweeps,
    determine_market_bias,
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


# ---------------------------------------------------------
# SWINGS
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# STRUCTURE CLASSIFICATION
# ---------------------------------------------------------

all_swings = sorted(
    swing_highs + swing_lows,
    key=lambda swing: swing.index
)

classified_swings = classify_structure(all_swings)


print("\n=== STRUCTURE CLASSIFICATION ===")

for swing in classified_swings:
    print(
        f"Index: {swing.index} | "
        f"Price: {swing.price} | "
        f"Type: {swing.kind} | "
        f"Structure: {swing.structure}"
    )


# ---------------------------------------------------------
# BOS
# ---------------------------------------------------------

bos_events = detect_bos(
    candles,
    classified_swings,
    classified_swings,
)


print("\n=== BOS EVENTS ===")

for event in bos_events:
    print(
        f"Index: {event.index} | "
        f"Direction: {event.direction} | "
        f"Level: {event.level} | "
        f"Structure: {event.structure}"
    )


# ---------------------------------------------------------
# LIQUIDITY SWEEPS
# ---------------------------------------------------------

sweep_events = detect_liquidity_sweeps(
    candles,
    classified_swings,
    classified_swings,
)


print("\n=== LIQUIDITY SWEEPS ===")

for event in sweep_events:
    print(
        f"Index: {event.index} | "
        f"Direction: {event.direction} | "
        f"Level: {event.level} | "
        f"Structure: {event.structure}"
    )


# ---------------------------------------------------------
# MARKET BIAS
# ---------------------------------------------------------

bias = determine_market_bias(bos_events)

print("\n=== MARKET BIAS ===")
print(f"Bias: {bias}")