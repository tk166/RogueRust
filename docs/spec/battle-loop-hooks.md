# 战斗回环钩子规格书：`TurnHost` 的 8 个必做钩子 + 6 个策略钩子

**参考实现**：`D:\Vibe\sts-tui\ref\RogueDeck-Core`（C# / .NET 10，MIT），锚点 commit `fd43e68ab91f40b475b745725abb17134b951c51`（只读，本次未改动）。
**被规格化的对象**：`kernel\rd-core\src\turn.rs:108-232` 的 `pub trait TurnHost`。
**内容镜像**：`tools\contentc\out\content.core.rdcf`（85,616 B，`content hash 0xD1075DE5`，23 status / 62 card / 394 enemy action / 109 encounter / 49 relic），用 `tools\contentc\reader.py` 读出。

**路径缩写**（下文所有 `文件:行号` 都基于这四个基址）：

| 缩写 | 实际路径 |
|---|---|
| `C:` | `ref\RogueDeck-Core\src\RogueDeck.Core\Combat\` |
| `SB:` | `ref\RogueDeck-Core\src\RogueDeck.Sandbox.Combat\Composition\` |
| `S:` | `ref\RogueDeck-Core\tests\RogueDeck.Sandbox.Tests\` |
| `K:` | `kernel\rd-core\src\` |

**标记约定**

- **【验证】** = 我逐行读过那段代码 / 实测过那个二进制，行号是我自己核出来的。
- **【未验证】** = 我没有读到证据，或读到了但没能独立确认。
- **【推测】** = 我按已有证据推的，没有直接证据。
- 所有行号取自 `read` 工具（不用 PowerShell 的 `Select-String` 行号——本机它报的行号与真实文件不符，`K:status_catalog.rs` 实测差 192 行）。

**本次验证规模**：§6.1 列了 **63 条**独立断言（每条带行号），§6.2 列了 **11 条**未验证项（含 3 件最重要的）。

---

## 0. 结论摘要

### 0.1 七步顺序：核实通过

任务给的口径「补能量 → pending 转正 → 触发器 → 解析队列 → 抽牌 → 清 Block → DoT」**与注册序一致**。行号（`C:StandardCombatPackage.cs`，`RegisterCombatEventHandler` 的调用序，本文件 :121-139）：

| # | 处理器 | 注册行 | 事件 | 谁做（在本内核里） |
|---|---|---|---|---|
| 0 | `ResetCardPlayTurnStatsOnTurnStartedHandler` | `:121` | TurnStarted | **不做**（内核没有每回合出牌统计，`K:turn.rs:565-568` 已如实标注） |
| 1 | `RefillResourceOnTurnStartedHandler(energy, defaultMax: 3)` | `:124` | TurnStarted | `K:turn.rs:571` |
| 2 | `ActivatePendingStatusesOnTurnStartedHandler` | `:126` | TurnStarted | **钩子 1** |
| 3 | `TriggeredProgramContextAdapters.TurnStarted.CreateHandler()` | `:127` | TurnStarted | **钩子 2** |
| 4 | `ResolveQueueOnTurnStartedHandler` | `:131` | TurnStarted | **无钩子**（见 §5.2） |
| 5 | `DrawCardsOnTurnStartedHandler(_cardsDrawnPerTurn)` | `:133` | TurnStarted | `K:turn.rs:599-600` |
| 6 | `ClearBlockOnTurnStartedHandler` | `:134` | TurnStarted | `K:turn.rs:607` |
| 7 | `DamageOverTimeOnTurnStartedHandler` | `:139` | TurnStarted | **钩子 4** |

**【验证】**：这 8 条是 `StandardCombatPackage.cs` 里**全部**的 `TurnStartedCombatEvent` 处理器。`:135-138` 那四条是 `TurnEndedCombatEvent`（我逐个查了它们的基类，`:140-151` 那批里只有 `ResetCardPlayTurnStatsOnTurnStartedHandler` 是 TurnStarted，`C:Cards\CardPlayTurnStats.cs:296`）。处理器容器是 `List` 尾插（`C:CombatDefinitionRegistryBuilder.cs:339-353`）+ `ImmutableArray.AddRange` 保序（`:463-468`），`GetCombatEventHandlers` 直接返回该数组（`C:CombatDefinitionRegistry.cs:223-229`）——**没有任何排序**。

所以「DoT 是最后一步」是真的（`:139` 注册在 `:134` 之后），而「七步」的说法少算了第 0 步。

### 0.2 与任务描述不一致的地方（冻结方描述有误）

| # | 说法 | 真相 |
|---|---|---|
| ① | 「`modifiers.rs` 里现有 `Pipeline` 枚举只有 `DamageDealt`/`DamageReceived`/`TurnStartDraw` 三条」 | **两条都错**。`K:modifiers.rs:34-45` 是 **4** 条：`DamageDealt`/`DamageReceived`/`Block`/`Cost`，**没有 `TurnStartDraw`**。`TurnStartDraw` 在另一个枚举里：`K:status_bind.rs:117-129`（`status_bind::Pipeline`，3 条：`DamageDealt`/`DamageReceived`/`TurnStartDraw`，**没有** `Block`/`Cost`）。参考实现的 `PassiveModifierPipeline` 是 **6** 条（`C:Effects\PassiveModifiers.cs:16-29`），内核两个枚举各取一半。 |
| ② | 「清 Block 在队列解析之前」（`K:turn.rs:24-25` 的模块头这么写） | **写反了**。注册序是 `:131` ResolveQueue → `:134` ClearBlock，即**清 Block 在队列解析之后**。同一个文件的 `K:turn.rs:605-606` 写的是对的，两处自相矛盾。`S:QueueTortureTests.cs:210-211` 的注释也写反了（「Block is cleared at the turn start BEFORE the Queue resolves」）。**11 点格挡之所以存活，原因不是这个**，见 §5.1——那是一个我读出来的、和注释完全不同的机制。 |
| ③ | 「`resolve_pending_queues` 对应第 5 步的 `ResolveOldest`」 | trait 的文档说它是「**任何**入队之后的排空（`C:CombatEventHandling.cs:81-115`）」（`K:turn.rs:124-127`），而 `start_current_turn` 的注释说第 5 步是「`ResolveQueueOnTurnStartedHandler` → `ResolveOldest(owner, int.MaxValue)`」（`K:turn.rs:588-590`）。**这是两个不同的东西**：前者排空「效果/事件/续延」三队列，后者解析战斗员的**牌区 QueuePile**。内核把同一个函数名用在两个语义上 ⇒ 今天**没有任何钩子负责解析 QueuePile**。 |
| ④ | 「`pending` 是『延迟 N 回合后生效』」 | 方向对，但来源错。`pending_turns` **不是**被施加状态自己声明的东西，而是**承受者身上已经生效的某个状态**的 `IncomingStatusDelay` 决定的（`C:Effects\StatusEffects.cs:124, 252-265`；`C:StatusDefinition.cs:41-44, 197-200`）。而且镜像里 23 个状态的 `IncomingStatusDelay` **全部为 null** ⇒ 今天这条路上 `pending_turns` 永远造不出非零值。 |
| ⑤ | 「DoT 与反射不受伤害修饰影响」 | 结论对，但**机制**要说清：DoT 走的是**同一套** `DealDamageEffectRequest` 处理函数，靠的是每条 spec 自己的 `RestrictDamageKind = Direct` 门（`C:Effects\PassiveModifiers.cs:85-87, 155`）。`K:status_catalog.rs:985` 那条测试断言的是**标准包三行**的 `RestrictDamageKind` 位，不是"伤害管线为 DoT 短路"。**告警**：`K:exec.rs:438-443` 的 `resolve_damage` 没有 `kind` 参数，直接拿它算 DoT 伤害会把力量/虚弱/易伤错误地算进去（`K:exec.rs:1789-1790` 的注释自己承认了这点）。 |
| ⑥ | 「`status_catalog.rs` 里有个 `decay_predicate` 概念」 | 名字对不上。函数叫 `decays_at_owner_turn_end`（`K:status_catalog.rs:661-664`），字段叫 `StatusMeta::decays_at_owner_turn_end`（`K:status_catalog.rs:357-359`），判据是**定义上的 `UsesDuration` 标记**（`C:Effects\StatusEffects.cs:394`），不是 id 名单也不是"有 duration 轴"这个推断。 |

### 0.3 一张总表：8 个必做钩子在 v1 里的真实工作量

判定依据只有两条：**(a) 参考实现在这个钩子上做了什么事；(b) 当前内容镜像里有没有东西会走到它**。

| 钩子 | 在镜像内容上有活干吗 | 标准包上有活干吗 | 定性 |
|---|---|---|---|
| `activate_pending_statuses` | **否**（23/23 状态 `IncomingStatusDelay` = null） | 否 | **可实现但今天必然空转**；实现成本极低（约 15 行），建议实现 |
| `run_turn_started_triggers` | **是**（3 条 TurnStarted 触发器：`fatigue` / `bookworm` / `queue_advances`） | 否（标准包没有状态触发器） | **真活**，且是最大的一块（需要新的触发器解码） |
| `resolve_pending_queues` | 取决于「宿主走不走入队模型」（§4.3） | 同 | **空实现就够，但前提是第 5 步真的没人需要** —— 见 §5.2，今天 QueuePile 无人解析 |
| `damage_over_time` | **是**（2 条带 `damage_over_time` 标签：`paperwork` / `poison`） | **是**（`standard.poison`，`C:StandardCombatPackage.cs:263-264`） | **真活**，且卡在一个缺参数上（§5.4） |
| `hand_turn_end_lifecycle` | **否**（62/62 卡 `LifecyclePrograms` = `{}`） | 否 | **已实现**（2026-10-19，见 §2.5）；内容一有 Burn 就走 |
| `run_turn_ended_triggers` | **是**（6 条 TurnEnded 触发器：`panic`/`poison`/`paper_seals_wax`/`one_remaining_seal`/`your_number_is_fading`/`counterclaim`） | 否 | **真活**。注意 **`poison` 的层数衰减就靠它**（§4.4） |
| `decrease_timed_statuses` | **否**（23/23 状态 `UsesDuration` = false） | **是**（16 个标准状态里 7 个 duration=true） | **今天空实现就够；跑标准包时必须实现** |
| `hand_is_retained` | **否**（无状态带 `retain_hand` 标签） | 否（`K:status_catalog.rs:1278` 的测试逐行钉住 16 个都没有） | **默认 `false` 就够** |

带默认值的策略钩子同理，见 §3 的逐条判定。

---

## 1. 参考实现的骨架：处理器 → 三个队列 → 一个排空循环

这一节是后面所有钩子的地基。**读不懂这一节，8 个钩子会全部写成"看起来对、和参考不一致"的样子。**

### 1.1 排空循环的精确形状

`StartCurrentTurn` 做的全部事情是（`C:CombatTurnProcessor.cs:15-37`）：三项校验 → `MarkTurnStarted`（只把 `TurnPhase` 从 `WaitingToStartTurn` 改成 `TurnInProgress`，`:324-330`）→ 记 trace/log → **`EnqueueEvent(TurnStartedCombatEvent)`**（`:28-32`）→ `ResolvePendingQueues`（`:34-37`）。

`ResolvePendingQueues`（`C:CombatEventHandling.cs:81-115`）：

```
while ((HasPendingEffects || HasPendingEvents || HasPendingContinuations) && Result == Ongoing) {
    if (resolvedCycles >= MaxQueueCycles) throw;          // :99-102
    ResolvePendingEffects();                              // :104  —— 抽干效果队列
    ResolvePendingEvents();                               // :105  —— 抽干事件队列
    if (!HasPendingEffects && !HasPendingEvents
        && TryDequeueContinuation(out var c)) c(combat);  // :107-111 —— 每轮只跑一个续延
    resolvedCycles++;
}
```

**【验证】** 上限：`MaxQueueCycles = MaxEffectsPerCycle = MaxEventsPerCycle = 1024`（`C:CombatExecutionLimits.cs:12-14`），触发器深度 `DefaultMaximumTriggerDepth = 64`（`C:CombatEffectChain.cs:10`）。

`ResolvePendingEvents`（`:51-72`）：一次取一个事件 → `GetCombatEventHandlers(类型)` → **按数组序依次调用全部 handler** → 一个事件跑完再取下一个。

### 1.2 关键事实：处理器**只入队**，排空发生在处理器全部跑完之后

这是本规格书里最容易被漏掉的一条。逐个核对 turn-start 的 8 个处理器：

| 处理器 | 它对状态做了什么 | 证据 |
|---|---|---|
| `ResetCardPlayTurnStats` | 直接重置统计（同步写） | `C:Cards\CardPlayTurnStats.cs:296-309` |
| `RefillResource…` | **`EnqueueEffect(RefillResourceEffectRequest)`** | `C:Resources\ResourceTurnLifecycleEventHandlers.cs:24-27` |
| `ActivatePendingStatuses…` | 同步 `SetPendingTurns(-1)` + `RecountActiveStatuses`，但转正通知是 `EnqueueEvent` | `C:Effects\StatusEffects.cs:426, 434-445` |
| TurnStarted 触发器 | 程序**同步**执行（`EffectProgramExecutor.Execute` 内联派发根节点，`C:Effects\Programs\EffectProgramExecution.cs:60-61`），但它产出的效果是 `EnqueueEffect` | 同左 + `C:EffectProgramNodeExecutors` 各 executor |
| `ResolveQueueOnTurnStarted` | 程序同步执行，效果入队 | `C:Cards\QueueResolution.cs:90-95` |
| `DrawCards…` | **`EnqueueEffect(DrawCardsEffectRequest)`** | `C:Cards\CardTurnLifecycleEventHandlers.cs:33-35` |
| `ClearBlock…` | **`EnqueueEffect(ClearDefensivePoolEffectRequest)`** | `C:Effects\DefensivePoolEffects.cs:316-319` |
| `DoT…` | **`EnqueueEffect(DamageOverTimeTickEffectRequest)`** | `C:Effects\StatusEffects.cs:468-471` |

⇒ 一个回合开始的实际时序是：

```
[第 1 轮排空] 效果队列空 → 事件队列里只有 TurnStarted → 8 个处理器按序跑完，
             期间把 Refill / 触发器效果 / 队列卡效果 / Draw / Clear / DoT tick
             按这个顺序塞进**效果队列**（FIFO）
