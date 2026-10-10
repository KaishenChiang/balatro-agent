"""Optional, bounded summaries of delivered public data and model submissions.

The viewer is an independent read-only consumer. No game or model calls here.
Failure to record or open it must never change a tool result or a checkpoint.
"""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import uuid

from .compact import expand
from .local_audit import canonical, make_dir, safe_path

SCHEMA = 'activity-v1'
ROOT = Path(__file__).resolve().parents[2]
TEXT_PROTOCOL = 'bilingual-tags-v1'


def text(value, limit=180):
    if not isinstance(value, str):
        return None
    value = ' '.join(value.split())
    return value[:limit] + ('…' if len(value) > limit else '')


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def bilingual(value, limit=120):
    """Extract model-submitted translations before truncation; never translate."""
    if not isinstance(value, str) or len(value) > 1024:
        return {}
    if len(re.findall(r'\[(?:en|zh-CN)\]', value)) != 2:
        return {}
    match = re.fullmatch(r'\s*\[(en|zh-CN)\]\s*(.*?)\s*\[(en|zh-CN)\]\s*(.*?)\s*', value, re.S)
    if not match or match[1] == match[3] or not match[2].strip() or not match[4].strip():
        return {}
    return {match[1]: text(match[2], limit), match[3]: text(match[4], limit)}


