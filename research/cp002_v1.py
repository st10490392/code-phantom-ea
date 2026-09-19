"""Strict CP-002 semantic closure: completed bars, no I/O or future labels.

ResearchEngine is the S/A streaming primitive adapter. StrictCore also exposes
F mechanics for synthetic verification; a production F scheduler is not enabled.
The earlier cp002 fixture reducer is intentionally a different specification.
"""
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from math import isfinite
from types import MappingProxyType

from research.cp002 import H4Context, Stamp, identity
from strategy.fvg import Displacement, detect_displacement
from strategy.optimized_engine import _IncrementalStructure
from strategy.structure import Candle, StructureShift, StructureState, SwingPoint


MINUTES = {"M15": 15, "M5": 5, "H4": 240}
TERMINAL = frozenset({"ENTERED", "UNLABELABLE", "DATA_COVERAGE_FAILURE",
    "CANCELLED_OPPOSITE_MSS", "STRUCTURALLY_INVALIDATED", "NO_ASSOCIATED_FVG",
    "DISPLACEMENT_MISSING", "UNFILLABLE_GAP_THROUGH", "AMBIGUOUS_CONTACT_INVALIDATION"})


@dataclass(frozen=True)
class Config:
    instrument: str
    dataset_id: str
    branch: str = "STRUCTURAL_REVERSAL"
    entry_model: str = "A"
    displacement_model: str = "S"
    sweep_model: str = "SAME_CANDLE_SWEEP"

    def __post_init__(self):
        if not self.instrument or not self.dataset_id:
            raise ValueError("instrument and dataset namespace required")
        if self.branch not in ("STRUCTURAL_REVERSAL", "SWEEP_REVERSAL"):
            raise ValueError("unknown branch")
        if self.entry_model not in ("A", "F"):
            raise ValueError("only A or M5-confirmed F")
        if self.displacement_model != "S":
            raise ValueError("D20: W remains unfrozen")
        if self.sweep_model != "SAME_CANDLE_SWEEP":
            raise ValueError("delayed reclaim is deferred; no window is frozen")

    @property
    def id(self):
        return identity("CP-002/semantic-closure-v1", self)

    def require_runnable(self):
        if self.entry_model == "F":
            raise ValueError("F fail-closed: joint M15/M5 production coverage scheduler not implemented")
        return self.id


@dataclass(frozen=True)
class Coverage:
    """Attestation for exactly the gap before a real bar; never inferred."""
    start: object
    end: object
    kind: str
    reference: str


@dataclass(frozen=True)
class Bar:
    stamp: Stamp
    candle: Candle
    gap_before: Coverage | None = None
    complete: bool = True

    @property
    def start(self):
        return self.stamp.time - timedelta(minutes=MINUTES[self.stamp.timeframe])


def validate_bar(bar):
    if type(bar) is not Bar or type(bar.stamp) is not Stamp or type(bar.candle) is not Candle:
        raise TypeError("typed causal Bar required; labels are not inputs")
    c = bar.candle
    if not all(isfinite(p) for p in (c.open, c.high, c.low, c.close)):
        raise ValueError("finite OHLC required")
    if c.low > min(c.open, c.close) or c.high < max(c.open, c.close):
        raise ValueError("invalid OHLC")
    if type(bar.complete) is not bool:
        raise ValueError("explicit bar coverage required")
    gap = bar.gap_before
    if gap is not None:
        if (type(gap) is not Coverage or gap.kind not in ("MARKET_CLOSED", "MISSING")
                or not gap.reference or gap.start.tzinfo is None or gap.end.tzinfo is None
                or gap.start >= gap.end):
            raise ValueError("invalid gap attestation")


