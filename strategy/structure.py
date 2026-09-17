from dataclasses import dataclass
from typing import Literal


Direction = Literal["bullish", "bearish", "neutral"]
StructureType = Literal["internal", "external"]
SwingKind = Literal["high", "low"]


@dataclass(frozen=True)
class Candle:
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class SwingPoint:
    index: int
    price: float
    kind: SwingKind
    structure: StructureType = "internal"
    confirmed_at: int | None = None


@dataclass(frozen=True)
class StructureEvent:
    index: int
    kind: str
    direction: Direction
    level: float
    structure: StructureType = "internal"


@dataclass(frozen=True)
class StructureShift:
    index: int
    direction: Direction
    broken_level: float
    structure: StructureType = "internal"
    previous_state: Direction = "neutral"
    kind: Literal["MSS", "CHoCH"] = "MSS"


def _confirmed_swings(swings, as_of_index: int):
    return [
        swing
        for swing in sorted(swings, key=lambda item: item.index)
        if swing.confirmed_at is None or swing.confirmed_at <= as_of_index
    ]


def detect_swing_highs(candles, window=2):
    """Detect confirmed swing highs using only past and present candle information."""

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
                    kind="high",
                    confirmed_at=i + window,
                )
            )

    return swings


def detect_swing_lows(candles, window=2):
    """Detect confirmed swing lows using only past and present candle information."""

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
                    kind="low",
                    confirmed_at=i + window,
                )
            )

    return swings


def classify_structure(swings, external_window=3):
    """Classify swings as internal or external using the prior extreme of the same kind."""

    if not swings:
        return []

    ordered = sorted(swings, key=lambda swing: swing.index)
    classified = []

    for index, swing in enumerate(ordered):
        prior_same_kind = [
            previous
            for previous in ordered[:index]
            if previous.kind == swing.kind
        ]

        if not prior_same_kind:
            structure = "internal"
        else:
            anchor = max(prior_same_kind, key=lambda item: item.price) if swing.kind == "high" else min(prior_same_kind, key=lambda item: item.price)
            if swing.kind == "high":
                structure = "external" if swing.price > anchor.price else "internal"
            else:
                structure = "external" if swing.price < anchor.price else "internal"

        classified.append(
            SwingPoint(
                index=swing.index,
                price=swing.price,
                kind=swing.kind,
                structure=structure,
                confirmed_at=swing.confirmed_at,
            )
        )

    return classified


def detect_bos(candles, swing_highs, swing_lows):
    """Detect BOS from confirmed structural levels and a close beyond the level."""

    events = []
    broken_highs = set()
    broken_lows = set()

    for i, candle in enumerate(candles):
        confirmed_highs = [
            swing for swing in sorted(swing_highs, key=lambda item: item.index)
            if swing.confirmed_at is not None and swing.confirmed_at <= i and swing.index < i
        ]
        confirmed_lows = [
            swing for swing in sorted(swing_lows, key=lambda item: item.index)
            if swing.confirmed_at is not None and swing.confirmed_at <= i and swing.index < i
        ]

        if confirmed_highs:
            latest_high = confirmed_highs[-1]
            if latest_high.index not in broken_highs and candle.close > latest_high.price:
                events.append(
                    StructureEvent(
                        index=i,
                        kind="BOS",
                        direction="bullish",
                        level=latest_high.price,
                        structure=latest_high.structure,
                    )
                )
                broken_highs.add(latest_high.index)

        if confirmed_lows:
            latest_low = confirmed_lows[-1]
            if latest_low.index not in broken_lows and candle.close < latest_low.price:
                events.append(
                    StructureEvent(
                        index=i,
                        kind="BOS",
                        direction="bearish",
                        level=latest_low.price,
                        structure=latest_low.structure,
                    )
                )
                broken_lows.add(latest_low.index)

    return events


def detect_structure_shift(candles, swing_highs, swing_lows):
    """Unified MSS/CHoCH detector.

    A structural shift is emitted when an established BOS direction changes from
    the previous directional state. Same-direction continuation is not a shift.
    """

    state: Direction = "neutral"
    shifts = []

    for event in detect_bos(candles, swing_highs, swing_lows):
        if state == "neutral":
            state = event.direction
            continue

        if event.direction != state:
            shifts.append(
                StructureShift(
                    index=event.index,
                    direction=event.direction,
                    broken_level=event.level,
                    structure=event.structure,
                    previous_state=state,
                    kind="MSS",
                )
            )
            state = event.direction

    return shifts


def detect_liquidity_sweeps(candles, swing_highs, swing_lows):
    """Detect liquidity sweeps using the latest confirmed relevant swing level."""

    events = []

    for i, candle in enumerate(candles):
        confirmed_highs = [
            swing for swing in sorted(swing_highs, key=lambda item: item.index)
            if swing.confirmed_at is not None and swing.confirmed_at <= i and swing.index < i
        ]
        confirmed_lows = [
            swing for swing in sorted(swing_lows, key=lambda item: item.index)
            if swing.confirmed_at is not None and swing.confirmed_at <= i and swing.index < i
        ]

        if confirmed_highs:
            latest_high = confirmed_highs[-1]
            if candle.high > latest_high.price and candle.close < latest_high.price:
                events.append(
                    StructureEvent(
                        index=i,
                        kind="SWEEP",
                        direction="bearish",
                        level=latest_high.price,
                        structure=latest_high.structure,
                    )
                )

        if confirmed_lows:
            latest_low = confirmed_lows[-1]
            if candle.low < latest_low.price and candle.close > latest_low.price:
                events.append(
                    StructureEvent(
                        index=i,
                        kind="SWEEP",
                        direction="bullish",
                        level=latest_low.price,
                        structure=latest_low.structure,
                    )
                )

    return events


def determine_market_bias(bos_events, structure_shifts=None):
    """Return bullish, bearish, or neutral based on directional counts of completed structure events."""

    events = list(bos_events)
    if structure_shifts:
        events.extend(structure_shifts)

    if not events:
        return "neutral"

    bullish_count = sum(1 for event in events if event.direction == "bullish")
    bearish_count = sum(1 for event in events if event.direction == "bearish")

    if bullish_count > bearish_count:
        return "bullish"
    if bearish_count > bullish_count:
        return "bearish"
    return "neutral"