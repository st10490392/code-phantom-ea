"""Strict normalization for Dukascopy M1 Historical Data Export CSV files."""

from dataclasses import replace
from datetime import timedelta

from data.historical import (ColumnMapping, DataValidationError,
                             HistoricalDataset, load_csv)


DUKASCOPY_M1_COLUMNS = ColumnMapping(
    "Etc/UTC", "Open", "High", "Low", "Close", "Volume"
)
DUKASCOPY_M1_PERIOD = timedelta(minutes=1)


def load_dukascopy_m1_csv(source, *, dataset_identifier="dataset"):
    """Load Dukascopy M1 bars and convert bar-open times to completion times.

    Dukascopy names candles by their starting time.  M3 candles are instead
    timestamped at completion, so the only provider-specific transformation is
    an exact one-minute shift.  OHLC and the provider's undocumented Volume
    value are preserved without interpretation or repair.
    """
    provider = load_csv(
        source,
        mapping=DUKASCOPY_M1_COLUMNS,
        dataset_identifier=dataset_identifier,
    )
    normalized = []
    for row_number, candle in enumerate(provider.candles, 2):
        provider_timestamp = candle.timestamp
        try:
            completion_timestamp = provider_timestamp + DUKASCOPY_M1_PERIOD
        except OverflowError as error:
            raise DataValidationError(
                "provider timestamp cannot be converted to M1 completion time",
                row=row_number,
            ) from error
        metadata = candle.source_metadata + (
            ("provider", "Dukascopy"),
            ("provider_period", "M1"),
            ("provider_timestamp", provider_timestamp.isoformat()),
            ("provider_timestamp_semantics", "bar_open"),
            ("canonical_timestamp_semantics", "bar_completion"),
        )
        normalized.append(replace(
            candle,
            timestamp=completion_timestamp,
            source_metadata=metadata,
        ))
    return HistoricalDataset(tuple(normalized), dataset_identifier)
