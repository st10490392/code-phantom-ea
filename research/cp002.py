"""CP-002 synthetic temporal core. No data loader, runner or outcome labeler.

Unresolved market semantics are not defaults. SyntheticContract certifies only
fixture-local association/validity inputs; it cannot authorize a campaign.
Existing strategy detectors and Observer V1 are deliberately left unchanged.
"""
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite
from types import MappingProxyType

from strategy.fvg import Displacement
from strategy.imbalance import Gap
from strategy.liquidity_v2 import LiquidityEvent
from strategy.structure import Candle, StructureShift, StructureState, SwingPoint


OPEN_DECISIONS = (
    "D03", "D10", "D15", "D16", "D20", "D25", "D27", "D28",
    "D40", "D42", "D43", "D44", "D45", "D51", "D55", "D56",
)
TERMINAL = frozenset({
    "ENTERED", "STRUCTURALLY_INVALIDATED", "FVG_INVALIDATED",
    "DATA_COVERAGE_FAILURE", "UNLABELABLE", "PREREQUISITE_FAILED",
})
DIRECTIONS = ("bullish", "bearish")


def _canonical(value):
    if hasattr(value, "__dataclass_fields__"):
        return _canonical(asdict(value))
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    # Preserve invalid risk evidence deterministically, without nonstandard JSON.
    if isinstance(value, float) and not isfinite(value):
        return {"nonfinite_risk_value": repr(value)}
    return value


def identity(*values):
    payload = json.dumps(_canonical(values), sort_keys=True, separators=(",", ":"),
                         allow_nan=False)
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Stamp:
    index: int
    time: datetime
    timeframe: str = "M15"

    def __post_init__(self):
        if type(self.index) is not int or self.index < 0:
            raise ValueError("nonnegative integer index required")
        if self.time.tzinfo is None or self.time.utcoffset() is None:
            raise ValueError("aware completion time required")
        if self.timeframe not in ("M15", "M5", "H4"):
            raise ValueError("unsupported timeframe; M1 refinement is deferred")
        object.__setattr__(self, "time", self.time.astimezone(timezone.utc))


@dataclass(frozen=True)
class Experiment:
    name: str
    instrument: str
    source_id: str
    branch: str = "STRUCTURAL_REVERSAL"
    entry_model: str = "A"
    displacement_model: str = "S"
    fixture_window: int | None = None

    def __post_init__(self):
        if not all((self.name, self.instrument, self.source_id)):
            raise ValueError("experiment, instrument and source identity required")
        if self.branch not in ("STRUCTURAL_REVERSAL", "SWEEP_REVERSAL"):
            raise ValueError("unsupported branch")
        if self.entry_model not in ("A", "F"):
            raise ValueError("unsupported entry model")
        if self.displacement_model not in ("S", "W"):
            raise ValueError("unsupported displacement model")
        if self.fixture_window is not None:
            if type(self.fixture_window) is not int or self.fixture_window < 1:
                raise ValueError("fixture window must be a positive integer")
            if self.displacement_model != "W":
                raise ValueError("fixture window is only meaningful for W")

    @property
    def id(self):
        return identity("CP-002/Freeze-V1", self)

    def require_runnable(self):
        """No runner exists: even a fixture W cannot become an approved W."""
        if self.displacement_model == "W":
            raise ValueError("D20: numerical W is not frozen; fixture values cannot authorize a campaign")
        raise ValueError("campaign disabled: unresolved association/invalidation/coverage decisions "
                         "D03/D25/D27/D28/D40/D42/D43/D44/D45; F also D51/D55/D56")


@dataclass(frozen=True)
class SyntheticContract:
    """Explicit fixture assumptions only; never a production rule selection."""
    name: str
    valid_gap_states: tuple[str, ...]

    def __post_init__(self):
        if not self.name.startswith("fixture:"):
            raise ValueError("fixture: contract namespace required")
        if type(self.valid_gap_states) is not tuple or not self.valid_gap_states:
            raise ValueError("explicit immutable fixture validity states required")
        if not set(self.valid_gap_states) <= {"new", "active", "partial", "mitigated"}:
            raise ValueError("invalid fixture gap state")


@dataclass(frozen=True)
class H4Context:
    id: str
    stamp: Stamp
    bias: str


@dataclass(frozen=True)
class Sweep:
    id: str
    stamp: Stamp
    event: LiquidityEvent


