from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from backtest.experiment import ExperimentConfig
from backtest.portfolio import InstrumentExperiment, MultiInstrumentRunner
from data.historical import (HistoricalCandle, HistoricalDataset,
                             aggregate_timeframe, dataset_fingerprint)
from strategy.engine import EngineConfig


def dataset(identifier, count=18, offset=0, mutation=None):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    values = []
    for index in range(count):
        center = 100 + offset + (index % 5)
        ohlc = (center, center + 2, center - 2, center + .5)
        if mutation and index == mutation[0]:
            ohlc = mutation[1]
        values.append(HistoricalCandle(start + timedelta(minutes=5 * (index + 1)),
                                       *ohlc, volume=1))
    return HistoricalDataset(tuple(values), identifier)


def configuration(identifier):
    return ExperimentConfig(
        f"experiment-{identifier}", identifier, "5m", higher_timeframe_seconds=900,
        engine=EngineConfig(require_htf_bias=False, require_liquidity_event=False,
                            require_mss=False, require_displacement=False,
                            require_pd_array=False, require_price_zone=False))


def inputs(b_mutation=None):
    return (
        InstrumentExperiment("A", dataset("a"), configuration("a")),
        InstrumentExperiment("B", dataset("b", offset=100, mutation=b_mutation),
                             configuration("b")),
    )


def test_instruments_run_independently_and_aggregate_observations():
    report = MultiInstrumentRunner(inputs()).run()
    assert [item.instrument for item in report.instruments] == ["A", "B"]
    assert report.aggregate_candle_count == 36
    assert report.aggregate_candidate_count == sum(
        len(item.experiment.candidates) for item in report.instruments)
    assert report.aggregate_metrics.total_candidates == sum(
        item.experiment.metrics.total_candidates for item in report.instruments)
    assert report.aggregate_candidate_frequency == report.aggregate_candidate_count / 36
    assert report.cumulative_r_dispersion >= 0


def test_mutating_instrument_b_cannot_change_instrument_a_state():
    original = MultiInstrumentRunner(inputs()).run()
    changed = MultiInstrumentRunner(inputs((10, (500, 510, 490, 505)))).run()
    assert original.instruments[0] == changed.instruments[0]
    assert original.instruments[1] != changed.instruments[1]


def test_repeated_runs_and_serialization_are_deterministic_and_immutable():
    runner = MultiInstrumentRunner(inputs())
    first, second = runner.run(), runner.run()
    assert first == second
    assert first.to_json() == second.to_json()
    with pytest.raises(FrozenInstanceError):
        first.aggregate_candidate_count = 0


def test_instrument_identity_and_dataset_binding_validation():
    item = inputs()[0]
    with pytest.raises(ValueError, match="unique"):
        MultiInstrumentRunner((item, item))
    with pytest.raises(ValueError, match="differ"):
        InstrumentExperiment("bad", dataset("a"), configuration("b"))
    with pytest.raises(ValueError, match="at least"):
        MultiInstrumentRunner(())


def test_deterministic_thousand_candle_multi_instrument_timeframe_stress():
    # Generated in memory: no large fixture or artifact is committed.
    first = dataset("stress-a", count=1200)
    second = dataset("stress-b", count=1200, offset=1000)
    first_htf = aggregate_timeframe(first, timedelta(minutes=15))
    second_htf = aggregate_timeframe(second, timedelta(minutes=15))
    assert len(first_htf.candles) == len(second_htf.candles) == 400
    assert dataset_fingerprint(first) == dataset_fingerprint(dataset("copy", count=1200))
    assert dataset_fingerprint(first_htf) == dataset_fingerprint(
        aggregate_timeframe(dataset("copy", count=1200), timedelta(minutes=15)))
    assert dataset_fingerprint(first) != dataset_fingerprint(second)


def test_caller_source_list_mutation_cannot_change_runner():
    source = list(inputs())
    runner = MultiInstrumentRunner(source)
    expected = runner.run()
    source.clear()
    assert runner.run() == expected
