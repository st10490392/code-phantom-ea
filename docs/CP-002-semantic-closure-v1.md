# CP-002 Semantic Closure V1 implementation record

The [approved specification](CP-002-strategy-spec-and-campaign-design-v1.md) records pre-result researcher decisions. This change implements and verifies them with synthetic candles only. No historical execution is authorized or performed.

## Entry points and readiness

- `research.cp002_v1.Config` declares immutable instrument/dataset, branch and variant identity. `ResearchEngine` accepts chronological completed M15 `Bar` objects and optional completed H4 context. It reuses the unchanged deterministic opposing-BOS primitive and inherited displacement settings. Natural primitive availability governs readiness; calendar reporting does not reset state.
- S × Aggressive is runnable through this in-memory research engine for either structural or same-candle-sweep reversal. There is no file loader, campaign runner, broker or historical execution command. A future caller must supply trustworthy completed candles, source identity and coverage evidence; this gate does not authorize historical research.
- F is **production fail-closed**: the joint M15/M5 production coverage scheduler is not implemented. `StrictCore(..., synthetic=True)` exposes confirmation mechanics for fixtures only. Tests cover strictly subsequent confirmation, reference close, coverage failure and no aggressive fallback. Resolved timing definitions do not imply a verified production stream adapter.
- W is rejected at configuration construction. D20 remains unresolved; no numerical W was selected. Delayed reclaim is also rejected and deferred without a window.
- `research.cp002_v1_labels` is a separate pure endpoint module. Causal modules never import it or accept its `Outcome` records as events. Its only execution in this change is synthetic unit verification.

The earlier `research.cp002` reducer remains an archived generic fixture model. Its production gate still refuses execution. Its multi-child fixture contracts cannot authorize strict V1 FVG ownership.

## Causal records and strict ownership

Immutable experiment, MSS, liquidity-generation, displacement, FVG, setup, transition and entry identities bind parent evidence. A new qualifying MSS creates a generation; replaying identical input is a no-op and conflicting replay is rejected. H4 relationship is latched at creation. No setup-capacity eviction or expiry parameter is introduced.

Each qualifying displacement can own only its exact C1/C2/C3 ordinary FVG, available at C3 completion. Multiple independent liquidity parents can create separate paths referencing that **same** FVG. They do not create additional FVG children. Consumed sweep parents cannot seed another generation. Closing beyond liquidity produces BREAK_PENDING, without a guessed acceptance or reclaim duration.

Lifecycle facts are separate from strategy termination. Contact is a later inclusive range intersection, not percentage invalidation. Frozen MSS protection governs pre-entry invalidation; the latest available protected M15 anchor separately supplies the entry stop. Same-interval contact and structural breach produce AMBIGUOUS_CONTACT_INVALIDATION without an entry. Full gap-through is unfillable. Opposite MSS cancels only pre-entry paths. Terminal identities cannot reactivate.

A entries record the contact interval, completion availability, reference fill, structural snapshot and 2R geometry independently. Open-inside uses open; an expected-side approach uses the near boundary. An unspecified approach is explicitly unlabelable. These are research reference prices, not executable broker fills.

## Coverage, continuity and outcomes

An explicit `Coverage` attestation must cover the exact interval between actual bars to establish a normal closure. It includes a source reference; the engine does not guess a calendar from elapsed time. Missing/incomplete required coverage fails the affected stream and paths closed. No candle is fabricated. A failed stream cannot silently restart with invented detector state.

One engine instance retains state across annual reporting boundaries. Independent datasets have independent namespaces. Authorized contiguous partitions would preserve causal state, but a locked partition must never be opened to finish an outcome. Incomplete authorized tails remain censored.

A labels exclude the contact candle. F labels start at the first full M15 interval beginning strictly after confirmation, including when confirmation falls exactly on an M15 boundary. Both use 96 real full candles. Missing coverage is explicit; ordinary closures add no synthetic candles. Future simultaneous SL/2R hits use STOP_FIRST, unlike pre-entry ambiguity. Neither hit over a complete horizon gives TIMEOUT. Incomplete unresolved horizons give CENSORED. Full-window excursions are descriptive and cannot change transitions.

## Computational limitations

Structure updates incrementally; displacement examines only its inherited rolling window; FVG formation retains three bars. Active paths and unconsumed liquidity are tracked without prefix-wide detector recomputation. Completed causal records, replay fingerprints, structural history and exact-price grouping membership remain in memory. Memory therefore grows with the input and event history: this implementation does not claim a bounded-memory historical runner, persistence or checkpoint recovery. Deterministic fresh replay is tested. Future storage/checkpoint work must preserve all identities and duplicate suppression, not silently evict valid setups.

## Dispositions and verification

The 60 unique D-IDs contain **52 RESOLVED, 1 OPEN, 2 CAMPAIGN_VARIABLE, 4 DEFERRED, 1 EXCLUDED**.

- OPEN: D20, the numerical delayed-displacement window and its exact boundary/timeout contract.
- CAMPAIGN_VARIABLE: D19 (S/W), D50 (A/F); only S/A is production-enabled here.
- DEFERRED: D26, D29 (IFVG), D32 (dealing-leg refinement), D36 (OTE).
- EXCLUDED: D57 (advanced management/execution-cost model).

`tests/test_cp002_v1.py` verifies strict geometry, parent identity, availability times, natural readiness, continuity, coverage/closure distinctions, lifecycle, cancellation, risk snapshots, ambiguity, fills, M5 fixtures, separate endpoint timing and replay/prefix invariance. Existing generic CP-002 tests remain applicable to their archived model. Safe regressions exclude `test_local_raw_acquisition_hashes_are_unchanged`, which reads historical research data. Regression verification uses an external audit hook that rejects `.research-data` access and socket connections. CP-001 implementation/artifacts and Observer V1 implementation/artifacts are unchanged.

Verification for this change: 34 strict focused tests passed; safe regression reported 373 passed and one historical-data test deselected, with zero boundary-access attempts. Frozen CP-001 specification/revision and Observer V1 specification fingerprints verified, as did Observer implementation-file hashes. Protected paths have no diff from `484efd86c8f4209b86be6ee62d3212abb3f7aa9e`. Whitespace and repository hygiene checks passed. No historical candidate, performance or optimization artifact was produced.
