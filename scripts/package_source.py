"""Export a checked, minimal source candidate; never publishes or pushes."""
import hashlib
import json
from pathlib import Path
import stat
import tomllib
from zipfile import ZipFile, ZIP_DEFLATED
import re
from bootstrap_sources import no_links, digest, unpack

ROOT=Path(__file__).resolve().parents[1]
TOP=['LICENSE','README.md','PROJECT.md','Install.cmd','Balatro Agent.cmd','pyproject.toml','uv.lock',
     '.gitignore','.python-version','AGENTS.md']
SCRIPTS=['setup.ps1','launcher.ps1','onboarding.py','bootstrap_sources.py','build_mod.py','startup_display.py',
         'install_portable.py','update_mod.py','package_source.py','verify_source_candidate.py',
         'stdio_smoke.py','export_contract.py','check_notes_persistence.py',
         'audit_experience_mcp_evidence.py','client_evidence.py','project.py','analyze_timings.py']
DOCS=['reference.md','maintenance.md','model-client.md',
      'observation-schema.json','action-schema.json','notes-schema.json','calculation-schema.json']


def selected_files(root=ROOT, *, include_validation=True):
    """Explicit roots and file types; local history/runtime data is excluded."""
    selected=[root/name for name in TOP]
    selected += [root/'scripts'/name for name in SCRIPTS]
    selected += [root/'docs/balatro-ai'/name for name in DOCS]
    selected += [root/'config'/name for name in ('dependencies.lock.json','game-lifecycle.example.json',
                                               'mcp-client.example.json','startup-ui.example.json')]
    selected += [root/'prompts'/name for name in ('bootstrap.md','first-use.md','mcp-evidence.js')]
    selected += [root/'experience/README.md']
    selected += [root/'third_party'/name for name in ('NOTICE.md','balatrobot-LICENSE.txt','lovely-LICENSE.md')]
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
        if any(p in ('.artifacts','.tools','.venv','__pycache__','runs','TEST') for p in relative.parts) or '.local.' in path.name or path.suffix.lower() in ('.jkr','.dll','.exe','.png'):
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


def require_source_check(root, version):
    """Fresh source checks authorize a candidate, never a new live-game claim."""
    path=root/'runs/checks/release-check.json'
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


def main():
    version=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    report=require_source_check(ROOT,version)
    review=ROOT/'deliverables/github-ready';no_links(review)
    if review.exists():raise ValueError('github-ready already exists; preserve it and inspect before rebuilding')
    destination=ROOT/'deliverables/source';no_links(destination)
    archive=destination/('balatro-agent-'+version+'-source-candidate.zip');no_links(archive)
    if archive.exists():raise ValueError('Source candidate already exists; preserve it before rebuilding')
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
        'synthetic':report['synthetic'],'development_stdio_exit_code':0,'development_tools':11,
        'fixed_downloads_verified':True,'minimal_mod_build_verified':True,
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
    (destination/'source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Never overwrite an existing review directory or silently keep stale files.
    unpack(archive,review)
    print(json.dumps({'files':len(entries)+1,'archive':archive.relative_to(ROOT).as_posix(),
        'review_directory':review.relative_to(ROOT).as_posix(),'bytes':archive.stat().st_size,
        'sha256':manifest['archive_sha256'],'published':False}))


if __name__=='__main__':main()
