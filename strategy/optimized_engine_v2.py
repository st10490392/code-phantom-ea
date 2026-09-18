"""Revision 2 incremental engine with indexed/cached cumulative state.

The frozen reference and Execution Revision 1 remain unchanged.  This module
preserves their observable snapshots while avoiding repeated sorting,
history flattening, and rebuilding of unchanged immutable tuples.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import replace
from decimal import Decimal

from strategy.confluence import Evidence, build_candidate_signal
from strategy.context import DealingRange
from strategy.engine import EngineSnapshot, HigherTimeframeContext, _latest_event, _source_id
from strategy.fvg import InvertedFairValueGap
from strategy.imbalance import Gap
from strategy.liquidity_v2 import LiquidityEvent, LiquidityPool
from strategy.optimized_engine import (_IncrementalExecutionState,
                                       _IncrementalLiquidity,
                                       _IncrementalStructure,
                                       OptimizedSequentialResearchEngine)
from strategy.timeframes import align_completed_candle


class _LiquidityV2(_IncrementalLiquidity):
    def __init__(self, tolerance: float, reclaim_window: int):
        super().__init__(tolerance, reclaim_window)
        self._ordered: list[LiquidityPool] = []
        self._active_tuple: tuple[LiquidityPool, ...] = ()
        self._active_dirty = False
        self._terminal_by_pool: dict[str, LiquidityEvent] = {}
        self.latest_terminal: dict[str, LiquidityEvent | None] = {
            "bullish": None, "bearish": None,
        }
        self._decimal_sums: dict[str, Decimal] = {}
        self._exact_groups: dict[str, dict[Decimal, list]] = {
            "buy_side": {}, "sell_side": {},
        }
        self._level_index: dict[str, list[tuple[float, str]]] = {
            "buy_side": [], "sell_side": [],
        }
        self._indexed: set[str] = set()
        self._pending: set[str] = set()

    def advance(self, candles, index, highs, lows):
        for swings, kind, side in ((highs, "high", "buy_side"),
                                   (lows, "low", "sell_side")):
            for swing in swings[self._seen[kind]:]:
                self._add_swing_v2(swing, side)
            self._seen[kind] = len(swings)

        current = []
        candle = candles[index]
        buy = self._level_index["buy_side"]
        sell = self._level_index["sell_side"]
        buy_stop = bisect_left(buy, (candle.high, ""))
        sell_start = bisect_left(sell, (candle.low, "\uffff"))
        process_ids = ({pool_id for _, pool_id in buy[:buy_stop]}
                       | {pool_id for _, pool_id in sell[sell_start:]}
                       | self._pending)
        for pool_id in tuple(process_ids):
            pool = self.pools[pool_id]
            before = len(self.events[pool.id])
            self._apply(pool, candle, index)
            emitted = self.events[pool.id][before:]
            current.extend(emitted)
            if self.breached_at[pool.id] is not None and pool.id not in self.consumed:
                self._remove_level(pool)
                self._pending.add(pool.id)
            terminal = next((event for event in reversed(emitted)
                             if event.pool_state == "consumed"), None)
            if terminal is not None:
                self._terminal_by_pool[pool.id] = terminal
                self._remove_level(pool)
                self._pending.discard(pool.id)
                self._active_dirty = True
        if self._active_dirty:
            self._refresh_active()
        current_tuple = tuple(sorted(current, key=lambda event: event.pool_id))
        for event in current_tuple:
            if event.pool_state == "consumed" and event.direction in self.latest_terminal:
                self.latest_terminal[event.direction] = event
        return self._active_tuple, current_tuple

    def _refresh_active(self):
        self._active_tuple = tuple(pool for pool in self._ordered
                                   if pool.id not in self.consumed)
        self._active_dirty = False
        return self._active_tuple

    def _add_swing_v2(self, swing, side):
        groups = self.groups[side]
        decimal_price = Decimal(str(swing.price))
        if self.tolerance == 0.0:
            group = self._exact_groups[side].get(decimal_price)
        else:
            tolerance = Decimal(str(self.tolerance))
            group = next((items for items in groups if abs(
                decimal_price - self._decimal_sums[self._pool_id(side, items)]
                / len(items)
            ) <= tolerance), None)
        if group is None:
            group = [swing]
            groups.append(group)
            if self.tolerance == 0.0:
                self._exact_groups[side][decimal_price] = group
        else:
            group.append(swing)
        pool_id = self._pool_id(side, group)
        if pool_id not in self._decimal_sums:
            self._decimal_sums[pool_id] = Decimal(0)
        self._decimal_sums[pool_id] += decimal_price
        old = self.pools.get(pool_id)
        if old is not None:
            self._ordered.remove(old)
            self._remove_level(old)
            self._pending.discard(pool_id)
        pool = LiquidityPool(
            pool_id, side, sum(item.price for item in group) / len(group),
            tuple(item.index for item in group),
            max(item.confirmed_at for item in group if item.confirmed_at is not None),
            "external" if any(item.structure == "external" for item in group)
            else "internal",
        )
        key = (pool.confirmed_at, pool.level, pool.id)
        keys = [(item.confirmed_at, item.level, item.id) for item in self._ordered]
        self._ordered.insert(bisect_left(keys, key), pool)
        self.pools[pool_id] = pool
        self.events[pool_id] = []
        self.breached_at[pool_id] = None
        self.consumed.discard(pool_id)
        removed_terminal = self._terminal_by_pool.pop(pool_id, None)
        if removed_terminal is not None:
            self._recompute_latest_terminals()
        self._insert_level(pool)
        self._active_dirty = True

    def _pool_id(self, side, group):
        return f"{side}:{self.groups[side].index(group)}:{group[0].index}"

    def _recompute_latest_terminals(self):
        for direction in self.latest_terminal:
            candidates = [event for event in self._terminal_by_pool.values()
                          if event.direction == direction]
            self.latest_terminal[direction] = (max(
                candidates, key=lambda event: (event.index, event.pool_id)
            ) if candidates else None)

    def _insert_level(self, pool):
        if pool.id in self._indexed:
            return
        items = self._level_index[pool.side]
        items.insert(bisect_left(items, (pool.level, pool.id)),
                     (pool.level, pool.id))
        self._indexed.add(pool.id)

    def _remove_level(self, pool):
        if pool.id not in self._indexed:
            return
        items = self._level_index[pool.side]
        position = bisect_left(items, (pool.level, pool.id))
        if position < len(items) and items[position] == (pool.level, pool.id):
            items.pop(position)
        self._indexed.discard(pool.id)


class _ExecutionStateV2(_IncrementalExecutionState):
    def __init__(self, config):
        super().__init__(config)
        self.liquidity = _LiquidityV2(config.liquidity_tolerance,
                                      config.reclaim_window)
        self._gap_tuple: tuple[Gap, ...] = ()
        self._inversion_tuple: tuple[InvertedFairValueGap, ...] = ()
        self._live_gap_indices: list[int] = []
        self.latest_gap = {"bullish": None, "bearish": None}
        self.latest_inversion = {"bullish": None, "bearish": None}

    def advance(self, candles, index):
        state, structure_events = self.structure.advance(candles, index)
        active, liquidity_events = self.liquidity.advance(
            candles, index, self.structure.highs, self.structure.lows,
        )
        self._advance_gaps_v2(candles, index)
        displacement = self._displacement(candles, index)
        return (state, structure_events, active, liquidity_events,
                self._gap_tuple, self._inversion_tuple, displacement)

    def _advance_gaps_v2(self, candles, index):
        candle = candles[index]
        changed = False
        still_live = []
        for position in self._live_gap_indices:
            gap = self.gaps[position]
            state = gap
            overlaps = candle.low <= gap.upper and candle.high >= gap.lower
            if overlaps:
                first_touch = gap.first_touch if gap.first_touch is not None else index
                invalid = (candle.close < gap.lower if gap.direction == "bullish"
                           else candle.close > gap.upper)
                if invalid:
                    state = replace(gap, state="invalidated", first_touch=first_touch,
                                    invalidated_at=index)
                    inversion = InvertedFairValueGap(
                        index, gap.created_at,
                        "bearish" if gap.direction == "bullish" else "bullish",
                        gap.lower, gap.upper,
                    )
                    self.inversions[gap.created_at] = inversion
                    current = self.latest_inversion[inversion.direction]
                    if current is None or inversion.source_index > current.source_index:
                        self.latest_inversion[inversion.direction] = inversion
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
                if state != gap:
                    self.gaps[position] = state
                    changed = True
            if state.state != "invalidated":
                still_live.append(position)
        self._live_gap_indices = still_live
        if index >= 2:
            first = candles[index - 2]
            gap = None
            if candle.low > first.high:
                gap = Gap(index, "bullish", first.high, candle.low, state="active")
            elif candle.high < first.low:
                gap = Gap(index, "bearish", candle.high, first.low, state="active")
            if gap is not None:
                self.gaps.append(gap)
                self._live_gap_indices.append(len(self.gaps) - 1)
                self.latest_gap[gap.direction] = gap
                changed = True
        if changed:
            self._gap_tuple = tuple(self.gaps)
            self._inversion_tuple = tuple(self.inversions[key]
                                          for key in sorted(self.inversions))


class OptimizedSequentialResearchEngineV2(OptimizedSequentialResearchEngine):
    """Exact snapshot-equivalent engine with indexed cumulative histories."""

    def __init__(self, execution, higher_timeframe=None, config=None):
        super().__init__(execution, higher_timeframe, config)
        self._state = _ExecutionStateV2(self.config)

    def _build_snapshot(self, index):
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
                state, _ = self._htf_structure.advance(self.higher_timeframe.candles,
                                                        htf_index)
                self._htf_contexts.append(HigherTimeframeContext(
                    self.higher_timeframe.timeframe, htf_index,
                    self._htf_structure.bias, state,
                    _latest_event(tuple(self._htf_structure.bos)
                                  + tuple(self._htf_structure.shifts)),
                ))
            htf = (HigherTimeframeContext(self.higher_timeframe.timeframe, None,
                                          "neutral", None, None)
                   if completed is None else self._htf_contexts[completed])

        (state, structure_events, active, liquidity_events, gaps, inverted,
         displacement) = self._state.advance(self.execution.candles, index)
        dealing_range = price_zone = None
        if (state.external_low is not None and state.external_high is not None
                and state.external_low.price < state.external_high.price):
            dealing_range = DealingRange(state.external_low.price,
                                         state.external_high.price)
            price_zone = dealing_range.position(
                self.execution.candles[index].close,
                self.config.equilibrium_tolerance,
            )
        evidence, signal = self._candidate_v2(
            index, htf, displacement, price_zone, liquidity_events)
        return EngineSnapshot(
            index, timestamp, alignment, htf, self._state.structure.bias, state,
            active, liquidity_events, structure_events, gaps, inverted,
            displacement, dealing_range, price_zone, evidence, signal,
        )

    def _candidate_v2(self, index, htf, displacement, price_zone,
                      liquidity_events):
        config = self.config
        shifts = self._state.structure.shifts
        shift = shifts[-1] if shifts and shifts[-1].index == index else None
        current_terminal = [event for event in liquidity_events
                            if event.index == index and event.pool_state == "consumed"]
        if shift is not None:
            direction = shift.direction
        elif displacement is not None:
            direction = displacement.direction
        elif current_terminal:
            direction = current_terminal[-1].direction
        else:
            return (), None
        if direction not in ("bullish", "bearish"):
            return (), None
        liquidity = self._state.liquidity.latest_terminal[direction]
        matching_displacement = (displacement if displacement is not None
                                 and displacement.direction == direction else None)
        matching_ifvg = self._state.latest_inversion[direction]
        matching_gap = self._state.latest_gap[direction]
        pd_array = matching_ifvg or matching_gap
        zone_passed = price_zone in (("discount", "equilibrium")
                                     if direction == "bullish"
                                     else ("premium", "equilibrium"))
        htf_passed = htf.bias == direction
        evidence = (
            Evidence("HTF context", htf_passed, f"completed HTF bias is {htf.bias}",
                     index=htf.completed_index,
                     source_id=_source_id("htf", htf.completed_index)),
            Evidence("liquidity target", liquidity is not None,
                     "matching confirmed liquidity pool" if liquidity else "none",
                     index=None if liquidity is None else liquidity.penetration_index,
                     source_id=None if liquidity is None else liquidity.pool_id),
            Evidence("liquidity event", liquidity is not None,
                     "none" if liquidity is None else str(liquidity.event_type),
                     index=None if liquidity is None else liquidity.index,
                     source_id=None if liquidity is None else liquidity.pool_id),
            Evidence("structural shift", shift is not None,
                     "confirmed MSS" if shift is not None else "none",
                     index=None if shift is None else shift.index,
                     source_id=None if shift is None else
                     _source_id("swing", shift.broken_swing_index)),
            Evidence("displacement", matching_displacement is not None,
                     "matching displacement" if matching_displacement else "none",
                     index=None if matching_displacement is None else
                     matching_displacement.index,
                     source_id=_source_id("displacement", None if
                                          matching_displacement is None else
                                          matching_displacement.index)),
            Evidence("PD array", pd_array is not None,
                     "none" if pd_array is None else type(pd_array).__name__,
                     index=None if pd_array is None else
                     (pd_array.index if isinstance(pd_array, InvertedFairValueGap)
                      else pd_array.created_at),
                     source_id=None if pd_array is None else _source_id(
                         "ifvg" if isinstance(pd_array, InvertedFairValueGap) else "fvg",
                         pd_array.index if isinstance(pd_array, InvertedFairValueGap)
                         else pd_array.created_at)),
            Evidence("premium/discount", zone_passed,
                     "unavailable" if price_zone is None else price_zone,
                     index=index, source_id=_source_id("range", index)),
        )
        required = ((not config.require_htf_bias or htf_passed)
                    and (not config.require_liquidity_event or liquidity is not None)
                    and (not config.require_mss or shift is not None)
                    and (not config.require_displacement or matching_displacement is not None)
                    and (not config.require_pd_array or pd_array is not None)
                    and (not config.require_price_zone or zone_passed))
        final = evidence + (Evidence(
            "candidate setup", required,
            "all configured evidence requirements passed" if required else
            "configured evidence requirements incomplete",
            index=index, source_id=_source_id("candidate", index)),)
        ordered = build_candidate_signal(index, direction, final)
        return ordered.evidence, ordered if required else None
