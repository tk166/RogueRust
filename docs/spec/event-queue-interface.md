# 事件队列接口冻结（三队列 + 触发器分发）

> **状态**：冻结提案，**待冻结方签字**。本文不含实现代码（§4 的 Rust 片段是**形状草图**，
> 不是已实现的东西，也不是逐字可粘贴的代码）。
>
> **本文不动 `kernel/`**。它是一个接口契约：先把"要加什么、加在哪、能不能进哈希、坏了怎么发现"
> 钉死，再让实现者去填。
>
> ⚠️ **行号会漂**：`C:` 前缀的行号取自 `ref/RogueDeck-Core`（只读镜像，稳定）；
> `K:` 前缀的行号取自本轮的工作区快照，而 `kernel/rd-core/src/{exec,play,status_bind}.rs`
> **正在被并发修改**（本轮 `git status` 就能看到）。引用 `K:` 时**以符号名为准**
> （函数名 / 常量名 / 测试名），行号只当"上次看到的位置"。
>
> **读者须知**：`docs/spec/battle-loop-hooks.md` §1 已经写过一遍"三队列 + 排空循环"的**形状**，
> 本文不重复它的推导，只做三件它没做的事：①把队列当**接口**冻下来（含内存预算与 Rust 形状）；
> ②把**触发器分发**的排序/计数/重入规则冻下来；③给出**两档方案**与一条明确的反向判断。
> 两文冲突时以本文为准，并把 `battle-loop-hooks.md` 的对应行改掉（§8 列了它已经过期的地方）。

---

## 0. 结论摘要（先看这一节）

### 0.1 五句话

1. **接口按"档 2"冻**：`CombatState` 上三个队列（效果 / 事件 / 续延）+ 一条效果链（chain）的
   **id + 触发栈**。三个队列**都不进哈希、不进快照**（§4.2）。
2. **不要做档 1**。理由不是"档 1 错"，而是"档 1 便宜不了多少"：真正贵的三件事（`exec.rs` 从
   "就地应用"拆成"请求 + 解析"、递归走树换成续延调度、`host.rs` 的触发器分发）**两档都要做**；
   差额只是 raise 点的数量，而那是每处一行的机械活（§5.4）。
3. **`CARD_MULTI` 的 10 个 NOT-COMPARABLE 在档 1/档 2 下都会变成可对照**，因为它们的成因单一：
   敌人的 `DamageDealt` 触发 `doubt` 的 `-1 层`（§5.3）。**但这不等于它们会变绿** ——
   变绿要求层数变化的**时点**也对（§6.2）。
4. **加队列的内存代价**：`CombatState` 184,648 B（30.5% SRAM）→ 保守档 **+14.6 KiB(+8.1%)**、
   中档 **+28 KiB(+15.8%)**、忠实档（集合不截断）**+45 KiB(+25%)**。依据见 §4.3 的表，
   **两个杠杆都是"内容集合的上限"**，不是队列长度。
5. **三队列里最不能照抄的一条**：参考的 `Queue<Action<CombatState>>`（`C:CombatState.cs:10`）
   在 `no_std` + 零分配 + `forbid(unsafe_code)` 下**不可能存在**。续延必须编码成**数据**
   （§4.1.3）。这是本文最重要的一条，也是最容易被实现者"顺手用闭包装一下"毁掉的一条。

### 0.2 冻结方描述有误的地方（以现实为准）

| # | 任务书/旧文档的说法 | 现实 | 证据 |
|---|---|---|---|
| ① | "**12 种**触发事件在 Rust 侧根本没有建模" | **不是 12 种**。Rust 侧认识 **25 个名字**（`TriggerEvent::from_wire_name`），其中 4 个有钩子、**21 个归 `NotHandled`**。**12** 是**镜像里落到 `NotHandled` 的触发器行数**，来自 **6 种**事件（`DamageTaken` 1 / `DamageDealt` 1 / `StatusApplied` 3 / `StatusMerged` 3 / `StatusStacksChanged` 2 / `StatusRemoved` 2）。 | `K:host.rs:316-331`（25 个名字）、`K:host.rs:2299-2301`（12 行、6 种，注释里写着）；`native/fight_diff.py:1311-1313` 的 `KERNEL_UNMODELLED_TRIGGER_EVENTS` 也是这 6 个 |
| ② | "`doubt` 带 `DamageDealt` 触发器" ⇒ 暗示"只要事件能 fire 就行" | 触发器的**效果**是 `modifyStatusStacks(doubt, -1)` 作用于 `sel.source`（= 出手方）。而 `doubt` 还有一条**被动** `DamageDealt / ScalePercent 75 / Priority 100 / RestrictDamageKind=Direct`，**那条内核已经在跑，而且有专门的测试钉着**：`doubt_on_the_source_scales_paper_cut_from_six_to_four`（`K:exec.rs:5095-5124`，6 → 4，并钉了"放在承受者身上时读不到 ⇒ 6"的反例）。⇒ **缺的只有触发器那半边**，被动不要再算作缺口。 | `ref/.../bureaucrats.roguedeck.json` 的 `doubt` 定义（`Trigger` + `PassiveModifiers` 两段，本轮实测读出）；`K:exec.rs:5095-5124` |
| ③ | "`PendingEffects` / `PendingEvents` / `PendingContinuations` 三队列 + `_pendingEffectChains`/`_pendingEffectOwners` 并行数组" | 准确，但**是 6 个队列**：效果、效果链、效果归属者、事件、事件链、续延。并行结构存在的唯一理由是 C# 的 `Queue<T>` 不能装元组**且**作者想避免装箱；它有两条**断言不变式**（`EnsureEffectQueueMetadataAligned` / `EnsureEventQueueMetadataAligned`）专门守这个分裂。**Rust 侧不该照抄**（§4.1.2）。 | `C:CombatState.cs:5-10`、`:401-406`、`:436-440`、`:461-462`、`:487-490`、`:557-570` |
| ④ | （隐含）"事件队列一上，`chain_num` 就会漂" | **不会**。触发器**不**分配链号：`CreateTriggeredEffectChain` 在父链上 `AppendTriggeredEffectDefinition`，**同一条链、深度 +1**（`C:CombatState.cs:492-498` + `C:CombatEffectChain.cs:74-83`），而 `_nextEffectChainNumber++` 只在 `CreateRootEffectChain` 里（`:545-555`）。⇒ **事件/触发器只影响 `exec_num`，不影响 `chain_num`**（除了 §6.2 那个已知的续延调度副作用）。 | `C:CombatState.cs:492-498, 545-555`；`C:Effects/Programs/EffectProgramExecution.cs:27, 31` |
| ⑤ | "`TriggerActivity` 不进哈希" | **对**，但要说全：它**在快照里**、**不在哈希文本里**。`C:CombatState.cs:409-413` 的注释说它"deliberately not part of a snapshot"，**这句注释是过期的**：`C:CombatStateSnapshot.cs:141-151` 有 `TriggerActivity` 字段，`C:CombatStateSnapshotter.cs:65-69` 填它，`C:CombatState.cs:854-856` 还原它。 | 四处都读过，行号如上 |

### 0.3 一张图

```
                    ┌──────────────── 排空循环（§2）────────────────┐
 EnqueueEffect ─────►│ [相位 1] 抽干效果队列（FIFO，每条进自己的链）   │
 EnqueueEvent  ─────►│ [相位 2] 抽干事件队列（FIFO，每条进自己的链）   │
 EnqueueCont.  ─────►│ [相位 3] 若前两相都空：跑**一个**续延           │
                    └──────────────────────────────────────────────┘
 事件 → 同类型的 handler 按**注册序**跑（§3.3）→ 每个 handler 内：触发器按
 (Priority 升序, Id 序) 跑（§3.2）→ 触发器节目**同步**跑、但它入队的效果**延后**生效
```

---

## 1. 参考的三个队列：类型、容量、上限

### 1.1 声明

全部在 `C:CombatState.cs:5-10`（**【验证】**，本轮逐行读过）：

| 字段 | 类型 | 公开视图 | 行号 |
|---|---|---|---|
| `_pendingEffects` | `Queue<IEffectRequest>` | `PendingEffects`（`IReadOnlyCollection`）、`HasPendingEffects`、`PendingEffectCount` | `:5`、`:167`、`:192-194` |
| `_pendingEffectChains` | `Queue<CombatEffectChainContext>` | 无 | `:6` |
| `_pendingEffectOwners` | `Queue<EffectProgramExecutionId?>` | 无 | `:7` |
| `_pendingEvents` | `Queue<ICombatEvent>` | `PendingEvents`、`HasPendingEvents`、`PendingEventCount` | `:8`、`:169`、`:196-198` |
| `_pendingEventChains` | `Queue<CombatEffectChainContext>` | 无 | `:9` |
| `_pendingContinuations` | `Queue<Action<CombatState>>` | 只有 `HasPendingContinuations`、`TryDequeueContinuation` | `:10`、`:200`、`:472-473` |

另有两条**不属于队列**但和它一起被反复误读的字段：`_activeProgramFrames`（正在跑的节目帧，
`List`，`:11`）和 `_triggerActivity`（`Dictionary<TriggeredEffectDefinitionId,int>`，`:414`）。

### 1.2 条目形状

`C:CombatEffectChain.cs:86-93`（**【验证】**）：

```csharp
internal readonly record struct PendingEffectQueueEntry(
    IEffectRequest Request, CombatEffectChainContext EffectChain, EffectProgramExecutionId? OwningProgramExecutionId);
internal readonly record struct PendingEventQueueEntry(
    ICombatEvent CombatEvent, CombatEffectChainContext EffectChain);
```

触点：`DequeueNextEffectEntry`（`C:CombatState.cs:429-440`，**出队前**先 `EnsureEffectQueueMetadataAligned`）、
`DequeueNextEventEntry`（`:480-490`）。⇒ **三列并行数组在逻辑上就是一条记录**，
分裂是 C# 的表示问题，不是语义问题。

`OwningProgramExecutionId` 的唯一用途：效果解析时 handler **抛异常**，把它绑回当时正在跑的
节目帧（`frame.FaultDueToNativeHandler`，`C:CombatEffectQueueProcessor.cs:35-49`），
让那一帧走到终态而不是永远 `Running`。**它不参与任何排序、不进哈希。**

### 1.3 容量：队列**没有**上限，上限在排空循环

**【验证】**：`Queue<T>` 是无界堆队列；全仓既没有 `new Queue<T>(capacity)`，
也没有任何"入队时拒绝/截断"的代码路径。唯一的三个上限是**每轮排空的迭代次数**：

```csharp
// C:CombatExecutionLimits.cs:7-14
public int MaxQueueCycles      { get; }   // 默认 1024，:12
public int MaxEffectsPerCycle  { get; }   // 默认 1024，:13
public int MaxEventsPerCycle   { get; }   // 默认 1024，:14
```

超限**抛 `InvalidOperationException`**（`C:CombatEventHandling.cs:99-102`、`:53-55`、
`C:CombatEffectQueueProcessor.cs:24-26`），**不是**截断、**不是**静默跳过；而且
`ResolvePendingQueues` 的抛出消息会附带 `WhatIsLooping(combat)`（`:121-141`）——
把三个队列的当前内容与最近 10 条日志打进去。这意味着：

> **参考实现里"排空卡住"是一个响亮失败，且带现场。** 移植时任何"队列满了就丢掉"的行为
> 都是**新增的静默失败**，必须换成响亮失败。

⇒ **移植的硬约束**：Rust 侧必须给队列**固定容量**（零分配），因此必然引入参考没有的
"队列满"错误。这个错误**必须和 1024 超限同级**（`Err`，带现场），不许丢条目。

### 1.4 效果链上下文：一个**共享不可变对象**，不是一个数字

`C:CombatEffectChain.cs:8-41`（**【验证】**）：

| 成员 | 语义 | 行号 |
|---|---|---|
| `Id` | `CombatEffectChainId(long)`，**哈希行 `chain_num` 的那个数字** | `:3-6`、`:14` |
| `TriggerDepth` | `=> _triggeredEffectDefinitionIds.Count` —— 就是触发栈长度 | `:16` |
| `MaximumTriggerDepth` | 默认 **64**，`≤0` 在构造时抛 | `:10`、`:30-35` |
| `TriggeredEffectDefinitionIds` | 触发栈本体（`IReadOnlyList<TriggeredEffectDefinitionId>`） | `:20-21` |
| `CanEnterTriggeredEffectDefinition` | 重入抑制；`SuppressRecursiveReentry` ⇒ `!Contains(id)` | `:49-62` |
| `EnsureCanAppendTriggeredEffectDefinition` | 深度 ≥ 64 ⇒ **抛**（不是跳过） | `:64-72` |

三条进队列的路径（**【验证】**，全部读过）：

1. `EnterEffectChain(chain)`（`C:CombatState.cs:500-511`）—— 出队后 `using` 包住解析，
   把 `CurrentEffectChain` 临时换成条目带来的那条，出作用域还原。
2. `CreateRootEffectChain()`（`:545-555`）—— **唯一**的 `_nextEffectChainNumber++` 点。
3. `CreateTriggeredEffectChain(defId)`（`:492-498`）—— `parent.AppendTriggeredEffectDefinition(defId)`，
   **不发号**（父链 id 不变、深度 +1）。

