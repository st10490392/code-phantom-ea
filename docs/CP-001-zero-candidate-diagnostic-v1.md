# CP-001 zero-candidate diagnostic V1

Recovered successfully; no development recomputation was performed. Session 67384 completed with exit code 0 at 2026-09-18 21:10:16.878 UTC (23:10 Johannesburg), duration 4615.644 seconds. Both COMPLETE messages and the final fingerprint were recovered from the persisted command execution record. Host Python process inspection on resumption found no running Python process. Initial Git status contained only the untracked completed diagnostic artifact. The recovered artifact is finalized byte-for-byte without rewriting its payload; omitted Counter keys mean zero.

## Executable logic and reachability

At M15 index i, choose exactly one direction: current MSS first, otherwise current displacement, otherwise the last current consumed liquidity event (ordered by index and pool ID). Without one of these triggers, return empty evidence and no signal. There is no second-direction evaluation or retry.

For the chosen bullish/bearish direction d, the frozen executable conjunction is:

```text
emit = trigger_exists
   AND completed_H4.bias == d
   AND historical_matching_consumed_liquidity_exists(d)
   AND MSS.index == i
   AND displacement.index == i AND displacement.direction == d
   AND (historical_matching_IFVG_exists(d) OR historical_matching_FVG_exists(d))
   AND ((d == bullish AND close <= (range.low + range.high)/2)
     OR (d == bearish AND close >= (range.low + range.high)/2))
```

The last predicate also requires an available range with low < high. Equilibrium tolerance is frozen at zero. All six require flags are true. Displacement uses the frozen five-bar lookback, range multiple 1.5 and body ratio 0.6. Liquidity target is duplicate evidence of liquidity availability, not a seventh independent requirement. Candidate setup records the conjunction.

**Demonstrated cause: logical impossibility under the frozen configuration.** MSS breaks the active structural high/low on the current close; the dealing range uses those same active levels at the same completed index. Bullish MSS implies close > range.high > midpoint, so the required discount/equilibrium predicate is false. Bearish MSS implies close < range.low < midpoint, so premium/equilibrium is false. An unavailable or invalid range also cannot pass. Thus MSS AND premium/discount is unreachable, independently of H4, liquidity, displacement, or PD evidence. This follows from the executable level selection, not merely the observed zero intersections. Delayed evidence cannot rescue a candidate: MSS must be current, and a later retracement has no qualifying historical MSS gate.

Code anchors: strategy/structure.py (_active_level, structural_state, detect_bos, detect_structure_shift); strategy/engine.py (_build_snapshot, _candidate); strategy/optimized_engine.py (_IncrementalStructure); strategy/optimized_engine_v2.py (_build_snapshot, _candidate_v2); strategy/context.py (DealingRange.position).

No implementation divergence or accidental instrumentation defect was found. The contradiction is in the frozen combination of requirements, shared by the oracle and optimized implementation. No repair is proposed or applied. Synthetic regression checks exercise both directions and exact snapshot-cache eviction equivalence; they are not market-data runs or parameter optimization.

MSS rarity has an additional structural explanation: only extensions are promoted to external swings; active external extrema persist rather than following every internal pivot, and each swing identity breaks once. H4 bias likewise persists until another qualifying structural break. These semantics explain why local price movement need not create a new MSS or change H4 bias.

Historical consumed liquidity has no recency limit. PD evidence prefers a matching historical IFVG over a matching ordinary FVG, even if the FVG is newer. No maximum evidence age, current price overlap, or currently unmitigated/valid ordinary-FVG filter is required. The diagnostic records selected PD type and age, not a full histogram of gap lifecycle states. These are frozen known limitations, not newly discovered defects. MSS and matching displacement must be current; liquidity and PD evidence may come from different historical candles.


## EURUSD

Completed M15 candles: 124322; evaluations: 30415; emitted ResearchSignals: 0.


| Gate | Individual passes | Cumulative passes |
|---|---:|---:|
| HTF context | 15097 | 15097 |
| liquidity event | 30413 | 15097 |
| structural shift | 7 | 1 |
| displacement | 10060 | 0 |
| PD array | 30414 | 0 |
| premium/discount | 15283 | 0 |

