from dataclasses import dataclass
from typing import Literal

from strategy.structure import Candle, SwingPoint


Direction = Literal["bullish", "bearish"]


@dataclass(frozen=True)
class LiquiditySweep:
	"""A wick through a prior swing level followed by a rejection close."""

	index: int
	direction: Direction
	level: float
	swing_index: int


def detect_sweeps(
	candles: list[Candle],
	swing_highs: list[SwingPoint],
	swing_lows: list[SwingPoint],
) -> list[LiquiditySweep]:
	"""Detect sweeps of the latest available high or low liquidity pool."""

	sweeps = []

	for index, candle in enumerate(candles):
		previous_highs = [swing for swing in swing_highs if swing.index < index]
		previous_lows = [swing for swing in swing_lows if swing.index < index]

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
