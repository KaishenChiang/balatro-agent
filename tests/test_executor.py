"""Synthetic execution boundaries using fixed native click/selection/event code.

These do not count as real Steam or current Codex action validation.
"""
import copy
import json
from pathlib import Path
import httpx
import pytest
from balatro_agent.actions import ActionRequest
from balatro_agent.contract import Envelope
from balatro_agent.executor import Executor
from balatro_agent.policy import canonical
from balatro_agent.reader import Reader
from balatro_agent.transport import GameClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def native_start_wrappers(request):
    return getattr(request, 'param', False)


@pytest.fixture
def game(lua_reader, tmp_path, native_start_wrappers):
    lua, snapshot = lua_reader
    native = ROOT / '.artifacts/game-source'
    if not (native/'engine/event.lua').exists():
        pytest.skip('Private fixed native functions absent')
    lua.execute((native/'engine/object.lua').read_text(encoding='utf-8'))
    lua.execute((native/'engine/event.lua').read_text(encoding='utf-8'))
    src = (native/'engine/ui.lua').read_text(encoding='utf-8')
    lua.execute('UIElement={};'+src[src.index('function UIElement:click()'):src.index('function UIElement:put_focused_cursor()')])
    src = (native/'cardarea.lua').read_text(encoding='utf-8')
    lua.execute('CardArea={};'+src[src.index('function CardArea:can_highlight'):src.index('function CardArea:parse_highlighted')])
    lua.execute(src[src.index('function CardArea:remove_from_highlighted'):src.index('function CardArea:unhighlight_all')])
    src = (native/'card.lua').read_text(encoding='utf-8')
    lua.execute('Card={};'+src[src.index('function Card:click()'):src.index('function Card:save()')])
    lua.execute("""
      Game={}; setmetatable(G,{__index=Game}); G.SETTINGS.profile=2; G.CONTROLLER.HID={controller=false}
      G.TIMERS={REAL=10,TOTAL=10}; G.ARGS={}; G.ROOM.jiggle=0
      G.E_MANAGER=EventManager(); G.FUNCS={}; TEST_CALLBACKS=0
      function play_sound() end
      function attach_native_area(a)
        a.highlighted={}; a.config.type='hand'
        a.can_highlight=CardArea.can_highlight; a.add_to_highlighted=CardArea.add_to_highlighted
        a.remove_from_highlighted=CardArea.remove_from_highlighted
        a.parse_highlighted=function() end
        for _,c in ipairs(a.cards) do
          c.area=a; c.click=Card.click
          c.states.click={can=true}
          c.highlight=function(self,v) self.highlighted=v end
        end
      end
      attach_native_area(G.hand)
      TEST_REROLL=ui({button='reroll_shop',func='can_reroll'}); TEST_REROLL.click=UIElement.click
      function reroll_scene()
        G.STATE=G.STATES.SHOP; G.shop=ui_box({}, {TEST_REROLL})
        G.shop_jokers=area({card('Same public stock')},2)
        G.shop_jokers.remove_card=function(self,c) table.remove(self.cards,1); return c end
        G.shop_jokers.emplace=function(self,c) self.cards[#self.cards+1]=c end
        for _,c in ipairs(G.shop_jokers.cards) do c.remove=function() end end
        G.GAME.dollars=10; G.GAME.bankrupt_at=0
        G.GAME.current_round.free_rerolls=0; G.GAME.shop={joker_max=1}
        G.GAME.round_scores={times_rerolled={amt=0}}
        G.CONTROLLER.save_cardarea_focus=function() return false end
        G.CONTROLLER.interrupt={}; G.CONTROLLER.recall_cardarea_focus=function() end
      end
      function stop_use() end
      function inc_career_stat() end
      function ease_dollars(n)
        G.E_MANAGER:add_event(Event({func=function() G.GAME.dollars=G.GAME.dollars+n; return true end}))
      end
      function calculate_reroll_cost() end
      function create_card_for_shop()
        local c=card('Same public stock'); c.juice_up=function() end; c.remove=function() end; return c
      end
      function save_run() end
      function remove_nils(t) return t end
    """)
    src = (native/'functions/button_callbacks.lua').read_text(encoding='utf-8')
    lua.execute(src[src.index('  G.FUNCS.reroll_shop ='):src.index('G.FUNCS.cash_out =')])
    src=(native/'game.lua').read_text(encoding='utf-8')
    start=src.index('    G.E_MANAGER:add_event(Event({',src.index("{name = 'spin_amount'"))
    end=src.index('    if saveTable then',start)
    # The actual fixed perpetual background callback; no substitute implementation.
    lua.execute('Game.start_run=function(self)\n'+src[start:end]+"""
      G.E_MANAGER:add_event(Event({trigger='after',delay=3,func=function() TEST_CALLBACKS=TEST_CALLBACKS+1; return true end}))
    end
    G.ARGS.spin={amount=0,eased=0,real=0}; G.real_dt=.016; G.TIMERS.BACKGROUND=0
    """, name='@game.lua')
    if native_start_wrappers:
        smods = ROOT / '.artifacts/upstream/smods-26.829.0'
        source = (smods/'src/utils.lua').read_text(encoding='utf-8')
        start = source.index('local game_start_run = Game.start_run')
        end = source.index('G.FUNCS.SMODS_scoring_calculation_function', start)
        body = source[start:end]
        if native_start_wrappers == 'with_effect':
            body = body.replace('G.SCORE_DISPLAY_QUEUE = nil', """
              G.SCORE_DISPLAY_QUEUE = nil
              G.E_MANAGER:add_event(Event({blocking=false,blockable=false,func=function() return false end}))
            """)
        lua.execute(body, name='=[SMODS _ "src/utils.lua"]')
        source = (smods/'src/utils/run_select.lua').read_text(encoding='utf-8')
        start = source.index('local start_run = Game.start_run')
        end = source.index('function SMODS.RunSelect.Functions.get_page_key', start)
        lua.execute(source[start:end], name='=[SMODS _ "src/utils/run_select.lua"]')
        lua.execute('SMODS.refresh_score_UI_list=function() TEST_CALLBACKS=TEST_CALLBACKS+1 end')
        if native_start_wrappers == 'unknown_wrapper':
            lua.execute('local previous=Game.start_run; function Game:start_run(args) previous(self,args) end',
                        name='=Synthetic unrecognized wrapper')
    (tmp_path/'reader-profile.json').write_text('{"profile":2,"native_ui_verified":true}', encoding='utf-8')
    lua.globals().BA_READER = lua.globals().TEST_READER
    lua.globals().BA_BINDING = lua.globals().TEST_BINDING
    lua.globals().BA_EXECUTOR = lua.execute((ROOT/'mod/executor.lua').read_text(encoding='utf-8'))
    lua.execute('BA_EXECUTOR.install_hooks()')

    def call(method, parameters=None):
        lua.globals().TEST_PARAMETERS = json.dumps(parameters or {}, ensure_ascii=False)
        lua.execute('TEST_INPUT=TEST_JSON.decode(TEST_PARAMETERS)')
        if method == 'reader_snapshot':
            return json.loads(lua.eval('TEST_JSON.encode(BA_READER.snapshot())'))
        if method == 'health':
            return json.loads(lua.eval('TEST_JSON.encode(BA_READER.health())'))
        fun = 'submit' if method == 'act_submit' else 'status'
        return json.loads(lua.eval(f'TEST_JSON.encode(BA_EXECUTOR.{fun}(TEST_INPUT))'))

    def tick(seconds=1):
        lua.execute(f'G.TIMERS.REAL=G.TIMERS.REAL+{seconds}; G.TIMERS.TOTAL=G.TIMERS.TOTAL+{seconds}; G.E_MANAGER:update({seconds},true); BA_BINDING.update(BA_READER); BA_EXECUTOR.update()')
    return lua, call, tick


