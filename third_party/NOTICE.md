# 来源与许可

项目原创代码、文档和经验采用MIT，全文见项目根目录`LICENSE`。第三方组件分别遵循下列原许可；本项目许可不覆盖原版Balatro或Steamodded。

许可证原文依据：[MIT/SPDX](https://spdx.org/licenses/MIT.html)。

- BalatroBot：Coder 与 Mod 清单列出的作者，发行 v1.5.2，提交 `9052d76f14723293f6c6b2cecaa791a5c4ae68f3`，MIT；完整许可保留在 `balatrobot-LICENSE.txt` 及已安装 Mod 的 `LICENSE`。仅复用 HTTP、注册、校验和错误模块，必要修改见 `mod/upstream-reader.patch`。清单版本 1.5.1 原样保留，Steamodded 依赖下限按当前实际固定版本调整。
- Lovely：ethangreen-dev/lovely-injector v0.9.0，MIT，许可见 `lovely-LICENSE.md`。使用该版本的 `version.dll`，不是后续 v0.10.0 的 `winmm.dll`。
- Steamodded：Steamodded/smods，固定 26.829.0，GPL-3.0，未修改其源码；完整 `LICENSE` 随源码归档和安装目录保留。
- 测试 JSON：rxi json.lua 0.1.2，MIT，来自固定 Steamodded 源码；完整许可在 `tests/support/json.lua` 文件头。
- Python、uv、MCP、httpx 和锁定的传递依赖：采用官方发行；各发行的许可随隔离运行环境或源码保留。完整解析依赖见 `uv.lock`，当前版本及 SHA-256 见 `runs/checks/versions-20261004.json`，旧版本清单保留于本机历史。

原版 Balatro 源码仅在 `.artifacts/game-source/` 用于本机建设核对，不属于交付源码，不公开发布。
