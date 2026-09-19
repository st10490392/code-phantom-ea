from dataclasses import FrozenInstanceError, asdict, fields, replace
from datetime import timedelta
import json

import pytest

from research.labels import FutureLabel, label_observation
from research.observer import (GATES, ObservationRecord, ResearchObserver,
                               Selection, capture_selection, cohort)
from research.storage import export_dataset, fingerprint, verify_export
from strategy.confluence import Evidence, build_candidate_signal
from strategy.engine import EngineConfig
from strategy.optimized_engine_v2 import OptimizedSequentialResearchEngineV2
from strategy.structure import Candle
from strategy.timeframes import ContextSeries
from tests.test_optimized_engine_equivalence import _generated, _series


def journal(execution, higher=None, *, all_rows=False):
    engine = OptimizedSequentialResearchEngineV2(execution, higher)
    observer = ResearchObserver("SYNTH", include_untriggered=all_rows)
    rows = []
    for c in execution.candles:
        snapshot = engine.advance()
        row = observer.observe(c, snapshot, capture_selection(engine, snapshot))
        if row:
            rows.append(row)
    return rows, engine


@pytest.fixture
def sample():
    return _series(_generated(7, 100))


def test_determinism_causality_gaps_htf_and_nonmutation(sample):
    times = tuple(t + (timedelta(minutes=90) if i >= 40 else timedelta())
                  for i, t in enumerate(sample.timestamps))
    execution = ContextSeries(sample.candles, "M15", times)
    h4 = ContextSeries(tuple(execution.candles[i] for i in (15, 31, 47, 63, 79)),
                       "H4", tuple(times[i] for i in (15, 31, 47, 63, 79)))
    rows, observed = journal(execution, h4, all_rows=True)
    repeat, _ = journal(execution, h4, all_rows=True)
    assert rows == repeat
    off = OptimizedSequentialResearchEngineV2(execution, h4)
    assert off.run() == observed.snapshots
    assert tuple(s.signal for s in off.snapshots) == tuple(s.signal for s in observed.snapshots)
    for end in (14, 15, 39, 40, 64):
        prefix, _ = journal(execution.prefix(end), h4, all_rows=True)
        assert prefix == rows[:end + 1]
    assert rows[14].h4_available is False
    assert rows[15].h4_completed_index == 0
    assert rows[15].h4_completed_timestamp == rows[15].execution_timestamp
    with pytest.raises(FrozenInstanceError):
        rows[0].close = 0
    # Adapter and observer have no engine side effects, including caches.
    engine = OptimizedSequentialResearchEngineV2(execution, h4)
    observer = ResearchObserver("SYNTH")
    for c in execution.candles:
        s = engine.advance()
        before = repr(engine.__dict__)
        selection = capture_selection(engine, s)
        observer.observe(c, s, selection)
        assert repr(engine.__dict__) == before


