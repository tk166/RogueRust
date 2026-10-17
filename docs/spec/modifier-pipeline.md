# 数值修饰管线与触发式效果 —— 重写规格书

**源仓库**：`D:\Vibe\sts-tui\ref\RogueDeck-Core`（C# / .NET 10 / MIT）
**目标**：把「卡面上的一个数字」变成「状态上真实发生的改变」的这条链，重写为不依赖 .NET、可跑在
ESP32-P4（双核 RV32 @360MHz、单精度 FPU、592KB SRAM / 32MB PSRAM）或 RL 训练环境的内核。
**证据约定**：`文件:行号` 相对仓库根目录；行为性断言优先引测试。范围仅限战斗内数值管线与触发式效果。

## 1. 职责与边界

### 1.1 这条链负责什么

把「效果请求（Effect Request）」落到状态上，并保证**同一份状态 + 同一串答案 ⇒ 同一结果**（纯函数式回放，
`CombatStateSnapshot.cs` / `CombatStateHasher.cs`）。三个可观察输出：数值（HP/防御池改变量，`DamageEffects.cs:162-169`）、
**事件**（`CombatEvents.cs`，触发器唯一的输入，不是渲染旁路）、日志与 trace（纯观察，`CombatState.cs:175-184`）。

### 1.2 三件不同的事，别混成一件

| 机制 | 干预时机 | 能否取消 | 返回值 | 注册位置 |
|---|---|---|---|---|
| **修饰器 Modifier** | 数值成形中（同步） | 不能取消，只能改数 | `int` | registry 排序数组 |
| **拦截器 Interceptor** | 命中发生前（同步） | 能取消/替换/重定向 | Allow/Block/Replace/Prevent/Redirect | registry 排序数组 |
| **触发器 Trigger** | 事件已发生后（异步） | 不能取消已发生的事 | 无（跑 program，往队列塞新请求） | registry 定义 + 运行期临时规则 |

**关键区别**：修饰器与拦截器都在**当前 effect 的 `Resolve` 调用栈内同步执行**；触发器在**事件队列**里跑，
比产生它的命中晚至少一个队列周期（§3 S9/S10）。任何"边算边触发"的实现都会改变观测顺序。

### 1.3 不属于本链的

目标选择（`CombatantTargetSelectors.cs`）在请求**入队之前**完成，属 recipe / effect program node 层；
卡牌可打出性（`ICardPlayValidator`）是与数值管线平行的另一组排序数组；回合推进/抽牌/回合边界
（`CombatTurnProcessor`）只决定"什么时候往队列里塞什么"。

### 1.4 必须原样保留的语义 vs 可以简化

| 必须保留（否则就是另一个游戏） | 依据 | 可以简化 |
|---|---|---|
| Source → Target → Global 的**阶段序** | `DamageEffects.cs:7-13` | 阶段数可砍到 2（Global 在标准内容里是空的） |
| 同 pipeline 内**加法先于乘法**（Priority 100 < 200） | `StandardCombatPackage.cs:280-283,428-431` | Priority 数值可压缩成 0/1/2 |
| 排序键是 `(Priority, 稳定次级键)`，**不是注册序也不是施加序** | `CombatDefinitionRegistryBuilder.cs:584-590`；`PassiveModifiers.cs:179-185` | 次级键可用整数而非字符串 |
| 伤害修饰默认只对 `DamageKind.Direct` 生效，DoT/Reflected 不受影响 | `PassiveModifiers.cs:87`；`VulnerableStatusTests.cs:87-131` | 可改成显式位掩码 |
| 全被格挡仍发 `DamageDealt(HealthDamage=0)`，且仍算"造成伤害的动作" | `DamageEffects.cs:171-183`；`StatusEffects.cs:523-524` | 无 |
| 触发式反应在**段与段之间**结算（多段攻击观感的地基） | `MechanicalChallengeTests.cs:353-385`；`CombatEventHandling.cs:104-111` | 无 |
| 深限 + 重入抑制两套循环保护 | `CombatEffectChain.cs:10-18,49-72`；`DamageEffects.cs:207` | 上限数值可调（4/3/64），机制必须留 |
| 状态三轴 `Stacks/Duration/Charges` 独立，合并规则 `+= / max / +=` | `StatusEffects.cs:135-139` | 内容不区分充能与时，可砍成两轴 |
| Down / 胜负由事件驱动 | `StandardCombatPackage.cs:149-150` | 可改直调，但会丢掉"先触发后倒地"的顺序 |

## 2. 数据结构

### 2.1 修饰器家族

都是「读上下文 → 返回新数值」的纯函数对象，注册后按 `(Priority, Id)` 排成不可变数组。

| 接口 | 上下文 | 关键成员 | 排序键 | 出处 |
|---|---|---|---|---|
| `IDamageAmountModifier` | `DamageAmountModificationContext` | `ModifierId`(string)、`Priority`、`Stage` | `ModifierId` | `DamageAmountModifiers.cs:7-39`；builder `:186,584-590` |
| `IBlockAmountModifier` | `BlockAmountModificationContext` | `ModifierId`、`Priority` | `ModifierId` | `BlockAmountModifiers.cs:3-20`；builder `:264` |
| `ICardCostModifier` | `CardCostModificationContext` | 同上 + `PricesActions` | `ModifierId` | `PassiveModifiers.cs:271-289` |
| `IDamageSplitter` | `DamageSplitContext` | `SplitterId`、`Priority` → `None/Split` | `SplitterId` | `DamageSplitters.cs:4,14-56`；builder `:251` |
| `IPreDownInterceptor` | `PreDownInterceptionContext` | `InterceptorId`、`Priority` → `Allow/Prevent/Redirect` | `InterceptorId` | `PreDownInterceptors.cs:14-62`；builder `:238` |
| `IStatusApplicationInterceptor` | `StatusApplicationInterceptionContext` | `ModifierId`、`Priority` → `Allow/Block/Replace` | `ModifierId` | `StatusApplicationInterceptors.cs:12-62`；builder `:225` |

标准内容里这三个数值家族**已经没有 bespoke 类**，只剩四个通用折叠器（全 Priority 1000）：`DeclarativePassiveDamageModifier`
(Source/Target)、`DeclarativePassiveBlockModifier`、`DeclarativePassiveCostModifier`（`PassiveModifiers.cs:222-289`，
注册于 `StandardCombatPackage.cs:47-50`）→ **整条数值管线 90% 的数据可以静态化成常量表。**

