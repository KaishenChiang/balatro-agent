"""Blind tooltip variables are public UI queries, never random draws."""
import pytest

from test_lua_boundary import public


def setup(lua, name='The Wheel', key='bl_wheel'):
    lua.globals().TEST_BLIND_NAME = name
    lua.globals().TEST_BLIND_KEY = key
    lua.execute("""
G.STATE=G.STATES.BLIND_SELECT
G.blind_select=ui()
G.GAME.round_resets.blind_choices={Boss=TEST_BLIND_KEY}
G.GAME.round_resets.blind_states={Boss='Select'}
G.P_BLINDS[TEST_BLIND_KEY]={name=TEST_BLIND_NAME,mult=2,dollars=5,config={unchanged=true}}
function localize(v, kind)
  if kind=='poker_hand_descriptions' then return {'Public hand description'} end
  if type(v)=='string' then return 'Public most-played hand' end
  if v.type=='raw_descriptions' then
    if TEST_BLIND_NAME=='The Wheel' then return {tostring(v.vars[1])..'/'..tostring(v.vars[2])..' face down'} end
    if TEST_BLIND_NAME=='The Ox' then return {v.vars[1]..' loses money'} end
    assert(next(v.vars)==nil)
    return {'Public static rule'}
  end
  return TEST_BLIND_NAME
end
""")


def test_wheel_uses_public_ui_vars_on_a_copy(lua_reader):
    lua, snapshot = lua_reader
    setup(lua)
    lua.execute("""
G.P_BLINDS.bl_wheel.loc_vars=function(self)
  self.config.unchanged=false
  return {vars={1,7}}
end
pseudorandom=function() error('Must not sample') end
""")
    assert public(snapshot)['blinds'][0]['description'] == ['1/7 face down']
    assert lua.eval('G.P_BLINDS.bl_wheel.config.unchanged') is True
    before = public(snapshot)
    lua.execute("G.GAME.seed='OTHER_HIDDEN_SEED'; G.GAME.pseudorandom={hidden='DIFFERENT'}")
    assert public(snapshot) == before


@pytest.mark.parametrize('name,key', [('The Ox','bl_ox'),('The Eye','bl_eye')])
def test_only_ox_receives_most_played_hand(lua_reader,name,key):
    lua,snapshot=lua_reader
    setup(lua,name,key)
    expected = 'Public most-played hand loses money' if name=='The Ox' else 'Public static rule'
    assert public(snapshot)['blinds'][0]['description'] == [expected]


@pytest.mark.parametrize('callback', [None, "error('Unconfirmed')", "return {vars='invalid'}", "return {vars={1}}"])
def test_unconfirmed_wheel_vars_do_not_become_fake_description(lua_reader,callback):
    lua,snapshot=lua_reader
    setup(lua)
    if callback:
        lua.execute('G.P_BLINDS.bl_wheel.loc_vars=function(self) '+callback+' end')
    result=public(snapshot)
    assert result['blinds'][0]['description'] == []
    assert 'tooltip_unavailable' in result['unknowns']
