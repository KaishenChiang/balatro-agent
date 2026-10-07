"""Update only recorded BalatroBot runtime files after a frozen, closed-game plan.

Called by project.py. No game actions, configuration edits or save decoding.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tomllib
import uuid

from balatro_agent.local_audit import canonical, make_dir, no_links, safe_path
from balatro_agent.windows_game import WindowsGame


def digest(path):
    no_links(path)
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    no_links(path)
    return json.loads(path.read_text(encoding='utf-8-sig'))


def ensure_idle(root, backend):
    for area, keys in [('executor', {'pending', 'input_pending'}), ('lifecycle', {'pending'})]:
        checkpoint = safe_path(root, 'runs', 'live', area, 'checkpoint.json')
        if checkpoint.exists():
            value = read_json(checkpoint)
            if not isinstance(value, dict) or set(value) != keys or any(value[k] is not None for k in keys):
                raise ValueError('Unresolved or invalid checkpoint; query the original action first')
    if backend.find() is not None:
        raise ValueError('Balatro must be normally closed before updating')


def relative_file(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('Unsafe build path')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or path.as_posix() != value:
        raise ValueError('Unsafe build path')
    return path


def opaque_files(save_root):
    # Copy bytes only. Exclude Mods, and refuse linked or unusually large trees.
    found = []
    total = 0
    for directory, children, names in os.walk(save_root, followlinks=False):
        parent = Path(directory)
        no_links(parent)
        children[:] = [name for name in children if not (parent == save_root and name == 'Mods')]
        for name in children:
            no_links(parent / name)
        for name in sorted(names):
            source = parent / name
            no_links(source)
            size = source.stat().st_size
            total += size
            if size > 64 * 1024**2 or total > 256 * 1024**2 or len(found) >= 1024:
                raise ValueError('Opaque save backup exceeds the maintenance limit')
            found.append(source)
    return sorted(found)


def make_plan(root, backend=None):
    root = root.absolute()
    no_links(root)
    backend = backend or WindowsGame(safe_path(root, 'config', 'game-lifecycle.local.json'))
    ensure_idle(root, backend)
    ledger_path = safe_path(root, 'runs', 'checks', 'current-installation.json')
    ledger = read_json(ledger_path)
    installed = ledger['installed_files']
    roots = {Path(item['path']).absolute().parent for item in installed if Path(item['path']).name == 'balatrobot.json'}
    if len(roots) != 1:
        raise ValueError('A unique recorded BalatroBot installation is required')
    mod_root = roots.pop()
    if mod_root.name != 'balatrobot' or mod_root.parent.name != 'Mods':
        raise ValueError('Unexpected Mod installation root')
    no_links(mod_root)
    save_root = mod_root.parent.parent
    build = safe_path(root, '.artifacts', 'built-mod', 'balatrobot')
    manifest_path = safe_path(root, 'mod', 'build-manifest.json')
    manifest = read_json(manifest_path)
    guards = {}
    for item in installed:
        path = Path(item['path']).absolute()
        actual = digest(path)
        if actual != item['sha256'].lower() or str(path) in guards:
            raise ValueError('Installed bytes differ from the recorded installation')
        guards[str(path)] = actual
    changes, names = [], set()
    for item in manifest['files']:
        relative = relative_file(item['path'])
        if relative.as_posix() in names:
            raise ValueError('Duplicate build path')
        names.add(relative.as_posix())
        source = safe_path(build, *relative.parts)
        if digest(source) != item['sha256'].lower():
            raise ValueError('Build bytes differ from its manifest')
        if relative.as_posix() == 'reader-profile.json':
            continue  # Never replace the native test-profile attestation.
        target = safe_path(mod_root, *relative.parts)
        before = guards.get(str(target))
        if before is None:
            raise ValueError('New/unrecorded runtime files require a separate installation plan')
        if before != item['sha256'].lower():
            changes.append({'relative': relative.as_posix(), 'source': str(source), 'target': str(target),
                            'before_sha256': before, 'after_sha256': item['sha256'].lower()})
    for path in opaque_files(save_root):
        guards[str(path)] = digest(path)
    # Guard existing local declarations and client configuration without decoding it.
    local = safe_path(root, 'config')
    for path in sorted(local.glob('*.local.json')):
        guards[str(path.absolute())] = digest(path)
    codex_config = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml'
    if codex_config.is_file():
        guards[str(codex_config.absolute())] = digest(codex_config)
    guards[str(ledger_path)] = digest(ledger_path)
    return {'schema': 'recorded-runtime-update-1',
            'version': tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version'],
            'mod_root': str(mod_root), 'save_root': str(save_root),
            'build_manifest_sha256': digest(manifest_path), 'changes': changes,
            'preserved_hashes': guards, 'game_started': False, 'saves_decoded': False}


def write_atomic(path, data):
    no_links(path)
    temporary = path.with_name(path.name + '.balatro-update-' + uuid.uuid4().hex + '.tmp')
    no_links(temporary)
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        no_links(path)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            no_links(temporary)
            temporary.unlink()


def apply_plan(plan, root, report, backend=None):
    root = root.absolute()
    report = safe_path(root, *report.absolute().relative_to(root).parts)
    backend = backend or WindowsGame(safe_path(root, 'config', 'game-lifecycle.local.json'))
    if make_plan(root, backend) != plan:
        raise ValueError('Installation/source/configuration changed after the frozen plan')
    if report.exists():
        raise ValueError('Preserve the existing update report; use a new output name')
    if not plan['changes']:
        raise ValueError('No runtime changes to install')
    backup = safe_path(root, '.artifacts', 'backups', 'mod-update-' +
                       datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    make_dir(backup)
    ledger_path = safe_path(root, 'runs', 'checks', 'current-installation.json')
    profile = safe_path(Path(plan['mod_root']), 'reader-profile.json')
    originals = [(ledger_path, 'current-installation-before.json')]
    if profile.exists():
        originals.append((profile, 'mod/reader-profile.json'))
    originals += [(Path(item['target']), 'mod/' + item['relative']) for item in plan['changes']]
    originals += [(path, 'Balatro/' + path.relative_to(Path(plan['save_root'])).as_posix())
                  for path in opaque_files(Path(plan['save_root']))]
    copied = []
    for source, relative in originals:
        target = safe_path(backup, *PurePosixPath(relative).parts)
        make_dir(target.parent)
        if target.exists():
            raise ValueError('Duplicate backup target')
        expected = plan['preserved_hashes'].get(str(source))
        if expected is None or digest(source) != expected:
            raise ValueError('Original bytes changed during backup')
        shutil.copy2(source, target)
        if digest(target) != expected:
            raise ValueError('Backup hash verification failed')
        copied.append({'source': str(source), 'backup_relative': relative, 'sha256': expected})
    proof = {'verified': True, 'originals': copied, 'frozen_plan': plan,
             'recovery': 'Normally close the game. Verify hashes and restore only necessary backed-up runtime files and their ledger entries. Preserve later saves and settings.'}
    write_atomic(backup / 'manifest.json', (json.dumps(proof, ensure_ascii=False, indent=2) + '\n').encode())
    # Nothing external is modified until every backup has passed and the plan still matches.
    if make_plan(root, backend) != plan:
        raise ValueError('State changed during backup; installation preserved')
    result = {'schema': plan['schema'], 'version': plan['version'], 'backup': str(backup),
              'backup_verified': True, 'installed': [], 'complete': False,
              'game_started': False, 'saves_decoded': False, 'profile_attestation_preserved': False}
    changed = {item['target']: item for item in plan['changes']}
    try:
        for item in plan['changes']:
            ensure_idle(root, backend)
            source, target = Path(item['source']), Path(item['target'])
            if digest(source) != item['after_sha256'] or digest(target) != item['before_sha256']:
                raise ValueError('Runtime file changed at the replacement boundary')
            write_atomic(target, source.read_bytes())
            if digest(target) != item['after_sha256']:
                raise ValueError('Installed hash verification failed')
            result['installed'].append(item)
        for value, before in plan['preserved_hashes'].items():
            expected = changed[value]['after_sha256'] if value in changed else before
            if digest(Path(value)) != expected:
                raise ValueError('A protected file changed; retain the partial update report')
        ledger = read_json(ledger_path)
        for item in ledger['installed_files']:
            key = str(Path(item['path']).absolute())
            if key in changed:
                item.update(sha256=changed[key]['after_sha256'], bytes=Path(key).stat().st_size)
        ledger['runtime_update'] = {'version': plan['version'], 'utc': datetime.now(timezone.utc).isoformat(),
                                    'backup': str(backup), 'changed_files': len(changed)}
        write_atomic(ledger_path, (json.dumps(ledger, ensure_ascii=False, indent=2) + '\n').encode())
        result.update(complete=True, profile_attestation_preserved=True,
                      protected_files=len(plan['preserved_hashes']), opaque_backups=len(copied) - len(plan['changes']) - 1 - int(profile.exists()))
    finally:
        make_dir(report.parent)
        write_atomic(report, (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
    return result


def run(root, output, apply=False):
    root = root.absolute()
    output_path = (root / output).absolute()
    output_path = safe_path(root, *output_path.relative_to(root).parts)
    if not output_path.is_relative_to(root / 'runs/checks'):
        raise ValueError('Maintenance evidence belongs under runs/checks')
    if not apply:
        if output_path.exists():
            raise ValueError('Preserve the existing frozen plan; use a new output name')
        plan = make_plan(root)
        make_dir(output_path.parent)
        write_atomic(output_path, (json.dumps(plan, ensure_ascii=False, indent=2) + '\n').encode())
        return {'plan': output, 'changed_files': len(plan['changes']), 'external_installation_applied': False}
    plan = read_json(output_path)
    report = output_path.with_name(output_path.stem + '-applied.json')
    return apply_plan(plan, root, report)
