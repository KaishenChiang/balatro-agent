"""Summarize delivered public call timings; never infer pure model latency."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def distribution(values):
    if not values:
        return {'count': 0}
    ordered = sorted(values)
    return {'count': len(values), 'total_ms': round(sum(values), 3),
            'median_ms': round(median(values), 3),
            'p95_ms': round(ordered[math.ceil(len(values) * .95) - 1], 3),
            'max_ms': round(ordered[-1], 3)}


def summarize(rows, first=None, last=None):
    # Both recorded client layouts are evidence. Normalize copies, never edit
    # the source or turn absent measurements into zero.
    normalized = []
    for row in rows:
        item = dict(row)
        for key, legacy in [('parameters', 'arguments'), ('client_tool_ms', 'duration_ms'),
                            ('client_started_utc', 'started_at'), ('client_finished_utc', 'ended_at')]:
            if key not in item and legacy in item:
                item[key] = item[legacy]
        normalized.append(item)
    calls = [r for r in normalized if 'tool' in r and 'step' in r
             and (first is None or r['step'] >= first) and (last is None or r['step'] <= last)]
    delivered = [r for r in calls if r.get('evidence_type') != 'host_tool_error_not_mcp_delivery']
    by_tool = defaultdict(list)
    for row in delivered:
        if numeric(row.get('client_tool_ms')):
            by_tool[row['tool']].append(row['client_tool_ms'])
    # The first selected call's gap begins outside the selected scope.
    gaps = []
    for previous, row in zip(calls, calls[1:]):
        gap = row.get('inter_call_gap_ms')
        if 'inter_call_gap_ms' not in row and 'client_finished_utc' in previous and 'client_started_utc' in row:
            gap = (datetime.fromisoformat(row['client_started_utc'].replace('Z', '+00:00'))
                   - datetime.fromisoformat(previous['client_finished_utc'].replace('Z', '+00:00'))).total_seconds() * 1000
        if numeric(gap):
            gaps.append(gap)
    actions = [r for r in delivered if r['tool'] == 'act']
    result = {'calls': len(calls), 'delivered_calls': len(delivered), 'host_errors': len(calls)-len(delivered),
              'tools': dict(Counter(r['tool'] for r in delivered)),
              'actions': dict(Counter(r['parameters']['action'] for r in actions)),
              'action_states': dict(Counter(r['result'].get('state', 'missing') for r in actions)),
              'rejections': dict(Counter(r['result'].get('reason', 'missing') for r in actions if r['result'].get('state') == 'REJECTED')),
              'tool_wait': distribution([v for values in by_tool.values() for v in values]),
              'by_tool_ms': {k: distribution(v) for k, v in sorted(by_tool.items())},
              'inter_call_gap': distribution(gaps), 'pure_model_latency_ms': None,
              'gap_includes': ['model/service scheduling', 'evidence persistence', 'other tools and maintenance', 'pauses'],
              'timing_unit': 'ms', 'performance_improvement_proven': False}
    by_action = defaultdict(list)
    for r in actions:
        if numeric(r.get('client_tool_ms')):
            by_action[r['parameters']['action']].append(r['client_tool_ms'])
    result['by_action_ms'] = {k: distribution(v) for k,v in sorted(by_action.items())}
    native = defaultdict(list)
    for row in actions:
        elapsed = (row['result'].get('timing') or {}).get('native_elapsed_ms')
        if row['result'].get('state') == 'COMPLETED' and numeric(elapsed):
            native[row['parameters']['action']].append(elapsed)
    result['by_completed_action_native_ms'] = {k: distribution(v) for k, v in sorted(native.items())}
    result['selection_by_region'] = dict(Counter(r['parameters'].get('parameters', {}).get('region', 'missing')
                                                for r in actions if r['parameters']['action'] == 'select'))
    result['direct_hand_requests'] = sum(r['parameters']['action'] in ('play', 'discard')
                                        and 'positions' in r['parameters'].get('parameters', {}) for r in actions)
    result['delivered_result_utf8_bytes'] = distribution([
        len(json.dumps(r['result'], ensure_ascii=False, separators=(',', ':')).encode('utf-8')) for r in delivered])
    result['result_size_unit'] = 'UTF-8 bytes; not model tokens'
    if calls and all(k in calls[0] and k in calls[-1] for k in ('client_started_utc', 'client_finished_utc')):
        result['scope_wall_ms'] = round((datetime.fromisoformat(calls[-1]['client_finished_utc'].replace('Z','+00:00'))
                                      - datetime.fromisoformat(calls[0]['client_started_utc'].replace('Z','+00:00'))).total_seconds()*1000,3)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--first', type=int)
    parser.add_argument('--last', type=int)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    evidence = (ROOT / args.evidence).resolve(); output = (ROOT / args.output).resolve()
    assert evidence.is_relative_to(ROOT / 'runs') and output.is_relative_to(ROOT / 'runs/checks')
    from balatro_agent.local_audit import safe_path
    safe_path(ROOT, *evidence.relative_to(ROOT).parts); safe_path(ROOT, *output.relative_to(ROOT).parts)
    rows = [json.loads(s) for s in evidence.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
    result = {'evidence_type': 'public_delivery_timings', 'source': args.evidence,
              'first_step': args.first, 'last_step': args.last, **summarize(rows, args.first, args.last)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('calls', 'tool_wait', 'inter_call_gap', 'action_states')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
