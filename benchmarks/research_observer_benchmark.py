"""Synthetic-first observer benchmark; optional hard-coded 2018 prefix smoke.

Run: PYTHONPATH=. python benchmarks/research_observer_benchmark.py OUTPUT
Add --development only after tests pass. OUTPUT must be new and local/ignored.
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import gc
import io
from itertools import islice
import json
from pathlib import Path
import random
import statistics
import time
import tracemalloc

from research.labels import FutureLabel, label_observation
from research.observer import ObservationRecord, ResearchObserver, capture_selection
from research.storage import export_dataset, fingerprint, verify_export
from strategy.engine import EngineConfig
from strategy.optimized_engine_v2 import OptimizedSequentialResearchEngineV2
from strategy.structure import Candle
from strategy.timeframes import ContextSeries

ENGINE_ID = '5b0d557a3d6fcddebab74b79d2e6c3bb563fec8b6a5019d72111ea6f1f31ed2a'


def synthetic(count):
    rng = random.Random(711)
    price = 100.
    candles = []
    for i in range(count):
        opening = price
        price += rng.uniform(-2, 2) * (3 if i % 19 == 0 else 1)
        candles.append(Candle(opening, max(opening,price)+rng.random(),
                              min(opening,price)-rng.random(), price))
    times = tuple(datetime(2020,1,1,tzinfo=timezone.utc)+timedelta(minutes=15*i+(75 if i>=count//2 else 0)) for i in range(count))
    execution = ContextSeries(tuple(candles),'M15',times)
    indices = tuple(range(15,count,16))
    h4 = ContextSeries(tuple(candles[i] for i in indices),'H4',tuple(times[i] for i in indices))
    source = fingerprint({'execution':[asdict(c) for c in candles],
                          'timestamps':[t.isoformat() for t in times],
                          'h4_indices':indices,'kind':'synthetic'})
    return execution,h4,source


def run(execution,h4,mode):
    engine = OptimizedSequentialResearchEngineV2(execution,h4)
    observer = ResearchObserver('SYNTH' if mode != 'smoke' else 'EURUSD')
    rows,labels,signals = [],[],[]
    for candle in execution.candles:
        snapshot = engine.advance()
        if snapshot.signal:
            signals.append(snapshot.signal)
        if mode != 'A':
            row = observer.observe(candle,snapshot,capture_selection(engine,snapshot))
            if row is not None:
                rows.append(row)
    if mode in ('C','smoke'):
        # Observations are finalized before any future history is inspected.
        labels = [label_observation(row,execution) for row in rows]
    return rows,labels,tuple(signals)


def benchmark(execution,h4,source,out,*,smoke=False):
    result = {'completed_candles':len(execution.candles),'source_fingerprint':source,'modes':{}}
    previous_signals = None
    for mode in ('A','B','C'):
        timings=[]
        for _ in range(3):
            gc.collect()
            started=time.perf_counter()
            rows,labels,signals=run(execution,h4,mode)
            timings.append(time.perf_counter()-started)
        if previous_signals is not None:
            assert signals==previous_signals
        previous_signals=signals
        gc.collect()
        tracemalloc.start()
        run(execution,h4,mode)
        _,peak=tracemalloc.get_traced_memory()
        tracemalloc.stop()
        result['modes'][mode]={'median_seconds':statistics.median(timings),'samples_seconds':timings,
                               'peak_traced_bytes':peak,'observations':len(rows),'labels':len(labels),
                               'signals':len(signals)}
    rows,labels,signals=run(execution,h4,'smoke' if smoke else 'C')
    args=dict(source_fingerprint=source,engine_identity=ENGINE_ID,
              configuration_identity=fingerprint(asdict(EngineConfig())))
    start=time.perf_counter()
    manifest=export_dataset(rows,out/'observations',record_type=ObservationRecord,population='eligible',**args)
    label_manifest=export_dataset(labels,out/'labels',record_type=FutureLabel,population='offline_labels',
                                  observation_dataset_fingerprint=manifest['dataset_fingerprint'],
                                  **dict(args,configuration_identity=fingerprint({'engine':asdict(EngineConfig()),'horizon':96,'same_candle_policy':'conservative'})))
    assert verify_export(out/'observations')==manifest
    assert verify_export(out/'labels')==label_manifest
    result['export_and_verify_seconds']=time.perf_counter()-start
    result['observation_csv_bytes']=(out/'observations'/'rows.csv').stat().st_size
    result['label_csv_bytes']=(out/'labels'/'rows.csv').stat().st_size
    result['observation_dataset_fingerprint']=manifest['dataset_fingerprint']
    result['label_dataset_fingerprint']=label_manifest['dataset_fingerprint']
    result['labelable']=sum(l.labelable for l in labels)
    result['example_observations']=[asdict(r) for r in rows[:2]] if smoke else []
    baseline=result['modes']['A']['median_seconds']
    for mode in ('B','C'):
        result['modes'][mode]['overhead_percent']=100*(result['modes'][mode]['median_seconds']/baseline-1)
    return result


def development_prefix():
    from data.mt5 import load_mt5_metaquotes_m1_csv
    from data.historical import aggregate_timeframe,dataset_fingerprint
    # Never enumerate partitions or open another year/instrument.
    path=Path('.research-data/CP-001/raw/pre-holdout/MT5/MetaQuotes-Demo/CP001_MetaQuotes-Demo_EURUSD_M1_2018.csv')
    with path.open() as stream:
        text=''.join(islice(stream,12001))  # header + 12,000 M1 candles only
    m1=load_mt5_metaquotes_m1_csv(io.StringIO(text),dataset_identifier='observer-smoke-EURUSD-2018-prefix')
    assert len(m1.candles)==12000 and all(c.timestamp.year==2018 for c in m1.candles)
    m15=aggregate_timeframe(m1,timedelta(minutes=15),timeframe_label='M15')
    h4=aggregate_timeframe(m1,timedelta(hours=4),timeframe_label='H4')
    return m15.context_series('M15'),h4.context_series('H4'),dataset_fingerprint(m1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--development',action='store_true')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    results={}
    if args.development:
        results['EURUSD_2018_prefix']=benchmark(*development_prefix(),args.output/'smoke',smoke=True)
        print('completed development prefix',flush=True)
    else:
        for count in (512,1024,2048):
            results[str(count)]=benchmark(*synthetic(count),args.output/str(count))
            print('completed synthetic',count,flush=True)
    (args.output/'benchmark.json').write_text(json.dumps(results,sort_keys=True,indent=2)+'\n')
    print(args.output/'benchmark.json',flush=True)
