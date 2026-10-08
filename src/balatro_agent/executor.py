"""Single-action gateway, durable intent and recovery. No automatic resubmit."""
import asyncio
from datetime import datetime, timezone
import json
import os
import time
import uuid
from pydantic import ValidationError
from .actions import ACTIONS, ActionRequest, ActionWire
from .contract import ADAPTER_VERSION, GAME_VERSION, SCHEMA_VERSION, POLICY_VERSION, UPSTREAM_COMMIT
from .policy import canonical
from .reader import Reader
from .transport import ReaderError
from .installation_registry import RegistrationGuard


def rejection(reason, action_id=None):
    return {'state': 'REJECTED', 'reason': reason, 'action_id': action_id, 'submitted': False, 'read_only': False}


class Executor:
    def __init__(self, reader: Reader, *, wait_s: float = 20):
        self.reader = reader
        self.wait_s = wait_s
        self.root = reader.settings.log_dir / 'executor'
        self.checkpoint = self.root / 'checkpoint.json'
        self.log = self.root / ('actions-' + uuid.uuid4().hex + '.jsonl')
        self.pending = None
        self.input_pending = None
        self.last_request = None
        self.checkpoint_broken = False
        self.registration = RegistrationGuard(reader.settings)
        self._expected_checkpoint = {'pending': None, 'input_pending': None}
        try:
            if self.checkpoint.exists():
                saved = json.loads(self.checkpoint.read_text(encoding='utf-8'))
                self._expected_checkpoint = saved
                if saved.get('pending') is not None:
                    self.pending = ActionRequest.model_validate(saved['pending']).model_dump()
                    self.last_request = self.pending
                if saved.get('input_pending') is not None:
                    self.input_pending = ActionRequest.model_validate(saved['input_pending']).model_dump()
                    if (self.pending is None or self.input_pending['action'] != 'close_menu'
                            or self.input_pending['action_id'] == self.pending['action_id']
                            or self.input_pending['observation_id'].split('-')[1] != self.pending['observation_id'].split('-')[1]):
                        raise ValueError('invalid_checkpoint')
                    self.last_request = self.input_pending
        except (OSError, ValueError, ValidationError):
            self.checkpoint_broken = True

    def _save(self):
        checkpoint = {'pending': self.pending, 'input_pending': self.input_pending}
        self.registration.persist('executor', checkpoint, lambda: self._save_local(checkpoint),
                                  expected=self._expected_checkpoint)
        self._expected_checkpoint = json.loads(canonical(checkpoint))

    def _save_local(self, checkpoint):
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.checkpoint.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        with temp.open('w', encoding='utf-8') as f:
            f.write(canonical(checkpoint)); f.flush(); os.fsync(f.fileno())
        os.replace(temp, self.checkpoint)

    def _record(self, kind, value):
        self.root.mkdir(parents=True, exist_ok=True)
        with self.log.open('a', encoding='utf-8') as f:
            row = {'kind': kind, 'client_context': self.reader.settings.client_context,
                   'utc': datetime.now(timezone.utc).isoformat(), 'value': value}
            f.write(canonical(row)+'\n'); f.flush(); os.fsync(f.fileno())

    def _safe_wire(self, raw):
        wire = ActionWire.model_validate(raw)
        result = wire.model_dump(exclude={'snapshot'})
        result['read_only'] = False
        if wire.state == 'REJECTED' and wire.submitted is not False:
            raise ValueError('invalid_response')
        if wire.state in ('RUNNING', 'AWAITING_INPUT', 'COMPLETED') and wire.submitted is not True:
            raise ValueError('invalid_response')
        expected_profile = self.reader.observed_profile(wire.observation_id)
        if (wire.submitted and expected_profile is not None
                and wire.execution_profile != expected_profile):
            raise ValueError('invalid_response')
        if wire.snapshot:
            env = wire.snapshot
            if env.game_session != wire.game_session or env.observation_id is None or not env.observation_id.startswith('obs-'+wire.game_session+'-'):
                raise ValueError('invalid_response')
            if (env.schema_version, env.visibility_policy_version, env.adapter_version, env.upstream_commit,
                env.upstream_mod_version, env.game_version, env.compatibility) != (SCHEMA_VERSION, POLICY_VERSION,
                ADAPTER_VERSION, UPSTREAM_COMMIT, '1.5.1', GAME_VERSION, 'supported'):
                raise ValueError('invalid_response')
            if env.profile is not None and env.public is not None:
                if (env.phase, env.ready, env.ready_reason) != (env.public.phase, env.public.ready, env.public.ready_reason):
                    raise ValueError('invalid_response')
                result['observation'] = self.reader.project_envelope(env)['observation']
        if wire.state == 'COMPLETED':
            terminal = wire.completion_signal == 'terminal_confirmation' and result.get('observation', {}).get('outcome') in ('win', 'loss')
            observation = result.get('observation', {})
            if not (observation.get('ready') and wire.execution_profile in (1, 2, 3)
                    and observation.get('profile') == wire.execution_profile
                    and wire.reason == 'completed' and wire.completion_signal is not None
                    and wire.submitted and wire.callback_confirmed and (wire.related_events_complete or terminal)):
                raise ValueError('invalid_response')
        if wire.state == 'AWAITING_INPUT':
            observation = result.get('observation', {})
            if not (self.pending and wire.action_id == self.pending['action_id']
                    and self.pending['action'] in ('open_run_setup', 'continue_run', 'start_run', 'main_menu')
                    and wire.reason == 'native_unlock_input' and wire.callback_confirmed
                    and wire.required_action == 'close_menu' and wire.input_for_action_id is None
                    and wire.completion_signal is None and wire.execution_profile in (1, 2, 3)
                    and observation.get('profile') == wire.execution_profile
                    and observation.get('ready') and observation.get('phase') in ('menu', 'main_menu')
                    and any(a['name'] == 'close_menu' and a['enabled'] for a in observation.get('ui_actions', []))):
                raise ValueError('invalid_response')
        return result

    def _unknown(self, req, reason='transport_uncertain'):
        return {'state': 'UNKNOWN', 'reason': reason, 'action_id': req['action_id'],
                'observation_id': req['observation_id'], 'submitted': None, 'read_only': False}

    def _deliver(self, tool, result, *, restore_request=None, restore_input=False):
        try:
            self._record('delivered_'+tool, result)
        except OSError:
            if result.get('submitted') is False:
                return {**rejection('log_unavailable', result.get('action_id')), 'read_only': result.get('read_only', False)}
            recovery = restore_request or self.last_request
            if recovery and result.get('action_id') == recovery['action_id']:
                if restore_input or (self.pending and recovery['action_id'] != self.pending['action_id']):
                    self.input_pending = recovery
                else:
                    self.pending = recovery
                try:
                    self._save()
                except OSError:
                    self.checkpoint_broken = True
            return {**self._unknown(result, 'log_unavailable'), 'submitted': result.get('submitted'),
                    'read_only': result.get('read_only', False)}
        return result

    async def _query(self, action_id):
        raw = await self.reader.client.action('action_status', {'action_id': action_id})
        return self._safe_wire(raw)

    def _settle(self, result):
        if result['state'] not in ('COMPLETED', 'REJECTED'):
            return
        attribute = None
        if self.input_pending and result['action_id'] == self.input_pending['action_id']:
            if result['state'] == 'COMPLETED' and result.get('input_for_action_id') != self.pending['action_id']:
                raise ValueError('invalid_response')
            attribute = 'input_pending'
        elif self.pending and result['action_id'] == self.pending['action_id'] and self.input_pending is None:
            attribute = 'pending'
        if attribute:
            saved = getattr(self, attribute)
            setattr(self, attribute, None)
            try:
                self._save()
            except OSError:
                setattr(self, attribute, saved)
                raise

    async def act(self, action, parameters, observation_id, action_id, reason, experience_refs):
        try:
            req = ActionRequest.model_validate(dict(action=action, parameters=parameters, observation_id=observation_id,
                      action_id=action_id, reason=reason, experience_refs=experience_refs)).model_dump()
        except (ValidationError, TypeError, ValueError):
            return self._deliver('act', rejection('unknown_action' if isinstance(action, str) and action not in ACTIONS else 'invalid_request'))
        if self.reader._tool_lock.locked():
            return self._deliver('act', rejection('action_busy', req['action_id']))
        async with self.reader._tool_lock:
            try:
                self.registration.check()
            except OSError:
                return self._deliver('act', rejection('checkpoint_unavailable', req['action_id']))
            lifecycle = getattr(self, 'lifecycle', None)
            if lifecycle is not None and lifecycle.blocks_actions():
                return self._deliver('act', rejection('action_busy', req['action_id']))
            if self.checkpoint_broken:
                return self._deliver('act', rejection('checkpoint_unavailable', req['action_id']))
            if self.input_pending:
                if canonical(req) == canonical(self.input_pending):
                    return await self._status_locked(req['action_id'])
                if req['action_id'] == self.input_pending['action_id']:
                    return self._deliver('act', rejection('id_conflict', req['action_id']))
                return self._deliver('act', rejection('action_busy', req['action_id']))
            continuation = False
            if self.pending:
                if canonical(req) == canonical(self.pending):
                    # Recover the same request by query only, never submit again.
                    return await self._status_locked(req['action_id'])
                if req['action_id'] == self.pending['action_id']:
                    return self._deliver('act', rejection('id_conflict', req['action_id']))
                if req['action'] != 'close_menu' or self.pending['action'] not in ('open_run_setup', 'continue_run', 'start_run', 'main_menu'):
                    return self._deliver('act', rejection('action_busy', req['action_id']))
                parent = await self._status_locked(self.pending['action_id'], deliver=False)
                if self.pending is not None:
                    if (parent['state'] != 'AWAITING_INPUT' or parent.get('game_session') != req['observation_id'].split('-')[1]):
                        return self._deliver('act', rejection('action_busy', req['action_id']))
                    continuation = True
            expected_profile = self.reader.observed_profile(req['observation_id'])
            if expected_profile not in (1, 2, 3):
                return self._deliver('act', rejection('stale_observation', req['action_id']))
            try:
                self._record('intent', {'request': req})
                if continuation:
                    self.input_pending = req
                else:
                    self.pending = req
                self.last_request = req
                self._save()
            except OSError:
                if continuation:
                    self.input_pending = None
                else:
                    self.pending = None
                self.checkpoint_broken = True
                return self._deliver('act', rejection('journal_unavailable', req['action_id']))
            try:
                transport_wait_ms, poll_count = 0.0, 0
                transport_started = time.perf_counter()
                raw = await self.reader.client.action('act_submit', {**req,
                                                      'expected_profile': {'profile': expected_profile, 'policy': 'current-native-v1'},
                                                      'game_session': req['observation_id'].split('-')[1]})
                transport_wait_ms += (time.perf_counter() - transport_started) * 1000
                result = self._safe_wire(raw)
                if result['action_id'] != req['action_id']:
                    raise ValueError('invalid_response')
                if result['state'] != 'REJECTED' and result['game_session'] != req['observation_id'].split('-')[1]:
                    raise ValueError('invalid_response')
                if continuation and result['state'] != 'REJECTED' and result.get('input_for_action_id') != self.pending['action_id']:
                    raise ValueError('invalid_response')
                deadline = time.monotonic() + self.wait_s
                while result['state'] == 'RUNNING' and time.monotonic() < deadline:
                    await asyncio.sleep(self.reader.settings.poll_interval_s)
                    transport_started = time.perf_counter()
                    result = await self._query(req['action_id'])
                    transport_wait_ms += (time.perf_counter() - transport_started) * 1000
                    poll_count += 1
                    if result['action_id'] != req['action_id'] or result['game_session'] != req['observation_id'].split('-')[1]:
                        raise ValueError('invalid_response')
                if result['state'] == 'RUNNING':
                    result = {**result, 'state': 'UNKNOWN', 'reason': 'completion_timeout'}
                result['timing'] = {**(result.get('timing') or {}),
                                    'transport_wait_ms': round(transport_wait_ms, 3), 'poll_count': poll_count}
                # Log result before clearing the durable uncertain checkpoint.
                self._record('confirmed_feedback', result)
                self._settle(result)
            except ReaderError:
                result = self._unknown(req)
            except (ValidationError, ValueError):
                result = self._unknown(req, 'invalid_response')
            except OSError:
                result = self._unknown(req, 'log_unavailable')
            except Exception:
                result = self._unknown(req, 'service_error')
            return self._deliver('act', result, restore_request=req, restore_input=continuation)

    async def _status_locked(self, action_id, *, deliver=True):
        known = next((r for r in (self.input_pending, self.pending) if r and action_id == r['action_id']), None)
        input_query = known is not None and known is self.input_pending
        try:
            result = await self._query(action_id)
            if result['action_id'] != action_id:
                raise ValueError('invalid_response')
            if known:
                session = known['observation_id'].split('-')[1]
                if result['game_session'] != session:
                    result = self._unknown(known, 'session_changed')
                else:
                    if deliver:
                        self._record('recovered_feedback', result)
                    else:
                        self._record('continuation_guard', {key: result.get(key) for key in
                            ('action_id', 'state', 'reason', 'game_session', 'observation_id', 'callback_confirmed', 'required_action')})
                    self._settle(result)
        except ReaderError:
            result = self._unknown(known or {'action_id': action_id, 'observation_id': None})
        except (ValidationError, ValueError):
            result = self._unknown(known or {'action_id': action_id, 'observation_id': None}, 'invalid_response')
        except OSError:
            result = self._unknown(known or {'action_id': action_id, 'observation_id': None}, 'log_unavailable')
        except Exception:
            result = self._unknown(known or {'action_id': action_id, 'observation_id': None}, 'service_error')
        result['read_only'] = True
        if not deliver:
            return result
        return self._deliver('action_status', result, restore_request=known, restore_input=input_query)

    async def action_status(self, action_id):
        import re
        if not isinstance(action_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}', action_id):
            return self._deliver('action_status', {**rejection('invalid_request'), 'read_only': True})
        async with self.reader._tool_lock:
            return await self._status_locked(action_id)