入队时链从哪来：`EnqueueEffect` / `EnqueueEvent` 的公开重载都是
`var chain = CurrentEffectChain ?? CreateRootEffectChain();`（`C:CombatState.cs:386`、`:446`）
⇒ **只有"从没有链的状态开始一次新的入队瀑布"才发号**。还有第三个发号点在节目侧：
`executionContext.EffectChain ??= combat.CurrentEffectChain ?? combat.CreateRootEffectChain()`
（`C:Effects/Programs/EffectProgramExecution.cs:31`）。

---

## 2. 排空循环的精确形状

> `battle-loop-hooks.md` §1.1 给过骨架；本节补充它没写的四条语义，并给"与就地执行的根本差别"。

### 2.1 `ResolvePendingQueues`（`C:CombatEventHandling.cs:81-115`）——**三相位，不是"每条立刻排空"**

```
combat.DefinitionRegistry = registry;                       // :91（让表达式能读定义数据）
while ((HasPendingEffects || HasPendingEvents || HasPendingContinuations)
       && Result == Ongoing)                                // :97
{
    if (resolvedCycles >= limits.MaxQueueCycles) throw;      // :99-102
    ResolvePendingEffects(...);                              // :104  相位 1：**抽干**
    ResolvePendingEvents(...);                               // :105  相位 2：**抽干**
    if (!HasPendingEffects && !HasPendingEvents
        && TryDequeueContinuation(out var c)) c(combat);     // :107-111 相位 3：**只跑一个**
    resolvedCycles++;                                        // :113
}
```

**四条被问到的语义，逐条回答（【验证】）**：

| 问题 | 答案 | 依据 |
|---|---|---|
| FIFO？ | **是，每个队列各自严格 FIFO**（`Queue<T>.Dequeue`） | `:429-440`、`:480-490` |
| "每条效果处理完立刻排空"还是"批量"？ | **批量 + 相位**：效果队列**全抽干**才轮到事件队列；事件队列**全抽干**才轮到续延；续延**每轮只跑一个** | `:104-111` |
| `MaxEventsPerCycle` 的 `max` 语义 | **"本轮事件相位里最多解析多少个事件"**，超了抛；它**不**限制跨轮总数，也**不**限制队列长度 | `:49-55` |
| 相位 3 的进入条件为什么要"前两相都空" | 因为 `TryDequeueContinuation` 在 `if (!HasPendingEffects && !HasPendingEvents && …)` 里面 —— **续延永远晚于它派生的效果**。这是"节目真正结束"的定义 | `:107-111` |
| 战斗结束怎么办 | 两个循环的 `while` 都带 `Result == Ongoing` ⇒ 一旦终局，**队列里剩下的东西永远不解析**（不报错、不清理） | `:97`、`C:CombatEffectQueueProcessor.cs:22`、`:340-367`（`SetResult` 会把活动帧全部取消） |

### 2.2 单队列的循环

**效果相位**（`C:CombatEffectQueueProcessor.cs:7-58`）：

```
while (HasPendingEffects && Result == Ongoing) {          // :22
    if (resolvedEffects >= MaxEffectsPerCycle) throw;      // :24-26
    entry = DequeueNextEffectEntry();                      // :28
    try { using (EnterEffectChain(entry.EffectChain))      // :32
              _resolver.Resolve(combat, registry, entry.Request); }   // :33
    catch { 绑回 owning frame → FaultDueToNativeHandler → throw; }    // :35-49
    Trace(EffectResolved…); resolvedEffects++;              // :51-56
}
```

**事件相位**（`C:CombatEventHandling.cs:39-73`）：

```
while (HasPendingEvents && Result == Ongoing) {                       // :51
    if (resolvedEvents >= MaxEventsPerCycle) throw;                   // :53-55
    entry    = DequeueNextEventEntry();                               // :57
    handlers = registry.GetCombatEventHandlers(entry.CombatEvent.GetType()); // :58
    using (EnterEffectChain(entry.EffectChain))                       // :60
        foreach (var h in handlers) h.Handle(...);                    // :62-63
    Trace(CombatEventDispatched…, handlers.Count);                     // :66-69
}
```

⚠️ **注意 `:60` 的位置**：handler 跑在**入队者那条链**里（不是新链、不是无链）。
⇒ 触发器里 `EnqueueEffect` 拿到的 `CurrentEffectChain` 非空 ⇒ **不再发号**。
这就是 §0.2 ④ 的机制原因。

### 2.3 与"就地执行"的**根本**差别（这是本节的要点）

内核今天在 `exec.rs` 里**递归走树，节点直接写状态**（`K:exec.rs` 的 `walk.depth` 与
`MAX_NODE_DEPTH = 64`，`:443-445`）。参考的实现是**派发 + 续延**。两者不是"写法不同"，是
**四个可观察的差别**：

| # | 差别 | 可观察后果 | 依据 |
|---|---|---|---|
| **D1** | **效果之间隔着整个相位**：同一次入队瀑布里的效果按 FIFO 逐条生效，但**触发器的效果**要等这批效果**全部**生效完 | 多段伤害 × "受击加力量"类被动：参考里两段都用旧力量，就地执行里第二段用新力量 | `:104-105`；【未验证】用内容实测（见 §6.2 的证伪向量 V3） |
| **D2** | **事件永远晚于效果**：`DamageDealt` 在伤害效果**内部**入队，但它在**事件相位**才被分发 | "受伤后获得格挡"的格挡**挡不住**同一批里的下一次伤害 | 同上 |
| **D3** | **续延在顶层跑**：`TryDequeueContinuation` 在 `:107-111` 处调用，此时**没有** `EnterEffectChain` ⇒ `CurrentEffectChain == null` ⇒ 续延里的 `EnqueueEffect/EnqueueEvent` **会发新号** | `chain_num` 的 +2/+3 记账（`play.rs:703-753`）；**这是"节目终态落在哪条链里"的唯一决定者** | `:107-111`、`C:CombatState.cs:386/446` |
| **D4** | **程序完成 ≠ 程序的效果完成**（`Sequence` 先把所有孩子派发下去再数剩余） | 兄弟节点"谁最后完成"可变 ⇒ 终态环链也不同 | `play.rs:861-867` 记录（**读源码推的，未逐行验证**） |

⇒ **一句话**：就地执行是"深度优先、立即生效"，参考是"广度优先（相位）、延迟生效 + 显式续延"。
**"触发事件"只是这条差别的一个消费者；`chain_num` 的那两格红（§6.2）也是它的消费者。**

### 2.4 谁调排空（排空点清单）

**【验证】**（grep 全部命中，只看 `src/`）：

| 调用点 | 行号 | 说明 |
|---|---|---|
| `CardPlay.PlayCardCore` | `C:Cards/CardPlay.cs:106-108` | 出牌：`EnqueueCardPlayEffects` 之后**立刻**排空 |
| `ScenarioRunner.ExecuteHeroPlays` | `C:ScenarioRunner.cs:121-122` | 驱动层：入队 `PlayCardEffectRequest` → 排空 |
| `CombatTurnProcessor.StartCurrentTurn` | `C:CombatTurnProcessor.cs:28-37` | `EnqueueEvent(TurnStarted)` → 排空 |
| `CombatTurnProcessor.EndCurrentTurn` | `:61-70` / `:77-80` / `:94-98` | 三次：TurnEnded 后、Advance 后、跳过已死战斗员后 |
| `ScenarioCombatFactory` | `C:ScenarioCombatFactory.cs:141, 161` | 建战斗（起始状态 / innate）后 |
| `InteractiveCombat` / `PartyCombat` | `C:InteractiveCombat.cs:220, 285, 326, 371` 等 | UI 驱动 |
| `CombatReplayRunner` | `C:CombatReplayRunner.cs:35, 49` | 回放 |

⇒ **参考的规则是"任何一个 `Enqueue*` 之后都可以排空，而且顶层入口每次都会排空"**。
`battle-loop-hooks.md` §2.3 已经指出内核把这个名字用在了两个语义上（`QueuePile` 的
`ResolveOldest` vs 三队列排空），本文不改那个裁决，只要求：**三队列排空的入口必须与
`QueuePile` 解析分开命名**。

---

## 3. 触发器：注册、排序、计数

### 3.1 两路来源，合流排序

- **注册表**（不可变，内容装进来的）：`registry.GetTriggeredEffectDefinitions(typeof(TEvent))`
  （`C:CombatDefinitionRegistry.cs:215-221`），装填路径 = `STAT.Triggers[i]` →
  `StatusDataRebuild.RebuildTrigger` → `RegisterTriggeredEffectDefinition`（`battle-loop-hooks.md` §4.4 已核）。
- **临时规则**（战斗上的 `TemporaryTriggeredProgram`）：`combat.GetTemporaryTriggeredPrograms(typeof(TEvent))`。

两路在 handler 里合流（`C:Effects/TriggeredProgramDefinition.cs:88-106`）：
注册表那路**预先排好序并缓存**（`ConditionalWeakTable`，`:75-76`、`:88-93`）；
只有存在临时规则时才在**每次事件**上重新 `OrderBy/ThenBy` 合并（`:96-106`）。

### 3.2 排序 = **(Priority **升序**, Id 序)** —— 不是降序

**【验证】**，两处逐字读过：

```csharp
// C:TriggeredProgramDefinition.cs:91-92（注册表那路，缓存）
.OrderBy(d => d.Priority)
.ThenBy(d => d.Id.value)
// C:TriggeredProgramDefinition.cs:104-105（与临时规则合流那路）
.OrderBy(x => x.Definition.Priority)
.ThenBy(x => x.Definition.Id.value)
```

⚠️ **两个必须写进契约的细节**：

1. **升序**（`OrderBy`），不是"Priority 大的先"。`Priority` 缺省 0（`:35`），
   状态触发器恒 0（`battle-loop-hooks.md` §4.4）⇒ 镜像上实际就是**纯 id 字符串序**。
2. **第二排序键的比较器是"默认"**，不是 `StringComparer.Ordinal`。同一份代码里
   `C:CombatDefinitionRegistry.cs:70, 72` 明确写了 `StringComparer.Ordinal`，
   而 `TriggeredProgramDefinition.cs:92/105` **没写** ⇒ 走 `Comparer<string>.Default`
   （文化相关）。对镜像的 id 形状（`{slug}_trigger{n}`，全小写+下划线+数字）两者一致；
   **【未验证】**：若 id 里出现大写、连字符或非 ASCII，两者可能不同。
   ⇒ **内核必须用 `Ident<>` 的 ASCII 字节序（= Ordinal）**，并在规格里写明这处
   "参考自己的两个 comparer 不一致，我们取 Ordinal"。

### 3.3 事件 → handler 的顺序 = **注册序**

**【验证】**：

- `RegisterCombatEventHandler` 把 handler **append** 进该事件类型的 `List`，并对
  "同一事件类型同一 handler 类型重复注册"抛异常（`C:CombatDefinitionRegistryBuilder.cs:334-353`）。
- `GetCombatEventHandlers` 原样返回那个数组（`C:CombatDefinitionRegistry.cs:223-229`），
  **不排序**。
- ⇒ 事件语义的"顺序"完全由 `StandardCombatPackage.cs:121-139` 的**调用序**决定 ——
  这就是 turn-start 七步顺序的真正来源（`battle-loop-hooks.md` §0.1 已核）。

⇒ **内核侧契约**：`EventKind` → `&[HandlerId]` 的**静态表**，顺序 = 手写顺序，**不许排序**。
这张表就是冻结物；任何"按优先级排一下"的顺手改动都会把七步顺序打乱。

### 3.4 一个候选触发器的**判定顺序**（五道闸，顺序是规格）

`C:TriggeredProgramDefinition.cs:114-193`（**【验证】**，逐行）：

| 序 | 闸 | 通过条件 | 失败后果 | 行号 |
|---|---|---|---|---|
| 1 | 重入抑制 | `CurrentEffectChain.CanEnterTriggeredEffectDefinition(def)`（默认策略 = 链里没有它） | `continue`（跳过） | `:117-123` |
| 2 | 深度 | `TriggerDepth >= MaximumTriggerDepth` 先**记 trace**，然后 `EnsureCanAppend…` **抛** | **抛** | `:125-135` |
| 3 | 门控状态 | `GatingStatus` 非空且当前**没人在身** ⇒ 跳过（tracing 时不跳，为了诊断）；**在构造上下文与过滤器之前** | `continue` | `:137-144` |
| 4 | 上下文 | `ContextFactory` 返回 `null`（如战斗员不在场） | 静默 `continue` | `:146-154` |
| 5 | 过滤器 | `Filters.All(f => f.Matches(ctx))` | `continue` | `:156-161` |

跑法（`:163-192`）：记 `Fired` trace → `CreateTriggeredEffectChain(def.Id)`（**同链、深度 +1**）
→ `EnqueueContinuation`-free 地**同步**跑节目 `EffectProgramExecutor.Execute`（`:170-173`）→
`carried = null`（门控缓存失效，因为触发器可能刚给出那个状态）→ **计数**（§3.5）→
临时规则额外记 `RecordActivation` 并**入队** `TemporaryRuleActivated`（`:179-192`）。

⚠️ **闸 1/2 只在 `CurrentEffectChain` 非空时执行**（`:117`/`:128` 的 `is { } currentChain`）。
事件 phase 里 `EnterEffectChain(entry.EffectChain)` 保证了它非空（`C:CombatEventHandling.cs:60`）
⇒ 实际上恒非空。

### 3.5 `TriggerActivity`：**"跑了"不算，"入队了效果"才算**