### 2.2 声明式被动修饰 `PassiveModifierSpec`

挂在 `StatusDefinition.PassiveModifiers`（`StatusDefinition.cs:34,101`），不可变。

| 字段 | 含义 | 默认 | 行号 |
|---|---|---|---|
| `Pipeline` | DamageDealt / DamageReceived / BlockGain / CardCost / OutgoingStatusApplicationStacks / TurnStartDraw | — | `PassiveModifiers.cs:16-30` |
| `Operation` | AddPerStack / AddFlat / ScalePercent / ClampMax | — | `:33-44` |
| `Magnitude` / `Priority` | 幅值 / 折叠序 | — / **100** | `:83-84` |
| `RestrictDamageKind` | 只对某伤害种类生效 | **Direct** | `:87` |
| `AppliesToStatusId` / `RestrictElement` / `RestrictSourceCardTag` | 施加目标 / 元素 / 来源卡标签 门控 | null | `:90,97,101` |
| `MagnitudeExpression` | 由活状态算幅值（必须纯） | null | `:93`；`MissingHealthMagnitude` `:57-73` |
| `OncePerAction` / `OncePerTurn` | 每动作 / 每回合最多贡献一次 | false | `:107,113` |

标准内容的四个 spec（这就是"力量和易伤谁先乘"的全部真相）：

| 状态 | Pipeline | Operation | Magnitude | Priority | 出处 |
|---|---|---|---|---|---|
| Strength | DamageDealt | AddPerStack | 1 | **100** | `StandardCombatPackage.cs:428-431` |
| Weak | DamageDealt | ScalePercent | 75 | **200** | `:280-283` |
| Vulnerable | DamageReceived | ScalePercent | 150 | **300** | `:339-342` |
| Dexterity | BlockGain | AddPerStack | 1 | **100** | `:360-363` |
| Frail | BlockGain | ScalePercent | 75 | **200** | `:318-321` |

### 2.3 标准拦截器（顺序即契约）

Artifact(**100**) 用 1 充能吃掉一次 Debuff 施加（`StatusApplicationInterceptors.cs:64-100`）；禁止令(**200**) 按
`StacksPerStack` 逐层抵扣，或 `RefusesWholeApplication` 用 1 层全否（`:113-191`）；放大(**300**) 让下次施加
+`AddStacks` 层，花掉 `StacksSpent` 层（`:205-273`）。注册序 `StandardCombatPackage.cs:71-73`；
注释 `:117,209` 写明"100→200→300 是为了让全否先发生、被拒绝的永不被放大"。

### 2.4 触发器的注册结构

```
ITriggeredEffectDefinition                     # TriggeredEffects.cs:14-27
  Id:struct(string) | EventType:Type | GatingStatus:StatusDefinitionId? | ReentryPolicy | GetEffectProgramRoot()
TriggeredProgramDefinition<TEventContext>      # TriggeredProgramDefinition.cs:11-64
  Priority:int | Program:EffectProgram<T>（数据树，不是代码） | Filters:IReadOnlyList<ITriggeredProgramFilter<T>>
  ContextFactory:Func<CombatState,Registry,ICombatEvent,TContext?>      # ⚠ 闭包
  BuildContext  :Func<TContext,TriggeredEffectActionBuildContext>       # ⚠ 闭包
```

`TriggeredProgramContextAdapters`（`:44-175`）为每个事件类型提供一个**静态适配器**（TurnStarted / TurnEnded /
RoundStarted / RoundEnded / DamageDealt / DamageReceived / Healed / StatusApplied / StatusApplicationBlocked /
StatusApplicationAmplified / …）：`Define(...)` 出定义、`CreateHandler()` 出配套处理器（`:22-38`）。标准包注册了
**58 个事件处理器**（`StandardCombatPackage.cs:121-190`），其中 **2 个**是常驻触发器定义（`standard.rage_block_on_attack_played`
`:404-416`、`standard.skill_combo_draw` `:388-402`）。

**临时规则**（运行期安装，不在 registry）：`TemporaryTriggeredProgram`（`TemporaryTriggeredProgram.cs:57-162`）带
`Definition + RemainingActivations + ExpiresAfterRound/Turn + OwnerCombatantId + ExpiryEffects`；生命周期由
`TemporaryRuleLifetime`（`:12-51`）描述：`OneShot` / `Activations(n)` / `UntilEndOfRound(r)` / `UntilEndOfTurn(r,t)` /
`UntilOwnerRemoved`；激活记在 `RecordActivation()`（`:118-126`）。

### 2.5 状态的表示：层数 / 持续时间 / 充能是三个独立轴

`StatusInstance`（`StatusInstance.cs:3-114`）持有 `Stacks / DurationTurns / Charges / PendingTurns`（均 ≥ 0）、
`AppliedRound/AppliedTurn`、`Visibility/Polarity`、`_tags:HashSet<TagId>`、`_counters:Dictionary`。

| 轴 | 谁在写，合并规则 | 到 0 时 | 出处 |
|---|---|---|---|
| Stacks | 施加合并 `+=`；`ApplyDelta` | 由正降到 0 ⇒ **移除实例** + `StatusExpired` | `StatusEffects.cs:135-139,819-850` |
| DurationTurns | 施加合并取 **max**；拥有者回合结束 -1 | 减到 0 ⇒ 移除 + `StatusExpired` | `:137,333-377,379-406` |
| Charges | 施加合并 `+=`；Artifact / Phoenix 消耗 | 减到 0 ⇒ 移除 + `StatusExpired` | `:138,745-802` |
| PendingTurns | 拥有者回合开始 -1，到 0 抛 `StatusActivated` | — | `:409-447` |

`CombatantState.Statuses` **只列活跃实例**（`IsActive ⇔ PendingTurns==0`），延迟中的只在 `PendingStatuses` /
`AllStatuses`（`CombatantState.cs:24-33`，`_activeCount` 免分配快路径）。`StatusDefinition` 用
`UsesStacks/UsesDuration/UsesCharges`（`StatusDefinition.cs:16-18`）声明"用哪几个轴"，`StackingBehavior`（`:24`）
决定合并还是每次新实例。

### 2.6 队列与链上下文

`CombatState`（`CombatState.cs:5-11`）持有三组队列：`_pendingEffects` + `_pendingEffectChains` +
`_pendingEffectOwners`（三平行）、`_pendingEvents` + `_pendingEventChains`、以及
`_pendingContinuations : Queue<Action<CombatState>>`（"段间结算"机制）。出队必须三个队列对齐（`:429-440`）。
`CombatEffectChainContext`（`CombatEffectChain.cs:8-84`）带 `Id / TriggerDepth=已进入触发器数 / MaximumTriggerDepth=64`（`:10`）。
快照/hash **不含**队列与 action scope（`:92-95`）。

