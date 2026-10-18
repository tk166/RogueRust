# RogueDeck 战斗内核移植规格书：**出牌（Play a Card）全流程**

**依据 commit**：`fd43e68ab91f40b475b745725abb17134b951c51`（`ref/RogueDeck-Core`，MIT，**本轮只读，未修改**）
**目标读者**：要在 `kernel/rd-core/src/play.rs` 里实现"能把一张牌打出去"的人。
**范围**：从"宿主说：英雄打出手里这张牌"到"这张牌落到某个区、效果全部结算完"。**不含**效果程序解释器本身（`exec.rs` 已有）、不含回合机（`turn.rs` 已有）、不含哈希格式（见 `snapshot.rs` / `hash.rs`）。

## 0. 怎么核实的（先读这一节，否则会误信后面的表）

### 0.1 路径缩写

| 缩写 | 展开 |
|---|---|
| `C:` | `ref\RogueDeck-Core\src\RogueDeck.Core\Combat\` |
| `T:` | `ref\RogueDeck-Core\tests\RogueDeck.Core.Tests\Combat\` |
| `K:` | `kernel\rd-core\src\` |
| 镜像 | `tools\contentc\out\content.core.rdcf`（85,616 B，content hash `0xD1075DE5`），用 `tools\contentc\reader.py` 读 |

### 0.2 证据分档

全文**每一条行为断言都带 `文件:行号`**，并按证据强度分三档：

| 档位 | 含义 | 本文数量 |
|---|---|---|
| **【实跑】** | 我用 `reader.py --dump-json` / 直接按 `rdcfmt.ROW_SCHEMAS` 逐格解二进制**量出来的** | 9 条（分布在 §1.4、§3.1、§3.7、§5.3、§8.2） |
| **【读码】** | 我逐行读了 C# 源码（含测试源码），**没有运行** | 其余全部 |
| **【未验证】** | 我明确没能证实的东西 | 7 条，列在 §0.3 |

**⚠ 一条重要的方法论限制**：`ref/` 是只读的，而 `dotnet build/test` 会往 `obj/`、`bin/` 写文件，所以**本轮我没有运行任何 C# 代码**。凡是我写"参考实现抛异常/状态不变"，依据都是**源码 + 参考实现自带的测试源码**，不是我跑出来的。这与本项目历来"成品必须自己量一遍"的纪律有差距，**造对拍向量时必须自己复现这些断言**。

### 0.3 我没能验证的 7 条（必须先知道）

| # | 未验证的东西 | 为什么没能验证 | 影响 |
|---|---|---|---|
| U1 | 参考实现的**任何运行时行为**（抛/不抛、状态变/不变） | `ref/` 只读；跑 dotnet 会写 `obj/`、`bin/`（违反本轮约束） | §2、§7 的"抛"全部来自源码与测试源码 |
| U2 | `PlayCondition`（CARD 格 5）的 **term 形状**（判别串、字段名） | 镜像 62 张卡**全部** `ABSENT16`（§3.1 实测）⇒ 一条实例都没有，无从量起 | §2.2 第 3 行；要接"仅当…"型内容时必须先造一份带 PlayCondition 的内容再量 |
| U3 | `QueueOnPlay`（格 6）的 term 形状与"入队"分支的真实行为 | 同上，62/62 `ABSENT16` | §5.4 的 QueuePile 分支在本内容里**永不执行** |
| U4 | `CardDefinition.Costs` 多条目时**支付顺序**（`C:Cards\CardPlay.cs:445`、`:509` 用了 `Dictionary` 枚举序） | .NET `Dictionary` 枚举序是实现细节；镜像 62 张卡最多 1 条费用，"两种资源同时付"造不出来 | §3.5 最后一条 |
| U5 | §6.2 里"一次出牌让 `next_effect_chain_number` 增加几条"的具体条数 | 这是读码推导，没有跑一遍对拍 | ⚠ 移植若要求逐位复刻，**必须自己量**这条 |
| U6 | `action` / `queue` **标签**与 `IsAction` / `QueueOnPlay` **字段**是不是一回事 | 我在 `C:\...\Combat\` 全树 grep 不到任何读 `action` 标签的代码；但 run 层（`src/RogueDeck.Run`）我没系统排查 | §1.4；本内容里 10 张卡带 `action` 标签而 `IsAction` 全 false |
| U7 | 法令（`CombatRules`）的 term 形状 | 镜像 23 条状态**全部** `ABSENT16`（§8.2 实测）⇒ 0 条法令实例 | §8.3：整块可以先用常量实现，但这正是"静默错"的温床 |

### 0.4 顺手纠正两处冻结描述

| 冻结方描述 | 实际 | 依据 |
|---|---|---|
| "内核 `modifiers.rs` 的 `Pipeline` 只有 `DamageDealt`/`DamageReceived`/`TurnStartDraw` 三条" | **不准确**。`K:modifiers.rs:36-45` 有 **4** 条：`DamageDealt` / `DamageReceived` / `Block` / **`Cost`**。`TurnStartDraw` 不在 `modifiers.rs`，而在 `K:status_bind.rs:122-130`（3 条：`DamageDealt`/`DamageReceived`/`TurnStartDraw`） | 读码 |
| "出牌时目标解析成 `ResolvedTargets`" | **参考实现里没有名为 `ResolvedTargets` 的类型**。在 `src/RogueDeck.Core` 全树 grep `ResolvedTargets` **0 命中**。目标由 `ICombatantTargetSelector.ResolveTargets(...)` 直接返回 `IReadOnlyCollection<CombatantId>` | 读码 |

---

## 1. 入口点：**四个**面，不是一个函数

### 1.1 四个面的对照（顺序即语义，四个面行为不同）

| # | 面 | 函数 | 拒绝语义 | 谁负责排空队列 | 依据 |
|---|---|---|---|---|---|
| A | **定义面** | `CombatCardPlayProcessor.PlayCard(combat, registry, CardPlayRequest, limits?)` | **抛** | 自己 | `C:Cards\CardPlay.cs:17-33` |
| B | **实例面（严格）** | `CombatCardPlayProcessor.PlayCardInstance(..., CardInstancePlayRequest, ...)` | **抛** | 自己 | `C:Cards\CardPlay.cs:35-68` |
| C | **实例面（请求）** | `PlayCardEffectHandler` ← `PlayCardEffectRequest` | **no-op**（写 `PlayCardOutcome(WasPlayed:false)`，不抛） | **不排空**（外层正在跑的那个处理器负责） | `C:Cards\PlayCardEffects.cs:21-96` |
| D | **命令面** | `CombatReplayRunner.Apply(combat, registry, PlayCardCommand)` | 转成 C 面 ⇒ no-op | 自己 | `C:CombatReplayRunner.cs:29-36` |

**⚠ 权威游戏路径是 D → C，不是 A/B。** 依据：`C:Cards\PlayCardEffects.cs:60-63` 的注释明确写 "this is the path the host, the playtest walker and Godot all play through"；`C:CombatReplayRunner.cs:31-35` 把命令改写成 `PlayCardEffectRequest` 再排空。A/B 是给测试与编辑器用的直连面。

**A 与 B 的差别（很容易忽略）**：A 按 `CardDefinitionId` 出牌，**手里可以一张牌都没有**，因此它没有卡实例可移动、没有 per-copy 标记可消费、没有 `CardCostPaid.CardInstanceId`（`C:Cards\CardPlay.cs:31` 传 `null`）。`T:CardPlayCompletionBoundaryTests.cs:155-180` 就是钉这一点的回归测试。

### 1.2 `PlayCardCore` 的六个阶段（A/B 共用，`C:Cards\CardPlay.cs:70-109`）

| # | 阶段 | 行号 | 内容 | 拒绝时 |
|---|---|---|---|---|
| 1 | 静态守卫 | `:79-86` | `combat`/`registry` 非空；`combat.Result != Ongoing` ⇒ 抛 | **抛，状态不变** |
| 2 | 找来源 | `:88-94` | `GetCombatant`（LINQ `First`，缺人即抛 `C:CombatState.cs:240-243`）；`!source.IsAlive` ⇒ 抛 | 抛 |
| 3 | 取定义 | `:96` | `registry.GetCard(...)`，未注册即抛（`C:CombatDefinitionRegistry.cs:133-138`） | 抛 |
| 4 | **受理校验器链** | `:98-104` → `:384-402` | 按 `(Priority, ModifierId)` 升序逐个 `Validate`，任一抛即中断 | 抛 |
| 5 | **入队 + 付费 + 执行** | `:106` → `:114-294` | 见 §1.3 | 抛（算费用 / 付不起 / 程序 fault / 排空超预算） |
| 6 | 排空三队列 | `:108` | `CombatQueueProcessor.ResolvePendingQueues`（`C:CombatEventHandling.cs:81-115`） | 抛（超预算时） |

**⚠ 阶段 4 在阶段 5 之前 ⇒ 校验器看到的费用还没付、卡还在手牌、`BeginActionScope` 还没开（`:188`）。** 这条顺序是语义：`PlayConditionCardPlayValidator` 求值时 action scope 是**空的**，所以条件里若有"本次动作内只能一次"的 spec，它是抢不到 claim 的。

### 1.3 `EnqueueCardPlayEffects` 的子相位（`C:Cards\CardPlay.cs:114-294`）——**这是整块的核心**

| 子相位 | 行号 | 干什么 | 备注 |
|---|---|---|---|
| 5.1 | `:122` | `BuildEffectRequests`：把 `card.Effects`（legacy recipe 列表）展开成 `List<IEffectRequest>` | **本内容里 100% 为空**，见 §1.4 |
| 5.2 | `:123` | `CalculateCosts(..., trace: true)`：算最终费用，并往 trace 发 `CardCostResolvedTraceEvent`（`:480-486`） | 只在这里 trace（请求面的预检 `trace: false`，`:321-329`） |
| 5.3 | `:125` | `EnsureCostsCanBePaid`：资源不存在或不够 ⇒ 抛（`:514-533`） | **付得起校验在付钱之前、在任何日志/事件之前** |
| 5.4 | `:126` | `PayCosts`：逐个 `resource.SetCurrent(current - amount)`（`:535-544`） | 不退、不夹紧（§3.5） |
| 5.5 | `:130-150` | `IsAction` ⇒ 只写 `ActionUsed` 日志；否则写 `CardCostPaid` 日志 + 入队 `CardCostPaidCombatEvent`（`:138`→`:330-353`）、写 `CardPlayed` 日志（`:140-142`）、入队 `CardPlayedCombatEvent`（`:144-149`） | **⚠ 费用为 0 时整个 5.5 的 `CardCostPaid` 部分跳过**：`:337-338` 早退；测试 `T:CardCostPaidEventTests.cs:59-98` |
| 5.6 | `:160-174` | 读**并清零**卡实例上的 `standard.card_output_scale_num/den` 标记 ⇒ `(scaleNum, scaleDen)` | 只在 `cardInstanceId != null` 时；整份镜像里这两个标记的出现次数 = **0**（§3.7 实测） |
| 5.7 | `:178-183` | **清掉**本卡的 `standard.card_cost_delta` 标记（"一手价只兑现一次"） | 同上，镜像 0 命中 |
| 5.8 | `:188` | `combat.BeginActionScope()`（`C:CombatState.cs:106`） | 动作作用域的**开**点 |
| 5.9 | `:191-194` | 把 5.1 的请求逐条 `combat.EnqueueEffect(...)`，若 5.6 有缩放则先过 `CardOutputScaling.ScaleRequest` | 顺序 = `card.Effects` 列表序 |
| 5.10 | `:199-219` | **QueueOnPlay 分支**：锁目标（`:202`）、入队移到 `QueuePile`（`:203-204`）、写日志（`:205-207`）、入队续延 `CloseAction`（`:217`）、**直接 return** | 关作用域被挪到续延里（`:208-217` 的长注释记录了这个真实 bug） |
| 5.11 | `:221-282` | **程序分支**：建 build context（`:223`）、装 `onTerminal` 落区回调（`:242-263`）、`EffectProgramExecutor.Execute(...)`（`:273-281`），终态回调里先落区再 `CloseAction`（`:277-281`） | 程序**就地同步执行**（`C:Effects\Programs\EffectProgramExecution.cs:60-61`） |
| 5.12 | `:283-293` | **无程序分支**：入队移到落点（`:285-289`）、入队续延 `CloseAction`（`:292`） | 卡片"没有 Program"才走这里；**本内容 62 张卡全有 Program**（§1.4 实测） |

**⚠ 5.9 与 5.11 的相对顺序决定了队列里的先后**：legacy 效果先进队列（5.9），之后程序**就地**执行、把它自己的请求**追加**到队尾（5.11）。所以排空时 legacy 效果**先**、程序效果**后**。本内容里 legacy 为空，这条暂时无差别 —— 但它一旦被填上就会立刻变成可观察差异。

### 1.4 本内容（core 镜像）里"卡"长什么样 ——【实跑】

> 这一节是给"移植时到底要实现哪些分支"用的。**表里每一格都是我从二进制量的，不是猜的。**

| 事实 | 值 | 怎么量的 |
|---|---|---|
| CARD 表 | 62 行 × 15 格，stride 32 B | `reader.py --stats` + `rdcfmt.row_stride("CARD")` |
| **没有 `Effects` 格** | CARD schema 15 格里**根本没有 legacy effect recipe 列表**（`K:content.rs:1013-1029` 的 `CARD_SCHEMA` 逐格一致） | 读 schema |
| `extra` 格 | 62/62 = `NULL16`（0xFFFE）⇒ 也没有藏在 extra 里 | 逐格解二进制 |
| `Program` 格 | 62/62 都有；信封 = `{Id:{"Value":"(unnamed)"}, MaxNodeDepth:64, MaxProgramSteps:1024, Root}` | dump |
| 程序根节点分布 | `sequence` 43 / `applyStatus` 8 / `dealDamage` 6 / `gainBlock` 4 / `drawCards` 1 | dump |
| 空程序 | 3 张 = `red_tape`、`duplicate_copy`、`unsigned_form`（根是 `sequence{Children:[]}`）—— **仍走 5.11 程序分支**，不走 5.12 | dump |
| 卡程序里出现的节点 | 11 种：`sequence/applyStatus/dealDamage/gainBlock/drawCards/gainResource/moveCardToZone/createCardInstance/forEachCardInZone` + 表达式 `const/sel.eventTarget/sel.source/sel.allEnemies/multiply/cardInstance.iterated/combatantStatusStacks` | dump 递归统计 |
| `IsAction` | 62/62 = `0x0000`（格 8，**present 且 false**） | 逐格解二进制 |
| `PlayCondition` | 62/62 = `0xFFFF`（**ABSENT**） | 逐格解二进制 |
| `QueueOnPlay` | 62/62 = `0xFFFF`（**ABSENT**） | 逐格解二进制 |
| 带 `action` **标签**的卡 | 10 张 | dump |
| 带 `queue` **标签**的卡 | 10 张 | dump |
| 带 `unplayable` **标签**的卡 | **2** 张 | dump |
| 带 `attack` 标签的卡 | 18 张；带 `skill` 标签的卡 **0** 张 | dump |

**结论（对移植极重要）**：
1. **本内容里 legacy `Effects` 列表恒为空 ⇒ 5.1 与 5.9 是死代码，卡的全部行为都在 `Program` 里。**
2. **`IsAction` 恒 false ⇒ 5.5 的"动作"分支、`PricesActions` 分支（`:471-472`）、`DecreeCardPlayValidator` 的 `IsAction` 早退（`C:CombatDecrees.cs:144-145`）在本内容下永不触发。**
3. `QueueOnPlay` 恒 absent ⇒ 5.10 永不触发。
4. 10 张卡带 `action` **标签**、`IsAction` 全是 false —— 这两个"action"**不是同一件事**（U6 未验证 run 层是否读那个标签）。⚠ **移植时不要把标签当成 `IsAction`。**
5. 2 张 `unplayable` 卡是我能用的**唯一**"校验器真的拒了"的现成素材。
6. **4 张卡的 on-play 程序今天跑不完**：`archive_the_evidence`、`archive_the_evidence+`、`shredder_drawer`、`shredder_drawer+` 用了 `node.forEachCardInZone` + `node.moveCardToZone`，而内核 `dispatch` 的 13 个分支里**这两个都不在**（`K:exec.rs:705-720`，落到 `_ => Err(ExecError::UnsupportedNode)`；模块头也自陈"15 种里支持 13 种"，`K:exec.rs:175`）。
   ⇒ **58/62 张卡的出牌流程今天就能跑；剩下 4 张会响亮失败（不是静默错）**，这也给 `play.rs` 定下一条验收标准：这 4 张必须报 `PlayError::Effect(ExecError::UnsupportedNode)`，而不是"打出去了但什么都没发生"。

---

## 2. 受理校验（validator chain）

### 2.1 排序规则：**不是注册顺序**，是 `(Priority 升序, ModifierId 序数升序)`

| 事实 | 依据 |
|---|---|
| 注册时**立即排序**：`RegisterCardPlayValidator` 里 `_cardPlayValidators.Add(validator)` 后紧跟 `SortByPriorityThenId(...)` | `C:CombatDefinitionRegistryBuilder.cs:189-200`（Add 在 `:198`，Sort 在 `:199`） |
| 有 base registry 时 `Build()` **合并后重排** | `C:CombatDefinitionRegistryBuilder.cs:407-408`、`:438-447` |
| 比较器：`Priority` 升序；相等时 `string.Compare(id, id, StringComparison.Ordinal)` | `C:CombatDefinitionRegistryBuilder.cs:584-592` |
| 读取时**原样返回**（不再排序） | `C:CombatDefinitionRegistry.cs:155` |
| 执行：`foreach (var validator in registry.GetCardPlayValidators()) validator.Validate(context);` | `C:Cards\CardPlay.cs:400-401` |
| 重复 `ModifierId` 被拒 | `C:CombatDefinitionRegistryBuilder.cs:194-197`；测试 `T:CardPlayValidatorTests.cs:22-32` |

### 2.2 实际执行顺序（标准包 5 个校验器）

标准包注册点：`C:StandardCombatPackage.cs:59-63`（注册顺序 Unplayable→Stun→PlayCondition→OneAttackPerTurn→Decree）。
**执行顺序（升序重排后）**：

| 执行序 | 校验器 | `Priority` | `ModifierId` | 判什么 | 拒绝时抛的消息 | 依据 |
|---|---|---|---|---|---|---|
| 1 | `StunCardPlayValidator` | **100** | `standard.stun_validator` | 来源身上有没有 `standard.stun` 状态 | `Combatant '{id}' cannot play cards while stunned.` | `C:Cards\CardPlayValidators.cs:58-75`（消息 `:73-74`） |
| 2 | `DecreeCardPlayValidator` | **150** | `standard.decree_validator` | ① `MaxCardsPerTurn` 上限 ② `NoLikenessInSuccession` 标签接续；`IsAction` 直接放行 | `... may play no more than {cap} card(s) this turn by decree.` / `... may not follow a '{tag}' card with another by decree.` | `C:CombatDecrees.cs:131-176`（消息 `:155-156`、`:170-171`） |
| 3 | `PlayConditionCardPlayValidator` | **150** | `standard.play_condition_validator` | `Card.PlayCondition` 求值为 false | `'{cardId}' cannot be played or used right now.` | `C:Cards\CardPlayValidators.cs:39-56`（消息 `:54`） |
| 4 | `OneAttackPerTurnCardPlayValidator` | **200** | `standard.one_attack_per_turn_validator` | 带 `attack` 标签 + 来源有 `standard.one_attack_per_turn` + 本回合已打过 ≥1 张 attack | `Combatant '{id}' cannot play more than one attack card this turn.` | `C:Cards\CardPlayTurnValidators.cs:3-29`（消息 `:26-27`） |
| 5 | `UnplayableCardPlayValidator` | **200** | `standard.unplayable_validator` | 卡带 `unplayable` 标签 | `Card '{cardId}' is unplayable.` | `C:Cards\CardPlayValidators.cs:23-35`（消息 `:33`） |

**150 两条谁先谁后**：`string.CompareOrdinal("standard.decree_validator", "standard.play_condition_validator")` —— 公共前缀 `standard.` 之后 `'d'`(100) < `'p'`(112) ⇒ **decree 先**。
**200 两条谁先谁后**：`"standard.one_attack_per_turn_validator"` vs `"standard.unplayable_validator"` —— `'o'`(111) < `'u'`(117) ⇒ **one_attack_per_turn 先**。

### 2.3 ⚠ 参考实现的注释与它自己的实现**相反**

`C:Cards\CardPlayValidators.cs:20-22` 声称 `UnplayableCardPlayValidator`：
> "Highest priority **so it short-circuits before other checks**."

`C:CombatDecrees.cs:135` 附和：
> "Below Unplayable and Stun (200): a curse is refused for being a curse **before** a decree is consulted."

**两句话都错**：排序是**升序**（`:588` `priority(left).CompareTo(priority(right))`），`Priority 200` 是**最后**才跑的那一档。实际后果：

| 场景 | 实际报的错 | 注释预期的错 |
|---|---|---|
| 被 Stun 的玩家手里有咒卡 | `cannot play cards while stunned.` | `is unplayable.` |
| 咒卡同时被法令禁止 | 法令那条 | `is unplayable.` |

**影响面**：三条拒绝都是 `InvalidOperationException`，而**错误文本不进哈希**（§2.5），所以对"能不能打一局"与对拍**零影响**；唯一有影响的是**校验器内部有副作用**的情况 —— `PlayConditionCardPlayValidator` 要**求值一个表达式**（`:49-53`），如果某个 PlayCondition 用了会消耗随机步/claim 的表达式，顺序就变成可观察的。本内容里 PlayCondition 一条都没有（§1.4），所以今天无差别。

**移植建议**：按**真实排序**实现（`(priority, modifier_id) 升序`），并在注释里写明"参考实现的注释是错的，别照抄"。如果将来要按注释实现，必须先造一条"咒卡 + 法令"的对拍向量把它钉死。

### 2.4 三种拒绝形态（**必须分开建模，别合并**）

| 调用方 | 拒绝表现 | 依据 |
|---|---|---|
| 严格面 A/B | `Validate` **抛** `InvalidOperationException`，异常穿出 `PlayCardInstance` 给宿主 | `C:Cards\CardPlayValidators.cs:15-17`（接口 `void Validate`，"抛=拒绝"就是接口契约）；测试 `T:CardPlayValidatorTests.cs:64-71`、`T:UnplayableCardTests.cs:58-70` |
| 请求面 C | 先问 `IsCardPlayAllowed`（`try { ValidateCardPlay(...); return true; } catch (InvalidOperationException) { return false; }`），false ⇒ **静默 no-op** | `C:Cards\CardPlay.cs:365-382`；`C:Cards\PlayCardEffects.cs:64-69` |
| 前端 | 直接调 `IsCardPlayAllowed` 决定"画成禁止"还是"点了再拒" | `C:Cards\CardPlay.cs:363-364` 的注释 |

**⚠ `IsCardPlayAllowed` 只 catch `InvalidOperationException`**（`:378`）。校验器里的 `ArgumentNullException.ThrowIfNull(context)`（`:30`/`:46`/`:65`）抛的是 `ArgumentNullException`（基类 `ArgumentException`），**不会被吞**。链条永远不会传 null，所以今天不可达；但逐位复刻的人要知道"被吞的只有 `InvalidOperationException` 这一种"。

### 2.5 错误码 / 错误消息**不进哈希**

| 断言 | 依据 |
|---|---|
| 哈希输入只有 `CombatStateSnapshot` 的字段，逐行都是 `id=`/`seed=`/`step=`/`result=`/`round=`/`turn=`/`phase=`/`active=`/`status_num=`/`card_num=`/`chain_num=`/`exec_num=`/`turn_order=`/`gs=`/`c=`/`res=`/`dp=`/`s=`/`tags=`/`cnt=`/`cz=`/`tr=` 这些**前缀** | `C:CombatStateHasher.cs:26-72` |
| 战斗日志（消息文本都在这儿）**不在快照里**，所以也不在哈希里 | `C:CombatState.cs:175-184`（"log is pure observation — no rule reads it — deliberately not part of the snapshot"）；哈希器全文无 log 行 |
| 异常消息从不写入任何状态 | 全文读码，异常只 `throw` |

⇒ **拒绝路径"报什么错"完全不进哈希；进哈希的只有"拒绝了 ⇒ 状态没动 ⇒ 哈希没动"。**

---

## 3. 费用

### 3.1 来源字段 ——【实跑】

| 层 | 形状 | 依据 |
|---|---|---|
| C# | `CardDefinition.Costs`：`IReadOnlyList<ResourceCost>`，`ResourceCost(ResourceId ResourceId, int Amount)` | `C:Cards\CardDefinitions.cs:5-7`、`:18` |
| 镜像 | CARD 格 3 `Costs`（`F_TERM` 句柄），落在 term 上 | `K:content.rs:1013-1029`（`costs => 3`）、`reader.py` `rdcfmt.CARD_ROW` |
| 镜像实测 | **62 张卡全部有 `Costs` 格**：47 张 = **1 条** 费用，15 张 = 指向同一个**空列表** term（`0x3a`，解出来就是 `[]`）。这 15 张是 12 张带 `zero_cost` 标签的卡 + 3 张只带 `junk` 的咒卡（`red_tape`/`duplicate_copy`/`unsigned_form`） | 逐格解二进制 + dump |
| 单条费用的 JSON 形 | `{"Amount":1,"ResourceId":{"value":"standard.energy"}}` —— `ResourceId` 是 `F_STR` + `FLAG_WRAP_LOWER`（`{"value":…}`），`Amount` 是 `F_INT` | dump |
| 取值分布 | 资源**只有** `standard.energy`（47/47）；金额只有 **1**（38 张）与 **2**（9 张） | dump |
| **每张卡最多 1 条费用** | 条目数直方图 = `{0 条: 15, 1 条: 47}` | dump |

**这张表回答了两件事**：
1. `Costs` 是**列表**（`F_TERM` → term list），不是对象。
2. **"印刷费用为 0 的卡根本不带费用条目"**（15 张带 `zero_cost`/`junk` 标签的卡 `Costs == []`），与 `C:Cards\CardPlay.cs:495-499` 的注释完全一致 —— 所以"最低费用法令要能给 0 费卡凭空造一条费用"不是理论问题，是这份内容的真实形状。

### 3.2 对应哪条修饰器管线：**`CardCost` 是第四条**（内核已有）

| 事实 | 依据 |
|---|---|
| `PassiveModifierPipeline` 枚举有 6 条：`DamageDealt`/`DamageReceived`/`BlockGain`/**`CardCost`**/`OutgoingStatusApplicationStacks`/`TurnStartDraw` | `C:Effects\PassiveModifiers.cs:16-30`（`CardCost` 在 `:21`） |
| **费用走的是 `CardCost`** | `C:Effects\PassiveModifiers.cs:286`（`DeclarativePassiveCostModifier` 传 `PassiveModifierPipeline.CardCost`） |
| 内核侧**已经**有对应变体：`Pipeline::Cost` | `K:modifiers.rs:44` |
| ⚠ 内核的 `status_bind::Pipeline::from_wire_name` 认 **4 个串**：`DamageDealt`/`DamageReceived`/`TurnStartDraw` + **`"BlockGain"`**（格挡管线，变体名是 `Pipeline::Block`、wire 串却是参考枚举的成员名 `BlockGain`）；返回 `None` 的是 `"CardCost"`/`"OutgoingStatusApplicationStacks"`，**以及 `"Block"`** —— 那是折叠器枚举的变体名，不是 wire 串 ⇒ 调用方报 `BindError::Pipeline` | `K:status_bind.rs:166-174`（`Pipeline::Block` 在 `:149-154`；写回用的 `wire_name` 在 `:178-185`）、`C:Effects\PassiveModifiers.cs:20` |
| **本镜像里 0 条 `CardCost` spec**（`PassiveModifiers` 的 pipeline 直方图：`DamageDealt` 2 / `TurnStartDraw` 1 / `DamageReceived` 2，共 5 条） | 【实跑】dump |

⇒ **移植结论**：枚举不用动；但 `status_bind` 的那 4 条串表将来一定要扩成 6 条，否则一旦内容里出现 `"CardCost"` 的 spec，**费用会静默按印刷价结算**（`BindError` 只在真的读到那条 spec 时才出现，而阅读路径在 `status_bind` 里）。今天不挡路，因为本内容 0 条。

### 3.3 六个 cost modifier 的**执行顺序**（升序重排后）

注册点：`C:StandardCombatPackage.cs:57`（declarative）、`:65-69`（5 个）。执行：`C:Cards\CardPlay.cs:469-478`（`foreach (var modifier in registry.GetCardCostModifiers())`，`:469`）。

| 执行序 | 类 | `Priority` | `ModifierId` | 判什么 | 依据 |
|---|---|---|---|---|---|
| 1 | `FreeNextCardCostModifier` | **100** | `standard.free_next_card_cost` | 有 `free_next_card` 状态且 `Charges > 0` ⇒ 本条目归 0 | `C:Cards\FreeNextCardCostModifier.cs:3-27` |
| 2 | `FirstAttackEachTurnFreeCostModifier` | **150** | `standard.first_attack_each_turn_free_cost` | 卡带 `attack` + 有该状态 + 本回合还没打过 attack ⇒ 0 | `C:Cards\CardPlayTurnCostModifiers.cs:3-33` |
| 3 | `SkillCostReductionCostModifier` | **200** | `standard.skill_cost_reduction_cost` | 卡带 `skill` + `skill_cost_reduction` 状态层数和 ⇒ 减 | `C:Cards\SkillCostReductionCostModifier.cs:3-29` |
| 4 | `DecreeCardCostModifier` | **300** | `standard.decree_free_nth_card` | 本回合第 `Amount` 张 ⇒ 0（`spec.Amount == played + 1`） | `C:CombatDecrees.cs:181-203` |
| 5 | `DeclarativePassiveCostModifier` | **1000** | `standard.declarative_card_cost` | 折叠所有 `CardCost` 规格（含 `OncePerTurn` claim） | `C:Effects\PassiveModifiers.cs:271-290` |
| 6 | `CardInstanceCostModifier` | **1100** | `standard.card_instance_cost` | 卡实例上的 `standard.card_cost_delta` 标记 | `C:Cards\CardInstanceCostModifier.cs:13-34` |

**⚠ 三条由顺序决定的真实后果**（读码推导，未实跑）：
1. **"第 N 张免费"（300）会被 declarative（1000）重新加价**：法令把它归 0 之后，一条 "全部卡 +1" 的 passive 会在 `:474` 之后把它变成 1。**"免费"于是不免费** —— 除非那条 passive 是 `AddFlat -1`。
2. **skill 减免（200）先于法令（300）**：减免到 0 之后，法令的 `if (currentAmount <= 0) return currentAmount;`（`C:CombatDecrees.cs:191-192`）早退 ⇒ 法令那张"免费"名额**不会被消耗**（它只看值，不看卡）。这是"免费额度被无形浪费"的形状。
3. **`IsAction` 只跳过不声明 `PricesActions` 的 modifier**（`:471-472`）：`DeclarativePassiveCostModifier` 声明 `PricesActions => true`（`C:Effects\PassiveModifiers.cs:278`）但内部再加 `onlyCardTagged: context.Card.IsAction`（`:288`）⇒ 动作只吃"按标签命名动作"的 spec。其余 5 个 modifier 的 `PricesActions` 默认 `false`（`C:Cards\CardCostModifiers.cs:29`）⇒ **动作完全不吃 free_next / first_attack / skill 减免 / 法令 / 卡实例价**。

### 3.4 取整 / 夹紧规则（逐条，**顺序敏感**）

| 步骤 | 规则 | 依据 |
|---|---|---|
| 1 | 逐条目取 `cost.Amount`；**`< 0` 立即抛** `Card '{id}' has a negative cost for resource '{rid}'.` | `C:Cards\CardPlay.cs:447-453` |
| 2 | 逐 modifier 折叠，**每过一个 modifier 就夹一次 `Math.Max(0, …)`** | `:474`（`var after = Math.Max(0, modifier.ModifyCostAmount(context, before));`） |
| 3 | 结果 `== 0` ⇒ **丢弃这个条目**（不进最终费用表） | `:488-489` |
| 4 | 同资源多条目 ⇒ `checked(current + modified)` 累加 | `:491-492` |
| 5 | 法令 `MinimumCardCost` 兜底：对每个在效 spec，若该资源已付额 `< Amount` ⇒ 直接**赋**值 `Amount`（能凭空造条目） | `:501-507` |
| 6 | 转成 `CalculatedResourceCost[]` 返回 | `:509-511` |

**⚠ 夹紧是"每个 modifier 之后"，不是"最后夹一次"。** 例：`printed 1 → (-99) → max(0,-98)=0 → (+5) = 5`，而"最后夹一次"会给 `max(0, 1-99+5)=0`。两者差 5。测试 `T:CardCostModifierTests.cs:120-150` 只钉了"单条 -99 ⇒ 费用 0 能打"这一半。

**⚠ "整数除法向零截断"**：`ScalePercent` 是 `current * magnitude / 100`（`C:Effects\PassiveModifiers.cs:210`），C# 与 Rust 的 `/` 对正数一致；负数在 `:216` 被 `Math.Max(0, …)` 兜住，所以不需要关心截断方向。内核 `K:modifiers.rs:54` 已按此实现。

### 3.5 欠费 / 超额 / 负数费用

| 情形 | 行为 | 依据 |
|---|---|---|
| **欠费** | `EnsureCostsCanBePaid` 抛 `Combatant '{id}' cannot pay {n} '{res}' for card '{card}'.`，**在付款之前**，状态不变 | `C:Cards\CardPlay.cs:125`、`:527-531`；测试 `T:CombatCardPlayProcessorTests.cs:76-109`（连日志都是空的，`:106`） |
| **资源池根本不存在** | 抛 `Combatant '{id}' does not have resource '{res}'.` | `:521-525` |
| **超额（付得起，付完有剩）** | 允许；付完就是付完，**不夹到上限、不退**（`SetCurrent` 直接减） | `:535-544` |
| **费用被 modifier 改成负数** | **不会发生**：`:474` 每步夹 0 | `:474` |
| **印刷费用是负数** | **抛**（配置错误，不是运行时兜底） | `:449-453` |
| **费用 0 / 无条目** | 允许；不产生 `CardCostPaid` 事件与日志（`:337-338`），`ResourceSpentThisTurn` 不加（`C:Cards\CardPlayTurnStats.cs:365-381` 的注释与 `:159-169`） | 读码 + 测试 `T:CardCostPaidEventTests.cs:59-98` |
| **同资源两条费用** | 先各自过 modifier 与夹紧，再累加；不够付 ⇒ **整张牌拒绝**（不是只付一条） | `:491-492`、`:514-533`；测试 `T:CardCostModifierTests.cs:152-193`（2+2=4 > 3 ⇒ 抛，能量留在 3） |
| ⚠ **支付顺序** | 返回列表来自 `Dictionary<ResourceId,int>` 的枚举序（`:445`、`:509-511`）⇒ **.NET 实现细节**；`CardCostPaidCombatEvent.Costs` 的数组顺序同理 | **U4 未验证**；镜像里 62 张卡最多 1 条费用，造不出反例 |

### 3.6 有没有 "X 费"

**引擎里没有 X 费这个东西。** 证据：

| 断言 | 依据 |
|---|---|
| `CardDefinition` 没有 `IsX`/`XCost`/`CostX` 之类字段 | `C:Cards\CardDefinitions.cs:11-78` 全文 |
| `src/RogueDeck.Core` 全树 grep `XCost`（区分大小写）**0 命中** | 读码 |
| 唯一的提及是测试注释：X 费用**内容**实现 = "读当前能量作为效果量 + `LoseResource` 把能量丢光"两个节点 | `T:XCostCardTests.cs:5-8`（程序在 `:26-31`） |
| 因此 X 费**不需要出牌流程支持**：它是一张费用为 0（或普通价）的卡，靠程序自己读能量 | 同上 |

**移植结论**：`play.rs` 不需要任何 X 分支。但要注意 `T:XCostCardTests.cs:49-61` 钉的那条边界：**0 能量时 X 费卡的 X = 0，效果量为 0 但仍是一次合法的程序执行**。这条测试是**直接跑程序**（`:57-58`）而不是走出牌路径，所以"0 能量时费用校验仍然放行"是我从"费用为 0 / 无费用条目 ⇒ 不产生费用 ⇒ 必然付得起"（§3.5）**推出来的，不是它测出来的**。

### 3.7 本内容下的实际费用（【实跑】+ 读码）

| 观察 | 值 |
|---|---|
| 47 张卡的印刷费用 | 1 或 2 能量 |
| 15 张卡 | 无费用条目（`[]`） |
| `skill` 标签的卡 | **0 张** ⇒ `SkillCostReductionCostModifier` 永不生效 |
| `CardCost` 的 declarative spec | **0 条** ⇒ `DeclarativePassiveCostModifier` 恒返回原值 |
| `standard.card_cost_delta` 标记在整份镜像里的出现次数 | **0** ⇒ `CardInstanceCostModifier` 永不生效 |
| `CombatRules` | **0 条** ⇒ `DecreeCardCostModifier` + `MinimumCardCost` 永不生效 |

⇒ **这份内容的有效费用 = 印刷费用**。`free_next` / `first_attack` 只在战斗中途被状态激活时才生效（那不是内容静态数据）。

---

## 4. 目标（Target）

### 4.1 怎么传进来

| 面 | 入参 | 依据 |
|---|---|---|
| B/C | `CardInstancePlayRequest.TargetCombatantId` / `PlayCardEffectRequest.TargetCombatantId`，类型 `CombatantId?`，**单个**，可空 | `C:Cards\CardPlay.cs:8-11`、`C:Cards\PlayCardEffects.cs:14-19` |
| D | `PlayCardCommand.TargetCombatantId`，同上 | `C:CombatCommands.cs:9-13` |
| A | `CardPlayRequest.TargetCombatantId` | `C:Cards\CardPlay.cs:3-6` |

**没有目标数组、没有 ResolvedTargets。宿主一次只能指定一个目标**（§0.4 已纠正）。

承载方式：把 `targetCombatantId` 塞进 `TriggeredEffectActionBuildContext.TargetSelectionContext.EventTargetId`：

```csharp
// C:Cards\CardPlay.cs:404-418
new TriggeredEffectActionBuildContext(
    new CombatantTargetSelectionContext(Combat, Source: source, EventTargetId: targetCombatantId),
    new TriggeredEffectActionSource(SourceCombatantId: source.Id, SourceCardId: cardDefinitionId));
