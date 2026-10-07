"""Prepare a portable first-install plan; --apply backs up and refuses replacement.

No game launch/exit, save parsing, profile selection or API-model calls.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tomllib
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from balatro_agent.windows_game import Installation, WindowsGame
from bootstrap_sources import no_links, digest, fetch, unpack
from update_mod import ensure_idle

ROOT=Path(__file__).resolve().parents[1]
TOOLS=['health','observe','wait_until_ready','act','action_status','read_notes','write_note','calculate','launch_game','close_game','recover_lost_session']


def installation_paths(root,steam_dir=None,library_dir=None):
    if (steam_dir is None)!=(library_dir is None):
        raise ValueError('Specify both Steam and library directories, or neither for automatic detection')
    if steam_dir is not None:
        Installation.verify(steam_dir,library_dir)
        return steam_dir.absolute(),library_dir.absolute()
    installation=Installation.discover(root/'config/game-lifecycle.local.json')
    return installation.steam.parent,installation.game.parents[3]


def quote(value):
    return json.dumps(str(value),ensure_ascii=False)


def verify_prepared_sources(root):
    manifest=json.loads((root/'config/dependencies.lock.json').read_text(encoding='utf-8'))
    for item in manifest['sources']:
        archive=fetch(item,root/'.artifacts/sources',offline=True)
        target=(root/item['destination']).absolute()
        if not target.is_relative_to(root.absolute()):raise ValueError('Dependency outside checkout')
        # Compare prepared bytes against the pinned archive. Existing edits are
        # retained and rejected, rather than re-labelled as a fixed version.
        unpack(archive,target,item['strip_root'])


def make_plan(steam_dir,library_dir,mods,config,root=ROOT):
    verify_prepared_sources(root)
    installation=Installation.verify(steam_dir,library_dir)
    mods,config=mods.absolute(),config.absolute()
    no_links(mods);no_links(config)
    targets=[mods/'balatrobot',mods/'smods',installation.game.parent/'version.dll',installation.game.parent/'winmm.dll']
    for target in targets:
        no_links(target)
        if target.exists():raise ValueError('Existing Mod/injector installation is preserved; first install refused')
    before=config.read_bytes() if config.is_file() else b''
    parsed=tomllib.loads(before.decode('utf-8-sig'))
    if 'balatro-agent' in parsed.get('mcp_servers',{}):raise ValueError('Existing balatro-agent config is preserved')
    python=root/'.venv/Scripts/python.exe'
    if not python.is_file():raise ValueError('Run uv sync --locked with Python3.13 first')
    build=root/'.artifacts/built-mod/balatrobot'
    manifest=json.loads((root/'mod/build-manifest.json').read_text(encoding='utf-8'))
    files=[]
    for entry in manifest['files']:
        source=(build/entry['path']).absolute()
        target=(mods/'balatrobot'/entry['path']).absolute()
        if '..' in Path(entry['path']).parts or not source.is_relative_to(build.absolute()) or not target.is_relative_to((mods/'balatrobot').absolute()):raise ValueError('Unsafe build manifest')
        no_links(source);no_links(target)
        if digest(source)!=entry['sha256']:raise ValueError('Mod source hash mismatch')
        files.append({'source':str(source),'target':str(target),'sha256':entry['sha256']})
    profile=json.loads((build/'reader-profile.json').read_text(encoding='utf-8'))
    if profile!={'native_ui_verified':False}:raise ValueError('Do not distribute a local profile attestation')
    smods=root/'.artifacts/upstream/smods-26.829.0'
    if not (smods/'LICENSE').is_file():raise ValueError('Verified Steamodded source required')
    for source in sorted(smods.rglob('*')):
        no_links(source)
        if source.is_file():
            target=mods/'smods'/source.relative_to(smods)
            no_links(target)
            files.append({'source':str(source),'target':str(target),'sha256':digest(source)})
    dll=root/'.artifacts/lovely/version.dll'
    no_links(dll)
    files.append({'source':str(dll),'target':str(installation.game.parent/'version.dll'),'sha256':digest(dll)})
    snippet='\n\n[mcp_servers.balatro-agent]\ncommand = '+quote(python)+'\nargs = ["-m", "balatro_agent.server"]\ncwd = '+quote(root)+'\nenabled = true\nenabled_tools = '+json.dumps(TOOLS)+'\nstartup_timeout_sec = 20\ntool_timeout_sec = 45\n\n[mcp_servers.balatro-agent.env]\nBALATRO_AGENT_CLIENT_CONTEXT = "codex_config"\n'
    candidate=before.decode('utf-8-sig')+snippet
    after=tomllib.loads(candidate)
    actual=after.pop('mcp_servers')['balatro-agent']
    original_others=tomllib.loads(candidate)
    del original_others['mcp_servers']['balatro-agent']
    expected=tomllib.loads(before.decode('utf-8-sig'));expected.setdefault('mcp_servers',{})
    if original_others!=expected or actual['enabled_tools']!=TOOLS:raise ValueError('Unrelated configuration changed')
    return {'schema':'portable-first-install-1','steam_dir':str(Path(steam_dir).absolute()),'library_dir':str(Path(library_dir).absolute()),
            'save_root':str(mods.parent),'config':str(config),'config_before_sha256':__import__('hashlib').sha256(before).hexdigest(),
            'files':files,'native_profile_attestation':'not_created','game_or_save_changes':False},candidate


def apply_plan(plan,candidate,root=ROOT):
    if os.name!='nt':raise ValueError('Windows only')
    lifecycle=root/'config/game-lifecycle.local.json'
    backend=WindowsGame(lifecycle)
    ensure_idle(root,backend)
    report=root/'.artifacts/portable-install.local.json';no_links(report)
    if report.exists():raise ValueError('Preserve the previous installation receipt before another attempt')
    config=Path(plan['config']);no_links(config)
    old=config.read_bytes() if config.exists() else b''
    if __import__('hashlib').sha256(old).hexdigest()!=plan['config_before_sha256']:raise ValueError('Config changed after preparation')
    for entry in plan['files']:
        source,target=Path(entry['source']),Path(entry['target'])
        no_links(source);no_links(target)
        if target.exists() or digest(source)!=entry['sha256']:raise ValueError('Target appeared or source changed; no replacement allowed')
    backup=root/'.artifacts/backups'/('portable-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8])
    no_links(backup)
    backup.mkdir(parents=True)
    (backup/'codex-config-before.toml').write_bytes(old)
    if digest(backup/'codex-config-before.toml')!=plan['config_before_sha256']:raise ValueError('Config backup verification failed')
    saved=[]
    save_root=Path(plan['save_root'])
    # Only an opaque backup; never decode saves or use their contents for play.
    if save_root.exists():
        for source in sorted(save_root.rglob('*')):
            no_links(source)
            if source.is_file():
                target=backup/'Balatro'/source.relative_to(save_root)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,target)
                if digest(target)!=digest(source):raise ValueError('Save backup verification failed')
                saved.append({'relative':source.relative_to(save_root).as_posix(),'sha256':digest(target)})
    (backup/'manifest.json').write_text(json.dumps({'verified':True,'config_sha256':plan['config_before_sha256'],'opaque_saved_files':saved},indent=2)+'\n',encoding='utf-8')
    applied=[]
    config_applied=False
    try:
        ensure_idle(root,backend)
        for entry in plan['files']:
            source,target=Path(entry['source']),Path(entry['target'])
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(source.read_bytes());stream.flush();os.fsync(stream.fileno())
            if digest(target)!=entry['sha256']:raise ValueError('Installed hash mismatch')
            applied.append(entry['target'])
        # Last check and atomic config replace, preserving every other setting.
        no_links(config)
        if config.exists() and digest(config)!=plan['config_before_sha256']:raise ValueError('Config changed during install; preserve it')
        config.parent.mkdir(parents=True,exist_ok=True)
        temp=config.with_name(config.name+'.balatro-'+uuid.uuid4().hex+'.tmp')
        with temp.open('xb') as stream:stream.write(candidate.encode('utf-8'));stream.flush();os.fsync(stream.fileno())
        os.replace(temp,config)
        if config.read_bytes()!=candidate.encode('utf-8'):raise ValueError('Installed config verification failed')
        config_applied=True
    finally:
        report.write_text(json.dumps({'backup':str(backup),'applied_files':applied,'expected_files':len(plan['files']),
            'config_applied':config_applied,'complete':config_applied and len(applied)==len(plan['files']),
            'profile_verified':False,'game_started':False,'no_existing_file_deleted':True},indent=2)+'\n',encoding='utf-8')
    return backup


def prepare_installation(root,steam_dir,library_dir,mods,client_config,apply=False):
    plan,candidate=make_plan(steam_dir,library_dir,mods,client_config,root)
    artifacts=root/'.artifacts';no_links(artifacts)
    artifacts.mkdir(exist_ok=True)
    frozen=artifacts/'portable-plan.local.json'
    config_candidate=artifacts/'portable-config-candidate.local.toml'
    no_links(frozen);no_links(config_candidate)
    if apply:
        if not frozen.is_file() or not config_candidate.is_file():
            raise ValueError('Prepare and inspect the installation plan before --apply')
        if json.loads(frozen.read_text(encoding='utf-8'))!=plan or config_candidate.read_bytes()!=candidate.encode('utf-8'):
            raise ValueError('Installation plan changed; preserve the old plan and review a fresh preparation')
    else:
        frozen.write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8',newline='\n')
        config_candidate.write_text(candidate,encoding='utf-8',newline='\n')
    local=root/'config/game-lifecycle.local.json';no_links(local)
    config={'steam_dir':plan['steam_dir'],'library_dir':plan['library_dir']}
    if local.exists() and json.loads(local.read_text(encoding='utf-8-sig'))!=config:
        raise ValueError('Existing lifecycle config differs; preserve it')
    if not local.exists():local.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    backup=apply_plan(plan,candidate,root) if apply else None
    return {'status':'installed_needs_client_reload' if apply else 'prepared',
        'prepared_files':len(plan['files']),'external_installation_applied':bool(apply),
        'plan':str(frozen),'client_config_candidate':str(config_candidate),
        'backup':str(backup) if backup else None,'profile_policy':'current-native-v1',
        'native_profile_verified':False,'game_started':False}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--steam-dir',type=Path)
    parser.add_argument('--library-dir',type=Path)
    parser.add_argument('--mods-dir',type=Path,default=Path(os.environ.get('APPDATA',str(Path.home()/'AppData/Roaming')))/'Balatro/Mods')
    parser.add_argument('--codex-config',type=Path,default=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    steam,library=installation_paths(ROOT,args.steam_dir,args.library_dir)
    print(json.dumps(prepare_installation(ROOT,steam,library,args.mods_dir,args.codex_config,args.apply)))


if __name__=='__main__':main()