def test_gate_accounting_ages_and_references(sample):
    rows, engine = journal(sample, all_rows=True)
    last_mss, last_disp = {}, {}
    pd_types = set()
    for row, snapshot in zip(rows, engine.snapshots):
        for event in snapshot.structure_events:
            if event.kind == "MSS":
                last_mss[event.direction] = event.index
        if snapshot.displacement:
            last_disp[snapshot.displacement.direction] = snapshot.execution_index
        if row.range_low is not None:
            assert row.range_position == pytest.approx((row.close-row.range_low)/(row.range_high-row.range_low))
            assert row.range_midpoint == (row.range_high+row.range_low)/2
        if row.execution_index >= 5:
            ranges = [c.high-c.low for c in sample.candles[row.execution_index-5:row.execution_index] if c.high>c.low]
            assert row.displacement_reference_range == sum(ranges)/len(ranges)
            assert row.displacement_range_threshold == row.displacement_reference_range*1.5
        d = row.selected_direction
        if d is None:
            assert row.gate_passes == () and not row.accepted_by_cp001_v1
            continue
        evidence = {e.name:e for e in snapshot.evidence}
        assert row.gate_passes == tuple(evidence[g].passed for g in GATES)
        assert row.gates_passed + len(row.missing_gates) == row.gates_required == 6
        assert row.first_failed_gate == next((g for g in GATES if not evidence[g].passed),None)
        assert row.matching_mss_age == (row.execution_index-last_mss[d] if d in last_mss else None)
        assert row.matching_displacement_age == (row.execution_index-last_disp[d] if d in last_disp else None)
        if row.liquidity_available:
            assert row.liquidity_index == evidence['liquidity event'].index
            assert row.liquidity_age == row.execution_index-row.liquidity_index
        if row.pd_type:
            pd_types.add(row.pd_type)
            assert row.pd_index == evidence['PD array'].index
            assert row.pd_age == row.execution_index-row.pd_index
            assert row.pd_is_current == (row.pd_age == 0)
            if row.pd_type == "IFVG":
                pd = next(g for g in snapshot.inverted_gaps if g.source_index == row.pd_source_index)
                assert row.pd_state == 'inverted'
            else:
                pd = next(g for g in snapshot.imbalances if g.created_at == row.pd_index)
                assert row.pd_state == pd.state
            assert (row.pd_lower,row.pd_upper) == (pd.lower,pd.upper)
    assert pd_types == {'FVG','IFVG'}
    for count in (4,5,6):
        assert list(cohort(rows,gates_passed=count)) == [r for r in rows if r.selected_direction and r.gates_passed==count]
    assert list(cohort(rows,missing_exactly=('structural shift',))) == [r for r in rows if r.missing_gates==('structural shift',)]
    assert all(r.current_mss for r in cohort(rows,current_mss=True))
    assert all(r.current_displacement for r in cohort(rows,current_displacement=True))
    assert all(r.direction_trigger=='current_terminal_liquidity' for r in cohort(rows,trigger='current_terminal_liquidity'))


def test_input_guards(sample):
    rows, engine = journal(sample)
    with pytest.raises(ValueError, match='current snapshot'):
        capture_selection(engine, engine.snapshots[0])
    with pytest.raises(ValueError, match='in order'):
        ResearchObserver('SYNTH').observe(sample.candles[1],engine.snapshots[1])
    with pytest.raises(ValueError, match='aware'):
        ResearchObserver('SYNTH').observe(sample.candles[0],replace(engine.snapshots[0],execution_timestamp=sample.timestamps[0].replace(tzinfo=None)))
    assert not set(f.name for f in fields(ObservationRecord)) & {'mfe','mae','mfe_r','mae_r','outcome_1r','outcome_2r'}


def level_fixture(sample, direction='bullish'):
    row = journal(sample)[0][0]
    return replace(row, execution_index=0, execution_timestamp=sample.timestamps[0].isoformat().replace('+00:00','Z'),
                   open=100.,high=100.,low=100.,close=100.,entry=100.,
                   selected_direction=direction, invalidation=99. if direction=='bullish' else 101.,
                   risk_distance=1., levels_valid=True,levels_reason=None)


def label_series(row, future):
    from datetime import datetime
    origin = datetime.fromisoformat(row.execution_timestamp.replace('Z','+00:00'))
    candles = (Candle(100,100,100,100),)+tuple(future)
    return ContextSeries(candles,'M15',tuple(origin+timedelta(minutes=15*i+(60 if i>=2 else 0)) for i in range(len(candles))))


