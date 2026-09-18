# CP-001 Dukascopy data acquisition

CP-001 uses Dukascopy historical data and remains offline after acquisition.
The repository does not contain downloaded market data. The local
`.research-data/` directory is ignored by Git.

## Authoritative source

Use Dukascopy Bank's official Historical Data Export:

<https://www.dukascopy.com/swiss/english/marketwatch/historical/>

Dukascopy documents programmatic bar retrieval through JForex `IHistory`, but
that interface runs in a JForex demo/live context. CP-001 does not accept
credentials or account connectivity. No undocumented web-widget endpoint may
be scripted.

## Validation sample first

Before acquiring multiple years, export these small samples:

| Instrument | Data | Period | Side | Requested dates |
| --- | --- | --- | --- | --- |
| EUR/USD | Candles | 1 minute | BID | 2024-01-02 through 2024-01-03 |
| GBP/USD | Candles | 1 minute | BID | 2024-01-02 through 2024-01-03 |

Select CSV and UTC/GMT when those choices are offered. Preserve the files
exactly as downloaded under:

```text
.research-data/CP-001/raw/sample/EURUSD/
.research-data/CP-001/raw/sample/GBPUSD/
```

Record the UI choices in:

```text
.research-data/CP-001/raw/sample/download-settings.txt
```

The record must include download time, source URL, instrument, selected date
range, timezone, period, BID/ASK side, output format, delimiter, filtering, and
any provider statement about whether timestamps denote bar start or completion.
Do not edit or normalize the raw downloads.

The samples must be inspected before a full download to establish the actual
columns, timestamp convention, timezone, interval coverage, instrument and
price-side identity, OHLC geometry, and volume semantics. The adapter must be
written from that evidence rather than an assumed schema.

## Dukascopy M1 timestamp normalization

Dukascopy's provider timestamp is a candle's **starting/opening time**. This is
documented by the official JForex
[`IHistory`](https://www.dukascopy.com/client/javadoc3/com/dukascopy/api/IHistory.html)
API, whose bar interval parameters and `getBarStart` use bar starting times, and
by Dukascopy's
[`Customizing the platform`](https://www.dukascopy.com/wiki/en/forex-cfds/jforex/customizing-platform/)
documentation, which says candles are named according to their start time.

That provider convention is distinct from M3's canonical convention:
`HistoricalCandle.timestamp` is the instant at which the complete OHLC candle
becomes observable. Consequently, `data.dukascopy.load_dukascopy_m1_csv`
normalizes every row deterministically as:

```text
canonical completion timestamp = provider bar-open timestamp + 1 minute
```

The loader uses the export's explicit `Etc/UTC,Open,High,Low,Close,Volume`
mapping. It preserves OHLC and Volume verbatim as numeric source values and
records both timestamp semantics in candle metadata. Dukascopy's Volume units
are not inferred and must not be used by strategy logic without separate
provider evidence. Missing M1 slots remain reported source gaps: the loader
does not synthesize or forward-fill candles.

## MetaTrader 5 / MetaQuotes-Demo M1 timestamp normalization

The CP-001 MetaTrader 5 exports were produced by native MQL5 `CopyRates()` and
contain the unmodified `MqlRates.time` field. MetaQuotes' official
[`MqlRates` structure](https://www.mql5.com/en/docs/constants/structures/mqlrates)
documentation defines `time` as the period start time. The official native
[`CopyRates`](https://www.mql5.com/en/docs/series/copyrates) documentation
likewise describes bar selection by open time and notes that position zero can
refer to the current, still-uncompleted bar. These native MQL5 sources establish
bar-open semantics; the native `CopyRates` page is not cited as an explicit UTC
statement.

The official MetaTrader 5 Python integration documentation for
[`copy_rates_range`](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py)
and independently for
[`copy_rates_from`](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py)
states that MetaTrader 5 stores tick and bar-open times in UTC and that data
received from the terminal use UTC time. Together, these official sources
establish the export's `provider_time` as a UTC M1 bar-opening timestamp.

M3 uses UTC completion timestamps, so
`data.mt5.load_mt5_metaquotes_m1_csv` applies only this provider-specific rule:

```text
canonical UTC completion timestamp = MqlRates UTC bar-open time + 1 minute
```

The exact expected schema is
`provider_time,open,high,low,close,tick_volume,spread,real_volume`. OHLC is
preserved as numeric candle data. `tick_volume`, `spread`, and `real_volume` are
preserved as uninterpreted source metadata; no economic meaning is assigned to
them. Missing rows remain missing. A source row opened at
`2024.12.31 23:59:00` completes at `2025-01-01T00:00:00+00:00`; this is a
completion-time normalization of the 2024 source row, not access to 2025 source
or holdout data.

## Pre-holdout acquisition after sample acceptance

After both samples pass validation, export M1 BID candles for EUR/USD and
GBP/USD covering 2018-01-01 through 2024-12-31. Store the unmodified source
files under:

```text
.research-data/CP-001/raw/pre-holdout/EURUSD/
.research-data/CP-001/raw/pre-holdout/GBPUSD/
```

Prefer manageable calendar chunks if the exporter permits them. Record every
chunk and its selected boundaries in a manifest. Do not download, inspect, or
place any 2025-2026 holdout data in the workspace before pre-holdout review.
