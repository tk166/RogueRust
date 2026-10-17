# Effect Program IR —— 重写规格书

> 源仓库 `D:\Vibe\sts-tui\ref\RogueDeck-Core`（C# / .NET 10，MIT）。目标：把战斗内核重写成不依赖 .NET 的内核（ESP32-P4 / RL 训练环境）。本文是**规格**非代码复制；断言附 `文件:行号`（相对仓库根）。
> **勘误**：任务书的 `Effects\EffectProgramDefinition.cs(218)` 不存在，218 行的对应文件是 **`Combat\Effects\TriggeredProgramDefinition.cs`**。任务书未列但同属本子系统的必要文件：`Combat\Serialization\CombatJson.cs`(422)、`Combat\CombatEffectChain.cs`(93)、`Combat\CombatEventHandling.cs`(145)、`Combat\CombatExecutionLimits.cs`(35)、`Effects\CombatantTargetSelectors.cs`(839)、`Effects\PositionalTargetSelectors.cs`(278)、`Combat\CombatRandom.cs`(57)。Programs 目录 10 文件共 8,815 行。

## 1. 职责与边界

**负责**：一个数据驱动的效果解释器 —— 把卡牌/状态/遗物/敌人动作的效果写成**与上下文无关的不可变 IR 树**，由确定性解释器执行。含 IR 类型系统(`Contracts.cs:43-535`)、控制流(`Nodes.cs:3-346`)、值语义与表达式求值(`Expressions.cs:41-2557`)、节点→effect request 翻译(`NodeExecutors.cs:602-2218`)、目标选择(`CombatantTargetSelectors.cs:49-839`)、作用域化结果存储与数据流校验(`Outcomes.cs:409-623` + `Contracts.cs:579-682`)、执行顺序/限额/重入(`Execution.cs:91-160` + `CombatEffectChain.cs:8-93`)、触发器确定性排序(`TriggeredProgramDefinition.cs:69-198`)、轨迹(`Trace.cs:19-72`)、JSON 往返（仅作者工具链，`CombatJson.cs:16-422`）。

**不负责**：① 数值结算（伤害/格挡/状态/资源/卡区算法在 `DamageEffects.cs`、`StatusEffects.cs` 等 `IEffectRequestHandler`，由 `CombatEffectQueueProcessor.cs:30-33` 调用；IR 只决定"发什么请求、什么顺序"）；② 事件队列与 handler 注册(`CombatEventHandling.cs:51-72`)；③ 持久化(`CombatStateSnapshot.cs`)；④ AI/UI/编辑器视图（`RogueDeck.Scenario.Authoring` 的 `CombatProgramModel` 不是运行时）。

**三层结构**：① 不可变程序树 → (registry: Type→executor) → ② 节点执行器（子节点 dispatch / effect 入队 / continuation 入队）→ ③ 宿主三队列循环。第 ① 层**语义必须原样保留**；第 ② 层的**实现机制**（闭包/反射/GC）**可以大幅简化**（§4.3、§5）。

**IR 是数据不是代码**：除 5 个逃逸口外全部可 JSON 往返（`CombatJson.cs:10-12, 363`）—— `SideEffectNode`(`Nodes.cs:99-114`)、`ContextValueExpression`(`Expressions.cs:952-960`)、4 个 `PreviousOutcome*Expression`(`Expressions.cs:66-204`)、`InstallTemporaryRuleNode`(`NativeNodes.cs:1550-1585`)（四者均未注册 JSON），加上触发器层的 `ContextFactory/BuildContext`(`TriggeredProgramDefinition.cs:19-20`)。

## 2. IR 数据结构

### 2.1 值类型：**只有 int 和 bool，没有 float**

表达式接口只有 `ICombatExpression<TContext,int>` 与 `<bool>` 两个闭合实例（`Expressions.cs:41-50`）；`Programs\` 内**零处** `float/double`。算术**饱和**不抛：`ArithmeticSaturation.Saturate(long)`（`Expressions.cs:211-217`，用于 `:231,256,280,304,544,580,200,798`）。除法用 `(long)` 中间量规避 `int.MinValue/-1`；除零默认返 0，可切 `Fault`（`:549-581`）。**唯一浮点**：`PositionalTargetSelectors.ForwardSign` 用 `double` 求两队 Y 均值的符号（`:43-52`）——重写必须改整数交叉相乘（`sign(enemySum*srcCnt - srcSum*enemyCnt)`）才逐位一致。⇒ **P4 的单精度 FPU 对本子系统不需要，内核可纯整数**（移植最大红利）。

### 2.2 节点（54 种）

通用字段：`TargetSelector` / `Amount|Delta|Value|Count`(int 表达式) / `ResultKey?` / `Max*`。原生操作实现 `INativeEffectOperationNode`（`Contracts.cs:84-96`），暴露 `ProducedEffectRequestType:Type`、`AcceptedTargetDomain`(默认 Combatant)、`TargetEligibility`(默认 LivingOnly)。

**控制流（10 种，`Nodes.cs`）**

| 节点 | 字段 | 语义 | 行 |
|---|---|---|---|
| NoOp | — | 空 | 27-32 |
| Sequence | `Children[]` | **批处理**：全孩子入队后才处理反应 | 3-25 |
| CausalSequence | `Children[]` | **因果**：每个孩子完全结算（含反应）才走下一个 | 34-56 |
| Conditional | `Condition:bool, Then, Else?` | `Children=[Then,(Else)]` | 58-97 |
| Repeat | `Count:int, Body, MaxCount=32` | 计数循环；count 只求值一次 | 116-155 |
| RepeatUntil | `StopCondition:bool, Body, MaxIterations=32` | 先跑后判；体至少一次；`IterationIndex` 可见 | 160-199 |
| ForEachTarget | `CollectionSelector, Body, MaxIterations=32` | 逐目标，`IterationTarget/Index` 生效 | 246-280 |
| ForEachCardInZone | `OwnerSelector, Zone, DefinitionFilter?, TagFilter?, MarkFilter?, TakeFirst?, Body, MaxIterations=64` | 逐卡；列表**循环开始快照**；`IteratedCard` 生效 | 287-346 |
| RandomTargetSelection | `CandidateSelector, Count:int, Body, MaxIterations=32` | 确定性随机取 Count 个（随机顺序）逐个体 | 201-244 |
| ChooseOptions | `Labels[], Count, Purpose, OptionAt(i)`（孩子=选项） | 玩家多选，按选中顺序链式结算 | `NativeNodes.cs:1657-1700` |

**原生操作（44 种，全在 `NativeNodes.cs`，字段见 `:6-1711` 属性块）** —— 生命：`DealDamage`(TargetSelector,Amount,`IgnoresBlock`,`Element?`,`Kind`,ResultKey)`:3-53`、`Heal`:54、`ModifyMaxHealth`:87、`SetHealth`:120。防御：`GainBlock`(…,Amount,ResultKey)`:160`、`ModifyDefensivePool`(…,`PoolId`,Delta)`:191`。资源：`GainResource`(…,`ResourceId`,Amount,`DefaultMax?`)`:227`、`LoseResource`:269、`RefillResource`:305、`ModifyResource`(…,Delta,`Min?`,`Max?`)`:1228`、`ModifySelectedResource`(…,`ResourceSelectionSpec`,Delta)`:572`。状态：`ApplyStatus`(TargetSelector,`SourceSelector?`,`StatusDefinitionId`,Stacks,`DurationTurns`,`Charges`,`UnrefusableBy?`,ResultKey)`:339`、`ApplyTriggerEventStatus`(…,`ResolveStatus(ctx)`,`Replicated`)`:423`、`RemoveStatus`:463、`RemoveStatusesByPolarity`(…,`StatusPolarity`)`:687`、`RemoveSelectedStatus`(…,`StatusSelectionSpec`)`:493`、`ModifySelectedStatusStacks`:525、`StealSelectedStatus`(From,Selection,To)`:604`、`ModifyStatusStacks/Duration/Charges`:715`。卡牌：`DrawCards`:823、`MoveAllCardsFromZone`(From,To)`:856`、`CreateCardInstance`(Definition,ToZone,Count)`:887`、`CreateCardCopy`(`ICardInstanceExpression`,ToZone,Count)`:927`、`MoveCardToZone`(Owner,Card,ToZone,`ZonePlacement`)`:1284`、`TransformCard`(Owner,Card,`ToDefinition`)`:1340`、`MarkCardInstance`(Owner,Source?,Card,`TagId`,`Remove`)`:1382`、`SetCardInstanceMarkCounter`(Owner,Card,`CounterId`,Value,`Relative`)`:1420`、`ReplayCardProgram`(Target,Card,`ScaleNumerator/Denominator`)`:981`、`PlayCard`(Player,Card,`CardTargetSelector?`)`:1491`、`QueueCard`:1701、`ResolveQueuedCards`(Target,Amount)`:1625`。单位/位置：`SummonCombatant`(Team,Definition,`DisplayNameKey`,MaxHealth,`Position?`,`StartingStatuses[]`)`:1026`、`MoveCombatant`(Target,`MovementMode`,X?,Y?,Step?)`:1074`、`SwapPositions`(First,Second)`:1136`、`SetCombatantLifecycleState`(…；eligibility=`AnyCombatantIncludingDowned`)`:1157`、`ChangeCombatantTeam`(同上)`:1185`。其他：`SetCombatantCounter`(Target,`CounterId`,Amount,`Relative`)`:655`、`AnnounceRule`(Announcer,`string Rule`)`:633`、`SetCombatResult`(`CombatResult`)`:1468`、`InstallTemporaryRule`(`ITriggeredEffectDefinition`,`TemporaryRuleLifetime`,`ExpiryEffects[]`)`:1550`、`RemoveTemporaryRule`(`TriggeredEffectDefinitionId`)`:1595`。逃逸：`SideEffectNode`(`Nodes.cs:99-114`)。

