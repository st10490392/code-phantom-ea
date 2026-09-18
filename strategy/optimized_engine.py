"""Incremental behavioral equivalent of the frozen sequential research engine.

``SequentialResearchEngine`` remains the CP-001 Baseline V1 oracle.  This
module changes only how its deterministic state is calculated: confirmed
history is retained and one completed candle is applied at a time.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from strategy.context import DealingRange
from strategy.engine import (EngineConfig, EngineSnapshot, HigherTimeframeContext,
                             SequentialResearchEngine, _latest_event)
from strategy.fvg import Displacement, InvertedFairValueGap
from strategy.imbalance import Gap
from strategy.liquidity_v2 import LiquidityEvent, LiquidityPool
from strategy.structure import (Candle, StructureEvent, StructureShift,
                                StructureState, SwingPoint)
from strategy.timeframes import align_completed_candle


class _IncrementalStructure:
    def __init__(self, window: int):
        self.window = window
        self.highs: list[SwingPoint] = []
        self.lows: list[SwingPoint] = []
        self._classification_extreme = {"high": None, "low": None}
        self._broken: set[tuple[str, int]] = set()
        self.bos: list[StructureEvent] = []
        self.shifts: list[StructureShift] = []
        self.bias = "neutral"

    def advance(self, candles: tuple[Candle, ...], index: int) -> tuple[
            StructureState, tuple[StructureEvent | StructureShift, ...]]:
        pivot = index - self.window
        if pivot >= self.window:
            left = candles[pivot - self.window:pivot]
            right = candles[pivot + 1:pivot + self.window + 1]
            candle = candles[pivot]
            if (candle.high > max(item.high for item in left)
                    and candle.high > max(item.high for item in right)):
                self._add_swing(pivot, candle.high, "high", index)
            if (candle.low < min(item.low for item in left)
                    and candle.low < min(item.low for item in right)):
                self._add_swing(pivot, candle.low, "low", index)

        current_bos = []
        candle = candles[index]
        for side, swings, crossed, direction in (
            ("high", self.highs, lambda price: candle.close > price, "bullish"),
            ("low", self.lows, lambda price: candle.close < price, "bearish"),
        ):
            swing = self._active(side, swings, index)
            if swing is not None and swing.identity not in self._broken and crossed(swing.price):
                event = StructureEvent(index, "BOS", direction, swing.price,
                                       swing.structure, swing.index, side,
                                       swing.confirmed_at)
                self._broken.add(swing.identity)
                self.bos.append(event)
                current_bos.append(event)

        current_shifts = []
        for event in current_bos:
            previous = self.bias
            if previous != "neutral" and event.direction != previous:
                shift = StructureShift(
                    event.index, event.direction, event.level, event.structure,
                    previous, "MSS", event.broken_swing_index, event.broken_side,
                )
                self.shifts.append(shift)
                current_shifts.append(shift)
            self.bias = event.direction

        high = self._active("high", self.highs, index)
        low = self._active("low", self.lows, index)
        state = StructureState(
            index, high, low,
            high if self.bias == "bearish" else None,
            low if self.bias == "bullish" else None,
        )
        return state, tuple(current_bos + current_shifts)

    def _add_swing(self, index: int, price: float, kind: str,
                   confirmed_at: int) -> None:
        extreme = self._classification_extreme[kind]
        extends = extreme is not None and (
            price > extreme.price if kind == "high" else price < extreme.price
        )
        swing = SwingPoint(index, price, kind,
                           "external" if extends else "internal", confirmed_at)
        if extreme is None or extends:
            self._classification_extreme[kind] = swing
        (self.highs if kind == "high" else self.lows).append(swing)

    def _active(self, side: str, swings: list[SwingPoint],
                index: int) -> SwingPoint | None:
        external = self._classification_extreme[side]
        if (external is not None and external.structure == "external"
                and external.confirmed_at is not None
                and external.confirmed_at <= index and external.index < index):
            return external
        latest = swings[-1] if swings else None
        return (latest if latest is not None and latest.confirmed_at is not None
                and latest.confirmed_at <= index and latest.index < index else None)


class _IncrementalLiquidity:
    def __init__(self, tolerance: float, reclaim_window: int):
        self.tolerance = tolerance
        self.reclaim_window = reclaim_window
        self.groups: dict[str, list[list[SwingPoint]]] = {
            "buy_side": [], "sell_side": [],
        }
        self.pools: dict[str, LiquidityPool] = {}
        self.events: dict[str, list[LiquidityEvent]] = {}
        self.breached_at: dict[str, int | None] = {}
        self.consumed: set[str] = set()
        self._seen = {"high": 0, "low": 0}

    def advance(self, candles: tuple[Candle, ...], index: int,
                highs: list[SwingPoint], lows: list[SwingPoint]):
        for swings, kind, side in ((highs, "high", "buy_side"),
                                   (lows, "low", "sell_side")):
            for swing in swings[self._seen[kind]:]:
                self._add_swing(swing, side)
            self._seen[kind] = len(swings)

        for pool in self._ordered_pools():
            if pool.id not in self.consumed:
                self._apply(pool, candles[index], index)
        events = tuple(sorted(
            (event for items in self.events.values() for event in items),
            key=lambda event: (event.index, event.pool_id),
        ))
        terminal = {event.pool_id for event in events
                    if event.pool_state == "consumed"}
        active = tuple(pool for pool in self._ordered_pools()
                       if pool.id not in terminal)
        current = tuple(event for event in events if event.index == index)
        return active, current, events

    def _add_swing(self, swing: SwingPoint, side: str) -> None:
        groups = self.groups[side]
        decimal_price = Decimal(str(swing.price))
        tolerance = Decimal(str(self.tolerance))
        group = next((items for items in groups if abs(
            decimal_price - sum((Decimal(str(item.price)) for item in items),
                                Decimal(0)) / len(items)
        ) <= tolerance), None)
        if group is None:
            group = [swing]
            groups.append(group)
        else:
            group.append(swing)
        number = groups.index(group)
        pool_id = f"{side}:{number}:{group[0].index}"
        pool = LiquidityPool(
            pool_id, side, sum(item.price for item in group) / len(group),
            tuple(item.index for item in group),
            max(item.confirmed_at for item in group if item.confirmed_at is not None),
            "external" if any(item.structure == "external" for item in group)
            else "internal",
        )
        self.pools[pool_id] = pool
        # A changed group is a newly confirmed reference pool in the oracle.
        self.events[pool_id] = []
        self.breached_at[pool_id] = None
        self.consumed.discard(pool_id)

    def _ordered_pools(self) -> list[LiquidityPool]:
        return sorted(self.pools.values(),
                      key=lambda pool: (pool.confirmed_at, pool.level, pool.id))

    def _apply(self, pool: LiquidityPool, candle: Candle, index: int) -> None:
        available_at = max(pool.confirmed_at, max(pool.source_indices) + 1)
        if index < available_at:
            return
        side = pool.side
        beyond = candle.high > pool.level if side == "buy_side" else candle.low < pool.level
        close_beyond = candle.close > pool.level if side == "buy_side" else candle.close < pool.level
        close_back = candle.close < pool.level if side == "buy_side" else candle.close > pool.level
        sweep_direction = "bearish" if side == "buy_side" else "bullish"
        breached_at = self.breached_at[pool.id]
        if breached_at is None:
            if not beyond:
                return
            if close_back:
                self._event(pool, index, "wick_swept", candle.close, index, index,
                            sweep_direction, "wick_sweep", "consumed")
                self.consumed.add(pool.id)
                return
            if not close_beyond:
                self._event(pool, index, "touched", candle.close, index, None,
                            sweep_direction, None, "active")
                return
            self.breached_at[pool.id] = index
            self._event(pool, index, "body_breached", candle.close, index, None,
                        sweep_direction, "breach", "active")
            if self.reclaim_window == 0:
                self._event(pool, index, "accepted_beyond", candle.close, index, index,
                            "bullish" if side == "buy_side" else "bearish",
                            "structural_break", "consumed")
                self.consumed.add(pool.id)
            return
        if index <= breached_at + self.reclaim_window and close_back:
            self._event(pool, index, "reclaimed", candle.close, breached_at, index,
                        sweep_direction, "reclaim_sweep", "consumed")
            self.consumed.add(pool.id)
        elif index >= breached_at + self.reclaim_window:
            self._event(pool, index, "accepted_beyond", candle.close, breached_at, index,
                        "bullish" if side == "buy_side" else "bearish",
                        "structural_break", "consumed")
            self.consumed.add(pool.id)

    def _event(self, pool, index, state, close, penetration, confirmation,
               direction, event_type, pool_state):
        self.events[pool.id].append(LiquidityEvent(
            index, pool.id, pool.side, pool.level, state, close, penetration,
            confirmation, direction, event_type, pool.source_indices, pool_state,
        ))


class _IncrementalExecutionState:
    def __init__(self, config: EngineConfig):
        self.config = config
        self.structure = _IncrementalStructure(config.swing_window)
        self.liquidity = _IncrementalLiquidity(config.liquidity_tolerance,
                                               config.reclaim_window)
        self.gaps: list[Gap] = []
        self.inversions: dict[int, InvertedFairValueGap] = {}

    def advance(self, candles: tuple[Candle, ...], index: int):
        state, structure_events = self.structure.advance(candles, index)
        active, liquidity_events, all_liquidity = self.liquidity.advance(
            candles, index, self.structure.highs, self.structure.lows,
        )
        self._advance_gaps(candles, index)
        displacement = self._displacement(candles, index)
        return (state, structure_events, active, liquidity_events, all_liquidity,
                tuple(self.gaps), tuple(self.inversions[key]
                                        for key in sorted(self.inversions)),
                displacement)

    def _advance_gaps(self, candles: tuple[Candle, ...], index: int) -> None:
        candle = candles[index]
        updated = []
        for gap in self.gaps:
            state = gap
            if gap.state != "invalidated" and index > gap.created_at:
                overlaps = candle.low <= gap.upper and candle.high >= gap.lower
                if overlaps:
                    first_touch = gap.first_touch if gap.first_touch is not None else index
                    invalid = (candle.close < gap.lower if gap.direction == "bullish"
                               else candle.close > gap.upper)
                    if invalid:
                        state = replace(gap, state="invalidated", first_touch=first_touch,
                                        invalidated_at=index)
                    elif gap.direction == "bullish" and candle.low <= gap.lower:
                        state = replace(gap, state="mitigated", first_touch=first_touch,
                                        mitigation_fraction=1.0)
                    elif gap.direction == "bearish" and candle.high >= gap.upper:
                        state = replace(gap, state="mitigated", first_touch=first_touch,
                                        mitigation_fraction=1.0)
                    else:
                        fraction = ((gap.upper - candle.low) / (gap.upper - gap.lower)
                                    if gap.direction == "bullish" else
                                    (candle.high - gap.lower) / (gap.upper - gap.lower))
                        state = replace(
                            gap, state="partial", first_touch=first_touch,
                            mitigation_fraction=max(gap.mitigation_fraction,
                                                    min(1.0, max(0.0, fraction))),
                        )
            updated.append(state)
            if (state.state == "invalidated" and gap.created_at not in self.inversions):
                self.inversions[gap.created_at] = InvertedFairValueGap(
                    index, gap.created_at,
                    "bearish" if gap.direction == "bullish" else "bullish",
                    gap.lower, gap.upper,
                )
        self.gaps = updated
        if index >= 2:
            first = candles[index - 2]
            if candle.low > first.high:
                self.gaps.append(Gap(index, "bullish", first.high, candle.low,
                                     state="active"))
            elif candle.high < first.low:
                self.gaps.append(Gap(index, "bearish", candle.high, first.low,
                                     state="active"))

    def _displacement(self, candles: tuple[Candle, ...], index: int):
        config = self.config
        if index < config.displacement_lookback:
            return None
        candle = candles[index]
        candle_range = candle.high - candle.low
        if candle_range <= 0:
            return None
        ranges = [item.high - item.low
                  for item in candles[index - config.displacement_lookback:index]
                  if item.high > item.low]
        if not ranges:
            return None
        body = abs(candle.close - candle.open)
        if (body / candle_range >= config.displacement_body_ratio
                and candle_range >= sum(ranges) / len(ranges)
                * config.displacement_range_multiple
                and candle.close != candle.open):
            return Displacement(index,
                                "bullish" if candle.close > candle.open else "bearish",
                                body, candle_range)
        return None


class OptimizedSequentialResearchEngine(SequentialResearchEngine):
    """Drop-in snapshot-equivalent engine with incremental detector state."""

    def __init__(self, execution, higher_timeframe=None, config=None):
        super().__init__(execution, higher_timeframe, config)
        self._state = _IncrementalExecutionState(self.config)
        self._htf_structure = _IncrementalStructure(self.config.swing_window)
        self._htf_contexts: list[HigherTimeframeContext] = []

    def _build_snapshot(self, index: int) -> EngineSnapshot:
        timestamp = (None if self.execution.timestamps is None
                     else self.execution.timestamps[index])
        alignment = None
        if self.higher_timeframe is None:
            htf = HigherTimeframeContext(None, None, "neutral", None, None)
        else:
            alignment = align_completed_candle(self.execution, self.higher_timeframe, index)
            completed = alignment.higher_timeframe_index
            while completed is not None and len(self._htf_contexts) <= completed:
                htf_index = len(self._htf_contexts)
                state, _ = self._htf_structure.advance(
                    self.higher_timeframe.candles, htf_index)
                htf = HigherTimeframeContext(
                    self.higher_timeframe.timeframe, htf_index,
                    self._htf_structure.bias, state,
                    _latest_event(tuple(self._htf_structure.bos)
                                  + tuple(self._htf_structure.shifts)),
                )
                self._htf_contexts.append(htf)
            htf = (HigherTimeframeContext(self.higher_timeframe.timeframe, None,
                                          "neutral", None, None)
                   if completed is None else self._htf_contexts[completed])

        (state, structure_events, active, liquidity_events, all_liquidity,
         gaps, inverted, displacement) = self._state.advance(
             self.execution.candles, index)
        dealing_range = None
        price_zone = None
        if (state.external_low is not None and state.external_high is not None
                and state.external_low.price < state.external_high.price):
            dealing_range = DealingRange(state.external_low.price,
                                         state.external_high.price)
            price_zone = dealing_range.position(
                self.execution.candles[index].close,
                self.config.equilibrium_tolerance,
            )
        evidence, signal = self._candidate(
            index, htf, self._state.structure.shifts, all_liquidity,
            displacement, gaps, inverted, price_zone,
        )
        return EngineSnapshot(
            index, timestamp, alignment, htf, self._state.structure.bias, state,
            active, liquidity_events, structure_events, gaps, inverted,
            displacement, dealing_range, price_zone, evidence, signal,
        )
