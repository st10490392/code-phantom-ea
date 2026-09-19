# CP-002 temporal core V1 — synthetic implementation boundary

Freeze commit: `23989d8` (`docs: freeze CP-002 temporal strategy v1`).
Authority: [approved Freeze V1 and decision register](CP-002-strategy-spec-and-campaign-design-v1.md).

## Implemented scope

`research/cp002.py` is a separate event-driven temporal reducer and immutable
observation layer. It neither changes nor wraps CP-001 candidate selection or
Observer V1 semantics. It accepts typed causal evidence, not file paths or future
labels. No historical-data adapter, campaign runner, outcome labeler, optimizer,
connectivity or order operation is included.

The implementation is a **coherent synthetic-only slice**, not a runnable frozen
market strategy. The approved architecture is implemented; missing strategy
definitions are deliberately not filled in by code.

| API / state | Contract |
|---|---|
| `Experiment` | Names instrument/source, branch, entry and displacement variant. Canonical content hash namespaces generation, area, transition and entry IDs. |
| `Experiment.require_runnable()` | Rejects every current production campaign because association/validity/coverage semantics are unresolved. W remains rejected even when a synthetic fixture supplies a window. No runner exists. |
| `SyntheticContract` | Explicit `fixture:` namespace plus allowed fixture gap states. It certifies only synthetic parent-association and guard evidence, never a research rule or production override. |
| `M15Frame` | One completed candle, current protected-structure snapshot, optional newly completed H4 reference, and tuples of current liquidity/MSS/displacement/FVG/validity events. Whole batch validates before mutation. |
| `M5Frame` | F-only confirmation/validity events. No M1 refinement input. Confirmation must be strictly later than contact availability. |
| `Generation` | Immutable MSS, branch, selected optional sweep and H4 creation classification. Displacement is latched once through immutable state replacement. Later MSS creates another generation. |
| `Area` | One independently tracked FVG with generation/displacement parent, own readiness/contact/state/reason. Every associated sibling is retained. No mutable latest-gap ownership. |
| `Transition` | Immutable IDs, previous/new state, availability, cause and parents. Exact batch replays are no-ops; changed content under an existing evidence or batch identity is rejected. |
| `Entry` | A-only completed-M15-close research reference after strictly later inclusive contact. Includes frozen causal protected M15 stop, source swing/snapshot, 2R geometry, parent chain and inherited horizon/ambiguity metadata. Metadata is not a computed outcome. |

## Causal evidence and fail-closed rules

The reducer consumes existing `StructureShift`, `Displacement`, `LiquidityEvent`,
`Gap`, `StructureState` and `SwingPoint` types. It checks completion/index
availability and the opposing-BOS shape of MSS evidence. It is not a substitute
for running/authenticating the frozen detectors upstream. Producer event IDs
must identify actual immutable source events, including pool generations; no
production ID/association adapter has been supplied.

FVG-to-impulse source-triplet/leg association remains D25/D27. Tests supply an
explicit fixture association, never a latest-FVG heuristic. Without a matching
fixture contract, an associated area terminates `UNLABELABLE` with the unresolved
association reason. Unrelated displacement IDs cannot attach arrays to a setup.

Pre-entry structural/array cancellation and priority remain partly unresolved
(D28/D40/D42/D43/D44). Each subsequent applicable frame must supply current
fixture validity evidence for an active area. Missing/unknown authority fails
closed as `UNLABELABLE`; explicit structural/array invalidation terminates that
area. This interface represents guards without inventing a market predicate.
Terminal areas never reactivate; a sibling's distinct validity remains independent.

S requires a same-completion matching displacement. Missing/opposite expansion
terminates that generation's prerequisite path, not other setups. Fixture-only W
uses a required positive local value, inclusive observed-M15 index difference and
the first same-direction displacement. This fixture deadline is not an approved
W value or an N-candle setup expiry. Ready setups have no age expiry or capacity
eviction.

Creation H4 uses the latest supplied completed context; absent new H4 evidence
retains that causal context. A stream with no H4 evidence is unavailable.
Regressing/conflicting or future H4 is rejected. Later context cannot rewrite
generation classification or become an eligibility gate.

The A contact predicate is inclusive low/high intersection with the whole FVG;
close-inside is unnecessary. Observation/entry occurs at completion using its
close, not an inferred intrabar limit fill. Entry uses that completion's protected
M15 swing, with no fallback, buffer or future anchor. Invalid geometry preserves
contact and emits an explicit unlabelable reason instead of an entry.