### 2.3 表达式（92 个 `*Expression` 类，全在 `Expressions.cs`）

| 分类 | 清单（行号） |
|---|---|
| 常量 | `Constant`:54 |
| 算术 | `Abs`:219、`Negate`:532、`Sign`:1050、`Add`:238、`Subtract`:262、`Multiply`:286、`Min`:310、`Max`:334、`Divide`:551、`Remainder`:587、`Clamp`:622 |
| 比较/布尔 | `Comparison`+`ComparisonOperator{Equal,NotEqual,Less,LessOrEqual,Greater,GreaterOrEqual}`:360-410、`And`:414、`Or`:438、`Not`:462（**And/Or 短路**） |
| 集合聚合 | `CountTargets`:1371、`SumOverTargets`:1329、`AnyTargetMatches`:1389、`AllTargetsMatch`:1430（后三者压/弹 IterationTarget） |
| 战斗态单目标读 | `CombatantCurrentHealth`:656、`MaxHealth`:676、`MissingHealth`:696、`HealthPercentage`:1069、`CurrentResource`:875、`MaxResource`:1176、`MissingResource`:1201、`DefensivePool`:1093、`Counter`:902、`Coord(axis)`:722、`StatusStacks`:777、`StatusStacksFromSource`:806、`StacksByPolarity`:846、`StatusDuration`:1229、`StatusCharges`:1256、`ZoneCardCount(zone,tag?,mark?)`:1122 |
| 几何/全局/迭代 | `GridDistance`(Manhattan):749、`RoundNumber`:925、`TurnNumber`:932、`IterationIndex`:941、`IterationTargetHasStatus`:481、`IterationTargetStatusStacks`:505 |
| 单目标谓词 | `TargetHasStatus`:1003、`TargetIsAlive`:1028、`TargetDowned`:1285、`TargetExists`:1305 |
| 回合统计 | `CardsPlayedThisTurn`:1473、`CardDrawsThisTurn`:1545、`DamageDealtThisTurn`:1565、`HitsThisTurn`:1586、`ResourceGainedThisTurn`:1606、`ResourceSpentThisTurn`:1629、`CardsPlayedThisTurnWithTag`:1651、`CardsPlayedLastTurn`:1676、`…WithTag`:1697、`FirstCardPlayed…HasTag`:1722、`CardPlaysThisCombat`:1503 |
| 触发事件读 | `EventAmount`:967、`TriggerEventSourceCardHasTag`:2072、`…IsReplicated`:2120、`…StatusIs`:2136、`…StatusPolarityIs`:2156、`…AmplifierIs`:2184、`…PreventerIs`:2202、`TriggerEventCardInstance`:2318、`TriggerEventCardZone`:2351、`ActionDealtDamage`:2288、`AnnouncedRuleIs`:2298、`TargetIntends`:2257 |
| **有副作用**（求值即发生） | `RandomBelow`:1917、`RandomCardInZone`:1934、`RandomCardInOwnerZone`:2025（推进 RNG）；`ClaimOnceThisAction`:2230（写 ledger，claim 即答案）；3 个聚合（压弹迭代目标） |
| 卡实例 `ICardInstanceExpression<TContext>→CardInstanceId?`:1749 | `Explicit`:1754、`CreateCardOutcome`:1765、`DrawCardOutcome`:1796、`PlayedCardInstance`:1820、`TriggerEventCardInstance`:2318、`CardInZone`:1838、`CardInOwnerZone`:1995、`FirstMarkedCardInOwnerZone`:1961、`ChosenCardInZone`:1868、`RandomCardInZone`:1934、`RandomCardInOwnerZone`:2025、`IteratedCard`:2058 |
| 卡属性 | `CardCost`:2388、`CardInstanceBaseCost`:2434、`CardInstanceHasMark`:2471、`CardInstanceHasTag`:2502、`CardInstanceMarkCounter`:2533 |
| **必须重写** | `PreviousOutcome{Field,BoolField,Sum,AnyTargetMatches}`:66-204（持 `Func<TOutcome,…>`）；逃逸 `ContextValueExpression(Func<TContext,int>)`:952-960 |

**应作为重写范式的写法**：`EventAmountExpression.Evaluate` 就是 `switch(context.SourceContext)` 的 tagged-union 事件字段表（`:970-998`），覆盖 11 种触发上下文（`StatusStacksChanged` 报 **New-Old**、`StatusMerged` 报 **AppliedStacks**、`CardsDrawn` 报 `Cards.Count`）；`TriggerEventStatus.Of:2102-2115` 同型。字符串比较：`TargetIntends` 用 `OrdinalIgnoreCase:2280`、`AnnouncedRuleIs` 用 `Ordinal:2314`，**不可混用**；未知兜底 `_=>0`/`_=>null` 必须保留。

### 2.4 结果键与结果类型

`EffectResultKey<TOutcome>(string Name)`（`:335-341`，空名抛）；`OrderedTargetOutcomes<T>` = `IReadOnlyList<TargetOutcome<T>>`，`TargetOutcome<T>(CombatantId TargetId, T Outcome, int DeterministicIndex)`（`:261-284`）；单元包装 `SingleOutcome<T>`（恰 1）/`OptionalOutcome<T>`（0 或 1），违反即抛（`:295-331`）。33 个 outcome `record`（`:5-154, 208-257`）全为 int/bool/id：例 `DamageOutcome(RequestedAmount,BlockedAmount,HealthLost,PreviousHealth,NewHealth,Overkill)`、`ApplyStatusOutcome(Applied,Merged,Blocked,ResultingStacks,ResultingDurationTurns,ResultingCharges)`。33 个 `OutcomeSlot<T>` 子类（`:161-257`）**只为一条不变量存在：每槽恰好完成一次，二次赋值抛**（`:161-180`）。执行器共 34 处 `ctx.Store(...)`。

### 2.5 选择器（37 个）

`ICombatantTargetSelector`（`CombatantTargetSelectors.cs:49-73`）五要素：`ResolveTargets(ctx)`、`Cardinality`、`TargetDomain`、`MayIncludeDownedTargets`(默认 false)、`RequiredContextCapabilities`(默认 None)。`TargetSelectorCardinality{ExactlyOne,ZeroOrOne,OneOrMore,ZeroOrMore,Unknown}`（`:15-31`），`IsAtMostOneTarget()`={ExactlyOne,ZeroOrOne}（`:39-40`）——标量读的准入判据。上下文 `CombatantTargetSelectionContext(Combat,Source,EventTargetId?,IterationTarget?)`（`:3-7`）。

