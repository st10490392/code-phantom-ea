"""Compact causal journal of the frozen CP-001 evidence path.

The observer receives one completed candle, its snapshot and a read-only
selection. It never receives an execution series or future candles.
"""
from bisect import bisect_left
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

from strategy.engine import EngineConfig

SCHEMA_VERSION = "research-observer/1"
GATES = ("HTF context", "liquidity event", "structural shift",
         "displacement", "PD array", "premium/discount")


@dataclass(frozen=True, slots=True)
class EventRef:
    index: int
    direction: str
    kind: str
    level: float | None
    source_index: int | None


@dataclass(frozen=True, slots=True)
class SwingRef:
    index: int
    confirmed_at: int | None
    price: float
    kind: str
    structure: str


@dataclass(frozen=True, slots=True)
class PDRef:
    kind: str
    direction: str
    index: int
    source_index: int
    lower: float
    upper: float
    state: str


def pd_ref(pd, kind):
    if pd is None:
        return None
    return PDRef(kind, pd.direction,
                 pd.index if kind == "IFVG" else pd.created_at,
                 pd.source_index if kind == "IFVG" else pd.created_at,
                 pd.lower, pd.upper, "inverted" if kind == "IFVG" else pd.state)


@dataclass(frozen=True, slots=True)
class LiquidityRef:
    index: int
    pool_id: str
    side: str
    level: float
    event_type: str | None


def liquidity_ref(event):
    return (None if event is None else LiquidityRef(
        event.index, event.pool_id, event.side, event.level, event.event_type))


@dataclass(frozen=True, slots=True)
class Selection:
    """Bounded references to already-computed immutable engine values."""
    liquidity: object | None = None
    pd: object | None = None
    pd_type: str | None = None
    liquidity_structure: str | None = None
    bullish_pd: PDRef | None = None
    bearish_pd: PDRef | None = None
    bullish_liquidity: LiquidityRef | None = None
    bearish_liquidity: LiquidityRef | None = None


def direction_trigger(snapshot):
    shifts = [e for e in snapshot.structure_events if e.kind == "MSS"]
    if shifts:
        return "current_mss", shifts[-1].direction
    if snapshot.displacement is not None:
        return "current_displacement", snapshot.displacement.direction
    terminal = [e for e in snapshot.liquidity_events if e.pool_state == "consumed"]
    if terminal:
        return "current_terminal_liquidity", terminal[-1].direction
    return None, None


def capture_selection(engine, snapshot):
    """Read-only Revision 2 adapter; call immediately after engine.advance().

    No engine cache eviction, mutation, or cumulative-history copying.
    The frozen engine identity is recorded in the exported manifest.
    """
    from strategy.optimized_engine_v2 import OptimizedSequentialResearchEngineV2
    if type(engine) is not OptimizedSequentialResearchEngineV2:
        raise TypeError("adapter requires frozen Execution Revision 2")
    if engine._next_index != snapshot.execution_index + 1 or engine._snapshots[-1] is not snapshot:
        raise ValueError("selection must accompany the current snapshot")
    if engine.config != EngineConfig():
        raise ValueError("adapter requires frozen CP-001 configuration")
    _, direction = direction_trigger(snapshot)
    state = engine._state

    def selected_pd(side):
        pd = state.latest_inversion[side]
        if pd is not None:
            return pd, "IFVG"
        pd = state.latest_gap[side]
        if pd is not None:
            # Creation pointer's state can be old; read the current lifecycle.
            position = bisect_left(snapshot.imbalances, pd.created_at,
                                   key=lambda gap: gap.created_at)
            pd = snapshot.imbalances[position]
        return pd, "FVG" if pd is not None else None

    bullish, bearish = selected_pd("bullish"), selected_pd("bearish")
    pd, kind = (bullish if direction == "bullish" else bearish) if direction else (None, None)
    liquidity = state.liquidity.latest_terminal[direction] if direction else None
    structure = state.liquidity.pools[liquidity.pool_id].structure if liquidity else None
    return Selection(liquidity, pd, kind, structure,
                     pd_ref(*bullish), pd_ref(*bearish),
                     liquidity_ref(state.liquidity.latest_terminal["bullish"]),
                     liquidity_ref(state.liquidity.latest_terminal["bearish"]))


