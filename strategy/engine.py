from dataclasses import dataclass

from strategy.confluence import Evidence, ResearchSignal, build_candidate_signal
from strategy.context import DealingRange, Zone
from strategy.fvg import (Displacement, InvertedFairValueGap,
                          detect_displacement, detect_ifvgs)
from strategy.imbalance import Gap, detect_gaps, evolve_gap
from strategy.liquidity_v2 import (LiquidityEvent, LiquidityPool,
                                   build_swing_pools, track_liquidity)
from strategy.structure import (Direction, StructureEvent, StructureShift,
                                StructureState, classify_structure, detect_bos,
                                detect_structure_shift, detect_swing_highs,
                                detect_swing_lows, determine_market_bias,
                                structural_state)
from strategy.timeframes import (ContextSeries, TimeframeAlignment,
                                  align_completed_candle)


@dataclass(frozen=True)
class EngineConfig:
    swing_window: int = 2
    liquidity_tolerance: float = 0.0
    reclaim_window: int = 1
    displacement_lookback: int = 5
    displacement_range_multiple: float = 1.5
    displacement_body_ratio: float = 0.6
    equilibrium_tolerance: float = 0.0
    require_htf_bias: bool = True
    require_liquidity_event: bool = True
    require_mss: bool = True
    require_displacement: bool = True
    require_pd_array: bool = True
    require_price_zone: bool = True

    def __post_init__(self):
        if self.swing_window < 1:
            raise ValueError("swing_window must be at least 1")
        if self.liquidity_tolerance < 0:
            raise ValueError("liquidity_tolerance cannot be negative")
        if self.reclaim_window < 0:
            raise ValueError("reclaim_window cannot be negative")
        if self.displacement_lookback < 1:
            raise ValueError("displacement_lookback must be at least 1")
        if self.displacement_range_multiple <= 0:
            raise ValueError("displacement_range_multiple must be positive")
        if not 0 < self.displacement_body_ratio <= 1:
            raise ValueError("displacement_body_ratio must be in (0, 1]")
        if self.equilibrium_tolerance < 0:
            raise ValueError("equilibrium_tolerance cannot be negative")


@dataclass(frozen=True)
class HigherTimeframeContext:
    timeframe: str | None
    completed_index: int | None
    bias: Direction
    structure: StructureState | None
    most_recent_event: StructureEvent | StructureShift | None


@dataclass(frozen=True)
class EngineSnapshot:
    execution_index: int
    execution_timestamp: object | None
    alignment: TimeframeAlignment | None
    htf_context: HigherTimeframeContext
    execution_bias: Direction
    structural_state: StructureState
    active_liquidity: tuple[LiquidityPool, ...]
    liquidity_events: tuple[LiquidityEvent, ...]
    structure_events: tuple[StructureEvent | StructureShift, ...]
    imbalances: tuple[Gap, ...]
    inverted_gaps: tuple[InvertedFairValueGap, ...]
    displacement: Displacement | None
    dealing_range: DealingRange | None
    price_zone: Zone | None
    evidence: tuple[Evidence, ...]
    signal: ResearchSignal | None = None


def _classified_swings(candles, window):
    raw = detect_swing_highs(candles, window) + detect_swing_lows(candles, window)
    classified = classify_structure(raw)
    return ([s for s in classified if s.kind == "high"],
            [s for s in classified if s.kind == "low"])


def _latest_event(events):
    if not events:
        return None
    return sorted(events, key=lambda event: (event.index, event.kind))[-1]


def _htf_context(series: ContextSeries, completed_index: int | None,
                 config: EngineConfig) -> HigherTimeframeContext:
    if completed_index is None:
        return HigherTimeframeContext(series.timeframe, None, "neutral", None, None)
    visible = series.candles[:completed_index + 1]
    highs, lows = _classified_swings(visible, config.swing_window)
    bos = detect_bos(visible, highs, lows)
    shifts = detect_structure_shift(visible, highs, lows)
    bias = determine_market_bias(bos, shifts)
    state = structural_state(highs + lows, completed_index, bias)
    return HigherTimeframeContext(
        series.timeframe, completed_index, bias, state,
        _latest_event(tuple(bos) + tuple(shifts)),
    )


def _source_id(prefix: str, index: int | None) -> str | None:
    return None if index is None else f"{prefix}:{index}"


