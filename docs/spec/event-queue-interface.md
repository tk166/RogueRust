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
pub const MAX_EVENT_ID_LIST:         usize = 8;   // 集合型事件的截断上限，见 4.3
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
    ProgramResume { frame: ProgramExecutionSlot, node: u16, ready: u8 },
    /// 节目进入终态（Completed/Faulted/Cancelled）：跑 `onTerminal`。
    ProgramTerminal { frame: ProgramExecutionSlot },
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

⇒ **建议 `MAX_EVENT_ID_LIST = 8`，并写清"内容一来它就失效"的条件**：
任何一次调用里"删除/抽/弃/搬"超过 8 张牌的**单条事件**。今天镜像的最大集合是
`StatusesRemovedByPolarity`（≤24），但内容里没有一张卡会一次删 8 个以上状态；
StS 侧的 `Fiend Fire`/`Second Wind` 会（一次消耗整手，最多 10 张）⇒ **M2a 之前必须复核这一条**。

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
   参考在这里**无界**。它今天不红是因为内容温和（最大集合 ≤4 张），StS 的
   `Second Wind` 一来就会推翻它。

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
5. **`StringComparer.Ordinal` vs 默认 comparer 的差别**：对镜像 id 一致；对别的 id 形状没有实测。
6. **`status_bind::DamageKind` 现在的实际变体集**（`battle-loop-hooks.md` §5.4 说只有 `Direct`，
   而 §8 说 DoT 管线已独立 —— 两者至少有一个过期，本轮没去核）。
7. **`CombatState.cs` 是否有第四个 `CreateRootEffectChain` 调用点**：我用的是 grep 而非全文通读。