**【验证】**（`C:TriggeredProgramDefinition.cs:166-177`）：

```csharp
var enqueuedBefore = combat.EffectsEnqueued;            // :168
using (combat.EnterEffectChain(triggeredChain))
    EffectProgramExecutor.Execute(...);                  // :170-173
if (combat.EffectsEnqueued > enqueuedBefore)             // :176
    combat.NoteTriggerActivity(definition.Id);           // :177
```

- `EffectsEnqueued` 是 `_effectsEnqueued` 这个**入队计数器**（`C:CombatState.cs:403`、`:415`、`:419`），
  **不是**"执行了效果"的计数。
- `NoteTriggerActivity` = `_triggerActivity[id]++`（`C:CombatState.cs:421-422`）。
- ⇒ 语义是：**程序跑了、并且至少入队了一个效果**，才 +1。跑了一圈什么都没入队的触发器**不计数**
  （`C:TriggerActivityTests.cs:57-64` 的 `pays`/`idle` 两格钉着它）。
- 可观察面：**不在哈希文本里**（`C:CombatStateHasher.cs:26-72` 全文无 `TriggerActivity`），
  **在快照里**（`C:CombatStateSnapshot.cs:141-151`），**没有任何 oracle 导出**
  （`native/RogueDeck.Oracle/**` 全文 grep `TriggerActivity` = 0 命中，本轮实测）。

⇒ **内核侧建议：不建模。** 理由：它的可观察面为零（不进哈希、不导出、不进 `rd-fightdump`），
而代价是 32 条 × 44 B ≈ 1.4 KB。**推翻条件（写在这里，别等它过期）**：一旦
①`rd_oracle_*` 新增任何"触发器活动"导出，或 ②任何验收闸门开始读存档/快照里的
`TriggerActivity`，或 ③内容里有规则**读**它（今天没有：`C:CombatState.cs:409-413` 明说
"nothing in the rules reads it"）。

---

## 4. 内核侧要加什么（**这一段是要签字的部分**）

### 4.1 `CombatState` 的新成员

#### 4.1.1 常量

```rust
// ---- 移植引入的容量（参考**没有**这些上限，见 §1.3）----
pub const MAX_PENDING_EFFECTS:       usize = 64;
pub const MAX_PENDING_EVENTS:        usize = 64;
pub const MAX_PENDING_CONTINUATIONS: usize = 64;
pub const MAX_LIVE_CHAINS:           usize = 64;  // 见 4.1.4
pub const MAX_EVENT_ID_LIST:         usize = 24;  // 集合型事件的**容量**（不是截断上限）：超出=响亮失败，见 4.3 末
// ---- 参考自己的上限，照抄 ----
pub const MAX_QUEUE_CYCLES:       u32 = 1024;  // C:CombatExecutionLimits.cs:12
pub const MAX_EFFECTS_PER_CYCLE:  u32 = 1024;  // :13
pub const MAX_EVENTS_PER_CYCLE:   u32 = 1024;  // :14
pub const MAX_TRIGGER_DEPTH:      u8  = 64;    // C:CombatEffectChain.cs:10
```

⚠️ `MAX_TRIGGER_DEPTH = 64` 和现有的 `exec.rs::MAX_NODE_DEPTH = 64`（`K:exec.rs:445`）是
**两件事**（一个是节目树深度，一个是触发器嵌套深度，参考里也是两个独立的数：
`MaxNodeDepth` 在节目信封上，`MaximumTriggerDepth` 在链上）。**不许共用同一个常量。**

#### 4.1.2 队列字段：**一条记录，不是并行数组**

```rust
pub struct PendingEffect {
    pub request: EffectRequest,          // 见 4.1.5
    pub chain:   ChainSlot,              // u16 索引，见 4.1.4（**不**存整条链）
    pub owner:   Option<ProgramExecutionSlot>,   // 只用于异常绑帧，不排序、不进哈希
}
pub struct PendingEvent {
    pub event: CombatEvent,
    pub chain: ChainSlot,
}
```

理由：参考的三列并行数组带两条断言不变式（`C:CombatState.cs:557-570`），
那是"`Queue<T>` 装不了元组"的产物。Rust 里把它们合成一条记录**语义完全等价**，
且消灭了一个可以漂移的不变式。**照抄并行数组是本接口最没意义的复杂度。**

#### 4.1.3 续延：**只能是数据，不能是闭包**（本文最重要的一条）

参考：`Queue<Action<CombatState>>`（`C:CombatState.cs:10`）、`TryDequeueContinuation`
（`:472-473`）。内核是 `no_std` + 零分配 + `forbid(unsafe_code)` ⇒ **装不下 `Box<dyn FnMut>`**。

```rust
/// 续延 = "某个节目帧的某一支走完了"。**只允许是数据。**
pub enum Continuation {
    /// 节点 `EnterContinuation` 的等价物：某帧的某条待续支线可以往前走了。
    ///
    /// ⚠️ **2026-10-19 批次 2 改过形状**：原冻结的是
    /// `ProgramResume { frame, node, ready: u8 }` 与一个 `ProgramTerminal { frame }`。落地时两处都得改，
    /// 而且都不是审美问题：
    /// * `ready` 没用了：那是"待续支线的就绪计数"，而真正的计数住在**节点槽**上
    ///   （`ProgramNodeSlot::remaining`，对应 `SequenceNodeExecutor` 捕获的 `var remaining`），
    ///   续延只需要说"这个槽完成了"。留一个字段却没人读，迟早有人读错。
    /// * `ProgramTerminal` **删掉了**：参考的终态回调是**同步**跑的（`MarkCompleted` →
    ///   `RunTerminalCleanup`，`C:EffectProgramIdentity.cs:121-129, 104-111`）。塞进续延队列会把它
    ///   挪到顶层（`C:CombatEventHandling.cs:107-111` 时 `CurrentEffectChain` 为 null）⇒ 它里面每次
    ///   `EnqueueEffect`/`EnqueueEvent` 都 `?? CreateRootEffectChain()` ⇒ **每次出牌多一个 `chain_num`**。
    ///   那不是"晚一点跑"，是**换了一条链**。⇒ 终态回调由 `exec.rs` 同步调用，它要的那点数据
    ///   （谁的牌、落哪个区）作为**数据**存在帧上（`ProgramTerminalHook`）。
    ProgramResume { frame: ProgramExecutionSlot, node: u16 },
    /// `Cards/CardPlay.cs:217 / :292` 的动作收尾。
    CloseAction { actor: CombatantId },
}
```

⚠️ **允许**把闭包**当参数传进来立刻调用**（`fn with_chain(&mut self, c: ChainSlot, f: impl FnOnce(&mut Self) -> R)`）；
**禁止**把闭包**存进队列**。这条规则要写进冻结契约，因为"用闭包把续延包装一下更省事"是最自然的
错误方向，而它一写就再也编译不进裸机目标（`acceptance.ps1` 的第 3/5/6 道闸门会红 —— 那是好事）。

#### 4.1.4 效果链：**arena + 父指针**，不是值

参考的 `CombatEffectChainContext` 是**共享不可变对象**，把 `TriggeredEffectDefinitionId[]`
整条带在身上（`C:CombatEffectChain.cs:12, 20-21, 39-40`）。如果 Rust 照抄成值类型，
一条深度 64 的链就是 64 × 41 B = **2.6 KiB**，而每个队列条目都要带一条链 ⇒ 灾难。

```rust
/// 持久化链表：一条链 = (父链, 自己这个触发器)。语义与参考的不可变快照等价。
pub struct ChainRecord {
    pub id:     i64,               // = 哈希行 chain_num 的那个数字
    pub parent: Option<ChainSlot>,
    pub trigger: u16,              // 触发器 id 的 intern 序号（内容装载时建表）
    pub depth:  u8,                // = parent.depth + 1，冗余存一份免得走链
    pub refs:   u8,                // 队列条目 + 作用域栈的引用计数，归零可回收
}
pub struct ChainSlot(u16);          // 队列条目里只存这个（2 B）
```

- **id 仍是 i64 且仍在 `CreateRootEffectChain` 处自增**（`C:CombatState.cs:545-555`）——
  它是哈希行，语义一个字都不能改。
- `refs` 是我们新增的簿记（参考有 GC）。**`refs` 归零的时机不是可观察的**；
  但"`MAX_LIVE_CHAINS` 用完"是**新增的响亮失败**（§1.3 的底线）。
- 触发器 id 的 intern：`TriggeredEffectDefinitionId` 在镜像里有 25 个、StS 全集也远小于 65536。
  intern 表可以住在 `Content` 里（内容装载时建），**不进 `CombatState`**。

#### 4.1.5 `EffectRequest` / `CombatEvent`：枚举，变体数 = 内容真的会产生的东西

```rust
pub enum EffectRequest {           // 参考的 IEffectRequest；**只装"会被解析的效果"**
    DealDamage { .. }, GainBlock { .. }, ApplyStatus { .. }, ModifyStatusStacks { .. },
    MoveCardToZone { .. }, DrawCards { .. }, CreateCardInstance { .. },
    GainResource { .. }, LoseResource { .. }, SetCombatantCounter { .. },
    SetLifecycle { .. }, ClearDefensivePool { .. }, TickDamageOverTime { .. },
    ResolveQueuedCards { .. }, /* … 与 EffectRequestHandler 的注册表一一对应 */
}
pub enum CombatEvent {             // 参考的 41 个 ICombatEvent record
    TurnStarted { .. }, TurnEnded { .. }, RoundStarted { .. }, RoundEnded { .. },
    DamageDealt { .. }, DamageTaken { .. }, /* … 全 41 个 */
}
```

**"41 个"的出处**：`C:CombatEvents.cs` 里有 **39** 条 `) : ICombatEvent;`（本轮实测计数），
另有两条在单独文件里 —— `ActionStartingTriggeredEffects.cs:14`、`ActionResolvedTriggeredEffects.cs:15`。

⚠️ **变体清单必须是"参考全集"还是"当前内容会用到的"？**
**答：接口按全集冻（41 个事件变体 + 效果变体），接线分批（§5.4）。** 理由：变体是**数据形状**，
加一个变体不改接口、不改调用者；而"哪些点会 `enqueue_event`"是**行为**，可以一条一条加、
每条都能用 diff 独立证伪。把两件事混在一起谈，就会得出"先冻一个小版本"的错误结论。

### 4.2 哈希与快照：**三个队列都不进**

| 面 | 结论 | 证据（全部【验证】，本轮逐行读过） |
|---|---|---|
| 快照记录 | **不含队列**。文件头写着 "Excludes transient execution queues and the combat log (output, not input state)" | `C:CombatStateSnapshot.cs:94`；字段表 `:120-151` 里只有 `NextEffectChainNumber` / `NextProgramExecutionId` / `TriggerActivity` 三个"执行相关"项 |
| 快照生成 | 不读队列 | `C:CombatStateSnapshotter.cs:42-71`（没有任何 `Pending*`） |
| **哈希文本** | **不含队列**。`AppendSnapshot` 全文只写 `id/seed/step/result/round/turn/phase/active/status_num/card_num/chain_num/exec_num/turn_order/gs/c/cz/tr` | `C:CombatStateHasher.cs:26-72` |
| 哈希里**有的**执行痕迹 | `chain_num=`（`:38`）、`exec_num=`（`:39`）—— **是计数器，不是队列内容** | 同上 |
| `rd_oracle_pending` 读什么 | `_pending = final.PendingEffectCount` ⇒ **只数效果队列的深度**，事件/续延**不数**；在**运行结束后**采样（脚本总会排空 ⇒ 恒 0 不是异常） | `native/RogueDeck.Oracle/OracleExports.cs:125, 208-210`；同样三份 `OracleExports.Extended.cs:254`、`OracleExports.Fight.cs:414`；`docs/spec/oracle-abi.md:121` |
| `rd_oracle_log_count` | 战斗日志条数（另一个"不进哈希"的附录结构） | `OracleExports.cs:126, 212-214` |
| 存档/恢复 | 参考在**静止点**存档（"no in-flight effect queue / program frames — those are output, not input"），恢复时**队列从空开始** | `C:CombatState.cs:718` 注释、`:795-796` 的还原 |

⇒ **结论（要签字的那一行）**，分两半，别合并读：

- **队列本身不移动基线**：它的**内容**不进哈希文本、不进快照、不被任何 oracle 导出读取
  （只有 `rd_oracle_pending` 数效果队列的深度，而它在静止点恒 0）。这不是"运气好"，
  是参考自己把队列划成了**输出**。
- **基线会漂的地方只有两处，而且都通过队列的"后果"**：
  1. `exec_num` —— 每个节目 +1（`C:EffectProgramExecution.cs:27` → `C:CombatState.cs:513-518`），
     **包括触发器节目**。⇒ 凡是"今天不跑、明天会跑"的触发器，其所在局面必漂。
     `CARD_MULTI` 的 10 格正是这一类（§5.3）。
  2. `chain_num` —— 只在续延调度改变"入队时有没有当前链"时漂（§2.3 的 D3/D4）。
     今天的 `play.rs` 用**手写发号**模拟了这件事（§5.2 末），所以**替换成真队列时这一项应该
     一进一出抵消**；剩下的是那 2 格已知红（§6.2 的 V2）。

⇒ 因此"182/62/394/85 会不会绿"取决于**这些局面里有没有触发器**，而不是取决于"加不加队列"。
`FIGHT_DIFF` 今天 182/182 绿 ⇒ 那 4 个场景里没有任何"今天不跑"的触发器（否则它今天就红了）
⇒ **它不该因为这一轮改动而漂；红了就说明改动伤到了别的东西**（V7 就是这条）。

