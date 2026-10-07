# AI 游玩经验

由模型根据自己实际收到的公开观察与反馈形成，不采用外部专家攻略。当前 **11条正式经验、39份版本文件**。每条分开记录来源、事实、解释、条件、反例、置信度与修订理由；笔记不是保证胜率的固定策略。

| 编号 | 当前版本 | 内容 |
| --- | --- | --- |
| EXP-SCORE-THRESHOLD | [r4](experience/EXP-SCORE-THRESHOLD/r0004.md) | 公开门槛、现成牌型与累计补分 |
| EXP-CONDITIONAL-HANDS | [r4](experience/EXP-CONDITIONAL-HANDS/r0004.md) | 条件Joker、Boss与非计分牌选择 |
| EXP-FLUSH-SUPPORT | [r5](experience/EXP-FLUSH-SUPPORT/r0005.md) | 同花支持条件及不同新局的路线边界 |
| EXP-MONEY-SCORING | [r4](experience/EXP-MONEY-SCORING/r0004.md) | 花费、利息与实际筹码成长 |
| EXP-CONDITIONAL-ENGINE | [r8](experience/EXP-CONDITIONAL-ENGINE/r0008.md) | 触发阶段、组合条件与黑板／钩子的反例 |
| EXP-PUBLIC-STATE-AFTER-DRAW | [r4](experience/EXP-PUBLIC-STATE-AFTER-DRAW/r0004.md) | 翻牌、位置变化、过期观察与UNKNOWN |
| EXP-REPEATED-HAND | [r4](experience/EXP-REPEATED-HAND/r0004.md) | 当前盲注重复牌型、眼睛限制与削弱 |
| EXP-RED-STAKE-ECON | [r2](experience/EXP-RED-STAKE-ECON/r0002.md) | 红注收入与得分成长、清水风险 |
| EXP-FIRST-CARD-ENGINE | [r2](experience/EXP-FIRST-CARD-ENGINE/r0002.md) | 首计分牌重复、复制、加乘顺序与纠错 |
| EXP-PLANET-RESERVE | [r1](experience/EXP-PLANET-RESERVE/r0001.md) | 优惠券条件、持有星球倍乘与包内升级 |
| EXP-SHUFFLED-JOKERS | [r1](experience/EXP-SHUFFLED-JOKERS/r0001.md) | 翻面打乱后的未知顺序与公开能力集合 |

每条HEAD.json指向当前版本；旧r文件保留审计和read_notes历史读取，不能随文档精简删除。首牌引擎r1的错误算式已在r2明确撤回，旧版本不能作为当前计分依据。红注经济置信度low，其余medium，须核对各自条件和反例。

首版正常局、整合白注、新白注及单列恢复尝试提供来源，建设与故障不混作连续正式局。完整交付、跨局修订和独立读盘证明已集中在[历史记录](../evidence/README.md)，按笔记的run_id／step及压缩包内原路径追溯。

最近恢复局152／153步新增两条，154实际读回；星球和翻面独立证明保留在历史包中。已有9条没有充分新对照时保留原修订，不强行更新。新用户默认获得这些已有经验；比较模型时必须登记相同起点，不能把它当作空经验测试。

新局前实际read_notes并重新核对当前牌、Joker、等级与Boss，不能照搬上一局配置。完整存储契约见[技术参考](../docs/balatro-ai/reference.md#经验与公开计算)；旧验收叙述与TEST样本已归档，正式内容和全部版本未改。