清单：上下文 5（`Source`:75、`SourceIncludingDowned`:97、`EventTarget`:113、`IterationTarget`:261、`Explicit(id)`:488）；队伍 6（`AllAlliesOfSource`:136、`AllEnemiesOfSource`:154、`AllCombatants(AliveOnly)`:172、`AllDamagedAlliesOfSource`:219、`AllAlliesOfSourceWithStatus`:231、`AllEnemiesOfSourceWithStatus`:246）；ZeroOrOne 极值 10（`Lowest/HighestHealthEnemyOfSource`:191/205、`Lowest/HighestHealthAllyOfSource`:460/474、`Lowest/HighestHealth`:329/414、`Lowest/HighestHealthPercentage`:573/597、`Lowest/HighestStatusStacks`:359/374）；过滤/组合 7（`Damaged`:279、`Downed`:639、`WithStatus`:303、`WithoutStatus`:437、`Union`:507、`Except`:552、`First`:622）；位置 9（`PositionalTargetSelectors.cs`：`Adjacent`:96、`SameColumn`:113、`SameRow`:130、`AllInSourceColumn`:147、`AllInSourceRow`:164、`Frontmost`:182、`Backmost`:211、`Nearest`:240、`OpposingInColumn`:264；基元 `ManhattanDistance`:33、`ForwardSign`:40、`StepAlongDepthTowardEnemies`:61、`StepAlongDepthFromSource`）。flat（无位置）战斗里位置类选择器恒空。

### 2.6 输出缩放（跨切面）

`OutputScaleNumerator/Denominator` + `ScaleOutput(int)`（`Outcomes.cs:394-405, 430-452`）：**只缩放正数的向下产出**（伤害/格挡/治疗/抽牌/获得资源/状态层数），向下取整，`num==den` 或 `amount<=0` 恒等；**不作用于费用/命中数/目标数/移动**。用于重放（`NodeExecutors.cs:1576-1577`）与 Redacted 类标记。

## 3. 求值 / 执行算法

### 3.1 宿主三队列（理解一切的钥匙）

`CombatState` 持 `_pendingEffects/_pendingEvents/_pendingContinuations`（`:10, 401-406, 461-473`）；effect 与 event 都带**入队时的 effect chain**，effect 另带**入队时的所属 frame id**（`:406`，供队列期 handler 异常回绑）。

```
ResolvePendingQueues(combat, registry, limits):            # CombatEventHandling.cs:81-115
  while (hasEffects || hasEvents || hasContinuations) && Result == Ongoing:
     if cycles++ >= MaxQueueCycles(1024): THROW            # :99-102 (附 WhatIsLooping 诊断)
     ResolvePendingEffects(...)   # :22-57  全部 effect FIFO 出队、各以其 chain 解析
     ResolvePendingEvents(...)    # :51-72  全部 event 出队 → handlers 顺序执行
     if !hasEffects && !hasEvents && TryDequeueContinuation(out c):   # :107-111
         c(combat)                 # ★ 每 cycle 只跑一条 continuation
```

**这是"节点 B 看得到 A 引发的反应"的机制**（`NodeExecutors.cs:596-600` 注释原话）。

### 3.2 入口 `EffectProgramExecutor.Execute`（`Execution.cs:7-64`）

```
ValidateNodeExecutors(root, registry??Default)      # :23 → 缺 executor 立即抛(:184-196)
frame = new Frame(program.Id, combat.AllocateProgramExecutionId(), ctx)   # :25-28
ctx.Frame=frame; ctx.EffectChain ??= CurrentEffectChain ?? CreateRootEffectChain()  # :30-31
ctx.MaxProgramSteps=program.MaxProgramSteps                                # :32
frame.MarkRunning(); ConfigureTerminalCleanup(combat,onTerminal); RegisterActiveProgramFrame(frame)  # :35-37
trace(ProgramStarted)                                                      # :39-47
wrappedComplete = c => { if frame.IsTerminal: return;  // :49-58
                         frame.MarkCompleted(); Unregister(frame); onComplete?(c); }
using combat.EnterEffectChain(ctx.EffectChain): ExecuteNode(root,...,path=root)      # :60-61
```

`ExecuteNode` 是**同步**的，但只做解析+入队；效果在 3.1 的循环里落地。

### 3.3 节点分派（`Execution.cs:91-160`）

```
if frame.IsTerminal: return                                       # :104-105 陈旧 continuation 拒收
try:
  ctx.ProgramStepCount++; if > MaxProgramSteps: THROW             # :109-114 (默认 1024)
  trace(NodeEntered, nodeTypeName, path, scopeDepth, execId, scopeId, chainId)   # :116-126
  exec = registry.Get(node.GetType())                             # :128
  prev = combat.CurrentOwningProgramExecutionId                   # :133
  combat.SetCurrentOwningProgramExecutionId(frame.ExecutionId)     # :134 ★给期间入队 effect 打标
  try: exec.Execute(node, ctx, combat, onComplete,
                    dispatch: (child,c,oc)=>ExecuteNode(child,ctx,c,oc,registry,ChildPath(node,path,child)))  # :137-144
  finally: combat.SetCurrentOwningProgramExecutionId(prev)         # :148
catch ex when !frame.IsTerminal:                                   # :151-159
  frame.MarkFaulted(ex); Unregister(frame); throw
```

`ChildPath` 用**引用相等**在孩子里找下标再取路径段（`sequence[i]`/`causal[i]`/`conditional.then|else`/`repeat.body`/`repeatUntil.body`/`forEach.body`/`forEachCard.body`/`randomTargets.body`/`option[i]`），找不到退化为类型名（`:166-180`）。**路径是纯结构信息，重写可用 u16 索引路径替代字符串。**

### 3.4 结构节点算法（`NodeExecutors.cs`）

| 节点 | 算法 |
|---|---|
| NoOp `:171-179` | `EnqueueContinuation(onComplete)` |
| Sequence `:181-213` | `ChildNodes.ToArray()`；空→完成；**`onComplete==null` 时逐个 `dispatch(null)` 直接返回**；否则共享计数器 `remaining=[N]`，每孩子 continuation 递减，到 0 才 `onComplete` ⇒ 孩子同时入队，全部完成后父才继续 |
| CausalSequence `:215-248` | `Step(i)`：`Result!=Ongoing`→return；`i>=N`→`onComplete`；否则 dispatch(child[i])，其 continuation = `using EnterEffectChain(ctx.EffectChain) Step(i+1)` ⇒ **串行且每次重入 chain** |
| Conditional `:250-279` | 真→`OpenScope()`+dispatch(Then)（continuation 里 `CloseScope()`）；假→Else 同法；无 Else→入队 onComplete |
| Repeat `:281-329` | `count=EvaluateCount()` **一次**；`<0` 抛；`>MaxCount` 抛；`Iteration(i)`：`OpenScope`→dispatch(body)→continuation `CloseScope`+`EnterEffectChain`+下一轮 |
| RepeatUntil `:331-377` | `PushLoopIndex(i)`+`OpenScope`→dispatch(body)→continuation `CloseScope`→**pop 之前**求 `StopCondition`（`:363-365`，体里仍可见 IterationIndex）→`PopLoopIndex`→stop 则完成，否则下一轮；`i>=MaxIterations` 直接完成 |
| ForEachTarget `:379-430` | `ResolveTargetsTraced().ToArray()`；`len>MaxIterations` 抛；每轮 `PushIterationTarget(t,i)`+`OpenScope`，continuation `CloseScope`+`PopIterationTarget` |
| ForEachCardInZone `:432-506` | `owner=OwnerSelector.FirstOrDefault()`，缺失→完成；取区卡（可选 definition / definition Tags / 实例 Marks 过滤）→`TakeFirst`→`ToArray()` **快照**；`len>MaxIterations` 抛；每轮 `PushIterationCard`+`OpenScope` |
| RandomTargets `:508-583` | `count=clamp(EvaluateCount(),0,len)`；`count>MaxIterations` 抛；`CreateShuffledIndexes(len,seed,step)` 取前 count，**`AdvanceRandomStep()` 一次**；之后同 ForEach |
| SideEffect `:585-594` | `typed.Execute(ctx,combat)` **同步**，再入队 onComplete |
| ChooseOptions `:2127-2178` | 选项=`Picks(...)`（无 chooser 取前 `min(Count,Labels.Count)`；有 chooser 时去重/剔越界/空则回退）；按顺序 `OpenScope`+dispatch，每个等前一个 |

