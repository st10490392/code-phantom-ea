"""CP-001 structural invalidation without changing the generic simulator."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import isfinite

from backtest.simulator import (HypotheticalLevels, ResearchMetrics,
                                SimulationResult, calculate_metrics,
                                simulate_candidates)
from strategy.confluence import ResearchSignal
from strategy.engine import EngineSnapshot
from strategy.structure import Candle


@dataclass(frozen=True)
class NonSimulatableCandidate:
    signal: ResearchSignal
    reason: str


@dataclass(frozen=True)
class StructuralSimulationReport:
    candidates: tuple[ResearchSignal, ...]
    simulations: tuple[SimulationResult, ...]
    non_simulatable: tuple[NonSimulatableCandidate, ...]
    metrics: ResearchMetrics

    @property
    def total_candidates(self) -> int:
        return len(self.candidates)

    @property
    def simulatable_candidates(self) -> int:
        return len(self.simulations)

    @property
    def non_simulatable_candidates(self) -> int:
        return len(self.non_simulatable)

    @property
    def non_simulatable_reason_counts(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(Counter(item.reason for item in self.non_simulatable).items()))


class StructuralLevelError(ValueError):
    """A raw candidate cannot receive CP-001 structural levels."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def protected_swing_levels(candle: Candle, snapshot: EngineSnapshot,
                           reward_risk: float = 2.0) -> HypotheticalLevels:
    """Build exact CP-001 V1 levels from the candidate's execution snapshot."""
    signal = snapshot.signal
    if signal is None or signal.index != snapshot.execution_index:
        raise StructuralLevelError("candidate_snapshot_mismatch")
    if not isfinite(candle.close):
        raise StructuralLevelError("non_finite_entry")
    if not isfinite(reward_risk) or reward_risk <= 0:
        raise ValueError("reward_risk must be positive and finite")

    if signal.direction == "bullish":
        protected = snapshot.structural_state.protected_low
    elif signal.direction == "bearish":
        protected = snapshot.structural_state.protected_high
    else:
        raise StructuralLevelError("invalid_direction")
    if protected is None:
        raise StructuralLevelError("missing_protected_swing")

    invalidation = protected.price
    if not isfinite(invalidation):
        raise StructuralLevelError("non_finite_anchor")
    entry = candle.close
    if invalidation == entry:
        raise StructuralLevelError("zero_risk")
    if ((signal.direction == "bullish" and invalidation > entry)
            or (signal.direction == "bearish" and invalidation < entry)):
        raise StructuralLevelError("directionally_invalid_anchor")

    risk = abs(entry - invalidation)
    objective = (entry + reward_risk * risk if signal.direction == "bullish"
                 else entry - reward_risk * risk)
    levels = HypotheticalLevels(entry, invalidation, objective)
    try:
        levels.validate(signal.direction)
    except ValueError as error:
        raise StructuralLevelError("invalid_level_construction") from error
    return levels


def simulate_protected_swing_candidates(
    candles: tuple[Candle, ...] | list[Candle],
    snapshots: tuple[EngineSnapshot, ...] | list[EngineSnapshot], *,
    reward_risk: float = 2.0,
    max_bars: int = 96,
    same_candle_policy: str = "conservative",
) -> StructuralSimulationReport:
    """Classify every raw candidate, then simulate only valid structural levels."""
    candle_tuple = tuple(candles)
    snapshot_tuple = tuple(snapshots)
    candidates = tuple(item.signal for item in snapshot_tuple if item.signal is not None)
    levels_by_index: dict[int, HypotheticalLevels] = {}
    simulatable = []
    rejected = []
    for snapshot in snapshot_tuple:
        signal = snapshot.signal
        if signal is None:
            continue
        if not 0 <= signal.index < len(candle_tuple):
            rejected.append(NonSimulatableCandidate(signal, "candidate_index_out_of_range"))
            continue
        try:
            levels = protected_swing_levels(candle_tuple[signal.index], snapshot,
                                            reward_risk)
        except StructuralLevelError as error:
            rejected.append(NonSimulatableCandidate(signal, error.reason))
            continue
        levels_by_index[signal.index] = levels
        simulatable.append(signal)

    simulations = simulate_candidates(
        candle_tuple, tuple(simulatable), lambda signal: levels_by_index[signal.index],
        same_candle_policy=same_candle_policy, max_bars=max_bars,
    )
    return StructuralSimulationReport(
        candidates, simulations, tuple(rejected), calculate_metrics(simulations)
    )
