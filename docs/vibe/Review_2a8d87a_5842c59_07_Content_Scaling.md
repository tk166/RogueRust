# RogueRust 第七轮增量审查：内核契约与 StS Wiki 内容对账

**范围**：`2a8d87acaa293c67784bc65382aa19ca96d58911` → `5842c5928010bd76850f6b11c75e2086bc648e25`  
**审查基准**：终点 commit 固定版本；StS **第一代** Wiki（`slaythespire.wiki.gg`）；README、`docs/sts-wiki-gap.md`、`docs/event-gaps.md`。  
**验证限制**：静态核对了起止版本的重点源代码、终点文档与公开 Wiki，未能获取完整 Git compare 补丁，未独立构建或运行测试。下述“确定”指能从所列源码推导；“待复现”指运行时影响仍需定向测试。

## 1. 总览

仓库记录的终点规模为：**293 条卡牌定义（154 基础、139 升级）；152 件遗物；146 种状态；50 种怪物；47 种遭遇**；最近开发记录 **1147 单测、21/21 聚合门禁**。这些是项目自报数字，不是本报告独立测试结果。卡牌条目与基础卡牌、遗物总体目录与 Ironclad 可用遗物不能混为一谈。

**主要判断：** 目前没有证据支持推倒 V1。复杂玩法正在复用既有 Run/Core/Content/WASM 分层，但新增长期状态没有完整接入存档与状态哈希，违反了以前已经沉淀的确定性契约；拾取类遗物又出现先修改状态、后进入可失败分支的事务问题。内容扩充方面，独立 Wiki 对账发现了明确错误（Orange Pellets），并存在若干已知有意偏差与事件缺口。

## 2. P0：RunState 新增字段未接入存档/回放指纹

