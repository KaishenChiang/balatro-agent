"""Modal menus expose their own navigation, not dimmed run-HUD controls."""
from test_lua_boundary import public


def test_settings_back_does_not_compete_with_underlying_hud(lua_reader):
    lua, snapshot = lua_reader
    lua.execute('''
      G.STATE=G.STATES.SHOP; G.STATE_COMPLETE=true
      G.OVERLAY_MENU=ui_box({}, {ui({button='options'}, {ui({text='Back'})})})
      G.HUD=ui_box({}, {ui({button='options'}, {ui({text='Options'})}),
                        ui({button='run_info'}, {ui({text='Run Info'})})})
    ''')
    result = public(snapshot)
    assert result['phase'] == 'menu' and result['ready']
    assert result['ui_actions'] == [{'name': 'open_options', 'enabled': True, 'blind_slot': None,
                                     'region': None, 'position': None, 'label': ['Back']}]
    assert result['resources']['dollars'] == 0
    lua.execute("G.HUD.UIRoot.children[1].children[1].config.text='OTHER_UNDERLAY_LABEL'")
    assert public(snapshot) == result


def test_hud_options_available_again_after_modal_is_closed(lua_reader):
    lua, snapshot = lua_reader
    lua.execute('''
      G.STATE=G.STATES.SHOP; G.STATE_COMPLETE=true; G.OVERLAY_MENU=nil
      G.shop=ui_box({}, {ui({button='toggle_shop'}, {ui({text='Next Round'})})})
      G.HUD=ui_box({}, {ui({button='options'}, {ui({text='Options'})})})
    ''')
    actions = public(snapshot)['ui_actions']
    assert any(a['name'] == 'open_options' and a['enabled'] for a in actions)
    assert any(a['name'] == 'next_round' and a['enabled'] for a in actions)
