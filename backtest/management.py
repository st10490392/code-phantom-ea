"""Offline hypothetical position-management research.

No object in this module can place or manage a real order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from math import isfinite
from typing import Callable, Literal

from backtest.simulator import HypotheticalLevels
from strategy.confluence import ResearchSignal
from strategy.structure import Candle


AmbiguityPolicy = Literal["conservative", "favorable"]


def _positive(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")


@dataclass(frozen=True)
class PartialObjective:
    objective_r: float
    fraction: float

    def __post_init__(self) -> None:
        _positive(self.objective_r, "partial objective_r")
        _positive(self.fraction, "partial fraction")
        if self.fraction >= 1:
            raise ValueError("partial fraction must be less than 1")


@dataclass(frozen=True)
class ManagementConfig:
    objective_r: float | None = None
    partial: PartialObjective | None = None
    break_even_after_partial: bool = False
    trailing_distance_r: float | None = None
    max_bars: int | None = None
    ambiguity_policy: AmbiguityPolicy = "conservative"
    daily_loss_boundary_r: float | None = None
    daily_gain_boundary_r: float | None = None

    def __post_init__(self) -> None:
        for name in ("objective_r", "trailing_distance_r", "daily_loss_boundary_r",
                     "daily_gain_boundary_r"):
            value = getattr(self, name)
            if value is not None:
                _positive(value, name)
        if self.partial is not None and self.objective_r is not None \
                and self.partial.objective_r >= self.objective_r:
            raise ValueError("partial objective must precede the final objective")
        if self.max_bars is not None and (isinstance(self.max_bars, bool)
                                          or not isinstance(self.max_bars, int)
                                          or self.max_bars < 1):
            raise ValueError("max_bars must be at least 1 or None")
        if self.ambiguity_policy not in ("conservative", "favorable"):
            raise ValueError("invalid ambiguity_policy")


@dataclass(frozen=True)
class RealizedFraction:
    fraction: float
    realized_r_per_unit: float
    contribution_r: float
    index: int
    reason: str


@dataclass(frozen=True)
class ManagedSimulationResult:
    candidate_index: int
    direction: str
    entry_reference: float
    initial_invalidation_reference: float
    objective_reference: float
    outcome: str
    bars_elapsed: int
    normalized_r: float | None
    resolved_index: int | None
    realized_fractions: tuple[RealizedFraction, ...]
    signal: ResearchSignal
    eligible: bool = True
    rejection_reason: str | None = None


def _level(entry: float, risk: float, direction: str, r_value: float) -> float:
    return entry + risk * r_value if direction == "bullish" else entry - risk * r_value


def _touch(candle: Candle, direction: str, objective: float, stop: float) -> tuple[bool, bool]:
    if direction == "bullish":
        return candle.high >= objective, candle.low <= stop
    return candle.low <= objective, candle.high >= stop


def _stop_r(entry: float, stop: float, risk: float, direction: str) -> Decimal:
    value = ((stop - entry) / risk if direction == "bullish"
             else (entry - stop) / risk)
    return Decimal(str(value))


def _result(signal: ResearchSignal, levels: HypotheticalLevels,
            objective: float, outcome: str, bars: int, resolved: int | None,
            fills: list[RealizedFraction], normalized: Decimal | None,
            *, eligible: bool = True, reason: str | None = None) -> ManagedSimulationResult:
    return ManagedSimulationResult(
        signal.index, signal.direction, levels.entry, levels.invalidation, objective,
        outcome, bars, None if normalized is None else float(normalized), resolved,
        tuple(fills), signal, eligible, reason,
    )


def simulate_managed_candidates(
    candles: tuple[Candle, ...] | list[Candle],
    candidates: tuple[ResearchSignal, ...] | list[ResearchSignal],
    level_provider: Callable[[ResearchSignal], HypotheticalLevels],
    config: ManagementConfig,
    *, timestamps: tuple[datetime, ...] | list[datetime] | None = None,
) -> tuple[ManagedSimulationResult, ...]:
    """Apply predefined management rules using candles after each signal only."""
    candle_tuple = tuple(candles)
    timestamp_tuple = None if timestamps is None else tuple(timestamps)
    daily_enabled = (config.daily_loss_boundary_r is not None
                     or config.daily_gain_boundary_r is not None)
    if timestamp_tuple is not None:
        if len(timestamp_tuple) != len(candle_tuple):
            raise ValueError("timestamps must match candle count")
        normalized = []
        for value in timestamp_tuple:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamps must be timezone-aware")
            normalized.append(value.astimezone(UTC))
        timestamp_tuple = tuple(normalized)
        if any(right <= left for left, right in zip(timestamp_tuple, timestamp_tuple[1:])):
            raise ValueError("timestamps must be strictly increasing")
    elif daily_enabled:
        raise ValueError("daily controls require completion timestamps")

    daily_totals: dict[object, Decimal] = {}
    results = []
    for signal in candidates:
        if not 0 <= signal.index < len(candle_tuple):
            raise ValueError("candidate index is outside candle history")
        levels = level_provider(signal)
        levels.validate(signal.direction)
        risk = abs(levels.entry - levels.invalidation)
        final_r = (levels.reward_risk() if config.objective_r is None
                   else config.objective_r)
        objective = _level(levels.entry, risk, signal.direction, final_r)
        candidate_day = (None if timestamp_tuple is None
                         else timestamp_tuple[signal.index].date())
        day_total = daily_totals.get(candidate_day, Decimal("0"))
        boundary_hit = ((config.daily_loss_boundary_r is not None
                         and day_total <= -Decimal(str(config.daily_loss_boundary_r)))
                        or (config.daily_gain_boundary_r is not None
                            and day_total >= Decimal(str(config.daily_gain_boundary_r))))
        if boundary_hit:
            results.append(_result(signal, levels, objective, "skipped", 0, None,
                                   [], None, eligible=False,
                                   reason="daily research boundary reached"))
            continue

        end = len(candle_tuple)
        if config.max_bars is not None:
            end = min(end, signal.index + config.max_bars + 1)
        remaining = Decimal("1")
        total = Decimal("0")
        stop = levels.invalidation
        partial_done = False
        fills: list[RealizedFraction] = []
        resolved = None
        outcome = "unresolved"
        for index in range(signal.index + 1, end):
            candle = candle_tuple[index]
            final_touch, stop_touch = _touch(candle, signal.direction, objective, stop)
            partial_touch = False
            partial_level = None
            if config.partial is not None and not partial_done:
                partial_level = _level(levels.entry, risk, signal.direction,
                                       config.partial.objective_r)
                partial_touch, _ = _touch(candle, signal.direction, partial_level, stop)

            favorable_touch = final_touch or partial_touch
            if stop_touch and favorable_touch and config.ambiguity_policy == "conservative":
                stop_value = _stop_r(levels.entry, stop, risk, signal.direction)
                contribution = remaining * stop_value
                total += contribution
                fills.append(RealizedFraction(float(remaining), float(stop_value),
                                              float(contribution), index, "invalidation"))
                remaining = Decimal("0")
                resolved, outcome = index, "loss" if total < 0 else "breakeven"
                break
            if final_touch:
                contribution = remaining * Decimal(str(final_r))
                total += contribution
                fills.append(RealizedFraction(float(remaining), float(final_r),
                                              float(contribution), index, "objective"))
                remaining = Decimal("0")
                resolved, outcome = index, "win" if total > 0 else "breakeven"
                break
            if partial_touch and config.partial is not None:
                fraction = Decimal(str(config.partial.fraction))
                contribution = fraction * Decimal(str(config.partial.objective_r))
                total += contribution
                remaining -= fraction
                fills.append(RealizedFraction(float(fraction), config.partial.objective_r,
                                              float(contribution), index,
                                              "partial_objective"))
                partial_done = True
                if config.break_even_after_partial:
                    stop = levels.entry
            elif stop_touch:
                stop_value = _stop_r(levels.entry, stop, risk, signal.direction)
                contribution = remaining * stop_value
                total += contribution
                fills.append(RealizedFraction(float(remaining), float(stop_value),
                                              float(contribution), index, "invalidation"))
                remaining = Decimal("0")
                resolved = index
                outcome = "win" if total > 0 else "loss" if total < 0 else "breakeven"
                break

            # A completed close may move the stop for subsequent candles only.
            if config.trailing_distance_r is not None and remaining:
                distance = risk * config.trailing_distance_r
                candidate_stop = (candle.close - distance if signal.direction == "bullish"
                                  else candle.close + distance)
                stop = (max(stop, candidate_stop) if signal.direction == "bullish"
                        else min(stop, candidate_stop))

        bars = max(0, (resolved if resolved is not None else end - 1) - signal.index)
        if remaining and config.max_bars is not None and end <= len(candle_tuple) \
                and end == signal.index + config.max_bars + 1:
            outcome = "expired"
            resolved = end - 1
        normalized_r = total if fills else (Decimal("0") if outcome == "expired" else None)
        result = _result(signal, levels, objective, outcome, bars, resolved, fills,
                         normalized_r)
        results.append(result)
        if daily_enabled and result.normalized_r is not None:
            daily_totals[candidate_day] = day_total + Decimal(str(result.normalized_r))
    return tuple(results)