```

### 4.2 什么时候解析成具体目标 —— **两条路不同**

| 路径 | 解析时机 | 依据 |
|---|---|---|
| **legacy `card.Effects` 列表** | **建请求时就解析**（即 §1.3 的 5.1，付款之前）：每个 recipe 调 `TargetSelector.ResolveTargets(buildContext.TargetSelectionContext)`，**每个解出的目标生成一条 effect request** | `C:Cards\CardEffectDefinitionHandlers.cs:46`、`:83`、`:119`、`:189`、`:226`、`:259`（各 recipe 一致）；入口 `C:Cards\CardPlay.cs:420-434` |
| **`card.Program`（本内容的唯一路径）** | **节点执行时解析**：`sel.eventTarget` / `sel.source` / `sel.allEnemies` 等在选择器节点执行的那一刻读 `ExecContext.event_target` | 参考侧在 `C:Effects\Programs\EffectProgramNodeExecutors.cs`；内核侧同语义在 `K:exec.rs`（`ExecContext.event_target`，`K:exec.rs:242-252`） |

⇒ **"出牌时解析一次"只对 legacy 路径成立；对程序路径，目标是"随时读"的。**

### 4.3 目标非法 = 空集，**不是拒绝出牌**

| 断言 | 依据 |
|---|---|
| `EventTarget` 选择器在 `EventTargetId == null` / 该单位不存在 / **该单位已倒下** 时返回**空集合** | `C:Effects\CombatantTargetSelectors.cs:113-134`（三处早退：`:122-123`、`:127-128`、`:130-132`） |
| 空集合 ⇒ `BuildEffectRequests` 的 `.Select(...)` 产出 **0 条**请求 ⇒ 这个效果静默什么也不做 | `C:Cards\CardEffectDefinitionHandlers.cs:48-53` 等 |
| 程序路径同理：目标解出空集 ⇒ 0 次伤害（参考侧逐目标枚举；内核 `K:exec.rs` 同层，**未逐行核对**） | `C:Effects\Programs\EffectProgramNodeExecutors.cs` |
| **出牌路径上没有任何一处校验目标合法性** | `C:Cards\CardPlay.cs:70-109`（阶段 1-6 全文无目标检查），`C:Cards\CardPlayValidators.cs` 全文无目标检查 |

**⚠ 结论：参考实现里不存在"目标非法 ⇒ 拒绝出牌"这条规矩。** 一张需要目标的牌，在 `target = null` 时**照样被受理、照样付费、照样进弃牌堆**，只是什么事都没发生（除了 `CardPlayed`/`CardCostPaid` 照样 fire）。
**移植时若自己加一条"目标非法就拒绝"，会与参考产生**（a）不同的费用扣除（b）不同的 `cards_played_this_turn`（c）不同的哈希。这是最容易被"善意加固"破坏的一条。

### 4.4 多目标上限：**无**

| 断言 | 依据 |
|---|---|
| `AllEnemiesOfSourceCombatantTargetSelector` 返回**全部**活着且异队的单位，无 `Take(n)` | `C:Effects\CombatantTargetSelectors.cs:154-169` |
| `AllAlliesOfSourceCombatantTargetSelector` 同理 | `:136-152` |
| 只有"最低/最高血量"这一类才会 `.Take(1)` | `:347`（`LowestHealth…`） |
| 每次 Build 为**每个**目标生成一条请求，因此一次出牌的效果请求条数 = Σ(各 recipe 的目标数) | `C:Cards\CardEffectDefinitionHandlers.cs` 各 `.Select(...).ToArray()` |
| 本内容里 `sel.allEnemies` 在卡程序里出现 **6** 次（AOE 卡） | 【实跑】dump 统计 |

⇒ 上限由"场上活人数量"与"请求条数"间接决定，出牌流程**自己不加任何上限**。移植侧的定容容器（`Bounded`）是唯一硬上限，**撞上限必须响亮报错**（`K:state.rs:186` 的 `CapacityError`），不能静默截断 —— 截断会静默少打一个目标。

---

## 5. 卡的去向

### 5.1 先纠正一个常见误解：**没有 in-play 区**

| 断言 | 依据 |
|---|---|
| `CardZone` 只有 7 个成员：`DrawPile`/`Hand`/`DiscardPile`/`ExhaustPile`/`BanishedPile`/`QueuePile`/`SetAsidePile` | `C:Cards\CardZones.cs:3-22`；内核同序 `K:state.rs:480-490`（含 `wire_name`：`draw/hand/disc/exh/ban/queue/aside`，`K:state.rs:513-523`） |
| **出牌期间卡一直留在 `Hand`**，直到它的 on-play program 走到终态 | `T:CardPlayCompletionBoundaryTests.cs:21-57`（`:51` 断言"程序第 1 步处理伤害时卡仍在 `Hand`"，`:54` 断言程序跑完才在 `DiscardPile`） |
| "in-play 区"这个词在参考实现里不存在（`grep -i inplay/in_play` 0 命中） | 读码 |

⇒ **不要新增 `InPlay` 区**。新增会改变 `cz=` 段的哈希行（`C:CombatStateHasher.cs:121-135` 逐区写 `draw/hand/disc/exh/ban/queue/aside`），从而与参考的规范文本对不上。

### 5.2 时间线 + 三个终态（**逐位必复刻**）

```
宿主出牌
  └─ 卡仍在 Hand（全程）
     ├─ 程序 Completed  ⇒ 入队 MoveCardToZone(卡 → 落点)    [C:Cards\CardPlay.cs:249-253]
     ├─ 程序 Faulted    ⇒ 直接 zones.MoveCardToZone(卡 → 落点)，写一条 "…after its on-play program faulted." 日志   [:254-261]
     └─ 程序 Cancelled  ⇒ 什么都不做（战斗已结束，卡留在 Hand）  [:240-241]、[:262]
