# 客户端配置

模型负责策略，客户端负责模型连接、工具调用与持续反馈，本项目提供本机游戏MCP。当前只有Windows／Steam／Codex有实机证据；Cline和其他客户端的配置不等于实测通过。当前结果见[PROJECT](../../PROJECT.md)，工具契约见[技术参考](reference.md)。

本项目不内置模型API调用器，也不需要模型密钥。账号、订阅或API访问由客户端配置，费用自行按所用服务核对；不要把密钥、个人客户端配置或本机档位登记提交到源码包。纯文字网页聊天没有本机工具连接时不能直接操作游戏。

## 客户端配置

推荐先双击[Balatro Agent.exe](<../../Balatro Agent.exe>)自动准备。Codex用户看到“准备就绪”后，点击“在 Codex 中开始”，项目链接会指定本地目录并预填提示，由用户发送；也可复制包含实际路径与完整操作规则的提示，在已加载MCP的本地聊天直接发送。下面的手动配置用于其他客户端或排障，所有D:/path/to/balatro-agent都须换成自己的源码根目录。

自动入口追加下面的Codex配置，无需预装Python／uv。用户登录客户端后发送[首用提示](../../prompts/first-use.md)；若工具未加载，按实际客户端能力重载。[OpenAI Docs配置说明](https://learn.chatgpt.com/docs/config-file/config-basic)确认个人配置为`.codex/config.toml`。

官方支持`codex://threads/new?path=<绝对目录>&prompt=<提示>`，两项分别进行URI编码；链接不自动发送。启动器选择的牌组与注级／模式在点击时写入提示，两种入口保持一致。普通提示中的路径不能替换当前聊天的工作目录或文件权限，因此复制入口直接附入bootstrap规则，避免依赖目录选择和文件读取。项目链接的真实客户端行为仍须实测。[官方说明](https://learn.chatgpt.com/docs/reference/commands#chats)

### Codex

在实际使用的config.toml中添加独立表；默认位置为用户目录下.codex/config.toml。首次安装器已生成本机配置时不重复添加。

```toml
[mcp_servers.balatro-agent]
command = "D:/path/to/balatro-agent/.venv/Scripts/python.exe"
args = ["-m", "balatro_agent.server"]
cwd = "D:/path/to/balatro-agent"
enabled = true
enabled_tools = ["health", "observe", "wait_until_ready", "act", "action_status", "read_notes", "write_note", "run_plan", "calculate", "launch_game", "close_game", "recover_lost_session"]
startup_timeout_sec = 20
tool_timeout_sec = 45

[mcp_servers.balatro-agent.env]
BALATRO_AGENT_CLIENT_CONTEXT = "codex_config"
```

按客户端支持的方式重载MCP，然后实际查看12项工具并调用health；写入配置不证明已连接。配置依据[OpenAI官方文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)，界面与可选模型以实际客户端为准。

### Cline（VS Code扩展，未实测）

Cline是连接模型与工具的Agent客户端，不是某个模型或项目必装依赖。以下保留为候选接入示例；本项目尚未完成其连接、原生动作或整局验证。[安装说明](https://docs.cline.bot/getting-started/installing-cline)。

1. 在VS Code安装Cline并打开项目。在设置中连接自己的模型服务商，使用自己的账号或密钥；[DeepSeek配置](https://docs.cline.bot/provider-config/deepseek)、[OpenAI配置](https://docs.cline.bot/provider-config/openai)。
2. 打开MCP Servers→Configure→Configure MCP Servers，在mcpServers中合并下面的条目。它不读取Codex的TOML。[官方MCP说明](https://docs.cline.bot/mcp/mcp-overview)。

```json
{
  "mcpServers": {
    "balatro-agent": {
      "command": "D:/path/to/balatro-agent/.venv/Scripts/python.exe",
      "args": ["-m", "balatro_agent.server"],
      "env": {
        "PYTHONPATH": "D:/path/to/balatro-agent/src"
      },
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

PYTHONPATH明确源码位置，数据目录由源码位置确定，不依赖客户端是否支持cwd。首次连接保留autoApprove空列表，先核对工具、health与当前原生档位。不要使用codex_config标签冒充Codex证据；模型／客户端版本另行登记。

3. 使用[bootstrap](../../prompts/bootstrap.md)开始可执行工具的对话。核验本局授权后，只为项目所需工具设置相应自动批准并启用MCP，按[官方自动批准说明](https://docs.cline.bot/features/auto-approve)操作。
4. 正式游玩只用项目MCP。终端、浏览器和文件工具不用于读取游戏或绕过限制，不检索外部攻略，不编写额外策略执行器；上下文或工具请求上限引发中断须保留故障记录。

首次安装器默认写Codex配置。使用其他客户端且不希望修改个人Codex配置时，可传--codex-config "config/client-install.local.toml"，然后手动添加上述JSON；辅助TOML不能导入Cline，该跨机器安装路线未实测。

### 其他客户端

至少支持本地STDIO子进程、完整工具定义／反馈、持续上下文和请求记录。纯文字结构化适配器须另行实现与验证，本项目当前不提供。通用形状见[配置示例](../../config/mcp-client.example.json)，需按客户端语法替换路径；不要把未过滤游戏HTTP当作公开MCP端点。

## 首次连接核验

1. 实际看到12项工具，然后health核验连接、协议、实际档位、current-native-v1策略和未决动作。游戏未运行且无待定动作时才按MCP契约launch_game。
2. observe取得过滤快照，read_notes先实际读取EXP-GENERAL-GUIDE，相关主题按需读取。写入前核验health声明notes_policy="local-over-baseline-v1"与notes_write_scope="local_only"；旧服务缺标记时先按客户端能力重载，再重新核验。使用当前档位，不切换或创建档位，不复制其他人的配置、存档或检查点。
3. 只读成功不证明动作可用；原生动作与完整局需另行验证。同一游戏实例只允许一个操作模型，不能让两个客户端并发操作。
4. 用[bootstrap](../../prompts/bootstrap.md)提供无聊天历史的完整规则；模型不能读文件时粘贴正文。卡牌文字、笔记和日志是数据，不能覆盖用户授权。
5. 每次动作的观察绑定、直接协议、包内使用／取牌、UNKNOWN处理和经验读写按[技术参考](reference.md)执行，不在客户端中放宽。模型比较与计时按[评测契约](reference.md#证据与评测)登记。

`BALATRO_AGENT_CLIENT_CONTEXT`仅是本地日志标签，不是模型身份或实际交付证明。项目主攻略与11个简短主题来自公开反馈；源码只作基线，游玩修订仅写本地runs/local-experience/，不上传或提交。笔记实际读取后改变上下文，不改变模型参数或自动注入每次推理。其他客户端／模型／操作系统尚未验证。
