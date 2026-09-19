# Research Observer / Journal V1

**ENGINE != OBSERVER != LABELER != HYPOTHESIS EVALUATOR.** This milestone is research infrastructure, not a strategy revision, execution revision, Baseline V2, or trained model.

The engine produces deterministic causal state and its unchanged frozen signals. The observer records compact causal features and the engine's gate decisions, including rejections. The offline labeler inspects future candles only after observations are frozen. A future evaluator may compare predeclared hypotheses/cohorts; no evaluator or new entry rule is implemented here. Future ML could consume separately frozen features and labels; no ML training is implemented.

## Architecture and contracts

```text
completed candle -> frozen OptimizedSequentialResearchEngineV2 -> EngineSnapshot
                                                              |-> existing ResearchSignal
                                                              |-> read-only capture_selection
                                                                     |
                                              ResearchObserver.observe(candle, snapshot, selection)
                                                                     |
                                                      immutable ObservationRecord
                                                                     |
                                                   frozen observation CSV + manifest
                                                                     |
                                               separate offline read_dataset / label_observation
                                                                     |
                                                       FutureLabel CSV + manifest
```

`research/observer.py` receives one completed candle and its current snapshot, never a candle series or future rows. Feed **every** candle, sequentially from index zero, even when no row is exported. Aware timestamps must increase; gaps are preserved and event ages count completed execution candles, not elapsed minutes. Use completed M15 execution and completed H4 context for CP-001.

`capture_selection(engine, snapshot)` must run immediately after `engine.advance()`. It reads Revision 2's already-indexed selections without modifying engine state, config, snapshots, signals or caches. It checks engine type, frozen configuration, and current snapshot identity. It resolves ordinary FVG lifecycle by binary search in the snapshot's existing tuple, avoiding a cumulative scan. Existing selected IFVG ordering is by source-gap identity, not necessarily latest inversion timestamp. The adapter deliberately follows that frozen behavior.

The observer keeps at most five prior candle ranges, two latest MSS references, and two displacement indices. It neither retains snapshots nor copies cumulative histories. Records and nested references are frozen dataclasses with slots. Records can be streamed directly to CSV. The observer state is per instrument/stream; do not share one observer across streams or attach it halfway through a stream. Resume/checkpoint serialization is not implemented.

The default population is all engine-eligible evaluations, accepted and rejected. `include_untriggered=True` also records completed candles without a trigger. Such rows have no selected direction, empty gate-pass/missing tuples, zero gates passed, six gates required, no acceptance, and `no_selected_direction` structural-level reason: gates were **not evaluated**, rather than all failed. Cohort helpers exclude those rows. Their prices, H4 state and bounded per-direction MSS/displacement/PD/liquidity references support descriptive sequence analysis.

## Causal feature construction

- Identity: instrument supplied by caller; canonical UTC completion timestamp; execution index; frozen direction trigger and direction. Priority is current MSS, then current displacement, then the last current terminal liquidity event; no second-direction retry.
- Price: completed OHLC; current dealing-range low/high/midpoint; `(close-low)/(high-low)` when finite; values are not clamped, so a close outside the range can have a normalized position below zero or above one. Price-zone classification comes from the snapshot.
- H4: availability, completed index and aligned completion timestamp, bias, latest structural event identity/level. No in-progress H4 candle is observed.
- Structure: current execution bias, protected high/low swing references, current BOS/MSS references, latest bullish/bearish MSS references and selected-direction MSS age. There is no inferred MSS expiry.
- Liquidity: selected matching consumed event's pool identity, side, event type, lifecycle classification, internal/external pool structure, first source index, confirmation/penetration indices, level and age. The first source index is compact provenance, not a copy of an unbounded equal-level cluster. Historical evidence may qualify; no recency cutoff is added. Compact latest bullish/bearish liquidity references also preserve event ages on untriggered retracement candles.
- Displacement: current flag/direction, candle high-low range and absolute body/range ratio. Reference range is the arithmetic mean of positive high-low ranges in the preceding five candles, only after a complete lookback exists. The threshold is reference times 1.5, body threshold 0.6. These describe the frozen implementation (not a separately invented ATR). Per-direction latest displacement indices permit bar-age calculations without retaining historical candles.
- PD: selected FVG/IFVG type, direction, boundaries, selection index, original source index, age, current/historical flag and known lifecycle state. Both directional selections are also stored as compact references for sequence work. IFVG state is `inverted`; the engine supplies no subsequent IFVG lifecycle validity, so none is invented. Ordinary FVG lifecycle is read causally from the current snapshot, even when the frozen candidate accepts historical/invalidated evidence.
- Gates: `gate_passes` is an ordered six-boolean tuple: H4 context, liquidity event, structural shift, displacement, PD array, premium/discount. Counts, first failure, missing gates and acceptance describe those exact gates. Liquidity target is duplicate evidence, not a seventh requirement. Acceptance is checked against the engine's existing signal.
- Structural levels: hypothetical entry is the completed close for each selected direction, including rejected records. Invalidation is the opposite protected execution swing; no fallback stop or H4 anchor is invented. Risk is the positive absolute distance. Invalid/missing/zero-risk/nonfinite anchors retain an explicit reason. Rejected records with valid geometry can be labeled, but do not become signals.

