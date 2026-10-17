# RogueDeck 战斗内核重写规格书：战斗状态 · 回合状态机 · 效果队列 · 确定性与快照

**源仓库**：`D:\Vibe\sts-tui\ref\RogueDeck-Core`（C# / .NET 10，MIT）
**目标**：不依赖 .NET 的战斗内核，跑在 ESP32-P4（双核 RISC-V @360MHz、单精度 FPU、592KB SRAM、32MB PSRAM），并用作 RL 训练环境。
**路径缩写**（下文 `文件:行号` 均基于这三个基址）：`C:` = `src\RogueDeck.Core\Combat\`；`T:` = `tests\RogueDeck.Core.Tests\Combat\`；`S:` = `tests\RogueDeck.Sandbox.Tests\`。
标 **⚠** = 重写最易踩；**【必须】** = 逐位复刻；**【可简化】** = 允许嵌入式改写。

## 1. 职责与边界

### 1.1 内核拥有的（重写必须存在）

| 职责 | 载体 | 锚点 |
|---|---|---|
| 战斗状态容器（战员/牌区/状态/计数器/临时规则/日志） | `CombatState` | `C:CombatState.cs:3-201` |
| 回合状态机（轮转 + 同时队伍两套） | `CombatTurnProcessor` / `SimultaneousTurnProcessor` | `C:CombatTurnProcessor.cs:3`、`C:SimultaneousTurnProcessor.cs:9` |
| 效果/事件/续延三队列的排空循环 | `CombatQueueProcessor`（定义在事件文件里） | `C:CombatEventHandling.cs:76-115` |
| 效果派发（按请求运行时类型查 handler） | `CombatEffectResolver` | `C:CombatEffectResolver.cs:3-18` |
| 效果链 / 重入抑制 / 深度上限 | `CombatEffectChainContext` | `C:CombatEffectChain.cs:8-84` |
| 触发程序分发（按 event 类型 → `(priority,id)` 序） | `TriggeredProgramCombatEventHandler<TEvent,TContext>` | `C:Effects\TriggeredProgramDefinition.cs:69-198` |
| 执行预算（三道上限） | `CombatExecutionLimits` | `C:CombatExecutionLimits.cs:3-35` |
| 确定性随机 | `CombatRandom`（静态无状态） | `C:CombatRandom.cs:3-57` |
| 快照 / 哈希 / 还原 | `CombatStateSnapshotter` / `CombatStateHasher` / `CombatState.Restore` | `C:CombatStateSnapshotter.cs:5`、`C:CombatStateHasher.cs:14`、`C:CombatState.cs:727-887` |
| 外部输入模型与回放 | `ICombatCommand` + `CombatReplayRunner` | `C:CombatCommands.cs:6-31`、`C:CombatReplayRunner.cs:8-81` |
| 法令（改规则而非改数值的状态）读写 | `CombatDecrees` | `C:CombatDecrees.cs:70-125` |

### 1.2 明确**不属于**战斗状态的（可外置/丢弃）

- **不可变内容注册表** `CombatDefinitionRegistry`（牌/状态/敌人行动/触发定义/节点执行器/修饰器）：被 `CombatState.DefinitionRegistry` 绑定，但**不入快照、不入哈希**（`C:CombatState.cs:54-57`）→ 重写为**只读 ROM 表 + 整数句柄**。
- **输入协作者**：`ICombatCardChooser` / `ICombatOptionChooser` / `UpcomingIntentKind` 投影 / `TraceListener`（`C:CombatState.cs:59-84`、`C:Cards\CardZones.cs:33-51`）。契约是"对同一 combat 必须确定性"，但由宿主注入，不参与状态；缺席时兜底取第一个候选。
- **纯观察**：`CombatLog`（`C:CombatState.cs:173-184` 明说没有任何规则读日志）、trace 流（`C:CombatState.cs:710-712`）。
- **瞬时执行态**：三队列 + 续延队列 + `_activeProgramFrames` + `_actionScopes` + `_resolvingQueuedCards` + `_endedThisPhase`。快照注释明说"输出，不是输入状态"（`C:CombatState.cs:718-724`）。⚠ 但 `_actionScopes` 的**开/关时机**是可观察行为（§4.4），不能因"不入快照"就忽略。
- **持久化**：`System.Text.Json`（`C:Serialization\CombatJson.cs`、`CombatSaveJson.cs`）。内核只提供快照结构体。

### 1.3 两条边界硬约束

1. **快照只在静默点取**：队列与程序帧为空。带活跃临时规则的快照在无 registry 时被 `Restore` 拒绝（`C:CombatState.cs:727-736`）；带过期副作用的临时规则一律拒绝（`:767-769`）。
2. **内核不强制"只能由当前行动者出牌"**：`PlayCardCore` 只检查 `Result == Ongoing` 与 `source.IsAlive`（`C:Cards\CardPlay.cs:82-94`），**没有** `ActiveCombatantId == source` 校验。何时谁能出牌是宿主责任 —— 这条必须显式写进重写规格，否则对拍会跑偏。

## 2. 状态数据结构

### 2.1 `CombatState`（`C:CombatState.cs:3-201`）

**2.1.1 参与哈希的标量**（★ = 有陷阱）

| 字段 | 类型 | 取值 | 语义 | 锚点 |
|---|---|---|---|---|
| `Id` | `CombatId`(string) | 非空 | 战斗标识 | `:15` |
| `RandomSeed` | `int` | 任意 | RNG 种子 | `:31` |
| `RandomStep` | `int` | ≥0 | RNG 流位置，每次随机操作 +1 | `:52` |
| `CurrentRound` | `int` | ≥1，构造=1 | 轮次 | `:21` |
| `CurrentTurn` | `int` | ≥1，构造=1 | 回合内序号（跨轮重置为 1） | `:23` |
| `TurnPhase` | `CombatTurnPhase` | `WaitingToStartTurn`=0 / `TurnInProgress`=1 | 转场闸门（**仅**轮转模式用） | `:25`、`C:CombatPrimitives.cs:12-16` |
| `ActiveCombatantId` | `CombatantId?` | 首个 `AddCombatant` 的 id | 当前行动者 | `:27` |
| `Result` | `CombatResult` | `Ongoing`/`Victory`/`Defeat`/`Draw`/`Aborted` | 非 Ongoing ⇒ 两个排空循环立刻停 | `:29`、`C:CombatPrimitives.cs:3-10` |
| `NextStatusInstanceNumber` | `int` | ≥1 | 状态实例 id 发号器（`status_%06d`） | `:150`、`:680-687` |
| `NextCardInstanceNumber` | `int` | ≥1 | 卡实例 id 发号器（`card_%06d`） | `:152`、`:689-696` |
| ★ `NextSummonedCombatantNumber` | `int` | ≥1 | 召唤战员 id 发号器（`summoned_%06d`） | `:698-708` —— **快照有、哈希无**，见 §5.4 |
| `NextEffectChainNumber` | `long` | ≥1 | 效果链 id 发号器 | `:12`、`:545-555` |
| `NextProgramExecutionId` | `long` | ≥1 | 程序帧 id 发号器 | `:13`、`:513-518` |

**2.1.2 不参与哈希的配置 / 非状态字段**

| 字段 | 说明 | 锚点 |
|---|---|---|
| `MaximumTriggerDepth` (`int` ≥1，默认 **64**) | 构造参数；快照里**没有**，重写当常量处理 | `:33`、`C:CombatEffectChain.cs:10` |
| `CellExclusive` (`bool` `init`) | 格子互斥规则，默认 false | `:38` |
| `SimultaneousTeamTurns` (`bool` `init`) | 同时队伍回合开关，默认 false | `:44` |
| ⚠ `CurrentPhaseTeam` (`TeamId?`) | 同时模式的当前阶段队伍 —— **既不入快照也不入哈希** | `:47` |
| `DefinitionRegistry` / `CardChooser` / `OptionChooser` / `UpcomingIntentKind` / `TraceListener` | 宿主注入的协作者 | `:57-84`、`:710` |

**2.1.3 集合字段**

| 字段 | 类型 | 有序性 | 快照 | 锚点 |
|---|---|---|---|---|
| `_combatants` | `List<CombatantState>` | 加入序（= turn order） | ✅ 按 `TurnOrder` 重排 | `:154`、`Snapshotter.cs:12-14` |
| `_turnOrder` | `List<CombatantId>` | **必须保序** | ✅ | `:155` |
| `_globalStatuses` | `List<StatusInstance>` | 加入序 | ✅ | `:156` |
| `_cardZonesByCombatant` / `_cardPlayTurnStatsByCombatant` | `Dictionary<CombatantId, …>` | 按 key 查，**遍历序不定** | ✅ 按 `TurnOrder` | `:157-158` |
| `_combatLog` | `List<CombatLogEntry>` | append-only，**无上限** ⚠ | ❌ 纯观察 | `:159`、`:889-892` |
| `_temporaryTriggeredPrograms` | `List<TemporaryTriggeredProgram>` | 安装序 | ✅ 按 `Id` 序 | `:160`、`Snapshotter.cs:26-40` |
| `_triggerActivity` | `Dictionary<TriggeredEffectDefinitionId,int>` | 按 key 查 | ✅ 按 key 序 | `:414-422` |
| `_effectsEnqueued` | `long` 计数 | — | ❌ | `:415` |

**2.1.4 瞬时执行态（不入快照）**

- `_pendingEffects` / `_pendingEffectChains` / `_pendingEffectOwners`：三个平行 `Queue<>`，**必须同长**否则出队抛错（`:5-7`、`:557-563`）。
- `_pendingEvents` / `_pendingEventChains`：两个平行 `Queue<>`（`:8-9`、`:565-570`）。
- `_pendingContinuations`：`Queue<Action<CombatState>>` ⚠ .NET 委托（`:10`、`:465-473`）。
- `_activeProgramFrames`：`List<IEffectProgramExecutionFrame>`；战斗结束时全部 `CancelDueToCombatEnd()` 并清空（`:11`、`:369-380`）。
- `_actionScopes`：`Stack<ActionScope>`，`ActionScope{HashSet<string> Claims(Ordinal), bool DealtDamage}` —— 一次行动的"只生效一次"账本（`:96-132`）。
- `_resolvingQueuedCards`：`HashSet<CardInstanceId>`，防止排队卡自我递归（`:140-148`）。
- `_endedThisPhase`：`HashSet<CombatantId>`，同时模式本阶段已结束的成员（`:49-50`）。
- `CurrentEffectChain`：`CombatEffectChainContext?`，`using` 作用域进出（`:171`、`:500-511`）。

### 2.2 `CombatantState`（`C:CombatantState.cs:3-130`）

| 字段 | 类型 | 取值 | 语义 | 锚点 |
|---|---|---|---|---|
| `Id` | `CombatantId`(string) | 非空 | 战员标识 | `:5` |
| `DefinitionId` | `CombatantDefinitionId` | 非空 | 内容定义引用 | `:6` |
| `DisplayNameKey` | `string` | 非空白（`:88-89`） | 本地化 key；还原时被重造为 `combatant.{def}`（`C:CombatState.cs:803`）—— **不入哈希、不入快照** | `:7` |
| `TeamId` | `TeamId`(string) | 标准 `"player"`/`"enemy"` | 阵营 | `:9`、`C:StandardCombatIds.cs:7-9` |
| `OwnerId` / `ControllerId` | `CombatantId?` | — | 召唤物归属/操控者；**不入快照** | `:10-11` |
| `LifecycleState` | `CombatantLifecycleState` | `Alive`/`Downed`/`Dead`/`Removed`/`Escaped`/`Banished` | `IsAlive ⇔ == Alive` | `:13`、`:79`、`C:CombatPrimitives.cs:25-33` |
| `Health` | `HealthState{Current≥0, Max>0, Current≤Max}` | — | HP；`SetMax` 把 Current 夹到 Max | `:14`、`C:CombatPrimitives.cs:98-139` |
| `_resources` | `Dictionary<ResourceId, ValuePoolState>` | — | 资源池（含能量） | `:16` |
| `_defensivePools` | `Dictionary<DefensivePoolId, ValuePoolState>` | — | 防御池（含 Block） | `:17` |
| `_statuses` | `List<StatusInstance>` | **含 pending** | `Statuses` 只给 active；`AllStatuses` 给全部 | `:18`、`:27-30` |
| `_tags` | `HashSet<TagId>` | 实测**恒空** | 哈希里输出空行 | `:19`、`C:CombatState.cs:722-724` |
| `_counters` | `Dictionary<CounterId,int>` | 缺省读 0 | 整场持久的命名整数 | `:20`、`:64-71` |
| `Position` | `CombatPosition?{int X,int Y}` | null=未上格 | **可选** 2D 战场；核心回合/效果循环不读它 | `:76`、`C:CombatPrimitives.cs:55-60` |
| `IntentKey` | `string?` | — | 预告（telegraph） | `:77` |

⚠ `Statuses` getter 在存在 pending 实例时会 `Where(...).ToList()` —— **每次读取都分配一个 List**（`:27-28`）。热点，重写应用"两个分离数组 + active 计数"。

### 2.3 状态实例 `StatusInstance`（`C:StatusInstance.cs:3-114`）

`Id`(`status_%06d`) · `DefinitionId` · `OwnerCombatantId` · `SourceCombatantId?` · `SourceCardId?` · `Stacks ≥0` · `DurationTurns ≥0` · `Charges ≥0` · **`PendingTurns ≥0`**（`:20-22`：`IsActive ⇔ PendingTurns == 0`；pending 实例"可见可被清除，但无效 —— 不带修饰器、不触发、对一切'你有没有这个状态'隐身"）· `AppliedRound ≥1` / `AppliedTurn ≥1` · `Visibility`(Visible/Hidden/DebugOnly) · `Polarity`(Buff/Debuff/Neutral) · `_tags HashSet<TagId>` · `_counters Dictionary<CounterId,int>`。

### 2.4 牌堆分区（7 个区，`C:Cards\CardZones.cs`）

```csharp
enum CardZone { DrawPile, Hand, DiscardPile, ExhaustPile, BanishedPile, QueuePile, SetAsidePile }  // :3-22
enum ZonePlacement { Bottom, Top }                                                                  // :27-31
```

表示法：`CombatantCardZones` = **7 个独立的 `List<CardInstance>`**（`:151-159`），**没有**统一数组。

| 区 | 语义 | 顺序约定 | 锚点 |
|---|---|---|---|
| `DrawPile` | 抽牌堆 | **index 0 = 堆顶**；`DrawCards` 从 `[0]` 取；`Top` = `Insert(0,·)` | `:161`、`:212-223`、`:240-258` |
| `Hand` / `DiscardPile` / `ExhaustPile` / `BanishedPile` | 手牌 / 弃牌堆 / 消耗堆 / 放逐堆 | append | `:162-165` |
| `QueuePile` | **已打出但效果未发生的卡**（"队列"） | **FIFO，index 0 等最久** | `:167-168`、`C:Cards\QueueResolution.cs` |
| `SetAsidePile` | 从手牌"搁置"待用、未打出 | 放下序，index 0 等最久 | `:170-171` |
| （"保留"） | **无独立 retain 区** —— 保留是**行为**：`RetainHandTag` 抑制回合结束弃手（`C:Cards\CardTurnLifecycleEventHandlers.cs:48-55`），`standard.retained_card` 标记让**单张**卡留在手（`C:StandardCombatIds.cs:95-100`） | — | — |

不变量：① 每张 `CardInstance` 恰好在一个区，`Zone` 字段与所在 List 必须一致，`MoveCardToZone` 先按 `card.Zone` 从旧区移除，找不到就抛（`:331-338`）。② `AddCard` 用 `ContainsCard(card.Id)` 去重（`:182-190`），而 `ContainsCard` 是**对 `AllCards` 的线性扫描**（`:173-205`）⇒ 每次抽/移牌 O(总牌数)；⚠ 重写必须换成 owner 索引表。③ `AllCards` 拼接序：draw → hand → discard → exhaust → banished → queue → setAside（`:173-180`）。④ 洗牌入参是**下标双射**（`MoveDiscardPileToDrawPile` `:260-297`、`ReorderDrawPile` `:302-323`）。⑤ 卡级可变标记挂在实例上（不是定义上）：`Marks`/`MarkCounters`/`MarkSourceCombatantId?`/`QueuedTargetId?`（`:53-149`）；保留计数器 id：`standard.card_output_scale_num/den`、`standard.card_cost_delta`（`C:StandardCombatIds.cs:85-93`）。

### 2.5 资源（能量）的表示

- 资源 = `CombatantState._resources: Dictionary<ResourceId, ValuePoolState>`，**能量只是其中一个普通池**：`EnergyResource = "standard.energy"`（`C:StandardCombatIds.cs:11`）。
- `ValuePoolState`（`C:CombatPrimitives.cs:141-211`）：`Current ≥0`、`Max int? ≥0`（null=无上限）、`CanExceedMax bool`。
- **故意超标（overfill）是合法状态**：`SetCurrent(v, allowExceedingMax:true)` 只在"**抬高**到超过上限"时拒绝；**降低**一个已超标的池永远允许（`:182-200` 的长注释 —— 由 Act-V "未花完的带进明天"法令打出来的 bug 修复）。
- 标准回合开始补满：`RefillResourceOnTurnStartedHandler(EnergyResource, defaultMax: 3)`（`C:StandardCombatPackage.cs:124`），注册在 turn-start 触发器**之前**。
- 四条原生请求：`RefillResourceEffectRequest` / `GainResourceEffectRequest` / `LoseResourceEffectRequest` / `ModifyResourceEffectRequest`（`C:Resources\ResourceEffects.cs:31,123,270,338`）。语义差异**可观察**（不同事件、不同日志类型）：refill **创建**缺失池并置 max；gain 夹到 `Max`（`CanExceedMax` 例外）；lose 地板 0；modify 依次夹 `[Min, Max, pool.Max, 0]`。

### 2.6 防御池

`_defensivePools: Dictionary<DefensivePoolId, ValuePoolState>`；标准 Block = `"standard.block"`，定义 `DefensivePoolDefinition(AbsorbPriority: 0, ClearsOnOwnerTurnStart: true)`（`C:StandardCombatPackage.cs:52-55`）。吸收顺序在 Build 时**预排序**为 `(AbsorbPriority, Id 序数)`（`C:CombatDefinitionRegistry.cs:68-71`）。

## 3. 回合状态机

### 3.1 轮转模式（默认 `SimultaneousTeamTurns == false`）

```
State: TurnPhase ∈ {WaitingToStartTurn, TurnInProgress}

