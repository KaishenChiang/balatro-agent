"""Synthetic activity/desktop checks; never launch Steam or a model."""
from dataclasses import replace
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from balatro_agent.activity import ActivityJournal, bilingual, open_viewer
from balatro_agent.compact import columns
from balatro_agent.contract import Envelope
from balatro_agent.reader import Reader
from balatro_agent.settings import Settings
from balatro_agent.windows_game import WindowsGame
from test_codex_handoff import run_ps
from test_lifecycle import Backend, game
from test_setup import ROOT, PS, quote


def events(journal):
    return [json.loads(line) for path in sorted(journal.root.glob('events-*.jsonl'))
            for line in path.read_text(encoding='utf-8').splitlines()]


def observation(counter=1):
    return {'observation_id':f'obs-0123456789abcdef-{counter}', 'phase':'hand', 'ready':True,
            'setup':{'deck_name':'Red Deck','stake_name':'White Stake'},
            'resources':{'ante':1,'round':2,'dollars':0,'chips':None,'hidden':'SECRET_RESOURCE'},
            'seed':'SECRET_SEED', 'draw_order':['SECRET_ORDER'],
            'regions':[{'name':'hand','cards':[
                {'position':0,'visibility':'face_up','name':'Ace','selected':True,'sort_id':'SECRET_TOKEN'},
                {'position':1,'visibility':'face_down','name':'SECRET_BACK','rank':'SECRET_RANK'},
                {'position':2,'visibility':'stone','name':None,'rank':'SECRET_STONE','suit':'SECRET_SUIT'}]}]}


@pytest.mark.parametrize('compact',[False,True])
def test_activity_whitelist_unknowns_masking_and_no_hidden_identity(settings,compact):
    journal=ActivityJournal(settings)
    value=observation()
    journal.delivered('observe',{'status':'ok','observation':columns(value) if compact else value})
    records=events(journal)
    assert len(records)==1 and records[0]['kind']=='observation'
    assert 'SECRET' not in json.dumps(records)
    data=records[0]['data']
    assert data['resources']['dollars']==0 and data['resources']['chips'] is None
    assert data['regions'][0]['cards'][1]['name'] is None
    assert data['regions'][0]['cards'][2]['name'] is None
    assert data['regions'][0]['cards'][0]['name']=='Ace'


def test_decision_reason_targets_and_poll_states_are_bounded_and_separate(settings):
    journal=ActivityJournal(settings)
    journal.delivered('observe',{'observation':observation()})
    req={'action':'play','parameters':{'positions':[0,1]},'observation_id':'obs-0123456789abcdef-1',
         'action_id':'one','reason':'Visible rationale. '*100,'experience_refs':['EXP-GENERAL-GUIDE@r1']}
    # Too-long raw requests must not enter the optional stream.
    journal.intent(req)
    assert len(events(journal))==1
    req['reason']='Visible rationale. '*30
    journal.intent(req)
    for _ in range(20): journal.progress('action_status',{'action_id':'one','state':'RUNNING','submitted':True})
    journal.progress('action_status',{'action_id':'one','state':'UNKNOWN','reason':'transport_uncertain','submitted':True})
    records=events(journal)
    assert [row['kind'] for row in records]==['observation','decision','action','action']
    assert records[1]['data']['targets'][0]['name']=='Ace'
    assert records[1]['data']['targets'][1]['name'] is None
    assert len(records[1]['data']['reason'])<=241
    assert records[-1]['data']['state']=='UNKNOWN' and records[-1]['data']['action']=='play'
    assert all(len(json.dumps(row,ensure_ascii=False).encode('utf-8'))<16384 for row in records)


def test_historical_feedback_does_not_replace_current_target_names(settings):
    journal=ActivityJournal(settings)
    newest=observation(3);newest['regions'][0]['cards'][0]['name']='Current card'
    journal.delivered('observe',{'observation':newest})
    journal.delivered('action_status',{'observation':observation(1),'state':'COMPLETED','action_id':'old'})
    journal.intent({'action':'play','parameters':{'positions':[0]},'observation_id':newest['observation_id'],
                    'action_id':'new','reason':'Use current public selection.','experience_refs':[]})
    records=events(journal)
    assert records[1]['data']['historical'] is True
    assert records[-1]['data']['targets'][0]['name']=='Current card'


