"""Synthetic persistence, isolation, failure and numeric behavior. No game calls."""
import asyncio
import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from mcp import Client
import pytest

from balatro_agent.calculate import Calculator
from balatro_agent.local_audit import canonical
from balatro_agent.notes import NotesService, NotesStore


@pytest.fixture
def local_settings(settings, tmp_path):
    return replace(settings, notes_dir=tmp_path/'experience')


@pytest.fixture
def content():
    return {'sources':[{'run_id':'test-synthetic','steps':[1,2]}], 'facts':['TEST：合成事实。'],
            'interpretation':['不是正式经验。'], 'conditions':['隔离合成检查。'],
            'counterexamples':['不能代替实机。'], 'confidence':'low', 'revision_reason':'创建测试内容。'}


def write(service, content, *, revision=0, write_id='write-1', note_id='TEST-PERSIST'):
    return service.write_note(note_id, content, revision, write_id, 'TEST')


def test_restart_and_separate_process_really_read_disk(local_settings,content):
    service=NotesService(local_settings)
    first=write(service,content)
    assert first['write_state']=='COMMITTED'
    code='import json,sys; from pathlib import Path; from balatro_agent.notes import NotesStore; print(json.dumps(NotesStore(Path(sys.argv[1])).read("TEST"),ensure_ascii=True))'
    external=json.loads(subprocess.check_output([sys.executable,'-c',code,str(local_settings.notes_dir)],text=True))
    assert external['notes'][0]['content']==content and external['notes'][0]['revision']==1
    path=local_settings.notes_dir/'TEST/TEST-PERSIST/r0001.md'
    assert '合成事实' in path.read_text(encoding='utf-8')
    assert NotesService(local_settings).read_notes('TEST')['notes']==external['notes']


def test_conflict_idempotence_and_full_history_after_revision(local_settings,content):
    s=NotesService(local_settings)
    first=write(s,content)
    old=(local_settings.notes_dir/'TEST/TEST-PERSIST/r0001.md').read_bytes()
    revised=copy.deepcopy(content); revised['facts'].append('TEST：修订事实。'); revised['revision_reason']='追加测试事实。'
    second=write(s,revised,revision=1,write_id='write-2')
    assert second['note']['revision']==2
    assert write(s,revised,revision=1,write_id='write-3')['status']=='revision_conflict'
    duplicate=write(NotesService(local_settings),content)
    assert duplicate['duplicate'] and duplicate['note']['revision']==1 and duplicate['note']['current_revision']==2
    assert write(s,revised,write_id='write-1')['status']=='id_conflict'
    assert (local_settings.notes_dir/'TEST/TEST-PERSIST/r0001.md').read_bytes()==old
    assert s.read_notes('TEST',['TEST-PERSIST'],1)['notes'][0]['content']==content
    assert s.read_notes('TEST',['TEST-PERSIST'])['notes'][0]['content']==revised


@pytest.mark.parametrize('target',['r0002.md','HEAD.json'])
def test_atomic_replace_failure_keeps_prior_head_and_content(local_settings,content,monkeypatch,target):
    s=NotesService(local_settings); assert write(s,content)['status']=='ok'
    changed=copy.deepcopy(content); changed['revision_reason']='修订故障检查。'
    original=os.replace
    def fail(source,destination):
        if Path(destination).name==target: raise OSError('SECRET_EXTERNAL_PATH')
        return original(source,destination)
    monkeypatch.setattr(os,'replace',fail)
    failure=write(s,changed,revision=1,write_id='write-2')
    assert failure['status']=='storage_unavailable' and failure['write_state']=='NOT_COMMITTED'
    assert 'SECRET' not in canonical(failure)
    assert s.read_notes('TEST')['notes'][0]['revision']==1
    monkeypatch.setattr(os,'replace',original)
    assert write(NotesService(local_settings),changed,revision=1,write_id='write-2')['note']['revision']==2
    assert not list(local_settings.notes_dir.rglob('.tmp-*'))


def test_fsync_failure_preserves_old_note(local_settings,content,monkeypatch):
    s=NotesService(local_settings); write(s,content)
    original=s.audit.record
    monkeypatch.setattr(s.audit,'record',lambda *args:None)
    monkeypatch.setattr(os,'fsync',lambda *args: (_ for _ in ()).throw(OSError('SECRET_FSYNC')))
    result=write(s,content,revision=1,write_id='write-2')
    assert result['write_state']=='NOT_COMMITTED'
    assert s.store.read('TEST')['notes'][0]['revision']==1