class ActivityJournal:
    def __init__(self, settings):
        self.root = settings.log_dir / 'activity'
        self.context = settings.client_context
        self.session = uuid.uuid4().hex
        self.sequence = 0
        self.last = {}
        self.latest_observation = None
        self.board = {}
        self.actions = {}

    def emit(self, kind, tool, data):
        """Best effort only; the mandatory audit remains authoritative."""
        try:
            key = (kind, tool, data.get('action_id'))
            signature = canonical(data)
            if self.last.get(key) == signature:
                return
            row = {'schema': SCHEMA, 'session': self.session, 'sequence': self.sequence + 1,
                   'utc': datetime.now(timezone.utc).isoformat(), 'kind': kind,
                   'tool': tool, 'data': data}
            encoded = canonical(row)
            if len(encoded.encode('utf-8')) > 16384:
                return
            make_dir(self.root)
            path = safe_path(self.root, 'events-' + self.session + '.jsonl')
            with path.open('a', encoding='utf-8') as stream:
                stream.write(encoded + '\n')
            self.sequence += 1
            self.last[key] = signature
            if len(self.last) > 256:
                self.last.pop(next(iter(self.last)))
        except Exception:
            pass

    def intent(self, request):
        from .actions import ActionRequest
        try:
            value = ActionRequest.model_validate(request).model_dump()
            parameters = value['parameters']
            data = {'action': value['action'], 'action_id': value['action_id'],
                    'reason': text(value['reason'], 240),
                    'reason_i18n': bilingual(value['reason']),
                    'experience_refs': [text(ref, 80) for ref in value['experience_refs'][:4]],
                    'parameters': {key: child[:8] if isinstance(child, list) else child
                                   for key, child in parameters.items()}}
            region = parameters.get('region', 'hand' if value['action'] in ('play', 'discard') else None)
            positions = parameters.get('positions', parameters.get('order'))
            if positions is None and 'position' in parameters:
                positions = [parameters['position']]
            if positions is None and value['action'] in ('play', 'discard'):
                positions = [card['position'] for card in self.board.get(region, []) if card['selected']]
            if positions is not None:
                available = {card['position']: card for card in self.board.get(region, [])}
                data['targets'] = [available.get(position, {'position': position, 'name': None}) for position in positions[:8]]
                data['card_count'] = len(positions)
            if value['action'] in ('buy', 'buy_and_use', 'sell', 'use', 'select_pack_card'):
                data['target_name'] = next((card['name'] for card in data.get('targets', []) if card.get('name')), None)
                data['target_region'] = region
            self.actions[value['action_id']] = {key: data[key] for key in ('action', 'card_count', 'target_name', 'target_region') if key in data}
            if len(self.actions) > 128:
                self.actions.pop(next(iter(self.actions)))
            self.emit('decision', 'act', data)
        except Exception:
            pass

    def progress(self, tool, result):
        try:
            data = {key: value for key in ('action_id', 'state', 'status', 'reason', 'submitted', 'callback_confirmed')
                                      if (value := result.get(key)) is not None and type(value) in (str, bool)
                                      and (not isinstance(value, str) or len(value) <= 100)}
            if result.get('action_id') in self.actions:
                data.update(self.actions[result['action_id']])
            self.emit('action', tool, data)
        except Exception:
            pass

    def _observation(self, tool, observation, *, historical=False):
        oid = observation.get('observation_id', '').split('-')
        if not historical and len(oid) == 3 and oid[2].isdigit():
            cursor = (oid[1], int(oid[2]))
            if self.latest_observation and cursor[0] == self.latest_observation[0] and cursor[1] < self.latest_observation[1]:
                historical = True
            else:
                self.latest_observation = cursor
        resources = observation.get('resources') or {}
        setup = observation.get('setup') or {}
        data = {'phase': text(observation.get('phase'), 40), 'ready': observation.get('ready') is True,
                'outcome': text(observation.get('outcome'), 20), 'historical': historical,
                'deck': text(setup.get('deck_name'), 80), 'stake': text(setup.get('stake_name'), 80),
                'resources': {key: number(resources.get(key)) for key in ('ante', 'round', 'dollars', 'chips', 'hands_left', 'discards_left')},
                'regions': [], 'blinds': []}
        for region in observation.get('regions', [])[:8]:
            cards = region.get('cards') or []
            shown = []
            for card in cards[:8]:
                visibility = card.get('visibility')
                shown.append({'position': number(card.get('position')),
                              'name': text(card.get('name'), 60) if visibility in ('face_up', 'stone') else None,
                              'visibility': text(visibility, 20), 'selected': card.get('selected') is True})
            data['regions'].append({'name': text(region.get('name'), 30), 'count': len(cards), 'cards': shown})
        for blind in observation.get('blinds', [])[:3]:
            data['blinds'].append({'name': text(blind.get('name'), 80), 'required_chips': number(blind.get('required_chips'))})
        if not historical:
            self.board = {region['name']: region['cards'] for region in data['regions']}
        self.emit('observation', tool, data)

    def delivered(self, tool, result):
        try:
            # Expand just the observation. Notes/plan bodies and other large
            # result trees are never copied or traversed for this optional UI.
            value = result
            hint = value.get('public_changes') or {}
            if isinstance(value.get('observation'), dict):
                self._observation(tool, expand(value['observation']),
                    historical=str(hint.get('reason', '')).startswith('historical_'))
            if hint.get('protocol') == 'public-changes-v1':
                sections = {'phase', 'hand', 'jokers', 'consumables', 'shop', 'pack',
                            'resources', 'blinds', 'poker_hands', 'deck_composition'}
                resource_fields = {'dollars', 'chips', 'hands_left', 'discards_left',
                                   'ante', 'round', 'reroll_cost', 'pack_choices'}
                summary = {'status': text(hint.get('status'), 40), 'reason': text(hint.get('reason'), 80),
                           **{key: [item for item in hint.get(key, []) if item in sections]
                              for key in ('changed', 'unchanged', 'unknown')},
                           'resource_changes': {key: {'before': number(change.get('before')),
                                                     'after': number(change.get('after'))}
                               for key, change in hint.get('resource_changes', {}).items() if key in resource_fields}}
                self.emit('changes', tool, summary)
            if tool in ('act', 'action_status'):
                self.progress(tool, value)
            elif tool in ('launch_game', 'close_game', 'recover_lost_session'):
                data = {key: text(value.get(key), 100) for key in ('state', 'reason', 'operation_id', 'action_id') if key in value}
                data.update({key: value[key] for key in ('running', 'mcp_connected', 'submitted', 'duplicate') if type(value.get(key)) is bool})
                self.emit('lifecycle', tool, data)
            elif tool == 'run_plan' and value.get('status') == 'ok':
                content = value.get('content') or {}
                self.emit('plan', tool, {'revision': number(value.get('revision')),
                    'updated': value.get('write_state') == 'COMMITTED' and value.get('duplicate') is not True,
                    'objective': text(content.get('objective'), 180),
                    'objective_i18n': bilingual(content.get('objective'), 90),
                    'priority_i18n': bilingual(next(iter(content.get('priorities', [])), None), 70),
                    'priorities': [text(item, 120) for item in content.get('priorities', [])[:4]],
                    'recheck_when': [text(item, 120) for item in content.get('recheck_when', [])[:4]]})
            elif tool in ('read_notes', 'write_note'):
                notes = value.get('notes', [])
                if isinstance(value.get('note'), dict):
                    notes = [value['note']]
                self.emit('notes', tool, {'status': text(value.get('status'), 40),
                    'committed': value.get('write_state') == 'COMMITTED',
                    'write_state': text(value.get('write_state'), 40),
                    'notes': [{'id': text(note.get('note_id'), 80), 'revision': number(note.get('revision'))}
                              for note in notes[:5]]})
            elif tool == 'health':
                self.emit('connection', tool, {key: text(value.get(key), 40) if isinstance(value.get(key), str) else value.get(key)
                           for key in ('status', 'phase', 'ready') if type(value.get(key)) in (str, bool)})
            elif tool == 'calculate':
                self.emit('calculation', tool, {'status': text(value.get('status'), 40),
                    'operation': text(value.get('operation'), 40), 'result': number(value.get('result'))})
            elif value.get('status') not in (None, 'ok'):
                self.emit('notice', tool, {'status': text(value.get('status'), 40)})
        except Exception:
            pass


def open_viewer(settings):
    """Dispatch only the bundled viewer, with no shell, game or model access."""
    if os.name != 'nt' or settings.client_context == 'development':
        return 'disabled'
    try:
        script = safe_path(ROOT, 'scripts', 'activity_viewer.ps1')
        if not script.is_file():
            return 'unavailable'
        folder = safe_path(settings.log_dir, 'activity')
        make_dir(folder)
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-STA', '-ExecutionPolicy', 'Bypass',
                          '-File', str(script), '-EventDirectory', str(folder)], cwd=ROOT,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        return 'requested'
    except Exception:
        return 'unavailable'
