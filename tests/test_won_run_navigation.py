"""Native menu navigation for a resumed win; no live game acceptance."""
import pytest

from test_executor import ROOT, game, native_start_wrappers, request
from test_unlock_input import next_frame, unlock_scene


def won_options_scene(game, won=True):
    lua, _, _ = game
    unlock_scene(game, count=0)
    source = (ROOT/'.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
    for start, end in [('G.FUNCS.options =', 'G.FUNCS.current_hands ='),
                       ('G.FUNCS.setup_run =', 'G.FUNCS.wait_for_high_scores =')]:
        lua.execute(source[source.index(start):source.index(end)], name='@functions/button_callbacks.lua')
    lua.globals().TEST_WON = won
    lua.execute('''
      G.STAGE=G.STAGES.RUN; G.STATE=G.STATES.SHOP; G.GAME.won=TEST_WON
      G.SETTINGS.paused=false; G.OVERLAY_MENU=nil
      TEST_OPTIONS=ui({button='options'}); TEST_OPTIONS.click=UIElement.click
      G.HUD=ui_box({}, {TEST_OPTIONS}); G.shop=ui_box({}, {})
      function create_UIBox_options()
        TEST_SETUP=ui({button='setup_run',id='restart_button'})
        TEST_SETUP.click=UIElement.click; TEST_SETUP.created_on_pause=true
        TEST_SETUP.states.click={can=true}
        local box=ui_box({}, {TEST_SETUP})
        box.remove=function(self) self.removed=true end
        return box
      end
    ''')


def test_resumed_win_uses_both_native_clicks_and_waits_for_display(game):
    lua, call, _ = game
    won_options_scene(game)
    before=call('reader_snapshot')['public']
    assert any(a['name']=='open_run_setup' and a['enabled'] for a in before['ui_actions'])
    parent=call('act_submit', request(game, 'open_run_setup', {}, 'resumed-win-setup'))
    assert parent['state']=='RUNNING'
    assert lua.eval('TEST_SETUP_OPENED')==0
    lua.execute('G.OVERLAY_MENU.VT={x=0,y=40,w=5,h=5}; G.OVERLAY_MENU.T={x=0,y=40,w=5,h=5}')
    next_frame(game)
    assert lua.eval('TEST_SETUP_OPENED')==0
    assert call('action_status', {'action_id':'resumed-win-setup'})['state']=='RUNNING'
    lua.execute('G.OVERLAY_MENU.VT.y=0; G.OVERLAY_MENU.T.y=0')
    next_frame(game)
    next_frame(game)
    assert lua.eval('TEST_SETUP_OPENED')==1
    assert call('action_status', {'action_id':'resumed-win-setup'})['state']=='COMPLETED'


def test_unfinished_run_has_no_setup_shortcut_and_rejects_it(game):
    lua, call, _ = game
    won_options_scene(game, won=False)
    assert not any(a['name']=='open_run_setup' for a in call('reader_snapshot')['public']['ui_actions'])
    result=call('act_submit', request(game, 'open_run_setup', {}, 'unfinished-setup'))
    assert result['state']=='REJECTED' and result['submitted'] is False
    assert lua.eval('G.OVERLAY_MENU') is None


@pytest.mark.parametrize('gate', ['disabled', 'foreign_overlay', 'profile_changed'])
def test_setup_second_click_cannot_cross_native_gates(game, gate):
    lua, call, _ = game
    won_options_scene(game)
    result=call('act_submit', request(game, 'open_run_setup', {}, 'gated-setup'))
    assert result['state']=='RUNNING'
    if gate=='disabled':
        lua.execute('TEST_SETUP.disable_button=true')
    elif gate=='foreign_overlay':
        lua.execute('G.OVERLAY_MENU=ui_box({}, {TEST_SETUP})')
    else:
        lua.execute('G.SETTINGS.profile=1')
    next_frame(game)
    assert lua.eval('TEST_SETUP_OPENED')==0
    assert call('action_status', {'action_id':'gated-setup'})['state']!='COMPLETED'


@pytest.mark.parametrize('won,stage,allowed', [(True,'RUN',True),(False,'RUN',False),(True,'MAIN_MENU',False)])
def test_only_live_native_won_run_can_replace_its_continue_cache(game,won,stage,allowed):
    lua, call, _ = game
    won_options_scene(game,won=won)
    lua.globals().TEST_STAGE=stage
    lua.execute('''
      G.STAGE=G.STAGES[TEST_STAGE]; G.SAVED_GAME={}; G.SETTINGS.paused=true
      G.SETTINGS.current_setup='New Run'; TEST_STARTS=0
      local button=ui({button='start_setup_run'}); button.click=UIElement.click
      button.created_on_pause=true; G.OVERLAY_MENU=ui_box({}, {button})
      G.FUNCS.start_setup_run=function() TEST_STARTS=TEST_STARTS+1 end
      SMODS.RunSelect={Setup={choices={deck_choice='b_red',stake_choice='stake_white',enable_seed=false,challenge=false}}}
      G.P_CENTERS.b_red={key='b_red',set='Back',unlocked=true,discovered=true}
      G.P_STAKES.stake_white={key='stake_white',order=1}
      SMODS.RunSelect.Pages={stake_choice={is_stake_unlocked=function() return true end}}
      -- Only the isolated fixture supplies the selected visible setup labels.
      local snapshot=BA_READER.snapshot
      BA_READER.snapshot=function(...)
        local s=snapshot(...)
        s.public.setup={availability='observed',deck_name=localize{type='name_text',set='Back',key='b_red'},
                       stake_name=localize{type='name_text',set='Stake',key='stake_white'}}
        return s
      end
    ''')
    result=call('act_submit',request(game,'start_run',{},'won-cache-start'))
    assert result['submitted'] is allowed
    assert lua.eval('TEST_STARTS')==int(allowed)
    if not allowed:
        assert result['state']=='REJECTED' and result['reason']=='wrong_phase'


@pytest.mark.parametrize('won', [True, False])
def test_native_options_menu_exit_only_after_actual_win(game, won):
    lua, call, _ = game
    won_options_scene(game, won=won)
    source = (ROOT/'.artifacts/game-source/functions/button_callbacks.lua').read_text(encoding='utf-8')
    lua.execute(source[source.index('G.FUNCS.go_to_menu ='):source.index('G.FUNCS.go_to_demo_cta =')],
                name='@functions/button_callbacks.lua')
    lua.execute('''
      TEST_NATIVE_EXIT=0; G.SETTINGS.paused=true
      local button=ui({button='go_to_menu'}); button.click=UIElement.click; button.created_on_pause=true
      G.OVERLAY_MENU=ui_box({}, {button})
      G.FUNCS.wipe_on=function() end; G.FUNCS.wipe_off=function() end
      function Game:delete_run() TEST_NATIVE_EXIT=TEST_NATIVE_EXIT+1 end
      function Game:main_menu()
        G.STAGE=G.STAGES.MAIN_MENU; G.STATE=G.STATES.MENU
        G.OVERLAY_MENU=nil; G.SETTINGS.paused=false
        G.MAIN_MENU_UI=ui_box({}, {ui({button='setup_run'})}); G.HUD=nil
      end
    ''')
    result=call('act_submit',request(game,'main_menu',{},'native-won-exit'))
    if not won:
        assert result['state']=='REJECTED' and result['submitted'] is False
        assert lua.eval('TEST_NATIVE_EXIT')==0
    else:
        assert result['submitted'] is True
        for _ in range(8):
            next_frame(game)
        done=call('action_status',{'action_id':'native-won-exit'})
        assert done['state']=='COMPLETED' and lua.eval('TEST_NATIVE_EXIT')==1
        assert done['snapshot']['public']['phase']=='main_menu'