StartCurrentTurn:                                    # C:CombatTurnProcessor.cs:7-38
  assert Result==Ongoing                             #   :120-125
  assert TurnOrder 非空 且 Active 存在且在 TurnOrder 内  #   :139-168
  assert Active.IsAlive                              #   :127-137
  TurnPhase <- TurnInProgress                        # C:CombatState.cs:324-330（重复则抛）
  trace + log("TurnStarted")
  EnqueueEvent(TurnStartedCombatEvent(active, round, turn))   # ← 入队，不是同步调用
  ResolvePendingQueues()                             # 事件处理器在此跑：见下表

EndCurrentTurn:                                      #   :40-99
  assert Result==Ongoing
  MarkTurnEnded()                                    # 必须 TurnInProgress 否则抛（C:CombatState.cs:332-338）
  trace + log("TurnEnded"); EnqueueEvent(TurnEndedCombatEvent(...))
  ResolvePendingQueues()                             # ① 消化 TurnEnded
  if Result != Ongoing: return                       # ② 战斗在回合结束时结束 ⇒ 不推进
  AdvanceToNextCombatant()                           # ③
  ResolvePendingQueues()                             # ④ 消化 RoundEnded/RoundStarted
  while Result==Ongoing && !Active.IsAlive && guard++ <= TurnOrder.Count:   # ⑤ 跳过被④打死的
      AdvanceToNextCombatant(); ResolvePendingQueues()

