# English support

Version 1.2.0 uses one bilingual Windows launcher and one MCP server. There is no separate English executable or game installation.

| Layer | Language behavior |
| --- | --- |
| Launcher | Uses Chinese for a Chinese Windows display language; otherwise English. The `Language / 语言` selector changes it immediately. |
| Decks, stakes and modes | Localized labels share the same fixed request keys. Changing language retains the selected deck, stake and preparation state. |
| Codex handoff | Both the project link and copied prompt use the selected interface language, including the complete play rules in the copy fallback. English prompts request English reports. |
| Game observation | Names, descriptions, legal hover text and menu labels come from the game's own localization and remain in that language. Changing the launcher language does not change the game language. |
| Game actions | Bind the current observation and use native controls/callbacks and current positions. They do not click by hardcoded Chinese button names or fixed translated menu positions. |
| MCP contract | Tool names, parameter names, statuses and identifiers remain stable. Tool descriptions and owned service error explanations are English. |
| Experience | Existing baseline and local note contents retain their original language and revision history. A multilingual model can use the Chinese baseline; it is not silently translated or overwritten. |

An English installation of Balatro uses the same setup. Launch Balatro Agent, choose English if needed, select a deck and mode, and start in Codex. No profile reset or unlock modification is required. The model verifies displayed deck/stake names and unlocks before starting. An anonymous locked slot does not identify a hidden deck: report locked or unconfirmed rather than guessing.

The code audit found native control names and `localize(...)` calls in the reader/executor. Joker names, effect text, current displayed values, editions, stickers and compatibility text come from legal native tooltip UI in the game's language. Public game text changes with game language; numerical resources are read as public numbers, not extracted from translated sentences. English Joker tooltip and purchase tests cover current values, copied-tooltip isolation, native purchase completion and duplicate-action protection. Current observation IDs still bind actual displayed state, so changing game language invalidates old observations when that text changes. Completion still requires native callback/event/phase and public postcondition evidence.

The release checks distinguish English/Chinese synthetic reader and action tests, Windows Forms switching and handoff tests, independent public-package rebuilding, and cold offline preparation. These exercise localization and the existing protections; they do not establish a complete live run in an English Steam game or first use on an English Windows computer. Current source evidence is in [validation.json](../../evidence/validation.json). Historical live-game results remain separate.

[English play rules](../../prompts/bootstrap.en.md) · [Maintenance](maintenance.en.md) · [MCP configuration](model-client.en.md) · [中文使用说明](../../README.zh-CN.md).