F records contact, arms M5, and accepts strictly later same-direction M5 proxy
confirmation. A valid confirmation is preserved on the area, which terminates
`UNLABELABLE: m5_confirmed_entry_disabled_D51_D55_D56`. That reason means the
unapproved fill/outcome path is blocked, not that the structural confirmation
failed. There is no A fallback and no use of a future enclosing M15 snapshot.

## Ordering, coverage and resources

Input streams must be monotonic UTC completions. At equal completion, M15 must
precede M5; reversed arrival is rejected, not assigned a different precedence.
Events within a completed frame are serialized by immutable ID. Equal liquidity
and MSS completion permits co-availability only.

The core checks consecutive indices and elapsed M15/M5 completion intervals,
plus explicit coverage flags. A gap/incomplete frame terminally fails active
areas and pending generations with `DATA_COVERAGE_FAILURE`; the stream remains
halted for new setup formation. This is conservative failure, not a new weekend
reset policy or interpolation. D03/D45 must define a real source's starting,
weekend and reset contract before an adapter can be authorized. Fixture streams
may start at a declared nonzero index with preconfirmed detector evidence.

Work scans waiting generations and active areas, not full candle prefixes. The
displacement index routes new arrays only to matching generations. All areas,
identity hashes and transition/entry records remain in memory in this slice:
memory is O(events + generations + areas + outputs), with **no hidden cap** and
no claim of bounded full-history memory. A later streaming ledger/persistence
implementation needs separate resource and identity tests.

Replay means rebuilding a new core from the same ordered batches, or idempotently
resending identical batches to the existing core. Both are tested. There is **no
serialized checkpoint/restore API**; do not start a new core midway and claim
equivalent state. Immutable snapshots returned earlier do not change when new
events are processed. Configuration properties cannot be replaced midstream.

## Remaining implementation/research blockers

Post-freeze dispositions: **37 RESOLVED, 16 OPEN, 2 CAMPAIGN_VARIABLE,
4 DEFERRED, 1 EXCLUDED**. D19 and D50 remain the two campaign dimensions.

OPEN IDs: D03 (start/warm-up), D10 (qualifying pool class), D15 (liquidity parent
selection), D16 (reuse/regrouping), D20 (unfrozen W), D25/D27 (FVG/impulse
association), D28 (lifecycle eligibility), D40/D42/D43/D44 (pre-entry
cancellation/invalidation/precedence), D45 (real coverage/calendar policy),
D51/D55/D56 (M5 entry/fill/horizon/partial-interval semantics).

Market-data integration, authentic event association/validity producers,
persistent checkpoints, streamed outputs, campaign execution and labels are not
implemented. Deferred model families remain absent. No result path is unlocked
by fixture-local values. Do not begin historical research after this milestone.

## Verification

Focused tests in `tests/test_cp002_temporal.py` exercise both directions,
descriptive H4 classes, branches, sweep/break distinction, equal-time causality,
S and fixture W, sibling identities and simultaneous contact, causal stops,
terminal behavior, disabled F entry, future-prefix invariance, immutable inputs,
idempotent replay and 200 independent synthetic sibling identities without
eviction. A detector-backed synthetic fixture also obtains MSS/displacement
from the existing repository primitives. No market CSV is used.

The ordinary suite must exclude
`test_local_raw_acquisition_hashes_are_unchanged`, which would read local
historical acquisition files including validation. Synthetic fixtures containing
later calendar literals are not historical data access.

Completed verification:

- Focused CP-002 synthetic tests: **48 passed** (1.40 seconds).
- Boundary-safe repository regression: **339 passed, 1 deselected** (52.46
  seconds), including CP-001 equivalence/identity, Observer V1 and repository
  hygiene tests. The deselection is exactly the historical acquisition-hash
  test named above; no full-suite claim includes it.
- Regression ran under a temporary Python audit hook rejecting `.research-data`
  file reads/enumeration and socket connections: **zero attempted accesses**.
  The wrapper explicitly added the repository to Python's import path after an
  initial collection-only import-path failure; no repository code was changed
  to correct that wrapper.
- CP-001 Baseline V1, Execution Revision 2 and Observer V1 canonical artifact
  fingerprints verified. Observer implementation hashes match. Existing
  strategy/backtest/data/adapter/risk code, research V1 modules and all frozen
  experiment artifacts are unchanged against `96323b4`.
- New-file and Git whitespace checks, syntax parsing and focused static
  import/file-operation/credential-pattern checks passed. The new core imports
  only stdlib and existing primitive modules; it has no labeler, data loader,
  broker or network import.

No historical inputs were read or modified. No CP-002 market outcomes,
historical candidate counts, performance artifacts or optimization were
produced. Validation and holdout were untouched. Existing simulator regression
tests used their synthetic fixtures only. Stop at this tested synthetic core;
the unresolved research/integration blockers above remain in force.