**文件**：
- [`kernel/rd-run/src/state.rs`](https://github.com/tk166/RogueRust/blob/5842c5928010bd76850f6b11c75e2086bc648e25/kernel/rd-run/src/state.rs#L1638-L1788)
- [`kernel/rd-run/src/state/archive.rs`](https://github.com/tk166/RogueRust/blob/5842c5928010bd76850f6b11c75e2086bc648e25/kernel/rd-run/src/state/archive.rs#L494-L558)
- [`kernel/rd-run/src/hash.rs`](https://github.com/tk166/RogueRust/blob/5842c5928010bd76850f6b11c75e2086bc648e25/kernel/rd-run/src/hash.rs)

| 字段/系统 | 影响游戏行为 | 观察到的遗漏 |
|---|---|---|
| `marks: [RunMark; MAX_RUN_DECK]` | Ritual Dagger 等实体卡的永久成长；跨战斗传递 | 存档与 Run hash 均未包含 |
| `chest_extra` | Matryoshka 的后续双遗物宝箱次数 | 存档/哈希漏 |
| `chest_empty` | N'loth's Hungry Face 的下个空宝箱 | 存档/哈希漏 |
| `pickup_relics` | Calling Bell 的待领取遗物 | 存档/哈希漏 |
| `pickup_potions` | Cauldron 的待领取药水 | 存档/哈希漏 |
| `event_step`、`event_resume`、`event_fight_pool`、`event_fight` | 多阶段事件的页面/战斗恢复/特殊遭遇 | 存档未包含，哈希覆盖不全 |
| `bosses_fought` | A20 第三幕双 Boss 进度 | 存档未包含，需核查哈希 |

存档 writer 在写完有效 `deck`、`relics`、`potions` 后仅写 `event` 与 `last_encounter`；reader 从基础 RunState 恢复，却没有给上述字段赋值。`marks` 则明确在源码中被解释为“不进 run hash”，此理由不成立：参考引擎的核心 golden fingerprint 与 RogueRust 自己的运行层 replay fingerprint 是不同的契约。只要一个字段影响**未来行为**，它就应参与 RunState 的完整快照/行为等价回放判据，除非有明确理由将其排除。

**最小复现用例：**
1. Ritual Dagger 完成一次或多次 Fatal，保存、回档、重新开战；比较卡牌实例的永久加伤。
2. 领取 Matryoshka 并只打开一次宝箱，保存、回档、检查剩余次数及后续宝箱效果。
3. 进入多阶段事件的非初始节点，保存、回档、对比事件节点与合法操作。
4. A20 第三幕打败第一个 Boss 后保存再回档，对比是否仍需第二场。
5. 在两个状态中只改变一张卡的 `RunMark`；确认 Run hash 不相同。

**修复方案：** 逐字段梳理 `RunState` 的初始化、变更、存档、恢复、哈希、不变量和重置；为确实影响后续行为的字段统一加到存档及规范哈希；提升存档版本，旧格式明确拒绝或做经测试的迁移。测试同时用 `assert_eq!(restored, state)` 和后续行为一致性/回放，不能只比哈希。

## 3. P1：拾取类遗物没有失败原子性

**文件**：[`state.rs#L2444-L2584`](https://github.com/tk166/RogueRust/blob/5842c5928010bd76850f6b11c75e2086bc648e25/kernel/rd-run/src/state.rs#L2444-L2584)、[`state.rs#L3326-L3375`](https://github.com/tk166/RogueRust/blob/5842c5928010bd76850f6b11c75e2086bc648e25/kernel/rd-run/src/state.rs#L3326-L3375)。

`push_relic("tiny_house", pool)` 先加金币、最大生命、当前生命、待领取药水、待领取卡牌，再调用可能失败的 `roll_pickup_offer(pool)?`。`pool=[]` 会触发 `RunError::PoolTooSmall`，但前面状态更改不会回滚，遗物也不会被写入腰带。`orrery` 先增加待选次数再抽取，也有同类路径。`pickup_add_card` 在成功加入一张卡并递减待领取次数后继续生成下一轮 offer；若下一轮生成失败，同样可能返回错误并留部分修改。

**回归用例**：
```rust
let before = state;
assert!(state.push_relic("tiny_house", &[]).is_err());
assert_eq!(state, before);  // 包括 RNG、金币、HP、牌组、待领取项
```

修复时可前置检查卡池有效性；对 RNG、后续抽牌仍可能失败的复杂流程，可以在 `RunState` 的临时副本上完成完整操作后一次提交。这里已有 `Copy` 状态基础，不需要新建通用事务框架。

## 4. P1：CombatBonus 达到容量时仍会丢效果

**文件**：[`state.rs#L481-L522`](https://github.com/tk166/RogueRust/blob/5842c5928010bd76850f6b11c75e2086bc648e25/kernel/rd-run/src/state.rs#L481-L522)、[`state.rs#L3506-L3608`](https://github.com/tk166/RogueRust/blob/5842c5928010bd76850f6b11c75e2086bc648e25/kernel/rd-run/src/state.rs#L3506-L3608)。

`MAX_COMBAT_STATUSES = 4`；`CombatBonus::push_status()` / `push_enemy_status()` 返回布尔值表示失败，但调用端有 `let _ = bonus.push_status(...)`；给敌人状态的分支只在 debug 断言，Release 可能静默忽略。**确定存在失败被吞路径**，但目前尚未验证现有合法遗物组合能否触及 4 个不同状态的上限。

推荐：让开战加成返回 `Result`，或证明合法组合的最大 distinct status 数不会超过容量，并使违反该证明的内容编译失败。要避免为 MCU 约束在 WASM 第一阶段损害行为正确性。

## 5. P1：Orange Pellets 实际行为与 StS Wiki 完全不符

**内容**：[`sts.roguedeck.json#L9445`](https://github.com/tk166/RogueRust/blob/5842c5928010bd76850f6b11c75e2086bc648e25/tools/contentc/packages/sts/sts.roguedeck.json#L9445-L9610)。

- 当前描述及效果程序：同回合打出 Power、Attack、Skill 后，给玩家 **+3 Strength、+3 Dexterity**。
- StS1 Wiki：满足条件后，**移除玩家所有 Debuff**，不授予力量或敏捷。
- [Wiki: Orange Pellets / Relics List](https://slaythespire.wiki.gg/wiki/Relics_List)。

这是可以由 JSON `node.applyStatus(strength=3)` 与 `node.applyStatus(dexterity=3)` 直接证实的行为错误，不是单纯文案不一致。`docs/sts-wiki-gap.md` F.19 也将错误效果描述为“一致”，说明 Wiki 核对表存在相同来源错误。

修复：沿用三种出牌类型跟踪，输出改为清除 Debuff；回归测试准备 Weak、Frail、Strength、Dexterity 等状态，验证只去除负面状态，不错误修改或清空 Buff，并覆盖回合重置与同回合多次满足条件。

## 6. P2：已声明但仍影响保真度的遗物差异

| 遗物 | Wiki 语义 | 当前偏差 | 应当如何处理 |
|---|---|---|---|
| Nilry's Codex | 回合末三选一，然后**洗入**抽牌堆 | 放在抽牌堆**顶部** | 确认有随机插入/洗牌的可复用操作后修正；需要固定种子验收 |
| Dead Branch | 每消耗一张牌，向手牌生成职业牌池中的随机牌（有战斗内生成限制） | 声明为任意基础牌，包含无色 | 将随机卡池映射至本职业合规生成集合；明确特殊/治愈排除规则 |
| Cauldron | 拾取时展示五瓶随机药水供挑选 | 将五瓶记为逐项待领取账，可能跨状态遗留；它们还未全部进入存档 | 用一次性供选择列表和容器容量规则表达，不要假定“有五个背包位置” |
| Matryoshka | 接下来两个非 Boss 宝箱获得额外遗物 | 第二件直接写入背包、不进普通奖励 UI | 已声明的 UI/交互简化，当前可接受，但需记录验证 |

Wiki：[Nilry's Codex](https://slaythespire.wiki.gg/wiki/Relics_List)、[Potions](https://slaythespire.wiki.gg/wiki/Potions)、[Relics List](https://slaythespire.wiki.gg/wiki/Relics_List)。

这些与 Orange Pellets 不同：在 gap 文档中已有部分偏差说明，可以作为逐步提高保真度的施工单，不应都当作 P0。

## 7. Wiki 缺口：重点是合法可玩内容，不是全类别百分比

当前项目记录：Red 75/75、Colorless 70/70 已覆盖目录，但“名字/条目存在”不等于交互及生成规则完整；药水 33 种已有入口；遗物 152/193（41 件中包含大量其他职业专属、Blight、Special）；三幕 50 怪物、47 遭遇，但仍有具体行为、刷新池与概率偏差。

按 `docs/event-gaps.md` 最新的 Wiki 分类：

| 内容 | 第一代 StS Wiki 数量 | 已覆盖真事件 | 具体仍缺 |
|---|---:|---:|---|
| Act 1 普通事件 | 11 | 8 | Big Fish、Living Wall、Hypnotizing Colored Mushrooms |
| Act 2 普通事件 | 13 | 5 | Augmenter、Council of Ghosts、Cursed Tome、The Library、Masked Bandits、Pleading Vagrant、Old Beggar、Vampires |
| Act 3 普通事件 | 7 | 1 | Falling、Mind Bloom、Mysterious Sphere、Sensory Stone、Tomb of Lord Red Mask、Winding Halls |

请注意：项目自写的 `old_shrine`、`ancient_forge`、`purification_shrine` 和 `wandering_merchant` 不能算作覆盖 Wiki 同名事件；`ancient_writing` 被放在第一幕且实现为自有事件，不等于原版第二幕的 Ancient Writing。数据口径还应单独处理 Shrine/One-Time Events。Wiki [Events List](https://slaythespire.wiki.gg/wiki/Events_List)、[Events 分类](https://slaythespire.wiki.gg/wiki/Events)。

**Wiki 对账中的另外一个真实差异**：`docs/event-gaps.md` 对未实现的 Mind Bloom 描述成“打 Boss / 复制整副牌 / 升级所有牌，代价是金币或掉血”，但原版选项实际是：战 Act 1 Boss 得 Rare relic；全部升级并获得 Mark of the Bloom（不能治疗）；999 金加 2 Normality；在更高楼层改为回满血并获得 Doubt。它是**缺失事件施工单中的事实错误**，不是已运行代码缺陷。[Wiki: Mind Bloom](https://slaythespire.wiki.gg/wiki/Mind_Bloom)。

**内容施工优先级**：
1. 修复已实现却错误的基础规则（Orange Pellets）；核查已实现遗物中的隐藏组合问题。
2. 填补已有表达能力即可支持的 Act 1/Act 2 事件；补充事件选择的准确代价与奖励。
3. 修补跨战斗成长、待领取账、事件树及 A20 双 Boss 的存档完整性。
4. 再补 Act 2/Act 3 复杂事件与特殊卡牌选择；最后再考虑第四幕、其他职业与无限模式。

## 8. 门禁：正确区分四层证据

| 层级 | 证明什么 | 不能证明什么 |
|---|---|---|
| 内容目录/编译检查 | ID 存在、字段格式对、引用有效 | 名字相同的遗物行为必然正确 |
| 元数据 Wiki 比对（如 audit_relic_gap） | 稀有度、名称、存在性与部分目录完整性 | Orange Pellets 的执行效果准确 |
| Rust 定向规则测试 | 特定状态、特定输入下执行结果 | 所有合法组合及相互作用都正确 |
| 实际整局/浏览器回归 | 主要流程可达，关键交互贯通 | 全部 Wiki 语义和不常见状态正确 |

改进建议：选定 15–30 个**复杂且高互动**遗物/事件建立机器可读的“Wiki 条款 → 内容节点 → 核心行为断言 → 浏览器可见结果”四联索引。不要为了数量而重新手抄全部 Wiki，也不必把统计门禁继续从 21 扩到更多。

**尤其需要新增三种通用回归夹具**：
- `RunState` 每个影响未来行为字段对应的“存档往返/哈希区分/后续行为”测试（更新字段时强制增补）。
- 故意失败的内容池与随机流：`Err` 时完整状态不变；成功时 RNG 消耗规则确定。
- 合法遗物组合的开战加成：覆盖相同状态合并、不同状态容量上界、敌方状态路径。

## 9. 可沉淀的工程实践和避免的误区

**值得保留**：
- 按真实遗物需求新增通用状态、触发器及跨战斗数据，而非提前建万能 DSL。
- `RunState` 保持独立于内容的设计：WASM 适配层按内容解释 ID、Run 层管规则和持久状态。
- 独立内容清单/关系校验/“无消费者字段”扫描；异常应显式报错。
- 把算法差异写成可追踪的“已知偏差”，避免把简化误报为等价。
- `RunState` 是可整体复制的类型，可用于需要复杂多步变更的局部原子提交。

**本轮必须新增到 Agent 契约的两条**：
1. **每新增一项可持久化状态，不允许只改持有字段的结构体**；必须列出初始化、跨战斗传递、保存、恢复、Run hash、回放、不变量、负向测试的覆盖情况。
2. **每新增一件“行为由内容节点实现”的遗物，不允许只对照 Wiki 的名称与稀有度**；至少写一个行为结果断言，确保确实实现的是 Wiki 语义。

## 10. 建议的最小下一轮任务包

| 顺序 | 等级 | 工作 | 验收 |
|---|---|---|---|
| 1 | P0 | 全面审计 RunState → Archive/Hash 字段映射，修复永久 mark、遗物账、事件链、A20 进度 | 字段级往返 + 后续行为一致；旧版本正确拒绝/迁移 |
| 2 | P1 | 修复 Orange Pellets | Debuff 清除、Buff 保留、三类牌时序验证 |
| 3 | P1 | 修复 Tiny House/Orrery/连续选牌异常时的原子性 | 空/非法内容池返回错误时 `state == before` |
| 4 | P1 | 检验 CombatBonus 状态上限 | 不会在 Release 中无提示丢效果 |
| 5 | P2 | Nilry / Dead Branch / Cauldron 行为差异 | Wiki 规则的随机池、时序与选择符合预期 |
| 6 | 内容 | Act 2/3 事件补齐 | 每个事件至少一条合法路径、一条异常/条件路径、Wiki 对账记录 |

**这轮不建议**：重写 Core/Run/WASM 分层、开始 V2、为旧嵌入式预算限制 WASM 内容、把临时 UI 的像素级门禁变成开发阻塞。

## 11. 可靠性声明与参考链接

本报告是面向风险点的**静态审查**，没有完整 diff 逐行覆盖，也没有执行 Rust/浏览器测试。文中可立即通过源码推出的失败路径与需要真实场景重现的潜在问题已分别说明。此版本 1147 个单测、21/21 闸门通过是仓库原有记录，不能被解释为独立验证，也不能证明 Wiki 保真度。

- [指定终点仓库](https://github.com/tk166/RogueRust/tree/5842c5928010bd76850f6b11c75e2086bc648e25)
- [RunState](https://github.com/tk166/RogueRust/blob/5842c5928010bd76850f6b11c75e2086bc648e25/kernel/rd-run/src/state.rs)
- [Archive](https://github.com/tk166/RogueRust/blob/5842c5928010bd76850f6b11c75e2086bc648e25/kernel/rd-run/src/state/archive.rs)
- [Run Hash](https://github.com/tk166/RogueRust/blob/5842c5928010bd76850f6b11c75e2086bc648e25/kernel/rd-run/src/hash.rs)
- [Wiki 第一代 Relics List](https://slaythespire.wiki.gg/wiki/Relics_List)
- [Wiki 第一代 Events List](https://slaythespire.wiki.gg/wiki/Events_List)
- [Wiki 第一代 Potions](https://slaythespire.wiki.gg/wiki/Potions)
- [Wiki Mind Bloom](https://slaythespire.wiki.gg/wiki/Mind_Bloom)
- [Wiki Ascensions](https://slaythespire.wiki.gg/wiki/Ascensions)


---

# 附：本仓的核对结论与实施计划（§308 起）

> 写于 `5842c59` 之后。**下面每一条都对着源码验过**，不是对报告的重述。
> 核对时用的工具留在 `native/check_state_fields.py`（字段清点，已加成闸门 22）。

## A.1 逐条判定

| 报告条目 | 判定 | 证据 |
|---|---|---|
| P0 `RunState` 新字段未接存档/回放指纹 | **真，且比报告的清单更长** | 报告列 5 组；穷尽遍历结构体是 **18 个字段**：`marks` `bosses_fought` `event_step` `event_resume` `event_next` `event_fight` `event_fight_pool` `fight_gold_bonus` `fight_gold_set` `fight_no_relic` `fight_relic_rarity` `fight_extra_relic` `fight_relic` `fight_potion_chance` `chest_extra` `chest_empty` `pickup_relics` `pickup_potions`。其中 `event_step` 是**指纹有、存档没有**（报告说"哈希覆盖不全"，方向对，但两栏是不对称的） |
| P0 "`marks` 不进 hash 的理由不成立" | **真**（那句话是本仓自己写的） | `state.rs` 原注释：*"它不进 run hash：参考的运行层没有这个概念"* —— 把 `hash_golden`（参考逐字节复刻）与 `hash.rs`（**我们自己**的回放指纹）混为一谈。已改 |
| P1 拾取类遗物无失败原子性 | **真（潜伏）** | `PickupTinyHouse` / `PickupAddCards` 先改金币/上限/欠账，再 `roll_pickup_offer(pool)?`。只有 `pool=[]` 时可达（真调用方都给全池），但它违反本仓"拒绝 ⇒ 一个字节都不改" |
| P1 `CombatBonus` 满容时静默丢 | **真，且不是"待复现"** | `MAX_COMBAT_STATUSES = 4`，`combat_bonus` 里 5 处 `let _ = bonus.push_status(...)`。**合法组合直接超**：`vajra`(力量) + `oddly_smooth_stone`(敏捷) + `thread_and_needle`(镀甲) + `bronze_scales`(荆棘) + `orichalcum` = 5 条，第 5 件静默失效。不需要稀有组合 |
| P1 `Orange Pellets` 效果错 | **真** | 内容状态行 `standard.orange_pellets` 的 `DescriptionKey` 与程序就是"+3 力量 +3 敏捷"；wiki 是 *"Whenever you play a Power, Attack, and Skill in the same turn, **remove all debuffs**"*（wiki 页 + Debuff 页两个独立来源）。**成本比报告估的高**：今天内容里没有任何"清 Debuff"节点，要走 `status_catalog` 的 `polarity`（`is_debuff()` 已有）+ 新节点，不是纯 JSON |
| P2 `Nilry's Codex` 进顶 vs 洗入 | **真，但已声明** | wiki：*"choose 1 of 3 random cards to **shuffle into** your draw pile"*。`docs/sts-wiki-gap.md` §F.19 早就写了"进**顶**不是洗入" |
| P2 `Dead Branch` 无色池 | **真，但已声明** | 同 §F.19（"池子是任意基础牌（含无色）"） |
| P2 `Cauldron` 记成逐项欠账 | **真，但根因是 P0** | 欠账本身是设计选择（`pickup_potions`），问题在它**没进存档**（已随 §308 修） |
| §7 `event-gaps.md` 的 `Mind Bloom` 描述错 | **真，是我写的** | wiki 四选项：*I am War*（打第 1 幕 Boss + 稀有遗物 + 50/25 金）、*I am Awake*（升级所有牌 + **Mark of the Bloom**）、*I am Rich*（999 金 + 2 `Normality`）、*I am Healthy*（回满 + `Doubt`）；第三项在 Rich/Healthy 之间换。我写的"复制整副牌"**根本不存在** |
| §7 `ancient_writing` 名不符实 | **真** | 我们的正文是 "Glyphs older than the Spire cover the wall."（升级一张牌），不是 wiki 的 Ancient Writing。**同名 id 会让下一次 wiki 对账看起来"已做"** |

## A.2 报告加分的地方

**它的证据路径是对的**：`Orange Pellets` 的错在**内容 JSON 的 `Statuses` 行**里（遗物行只带
`DisplayName`/`Rarity`，行为挂在"开战状态"上）。核对时一度以为是它看错了层，查完发现是我错。

## A.3 它没看出的两件事（比它列的更坏）

1. **那条"整局相等"的存档判据是瞎的。** `archive.rs` 的 round-trip 测试写着
   *"`RunState` 派生 `PartialEq`，所以判据是整局相等 —— 漏还原一个字段就红"*，
   而夹具 `sample()` 只设了六个字段：**漏 18 个字段它照样绿**。
   ⇒ 修字段只是第一步，**把夹具做成"每一格都非默认"** 才是那一条判据开始工作的时刻。
   负控已做：删掉 `chest_extra` 的写入、删掉 `marks` 的写循环，两次都红（`native/p308_negative.py`）。
2. **`docs/sts-wiki-gap.md` 的"wiki"那一列是从我们自己的行为抄的。**
   §F.19 原文：`orange_pellets | wiki: 一回合内 Power+Attack+Skill ⇒ +3 力量/敏捷 | 已做 | **一致**`
   —— 代码错 → 文档把错的行为写成"wiki 语义" → 对账永远通过。
   更糟的是 `coverage-matrix` 把 `orange_pellets_pays_once_all_three_card_kinds_were_played`
   （测试名本身把错规则写死）记成 `Implemented + TestNamed`：**这条测试会替 bug 站岗**。

## A.4 与报告不同的优先级

| 报告 | 本仓 |
|---|---|
| 1. P0 存档（六项并成一格） | **`event_step` 排第一**：事件中途存档＝重开时静默跳回第一屏（玩家按一次"保存"就撞上）；`marks` 要 `Ritual Dagger` 才可见 |
| 4. P1 `CombatBonus` 容量 | **提到与 P0 同级**：合法遗物组合 5 件就触发，且失败是静默的；上限 4 是我们自己写的，加宽到 8 只是一行 |
| 2. P1 `Orange Pellets` | **第二位**，但成本含一个新节点 + 一条替 bug 站岗的测试要一起改 |
| 6. 内容：Act 2/3 事件 | **报告漏了更大的一个**：Act 2 **普通遭遇池只有 3 条**（wiki 13 种组合） |
| §8 建议"15–30 个四联索引" | 同意，但落地成 `coverage-matrix` 的第 5 列（wiki 条款 id），**不要新建一份清单** —— 否则同一份事实第二存法 |

## A.5 实施计划

| 节 | 等级 | 工作 | 验收 |
|---|---|---|---|
| **§308** | P0 | 18 个字段同时进存档与指纹；`sample_full()` 做成总夹具；两个 `marks` 遗留（删牌不清尾槽、加牌继承）| `STATE_FIELDS PASS (63 fields)`（**新闸门 22**）+ round-trip 在总夹具上跑 + 两条负控红 |
| **§309** | P1 | `CombatBonus` 容量（加宽 + 失败不再静默）；`PickupTinyHouse`/`PickupAddCards` 的原子性（失败时 `state == before`）| 5 件合法遗物组合的状态条数 == 5；空池返回错误时整局相等 |
| **§310** | P1 | `Orange Pellets` 改成"清 Debuff"（新内容节点 + `polarity`）+ 修 §F.19 的"wiki"列 + 改掉那条站岗测试 | Weak/Frail 被清、Buff 保留、三类牌时序；一条"wiki 条款 → 节点 → 断言"的样板 |
| **§311** | 文档 | `event-gaps.md` 的 `Mind Bloom` 事实错误、`ancient_writing` 改名、Act 2 池缺口进 README | 与 wiki 逐条对齐 |

一组**不做**的（报告与我都同意）：重写 Core/Run/WASM 分层、开 V2、为嵌入式预算限制 WASM 内容、
把像素门禁变成开发阻塞。