```

| 终态 | 触发条件 | 落区手段 | 依据 |
|---|---|---|---|
| `Completed` | 程序跑完 | **入队**一条 `MoveCardToZoneEffectRequest`（走效果队列 ⇒ `CardMovedToZone` 事件与日志在队列里 fire） | `:249-253` |
| `Faulted` | 程序抛 | **直接** `zones.MoveCardToZone(...)` 绕开队列（队列在 fault 之后不会再排空） | `:254-261` |
| `Cancelled` | 程序执行中途战斗结束（`SetResult` 会取消所有在飞帧，`C:CombatState.cs:358-359`） | 不动 | `:240-241`、`:262`；测试 `T:CardProgramTerminalCleanupTests.cs:62-78`（`:75` 结果 Victory、`:77` 卡仍在 `Hand`） |

**终态回调里的前置守卫**（`:244-247`）：先查"卡还在这些 zone 里"且"它的 `Zone` 仍是 `Hand`"，否则**直接 return**（不移动）。这条让"程序自己把卡挪走了"的卡不被二次搬动 —— 测试 `T:CardPlayCompletionBoundaryTests.cs:90-121`。

**⚠ "先入队再移动" vs "直接移动" 是可观察差异**：入队路径会 fire `CardMovedToZoneCombatEvent`（`C:Effects\CardZoneEffects.cs:207-211`）与日志（`:203-205`），直接移动只写日志（`:257-260`）**不 fire 事件**。所以 faulted 的落区**不会**触发"牌进入弃牌堆"类触发器。

### 5.3 落点怎么定

```csharp
// C:Cards\CardPlay.cs:298-302
internal static CardZone PlayedCardDestination(registry, source, card) =>
    CombatDecrees.Any(registry, source, CombatRule.PlayedCardsExhaust)
        ? CardZone.ExhaustPile
        : card.PlayedCardDestinationZone;