def test_plan_changes_and_note_reads_are_summaries_of_submitted_data(settings):
    journal=ActivityJournal(settings)
    content={'objective':'Current public goal','priorities':['A visible priority'],
             'recheck_when':['At next visible change'],'private':'SECRET'}
    journal.delivered('run_plan',{'status':'ok','revision':1,'content':content,'write_state':'COMMITTED','duplicate':False})
    journal.delivered('run_plan',{'status':'ok','revision':1,'content':content,'read_only':True})
    journal.delivered('write_note',{'status':'ok','write_state':'COMMITTED','note':{'note_id':'EXP-A','revision':2,'content':'SECRET_FULL_NOTE'}})
    journal.delivered('read_notes',{'status':'ok','notes':[{'note_id':'EXP-A','revision':2,'markdown':'SECRET_FULL_NOTE'}]})
    records=events(journal)
    assert records[0]['data']['updated'] is True and records[1]['data']['updated'] is False
    assert records[2]['data']['notes']==[{'id':'EXP-A','revision':2}]
    assert 'SECRET' not in json.dumps(records)


def test_arithmetic_summary_does_not_copy_raw_inputs_or_unknown_numbers(settings):
    journal=ActivityJournal(settings)
    journal.delivered('calculate',{'status':'ok','operation':'sum','result':0,'inputs':{'secret':'SECRET'}})
    journal.delivered('calculate',{'status':'invalid_input','result':None,'inputs':{'secret':'SECRET'}})
    records=events(journal)
    assert records[0]['kind']=='calculation' and records[0]['data']['result']==0
    assert records[1]['data']['result'] is None and 'SECRET' not in json.dumps(records)


def test_optional_activity_write_failure_preserves_delivered_observation(settings,public_envelope):
    reader=Reader(settings)
    blocked=settings.log_dir/'blocked';blocked.parent.mkdir();blocked.write_text('occupied')
    reader.activity.root=blocked
    result=reader._deliver('observe',reader.project_envelope(Envelope.model_validate(public_envelope)))
    assert result['status']=='ok' and reader.last_delivered_observation is not None
    assert reader._log_file.is_file()


def test_mandatory_delivery_failure_does_not_publish_an_unreceived_observation(settings,public_envelope,monkeypatch):
    reader=Reader(settings)
    def fail(*args): raise OSError('SECRET_PATH')
    monkeypatch.setattr(reader,'_record_delivered',fail)
    result=reader._deliver('observe',reader.project_envelope(Envelope.model_validate(public_envelope)))
    records=events(reader.activity)
    assert result['status']=='log_unavailable' and not any(row['kind']=='observation' for row in records)
    assert records[-1]['data']['status']=='log_unavailable'


class MonitorBackend(Backend,WindowsGame):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize('existing',[False,True])
async def test_native_launch_requests_viewer_once_and_duplicate_queries_do_not_reopen(game,monkeypatch,existing):
    reader,executor,backend,lifecycle=game
    backend=MonitorBackend();backend.process=backend.process if existing else None
    lifecycle.backend=backend;calls=[]
    monkeypatch.setattr('balatro_agent.activity.open_viewer',lambda settings:calls.append('viewer') or 'requested')
    result=await lifecycle.launch_game('activity-launch',1)
    assert result['state']=='COMPLETED' and result['activity_window']=='requested' and calls==['viewer']
    again=await lifecycle.launch_game('activity-launch',1)
    assert again['duplicate'] and 'activity_window' not in again and calls==['viewer']
    assert backend.launches==(0 if existing else 1)
    backend.process=None;executor.pending={'action_id':'unresolved'}
    blocked=await lifecycle.launch_game('later-blocked',1)
    assert blocked['state']=='REJECTED' and 'activity_window' not in blocked and calls==['viewer']


