"""Real WinExe/PowerShell boundaries with synthetic workers and local HTTP only."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pytest

from test_setup import ROOT, PS, quote, run_helpers

sys.path.insert(0,str(ROOT/'scripts'))
from package_source import verify_launcher


@pytest.mark.parametrize('mode',['resume','ignore_range','invalid_range'])
def test_download_resumes_only_matching_range_and_preserves_original(tmp_path,mode):
    body=b'public synthetic archive'*5000
    original=tmp_path/('download.zip.'+'1'*32+'.part')
    prefix=body[:23000];original.write_bytes(prefix)
    ranges=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ranges.append(self.headers.get('Range'))
            if mode=='ignore_range':
                content=body;self.send_response(200)
            else:
                content=body[len(prefix):];self.send_response(206)
                start=len(prefix) if mode=='resume' else len(prefix)+1
                self.send_header('Content-Range',f'bytes {start}-{len(body)-1}/{len(body)}')
            self.send_header('Content-Length',str(len(content)));self.end_headers()
            self.wfile.write(content)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    item={'url':f'http://127.0.0.1:{server.server_port}/archive','sha256':hashlib.sha256(body).hexdigest()}
    try:
        result=run_helpers(tmp_path,item,"Receive-LockedArchive $item (Join-Path $root 'download.zip') 2 0")
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
    assert original.read_bytes()==prefix and ranges==[f'bytes={len(prefix)}-']
    if mode=='invalid_range':
        assert result.returncode!=0 and not (tmp_path/'download.zip').exists()
    else:
        assert result.returncode==0,result.stderr
        assert (tmp_path/'download.zip').read_bytes()==body


def test_stalled_download_times_out_and_retries_with_bounded_wait(tmp_path):
    if not PS:pytest.skip('Windows PowerShell')
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path);self.send_response(200)
            self.send_header('Content-Length','10000');self.end_headers()
            time.sleep(3)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    started=time.monotonic()
    try:
        result=run_helpers(tmp_path,{'url':f'http://127.0.0.1:{server.server_port}/stall','sha256':'0'*64},
            "Receive-LockedArchive $item (Join-Path $root 'download.zip') 1 1")
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
    assert result.returncode!=0 and not (tmp_path/'download.zip').exists()
    assert len(calls)==2 and time.monotonic()-started<10


def test_progress_receipt_is_updated_atomically_and_bound_to_launch(tmp_path):
    path=tmp_path/'progress.json'
    operation="$env:BALATRO_SETUP_PROGRESS="+quote(path)+";$env:BALATRO_SETUP_ID='new-launch';$env:BALATRO_SETUP_STAGE='1';"
    operation+="Write-PreparationProgress 'connecting' 'uv';Write-PreparationProgress 'downloading' 'uv' 1024 2048 512;"
    operation+="Write-PreparationProgress 'verifying' 'uv' 2048 2048 0"
    result=run_helpers(tmp_path,{},operation)
    assert result.returncode==0,result.stderr
    value=json.loads(path.read_text())
    assert value['preparation_id']=='new-launch' and value['state']=='verifying'
    assert value['received_bytes']==value['total_bytes']==2048
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('exit_code',[0,19])
def test_real_exe_uses_unicode_project_and_creates_no_console(tmp_path,exit_code):
    if not PS:pytest.skip('Windows WinExe')
    root=tmp_path/'中文 path & bang!';scripts=root/'scripts';scripts.mkdir(parents=True)
    executable=root/'Balatro Agent.exe';shutil.copyfile(ROOT/executable.name,executable)
    source="param([switch]$Preview,[string]$PreviewImage,[string]$PreviewState)\n"
    source+="Add-Type 'using System; using System.Runtime.InteropServices; public static class ConsoleProbe { [DllImport(\"kernel32.dll\")] public static extern IntPtr GetConsoleWindow(); }'\n"
    source+="$value=@{root=$PSScriptRoot;console=[ConsoleProbe]::GetConsoleWindow().ToInt64();image=$PreviewImage;preview=[bool]$Preview}\n"
    source+="[IO.File]::WriteAllText((Join-Path $PSScriptRoot '../called.json'),($value|ConvertTo-Json))\n"
    source+=f'exit {exit_code}\n'
    (scripts/'launcher.ps1').write_text(source,encoding='utf-8-sig')
    image=root/'截图 with spaces.png'
    result=subprocess.run([str(executable),'--preview','--preview-image',str(image)],cwd=tmp_path,timeout=30)
    value=json.loads((root/'called.json').read_text(encoding='utf-8-sig'))
    assert result.returncode==exit_code and value['console']==0
    assert value['root']==str(scripts) and value['image']==str(image) and value['preview']


def test_public_binary_is_bound_to_its_own_source_and_build_receipt(tmp_path):
    assert verify_launcher(ROOT)
    for relative in ('Balatro Agent.exe','windows/launcher-build.json','windows/Launcher.cs',
                     'windows/app.manifest','scripts/build_launcher.ps1','pyproject.toml'):
        target=tmp_path/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/relative,target)
    assert verify_launcher(tmp_path)
    (tmp_path/'windows/Launcher.cs').write_text('changed source')
    assert not verify_launcher(tmp_path)