A current MSS and the required price zone remain logically incompatible under CP-001 V1. This infrastructure does not repair, loosen or reinterpret either requirement.

## Offline labels

`research/labels.py` returns a separate immutable `FutureLabel`, keyed by instrument, timestamp, index, and SHA-256 of the exact observation. It verifies source timestamp and entry-candle OHLC. The caller must also preserve the full source dataset fingerprint in export provenance: entry-row checks alone cannot prove whole-history identity.

The default horizon is **96 subsequent completed execution candles**, excluding the observation candle. The generic label function supports an explicit positive horizon, recorded in every label; CP-001-derived benchmark/smoke labels use 96. No retracement window or MSS-validity window is chosen.

MFE and MAE are nonnegative **full-window** favorable/adverse price excursions, even after a target or invalidation touch. They are descriptive path extrema, not executable profit, post-entry management, or realized R. R-normalized values divide these extrema by valid frozen structural risk. The raw first-touch ages for +1R, +2R and invalidation likewise describe the full observed window, including touches after an earlier stop.

Two separate races compare +1R versus invalidation and +2R versus invalidation. Ties use the existing conservative policy: invalidation wins. An earlier +1R remains a +1R success even if a later +2R/stop candle is ambiguous. Each outcome is `target_first`, `invalidation_first`, `neither_within_horizon`, `censored`, or `unlabelable`. Missing future candles are explicitly censored; they are never reported as a completed horizon. With zero subsequent bars excursions are null. Missing/invalid structural levels produce null R outcomes with the preserved reason; no fallback stop is supplied. Price gaps and same-candle ambiguity use high/low touches without inventing an intrabar route, consistent with the frozen simulator.

Causal feature APIs do not import the labeler or accept label fields. Storage handles the two typed schemas separately and rejects schema mixing. Reading features from an observation CSV restores their immutable types; it does not merge labels. Future outcomes cannot be fed back into this engine through any observer API.

## Descriptive cohorts and sequences

`cohort` supports gates-passed counts, acceptance, trigger type, current MSS, current displacement and exact missing-gate combinations (order independent). This includes 6/6, 5/6, 4/6, missing exactly MSS, missing exactly price zone, and joint missing conditions. Filtering does not create a ResearchSignal, entry rule, optimized configuration or alternative strategy.

In all-candle mode, a later researcher can join retained MSS identities, displacement indices, PD source/formation indices, current zone and H4 bias to study chronological sequences and first retracements. Ages do not imply validity. No expiry period, retracement window, continuity assumption across data gaps, or predeclared-hypothesis evaluator is implemented. Only the latest relevant directional references are retained; this is not an exhaustive event ledger of every pool or simultaneous inversion.

Automatically rewriting strategy rules using outcomes from the same historical sample would turn exploratory observations into training feedback and repeatedly select favorable noise. It would also contaminate subsequent evaluation through data snooping and multiple comparisons. Future hypotheses require separate preregistration, frozen definitions and independently authorized evaluation boundaries; neither validation nor holdout is opened in this milestone.

## Storage and reproducibility

Use `export_dataset` with a **new** output directory, typed record class, source SHA-256, engine/execution SHA-256, configuration SHA-256 and explicit population. Rows must be ordered uniquely by `(instrument, execution_index)`. Bulk outputs belong under ignored `.research-data/`; none are committed.

