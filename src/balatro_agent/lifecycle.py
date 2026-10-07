"""Normal OS lifecycle with durable receipts; never a game recovery shortcut."""
import asyncio
import hashlib
import json
import math
import os
import re
import time
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field

from .local_audit import LocalAudit, canonical, make_dir, safe_path
from .transport import ReaderError
from .windows_game import GameProcessError, ProcessIdentity, WindowsGame

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}')
OBS = re.compile(r'obs-[a-f0-9]{16}-[0-9]+')
Reason = Literal['already_running', 'started', 'closed', 'already_stopped',
                 'operation_busy', 'game_action_unknown', 'checkpoint_unavailable',
                 'invalid_request', 'id_conflict', 'installation_unverified',
                 'windows_only', 'process_unverified', 'multiple_game_processes',
                 'game_window_unverified', 'process_changed', 'close_dispatch_failed',
                 'test_profile_required', 'unknown_profile', 'observation_unavailable', 'stale_observation',
                 'unsafe_to_close', 'journal_unavailable', 'launch_timeout',
                 'close_timeout', 'dispatch_uncertain', 'service_error', 'receipt_limit']


class Receipt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')
    tool: Literal['launch_game', 'close_game']
    state: Literal['INTENT', 'COMPLETED', 'REJECTED', 'UNKNOWN']
    reason: Reason
    submitted: bool | None = False
    running: bool | None = None
    mcp_connected: bool | None = None
    focus: Literal['confirmed', 'not_confirmed', 'not_requested'] = 'not_requested'
    read_only: bool = False


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    receipt: Receipt
    target_pid: int | None = Field(default=None, gt=0, le=4294967295)
    target_created: int | None = Field(default=None, gt=0, le=18446744073709551615)


class LifecycleJournal:
    def __init__(self, settings):
        self.root = settings.log_dir / 'lifecycle'

    def _read(self, path):
        if path.stat().st_size > 8192:
            raise ValueError('invalid_checkpoint')
        return json.loads(path.read_text(encoding='utf-8'))

    def pending(self):
        path = safe_path(self.root, 'checkpoint.json')
        if not path.exists():
            return None
        value = self._read(path)
        if set(value) != {'pending'} or value['pending'] is not None and (not isinstance(value['pending'], str) or not ID.fullmatch(value['pending'])):
            raise ValueError('invalid_checkpoint')
        return value['pending']

    def _atomic(self, path, value):
        make_dir(self.root)
        temp = safe_path(self.root, uuid.uuid4().hex + '.tmp')
        with temp.open('x', encoding='utf-8') as stream:
            stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)

    def set_pending(self, value):
        self._atomic(safe_path(self.root, 'checkpoint.json'), {'pending': value})

    def read(self, operation_id):
        path = safe_path(self.root, operation_id + '.json')
        if not path.exists():
            return None
        record = Record.model_validate(self._read(path))
        if record.receipt.operation_id != operation_id:
            raise ValueError('invalid_receipt')
        return record

    def save(self, record):
        self._atomic(safe_path(self.root, record.receipt.operation_id + '.json'), record.model_dump())