### 3.5 原生操作的统一模式（`:596-643` 注释即规范）

```
1. amount = ctx.ScaleOutput(Evaluate*)     # 仅"产出型"节点；费用/计数不缩放
2. targets = TargetSelector.ResolveTargetsTraced(ctx, combat)
3. slots = ResultKey is null ? null : targets.Select(_ => new XOutcomeSlot())
4. for i: combat.EnqueueEffect(new XEffectRequest(..., OutcomeSlot: slots?[i]))
5. if ResultKey is key: EnqueueContinuation(c => { results = targets.Select((id,i)=>TargetOutcome(id,slots[i].Value!,i));
                                                  ctx.Store(key, new OrderedTargetOutcomes(results)); onComplete?(c); })
   else: EnqueueContinuation(onComplete)
```

⇒ **结果键语义 = "等所有请求落地后从槽取值写入当前作用域"**；`DeterministicIndex` 就是 `targets` 解析顺序（`:631-632`）。

**特例（逐条复刻）**：`ApplyStatus` 命名源解析为空 ⇒ **整节点不发请求**（不回落行动者），链继续 `:917-929`；`ApplyTriggerEventStatus.ResolveStatus==null` ⇒ **同步** `onComplete(combat)`（不入队）`:1162-1167`，复制时带 `Replicated:true` `:1187-1193`；`TransformCard/MoveCardToZone` 卡片或 owner 为 null ⇒ **同步**写 `WasTransformed/WasMoved:false` 结果并继续 `:1859-1878, 1913-1932`；`PlayCard` 卡片或玩家空 ⇒ `Store(key, OrderedTargetOutcomes<PlayCardOutcome>.Empty)`（**唯一显式存空值处**）`:2050-2067`；`CreateCardCopy` 源 definition 失败 ⇒ `targetList=[]` 但仍完成键与 continuation `:1515-1519`；**`GainBlock` 有 `ResultKey`+`GetProducedResult()`(`NativeNodes.cs:166,181-184`) 但执行器从不 Store**（`:765-781`）⇒ 预检过、运行期取值抛（**须决策，建议补 Store**）；`QueueCard` 额外入队 `CardPlayedCombatEvent`（"排队的卡现在算已打出"）`:2180-2218`；`AnnounceRule` 入队的是 **event** 而非 effect `:963-979`；`SummonCombatant/SetCombatResult/TransformCard/MoveCardToZone/Install|RemoveTemporaryRule` 存**裸 outcome**（单槽非 Ordered）`:1592-1620, 1960-1985, 1888-1903, 1943-1955, 1987-2040`；`ReplayCardProgram` 建新 `EffectExecutionContext<CardPlayContext>`+可选 scale 后**递归** `Execute(...)`（独立子程序，不入队）`:1552-1590`；`MoveCombatant` 未放置/目的地 null ⇒ 跳过 `:1639-1662`；`SwapPositions` 只取两侧第一个，相同 id/未放置 ⇒ 无操作 `:1669-1695`；`StealSelectedStatus` `from==thief` 跳过 `:1054-1078`；`ModifySelectedStatusStacks/RemoveSelectedStatus` 命名源空 ⇒ 传 null 给 `StatusSelection`（"选不到"）`:1084-1092`；`ResolveQueuedCards` 同步调 `QueueResolution.ResolveOldest`（绕过队列）`:2110-2125`。`SelectorResolutionTracing`(`:6-24`)：所有解析走 `ResolveTargetsTraced`，仅 `TraceListener!=null` 时发事件，行为等价。

### 3.6 表达式求值

纯函数 `Evaluate(EffectExecutionContext<TContext>, CombatState)`。安全带：`ScalarTargetExpression.RequireSingleSelector` **构造期**拒多目标、`RequireSingle` **求值期**若 >1 抛；空集由各表达式返默认（0/false）（`Expressions.cs:11-37, 667-673`）。`IterationTarget` 是**词法**的：`ctx.GetTargetSelectionContext()` 把它注入选择上下文（`Outcomes.cs:610-614`），聚合表达式手动压弹。

### 3.7 生命周期状态机（`Identity.cs:5-181`）

`{Created,Running,WaitingForNativeOperation,WaitingForReactionBoundary,Completed,Cancelled,Faulted}`（中间两态**目前无代码写入**，是预留）。`Created→MarkRunning→Running`；`MarkCompleted`（终态，从终态再转抛）；`MarkCancelled`（已是 Cancelled 幂等返回，从 Completed/Faulted 抛）；`MarkFaulted(ex)`（从 Completed 抛）；`CancelDueToCombatEnd()` 幂等 no-op；`FaultDueToNativeHandler(ex)` 非终态幂等 no-op。每次终态转换发一次 trace 并跑一次 `RunTerminalCleanup()`（`_terminalCleanupRan` 保证恰一次，`:104-111`）。**战斗结束时** `CombatState.SetResult` 把 `_activeProgramFrames` 全部 `CancelDueToCombatEnd()` 并清空（`CombatState.cs:361-366`）——因为 3.1 循环在 `Result!=Ongoing` 时直接停，否则 frame 永远停在 Running。

## 4. 顺序契约与不变量

### 4.1 不可变契约

| # | 契约 | 证据 / 理由 |
|---|---|---|
| O1 | **Causal 的每个孩子完全结算（含其引发的全部反应）后下一个才被求值** | `NodeExecutors.cs:215-248`；`EffectProgramCausalSequenceTests.cs:46-71`（causal→HP 15）vs `:74-90`（batch→HP 5） |
| O2 | **Batch 的所有孩子先入队，反应最后跑** | `NodeExecutors.cs:195-212` |
| O3 | continuation **只在 effect 与 event 队列都空**时每 cycle 跑一条 | `CombatEventHandling.cs:107-111` |
| O4 | effect 严格 FIFO，且以**入队时绑定的 chain** 解析 | `CombatState.cs:394-407`、`CombatEffectQueueProcessor.cs:28-33` |
| O5 | 先入队请求、**后**入队自己的完成 continuation ⇒ 读取者一定看到已结算 outcome | `NodeExecutors.cs:614-641`（请求 615-623 早于 continuation 629-636） |
| O6 | `Repeat.Count` **只求值一次**；`RepeatUntil.StopCondition` 在**每次体后、pop 前**求值 | `:287`、`:363-365`；`EffectProgramRepeatTests.cs:118-145`（callCount==1） |
| O7 | 每次迭代 `OpenScope`+压迭代变量，**在 continuation 里成对关闭/弹出** | `:321-327, 419-427, 495-503, 572-580` ⇒ 外层值自动恢复，无需保存/恢复 |
| O8 | `IterationTarget/IterationCard/IterationIndex` 是**词法**的（最内层），空则 null/0 | `Outcomes.cs:352-371, 454-484`；`Expressions.cs:944-945`（越界读 0） |
| O9 | 结果键**同作用域唯一生产者**、**先生产后消费**、读取类型须一致、标量读要求生产者单目标 | `Contracts.cs:601-622, 687-701`（构建期，`EffectProgram` 构造时执行 `:572-573`） |
| O10 | **分支内结果键不外泄**；Sequence 兄弟共享外层可见集；Causal 兄弟逐个累积 | `Contracts.cs:626-681` |
| O11 | 同名触发器顺序 = `(Priority asc, Id asc)`，**与注册顺序无关** | `TriggeredProgramDefinition.cs:88-92, 104-106`；`TriggeredProgramParityTests.cs:334-353, 355-373` |
| O12 | `Result!=Ongoing` ⇒ 立即停；Causal/Repeat/RepeatUntil/ForEach/ForEachCard/RandomTargets 进入下一轮前检查并**丢弃剩余迭代**（不抛） | `NodeExecutors.cs:232-233, 311-312, 347-348, 410-411, 486-487, 563-564`；`EffectProgramRepeatTests.cs:171-188` |
| O13 | **陈旧 continuation 丢弃**：frame 已终态时 `ExecuteNode` 直接 return | `Execution.cs:104-105`；`wrappedComplete` `:53-54` |
| O14 | RNG = `(RandomSeed, RandomStep)` 的**纯函数哈希**（SplitMix 变体）+ Fisher–Yates 倒序；每次随机读后 `RandomStep++` | `CombatRandom.cs:5-56`；`CombatState.cs:675-678` ⇒ 快照只需存 step |
| O15 | 结果槽**恰好完成一次**，二次赋值抛 | `Outcomes.cs:161-180` |
| O16 | 存储键是 `(name, Type)` 元组 ⇒ **同名不同类型不冲突** | `Outcomes.cs:416-418, 574, 581, 596` |