[第 2 轮排空] 效果队列按 FIFO 抽干：补能量 → 触发器效果… → 队列卡效果… → 抽牌 → 清格挡 → DoT 跳
[第 3+ 轮]   程序续延（onComplete）每轮跑一个，可能再产生效果/事件
```

**【验证】** 效果队列是 `Queue<IEffectRequest>` + 平行的 `Queue<CombatEffectChainContext>`（`C:CombatState.cs:5-6, 401-406`），`DequeueNextEffectEntry` 是 `Dequeue`（`:429-440`）⇒ 严格 FIFO。

**这就是为什么「七步顺序」既是规格又"看起来没被执行"**：顺序体现在**入队序**上，不体现在处理器内的直接写。任何"某一步的判定发生在何时"的问题，答案都可能是「处理器时点」或「效果生效时点」，二者相差一整个轮次。

### 1.3 「判定时点」vs「生效时点」

| 步骤 | 判定（采样）时点 | 生效时点 | 证据 |
|---|---|---|---|
| 1 补能量 | 效果生效时 | 效果生效时 | `C:Resources\ResourceEffects.cs:50, 84-96` |
| 2 pending 转正 | **处理器时点**（遍历 `PendingStatuses`） | 处理器时点（`SetPendingTurns` 是直接写） | `C:Effects\StatusEffects.cs:420-445` |
| 3 触发器 | 处理器时点（谁在身、过滤器、排序） | 程序同步跑，效果延后 | `C:Effects\TriggeredProgramDefinition.cs:114-193` |
| 4 卡牌队列 | 处理器时点（快照 `Queue` 前 N 张） | 程序同步跑，效果延后 | `C:Cards\QueueResolution.cs:29-37` |
| 5 抽牌 | **效果生效时**（`zones.Hand.Count` 在 handler `:35` 里读） | 效果生效时 | `C:Effects\CardZoneEffects.cs:31-46` |
| 6 清格挡 | **处理器时点**（`pool.Current <= 0` 在 `:305` 采样） | 效果生效时 | `C:Effects\DefensivePoolEffects.cs:301-320` |
| 7 DoT | **处理器时点**决定"谁跳"（`:460-466` 遍历 `Statuses`、查标签、`Stacks>0`）；**效果生效时**读层数决定"跳多少"（`:495-508`） | 效果生效时 | `C:Effects\StatusEffects.cs:449-510` |

**第 6 行是内核今天唯一真正算错的地方**，见 §5.1。

**【验证】** 第 7 行还有一条参考代码自己的注释为证：`C:Effects\StatusEffects.cs:476-479`「The tick reads the instance's stacks when it RESOLVES, not when it was queued: turn-start triggers run before this automation but their own work is queued too, so an "antidote" trigger that removes stacks must shrink the very tick it precedes.」

---

## 2. 八个必做钩子

每个钩子用同一套小节：签名 → 参考位置 → 有序步骤 → 读写字段 → 异常路径 → 哈希影响 → 内核现状与缺口 → 在镜像内容上的工作量。

### 2.1 `activate_pending_statuses(state, actor)`

**签名**（`K:turn.rs:110-114`）：`fn(&mut self, state: &mut CombatState, actor: &CombatantId) -> Result<(), TurnError>`

**参考位置**：`C:Effects\StatusEffects.cs:409-447`（`ActivatePendingStatusesOnTurnStartedHandler`）。调用点：turn-start 处理器 #2（`C:StandardCombatPackage.cs:126`）。

**有序步骤**（**【验证】**，逐行）：

1. `TryGetCombatant(event.CombatantId)` 失败 ⇒ **静默 return**（`:417-418`）。
2. `var pending = combatant.PendingStatuses.ToList()`；空 ⇒ return（`:420-422`）。`PendingStatuses` = `_statuses.Where(!IsActive)`（`C:CombatantState.cs:29`），`IsActive` = `PendingTurns == 0`（`C:StatusInstance.cs:22`）⇒ **集合里每个实例的 `PendingTurns >= 1`**。
3. **按实例插入序**（`_statuses` 是 `List`，`PendingStatuses` 不排序）逐个：
   - `status.SetPendingTurns(status.PendingTurns - 1)`（`:426`）。`SetPendingTurns` 对负数**抛** `ArgumentOutOfRangeException`（`C:StatusInstance.cs:99-105`）——因为 `PendingTurns >= 1`，减到 0 是下界，不会抛。
   - `if (!status.IsActive) continue;`（`:427-428`）语义：`PendingTurns == 0` 才继续。因为每轮只减 1，**只有 `PendingTurns == 1` 的实例在本次转正**。
   - 记 `StatusApplied` 日志（`:430-432`）。
   - `EnqueueEvent(StatusActivatedCombatEvent{ 实例 id、定义 id、Stacks、DurationTurns、Charges、SourceCombatantId、SourceCardId })`（`:434-443`）。
4. 循环外 `combatant.RecountActiveStatuses()`（`:445`）——重算 `_activeCount` 快路径（`C:CombatantState.cs:58`）。

**读**：`combatant.Statuses` 的 `PendingTurns`、`Id`、`DefinitionId`、`Stacks`、`DurationTurns`、`Charges`、`SourceCombatantId`、`SourceCardId`。
**写**：该实例的 `PendingTurns`（−1）、`_activeCount`；并**入队一个事件**。

**层数/时长/充能是否重置**：**不重置**（**【验证】**：整个 handler 只调 `SetPendingTurns` 与 `RecountActiveStatuses`，没有 `SetStacks`/`SetDurationTurns`/`SetCharges`）。转正 = 同一个实例从"不可见"变成"可见"。

**多个 pending 同时转正的顺序**：实例插入序（`List` 序），不是 id 序、不是定义序。`StatusActivated` 事件按同序入队、同序分发。

**异常路径**：只有第 2 步那个 `SetPendingTurns` 的负数断言（不可达）；没有别的 throw。

**哈希影响**（**【验证】**，`C:CombatStateHasher.cs:108-119`）：

| 必然变化 | 必然不变 |
|---|---|
| 成功转正的实例那行的 ` pend=<n>` **后缀消失**（`:116-117`：`if (s.PendingTurns > 0)` 才写） | `s=` 行的其余列（`stk=` / `dur=` / `chg=` / `pol=`）——一个字节都不变 |
| 什么都没转正、但减了 1 的实例：`pend=` **数值变化**（` pend=2` → ` pend=1`） | `status_num=`（不新建实例） |
| 事件队列若是空的、而这里入了事件 ⇒ `chain_num=` 可能变（`EnqueueEvent` 在无当前链时 `CreateRootEffectChain()`，`C:CombatState.cs:442-452, 545-555`，`chain_num` 是哈希行，`C:CombatStateHasher.cs:38`） | `round=` / `turn=` / `phase=` / `active=` |

⚠️ 补充：状态快照走 `AllStatuses`（`C:CombatStateSnapshotter.cs:89-90`），所以 pending 实例**在快照里、也在哈希里**。

**内核现状与缺口**：

- `K:state.rs:800-819` 的 `StatusInstance` 有 `pub pending_turns: i32`，`K:state.rs:1098` 有 `statuses_mut() -> &mut [StatusInstance]`，`K:state.rs:1113` 有 `remove_status(index)`。⇒ **机件齐备**。
- 缺一个 `Combatant` 级的"active only"视图（参考的 `Statuses` 是过滤后的，内核 `K:state.rs:1084 statuses()` 返回全部实例）。写本钩子时必须自己按 `pending_turns == 0` 过滤。**这不是本钩子的缺口，而是一条已经存在的、与 turn 无关的偏差**：`K:exec.rs:2099-2115` 的 `total_stacks` 只按 `definition_id` 匹配、**从不看 `pending_turns`**，而它拿到的切片来自 `K:exec.rs:467, 487` 的 `statuses()`（全部实例）⇒ **今天内核在"pending 实例挂在战斗员身上"时，修饰管线会把它算进去，参考不会**（参考在 `C:Effects\PassiveModifiers.cs:142` 遍历的是 active-only 的 `Statuses`）。当前镜像造不出 pending 实例（§4.2），所以不可观测；建议单独记一条 issue，别等 2.1 落地才想起来。

**在镜像内容上的工作量**：**空转**。23/23 状态的 `IncomingStatusDelay` 全是 `null`（实测，见 §6.1），所以 `pending_turns` 永远造不出非零值。实现它只是为了"内容一开这个口子就自动正确"。

---

### 2.2 `run_turn_started_triggers(state, actor)`

**签名**（`K:turn.rs:118-122`）。

**参考位置**：`C:Effects\TriggeredProgramDefinition.cs:69-198`（`TriggeredProgramCombatEventHandler<TEvent,TEventContext>`），注册在 `C:StandardCombatPackage.cs:127`，上下文/过滤器在 `C:Effects\TriggeredProgramContextAdapters.cs:46-53` 与 `C:Effects\TurnStartedTriggeredEffects.cs:22-31`。

**有序步骤**（**【验证】**）：

1. **取定义表**：`registry.GetTriggeredEffectDefinitions(typeof(TurnStartedCombatEvent))` → 筛 `TriggeredProgramDefinition<TurnStartedTriggeredEffectContext>` → **按 `(Priority, Id.value)` 排序**（`:88-92`，`OrderBy(Priority).ThenBy(Id.value)`），排序结果按 registry 缓存（`ConditionalWeakTable`，`:75-76`）。
2. **并入临时规则**：`combat.GetTemporaryTriggeredPrograms(typeof(TurnStartedCombatEvent))` 非空时，两股流**合并后重新按同一键排序**（`:95-106`）。
3. 逐个：
   - **重入抑制**（`:117-123`）：`CurrentEffectChain.CanEnterTriggeredEffectDefinition(def)`；策略 `SuppressRecursiveReentry` 时，若本链里已有同 id ⇒ 跳过（`C:CombatEffectChain.cs:49-62`）。
   - **深度闸**（`:128-135`）：`chain.TriggerDepth >= chain.MaximumTriggerDepth`（64）⇒ 抛 `InvalidOperationException`。注意顺序：先记 trace，再 `EnsureCanAppendTriggeredEffectDefinition`——**深度用尽会抛，不是跳过**。
   - **GatingStatus 预筛**（`:139-144`）：`def.GatingStatus` 非空且**没有任何战斗员携带该状态定义** ⇒ 跳过（不建上下文、不问过滤器）。
   - **建上下文**（`:148-154`）：`ContextFactory` 返回 `null` ⇒ 跳过。TurnStarted 的工厂是「`TryGetCombatant(e.CombatantId)` 失败 ⇒ null」（`C:Effects\TriggeredProgramContextAdapters.cs:48-52`）。
   - **过滤器**（`:156-161`）：**全部** `Matches` 为真才跑（`All`，短路）。
   - **跑程序**（`:166-173`）：`CreateTriggeredEffectChain(def.Id)` → `EnterEffectChain` → `EffectProgramExecutor.Execute(program, ctx, buildCtx, combat, registry)`。**程序同步跑，效果入队。**
   - **记账**（`:176-177, 179-192`）：若本次跑出了效果 ⇒ `NoteTriggerActivity(def.Id)`（**不在快照里**，`C:CombatState.cs:409-414` 说得很明确）；若是临时规则实例 ⇒ `RecordActivation()` + 记日志 + `EnqueueEvent(TemporaryRuleActivatedCombatEvent)`。
4. 循环外：有临时规则被激活过 ⇒ `RemoveExpiredTemporaryTriggeredPrograms()`（`:196-197`）。

**次数限制**：注册表里的触发器**没有次数上限**（每次事件都问一遍）；**临时规则**有 `RemainingActivations`（`C:Effects\TemporaryTriggeredProgram.cs`，`RecordActivation` 递减），用完在 `:196-197` 被移除。

**排序键的精确口径**：`Priority` 是 int 升序；次级 `Id.value` 是 **string 默认比较器**（`ThenBy` 不传 `StringComparer`）。**【未验证】** C# 的 `Comparer<string>.Default` 是 culture-sensitive（`string.CompareTo`），不是 `Ordinal`；对纯 ASCII 的 `{statusSlug}_trigger{index}` 其行为是否与字节序逐字相同，**我没有验证过**。内核若要逐位对齐，建议按字节序实现并在测试里钉住，同时把这条差异写进 SEMANTICS。

**内容镜像里 TriggerStarted 触发器长什么样**（实测，**【验证】**）：

- 触发器存在 `STAT.Triggers` 格（`K:content.rs:1322-1323`，cell 索引 7，`F_TERM` 句柄）。
- 全部 25 条触发器条目的键只有两个：`Event`（`TriggerEvent` 枚举名的字符串）+ `Program`（节目信封 `{Id, MaxNodeDepth=64, MaxProgramSteps=1024, Root}`）。**`Scope` 键一条都没有出现** ⇒ 全是默认 `Bearer`（`SB:StatusDataRebuild.cs:25`）。
- `Event` 分布：`TurnEnded`×6、`RoundEnded`×4、`TurnStarted`×3、`StatusApplied`×3、`StatusMerged`×3、`StatusStacksChanged`×2、`StatusRemoved`×2、`DamageDealt`×1、`DamageTaken`×1。
- 3 条 `TurnStarted`：`fatigue`（`node.sequence` = `loseResource` + `modifyStatusStacks`）、`bookworm`（`node.conditional` 套 4 个 `sequence`，共 8 个 `modifyStatusStacks`）、`queue_advances`（`node.conditional` 套 2 个 `setCombatantCounter`）。
- 用到的节点种类全在 `exec.rs` 已交付的 15 种里 ⇒ **执行层够用**。

**触发器是怎么从内容变成引擎定义的**（**【验证】**，`SB:StatusDataRebuild.cs:15-46`）：

- id = `$"{statusSlug}_trigger{index}"`（`:19`）；
- `Enum.Parse<TriggerEvent>(data.Event)`（`:18`）——`TriggerEvent` 是 **Sandbox 层的枚举**（`SB:EffectVocabulary.cs:29-71`），不是 Core 的东西；
- `gatingStatus = 该状态 id`（`:29`），**`StatusExpired` 例外**（`:70-73` 不传 gate）；
- `priority` **不传** ⇒ `TriggeredProgramDefinition` 构造默认 `0`（`C:Effects\TriggeredProgramDefinition.cs:35`，`TriggeredProgramAdapter.Define` 默认 `priority = 0`，`C:Effects\TriggeredProgramContextAdapters.cs:25`）⇒ **所有状态触发器同优先级，实际顺序完全由 id 字符串决定**；
- `reentryPolicy` 默认 `SuppressRecursiveReentry`（同 `:26`）；
- Bearer 作用域挂的过滤器是 `TurnStartedCombatantHasStatusTriggerFilter(statusId)` = 「**本回合行动者**身上有该状态」（`C:Effects\TurnStartedTriggeredEffects.cs:22-31`，读 `context.TurnCombatant.Statuses`）；`Anywhere` 作用域换成 `AnyCombatantHasStatusTriggerFilter`（`SB:StatusDataRebuild.cs:33-35`）。
- `TurnStarted` ↔ `TurnStartedCombatEvent` 的映射见 `SB:StatusTriggerPrograms.cs:44`；上下文的 `TriggeredEffectActionSource` 是 `SourceCombatantId = event.CombatantId`（`C:Effects\TurnStartedTriggeredEffects.cs:55-62`）⇒ 节目里 `sel.source` 解析成**本回合行动者**。

**哈希影响**：

| 必然变化 | 必然不变 |
|---|---|
| 程序产出的每个效果的真值（如 `modifyStatusStacks` ⇒ `s=` 行层数、`setCombatantCounter` ⇒ `cnt=` 行、`loseResource` ⇒ `res=` 行） | `round=` / `turn=` / `phase=` |
| 每跑一个程序 ⇒ `exec_num=` +1（`C:CombatState.cs:513-518` 的 `AllocateProgramExecutionId`，`EffectProgramExecutor.Execute` 在 `:27` 调用；`exec_num` 是哈希行，`C:CombatStateHasher.cs:39`） | `status_num=` / `card_num=`（除非节目自己建了实例/卡） |
| 首次在无当前链时入队 ⇒ `chain_num=` +1（`:442-452` + `:545-555`；哈希行 `:38`） | 程序什么都没做 ⇒ 除 `exec_num`/`chain_num` 外一个字节都不变 |
| `cnt=` 行（`setCombatantCounter` 走 `ModifyCounter`/`SetCounter`，`C:CombatantState.cs:64-71`） | `TriggerActivity` **不入快照**（`C:CombatState.cs:409-414`）⇒ 不影响哈希 |

**内核现状与缺口**（这是本钩子最贵的地方）：

- **`ir.rs` 没有任何读 `STAT.Triggers` 的入口**。公开 API 只有 `Ir::card_program_root(index)`（`K:ir.rs:489`）、`NodeRef` 的字段读取（`:197-470`）；`Content` 层能拿到 cell 句柄（`K:content.rs:1322-1323`）与裸 term（`K:content.rs:548 term(tid)`），但**没有"状态 → 触发器官网"的解码器**。⇒ **需要冻结方加接口**（建议形状：`Ir::status_trigger_entries(&self, status_index: u32, out: &mut [TriggerEntry]) -> Result<usize>`，`TriggerEntry{ event: TriggerEventName, root: NodeRef, max_steps: u32 }`）。
- **内核没有 `TriggerEvent` 的类型**。参考里它是 Sandbox 层的枚举（`SB:EffectVocabulary.cs:29`），而 `TurnStarted`/`TurnEnded` 只是 25 个名字里的 2 个。v1 至少要能**认出**全部 25 个名字并对不支持的**响亮拒绝**（`IrError::UnknownKind` 风格的失败，不能静默跳过——静默跳过会让"内容写了规则但内核不跑"变成隐性算错）。
- **没有 `ExecContext` 之外的程序执行入口问题**：`K:exec.rs:412 execute(root, &mut ExecContext)` 够用，但要自己填 `source` / `event_target` / `max_steps` / `content`。
- **`exec_num` / `chain_num` 没有发号器**：`K:state.rs:1452-1453` 只有字段（`new()` 里 =1，`K:state.rs:1527-1528`），全仓 `grep` 不到任何 `+=`（实测）。程序一跑，参考的 `exec_num` 就前进，内核不动 ⇒ **哈希必然发散**（§5.5）。

**在镜像内容上的工作量**：**真活**。3 条 TurnStarted 触发器，要真的把 `fatigue` 的 `loseResource`、`bookworm` 的条件分支、`queue_advances` 的计数器跑出来。

---

### 2.3 `resolve_pending_queues(state)`

**签名**（`K:turn.rs:127`）。注意它**没有 `actor`**——它排空的是全局队列。

**参考位置**：`C:CombatEventHandling.cs:76-115`（`CombatQueueProcessor.ResolvePendingQueues`）。

**它到底排空什么**（**【验证】**）：三个队列，都是 `CombatState` 上的 `Queue<T>`：

| 队列 | 类型 | 谁往里塞 | 证据 |
|---|---|---|---|
| `_pendingEffects` | `Queue<IEffectRequest>` | `EnqueueEffect`（效果 handler、节点 executor、各生命周期 handler） | `C:CombatState.cs:5, 382-407` |
| `_pendingEvents` | `Queue<ICombatEvent>` | `EnqueueEvent`（效果 handler 想通知的触发器） | `C:CombatState.cs:8, 442-463` |
| `_pendingContinuations` | `Queue<Action<CombatState>>` | `EnqueueContinuation`（节点 executor 表示"我这个节点做完了"） | `C:CombatState.cs:10, 465-473` |

**解析顺序与上限**：见 §1.1。三条要点：

1. **效果队列优先于事件队列**，每轮都是。
2. **续延每轮只跑一个**（`:107-111` 的 `TryDequeueContinuation` 只 `Dequeue` 一个），且**只在效果队列与事件队列都空时才跑** ⇒ "程序真正结束"永远晚于它派生的效果。
3. 三个上限各 1024，超了**抛**（`:99-102, 53-55`），不是截断。

**与 `next_effect_chain_number` 的关系**（**【验证】**）：

- `EnqueueEffect` / `EnqueueEvent` 在 `CurrentEffectChain == null` 时调 `CreateRootEffectChain()`（`C:CombatState.cs:386, 446`），它 `new CombatEffectChainId(_nextEffectChainNumber)` 然后 `_nextEffectChainNumber++`（`:545-555`）。
- 在链作用域内（`EnterEffectChain`）入队则**不再发号**，沿用外层链（`:500-511` 的 `IDisposable` 会还原 `CurrentEffectChain`）。
- 触发器进入时 `CreateTriggeredEffectChain` → `AppendTriggeredEffectDefinition`（`:492-498`，`C:CombatEffectChain.cs:74-83`）：**同一条链、深度 +1，不重新发号**。
- ⇒ `chain_num` 只在"从没有链的状态开始一次新的入队瀑布"时前进。**它是哈希行**（`C:CombatStateHasher.cs:38`），所以"入队几次"是可观测的，不是实现细节。

**它是空的条件（任务点名要的答案）**：

> 如果宿主**不在钩子之间保留任何待处理队列**（即每个钩子在返回前就把自己的效果直接写进状态），那么 `resolve_pending_queues` 的调用永远是 no-op——三个队列恒空，`while` 条件第一次就不成立。

**这是"空实现就够"的准确条件，也是它的边界**：

1. 一旦宿主为了让"触发器能看到宿主效果造成的伤害"而把效果入队（参考的所有触发器都依赖这一点），队列就不再恒空，`resolve_pending_queues` 变成**必须**真的排空。
2. **更硬的一条**：第 5 步在参考里是 `ResolveOldest`（解析牌区 `QueuePile`），而内核把这个位置交给了 `resolve_pending_queues`（`K:turn.rs:591`）。如果宿主的 `resolve_pending_queues` 只排空"效果队列"（而它恒空），**`QueuePile` 里的牌就永远不会解析，也永远不会离队**——这正是 `S:QueueTortureTests.cs:170-192` 钉住的行为（`Assert.Empty(fight.Queue)`）的失败形态。见 §5.2。

**我验证「队列今天会是空的」的方法（任务要求的"给出验证方法"）**：

- 读 `K:turn.rs` 全文的 6 处 `host.resolve_pending_queues(...)` 调用点（`:591, 620, 670, 681, 691`），确认**它们之间没有任何东西会往宿主的队列里塞东西**，除非宿主自己塞。
- 读 `C:CombatEventHandling.cs:97-114`，确认排空的进入条件是 `HasPendingEffects || HasPendingEvents || HasPendingContinuations` 三者皆假即不进循环 ⇒ "空"的判据是**这三个都空**，而不是"牌区 Queue 空"。
- 反向验证（内容侧）：镜像里有 `node.resolveQueuedCards` 这个节点种类吗？——`C:StandardCombatPackage.cs:217` 注册了 `ResolveQueuedCardsNodeExecutor`，说明**语言层面存在"提前解析队列"的效果**；但 core 镜像的 62 张卡里没有人用（`K:exec.rs` 的 15 种已交付节点里也没有它）。⇒ 今天"队列"只能靠 turn-start 那一次窗口解析。

**哈希影响**：

| 必然变化 | 必然不变 |
|---|---|
| 被执行的效果的真值（`res=` / `dp=` / `s=` / `cnt=` / `cz=` 行） | 队列本身**不入哈希**（快照只取 `HasPending*` 之外的稳定状态，`C:CombatStateSnapshotter.cs:42-71` 里没有队列字段） |
| 每发一个新链 ⇒ `chain_num=` +1；每跑一个程序 ⇒ `exec_num=` +1 | `round=` / `turn=`（本钩子不碰回合计数） |
| 效果导致战斗结束 ⇒ `result=` 变化（`C:CombatState.cs:340-367`） | |

**内核现状与缺口**：

- 内核**没有三队列**：`K:state.rs` 里没有 `pending_effects`/`pending_events`/`pending_continuations` 字段（实测 grep 无）。`K:exec.rs:739-741` 的模块头如实写了「参考是"全部孩子同时入队…"，**没有事件队列时两者观察等价**；一旦有触发器就必须换成真正的队列」。
- ⇒ 本钩子的正确实现**依赖先决定"内核要不要引入三队列"**。这不是钩子的事，是架构裁决。见 §5.2。

---

### 2.4 `damage_over_time(state, actor)`

**签名**（`K:turn.rs:130-134`）。

**参考位置**：两段。**入队段** `C:Effects\StatusEffects.cs:449-474`（`DamageOverTimeOnTurnStartedHandler`，注册于 `C:StandardCombatPackage.cs:139`）；**结算段** `:480-510`（`DamageOverTimeTickEffectRequest` + `DamageOverTimeTickEffectHandler`）。

**有序步骤**（**【验证】**）：

**A. 处理器时点（turn-start 第 8 步，效果全部入队之后、但还没生效）**

1. `TryGetCombatant(event.CombatantId)` 失败 ⇒ return（`:457-458`）。
2. `foreach (var status in combatant.Statuses.ToArray())`（`:460`）——**注意是 `Statuses`**，即 **active-only**，pending 的 DoT **不跳**。`.ToArray()` 是循环内修改的保险。
3. `if (!status.Tags.Contains(StandardCombatIds.DamageOverTimeTag)) continue;`（`:462-463`）——判据是**实例上的标签**。实例标签在**创建时**从定义拷贝：`initialTags: definition.Tags`（`C:Effects\StatusEffects.cs:196`）⇒ 实际等价于"定义带 `damage_over_time` 标签"。
4. `if (status.Stacks <= 0) continue;`（`:465-466`）。
5. `EnqueueEffect(DamageOverTimeTickEffectRequest{ TargetCombatantId: event.CombatantId, StatusInstanceId: status.Id })`（`:468-471`）——**每一条实例一个请求，按实例序入队**。注意请求里**没有金额**。

**B. 效果生效时点**

6. 按 id 重新找实例；找不到 / `Stacks <= 0` / 标签没了 ⇒ **什么都不做**（`:495-499`）。
7. `EnqueueEffect(DealDamageEffectRequest{ TargetCombatantId, Amount: status.Stacks, SourceCombatantId: status.SourceCombatantId, SourceCardId: status.SourceCardId, Kind: DamageKind.DamageOverTime, SourceStatusId: status.DefinitionId })`（`:501-509`）。
8. 走 `DealDamageEffectHandler` 的**全部**流程（`C:Effects\DamageEffects.cs:43-204`）。

**读**：`statuses()`（定义 id、层数、标签、`SourceCombatantId`、`SourceCardId`）、目标 HP、目标的全部防御池。
**写**：目标 `Health.Current`、防御池 `Current`；并**入队** `DamageDealtCombatEvent` + `DamageReceivedCombatEvent`（`C:Effects\DamageEffects.cs:185-203`），可能入队 `SetCombatantLifecycleStateEffectRequest{Downed}`（经 `MarkCombatantDownedOnZeroHealthHandler`，`C:Effects\CombatantLifecycleEffects.cs:156-180`）。

**失败/异常路径**（**【验证】**）：

| 情形 | 行为 |
|---|---|
| `Amount < 0` | **抛** `ArgumentOutOfRangeException`（`C:Effects\DamageEffects.cs:50-51`）。DoT 的 `Amount = Stacks`，而 `Stacks` 构造时非负（`C:StatusInstance.cs:52-53`）⇒ 正常不可达 |
| 目标不在场 | `GetCombatant` 抛（`:54`） |
| 伤害为 0 | 不抛，仍走完（扣 0、发事件） |
| 杀掉目标 | 入队 Downed 效果 → 再入队 `CombatantLifecycleChangedCombatEvent` → `UpdateStandardCombatResultOnLifecycleChangedHandler` 判胜负 |

**哈希影响**：

| 必然变化（有伤害时） | 必然不变 |
|---|---|
| 目标 `c=... hp=<n>/<max>`（`C:CombatStateHasher.cs:80`；内核 `K:snapshot.rs:209-212`） | `s=` 行**完全不变**——DoT **不扣层数**（`C:Effects\StatusEffects.cs:449-510` 里没有任何 `SetStacks`）。`standard.poison` 也不衰减（`decay=false`，`K:status_catalog.rs:443-449`） |
| 有格挡被吸收 ⇒ `dp=standard.block <n>/<max>`（`C:CombatStateHasher.cs:88-91`；内核 `K:snapshot.rs:221-225`） | `res=`（资源不变） |
| 目标 HP 归零 ⇒ `c=... lc=` 变化 + `result=` 可能变化 | `round=` / `turn=` / `phase=` / `active=` |
| `chain_num` / `exec_num`：走的是效果队列，参考里 tick 是入队产物；内核若不建模则不变，建模则变（§5.5） | `status_num=` |
| **RNG**：`step=` **不变**（见下） | `cz=`（牌区） |

**RNG**：**【验证】** DoT 全路径没有随机：`C:Effects\StatusEffects.cs`（449-510）与 `C:Effects\DamageEffects.cs` 全文都没有 `RandomSeed`/`RandomStep`/`AdvanceRandomStep`/`CreateShuffledIndexes`（grep 实测 0 命中，只有一句注释里的 "random" 字样在 `:605`，那是另一个 handler）。⇒ **DoT 不推进 `random_step`**。

**DoT 吃不吃格挡**：**吃**。`IgnoresBlock` 默认 `false`（`C:Effects\DamageEffects.cs:21-24`），DoT tick 构造请求时**没有**传 `IgnoresBlock`（`C:Effects\StatusEffects.cs:501-509`）⇒ 走 `:80-101` 的防御池吸收。

**DoT 走不走修饰器管线、管线名是什么**：**走**，但**每条 spec 自己带门**。

- 管线是 `DealDamage` 的那两条：**Source 阶段读出手者**（`PassiveModifierPipeline.DamageDealt`）、**Target 阶段读承受者**（`DamageReceived`），阶段序 `Source → Target → Global`（`C:Effects\DamageEffects.cs:7-13, 305-317`）。
- 门在 `DeclarativePassiveModifierEngine.Apply`：`if (damageKind is { } kind && spec.RestrictDamageKind is { } restrict && restrict != kind) continue;`（`C:Effects\PassiveModifiers.cs:154-156`），而 `RestrictDamageKind` 的**默认值是 `Direct`**（`:85-87`）。
- ⇒ **标准包的三行（力量/虚弱/易伤）对 DoT 整表不参与**，因为它们的 `RestrictDamageKind` 是 `Direct`。这与 `K:status_catalog.rs:985` 那条测试（`damage_rows_are_direct_only_so_dot_and_reflected_are_untouched`）测的是同一件事，但**测试测的是表，不是管线**。
- ⇒ **不是第四条管线**，是"同一条 `DealDamage` 管线 + `Kind = DamageOverTime` + 默认全被门挡住"。
- ⇒ **内容可以开这个口子**：镜像里 5 条 spec 全是 `RestrictDamageKind = "Direct"`（实测），所以今天 DoT 一定不被放大；但只要内容写一条 `RestrictDamageKind = null` 的 spec，它就会作用于 DoT。

**取整/定点规则**（**【验证】**）：全程整数，没有浮点。

- `ScalePercent` = `current * magnitude / 100`，**向零截断**（`C:Effects\PassiveModifiers.cs:210`；Rust 侧 `K:modifiers.rs:277` 的 `wrapping_mul(...) / 100`，注释 `:268-269` 明确"Rust 的 `/` 与 C# 一样向零截断"）。
- **每一步之后**夹 `Math.Max(0, ·)`（`C:Effects\DamageEffects.cs:312`；内核 `K:modifiers.rs:297-299` 是"整条管线末尾夹一次"，模块头 `:295-296` 说明了这是对 `:312` 的逐字对应）。
- DoT 自己的金额是 `Stacks`，**没有乘法、没有取整**。

**内核现状与缺口**：

- `K:exec.rs:438-443` 的 `resolve_damage(ctx, target, base, ignores_block)` **没有 `kind` 参数**，且 `K:exec.rs:1787-1797` 的 `damage_kind_passes` 是 `const fn`，`Some(BindDamageKind::Direct) => true` 是无条件放行。⇒ **直接复用会把力量/虚弱/易伤算进 DoT**（`K:exec.rs:1789-1790` 的注释自己写着「v1 的效果解释器只造成 Direct 伤害（没有 DoT / 反伤 / 元素路径），所以这条门今天恒放行」）。这是本钩子唯一的硬阻塞，见 §5.4。
- `K:status_catalog.rs:286-287` 已有 `TAG_DAMAGE_OVER_TIME` 与 `tag_bit("damage_over_time")`（`:313-326`）；镜像侧的标签是**定义**上的字符串列表（`STAT.Tags`，`K:content.rs:1320-1321`），内核目前**没有**"从镜像读标签位"的函数（`status_bind::decode` 只解极性 + 修饰器，`K:status_bind.rs:253-261`）。⇒ 需要补一个 `status_bind::has_tag(content, id, bit)` 之类的东西。
- `K:state.rs` 的 `StatusInstance` **没有 tags 字段**（`:800-819`，注释明说按哈希需要的字段建的）。因为参考是"定义标签的拷贝"，走定义查表是等价且更省的 —— 但要**写进规格**，否则有人会想去加字段。

**在镜像内容上的具体向量**（实测数据，可直接当验收用例）：`poison`（`Tags=["damage_over_time"]`、`UsesStacks=true`、`UsesDuration=false`）与 `paperwork`（同标签）。假设英雄带 `poison 3`：
- 回合开始：DoT 造成 **3** 点（`Amount = Stacks = 3`），先扣格挡、余下扣血；
- 回合结束：`poison` 自己的 `TurnEnded` 触发器（`node.modifyStatusStacks{Delta:-1, StatusDefinitionId:"poison", TargetSelector: sel.source}`）把层数减到 **2**。⇒ **poison 的衰减靠触发器，不靠 duration 轴**（§4.4）。

---

### 2.5 `hand_turn_end_lifecycle(state, actor)`

**签名**（`K:turn.rs:137-141`）。

**参考位置**：`C:Cards\CardLifecyclePrograms.cs:21-46`（`CardLifecycleTurnEndInHandHandler`），注册于 `C:StandardCombatPackage.cs:135`。

**有序步骤**（**【验证】**）：

1. `TryGetCombatant(event.CombatantId)` 失败 ⇒ return（`:28-29`）。
2. `foreach (var card in combat.GetCardZones(combatEvent.CombatantId).GetCardsInZone(CardZone.Hand))`（`:31`）——**手牌序**，且是活视图（不 `.ToArray()`；注释 `:17-20` 说"a program that moves the card is fine（we snapshot the hand first）"，但代码里**没有**显式快照；`GetCardsInZone` 返回什么由 `CardZones` 决定，**【未验证】** 它是否拷贝）。
3. `registry.TryGetCard(card.DefinitionId)` 失败 ⇒ continue（`:33-34`）。
4. `definition.LifecyclePrograms.TryGetValue(CardLifecycleTrigger.TurnEndInHand, out program)` 失败 ⇒ continue（`:35-36`）。`CardLifecycleTrigger` 目前**只有 `TurnEndInHand` 一个成员**（`:8-11`）。
5. `EffectProgramExecutor.Execute(program, new CardLifecycleContext(definition, card.Id, owner.Id), buildCtx, combat, registry)`（`:38-43`）——**同步跑，效果入队**。`buildCtx` 的 `Source = owner`、`EventTargetId = owner`（`C:Effects\CardLifecycleTriggeredEffects.cs:42-55`）。

**读**：`CardZone.Hand` 的牌（定义 id、实例 id）、卡定义的 `LifecyclePrograms`。
**写**：无直接写；只入队。

**异常路径**：没有显式 throw。节目里的节点可能抛（`ValidateNodeExecutors` 在 `Execute` 前置检查，`C:Effects\Programs\EffectProgramExecution.cs:22-23, 184-196`）——**未注册 executor 就抛**，整个 turn-end 中断。

**哈希影响**：

| 必然变化 | 必然不变 |
|---|---|
| 节目产出的效果的真值 | `cz=` 牌区行**只有节目自己动了牌才变**；普通卡（无 lifecycle program）**一个字节都不变** |
| `exec_num=`（每跑一个节目 +1） | `chain_num=` —— ⚠️ **2026-10-19 更正**：本表原来把 `chain_num` 也列在"必然变化"里，那是错的。处理器跑在 `TurnEndedCombatEvent` 的分发里，那一刻 `CurrentEffectChain` 是事件自己那条链（`C:CombatEventHandling.cs:60` 的 `using (EnterEffectChain(entry.EffectChain))`）⇒ `Execute` 里 `EffectChain ??= CurrentEffectChain ?? CreateRootEffectChain()`（`C:Programs/EffectProgramExecution.cs:31`）**不会**建新根链、**不发号**。整批 turn-end 处理器只花事件那一个号 |
| | `s=` / `res=` / `dp=` / `hp=` |
| | `phase=` 已经在 turn-end 之前变成 `WaitingToStartTurn`（`K:turn.rs:739` / 参考 `C:CombatState.cs:332-338`） |

**内核现状（2026-10-19 实现，`K:host.rs::try_hand_turn_end_lifecycle`）**：

- 镜像内容：**62/62 卡的 `LifecyclePrograms` 是 `{}`**（实测；字段全集 = `Costs/Id/LifecyclePrograms/PackageId/PlayedCardDestinationZone/Program/RetainInHandOnTurnEnd/Tags/TurnEndHandDestinationZone`）⇒ 真实内容上**一条节目都不跑**：不改一格状态、不发执行号、不建链。那条"空"路径是解码器的两次格读取（哨兵 / 0 字段的 `_obj`），**不是特判**。
- **机制是真的**：解码 `CARD.LifecyclePrograms[TurnEndInHand]`（键名两种拼法都收：`"TurnEndInHand"` 与枚举序数 `"0"` —— 哪一种会真的出现在镜像里 **【未验证】**，因为 62/62 卡是 `{}`、没有任何实例能观察键名），走 `exec::begin` 派发，`sel.source` / `sel.eventTarget` 都绑正在结束回合的那个人（`C:CardLifecycleTriggeredEffects.cs:49-55`）。
- **链号 +0**：内核把 `TurnEnded` 的那**一个**号发在 `try_run_turn_ended_triggers` 里（在本钩子之后），所以这里用 `CombatState::adopt_root_chain`（建链、不推进 `next_effect_chain_number`）表达"复用一条已经发过号的链"。链的 **id** 拿到的是"上一个已发的号"（参考里是事件那条链的号），但 id 不进哈希、也没有按 id 的查表 ⇒ 可观察量（`chain_num`）一致。
- 三条**偏离**（都写在函数的文档里）：① 定义查不到 ⇒ 响亮失败（参考是 `continue`）；② 节目上下文的"卡槽"没有对应物（`ExecContext` 只有一个 `forEachCardInZone` 的迭代卡槽，**故意不绑**）⇒ 读卡槽的表达式得到 `ExprError::NoTarget`（响亮）；③ 先解码全部手牌再跑（参考边跑边解，只在内容坏了时可观察）。
- 缺失的**观测对象**：真实镜像没有一张带节目的卡，所以"节目跑起来了"这件事由 `K:host.rs` 测试里那份**手搓 RDCF 镜像**当观察对象（`burn` / `burn_dual` / `burn_block` / `burn_retained` / `weird` / `plain`）。
- ⚠️ **顺带发现的另一个缺口（不在本钩子里）**：`K:host.rs::card_stays_in_hand_at_turn_end` 恒返回 `false`，理由写的是"62/62 卡 `RetainInHandOnTurnEnd = false`（实测）"。手搓镜像里那张 `true` 的卡证明：**内容一旦真的用这个字段，它会被静默忽略**（卡照样在回合末被弃）。


**时点**：它在 turn-end 处理器序里是**第 1 位**（`:135`），在弃手牌（`:136`）之前。参考的注释（`:17-20`）解释了原因：「before the end-of-turn discard, which is deferred (enqueued), so the hand is intact here」。

---

### 2.6 `run_turn_ended_triggers(state, actor)`

**签名**（`K:turn.rs:144-148`）。

**参考位置**：与 2.2 是**同一个 handler 类**（`TriggeredProgramCombatEventHandler<TurnEndedCombatEvent, TurnEndedTriggeredEffectContext>`），只是注册的事件/上下文不同（`C:StandardCombatPackage.cs:137`）。

**有序步骤**：**与 2.2 逐条相同**，只换三样东西：

| 项 | TurnStarted | TurnEnded | 证据 |
|---|---|---|---|
| 事件类型 | `TurnStartedCombatEvent` | `TurnEndedCombatEvent` | `C:StandardCombatPackage.cs:127, 137` |
| 上下文 | `TurnStartedTriggeredEffectContext` | `TurnEndedTriggeredEffectContext`；两者的 `ContextFactory` 都是「`TryGetCombatant(e.CombatantId)` 失败 ⇒ null」 | `C:Effects\TriggeredProgramContextAdapters.cs:46-53, 55-62` |
| Bearer 过滤器 | `TurnStartedCombatantHasStatusTriggerFilter` | `TurnEndedCombatantHasStatusTriggerFilter`（读 `TurnCombatant.Statuses`） | `C:Effects\TurnEndedTriggeredEffects.cs:22-31` |
| `sel.source` | `event.CombatantId` | 同 | `C:Effects\TurnEndedTriggeredEffects.cs:55-62` |

**排序·次数限制**：同 2.2（`(priority=0, id 字符串)`；注册表触发器无次数上限；临时规则有）。

**异常路径**：深度超限**抛**；过滤器/上下文失败**静默跳过**。

**哈希影响**：同 2.2。**额外一条**：`decrease_timed_statuses`（处理器 #4，`:138`）排在它之后，而两者都只入队 ⇒ 效果序是「触发器效果 … → 时长递减」。

**镜像内容上的具体向量**（实测，6 条）：

| 状态 | 节目根 | 干什么 |
|---|---|---|
| `panic` | `node.modifyStatusStacks` | `Delta = -1`（`sel.source` 指向自己） |
| `poison` | `node.modifyStatusStacks` | `Delta = -1`（同上）⇒ **poison 的衰减** |
| `paper_seals_wax` | `node.setCombatantCounter` | 写一个计数器 |
| `one_remaining_seal` | `node.sequence` | 含 `applyStatus` |
| `your_number_is_fading` | `node.conditional` | 含 2 个 `node.dealDamage` ⇒ **会在回合结束时造成伤害** |
| `counterclaim` | `node.setCombatantCounter` | 写一个计数器 |

⇒ **反证"空实现够用"不成立**：`poison` 一挂上，回合结束不减层，`poison` 就变成永久且每回合按层数跳——**这是可观测的算错**，不是"少了个润色"。

---

### 2.7 `decrease_timed_statuses(state, actor)`

**签名**（`K:turn.rs:151-155`）。

**参考位置**：**入队段** `C:Effects\StatusEffects.cs:379-406`（`DecreaseTimedStatusDurationsOnTurnEndedHandler`，注册于 `C:StandardCombatPackage.cs:138`）；**结算段** `:333-377`（`DecreaseStatusDurationEffectRequest` + `DecreaseStatusDurationEffectHandler`）。

**有序步骤**（**【验证】**）：

**A. 处理器时点**

1. `TryGetCombatant` 失败 ⇒ return（`:387-388`）。
2. `foreach (var status in combatant!.Statuses.ToArray())`（`:390`）——**active-only**，pending 实例**不衰减**（这是 `AllStatuses` 与 `Statuses` 的一处关键分野）。
3. `if (!definition.UsesDuration) continue;`（`:394`）——**判据是定义上的 `UsesDuration` 标记**。
4. `if (status.DurationTurns <= 0) continue;`（`:397-398`）。
5. `EnqueueEffect(DecreaseStatusDurationEffectRequest{ TargetCombatantId, StatusInstanceId })`（`:400-403`）——`Amount` 用默认值 **1**（`:330`）。

**B. 效果生效时点**

6. `Amount <= 0` ⇒ **抛**（`:340-341`，不可达）。
7. 按 id 找实例，找不到 ⇒ return（`:343-348`）。
8. `DurationTurns <= 0` ⇒ return（`:350-351`）。
9. `newDuration = Math.Max(0, old - Amount)`（`:353-354`）→ `SetDurationTurns(newDuration)`（`:356`）→ 记日志（`:358-360`）。
10. `if (newDuration > 0) return;`（`:362-363`）。
11. **归零 ⇒ 删实例**：`target.RemoveStatus(status)`（`:365`）+ 记 `StatusExpired`（`:367-369`）+ `EnqueueEvent(StatusExpiredCombatEvent)`（`:371-375`）。

**减到 0 是删实例还是留 0 层**：**删实例**（第 11 步）。**【验证】** 这一点在本项目里格外重要：`K:exec.rs:1066-1079` 已经就"留一条 0 层实例不是等价物"写过一段教训（它会出现在 `s=` 行、`statuses()`、以及 24 条容量的余量里），**同一条理由适用于这里**。

**与 `pending` 的交互**：**无交互**——第 2 步用 `Statuses` 排除了 pending 实例，所以 pending 的时长**在等待期间不衰减**。转正之后才开始衰减。

**判定谓词（任务问的 `decay_predicate`）**：

- 参考的判据 = `definition.UsesDuration`（`:394`）。
- 内核已有：`K:status_catalog.rs:661-664` `decays_at_owner_turn_end(status_id) -> bool`，数据字段 `StatusMeta::decays_at_owner_turn_end`（`:357-359`），并**冻结了一条不变量**：标准包里它**恒等于** `axes.duration`（定义处注释 `:357-358` + 测试逐行钉住 16 行）。
- 标准包里为真的 **7 个**（`K:status_catalog.rs:647-654` 的注释）：`weak` / `vulnerable` / `frail` / `stun` / `one_attack_per_turn` / `first_attack_each_turn_free` / `skill_cost_reduction`。**`standard.poison` 不在内**（它只有层数轴）。
- 内容侧：镜像 23 个状态 `UsesDuration` **全 false**（实测）⇒ 今天没有任何实例会衰减。格子在 `K:content.rs:1342-1343`（`uses_duration` / `uses_charges`，`F_BOOL`）。

**哈希影响**：

| 必然变化 | 必然不变 |
|---|---|
| 被减的实例：`s=… dur=<n>` 数值变化（`C:CombatStateHasher.cs:113`） | `stk=` / `chg=` / `pol=` |
| 归零：**整行消失**（`RemoveStatus`），且**剩下的实例保持相对顺序**（`K:state.rs:1113` 的 `remove_status` 契约：左移一格再 `pop()`，`K:exec.rs:1068-1071` 说明了理由） | `status_num=`（不新建） |
| 归零：`tag?` / `cnt=` 不变；`StatusExpiredCombatEvent` 入队 ⇒ 有 `StatusExpired` 触发器的内容会连锁（镜像有 2 条 `StatusRemoved` / 0 条 `StatusExpired` 触发器） | `round=` / `turn=` / `phase=`（`phase` 已在 turn-end 开头改掉） |
| `chain_num=`（事件入队时若链为空） | `cz=`（牌区无关） |

**内核现状**：谓词、`remove_status`、字段都在。**空转**于当前镜像，**真活**于标准包。

---

### 2.8 `hand_is_retained(state, actor) -> bool`

**签名**（`K:turn.rs:159`，**`&self`，不可变**，返回 `bool`）。

**参考位置**：`C:Cards\CardTurnLifecycleEventHandlers.cs:39-59`（`DiscardHandOnTurnEndedHandler`），注册于 `C:StandardCombatPackage.cs:136`。

**判定来源**（**【验证】**）：**身上有任意一个状态实例带 `retain_hand` 标签**：

```
if (combat.TryGetCombatant(e.CombatantId, out var combatant) &&
    combatant!.Statuses.Any(status => status.Tags.Contains(StandardCombatIds.RetainHandTag)))
{  // 记一条 TurnAutomationSuppressed 日志
   return; }                                  // 根本不给 MoveHandCards 入队
