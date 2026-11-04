# RogueRust 第五轮代码审查：内容扩充、门禁与 StS Wiki 差距

> 审查版本：`105659cdfda48577135dd79492b214109d4b68d8` → `a9d2c539c12a66dbe876d87c18e9b24c161e957f`  
> 审查日期：2026-11-04  
> 目标范围：第一阶段 WASM 优先；不以 MCU 兼容、极限内存预算或临时 UI 像素一致性为阻塞标准。  
> 方法与限制：读取指定终点 commit 的公开源码、README、Wiki 缺口文档、若干检查脚本并交叉核对 StS **第一代** Wiki。未能取得完整 Git compare 补丁；未在本地 clone、编译、执行测试。因此这是**有针对性的静态代码和文档审查**，不是穷尽式差异审计，更不是独立测试通过证明。

## 1. 执行摘要

总体方向正确：内容扩充带动了 Core、WASM、内容格式、校验器协同迭代，而不是单纯往 JSON 堆内容。最值得沉淀的是 **内容事实检查 + 二进制往返 + 外键检查 + 无效字段检查** 的多层门禁、以最小新抽象修复真实机制的迭代方式，以及新内容有意降级时写明原因。

目前风险从“基础设施是否能用”转向“**玩家可见的行为是否与 StS 一致，且检查器能否发现行为差异**”。优先修正 `select_cards_node` 的候选截断/数量边界，完善 Stasis 随机性与 Red Slaver Entangle，然后将已完成的内容从过期 gap 表里清理。

## 2. 问题优先级与证据表

| 优先级 | 项目 | 静态证据 | 建议最低验收 |
|---|---|---|---|
| P1 | `select_cards_node` 候选列表固定 64 个、溢出静默 `break` | `kernel/rd-core/src/exec.rs:3458-3466` | 65+ 张牌、最高稀有度卡位于末尾时仍可参与；不得静默截断 |
| P1 | Stasis `HighestRarity` 同稀有度保持牌堆顺序而非随机 | `exec.rs:3490-3501`；StS Wiki Bronze Automaton | 至少两张并列最高稀有度卡；不同种子可选择不同卡，相同种子可重放 |
| P1 | `Count > found` 时遍历未填充的 `order` 位置 | `exec.rs:3519-3529` | 仅一张候选要求两张时明确、稳定、无重复的行为 |
| P1 | Red Slaver 仅 Stab/Scrape，缺 Entangle | `native/sts_content_check.py:260`；Wiki Slavers | 增加 Entangled 的禁止攻击判定及敌人动作序列测试 |
| P1 | `Owner` 关系没有校验主人真实存在；畸形值 `continue` | `kernel/rd-wasm/src/lib.rs:651-664` | 故意拼错主人 ID，内容门禁或建战失败；同名实例绑定明确 |
| P1 文档 | gap 文件与 README 就 Boss、Ascension、事件等出现跨阶段矛盾 | `docs/sts-wiki-gap.md:77-100,156-190,209-247`；`README.md:119-146` | 当前能力与待办各只有一个版本，不再出现过期任务 |
| P1 文档 | Double Damage、Duplication、Double Tap、Divinity 被混淆 | `docs/sts-wiki-gap.md:47`；Wiki 语义页 | 明确“倍率/追加打出/姿态”，按 Ironclad 范围标记不适用项 |
| P2 | `EnemySpec::spawn()` 将未知布尔编码当成 true | `kernel/rd-core/src/content.rs:1979-1993` | 只接受明确布尔值及合法缺省哨兵，其余报错 |
| P2 | `Box::leak` 随每次战斗建立累积 | `kernel/rd-wasm/src/lib.rs:585-621` | 长跑测试报告增长；当前阶段不要求彻底重写 |
| P2 | 检查器的两份“事实表”可能一起抄错 | `native/sts_content_check.py`、`native/gap_check.py` | 每批增量抽样对 Wiki 原页和出处版本核查 |
| P2 | 20 道门禁不等于 Act2/Act3 浏览器闭环 | `README.md` 门禁说明、`web/act1_slice.mjs` | 在现有门禁中增补全遭遇构造 + Act2/3 代表战斗切片 |