### 4.2 重入保护与限额（具体数字全部保留）

触发器级：`CombatEffectChainContext` 携带 `TriggeredEffectDefinitionId` 列表（`CombatEffectChain.cs:12-41`）。`CanEnterTriggeredEffectDefinition`：`SuppressRecursiveReentry` ⇒ `!defIds.Contains(Id)`；`AllowRecursiveReentry` ⇒ true；其他 ⇒ 抛（`:49-62`）。判定点 `TriggeredProgramDefinition.cs:117-123`（跳过并 trace `SkippedReentrySuppressed`）与 `:128-135`（先 trace 再抛）。

| 限额 | 默认 | 定义 | 检查 |
|---|---|---|---|
| 节点树静态深度 `MaxNodeDepth` | **64** | `Contracts.cs:539` | `:721-723`（构建期） |
| 程序步数 `MaxProgramSteps` | **1024** | `:540` | `Execution.cs:110-114`（运行期，含循环重入） |
| 活跃作用域 `MaxActiveScopes` | **32** | `Outcomes.cs:500` | `:522-536`（先 trace `LimitExceeded` 再抛） |
| 触发器链深度 `MaximumTriggerDepth` | **64** | `CombatEffectChain.cs:10` | `:67-71` |
| `RepeatEffectNode.MaxCount` | **32** | `Nodes.cs:119` | `NodeExecutors.cs:294-297` **抛** |
| `ForEachTargetEffectNode.MaxIterations` | **32** | `:249` | `:390-393` **抛** |
| `ForEachCardInZoneNode.MaxIterations` | **64** | `:290` | `:467-470` **抛** |
| `RandomTargetSelectionNode.MaxIterations` | **32** | `:204` | `:519-522` **抛** |
| `RepeatUntilEffectNode.MaxIterations` | **32** | `:163` | `:351-355` **静默完成** ⚠ |
| 队列 cycle `MaxQueueCycles` | **1024** | `CombatExecutionLimits.cs:12` | `CombatEventHandling.cs:99-102`（抛 + `WhatIsLooping` 诊断） |
| 每 cycle effects / events | **1024/1024** | `:13-14` | `CombatEffectQueueProcessor.cs:24-26`、`CombatEventHandling.cs:53-55` |

⚠ `Repeat/ForEach/ForEachCard/RandomTargets` 超限是 **throw**，而 `RepeatUntil` 超限是**正常完成**。**不可统一**。

### 4.3 必须原样保留 vs 可以大幅简化

| 必须原样保留（语义） | 可大幅简化（实现） |
|---|---|
| O1–O16 全部顺序契约；全部限额数字与 throw/静默的区分 | `Action<>` continuation → 显式续体记录（§5.1） |
| `TContext` 的**可观测行为**（哪些表达式在哪种触发器下有效、`EventAmount` 的分支集合） | `TContext` 泛型本身 → 运行期 `ContextTag`+union（§5.3） |
| 结果键的词法作用域 + 单生产者/类型/基数契约 | `(string,Type)` 字典 → `u16 key id`+定长 slot 数组（§5.4） |
| 33 个 outcome 的字段集与含义；槽"恰一次"不变量 | 33 个 `OutcomeSlot` 子类 → 1 个 tagged struct（§5.8） |
| RNG 算法（SplitMix+step 递增+Fisher–Yates 倒序） | LINQ / `IEnumerable` 实现（§5.7, §5.9） |
| And/Or 短路 + 副作用表达式的求值时机；`Ordinal` vs `OrdinalIgnoreCase` | JSON 运行时反序列化（§5.5，只在工具链保留） |
| 异常 → frame Faulted 的单终态语义 | 用异常做控制流（§5.6） |

## 5. 宿主依赖清单（最重要）

