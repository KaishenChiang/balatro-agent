"""Performance evidence must separate observed waits, gaps and host failures."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('timing_evidence', Path(__file__).resolve().parents[1] / 'scripts/analyze_timings.py')
timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing)


def row(step, wait=100, gap=200, state='COMPLETED'):
    return {'step': step, 'tool': 'act', 'parameters': {'action': 'play'},
            'result': {'state': state, 'reason': 'wrong_phase' if state == 'REJECTED' else 'completed'},
            'client_tool_ms': wait, 'inter_call_gap_ms': gap}


def test_scope_excludes_pre_scope_gap_and_preserves_rejections():
    report = timing.summarize([row(1), row(2, gap=999999), row(3, state='REJECTED'), row(4)], 2, 3)
    assert report['calls'] == 2
    assert report['tool_wait']['total_ms'] == 200
    assert report['inter_call_gap']['total_ms'] == 200
    assert report['rejections'] == {'wrong_phase': 1}
    assert report['pure_model_latency_ms'] is None and not report['performance_improvement_proven']


def test_host_error_attempt_is_not_mcp_delivery_or_action():
    failed = row(2, wait=100000)
    failed['evidence_type'] = 'host_tool_error_not_mcp_delivery'
    report = timing.summarize([row(1), failed, row(3)])
    assert report['calls'] == 3 and report['delivered_calls'] == 2 and report['host_errors'] == 1
    assert report['tool_wait']['total_ms'] == 200 and report['action_states'] == {'COMPLETED': 2}


def test_unknown_and_missing_timing_are_not_zero_or_normal_completion():
    report = timing.summarize([row(1, wait=None, gap=None, state='UNKNOWN'), row(2, wait=True, gap=-1)])
    assert report['tool_wait'] == {'count': 0}
    assert report['inter_call_gap'] == {'count': 0}
    assert report['action_states']['UNKNOWN'] == 1


def test_wall_time_uses_actual_start_and_end_and_p95_nearest_rank():
    a = row(1, wait=150); b = row(2, wait=250)
    a.update(client_started_utc='2026-10-04T12:00:00Z', client_finished_utc='2026-10-04T12:00:00.150Z')
    b.update(client_started_utc='2026-10-04T12:00:01Z', client_finished_utc='2026-10-04T12:00:01.250Z')
    report = timing.summarize([a,b])
    assert report['scope_wall_ms'] == 1250 and report['tool_wait']['p95_ms'] == 250


def test_legacy_actual_delivery_layout_and_native_completion_timing():
    rows = [
        {'step': 1, 'tool': 'act', 'arguments': {'action': 'select', 'parameters': {'region': 'shop_jokers'}},
         'duration_ms': 20, 'started_at': '2026-10-05T00:00:00Z', 'ended_at': '2026-10-05T00:00:00.020Z',
         'result': {'state': 'COMPLETED', 'timing': {'native_elapsed_ms': 0}}},
        {'step': 2, 'tool': 'act', 'arguments': {'action': 'play', 'parameters': {'positions': [0]}},
         'duration_ms': 100, 'started_at': '2026-10-05T00:00:01Z', 'ended_at': '2026-10-05T00:00:01.100Z',
         'result': {'state': 'UNKNOWN', 'timing': {'native_elapsed_ms': 90}}},
    ]
    report = timing.summarize(rows)
    assert report['tool_wait']['total_ms'] == 120 and report['inter_call_gap']['total_ms'] == 980
    assert report['selection_by_region'] == {'shop_jokers': 1} and report['direct_hand_requests'] == 1
    assert report['by_completed_action_native_ms'] == {'select': {'count': 1, 'total_ms': 0, 'median_ms': 0, 'p95_ms': 0, 'max_ms': 0}}
    assert 'parameters' not in rows[0] and report['pure_model_latency_ms'] is None
    assert report['delivered_result_utf8_bytes']['count'] == 2