## 3. 核心实现问题

### 3.1 候选集静默截断与取样顺序

`select_cards_node()` 用 `MAX_SELECTED_CARDS * 8` 当临时缓冲区容量，并在达到容量时 `break`。由于目标牌区容量可大于 64，后续牌没有进入排序。若 Stasis 需要从抽牌堆选择最高稀有度卡，排在第 65 张以后的 Rare 会被忽略。

建议：

- 如果保持静态数组，使用真正的合法牌区容量作为候选上界；收集容量不够时返回错误，不准 `break`。
- `HighestRarity` 先找到最高 rank，再对并列最高的候选进行**由既有战斗 RNG 驱动的随机选择**。明确 RNG 消费次数；不建议凭 UI 观察重掷。
- `count` 与候选数量必须协同：采用 `min(count, found)` 或显式拒绝，具体以效果节点语义为准。不要读取 `order[found..]` 的默认索引。
- 测试：64/65/96 张、最高稀有度位于末尾、完全同级、空主牌堆但备用牌堆非空、只有一张却请求两张。

StS Wiki 明确写出 Bronze Orb 的 Stasis 从 draw pile（空时 discard）随机盗取**最高稀有度**卡，死亡后返还手牌。该 Wiki 页面本身标注部分内容“under construction”，因此数值/模式如有冲突应交叉核对原版资源，但这条核心规则描述清楚。

### 3.2 敌人 Owner 引用完整性

`rd-wasm/src/lib.rs` 建立 `Owner` 时，只对字符串做 `CombatantId::new`，然后给 minion 指针赋值；没有对当前遭遇中主人是否存在进行解析，而且非法 minion/master 名称会被静默 `continue`。例如拼错可构造的主人 ID，战斗状态仍建立，但死亡关联无法按预期触发。

建议在内容编译或 `XREF` 验收中新增 **ENCT Owner 外键**，在 build-fight 中对已登场主人进行存在性检查。对于主人仅在后续 Spawn 才出现的场景，必须另定义合法引用范围；不要隐含接受悬空引用。针对同名 `id#2` 场景也需测试名字规范化与引用解析。

### 3.3 F_BOOL 解析宽松

`EnemySpec::spawn()` 当前 `BOOL_TRUE/BOOL_FALSE` 之外统一 `Ok(true)`。应单列 `ABSENT16/NULL16`（以现有格式合法哨兵为准）默认 true，其他槽值报 `WrongFieldKind` 或新增 `BadBool`。

### 3.4 战斗数据泄漏

`Box::leak` 解决了静态寿命要求，但持续开战会泄漏多个切片以及重复名字和主人字符串。这是**已存在且在此次扩充进一步使用**的技术债。第一阶段不应再为其启动大范围内核重构；先通过连续 100/500/1000 次重建战斗的 WASM 内存曲线判断实际影响。长期合理方向是 Session 持有 `FightPlan` 背后的数据，而非永久泄漏。

## 4. 门禁设计评估

### 4.1 已经值得保留的方法

`native/sts_content_check.py` 的检查分成：

1. `INV`：根据人工整理的参考事实表核对伤害、层数、稀有度等；
2. `ROUND`：JSON 编译为 full/core 镜像后，读回内容，逐键比较，包括字段是否存在；
3. `XREF`：验证牌组、遭遇、敌人动作、状态 ID 等引用；
4. `INERT`：明确列出编入内容但运行时不读取的字段。

配合镜像过期检查、故障注入及分层浏览器测试，属于可以长期复用的工程实践。特别是 `INERT` 减少“看似完整、实际根本没有被消费”的字段，是内容驱动引擎的重要风险控制。

### 4.2 不能被绿灯证明的内容

