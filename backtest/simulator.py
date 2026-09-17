from dataclasses import dataclass
from math import isfinite
from typing import Callable, Literal

from strategy.confluence import ResearchSignal
from strategy.structure import Candle

Outcome = Literal["win", "loss", "unresolved"]
SameCandlePolicy = Literal["conservative", "optimistic"]


@dataclass(frozen=True)
class HypotheticalLevels:
    entry: float
    invalidation: float
    objective: float

    def validate(self, direction: str) -> None:
        if not all(isfinite(value) for value in (
                self.entry, self.invalidation, self.objective)):
            raise ValueError("hypothetical levels must be finite")
        if direction == "bullish":
            valid = self.invalidation < self.entry < self.objective
        elif direction == "bearish":
            valid = self.objective < self.entry < self.invalidation
        else:
            raise ValueError("signal direction must be bullish or bearish")
        if not valid:
            raise ValueError(
                "levels must place entry strictly between invalidation and objective"
            )

    def reward_risk(self) -> float:
        return abs(self.objective - self.entry) / abs(self.entry - self.invalidation)


@dataclass(frozen=True)
class SimulationResult:
    candidate_index: int
    direction: str
    entry_reference: float
    invalidation_reference: float
    objective_reference: float
    outcome: Outcome
    bars_elapsed: int
    normalized_r: float | None
    resolved_index: int | None
    signal: ResearchSignal


@dataclass(frozen=True)
class ResearchMetrics:
    total_candidates: int
    resolved: int
    unresolved: int
    wins: int
    losses: int
    win_rate: float
    average_r: float
    cumulative_r: float
    expectancy_r: float
    maximum_drawdown_r: float
    longest_win_streak: int
    longest_loss_streak: int


def simulate_candidates(
    candles: tuple[Candle, ...] | list[Candle],
    candidates: tuple[ResearchSignal, ...] | list[ResearchSignal],
    level_provider: Callable[[ResearchSignal], HypotheticalLevels],
    *, same_candle_policy: SameCandlePolicy = "conservative",
    max_bars: int | None = None,
) -> tuple[SimulationResult, ...]:
    """Resolve hypothetical outcomes strictly after candidate generation.

    This is an OHLC research abstraction, not order execution. When objective
    and invalidation are both touched, conservative policy records a loss and
    optimistic policy records a win because intrabar ordering is unknowable.
    Touches use the completed candle's full high/low, so an open beyond a level
    counts as a touch. If that candle also touches the opposing level, the same
    ambiguity policy applies; the open is not used to invent an intrabar path.
    """
    if same_candle_policy not in ("conservative", "optimistic"):
        raise ValueError("same_candle_policy must be conservative or optimistic")
    if max_bars is not None and max_bars < 1:
        raise ValueError("max_bars must be at least 1 or None")
    results = []
    for signal in candidates:
        if not 0 <= signal.index < len(candles):
            raise ValueError("candidate index is outside candle history")
        levels = level_provider(signal)
        levels.validate(signal.direction)
        end = len(candles)
        if max_bars is not None:
            end = min(end, signal.index + max_bars + 1)
        outcome: Outcome = "unresolved"
        resolved_index = None
        normalized_r = None
        for index in range(signal.index + 1, end):
            candle = candles[index]
            if signal.direction == "bullish":
                objective_touched = candle.high >= levels.objective
                invalidation_touched = candle.low <= levels.invalidation
            else:
                objective_touched = candle.low <= levels.objective
                invalidation_touched = candle.high >= levels.invalidation
            if not objective_touched and not invalidation_touched:
                continue
            resolved_index = index
            objective_wins = objective_touched and (
                not invalidation_touched or same_candle_policy == "optimistic"
            )
            if objective_wins:
                outcome = "win"
                normalized_r = levels.reward_risk()
            else:
                outcome = "loss"
                normalized_r = -1.0
            break
        bars_elapsed = ((resolved_index if resolved_index is not None else end - 1)
                        - signal.index)
        results.append(SimulationResult(
            signal.index, signal.direction, levels.entry, levels.invalidation,
            levels.objective, outcome, max(0, bars_elapsed), normalized_r,
            resolved_index, signal,
        ))
    return tuple(results)


def calculate_metrics(results: tuple[SimulationResult, ...] | list[SimulationResult]
                      ) -> ResearchMetrics:
    resolved = [result for result in results if result.outcome != "unresolved"]
    wins = sum(result.outcome == "win" for result in resolved)
    losses = sum(result.outcome == "loss" for result in resolved)
    r_values = [result.normalized_r for result in resolved
                if result.normalized_r is not None]
    cumulative = sum(r_values)
    average = cumulative / len(r_values) if r_values else 0.0
    peak = 0.0
    equity = 0.0
    maximum_drawdown = 0.0
    win_streak = loss_streak = longest_win = longest_loss = 0
    for result in resolved:
        equity += result.normalized_r or 0.0
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
        if result.outcome == "win":
            win_streak += 1
            loss_streak = 0
            longest_win = max(longest_win, win_streak)
        else:
            loss_streak += 1
            win_streak = 0
            longest_loss = max(longest_loss, loss_streak)
    return ResearchMetrics(
        total_candidates=len(results), resolved=len(resolved),
        unresolved=len(results) - len(resolved), wins=wins, losses=losses,
        win_rate=wins / len(resolved) if resolved else 0.0,
        average_r=average, cumulative_r=cumulative, expectancy_r=average,
        maximum_drawdown_r=maximum_drawdown,
        longest_win_streak=longest_win, longest_loss_streak=longest_loss,
    )