def event_ref(event):
    if event is None:
        return None
    return EventRef(event.index, event.direction, event.kind,
                    getattr(event, "level", getattr(event, "broken_level", None)),
                    getattr(event, "broken_swing_index", None))


def swing_ref(swing):
    return (None if swing is None else SwingRef(
        swing.index, swing.confirmed_at, swing.price, swing.kind, swing.structure))


def utc_timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware completed-candle datetime required")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    schema_version: str
    instrument: str
    execution_timestamp: str
    execution_index: int
    direction_trigger: str | None
    selected_direction: str | None
    open: float
    high: float
    low: float
    close: float
    range_low: float | None
    range_high: float | None
    range_midpoint: float | None
    range_position: float | None
    price_zone: str | None
    h4_available: bool
    h4_completed_index: int | None
    h4_completed_timestamp: str | None
    h4_bias: str
    h4_event: EventRef | None
    structural_bias: str
    protected_high: SwingRef | None
    protected_low: SwingRef | None
    current_bos: tuple[EventRef, ...]
    current_mss: tuple[EventRef, ...]
    latest_bullish_mss: EventRef | None
    latest_bearish_mss: EventRef | None
    matching_mss_age: int | None
    liquidity_available: bool
    liquidity_pool_id: str | None
    liquidity_side: str | None
    liquidity_event_type: str | None
    liquidity_state: str | None
    liquidity_structure: str | None
    liquidity_source_index: int | None
    liquidity_confirmation_index: int | None
    liquidity_level: float | None
    liquidity_index: int | None
    liquidity_penetration_index: int | None
    liquidity_age: int | None
    latest_bullish_liquidity: LiquidityRef | None
    latest_bearish_liquidity: LiquidityRef | None
    current_displacement: bool
    displacement_direction: str | None
    candle_range: float
    body_range_ratio: float | None
    displacement_reference_range: float | None
    displacement_range_threshold: float | None
    displacement_body_threshold: float
    latest_bullish_displacement_index: int | None
    latest_bearish_displacement_index: int | None
    matching_displacement_age: int | None
    pd_type: str | None
    pd_direction: str | None
    pd_lower: float | None
    pd_upper: float | None
    pd_index: int | None
    pd_source_index: int | None
    pd_age: int | None
    pd_state: str | None
    pd_is_current: bool | None
    latest_bullish_pd: PDRef | None
    latest_bearish_pd: PDRef | None
    gate_passes: tuple[bool, ...]
    gates_passed: int
    gates_required: int
    first_failed_gate: str | None
    missing_gates: tuple[str, ...]
    accepted_by_cp001_v1: bool
    entry: float
    invalidation: float | None
    risk_distance: float | None
    levels_valid: bool
    levels_reason: str | None


def structural_levels(candle, snapshot, direction):
    """Same protected-anchor geometry, also for rejected observations.

    Does not fabricate a ResearchSignal or a fallback stop.
    """
    if direction not in ("bullish", "bearish"):
        return None, None, "no_selected_direction"
    state = snapshot.structural_state
    anchor = state.protected_low if direction == "bullish" else state.protected_high
    if anchor is None:
        return None, None, "missing_protected_swing"
    stop = anchor.price
    if not isfinite(stop):
        return None, None, "non_finite_anchor"
    risk = abs(candle.close - stop)
    if risk == 0:
        return stop, None, "zero_risk"
    if (direction == "bullish" and stop > candle.close) or (direction == "bearish" and stop < candle.close):
        return stop, None, "directionally_invalid_anchor"
    if not isfinite(risk) or not isfinite(candle.close + (2 * risk if direction == "bullish" else -2 * risk)):
        return stop, None, "invalid_level_construction"
    return stop, risk, None


