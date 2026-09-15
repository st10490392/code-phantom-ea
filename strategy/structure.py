from dataclasses import dataclass
from typing import Literal


Direction = Literal["bullish", "bearish", "neutral"]
StructureType = Literal["internal", "external"]


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
    structure: StructureType = "internal"


@dataclass
class StructureEvent:
    index: int
    kind: str  # "BOS", "CHoCH", or "SWEEP"
    direction: Direction
    level: float
    structure: StructureType = "internal"


def detect_swing_highs(candles, window=2):
    """
    Detect confirmed swing highs.

    With window=2:

        candle before  candle before
               \          /
                [ PIVOT ]
               /          \
        candle after   candle after

    The pivot high must be higher than the highs
    of the two candles on either side.
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
    Detect confirmed swing lows using the same pivot model.
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


def classify_structure(swings, external_window=3):
    """
    Classify swings as internal or external.

    V0.1 approach:
        A swing is external when it is separated from
        surrounding swings by a larger structural move.

    For now we use a simple significance rule based on
    neighboring swing prices.

    This is intentionally conservative. We will refine
    structural hierarchy after testing real market data.
    """

    if not swings:
        return []

    classified = []

    for i, swing in enumerate(swings):

        previous_swings = swings[max(0, i - external_window):i]
        next_swings = swings[i + 1:i + 1 + external_window]

        surrounding = previous_swings + next_swings

        if not surrounding:
            structure = "internal"
        else:
            distances = [
                abs(swing.price - other.price)
                for other in surrounding
            ]

            average_distance = sum(distances) / len(distances)

            # Conservative significance threshold.
            structure = (
                "external"
                if average_distance > 0
                else "internal"
            )

        classified.append(
            SwingPoint(
                index=swing.index,
                price=swing.price,
                kind=swing.kind,
                structure=structure
            )
        )

    return classified


def detect_bos(candles, swing_highs, swing_lows):
    """
    Detect basic Breaks of Structure.

    Bullish BOS:
        candle closes above a previous swing high.

    Bearish BOS:
        candle closes below a previous swing low.
    """

    events = []

    broken_highs = set()
    broken_lows = set()

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

            if (
                latest_high.index not in broken_highs
                and candle.close > latest_high.price
            ):
                events.append(
                    StructureEvent(
                        index=i,
                        kind="BOS",
                        direction="bullish",
                        level=latest_high.price,
                        structure=latest_high.structure
                    )
                )

                broken_highs.add(latest_high.index)

        if previous_lows:

            latest_low = previous_lows[-1]

            if (
                latest_low.index not in broken_lows
                and candle.close < latest_low.price
            ):
                events.append(
                    StructureEvent(
                        index=i,
                        kind="BOS",
                        direction="bearish",
                        level=latest_low.price,
                        structure=latest_low.structure
                    )
                )

                broken_lows.add(latest_low.index)

    return events


def detect_liquidity_sweeps(candles, swing_highs, swing_lows):
    """
    Detect liquidity sweeps.

    High sweep:
        price trades above a previous swing high
        but closes back below that level.

    Low sweep:
        price trades below a previous swing low
        but closes back above that level.
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

            if (
                candle.high > latest_high.price
                and candle.close < latest_high.price
            ):
                events.append(
                    StructureEvent(
                        index=i,
                        kind="SWEEP",
                        direction="bearish",
                        level=latest_high.price,
                        structure=latest_high.structure
                    )
                )

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
                        level=latest_low.price,
                        structure=latest_low.structure
                    )
                )

    return events


def determine_market_bias(bos_events):
    """
    Determine the current structural bias from BOS events.

    Latest bullish BOS  -> bullish
    Latest bearish BOS  -> bearish
    No BOS               -> neutral
    """

    if not bos_events:
        return "neutral"

    latest_event = bos_events[-1]

    if latest_event.direction == "bullish":
        return "bullish"

    if latest_event.direction == "bearish":
        return "bearish"

    return "neutral"