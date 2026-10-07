"""Synthetic lost-session maintenance. No real Steam or Codex acceptance."""
import copy
import json

import httpx
import pytest

from balatro_agent.executor import Executor
from balatro_agent.reader import Reader
from balatro_agent.recovery import SessionRecovery
from balatro_agent.transport import GameClient

OLD = 'fedcba9876543210'
NEW = '0123456789abcdef'
OBS = 'obs-' + NEW + '-3'


@pytest.fixture
def recovery_case(settings, public_envelope):
    registration = json.loads(settings.profile_file.read_text())
    registration['profile'] = 2
    settings.profile_file.write_text(json.dumps(registration))
    envelope = copy.deepcopy(public_envelope)
    envelope['profile'] = 2
    methods = []
    wire = {'state': 'UNKNOWN', 'reason': 'record_not_found', 'action_id': 'lost-select',
            'game_session': NEW, 'submitted': False, 'callback_confirmed': False,
            'related_events_complete': False, 'duplicate': False}

    def process(request):
        payload = json.loads(request.content)
        methods.append(payload['method'])
        assert payload['method'] != 'act_submit', 'Recovery must never submit a game action'
        value = wire if payload['method'] == 'action_status' else envelope
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': payload['id'], 'result': value})

    reader = Reader(settings, GameClient(settings.url, 1, transport=httpx.MockTransport(process)))
    executor = Executor(reader)
    executor.pending = {'action': 'select', 'parameters': {'region': 'hand', 'positions': [0]},
                        'observation_id': 'obs-' + OLD + '-1', 'action_id': 'lost-select',
                        'reason': 'Synthetic pending selection', 'experience_refs': []}
    executor._save()
    return SessionRecovery(executor), executor, methods, envelope, wire


async def test_retirement_retains_unknown_and_durable_intent(recovery_case):
    r, e, calls, _, _ = recovery_case
    before = json.loads(e.checkpoint.read_text())
    result = await r.recover('lost-select', OBS, 'recover-1')
    assert result['state'] == 'RETIRED' and result['original_action_state'] == 'UNKNOWN'
    assert result['normal_game_completed'] is False and result['game_action_submitted'] is False
    assert e.pending is None and json.loads(e.checkpoint.read_text()) == {'pending': None, 'input_pending': None}
    record = json.loads((r.root/'recover-1.json').read_text())
    assert record['checkpoint_before'] == before
    assert calls == ['action_status', 'reader_snapshot']


async def test_duplicate_receipt_survives_service_restart(recovery_case):
    r, e, calls, _, _ = recovery_case
    result = await r.recover('lost-select', OBS, 'recover-1')
    after = list(calls)
    new = SessionRecovery(Executor(e.reader))
    duplicate = await new.recover('lost-select', OBS, 'recover-1')
    assert duplicate == {**result, 'duplicate': True}
    assert calls == after
    assert (await new.recover('another-id', OBS, 'recover-1'))['reason'] == 'id_conflict'


@pytest.mark.parametrize('change,expected', [
    ('same_session', 'session_not_lost'), ('stale', 'stale_observation'),
    ('unready', 'not_ready'), ('unknown_profile', 'observation_unavailable'),
    ('different_wire_session', 'session_loss_unconfirmed'),
    ('different_wire_id', 'session_loss_unconfirmed'), ('other_unknown', 'session_loss_unconfirmed'),
    ('running', 'session_loss_unconfirmed'), ('completed', 'session_loss_unconfirmed'),
    ('wrong_action', 'pending_action_mismatch'), ('bad_checkpoint', 'checkpoint_changed'),
])
async def test_failed_gate_never_clears_waiting(recovery_case, change, expected):
    r, e, calls, envelope, wire = recovery_case
    action_id, observation_id = 'lost-select', OBS
    if change == 'same_session': observation_id = 'obs-' + OLD + '-1'
    elif change == 'stale': observation_id = 'obs-' + NEW + '-2'
    elif change == 'unready':
        envelope['ready'] = envelope['public']['ready'] = False
        envelope['ready_reason'] = envelope['public']['ready_reason'] = 'controller_locked'
    elif change == 'unknown_profile': envelope['profile'] = None
    elif change == 'different_wire_session': wire['game_session'] = 'aaaaaaaaaaaaaaaa'
    elif change == 'different_wire_id': wire['action_id'] = 'other-id'
    elif change == 'other_unknown': wire['reason'] = 'native_error'
    elif change == 'running': wire.update(state='RUNNING', submitted=True, reason='accepted')
    elif change == 'completed':
        wire.update(state='COMPLETED', submitted=True, reason='completed', snapshot=envelope,
                    execution_profile=2,
                    callback_confirmed=True, related_events_complete=True,
                    completion_signal='callback_events')
    elif change == 'wrong_action': action_id = 'other-action'
    elif change == 'bad_checkpoint': e.checkpoint.write_text('{"pending":null,"input_pending":null}')
    result = await r.recover(action_id, observation_id, 'recover-1')
    assert result['state'] == 'REJECTED' and result['reason'] == expected
    assert e.pending is not None and not (r.root/'recover-1.json').exists()
    assert 'act_submit' not in calls