- `INV` 的事实表来源若抄错，代码和内容一起一致也会绿。此前 Agent 自己在核查 `blind` 稀有度 / Exhaust 时已发现此类问题。
- `gap_check.py` 主要是**打印当前源码/内容统计**，并不自动读取 Wiki，也不把 README 和 gap 文档里过期的自然语言句子逐条判红。
- `is_declared_inert()` 名单为空只能说明“没有**显式标记** inert 的 status”，不能逻辑推导“全部 status 的每条 StS 语义均已正确实现”。这句话应修改。
- Act1 浏览器切片及随机 Soak 不能替代 Act2/Act3 的定向验证。`enc_darklings` 此前可以进入池却无法初始化，直到较晚才被修复，这正是“内容在池里”与“能成功建战”不同的反例。

推荐新增无需新门编号的两种能力：

- `AllEncounterConstructible`：枚举所有可进入的 encounter，按 `A0/A9/A19/A20` 构建战斗，检查首轮动作合法、状态指纹可取、结束或退出不会失败。
- `WikiFacts`：为新/修改的内容事实记录 `entity/action/field/expected/source_url/checked_at/status`，只有核对过 Wiki 原页的项标记 `verified`；有意降级单独标记 `intentional_deviation`。不要求每次 CI 访问 Wiki。

## 5. README、gap 文档的准确性

### 5.1 README 正确但需限定的说法

- “三幕完整路径打通”、“三幕各 3 Boss / 3 精英遭遇”、“20/20 Ascension 有机制”主要说明**结构和规则入口覆盖**，不是敌人 AI/数字全等。建议用 `Implemented / Tested / Wiki-verified / Intentional deviation` 四个维度标示。
- 33 瓶 Ironclad 口径药水，不等于全部官方药水，也不能只凭出现 ID 断言全部特殊交互与原版一致。Wiki 明确 Potion 有角色专属表、概率、饮用地点与遗物交互；这些维度应单独评估。
- 45 条卡牌是 **28 个基础 ID + 17 个升级 ID**，不可直接当作 45 张不同 Ironclad 职业卡，也不能作为“StS 卡牌完成百分比”。
- README 第 4 行参考实现链接指向 GitHub 首页，建议替换为真实仓库 URL。
- 开头三条 MCU 零分配约束仍被描述成第一优先级；应区别“未来兼容目标”与“第一阶段 WASM 开发优先级”，否则 Agent 容易重复过度优化。
- README 明确写出意图抽签使用 `(seed, round, slot)` 派生函数而非严格模拟原版随机流，这一**有意偏差**披露是好的实践，应保持。

### 5.2 gap 文档内部冲突

| 位置 | 错误/过时内容 | 与当前 README/后续条目的关系 | 修订办法 |
|---|---|---|---|
| C 形态切换/复活 | Guardian/Awakened One 仍“没有” | README 记为实现了真实 Mode Shift、复活 | 移入已完成；保留具体残余差异 |
| D Boss 池 | 每幕仅 1 个 Boss | README 已是每幕 3 个 | 删除历史计数 |
| D 事件效果 | 一选项可包含多个效果的描述与完成记录 | README 仍写“一个选项只能有一条效果” | 以当前内容格式与执行器为准统一 |
| E Ascension | “我们 9 条” | 同文已有 20/20 | 修改为 20/20 **机制入口**，并区分数值覆盖 |
| E 动作覆盖 | 42/79 与 48/49 同时出现 | 可能是不同阶段或不同口径 | 保留当前一个权威统计，注明 `actions` / `variants` 两种单位 |
| §3 待办 | 补 A1/A10/A12、六 Boss、A20 | 新版本记录均已完成 | 删除已完成项，重新排序真正缺口 |
| H Boss 降级 | Bronze Orb 没 Stasis、Guardian 只 HP 半血切换、Awakened 无 Cultist | README 已确认这些实现了 | 表改为最新行为；将历史降级移至 port-plan |
| A Double Damage | 等同于 Blasphemy/Divinity 的“下一张攻击打两次”，与 Duplication 共用 | 与 Wiki 三种截然不同机制混淆 | 更正术语；Watcher 内容不在 Ironclad 范围内 |