## 3. 算法：一次伤害从卡面数字到扣血

### 3.0 有序阶段总览

```
S0  受理与契约校验    负数 ⇒ 抛异常；目标不存在 ⇒ 抛异常
S1  分担短路          IsRedistributedShare ⇒ 跳过 S2 与 S3
S2  数量修饰管线      Source 阶段 → Target 阶段 → Global 阶段
S3  分裂              splitter 命中即 return，本次命中不再落地
S4  防御池吸收        按 (AbsorbPriority, Id) 依次 drain；IgnoresBlock ⇒ 全跳
S5  生命损失计算      newHealth = max(0, hp - remaining)
S6  死亡前拦截        仅当 新HP==0 ∧ 原HP>0 ∧ RedirectionDepth<4
S7  提交写入          Health.SetCurrent；确定 Overkill
S8  输出              OutcomeSlot / 日志 / 动作记账 / 入队两个事件
S9  队列循环          effects 全排空 → events 全排空 → continuation
S10 事件分派          handler 按注册序；触发器按 (Priority,Id)；新 effect 下一 cycle 才解析
```

**四个短阶段**（S0/S1/S5/S7，全在 `DamageEffects.cs` 内）：

| 阶段 | 行为 | 行号 |
|---|---|---|
| **S0** | 只读 `Amount`，**不读状态**；`Amount<0` ⇒ `ArgumentOutOfRangeException`。无短路 | `:45-54` |
| **S1** | `IsRedistributedShare==true` ⇒ 跳过 S2/S3，直接带最终值进 S4（否则对称链接会级联） | `:59-61,66-67,29-32` |
| **S5 / S7** | `newHealth = max(0, hpBefore - remaining)`（纯算术）；`healthDamage = before - newHealth`；`overkill = intercepted ? 0 : remaining - healthDamage` | `:103-104,138-141` |

### S2 · 数量修饰管线 —— `DamageEffects.cs:273-320`

```
current = request.Amount
for stage in [Source, Target, Global]:          # 硬编码数组 :7-13，不是按 Priority 全局排
    for m in registry.damage_amount_modifiers:  # 已按 (Priority, ModifierId) 排好
        if m.Stage != stage: continue
        current = max(0, m.ModifyDamageAmount(ctx, current))    # :312
```

**谁参与**：Source 阶段读**出手者**状态；Target 阶段读**承受者**状态；Global 两方都能读。上下文带
`Combat/Registry/TargetCombatant/SourceCombatant/SourceCardId/Kind/RequestedAmount/Element`
（`DamageAmountModifiers.cs:14-24`）。`SourceCombatant` 可为 null（无来源伤害），此时声明式折叠直接返回原值（`PassiveModifiers.cs:248-249`）。

**声明式折叠内部**（`PassiveModifiers.cs:124-217`）——第二层门控与排序：

```
if amount <= 0: return amount                      # :137-138 唯一的早退短路
for 每个 该战斗员状态实例的分组(按 DefinitionId):
    totalStacks = 该定义所有实例层数之和             # :148（多实例先求和再乘）
    for spec in 定义的 PassiveModifiers:
        Pipeline 不匹配 ⇒ 跳过
        伤害 pipeline 且 RestrictDamageKind ≠ 本次 Kind ⇒ 跳过      # :155
        AppliesToStatusId / RestrictElement / RestrictSourceCardTag 门控   # :158,162,168
        收入 applicable，键 = (spec.Priority, statusId, specIndex)
sort by (Priority, statusId 序数, specIndex)        # :179-185
for e in applicable:
    OncePerAction / OncePerTurn ⇒ 先 claim，抢不到就跳过（claim 在所有门控之后）   # :191-201
    magnitude = MagnitudeExpression?.Evaluate(..) ?? Magnitude                    # :205
    current = op(current, magnitude, stacks)                                      # :206-213
return max(0, current)                              # :216
```

运算精确语义（**全整数**）：`AddPerStack` = `current + magnitude*stacks`；`AddFlat` = `current + magnitude`；
`ScalePercent` = `current * magnitude / 100`（**整数除法向下取整**）；`ClampMax` = `min(current, max(0,magnitude))`（0 合法 ⇒ 可完全抹掉，`:39-43,211`）。

**短路与失败**：`amount<=0` 立即返回；每个修饰器返回值被 `max(0,·)` 夹住 ⇒ 管线不可能产出负数；修饰器
**不能取消**一次命中，把数值降到 0 是唯一的"否决"（后续阶段照走，会发 `HealthDamage=0` 的事件）。
`OncePerAction` 账本在 `CombatState._actionScopes`（`CombatState.cs:96-122`）：没有打开的动作作用域时
`TryClaimOnceThisAction` 恒 false ⇒ 状态跳伤（DoT）永远吃不到"每动作一次"的加成。

### S3 · 分裂 —— `DamageEffects.cs:66-68,209-247`

仅在 `!IsRedistributedShare` 时按 `(Priority, SplitterId)` 问 `registry.GetDamageSplitters()`，**第一个返回 `Split`
的胜出**（`:223-244`）；读 `DamageSplitContext{ Target, Amount(修饰后), SourceCombatantId }`（`DamageSplitters.cs:37-42`）。
每个 `share.Amount>0` 作为**新请求**入队（`IsRedistributedShare=true`，继承 `SourceCombatantId/SourceCardId/Kind/IgnoresBlock`，
**不继承** `OutcomeSlot/Element/RedirectionDepth`），**原命中立即 `return`**（`:68`）⇒ 原目标不掉血、不发事件、
不写 OutcomeSlot。标准包**没有**注册 splitter。

### S4 · 防御池吸收 —— `DamageEffects.cs:70-101`

```
if !IgnoresBlock:
    for poolDef in registry.GetDefensivePoolsInAbsorbOrder():   # AbsorbPriority 升序，(Id 序数) 次级
        if remaining <= 0: break
        若目标没有此池 / 池值 <= 0: continue
        absorbed = min(pool.Current, remaining)
        只记【第一个】吸收池的 before/after（trace 用）
        pool.SetCurrent(pool.Current - absorbed); blockedDamage += absorbed; remaining -= absorbed
```

