# 敌人意图与动作选择（Enemy Intent & Action Selection）规格书

> **状态**：recon 规格书，**只描述参考实现的真实行为**，不含任何 Rust 实现。
> **产出任务**：内核"敌人不会行动"这一块的迁移前置。本文件是 `intent.rs` 的冻结依据。
>
> **依据的参考实现**：`D:\Vibe\sts-tui\ref\RogueDeck-Core\`（只读），锚点 commit
> `fd43e68ab91f40b475b745725abb17134b951c51`。**没有跑过 dotnet**（会往它的 obj/bin 写文件），
> 也没有跑过 cargo。下文的每一条"行为"都是**从代码路径读出来的**，不是跑出来的。
>
> **依据的内容镜像**：`tools\contentc\out\content.core.rdcf`
> （85,616 B，`flags=1` 表现层已剥，`content_hash=0xD1075DE5`）。所有分布数字由
> `native\_recon_intent.py` 用 `tools\contentc\reader.py` 实测，见 §11。
>
> **验证标记约定**
> * ✔ **我验证过** = 我读了那一行代码 / 我量了那个产物，行号可复核。
> * ✘ **未验证** = 推断、依赖第三方文档行为、或需要运行引擎才能确认。
> * 【推测】= 我的猜测，不是规格。
>
> ⚠️ **行号时效**：本文对 `ref\RogueDeck-Core\**` 与 `tools\contentc\**` 的行号是锚点 commit 上的，
> 稳定。对 `kernel\rd-core\src\play.rs` 的引用（只有 `:50-52`、`:54-56` 两处）**取自我写这份文档时**
> 的版本，而那个文件当时正被另一个任务并发实现 —— 引用它的那两条论据请自行复核一次。

---

## 0. 结论速览

| 问题 | 答案（一句话） | 详见 |
|---|---|---|
| 谁挑动作？ | **引擎不挑。**挑选是一个**由宿主注入的纯函数** `Func<CombatState, CombatantId, int, EnemyActionDefinitionId?>`，参考实现里唯一的实现是 `EnemyIntentSelectors.Build` | §1.1 §3.1 |
| 敌方回合跑 turn-start 七步吗？ | **跑，完整跑。**`StartCurrentTurn` 不看队伍，敌人也补能量、转正 pending、跑触发器、清 Block、吃 DoT | §1.3 |
| 意图是什么？ | **一个"每次问都重算"的投影**，不是状态。它不是"提前存好的下一回合计划"，而是"如果现在轮到它，它会做什么" | §2 |
| 状态模型里有 intent 字段吗？ | C# 有 `CombatantState.IntentKey`，但**全仓零调用者**（死字段）；Rust 内核没有。**建议不要加** | §2.2 §2.5 |
| 选择算法 | **确定性、零 RNG**：`IntentRules` 按 Priority 降序首个匹配 → 否则 `Actions[(round-1) % count]` | §3 |
| EACT 行有 7 格 | `Id / NameKey / DescriptionKey / PackageId / Intent / Program / extra`。**没有权重格、没有条件格、没有冷却格** —— 冻结方描述有误 | §4.1 §4.5 |
| 敌人和动作怎么关联 | **按 id 字符串**，不是槽位。脚本本身存在 `ENCT` 行的 enemy record 里 | §5.3 |
| 执行路径 | **和出牌同一条** `EffectProgramExecutor.Execute`；`source`=敌人，`event_target`=目标 | §6 |
| 纯数据驱动？ | **选择规则 100% 是内容；执行 100% 是引擎。**但"动作脚本"存在 ENCT 里，不在 EACT 里 —— 这决定接口必须拿到 (遭遇, 槽位) 而不只是 combatant | §8.2 |

---

## 1. 敌方回合的入口与顺序

### 1.1 引擎里**没有**"敌方回合"这个概念（✔）

`RogueDeck.Core` 只知道**战斗员**，不知道"玩家"和"敌人"的区别。三处证据：

1. `CombatTurnProcessor.StartCurrentTurn`（`Core\Combat\CombatTurnProcessor.cs:7-38`）对
   `combat.ActiveCombatantId` 无任何队伍判断（✔）。
2. `EnemyIntentSelectors` 住在 **Scenario 层**，不在 Core 里（`Scenario\Authoring\EnemyIntentRules.cs:149`）（✔）。
3. `ExecuteEnemyActionEffectRequest` 是一个**普通效果请求**，任何一方都能发
   （`Core\Combat\EnemyActions\EnemyActionEffects.cs:6-10`）（✔）。

**所以"某个战斗员的回合"和"敌人行动"是两件正交的事。**回合推进是引擎的；"这个回合该做什么"是宿主的。

### 1.2 三个真实入口（✔）

仓库里只有三处会真正驱动敌人出手：

| 入口 | 挑动作的方式 | 位置 |
|---|---|---|
| `InteractiveCombat.EndTurn` | 调用注入的 `_enemyIntent(state, enemyId, state.CurrentRound)` | `Scenario\Scripting\InteractiveCombat.cs:345-403` |
| `PartyCombat.RunEnemyPhaseThenNextPlayerPhase` | 同上，但目标由 `PartyEnemyTargeting` 另选 | `Scenario\Scripting\PartyCombat.cs:125-154` |
| `ScenarioRunner.ExecuteEnemyActs` | **不挑**：动作 id 直接来自脚本步 `EnemyActs(enemyId, actionId, targetId)` | `Scenario\Scripting\ScenarioRunner.cs:148-194` |

三个入口最终都走同一句（✔）：

```csharp
combat.EnqueueEffect(new ExecuteEnemyActionEffectRequest(enemyId, actionId, target));
_queues.ResolvePendingQueues(combat, registry);
```

（`InteractiveCombat.cs:370-371`、`PartyCombat.cs:143-144`、`ScenarioRunner.cs:191-192`）

**这三个入口里没有任何一个是"引擎"**：都是 harness / driver。这是本层最重要的一条架构事实。

### 1.3 敌方回合跑完整的 turn-start 七步（✔）

`InteractiveCombat.EndTurn` 的顺序是（`InteractiveCombat.cs:350-388`，✔）：

```
353:  _turns.EndCurrentTurnAndStartNextTurn(...)   ← ①先结束英雄回合 + 启动下一个战斗员的回合
358:  while (Result == Ongoing && ActiveCombatantId != hero)   ← ②此时 active 已经是敌人
361:      actionId = _enemyIntent(...)              ← ③选动作
370:      EnqueueEffect(ExecuteEnemyActionEffectRequest)
384:      _turns.EndCurrentTurnAndStartNextTurn(...) ← ④结束这个敌人回合、启动下一个
```

第 353 行那次 `EndCurrentTurnAndStartNextTurn` 内部会调
`StartCurrentTurn`（`CombatTurnProcessor.cs:101-118`），后者**无条件**为"下一个存活战斗员"
（包括敌人）入队 `TurnStartedCombatEvent`（`CombatTurnProcessor.cs:28-32`），并且
`ResolvePendingQueues` 会按注册序跑完那七个处理器（`StandardCombatPackage.cs:121-139`）。

**结论**：敌方回合的 turn-start 与玩家回合**完全相同**，顺序也相同：

```
补能量 → pending 转正 → turn-start 触发器 → 队列 → 抽牌 → 清 Block → DoT
```

这条顺序在内核里已经实现（`kernel\rd-core\src\turn.rs:588-681`，尤其 `:611-616` 的注释说明了
"顺序是规格的一部分"）。**所以"敌方回合要不要跑七步"这个问题在内核里已经答完了 —— 会跑，
因为 `start_current_turn` 没有队伍参数**（✔ 读 `turn.rs:588-597`：`ensure_active_can_start_turn`
只查存活与在回合序里）。

### 1.4 ⚠️ 敌方回合会发生的三个"副作用"（✔ 读码，未跑引擎）

这不是 bug，但**内核必须复刻**，否则状态哈希会分叉：

1. **敌人会凭空长出一个 3/3 的能量池。**
   `RefillResourceOnTurnStartedHandler` 对任何战斗员入队 `RefillResourceEffectRequest(energy, 3)`
   （`Core\Combat\Resources\ResourceTurnLifecycleEventHandlers.cs:19-28`），而
   `RefillResourceEffectHandler` 在资源**不存在时直接创建**它
   （`Core\Combat\Resources\ResourceEffects.cs:50-56`）。⇒ 每个敌人第一次回合开始时，
   `Resources["standard.energy"] = { current: 3, max: 3 }`。这**会**进状态哈希：
   `CombatStateHasher` 对**每个战斗员**的每个资源都写 `res=<id> <cur>/<max>` 行
   （`Core\Combat\CombatStateHasher.cs:83-86`，✔）。
2. **敌人会尝试抽 5 张牌，然后什么也没发生。**
   每个战斗员（含敌人）在 `AddCombatant` 时都分到一套空卡区
   （`Core\Combat\CombatState.cs:233`）。`DrawCardsOnTurnStartedHandler` 不看队伍
   （`Core\Combat\Cards\CardTurnLifecycleEventHandlers.cs:15-36`），于是入队抽 5 张；
   `DrawCardsEffectHandler` 抽到 `drawnCards.Count == 0` 后**静默 return**，
   **不写日志、不发事件**（`Core\Combat\Effects\CardZoneEffects.cs:49-60, 84-89`）。
   ⇒ 净效果为零。
3. **敌人回合结束会尝试弃手牌，也是零。**
   `DiscardHandOnTurnEndedHandler` → `MoveHandCardsOnTurnEndEffectRequest`，
   手牌为空时直接 return（`CardZoneEffects.cs:354-358`）。

> **给内核的话**：第 2、3 条可以安全地不做（净效果为零）。第 1 条**不能**不做 —— 它改变状态。

### 1.5 `TurnHost` 那 8 个钩子和敌方回合的关系（✔）

内核的 `TurnHost` 有 8 个必实现钩子（`turn.rs:114-291`，✔）：
`activate_pending_statuses` / `run_turn_started_triggers` / `resolve_card_queue` /
`resolve_pending_queues` / `damage_over_time` / `hand_turn_end_lifecycle` /
`run_turn_ended_triggers` / `decrease_timed_statuses` / `hand_is_retained`（最后一个是 `&self`）。

**它们全部与队伍无关，敌方回合原样调用。** 唯一"看起来只属于玩家"的是 `hand_*` 系列 ——
而参考实现对敌人也是走同一条路（`DiscardHandOnTurnEndedHandler` 不看队伍），只是空手牌让它无效。
所以：**不需要给 `TurnHost` 加 `is_enemy` 之类的参数**。

---

## 2. "意图（intent）"是什么

### 2.1 三个概念必须分开（✔）

参考实现把它们做成了**三个互不引用的东西**：

| 概念 | 类型 | 住哪 | 引擎看得见吗 |
|---|---|---|---|
| **可执行体**：这个动作干什么 | `EnemyActionDefinition`（`Program` + 旧式 `Effects`） | Core（`EnemyActions\EnemyActionDefinitions.cs:13-39`） | **看得见**，这是唯一进引擎的东西 |
| **表现标签**：这个动作该怎么显示 | `ActionIntent(Label, Kind)`（`Scenario\Authoring\ActionIntent.cs:15-20`） | Scenario/harness 的字典 `CompiledScenario.Intents` | **看不见**，引擎完全不知道 |
| **这一回合选哪个** | `Func<CombatState, CombatantId, int, EnemyActionDefinitionId?>` | 宿主注入 | **引擎看不见，只收到一个 request** |

`ActionIntent.cs:3-4` 的注释把这件事写死了：**"This is harness-only metadata — the engine
never sees it (it only knows the EnemyActionDefinition that executes)."**（✔）

### 2.2 所以"意图"不是"提前公开下一回合要做什么"（✔）

它是**一个纯粹的投影函数**：给定此刻的状态，回答"如果现在轮到它，它会用哪个动作"。
没有"选择 → 存储 → 之后消费"的三段式。证据：

* `CombatantState.IntentKey`（`Core\Combat\CombatantState.cs:77`）与 `SetIntent`（`:126-129`）存在，
  但**全仓（src + 全部测试工程）零调用者**。我 grep 过整个 `ref\RogueDeck-Core` 的
  `SetIntent|\.IntentKey`，只有那一处声明（✔ 实测）。⇒ **死字段。**
* `IntentKey` 不进快照、不进哈希（`kernel\rd-core\src\snapshot.rs:83` 把它列在"范围外"清单里，✔）。
* 真正的"预告"是 `CombatState.UpcomingIntentKind`（`Core\Combat\CombatState.cs:81-84`）：
  **一个 `Func<CombatState, CombatantId, string?>?`**，由 driver 装上
  （`InteractiveCombat.cs:118-124`、`PartyCombat.cs:59-64`），供战斗程序问
  "目标是不是打算攻击"（`Core\Combat\Effects\Programs\EffectProgramExpressions.cs:2257-2281`）。
  它是一个 **host collaborator**，不进快照、不进哈希（`snapshot.rs:80-82`，✔）。

### 2.3 什么时候被选择 / 公开 / 消耗

| 动作 | 真实行为 | 行号 |
|---|---|---|
| **选择** | 在**该敌人自己的回合已经开始之后**（`EndCurrentTurnAndStartNextTurn` 返回后），每回合一次 | `InteractiveCombat.cs:353→361` |
| **公开** | **每次问都重算**。UI 每帧问 `UpcomingIntentFor` 就重跑一遍选择函数；牌在手上问 `intends` 也重跑一遍 | `InteractiveCombat.cs:126-133`、`:157-170` |
| **消耗** | **不存在"消耗"**。没有任何字段被写下或清掉 | （`IntentKey` 零调用者） |

`IntentReadingTortureTests.cs:107-121`（✔）钉住了"公开的答案会随战斗移动"：
第 1 回合预告 `Attack`（于是牌多挂 1 层 `doubt`），`EndTurn` 之后第 2 回合预告变成 `Defend`，
同一张牌就不再多挂。**这条测试恰好证明预告是重算的，不是记住的。**

### 2.4 ⚠️ "预告" ≠ "事实"：三处会分叉（✔ 读码，✘ 未跑引擎验证）

参考实现自己在 `InteractiveCombat.cs:405-421` 里承认了一种分叉（Fork 上无人应答 prompt）。
我读代码找到另外两种，都**不在**它的注释里：

1. **Fork 上没有 chooser**（`InteractiveCombat.cs:418-421`，参考自己说的，✔）。
2. **预告在英雄回合中算，动作在英雄回合结束后算，中间状态会变。** 中间发生了：
   英雄的 turn-end（弃手牌、turn-end 触发器、有期限状态 -1）→ 该敌人的 turn-start
   （补能量、pending 转正、触发器、抽牌、**清 Block**、**吃 DoT**）。
   任何读 `health` / `statuses` / `counter` 的条件都可能在这两步之间变号。
   ⇒ **`SelfHasStatusCondition` / `EnemyHealthPercentCondition` 这类条件的预告可能撒谎。**
3. **死掉的敌人仍然会被问。** `EnemyIntentSelectors` 的 lambda 不检查 `IsAlive`
   （`EnemyIntentRules.cs:154-167`）—— 见 §7.5。

### 2.5 内核 `state.rs` 要不要加 intent 字段？

**建议：不要加。**三条理由：

1. 加了就是**加了参考实现没有的东西**，而快照/哈希是对着参考实现逐字节比的
   （`corpus/hash_cases/*.txt` 85 份）。多一个字段就要解释它为什么不进哈希。
2. 参考实现的 `IntentKey` 是死字段 —— 抄它等于抄一个 bug。
3. 预告是 (state, content) 的纯函数，**每次问重算**是对的：它保证"预告"和"真打"
   永远用同一份状态与同一段代码，不会分叉（这也是本项目在 `play.rs:50-52` 用过的论证）。

**要加的是"内容侧"而不是"状态侧"**：一个 `EnemyScript<'a> { actions: &[u16], rules: &[RuleRef] }`
的借用视图（见 §8.1）。

### 2.6 ⚠️ `flags=1` 的 core 镜像里**没有 `Label`**（✔ 实测）

同一份内容的两份镜像：

| | `content.core.rdcf`（flags=1） | `content.rdcf`（flags=0） |
|---|---|---|
| `EACT.Intent` 解码出的键 | `["Kind"]` × 394 | `["Kind", "Label"]` × 394 |
| `EACT.NameKey` 存在条数 | **0 / 394** | **394 / 394** |
| `EACT.DescriptionKey` 存在条数 | **0 / 394** | **394 / 394** |
| opcode 数 | 130 | 139 |
| string 数 | 1375 | 3140 |
| root 表 | 16（无 `Presentation`） | 17（有 `Presentation`） |

⇒ **拿 core 镜像做 UI 只能显示 `Kind`（⚔/🛡/▲/▼/✦），显示不出"Rubber Stamp Rush · 5 dmg"这种标签。**
内核 `content.rs:447` 已经写了这条前提（"`flags & 1` … `NameKey`/`Label` 不可假设存在"），✔。

---

## 3. 选择算法（纯逻辑，无内容兜底 ⇒ 每个分支都给行号）

### 3.1 签名与实现（✔ 全文只有 19 行）

`Scenario\Authoring\EnemyIntentRules.cs:149-168`：

```csharp
public static Func<CombatState, CombatantId, int, EnemyActionDefinitionId?> Build(CompiledScenario compiled)
{
    var byId = compiled.Enemies.ToDictionary(e => e.CombatantId);      // :153
    return (state, enemyId, round) =>
    {
        if (!byId.TryGetValue(enemyId, out var enemy))                // :156
            return null;                                              // :157
        if (enemy.IntentRules.Count > 0)                              // :159
            foreach (var rule in enemy.IntentRules.OrderByDescending(r => r.Priority))  // :160
                if (rule.Condition.Matches(state, enemyId))           // :161
                    return rule.Action;                               // :162
        return enemy.Actions.Count > 0                                // :164
            ? enemy.Actions[(round - 1) % enemy.Actions.Count]        // :165
            : (EnemyActionDefinitionId?)null;                         // :166
    };
}
```

**分支树（穷举）**：

| # | 条件 | 结果 | 行号 |
|---|---|---|---|
| B0 | `enemyId` 不在 `compiled.Enemies` 里 | `null`（放弃本次行动） | `:156-157` |
| B1 | `IntentRules.Count > 0` 且存在匹配规则 | **该规则的动作**（不是循环里的） | `:159-162` |
| B2 | `IntentRules.Count > 0` 但无一匹配 | 落回 B3（**规则失败 ≠ 放弃**） | `:159` 之后不回，`:164` |
| B3 | `Actions.Count > 0` | `Actions[(round-1) % Actions.Count]` | `:164-165` |
| B4 | `Actions.Count == 0` | `null` | `:166` |

`EnemyIntentRulesTests.cs:63-71`（✔）钉住 B3 的 1-based 语义：
`selector(state, ogre, 1) == Smash`、`round 2 == Harden`、`round 3 == Smash`（wraps）。

### 3.2 规则的评估顺序 = `Priority` 降序，**不是**列表顺序（✔）

`:160` 的 `OrderByDescending(r => r.Priority)`。`EnemyIntentRulesTests.cs:90-102`（✔）
钉住它：两条规则都恒真，Priority 5 的胜出。

**同 Priority 的 tie-break（✘ 未验证）**：`Enumerable.OrderByDescending` 在
LINQ-to-Objects 里是**稳定排序**（文档行为），所以同 Priority 保持**作者列表顺序**。
我**没有实测**这一点，但它对本内容不可观察 —— 镜像里唯一存在同 Priority 的两条规则
（`contradictory_signpost`，两条 Priority=20）条件互斥（`Equal 1` / `Equal 2`）。
见 §3.6 的实测清单。

### 3.3 `round` 是 1-based 的 `CurrentRound`，且在**动作时点**采样（✔）

`:165` 用 `(round - 1) % count`。`round` 由调用方传入：

* `InteractiveCombat.cs:361`：`_enemyIntent(_combat, enemyId, _combat.CurrentRound)`
* `PartyCombat.cs:140`：同一个写法
* `InteractiveCombat.cs:122`（预告）与 `:165`（lookahead）：也传 `CurrentRound [+ ahead]`

**关键时序（✔ 逐行推过）**：`CurrentRound` 只在**回合序绕回**时 +1，不在每个战斗员切换时 +1 ——
`CombatTurnProcessor.cs:190-205` 的 `if (nextIndex <= currentIndex) { RoundEnded; AdvanceRound; }
else AdvanceTurn;`，而 `CombatState.AdvanceTurn()` 只 `CurrentTurn++`、`AdvanceRound()` 才
`CurrentRound++` 且 `CurrentTurn = 1`（`CombatState.cs:572-588`，✔）。

回合序 = `[hero, ally…, enemy…]`（`ScenarioCombatFactory.cs:19-24` 按这个顺序 `AddCombatant`，
`AddCombatant` 往 `_turnOrder` 追加，`CombatState.cs:232`）。于是：

| 场景 | 英雄回合时 `CurrentRound` | 敌人出手时 `CurrentRound` | 一致？ |
|---|---|---|---|
| 1 敌 | R | R（`1 > 0` ⇒ `AdvanceTurn`） | ✔ |
| 2 敌 | R | 两只都是 R（`2 > 0`、`2 > 1`） | ✔ |
| 首个敌人已死 | R | R（跳过死者，`2 > 0` 仍 `AdvanceTurn`） | ✔ |

⇒ **预告和事实用的是同一个 `round`。**这一点让 B3 的纯循环部分是精确的（不含 §2.4 的条件分叉）。

### 3.4 RNG：选择环节 **0 次**；执行环节"看程序"（✔）

* `EnemyIntentSelectors.Build` 的函数体里**没有任何**随机源（`EnemyIntentRules.cs:154-167`）。
* `Condition.Matches` 的 10 个实现里**没有**随机源（`EnemyIntentRules.cs:40-144`）。

⇒ **"选哪个动作"这条路径推进 0 次 `(seed, step)`。内核不需要为它准备 RNG。**

**但"执行这个动作"可能推**：会动 `RandomStep` 的地方（全部 `✔` 扫过整个 `src`，
`CreateShuffledIndexes` 的调用点 + 紧随其后的 `AdvanceRandomStep`）：

| 位置 | 干什么 | 推几次 |
|---|---|---|
| `CardZoneEffects.cs:62-69` | 弃牌堆重洗 | 1 |
| `ScenarioCombatFactory.cs:86-88` | 开局洗牌堆 | 1 |
| `ResourceSelection.cs:64-65` | 随机选资源 | 1 |
| `StatusSelection.cs:87-88` | 随机选状态 | 1 |
| `EffectProgramExpressions.cs:1928-1929` | `randomRange` 类表达式 | 1 |
| `EffectProgramExpressions.cs:1952-1953`、`:2049-2050` | 随机选卡 | 1 |
| `EffectProgramNodeExecutors.cs:527-539` | `RandomTargetSelectionNodeExecutor`（随机取 N 个目标） | 1（`count==0` 时推 **0**） |

**本内容的 394 个敌方动作程序一次都用不到上面任何一个**（§4.3 的 kind 词表里没有随机节点、
选择器只有 `sel.eventTarget`/`sel.source`/`sel.allAllies`）⇒ **这份内容里执行敌方动作也推进 0 次。**
但这是内容的性质，不是这一层的性质 —— 内核的 `execute_action` 必须走能推 RNG 的那条路。

**唯一一处与"随机"沾边的是队伍模式下的选目标**（不是在选动作）：
`PartyCombat.EnemyTarget` 的 `Random` 策略（`PartyCombat.cs:168-169`，✔）：

```csharp
PartyEnemyTargeting.Random => players[
    CombatRandom.CreateShuffledIndexes(players.Length, _combat.RandomSeed, _targetStep++)[0]].Id,
```

注意它用的是**本地计数器 `_targetStep`**（`PartyCombat.cs:34`，初值 0），
**不是 `_combat.RandomStep`**，也**不调用 `AdvanceRandomStep()`**。后果：

* 同一个 seed 下，每场战斗的"随机目标"序列都一样；
* `CreateSnapshot`/`Restore` 之后 `_targetStep` 归零（它是 driver 的字段，不进状态）⇒ **恢复后随机序列重来**；
* 它**不影响**哈希（因为没动 `random_step`）。

单人模式根本不走这条：目标永远写死为 `_heroId`（`InteractiveCombat.cs:370`，✔）。

### 3.5 条件原语的 10 种（✔ 全部读完，`EnemyIntentRules.cs:22-144`）

| # | 类型 | 判别式（JSON kind） | 读什么 | 行号 |
|---|---|---|---|---|
| 1 | `EnemyHealthPercentCondition(Op, Percent)` | `intent.healthPercent` | `Health.Current*100` vs `Percent*Health.Max`（**交叉相乘，无浮点**） | `:40-48` |
| 2 | `RoundCondition(Op, Round)` | `intent.round` | `state.CurrentRound` | `:51-55` |
| 3 | `SelfHasStatusCondition(Status, MinStacks=1)` | `intent.selfHasStatus` | 自己身上该状态层数 ≥ MinStacks | `:58-66` |
| 4 | `OpponentHasStatusCondition(Status, MinStacks=1)` | `intent.opponentHasStatus` | **任意**敌方队伍成员身上 | `:70-79` |
| 5 | `SelfHasCounterCondition(Counter, Op, Value)` | `intent.selfHasCounter` | `Combatant.GetCounter`（**缺席读 0**） | `:85-93` |
| 6 | `SelfResourceCondition(Resource, Op, Value)` | `intent.selfResource` | `Resources[rid].Current`（**缺席读 0**） | `:96-105` |
| 7 | `OpponentCardsPlayedCondition(Op, Value, LastTurn=true)` | `intent.opponentCardsPlayed` | 第一个对立战斗员的 `GetCardPlayTurnStats` | `:110-123` |
| 8 | `AllOfCondition(list)` | `intent.allOf` | 全真（**空 ⇒ true**） | `:126-130` |
| 9 | `AnyOfCondition(list)` | `intent.anyOf` | 任一真（**空 ⇒ false**） | `:133-137` |
| 10 | `NotCondition(inner)` | `intent.not` | 取反 | `:140-144` |

比较算子的字符串拼法来自 `System.Text.Json` 的枚举序列化：
`Equal / NotEqual / Less / LessOrEqual / Greater / GreaterOrEqual`（`EnemyIntentRules.cs:26-35`），
未知算子**抛异常**（`:34`）。

**判别式名字的来源**：`Run\Serialization\RunJson.cs:141-151` 里 `RegisterIntentConditions`
逐条注册了这 10 个字符串（✔ 我把 10 条都读到了）。**这证明 IR kind 名就是这个字典**，
不是别的映射。

**参考实现自己声明了这一套为什么不复用效果程序的表达式机制**（`EnemyIntentRules.cs:12-15`，✔）：
"intent selection happens when NO effect is executing … so the effect-program expression
machinery — which needs an `EffectExecutionContext` — does not apply."
⇒ **不要把它接进 `expr.rs`。**它是另一套求值器。

### 3.6 本内容实测：只有 2 种条件、5 条规则、3 个敌人（✔ 实测）

`ENCT` 149 条 enemy record 里：

* **有 ≥1 条规则的敌人：3 / 149**（146 个是纯循环）
* 规则条数分布：`{1: 2, 3: 1}`
* Priority 取值：`{10: 3, 20: 2}`
* 条件 kind：`intent.selfHasCounter` ×4、`intent.opponentCardsPlayed` ×1
* **另外 8 种条件在本内容里一次都没出现** ⇒ 它们的 IR kind 在镜像里根本不存在（opcode 是从"实际出现的 kind"分配的）

逐条（✔ 实测输出）：

```
city_easy_01        a_very_official_line  maxHP=29  cycle=[shuffle_forward, compress_the_queue, shuffle_backward]
  P10 -> a_very_official_line.everyone_moves
         intent.selfHasCounter{Counter:"queue_position", Op:GreaterOrEqual, Value:3}

city_normal_ordinance_04  contradictory_signpost  maxHP=49  cycle=[turn_in_place]
  P20 -> contradictory_signpost.dangerous_shortcut
         intent.selfHasCounter{Counter:"signposted_route", Op:Equal, Value:1}
  P20 -> contradictory_signpost.long_administrative_route
         intent.selfHasCounter{Counter:"signposted_route", Op:Equal, Value:2}
  P10 -> contradictory_signpost.no_route_listed
         intent.opponentCardsPlayed{LastTurn:true, Op:Equal, Value:0}

city_normal_delay_07  minute_moth  maxHP=36  cycle=[nibble_the_hour, dusty_wings, land_on_the_clock]
  P10 -> minute_moth.wingbeat_delay
         intent.selfHasCounter{Counter:"stolen_minute", Op:GreaterOrEqual, Value:2}
```

### 3.7 ⚠️ 本内容里这 5 条规则**依赖内核还不存在的东西**（✔ 实测）

我把全镜像所有 `node.setCombatantCounter` 的落点都扫了一遍：

* **5 处**在 EACT 的 Program 里，**全部是把计数器置 0**（`Amount: const 0, Relative: false`），
  而且每一个都是**那条 override 动作自己**：

  ```
  EACT[3]   a_very_official_line.everyone_moves        queue_position   := 0
  EACT[255] contradictory_signpost.dangerous_shortcut  signposted_route := 0
  EACT[256] contradictory_signpost.long_administrative_route signposted_route := 0
  EACT[275] inverted_hourglass.turn_the_glass          stolen_sand      := 0
  EACT[286] minute_moth.wingbeat_delay                 stolen_minute    := 0
  ```

  即 `EnemyIntentRules.cs:81-84` 描述的那个模式："a triggered effect bumps a counter … a
  high-priority intent rule fires the special action while the counter matches, **and that
  action resets the counter**"（✔ 设计意图与实现一致）。

* **谁把计数器加上去？**
  * `queue_position` ← `STATUS[7] queue_advances` 的 `Triggers`（×2）
  * `signposted_route` ← `ENCT city_normal_ordinance_04.TriggeredEffects`（×8）
  * `stolen_minute` ← `STATUS[20] stolen_minute_passive` 的 `Triggers` 与
    `ENCT city_normal_delay_07.TriggeredEffects`

⇒ **三个计数器全部由"触发器程序"驱动，而内核没有触发器系统。**
所以：**一个忠实实现的 `intent.rs` 在这份内容上会永远走 B3（循环分支）** ——
因为 4 条 `selfHasCounter` 规则永假。这不是"实现错了"，是内容的依赖没到位。

* 第 5 条 `intent.opponentCardsPlayed` **不需要触发器**，它只需要**每回合出牌统计**。
  而内核**故意没有**这张表（`play.rs:54-56`，✔：「本内核没有这张统计表」）。
  ⇒ 这一条需要新增状态，或者**响亮拒绝**。

**这两条是本层最诚实的边界，写在这里以免将来被当成"已经做完"。**

---

## 4. 动作的数据形状（`EACT` 行，全部实测）

### 4.1 7 格逐格（✔ 代码 + 实测）

`schema` 来源两处，逐字一致：
`tools\contentc\rdcfmt.py:249-253` 与 `kernel\rd-core\src\content.rs:1055-1064`（✔ 对照过）。

| 格 | 键 | 字段种类 | 实测（394 行） | 是什么 |
|---|---|---|---|---|
| 0 | `Id` | `F_STR` | **394 有值** | 动作 id，`<enemy>.<action>` 拼法 |
| 1 | `NameKey` | `F_STR` | **394 ABSENT** | 表现层名字键（core 镜像剥掉了） |
| 2 | `DescriptionKey` | `F_STR` | **394 ABSENT** | 表现层描述键（同上） |
| 3 | `PackageId` | `F_STR` | **394 = `"scenario"`** | 包名。本内容只有一个值 |
| 4 | `Intent` | `F_TERM` | **394 有值** | `_obj(Kind)`，见 §4.4 |
| 5 | `Program` | `F_TERM` | **394 有值** | **指向效果程序的那一格** |
| 6 | `extra` | `F_TERM` | **394 = NULL**（不是 ABSENT） | 兜底键集。本内容一条都没用 |

`stride = 16`（7 格 = 14 B → align4 = 16，末尾 1 个填充 u16 不是数据格，`content.rs:1091-1134`，✔）。

### 4.2 394 条的分布（✔ 实测）

* EACT 行数：**394**（`content.rdcf` 与 `content.core.rdcf` 都是 394）
* distinct `Id`：**394**（没有重复）
* id 长度：最长 **54** B（`queue_crier_homunculus.call_a_number_that_is_not_yours`），
  **39 条 > 40 B** ← 这条会影响 §8.1 的 id 容量选择
* **带条件的动作行：0**（没有条件格，`extra` 全 NULL，程序里 `node.conditional` 0 处）
* **带权重的动作行：0**（没有权重格，镜像里唯一的 `Weight` 字段属于 `_obj(Value,Weight)` op=122 的 99 条 term，那是 run 层奖励池，不在 EACT 里）
* **带冷却的动作行：0**（没有冷却格）

### 4.3 `Program` 格：根节点 kind 分布（✔ 实测）

394 条**全部**是同一个信封形状 `_obj(Id, MaxNodeDepth, MaxProgramSteps, Root)`（op **116**，
`opclass=1` 普通对象、**没有 `kind`**）。信封里的三个常量是**固定值**：

* `Id` = `"(unnamed)"` × **394**
  （`EnemyActionDefinitions.cs:84-85` 会在 `Build()` 时把它改写成
  `enemy-action:{Id}:on-execute`，所以镜像里那个 `(unnamed)` 是**改写前的作者值**，✔）
* `MaxNodeDepth` = `64` × 394
* `MaxProgramSteps` = `1024` × 394

**根节点 kind 分布（394/394 全落在 4 种）**：

| 根 kind | 条数 |
|---|---|
| `node.sequence` | **199** |
| `node.dealDamage` | **95** |
| `node.applyStatus` | **59** |
| `node.gainBlock` | **41** |

**全深度 kind 词表（任一深度出现即计入）**：

| kind | 次数 | | kind | 次数 |
|---|---|---|---|---|
| `const` | 622 | | `sel.allAllies` | 20 |
| `sel.eventTarget` | 430 | | `multiply` | 9 |
| `node.applyStatus` | 239 | | `combatantStatusStacks` | 8 |
| `node.dealDamage` | 235 | | `node.setCombatantCounter` | 5 |
| `node.sequence` | 199 | | `add` | 4 |
| `sel.source` | 173 | | `min` | 3 |
| `node.gainBlock` | 135 | | `divide` | 1 |
| | | | `combatantCounter` | 1 |

**这张表是本层最重要的"内容规模"事实**：394 个敌方动作程序只用了
**5 种节点 + 3 种选择器 + 6 种表达式**。

* 节点：`sequence` / `dealDamage` / `applyStatus` / `gainBlock` / `setCombatantCounter`
  —— 全部已在 `exec.rs` 实现（`exec.rs:684-691`、`:791-794`，✔）
* 选择器：`sel.eventTarget` / `sel.source` / `sel.allAllies` —— 内核 `targets.rs:82-105`
  都有对应变体（`EventTarget` / `Source` / `AllAlliesOfSource`，✔）
* 表达式：`const` / `multiply` / `add` / `min` / `divide` / `combatantStatusStacks` / `combatantCounter`
  —— `expr.rs:277-308` 的 `INT_KINDS` 全覆盖（✔）

⇒ **执行侧今天就是齐的**（这也是 §8 结论的依据）。

### 4.4 `Intent` 格：只有 `Kind`（✔ 实测）

* 394 条全部是 op **118** `_obj(Kind)`（`opclass=1`，普通对象）
* `Kind` 分布：

| Kind | 条数 |
|---|---|
| `Special` | **168** |
| `Attack` | **110** |
| `Debuff` | 51 |
| `Defend` | 44 |
| `Buff` | 21 |

* **`Label` 在 core 镜像里不存在**（§2.6）。全镜像里 `Label` 存在 394/394。
* `IntentKind` 枚举 = `Unknown/Attack/Defend/Buff/Debuff/Special`（`ActionIntent.cs:5-13`），
  本内容未用 `Unknown`。显示用字形在 `ActionIntent.cs:25-48`（⚔🛡▲▼✦•）—— 纯表现，内核不需要。

### 4.5 ⚠️ 冻结方描述有误 #1：没有"权重/条件/冷却"格（✔ 实测）

任务书里问："`EACT` 行的 7 个格分别是什么、…、哪一格是权重/条件/冷却"。

**实测答案：没有这样的格。**7 格全部是上面 §4.1 那 7 个，`extra` 在 394/394 上是 NULL。
镜像里既没有 `Weight`/`Chance`/`Cooldown`/`Priority` 出现在任何动作行里，
也没有任何动作程序含 `node.conditional`（0/394）。

**所有"条件"都在别处**：在 `ENCT` 行 → enemy record → `IntentRules`（§5.3）。
**所有"顺序"也在别处**：在 `ENCT` 行 → enemy record → `Actions`。

也就是说：**`EACT` 是"动作库"，`ENCT` 才是"敌人与它的脚本"。**这条分工是 §8 接口设计的根本约束。

### 4.6 ⚠️ 关于那 99 条 `Weight` term（✔ 实测，✘ 未精确定位）

镜像里有 99 条 `_obj(Value,Weight)`（op=122）term。我用**槽位图可达性**粗扫过一遍
（会因 AUX/串槽位与本表别名而**过近似**），得到 15 条"可能从 EACT.Program/ENCT 可达"——
这个数**不可信**。**可信的是**：我用**解码后的 JSON 图**精确遍历了 394 个动作程序的
**每一个键**（28 个不同的键：`Amount/Cardinality/Charges/Children/CounterId/Dividend/Divisor/
DurationTurns/Element/Id/IgnoresBlock/Left/MaxNodeDepth/MaxProgramSteps/Relative/
RequiredContextCapabilities/ResultKey/Right/Root/Selector/Stacks/StatusDefinitionId/StatusId/
TargetSelector/Value/ZeroPolicy/kind/value`），**`Weight` 一次都没出现**（✔）。
⇒ 敌人的动作程序里没有任何权重。那 99 条属于 run 层（奖励池），与敌人无关。

---

## 5. 和遭遇（`ENCT`）的关系

### 5.1 `ENCT` 的 8 格（✔ 代码 + 实测）

| 格 | 键 | 种类 | 实测（109 行） |
|---|---|---|---|
| 0 | `Id` | `F_STR` + **`FLAG_WRAP_UPPER`** | 109 有值，最长 26 B |
| 1 | `Enemies` | `F_TERM` | 109 有值 ← **敌人名单在这里** |
| 2 | `HeroResources` | `F_TERM` | 109 有值，全是 1 条（`standard.energy 3/3`） |
| 3 | `HeroStartingStatuses` | `F_TERM` | 109 有值，全是 1 条 |
| 4 | `TriggeredEffects` | `F_TERM` | 99 条空 / 6 条 1 项 / 3 条 5 项 / 1 条 10 项 |
| 5 | `HeroDisplayName` | `F_STR` | **109 ABSENT** |
| 6 | `CardsDrawnPerTurn` | `F_INT` | **109 = NULL**（不是 ABSENT；⇒ 走 blueprint 默认 5） |
| 7 | `extra` | `F_TERM` | **109 = NULL** |

注意 `Id` 的**大写包装拼法** `{"Value": s}` 是 `ENCT` 独有的（`rdcfmt.py:255`
`FLAG_WRAP_UPPER`；`EnemyActionDefinitionId` 那种小写 `{"value": s}` 则是 `F_TERM`）。
内核 `content.rs:1068` 已经把 `FLAG_WRAP_UPPER` 冻在 schema 里（✔）。

### 5.2 敌人名单：149 条 record，形状固定（✔ 实测）

* 109 条遭遇共 **149 条 enemy record**；分布：`{1 个敌人: 76, 2: 26, 3: 7}`
* **149/149 是同一种 shape**：`_obj(Actions, Id, IntentRules, MaxHealth, Position, StartingStatuses)`
  —— **六个键全部存在**（`IntentRules` 在 146 条上是空列表，`Position` 全是 `null`）
* `MaxHealth`：11–132（53 个不同值）
* `StartingStatuses`：129 条空 / 17 条 1 项 / 3 条 2 项
* enemy record 的 `Id`：**118 个不同值，其中 24 个被 ≥2 条遭遇复用**
  （例：`stamp_goblin` 出现在 `city_easy_02 / city_normal_01 / city_normal_09`）
  ⇒ 同一个敌人定义在不同遭遇里可以有**不同的 `Actions` 脚本**（这一点我没逐对比较，✘ 未验证）

形状对照 C# 类型 `EncounterEnemy`（`Run\Combat\Encounters.cs:80-89`）：
`Id, MaxHealth, Actions, StartingStatuses, DisplayName, Position, IntentRules` ——
7 个 JSON 键，镜像里 6 个（`DisplayName` 未出现）。✔

### 5.3 敌人 ↔ `EACT` 的关联方式：**按 id 字符串**（✔ 实测）

enemy record 的 `Actions` 是 **term 列表**，每个元素解码成 `{"value": "<eact id>"}`
（`_wrap_lower`，即 `EnemyActionDefinitionId`）。`IntentRules[].Action` 同形。

> ⚠️ **2026-10-17 冻结方更正（实装时顶回来的，这条会咬人）**：
> 上面那句"`Actions` 是 term 列表、元素是 `_wrap_lower`"说的是**解码后的 JSON 形状**，
> **不是二进制形状**。二进制里它是 **`F_STRLIST + FLAG_WRAP_LOWER`**，`AUX` 里存的是**串号**，
> 整份镜像里**连一个 `_wrap_lower` term 都没有**。
> 照原文实现会读到不相干的数据，而且**不会报错**（当成空列表或错位的 term id）。
> `IntentRules[].Action` 是 `F_STR + FLAG_WRAP_LOWER`（同样存串号），也不是 term。


实测覆盖率：

* `Actions` 里出现的 distinct id：**389**
* `IntentRules[].Action` 里出现的 distinct id：**5**（`everyone_moves` / `dangerous_shortcut` /
  `long_administrative_route` / `no_route_listed` / `wingbeat_delay`）
* **`389 + 5 = 394`，两组不重叠** ⇒ **每一条 EACT 行都被某条遭遇用到，没有孤儿，没有悬空引用**（0 条 dangling）
* 每个敌人的 `Actions` 条数分布：`{1: 1, 2: 9, 3: 107, 4: 20, 5: 12}`（合计 480 个槽位、389 个不同动作 ⇒ 91 处复用）

⇒ **`Actions` 是"顺序循环脚本"，`IntentRules` 是"条件覆盖"，两者可以引用同一个动作，
但本内容恰好没有重叠。**

匹配是**字符串相等**，不是表索引：`CompiledScenarioEnumerator` 里
`EnemyIntentSelectors.Build` 用 `compiled.Enemies.ToDictionary(e => e.CombatantId)`
（`EnemyIntentRules.cs:153`），引擎侧用 `registry.TryGetEnemyAction(id, out _)`
（`InteractiveCombat.cs:363`）。镜像的 `IDX` 段提供了 `id → (elkind, index)` 的映射
（`reader.py:119-128`，`content.rs:162-177`），实测 `lookup("a_very_official_line.shuffle_forward")
→ (3= enemy_action, 0)`（✔）。

**这也意味着：敌人与自己脚本的绑定靠"战斗员 id == enemy record 的 Id"。**
✔ `Encounters.cs:213` `new EnemyBlueprint(spec.Id)` → `ScenarioCombatFactory.cs:112-117`
`new CombatantState(blueprint.CombatantId, …)`，而 `CombatantId => new(Id)`（`Blueprints.cs:212`）。

### 5.4 一条遭遇怎么决定"场上出现哪些敌人"（✔）

1. Run 层按节点/分布选一个 `EncounterId`（`Run\Map\EncounterSelector.cs`、`EncounterDistribution.cs`
   —— 我**没读这两个文件**，✘ 未验证选择策略）。
2. `EncounterCatalog.Build`（`Encounters.cs:174-223`）把 `EncounterEnemy` 逐条投影成 `EnemyBlueprint`：
   `:211-220` 按**遭遇里写的顺序** `foreach (var spec in encounter.Enemies)`，
   把 `spec.Actions` 一条条加进 `enemy.Actions`、`spec.IntentRules` 一条条加进 `enemy.IntentRules`。
3. `ScenarioCombatFactory.Build`（`:19-24`）按 `[Hero, Allies…, Enemies…]` 调 `AddCombatant`，
   而 `AddCombatant` **追加**到 `_turnOrder`（`CombatState.cs:232`）。

⇒ **`Enemies` 的列表顺序 = 上场顺序 = 回合顺序。**这是一个"顺序即语义"的点。

### 5.5 ⚠️ 冻结方描述有误 #2：`ENCT` 不是"遭遇 → 敌人种类"的纯表

任务书里说"一条遭遇怎么决定场上出现哪些敌人"。答案不只是"读 `Enemies`"：
**`Enemies` 里的每条 record 自带 `MaxHealth`、`StartingStatuses`、`Actions`、`IntentRules`**。
⇒ 遭遇不是"引用敌人定义"，而是**内联定义这一场里的敌人**。同一个 `Id` 在不同遭遇里是两条独立记录。
这对内核很重要：**不能建一张"敌人定义表"，敌人的血量和脚本是"遭遇 × 槽位"级别的数据。**

---

## 6. 执行路径

### 6.1 请求 → handler（✔）

`ExecuteEnemyActionEffectRequest(ActorId, ActionId, TargetCombatantId?)`
（`EnemyActionEffects.cs:6-10`）→ `ExecuteEnemyActionEffectHandler.Resolve`（`:12-65`）：

```
:20-21  if (!TryGetCombatant(actor) || !actor.IsAlive) return;     ← 死掉的敌人：静默 no-op
:23     var action = registry.GetEnemyAction(request.ActionId);     ← 未注册 ⇒ 抛异常
:33-62  如果有人监听 ActionStarting：先"宣布"，等它跑完再动
:64     否则立刻 Act
```

### 6.2 "先宣布"分支（✔）

`Listens`（`:69-75`）判断：注册表里存在 `ActionStartingCombatEvent` 的触发器，且
（该触发器无 gating status **或** 场上有人带那个 status）。
有监听时：入队 `ActionStartingCombatEvent`、把 `WhenSettled` 排成 continuation（`:33-37`），
等"宣布后新起的程序"全部跑完（`:41-45`）之后：

* 若该战斗员身上有 `standard.action_fails`（`StandardCombatIds.cs:30`）：**移除它、
  记一条 `EnemyActionFailed` 日志、并且仍然"开一个动作再关掉"**（`BeginActionScope` + `CloseAction`，
  `EnemyActionEffects.cs:48-58`）。⇒ **失败的动作也算一次动作**（`ActionResolved` 会发）。
* 否则 `Act`。

`standard.action_fails` 这个状态由标准包注册（`StandardCombatPackage.cs:37, 494-503`）。
内核有这个概念吗？**没有**（没有事件队列、没有 trigger），所以这条分支在内核 v1 里必然不可达。

### 6.3 `Act` 的三件套（✔）

`:82-89` 记日志 + 入队 `EnemyActionExecutedCombatEvent`；
`:91-96` 造 build context：

```csharp
new CombatantTargetSelectionContext(Combat: combat, Source: actor,
                                    EventTargetId: request.TargetCombatantId)
```
⇒ **`source` = 出手的敌人，`event_target` = 请求里的目标**（可能为 null）。

`:101` `combat.BeginActionScope();` —— 开一个"动作作用域"（用于"每动作一次"的声明与
`ActionResolved.DealtDamage` 的判定）。
`:104-110` 先跑旧式 `Effects` 配方（本内容没有，`EnemyActionDefinition.Effects` 为空）。
`:112-122` 再跑 `Program`：
`:123-126` 没有 `Program` 时就只排一个 `CloseAction`。
`:119, :121` `onComplete: null`，`onTerminal: (_, c) => CombatCardPlayProcessor.CloseAction(c, actorId)`。

`CloseAction`（`Cards\CardPlay.cs:306-312`）：`EndActionScope(out dealtDamage)`，
作用域真的关了才入队 `ActionResolvedCombatEvent(actor, dealtDamage)`。

### 6.4 和出牌**同一条**执行器（✔ 逐行对照）

| | 出牌 | 敌方动作 |
|---|---|---|
| 调用 | `EffectProgramExecutor.Execute(program, executionContext, combat, onComplete: null, registry: registry.EffectNodeExecutors, onTerminal: …)`（`CardPlay.cs:273-281`） | 同（`EnemyActionEffects.cs:114-122`） |
| context | `EffectExecutionContext<CardPlayContext>(new CardPlayContext(card, cardInstanceId), buildContext)`（`CardPlay.cs:266-267`） | `Execute` 的 4 参重载内部 new（`EffectProgramExecution.cs:67-87`），context = `EnemyActionContext(action)` |
| `onTerminal` | 先搬卡，再 `CloseAction` | 只 `CloseAction` |
| 作用域 | `BeginActionScope`（出牌路径） | `:101` `BeginActionScope` |

⇒ **是同一个 `EffectProgramExecutor`。**唯一真正不同的是 context 类型与终结处理。

### 6.5 目标解析的边界（✔）

`sel.eventTarget` 在**三种情况**下解析为空集，而**空集不是错误**：

* `EventTargetId is null` → 空（`CombatantTargetSelectors.cs:122-123`）
* 目标不在场上 → 空（`:127-128`）
* **目标已倒下 → 空**（`:130-132`）

`sel.allAllies` 含**自己**（`TeamId == Source.TeamId && IsAlive`，`:145-150`）。
⇒ 敌人用 `sel.allAllies` 的 20 处是"给己方全队（含自己）上状态"。

内核对应：`targets.rs:212-213` 的 `ExecContext.event_target: Option<CombatantId>`，
且 `targets.rs:42` 明确写了"**空集不是错**"。✔ 语义已经对齐。

### 6.6 内核侧的现成映射（✔）

```
参考                               内核
EnemyActionContext(action)      →  （不需要：context 只被程序用来读 Action，本内容 0 处）
CombatantTargetSelectionContext →  exec::ExecContext { source, event_target, … }
  Source: actor                     source: Some(enemy)
  EventTargetId: target             event_target: Some(target) / None
program.MaxProgramSteps = 1024  →  ExecContext.max_steps: 1024
registry.EffectNodeExecutors    →  exec::execute(root, &mut ctx)
```

`ExecContext` 见 `kernel\rd-core\src\exec.rs:296-312`，入口 `exec::execute` 在 `:484`（✔）。

---

## 7. 失败 / 边界（每一条都给行号）

> 下面每一条都区分**参考实现真正做了什么**与**有没有测试钉住**。

### 7.1 选择器返回 `null`（没有可用动作）

`InteractiveCombat.cs:363` 的 `if` 不成立 → 走 `:376-377` 的 `else` →
**只调 `watch?.Invoke(enemyId, actionId, 0, 0)`，然后什么都不做**。
之后 `:379` 检查战斗是否结束、`:383-384` **照常结束这个敌人的回合**。

⇒ **"没有动作" = 这个敌人的回合被白白消耗掉**（turn-start 与 turn-end 的自动化仍然全部发生）。
✔ 读码。✘ 无测试专门钉住这一点（我 grep 了 `EnemyActionTests` / `EnemyIntentRulesTests`，没有）。

### 7.2 选到了未注册的动作 id

同上：`:363` 的 `_registry.TryGetEnemyAction(id, out _)` 为 false ⇒ 与 7.1 完全同一条路径。
注意**这不抛异常**（只有 handler 里的 `registry.GetEnemyAction` 会抛，而那是走不到的）。

### 7.3 敌人一个动作都没有（`Actions` 空 + `IntentRules` 空）

`EnemyIntentRules.cs:164-166` 走 B4 ⇒ `null` ⇒ 同上 7.1。
本内容**没有这种敌人**（`actions-per-enemy` 分布里最小是 1）。

### 7.4 条件都不满足

`EnemyIntentRules.cs:159-162` 循环走完不返回 ⇒ **落回 `:164` 的循环分支**。
**不是"跳过回合"**。这是设计（`EnemyIntentRules.cs:9-10`：`"If no rule matches, the enemy
falls back to its plain Actions cycle (round-based), so an enemy with no rules behaves
exactly as before."`）✔。

### 7.5 敌人在**自己回合开始前/中**被打死

三种子情况：

**(a) 回合开始前就死了** —— 不该轮到它：`CombatTurnProcessor.cs:86-98` 有跳过死者的循环，
但**那个循环在 `StartCurrentTurn` 之前**。若死发生在 turn-start 自动化里（见 (c)），跳过逻辑不会再跑。

**(b) 自己回合被 DoT 打死** —— DoT 在 `StartCurrentTurn` 里同步结算
（`StandardCombatPackage.cs:139` → `DamageOverTimeOnTurnStartedHandler`，
`StatusEffects.cs:449-474`，落在 `turn.rs:672`）。于是：
`EndCurrentTurnAndStartNextTurn` 返回时，**active 是一个已经死了的战斗员**。
`InteractiveCombat.cs:358` 的循环条件只看 `ActiveCombatantId != hero`，不看存活 ⇒
**会为这个死敌人选一个动作**（`:361`），然后
`EnqueueEffect(ExecuteEnemyActionEffectRequest(...))`（`:370`）——
handler 在 `EnemyActionEffects.cs:20-21` 直接 return。
**但 `:372` 的 `Record(new EnemyActs(...))` 无条件执行** ⇒
**叙事日志会声称这个死敌人"行动了"。** ✔ 读码（无测试钉住，我 grep 过 `DiagnosticCombatLog`/`EnemyActionTests` 没找到）。

**(c) 在自己动作里被打死**（荆棘/反伤）—— 程序继续跑到终结，`CloseAction` 照跑
（`CardPlay.cs:306-312` 里 `TryGetCombatant` 只是判存在，不判存活）；
之后 `:383` `if (ActiveCombatantId == enemyId)` 仍成立 ⇒ 正常结束它的回合，
`:170-212` 的 `AdvanceToNextCombatant` 会跳过死者。✔ 读码。

### 7.6 全部敌人倒下

`MarkCombatantDownedOnZeroHealthHandler`（`Combatants\CombatantLifecycleEffects.cs:156`）
→ `CombatantLifecycleChangedCombatEvent` → `UpdateStandardCombatResultOnLifecycleChangedHandler`
（`CombatStateEffects.cs:28-59`）：无存活敌人 ⇒ `Victory`；无存活玩家 ⇒ `Defeat`；两边都没 ⇒ `Draw`。

⇒ `InteractiveCombat.cs:379` 的 `if (Result != Ongoing) break;` 直接跳出，
**英雄的下一个回合不会被启动**（`:384` 那句没跑）。✔ 读码。

### 7.7 循环保险丝：`TurnOrder.Count + 2`（✔）

`InteractiveCombat.cs:356-357` + `:386-387`：超过就 `break`，**不报错、不记录**。
`ScenarioRunner.cs:210, 236` 有两个同型保险丝（后者会 `problems.Add(...)`，
前者 `:214-218` 也会记）。⇒ **driver 的保险丝分两种：一种静默、一种留痕。**
内核复刻时要注意：静默 break 会让"回合没绕回英雄"变成不可观察。

### 7.8 目标已死 / 不存在

见 §6.5：动作**照常"执行"**，只是打空（`CardZoneEffects` 那类不是，是 `dealDamage` 的目标集为空）。
`sel.source` 的 173 处与 `sel.allAllies` 的 20 处不受影响。✔

### 7.9 运行时召唤出来的敌人

`SummonCombatantEffectHandler` 会 `combat.AddCombatant(summoned)`
⇒ 进回合序（`CombatState.cs:232`）⇒ 会拿到 turn-start、会被 driver 问"你做什么"。
但选择器只认 `compiled.Enemies`（`EnemyIntentRules.cs:153,156`）⇒ **返回 `null` ⇒ 站着不动**。
✔ 读码（两端都读了）。

### 7.10 一次动作的步数上限

信封里 `MaxProgramSteps = 1024`（394/394 实测）。参考的 `EffectProgramExecutor` 在超步时抛
`InvalidOperationException`（`EffectProgramExecution.cs:109-114`）⇒ 整个程序 fault ⇒
`onTerminal(Faulted)` 仍然 `CloseAction`（`EnemyActionEffects.cs:121`）。✔
内核有 `ExecError::StepLimit`（`exec.rs:243`）。

---

## 8. 对 Rust 界面的建议（**不写实现**）

### 8.1 建议的模块形状

**一个模块 `intent.rs`，四个公有项。**理由是这一层只需回答两件事：
"选中哪个动作"和"把这个动作跑起来"，而"跑"已经 100% 现成。

```rust
// ── 内容侧的借用视图：ENCT 行的 enemy record ────────────────────────────────
/// 一个敌人的"脚本"。**来自 ENCT 行，不是 EACT 行**（§5.3）。
pub struct EnemyScript<'a> {
    pub combatant: &'a str,       // enemy record.Id，最长实测 24 B
    pub actions: &'a [u16],       // Actions 的 term id 列表（顺序即循环序）
    pub rules: &'a [RuleRef<'a>], // IntentRules，已按 Priority 降序排好（排序不在本函数里做）
    pub max_health: i32,
}

// ── 选择 ───────────────────────────────────────────────────────────────────
pub enum ChoiceReason {
    /// `Actions[(round-1) % len]`。`slot` 留给测试断言"确实是第几条"。
    Cycled { round: i32, slot: u16 },
    /// 命中了第 `index` 条规则（已在降序后的序里）。
    Rule { index: u16, priority: i32 },
}

pub struct ActionChoice {
    pub action_row: u32,          // EACT 行号
    pub intent_kind: Option<IntentKind>, // 只有 Kind；Label 在 core 镜像里不存在（§2.6）
    pub reason: ChoiceReason,
}

/// 纯函数：**不动状态、不推进 RNG、不分配。**
pub fn select_action(
    state: &CombatState,
    content: &Content<'_>,
    script: &EnemyScript<'_>,
    actor: &CombatantId,
    round: i32,
) -> Result<Option<ActionChoice>, IntentError>;

/// 条件求值（单独暴露，因为它是 10 个原语，测试要逐个打）。
pub fn condition_matches(
    state: &CombatState,
    content: &Content<'_>,   // 只用于把 CounterId/StatusId 串解析出来
    cond: NodeRef<'_>,
    actor: &CombatantId,
) -> Result<bool, IntentError>;

// ── 执行 ───────────────────────────────────────────────────────────────────
/// 与 `play::play_card` 同构：严格面。**失败时状态保证不变。**
pub fn execute_action(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    actor: &CombatantId,
    action_row: u32,
    target: Option<CombatantId>,
) -> Result<ExecStats, IntentError>;

/// 请求面：死掉的 actor / 未注册的动作 → `Ok(NOT_EXECUTED)`，与参考的 no-op 同构。
pub fn try_execute_action(...) -> Result<ActionReport, IntentError>;
```

**必须补的一个访问器**（`ir.rs` 现在只有卡版本）：

```rust
// ir.rs:489 的 card_program_root 只认 Table::Card。
// EACT 的 Program 格形状**完全相同**（op 116 `_obj(Id,MaxNodeDepth,MaxProgramSteps,Root)`），
// 实测 394/394。建议加同形的 enemy_action_program_root(index)。
pub fn enemy_action_program_root(&self, index: u32) -> Result<NodeRef<'a>, IrError>;
```

**接口的三条硬约束**（每条都有实测依据）：

1. **`select_action` 必须拿到"遭遇 + 槽位"，不能只拿到 combatant。**
   脚本（`Actions` / `IntentRules`）在 `ENCT` 里（§5.3），`EACT` 只有动作库。
   ⇒ 别把签名写成 `select_action(state, actor)`。**这是本层最容易设计错的地方。**
2. **不要给 `EnemyActionId` 用 `Ident<40>`。**
   `state.rs:114` 的 `ID_CAP = 40`，但实测 **39/394 个动作 id 超过 40 B**，
   最长 54 B（`queue_crier_homunculus.call_a_number_that_is_not_yours`）。
   要么给一个 `ENEMY_ACTION_ID_CAP = 56`，要么直接用 `&'a str` 借镜像的串池
   （后者更符合"零分配"）。而 `CombatantId` / `EncounterId` 用 40 就够（实测 ≤24 / ≤26）。
3. **`intent_kind` 只有 `Kind`。**core 镜像里 `Label` 不存在（§2.6）。想显示标签只能用全镜像。

### 8.2 哪一部分必须由内容决定，哪一部分是引擎硬编码

| 环节 | 谁决定 | 依据 |
|---|---|---|
| **动作有哪些** | **内容**（`ENCT` → `Actions`） | §5.3 |
| **循环顺序** | **内容**（`Actions` 的列表顺序） | `EnemyIntentRules.cs:165` |
| **条件** | **内容**（`ENCT` → `IntentRules`，10 种原语） | §3.5 §3.6 |
| **优先级** | **内容**（每条规则一个 `Priority` 整数） | `EnemyIntentRules.cs:160` |
| **动作干什么** | **内容**（`EACT` → `Program` 效果程序） | §4.3 |
| **意图显示类别** | **内容**（`EACT` → `Intent.Kind`） | §4.4 |
| **敌人血量/初始状态** | **内容**（enemy record 的 `MaxHealth` / `StartingStatuses`） | §5.2 |
| 选择算法（"规则优先、否则循环"） | **引擎硬编码** | `EnemyIntentRules.cs:154-167` |
| `(round-1) % n` 的取模与 1-based 语义 | **引擎硬编码** | `:165` |
| 排序方向（降序）与稳定性 | **引擎硬编码** | `:160` |
| 10 个条件原语的**语义** | **引擎硬编码**（但**用哪些**是内容） | `:22-144` |
| `absent counter ⇒ 0` / `absent resource ⇒ 0` | **引擎硬编码** | `:91` `:102` |
| HP 百分比用交叉相乘 | **引擎硬编码** | `:46` |
| 谁先动（回合序） | **引擎 + 内容的顺序** | §3.3 §5.4 |
| "没有动作就跳过回合" | **引擎硬编码** | §7.1 |

**结论：这一层是"纯数据驱动"的，但驱动它的是 `ENCT` 而不是 `EACT`。**
只要接口按 (遭遇行, 敌人槽位) 取脚本，`intent.rs` 里就**一行内容相关的常量都不该有**
（唯一的数字是 `%` 和 `-1`，都来自算法本身）。

**唯一不能做成纯数据的是"选目标"**：单人模式写死 `_heroId`（`InteractiveCombat.cs:370`），
队伍模式是 5 种硬编码策略（`PartyCombat.cs:10-17, 158-173`）。这是**宿主策略**，不是内容，
建议 v1 只做单人（`target = Some(hero)`），队伍模式响亮拒绝。

### 8.3 建议的成对测试（瞄准危险的那一面）

本项目纪律：测试要瞄准"范围内会被拒的动作"，成对写。这一层建议：

1. **`Cycled` 与 `Rule` 必须给出不同结果**：同一个敌人，先无规则断言 `round 1/2/3` 的循环，
   再加一条恒真规则断言变成 override（照抄 `EnemyIntentRulesTests.cs:63-102` 的成对形状）。
2. **规则的兜底 ≠ 放弃**：一条永远不匹配的规则 + 一个非空 `Actions` ⇒ 必须落到循环，
   **不是** `None`（§7.4 最容易被写成"跳过"）。
3. **降序 vs 列表顺序**：列表里先写 Priority=1、后写 Priority=5，断言选 5。
4. **`round` 是 1-based**：`round=0` 会算成 `(-1) % n` —— C# 里 `-1 % 3 == -1` 会抛
   （`List` 负索引），Rust 里 `-1 % 3 == -1` 也负 ⇒ **必须显式拒绝 `round < 1`**。
   参考实现**没有**这个检查（`:165` 直接下标）⇒ 这是一处**内容/宿主出错时的崩溃面**，
   建议内核**响亮拒绝**并记录为有意偏差。
5. **死掉的敌人**：断言 `select_action` 对死 combatant 的返回值（决策 + 记录）
   与 `execute_action` 的 no-op 是两个不同的问题，**不能合并**（§7.5）。
6. **`event_target` 死了 ⇒ 空集而不是错误**（§6.5）。
7. **变异测试**：把 `% count` 改成 `% (count-1)`、把降序改成升序，测试必须变红。

### 8.4 这一层之前必须先补/必须拒绝的东西

| 缺什么 | 影响 | 建议 |
|---|---|---|
| 触发器系统（事件队列） | 4/5 条 `IntentRule` **永假**（§3.7）；`ActionStarting`/`ActionResolved`/`EnemyActionExecuted` 三个事件发不出 | **仍然要实现条件求值器**："计数器缺席读 0"是忠实语义，永假是内容的依赖没到位，不是我们编的。**不要**为了让它"看起来有动作"而特判。事件侧归到触发器那一轮 |
| 每回合出牌统计 `CardPlayTurnStats` | `intent.opponentCardsPlayed` 无法求值 | 响亮拒绝该 kind（`IntentError::UnsupportedCondition`）。⚠️ 内核 `play.rs:54-56` 明确写了"本内核没有这张统计表"；**但 `play.rs` 正在被并发实现**，若出牌那一轮把它补上了，这条自动解除 —— 接活前请重读 `play.rs` |
| `standard.action_fails` | 只有"先宣布"分支用到，v1 不可达 | 不需要 |
| 动作作用域（`BeginActionScope`/`EndActionScope`） | `ActionResolved.DealtDamage` 发不出 | 与本层解耦，归到触发器那一轮 |
| ENCT 行的 enemy record 解析 | **当前 `content.rs` 完全没有**（只有 `encounter(index)` 返回 8 格原值） | 需要一个新的借用视图层（`EnemyScript`），读 `ENCT.Enemies` 的 term 列表 |

**所以现实的范围建议**：`intent.rs` v1 = `select_action`（循环分支 + 规则框架，
条件只支持能在今天求值的那些）+ `execute_action`（直接调 `exec::execute`）。
**在这份内容上它能做的正好是 146/149 个敌人的循环，以及 3 个敌人的"按优先级检查、全部落回循环"。**

> ⚠️ **2026-10-17 冻结方更正**：上面这两个数字都不对。实装实测是
> **148/149 走循环 + 1 个明确失败**。原因：5 条 `IntentRule` 里
> **4 条 `intent.selfHasCounter` 是能忠实求值的**（缺席读 0），恒假只是因为
> **计数器只由触发器程序递增**（内核没有触发器）⇒ 它们会走完优先级检查再落回循环；
> 第 5 条 `intent.opponentCardsPlayed` 要 `CardPlayTurnStats`（内核故意没有）⇒ **响亮 `Err`**。
> 我原文把"能求值但恒假"错写成了"用不了"，差别很重要：前者是**能力齐、内容依赖缺**，
> 后者是**内核缺能力** —— 两者的排查方向相反。

这不是"做完"，但它**是**"一局能打"所缺的那一块，而且它的每一条边界都能被测试钉住。

---

## 9. 我没能验证的事（按重要性）

1. **没有跑过任何引擎。**所有"行为"都是从 C# 代码路径读出来的。特别是 §1.4 的
   "敌人白长 3/3 能量"、§7.5 的"死敌人被记成行动了"这两条，
   **强烈建议在执行侧用一次 oracle/dotnet 跑一次战斗来确认**（本任务的约束禁止我跑）。
2. **没有读过 `SimultaneousTurnProcessor` / `EncounterSelector` / `EncounterDistribution`。**
   队伍模式的敌方相位（`PartyCombat.cs:125-154`）的 turn-start 时机、以及 run 层怎么挑遭遇，
   我都只有调用点的信息。
3. **`OrderByDescending` 的稳定性**（§3.2）是 LINQ 的文档行为，未实测；
   但本内容里唯一存在 tie 的地方条件互斥，所以不可观察。
4. **`InteractiveCombat.cs:372` 的 `Record` 是否真的被渲染成一条"敌人行动了"的日志**
   —— 我读了 `NarrativeLogRenderer` 的存在但**没读它的实现**（`Scenario\Reporting\NarrativeLogRenderer.cs`）。
5. **重复出现的 enemy id（24 个）在不同遭遇里 `Actions` 是否相同** —— 我没逐对比较。
6. **`RequiredContextCapabilities` 字段**（出现在动作程序的 28 个键里）的语义 —— 我没读它。

---

## 10. 冻结方描述有误（汇总，供上一级修订）

| # | 冻结方的说法 | 真实情况 | 证据 |
|---|---|---|---|
| 1 | "`EACT` 行…哪一格是权重/条件/冷却" | **没有这三格。**7 格是 `Id/NameKey/DescriptionKey/PackageId/Intent/Program/extra`，且 `extra` 在 394/394 上是 NULL | §4.1 §4.5 |
| 2 | 隐含"遭遇引用敌人定义" | **遭遇内联定义敌人**（`MaxHealth`/`Actions`/`IntentRules`/`StartingStatuses` 全在 `ENCT.Enemies` 的 record 里） | §5.2 §5.5 |
| 3 | "394 条 EACT"（转抄旧报告） | **正确**：394（core 与 full 镜像都是 394）。但"109 条遭遇"→ **149 条 enemy record**，不是 109 个敌人 | §4.2 §5.2 |
| 4 | "意图…什么时候被选择、什么时候被公开/消耗" | **没有"消耗"这一环**；`CombatantState.IntentKey` 是**零调用者的死字段**；公开 = 每次问重算 | §2.2 |
| 5 | "RNG 从哪来（(seed, step) 那条流？推进几次？）" | **选择动作推进 0 次。**零 RNG。唯一随机在**队伍模式选目标**，且用的是 driver 的局部计数器 `_targetStep++`，**不是** `combat.RandomStep` | §3.4 |

> 第 1、2、4 条会直接导致接口设计错位：以为"动作自带条件/权重"会去做一个
> `EACT` 驱动的选择器，而真相是 **`ENCT` 驱动的选择器 + `EACT` 驱动的执行器**。

---

## 11. 实测方法与可复现性

脚本：`native\_recon_intent.py`（只读，不写任何东西；用完可删）。

```
python native\_recon_intent.py            # 主表：行数/逐格 presence/Program 根 kind/Intent/ENCT/enemy record/EACT 覆盖
python native\_recon_intent.py part2      # 解码图精确遍历：全深度 kind 词表、可疑键、enemy id 复用、core vs full 差异
python native\_recon_intent.py part3      # 逐条打印全部 5 条 IntentRule
python native\_recon_intent.py part4      # 全镜像 node.setCombatantCounter 落点
python native\_recon_intent.py part5      # 哪些动作程序置零计数器 + 哪些遭遇用到它们
python native\_recon_intent.py part6      # id 长度（EnemyActionId 容量论证）
```

全部数字来自 `tools\contentc\out\content.core.rdcf`（85,616 B，`content_hash=0xD1075DE5`）。
`part2` 同时跑了 `content.rdcf`（158,296 B）做对照，两者除表现层外**逐项一致**
（EACT 394 / ENCT 109 / enemy record 149 / Program 根 kind 分布 / 全深度 kind 词表 全部相同）。

**本次核对的规模**：C# 侧约 **30 个文件**（含 3 个测试工程的文件）、约 **70 处行号断言**；
Rust 侧 8 个文件、约 20 处；内容侧 **394/394** EACT 行、**109/109** ENCT 行、
**149/149** enemy record、**5/5** IntentRule、**5/5** `node.setCombatantCounter` 落点。
