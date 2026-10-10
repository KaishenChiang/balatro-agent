# Public changes / 本步公开变化

In 1.3.0, `health.public_changes_protocol` advertises `public-changes-v1`. Delivered observations keep their full public content, IDs and native action evidence. A small top-level `public_changes` hint describes changes since the previous successfully audited, delivered public observation. Reader and Executor share one in-memory baseline; polling snapshots, undelivered results and private game data never enter it. Restarting the MCP service starts without a baseline.

`status="compared"` includes `changed`, `unchanged` and `unknown` section names. Known numeric resources may include `resource_changes` with `before` and `after`. Names, card identities, tooltips and targets are not duplicated into the hint. A section can be both changed and unknown: some visible information changed while some applicable fields remain unknown. `unchanged` describes known public fields only, and omitted sections do not prove that anything stayed unchanged. Hidden cards, missing applicable rank/suit, debuff/forced-selection flags or region-specific prices cannot establish unchanged content.

`status="unavailable"` explains a missing baseline, run/session/profile boundary, historical receipt, pending or uncertain action, delivery gap, invalid observation or a non-actionable phase. Unknown or pending current actions clear the comparison baseline. Explicit archival queries and older observations do not advance the current plan, observation or activity target cache. A terminal observation can be compared, but cannot seed the next run. A lower Ante alone is not a new run; public native effects can lower it.

The model should check `changed` and `unknown`, then decide whether its own plan's recheck conditions apply. Full current hand cards, resources and zero-based targets always come from the latest observation. The hint neither selects a strategy nor confirms execution, and cannot authorize continuation after `UNKNOWN`. The optional activity journal records a bounded copy of this hint; the [activity window](activity.md) displays major stages and actions, omitting the detailed comparison. No extra game poll, model call or strategy search is added.

The delivery audit records the actual full/compact response before committing the baseline. Audit failure clears the hint baseline while preserving existing native-action recovery and checkpoints. Complete observations remain available in both presentation formats. Synthetic comparison and delivery checks do not establish whole-run speed or win rate.

---

1.3.0的`health.public_changes_protocol`声明`public-changes-v1`。工具交付的完整公开观察、编号和原生完成证据均保留；顶层`public_changes`简述自上一份成功记录并交付的公开观察以来的变化。Reader与Executor共享一个内存基线，中间轮询、未交付结果和私有游戏数据不进入比较；MCP重启后重新建立基线。

`status="compared"`提供`changed`、`unchanged`、`unknown`区域名；已知资源可提供`resource_changes`的前后数值。提示不重复牌名、身份、悬停文字或目标。同一项目可同时已变和未知：部分可见内容已变，仍有适用字段未知。`unchanged`只描述已知公开字段，未列项目不证明不变。背面牌、适用点数／花色缺失、弱化／强制选牌状态未知或对应区域价格缺失，都不能证明内容未变。

`status="unavailable"`解释无基线、换局／会话／档位、历史收据、未决／不确定动作、交付缺口、无效观察或非可操作阶段。当前UNKNOWN和未决动作清除比较基线；显式历史查询或较旧观察不推进当前计划、观察和窗口目标缓存。终局可比较但不作为下一局基线；原生效果可降低Ante，仅底注下降不判断换局。

模型先检查已变／未知项目，再判断自己计划的复查条件是否满足。手牌、资源和零基目标位置始终以最新完整观察为准。提示不选策略、不证明动作完成，也不授权继续UNKNOWN。同一份提示的有界摘要保存在附加日志中；[状态窗口](activity.md)正文只保留重要阶段和操作，不展示逐字段比较。不额外观察、调用模型或搜索策略。

实际full／compact响应成功写入必需交付审计后才推进基线；审计失败清除比较基线，保留原有UNKNOWN和检查点恢复。合成比较与接入检查不能证明整局提速或胜率提升。
