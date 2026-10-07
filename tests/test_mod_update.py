"""Runtime replacement preserves saves/config and refuses drift/UNKNOWN/races."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import update_mod as updater


class Backend:
    def __init__(self):
        self.calls = 0
        self.open_at = None

    def find(self):
        self.calls += 1
        return object() if self.open_at and self.calls >= self.open_at else None


@pytest.fixture
def layout(tmp_path, monkeypatch):
    root = tmp_path / 'checkout'
    mod = tmp_path / 'Roaming/Balatro/Mods/balatrobot'
    build = root / '.artifacts/built-mod/balatrobot'
    old = {'balatrobot.json': b'fixed manifest', 'reader/reader.lua': b'old reader',
           'reader/executor.lua': b'old executor', 'reader-profile.json': b'{"profile":2,"native_ui_verified":true}',
           'reader/startup_ui.lua': b'keep cosmetic'}
    for relative, data in old.items():
        path = mod / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        prepared = build / relative
        prepared.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_bytes(data)
    (build / 'reader/reader.lua').write_bytes(b'new reader')
    (build / 'reader/executor.lua').write_bytes(b'new executor')
    (build / 'reader-profile.json').write_bytes(b'{"native_ui_verified":false}')
    checks = root / 'runs/checks'
    checks.mkdir(parents=True)
    ledger = {'installed_files': [{'path': str(mod / relative), 'sha256': updater.digest(mod / relative), 'bytes': len(data)}
                                  for relative, data in old.items()]}
    other = mod.parent / 'other_mod/keep.lua'
    other.parent.mkdir()
    other.write_bytes(b'other Mod')
    ledger['installed_files'].append({'path': str(other), 'sha256': updater.digest(other), 'bytes': other.stat().st_size})
    (checks / 'current-installation.json').write_text(json.dumps(ledger), encoding='utf-8')
    (root / 'mod').mkdir()
    manifest = {'files': [{'path': p.relative_to(build).as_posix(), 'sha256': updater.digest(p)}
                          for p in build.rglob('*') if p.is_file()]}
    (root / 'mod/build-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (root / 'pyproject.toml').write_text('[project]\nversion="0.4.0"', encoding='utf-8')
    for area, checkpoint in [('executor', {'pending': None, 'input_pending': None}), ('lifecycle', {'pending': None})]:
        path = root / 'runs/live' / area / 'checkpoint.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(checkpoint), encoding='utf-8')
    (root / 'config').mkdir()
    profile = root / 'config/test-profile.local.json'
    profile.write_bytes(b'local attestation')
    saved = mod.parent.parent / '2/save.jkr'
    saved.parent.mkdir()
    saved.write_bytes(b'opaque synthetic compressed data')
    client = tmp_path / 'client'
    client.mkdir()
    (client / 'config.toml').write_bytes(b'client setting preserved')
    monkeypatch.setenv('CODEX_HOME', str(client))
    return root, mod, build, saved, client, Backend()


def test_runtime_update_backs_up_bytes_and_preserves_attestations_saves_and_other_mods(layout):
    root, mod, _, saved, client, backend = layout
    before = {p: p.read_bytes() for p in [saved, mod / 'reader-profile.json', mod / 'reader/startup_ui.lua',
                                         mod.parent / 'other_mod/keep.lua', client / 'config.toml']}
    plan = updater.make_plan(root, backend)
    assert {i['relative'] for i in plan['changes']} == {'reader/reader.lua', 'reader/executor.lua'}
    result = updater.apply_plan(plan, root, root / 'runs/checks/applied.json', backend)
    assert result['complete'] and result['backup_verified'] and result['profile_attestation_preserved']
    assert not result['saves_decoded'] and not result['game_started']
    assert all(p.read_bytes() == data for p, data in before.items())
    proof = updater.read_json(Path(result['backup']) / 'manifest.json')
    assert all(updater.digest(Path(result['backup']) / item['backup_relative']) == item['sha256'] for item in proof['originals'])
    assert (Path(result['backup']) / 'mod/reader/reader.lua').read_bytes() == b'old reader'
    assert (Path(result['backup']) / 'Balatro/2/save.jkr').read_bytes() == before[saved]
    ledger = updater.read_json(root / 'runs/checks/current-installation.json')
    assert all(updater.digest(Path(i['path'])) == i['sha256'] for i in ledger['installed_files'])


@pytest.mark.parametrize('drift', ['installed', 'source', 'save', 'profile', 'client'])
def test_frozen_plan_rejects_drift_before_any_runtime_replacement(layout, drift):
    root, mod, build, saved, client, backend = layout
    plan = updater.make_plan(root, backend)
    path = {'installed': mod / 'reader/reader.lua', 'source': build / 'reader/reader.lua',
            'save': saved, 'profile': mod / 'reader-profile.json', 'client': client / 'config.toml'}[drift]
    path.write_bytes(b'new user change')
    before = (mod / 'reader/executor.lua').read_bytes()
    with pytest.raises(ValueError):
        updater.apply_plan(plan, root, root / 'runs/checks/applied.json', backend)
    assert (mod / 'reader/executor.lua').read_bytes() == before
    assert path.read_bytes() == b'new user change'
    assert not (root / 'runs/checks/applied.json').exists()


def test_game_reopening_after_backup_refuses_before_runtime_write(layout):
    root, mod, _, _, _, backend = layout
    plan = updater.make_plan(root, backend)
    backend.open_at = 3  # First apply check passes; post-backup check sees the game.
    with pytest.raises(ValueError, match='normally closed'):
        updater.apply_plan(plan, root, root / 'runs/checks/applied.json', backend)
    assert (mod / 'reader/reader.lua').read_bytes() == b'old reader'
    assert list((root / '.artifacts/backups').glob('*/manifest.json'))


def test_unknown_checkpoint_is_never_cleared_by_maintenance(layout):
    root, _, _, _, _, backend = layout
    checkpoint = root / 'runs/live/executor/checkpoint.json'
    data = b'{"pending":{"action_id":"unknown-original"},"input_pending":null}'
    checkpoint.write_bytes(data)
    with pytest.raises(ValueError, match='Unresolved'):
        updater.make_plan(root, backend)
    assert checkpoint.read_bytes() == data


@pytest.mark.parametrize('value', ['../escape.lua', '/escape.lua', 'C:/escape.lua', 'folder\\escape.lua'])
def test_runtime_manifest_paths_cannot_escape_exact_roots(layout, value):
    root, _, _, _, _, backend = layout
    path = root / 'mod/build-manifest.json'
    manifest = updater.read_json(path)
    manifest['files'][0]['path'] = value
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='Unsafe'):
        updater.make_plan(root, backend)


def test_partial_failure_keeps_verified_backup_and_reports_the_actual_replacements(layout, monkeypatch):
    root, mod, _, _, _, backend = layout
    plan = updater.make_plan(root, backend)
    replace = updater.os.replace

    def failed_second(source, target):
        if Path(target) == Path(plan['changes'][1]['target']):
            raise OSError('synthetic disk failure')
        return replace(source, target)

    monkeypatch.setattr(updater.os, 'replace', failed_second)
    report = root / 'runs/checks/applied.json'
    with pytest.raises(OSError):
        updater.apply_plan(plan, root, report, backend)
    result = updater.read_json(report)
    assert not result['complete'] and len(result['installed']) == 1
    first, second = plan['changes']
    assert updater.digest(Path(first['target'])) == first['after_sha256']
    assert updater.digest(Path(second['target'])) == second['before_sha256']
    assert (Path(result['backup']) / 'mod/reader/reader.lua').read_bytes() == b'old reader'
