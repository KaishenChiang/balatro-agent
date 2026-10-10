"""Export a checked, minimal source candidate; never publishes or pushes."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import tomllib
from zipfile import ZipFile, ZIP_DEFLATED
import re
import argparse
import struct
from bootstrap_sources import no_links, digest, unpack

ROOT=Path(__file__).resolve().parents[1]
TOP=['LICENSE','README.md','README.zh-CN.md','PROJECT.md','CHANGELOG.md','Balatro Agent.exe','pyproject.toml','uv.lock',
     '.gitattributes','.gitignore','.python-version','AGENTS.md']
SCRIPTS=['setup.ps1','launcher.ps1','activity_viewer.ps1','codex_handoff.ps1','localization.ps1','build_launcher.ps1','onboarding.py','bootstrap_sources.py','build_mod.py','startup_display.py',
         'install_portable.py','update_mod.py','package_source.py','verify_source_candidate.py','verify_offline.py',
         'stdio_smoke.py','export_contract.py','check_notes_persistence.py',
         'audit_experience_mcp_evidence.py','client_evidence.py','project.py','analyze_timings.py']
DOCS=['reference.md','maintenance.md','maintenance.en.md','model-client.md','model-client.en.md','english-support.md','activity.md','public-changes.md','optimization.md',
      'observation-schema.json','action-schema.json','notes-schema.json','calculation-schema.json','run-plan-schema.json']


def verified_bundles(root=ROOT):
    """Whitelist only complete fixed public distributions, never local caches."""
    paths=[root/'vendor/README.md',root/'config/runtime.lock.json']
    component_lock=json.loads((root/'config/dependencies.lock.json').read_text(encoding='utf-8'))
    link=component_lock['offline_runtime']
    if link['manifest']!='config/runtime.lock.json' or link['sha256']!=digest(root/'config/runtime.lock.json'):
        raise ValueError('Runtime manifest differs from the component lock')
    for item in component_lock['sources']:
        if Path(item['archive']).name!=item['archive'] or '\\' in item['archive'] or ':' in item['archive']:
            raise ValueError('Unsafe bundled archive name')
        path=root/'vendor'/item['archive'];no_links(path)
        if digest(path)!=item['sha256']:
            raise ValueError('Bundled fixed component differs from its lock')
        paths.append(path)
    manifest=json.loads((root/'config/runtime.lock.json').read_text(encoding='utf-8'))
    if (manifest['schema']!='balatro-offline-runtime-1' or manifest['platform']!='windows-x86_64'
            or manifest['python_version']!='3.13.11' or manifest['uv_version']!='0.9.21'
            or manifest['archive']!='runtime-windows-x64.zip' or manifest['uv_lock_sha256']!=digest(root/'uv.lock')):
        raise ValueError('Bundled runtime lock differs from the source')
    archive=root/'vendor'/manifest['archive'];no_links(archive)
    if digest(archive)!=manifest['sha256'] or archive.stat().st_size!=manifest['bytes']:
        raise ValueError('Bundled runtime archive differs from its lock')
    records=[manifest['python'],*manifest['wheels']]
    names=[r['path'] for r in records]
    if not 2<=len(names)<=80 or len(set(n.casefold() for n in names))!=len(names):
        raise ValueError('Invalid bundled runtime member list')
    for name in names:
        path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or '\0' in name:
            raise ValueError('Unsafe bundled runtime member')
    locked={p['name']:p for p in tomllib.loads((root/'uv.lock').read_text(encoding='utf-8'))['package']}
    for record in manifest['wheels']:
        if not record['path'].startswith('wheels/') or not record['path'].endswith('.whl') or not record['license_files']:
            raise ValueError('Invalid licensed runtime wheel')
        package=locked.get(record['name'])
        if package and (record['version']!=package['version'] or not any(
                w['url']==record['url'] and w['hash']=='sha256:'+record['sha256'] for w in package['wheels'])):
            raise ValueError('Bundled wheel differs from uv.lock')
    with ZipFile(archive) as bundle:
        if set(bundle.namelist())!=set(names) or len(bundle.infolist())!=len(names):
            raise ValueError('Unregistered bundled runtime member')
        if sum(e.file_size for e in bundle.infolist())>150_000_000:
            raise ValueError('Bundled runtime exceeds size limit')
        for record in records:
            with bundle.open(record['path']) as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=record['sha256']:
                    raise ValueError('Bundled runtime member differs from its lock')
            if bundle.getinfo(record['path']).file_size!=record['bytes']:
                raise ValueError('Bundled runtime member size differs')
    paths.append(archive)
    return paths


def verify_launcher(root=ROOT):
    """Allow only the self-authored WinExe bound to its source/build receipt."""
    try:
        receipt_path=root/'windows/launcher-build.json'
        no_links(receipt_path)
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt['schema']!='self-authored-launcher-1' or receipt['executable']!='Balatro Agent.exe':
            return False
        inputs={'source':'windows/Launcher.cs','app_manifest':'windows/app.manifest',
                'build_script':'scripts/build_launcher.ps1'}
        for key, relative in inputs.items():
            path=root/relative; no_links(path)
            if receipt[key]!=relative or digest(path)!=receipt[key+'_sha256']:
                return False
        executable=root/'Balatro Agent.exe'; no_links(executable)
        if digest(executable)!=receipt['sha256'] or receipt['subsystem']!='windows_gui':
            return False
        version=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
        if receipt['version']!=version+'.0' or receipt['license']!='MIT':
            return False
        data=executable.read_bytes(); offset=struct.unpack_from('<I',data,0x3c)[0]
        return (data[:2]==b'MZ' and data[offset:offset+4]==b'PE\0\0'
                and struct.unpack_from('<H',data,offset+4)[0]==0x8664
                and struct.unpack_from('<H',data,offset+24+68)[0]==2)
    except (OSError,ValueError,KeyError,struct.error):
        return False


def selected_files(root=ROOT, *, include_validation=True):
    """Explicit roots and file types; local history/runtime data is excluded."""
    selected=[root/name for name in TOP]
    if not verify_launcher(root):
        raise ValueError('Self-authored GUI launcher does not match its source/build receipt')
    selected += [root/'windows'/name for name in ('Launcher.cs','app.manifest','launcher-build.json')]
    selected += [root/'scripts'/name for name in SCRIPTS]
    selected += [root/'docs/balatro-ai'/name for name in DOCS]
    selected += [root/'config'/name for name in ('dependencies.lock.json','game-lifecycle.example.json',
                                               'mcp-client.example.json','startup-ui.example.json')]
    selected += [root/'prompts'/name for name in ('bootstrap.md','bootstrap.en.md','first-use.md','first-use.en.md','mcp-evidence.js')]
    selected += [root/'experience/README.md']
    selected += [root/'third_party'/name for name in ('NOTICE.md','balatrobot-LICENSE.txt','lovely-LICENSE.md')]
    selected += [root/'third_party'/name for name in ('uv-LICENSE-MIT.txt','uv-LICENSE-APACHE.txt')]
    selected += verified_bundles(root)
    selected += list((root/'src').rglob('*.py'))
    selected += list((root/'tests').glob('*.py'))+list((root/'tests/support').glob('*.lua'))
    selected += [p for p in (root/'mod').glob('*') if p.suffix in ('.lua','.patch','.json','.toml')]
    selected += [p for p in (root/'experience/experience').rglob('*')
                 if p.is_file() and (p.name=='HEAD.json' or p.suffix=='.md')]
    selected += [root/'evidence'/name for name in ('README.md','history.json','historical-runs.zip')]
    if include_validation and (root/'evidence/validation.json').is_file():
        selected.append(root/'evidence/validation.json')
    files=sorted(set(selected))
    for path in files:
        no_links(path)
        relative=path.relative_to(root)
        if not path.is_file() or getattr(path.stat(),'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Missing or linked candidate file')
        forbidden_binary=path.suffix.lower() in ('.jkr','.dll','.exe','.png') and relative.as_posix()!='Balatro Agent.exe'
        if any(p in ('.artifacts','.tools','.venv','__pycache__','runs','TEST') for p in relative.parts) or '.local.' in path.name or forbidden_binary:
            raise ValueError('Forbidden source candidate content')
    return files


def source_snapshot(root=ROOT):
    return [{'path':p.relative_to(root).as_posix(),'sha256':digest(p)}
            for p in selected_files(root,include_validation=False)]


def portable_guidelines(data):
    """Export the shared rules while removing the explicit local-only block."""
    value = data.decode('utf-8-sig')
    markers = ('<!-- local-only:start -->', '<!-- local-only:end -->')
    if value.count(markers[0]) != value.count(markers[1]):
        raise ValueError('Unbalanced local-only instruction block')
    value = re.sub(r'(?ms)^<!-- local-only:start -->\r?\n.*?^<!-- local-only:end -->\r?\n?', '', value)
    if any(marker in value for marker in markers):
        raise ValueError('Malformed local-only instruction block')
    return value.encode('utf-8')


def audited_run(root, summary_path):
    """Bind each report to its immutable public delivery log and audit."""
    def read(relative):
        path = (root / relative).absolute()
        assert '..' not in path.parts and path.is_relative_to(root / 'runs')
        no_links(path)
        return json.loads(path.read_text(encoding='utf-8-sig'))
    summary = read(summary_path)
    log = root / summary['actual_evidence']
    assert log == (root / summary_path).parent / 'codex-mcp.jsonl'
    no_links(log)
    audit = read(summary['safe_delivery_audit'])
    assert audit['comparison_passed'] and audit['sha256'] == hashlib.sha256(log.read_bytes()).hexdigest()
    rows = [json.loads(line) for line in log.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    calls = [row for row in rows if 'tool' in row]
    steps = {row['step']: row for row in calls}
    host_errors = [row for row in calls if row.get('evidence_type') == 'host_tool_error_not_mcp_delivery']
    assert len(steps) == len(calls) == summary['whole_test_calls']
    assert len(calls) - len(host_errors) == audit['actual_calls']
    assert len(host_errors) == len(audit.get('host_errors', []))
    for row in host_errors:
        assert row['result'] == {'isError': True, 'status': 'external_tool_error'}
    return summary, rows, calls, steps, host_errors


def verified_speed_run(root, summary_path, *, outcomes=('win',)):
    """A continuous timing claim cannot hide host errors or unknown results."""
    summary, _, calls, steps, host_errors = audited_run(root, summary_path)
    assert not host_errors
    selected = [row for row in calls if summary['start_or_resume_step'] <= row['step'] <= summary['terminal_step']]
    assert len(selected) == summary['gameplay_calls']
    assert not any(row['result'].get('state') in ('UNKNOWN', 'RUNNING', 'AWAITING_INPUT') for row in selected)
    assert not any(row.get('parameters', {}).get('action') == 'continue_endless' for row in selected)
    terminal = steps[summary['terminal_step']]['result']
    assert terminal['state'] == 'COMPLETED' and terminal['completion_signal'] == 'terminal_confirmation'
    assert terminal['observation']['outcome'] == summary['outcome'] and summary['outcome'] in outcomes
    assert terminal['observation']['profile'] == summary['profile'] == 2
    close = steps[summary['close_step']]['result']
    assert close['state'] == 'COMPLETED' and close['running'] is False
    return summary


def verified_fault_recovery_run(root, summary_path):
    """A completed segment must retain its interrupted-attempt classification."""
    summary, rows, calls, steps, host_errors = audited_run(root, summary_path)
    assert summary['formal_game'] is False and summary['resumed_existing_attempt'] is True
    assert summary['original_attempt'] == 'n5-fresh-context-20261005-01'
    assert summary['interrupted_attempt'] is True and summary['new_random_attempts'] == 0
    header = rows[0]
    assert header['attempt_kind'] == 'fault_recovery_segment' and header['original_attempt'] == summary['original_attempt']
    assert not any(row.get('parameters', {}).get('action') in ('start_run', 'continue_endless') for row in calls)
    selected = [row for row in calls if summary['start_or_resume_step'] <= row['step'] <= summary['terminal_step']]
    assert len(selected) == summary['gameplay_calls']
    # Read-only UNKNOWN queries and host failures remain visible. An actually
    # submitted unresolved action cannot be promoted by a later outcome report.
    assert not any(row['tool'] == 'act' and row['result'].get('state') in ('UNKNOWN', 'RUNNING', 'AWAITING_INPUT') for row in selected)
    assert len(host_errors) == summary.get('host_tool_errors', 0)
    assert len(calls) - len(host_errors) == summary.get('actual_mcp_deliveries', len(calls))
    terminal = steps[summary['terminal_step']]['result']
    assert terminal['state'] == 'COMPLETED' and terminal['completion_signal'] == 'terminal_confirmation'
    assert terminal['observation']['outcome'] == summary['outcome'] and summary['outcome'] in ('win', 'loss')
    assert terminal['observation']['profile'] == summary['profile'] == 2
    close = steps[summary['close_step']]['result']
    assert close['state'] == 'COMPLETED' and close['running'] is False
    resumed = steps[summary['start_or_resume_step']]
    assert resumed['tool'] == 'act' and resumed['parameters']['action'] == 'continue_run'
    return summary


def require_source_check(root, version, check_report='runs/checks/release-check.json'):
    """Fresh source checks authorize a candidate, never a new live-game claim."""
    path=(root/check_report).absolute()
    if '..' in path.parts or not path.is_relative_to(root/'runs/checks'):
        raise ValueError('Source check report belongs under runs/checks')
    if not path.is_file():
        raise ValueError('Current version has no registered complete delivery evidence; run project.py check --output runs/checks/release-check.json')
    no_links(path)
    report=json.loads(path.read_text(encoding='utf-8'))
    checks=report.get('synthetic',{})
    status=report.get('status',{})
    valid=(status.get('version')==version and report.get('pytest_exit_code')==0
           and report.get('development_stdio_exit_code')==0
           and checks.get('tests',0)>0 and all(checks.get(k)==0 for k in ('failures','errors','skipped'))
           and status.get('single_stdio_entrypoint') is True
           and status.get('built_runtime_hashes_match') is True
           and status.get('bundled_dependencies_verified') is True
           and bool(status.get('fixed_downloads'))
           and all(i.get('hash_match') is True for i in status['fixed_downloads'])
           and report.get('source_unchanged_during_check') is True)
    if not valid:
        raise ValueError('Current version has no registered complete delivery evidence; source checks are incomplete')
    if report.get('source_snapshot')!=source_snapshot(root):
        raise ValueError('Source changed after checks; preserve the old report and run a fresh check')
    return report


def candidate_bytes(path,root=ROOT):
    data=path.read_bytes()
    return portable_guidelines(data) if path==root/'AGENTS.md' else data


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--review-dir',default='deliverables/github-ready')
    parser.add_argument('--check-report',default='runs/checks/release-check.json')
    args=parser.parse_args(argv)
    version=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    report=require_source_check(ROOT,version,args.check_report)
    review=(ROOT/args.review_dir).absolute();no_links(review)
    if '..' in review.parts or not review.is_relative_to(ROOT/'deliverables'):
        raise ValueError('Review directory must stay inside deliverables')
    if review.exists():raise ValueError('github-ready already exists; preserve it and inspect before rebuilding')
    destination=ROOT/'deliverables/source';no_links(destination)
    archive=destination/('balatro-agent-'+version+'-source-candidate.zip');no_links(archive)
    companion=destination/('balatro-agent-'+version+'-source-manifest.json');no_links(companion)
    if archive.exists():raise ValueError('Source candidate already exists; preserve it before rebuilding')
    if companion.exists():raise ValueError('Source manifest already exists; preserve it before rebuilding')
    files=selected_files(ROOT,include_validation=False)
    history=json.loads((ROOT/'evidence/history.json').read_text(encoding='utf-8'))
    if digest(ROOT/'evidence/historical-runs.zip')!=history['archive_sha256']:
        raise ValueError('Historical archive changed')
    with ZipFile(ROOT/'evidence/historical-runs.zip') as bundle:
        if set(bundle.namelist())!={i['path'] for i in history['files']}:
            raise ValueError('Historical archive member list changed')
        for item in history['files']:
            if hashlib.sha256(bundle.read(item['path'])).hexdigest()!=item['sha256']:
                raise ValueError('Historical evidence hash changed')
    validation={'evidence_type':'current_source_checks_not_live_game_acceptance','version':version,
        'synthetic':report['synthetic'],'development_stdio_exit_code':0,
        'development_tools':len(json.loads((ROOT/report['development_stdio_report']).read_text(encoding='utf-8'))['tools']),
        'fixed_downloads_verified':True,'minimal_mod_build_verified':True,
        'bundled_distributions_verified':True,
        'current_version_real_game_verified':False,'historical_live_evidence':'history.json',
        'real_game_or_client_config_written':False,'published':False,
        'source_snapshot':[{'path':p.relative_to(ROOT).as_posix(),
                            'sha256':hashlib.sha256(candidate_bytes(p)).hexdigest()} for p in files],
        'scope':'Local checks include private native-function fixtures; public checkout skips those when absent. Actual new-machine cold installation, client reload, other clients and model rankings remain unverified.'}
    (ROOT/'evidence/validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    files=selected_files(ROOT)
    entries=[]
    destination.mkdir(parents=True,exist_ok=True)
    with ZipFile(archive,'x',compression=ZIP_DEFLATED,compresslevel=9) as bundle:
        for path in files:
            name=path.relative_to(ROOT).as_posix();data=candidate_bytes(path)
            bundle.writestr(name,data)
            entries.append({'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
        manifest={'type':'checked_local_source_candidate_not_published','version':version,'files':entries,
            'license':'MIT_self_authored_only','historical_evidence':'evidence/history.json',
            'current_version_real_game_verified':False,'game_or_client_config_changed':False,
            'excluded':'game binaries/assets/private source/saves/seeds/keys/personal configuration/runtime environments/TEST/backups',
            'public_transformations':['AGENTS.md local-only block removed'],
            'fresh_source_rebuild_required':True}
        bundle.writestr('SOURCE-MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    manifest['archive_sha256']=digest(archive)
    with companion.open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    # Never overwrite an existing review directory or silently keep stale files.
    unpack(archive,review)
    print(json.dumps({'files':len(entries)+1,'archive':archive.relative_to(ROOT).as_posix(),
        'review_directory':review.relative_to(ROOT).as_posix(),'bytes':archive.stat().st_size,
        'sha256':manifest['archive_sha256'],'published':False}))


if __name__=='__main__':main()
