"""Synthetic lifecycle safety/recovery. Does not prove Steam/Codex operation."""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from balatro_agent.executor import Executor
from balatro_agent.lifecycle import GameLifecycle
from balatro_agent.settings import Settings
from balatro_agent.transport import ReaderError
from balatro_agent.windows_game import GameProcessError, Installation, ProcessIdentity

OBS = 'obs-0123456789abcdef-1'
PROCESS = ProcessIdentity(123, 987654321)


class Backend:
    def __init__(self):
        self.process = PROCESS
        self.launches = self.closes = self.focuses = 0
        self.finish_launch = self.finish_close = True
        self.focus_error = None

    def find(self):
        return self.process

    def focus(self, process):
        assert process == self.process
        self.focuses += 1
        if self.focus_error:
            raise GameProcessError(self.focus_error)
        return True

    def launch(self):
        self.launches += 1
        if self.finish_launch:
            self.process = PROCESS

    def close(self, process):
        assert process == self.process
        self.closes += 1
        if self.finish_close:
            self.process = None


@pytest.fixture
def game(tmp_path, monkeypatch):
    reader = SimpleNamespace(settings=replace(Settings(), log_dir=tmp_path/'logs'),
                             _tool_lock=asyncio.Lock(), connected=True)
    monkeypatch.setattr('balatro_agent.settings.ROOT', tmp_path)
    evidence=tmp_path/'runs/checks/native-profile-20261001-codex.md'
    evidence.parent.mkdir(parents=True)
    evidence.write_text('Synthetic independent profile evidence; no live verification.')
    # Frozen Settings retains real code, while profile evidence is isolated.
    profile = tmp_path/'profile.json'
    profile.write_text(json.dumps({'profile':2,'native_ui_verified':True,
        'evidence':'runs/checks/native-profile-20261001-codex.md'}))
    reader.settings = replace(reader.settings, profile_file=profile)
    reader.observation = {'observation_id':OBS,'profile':2,'phase':'terminal',
                          'ready':True,'outcome':'win','resources':{'availability':'observed'}}

    async def envelope(_):
        if not reader.connected:
            raise ReaderError('disconnected')
        return object()

    async def observe():
        return {'status':'ok','observation':reader.observation}

    reader._envelope, reader._observe = envelope, observe
    executor = Executor(reader)
    backend = Backend()
    lifecycle = GameLifecycle(reader, executor, backend, poll_s=0.001)
    executor.lifecycle = lifecycle
    return reader, executor, backend, lifecycle


async def test_existing_game_never_launched_even_with_game_unknown(game):
    r,e,b,l = game
    e.pending = {'action_id':'uncertain'}
    result = await l.launch_game('existing',0)
    assert result['state']=='COMPLETED' and result['reason']=='already_running'
    assert result['focus']=='confirmed' and result['mcp_connected']
    assert b.launches==0 and e.pending=={'action_id':'uncertain'}
    assert (await l.close_game('unsafe',OBS,0))['reason']=='game_action_unknown'
    assert b.closes==0


async def test_same_id_across_service_restart_does_not_relaunch(game):
    r,e,b,l=game
    b.process=None
    assert (await l.launch_game('once',0))['state']=='COMPLETED'
    assert b.launches==1
    b.process=None
    restarted=GameLifecycle(r,e,b)
    repeat=await restarted.launch_game('once',0)
    assert repeat['duplicate'] and repeat['state']=='COMPLETED' and b.launches==1
    assert (await restarted.close_game('once',OBS,0))['reason']=='id_conflict'


async def test_launch_timeout_and_late_recovery_query_only(game):
    r,e,b,l=game
    b.process=None; b.finish_launch=False
    assert (await l.launch_game('late',0))['state']=='UNKNOWN'
    assert l.blocks_actions() and b.launches==1
    assert (await l.launch_game('different',0))['reason']=='operation_busy'
    b.process=PROCESS
    result=await GameLifecycle(r,e,b).launch_game('late',0)
    assert result['state']=='COMPLETED' and b.launches==1
    assert not l.blocks_actions()


async def test_unknown_game_cannot_be_restarted_after_disappearance(game):
    r,e,b,l=game
    e.pending={'action_id':'uncertain'}; b.process=None
    assert (await l.launch_game('restart',0))['reason']=='game_action_unknown'
    assert b.launches==0


@pytest.mark.parametrize('changes,reason',[
    ({'phase':'hand'},'unsafe_to_close'),
    ({'phase':'menu'},'unsafe_to_close'),
    ({'ready':False},'unsafe_to_close'),
    ({'outcome':None},'unsafe_to_close'),
    ({'profile':None},'observation_unavailable'),
    ({'observation_id':'obs-0123456789abcdef-2'},'stale_observation'),
    ({'phase':'main_menu','resources':{'availability':'observed'}},'unsafe_to_close'),
])
async def test_close_rejects_uncertain_active_or_stale_states(game,changes,reason):
    r,e,b,l=game
    r.observation.update(changes)
    result=await l.close_game('unsafe',OBS,0)
    assert result['state']=='REJECTED' and result['reason']==reason and b.closes==0


@pytest.mark.parametrize('profile',[1,2,3])
@pytest.mark.parametrize('phase,outcome,availability',[
    ('terminal','win','observed'),('terminal','loss','observed'),
    ('main_menu',None,'not_applicable')])