def coverage_ok(previous, bar):
    validate_bar(bar)
    if not bar.complete:
        return False
    if previous is None:
        return bar.stamp.index == 0 and bar.gap_before is None
    if (bar.stamp.index != previous.stamp.index + 1
            or bar.start < previous.stamp.time):
        return False
    if bar.start == previous.stamp.time:
        if bar.gap_before is not None:
            raise ValueError("gap attestation without a gap")
        return True
    gap = bar.gap_before
    return (gap is not None and gap.kind == "MARKET_CLOSED"
            and gap.start == previous.stamp.time and gap.end == bar.start)


@dataclass(frozen=True)
class Level:
    id: str
    group_id: str
    side: str
    price: float
    source_indices: tuple[int, ...]
    confirmed_at: int
    structure: str


@dataclass(frozen=True)
class LiquidityObservation:
    id: str
    level: Level
    stamp: Stamp
    kind: str
    direction: str | None


@dataclass(frozen=True)
class Frame:
    bar: Bar
    structure: StructureState
    shifts: tuple[StructureShift, ...] = ()
    displacement: Displacement | None = None
    new_levels: tuple[Level, ...] = ()
    h4: H4Context | None = None


@dataclass(frozen=True)
class FVG:
    id: str
    c1: Stamp
    c2: Stamp
    c3: Stamp
    direction: str
    lower: float
    upper: float


@dataclass(frozen=True)
class Path:
    id: str
    branch: str
    mss_id: str
    mss: StructureShift
    created: Stamp
    liquidity: LiquidityObservation | None
    h4: H4Context | None
    htf_relationship: str
    protection: SwingPoint | None
    displacement_id: str | None
    state: str
    fvg: FVG | None = None
    contact: Stamp | None = None
    interaction_start: object | None = None
    confirmation: Stamp | None = None
    confirmation_id: str | None = None
    confirmation_event: StructureShift | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Transition:
    id: str
    path_id: str
    stamp: Stamp
    before: str | None
    after: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Lifecycle:
    id: str
    fvg_id: str
    stamp: Stamp
    facts: tuple[str, ...]


@dataclass(frozen=True)
class Entry:
    id: str
    experiment_id: str
    path: Path
    model: str
    interaction_start: object
    interaction_end: object
    candidate_available_at: object
    reference_fill: float
    stop: float
    stop_anchor: SwingPoint
    stop_snapshot: Stamp
    risk: float
    target: float


def strict_fvg(c1, c2, c3, direction, namespace):
    if (c2.stamp.index != c1.stamp.index + 1 or c3.stamp.index != c2.stamp.index + 1
            or any(b.stamp.timeframe != "M15" for b in (c1, c2, c3))):
        raise ValueError("adjacent completed M15 triplet required")
    if direction == "bullish" and c3.candle.low > c1.candle.high:
        low, high = c1.candle.high, c3.candle.low
    elif direction == "bearish" and c3.candle.high < c1.candle.low:
        low, high = c3.candle.high, c1.candle.low
    else:
        return None
    return FVG(identity(namespace, "FVG", c1.stamp, c2.stamp, c3.stamp, low, high),
               c1.stamp, c2.stamp, c3.stamp, direction, low, high)


def gap_facts(fvg, candle):
    overlap = candle.low <= fvg.upper and candle.high >= fvg.lower
    facts = []
    if overlap:
        facts.append("CONTACTED")
        facts.append("FULLY_TRAVERSED" if candle.low <= fvg.lower and candle.high >= fvg.upper
                     else "PARTIALLY_INTERACTED")
    if candle.close < fvg.lower if fvg.direction == "bullish" else candle.close > fvg.upper:
        facts.append("CLOSE_THROUGH")
    return tuple(facts)


def reference_fill(fvg, candle):
    if not candle.low <= fvg.upper or not candle.high >= fvg.lower:
        return None
    if fvg.lower <= candle.open <= fvg.upper:
        return candle.open
    if fvg.direction == "bullish" and candle.open > fvg.upper:
        return fvg.upper
    if fvg.direction == "bearish" and candle.open < fvg.lower:
        return fvg.lower
    return None  # no approved expected-side reference; do not guess