class GameLifecycle:
    def __init__(self, reader, executor, backend=None, *, poll_s=0.2):
        self.reader, self.executor = reader, executor
        self.backend = backend or WindowsGame(reader.settings.lifecycle_file)
        self.journal = LifecycleJournal(reader.settings)
        self.audit = LocalAudit(reader.settings)
        self.poll_s = poll_s

    def blocks_actions(self):
        try:
            return self.journal.pending() is not None
        except (OSError, ValueError):
            return True

    def _deliver(self, receipt, duplicate=False):
        result = receipt.model_dump()
        result['duplicate'] = duplicate
        try:
            self.audit.record(receipt.tool, 'delivered', result)
        except (OSError, ValueError):
            result.update(state='UNKNOWN' if receipt.submitted else 'REJECTED', reason='journal_unavailable')
        return result

    async def launch_game(self, operation_id, timeout_s=25.0):
        return await self._request('launch_game', operation_id, None, timeout_s)

    async def close_game(self, operation_id, observation_id, timeout_s=15.0):
        return await self._request('close_game', operation_id, observation_id, timeout_s)

    async def _connected(self):
        try:
            await self.reader._envelope('health')
            return True
        except ReaderError:
            return False

    def _finish(self, record):
        try:
            self.journal.save(record)
            if record.receipt.state in ('COMPLETED', 'REJECTED') and self.journal.pending() == record.receipt.operation_id:
                self.journal.set_pending(None)
        except (OSError, ValueError):
            record.receipt.state = 'UNKNOWN' if record.receipt.submitted or self.blocks_actions() else 'REJECTED'
            record.receipt.reason = 'journal_unavailable'
        return self._deliver(record.receipt)

    def _focus(self, process):
        try:
            return 'confirmed' if self.backend.focus(process) else 'not_confirmed'
        except GameProcessError:
            # A running process and connected Mod are sufficient startup proof.
            # Window/focus failures are reported separately, not force-bypassed.
            return 'not_confirmed'

    async def _wait(self, record, timeout_s):
        deadline = time.monotonic() + timeout_s
        receipt = record.receipt
        while True:
            process = self.backend.find()
            receipt.running = process is not None
            if receipt.tool == 'launch_game':
                receipt.mcp_connected = process is not None and await self._connected()
                if receipt.mcp_connected:
                    receipt.focus = self._focus(process)
                    receipt.state, receipt.reason = 'COMPLETED', 'started'
                    return self._finish(record)
            else:
                target = ProcessIdentity(record.target_pid, record.target_created)
                if process is None:
                    receipt.state, receipt.reason = 'COMPLETED', 'closed'
                    receipt.mcp_connected = False
                    return self._finish(record)
                if process != target:
                    # The original process exited; another one appeared. Never
                    # close it or claim that the game is currently stopped.
                    receipt.state, receipt.reason = 'UNKNOWN', 'process_changed'
                    return self._finish(record)
            if time.monotonic() >= deadline:
                receipt.state = 'UNKNOWN'
                receipt.reason = 'launch_timeout' if receipt.tool == 'launch_game' else 'close_timeout'
                return self._finish(record)
            await asyncio.sleep(min(self.poll_s, max(0, deadline - time.monotonic())))

    async def _request(self, tool, operation_id, observation_id, timeout_s):
        valid_id = isinstance(operation_id, str) and ID.fullmatch(operation_id)
        if valid_id and (operation_id.casefold() == 'checkpoint' or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])', operation_id.split('.')[0])):
            valid_id = False
        receipt = Receipt(operation_id=operation_id if valid_id else 'invalid', tool=tool,
                          state='REJECTED', reason='invalid_request')
        if (not valid_id or isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
                or not math.isfinite(timeout_s) or not 0 <= timeout_s <= 30
                or tool == 'close_game' and (not isinstance(observation_id, str) or not OBS.fullmatch(observation_id))):
            return self._deliver(receipt)
        fingerprint = hashlib.sha256(canonical({'tool': tool, 'observation_id': observation_id,
                                                'timeout_s': float(timeout_s)}).encode()).hexdigest()
        if self.reader._tool_lock.locked():
            receipt.reason = 'operation_busy'
            return self._deliver(receipt)
        async with self.reader._tool_lock:
            record = None
            try:
                saved = self.journal.read(operation_id)
                pending = self.journal.pending()
                if saved:
                    if saved.fingerprint != fingerprint:
                        receipt.reason = 'id_conflict'
                        return self._deliver(receipt)
                    if saved.receipt.state in ('COMPLETED', 'REJECTED'):
                        if pending == operation_id:
                            self.journal.set_pending(None)
                        return self._deliver(saved.receipt, True)
                    if pending != operation_id:
                        receipt.reason = 'checkpoint_unavailable'
                        return self._deliver(receipt)
                    # Query/poll only. INTENT can be a crash before dispatch:
                    # absence cannot prove it is safe to resend.
                    saved.receipt.state, saved.receipt.submitted = 'UNKNOWN', None
                    record = saved
                    receipt = saved.receipt
                    return await self._wait(saved, timeout_s)
                if pending:
                    receipt.reason = 'operation_busy'
                    return self._deliver(receipt)
                if self.executor.checkpoint_broken:
                    receipt.reason = 'checkpoint_unavailable'
                    return self._deliver(receipt)
                if len(list(self.journal.root.glob('*.json'))) >= 1000:
                    receipt.reason = 'receipt_limit'
                    return self._deliver(receipt)
                process = self.backend.find()
                record = Record(fingerprint=fingerprint, receipt=receipt)
                if tool == 'launch_game' and process:
                    self.audit.record(tool, 'existing_window_intent', {'operation_id':operation_id})
                    receipt.state, receipt.reason, receipt.running = 'COMPLETED', 'already_running', True
                    receipt.mcp_connected = await self._connected()
                    receipt.focus = self._focus(process)
                    return self._finish(record)
                if self.executor.pending:
                    receipt.reason = 'game_action_unknown'
                    return self._finish(record)
                if tool == 'close_game':
                    if process is None:
                        receipt.state, receipt.reason, receipt.running = 'COMPLETED', 'already_stopped', False
                        return self._finish(record)
                    try:
                        result = await self.reader._observe()
                    except ReaderError:
                        receipt.reason = 'observation_unavailable'
                        return self._finish(record)
                    obs = result.get('observation', {})
                    if result.get('status') != 'ok' or type(obs.get('profile')) is not int or obs['profile'] not in (1, 2, 3):
                        receipt.reason = 'observation_unavailable'
                        return self._finish(record)
                    if obs.get('observation_id') != observation_id:
                        receipt.reason = 'stale_observation'
                        return self._finish(record)
                    safe = obs.get('phase') == 'terminal' and obs.get('outcome') in ('win', 'loss') or (
                        obs.get('phase') == 'main_menu' and obs.get('resources', {}).get('availability') == 'not_applicable')
                    if not obs.get('ready') or not safe:
                        receipt.reason = 'unsafe_to_close'
                        return self._finish(record)
                    record.target_pid, record.target_created = process.pid, process.created
                # Write both checkpoint and intent before issuing any launch or
                # close request. Failures after dispatch remain query-only.
                receipt.state, receipt.reason = 'INTENT', 'dispatch_uncertain'
                self.journal.save(record)
                self.journal.set_pending(operation_id)
                self.audit.record(tool, 'intent', receipt.model_dump())
                if tool == 'launch_game':
                    self.backend.launch()
                else:
                    self.backend.close(process)
                receipt.submitted = True
                self.journal.save(record)
                return await self._wait(record, timeout_s)
            except GameProcessError as exc:
                # Explicit backend rejection precedes its native dispatch.
                receipt.state, receipt.reason = 'REJECTED', exc.code
                if record and receipt.submitted is not False:
                    receipt.state = 'UNKNOWN'
                if record:
                    return self._finish(record)
                return self._deliver(receipt)
            except (OSError, ValueError, TypeError):
                receipt.state = 'UNKNOWN' if record and self.blocks_actions() else 'REJECTED'
                receipt.reason = 'journal_unavailable'
                return self._deliver(receipt)
            except Exception:
                receipt.state = 'UNKNOWN' if record and self.blocks_actions() else 'REJECTED'
                receipt.reason = 'service_error'
                return self._deliver(receipt)