EndCurrentTurnAndStartNextTurn:  EndCurrentTurn(); if Ongoing: StartCurrentTurn()   #   :101-118

AdvanceToNextCombatant:                              #   :170-212
  cur = index(Active) in TurnOrder
  for off in 1..TurnOrder.Count:
      nxt = (cur+off) mod TurnOrder.Count
      if !TurnOrder[nxt].IsAlive: continue
      if nxt <= cur:                                 # 绕回 ⇒ 新一轮
          EnqueueEvent(RoundEndedCombatEvent(CurrentRound, ActiveCombatantId))
          AdvanceRound()                             # CurrentRound++; CurrentTurn=1;
                                                     # 两个 Mark 都做（round + turn），再移除**已到期**的
          EnqueueEvent(RoundStartedCombatEvent(CurrentRound))
      else:
          AdvanceTurn()                              # CurrentTurn++;
                                                     # 只做 MarkExpiredIfPastTurn，再移除**已到期**的
      SetActiveCombatant(nxt); return
  throw "no living combatants in the turn order"
```

⚠️ **订正（2026-10-17）**：这两行原写作"清临时规则"，**是错的**。参考实现
（`C:CombatState.cs:572-592` + `C:TemporaryTriggeredProgram.cs:130-145`）只移除**已经到期**的规则：

```
AdvanceTurn:   CurrentTurn++；
               每条规则 MarkExpiredIfPastTurn(CurrentRound, CurrentTurn)；
               RemoveExpiredTemporaryTriggeredPrograms()
AdvanceRound:  CurrentRound++; CurrentTurn = 1；
               每条规则 MarkExpiredIfPastRound(CurrentRound)；
               每条规则 MarkExpiredIfPastTurn(CurrentRound, CurrentTurn)；   ← 两个都做
               RemoveExpiredTemporaryTriggeredPrograms()

MarkExpiredIfPastRound(r):  expires_after_round = Some(n) 且 r > n            ⇒ 到期
MarkExpiredIfPastTurn(r, t): expires_after_turn = Some(n) 且
                             ( r > (expires_after_round ?? r) || (同轮且 t > n) )  ⇒ 到期
```

三条后果，**都会被 `tr=` 行看见**（它是哈希可见的），所以都不是风格问题：

1. **没有到期字段的规则会活过回合和轮次边界** —— 不是"清空"；
2. **只按轮到期的规则在回合边界不消失**（`AdvanceTurn` 不做 `MarkExpiredIfPastRound`）；
3. **没有 `expires_after_round` 的 `expires_after_turn = N` 规则，绕到下一轮时也不消失** ——
   因为到期轮默认取**当前轮**，跨轮之后 `r > r` 为假、`t > N` 也要本轮内才成立。

内核对应实现：`CombatState::expire_temporary_rules_at_turn_boundary` /
`..._at_round_boundary`（**调用前必须已完成自增**），由 `turn.rs` 在两个推进分支里调用。
`clear_temporary_rules()` 仍存在，但**回合/轮次边界不该再用它**。

**`TurnStartedCombatEvent` 的标准处理器顺序**（= 注册序，`C:StandardCombatPackage.cs:121-139`）—— 这就是"一个回合从开始到结束的完整阶段序列"：

| # | 处理器 | 做什么 | 锚点 |
|---|---|---|---|
| 1 | `ResetCardPlayTurnStatsOnTurnStartedHandler` | 清"本回合"统计（先把上一回合快照成 last-turn） | `C:Cards\CardPlayTurnStats.cs:296-309` |
| 2 | `RefillResourceOnTurnStartedHandler(energy, 3)` | 补能量（**在触发器之前**） | `C:Resources\ResourceTurnLifecycleEventHandlers.cs:3` |
| 3 | `ActivatePendingStatusesOnTurnStartedHandler` | pending 状态 `PendingTurns--`，到 0 转正 | `C:Effects\StatusEffects.cs:409` |
| 4 | `TriggeredProgramContextAdapters.TurnStarted.CreateHandler()` | 全部 turn-start 触发程序（按 `(priority,id)` 序） | `C:Effects\TriggeredProgramDefinition.cs:78` |
| 5 | `ResolveQueueOnTurnStartedHandler` | **解析队列：`ResolveOldest(owner, int.MaxValue)`** | `C:Cards\QueueResolution.cs:133-137` |
| 6 | `DrawCardsOnTurnStartedHandler(5)` | 抽牌（受 `TurnStartDraw` 修饰流水线 + `MaxHandSize` 法令夹） | `C:Cards\CardTurnLifecycleEventHandlers.cs:3-37` |
| 7 | `ClearBlockOnTurnStartedHandler` | 清"回合开始清空"的防御池（Block） | `C:Effects\DefensivePoolEffects.cs:283-322` |
| — | `DamageOverTimeOnTurnStartedHandler` | DoT 结算 | `C:StandardCombatPackage.cs:139` |

**`TurnEndedCombatEvent` 顺序**（`:135-138`）：`CardLifecycleTurnEndInHandHandler` → `DiscardHandOnTurnEndedHandler`（被 `RetainHandTag` 抑制）→ 触发程序 → `DecreaseTimedStatusDurationsOnTurnEndedHandler`。

**设计关键顺序**（`C:StandardCombatPackage.cs:122-133` 注释）：补能量 → 触发器 → **队列** → 抽牌 → 清 Block。队列卡的效果"一定发生在手牌到来之前"；清 Block 在队列解析之前，所以队列里的 `gainBlock` 能活到它被排队的那一回合（`S:QueueTortureTests.cs:210-212` 断言 11 点 Block 存活）。

### 3.2 同时队伍回合模式（`SimultaneousTeamTurns == true`）

```
StartTeamPhase(team):                          # C:SimultaneousTurnProcessor.cs:14-30
  assert Ongoing; BeginTeamPhase(team)         # CurrentPhaseTeam=team; _endedThisPhase.Clear()  (C:CombatState.cs:295-299)
  for member in 该队存活成员.ToArray():          # ⚠ 先物化，否则解析中召唤会改变遍历
      SetActiveCombatant(member)
      trace+log("TurnStarted"); EnqueueEvent(TurnStartedCombatEvent(member,...))
      ResolvePendingQueues()                   # 每个成员各跑完整 turn-start 序列
      if Result != Ongoing: return

EndMemberTurn(memberId):                       #   :34-54
  assert 有活跃阶段 且 member.TeamId == CurrentPhaseTeam
  if HasMemberEnded(memberId): return          # 幂等
  SetActiveCombatant(memberId); TurnEnded 事件; ResolvePendingQueues(); MarkMemberEnded(memberId)

AdvanceToNextTeamPhase():                      #   :61-98
  teams = 按 TurnOrder 首次出现序去重的 TeamId 列表        #   :100-108
  若绕回: EnqueueEvent(RoundEnded); AdvanceRound(); EnqueueEvent(RoundStarted); ResolvePendingQueues(); if !Ongoing return
  否则:   AdvanceTurn()
  StartTeamPhase(next)