### 5.3 Double Damage / Duplication / Double Tap / Divinity 必须分开

| 机制 | StS 1 语义 | 类别 |
|---|---|---|
| Double Damage | 攻击伤害倍率 ×2（与某些 Buff 相关） | 倍率修饰 |
| Duplication | 下一张或下几张牌打出两次；可以是 Skill/Power | 额外播放动作 |
| Double Tap | 下一张或两张 Attack 打出两次 | 额外播放动作 + Attack 限制 |
| Divinity（Watcher） | 进入姿态获得能量，姿态中攻击造成 ×3 伤害 | 姿态/伤害倍率，**不属当前 Ironclad 目标** |

因此不能把 `standard.duplication` 视作已经支持 Double Damage 或 Divinity。这首先是 Wiki 解释错误，其次才决定是否要扩展内核。

## 6. 当前代码与 StS Wiki 的实际剩余差距

下表按**实际游戏影响**而非仅实体数量排序。`确认`指代码/项目自认缺口与 Wiki 内容相互印证；`部分`表示有框架但行为不等价；`暂不优先`表示超出本轮 Ironclad 单三幕重点。

| 分类 | 当前状态 | Wiki/原版差距 | 级别 |
|---|---|---|---|
| Red Slaver | 只有 Stab、Scrape | 缺 Entangle 与相关 AI 限制 | P1 确认 |
| Bronze Orb | 能盗卡、死亡归还；新通用挑选机制 | 最高稀有度并列随机、>64 张候选溢出 | P1 确认 |
| Barricade / Blur | 缺 | 格挡跨回合保留、条件性清除 | P1 已列缺口 |
| Entangled | 缺 | 禁用本回合 Attack 出牌 | P1 已列缺口 |
| Slow | 缺 | Giant Head 每张牌对目标增伤 | P1 已列缺口 |
| Draw / Energized | 只有本回合即时版 | 下一回合增抽、增能量的结算时序 | P1/P2 |
| Reptomancer Dagger | 不能自行自毁 | Explode 自毁，同时执行伤害/塞 Wound | P1/P2 |
| Looter | 无完整偷金逃跑 | 金币损失与 Escaped 的结算一致性 | P2 |
| Giant Head | 320 HP 简化版、伤害/Glare 改写 | 500 HP、Slow、It Is Time 递增 | P2 有意偏差 |
| Boss Ascension 起始值 | `StartingStatuses` 缺独立 Asc 轴 | 例如某些 Boss 的 Artifact/Regenerate 随难度变化 | P2 已披露 |
| A9 Boss HP | 百分比近似 | StS 指定血量不必与通用百分比完全一致 | P2 已披露 |
| Boss 行动 RNG | 派生 `(seed, round, slot)` | 不等同于 StS 的随机流消费 | P2 有意偏差 |
| Ironclad 卡牌 | 28 基础记录含非 Ironclad 卡 | 原版职业卡池、升级与触发组合仍大量缺失 | P1 内容规模 |
| 遗物 | 13 件 | 遗物池、稀有度、组合效果与触发时机严重不足 | P1 内容规模 |
| 事件 | 9 个 | 三幕事件池、选项条件、A15、遗物互动等仍稀疏 | P1 内容规模 |
| 普通遭遇 | Act2 普通池仅 2 个（gap 自述） | 三幕丰富度与遭遇分布 | P1 体验 |
| 商店 | 无色卡货架缺失 | StS 商店销售 2 张无色牌等 | P2 |
| 篝火 | Rest / Smith | Recall / Lift / Toke / Dig | P2 |
| 第四幕 | 无钥匙、Act4 | 红/绿/蓝钥匙与 Heart 关卡 | 暂不优先 |
| 角色范围 | Ironclad only | Silent/Defect/Watcher 内容、Stance/Orbs/Scry | 明确不做 |

