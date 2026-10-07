"""Bundled original distributions obey the same hash and drift boundaries."""
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pytest

from test_setup import ROOT, run_helpers, uv_layout

sys.path.insert(0,str(ROOT/'scripts'))
import bootstrap_sources


def digest(data):return hashlib.sha256(data).hexdigest()


def layout(root):
    (root/'config').mkdir()
    (root/'vendor').mkdir()
    (root/'uv.lock').write_bytes(b'public synthetic dependency lock')
    files={'python/20251217/cpython-3.13.11+20251217-x86_64-pc-windows-msvc-install_only_stripped.tar.gz':b'public Python archive',
           'wheels/public-1-py3-none-any.whl':b'public original wheel'}
    archive=root/'vendor/runtime-windows-x64.zip'
    with ZipFile(archive,'w') as bundle:
        for name,data in files.items():bundle.writestr(name,data)
    records=[{'path':name,'sha256':digest(data),'bytes':len(data),'name':'public','version':'1'} for name,data in files.items()]
    manifest={'schema':'balatro-offline-runtime-1','platform':'windows-x86_64',
              'python_version':'3.13.11','uv_version':'0.9.21','archive':archive.name,
              'sha256':digest(archive.read_bytes()),'uv_lock_sha256':digest((root/'uv.lock').read_bytes()),
              'python':records[0],'wheels':records[1:]}
    (root/'config/runtime.lock.json').write_text(json.dumps(manifest),encoding='utf-8')
    (root/'config/dependencies.lock.json').write_text(json.dumps({'offline_runtime':{
        'manifest':'config/runtime.lock.json','sha256':digest((root/'config/runtime.lock.json').read_bytes())}}),encoding='utf-8')
    return manifest,files


def test_bundled_runtime_preflights_all_files_then_extracts_and_reuses(tmp_path):
    _,files=layout(tmp_path)
    for _ in range(2):
        result=run_helpers(tmp_path,{},'$value=Install-LockedRuntime $root $true; $value | ConvertTo-Json -Compress')
        assert result.returncode==0,result.stderr
        value=json.loads(result.stdout)
        assert value['Mirror'].startswith('file:///')
        assert Path(value['Wheels'])==tmp_path/'.artifacts/offline-runtime/wheels'
        assert all((tmp_path/'.artifacts/offline-runtime'/name).read_bytes()==data for name,data in files.items())


@pytest.mark.parametrize('damage',['archive','member','unregistered','traversal','source_lock','existing'])
def test_bundled_runtime_damage_refuses_before_other_extraction(tmp_path,damage):
    manifest,files=layout(tmp_path)
    archive=tmp_path/'vendor/runtime-windows-x64.zip'
    if damage=='archive':archive.write_bytes(b'corrupt input retained')
    if damage in ('member','unregistered'):
        entries=dict(files)
        if damage=='member':entries[next(iter(files))]=b'replaced upstream input'
        else:entries['unregistered.exe']=b'unregistered'
        with ZipFile(archive,'w') as bundle:
            for name,data in entries.items():bundle.writestr(name,data)
        manifest['sha256']=digest(archive.read_bytes())
    if damage=='traversal':manifest['wheels'][0]['path']='wheels/../../escape.whl'
    if damage=='source_lock':(tmp_path/'uv.lock').write_bytes(b'changed source lock')
    existing=None
    if damage=='existing':
        existing=tmp_path/'.artifacts/offline-runtime'/next(iter(files))
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b'local modification retained')
    (tmp_path/'config/runtime.lock.json').write_text(json.dumps(manifest),encoding='utf-8')
    (tmp_path/'config/dependencies.lock.json').write_text(json.dumps({'offline_runtime':{
        'manifest':'config/runtime.lock.json','sha256':digest((tmp_path/'config/runtime.lock.json').read_bytes())}}),encoding='utf-8')
    original=archive.read_bytes()
    result=run_helpers(tmp_path,{},'Install-LockedRuntime $root $true')
    assert result.returncode!=0
    assert archive.read_bytes()==original
    assert not (tmp_path/'.artifacts/offline-runtime/wheels').exists()
    if existing:assert existing.read_bytes()==b'local modification retained'


def test_uv_can_bootstrap_offline_from_bundled_archive(tmp_path):
    item=uv_layout(tmp_path)
    vendor=tmp_path/'vendor';vendor.mkdir()
    original=tmp_path/'.artifacts/sources'/item['archive']
    original.rename(vendor/item['archive'])
    result=run_helpers(tmp_path,item,'Install-LockedUv $root $item $true')
    assert result.returncode==0,result.stderr
    assert original.read_bytes()==(vendor/item['archive']).read_bytes()


@pytest.mark.parametrize('corrupt',[False,True])
def test_mod_bundle_never_needs_network_and_damaged_bundle_is_retained(tmp_path,monkeypatch,corrupt):
    vendor=tmp_path/'vendor';vendor.mkdir()
    (vendor/'public.zip').write_bytes(b'bad' if corrupt else b'public fixed original')
    monkeypatch.setattr(bootstrap_sources,'ROOT',tmp_path)
    def unexpected(*args,**kwargs):raise AssertionError('Bundled input must not download')
    monkeypatch.setattr(bootstrap_sources.urllib.request,'urlopen',unexpected)
    item={'archive':'public.zip','sha256':digest(b'public fixed original')}
    cache=tmp_path/'.artifacts/sources'
    if corrupt:
        with pytest.raises(ValueError,match='Bundled archive hash mismatch'):
            bootstrap_sources.fetch(item,cache,offline=True)
        assert not cache.exists()
    else:assert bootstrap_sources.fetch(item,cache,offline=True).read_bytes()==b'public fixed original'
    assert (vendor/'public.zip').read_bytes()==(b'bad' if corrupt else b'public fixed original')
