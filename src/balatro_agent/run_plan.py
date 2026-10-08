"""Small model-authored run memory. No game reads, choices or automatic play."""
from datetime import datetime, timezone
import hashlib
import json
import os
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .local_audit import LocalAudit, canonical, make_dir, safe_path

MAX_REVISIONS = 50
MAX_FILE_BYTES = 160000
MESSAGES = {
    'invalid_input': '计划结构、大小或编号不符合契约。',
    'run_scope_missing': '尚无当前会话已确认的新局或继续对局；不能复用旧局计划。',
    'stale_observation': '计划必须绑定最近实际交付的当前局可操作观察。',
    'action_pending': '未决动作或检查点故障时不能修订计划。',
    'unread_experience': '计划引用的经验版本须先通过 content 或 full 实际读取。',
    'revision_conflict': '预期计划修订与磁盘不一致。',
    'id_conflict': '该写入ID已有不同计划内容。',
    'resource_limit': '本局计划修订已达上限。',
    'store_corrupt': '计划记录未通过完整性检查。',
    'unsafe_path': '计划目录存在不允许的链接或路径结构。',
    'busy': '另一个计划写入正在进行或保留了锁。',
    'storage_unavailable': '本地计划存储不可用。',
    'log_unavailable': '计划安全记录未能写入。',
}


class PlanError(Exception):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Scope(StrictModel):
    observation_id: str = Field(pattern=r'^obs-[0-9a-f]{16}-[0-9]+$')
    profile: int = Field(ge=1, le=3)
    action_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$')


class Continuity(StrictModel):
    observation_id: str = Field(pattern=r'^obs-[0-9a-f]{16}-[0-9]+$')
    profile: int = Field(ge=1, le=3)
    round: int | float | None = Field(ge=0, allow_inf_nan=False)


class PlanContent(StrictModel):
    objective: str = Field(min_length=1, max_length=200)
    priorities: list[str] = Field(min_length=1, max_length=4)
    recheck_when: list[str] = Field(min_length=1, max_length=4)
    experience_refs: list[str] = Field(max_length=6)

    @model_validator(mode='after')
    def bounded(self):
        import re
        texts = [self.objective] + self.priorities + self.recheck_when
        if (any(not text.strip() or len(text) > 200 or any(ord(c) < 32 for c in text) for text in texts)
                or any(not re.fullmatch(r'EXP-[A-Z0-9][A-Z0-9-]{0,47}@r([1-9][0-9]?|100)', ref)
                       for ref in self.experience_refs)
                or len(set(self.experience_refs)) != len(self.experience_refs)
                or len(canonical(self.model_dump()).encode('utf-8')) > 2000):
            raise ValueError('invalid_input')
        return self


class PlanWrite(StrictModel):
    observation_id: str = Field(pattern=r'^obs-[0-9a-f]{16}-[0-9]+$')
    content: PlanContent
    expected_revision: int = Field(ge=0, le=MAX_REVISIONS)
    write_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')


def failure(code, write=False):
    result = {'status': code, 'reason': MESSAGES[code], 'schema_version': 'run-plan-v1',
              'read_only': not write, 'game_action_submitted': False}
    if write:
        result['write_state'] = 'NOT_COMMITTED'
    return result


