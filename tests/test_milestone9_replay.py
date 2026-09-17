import json
from datetime import UTC, datetime, timedelta

import pytest

from adapters.replay import (CollectingSignalSink, InMemoryCompletedCandleSource,
                             LocalJsonStateStore, MonitoringHealthReporter,
                             OfflineClock, ReplayAdapter)
from backtest.experiment import ExperimentConfig, ExperimentRunner
from data.historical import HistoricalCandle, HistoricalDataset
from strategy.engine import EngineConfig


def candles(count=8):
    start = datetime(2026, 5, 1, tzinfo=UTC)
    return tuple(HistoricalCandle(start + timedelta(minutes=5 * (i + 1)),
                                  100 + i % 3, 102 + i % 3, 98 + i % 3,
                                  101 + i % 3) for i in range(count))


def config():
    return ExperimentConfig("replay", "replay-data", "5m",
        higher_timeframe_seconds=900,
        engine=EngineConfig(require_htf_bias=False, require_liquidity_event=False,
                            require_mss=False, require_displacement=False,
                            require_pd_array=False, require_price_zone=False))


def test_replay_matches_independent_prefixes_and_is_deterministic():
    history = candles()
    first = ReplayAdapter(InMemoryCompletedCandleSource(history), config()).run()
    assert first == ReplayAdapter(InMemoryCompletedCandleSource(history), config()).run()
    for index, snapshot in enumerate(first.snapshots):
        prefix = HistoricalDataset(history[:index + 1], "replay-data")
        assert snapshot == ExperimentRunner(prefix, config()).run().snapshots[-1]


def test_sink_health_and_structured_records_are_observational():
    sink, health = CollectingSignalSink(), MonitoringHealthReporter()
    result = ReplayAdapter(InMemoryCompletedCandleSource(candles()), config(),
                           signal_sink=sink, health=health).run()
    assert tuple(item[0] for item in sink.items) == result.signals
    assert health.items == (("healthy", "accepted=8"),)
    assert sum(item.event == "candle_accepted" for item in result.records) == 8


def test_duplicate_out_of_order_and_invalid_values_are_rejected():
    values = candles(2)
    for invalid in ((values[0], values[0]), (values[1], values[0])):
        with pytest.raises(ValueError, match="strictly increasing"):
            ReplayAdapter(InMemoryCompletedCandleSource(invalid), config()).run()
    with pytest.raises(TypeError, match="invalid candle"):
        ReplayAdapter(InMemoryCompletedCandleSource((object(),)), config()).run()
    with pytest.raises(ValueError):
        HistoricalCandle(datetime.now(UTC), 10, 5, 8, 9)


def test_persistence_restart_equals_uninterrupted_replay(tmp_path):
    history = candles()
    uninterrupted = ReplayAdapter(InMemoryCompletedCandleSource(history), config()).run()
    store = LocalJsonStateStore(tmp_path / "state.json")
    ReplayAdapter(InMemoryCompletedCandleSource(history[:4]), config(),
                  persistence=store).run()
    resumed = ReplayAdapter(InMemoryCompletedCandleSource(history[4:]), config(),
                            persistence=store, resume=True).run()
    assert resumed.accepted_candles == uninterrupted.accepted_candles
    assert resumed.snapshots == uninterrupted.snapshots[4:]


def test_persistence_detects_corruption(tmp_path):
    path, store = tmp_path / "state.json", LocalJsonStateStore(tmp_path / "state.json")
    store.save({"dataset_identifier": "replay-data", "candles": []})
    content = json.loads(path.read_text())
    content["payload"]["state"]["dataset_identifier"] = "tampered"
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="corrupt"):
        store.load()


def test_clock_and_source_copy_validation():
    point = datetime(2026, 1, 1, tzinfo=UTC)
    assert OfflineClock(point).now() == point
    with pytest.raises(ValueError, match="timezone-aware"):
        OfflineClock(datetime(2026, 1, 1))
    values = list(candles())
    source = InMemoryCompletedCandleSource(values)
    values.clear()
    assert len(ReplayAdapter(source, config()).run().accepted_candles) == 8
