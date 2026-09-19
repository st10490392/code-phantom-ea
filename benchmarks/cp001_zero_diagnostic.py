import gc
import hashlib
import json
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

from data.historical import HistoricalDataset, aggregate_timeframe, dataset_fingerprint
from data.mt5 import load_mt5_metaquotes_m1_csv
from strategy.engine import EngineConfig
from strategy.optimized_engine_v2 import OptimizedSequentialResearchEngineV2

ROOT = Path('.research-data/CP-001/raw/pre-holdout/MT5/MetaQuotes-Demo')
YEARS = range(2018, 2023)
GATES = ('HTF context', 'liquidity event', 'structural shift',
         'displacement', 'PD array', 'premium/discount')
EXPECTED = {
    'EURUSD': ('9ea6bbd6e96e1a248657fbfba90387d8b4ad22f02bd353591620bdd993697d67', 124322, 7781),
    'GBPUSD': ('4197fa40c489531ff1f4461156c937ee92ec84bd9c9b5385213425abee3959f9', 124324, 7781),
}
RESULT_PATH = Path('experiments/CP-001-development-results-v1.json')
RESULT_FILE_SHA256 = '43ae8a681b9ab72e754ed94120c73625bac9e4c6855a5ccdffb6b15f88c2e4d7'


def pct(count, denominator):
    return 100.0 * count / denominator if denominator else 0.0


def iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def load(symbol):
    candles = []
    for year in YEARS:
        path = ROOT / f'CP001_MetaQuotes-Demo_{symbol}_M1_{year}.csv'
        dataset = load_mt5_metaquotes_m1_csv(path, dataset_identifier=f'{symbol}-{year}')
        candles.extend(dataset.candles)
        print('LOADED', symbol, year, len(dataset.candles), flush=True)
    m1 = HistoricalDataset(tuple(candles), f'CP-001-{symbol}-development')
    fingerprint = dataset_fingerprint(m1)
    m15 = aggregate_timeframe(m1, timedelta(minutes=15), timeframe_label='M15')
    h4 = aggregate_timeframe(m1, timedelta(hours=4), timeframe_label='H4')
    expected = EXPECTED[symbol]
    assert (fingerprint, len(m15.candles), len(h4.candles)) == expected
    print('INPUT', symbol, fingerprint, len(m15.candles), len(h4.candles), flush=True)
    return m15, h4, fingerprint


def blank_direction():
    return {
        'eligible_candles': 0,
        'emitted_signals': 0,
        'individual_pass_counts': Counter(),
        'cumulative_pass_counts': Counter(),
        'first_fail_counts': Counter(),
        'near_miss_distribution': Counter(),
        'pairwise_intersections': Counter(),
    }


def evidence_record(snapshot):
    by_name = {item.name: item for item in snapshot.evidence}
    return {
        name: {
            'detail': by_name[name].detail,
            'index': by_name[name].index,
            'passed': by_name[name].passed,
            'source_id': by_name[name].source_id,
        } for name in GATES
    }


