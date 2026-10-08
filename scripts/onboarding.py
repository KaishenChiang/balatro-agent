"""Automatic preparation and read-only reuse through project.py; no model/game launch."""
import asyncio
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import tomllib
import uuid

from balatro_agent.windows_game import Installation, WindowsGame
from install_portable import TOOLS, installation_paths, prepare_installation
from bootstrap_sources import digest, no_links
from update_mod import ensure_idle, read_json, run as update_runtime, write_atomic, relative_file
from balatro_agent.installation_registry import (
    InstallationRegistry, SCHEMA as REGISTRY_SCHEMA, TRACKING, ENVIRONMENT_KEY, registry_path)


class NeedsPreparation(Exception):
    pass


LEGACY_TOOLS = [tool for tool in TOOLS if tool != 'run_plan']


def tools_match(tools, *, allow_legacy=False):
    if not isinstance(tools, list) or any(not isinstance(tool, str) for tool in tools):
        return False
    choices = (TOOLS, LEGACY_TOOLS) if allow_legacy else (TOOLS,)
    return any(len(tools) == len(choice) and set(tools) == set(choice) for choice in choices)


def client_entry(root):
    return {'command': str(root / '.venv/Scripts/python.exe'),
            'args': ['-m', 'balatro_agent.server'], 'cwd': str(root),
            'enabled': True, 'enabled_tools': TOOLS,
            'startup_timeout_sec': 20, 'tool_timeout_sec': 45,
            'env': {'BALATRO_AGENT_CLIENT_CONTEXT': 'codex_config'}}


def client_ready(root, config, *, allow_legacy=False):
    no_links(config)
    parsed = tomllib.loads(config.read_text(encoding='utf-8-sig')) if config.exists() else {}
    entry = parsed.get('mcp_servers', {}).get('balatro-agent')
    if entry is None:
        return False
    expected = client_entry(root)
    paths_match = all(isinstance(entry.get(key), str) and Path(entry[key]) == Path(expected[key])
                      for key in ('command', 'cwd'))
    tools = entry.get('enabled_tools', TOOLS)
    matches_tools = tools_match(tools, allow_legacy=allow_legacy)
    environment = entry.get('env', {})
    if not (paths_match and entry.get('args') == expected['args']
            and entry.get('enabled', True) is True and matches_tools
            and isinstance(environment, dict) and environment.get('BALATRO_AGENT_CLIENT_CONTEXT') == 'codex_config'):
        raise ValueError('Existing balatro-agent config differs; preserve it and inspect the client configuration')
    return True


def client_identity(config):
    """Verify our service identity while allowing its two paths to be stale."""
    no_links(config)
    entry = tomllib.loads(config.read_text(encoding='utf-8-sig')).get('mcp_servers', {}).get('balatro-agent')
    if not isinstance(entry, dict):
        raise ValueError('Existing balatro-agent registration is unavailable; preserve the client configuration')
    command, cwd = entry.get('command'), entry.get('cwd')
    tools = entry.get('enabled_tools', TOOLS)
    env = entry.get('env', {})
    if (not isinstance(command, str) or not Path(command).is_absolute()
            or tuple(p.lower() for p in Path(command).parts[-3:]) != ('.venv', 'scripts', 'python.exe')
            or not isinstance(cwd, str) or not Path(cwd).is_absolute()
            or entry.get('args') != ['-m', 'balatro_agent.server']
            or entry.get('enabled', True) is not True
            or not tools_match(tools, allow_legacy=True)
            or not isinstance(env, dict) or env.get('BALATRO_AGENT_CLIENT_CONTEXT') != 'codex_config'
            or env.get(ENVIRONMENT_KEY) is not None and (not isinstance(env[ENVIRONMENT_KEY], str) or Path(env[ENVIRONMENT_KEY]) != registry_path(config))):
        raise ValueError('Existing balatro-agent config differs; preserve it and inspect the client configuration')
    return entry


