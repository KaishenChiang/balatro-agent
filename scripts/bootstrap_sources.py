"""Fetch verified fixed dependencies into this checkout; no game/config writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import urllib.request
import uuid
import time
import shutil
from datetime import datetime, timezone
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]


def progress(state, component, received=0, total=-1, speed=0):
    """Installer telemetry only; never proof that preparation completed."""
    target=os.environ.get('BALATRO_SETUP_PROGRESS')
    identifier=os.environ.get('BALATRO_SETUP_ID')
    if not target or not identifier:
        return
    path=Path(target).absolute()
    if not path.is_relative_to(ROOT/'.artifacts') or '..' in path.parts:
        raise ValueError('Invalid preparation progress path')
    no_links(path)
    value={'schema':'preparation-progress-1','preparation_id':identifier,
           'stage':int(os.environ.get('BALATRO_SETUP_STAGE','3')), 'state':state,
           'component':component,'received_bytes':received,'total_bytes':total,
           'bytes_per_second':speed,'attempt':1,'utc':datetime.now(timezone.utc).isoformat()}
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temporary.open('x',encoding='utf-8') as stream:
        json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)


def no_links(path):
    for part in [*reversed(path.absolute().parents),path.absolute()]:
        try:info=part.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Links/reparse points are not accepted')


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def unpack(archive,destination,strip_root=False):
    no_links(destination)
    with ZipFile(archive) as bundle:
        entries=bundle.infolist()
        if len(entries)>20000 or sum(e.file_size for e in entries)>400_000_000:
            raise ValueError('Archive size limit exceeded')
        plans=[]; roots=set()
        for entry in entries:
            path=PurePosixPath(entry.filename)
            raw=entry.orig_filename
            if path.is_absolute() or '..' in path.parts or '\\' in raw or ':' in raw or '\x00' in raw or stat.S_ISLNK(entry.external_attr>>16):
                raise ValueError('Unsafe archive entry')
            if not path.parts:continue
            roots.add(path.parts[0])
            parts=path.parts[1:] if strip_root else path.parts
            if entry.is_dir() or not parts:continue
            target=destination.joinpath(*parts)
            no_links(target)
            if not target.absolute().is_relative_to(destination.absolute()):
                raise ValueError('Unsafe destination')
            data=bundle.read(entry)
            if target.exists() and target.read_bytes()!=data:
                raise ValueError('Existing source differs; preserve and inspect it')
            plans.append((target,data))
        if strip_root and len(roots)!=1:raise ValueError('Unexpected archive roots')
        for target,data in plans:
            if not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True)
                with target.open('xb') as stream:stream.write(data)
        return len(plans)


def fetch(item,cache,offline=False):
    if Path(item['archive']).name!=item['archive'] or ':' in item['archive'] or '\\' in item['archive']:
        raise ValueError('Unsafe cache archive name')
    path=cache/item['archive']; no_links(path)
    bundled=ROOT/'vendor'/item['archive'];no_links(bundled)
    if bundled.exists():
        if digest(bundled)!=item['sha256']:
            raise ValueError('Bundled archive hash mismatch; original retained')
        if not path.exists():
            cache.mkdir(parents=True,exist_ok=True)
            with bundled.open('rb') as source,path.open('xb') as target:
                shutil.copyfileobj(source,target);target.flush();os.fsync(target.fileno())
    if not path.exists():
        if offline:raise ValueError('Pinned archive absent from cache')
        cache.mkdir(parents=True,exist_ok=True)
        temporary=cache/(item['archive']+'.'+uuid.uuid4().hex+'.part')
        size=0
        started=time.monotonic();last=started
        progress('connecting',item['archive'])
        with urllib.request.urlopen(item['url'],timeout=30) as response,temporary.open('xb') as stream:
            total=int(response.headers.get('Content-Length',-1))
            while chunk:=response.read(65536):
                size+=len(chunk)
                if size>150_000_000:raise ValueError('Download limit exceeded')
                stream.write(chunk)
                now=time.monotonic()
                if now-started>600:raise ValueError('Dependency download exceeded 10 minutes; partial file retained')
                if now-last>=0.3:
                    stream.flush()
                    progress('downloading',item['archive'],size,total,size/max(0.1,now-started));last=now
            stream.flush();os.fsync(stream.fileno())
        progress('verifying',item['archive'],size,total)
        if digest(temporary)!=item['sha256']:raise ValueError('Archive hash mismatch; partial file retained')
        if path.exists():raise ValueError('Archive appeared during download; preserve it')
        os.replace(temporary,path)
    if digest(path)!=item['sha256']:raise ValueError('Archive hash mismatch; original retained')
    return path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cache',type=Path,default=ROOT/'.artifacts/sources')
    parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    manifest=json.loads((ROOT/'config/dependencies.lock.json').read_text(encoding='utf-8'))
    records=[]
    for item in manifest['sources']:
        destination=ROOT/item['destination']
        if not destination.absolute().is_relative_to(ROOT):raise ValueError('Destination outside checkout')
        archive=fetch(item,args.cache,args.offline)
        count=unpack(archive,destination,item['strip_root'])
        progress('working',item['name'])
        records.append({'name':item['name'],'version':item['version'],'sha256':digest(archive),'verified_files':count})
    output=ROOT/'.artifacts/bootstrap-report.json'
    output.write_text(json.dumps({'dependencies':records,'external_installation_changed':False},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'verified_dependencies':len(records),'game_or_config_changes':False}))


if __name__=='__main__':main()