吸收序在构建 registry 时预计算一次（`CombatDefinitionRegistry.cs:68-71`）；标准只有 Block，`AbsorbPriority=0`
（`StandardCombatPackage.cs:54-55`）；测试证明自定义池可以反超 Block（`DefensivePoolAbsorptionTests.cs:40-55`）。
trace 语义：`BlockPoolId/Before/After` 只报**第一个**吸收的池，`BlockedAmount` 是**所有池之和**（`:72-74,90-98`），
单池时二者重合。短路：`IgnoresBlock=true`（真伤）跳过整个循环且池值不动（`DefensivePoolAbsorptionTests.cs:57-72`）；
`remaining<=0` 中途 break。无失败路径。

### S6 · 死亡前拦截 —— `DamageEffects.cs:110-136,249-271,207`

**触发条件三者全满足**：`newHealth==0` ∧ `healthBefore>0` ∧ `RedirectionDepth<4`（`MaxRedirectionDepth` `:207`）。
按 `(Priority, InterceptorId)` 问 `registry.GetPreDownInterceptors()`，**第一个非 `Allow` 的胜出**（`:263-268`）；
读 `PreDownInterceptionContext{ Target, LethalAmount(格挡后剩余伤害), SourceCombatantId }`（`PreDownInterceptors.cs:42-48`）。
`Allow` 照常倒地；`Prevent(h)` ⇒ `newHealth=clamp(h,1,Max)` 且不产生新命中；`Redirect(to)` ⇒ 原目标
`newHealth=healthBefore`（**完全免伤**），**整笔剩余伤害**作为新命中入队给 `to` 且 `RedirectionDepth+1`（`:130-134`），
新命中重走 S0→… 但不再带 `OutcomeSlot`。拦截器可在 `Intercept` 里**同步改状态**（Phoenix 消耗充能，
`PreDownInterceptionTests.cs:20-29`）；仅发生在"即将从活着变成 0"时。

### S8 · 输出（顺序即语义）—— `DamageEffects.cs:144-203`

1. **Trace**（仅当挂了 listener；`tracing` 在 S0 快照一次 `:53`）：带 `BaseAmount/ModifierSteps/AmountAfterModifiers/`
   `池 before-after/HealthLost/IgnoresBlock/SourceStatusId`；`ModifierSteps` 只在 tracing 时收集（`:58-61`）⇒ 生产路径零分配。
2. **OutcomeSlot**（`:162-169`）：`RequestedAmount/BlockedAmount/HealthLost/PreviousHealth/NewHealth/Overkill`。
3. **日志**：一行 `DamageDealt` 文本（`:171-173`）。
4. **动作记账**（`:178-183`）：`Kind==Direct` ∧ 双方在 ∧ **不同队** ⇒ `NoteActionDealtDamage()`；注释明说
   **被格挡也算造成伤害**，状态跳伤不算（不在动作作用域里）。
5. **先入队 `DamageDealtCombatEvent`、再入队 `DamageReceivedCombatEvent`**（`:185-203`）。完全被格挡时
   `HealthDamage=0` 但事件照发：触发器看得到，反伤（Thorns）看不到（`StatusEffects.cs:523-524`）。

### S9 · 队列循环 —— `CombatEventHandling.cs:81-115`

```
while (有待处理 effects || events || continuations) && Result == Ongoing:
    若 cycle >= 1024 ⇒ 抛异常（附带"谁在循环"报告 :121-141）
    ResolvePendingEffects(..)     # 排空 effect 队列（新入队的在同轮继续）
    ResolvePendingEvents(..)      # 排空 event 队列（handler 里新入队的 event 同轮继续）
    if 两队列都空 && 有 continuation: 跑一个 continuation
```

**顺序铁律（测试 `CombatQueueProcessorTests.cs:56-80`）：同一 cycle 内 effect 先于 event。** 推论：事件
handler 里 `EnqueueEffect` 的请求要等**整个事件队列排空**才解析（下一 cycle）；effect 解析时入队的 event
要等**整个 effect 队列排空**才分派 ⇒ **触发器不能"边算边跑"**。

### S10 · 事件分派 —— `CombatEventHandling.cs:37-73` + `TriggeredProgramDefinition.cs:69-198`

```
handlers = registry.GetCombatEventHandlers(evt.GetType())   # 按【注册顺序】的数组
foreach handler: handler.Handle(combat, registry, evt)      # 无优先级
```

`DamageDealt` 在标准包挂了 **4 个** handler（`StandardCombatPackage.cs` 注册顺序）：`TrackDamageDealtThisTurnHandler`
(`:144`) → `TriggeredDamageOnDamageDealtHandler`(`:148`，给攻击者入队一笔 `Kind=Reflected` 伤害 `:512-552`) →
`MarkCombatantDownedOnZeroHealthHandler`(`:149`，HP==0 ⇒ 入队 Downed) → `TriggeredProgramCombatEventHandler<DamageDealt,…>`
(`:157`，跑所有注册触发器)。**⇒ 同事件的多 handler 之间没有排序键，顺序 = 注册顺序**（builder 就是 `List.Add`，
`:334-354`）。这是隐形但真实的契约：重排注册顺序会改变可观察行为。

```
defs = (缓存的注册触发器) ⊕ (临时规则) 再按 (Priority, Id.value) 排序        # :88-106
for (definition, instance) in defs:
    if 当前链已含它 且 策略=Suppress ⇒ 跳过（记 trace）                      # :117-123
    if 链深 >= 64 ⇒ 抛异常                                                   # :128-135
    if 有 GatingStatus 且没人戴着（非 tracing）⇒ 跳过                        # :139-144
    ctx = ContextFactory(..); null ⇒ 跳过；Filters 全部 Matches 才继续        # :148-161
    开新链（TriggerDepth+1）⇒ 执行 program ⇒ 入队过东西则记 activity        # :166-177
    临时规则：RecordActivation() + 发 TemporaryRuleActivated 事件            # :179-192
```

`carried`（"谁戴着门控状态"）惰性构建，**每有一个触发器真正跑过就置空重建**（`:112,141,174`），因为这些
program 可能刚给出别人正在等的状态。**因果 vs 顺序**：`SequenceEffectNode` 一次性 dispatch 所有子节点
（`EffectProgramNodeExecutors.cs:181-213`）；`CausalSequenceEffectNode` 等每个子节点完成才继续（`:215-`），
"完成"走 `combat.EnqueueContinuation(onComplete)`（`:177,262,…`），continuation 只在**两个队列都排空后**才执行
（`CombatEventHandling.cs:107-111`）⇒ **段与段之间完整结算所有反应**（`RepeatEffectNode` 同理，
`MechanicalChallengeTests.cs:352`）。这正是向量 #13 成立的原因。