def test_prewrite_log_failure_does_not_commit_and_postwrite_is_unknown(local_settings,content,monkeypatch):
    s=NotesService(local_settings)
    def fail(*args): raise OSError('SECRET_LOG_PATH')
    monkeypatch.setattr(s.audit,'record',fail)
    result=write(s,content)
    assert result['write_state']=='NOT_COMMITTED' and not local_settings.notes_dir.exists()
    s=NotesService(local_settings); original=s.audit.record
    def fail_delivery(tool,kind,value):
        if kind=='delivered': raise OSError('SECRET_LOG_PATH')
        original(tool,kind,value)
    monkeypatch.setattr(s.audit,'record',fail_delivery)
    result=write(s,content)
    assert result['status']=='log_unavailable' and result['write_state']=='UNKNOWN'
    fresh=NotesService(local_settings)
    assert fresh.read_notes('TEST')['notes'][0]['revision']==1
    assert write(fresh,content)['duplicate']
    assert 'SECRET' not in canonical(result)


def test_cross_instance_writers_do_not_lose_updates(local_settings,content):
    write(NotesService(local_settings),content)
    a=copy.deepcopy(content);a['revision_reason']='writer a'
    b=copy.deepcopy(content);b['revision_reason']='writer b'
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda args:write(NotesService(local_settings),args[0],revision=1,write_id=args[1]),[(a,'writer-a'),(b,'writer-b')]))
    assert sum(r['status']=='ok' for r in results)==1
    assert all(r['status'] in ('ok','busy','revision_conflict') for r in results)
    assert NotesService(local_settings).read_notes('TEST')['notes'][0]['revision']==2


def test_formal_test_separation_and_empty_disk(local_settings,content):
    s=NotesService(local_settings)
    assert s.read_notes()['notes']==[]
    write(s,content)
    assert s.read_notes()['notes']==[] and len(s.read_notes('TEST')['notes'])==1
    formal=copy.deepcopy(content); formal['sources']=[{'run_id':'n5-synthetic-fixture','steps':[1]}]
    assert s.write_note('EXP-SYNTHETIC',formal,0,'formal-fixture')['status']=='ok'
    assert len(s.read_notes()['notes'])==1 and len(s.read_notes('TEST')['notes'])==1
    assert s.write_note('EXP-BAD',content,0,'bad-source')['status']=='invalid_input'


def test_compact_notes_preserve_content_revision_history_and_disk_reads(local_settings, content):
    service = NotesService(local_settings)
    write(service, content)
    path = local_settings.notes_dir/'TEST/TEST-PERSIST/r0001.md'
    before = path.read_bytes()
    full = service.read_notes('TEST')
    compact = service.read_notes('TEST', view='content')
    assert compact == {**full, 'notes': [{k: v for k, v in full['notes'][0].items() if k != 'markdown'}]}
    assert len(canonical(compact)) < len(canonical(full)) / 2
    changed = copy.deepcopy(content)
    changed['facts'].append('TEST：磁盘新修订。')
    changed['revision_reason'] = '测试每次读取最新磁盘。'
    assert write(NotesService(local_settings), changed, revision=1, write_id='write-2')['status'] == 'ok'
    assert service.read_notes('TEST', view='content')['notes'][0]['content'] == changed
    historical = service.read_notes('TEST', ['TEST-PERSIST'], 1, 'content')['notes'][0]
    assert historical['revision'] == 1 and historical['current_revision'] == 2 and historical['content'] == content
    assert path.read_bytes() == before


@pytest.mark.parametrize('view', ['', 'summary', None, [], {}])
def test_notes_unknown_view_rejects_without_echo_or_writes(local_settings, content, view):
    service = NotesService(local_settings)
    write(service, content)
    assert service.read_notes('TEST', view=view)['status'] == 'invalid_input'


@pytest.mark.parametrize('note_id',['../SECRET','C:/SECRET','TEST-X:SECRET','TEST-CON.txt','TEST-','EXP-WRONG', 'TEST-'+'X'*49,'TEST-X/SECRET','TEST-X\\SECRET'])
def test_invalid_identity_cannot_access_or_write_files(local_settings,content,note_id):
    s=NotesService(local_settings)
    result=write(s,content,note_id=note_id)
    assert result['status']=='invalid_input' and 'SECRET' not in canonical(result)
    assert not local_settings.notes_dir.exists()


