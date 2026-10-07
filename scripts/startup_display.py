"""Fixed-path display preferences and read-only maintenance diagnostics."""
from datetime import datetime, timezone
import json
from pathlib import Path

from balatro_agent.local_audit import make_dir, no_links, safe_path
from balatro_agent.windows_game import GameProcessError, WindowsGame
from update_mod import write_atomic


DEFAULTS = {'hide_console': True, 'hide_loading': True}
SOURCE_OPTIONS = 'local options = {hide_console = true, hide_loading = true}'


def validate_options(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS) or any(type(v) is not bool for v in value.values()):
        raise ValueError('Invalid startup display preferences')
    return value


def read_options(root):
    path = safe_path(root, 'config', 'startup-ui.local.json')
    try:
        if path.stat().st_size > 2048:
            raise ValueError('Startup preferences exceed the size limit')
        return validate_options(json.loads(path.read_text(encoding='utf-8-sig')))
    except FileNotFoundError:
        return dict(DEFAULTS)


def configure(root, *, console=None, loading=None):
    if console is None and loading is None:
        raise ValueError('Choose at least one display preference')
    options = dict(read_options(root))
    for key, value in (('hide_console', console), ('hide_loading', loading)):
        if value is not None:
            if type(value) is not bool:
                raise ValueError('Display preferences must be boolean')
            options[key] = value
    path = safe_path(root, 'config', 'startup-ui.local.json')
    make_dir(path.parent)
    write_atomic(path, (json.dumps(options, indent=2) + '\n').encode())
    return {'status': 'configured_not_deployed', 'options': options,
            'preferences': 'config/startup-ui.local.json', 'game_state_changed': False,
            'requires_build_and_update': True}


def render_source(source, options):
    validate_options(options)
    if source.count(SOURCE_OPTIONS) != 1:
        raise ValueError('Startup source options marker changed')
    fields = ', '.join(key + ' = ' + str(options[key]).lower() for key in DEFAULTS)
    return source.replace(SOURCE_OPTIONS, 'local options = {' + fields + '}')


def checkpoint_state(root, area, keys):
    try:
        path = safe_path(root, 'runs', 'live', area, 'checkpoint.json')
        if path.stat().st_size > 8192:
            return 'invalid'
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict) or set(value) != keys:
            return 'invalid'
        return 'clear' if all(value[k] is None for k in keys) else 'pending'
    except FileNotFoundError:
        return 'missing'
    except (OSError, ValueError, TypeError):
        return 'unavailable'


def log_metadata(root):
    result = {'location': '%APPDATA%/Balatro/Mods/lovely/log', 'contents_read': False}
    try:
        ledger = safe_path(root, 'runs', 'checks', 'current-installation.json')
        if ledger.stat().st_size > 1024 * 1024:
            raise ValueError('Installation ledger exceeds the size limit')
        files = json.loads(ledger.read_text(encoding='utf-8-sig'))['installed_files']
        roots = {Path(i['path']).absolute().parent for i in files if Path(i['path']).name == 'balatrobot.json'}
        if len(roots) != 1:
            raise ValueError('No unique recorded installation')
        mod = roots.pop()
        if mod.name != 'balatrobot' or mod.parent.name != 'Mods':
            raise ValueError('Unrecognized Mod directory')
        path = mod.parent / 'lovely' / 'log'
        no_links(path)
        if not path.is_dir():
            return {**result, 'status': 'missing'}
        count, total, latest = 0, 0, None
        for item in path.glob('lovely-*.log'):
            if count >= 1000:
                return {**result, 'status': 'limit_exceeded'}
            no_links(item)
            if not item.is_file():
                continue
            stat = item.stat()
            count += 1
            total += stat.st_size
            latest = max(latest or stat.st_mtime, stat.st_mtime)
        return {**result, 'status': 'available', 'files': count, 'bytes': total,
                'latest_modified_utc': datetime.fromtimestamp(latest, timezone.utc).isoformat() if latest is not None else None}
    except (OSError, ValueError, KeyError, TypeError):
        return {**result, 'status': 'unavailable'}


def diagnose(root, static_status, backend=None):
    try:
        display = {'status': 'ok', 'requested': read_options(root),
                   'runtime_verified': False, 'fixed_steamodded': '26.829.0'}
    except (OSError, ValueError, TypeError):
        display = {'status': 'preferences_unavailable', 'runtime_verified': False}
    try:
        backend = backend or WindowsGame(safe_path(root, 'config', 'game-lifecycle.local.json'))
        process = {'state': 'running' if backend.find() is not None else 'stopped'}
    except GameProcessError as exc:
        known = {'windows_only', 'installation_unverified', 'process_unverified', 'multiple_game_processes'}
        process = {'state': 'unverified', 'reason': exc.code if exc.code in known else 'process_unverified'}
    except Exception:
        process = {'state': 'unverified', 'reason': 'process_unverified'}
    checkpoints = {'executor': checkpoint_state(root, 'executor', {'pending', 'input_pending'}),
                   'lifecycle': checkpoint_state(root, 'lifecycle', {'pending'})}
    return {'evidence_type': 'readonly_startup_diagnostics', 'utc': datetime.now(timezone.utc).isoformat(),
            'static_status': static_status, 'process': process, 'checkpoints': checkpoints,
            'display': display, 'lovely_logs': log_metadata(root),
            'game_information_read': False, 'game_actions_submitted': False,
            'interface_check': 'Use the connected MCP health tool; this command does not contact the game.',
            'startup_stage': 'not_observed', 'startup_duration_ms': None}


def save_report(root, output, report):
    path = safe_path(root, *Path(output).parts)
    if not path.is_relative_to(root / 'runs' / 'checks') or path.exists():
        raise ValueError('Use a new diagnostic output under runs/checks')
    make_dir(path.parent)
    write_atomic(path, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
