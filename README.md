# code-phantom-ea

## Strategy foundation

The current strategy is a staged event pipeline:

`Liquidity -> FVG -> IFVG -> Displacement`

The implementation treats ICT terminology as definitions that can be tested:

- **Liquidity sweep:** price trades beyond the latest confirmed swing high or
	low and closes back through that level.
- **FVG:** a three-candle imbalance. A bullish gap has candle 3 low above
	candle 1 high; a bearish gap has candle 3 high below candle 1 low.
- **IFVG:** the first later candle close through the far boundary of an FVG.
	The actionable direction flips when the gap is inverted.
- **Displacement:** a candle whose range is larger than a configurable
	multiple of the preceding average range and whose body occupies a
	configurable portion of that range.

`strategy.entries.find_setups` returns only complete sequences. It currently
requires the sweep and original FVG to agree, then requires the IFVG and
displacement to agree after inversion. This is the initial formal model and
should be validated against historical data before adding execution or risk
management.