重要：用户当前目标是“类似 StS”，并非必须复制全部 StS 内容；有意偏差可以保留，但要标注，避免文件里一边写“全部精确”，另一边列出“仍故意不一致”。

## 7. 下一轮建议工作包（防止无止境基础设施重构）

### 工作包 A：少量正确性修补（优先）

1. 修 `select_cards_node()` 的容量、并列随机、`Count>found` 三个边界。
2. 修内容 `Owner` 外键，顺手纠正非法 F_BOOL 解析。
3. 用至少两个负向测试证明上述问题在修前可以红、修后可以绿。

验收：修复前失败样例、修复后通过；不得顺手迁移全部内核或扩写 ABI。

### 工作包 B：机制级内容扩充

1. `Entangled` + Red Slaver 真正第三招与行为限制。
2. 回合格挡保留相关（Barricade / Blur），其事件时序测试。
3. `Slow`（Giant Head），下一回合 Draw/Energized；选择玩家可感知收益最大的机制先做。
4. 后续再做 Reptomancer Dagger 自毁、Looter 偷钱逃跑。

验收：每种机制至少有单元场景 + 特定敌人脚本场景；同机制不同内容项不复制规则逻辑。

### 工作包 C：低成本覆盖拓展

- Act2/Act3 的 deterministic battle smoke（各 1~2 个特殊敌人）。
- 遍历 33 encounter 的可构建测试；包含预置、Spawn:false、重复 ID、Owner。
- 内容字段的 Wiki 来源追溯，至少重点核对伤害、稀有度、Exhaust、A 阈值。

### 工作包 D：文档纠偏

- `sts-wiki-gap.md` 保留“**当前**差距”而非历史缺口，历史移入 `port-plan.md`。
- 采用按内容项编码的覆盖矩阵：`Entity | Implemented | RuntimeTested | WikiVerified | IntentionalDeviation | Evidence`。
- 由 `gap_check.py` 生成 **当前计数区块**，让 README/gap 引用它；同一单位只在一处人工维护。
- README 写清第一阶段 WASM 优先，裸机与极限内存约束保留为未来目标。

## 8. 值得沉淀到 AGENTS.md 的实践

> **内容扩充行为契约**：
>
> 1. 新规则先确认是否已有同等抽象；只扩展缺少的表达能力，不重复建系统。
> 2. 新机制同时给出成功、拒绝、容量边界、生命周期、确定性回放五类语义。
> 3. 内容编译的外键必须可靠解析，不允许 `continue`/`unwrap_or(false)` 将配置错误静默吞掉。
> 4. 内容门禁有四层：事实（Wiki）、编译与读回、外键、运行时语义；任何一层绿色不能代表其他层绿色。
> 5. 文档数字必须注明统计单位：实体 ID、升级行、动作、变体、拥有机制、行为对齐不能混为一个完成率。
> 6. 故意降级属于产品决策，必须在内容和 gap 文件明确标注；不能再写“与 Wiki 完全一致”。
> 7. 阶段性报告写明独立执行的命令、成功输出、未执行项、风险；禁止把旧的 20/20 闸门记录当本轮实际复验。
> 8. 对第一阶段无关的 MCU、嵌入式内存和临时像素门禁，不为了形式完备扩大授权范围。

## 9. 主要源码与 Wiki 出处

### 仓库（全部固定到指定终点 commit）