CSV uses UTF-8, LF, fixed dataclass field order and canonical JSON cells, preserving null, booleans, numbers and bounded nested references. This requires JSON-decoding cells after CSV parsing; `read_dataset` handles it. Feature/label manifests are separate. Label exports require their parent observation-dataset fingerprint; per-row observation fingerprints support exact joins. Different sources, configs, populations, schemas, row bytes or implementation hashes change dataset identity. Observation configuration identity covers frozen EngineConfig; population records the inclusion mode. Label configuration identity should include EngineConfig, horizon and conservative policy, as in the benchmark.

Manifests record schema version, source fingerprint, engine/execution identity, observer implementation path hashes and aggregate hash, configuration identity, population, row count, ordered field names, CSV byte hash and parent observation identity. The dataset fingerprint is SHA-256 of canonical JSON of this manifest payload. No elapsed times, timestamps of export or absolute output paths enter identity. Export verification rehashes table bytes and checks header and row count.

A failed stream export may leave a partial `rows.csv` without a manifest. Such output is not a finalized dataset; retry into a new directory. Files are not overwritten. Atomic directory publication and cross-process write coordination are not implemented. The stdlib JSON float encoding is the reproducibility contract; nonfinite JSON numbers are rejected.

## Usage

```python
observer = ResearchObserver("EURUSD")
for candle in execution.candles:
    snapshot = engine.advance()
    row = observer.observe(candle, snapshot, capture_selection(engine, snapshot))
    if row is not None:
        # Yield to export_dataset; do not store snapshots in the journal.
        yield row

# In a separate offline stage after feature export:
for row in read_dataset(feature_directory, record_type=ObservationRecord):
    label = label_observation(row, source_execution, horizon=96)
    # Export only as FutureLabel, with parent observation manifest identity.
```

The engine's existing `advance()` API retains its own snapshots. The observer does not evict them or alter that behavior. For large studies, engine-owned memory and runtime can dominate; this milestone benchmarks bounded prefixes and does not promise a full-history memory improvement to the frozen engine.


## Exact versioned schemas

The formulas and null semantics are specified above. Tuple fields contain bounded immutable references rather than complete engine objects.

### ObservationRecord

| Field | Type |
|---|---|
| `schema_version` | `str` |
| `instrument` | `str` |
| `execution_timestamp` | `str` |
| `execution_index` | `int` |
| `direction_trigger` | `str \| None` |
| `selected_direction` | `str \| None` |
| `open` | `float` |
| `high` | `float` |
| `low` | `float` |
| `close` | `float` |
| `range_low` | `float \| None` |
| `range_high` | `float \| None` |
| `range_midpoint` | `float \| None` |
| `range_position` | `float \| None` |
| `price_zone` | `str \| None` |
| `h4_available` | `bool` |
| `h4_completed_index` | `int \| None` |
| `h4_completed_timestamp` | `str \| None` |
| `h4_bias` | `str` |
| `h4_event` | `research.observer.EventRef \| None` |
| `structural_bias` | `str` |
| `protected_high` | `research.observer.SwingRef \| None` |
| `protected_low` | `research.observer.SwingRef \| None` |
| `current_bos` | `tuple[research.observer.EventRef, ...]` |
| `current_mss` | `tuple[research.observer.EventRef, ...]` |
| `latest_bullish_mss` | `research.observer.EventRef \| None` |
| `latest_bearish_mss` | `research.observer.EventRef \| None` |
| `matching_mss_age` | `int \| None` |
| `liquidity_available` | `bool` |
| `liquidity_pool_id` | `str \| None` |
| `liquidity_side` | `str \| None` |
| `liquidity_event_type` | `str \| None` |
| `liquidity_state` | `str \| None` |
| `liquidity_structure` | `str \| None` |
| `liquidity_source_index` | `int \| None` |
| `liquidity_confirmation_index` | `int \| None` |
| `liquidity_level` | `float \| None` |
| `liquidity_index` | `int \| None` |
| `liquidity_penetration_index` | `int \| None` |
| `liquidity_age` | `int \| None` |
| `latest_bullish_liquidity` | `research.observer.LiquidityRef \| None` |
| `latest_bearish_liquidity` | `research.observer.LiquidityRef \| None` |
| `current_displacement` | `bool` |
| `displacement_direction` | `str \| None` |
| `candle_range` | `float` |
| `body_range_ratio` | `float \| None` |
| `displacement_reference_range` | `float \| None` |
| `displacement_range_threshold` | `float \| None` |
| `displacement_body_threshold` | `float` |
| `latest_bullish_displacement_index` | `int \| None` |
| `latest_bearish_displacement_index` | `int \| None` |
| `matching_displacement_age` | `int \| None` |
| `pd_type` | `str \| None` |
| `pd_direction` | `str \| None` |
| `pd_lower` | `float \| None` |
| `pd_upper` | `float \| None` |
| `pd_index` | `int \| None` |
| `pd_source_index` | `int \| None` |
| `pd_age` | `int \| None` |
| `pd_state` | `str \| None` |
| `pd_is_current` | `bool \| None` |
| `latest_bullish_pd` | `research.observer.PDRef \| None` |
| `latest_bearish_pd` | `research.observer.PDRef \| None` |
| `gate_passes` | `tuple[bool, ...]` |
| `gates_passed` | `int` |
| `gates_required` | `int` |
| `first_failed_gate` | `str \| None` |
| `missing_gates` | `tuple[str, ...]` |
| `accepted_by_cp001_v1` | `bool` |
| `entry` | `float` |
| `invalidation` | `float \| None` |
| `risk_distance` | `float \| None` |
| `levels_valid` | `bool` |
| `levels_reason` | `str \| None` |

