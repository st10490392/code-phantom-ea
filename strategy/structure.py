from dataclasses import dataclass
from typing import Literal


Direction = Literal["bullish", "bearish", "neutral"]
StructureType = Literal["internal", "external"]
SwingKind = Literal["high", "low"]

STRUCTURE_LEVEL_TOLERANCE = 1e-8


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
class StructuralLevel:
    side: SwingKind
    structure: StructureType
    price: float

    def identity(self, tolerance: float = STRUCTURE_LEVEL_TOLERANCE) -> tuple[str, str, float]:
        normalized = round(self.price / tolerance) * tolerance
        return (self.side, self.structure, normalized)


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


def _available_swings(swings, as_of_index: int):
    """Return only confirmed swings available at the evaluation candle index.

    A swing is available only after the confirmation bar has passed. In other
    words, confirmation is a state that becomes active on the next candle, not
    on the candle that confirms the swing itself. `confirmed_at=None` is never
    treated as confirmed.
    """

    return [
        swing
        for swing in sorted(swings, key=lambda item: item.index)
        if swing.confirmed_at is not None
        and swing.confirmed_at + 1 < as_of_index
        and swing.index < as_of_index
    ]


def _latest_external_swing(swings, kind: SwingKind):
    external = [swing for swing in swings if swing.kind == kind and swing.structure == "external"]
    return external[-1] if external else None


def _break_identity(kind: SwingKind, price: float, structure: StructureType):
    return StructuralLevel(kind, structure, price).identity()


def detect_swing_highs(candles, window=2):
    """Detect confirmed swing highs without lookahead bias."""

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
    """Detect confirmed swing lows without lookahead bias."""

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
    """Assign internal/external structure in a hierarchical, deterministic way.

    Algorithm:
    - Only confirmed swings are considered.
    - The active external high and active external low define the current broader
      structure for each side.
    - A swing is internal unless it extends the current active external swing of
      the same kind. When it does extend it, it becomes the new active external
      swing for that side.

    This is conservative: the first confirmed swing of a side is never treated as
    an external structural break until a broader same-side extreme is established.
    This does not claim to capture every possible market regime; it is a formal,
    auditable starting point for structural analysis.
    """

    confirmed = [swing for swing in swings if swing.confirmed_at is not None]
    if not confirmed:
        return []

    ordered = sorted(confirmed, key=lambda swing: swing.index)
    latest_same_side = {"high": None, "low": None}
    classified = []

    for swing in ordered:
        previous = latest_same_side[swing.kind]

        if previous is None:
            structure = "internal"
        elif swing.kind == "high":
            structure = "external" if swing.price > previous.price else "internal"
        else:
            structure = "external" if swing.price < previous.price else "internal"

        latest_same_side[swing.kind] = swing

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
    """Detect BOS only from confirmed structural levels and a close beyond them."""

    events = []
    broken_levels = set()

    for i, candle in enumerate(candles):
        confirmed_highs = _available_swings(swing_highs, i)
        confirmed_lows = _available_swings(swing_lows, i)

        if confirmed_highs:
            latest_high = confirmed_highs[-1]
            level_key = _break_identity("high", latest_high.price, latest_high.structure)
            if level_key not in broken_levels and candle.close > latest_high.price:
                events.append(
                    StructureEvent(
                        index=i,
                        kind="BOS",
                        direction="bullish",
                        level=latest_high.price,
                        structure=latest_high.structure,
                    )
                )
                broken_levels.add(level_key)

        if confirmed_lows:
            latest_low = confirmed_lows[-1]
            level_key = _break_identity("low", latest_low.price, latest_low.structure)
            if level_key not in broken_levels and candle.close < latest_low.price:
                events.append(
                    StructureEvent(
                        index=i,
                        kind="BOS",
                        direction="bearish",
                        level=latest_low.price,
                        structure=latest_low.structure,
                    )
                )
                broken_levels.add(level_key)

    return events


def detect_structure_shift(candles, swing_highs, swing_lows):
    """Emit a structure shift only when an opposing confirmed external swing is broken.

    This is a state-based structural change detector. A direction flip only counts
    as a shift when the event breaks the active opposing external structure.
    It is evidence of a structural change, not a forecast of reversal.
    """

    bos_events = detect_bos(candles, swing_highs, swing_lows)
    if not bos_events:
        return []

    state: Direction = "neutral"
    shifts = []

    for event in bos_events:
        if state == "neutral":
            state = event.direction
            continue

        if event.direction == state:
            continue

        if event.direction == "bullish":
            latest_low = _latest_external_swing(
                [
                    swing
                    for swing in _available_swings(swing_lows, event.index)
                    if swing.confirmed_at is not None
                ],
                "low",
            )
            if latest_low is not None and event.level >= latest_low.price:
                shifts.append(
                    StructureShift(
                        index=event.index,
                        direction="bullish",
                        broken_level=latest_low.price,
                        structure=latest_low.structure,
                        previous_state=state,
                        kind="MSS",
                    )
                )
                state = "bullish"
                continue

        if event.direction == "bearish":
            latest_high = _latest_external_swing(
                [
                    swing
                    for swing in _available_swings(swing_highs, event.index)
                    if swing.confirmed_at is not None
                ],
                "high",
            )
            if latest_high is not None and event.level <= latest_high.price:
                shifts.append(
                    StructureShift(
                        index=event.index,
                        direction="bearish",
                        broken_level=latest_high.price,
                        structure=latest_high.structure,
                        previous_state=state,
                        kind="MSS",
                    )
                )
                state = "bearish"
                continue

        state = event.direction

    return shifts


def detect_liquidity_sweeps(candles, swing_highs, swing_lows):
    """Detect liquidity sweeps only from confirmed structural levels."""

    events = []

    for i, candle in enumerate(candles):
        confirmed_highs = _available_swings(swing_highs, i)
        confirmed_lows = _available_swings(swing_lows, i)

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
    """Return the current confirmed structural bias from the most recent event."""

    events = list(bos_events)
    if structure_shifts:
        events.extend(structure_shifts)

    if not events:
        return "neutral"

    latest_event = sorted(events, key=lambda event: event.index)[-1]
    if latest_event.direction == "bullish":
        return "bullish"
    if latest_event.direction == "bearish":
        return "bearish"
    return "neutral"