"""Synthetic public context, disk memory and MCP contracts; never play a game."""
import copy
import json
import subprocess
import sys
from dataclasses import replace

import pytest
from mcp import Client

from balatro_agent.compact import columns, expand, present
from balatro_agent.contract import Envelope
from balatro_agent.executor import Executor
from balatro_agent.notes import NotesService
from balatro_agent.policy import canonical
from balatro_agent.reader import Reader
from balatro_agent.run_plan import RunPlans


class NoGame:
    async def read(self, *args):
        raise AssertionError('test must not read a game')

    async def action(self, *args):
        raise AssertionError('test must not act in a game')


def note_content(text='Synthetic condition'):
    return {'sources': [{'run_id': 'n5-synthetic-context', 'steps': [1]}], 'facts': [text],
            'interpretation': ['Synthetic memory test, no strategy.'], 'conditions': [text],
            'counterexamples': ['No real game evidence.'], 'confidence': 'low', 'revision_reason': text}


@pytest.fixture
def context(settings, public_envelope):
    reader = Reader(settings, NoGame())
    executor = Executor(reader)
    notes = NotesService(settings)
    plans = RunPlans(reader, executor, notes)
    reader.plans = plans
    public = reader.project_envelope(Envelope.model_validate(public_envelope))['observation']
    # In real runs the deck/stake are observed even outside run setup pages.
    public['setup'].update(availability='observed', deck_name='Red Deck', stake_name='White Stake')
    request = {'action': 'start_run', 'action_id': 'synthetic-start-1', 'parameters': {},
               'reason': 'synthetic context receipt', 'experience_refs': [],
               'observation_id': public['observation_id']}
    # This receipt tests context scoping only, not native action completion.
    executor._deliver('act', {'state': 'COMPLETED', 'action_id': request['action_id'],
                             'submitted': True, 'observation': public}, restore_request=request)
    content = {'objective': 'Synthetic bounded plan', 'priorities': ['Reuse the observed constraint'],
               'recheck_when': ['The public constraint changes'], 'experience_refs': []}
    return reader, executor, notes, plans, public, content, request


@pytest.mark.parametrize('phase', ['hand', 'shop', 'pack', 'blind_select', 'menu', 'terminal'])
def test_compact_roundtrip_keeps_all_public_fields_and_unknowns(settings, public_envelope, phase):
    raw = copy.deepcopy(public_envelope)
    raw['phase'] = raw['public']['phase'] = phase
    card = raw['public']['regions'][0]['cards'][0]
    raw['public']['regions'][0]['cards'] = [{**card, 'position': i} for i in range(8)]
    reader = Reader(settings, NoGame())
    full = reader.project_envelope(Envelope.model_validate(raw))
    compact = present(full, 'compact')
    assert compact['observation_encoding'] == 'columns-v1'
    assert expand(compact['observation']) == full['observation']
    assert len(canonical(compact).encode('utf-8')) < len(canonical(full).encode('utf-8'))
    assert compact['observation']['observation_id'] == full['observation']['observation_id']
    assert expand(compact['observation'])['resources']['ante'] is None
    assert full['observation']['regions'][0]['cards'][0]['position'] == 0


@pytest.mark.parametrize('visibility', ['face_down', 'stone', 'undiscovered'])
def test_compact_preserves_hidden_mask_and_heterogeneous_missing_fields(settings, public_envelope, visibility):
    raw = copy.deepcopy(public_envelope)
    card = raw['public']['regions'][0]['cards'][0]
    raw['public']['regions'][0]['cards'] = [
        {**card, 'position': i, 'visibility': visibility if i == 3 else 'face_up',
         'seed': 'SECRET', 'native_id': 'SECRET', 'rank': 'Ace', 'suit': 'Spades'} for i in range(8)]
    full = Reader(settings, NoGame()).project_envelope(Envelope.model_validate(raw))
    compact = present(full, 'compact')
    assert expand(compact['observation']) == full['observation']
    masked = expand(compact['observation'])['regions'][0]['cards'][3]
    assert 'SECRET' not in canonical(compact)
    if visibility == 'face_down':
        assert masked == {'position': 3, 'visibility': 'face_down', 'selected': False}
    else:
        assert masked['rank'] is None and masked['suit'] is None


