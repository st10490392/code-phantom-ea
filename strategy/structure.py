from dataclasses import dataclass


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float


@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str  # "high" or "low"


@dataclass
class StructureEvent:
    index: int
    kind: str  # "BOS" or "SWEEP"
    direction: str  # "bullish" or "bearish"
    level: float


def detect_swing_highs(candles, window=2):
    """
    Detect swing highs.

    Default:
        2 candles before
        1 pivot candle
        2 candles after

    This gives us a 5-candle pivot.
    """

    if window < 1:
        raise ValueError("window must be at least 1")

    swings = []

    for i in range(window, len(candles) - window):

        current = candles[i]

        left = candles[i - window:i]
        right = candles[i + 1:i + window + 1]

        left_high = max(c.high for c in left)
        right_high = max(c.high for c in right)

        if current.high > left_high and current.high > right_high:
            swings.append(
                SwingPoint(
                    index=i,
                    price=current.high,
                    kind="high"
                )
            )

    return swings


def detect_swing_lows(candles, window=2):
    """
    Detect swing lows using the same 5-candle model.
    """

    if window < 1:
        raise ValueError("window must be at least 1")

    swings = []

    for i in range(window, len(candles) - window):

        current = candles[i]

        left = candles[i - window:i]
        right = candles[i + 1:i + window + 1]

        left_low = min(c.low for c in left)
        right_low = min(c.low for c in right)

        if current.low < left_low and current.low < right_low:
            swings.append(
                SwingPoint(
                    index=i,
                    price=current.low,
                    kind="low"
                )
            )

    return swings


def detect_bos(candles, swing_highs, swing_lows):
    """
    Detect basic Breaks of Structure.

    Bullish BOS:
        candle closes above a previous swing high.

    Bearish BOS:
        candle closes below a previous swing low.
    """

    events = []

    for i, candle in enumerate(candles):

        previous_highs = [
            swing for swing in swing_highs
            if swing.index < i
        ]

        previous_lows = [
            swing for swing in swing_lows
            if swing.index < i
        ]

        if previous_highs:
            latest_high = previous_highs[-1]

            if candle.close > latest_high.price:
                events.append(
                    StructureEvent(
                        index=i,
                        kind="BOS",
                        direction="bullish",
                        level=latest_high.price
                    )
                )

        if previous_lows:
            latest_low = previous_lows[-1]

            if candle.close < latest_low.price:
                events.append(
                    StructureEvent(
                        index=i,
                        kind="BOS",
                        direction="bearish",
                        level=latest_low.price
                    )
                )

    return events


def detect_liquidity_sweeps(candles, swing_highs, swing_lows):
    """
    Detect basic liquidity sweeps.

    High sweep:
        price trades above a previous swing high
        but closes back below it.

    Low sweep:
        price trades below a previous swing low
        but closes back above it.
    """

    events = []

    for i, candle in enumerate(candles):

        previous_highs = [
            swing for swing in swing_highs
            if swing.index < i
        ]

        previous_lows = [
            swing for swing in swing_lows
            if swing.index < i
        ]

        # Buy-side liquidity sweep
        if previous_highs:

            latest_high = previous_highs[-1]

            if (
                candle.high > latest_high.price
                and candle.close < latest_high.price
            ):
                events.append(
                    StructureEvent(
                        index=i,
                        kind="SWEEP",
                        direction="bearish",
                        level=latest_high.price
                    )
                )

        # Sell-side liquidity sweep
        if previous_lows:

            latest_low = previous_lows[-1]

            if (
                candle.low < latest_low.price
                and candle.close > latest_low.price
            ):
                events.append(
                    StructureEvent(
                        index=i,
                        kind="SWEEP",
                        direction="bullish",
                        level=latest_low.price
                    )
                )

    return events