@pytest.mark.parametrize('profile',[1,2,3])
async def test_lost_session_retirement_uses_current_profile_without_registration(recovery_case,profile):
    r,e,calls,envelope,_=recovery_case
    e.reader.settings.profile_file.unlink()
    envelope['profile']=profile
    result=await r.recover('lost-select',OBS,'recover-current')
    assert result['state']=='RETIRED' and result['original_action_state']=='UNKNOWN'
    assert result['game_action_submitted'] is False and e.pending is None
    assert 'act_submit' not in calls


async def test_pending_parent_and_input_archived_together(recovery_case):
    r, e, _, _, _ = recovery_case
    e.pending.update(action='continue_run', parameters={})
    e.input_pending = {**e.pending, 'action': 'close_menu', 'action_id': 'input-step'}
    e._save()
    assert (await r.recover('lost-select', OBS, 'recover-1'))['state'] == 'RETIRED'
    record = json.loads((r.root/'recover-1.json').read_text())
    assert record['checkpoint_before']['input_pending']['action_id'] == 'input-step'
    assert e.pending is None and e.input_pending is None


@pytest.mark.parametrize('failure', ['archive', 'checkpoint'])
async def test_disk_failure_retains_waiting_and_allows_same_id_recovery(recovery_case, monkeypatch, failure):
    r, e, _, _, _ = recovery_case
    original = e._save
    def fail(*args): raise OSError('SECRET_PATH_MUST_NOT_ESCAPE')
    with monkeypatch.context() as patch:
        patch.setattr(r, '_archive', fail) if failure == 'archive' else patch.setattr(e, '_save', fail)
        result = await r.recover('lost-select', OBS, 'recover-1')
    assert result['state'] == 'REJECTED' and result['reason'] == 'journal_unavailable'
    assert 'SECRET' not in json.dumps(result) and e.pending is not None
    assert json.loads(e.checkpoint.read_text())['pending'] is not None
    assert (await r.recover('lost-select', OBS, 'recover-1'))['state'] == 'RETIRED'


async def test_lost_delivery_is_unknown_then_same_id_receipt(recovery_case, monkeypatch):
    r, e, _, _, _ = recovery_case
    def fail(*args): raise OSError('SECRET_LOG_PATH')
    with monkeypatch.context() as patch:
        patch.setattr(r.audit, 'record', fail)
        result = await r.recover('lost-select', OBS, 'recover-1')
    assert result['status'] == 'log_unavailable' and result['write_state'] == 'UNKNOWN'
    assert e.pending is None
    result = await r.recover('lost-select', OBS, 'recover-1')
    assert result['state'] == 'RETIRED' and result['duplicate'] is True


async def test_serialization_and_path_traversal_rejection(recovery_case):
    r, e, calls, _, _ = recovery_case
    await e.reader._tool_lock.acquire()
    try:
        assert (await r.recover('lost-select', OBS, 'recover-1'))['reason'] == 'action_busy'
    finally:
        e.reader._tool_lock.release()
    assert (await r.recover('lost-select', OBS, '../outside'))['reason'] == 'invalid_request'
    assert calls == [] and e.pending


async def test_private_changes_do_not_enter_archive_or_response(recovery_case):
    r, e, _, envelope, wire = recovery_case
    envelope['seed'] = 'SECRET_SEED'
    envelope['public']['internal'] = 'SECRET_FUTURE'
    envelope['public']['regions'][0]['cards'][0]['key'] = 'SECRET_ID'
    wire['internal'] = 'SECRET_RESPONSE'
    result = await r.recover('lost-select', OBS, 'recover-1')
    assert result['state'] == 'RETIRED'
    assert 'SECRET' not in (r.root/'recover-1.json').read_text()


async def test_tampered_duplicate_never_exports_unrecognized_text(recovery_case):
    r, _, _, _, _ = recovery_case
    assert (await r.recover('lost-select', OBS, 'recover-1'))['state'] == 'RETIRED'
    path = r.root/'recover-1.json'
    record = json.loads(path.read_text())
    record['response']['hidden'] = 'SECRET_FUTURE'
    path.write_text(json.dumps(record))
    result = await r.recover('lost-select', OBS, 'recover-1')
    assert result['state'] == 'REJECTED' and 'SECRET' not in json.dumps(result)


@pytest.mark.parametrize('gate', ['checkpoint_broken', 'no_pending', 'lifecycle_busy', 'disconnected'])
async def test_additional_fail_closed_gates(recovery_case, gate):
    from types import SimpleNamespace
    from balatro_agent.transport import ReaderError
    r, e, calls, _, _ = recovery_case
    if gate == 'checkpoint_broken': e.checkpoint_broken = True
    elif gate == 'no_pending': e.pending = None
    elif gate == 'lifecycle_busy': e.lifecycle = SimpleNamespace(blocks_actions=lambda: True)
    else:
        async def disconnected(*args): raise ReaderError('disconnected')
        e._query = disconnected
    expected = {'checkpoint_broken': 'checkpoint_unavailable', 'no_pending': 'pending_action_mismatch',
                'lifecycle_busy': 'operation_busy', 'disconnected': 'transport_uncertain'}[gate]
    result = await r.recover('lost-select', OBS, 'recover-1')
    assert result['state'] == 'REJECTED' and result['reason'] == expected
    assert not (r.root/'recover-1.json').exists()
    assert calls == []
