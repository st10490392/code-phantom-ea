import csv
import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from io import StringIO
from pathlib import Path
from typing import Mapping, TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from strategy.structure import Candle
from strategy.timeframes import ContextSeries


class DataValidationError(ValueError):
    """Historical data is malformed; ``row`` is the one-based CSV data row."""

    def __init__(self, message: str, row: int | None = None):
        self.row = row
        prefix = f"row {row}: " if row is not None else ""
        super().__init__(prefix + message)


def _finite_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class ColumnMapping:
    timestamp: str
    open: str
    high: str
    low: str
    close: str
    volume: str | None = None


@dataclass(frozen=True)
class HistoricalCandle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    source_metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise DataValidationError("timestamp must be timezone-aware")
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(UTC))
        values = (self.open, self.high, self.low, self.close)
        if not all(_finite_number(value) for value in values):
            raise DataValidationError("OHLC values must be finite")
        if self.volume is not None and not _finite_number(self.volume):
            raise DataValidationError("volume must be finite when present")
        if self.high < self.low:
            raise DataValidationError("high cannot be below low")
        if not self.low <= self.open <= self.high:
            raise DataValidationError("open must be within [low, high]")
        if not self.low <= self.close <= self.high:
            raise DataValidationError("close must be within [low, high]")
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, float(getattr(self, name)))
        if self.volume is not None:
            object.__setattr__(self, "volume", float(self.volume))
        object.__setattr__(self, "source_metadata", tuple(self.source_metadata))

    def as_strategy_candle(self) -> Candle:
        return Candle(self.open, self.high, self.low, self.close)


@dataclass(frozen=True)
class DatasetGap:
    previous_timestamp: datetime
    next_timestamp: datetime
    missing_intervals: int


@dataclass(frozen=True)
class DatasetQualityReport:
    candle_count: int
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    duplicate_count: int
    chronological: bool
    invalid_rows: tuple[int, ...] = ()
    observed_interval_seconds: float | None = None
    interval_consistent: bool = True
    expected_interval_seconds: float | None = None
    gaps: tuple[DatasetGap, ...] = ()


@dataclass(frozen=True)
class HistoricalDataset:
    candles: tuple[HistoricalCandle, ...]
    identifier: str = "dataset"
    quality: DatasetQualityReport = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "candles", tuple(self.candles))
        if not self.candles:
            raise DataValidationError("dataset cannot be empty")
        timestamps = [candle.timestamp for candle in self.candles]
        for index, (left, right) in enumerate(zip(timestamps, timestamps[1:]), 2):
            if right == left:
                raise DataValidationError("duplicate timestamp", row=index)
            if right < left:
                raise DataValidationError("timestamps must be strictly increasing", row=index)
        object.__setattr__(self, "quality", quality_report(self.candles))

    def context_series(self, timeframe: str | None = None) -> ContextSeries[Candle]:
        return ContextSeries(
            tuple(candle.as_strategy_candle() for candle in self.candles),
            timeframe,
            tuple(candle.timestamp for candle in self.candles),
        )

    def prefix(self, end_index: int) -> "HistoricalDataset":
        if not 0 <= end_index < len(self.candles):
            raise IndexError("end_index is outside the dataset")
        return HistoricalDataset(self.candles[:end_index + 1], self.identifier)


DEFAULT_ALIASES = {
    "timestamp": ("timestamp", "time", "date", "datetime"),
    "open": ("open",), "high": ("high",), "low": ("low",),
    "close": ("close",), "volume": ("volume",),
}


def _resolve_mapping(headers: list[str]) -> ColumnMapping:
    normalized: dict[str, list[str]] = {}
    for header in headers:
        normalized.setdefault(header.strip().lower(), []).append(header)
    resolved = {}
    for field_name, aliases in DEFAULT_ALIASES.items():
        matches = [original for alias in aliases
                   for original in normalized.get(alias, ())]
        if len(matches) > 1:
            raise DataValidationError(
                f"ambiguous {field_name} columns: {', '.join(matches)}"
            )
        if not matches:
            if field_name == "volume":
                resolved[field_name] = None
                continue
            raise DataValidationError(f"missing required {field_name} column")
        resolved[field_name] = matches[0]
    return ColumnMapping(**resolved)


