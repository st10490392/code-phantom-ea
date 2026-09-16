from dataclasses import dataclass

from strategy.fvg import (
	Displacement,
	FairValueGap,
	InvertedFairValueGap,
	detect_displacement,
	detect_fvgs,
	detect_ifvgs,
)
from strategy.liquidity import LiquiditySweep, detect_sweeps
from strategy.structure import (
	Candle,
	detect_swing_highs,
	detect_swing_lows,
)


@dataclass(frozen=True)
class StrategySetup:
	"""A complete Liquidity -> FVG -> IFVG -> Displacement sequence."""

	direction: str
	liquidity: LiquiditySweep
	fvg: FairValueGap
	ifvg: InvertedFairValueGap
	displacement: Displacement


def find_setups(candles: list[Candle]) -> list[StrategySetup]:
	"""Return only setups that complete every strategy stage in order.

	The directional filter is deliberately explicit: the sweep and initial
	FVG must agree, then the IFVG and displacement must agree after inversion.
	This is a foundation rule, not a claim that it is the only valid ICT
	model; changing it should be a conscious strategy decision.
	"""

	swing_highs = detect_swing_highs(candles)
	swing_lows = detect_swing_lows(candles)
	sweeps = detect_sweeps(candles, swing_highs, swing_lows)
	fvgs = detect_fvgs(candles)
	ifvgs = detect_ifvgs(candles, fvgs)
	displacements = detect_displacement(candles)
	setups = []

	for sweep in sweeps:
		matching_fvgs = [
			gap
			for gap in fvgs
			if gap.index > sweep.index and gap.direction == sweep.direction
		]

		for gap in matching_fvgs:
			matching_ifvgs = [
				inverted
				for inverted in ifvgs
				if inverted.source_index == gap.index
				and inverted.index > gap.index
			]

			for inverted in matching_ifvgs:
				matching_displacements = [
					displacement
					for displacement in displacements
					if displacement.index > inverted.index
					and displacement.direction == inverted.direction
				]

				if matching_displacements:
					setups.append(
						StrategySetup(
							direction=inverted.direction,
							liquidity=sweep,
							fvg=gap,
							ifvg=inverted,
							displacement=matching_displacements[0],
						)
					)
					break

				break

	return setups
