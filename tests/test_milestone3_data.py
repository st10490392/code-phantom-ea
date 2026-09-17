from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest

from data.historical import (ColumnMapping, DataValidationError,
                             HistoricalCandle, HistoricalDataset,
                             aggregate_timeframe, dataset_fingerprint, load_csv,
                             load_csv_text, parse_timestamp, quality_report)


VALID = """timestamp,open,high,low,close,volume
2026-01-01T10:00:00Z,10,11,9,10.5,100
2026-01-01T10:05:00+00:00,10.5,12,10,11.5,110
"""


def test_valid_csv_default_mapping_and_fixture(tmp_path):
    dataset = load_csv_text(VALID, dataset_identifier="sample")
    assert len(dataset.candles) == 2
    assert dataset.candles[0].timestamp == datetime(2026, 1, 1, 10, tzinfo=UTC)
    assert dataset.candles[1].volume == 110
    fixture = load_csv("tests/fixtures/valid_ohlc.csv", dataset_identifier="fixture")
    assert fixture.quality.candle_count == 3


def test_custom_mapping_and_explicit_timezone_normalize_to_utc():
    text = "when,o,h,l,c,v\n2026-01-01T12:00:00,10,11,9,10,5\n"
    mapping = ColumnMapping("when", "o", "h", "l", "c", "v")
    dataset = load_csv_text(text, mapping=mapping, default_timezone="Africa/Johannesburg")
    assert dataset.candles[0].timestamp == datetime(2026, 1, 1, 10, tzinfo=UTC)
    with pytest.raises(DataValidationError, match="distinct"):
        load_csv_text(text, mapping=ColumnMapping("when", "o", "h", "l", "c", "c"),
                      default_timezone="UTC")
    with pytest.raises(DataValidationError, match="unique"):
        load_csv_text("timestamp,open,open,high,low,close\n"
                      "2026-01-01T00:00:00Z,1,1,2,0,1\n",
                      mapping=ColumnMapping("timestamp", "open", "high", "low", "close"))


@pytest.mark.parametrize(("text", "message"), (
    ("timestamp,open,high,low\n2026-01-01T00:00:00Z,1,2,0\n", "close"),
    ("timestamp,open,high,low,close\n2026-01-01T00:00:00Z,x,2,0,1\n", "malformed open"),
    ("timestamp,open,high,low,close\n2026-01-01T00:00:00Z,1,nan,0,1\n", "finite"),
    ("timestamp,open,high,low,close\n2026-01-01T00:00:00Z,1,inf,0,1\n", "finite"),
    ("timestamp,open,high,low,close\n2026-01-01T00:00:00Z,2,1,0,1\n", "open"),
    ("timestamp,open,high,low,close\n2026-01-01T00:00:00Z,1,0,2,1\n", "high"),
    ("timestamp,open,high,low,close\n2026-01-01T00:00:00Z,1,2,0,3\n", "close"),
    ("timestamp,open,high,low,close\n2026-01-01T00:00:00Z,1,2,0,1,extra\n", "row shape"),
    ("timestamp,open,high,low,close\n2026-01-01T00:00:00Z,1,2,0\n", "row shape"),
))
def test_csv_validation_errors_include_row(text, message):
    with pytest.raises(DataValidationError, match=message) as error:
        load_csv_text(text)
    if "missing required" not in str(error.value):
        assert error.value.row == 2


def test_empty_ambiguous_duplicate_and_reversed_data_rejected():
    with pytest.raises(DataValidationError, match="empty"):
        load_csv_text("timestamp,open,high,low,close\n")
    with pytest.raises(DataValidationError, match="ambiguous"):
        load_csv_text("timestamp,time,open,high,low,close\n"
                      "2026-01-01T00:00:00Z,x,1,2,0,1\n")
    duplicate = VALID + "2026-01-01T10:05:00Z,10,11,9,10,1\n"
    with pytest.raises(DataValidationError, match="duplicate"):
        load_csv_text(duplicate)
    reversed_rows = """timestamp,open,high,low,close
2026-01-01T10:05:00Z,1,2,0,1
2026-01-01T10:00:00Z,1,2,0,1
"""
    with pytest.raises(DataValidationError, match="strictly increasing"):
        load_csv_text(reversed_rows)