```

⚠ 同时模式**不用** `TurnPhase`；且 `CurrentPhaseTeam` / `_endedThisPhase` **不入快照、不入哈希**（§5.4）。

### 3.3 法令（Decrees）的角色

法令 = "改变**规则**而不是数值"的状态（`C:CombatDecrees.cs:5-51`）。7 条：`MaxCardsPerTurn` / `NoLikenessInSuccession` / `NthCardOfTurnIsFree` / `MinimumCardCost` / `UnspentResourceCarries` / `PlayedCardsExhaust` / `MaxHandSize`。载体 `CombatRuleSpec(Rule, Amount, Tags?, Resource?)`（`:57-66`），挂在 `StatusDefinition.CombatRules` 上，"谁戴谁受约束" —— **没有全局规则表**（`:14-18`）。

【必须】保留的读取语义：① 收集顺序稳定 —— 按 `(statusId 序数, specIndex)` 排序；② 重复法令**不互相放松** —— `Ceiling` 取 `Min`，`Floor` 取 `Max`（`:70-125`）；③ 三个读取点：`DecreeCardPlayValidator`（Priority **150**，出牌前拒绝，`IsAction` 卡不受约束，`:131-176`）、`DecreeCardCostModifier`（Priority **300**，第 N 张免费，只降不升，`:181-203`）、`MinimumCardCost` **不作 cost modifier** 而在 `CalculateCosts` 末尾兜底（它要能给"印刷费用为 0 因而根本没有 cost 条目"的卡**凭空造一个**费用，`C:Cards\CardPlay.cs:495-507`）；④ `UnspentResourceCarries` 作用在 refill：`refillTarget = (Max ?? DefaultMax) + Current`，以 `allowExceedingMax: true` 写入（`C:Resources\ResourceEffects.cs:84-96`）；⑤ `PlayedCardsExhaust` 覆盖卡定义落点（`C:Cards\CardPlay.cs:298-302`）；⑥ `MaxHandSize` 在抽牌入口裁剪 `wanted`（`C:Effects\CardZoneEffects.cs:30-46`）。

### 3.4 玩家输入：何时被接受、何时被拒绝

**接受路径唯一**：`CombatReplayRunner.Apply(command)`（`C:CombatReplayRunner.cs:13-60`）。**自动起手**：若 `TurnPhase == WaitingToStartTurn`，`PlayCardCommand` / `EndTurnCommand` / `ExecuteEnemyActionCommand` 到达时**先自动 `StartCurrentTurn`**（`:74-81`）。

| 命令 | 行为 | 锚点 |
|---|---|---|
| `PlayCardCommand(Source, CardInstanceId, Target?)` | 入队 `PlayCardEffectRequest` → `ResolvePendingQueues` | `:29-36` |
| `EndTurnCommand(CombatantId)` | `EndCurrentTurnAndStartNextTurn` | `:38-41` |
| `ExecuteEnemyActionCommand(Actor, ActionId, Target?)` | 入队 `ExecuteEnemyActionEffectRequest` | `:43-50` |
| `SelectTargetCommand` | **空实现（TODO）**，直接丢弃 | `:52-54` |
| 其它 | 抛 `InvalidOperationException("Unknown command type")` | `:56-58` |

命令数值词汇见 `C:CombatCommands.cs:9-31`。

**拒绝规则（分层，越靠前越早拒绝）**：① `Result != Ongoing` ⇒ 抛（`C:Cards\CardPlay.cs:82-86`、`C:CombatTurnProcessor.cs:120-125`）。② `TurnPhase` 不匹配 ⇒ `MarkTurnStarted`/`MarkTurnEnded` 抛（`C:CombatState.cs:324-338`）；**Start 不能连调两次**（`T:CombatTurnProcessorTests.cs:26-36`）；**未 Start 就 End 抛**（`T:CombatTurnProcessorTests.cs:39-47`）。③ `!source.IsAlive` ⇒ 抛（`CardPlay.cs:90-94`）。④ 校验器链（按 `(Priority, ModifierId)` 序，`C:CombatDefinitionRegistryBuilder.cs:584-592`）：`UnplayableCardPlayValidator`(200) / `OneAttackPerTurnCardPlayValidator`(200) / `PlayConditionCardPlayValidator`(150) / `DecreeCardPlayValidator`(150) / `StunCardPlayValidator`(100)（`C:StandardCombatPackage.cs:59-63`）—— **校验器以"抛异常"表示拒绝**（`C:Cards\CardPlayValidators.cs:11-18`）。⑤ 费用不足 / 资源缺失 ⇒ `EnsureCostsCanBePaid` 抛，**且在效果入队之前**（`CardPlay.cs:122-126`、`:514-533`）。⑥ `ICombatCardChooser`/`ICombatOptionChooser` 缺席时的确定性兜底 = 取第一个候选（`C:Cards\CardZones.cs:35-51`）。

⑦ **两条表面（surface）语义不同**（【必须】保留）：直接处理器路径 `CombatCardPlayProcessor.PlayCardInstance` 拒绝 = **抛**（`:45-68`）；效果请求路径 `PlayCardEffectRequest` 拒绝 = **静默 no-op + `WasPlayed=false`**，卡留手里、战斗继续（`C:Cards\CardPlay.cs:356-382` 的 `IsCardPlayAllowed` 用 `catch (InvalidOperationException) { return false; }`）。前端要"把不可出的牌画成不可出"就调这个公开 API（`:363-365`）。

## 4. 效果队列算法

### 4.1 三队列 + 三个平行元数据队列

- 效果：`_pendingEffects: Queue<IEffectRequest>` + `_pendingEffectChains: Queue<CombatEffectChainContext>` + `_pendingEffectOwners: Queue<EffectProgramExecutionId?>`（`C:CombatState.cs:5-7`）。
- 事件：`_pendingEvents: Queue<ICombatEvent>` + `_pendingEventChains`（`:8-9`）。
- 续延：`_pendingContinuations: Queue<Action<CombatState>>`（`:10`）。

**入队**：`EnqueueEffect(request)` 取 `CurrentEffectChain ?? CreateRootEffectChain()`（`:382-407`）；`EnqueueEvent` 同理（`:442-463`）。两个内部重载都额外记录"入队时正在跑的程序帧 id"，用于把 handler 抛出的异常绑回拥有者（`:404-406`）。
**出队**：`DequeueNextEffectEntry()` **先校验三队列等长**，不等长抛 `"Pending effect requests and their effect-chain metadata are out of sync."`（`:429-440`、`:557-563`）；事件同理（`:565-570`）。
**优先级**：**队列本身没有优先级，严格 FIFO**。优先级只存在于两处：(a) 事件**处理器**注册序（§3.1 表）；(b) 触发程序按 `(Priority, Id 序数)` 排序（`C:Effects\TriggeredProgramDefinition.cs:88-106`）。

### 4.2 排空主循环（`CombatQueueProcessor.ResolvePendingQueues`，`C:CombatEventHandling.cs:81-115`）

```
ResolvePendingQueues(combat, registry, limits?):
  combat.DefinitionRegistry = registry                 # 供表达式读定义数据
  limits ??= CombatExecutionLimits.Default             # {1024, 1024, 1024}  C:CombatExecutionLimits.cs:11-14
  cycles = 0
  while (HasPendingEffects || HasPendingEvents || HasPendingContinuations) && Result == Ongoing:
      if cycles >= limits.MaxQueueCycles(1024):
          throw "Stopped resolving pending queues after reaching the limit of 1024 cycles." + WhatIsLooping()
      ResolvePendingEffects(...)                       # 先抽干"效果"
      ResolvePendingEvents(...)                        # 再抽干"事件"
      if 效果队列空 && 事件队列空 && TryDequeueContinuation(out c): c(combat)   # 最后跑一个续延
      cycles++
```

【必须】：① 效果在事件**之前**跑完 ⇒"先生效后广播"；`T:CombatQueueProcessorTests.cs:57-80` 断言日志序 `[BlockGained, TestEventHandled]`。② 续延**只在两个队列都空**时执行，且**一次循环只执行一个**（不是 while）⇒ 续延看到的是静态队列。③ 循环条件含 `Result == Ongoing`：结果一旦终止，队列**立即停止排空**（残余效果被永久丢弃），活跃程序帧全部 `CancelDueToCombatEnd()`（`C:CombatState.cs:358-366`）。

### 4.3 效果子循环与执行预算（`C:CombatEffectQueueProcessor.cs:7-58`）

```
ResolvePendingEffects:                                  # 事件子循环同构，见 C:CombatEventHandling.cs:39-73
  combat.DefinitionRegistry = registry
  resolved = 0
  while HasPendingEffects && Result == Ongoing:
      if resolved >= limits.MaxEffectsPerCycle(1024): throw "…limit of 1024 effects per cycle."
      e = DequeueNextEffectEntry()
      try:
          using combat.EnterEffectChain(e.EffectChain):
              resolver.Resolve(combat, registry, e.Request)   # 按运行时类型取 handler（C:CombatEffectResolver.cs:14-16）
      catch ex:
          if e.OwningProgramExecutionId 有活跃帧 frame:
              frame.FaultDueToNativeHandler(ex); UnregisterActiveProgramFrame(frame)
          throw                                        # 异常继续向外传播
      combat.Trace(EffectResolvedTraceEvent(...)); resolved++
