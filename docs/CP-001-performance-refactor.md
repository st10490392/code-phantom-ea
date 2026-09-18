# CP-001 execution-engine performance refactor

This revision preserves CP-001 Baseline V1 as the behavioral oracle and does
not change its frozen artifact or strategy hypothesis. No market-performance
result existed before this work, and market data was not used by the refactor.

## Full-prefix source

For execution candle `i`, the reference engine slices `candles[:i + 1]` and
recomputes confirmed swings, structure classification, BOS, MSS, structural
state, liquidity pools and their complete histories, all FVG lifecycles and
IFVGs, and every displacement. It independently repeats the corresponding
structure work for the visible H4 prefix. Several detectors contain their own
historical scans, making some datasets worse than a single quadratic loop.

## Incremental state

The separate optimized engine retains confirmed and classified swings, active
external levels, broken BOS identities, BOS/MSS history and bias, liquidity
groups and pool transition state, evolving FVGs and first inversions, and the
rolling displacement input window. H4 state advances once per newly visible H4
candle and is cached by completed index. Candidate evidence is still built by
the frozen canonical ordering function.

Every public snapshot field remains materialized for exact equality. Therefore
the refactor removes full-prefix detector reconstruction but does not claim a
formal linear bound: updating all live liquidity pools and gaps, sorting pools,
and copying cumulative tuple-valued snapshot fields can still be linear in
retained state per candle and quadratic in an adversarial full run. Swing,
structure, displacement, and H4 transitions are bounded incremental updates;
liquidity grouping can also scan existing groups when tolerance clustering is
enabled.

## Benchmark protocol

`benchmarks/cp001_engine_benchmark.py` generates deterministic non-market OHLC
data with a fixed PRNG seed. Reference and optimized snapshots are asserted
equal for every jointly benchmarked size. The reference maximum defaults to
400 because its observed growth makes larger sizes impractical on the current
hardware; optimized-only timings continue through 3200. Timing is empirical
and is not used as proof of complexity.