async def test_normal_close_and_repeat_never_close_new_process(game,phase,outcome,availability,profile):
    r,e,b,l=game
    r.settings.profile_file.unlink()
    r.observation.update(profile=profile,phase=phase,outcome=outcome,resources={'availability':availability})
    result=await l.close_game('normal',OBS,0)
    assert result['state']=='COMPLETED' and result['running'] is False and b.closes==1
    b.process=ProcessIdentity(123,987654322)
    assert (await l.close_game('normal',OBS,0))['duplicate'] and b.closes==1


async def test_close_timeout_never_issues_second_close_or_allows_act(game):
    r,e,b,l=game
    b.finish_close=False
    result=await l.close_game('slow',OBS,0)
    assert result['state']=='UNKNOWN' and l.blocks_actions() and b.closes==1
    assert (await l.close_game('slow',OBS,0))['state']=='UNKNOWN' and b.closes==1
    action=await e.act('play',{},OBS,'blocked','合成检查',[])
    assert action['state']=='REJECTED' and action['reason']=='action_busy'
    b.process=None
    assert (await l.close_game('slow',OBS,0))['state']=='COMPLETED'
    assert not l.blocks_actions()


async def test_pid_reuse_is_not_successful_close(game):
    r,e,b,l=game
    b.finish_close=False
    await l.close_game('reused',OBS,0)
    b.process=ProcessIdentity(PROCESS.pid,PROCESS.created+1)
    result=await l.close_game('reused',OBS,0)
    assert result['state']=='UNKNOWN' and result['reason']=='process_changed' and b.closes==1


async def test_recovery_process_check_failure_never_clears_unknown(game,monkeypatch):
    r,e,b,l=game
    b.finish_close=False
    await l.close_game('unverified-recovery',OBS,0)
    def unavailable():raise GameProcessError('process_unverified')
    monkeypatch.setattr(b,'find',unavailable)
    result=await l.close_game('unverified-recovery',OBS,0)
    assert result['state']=='UNKNOWN' and l.blocks_actions() and b.closes==1


async def test_crash_before_dispatch_is_not_permission_to_reissue(game):
    r,e,b,l=game
    b.process=None; b.finish_launch=False
    await l.launch_game('crash',0)
    saved=l.journal.read('crash')
    saved.receipt.state='INTENT'; saved.receipt.submitted=False
    l.journal.save(saved)
    b.launches=0
    result=await GameLifecycle(r,e,b).launch_game('crash',0)
    assert result['state']=='UNKNOWN' and b.launches==0


@pytest.mark.parametrize('operation_id',['../secret','checkpoint','con','NUL.txt','x:y','LPT1','a'*81])
async def test_ids_cannot_address_arbitrary_paths_or_checkpoint(game,operation_id):
    r,e,b,l=game
    result=await l.launch_game(operation_id,0)
    assert result['reason']=='invalid_request' and b.launches==b.focuses==0
    assert not l.journal.root.exists()


async def test_broken_lifecycle_checkpoint_fails_closed(game):
    r,e,b,l=game
    l.journal.set_pending(None)
    (l.journal.root/'checkpoint.json').write_text('{invalid')
    result=await l.launch_game('corrupt',0)
    assert result['reason']=='journal_unavailable' and b.focuses==b.launches==0 and l.blocks_actions()


async def test_shared_lock_prevents_close_during_game_action(game):
    r,e,b,l=game
    async with r._tool_lock:
        assert (await l.close_game('race',OBS,0))['reason']=='operation_busy'
    assert b.closes==0


async def test_focus_denial_does_not_claim_focus_or_launch_again(game):
    r,e,b,l=game
    b.focus_error='game_window_unverified'
    result=await l.launch_game('focus-denied',0)
    assert result['state']=='COMPLETED' and result['focus']=='not_confirmed' and b.launches==0


async def test_intent_write_failure_prevents_dispatch_and_redacts_error(game,monkeypatch):
    r,e,b,l=game
    b.process=None
    def broken(_):
        raise OSError('SECRET arbitrary local path')
    monkeypatch.setattr(l.journal,'save',broken)
    result=await l.launch_game('disk-full',0)
    assert result['state']=='REJECTED' and 'SECRET' not in json.dumps(result) and b.launches==0


async def test_result_write_failure_preserves_uncertainty(game,monkeypatch):
    r,e,b,l=game
    b.process=None
    original=l.journal.save
    def fail_after_dispatch(record):
        if record.receipt.submitted:
            raise OSError('SECRET')
        return original(record)
    monkeypatch.setattr(l.journal,'save',fail_after_dispatch)
    result=await l.launch_game('disk-after',0)
    assert result['state']=='UNKNOWN' and b.launches==1 and l.blocks_actions()
    monkeypatch.setattr(l.journal,'save',original)
    assert (await l.launch_game('disk-after',0))['state']=='COMPLETED' and b.launches==1


@pytest.mark.parametrize('appid,folder', [('42','Balatro'),('2379780','../Balatro'),('2379780','C:Balatro')])
def test_installation_metadata_cannot_select_other_app_or_escape_library(tmp_path,appid,folder):
    steam=tmp_path/'Steam'; library=tmp_path/'Library'
    steam.mkdir(); (steam/'steam.exe').write_bytes(b'fake')
    (library/'steamapps/common/Balatro').mkdir(parents=True)
    (library/'steamapps/common/Balatro/Balatro.exe').write_bytes(b'fake')
    (library/'steamapps/appmanifest_2379780.acf').write_text(f'"appid" "{appid}"\n"installdir" "{folder}"')
    with pytest.raises(GameProcessError):
        Installation.verify(steam,library)