```

| 预算 | 默认 | 超限行为 | 锚点 |
|---|---|---|---|
| `MaxQueueCycles` | **1024** | 抛 + 报告队首 6 个效果/事件与末 10 条日志 | `C:CombatExecutionLimits.cs:12`、`C:CombatEventHandling.cs:99-102,121-144` |
| `MaxEffectsPerCycle` | **1024** | 抛 | `:13`、`C:CombatEffectQueueProcessor.cs:24-26` |
| `MaxEventsPerCycle` | **1024** | 抛 | `:14`、`C:CombatEventHandling.cs:53-55` |
| `MaximumTriggerDepth` | **64** | 抛（**在过滤器之前**） | `C:CombatEffectChain.cs:10`、`:64-72` |
| `EffectProgram.MaxProgramSteps` | 每程序自带 | 抛 | `C:Effects\Programs\EffectProgramExecution.cs:109-114` |

三者都必须 > 0，否则构造抛 `ArgumentOutOfRangeException`（`C:CombatExecutionLimits.cs:16-29`，测试 `T:CombatExecutionLimitsTests.cs:30-61`）。

### 4.4 链（Chain）与队列（Queue）的关系

- **链是"谁引起的"的路径**，随队列条目一起旅行：入队时把 `CurrentEffectChain` 快照进平行元数据队列，出队时用 `using combat.EnterEffectChain(entry.EffectChain)` 恢复为当前链（`C:CombatState.cs:500-511`）。
- `CombatEffectChainContext`（`C:CombatEffectChain.cs:8-84`）= `{Id, MaximumTriggerDepth, IReadOnlyList<TriggeredEffectDefinitionId> TriggeredEffectDefinitionIds}`；`TriggerDepth == 那个 list 的 Count`（`:16`）。
- **链是不可变单链表**：`AppendTriggeredEffectDefinition` 返回**新** context（`:74-83`），原链不动。根链 `CreateRootEffectChain()` 分配新 `Id`（`_nextEffectChainNumber++`），深度 0（`:545-555`）。`EnqueueEffect`/`EnqueueEvent` 在无当前链时**各造一条新根链**。触发进入用 `CreateTriggeredEffectChain(id)` = `parentChain.AppendTriggeredEffectDefinition(id)`（`:492-498`）。
- `EnterEffectChain` 返回 `IDisposable`，`Dispose` 恢复**外层**链；退出后 `CurrentEffectChain == null`（`T:CombatEffectChainDepthLimitTests.cs:46` 断言）。

**重入保护（两道闸门，顺序不可交换 —— 有源码级测试锁死）**：① **重入抑制** `CanEnterTriggeredEffectDefinition(def)`：`SuppressRecursiveReentry`（默认，枚举值 0）⇒ `!链里已含该 definitionId`；`AllowRecursiveReentry` ⇒ 永远 true；未知策略抛（`C:CombatEffectChain.cs:49-62`、`C:Effects\TriggeredEffects.cs:8-12,23-24`）。② **深度上限** `EnsureCanAppendTriggeredEffectDefinition`：`TriggerDepth < MaximumTriggerDepth` 才放行，否则抛（`:64-72`）。

执行顺序（`C:Effects\TriggeredProgramDefinition.cs:114-161`）：**重入检查 → 深度检查 → GatingStatus 快速跳过 → 构造 context → 过滤器 → 执行**。顺序由 `T:CombatEffectReentryPolicyTests.cs:163-233` 与 `T:CombatEffectChainDepthLimitTests.cs:189-278` 用 `IndexOf` 位置断言硬锁。语义后果：**递归抑制优先于深度上限** —— 同一定义第 64 层的自我重入会被"已经进过"挡掉，而不是撞深度墙（`T:CombatEffectChainDepthLimitTests.cs:138-187`）。**同名触发器在兄弟事件上可以各自触发**（链是每条事件各自 append，不是全局集合）：`T:CombatEffectReentryPolicyTests.cs:58-113` 断言 2 次激活。

### 4.5 队列被修改时的迭代安全策略 ⚠

**核心结论：内核从不在迭代队列的同时修改它。** 四个手法：

1. **同步 while + 每轮重读 `Count`**：入队使循环继续、出队使循环前进（`C:CombatEffectQueueProcessor.cs:22`）。
2. **平行队列一起出队**，先做长度断言（`C:CombatState.cs:557-570`）—— 用"结构不一致就炸"代替迭代器失效检测。
3. **遍历集合前一律 `.ToArray()`/`.ToList()` 物化**（全仓库惯例）：`C:CombatTurnProcessor.cs:363`、`C:CombatState.cs:654-660`（"物化以免受后续安装/剪枝影响"）、`C:SimultaneousTurnProcessor.cs:22`、`C:Cards\QueueResolution.cs:29-33`。`TemporaryRuleTests` / `S:QueueTortureTests` 就是靠这条撑住"解析中安装/移除临时规则"。
4. **`QueueResolution` 两段式**：先**快照**要解析的卡 id 列表（`Queue.Where(!IsResolvingQueuedCard).Take(count).ToList()`，`C:Cards\QueueResolution.cs:29-33`），再**逐个串行**解析；每张卡开始前**重新校验** `ContainsCard && Zone==QueuePile && !IsResolvingQueuedCard`，不满足就跳过（`:51-56`）。递归通过 `onTerminal` 续延而非栈（`:109`）⇒ 窗口期内被排队的卡**必须等下一个窗口**（`:10-13` 注释）。自我保护：`_resolvingQueuedCards` 阻止"卡在跑时又被当候选"（`C:CombatState.cs:134-148`）—— 否则 Night Docket 类卡无限自递归（`:135-139` 注释明说这是 stack overflow）。⚠ 只有 `Completed` 才继续下一张，`Faulted` 直接 return（`:100-107`）—— 否则会出现两个未回答的提问并存。

**⚠ 一个真实的迭代安全缺口（重写时顺手修）**：`ClearBlockOnTurnStartedHandler` 直接 `foreach (var poolDef in registry.DefensivePoolDefinitions.Values)` 入队清理请求（`C:Effects\DefensivePoolEffects.cs:301`）。`DefensivePoolDefinitions` 是 `ImmutableDictionary`，遍历序 = 哈希桶序；key 是包着 `string` 的 record struct，**.NET 的 string 哈希每进程随机化** ⇒ 当**多于一个**池选择 `ClearsOnOwnerTurnStart` 时，入队顺序跨进程不稳定。目前只有 Block 一个池所以没炸，但这是内核里唯一一处"集合遍历序影响队列顺序"的地方。重写应改为按 `(AbsorbPriority, Id)` 排序后入队，并把该改正记为**有意偏离**。

## 5. 确定性与快照

### 5.1 随机数生成器（`C:CombatRandom.cs`，全文 57 行，无状态静态类）

```
初始: state = (uint)randomSeed ^ ((uint)randomStep * 0x9E3779B9u) ^ 0xA5A5A5A5u
      state == 0 ? 0x6D2B79F5u : state                                   # :29-42
下一步: state += 0x9E3779B9u                                             # :44-56
      z = state; z = (z ^ (z>>16)) * 0x85EBCA6Bu; z = (z ^ (z>>13)) * 0xC2B2AE35u
      return z ^ (z>>16)
洗牌: indexes = 0..count-1                                               # :5-27
      for i = count-1 downto 1:
          j = (int)(next() % (uint)(i+1)); swap(indexes[i], indexes[j])
      count <= 1 ⇒ 原样返回，不消耗随机数