combat.EnqueueEffect(new MoveHandCardsOnTurnEndEffectRequest(e.CombatantId));
```

- 标签名 `"retain_hand"`（`C:StandardCombatIds.cs:55`），**不是法令、不是卡标记**。
- 是 `Statuses`（active-only ⇒ pending 的 `retain_hand` **不生效**）。
- 是 `Any`（**任意一个**就够），不按层数、不看时长。

**语义**：「整手牌都不弃」，且是**短路**——参考在**没有**入队任何效果的情况下就返回了。⇒ 实现里必须**先判它**，判真就一张都不动。

**哈希影响**：判真 ⇒ `cz=` 的 `hand` 堆**一个字节都不变**（没有移动、没有排序、没有 `HandDiscardedCombatEvent`）；判假 ⇒ 走弃手牌（§4.6）。

**内核现状**：`K:turn.rs:809-811` 已在 `discard_hand` 里先判它并 `return Ok(0)`。数据侧：`K:status_catalog.rs:290-293` 有 `TAG_RETAIN_HAND`，`K:status_catalog.rs:1278-1279` 的测试钉住**标准包 16 个状态一个都不带这个标签**；镜像 23 个状态的 `Tags` 里也没有 `retain_hand`（实测）⇒ 恒 `false`。
⇒ **默认 `false` 就够**，且默认值恰好正确。

---

## 3. 六个带默认值的策略钩子

这六个的默认值都**必须**等于"参考实现在没有对应法令/标记/修饰器时的行为"。逐条给判定来源与今天的正确性。

### 3.1 `block_is_retained` → 默认 `false`

**参考位置**：`C:Effects\DefensivePoolEffects.cs:283-322`（`ClearBlockOnTurnStartedHandler`）。
**判定**：`combatant.Statuses.Any(s => s.Tags.Contains(RetainBlockTag))`（`:297`），标签名 `"retain_block"`（`C:StandardCombatIds.cs:56`）。
**作用范围**：**该战斗员名下所有** `ClearsOnOwnerTurnStart` 的池（`:301-320`）。
**池定义**：`standard.block` 是 `AbsorbPriority: 0, ClearsOnOwnerTurnStart: true`（`C:StandardCombatPackage.cs:54-55`；`C:DefensivePoolDefinition.cs:11-14`）。
**今天的正确性**：镜像无 `retain_block`；标准包 16 个状态也无（`K:status_catalog.rs:1278-1279`）⇒ **默认 `false` 正确**。
**⚠️ 与内核的一处偏差**：见 §5.1（采样时点）。

### 3.2 `turn_start_draw_count(state, actor, base) -> i32` → 默认 `base`

**参考位置**：`C:Cards\CardTurnLifecycleEventHandlers.cs:15-36`。
**实现**：`cardsToDraw = DeclarativePassiveModifierEngine.Apply(combat, registry, combatant, PassiveModifierPipeline.TurnStartDraw, damageKind: null, _cardsToDraw)`（`:27-29`），然后 `if (cardsToDraw <= 0) return;`（`:30-31`），再入队 `DrawCardsEffectRequest{Count: cardsToDraw}`（`:33-35`）。
**细节（**【验证】**）**：

- `damageKind: null` ⇒ `C:Effects\PassiveModifiers.cs:155` 的种类门被跳过（`damageKind is { } kind` 为假）⇒ `RestrictDamageKind` 对这条管线**无意义**。
- `amount <= 0` 时 `Apply` **原值返回**且不跑任何 spec（`:136-138`）——所以 `base = 0` 时修饰器不参与。
- 折叠末尾 `Math.Max(0, current)`（`:216`）⇒ 结果不下溢。
- handler 自己在 `_cardsToDraw == 0` 时就 return（`:20-21`），所以"配置抽 0 张"根本不入队。
- **`max_hand_size` 的裁剪在效果生效时**（`C:Effects\CardZoneEffects.cs:31-46`），不在宿主里。`K:turn.rs:195` 的注释也这么要求了。

**今天的正确性**：**默认 `base` 是错的。** 镜像的 `panic` 带 `PassiveModifiers = [{Pipeline: "TurnStartDraw", Operation: "AddPerStack", Magnitude: -1, Priority: 100, RestrictDamageKind: null}]`（实测）⇒ 带 `panic N` 的战斗员应当少抽 N 张，默认实现会多抽。
**实现阻塞**：`K:modifiers.rs:34-45` 的 `Pipeline` **没有 `TurnStartDraw`**；`K:status_bind.rs:121-129` 有，但那边是"内容数据管线"，`K:status_bind::decode` 只把 spec 解码成结构体，**没有折叠器**（`K:modifiers.rs:223` 的 `apply` 只认 `modifiers::Pipeline`）。⇒ 要么给 `modifiers::Pipeline` 加一个变体（改冻结接口），要么在宿主里写一条专用折叠。**建议前者**，理由是：`Pipeline` 是"折叠器的管线"（`K:status_bind.rs:119-120` 的注释明说两者同名不同义），加变体正是它的职责。

### 3.3 `unspent_energy_carries` → 默认 `false`

**参考位置**：`C:Resources\ResourceEffects.cs:84-96`。
**判定**：`CombatDecrees.InForce(registry, holder, CombatRule.UnspentResourceCarries).Any(spec => spec.Resource is null || spec.Resource == 本次资源)`（`:90-92`）。
**效果**：`refillTarget = checked(refillTarget + previousCurrent)`（`:94`），`SetCurrent(refillTarget, allowExceedingMax: carries)`（`:96`）——**允许超上限**。
**法令定义**：`C:CombatDecrees.cs:39-42`（`UnspentResourceCarries`），由**状态**的 `CombatRules` 承载（`C:StatusDefinition.cs:36-39`）。
**今天的正确性**：镜像 49 件遗物的 `CombatRules` **0 条**（实测），23 个状态的 `CombatRules` 也全空（dump 里该键一次都没出现）⇒ 恒 `false`。
**内核侧**：`K:turn.rs:377-381` 已按"补到 / 累加"两分支实现，且 `:360-361` 如实写明"池不存在时参考提前 return，法令不参与，本函数照此办理"。**【验证】** 与 `C:Resources\ResourceEffects.cs:50-81`（创建分支在 `:81` 就 `return`，法令判断在 `:90` 之后）一致。

### 3.4 `card_stays_in_hand_at_turn_end(state, actor, slot) -> bool` → 默认 `false`

**参考位置**：`C:Effects\CardZoneEffects.cs:413-428`（`ResolveTurnEndDestinationZone` 的第 ①② 条）。
**判定顺序**（**【验证】**）：

1. `card.Marks.Contains(StandardCombatIds.RetainedCardMark)` ⇒ `CardZone.Hand`（`:419-420`）。标记名 `"standard.retained_card"`（`C:StandardCombatIds.cs:100`），是**每实例**的标记，由 `markCardInstance` 效果加上。
2. `definition.RetainInHandOnTurnEnd` ⇒ `CardZone::Hand`（`:422-425`）——**每定义**的开关。
3. 否则走 `turn_end_hand_destination`。

**今天的正确性**：62/62 卡 `RetainInHandOnTurnEnd = false`（实测）；`TurnEndHandDestinationZone` 全是 `DiscardPile`（实测）。标记今天没有任何内容去加（`node.markCardInstance` 在 core 镜像的 62 张卡里未出现——**【未验证】**，我只验证了卡定义的字段，没数节点种类）。⇒ 默认 `false` **应当**正确，但这条依赖"没有内容加标记"，**没有 `RetainInHandOnTurnEnd` 那条硬**。

### 3.5 `turn_end_hand_destination(state, actor, slot) -> CardZone` → 默认 `DiscardPile`

**参考位置**：同 `C:Effects\CardZoneEffects.cs:427`（`definition.TurnEndHandDestinationZone`）。
**迁移规则**：`zones.MoveCardToZone(card.Id, destinationZone)`（`:369`）**不带 `Placement`** ⇒ 默认 `ZonePlacement.Bottom`（`:162` 的默认参数）⇒ 每个目的堆内部**保持手牌原序**。内核照抄（`K:turn.rs:864` 传 `ZonePlacement::Bottom`）。
**返回 `Hand` 的含义**：等价于"留下"（`:366-367` 的 `if (destinationZone == CardZone.Hand) continue;`）。内核 `K:turn.rs:839-841` 同样处理。
**今天的正确性**：62/62 全是 `DiscardPile` ⇒ 默认值正确。

### 3.6 `on_round_ended` / `on_round_started` → 默认 `Ok(())`

**参考位置**：`C:CombatTurnProcessor.cs:190-205`（绕回时 `EnqueueEvent(RoundEndedCombatEvent)` → `AdvanceRound()` → `EnqueueEvent(RoundStartedCombatEvent)`）。
**要点**：`RoundEnded` 事件带 `LastActiveCombatantId`（`C:Effects\TriggeredProgramContextAdapters.cs:74-82` 的工厂会读它），`RoundStarted` 无参数（`:64-72` 读的是 `ActiveCombatantId`——注意此刻 `SetActiveCombatant` 还没调用，`C:CombatTurnProcessor.cs:199-207` 的顺序），⇒ **`RoundStarted` 的上下文用的是"上一轮的活跃单位"**。**【验证】** 这是 `:199-201` 入队在 `:207` 设活跃之前造成的，不是笔误，但是个容易踩的坑。
**镜像上有活**：4 条 `RoundEnded` 触发器（`witness_the_seal` / `loophole` / `still_in_force_passive` / `sustained`），全是 `node.setCombatantCounter`。⇒ 这两个钩子今天**不是空的**。内核 `K:turn.rs:173-183` 的默认实现 `Ok(())` 会让这 4 条永远不跑 —— 但它们是可选钩子，默认值语义是"标准包不额外做"，**内容一用就必须覆盖**。建议在文档/测试里把它标成"有内容依赖的必做项"。

---

## 4. 专题

### 4.1 DoT 的数值到底从哪来（任务点名）

**答案：状态实例的 `Stacks`，乘以 1，没有任何其它系数。** 没有"每层伤害"字段、没有硬编码表。

- 唯一的金额表达式是 `Amount: status.Stacks`（`C:Effects\StatusEffects.cs:504`）。
- "哪些状态是 DoT"由**定义上的标签**决定：`DamageOverTimeTag = "damage_over_time"`（`C:StandardCombatIds.cs:45`），标准包在造 `standard.poison` 时 `definition.Tags.Add(DamageOverTimeTag)`（`C:StandardCombatPackage.cs:263-264`）。
- 判据读的是**实例标签**（`status.Tags.Contains(...)`，`:462, :498`），实例标签在创建时从定义拷贝（`:196`）。
- 镜像里带这个标签的是 `paperwork` 与 `poison`（实测）。

⇒ **没有任何"数值从哪来"的歧义**：`poison 3` 就是 3 点。不是 StS 的"层数 = 伤害"恰好相同——这里**引擎层面**就是 `Amount = Stacks`，没有 `Stacks` 作为"剩余次数"的第三种含义。

### 4.2 `pending` 的语义

**是「延迟 N 次拥有者回合开始」**，且**N 由承受者决定，不由被施加的状态决定**。

- 值来源：`IncomingDelayFor(combat, registry, target, definition)`（`C:Effects\StatusEffects.cs:124, 252-265`）= 遍历**承受者当前的 active 状态**，取所有 `IncomingStatusDelay` 中「极性适用（`spec.Applies(polarity)`）」的**最大** `Turns`（`:255-264`）。
- `IncomingStatusDelaySpec(Turns, Polarity?)`（`C:StatusDefinition.cs:197-200`）；`Polarity = null` ⇒ 延迟一切，`Debuff` ⇒ 只延迟负面。
- `pendingTurns > 0` 的应用**永远建新实例**（`:126` 的 merge 分支要求 `pendingTurns == 0`）——注释 `:122-123` 说明了理由：「merging it into a status already in force would make it effective at once」。
- **递减时机**：拥有者**自己的**回合开始，处理器 #2（`C:StandardCombatPackage.cs:126`），每次 −1（`C:Effects\StatusEffects.cs:426`）。
- **转正**：`PendingTurns == 0`（`C:StatusInstance.cs:22`）。**不重置层数/时长/充能**（§2.1）。
- **等待期间的行为**（**【验证】**，全部由 `CombatantState.Statuses = 只列 active` 一条实现，`C:CombatantState.cs:27-28`）：
  - 不参与修饰管线（`DeclarativePassiveModifierEngine` 遍历 `combatant.Statuses`，`C:Effects\PassiveModifiers.cs:142`）；
  - 不跳 DoT（`:460`）；
  - 不触发状态触发器（Bearer 过滤器读 `Statuses`）；
  - **不衰减时长**（`C:Effects\StatusEffects.cs:390`）；
  - 但**可见、可被清除**：`RemoveStatusEffectRequest` 走 `target.AllStatuses`（`:572-574`，注释 `:570-571` 明说"cleansing reaches pending instances as well"）；
  - 且**进哈希**（`pend=<n>`，`C:CombatStateHasher.cs:116-117`）。
- **多个同时转正的顺序**：实例插入序。

**镜像现状**：23/23 `IncomingStatusDelay = null` ⇒ `pending_turns` 恒 0。**这条路上今天没有可观测行为。**

### 4.3 「队列」有三种，别混

这是本次最容易出错的概念，任务里「pending queue」这个词至少对应三样东西：

| # | 名字 | 内容 | 谁往里塞 | 谁排空 | 内核里对应什么 |
|---|---|---|---|---|---|
| A | **效果队列** `_pendingEffects` | `IEffectRequest`（"请做这件事"） | 任何 `EnqueueEffect` | `ResolvePendingEffects`（`C:CombatEventHandling.cs:104`） | **没有**（宿主自己决定） |
| B | **事件队列** `_pendingEvents` | `ICombatEvent`（"这件事发生了"） | 任何 `EnqueueEvent` | `ResolvePendingEvents`（`:105`） | **没有** |
| C | **牌区 QueuePile** `CardZone.QueuePile` | 已付费、已锁定目标、效果延后的**卡** | `node.queueCard` / 卡的 `QueueOnPlay` | `QueueResolution.ResolveOldest`（`C:Cards\QueueResolution.cs:18-38`），由 turn-start 处理器 #4（`:131`，`C:StandardCombatPackage.cs:131`）在 `int.MaxValue` 上全清 | `K:state.rs` 有 `CardZone::QueuePile`；**没有解析器** |
| D | **续延队列** `_pendingContinuations` | `Action<CombatState>`（"我这个节点做完了"） | 节点 executor | 每轮跑一个（`:107-111`） | **没有** |

**A/B/D 与 `next_effect_chain_number` 的关系**：入队时若 `CurrentEffectChain == null` ⇒ 发一个新链号（`C:CombatState.cs:545-555`）；链在作用域内沿用时**不发号**。链号是哈希行（`C:CombatStateHasher.cs:38`）。

**C 与 A 的关系**：`ResolveOldest` 把牌的节目**同步执行**，节目产出的效果进 A（`C:Cards\QueueResolution.cs:90-95`）；牌离队是通过**入队一个 `MoveCardToZoneEffectRequest`** 实现的（`Finish`，`:116-128`）。⇒ 一张队列卡"解析完"的标志是它的落点效果生效。

**C 的排序与上限**（**【验证】**）：

- "最老的先"：`Queue.Where(!IsResolvingQueuedCard).Take(count)`（`:29-33`）⇒ 按 `Queue` 堆内序（入队序），**跳过正在解析的那张**（`:27-28` 的注释）。
- 整个窗口的集合**在解析第一张之前快照**（`:29-33` 的 `.ToList()`）⇒ "在窗口内被塞进队列的卡要等下一个窗口"（模块头 `:10-13`）。
- 数量上限：turn-start 用 `int.MaxValue`（`:137`）⇒ 全清。
- **逐张串行**：下一张要等前一张的节目 `onTerminal` 且状态非 `Faulted`（`:100-110`）。
- 目标锁定：卡在排队时锁定的目标若已离场，节目里绑定目标的那部分**失效，不重定向**（`:66-70`）。

### 4.4 触发器：来源、排序、次数限制（汇总表）

| 问题 | 答案 | 证据 |
|---|---|---|
| 从哪来 | 注册表的 `TriggeredEffectDefinitions`（不可变）+ 战斗上的临时规则 | `C:Effects\TriggeredProgramDefinition.cs:88-106` |
| 内容怎么进去 | 状态的 `STAT.Triggers[]` → `SB:StatusDataRebuild.RebuildTrigger` → `RegisterTriggeredEffectDefinition` | `SB:StatusDataRebuild.cs:15-46` |
| 事件名从哪来 | `TriggerEvent` 枚举（**Sandbox 层**，25 个成员） | `SB:EffectVocabulary.cs:29-71` |
| 排序 | `(Priority 升序, Id.value 字符串)`；状态触发器 Priority 恒 0 ⇒ **纯 id 字符串序** | `:91-92`，`SB:StatusDataRebuild.cs:19`（id = `{slug}_trigger{index}`），`C:Effects\TriggeredProgramContextAdapters.cs:25`（priority 默认 0） |
| 次数限制 | 注册表触发器**无**；临时规则 `RemainingActivations` | `:179-192`, `:196-197` |
| 重入抑制 | 同一效果链里同 id 不重复触发（默认策略） | `:117-123`，`C:CombatEffectChain.cs:49-62` |
| 深度上限 | 64，**超了抛** | `C:CombatEffectChain.cs:10, 64-72` |
| 预筛 | `GatingStatus`：没人在身就跳过 | `:139-144` |
| 上下文失败 | 静默跳过 | `:148-154` |
| 过滤器 | 全部为真才跑 | `:156-161` |
| 遗物/卡能不能带战斗触发器 | 镜像里**都不能**：49 件遗物只有 `CombatRules` + `RunPrograms`（0 条 CombatRules），62 张卡没有触发器字段 | 实测 ✅ |
| 镜像里有多少 | 25 条，分布在 15 个状态上；`TurnStarted`×3 / `TurnEnded`×6 | 实测 ✅ |

### 4.5 有时限状态减一（汇总）

见 §2.7。三条必须记住的：**判据是 `UsesDuration`（不是"有 duration 轴"这个推断）、pending 不衰减、归零删实例**。镜像上 0 个 `UsesDuration=true` ⇒ 今天空转；标准包上 7 个。

### 4.6 手牌收尾三者的优先级

**优先级从高到低**（**【验证】**，全部在 `C:Cards\` 里）：

1. **`hand_is_retained`**（`C:Cards\CardTurnLifecycleEventHandlers.cs:48-55`）：`retain_hand` 状态标签 ⇒ **整手不动**，连 `MoveHandCardsOnTurnEndEffectRequest` 都不入队。判定时点在**处理器时点**（turn-end 第 2 位）。
2. **`card_stays_in_hand_at_turn_end`**（`C:Effects\CardZoneEffects.cs:419-425`）：① 实例标记 `standard.retained_card` ② 定义 `RetainInHandOnTurnEnd`。**逐张**。
3. **`turn_end_hand_destination`**（`:427`）：定义 `TurnEndHandDestinationZone`，默认 `DiscardPile`。**逐张**，且只有 2 没命中才问。
4. 落点一律 `Bottom`（`:162, :369`）⇒ 目的堆内部保手牌原序。

**判定来源是"状态 tag / 卡实例标记 / 卡定义"三种，都**不是**法令。**（法令 `MaxHandSize` 影响的是**抽牌入口**，`C:Effects\CardZoneEffects.cs:31-46`，与收尾无关。）

### 4.7 能量 / 格挡 / 抽牌数

| 项 | 判定来源 | 参考位置 | 内核对应 | 镜像里有吗 |
|---|---|---|---|---|
| `unspent_energy_carries` | 状态上的 `CombatRules` 含 `CombatRule.UnspentResourceCarries` | `C:Resources\ResourceEffects.cs:90-96`；`C:CombatDecrees.cs:39-42` | `K:turn.rs:377` | **否**（0 条） |
| `block_is_retained` | 状态实例带 `retain_block` 标签 | `C:Effects\DefensivePoolEffects.cs:297` | `K:turn.rs:520` | **否** |
| `turn_start_draw_count` | `TurnStartDraw` 管线的 spec 折叠（从**抽牌者**读状态） | `C:Cards\CardTurnLifecycleEventHandlers.cs:25-31` | `K:turn.rs:599` | **是**：`panic` 的 `AddPerStack -1` |
| 抽牌张数上限 | `CombatDecrees.Ceiling(..., CombatRule.MaxHandSize)`，在**抽牌入口**裁剪 | `C:Effects\CardZoneEffects.cs:31-46` | `K:turn.rs:407-423` + `TurnConfig::max_hand_size` | **否**（无 `MaxHandSize` 法令） |
| 补能量目标 | `pool.Max ?? DefaultMax` | `C:Resources\ResourceEffects.cs:85` | `K:turn.rs:376` | 镜像的 encounter 声明 `standard.energy 9/9`（`S:QueueTortureTests.cs:44` 的同类写法） |

---

## 5. 内核与参考的已知偏差（需冻结方裁决）

这一节是我这次读出来的、**会造成哈希可见分歧**的东西。前 4 条我主张必须改，后 2 条是实现阻塞。

### 5.1 第 7 步清格挡的采样时点 —— **我认定内核今天算错**

**参考的行为**（**【验证】**）：`ClearBlockOnTurnStartedHandler` 在**处理器时点**采样 `pool.Current`：

```
:305  if (!combatant.DefensivePools.TryGetValue(poolDef.Id, out var pool) || pool.Current <= 0)
:306      continue;                    // ← 池此刻是 0，就根本不入队清空请求
:308-314  if (retains) { log; continue; }
:316-319  combat.EnqueueEffect(new ClearDefensivePoolEffectRequest(...));
```

而所有别的步骤（补能量、触发器、队列卡、抽牌）的**效果**都要等到之后才生效。⇒ 参考的实际语义是：

> **"回合开始时池里有格挡吗？"决定清不清；清的动作本身排在本回合其它效果之后。**

**内核的行为**：`K:turn.rs:504-529` 的 `clear_turn_start_pool` 在 `start_current_turn` 的**第 7 步**才采样 `pool.current`（`:517`），而第 5 步已经调过 `host.resolve_pending_queues`（`:591`）——如果宿主在那里解析了队列卡（`guard` 那种 `gainBlock 11`），**内核采到的是 11，于是把刚加上的格挡清掉**。

**分歧的具体例子**（两者都会出现，取决于英雄回合结束时格挡是否为 0）：

| 英雄回合结束时的格挡 | 队列卡 `gainBlock 11` | 参考结果 | 内核今天的结果 |
|---|---|---|---|
| 0 | +11 | **11**（清空被跳过） | **0**（采到 11 ⇒ 清） |
| 10 | +11 | **0**（10>0 ⇒ 入队清空；11 先加、清空后到） | **0**（采到 21 ⇒ 清） |

⇒ 第一行是**真分歧**，且恰好就是 `S:QueueTortureTests.cs:194-214` 那个用例的场景（该用例**区分不出来**，因为两种解释都给 11 —— 这就是为什么注释写反了却一直没被发现）。

**修法**（供冻结方选择）：
- (a) 在 `start_current_turn` 入口把 `pool.current` 采样下来（一个 `i32`），`clear_turn_start_pool` 用这个采样值判"清不清"，用实时值判"清多少"；
- (b) 把清格挡改成"宿主钩子"，由宿主在正确时点决定入队——但这会把一行语义推给宿主，不推荐。
**建议 (a)**，并在 `K:turn.rs:24-25` 与 `S:QueueTortureTests` 的注释上一并改正描述。

### 5.2 第 5 步的语义冲突 + QueuePile 今天无人解析

`K:turn.rs:591` 调 `host.resolve_pending_queues(state)`，并且 `:588-590` 的注释说这一步就是 `ResolveQueueOnTurnStartedHandler`（卡牌队列）。但：
- trait 的文档（`:124-127`）说这个方法是"任何入队之后的排空"（效果/事件/续延）；
- §4.3 说明这是**两件不同的事**（D 组 vs C 组）。

**后果**：如果宿主按 trait 文档实现它（只排空效果队列，而效果队列恒空），则**没有任何钩子会把 `CardZone::QueuePile` 里的牌解析掉或移出去**。这不是"少了个润色"：`QueuePile` 里的牌会永远留在那里，`cz=` 行永久不同，且 `counter` 那种"每张队列牌 +3 伤害"的卡会一直算错。

**需要的裁决**（三选一，都要写进冻结契约）：
- (a) 新增第 9 个钩子 `resolve_card_queue(state, actor)`，排在 2 与 6 之间；
- (b) 约定 `run_turn_started_triggers` **的末尾**也要做一次 `ResolveOldest(int.MaxValue)`（即一个钩子覆盖参考的两个处理器 #3+#4）；
- (c) 约定 `resolve_pending_queues` 在**回合开始的调用点**额外承担 `ResolveOldest`（最糟的选项：同一个函数在不同调用点语义不同）。

**我推荐 (a)**：它与注册序一一对应，可测，且不改变已有 6 个调用点的语义。

### 5.3 turn-end 的"弃手牌"时点

**参考**：`DiscardHandOnTurnEndedHandler`（`:136`）只**入队** `MoveHandCardsOnTurnEndEffectRequest`；真正搬牌发生在效果生效时，即**在 turn-end 的三个处理器（含触发器程序）全部跑完之后**。⇒ 回合结束触发器改动的手牌**会被同一轮的弃牌带走**（或者说：触发器可能把牌移走/加进来，弃牌看到的是最新的手牌）。

**内核**：`K:turn.rs:652-660` 是 `hand_turn_end_lifecycle` → **`discard_hand` 同步执行** → `run_turn_ended_triggers`。⇒ 弃牌发生在触发器**之前**。

**今天的可观测性**：镜像 6 条 `TurnEnded` 触发器没有一条动牌（`modifyStatusStacks` / `setCombatantCounter` / `applyStatus` / `dealDamage`）⇒ **当前内容下不可观测**。标为"已知偏差，内容一变就可能暴露"，建议在文档里写明，不建议现在改结构（改了就要引入三队列）。

### 5.4 `DamageKind` 缺参数（DoT 的硬阻塞）

`K:exec.rs:438-443` 的 `resolve_damage` 没有 `kind` 参数；`K:exec.rs:1787-1797` 的 `damage_kind_passes` 对 `Some(Direct)` 无条件放行。而 `K:status_bind::DamageKind` 只有 `Direct` 一个变体（`K:status_bind.rs:154-182`，注释说镜像里 `RestrictDamageKind` 只出现 `Direct`/null）。

⇒ 三个选择：
- (a) 给 `resolve_damage` 加 `kind: DamageKind` 参数（改冻结签名）；
- (b) 加一个并行的 `resolve_damage_of_kind(...)`（不动老签名）；
- (c) 在宿主里另写一条 DoT 专用折叠（**不推荐**：会架空 `K:modifiers.rs` 的两张已经交付并测试过的表，正是 `K:exec.rs:430-432` 警告过的事）。

**建议 (b)**：`resolve_damage` 转调 `resolve_damage_of_kind(..., DamageKind::Direct)`，语义完全不变，老调用点一行不改。

### 5.5 `chain_num` / `exec_num` 没有发号器（哈希必然发散）

- 参考：每个 `EffectProgramExecutor.Execute` ⇒ `AllocateProgramExecutionId()`（`C:CombatState.cs:513-518`，由 `C:Effects\Programs\EffectProgramExecution.cs:27` 调用）；每次"无当前链时的入队"⇒ `_nextEffectChainNumber++`（`:545-555`）。
- 内核：`K:state.rs:1452-1453` 两个字段存在、初值 1（`:1527-1528`）、**进哈希**（`K:snapshot.rs:156` 的 `chain_num=`；`exec_num` 同区），但**全仓没有任何 `+=`**（实测 grep）。

⇒ 宿主一旦真的跑节目（2.2 / 2.4 / 2.6 / 2.5 都要跑），参考的 `chain_num`/`exec_num` 就前进，内核不动 ⇒ **指纹必然不同**。

需要补的 API（建议）：`CombatState::allocate_program_execution_id() -> i64`、`CombatState::create_root_effect_chain() -> i64`（或宿主持有的 `chain` 值），并明确"链作用域内不发号"的规则。**注意**：`C:CombatState.cs:386` 与 `:446` 的 `??` 是这条规则的全部 —— 只要宿主把"当前链"作为参数传下去，就等价。

### 5.6 `TurnStartDraw` 在两个 `Pipeline` 枚举之间缺失

见 §0.2 ① 与 §3.2。一句话：`K:modifiers.rs::Pipeline` 缺 `TurnStartDraw`，`K:status_bind::Pipeline` 缺 `Block`/`Cost`，而参考是一个 6 成员的枚举（`C:Effects\PassiveModifiers.cs:16-29`）。**这不是 bug，是两次叶子交付各取所需的结果**，但 `turn_start_draw_count` 的实现者会撞上它。

---

## 6. 我验证了什么 / 没验证什么

### 6.1 已验证（63 条，每条都可复核）

**A. 回合顺序（8 条）**

1. TurnStarted 处理器共 8 个，注册行 = `:121,124,126,127,131,133,134,139`（`C:StandardCombatPackage.cs`）。
2. TurnEnded 处理器共 4 个，注册行 = `:135,136,137,138`。
3. 处理器按注册序执行，无排序（`C:CombatDefinitionRegistryBuilder.cs:339-353, 463-468`；`C:CombatDefinitionRegistry.cs:223-229`）。
4. `:140-151` 那批里只有 `ResetCardPlayTurnStatsOnTurnStartedHandler` 是 TurnStarted（`C:Cards\CardPlayTurnStats.cs:296`）。
5. 排空循环形状：效果 → 事件 → 每轮一个续延（`C:CombatEventHandling.cs:97-114`）。
6. 三个上限均为 1024（`C:CombatExecutionLimits.cs:12-14`）；触发器深度 64（`C:CombatEffectChain.cs:10`）。
7. 效果队列严格 FIFO（`C:CombatState.cs:401-407, 429-440`）。
8. 所有 turn-start 生命周期 handler 都是**入队**，只有 `ResetCardPlayTurnStats` 与 `ActivatePendingStatuses` 是同步写（`C:Resources\ResourceTurnLifecycleEventHandlers.cs:24-27`；`C:Cards\CardTurnLifecycleEventHandlers.cs:33-35`；`C:Effects\DefensivePoolEffects.cs:316-319`；`C:Effects\StatusEffects.cs:468-471`）。

**B. pending（6 条）**

9. `IsActive == (PendingTurns == 0)`（`C:StatusInstance.cs:22`）。
10. 转正每次 −1，只有原本为 1 的转正（`C:Effects\StatusEffects.cs:426-428`）。
11. 转正不重置 stk/dur/chg（同 handler 全文无 `SetStacks`/`SetDurationTurns`/`SetCharges`）。
12. 转正后 `RecountActiveStatuses()`（`:445`；`C:CombatantState.cs:58`）。
13. 转正入队 `StatusActivatedCombatEvent`，按实例序（`:424-443`）。
14. `pending_turns` 的来源是承受者的 `IncomingStatusDelay`，取最大且极性适用者（`:252-265`）。

**C. DoT（9 条）**

15. 判据 = 实例标签含 `damage_over_time`（`C:Effects\StatusEffects.cs:462`）。
16. 实例标签在创建时从定义拷贝（`:196`）。
17. 只有 active 状态会入队 tick（`:460` 用 `Statuses`）。
18. `Stacks <= 0` 不跳（`:465-466`）。
19. 金额 = `Stacks`（`:504`）。
20. Kind = `DamageOverTime`（`:507`）。
21. 吃格挡（`IgnoresBlock` 默认 false，`:21-24`；tick 不传，`:501-509`）。
22. 读层数在**效果生效时**，不在入队时（模块注释 `:476-479` + `:495-508`）。
23. DoT 全路径不碰 RNG（两文件 grep 0 命中）。

**D. 伤害修饰门（4 条）**

24. `RestrictDamageKind` 默认 `Direct`（`C:Effects\PassiveModifiers.cs:85-87`）。
25. 门在 `:154-156`，`damageKind == null` 时跳过。
26. 阶段序 `Source → Target → Global`（`C:Effects\DamageEffects.cs:7-13, 305-317`）。
27. `ScalePercent` 是整数除法向零截断（`C:Effects\PassiveModifiers.cs:210`）。

**E. 触发器（10 条）**

28. 排序 `(Priority, Id.value)`（`C:Effects\TriggeredProgramDefinition.cs:91-92`）。
29. 临时规则并入同一次排序（`:95-106`）。
30. 重入抑制默认开启（`:37` 的默认参数；`C:Effects\TriggeredProgramContextAdapters.cs:26`）。
31. 深度超限**抛**（`C:CombatEffectChain.cs:64-72`）。
32. `GatingStatus` 预筛（`C:Effects\TriggeredProgramDefinition.cs:139-144`）。
33. 过滤器是 `All`（`:156-161`）。
34. 状态触发器 Priority 恒 0、id = `{slug}_trigger{index}`、默认 Bearer 作用域（`SB:StatusDataRebuild.cs:19, 25, 39-46`；`C:Effects\TriggeredProgramContextAdapters.cs:25`）。
35. `TriggerEvent` 是 Sandbox 层枚举、25 个成员（`SB:EffectVocabulary.cs:29-71`）。
36. `TurnStarted` ↔ `TurnStartedCombatEvent`、`TurnEnded` ↔ `TurnEndedCombatEvent` 的映射（`SB:StatusTriggerPrograms.cs:44-46`）。
37. `sel.source` 在 TurnStarted/TurnEnded 上下文里 = 本回合行动者（`C:Effects\TurnStartedTriggeredEffects.cs:55-62`；`C:Effects\TurnEndedTriggeredEffects.cs:55-62`）。

**F. 时长衰减（5 条）**

38. 判据 = 定义 `UsesDuration`（`C:Effects\StatusEffects.cs:394`）。
39. 只遍历 active（`:390`）。
40. 请求 Amount 默认 1（`:330`）。
41. 归零删除实例（`:365`）。
42. 归零入队 `StatusExpiredCombatEvent`（`:371-375`）。

**G. 手牌与格挡（7 条）**

43. `retain_hand` 整手短路（`C:Cards\CardTurnLifecycleEventHandlers.cs:48-55`）。
44. `standard.retained_card` 标记 > 定义 `RetainInHandOnTurnEnd` > `TurnEndHandDestinationZone`（`C:Effects\CardZoneEffects.cs:419-427`）。
45. 落点默认 `Bottom`（`:162`；`:369` 不传）。
46. `retain_block` 抑制**所有** `ClearsOnOwnerTurnStart` 的池（`C:Effects\DefensivePoolEffects.cs:297-320`）。
47. `standard.block` = `AbsorbPriority 0, ClearsOnOwnerTurnStart true`（`C:StandardCombatPackage.cs:54-55`）。
48. 清格挡的**入队条件**在处理器时点采样 `pool.Current`（`C:Effects\DefensivePoolEffects.cs:305`）—— **§5.1 的依据**。
49. 抽牌张数经 `TurnStartDraw` 折叠、`damageKind: null`、末尾夹 `max(0,·)`（`C:Cards\CardTurnLifecycleEventHandlers.cs:25-31`；`C:Effects\PassiveModifiers.cs:136-138, 216`）。

**H. 哈希（6 条）**

50. 状态行 `s= <id> <def> stk= dur= chg= pol=[ pend=]`，`pend=` 只在 `>0` 时写（`C:CombatStateHasher.cs:108-119`；`K:snapshot.rs:229-231`）。
51. 快照走 `AllStatuses`（`C:CombatStateSnapshotter.cs:89-90`）。
52. `res=` / `dp=` 各自一行（`C:CombatStateHasher.cs:83-91`）。
53. `chain_num=` / `exec_num=` 是哈希行（`:38-39`）。
54. `TriggerActivity` 不入快照（`C:CombatState.cs:409-414`）。
55. 队列本身不入快照（`C:CombatStateSnapshotter.cs:42-71`）。

**I. 内核侧（8 条）**

56. `TurnHost` 8 必做 + 6 可选，签名行号 `K:turn.rs:110-231`；`NullHost` 在 `:241-266`。
57. `start_current_turn` 的 8 个阶段与 6 处 `stopped()` 短路（`K:turn.rs:544-622`）。
58. `discard_hand` 的 4 档判定与容量预检（`K:turn.rs:802-869`）。
59. `StatusInstance` 有 `pending_turns`、无 tags（`K:state.rs:800-819`）；`statuses_mut` / `remove_status` 在 `:1098, 1113`；`statuses()` 返回**全部**实例、`total_stacks` 不过滤 pending（`K:exec.rs:2099-2115`）⇒ 与参考的 active-only 视图不等价。
60. `modifiers::Pipeline` 4 条、`status_bind::Pipeline` 3 条（`K:modifiers.rs:34-45`；`K:status_bind.rs:121-129`）。
61. `resolve_damage` 无 kind 参数（`K:exec.rs:438-443`），`damage_kind_passes` 对 Direct 无条件放行（`:1787-1797`）。
62. `next_effect_chain_number` / `next_program_execution_id` 存在且进哈希，但无发号器（`K:state.rs:1452-1453, 1527-1528`；`K:snapshot.rs:156`）。
63. `ir.rs` 只有 `card_program_root`，没有状态触发器解码入口（`K:ir.rs:475-489` 的 `impl Ir`）。

**J. 镜像内容实测（并入上表统计，均为 `reader.py` 直接读出）**
`TurnStarted` 3 条 / `TurnEnded` 6 条 / `RoundEnded` 4 条触发器；触发器条目只有 `Event` + `Program` 两个键，`Scope` 0 次出现；23/23 状态 `IncomingStatusDelay = null`、`UsesDuration = false`；2 个状态带 `damage_over_time`（`paperwork` / `poison`）；1 条 `TurnStartDraw` spec（`panic`，`AddPerStack -1`）；5 条 spec 全为 `RestrictDamageKind = "Direct"`；62/62 卡 `LifecyclePrograms = {}`、`RetainInHandOnTurnEnd = false`、`TurnEndHandDestinationZone = DiscardPile`；49 件遗物 0 条 `CombatRules`。

### 6.2 未验证（11 条，按重要性排序）

1. **`Hand` 的活跃视图语义**：`C:Cards\CardLifecyclePrograms.cs:17-20` 的注释说"we snapshot the hand first"，但 `:31` 的 `foreach` 直接遍历活视图、**代码里没有显式快照**。`GetCardsInZone` 返回的是拷贝还是视图，我**没读** `C:Cards\CardZones.cs` 的实现。⇒ "`TurnEndInHand` 节目把这张牌移出牌区后，循环会不会崩/会不会跳过下一张"**未知**。（本项目没有 `List` 并发修改异常的问题吗？C# 的 `List` 在 `foreach` 中修改会抛 `InvalidOperationException`。如果 `GetCardsInZone` 是视图，那"移牌的节目"就会**抛**——这与注释说的"a program that moves the card is fine"矛盾。**这是一条真实的疑点，需要有人读 `CardZones.GetCardsInZone`**。）
   > **2026-10-19 补注**：这条**仍然未验证**（还是没读 `CardZones.cs`）。内核那一侧的选择是**先快照手牌槽位**再逐个跑（`K:host.rs::try_hand_turn_end_lifecycle`），理由是参考的注释明确说"移牌的节目是合法的"，而活视图会让 C# 的 `foreach` 抛。如果将来有人读了 `CardZones.GetCardsInZone` 发现它其实是活视图（且移牌真的会抛），那参考的注释就是错的，本内核的快照反而是**更宽**的行为 —— 那时要在 §2.5 记一笔。

2. **`Comparer<string>.Default` 是否等价于字节序**：`ThenBy(d => d.Id.value)` 用的是 culture-sensitive 比较（`C:Effects\TriggeredProgramDefinition.cs:92`）。对 `{slug}_trigger{n}` 这种纯 ASCII，多数情况一致，但 culture 比较会忽略/重排某些标点与大小写。**我没有验证**当前 25 条触发器在这种比较下的真实次序。
3. **`_pendingContinuations` 与"程序真正结束"的等价性**：我确认了"每轮只跑一个续延"（`C:CombatEventHandling.cs:107-111`），但**没有**验证"没有续延可跑 ⇒ 所有节目都结束了"这条不变量在所有节点种类下成立（`forEachTarget` 的多层续延尤其可疑）。
4. **`ir.rs` 能否从 `Content` 解出 `STAT.Triggers` 的完整结构**：我验证了 cell 索引（`K:content.rs:1322-1323`）与 `Content::term` 的存在（`:548`），但**没有**尝试用现有 API 真的走通一遍；`Triggers` 元素的确切 term 形状（`_obj{Event, Program}` vs 别的拼法）我只从 JSON dump 反推，**没有在二进制层核对**（这正是 FACT.md 里"二进制层的拼法可能与 JSON dump 不同"的那个坑）。
5. **`node.markCardInstance` 在 core 镜像里出现了几次**：我据此判断"今天没有内容给卡加 `standard.retained_card` 标记"（§3.4），但只数了卡定义的字段，**没数节点种类**。
6. **`_cardsDrawnPerTurn` 的实际取值**：`C:StandardCombatPackage.cs:133` 传的是构造参数，我**没有**读它在哪里被设成 5。
7. **`C:Effects\StatusEffects.cs` 中 `MaxInterceptionDepth = 3`（`:48`）与 `DamageEffects.cs` 的 `MaxRedirectionDepth = 4`（`:207`）在 DoT 路径上是否可能触发**：我没有构造场景。
8. **`activation` 计数与 `TurnStarted` 临时规则的交互**：`TemporaryTriggeredProgram.RecordActivation` 的具体递减口径我没读那个文件。
9. **镜像 `sustained` 等 4 条 `RoundEnded` 触发器的 gate**：`RoundEnded` 分支在 `SB:StatusDataRebuild.cs:121-124` **没有传 `gatingStatus`、没有传 filters**（与其它事件不同）。这意味着"没人在身也会跑"？还是上下文工厂会挡？我**没验证**（这会影响 §3.6 的"内容一用就必须实现"的说法）。
10. **`CombatDecrees.InForce` 的完整语义**（多状态多条 spec 如何合并）：只读了 `:90-92` 的调用点，没读 `C:CombatDecrees.cs:70-125`。
11. **镜像 `one_remaining_seal` 的 `DamageTaken` 触发器在 DoT 伤害下是否触发**：`C:Effects\StatusEffects.cs:520-521` 只对 `Reflected` 早退，所以 DoT 会触发它；但 `DamageTaken` → `DamageReceivedCombatEvent` 的映射我没读到（`SB:StatusDataRebuild.cs:47-50` 确认存在映射），具体过滤器是 `DamageReceivedReceiverHasStatusTriggerFilter` —— 逻辑上会触发，但**没有实测**。

---

## 7. 落地顺序与验收向量建议

**顺序**（依赖关系决定）：

1. **先裁决三件事**（冻结方的活，不是叶子的活）：§5.2 第 5 步语义、§5.4 `DamageKind` 参数、§5.5 发号器。三件不定，后面写出来的钩子必然要返工。
2. **补接口**：`Ir::status_trigger_entries`（§2.2）、`status_bind` 的标签位读取（§2.4）、`resolve_damage_of_kind`（§5.4）、`allocate_program_execution_id` / `create_root_effect_chain`（§5.5）。**先建桩 + 写一行调用它的代码**，写不出调用代码就是接口开错了（本项目纪律 #7）。
3. **实现顺序按"内容里真有活"排**：`run_turn_ended_triggers`（6 条）→ `run_turn_started_triggers`（3 条）→ `damage_over_time`（2 个状态）→ `turn_start_draw_count`（1 条 spec）→ 其余空实现但**带响亮失败**。
4. `activate_pending_statuses` / `decrease_timed_statuses` 可以先空，但**必须在"有 pending / 有 UsesDuration"时响亮失败**，否则内容一开就是隐性算错。

**验收向量**（都用镜像内容，可直接写成对照测试）：

| # | 场景 | 期望 | 覆盖的钩子 |
|---|---|---|---|
| V1 | 英雄带 `poison 3`，回合开始（格挡 0） | HP −3；`s=` 行 `stk=3` 不变 | `damage_over_time` |
| V2 | 英雄带 `poison 3` + 格挡 5，回合开始 | 格挡 −3 → 2；HP 不变 | `damage_over_time` + 格挡吸收 |
| V3 | 接 V1，回合结束 | `poison` 层数 3 → 2（触发器减的，不是 duration） | `run_turn_ended_triggers` |
| V4 | 英雄带 `poison 1`，回合结束 | 层数归 0 ⇒ **实例被删**（`modifyStatusStacks` 的 0 层删实例规则） | `run_turn_ended_triggers` |
| V5 | 英雄带 `panic 2`，回合开始 | 抽牌 5 → 3 | `turn_start_draw_count` |
| V6 | 英雄带 `fatigue 1`，回合开始（能量 3/3） | 先补到 3，再 `loseResource` 1 → 2；**不是** 3 | 补能量 + `run_turn_started_triggers` 的顺序 |
| V7 | 英雄回合结束时格挡 = 0，队列卡 `gainBlock 11` 在下一回合开始解析 | 回合开始后格挡 = **11** | §5.1 的判别向量 |
| V8 | 英雄回合结束时格挡 = 10，同上 | 回合开始后格挡 = **0** | §5.1 的反例（**这一个能把两种实现分开**） |
| V9 | 任何回合开始 | 无 pending / 无 UsesDuration 的状态 ⇒ 那 6 个"空转"钩子**一个哈希行都不许变** | 全部空实现 |
| V10 | 任意回合的开始/结束 | `chain_num=` / `exec_num=` 与参考逐位一致（需要 §5.5 的发号器） | 全部 |

## 8. 冻结方的更正（实装之后回来改的，按"错的就写错"处理）

执行方在实现过程中顶回来三处**规格书自身的错**。逐条记，因为它们都是"照着错的规格写会得到错的实现"。

### 8.1 V2 向量是错的（原文说"格挡 −3 → 2；HP 不变"）

**错因**：七步顺序里清格挡是**第 7 步**（`StandardCombatPackage.cs:134`）、DoT 是**第 8 步**（`:139`），
而清格挡的效果是"把当前值抹成 0"。所以"回合开始时的 5 点格挡"**活不到 DoT 那一跳**：

* 正确结果：**格挡归 0，HP −3**（毒直接打血）。
* 原文的"格挡 −3 → 2、HP 不变"描述的是"格挡在 DoT 之前还在"的直觉，而那与七步顺序相反。

⇒ V2 必须改写成"格挡 0 / HP −3"，并且**另外**补一条正例说明"格挡确实参与 DoT 吸收"
（做法是让格挡在**同一回合内**由队列卡/触发器加上来，那时清格挡已经过去了 —— 见 §5.1 的 V7/V8 那一族）。

> 这条教训值得单说：**"格挡能挡 DoT"在参考里是真的，但它只在"格挡是这一回合新加的"时成立。**
> 把"格挡能吸收伤害"的一般直觉套到回合开始的 DoT 上，就会写出一条自洽但永远对不上的验收向量。

### 8.2 §2.2 说"执行层够用"是错的：`queue_advances` 会响亮失败

`queue_advances` 那条状态的条件用 `cardsPlayedLastTurn`，而 `expr.rs` **没有实现**这个 kind
（它需要 `CardPlayTurnStats`，内核没有这张表）。⇒ 该状态一旦在身，钩子会
`Exec(Expr(UnsupportedKind))` —— 响亮失败，不是静默算错，这是对的行为；
但"执行层够用"这句话是错的：**它够用于 62 张卡的卡程序，不够用于全部状态触发器。**

### 8.3 `bookworm` 的形状描述错

原文说 4 个 `sequence` / 8 个 `modifyStatusStacks`，实测是 **2 个 `sequence` / 4 个 `modifyStatusStacks`**。
量法：`tools\contentc\reader.py` dump `STAT.Triggers` 后数 term。


**V8 是我建议的最关键一条**：它是唯一能把"清格挡采样时点"两种实现分开的向量，而现存的 `S:QueueTortureTests.cs:194-214` 恰好分不开（这也是那条注释写反了却一直绿着的原因）。