```

| 事实 | 依据 |
|---|---|
| 默认落点 = `CardDefinition.PlayedCardDestinationZone`，构造默认 `DiscardPile` | `C:Cards\CardDefinitions.cs:32`、`:106` |
| 法令 `PlayedCardsExhaust` 覆盖成 `ExhaustPile`（从**出牌者**身上读，不是从卡的主人） | `C:CombatDecrees.cs:46`、`C:Cards\CardPlay.cs:298-302` |
| 镜像实测：**`DiscardPile` 48 张 / `ExhaustPile` 14 张**，格 13 是 `F_STR` 存**枚举名原文** | 【实跑】逐格解二进制 + dump |
| 与 `exhaust` 标签数量（14）一致 | 【实跑】dump |
| `TurnEndHandDestinationZone` 62/62 = `DiscardPile`；`RetainInHandOnTurnEnd` 62/62 = false | 【实跑】 |
| 若卡没有 Program ⇒ 落区走 `:285-289`（**入队**移动，和 Completed 同形） | `C:Cards\CardPlay.cs:283-293` |

⚠ **镜像里 14 张 `ExhaustPile` 卡**是"出牌路径把牌送进消耗堆"的现成素材：这是**唯一**能验证"落区"字段的向量。**`PlayedCardDestinationZone` 是枚举名字符串**（`"DiscardPile"`/`"ExhaustPile"`/`"BanishedPile"`…），内核 `K:content.rs` 已能读格 13，但**从串到 `CardZone` 的映射还需要一层**（内核 `CardZone::wire_name` 给的是短名 `disc`/`exh`，不是枚举名）— 读码。

### 5.4 `QueueOnPlay` 的特殊形状（本内容不触发）

| 步骤 | 依据 |
|---|---|
| 付完费、fire 完 `CardPlayed`/`CardCostPaid`、**把选中的目标锁到实例上**（`SetQueuedTarget`） | `C:Cards\CardPlay.cs:202`；`C:Cards\CardZones.cs:82-84` |
| 入队一条 `MoveCardToZoneEffectRequest(source, instance, CardZone.QueuePile)` | `:203-204` |
| 入队续延 `CloseAction`（关动作作用域） | `:217` |
| **return**（不跑程序） | `:218` |
| 之后在"所有者下个回合开始、触发器之后、抽牌之前"由 `QueueResolution.ResolveOldest(...)` 跑程序 | `C:Cards\QueueResolution.cs:14-38`；窗口注册在 `C:Cards\QueueResolution.cs:133-138`（`ResolveQueueOnTurnStartedHandler`），注册顺序见 `C:StandardCombatPackage.cs:131` |
| 解析**不是第二次出牌**：不付费、不 fire `CardPlayed`、不过校验器 | `C:Cards\QueueResolution.cs:6-8` 注释 |
| 解析完落区仍过 `PlayedCardDestination`（法令也生效），并清掉锁 | `:116-128` |
| 目标在窗口到来前离场 ⇒ 目标绑定的部分**哑火，不重选目标** | `:66-70` |

**本内容 `QueueOnPlay` 62/62 ABSENT（U3）⇒ 本节无法实测。** 移植建议：先把 `QueuePile` 当作"永远空的区"实现（哈希里 `queue=` 段只在非空时写，`C:CombatStateHasher.cs:128-131`），等有带 `queue` 标志的内容再补 —— **不要**因为 10 张卡带了 `queue` **标签**就以为它们会进队列（U6）。

### 5.5 具体方法名（移植对照表）

| 动作 | 参考实现 | 内核现状 |
|---|---|---|
| 取某人牌区 | `CombatState.GetCardZones(id)`（先 `TryGetCombatant`，缺人抛） | `K:state.rs` `card_zones(...)` 返回 `Option` |
| 找卡 | `CombatantCardZones.GetCard(id)`，找不到抛 `Card instance '{id}' does not exist in these card zones.` | `K:state.rs:2021` `ZoneCards` |
| 有这张卡吗 | `ContainsCard(id)`（线性扫全部 7 个区） | 有 |
| 加卡 | `AddCard(card)`（重复 id 抛） | `K:state.rs:1832` `push_card`（定容 + `CapacityError`） |
| **移区（唯一入口）** | `CombatantCardZones.MoveCardToZone(id, zone, placement = Bottom)`：**按 id 在 7 个区里找** → `RemoveFromCurrentZone` → `SetZone` → 目标区 `Add`/`Insert(0)`；找不到 id 抛 | 内核已有 `K:state.rs:1902-1930` `move_card(owner, from, to, slot, placement)`，**但要传 `from`，且"卡不在 `from`"返回 `Ok(false)` 而不是抛**（`K:state.rs:1896-1897`、`:1922-1924`）—— 调用方必须自己先定位 `from`，否则会静默当成 no-op |
| 效果层的移区 | `MoveCardToZoneEffectHandler`（校验 `OwnerId == CombatantId`，同区同 placement=`Bottom` 时**不动**） | **需新写**：`K:exec.rs` 的 `dispatch` **不分派** `moveCardToZone`（`K:exec.rs:705-720` 落到 `Err(UnsupportedNode)`），只有字符串 `ToZone` 的解析函数在 `K:exec.rs:1434-1442` |
| 抽牌 | `CombatantCardZones.DrawCards(count)` | `K:state.rs:1936` `draw_card` |

**⚠ `MoveCardToZone` 的三个易错点**（`C:Cards\CardZones.cs:212-223`、`C:Effects\CardZoneEffects.cs:187-195`）：
1. `ZonePlacement.Top` 会 `Insert(0)` —— 对弃牌堆也生效，不只是抽牌堆（`C:Cards\CardZones.cs:219-222`）。
2. **同区移动 + `Bottom` = 完全不动**（`C:Effects\CardZoneEffects.cs:187` 早退，且 outcome 写 `WasMoved:false`）；同区 + `Top` 会挪位置。
3. 移动**不 fire** 任何事件本身；事件在 handler 里 fire（`:207-211`）。

---

## 6. 状态机影响：一次出牌动了哪些编号

### 6.1 逐一核对

| 字段 | 一次普通出牌（本内容形态：有 Program、无 legacy Effects、无 QueueOnPlay、无缩放/费用标记） | 依据 |
|---|---|---|
| `current_round` / `current_turn` | **不动**（出牌不是回合边界） | `C:Cards\CardPlay.cs:70-294` 全文无 `AdvanceTurn`/`AdvanceRound` |
| `turn_phase` / `result` | **不动**（除非卡的效果自己 `SetResult`） | 同上 |
| `active_combatant_id` | **不动**；⚠ 也**不校验**（§7） | 同上 |
| **`random_step`** | **出牌框架本身不动**。只有卡的效果可能推进：全树 7 个 `AdvanceRandomStep()` 调用点 = `C:Effects\CardZoneEffects.cs:69`（抽牌重洗）、`C:Effects\ResourceSelection.cs:65`、`C:Effects\StatusSelection.cs:88`、`C:Effects\Programs\EffectProgramExpressions.cs:1929`/`:1953`/`:2050`、`C:Effects\Programs\EffectProgramNodeExecutors.cs:539`（定义在 `C:CombatState.cs:675-677`） | grep（读码） |
| **`next_card_instance_number`** | **不动**。只有 `createCardInstance` 效果处理器调 `CreateNextCardInstanceId()`（`C:Effects\CardCreationEffects.cs:36`）；本内容 62 张卡里有 **12** 处 `node.createCardInstance` ⇒ 那些牌**会**动它 | grep（读码）+ 【实跑】节点直方图 |
| **`next_status_instance_number`** | 出牌框架**不动**；只有状态施加路径（`C:Effects\StatusEffects.cs:184`、`:721`） | grep（读码） |
| **`next_effect_chain_number`** | **会动**，见 §6.2 | `C:CombatState.cs:545-555` |
| **`next_program_execution_id`** | **会动 +1**（有 Program 时）。`EffectProgramExecutor.Execute` 一进来就 `combat.AllocateProgramExecutionId()` | `C:Effects\Programs\EffectProgramExecution.cs:25-28`、`C:CombatState.cs:513-518` |
| `next_summoned_combatant_number` | 不动（出牌不召唤） | — |
| action 作用域 | 开 1 次（`:188`）、关 1 次（`:217` 续延 / `:280` 程序终态 / `:292` 续延） | `C:CombatState.cs:106`、`:110-119` |
| **卡牌回合统计** | `CardsPlayedThisTurn++`、`LastCardPlayedDefinitionId`、按定义/标签计数、整场计数——由 `CardPlayedCombatEvent` 的处理器 `TrackCardsPlayedThisTurnHandler` 做 | `C:Cards\CardPlayTurnStats.cs:278-294`（handler）、`:118-147`（`RecordCardPlayed`） |
| `ResourceSpentThisTurn` | 由 `CardCostPaidCombatEvent` 的处理器累加**实际付出额**（0 费不加） | `C:Cards\CardPlayTurnStats.cs:368-382` |
| 战斗日志 | 至少 `CardPlayed` 一条（非动作）；有费用时加 `CardCostPaid`；落区时加 `CardMovedToZone` | `:140-142`、`:344-346`、`C:Effects\CardZoneEffects.cs:203-205` |

### 6.2 ⚠⚠ `next_effect_chain_number`：**两条入口对同一次出牌给出不同的值**

规则：`CreateRootEffectChain()` 才 +1（`C:CombatState.cs:545-555`），而它只在**没有环境链**时被调用：

```csharp
// C:CombatState.cs:386-391   EnqueueEffect
var chain = CurrentEffectChain ?? CreateRootEffectChain();
// C:CombatState.cs:446-451   EnqueueEvent
var chain = CurrentEffectChain ?? CreateRootEffectChain();
// C:Effects\Programs\EffectProgramExecution.cs:31
executionContext.EffectChain ??= combat.CurrentEffectChain ?? combat.CreateRootEffectChain();
```

`CurrentEffectChain` 只在 `using (combat.EnterEffectChain(...))` 内非空（`C:CombatState.cs:500-511`）。

| 入口 | 出牌时是否在环境链内 | 后果 |
|---|---|---|
| **A/B（宿主直连）** | **否**（`PlayCardCore` 不在任何 `EnterEffectChain` 里） | 出牌过程中**凡是在"没有环境链"的时刻发生的** `EnqueueEffect`/`EnqueueEvent` 各造一条新根链 ⇒ 每条 **+1**。本内容形态下的候选者是：`CardCostPaid` 事件（**仅费用 > 0** 时，`:138`）、`CardPlayed` 事件（`:144`）、程序自己那条链（`C:Effects\Programs\EffectProgramExecution.cs:31`）。程序**内部**的入队与程序终态回调里的落区入队都在 `EnterEffectChain` 范围内（`:60-61`），因此**复用、不新增**。⚠ **确切条数我没有实跑（U5）**，以上是推导；要用必须自己量 |
| **C/D（请求面，游戏真实路径）** | **是** —— `ResolvePendingEffects` 里 `using (combat.EnterEffectChain(entry.EffectChain)) { _resolver.Resolve(...) }`（`C:CombatEffectQueueProcessor.cs:32-33`） | 全部**复用**外层那条链 ⇒ **+0** |

⇒ **同一次出牌，通过 A/B 和通过 C/D，`chain_num` 不同 ⇒ `CombatStateHasher.cs:38` 那一行不同 ⇒ 哈希不同。** 也就是说**这两个入口不是"同一件事的两种写法"**，它们产生不同的规范文本。

**这是本文最该被对拍钉死的一条（U5：条数我没实跑）。** 移植侧若只实现一条入口，必须选 **C/D**（游戏真实路径），并明确记录"A/B 面的 `chain_num` 行为不实现"。

### 6.3 哈希层面：哪些"必须变 / 必须不变"

> 本节只说"必须变什么"，不重复哈希格式（那在 `snapshot.rs`/`hash.rs`）。

| 组 | 字段 | 依据 |
|---|---|---|
| **必须变**（若真的出牌了） | `hand=`/`disc=`/`exh=`/`queue=` 段（`cz=` 行）、`exec_num=`（`C:CombatStateHasher.cs:39`）、`chain_num=`（`:38`，条数见 §6.2）、`res=standard.energy …` 行（付费用）、战斗员 `hp=`/`dp=`（若卡造成伤害/格挡）、`s=`（若卡施加状态）、`card_num=`（**仅**当卡的效果造卡时，`:37`） | `C:CombatStateHasher.cs:26-72`、`:121-164` |
| **必须不变** | `id=` / `seed=` / `step=`（除非效果用了随机）/ `result=` / `round=` / `turn=` / `phase=` / `active=` / `status_num=`（除非施加状态）/ `turn_order=` | 同上；`:28-44` |
| **变了也不进哈希** | `CardsPlayedThisTurn`、`CardsPlayedLastTurn`、`LastCardPlayedDefinitionId`、按定义/标签计数、`CardDrawsThisTurn`、`ResourceSpentThisTurn`、`once-per-turn` claims、以及 `_actionScopes` | 快照**有** `CardPlayTurnStats`（`C:CombatStateSnapshot.cs:139`、`:160-162`）但哈希器**逐行不含**（`C:CombatStateHasher.cs:26-72` 全文）；`_actionScopes` 注释明说"deliberately not part of the snapshot or the state hash"（`C:CombatState.cs:95`） |

**⚠ 这条是"对拍会绿、规则会错"的经典陷阱**：法令 `MaxCardsPerTurn` / `NoLikenessInSuccession` / `NthCardOfTurnIsFree` 全部只读 `CardPlayTurnStats`，而它**不进哈希**。所以"出牌统计算错"这种 bug 对拍 100% 通过（本项目已有同类教训：`docs/spec/combat-state-and-turn.md:453` 记了同一个坑）。
⇒ 移植侧**必须**为 `CardsPlayedThisTurn`/`LastCardPlayedDefinitionId` 单独写断言，不能靠哈希。

---

## 7. 失败路径：返回什么 + 状态是否不变

### 7.1 全表

| 情形 | 严格面 A/B | 请求面 C（游戏路径） | 状态是否"逐字节不变" | 依据 |
|---|---|---|---|---|
| **战斗已结束**（`Result != Ongoing`） | 抛 `Cannot play card because combat result is '{r}'.` | **no-op**（`WasPlayed=false`）—— 请求处理器**没有**这条检查，靠外层队列循环 `while (… && Result == Ongoing)` 停下来不让它跑 | 是（§7.2 除外） | `C:Cards\CardPlay.cs:82-86`、`C:Cards\PlayCardEffects.cs:28-32`、`C:CombatEventHandling.cs:97` |
| **来源已倒下 / 不存在** | 抛 `…cannot play cards because it is not alive.` / LINQ `First` 抛 | no-op（`TryGetCombatant` + `IsAlive`，`:28-32`） | 是 | `:88-94`、`:28-32` |
| **卡定义未注册** | `registry.GetCard` 抛 | 走 `registry.GetCard`（`:50`）⇒ **会抛**（⚠ 请求面在这一点上不 no-op） | 是 | `C:CombatDefinitionRegistry.cs:133-138`、`C:Cards\PlayCardEffects.cs:50` |
| **卡实例不存在** | `zones.GetCard` 抛 `Card instance '{id}' does not exist in these card zones.` | no-op（先 `zones.ContainsCard`，`:36-40`） | 是 | `C:Cards\CardZones.cs:192-200`、`:36-40` |
| **卡不在手牌**（在别的区） | 抛 `Card instance '{id}' cannot be played because it is in zone '{z}'.` | no-op（`:44-48`） | 是 | `C:Cards\CardPlay.cs:54-58`、`:44-48` |
| **卡不属于该来源** | 抛 `Card instance '{id}' is not owned by combatant '{c}'.` | 隐式 no-op（`GetCardZones(player)` 只搜那个人的区 ⇒ `ContainsCard` false） | 是 | `:48-52`、`C:Cards\PlayCardEffects.cs:34-40` |
| **校验器拒绝**（Stun/Unplayable/PlayCondition/法令/一回合一次攻击） | 抛（消息见 §2.2） | no-op（`IsCardPlayAllowed` 吞掉，`:64-69`） | 是 | §2.4 |
| **资源池不存在** | 抛 `…does not have resource '{res}'.` | no-op（`:74-82` 的预检用 `TryGetValue`） | 是 | `:521-525`、`:76-81` |
| **付不起** | 抛 `…cannot pay {n} '{res}' for card '{id}'.` | no-op（`:74-82`） | 是（含日志：`T:CombatCardPlayProcessorTests.cs:106` 断言 `CombatLog` 为空） | `:527-531` |
| **印刷费用为负 / 定义损坏** | 抛（`:449-453`） | 预检 `CalculateCostsInternal` 也会抛（`:71-72` → `:321-329`） | 是 | 同左 |
| **不是当前行动者** | **⚠ 没有任何校验 ⇒ 会被接受** | 同样接受 | **不适用（成功出牌，状态会变）** | `C:Cards\CardPlay.cs:70-109` 全阶段无 `ActiveCombatantId` 检查；同一结论已由 `docs/spec/combat-state-and-turn.md:37` 记录 |
| **目标非法** | **不拒绝**（§4.3）⇒ 成功出牌、效果哑火 | 同 | 不适用 | §4.3 |
| **效果执行超预算** | 抛 `Stopped resolving pending effects after reaching the limit of …` | 抛（外层循环） | **否** —— 已经做了一半 | `C:CombatEffectQueueProcessor.cs:22-26`、`:99-102`；`C:CombatExecutionLimits.cs:11-14`（默认 1024/1024/1024） |
| **程序抛异常（Faulted）** | 异常穿出，但卡**已被移到落点** | 同 | **否**（卡已落区，可能已付费） | §5.2 |

### 7.2 ⚠ 三处"看起来零副作用、实际不是逐字节不变"

| # | 事实 | 依据 |
|---|---|---|
| 1 | **校验器链会顺手创建一个 `CardPlayTurnStats` 条目**：`DecreeCardPlayValidator`/`OneAttackPerTurnCardPlayValidator` 调 `GetCardPlayTurnStats`，而这个 getter **在缺失时 `Add` 一个空对象** | `C:CombatState.cs:265-277`（`:270-274` 就是 `TryGetValue` 失败后 `new` + `Add`）；`C:CombatDecrees.cs:152`、`:162`、`:194` |
| 2 | **`BuildEffectRequests` 在付得起校验之前跑**（`:122` 早于 `:125`）：若某个 legacy recipe 的 `Build` 有副作用（例如解析目标时选牌/消耗 chooser），失败路径就不再是零副作用 | `C:Cards\CardPlay.cs:122-125`。我没有逐条排查全部 recipe 的 `Build` 是否纯净（**读码未穷尽**） |
| 3 | **`GetCardZones` 会在缺人时抛**，但**不会**创建条目（`CardZonesByCombatant[id]` 是索引器读）；所以这条是无副作用的 | `C:CombatState.cs:258-264` |

⇒ 严格说：**失败路径"哈希不变"成立，"逐字节不变"不成立**（会多一个空 turn-stats 条目）。但那个条目**不进哈希**（§6.3）⇒ 对拍看不出来，**只有快照 JSON 对比能看出来**。移植侧若做 snapshot 级对拍，必须复刻"读 stats 会创建条目"这个副作用；若只做哈希对拍，可以省略（并记录为有意偏离）。

### 7.3 `IsCardPlayAllowed` 是**答案的唯一权威**

`C:Cards\CardPlay.cs:363-364` 的注释明确：前端要"把禁止的牌画成禁止"，**唯一诚实的答案就是出牌路径会给的那个**。移植侧应当把"能不能打"实现成**同一个函数的一次试运行**（`play_card` 的 dry-run 模式），而**不要**另写一份 `can_play`（两份实现必然漂移）。这是本项目"成对写测试"纪律的直接推论。

---

## 8. 与临时规则 / 法令（decree）的关系

### 8.1 出牌路径上**确实**读法令 —— 共 5 处

| # | 读点 | 行号 | 读哪个字段 | 规则 |
|---|---|---|---|---|
| 1 | `DecreeCardPlayValidator` | `C:CombatDecrees.cs:150-158` | `Ceiling(registry, source, CombatRule.MaxCardsPerTurn)` 的 `Amount` + `GetCardPlayTurnStats(source.Id).CardsPlayedThisTurn` | `MaxCardsPerTurn` |
| 2 | `DecreeCardPlayValidator` | `C:CombatDecrees.cs:160-174` | `InForce(..., NoLikenessInSuccession)` 的 `spec.LikenessTags`（→ `Tags` 字段）；读 `stats.LastCardPlayedDefinitionId` 与 `stats.LastCardPlayedThisTurnHasTag(tag)` | `NoLikenessInSuccession` |
| 3 | `DecreeCardCostModifier` | `C:CombatDecrees.cs:194-199` | `InForce(..., NthCardOfTurnIsFree)` 的 `spec.Amount`；比 `GetCardPlayTurnStats(...).CardsPlayedThisTurn + 1` | `NthCardOfTurnIsFree` |
| 4 | `CalculateCosts` 末尾的兜底 | `C:Cards\CardPlay.cs:501-507` | `InForce(..., MinimumCardCost)` 的 `spec.Amount` 与 `spec.ResourceOrEnergy`（→ `Resource` 字段，缺省 `standard.energy`，`C:CombatDecrees.cs:65`） | `MinimumCardCost` |
| 5 | `PlayedCardDestination` | `C:Cards\CardPlay.cs:298-302` | `Any(registry, source, CombatRule.PlayedCardsExhaust)`（只看有没有） | `PlayedCardsExhaust` |

**不在出牌路径上的两条**：`UnspentResourceCarries`（refill 处，`C:Resources\ResourceEffects.cs:84-96`）、`MaxHandSize`（抽牌入口，`C:Effects\CardZoneEffects.cs:30-46`）。

**读取语义（三条必须保留）**（`C:CombatDecrees.cs:70-125`）：
1. 收集顺序稳定：按 `(statusId 序数, specIndex)` 排序（`:78-101`）。
2. 重复法令**不互相放松**：`Ceiling` 取 `Min`（`:111-116`）、`Floor` 取 `Max`（`:119-124`）。
3. **"谁戴谁受约束"**：`InForce` 从**出牌者**身上读（`:72-73` 的 `combatant` 参数）；没有全局规则表（`:14-18`）。

### 8.2 但**本内容里一条法令都没有**【实跑】

| 测量 | 值 |
|---|---|
| STAT 表 | 23 行 × 20 格，stride 40 |
| `CombatRules`（格 9，`F_TERM`） | **23/23 = `0xFFFF`（ABSENT16）** ⇒ 没有任何状态携带法令 |
| `PassiveModifiers`（格 8） | 23/23 **present**，但只有 5 条 spec（`DamageDealt` 2 / `DamageReceived` 2 / `TurnStartDraw` 1），多数指向共享空列表 term `0x3a` |
| `PassiveModifiers` 里 `CardCost` / `BlockGain` 的条数 | **0 / 0** |

⇒ **§8.1 的 5 处读点在当前内容下全部 0 命中**。内核把"法令整块"标为未实现，**对这份内容是可接受的**：只要实现成"永远没有法令"（`ceiling = null`、`floor = null`、`exhaust_override = false`、`nth_free = none`），行为与参考**逐位一致**。

### 8.3 ⚠ 这正是"静默错"的温床

| 风险 | 说明 |
|---|---|
| 一旦接入带法令的内容（例如 `env-abi.md:130` 提到的 `costfloor` 场景：起手戴"卡牌最低费用=1"法令），**5 处全部会静默按"没有法令"算** | 结果是能量扣错/牌没进消耗堆，而**哈希对拍会通过**（因为参考当时也没跑过那条向量） |
| `CombatRule` 枚举 7 个成员里，出牌路径读 5 个（§8.1） | 剩下 2 个在回合机侧 |
| 法令的 term 形状（`CombatRules` 列表里每个 spec 的判别串与 4 个字段）**完全未验证**（U7） | 想接就得先造内容再量 |

**移植建议**：`play.rs` 里把 5 个读点全部**显式写成"从 host 取法令视图"的接缝**（即使默认实现恒为"无法令"），并在文档里写清"默认实现只对当前 core 镜像成立"。这样接法令时是**补一个函数**，不是**改一条流水线**。

---

## 9. 对 Rust 界面的建议（只给建议，不写实现）

### 9.1 为什么不能把四个面合成一个函数

参考的四个面在**返回语义**上不同（§1.1）：A/B 抛、C/D no-op。Rust 里没有"抛 vs 静默"的双形态，**必须用两个函数表达**，否则会丢掉一条真实语义（`outcome.WasPlayed == false` 是可观察的，`T:UnplayableCardTests.cs:52` 就是在断言它）。

### 9.2 建议的公开面

```rust
// kernel/rd-core/src/play.rs