def tracked_client_bytes(before, config):
    """Add only our independent checkpoint path, preserving other TOML bytes."""
    text = before.decode('utf-8-sig')
    expected = tomllib.loads(text)
    environment = expected['mcp_servers']['balatro-agent']['env']
    desired = str(registry_path(config))
    if ENVIRONMENT_KEY in environment:
        if Path(environment[ENVIRONMENT_KEY]) != Path(desired):
            raise ValueError('Existing independent registration path differs; preserve it')
        return before
    headers = list(re.finditer(r"(?m)^\[mcp_servers\.(?:balatro-agent|\"balatro-agent\"|'balatro-agent')\.env\][ \t]*(?:#[^\r\n]*)?\r?$", text))
    if len(headers) != 1:
        raise ValueError('Existing client environment cannot safely be updated; preserve the configuration')
    newline = '\r\n' if headers[0].group().endswith('\r') else '\n'
    position = headers[0].end()
    line = ENVIRONMENT_KEY + ' = ' + json.dumps(desired, ensure_ascii=False) + newline
    if text[position:position + 1] == '\n':
        position += 1
    else:
        line = newline + line
    result = text[:position] + line + text[position:]
    environment[ENVIRONMENT_KEY] = desired
    if tomllib.loads(result) != expected:
        raise ValueError('Unrelated client configuration changed')
    return (b'\xef\xbb\xbf' if before.startswith(b'\xef\xbb\xbf') else b'') + result.encode('utf-8')


def backup_client_change(root, config, candidate, kind):
    before = config.read_bytes()
    backup = root / '.artifacts/backups' / (kind + '-' + uuid.uuid4().hex)
    no_links(backup); backup.mkdir(parents=True)
    original = backup / 'config-before.toml'
    original.write_bytes(before)
    if original.read_bytes() != before:
        raise ValueError('Client backup verification failed')
    write_atomic(backup / 'manifest.json', json.dumps({'verified': True,
        'target': str(config), 'sha256': digest(original)}).encode())
    if config.read_bytes() != before:
        raise ValueError('Client configuration changed during preparation')
    write_atomic(config, candidate)
    if config.read_bytes() != candidate:
        raise ValueError('Client registration verification failed')


def registry_ready(registry, root, steam, library, mods, config, entries):
    value = registry.read()
    if value is None:
        return False
    if (Path(value.get('config', '')) != config or Path(value.get('steam_dir', '')) != steam
            or Path(value.get('library_dir', '')) != library or Path(value.get('mods', '')) != mods):
        raise ValueError('Independent installation paths differ; preserve the receipt')
    return Path(value['root']) == root and value['installed_files'] == entries


def publish_registry(registry, root, steam, library, mods, config, entries):
    previous = registry.read()
    backend = WindowsGame(root / 'config/game-lifecycle.local.json')
    ensure_idle(root, backend)
    if previous is not None:
        previous_root = Path(previous['root'])
        registry_ready(registry, previous_root, steam, library, mods, config, previous['installed_files'])
        registry.ensure_idle(previous_root)
        ensure_idle(previous_root, backend)
    before = config.read_bytes()
    candidate = tracked_client_bytes(before, config)
    if candidate != before:
        backup_client_change(root, config, candidate, 'checkpoint-registration')
    ensure_idle(root, backend)
    registry.publish({'schema': REGISTRY_SCHEMA, 'checkpoint_tracking': TRACKING,
        'root': str(root), 'config': str(config), 'steam_dir': str(steam),
        'library_dir': str(library), 'mods': str(mods), 'installed_files': entries})