class ResearchObserver:
    def __init__(self, instrument, config=None, *, include_untriggered=False):
        if not isinstance(instrument, str) or not instrument.strip():
            raise ValueError("instrument required")
        self.config = config or EngineConfig()
        if self.config != EngineConfig():
            raise ValueError("V1 observer requires the frozen CP-001 configuration")
        self.instrument = instrument
        self.include_untriggered = include_untriggered
        self._next = 0
        self._last_time = None
        self._ranges = deque(maxlen=self.config.displacement_lookback)
        self._mss = {"bullish": None, "bearish": None}
        self._displacement = {"bullish": None, "bearish": None}

    def observe(self, candle, snapshot, selection=Selection()):
        i = snapshot.execution_index
        timestamp = utc_timestamp(snapshot.execution_timestamp)
        if i != self._next or (self._last_time is not None and snapshot.execution_timestamp <= self._last_time):
            raise ValueError("consume every completed candle once, in order, from index zero")
        if not all(isfinite(x) for x in (candle.open, candle.high, candle.low, candle.close)):
            raise ValueError("finite OHLC required")
        if candle.low > min(candle.open, candle.close) or candle.high < max(candle.open, candle.close):
            raise ValueError("invalid OHLC")
        if snapshot.alignment is not None:
            htime = snapshot.alignment.higher_timeframe_timestamp
            if htime is not None and htime > snapshot.execution_timestamp:
                raise ValueError("future H4 context")
        htf = snapshot.htf_context
        if htf.most_recent_event is not None and (htf.completed_index is None or htf.most_recent_event.index > htf.completed_index):
            raise ValueError("future H4 structural event")
        for swing in (snapshot.structural_state.protected_high, snapshot.structural_state.protected_low):
            if swing is not None and (swing.index > i or swing.confirmed_at is None or swing.confirmed_at > i):
                raise ValueError("unconfirmed protected swing")
        for ref in (selection.bullish_liquidity, selection.bearish_liquidity):
            if ref is not None and not 0 <= ref.index <= i:
                raise ValueError("future liquidity reference")
        for ref in (selection.bullish_pd, selection.bearish_pd):
            if ref is not None and not 0 <= ref.source_index <= ref.index <= i:
                raise ValueError("future PD reference")
        trigger, direction = direction_trigger(snapshot)
        evidence = {e.name: e for e in snapshot.evidence}
        liq, pd = selection.liquidity, selection.pd
        pd_index = None if pd is None else (pd.index if selection.pd_type == "IFVG" else pd.created_at)
        if direction is not None:
            if any(g not in evidence for g in GATES):
                raise ValueError("missing frozen evidence")
            if (liq is not None) != evidence["liquidity event"].passed or (pd is not None) != evidence["PD array"].passed:
                raise ValueError("selection does not match frozen evidence")
            if liq is not None and (liq.index != evidence["liquidity event"].index or liq.pool_id != evidence["liquidity event"].source_id or liq.direction != direction or liq.index > i):
                raise ValueError("liquidity reference mismatch")
            if pd is not None and (pd_index != evidence["PD array"].index or pd.direction != direction or pd_index > i):
                raise ValueError("PD reference mismatch")
        bos = tuple(event_ref(e) for e in snapshot.structure_events if e.kind == "BOS")
        mss = tuple(event_ref(e) for e in snapshot.structure_events if e.kind == "MSS")
        for event in bos + mss:
            if event.index != i:
                raise ValueError("non-current structural event")
        for event in mss:
            self._mss[event.direction] = event
        disp = snapshot.displacement
        if disp is not None:
            if disp.index != i:
                raise ValueError("non-current displacement")
            self._displacement[disp.direction] = i
        prior = [r for r in self._ranges if r > 0]
        reference = sum(prior) / len(prior) if len(self._ranges) == self._ranges.maxlen and prior else None
        candle_range = candle.high - candle.low
        self._ranges.append(candle_range)
        self._next += 1
        self._last_time = snapshot.execution_timestamp
        if direction is None and not self.include_untriggered:
            return None
        # Untriggered rows describe state, not a counterfactual direction.
        passes = tuple(evidence[g].passed for g in GATES) if direction else ()
        missing = tuple(g for g, passed in zip(GATES, passes) if not passed)
        accepted = bool(direction) and all(passes)
        if accepted != (snapshot.signal is not None):
            raise ValueError("frozen acceptance mismatch")
        rng = snapshot.dealing_range
        lo, hi = (rng.low, rng.high) if rng else (None, None)
        midpoint = rng.equilibrium if rng else None
        normalized = (candle.close - lo) / (hi - lo) if rng else None
        if normalized is not None and not isfinite(normalized):
            normalized = None
        stop, risk, reason = structural_levels(candle, snapshot, direction)
        state, htf = snapshot.structural_state, snapshot.htf_context
        matching_mss = self._mss.get(direction)
        matching_disp = self._displacement.get(direction)
        htime = snapshot.alignment.higher_timeframe_timestamp if snapshot.alignment else None
        return ObservationRecord(
            SCHEMA_VERSION, self.instrument, timestamp, i, trigger, direction,
            candle.open, candle.high, candle.low, candle.close, lo, hi, midpoint,
            normalized, snapshot.price_zone, htf.completed_index is not None,
            htf.completed_index, utc_timestamp(htime) if htime else None,
            htf.bias, event_ref(htf.most_recent_event), snapshot.execution_bias,
            swing_ref(state.protected_high), swing_ref(state.protected_low), bos, mss,
            self._mss["bullish"], self._mss["bearish"],
            i - matching_mss.index if matching_mss else None,
            liq is not None, liq.pool_id if liq else None, liq.side if liq else None,
            liq.event_type if liq else None, liq.state if liq else None,
            selection.liquidity_structure,
            liq.source_indices[0] if liq and liq.source_indices else None,
            liq.confirmation_index if liq else None,
            liq.level if liq else None, liq.index if liq else None,
            liq.penetration_index if liq else None, i - liq.index if liq else None,
            selection.bullish_liquidity, selection.bearish_liquidity,
            disp is not None, disp.direction if disp else None, candle_range,
            abs(candle.close - candle.open) / candle_range if candle_range > 0 else None,
            reference, reference * self.config.displacement_range_multiple if reference is not None else None,
            self.config.displacement_body_ratio, self._displacement["bullish"],
            self._displacement["bearish"], i - matching_disp if matching_disp is not None else None,
            selection.pd_type, pd.direction if pd else None, pd.lower if pd else None,
            pd.upper if pd else None, pd_index,
            (pd.source_index if selection.pd_type == "IFVG" else pd.created_at) if pd else None,
            i - pd_index if pd else None,
            ("inverted" if selection.pd_type == "IFVG" else pd.state) if pd else None,
            pd_index == i if pd else None, selection.bullish_pd, selection.bearish_pd,
            passes, sum(passes), len(GATES),
            missing[0] if missing else None, missing, accepted,
            candle.close, stop, risk, reason is None, reason)


def cohort(records, *, gates_passed=None, trigger=None, missing_exactly=None,
           current_mss=False, current_displacement=False, accepted=None):
    """Descriptive filter only; never produces an entry rule or signal."""
    for row in records:
        if row.selected_direction is None:
            continue
        if gates_passed is not None and row.gates_passed != gates_passed:
            continue
        if trigger is not None and row.direction_trigger != trigger:
            continue
        if missing_exactly is not None and set(row.missing_gates) != set(missing_exactly):
            continue
        if current_mss and not row.current_mss:
            continue
        if current_displacement and not row.current_displacement:
            continue
        if accepted is not None and row.accepted_by_cp001_v1 != accepted:
            continue
        yield row
