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

## Structure engine definitions

The structure engine uses explicit, deterministic rules for this software
implementation. These are the repository's formal definitions and are not
presented as universal ICT truth.

- **Swing confirmation:** a pivot is a candidate only when it has the required
	left and right candles. The swing is not considered available to downstream
	logic until `confirmed_at`, which is the first candle index after the
	required confirmation window.
- **Internal swing:** a swing that does not exceed the most recent confirmed
	swing of the same kind in the directional hierarchy. It remains internal
	until it creates a new structural extreme.
- **External swing:** a swing that sets a new structural extreme relative to
	the most recent confirmed swing of the same kind.
- **BOS:** a candle close beyond a previously confirmed structural level.
	A wick through a level without a close beyond it does not become BOS.
	Repeated BOS events against the same structural level are suppressed.
- **Structure shift / MSS / CHoCH:** this repository models structure shifts
	as a change in the direction of BOS events relative to the prior structural
	state. This does not imply that every shift guarantees reversal; it merely
	records a directional change in market structure.
- **Market bias:** bias is derived from the directional count of completed BOS
	events and structural shifts, returning bullish, bearish, or neutral only
	when there is enough information to support a directional evaluation.