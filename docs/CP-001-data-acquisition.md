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
