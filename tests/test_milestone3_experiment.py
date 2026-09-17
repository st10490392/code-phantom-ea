import csv
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest

from backtest.experiment import (RESEARCH_SCHEMA_VERSION, ExperimentConfig,
                                 ExperimentResult, ExperimentRunner,
                                 SimulationConfig, experiment_fingerprint)
from backtest.simulator import ResearchMetrics, SimulationResult
from data.historical import (HistoricalCandle, HistoricalDataset,
                             dataset_fingerprint, load_csv_text)
from strategy.confluence import Evidence, ResearchSignal
from strategy.engine import EngineConfig, SequentialResearchEngine


def dataset(identifier="experiment-data"):
    values = (
        (9, 10, 8, 9), (9, 9.5, 7, 8), (8, 11, 8, 10),
        (10, 10.5, 6, 6.5), (6.5, 12, 6.2, 11.5),
        (11.5, 13, 11, 12.5),
    )
    start = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
    return HistoricalDataset(tuple(
        HistoricalCandle(start + timedelta(minutes=5 * index), *ohlc)
        for index, ohlc in enumerate(values)
    ), identifier)


def engine_config():
    return EngineConfig(
        swing_window=1, displacement_lookback=1,
        displacement_range_multiple=1, displacement_body_ratio=.5,
        require_htf_bias=False, require_liquidity_event=False,
        require_pd_array=False, require_price_zone=False,
    )


def config(**changes):
    base = ExperimentConfig(
        "reproducible", "experiment-data", "5m", execution_interval_seconds=300,
        engine=engine_config(), simulation=SimulationConfig(1, 2, "conservative", 5),
    )
    return replace(base, **changes)