### EventRef

| Field | Type |
|---|---|
| `index` | `int` |
| `direction` | `str` |
| `kind` | `str` |
| `level` | `float \| None` |
| `source_index` | `int \| None` |

### SwingRef

| Field | Type |
|---|---|
| `index` | `int` |
| `confirmed_at` | `int \| None` |
| `price` | `float` |
| `kind` | `str` |
| `structure` | `str` |

### PDRef

| Field | Type |
|---|---|
| `kind` | `str` |
| `direction` | `str` |
| `index` | `int` |
| `source_index` | `int` |
| `lower` | `float` |
| `upper` | `float` |
| `state` | `str` |

### LiquidityRef

| Field | Type |
|---|---|
| `index` | `int` |
| `pool_id` | `str` |
| `side` | `str` |
| `level` | `float` |
| `event_type` | `str \| None` |

### FutureLabel

| Field | Type |
|---|---|
| `schema_version` | `str` |
| `instrument` | `str` |
| `execution_timestamp` | `str` |
| `execution_index` | `int` |
| `observation_fingerprint` | `str` |
| `horizon` | `int` |
| `observed_bars` | `int` |
| `horizon_complete` | `bool` |
| `labelable` | `bool` |
| `unlabelable_reason` | `str \| None` |
| `mfe` | `float \| None` |
| `mae` | `float \| None` |
| `mfe_r` | `float \| None` |
| `mae_r` | `float \| None` |
| `bars_to_1r` | `int \| None` |
| `bars_to_2r` | `int \| None` |
| `bars_to_invalidation` | `int \| None` |
| `one_r_before_invalidation` | `bool \| None` |
| `two_r_before_invalidation` | `bool \| None` |
| `outcome_1r` | `str` |
| `outcome_2r` | `str` |
| `ambiguity_1r` | `bool` |
| `ambiguity_2r` | `bool` |
| `same_candle_policy` | `str` |

## Measured performance and permitted smoke test

Measured locally on 2026-09-19. Each runtime is the median of three untraced runs; peak memory is a separate tracemalloc run, not process RSS. A = engine only; B = engine plus observer; C = engine plus observer plus offline 96-bar labeler. Export/verification time is separate. No concurrent test process ran during these final measurements. Runtime values are descriptive environment-dependent measurements, not identity inputs.

| Synthetic candles | Rows | A seconds | B seconds | B overhead | C seconds | C overhead | A/B/C peak MB (decimal) | Feature/label CSV bytes |
|---|---:|---:|---:|---:|---:|---:|---|---|
| 512 | 131 | 0.1097 | 0.1828 | 66.6% | 0.2766 | 152.1% | 1.144/1.366/1.427 | 243705 / 42367 |
| 1024 | 257 | 0.2616 | 0.4140 | 58.3% | 0.6124 | 134.1% | 2.893/3.316/3.424 | 484142 / 82673 |
| 2048 | 514 | 0.7449 | 1.0607 | 42.4% | 1.2229 | 64.2% | 8.377/9.205/9.409 | 978525 / 165295 |