统计口径：正则计数（`Programs\` 10 文件 8,815 行 + `TriggeredProgramDefinition.cs` 218 行）。

| 依赖 | 处数 | 分布 |
|---|---|---|
| `Action<…>` | **199**（Programs）／203（整个 Core） | Executors 189、Execution 6、Nodes 2、Identity 2 |
| `Func<…>` | **10**（Expressions）／4（TriggeredProgramDefinition） | — |
| `typeof(` | 105 | Contracts 33、Executors 53、NativeNodes 7、Outcomes 6、其他 6 |
| `throw new` | 65 | Executors 9、NativeNodes 10、Outcomes 10、Expressions 9、Contracts 6… |
| LINQ 调用 | 197 | Executors 145、Expressions 42、NativeNodes 5、Nodes 4 |
| `Dictionary<…>` | 14 | Contracts 9、TriggeredProgramDefinition 4、Executors 3、Outcomes 2 |
| `record` | 37 | Outcomes 33、Identity 3、Contracts 1 |
| `IEnumerable<…>` | 108 | NativeNodes 66、Expressions 23、Nodes 7、Contracts 4 |

### 5.1 `Action<>` / `Func<>` 闭包（最大工程量）

**5 类语义**：① **continuation（核心机制）** —— `combat.EnqueueContinuation(Action<CombatState>)`(`CombatState.cs:465-473`)、执行器签名 `Execute(node,ctx,combat, Action<CombatState>? onComplete, Action<IEffectNode,CombatState,Action<CombatState>?> dispatch)`(`NodeExecutors.cs:28-36`)：**28 处"存结果键再继续"的闭包**(`:629,669,709,749,806,846,884,947,1221,1258,1297,1336,1375,1413,1451,1491,1536,1608,1718,1755,1796,1835,1891,1946,1973,2001,2028,2093`)、**85 处 `EnqueueContinuation(...)`**、**10 处 `dispatch(...)` 闭包**(`:198,205,242,273,322,360,422,498,575,2172`，每次进入控制流节点都分配一个捕获 `children/body/index/ctx/onComplete` 的闭包对象)；② **结果字段读取器** `Func<TOutcome,int|bool>`(`Expressions.cs:71,80,110,119,149,156,181,188`)；③ **上下文读取器** `ContextValueExpression(Func<TContext,int>)`(`:952-956`)；④ **副作用节点** `SideEffectNode(Action<…>)`(`Nodes.cs:102,106`)；⑤ **终态回调** `Action<EffectProgramExecutionState,CombatState>`(`Identity.cs:72,96-102`)、`Action<CombatState>? onComplete`(`Execution.cs:11-13`)。

**no_std 替代：显式续体记录（tagged union），禁止闭包。**

```rust
enum ContKind: u8 { ProgramDone, SeqNext, CausalNext, CondExit, RepeatNext, RepeatUntilNext,
                    ForEachNext, ForEachCardNext, RandomIterNext, ChooseNext, NativeStore }
struct Continuation {                     // POD，无指针无 GC
  kind: ContKind, node_idx: u16 /*编译期节点索引*/, index: u16 /*孩子或迭代下标*/,
  scope_id: u16,                          // 需要 CloseScope
  key: u16,                               // NativeStore
  target_lo: u16, target_hi: u16,         // 目标区间（在 frame 的 target arena 里）
  slot_base: u16,                         // outcome slot arena 起点
  parent: u16,                            // 父续体索引 ⇒ onComplete 链塌缩为续体栈
}
```

要点：**不要用 C 模拟闭包**——闭包捕获的一切（children/index/count/ctx/onComplete）本来就在树或 frame 里，改成 `(节点位置, 迭代下标, 父续体)` 即零分配；`dispatch` 变 `dispatch_child(frame, child_idx, parent_cont)`；`Func<TOutcome,*> Field` → `enum OutcomeField:u8` + 只读表 `const OUTCOME_FIELD: [[FieldAccess;N];33]`（放 ROM）；`ContextValueExpression`/`SideEffectNode` 直接删除（JSON 也未注册）；触发器层 `ContextFactory/BuildContext` → 每事件类型一个具名 `fn(combat,&Event)->Option<Ctx>`，放在按 `EventKind` 索引的 const 表；`onTerminal` → `TerminalReason` 枚举 + switch/函数指针表。

### 5.2 `typeof` 注册表 / `Type` 作为键

| 位置 | 用法 | 替代 |
|---|---|---|
| `EffectNodeExecutorRegistry._executors: Dictionary<Type, IEffectNodeExecutor>` `NodeExecutors.cs:42` | 运行期按 CLR 类型找执行器 | `enum NodeKind` + `const NODE_EXEC: [fn(&mut Frame, NodeId); N]`（ROM） |
| 53 条 `RegisterOpenGeneric(typeof(XNode<>), new XExecutor())` `:60-112` | 开泛型+反射闭类型 | 编译期固定表；**顺带消灭开泛型/闭类型 fallback**(`:143-157`) |
| `IEffectNode.NodeContextType => typeof(TContext)` `Contracts.cs:76` | 上下文能力校验 | `ContextTag` |
| `IResultKeyConsumer.ResultKeyType:Type`、`ProducedResult.Type` `Contracts.cs:18,33-36` | 结果类型安全 | `enum OutcomeKind:u8`，preflight 比枚举 |
| `Type` 相等比较 + `FormatType` 反射 `Contracts.cs:611-614,703-714` | 报错文本 | `OutcomeKind`→`&'static str` 表 |
| 存储键 `(string,Type)` `Outcomes.cs:418,574,581,596` | 类型安全同名结果 | §5.4 |
| `node.GetType().Name`(`Execution.cs:120,163`)、`ex.GetType().Name`(`Identity.cs:152`) | 诊断 | `NodeKind`/`FaultCode` 名字表 |
| **`EffectContextCapabilities.ForContextType` 按 `Type.Name` 字符串猜** `EffectProgramTargetingContracts.cs:54-81` | `name=="CardPlayContext"` / `name.EndsWith("TriggeredEffectContext")`，**未匹配返回 All（宽容）**:79-80 | `enum ContextKind` + `const [EffectContextCapability;N]` 表；**保留"未知上下文=All"**，否则第三方内容被误拒 |
| `type.MakeGenericType(contextType)` `CombatJson.cs:44` | 运行时闭泛型 | **无等价物**，见 §5.3 |

### 5.3 `TContext` 泛型本身

整个 IR 是 `class Foo<TContext> where TContext:class`（`Contracts.cs:68,536-539`；`Expressions.cs:41-42`；`NativeNodes.cs` 全文件）。`TContext` 只用于：① `EffectExecutionContext<TContext>.SourceContext` 的静态类型(`Outcomes.cs:426`)；② JSON 的开泛型闭合 `MakeGenericType`(`CombatJson.cs:44`)；③ 上下文能力校验。**替代**：降为运行期 tag。

```rust
enum ContextTag: u8 { CardPlay, EnemyAction, DamageDealt, DamageReceived, Healed, StatusApplied,
                      StatusMerged, /* … */ RuleAnnounced, ActionResolved }
struct EventPayload { tag: ContextTag, source_card: u16, target: u16, actor: u16,
                      amount: i32, amount2: i32, status: u16, zone: u8, replicated: bool }
```

证据：`EventAmountExpression`(`Expressions.cs:970-998`) 与 `TriggerEventStatus.Of`(`:2102-2115`) **已经就是这个模式**——`switch(SourceContext)` 在固定事件字段表上取值。重写只是把编译器的类型分派改成显式 tag 分派，**正好**让 IR 与 JSON 都不再需要泛型（也消灭 P4 上 44 节点 × N 上下文的单态化膨胀）。

### 5.4 字符串键字典 / 字符串 ID

| 位置 | 替代 |
|---|---|
| `EffectResultKey<TOutcome>(string Name)` `Outcomes.cs:335-341` | `struct ResultKeyId(u16)`，内容编译器分配；名字只留调试表 |
| 作用域栈 `List<Dictionary<(string,Type),object>>` `:418`；`OpenScope` 每次 `new Dictionary`:537 | `MaxActiveScopes=32` 上界确定 ⇒ 定长 scope arena，每 scope `[Option<OutcomeValue>; N_RESULT_KEY]`（N 为内容包结果键总数，几十），零分配 |
| `CombatJsonRegistry` 的 `Dictionary<string,Type>` `CombatJson.cs:18-19` | **只在 PC 内容编译器**，不进固件 |
| 所有 `record Id(string value)`（`StatusDefinitionId`/`ResourceId`/`CardDefinitionId`/`TagId`/`CounterId`/`DefensivePoolId`/`ElementId`/`TeamId`/`CombatantId`/`CardInstanceId`…） | 编译期 intern 成 u16/u32，运行期零 strcmp。⚠ **副作用**：`Id` 的**字典序被用作触发器顺序**（O11，`TriggeredProgramDefinition.cs:105`），intern 后数字序 ≠ 字符串序 ⇒ 必须保留按字符串预排序的 id 表或显式 `u16 order` 字段 |

### 5.5 `System.Text.Json`

唯一入口 `CombatJson.cs`(422)：`JsonConverter<T>`(`:51-117`)、`Utf8JsonReader/Writer`、`JsonSerializerOptions.MakeReadOnly`、`JsonStringEnumConverter`(`:159`)、`DefaultJsonTypeInfoResolver().WithAddedModifier(...)` **反射删除 `Children` 属性**(`:177-193`)。装饰在 IR 上的属性：`[JsonConstructor]`(`Nodes.cs:13,44`；`NativeNodes.cs:1670`；`CombatantTargetSelectors.cs:513`)、`[JsonIgnore(WhenWritingNull/Default)]` 12 处（`Expressions.cs:1136,1878`；`NativeNodes.cs:19,352,369,428,499,536`；`Nodes.cs:298`；`StatusSelection.cs:36,43,50`）—— ⚠ `WhenWritingNull` 是"跳过 null 以保持旧文档逐字节等价"的**兼容要求**（`Nodes.cs:296-300` 注释），重写的内容编译器必须复刻。

**关键判断**：JSON 只属于作者工具/内容编译链，运行期只读已构建 registry。证据：`CombatJson.cs:132-137` 注释——每场战斗开始 1.7 秒里有 **1.6 秒**花在 System.Text.Json 的类型元数据反射上。⇒ **固件不需要 JSON 解析器**：内容预编译成紧凑二进制（或直接生成常量表），`CombatJson` 的等价物留 PC 端。若必须设备端读写 JSON，用 `serde-json-core`/自写 pull parser，但**不要**复刻 `MakeGenericType` 那条路。

### 5.6 异常作为控制流

**(a) 合约违约/限额（可恢复，须保留可观测性）**：负/超限 repeat count(`NodeExecutors.cs:289-297`)、ForEach/ForEachCard/RandomTargets 超限(`:390-393,467-470,519-522`)、程序步数超限(`Execution.cs:110-114`)、活跃作用域超限(`Outcomes.cs:522-536`)、除零 Fault 策略(`Expressions.cs:575-576,611-612`)、标量读多目标(`:30-36,94-97`)、结果键未生产/类型不符(`Contracts.cs:605-614` 构建期、`Outcomes.cs:588-589` 运行期)、结果槽二次完成(`:173-175`)、链深度超限(`CombatEffectChain.cs:70-71`)、队列 cycle/数量超限(`CombatEventHandling.cs:99-102`、`CombatEffectQueueProcessor.cs:24-26`)、缺 executor(`Execution.cs:189-192`)。

**(b) 参数校验（构造/加载期，可 panic）**：`ArgumentNullException.ThrowIfNull`、`ArgumentOutOfRangeException`（如 `Nodes.cs:139-142,183-186`）。

**替代**：`enum FaultCode:u16` + `Result<(),Fault>`；`Execute` 返回 `Fault` 而不 unwind；frame 进 `Faulted` 记录 `FaultCode`+`node_idx`。⚠ **不能简单 `panic!`**：RL 环境要批量自对弈（`roguedeck-bot --runs N`），一份非法内容不该杀掉整进程；但 (b) 类可以 panic（只在加载期）。

### 5.7 LINQ

Executors 145 处居首。**有分配的热点**：`node.ChildNodes.ToArray()`(`:186,220`)、`ChildNodes.ToArray()`(`:388`)、`ResolveTargetsTraced(...).ToList()`（约 24 处：`:609,652,692,732,772,790,829,868,907,1170,1206,1243,1281,1320,1359,1398,1435,1474,1518,1628,1703,1740,1778,1819`）、`.Select(...).ToList()` 造 outcome（`:631-633,671-673,711-713,751-753,808-810,848-850,886-888,949-951,1223-1225,1260-1262,1299-1301,1338-1340,1377-1379,1415-1417,1453-1455,1493-1495,1538-1540,1719-1721,1757-1759,1798-1800,1837-1839,2095-2097`）、`cards.Where(...).ToList()`(`:1163`)、`matches.Take(...)`(`:464`)。**替代**：全部改 `for` + 预分配 slice（arena）。`ToArray()` 的**快照语义必须保留**（`ForEachCardInZone` 的快照在 `Nodes.cs:286` 注释里明说），但可快照到预分配缓冲。

### 5.8 `record` 继承层次

33 个 outcome `record`(`Outcomes.cs:5-154,208-257`)+`TargetOutcome<T>`(`:261`)+`SingleOutcome/OptionalOutcome`(`:295,311`)+`EffectResultKey`(`:335`)+3 个 id `record struct`(`Identity.cs:191,207,227`)+`CombatantTargetSelectionContext`(`CombatantTargetSelectors.cs:3`)+若干 `record` 选择器。`record` 带来的语义：**结构相等**（测试与状态哈希依赖）、`with` 表达式(`Outcomes.cs:613`、`PositionalTargetSelectors.cs:73`) ⇒ POD struct + `PartialEq`/memcmp + 字段赋值。**`abstract class OutcomeSlot<TOutcome>` + 33 个空子类**(`:161-257`)：除"值只能写一次"外无内容 ⇒ `struct OutcomeSlot { filled: bool, value: OutcomeValue }` + `slot_set()` 断言；**恰一次不变量必须保留**(O15)，它是重复结算的哨兵。`IEffectNode`/`IEffectNode<TContext>` 双接口 + 协变 `IEnumerable`(`Contracts.cs:43-77`) 只为让执行器不认识 `TContext` 也能工作 ⇒ 单一 tagged 节点结构 + `NodeKind`。

### 5.9 其它 .NET 依赖

| 依赖 | 证据 | 替代 |
|---|---|---|
| `IReadOnlyList/IReadOnlyCollection/IEnumerable` 作为 IR 字段 | `NativeNodes.cs` 66 处 | `Slice<T>`(ptr+len) |
| `HashSet<…>` | `CombatState.cs:49,102,140,379` | bitset/小数组。⚠ `:102` 的 `Claims: HashSet<string>(Ordinal)` 就是 `ClaimOnceThisAction` 的账本(`Expressions.cs:2244`→`combat.TryClaimOnceThisAction`)，每个 action 作用域一个，须保留"claim 即答案"+Ordinal |
| `ConditionalWeakTable<Registry, Definition[]>` 缓存已排序触发器 | `TriggeredProgramDefinition.cs:75-76,88-93` | 编译期排好的静态数组（内容不变则序不变） |
| `IDisposable`+`using`（`EnterEffectChain`） | `CombatState.cs:500-511`；`NodeExecutors.cs:244,325,373,426,502,579` | 显式 `chain_push/pop` |
| `Exception? FaultException` 持异常对象 | `Identity.cs:23,69,150` | `FaultCode` |
| GC 假设：IR 是引用类型图且**表达式节点被共享** | `Expressions.cs` 全文件；`EffectProgramConditionalTests.cs:307-321`（`absDelta` 被两个节点引用） | arena + 节点索引；**共享语义保留** |
| `Math.Clamp/Sign/Abs`、`(long)` 提升 | `Expressions.cs:231,544,1062,643-646` | 手写整数版；注意 `Math.Abs(int.MinValue)` 已用 `(long)` 规避(`:231`) |
| `string.Equals(…, Ordinal/OrdinalIgnoreCase)`、`ThenBy(d=>d.Id.value)` 字符串排序 | `Expressions.cs:2280,2314`；`TriggeredProgramDefinition.cs:105` | 字节比较/ASCII 折叠；id 表按字符串序预排 |

**顺带发现的两处不一致（重写时须决策，属修 bug 而非移植）**：① `ApplyTriggerEventStatusNode<>` **在 JSON 注册了**(`CombatJson.cs:381`) 但**在 executor 注册表里没有**(`NodeExecutors.cs:60-112` 无此项，尽管 `ApplyTriggerEventStatusNodeExecutor` 存在于 `:1153`) ⇒ 任何含该节点的程序会在 preflight 抛(`Execution.cs:189-192`)。② `GainBlockNode` 声明 `ResultKey`/`GetProducedResult()`(`NativeNodes.cs:166,181-184`) 但执行器从不 Store(`:765-781`)。

## 6. 内存与 CPU 预算提示

### 6.1 内容体量实测

对自带内容包 `src\RogueDeck.Sandbox.Run\SampleContent\bureaucrats.roguedeck.json`（**8,291,305 字节**）做 kind 直方图：`"kind"` 出现次数 = **IR 对象总数 16,890**，其中 `node.*` **5,113**、`sel.*` **4,358**、表达式类 ~**5,741**（余量为其他域的 kind）。高频（前 18）：`const 3695`、`sel.iterationTarget 2264`、`sel.eventTarget 1637`、`node.setCombatantCounter 1637`、`node.sequence 1273`、`node.applyStatus 936`、`compare 739`、`fx.addCard 738`、`node.conditional 563`、`combatantCounter 550`、`combatantStatusStacks 495`、`fx.addRelicById 492`、`sel.source 315`、`node.dealDamage 260`、`node.gainBlock 181`、`and 177`、`node.modifyStatusStacks 159`。⇒ 全部内容约 **1.5 万个 IR 对象**；每对象 24–40 B 的 C 结构体 ⇒ **360–600 KB，必须放 PSRAM**（SRAM 592 KB 还要分给战斗状态与栈）。8.3 MB 的 JSON 只在 PC 侧。

### 6.2 可放 ROM（`.rodata`）的编译期常量表

节点 kind 名表(`CombatJson.cs:364-421`，52 条) / 节点→执行器函数表(`NodeExecutors.cs:60-112`，53 条) / 选择器 kind 名表(`CombatJson.cs:316-359`，36 条) / 表达式 kind 名表(`:217-313`，~100 条) / 结果键 id↔名表 / **outcome 字段访问表**（替代 `Func<TOutcome,int>`，`Expressions.cs:71,110,149,181`）/ **事件字段表**（`Expressions.cs:970-998,2102-2115`，按 `ContextTag` 索引）/ **上下文能力表**（替代 `TargetingContracts.cs:56-81`）/ 触发器 `(Priority,Id)` 已排序结果 / 各选择器的 `Cardinality`/`TargetDomain`/`MayIncludeDowned` 表。

### 6.3 峰值分配

**每次程序调用**：1 个 frame(`Execution.cs:25-28`)；1 个 `EffectExecutionContext`（含 1 个 `List<Dictionary>` 初始 dict、两个 `Stack<T>`、`List<long> _scopeIds`，`Outcomes.cs:418-424,456-459,480`）；**每次 `OpenScope` 再 1 个 `Dictionary`** + List 扩容(`:537`)。**每个带 `ResultKey` 的原生操作 × N 目标（最热路径）**：1 个 `List<CombatantId>` + N 个 `XOutcomeSlot` + 1 个 continuation 闭包 + 1 个 `List<TargetOutcome<T>>` + N 个 `TargetOutcome<T>` + 1 个 `OrderedTargetOutcomes<T>` ⇒ **≈ 4N+3 次堆分配**，在 28 个节点里重复(`:609-641` 模式)。**每次进入控制流节点**：`ChildNodes.ToArray()` 1 个数组(`:186,220`)；Sequence 额外 `remaining=new[]{N}` + **N 个 dispatch 闭包**(`:202-211`)；Causal/Repeat/RepeatUntil/ForEach/ForEachCard/RandomTargets/ChooseOptions 每步 1 个 dispatch 闭包(`:242,322,360,422,498,575,2172`)。

**已知爆炸案例（务必在设计里堵住）**：`CombatJson.cs:170-173` 注释记录"一个 boss 规则的 `Children` 视图被重复序列化，**达 311,624 节点 / 15 MB**，而树本身约 40 个节点" ⇒ **"可遍历视图"不能作为数据被写**；内容编译器要对节点数设限并检测重复。

**栈深度**：Sequence/CausalSequence 的 `dispatch` 同步递归(`:205,242`)，宿主循环的 `continuation(combat)`(`CombatEventHandling.cs:110`) 也叠栈；原设计靠"每 cycle 一条 continuation"摊平长链，但**同一节点内的兄弟仍是同步递归**。P4 的 FreeRTOS 任务栈仅几 KB ⇒ `MaxNodeDepth=64`(`Contracts.cs:539`) 是**硬约束**，续体实现应改显式帧数组而非 C 递归（§5.1）。

**CPU**：本子系统自身是 O(树大小) 的整数运算 + 选择器解析（每次遍历 combatant 列表），零浮点（除 §2.1 的 `ForwardSign`）。原始 C# 基线：1,500 个状态触发器程序的 JSON 反序列化预热 **1.6s/1.7s 每场战斗开始**(`CombatJson.cs:132-137`) ⇒ 重写后应为 **0**（预编译）。可优化点：`ApplyStatusNode` 同节点解析 `TargetSelector` 与 `SourceSelector` 各一次(`:907,918-920`)，`MarkCardInstance`/`SetCardInstanceMarkCounter` 同(`:1008-1013,1039`) ⇒ frame 内缓存同节点同次的选择结果；`ForEachCardInZone` 的 `TagFilter` 每卡查 registry(`:452-458`) ⇒ definition.Tags 预编译成 bitset。

## 7. 验收测试向量（重写后的对拍用例）

来源均在 `tests\RogueDeck.Core.Tests\Combat\`（V12 在 `tests\RogueDeck.Scenario.Tests\`）。

| # | 输入 | 期望输出 | 来源 |
|---|---|---|---|
| V1 | `Abs(Const(-3))`=`3`；`Divide(10,3)`=`3`；`Divide(10,0)` 默认=`0`；`Divide(10,0,Fault)`=抛；`Remainder(10,3)`=`1`；`Clamp(-5,0,10)`=`0`、`Clamp(15,0,10)`=`10` | 见左 | `EffectProgramConditionalTests.cs:10-15`；`EffectProgramPhase3ExpressionTests.cs:24-98` |
| V2 | `And(Const(false), SideEffectExpr)`、`Or(Const(true), SideEffectExpr)` | 右侧**未被求值**（短路） | `EffectProgramConditionalTests.cs:128-150` |
| V3 | `Conditional(cond, Then=DealDamage(EventTarget,6), Else=DealDamage(EventTarget,2))`，hero 20 / goblin 12，eventTarget=goblin | `cond=true`→goblin **6** HP；`cond=false`→**10** HP；无 Else 且 false→**12** HP | `EffectProgramConditionalTests.cs:154-210` |
| V4 | Shatter = `Causal[ ModifyDefensivePool(EventTarget,Block,-5,key="removed"), Conditional(abs(removed.AppliedDelta)>0, DealDamage(EventTarget, abs(removed.AppliedDelta))) ]`，goblin 12 HP | block **3**→HP **9**；block **5**→HP **7**；block **0**→HP **12** | `EffectProgramConditionalTests.cs:241-300`（构造 `:304-323`） |
| V5 | `Repeat(count=每次调用 callCount++ 并返回 3, body=DealDamage(EventTarget,1))`，goblin 12 HP | `callCount==1` 且 HP **9**（计数只求值一次） | `EffectProgramRepeatTests.cs:118-145` |
| V6 | `Repeat(Const(10),NoOp,maxCount=5)` / `Repeat(Const(-1),NoOp)` / `Repeat(Const(5),DealDamage(1),maxCount=5)` | 前两者**抛**；第三者不抛且 HP **7** | `EffectProgramRepeatTests.cs:192-247` |
| V7 | `ForEach(AllEnemiesOfSource, Conditional(IterationTargetHasStatus(Poison), DealDamage(IterationTarget, IterationTargetStatusStacks(Poison))))`，三哥布林 poison 3/0/5 各 12 HP | HP **9 / 12 / 7** | `EffectProgramForEachTests.cs:173-194` |
| V8 | 同上，三只各 poison 2、HP 各 10 → **8/8/8**；A=1HP+poison3（迭代 0 死亡）、C=poison4 → A **死**、B **12**、C **8** | 见左 | `EffectProgramForEachTests.cs:196-224, 226-249` |
| V9 | (a) `Repeat(4,Repeat(4,NoOp))` + `maxProgramSteps=10` → 抛；`Repeat(3,NoOp)` + `maxProgramSteps=4` → 不抛且 `ProgramStepCount==4`。(b) `MaxActiveScopes=2` + `Repeat(1,Repeat(1,NoOp))` → 抛 | 见左 | `EffectProgramExecutionLimitTests.cs:101-147, 174-196` |
| V10 | 触发器 Id `{zzz,aaa,mmm}` 全 `priority=0`，按 zzz→aaa→mmm 注册；以及 `aaa p=5`、`zzz p=0` | 触发序 **["test.aaa","test.mmm","test.zzz"]**；以及 **["test.zzz","test.aaa"]** | `TriggeredProgramParityTests.cs:334-353, 355-373` |
| V11 | `Causal[DealDamage(hero,5), DealDamage(hero,10)]` + "英雄受伤则获 10 格挡"反应，hero 20 HP；同结构换 batch `Sequence` | Causal → **15** HP；batch → **5** HP | `EffectProgramCausalSequenceTests.cs:46-71, 74-90` |
| V12 | `CombatNodeModel` → `Build<CardPlayContext>` → `Classify`；以及 `Repeat(2, dealDamage(allEnemies,Event))` 经 `CombatJson` 序列化+反序列化后再 `Classify` | 模型**结构相等**（往返恒等） | `tests\RogueDeck.Scenario.Tests\CombatProgramModelTests.cs:43-52, 54-69` |
| V13 | `ApplyStatus(SourceSelector=Explicit(已死敌人))` | **不发请求**（不回落行动者），链继续 | `NodeExecutors.cs:917-929` |
| V14 | `PlayCard` 且卡片解析 null；`RepeatUntil(stopCond 恒假, body, maxIterations=32)` | 存 `OrderedTargetOutcomes<PlayCardOutcome>.Empty` 并继续(`:2050-2057`)；体跑 **32 次**后**正常完成**不抛(`:351-355`) | `NodeExecutors.cs` |
| V15 | `RandomTargetSelection(candidates=3,count=2)`，`seed=7,step=0`；同名结果键在两个 Sequence 兄弟各生产一次 | 取 `CreateShuffledIndexes(3,7,0)` 前 2、`step` 变 1(`:527-540`、`CombatRandom.cs:5-56`)；构建期抛 "produced by more than one operation in the same scope"(`Contracts.cs:687-701`) | 同左 |

**对拍执行建议**：① C# 侧生成 golden：`{程序 AST, 初始战斗快照, 输入序列}` → `{每步战斗状态哈希, trace 事件序列}`；仓库已有 `Combat\CombatStateHasher.cs`（含 `seed=`/`step=`）可作摘要。② 重写侧按同输入跑，比对**状态哈希 + 规范化 trace**（`Trace.cs:19-42` 的 8 种 kind + `ExecutionId/NodePath/ScopeId/ChainId`）⇒ 重写侧**必须保留这四元身份**（可换整数）。③ 三条最容易被"顺手优化掉"的语义必须专门覆盖：V5（计数单次求值）、V10（注册顺序无关）、V11（causal/batch 差异）。
