"""Strict normalization for CP-001 MetaTrader 5 M1 CopyRates exports."""

import csv
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

from data.historical import (DataValidationError, HistoricalCandle,
                             HistoricalDataset)


MT5_M1_COLUMNS = (
    "provider_time", "open", "high", "low", "close",
    "tick_volume", "spread", "real_volume",
)
MT5_M1_PERIOD = timedelta(minutes=1)


def _number(value: str, name: str) -> float:
    try:
        result = float(value)
    except ValueError as error:
        raise DataValidationError(f"malformed {name} value {value!r}") from error
    if not math.isfinite(result):
        raise DataValidationError(f"{name} must be finite")
    return result


def _integer(value: str, name: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise DataValidationError(f"malformed {name} value {value!r}") from error


def _provider_time(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y.%m.%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError as error:
        raise DataValidationError(
            f"malformed provider_time value {value!r}"
        ) from error


def load_mt5_metaquotes_m1_csv(source, *, dataset_identifier="dataset"):
    """Load one strict MetaQuotes CopyRates M1 CSV into canonical candles.

    ``provider_time`` is the MqlRates UTC period-open timestamp. A complete M1
    candle becomes causally visible exactly one minute later. Provider volume
    and spread fields are retained as uninterpreted source metadata; gaps are
    neither repaired nor filled.
    """
    close_stream = False
    if hasattr(source, "read"):
        stream = source
    else:
        stream = Path(source).open("r", encoding="utf-8", newline="")
        close_stream = True
    try:
        reader = csv.reader(stream, strict=True)
        try:
            header = next(reader)
        except StopIteration as error:
            raise DataValidationError("CSV header is missing") from error
        except csv.Error as error:
            raise DataValidationError(f"malformed CSV: {error}", row=1) from error
        if tuple(header) != MT5_M1_COLUMNS:
            raise DataValidationError(
                "expected exact MT5 schema: " + ",".join(MT5_M1_COLUMNS)
            )

        candles = []
        try:
            for row_number, row in enumerate(reader, 2):
                if len(row) != len(MT5_M1_COLUMNS):
                    raise DataValidationError("inconsistent row shape", row=row_number)
                try:
                    provider_time = _provider_time(row[0])
                    tick_volume = _integer(row[5], "tick_volume")
                    spread = _integer(row[6], "spread")
                    real_volume = _integer(row[7], "real_volume")
                    if tick_volume < 0 or real_volume < 0:
                        raise DataValidationError("volume fields cannot be negative")
                    try:
                        completion_time = provider_time + MT5_M1_PERIOD
                    except OverflowError as error:
                        raise DataValidationError(
                            "provider timestamp cannot be converted to M1 completion time"
                        ) from error
                    candles.append(HistoricalCandle(
                        completion_time,
                        _number(row[1], "open"),
                        _number(row[2], "high"),
                        _number(row[3], "low"),
                        _number(row[4], "close"),
                        source_metadata=(
                            ("provider", "MetaTrader 5 / MetaQuotes-Demo"),
                            ("provider_period", "M1"),
                            ("provider_timestamp", provider_time.isoformat()),
                            ("provider_timestamp_timezone", "UTC"),
                            ("provider_timestamp_semantics", "bar_open"),
                            ("canonical_timestamp_semantics", "bar_completion"),
                            ("tick_volume", str(tick_volume)),
                            ("spread", str(spread)),
                            ("real_volume", str(real_volume)),
                        ),
                    ))
                except DataValidationError as error:
                    raise DataValidationError(str(error), row=row_number) from error
        except csv.Error as error:
            raise DataValidationError(
                f"malformed CSV: {error}", row=reader.line_num
            ) from error
        try:
            return HistoricalDataset(tuple(candles), dataset_identifier)
        except DataValidationError as error:
            if error.row is not None:
                raise DataValidationError(
                    str(error).split(": ", 1)[-1], row=error.row + 1
                ) from error
            raise
    finally:
        if close_stream:
            stream.close()
