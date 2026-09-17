# Code Phantom EA

Code Phantom EA is a deterministic SMC/ICT research and backtesting engine.
It produces auditable observations and candidate evidence; it does not connect
to brokers, execute orders, or claim profitability.

## Causality contract

All APIs operate on completed candles. A pivot with `confirmed_at=N` is
invisible before state `N` and usable at state `N`; its pivot index must still
precede the evaluating candle. No detector reads future data to label an
earlier event.

## Structure v1.2

Geometric pivot detection is separate from structural significance.
`classify_structure` maintains same-side external extremes: an internal swing
cannot replace an active external extreme, while a genuine extension can.
`structural_state` exposes active external and bias-dependent protected levels.

BOS requires a close beyond the active confirmed structural high (bullish) or
low (bearish). Events retain `broken_swing_index`, `broken_side`, confirmation
time, level, and structure class, and are deduplicated by source-swing identity.
After bearish structure, bullish MSS breaks the relevant high; after bullish
structure, bearish MSS breaks the relevant low. A direction flip alone is
insufficient. The available inputs do not reliably separate MSS from CHoCH, so
the engine conservatively emits `MSS` rather than guessing.

## Delivery and price legs

Delivery legs group observable directional closes and measure indices, prices,
movement, candle count, bodies, ranges, efficiency, displacement candles, and
optional originating/terminating swings. Parameters are explicit; a short
four-candle expansion can be meaningful. CISD records a close through an
opposing delivery-run reference as evidence, not proof of reversal.

## Liquidity v2

Confirmed swings form buy-side or sell-side pools. Equal highs/lows cluster
only under the caller's explicit absolute tolerance. Pools carry source
indices, price, structure class, confirmation availability, and state.
The tracker distinguishes:

- wick sweep: penetration and close back through on the same candle;
- reclaim sweep: close-through followed by a close back within the configured
  confirmation window;
- structural break: no qualifying reclaim before that window expires.

Events retain pool identity, penetration and confirmation candles, direction,
type, level, source indices, and resulting active/consumed state. Each pool is
consumed once. The legacy `strategy.liquidity.detect_sweeps` API remains.

## Imbalance, context, and evidence

The original FVG/IFVG APIs remain intact. `strategy.imbalance` adds causal gap
snapshots for `new -> active -> partial -> mitigated/invalidated`, with
mitigation depth. Invalidation supports the existing IFVG detector.

`DealingRange` provides equilibrium, premium/discount, and a configurable OTE
band as geometry only. `ContextSeries` and `MultiTimeframeContext` carry
optional caller-supplied timeframe/timestamp data; neither is fabricated.

`build_candidate_signal` orders explainable evidence as HTF context, liquidity
target/event, structural shift, displacement, PD array, premium/discount, and
candidate setup. These are research candidates, not executable trades.

## Existing staged setup API

For compatibility, `strategy.entries.find_setups` retains the original
`Liquidity -> FVG -> IFVG -> Displacement` sequence. It returns only complete
research sequences and performs no execution or risk management.

## Tests

```sh
python3 -m pytest -q
```
