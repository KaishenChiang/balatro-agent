"""One maintenance entrypoint. Never submits gameplay.

prepare registers this project with the client; update-mod applies frozen runtime differences.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tomllib
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def hash_match(path, expected):
    try:
        return path.is_file() and digest(path) == expected.lower()
    except OSError:
        return None


def status():
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    locked = json.loads((ROOT / 'config/dependencies.lock.json').read_text())['sources']
    cache = [{'name': i['name'], 'available': (ROOT / '.artifacts/sources' / i['archive']).is_file(),
              'hash_match': (ROOT / '.artifacts/sources' / i['archive']).is_file()
              and digest(ROOT / '.artifacts/sources' / i['archive']) == i['sha256']} for i in locked]
    result = {'evidence_type': 'static_project_status', 'utc': datetime.now(timezone.utc).isoformat(),
              'version': project['version'], 'python': platform.python_version(),
              'mcp': importlib.metadata.version('mcp'), 'httpx': importlib.metadata.version('httpx'),
              'single_stdio_entrypoint': project['scripts'] == {'balatro-agent': 'balatro_agent.server:main'},
              'uv_lock_sha256': digest(ROOT / 'uv.lock'), 'fixed_downloads': cache,
              'live_game_verified': False}
    from package_source import verify_launcher, verified_bundles
    result['packaged_gui_launcher_verified'] = verify_launcher(ROOT)
    try:
        result['bundled_dependencies_verified'] = bool(verified_bundles(ROOT))
    except (OSError,ValueError,KeyError):
        result['bundled_dependencies_verified'] = False
    built = ROOT / '.artifacts/built-mod/balatrobot'
    manifest = json.loads((ROOT / 'mod/build-manifest.json').read_text())['files']
    runtime = [i for i in manifest if i['path'] != 'reader-profile.json']
    result['built_runtime_files'] = len(runtime)
    result['built_runtime_hashes_match'] = bool(runtime) and all(
        hash_match(built / i['path'], i['sha256']) is True for i in runtime)
    installation = ROOT / 'runs/checks/current-installation.json'
    if installation.exists():
        entries = json.loads(installation.read_text(encoding='utf-8-sig'))['installed_files']
        matched = [hash_match(Path(i['path']), i['sha256']) for i in entries]
        result['installed_files'] = len(entries)
        result['installed_hashes_match'] = None if None in matched else all(matched)
        result['installed_files_unavailable'] = sum(v is None for v in matched)
        mods = {Path(i['path']).parents[1] for i in entries if Path(i['path']).name == 'balatrobot.json'}
        correspondence = [hash_match(next(iter(mods)) / 'balatrobot' / i['path'], i['sha256']) for i in runtime] if len(mods) == 1 else [False]
        result['installed_runtime_matches_build'] = None if None in correspondence else all(correspondence)
    return result


def run_script(name, *args):
    return subprocess.run([sys.executable, str(ROOT / 'scripts' / name), *args], cwd=ROOT, check=False).returncode


def check_health(static, *, source_only=False):
    source = (static.get('single_stdio_entrypoint') is True
              and static.get('packaged_gui_launcher_verified') is True
              and static.get('bundled_dependencies_verified') is True
              and static.get('built_runtime_hashes_match') is True
              and bool(static.get('fixed_downloads'))
              and all(i.get('hash_match') is True for i in static['fixed_downloads']))
    installation_keys = ('installed_hashes_match', 'installed_runtime_matches_build')
    installation = (all(static.get(k) is True for k in installation_keys)
                    if any(k in static for k in installation_keys) else None)
    return {'source_status_passed': source, 'recorded_installation_passed': installation,
            'installation_required': not source_only,
            'static_checks_passed': source and (source_only or installation is not False)}


def check(output, *, source_only=False):
    from balatro_agent.local_audit import safe_path
    target = (ROOT / output).absolute()
    assert target.is_relative_to(ROOT / 'runs/checks') and '..' not in target.parts
    safe_path(ROOT, *target.relative_to(ROOT).parts)
    if target.exists() or target.with_suffix('.xml').exists() or target.with_name(target.stem + '-stdio.json').exists():
        raise ValueError('Preserve previous check evidence and choose a new output')
    target.parent.mkdir(parents=True, exist_ok=True)
    xml = target.with_suffix('.xml')
    stdio = target.with_name(target.stem + '-stdio.json')
    env = dict(os.environ)
    env['BALATRO_AGENT_CLIENT_CONTEXT'] = 'development'
    from package_source import source_snapshot
    before = source_snapshot(ROOT)
    # A fresh workspace directory avoids cross-user ownership of global TEMP.
    temporary = ROOT / '.artifacts' / ('test-tmp-' + uuid.uuid4().hex)
    tested = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--tb=short', '-p', 'no:cacheprovider', '--basetemp=' + str(temporary), '--junitxml=' + str(xml)], cwd=ROOT, env=env).returncode
    smoke = run_script('stdio_smoke.py', '--output', stdio.relative_to(ROOT).as_posix()) if tested == 0 else None
    suites = ET.parse(xml).getroot().iter('testsuite') if xml.exists() else []
    totals = {key: 0 for key in ('tests', 'failures', 'errors', 'skipped')}
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.get(key, '0'))
    value = {'evidence_type': 'fresh_integrated_development_checks', 'utc': datetime.now(timezone.utc).isoformat(),
             'synthetic': totals, 'pytest_exit_code': tested, 'development_stdio_exit_code': smoke,
             'development_stdio_report': stdio.relative_to(ROOT).as_posix(),
             'codex_actual_invocation': False, 'status': status(), 'source_snapshot': before,
             'source_unchanged_during_check': before == source_snapshot(ROOT)}
    value['scope'] = 'source_only' if source_only else 'source_and_recorded_installation'
    value.update(check_health(value['status'], source_only=source_only))
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(value, ensure_ascii=False))
    return tested or smoke or (0 if value['static_checks_passed'] and value['source_unchanged_during_check'] else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'status', 'diagnose', 'configure-display', 'check', 'build', 'build-launcher', 'package', 'verify-package', 'verify-offline', 'update-mod', 'timings', 'audit'])
    parser.add_argument('--output')
    parser.add_argument('--source-only', action='store_true')
    parser.add_argument('--check-report')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--console', choices=['hidden', 'visible'])
    parser.add_argument('--loading', choices=['hidden', 'visible'])
    parser.add_argument('--evidence')
    parser.add_argument('--first', type=int)
    parser.add_argument('--last', type=int)
    parser.add_argument('--steam-dir', type=Path)
    parser.add_argument('--library-dir', type=Path)
    parser.add_argument('--mods-dir', type=Path)
    parser.add_argument('--codex-config', type=Path)
    parser.add_argument('--reuse-only', action='store_true')
    parser.add_argument('--preparation-id')
    args = parser.parse_args()
    if args.source_only and args.command != 'check':
        parser.error('--source-only is only valid with check')
    if args.check_report and args.command != 'package':
        parser.error('--check-report is only valid with package')
    if any((args.steam_dir, args.library_dir, args.mods_dir, args.codex_config, args.reuse_only, args.preparation_id)) and args.command != 'prepare':
        parser.error('Preparation options are only valid with prepare')
    if args.command == 'prepare':
        if args.apply or args.console is not None or args.loading is not None:
            parser.error('Unrelated maintenance options cannot be combined with prepare')
        from onboarding import prepare, NeedsPreparation
        from balatro_agent.windows_game import GameProcessError
        try:
            result = prepare(ROOT, steam_dir=args.steam_dir, library_dir=args.library_dir,
                mods=args.mods_dir, config=args.codex_config, reuse_only=args.reuse_only,
                preparation_id=args.preparation_id)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        except NeedsPreparation as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except (OSError, ValueError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except GameProcessError as exc:
            print('Steam installation could not be verified: ' + exc.code, file=sys.stderr)
            return 1
    if args.apply and args.command != 'update-mod':
        parser.error('--apply is only valid with update-mod')
    if (args.console is not None or args.loading is not None) and args.command != 'configure-display':
        parser.error('--console and --loading are only valid with configure-display')
    if args.command == 'configure-display':
        if args.console is None and args.loading is None:
            parser.error('Choose --console or --loading')
        from startup_display import configure
        print(json.dumps(configure(ROOT, console=args.console == 'hidden' if args.console is not None else None,
                                   loading=args.loading == 'hidden' if args.loading is not None else None)))
        return 0
    if args.command == 'diagnose':
        from startup_display import diagnose, save_report
        report = diagnose(ROOT, status())
        if args.output:
            save_report(ROOT, args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    output = args.output or 'runs/checks/project-check.json'
    if args.command in ('timings', 'audit'):
        if not args.evidence:
            parser.error('--evidence is required for timings/audit')
        extra = ['--evidence', args.evidence, '--output', output]
        if args.command == 'timings':
            for name in ('first', 'last'):
                if getattr(args, name) is not None:
                    extra += ['--' + name, str(getattr(args, name))]
        return run_script('analyze_timings.py' if args.command == 'timings' else 'audit_experience_mcp_evidence.py', *extra)
    if args.command == 'update-mod':
        from update_mod import run
        print(json.dumps(run(ROOT, output, args.apply), ensure_ascii=False))
        return 0
    if args.command == 'status':
        print(json.dumps(status(), ensure_ascii=False, indent=2)); return 0
    if args.command == 'check':
        return check(output, source_only=args.source_only)
    if args.command == 'build':
        return run_script('build_mod.py')
    if args.command == 'build-launcher':
        if os.name != 'nt':
            raise RuntimeError('The GUI launcher build requires Windows')
        return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', str(ROOT / 'scripts/build_launcher.ps1')], cwd=ROOT, check=False).returncode
    if args.command == 'package':
        arguments = ['--review-dir', args.output] if args.output else []
        if args.check_report:
            arguments += ['--check-report', args.check_report]
        return run_script('package_source.py', *arguments)
    if args.command == 'verify-offline':
        return run_script('verify_offline.py', '--output', args.output or 'runs/checks/offline-preparation.json')
    return run_script('verify_source_candidate.py', '--output', output)


if __name__ == '__main__':
    raise SystemExit(main())
