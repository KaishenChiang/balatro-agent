"""Maintenance cannot expose raw logs/checkpoints or silently install changes."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import startup_display as display
from balatro_agent.windows_game import GameProcessError


class Backend:
    def __init__(self, running=False, error=None):
        self.running, self.error = running, error

    def find(self):
        if self.error:
            raise self.error
        return object() if self.running else None


def test_defaults_are_hidden_without_creating_preferences(tmp_path):
    assert display.read_options(tmp_path) == display.DEFAULTS
    assert not (tmp_path / 'config').exists()


def test_preferences_are_independent_and_do_not_build_or_install(tmp_path):
    first = display.configure(tmp_path, console=False)
    assert first['status'] == 'configured_not_deployed'
    assert first['options'] == {'hide_console': False, 'hide_loading': True}
    second = display.configure(tmp_path, loading=False)
    assert second['options'] == {'hide_console': False, 'hide_loading': False}
    assert not second['game_state_changed'] and second['requires_build_and_update']
    assert not (tmp_path / '.artifacts').exists()


@pytest.mark.parametrize('value', [None, [], {'hide_console': 1, 'hide_loading': True},
                                 {'hide_console': True}, {**display.DEFAULTS, 'arbitrary': 'private'}])
def test_unknown_or_invalid_preferences_are_rejected_and_preserved(tmp_path, value):
    path = tmp_path / 'config/startup-ui.local.json'
    path.parent.mkdir()
    original = json.dumps(value)
    path.write_text(original)
    with pytest.raises(ValueError):
        display.read_options(tmp_path)
    assert path.read_text() == original


def test_oversized_preferences_are_rejected(tmp_path):
    path = tmp_path / 'config/startup-ui.local.json'
    path.parent.mkdir()
    path.write_text(' ' * 2049)
    with pytest.raises(ValueError):
        display.read_options(tmp_path)


def test_render_is_deterministic_and_marker_drift_is_rejected():
    source = (ROOT / 'mod/startup_ui.lua').read_text(encoding='utf-8')
    assert display.render_source(source, display.DEFAULTS) == source
    actual = display.render_source(source, {'hide_console': False, 'hide_loading': True})
    assert 'hide_console = false, hide_loading = true' in actual
    with pytest.raises(ValueError):
        display.render_source(source + '\n' + display.SOURCE_OPTIONS, display.DEFAULTS)


@pytest.mark.parametrize('running', [False, True])
def test_diagnostics_process_metadata_never_reads_game_or_authorizes_actions(tmp_path, running):
    result = display.diagnose(tmp_path, {'live_game_verified': False}, Backend(running))
    assert result['process']['state'] == ('running' if running else 'stopped')
    assert result['startup_stage'] == 'not_observed' and result['startup_duration_ms'] is None
    assert not result['game_information_read'] and not result['game_actions_submitted']
    assert result['checkpoints'] == {'executor': 'missing', 'lifecycle': 'missing'}
    assert not result['display']['runtime_verified']


@pytest.mark.parametrize('error,reason', [(GameProcessError('private path'), 'process_unverified'),
                                        (GameProcessError('multiple_game_processes'), 'multiple_game_processes'),
                                        (RuntimeError('private path'), 'process_unverified')])
def test_process_errors_are_filtered(tmp_path, error, reason):
    result = display.diagnose(tmp_path, {}, Backend(error=error))
    assert result['process'] == {'state': 'unverified', 'reason': reason}
    assert 'private' not in json.dumps(result)


def test_checkpoint_records_are_not_exported(tmp_path):
    folder = tmp_path / 'runs/live/executor'
    folder.mkdir(parents=True)
    path = folder / 'checkpoint.json'
    path.write_text(json.dumps({'pending': 'private-action', 'input_pending': None}))
    result = display.diagnose(tmp_path, {}, Backend())
    assert result['checkpoints']['executor'] == 'pending'
    assert 'private-action' not in json.dumps(result)
    path.write_text(json.dumps({'hidden': 'private-state'}))
    assert display.diagnose(tmp_path, {}, Backend())['checkpoints']['executor'] == 'invalid'


def test_log_metadata_does_not_read_or_export_log_contents(tmp_path, monkeypatch):
    mod = tmp_path / 'Roaming/Balatro/Mods/balatrobot'
    logs = mod.parent / 'lovely/log'
    logs.mkdir(parents=True)
    (logs / 'lovely-2026.log').write_text('private hidden card or raw error')
    ledger = tmp_path / 'runs/checks/current-installation.json'
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({'installed_files': [{'path': str(mod / 'balatrobot.json')}]}))
    original = Path.read_text
    def read(path, *args, **kwargs):
        if path.suffix == '.log':
            pytest.fail('Raw log read')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    result = display.diagnose(tmp_path, {}, Backend())
    assert result['lovely_logs']['status'] == 'available'
    assert result['lovely_logs']['files'] == 1
    assert not result['lovely_logs']['contents_read']
    assert 'private' not in json.dumps(result)


def test_report_preserves_existing_evidence_and_rejects_escape(tmp_path):
    display.save_report(tmp_path, 'runs/checks/startup.json', {'status': 'safe'})
    with pytest.raises(ValueError):
        display.save_report(tmp_path, 'runs/checks/startup.json', {'status': 'overwrite'})
    for path in ('outside.json', '../escape.json'):
        with pytest.raises(ValueError):
            display.save_report(tmp_path, path, {})
    assert json.loads((tmp_path / 'runs/checks/startup.json').read_text()) == {'status': 'safe'}


def test_new_maintenance_sources_and_example_are_in_allowlist():
    import package_source
    files = {p.relative_to(ROOT).as_posix() for p in package_source.selected_files(ROOT)}
    assert {'scripts/startup_display.py', 'config/startup-ui.example.json',
            'tests/test_startup_maintenance.py'} <= files
    assert 'config/startup-ui.local.json' not in files
