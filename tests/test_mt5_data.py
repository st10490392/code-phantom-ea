import hashlib
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pytest

from data.historical import DataValidationError, aggregate_timeframe, quality_report
from data.mt5 import MT5_M1_COLUMNS, load_mt5_metaquotes_m1_csv
from strategy.timeframes import ContextSeries, align_completed_candle


HEADER = ",".join(MT5_M1_COLUMNS) + "\n"
RAW_ROOT = Path(
    ".research-data/CP-001/raw/pre-holdout/MT5/MetaQuotes-Demo"
)
RAW_SHA256 = {
    "CP001_MT5_PROVENANCE.txt": "4419dfadbd6e6dd4d5613aa470743f1511fcdbd224a64f13bd5bafba76b8d8b8",
    "CP001_MetaQuotes-Demo_EURUSD_M1_2018.csv": "090d142ec51fbdb3e6d9880554b5dc8c2adb96b4e3b9704c672d439579d47023",
    "CP001_MetaQuotes-Demo_EURUSD_M1_2019.csv": "c4091225c6be01354d4dfc7c0d3e6c1af4b12450b2a7acb0efa13670dcdd459f",
    "CP001_MetaQuotes-Demo_EURUSD_M1_2020.csv": "8f3f56ff11d07ecc9f20b19ba32115c6666bab79ec9dfaffbc19073b21819d93",
    "CP001_MetaQuotes-Demo_EURUSD_M1_2021.csv": "88b7c55e3660e2559dfbd1402ec797dd2d72e28f667dbddd99aec6dc3bdc4291",
    "CP001_MetaQuotes-Demo_EURUSD_M1_2022.csv": "b08a2130bda748538b9cd6568920dd55d67add01f3b8118f4aea8cccc75f425b",
    "CP001_MetaQuotes-Demo_EURUSD_M1_2023.csv": "c72fd85e56ca2f770b4fe16b83041ec1db5f367aa1f874a5c68862c057c5b1d8",
    "CP001_MetaQuotes-Demo_EURUSD_M1_2024.csv": "823451ef7bebd0c79a22e8943396e5c877616e4de097f5e9cb3f18372013fcfe",
    "CP001_MetaQuotes-Demo_GBPUSD_M1_2018.csv": "856ddc15d8c9530304d27ad9cc91aeb6cf5b7faf5b9ae24a77ff0ffda4346c36",
    "CP001_MetaQuotes-Demo_GBPUSD_M1_2019.csv": "3663fe31a93005e295a9bf6e49e0bb296726712c525b7302506c737a4da7c478",
    "CP001_MetaQuotes-Demo_GBPUSD_M1_2020.csv": "cc468175d6413fcd48188ec3fc536c0029561705e72ebc11e20e0db5b747e5d1",
    "CP001_MetaQuotes-Demo_GBPUSD_M1_2021.csv": "c8f6425ae92d49b90a220072fe46de7ceb8a7fcfadb0aa811d6aa1ac7b5f1b4a",
    "CP001_MetaQuotes-Demo_GBPUSD_M1_2022.csv": "af461d602ee079ef1ac0a808e11f85fa910b7c75ea04cfa533f625ab5004a265",
    "CP001_MetaQuotes-Demo_GBPUSD_M1_2023.csv": "f38f9b2d8dcbc7ea0deebbfad2f6a8e26754ad951cea7449918ee996441a312c",
    "CP001_MetaQuotes-Demo_GBPUSD_M1_2024.csv": "47c21d99c11db61793910e053f7be6d8db632b9f0455f4ead7681ecaed0cbad8",
}


def rows(*timestamps):
    return HEADER + "".join(
        f"{timestamp},1.1000,1.2000,1.0000,1.1500,{10+i},{2+i},{i}\n"
        for i, timestamp in enumerate(timestamps)
    )


def test_local_raw_acquisition_hashes_are_unchanged():
    if not RAW_ROOT.is_dir():
        pytest.skip("ignored local CP-001 acquisition is not present")
    for filename, expected in RAW_SHA256.items():
        digest = hashlib.sha256((RAW_ROOT / filename).read_bytes()).hexdigest()
        assert digest == expected, filename