def test_links_in_root_folder_and_revision_are_rejected(local_settings,content,tmp_path):
    # Junctions are included in Windows reparse-point detection; symlink when supported.
    external=tmp_path/'outside';external.mkdir()
    root=local_settings.notes_dir
    if os.name=='nt':
        subprocess.run(['cmd','/c','mklink','/J',str(root),str(external)],check=True,capture_output=True)
    else:
        root.symlink_to(external,target_is_directory=True)
    s=NotesService(local_settings)
    assert write(s,content)['status']=='unsafe_path'
    assert s.read_notes()['status']=='unsafe_path'
    assert list(external.iterdir())==[]


def test_corrupt_or_oversize_store_never_echoes_contents(local_settings,content):
    s=NotesService(local_settings);write(s,content)
    revision=local_settings.notes_dir/'TEST/TEST-PERSIST/r0001.md'
    revision.write_text('SECRET_FILE_CONTENT'*5000)
    result=s.read_notes('TEST')
    assert result['status']=='store_corrupt' and 'SECRET' not in canonical(result)
    assert write(s,content,revision=1,write_id='write-2')['status']=='store_corrupt'


@pytest.mark.parametrize('mutation',[
    lambda c:c.update(facts=[]), lambda c:c.update(facts=['X'*2001]),
    lambda c:c.update(confidence='SECRET'), lambda c:c.update(sources=[{'run_id':'test-x','steps':[0]}]),
    lambda c:c.update(sources=[{'run_id':'test-x','steps':[True]}]), lambda c:c.update(extra='SECRET'),
    lambda c:c.update(interpretation=['SECRET\x00']), lambda c:c.update(facts=['X'*1900]*10),
])
def test_content_limits_and_extra_fields_reject_safely(local_settings,content,mutation):
    mutation(content);s=NotesService(local_settings)
    result=write(s,content)
    assert result['status']=='invalid_input' and 'SECRET' not in canonical(result)


def test_read_limits_and_stale_lock_are_explicit(local_settings,content):
    s=NotesService(local_settings)
    assert s.read_notes('TEST',['TEST-MISSING'])['status']=='not_found'
    assert s.read_notes('TEST',['TEST-X']*21)['status']=='invalid_input'
    assert s.read_notes('TEST',[{}])['status']=='invalid_input'
    assert s.read_notes('TEST',revision=1)['status']=='invalid_input'
    local_settings.notes_dir.mkdir();(local_settings.notes_dir/'.writer-lock').mkdir()
    assert write(s,content)['status']=='busy'
    assert (local_settings.notes_dir/'.writer-lock').exists()


@pytest.mark.parametrize('operation,inputs,result',[
    ('sum',{'values':[1e12,1,-1e12]},1),('difference',{'values':[300,123]},177),
    ('product',{'values':[3,4,-2]},-24),('quotient',{'values':[300,4]},75),
    ('mean',{'values':[1,2,9]},4),('median',{'values':[9,1,3,7]},5),
    ('variance_population',{'values':[1,3]},1),('combination',{'n':5,'k':2},10),
    ('hypergeometric',{'population':10,'successes':4,'draws':2,'min_successes':1,'max_successes':2},2/3),
    ('hypergeometric',{'population':0,'successes':0,'draws':0,'min_successes':0,'max_successes':0},1),
    ('hypergeometric',{'population':5,'successes':1,'draws':4,'min_successes':3,'max_successes':4},0),
])
def test_arithmetic_and_probability_known_results(local_settings,operation,inputs,result):
    returned=Calculator(local_settings).calculate(operation,inputs)
    assert returned['status']=='ok' and returned['result']==pytest.approx(result)
    assert returned['inputs']==inputs and returned['formula'] and returned['assumptions']


@pytest.mark.parametrize('operation,inputs,status',[
    ('exec',{'code':'SECRET'},'invalid_input'),('sum',{'values':[None]},'invalid_input'),
    ('sum',{'values':[True]},'invalid_input'),('sum',{'values':[float('nan')]},'invalid_input'),
    ('sum',{'values':[float('inf')]},'invalid_input'),('sum',{'values':[1e13]},'invalid_input'),
    ('sum',{'values':[1]*201},'invalid_input'),('sum',{'values':[]},'invalid_input'),
    ('sum',{'values':[1],'secret':'SECRET'},'invalid_input'),('quotient',{'values':[1,0]},'division_by_zero'),
    ('difference',{'values':[1]},'invalid_input'),('product',{'values':[1e12]*200},'resource_limit'),
    ('combination',{'n':1000,'k':500},'resource_limit'),('combination',{'n':3,'k':4},'invalid_input'),
    ('combination',{'n':True,'k':1},'invalid_input'),
    ('hypergeometric',{'population':10,'successes':11,'draws':2,'min_successes':0,'max_successes':2},'invalid_input'),
])
def test_calculation_rejections_are_fixed_and_logs_match(local_settings,operation,inputs,status):
    calculator=Calculator(local_settings)
    result=calculator.calculate(operation,inputs)
    assert result['status']==status and 'SECRET' not in canonical(result) and 'inputs' not in result
    log=next((local_settings.log_dir/'local').glob('*.jsonl')).read_text(encoding='utf-8')
    assert 'SECRET' not in log and json.loads(log)['value']==result