class StrictCore:
    """Consumes fully completed evidence frames. No synthetic validity override.

    Production users must use ResearchEngine's raw-bar primitive adapter.
    F evidence-frame mechanics are available only with explicit synthetic=True.
    """
    def __init__(self, config, *, synthetic=False):
        if type(config) is not Config:
            raise TypeError("strict Config required")
        if not synthetic:
            config.require_runnable()
        self._config = config
        self._paths = {}
        self._active = set()
        self._levels = {}
        self._broken_levels = set()
        self._sweeps = {}
        self._consumed = set()
        self._liquidity = []
        self._transitions = []
        self._lifecycle = {}
        self._entries = []
        self._bars = []  # only the current triplet
        self._last = {}
        self._seen = {}
        self._level_ids = {}
        self._order = None
        self._h4 = None
        self._m15_state = None
        self._failed = set()
        self._m5_covered = set()

    @property
    def config(self): return self._config
    @property
    def paths(self): return MappingProxyType(dict(self._paths))
    @property
    def transitions(self): return tuple(self._transitions)
    @property
    def entries(self): return tuple(self._entries)
    @property
    def lifecycle(self): return tuple(self._lifecycle.values())
    @property
    def liquidity(self): return tuple(self._liquidity)

    def _set(self, path, state, stamp, *reasons, **changes):
        if path.state in TERMINAL:
            return path
        transition = Transition(identity(path.id, stamp, state, reasons), path.id,
                                stamp, path.state, state, tuple(reasons))
        self._transitions.append(transition)
        path = replace(path, state=state, reason=reasons[0] if reasons else None, **changes)
        self._paths[path.id] = path
        if state in TERMINAL:
            self._active.discard(path.id)
        return path

    def _validate(self, frame):
        if type(frame) is not Frame:
            raise TypeError("typed causal Frame required; no future labels")
        bar = frame.bar
        validate_bar(bar)
        tf = bar.stamp.timeframe
        if tf not in ("M15", "M5") or (tf == "M5" and self.config.entry_model != "F"):
            raise ValueError("unsupported stream")
        key = (tf, bar.stamp.index)
        digest = identity(frame)
        if key in self._seen:
            if self._seen[key] != digest: raise ValueError("conflicting replay")
            return key, digest, True
        if type(frame.structure) is not StructureState or frame.structure.as_of_index != bar.stamp.index:
            raise ValueError("current structural snapshot required")
        if type(frame.shifts) is not tuple or type(frame.new_levels) is not tuple:
            raise TypeError("immutable evidence tuples required")
        for shift in frame.shifts:
            if (type(shift) is not StructureShift or shift.index != bar.stamp.index
                    or shift.kind != "MSS" or shift.direction not in ("bullish", "bearish")
                    or shift.previous_state not in ("bullish", "bearish")
                    or shift.previous_state == shift.direction
                    or shift.broken_side != ("high" if shift.direction == "bullish" else "low")
                    or shift.broken_swing_index is None
                    or not 0 <= shift.broken_swing_index < bar.stamp.index):
                raise ValueError("causal opposing-BOS MSS proxy required")
        for anchor in (frame.structure.protected_high, frame.structure.protected_low):
            if anchor is not None and (type(anchor) is not SwingPoint or anchor.confirmed_at is None
                    or anchor.confirmed_at > bar.stamp.index or not 0 <= anchor.index < bar.stamp.index):
                raise ValueError("future or unavailable protected reference")
        if frame.displacement is not None and (
                type(frame.displacement) is not Displacement or frame.displacement.index != bar.stamp.index
                or frame.displacement.direction not in ("bullish", "bearish")):
            raise ValueError("current displacement required")
        if tf == "M5" and (frame.new_levels or frame.displacement or frame.h4):
            raise ValueError("M5 frame carries confirmation only")
        for level in frame.new_levels:
            if (type(level) is not Level or not level.id or not level.group_id
                    or not isfinite(level.price) or level.side not in ("high", "low")
                    or type(level.source_indices) is not tuple or not level.source_indices
                    or not max(level.source_indices) < level.confirmed_at <= bar.stamp.index
                    or min(level.source_indices) < 0 or level.structure not in ("internal", "external")):
                raise ValueError("confirmed immutable structural liquidity required")
            if level.id in self._level_ids and self._level_ids[level.id] != level:
                raise ValueError("liquidity generation identity changed")
        if frame.h4 is not None:
            h = frame.h4
            if (type(h) is not H4Context or h.stamp.timeframe != "H4"
                    or h.stamp.time > bar.stamp.time or h.bias not in ("bullish", "bearish", "neutral")):
                raise ValueError("unavailable H4")
            if self._h4 and h != self._h4 and h.stamp.time <= self._h4.stamp.time:
                raise ValueError("regressing H4")
        order = (bar.stamp.time, 0 if tf == "M15" else 1)
        if self._order is not None and order <= self._order:
            raise ValueError("completion order must be M15 then M5 at equality")
        return key, digest, False

    def advance(self, frame):
        key, digest, replay = self._validate(frame)
        if replay: return ()
        bar = frame.bar
        tf = bar.stamp.timeframe
        valid = coverage_ok(self._last.get(tf), bar)
        before = len(self._transitions)
        self._seen[key] = digest
        self._order = (bar.stamp.time, 0 if tf == "M15" else 1)
        self._last[tf] = bar
        if not valid or tf in self._failed:
            self._failed.add(tf)
            for pid in sorted(self._active):
                p = self._paths[pid]
                if tf == "M15" or p.state == "M5_CONFIRMATION_ARMED":
                    self._set(p, "DATA_COVERAGE_FAILURE", bar.stamp, "required_transition_unobservable")
            return tuple(self._transitions[before:])
        if tf == "M15":
            self._m15_state = (frame.structure, bar.stamp)
            if frame.h4 is not None: self._h4 = frame.h4
            self._bars.append(bar)
            self._bars = self._bars[-3:]
            self._observe_liquidity(frame)
            self._advance_paths(frame)
            self._new_paths(frame)
        else:
            self._confirm(frame)
        return tuple(self._transitions[before:])

    def _observe_liquidity(self, frame):
        bar = frame.bar
        c = bar.candle
        for level in frame.new_levels:
            self._levels[level.group_id] = level
            self._level_ids[level.id] = level
        for level in sorted(self._levels.values(), key=lambda x: x.id):
            if level.id in self._broken_levels: continue
            bullish = level.side == "low"
            extreme = c.low if bullish else c.high
            through = extreme < level.price if bullish else extreme > level.price
            back = c.close > level.price if bullish else c.close < level.price
            beyond = c.close < level.price if bullish else c.close > level.price
            if through and back:
                kind = "SAME_CANDLE_SWEEP"
            elif through and beyond:
                kind = "BREAK_PENDING"  # no timeout/reclaim/acceptance window invented
            elif extreme == level.price or (through and c.close == level.price):
                kind = "TOUCH"
            else:
                continue
            event = LiquidityObservation(identity(self.config.id, level.id, bar.stamp, kind),
                                         level, bar.stamp, kind,
                                         ("bullish" if bullish else "bearish") if kind == "SAME_CANDLE_SWEEP" else None)
            self._liquidity.append(event)
            if kind != "TOUCH":
                self._broken_levels.add(level.id)
                self._levels.pop(level.group_id)
            if kind == "SAME_CANDLE_SWEEP": self._sweeps[event.id] = event

    def _new_paths(self, frame):
        bar = frame.bar
        for shift in sorted(frame.shifts, key=lambda x: (x.direction, x.broken_swing_index)):
            mss_id = identity(self.config.id, bar.stamp, shift)
            parents = [None] if self.config.branch == "STRUCTURAL_REVERSAL" else [
                s for s in self._sweeps.values() if s.id not in self._consumed
                and s.direction == shift.direction and s.stamp.time <= bar.stamp.time]
            for parent in sorted(parents, key=lambda x: x.id if x else ""):
                if parent:
                    self._consumed.add(parent.id)
                    self._sweeps.pop(parent.id)
                protection = (frame.structure.protected_low if shift.direction == "bullish"
                              else frame.structure.protected_high)
                disp = frame.displacement
                disp_id = identity(self.config.id, "displacement", bar.stamp, disp) if (
                    disp is not None and disp.direction == shift.direction) else None
                h = self._h4
                relation = ("HTF_UNAVAILABLE" if h is None else "HTF_NEUTRAL" if h.bias == "neutral"
                            else "HTF_ALIGNED" if h.bias == shift.direction else "COUNTER_HTF")
                pid = identity(self.config.id, mss_id, parent.id if parent else None)
                p = Path(pid, self.config.branch, mss_id, shift, bar.stamp, parent, h,
                         relation, protection, disp_id, "MSS_CONFIRMED")
                self._paths[pid] = p
                self._active.add(pid)
                self._transitions.append(Transition(identity(pid, "created"), pid, bar.stamp,
                                                    None, "MSS_CONFIRMED", ("new_generation",)))
                bad = self._anchor_reason(protection, shift.direction, bar.candle.close)
                if bad: self._set(p, "UNLABELABLE", bar.stamp, "mss_protection:" + bad)
                elif disp_id is None: self._set(p, "DISPLACEMENT_MISSING", bar.stamp, "S_requires_same_candle")
                elif len(self._bars) < 2: self._set(p, "NO_ASSOCIATED_FVG", bar.stamp, "C1_unavailable")
                else: self._set(p, "WAITING_FOR_C3", bar.stamp, "C2_displacement_latched")

    @staticmethod
    def _anchor_reason(anchor, direction, price):
        if anchor is None: return "missing_protected_swing"
        if not isfinite(anchor.price): return "non_finite_anchor"
        if anchor.kind != ("low" if direction == "bullish" else "high"): return "wrong_anchor_kind"
        if anchor.price == price: return "zero_risk"
        if (direction == "bullish" and anchor.price > price) or (direction == "bearish" and anchor.price < price):
            return "directionally_invalid_anchor"
        return None

    def _facts(self, fvg, stamp, facts):
        key = identity(fvg.id, stamp, facts)
        self._lifecycle[key] = Lifecycle(key, fvg.id, stamp, facts)

    def _advance_paths(self, frame):
        bar, c = frame.bar, frame.bar.candle
        for pid in sorted(self._active):
            p = self._paths[pid]
            bullish = p.mss.direction == "bullish"
            breached = c.low <= p.protection.price if bullish else c.high >= p.protection.price
            opposite = any(s.direction != p.mss.direction for s in frame.shifts)
            facts = gap_facts(p.fvg, c) if p.fvg else ()
            contact = p.state == "WAITING_FOR_RETRACEMENT" and "CONTACTED" in facts
            if facts: self._facts(p.fvg, bar.stamp, facts)
            if contact and breached:
                reasons = ("AMBIGUOUS_CONTACT_INVALIDATION",) + (("CANCELLED_OPPOSITE_MSS",) if opposite else ())
                self._set(p, "AMBIGUOUS_CONTACT_INVALIDATION", bar.stamp, *reasons,
                          contact=bar.stamp, interaction_start=bar.start)
                continue
            if breached or opposite:
                reasons = tuple(x for x, yes in (("STRUCTURALLY_INVALIDATED", breached),
                                                ("CANCELLED_OPPOSITE_MSS", opposite)) if yes)
                self._set(p, reasons[0], bar.stamp, *reasons)
                continue
            if p.state == "WAITING_FOR_C3":
                if len(self._bars) != 3 or self._bars[1].stamp != p.created:
                    self._set(p, "NO_ASSOCIATED_FVG", bar.stamp, "strict_C2_ownership_failed")
                    continue
                fvg = strict_fvg(*self._bars, p.mss.direction, self.config.id)
                if fvg is None:
                    self._set(p, "NO_ASSOCIATED_FVG", bar.stamp, "strict_triplet_has_no_gap")
                else:
                    self._facts(fvg, bar.stamp, ("CREATED", "AVAILABLE", "UNTOUCHED"))
                    self._set(p, "WAITING_FOR_RETRACEMENT", bar.stamp, "C3_available_no_entry", fvg=fvg)
                continue
            if p.state == "M5_CONFIRMATION_ARMED":
                last_m5 = self._last.get("M5")
                # At equal completion M15 precedes M5; allow that one pending M5 bar.
                if ("M5" in self._failed or last_m5 is None
                        or last_m5.stamp.time < bar.stamp.time - timedelta(minutes=5)):
                    self._set(p, "DATA_COVERAGE_FAILURE", bar.stamp, "M5_coverage_after_arming_unavailable")
                continue
            if p.state != "WAITING_FOR_RETRACEMENT": continue
            far_gap = c.high < p.fvg.lower if bullish else c.low > p.fvg.upper
            if far_gap:
                self._set(p, "UNFILLABLE_GAP_THROUGH", bar.stamp, "no_observable_zone_overlap")
            elif contact:
                p = self._set(p, "CONTACTED", bar.stamp, "first_later_range_interaction",
                              contact=bar.stamp, interaction_start=bar.start)
                if self.config.entry_model == "F":
                    if "M5" in self._failed:
                        self._set(p, "DATA_COVERAGE_FAILURE", bar.stamp, "M5_stream_unreliable")
                    else:
                        self._set(p, "M5_CONFIRMATION_ARMED", bar.stamp, "await_subsequent_M5_MSS")
                else:
                    fill = reference_fill(p.fvg, c)
                    if fill is None: self._set(p, "UNLABELABLE", bar.stamp, "unsupported_reference_fill_approach")
                    else: self._enter(p, fill, bar.stamp)

    def _confirm(self, frame):
        bar = frame.bar
        for pid in sorted(self._active):
            p = self._paths[pid]
            if p.state != "M5_CONFIRMATION_ARMED" or bar.stamp.time <= p.contact.time: continue
            if bar.start < p.contact.time:
                self._set(p, "DATA_COVERAGE_FAILURE", bar.stamp, "partial_arming_interval")
                continue
            # The first post-contact bar must begin at arming, unless an observed
            # preceding M5 bar or exact closure attestation establishes coverage.
            if p.id not in self._m5_covered:
                gap = bar.gap_before
                if bar.start > p.contact.time and not (gap and gap.kind == "MARKET_CLOSED"
                        and gap.start <= p.contact.time and gap.end == bar.start):
                    self._set(p, "DATA_COVERAGE_FAILURE", bar.stamp, "unobserved_M5_since_contact")
                    continue
            breached = (bar.candle.low <= p.protection.price if p.mss.direction == "bullish"
                        else bar.candle.high >= p.protection.price)
            if breached:
                self._set(p, "STRUCTURALLY_INVALIDATED", bar.stamp, "observed_M5_protection_breach")
                continue
            self._transitions.append(Transition(identity(p.id, bar.stamp, "M5_coverage"), p.id,
                bar.stamp, p.state, "M5_COVERAGE_OBSERVED", ("complete_post_contact_interval",)))
            self._m5_covered.add(p.id)
            matching = next((s for s in frame.shifts if s.direction == p.mss.direction), None)
            if matching:
                p = replace(p, confirmation=bar.stamp,
                            confirmation_id=identity(self.config.id, "M5_MSS", bar.stamp, matching),
                            confirmation_event=matching)
                self._paths[p.id] = p
                self._enter(p, bar.candle.close, bar.stamp)

    def _enter(self, p, fill, stamp):
        state, snapshot = self._m15_state
        anchor = state.protected_low if p.mss.direction == "bullish" else state.protected_high
        reason = self._anchor_reason(anchor, p.mss.direction, fill)
        if reason:
            self._set(p, "UNLABELABLE", stamp, "entry_stop:" + reason)
            return
        risk = abs(fill - anchor.price)
        target = fill + (2*risk if p.mss.direction == "bullish" else -2*risk)
        if not isfinite(target) or not isfinite(risk):
            self._set(p, "UNLABELABLE", stamp, "non_finite_risk_geometry")
            return
        entered = self._set(p, "ENTERED", stamp, "research_reference_only")
        self._entries.append(Entry(identity(p.id, "entry"), self.config.id, entered,
            self.config.entry_model, p.interaction_start, p.contact.time, stamp.time,
            fill, anchor.price, anchor, snapshot, risk, target))


