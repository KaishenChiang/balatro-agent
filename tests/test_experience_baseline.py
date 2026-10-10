"""Synthetic local learning/upgrade isolation; shipped text is not gameplay evidence."""
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from balatro_agent.local_audit import canonical
from balatro_agent.notes import NotesService, NotesStore
from balatro_agent.settings import Settings


def fixture_content(label):
    return {'sources': [{'run_id': 'n5-synthetic-baseline-fixture', 'steps': [1]}],
            'facts': ['SYNTHETIC ONLY: ' + label],
            'interpretation': ['Synthetic storage fixture, not a strategy.'],
            'conditions': ['Temporary test directory only.'],
            'counterexamples': ['Not real-game evidence.'], 'confidence': 'low',
            'revision_reason': label}


def commit(store, label, revision=0, write_id='seed-1', note_id='EXP-SYNTHETIC'):
    request = store.request('experience', note_id, fixture_content(label), revision, write_id)
    return store.write(request)


@pytest.fixture
def layered(settings, tmp_path):
    base = NotesStore(tmp_path / 'baseline')
    commit(base, 'seed one')
    commit(base, 'seed two', 1, 'seed-2')
    config = replace(settings, notes_dir=tmp_path / 'local', baseline_notes_dir=base.root)
    return base, config


def snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def test_reads_baseline_without_copying_and_test_partition_never_inherits(layered):
    base, config = layered
    service = NotesService(config)
    assert service.read_notes(view='content') == base.read(view='content')
    historical = service.read_notes(note_ids=['EXP-SYNTHETIC'], revision=1)
    assert historical['notes'][0]['content'] == fixture_content('seed one')
    assert historical['notes'][0]['current_revision'] == 2
    assert not config.notes_dir.exists()
    assert service.read_notes(note_ids=[])['notes'] == []
    assert service.read_notes(kind='TEST')['notes'] == []
    test = fixture_content('TEST fixture')
    test['sources'] = [{'run_id': 'test-synthetic', 'steps': [1]}]
    assert service.write_note('TEST-LOCAL', test, 0, 'test-only', 'TEST')['write_state'] == 'COMMITTED'
    assert service.read_notes(kind='TEST')['notes'][0]['content'] == test
    assert not (base.root / 'TEST').exists()


def test_first_local_revision_forks_complete_history_and_never_changes_baseline(layered):
    base, config = layered
    before = snapshot(base.root)
    service = NotesService(config)
    content = fixture_content('personal revision')
    result = service.write_note('EXP-SYNTHETIC', content, 2, 'personal-3')
    assert result['note']['revision'] == 3
    assert snapshot(base.root) == before
    for revision in (1, 2):
        relative = Path(f'experience/EXP-SYNTHETIC/r{revision:04d}.md')
        assert (config.notes_dir / relative).read_bytes() == (base.root / relative).read_bytes()
        assert service.read_notes(note_ids=['EXP-SYNTHETIC'], revision=revision)['status'] == 'ok'
    assert service.write_note('EXP-SYNTHETIC', content, 2, 'personal-3')['duplicate']
    assert service.write_note('EXP-SYNTHETIC', content, 2, 'other-3')['status'] == 'revision_conflict'
    assert service.write_note('EXP-SYNTHETIC', fixture_content('different'), 2, 'personal-3')['status'] == 'id_conflict'
    code = ('import json,sys; from pathlib import Path; from balatro_agent.notes import NotesStore; '
            'print(json.dumps(NotesStore(Path(sys.argv[1]),baseline_root=Path(sys.argv[2])).read(),ensure_ascii=True))')
    independent = json.loads(subprocess.check_output(
        [sys.executable, '-c', code, str(config.notes_dir), str(base.root)], text=True))
    assert independent['notes'][0]['content'] == content


def test_source_upgrade_keeps_personal_history_and_updates_untouched_topics(layered):
    base, config = layered
    service = NotesService(config)
    local = fixture_content('personal branch')
    assert service.write_note('EXP-SYNTHETIC', local, 2, 'personal-3')['status'] == 'ok'
    commit(base, 'new official rule', 2, 'official-3')
    commit(base, 'new official topic', note_id='EXP-UNTOUCHED', write_id='untouched-1')
    fresh = NotesService(config)
    current = {n['note_id']: n for n in fresh.read_notes()['notes']}
    assert current['EXP-SYNTHETIC']['content'] == local
    assert current['EXP-UNTOUCHED']['content'] == fixture_content('new official topic')
    assert not (config.notes_dir / 'experience/EXP-UNTOUCHED').exists()
    assert fresh.read_notes(note_ids=['EXP-SYNTHETIC'], revision=1)['notes'][0]['content'] == fixture_content('seed one')


