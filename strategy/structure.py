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

    @property
    def identity(self) -> tuple[SwingKind, int]:
        return (self.kind, self.index)

@dataclass(frozen=True)
class StructuralLevel:
    side: SwingKind
    structure: StructureType
    price: float
    swing_index: int | None = None
    confirmed_at: int | None = None

    def identity(self, tolerance: float | None = None) -> tuple:
        del tolerance
        if self.swing_index is not None:
            return (self.side, self.swing_index)
        return (self.side, self.structure, self.price)

@dataclass(frozen=True)
class StructureState:
    as_of_index: int
    external_high: SwingPoint | None = None
    external_low: SwingPoint | None = None
    protected_high: SwingPoint | None = None
    protected_low: SwingPoint | None = None

@dataclass(frozen=True)
class StructureEvent:
    index: int
    kind: str
    direction: Direction
    level: float
    structure: StructureType = "internal"
    broken_swing_index: int | None = None
    broken_side: SwingKind | None = None
    broken_confirmed_at: int | None = None

@dataclass(frozen=True)
class StructureShift:
    index: int
    direction: Direction
    broken_level: float
    structure: StructureType = "internal"
    previous_state: Direction = "neutral"
    kind: Literal["MSS", "CHoCH"] = "MSS"
    broken_swing_index: int | None = None
    broken_side: SwingKind | None = None

def _available_swings(swings, as_of_index: int):
    """A swing is usable at completed-candle state ``confirmed_at``."""
    return [s for s in sorted(swings, key=lambda x: (x.index, x.kind))
            if s.confirmed_at is not None and s.confirmed_at <= as_of_index
            and s.index < as_of_index]

def detect_swing_highs(candles, window=2):
    if window < 1:
        raise ValueError("window must be at least 1")
    return [SwingPoint(i, candles[i].high, "high", confirmed_at=i + window)
            for i in range(window, len(candles) - window)
            if candles[i].high > max(c.high for c in candles[i-window:i])
            and candles[i].high > max(c.high for c in candles[i+1:i+window+1])]

def detect_swing_lows(candles, window=2):
    if window < 1:
        raise ValueError("window must be at least 1")
    return [SwingPoint(i, candles[i].low, "low", confirmed_at=i + window)
            for i in range(window, len(candles) - window)
            if candles[i].low < min(c.low for c in candles[i-window:i])
            and candles[i].low < min(c.low for c in candles[i+1:i+window+1])]

def classify_structure(swings, external_window=3):
    """Promote only extensions; internal pivots never move active extremes."""
    del external_window
    active: dict[SwingKind, SwingPoint | None] = {"high": None, "low": None}
    result = []
    for swing in sorted((s for s in swings if s.confirmed_at is not None),
                        key=lambda s: (s.index, s.kind)):
        extreme = active[swing.kind]
        extends = extreme is not None and (
            swing.price > extreme.price if swing.kind == "high"
            else swing.price < extreme.price)
        structure: StructureType = "external" if extends else "internal"
        item = SwingPoint(swing.index, swing.price, swing.kind, structure, swing.confirmed_at)
        if extreme is None or extends:
            active[swing.kind] = item
        result.append(item)
    return result

def structural_state(swings, as_of_index: int, bias: Direction = "neutral") -> StructureState:
    available = _available_swings(swings, as_of_index)
    def active(side):
        same = [s for s in available if s.kind == side]
        external = [s for s in same if s.structure == "external"]
        return external[-1] if external else (same[-1] if same else None)
    high, low = active("high"), active("low")
    return StructureState(as_of_index, high, low,
                          high if bias == "bearish" else None,
                          low if bias == "bullish" else None)

def _active_level(swings, side: SwingKind, index: int):
    available = [s for s in _available_swings(swings, index) if s.kind == side]
    external = [s for s in available if s.structure == "external"]
    return external[-1] if external else (available[-1] if available else None)

def detect_bos(candles, swing_highs, swing_lows):
    events, broken = [], set()
    for i, candle in enumerate(candles):
        checks = (("high", swing_highs, lambda p: candle.close > p, "bullish"),
                  ("low", swing_lows, lambda p: candle.close < p, "bearish"))
        for side, swings, crossed, direction in checks:
            swing = _active_level(swings, side, i)
            if swing and swing.identity not in broken and crossed(swing.price):
                events.append(StructureEvent(i, "BOS", direction, swing.price,
                    swing.structure, swing.index, side, swing.confirmed_at))
                broken.add(swing.identity)
    return events

def detect_structure_shift(candles, swing_highs, swing_lows):
    """MSS is an opposing break of the relevant high/low, never a mere flip."""
    state: Direction = "neutral"
    shifts = []
    for event in detect_bos(candles, swing_highs, swing_lows):
        valid = ((event.direction == "bullish" and event.broken_side == "high") or
                 (event.direction == "bearish" and event.broken_side == "low"))
        if state != "neutral" and event.direction != state and valid:
            shifts.append(StructureShift(event.index, event.direction, event.level,
                event.structure, state, "MSS", event.broken_swing_index,
                event.broken_side))
        if valid:
            state = event.direction
    return shifts

def detect_liquidity_sweeps(candles, swing_highs, swing_lows):
    events, consumed = [], set()
    for i, candle in enumerate(candles):
        checks = (("high", swing_highs,
                   lambda p: candle.high > p and candle.close < p, "bearish"),
                  ("low", swing_lows,
                   lambda p: candle.low < p and candle.close > p, "bullish"))
        for side, swings, swept, direction in checks:
            swing = _active_level(swings, side, i)
            if swing and swing.identity not in consumed and swept(swing.price):
                events.append(StructureEvent(i, "SWEEP", direction, swing.price,
                    swing.structure, swing.index, side, swing.confirmed_at))
                consumed.add(swing.identity)
    return events

def determine_market_bias(bos_events, structure_shifts=None):
    events = list(bos_events) + list(structure_shifts or [])
    return sorted(events, key=lambda e: e.index)[-1].direction if events else "neutral"