def ensure_client(root, config):
    if client_ready(root, config):
        return
    before = config.read_bytes() if config.exists() else b''
    snippet = '\n\n[mcp_servers.balatro-agent]\n'
    for key, value in client_entry(root).items():
        if key != 'env':
            snippet += key + ' = ' + json.dumps(value, ensure_ascii=False) + '\n'
    snippet += '\n[mcp_servers.balatro-agent.env]\nBALATRO_AGENT_CLIENT_CONTEXT = "codex_config"\n'
    candidate = before.decode('utf-8-sig') + snippet
    parsed = tomllib.loads(candidate)
    del parsed['mcp_servers']['balatro-agent']
    expected = tomllib.loads(before.decode('utf-8-sig'))
    expected.setdefault('mcp_servers', {})
    if parsed != expected:
        raise ValueError('Unrelated client configuration changed')
    backup = root / '.artifacts/backups' / ('client-' + uuid.uuid4().hex)
    no_links(backup)
    backup.mkdir(parents=True)
    original = backup / 'config-before.toml'
    original.write_bytes(before)
    if original.read_bytes() != before:
        raise ValueError('Client backup verification failed')
    write_atomic(backup / 'manifest.json', json.dumps({
        'target': str(config), 'sha256': digest(original), 'verified': True
    }).encode())
    no_links(config)
    if (config.read_bytes() if config.exists() else b'') != before:
        raise ValueError('Client configuration changed during preparation')
    config.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(config, candidate.encode('utf-8'))
    if not client_ready(root, config):
        raise ValueError('Client registration verification failed')


def relocated_client_bytes(before, previous, root):
    """Repair project paths and a known legacy tool list, preserving other bytes."""
    text = before.decode('utf-8-sig')
    parsed = tomllib.loads(text)
    expected = tomllib.loads(text)
    expected['mcp_servers']['balatro-agent'].update(
        command=client_entry(root)['command'], cwd=str(root))
    headers = list(re.finditer(
        r"(?m)^\[mcp_servers\.(?:balatro-agent|\"balatro-agent\"|'balatro-agent')\][ \t]*(?:#[^\r\n]*)?\r?$", text))
    if len(headers) != 1:
        raise ValueError('Existing client paths cannot safely be updated; preserve the configuration')
    start = headers[0].end()
    following = re.search(r'(?m)^[ \t]*\[', text[start:])
    end = start + following.start() if following else len(text)
    block = text[start:end]
    for key, value in [('command', client_entry(root)['command']), ('cwd', str(root))]:
        pattern = re.compile(r"(?m)^([ \t]*" + key + r"[ \t]*=[ \t]*)(\"(?:[^\"\\\r\n]|\\.)*\"|'[^'\r\n]*')([ \t]*(?:#[^\r\n]*)?\r?$)")
        matches = list(pattern.finditer(block))
        if len(matches) != 1:
            raise ValueError('Existing client paths cannot safely be updated; preserve the configuration')
        match = matches[0]
        block = block[:match.start(2)] + json.dumps(value, ensure_ascii=False) + block[match.end(2):]
    tools = parsed['mcp_servers']['balatro-agent'].get('enabled_tools', TOOLS)
    if not tools_match(tools, allow_legacy=True):
        raise ValueError('Existing client tools differ; preserve the configuration')
    if not tools_match(tools):
        matches = list(re.finditer(r'(?m)^[ \t]*enabled_tools[ \t]*=[ \t]*\[', block))
        if len(matches) != 1:
            raise ValueError('Existing client tools cannot safely be updated; preserve the configuration')
        position = matches[0].end()
        block = block[:position] + '"run_plan", ' + block[position:]
        expected['mcp_servers']['balatro-agent']['enabled_tools'] = ['run_plan', *tools]
    result = text[:start] + block + text[end:]
    if tomllib.loads(result) != expected or Path(parsed['mcp_servers']['balatro-agent']['cwd']) != previous:
        raise ValueError('Unrelated client configuration changed')
    return (b'\xef\xbb\xbf' if before.startswith(b'\xef\xbb\xbf') else b'') + result.encode('utf-8')