def test_exact_utc_open_to_completion_conversions_and_metadata():
    dataset = load_mt5_metaquotes_m1_csv(StringIO(rows(
        "2018.01.02 00:00:00", "2024.12.31 23:59:00"
    )))
    assert dataset.candles[0].timestamp == datetime(2018, 1, 2, 0, 1, tzinfo=UTC)
    assert dataset.candles[1].timestamp == datetime(2025, 1, 1, tzinfo=UTC)
    assert (dataset.candles[0].open, dataset.candles[0].high,
            dataset.candles[0].low, dataset.candles[0].close) == (1.1, 1.2, 1.0, 1.15)
    metadata = dict(dataset.candles[0].source_metadata)
    assert metadata["provider_timestamp"] == "2018-01-02T00:00:00+00:00"
    assert metadata["provider_timestamp_timezone"] == "UTC"
    assert metadata["provider_timestamp_semantics"] == "bar_open"
    assert (metadata["tick_volume"], metadata["spread"],
            metadata["real_volume"]) == ("10", "2", "0")
    assert dataset.candles[0].volume is None


def test_bar_is_visible_only_at_completion():
    dataset = load_mt5_metaquotes_m1_csv(StringIO(rows("2024.01.02 00:00:00")))
    observations = ContextSeries((object(), object()), timestamps=(
        datetime(2024, 1, 2, 0, 0, 59, 999999, tzinfo=UTC),
        datetime(2024, 1, 2, 0, 1, tzinfo=UTC),
    ))
    completed = dataset.context_series("M1")
    assert align_completed_candle(observations, completed, 0).higher_timeframe_index is None
    assert align_completed_candle(observations, completed, 1).higher_timeframe_index == 0


def test_m5_aggregation_is_causal_after_normalization():
    m1 = load_mt5_metaquotes_m1_csv(StringIO(rows(*(
        f"2024.01.02 00:0{minute}:00" for minute in range(5)
    ))))
    m5 = aggregate_timeframe(m1, timedelta(minutes=5))
    assert [c.timestamp.minute for c in m1.candles] == [1, 2, 3, 4, 5]
    assert len(m5.candles) == 1
    assert m5.candles[0].timestamp == datetime(2024, 1, 2, 0, 5, tzinfo=UTC)


def test_gaps_and_raw_bytes_are_preserved(tmp_path):
    path = tmp_path / "mt5.csv"
    path.write_text(rows("2024.01.02 00:00:00", "2024.01.02 00:02:00"), encoding="utf-8")
    before = hashlib.sha256(path.read_bytes()).digest()
    dataset = load_mt5_metaquotes_m1_csv(path)
    report = quality_report(dataset.candles, timedelta(minutes=1))
    assert hashlib.sha256(path.read_bytes()).digest() == before
    assert len(dataset.candles) == 2
    assert report.gaps[0].missing_intervals == 1


@pytest.mark.parametrize(("text", "message"), (
    ("bad,header\n", "exact MT5 schema"),
    (HEADER + "2024.01.02 00:00:00,1,2,0,1,1,2\n", "row shape"),
    (HEADER + "bad,1,2,0,1,1,2,0\n", "provider_time"),
    (HEADER + "2024.01.02 00:00:00,nan,2,0,1,1,2,0\n", "finite"),
    (HEADER + "2024.01.02 00:00:00,1,2,0,1,x,2,0\n", "tick_volume"),
    (HEADER + "2024.01.02 00:00:00,1,2,0,1,-1,2,0\n", "negative"),
))
def test_malformed_rows_fail_deterministically(text, message):
    with pytest.raises(DataValidationError, match=message):
        load_mt5_metaquotes_m1_csv(StringIO(text))


def test_future_rows_cannot_change_earlier_canonical_results():
    prefix = load_mt5_metaquotes_m1_csv(StringIO(rows("2024.01.02 00:00:00")))
    full = load_mt5_metaquotes_m1_csv(StringIO(rows(
        "2024.01.02 00:00:00", "2024.01.02 00:01:00"
    )))
    assert full.candles[0] == prefix.candles[0]
    assert full.prefix(0) == prefix