#### 4.2.1 风险段：上面那两笔"不会漂"是**推断**，各有边界（2026-10-19 批次 2 补）

上面写的"基线会漂的地方只有两处"里，两条判断都不是从代码里读出来的**定理**，而是
"按参考的代码形状推的、恰好被批次 1 的实测覆盖了一次"的**推断**。批次 1 实测确实一条基线都没动
（§11.3），但**实测只覆盖了当时跑到的那 póker 局面**。两条推断各自的失效边界写在这里，
因为下一批（效果队列有生产者之后）就会走到离边界更近的地方：

| 推断 | 依据 | **失效边界**（具体到"哪一天会怎样"） |
|---|---|---|
| 触发器节目发的 `exec_num` **恰好 +1** | `C:EffectProgramExecution.cs:27`：`Execute` 每进一次就 `AllocateProgramExecutionId`，**包括触发器节目** | 它只保证"跑一个节目 = +1"。基线不漂还需要**第二个条件**：这一批新跑起来的节目，参考本来就在跑同一批。⇒ 一旦"触发器跑的次数"与参考不同（少跑/多跑一次），`exec_num` 就是差 1 而**不是**差 0，且这个差**不是**队列本身造成的 |
| 四个回合事件的**根链笔数一进一出正好抵消** | `C:CombatState.cs:446`：`var chain = CurrentEffectChain ?? CreateRootEffectChain()` —— **只在没有环境链时才发号** | **只要哪天出现"触发器在没有环境链的地方跑"，`chain_num` 就会多一笔**：那一刻节目里任何 `EnqueueEffect`/`EnqueueEvent` 都走 `?? CreateRootEffectChain()` 那一支（`:386`/`:446`），而参考的同一次入队是在**某条链里**发生的（⇒ +0）。反方向也成立：一旦某个回合边界事件改成"在某条效果链的作用域内部入队"，它就从 +1 变成 **+0**（少一笔）。这条边界的具体形状是：**"入队时有没有环境链"是语义，`chain_num` 是它唯一的观察者** |

⚠️ 还有一条：批次 1 的"一进一出抵消"只覆盖了**四条边界事件**（turn/round × started/ended）与
`DamageDealt`（它在链里入队，与参考一致）。它**没有**覆盖"节目终态落在哪条链里"——
那需要 `exec` 真的回报终态（批次 2），也正因为如此，`shredder_drawer` 那 2 格（§11.3 末）
才在批次 1 之后仍然红：它们差的**不是**续延 FIFO，是"终态落在哪条链里"这个**回报**。

### 4.3 成本估算（`CombatState` 184,648 B / 30.5% SRAM → ?）

**依据（可复核）**：内核 id 是内联字符串 —— `Ident<40>` = **41 B**、`Ident<16>` = **17 B**
（`K:state.rs:214-217, 128, 134`），`Option<Ident<40>>` = 42 B，`Option<i64>` = 16 B。
`Bounded<T,N>` = `[T; N] + len`，所以 `N × size_of::<T>()`。基线 184,648 B 见
`K:state.rs:52`（与 `rd-sizeprobe` 的实测打印同一来源）。

| 项 | 单条估算 | 数量 | 小计 |
|---|---|---|---|
| `PendingEffect` | `EffectRequest`（最大变体 `DealDamage`：目标选择器 ~42 + 金额 ~16 + `kind` 1 + `source` 42 + `source_card` 42 ≈ **144**，`ApplyStatus` ≈ **180** ⇒ 取 **192**）+ `chain` u16 2 + `owner` u32+tag 8 | 64 | **12.5 KiB** |
| `PendingEvent` | 最大变体是**集合型**：`StatusRemoved{target 41, ids[17;8] 136, def 41}` ≈ **218**；`StatusMerged` ≈ **200**；取 **224** + `chain` 2 | 64 | **14.2 KiB** |
| `Continuation` | 枚举，最大变体 `ProgramResume` = u16+u16+u8 ≈ **8** | 64 | **0.5 KiB** |
| `ChainRecord` arena | `id` 8 + `parent` 2 + `trigger` 2 + `depth` 1 + `refs` 1 = **16** | 64 | **1.0 KiB** |
| `TriggerActivity`（§3.5 建议不建模） | `Ident<40>` 41 + `u16` 2 | 32 | (1.4 KiB) |
| **合计** | | | **≈ 28.2 KiB ⇒ 184,648 → 213,500 B，30.5% → 35.3%** |

**三个档（队列容量 / 集合上限两个杠杆）**：

| 档 | 效果/事件/续延容量 | `MAX_EVENT_ID_LIST` | 增量 | 新总量 | SRAM |
|---|---|---|---|---|---|
| 保守 | 32 / 32 / 32 | 8 | **+14.6 KiB (+8.1%)** | ≈ 199,600 B | 33.0% |
| 中（上表） | 64 / 64 / 64 | 8 | **+28.2 KiB (+15.8%)** | ≈ 213,500 B | 35.3% |
| 忠实（集合不截断） | 64 / 64 / 64 | 24（= `MAX_STATUSES_PER_COMBATANT`） | **+45 KiB (+25%)** | ≈ 230,700 B | 38.1% |

**成本的真正驱动是"集合型事件"，不是队列长度**：`StatusRemoved` / `StatusesRemovedByPolarity` /
`CardsDrawn` / `HandDiscarded` / `CardsMovedBetweenZones` 在参考里带 `IReadOnlyCollection<…>`
（`C:CombatEvents.cs:66-71` `CardInstanceCreated`、`:72-77` `CardCostPaid`、`:85-88` `CardsDrawn`、`:90-93` `Shuffled`、`:95-98` `HandDiscarded`、`:100-105` `CardsMovedBetweenZones`、`:246-250` `StatusesRemovedByPolarity`、`:251-255` `StatusRemoved` —— **共 8 条**）。内联成数组后，`MAX_EVENT_ID_LIST` 每 +8
就是每事件 +136 B ⇒ 64 个事件的容量下 **+8.7 KiB**。

⇒ **`MAX_EVENT_ID_LIST` 定为 `24`（忠实档：集合型事件不截断）。** 2026-10-19 冻结方推翻了本文
原先的"建议 `8`"。**否决理由不是内存不够，是治理性的**：`8` 截断的对象是**集合型事件携带的
id 列表**，而参考在这里是 `IReadOnlyCollection`、**无界**（`C:CombatEvents.cs:85-105, 246-255`
那 8 条）。超出容量的那部分会**静默消失** —— 不报错、没有测试会红、没有计数器会动。
**那是语义降级，不是实现选择**；省下的 17 KB 是这条降级的**价格**，不是它的**理由**。

> **硬规则（原文照抄，不做解释）**：**"一个容量常量放大后行为会变 ⇒ 它是语义，不是实现选择；不许拿它去换预算，也不许作为推荐方案出现在取舍里。"**

⇒ **任何集合型事件超出容量时必须响亮失败，永不静默截断**，而且**只用现有的变体**（不发明新的）：

| 溢出的东西 | 用哪个变体 | 先例 |
|---|---|---|
| 集合型事件的 id 列表（`StatusRemoved` / `CardsDrawn` / …） | `BindError::BufferTooSmall { needed, have }`（`K:status_bind.rs:378`） | 同一个变体今天就在给"触发器句柄暂存区"用，注释原文："**不截断**：少读几条触发器等于内容静默不发作"（`K:status_bind.rs:505`）——**同一种静默，同一个理由** |
| 三个队列 / 链 arena 本身满了 | `ExecError::Capacity(CapacityError::Full(Container::…))`（`K:state.rs:151` 起） | 内核所有定容容器都走这一条，`Container` 加三个成员即可 |

"内容温和所以今天撞不到"是**观察，不是保证**：今天镜像最大集合是 `StatusesRemovedByPolarity`（≤24），
StS 侧 `Fiend Fire` / `Second Wind` 一次消耗整手（最多 10 张）。`24` 让这两条**不再越界**，
但 M2a 一进来内容就可能带 25 个 id ⇒ **这一条仍要在 M2a 复核**，且复核的方式是"溢出会不会红"，
不是"够不够用"。

**【估算标注】**：以上全部是**算术估算，未编译实测**。实测口径已存在：`rd-sizeprobe`
（`K:rd-sizeprobe/src/lib.rs:39, 144` 打印 `size_of::<CombatState>()` 与 SRAM 百分比）
与 `rd-wasm` 的探针 `:1136-1154`。**实现落地后第一件事是跑它，把上表换成实测值。**

### 4.4 内核要补的 API（建议签名）

```rust
impl CombatState {
    // ── 发号器（参考同名同义）──
    pub fn allocate_program_execution_id(&mut self) -> i64;        // C:CombatState.cs:513-518
    pub fn create_root_effect_chain(&mut self) -> Result<ChainSlot, QueueError>; // :545-555

    // ── 入队（参考的 ?? 规则是这两行的全部）──
    pub fn enqueue_effect(&mut self, req: EffectRequest) -> Result<(), QueueError>;
    pub fn enqueue_event(&mut self, ev: CombatEvent) -> Result<(), QueueError>;
    pub fn enqueue_continuation(&mut self, c: Continuation) -> Result<(), QueueError>;
    //     ↑ 三条都是 `let chain = self.current_chain().unwrap_or(self.create_root_effect_chain()?);`
    //        （C:CombatState.cs:386 / :446）

    // ── 链作用域（EnterEffectChain）──
    pub fn with_chain<R>(&mut self, c: ChainSlot, f: impl FnOnce(&mut Self) -> R) -> R; // :500-511
    pub fn create_triggered_chain(&mut self, trig: u16) -> Result<ChainSlot, QueueError>; // :492-498

    // ── 出队（参考先断言元数据对齐，我们没有并行数组 ⇒ 无需断言）──
    pub fn dequeue_effect(&mut self) -> Option<PendingEffect>;   // :429-440
    pub fn dequeue_event(&mut self) -> Option<PendingEvent>;     // :480-490
    pub fn try_dequeue_continuation(&mut self) -> Option<Continuation>; // :472-473
}

/// 排空：**与 `QueuePile` 的 `ResolveOldest` 分开命名**（battle-loops §2.3 的裁决）。
pub fn resolve_pending_queues(
    state: &mut CombatState, host: &mut impl EventHost, limits: QueueLimits,
) -> Result<(), QueueError>;
```

⚠️ `create_root_effect_chain` 这个名字**内核已经有了**（`play.rs:761` 等调它，返回 `i64`）。
落地时必须**改成返回 slot 而保持 id 语义**，或者保留两个函数（`create_root_effect_chain_id() -> i64`
给现有调用点 + 新函数返回 slot）。这是"要不要动 `play.rs` 的显式发号"的分水岭（§5.2）。

### 4.5 触发器分发要补的接口

```rust
/// 一个事件类型的 handler 列表，**顺序 = 静态表顺序 = 注册序**（§3.3），不许排序。
pub trait EventHost {
    fn dispatch_event(&mut self, state: &mut CombatState, ev: &CombatEvent) -> Result<(), HostError>;
}
/// 触发器候选的收集与排序（§3.2）：(Priority **升序**, Id **Ordinal** 序)。
pub fn triggers_for(state: &CombatState, event: TriggerEventKey) -> impl Iterator<Item = TriggerId>;
```

五个闸的顺序见 §3.4；**闸 2（深度）抛、闸 1/3/4/5 跳过**这个不对称必须原样保留。

---

## 5. 两档方案

### 5.1 定义

| | 档 1（最小） | 档 1b（"同步钩子"，= `sts-act1-plan.md` §G2 的"最小可行"） | 档 2（完整） |
|---|---|---|---|
| 三队列 | **有**（效果/事件/续延） | **无** | **有** |
| `exec.rs` | 拆成 "请求 + 解析"，递归树换成续延 | **不动**（仍是递归就地执行） | 同档 1 |
| 事件种类 | 只接 `DamageTaken` / `DamageDealt` / `CardPlayed` / `Downed`（4 种） | 同左，但**同步**调用 | 41 种全接 |
| 触发器 | 真的按 §3 跑，效果**入队延后** | 真的跑，效果**就地立即**生效 | 同档 1 |

⚠️ 任务书把"档 1"写成"只把敌人动作/出牌程序改成入队再排空，不实现全部 12 种事件"——
按那个定义档 1 **必然包含三队列**（否则"入队再排空"无从谈起）。所以我把"不带队列的
同步钩子"单列为 **档 1b**，因为 `sts-act1-plan.md:84` 已经把它当成"最小可行"推荐过一次，
它值得被单独判死刑。

### 5.2 逐维对比

