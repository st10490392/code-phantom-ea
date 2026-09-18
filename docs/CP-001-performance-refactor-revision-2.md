# CP-001 execution-engine performance refactor — Revision 2

This is a computational revision of the unchanged CP-001 Baseline V1
hypothesis. The original engine remains the ultimate behavioral oracle and
Execution Revision 1 remains an intermediate oracle. No strategy-performance
metric was calculated or used during this refactor.

## Measured Revision 1 hotspots

At 4000 deterministic synthetic candles under profiling, Revision 1 spent
24.2 of 33.1 profiled seconds in liquidity advancement. Repeated global sorts
accounted for 16.2 seconds; rebuilding ordered pools accounted for 7.2 seconds;
tolerance-group searches and repeated averages accounted for 5.2 seconds.
FVG lifecycle processing accounted for 4.3 seconds. Complete event histories
were flattened and sorted on every candle even though snapshots expose only
current liquidity events, and unchanged active-pool/gap tuples were repeatedly
rebuilt.

## Revision 2 state

Revision 2 maintains ordered pools, side-specific level indexes, pending breach
identities, per-pool terminal events, latest terminal evidence by direction,
exact-price pool indexes for the frozen zero-tolerance configuration, live gap
indices, latest gap/IFVG evidence references, and cached immutable tuples.
Untouched liquidity pools are found by bisecting level indexes rather than by
scanning every pool. Immutable snapshot tuples are reused only while their
observable value is unchanged.

Exact cumulative snapshots still impose growing output size. Live gaps must be
updated when overlapping, active-pool tuples must be rebuilt when membership
changes, and nonzero-tolerance grouping preserves ordered first-match behavior.
Therefore Revision 2 removes the measured repeated global-history operations
but does not claim formal linear complexity or eliminate every adversarial
quadratic bound.
