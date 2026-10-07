"""An evidence-only client cannot execute game actions or overwrite history."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from client_evidence import append_call


def scene(tmp_path):
    run = 'n5-test-evidence'
    folder = tmp_path/'runs/optimization'/run
    folder.mkdir(parents=True)
    log = folder/'codex-mcp.jsonl'
    header = {'evidence_type':'codex_actual_mcp_construction','run_id':run}
    log.write_text(json.dumps(header)+'\n',encoding='utf-8')
    row = {'step':1,'tool':'observe','parameters':{},'result':{'status':'ok','observation':{'ready':True}}}
    payload = folder/'.call-0001.json'
    payload.write_text(json.dumps(row),encoding='utf-8')
    return run, log, payload, row


def test_append_exact_dto_duplicate_recovery_and_conflict(tmp_path):
    run, log, payload, row = scene(tmp_path)
    assert append_call(tmp_path, run, payload) == {'recorded_step':1,'duplicate':False,'game_called':False}
    assert json.loads(log.read_text().splitlines()[-1]) == row
    before = log.read_bytes()
    payload.write_text(json.dumps(row))
    assert append_call(tmp_path, run, payload)['duplicate']
    assert log.read_bytes() == before
    payload.write_text(json.dumps({**row,'result':{'status':'different'}}))
    with pytest.raises(ValueError, match='sequence conflict'):
        append_call(tmp_path, run, payload)
    assert payload.exists() and log.read_bytes() == before


@pytest.mark.parametrize('mutation', [
    {'step':2}, {'step':True}, {'tool':'arbitrary_lua'}, {'parameters':[]}, {'result':None},
])
def test_invalid_call_preserves_log_and_spool(tmp_path, mutation):
    run, log, payload, row = scene(tmp_path)
    before = log.read_bytes()
    payload.write_text(json.dumps({**row,**mutation}))
    with pytest.raises(ValueError):
        append_call(tmp_path, run, payload)
    assert payload.exists() and log.read_bytes() == before


def test_evidence_path_cannot_escape_registered_run(tmp_path):
    run, log, payload, row = scene(tmp_path)
    before = log.read_bytes()
    with pytest.raises(ValueError):
        append_call(tmp_path, '../outside', payload)
    elsewhere = tmp_path/'elsewhere.json'
    elsewhere.write_text(json.dumps(row))
    with pytest.raises(ValueError):
        append_call(tmp_path, run, elsewhere)
    assert log.read_bytes() == before and elsewhere.exists()
