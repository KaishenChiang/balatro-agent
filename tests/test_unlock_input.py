"""Isolated native unlock callbacks; never a Steam/live-game acceptance."""
import json

import httpx
import pytest

from test_executor import ROOT, game, native_start_wrappers, request
from balatro_agent.executor import Executor
from balatro_agent.reader import Reader
from balatro_agent.transport import GameClient


def unlock_scene(game, count=2):
    lua, _, _ = game
    source = (ROOT/'.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
    start = source.index('G.FUNCS.overlay_menu  =')
    lua.execute(source[start:source.index('G.FUNCS.test_framework', start)], name='@functions/button_callbacks.lua')
    start = source.index('G.FUNCS.notify_then_setup_run =')
    lua.execute(source[start:source.index('G.FUNCS.change_challenge_description', start)], name='@functions/button_callbacks.lua')
    source = (ROOT/'.artifacts/game-source/functions/common_events.lua').read_text(encoding='utf-8')
    start = source.index('function unlock_notify()')
    lua.execute(source[start:source.index('function discover_card(', start)], name='@functions/common_events.lua')
    lua.globals().TEST_NOTICES = '\n'.join(f'c_test_{i}' for i in range(count))
    lua.execute("""
      G.SETTINGS.paused=true; G.CONTROLLER.cursor_down={}; G.CONTROLLER.mod_cursor_context_layer=function() end
      G.save_settings=function() TEST_SAVES=(TEST_SAVES or 0)+1 end
      TEST_REMOVALS=0; TEST_SETUP_OPENED=0; TEST_UNLOCK_READS=0
      function get_compressed() TEST_UNLOCK_READS=TEST_UNLOCK_READS+1; return TEST_NOTICES end
      love={filesystem={remove=function() TEST_NOTICES=nil end}}
      G.P_CENTERS={}
      for i=0,9 do G.P_CENTERS['c_test_'..i]={set='Joker',name='Public unlock '..i} end
      function create_UIBox_card_unlock(center)
        local button=ui({button='continue_unlock'}, {ui({text='Continue'})})
        button.created_on_pause=true; button.click=UIElement.click
        local box=ui_box({}, {ui({text=center.name}),button})
        box.remove=function(self) self.removed=true; TEST_REMOVALS=TEST_REMOVALS+1 end
        return box
      end
      setmetatable(UIBox,{__call=function(_,args)
        local box=args.definition; box.config=args.config; box.alignment={offset=args.config.offset}
        box.align_to_major=function() end
        return box
      end})
      G.UIDEF={run_setup=function()
        TEST_SETUP_OPENED=TEST_SETUP_OPENED+1
        return ui_box({}, {ui({text='Public run setup'})})
      end}
      local button=ui({button='notify_then_setup_run',id='from_game_over'})
      button.click=UIElement.click
      G.STATE=G.STATES.GAME_OVER; G.OVERLAY_MENU=ui_box({}, {button})
      G.OVERLAY_MENU.remove=function(self) self.removed=true end
    """)


def next_frame(game, seconds=.2):
    lua, _, _ = game
    # Simulate the normal Controller frame-lock release, not an MCP operation.
    lua.execute('G.CONTROLLER.locks.frame=nil; G.CONTROLLER.locks.frame_set=nil')
    lua.globals().TEST_DT=seconds
    lua.execute('''
      G.TIMERS.REAL=G.TIMERS.REAL+TEST_DT
      if G.TIMERS.UPTIME then G.TIMERS.UPTIME=G.TIMERS.UPTIME+TEST_DT end
      if not G.SETTINGS.paused then G.TIMERS.TOTAL=G.TIMERS.TOTAL+TEST_DT end
      G.CONTROLLER.locked=false
      for _,v in pairs(G.CONTROLLER.locks) do if v then G.CONTROLLER.locked=true end end
      G.E_MANAGER:update(TEST_DT,true); BA_BINDING.update(BA_READER); BA_EXECUTOR.update()
    ''')


@pytest.mark.parametrize('navigation', ['open_run_setup', 'main_menu'])
@pytest.mark.parametrize('count', [1, 2])
def test_owned_unlock_slides_on_screen_after_its_event_returns(game, navigation, count):
    """Native overlay_menu starts at y=10; VT can remain outside the room."""
    lua, call, _ = game
    unlock_scene(game, count)
    lua.execute('''
      local original=UIBox
      setmetatable(original,{__call=function(_,args)
        local box=args.definition; box.config=args.config; box.alignment={offset=args.config.offset}
        box.VT={x=0,y=40,w=5,h=5}; box.align_to_major=function() end
        return box
      end})
    ''')
    if navigation == 'main_menu':
        source=(ROOT/'.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
        start=source.index('G.FUNCS.go_to_menu =')
        lua.execute(source[start:source.index('G.FUNCS.go_to_demo_cta =',start)])
        lua.execute('''
          G.TIMERS.UPTIME=10
          G.FUNCS.wipe_on=function() end; G.FUNCS.wipe_off=function() end
          G.delete_run=function() end
          Game.main_menu=function(self)
            -- The native method resets REAL/TOTAL, not UPTIME.
            G.TIMERS.REAL=12; G.TIMERS.TOTAL=12
            G.STAGE=G.STAGES.MAIN_MENU; G.STATE=G.STATES.MENU
            G.OVERLAY_MENU=nil; G.MAIN_MENU_UI=ui_box({}, {ui({text='Main menu'})})
            G.E_MANAGER:add_event(Event({func=function() unlock_notify(); return true end}))
          end
          local button=ui({button='go_to_menu'}); button.click=UIElement.click
          G.OVERLAY_MENU=ui_box({id='you_win_UI'}, {button}); G.OVERLAY_MENU.remove=function(self) self.removed=true end
        ''')
    parent=request(game,navigation,{},'sliding-'+navigation)
    assert call('act_submit',parent)['submitted']
    for _ in range(4): next_frame(game)
    assert call('action_status',{'action_id':parent['action_id']})['state']=='RUNNING'
    assert call('reader_snapshot')['public']['ready'] is False
    for i in range(count):
        # Normal render movement, not a submitted game operation.
        lua.execute('G.OVERLAY_MENU.VT.y=0')
        for _ in range(3): next_frame(game)
        status=call('action_status',{'action_id':parent['action_id']})
        assert status['state']=='AWAITING_INPUT' and status['required_action']=='close_menu'
        child=request(game,'close_menu',{},f'sliding-input-{navigation}-{i}')
        result=call('act_submit',child)
        assert result['submitted'] and result['input_for_action_id']==parent['action_id']
        if lua.eval('G.OVERLAY_MENU~=nil'):
            assert call('action_status',{'action_id':child['action_id']})['state']=='RUNNING'
            lua.execute('G.OVERLAY_MENU.VT.y=0')
        for _ in range(3): next_frame(game)
        assert call('action_status',{'action_id':child['action_id']})['state']=='COMPLETED'
        assert lua.eval('TEST_REMOVALS')==i+1
    assert call('action_status',{'action_id':parent['action_id']})['state']=='COMPLETED'


def test_foreign_unlock_after_unrelated_owned_overlay_is_not_adopted(game):
    lua, call, _ = game
    unlock_scene(game,1)
    # The navigation created a settings overlay. A different event then
    # replaced it with an unlock. Neither readiness nor the button is proof.
    lua.execute('''
      G.FUNCS.notify_then_setup_run=function()
        G.OVERLAY_MENU=nil
        G.E_MANAGER:add_event(Event({func=function()
          G.SETTINGS.paused=true
          G.FUNCS.overlay_menu{definition=ui_box({}, {ui({text='Settings'})})}
          return true
        end}))
        G.E_MANAGER:add_event(Event({func=function() return false end,blockable=false}))
      end
    ''')
    parent=request(game,'open_run_setup',{},'foreign-unlock-parent')
    call('act_submit',parent)
    for _ in range(3): next_frame(game)
    lua.execute('G.OVERLAY_MENU=nil; unlock_notify()')
    for _ in range(3): next_frame(game)
    status=call('action_status',{'action_id':parent['action_id']})
    assert status['state']=='RUNNING'
    child=request(game,'close_menu',{},'foreign-unlock-child')
    assert call('act_submit',child)['reason']=='action_busy'
    assert lua.eval('TEST_REMOVALS')==0


def test_navigation_timeout_uses_uptime_when_native_real_clock_resets(game):
    lua,call,_=game
    unlock_scene(game,1)
    lua.execute('''
      G.TIMERS.REAL=1000; G.TIMERS.UPTIME=1000
      G.FUNCS.notify_then_setup_run=function()
        G.OVERLAY_MENU=nil; G.TIMERS.REAL=12
        G.E_MANAGER:add_event(Event({func=function() return false end}))
      end
    ''')
    parent=request(game,'open_run_setup',{},'reset-clock-timeout')
    call('act_submit',parent)
    next_frame(game,61)
    status=call('action_status',{'action_id':parent['action_id']})
    assert status['state']=='UNKNOWN' and status['reason']=='completion_timeout'


@pytest.mark.parametrize('load_locked', [False, True])
@pytest.mark.parametrize('frame_locked,wipe', [(False, False), (True, False), (False, True)])
def test_paused_unlock_readiness_matches_native_pointer_gate(game, load_locked, frame_locked, wipe):
    lua, call, _ = game
    unlock_scene(game, 1)
    lua.execute('G.OVERLAY_MENU=nil; unlock_notify(); G.E_MANAGER:update(0,true)')
    next_frame(game)
    lua.globals().TEST_LOAD = load_locked
    lua.globals().TEST_FRAME = frame_locked
    lua.globals().TEST_WIPE = wipe
    lua.execute("""
      G.CONTROLLER.locked=TEST_LOAD or TEST_WIPE; G.CONTROLLER.locks.load=TEST_LOAD
      G.CONTROLLER.locks.frame=TEST_FRAME; G.screenwipe=TEST_WIPE or nil
      G.CONTROLLER.cursor_position={x=0,y=0}; G.CONTROLLER.cursor_down={}; G.TILESCALE=1; G.TILESIZE=1
      G.CONTROLLER.HID={}; G.CONTROLLER.hovering={}; G.CONTROLLER.focused={}
    """)
    src = (ROOT/'.artifacts/game-source/engine/controller.lua').read_text(encoding='utf-8')
    start = src.index('function Controller:L_cursor_press(')
    lua.execute('Controller={};'+src[start:src.index('function Controller:L_cursor_release(',start)])
    lua.execute('Controller.L_cursor_press(G.CONTROLLER,0,0)')
    native_allowed = lua.eval('G.CONTROLLER.is_cursor_down') is True
    observed = call('reader_snapshot')['public']
    assert observed['ready'] == native_allowed
    assert next(a for a in observed['ui_actions'] if a['name']=='close_menu')['enabled'] == native_allowed


def test_navigation_yields_each_native_unlock_without_premature_completion(game):
    lua, call, _ = game
    unlock_scene(game)
    parent = request(game, 'open_run_setup', {}, 'nav-with-unlocks')
    assert call('act_submit', parent)['state']=='RUNNING'
    next_frame(game)
    # overlay_menu sets a fresh frame lock while constructing the first notice.
    assert call('action_status', {'action_id':parent['action_id']})['state']=='RUNNING'
    for _ in range(4):
        next_frame(game)
        status = call('action_status', {'action_id':parent['action_id']})
        if status['state']=='AWAITING_INPUT': break
    first_overlay = lua.eval('G.OVERLAY_MENU')
    assert status['state']=='AWAITING_INPUT' and status['required_action']=='close_menu'
    assert status['callback_confirmed'] and not status['related_events_complete']
    assert lua.eval('TEST_SETUP_OPENED')==0 and lua.eval('TEST_REMOVALS')==0
    next_frame(game, 120)
    assert call('action_status', {'action_id':parent['action_id']})['state']=='AWAITING_INPUT'
    bad = request(game, 'sort_rank', {}, 'unrelated-while-unlock')
    assert call('act_submit',bad)['reason']=='action_busy'
    for i in range(2):
        child = request(game, 'close_menu', {}, f'unlock-input-{i}')
        response = call('act_submit', child)
        assert response['submitted'] and response['input_for_action_id']==parent['action_id']
        next_frame(game)
        response = call('action_status', {'action_id':child['action_id']})
        assert response['state']=='COMPLETED' and response['callback_confirmed']
        assert lua.eval('TEST_REMOVALS')==i+1
        duplicate = call('act_submit', child)
        assert duplicate['duplicate'] and lua.eval('TEST_REMOVALS')==i+1
        if i==0:
            assert first_overlay['removed'] is True
            status = call('action_status', {'action_id':parent['action_id']})
            assert status['state']=='AWAITING_INPUT' and lua.eval('TEST_SETUP_OPENED')==0
    status = call('action_status', {'action_id':parent['action_id']})
    assert status['state']=='COMPLETED' and status['related_events_complete']
    assert lua.eval('TEST_SETUP_OPENED')==1 and lua.eval('TEST_UNLOCK_READS')==1


async def test_gateway_persists_parent_and_input_across_mcp_restart(settings, game):
    lua, call, _ = game
    unlock_scene(game)
    settings.profile_file.write_text(settings.profile_file.read_text().replace('"profile": 3','"profile": 2'))
    calls=[]
    def process(req):
        body=json.loads(req.content); calls.append(body['method'])
        result=call(body['method'],body['params'])
        if body['method'] in ('act_submit','action_status'):
            next_frame(game)
            result=call('action_status',{'action_id':body['params']['action_id']})
        return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':result})
    reader=Reader(settings,GameClient(settings.url,1,transport=httpx.MockTransport(process)))
    await reader.observe()
    exe=Executor(reader,wait_s=.1)
    parent=request(game,'open_run_setup',{},'gateway-nav')
    payload=lambda req:{k:v for k,v in req.items() if k not in ('expected_profile','game_session')}
    result=await exe.act(**payload(parent))
    assert result['state']=='AWAITING_INPUT' and exe.pending['action_id']=='gateway-nav'
    for i in range(2):
        exe=Executor(reader,wait_s=.1)
        child=request(game,'close_menu',{},f'gateway-close-{i}')
        result=await exe.act(**payload(child))
        assert result['state']=='COMPLETED' and result['input_for_action_id']=='gateway-nav'
    result=await exe.action_status(parent['action_id'])
    assert result['state']=='COMPLETED' and exe.pending is None
    assert calls.count('act_submit')==3 and lua.eval('TEST_UNLOCK_READS')==1


@pytest.mark.parametrize('mutation', [
    'G.SETTINGS.paused=false', 'G.OVERLAY_MENU.UIRoot.children[2].created_on_pause=false',
    'G.OVERLAY_MENU.UIRoot.children[2].disable_button=true', 'G.screenwipe=true',
    'G.CONTROLLER.locks.frame=true', 'G.CONTROLLER.lock_input=true',
])
def test_navigation_cannot_use_unlock_input_when_native_context_is_invalid(game, mutation):
    lua,call,_=game
    unlock_scene(game, 1)
    parent=request(game,'open_run_setup',{},'guarded-nav')
    call('act_submit',parent)
    for _ in range(5): next_frame(game)
    assert call('action_status',{'action_id':parent['action_id']})['state']=='AWAITING_INPUT'
    lua.execute(mutation)
    child=request(game,'close_menu',{},'invalid-input')
    result=call('act_submit',child)
    assert result['state']=='REJECTED' and result['submitted'] is False
    assert lua.eval('TEST_REMOVALS')==0 and lua.eval('TEST_SETUP_OPENED')==0


@pytest.mark.parametrize('fault', ['lost_input_response','lost_input_delivery','lost_parent_delivery','restart_game'])
async def test_gateway_unlock_recovery_never_replays_input(settings,game,monkeypatch,fault):
    lua,call,_=game
    unlock_scene(game,1)
    config=json.loads(settings.profile_file.read_text());config['profile']=2
    settings.profile_file.write_text(json.dumps(config))
    submitted=[]; drop=False
    def process(req):
        body=json.loads(req.content)
        if body['method']=='act_submit': submitted.append(body['params']['action_id'])
        value=call(body['method'],body['params'])
        for _ in range(5): next_frame(game)
        if body['method'] in ('act_submit','action_status'):
            value=call('action_status',{'action_id':body['params']['action_id']})
        if drop and body['method']=='act_submit': raise httpx.ReadTimeout('Lost input response',request=req)
        return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':value})
    reader=Reader(settings,GameClient(settings.url,1,transport=httpx.MockTransport(process)))
    await reader.observe()
    exe=Executor(reader,wait_s=.1)
    payload=lambda req:{k:v for k,v in req.items() if k not in ('expected_profile','game_session')}
    parent=request(game,'open_run_setup',{},'recover-nav')
    assert (await exe.act(**payload(parent)))['state']=='AWAITING_INPUT'
    child=request(game,'close_menu',{},'recover-input')
    if fault=='restart_game':
        lua.execute("BA_BINDING.session='abcdef0123456789'; BA_EXECUTOR=assert(loadfile('mod/executor.lua'))()")
        result=await exe.act(**payload(child))
        assert result['state']=='REJECTED' and submitted==['recover-nav']
        assert exe.pending and (await exe.action_status('recover-nav'))['state']=='UNKNOWN'
        return
    if fault=='lost_input_response': drop=True
    original=exe._record
    def fail_delivery(kind,value):
        target='recover-input' if fault=='lost_input_delivery' else 'recover-nav'
        if kind.startswith('delivered_') and value.get('action_id')==target: raise OSError('Lost durable delivery')
        return original(kind,value)
    if fault=='lost_input_delivery': monkeypatch.setattr(exe,'_record',fail_delivery)
    result=await exe.act(**payload(child))
    if fault in ('lost_input_response','lost_input_delivery'):
        assert result['state']=='UNKNOWN' and exe.input_pending and exe.pending
        recovered=Executor(reader,wait_s=.1)
        assert (await recovered.act(**payload(child)))['state']=='COMPLETED'
        assert submitted==['recover-nav','recover-input']
        exe=recovered
    if fault=='lost_parent_delivery': monkeypatch.setattr(exe,'_record',fail_delivery)
    result=await exe.action_status('recover-nav')
    if fault=='lost_parent_delivery':
        assert result['state']=='UNKNOWN' and exe.pending and exe.input_pending is None
        monkeypatch.setattr(exe,'_record',original)
        result=await exe.action_status('recover-nav')
    assert result['state']=='COMPLETED' and exe.pending is None and exe.input_pending is None
    assert submitted==['recover-nav','recover-input'] and lua.eval('TEST_REMOVALS')==1


def test_native_continue_run_waits_for_unlock_inputs_and_its_load_event(game):
    lua,call,_=game
    unlock_scene(game,2)
    source=(ROOT/'.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
    start=source.index('G.FUNCS.start_setup_run =')
    lua.execute(source[start:source.index('G.FUNCS.start_challenge_run =',start)])
    start=source.index('G.FUNCS.start_run =')
    lua.execute(source[start:source.index('G.FUNCS.go_to_menu =',start)])
    source=(ROOT/'.artifacts/game-source/game.lua').read_text(encoding='utf-8')
    start=source.index('    G.CONTROLLER.locks.load = true',source.index('function Game:start_run('))
    load_event=source[start:source.index('    if saveTable and saveTable.ACTION then',start)]
    start=source.index('    G.E_MANAGER:add_event(Event({',source.index('    self.HUD:recalculate()',source.index('function Game:start_run(')))
    notifications=source[start:source.index('\nend\n',start)]
    lua.execute('Game.start_run=function(self,args)\n'+'''
      TEST_LOAD_CALLS=(TEST_LOAD_CALLS or 0)+1
      G.SETTINGS.paused=false; G.STAGE=G.STAGES.RUN; G.STATE=G.STATES.SELECTING_HAND
      G.STATE_COMPLETE=true
    '''+load_event+notifications+'\nend',name='@game.lua')
    lua.execute('''
      G.FUNCS.wipe_on=function() end; G.FUNCS.wipe_off=function() end
      G.delete_run=function() end; G.SAVED_GAME={}; G.SETTINGS.current_setup='Continue'
      G.STAGE=G.STAGES.MAIN_MENU; G.STATE=G.STATES.MENU
      local button=ui({button='start_setup_run'}); button.click=UIElement.click
      G.OVERLAY_MENU=ui_box({}, {button}); G.OVERLAY_MENU.remove=function(self) self.removed=true end
    ''')
    parent=request(game,'continue_run',{},'continue-with-input')
    assert call('act_submit',parent)['state']=='RUNNING'
    for _ in range(6): next_frame(game)
    status=call('action_status',{'action_id':parent['action_id']})
    assert status['state']=='AWAITING_INPUT' and lua.eval('G.CONTROLLER.locks.load') is True
    paused_total=lua.eval('G.TIMERS.TOTAL')
    next_frame(game,120)
    assert lua.eval('G.TIMERS.TOTAL')==paused_total
    assert call('action_status',{'action_id':parent['action_id']})['state']=='AWAITING_INPUT'
    for i in range(2):
        child=request(game,'close_menu',{},f'continue-input-{i}')
        assert call('act_submit',child)['input_for_action_id']==parent['action_id']
        for _ in range(6):
            next_frame(game,1)
            if call('action_status',{'action_id':child['action_id']})['state']=='COMPLETED': break
        assert call('action_status',{'action_id':child['action_id']})['state']=='COMPLETED'
        if i==0:
            assert lua.eval('TEST_REMOVALS')==1 and lua.eval('G.CONTROLLER.locks.load') is True
            assert call('action_status',{'action_id':parent['action_id']})['state']=='AWAITING_INPUT'
    status=call('action_status',{'action_id':parent['action_id']})
    assert status['state']=='COMPLETED' and status['related_events_complete']
    assert status['snapshot']['public']['phase']=='hand'
    assert lua.eval('TEST_LOAD_CALLS')==1 and lua.eval('G.CONTROLLER.locks.load') is None


@pytest.mark.parametrize('corruption', ['missing_callback','wrong_profile','unready','no_close','wrong_required_action','wrong_input_owner'])
async def test_inconsistent_unlock_wait_preserves_unknown_checkpoint(settings,game,corruption):
    _,call,_=game
    unlock_scene(game,1)
    config=json.loads(settings.profile_file.read_text());config['profile']=2
    settings.profile_file.write_text(json.dumps(config))
    submitted=[]
    def process(req):
        body=json.loads(req.content)
        if body['method']=='act_submit': submitted.append(body['params']['action_id'])
        value=call(body['method'],body['params'])
        for _ in range(5): next_frame(game)
        if body['method'] in ('act_submit','action_status'):
            value=call('action_status',{'action_id':body['params']['action_id']})
            if value['state']=='AWAITING_INPUT':
                if corruption=='missing_callback': value['callback_confirmed']=False
                elif corruption=='wrong_profile': value['snapshot']['profile']=1
                elif corruption=='unready': value['snapshot']['ready']=False;value['snapshot']['public']['ready']=False
                elif corruption=='no_close': value['snapshot']['public']['ui_actions']=[]
                elif corruption=='wrong_required_action': value['required_action']='start_run'
                else: value['input_for_action_id']='other-action'
        return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':value})
    reader=Reader(settings,GameClient(settings.url,1,transport=httpx.MockTransport(process)))
    await reader.observe()
    exe=Executor(reader,wait_s=.1)
    parent=request(game,'open_run_setup',{},'bad-wait-parent')
    payload=lambda req:{k:v for k,v in req.items() if k not in ('expected_profile','game_session')}
    result=await exe.act(**payload(parent))
    assert result['state']=='UNKNOWN' and result['reason']=='invalid_response' and exe.pending
    child=request(game,'close_menu',{},'bad-wait-child')
    assert (await exe.act(**payload(child)))['reason']=='action_busy'
    assert submitted==['bad-wait-parent'] and exe.input_pending is None
