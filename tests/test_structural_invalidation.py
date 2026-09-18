from dataclasses import replace
import hashlib
import json
from math import inf
from pathlib import Path

import pytest

from backtest.structural import (StructuralLevelError, protected_swing_levels,
                                 simulate_protected_swing_candidates)
from strategy.confluence import Evidence, ResearchSignal
from strategy.engine import (EngineConfig, EngineSnapshot, HigherTimeframeContext,
                             SequentialResearchEngine)
from strategy.structure import (Candle, StructureState, SwingPoint)
from strategy.timeframes import ContextSeries


def signal(direction="bullish", index=0):
    return ResearchSignal(index, direction, (
        Evidence("candidate setup", True, "frozen CP-001 V1", index=index),
    ))


def swing(price, kind):
    return SwingPoint(0, price, kind, "external", 0)


def snapshot(direction="bullish", *, low=90, high=110, h4_low=None, index=0):
    protected_low = None if low is None else swing(low, "low")
    protected_high = None if high is None else swing(high, "high")
    h4_state = StructureState(index, protected_low= (
        None if h4_low is None else swing(h4_low, "low")
    ))
    return EngineSnapshot(
        index, index, None,
        HigherTimeframeContext("H4", 0, direction, h4_state, None),
        direction, StructureState(index, protected_high=protected_high,
                                  protected_low=protected_low),
        (), (), (), (), (), None, None, None, (), signal(direction, index),
    )


def test_bullish_uses_exact_protected_low_without_buffer_and_exact_2r():
    levels = protected_swing_levels(Candle(99, 102, 89, 100), snapshot(low=90))
    assert (levels.entry, levels.invalidation, levels.objective) == (100, 90, 120)
    assert levels.reward_risk() == 2


def test_bearish_uses_exact_protected_high_without_buffer_and_exact_2r():
    levels = protected_swing_levels(
        Candle(101, 111, 98, 100), snapshot("bearish", high=110)
    )
    assert (levels.entry, levels.invalidation, levels.objective) == (100, 110, 80)
    assert levels.reward_risk() == 2


def test_missing_m15_anchor_does_not_fall_back_to_h4_or_other_prices():
    item = snapshot(low=None, h4_low=80)
    with pytest.raises(StructuralLevelError, match="missing_protected_swing"):
        protected_swing_levels(Candle(100, 105, 95, 101), item)
    report = simulate_protected_swing_candidates(
        (Candle(100, 105, 95, 101),), (item,)
    )
    assert report.total_candidates == 1
    assert report.simulatable_candidates == 0
    assert report.non_simulatable_candidates == 1
    assert report.non_simulatable_reason_counts == (("missing_protected_swing", 1),)


@pytest.mark.parametrize(("item", "candle", "reason"), (
    (snapshot(low=101), Candle(100, 102, 99, 100), "directionally_invalid_anchor"),
    (snapshot("bearish", high=99), Candle(100, 102, 98, 100),
     "directionally_invalid_anchor"),
    (snapshot(low=100), Candle(100, 102, 98, 100), "zero_risk"),
    (snapshot(low=inf), Candle(100, 102, 98, 100), "non_finite_anchor"),
))
def test_invalid_anchors_are_deterministically_classified(item, candle, reason):
    report = simulate_protected_swing_candidates((candle,), (item,))
    assert report.total_candidates == report.non_simulatable_candidates == 1
    assert report.simulatable_candidates == 0
    assert report.non_simulatable[0].reason == reason


def test_simulation_retains_raw_population_and_uses_96_bar_conservative_policy():
    valid = snapshot(index=0, low=99)
    missing = snapshot(index=1, low=None)
    candles = (Candle(100, 100, 100, 100), Candle(100, 103, 98, 100))
    report = simulate_protected_swing_candidates(candles, (valid, missing))
    assert report.total_candidates == 2
    assert report.simulatable_candidates == report.non_simulatable_candidates == 1
    assert report.simulations[0].outcome == "loss"
    assert report.simulations[0].normalized_r == -1


def test_future_rows_cannot_change_frozen_candidate_levels():
    frozen = snapshot(low=90)
    prefix = (Candle(99, 102, 89, 100),)
    future = prefix + (Candle(100, 1000, 1, 900),)
    first = protected_swing_levels(prefix[0], frozen)
    second = protected_swing_levels(future[0], frozen)
    assert first == second == protected_swing_levels(prefix[0], replace(frozen))


def test_real_engine_prefix_invariance_freezes_anchor_entry_risk_and_objective():
    prefix = (
        Candle(9, 10, 8, 9), Candle(9, 9.5, 7, 8),
        Candle(8, 11, 8, 10), Candle(10, 10.5, 6, 6.5),
        Candle(6.5, 12, 6.2, 11.5),
    )
    future = prefix + (Candle(11.5, 1000, 1, 900),)
    config = EngineConfig(
        swing_window=1, displacement_lookback=1,
        displacement_range_multiple=1, displacement_body_ratio=.5,
        require_htf_bias=False, require_liquidity_event=False,
        require_pd_array=False, require_price_zone=False,
    )
    prefix_snapshot = SequentialResearchEngine(
        ContextSeries(prefix), config=config
    ).run()[-1]
    full_snapshot = SequentialResearchEngine(
        ContextSeries(future), config=config
    ).run()[len(prefix) - 1]
    assert full_snapshot == prefix_snapshot
    assert protected_swing_levels(prefix[-1], prefix_snapshot) == \
        protected_swing_levels(future[len(prefix) - 1], full_snapshot)


def test_frozen_cp001_specification_and_code_identity_are_self_verifying():
    artifact = json.loads(Path("experiments/CP-001-baseline-v1.json").read_text())
    specification = artifact["specification"]
    payload = json.dumps(
        specification, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()
    assert hashlib.sha256(payload).hexdigest() == artifact["freeze_fingerprint"]

    code = specification["code_identity"]
    items = []
    for path, expected in sorted(code["implementation_files"].items()):
        actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        assert actual == expected, path
        items.append({"path": path, "sha256": actual})
    encoded = json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == code["implementation_content_sha256"]

    assert specification["derived_timeframes"]["execution"]["label"] == "M15"
    assert specification["derived_timeframes"]["higher_context"]["label"] == "H4"
    assert specification["management"]["objective_r"] == 2.0
    assert specification["management"]["maximum_holding_execution_bars"] == 96