def request(game, action='select', parameters=None, action_id='synthetic-1'):
    _, call, _ = game
    snap = call('reader_snapshot')
    return dict(action=action, parameters=parameters if parameters is not None else {'region':'hand','positions':[0]},
                observation_id=snap['observation_id'], action_id=action_id, reason='Synthetic boundary verification',
                experience_refs=[], expected_profile={'profile':snap['profile'],'policy':'current-native-v1'}, game_session=snap['game_session'])


def test_native_selection_forced_protection_and_no_partial_mutation(game):
    lua, call, _ = game
    lua.execute('G.hand.cards[1].ability.forced_selection=true; G.hand.cards[1]:click()')
    req = request(game, parameters={'region':'hand','positions':[1]})
    before = call('reader_snapshot')
    result = call('act_submit',req)
    assert result['state']=='REJECTED' and result['reason']=='selection_restricted'
    assert call('reader_snapshot')==before
    req = request(game, parameters={'region':'hand','positions':[0,1]},action_id='synthetic-2')
    result = call('act_submit',req)
    assert result['state']=='COMPLETED' and lua.eval('#G.hand.highlighted')==2


def test_disabled_native_card_cannot_be_selected(game):
    lua,call,_=game
    lua.execute('G.hand.cards[1].states.click.can=false')
    before=call('reader_snapshot')
    result=call('act_submit',request(game))
    assert result['state']=='REJECTED' and result['reason']=='button_unavailable'
    assert call('reader_snapshot')==before and lua.eval('#G.hand.highlighted')==0


def test_fixed_loader_clears_current_mod_before_runtime_action(game):
    lua,call,_=game
    lua.execute('SMODS.current_mod=nil')
    result=call('act_submit',request(game))
    assert result['state']=='COMPLETED' and result['submitted']
    journal=Path(lua.eval('TEST_MOD_PATH'))/'executor-journal.jsonl'
    assert journal.exists() and 'result' in journal.read_text(encoding='utf-8')


@pytest.mark.parametrize('forced', ['true','false'])
def test_face_down_selection_refusal_and_journal_ignore_hidden_identity(game,forced):
    lua,call,_=game
    lua.execute("G.hand.cards[1]:click(); G.hand.cards[1].facing='back'; G.hand.cards[1].sprite_facing='back'")
    before=call('reader_snapshot')
    req=request(game,parameters={'region':'hand','positions':[]})
    lua.execute("G.hand.cards[1].base={value='SECRET_RANK',suit='SECRET_SUIT'}; G.hand.cards[1].config.center.key='SECRET_KEY'; G.hand.cards[1].ability.forced_selection="+forced)
    assert call('reader_snapshot')==before
    result=call('act_submit',req)
    assert result['state']=='REJECTED' and result['reason']=='unsupported_rule'
    assert call('reader_snapshot')==before
    journal=Path(lua.eval('SMODS.current_mod.path'))/'executor-journal.jsonl'
    assert 'SECRET' not in journal.read_text(encoding='utf-8')+canonical(result)