async def test_mcp_roundtrip_revises_local_experience_using_the_delivered_baseline_revision(layered, monkeypatch):
    from mcp import Client
    import balatro_agent.server as server
    base, config = layered
    before = snapshot(base.root)
    monkeypatch.setattr(server, 'notes', NotesService(config))
    async with Client(server.mcp) as client:
        first = (await client.call_tool('read_notes', {
            'note_ids': ['EXP-SYNTHETIC'], 'view': 'content'})).structured_content
        assert first['notes'][0]['revision'] == 2
        content = fixture_content('MCP personal revision')
        written = (await client.call_tool('write_note', {
            'note_id': 'EXP-SYNTHETIC', 'content': content,
            'expected_revision': first['notes'][0]['revision'], 'write_id': 'mcp-personal-3'})).structured_content
        assert written['write_state'] == 'COMMITTED' and written['note']['revision'] == 3
        current = (await client.call_tool('read_notes', {
            'note_ids': ['EXP-SYNTHETIC'], 'view': 'content'})).structured_content
        assert current['notes'][0]['content'] == content
        historical = (await client.call_tool('read_notes', {
            'note_ids': ['EXP-SYNTHETIC'], 'revision': 1, 'view': 'content'})).structured_content
        assert historical['notes'][0]['content'] == fixture_content('seed one')
    assert snapshot(base.root) == before
    assert (config.notes_dir / 'experience/EXP-SYNTHETIC/r0003.md').is_file()


@pytest.mark.parametrize('failed_target', ['r0001.md', 'r0002.md', 'HEAD.json'])
def test_interrupted_first_fork_retains_baseline_and_same_request_can_resume(layered, monkeypatch, failed_target):
    base, config = layered
    before = snapshot(base.root)
    service = NotesService(config)
    content = fixture_content('personal revision')
    original = os.replace
    def fail(source, destination):
        if Path(destination).name == failed_target:
            raise OSError('SECRET_PATH')
        original(source, destination)
    monkeypatch.setattr(os, 'replace', fail)
    result = service.write_note('EXP-SYNTHETIC', content, 2, 'personal-3')
    assert result['status'] == 'storage_unavailable' and result['write_state'] == 'NOT_COMMITTED'
    assert 'SECRET' not in canonical(result)
    assert service.read_notes()['notes'][0]['revision'] == 2
    assert snapshot(base.root) == before
    monkeypatch.setattr(os, 'replace', original)
    if failed_target == 'HEAD.json':
        alternative = fixture_content('different request')
        assert service.write_note('EXP-SYNTHETIC', alternative, 2, 'alternative-3')['status'] == 'storage_unavailable'
    resumed = NotesService(config).write_note('EXP-SYNTHETIC', content, 2, 'personal-3')
    assert resumed['write_state'] == 'COMMITTED' and resumed['note']['revision'] == 3
    assert snapshot(base.root) == before


def test_stale_baseline_revision_cannot_fork_a_newer_official_head(layered):
    base, config = layered
    commit(base, 'new official rule', 2, 'official-3')
    service = NotesService(config)
    result = service.write_note('EXP-SYNTHETIC', fixture_content('stale'), 2, 'stale-3')
    assert result['status'] == 'revision_conflict'
    assert not (config.notes_dir / 'experience/EXP-SYNTHETIC/HEAD.json').exists()


def test_corrupt_baseline_history_cannot_be_copied_or_exposed(layered):
    base, config = layered
    (base.root / 'experience/EXP-SYNTHETIC/r0001.md').write_text('SECRET_CORRUPTION', encoding='utf-8')
    service = NotesService(config)
    result = service.write_note('EXP-SYNTHETIC', fixture_content('personal'), 2, 'personal-3')
    assert result['status'] == 'store_corrupt' and 'SECRET' not in canonical(result)
    assert not (config.notes_dir / 'experience/EXP-SYNTHETIC/HEAD.json').exists()