def pending_adoption(root, config):
    path = root / '.artifacts/installation-adoption.local.json'
    if not path.exists():
        return None
    plan = read_json(path)
    if plan.get('schema') != 'existing-installation-adoption-1' or Path(plan['root']) != root or Path(plan['config']) != config:
        raise ValueError('Recorded installation adoption paths changed; preserve the record')
    previous = Path(plan['previous_root'])
    no_links(previous)
    registered = Path(plan.get('registered_root', str(previous)))
    if previous == root or Path(client_identity(config)['cwd']) != registered:
        raise ValueError('Previous client registration changed; preserve the adoption record')
    backup = Path(plan['backup'])
    if not backup.is_relative_to(root / '.artifacts/backups'):
        raise ValueError('Unexpected installation adoption backup')
    manifest = read_json(backup / 'manifest.json')
    if manifest.get('verified') is not True:
        raise ValueError('Installation adoption backup is unverified')
    for item in manifest['files']:
        target = backup / relative_file(item['relative'])
        if digest(target) != item['sha256']:
            raise ValueError('Installation adoption backup changed; preserve it')
    if plan.get('registry_sha256'):
        registry = InstallationRegistry(registry_path(config))
        if digest(registry.path) != plan['registry_sha256']:
            raise ValueError('Independent installation receipt changed during adoption')
        registry.ensure_idle(previous)
        for area, expected in plan['independent_checkpoints'].items():
            if digest(registry.checkpoint_path(area)) != expected:
                raise ValueError('Independent checkpoint changed during adoption')
    if plan['previous_ledger_sha256'] is not None:
        ledger = previous / 'runs/checks/current-installation.json'
        if digest(ledger) != plan['previous_ledger_sha256'] or digest(backup / 'current-installation-before.json') != plan['previous_ledger_sha256']:
            raise ValueError('Previous installation record changed; preserve the adoption record')
    if digest(config) != plan['config_before_sha256'] or digest(backup / 'config-before.toml') != plan['config_before_sha256']:
        raise ValueError('Client configuration changed during adoption; preserve it')
    ensure_idle(previous, WindowsGame(root / 'config/game-lifecycle.local.json'))
    return plan