def test_short_arrays_never_grow_and_columns_are_strict():
    for size in range(7):
        value = [{'x': i, 'different' if i % 2 else 'field': None} for i in range(size)]
        assert expand(columns(value)) == value
        assert len(canonical(columns(value))) <= len(canonical(value))
    with pytest.raises(ValueError, match='invalid_columns'):
        expand({'$columns': ['position'], '$rows': [[0, 1]]})


async def test_invalid_view_cannot_read_or_submit(context):
    reader, executor, _, _, public, _, _ = context
    assert (await reader.observe('SECRET'))['status'] == 'invalid_view'
    assert (await reader.wait_until_ready(view='SECRET'))['status'] == 'invalid_view'
    result = await executor.act('play', {'positions': [0]}, public['observation_id'], 'test', 'test', [], 'SECRET')
    assert result['state'] == 'REJECTED' and not result['submitted']
    assert (await executor.action_status('test', view='SECRET'))['state'] == 'REJECTED'


def test_index_is_literal_bounded_discovery_and_actual_disk_read(context):
    _, _, notes, _, _, _, _ = context
    for index in range(21):
        assert notes.write_note(f'EXP-TOPIC-{index:02}', note_content('Alpha'*35), 0, f'index-{index}')['status'] == 'ok'
    first = notes.read_notes(view='index', query='aLPHa')
    assert first['discovery_only'] and first['total_matches'] == 21 and first['next_offset'] == 20
    assert len(first['notes']) == 20 and first['notes'][0]['preview_only']
    assert len(first['notes'][0]['fact_preview']) == 120
    assert not notes.read_refs
    second = notes.read_notes(view='index', query='alpha', offset=first['next_offset'])
    assert len(second['notes']) == 1 and second['next_offset'] is None
    assert notes.read_notes(view='index', query='.*')['notes'] == []
    note = notes.read_notes(note_ids=['EXP-TOPIC-00'], view='content')['notes'][0]
    assert notes.read_refs == {'EXP-TOPIC-00@r1'}
    changed = note_content('Beta new disk revision')
    assert notes.write_note('EXP-TOPIC-00', changed, 1, 'index-revise')['status'] == 'ok'
    assert notes.read_notes(view='index', query='Beta')['notes'][0]['note_ref'] == 'EXP-TOPIC-00@r2'


@pytest.mark.parametrize('kwargs', [{'view': 'content', 'query': 'x'}, {'view': 'index', 'query': 'x'*81},
                                    {'view': 'index', 'offset': True}, {'view': 'index', 'offset': -1}])
def test_invalid_index_requests_fail_without_echo(context, kwargs):
    notes = context[2]
    assert notes.read_notes(**kwargs)['status'] == 'invalid_input'


def test_plan_persistence_duplicates_and_revision_conflicts(context):
    reader, executor, notes, plans, public, content, _ = context
    assert plans.read()['revision'] == 0
    first = plans.write(public['observation_id'], content, 0, 'plan-1')
    assert first['write_state'] == 'COMMITTED' and not first['game_action_submitted']
    assert plans.write(public['observation_id'], content, 0, 'plan-1')['duplicate']
    changed = {**content, 'objective': 'Changed public constraint'}
    assert plans.write(public['observation_id'], changed, 0, 'plan-1')['status'] == 'id_conflict'
    assert plans.write(public['observation_id'], changed, 0, 'plan-2')['status'] == 'revision_conflict'
    assert plans.write(public['observation_id'], changed, 1, 'plan-2')['revision'] == 2
    fresh = RunPlans(reader, executor, notes)
    assert fresh.read()['content'] == changed
    assert len(fresh._history()) == 2
    # A separate interpreter must read the committed plan, not an in-memory copy.
    code = ('import json,sys; from pathlib import Path; from types import SimpleNamespace; '
            'from balatro_agent.settings import Settings; from balatro_agent.reader import Reader; '
            'from balatro_agent.run_plan import RunPlans; '
            'r=Reader(Settings(log_dir=Path(sys.argv[1]))); r.last_delivered_observation=json.loads(sys.argv[2]); '
            'p=RunPlans(r,SimpleNamespace(),SimpleNamespace()); print(json.dumps(p.read()))')
    independent = json.loads(subprocess.check_output([sys.executable, '-c', code,
        str(reader.settings.log_dir), canonical(public)], text=True))
    assert independent['revision'] == 2 and independent['content'] == changed


