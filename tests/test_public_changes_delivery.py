"""Synthetic delivery integration; no actual game or model access."""
from copy import deepcopy
import json

import pytest

from balatro_agent.compact import expand
from balatro_agent.contract import Observation
from balatro_agent.policy import project
from balatro_agent.executor import Executor
from balatro_agent.notes import NotesService
from balatro_agent.reader import Reader
from balatro_agent.run_plan import RunPlans
from test_public_changes import observation as raw_observation


def observation(*args):
    return project(Observation.model_validate(raw_observation(*args)))


class NoGame:
    async def read(self, *args):
        raise AssertionError('Synthetic delivery must never read a game')

    async def action(self, *args):
        raise AssertionError('Synthetic delivery must never submit a game action')


def request(public, action='play', action_id='step2'):
    return {'action': action, 'action_id': action_id, 'observation_id': public['observation_id'],
            'parameters': {}, 'reason': 'Synthetic public delivery check', 'experience_refs': []}


@pytest.mark.parametrize('view', ['full', 'compact'])
def test_reader_executor_share_only_successfully_delivered_baseline(settings, view):
    reader = Reader(settings, NoGame()); executor = Executor(reader)
    first = observation()
    # Enough public cards to exercise lossless columns as well as full objects.
    first['regions'][0]['cards'] = [{**first['regions'][0]['cards'][0], 'position': i} for i in range(8)]
    assert reader._deliver('observe', {'status': 'ok', 'observation': first}, view)['public_changes']['reason'] == 'no_baseline'
    current = deepcopy(first); current['observation_id'] = observation(2)['observation_id']
    current['resources']['dollars'] = 4
    delivered = executor._deliver('act', {'state': 'COMPLETED', 'submitted': True, 'action_id': 'step2',
        'observation': current}, restore_request=request(first), view=view)
    hint = delivered['public_changes']
    assert expand(delivered)['observation'] == current
    assert hint['from_observation_id'] == first['observation_id']
    assert hint['resource_changes'] == {'dollars': {'before': 0, 'after': 4}}
    assert json.loads(executor.log.read_text(encoding='utf-8').splitlines()[-1])['value'] == delivered
    next_public = deepcopy(current); next_public['observation_id'] = observation(3)['observation_id']
    next_result = reader._deliver('observe', {'status': 'ok', 'observation': next_public}, view)
    assert next_result['public_changes']['from_observation_id'] == current['observation_id']
    assert json.loads(reader._log_file.read_text(encoding='utf-8').splitlines()[-1])['result'] == next_result
    rows = [json.loads(line) for path in reader.activity.root.glob('*.jsonl')
            for line in path.read_text(encoding='utf-8').splitlines()]
    summary = next(row for row in reversed(rows) if row['kind'] == 'changes')
    assert summary['data']['unchanged'] == next_result['public_changes']['unchanged']
    assert summary['data']['unknown'] == next_result['public_changes']['unknown']


@pytest.mark.parametrize('path', ['reader', 'executor'])
def test_failed_mandatory_delivery_clears_hint_baseline_and_preserves_action_recovery(settings, monkeypatch, path):
    reader = Reader(settings, NoGame()); executor = Executor(reader)
    first = observation(); reader._deliver('observe', {'status': 'ok', 'observation': first})
    current = observation(2)
    def fail(*args): raise OSError('Synthetic mandatory audit failure')
    with monkeypatch.context() as patch:
        if path == 'reader':
            patch.setattr(reader, '_record_delivered', fail)
            result = reader._deliver('observe', {'status': 'ok', 'observation': current})
            assert result['status'] == 'log_unavailable'
        else:
            patch.setattr(executor, '_record', fail)
            result = executor._deliver('act', {'state': 'COMPLETED', 'submitted': True,
                'action_id': 'step2', 'observation_id': first['observation_id'],
                'observation': current}, restore_request=request(first))
            assert result['state'] == 'UNKNOWN' and result['submitted'] is True
            assert executor.pending['action_id'] == 'step2' and executor.checkpoint.is_file()
    assert reader.last_delivered_observation == first
    assert reader.public_changes._baseline is None
    rows = [json.loads(line) for p in reader.activity.root.glob('*.jsonl')
            for line in p.read_text(encoding='utf-8').splitlines()]
    assert len([row for row in rows if row['kind'] == 'observation']) == 1
    if path=='executor': assert rows[-1]['data']['state']=='UNKNOWN'
    else: assert rows[-1]['data']['status']=='log_unavailable'
    latest = reader._deliver('observe', {'status': 'ok', 'observation': observation(3)})
    assert latest['public_changes']['reason'] == 'no_baseline'


@pytest.mark.parametrize('foreign_session', [False, True])
def test_historical_receipts_cannot_rewind_plan_current_observation_or_activity_targets(settings, foreign_session):
    reader = Reader(settings, NoGame()); executor = Executor(reader)
    notes = NotesService(settings); plans = RunPlans(reader, executor, notes); reader.plans = plans
    first = observation(2); first['regions'][0]['cards'][0]['name'] = 'Current card'
    executor._deliver('act', {'state': 'COMPLETED', 'submitted': True, 'action_id': 'start',
        'observation': first}, restore_request=request(first, 'start_run', 'start'))
    assert plans.write(first['observation_id'], {'objective': 'Synthetic current plan',
        'priorities': ['Review public feedback'], 'recheck_when': ['A public field changes'],
        'experience_refs': []}, 0, 'plan1')['status'] == 'ok'
    active = (plans.root/'active.json').read_bytes()
    old = observation(20)  # Unknown old receipts may even have a larger epoch.
    if foreign_session: old['observation_id'] = 'obs-fedcba9876543210-20'
    old['regions'][0]['cards'][0]['name'] = 'Historical card'
    result = executor._deliver('action_status', {'state': 'COMPLETED', 'submitted': True,
        'action_id': 'historical-query', 'observation': old})
    assert result['public_changes']['reason'] == 'historical_receipt'
    assert reader.last_delivered_observation == first and (plans.root/'active.json').read_bytes() == active
    assert plans.read()['content']['objective'] == 'Synthetic current plan'
    assert reader.activity.board['hand'][0]['name'] == 'Current card'
    rows = [json.loads(line) for p in reader.activity.root.glob('*.jsonl')
            for line in p.read_text(encoding='utf-8').splitlines()]
    assert next(row for row in reversed(rows) if row['kind'] == 'observation')['data']['historical'] is True
    latest = deepcopy(first); latest['observation_id'] = observation(3)['observation_id']
    assert reader._deliver('observe', {'status': 'ok', 'observation': latest})['public_changes']['from_observation_id'] == first['observation_id']