@dataclass(frozen=True)
class Shift:
    id: str
    stamp: Stamp
    event: StructureShift
    liquidity_id: str | None = None


@dataclass(frozen=True)
class Impulse:
    id: str
    stamp: Stamp
    event: Displacement


@dataclass(frozen=True)
class Array:
    id: str
    stamp: Stamp
    gap: Gap
    displacement_id: str
    association_contract: str


@dataclass(frozen=True)
class Validity:
    """Current causal lifecycle evidence, with explicit fixture guard authority."""
    fvg_id: str
    contract: str
    status: str  # VALID, STRUCTURALLY_INVALIDATED, FVG_INVALIDATED
    gap_state: str
    reference_id: str


@dataclass(frozen=True)
class M15Frame:
    stamp: Stamp
    candle: Candle
    structure: StructureState
    h4: H4Context | None = None
    sweeps: tuple[Sweep, ...] = ()
    shifts: tuple[Shift, ...] = ()
    impulses: tuple[Impulse, ...] = ()
    arrays: tuple[Array, ...] = ()
    validity: tuple[Validity, ...] = ()
    coverage_complete: bool = True


@dataclass(frozen=True)
class M5Frame:
    stamp: Stamp
    shifts: tuple[Shift, ...] = ()
    validity: tuple[Validity, ...] = ()
    coverage_complete: bool = True


@dataclass(frozen=True)
class Generation:
    id: str
    branch: str
    mss: Shift
    liquidity: Sweep | None
    h4: H4Context | None
    htf_relationship: str
    state: str = "FORMING"
    displacement: Impulse | None = None


@dataclass(frozen=True)
class Area:
    id: str
    generation_id: str
    fvg: Array
    ready: Stamp
    state: str = "FVG_AVAILABLE"
    contact: Stamp | None = None
    confirmation: Shift | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Transition:
    id: str
    subject_id: str
    event_id: str
    stamp: Stamp
    before: str | None
    after: str
    reason: str
    parents: tuple[str, ...]


@dataclass(frozen=True)
class Entry:
    id: str
    experiment_id: str
    area_id: str
    generation_id: str
    branch: str
    direction: str
    entry_model: str
    stamp: Stamp
    price: float
    stop: float
    stop_reference: SwingPoint
    stop_snapshot: Stamp
    risk: float
    objective: float
    contact: Stamp
    parent_ids: tuple[str, ...]
    horizon_subsequent_m15: int = 96
    same_candle_policy: str = "conservative"


