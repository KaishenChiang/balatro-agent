# Installation, maintenance and recovery

Use the complete project folder on Windows x64 with a legitimate Steam installation of Balatro. Run **Balatro Agent.exe** from that folder. Python, uv, locked dependencies and fixed Mod archives are bundled; do not download an EXE alone or move it out of the folder. Keep the folder in a permanent writable location.

The interface follows the Windows display language (Chinese or English fallback) and also offers `Language / 语言`. Changing this selector changes labels and both prompt paths, preserves your deck/stake selection and does not restart preparation. It does not change Balatro's language or select a game profile. The optional launcher argument `--language en` or `--language zh-CN` chooses an interface language for that launch.

Before installation or updates, close Balatro normally and resolve pending actions. The preparation worker discovers a unique Steam installation, verifies bundled hashes, freezes the installation plan, checks backups and existing Mods, builds the adapter and configures MCP. It preserves unrelated settings, Mods, profiles and saves. A conflict is reported rather than silently replaced. A partial failure retains its real receipts; this is not a cross-file atomic rollback guarantee.

When ready, use **Start in Codex**, review the prefilled prompt and send it. A successfully dispatched project-link request closes the launcher. **Copy play prompt** includes the actual project path and full rules; paste it in a local Codex chat with the MCP tools loaded. Copy and fallback paths keep the launcher open. After copying you may close it manually. Codex manages the MCP process independently. Keep the project folder.

If a chat lacks the tools, reload MCP with the client's available controls or reopen Codex. Preparation does not prove an existing chat has reloaded. The path in a prompt does not change that chat's working directory or permissions. The interface shows a short localized failure explanation; **Details** retains real worker output and paths for troubleshooting.

## Moving or updating the project

Verified installation receipts and mirrored unresolved-action records under the client configuration directory permit repairing a moved or re-downloaded project's registered path. The launcher checks ownership, installed hashes, normal game closure and idle old/new checkpoints, then backs up and updates only the managed entry. A known 11-tool registration can upgrade to the current 12 tools. Other/custom configuration conflicts stop for inspection. Missing trusted receipts cannot be bypassed by guessing an old path.

Back up and migrate `runs/local-experience/` separately. It contains personal revisions and complete branched history; the public baseline never replaces them. Preserve `runs/live/` (including `run-plans/`), checkpoints, UNKNOWN records, installation ledgers and backups during maintenance. A changed session or language does not justify deleting records, locks or saves to bypass an unresolved action. Historical and local notes may use either language; keep their original bytes.

For a stopped/unresolved action, query its original ID and observe through MCP. Never replay an uncertain action or promote UNKNOWN to a loss. `recover_lost_session` is only for a confirmed lost old session under its contract. Normal wins/losses retain the game results window; closing the game requires a separate explicit request.

The [activity viewer](activity.md) is separate from the preparation launcher. A new permitted MCP game launch requests it automatically; `Balatro Agent.exe --monitor` reopens it without installation. Closing it does not stop gameplay or discard records. The interface displays submitted rationale and plans; it cannot retrieve unsubmitted internal reasoning.

## Developer checks and source delivery

`scripts/project.py` is the maintenance entry point. Use Python 3.13 with the project environment and `uv.lock`; the fixed sources and runtime manifest are under `config/`. From the project folder:

```powershell
.venv/Scripts/python.exe scripts/project.py status
.venv/Scripts/python.exe scripts/project.py build
.venv/Scripts/python.exe scripts/project.py build-launcher
.venv/Scripts/python.exe scripts/project.py check --source-only --output runs/checks/release-check-1.3.2.json
.venv/Scripts/python.exe scripts/project.py package --check-report runs/checks/release-check-1.3.2.json --output deliverables/github-ready-1.3.2
.venv/Scripts/python.exe scripts/project.py verify-package --output runs/checks/source-validation-1.3.2.json
.venv/Scripts/python.exe scripts/project.py verify-offline --output runs/checks/offline-preparation-1.3.2.json
```

Use new report/candidate paths; do not overwrite old evidence. Source-only checks do not update the game. Independent rebuilds and offline checks operate in fresh project-local directories and block real game transport. Private native-function fixtures are excluded from public source, and corresponding public tests skip when absent.

Public source contains only selected code, documentation, fixed licensed distributions, immutable experience and selected historical evidence. Exclude personal configuration, environments, artifacts, live records, saves, seeds, keys, private game materials, TEST and backups. Verify each candidate member against its manifest before publication. Source checks, independent builds, offline preparation, client reload and real gameplay are separate evidence. Push only with explicit authorization; source publication does not automatically create a GitHub Release or tag.

[Chinese detailed maintenance reference](maintenance.md) · [English MCP setup](model-client.en.md) · [English support scope](english-support.md).
