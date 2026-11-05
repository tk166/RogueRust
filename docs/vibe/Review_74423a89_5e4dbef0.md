# RogueRust 第六轮增量审查：代码规范与 StS 内容完整性

- **审查范围**：`74423a89b091f223be4d57ac556396907e1bb31f` → `5e4dbef0b2992f6d0b56d2cdd3f468dcdb79f31c`
- **目标**：WASM 优先，维持 V1；不把 MCU 内存预算、临时 UI 视觉质量或过期文档作为本轮阻塞项。
- **证据边界**：本报告基于终点提交的关键源码、指定起止提交记录、开发日志和 StS 1 Wiki 的静态交叉核查。**未取得完整 compare 补丁，未本地编译、执行测试或覆盖全部改动**；不把仓库自报的 900 个单元测试和 21/21 闸门当作独立复验。

## 一、总体结论

本轮内容扩充有实质成果：Entangled、Barricade、Blur、Slow、Berserk、Flying、敌人自毁后的轮转、Looter 偷钱/逃离结算、不同 Ascension 的生命与行动变体、多个精英和 Boss 的行为修复，以及自动生成的覆盖矩阵。这比逐一硬编码动作更有可持续性。

但当前至少存在三项高度具体的规则/状态问题：**Slow 层数跨回合延续**、**The Maw 的 Nom Nom 错把行动者序号当作战斗轮次**、**CombatState.reset_in_place 漏清新增状态字段**。同时，新覆盖矩阵所称 `RuntimeTested` / `WikiVerified` 是来源线索，并不能证明每项玩法语义都通过测试且符合 Wiki。

## 二、发现清单（按修复顺序）

### P1-A：Slow 跨回合未重置，开场层数可能还存在 +10% 偏差

- **定位**：`tools/contentc/packages/sts/sts.roguedeck.json`，`standard.slow`（约 L2310–2368）、`giant_head` 开场状态（约 L25372–25378）；`kernel/rd-core/src/turn.rs`。
- **证据**：Slow 具有 `CardPlayed` 增层、`DamageReceived` `ScalePercentPerStack(10)`，但没有回合末清零的触发器，`UsesDuration=false`。`giant_head` 以 `Stacks=1` 添加该状态。
- **Wiki**：Slow 只统计**本回合**出的牌，下一回合重新从 0 开始；如果开场 1 层直接被用于倍率，还可能导致未打牌就享有 +10%。
- **风险**：第一回合打 5 张牌后，后续回合如果继续累计，会得到不符合原版的攻击倍率；基于当前回合数值的测试无法发现这个错误。
- **最小修复**：明确 Slow 的「状态存在」与「本回合累计牌数」是否允许分开表示；在玩家回合边界重置累计值，不删除 Slow 常驻能力；补 `0/1/5 张牌` 与两回合定向测试，验证未打牌时倍率为 1.0。
- **性质**：缺失生命周期代码与 Wiki 行为差异可静态核对；实际故障尚未动态复现。

代码：<https://github.com/tk166/RogueRust/blob/5e4dbef0b2992f6d0b56d2cdd3f468dcdb79f31c/tools/contentc/packages/sts/sts.roguedeck.json#L2310-L2368>
Wiki：<https://slay-the-spire.fandom.com/wiki/Slow>

### P1-B：The Maw 的 Nom Nom 连击次数取错变量

- **定位**：`sts.roguedeck.json`，`maw.nom_nom`（L22895–22962）；`rd-core/src/expr.rs` `eval_int`（L504–512）；`rd-core/src/turn.rs` 回合推进（约 L777+）。
- **当前公式**：`ceil(turnNumber / 2)`，其中 `turnNumber => state.current_turn`。
- **关键问题**：`current_turn` 是**一轮内行动者次序**，新一轮重置为 1；单人对单只 Maw 的场景里，Maw 通常每轮都对应值 2。原版指的是战斗持续的**轮次**，应考虑 `roundNumber => state.current_round`。
- **预期**：如果强制在战斗第 2、4、6 轮执行 Nom Nom，其连击次数应为 1、2、3（每击伤害 5，其他伤害修饰另算）。
- **建议**：仅将该内容表达式替换为 `roundNumber`，通过真正推进回合而不是直接伪造 `current_turn=1..6` 的测试验证。并核验战斗首轮 round 从 1 开始。
- **性质**：变量语义和内容表达式在源码中已确认；未独立运行。