class TemporalCore:
    """Incremental event reducer; accepts causal objects, never files or labels.

    One complete M15/M5 batch per completion; duplicate exact batches are no-ops.
    All mutation is private; returned state/log objects are frozen snapshots.
    Memory is explicitly O(events + generations + areas + log); no hidden cap.
    """
    def __init__(self, experiment: Experiment, *, fixture_contract=None):
        if type(experiment) is not Experiment:
            raise TypeError("Experiment required")
        if fixture_contract is not None and type(fixture_contract) is not SyntheticContract:
            raise TypeError("SyntheticContract required")
        if experiment.displacement_model == "W" and (
                fixture_contract is None or experiment.fixture_window is None):
            raise ValueError("unresolved W; only an explicit fixture-local window may exercise W")
        self._experiment = experiment
        self._contract = fixture_contract
        self._generations = {}
        self._areas = {}
        self._sweeps = {}
        self._waiting = set()
        self._by_displacement = {}
        self._active = set()
        self._transitions = []
        self._entries = []
        self._seen = {}
        self._evidence = {}
        self._last_time = None
        self._m15 = None
        self._m5 = None
        self._h4 = None
        self._failed_coverage = False

    @property
    def experiment(self):
        return self._experiment

    @property
    def contract(self):
        return self._contract

    @property
    def generations(self):
        return MappingProxyType(dict(self._generations))

    @property
    def areas(self):
        return MappingProxyType(dict(self._areas))

    @property
    def transitions(self):
        return tuple(self._transitions)

    @property
    def entries(self):
        return tuple(self._entries)

    def _parents(self, area):
        gen = self._generations[area.generation_id]
        return tuple(x for x in (
            self.experiment.id, gen.id, gen.h4.id if gen.h4 else None,
            gen.liquidity.id if gen.liquidity else None, gen.mss.id,
            gen.displacement.id, area.fvg.id,
        ) if x is not None)

    def _log(self, subject, event, stamp, before, after, reason, parents):
        self._transitions.append(Transition(
            identity(self.experiment.id, subject, event, after), subject,
            event, stamp, before, after, reason, parents))

    def _generation_state(self, gen, state, event, stamp, reason):
        self._log(gen.id, event, stamp, gen.state, state, reason,
                  tuple(x for x in (gen.mss.id, gen.liquidity.id if gen.liquidity else None) if x))
        gen = replace(gen, state=state)
        self._generations[gen.id] = gen
        return gen

    def _area_state(self, area, state, event, stamp, reason, **changes):
        if area.state in TERMINAL:
            return area
        self._log(area.id, event, stamp, area.state, state, reason, self._parents(area))
        area = replace(area, state=state, reason=reason, **changes)
        self._areas[area.id] = area
        if state in TERMINAL:
            self._active.discard(area.id)
        return area

    @staticmethod
    def _shift_check(shift, stamp):
        if type(shift) is not Shift or type(shift.event) is not StructureShift:
            raise TypeError("typed repository MSS evidence required")
        e = shift.event
        if shift.stamp != stamp or e.index != stamp.index:
            raise ValueError("shift must be current at its completion")
        expected_side = "high" if e.direction == "bullish" else "low"
        if (e.kind != "MSS" or e.direction not in DIRECTIONS
                or e.previous_state not in DIRECTIONS or e.previous_state == e.direction
                or e.broken_side != expected_side or e.broken_swing_index is None
                or not 0 <= e.broken_swing_index < e.index or not isfinite(e.broken_level)):
            raise ValueError("repository opposing-BOS MSS proxy evidence required")

    def _validate(self, frame):
        """Preflight the whole batch before changing any state."""
        if type(frame) not in (M15Frame, M5Frame):
            raise TypeError("only typed causal M15Frame/M5Frame accepted; no labels")
        expected = "M15" if type(frame) is M15Frame else "M5"
        if type(frame.stamp) is not Stamp or frame.stamp.timeframe != expected:
            raise ValueError("frame timeframe mismatch")
        if expected == "M5" and self.experiment.entry_model != "F":
            raise ValueError("M5 stream belongs only to F")
        if type(frame.coverage_complete) is not bool:
            raise TypeError("explicit coverage boolean required")
        collections = (frame.shifts, frame.validity)
        if expected == "M15":
            collections += (frame.sweeps, frame.impulses, frame.arrays)
        if any(type(items) is not tuple for items in collections):
            raise TypeError("immutable event tuples required")
        key = (expected, frame.stamp.index)
        digest = identity(frame)
        if key in self._seen:
            if self._seen[key] != digest:
                raise ValueError("conflicting replay batch")
            return key, digest, True, []
        if self._last_time is not None and frame.stamp.time < self._last_time:
            raise ValueError("out-of-order completion")
        if (expected == "M15" and self._m5 is not None
                and self._m5.stamp.time == frame.stamp.time):
            raise ValueError("same-completion M15 batch must precede M5 batch")
        last = self._m15 if expected == "M15" else self._m5
        if last is not None and (frame.stamp.index <= last.stamp.index
                                 or frame.stamp.time <= last.stamp.time):
            raise ValueError("non-increasing stream")
        refs = list(frame.shifts)
        for shift in frame.shifts:
            self._shift_check(shift, frame.stamp)
        for v in frame.validity:
            if type(v) is not Validity or not v.reference_id:
                raise ValueError("typed validity with causal reference required")
            if v.status not in ("VALID", "STRUCTURALLY_INVALIDATED", "FVG_INVALIDATED"):
                raise ValueError("undefined validity status")
            if v.gap_state not in ("new", "active", "partial", "mitigated", "invalidated"):
                raise ValueError("ordinary gap state required")
        if len({v.fvg_id for v in frame.validity}) != len(frame.validity):
            raise ValueError("duplicate area validity evidence")
        if expected == "M15":
            c = frame.candle
            if type(c) is not Candle or not all(isfinite(x) for x in (c.open, c.high, c.low, c.close)):
                raise ValueError("finite completed OHLC required")
            if c.low > min(c.open, c.close) or c.high < max(c.open, c.close):
                raise ValueError("invalid OHLC")
            if type(frame.structure) is not StructureState or frame.structure.as_of_index != frame.stamp.index:
                raise ValueError("current M15 structural snapshot required")
            for swing in (frame.structure.protected_high, frame.structure.protected_low):
                if swing is not None and (type(swing) is not SwingPoint or swing.confirmed_at is None
                                         or swing.confirmed_at > frame.stamp.index
                                         or not 0 <= swing.index < frame.stamp.index):
                    raise ValueError("unavailable protected swing")
            if frame.h4 is not None:
                h = frame.h4
                if (type(h) is not H4Context or h.stamp.timeframe != "H4"
                        or h.stamp.time > frame.stamp.time or h.bias not in (*DIRECTIONS, "neutral")):
                    raise ValueError("unavailable H4 context")
                if self._h4 is not None and h != self._h4 and (
                        h.stamp.time <= self._h4.stamp.time or h.stamp.index <= self._h4.stamp.index):
                    raise ValueError("regressing or conflicting completed H4 context")
                refs.append(h)
            for sweep in frame.sweeps:
                if type(sweep) is not Sweep or type(sweep.event) is not LiquidityEvent:
                    raise TypeError("typed liquidity evidence required")
                if sweep.stamp != frame.stamp or sweep.event.index != frame.stamp.index:
                    raise ValueError("liquidity must be published at confirmation completion")
                if sweep.event.confirmation_index != frame.stamp.index:
                    raise ValueError("liquidity confirmation cannot be backdated")
                if (type(sweep.event.source_indices) is not tuple
                        or not sweep.event.source_indices
                        or any(type(i) is not int or not 0 <= i < frame.stamp.index
                               for i in sweep.event.source_indices)
                        or not all(isfinite(x) for x in (sweep.event.level, sweep.event.close))
                        or sweep.event.penetration_index is None
                        or not 0 <= sweep.event.penetration_index <= frame.stamp.index):
                    raise ValueError("immutable causal liquidity sources required")
            if len(frame.impulses) > 1:
                raise ValueError("one repository displacement per M15 candle")
            for impulse in frame.impulses:
                if (type(impulse) is not Impulse or type(impulse.event) is not Displacement
                        or impulse.stamp != frame.stamp or impulse.event.index != frame.stamp.index
                        or impulse.event.direction not in DIRECTIONS
                        or not all(isfinite(x) and x > 0 for x in
                                   (impulse.event.body, impulse.event.range))
                        or impulse.event.body > impulse.event.range):
                    raise ValueError("current typed displacement required")
            for array in frame.arrays:
                if (type(array) is not Array or type(array.gap) is not Gap
                        or array.stamp != frame.stamp or array.gap.created_at != frame.stamp.index
                        or array.gap.direction not in DIRECTIONS
                        or not all(isfinite(x) for x in (array.gap.lower, array.gap.upper))
                        or any(i is not None and not array.gap.created_at <= i <= frame.stamp.index
                               for i in (array.gap.first_touch, array.gap.invalidated_at))):
                    raise ValueError("current finite ordinary FVG required")
            refs += list(frame.sweeps) + list(frame.impulses) + list(frame.arrays)
        batch = {}
        for ref in refs:
            if not ref.id:
                raise ValueError("nonempty immutable evidence ID required")
            content = identity(ref)
            if ref.id in batch and batch[ref.id] != content:
                raise ValueError("conflicting batch identity")
            if ref.id in self._evidence and self._evidence[ref.id] != content:
                raise ValueError("immutable evidence ID changed")
            batch[ref.id] = content
        if len({s.id for s in frame.shifts}) != len(frame.shifts):
            raise ValueError("duplicate shift in batch")
        if expected == "M15" and len({a.id for a in frame.arrays}) != len(frame.arrays):
            raise ValueError("duplicate FVG in batch")
        return key, digest, False, list(batch.items())

    def advance(self, frame):
        key, digest, replay, refs = self._validate(frame)
        if replay:
            return ()
        start = len(self._transitions)
        last = self._m15 if type(frame) is M15Frame else self._m5
        minutes = 15 if type(frame) is M15Frame else 5
        gap = last is not None and (
            frame.stamp.index != last.stamp.index + 1
            or frame.stamp.time != last.stamp.time + timedelta(minutes=minutes))
        self._seen[key] = digest
        self._evidence.update(refs)
        self._last_time = frame.stamp.time
        if gap or not frame.coverage_complete or self._failed_coverage:
            self._failed_coverage = True
            for aid in sorted(self._active):
                self._area_state(self._areas[aid], "DATA_COVERAGE_FAILURE", digest,
                                 frame.stamp, "noncontiguous_or_incomplete_stream")
            for gid in sorted(self._waiting):
                self._generation_state(self._generations[gid], "DATA_COVERAGE_FAILURE",
                                       digest, frame.stamp, "noncontiguous_or_incomplete_stream")
            self._waiting.clear()
        elif type(frame) is M15Frame:
            self._on_m15(frame, digest)
        else:
            self._on_m5(frame, digest)
        if type(frame) is M15Frame:
            self._m15 = frame
        else:
            self._m5 = frame
        return tuple(self._transitions[start:])

    def _on_m15(self, frame, event_id):
        if frame.h4 is not None:
            self._h4 = frame.h4
        for sweep in frame.sweeps:
            self._sweeps[sweep.id] = sweep
        for shift in sorted(frame.shifts, key=lambda s: s.id):
            parent = None
            if self.experiment.branch == "SWEEP_REVERSAL":
                parent = self._sweeps.get(shift.liquidity_id)
                if parent is None:
                    continue
                liq = parent.event
                side = "sell_side" if shift.event.direction == "bullish" else "buy_side"
                if (liq.event_type not in ("wick_sweep", "reclaim_sweep")
                        or liq.state != ("wick_swept" if liq.event_type == "wick_sweep" else "reclaimed")
                        or liq.pool_state != "consumed" or liq.direction != shift.event.direction
                        or liq.side != side or parent.stamp.time > shift.stamp.time):
                    continue
            elif shift.liquidity_id is not None:
                # Structural branch must not acquire an implicit sweep prerequisite.
                parent = None
            gid = identity(self.experiment.id, self.experiment.branch, shift.id,
                           parent.id if parent else None)
            h = self._h4
            relation = ("HTF_UNAVAILABLE" if h is None else "HTF_NEUTRAL" if h.bias == "neutral"
                        else "HTF_ALIGNED" if h.bias == shift.event.direction else "COUNTER_HTF")
            gen = Generation(gid, self.experiment.branch, shift, parent, h, relation)
            self._generations[gid] = gen
            self._log(gid, shift.id, shift.stamp, None, "FORMING", "new_generation", (shift.id,))
            gen = self._generation_state(gen, "MSS_CONFIRMED", shift.id, shift.stamp, "opposing_bos_proxy")
            self._generation_state(gen, "WAITING_FOR_DISPLACEMENT", shift.id, shift.stamp, "await_directional_expansion")
            self._waiting.add(gid)
        for gid in sorted(self._waiting):
            gen = self._generations[gid]
            age = frame.stamp.index - gen.mss.stamp.index
            window = 0 if self.experiment.displacement_model == "S" else self.experiment.fixture_window
            match = next((d for d in frame.impulses if d.event.direction == gen.mss.event.direction), None)
            if 0 <= age <= window and match is not None:
                gen = replace(gen, displacement=match)
                self._generation_state(gen, "DISPLACEMENT_CONFIRMED", match.id,
                                       frame.stamp, "first_qualifying_displacement")
                self._by_displacement.setdefault(match.id, set()).add(gid)
                self._waiting.remove(gid)
            elif age >= window:
                self._generation_state(gen, "PREREQUISITE_FAILED", event_id, frame.stamp,
                                       "same_completion_displacement_missing" if window == 0
                                       else "fixture_displacement_window_exhausted")
                self._waiting.remove(gid)
        for array in sorted(frame.arrays, key=lambda a: a.id):
            for gid in sorted(self._by_displacement.get(array.displacement_id, ())):
                gen = self._generations[gid]
                if array.gap.direction != gen.mss.event.direction:
                    continue
                aid = identity(self.experiment.id, gid, array.id)
                area = Area(aid, gid, array, frame.stamp)
                self._areas[aid] = area
                self._active.add(aid)
                self._log(aid, array.id, frame.stamp, None, "FVG_AVAILABLE",
                          "associated_area", self._parents(area))
                if self.contract is None or array.association_contract != self.contract.name:
                    self._area_state(area, "UNLABELABLE", array.id, frame.stamp,
                                     "unresolved_fvg_association_D25_D27")
                elif array.gap.state not in self.contract.valid_gap_states:
                    self._area_state(area, "FVG_INVALIDATED" if array.gap.state == "invalidated"
                                     else "UNLABELABLE", array.id, frame.stamp, "ineligible_fixture_gap_state")
                else:
                    self._area_state(area, "WAITING_FOR_RETRACEMENT", array.id,
                                     frame.stamp, "ready_no_formation_contact")
        guards = {v.fvg_id: v for v in frame.validity}
        for aid in sorted(self._active):
            area = self._areas[aid]
            if frame.stamp.time <= area.ready.time:
                continue
            area = self._guard(area, guards.get(area.fvg.id), frame.stamp, event_id)
            if area.state != "WAITING_FOR_RETRACEMENT":
                continue
            gap = area.fvg.gap
            if frame.candle.low <= gap.upper and frame.candle.high >= gap.lower:
                area = self._area_state(area, "CONTACTED", event_id, frame.stamp,
                                        "inclusive_later_range_contact", contact=frame.stamp)
                if self.experiment.entry_model == "F":
                    self._area_state(area, "WAITING_FOR_M5_CONFIRMATION", event_id,
                                     frame.stamp, "armed_after_contact")
                else:
                    self._entry(area, frame, event_id)

    def _guard(self, area, validity, stamp, event_id):
        if (self.contract is None or validity is None
                or validity.contract != self.contract.name):
            return self._area_state(area, "UNLABELABLE", event_id, stamp,
                                    "unresolved_causal_validity_D28_D40_D42_D43_D44")
        if validity.status != "VALID":
            return self._area_state(area, validity.status, event_id, stamp,
                                    validity.reference_id)
        if validity.gap_state not in self.contract.valid_gap_states:
            return self._area_state(area, "FVG_INVALIDATED" if validity.gap_state == "invalidated"
                                    else "UNLABELABLE", event_id, stamp, "ineligible_fixture_gap_state")
        return area

    def _entry(self, area, frame, event_id):
        gen = self._generations[area.generation_id]
        bullish = gen.mss.event.direction == "bullish"
        swing = frame.structure.protected_low if bullish else frame.structure.protected_high
        price = frame.candle.close
        reason = None
        if swing is None:
            reason = "missing_protected_swing"
        elif not isfinite(swing.price):
            reason = "non_finite_anchor"
        elif swing.kind != ("low" if bullish else "high"):
            reason = "invalid_anchor_kind"
        elif swing.price == price:
            reason = "zero_risk"
        elif (bullish and swing.price > price) or (not bullish and swing.price < price):
            reason = "directionally_invalid_anchor"
        if reason:
            self._area_state(area, "UNLABELABLE", event_id, frame.stamp, reason)
            return
        risk = abs(price - swing.price)
        objective = price + (2 * risk if bullish else -2 * risk)
        if not isfinite(risk) or not isfinite(objective):
            self._area_state(area, "UNLABELABLE", event_id, frame.stamp, "invalid_level_construction")
            return
        self._entries.append(Entry(
            identity(self.experiment.id, area.id, "entry"), self.experiment.id,
            area.id, gen.id, gen.branch, gen.mss.event.direction, "A", frame.stamp,
            price, swing.price, swing, frame.stamp, risk, objective, area.contact,
            self._parents(area)))
        self._area_state(area, "ENTERED", event_id, frame.stamp, "m15_completion_close_entry")

    def _on_m5(self, frame, event_id):
        guards = {v.fvg_id: v for v in frame.validity}
        for aid in sorted(self._active):
            area = self._areas[aid]
            if area.state != "WAITING_FOR_M5_CONFIRMATION":
                continue
            if frame.stamp.time <= area.contact.time:
                continue
            area = self._guard(area, guards.get(area.fvg.id), frame.stamp, event_id)
            if area.state in TERMINAL:
                continue
            gen = self._generations[area.generation_id]
            match = next((s for s in sorted(frame.shifts, key=lambda s: s.id)
                          if s.event.direction == gen.mss.event.direction), None)
            if match is not None:
                # Accept causal confirmation observation, not an invented F fill.
                self._area_state(area, "UNLABELABLE", match.id, frame.stamp,
                                 "m5_confirmed_entry_disabled_D51_D55_D56", confirmation=match)