class SequentialResearchEngine:
    """Offline completed-candle engine with immutable, auditable snapshots."""

    def __init__(self, execution: ContextSeries,
                 higher_timeframe: ContextSeries | None = None,
                 config: EngineConfig | None = None):
        self.execution = execution
        self.higher_timeframe = higher_timeframe
        self.config = config or EngineConfig()
        if higher_timeframe is not None:
            execution.require_timestamps()
            higher_timeframe.require_timestamps()
        self._next_index = 0
        self._snapshots: list[EngineSnapshot] = []

    @property
    def snapshots(self) -> tuple[EngineSnapshot, ...]:
        return tuple(self._snapshots)

    def advance(self) -> EngineSnapshot:
        if self._next_index >= len(self.execution.candles):
            raise StopIteration("all execution candles have been processed")
        snapshot = self._build_snapshot(self._next_index)
        self._snapshots.append(snapshot)
        self._next_index += 1
        return snapshot

    def run(self) -> tuple[EngineSnapshot, ...]:
        while self._next_index < len(self.execution.candles):
            self.advance()
        return self.snapshots

    def _build_snapshot(self, index: int) -> EngineSnapshot:
        config = self.config
        visible = self.execution.candles[:index + 1]
        timestamp = (None if self.execution.timestamps is None
                     else self.execution.timestamps[index])

        alignment = None
        if self.higher_timeframe is None:
            htf = HigherTimeframeContext(None, None, "neutral", None, None)
        else:
            alignment = align_completed_candle(
                self.execution, self.higher_timeframe, index
            )
            htf = _htf_context(
                self.higher_timeframe, alignment.higher_timeframe_index, config
            )

        highs, lows = _classified_swings(visible, config.swing_window)
        bos = detect_bos(visible, highs, lows)
        shifts = detect_structure_shift(visible, highs, lows)
        execution_bias = determine_market_bias(bos, shifts)
        state = structural_state(highs + lows, index, execution_bias)
        current_structure = tuple(
            event for event in tuple(bos) + tuple(shifts) if event.index == index
        )

        pools = build_swing_pools(highs, lows, config.liquidity_tolerance)
        all_liquidity_events = track_liquidity(visible, pools, config.reclaim_window)
        terminal_pool_ids = {
            event.pool_id for event in all_liquidity_events
            if event.pool_state == "consumed"
        }
        active_pools = tuple(pool for pool in pools if pool.id not in terminal_pool_ids)
        current_liquidity = tuple(
            event for event in all_liquidity_events if event.index == index
        )

        gaps = detect_gaps(visible)
        evolved_gaps = tuple(evolve_gap(visible, gap) for gap in gaps)
        inverted = tuple(detect_ifvgs(visible))
        displacements = detect_displacement(
            visible, config.displacement_lookback,
            config.displacement_range_multiple, config.displacement_body_ratio,
        )
        displacement = next(
            (event for event in reversed(displacements) if event.index == index), None
        )

        dealing_range = None
        price_zone = None
        if (state.external_low is not None and state.external_high is not None
                and state.external_low.price < state.external_high.price):
            dealing_range = DealingRange(state.external_low.price,
                                         state.external_high.price)
            price_zone = dealing_range.position(
                visible[-1].close, config.equilibrium_tolerance
            )

        evidence, signal = self._candidate(
            index, htf, shifts, all_liquidity_events, displacement,
            evolved_gaps, inverted, price_zone,
        )
        return EngineSnapshot(
            index, timestamp, alignment, htf, execution_bias, state,
            active_pools, current_liquidity, current_structure, evolved_gaps,
            inverted, displacement, dealing_range, price_zone, evidence, signal,
        )

    def _candidate(self, index, htf, shifts, liquidity_events, displacement,
                   gaps, inverted, price_zone):
        config = self.config
        current_shifts = [event for event in shifts if event.index == index]
        shift = current_shifts[-1] if current_shifts else None
        current_terminal_liquidity = [
            event for event in liquidity_events
            if event.index == index and event.pool_state == "consumed"
        ]
        if shift is not None:
            direction = shift.direction
        elif displacement is not None:
            direction = displacement.direction
        elif current_terminal_liquidity:
            direction = current_terminal_liquidity[-1].direction
        else:
            return (), None
        if direction not in ("bullish", "bearish"):
            return (), None
        terminal_liquidity = [
            event for event in liquidity_events
            if event.index <= index and event.pool_state == "consumed"
            and event.direction == direction
        ]
        liquidity = terminal_liquidity[-1] if terminal_liquidity else None
        matching_displacement = (
            displacement if displacement is not None
            and displacement.direction == direction else None
        )
        matching_ifvg = next(
            (gap for gap in reversed(inverted)
             if gap.index <= index and gap.direction == direction), None
        )
        matching_gap = next(
            (gap for gap in reversed(gaps)
             if gap.created_at <= index and gap.direction == direction), None
        )
        pd_array = matching_ifvg or matching_gap
        zone_passed = price_zone in (
            ("discount", "equilibrium") if direction == "bullish"
            else ("premium", "equilibrium")
        )
        htf_passed = htf.bias == direction

        evidence = (
            Evidence("HTF context", htf_passed,
                     f"completed HTF bias is {htf.bias}", index=htf.completed_index,
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
                     source_id=None if shift is None else _source_id(
                         "swing", shift.broken_swing_index)),
            Evidence("displacement", matching_displacement is not None,
                     "matching displacement" if matching_displacement else "none",
                     index=None if matching_displacement is None else matching_displacement.index,
                     source_id=_source_id("displacement", None if matching_displacement is None
                                          else matching_displacement.index)),
            Evidence("PD array", pd_array is not None,
                     "none" if pd_array is None else type(pd_array).__name__,
                     index=None if pd_array is None else (
                         pd_array.index if isinstance(pd_array, InvertedFairValueGap)
                         else pd_array.created_at),
                     source_id=None if pd_array is None else _source_id(
                         "ifvg" if isinstance(pd_array, InvertedFairValueGap) else "fvg",
                         pd_array.index if isinstance(pd_array, InvertedFairValueGap)
                         else pd_array.created_at)),
            Evidence("premium/discount", zone_passed,
                     "unavailable" if price_zone is None else price_zone,
                     index=index, source_id=_source_id("range", index)),
        )
        required = (
            (not config.require_htf_bias or htf_passed)
            and (not config.require_liquidity_event or liquidity is not None)
            and (not config.require_mss or shift is not None)
            and (not config.require_displacement or matching_displacement is not None)
            and (not config.require_pd_array or pd_array is not None)
            and (not config.require_price_zone or zone_passed)
        )
        final_evidence = evidence + (Evidence(
            "candidate setup", required,
            "all configured evidence requirements passed" if required
            else "configured evidence requirements incomplete",
            index=index, source_id=_source_id("candidate", index),
        ),)
        ordered = build_candidate_signal(index, direction, final_evidence)
        return ordered.evidence, ordered if required else None