def test_stone_action_binding_and_feedback_ignore_hidden_rank_suit(game):
    lua,call,_=game
    lua.execute("G.hand.cards[1].ability.effect='Stone Card'; G.hand.cards[1].config.center.key='m_stone'")
    before=call('reader_snapshot'); req=request(game)
    lua.execute("G.hand.cards[1].base={value='SECRET_RANK',suit='SECRET_SUIT'}")
    assert call('reader_snapshot')==before
    result=call('act_submit',req)
    assert result['state']=='COMPLETED' and 'SECRET' not in canonical(result)


@pytest.mark.parametrize('p', [
    {'region':'hand','positions':[0,0]}, {'region':'hand','positions':[99]},
    {'region':'HIDDEN_REGION','positions':[0]}, {'region':'hand','positions':[0],'extra':'SECRET'},
    {'region':'hand','positions':[True]}, {'region':'hand','positions':[-1]},
    {'region':'hand','positions':[0,1,2,3,4,5]},
])
def test_invalid_selection_leaves_no_changes(game,p):
    _,call,_=game
    req=request(game,parameters=p)
    before=call('reader_snapshot')
    result=call('act_submit',req)
    assert result['state']=='REJECTED' and not result['submitted']
    assert call('reader_snapshot')==before and 'SECRET' not in canonical(result)


@pytest.mark.parametrize('profile', ['1','3','nil'])
def test_native_wrong_or_unknown_profile_cannot_submit(game,profile):
    lua,call,_=game
    req=request(game)
    lua.execute('G.SETTINGS.profile='+profile)
    result=call('act_submit',req)
    assert result['state']=='REJECTED' and result['reason'] in ('profile_mismatch','unknown_profile')
    assert lua.eval('#G.hand.highlighted')==0
    if profile!='nil': assert call('reader_snapshot')['public']


def test_old_observation_after_public_change_and_noop_commit(game):
    lua,call,_=game
    req=request(game,parameters={'region':'hand','positions':[]})
    first=call('act_submit',req)
    assert first['state']=='COMPLETED'
    assert first['snapshot']['observation_id']!=req['observation_id']
    assert call('act_submit',{**req,'action_id':'other'})['reason']=='stale_observation'
    req=request(game,action_id='new')
    lua.execute('G.GAME.dollars=1')
    assert call('act_submit',req)['reason']=='stale_observation'


def test_actual_native_reroll_dedup_and_same_goods_completion(game):
    lua,call,tick=game
    lua.execute('reroll_scene()')
    req=request(game,'reroll',{})
    first=call('act_submit',req)
    assert first['state']=='RUNNING' and first['callback_confirmed']
    assert call('act_submit',req)['duplicate']
    changed={**req,'reason':'Different request content'}
    assert call('act_submit',changed)['reason']=='id_conflict'
    for _ in range(20):
        if call('action_status',{'action_id':req['action_id']})['state']=='COMPLETED': break
        tick()
    result=call('action_status',{'action_id':req['action_id']})
    assert result['state']=='COMPLETED' and result['related_events_complete']
    assert lua.eval('G.GAME.dollars')==5 and lua.eval('G.GAME.round_scores.times_rerolled.amt')==1
    assert call('act_submit',req)['state']=='COMPLETED'
    tick()
    assert lua.eval('G.GAME.dollars')==5


def test_related_descendant_events_wait_without_global_queue_clear(game):
    lua,call,tick=game
    lua.execute("""
      reroll_scene()
      G.FUNCS.reroll_shop=function()
        G.E_MANAGER:add_event(Event({func=function()
          G.E_MANAGER:add_event(Event({trigger='after',delay=3,func=function() TEST_CALLBACKS=TEST_CALLBACKS+1; return true end}))
          return true
        end}))
      end
      G.E_MANAGER:add_event(Event({blocking=false,blockable=false,func=function() return false end}),'other')
    """)
    req=request(game,'reroll',{})
    assert call('act_submit',req)['state']=='RUNNING'
    tick()
    assert call('action_status',{'action_id':req['action_id']})['state']=='RUNNING'
    tick(4)
    tick(4)
    result=call('action_status',{'action_id':req['action_id']})
    assert result['state']=='COMPLETED' and lua.eval('#G.E_MANAGER.queues.other')==1


@pytest.mark.parametrize('native_start_wrappers', [False, True], indirect=True)
def test_fixed_start_perpetual_background_is_not_action_completion(game, native_start_wrappers):
    lua,call,tick=game
    lua.execute('reroll_scene(); G.FUNCS.reroll_shop=function() G:start_run() end')
    req=request(game,'reroll',{})
    assert call('act_submit',req)['state']=='RUNNING'
    assert lua.eval('TEST_CALLBACKS')==0
    # The fixed Steamodded score-UI callback follows the delayed native event.
    for _ in range(6): tick()
    result=call('action_status',{'action_id':req['action_id']})
    assert result['state']=='COMPLETED' and result['related_events_complete']
    assert lua.eval('TEST_CALLBACKS')==(2 if native_start_wrappers else 1)
    assert lua.eval('#G.E_MANAGER.queues.base')==1


def test_similar_effect_event_outside_bootstrap_remains_pending(game):
    lua,call,tick=game
    lua.execute("""
      reroll_scene()
      G.FUNCS.reroll_shop=function()
        G.E_MANAGER:add_event(Event({blocking=false,blockable=false,func=function() return false end}))
      end
    """)
    req=request(game,'reroll',{})
    assert call('act_submit',req)['state']=='RUNNING'
    tick(10)
    assert call('action_status',{'action_id':req['action_id']})['state']=='RUNNING'