First failure uses the frozen conjunction order; it does not mean later evidence was not evaluated.

| Requirement | Bullish | Bearish | Total |
|---|---:|---:|---:|
| HTF context | 14323 | 995 | 15318 |
| liquidity event | 0 | 0 | 0 |
| structural shift | 975 | 14121 | 15096 |
| displacement | 0 | 1 | 1 |
| PD array | 0 | 0 | 0 |
| premium/discount | 0 | 0 | 0 |

Pairwise intersection matrix among evaluated candles; diagonal is individual passes. H=H4, L=liquidity, M=MSS, D=displacement, A=PD array, Z=price zone.

| | H | L | M | D | A | Z |
|---|---:|---:|---:|---:|---:|---:|
| H | 15097 | 15097 | 1 | 5086 | 15097 | 3926 |
| L | 15097 | 30413 | 7 | 10058 | 30412 | 15283 |
| M | 1 | 7 | 7 | 4 | 7 | 0 |
| D | 5086 | 10058 | 4 | 10060 | 10060 | 4997 |
| A | 15097 | 30412 | 7 | 10060 | 30414 | 15282 |
| Z | 3926 | 15283 | 0 | 4997 | 15282 | 15283 |

| Passed / 6 | Bullish | Bearish | Total |
|---|---:|---:|---:|
| 0/6 | 0 | 0 | 0 |
| 1/6 | 0 | 0 | 0 |
| 2/6 | 2550 | 118 | 2668 |
| 3/6 | 8902 | 7465 | 16367 |
| 4/6 | 3802 | 6261 | 10063 |
| 5/6 | 44 | 1273 | 1317 |
| 6/6 | 0 | 0 | 0 |

All 5/6 near misses lack MSS. Strongest means five gates passed; ties are ordered by timestamp, not profitability. All eight earliest strongest observations are retained below, together with earliest per-direction liquidity, displacement and MSS examples. Full evidence indices and source IDs are in the JSON.

| UTC completion | Direction | Trigger | Passes | Missing gates |
|---|---|---|---:|---|
| 2018-01-02T02:30:00Z | bearish | current_terminal_liquidity | 2/6 | HTF context, structural shift, displacement, PD array |
| 2018-01-02T03:00:00Z | bullish | current_displacement | 2/6 | HTF context, liquidity event, structural shift, premium/discount |
| 2018-01-02T03:30:00Z | bullish | current_terminal_liquidity | 2/6 | HTF context, structural shift, displacement, premium/discount |
| 2018-01-02T04:00:00Z | bearish | current_displacement | 3/6 | HTF context, structural shift, premium/discount |
| 2018-01-02T04:45:00Z | bearish | current_mss | 3/6 | HTF context, displacement, premium/discount |
| 2018-01-02T08:00:00Z | bullish | current_mss | 4/6 | HTF context, premium/discount |
| 2018-01-08T03:00:00Z | bullish | current_displacement | 5/6 | structural shift |
| 2018-01-11T17:30:00Z | bearish | current_displacement | 5/6 | structural shift |
| 2018-01-11T22:45:00Z | bearish | current_displacement | 5/6 | structural shift |
| 2018-01-12T07:45:00Z | bearish | current_displacement | 5/6 | structural shift |
| 2018-02-28T02:30:00Z | bullish | current_displacement | 5/6 | structural shift |
| 2018-02-28T05:30:00Z | bullish | current_displacement | 5/6 | structural shift |
| 2018-02-28T08:45:00Z | bullish | current_displacement | 5/6 | structural shift |
| 2018-03-01T00:15:00Z | bullish | current_displacement | 5/6 | structural shift |

Additional context (counts over all M15 candles unless noted):

- direction_counts: {"bearish": 15117, "bullish": 15298}
- direction_trigger_counts: {"current_displacement": 10056, "current_mss": 7, "current_terminal_liquidity": 20352}
- completed_h4_context_candles: 124307
- h4_bias_counts: {"bearish": 116043, "bullish": 8008, "neutral": 271}
- dealing_range_available_candles: 124299
- liquidity_terminal_event_types: {"reclaim_sweep": 4937, "structural_break": 10866, "wick_sweep": 14610}
- pd_array_types: {"Gap": 5, "InvertedFairValueGap": 30409}
- pd_array_age_execution_bars: {"count": 30414, "maximum": 121, "mean": 14.26435194318406, "minimum": 0}

