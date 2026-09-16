from dataclasses import dataclass
from typing import Literal

from strategy.structure import Candle


Direction = Literal["bullish", "bearish"]


@dataclass(frozen=True)
class FairValueGap:
	"""A three-candle imbalance that has not yet been invalidated."""

	index: int
	direction: Direction
	lower: float
	upper: float


@dataclass(frozen=True)
class InvertedFairValueGap:
	"""An FVG that was closed through and is now traded as an IFVG."""

	index: int
	source_index: int
	direction: Direction
	lower: float
	upper: float


@dataclass(frozen=True)
class Displacement:
	"""A directional candle with an unusually large, decisive body."""

	index: int
	direction: Direction
	body: float
	range: float


def detect_fvgs(candles: list[Candle]) -> list[FairValueGap]:
	"""Detect standard three-candle bullish and bearish fair value gaps.

	A bullish gap exists when candle 3's low is above candle 1's high.
	A bearish gap exists when candle 3's high is below candle 1's low.
	``index`` identifies candle 3, the first candle that confirms the gap.
	"""

	gaps = []

	for index in range(2, len(candles)):
		first = candles[index - 2]
		third = candles[index]

		if third.low > first.high:
			gaps.append(
				FairValueGap(index, "bullish", first.high, third.low)
			)
		elif third.high < first.low:
			gaps.append(
				FairValueGap(index, "bearish", third.high, first.low)
			)

	return gaps


def detect_ifvgs(
	candles: list[Candle],
	fvgs: list[FairValueGap] | None = None,
) -> list[InvertedFairValueGap]:
	"""Detect the first close through each FVG's far boundary.

	Invalidation changes the actionable direction: a bullish gap becomes a
	bearish IFVG after a close below its lower boundary, and vice versa.
	"""

	gaps = detect_fvgs(candles) if fvgs is None else fvgs
	inverted = []

	for gap in gaps:
		for index in range(gap.index + 1, len(candles)):
			close = candles[index].close
			invalidated = (
				close < gap.lower
				if gap.direction == "bullish"
				else close > gap.upper
			)

			if invalidated:
				inverted.append(
					InvertedFairValueGap(
						index=index,
						source_index=gap.index,
						direction=(
							"bearish"
							if gap.direction == "bullish"
							else "bullish"
						),
						lower=gap.lower,
						upper=gap.upper,
					)
				)
				break

	return inverted


def detect_displacement(
	candles: list[Candle],
	lookback: int = 5,
	range_multiple: float = 1.5,
	body_ratio: float = 0.6,
) -> list[Displacement]:
	"""Detect candles with a large range and decisive close.

	The reference range is the mean true range of the preceding candles.
	Requiring prior data avoids using the current candle to define its own
	threshold and makes the detector suitable for streaming use.
	"""

	if lookback < 1:
		raise ValueError("lookback must be at least 1")
	if range_multiple <= 0:
		raise ValueError("range_multiple must be positive")
	if not 0 < body_ratio <= 1:
		raise ValueError("body_ratio must be in the range (0, 1]")

	displacements = []

	for index, candle in enumerate(candles):
		if index < lookback:
			continue

		candle_range = candle.high - candle.low
		if candle_range <= 0:
			continue

		prior_ranges = [
			previous.high - previous.low
			for previous in candles[index - lookback:index]
			if previous.high > previous.low
		]
		if not prior_ranges:
			continue

		average_range = sum(prior_ranges) / len(prior_ranges)
		body = abs(candle.close - candle.open)
		decisive = body / candle_range >= body_ratio
		unusually_large = candle_range >= average_range * range_multiple

		if decisive and unusually_large and candle.close != candle.open:
			displacements.append(
				Displacement(
					index=index,
					direction=(
						"bullish" if candle.close > candle.open else "bearish"
					),
					body=body,
					range=candle_range,
				)
			)

	return displacements