@pytest.mark.parametrize('native_start_wrappers', ['with_effect', 'unknown_wrapper'], indirect=True)
def test_wrapped_start_effect_or_unknown_source_cannot_be_ignored(game):
    lua,call,tick=game
    lua.execute('reroll_scene(); G.FUNCS.reroll_shop=function() G:start_run() end')
    req=request(game,'reroll',{})
    assert call('act_submit',req)['state']=='RUNNING'
    for _ in range(4): tick(5)
    result=call('action_status',{'action_id':req['action_id']})
    assert lua.eval('TEST_CALLBACKS')==2
    assert result['state']=='RUNNING' and not result['related_events_complete']


def test_parallel_submission_rejected_at_game_boundary(game):
    lua,call,_=game
    lua.execute('reroll_scene()')
    first=request(game,'reroll',{})
    assert call('act_submit',first)['state']=='RUNNING'
    second=request(game,'reroll',{},'other')
    assert call('act_submit',second)['reason']=='action_busy'


def test_game_journal_failure_prevents_selection(game):
    lua,call,_=game
    req=request(game)
    lua.execute('io.open=function() return nil end')
    # A rejection also needs a durable record. Both profile reading and
    # journaling fail here, so report the failed journal without submitting.
    result=call('act_submit',req)
    assert result['reason']=='journal_unavailable' and result['submitted'] is False
    assert lua.eval('#G.hand.highlighted')==0


def test_game_intent_journal_failure_is_before_native_commit(game):
    lua,call,_=game
    req=request(game)
    lua.execute("local original=io.open; io.open=function(path,mode) if path:match('executor%-journal') then return nil end; return original(path,mode) end")
    result=call('act_submit',req)
    assert result['reason']=='journal_unavailable' and result['submitted'] is False
    assert lua.eval('#G.hand.highlighted')==0


def test_game_submission_journal_failure_is_unknown_not_rejected(game):
    lua,call,_=game
    req=request(game)
    lua.execute("""
      local original=io.open; local writes=0
      io.open=function(path,mode)
        if path:match('executor%-journal') then writes=writes+1; if writes>1 then return nil end end
        return original(path,mode)
      end
    """)
    result=call('act_submit',req)
    assert result['state']=='UNKNOWN' and result['submitted']
    assert lua.eval('#G.hand.highlighted')==1
    assert call('act_submit',request(game,action_id='other'))['state']=='REJECTED'
    assert call('action_status',{'action_id':req['action_id']})['state']=='UNKNOWN'


def test_rejected_ids_keep_consistent_content_and_query(game):
    _,call,_=game
    req=request(game,parameters={'region':'hand','positions':[99]})
    result=call('act_submit',req)
    assert result['state']=='REJECTED'
    assert call('act_submit',req)['duplicate']
    assert call('action_status',{'action_id':req['action_id']})['state']=='REJECTED'
    assert call('act_submit',{**req,'parameters':{'region':'hand','positions':[0]}})['reason']=='id_conflict'


@pytest.mark.parametrize('mutation', [
    'TEST_REROLL.disable_button=true', 'TEST_REROLL.under_overlay=true',
    'TEST_REROLL.states.visible=false', 'TEST_REROLL.last_clicked=9.95',
    'TEST_REROLL.config.button=nil', 'G.CONTROLLER.locks.other=true',
])
def test_native_click_gates_prevent_resource_change(game,mutation):
    lua,call,_=game
    lua.execute('reroll_scene(); '+mutation)
    req=request(game,'reroll',{})
    result=call('act_submit',req)
    assert result['state']=='REJECTED' and not result['submitted'] and lua.eval('G.GAME.dollars')==10
    assert lua.eval('#G.E_MANAGER.queues.base')==0


def test_related_event_cancellation_keeps_unknown_and_busy(game):
    lua,call,_=game
    lua.execute('reroll_scene()')
    req=request(game,'reroll',{})
    assert call('act_submit',req)['state']=='RUNNING'
    lua.execute('G.E_MANAGER:clear_queue(); BA_EXECUTOR.update()')
    result=call('action_status',{'action_id':req['action_id']})
    assert result['state']=='UNKNOWN' and result['reason']=='events_cancelled'
    assert call('act_submit',request(game,'reroll',{},'other'))['reason']=='action_busy'