Feature CSV growth is approximately linear in observation count. Added B-minus-A peak memory is approximately 0.223, 0.422 and 0.827 MB across these sizes, whereas engine-owned retained histories already grow faster. Observer added time at 2,048 candles is approximately 0.316 seconds; no evidence here makes the observer itself impractical. This is not a full-development scalability guarantee. Observer bookkeeping is bounded plus O(log gaps) lookups and current-event consumption; retained output is O(rows), or can be streamed. Labeling is O(rows × horizon), with horizon 96 here.

The smoke test read **only the first 12,000 M1 rows of EURUSD 2018**, from the explicitly named development file; it did not enumerate or open other research partitions. Existing aggregation produced 803 completed M15 candles. All modes emitted zero ResearchSignals and matched signal tuples. It exported 199 rejected observations and 199 separate labels; 99 observations had valid structural geometry and 100 were unlabelable. These are integration counts, not a new hypothesis test or strategy assessment.

Smoke runtime A/B/C: 0.1874/0.3068/0.4526 seconds. B overhead 63.8%; C overhead 141.6%. Peak traced A/B/C: 1.935/2.261/2.348 MB. Feature CSV 330252 bytes; label CSV 64847 bytes; combined export and verification 0.4301 seconds.

Smoke provenance:

- source_fingerprint: `c23f5548e8d5074924c9861205200b2c6511c7706a53a5d6b8d49d2d6f3ae8f0`
- observation_dataset_fingerprint: `4750e1d75b1f6dee9da0291a6b573c155a3d53c94499b6a1e9774be119ffcb09`
- label_dataset_fingerprint: `c8e1b4ded70548a0ac83aa5b52c43ad7064d6737899f283d59b7422039eb3c37`

Two causal examples: 2018-01-02 02:30 UTC, execution index 9, bearish terminal-liquidity trigger, 2/6 gates; and 03:00 UTC, index 11, bullish displacement trigger, 2/6 gates. Both preserve `missing_protected_swing` and are unlabelable for R outcomes. No stop was invented.

All bulk CSVs, manifests and detailed measurement files are local under ignored `.research-data/research-observer-v1-benchmark/` and `.research-data/research-observer-v1-development-smoke/`. They are not committed. Run the benchmark script with a new output directory; `--development` opens only the hard-coded 2018 prefix and must be explicitly authorized.

## Version identity

Observer fingerprint: `018885c10da1606cc72a70a9ecb1067ae8d1cb02367e4a7f570a523d3420a6aa`.

Implementation identity: `7d079ac8f2a58bf65ef699456e64af9ef8ed700e9ec97f7f1be06aabf6d04363`. The canonical artifact is `experiments/research-observer-v1.json`; its per-file hashes cover the observer, labeler, storage and package module. The benchmark hash is recorded separately. This identity is research infrastructure only.

## Final audit

- Focused observer tests: **16 passed** (5.35 seconds), including separate CSV round-trip, both-direction frozen-simulator label equivalence and untriggered liquidity-sequence coverage.
- Focused observer plus engine equivalence tests: **89 passed** (45.25 seconds).
- Boundary-safe full suite: **291 passed, 1 deselected** (51.75 seconds), using `python -m pytest -q -k 'not test_local_raw_acquisition_hashes_are_unchanged'`. The pre-existing deselected test would hash 2023–2024 acquisition files. Synthetic fixtures with later calendar literals are not validation/holdout data.
- Compileall passed over main.py, adapters, backtest, benchmarks, data, research, risk, strategy and tests.
- Git diff whitespace checks and `git fsck --full` passed.
- Repository hygiene passed: no raw research data, generated bulk journal, virtual environment, Python cache, bytecode or logs are tracked or pending for commit.
- Static connectivity/broker-import and broker-operation scans found no calls/imports; credential-pattern scan of tracked and new text files found no credentials. This is a static code scan, not an external vulnerability-database audit.
- Frozen strategy, Baseline V1, Execution Revision 2, original CP-001 development result and zero-candidate diagnostic remain byte-identical to checkpoint `f6db8e26aae584858b23aec77b760bc2bcdf0f5c`.

No strategy optimization, Baseline V2, ML training, live/broker connectivity, validation access or holdout access occurred. Only research infrastructure, tests, schema/identity and documentation are published. Stop after Research Observer V1.
