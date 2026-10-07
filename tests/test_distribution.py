"""Portable preparation and archive boundaries; no writes to real installation."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from bootstrap_sources import unpack, digest, fetch
from install_portable import make_plan
import install_portable as portable


@pytest.mark.parametrize('name',['../outside','/absolute','C:/escape','nested/../../escape','folder\\escape'])
def test_zip_cannot_escape_destination(tmp_path,name):
    archive=tmp_path/'bad.zip'
    with ZipFile(archive,'w') as bundle:bundle.writestr(name,b'data')
    if '\\' in name:
        # ZipFile normalizes names while writing on Windows; construct a real
        # incoming archive with raw backslash names in both directory headers.
        archive.write_bytes(archive.read_bytes().replace(name.replace('\\','/').encode(),name.encode()))
    with pytest.raises(ValueError):unpack(archive,tmp_path/'destination')
    assert not (tmp_path/'destination').exists()


def test_unpack_refuses_existing_edits_and_is_repeatable(tmp_path):
    archive=tmp_path/'source.zip'
    with ZipFile(archive,'w') as bundle:bundle.writestr('root/file.txt',b'fixed')
    dest=tmp_path/'destination'
    assert unpack(archive,dest,True)==1
    assert unpack(archive,dest,True)==1
    (dest/'file.txt').write_bytes(b'user edit')
    with pytest.raises(ValueError):unpack(archive,dest,True)
    assert (dest/'file.txt').read_bytes()==b'user edit'


@pytest.fixture
def install_layout(tmp_path,monkeypatch):
    # Source archive/hash comparison is checked separately below. These cases
    # isolate installation planning against synthetic external destinations.
    monkeypatch.setattr('install_portable.verify_prepared_sources',lambda root:None)
    root=tmp_path/'checkout';steam=tmp_path/'Steam';library=tmp_path/'Library'
    mods=tmp_path/'Roaming/Balatro/Mods';config=tmp_path/'Codex/config.toml'
    steam.mkdir();(steam/'steam.exe').write_bytes(b'fake')
    game=library/'steamapps/common/Balatro'
    game.mkdir(parents=True);(game/'Balatro.exe').write_bytes(b'fake')
    (library/'steamapps/appmanifest_2379780.acf').write_text('"appid" "2379780"\n"installdir" "Balatro"',encoding='utf-8')
    python=root/'.venv/Scripts/python.exe';python.parent.mkdir(parents=True);python.write_bytes(b'fake')
    build=root/'.artifacts/built-mod/balatrobot';build.mkdir(parents=True)
    (build/'reader-profile.json').write_text('{"native_ui_verified":false}',encoding='utf-8')
    (build/'balatrobot.lua').write_text('-- synthetic',encoding='utf-8')
    manifest={'files':[{'path':p.name,'sha256':digest(p)} for p in build.iterdir()]}
    (root/'mod').mkdir();(root/'mod/build-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    (root/'config').mkdir()
    smods=root/'.artifacts/upstream/smods-26.829.0';smods.mkdir(parents=True);(smods/'LICENSE').write_text('synthetic license',encoding='utf-8')
    lovely=root/'.artifacts/lovely';lovely.mkdir();(lovely/'version.dll').write_bytes(b'fake')
    config.parent.mkdir();config.write_text('model = "user-model"\n[mcp_servers.other]\ncommand = "keep"\n',encoding='utf-8')
    return root,steam,library,mods,config


def test_prepare_portable_preserves_other_config_and_never_installs(install_layout):
    root,steam,library,mods,config=install_layout
    original=config.read_bytes()
    plan,candidate=make_plan(steam,library,mods,config,root)
    assert len(plan['files'])==4 and len(plan['config_before_sha256'])==64
    assert 'launch_game' in candidate and 'close_game' in candidate
    assert 'recover_lost_session' in candidate
    assert config.read_bytes()==original and not mods.exists()
    assert plan['native_profile_attestation']=='not_created'


@pytest.mark.parametrize('existing',['mod','injector','config'])
def test_portable_never_replaces_existing_install_or_config(install_layout,existing):
    root,steam,library,mods,config=install_layout
    if existing=='mod':(mods/'balatrobot').mkdir(parents=True)
    if existing=='injector':(library/'steamapps/common/Balatro/version.dll').write_bytes(b'user dll')
    if existing=='config':config.write_text('[mcp_servers.balatro-agent]\ncommand="keep"',encoding='utf-8')
    with pytest.raises(ValueError):make_plan(steam,library,mods,config,root)


def test_corrupt_cached_dependency_is_retained_and_rejected(tmp_path):
    archive=tmp_path/'fixed.zip';archive.write_bytes(b'edited')
    item={'archive':'fixed.zip','sha256':'0'*64}
    with pytest.raises(ValueError):fetch(item,tmp_path,offline=True)
    assert archive.read_bytes()==b'edited'


def test_cache_name_cannot_escape_or_use_windows_ads(tmp_path):
    for name in ('../outside.zip','C:stream','nested\\archive.zip'):
        with pytest.raises(ValueError):fetch({'archive':name,'sha256':'0'*64},tmp_path,offline=True)


def test_autodetection_uses_verified_steam_metadata_not_save_contents(install_layout,monkeypatch):
    root,steam,library,_,_=install_layout
    actual=portable.Installation.verify(steam,library)
    calls=[]
    monkeypatch.setattr(portable.Installation,'discover',lambda config:(calls.append(config),actual)[1])
    assert portable.installation_paths(root)==(steam,library)
    assert calls==[root/'config/game-lifecycle.local.json']
    assert portable.installation_paths(root,steam,library)==(steam,library)


@pytest.mark.parametrize('missing',['steam','library'])
def test_partial_path_override_cannot_guess_another_installation(install_layout,missing):
    root,steam,library,_,_=install_layout
    with pytest.raises(ValueError,match='both'):
        portable.installation_paths(root,None if missing=='steam' else steam,None if missing=='library' else library)


def test_apply_requires_a_previously_prepared_exact_plan(install_layout):
    root,steam,library,mods,config=install_layout
    before=config.read_bytes()
    with pytest.raises(ValueError,match='Prepare and inspect'):
        portable.prepare_installation(root,steam,library,mods,config,True)
    assert not mods.exists() and config.read_bytes()==before
    assert not (root/'config/game-lifecycle.local.json').exists()


def test_apply_refuses_config_drift_since_preparation(install_layout):
    root,steam,library,mods,config=install_layout
    portable.prepare_installation(root,steam,library,mods,config)
    config.write_text('model="new-user-setting"\n',encoding='utf-8')
    with pytest.raises(ValueError,match='plan changed'):
        portable.prepare_installation(root,steam,library,mods,config,True)
    assert not mods.exists() and 'new-user-setting' in config.read_text()


def closed_backend(monkeypatch,find=lambda:None):
    if os.name!='nt':pytest.skip('Windows first-install boundary')
    class Backend:
        def __init__(self,config):pass
        def find(self):return find()
    monkeypatch.setattr(portable,'WindowsGame',Backend)


@pytest.mark.parametrize('area,value',[('executor',{'pending':{'state':'UNKNOWN'},'input_pending':None}),
    ('executor',{'pending':None}),('lifecycle',{'pending':{'state':'RUNNING'}})])
def test_first_install_refuses_pending_or_invalid_checkpoints(install_layout,monkeypatch,area,value):
    closed_backend(monkeypatch)
    root,steam,library,mods,config=install_layout
    portable.prepare_installation(root,steam,library,mods,config)
    path=root/'runs/live'/area/'checkpoint.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps(value),encoding='utf-8')
    before=config.read_bytes()
    with pytest.raises(ValueError,match='checkpoint'):
        portable.prepare_installation(root,steam,library,mods,config,True)
    assert not mods.exists() and config.read_bytes()==before


def test_first_install_preserves_crlf_config_unrelated_mods_and_opaque_save(install_layout,monkeypatch):
    closed_backend(monkeypatch)
    root,steam,library,mods,config=install_layout
    config.write_bytes(b'model = "user-model"\r\n[mcp_servers.other]\r\ncommand = "keep"\r\n')
    saved=mods.parent/'1/save.jkr';saved.parent.mkdir(parents=True);saved.write_bytes(b'opaque synthetic save')
    other=mods/'other/keep.lua';other.parent.mkdir(parents=True);other.write_bytes(b'keep unrelated Mod')
    before={p:p.read_bytes() for p in (saved,other,config)}
    prepared=portable.prepare_installation(root,steam,library,mods,config)
    assert prepared['status']=='prepared' and config.read_bytes()==before[config]
    result=portable.prepare_installation(root,steam,library,mods,config,True)
    receipt=json.loads((root/'.artifacts/portable-install.local.json').read_text())
    assert receipt['complete'] and receipt['config_applied'] and len(receipt['applied_files'])==4
    assert result['status']=='installed_needs_client_reload' and result['profile_policy']=='current-native-v1'
    assert json.loads((mods/'balatrobot/reader-profile.json').read_text())=={'native_ui_verified':False}
    assert saved.read_bytes()==before[saved] and other.read_bytes()==before[other]
    assert config.read_bytes().startswith(before[config])
    backup=Path(result['backup'])
    assert (backup/'codex-config-before.toml').read_bytes()==before[config]
    assert (backup/'Balatro/1/save.jkr').read_bytes()==before[saved]
    assert not (root/'config/test-profile.local.json').exists()


def test_game_reopened_during_backup_stops_before_external_writes(install_layout,monkeypatch):
    calls=[]
    closed_backend(monkeypatch,lambda:(calls.append(1),object() if len(calls)>1 else None)[1])
    root,steam,library,mods,config=install_layout
    portable.prepare_installation(root,steam,library,mods,config)
    before=config.read_bytes()
    with pytest.raises(ValueError,match='normally closed'):
        portable.prepare_installation(root,steam,library,mods,config,True)
    receipt=json.loads((root/'.artifacts/portable-install.local.json').read_text())
    assert not receipt['complete'] and not receipt['applied_files']
    assert not mods.exists() and config.read_bytes()==before


def test_partial_install_keeps_precise_receipt_backup_and_user_config(install_layout,monkeypatch):
    closed_backend(monkeypatch)
    root,steam,library,mods,config=install_layout
    portable.prepare_installation(root,steam,library,mods,config)
    before=config.read_bytes()
    def fail_config(source,target):raise OSError('synthetic config write failure')
    monkeypatch.setattr(portable.os,'replace',fail_config)
    with pytest.raises(OSError,match='synthetic'):
        portable.prepare_installation(root,steam,library,mods,config,True)
    receipt=json.loads((root/'.artifacts/portable-install.local.json').read_text())
    assert not receipt['complete'] and not receipt['config_applied']
    assert len(receipt['applied_files'])==4 and all(Path(p).is_file() for p in receipt['applied_files'])
    assert config.read_bytes()==before
    assert (Path(receipt['backup'])/'codex-config-before.toml').read_bytes()==before
    with pytest.raises(ValueError,match='preserved'):
        portable.prepare_installation(root,steam,library,mods,config,True)