def diagnostic(symbol, m15, h4, config):
    execution = m15.context_series('M15')
    higher = h4.context_series('H4')
    engine = OptimizedSequentialResearchEngineV2(execution, higher, config)
    total = len(execution.candles)
    h4_completed = 0
    h4_bias = Counter()
    dealing_range_available = 0
    eligible = 0
    signals = 0
    direction_counts = Counter()
    trigger_counts = Counter()
    individual = Counter()
    cumulative = Counter()
    first_fail = Counter()
    near_miss = Counter()
    near_missing = Counter()
    pairs = Counter()
    by_direction = {'bullish': blank_direction(), 'bearish': blank_direction()}
    pd_types = Counter()
    pd_ages = []
    liquidity_types = Counter()
    examples = []
    earliest = {}
    started = time.perf_counter()
    for index in range(total):
        snapshot = engine.advance()
        engine._snapshots.clear()
        if snapshot.htf_context.completed_index is not None:
            h4_completed += 1
        h4_bias[snapshot.htf_context.bias] += 1
        dealing_range_available += snapshot.dealing_range is not None
        if not snapshot.evidence:
            if (index + 1) % 10000 == 0:
                print('PROGRESS', symbol, index + 1,
                      f'{time.perf_counter()-started:.3f}', 'eligible', eligible,
                      flush=True)
            continue
        eligible += 1
        signals += snapshot.signal is not None
        evidence = {item.name: item for item in snapshot.evidence}
        direction = (snapshot.signal.direction if snapshot.signal is not None else
                     ('bullish' if any(
                         (item.name in ('structural shift', 'displacement') and item.passed
                          and item.detail.startswith('matching'))
                         for item in snapshot.evidence) else None))
        # Signal may be absent; recover exact selected direction from the same
        # priority inputs exposed by Revision 2 state.
        shifts = engine._state.structure.shifts
        shift = shifts[-1] if shifts and shifts[-1].index == index else None
        displacement = snapshot.displacement
        terminal = [item for item in snapshot.liquidity_events
                    if item.pool_state == 'consumed']
        if shift is not None:
            direction = shift.direction; trigger = 'current_mss'
        elif displacement is not None:
            direction = displacement.direction; trigger = 'current_displacement'
        else:
            assert terminal
            direction = terminal[-1].direction; trigger = 'current_terminal_liquidity'
        assert direction in ('bullish', 'bearish')
        direction_counts[direction] += 1
        trigger_counts[trigger] += 1
        target = by_direction[direction]
        target['eligible_candles'] += 1
        target['emitted_signals'] += snapshot.signal is not None
        passed = {name: evidence[name].passed for name in GATES}
        for name, value in passed.items():
            if value:
                individual[name] += 1
                target['individual_pass_counts'][name] += 1
        prefix = True
        for name in GATES:
            prefix = prefix and passed[name]
            if prefix:
                cumulative[name] += 1
                target['cumulative_pass_counts'][name] += 1
        failed = next((name for name in GATES if not passed[name]), None)
        first_fail[failed or 'emitted'] += 1
        target['first_fail_counts'][failed or 'emitted'] += 1
        score = sum(passed.values())
        near_miss[f'{score}/6'] += 1
        target['near_miss_distribution'][f'{score}/6'] += 1
        if score == 5:
            missing = next(name for name in GATES if not passed[name])
            near_missing[missing] += 1
        for left_pos, left in enumerate(GATES):
            for right in GATES[left_pos + 1:]:
                if passed[left] and passed[right]:
                    key = f'{left} × {right}'
                    pairs[key] += 1
                    target['pairwise_intersections'][key] += 1
        pd = evidence['PD array']
        if pd.passed:
            pd_types[pd.detail] += 1
            pd_ages.append(index - pd.index)
        liquidity = evidence['liquidity event']
        if liquidity.passed:
            liquidity_types[liquidity.detail] += 1

        record = {
            'direction': direction,
            'evidence': evidence_record(snapshot),
            'passed_required_count': score,
            'timestamp': iso(execution.timestamps[index]),
            'trigger': trigger,
        }
        # Deterministic representative selection: earliest for each requested
        # category plus strongest near misses ranked after the pass count.
        for category, condition in (
            ('mss', passed['structural shift']),
            ('displacement', passed['displacement']),
            ('liquidity', passed['liquidity event']),
        ):
            key = f'{category}:{direction}'
            if condition and key not in earliest:
                earliest[key] = record
        examples.append(record)
        if (index + 1) % 10000 == 0:
            print('PROGRESS', symbol, index + 1, f'{time.perf_counter()-started:.3f}',
                  'eligible', eligible, flush=True)

    strongest = sorted(examples, key=lambda item: (-item['passed_required_count'],
                                                    item['timestamp']))[:8]
    representatives = list(earliest.values()) + strongest
    unique = []
    seen = set()
    for item in representatives:
        key = (item['timestamp'], item['direction'])
        if key not in seen:
            seen.add(key); unique.append(item)

    def format_direction(item):
        denominator = item['eligible_candles']
        return {
            'eligible_candles': denominator,
            'emitted_signals': item['emitted_signals'],
            'individual_pass_counts': dict(item['individual_pass_counts']),
            'cumulative_pass_counts': dict(item['cumulative_pass_counts']),
            'first_fail_counts': dict(item['first_fail_counts']),
            'near_miss_distribution': dict(item['near_miss_distribution']),
            'pairwise_intersections': dict(item['pairwise_intersections']),
        }
    result = {
        'completed_h4_context_candles': h4_completed,
        'completed_h4_context_percentage_total_m15': pct(h4_completed, total),
        'dealing_range_available_candles': dealing_range_available,
        'dealing_range_available_percentage_total_m15': pct(dealing_range_available, total),
        'direction_counts': dict(direction_counts),
        'direction_trigger_counts': dict(trigger_counts),
        'directional_breakdown': {key: format_direction(value)
                                  for key, value in by_direction.items()},
        'eligible_candidate_evaluations': eligible,
        'eligible_percentage_total_m15': pct(eligible, total),
        'emitted_research_signals': signals,
        'first_fail_counts': dict(first_fail),
        'funnel': {
            'cumulative_pass_counts': dict(cumulative),
            'individual_pass_counts': dict(individual),
            'percent_of_eligible': {name: pct(individual[name], eligible)
                                    for name in GATES},
            'percent_of_total_m15': {name: pct(individual[name], total)
                                     for name in GATES},
        },
        'h4_bias_counts': dict(h4_bias),
        'liquidity_terminal_event_types': dict(liquidity_types),
        'near_miss_distribution': dict(near_miss),
        'n_minus_1_missing_conditions': dict(near_missing),
        'pairwise_intersections': dict(pairs),
        'pairwise_zero_intersections': [
            f'{left} × {right}' for pos, left in enumerate(GATES)
            for right in GATES[pos + 1:] if pairs[f'{left} × {right}'] == 0
        ],
        'pd_array_age_execution_bars': ({
            'count': len(pd_ages), 'maximum': max(pd_ages),
            'minimum': min(pd_ages), 'mean': sum(pd_ages) / len(pd_ages),
        } if pd_ages else {'count': 0, 'maximum': None, 'minimum': None, 'mean': None}),
        'pd_array_types': dict(pd_types),
        'representative_examples': unique,
        'total_completed_m15_candles': total,
    }
    print('COMPLETE', symbol, 'eligible', eligible, 'signals', signals, flush=True)
    return result


