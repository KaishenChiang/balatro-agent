"""Synthetic native selection/setup boundaries. These are not live acceptance."""
import copy
import json

import pytest
from pydantic import ValidationError

from balatro_agent.actions import ActionRequest
from balatro_agent.contract import Envelope
from test_executor import ROOT, game, native_start_wrappers, request


def hand_scene(game):
    lua, _, _ = game
    source = (ROOT / '.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
    lua.execute('G.C={UI={BACKGROUND_INACTIVE={}},BLUE={},RED={}}; TEST_HAND_CALLS=0')
    for start, end in [('  G.FUNCS.can_play =', '  G.FUNCS.can_start_run ='),
                       ('  G.FUNCS.can_discard =', '  G.FUNCS.can_use_consumeable =')]:
        lua.execute(source[source.index(start):source.index(end)], name='@functions/button_callbacks.lua')
    lua.execute('''
      G.STATE=G.STATES.SELECTING_HAND; G.STATE_COMPLETE=true; G.SETTINGS.paused=false
      G.OVERLAY_MENU=nil; G.GAME.blind.block_play=false
      TEST_PLAY=ui({func='can_play'}); TEST_PLAY.click=UIElement.click
      TEST_DISCARD=ui({func='can_discard'}); TEST_DISCARD.click=UIElement.click
      G.buttons=ui_box({}, {TEST_PLAY,TEST_DISCARD})
      G.FUNCS.can_play(TEST_PLAY); G.FUNCS.can_discard(TEST_DISCARD)
      local function finish_hand(play)
        TEST_HAND_CALLS=TEST_HAND_CALLS+1
        if play then G.STATE=G.STATES.HAND_PLAYED end
        G.E_MANAGER:add_event(Event({trigger='after',delay=2,func=function()
          G.STATE=G.STATES.DRAW_TO_HAND
          G.E_MANAGER:add_event(Event({trigger='after',delay=2,func=function()
            G.STATE=G.STATES.SELECTING_HAND; return true
          end}))
          return true
        end}))
      end
      G.FUNCS.play_cards_from_highlighted=function() finish_hand(true) end
      G.FUNCS.discard_cards_from_highlighted=function() finish_hand(false) end
    ''')


@pytest.mark.parametrize('action', ['play', 'discard'])
def test_direct_positions_one_native_submission_waits_and_deduplicates(game, action):
    lua, call, tick = game
    hand_scene(game)
    req = request(game, action, {'positions': [1, 0]}, 'direct-hand')
    first = call('act_submit', req)
    assert first['state'] == 'RUNNING' and first['submitted'] is True
    assert lua.eval('TEST_HAND_CALLS') == 1
    assert lua.eval('#G.hand.highlighted') == 2
    duplicate = call('act_submit', req)
    assert duplicate['duplicate'] is True and lua.eval('TEST_HAND_CALLS') == 1
    assert call('action_status', {'action_id': 'direct-hand'})['state'] == 'RUNNING'
    for _ in range(12):
        tick()
    done = call('action_status', {'action_id': 'direct-hand'})
    assert done['state'] == 'COMPLETED' and done['completion_signal'] == 'callback_events'
    assert done['callback_confirmed'] and done['related_events_complete']
    changed = copy.deepcopy(req)
    changed['parameters'] = {'positions': [0]}
    assert call('act_submit', changed)['reason'] == 'id_conflict'
    assert lua.eval('TEST_HAND_CALLS') == 1


@pytest.mark.parametrize('gate', ['forced', 'stale', 'profile', 'block', 'empty_hands', 'button', 'limit', 'invalid_target'])
def test_direct_positions_preflight_has_no_partial_selection(game, gate):
    lua, call, _ = game
    hand_scene(game)
    positions = [1]
    if gate == 'forced':
        lua.execute('G.hand.cards[1].ability.forced_selection=true; G.hand.cards[1]:click()')
    elif gate == 'block':
        lua.execute('G.GAME.blind.block_play=true')
    elif gate == 'empty_hands':
        lua.execute('G.GAME.current_round.hands_left=0')
    elif gate == 'button':
        lua.execute('TEST_PLAY.disable_button=true')
    elif gate == 'limit':
        positions = [0, 1]
        lua.execute('G.hand.config.highlighted_limit=1')
    elif gate == 'invalid_target':
        positions = [0, 99]
    before = lua.eval('TEST_JSON.encode({G.hand.cards[1].highlighted,G.hand.cards[2].highlighted})')
    req = request(game, 'play', {'positions': positions}, 'direct-gated')
    if gate == 'stale':
        req['observation_id'] = 'obs-' + req['game_session'] + '-0'
    if gate == 'profile':
        lua.execute('G.SETTINGS.profile=1')
    result = call('act_submit', req)
    assert result['state'] == 'REJECTED' and result['submitted'] is False
    assert lua.eval('TEST_HAND_CALLS') == 0
    assert lua.eval('TEST_JSON.encode({G.hand.cards[1].highlighted,G.hand.cards[2].highlighted})') == before


@pytest.mark.parametrize('forced', [True, False])
def test_direct_hidden_selected_card_refusal_is_identity_independent(game, forced):
    lua, call, _ = game
    hand_scene(game)
    lua.globals().TEST_FORCED = forced
    lua.execute('''
      G.hand.cards[1]:click(); G.hand.cards[1].facing='back'; G.hand.cards[1].sprite_facing='back'
      G.hand.cards[1].ability.forced_selection=TEST_FORCED
      G.hand.cards[1].base={value='SECRET_RANK',suit='SECRET_SUIT'}
    ''')
    result = call('act_submit', request(game, 'play', {'positions': [1]}, 'direct-hidden'))
    assert result['state'] == 'REJECTED' and result['reason'] == 'unsupported_rule'
    assert lua.eval('TEST_HAND_CALLS') == 0 and lua.eval('#G.hand.highlighted') == 1
    assert 'SECRET' not in json.dumps(result)


def test_native_guard_failure_after_selection_is_unknown_and_never_replayed(game):
    lua, call, _ = game
    hand_scene(game)
    lua.execute('G.FUNCS.can_play=function(e) e.config.button=nil end')
    req = request(game, 'play', {'positions': [0]}, 'native-guard-unknown')
    result = call('act_submit', req)
    assert result['state'] == 'UNKNOWN' and result['submitted'] is True
    assert lua.eval('#G.hand.highlighted') == 1 and lua.eval('TEST_HAND_CALLS') == 0
    assert call('act_submit', req)['duplicate'] is True
    other = request(game, 'play', {'positions': [1]}, 'blocked-after-unknown')
    assert call('act_submit', other)['reason'] == 'action_busy'
    assert lua.eval('#G.hand.highlighted') == 1 and lua.eval('TEST_HAND_CALLS') == 0


@pytest.mark.parametrize('parameters', [{'positions': []}, {'positions': [True]}, {'positions': [0, 0]},
                                       {'positions': [0, 1, 2, 3, 4, 5]}, {'positions': [0], 'region': 'hand'}])
def test_direct_parameters_rejected_in_both_boundaries(game, parameters):
    _, call, _ = game
    hand_scene(game)
    req = request(game, 'play', parameters, 'direct-parameters')
    result = call('act_submit', req)
    assert result['state'] == 'REJECTED' and result['reason'] == 'invalid_parameters'
    args = {k: v for k, v in req.items() if k not in ('expected_profile', 'game_session')}
    with pytest.raises(ValidationError):
        ActionRequest.model_validate(args)


def setup_scene(game, kind='deck'):
    lua, _, _ = game
    lua.globals().TEST_KIND = kind
    lua.execute('''
      G.STAGE=G.STAGES.MAIN_MENU; G.SETTINGS.paused=true; G.HUD=nil; G.SAVED_GAME=nil
      SMODS.RunSelect={Internals={pages={'deck_choice','stake_choice'},current_page=TEST_KIND=='deck' and 1 or 2},
        Setup={choices={deck_choice='b_red',stake_choice='stake_white',enable_seed=false,challenge=false}},Pages={}}
      G.P_CENTERS={b_red={key='b_red',set='Back',unlocked=true,discovered=true},
        b_blue={key='b_blue',set='Back',unlocked=true,discovered=true},
        b_hidden={key='SECRET_LOCKED',set='Back',unlocked=false,discovered=false}}
      G.P_STAKES={stake_white={key='stake_white',order=1,applied_stakes={}},
        stake_red={key='stake_red',order=2,applied_stakes={'stake_white'}},
        stake_gold={key='stake_gold',order=8,applied_stakes={'stake_orange'}}}
      G.PROFILES={[2]={deck_usage={b_red={wins_by_key={stake_white=true}}}}}
      function Back(center)
        return {get_name=function() return center.unlocked and localize{type='name_text',set='Back',key=center.key} or 'Locked' end,
                generate_UI=function() return ui({}, {ui({text=center.unlocked and 'Public deck effect' or 'Public unlock requirement'})}) end}
      end
      G.UIDEF={stake_description=function(order) return ui({}, {ui({text='Public stake rule '..order})}) end}
      SMODS.RunSelect.Pages.deck_choice={handle_choice=function(self,c)
        SMODS.RunSelect.Setup.choices.deck_choice=c.config.center.key; TEST_SETUP_CLICKS=TEST_SETUP_CLICKS+1
      end}
      SMODS.RunSelect.Pages.stake_choice={handle_choice=function(self,key)
        SMODS.RunSelect.Setup.choices.stake_choice=key; TEST_SETUP_CLICKS=TEST_SETUP_CLICKS+1
      end}
      TEST_SETUP_CLICKS=0
      local page=TEST_KIND=='deck' and 'deck_choice' or 'stake_choice'
      local keys=TEST_KIND=='deck' and {'b_red','b_blue','b_hidden'} or {'stake_white','stake_red','stake_gold'}
      local nodes={ui({id='run_select'}),ui({button='exit_overlay_menu'})}
      TEST_SETUP_CARDS={}
      for i,key in ipairs(keys) do
        local c=card('Setup card'); c.params={run_select_selection_choice={i,page}}
        c.config.center=TEST_KIND=='deck' and G.P_CENTERS[key] or G.P_STAKES[key]
        if TEST_KIND=='stake' then c.params.stake=key; c.params.stake_chip_locked=i==3 end
        c.states.click={can=true}; c.click=Card.click; TEST_SETUP_CARDS[i]=c
        local a=area({c}); a.config.run_select=page
        local n=ui({object=a}); n.UIT=G.UIT.O; nodes[#nodes+1]=n
      end
      G.OVERLAY_MENU=ui_box({},nodes)
      SMODS.RunSelect.Internals.holding_secret={key='SECRET_HOLDING',order='SECRET_ORDER'}
    ''')
    source = (ROOT / '.artifacts/upstream/smods-26.829.0/src/utils/run_select.lua').read_text(encoding='utf-8')
    lua.execute(source[source.index('local card_click_ref = Card.click'):source.index('local card_area_align_ref =')],
                name='=[SMODS _ "src/utils/run_select.lua"]')
    lua.execute('for _,c in ipairs(TEST_SETUP_CARDS) do c.click=Card.click end')
    source = (ROOT / '.artifacts/upstream/smods-26.829.0/src/game_objects/runselectpage.lua').read_text(encoding='utf-8')
    start = source.index('is_stake_unlocked = function(stake)')
    body = source[start + len('is_stake_unlocked = '):source.index('    create_selection_card =', start)].rstrip().removesuffix(',')
    lua.execute('SMODS.RunSelect.Pages.stake_choice.is_stake_unlocked=' + body)


@pytest.mark.parametrize('kind', ['deck', 'stake'])
def test_setup_only_rendered_candidates_and_native_unlocked_click(game, kind):
    lua, call, tick = game
    setup_scene(game, kind)
    first = call('reader_snapshot')
    projected = Envelope.model_validate(first).public.setup
    assert projected.page == kind + '_choice' and len(projected.options) == 3
    assert [o.enabled for o in projected.options] == [True, True, False]
    assert 'SECRET' not in json.dumps(first)
    lua.execute("SMODS.RunSelect.Internals.holding_secret={key='SECRET_CHANGED'}")
    assert call('reader_snapshot')['observation_id'] == first['observation_id']
    locked = call('act_submit', request(game, 'select_setup_option', {'kind': kind, 'position': 2}, 'locked-setup'))
    assert locked['submitted'] is False and lua.eval('TEST_SETUP_CLICKS') == 0
    req = request(game, 'select_setup_option', {'kind': kind, 'position': 1}, 'choose-setup')
    result = call('act_submit', req)
    for _ in range(4):
        tick()
    done = call('action_status', {'action_id': 'choose-setup'})
    assert done['state'] == 'COMPLETED' and lua.eval('TEST_SETUP_CLICKS') == 1
    assert done['snapshot']['public']['setup']['options'][1]['selected'] is True
    assert call('act_submit', req)['duplicate'] is True and lua.eval('TEST_SETUP_CLICKS') == 1


@pytest.mark.parametrize('gate', ['seed', 'challenge', 'locked', 'foreign', 'unfinished', 'hidden_setup'])
def test_native_progression_start_rejects_unsafe_configuration(game, gate):
    lua, call, _ = game
    setup_scene(game, 'stake')
    lua.execute('''
      TEST_START_COUNT=0
      local b=ui({button='run_select_start_run'}); b.click=UIElement.click; b.created_on_pause=true
      G.OVERLAY_MENU.UIRoot.children[#G.OVERLAY_MENU.UIRoot.children+1]=b
      G.FUNCS.run_select_start_run=function() TEST_START_COUNT=TEST_START_COUNT+1 end
      local snapshot=BA_READER.snapshot
      BA_READER.snapshot=function(...)
        local s=snapshot(...); s.public.setup.availability='observed'
        s.public.setup.deck_name=localize{type='name_text',set='Back',key=SMODS.RunSelect.Setup.choices.deck_choice}
        s.public.setup.stake_name=localize{type='name_text',set='Stake',key=SMODS.RunSelect.Setup.choices.stake_choice}
        return s
      end
    ''')
    if gate == 'seed':
        lua.execute('SMODS.RunSelect.Setup.choices.enable_seed=true')
    elif gate == 'challenge':
        lua.execute("SMODS.RunSelect.Setup.choices.challenge='anything'")
    elif gate == 'locked':
        lua.execute("SMODS.RunSelect.Setup.choices.stake_choice='stake_gold'")
    elif gate == 'foreign':
        lua.execute("SMODS.RunSelect.Setup.choices.deck_choice='b_hidden'")
    elif gate == 'unfinished':
        lua.execute('G.STAGE=G.STAGES.RUN; G.GAME.won=false; G.SAVED_GAME={}')
    elif gate == 'hidden_setup':
        lua.execute("local snapshot=BA_READER.snapshot; BA_READER.snapshot=function(...) local s=snapshot(...); s.public.setup.deck_name=nil; return s end")
    result = call('act_submit', request(game, 'start_run', {}, 'unsafe-start'))
    assert result['state'] == 'REJECTED' and result['submitted'] is False
    assert lua.eval('TEST_START_COUNT') == 0


@pytest.mark.parametrize('page', ['deck', 'stake'])
@pytest.mark.parametrize('stage', ['MAIN_MENU', 'RUN'])
def test_rendered_stake_tower_uses_top_chip_and_ignores_holding_area(game, page, stage):
    lua, call, _ = game
    setup_scene(game, page)
    lua.globals().TEST_STAGE = stage
    lua.execute('''
      G.STAGE=G.STAGES[TEST_STAGE]; G.GAME.won=true; G.GAME.stake=1
      SMODS.RunSelect.Setup.choices.stake_choice='stake_red'
      local red,white=card('Red chip'),card('White chip')
      red.params={run_select_stake_tower={2,'stake_red'}}
      white.params={run_select_stake_tower={1,'stake_white'}}
      -- Fixed populate_stake_tower builds the holding stack white then red.
      -- Native draw_card_from removes from its end, rendering red then white.
      TEST_TOWER=area({red,white}); TEST_TOWER.config.run_select_stake_tower=true
      local tower_node=ui({object=TEST_TOWER}); tower_node.UIT=G.UIT.O
      local nodes=G.OVERLAY_MENU.UIRoot.children
      nodes[#nodes+1]=tower_node
      local hidden=card('Hidden chip'); hidden.params={run_select_stake_tower={8,'stake_gold'}}
      TEST_HOLDING=area({hidden}); TEST_HOLDING.config.run_select_stake_tower=true
      local hidden_node=ui({object=TEST_HOLDING}); hidden_node.UIT=G.UIT.O
      hidden_node.states.visible=false; nodes[#nodes+1]=hidden_node
      nodes[#nodes+1]=ui({id='deck_preview_text_1',text=localize{type='name_text',set='Back',key='b_red'}})
    ''')
    first = call('reader_snapshot')
    assert first['public']['setup']['stake_name'] == lua.eval("localize{type='name_text',set='Stake',key='stake_red'}")
    assert first['public']['setup']['deck_name'] == lua.eval("localize{type='name_text',set='Back',key='b_red'}")
    lua.execute("TEST_HOLDING.cards[1].params.run_select_stake_tower={99,'SECRET_CHANGED'}")
    assert call('reader_snapshot') == first
    lua.execute('TEST_TOWER.cards={}')
    empty = call('reader_snapshot')['public']
    assert empty['setup'].get('stake_name') is None and 'unconfirmed_field' in empty['unknowns']


@pytest.mark.parametrize('deck,stake', [('b_red', 'stake_red'), ('b_blue', 'stake_white')])
@pytest.mark.parametrize('save,allowed', [(None, True), ('won', True), ('unfinished', False),
    ('unknown', False), ('truthy', False), ('placeholder_won', False)])
def test_unlocked_native_nondefault_start_allowed(game, deck, stake, save, allowed):
    lua, call, _ = game
    setup_scene(game, 'stake')
    lua.globals().TEST_DECK, lua.globals().TEST_STAKE = deck, stake
    lua.execute('''
      SMODS.RunSelect.Setup.choices.deck_choice=TEST_DECK; SMODS.RunSelect.Setup.choices.stake_choice=TEST_STAKE
      TEST_START_COUNT=0
      local b=ui({button='run_select_start_run'}); b.click=UIElement.click; b.created_on_pause=true
      G.OVERLAY_MENU.UIRoot.children[#G.OVERLAY_MENU.UIRoot.children+1]=b
      G.FUNCS.run_select_start_run=function() TEST_START_COUNT=TEST_START_COUNT+1 end
      local snapshot=BA_READER.snapshot
      BA_READER.snapshot=function(...)
        local s=snapshot(...); s.public.setup.availability='observed'
        s.public.setup.deck_name=localize{type='name_text',set='Back',key=TEST_DECK}
        s.public.setup.stake_name=localize{type='name_text',set='Stake',key=TEST_STAKE}; return s
      end
    ''')
    if save == 'won':
        lua.execute('G.SAVED_GAME={GAME={won=true,SECRET="NOT_EXPORTED"}}')
    elif save == 'unfinished':
        lua.execute('G.SAVED_GAME={GAME={won=false}}')
    elif save == 'unknown':
        lua.execute('G.SAVED_GAME={}')
    elif save == 'truthy':
        lua.execute('G.SAVED_GAME={GAME={won=1}}')
    elif save == 'placeholder_won':
        lua.execute('G.GAME.won=true; G.SAVED_GAME={GAME={won=false}}')
    result = call('act_submit', request(game, 'start_run', {}, 'unlocked-start'))
    assert result['submitted'] is allowed and lua.eval('TEST_START_COUNT') == int(allowed)
    assert 'NOT_EXPORTED' not in json.dumps(result)
    if not allowed:
        assert result['state'] == 'REJECTED' and result['reason'] == 'wrong_phase'


@pytest.mark.parametrize('case,allowed', [('normal_loss',True),('unknown_cached_run',False),('unfinished_run',False)])
def test_climb_new_attempt_after_loss_preserves_unfinished_and_unknown_runs(game,case,allowed):
    lua,call,_=game
    setup_scene(game,'stake')
    lua.execute('''
      G.STAGE=G.STAGES.RUN; G.STATE=G.STATES.GAME_OVER; G.GAME.won=false
      TEST_START_COUNT=0
      local b=ui({button='run_select_start_run'}); b.click=UIElement.click; b.created_on_pause=true
      G.OVERLAY_MENU.UIRoot.children[#G.OVERLAY_MENU.UIRoot.children+1]=b
      G.FUNCS.run_select_start_run=function() TEST_START_COUNT=TEST_START_COUNT+1 end
      local snapshot=BA_READER.snapshot
      BA_READER.snapshot=function(...)
        local s=snapshot(...); s.public.setup.availability='observed'
        s.public.setup.deck_name=localize{type='name_text',set='Back',key='b_red'}
        s.public.setup.stake_name=localize{type='name_text',set='Stake',key='stake_white'}; return s
      end
    ''')
    if case=='unknown_cached_run':
        lua.execute('G.SAVED_GAME={GAME={}}')
    elif case=='unfinished_run':
        lua.execute('G.STATE=G.STATES.SELECTING_HAND; G.SAVED_GAME={GAME={won=false}}')
    result=call('act_submit',request(game,'start_run',{},'climb-loss-start'))
    assert result['submitted'] is allowed and lua.eval('TEST_START_COUNT')==int(allowed)
    if not allowed:
        assert result['state']=='REJECTED'


@pytest.mark.parametrize('direction,initial,expected', [('next_game_speed', 3, 4), ('previous_game_speed', 2, 0.5)])
def test_speed_uses_actual_native_cycle_and_confirmed_rendered_value(game, direction, initial, expected):
    lua, call, tick = game
    setup_scene(game)
    source = (ROOT / '.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
    start = source.index('G.FUNCS.option_cycle =')
    end = source.index('\nend', start) + len('\nend')
    lua.execute(source[start:end], name='@functions/button_callbacks.lua')
    start = source.index('G.FUNCS.change_gamespeed =')
    end = source.index('\nend', start) + len('\nend')
    lua.execute(source[start:end], name='@functions/button_callbacks.lua')
    lua.globals().TEST_INITIAL = initial
    lua.execute('''
      G.C={BLACK={},WHITE={}}; TEST_CYCLE={options={0.5,1,2,4},current_option=TEST_INITIAL,opt_callback='change_gamespeed'}
      G.SETTINGS.GAMESPEED=TEST_CYCLE.options[TEST_INITIAL]
      local box=ui_box(); box.get_UIE_by_ID=function() return nil end
      local nodes={}
      for _,dir in ipairs({'l','r'}) do
        local b=ui({button='option_cycle',ref_table=TEST_CYCLE,ref_value=dir})
        b.click=UIElement.click; b.created_on_pause=true; b.UIBox=box; b.parent={parent={}}
        nodes[#nodes+1]=b
      end
      G.OVERLAY_MENU=ui_box({},nodes)
    ''')
    before = call('reader_snapshot')['public']['preferences']
    assert before['availability'] == 'observed'
    result = call('act_submit', request(game, direction, {}, 'normal-speed'))
    for _ in range(10):
        tick()
    done = call('action_status', {'action_id': 'normal-speed'})
    assert done['state'] == 'COMPLETED'
    assert lua.eval('G.SETTINGS.GAMESPEED') == expected
    assert done['snapshot']['public']['preferences']['game_speed'] == expected