/// 一次出牌的请求。**只接受卡实例**：参考的实例面是唯一带落区/标记消费/`CardCostPaid.CardInstanceId`
/// 的路径（`C:Cards\CardPlay.cs:8-11`、`:31`），定义面对本内容是死路（§1.4）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PlayRequest<'a> {
    pub source: &'a CombatantId,
    pub card: CardInstanceId,
    /// 参考里叫 `TargetCombatantId`，语义是"填进 build context 的 EventTargetId"（§4.1）。
    /// ⚠ 传 `None` **不是错误**，是"选择器解出空集"（§4.3）。
    pub target: Option<CombatantId>,
}

/// 拒绝理由。**每个变体都来自参考里真实存在的一条断言**（§2.2/§3.5/§7.1），不是自创。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlayError {
    /// `Result != Ongoing`（`C:Cards\CardPlay.cs:82-86`）。
    NotOngoing,
    /// 来源不存在 / 已倒下（`:88-94`）。
    SourceUnavailable,
    /// 定义未注册（`C:CombatDefinitionRegistry.cs:133-138`）。
    UnknownCard,
    /// 实例不存在 / 不属于该来源 / 不在手牌（`C:Cards\CardZones.cs:192-200`、`:48-58`）。
    CardNotInHand,
    /// 校验器链拒绝。**带上是哪一条**，因为顺序是语义（§2.2）。
    Refused(Refusal),
    /// 资源池不存在（`:521-525`）。
    MissingResource { resource: ResourceId },
    /// 付不起（`:527-531`）。`need/have` 都带上，别只给一个字符串。
    Unaffordable { resource: ResourceId, need: i32, have: i32 },
    /// 印刷费用为负（`:449-453`）。
    NegativePrintedCost { resource: ResourceId },
    /// 效果执行失败（`exec::ExecError`）。
    Effect(exec::ExecError),
    /// 定容容器满（`state::CapacityError`）。
    Capacity(state::CapacityError),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Refusal {
    Stunned,
    Unplayable,
    PlayConditionFalse,
    DecreeMaxCardsPerTurn { cap: i32, played: i32 },
    DecreeNoLikeness { tag: TagId },
    OneAttackPerTurn,
}

