import hashlib
from datetime import UTC, datetime, timedelta

from data.dukascopy import DUKASCOPY_M1_COLUMNS, load_dukascopy_m1_csv
from data.historical import aggregate_timeframe, quality_report
from strategy.timeframes import ContextSeries, align_completed_candle


HEADER = "Etc/UTC,Open,High,Low,Close,Volume\n"


def rows(*timestamps):
    return HEADER + "".join(
        f"{timestamp},1.1,1.2,1.0,1.15,{10000 * (index + 1)}\n"
        for index, timestamp in enumerate(timestamps)
    )


def test_explicit_mapping_and_midnight_bar_complete_at_0001(tmp_path):
    path = tmp_path / "dukascopy.csv"
    path.write_text(rows("2024-01-02T00:00:00+00:00"), encoding="utf-8")

    dataset = load_dukascopy_m1_csv(path)

    assert DUKASCOPY_M1_COLUMNS.timestamp == "Etc/UTC"
    assert dataset.candles[0].timestamp == datetime(2024, 1, 2, 0, 1, tzinfo=UTC)
    assert dict(dataset.candles[0].source_metadata) == {
        "provider": "Dukascopy",
        "provider_period": "M1",
        "provider_timestamp": "2024-01-02T00:00:00+00:00",
        "provider_timestamp_semantics": "bar_open",
        "canonical_timestamp_semantics": "bar_completion",
    }


def test_provider_bar_is_not_visible_before_completion(tmp_path):
    path = tmp_path / "dukascopy.csv"
    path.write_text(rows("2024-01-02T00:00:00+00:00"), encoding="utf-8")
    dataset = load_dukascopy_m1_csv(path)

    before_completion = datetime(2024, 1, 2, 0, 0, 59, 999999, tzinfo=UTC)
    at_completion = datetime(2024, 1, 2, 0, 1, tzinfo=UTC)
    observation_times = ContextSeries(
        (object(), object()), timestamps=(before_completion, at_completion)
    )
    completed_bars = dataset.context_series("M1")
    assert align_completed_candle(
        observation_times, completed_bars, 0
    ).higher_timeframe_index is None
    assert align_completed_candle(
        observation_times, completed_bars, 1
    ).higher_timeframe_index == 0


def test_2359_provider_bar_completes_on_next_day(tmp_path):
    path = tmp_path / "dukascopy.csv"
    path.write_text(rows("2024-01-02T23:59:00+00:00"), encoding="utf-8")

    candle = load_dukascopy_m1_csv(path).candles[0]

    assert candle.timestamp == datetime(2024, 1, 3, 0, 0, tzinfo=UTC)


def test_htf_aggregation_uses_normalized_completion_boundaries(tmp_path):
    path = tmp_path / "dukascopy.csv"
    path.write_text(rows(*(
        f"2024-01-02T00:0{minute}:00+00:00" for minute in range(5)
    )), encoding="utf-8")

    m1 = load_dukascopy_m1_csv(path)
    m5 = aggregate_timeframe(m1, timedelta(minutes=5))

    assert [c.timestamp for c in m1.candles] == [
        datetime(2024, 1, 2, 0, minute, tzinfo=UTC) for minute in range(1, 6)
    ]
    assert len(m5.candles) == 1
    assert m5.candles[0].timestamp == datetime(2024, 1, 2, 0, 5, tzinfo=UTC)
    assert m5.candles[0].volume == 150000


def test_loading_does_not_modify_raw_file_or_fill_source_gaps(tmp_path):
    path = tmp_path / "dukascopy.csv"
    path.write_text(rows(
        "2024-01-02T00:00:00+00:00",
        "2024-01-02T00:02:00+00:00",
    ), encoding="utf-8")
    before = hashlib.sha256(path.read_bytes()).digest()

    dataset = load_dukascopy_m1_csv(path)

    after = hashlib.sha256(path.read_bytes()).digest()
    report = quality_report(dataset.candles, timedelta(minutes=1))
    assert before == after
    assert len(dataset.candles) == 2
    assert len(report.gaps) == 1
    assert report.gaps[0].missing_intervals == 1
