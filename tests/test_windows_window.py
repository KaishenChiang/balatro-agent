"""Portable window ownership/filtering checks; no native OS input."""
import ctypes
from ctypes import wintypes as w
from types import SimpleNamespace

import pytest

from balatro_agent.windows_game import GameProcessError, ProcessIdentity, WindowsGame


def backend(rows, enum_ok=True):
    process=ProcessIdentity(7116,1234)
    b=WindowsGame(None)
    b.find=lambda:process
    b.enum_callback=lambda f:f
    def pid(hwnd,out):
        ctypes.cast(out,ctypes.POINTER(w.DWORD)).contents.value=rows[hwnd]['pid']
        return 1
    def kind(hwnd,out,size):
        value=rows[hwnd]['class']
        out.value=value
        return len(value)
    def enum(callback,_):
        for hwnd in rows:callback(hwnd,0)
        return enum_ok
    b.u=SimpleNamespace(GetWindowThreadProcessId=pid,GetClassNameW=kind,
                        IsWindowVisible=lambda h:rows[h].get('visible',True),EnumWindows=enum)
    return b,process


def test_game_window_is_selected_with_visible_lovely_console():
    b,p=backend({10:{'pid':7116,'class':'ConsoleWindowClass'},20:{'pid':7116,'class':'SDL_app'}})
    assert b._window(p)==20


def test_other_process_or_hidden_render_window_is_not_selected():
    b,p=backend({10:{'pid':123,'class':'SDL_app'},20:{'pid':7116,'class':'SDL_app'},
                 30:{'pid':7116,'class':'SDL_app','visible':False}})
    assert b._window(p)==20


@pytest.mark.parametrize('rows,enum_ok',[
    ({10:{'pid':7116,'class':'ConsoleWindowClass'}},True),
    ({10:{'pid':7116,'class':'unknown'}},True),
    ({10:{'pid':7116,'class':'SDL_app'},20:{'pid':7116,'class':'SDL_app'}},True),
    ({10:{'pid':7116,'class':'SDL_app'}},False),
])
def test_window_ambiguity_or_enumeration_failure_refuses_close(rows,enum_ok):
    b,p=backend(rows,enum_ok)
    with pytest.raises(GameProcessError,match='game_window_unverified'):
        b._window(p)
