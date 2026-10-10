# Live play activity / 实时游玩状态

The independent Windows viewer opens with a permitted new `launch_game` request, including a verified game that is already running. It stays separate from the preparation launcher and Lovely's hidden console. Closing it does not stop the game, MCP or model. Identical lifecycle-ID queries do not reopen a window you closed. After the game ends or closes, the viewer retains its records for review.

The timeline uses local **HH:mm:ss**, with one short line per meaningful event: game stages and run outcomes, the model's submitted decision and brief rationale, plan updates, confirmed native actions, and experience reads/saves. A purchase/use can name the one visible target; hand inventories, raw parameters, tool names, action IDs, note IDs and protocol codes are omitted. Repeated observations within the same stage and round, successful calculation output and plan reads do not clutter the view. Ordinary execution progress appears above the timeline. Unconfirmed results, rejected actions and in-game prompts remain explicit in plain language; an intention never appears as an executed action.

The records come only from public MCP results and the model's submitted `act.reason`/`run_plan`, not from unsubmitted internal reasoning or intermediate chat prose. Native observations and audit originals keep their original language. Displayed deck/stake names use the same public bilingual catalogue as the launcher. The model submits short equivalent summaries inside existing `act.reason`, plan `objective` and `priorities[0]` strings using `[zh-CN]... [en]...` when health advertises `activity_text_protocol="bilingual-tags-v1"`. The viewer selects the requested language, including when switching historical rows. One short sentence per language counts toward existing limits (200 characters per plan item, 2000 UTF-8 bytes per content); no extra tool call or model API is involved. Plain text stays valid. Old or mislabelled text without a usable translation gets an explicit localized unavailable-summary notice alongside the known operation; narrowly recognized old setup phrases can be rendered directly. An unmapped foreign target name uses its known public category rather than a guessed translation. Full original text remains in mandatory records. Historical observations do not replace the current stage or target names. The detailed [public changes hint](public-changes.md) and arithmetic results remain in the local records and model responses, including the distinction between zero and unknown values.

The interface follows the Windows display language, with a **Language / 语言** selector. It supports following the latest records, pausing the visible view, copying the visible text and opening the log folder. Reopen without installation or game operations:

```powershell
& '.\Balatro Agent.exe' --monitor
& '.\Balatro Agent.exe' --monitor --language en
```

MCP writes small optional JSONL summaries after the required audit/delivery boundary. An independent PowerShell/Windows Forms process reads the appended records; it does not poll the game or call a model. Known files are checked every 500 ms, and new session files are discovered every 3 seconds. An unchanged file is not reopened. Text is formatted once per new visible event and cached; sorting and body updates happen only when the timeline changes or the language is switched/resumed. Non-observation tool results are not recursively copied for the optional journal.

The window keeps at most 500 visible summaries, 2,048 recent deduplication IDs, 256 action descriptions and 256 comparison keys. It retains only fields needed to display/retranslate each row, excluding card inventories. It reads at most the 20 most recently active service-session files and starts within each file's last 1 MiB; each read is capped at 128 KiB. Summary entries are capped at 16 KiB. Complete files remain under `runs/live/activity/`, and existing mandatory reader, executor and local-tool audits retain the full evidence. Disk records can grow as play continues; the viewer does not load their full history into memory.

Viewer and optional summary-writing failures do not change native results, clear checkpoints, replay actions or bypass mandatory audits. Closing the viewer frees its process resources while MCP continues recording. Development/offline smoke checks do not automatically open a desktop viewer. No extra observations, model API calls, strategy generation, saves or hidden-state reads are added.

The 1.3.1 local synthetic performance check uses 500 visible decisions and measures an idle 6-second interval after loading. The earlier viewer used about 75% of one logical CPU core; the optimized version used about 1%. The optimized window still needs approximately 130 MiB of working-set memory for PowerShell, .NET, controls and bounded records; this is a separate process, not a zero-cost feature. A 100-call synthetic journal check with eight public cards per observation took a median of about 1.4 ms and a 95th percentile of about 3.1 ms per summary. These measurements do not establish live game FPS, whole-run speed, or another machine's resource usage.

