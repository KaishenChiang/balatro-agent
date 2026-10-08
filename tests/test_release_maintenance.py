"""Release checks preserve installation facts and earlier release evidence."""
import json
import sys

import pytest

from test_setup import ROOT

sys.path.insert(0, str(ROOT / 'scripts'))
import project
import package_source
import stdio_smoke


def source_ready():
    return {'single_stdio_entrypoint': True, 'packaged_gui_launcher_verified': True,
            'bundled_dependencies_verified': True, 'built_runtime_hashes_match': True,
            'fixed_downloads': [{'hash_match': True}]}


def test_source_release_can_pass_while_old_installation_mismatch_remains_visible():
    status = source_ready() | {'installed_hashes_match': False, 'installed_runtime_matches_build': False}
    assert not project.check_health(status)['static_checks_passed']
    assessed = project.check_health(status, source_only=True)
    assert assessed['static_checks_passed'] and assessed['source_status_passed']
    assert assessed['recorded_installation_passed'] is False
    assert status['installed_hashes_match'] is False


@pytest.mark.parametrize('field', ['packaged_gui_launcher_verified', 'bundled_dependencies_verified',
                                  'built_runtime_hashes_match', 'single_stdio_entrypoint', 'fixed_downloads'])
def test_source_only_cannot_hide_invalid_source_or_bundles(field):
    status = source_ready()
    status[field] = [] if field == 'fixed_downloads' else False
    assert not project.check_health(status, source_only=True)['static_checks_passed']


def test_missing_installation_is_not_reported_as_verified():
    assessed = project.check_health(source_ready(), source_only=True)
    assert assessed['static_checks_passed']
    assert assessed['recorded_installation_passed'] is None


def test_check_refuses_to_overwrite_old_report_before_running_tests(tmp_path, monkeypatch):
    monkeypatch.setattr(project, 'ROOT', tmp_path)
    target = tmp_path / 'runs/checks/old.json'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'original evidence')
    with pytest.raises(ValueError, match='Preserve previous'):
        project.check('runs/checks/old.json', source_only=True)
    assert target.read_bytes() == b'original evidence'
    assert not (tmp_path / '.artifacts').exists()


def test_explicit_release_check_report_is_confined_to_checks_directory(tmp_path, monkeypatch):
    snapshot = [{'path': 'src/example.py', 'sha256': 'a' * 64}]
    monkeypatch.setattr(package_source, 'source_snapshot', lambda root: snapshot)
    report = {'synthetic': {'tests': 5, 'failures': 0, 'errors': 0, 'skipped': 0},
              'pytest_exit_code': 0, 'development_stdio_exit_code': 0,
              'source_unchanged_during_check': True, 'source_snapshot': snapshot,
              'status': source_ready() | {'version': '1.0.0'}}
    target = tmp_path / 'runs/checks/release-1.0.0.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(report), encoding='utf-8')
    assert package_source.require_source_check(tmp_path, '1.0.0', 'runs/checks/release-1.0.0.json') == report
    with pytest.raises(ValueError, match='belongs under'):
        package_source.require_source_check(tmp_path, '1.0.0', '../outside.json')


def test_development_stdio_server_blocks_real_game_transport(monkeypatch):
    import asyncio
    from balatro_agent import server
    from balatro_agent.transport import ReaderError
    from balatro_agent.settings import Settings
    monkeypatch.setenv('BALATRO_AGENT_CLIENT_CONTEXT', 'development')
    monkeypatch.setattr(server, 'main', lambda: None)
    class IdleClient:
        async def close(self):
            pass
    monkeypatch.setattr(server.reader, 'client', IdleClient())
    monkeypatch.setattr(server.reader, 'settings', Settings.runtime())
    try:
        stdio_smoke.isolated_server()
        for method in ('health', 'reader_snapshot'):
            with pytest.raises(ReaderError, match='disconnected'):
                asyncio.run(server.reader.client.read(method))
        assert server.reader.settings.client_context == 'development'
    finally:
        asyncio.run(server.reader.client.close())