```

这是 **SplitMix64 的 32 位变体**（`0x9E3779B9` 黄金比增量 + 两轮 xor-shift-multiply 终结器）。
**状态只有 4 字节**（`uint`），且**它不是被保存的** —— 每次调用都从 `(RandomSeed, RandomStep)` 重新派生（`:18`）。所以**持久化的 RNG 状态 = 8 字节**（两个 `int32`）。
**流分离方式 = 单调递增的 `randomStep`**（`CombatState.AdvanceRandomStep()`，`C:CombatState.cs:675-678`）。**没有多流**（不分战斗流/奖励流），只有一条全局计数器。

| 场景 | 调用 | 一次性抽一个的用法 | 锚点 |
|---|---|---|---|
| 弃牌堆洗回抽牌堆 | `CreateShuffledIndexes(discard.Count, seed, step)` 后 `step++` | 全排列 | `C:Effects\CardZoneEffects.cs:62-69` |
| 开局抽牌堆洗牌 | 同上 | 全排列 | `ScenarioCombatFactory.cs:86-88` |
| 随机选一个资源 / 状态 | `CreateShuffledIndexes(n, seed, step)[0]` | ⚠ **仍跑完 n-1 次迭代** | `C:Effects\ResourceSelection.cs:64-65`、`StatusSelection.cs:87-88` |
| 随机目标 / roll / 手牌 | 同上 | ⚠ 同上 | `C:Effects\Programs\EffectProgramExpressions.cs:1928-1929,1952-1953,2049-2050` |
| 随机洗牌型节点 | 全排列 + trace `RandomStepUsed` | 全排列 | `C:Effects\Programs\EffectProgramNodeExecutors.cs:526-548` |

⚠ **重写铁律**：抽单个元素 = `[0]`，但**必须完整执行整趟 Fisher–Yates**，因为 `indexes[0]` 的最终值是整条随机序列的结果，且 `AdvanceRandomStep()` 只 +1（不是 n）。任何"提前 break 的优化"都会破坏比特一致。

### 5.2 快照包含什么（`C:CombatStateSnapshot.cs:115-148`、`CombatStateSnapshotter.cs`）

| 快照字段 | 来源 | 排序键 | 哈希 | 锚点 |
|---|---|---|---|---|
| `Id` / `RandomSeed` / `RandomStep` | 直取 | — | ✅ | `Snapshotter.cs:43-45` |
| `Result` / `CurrentRound` / `CurrentTurn` / `TurnPhase` / `ActiveCombatantId` | 直取 | — | ✅ | `:46-50` |
| `TurnOrder` | `List` 原序 | 原序 | ✅ | `:51` |
| `Combatants[]` | **按 `TurnOrder` 遍历** | TurnOrder | ✅ | `:12-14` |
| └ `Resources` / `DefensivePools` | 字典 | `OrderBy(key.value, Ordinal)` | ✅ | `:81-88` |
| └ `Statuses` | **`AllStatuses`（含 pending）** | 实例列表序 | ✅（不含 Tags/Counters） | `:89-90` |
| └ `Tags` / `Counters` | HashSet / 字典 | `OrderBy(value/key, Ordinal)` | ✅（Tags 实际恒空） | `:91-97` |
| `GlobalStatuses[]` | List 原序 | 原序 | ✅ | `:21-23` |
| `CardZones[]`（7 区各自 `ImmutableArray<CardInstanceSnapshot>`） | **按 `TurnOrder`**；区内保持 List 原序 | TurnOrder | ✅ | `:16-19`、`:122-130` |
| └ 卡内 `Marks` / `MarkCounters` | HashSet / 字典 | `OrderBy(value/key, Ordinal)` | ✅ | `:132-145` |
| `NextStatusInstanceNumber` / `NextCardInstanceNumber` / `NextSummonedCombatantNumber` | 直取 | — | 前两个 ✅ / **召唤号 ❌** | `:55-57` |
| `NextEffectChainNumber` / `NextProgramExecutionId` | 直取 | — | ✅ | `:58-59` |
| `TemporaryRules[]` | List | `OrderBy(Id, Ordinal)` | ✅ | `:26-40` |
| `CardPlayTurnStats[]` | 按 TurnOrder | TurnOrder；内部按 key 序数 | **❌ 不入哈希** | `:62-64` |
| `TriggerActivity[]` | 字典 | `OrderBy(key.value, Ordinal)` | **❌ 不入哈希** | `:65-70` |

**不入快照的**（同样重要）：三队列 + 续延队列 + `_activeProgramFrames`（`C:CombatState.cs:718-723`）、整个 `CombatLog`（`:175-179`）、`_actionScopes`（`:94-95`）、`_resolvingQueuedCards`、`_endedThisPhase`、`CurrentPhaseTeam`、`SimultaneousTeamTurns`、`CellExclusive`、`DefinitionRegistry`；战员的 `DisplayNameKey` / `OwnerId` / `ControllerId` / `Position` / `IntentKey`；状态的 `Tags` / `Counters` / `Visibility`（`Visibility` 实际在 `StatusInstanceSnapshot` 里，但哈希器不写它）。

⚠ **快照里绝不能是 ValueTuple** —— `System.Text.Json` 只序列化属性，ValueTuple 的 `Item1/Item2` 是字段，会静默写成 `{}`，导致存档丢能量/丢牌区（`C:CombatStateSnapshot.cs:8-20` 的长注释 + `:150-159`）。沿用 JSON 存档时这条依然成立。

### 5.3 哈希算法（`C:CombatStateHasher.cs`）

`text` = 规范化的 `key=value\n` 文本（固定字段顺序；集合按快照里已有顺序）→ `UTF8(text)` → **`SHA256`** → 小写十六进制（`:16-24`）。

- 分隔符统一 `'\n'`（LF，**不是** `Environment.NewLine` —— 关键：`AppendLine` 只在诊断渲染器里用）。
- 集合元素以 `,` 结尾（`:41-44`、`:99-102`），空集合留下一个空行。
- 整数用 `StringBuilder.Append(int/long)`；可选值用 `?.ToString() ?? "null"/"inf"/"none"`（`:64-66`、`:85-90`）。枚举一律 `(int)`（`:31,34,79,115`）。
- **刻意跳过**：状态实例的 `Tags`/`Counters`/`SourceCombatantId`/`SourceCardId`/`AppliedRound`/`AppliedTurn`/`Visibility`（`AppendStatus` 只写 `id def stk dur chg pol [pend]`，`:108-119`）；卡的 `Zone`（区名本身即 key）；`QueuePile`/`SetAsidePile` **为空时整段省略**，以保证"加了这两个区之后旧哈希不变"（`:128-135`）。
- 结果 64 hex 字符（测试 `T:CombatSnapshotTests.cs:161-169`）。

### 5.4 跨机器/跨语言比特一致：判断与依据

**结论：可以做到比特一致（SHA-256 十六进制字符串完全相同），但有 5 条约束，其中 2 条需要改数据或改行为。**

| # | 风险 | 现状 | 判定 |
|---|---|---|---|
| 1 | **浮点** | 全部 Combat 目录里唯一的 `double` 是 `PositionalTargetSelectors.ForwardSign` 的两次 `.Average()`（`C:Effects\PositionalTargetSelectors.cs:43-49`），最终只取 `Math.Sign` | ⚠ **必须改**：ESP32-P4 只有单精度 FPU，用 `float` 重实现会在"两队均深几乎相等"时翻转符号。改用**整数叉积**判定 `sign(sumEnemy*countSrc - sumSrc*countEnemy)`，但只能"多数情况下"等价 —— 需要用对拍测试确认该分支在语料上永不触发符号差别。位置系统本身 opt-in（`C:CombatPrimitives.cs:55-59`），第一版可以先不实现 |
| 2 | **文化相关格式化** | 哈希器用 `StringBuilder.Append(int)` → 内部 `int.ToString()` 用 `NumberFormatInfo.CurrentInfo`；id 用 `$"card_{n:000000}"`（`D6`） | ⚠ 现状在 `InvariantCulture`/`zh-CN`/`en-US` 下都对（纯 ASCII 数字），但**重写必须显式固定为"ASCII 十进制 + 负号 `-`"**，不要依赖默认 |
| 3 | **字典/集合遍历顺序** | 快照器**全部显式排序**（`StringComparer.Ordinal`）；哈希器只按快照给定顺序写 | ✅ 重写侧同样排序即可。**唯一缺口**：`C:Effects\DefensivePoolEffects.cs:301`（§4.5）。.NET string 哈希每进程随机化 ⇒ 多池清理时队列顺序不稳 ⇒ 重写应排序，记为有意改正 |
| 4 | **序数比较 = UTF-16 code unit 序** | 所有排序用 `StringComparer.Ordinal` | ✅ 只要 **id 全为 ASCII**（实测全部是：`standard.strike`、`card_000001`、`test.zap`…），UTF-16 序数序 ≡ UTF-8 字节序 ⇒ C 的 `strcmp` 直接等价。**约束：内容 id 必须 ASCII-only**（出现 U+10000 以上字符时两者分叉） |
| 5 | **哈希覆盖面不完整** | 见下表 | ⚠ **规范必须逐字复制这个"子集"定义**，而不是"哈希所有状态" |

**哈希不覆盖但快照覆盖的字段**（⇒ 用哈希对拍会漏检）：

| 漏检项 | 后果 | 锚点 |
|---|---|---|
| `NextSummonedCombatantNumber` | 召唤物 id 发号器分叉，哈希看不出来 | 快照 `:57`；哈希器 `:36-39` 无此项 |
| `CardPlayTurnStats` 整块（本回合/上回合出牌数、按定义/标签计数、draws、damage、hits、gained、spent、claims、整场出牌表） | "超过上一回合""又以 Attack 开场""本回合第三张"这类规则在还原后全部读 0，而哈希**不会**报错（`C:Cards\CardPlayTurnStats.cs:196-202` 记录了这个真实事故） | 快照 `:139`；哈希器无此项 |
| `TriggerActivity` | 宿主展示用的"某规则触发多少次"，还原后重新计数 | 快照 `:147`；哈希器无此项 |
| `CurrentPhaseTeam` / `_endedThisPhase` | **快照和哈希里都没有** ⇒ 同时队伍模式的中途存档无法忠实还原 | `C:CombatState.cs:47-50` |
| 状态 `Tags`/`Counters`、战员 `Position`/`IntentKey` | 位姿/标记变化不可见 | `C:CombatStateHasher.cs:108-119` |

**给重写的规格建议**：把哈希定义成两个等级 —— **(a) `hash_golden`** = 现有 SHA-256/规范文本的**逐字节等价物**（与 C# 对拍、兼容旧存档）；**(b) `hash_full`** = 覆盖全部快照字段的完整指纹（RL 训练的状态去重/缓存用，可换 xxHash/CRC 省算力）。两者都必须在接口上注明覆盖范围。另外：**SHA-256 在 RL 训练步频下太贵**，训练用 (b)，并考虑增量更新（每次状态变更更新 rolling hash）而非每步重算。

## 6. 宿主依赖清单 + 内存预算

### 6.1 依赖 .NET 需要重设计的东西

| 依赖 | 出现位置（代表性） | 重写方案 |
|---|---|---|
| **`Action<CombatState>` 续延** | `C:CombatState.cs:10`（`Queue<Action<CombatState>>`）、`:465-473`、`C:Cards\CardPlay.cs:217,292`（`EnqueueContinuation(c => CloseAction(c, actor))`）、`C:Cards\QueueResolution.cs:96-110`（递归续延）、`C:Effects\Programs\EffectProgramExecution.cs:11-13,49-58`（`onComplete`/`onTerminal`） | **最大的一处重设计。**需要显式 `Continuation` 结构体联合（tagged union）：`{CloseAction(actor) / PlaceCard(owner,card,zone,state) / ResolveQueueNext(owner, ids[], index)}` + 一个**定长**队列。捕捉变量（actor/cardId/destZone）进结构体字段。`QueueResolution.ResolveFrom` 的递归本为尾递归，改成循环 + 显式下标（`:109`） |
| **`Dictionary<…>` / `HashSet<…>`** | `C:CombatantState.cs:16-20`、`C:CombatState.cs:157-160,414`、`C:Cards\CardZones.cs:68-69`、`C:Cards\CardPlayTurnStats.cs:5-34`（**6 字典 + 3 HashSet**）、`C:CombatDefinitionRegistryBuilder.cs:16-30` | key 全是 `record struct(Value)` 包字符串 ⇒ 改 **u16 句柄 + 有序数组/开放寻址小表**。`CardPlayTurnStats` 的 9 个容器每战员一份，**是热路径主要分配源** |
| **`HashSet<string>`（Ordinal）** | `C:CombatState.cs:102`（`ActionScope.Claims`）、`C:Cards\CardPlayTurnStats.cs:29`（`_claimedThisTurn`） | 字符串 → **编译期算好的 u32 稳定哈希（FNV-1a 等）+ 小表**，或改成内容里预声明的 claim id 枚举 |
| **`System.Text.Json`** | `C:Serialization\CombatJson.cs`（整文件：`JsonConverter`/`JsonSerializerOptions`/`Utf8JsonReader`/`JsonTypeInfo`）、`CombatSaveJson.cs:12-23`、`C:CombatStateSnapshot.cs:145-146`（`[JsonIgnore]`） | 存档/内容加载是**宿主功能**，内核只暴露快照 POD。ESP32 侧用自有二进制格式；**但 `hash_golden` 的规范文本必须能逐字节产生** |
| **异常控制流** | ★ `C:Cards\CardPlay.cs:365-382`（`IsCardPlayAllowed` 用 `try/catch(InvalidOperationException)` 当返回值）、`C:Cards\CardPlayValidators.cs:11-18`（**接口契约即"抛=拒绝"**）、`C:Cards\CardPlay.cs:44-68`、`:514-533`、`C:CombatEffectQueueProcessor.cs:30-49`（catch→`FaultDueToNativeHandler`→rethrow）、`C:Effects\Programs\EffectProgramExecution.cs:107-159`（`catch (Exception ex) when (frame is {IsTerminal:false})`，用 `when` 保证只 fault 一次）、`C:Cards\QueueResolution.cs:100-107`（依赖 `Faulted` 终态） | 全面改为**返回值/结果枚举**：`PlayValidationResult { Ok, Unplayable, Stunned, PlayConditionFailed, DecreeRefused(rule), Unaffordable(resource,need,have) }`；`EffectResolveResult { Ok, Faulted(code) }`。ESP32 上 C++ 异常会带来 RTTI + 展开表 + 体积，且 `Faulted` 语义必须**显式建模**（它决定队列是否继续） |
| **LINQ** | `C:CombatState.cs:228,242,247,256,283,289,308,314,380,532`、`C:Cards\CardZones.cs:173-180`（`Concat×6 + ToArray`）、`C:Cards\CardPlayTurnStats.cs:207-219`、`C:CombatStateSnapshotter.cs:12-70`（几乎全 LINQ）、`C:Cards\CardZones.cs:240-258` | 全部展开为显式 `for` + 调用方拥有的 scratch buffer。尤其 `CardZones.ContainsCard/GetCard` 的线性扫描（`:192-205`）要换成 owner→card 索引 |
| **`string` 插值 / `ToString()` 日志** | `C:CombatState.cs:891`、`:682,691,703`（`$"card_{n:000000}"`）、`C:Cards\CardPlay.cs:340-352`、每一个异常消息 | 编译期开关：MCU 构建下把格式化推后到"确实要输出"；异常消息改错误码。**注意 id 字符串生成在 `CreateNextCardInstanceId` 里是必需行为（哈希/存档要用）** |
| **浮点** | 除 §5.4#1 那处外，Combat 目录**零浮点** | ✅ 好消息：核心玩法数值全 `int`/`long`，不需要定点化 |
| **`System.Security.Cryptography`** | `C:CombatStateHasher.cs:3,23`（`SHA256.HashData`）、`Convert.ToHexString(...).ToLowerInvariant()` | 自带 SHA-256（~1.5–2 KB 代码 + 96 B 状态），或训练路径换非加密哈希 |
| **`ImmutableArray` / `ImmutableDictionary`** | `C:CombatStateSnapshot.cs`、`C:CombatDefinitionRegistry.cs:12-32` | 只读数组 = `const` + 长度；`ImmutableDictionary` → 排序表 + 二分 |

### 6.2 一场战斗的常驻内存估算

**估算依据**：以规范文本（§5.3）长度作为"信息量下界"，以 C# 对象图（对象头 16B、字段引用另开堆对象、`Dictionary` 空表 ~80B+、`List` 空 ~32B+、`string` 每个 ~26+2n B）作为"现状上界"。取一场较重战斗：**4 名玩家 + 3 名敌人、共 200 张卡实例、约 20 个状态实例**。

| 内容 | 规范文本量 | 打包状态（重写目标） | C# 现状（估） |
|---|---|---|---|
| 战员 7 个 ×（id/def/team/hp/lc + 资源 + 池） | ~60 B/人 ⇒ 0.4 KB | 7 × 80 B ≈ **0.6 KB** | 7 × ~600 B ≈ 4 KB |
| 状态 20 个 | ~55 B/个 ⇒ 1.1 KB | 20 × 40 B ≈ **0.8 KB** | 20 × ~250 B ≈ 5 KB |
| 卡实例 200 张 | ~35–60 B/张 ⇒ **7–12 KB** | 200 × 24 B ≈ **4.8 KB** | 200 × ~180 B ≈ 36 KB |
| 牌区/字典/统计容器 | — | ~2 KB | 7 × ~1 KB ≈ 7 KB |
| 临时规则 + 触发活跃度 | 少量 | **< 0.5 KB** | ~1 KB |
| **小计（可变状态）** | **~10–15 KB** | **≈ 9 KB** | **≈ 55 KB** |
| ⚠ `CombatLog`（append-only，**无上限**） | ~60–150 B/条 | **必须环形缓冲（如 256 条 ≈ 32 KB）或 MCU 下编译掉** | 长战斗轻松 **数百 KB–MB** |
| ⚠ trace 流 `CombatTraceCollector` | 每条含修饰器步骤 | **默认关闭**（仅 `TraceListener != null` 时产生，`C:CombatState.cs:712`） | 同量级 |
| 效果/事件/续延队列 | — | 三重平行队列 → 合并为效果条目结构体 ~16 B/项 × 512 ≈ **8 KB**（上限 1024，见 §4.3） | 每项 ~100 B |
| 活跃程序帧 + 临时规则 | — | < 1 KB | 小 |
| **单场可变合计** | | **≈ 25–60 KB（含环形日志）** | **≥ 300 KB – 数 MB** |

**内容（整场共享、只读）**：8.29 MB 示例 JSON 是**整个游戏**的内容（含地图/事件/元数据），不是一场战斗。真正需要常驻的内容子集 = 本场用到的卡定义 + 状态定义 + 敌人行动 + 触发定义 + 编译后的效果程序树，按"30 张卡 × ~8 节点 × 24 B + 30 状态 + 10 敌人行动 ≈ **10–50 KB**"估 ⇒ **可固化 flash/ROM，按需分页到 PSRAM**。

| 放 SRAM（快、少） | 放 PSRAM（大、慢） | 固化 ROM/flash（只读） |
|---|---|---|
| `CombatState` 全部标量 + 战员数组（~1 KB） | `CombatLog` 环形缓冲 | 卡/状态/敌人行动**定义**表 |
| **卡实例（~5 KB）—— 建议留 SRAM，不要赶到 PSRAM** | 快照/规范文本 buffer（每次哈希 ~10 KB） | 编译后的**效果程序树** |
| 队列（~8 KB）、状态实例（~1 KB） | 存档/读档缓冲、内容加载临时区 | id 字符串池（`standard.strike` 等） |
| 随机数状态（8 B）、计数器 | | 位图 / 本地化字符串 / 主题字体 |
| **合计 ≈ 25–40 KB** —— 占 592 KB SRAM 的 5–7%，**绰绰有余** | | |

**判断**：SRAM 592 KB **完全够**。真正的风险不是容量，而是 **(a) `CombatLog`/trace 的无界增长**、**(b) 每步产生规范文本做 SHA-256 的 PSRAM 带宽 + 算力**。RL 训练务必用增量 `hash_full`。

## 7. 验收测试向量（重写对拍基准）

每条给：初始状态 → 操作序列 → 期望。**`hash_golden` 一栏需先在原实现上跑出来填死**（把 `CombatStateHasher.ComputeHash(combat.CreateSnapshot())` 的值贴进来）；下表给的是**语义期望**。

| # | 来源 | 初始状态 | 操作 | 期望 |
|---|---|---|---|---|
| **V1** 回合推进 | `T:CombatTurnProcessorTests.cs:50-67` | hero_001(20/20, player) + goblin_001(12/12, enemy)，`TurnOrder=[hero,goblin]`，`Active=hero`，Round=1 Turn=1 | `StartCurrentTurn` → `EndCurrentTurn` | `Active==goblin`；`Round==1`；`Turn==2`；`TurnPhase==WaitingToStartTurn`；日志类型序 **`[TurnStarted, TurnEnded]`** |
| **V2** 轮次回绕 | `T:CombatTurnProcessorTests.cs:70-85` | 同上，但先 `SetActiveCombatant(goblin)` | `StartCurrentTurn` → `EndCurrentTurn` | `Active==hero`；**`Round==2`**；**`Turn==1`**；`TurnPhase==WaitingToStartTurn` |
| **V3** 回合结束前先消化挂起效果 | `T:CombatTurnProcessorTests.cs:136-173` | 仅注册 `GainBlockEffectHandler` + `DealDamageEffectHandler` + Block 池定义（`AbsorbPriority:0, ClearsOnOwnerTurnStart:true`）；hero 20/20 | `StartCurrentTurn`；入队 `GainBlock(hero,6)`、`DealDamage(hero,10)`；`EndCurrentTurn` | hero HP **16**；Block **0**；`PendingEffectCount==0`；`Active==goblin`；日志类型序 **`[TurnStarted, TurnEnded, BlockGained, DamageDealt]`** |
| **V4** 同轮内"效果先于事件" | `T:CombatQueueProcessorTests.cs:57-80` | hero 20/20；注册 `AddLogOnTestEventHandler`（只写一条 `TestEventHandled` 日志） | 先 `EnqueueEffect(GainBlock(hero,3))` 再 `EnqueueEvent(TestCombatEvent)`；`ResolvePendingQueues` | `CombatLog.Count==2`；`[0].Type=="BlockGained"`；`[1].Type=="TestEventHandled"` |
| **V5** 队列循环预算 | `T:CombatQueueProcessorTests.cs:83-103` | 注册一个"每次处理都重新入队自己"的 handler | `ResolvePendingQueues(combat, registry, new CombatExecutionLimits(maxQueueCycles: 3))` | **抛 `InvalidOperationException`**（消息含 "limit of 3 cycles"） |
| **V6** 触发重入抑制（先于过滤器） | `T:CombatEffectReentryPolicyTests.cs:8-56` | 一个 `SuppressRecursiveReentry`（默认）的 RoundStarted 触发，程序会入队"再发一个 RoundStarted"的效果；过滤器只计数 | `EnqueueEvent(RoundStartedCombatEvent)` → `ResolvePendingQueues` | `filter.MatchCount==1`；`resolvedEffectCount==1`；两队列均空；`CurrentEffectChain == null` |
| **V7** 触发深度上限（先于过滤器；递归抑制优先） | `T:CombatEffectChainDepthLimitTests.cs:50-136` + `:138-187` | `maximumTriggerDepth=3`；注册 `test.depth_0..3` 四个互相级联的 RoundStarted 触发 | `EnqueueEvent(RoundStarted)` → `ResolvePendingQueues` | **抛 `InvalidOperationException`**，消息同时含 `"test.depth_3"` 与 `"maximum trigger depth of 3"`；`activationCount==3`；`resolvedEffectCount==3`；`terminalFilter.MatchCount==3`；两队列均空；`CurrentEffectChain == null`。**变体**（`:138-187`，`maximumTriggerDepth=1`，单个自我重入定义）：**不抛**，`resolvedEffectCount==1` |
| **V8** 根链深度为 0、上限可配置 | `T:CombatEffectChainDepthLimitTests.cs:21-47` | `maximumTriggerDepth=3`；注册一个"捕获 `combat.CurrentEffectChain`"的效果 handler | 入队该效果；`CombatEffectQueueProcessor.ResolvePendingEffects` | 捕获到的链 `TriggerDepth==0`；`MaximumTriggerDepth==3`；结束后 `combat.CurrentEffectChain == null` |
| **V9** RNG 洗牌回放确定性 | `T:RngDeterminismTests.cs:24-53` | 标准 registry；hero+goblin；抽牌堆空、弃牌堆放 5 张 `standard.strike` | 入队 `DrawCardsEffectRequest(hero, 3)`；`ResolvePendingQueues`。**跑两遍**（同 seed=12345） | `RandomStep > 0`（洗牌消耗了步数）；两遍**手牌 id 序列完全相同**；两遍**快照哈希完全相同** |
| **V10** 存档→还原→再快照：哈希恒等 | `T:CombatStateRestoreTests.cs:36-69`（初始态见 `:15-34`） | hero 有 energy `(2, max 3)`；牌 `c1→Hand`、`c2→DrawPile`、`c3→DiscardPile`；对 goblin 施加 Stun(0 stacks, dur 1) 且造成 3 伤害；`AdvanceRandomStep()` | ① `Restore(snapshot)` → 比哈希；② `ToJson` → `FromJson` → `Restore` → 比哈希 | 两次都 **`hash(snapshot) == hash(restored.CreateSnapshot())`**；`Energy.Current==2`；`Hand.Count==1`；`DrawPile` 单张且 `Id=="c2"`；goblin 有 Stun 且 HP 一致。**另**（`:87-100`）：带 `TemporaryRules` 的快照在无 registry 的 `Restore` 下**必须抛** |
| **V11** 出牌：付费/落区/伤害 | `T:PlayCardOperationTests.cs:16-65` | hero(20/20) + goblin(12/12)；自由卡（费用 0）程序 = `DealDamageNode(EventTarget, 5)`；卡在 Hand | `PlayCardEffectRequest(hero, card, goblin)` → `ResolvePendingQueues` | `outcome.WasPlayed==true`；goblin HP **7**；卡 `Zone==DiscardPile`；`Hand` 空。**变体**（`:46-65`）：费用 2、energy 3/3 ⇒ energy **1**。**拒绝语义**（`:114-155`）：能量不足 / 卡在 DrawPile / hero 已 `Dead` ⇒ `WasPlayed==false`，goblin HP 保持 **12**，卡**保持原区**，energy 不变 |
| **V12** 队列语义（付费即时/效果延后/FIFO/锁目标） | `S:QueueTortureTests.cs:169-192`、`:194-214`、`:216-234` | 敌方 200 HP；牌 `deferred`(QueueOnPlay, cost 1, deal 13) / `guard`(QueueOnPlay, cost 1, gain 11 Block) / `docket`(resolve oldest 1) / `counter`(deal 6+3×QueueCount) | ① 出 `deferred`；② `EndTurn` | ① 后：energy **−1**、敌方 HP **不变**、`Queue.Count==1`；② 后：敌方 HP **−13**、`Queue` 空。**`:194-214`**：先 `deferred` 再 `guard` ⇒ `Queue.Count==2`；`EndTurn` 后 `Queue` 空、敌方 **−13**、hero **Block==11**（清 Block 发生在队列解析之前，所以这 11 点存活）。**`:216-234`**：`deferred`×2 后出 `docket` ⇒ 敌方 **−13**（只解析最老一张），`Queue.Count==1` |
| **V13** 法令：未花完的带进明天 | `T:CombatDecreeTests.cs:130-143`（+`:145-172`） | hero 能量池 max 3 且 `SetCurrent(2)`；hero 戴 `CombatRuleSpec(UnspentResourceCarries)` | 触发 turn-start 的 `RefillResource(energy, defaultMax:3)` | `Energy.Current==5`；**`Energy.Max==3`**（故意超标；之后仍可继续支付 —— `:146-172` 连出 4 张 cost-1 Strike ⇒ 6→5→…→**2**）。**反例**（`:174-185`，无法令）：refill 覆盖 ⇒ `Current==3` |
| **V14** 法令：手牌上限 | `T:CombatDecreeTests.cs:203-214` | hero 戴 `CombatRuleSpec(MaxHandSize, Amount:7)`；抽牌堆 10 张 | 抽 10 | `Hand.Count==3`；`DrawPile.Count==7`（**没抽到的卡留在抽牌堆，不是抽出来扔掉**） |

**对拍执行建议**：① 先在原 C# 实现上把每条向量的 `hash_golden` 与**完整快照**落盘成 JSON 期望文件（哈希只覆盖 §5.4 列出的子集，所以必须同时落盘完整快照，否则漏检 §5.4 的漏检项）。② V1–V3、V6–V8、V11 需要注入"自定义 handler / 触发定义"⇒ 重写侧需要一个**测试专用的小型内容注册入口**（对应 `CombatDefinitionRegistryBuilder` 的最小可用子集）。③ V9、V10 是**唯一**直接断言确定性；其余断言可观察状态/日志/异常，与哈希正交，两边都要过。④ 补两条原文没有但重写必需的向量：**(a) "非当前行动者出牌"** —— 记录原实现的**实际**行为（目前会被接受，`C:Cards\CardPlay.cs:82-94` 无行动者校验），以此钉死这条边界；**(b) "多防御池同时 `ClearsOnOwnerTurnStart`" 的入队顺序** —— §4.5 / §5.4#3 的唯一不稳定点，重写后应产生**稳定**顺序，需显式记为本项目的有意偏离。
