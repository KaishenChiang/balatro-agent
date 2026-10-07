# Balatro Agent

让支持工具调用的AI通过本地MCP游玩Steam《Balatro／小丑牌》。模型负责决策；程序读取玩家可见信息、验证并执行原生动作、确认结果，并保存、读取和修订模型的经验。

```text
模型 ↔ Agent客户端 ↔ 本地STDIO MCP ↔ Mod ↔ Steam Balatro
                           ↕
                      对局记录与经验
```

当前版本为 **0.6.4**。默认红色牌组／白注、原生随机，第8底注获胜或正常失败后停止。

## 开始使用

1. 在Windows x64下载并解压源码，保留项目目录。电脑上需要合法安装的Steam版Balatro。
2. 双击 [Balatro Agent.exe](<Balatro Agent.exe>)。小窗口自动查找游戏，使用内置组件准备Python与依赖、备份并安装Mod、配置Codex；已有环境经核验后直接复用。
3. 看到“准备就绪”后，点击“打开 Codex”和“复制游玩提示”。在已登录的Codex中打开窗口提供的项目目录，粘贴并发送提示：

> 请阅读 prompts/bootstrap.md，并通过 balatro-agent MCP 自主游玩一局原生随机红色牌组／白注，优先保证通关并尽快完成。第8底注获胜或正常失败后停止，保存并读回心得，报告结果和用时。

完整下载包已内置固定版本的工具、Python、依赖和Mod，首次准备无需再下载组件。游戏本体和Codex登录由用户准备。若游戏仍在运行、找到多份安装或已有冲突，窗口显示处理提示；安装细节见[维护说明](docs/balatro-ai/maintenance.md)。

**已经连接MCP时：**

直接发送上面的两句话。[首用提示](prompts/first-use.md)可独立复制，详细操作规则由[bootstrap](prompts/bootstrap.md)和工具校验提供。

Codex若尚未加载新增工具，按实际客户端能力重载后继续。Windows官方启动命令目前不能保证自动选中目录，窗口提供“复制项目路径”；程序准备成功与Codex实际连接分别核验。[官方说明](https://learn.chatgpt.com/docs/developer-commands?surface=cli#codex-app)

没有本机工具连接的纯文字网页聊天不能直接操作游戏。其他客户端须支持本地STDIO MCP、模型工具调用和连续执行；[客户端配置](docs/balatro-ai/model-client.md)保留Cline接入示例，尚未实测。

## 验证范围

Windows／Steam／Codex具有历史实机证据，最近实装版本为0.6.1。当前0.6.4的源码检查与构建见[验证记录](evidence/README.md)；当前版本的真实游戏、真实客户端按钮启动和其他电脑完整首用仍待验证。历史4个连续正常完成局为3胜1败，恢复局另列，不能据此推导稳定胜率或模型排名。

项目保留11条[经验](experience/README.md)及全部39份修订。模型比较时须登记相同的经验起点、牌组、注级、客户端与推理设置，并保留失败和故障；详见[评测契约](docs/balatro-ai/reference.md#证据与评测)。

## 文件与说明

| 路径 | 内容 |
| --- | --- |
| src/balatro_agent/、mod/ | 唯一MCP服务与游戏适配 |
| Balatro Agent.exe、windows/、scripts/ | 无控制台的桌面入口、可审查的C#源码、自动准备与维护 |
| config/ | 固定依赖锁与可移植配置示例 |
| vendor/ | 已核验的上游原始发行包与许可索引，用于离线准备 |
| tests/ | 行为、公开信息与失败路径检查 |
| prompts/ | 首用与无历史上下文游玩提示 |
| experience/ | 完整经验及修订 |
| evidence/ | 精选历史记录压缩包与当前源码检查 |
| third_party/、LICENSE | 第三方归属与许可 |

[AGENTS](AGENTS.md)规定执行边界，[PROJECT](PROJECT.md)列当前验证状态，[技术参考](docs/balatro-ai/reference.md)说明工具契约，[维护说明](docs/balatro-ai/maintenance.md)说明安装、更新和恢复。模型不能读取文件时，直接粘贴对应提示全文。

## 许可与发布内容

自有代码、文档与经验采用[MIT](LICENSE)，第三方许可见[NOTICE](third_party/NOTICE.md)。

提交源码与上述目录；不要上传本机的.venv/、.tools/、.artifacts/、runs/、deliverables/、个人配置、存档或密钥。[.gitignore](.gitignore)已排除这些内容。维护命令可生成独立的github-ready目录与源码候选ZIP；发布前按[源码交付](docs/balatro-ai/maintenance.md#源码交付)核验。