@pytest.mark.parametrize('direction',['bullish','bearish'])
def test_excursions_ordering_and_conservative_ties(sample,direction):
    row = level_fixture(sample,direction)
    def c(hi,lo):
        return Candle(100,hi,lo,100) if direction=='bullish' else Candle(100,200-lo,200-hi,100)
    series = label_series(row,[c(101.2,99.5),c(102.5,99.4),c(100.5,98.5)])
    before = fingerprint(row)
    label = label_observation(row,series,horizon=3)
    assert (label.mfe,label.mae,label.mfe_r,label.mae_r)==(2.5,1.5,2.5,1.5)
    assert (label.bars_to_1r,label.bars_to_2r,label.bars_to_invalidation)==(1,2,3)
    assert label.one_r_before_invalidation and label.two_r_before_invalidation
    assert label.outcome_1r==label.outcome_2r=='target_first'
    tie = label_observation(row,label_series(row,[c(102.5,98.5)]),horizon=1)
    assert tie.outcome_1r==tie.outcome_2r=='invalidation_first'
    assert tie.ambiguity_1r and tie.ambiguity_2r
    split = label_observation(row,label_series(row,[c(101.2,99.5),c(102.5,98.5)]),horizon=2)
    assert split.one_r_before_invalidation and not split.two_r_before_invalidation
    assert fingerprint(row)==before
    assert label.observation_fingerprint==before
    assert not hasattr(row,'mfe')


def test_horizon_censoring_and_unlabelable(sample):
    row=level_fixture(sample)
    flat=Candle(100,100.5,99.5,100)
    series=label_series(row,[flat]*97)
    label=label_observation(row,series)
    assert label.horizon==label.observed_bars==96
    assert label.outcome_1r==label.outcome_2r=='neither_within_horizon'
    censored=label_observation(row,series.prefix(2))
    assert censored.outcome_1r=='censored' and censored.one_r_before_invalidation is None
    empty=label_observation(row,series.prefix(0))
    assert empty.mfe is None and empty.mae is None
    for reason in ('missing_protected_swing','zero_risk','directionally_invalid_anchor'):
        bad=replace(row,levels_valid=False,levels_reason=reason,risk_distance=None)
        label=label_observation(bad,series)
        assert not label.labelable and label.unlabelable_reason==reason
        assert label.mfe_r is None and label.outcome_1r=='unlabelable'
    with pytest.raises(ValueError,match='source mismatch'):
        label_observation(replace(row,close=101),series)
    # Current candle extremes are excluded; the first future target is age 1.
    first=label_observation(row,label_series(row,[Candle(100,102,100,101)]))
    assert first.bars_to_2r==1


def test_structural_level_geometry(sample):
    from research.observer import structural_levels
    from strategy.structure import SwingPoint
    snapshot=journal(sample,all_rows=True)[1].snapshots[0]
    c=Candle(100,100,100,100)
    state=snapshot.structural_state
    assert structural_levels(c,snapshot,'bullish')[2]=='missing_protected_swing'
    for stop,reason in ((99,None),(100,'zero_risk'),(101,'directionally_invalid_anchor'),(float('nan'),'non_finite_anchor')):
        s=replace(snapshot,structural_state=replace(state,protected_low=SwingPoint(0,stop,'low',confirmed_at=0)))
        assert structural_levels(c,s,'bullish')[2]==reason
    s=replace(snapshot,structural_state=replace(state,protected_high=SwingPoint(0,101,'high',confirmed_at=0)))
    assert structural_levels(c,s,'bearish')==(101,1,None)