### 3.2 对照：格挡 / 治疗 / 状态施加

| 管线 | 阶段 | 出处 |
|---|---|---|
| **GainBlock** | 受理(负数抛异常) → 单阶段修饰循环（`GetBlockAmountModifiers()`，**无 stage**，声明式折叠 `BlockGain`）→ `modifiedAmount==0` 视为空操作但仍写 OutcomeSlot → 无池则建、有池则 `+=` 并夹到 `int.MaxValue` → 日志 → `BlockGained` 事件（**只有真正落地才发**） | `DefensivePoolEffects.cs:11-105,129-166` |
| **Heal** | 受理(负数抛异常) → `newHealth = min(Max, hp+amount)`（`long` 中间量防溢出）→ 日志 → `Healed` 事件。**无任何修饰器/拦截器挂钩** | `DamageEffects.cs:323-377` |
| **ApplyStatus** | 受理(三轴负数抛异常 `StatusEffects.cs:55-62`) → 拦截器链（深度<3；Block ⇒ 写 Blocked 结果并返回；Replace ⇒ 入队替换、深度+1、原请求作废）→ 出手方 `OutgoingStatusApplicationStacks` 折叠（Catalyst 类放大 `:113-120`）→ 计算 `PendingTurns`（取目标身上所有延迟规格的最大值 `:252-265`）→ 可合并且非延迟则合并（层数/充能相加、时长取 max `:126-181`），否则新实例（`:183-199`）→ 延迟中的**不发** `StatusApplied`（`:215-217`）→ 发 `StatusAppliedCombatEvent` | `StatusEffects.cs:43-324` |
| **DoT 一跳** | 回合开始把每个带 `DamageOverTimeTag` 的状态入队一个 tick（`:449-474`）→ tick 在**解析时**读层数（不是入队时），产生 `Kind=DamageOverTime` 的 `DealDamage` 且带 `SourceStatusId`（`:480-510`） | 同上 |

## 4. 顺序契约

### 4.1 四条互不相干的排序轴

| # | 排序对象 | 键 | 证据 |
|---|---|---|---|
| A | 修饰器 / 拦截器 / 分裂器 | `(Priority 升序, Id 序数)`，构建期排一次，运行期不再排 | `CombatDefinitionRegistryBuilder.cs:186,225,238,251,264,584-590`；`ModifierPipelineTests.cs:16-84` |
| B | 同一 pipeline 内的 spec 折叠 | `(spec.Priority, statusId 序数, specIndex)` | `PassiveModifiers.cs:179-185` |
| C | 触发器 | `(Priority 升序, Id.value 序数)`，注册触发器与临时规则合并后再排 | `TriggeredProgramDefinition.cs:88-106`；`TriggeredProgramParityTests.cs:334-373` |
| — | 同事件的多个 handler | **无键 ⇒ 注册顺序** | `CombatDefinitionRegistryBuilder.cs:334-354`；`CombatEventHandling.cs:58-63` |

三条轴在不同层生效：A 决定"哪个修饰器对象先跑"，B 决定"折叠器内部哪个 spec 先跑"，C 决定"哪个触发器先跑"。
**没有一处的排序键是注册顺序或施加顺序**（B 用状态定义 id 而不是实例顺序，这正是"百分比与加法能稳定复合"的原因，`PassiveModifiers.cs:77-79`）。

### 4.2 加法与乘法

**同 pipeline 内加法先于乘法**（`AddPerStack` Priority 100 < `ScalePercent` 200）。标准内容的完整公式
（`DamageKind.Direct` 且双方在场）：

```
dmg = base
dmg = dmg + Strength层数            # Source/100
dmg = dmg * 75 / 100   (若有 Weak)  # Source/200
dmg = dmg * 150 / 100  (目标有易伤)  # Target/300
```

**双标 bug 的两个经典形态**：

1. **把易伤做成 Source 阶段的乘法并和力量混排** ⇒ `base*1.5 + strength`。`ModifierPipelineTests.cs:102-122` 把
   错序答案写在注释里：base 5 + 力量 2 + 易伤 ⇒ 正确 `(5+2)*1.5=10`（HP 100→90），错序 `5*1.5+2=9`；
   `:124-143` 另一条：base 10 + 虚弱 + 易伤 ⇒ `10*0.75=7`，`7*1.5=10`（HP→90）。
2. **加法与乘法的相对优先级弄反**（例如让虚弱 Priority=50）。`VulnerableStatusTests.cs:133-170` 给出三件套权威
   值：base 6、力量 2、虚弱、易伤 ⇒ `(6+2)=8 → *75/100=6 → *150/100=9` ⇒ HP 12→**3**。换成 base 7、力量 3 就能
   看出差别：正确 `(7+3)*0.75=7 → *1.5=10`，错序 `7*0.75=5 → +3=8 → *1.5=12`。**必须按 Priority 逐步折叠。**

**截断点也必须一致**：每步都是整数除法向下取整（`PassiveModifiers.cs:210`）。`BlockAmountModifierTests.cs:104-130`
（`5*75/100=3`）钉住乘法截断，`:132-166`（`(5+2)*75/100=5.25→5`）钉住加法先于乘法。

### 4.3 拦截器与触发器的相对时序

| 时刻 | 谁在跑 | 说明 |
|---|---|---|
| effect 解析中（同步） | 修饰器 → 分裂器 → 防御池 → 死亡前拦截 | 一整个 `Resolve` 栈内，只影响"这一次命中" |
| effect 解析中（同步） | **状态施加拦截器** | 在 `ApplyStatusEffectHandler.Resolve` 内，不是独立事件 |
| 同一 cycle 稍后（异步） | 事件 handler（含**触发器**） | effects 全排空 → events 全排空（`CombatEventHandling.cs:104-105`） |
| 下一 cycle | 事件 handler 入队的 effect | 例：反伤、`Downed` 引发的爆炸 |

状态施加的顺序契约：Artifact(100) 全否 → 禁止令(200) 抵扣/全否 → 放大(300)。放大是 `Replace`，会**重新入队**
并**再走一遍拦截链**，用 `ApplyStatusEffectRequest.Amplified` 标记防止二次放大，替换链深度上限 3
（`StatusEffects.cs:48,100-104,277-278`）；"被拒绝的永不被放大"由 `StatusAmplificationTests.cs:67-80` 钉住。
禁止令内部顺序是 `(Prevention.Priority 降序, 实例年龄升序)`（`:128-155`），由 `PreventionPriorityTests.cs:51-62` 钉住；
消耗是**同步**的（`:181` 直接 `ApplyDelta`，不走队列），否则同一次排空里的第二次施加会看到还没扣的层数（`:110-112`）。