def adopt_registered_installation(root, steam, library, mods, config, registry=None):
    """Reuse only an idle, hash-verified installation belonging to the registered project."""
    parsed = tomllib.loads(config.read_text(encoding='utf-8-sig')) if config.exists() else {}
    entry = parsed.get('mcp_servers', {}).get('balatro-agent')
    if not isinstance(entry, dict) or not isinstance(entry.get('cwd'), str):
        return None
    independent = registry.read() if registry else None
    previous = Path(independent['root'] if independent else entry['cwd']).absolute()
    registered = Path(entry['cwd']).absolute()
    if previous == root and independent is None:
        return None
    no_links(previous)
    client_identity(config)
    if independent:
        registry_ready(registry, previous, steam, library, mods, config, independent['installed_files'])
        registry.ensure_idle(previous)
        entries = verify_installation_entries(independent['installed_files'], steam, library, mods)
        previous_ledger = previous / 'runs/checks/current-installation.json'
        if previous_ledger.exists() and recorded_installation(previous, steam, library, mods) != entries:
            raise ValueError('Previous installation record differs from its independent receipt; preserve it')
    else:
        if not client_ready(previous, config, allow_legacy=True):
            raise ValueError('Previous project registration could not be verified')
        project_path = previous / 'pyproject.toml'
        no_links(project_path)
        if not project_path.is_file() or tomllib.loads(project_path.read_text(encoding='utf-8'))['project'].get('name') != 'balatro-agent':
            raise ValueError(f'Previous registered project is unavailable: {previous}; no independent installation receipt is available. Preserve existing Mods and configuration')
        if installation_paths(previous) != (steam, library):
            raise ValueError('Previous installation paths changed; preserve the installation')
        entries = recorded_installation(previous, steam, library, mods)
    ledger = previous / 'runs/checks/current-installation.json'
    if entries is None or not independent and not ledger.is_file():
        raise ValueError('Previous installation record is unavailable; preserve existing Mods')
    lifecycle = root / 'config/game-lifecycle.local.json'
    settings = {'steam_dir': str(steam), 'library_dir': str(library)}
    if lifecycle.exists() and read_json(lifecycle) != settings:
        raise ValueError('Existing lifecycle config differs; preserve it')
    if not lifecycle.exists():
        write_atomic(lifecycle, (json.dumps(settings, indent=2) + '\n').encode())
    backend = WindowsGame(lifecycle)
    ensure_idle(previous, backend)
    ensure_idle(root, backend)
    if previous == root:
        # Re-downloading to the same path can remove the project-local ledger.
        # The independently mirrored idle checkpoints and installed bytes must
        # still verify before recreating that missing receipt.
        if ledger.exists():
            raise ValueError('Preserve the existing local installation record')
        registry.ensure_idle(root)
        save_ledger(root, entries)
        return None
    before = config.read_bytes()
    relocated_client_bytes(before, registered, root)  # Refuse unsupported TOML before writing metadata.
    plan = pending_adoption(root, config)
    if plan is None:
        backup = root / '.artifacts/backups' / ('installation-adoption-' + uuid.uuid4().hex)
        no_links(backup)
        backup.mkdir(parents=True)
        originals = [('config-before.toml', before)]
        if ledger.is_file():
            originals.append(('current-installation-before.json', ledger.read_bytes()))
        if independent:
            originals.append(('independent-installation-before.json', registry.path.read_bytes()))
            originals += [('checkpoint-' + area + '-before.json', registry.checkpoint_path(area).read_bytes()) for area in ('executor', 'lifecycle')]
        for relative, data in originals:
            (backup / relative).write_bytes(data)
            if (backup / relative).read_bytes() != data:
                raise ValueError('Installation adoption backup verification failed')
        write_atomic(backup / 'manifest.json', json.dumps({'verified': True, 'files': [
            {'relative': name, 'sha256': digest(backup / name)} for name, _ in originals]}).encode())
        plan = {'schema': 'existing-installation-adoption-1', 'root': str(root),
            'previous_root': str(previous), 'config': str(config), 'backup': str(backup),
            'registered_root': str(registered),
            'previous_ledger_sha256': digest(backup / 'current-installation-before.json') if ledger.is_file() else None,
            'registry_sha256': digest(registry.path) if independent else None,
            'independent_checkpoints': {area: digest(registry.checkpoint_path(area)) for area in ('executor', 'lifecycle')} if independent else {},
            'config_before_sha256': digest(backup / 'config-before.toml'),
            'installed_files_verified': len(entries), 'game_started': False}
        write_atomic(root / '.artifacts/installation-adoption.local.json', (json.dumps(plan, indent=2) + '\n').encode())
    # Recheck the original ownership, checkpoints and all installed bytes after backup.
    pending_adoption(root, config)
    checked = verify_installation_entries(independent['installed_files'], steam, library, mods) if independent else recorded_installation(previous, steam, library, mods)
    if checked != entries:
        raise ValueError('Installed files changed during adoption')
    ensure_idle(root, backend)
    save_ledger(root, entries)
    return plan


def relocate_registered_client(root, config, plan):
    pending_adoption(root, config)
    ensure_idle(root, WindowsGame(root / 'config/game-lifecycle.local.json'))
    before = config.read_bytes()
    candidate = relocated_client_bytes(before, Path(plan.get('registered_root', plan['previous_root'])), root)
    if digest(config) != plan['config_before_sha256']:
        raise ValueError('Client configuration changed at the adoption boundary')
    write_atomic(config, candidate)
    if not client_ready(root, config):
        raise ValueError('Relocated client registration verification failed')


def runtime_ready(root):
    no_links(root / '.venv/Scripts/python.exe')
    if not (root / '.venv/Scripts/python.exe').is_file() or sys.version_info[:3] != (3, 13, 11):
        return False
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    try:
        return all(importlib.metadata.version(name) == version for name, version in
                   [('mcp', '2.2.0'), ('httpx', '0.28.1'), ('balatro-agent', project['version'])])
    except importlib.metadata.PackageNotFoundError:
        return False


