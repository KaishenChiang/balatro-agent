"""Archive proof must preserve UNKNOWN and exact request/response binding."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from balatro_agent.local_audit import canonical

spec=importlib.util.spec_from_file_location('delivery_audit',Path(__file__).resolve().parents[1]/'scripts/audit_experience_mcp_evidence.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def case(tmp_path):
    old='1111111111111111';new='2222222222222222'
    request={'action_id':'lost','observation_id':f'obs-{new}-2','recovery_id':'retire'}
    response={'state':'RETIRED','reason':'lost_session_archived','recovery_id':'retire','action_id':'lost',
        'original_action_state':'UNKNOWN','old_session':old,'current_session':new,'submitted':False,
        'game_action_submitted':False,'read_only':False,'normal_game_completed':False,'duplicate':False,'write_state':'COMMITTED'}
    before={'pending':{'action_id':'lost','observation_id':f'obs-{old}-1'},'input_pending':None}
    archive={'request':request,'response':response,'checkpoint_before':before,
        'checkpoint_sha256':hashlib.sha256(canonical(before).encode()).hexdigest(),
        'current_observation':{'profile':2,'ready':True,'observation_id':request['observation_id']},
        'queried_status':{'state':'UNKNOWN','reason':'record_not_found','action_id':'lost','game_session':new}}
    path=tmp_path/'runs/live/executor/retired-sessions/retire.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps(archive),encoding='utf-8')
    return {'parameters':copy.deepcopy(request),'result':copy.deepcopy(response)},path,archive


@pytest.mark.parametrize('duplicate',[False,True])
def test_committed_retirement_binds_archive_even_for_duplicate(tmp_path,duplicate):
    row,path,_=case(tmp_path);row['result']['duplicate']=duplicate
    receipt,error=audit.retirement_receipt(tmp_path,row)
    assert error is None and receipt['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert row['result']['original_action_state']=='UNKNOWN'


@pytest.mark.parametrize('damage',['missing','request','checkpoint','query','completion'])
def test_delivered_ack_without_consistent_archive_fails(tmp_path,damage):
    row,path,archive=case(tmp_path)
    if damage=='missing':path.unlink()
    else:
        if damage=='request':archive['request']['action_id']='other'
        if damage=='checkpoint':archive['checkpoint_before']['pending']['action_id']='other'
        if damage=='query':archive['queried_status']['state']='COMPLETED'
        if damage=='completion':archive['response']['normal_game_completed']=True
        path.write_text(json.dumps(archive),encoding='utf-8')
    assert audit.retirement_receipt(tmp_path,row)==(None,'missing_or_inconsistent_retirement_receipt')


def test_only_explicit_host_error_is_excluded_from_mcp_comparison():
    row={'evidence_type':'host_tool_error_not_mcp_delivery','result':{'status':'external_tool_error','isError':True}}
    assert audit.host_error(row)
    assert not audit.host_error({'result':row['result']})
    assert not audit.host_error({**row,'result':{'status':'error','isError':True}})


def test_health_wrapper_constants_do_not_mask_state_or_unknown_metadata():
    old={'status':'ok','profile':2,'ready':True}
    newer={**old,'unlock_input_protocol':'native-overlay-v1'}
    assert audit.comparison_value('health',old)==audit.comparison_value('health',newer)
    assert audit.comparison_value('health',old)!=audit.comparison_value('health',{**newer,'ready':False})
    assert audit.comparison_value('health',old)!=audit.comparison_value('health',{**newer,'unknown':'extra'})
    with pytest.raises(AssertionError):
        audit.comparison_value('health',{**old,'unlock_input_protocol':'unexpected'})


def test_json_number_spelling_does_not_lose_actual_delivery():
    recorded = {'state': 'COMPLETED', 'timing': {'transport_wait_ms': 50.0},
                'observation': {'resources': {'dollars': 32}}}
    actual = json.loads(json.dumps(recorded).replace('50.0', '50'))
    assert audit.comparison_value('act', recorded) == audit.comparison_value('act', actual)
    assert recorded['timing']['transport_wait_ms'] == 50.0
    for timing in (50.001, True, '50', None):
        changed = copy.deepcopy(actual)
        changed['timing']['transport_wait_ms'] = timing
        assert audit.comparison_value('act', recorded) != audit.comparison_value('act', changed)
    assert audit.comparison_value('act', {'n': 1}) != audit.comparison_value('act', {'n': True})
    assert audit.comparison_value('act', {'n': 9007199254740993}) != audit.comparison_value('act', {'n': float(9007199254740993)})


def test_action_journal_index_uses_the_same_numeric_comparison(tmp_path, monkeypatch):
    request = {'action': 'select', 'parameters': {'region': 'jokers', 'positions': [0]},
               'observation_id': 'obs-2222222222222222-2', 'action_id': 'numeric-case',
               'reason': 'select a public target', 'experience_refs': []}
    result = {'action_id': 'numeric-case', 'state': 'COMPLETED', 'submitted': True,
              'timing': {'transport_wait_ms': 50}}
    evidence = tmp_path / 'runs/optimization/numeric/codex-mcp.jsonl'
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({'evidence_type': 'codex_actual_mcp_construction'}) + '\n' +
                        json.dumps({'tool': 'act', 'parameters': request, 'result': result}) + '\n', encoding='utf-8')
    journal = tmp_path / 'runs/live/executor/actions-numeric.jsonl'
    journal.parent.mkdir(parents=True)
    delivered = copy.deepcopy(result)
    delivered['timing']['transport_wait_ms'] = 50.0
    journal.write_text('\n'.join(json.dumps(row) for row in [
        {'client_context': 'codex_config', 'kind': 'intent', 'utc': '2026-10-05T00:00:00Z', 'value': {'request': request}},
        {'client_context': 'codex_config', 'kind': 'delivered_act', 'utc': '2026-10-05T00:00:01Z', 'value': delivered},
    ]) + '\n', encoding='utf-8')
    before = evidence.read_bytes()
    (tmp_path / 'runs/checks').mkdir(parents=True)
    monkeypatch.setattr(audit, 'ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['audit', '--evidence', 'runs/optimization/numeric/codex-mcp.jsonl',
                                  '--output', 'runs/checks/numeric.json'])
    assert audit.main() == 0
    checked = json.loads((tmp_path / 'runs/checks/numeric.json').read_text(encoding='utf-8'))
    assert checked['comparison_passed'] and checked['actual_calls'] == 1
    assert checked['matches'][0]['intent']['line'] == 1
    assert evidence.read_bytes() == before