### 4.4 检查表：搞错就会出现"双标"

| 搞错的事 | 症状 |
|---|---|
| stage 顺序（Target 抢在 Source 前） | 力量/易伤组合数值漂移（§4.2 #1） |
| 同 pipeline 内不按 Priority、而按"状态施加顺序"折叠 | 同一场战斗重放结果不一致 |
| 触发器同步跑（不走队列） | 多段攻击每段反应次序全变；反伤在段内命中而非段间 |
| event handler 当成有优先级 | 重排注册顺序即改变行为（`StandardCombatPackage.cs:144-157`） |
| 用 `max(0,·)` 之外的方式夹负数 | `ClampMax(0)` 与"降到 0"语义分不开（`PassiveModifiers.cs:39-43,211`） |
| 合并时长用 `+=` 而不是 `max` | 每回合重复施加同一 buff 会永久续期（`StatusEffects.cs:137`） |
| 让延迟中的状态进 `Statuses` | "可见但惰性"变成"立刻生效"（`CombatantState.cs:24-33`） |
| 把 DoT/反伤也当 Direct 处理 | 力量会加成中毒、易伤会放大反伤（`VulnerableStatusTests.cs:87-131`） |
| once-per-action 在门控之前 claim | 本该不适用的 spec 被白烧掉配额（`PassiveModifiers.cs:191-201`） |

## 5. 宿主依赖清单（必须重新设计的东西）

| # | 依赖 | 出处 | 为什么在 no_std 上是问题 | 替代方案 |
|---|---|---|---|---|
| 1 | **委托闭包** `Func<…,TContext?>` / `Func<TContext,BuildCtx>` | `TriggeredProgramDefinition.cs:19-20,53-54`；`TriggeredProgramContextAdapters.cs:30-34,46-175` | 捕获环境的函数对象 = 分配 + trait object | 每事件类型一个 `EventKind` 枚举 + `fn build_ctx(evt, out:&mut CtxBuf)->bool` 静态函数表；上下文用 `#[repr(C)]` 固定布局 struct |
| 2 | **`Type` 作字典键（反射式分派）** | `CombatDefinitionRegistry.cs:14,31,179-192,215-229`；`CombatEffectResolver.cs:14-16`；`CombatEventHandling.cs:58` | 运行期类型身份不可用 | 编译期枚举 `RequestKind`/`EventKind`，表就是 `[Handler; N]`，索引即分派 |
| 3 | **虚调度 + 堆分配结果对象**：六个修饰器/拦截器接口 + `DamageSplitResult`/`PreDownInterceptionResult`/`InterceptionResult` 密封层级 | `DamageAmountModifiers.cs:26-39`；`DamageSplitters.cs:14-33`；`PreDownInterceptors.cs:14-39`；`StatusApplicationInterceptors.cs:12-46` | 每次分裂/拦截 `new` 一个结果对象；接口调用不可内联 | `enum Outcome{Allow,Block,Prevent{h},Redirect{id},None,Split{len,shares}}` 值类型；修饰器退化成 `(Pipeline,Op,Magnitude,Priority,gates)` 数据行 + `match` |
| 4 | **`ConditionalWeakTable` 缓存** | `TriggeredProgramDefinition.cs:75-76,88-93` | 弱引用 / GC 概念不存在 | 构建期算好每个 `EventKind` 的排序切片**索引区间**，运行期只读 |
| 5 | **LINQ**（GroupBy/Sum/Where/OrderBy/FirstOrDefault/Any/SelectMany/OfType） | `PassiveModifiers.cs:142-148,176-185`；`StatusEffects.cs:128-129,256-262,460,535`；`TriggeredProgramDefinition.cs:89-92,141` | 每个算子可能分配迭代器/闭包；`GroupBy` 一次建一个 Lookup | 手写双层循环 + 定容栈数组；排序用插入排序（k 通常 < 8）；**`GroupBy` 改成按定义 id 扫两遍** |
| 6 | **字符串键**：`ModifierId`/`SplitterId`/`InterceptorId` 参与排序；once-claim 键是 `$"{pipeline}\|{statusId}\|{specIndex}\|{id}"` | `DamageAmountModifiers.cs:30`；`DamageSplitters.cs:51`；`PreDownInterceptors.cs:57`；`PassiveModifiers.cs:194,200`；builder `:588`；`CombatState.cs:102,121-122` | 字符串比较 + 格式化分配 | Id → 编译期 `u16`；claim 键打包成 `u64` 位域（pipeline:4 \| status:16 \| spec:8 \| combatant:16） |
| 7 | **异常作为控制流** | 参数校验 `DamageEffects.cs:50-51`、`StatusEffects.cs:55-62,340,759`；深度超限 `CombatEffectChain.cs:64-72`；循环上限 `CombatEventHandling.cs:53-56,99-102` | `panic!` 会终止整局；嵌入式要可恢复 | **契约违例**（负数/未注册）→ `debug_assert!` + release 夹取；**深度/循环上限** → 返回 `Outcome::DepthExceeded` / 停表上报；解析失败 → `Result<(), CombatError>` |
| 8 | **`record` + `with` 表达式** | `DamageEffects.cs:15-41`；`StatusEffects.cs:101-104,186`；`StatusApplicationInterceptors.cs:186,269` | record class 是堆对象 | `#[derive(Clone,Copy)] struct` + 显式 `fn with_depth(self,d:u8)->Self`；请求进对象池 / 环形缓冲 |
| 9 | **泛型节点执行器 + `GetGenericTypeDefinition()`** | `EffectProgramNodeExecutors.cs:148-151,159-166`；注册 `StandardCombatPackage.cs:194-248` | 运行期泛型类型身份不可用 | 每节点类型一个 `NodeKind` 枚举；执行器表 `[NodeExecutor; N]`；program 编译成扁平 **opcode 数组** |
| 10 | **`ImmutableDictionary` / `ImmutableArray`** | `CombatDefinitionRegistry.cs:12-32` | 依赖库、结构大、构建期开销 | 全换 `&'static [T]` + 按 `u16` id 二分；表可直接放 flash |
| 11 | **GC / 无池化队列** | `CombatState.cs:5-11` | 每 effect 一次堆分配；continuation 是闭包 | 三个**值类型 tagged union 环形缓冲**；continuation 改成可序列化指令 `(NodeId,ChildIndex,FrameId)` |
| 12 | **快照 / hash 依赖 .NET 序列化** | `CombatStateSnapshotter.cs`、`CombatStateHasher.cs`、`CombatState.cs:714-890` | RL 环境的状态观测 | 自定定点内存布局，RL 侧直接读结构体数组（更快） |