| 维度 | 档 1 | 档 1b | 档 2 |
|---|---|---|---|
| **改哪些文件** | `state.rs`（队列+链 arena）、`exec.rs`（应用→请求，递归→续延，**大改**）、`host.rs`（分发+触发器跑）、`turn.rs`（`resolve_pending_queues` 变真）、`play.rs`（删掉手写发号，见下）、`intent.rs`（敌人动作 +2 的显式记账） | 只改 `host.rs` + 3 个 raise 点（`exec.rs::resolve_damage` 之后、`play.rs` 成功之后、生命归零之后） | 同档 1 + 30 处 raise 点 |
| **改哪些冻结契约** | `effect-program-ir.md`（"没有事件队列时 Sequence 与 CausalSequence 观察等价"，`K:exec.rs:70, 966` 两处**全部作废**）、`play-card-flow.md`（`chain_num` 的四笔账表）、`battle-loop-hooks.md` §2.3（`resolve_pending_queues` 的空实现论述）、`turn.rs` 的 trait 注释 | 只新增"钩子在 S8 之后同步跑"一节；**不改**已有顺序契约 | 同档 1 + 补齐 41 个事件的 raise 时点 |
| **动哈希基线吗** | **会**：`exec_num` 每跑一个触发器 +1（§4.2），`chain_num` 在 D3/D4 路径上会变 ⇒ 必须重跑 **182/182（FIGHT_DIFF）+ 62/62（CARD_DIFF）+ 394/394（ENEMY_DIFF）+ 85 份语料 + 129 golden** | **会**，且方式同上（同步钩子也跑节目、也发 `exec_num`） | **会**，同档 1 |
| **7 个敌人能跑吗** | **5/7**：`louse_red` `louse_green` `fungi_beast` `mad_gremlin` `gremlin_nob` 只需事件；`lagavulin` `the_guardian` 还要 G1（阶段/意图打断） | **5/7 但语义可疑**（见 §6.2 的 V3 向量） | **7/7**（G1 仍需另做，与本接口正交） |
| **`CARD_MULTI` 10 格能变可对照吗** | **能**（`DamageDealt` 接了 + 触发器真跑） | **能**（本轮内容上两种做法的哈希**预测相同**，未验证） | **能** |
| **`CARD_MULTI` 那 2 格红（`shredder_drawer`）** | **具备修的条件**（续延 FIFO 就是它的成因），但**不保证**修好（§6.2） | **修不了**（没有续延，D3/D4 不存在） | 同档 1 |
| **工作量** | **大**（`exec.rs` 是主战场，且**当前正被别人改**） | **中**（~300 行 + 3 个钩子） | **大**（档 1 + 约 30 处 raise 点 + 41 个变体） |
| **档 2 到来时会被丢掉吗** | **不会**：三队列、续延编码、分发表、raise 点全部保留（真子集） | **会丢一半**：raise 点留下，但"何时执行 handler"整段重做，所有依赖次序的推理作废 | — |

**关于 `play.rs` 的手写发号（两档共同的账）**：`play.rs:703-753` 有一张"四笔账"表
（正常 +3 / Cancelled +1 / Faulted +1 / 无节目 +2 / 被拒 +1），是**没有队列时**用显式
`create_root_effect_chain()` 模拟出来的。**实测的 5 个显式发号点**（`K:play.rs` 全文 grep）：

| 行 | 模拟的是参考的哪一次入队 |
|---|---|
| `:496` | 被校验器拒绝的出牌请求（`C:ScenarioRunner.cs:121` 先入队才拒绝） |
| `:761` | 请求面（`Face::Queued`）本身 |
| `:778` | 无节目分支的 `EnqueueContinuation(CloseAction)`（续延在链外 ⇒ 发号） |
| `:885` | `onTerminal(Completed)` 的搬区 |
| `:887` | `onTerminal(Completed)` 的收尾 `CloseAction` |

另外 `:790` 有 `allocate_program_execution_id()`（对应 `C:EffectProgramExecution.cs:27`，
**这个不用删**，参考那里也是显式调用）。

三队列一上，前五笔就**自然发生**，那五行必须删掉 —— 否则会**双倍发号**。
⚠️ **落地顺序要求**：删显式发号与接排空必须**同一个提交**，中间态必然有一个数不对，
而"中间态跑一遍验收"会给出一个看起来像回归的假信号。

### 5.3 为什么那 10 格会变可对照（机制，逐条）

0. **被动那半边今天是绿的**：`doubt` 的 `DamageDealt/ScalePercent 75` 被`doubt_on_the_source_scales_paper_cut_from_six_to_four`（`K:exec.rs:5095-5124`）钉着（6 → 4，含"放在承受者身上读不到 ⇒ 6"的反例）⇒ 差异**只**来自触发器那半边。
1. `doubt` 的触发器 = `DamageDealt` → `modifyStatusStacks(doubt, -1)` 到 `sel.source`（§0.2 ②）。
2. `CARD_MULTI` 的两个变体都会让**敌人出手**，于是敌人**真的造成伤害** ⇒ `DamageDealt` 真发生。
3. C# 侧因此每次出手让敌人的 `doubt` 层数 −1 ⇒ 规范文本的 `s=doubt stk=N` 行与 Rust 不同。
4. `fight_diff.py` 把这个 MISMATCH 用 `kernel_gap_for`（`:1329-1346`）改判成 `NOT-COMPARABLE`，
   **判据正是**"卡把带未建模触发器的状态打到敌人身上 **且** 脚本里有敌人出手"（`:1333-1335`）。
5. ⇒ 一旦 `DamageDealt` 被 raise 且 doubt 的触发器真跑，条件 4 不再成立 ⇒ 该格变成
   **pass 或真 MISMATCH**，两种都属于"可对照"。

⚠️ **"能变可对照"≠"能变绿"**：绿还要求层数变化的**时点**与参考一致（§2.3 的 D1/D2）。
本轮**没有**实测这一点（需要真跑），列为 §6.2 的 V1 向量。

> **【2026-10-19 批次 1 实测纠正，方向错了】** 上面这段的**方向**是错的：实测那 10 格
> **直接变绿**，不是"变成可对照然后再等时点对上"（§11.3："那 10 格是**变成一致**而不是
> 变成可对照"，连 `chain_num`/`exec_num` 都逐字节相同）。真正脆的是**另一头**：
> 绿了之后它**不会**再退化成 `NOT-COMPARABLE` —— `kernel_gap_for` 的判据是"卡把带未建模
> 触发器的状态打到敌人身上**且**脚本里有敌人出手"，而触发器一旦有钩子，那条判据就不再成立
> ⇒ 下次 raise 点挪一格（链作用域内外、落血前后、入队早一步晚一步），这 10 格会直接从
> **绿**跳到**真 MISMATCH**，中间没有"可对照"这一站。
> ⇒ 正确的担心是"**绿得很脆**"，而不是"可能只是可对照"。§6.2 的 V1 因此要读成
> "把 raise 点挪进/挪出链作用域，那 10 格必须变红"。

### 5.4 推荐：**不做档 1（也不做档 1b），直接档 2**

一句话：**档 1 与档 2 的接口是同一个接口，差别只在变体的数量和 raise 点的数量；
既然接口一样，就没有理由先冻一个"4 个变体"的版本 —— 冻全，接线分批。**

三条理由：

1. **省下来的不是成本大头。** 贵的三件事 ——（a）`exec.rs` 把 15 种节点从"直接写状态"拆成
   "造 `EffectRequest` + 解析器"，（b）递归走树换成 `Continuation` 调度，（c）`host.rs` 的
   触发器分发 + 五道闸 —— **两档都要做**。档 1 相对档 2 少的东西是"30 处
   `enqueue_event(...)` 调用 + 一个 `match` 变体"，那是机械增量，不是难度增量。
2. **档 1b（同步钩子）在目标内容上就是错的。** 参考的两相位（`C:CombatEventHandling.cs:104-105`：
   效果全抽干才轮到事件）决定了"触发器效果晚于整批效果"。`mad_gremlin` 的 `Angry`
   （`sts-act1-plan.md:194`）撞上多段攻击时，两段伤害都用旧力量；同步钩子会让第二段用新力量。
   ⇒ 省下的活要在一个**内容进来就要重做**的方向上还回去。
3. **基线重跑的代价与事件种类数无关，只与"跑一次"有关。** `exec_num` 每个节目 +1、
   `chain_num` 在续延路径上变 —— 这两件事在档 1 里就已经发生了。分成两档 = 两组基线
   （182/62/394/85/129）重跑两次，合并成一次只跑一次。

**"接线分批"是什么意思**（这是档 2 内部的落地顺序，不是档 1）：

| 批 | 接什么 | `not_handled` 行数（`K:host.rs:2301` 的断言） | 判据 |
|---|---|---|---|
| 1 | 三队列 + 续延 + **`DamageDealt` / `DamageTaken` / `CardPlayed` / `Downed`** | 12 → **10**（`DamageTaken` 1 + `DamageDealt` 1 有了钩子） | `CARD_MULTI` **122/124**（2 格 `shredder_drawer` 留给 V2）；182/62/394/85 全绿 |
| 2 | `StatusApplied` / `StatusMerged` / `StatusStacksChanged` / `StatusRemoved` | 10 → **0**（剩下 10 行正好是这 4 种） | 镜像 25 条触发器**全部**有钩子；`host.rs` 的断言改成 0 |
| 3 | 其余 **17** 个 `TriggerEvent` 名字（25 − 4 已有 − 4 批 1 = 17） | 保持 0 | 新增 `STS_ENEMY` 层（`sts-act1-plan.md:320`） |

⚠️ 批 2 的"10 → 0"是**镜像层面**的（当前这一份内容）；批 3 打的 17 个名字在**镜像里一条
触发器都没有**，所以 `not_handled` 保持 0 并不说明它们被验过 —— 它们要靠 StS 内容来验。

每批都**只加 `enqueue_event` 调用点与 `CombatEvent` 变体的使用**，不动接口。

---

## 6. 迁移路径与证伪向量

### 6.1 档 1 是档 2 的子集吗？

**分开回答，因为两个"档 1"答案相反**（这是本文最需要签字的一段）：

| | 会被丢掉吗 | 说明 |
|---|---|---|
| **档 1（队列 + 4 事件）** | **不会，是真子集** | 队列形状、链 arena、续延枚举、分发表、4 个 raise 点全部保留；档 2 只是加 raise 点与 `CombatEvent` 变体。**但它仍然不值得先做**（§5.4） |
| **档 1b（同步钩子）** | **会丢掉"时机"这一半** | 3 个 raise 点留下（钩子还在那儿），但"handler 在哪个相位跑"整段重做；`sts-act1-plan.md:84` 那条"顺序契约只新增一条：hook 在 S8 之后同步跑"**会作废** |

⇒ **所以"该不该先做档 1"的答案是：不该。** 档 1 不节省主成本，而档 1b 明确会被回滚。

### 6.2 证伪向量（每条都要能**红**）

| # | 向量 | 期望 | 它证伪什么 |
|---|---|---|---|
| **V1** | 跑 `native/fight_diff.py --cards-multi`，看 10 个 doubt 格 | **122/124**（10 格从 NOT-COMPARABLE 变成 pass，剩下 2 格是 V2 的 `shredder_drawer`）。"NOT-COMPARABLE 消失了"本身不算成功 —— 变成真 MISMATCH 也一样消失 | 触发器的**层数变化时点**是否与参考一致 |
| **V2** | 同上，看 `shredder_drawer` / `shredder_drawer+` 的 `play_again` | step0 `chain_num` 从 4 → **3** | 续延 FIFO 是否复现了 D3（"最后完成的是谁"） |
| **V3** | 新造一局：多段攻击卡（2×N）打一个带"受击 +1 力量"的敌人，比对每段伤害 | 两段伤害**相同** | D1/D2 的相位（§2.3）。**档 1b 会在这条上红** |
| **V4** | 把 `MAX_PENDING_EVENTS` 调到 2，跑一个会一次产生 3 个事件的节目 | **响亮失败**（`Err` + 现场），不是静默丢 | §1.3 的底线 |
| **V5** | 跑 `rd-sizeprobe`，与 §4.3 的表比对 | 差 < 15% | 内存估算 |
| **V6** | `cargo check --target riscv32imac-unknown-none-elf` + `firmware-link` | 绿 | 续延被写成闭包就会在这里红（§4.1.3） |
| **V7** | 85 份语料 + 129 golden + `FIGHT_DIFF 182/182` | 全绿 | "队列不进哈希"（§4.2）。**这条红了就说明有人把队列内容塞进了 `snapshot.rs`** |
| **V8** | 把 `TriggerActivity` 计数改成"跑了就 +1"，重跑 V7 | **仍然全绿** | §3.5 的"不进哈希"结论（若红了，说明它其实可观察，我们的"不建模"就错了） |

---

## 7. 这次冻结最可能错的三条（我自己点名）

1. **"档 2 一次接完能让 `CARD_MULTI` 124/124 全绿（含那 2 格红）"** —— 最可能错。
   那 2 格靠的是**续延排队次序**这一条最薄弱的知识（`play.rs:875-876` 自己写着
   "读源码推的、没有逐行验证"）。"具备机制"不等于"一次到位"。
2. **"`chain_num` 不受触发器影响"** —— 在**触发器节目由 `EnterEffectChain` 包住**这条前提上成立
   （`C:CombatEventHandling.cs:60` + `C:TriggeredProgramDefinition.cs:170`）。但
   `C:EffectProgramExecution.cs:31` 还有一个 `?? CreateRootEffectChain()`：
   任何"节目在没有当前链的地方启动"的路径都会发号。我列出了三个发号点，**不敢说没有第四个**。
3. **`MAX_EVENT_ID_LIST = 8`** —— 这是**为了内存选的数**，不是从参考推出来的数。
   参考在这里**无界**。它今天不红是因为内容温和（最大集合 ≤4 张）。
   ⚠️ **已兑现（2026-10-19）**：它没有被 `Second Wind` 推翻，而是被**治理规则**推翻 ——
   "放大后行为会变 ⇒ 它是语义，不是实现选择"。现在 `= 24`，超出必须响亮失败（§4.3 末、§10.5）。

