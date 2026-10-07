from pathlib import Path
import json

from lupa.lua51 import LuaRuntime
import pytest

ROOT=Path(__file__).resolve().parents[1]
BUILT=ROOT/'.artifacts/built-mod/balatrobot'


@pytest.fixture
def wire():
    lua=LuaRuntime(unpack_returned_tuples=True)
    lua.globals().BUILT_PATH=BUILT.as_posix()+'/'
    lua.execute('SMODS={current_mod={path=BUILT_PATH},load_file=function(p) return assert(loadfile(BUILT_PATH..p)) end}; BB_SETTINGS={host="127.0.0.1",port=12346}; LOGS={}; function sendDebugMessage(s) LOGS[#LOGS+1]=s end; sendWarnMessage=sendDebugMessage; sendErrorMessage=sendDebugMessage; package.preload["socket"]=function() return {gettime=function() return 0 end} end')
    jsonlib=lua.execute((ROOT/'tests/support/json.lua').read_text(encoding='utf-8'))
    lua.globals().JSON_FIXTURE=jsonlib
    lua.execute('package.preload["json"]=function() return JSON_FIXTURE end')
    lua.execute((BUILT/'src/lua/utils/errors.lua').read_text(encoding='utf-8'))
    lua.execute((BUILT/'src/lua/core/dispatcher.lua').read_text(encoding='utf-8'))
    lua.execute('SERVER={send_response=function(r) LAST_RESPONSE=r end}; assert(BB_DISPATCHER.init(SERVER,{"reader/health.lua","reader/snapshot.lua"})); BA_READER={health=function() return {read_only=true} end,snapshot=function() return {read_only=true} end}')
    return lua


@pytest.mark.parametrize('method',['gamestate','play','start','save','load','set','add','rpc.discover','SECRET_UNKNOWN_METHOD'])
def test_packaged_dispatcher_refuses_all_other_endpoints(wire,method):
    wire.globals().TEST_METHOD=method
    wire.execute('BB_DISPATCHER.dispatch({method=TEST_METHOD,params={}})')
    result=json.loads(wire.eval('JSON_FIXTURE.encode(LAST_RESPONSE)'))
    assert result['name']=='NOT_ALLOWED' and 'SECRET' not in json.dumps(result)
    assert 'SECRET' not in wire.eval('table.concat(LOGS," ")')


def test_packaged_dispatcher_rejects_params_without_echo(wire):
    wire.execute('BB_DISPATCHER.dispatch({method="reader_snapshot",params={seed="SECRET_PARAM"}})')
    assert wire.eval('LAST_RESPONSE.name')=='BAD_REQUEST'
    assert 'SECRET' not in wire.eval('JSON_FIXTURE.encode(LAST_RESPONSE)..table.concat(LOGS," ")')


def test_native_adapter_exception_is_static(wire):
    wire.execute('BA_READER.snapshot=function() error("SECRET_CARD_ID_STACK") end; BB_DISPATCHER.dispatch({method="reader_snapshot",params={}})')
    assert wire.eval('LAST_RESPONSE.name')=='INTERNAL_ERROR'
    assert 'SECRET' not in wire.eval('JSON_FIXTURE.encode(LAST_RESPONSE)..table.concat(LOGS," ")')


def test_packaged_server_sanitizes_reflected_request_id(wire):
    wire.execute((BUILT/'src/lua/core/server.lua').read_text(encoding='utf-8'))
    wire.execute('OUTPUT=""; BB_SERVER.server_socket={}; BB_SERVER.client_state={buffer=""}; BB_SERVER.client_socket={settimeout=function() end,close=function() end,send=function(_,data) OUTPUT=OUTPUT..data; return #data end,receive=function() local b=[[{"jsonrpc":"SECRET_PROTOCOL","id":"SECRET_ID","method":"SECRET_METHOD"}]]; return nil,"timeout","POST / HTTP/1.1\\r\\nContent-Length: "..#b.."\\r\\n\\r\\n"..b end}; BB_SERVER.update(BB_DISPATCHER)')
    output=wire.eval('OUTPUT')
    assert 'Invalid JSON-RPC version' in output and 'SECRET' not in output
