from pathlib import Path
import json

from lupa.lua51 import LuaRuntime
import pytest

from balatro_agent.contract import ADAPTER_VERSION, GAME_VERSION, POLICY_VERSION, SCHEMA_VERSION, UPSTREAM_COMMIT
from balatro_agent.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def public_envelope():
    return {"schema_version":SCHEMA_VERSION,"visibility_policy_version":POLICY_VERSION,"adapter_version":ADAPTER_VERSION,
            "upstream_commit":UPSTREAM_COMMIT,"upstream_mod_version":"1.5.1","game_version":GAME_VERSION,"profile":3,
            "phase":"hand","ready":True,"ready_reason":"ui_operable","compatibility":"supported",
            "game_session":"0123456789abcdef","observation_id":"obs-0123456789abcdef-3",
            "public":{"phase":"hand","ready":True,"ready_reason":"ui_operable","resources":{"dollars":0,"chips":0,"hands_left":4,"discards_left":3},
                      "regions":[{"name":"hand","capacity":8,"selection_limit":5,"cards":[{"position":0,"visibility":"face_up","selected":False,"name":"Ace","rank":"Ace","suit":"Spades","description":["Public description"]}]}]}}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    import balatro_agent.settings as module
    monkeypatch.setattr(module,"ROOT",tmp_path)
    evidence = tmp_path / "runs/checks/native-profile-synthetic.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("SYNTHETIC ONLY. No UI verification.",encoding="utf-8")
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"profile":3,"native_ui_verified":True,"evidence":"runs/checks/native-profile-synthetic.md"}),encoding="utf-8")
    return Settings(profile_file=profile,log_dir=tmp_path / "logs",notes_dir=tmp_path / "experience",
                    baseline_notes_dir=None,poll_interval_s=0.01)


@pytest.fixture
def lua_reader(tmp_path):
    (tmp_path / "reader-profile.json").write_text('{"profile":3,"native_ui_verified":true}',encoding="utf-8")
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().TEST_MOD_PATH=tmp_path.as_posix()+"/"
    lua.execute('SMODS={current_mod={path=TEST_MOD_PATH}}')
    lib = lua.execute((ROOT / "tests/support/json.lua").read_text(encoding="utf-8"))
    lua.globals().TEST_JSON=lib
    lua.execute('package.preload["json"]=function() return TEST_JSON end')
    lua.execute((ROOT / "tests/support/lua_fixture.lua").read_text(encoding="utf-8"))
    module = lua.execute((ROOT / "mod/reader.lua").read_text(encoding="utf-8"))
    binding = lua.execute((ROOT / "mod/binding.lua").read_text(encoding="utf-8"))
    binding.attach(module)
    lua.globals().TEST_BINDING = binding
    lua.globals().TEST_READER=module
    def snapshot():
        return json.loads(lua.eval('TEST_JSON.encode(TEST_READER.snapshot())'))
    return lua, snapshot