def test_export_determinism_separation_tamper_and_cohorts(sample,tmp_path):
    rows,_=journal(sample)
    args=dict(record_type=ObservationRecord,source_fingerprint='a'*64,engine_identity='b'*64,
              configuration_identity=fingerprint(EngineConfig()),population='eligible')
    a=export_dataset(iter(rows),tmp_path/'a',**args)
    b=export_dataset(iter(rows),tmp_path/'b',**args)
    assert a==b==verify_export(tmp_path/'a')
    assert (tmp_path/'a'/'rows.csv').read_bytes()==(tmp_path/'b'/'rows.csv').read_bytes()
    with pytest.raises(FileExistsError):
        export_dataset(rows,tmp_path/'a',**args)
    with pytest.raises(ValueError,match='ordered'):
        export_dataset(rows[::-1],tmp_path/'bad',**args)
    labels=[label_observation(r,sample) for r in rows]
    with pytest.raises(TypeError,match='mixing'):
        export_dataset(labels,tmp_path/'mix',**args)
    labelargs=dict(args,record_type=FutureLabel,population='offline_labels',observation_dataset_fingerprint=a['dataset_fingerprint'])
    manifest=export_dataset(labels,tmp_path/'labels',**labelargs)
    assert manifest==verify_export(tmp_path/'labels')
    assert all(l.observation_fingerprint==fingerprint(r) for l,r in zip(labels,rows))
    with (tmp_path/'a'/'rows.csv').open('ab') as f:
        f.write(b'bad')
    with pytest.raises(ValueError,match='table fingerprint'):
        verify_export(tmp_path/'a')


def test_separate_offline_roundtrip(sample,tmp_path):
    from research.storage import read_dataset
    rows,_=journal(sample,all_rows=True)
    args=dict(source_fingerprint='a'*64,engine_identity='b'*64,
              configuration_identity=fingerprint(EngineConfig()))
    obs=export_dataset(rows,tmp_path/'features',record_type=ObservationRecord,population='all_completed',**args)
    loaded=list(read_dataset(tmp_path/'features',record_type=ObservationRecord))
    assert loaded==rows
    labels=[label_observation(row,sample) for row in loaded]
    export_dataset(labels,tmp_path/'labels',record_type=FutureLabel,population='offline_labels',
                   observation_dataset_fingerprint=obs['dataset_fingerprint'],**args)
    assert list(read_dataset(tmp_path/'labels',record_type=FutureLabel))==labels
    assert list(read_dataset(tmp_path/'features',record_type=ObservationRecord))==rows
    with pytest.raises(TypeError,match='schema mismatch'):
        list(read_dataset(tmp_path/'labels',record_type=ObservationRecord))


def test_exact_cohort_combinations_and_ordering(sample):
    row=journal(sample)[0][0]
    fixtures=[]
    for missing in ((),('structural shift',),('premium/discount',),('structural shift','premium/discount')):
        fixtures.append(replace(row,gate_passes=tuple(g not in missing for g in GATES),
                                gates_passed=6-len(missing),missing_gates=missing,
                                first_failed_gate=missing[0] if missing else None,
                                accepted_by_cp001_v1=not missing))
    assert list(cohort(fixtures,accepted=True))==[fixtures[0]]
    assert list(cohort(fixtures,gates_passed=5))==fixtures[1:3]
    assert list(cohort(fixtures,missing_exactly=('premium/discount',)))==[fixtures[2]]
    assert list(cohort(fixtures,missing_exactly=('premium/discount','structural shift')))==[fixtures[3]]


def test_stop_first_beyond_horizon_and_nonzero_entry_extremes(sample):
    row=level_fixture(sample)
    flat=Candle(100,100.1,99.9,100)
    history=label_series(row,[flat]*96+[Candle(100,105,95,100)])
    l=label_observation(row,history)
    assert l.bars_to_1r is l.bars_to_2r is l.bars_to_invalidation is None
    assert l.horizon_complete and l.outcome_2r=='neither_within_horizon'
    l=label_observation(row,label_series(row,[Candle(100,100.5,98,100),Candle(100,103,100,102)]))
    assert l.outcome_1r==l.outcome_2r=='invalidation_first'
    assert l.bars_to_1r==2 and l.bars_to_invalidation==1
    # Entry candle's extreme range is not a future excursion or target touch.
    widened=replace(row,high=110,low=90)
    source=label_series(row,[flat])
    source=replace(source,candles=(Candle(100,110,90,100),flat))
    l=label_observation(widened,source)
    assert l.mfe==pytest.approx(.1) and l.mae==pytest.approx(.1)
    assert l.bars_to_1r is None