@pytest.mark.parametrize('price', [0,5])
def test_fixed_native_purchase_waits_even_while_reader_ready(game,price):
    lua,call,tick=game
    src=(ROOT/'.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
    lua.execute(src[src.index('G.FUNCS.check_for_buy_space ='):src.index('  G.FUNCS.toggle_shop =')])
    lua.execute(f"""
      reroll_scene(); G.GAME.current_round.jokers_purchased=0
      G.GAME.round_scores.cards_purchased={{amt=0}}; G.jokers.cards={{}}
      G.jokers.emplace=function(self,c) self.cards[#self.cards+1]=c; c.area=self end
      TEST_PRODUCT=G.shop_jokers.cards[1]; TEST_PRODUCT.ability.set='Joker'
      TEST_PRODUCT.area=G.shop_jokers
      TEST_PRODUCT.config.center.set='Joker'; TEST_PRODUCT.cost={price}; TEST_PRODUCT.highlighted=true
      TEST_PRODUCT.is=function() return true end; TEST_PRODUCT.add_to_deck=function() end
      TEST_PRODUCT.calculate_joker=function() end
      TEST_BUY=ui({{button='buy_from_shop',func='can_buy',ref_table=TEST_PRODUCT}})
      TEST_BUY.click=UIElement.click
      TEST_PRODUCT.children.buy_button=ui_box({{}},{{TEST_BUY}})
      TEST_PRODUCT.children.buy_button.remove=function(self) self.removed=true end
    """)
    req=request(game,'buy',{'region':'shop_jokers','position':0})
    result=call('act_submit',req)
    assert result['state']=='RUNNING' and call('reader_snapshot')['public']['ready']
    assert lua.eval('#G.jokers.cards')==0
    for _ in range(20):
        if call('action_status',{'action_id':req['action_id']})['state']=='COMPLETED': break
        tick()
    result=call('action_status',{'action_id':req['action_id']})
    assert result['state']=='COMPLETED' and lua.eval('G.GAME.dollars')==10-price
    assert lua.eval('#G.jokers.cards')==1 and lua.eval('G.GAME.round_scores.cards_purchased.amt')==1


@pytest.mark.parametrize('phase', ['hand','loss','win'])
def test_play_zero_score_and_terminal_paused_lineage(game,phase):
    lua,call,tick=game
    lua.execute("""
      local node=G.buttons.UIRoot.children[1]; node.click=UIElement.click
      G.hand.cards[1]:click()
      G.FUNCS.play_cards_from_highlighted=function()
        G.STATE=G.STATES.HAND_PLAYED
        G.E_MANAGER:add_event(Event({func=function()
          G.STATE=G.STATES.DRAW_TO_HAND
          G.E_MANAGER:add_event(Event({func=function() G.STATE=G.STATES.SELECTING_HAND; return true end}))
          return true
        end}))
      end
    """)
    req=request(game,'play',{})
    result=call('act_submit',req)
    assert result['state']=='RUNNING'
    if phase=='hand':
        for _ in range(4): tick()
    else:
        lua.execute("""
          G.STATE=G.STATES.GAME_OVER; G.SETTINGS.paused=true
          G.OVERLAY_MENU=ui_box({}, {ui({id='from_game_over',button='notify_then_setup_run'}),ui({button='go_to_menu'})})
        """)
        if phase=='win':
            lua.execute("G.STATE=G.STATES.ROUND_EVAL; G.OVERLAY_MENU.UIRoot.config.id='you_win_UI'")
        lua.execute('BA_EXECUTOR.update()')
    result=call('action_status',{'action_id':req['action_id']})
    assert result['state']=='COMPLETED' and result['snapshot']['public']['resources']['chips']==0
    if phase!='hand':
        assert result['completion_signal']=='terminal_confirmation' and not result['related_events_complete']
        assert result['snapshot']['public']['outcome']==phase


def native_drag_fixture(lua,region):
    src=(ROOT/'.artifacts/game-source/cardarea.lua').read_text(encoding='utf-8')
    lua.execute(src[src.index('function CardArea:align_cards()'):src.index('function CardArea:hard_set_T(')])
    src=(ROOT/'.artifacts/game-source/engine/moveable.lua').read_text(encoding='utf-8')
    lua.execute('Moveable={};'+src[src.index('function Moveable:drag('):src.index('function Moveable:juice_up(')])
    src=(ROOT/'.artifacts/game-source/engine/node.lua').read_text(encoding='utf-8')
    lua.execute('Node={drag=function() end};'+src[src.index('function Node:stop_drag()'):src.index('function Node:hover()')])
    lua.globals().TEST_ORDER_REGION=region
    lua.execute("""
      G.CONTROLLER.cursor_position={x=0,y=0}; G.TILESCALE=1; G.TILESIZE=1
      G.HIGHLIGHT_H=0.2; G.SETTINGS.reduced_motion=true; G.ROOM.T.r=0
      function point_translate(p,t) p.x=p.x+t.x; p.y=p.y+t.y end
      function point_rotate(p,r) local x=p.x; p.x=x*math.cos(r)-p.y*math.sin(r); p.y=x*math.sin(r)+p.y*math.cos(r) end
      TEST_AREA=area({card('First'),card('Second'),card('Third')},8)
      TEST_AREA.config.type=TEST_ORDER_REGION=='hand' and 'hand' or 'joker'
      TEST_AREA.config.temp_limit=8; TEST_AREA.card_w=1; TEST_AREA.T={x=1,y=2,w=8,h=1}
      TEST_AREA.children={}; TEST_AREA.align_cards=CardArea.align_cards
      for i,c in ipairs(TEST_AREA.cards) do
        c.T={x=i,y=2,w=1,h=1}; c.states.drag={can=true,is=false}; c.container=G.ROOM
        c.ARGS={}; c.shadow_parrallax={x=0,y=0}; c.drag=Moveable.drag; c.stop_drag=Node.stop_drag
        c.config.card={order=123}; c.config.center.order=456; c.area=TEST_AREA
      end
      if TEST_ORDER_REGION=='hand' then G.hand=TEST_AREA
      elseif TEST_ORDER_REGION=='jokers' then G.jokers=TEST_AREA
      else G.consumeables=TEST_AREA end
      TEST_AREA:align_cards()
    """)


@pytest.mark.parametrize('region', ['hand','jokers','consumables'])
def test_native_drag_reorder_preserves_card_definitions(game,region):
    lua,call,_=game
    native_drag_fixture(lua,region)
    req=request(game,'reorder',{'region':region,'order':[2,0,1]})
    result=call('act_submit',req)
    assert result['state']=='COMPLETED'
    assert lua.eval('TEST_AREA.cards[1].public_name')=='Third'
    assert lua.eval('TEST_AREA.cards[2].public_name')=='First'
    assert lua.eval('TEST_AREA.cards[3].public_name')=='Second'
    assert lua.eval('TEST_AREA.cards[1].config.card.order')==123
    assert lua.eval('TEST_AREA.cards[1].config.center.order')==456


@pytest.mark.parametrize('mutation', ['TEST_AREA.cards[2].pinned=true','TEST_AREA.cards[2].states.drag.can=false'])
def test_reorder_restriction_rejects_without_partial_movement(game,mutation):
    lua,call,_=game
    native_drag_fixture(lua,'jokers'); lua.execute(mutation)
    req=request(game,'reorder',{'region':'jokers','order':[2,0,1]})
    before=call('reader_snapshot')
    assert call('act_submit',req)['state']=='REJECTED'
    assert call('reader_snapshot')==before


@pytest.mark.parametrize('mutation', [
    "G.GAME.seed='SECRET_CHANGED'; G.GAME.pseudorandom={state='SECRET_RNG'}",
    "G.deck.cards[1],G.deck.cards[2]=G.deck.cards[2],G.deck.cards[1]",
    "G.future_pack={card('SECRET_UNOPENED')}",
    "G.hand.cards[1].sort_id='SECRET_OTHER'; G.hand.cards[1].playing_card='SECRET_OTHER_ID'",
])
def test_action_binding_and_return_hidden_invariance(game,mutation):
    lua,call,_=game
    req=request(game)
    before=call('reader_snapshot')
    lua.execute(mutation)
    assert call('reader_snapshot')==before
    result=call('act_submit',req)
    assert result['state']=='COMPLETED' and 'SECRET' not in canonical(result)


def python_gateway(settings,game, handler=None):
    data=json.loads(settings.profile_file.read_text()); data['profile']=2
    settings.profile_file.write_text(json.dumps(data))
    _,call,tick=game
    requests=[]
    def process(req):
        payload=json.loads(req.content); requests.append(payload['method'])
        value=call(payload['method'],payload['params'])
        if payload['method']=='action_status':
            for _ in range(20):
                if call('action_status',payload['params'])['state']=='COMPLETED': break
                tick()
            value=call('action_status',payload['params'])
        if handler is not None:
            handler(req,payload,value)
        return httpx.Response(200,json={'jsonrpc':'2.0','id':payload['id'],'result':value})
    client=GameClient(settings.url,1,transport=httpx.MockTransport(process))
    reader=Reader(settings,client)
    # The fixture's model already received the native snapshot via request().
    reader.project_envelope(Envelope.model_validate(call('reader_snapshot')))
    return Executor(reader,wait_s=.1),requests


@pytest.mark.parametrize('profile', [1,2,3])
async def test_current_native_profile_works_without_attestation(settings,game,profile,tmp_path):
    lua,_,_=game
    lua.execute('G.SETTINGS.profile='+str(profile))
    settings.profile_file.unlink()
    (tmp_path/'reader-profile.json').write_text('{"native_ui_verified":false}',encoding='utf-8')
    exe,requests=python_gateway_without_attestation(settings,game)
    observed=await exe.reader.observe()
    assert observed['observation']['profile']==profile
    req=request(game)
    result=await exe.act(**{k:v for k,v in req.items() if k not in ('expected_profile','game_session')})
    assert result['state']=='COMPLETED' and result['execution_profile']==profile
    assert result['observation']['profile']==profile and exe.pending is None
    assert requests==['reader_snapshot','act_submit']
    assert not settings.profile_file.exists()


def python_gateway_without_attestation(settings,game):
    _,call,_=game
    requests=[]
    def process(req):
        payload=json.loads(req.content); requests.append(payload['method'])
        value=call(payload['method'],payload['params'])
        return httpx.Response(200,json={'jsonrpc':'2.0','id':payload['id'],'result':value})
    return Executor(Reader(settings,GameClient(settings.url,1,transport=httpx.MockTransport(process))),wait_s=.1),requests


async def test_fabricated_unobserved_id_cannot_submit(settings,game):
    exe,requests=python_gateway_without_attestation(settings,game)
    req=request(game)
    result=await exe.act(**{k:v for k,v in req.items() if k not in ('expected_profile','game_session')})
    assert result['state']=='REJECTED' and result['reason']=='stale_observation'
    assert requests==[] and exe.pending is None


def test_legacy_integer_profile_transport_is_rejected_before_commit(game):
    lua,call,_=game
    req={**request(game),'expected_profile':2}
    result=call('act_submit',req)
    assert result['state']=='REJECTED' and result['reason']=='invalid_request'
    assert result['submitted'] is False and lua.eval('#G.hand.highlighted')==0


def test_profile_change_during_native_events_remains_unknown(game):
    lua,call,tick=game
    lua.execute('reroll_scene(); G.SETTINGS.profile=1')
    req=request(game,'reroll',{})
    assert call('act_submit',req)['state']=='RUNNING'
    lua.execute('G.SETTINGS.profile=3')
    tick()
    result=call('action_status',{'action_id':req['action_id']})
    assert result['state']=='UNKNOWN' and result['reason']=='profile_mismatch'
    assert result['execution_profile']==1
    next_req=request(game,'reroll',{},'after-profile-change')
    assert call('act_submit',next_req)['reason']=='action_busy'



async def test_gateway_filtered_result_log_and_checkpoint(settings,game):
    exe,requests=python_gateway(settings,game)
    req=request(game)
    payload={k:v for k,v in req.items() if k not in ('expected_profile','game_session')}
    result=await exe.act(**payload)
    assert result['state']=='COMPLETED' and result['observation']['profile']==2
    assert requests==['act_submit'] and exe.pending is None
    log=exe.log.read_text(encoding='utf-8')
    assert 'HIDDEN' not in log and 'seed' not in log
    assert json.loads(exe.checkpoint.read_text())['pending'] is None


@pytest.mark.parametrize('corruption', ['unready','wrong_profile','missing_execution_profile','missing_callback','rejected_after_submit'])
async def test_gateway_inconsistent_completion_never_clears_pending(settings,game,corruption):
    def corrupt(req,payload,value):
        if payload['method']!='act_submit': return
        if corruption=='unready':
            value['snapshot']['ready']=False; value['snapshot']['public']['ready']=False
        elif corruption=='wrong_profile': value['snapshot']['profile']=1
        elif corruption=='missing_execution_profile': value.pop('execution_profile',None)
        elif corruption=='missing_callback': value['callback_confirmed']=False
        else: value['state']='REJECTED'
    exe,requests=python_gateway(settings,game,corrupt)
    req=request(game); payload={k:v for k,v in req.items() if k not in ('expected_profile','game_session')}
    result=await exe.act(**payload)
    assert result['state']=='UNKNOWN' and result['reason']=='invalid_response' and exe.pending
    assert json.loads(exe.checkpoint.read_text())['pending']['action_id']==req['action_id']
    assert requests==['act_submit']


async def test_gateway_commit_lost_response_queries_without_resubmit(settings,game):
    lua,_,_=game
    lua.execute('reroll_scene()')
    def lose(req,payload,value):
        if payload['method']=='act_submit': raise httpx.ReadTimeout('SECRET_LOST_RESPONSE',request=req)
    exe,requests=python_gateway(settings,game,lose)
    req=request(game,'reroll',{})
    payload={k:v for k,v in req.items() if k not in ('expected_profile','game_session')}
    result=await exe.act(**payload)
    assert result['state']=='UNKNOWN' and exe.pending
    assert (await exe.act(**{**payload,'action_id':'different'}))['reason']=='action_busy'
    recovered=Executor(exe.reader)
    result=await recovered.act(**payload)
    assert result['state']=='COMPLETED' and requests.count('act_submit')==1
    assert lua.eval('G.GAME.dollars')==5 and recovered.pending is None


async def test_gateway_log_failure_before_submit(settings,game,monkeypatch):
    exe,requests=python_gateway(settings,game)
    def fail(*args): raise OSError('SECRET_DISK')
    monkeypatch.setattr(exe,'_record',fail)
    req=request(game)
    result=await exe.act(**{k:v for k,v in req.items() if k not in ('expected_profile','game_session')})
    assert result['state']=='REJECTED' and not requests and 'SECRET' not in canonical(result)


async def test_gateway_delivered_log_failure_after_commit_keeps_checkpoint(settings,game,monkeypatch):
    exe,requests=python_gateway(settings,game)
    original=exe._record
    def fail_delivered(kind,value):
        if kind.startswith('delivered'): raise OSError('SECRET_AFTER')
        original(kind,value)
    monkeypatch.setattr(exe,'_record',fail_delivered)
    req=request(game); payload={k:v for k,v in req.items() if k not in ('expected_profile','game_session')}
    result=await exe.act(**payload)
    assert result['state']=='UNKNOWN' and result['submitted'] and exe.pending
    assert json.loads(exe.checkpoint.read_text())['pending']['action_id']==req['action_id']
    monkeypatch.setattr(exe,'_record',original)
    result=await exe.action_status(req['action_id'])
    assert result['state']=='COMPLETED' and exe.pending is None and requests.count('act_submit')==1


async def test_gateway_recovered_delivery_failure_restores_checkpoint(settings,game,monkeypatch):
    def lose(req,payload,value):
        if payload['method']=='act_submit': raise httpx.ReadTimeout('Lost response',request=req)
    exe,requests=python_gateway(settings,game,lose)
    req=request(game); payload={k:v for k,v in req.items() if k not in ('expected_profile','game_session')}
    assert (await exe.act(**payload))['state']=='UNKNOWN'
    recovered=Executor(exe.reader)
    original=recovered._record
    def fail_delivered(kind,value):
        if kind.startswith('delivered'): raise OSError('SECRET_DELIVERY')
        original(kind,value)
    monkeypatch.setattr(recovered,'_record',fail_delivered)
    result=await recovered.action_status(req['action_id'])
    assert result['state']=='UNKNOWN' and result['read_only'] and recovered.pending
    assert json.loads(recovered.checkpoint.read_text())['pending']['action_id']==req['action_id']
    monkeypatch.setattr(recovered,'_record',original)
    assert (await recovered.action_status(req['action_id']))['state']=='COMPLETED'
    assert recovered.pending is None and requests.count('act_submit')==1


async def test_game_restart_loss_blocks_new_actions(settings,game):
    lua,_,_=game
    lua.execute('reroll_scene()')
    def lose(req,payload,value):
        if payload['method']=='act_submit': raise httpx.ReadTimeout('SECRET',request=req)
    exe,requests=python_gateway(settings,game,lose)
    req=request(game,'reroll',{})
    payload={k:v for k,v in req.items() if k not in ('expected_profile','game_session')}
    assert (await exe.act(**payload))['state']=='UNKNOWN'
    # Isolated process-restart equivalent: a new game record/session, no real save.
    lua.execute("BA_BINDING.session='abcdef0123456789'; BA_EXECUTOR=assert(loadfile('mod/executor.lua'))()")
    result=await exe.action_status(req['action_id'])
    assert result['state']=='UNKNOWN' and result['reason']=='session_changed'
    assert exe.pending and requests.count('act_submit')==1


@pytest.mark.parametrize('change', [
    {'action':'set'}, {'parameters':{'region':'hand','positions':[0,0]}},
    {'parameters':{'region':'hand','positions':[False]}}, {'parameters':{'region':'hand','positions':[0],'hidden':'SECRET'}},
    {'observation_id':'obs-legacy'}, {'reason':''}, {'experience_refs':['']},
])
async def test_gateway_strict_requests_never_reach_game(settings,game,change):
    exe,requests=python_gateway(settings,game)
    req=request(game); payload={k:v for k,v in req.items() if k not in ('expected_profile','game_session')}
    result=await exe.act(**{**payload,**change})
    assert result['state']=='REJECTED' and not requests and 'SECRET' not in canonical(result)


@pytest.mark.parametrize('main_menu', [False,True])
@pytest.mark.parametrize('another_unlock', [False,True])
def test_native_unlock_continue_closes_only_current_overlay(game,main_menu,another_unlock):
    lua,call,tick=game
    source=(ROOT/'.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
    start=source.index('G.FUNCS.exit_overlay_menu =')
    lua.execute(source[start:source.index('G.FUNCS.test_framework',start)])
    lua.execute("""
        G.CONTROLLER.mod_cursor_context_layer=function() end
        G.save_settings=function() TEST_SETTINGS_SAVES=(TEST_SETTINGS_SAVES or 0)+1 end
        function unlock_overlay()
          local button=ui({button='continue_unlock'},{ui({text='Visible continue'})})
          button.click=UIElement.click
          local box=ui_box({}, {button})
          box.remove=function(self) self.removed=true end
          return box
        end
        G.OVERLAY_MENU=unlock_overlay(); TEST_FIRST_UNLOCK=G.OVERLAY_MENU
        G.SETTINGS.paused=true
    """)
    if main_menu:
        lua.execute('G.STAGE=G.STAGES.MAIN_MENU; G.STATE=G.STATES.MENU; G.MAIN_MENU_UI=ui_box()')
    if another_unlock:
        # A previously queued native unlock is processed by continue_unlock's
        # real E_MANAGER:update call; it is not this action's child effect.
        lua.execute("G.E_MANAGER:add_event(Event({func=function() G.OVERLAY_MENU=unlock_overlay(); G.SETTINGS.paused=true; return true end}),'unlock')")
    req=request(game,'close_menu',{})
    result=call('act_submit',req)
    assert result['submitted'] and result['callback_confirmed']
    assert lua.eval('TEST_FIRST_UNLOCK.removed') is True
    assert lua.eval('G.OVERLAY_MENU~=TEST_FIRST_UNLOCK') is True
    # The normal next frame releases the native exit_overlay_menu frame lock.
    lua.execute('G.CONTROLLER.locks.frame=nil; G.CONTROLLER.locks.frame_set=nil')
    tick(0.2)
    result=call('action_status',{'action_id':req['action_id']})
    assert result['state']=='COMPLETED' and result['related_events_complete']
    assert result['snapshot']['public']['phase']==('main_menu' if main_menu else ('menu' if another_unlock else 'hand'))
    assert lua.eval('TEST_SETTINGS_SAVES')==1
    if another_unlock:
        assert lua.eval('G.OVERLAY_MENU.removed') is None
        assert lua.eval('G.SETTINGS.paused') is True


@pytest.mark.parametrize('action', ['buy','use'])
def test_paid_booster_callback_cannot_complete_before_displayed_pack(game,action):
    lua,call,tick=game
    lua.execute("""
        G.STATE=G.STATES.SHOP; G.shop=ui_box()
        local product=card('Visible booster'); product.ability.set='Booster'; product.highlighted=true
        G.shop_booster=area({product}); product.area=G.shop_booster
        TEST_OPEN_BUTTON=ui({button='use_card',ref_table=product})
        TEST_OPEN_BUTTON.click=UIElement.click
        product.children.buy_button=ui_box({}, {TEST_OPEN_BUTTON})
        G.FUNCS.use_card=function() TEST_CALLBACKS=TEST_CALLBACKS+1 end
    """)
    if action=='buy':
        lua.execute("TEST_OPEN_BUTTON.config.func='can_open'")
    req=request(game,action,{'region':'shop_boosters','position':0})
    result=call('act_submit',req)
    assert result['state']=='RUNNING' and result['callback_confirmed']
    tick(0.2)
    assert call('action_status',{'action_id':req['action_id']})['state']=='RUNNING'
    assert lua.eval('TEST_CALLBACKS')==1
    lua.execute('G.STATE=G.STATES.SMODS_BOOSTER_OPENED; G.booster_pack=ui_box(); G.pack_cards=area(); G.GAME.pack_choices=1')
    tick(0.2)
    assert call('action_status',{'action_id':req['action_id']})['state']=='RUNNING'
    lua.execute("G.pack_cards.cards={card('Displayed pack choice')}; G.pack_cards.cards[1].area=G.pack_cards")
    tick(0.2)
    result=call('action_status',{'action_id':req['action_id']})
    assert result['state']=='COMPLETED' and result['snapshot']['public']['phase']=='pack'
