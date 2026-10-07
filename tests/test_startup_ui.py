"""Cosmetic startup changes must not bypass initialization or stop the game."""
from pathlib import Path
import sys
import tomllib

import pytest
from lupa.lua51 import LuaRuntime


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from startup_display import DEFAULTS, render_source


def module(lua, options=None):
    source = (ROOT / 'mod/startup_ui.lua').read_text(encoding='utf-8')
    ui = lua.execute(render_source(source, options or DEFAULTS))
    lua.globals().STARTUP_MODULE = ui
    lua.execute("package.preload['balatro_agent.startup_ui'] = function() return STARTUP_MODULE end")
    return ui


def loading_runtime(version='26.829.0'):
    lua = LuaRuntime()
    lua.execute('''
      G = {ARGS = {bt = 5}, GAME = {dollars = 7}}
      love = {timer = {getTime = function() return 42 end},
              graphics = setmetatable({}, {__index = function() error('drawing') end})}
      ORIGINAL_CALLS = 0
      function boot_timer(label, next, progress) ORIGINAL_CALLS = ORIGINAL_CALLS + 1; LAST_LABEL = label end
    ''')
    lua.globals().SMODS = lua.table_from({'version': version})
    return lua


def test_startup_display_keeps_timing_without_drawing_or_changing_game():
    patch = tomllib.loads((ROOT / 'mod/lovely.toml').read_text(encoding='utf-8'))
    smods = tomllib.loads((ROOT / '.artifacts/upstream/smods-26.829.0/lovely/core.toml').read_text(encoding='utf-8'))
    assert patch['manifest']['priority'] > smods['manifest']['priority']
    copy = next(p['copy'] for p in patch['patches'] if 'copy' in p)
    assert copy['target'] == 'main.lua' and copy['position'] == 'append'
    lua = loading_runtime()
    ui = module(lua)
    lua.execute(copy['payload'])
    lua.execute("boot_timer('stage', 'Loading Mods', 0.95)")
    assert lua.eval('G.ARGS.bt') == 42
    assert lua.eval('G.GAME.dollars') == 7
    assert lua.eval('G.LOADING') is None
    assert ui['loading_status'] == 'hidden'
    assert lua.eval('ORIGINAL_CALLS') == 0


def test_console_module_hides_own_console_without_closing_it():
    lua = LuaRuntime()
    lua.execute('''
      jit = {os = 'Windows'}
      HIDE_CALLS = 0
      package.preload.ffi = function()
        return {cdef = function() end, load = function(name)
          if name == 'kernel32' then return {GetConsoleWindow = function() return 123 end} end
          assert(name == 'user32')
          return {IsWindowVisible = function() return 0 end, ShowWindow = function(window, command)
            assert(window == 123 and command == 0)
            HIDE_CALLS = HIDE_CALLS + 1
          end}
        end}
      end
    ''')
    ui = module(lua)
    assert lua.eval('HIDE_CALLS') == 1
    assert ui['console_status'] == 'hidden'


def test_optional_console_api_failure_does_not_abort_startup():
    lua = LuaRuntime()
    lua.execute('''
      jit = {os = 'Windows'}
      package.preload.ffi = function()
        return {cdef = function() error('console unavailable') end}
      end
    ''')
    result = module(lua)
    assert result['console_status'] == 'api_unavailable'
    assert callable(result['apply_loading'])


@pytest.mark.parametrize('version', ['26.830.0', 'unknown', None])
def test_version_drift_preserves_original_loading(version):
    lua = loading_runtime(version)
    ui = module(lua)
    ui['apply_loading']()
    lua.execute("boot_timer('original', 'stage', 0.2)")
    assert ui['loading_status'] == 'version_mismatch'
    assert lua.eval('ORIGINAL_CALLS') == 1
    assert lua.eval('LAST_LABEL') == 'original'


def test_loading_preference_preserves_original_timer_and_console_is_independent():
    lua = loading_runtime()
    ui = module(lua, {'hide_console': True, 'hide_loading': False})
    ui['apply_loading']()
    lua.execute('boot_timer()')
    assert ui['loading_status'] == 'visible_by_preference'
    assert ui['console_status'] == 'unsupported_platform'
    assert lua.eval('ORIGINAL_CALLS') == 1


def test_visible_console_preference_does_not_load_native_api_or_disable_loading():
    lua = loading_runtime()
    lua.execute("jit = {os='Windows'}; package.preload.ffi = function() error('must not load') end")
    ui = module(lua, {'hide_console': False, 'hide_loading': True})
    ui['apply_loading']()
    lua.execute('boot_timer()')
    assert ui['console_status'] == 'visible_by_preference'
    assert ui['loading_status'] == 'hidden'
    assert lua.eval('G.ARGS.bt') == 42


def test_missing_console_does_not_claim_hidden():
    lua = LuaRuntime()
    lua.execute('''
      jit = {os = 'Windows'}
      package.preload.ffi = function()
        return {cdef = function() end, load = function(name)
          if name == 'kernel32' then return {GetConsoleWindow = function() return nil end} end
          return {ShowWindow = function() error('must not hide') end}
        end}
      end
    ''')
    assert module(lua)['console_status'] == 'no_console'


def test_native_api_success_without_hidden_window_does_not_claim_hidden():
    lua = LuaRuntime()
    lua.execute('''
      jit = {os = 'Windows'}
      package.preload.ffi = function()
        return {cdef = function() end, load = function(name)
          if name == 'kernel32' then return {GetConsoleWindow = function() return 123 end} end
          return {ShowWindow = function() return 0 end, IsWindowVisible = function() return 1 end}
        end}
      end
    ''')
    assert module(lua)['console_status'] == 'hide_not_confirmed'


def test_missing_ffi_still_allows_loading_patch():
    lua = loading_runtime()
    lua.execute("jit = {os='Windows'}; package.preload.ffi = function() error('private native failure') end")
    ui = module(lua)
    ui['apply_loading']()
    assert ui['console_status'] == 'ffi_unavailable'
    assert ui['loading_status'] == 'hidden'
    assert 'private' not in str(ui['console_status'])


def test_missing_loading_context_uses_original_without_game_mutation():
    lua = loading_runtime()
    ui = module(lua)
    ui['apply_loading']()
    lua.execute("G.ARGS = nil; boot_timer('fallback')")
    assert lua.eval('ORIGINAL_CALLS') == 1
    assert lua.eval('G.GAME.dollars') == 7


def test_missing_timer_preserved_and_log_contains_only_fixed_statuses():
    lua = loading_runtime()
    lua.execute("boot_timer=nil; function sendInfoMessage(message) LOGGED=message end")
    ui = module(lua)
    ui['apply_loading']()
    assert ui['loading_status'] == 'timer_unavailable'
    assert lua.eval('boot_timer') is None
    assert lua.eval('LOGGED') == 'Startup display: console=unsupported_platform; loading=timer_unavailable'