代码：<https://github.com/tk166/RogueRust/blob/5e4dbef0b2992f6d0b56d2cdd3f468dcdb79f31c/tools/contentc/packages/sts/sts.roguedeck.json#L22895-L22962>
Wiki：<https://slaythespire.wiki.gg/wiki/The_Maw>

### P1-C：`CombatState::reset_in_place` 未纳入新增状态字段

- **定位**：`kernel/rd-core/src/state.rs` L3293–3334、L3406–3448、L3455–3473。
- **源码事实**：`blank()` 和 `Empty::EMPTY` 为 `vacated_seat`、`gold_carried_away`、`ascension` 指定了默认值；`reset_in_place()` 委托 `reset_scalars()` 复位标量并清容器，但 `reset_scalars()` 没有重置这三个字段。
- **后果**：当复用已发生逃跑偷钱或席位空缺的 CombatState 时，旧状态可能带入新战斗。生产路径如果另行显式设置某些字段，可以缓解特定场景，但**`reset_in_place` 自身宣称的「等价于新建状态」不成立**。
- **测试漏洞**：`reset_in_place_matches_new_field_for_field()` 比的是**规范哈希文本**；参考哈希有意排除的状态字段不会使这个测试失败，因此名称里的“field for field”覆盖强度被高估。
- **建议**：把三个字段纳入 `reset_scalars()`，再构造先污染这三个字段、再重置、再检查精确字段值的测试；保留原来的规范哈希测试验证原有契约。未来新增状态字段时必须检查构造、重置、结算、快照、回放。
- **性质**：直接源码确定的重置契约缺陷；最终玩家影响取决于调用路径，待验证。

代码：<https://github.com/tk166/RogueRust/blob/5e4dbef0b2992f6d0b56d2cdd3f468dcdb79f31c/kernel/rd-core/src/state.rs#L3455-L3473>

### P2-A：覆盖矩阵是优秀的“证据索引”，但列名容易让人误以为通过语义验证

- **定位**：`native/coverage_matrix.py` L365–425 与 L600–657。
- `test:<fn>` 实际取自测试函数**字符串字面量**，即便只是构造时引用了实体名，也会被计为具名 `RuntimeTested`；扫描仅包含三个 crate `src/` 一级 `.rs`，没有递归检查所有独立集成测试目录。
- `WikiVerified` 对敌人动作主要继承**所属怪物的 Wiki 页面**，并结合 checker 中是否包含相关不变量表，不能证明动作的 **概率、时间语义、回合状态**全部对齐。`maw.nom_nom` 就是典型反例：能拿到 Wiki 来源标签，却使用错误的回合变量。
- 行动 ID 被列进 `INV_UNWIRED` 时，`build_entities()` 可以显示 `Implemented: yes (declared unwired)`；这是“已声明不可接线”的认可，**不能与运行时可达混为一谈**。`if not reachable and aid in everywhere` 还把字符串 ID 与字典键比较，基本不会触发预期的跨表引用检测。
- **建议**：保留矩阵及其生成器，分别命名为 `SourceReferenced`、`TestNameReferenced`、`GenericHarnessCovered` 和 `BehaviorAsserted`；优先把高风险行为的断言指向可执行测试。加入 3–5 个覆盖矩阵自身的对抗性夹具，特别是“函数体仅出现 id 但未执行行为”。不要为此扩大门禁总量。

代码：<https://github.com/tk166/RogueRust/blob/5e4dbef0b2992f6d0b56d2cdd3f468dcdb79f31c/native/coverage_matrix.py#L365-L425>