### 5.1 嵌入式可行性的直接结论

> **修饰器、拦截器、触发器都不需要动态分配与虚调度就能完整表达。**

- **修饰器**：全部退化成 `(Pipeline, Operation, Magnitude, Priority, 门控位)` 的 POD 行 + `match` 分派；
  标准内容只有 **2 个**修饰器对象 + 4 个 spec。**零对象。**
- **拦截器**：三种结果都是值类型 tagged union；Artifact/禁止令/放大可直接写成 `match InterceptorKind`。唯一要
  注意的是 `Intercept` 内同步改状态（Phoenix 消耗充能）——把 `&mut CombatState` 传进去即可，别同时借状态切片。
- **触发器**：program 本身已是**数据**（`EffectProgram` 是节点树，执行器是解释器）。唯一贴着"对象"的是
  `ContextFactory`/`BuildContext` 两个闭包 → 换成 `EventKind` + 静态函数表；58 个事件处理器里 56 个是普通 handler。
- **真正需要动态内存的只有四处**：效果队列、事件队列、continuation 队列、运行期临时规则列表（前三个用定容环形
  缓冲，第四个用定容数组）。**字符串可以彻底消灭**：所有 Id 都是 `record struct(string)` 包装
  （`TriggeredEffects.cs:3-6`），内容在编译/加载期就能映射成 `u16`。

## 6. 内存与 CPU 预算提示

### 6.1 一次伤害遍历多少个修饰器

| 遍历 | 次数 | 出处 |
|---|---|---|
| S2 阶段循环 × 修饰器数组 | `3 × N_dmg`，其中只有 `N_dmg` 次真正调用 | `DamageEffects.cs:305-317` |
| 标准内容 `N_dmg` | **2**（`standard.declarative_damage_dealt` / `_received`） | `StandardCombatPackage.cs:47-48` |
| 每次声明式调用的内部成本 | 遍历该战斗员全部状态实例并 `GroupBy`：`O(S log S)` + `O(Σ specs)` 候选收集 + `O(k log k)` 排序 + 折叠 | `PassiveModifiers.cs:140-214` |
| 每次命中的格挡修饰器 | **1**（`standard.declarative_block_gain`） | `:50` |

**这是整条链的热点**：每次命中两次 `GroupBy` 分配（Source 一次、Target 一次）。重写最该做的优化是把状态的
spec 索引**预摊平缓存**在战斗员身上（脏标记 + 重算），让一次命中变成对一张小数组的线性扫描；原实现的
`carried` 集合（`TriggeredProgramDefinition.cs:112-144`）就是这种缓存的先例。

### 6.2 一场战斗注册了多少东西（标准包）

| 类别 | 数量 | 出处 |
|---|---|---|
| 状态定义 / 常驻触发器定义 | 16 / **2** | `StandardCombatPackage.cs:26-43`（`:33,42`） |
| 伤害 / 格挡修饰器对象 | 2 / 1 | `:47-50` |
| 卡费修饰器 / 卡牌校验器 | 5 / 5 | `:59-69` |
| 状态施加拦截器 | **3** | `:71-73` |
| 分裂器 / 死亡前拦截器 | **0 / 0**（全在内容侧） | `PreDownInterceptionTests.cs:69,95` |
| 防御池定义 | 1（Block，AbsorbPriority=0，回合开始清空） | `:54-55` |
| **事件处理器总数** | **58**（`DamageDealt` 4 个） | `:121-190` |
| 效果请求处理器 / 节点执行器 | 43 / 54 | `:78-120`、`:194-248` |

**内容规模参考**：内置样例（《Bureaucrats & Broomsticks》Act I）**62 张卡 / 109 场遭遇**
（`src/RogueDeck.Sandbox.Run/Composition/BureaucratsSample.cs:5-9`），战斗定义由库编译
（`src/RogueDeck.Scenario/Authoring/CompiledCombatLibrary.cs:22-50`）；status/trigger 数量由内容决定，本仓库内不可静态枚举。

### 6.3 每事件成本

触发器切片按 `EventType` 缓存（`TriggeredProgramDefinition.cs:75-93`）⇒ 首事件后 O(1) 取表；但**每次事件仍要遍历
该类型全部定义**并逐个跑 `GatingStatus` 检查，且**门控集合在每次真正触发后重建**（`:112,139-144,174`）⇒ 一次
事件有 k 个触发器真跑了，就是 `k × O(全体战斗员状态数)`；重写时换成**增量维护**（施加/移除状态时更新引用计数表）
可省掉这一项。有临时规则时每次事件都要把注册表与临时表**合并再排序**（`:95-106`）；无则零分配。

### 6.4 可以编译期固定 vs 必须运行期

| 编译期固定（flash/`const`） | 运行期可变 |
|---|---|
| 全部修饰器/拦截器/分裂器/防御池定义表 + 状态定义 + `PassiveModifiers` 表 + 合并行为 | 效果队列、事件队列、continuation 队列 |
| 触发器定义表 + 每 `EventKind` 的排序切片 | 每个战斗员的 `StatusInstance` 列表（层数/时长/充能）；临时规则 + `RemainingActivations` |
| effect program 节点树（编译成 opcode 数组）、卡牌/敌人行动定义 | 动作作用域 claim 账本 / 回合统计 / HP、资源池、防御池 |

### 6.5 建议的固定容量（对齐原实现的硬上限）

| 项 | 原实现 | 出处 | ESP32-P4 建议 |
|---|---|---|---|
| 效果/事件队列每 cycle 上限；队列 cycle 上限 | 1024 / 1024；1024 | `CombatExecutionLimits.cs:12-14` | 环形缓冲 256、cycle 128（越界停表报错，别 panic） |
| 触发器链深上限 | 64 | `CombatEffectChain.cs:10` | 16~32 |
| 死亡前重定向深度 / 状态施加替换深度 | 4 / 3 | `DamageEffects.cs:207`、`StatusEffects.cs:48` | 原样 |
| 临时规则数 | 无上限 | `CombatState.cs:160` | 32（内容普查后定） |