@pytest.mark.asyncio
async def test_viewer_dispatch_failure_does_not_block_or_change_game_launch(game,monkeypatch):
    reader,executor,backend,lifecycle=game
    backend=MonitorBackend();backend.process=None;lifecycle.backend=backend
    def fail(settings): raise OSError('viewer not available')
    monkeypatch.setattr('balatro_agent.activity.open_viewer',fail)
    result=await lifecycle.launch_game('viewer-failed',1)
    assert result['state']=='COMPLETED' and result['reason']=='started'
    assert result['activity_window']=='unavailable' and backend.launches==1
    assert lifecycle.journal.pending() is None


@pytest.mark.asyncio
async def test_pending_action_blocks_native_launch_without_opening_viewer(game,monkeypatch):
    reader,executor,backend,lifecycle=game
    backend=MonitorBackend();backend.process=None;lifecycle.backend=backend
    executor.pending={'action_id':'unresolved'};calls=[]
    monkeypatch.setattr('balatro_agent.activity.open_viewer',lambda settings:calls.append(True) or 'requested')
    result=await lifecycle.launch_game('blocked-viewer',1)
    assert result['state']=='REJECTED' and result['reason']=='game_action_unknown'
    assert not calls and backend.launches==0


def test_development_context_never_starts_a_desktop_viewer(settings,monkeypatch):
    def fail(*args,**kwargs): pytest.fail('development must not dispatch a desktop process')
    monkeypatch.setattr('balatro_agent.activity.subprocess.Popen',fail)
    assert open_viewer(replace(settings,client_context='development'))=='disabled'


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_exe_monitor_mode_selects_read_only_viewer_and_preserves_language(tmp_path,language):
    if not PS: pytest.skip('Windows WinExe')
    scripts=tmp_path/'scripts';scripts.mkdir()
    shutil.copyfile(ROOT/'Balatro Agent.exe',tmp_path/'Balatro Agent.exe')
    (scripts/'activity_viewer.ps1').write_text('param([string]$Language)\n$Language|Set-Content -LiteralPath (Join-Path $PSScriptRoot "../called.txt") -Encoding UTF8',encoding='utf-8-sig')
    result=subprocess.run([str(tmp_path/'Balatro Agent.exe'),'--monitor','--language',language],timeout=20)
    assert result.returncode==0
    assert (tmp_path/'called.txt').read_text(encoding='utf-8-sig').strip()==language
    assert not (tmp_path/'runs').exists()


def viewer_copy(tmp_path,hook):
    scripts=tmp_path/'scripts';scripts.mkdir()
    shutil.copyfile(ROOT/'scripts/localization.ps1',scripts/'localization.ps1')
    source=(ROOT/'scripts/activity_viewer.ps1').read_text(encoding='utf-8-sig')
    marker='$form.Dispose(); $timer.Dispose(); exit 0'
    assert source.count(marker)==1
    source=source.replace(marker,hook+'\n'+marker)
    entry=scripts/'activity_viewer.ps1';entry.write_text(source,encoding='utf-8-sig')
    return entry


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_real_viewer_formats_live_summaries_and_language_switch_keeps_records(tmp_path,settings,language):
    journal=ActivityJournal(settings)
    journal.delivered('observe',{'observation':observation()})
    journal.intent({'action':'play','parameters':{'positions':[0]},'observation_id':'obs-0123456789abcdef-1','action_id':'sample',
                    'reason':'Use the observed selection.','experience_refs':['EXP-GENERAL-GUIDE@r1']})
    journal.progress('act',{'action_id':'sample','state':'UNKNOWN','reason':'transport_uncertain','submitted':True})
    hook='''$before=$body.Text;$count=$script:rows.Count
$languageChoice.SelectedIndex=if($languageChoice.SelectedIndex -eq 0){1}else{0}
@{before=$before;after=$body.Text;count=$count;after_count=$script:rows.Count;language=$script:activityLanguage;readonly=$body.ReadOnly}|ConvertTo-Json -Depth 4'''
    entry=viewer_copy(tmp_path,hook)
    result=run_ps('. '+quote(entry)+' -Preview -Language '+language+' -EventDirectory '+quote(journal.root))
    assert result['readonly'] and result['count']==result['after_count']==3
    english=result['before'] if language=='en' else result['after']
    chinese=result['after'] if language=='en' else result['before']
    assert 'Result unconfirmed: Play 1 card' in english and '结果尚未确认：出牌 1 张' in chinese
    assert 'State: Playing hand' in english and '状态：出牌阶段' in chinese
    assert 'Decision:' in english and '决策：' in chinese
    assert all(re.match(r'^\d{2}:\d{2}:\d{2}  ',line) for line in english.splitlines() if line)
    for forbidden in ('Ace','UNKNOWN','SECRET','action_status','transport_uncertain','sample','EXP-GENERAL-GUIDE','positions'):
        assert forbidden not in english and forbidden not in chinese


