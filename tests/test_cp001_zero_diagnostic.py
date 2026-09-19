"""Boundary-safe checks of recovered counts and frozen gate reachability."""
import hashlib
import json
from pathlib import Path

from strategy.engine import EngineConfig, SequentialResearchEngine
from strategy.optimized_engine_v2 import OptimizedSequentialResearchEngineV2
from tests.test_optimized_engine_equivalence import _generated, _series


def test_recovered_diagnostic_integrity_and_count_identities():
    artifact = json.loads(Path(
        "experiments/CP-001-zero-candidate-diagnostic-v1.json").read_text())
    data = artifact["diagnostic"]
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert hashlib.sha256(canonical.encode()).hexdigest() == artifact["diagnostic_fingerprint"]
    original = Path("experiments/CP-001-development-results-v1.json").read_bytes()
    assert hashlib.sha256(original).hexdigest() == data["development_result_file_sha256"]
    result = json.loads(original)
    encoded = json.dumps(result["result"], sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(encoded.encode()).hexdigest() == data["development_result_fingerprint"]
    gates = data["candidate_gate_order"]
    for instrument in data["instruments"].values():
        d = instrument["diagnostic"]
        n = d["eligible_candidate_evaluations"]
        assert sum(d["direction_counts"].values()) == sum(d["direction_trigger_counts"].values()) == n
        assert sum(d["h4_bias_counts"].values()) == d["total_completed_m15_candles"]
        assert d["emitted_research_signals"] == 0
        groups = [dict(d, **d["funnel"], eligible_candles=n)] + list(d["directional_breakdown"].values())
        for group in groups:
            count = group["eligible_candles"]
            assert sum(group["first_fail_counts"].values()) == count
            scores = group["near_miss_distribution"]
            assert sum(scores.values()) == count
            assert sum(int(k.split('/')[0]) * v for k, v in scores.items()) == sum(group["individual_pass_counts"].values())
            assert sum(int(k.split('/')[0]) * (int(k.split('/')[0]) - 1) // 2 * v for k, v in scores.items()) == sum(group["pairwise_intersections"].values())
            previous = count
            for gate in gates:
                current = group["cumulative_pass_counts"].get(gate, 0)
                assert previous - current == group["first_fail_counts"].get(gate, 0)
                previous = current
            assert previous == 0
        for field in ("individual_pass_counts", "cumulative_pass_counts", "first_fail_counts", "pairwise_intersections", "near_miss_distribution"):
            overall = d["funnel"].get(field, d.get(field))
            keys = set(overall).union(*(g[field] for g in d["directional_breakdown"].values()))
            for key in keys:
                assert overall.get(key, 0) == sum(g[field].get(key, 0) for g in d["directional_breakdown"].values())
        assert d["pairwise_intersections"].get("structural shift × premium/discount", 0) == 0
        assert d["n_minus_1_missing_conditions"] == {"structural shift": d["near_miss_distribution"]["5/6"]}
        for example in d["representative_examples"]:
            assert 2018 <= int(example["timestamp"][:4]) <= 2022
            assert sum(e["passed"] for e in example["evidence"].values()) == example["passed_required_count"]


def test_frozen_mss_zone_contradiction_and_snapshot_eviction_equivalence():
    config = EngineConfig(**json.loads(Path("experiments/CP-001-baseline-v1.json").read_text())["specification"]["candidate_generation"]["engine"])
    directions = set()
    for seed in range(8):
        execution = _series(_generated(seed, 100))
        expected = SequentialResearchEngine(execution, config=config).run()
        observed = OptimizedSequentialResearchEngineV2(execution, config=config)
        for reference in expected:
            snapshot = observed.advance()
            observed._snapshots.clear()  # Exact eviction used by recovered diagnostic.
            assert snapshot == reference
            assert snapshot.signal is None
            for shift in snapshot.structure_events:
                if shift.kind != "MSS":
                    continue
                directions.add(shift.direction)
                evidence = {e.name: e for e in snapshot.evidence}
                assert evidence["structural shift"].passed
                assert not evidence["premium/discount"].passed
                rng = snapshot.dealing_range
                if rng is not None:
                    close = execution.candles[snapshot.execution_index].close
                    if shift.direction == "bullish":
                        assert close > rng.high > rng.equilibrium
                    else:
                        assert close < rng.low < rng.equilibrium
    assert directions == {"bullish", "bearish"}