class RunPlans:
    def __init__(self, reader, executor, notes):
        self.reader, self.executor, self.notes = reader, executor, notes
        self.root = reader.settings.log_dir / 'run-plans'
        self.audit = LocalAudit(reader.settings)
        self.scope = None
        self.cached = []
        self.progress = {}
        self.continuity = None
        self.restored = False
        self.problem = None
        try:
            path = safe_path(self.root, 'active.json')
            if path.exists():
                row = self._json(path)
                if (set(row) not in ({'schema_version', 'scope'}, {'schema_version', 'scope', 'continuity'})
                        or row['schema_version'] != 'run-plan-v1'):
                    raise PlanError('store_corrupt')
                self.scope = Scope.model_validate(row['scope']).model_dump() if row['scope'] is not None else None
                if 'continuity' in row:
                    self.continuity = Continuity.model_validate(row['continuity']).model_dump() if row['continuity'] is not None else None
                    if (self.scope is None) != (self.continuity is None):
                        raise PlanError('store_corrupt')
                    if self.continuity is not None:
                        start, latest = self.scope['observation_id'].split('-'), self.continuity['observation_id'].split('-')
                        if start[1] != latest[1] or int(latest[2]) < int(start[2]) or self.scope['profile'] != self.continuity['profile']:
                            raise PlanError('store_corrupt')
                        if self.continuity['round'] is not None:
                            self.progress = {'round': self.continuity['round']}
                self.cached = self._history()
                self.restored = self.scope is not None
        except (OSError, ValueError, TypeError, KeyError, PlanError, ValidationError) as exc:
            self.problem = self._code(exc)

    @staticmethod
    def _code(exc):
        if isinstance(exc, PlanError):
            return str(exc)
        if isinstance(exc, (ValueError, TypeError, KeyError)):
            return 'unsafe_path' if str(exc) == 'unsafe_path' else 'store_corrupt'
        return 'storage_unavailable'

    def _json(self, path):
        with path.open('rb') as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise PlanError('store_corrupt')
        value = json.loads(data)
        if not isinstance(value, dict):
            raise PlanError('store_corrupt')
        return value

    def _atomic(self, path, value):
        make_dir(self.root)
        temporary = safe_path(self.root, '.tmp-' + uuid.uuid4().hex)
        try:
            with temporary.open('xb') as handle:
                handle.write(canonical(value).encode('utf-8'))
                handle.flush()
                os.fsync(handle.fileno())
            safe_path(self.root, path.name)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                safe_path(self.root, temporary.name).unlink()

    def _active(self):
        return {'schema_version': 'run-plan-v1', 'scope': self.scope, 'continuity': self.continuity}

    def _cursor(self, observation, *, carry_round=True):
        return Continuity.model_validate({'observation_id': observation['observation_id'],
            'profile': observation['profile'],
            'round': observation['resources'].get('round') if observation['resources'].get('round') is not None
                     else self.progress.get('round') if carry_round else None}).model_dump()

    def _set_scope(self, scope, observation=None):
        continuity = self._cursor(observation, carry_round=False) if scope is not None else None
        self._atomic(safe_path(self.root, 'active.json'),
                     {'schema_version': 'run-plan-v1', 'scope': scope, 'continuity': continuity})
        self.scope, self.cached, self.progress, self.problem = scope, [], {}, None
        self.continuity, self.restored = continuity, False
        if continuity is not None and continuity['round'] is not None:
            self.progress = {'round': continuity['round']}

    def _resume_matches(self, observation):
        # After an MCP restart only an unchanged public decision point confirms
        # continuity. Unobserved native navigation could have started another run.
        return (self.continuity is not None
                and observation['observation_id'] == self.continuity['observation_id']
                and observation['profile'] == self.continuity['profile']
                and (observation['resources'].get('round') is None
                     or observation['resources']['round'] == self.continuity['round']))

    def _path(self):
        return safe_path(self.root, self.scope['observation_id'] + f"-p{self.scope['profile']}.json")

    def _history(self):
        if self.scope is None:
            return []
        path = self._path()
        if not path.exists():
            return []
        stored = self._json(path)
        if (set(stored) != {'schema_version', 'scope', 'revisions'}
                or stored['schema_version'] != 'run-plan-v1' or stored['scope'] != self.scope
                or not isinstance(stored['revisions'], list) or not 1 <= len(stored['revisions']) <= MAX_REVISIONS):
            raise PlanError('store_corrupt')
        seen = set()
        for revision, row in enumerate(stored['revisions'], 1):
            if not isinstance(row, dict) or set(row) != {'request', 'request_hash', 'created_utc'}:
                raise PlanError('store_corrupt')
            request = PlanWrite.model_validate(row['request']).model_dump()
            if (request['expected_revision'] != revision - 1 or request['write_id'] in seen
                    or self._hash(request) != row['request_hash']
                    or request['observation_id'].split('-')[1] != self.scope['observation_id'].split('-')[1]
                    or int(request['observation_id'].split('-')[2]) < int(self.scope['observation_id'].split('-')[2])):
                raise PlanError('store_corrupt')
            if not isinstance(row['created_utc'], str):
                raise PlanError('store_corrupt')
            datetime.fromisoformat(row['created_utc'])
            seen.add(request['write_id'])
        return stored['revisions']

    @staticmethod
    def _hash(request):
        return hashlib.sha256(canonical(request).encode('utf-8')).hexdigest()

    def attach(self, result, request=None):
        """Track only filtered feedback, retaining old run files on boundaries.

        Optional memory failures never change a native action's completion state.
        """
        observation = result.get('observation')
        if observation is None:
            return result
        try:
            if self.problem:
                return {**result, 'run_plan_status': self.problem}
            if self.continuity is not None:
                previous, incoming = self.continuity['observation_id'].split('-'), observation['observation_id'].split('-')
                if previous[1] == incoming[1] and int(incoming[2]) < int(previous[2]):
                    return {**result, 'run_plan_status': 'stale_observation'}
            if (request and result.get('state') == 'COMPLETED' and not result.get('duplicate')
                    and request['action_id'] == result.get('action_id')):
                if request['action'] in ('start_run', 'continue_run'):
                    if self.scope is None or self.scope['action_id'] != request['action_id']:
                        self._set_scope({'observation_id': observation['observation_id'],
                                         'profile': observation['profile'], 'action_id': request['action_id']}, observation)
                elif request['action'] in ('open_run_setup', 'main_menu') and self.scope is not None:
                    self._set_scope(None)
            if self.scope is not None:
                if self.restored:
                    if not self._resume_matches(observation):
                        self._set_scope(None)
                        return {**result, 'run_plan_status': 'run_scope_missing'}
                    self.restored = False
                identifier = observation['observation_id']
                if (identifier.split('-')[1] != self.scope['observation_id'].split('-')[1]
                        or observation['profile'] != self.scope['profile']
                        or observation['phase'] == 'main_menu'
                        or observation['setup']['page'] in ('deck_choice', 'stake_choice')):
                    self._set_scope(None)
                elif int(identifier.split('-')[2]) < int(self.scope['observation_id'].split('-')[2]):
                    return {**result, 'run_plan_status': 'stale_observation'}
                else:
                    resources = observation['resources']
                    # Native vouchers can lower Ante within the same run. Only
                    # the public round counter is a continuity guard here.
                    progress = {key: resources[key] for key in ('round',) if resources.get(key) is not None}
                    if any(value < self.progress.get(key, value) for key, value in progress.items()):
                        self._set_scope(None)
                    else:
                        self.progress.update(progress)
                        continuity = self._cursor(observation)
                        if continuity != self.continuity:
                            self._atomic(safe_path(self.root, 'active.json'),
                                {**self._active(), 'continuity': continuity})
                            self.continuity = continuity
            if self.scope is not None and self.cached:
                return {**result, 'run_plan_ref': {'scope_observation_id': self.scope['observation_id'],
                                                 'revision': len(self.cached)}}
        except (OSError, ValueError, TypeError, KeyError, PlanError, ValidationError) as exc:
            self.problem = self._code(exc)
            return {**result, 'run_plan_status': self.problem}
        return result

    def _current(self):
        observation = self.reader.last_delivered_observation
        if self.problem:
            raise PlanError(self.problem)
        if (self.scope is None or observation is None
                or observation['profile'] != self.scope['profile']
                or observation['observation_id'].split('-')[1] != self.scope['observation_id'].split('-')[1]):
            raise PlanError('run_scope_missing')
        if int(observation['observation_id'].split('-')[2]) < int(self.scope['observation_id'].split('-')[2]):
            raise PlanError('stale_observation')
        if self.restored:
            if not self._resume_matches(observation):
                self._set_scope(None)
                raise PlanError('run_scope_missing')
            self.restored = False
        if (self.continuity is not None
                and int(observation['observation_id'].split('-')[2]) < int(self.continuity['observation_id'].split('-')[2])):
            raise PlanError('stale_observation')
        return observation

    def _result(self, history, write=False, duplicate=False):
        row = history[-1] if history else None
        result = {'status': 'ok', 'schema_version': 'run-plan-v1', 'read_only': not write,
                  'game_action_submitted': False, 'model_authored': True, 'scope': self.scope,
                  'revision': len(history), 'content': row['request']['content'] if row else None,
                  'based_on_observation_id': row['request']['observation_id'] if row else None}
        if write:
            result.update(write_state='COMMITTED', duplicate=duplicate)
        return result

    def read(self):
        try:
            self._current()
            self.cached = self._history()  # Explicit reads always go to disk.
            result = self._result(self.cached)
        except (OSError, ValueError, TypeError, KeyError, PlanError, ValidationError) as exc:
            result = failure(self._code(exc))
        return self.audit.deliver('run_plan', result)

    def write(self, observation_id, content, expected_revision, write_id):
        lock = None
        try:
            request = PlanWrite.model_validate(dict(observation_id=observation_id, content=content,
                expected_revision=expected_revision, write_id=write_id)).model_dump()
        except (ValueError, TypeError, ValidationError):
            return self.audit.deliver('run_plan', failure('invalid_input', True), write=True)
        try:
            observation = self._current()
            make_dir(self.root)
            candidate = safe_path(self.root, '.writer-lock')
            try:
                candidate.mkdir()
            except FileExistsError:
                raise PlanError('busy') from None
            lock = candidate
            active = self._json(safe_path(self.root, 'active.json'))
            if active != self._active():
                raise PlanError('run_scope_missing')
            history = self._history()
            digest = self._hash(request)
            duplicate = next((row for row in history if row['request']['write_id'] == write_id), None)
            if duplicate:
                if digest != duplicate['request_hash']:
                    raise PlanError('id_conflict')
                result = self._result(history[:duplicate['request']['expected_revision'] + 1], True, True)
            else:
                if self.executor.pending or self.executor.input_pending or self.executor.checkpoint_broken:
                    raise PlanError('action_pending')
                if (observation_id != observation['observation_id'] or not observation['ready']
                        or observation['outcome'] is not None
                        or observation['phase'] not in ('hand', 'shop', 'pack', 'blind_select')
                        or int(observation_id.split('-')[2]) < int(self.scope['observation_id'].split('-')[2])):
                    raise PlanError('stale_observation')
                if not set(request['content']['experience_refs']) <= self.notes.read_refs:
                    raise PlanError('unread_experience')
                if expected_revision != len(history):
                    raise PlanError('revision_conflict')
                if len(history) >= MAX_REVISIONS:
                    raise PlanError('resource_limit')
                try:
                    self.audit.record('run_plan', 'intent', request)
                except (OSError, ValueError):
                    raise PlanError('log_unavailable') from None
                history.append({'request': request, 'request_hash': digest,
                                'created_utc': datetime.now(timezone.utc).isoformat()})
                self._atomic(self._path(), {'schema_version': 'run-plan-v1', 'scope': self.scope, 'revisions': history})
                self.cached = history
                result = self._result(history, True)
        except (OSError, ValueError, TypeError, KeyError, PlanError, ValidationError) as exc:
            result = failure(self._code(exc), True)
        finally:
            if lock is not None:
                try:
                    safe_path(self.root, lock.name).rmdir()
                except (OSError, ValueError):
                    pass
        return self.audit.deliver('run_plan', result, write=True)
