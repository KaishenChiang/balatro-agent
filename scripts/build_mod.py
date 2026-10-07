"""Reproducible, auditable minimal subset of fixed BalatroBot transport."""
from pathlib import Path
import difflib
import hashlib
import json
import shutil
from startup_display import read_options, render_source

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "9052d76f14723293f6c6b2cecaa791a5c4ae68f3"
UPSTREAM = ROOT / ".artifacts/upstream" / ("balatrobot-" + COMMIT)
DEST = ROOT / ".artifacts/built-mod/balatrobot"


def main():
    display = read_options(ROOT)
    DEST.mkdir(parents=True, exist_ok=True)
    changes = []
    for name in ("LICENSE", "balatrobot.json", "src/lua/core/server.lua", "src/lua/core/dispatcher.lua", "src/lua/core/validator.lua", "src/lua/utils/errors.lua"):
        original = (UPSTREAM / name).read_text(encoding="utf-8")
        updated = original
        if name == "balatrobot.json":
            manifest = json.loads(original)
            manifest["dependencies"] = ["Steamodded (>=26.829.0)"]
            updated = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        if name.endswith("dispatcher.lua"):
            updated = updated.replace('local BB_LOGGER = assert(SMODS.load_file("src/lua/utils/logger.lua"))()', '-- Reader patch: raw request logging is not loaded.')
            start = updated.index('function BB_DISPATCHER.dispatch(request)')
            updated = updated[:start] + '''function BB_DISPATCHER.dispatch(request)
  -- Static errors only. No arbitrary forwarding, discovery or raw params logs.
  local method = request.method
  if method ~= "health" and method ~= "reader_snapshot" and method ~= "act_submit" and method ~= "action_status" then
    BB_DISPATCHER.send_error("Method not allowed", BB_ERROR_NAMES.NOT_ALLOWED)
    return
  end
  if type(request.params) ~= "table" or ((method == "health" or method == "reader_snapshot") and next(request.params) ~= nil) then
    BB_DISPATCHER.send_error("No parameters accepted", BB_ERROR_NAMES.BAD_REQUEST)
    return
  end
  local endpoint = BB_DISPATCHER.endpoints[method]
  local ok = pcall(function()
    endpoint.execute(request.params, function(result) BB_DISPATCHER.Server.send_response(result) end)
  end)
  if not ok then
    BB_DISPATCHER.send_error("Reader snapshot failed", BB_ERROR_NAMES.INTERNAL_ERROR)
  end
end
'''
        if name.endswith("server.lua"):
            begin = updated.index('  -- Load OpenRPC spec file from mod directory')
            end = updated.index('  sendDebugMessage("HTTP server listening', begin)
            updated = updated[:begin] + '  -- Reader patch: no upstream full-state/action discovery document.\n  BB_SERVER.openrpc_spec = nil\n\n' + updated[end:]
            updated = updated.replace('"Failed to encode response: " .. tostring(json_str)', '"Reader response encoding failed"')
            updated = updated.replace('BB_SERVER.current_request_id = parsed.id', 'BB_SERVER.current_request_id = type(parsed.id) == "number" and parsed.id >= 1 and parsed.id <= 1000000000 and parsed.id == math.floor(parsed.id) and parsed.id or nil')
            # Narrow identifiers prevent reflection of arbitrary strings.
            updated = updated.replace('if id_type ~= "number" and id_type ~= "string" then', 'if id_type ~= "number" or parsed.id < 1 or parsed.id > 1000000000 then')
            updated = updated.replace("Invalid Request: 'id' must be an integer or string", "Request id must be a positive bounded integer")
        target = DEST / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(updated, encoding="utf-8", newline="\n")
        if updated != original:
            changes.extend(difflib.unified_diff(original.splitlines(keepends=True), updated.splitlines(keepends=True), fromfile="upstream/"+name, tofile="reader/"+name))
    original_entry = (UPSTREAM / "balatrobot.lua").read_text(encoding="utf-8")
    updated_entry = (ROOT / "mod/balatrobot.lua").read_text(encoding="utf-8")
    changes.extend(difflib.unified_diff(original_entry.splitlines(keepends=True), updated_entry.splitlines(keepends=True), fromfile="upstream/balatrobot.lua", tofile="reader/balatrobot.lua"))
    shutil.copyfile(ROOT / "mod/balatrobot.lua", DEST / "balatrobot.lua")
    shutil.copyfile(ROOT / "mod/lovely.toml", DEST / "lovely.toml")
    (DEST / "reader").mkdir(exist_ok=True)
    for source, target in ((name,name) for name in ("reader.lua","health.lua","snapshot.lua","binding.lua","executor.lua","act_submit.lua","action_status.lua","startup_ui.lua")):
        if source == 'startup_ui.lua':
            data = render_source((ROOT / 'mod' / source).read_text(encoding='utf-8'), display)
            (DEST / 'reader' / target).write_text(data, encoding='utf-8', newline='\n')
        else:
            shutil.copyfile(ROOT / "mod" / source, DEST / "reader" / target)
    (DEST / "reader-profile.json").write_text('{"native_ui_verified": false}\n', encoding="utf-8")
    (ROOT / "mod/upstream-reader.patch").write_text(''.join(changes), encoding="utf-8")
    files = [{"path":p.relative_to(DEST).as_posix(),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(DEST.rglob('*')) if p.is_file()]
    (ROOT / "mod/build-manifest.json").write_text(json.dumps({"upstream_release":"1.5.2","upstream_commit":COMMIT,"upstream_manifest_version":"1.5.1","files":files},indent=2),encoding="utf-8")
    print(json.dumps({"built_mod":str(DEST),"files":len(files)}))


if __name__ == "__main__": main()
