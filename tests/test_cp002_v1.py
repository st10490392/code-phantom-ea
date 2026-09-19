"""Strict semantic closure fixtures. No files, historical candles or outcomes."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from random import Random

import pytest

from research.cp002 import H4Context, Stamp, identity
from research.cp002_v1 import (
    Bar, Config, Coverage, Frame, Level, ResearchEngine, StrictCore,
    gap_facts, reference_fill, strict_fvg,
)
from research.cp002_v1_labels import first_outcome_start, label_entry
from strategy.fvg import Displacement
from strategy.structure import Candle, StructureShift, StructureState, SwingPoint


BASE = datetime(2000, 12, 31, 23, tzinfo=timezone.utc)


def bar(i, c=None, tf="M15", time=None, **kw):
    minutes = 15 if tf == "M15" else 5
    return Bar(Stamp(i, time or BASE+timedelta(minutes=(i+1)*minutes), tf),
               c or Candle(14, 15, 11, 14), **kw)


def mirror(c): return Candle(24-c.open, 24-c.low, 24-c.high, 24-c.close)


def state(i, direction="bullish", price=None):
    if i == 0:
        return StructureState(0)
    price = (6 if i < 4 else 8) if price is None else price
    if direction == "bearish": price = 24-price
    swing = SwingPoint(0 if i < 4 else 1, price, "low" if direction == "bullish" else "high",
                       "internal", 1 if i < 4 else 3)
    return StructureState(i, protected_low=swing if direction == "bullish" else None,
                          protected_high=swing if direction == "bearish" else None)


def shift(i=2, direction="bullish"):
    return StructureShift(i, direction, 12, "internal",
        "bearish" if direction == "bullish" else "bullish", "MSS", 0,
        "high" if direction == "bullish" else "low")


def frames(direction="bullish", levels=()):
    candles = [Candle(9, 10, 8, 9), Candle(9, 10, 8, 9),
               Candle(9, 15, 7, 14), Candle(14, 16, 12, 15), Candle(14, 15, 11, 14)]
    if direction == "bearish": candles = [mirror(c) for c in candles]
    return [Frame(bar(i,c), state(i,direction),
                  (shift(i,direction),) if i == 2 else (),
                  Displacement(i,direction,5,8) if i == 2 else None,
                  levels if i == 1 else ()) for i,c in enumerate(candles)]


def core(branch="STRUCTURAL_REVERSAL", model="A"):
    return StrictCore(Config("SYNTH", "synthetic:closure", branch, model), synthetic=True)


def run(items, engine=None):
    engine = engine or core()
    for item in items: engine.advance(item)
    return engine


def levels(direction="bullish"):
    return tuple(Level(f"level-{i}", f"group-{i}", "low" if direction == "bullish" else "high",
                       price if direction == "bullish" else 24-price, (0,), 1,
                       "internal" if i == 0 else "external") for i,price in enumerate((9,8)))


@pytest.mark.parametrize("direction", ["bullish", "bearish"])
def test_strict_triplet_availability_first_contact_and_boundary_fill(direction):
    f = frames(direction)
    engine = run(f[:3])
    path, = engine.paths.values()
    assert path.state == "WAITING_FOR_C3" and path.fvg is None
    assert not engine.entries
    engine.advance(f[3])
    ready = engine.paths[path.id]
    assert ready.fvg.c2 == f[2].bar.stamp and ready.fvg.c3 == f[3].bar.stamp
    assert ready.state == "WAITING_FOR_RETRACEMENT" and ready.contact is None
    assert engine.lifecycle[-1].facts == ("CREATED", "AVAILABLE", "UNTOUCHED")
    assert not engine.entries  # C3 necessarily touches the near edge
    engine.advance(f[4])
    entry, = engine.entries
    assert entry.path.id == path.id and entry.path.fvg == ready.fvg
    assert entry.reference_fill == 12 and entry.candidate_available_at == f[4].bar.stamp.time
    assert entry.interaction_start == f[4].bar.start and entry.interaction_end == f[4].bar.stamp.time
    assert entry.stop == (8 if direction == "bullish" else 16)
    assert entry.stop_anchor.index == 1 and entry.stop_snapshot == f[4].bar.stamp
    assert entry.path.protection.price == (6 if direction == "bullish" else 18)
    assert entry.target == (20 if direction == "bullish" else 4)
    assert entry.path.contact.time > ready.fvg.c3.time
    assert "CONTACTED" in engine.lifecycle[-1].facts


@pytest.mark.parametrize("direction", ["bullish", "bearish"])
def test_strict_fvg_equality_is_not_gap(direction):
    f = frames(direction)
    c = Candle(11,12,10,11) if direction == "bullish" else Candle(13,14,12,13)
    f[3] = replace(f[3], bar=bar(3,c))
    engine = run(f)
    p, = engine.paths.values()
    assert p.state == "NO_ASSOCIATED_FVG" and p.reason == "strict_triplet_has_no_gap"
    assert not engine.entries


def test_c2_ownership_rejects_later_or_historical_displacement_and_second_gap():
    f = frames()
    bad = replace(f[2], displacement=Displacement(1,"bullish",5,8))
    engine = run(f[:2])
    trace = engine.transitions
    with pytest.raises(ValueError, match="current displacement"): engine.advance(bad)
    assert engine.transitions == trace
    no_s = run(f[:2]+[replace(f[2], displacement=None),f[3],f[4]])
    assert next(iter(no_s.paths.values())).state == "DISPLACEMENT_MISSING"
    entered = run(f)
    original = entered.entries[0]
    entered.advance(Frame(bar(5,Candle(17,19,16,18)),state(5)))
    assert entered.entries == (original,)
    assert len({p.fvg.id for p in entered.paths.values() if p.fvg}) == 1


@pytest.mark.parametrize("direction", ["bullish", "bearish"])
def test_multiple_directional_sweep_parents_preserved_single_owned_fvg(direction):
    engine = run(frames(direction, levels(direction)),core("SWEEP_REVERSAL"))
    entries = engine.entries
    assert len(entries) == 2
    assert len({e.path.liquidity.id for e in entries}) == 2
    assert len({e.path.fvg.id for e in entries}) == 1
    assert all(e.path.liquidity.kind == "SAME_CANDLE_SWEEP" for e in entries)
    assert {e.path.liquidity.level.structure for e in entries} == {"internal","external"}
    assert all(e.path.liquidity.stamp == e.path.created for e in entries)


@pytest.mark.parametrize("contact_candle,kind", [
    (Candle(10,15,9,14),"TOUCH"),
    (Candle(9,15,7,9),"TOUCH"),
    (Candle(9,15,7,8),"BREAK_PENDING"),
])
def test_equality_or_close_beyond_is_not_same_candle_sweep(contact_candle,kind):
    f=frames(levels=(levels()[0],))
    f[2]=replace(f[2],bar=bar(2,contact_candle))
    engine=run(f[:3],core("SWEEP_REVERSAL"))
    assert engine.liquidity[-1].kind == kind
    assert not engine.paths


def test_no_delayed_reclaim_or_reusing_consumed_parent():
    f=frames(levels=(levels()[0],))
    f[1]=replace(f[1],bar=bar(1,Candle(9,10,7,8)))
    engine=run(f,core("SWEEP_REVERSAL"))
    assert [x.kind for x in engine.liquidity] == ["BREAK_PENDING"]
    assert not engine.paths
    seeded=run(frames(levels=(levels()[0],)),core("SWEEP_REVERSAL"))
    before=dict(seeded.paths)
    seeded.advance(Frame(bar(5),state(5), (shift(5),), Displacement(5,"bullish",5,8)))
    assert dict(seeded.paths)==before
    with pytest.raises(ValueError,match="delayed reclaim"):
        Config("SYNTH","fixture",sweep_model="RECLAIM")


def test_new_liquidity_generation_can_seed_but_old_parent_is_immutable():
    engine=run(frames(levels=(levels()[0],)),core("SWEEP_REVERSAL"))
    old,=engine.paths.values()
    new=replace(levels()[0],id="new-generation",source_indices=(0,2),confirmed_at=4)
    engine.advance(Frame(bar(5,Candle(9,15,7,14)),state(5), (shift(5),),
                         Displacement(5,"bullish",5,8),(new,)))
    assert len(engine.paths)==2 and engine.paths[old.id]==old
    assert {p.liquidity.level.id for p in engine.paths.values()}=={"level-0","new-generation"}


def test_first_interaction_lifecycle_is_observational_not_percentage_invalidation():
    f=frames()
    f[4]=replace(f[4],bar=bar(4,Candle(14,15,9,9.5)))
    engine=run(f)
    assert engine.lifecycle[-1].facts==("CONTACTED","FULLY_TRAVERSED","CLOSE_THROUGH")
    assert engine.entries[0].reference_fill==12
    original=engine.entries[0]
    engine.advance(Frame(bar(5,Candle(9,10,5,6)),state(5)))
    assert engine.entries==(original,)


def test_opposite_mss_cancels_preentry_not_postentry():
    f=frames()
    f[4]=replace(f[4],shifts=(shift(4,"bearish"),))
    engine=run(f)
    original=next(p for p in engine.paths.values() if p.created.index==2)
    assert original.state=="CANCELLED_OPPOSITE_MSS" and not engine.entries
    entered=run(frames())
    before=entered.entries
    entered.advance(Frame(bar(5),state(5),(shift(5,"bearish"),)))
    assert entered.entries==before and entered.paths[before[0].path.id].state=="ENTERED"


def test_frozen_protection_cannot_move_away_to_rescue_path():
    f=frames()
    f[4]=replace(f[4],bar=bar(4,Candle(8,9,5,8)),structure=state(4,price=2))
    engine=run(f)
    p,=engine.paths.values()
    assert p.protection.price==6 and p.state=="STRUCTURALLY_INVALIDATED"
    assert not engine.entries


def test_same_interval_contact_and_structural_invalidation_is_not_loss():
    f=frames()
    f[4]=replace(f[4],bar=bar(4,Candle(14,15,5,14)))
    engine=run(f)
    p,=engine.paths.values()
    assert p.state=="AMBIGUOUS_CONTACT_INVALIDATION"
    assert p.contact==f[4].bar.stamp and not engine.entries
    assert engine.transitions[-1].reasons==("AMBIGUOUS_CONTACT_INVALIDATION",)


def test_gap_through_without_overlap_never_fabricates_fill():
    f=frames()
    f[4]=replace(f[4],bar=bar(4,Candle(9,9.5,8,9)))
    engine=run(f)
    p,=engine.paths.values()
    assert p.state=="UNFILLABLE_GAP_THROUGH" and p.contact is None
    assert not engine.entries


@pytest.mark.parametrize("opening", [10,11,12])
def test_open_inside_including_boundaries_uses_open(opening):
    f=frames(); f[4]=replace(f[4],bar=bar(4,Candle(opening,15,9,14)))
    entry=run(f).entries[0]
    assert entry.reference_fill==opening
    assert entry.candidate_available_at==f[4].bar.stamp.time


def test_unapproved_approach_fails_closed_without_reference_guess():
    f=frames(); f[4]=replace(f[4],bar=bar(4,Candle(9,13,8.5,12)))
    engine=run(f)
    assert not engine.entries
    assert next(iter(engine.paths.values())).reason=="unsupported_reference_fill_approach"


@pytest.mark.parametrize("at_mss", [True,False])
def test_missing_protection_or_entry_stop_has_explicit_reason(at_mss):
    f=frames(); i=2 if at_mss else 4; f[i]=replace(f[i],structure=StructureState(i))
    engine=run(f); p,=engine.paths.values()
    assert p.state=="UNLABELABLE"
    assert p.reason==("mss_protection:" if at_mss else "entry_stop:")+"missing_protected_swing"


def test_natural_warmup_and_year_boundary_do_not_reset_raw_detector_state():
    engine=ResearchEngine(Config("SYNTH","natural"))
    candles=[Candle(10,11,9,10)]*7
    for i,c in enumerate(candles):
        engine.advance(bar(i,c))
        assert not engine.core.paths  # no required structural events exist
    assert len(engine._candles)==7
    assert engine._last.stamp.time.year==2001
    assert engine._structure.bias=="neutral"
    # The completed year is a report label only; no restart or fixed warm-up gate.
    assert engine.core._last['M15'].stamp.index==6


def test_raw_detector_adapter_replay_and_prefix_are_identical():
    rng=Random(81); price=100; bars=[]
    for i in range(100):
        close=price+rng.choice((-4,-2,1,3)); high=max(price,close)+1; low=min(price,close)-1
        bars.append(bar(i,Candle(price,high,low,close))); price=close
    config=Config("SYNTH","detector-prefix")
    first,second=ResearchEngine(config),ResearchEngine(config)
    for b in bars[:50]: first.advance(b)
    prefix=first.core.transitions
    for b in bars[50:]: first.advance(b)
    for b in bars: second.advance(b)
    assert first.core.transitions[:len(prefix)]==prefix
    assert first.core.transitions==second.core.transitions
    assert first.core.entries==second.core.entries
    before=first.core.transitions
    for b in bars: assert first.advance(b)==()
    assert first.core.transitions==before


def test_normal_closure_preserves_setup_missing_coverage_does_not():
    f=frames(); ready=run(f[:4]); missing=run(f[:4])
    later_time=f[4].bar.stamp.time+timedelta(days=2)
    later=replace(f[4].bar,stamp=replace(f[4].bar.stamp,time=later_time))
    closure=Coverage(f[3].bar.stamp.time,later.start,"MARKET_CLOSED","synthetic:closure")
    ready.advance(replace(f[4],bar=replace(later,gap_before=closure)))
    assert ready.entries[0].path.created==f[2].bar.stamp
    missing.advance(replace(f[4],bar=later))
    assert next(iter(missing.paths.values())).state=="DATA_COVERAGE_FAILURE"
    assert not missing.entries


def test_false_or_partial_closure_attestation_cannot_cover_material_gap():
    f=frames(); engine=run(f[:4])
    b=replace(f[4].bar,stamp=replace(f[4].bar.stamp,time=f[4].bar.stamp.time+timedelta(hours=1)))
    attestation=Coverage(f[3].bar.stamp.time+timedelta(minutes=5),b.start,"MARKET_CLOSED","partial")
    engine.advance(replace(f[4],bar=replace(b,gap_before=attestation)))
    assert next(iter(engine.paths.values())).reason=="required_transition_unobservable"


def f_entry():
    f=frames(); engine=core(model="F")
    # Warm synthetic M5 evidence stream before contact; M15 must precede M5 at equality.
    m5_index=0
    for frame in f:
        # Fill all M5 intervals preceding this M15 completion.
        while BASE+timedelta(minutes=(m5_index+1)*5)<frame.bar.stamp.time:
            engine.advance(Frame(bar(m5_index,Candle(14,15,11,14),"M5"),StructureState(m5_index)))
            m5_index+=1
        engine.advance(frame)
        # Same-completion confirmation must not qualify.
        shifts=(shift(m5_index),) if frame.bar.stamp.index==4 else ()
        engine.advance(Frame(bar(m5_index,Candle(14,15,11,14),"M5"),StructureState(m5_index),shifts))
        m5_index+=1
    assert not engine.entries and next(iter(engine.paths.values())).state=="M5_CONFIRMATION_ARMED"
    confirm=bar(m5_index,Candle(13,15,12,14),"M5")
    engine.advance(Frame(confirm,StructureState(m5_index),(shift(m5_index),)))
    return engine,confirm


def test_m5_cannot_confirm_before_or_at_contact_uses_subsequent_close():
    engine,confirm=f_entry(); entry,=engine.entries
    assert entry.model=="F" and entry.reference_fill==14
    assert entry.candidate_available_at==confirm.stamp.time
    assert entry.path.confirmation==confirm.stamp
    assert entry.path.confirmation.time>entry.path.contact.time
    assert entry.stop_snapshot.time<confirm.stamp.time  # no enclosing future M15 state


def test_missing_m5_coverage_fails_path_not_aggressive_fallback():
    engine=run(frames(),core(model="F"))
    t=engine._last['M15'].stamp.time+timedelta(minutes=10)
    engine.advance(Frame(bar(0,Candle(13,15,12,14),"M5",time=t),StructureState(0)))
    p,=engine.paths.values()
    assert p.state=="DATA_COVERAGE_FAILURE" and not engine.entries


def test_production_gates_s_a_only_w_reclaim_and_f_refused():
    assert Config("SYNTH","run-readiness").require_runnable()
    with pytest.raises(ValueError,match="W remains unfrozen"):
        Config("SYNTH","fixture",displacement_model="W")
    with pytest.raises(ValueError,match="coverage scheduler"):
        ResearchEngine(Config("SYNTH","fixture",entry_model="F"))


def outcome_bars(entry,n=96,c=None):
    start=first_outcome_start(entry)
    return [bar(i,c or Candle(13,14,11,13),time=start+timedelta(minutes=(i+1)*15)) for i in range(n)]


def test_aggressive_outcomes_exclude_contact_candle_and_stop_first_is_postentry_only():
    entry=run(frames()).entries[0]
    assert first_outcome_start(entry)==entry.interaction_end
    both=Candle(12,21,7,12)
    bars=outcome_bars(entry,c=both)
    result=label_entry(entry,bars,experiment_id=entry.experiment_id)
    assert result.result=="STOP_FIRST" and result.ambiguous_stop_first
    assert result.observed_bars==96 and result.horizon_complete
    assert entry.path.state=="ENTERED"  # labels cannot rewrite causality


def test_m5_outcome_excludes_partial_interval_and_equal_boundary_start():
    engine,confirm=f_entry(); entry=engine.entries[0]
    start=first_outcome_start(entry)
    assert start>confirm.stamp.time
    partial=bar(0,Candle(14,100,0,14),time=start)
    result=label_entry(entry,[partial]+outcome_bars(entry),experiment_id=entry.experiment_id)
    assert result.result=="TIMEOUT" and result.mfe==0 and result.mae==3
    aligned=replace(entry,candidate_available_at=start)
    assert first_outcome_start(aligned)==start+timedelta(minutes=15)


def test_timeout_censoring_namespace_and_label_isolation():
    engine=run(frames()); entry=engine.entries[0]; before=engine.transitions
    full=label_entry(entry,outcome_bars(entry),experiment_id=entry.experiment_id)
    short=label_entry(entry,outcome_bars(entry,3),experiment_id=entry.experiment_id)
    assert full.result=="TIMEOUT" and short.result=="CENSORED"
    with pytest.raises(ValueError,match="namespace"):
        label_entry(entry,[],experiment_id="other")
    with pytest.raises(TypeError,match="no future labels"): engine.advance(full)
    assert engine.transitions==before
    with pytest.raises(FrozenInstanceError): full.result="TARGET_FIRST"


def test_future_prefix_invariance_and_replay_identity_with_year_boundary():
    f=frames(); first=run(f[:4]); prefix=first.transitions
    snapshot=dict(first.paths)
    first.advance(f[4]); replay=run(f)
    assert first.transitions[:len(prefix)]==prefix
    assert all(p.state=="WAITING_FOR_RETRACEMENT" for p in snapshot.values())
    assert identity(first.transitions,first.entries)==identity(replay.transitions,replay.entries)
    for frame in f: assert first.advance(frame)==()
    assert first.entries==replay.entries
