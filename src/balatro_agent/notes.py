"""Atomic immutable Markdown revisions and disk reads, with no strategy content."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .local_audit import LocalAudit, canonical, make_dir, safe_path

LIMIT_NOTES = 200
LIMIT_REVISIONS = 100
LIMIT_FILE_BYTES = 65536
LIMIT_RESPONSE_BYTES = 262144
ID = re.compile(r'^(EXP|TEST)-[A-Z0-9][A-Z0-9-]{0,47}$')
WRITE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')
ERRORS = {
    'invalid_input': 'The note request structure, ID, kind or text does not meet the bounded contract.',
    'not_found': 'The requested note or revision does not exist.',
    'revision_conflict': 'Expected revision differs from the current revision on disk.',
    'id_conflict': 'This write ID already belongs to different content.',
    'resource_limit': 'Note count, history or response size exceeds limits.',
    'unsafe_path': 'The controlled directory contains an unsupported link or path structure.',
    'store_corrupt': 'Note storage failed its integrity checks.',
    'busy': 'Another note write is active or retains a lock; this request was not committed.',
    'storage_unavailable': 'Controlled note storage is unavailable; this request was not committed.',
    'log_unavailable': 'The safe intent could not be recorded; the note was not committed.',
}


class NoteError(Exception):
    pass


class Source(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    run_id: str = Field(pattern=r'^(n5|test)-[A-Za-z0-9-]{1,60}$')
    steps: list[int] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def bounded(self):
        if any(type(n) is not int or not 1 <= n <= 5000 for n in self.steps) or len(set(self.steps)) != len(self.steps):
            raise ValueError('invalid_input')
        self.steps = sorted(self.steps)
        return self


class NoteContent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    sources: list[Source] = Field(min_length=1, max_length=20)
    facts: list[str] = Field(min_length=1, max_length=20)
    interpretation: list[str] = Field(min_length=1, max_length=20)
    conditions: list[str] = Field(min_length=1, max_length=20)
    counterexamples: list[str] = Field(min_length=1, max_length=20)
    confidence: str = Field(pattern=r'^(low|medium|high)$')
    revision_reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def bounded_text(self):
        texts = self.facts + self.interpretation + self.conditions + self.counterexamples + [self.revision_reason]
        if any(not s.strip() or len(s) > 2000 or any(ord(c) < 32 and c not in '\n\t\r' for c in s) for s in texts):
            raise ValueError('invalid_input')
        if len(canonical(self.model_dump()).encode('utf-8')) > 12000:
            raise ValueError('invalid_input')
        return self


class WriteNoteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['experience', 'TEST'] = 'experience'
    note_id: str = Field(pattern=r'^(EXP|TEST)-[A-Z0-9][A-Z0-9-]{0,47}$')
    content: NoteContent
    expected_revision: int = Field(ge=0, le=LIMIT_REVISIONS)
    write_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')


def error(code, *, write=False):
    result = {'status': code, 'reason': ERRORS[code], 'read_only': not write, 'schema_version': 'notes-1'}
    if write:
        result['write_state'] = 'NOT_COMMITTED'
    return result


def render(row):
    content = row['content']
    lines = ['<!-- balatro-note-v1 ' + canonical(row) + ' -->',
             '# ' + row['note_id'], '',
             f"类型：{row['kind']}；修订：{row['revision']}；UTC：{row['created_utc']}", '', '## 来源', '']
    lines += [f"- {s['run_id']}，步骤 " + ', '.join(map(str, s['steps'])) for s in content['sources']]
    for field, label in [('facts', '观察事实'), ('interpretation', '解释或假设'),
                         ('conditions', '适用条件'), ('counterexamples', '反例或待验证项')]:
        lines += ['', '## ' + label, ''] + ['- ' + text.replace('\n', '\n  ') for text in content[field]]
    lines += ['', '## 置信程度', '', content['confidence'], '', '## 修订或保留理由', '', content['revision_reason'], '']
    return '\n'.join(lines)


class NotesStore:
    def __init__(self, root: Path, *, baseline_root: Path | None = None):
        self.root = root.absolute()
        self.baseline = NotesStore(baseline_root) if baseline_root is not None else None
        if self.baseline is not None and (self.root.is_relative_to(self.baseline.root)
                                         or self.baseline.root.is_relative_to(self.root)):
            raise ValueError('unsafe_path')

    def _identity(self, kind, note_id):
        if kind not in ('experience', 'TEST') or not isinstance(note_id, str) or not ID.fullmatch(note_id):
            raise NoteError('invalid_input')
        if not note_id.startswith('EXP-' if kind == 'experience' else 'TEST-'):
            raise NoteError('invalid_input')
        return safe_path(self.root, kind, note_id)

    def _bytes(self, path):
        safe_path(self.root, *path.relative_to(self.root).parts)
        if not path.is_file():
            raise NoteError('store_corrupt')
        with path.open('rb') as stream:
            data = stream.read(LIMIT_FILE_BYTES + 1)
        if len(data) > LIMIT_FILE_BYTES:
            raise NoteError('store_corrupt')
        return data

    def _local_head(self, kind, note_id):
        folder = self._identity(kind, note_id)
        path = safe_path(self.root, kind, note_id, 'HEAD.json')
        if not path.exists():
            return 0
        try:
            row = json.loads(self._bytes(path))
            if set(row) != {'schema_version', 'note_id', 'kind', 'revision'} or row['schema_version'] != 'notes-1':
                raise ValueError()
            if row['note_id'] != note_id or row['kind'] != kind or type(row['revision']) is not int or not 1 <= row['revision'] <= LIMIT_REVISIONS:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise NoteError('store_corrupt') from None
        return row['revision']

    def _head(self, kind, note_id):
        current = self._local_head(kind, note_id)
        if current == 0 and kind == 'experience' and self.baseline is not None:
            return self.baseline._head(kind, note_id)
        return current

    def _revision(self, kind, note_id, revision):
        # A committed local topic owns its entire history. Never fill a missing
        # local revision from a baseline that may have independently changed.
        if (kind == 'experience' and self.baseline is not None
                and self._local_head(kind, note_id) == 0
                and revision <= self.baseline._head(kind, note_id)):
            return self.baseline._revision(kind, note_id, revision)
        path = safe_path(self.root, kind, note_id, f'r{revision:04d}.md')
        try:
            markdown = self._bytes(path).decode('utf-8')
            first = markdown.split('\n', 1)[0]
            if not first.startswith('<!-- balatro-note-v1 ') or not first.endswith(' -->'):
                raise ValueError()
            row = json.loads(first[len('<!-- balatro-note-v1 '):-4])
            if set(row) != {'schema_version', 'note_id', 'kind', 'revision', 'created_utc', 'write_id', 'request_hash', 'content'}:
                raise ValueError()
            if row['schema_version'] != 'notes-1' or row['note_id'] != note_id or row['kind'] != kind or type(row['revision']) is not int or row['revision'] != revision:
                raise ValueError()
            if not isinstance(row['created_utc'], str) or len(row['created_utc']) > 40:
                raise ValueError()
            datetime.fromisoformat(row['created_utc'])
            if not isinstance(row['write_id'], str) or not WRITE_ID.fullmatch(row['write_id']) or not isinstance(row['request_hash'], str) or not re.fullmatch('[0-9a-f]{64}', row['request_hash']):
                raise ValueError()
            content = NoteContent.model_validate(row['content']).model_dump()
            self._sources(kind, content)
            request = {'kind': kind, 'note_id': note_id, 'content': content, 'expected_revision': revision - 1, 'write_id': row['write_id']}
            if self._hash(request) != row['request_hash'] or render(row) != markdown:
                raise ValueError()
        except (ValueError, TypeError, KeyError, ValidationError, NoteError):
            raise NoteError('store_corrupt') from None
        return row

    @staticmethod
    def _sources(kind, content):
        prefix = 'n5-' if kind == 'experience' else 'test-'
        if any(not source['run_id'].startswith(prefix) for source in content['sources']):
            raise NoteError('invalid_input')

    @staticmethod
    def _hash(request):
        return hashlib.sha256(canonical(request).encode('utf-8')).hexdigest()

    def _ids(self, kind):
        folder = safe_path(self.root, kind)
        ids = []
        # Bounded scan, including incomplete creates; unknown children fail closed.
        for item in folder.iterdir() if folder.exists() else ():
            self._identity(kind, item.name)
            if not item.is_dir():
                raise NoteError('store_corrupt')
            ids.append(item.name)
            if len(ids) > LIMIT_NOTES:
                raise NoteError('resource_limit')
        if kind == 'experience' and self.baseline is not None:
            ids = set(ids).union(self.baseline._ids(kind))
            if len(ids) > LIMIT_NOTES:
                raise NoteError('resource_limit')
        return sorted(ids)

    def _fork_history(self, kind, note_id, current):
        """Copy validated baseline history under the existing writer lock.

        Commit the first local HEAD only with the requested new revision.
        Interrupted copies remain reusable without overwriting old revisions.
        """
        if (kind != 'experience' or self.baseline is None or current == 0
                or self._local_head(kind, note_id) != 0):
            return
        if self.baseline._head(kind, note_id) != current:
            raise NoteError('revision_conflict')
        for revision in range(1, current + 1):
            row = self.baseline._revision(kind, note_id, revision)
            data = render(row).encode('utf-8')
            path = safe_path(self.root, kind, note_id, f'r{revision:04d}.md')
            if path.exists():
                if self._bytes(path) != data:
                    raise NoteError('store_corrupt')
            else:
                self._atomic(path, data)
        if self.baseline._head(kind, note_id) != current:
            raise NoteError('revision_conflict')

    @staticmethod
    def _public(row, current):
        return {key: row[key] for key in ('note_id', 'kind', 'revision', 'created_utc', 'write_id', 'content')} | {
            'current_revision': current, 'markdown': render(row), 'source_validation': 'model_supplied_audit_required'}

    def read(self, kind='experience', note_ids=None, revision=None, view='full', query=None, offset=0):
        if kind not in ('experience', 'TEST') or view not in ('full', 'content', 'index'):
            raise NoteError('invalid_input')
        if (type(offset) is not int or not 0 <= offset <= LIMIT_NOTES
                or (view != 'index' and (query is not None or offset != 0))
                or (query is not None and (not isinstance(query, str) or len(query) > 80
                    or any(ord(c) < 32 for c in query)))):
            raise NoteError('invalid_input')
        if note_ids is not None and (not isinstance(note_ids, list) or len(note_ids) > 20 or any(not isinstance(n, str) for n in note_ids) or len(set(note_ids)) != len(note_ids)):
            raise NoteError('invalid_input')
        if revision is not None and (type(revision) is not int or not 1 <= revision <= LIMIT_REVISIONS or note_ids is None or len(note_ids) != 1):
            raise NoteError('invalid_input')
        ids = self._ids(kind) if note_ids is None else note_ids
        if len(ids) > 20 and view != 'index':
            raise NoteError('resource_limit')
        notes = []
        for note_id in ids:
            current = self._head(kind, note_id)
            if current == 0:
                if note_ids is None:
                    continue
                raise NoteError('not_found')
            selected = revision if revision is not None else current
            if selected > current:
                raise NoteError('not_found')
            row = self._revision(kind, note_id, selected)
            if view == 'index':
                # Literal retrieval only: no model, relevance score or strategy.
                content = row['content']
                text = canonical({'note_id': note_id, 'content': content}).casefold()
                if query and query.strip().casefold() not in text:
                    continue
                previews = content['conditions'][:2]
                notes.append({'note_id': note_id, 'revision': selected, 'current_revision': current,
                              'note_ref': f'{note_id}@r{selected}', 'confidence': content['confidence'],
                              'fact_preview': content['facts'][0][:120],
                              'condition_previews': [s[:120] for s in previews],
                              'counterexample_preview': content['counterexamples'][0][:120],
                              'preview_only': True})
            else:
                notes.append(self._public(row, current))
        if view == 'content':
            for note in notes:
                del note['markdown']
        result = {'status': 'ok', 'schema_version': 'notes-1', 'read_only': True, 'kind': kind, 'notes': notes}
        if view == 'index':
            total = len(notes)
            result.update(notes=notes[offset:offset + 20], total_matches=total, discovery_only=True,
                          next_offset=offset + 20 if offset + 20 < total else None)
        if len(canonical(result).encode('utf-8')) > LIMIT_RESPONSE_BYTES:
            raise NoteError('resource_limit')
        return result

    def request(self, kind, note_id, content, expected_revision, write_id):
        self._identity(kind, note_id)
        try:
            request = WriteNoteRequest.model_validate({'kind': kind, 'note_id': note_id, 'content': content,
                                                       'expected_revision': expected_revision, 'write_id': write_id}).model_dump()
        except (ValueError, TypeError, ValidationError):
            raise NoteError('invalid_input') from None
        self._sources(kind, request['content'])
        return request

    def _atomic(self, path, data):
        temporary = safe_path(self.root, *path.parent.relative_to(self.root).parts, '.tmp-' + uuid.uuid4().hex)
        try:
            with temporary.open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            safe_path(self.root, *path.relative_to(self.root).parts)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                safe_path(self.root, *temporary.relative_to(self.root).parts)
                temporary.unlink()

    def write(self, request):
        kind, note_id = request['kind'], request['note_id']
        make_dir(self.root)
        lock = safe_path(self.root, '.writer-lock')
        try:
            lock.mkdir()
        except FileExistsError:
            raise NoteError('busy') from None
        try:
            ids = self._ids(kind)
            if note_id not in ids and len(ids) >= LIMIT_NOTES:
                raise NoteError('resource_limit')
            current = self._head(kind, note_id)
            digest = self._hash(request)
            for revision in range(1, current + 1):
                row = self._revision(kind, note_id, revision)
                if row['write_id'] == request['write_id']:
                    if row['request_hash'] != digest:
                        raise NoteError('id_conflict')
                    return {'status': 'ok', 'schema_version': 'notes-1', 'read_only': False,
                            'write_state': 'COMMITTED', 'duplicate': True, 'note': self._public(row, current)}
            if current != request['expected_revision']:
                raise NoteError('revision_conflict')
            if current >= LIMIT_REVISIONS:
                raise NoteError('resource_limit')
            folder = self._identity(kind, note_id)
            make_dir(folder)
            self._fork_history(kind, note_id, current)
            revision = current + 1
            path = safe_path(self.root, kind, note_id, f'r{revision:04d}.md')
            if path.exists():
                # A failed HEAD commit left an immutable orphan. Reuse only same request.
                row = self._revision(kind, note_id, revision)
                if row['request_hash'] != digest:
                    raise NoteError('storage_unavailable')
            else:
                row = {'schema_version': 'notes-1', 'note_id': note_id, 'kind': kind, 'revision': revision,
                       'created_utc': datetime.now(timezone.utc).isoformat(), 'write_id': request['write_id'],
                       'request_hash': digest, 'content': request['content']}
                self._atomic(path, render(row).encode('utf-8'))
            head = {key: row[key] for key in ('schema_version', 'note_id', 'kind', 'revision')}
            self._atomic(safe_path(self.root, kind, note_id, 'HEAD.json'), canonical(head).encode('utf-8'))
            return {'status': 'ok', 'schema_version': 'notes-1', 'read_only': False,
                    'write_state': 'COMMITTED', 'duplicate': False, 'note': self._public(row, revision)}
        finally:
            safe_path(self.root, '.writer-lock')
            # A cleanup error must never misreport a committed HEAD as uncommitted.
            # A remaining lock blocks future writes and is preserved for review.
            try:
                lock.rmdir()
            except OSError:
                pass


class NotesService:
    def __init__(self, settings, *, activity=None):
        self.store = NotesStore(settings.notes_dir, baseline_root=settings.baseline_notes_dir)
        self.audit = LocalAudit(settings, activity=activity)
        self.read_refs = set()

    @staticmethod
    def _failure(exc, write=False):
        code = str(exc) if isinstance(exc, NoteError) else 'unsafe_path' if isinstance(exc, ValueError) and str(exc) == 'unsafe_path' else 'storage_unavailable'
        return error(code if code in ERRORS else 'storage_unavailable', write=write)

    def read_notes(self, kind='experience', note_ids=None, revision=None, view='full', query=None, offset=0):
        try:
            result = self.store.read(kind, note_ids, revision, view, query, offset)
        except (NoteError, OSError, ValueError, TypeError) as exc:
            result = self._failure(exc)
        delivered = self.audit.deliver('read_notes', result)
        if delivered.get('status') == 'ok' and kind == 'experience' and view != 'index':
            self.read_refs.update(f"{note['note_id']}@r{note['revision']}" for note in delivered['notes'])
        return delivered

    def write_note(self, note_id, content, expected_revision, write_id, kind='experience', view='full'):
        try:
            if view not in ('content', 'full'):
                raise NoteError('invalid_input')
            request = self.store.request(kind, note_id, content, expected_revision, write_id)
            try:
                self.audit.record('write_note', 'intent', request)
            except (OSError, ValueError):
                raise NoteError('log_unavailable') from None
            result = self.store.write(request)
            if view == 'content':
                result['note'] = {key: value for key, value in result['note'].items() if key != 'markdown'}
        except (NoteError, OSError, ValueError, TypeError) as exc:
            result = self._failure(exc, write=True)
        return self.audit.deliver('write_note', result, write=True)
