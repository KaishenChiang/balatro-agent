# MCP client setup

The launcher prepares the environment and the managed `balatro-agent` registration automatically. Use it first. **Start in Codex** opens a project chat when the client supports the link; the prompt still requires review and sending. The copy fallback includes the actual path and complete rules. Reload MCP or reopen the client when its tool list has not refreshed.

For manual setup, use your complete extracted project folder in both `command` and `cwd`. This is one local STDIO service, with no model API key or paid API caller in the program. Example Codex TOML (replace the example paths):

```toml
[mcp_servers.balatro-agent]
command = 'D:\Games\balatro-agent\.venv\Scripts\python.exe'
args = ['-m', 'balatro_agent.server']
cwd = 'D:\Games\balatro-agent'
enabled = true
enabled_tools = ['health', 'observe', 'wait_until_ready', 'act', 'action_status', 'read_notes', 'write_note', 'run_plan', 'calculate', 'launch_game', 'close_game', 'recover_lost_session']

[mcp_servers.balatro-agent.env]
BALATRO_AGENT_CLIENT_CONTEXT = 'codex_config'
```

Keep any independently tracked `BALATRO_AGENT_REGISTRATION_FILE` installed by the launcher; do not remove it to bypass ownership or unresolved-action checks. A manually configured service still needs verified installation/lifecycle paths. Preserve unrelated client entries and settings. Other clients may support a similar STDIO `command`/`args`/`cwd` registration, but they have not been live-validated here.

After connecting, verify all **12 tools**, call `health`, and follow the [English play rules](../../prompts/bootstrap.en.md). Tool descriptions and service error explanations are English; protocol keys remain stable. Card/deck/stake names and descriptions remain in the game's current language. Interface language and game language are independent. The user/launcher's prompt chooses report language; English prompts request English reports.

The chat model is the only strategy decision maker. Use only MCP for actual game reads/actions. No terminal gameplay, hidden state, save probing, model API caller or external strategy advice. Plans and experience are local data with complete revision history. Existing Chinese experience remains valid for multilingual models; do not overwrite history for localization.

A browser-only chat cannot directly access this local game. A path in a prompt does not grant permissions or load tools. A Ready launcher receipt validates preparation, not the tool connection of an existing chat. Development checks deliberately block real game transport and do not count as real client gameplay evidence.

[Maintenance and recovery](maintenance.en.md) · [Localization scope](english-support.md) · [Chinese client reference](model-client.md).
