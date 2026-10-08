"""Cold dependency preparation from public files, without game/config writes."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import tomllib
import uuid

from bootstrap_sources import no_links, digest
from package_source import selected_files, candidate_bytes

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='runs/checks/offline-preparation.json')
    args=parser.parse_args()
    output=(ROOT/args.output).absolute()
    if '..' in output.parts or not output.is_relative_to(ROOT/'runs/checks'):
        raise ValueError('Validation output belongs under runs/checks')
    no_links(output)
    if output.exists():raise ValueError('Preserve the existing validation and choose a new output')
    if os.name!='nt':raise ValueError('This cold preparation probe supports Windows x64 only')
    target=ROOT/'.artifacts'/('offline-validation-'+uuid.uuid4().hex)
    no_links(target)
    files=selected_files(ROOT)
    for source in files:
        path=target/source.relative_to(ROOT)
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(candidate_bytes(source,ROOT))
    before={p.relative_to(target).as_posix():digest(p) for p in target.rglob('*') if p.is_file()}
    assert not (target/'.tools').exists() and not (target/'.venv').exists() and not (target/'.artifacts').exists()
    environment=dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'):
        environment.pop(key,None)
    environment['BALATRO_AGENT_CLIENT_CONTEXT']='development'
    powershell=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
    setup=[powershell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
           '-File',str(target/'scripts/setup.ps1'),'-DependenciesOnly','-Offline']
    python=str(target/'.venv/Scripts/python.exe')
    manifest=json.loads((target/'config/runtime.lock.json').read_text(encoding='utf-8'))
    expected={r['name']:r['version'] for r in manifest['wheels'] if r['purpose']=='runtime'}
    query='import importlib.metadata,json,sys; print(json.dumps({"python":list(sys.version_info[:3]),"versions":{n:importlib.metadata.version(n) for n in '+repr(list(expected))+'}}))'
    commands=[('cold_dependencies',setup),('reuse_dependencies',setup),
              ('locked_versions',[python,'-c',query]),
              ('mod_build',[python,str(target/'scripts/build_mod.py')]),
              ('development_stdio',[python,str(target/'scripts/stdio_smoke.py'),'--output','runs/checks/offline-stdio.json'])]
    results=[];versions_match=False
    for kind,command in commands:
        started=time.monotonic()
        result=subprocess.run(command,cwd=target,env=environment,capture_output=True,text=True,
                              encoding='utf-8',errors='replace',timeout=180)
        (target/(kind+'.stdout.txt')).write_text(result.stdout,encoding='utf-8')
        (target/(kind+'.stderr.txt')).write_text(result.stderr,encoding='utf-8')
        elapsed=round(time.monotonic()-started,3)
        results.append({'kind':kind,'exit_code':result.returncode,'seconds':elapsed,
                        'output':(result.stdout+result.stderr)[-2000:]})
        print(json.dumps({'kind':kind,'exit_code':result.returncode,'seconds':elapsed}),flush=True)
        if result.returncode:break
        if kind=='locked_versions':
            actual=json.loads(result.stdout)
            versions_match=actual['python']==[3,13,11] and actual['versions']==expected
            if not versions_match:break
    unchanged=all((target/name).is_file() and digest(target/name)==sha for name,sha in before.items())
    build=target/'mod/build-manifest.json'
    build_match=(any(r['kind']=='mod_build' and r['exit_code']==0 for r in results)
                 and build.is_file() and build.read_bytes()==(ROOT/'mod/build-manifest.json').read_bytes())
    success=(len(results)==5 and all(r['exit_code']==0 for r in results) and versions_match and unchanged and build_match)
    report={'evidence_type':'independent_cold_offline_dependency_preparation',
            'version':tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version'],
            'utc':datetime.now(timezone.utc).isoformat(),'validation_directory':target.relative_to(ROOT).as_posix(),
            'started_without_python_venv_or_cache':True,'installer_offline_flag':True,
            'python_source':'verified local file mirror; uv 0.9.21 cannot use --offline for an uncached local archive',
            'runtime_sync_offline_flag':True,
            'copied_existing_environment':False,'locked_versions_match':versions_match,
            'source_hashes_unchanged':unchanged,'fresh_mod_build_matches':build_match,
            'development_tools':len(json.loads((target/'runs/checks/offline-stdio.json').read_text(encoding='utf-8'))['tools']) if success else None,
            'passed':success,'commands':results,
            'real_game_or_client_config_changed':False,'real_game_verified':False,
            'full_new_machine_installation_verified':False}
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('commands','validation_directory')}))
    if not success:raise ValueError('Cold offline preparation did not pass; preserve its report')


if __name__=='__main__':main()
