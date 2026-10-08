"""Execute the PowerShell bootstrap boundaries against workspace fixtures only."""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from zipfile import ZipFile

import pytest

ROOT=Path(__file__).resolve().parents[1]
PS=shutil.which('powershell.exe') if os.name=='nt' else None


def quote(value):return "'"+str(value).replace("'","''")+"'"


def run_helpers(root,item,operation):
    if not PS:pytest.skip('Windows PowerShell bootstrap')
    path=root/'item.json';path.write_text(json.dumps(item),encoding='utf-8')
    command="$ErrorActionPreference='Stop'; $tokens=$null; $errors=$null; "
    command+="$ast=[Management.Automation.Language.Parser]::ParseFile("+quote(ROOT/'scripts/setup.ps1')+",[ref]$tokens,[ref]$errors); "
    command+="if($errors.Count){throw 'PowerShell parse failed'}; "
    command+="$ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$true) | ForEach-Object {Invoke-Expression $_.Extent.Text}; "
    command+="$root="+quote(root)+"; $item=Get-Content -LiteralPath "+quote(path)+" -Raw | ConvertFrom-Json; "+operation
    return subprocess.run([PS,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-Command',command],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)


def uv_layout(root,names=('uv.exe','uvw.exe','uvx.exe')):
    archive=root/'.artifacts/sources/uv-0.9.21.zip';archive.parent.mkdir(parents=True)
    with ZipFile(archive,'w') as bundle:
        for name in names:bundle.writestr(name,b'synthetic nonexecutable '+name.encode())
    return {'version':'0.9.21','archive':archive.name,'destination':'.tools/uv',
        'url':'https://github.com/astral-sh/uv/releases/download/0.9.21/uv-x86_64-pc-windows-msvc.zip',
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}


def test_powershell_bootstrap_extracts_verified_uv_without_running_it(tmp_path):
    item=uv_layout(tmp_path)
    result=run_helpers(tmp_path,item,'Install-LockedUv $root $item $true')
    assert result.returncode==0,result.stderr
    assert (tmp_path/'.tools/uv/uv.exe').read_bytes()==b'synthetic nonexecutable uv.exe'
    assert run_helpers(tmp_path,item,'Install-LockedUv $root $item $true').returncode==0


def test_edited_uv_executable_is_preserved_before_any_other_file_is_added(tmp_path):
    item=uv_layout(tmp_path)
    exe=tmp_path/'.tools/uv/uv.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'user edits')
    result=run_helpers(tmp_path,item,'Install-LockedUv $root $item $true')
    assert result.returncode!=0 and 'differs' in result.stderr
    assert exe.read_bytes()==b'user edits' and not (exe.parent/'uvx.exe').exists()


@pytest.mark.parametrize('damage',['cache','entries','lock'])
def test_corrupt_or_unexpected_bootstrap_stops_before_extraction(tmp_path,damage):
    item=uv_layout(tmp_path,('uv.exe','uvw.exe','../outside.exe') if damage=='entries' else ('uv.exe','uvw.exe','uvx.exe'))
    if damage=='cache':(tmp_path/'.artifacts/sources/uv-0.9.21.zip').write_bytes(b'corrupt retained cache')
    if damage=='lock':item['destination']='../outside'
    result=run_helpers(tmp_path,item,'Install-LockedUv $root $item $true')
    assert result.returncode!=0
    assert not (tmp_path/'.tools').exists() and not (tmp_path/'outside.exe').exists()


def test_offline_first_use_does_not_fall_back_to_unverified_download(tmp_path):
    item=uv_layout(tmp_path);(tmp_path/'.artifacts/sources/uv-0.9.21.zip').unlink()
    result=run_helpers(tmp_path,item,'Install-LockedUv $root $item $true')
    assert result.returncode!=0 and 'absent from cache' in result.stderr
    assert not (tmp_path/'.tools').exists()


@pytest.mark.parametrize('matches',[True,False])
def test_download_checks_hash_before_committing_and_retains_mismatch(tmp_path,matches):
    if not PS:pytest.skip('Windows PowerShell bootstrap')
    body=b'synthetic download data, never executed'
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    item={'url':f'http://127.0.0.1:{server.server_port}/fixture',
          'sha256':hashlib.sha256(body).hexdigest() if matches else '0'*64}
    try:
        result=run_helpers(tmp_path,item,"Receive-LockedArchive $item (Join-Path $root 'download.zip')")
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
    if matches:
        assert result.returncode==0,result.stderr
        assert (tmp_path/'download.zip').read_bytes()==body
        assert not list(tmp_path.glob('*.part'))
    else:
        assert result.returncode!=0 and 'hash mismatch' in result.stderr
        assert not (tmp_path/'download.zip').exists()
        assert [p.read_bytes() for p in tmp_path.glob('*.part')]==[body]


def test_new_setup_entrypoints_are_in_source_allowlist():
    import sys
    sys.path.insert(0,str(ROOT/'scripts'))
    try:
        import package_source
        files={p.relative_to(ROOT).as_posix() for p in package_source.selected_files(ROOT)}
        assert {'Balatro Agent.exe','scripts/setup.ps1','prompts/first-use.md','tests/test_setup.py'}<=files
        assert not {'Balatro Agent.cmd','Install.cmd'} & files
        assert not any('.tools' in Path(p).parts or p.endswith('.local.toml') for p in files)
    finally:sys.path.remove(str(ROOT/'scripts'))


@pytest.mark.parametrize('options,message',[
    (['-Install','-Apply'],'Choose -Install'),
    (['-Install','-DependenciesOnly'],'-DependenciesOnly cannot be combined'),
])
def test_one_click_rejects_conflicting_modes_before_bootstrapping(options,message):
    if not PS:pytest.skip('Windows PowerShell bootstrap')
    result=subprocess.run([PS,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
        '-File',str(ROOT/'scripts/setup.ps1'),*options,'-Offline'],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
    assert result.returncode==1 and message in result.stderr
    assert '1/4' not in result.stdout
