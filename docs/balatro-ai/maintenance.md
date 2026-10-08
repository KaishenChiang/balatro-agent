# 安装、维护与恢复

项目只有一个STDIO服务；游戏观察和操作通过MCP，维护脚本不替模型作策略决策。工具契约见[技术参考](reference.md)，验证范围见[PROJECT](../../PROJECT.md)。

## 首次安装

Windows x64用户双击根目录[Balatro Agent.exe](<../../Balatro Agent.exe>)。窗口自动检查Steam安装元数据，无需预装Python或uv；使用vendor内的固定发行归档，在项目内准备Python3.13.11和隔离依赖，构建Mod、冻结安装方案、核验备份并追加Codex配置。成功后提供“在 Codex 中开始”和“复制游玩提示”。项目目录须长期保留。

用户可选择15种原版牌组和8个固定注级、最高已解锁注级或爬塔模式，默认红色牌组／白注单局。解锁情况由模型在游戏内通过当前MCP公开候选核验；目录中的选项不证明已解锁。最高注级尝试一局，爬塔从该牌组最高已解锁注级开始，正常失败重试当前等级、胜利后核验并升一级直至金注通关，单局／最高模式不自动重试。

“在Codex中开始”通过官方项目链接传入实际目录、当前选择与目标提示，只预填并等待用户发送；复制入口附带路径、选择与完整bootstrap规则，可直接在已加载MCP的本地Codex聊天发送。未注册协议或打开失败时使用复制入口，底部仍保留项目路径供排障。提示中的路径不改变已有聊天的工作目录或文件权限，准备收据不证明客户端已经加载MCP。[官方项目链接](https://learn.chatgpt.com/docs/reference/commands#chats)

EXE是唯一桌面入口，C#源码和构建收据在windows/；重复的CMD启动和安装包装已移除。vendor包含公开的上游原始归档，先核对整包和各成员SHA-256，再通过本地Python镜像与wheel目录离线准备，不需要复制现成venv。运行依赖和构建依赖的版本、URL、哈希及许可见[运行锁](../../config/runtime.lock.json)；Mod与uv见[组件锁](../../config/dependencies.lock.json)。完整包无需联网下载组件。

窗口底部“详情”显示本次日志。维护副本缺少内置归档时才使用下载或旧缓存；下载显示字节量和速度。uv下载每次连接与读操作上限20秒、至多重试一次；低于1 KB/s持续30秒或单次总计10分钟会停止。已有部分文件复制后续传，原文件保留，必须核对Range和最终完整SHA256；服务器不支持Range时保存前缀并重新下载。默认读取系统代理，显式HTTPS_PROXY优先，不修改系统网络设置。Python和Mod下载仍分别遵循uv及公开源校验；不把进度或网络成功当成安装完成。

游戏未安装时在下载依赖前提示；需要安装或更新时游戏须正常关闭。已有完整的项目安装按账本与构建哈希核验，直接复用；有源码更新时只更新已记录的项目Mod文件。同名冲突、个人修改、部分安装或未决动作保留并报告，不强制覆盖。

重新下载到新目录时，自动准备可接续Codex当前登记的同一项目安装。它核验旧目录的安装账本、固定文件和备份，检查新旧目录均无未决动作且游戏已正常关闭，先备份账本与配置再生成新目录记录；需要时沿用冻结的Mod更新流程。配置只迁移command／cwd两个路径，其他工具、模型、额外环境和个人设置保留。旧目录与检查点保留为历史，不复制动作状态来绕过UNKNOWN。无法证明来源、文件有改动、旧目录丢失或TOML路径写法无法安全迁移时仍停止，不把这些情况误报为网络超时。

由Codex执行或自定路径时，在源码根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Install -Automatic
```

需要先审查安装方案时，保留PowerShell两步模式：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Apply
```

执行策略只作用于该进程，不改系统PATH或注册全局Python。实际安装须匹配冻结方案，游戏已正常关闭且无未决动作；拒绝覆盖已有Mod、注入器和同名MCP配置，保留其他设置及存档。方案在.artifacts/portable-plan.local.json，配置候选在portable-config-candidate.local.toml，真实收据在portable-install.local.json；成功须complete=true。部分失败保留收据和备份，不整份覆盖个人配置或删文件绕过。

路径不唯一时成对提供`-SteamDir "E:/Steam" -LibraryDir "F:/SteamLibrary"`；自定位置用`-ModsDir`、`-CodexConfig`。`-DependenciesOnly`只准备依赖；完整vendor包支持冷启动`-Offline`。`-Install`与`-Apply`不能混用。下载失败保留部分文件，不关闭证书校验。

默认配置Codex，模型登录由客户端负责。其他客户端可用`-CodexConfig "config/client-install.local.toml"`生成独立辅助文件，再按[客户端配置](model-client.md#客户端配置)接入；TOML不能直接导入Cline。首用两句提示见[首用提示](../../prompts/first-use.md)，模型操作规则见[bootstrap](../../prompts/bootstrap.md)。

## 已有安装与检查

已有安装再次打开Balatro Agent即可核验复用；命令行维护入口为scripts/project.py：

```powershell
.venv/Scripts/python.exe scripts/project.py status
.venv/Scripts/python.exe scripts/project.py prepare --reuse-only
.venv/Scripts/python.exe scripts/project.py diagnose --output runs/checks/diagnosis.json
.venv/Scripts/python.exe scripts/project.py build
.venv/Scripts/python.exe scripts/project.py build-launcher
.venv/Scripts/python.exe scripts/project.py verify-offline --output runs/checks/offline-preparation.json
.venv/Scripts/python.exe scripts/project.py update-mod --output runs/checks/mod-update-plan.json
.venv/Scripts/python.exe scripts/project.py check --output runs/checks/release-check.json
```

- status／diagnose只读核验安装、构建、进程、未决动作和日志元数据，不读局面或存档、不自动启闭游戏。
- prepare由自动入口调用，首次安装或更新仍冻结方案、核验备份并保留真实收据；--reuse-only只核验已有环境、枚举工具并保存本地准备结果，不下载安装。准备结果在.artifacts/onboarding.local.json；不代表Codex已加载工具或游戏已连接。
- build只重建项目内Mod，不安装。首次初始化已准备固定来源；新开发副本先运行bootstrap_sources.py。
- build-launcher仅用Windows内置.NET编译器重建自有GUI入口；既有EXE必须匹配收据，保留旧版后替换。不宣称旧编译器的输出字节可复现。源码打包只允许这一有源码与构建哈希绑定的自有EXE，其他运行程序仍排除。
- verify-offline仅复制公开交付文件，在无Python、venv和缓存的新目录以-DependenciesOnly／-Offline准备组件，核对版本、重建Mod并检查开发STDIO；不写真实游戏或客户端配置，不算其他机器完整首用通过。
- update-mod默认冻结差异；游戏正常关闭、无未决动作且已授权更新时，同一output加`--apply`。漂移拒绝，先核验备份，部分失败保留收据。
- check执行合成检查与隔离TEST开发STDIO，并冻结源码哈希；STDIO检查阻断真实游戏传输，不读取正在进行的局面。已有报告拒绝覆盖，应选择新output。默认同时核验记录中的安装，不匹配或不可读时可退出1；`--source-only`只以当前源码、固定组件和构建决定状态码，仍完整报告旧安装不匹配事实。须分别检查pytest_exit_code、development_stdio_exit_code、source_status_passed与recorded_installation_passed，不能把源码检查通过写成实装核验通过。

源码开发环境需要dev依赖；首次用户安装默认只装运行依赖：

```powershell
$env:UV_PYTHON_INSTALL_DIR = "$PWD/.tools/python"
.tools/uv/uv.exe sync --locked --python 3.13.11 --managed-python
```

部分检查提取本机合法游戏源码中的固定原生函数；私人材料不随仓库提供，缺失时这些检查跳过。公开快照、协议与其他合成检查仍执行，计数必须区分“通过”和“跳过”。

## 源码交付

```powershell
.venv/Scripts/python.exe scripts/project.py check --source-only --output runs/checks/release-check-1.0.0.json
.venv/Scripts/python.exe scripts/project.py package --check-report runs/checks/release-check-1.0.0.json --output deliverables/github-ready-1.0.0
.venv/Scripts/python.exe scripts/project.py verify-package --output runs/checks/source-validation-1.0.0.json
```

package要求本次源码检查、开发STDIO、内置固定发行包和最小Mod构建通过，源码哈希保持不变；不以历史游戏胜利作当前版本通过条件。它生成指定的deliverables/审核目录、deliverables/source/下的完整离线源码候选ZIP和逐文件清单，移除AGENTS中的本机操作者段落。自有EXE绑定可审查源码与构建收据，vendor只允许锁定的公开原始归档；不带本机运行环境、个人配置、游戏材料、存档、种子、TEST或备份。已有候选／review目录拒绝覆盖，先保全再重新构建。

示例版本须按实际pyproject版本替换，检查报告和审核目录均使用新路径。审核目录必须位于deliverables/内，不覆盖已有候选或Git历史。

verify-package在新目录用固定缓存离线初始化、重建Mod、核对全部候选文件哈希、运行公开检查和开发STDIO；公开副本缺少私人原生函数时按实际记录跳过。结果同时保留本机完整报告和源码包旁按版本命名的source-validation.json；source-manifest.json也按版本命名，旧版本附件保留。源码交付不证明当前版本真实游戏或其他电脑的完整首次安装。

GitHub提交审核目录中的内容，或按[README](../../README.md#许可与源码提交)提交允许目录。不要上传整个本机工作区；.gitignore排除本机环境和记录，但无法替代逐文件发布检查。公开发布／推送须取得用户授权，已有明确授权时按其范围执行。

## 运行保护与恢复

runs/live/中的动作检查点、历史UNKNOWN、生命周期记录，config中的本机配置，runs/checks/current-installation.json及.artifacts/backups/都是维护资料。保持原路径，不删作缓存。UNKNOWN只查询原ID和观察，按[恢复契约](reference.md#正常启动关闭与丢失会话)核验旧会话；不靠删文件、重启、更换ID或新开局绕过。

安装恢复核对备份Manifest、原路径和哈希，只恢复必要文件，保留后来无关修改；不解码存档。工作区精简的私人归档位置、移动清单和核验结果由.artifacts/archive.latest.local.json指向。按清单恢复所需成员，不整体覆盖当前进度。

## 启动显示开关

默认隐藏启动控制台和加载画面，Lovely／Steamodded初始化、计时和日志仍保留。需要排障时可分别恢复：

```powershell
.venv/Scripts/python.exe scripts/project.py configure-display --console visible
.venv/Scripts/python.exe scripts/project.py configure-display --loading visible
```

偏好只写项目内config/startup-ui.local.json，示例见[配置](../../config/startup-ui.example.json)。随后正常关窗、核验无未决动作、build并按新冻结清单update-mod／--apply，下次正常启动生效。不得删除Lovely／Steamodded来隐藏外观；显示变化不代表已证明提速。

## 记录与经验

源码经验基线及全部版本位于experience/experience/，运行时只读；游玩修订位于runs/local-experience/experience/，优先读取并保留该主题全部历史，不上传、提交或反写源码。原目录升级保留runs/local-experience/；换项目目录时先备份并逐文件核验，再单独迁移该目录，不能用复制动作检查点来绕过UNKNOWN。已修订主题不自动混入新基线，未修订主题读取新基线；迁移不得覆盖同编号不同内容的r文件，冲突需保留双方证据并复核。首次写入中断保留部分历史，原请求可恢复；不清锁、删HEAD或删旧修订来继续。

历史精选记录集中于[evidence](../../evidence/README.md)，旧建设记录保留在私人归档，不作为当前任务或授权。新对局须按[bootstrap](../../prompts/bootstrap.md)先实际读取主攻略、核对条件，相关主题按需读取并保留全部反馈；终局有新认识才写入并独立读回。更新源码文件不代表客户端已重载：health缺少notes_policy="local-over-baseline-v1"或notes_write_scope="local_only"时，先重载MCP并重新核验，再提交心得。开发STDIO使用隔离目录和阻断游戏的传输，不读取正式基线或本地经验。

维护入口还提供timings／audit，基于完整过滤交付重算计时和记录一致性。调用间隔不是纯推理时间，故障恢复与连续正常局分开。