def test_naive_timezone_required_and_dst_anomalies_rejected():
    with pytest.raises(DataValidationError, match="explicit timezone"):
        parse_timestamp("2026-01-01T10:00:00")
    with pytest.raises(DataValidationError, match="DST gap"):
        parse_timestamp("2026-03-29T02:30:00", "Europe/Berlin")
    with pytest.raises(DataValidationError, match="ambiguous"):
        parse_timestamp("2026-10-25T02:30:00", "Europe/Berlin")


def test_dataset_fingerprint_is_content_based_and_volume_contributes():
    first = load_csv_text(VALID, dataset_identifier="one")
    second = load_csv_text(VALID, dataset_identifier="different-file")
    assert dataset_fingerprint(first) == dataset_fingerprint(second)
    changed = HistoricalDataset(
        (replace(first.candles[0], close=10.25), first.candles[1]), "one"
    )
    assert dataset_fingerprint(changed) != dataset_fingerprint(first)
    volume_changed = HistoricalDataset(
        (replace(first.candles[0], volume=101), first.candles[1]), "one"
    )
    assert dataset_fingerprint(volume_changed) != dataset_fingerprint(first)
    equivalent_offset = load_csv_text("""timestamp,open,high,low,close,volume
2026-01-01T12:00:00+02:00,10,11,9,10.5,100
2026-01-01T12:05:00+02:00,10.5,12,10,11.5,110
""")
    assert dataset_fingerprint(equivalent_offset) == dataset_fingerprint(first)
    manual_integers = HistoricalDataset((
        HistoricalCandle(datetime(2026, 1, 1, 10, tzinfo=UTC), 10, 11, 9, 10.5, 100),
        HistoricalCandle(datetime(2026, 1, 1, 10, 5, tzinfo=UTC), 10.5, 12, 10, 11.5, 110),
    ))
    assert dataset_fingerprint(manual_integers) == dataset_fingerprint(first)


def _five_minute_dataset(include_partial=True, volume=True):
    start = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
    candles = []
    for index in range(12 + int(include_partial)):
        price = 100 + index
        candles.append(HistoricalCandle(
            start + timedelta(minutes=5 * index), price, price + 2,
            price - 1, price + 1, float(index + 1) if volume else None,
        ))
    return HistoricalDataset(tuple(candles), "five-minute")


def test_htf_aggregation_ohlc_volume_and_completion_boundary():
    source = _five_minute_dataset()
    aggregated = aggregate_timeframe(source, timedelta(hours=1))
    assert len(aggregated.candles) == 1
    candle = aggregated.candles[0]
    assert candle.timestamp == datetime(2026, 1, 1, 11, tzinfo=UTC)
    assert (candle.open, candle.high, candle.low, candle.close) == (100, 113, 99, 112)
    assert candle.volume == sum(range(1, 13))
    no_volume = aggregate_timeframe(_five_minute_dataset(volume=False), timedelta(hours=1))
    assert no_volume.candles[0].volume is None


def test_incomplete_final_bucket_dropped_by_default_and_explicitly_retained():
    source = _five_minute_dataset()
    safe = aggregate_timeframe(source, timedelta(hours=1))
    retained = aggregate_timeframe(source, timedelta(hours=1),
                                   retain_incomplete_final=True)
    assert [item.timestamp.hour for item in safe.candles] == [11]
    assert [item.timestamp.hour for item in retained.candles] == [11, 12]
    assert retained.candles[-1].close == source.candles[-1].close
    with pytest.raises(ValueError, match="exceed"):
        aggregate_timeframe(source, timedelta(minutes=5))


def test_quality_report_only_claims_gaps_with_expected_interval():
    dataset = load_csv_text(VALID)
    ordinary = dataset.quality
    explicit = quality_report(dataset.candles, timedelta(minutes=2))
    assert ordinary.gaps == () and ordinary.expected_interval_seconds is None
    assert explicit.gaps[0].missing_intervals == 2


def test_canonical_objects_are_immutable_and_copy_source_collections():
    items = [load_csv_text(VALID).candles[0]]
    dataset = HistoricalDataset(items)
    items.append(load_csv_text(VALID).candles[1])
    assert len(dataset.candles) == 1
    with pytest.raises(FrozenInstanceError):
        dataset.identifier = "changed"