def test_plan_ref_requires_full_delivered_experience(context):
    _, _, notes, plans, public, content, _ = context
    assert notes.write_note('EXP-SYNTHETIC', note_content(), 0, 'note-1')['status'] == 'ok'
    content['experience_refs'] = ['EXP-SYNTHETIC@r1']
    notes.read_notes(view='index')
    assert plans.write(public['observation_id'], content, 0, 'plan-1')['status'] == 'unread_experience'
    notes.read_notes(note_ids=['EXP-SYNTHETIC'], view='content')
    assert plans.write(public['observation_id'], content, 0, 'plan-1')['write_state'] == 'COMMITTED'


@pytest.mark.parametrize('pending', ['pending', 'input_pending', 'checkpoint_broken'])
def test_plan_cannot_bypass_unknown_checkpoint(context, pending):
    _, executor, _, plans, public, content, _ = context
    setattr(executor, pending, True)
    result = plans.write(public['observation_id'], content, 0, 'plan-1')
    assert result['status'] == 'action_pending' and getattr(executor, pending) is True


@pytest.mark.parametrize('change', ['new_run', 'profile', 'session', 'setup', 'menu', 'decreasing_round'])
def test_old_plan_is_never_reused_across_observed_run_boundaries(context, change):
    reader, executor, notes, plans, public, content, request = context
    plans.write(public['observation_id'], content, 0, 'plan-1')
    old = plans._path().read_bytes()
    observation = copy.deepcopy(public)
    observation['observation_id'] = 'obs-0123456789abcdef-4'
    new_request = None
    if change == 'new_run':
        new_request = {**request, 'action_id': 'synthetic-start-2'}
    elif change == 'profile':
        observation['profile'] = 2
    elif change == 'session':
        observation['observation_id'] = 'obs-abcdef0123456789-4'
    elif change == 'setup':
        observation['setup']['page'] = 'deck_choice'
    elif change == 'menu':
        observation['phase'] = 'main_menu'
    else:
        previous = {**public, 'resources': {**public['resources'], 'round': 5}}
        reader._deliver('observe', {'observation': previous})
        observation['resources']['round'] = 1
    result = {'observation': observation, 'state': 'COMPLETED', 'submitted': True,
              'action_id': new_request['action_id'] if new_request else 'synthetic-other'}
    executor._deliver('act', result, restore_request=new_request)
    read = plans.read()
    assert read.get('content') is None
    assert read.get('revision') == 0 if change == 'new_run' else read['status'] == 'run_scope_missing'
    paths = [p for p in plans.root.glob('obs-*.json')]
    assert any(path.read_bytes() == old for path in paths)
    assert RunPlans(reader, executor, notes).read().get('content') is None


def test_plan_storage_failure_cannot_relabel_completed_native_action(context, monkeypatch):
    _, executor, _, plans, public, _, request = context
    def fail(*args):
        raise OSError('SECRET_PATH')
    monkeypatch.setattr(plans, '_atomic', fail)
    receipt = {'state': 'COMPLETED', 'submitted': True, 'action_id': 'synthetic-start-2', 'observation': public}
    result = executor._deliver('act', receipt, restore_request={**request, 'action_id': 'synthetic-start-2'})
    assert result['state'] == 'COMPLETED' and result['run_plan_status'] == 'storage_unavailable'
    assert 'SECRET' not in canonical(result)


def test_visible_deck_and_stake_do_not_invalidate_a_run_plan(context):
    reader, _, _, plans, public, content, _ = context
    plans.write(public['observation_id'], content, 0, 'plan-1')
    result = reader._deliver('observe', {'status': 'ok', 'observation': {
        **public, 'observation_id': 'obs-0123456789abcdef-4'}})
    assert result['run_plan_ref']['revision'] == 1
    assert plans.read()['content'] == content


def test_legitimate_ante_decrease_does_not_discard_the_current_plan(context):
    reader, _, _, plans, public, content, _ = context
    plans.write(public['observation_id'], content, 0, 'plan-1')
    reader._deliver('observe', {'observation': {**public, 'resources': {**public['resources'], 'ante': 3, 'round': 5}}})
    result = reader._deliver('observe', {'observation': {**public, 'resources': {**public['resources'], 'ante': 2, 'round': 5}}})
    assert result['run_plan_ref']['revision'] == 1 and plans.read()['content'] == content