### P2-B：`gold_carried_away` 未纳入参考哈希，回放语义需要单独定义

- **定位**：`kernel/rd-core/src/state.rs` 中 `gold_carried_away` 的注释，`rd-wasm/src/run.rs` 中战斗结算。
- 该值确实影响整局金币，同时作者有意识地不把它写进**参考战斗哈希**，为了保留 C# Oracle 的历史语义；回放日志的 `fight_end` 会额外记录值。
- **评价**：这是可接受的兼容权衡，不应为了“所有状态都入哈希”破坏既有参考契约。
- **风险**：参考状态哈希相等，不能自动推出两个战斗在 Looter 逃跑金币结算上等价。
- **建议**：保留参考哈希，另提供战斗结算信息的验证（例如明确比较 `gold_carried_away` 和最终 RunState 金币），不要声称参考哈希覆盖所有实际玩法语义。

## 三、内容完整性：正确理解 360 行覆盖矩阵

终点生成物 `docs/coverage-matrix.md` 的汇总（**实体记录数，不是全部独立游戏机制数，也不是 Wiki 准确率**）：

| 类别 | 内容条目 | 带 `test:` 名称 | 仅 `harness:` 或无具名测试 |
|---|---:|---:|---:|
| 怪物 | 47 | 33 | 14 无具名测试 |
| 敌人动作 | 130 | 59 | 71 仅通用 harness |
| 卡牌 | 51 | 21 | 30 仅通用 harness |
| 状态 | 43 | 40 | 1 harness，2 无证据 |
| 遭遇 | 34 | 25 | 9 仅 harness |
| 事件 | 9 | 9 | — |
| 遗物 | 13 | 9 | 4 仅 harness |
| 药水 | 33 | 33 | — |
| **总计** | **360** | **229** | **131** |

额外解释：

1. **51 行卡牌含基础与升级变体**，不可直接作为“原版 75 张 Ironclad 卡牌”的完成比例。应按基础卡牌唯一 ID、卡牌类型和升级效果单独统计；StS 原版 Ironclad 为 75 种（3 Starter、20 Common、36 Uncommon、16 Rare）。
2. 9 个事件 ID 对应 12 个幕池位次，不是 12 个不同事件。大量遗物和事件内容仍待扩充，不能因敌人 AI 较成熟便宣称整局内容接近完整。
3. 47 个怪物中 14 个没有**具名源码测试的索引证据**，不等于完全没有任何测试；应优先挑出有复杂行为的精英、Boss、召唤物以及逃跑型敌人，用确定性行动序列覆盖。
4. 43 状态里 `standard.lose_dexterity`、`standard.phantom_veil` 缺少矩阵认可的测试证据，适合作为低成本补测对象。
5. 177 个 `wiki:` 条目均来自怪物及动作关联，**卡牌没有独立 Wiki 对照来源**；内容 checker 的人工清单也可能一起抄错。
6. A20 的 StS 原版含 Act 3 双 Boss。即便配置支持 Ascension 0–20 的数值/AI 分支，也不能据此宣称 A20 整局流程完全对齐；须另行核验有无第二场不同 Boss 的连接与结算。未见完整比对，列为待证实内容缺口而非已确认 Bug。

来源：<https://github.com/tk166/RogueRust/blob/5e4dbef0b2992f6d0b56d2cdd3f468dcdb79f31c/docs/coverage-matrix.md>；<https://www.slaythespire.gg/cards/ironclad>；<https://slaythespire.wiki.gg/wiki/Ascension>。

## 四、值得沉淀的工程实践

