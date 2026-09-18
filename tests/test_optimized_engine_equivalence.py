import random
from datetime import UTC, datetime, timedelta

import pytest

from backtest.structural import (StructuralLevelError, protected_swing_levels,
                                 simulate_protected_swing_candidates)
from strategy.engine import EngineConfig, SequentialResearchEngine
from strategy.optimized_engine import OptimizedSequentialResearchEngine
from strategy.structure import Candle
from strategy.timeframes import ContextSeries


def _series(candles, *, step=15, start=0, label="M15"):
    origin = datetime(2020, 1, 1, tzinfo=UTC)
    timestamps = tuple(origin + timedelta(minutes=start + step * index)
                       for index in range(len(candles)))
    return ContextSeries(tuple(candles), label, timestamps)


def _generated(seed, count):
    rng = random.Random(seed)
    price = 100.0
    candles = []
    for index in range(count):
        opening = price
        # Periodic flat and oversized bars exercise empty range lookbacks,
        # displacement, gaps, extensions, reversals, and both directions.
        change = 0.0 if index % 29 == 0 else rng.uniform(-2.5, 2.5)
        if index % 37 == 0:
            change *= 4
        close = opening + change
        wick_high = 0.0 if index % 31 == 0 else rng.uniform(0, 1.2)
        wick_low = 0.0 if index % 31 == 0 else rng.uniform(0, 1.2)
        high = max(opening, close) + wick_high
        low = min(opening, close) - wick_low
        candles.append(Candle(opening, high, low, close))
        price = close
    return tuple(candles)


def _assert_equivalent(execution, higher=None, config=None):
    reference = SequentialResearchEngine(execution, higher, config).run()
    optimized = OptimizedSequentialResearchEngine(execution, higher, config).run()
    assert optimized == reference
    assert len(optimized) == len(reference)
    for expected, actual in zip(reference, optimized):
        assert actual.execution_index == expected.execution_index
        assert actual.execution_timestamp == expected.execution_timestamp
        assert actual.execution_bias == expected.execution_bias
        assert actual.htf_context == expected.htf_context
        assert actual.structural_state == expected.structural_state
        assert actual.structure_events == expected.structure_events
        assert actual.active_liquidity == expected.active_liquidity
        assert actual.liquidity_events == expected.liquidity_events
        assert actual.dealing_range == expected.dealing_range
        assert actual.price_zone == expected.price_zone
        assert actual.displacement == expected.displacement
        assert actual.imbalances == expected.imbalances
        assert actual.inverted_gaps == expected.inverted_gaps
        assert actual.evidence == expected.evidence
        assert actual.signal == expected.signal
    return reference, optimized


@pytest.mark.parametrize("candles", (
    # No swings / zero ranges.
    (Candle(10, 10, 10, 10),) * 8,
    # Swings, external extensions, bullish/bearish breaks and shifts,
    # wick/body liquidity transitions, FVG/IFVG, range-zone changes.
    (
        Candle(10, 11, 9, 10), Candle(10, 12, 8, 11),
        Candle(11, 11.5, 9, 9.5), Candle(9.5, 13, 9, 12.8),
        Candle(12.8, 13, 7, 7.2), Candle(7.2, 14, 7, 13.8),
        Candle(13.8, 14, 6, 6.2), Candle(6.2, 15, 6, 14.8),
        Candle(14.8, 15, 5, 5.2), Candle(5.2, 16, 5, 15.8),
    ),
    # Exact equal-level/touched pools and equilibrium closes.
    (
        Candle(10, 11, 9, 10), Candle(10, 12, 10, 11),
        Candle(11, 11, 9, 10), Candle(10, 12, 10, 11),
        Candle(11, 12.5, 8, 12), Candle(12, 12, 7, 8),
        Candle(8, 13, 8, 12), Candle(12, 13, 6, 7),
    ),
))
@pytest.mark.parametrize("reclaim_window", (0, 1, 2))
def test_adversarial_snapshot_state_is_exact(candles, reclaim_window):
    config = EngineConfig(
        swing_window=1, liquidity_tolerance=0.0,
        reclaim_window=reclaim_window, displacement_lookback=2,
        displacement_range_multiple=1.0, displacement_body_ratio=0.5,
        require_htf_bias=False,
    )
    _assert_equivalent(_series(candles), config=config)


@pytest.mark.parametrize("seed", range(12))
def test_deterministic_generated_sequences_match(seed):
    candles = _generated(seed, 96)
    execution = _series(candles)
    h4_candles = tuple(candles[index] for index in range(15, len(candles), 16))
    higher = _series(h4_candles, step=240, start=240, label="H4")
    config = EngineConfig(liquidity_tolerance=0.05)
    _assert_equivalent(execution, higher, config)


def test_prefix_and_future_row_invariance_with_gapped_timestamps():
    candles = _generated(91, 72)
    origin = datetime(2021, 1, 1, tzinfo=UTC)
    timestamps = tuple(origin + timedelta(minutes=15 * index + (60 if index >= 31 else 0))
                       for index in range(len(candles)))
    execution = ContextSeries(candles, "M15", timestamps)
    higher = ContextSeries(
        tuple(candles[index] for index in (15, 31, 47, 63)), "H4",
        tuple(timestamps[index] for index in (15, 31, 47, 63)),
    )
    config = EngineConfig(liquidity_tolerance=0.1)
    reference, optimized = _assert_equivalent(execution, higher, config)
    for end in (0, 1, 7, 16, 30, 31, 48, 63, 70):
        reference_prefix, optimized_prefix = _assert_equivalent(
            execution.prefix(end), higher, config)
        assert optimized_prefix == optimized[:end + 1]
        assert reference_prefix == reference[:end + 1]


def test_structural_levels_and_classifications_match_for_all_candidates():
    candles = _generated(2026, 140)
    execution = _series(candles)
    config = EngineConfig(
        swing_window=1, displacement_lookback=2,
        displacement_range_multiple=1.0, displacement_body_ratio=0.4,
        require_htf_bias=False, require_liquidity_event=False,
        require_mss=False, require_pd_array=False, require_price_zone=False,
    )
    reference, optimized = _assert_equivalent(execution, config=config)
    assert simulate_protected_swing_candidates(candles, reference) == \
        simulate_protected_swing_candidates(candles, optimized)
    for left, right in zip(reference, optimized):
        if left.signal is not None:
            try:
                expected = ("levels", protected_swing_levels(
                    candles[left.execution_index], left))
            except StructuralLevelError as error:
                expected = ("rejected", error.reason)
            try:
                actual = ("levels", protected_swing_levels(
                    candles[right.execution_index], right))
            except StructuralLevelError as error:
                actual = ("rejected", error.reason)
            assert actual == expected