## GBPUSD

Completed M15 candles: 124324; evaluations: 30826; emitted ResearchSignals: 0.


| Gate | Individual passes | Cumulative passes |
|---|---:|---:|
| HTF context | 15432 | 15432 |
| liquidity event | 30825 | 15432 |
| structural shift | 7 | 0 |
| displacement | 10068 | 0 |
| PD array | 30825 | 0 |
| premium/discount | 15290 | 0 |

First failure uses the frozen conjunction order; it does not mean later evidence was not evaluated.

| Requirement | Bullish | Bearish | Total |
|---|---:|---:|---:|
| HTF context | 14271 | 1123 | 15394 |
| liquidity event | 0 | 0 | 0 |
| structural shift | 1147 | 14285 | 15432 |
| displacement | 0 | 0 | 0 |
| PD array | 0 | 0 | 0 |
| premium/discount | 0 | 0 | 0 |

Pairwise intersection matrix among evaluated candles; diagonal is individual passes. H=H4, L=liquidity, M=MSS, D=displacement, A=PD array, Z=price zone.

| | H | L | M | D | A | Z |
|---|---:|---:|---:|---:|---:|---:|
| H | 15432 | 15432 | 0 | 5094 | 15432 | 5703 |
| L | 15432 | 30825 | 7 | 10067 | 30824 | 15290 |
| M | 0 | 7 | 7 | 3 | 7 | 0 |
| D | 5094 | 10067 | 3 | 10068 | 10068 | 4973 |
| A | 15432 | 30824 | 7 | 10068 | 30825 | 15289 |
| Z | 5703 | 15290 | 0 | 4973 | 15289 | 15290 |

| Passed / 6 | Bullish | Bearish | Total |
|---|---:|---:|---:|
| 0/6 | 0 | 0 | 0 |
| 1/6 | 0 | 0 | 0 |
| 2/6 | 3669 | 270 | 3939 |
| 3/6 | 8197 | 6647 | 14844 |
| 4/6 | 3435 | 6743 | 10178 |
| 5/6 | 117 | 1748 | 1865 |
| 6/6 | 0 | 0 | 0 |

All 5/6 near misses lack MSS. Strongest means five gates passed; ties are ordered by timestamp, not profitability. All eight earliest strongest observations are retained below, together with earliest per-direction liquidity, displacement and MSS examples. Full evidence indices and source IDs are in the JSON.

| UTC completion | Direction | Trigger | Passes | Missing gates |
|---|---|---|---:|---|
| 2018-01-02T02:45:00Z | bearish | current_terminal_liquidity | 2/6 | HTF context, structural shift, displacement, PD array |
| 2018-01-02T03:15:00Z | bullish | current_displacement | 2/6 | HTF context, liquidity event, structural shift, premium/discount |
| 2018-01-02T04:15:00Z | bearish | current_mss | 3/6 | HTF context, displacement, premium/discount |
| 2018-01-02T04:30:00Z | bullish | current_terminal_liquidity | 3/6 | HTF context, structural shift, displacement |
| 2018-01-02T05:30:00Z | bullish | current_mss | 3/6 | HTF context, displacement, premium/discount |
| 2018-01-02T13:30:00Z | bearish | current_displacement | 3/6 | HTF context, structural shift, premium/discount |
| 2018-01-06T00:00:00Z | bullish | current_displacement | 5/6 | structural shift |
| 2018-01-08T03:30:00Z | bullish | current_displacement | 5/6 | structural shift |
| 2018-01-08T12:45:00Z | bullish | current_displacement | 5/6 | structural shift |
| 2018-01-09T03:45:00Z | bullish | current_displacement | 5/6 | structural shift |
| 2018-01-09T07:45:00Z | bullish | current_displacement | 5/6 | structural shift |
| 2018-01-12T04:00:00Z | bearish | current_displacement | 5/6 | structural shift |
| 2018-01-12T07:30:00Z | bearish | current_displacement | 5/6 | structural shift |
| 2018-01-12T09:00:00Z | bearish | current_displacement | 5/6 | structural shift |