1. **真实机制推动最小抽象**：Entangled 的出牌合法性、Flying 的攻击减伤与层数、Berserk 的行动回合能量、按 Ascension 变动的行动和开场状态，都是因为真实内容需要而新增能力。不要提前设计 V2 万能 DSL。
2. **把“无数据”与“非法数据”分开**：内容编译器在 Ascension 新字段等路径上选择显式报错，而不是以默认值掩盖解析失败。
3. **通过长回合/多动作测试发现资源泄漏**：根效果链引用计数的修复比增大容量更合理；它验证了资源生命周期，不是极端内存优化。
4. **生成覆盖矩阵而非维护 360 行手工清单**：方向正确。下一步不是换框架，而是准确标记每一列的证据强弱。
5. **用具体 Wiki 条目反向检验抽象的行为含义**：本轮两项 P1（Slow 与 Maw）都说明“表达式能执行”≠“表达式使用的时间语义正确”。

## 五、最小迭代清单

| 优先级 | 工作项 | 最低验收 |
|---|---|---|
| P1 | Slow 回合内层数管理及开场初值 | 无出牌时 0% 加成；每回合独立统计；连续两回合真实操作一致 |
| P1 | Maw Nom Nom 的战斗轮次 | 第 2/4/6 轮强制执行分别 1/2/3 击；通过真实状态机推进 |
| P1 | CombatState 新字段重置 | 先污染 `vacated_seat`、`gold_carried_away`、`ascension`，再 reset，全恢复默认 |
| P2 | 覆盖矩阵证据粒度与负向夹具 | 仅引用字符串的测试不计作行为断言；Wiki 来源不被误认成语义验证 |
| P2 | Looter 结算与重放证据 | 逃离丢金币、击杀返金币、重放结算结果一致 |
| 内容 | 扩展 Ironclad 基础卡、遗物、事件 | 唯一 ID 统计、Wiki 事实及目标机制可玩性分别可核验 |
| 观察项 | A20 第二场 Boss | 如不在范围，显式标记缺口，不以 20/20 配置数代替流程完成 |

本轮不建议进行全局状态重构、WASM ABI 再设计、通用 VM/DSL V2 重写，也不把临时 UI 的像素级门禁列为阻塞项。

## 六、审查方法与局限

- 已核对：指定起止提交页、终点版本 `rd-core` 的状态/表达式/回合代码、STS 内容 JSON、覆盖矩阵生成器和其输出、开发记录相关段落，并使用 StS 第一代 Wiki 交叉检查 Slow/Maw/A20 规则。
- 未完成：完整提交范围 diff 全覆盖、Rust 本机编译、WASM 浏览器执行、全部怪物/卡牌逐条 Wiki 对账、故障注入动态复现。
- 结论级别：P1-A/P1-B/P1-C 是**静态源码证实的语义/契约问题**；P2 是**证据有效性或需进一步验证的风险**；全部待 Agent 用定向测试复验。不要把测试通过数量当成这些问题不存在的证据。

---

**一句话评价**：V1 的机制表达能力与开发验证体系都在进步；下一步的关键不是继续增加抽象，而是确保“时间语义、状态生命周期、测试证据”与新增内容同步扩展。

---

# 七、作者侧复核（写在审查之后，日期 2026-11-05）

> 这一节是**被审的一方**逐条回到源码核对的结论。方法：只读源码 + 检索，**没有**重跑测试或闸门
> （所以"测试能不能红"这件事，下面都是靠**已有测试的写法**判断，不是靠跑）。每条都给出
> `文件:行号`，可以独立复查。

## 7.1 判定总表

| 审查条目 | 判定 | 备注 |
|---|---|---|
| P1-A `Slow` 跨回合未重置 | ✅ 成立（两半都成立） | "开场可能 +10%" 应改成**确定**；另有一处审查未提的偏差 |
| P1-B `Nom Nom` 取错变量 | ✅ 成立 | 比审查说的更严重：不是"增长慢"，是**完全不增长**；病根是测试伪造了变量 |
| P1-C `reset_in_place` 漏字段 | ✅ 成立 | 影响面比审查暗示的**小**（生产路径不走它），但**测试的谎言比审查说的更大** |
| P2-A 覆盖矩阵证据粒度 | ✅ 一半是**作者的实现 bug** | 作者自查另发现两条审查未提的问题 |
| P2-B `gold_carried_away` 不入参考哈希 | ✅ 同意（有意为之） | 只需修正口径说明 |
| 内容项 6：A20 双 Boss | ⚠️ **已实现且有测试** | 过时的是本仓库 `FACT.md` 的"还不能"清单 |

