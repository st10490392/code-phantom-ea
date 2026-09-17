from dataclasses import dataclass, replace
from typing import Literal

from strategy.structure import Candle

Direction = Literal["bullish", "bearish"]
GapState = Literal["new", "partial", "mitigated", "invalidated"]


@dataclass(frozen=True)
class Gap:
    created_at: int
    direction: Direction
    lower: float
    upper: float
    state: GapState = "new"
    first_touch: int | None = None
    invalidated_at: int | None = None

    @property
    def midpoint(self) -> float:
        return (self.lower + self.upper) / 2


def detect_gaps(candles: list[Candle]) -> list[Gap]:
    gaps: list[Gap] = []
    for i in range(2, len(candles)):
        first, third = candles[i - 2], candles[i]
        if third.low > first.high:
            gaps.append(Gap(i, "bullish", first.high, third.low))
        elif third.high < first.low:
            gaps.append(Gap(i, "bearish", third.high, first.low))
    return gaps


def evolve_gap(candles: list[Candle], gap: Gap) -> Gap:
    state = gap
    for i in range(gap.created_at + 1, len(candles)):
        c = candles[i]
        overlaps = c.low <= gap.upper and c.high >= gap.lower
        if not overlaps:
            continue

        first_touch = state.first_touch if state.first_touch is not None else i
        if gap.direction == "bullish":
            if c.close < gap.lower:
                return replace(state, state="invalidated", first_touch=first_touch, invalidated_at=i)
            if c.low <= gap.lower:
                state = replace(state, state="mitigated", first_touch=first_touch)
            else:
                state = replace(state, state="partial", first_touch=first_touch)
        else:
            if c.close > gap.upper:
                return replace(state, state="invalidated", first_touch=first_touch, invalidated_at=i)
            if c.high >= gap.upper:
                state = replace(state, state="mitigated", first_touch=first_touch)
            else:
                state = replace(state, state="partial", first_touch=first_touch)
    return state
