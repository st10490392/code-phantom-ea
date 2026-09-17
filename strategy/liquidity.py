from dataclasses import dataclass
from typing import Literal

from strategy.structure import Candle, SwingPoint


Direction = Literal["bullish", "bearish"]


@dataclass(frozen=True)
class LiquiditySweep:
    """A wick through a prior confirmed swing level followed by a rejection close."""

    index: int
    direction: Direction
    level: float
    swing_index: int


def _available_swings(swings: list[SwingPoint], as_of_index: int) -> list[SwingPoint]:
    return [
        swing
        for swing in sorted(swings, key=lambda item: item.index)
        if swing.confirmed_at is not None
        and swing.confirmed_at + 1 < as_of_index
        and swing.index < as_of_index
    ]


def detect_sweeps(
    candles: list[Candle],
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
) -> list[LiquiditySweep]:
    """Detect sweeps of the latest available confirmed high or low liquidity pool."""

    sweeps = []

    for index, candle in enumerate(candles):
        previous_highs = _available_swings(swing_highs, index)
        previous_lows = _available_swings(swing_lows, index)

        if previous_highs:
            swing = previous_highs[-1]
            if candle.high > swing.price and candle.close < swing.price:
                sweeps.append(
                    LiquiditySweep(index, "bearish", swing.price, swing.index)
                )

        if previous_lows:
            swing = previous_lows[-1]
            if candle.low < swing.price and candle.close > swing.price:
                sweeps.append(
                    LiquiditySweep(index, "bullish", swing.price, swing.index)
                )

    return sweeps