---

## 8. `battle-loop-hooks.md` 已经过期的行（顺手核对到的）

> 本文不动那个文件（本轮只准改 `acceptance.ps1` + 新建本文），但落地时必须一起改。

| 位置 | 原文 | 现实 |
|---|---|---|
| §2.3"内核现状与缺口" | "内核**没有三队列**" | 仍然正确（`K:state.rs` 无 `pending_*` 字段）。**但**同一段的 §5.5 已过期 ↓ |
| §2.3 哈希影响表 | "队列本身不入哈希（`CombatStateSnapshotter.cs:42-71` 里没有队列字段）" | **正确**，与本文 §4.2 一致 |
| §5.5 | "`chain_num` / `exec_num` 没有发号器……全仓 grep 不到任何 `+=`" | **已过期**：`K:host.rs:3167-3211`、`K:intent.rs:685-707, 1810-1859`、`K:play.rs:703-753, 759-762` 都已有发号与实测账 |
| §5.4 | "`status_bind::DamageKind` 只有 `Direct` 一个变体" | **已过期**：DoT 现在走独立的伤害种类管线（`K:status_bind.rs` 已扩，本轮未逐行复核 —— 标【未验证】） |
| §1.1 的上限表 | `MaxQueueCycles = MaxEffectsPerCycle = MaxEventsPerCycle = 1024` | **正确**（`C:CombatExecutionLimits.cs:12-14`） |

---

## 9. 我验证了什么 / 没验证什么

### 9.1 已验证（每条都可复核；本轮逐行读过原文）

**队列与排空（10 条）**
1. 六个队列的声明与类型（`C:CombatState.cs:5-10`）。
2. 三列并行数组 + 两条对齐断言（`:401-406`、`:436-440`、`:461-462`、`:487-490`、`:557-570`）。
3. 三相位排空循环 + 每轮一个续延（`C:CombatEventHandling.cs:97-114`）。
4. 效果相位 / 事件相位的 `while` 与各自的 cap（`C:CombatEffectQueueProcessor.cs:22-26`、`C:CombatEventHandling.cs:51-55`）。
5. 三个 cap 默认 1024、`≤0` 抛（`C:CombatExecutionLimits.cs:11-34`）。
6. 超限**抛**且带 `WhatIsLooping` 现场（`C:CombatEventHandling.cs:99-102, 121-141`）。
7. 事件 handler 跑在**入队者的链**里（`C:CombatEventHandling.cs:60`）。
8. 终局后两个循环都停、队列剩余不解析（`:97`、`C:CombatEffectQueueProcessor.cs:22`）。
9. 效果解析异常绑回 owning frame（`C:CombatEffectQueueProcessor.cs:35-49`）。
10. `rd_oracle_pending` = `PendingEffectCount`（`native/.../OracleExports.cs:125, 210`；另两份同）。

**链与发号器（6 条）**
11. `CombatEffectChainContext` 的 `Id/TriggerDepth/64/重入抑制/追加不发号`（`C:CombatEffectChain.cs:3-83`）。
12. 唯一 `_nextEffectChainNumber++` 在 `CreateRootEffectChain`（`C:CombatState.cs:545-555`）。
13. `EnqueueEffect`/`EnqueueEvent` 的 `?? CreateRootEffectChain()`（`:386`、`:446`）。
14. 第三个发号点：`EffectProgramExecution.cs:31`。
15. `exec_num` 每个节目 +1（`EffectProgramExecution.cs:27` → `CombatState.cs:513-518`）。
16. 触发器链不发号（`CombatState.cs:492-498`）。

**触发器（7 条）**
17. 排序 = `(Priority 升序, Id)`，两处都**没写** `StringComparer.Ordinal`（`TriggeredProgramDefinition.cs:91-92, 104-105`）。
18. 事件 handler = 注册序，重复注册抛（`CombatDefinitionRegistryBuilder.cs:334-353`、`CombatDefinitionRegistry.cs:223-229`）。
19. 五道闸的顺序与"跳过 vs 抛"的不对称（`TriggeredProgramDefinition.cs:117-161`）。
20. `TriggerActivity` 只在"入了效果"时 +1（`:168-177`、`CombatState.cs:403-422`）。
21. `TriggerActivity` 在快照里、不在哈希里、无 oracle 导出（`CombatStateSnapshot.cs:141-151`、`CombatStateHasher.cs:26-72`、grep=0）。
22. 触发器节目**同步**跑、效果入队（`:170-173`）。
23. 临时规则：`RecordActivation` + 入队 `TemporaryRuleActivated` + 过期剪枝（`:179-197`）。

**哈希/快照（4 条）**
24. `CombatStateSnapshot.cs:94` 明文"Excludes transient execution queues"。
25. `AppendSnapshot` 全文无队列（`CombatStateHasher.cs:26-72`）；有 `chain_num`/`exec_num`（`:38-39`）。
26. 参考在静止点存档、恢复时队列从空开始（`CombatState.cs:718, 795-796`）。
27. 参考共 **41** 个 `ICombatEvent` 记录（`C:CombatEvents.cs` 39 条 + `ActionStartingTriggeredEffects.cs:14` + `ActionResolvedTriggeredEffects.cs:15`），本轮逐条读过；其中 **8 条**带 `IReadOnlyCollection<>` 载荷（见 §4.3）。

**内核侧现状（5 条）**
28. 内核无 `pending_*` 字段（`K:state.rs` 的字段表，本轮读过）。
29. `Ident<40>` = 41 B、`Ident<16>` = 17 B（`K:state.rs:128, 134, 214-217`）。
30. `MAX_NODE_DEPTH = 64` 是**节目树深度**（`K:exec.rs:443-445`），与 `MaximumTriggerDepth` 无关。
31. `play.rs` 的四笔账 + 2 格已知红 + "要修得让 exec 回报终态落在哪条链"（`K:play.rs:703-753, 832-883`）。
32. `K:host.rs` 认识 25 个事件名、21 个归 `NotHandled`、镜像里 12 行 / 6 种（`K:host.rs:316-331, 2299-2301`）。

**内容（3 条）**
33. `doubt` 的触发器与被动两条都在（`bureaucrats.roguedeck.json`）。
34. `fight_diff.py` 的 `NOT-COMPARABLE` 判据（`:1329-1346`）+ 6 种未建模事件（`:1311-1313`）。
35. 7 个敌人只缺 G2、2 个还要 G1（`docs/spec/sts-act1-plan.md:215-219`、`:191-200`）。

### 9.2 未验证（按重要性排序）

1. **触发器效果的相位差在**本内容**上是否可观察**（D1/D2）。需要 V1/V3 向量真跑。
2. **`shredder_drawer` 的 2 格红能否被续延 FIFO 修好**（V2）。"续延排队次序决定谁最后完成"
   是**读源码推的**（`play.rs:875-876` 自己也这么说）。
3. **§4.3 的所有字节数**：算术估算，未编译。`rd-sizeprobe` 一跑就知道（V5）。
4. **`MAX_EVENT_ID_LIST = 8` 是否够**：今天够，StS M2a 会不够（§4.3 末段）。
   ⚠️ **已定案（2026-10-19）**：不用"够不够"回答，改成 `24` + 溢出响亮失败（§4.3 末、§10.5）。
5. **`StringComparer.Ordinal` vs 默认 comparer 的差别**：对镜像 id 一致；对别的 id 形状没有实测。
6. **`status_bind::DamageKind` 现在的实际变体集**（`battle-loop-hooks.md` §5.4 说只有 `Direct`，
   而 §8 说 DoT 管线已独立 —— 两者至少有一个过期，本轮没去核）。
7. **`CombatState.cs` 是否有第四个 `CreateRootEffectChain` 调用点**：我用的是 grep 而非全文通读。

---

## 10. 实测内存（2026-10-19）

> 本节**只追加**，不改上面任何一行。§4.3 的三档数字从今天起是**历史估算**：
> 它的结论（三档都越过 192 KiB）被实测证实了，但分量要对上账 —— 总额吻合是两处反向误差
> 几乎抵消出来的（§10.4）。
> 实测手段是给 `CombatState` 加一段**临时**的字段形状（只建字段，不实现任何队列逻辑），
> 量完还原：`state.rs` 的 sha256 与实验前逐字节相同（`F1080EBB…FABDB1`），
> `git status --porcelain` 为空。

### 10.1 基线真值（不是估算）

```
$ tools\cargo.ps1 test -p rd-core --release state_fits_the_sram_plan '--' --nocapture
size_of::<CombatState>() = 184648 bytes (180 KiB)
  card pool  : 224 x 440 = 98560 bytes
  combatants : 12 x 4832 = 57984 bytes
  piles      : 12 x 1392 = 16704 bytes
test result: ok. 1 passed; 0 failed; … 531 filtered out
```

⇒ **184,648 B = 606,208 B SRAM 的 30.46%**，与 §0.1 ⑤ / §4.3 的基线一致（这一条估算是对的）。
两个"抄了第二份"的数字同时过期，本轮已改成指路（不再复制）：

| 位置 | 原值 | 现实 |
|---|---|---|
| `kernel/rd-sizeprobe/src/lib.rs` 的 `the_state_model_fits_the_sram_budget…` 注释 | "当前实测 171,848 B" | 184,648 B（差 12,800 B，从 `StatusInstance.source_combatant_id` 那次起就没跟上；上界 192 KiB 没报警，因为 184,648 还没到） |
| `tools/size_probe.py` 末行 | "171,848 B = 28.3%" | 同上 |

⚠️ **`state.rs` 模块头那张表也烂了一行**（本轮**没有**改它，按任务书 `state.rs` 只用于实验）：
`combatants (12 × 3,872 = 46,464)` 与实测 `12 × 4,832 = 57,984` 差 **11,520 B**；
`size_of::<CombatState>()` 那一行（184,648）反倒是新的。⇒ 表里的总数跟着改过，行没跟着改。

### 10.2 三档实测（同一段形状，只改容量）

实验块的形状（照 §4.1.2–§4.1.5；载荷用内核**真实** id 类型，`CombatantId`/`StatusDefinitionId`
41 B、`StatusInstanceId`/`CardInstanceId` 17 B）：

| 探针类型 | 字段 |
|---|---|
| `EffectRequest` | 4 变体；最大 = `ApplyStatus{target,status,stacks,duration,source,source_card}`（六段，对应参考的状态施加请求） |
| `PendingEffect` | `{request, chain: u16, owner: Option<u32>}` |
| `CombatEvent` | 7 变体；集合型 3 个用 `Bounded<Id, MAX_EVENT_ID_LIST>`（`StatusRemoved` / `CardsDrawn` / `CardsMovedBetweenZones`） |
| `PendingEvent` | `{event, chain: u16}` |
| `Continuation` | §4.1.3 原样：`ProgramResume{frame,node,ready}` / `ProgramTerminal{frame}` / **`CloseAction{actor: CombatantId}`** |
| `ChainRecord` | `{id: i64, parent: Option<u16>, trigger: u16, depth: u8, refs: u8}` |

每档各跑一次 `probe_queue_memory`（打印条目尺寸 + 总量）：

```
PROBE tier: effects=32 events=32 conts=32 chains=64 idlist=8      ← 保守
PROBE EffectRequest                = 160
PROBE PendingEffect                = 172
PROBE CombatEvent                  = 220
PROBE PendingEvent                 = 224
PROBE Continuation                 = 44
PROBE ChainRecord                  = 16
PROBE CombatState               = 199768

PROBE tier: effects=64 events=64 conts=64 chains=64 idlist=8      ← 中
PROBE CombatState               = 213848

PROBE tier: effects=64 events=64 conts=64 chains=64 idlist=24     ← 忠实
PROBE CombatEvent                  = 492
PROBE PendingEvent                 = 496
PROBE CombatState               = 231256
```

| 档 | 效果/事件/续延 | `MAX_EVENT_ID_LIST` | 增量 | **实测总量** | SRAM | §4.3 估算 | 误差 |
|---|---|---|---|---|---|---|---|
| 基线 | — | — | — | **184,648** | 30.46% | 184,648 | 0 |
| 保守 | 32 / 32 / 32 | 8 | **+15,120 B (+14.77 KiB, +8.19%)** | **199,768** | 32.95% | 199,600 | +168 B (**+0.08%**) |
| 中 | 64 / 64 / 64 | 8 | **+29,200 B (+28.52 KiB, +15.81%)** | **213,848** | 35.28% | 213,500 | +348 B (**+0.16%**) |
| 忠实 | 64 / 64 / 64 | 24 | **+46,608 B (+45.52 KiB, +25.24%)** | **231,256** | 38.15% | 230,700 | +556 B (**+0.24%**) |

`MAX_LIVE_CHAINS` 三档都取 64（§4.1.1 的常数），它只占 1,024 B，**不是杠杆**。
⇒ **V5（"差 < 15%"）以 0.24% 的最大偏差通过。**

### 10.3 结论：三档**全部**越过 192 KiB

`state_fits_the_sram_plan`（`state.rs:2833`）与 `rd-sizeprobe` 的同名断言都是
`size <= 192 * 1024` = **196,608 B**。连最便宜的保守档都比它高 **3,160 B**。
⇒ 加队列**必然**要动这道上界；这不是"可能超"，是"一定超"。

**"几开"的账**（SRAM 606,208 B；RL 环境要多实例）：