def test_plan_log_failure_after_commit_returns_unknown_and_can_read_back(context, monkeypatch):
    _, _, _, plans, public, content, _ = context
    original = plans.audit.record
    def fail(tool, kind, value):
        if kind == 'delivered':
            raise OSError('SECRET_PATH')
        original(tool, kind, value)
    monkeypatch.setattr(plans.audit, 'record', fail)
    result = plans.write(public['observation_id'], content, 0, 'plan-1')
    assert result['write_state'] == 'UNKNOWN' and 'SECRET' not in canonical(result)
    monkeypatch.setattr(plans.audit, 'record', original)
    assert plans.read()['content'] == content
    assert plans.write(public['observation_id'], content, 0, 'plan-1')['duplicate']


@pytest.mark.parametrize('content', [{'objective': 'SECRET'}, {'objective': 'x', 'priorities': ['x'],
    'recheck_when': ['x'], 'experience_refs': [], 'hidden': 'SECRET'}, {'objective': 'x',
    'priorities': ['x'*201], 'recheck_when': ['x'], 'experience_refs': []}])
def test_invalid_plans_are_not_written_or_echoed(context, content):
    _, _, _, plans, public, _, _ = context
    result = plans.write(public['observation_id'], content, 0, 'plan-1')
    assert result['status'] == 'invalid_input' and 'SECRET' not in canonical(result)
    assert not plans._path().exists()


def test_corrupt_plan_file_fails_closed_without_echo(context):
    reader, executor, notes, plans, public, content, _ = context
    plans.write(public['observation_id'], content, 0, 'plan-1')
    plans._path().write_text('SECRET_CORRUPTION', encoding='utf-8')
    result = RunPlans(reader, executor, notes).read()
    assert result['status'] == 'store_corrupt' and 'SECRET' not in canonical(result)


@pytest.mark.parametrize('value', [None, 17, [], {'schema_version': 'run-plan-v1', 'scope': 0}])
def test_malformed_active_plan_cannot_prevent_service_initialization(context, value):
    reader, executor, notes, _, public, _, _ = context
    path = reader.settings.log_dir / 'run-plans/active.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    before = path.read_bytes()
    fresh = RunPlans(reader, executor, notes)
    assert fresh.read()['status'] == 'store_corrupt'
    assert fresh.attach({'state': 'COMPLETED', 'observation': public})['state'] == 'COMPLETED'
    assert path.read_bytes() == before


@pytest.mark.parametrize('damage', ['null_history', 'invalid_timestamp', 'invalid_cursor'])
def test_corrupt_plan_metadata_is_isolated_from_native_actions(context, damage):
    reader, executor, notes, plans, public, content, _ = context
    plans.write(public['observation_id'], content, 0, 'plan-1')
    if damage == 'invalid_cursor':
        path = plans.root / 'active.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['continuity']['profile'] = 2
    else:
        path = plans._path()
        data = None if damage == 'null_history' else json.loads(path.read_text(encoding='utf-8'))
        if damage == 'invalid_timestamp':
            data['revisions'][0]['created_utc'] = None
    path.write_text(json.dumps(data), encoding='utf-8')
    fresh = RunPlans(reader, executor, notes)
    assert fresh.read()['status'] == 'store_corrupt'
    assert fresh.attach({'state': 'COMPLETED', 'observation': public})['run_plan_status'] == 'store_corrupt'
    assert executor.pending is None and not executor.checkpoint_broken


@pytest.mark.parametrize('next_round', [1, 5, 6])
def test_restart_requires_confirmed_continuity_before_reusing_a_plan(context, next_round):
    reader, executor, notes, plans, public, content, _ = context
    plans.write(public['observation_id'], content, 0, 'plan-1')
    previous = {**public, 'observation_id': 'obs-0123456789abcdef-5',
                'resources': {**public['resources'], 'round': 5}}
    reader._deliver('observe', {'observation': previous})
    old_history = plans._path().read_bytes()
    fresh = RunPlans(reader, executor, notes)
    assert fresh.progress == {'round': 5}
    reader.plans = fresh
    changed = {**previous, 'observation_id': 'obs-0123456789abcdef-10',
               'resources': {**previous['resources'], 'round': next_round}}
    result = reader._deliver('observe', {'observation': changed})
    assert 'run_plan_ref' not in result and result['run_plan_status'] == 'run_scope_missing'
    assert fresh.read()['status'] == 'run_scope_missing'
    assert any(path.read_bytes() == old_history for path in fresh.root.glob('obs-*.json'))


