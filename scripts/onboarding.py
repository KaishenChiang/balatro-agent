"""Automatic preparation and read-only reuse through project.py; no model/game launch."""
import asyncio
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tomllib
import uuid

from balatro_agent.windows_game import Installation
from install_portable import TOOLS, installation_paths, prepare_installation
from bootstrap_sources import digest, no_links
from update_mod import read_json, run as update_runtime, write_atomic, relative_file


class NeedsPreparation(Exception):
    pass


def client_entry(root):
    return {'command': str(root / '.venv/Scripts/python.exe'),
            'args': ['-m', 'balatro_agent.server'], 'cwd': str(root),
            'enabled': True, 'enabled_tools': TOOLS,
            'startup_timeout_sec': 20, 'tool_timeout_sec': 45,
            'env': {'BALATRO_AGENT_CLIENT_CONTEXT': 'codex_config'}}


def client_ready(root, config):
    no_links(config)
    parsed = tomllib.loads(config.read_text(encoding='utf-8-sig')) if config.exists() else {}
    entry = parsed.get('mcp_servers', {}).get('balatro-agent')
    if entry is None:
        return False
    expected = client_entry(root)
    paths_match = all(isinstance(entry.get(key), str) and Path(entry[key]) == Path(expected[key])
                      for key in ('command', 'cwd'))
    tools = entry.get('enabled_tools', TOOLS)
    tools_match = isinstance(tools, list) and len(tools) == len(TOOLS) and set(tools) == set(TOOLS)
    environment = entry.get('env', {})
    if not (paths_match and entry.get('args') == expected['args']
            and entry.get('enabled', True) is True and tools_match
            and isinstance(environment, dict) and environment.get('BALATRO_AGENT_CLIENT_CONTEXT') == 'codex_config'):
        raise ValueError('Existing balatro-agent config differs; preserve it and inspect the client configuration')
    return True


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
    if reuse_only:
        if entries is None or not client_ready(root, config) or not build_matches_install(root, mods):
            raise NeedsPreparation('Local installation needs preparation')
    elif entries is None:
        prepare_installation(root, steam, library, mods, config)
        prepare_installation(root, steam, library, mods, config, True)
        entries = recorded_installation(root, steam, library, mods)
        save_ledger(root, entries)
    else:
        client_ready(root, config)  # Reject conflicts before changing runtime.
        if not build_matches_install(root, mods):
            save_ledger(root, entries)
            output = 'runs/checks/automatic-update-' + uuid.uuid4().hex + '.json'
            update_runtime(root, output)
            update_runtime(root, output, True)
        ensure_client(root, config)
    entries = recorded_installation(root, steam, library, mods)
    if not client_ready(root, config) or not build_matches_install(root, mods):
        raise ValueError('Final preparation verification failed')
    count = asyncio.run(list_prepared_tools(root))
    result = {'schema': 'automatic-preparation-1', 'preparation_id': preparation_id,
        'utc': datetime.now(timezone.utc).isoformat(),
        'version': tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version'],
        'prepared': True, 'reused_installation': reused, 'installed_files_verified': len(entries),
        'stdio_tools_verified': count, 'client_config': str(config),
        'client_connection_verified': False, 'game_started': False,
        'next_step': 'Open this project in Codex and send prompts/first-use.md'}
    target = root / '.artifacts/onboarding.local.json'
    no_links(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(target, (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
    return result