| 档 | 单实例 | 2 开 | 3 开 |
|---|---|---|---|
| 基线 | 184,648 (30.5%) | 369,296 (60.9%) | 553,944 (91.4%) —— 已不可能 |
| 保守 | 199,768 (33.0%) | 399,536 (65.9%) | 599,304 (**98.9%**) |
| 中 | 213,848 (35.3%) | 427,696 (70.6%) | 641,544 (**105.8%**，超总预算) |
| 忠实 | 231,256 (38.1%) | 462,512 (76.3%) | 693,768 (114.4%) |

⚠️ **队列不是"几开"的杠杆**：三档都是"2 开可行、3 开不可行"，而这个结论在**加队列之前**
就已经成立（基线 3 开 = 91.4%，再留固件/栈/堆就没地方了）。真正的杠杆是 §3-D9 的
id intern（98,560 B 的卡池 + 57,984 B 的战斗员），以及它顺带把队列载荷从
`Ident<40>`(41 B) 压到 `u16`（`StatusInstanceId` 一旦 intern，`CombatEvent` 的集合型变体
会从 220/492 B 掉到几十字节）。**别把"加了队列所以开不了多实例"当成结论**。

### 10.4 与 §4.3 的估算逐项比对：**总额对上了，分量没对上**

| 项 | 实测 | §4.3 估算 | 差 | 说明 |
|---|---|---|---|---|
| `EffectRequest`（最大变体 `ApplyStatus`） | **160** | 192 | −32 | 估算取的是 `DealDamage` 144 与 `ApplyStatus` 180 的"取 192"；实测六段载荷 160 B 就够 |
| `PendingEffect` | **172** | 202 | −30 | 160 + chain 2 + owner 8 = 170 → 对齐 172 |
| `CombatEvent`（idlist=8） | **220** | 224 | −4 | 估算的 `ids[17;8] = 136` 与 §4.3 一样用对了 `INSTANCE_ID_CAP=16` ⇒ 17 B/个 |
| `PendingEvent` | **224** | 226 | −2 | |
| `Continuation` | **44** | **8** | **+36** | ← **唯一真错**，而且**被本文自己的 §4.1.3 推翻**：`CloseAction { actor: CombatantId }` 带一个 41 B 的内联 id，枚举大小由它决定，不是"u16+u16+u8 ≈ 8" |
| `ChainRecord` | **16** | 16 | 0 | |
| **合计（中档）** | **29,200 B** | 28,877 B（28.2 KiB） | +323 B | 两处反向误差几乎抵消（−30×64 与 +36×64） |

⇒ 教训只有一句：**总额吻合不等于分量吻合**。这里 −2,048 B（效果区 −1,920 + 事件区 −128）
与 +2,304 B（续延区）互相抵消，净 +256 B，剩余 +67 B 是结构体对齐 —— 也就是说
"28.2 KiB 的估算"能对上，**靠的是两个反方向的错**。若 `Continuation` 那一处到落地时才被发现，
它会变成一个"+2.25 KiB 的意外"。下一版估算请把**条目级**的数也写出来并对账，别只对总额。

### 10.5 决议：**忠实档（64/64/64，`MAX_EVENT_ID_LIST = 24`，集合型事件不截断）**，上界改成 **240 KiB（245,760 B）**

> **本节原来的结论是"推荐中档（`MAX_EVENT_ID_LIST = 8`）+ 上界 224 KiB"。那个结论已被推翻，
> 且不是因为算错了账（账是对的）。** 保留这段被推翻的记录，因为**否决理由本身就是一条规则**。

| 项 | 决议 | 理由 |
|---|---|---|
| **档位 = 忠实档 231,256 B** | `MAX_EVENT_ID_LIST = 24`，集合型事件**不截断** | **`MAX_EVENT_ID_LIST` 不是预算参数，是语义**：它放大后行为会变（参考在这里无界，`C:CombatEvents.cs:85-105, 246-255`），所以它是语义，不是实现选择 —— **不许拿它去换预算**。`8` 的真实代价是"超出部分静默消失、没有测试会红"，即**语义降级**；17.4 KiB 是这条降级的价格标签，不是选它的理由 |
| **中档已否决** | 不采纳 213,848 B / 上界 224 KiB | 否决理由同上一条，**不是**"忠实档更省"（它多花 17.4 KiB）。附带事实：省下的这 17.4 KiB **只省片上 SRAM** —— `CombatState` 是 POD（`Copy`、无指针、无内部引用），ESP32-P4 有 **16/32 MB PSRAM**，真要多开该做的是 §3-D9 的 id intern（98,560 B 卡池 + 57,984 B 战斗员），不是砍事件的集合上限 |
| **硬规则（原文照抄）** | — | **"一个容量常量放大后行为会变 ⇒ 它是语义，不是实现选择；不许拿它去换预算，也不许作为推荐方案出现在取舍里。"** |
| **超出容量怎么办** | `BindError::BufferTooSmall { needed, have }`（id 列表）/ `ExecError::Capacity(CapacityError::Full(Container::…))`（队列本身） | **永不静默截断**（§4.3 末给了两张表和先例；两个变体都是**现有**的，不新发明） |
| **上界 240 KiB（245,760 B）** | 231,256 → 245,760 是 **+6.3% 余量**（够再加一两个小字段） | **这次抬界换的是语义完整性，不是"让测试过"**：224 KiB 那条线本来就是为了拦住忠实档而设的（§10.5 旧文原话："谁要抬 `MAX_EVENT_ID_LIST`，就必须先看本节"）—— 现在看过了，结论是抬。**别再把它当成弹性预算**：下一次抬上界必须同样给出"放大后行为会变吗"的答案 |
| **要改两处** | `kernel/rd-core/src/state.rs` 的 `state_fits_the_sram_plan` 与 `kernel/rd-sizeprobe/src/lib.rs` 的同一条断言，**必须一起改** | 否则裸机侧和宿主侧会各说各话 |
| **同一提交里顺手做** | `state.rs` 模块头的内存表：加一行队列、把 `combatants` 那一行改成 57,984（§10.1）；`EMPTY` 从 184,648 涨到 231,256（若有人 `*state = EMPTY` 就付一次 231 KB memcpy）【未实测】 | — |

**为什么"中档"当初看起来是对的、而它其实错了**：旧论证的三条里，①"选它不改接口"是对的（`8` 是
§4.1.1 冻的常量）—— 但那说明**接口本来就冻错了**，不说明 `8` 对；②"32 深度会先撞墙"是对的，
它支持 64 而**不支持 8**；③"忠实档多付 17.4 KiB 换一个今天用不到的集合上限，那时该做 intern"
—— 这一条把"今天用不到"当成了"不会静默降级"。**"用不到"和"静默丢"是两件事**：前者是概率，
后者是已经发生的语义变化，只是没有观察者在看。

### 10.6 本轮实测与本文冲突的地方（以现实为准）

1. **§4.3 的 `Continuation ≈ 8 B` 与 §4.1.3 的冻结算术冲突**：按 §4.1.3 写出来的枚举是 **44 B**
   （`CloseAction { actor: CombatantId }` ⇒ 41 B 的 `Ident<40>` + tag + 对齐）。§4.3 那一行
   的 0.5 KiB 应为 **2.75 KiB**。本文没有改 §4.3 的原文，但实现者请按 44 B 记账。
2. **"`state_fits_the_sram_plan` 的上界与状态模型的真值在同一条断言里"是个假安全感**：
   断言只看到总量（184,648 ≤ 192 KiB），看不到模块头那张表里 `combatants` 那行已经错了 11,520 B。
   §10.1 记了这一条 —— "上界没红"不等于"文档里的数字是对的"。
3. **`rd-sizeprobe` 与 `size_probe.py` 各抄了一份总量**（171,848 B），与 `state.rs` 的真值脱节。
   已改成"指路 + 唯一出处"（`state_fits_the_sram_plan` 的 println / `COMBAT_STATE_BYTES`）。
4. **`MAX_LIVE_CHAINS = 64` 在三档里都不是杠杆**（1,024 B）。§4.1.1 把它和三个队列容量并列，
   容易让人以为"档位也调它"——调它只值 ±512 B。
5. **`PendingEffect` 的 `owner: Option<ProgramExecutionSlot>` 是真的贵**：`Option<u32>` = 8 B，
   64 条就是 512 B；而唯一的用途是"效果解析抛异常时把帧绑回去"（§1.2 末）。
   若落地时发现 `forbid(unsafe_code)` 下没有异常路径，这 512 B 可以省 —— 但那要等 §4.4 的
   错误类型定下来，本节不建议提前省。

### 10.7 复现方法（别从 §4.3 的估算抄，从这里抄）

1. 备份 `kernel/rd-core/src/state.rs`（记下 sha256）。
2. 在 `// The state` 段前插入探针类型（§10.2 表的六个 struct/enum + 5 个常量）。
3. 给 `CombatState` 加 4 个字段（`pending_effects/events/continuations` 用 `Bounded<…, N>`，
   外加 `chains`），并在 `impl Empty for CombatState` 的 `EMPTY` 与 `fn blank()` 里各补 4 行
   `Bounded::new()` —— **三处都要改**，少一处编译不过（这也说明"加字段"不是一处改动）。
4. 加一个打印 `size_of::<…>()` 的 `#[test]`，`tools\cargo.ps1 test -p rd-core --release <测试名> '--' --nocapture`。
5. 改常量换档，重跑。还原时用备份覆盖，**然后 `touch` 一次源文件**（`Copy-Item` 会把 mtime
   一起恢复，cargo 会拿旧 rlib 复用，于是量到的是上一档的数 —— 这条坑本项目踩过）。
6. 还原后必须 `cargo test -p rd-core --release` 全绿（本轮 **532 passed**）再看 `git status`。

---

## 11. 批次 1 落地实况（2026-10-19，**只追加**）

> 这一节记录**做完了什么、量到了什么**。上面 §0–§10 的推理不改（§10.5 的档位决议已在原地改过）。
> 凡是本节与上面的估算冲突，以本节为准。

### 11.1 落地形状

| 项 | 实况 | 与冻结文档的差异 |
|---|---|---|
| 六个队列 | **有**：`pending_effects` / `pending_effect_chains` / `pending_effect_owners` / `pending_events` / `pending_event_chains` / `pending_continuations`，每列一个 `Fifo<T, 64>`（环形缓冲） | **照参考的三列并行数组 + 两条对齐断言**（任务书要求），而不是 §4.1.2 建议的"合成一条记录"。断言是**真的检查**（`ensure_effect_queue_aligned` / `ensure_event_queue_aligned`，每次出队前跑），不是 `debug_assert!` |
| 链 arena | `ChainArena`：`128 × ChainRecord(16 B)` = 2,048 B，`refs` 归零即回收 | `MAX_LIVE_CHAINS` 从 64 → **128**：最坏局面是"事件队列装满（64 条各持一条链）+ 正在分发那条派生出的触发链（+1）"⇒ 65，取 2 倍余量。**它是"到顶就响亮失败"的容量，不是预算杠杆** |
| 档位 | **忠实档**：`MAX_EVENT_ID_LIST = 24`，集合型事件**不截断**（`EventIdList::push` 超了返回 `Full(Container::EventIdList)`） | 与 §10.5 的决议一致 |
| 上界 | **240 KiB（245,760 B）**，`state.rs` 与 `rd-sizeprobe` 两处一起改 | 一致 |
| 排空循环 | `Host::resolve_pending_queues_with(state, QueueLimits)`：`while has_pending && Result == Ongoing` → 相位 1 抽干效果 → 相位 2 抽干事件 → 相位 3 只跑**一个**续延（且前两相都空） | 逐行照 `CombatEventHandling.cs:97-113`。三个上限（1024/1024/1024）做成 `QueueLimits` **参数**，于是测试能把它们当场撞出来 |
| 四个回合事件 | `TurnStarted` / `TurnEnded` / `RoundStarted` / `RoundEnded` 都走 `enqueue_event_at_root` + 排空；**链号笔数不变**（那一笔从 `TurnHost` 适配器挪进了入队，一进一出抵消） | 一致 |
| `DamageDealt` | **接了**：`exec.rs::resolve_damage_of_kind` 在落血/判胜负之后入队（`DamageEffects.cs:186-194`）；`host.rs` 按 **Bearer = 出手方**（`StatusDataRebuild.cs:53-55`）收集并跑触发器，上下文 `sel.source = SourceCombatant`、`eventTarget = TargetCombatantId` | `not_handled` 12 → **11**（`DamageDealt` 那 1 行不再是缺口） |
| 续延 | 队列 + 相位 3 + `CloseAction` 的**执行**（`current_chain` 为空才发号）；`ProgramResume` / `ProgramTerminal` **响亮失败** | **节点级续延调度（`exec.rs` 拆成"请求 + 解析"）留到批次 2**。`play.rs` 的两处 `EnqueueContinuation(CloseAction)` 仍是手工发号（`:785`/`:894`），搬进队列会改变 `play.rs` 自己那些"发号笔数"断言的可观察点 |
| 效果队列 | **没有生产者**（`exec.rs` 仍是就地应用）⇒ 相位 1 拿到条目就 `HostError::Unsupported("EffectRequest")` | 批次 2 补解析器 |

### 11.2 实测内存（**不是估算**）