def test_config_immutable_deterministic_json_round_trip_and_unknown_rejection():
    original = config()
    encoded = original.to_json()
    assert ExperimentConfig.from_json(encoded) == original
    assert encoded == original.to_json()
    with pytest.raises(FrozenInstanceError):
        original.experiment_name = "changed"
    content = json.loads(encoded)
    content["unknown"] = 1
    with pytest.raises(ValueError, match="unknown"):
        ExperimentConfig.from_json(json.dumps(content))
    del content["unknown"]
    del content["execution_timeframe"]
    with pytest.raises(ValueError, match="missing"):
        ExperimentConfig.from_json(json.dumps(content))
    with pytest.raises(ValueError, match="malformed"):
        ExperimentConfig.from_json("{")
    with pytest.raises(ValueError, match="duplicate"):
        ExperimentConfig.from_json(encoded[:-1] + ',"experiment_name":"again"}')
    nan_content = json.loads(encoded)
    nan_content["engine"]["liquidity_tolerance"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        ExperimentConfig.from_json(json.dumps(nan_content))
    wrong_type = json.loads(encoded)
    wrong_type["engine"]["require_mss"] = 1
    with pytest.raises(ValueError, match="boolean"):
        ExperimentConfig.from_json(json.dumps(wrong_type))


def test_experiment_fingerprint_is_deterministic_and_parameter_sensitive():
    data_hash = dataset_fingerprint(dataset())
    first = experiment_fingerprint(config(), data_hash)
    assert first == experiment_fingerprint(config(), data_hash)
    changed = config(engine=replace(engine_config(), swing_window=2))
    assert experiment_fingerprint(changed, data_hash) != first
    assert experiment_fingerprint(config(), data_hash, "different-schema") != first
    numerically_equivalent = config(
        engine=replace(engine_config(), displacement_range_multiple=1.0),
        simulation=SimulationConfig(1.0, 2.0, "conservative", 5),
    )
    assert experiment_fingerprint(numerically_equivalent, data_hash) == first


def test_runner_reproducible_from_independent_canonical_copies():
    csv_data = """timestamp,open,high,low,close
2026-01-01T10:05:00Z,9,10,8,9
2026-01-01T10:10:00Z,9,9.5,7,8
2026-01-01T10:15:00Z,8,11,8,10
2026-01-01T10:20:00Z,10,10.5,6,6.5
2026-01-01T10:25:00Z,6.5,12,6.2,11.5
2026-01-01T10:30:00Z,11.5,13,11,12.5
"""
    first_data = load_csv_text(csv_data, dataset_identifier="experiment-data")
    second_data = load_csv_text(str(csv_data), dataset_identifier="experiment-data")
    first = ExperimentRunner(first_data, config()).run()
    second = ExperimentRunner(second_data, config()).run()
    assert first.dataset_fingerprint == second.dataset_fingerprint
    assert first.experiment_fingerprint == second.experiment_fingerprint
    assert first.candidates == second.candidates
    assert first.simulations == second.simulations
    assert first.metrics == second.metrics
    assert first.to_json() == second.to_json()
    assert first.schema_version == RESEARCH_SCHEMA_VERSION


def test_runner_preserves_prefix_invariance_through_data_layer():
    full_data = dataset()
    full = ExperimentRunner(full_data, config()).run()
    for index, expected in enumerate(full.snapshots):
        prefix = full_data.prefix(index)
        actual = ExperimentRunner(prefix, config()).run().snapshots[-1]
        assert actual == expected


def test_runner_prefix_invariance_survives_htf_aggregation():
    full_data = dataset()
    configured = config(higher_timeframe_seconds=900)
    full = ExperimentRunner(full_data, configured).run()
    for index, expected in enumerate(full.snapshots):
        actual = ExperimentRunner(full_data.prefix(index), configured).run().snapshots[-1]
        assert actual == expected


def test_appending_future_csv_rows_cannot_change_earlier_observations():
    rows = [
        "2026-01-01T10:05:00Z,9,10,8,9",
        "2026-01-01T10:10:00Z,9,9.5,7,8",
        "2026-01-01T10:15:00Z,8,11,8,10",
        "2026-01-01T10:20:00Z,10,10.5,6,6.5",
        "2026-01-01T10:25:00Z,6.5,12,6.2,11.5",
        "2026-01-01T10:30:00Z,11.5,13,11,12.5",
        "2026-01-01T10:35:00Z,12.5,100,-50,90",
    ]
    header = "timestamp,open,high,low,close\n"
    full_data = load_csv_text(header + "\n".join(rows) + "\n",
                              dataset_identifier="experiment-data")
    full = ExperimentRunner(full_data, config(higher_timeframe_seconds=900)).run()
    for index in range(len(rows) - 1):
        prefix_data = load_csv_text(header + "\n".join(rows[:index + 1]) + "\n",
                                    dataset_identifier="experiment-data")
        prefix = ExperimentRunner(prefix_data,
                                  config(higher_timeframe_seconds=900)).run()
        assert prefix.snapshots[-1] == full.snapshots[index]
        assert prefix.snapshots[-1].signal == full.snapshots[index].signal
        assert prefix.snapshots[-1].evidence == full.snapshots[index].evidence


def test_aggregation_htf_not_visible_before_completion_and_visible_at_equality():
    source = dataset()
    configured = config(higher_timeframe_seconds=1800)
    result = ExperimentRunner(source, configured).run()
    # Source completions are 10:05..10:30; the 30-minute HTF bucket completes at 10:30.
    assert all(snapshot.htf_context.completed_index is None
               for snapshot in result.snapshots[:-1])
    assert result.snapshots[-1].execution_timestamp == datetime(2026, 1, 1, 10, 30, tzinfo=UTC)
    assert result.snapshots[-1].htf_context.completed_index == 0


def test_incomplete_htf_is_never_exposed_by_safe_default():
    source = dataset()
    configured = config(higher_timeframe_seconds=3600)
    result = ExperimentRunner(source, configured).run()
    assert all(snapshot.htf_context.completed_index is None for snapshot in result.snapshots)
    assert result.warnings == ("no completed higher-timeframe candle available",)


def test_empty_dataset_and_identifier_mismatch_rejected():
    with pytest.raises(ValueError, match="empty"):
        HistoricalDataset(())
    with pytest.raises(ValueError, match="identifier"):
        ExperimentRunner(dataset("other"), config())


def test_json_and_candidate_csv_exports_are_deterministic_and_parseable(tmp_path):
    result = ExperimentRunner(dataset(), config()).run()
    assert result.to_json() == result.to_json()
    parsed = json.loads(result.to_json())
    assert parsed["experiment_fingerprint"] == result.experiment_fingerprint
    assert parsed["metrics"]["total_candidates"] == len(result.candidates)
    csv_text = result.candidate_csv()
    assert csv_text == result.candidate_csv()
    rows = list(csv.DictReader(StringIO(csv_text)))
    assert len(rows) == len(result.candidates)
    json_path, csv_path = tmp_path / "report.json", tmp_path / "candidates.csv"
    result.write_json(json_path)
    result.write_candidate_csv(csv_path)
    assert json_path.read_text().rstrip("\n") == result.to_json()
    assert csv_path.read_text() == csv_text


def test_candidate_csv_neutralizes_formula_prefix():
    malicious = ResearchSignal(0, "=FORMULA", (Evidence("x", True, "safe"),))
    simulation = SimulationResult(0, "=FORMULA", 1, 0, 2, "unresolved", 0,
                                  None, None, malicious)
    data = dataset()
    result = ExperimentResult(
        "e", "d", config(), RESEARCH_SCHEMA_VERSION,
        data.candles[0].timestamp, data.candles[-1].timestamp, data.quality,
        (), (malicious,), (simulation,), ResearchMetrics(1, 0, 1, 0, 0,
        0, 0, 0, 0, 0, 0, 0), (),
    )
    row = next(csv.DictReader(StringIO(result.candidate_csv())))
    assert row["direction"].startswith("'=")