Additional context (counts over all M15 candles unless noted):

- direction_counts: {"bearish": 15408, "bullish": 15418}
- direction_trigger_counts: {"current_displacement": 10065, "current_mss": 7, "current_terminal_liquidity": 20754}
- completed_h4_context_candles: 124309
- h4_bias_counts: {"bearish": 115068, "bullish": 8937, "neutral": 319}
- dealing_range_available_candles: 124319
- liquidity_terminal_event_types: {"reclaim_sweep": 4923, "structural_break": 10908, "wick_sweep": 14994}
- pd_array_types: {"Gap": 2, "InvertedFairValueGap": 30823}
- pd_array_age_execution_bars: {"count": 30825, "maximum": 141, "mean": 14.437469586374696, "minimum": 0}

## Artifact identity and boundaries

Canonical diagnostic fingerprint: `050e7809a07323c90d3517bd61643f0d880797d2651ae0d5eea0f1054c0c6d5d`. Algorithm: SHA-256 of sorted compact JSON of the diagnostic payload.

Original development result canonical fingerprint: `57671bc3eade824bdd97b0cf6d680e43641f093b7555049e578115f6f77e606e`; raw file SHA-256: `43ae8a681b9ab72e754ed94120c73625bac9e4c6855a5ccdffb6b15f88c2e4d7`. Original file verified byte-identical to HEAD before reporting.

Frozen CP-001 strategy and EngineConfig unchanged. No parameter optimization. No Baseline V2. No 2023–2024 validation data or 2025–2026 holdout data accessed. Source review and synthetic test literals containing those years are not access to research partitions. Stop after diagnostic; no validation or holdout run.


## Recovery provenance and audit

The exact recovered runner is preserved at `benchmarks/cp001_zero_diagnostic.py` (SHA-256 `cac0044e288432c327749f042a5d3218c038a24f902ee8f92d4a5aa65a6f2075`). It was copied, not rerun. Its final artifact write occurs only after both full instrument loops and before/after original-result byte-hash assertions. Persisted stdout records both input fingerprint assertions, full progress through 120,000 candles, both COMPLETE messages, and the matching final diagnostic fingerprint; the command record reports exit code 0. The original script's single final artifact write supplies no per-instrument checkpoint, but recovery of this successful run made restart recovery unnecessary.

Audit on 2026-09-19:

- Targeted diagnostic, oracle/Revision 1/Revision 2 equivalence, and frozen execution identity tests: 77 passed in 29.77 seconds.
- Boundary-safe full suite: `python -m pytest -q -k 'not test_local_raw_acquisition_hashes_are_unchanged'`: 275 passed, 1 deselected in 32.00 seconds. The deselected pre-existing test hashes local 2023–2024 acquisition files; running it would violate the research boundary. Synthetic fixtures with calendar years beyond development do not contain validation/holdout observations.
- `python -m compileall -q main.py adapters backtest benchmarks data risk strategy tests`: passed.
- `git diff --check`: passed; `git fsck --full`: passed.
- Repository hygiene: no tracked research data, virtual environment, Python cache, bytecode or logs; existing hygiene regression passed.
- Static AST scan of tracked Python plus new diagnostic Python files: no network/broker-library imports. Credential-pattern scan: no findings. This is a static scan, not an external vulnerability-database audit or network probe.
- Original development artifact byte-identical to HEAD; canonical fingerprint matches the requested value. Strategy and baseline diff empty.
- Instrumentation preserves EURUSD ResearchSignals = 0 and GBPUSD ResearchSignals = 0, matching the committed development run. The full market runs were recovered, not recomputed; snapshot-cache eviction additionally passed synthetic oracle equivalence.

Only the diagnostic artifact, preserved diagnostic runner, diagnostic regression tests, and this report are included in the diagnostic commit. Commit identity and remote synchronization are reported after publication; no self-referential commit hash is embedded here.