/// 成功出牌的报告。做成返回值是为了让测试断言"确实付了钱、确实落了区"，
/// 而不是只能看哈希（§6.3 的教训）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PlayReport {
    /// 对应 `PlayCardOutcome.WasPlayed`（`C:Cards\PlayCardEffects.cs:88`、`:93`）。
    /// `try_play_card` 拒绝时返回 `Ok(PlayReport { played: false, .. })`，与参考的 no-op 同构。
    pub played: bool,
    /// 实际付出的每条费用（`CalculatedResourceCost[]`，`:509-511`）。0 费时为空。
    pub paid: PaidCosts,
    /// 卡最终所在区；`None` = 没出牌，或战斗在程序中途结束（卡留在手牌，§5.2 Cancelled）。
    pub landed: Option<CardZone>,
    /// 是否 fire 了 `CardPlayed`（`IsAction` 时为 false，`:130-150`）。
    pub counted_as_card_played: bool,
}

/// 严格面（A/B）：拒绝 = `Err`，与参考的"抛"同构。
pub fn play_card<H: PlayHost>(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    req: &PlayRequest<'_>,
    host: &mut H,
) -> Result<PlayReport, PlayError>;

/// 请求面（C/D，**游戏真实路径**）：拒绝 = `Ok(PlayReport { played: false })`。
/// 单独一个函数，因为参考这两个面的语义真的不同（§1.1）。
pub fn try_play_card<H: PlayHost>(...) -> Result<PlayReport, PlayError>;

