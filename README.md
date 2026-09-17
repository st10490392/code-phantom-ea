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

## Sequential multi-timeframe engine

`SequentialResearchEngine` advances exactly one completed execution candle per
call to `advance`. Each immutable `EngineSnapshot` is built only from the
execution prefix ending at that index. Detectors never receive later execution
candles. Snapshots expose timestamp alignment, HTF context, execution structure,
active liquidity, current structure/liquidity events, causal imbalance states,
displacement, dealing-range position, ordered evidence, and an optional
`ResearchSignal`.

`ContextSeries` copies caller collections into tuples so later caller mutation
cannot alter historical engine state. Running a full history and running every
prefix independently are required to produce identical snapshots at matching
indices.

### MTF completion and alignment

Timestamps are supplied by the caller and interpreted as candle completion
timestamps. An execution candle sees the latest HTF candle whose timestamp is
less than or equal to the execution timestamp. Equality therefore means the HTF
candle has just completed; a later timestamp remains invisible. Series used for
MTF alignment require strictly increasing, mutually comparable timestamps.
Timeframe labels do not imply durations, and missing timestamps cause a clear
error rather than guessed alignment.

HTF bias is derived from the existing confirmed Structure v1.2 BOS/MSS events.
Until directional evidence exists, it remains neutral. External and protected
levels and the latest causal event are retained in the HTF snapshot.

### Candidate generation

Candidate evidence follows the canonical order:

`HTF context -> liquidity target/event -> structural shift -> displacement -> PD array -> premium/discount -> candidate setup`

Thresholds and required evidence are explicit in `EngineConfig`. Evidence
retains source indices or identities where available. A candidate is emitted
only on a completed candle after its configured requirements exist. It is an
immutable research observation with no execution method.

## Historical simulation

`backtest.simulator.simulate_candidates` applies caller-supplied hypothetical
entry, invalidation, and objective references to later candles only. The signal
candle itself is never used to resolve its outcome. Levels must be finite and
must place entry strictly between invalidation and objective in the appropriate
direction.

Because OHLC data cannot reveal intrabar path, a candle touching objective and
invalidation is ambiguous. The default `conservative` policy records a loss;
the caller may explicitly choose the documented `optimistic` policy. Candidates
that do not touch either reference within available history or the optional bar
limit remain unresolved. These are hypothetical research outcomes, not orders.
Touches are evaluated from the completed candle's full high/low. An opening gap
beyond a reference therefore counts as touching it. If the same completed candle
also touches the opposing reference, the selected same-candle policy still
controls the result; the engine does not infer an intrabar path from the open.

`calculate_metrics` reports candidate/resolution counts, wins, losses, resolved
win rate, average and cumulative R, expectancy in R, peak-to-trough drawdown in
cumulative R, and longest win/loss streaks. Empty and entirely unresolved sets
return safe zero-valued rates and aggregates. These metrics are descriptive
backtesting output, not evidence of predictive edge.

Code Phantom EA remains offline research/backtesting infrastructure. It has no
broker connection, live feed, credential handling, position sizing, or order
execution interface.

## Historical data and reproducible experiments

Milestone 3 adds a standard-library-only ingestion and experiment layer. It
does not require pandas or numpy and performs no network access.

### Canonical data and CSV ingestion

`data.historical.HistoricalCandle` stores a completion timestamp, OHLC, optional
volume, and optional source metadata. Timestamps are normalized to timezone-aware
UTC. OHLC and volume contribute to dataset identity; source metadata, filename,
path, and the human-readable dataset identifier do not.

`load_csv` accepts either an explicit `ColumnMapping` or an unambiguous default
header mapping. Default timestamp aliases are `timestamp`, `time`, `date`, and
`datetime`; if more than one is present, loading fails rather than guessing.
Naive timestamps require an explicit IANA timezone or timezone object. DST gaps
and ambiguous folds are rejected. ISO-8601 offsets and `Z` are normalized to UTC.

Before a dataset is accepted, ingestion rejects empty files, missing columns,
inconsistent row shapes, malformed or non-finite numbers, invalid OHLC geometry,
duplicate timestamps, and timestamps moving backward. Errors identify the CSV
data row when applicable. Strict loading produces no repaired rows.

A minimal file is:

```csv
timestamp,open,high,low,close,volume
2026-01-01T10:00:00Z,100,102,99,101,25
2026-01-01T10:05:00Z,101,103,100,102,30
```

`DatasetQualityReport` records count, UTC range, ordering, duplicates, observed
interval consistency, and invalid rows. Missing intervals are reported only
when the caller supplies an expected interval; a timeframe label alone never
implies missing candles.

### Timeframe aggregation

`aggregate_timeframe` uses UTC Unix-epoch-aligned `(bucket_start, bucket_end]`
buckets. A source candle completing exactly on a boundary belongs to the bucket
ending on that boundary. Aggregated open/high/low/close use first/max/min/final
values, and volume is summed only when every source candle has volume.

The aggregated candle timestamp is its bucket completion time. The final bucket
is dropped by default unless its final source candle completes exactly at that
boundary. `retain_incomplete_final=True` is an explicit caller assertion to
retain it; it still carries the actual bucket-end completion timestamp and is
therefore not visible to the sequential engine before that time.

### Experiment configuration and identity

`ExperimentConfig` is frozen and contains the experiment and dataset IDs,
execution and optional HTF intervals, complete `EngineConfig`, OTE values,
candidate requirements, and complete `SimulationConfig`. Serialization is
stable-key JSON containing all resolved defaults. Loading requires the exact
schema: missing, unknown, duplicate, non-finite, or incorrectly typed
strategy-affecting fields are rejected.

Example construction:

```python
from backtest.experiment import ExperimentConfig, ExperimentRunner, SimulationConfig

config = ExperimentConfig(
    experiment_name="example-research",
    dataset_identifier="sample-2026-01",
    execution_timeframe="5m",
    execution_interval_seconds=300,
    higher_timeframe_seconds=3600,
    simulation=SimulationConfig(
        risk_distance=1.0,
        reward_risk=2.0,
        same_candle_policy="conservative",
    ),
)
result = ExperimentRunner(dataset, config).run()
```

The dataset fingerprint is SHA-256 over deterministic JSON containing canonical
UTC completion timestamps, normalized OHLC, and volume. The experiment
fingerprint is SHA-256 over that dataset fingerprint, the complete normalized
configuration, and `RESEARCH_SCHEMA_VERSION`. The schema version changes when
report/fingerprint interpretation changes; reproducibility is not based solely
on a Git commit.

`ExperimentRunner` constructs timeframe contexts, advances
`SequentialResearchEngine` candle by candle, collects immutable candidates,
applies the configured hypothetical research rule, calculates metrics, and
returns an immutable `ExperimentResult`. Reports export deterministic local JSON
and one-row-per-candidate CSV. Text fields with spreadsheet formula prefixes are
escaped. Nothing is uploaded, and exported outcomes remain hypothetical research
observations rather than executable orders or evidence of predictive edge.

## Tests

```sh
python3 -m pytest -q
```