**SRAM 估算**：10 战斗员 × 每员 20 个状态实例 ≈ 200 × ~40 B ≈ 8 KB；队列 ~256 × ~24 B ≈ 6 KB；静态定义表放
PSRAM/flash。**592KB SRAM 对战斗内核绰绰有余，瓶颈在分配与比较，不在容量。** **CPU 提示**：全整数运算（无浮点），
单精度 FPU 用不上；一次命中约 2 次修饰器调用 + 1 次池循环，真正的成本在 `GroupBy`/排序/LINQ 与事件分派的类型查找上 ——
这三项在 C/Rust 里天然消失。

## 7. 验收测试向量

以下可直接做重写版的黄金测试（数值均为**最终 HP / 池值**，不是中间量）。

| # | 输入状态 | 一次操作 | 期望 | 出处 |
|---|---|---|---|---|
| 1 | 双方 HP 100；英雄 Strength 2；哥布林 Vulnerable | `DealDamage(哥布林, 5, 来源=英雄, Direct)` | **哥布林 HP 90**（`(5+2)*150/100=10`） | `ModifierPipelineTests.cs:102-122` |
| 2 | 双方 HP 100；英雄 Weak；哥布林 Vulnerable | `DealDamage(10, Direct)` | **哥布林 HP 90**（`10*75/100=7`，`7*150/100=10`） | `ModifierPipelineTests.cs:124-143` |
| 3 | 哥布林 HP 12；英雄 Strength 2（变体 +Weak） | `DealDamage(6, Direct)` | **HP 4**（`6+2`）；变体 **HP 6**（`(6+2)*75/100`） | `DamageAmountModifierTests.cs:37-62,91-124` |
| 4 | 哥布林 HP 12；英雄 Strength 5 | `DealDamage(5, kind=DamageOverTime)` | **哥布林 HP 7**（DoT 不走 Direct 修饰） | `:126-151`；`VulnerableStatusTests.cs:87-131` |
| 5 | 哥布林 HP 12、5 Block、Vulnerable | `DealDamage(6, Direct)` | **HP 8，Block 0**（先修饰 `6*1.5=9`，后格挡 `9-5=4`） | `VulnerableStatusTests.cs:52-85` |
| 6 | 哥布林 HP 12；英雄 Strength 2 + Weak、哥布林 Vulnerable | `DealDamage(6, Direct)` | **哥布林 HP 3**（`8 → *0.75=6 → *1.5=9`） | `VulnerableStatusTests.cs:133-170` |
| 7 | 英雄 HP 20、Block 5、Ward 池 3（`AbsorbPriority=10`） | `DealDamage(6)`；变体 `IgnoresBlock=true` | **Block 0 / Ward 2 / HP 20**；真伤变体 **Block 5 / Ward 3 / HP 14** | `DefensivePoolAbsorptionTests.cs:23-38,57-72` |
| 8 | 英雄 HP 40/50，Phoenix（1 充能，`Prevent(Max/2)`） | `DealDamage(100)` ×2 | 第一次 **存活 HP 25**（充能消耗、状态移除），第二次 **HP 0 倒地** | `PreDownInterceptionTests.cs:64-88` |
| 9 | 盟友 HP 5；保护者 HP 50/50 带 Martyr 1 层 | `DealDamage(盟友, 10)` | **盟友 HP 5（完全免伤）**，**保护者 HP 40**（整笔重定向，深度+1） | `PreDownInterceptionTests.cs:90-114` |
| 10 | 玩家 50/50，Toll（`StacksPerStack=1`，2 层）；变体再加 Charge（`Priority=10, RefusesWholeApplication`，1 层） | `ApplyStatus(Fear, 3)` | **Fear 1 / Toll 0**；变体 **Fear 0 / Charge 0 / Toll 仍 2** | `PreventionPriorityTests.cs:24-34,51-62` |
| 11 | 玩家 50/50，Register（`AddStacks=1,StacksSpent=1`）1 层 | `ApplyStatus(Register,1)` → `ApplyStatus(Curse,2)` | **Curse 3 / Register 0**（放大替换后重入链，只放大一次） | `StatusAmplificationTests.cs:18-27,44-53` |
| 12 | 哥布林 HP 12；"每受一次伤害回 1 HP"触发器 | 一张 3 段、每段 3 伤害的卡（因果重复） | **哥布林 HP 6**（每段 `-3+1`，段间完整结算） | `MechanicalChallengeTests.cs:353-385` |
| 13 | 哥布林 HP 12；「造成 7 伤害、再按实际掉血回血」的卡（英雄 10/20） | 出牌 | **哥布林 HP 5，英雄 HP 17**（`HealthLost` 喂给下游） | `MechanicalChallengeTests.cs:62-93` |
| 14 | Boss HP 70、无状态无格挡；Double Slash 每段 6 + 全局 Brittle Armor 每段 +2 | 出牌 | **Boss HP 54**（`70 - 2*(6+2)`） | `BossEncounterScenarioTests.cs:159-170` |
| 15 | 英雄 5 Block 请求（变体：+Dexterity 2 / +Frail / +两者） | `GainBlock(5)` | **7 / 3 / 5**（`5+2`；`5*75/100`；`(5+2)*75/100=5.25→5`） | `BlockAmountModifierTests.cs:76-102,104-130,132-166` |
| 16 | 三个同优先级触发器 `test.zzz/test.aaa/test.mmm`（变体：`zzz` p=0、`aaa` p=5） | 触发一次 `DamageDealt` | 顺序 **`aaa→mmm→zzz`**；变体 **`zzz→aaa`**（priority 覆盖 Id） | `TriggeredProgramParityTests.cs:334-373` |
| 17 | 一个 effect 与一个 event 同时在队列里 | 排空队列 | 日志顺序 **先 BlockGained 后 TestEventHandled** | `CombatQueueProcessorTests.cs:56-80` |

**回归用法**：做成表驱动测试，输入 = 初始状态 + 事件/请求序列，输出 = `(HP, 各池值, 状态三轴, 事件序列)`。
第 16/17 条是最容易在重写里悄悄失败的"顺序类"向量，建议**单独**跑，别混进数值向量。

**移植时的五个"别省"**：① 三阶段顺序；② spec 折叠的 `(Priority, statusId, index)` 三键；③ effect 先于 event 的
同 cycle 顺序；④ 触发器晚一个 cycle；⑤ `max(0,·)` 与整数向下取整的位置。