- [README.md](https://github.com/tk166/RogueRust/blob/a9d2c539c12a66dbe876d87c18e9b24c161e957f/README.md)
- [docs/sts-wiki-gap.md](https://github.com/tk166/RogueRust/blob/a9d2c539c12a66dbe876d87c18e9b24c161e957f/docs/sts-wiki-gap.md)
- [kernel/rd-core/src/exec.rs](https://github.com/tk166/RogueRust/blob/a9d2c539c12a66dbe876d87c18e9b24c161e957f/kernel/rd-core/src/exec.rs#L3420-L3531)
- [kernel/rd-core/src/content.rs](https://github.com/tk166/RogueRust/blob/a9d2c539c12a66dbe876d87c18e9b24c161e957f/kernel/rd-core/src/content.rs#L1973-L1995)
- [kernel/rd-wasm/src/lib.rs](https://github.com/tk166/RogueRust/blob/a9d2c539c12a66dbe876d87c18e9b24c161e957f/kernel/rd-wasm/src/lib.rs#L548-L665)
- [native/sts_content_check.py](https://github.com/tk166/RogueRust/blob/a9d2c539c12a66dbe876d87c18e9b24c161e957f/native/sts_content_check.py)
- [native/gap_check.py](https://github.com/tk166/RogueRust/blob/a9d2c539c12a66dbe876d87c18e9b24c161e957f/native/gap_check.py)

### Wiki（请始终确认页面是 **Slay the Spire 1** 而非 StS 2）

- [Bronze Automaton / Bronze Orb / Stasis](https://slaythespire.wiki.gg/wiki/Bronze_Automaton)
- [Slavers / Red Slaver / Entangle](https://slay-the-spire.fandom.com/wiki/Slavers)
- [Duplication](https://slaythespire.gg/buffs/Duplication)
- [Double Tap](https://slaythespire.wiki.gg/wiki/Double_Tap)
- [Divinity](https://slay-the-spire.fandom.com/wiki/Divinity)
- [Potions, class exclusivity, drop odds and interactions](https://slaythespire.wiki.gg/wiki/Potions)
- [Map Locations, Merchant and Boss pools](https://slaythespire.wiki.gg/wiki/Treasure_Rooms)
- [Mechanics, three keys](https://slaythespire.wiki.gg/wiki/Mechanics)
- [The Ending (Act4)](https://slaythespire.wiki.gg/wiki/The_Ending)

---

**结论**：引擎已有可靠的“可扩充”基础。现在最有回报的是修复几个明确的新机制边界、完善已经出现但失真的敌人行为、建立 Wiki 语义分级覆盖表，并停止将过期阶段笔记混在当前缺口清单里。除非新问题要求，不建议推翻 Core/Run/WASM 分层、重写已有内容编译格式或扩大临时 UI 的像素门禁。

---

## 10. 维护者复核（对应 `port-plan.md` §195.9）

> 复核方式：逐条打开报告引用的源码位置核对（`105659c..a9d2c53` 的实际状态），**不采信文字描述**。
> 本机可跑测试，所以下面的"成立"是"我按代码路径确认"，不是"我同意措辞"。

### 10.1 逐条裁定

| 报告条目 | 裁定 | 关键证据 / 备注 |
|---|---|---|
| P1-1 候选缓冲 64、溢出静默 `break` | **成立** | 缓冲是 `MAX_SELECTED_CARDS * 8` = 64，而 `MAX_CARDS_PER_ZONE` = **96**；`if found == candidates.len() { break }` |
| P1-2 `HighestRarity` 并列按牌堆序 | **成立** | 稳定选择 ⇒ 三张同稀有度永远偷同一张（第一张） |
| P1-3 `Count > found` 读未填充 `order` | **成立，且是活路径** | Stasis 的归还就是 `Count: 4`、`found == 1` ⇒ 同一张卡入队 4 次、`effects` 多记 3 次（此前只表现为"同区搬运是 no-op"，所以没红） |
| P1-4 Red Slaver 缺 Entangle | **成立** | 动作表只有 `stab` / `scrape`。但注意它不只是内容缺口：`Entangled` 要在 `play.rs` 加一条拒绝 |
| P1-5 `Owner` 无外键、畸形值 `continue` | **成立（本轮引入）** | `CombatantId::new` 失败即 `continue`，且不校验 master 是否在场 ⇒ 拼错主人 = 悬空引用 = 小兵永不逃跑，**完全静默** |
| P1-6 gap 文档与 README 矛盾 | **成立** | gap 的 103/115/249/253/278/284 行仍是旧状态；最刺眼的是 **§194 写的 §H 表**在 §195 之后整表过期 |
| P2-1 `spawn()` 未知布尔值当 true | **成立** | `_ => Ok(true)` 同时吞掉 `BOOL_ABSENT`/`BOOL_NULL` **和垃圾槽值** |
| P2-2 `Box::leak` 累积 | **成立（既有技术债）** | 每次建战泄漏若干切片；代码里已注明是浏览器取舍。第一阶段不动 |
| P2-3 两份事实表可能一起抄错 | **成立且无法证伪** | 只能靠"抽样回 wiki 原页"；已在 §195.9 的流程里写成硬要求 |
| P2-4 20 道门禁 ≠ Act2/3 闭环 | **成立** | `web/act1_slice.mjs` 只覆盖第一幕 |

### 10.2 报告里已过时的两处

1. **"`is_declared_inert()` 名单为空"** —— 复查时应为 **7 条**（`sharp_hide` / `curiosity` /
   `mode_shift` / `unawakened` / `stasis` / `stasis_ready` / `draw_reduction`）。它想表达的**结论**
   仍然成立（"在 inert 名单上"≠"内容触发器写得对"），但论据要换。
2. **"45 条卡牌是 28 基础 + 17 升级"** —— README 当前就是这么写的；真正的缺陷是那 28 条里混着
   `buffer`（Defect）与 `apparition`（无色事件牌），报告把它归进"Ironclad 卡牌"那一行是对的。

### 10.3 报告漏掉的三条

1. **同一个 64 也卡住排序数组**：`order` 与 `candidates` 同尺寸，所以只修收集不修排序仍会溢出。
2. **`Owner` 与"同名记录"交叉**：主人自己若是重复 id（`cultist#2`），`Owner: "cultist"` 会绑到
   **第一条** —— 修外键时"悬空"与"歧义"都要报错。
3. **`FallbackZone` + `RequireTag` 的组合已核，非缺陷**：过滤后 `found == 0` 不会 `break`，会正确
   落到备用牌堆。写在这里是为了让下一个人不必再查一遍。

### 10.4 优先级的不同意见

报告 §6 把"Ironclad 卡牌只有 28 条基础记录"列为 **P1 内容规模**。本项目是"内核可扩充性优先、内容
按需长"的原型，我不接受这个排序：它的成本是"几十张卡 × 每张一条内容门事实"，收益是把已经对齐的机制
重复四十遍；真按 P1 做会让"机制覆盖"停下来等"卡池覆盖"。**降为 P2**，并用报告自己 §5.1 的四维标注
（`Implemented / Tested / Wiki-verified / Intentional deviation`）表达成熟度，而不是拿卡牌数量当完成率。

其余同意报告的排序，并按下面的"顺序"执行（与报告的唯一区别：把"可构建性门禁"提到机制扩充之前 ——
`enc_darklings` 这个"进得了池、永远建不起来"的 bug 正是缺它）。

### 10.5 实际执行的顺序

| 序 | 事项 | 状态 |
|---|---|---|
| 1 | `select_cards` 三个边界（容量报错 / 并列用战斗 RNG / `min(count, found)`）+ `Owner` 外键 + `spawn()` 布尔严格 | §195.9.1，含四条负控 |
| 2 | 门禁 `AllEncounterConstructible`（全部可入池遭遇 × A0/A9/A19/A20 建战） | §195.9.2 |
| 3 | gap 文档只留"当前差距"，历史归档到 `port-plan.md`；计数交给 `gap_check.py` 生成 | §195.9.3 |
| 4 | `Entangled` + Red Slaver 第三招（要动 `play.rs` 的拒绝码） | 待做 |
| 5 | Barricade / Blur、Slow、下回合 Draw/Energized、Dagger 自毁、Looter | 待做 |
| — | Act4 / 其他角色 / `Box::leak` 重构 | 明确不做，写进 README"范围外" |