/// dry-run：只回答"能不能打"，绝不动状态。**必须由 `play_card` 的同一条代码路径实现**
/// （参考的 `IsCardPlayAllowed` 就是这么做的，`C:Cards\CardPlay.cs:365-382` 的 try/catch）。
pub fn can_play_card<H: PlayHost>(state: &CombatState, content: Option<&Content<'_>>, req: &PlayRequest<'_>, host: &H) -> Result<(), PlayError>;
```

### 9.3 `PlayHost`：把外部世界做成接缝（照 `turn.rs` 的 `TurnHost` 抄）

`K:turn.rs:107-159` 已经把"回合机的七个外部位点"做成了 trait（含默认实现），`play.rs` 应该同构：

```rust
pub trait PlayHost {
    /// 受理校验器链，按 `(priority, modifier_id)` 升序（§2.1）。默认实现 = 标准包 5 条。
    fn validate_card_play(&mut self, state: &CombatState, card: &CardDef, req: &PlayRequest<'_>) -> Result<(), Refusal>;

    /// 算最终费用（§3.3-3.4）。默认实现 = 印刷费用 + 6 个 modifier 里适用的那些。
    /// 做成接缝而不是内联，是因为 6 个 modifier 里有 4 个要内容（状态 spec/法令/卡标记）。
    fn calculate_costs(&mut self, state: &CombatState, card: &CardDef, req: &PlayRequest<'_>) -> Result<PaidCosts, PlayError>;

    /// 落点：法令 `PlayedCardsExhaust` + 卡定义（§5.3）。
    fn played_card_destination(&self, state: &CombatState, card: &CardDef, actor: &CombatantId) -> CardZone;

    /// 执行 on-play 程序。默认 = `exec::execute(root, ctx)`（§4.2 程序路径）。
    fn run_on_play_program(&mut self, state: &mut CombatState, card: &CardDef, req: &PlayRequest<'_>) -> Result<(), PlayError>;

    /// 事件入队 + 队列排空（§1.2 阶段 6）。**必须由 host 提供**：内核 `state.rs` 里
    /// **没有** `PendingEffects`/`PendingEvents`/`PendingContinuations` 三队列（§10 风险 1）。
    fn enqueue_event(&mut self, state: &mut CombatState, event: CombatEvent);
    fn resolve_pending_queues(&mut self, state: &mut CombatState) -> Result<(), PlayError>;

    /// 卡牌回合统计（§6.1）。**默认实现必须真的做**，因为法令要读它而哈希看不见它（§6.3）。
    fn record_card_played(&mut self, state: &mut CombatState, actor: &CombatantId, card: &CardDef);
}
```

### 9.4 三条必须守的纪律（否则移植会"绿但错"）

1. **`can_play_card` 不能是第二份实现**。用同一函数跑一遍并把 `PlayError` 当返回值，或显式 dry-run 模式。
2. **`PlayReport` 不能只有 `bool`**。`T:CardCostModifierTests.cs:143-195` 就是在断言"事件里带的是**改后**的费用"；只返回 bool 会丢掉 `paid` 这个可断言面。
3. **`target: None` 不许报错**（§4.3）。想"帮用户挡一下"是错的，会与参考的哈希分叉。

---

## 10. 移植风险排序（按"会静默错"的概率）

| # | 风险 | 为什么危险 | 建议的钉子 |
|---|---|---|---|
| **1** | **"入队-排空" vs "就地执行"**：参考的 `dealDamage` 是**入队** effect request、之后由 `CombatQueueProcessor` 排空（`C:CombatEffectQueueProcessor.cs:7-58`）；内核 `K:exec.rs:412` 的 `execute` 是**就地**写状态。而且内核 `K:state.rs:1441-1453` 的 `CombatState` **根本没有**三队列字段（`PendingEffects`/`PendingEvents`/`PendingContinuations` 一个都没有） | 中间态可观察：`CardPlayed` 触发器在卡的伤害**之前**还是**之后**跑、卡在程序跑完前是否还在手牌（`T:CardPlayCompletionBoundaryTests.cs`）、`Faulted` 时卡是否已落区（§5.2）全都由这个模型决定 | 至少写 3 条向量：(a) 卡在程序第 1 步时仍在手牌；(b) `CardPlayed` 触发器的抽牌发生在卡的伤害之前；(c) Faulted 后卡在弃牌堆且**没有** `CardMovedToZone` 事件 |
| **2** | **两个入口的 `chain_num` 不一致**（§6.2） | 同一次出牌两条入口给出不同哈希；照抄错的那条会永久偏移 `chain_num=` 那一行 | 只实现 C/D 面；显式记"A/B 面不实现"，并为"一次出牌把 `chain_num` 推到多少"写死一条断言（U5：数字自己量） |
| **3** | **legacy `Effects` 在本内容里为空**（§1.4） | 移植者会很自然地认为"卡只有 Program"、于是删掉 legacy 路径；一旦换成带 `Effects` 的内容就整块失效 | `play.rs` **保留** legacy 分支（哪怕默认空），并写一条"两个请求来源都进队列、legacy 在前"的测试 |
| **4** | **校验器顺序**（注释与实现相反，§2.3） | 照抄注释 ⇒ 顺序错 ⇒ 报错文本变、副作用型的 PlayCondition 行为变 | 断言"5 个校验器的执行序 = stun, decree, play_condition, one_attack, unplayable" |
| **5** | **失败路径的"零副作用"只是哈希意义**（§7.2） | 读 stats 会创建空条目；快照级对拍会炸，哈希级不会 | 若做快照对拍，复刻该副作用；若不做，记录为有意偏离 |
| **6** | **法令 5 个读点全部 0 命中**（§8.2） | 接内容时静默错且对拍不报 | 五个读点全部做成 host 接缝（§9.3），默认"无法令"并在注释里写清适用范围 |
| **7** | `Costs` 的 `Dictionary` 枚举序（§3.5，U4） | 支付顺序/事件里 `Costs` 数组顺序是 .NET 实现细节；本内容 1 条目/卡，造不出反例 | 内核自己定一个稳定序（按 `CardZone` 那样按资源 id 序数排），并记录为**有意偏离** |
| **8** | 卡牌回合统计不进哈希（§6.3） | "出牌统计算错"对拍 100% 通过 | 单独断言 `CardsPlayedThisTurn` / `LastCardPlayedDefinitionId` / 按标签计数 |
| **9** | **程序预检（preflight）的时机**：参考在 `EffectProgramExecutor.Execute` 一进来就 `ValidateNodeExecutors(program.Root, ...)`，**早于** `AllocateProgramExecutionId()`（`:22-23` 早于 `:25-28`） | 一个含"未注册节点"的程序**不消耗** `next_program_execution_id`；内核若把"不支持这个节点"当执行期错误，`exec_num` 就会比参考多涨一次 | 在 `play.rs` 里把"节点全支持"检查放在分配 exec id **之前**；4 张含 `moveCardToZone`/`forEachCardInZone` 的卡（§1.4 第 6 条）就是现成的反例素材 |

---

## 附：本文用到的全部 C# 锚点索引

| 主题 | 锚点 |
|---|---|
| 四个入口面 | `C:Cards\CardPlay.cs:17-33`、`:35-68`、`C:Cards\PlayCardEffects.cs:21-96`、`C:CombatReplayRunner.cs:29-36` |
| 出牌核心六阶段 | `C:Cards\CardPlay.cs:70-109` |
| 入队+付费 12 个子相位 | `C:Cards\CardPlay.cs:114-294` |
| 受理校验链 | `C:Cards\CardPlayValidators.cs`（全文）、`C:Cards\CardPlayTurnValidators.cs:3-29`、`C:CombatDecrees.cs:131-176`、`C:Cards\CardPlay.cs:384-402` |
| 校验器排序 | `C:CombatDefinitionRegistryBuilder.cs:189-200`、`:202-213`、`:438-447`、`:584-592` |
| 费用计算 | `C:Cards\CardPlay.cs:436-512`、`:316-329`、`:514-544` |
| 费用修饰器 | `C:StandardCombatPackage.cs:57`、`:65-69`；`C:Effects\PassiveModifiers.cs:16-30`、`:271-290`；`C:Cards\FreeNextCardCostModifier.cs:3-27`；`C:Cards\CardPlayTurnCostModifiers.cs:3-33`；`C:Cards\SkillCostReductionCostModifier.cs:3-29`；`C:Cards\CardInstanceCostModifier.cs:13-34`；`C:CombatDecrees.cs:181-203` |
| 目标选择器 | `C:Effects\CombatantTargetSelectors.cs:113-134`、`:136-152`、`:154-169`、`:347`；`C:Cards\CardEffectDefinitionHandlers.cs:46` 等 |
| 牌区与移区 | `C:Cards\CardZones.cs:3-22`、`:182-223`、`:192-205`；`C:Effects\CardZoneEffects.cs:155-213` |
| 落区三终态 | `C:Cards\CardPlay.cs:240-263`、`:283-302` |
| 队列解析 | `C:Cards\QueueResolution.cs:14-138` |
| 队列排空 | `C:CombatEventHandling.cs:37-115`、`C:CombatEffectQueueProcessor.cs:7-58`、`C:CombatExecutionLimits.cs:3-35` |
| 生成器编号 / 动作作用域 | `C:CombatState.cs:106-132`、`:513-518`、`:545-555`、`:675-708` |
| 卡牌回合统计 | `C:Cards\CardPlayTurnStats.cs:118-147`、`:278-294`、`:365-382` |
| 法令 | `C:CombatDecrees.cs:19-51`、`:57-66`、`:70-125` |
| 哈希与快照 | `C:CombatStateHasher.cs:26-164`、`C:CombatStateSnapshot.cs:115-162` |
| 内核现状（只读参考） | `K:modifiers.rs:36-45`、`K:status_bind.rs:122-140`、`K:state.rs:480-490`、`:513-523`、`:1441-1453`、`K:exec.rs:170-289`、`:412`、`K:turn.rs:60-159`、`K:content.rs:1013-1029`、`:1268-1300` |
| 参考测试（行为钉子） | `T:CombatCardPlayProcessorTests.cs:8-109`、`T:CardPlayValidatorTests.cs:44-116`、`T:UnplayableCardTests.cs:41-70`、`T:CardPlayCompletionBoundaryTests.cs:21-180`、`T:CardProgramTerminalCleanupTests.cs:18-78`、`T:CardCostModifierTests.cs:46-193`、`T:CardCostPaidEventTests.cs:10-195`、`T:XCostCardTests.cs:33-61` |