def test_unchanged_public_observation_restores_plan_after_restart(context):
    reader, executor, notes, plans, public, content, _ = context
    plans.write(public['observation_id'], content, 0, 'plan-1')
    reader.plans = fresh = RunPlans(reader, executor, notes)
    result = reader._deliver('observe', {'observation': public})
    assert result['run_plan_ref']['revision'] == 1
    assert fresh.read()['content'] == content


def test_legacy_plan_without_continuity_is_preserved_but_not_reused(context):
    reader, executor, notes, plans, public, content, _ = context
    plans.write(public['observation_id'], content, 0, 'plan-1')
    history = plans._path().read_bytes()
    path = plans.root / 'active.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    del data['continuity']
    path.write_text(json.dumps(data), encoding='utf-8')
    reader.plans = fresh = RunPlans(reader, executor, notes)
    reader._deliver('observe', {'observation': public})
    assert fresh.read()['status'] == 'run_scope_missing'
    assert any(path.read_bytes() == history for path in fresh.root.glob('obs-*.json'))


@pytest.mark.parametrize('receipt', ['old_start', 'old_setup', 'duplicate_start'])
def test_historical_receipt_does_not_clear_current_plan_or_current_observation(context, receipt):
    reader, executor, _, plans, public, content, request = context
    plans.write(public['observation_id'], content, 0, 'plan-1')
    latest = {**public, 'observation_id': 'obs-0123456789abcdef-8',
              'resources': {**public['resources'], 'round': 5}}
    reader._deliver('observe', {'observation': latest})
    old = copy.deepcopy(public)
    if receipt == 'old_setup':
        old['phase'] = 'menu'
        old['setup']['page'] = 'deck_choice'
    before = (plans.root / 'active.json').read_bytes()
    result = executor._deliver('action_status', {'state': 'COMPLETED', 'submitted': True,
        'action_id': request['action_id'], 'duplicate': receipt == 'duplicate_start', 'observation': old},
        restore_request=request if receipt == 'duplicate_start' else None)
    assert result['state'] == 'COMPLETED' and result['run_plan_status'] == 'stale_observation'
    assert reader.last_delivered_observation == latest
    assert (plans.root / 'active.json').read_bytes() == before
    assert plans.read()['content'] == content and plans.progress == {'round': 5}


@pytest.mark.parametrize('callback', [True, False])
async def test_fast_polling_returns_only_confirmed_completion(settings, public_envelope, monkeypatch, callback):
    import balatro_agent.executor as module
    delays, calls = [], []
    async def sleep(delay):
        delays.append(delay)
    monkeypatch.setattr(module.asyncio, 'sleep', sleep)
    config = replace(settings, poll_interval_s=.2)
    class SyntheticGame:
        async def action(self, method, parameters):
            calls.append(method)
            completed = method == 'action_status'
            return {'state': 'COMPLETED' if completed else 'RUNNING',
                'reason': 'completed' if completed else 'accepted', 'action_id': 'synthetic-poll',
                'observation_id': public_envelope['observation_id'], 'game_session': public_envelope['game_session'],
                'submitted': True, 'execution_profile': 3,
                'callback_confirmed': callback if completed else False, 'related_events_complete': completed,
                'completion_signal': 'callback_events' if completed else None,
                'snapshot': public_envelope if completed else None}
    reader = Reader(config, SyntheticGame())
    reader.project_envelope(Envelope.model_validate(public_envelope))
    executor = Executor(reader)
    result = await executor.act('play', {'positions': [0]}, public_envelope['observation_id'],
                                'synthetic-poll', 'synthetic public test', [], 'compact')
    assert calls == ['act_submit', 'action_status'] and 0 < delays[0] <= .05 < config.poll_interval_s
    if callback:
        assert result['state'] == 'COMPLETED' and executor.pending is None
    else:
        assert result['state'] == 'UNKNOWN' and executor.pending
        assert (await executor.act('play', {'positions': [0]}, public_envelope['observation_id'],
            'different-id', 'test', []))['reason'] == 'action_busy'
        assert calls.count('act_submit') == 1