def _validate_mapping(mapping: ColumnMapping, headers: list[str]) -> None:
    required = (mapping.timestamp, mapping.open, mapping.high, mapping.low,
                mapping.close)
    selected = required + ((mapping.volume,) if mapping.volume else ())
    if len(set(selected)) != len(selected):
        raise DataValidationError("column mappings must be distinct")
    for name in selected:
        if name not in headers:
            raise DataValidationError(f"mapped column {name!r} is missing")


def _timezone(value: str | tzinfo | None) -> tzinfo | None:
    if value is None or isinstance(value, tzinfo):
        return value
    if value.upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise DataValidationError(f"unknown timezone {value!r}") from error


def parse_timestamp(value: str, default_timezone: str | tzinfo | None = None) -> datetime:
    text = value.strip()
    if not text:
        raise DataValidationError("timestamp is empty")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as error:
        raise DataValidationError(f"malformed ISO-8601 timestamp {value!r}") from error
    if parsed.tzinfo is None:
        zone = _timezone(default_timezone)
        if zone is None:
            raise DataValidationError("naive timestamp requires an explicit timezone")
        first = parsed.replace(tzinfo=zone, fold=0)
        second = parsed.replace(tzinfo=zone, fold=1)
        first_valid = first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == parsed
        second_valid = second.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == parsed
        if not first_valid and not second_valid:
            raise DataValidationError("timestamp falls in a DST gap")
        if first_valid and second_valid and first.utcoffset() != second.utcoffset():
            raise DataValidationError("timestamp is ambiguous across a DST fold")
        parsed = first if first_valid else second
    return parsed.astimezone(UTC)


def _number(value: str | None, field_name: str) -> float:
    if value is None or not value.strip():
        raise DataValidationError(f"{field_name} is missing")
    try:
        number = float(value)
    except ValueError as error:
        raise DataValidationError(f"malformed {field_name} value {value!r}") from error
    if not math.isfinite(number):
        raise DataValidationError(f"{field_name} must be finite")
    return number


def load_csv(source: str | Path | TextIO, *, mapping: ColumnMapping | None = None,
             default_timezone: str | tzinfo | None = None,
             dataset_identifier: str = "dataset") -> HistoricalDataset:
    """Load strict CSV into canonical UTC completion-time candles."""
    close_stream = False
    if hasattr(source, "read"):
        stream = source
    else:
        stream = Path(source).open("r", encoding="utf-8", newline="")
        close_stream = True
    try:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames is None:
            raise DataValidationError("CSV header is missing")
        headers = list(reader.fieldnames)
        if len(set(headers)) != len(headers):
            raise DataValidationError("CSV header names must be unique")
        selected = mapping or _resolve_mapping(headers)
        _validate_mapping(selected, headers)
        candles = []
        try:
            for row_number, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise DataValidationError("inconsistent row shape", row=row_number)
                try:
                    volume = (_number(row[selected.volume], "volume")
                              if selected.volume else None)
                    candle = HistoricalCandle(
                        parse_timestamp(row[selected.timestamp], default_timezone),
                        _number(row[selected.open], "open"),
                        _number(row[selected.high], "high"),
                        _number(row[selected.low], "low"),
                        _number(row[selected.close], "close"), volume,
                    )
                except DataValidationError as error:
                    raise DataValidationError(str(error), row=row_number) from error
                candles.append(candle)
        except csv.Error as error:
            raise DataValidationError(f"malformed CSV: {error}", row=reader.line_num) from error
        try:
            return HistoricalDataset(tuple(candles), dataset_identifier)
        except DataValidationError as error:
            if error.row is not None:
                raise DataValidationError(str(error).split(": ", 1)[-1], row=error.row + 1) from error
            raise
    finally:
        if close_stream:
            stream.close()


def load_csv_text(text: str, **kwargs) -> HistoricalDataset:
    return load_csv(StringIO(text), **kwargs)