## 7.2 P1-A：`Slow` —— 成立，且偏差比审查列出的多一条

wiki（`slay-the-spire.fandom.com/wiki/Slow`）原文：*"For every card you have played **this turn**,
enemy takes 10% more damage from Attacks, not compounding. **Slow resets at end of turn**; enemy does
NOT carry over stacks of Slow from turn to turn. Only applies to damage caused by playing **Attack
cards**."*

四条事实（前三条是审查提的，第四条是复核时补的）：

1. `standard.slow` 只有 `CardPlayed → +1 层`，`UsesDuration: false`，**没有任何衰减触发器** ⇒
   第 2 回合再打 5 张就是 10 层 = ×200%。
2. §198 的测试 `slow_scales_linearly_with_stacks_and_grows_on_every_card_played`
   （`kernel/rd-core/src/host.rs:7943`）只测"给定层数 → 伤害"和"出牌 +1 层"，**没有一条跨回合断言**
   ⇒ 三个层数点全绿也掩盖了它。
3. `giant_head.StartingStatuses = Slow 1` + `ScalePercentPerStack 10` ⇒ **未出牌就 ×110%**。
   审查写"可能"，实际是确定。
4. **审查未提**：我们的修饰器是 `RestrictDamageKind: Direct`，只区分"直接伤害 / DoT"；wiki 限定
   *"damage caused by playing Attack cards"* ⇒ 火焰药水打 Giant Head 现在也会被放大。
   内核 `modifiers.rs:356` 已经支持 `RestrictSourceCardTag`，内容里那一格是 `null`。

**修法上的硬约束（这条决定了不能按"回合末清零"实现）**：

* `apply_status` 的 `stacks == 0` **不算一次施加**（`exec.rs:4068`）；
* `modifyStatusStacks` 减到 0 会**删掉实例**（`exec.rs:2821`，照参考 `StatusEffects.cs:830-838`）。

⇒ "Slow 存在但计数为 0"这个状态在现有节点集里表达不出来；实例一删，`CardPlayed` 触发器就再也不响。
而内核**已经有** `cardsPlayedThisTurn` 表达式（`expr.rs:527`，`state.cards_played_this_turn`
每回合归零）⇒ 最小修法是加第四种修饰器运算 `ScalePercentPerCardPlayedThisTurn`（与 §198 加
`ScalePercentPerStack` 同形、同走穷尽 `match`），让 `standard.slow` 退化为**标记状态**：
开局 0%、每回合自动归零、可叠加 `RestrictSourceCardTag: attack`。

## 7.3 P1-B：`Nom Nom` —— 成立，而且不是"增长偏慢"

* `turnNumber → state.current_turn`（`expr.rs:540`）；`turn.rs:947/970-979`：一轮内逐个战斗员 +1，
  **绕回时置 1**。
* 单怪场景 Maw 行动时恒为 2 ⇒ `(2+1)/2 = 1` 击，**永远 1 击**；双怪场景恒为 3 ⇒ 恒 2 击。
* §212 的测试 `nom_nom_hits_five_damage_ceil_turn_over_two_times` **直接写
  `session.state.current_turn = turn`**（`kernel/rd-wasm/src/lib.rs:4885`）—— 它验证的公式在真实
  玩法里取不到那些值。**这是比"抄错变量"更值得记的教训：测试伪造了一个不会增长的量。**

修法：内容换 `roundNumber`；测试改成**真的推进轮次**（连打 `end_current_turn_and_start_next`），
断言第 2/4/6 轮 = 1/2/3 击。

## 7.4 P1-C：`reset_in_place` —— 成立，但要分成两件事

* 事实对：`reset_scalars`（`state.rs:3641`）只重置 12 个标量，`vacated_seat` / `gold_carried_away` /
  `ascension` 不在其中。
