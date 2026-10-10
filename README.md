# Balatro Agent

English | [简体中文](README.zh-CN.md)

Let a tool-capable AI play the Steam edition of **Balatro** through a local MCP server. The model makes the decisions; the program reads player-visible information, performs native actions, confirms their results, and stores reusable experience.

**Version 1.3.2 · Windows x64 / Steam / Codex.** The default is one unseeded run with the Red Deck at White Stake. Other original decks, all eight stakes, highest unlocked stake, and a climb mode are available.

## Download and play

1. [Download the complete project ZIP](https://github.com/KaishenChiang/balatro-agent/archive/refs/heads/main.zip) and extract it to a permanent folder. Keep the whole folder: the EXE uses its scripts and bundled components. Have a legitimate Steam installation of Balatro and a signed-in Codex desktop app. Close the game normally before installation or updates.
2. Open **[Balatro Agent.exe](<Balatro Agent.exe>)** and wait for **Ready**. It finds its project folder and game installation, prepares the bundled Python and locked dependencies, backs up and installs the Mods, and configures MCP. No separate Python installation is needed. Later launches verify and reuse the installation. Verified receipts help recover moved or re-downloaded projects without replacing unrelated settings.
3. Choose **Deck** and **Stake / mode**, then click **Start in Codex**. When the installed Codex supports the project link, it opens a project chat and pre-fills the selected options and prompt. The launcher closes after successfully dispatching this request. Review and **send the prompt in Codex** to begin.
4. If the project link is unavailable, use **Copy play prompt** and paste it into a local Codex chat with the `balatro-agent` MCP tools loaded. The prompt includes the real project path, selected mode, and full rules; you do not need to select the project folder first. This fallback keeps the launcher open.

The launcher automatically uses Chinese on a Chinese Windows display language and English otherwise. Use **Language / 语言** to switch at any time; deck/stake choices and preparation state are retained. Both handoff paths use your selected language. This does not change Balatro's language: the same MCP reads native localized text and acts through native controls in either Chinese or English. See [English support](docs/balatro-ai/english-support.md). If Codex cannot see the tools after setup, reload MCP using the client's available controls or reopen Codex before sending the prompt. “Ready” confirms preparation, not that an existing chat has loaded the service. A path in a prompt does not change an existing chat's working directory or file permissions. A browser-only chat cannot directly control the local game.

Codex starts and manages MCP independently, so gameplay continues after the launcher closes. You can also close the launcher manually after copying the prompt; keep the project folder. The full download bundles the fixed tools, Python, dependencies, and Mods for offline preparation. Steam, the game, and client sign-in remain prerequisites. Advanced setup and recovery are covered in the [maintenance guide](docs/balatro-ai/maintenance.en.md).

## Live play activity

A new permitted MCP `launch_game` request opens an independent bilingual activity window. Its concise timeline uses **HH:mm:ss** and shows stage changes, short submitted decisions, plan updates, executed actions, and experience saves. Card inventories, tool names, internal IDs and repeated polls stay out of the timeline. Unconfirmed results remain clearly labelled; current execution appears above the timeline. You may close the window without interrupting gameplay and reopen it with `Balatro Agent.exe --monitor`. Identical launch queries do not reopen it. The selected language also controls deck/stake names and the model's short bilingual summaries. Older free text without a matching summary uses a localized operation and a clear unavailable-summary notice; its original stays in the records. Complete records stay local. The window displays submitted rationale and plans; it cannot read unsubmitted internal reasoning. See [how it works and its measured overhead](docs/balatro-ai/activity.md). The [public changes hint](docs/balatro-ai/public-changes.md) and full observations remain available to the model.

## Decks and stakes

The launcher offers all **15 original decks**. A selection requests a deck; the model checks its unlock status through the current profile's visible game menus. Locked or unconfirmed choices are reported and stopped without changing the requested deck or stake.

| Stake / mode | Behavior |
| --- | --- |
| White, Red, Green, Black, Blue, Purple, Orange, Gold | One run at the selected stake |
| Highest stake | One run at the highest visibly verified unlocked stake for that deck |
| Climb mode | Start at that deck's highest unlocked stake; retry normal losses, advance one stake after a verified win, and stop after beating Gold or when asked to stop |

Climb mode reports and reviews each run before continuing. Connection errors and uncertain (`UNKNOWN`) actions follow recovery rules and are not treated as normal losses. A new-run request can replace an unfinished old run through native menus. Once the requested run starts, the agent does not restart it to test outcomes or saves.

## Results and local experience

Each completed run returns a brief report: **actual deck / stake · win or loss · ante / round · elapsed time · experience update status**. Time includes model decisions and execution waits. An update is reported only after writing and reading it back; no new finding can mean no update.

After a single run or a completed climb, the game stays on the results screen with its window open. Closing the game requires a separate explicit request. An authorized climb continues through native menus after each report.

The source includes a [general guide and 11 short topics](experience/README.md), with all **61 revisions** preserved. New experience is written only to `runs/local-experience/` and takes precedence over the read-only baseline. Local revisions are not published automatically. Explicitly requested, reviewed updates can be incorporated into the shared baseline; the [experience index](experience/README.md) records the 2026-10-09/10 import and its preserved source notes. Back up and migrate that folder separately when moving projects. Notes affect available context, not model parameters.

The context optimizations introduced in 1.1.0 add literal note search, a small model-authored run plan, lossless compact observations, and shorter early status polling. Full views remain available; native completion and hidden-information protections stay in place. Plans keep their revision history, reject uncertain continuity after reconnecting, and isolate storage faults from game results. Historical action queries do not rewind the current observation. The known 11-tool configuration from 1.0.x upgrades to 12 tools after installation, closed-game, and idle checks. See the [optimization details](docs/balatro-ai/optimization.md) for design and evidence. Smaller responses have been measured; whole-run speed and stable win rates have not been established.

## Verification and project layout

Historical live evidence covers Windows / Steam / Codex; the latest complete live runs used **0.6.1**. Current source checks, development MCP, rebuilds, and offline preparation are recorded separately in [PROJECT](PROJECT.md) and [validation evidence](evidence/README.md). A complete 1.3.2 live run in an English Steam game, real climb and unlock branches, actual Codex project-link behavior, and first use on another computer remain unverified. Historical results do not establish stable win rates or model rankings.

[Play rules](prompts/bootstrap.en.md) · [First-use prompt](prompts/first-use.en.md) · [Technical contract](docs/balatro-ai/reference.md) · [Client configuration](docs/balatro-ai/model-client.en.md) · [Changelog](CHANGELOG.md). Play, setup and recovery guides are available in English; the full technical reference, project history and historical experience retain their original Chinese text. The redundant CMD launchers were removed; the EXE is the desktop entry.

| Path | Contents |
| --- | --- |
| `Balatro Agent.exe`, `windows/`, `scripts/` | Desktop launcher, its source, automatic preparation and maintenance |
| `src/balatro_agent/`, `mod/` | One MCP server and game adapter |
| `config/`, `vendor/` | Dependency locks, original distributions and portable examples |
| `prompts/`, `experience/` | Play instructions and immutable experience history |
| `tests/`, `evidence/` | Behavior checks, selected historical evidence and source validation |
| `third_party/`, `LICENSE` | Third-party notices and licenses |

## License and source publication

Self-authored code, documentation, and experience use the [MIT License](LICENSE). Bundled third-party components retain their licenses in [NOTICE](third_party/NOTICE.md).

Public source excludes local environments, private artifacts, run records, personal configuration, saves, seeds, keys, tests containing private game code, and backups. See [.gitignore](.gitignore) and the [source delivery checks](docs/balatro-ai/maintenance.en.md#developer-checks-and-source-delivery). Published source is identified by the [GitHub main-branch history](https://github.com/KaishenChiang/balatro-agent/commits/main/) and the commit receipt; pushing source does not create a GitHub Release.