def quality_report(candles: tuple[HistoricalCandle, ...] | list[HistoricalCandle],
                   expected_interval: timedelta | None = None) -> DatasetQualityReport:
    items = tuple(candles)
    if not items:
        return DatasetQualityReport(0, None, None, 0, True)
    timestamps = [item.timestamp for item in items]
    duplicate_count = len(timestamps) - len(set(timestamps))
    chronological = all(left < right for left, right in zip(timestamps, timestamps[1:]))
    deltas = [(right - left).total_seconds()
              for left, right in zip(timestamps, timestamps[1:])]
    observed = deltas[0] if deltas and all(delta == deltas[0] for delta in deltas) else None
    expected_seconds = None
    gaps = []
    if expected_interval is not None:
        expected_seconds = expected_interval.total_seconds()
        if expected_seconds <= 0:
            raise ValueError("expected_interval must be positive")
        for left, right, delta in zip(timestamps, timestamps[1:], deltas):
            if delta > expected_seconds:
                gaps.append(DatasetGap(
                    left, right, max(1, math.ceil(delta / expected_seconds) - 1)
                ))
    return DatasetQualityReport(
        len(items), timestamps[0], timestamps[-1], duplicate_count,
        chronological, (), observed, observed is not None or len(deltas) <= 1,
        expected_seconds, tuple(gaps),
    )


def _canonical_number(value: float | None):
    if value is None:
        return None
    return 0.0 if value == 0 else value


def dataset_fingerprint(dataset: HistoricalDataset) -> str:
    """Hash canonical UTC timestamp/OHLC/volume; identifier and metadata excluded."""
    records = [{
        "timestamp": candle.timestamp.isoformat().replace("+00:00", "Z"),
        "open": _canonical_number(candle.open),
        "high": _canonical_number(candle.high),
        "low": _canonical_number(candle.low),
        "close": _canonical_number(candle.close),
        "volume": _canonical_number(candle.volume),
    } for candle in dataset.candles]
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def aggregate_timeframe(dataset: HistoricalDataset, interval: timedelta, *,
                        retain_incomplete_final: bool = False,
                        timeframe_label: str | None = None) -> HistoricalDataset:
    """Aggregate completion candles into UTC epoch-aligned ``(start, end]`` buckets."""
    seconds = interval.total_seconds()
    if seconds <= 0 or not seconds.is_integer():
        raise ValueError("aggregation interval must be positive whole seconds")
    source_deltas = [
        (right.timestamp - left.timestamp).total_seconds()
        for left, right in zip(dataset.candles, dataset.candles[1:])
    ]
    if source_deltas and seconds <= min(source_deltas):
        raise ValueError("aggregation interval must exceed the observed source interval")
    bucket_us = int(seconds) * 1_000_000
    epoch = datetime(1970, 1, 1, tzinfo=UTC)

    def bucket_end(timestamp: datetime) -> datetime:
        elapsed = timestamp - epoch
        elapsed_us = (elapsed.days * 86_400_000_000
                      + elapsed.seconds * 1_000_000 + elapsed.microseconds)
        end_us = ((elapsed_us - 1) // bucket_us + 1) * bucket_us
        return epoch + timedelta(microseconds=end_us)

    groups: list[tuple[datetime, list[HistoricalCandle]]] = []
    for candle in dataset.candles:
        end = bucket_end(candle.timestamp)
        if not groups or groups[-1][0] != end:
            groups.append((end, [candle]))
        else:
            groups[-1][1].append(candle)
    if groups and not retain_incomplete_final:
        final_end, final_rows = groups[-1]
        if final_rows[-1].timestamp != final_end:
            groups.pop()
    if not groups:
        raise DataValidationError("aggregation produced no completed candles")
    aggregated = []
    for end, rows in groups:
        volumes = [row.volume for row in rows]
        volume = sum(volumes) if all(value is not None for value in volumes) else None
        aggregated.append(HistoricalCandle(
            end, rows[0].open, max(row.high for row in rows),
            min(row.low for row in rows), rows[-1].close, volume,
        ))
    label = timeframe_label or f"{int(seconds)}s"
    return HistoricalDataset(tuple(aggregated), f"{dataset.identifier}:{label}")