```
size_of::<CombatState>() = 207712 bytes (202 KiB)      ← 34.3% of 606,208 B SRAM
  card pool  : 224 x 440 = 98560 bytes
  combatants : 12 x 4832 = 57984 bytes
  piles      : 12 x 1392 = 16704 bytes
  queue      : effects 64 x 176 | events 64 x 96 | conts 64 x 44 | chains 128 x 16 = 23040 B
```

⇒ **184,648 → 207,712 B（+23,064 B，+11.2%）**，SRAM 30.46% → **34.26%**。

⚠️ **它比 §10.2 探针的忠实档 231,256 B 小 23,544 B**，原因只有一个：探针按
"`CombatEvent` = 参考全集 41 个变体、集合型按 `idlist=24` ⇒ 492 B"量形状，
而**批次 1 只声明了接了线的那 5 个变体**（`CombatEvent` = **96 B**）。
差额是**还没有生产者的变体**，不是能力 —— 批次 2/3 每接一种事件，`CombatEvent` 会往
那个 492 B 长一段，`CombatState` 跟着长。**240 KiB 上界对两条都成立**（对 231,256 余 6.3%，
对 207,712 余 15.5%），它存在的理由是"别让全集形状静悄悄越界"。

### 11.3 对拍数字（四条基线，**全部按现实报**）

| 层 | 批次 1 之前 | 之后 | 变了吗 |
|---|---|---|---|
| `FIGHT_DIFF` | 182/182 | **182/182** | 没变 |
| `CARD_DIFF` | 62/62 | **62/62** | 没变 |
| `CARD_MULTI` | 112/124（10 不可对照 + 2 MISMATCH） | **122/124（0 不可对照 + 2 MISMATCH）** | 那 10 格变成**一致**（不是"变成真 MISMATCH"） |
| `ENEMY_DIFF` | 394/394 | **394/394** | 没变 |
| 单测 | 532 | **547** | +15 |
| 聚合验收 | 12/12 | **12/12** | 没变 |

**"没有基线漂移"这件事是结论，不是运气**：`DamageDealt` 的触发器节目**发号**（`exec_num` +1/节目）、
四个回合事件**建根链**（`chain_num` +1/事件）—— 这两笔在参考里本来就这么记，内核算出来的
数目与参考**逐字节相同**。⇒ §4.2 那条"队列内容不进哈希、只有它的后果会漂"得到了正面验证：
后果也对得上，所以一条基线都没动。

**那 10 格是"变成一致"而不是"变成可对照"**：`doubt` 的层数变化**时点**也与参考一致
（§5.3 的 D1/D2 那半条本来标着"未验证"，现在有了 10 个观测点的正面证据）。

**剩下 2 格（`shredder_drawer` / `shredder_drawer+` 的 `play_again`，step0 `chain_num` 4/3）
与续延无关**：它要的是"节目终态落在哪条链里"这个**回报**（批次 2 的 `exec.rs` 拆分），
不是"续延 FIFO"。⇒ 批次 1 的合格线（122/124）**不需要节点级续延**就已经达到。

### 11.4 这一轮**没能**用变异测试钉住的东西

"两相位塌成同步"（效果一入队就解析）在批次 1 **没有可观察后果**：效果队列没有生产者，
而且内核没有战斗日志。能钉住的是它的三个可观察的**近邻**，三个都已被变异测试判红：

| 变异 | 判红的测试 |
|---|---|
| 排空循环漏掉 `Result == Ongoing` 守卫 | `the_loop_condition_is_re_read_every_cycle_not_checked_once_at_the_door`（红在 1024 轮上限上） |
| 续延改成"入队即执行" | `a_continuation_waits_for_the_drain_and_runs_at_the_top_level`（①） |
| 续延无条件发号（= 不承认"跑在顶层"） | 同上（③ 的反例） |
| 队满静默丢弃 | `a_full_queue_refuses_the_65th_entry_instead_of_dropping_it` |
| 相位上限静默 `break` | `the_limits_are_loud_and_parameterised_so_they_can_be_reached` |
| 两相位掉序（先事件后效果） | `the_effect_phase_runs_before_the_event_phase` |

---

## 12. 批次 2 落地实况（2026-10-19，**只追加**）

> 这一节记录"做完了什么、量到了什么、哪里与上面的推理冲突"。**§0–§11 不改**（§4.1.3 的续延形状与
> §5.3 的方向性错误已在原地改过 —— 那两处冻结的是**接口/结论**，不是历史记录）。

### 12.1 落地形状：exec 真的拆成了"请求 + 解析"

| 项 | 实况 | 依据 |
|---|---|---|
| 效果队列的**生产者** | **11 种产出型节点**全部改成"算好参数 → EnqueueEffect → 完成塞进续延"，**一个都不就地写状态** | C:EffectProgramNodeExecutors.cs 那 11 个 EnqueueEffect 调用点（:615/:658/:698/:738/:775/:835/:932/:990/:1015/:1404/:1480/:1936 一族） |
| 效果队列的**解析器** | exec::resolve_effect：拆请求、重建 ExecContext、调既有的实体函数（esolve_damage_of_kind / gain_block_for / pply_one_status / draw_for / …）。**修饰器与极性在解析时读**（C:DamageEffects.cs:273-320） | 相位 1（C:CombatEffectQueueHandler.cs 一族） |
| 节点级续延调度 | **真的调度**：帧 arena（8）+ 节点槽 arena（64）+ 循环快照 arena（4）。一条续延 = (帧槽, 节点槽)，节点槽带**父**与**计数**（= 参考闭包捕获的两样东西） | C:EffectProgramExecution.cs:91-160、:202-211、:496-504 |
| "节目终态落在哪条链里" | **有了回报**：ProgramExecutionFrame::terminal_chain 记下终态那一刻的 current_chain；收尾那一笔发不发号**由它决定**（enqueue_effect / close_action 的 ??） | C:CombatState.cs:386/446 |
| 出牌终态回调 | 从 play.rs 的手工账搬成**数据 + 同步调用**：ProgramTerminalHook::CardPlay{player, card, destination} + play::run_terminal_hook | C:Cards/CardPlay.cs:242-281 |
| play.rs 的链号账 | **一笔都不手写**了：请求链（开场建一条并 with_chain）+ 落区/收尾（终态回调里的 ??）。批 1 那三行显式 create_root_effect_chain() 全删 | 同上 |
| 续延形状 | ProgramResume{frame,node}（去掉 eady）、**删掉 ProgramTerminal** | 见 §4.1.3 的原位更正 |

### 12.2 实测内存（**不是估算**）

```
size_of::<CombatState>() = 213224 B (208 KiB), 35.2% of 606208 B SRAM   ← 批次 1 是 207712
  帧 arena    : 8   × 216 B = 1728 B
  节点槽 arena: 64  ×  12 B =  768 B
  循环快照    : 4   × 546 B = 2184 B      ← 目标 12×41+1 与卡 96×2+1 取大者 + 保存位
  残差（对齐等）
```

⇒ **207,712 → 213,224 B（+5,512 B，+2.7%）**，SRAM 34.26% → **35.24%**。上界 **245,760 B 仍然成立**
（余量 32,536 B）。⚠️ §11.2 那条提醒还在：CombatEvent 全集（492 B）比今天的 96 B 贵 ~24 KB，
两者相加 ≈ 237 KB，**仍在 245,760 以内，但余量只剩 ~8 KB** —— 下一次抬界之前必须先回答
"放大后行为会不会变"，而不是先看余量。

### 12.3 对拍数字（四条基线，**全部按现实报**）

| 层 | 批次 1 | 批次 2 | 变了吗 |
|---|---|---|---|
| FIGHT_DIFF | 182/182 | **182/182** | 没变 |
| CARD_DIFF | 62/62 | **62/62** | 没变 |
| CARD_MULTI | 122/124（2 MISMATCH） | **124/124（0 不可对照 + 0 MISMATCH）** | **那 2 格绿了** |
| ENEMY_DIFF | 394/394 | **394/394** | 没变 |
| 单测 | 547 | **549** | +2（新增两条机制钉子） |
| 聚合验收 | 12/12 | **12/12** | 没变（golden/corpus 一格都没漂） |

**那 2 格的机制（读完源码 + 现场可复现）**：shredder_drawer 的节目是
sequence[forEachCardInZone(Hand, junk), dealDamage(9)]，牌组两张都是 junk。
* 派发：orEach 先把第 1 趟的 Body 派发下去（:472），dealDamage 也派发（:615）⇒
  续延队列 = [body₀完成, dealDamage 完成]；
* 第 1 趟 Body 的续延把第 2 趟排到**队尾**（:502-503）⇒ 队列 = [dealDamage 完成, body₁完成]；
* ⇒ **最后一个完成的是 forEach 循环本身**，而它在
  using (c.EnterEffectChain(ctx.EffectChain!)) 里完成（:489-493 的 onComplete）
  ⇒ 节目终态落在**节目链里** ⇒ onTerminal 里的 EnqueueEffect/EnqueueEvent **都不发号**
  ⇒ 出牌合计 **+1**（只有请求那一笔）。
* 对照 rchive_the_evidence（	akeFirst=1，只走 1 张）：最后完成的是兄弟 gainBlock
  （它的续延在**顶层**跑）⇒ 终态在链外 ⇒ 收尾 **+1** ⇒ 出牌合计 **+2**。

⇒ 这一格的绿**不是把 4 改成 3 试出来的**：play.rs 里那三笔手工账被整段删掉了，
"发不发号"现在由 current_chain 在终态那一刻的取值决定，而那个取值由**谁最后完成**决定。

### 12.4 这一轮**新的能力边界**（如实）

1. **集合为空时参考是同步完成、内核排一条续延**（orEachTarget / orEachCardInZone 的空快照，
   :489-493 在 Execute 的栈上跑）。差别只在"终态落在哪条链里"那一刻可见，本内容里没有这种局面。
   **内容一来空集合它就会出现**（exec.rs::dispatch_for_each_* 各有一行注释指着这条）。
2. **严格面（play_card）比参考少两个链号**：参考的 PlayCardCore 在顶层跑，CardCostPaid
   （:138）与 CardPlayed（:144）各发一个号；本内核**没有这两个事件变体**。请求面
   （	ry_play_card，全局对拍走的那条）不受影响。
3. **exec::execute 是遗留入口**：它**不发号**（intent.rs 与旧调用方已经手工记过），只
   dopt_root_chain() 把那条链建出来。⚠️ 它**也不排空事件**（本层没有触发器分派器）——
   把事件出队丢掉会让 doubt 的 DamageDealt 触发器永远不跑（实测：CARD_MULTI 立刻退回 114/124）。
4. **play.rs 的无节目分支**仍然手工入队（搬区 + CloseAction 续延），因为那台机器不经过节目帧。

### 12.5 容量常量逐条（C1 那个问句的答案）

| 常量 | 值 | 放大后行为会变吗 | 结论 |
|---|---|---|---|
| MAX_PROGRAM_FRAMES | 8 | **不会** —— 只把"同时有几个节目在飞"推远，超了 Full(ProgramFrames) 响亮失败 | 容量，不是语义 |
| MAX_PROGRAM_NODE_SLOTS | 64 | **不会** —— 同上（节点槽 = 参考的闭包捕获） | 容量，不是语义 |
| MAX_PROGRAM_LOOPS | 4 | **不会** —— 同上（循环快照 = 参考闭包捕获的 CardInstanceId[]） | 容量，不是语义 |
| MAX_EVENT_ID_LIST | 24 | **会**（参考在这里无界） | **语义**，§10.5 的硬规则适用；本批没有动它 |
| 三个队列 64 / MAX_LIVE_CHAINS 128 | — | **不会** | 本批没有动它们；链引用计数这一轮**才真正平衡**（见 12.6） |

### 12.6 这一轮抓到的三处真 bug（都不是测试问题）

1. **效果队列条目没有持链引用**（enqueue_effect_with_owner 漏了 cquire）⇒ 帧的引用一放，
   条目手里的链就没了 ⇒ 下一次 cquire 报 Full(Chains)。**它伪装成"容量不够"**，
   而调大 MAX_LIVE_CHAINS 会把这条静默吞掉。
2. **ChainArena 的帧引用从未归还**（eap_frames 漏了 elease）⇒ 每跑一个节目漏一条链。
3. **循环的"下一趟下标"读错了槽**（读了刚完成的那个子槽，它的 emaining 恒 0）⇒ 循环一直重跑
   第 0 趟，第 2 趟搬同一张卡 ⇒ move_card_for 报 Modifier。**它伪装成"内容坏了"**。

### 12.7 变异测试（6 条，全部**真的红**）

| # | 变异 | 判红的测试 |
|---|---|---|
| M1 | 两相位掉序（事件相位排到效果相位之前） | host::the_effect_phase_runs_before_the_event_phase |
| M2 | close_action 无条件发号（= 批次 1 的做法） | play::the_program_terminal_lands_in_the_chain_exactly_when_the_loop_finishes_last |
| M3 | 循环走完**不重入**节目链 | 同上 |
| M4 | Sequence 的"还剩几个"记成 0 | 同上 |
| M5 | 帧回收时不还链引用 | exec::a_program_hands_back_the_chain_references_it_took |
| M6 | 触发器入队的效果**当场**解析（"塌成同步"的字面版） | host::the_effect_phase_runs_before_the_event_phase |

⇒ §11.4 那条"两相位塌成同步在批次 1 没有可观察后果"**在批次 2 之后有后果了**：
M1 与 M6 都被同一条测试判红，而那条测试的判据是"两条 DamageDealt 事件分发时 doubt 还在不在"
（exec_num 差 1）。