def recorded_installation(root, steam, library, mods):
    receipt = root / '.artifacts/portable-install.local.json'
    ledger = root / 'runs/checks/current-installation.json'
    if receipt.exists():
        proof = read_json(receipt)
        if proof.get('complete') is not True:
            raise ValueError('Incomplete installation receipt; preserve the receipt and backups for recovery')
        plan = read_json(root / '.artifacts/portable-plan.local.json')
        if Path(plan['steam_dir']) != steam or Path(plan['library_dir']) != library or Path(plan['save_root']) != mods.parent:
            raise ValueError('Recorded installation paths changed; preserve the old installation')
        expected = [item['target'] for item in plan['files']]
        if proof['applied_files'] != expected or proof['expected_files'] != len(expected):
            raise ValueError('Installation receipt does not match its frozen plan')
        backup = Path(proof['backup'])
        if not backup.is_relative_to(root / '.artifacts/backups'):
            raise ValueError('Unexpected backup path')
        if read_json(backup / 'manifest.json').get('verified') is not True:
            raise ValueError('Installation backup is unverified')
    if ledger.exists():
        entries = read_json(ledger)['installed_files']
    elif receipt.exists():
        entries = [{'path': item['target'], 'sha256': item['sha256']} for item in plan['files']]
    else:
        return None
    return verify_installation_entries(entries, steam, library, mods)


def verify_installation_entries(entries, steam, library, mods):
    injector = Installation.verify(steam, library).game.parent / 'version.dll'
    seen = set()
    for entry in entries:
        path = Path(entry['path']).absolute()
        if path in seen or not (path.is_relative_to(mods / 'balatrobot') or path.is_relative_to(mods / 'smods') or path == injector):
            raise ValueError('Unexpected or duplicate recorded installation file')
        seen.add(path)
        if digest(path) != entry['sha256'].lower():
            raise ValueError('Installed bytes differ from the recorded installation; preserve user changes')
    if not entries or mods / 'balatrobot/balatrobot.json' not in seen or injector not in seen:
        raise ValueError('Incomplete recorded Mod installation')
    return entries


def build_matches_install(root, mods):
    for item in read_json(root / 'mod/build-manifest.json')['files']:
        path = relative_file(item['path'])
        if path.as_posix() == 'reader-profile.json':
            continue  # Preserve historical local declarations.
        source = root / '.artifacts/built-mod/balatrobot' / path
        if digest(source) != item['sha256']:
            raise ValueError('Prepared Mod differs from its build manifest')
        if digest(mods / 'balatrobot' / path) != item['sha256']:
            return False
    return True


def save_ledger(root, entries):
    path = root / 'runs/checks/current-installation.json'
    no_links(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, (json.dumps({'installed_files': entries}, indent=2) + '\n').encode())


async def list_prepared_tools(root):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    parameters = StdioServerParameters(command=str(root / '.venv/Scripts/python.exe'),
        args=['-m', 'balatro_agent.server'], cwd=str(root),
        env={**os.environ, 'BALATRO_AGENT_CLIENT_CONTEXT': 'development'})
    async with asyncio.timeout(20), stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            listed = await session.list_tools()
            if {tool.name for tool in listed.tools} != set(TOOLS):
                raise ValueError('Prepared MCP tool list differs from the project contract')
    return len(listed.tools)