Developer replay/preview can use `scripts/activity_viewer.ps1 -EventDirectory <summary-folder> -Language en -Preview -PreviewImage <PNG>` on synthetic records. This reads only the specified activity records. Preview is not live gameplay evidence. Keep records and personal experience out of GitHub/source delivery.

---

允许的新 `launch_game` 请求会同步请求打开独立状态窗口，游戏已正常运行时也适用。它与准备启动器、Lovely 控制台分开；关闭状态窗口不会关闭游戏、MCP 或模型。相同生命周期编号的查询不会重新打开已关闭窗口。游戏结算或关窗后仍可保留记录复查。

时间只保留本地**时分秒**，每条只显示一个重点：阶段变化和胜负、模型提交的简短决策与依据、计划更新、已确认执行的操作、心得读写结果。购买或使用时可显示一个公开目标名称；不显示手牌清单、原始参数、工具名、动作编号、经验编号和协议状态码。同阶段同回合的重复读取、成功算术输出与计划重读从正文中隐藏；普通执行进度显示在窗口上方。未知结果、拒绝和游戏内提示仍用可读文字区分，请求不会显示为已执行。

内容只来自模型实际收到的公开MCP结果，以及提交的决策依据和局内计划；未提交的内部思考与聊天正文无法读取。原生观察与审计原文保留原语言；界面牌组／注级名称复用启动器的公共双语目录。health声明activity_text_protocol="bilingual-tags-v1"时，模型在原有act.reason、计划objective和priorities[0]字符串内以`[zh-CN]... [en]...`提交同义短摘要，窗口选择对应语言，切换历史行时同样生效。每种语言只写一句，标签与两种摘要计入原上限（计划每项200字符、正文2000 UTF-8字节），无需额外工具请求或模型API。普通单语文字继续有效；旧记录或错标文本缺可用译文时，用所选语言明确提示，并显示已知操作。仅已识别的旧开局句式可直接转换；无法转换的外语目标名显示已知公开类别，不猜译名。完整原文仍在必需记录中。历史观察不回退当前阶段和目标。[公开变化提示](public-changes.md)与算术结果仍完整保留在本地记录和模型返回中，零与未知值的区别保持。

默认跟随 Windows 显示语言，可在 **Language / 语言** 切换中英。支持跟随最新、暂停当前显示、复制当前记录、打开记录目录。关闭后运行上述 `--monitor` 入口可重开，不重新准备安装或操作游戏。

MCP通过必需审计／交付边界后，追加一条小型可选JSONL摘要；独立的PowerShell／Windows Forms窗口读取这些追加内容。既有文件每500毫秒检查一次，新增会话文件每3秒发现一次；文件未增长时不重新打开。新摘要只格式化一次并缓存，正文只在新增可见事件、切换语言或恢复跟随时整理更新。附加记录不再复制笔记等完整返回树。

最多保留500条可见摘要、2,048个近期去重编号、256份动作描述及256个比较键；界面只保留显示／重新翻译需要的字段，不留整副牌面树。读取最近活跃的20个会话文件，每文件从末尾1 MiB范围内开始，每次读取上限128 KiB、每条摘要上限16 KiB。完整摘要保留在 `runs/live/activity/`，原有审计保留完整证据。文件会随游玩增长，但窗口不把全部历史载入内存。

窗口或附加记录失败不改变游戏结果、不删除检查点、不重发动作，也不替代必需审计。关闭窗口会释放该进程的资源，MCP继续记录。无额外游戏观察、模型API、策略或存档访问。开发与离线检查不会自动开窗；合成预览不作为实机验收。

1.3.1本机合成测量使用500条可见决策，载入后观察6秒空闲刷新：旧窗口约占一个逻辑核心的75%，优化后约1%。窗口进程仍需要约130 MiB工作集内存，包含PowerShell、.NET、界面控件及有上限的记录。另以每次8张公开牌的100次合成观察测量摘要写入，中位约1.4毫秒、95分位约3.1毫秒。上述结果不代表真实游戏帧率、整局提速或其他电脑的开销。