class ResearchEngine:
    """S/A incremental completed-M15 adapter. No loader or historical runner.

    Reuses the unchanged opposing-BOS detector and fixed-size displacement
    lookback. Price-equality liquidity grouping matches inherited tolerance 0.
    All histories are explicit in-memory state; no hidden capacity eviction.
    """
    def __init__(self, config):
        config.require_runnable()
        self.core = StrictCore(config)
        self._structure = _IncrementalStructure(2)
        self._candles = []
        self._last = None
        self._seen = {}
        self._groups = {}
        self._counts = {"high": 0, "low": 0}
        self._failed = False

    def advance(self, bar, *, h4=None):
        validate_bar(bar)
        if bar.stamp.timeframe != "M15": raise ValueError("M15 adapter only")
        key, digest = bar.stamp.index, identity(bar, h4)
        if key in self._seen:
            if self._seen[key] != digest: raise ValueError("conflicting replay")
            return ()
        if self._last and bar.stamp.time <= self._last.stamp.time:
            raise ValueError("non-increasing completion")
        if h4 is not None and (type(h4) is not H4Context or h4.stamp.time > bar.stamp.time
                              or h4.stamp.timeframe != "H4" or h4.bias not in ("bullish", "bearish", "neutral")):
            raise ValueError("unavailable H4")
        old_h4 = self.core._h4
        if h4 and old_h4 and h4 != old_h4 and h4.stamp.time <= old_h4.stamp.time:
            raise ValueError("regressing H4")
        valid = coverage_ok(self._last, bar)
        if self._failed or not valid:
            self._failed = True
            result = self.core.advance(Frame(replace(bar, complete=False), StructureState(key)))
        else:
            self._candles.append(bar.candle)
            state, events = self._structure.advance(self._candles, key)
            levels = []
            for side, swings in (("high", self._structure.highs), ("low", self._structure.lows)):
                for swing in swings[self._counts[side]:]:
                    group_key = (side, Decimal(str(swing.price)))
                    group = self._groups.setdefault(group_key, [])
                    group.append(swing)
                    members = tuple(s.index for s in group)
                    group_id = identity(self.core.config.id, side, str(group_key[1]))
                    levels.append(Level(identity(group_id, members, swing.confirmed_at), group_id,
                        side, sum(s.price for s in group)/len(group), members,
                        max(s.confirmed_at for s in group),
                        "external" if any(s.structure == "external" for s in group) else "internal"))
                self._counts[side] = len(swings)
            disp = detect_displacement(self._candles[-6:]) if key >= 5 else []
            displacement = replace(disp[-1], index=key) if disp else None
            result = self.core.advance(Frame(bar, state,
                tuple(e for e in events if type(e) is StructureShift), displacement, tuple(levels), h4))
        self._last = bar
        self._seen[key] = digest
        return result