def main():
    assert hashlib.sha256(RESULT_PATH.read_bytes()).hexdigest() == RESULT_FILE_SHA256
    baseline = json.loads(Path('experiments/CP-001-baseline-v1.json').read_text())
    config = EngineConfig(**baseline['specification']['candidate_generation']['engine'])
    instruments = {}
    for symbol in ('EURUSD', 'GBPUSD'):
        m15, h4, fingerprint = load(symbol)
        instruments[symbol] = {
            'development_fingerprint': fingerprint,
            'diagnostic': diagnostic(symbol, m15, h4, config),
        }
        del m15, h4
        gc.collect()
    assert hashlib.sha256(RESULT_PATH.read_bytes()).hexdigest() == RESULT_FILE_SHA256
    result = {
        'baseline_fingerprint': baseline['freeze_fingerprint'],
        'candidate_gate_order': list(GATES),
        'development_result_file_sha256': RESULT_FILE_SHA256,
        'development_result_fingerprint': '57671bc3eade824bdd97b0cf6d680e43641f093b7555049e578115f6f77e606e',
        'diagnostic_id': 'CP-001-zero-candidate-diagnostic-v1',
        'execution_revision_2_fingerprint': '5b0d557a3d6fcddebab74b79d2e6c3bb563fec8b6a5019d72111ea6f1f31ed2a',
        'git_revision': '8afbd0d3feb03608f30ec50cf50b99bffed107f2',
        'instruments': instruments,
        'scope': 'non-mutating diagnostic over development source years 2018-2022 only',
    }
    canonical = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)
    artifact = {
        'diagnostic': result,
        'diagnostic_fingerprint': hashlib.sha256(canonical.encode()).hexdigest(),
        'fingerprint_algorithm': 'sha256(canonical-json(diagnostic))',
    }
    Path('experiments/CP-001-zero-candidate-diagnostic-v1.json').write_text(
        json.dumps(artifact, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print('DIAGNOSTIC_FINGERPRINT', artifact['diagnostic_fingerprint'], flush=True)


if __name__ == '__main__':
    main()