* **影响面比审查暗示的小**：`rd-wasm` 每场战斗都 `Box::new(CombatState::new(..))`（`lib.rs:797`），
  玩家路径今天不经过 `reset_in_place`；它只在 `build_fight_from_content` 里用，而调用方目前只有测试。
  与审查的 hedge 一致。
* **但若真被复用，后果比"带进新战斗"更硬**：`apply_fight_outcome` 是 `adjust_gold(-carried_gold)`
  （`kernel/rd-wasm/src/run.rs:3491`）⇒ 会**每场重复扣同一笔被偷的金币**。
* **测试的谎言比审查说的更大**：`reset_in_place_matches_new_field_for_field` 比的是 `canonical_text`，
  而这三个字段**都不在 `snapshot.rs` 里**（检索为空）⇒ 名字里的 "field for field" 不成立，它会继续
  放过下一个新字段。

修法：三字段进 `reset_scalars` + 一条"**先污染、再 reset、再逐字段精确比对**"的测试（比
`state.xxx`，不比哈希文本），原哈希测试保留为"原有契约"。

## 7.5 P2-A：覆盖矩阵 —— 一半是作者的实现 bug

* ✅ 检索确认：`if not reachable and aid in everywhere`（`native/coverage_matrix.py:174`）把
  **字符串 id 与 dict 键**比较 —— 作者在 §215 把 `everywhere` 改成按类别的 dict 之后漏改这一处，
  那个 "referenced elsewhere" 兜底**永远不成立**。今天无行为影响（动作要么在动作表、要么在
  `INV_UNWIRED`），但它是"写着检查、实际不检查"。
* ✅ 扫描器**不递归**：`kernel/rd-run/src/state/archive.rs` 的 **8 条**测试没被扫到；另有 **1 条**
  测试的 `#[test]` 与 `fn` 之间隔着 doc 注释，被 head 正则挡掉。对账：源码里 `#[test]` 共 906 处，
  其中 **4 处是注释里提到的**（`content.rs:4731` 等）⇒ 真实 902，扫到 893，缺口 9 = 8 + 1，完全吻合。
* ✅ 列名：同意拆成 `TestNamed` / `HarnessOnly` / `SourceTie(wiki|spec)` / `DeclaredDeviation`，
  表头写明"**任何一列都不声称行为正确**"。`maw.nom_nom` 就是最好的反例：有 `wiki:` 标签、变量是错的。
* **作者补充一条同类问题**：动作的 `wiki:` 是**从所属怪继承**的（有意保守），但页面上没写"继承"
  两个字，容易被读成"这条动作自己核过"。

## 7.6 P2-B：`gold_carried_away` —— 同意，这是有意的

不进参考哈希是为了不破坏 C# Oracle 的契约（§201），金额改走 `fight_end` 文本。要改的只是措辞：
**参考哈希相等 ≠ 玩法等价**。

## 7.7 一条过时的：A20 双 Boss

已实现且有测试：`kernel/rd-run/src/state.rs:5800-5822` —— 第一只倒下后 `mark_boss_beaten()` 只重开
节点、第二只才算赢；`docs/sts-wiki-gap.md` 的第 20 条也写着"有"。过时的是 `FACT.md` 的能力边界清单。

## 7.8 接下来（作者侧的排期）

* **§216**：三条 P1 一次交付 —— `Slow`（新运算 + 标记化 + 攻击卡范围 + 跨回合测试 + 负控）、
  `Nom Nom`（`roundNumber` + 真推进轮次的测试）、`reset_scalars`（三字段 + 精确字段测试）。
* **§217**：覆盖矩阵（`aid in everywhere`、递归扫描、doc 注释形状、列名与表头口径、一个"函数体只
  出现 id 但没断言行为"的对抗性夹具），然后按新扫描结果重算矩阵数字。
* **不进这两节**：卡牌 30/75 基础、遗物/事件扩充、A20 之外的内容缺口 —— 按审查建议留作观察项。