def prepare(root, *, steam_dir=None, library_dir=None, mods=None, config=None,
            reuse_only=False, preparation_id=None):
    config = (config or Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml').absolute()
    registry = InstallationRegistry(registry_path(config))
    with registry.lock():
        return _prepare(root, steam_dir=steam_dir, library_dir=library_dir, mods=mods,
                        config=config, reuse_only=reuse_only, preparation_id=preparation_id, registry=registry)


def _prepare(root, *, steam_dir=None, library_dir=None, mods=None, config=None,
             reuse_only=False, preparation_id=None, registry):
    root = root.absolute()
    no_links(root)
    steam, library = installation_paths(root, steam_dir, library_dir)
    mods = (mods or Path(os.environ['APPDATA']) / 'Balatro/Mods').absolute()
    config = (config or Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml').absolute()
    no_links(mods)
    if not runtime_ready(root):
        raise NeedsPreparation('Project-local Python and locked dependencies need preparation')
    entries = recorded_installation(root, steam, library, mods)
    reused = entries is not None
    adoption = None
    if reuse_only:
        if entries is None:
            raise NeedsPreparation('Local installation needs preparation')
        try:
            registered = client_ready(root, config)
        except ValueError:
            if pending_adoption(root, config) is None:
                client_identity(config)
                raise NeedsPreparation('Verified installation client paths need preparation')
            raise NeedsPreparation('Verified installation adoption needs completion')
        if not registered or not build_matches_install(root, mods):
            raise NeedsPreparation('Local installation needs preparation')
        if not registry_ready(registry, root, steam, library, mods, config, entries):
            raise NeedsPreparation('Independent installation receipt needs preparation')
        if Path(client_identity(config)['env'].get(ENVIRONMENT_KEY, '')) != registry.path:
            raise NeedsPreparation('Independent checkpoint tracking needs preparation')
    else:
        if entries is None:
            adoption = adopt_registered_installation(root, steam, library, mods, config, registry)
            entries = recorded_installation(root, steam, library, mods)
            if adoption is None and entries is None:
                prepare_installation(root, steam, library, mods, config)
                prepare_installation(root, steam, library, mods, config, True)
                entries = recorded_installation(root, steam, library, mods)
                save_ledger(root, entries)
            else:
                entries = recorded_installation(root, steam, library, mods)
                reused = True
        if adoption is None:
            entry = tomllib.loads(config.read_text(encoding='utf-8-sig')).get('mcp_servers', {}).get('balatro-agent') if config.exists() else None
            if isinstance(entry, dict) and Path(entry.get('cwd', '')) != root:
                adoption = pending_adoption(root, config)
        if adoption is None:
            try:
                client_ready(root, config)
            except ValueError:
                # A local, hash-verified installation can repair its own stale
                # paths even when an older version has no independent receipt.
                entry = client_identity(config)
                previous = Path(entry['cwd'])
                backend = WindowsGame(root / 'config/game-lifecycle.local.json')
                ensure_idle(root, backend); ensure_idle(previous, backend)
                independent = registry.read()
                if independent:
                    registry_ready(registry, Path(independent['root']), steam, library, mods, config, independent['installed_files'])
                    registry.ensure_idle(Path(independent['root']))
                    ensure_idle(Path(independent['root']), backend)
                    verify_installation_entries(independent['installed_files'], steam, library, mods)
                elif (previous / 'pyproject.toml').is_file():
                    if recorded_installation(previous, steam, library, mods) != entries:
                        raise ValueError('Previous installation record differs; preserve it')
                before = config.read_bytes()
                backup_client_change(root, config, relocated_client_bytes(before, previous, root), 'client-path-repair')
        if not build_matches_install(root, mods):
            save_ledger(root, entries)
            output = 'runs/checks/automatic-update-' + uuid.uuid4().hex + '.json'
            update_runtime(root, output)
            update_runtime(root, output, True)
        if adoption is not None:
            relocate_registered_client(root, config, adoption)
        else:
            ensure_client(root, config)
    entries = recorded_installation(root, steam, library, mods)
    if not client_ready(root, config) or not build_matches_install(root, mods):
        raise ValueError('Final preparation verification failed')
    count = asyncio.run(list_prepared_tools(root))
    if not reuse_only:
        publish_registry(registry, root, steam, library, mods, config, entries)
    result = {'schema': 'automatic-preparation-1', 'preparation_id': preparation_id,
        'utc': datetime.now(timezone.utc).isoformat(),
        'version': tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version'],
        'prepared': True, 'reused_installation': reused, 'installed_files_verified': len(entries),
        'stdio_tools_verified': count, 'client_config': str(config),
        'independent_installation_receipt': str(registry.path), 'checkpoint_tracking': TRACKING,
        'client_connection_verified': False, 'game_started': False,
        'next_step': 'Use the launcher to open a Codex project chat with its prompt, or paste the complete path-aware play prompt into a local Codex chat'}
    target = root / '.artifacts/onboarding.local.json'
    no_links(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(target, (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
    return result