def test_calculation_and_read_log_failures_suppress_results(local_settings,content,monkeypatch):
    c=Calculator(local_settings);s=NotesService(local_settings);write(s,content)
    def fail(*args): raise OSError('SECRET')
    monkeypatch.setattr(c.audit,'record',fail);monkeypatch.setattr(s.audit,'record',fail)
    assert c.calculate('sum',{'values':[1,2]})['status']=='log_unavailable'
    assert s.read_notes('TEST')['status']=='log_unavailable'
    assert 'notes' not in s.read_notes('TEST')


async def test_mcp_new_tool_structured_roundtrip_isolation(local_settings,content,monkeypatch):
    import balatro_agent.server as server
    monkeypatch.setattr(server,'notes',NotesService(local_settings))
    monkeypatch.setattr(server,'calculator',Calculator(local_settings))
    async with Client(server.mcp) as client:
        result=await client.call_tool('write_note',{'note_id':'TEST-PROTOCOL','content':content,'expected_revision':0,'write_id':'protocol-1','kind':'TEST'})
        assert not result.is_error and result.structured_content['write_state']=='COMMITTED'
        read=await client.call_tool('read_notes',{'kind':'TEST','note_ids':['TEST-PROTOCOL']})
        assert read.structured_content['notes'][0]['content']==content
        calc=await client.call_tool('calculate',{'operation':'sum','inputs':{'values':[2,3]}})
        assert calc.structured_content['result']==5


def test_quota_and_revision_limits_preserve_existing_notes(local_settings,content,monkeypatch):
    import balatro_agent.notes as module
    monkeypatch.setattr(module,'LIMIT_NOTES',2)
    monkeypatch.setattr(module,'LIMIT_REVISIONS',2)
    s=NotesService(local_settings)
    assert write(s,content,note_id='TEST-A')['status']=='ok'
    assert write(s,content,note_id='TEST-B')['status']=='ok'
    assert write(s,content,note_id='TEST-C')['status']=='resource_limit'
    assert write(s,content,note_id='TEST-A',revision=1,write_id='a-rev2')['status']=='ok'
    assert write(s,content,note_id='TEST-A',revision=2,write_id='a-rev3')['status']=='resource_limit'
    read=s.read_notes('TEST')
    assert [(n['note_id'],n['revision']) for n in read['notes']]==[('TEST-A',2),('TEST-B',1)]


def test_return_size_limit_does_not_deliver_partial_notes(local_settings,content,monkeypatch):
    import balatro_agent.notes as module
    s=NotesService(local_settings);write(s,content)
    monkeypatch.setattr(module,'LIMIT_RESPONSE_BYTES',100)
    result=s.read_notes('TEST')
    assert result['status']=='resource_limit' and 'notes' not in result
    monkeypatch.setattr(module,'LIMIT_RESPONSE_BYTES',262144)
    assert s.read_notes('TEST')['notes'][0]['revision']==1


def test_orphan_different_request_cannot_overwrite_then_original_recovers(local_settings,content,monkeypatch):
    s=NotesService(local_settings);write(s,content)
    original=os.replace
    def fail_head(source,destination):
        if Path(destination).name=='HEAD.json': raise OSError('HEAD failure')
        original(source,destination)
    monkeypatch.setattr(os,'replace',fail_head)
    assert write(s,content,revision=1,write_id='orphan-2')['status']=='storage_unavailable'
    path=local_settings.notes_dir/'TEST/TEST-PERSIST/r0002.md';orphan=path.read_bytes()
    monkeypatch.setattr(os,'replace',original)
    alternative=copy.deepcopy(content);alternative['revision_reason']='不同请求。'
    assert write(NotesService(local_settings),alternative,revision=1,write_id='other-2')['status']=='storage_unavailable'
    assert path.read_bytes()==orphan and s.store.read('TEST')['notes'][0]['revision']==1
    assert write(NotesService(local_settings),content,revision=1,write_id='orphan-2')['note']['revision']==2