def test_missing_local_history_does_not_silently_fall_back_to_official_history(layered):
    _, config = layered
    service = NotesService(config)
    assert service.write_note('EXP-SYNTHETIC', fixture_content('personal'), 2, 'personal-3')['status'] == 'ok'
    (config.notes_dir / 'experience/EXP-SYNTHETIC/r0001.md').unlink()
    result = service.read_notes(note_ids=['EXP-SYNTHETIC'], revision=1)
    assert result['status'] == 'store_corrupt'


def test_runtime_local_paths_and_development_test_isolation(tmp_path, monkeypatch):
    import balatro_agent.settings as module
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.delenv('BALATRO_AGENT_CLIENT_CONTEXT', raising=False)
    normal = Settings.runtime()
    assert normal.notes_dir == tmp_path / 'runs/local-experience'
    assert normal.baseline_notes_dir == tmp_path / 'experience'
    monkeypatch.setenv('BALATRO_AGENT_CLIENT_CONTEXT', 'development')
    development = Settings.runtime()
    assert development.baseline_notes_dir is None
    assert development.notes_dir == tmp_path / 'runs/checks/stdio-development/experience'


def test_shipped_primary_guide_and_references_have_bounded_payload_and_valid_ids():
    root = Path(__file__).resolve().parents[1]
    rows = NotesStore(root / 'experience').read(view='content')['notes']
    notes = {row['note_id']: row for row in rows}
    guide = notes['EXP-GENERAL-GUIDE']
    assert len(canonical(guide['content']).encode('utf-8')) <= 8000
    for note_id, row in notes.items():
        if note_id != 'EXP-GENERAL-GUIDE':
            assert len(canonical(row['content']).encode('utf-8')) <= 3000
    references = set(re.findall(r'EXP-[A-Z0-9]+(?:-[A-Z0-9]+)*', canonical(guide['content'])))
    assert references <= notes.keys()
    assert references == notes.keys() - {'EXP-GENERAL-GUIDE'}


@pytest.mark.parametrize('view', ['full', 'content'])
@pytest.mark.parametrize('damage', [None, 'content', 'write_id', 'markdown', 'missing_markdown', 'missing_metadata', 'status'])
def test_independent_disk_verifier_matches_local_revision_and_rejects_tampered_delivery(tmp_path, monkeypatch, view, damage):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('synthetic_disk_check', root / 'scripts/check_notes_persistence.py')
    disk_check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(disk_check)
    baseline = NotesStore(tmp_path / 'experience')
    commit(baseline, 'synthetic official revision')
    local = NotesStore(tmp_path / 'runs/local-experience', baseline_root=baseline.root)
    commit(local, 'synthetic personal revision', 1, 'personal-2')
    delivered = local.read(note_ids=['EXP-SYNTHETIC'], view=view)
    note = delivered['notes'][0]
    if damage == 'content':
        note['content']['facts'] = ['SYNTHETIC tampered delivery.']
    elif damage == 'write_id':
        note['write_id'] = 'other-writer'
    elif damage == 'markdown':
        note['markdown'] = 'SYNTHETIC invalid Markdown.'
    elif damage == 'missing_markdown':
        note.pop('markdown', None)
        if view == 'content':
            note['markdown'] = 'SYNTHETIC unexpected field.'
    elif damage == 'missing_metadata':
        del note['source_validation']
    elif damage == 'status':
        delivered['status'] = 'storage_unavailable'
    evidence = tmp_path / 'runs/checks/codex-mcp-experience-synthetic.jsonl'
    evidence.parent.mkdir(parents=True)
    evidence.write_text('\n'.join(json.dumps(row) for row in [
        {'evidence_type': 'codex_actual_mcp_construction', 'formal_game': False, 'synthetic_fixture': True},
        {'tool': 'read_notes', 'parameters': {'view': view}, 'result': delivered},
    ]) + '\n', encoding='utf-8')
    before = snapshot(baseline.root)
    monkeypatch.setattr(disk_check, 'ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['disk-check', '--kind', 'experience', '--note-id', 'EXP-SYNTHETIC',
        '--revision', '2', '--evidence', str(evidence.relative_to(tmp_path)),
        '--output', 'runs/checks/disk.json'])
    if damage is None:
        disk_check.main()
        report = json.loads((tmp_path / 'runs/checks/disk.json').read_text(encoding='utf-8'))
        assert report['disk_matches_actual_delivery'] and not report['counts_as_formal_experience']
        assert report['current_revision'] == 2 and report['matching_actual_lines'] == [2]
    else:
        with pytest.raises(AssertionError, match='No matching actual delivered note'):
            disk_check.main()
        assert not (tmp_path / 'runs/checks/disk.json').exists()
    assert snapshot(baseline.root) == before


