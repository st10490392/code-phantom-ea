"""Synthetic causal events only. Fixture policies are not research parameters."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import pytest

from research.cp002 import (
    Area, Array, Experiment, H4Context, Impulse, M15Frame, M5Frame,
    Shift, Stamp, Sweep, SyntheticContract, TemporalCore, Validity, identity,
)
from strategy.fvg import Displacement, detect_displacement
from strategy.imbalance import Gap
from strategy.liquidity_v2 import LiquidityEvent
from strategy.structure import (
    Candle, StructureShift, StructureState, SwingPoint, detect_structure_shift,
)


EPOCH = datetime(2000, 1, 3, tzinfo=timezone.utc)
CONTRACT = SyntheticContract("fixture:explicit-association-and-guards", ("new", "active", "partial"))


def stamp(index, timeframe="M15"):
    minutes = {"M15": 15, "M5": 5, "H4": 240}[timeframe]
    return Stamp(index, EPOCH + timedelta(minutes=index * minutes), timeframe)


def core(**kwargs):
    return TemporalCore(Experiment("synthetic-v1", "SYNTH", "synthetic:only", **kwargs),
                        fixture_contract=CONTRACT)


def shift(index=2, direction="bullish", timeframe="M15", name="mss", liquidity=None):
    return Shift(name, stamp(index, timeframe), StructureShift(
        index, direction, 12, "external", "bearish" if direction == "bullish" else "bullish",
        "MSS", 0, "high" if direction == "bullish" else "low"), liquidity)


def impulse(index=2, direction="bullish", name="disp"):
    return Impulse(name, stamp(index), Displacement(index, direction, 6, 8))


def array(index=2, direction="bullish", name="fvg", parent="disp"):
    low, high = (10, 12) if direction == "bullish" else (12, 14)
    return Array(name, stamp(index), Gap(index, direction, low, high, "active"),
                 parent, CONTRACT.name)


def guard(name="fvg", status="VALID", gap_state="active"):
    return Validity(name, CONTRACT.name, status, gap_state, "fixture:causal-guard-reference")


def snapshot(index, direction="bullish", price=None):
    price = (8 if direction == "bullish" else 16) if price is None else price
    swing = SwingPoint(0, price, "low" if direction == "bullish" else "high", "external", 1)
    return StructureState(index, protected_low=swing if direction == "bullish" else None,
                          protected_high=swing if direction == "bearish" else None)


def candle(direction="bullish", contact=True):
    c = Candle(14, 15, 11, 14) if contact else Candle(15, 16, 13, 15)
    if direction == "bearish":
        return Candle(24-c.open, 24-c.low, 24-c.high, 24-c.close)
    return c


def formation(direction="bullish", h4=None, siblings=1, liquidity=None):
    return M15Frame(stamp(2), candle(direction), snapshot(2, direction), h4,
                    shifts=(shift(direction=direction, liquidity=liquidity),),
                    impulses=(impulse(direction=direction),),
                    arrays=tuple(array(direction=direction, name=f"fvg-{i}")
                                 for i in range(siblings)))


def later(index=3, direction="bullish", siblings=1, contact=True, **changes):
    frame = M15Frame(stamp(index), candle(direction, contact), snapshot(index, direction),
                     validity=tuple(guard(f"fvg-{i}") for i in range(siblings)))
    return replace(frame, **changes)


@pytest.mark.parametrize("direction", ["bullish", "bearish"])
def test_mirrored_later_wick_entry_has_complete_immutable_parent_chain(direction):
    engine = core()
    ready = formation(direction)
    engine.advance(ready)
    area = next(iter(engine.areas.values()))
    gen = engine.generations[area.generation_id]
    assert area.state == "WAITING_FOR_RETRACEMENT"
    assert area.ready == ready.stamp and area.contact is None
    assert gen.mss.id == "mss" and gen.displacement.id == "disp"
    assert gen.branch == "STRUCTURAL_REVERSAL" and gen.liquidity is None
    assert not engine.entries  # formation candle overlaps, but cannot enter
    frame = later(direction=direction)
    assert not area.fvg.gap.lower <= frame.candle.close <= area.fvg.gap.upper
    engine.advance(frame)
    entry, = engine.entries
    assert entry.area_id == area.id and entry.generation_id == gen.id
    assert entry.parent_ids[-3:] == ("mss", "disp", "fvg-0")
    assert entry.stamp == frame.stamp and entry.contact == frame.stamp
    assert entry.price == frame.candle.close and entry.entry_model == "A"
    assert entry.stop == (8 if direction == "bullish" else 16)
    assert entry.objective == entry.price + (2 if direction == "bullish" else -2)*entry.risk
    assert entry.horizon_subsequent_m15 == 96 and entry.same_candle_policy == "conservative"
    states = [t.after for t in engine.transitions if t.subject_id == area.id]
    assert states == ["FVG_AVAILABLE", "WAITING_FOR_RETRACEMENT", "CONTACTED", "ENTERED"]
    assert engine.areas[area.id].reason == "m15_completion_close_entry"
    assert area.state == "WAITING_FOR_RETRACEMENT"  # old snapshot is unchanged
    with pytest.raises(FrozenInstanceError):
        entry.price = 0


@pytest.mark.parametrize("bias,relation", [
    ("bullish", "HTF_ALIGNED"), ("bearish", "COUNTER_HTF"),
    ("neutral", "HTF_NEUTRAL"), (None, "HTF_UNAVAILABLE"),
])
def test_h4_classification_is_descriptive_latched_and_does_not_gate(bias, relation):
    engine = core()
    context = None if bias is None else H4Context("h4-initial", stamp(0, "H4"), bias)
    engine.advance(formation(h4=context))
    gen, = engine.generations.values()
    engine.advance(later(h4=None))
    assert len(engine.entries) == 1
    assert engine.generations[gen.id].htf_relationship == relation
    assert engine.generations[gen.id].h4 == context


def test_h4_future_context_rejected_before_mutation():
    engine = core()
    with pytest.raises(ValueError, match="H4"):
        engine.advance(formation(h4=H4Context("future", stamp(1, "H4"), "bullish")))
    assert not engine.generations and not engine.transitions


def sweep(index=2, name="sweep", event_type="wick_sweep"):
    return Sweep(name, stamp(index), LiquidityEvent(
        index, "pool:generation-1", "sell_side", 9,
        "reclaimed" if event_type == "reclaim_sweep" else "wick_swept", 10,
        index, index, "bullish", event_type, (0,), "consumed"))


@pytest.mark.parametrize("kind", ["wick_sweep", "reclaim_sweep"])
def test_sweep_parent_equal_completion_is_latched_before_mss(kind):
    engine = core(branch="SWEEP_REVERSAL")
    parent = sweep(event_type=kind)
    engine.advance(replace(formation(liquidity="sweep"), sweeps=(parent,)))
    gen, = engine.generations.values()
    assert gen.liquidity == parent
    assert gen.mss.stamp.time == parent.stamp.time
    newer = sweep(3, "newer")
    engine.advance(later(sweeps=(newer,)))
    assert engine.generations[gen.id].liquidity == parent
    assert "sweep" in engine.entries[0].parent_ids and "newer" not in engine.entries[0].parent_ids


@pytest.mark.parametrize("kind", ["structural_break", "breach"])
def test_accepted_breakout_or_pending_breach_never_becomes_reversal_sweep(kind):
    engine = core(branch="SWEEP_REVERSAL")
    engine.advance(replace(formation(liquidity="sweep"), sweeps=(sweep(event_type=kind),)))
    assert not engine.generations and not engine.areas and not engine.entries


def test_sweep_branch_requires_parent_but_structural_branch_does_not():
    swept = core(branch="SWEEP_REVERSAL")
    swept.advance(formation())
    assert not swept.generations
    structural = core()
    structural.advance(formation())
    assert next(iter(structural.generations.values())).liquidity is None


def test_reclaim_availability_cannot_be_backdated():
    engine = core(branch="SWEEP_REVERSAL")
    bad = replace(sweep(), event=replace(sweep().event, confirmation_index=3))
    with pytest.raises(ValueError, match="backdated"):
        engine.advance(replace(formation(liquidity="sweep"), sweeps=(bad,)))
    assert not engine.transitions


def test_s_missing_or_opposite_displacement_is_terminal_not_satisfied_later():
    engine = core()
    engine.advance(replace(formation(), impulses=(impulse(direction="bearish"),), arrays=()))
    gen, = engine.generations.values()
    assert gen.state == "PREREQUISITE_FAILED"
    engine.advance(later(impulses=(impulse(3, name="later-disp"),),
                         arrays=(array(3, name="late", parent="later-disp"),)))
    assert engine.generations[gen.id].state == "PREREQUISITE_FAILED"
    assert not engine.areas


def test_unresolved_w_and_fixture_window_never_authorize_campaign():
    exp = Experiment("w", "SYNTH", "synthetic", displacement_model="W")
    with pytest.raises(ValueError, match="numerical W is not frozen"):
        exp.require_runnable()
    with pytest.raises(ValueError, match="unresolved W"):
        TemporalCore(exp, fixture_contract=CONTRACT)
    fixture_exp = replace(exp, fixture_window=2)
    with pytest.raises(ValueError, match="fixture values"):
        fixture_exp.require_runnable()
    with pytest.raises(ValueError, match="campaign disabled"):
        core().experiment.require_runnable()
    for bad in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            replace(exp, fixture_window=bad)


def test_fixture_local_w_latches_first_matching_event_never_replaces_it():
    engine = core(displacement_model="W", fixture_window=2)
    engine.advance(replace(formation(), impulses=(), arrays=()))
    gen, = engine.generations.values()
    assert gen.state == "WAITING_FOR_DISPLACEMENT"
    engine.advance(later(impulses=(impulse(3, "bearish", "opposite"),)))
    assert engine.generations[gen.id].displacement is None
    engine.advance(later(4, impulses=(impulse(4, name="first"),),
                         arrays=(array(4, name="fvg-0", parent="first"),)))
    assert engine.generations[gen.id].displacement.id == "first"
    engine.advance(later(5, impulses=(impulse(5, name="second"),)))
    assert engine.generations[gen.id].displacement.id == "first"
    assert engine.entries[0].stamp.index == 5


def test_w_fixture_boundary_timeout_not_global_setup_expiry():
    engine = core(displacement_model="W", fixture_window=1)
    engine.advance(replace(formation(), impulses=(), arrays=()))
    engine.advance(later(contact=False))
    assert next(iter(engine.generations.values())).state == "PREREQUISITE_FAILED"
    assert engine.transitions[-1].reason == "fixture_displacement_window_exhausted"


def test_unrelated_historical_fvg_cannot_satisfy_parent():
    engine = core()
    engine.advance(replace(formation(), arrays=(array(name="unrelated", parent="old-displacement"),)))
    assert not engine.areas
    with pytest.raises(ValueError, match="current finite ordinary FVG"):
        engine.advance(later(arrays=(array(2, name="backdated"),)))
    assert not engine.entries


def test_all_sibling_arrays_retained_and_independent_invalidation():
    engine = core()
    engine.advance(formation(siblings=3))
    before = dict(engine.areas)
    assert len(before) == 3
    assert len({a.generation_id for a in before.values()}) == 1
    guards = (guard("fvg-0", "FVG_INVALIDATED", "invalidated"),
              guard("fvg-1"), guard("fvg-2"))
    engine.advance(later(siblings=3, validity=guards))
    by_fvg = {a.fvg.id: a for a in engine.areas.values()}
    assert by_fvg["fvg-0"].state == "FVG_INVALIDATED"
    assert by_fvg["fvg-1"].state == by_fvg["fvg-2"].state == "ENTERED"
    assert len(engine.entries) == 2
    for aid, old in before.items():
        assert old.fvg == engine.areas[aid].fvg and old.generation_id == engine.areas[aid].generation_id
        assert old.ready == engine.areas[aid].ready


def test_siblings_have_no_hidden_capacity_eviction():
    engine = core()
    engine.advance(formation(siblings=200))
    ids = set(engine.areas)
    engine.advance(later(siblings=200))
    assert set(engine.areas) == ids and len(engine.entries) == 200
    assert len({e.id for e in engine.entries}) == 200
    assert all(e.stamp == stamp(3) for e in engine.entries)


@pytest.mark.parametrize("touch", [10, 12])
def test_contact_geometry_is_inclusive_at_both_boundaries(touch):
    engine = core()
    engine.advance(formation())
    engine.advance(later(candle=Candle(touch, touch, touch, touch)))
    assert engine.entries[0].price == touch


def test_repeated_contact_and_exact_batch_replay_do_not_duplicate():
    engine = core()
    frames = [formation(), later(), later(4)]
    for f in frames:
        engine.advance(f)
    trace, entries = engine.transitions, engine.entries
    for f in frames:
        assert engine.advance(f) == ()
    assert engine.entries == entries and engine.transitions == trace
    assert len(entries) == 1 and len({t.id for t in trace}) == len(trace)
    with pytest.raises(ValueError, match="conflicting replay"):
        engine.advance(replace(frames[1], candle=Candle(14, 16, 11, 14)))
    assert engine.transitions == trace


def test_no_retracement_does_not_expire_and_gap_without_overlap_is_not_contact():
    engine = core()
    engine.advance(formation())
    for i in range(3, 103):
        engine.advance(later(i, contact=False))
    area, = engine.areas.values()
    assert area.state == "WAITING_FOR_RETRACEMENT" and area.ready == stamp(2)
    assert not engine.entries


def test_m5_before_equal_and_after_contact_and_disabled_result_path():
    engine = core(entry_model="F")
    engine.advance(formation())
    engine.advance(M5Frame(stamp(8, "M5"), (shift(8, timeframe="M5", name="before"),)))
    assert next(iter(engine.areas.values())).confirmation is None
    engine.advance(later())
    engine.advance(M5Frame(stamp(9, "M5"), (shift(9, timeframe="M5", name="equal"),)))
    assert next(iter(engine.areas.values())).state == "WAITING_FOR_M5_CONFIRMATION"
    confirm = shift(10, timeframe="M5", name="after")
    engine.advance(M5Frame(stamp(10, "M5"), (confirm,), (guard("fvg-0"),)))
    area, = engine.areas.values()
    assert area.contact == stamp(3) and area.confirmation == confirm
    assert area.confirmation.stamp.time > area.contact.time
    assert area.state == "UNLABELABLE"
    assert area.reason == "m5_confirmed_entry_disabled_D51_D55_D56"
    assert not engine.entries


def test_wrong_direction_m5_never_falls_back_to_a_or_uses_m1():
    engine = core(entry_model="F")
    engine.advance(formation())
    engine.advance(later())
    engine.advance(M5Frame(stamp(10, "M5"),
                           (shift(10, "bearish", "M5", "wrong-m5"),), (guard("fvg-0"),)))
    assert next(iter(engine.areas.values())).state == "WAITING_FOR_M5_CONFIRMATION"
    assert not engine.entries
    with pytest.raises(ValueError, match="M1 refinement is deferred"):
        Stamp(1, EPOCH, "M1")


def test_m5_future_enclosing_m15_snapshot_cannot_be_used():
    engine = core(entry_model="F")
    engine.advance(formation())
    engine.advance(later())
    engine.advance(later(4, contact=False))
    with pytest.raises(ValueError, match="out-of-order"):
        engine.advance(M5Frame(stamp(10, "M5"), (shift(10, timeframe="M5"),)))
    assert not engine.entries


@pytest.mark.parametrize("price,reason", [(None, "missing_protected_swing"),
    (float('nan'), "non_finite_anchor"), (float('inf'), "non_finite_anchor"),
    (14, "zero_risk"), (15, "directionally_invalid_anchor")])
def test_invalid_structural_stop_is_explicit_unlabelable(price, reason):
    engine = core()
    engine.advance(formation())
    structural = StructureState(3) if price is None else snapshot(3, price=price)
    engine.advance(later(structure=structural))
    area, = engine.areas.values()
    assert area.state == "UNLABELABLE" and area.reason == reason
    assert area.contact == stamp(3) and not engine.entries


def test_stop_uses_current_causal_m15_snapshot_not_setup_stop():
    engine = core()
    engine.advance(formation())
    entry_swing = SwingPoint(1, 9, "low", "external", 3)
    engine.advance(later(structure=StructureState(3, protected_low=entry_swing)))
    entry, = engine.entries
    assert entry.stop_reference == entry_swing and entry.stop_snapshot == stamp(3)
    assert entry.stop == 9 and entry.stop != 8
    engine.advance(later(4, structure=snapshot(4, price=10)))
    assert engine.entries[0] == entry


def test_unconfirmed_stop_rejected_before_batch_mutation():
    engine = core()
    engine.advance(formation())
    trace = engine.transitions
    future = SwingPoint(1, 8, "low", "external", 4)
    with pytest.raises(ValueError, match="unavailable protected"):
        engine.advance(later(structure=StructureState(3, protected_low=future)))
    assert engine.transitions == trace and not engine.entries


@pytest.mark.parametrize("terminal", ["STRUCTURALLY_INVALIDATED", "FVG_INVALIDATED"])
def test_terminal_area_never_resurrects(terminal):
    engine = core()
    engine.advance(formation())
    engine.advance(later(validity=(guard("fvg-0", terminal),)))
    old, = engine.areas.values()
    engine.advance(later(4))
    assert engine.areas[old.id] == old and old.state == terminal
    assert not engine.entries


def test_new_mss_generation_never_mutates_existing_parent_chain():
    engine = core()
    engine.advance(formation())
    gen, = engine.generations.values()
    engine.advance(later(contact=False, shifts=(shift(3, name="mss-2"),),
                         impulses=(impulse(3, name="disp-2"),),
                         arrays=(array(3, name="fvg-2", parent="disp-2"),)))
    assert len(engine.generations) == 2 and len(engine.areas) == 2
    assert engine.generations[gen.id] == gen
    assert {a.fvg.displacement_id for a in engine.areas.values()} == {"disp", "disp-2"}


@pytest.mark.parametrize("gap_kind", ["index", "time", "coverage"])
def test_missing_coverage_fails_closed_no_interpolation_or_later_reactivation(gap_kind):
    engine = core()
    engine.advance(formation())
    frame = later()
    if gap_kind == "index":
        frame = later(4)
    elif gap_kind == "time":
        frame = replace(frame, stamp=replace(frame.stamp, time=frame.stamp.time+timedelta(minutes=1)))
    else:
        frame = replace(frame, coverage_complete=False)
    engine.advance(frame)
    area, = engine.areas.values()
    assert area.state == "DATA_COVERAGE_FAILURE"
    assert area.reason == "noncontiguous_or_incomplete_stream"
    engine.advance(later(5))
    assert engine.areas[area.id] == area and not engine.entries


def test_unknown_validity_and_unapproved_association_fail_closed():
    engine = core()
    engine.advance(formation())
    engine.advance(later(validity=()))
    assert next(iter(engine.areas.values())).reason.startswith("unresolved_causal_validity")
    unsafe = TemporalCore(core().experiment)
    unsafe.advance(formation())
    assert next(iter(unsafe.areas.values())).reason == "unresolved_fvg_association_D25_D27"
    assert not unsafe.entries


def test_future_prefix_invariance_and_deterministic_replay():
    frames = [formation(), later(contact=False), later(4)]
    prefix = core()
    for f in frames[:2]:
        prefix.advance(f)
    prefix_trace, prefix_areas = prefix.transitions, dict(prefix.areas)
    one, two = core(), core()
    for engine in (one, two):
        for f in frames:
            engine.advance(f)
    assert one.transitions[:len(prefix_trace)] == prefix_trace
    assert all(a.state == "WAITING_FOR_RETRACEMENT" for a in prefix_areas.values())
    assert one.transitions == two.transitions and one.entries == two.entries
    assert identity(one.transitions, one.entries) == identity(two.transitions, two.entries)


def test_labels_and_mutable_inputs_cannot_be_state_machine_inputs():
    engine = core()
    engine.advance(formation())
    before = engine.transitions
    for payload in ({"future_label": "winner"}, {"mfe_r": 99}, object()):
        with pytest.raises(TypeError, match="no labels"):
            engine.advance(payload)
    with pytest.raises(TypeError):
        M15Frame(stamp(3), candle(), snapshot(3), future_label="winner")
    with pytest.raises(TypeError, match="immutable event tuples"):
        engine.advance(replace(later(), validity=[guard("fvg-0")]))
    with pytest.raises(TypeError):
        engine.areas["injected"] = Area
    with pytest.raises(AttributeError):
        engine.experiment = replace(engine.experiment, name="changed")
    assert engine.transitions == before


def test_changed_evidence_id_is_rejected_atomically():
    engine = core()
    engine.advance(formation())
    trace = engine.transitions
    with pytest.raises(ValueError, match="immutable evidence ID changed"):
        engine.advance(later(arrays=(array(3, name="fvg-0"),)))
    assert engine.transitions == trace


def test_existing_repository_detectors_can_supply_typed_proxy_evidence():
    candles = [Candle(10, 12, 8, 10)]*5 + [Candle(10, 11, 6, 7), Candle(7, 18, 7, 17)]
    highs = [SwingPoint(0, 12, "high", "external", 1)]
    lows = [SwingPoint(0, 8, "low", "external", 1)]
    mss = detect_structure_shift(candles, highs, lows)[-1]
    displacement = detect_displacement(candles)[-1]
    assert mss.index == displacement.index == 6 and mss.direction == "bullish"
    engine = core()
    engine.advance(M15Frame(stamp(6), candles[6], snapshot(6),
        shifts=(Shift("detected-mss", stamp(6), mss),),
        impulses=(Impulse("detected-disp", stamp(6), displacement),)))
    gen, = engine.generations.values()
    assert gen.mss.event == mss and gen.displacement.event == displacement


def test_same_timestamp_stream_order_is_enforced_not_incidental():
    engine = core(entry_model="F")
    engine.advance(formation())
    engine.advance(M5Frame(stamp(9, "M5")))
    trace = engine.transitions
    with pytest.raises(ValueError, match="M15 batch must precede M5"):
        engine.advance(later())
    assert engine.transitions == trace


def test_completed_h4_is_retained_for_new_generation_until_replaced():
    engine = core()
    h4 = H4Context("h4", stamp(0, "H4"), "bearish")
    engine.advance(formation(h4=h4))
    engine.advance(later(contact=False, shifts=(shift(3, name="next-mss"),),
                         impulses=(impulse(3, name="next-disp"),)))
    assert len(engine.generations) == 2
    assert all(g.h4 == h4 and g.htf_relationship == "COUNTER_HTF"
               for g in engine.generations.values())


def test_siblings_can_form_on_successive_completions_with_independent_ready_times():
    engine = core()
    engine.advance(formation())
    original, = engine.areas.values()
    engine.advance(later(contact=False, arrays=(array(3, name="sibling"),)))
    sibling = next(a for a in engine.areas.values() if a.fvg.id == "sibling")
    assert original.generation_id == sibling.generation_id
    assert original.ready == stamp(2) and sibling.ready == stamp(3)
    engine.advance(later(4, validity=(guard("fvg-0"), guard("sibling"))))
    assert {e.area_id for e in engine.entries} == {original.id, sibling.id}
    assert all(e.stamp == stamp(4) for e in engine.entries)
