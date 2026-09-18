from datetime import UTC, datetime, timedelta

import pytest

from backtest.structural import simulate_protected_swing_candidates
from strategy.engine import EngineConfig, SequentialResearchEngine
from strategy.optimized_engine import OptimizedSequentialResearchEngine
from strategy.optimized_engine_v2 import OptimizedSequentialResearchEngineV2
from strategy.timeframes import ContextSeries
from tests.test_optimized_engine_equivalence import _generated, _series


def _three_way(execution, higher=None, config=None):
    reference = SequentialResearchEngine(execution, higher, config).run()
    revision_1 = OptimizedSequentialResearchEngine(execution, higher, config).run()
    revision_2 = OptimizedSequentialResearchEngineV2(execution, higher, config).run()
    assert reference == revision_1 == revision_2
    return reference, revision_1, revision_2


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("tolerance,reclaim", ((0.0, 0), (0.0, 1),
                                                (0.05, 1), (0.1, 2)))
def test_three_way_generated_state_equivalence(seed, tolerance, reclaim):
    candles = _generated(seed, 96)
    execution = _series(candles)
    indices = range(15, len(candles), 16)
    higher = ContextSeries(
        tuple(candles[index] for index in indices), "H4",
        tuple(execution.timestamps[index] for index in indices),
    )
    config = EngineConfig(liquidity_tolerance=tolerance,
                          reclaim_window=reclaim)
    _three_way(execution, higher, config)


def test_three_way_prefix_future_invariance_with_timestamp_gap():
    candles = _generated(712, 80)
    origin = datetime(2022, 1, 1, tzinfo=UTC)
    timestamps = tuple(origin + timedelta(
        minutes=15 * index + (75 if index >= 37 else 0)
    ) for index in range(len(candles)))
    execution = ContextSeries(candles, "M15", timestamps)
    higher_indices = (15, 31, 47, 63, 79)
    higher = ContextSeries(
        tuple(candles[index] for index in higher_indices), "H4",
        tuple(timestamps[index] for index in higher_indices),
    )
    config = EngineConfig(liquidity_tolerance=0.05)
    full = _three_way(execution, higher, config)
    for end in (0, 2, 15, 36, 37, 48, 64, 78):
        prefix = _three_way(execution.prefix(end), higher, config)
        assert prefix[2] == full[2][:end + 1]
        assert prefix[1] == full[1][:end + 1]
        assert prefix[0] == full[0][:end + 1]


def test_three_way_candidate_levels_and_rejection_reasons():
    candles = _generated(2027, 150)
    config = EngineConfig(
        swing_window=1, displacement_lookback=2,
        displacement_range_multiple=1.0, displacement_body_ratio=0.4,
        require_htf_bias=False, require_liquidity_event=False,
        require_mss=False, require_pd_array=False, require_price_zone=False,
    )
    snapshots = _three_way(_series(candles), config=config)
    reports = tuple(simulate_protected_swing_candidates(candles, item)
                    for item in snapshots)
    assert reports[0] == reports[1] == reports[2]
