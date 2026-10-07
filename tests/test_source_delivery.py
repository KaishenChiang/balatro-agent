"""Release claims must bind to native terminal and current audited evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

scripts = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(scripts))
try:
    spec = importlib.util.spec_from_file_location('source_delivery', scripts / 'package_source.py')
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
finally:
    sys.path.remove(str(scripts))


def case(tmp_path):
    directory = tmp_path / 'runs/optimization/n5-example'
    directory.mkdir(parents=True)
    rows = [
        {'step': 1, 'tool': 'act', 'parameters': {'action': 'play'},
         'result': {'state': 'COMPLETED', 'completion_signal': 'terminal_confirmation',
                    'observation': {'outcome': 'win', 'profile': 2}}},
        {'step': 2, 'tool': 'close_game', 'result': {'state': 'COMPLETED', 'running': False}}
    ]
    summary = {'actual_evidence': 'runs/optimization/n5-example/codex-mcp.jsonl',
               'safe_delivery_audit': 'runs/checks/audit.json', 'whole_test_calls': 2,
               'start_or_resume_step': 1, 'terminal_step': 1, 'close_step': 2,
               'gameplay_calls': 1, 'outcome': 'win', 'profile': 2}
    def save():
        log = directory / 'codex-mcp.jsonl'
        log.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        (directory / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
        checks = tmp_path / 'runs/checks'
        checks.mkdir(exist_ok=True)
        (checks / 'audit.json').write_text(json.dumps({'comparison_passed': True,
            'actual_calls': sum('tool' in row for row in rows), 'sha256': hashlib.sha256(log.read_bytes()).hexdigest()}), encoding='utf-8')
    save()
    return rows, summary, save


def test_native_terminal_and_normal_close_bind_release_claim(tmp_path):
    _, summary, _ = case(tmp_path)
    assert package.verified_speed_run(tmp_path, 'runs/optimization/n5-example/summary.json') == summary


@pytest.mark.parametrize('damage', ['unknown', 'not_win', 'no_terminal_signal', 'wrong_profile', 'still_running', 'endless'])
def test_stated_win_does_not_override_actual_unfinished_or_other_profile(tmp_path, damage):
    rows, _, save = case(tmp_path)
    if damage == 'unknown': rows[0]['result']['state'] = 'UNKNOWN'
    if damage == 'not_win': rows[0]['result']['observation']['outcome'] = 'loss'
    if damage == 'no_terminal_signal': rows[0]['result']['completion_signal'] = 'callback_events'
    if damage == 'wrong_profile': rows[0]['result']['observation']['profile'] = 1
    if damage == 'still_running': rows[1]['result']['running'] = True
    if damage == 'endless': rows[0]['parameters']['action'] = 'continue_endless'
    save()
    with pytest.raises(AssertionError):
        package.verified_speed_run(tmp_path, 'runs/optimization/n5-example/summary.json')


def test_stale_passing_audit_cannot_certify_a_changed_log(tmp_path):
    case(tmp_path)
    with (tmp_path / 'runs/optimization/n5-example/codex-mcp.jsonl').open('a') as stream:
        stream.write(json.dumps({'step': 3, 'tool': 'observe', 'result': {}}) + '\n')
    with pytest.raises(AssertionError):
        package.verified_speed_run(tmp_path, 'runs/optimization/n5-example/summary.json')


@pytest.mark.parametrize('version', ['0.6.0', '0.6.1'])
def test_unverified_new_version_cannot_package_historical_success(tmp_path, monkeypatch, version):
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion="' + version + '"\n', encoding='utf-8')
    monkeypatch.setattr(package, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='no registered complete delivery evidence'):
        package.main()
    assert not (tmp_path / 'deliverables').exists()


def recovery_case(tmp_path):
    rows, summary, save = case(tmp_path)
    rows.insert(0, {'attempt_kind': 'fault_recovery_segment',
                    'original_attempt': 'n5-fresh-context-20261005-01'})
    rows.insert(1, {'step': 1, 'tool': 'act', 'parameters': {'action': 'continue_run'},
                    'result': {'state': 'COMPLETED'}})
    rows[2]['step'] = 2
    rows[3]['step'] = 3
    summary.update(whole_test_calls=3, terminal_step=2, close_step=3, gameplay_calls=2,
                   formal_game=False, resumed_existing_attempt=True, interrupted_attempt=True,
                   original_attempt='n5-fresh-context-20261005-01', new_random_attempts=0)
    save()
    return rows, summary, save


@pytest.mark.parametrize('outcome', ['win', 'loss'])
def test_recovery_completion_retains_interruption_for_either_native_outcome(tmp_path, outcome):
    rows, summary, save = recovery_case(tmp_path)
    rows[2]['result']['observation']['outcome'] = summary['outcome'] = outcome
    save()
    assert package.verified_fault_recovery_run(tmp_path, 'runs/optimization/n5-example/summary.json') == summary


@pytest.mark.parametrize('damage', ['formal', 'new_attempt', 'forgot_interruption', 'not_resumed', 'wrong_original', 'new_start', 'endless'])
def test_recovery_must_not_be_relabelled_a_clean_or_new_attempt(tmp_path, damage):
    rows, summary, save = recovery_case(tmp_path)
    if damage == 'formal': summary['formal_game'] = True
    if damage == 'new_attempt': summary['new_random_attempts'] = 1
    if damage == 'forgot_interruption': summary['interrupted_attempt'] = False
    if damage == 'not_resumed': summary['resumed_existing_attempt'] = False
    if damage == 'wrong_original': rows[0]['original_attempt'] = 'n5-another'
    if damage == 'new_start': rows[1]['parameters']['action'] = 'start_run'
    if damage == 'endless': rows[1]['parameters']['action'] = 'continue_endless'
    save()
    with pytest.raises(AssertionError):
        package.verified_fault_recovery_run(tmp_path, 'runs/optimization/n5-example/summary.json')


def source_check(tmp_path,monkeypatch):
    checks=tmp_path/'runs/checks';checks.mkdir(parents=True)
    snapshot=[{'path':'source.py','sha256':'a'*64}]
    report={'pytest_exit_code':0,'development_stdio_exit_code':0,
        'synthetic':{'tests':5,'failures':0,'errors':0,'skipped':0},
        'source_unchanged_during_check':True,'source_snapshot':snapshot,
        'status':{'version':'0.6.2','single_stdio_entrypoint':True,
                  'built_runtime_hashes_match':True,'fixed_downloads':[{'hash_match':True}],
                  'installed_runtime_matches_build':False}}
    monkeypatch.setattr(package,'source_snapshot',lambda root:snapshot)
    return checks/'release-check.json',report


def test_failed_checks_cannot_export_a_source_candidate(tmp_path,monkeypatch):
    path,report=source_check(tmp_path,monkeypatch)
    report['synthetic']['failures']=1
    path.write_text(json.dumps(report),encoding='utf-8')
    with pytest.raises(ValueError,match='checks are incomplete'):
        package.require_source_check(tmp_path,'0.6.2')


def test_changed_source_cannot_reuse_a_passing_report(tmp_path,monkeypatch):
    path,report=source_check(tmp_path,monkeypatch)
    report['source_snapshot']=[{'path':'source.py','sha256':'b'*64}]
    path.write_text(json.dumps(report),encoding='utf-8')
    with pytest.raises(ValueError,match='Source changed after checks'):
        package.require_source_check(tmp_path,'0.6.2')


def test_checked_candidate_does_not_require_or_claim_current_live_installation(tmp_path,monkeypatch):
    path,report=source_check(tmp_path,monkeypatch)
    path.write_text(json.dumps(report),encoding='utf-8')
    result=package.require_source_check(tmp_path,'0.6.2')
    assert result['status']['installed_runtime_matches_build'] is False


def test_recovery_keeps_host_failure_and_read_only_unknown_without_claiming_continuity(tmp_path):
    rows, summary, save = recovery_case(tmp_path)
    rows.insert(2, {'step': 4, 'tool': 'act', 'parameters': {'action': 'play'},
                   'evidence_type': 'host_tool_error_not_mcp_delivery',
                   'result': {'isError': True, 'status': 'external_tool_error'}})
    rows.insert(3, {'step': 5, 'tool': 'action_status', 'result': {'state': 'UNKNOWN', 'read_only': True}})
    rows[4]['step'], rows[5]['step'] = 6, 7
    summary.update(whole_test_calls=5, actual_mcp_deliveries=4, host_tool_errors=1,
                   terminal_step=6, close_step=7, gameplay_calls=4)
    save()
    audit_path = tmp_path / 'runs/checks/audit.json'
    audit = json.loads(audit_path.read_text())
    audit.update(actual_calls=4, host_errors=[{'counts_as_mcp_delivery': False}])
    audit_path.write_text(json.dumps(audit), encoding='utf-8')
    assert package.verified_fault_recovery_run(tmp_path, 'runs/optimization/n5-example/summary.json') == summary
    with pytest.raises(AssertionError):
        package.verified_speed_run(tmp_path, 'runs/optimization/n5-example/summary.json')


def test_submitted_unknown_cannot_be_promoted_by_a_recovery_terminal(tmp_path):
    rows, summary, save = recovery_case(tmp_path)
    rows.insert(2, {'step': 4, 'tool': 'act', 'result': {'state': 'UNKNOWN', 'submitted': True}})
    rows[3]['step'], rows[4]['step'] = 5, 6
    summary.update(whole_test_calls=4, terminal_step=5, close_step=6, gameplay_calls=3)
    save()
    with pytest.raises(AssertionError):
        package.verified_fault_recovery_run(tmp_path, 'runs/optimization/n5-example/summary.json')