async def test_mcp_exposes_compact_notes_index_and_plan_roundtrip(context, monkeypatch):
    import balatro_agent.server as server
    reader, executor, notes, plans, public, content, _ = context
    for name, value in [('reader', reader), ('executor', executor), ('notes', notes), ('plans', plans)]:
        monkeypatch.setattr(server, name, value)
    notes.write_note('EXP-SYNTHETIC', note_content(), 0, 'note-1')
    async with Client(server.mcp) as client:
        index = (await client.call_tool('read_notes', {'view': 'index'})).structured_content
        assert index['discovery_only'] and not notes.read_refs
        full = (await client.call_tool('read_notes', {})).structured_content
        assert 'markdown' not in full['notes'][0]
        content['experience_refs'] = ['EXP-SYNTHETIC@r1']
        written = (await client.call_tool('run_plan', {'mode': 'write', 'observation_id': public['observation_id'],
            'content': content, 'expected_revision': 0, 'write_id': 'mcp-plan-1'})).structured_content
        assert written['write_state'] == 'COMMITTED'
        read = (await client.call_tool('run_plan', {})).structured_content
        assert read['content'] == content
        assert reader.last_delivered_observation == public
        class PublicOnly:
            async def read(self, method, timeout):
                shown = copy.deepcopy(public)
                card = shown['regions'][0]['cards'][0]
                shown['regions'][0]['cards'] = [{**card, 'position': i} for i in range(8)]
                return {'schema_version': 'reader-2', 'visibility_policy_version': 'player-visible-1',
                    'adapter_version': '0.3.0', 'upstream_commit': '9052d76f14723293f6c6b2cecaa791a5c4ae68f3',
                    'upstream_mod_version': '1.5.1', 'game_version': '1.0.1o-FULL', 'profile': 3,
                    'phase': 'hand', 'ready': True, 'ready_reason': 'ui_operable', 'compatibility': 'supported',
                    'game_session': '0123456789abcdef', 'observation_id': shown['observation_id'], 'public': shown}
        reader.client = PublicOnly()
        compact = (await client.call_tool('observe', {})).structured_content
        traditional = (await client.call_tool('observe', {'view': 'full'})).structured_content
        assert compact['observation_encoding'] == 'columns-v1'
        assert expand(compact['observation']) == traditional['observation']
        assert compact['run_plan_ref']['revision'] == 1 and 'content' not in compact['run_plan_ref']
        delivered = [json.loads(line)['result'] for line in reader._log_file.read_text(encoding='utf-8').splitlines()]
        assert delivered[-2] == compact and delivered[-1] == traditional


def test_plan_write_and_duplicate_have_matching_audit_records(context, monkeypatch):
    import importlib.util
    from pathlib import Path
    import shutil
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('synthetic_plan_audit', root/'scripts/audit_experience_mcp_evidence.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    reader, _, _, plans, public, content, _ = context
    # Synthetic label exercises the audit filter, not a real Codex invocation.
    plans.audit.context = 'codex_config'
    request = {'mode': 'write', 'observation_id': public['observation_id'], 'content': content,
               'expected_revision': 0, 'write_id': 'audit-plan-1'}
    result = plans.write(**{key: value for key, value in request.items() if key != 'mode'})
    duplicate = plans.write(**{key: value for key, value in request.items() if key != 'mode'})
    local_root = reader.settings.log_dir.parent
    journal = local_root/'runs/live/local'
    journal.mkdir(parents=True)
    for path in plans.audit.root.glob('*.jsonl'):
        shutil.copy2(path, journal/path.name)
    evidence = local_root/'runs/checks/codex-mcp-synthetic-plan.jsonl'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text('\n'.join(canonical(row) for row in [
        {'evidence_type': 'codex_actual_mcp_construction', 'synthetic_fixture': True, 'formal_game': False},
        {'tool': 'run_plan', 'parameters': request, 'result': result},
        {'tool': 'run_plan', 'parameters': request, 'result': duplicate}])+'\n', encoding='utf-8')
    monkeypatch.setattr(audit, 'ROOT', local_root)
    monkeypatch.setattr(sys, 'argv', ['audit', '--evidence', str(evidence.relative_to(local_root)),
                                    '--output', 'runs/checks/audit.json'])
    assert audit.main() == 0
    checked = json.loads((evidence.parent/'audit.json').read_text(encoding='utf-8'))
    assert checked['comparison_passed'] and len(checked['matches']) == 2
