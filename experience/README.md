# 通用经验基线

源码提供 **1份通用攻略、11个简短主题、54份完整版本文件**。内容由模型从既有公开反馈中提炼，未采用外部专家攻略；这是一套有条件的决策框架，不是保证胜率的固定路线。

日常先读 [通用攻略 r2](experience/EXP-GENERAL-GUIDE/r0002.md)。它覆盖累计门槛、条件计分、弃牌与出牌、经济与成长、升级改牌、Boss、跳盲及观察更新。通用不等于无条件：当前局面优先，适用条件与反例必须保留。

## 读取与本地学习

开局调用 `read_notes({note_ids:["EXP-GENERAL-GUIDE"],view:"content"})`，遇到相关机制再按编号读下表主题；未支持content时省略view。旧版本与逐手算式供追溯，默认不装入整局上下文。

经验只有被工具实际读出后才进入聊天上下文，不修改模型参数，也不由程序逐步强制注入。新聊天或上下文压缩后引用不清时重读主攻略，不机械地每步读取。

- **源码基线：** `experience/experience/`，随源码包提供。
- **用户修订：** `runs/local-experience/experience/`，按主题优先读取；首次修改在本地保留该主题的全部基线历史，再追加新修订。
- **更新原则：** 跨构筑规则修订主攻略，特定技巧精简保留在对应主题；保留来源、事实/解释、条件、反例、置信度与修订理由。不逐局堆叠流水账，没有新认识时保留原经验。
- **升级与发布：** 本地目录不上传、不提交、不反写基线，源码打包排除runs/。升级时保全本地目录；已修改主题不自动合并新基线，未修改主题跟随基线。换目录时单独迁移经验，不复制动作检查点绕过UNKNOWN。

## 按需参考

| 编号 | 当前版本 | 用途 |
| --- | --- | --- |
| EXP-GENERAL-GUIDE | [r2](experience/EXP-GENERAL-GUIDE/r0002.md) | 主攻略：通用决策框架 |
| EXP-SCORE-THRESHOLD | [r5](experience/EXP-SCORE-THRESHOLD/r0005.md) | 通用补充：缺口、现成牌与累计补分 |
| EXP-CONDITIONAL-HANDS | [r5](experience/EXP-CONDITIONAL-HANDS/r0005.md) | 通用补充：计分牌、附带牌、留手与强制条件 |
| EXP-MONEY-SCORING | [r6](experience/EXP-MONEY-SCORING/r0006.md) | 通用补充：付款后资源、预算与成长 |
| EXP-CONDITIONAL-ENGINE | [r9](experience/EXP-CONDITIONAL-ENGINE/r0009.md) | 通用补充：触发阶段、顺序与条件冲突 |
| EXP-PUBLIC-STATE-AFTER-DRAW | [r5](experience/EXP-PUBLIC-STATE-AFTER-DRAW/r0005.md) | 通用补充：观察更新、拒绝与UNKNOWN |
| EXP-FLUSH-SUPPORT | [r7](experience/EXP-FLUSH-SUPPORT/r0007.md) | 条件参考：同花投入及其失败边界 |
| EXP-REPEATED-HAND | [r5](experience/EXP-REPEATED-HAND/r0005.md) | 条件参考：同盲重复与Boss限制 |
| EXP-FIRST-CARD-ENGINE | [r3](experience/EXP-FIRST-CARD-ENGINE/r0003.md) | 条件参考：首张计分牌与逐次触发 |
| EXP-PLANET-RESERVE | [r2](experience/EXP-PLANET-RESERVE/r0002.md) | 条件参考：优惠券与星球持有 |
| EXP-SHUFFLED-JOKERS | [r2](experience/EXP-SHUFFLED-JOKERS/r0002.md) | 条件参考：翻面打乱后的未知顺序 |
| EXP-RED-STAKE-ECON | [r3](experience/EXP-RED-STAKE-ECON/r0003.md) | 条件参考：红注规则，不直接套用于白注 |

每条HEAD.json指向当前版本，旧r文件完整保留。首牌r1的错误解释已在r2撤回，旧版本只供审计。红注主题置信度low，其余medium；有限对局不能证明稳定胜率或最优策略。

## 整理与来源

2026-10-08实际通过MCP读完11个主题后整理上述基线，并逐项保存、读回；此次是经验编辑，没有新增实机对局。原有41份历史文件保留，旧经验索引已归档并核对哈希。完整工具记录与独立进程核验留在本地检查目录，不作为新游戏验收。

既有正常局、建设局与故障恢复来源继续分开。按笔记run_id/step追溯[历史记录](../evidence/README.md)，模型比较须登记相同经验起点，不能称为空经验测试。

2026-10-07红色牌组/白注局 `n5-redwhite-20261007-01` 在157步、第6底注灵媒正常失败，35799/40000；同花7级、15次使用及玻璃同花20900仍不足。该局局后修订同花r6、经济r5，并完成MCP读回与独立读盘；此次整理保留这些历史。步骤为实际action_id末尾编号。

该局北京时间19:22:57开局、21:21:38终局，跨度1小时58分41秒含用户暂停；20:25:51恢复后55分47秒。暂停开始未精确记录，不报告整局净执行时间或纯推理时间。

完整存储契约见[技术参考](../docs/balatro-ai/reference.md#经验与公开计算)，执行入口见[bootstrap](../prompts/bootstrap.md)。