def test_viewer_reassembles_partial_utf8_lines_and_ignores_corrupt_records(tmp_path,settings):
    journal=ActivityJournal(settings)
    journal.emit('notice','observe',{'status':'中文状态'})
    path=next(journal.root.glob('*.jsonl'));raw=path.read_bytes();split=raw.index('中文'.encode('utf-8'))+1
    path.write_bytes(raw[:split])
    import base64
    tail=base64.b64encode(raw[split:]+b'invalid json\n').decode()
    hook='''$before=$script:rows.Count
$stream=[IO.File]::Open('''+quote(path)+''',[IO.FileMode]::Append,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite)
$bytes=[Convert]::FromBase64String('''+quote(tail)+''');$stream.Write($bytes,0,$bytes.Length);$stream.Dispose()
Refresh-Activity;Render-Activity -Force
@{before=$before;after=$script:rows.Count;text=$body.Text}|ConvertTo-Json'''
    entry=viewer_copy(tmp_path,hook)
    result=run_ps('. '+quote(entry)+' -Preview -Language zh-CN -EventDirectory '+quote(journal.root))
    assert result['before']==0 and result['after']==1 and '中文状态' in result['text']
    assert path.read_bytes()==raw+b'invalid json\n'  # Viewer preserves even corrupt records.


def test_paused_view_survives_language_switch_and_resumes_new_records(tmp_path,settings):
    journal=ActivityJournal(settings)
    journal.emit('notice','observe',{'status':'[en]before pause [zh-CN]暂停前'})
    path=next(journal.root.glob('*.jsonl'))
    hook='''$follow.Checked=$false
$newRow=@{schema='activity-v1';session='''+quote(journal.session)+''';sequence=2;utc=[DateTimeOffset]::UtcNow.ToString('o');kind='notice';tool='observe';data=@{status='[en]after pause [zh-CN]暂停后'}}|ConvertTo-Json -Compress
[IO.File]::AppendAllText('''+quote(path)+''',$newRow+"`n",(New-Object Text.UTF8Encoding($false)))
Refresh-Activity;Render-Activity
$paused=$body.Text
$languageChoice.SelectedIndex=1;$translated=$body.Text
$follow.Checked=$true
@{paused=$paused;translated=$translated;resumed=$body.Text;count=$script:rows.Count}|ConvertTo-Json'''
    entry=viewer_copy(tmp_path,hook)
    result=run_ps('. '+quote(entry)+' -Preview -Language en -EventDirectory '+quote(journal.root))
    assert result['count']==2
    assert 'before pause' in result['paused'] and 'after pause' not in result['paused']
    assert '暂停前' in result['translated'] and '暂停后' not in result['translated']
    assert '暂停后' in result['resumed'] and 'after pause' not in result['resumed']