def test_reference_guards_and_subsecond_timestamps(sample):
    from research.observer import PDRef
    execution=replace(sample,timestamps=tuple(sample.timestamps[0]+timedelta(microseconds=i) for i in range(100)))
    rows,_=journal(execution,all_rows=True)
    assert len(rows)==100
    engine=OptimizedSequentialResearchEngineV2(sample)
    s=engine.advance()
    with pytest.raises(ValueError,match='future PD'):
        ResearchObserver('SYNTH').observe(sample.candles[0],s,
            Selection(bullish_pd=PDRef('FVG','bullish',10,10,1,2,'active')))


@pytest.mark.parametrize('direction',['bullish','bearish'])
def test_label_races_match_frozen_simulator(sample,direction):
    from backtest.simulator import HypotheticalLevels,simulate_candidates
    row=level_fixture(sample,direction)
    signal=build_candidate_signal(0,direction,())
    for candles in ([Candle(100,103,98,100)],
                    [Candle(100,101.2,99.5,100),Candle(100,103,98,100)],
                    [Candle(100,100.2,99.8,100)]):
        series=label_series(row,candles)
        label=label_observation(row,series,horizon=len(candles))
        for r,outcome in ((1,label.outcome_1r),(2,label.outcome_2r)):
            sign=1 if direction=='bullish' else -1
            levels=HypotheticalLevels(100,row.invalidation,100+sign*r)
            simulation=simulate_candidates(series.candles,(signal,),lambda _:levels,
                                           max_bars=len(candles),same_candle_policy='conservative')[0]
            expected={'win':'target_first','loss':'invalidation_first','unresolved':'neither_within_horizon'}
            assert outcome==expected[simulation.outcome]


def test_versioned_observer_identity():
    import hashlib
    from pathlib import Path
    from research.storage import implementation_identity
    artifact=json.loads(Path('experiments/research-observer-v1.json').read_text())
    spec=artifact['specification']
    assert fingerprint(spec)==artifact['observer_fingerprint']
    assert implementation_identity()==spec['implementation_files']
    assert fingerprint(implementation_identity())==spec['implementation_identity']
    assert asdict(EngineConfig())==spec['engine_configuration']
    assert [f.name for f in fields(ObservationRecord)]==[f['name'] for f in spec['schemas']['ObservationRecord']]
    assert [f.name for f in fields(FutureLabel)]==[f['name'] for f in spec['schemas']['FutureLabel']]
    for filename,sha in spec['frozen_checkpoints'].items():
        assert hashlib.sha256(Path('experiments',filename).read_bytes()).hexdigest()==sha
    engine=spec['source_engine']
    assert hashlib.sha256(Path(engine['artifact']).read_bytes()).hexdigest()==engine['artifact_sha256']
    assert json.loads(Path(engine['artifact']).read_text())['revision_fingerprint']==engine['revision_fingerprint']
    assert hashlib.sha256(Path('benchmarks/research_observer_benchmark.py').read_bytes()).hexdigest()==spec['benchmark_implementation_sha256']


def test_untriggered_retracement_sequence_references(sample):
    rows,engine=journal(sample,all_rows=True)
    assert any(r.selected_direction is None and (r.latest_bullish_liquidity or r.latest_bearish_liquidity) for r in rows)
    # Independently read current engine selections on every candle, including
    # no-trigger rows, so a later retracement can measure each direction's age.
    engine=OptimizedSequentialResearchEngineV2(sample)
    observer=ResearchObserver('SYNTH',include_untriggered=True)
    for c in sample.candles:
        s=engine.advance()
        row=observer.observe(c,s,capture_selection(engine,s))
        for direction in ('bullish','bearish'):
            event=engine._state.liquidity.latest_terminal[direction]
            ref=getattr(row,'latest_'+direction+'_liquidity')
            assert (ref is None)==(event is None)
            if ref:
                assert ref.index==event.index and ref.pool_id==event.pool_id
                assert row.execution_index-ref.index>=0