def test_source_upgrade_after_interrupted_first_commit_preserves_the_pending_branch(layered, monkeypatch):
    base, config = layered
    service = NotesService(config)
    original = os.replace
    def fail_head(source, destination):
        if Path(destination).name == 'HEAD.json':
            raise OSError('SYNTHETIC interrupted HEAD')
        original(source, destination)
    monkeypatch.setattr(os, 'replace', fail_head)
    assert service.write_note('EXP-SYNTHETIC', fixture_content('pending personal revision'), 2, 'pending-3')['status'] == 'storage_unavailable'
    monkeypatch.setattr(os, 'replace', original)
    pending = snapshot(config.notes_dir)
    commit(base, 'new official revision', 2, 'official-3')
    official = snapshot(base.root)
    fresh = NotesService(config)
    assert fresh.read_notes()['notes'][0]['content'] == fixture_content('new official revision')
    assert fresh.write_note('EXP-SYNTHETIC', fixture_content('pending personal revision'), 2, 'pending-3')['status'] == 'revision_conflict'
    assert fresh.write_note('EXP-SYNTHETIC', fixture_content('fresh request'), 3, 'fresh-4')['status'] == 'store_corrupt'
    assert snapshot(config.notes_dir) == pending
    assert snapshot(base.root) == official


def test_shipped_baseline_contains_valid_complete_history_and_all_guides():
    root = Path(__file__).resolve().parents[1]
    store = NotesStore(root / 'experience')
    rows = store.read(view='content')['notes']
    assert len(rows) == 12
    count = 0
    for row in rows:
        for revision in range(1, row['revision'] + 1):
            assert store._revision('experience', row['note_id'], revision)['revision'] == revision
            count += 1
    assert count == 61


def test_nested_baseline_and_local_roots_are_rejected_without_creating_files(tmp_path):
    for local, base in ((tmp_path, tmp_path / 'baseline'), (tmp_path / 'local', tmp_path), (tmp_path, tmp_path)):
        with pytest.raises(ValueError, match='unsafe_path'):
            NotesStore(local, baseline_root=base)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('tool,explicit_view', [('read_notes', None), ('write_note', None), ('write_note', 'content')])
def test_independent_verifier_accepts_current_default_content_receipts(tmp_path, monkeypatch, tool, explicit_view):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('synthetic_default_disk_check', root/'scripts/check_notes_persistence.py')
    disk_check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(disk_check)
    store = NotesStore(tmp_path/'runs/local-experience', baseline_root=tmp_path/'experience')
    commit(store, 'synthetic default content receipt')
    read = store.read(note_ids=['EXP-SYNTHETIC'], view='content')
    delivered = read if tool == 'read_notes' else {'status': 'ok', 'write_state': 'COMMITTED', 'note': read['notes'][0]}
    parameters = {} if explicit_view is None else {'view': explicit_view}
    evidence = tmp_path/'runs/checks/codex-mcp-experience-synthetic-default.jsonl'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text('\n'.join(json.dumps(row) for row in [
        {'evidence_type': 'codex_actual_mcp_construction', 'formal_game': False, 'synthetic_fixture': True},
        {'tool': tool, 'parameters': parameters, 'result': delivered}])+'\n', encoding='utf-8')
    monkeypatch.setattr(disk_check, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['disk-check', '--kind', 'experience', '--note-id', 'EXP-SYNTHETIC',
        '--revision', '1', '--evidence', str(evidence.relative_to(tmp_path)), '--output', 'runs/checks/default-disk.json'])
    disk_check.main()
    report = json.loads((evidence.parent/'default-disk.json').read_text(encoding='utf-8'))
    assert report['disk_matches_actual_delivery'] and not report['counts_as_formal_experience']