@pytest.mark.parametrize('language', ['en','zh-CN'])
def test_routine_changes_and_arithmetic_stay_in_logs_without_cluttering_the_view(tmp_path,settings,language):
    journal=ActivityJournal(settings)
    hint={'protocol':'public-changes-v1','status':'compared','changed':['resources'],
          'unchanged':['phase'],'unknown':['hand'],'resource_changes':{'dollars':{'before':0,'after':4}},
          'hidden':'SECRET'}
    journal.delivered('observe',{'observation':observation(),'public_changes':hint})
    journal.delivered('calculate',{'status':'ok','operation':'sum','result':0})
    entry=viewer_copy(tmp_path,'@{text=$body.Text;count=$script:rows.Count}|ConvertTo-Json')
    result=run_ps('. '+quote(entry)+' -Preview -Language '+language+' -EventDirectory '+quote(journal.root))
    assert result['count']==1
    assert all(value not in result['text'] for value in ('0 → 4','sum','SECRET','Public changes','公开变化'))
    records=events(journal)
    assert len(records)==3 and records[-1]['data']['result']==0


def test_real_viewer_refreshes_then_closes_without_stopping_the_publisher(tmp_path,settings):
    if not PS: pytest.skip('Windows Forms')
    journal=ActivityJournal(settings)
    journal.emit('notice','observe',{'status':'before update'})
    directory=tmp_path/'scripts';directory.mkdir()
    shutil.copyfile(ROOT/'scripts/localization.ps1',directory/'localization.ps1')
    source=(ROOT/'scripts/activity_viewer.ps1').read_text(encoding='utf-8-sig')
    report=tmp_path/'viewer-closed.json'
    ready=tmp_path/'viewer-ready.txt'
    # The private timer only closes its own form after seeing the published update.
    hook='''$testTimer=New-Object Windows.Forms.Timer;$testTimer.Interval=100
$testTimer.Add_Tick({if($body.Text.Contains('after')){$testTimer.Stop();@{text=$body.Text;count=$script:rows.Count}|ConvertTo-Json|Set-Content -LiteralPath '''+quote(report)+''' -Encoding UTF8;$form.Close()}})
$testTimer.Start()
$form.Add_Shown({[IO.File]::WriteAllText('''+quote(ready)+''','synthetic ready')})
'''
    assert source.count('$form.ShowDialog() | Out-Null')==1
    source=source.replace('$form.ShowDialog() | Out-Null',hook+'$form.ShowDialog() | Out-Null')
    entry=directory/'activity_viewer.ps1';entry.write_text(source,encoding='utf-8-sig')
    process=subprocess.Popen([PS,'-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','Bypass','-File',str(entry),
                              '-Language','en','-EventDirectory',str(journal.root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        import time
        deadline=time.monotonic()+8
        while not ready.exists() and time.monotonic()<deadline:
            time.sleep(.05)
        assert ready.exists(), 'Synthetic viewer did not become ready'
        journal.emit('notice','observe',{'status':'after update'})
        output,error=process.communicate(timeout=20)
        assert process.returncode==0,error.decode(errors='replace')
        result=json.loads(report.read_text(encoding='utf-8-sig'))
        assert result['count']==2 and 'before' in result['text'] and 'after' in result['text']
        journal.emit('notice','observe',{'status':'publisher still works'})
        assert len(events(journal))==3
    finally:
        # Only the spawned synthetic test helper is cleaned up on test failure.
        if process.poll() is None: process.terminate();process.wait(timeout=5)


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_key_events_are_plain_and_repeated_polls_do_not_repeat_timeline_rows(tmp_path,settings,language):
    journal=ActivityJournal(settings)
    journal.delivered('observe',{'observation':observation()})
    changed=observation(2);changed['regions'][0]['cards'][0]['name']='Another hand inventory item'
    journal.delivered('observe',{'observation':changed})
    journal.intent({'action':'discard','parameters':{'positions':[0,1]},'observation_id':changed['observation_id'],
                    'action_id':'rh1010-050-copy-sharp','reason':'Keep the remaining cards.','experience_refs':[]})
    journal.progress('act',{'action_id':'rh1010-050-copy-sharp','state':'RUNNING','submitted':True})
    journal.progress('act',{'action_id':'rh1010-050-copy-sharp','state':'COMPLETED','reason':'completed'})
    journal.progress('action_status',{'action_id':'rh1010-050-copy-sharp','state':'COMPLETED','reason':'completed'})
    journal.progress('act',{'action_id':'blocked','action':'buy','state':'REJECTED','reason':'button_unavailable'})
    ending=observation(3);ending.update(phase='terminal',outcome='loss',ready=False)
    journal.delivered('observe',{'observation':ending})
    entry=viewer_copy(tmp_path,'@{text=$body.Text;count=$script:rows.Count;recent=$recent.Text}|ConvertTo-Json')
    result=run_ps('. '+quote(entry)+' -Preview -Language '+language+' -EventDirectory '+quote(journal.root))
    assert result['count']==5
    for value in ('action_status','rh1010-050-copy-sharp','COMPLETED','completed','RUNNING','Ace','Another hand inventory item','button_unavailable'):
        assert value not in result['text']
    assert ('Executed: Discard 2 cards' if language=='en' else '已执行：弃牌 2 张') in result['text']
    assert ('Run lost' if language=='en' else '本局失败') in result['text']
    assert ('disabled this button' if language=='en' else '按钮暂不可用') in result['text']
    assert re.search(r'\d{2}:\d{2}:\d{2}$',result['recent'])


def test_idle_ticks_do_not_format_existing_rows_or_change_the_view(tmp_path,settings):
    journal=ActivityJournal(settings)
    journal.delivered('observe',{'observation':observation()})
    hook='''$before=$body.Text;$script:formatCalls=0
function Format-Activity($Row) { $script:formatCalls++;return 'unexpected reformat' }
1..20|ForEach-Object { Refresh-Activity;Render-Activity }
@{before=$before;after=$body.Text;calls=$script:formatCalls}|ConvertTo-Json'''
    entry=viewer_copy(tmp_path,hook)
    result=run_ps('. '+quote(entry)+' -Preview -Language en -EventDirectory '+quote(journal.root))
    assert result['calls']==0 and result['before']==result['after']


def test_timeline_and_deduplication_memory_are_bounded(tmp_path,settings):
    journal=ActivityJournal(settings)
    for i in range(2500):
        journal.emit('decision','act',{'action':'play','action_id':f'test-{i}','card_count':1,'reason':'Synthetic bounded input.'})
    hook='''1..16|ForEach-Object { Refresh-Activity;Render-Activity }
@{rows=$script:rows.Count;seen=$script:seen.Count;cache=$script:actionDescriptions.Count;text=$body.Text}|ConvertTo-Json'''
    entry=viewer_copy(tmp_path,hook)
    result=run_ps('. '+quote(entry)+' -Preview -Language en -EventDirectory '+quote(journal.root))
    assert result['rows']==500 and result['seen']<=2048 and result['cache']<=256
    assert result['text'].count('Decision:')==500 and 'test-' not in result['text']


def test_non_observation_activity_does_not_expand_large_result_trees(settings,monkeypatch):
    def fail(value): pytest.fail('Do not expand notes or plans for the optional viewer')
    monkeypatch.setattr('balatro_agent.activity.expand',fail)
    journal=ActivityJournal(settings)
    journal.delivered('read_notes',{'status':'ok','notes':[{'note_id':'EXP-A','revision':1,'markdown':'x'*1_000_000}]})
    assert events(journal)[0]['data']['notes']==[{'id':'EXP-A','revision':1}]


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_item_plan_and_uncertain_note_summaries_show_only_relevant_information(tmp_path,settings,language):
    journal=ActivityJournal(settings);value=observation();value['phase']='shop'
    value['regions']=[{'name':'shop_jokers','cards':[
        {'position':0,'visibility':'face_up','name':'Chosen item'},
        {'position':1,'visibility':'face_up','name':'Other inventory item'}]}]
    journal.delivered('observe',{'observation':value})
    journal.intent({'action':'buy','parameters':{'region':'shop_jokers','position':0},
                    'observation_id':value['observation_id'],'action_id':'internal-buy-id',
                    'reason':'Use the confirmed public target.','experience_refs':['EXP-GENERAL-GUIDE@r1']})
    journal.progress('act',{'action_id':'internal-buy-id','state':'COMPLETED'})
    journal.delivered('write_note',{'status':'log_unavailable','write_state':'UNKNOWN'})
    content={'objective':'Review latest feedback.','priorities':['Check the current goal.','Omit this second priority.']}
    journal.delivered('run_plan',{'status':'ok','revision':2,'write_state':'COMMITTED','content':content})
    journal.delivered('run_plan',{'status':'ok','revision':2,'read_only':True,'content':content})
    entry=viewer_copy(tmp_path,'@{text=$body.Text;count=$script:rows.Count}|ConvertTo-Json')
    result=run_ps('. '+quote(entry)+' -Preview -Language '+language+' -EventDirectory '+quote(journal.root))
    assert result['count']==5
    assert result['text'].count('Chosen item' if language=='en' else '小丑牌')==2
    if language=='zh-CN':
        assert 'Chosen item' not in result['text'] and 'Review latest feedback' not in result['text']
    assert 'Other inventory item' not in result['text'] and 'Omit this second priority' not in result['text']
    assert 'internal-buy-id' not in result['text'] and 'EXP-GENERAL-GUIDE' not in result['text']
    assert ('Experience save unconfirmed' if language=='en' else '心得保存结果尚未确认') in result['text']
    assert ('Experience saved' if language=='en' else '心得已保存') not in result['text']


def test_bilingual_display_extracts_each_language_before_optional_journal_truncation(settings):
    journal=ActivityJournal(settings)
    reason='[en]'+('Short public rationale. '*11)+' [zh-CN]按当前公开反馈出牌。'
    request={'action':'play','parameters':{'positions':[0]},'observation_id':'obs-0123456789abcdef-1',
             'action_id':'bilingual','reason':reason,'experience_refs':[]}
    journal.intent(request)
    data=events(journal)[0]['data']
    assert '[zh-CN]' not in data['reason']  # raw display excerpt can end before the second language
    assert data['reason_i18n']['zh-CN']=='按当前公开反馈出牌。'
    assert len(data['reason_i18n']['en'])<=121
    from balatro_agent.actions import ActionRequest
    assert ActionRequest.model_validate(request).reason==reason  # native request/audit is not rewritten
    from balatro_agent.run_plan import PlanContent
    content={'objective':'[en]Play one verified random run. [zh-CN]游玩一局已核验的随机对局。',
             'priorities':['[zh-CN]检查新的公开反馈。 [en]Check new public feedback.'],
             'recheck_when':['At the next phase change.'],'experience_refs':[]}
    assert PlanContent.model_validate(content).model_dump()==content
    journal.delivered('run_plan',{'status':'ok','write_state':'COMMITTED','content':content})
    plan=events(journal)[-1]['data']
    assert plan['objective_i18n']['en']=='Play one verified random run.'
    assert plan['priority_i18n']['zh-CN']=='检查新的公开反馈。'


@pytest.mark.parametrize('invalid', [None, '[en]Only one language', '[en]one [en]two',
                                    '[en]one [zh-CN]', '[en]one [zh-CN]二 [en]three'])
def test_ambiguous_bilingual_submissions_do_not_create_a_translation(invalid):
    assert bilingual(invalid)=={}


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_real_viewer_selects_matching_model_summary_and_translates_foreign_setup(tmp_path,settings,language):
    journal=ActivityJournal(settings)
    value=observation();value['setup']={'deck_name':'红色牌组','stake_name':'紫注'}
    journal.delivered('observe',{'observation':value})
    journal.intent({'action':'play','parameters':{'positions':[0]},'observation_id':value['observation_id'],
                    'action_id':'bilingual-real-viewer',
                    'reason':'[zh-CN]按当前条件补足分数。 [en]Meet the score using current conditions.',
                    'experience_refs':[]})
    content={'objective':'[en]Finish one random run. [zh-CN]完成一局随机对局。',
             'priorities':['[zh-CN]保留弃牌机会。 [en]Keep a discard available.']}
    journal.delivered('run_plan',{'status':'ok','write_state':'COMMITTED','content':content})
    hook='''$first=$body.Text;$languageChoice.SelectedIndex=if($languageChoice.SelectedIndex -eq 0){1}else{0}
@{first=$first;second=$body.Text;count=$script:rows.Count}|ConvertTo-Json'''
    entry=viewer_copy(tmp_path,hook)
    result=run_ps('. '+quote(entry)+' -Preview -Language '+language+' -EventDirectory '+quote(journal.root))
    english=result['first'] if language=='en' else result['second']
    chinese=result['second'] if language=='en' else result['first']
    assert result['count']==3
    assert 'Red Deck · Purple Stake' in english and '红色牌组 · 紫注' in chinese
    for expected in ('Meet the score using current conditions.','Finish one random run.','Keep a discard available.'):
        assert expected in english and expected not in chinese
    for expected in ('按当前条件补足分数。','完成一局随机对局。','保留弃牌机会。'):
        assert expected in chinese and expected not in english
    assert not re.search(r'[\u3400-\u9fff]',english)
    assert not re.search(r'[A-Za-z]{2,}',chinese)
    assert '[en]' not in english+chinese and '[zh-CN]' not in english+chinese


@pytest.mark.parametrize('language',['en','zh-CN'])
def test_untranslated_or_mislabelled_text_does_not_leak_foreign_prose_or_invent_a_plan(tmp_path,settings,language):
    journal=ActivityJournal(settings)
    foreign='只保留原文，没有翻译。' if language=='en' else 'Only the original rationale, no translation.'
    journal.intent({'action':'play','parameters':{'positions':[0]},'observation_id':'obs-0123456789abcdef-1',
                    'action_id':'foreign', 'reason':foreign,'experience_refs':[]})
    # Label alone cannot make a Chinese sentence English or vice versa.
    journal.emit('plan','run_plan',{'updated':True,'objective':'original',
        'objective_i18n':{'en':'错误的中文。','zh-CN':'Incorrect English.'},'priorities':[]})
    journal.emit('notice','observe',{'status':foreign})
    entry=viewer_copy(tmp_path,'@{text=$body.Text;count=$script:rows.Count}|ConvertTo-Json')
    result=run_ps('. '+quote(entry)+' -Preview -Language '+language+' -EventDirectory '+quote(journal.root))
    assert result['count']==3 and foreign not in result['text']
    if language=='en':
        assert 'English summary unavailable' in result['text'] and 'Decision: Play 1 card' in result['text']
        assert not re.search(r'[\u3400-\u9fff]',result['text'])
    else:
        assert '暂无中文计划摘要' in result['text'] and '决策：出牌 1 张' in result['text']
        assert not re.search(r'[A-Za-z]{2,}',result['text'])
    assert events(journal)[0]['data']['reason']==foreign


def test_complete_public_catalogue_and_reported_legacy_sentences_use_selected_language():
    command='. '+quote(ROOT/'scripts/localization.ps1')+''';$rows=@();$choices=Get-BalatroPlayChoices
foreach($choice in @($choices.Decks)+@($choices.Stakes)) {
    $rows+=@{en=(Get-BalatroDisplayName $choice.Name en activity_deck_unknown);
             zh=(Get-BalatroDisplayName $choice.EnglishName zh-CN activity_deck_unknown);
             expected_en=$choice.EnglishName;expected_zh=$choice.Name}
}
@{rows=$rows;plan=(Get-BalatroDisplayProse 'Start exactly one native unseeded run with the verified Red Deck and White Stake.' zh-CN);
decision=(Get-BalatroDisplayProse 'Red Deck is visibly selected and enabled; verify its White Stake option.' zh-CN)}|ConvertTo-Json -Depth 4'''
    result=run_ps(command)
    assert len(result['rows'])==25
    assert all(row['en']==row['expected_en'] and row['zh']==row['expected_zh'] for row in result['rows'])
    assert result['plan']=='按已核验的设置开始一局原生随机对局。'
    assert result['decision']=='红色牌组已选中且可用；核验白注选项。'
