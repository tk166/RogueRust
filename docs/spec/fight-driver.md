# 一局战斗的驱动层（`battle.rs`）—— 语义与整局对拍方案

依据：commit `fd43e68ab91f40b475b745725abb17134b951c51`。
参考实现的两个文件逐行读过，本文所有断言都带行号：
`ref/RogueDeck-Core/src/RogueDeck.Scenario/Scripting/ScenarioRunner.cs`（267 行）与
`.../ScenarioCombatFactory.cs`（171 行）。

## 0. 这一层唯一要做的事

`ScenarioRunner.cs:9-11` 的自述是全部设计依据：

> It adds NO combat semantics — it only sequences engine calls and observes the result.
> Every problem it surfaces (faulted plays, no-op plays, premature combat end, step exceptions)
> is a real observation about how the engine behaved, not an authored assertion.

⇒ 两条铁律：**不在这里新增战斗语义**；**"问题"是观测不是失败**。

## 1. 建战斗：`ScenarioCombatFactory.Build` 的顺序（`:11-64`）

顺序本身就是语义，逐条：

| # | 步骤 | 行号 |
|---|---|---|
| 1 | `new CombatState(combatId, seed)`（`CellExclusive`/`SimultaneousTeamTurns` 本内核不模型化） | `:13-17` |
| 2 | 加英雄（队 = Player）→ 加友方 → 加敌人（队 = Enemy） | `:19-24` |
| 3 | `SetActiveCombatant(hero)` | `:26` |
| 4 | `DealDeck(hero)`：按牌组顺序，每张一个**新卡实例 id**（`CreateNextCardInstanceId()`），进**抽牌堆** | `:31`、`:67-77` |
| 5 | `ShuffleDrawPileOnStart` ⇒ 洗**玩家的**抽牌堆；`Count <= 1` 时**什么都不做**（连 `random_step` 都不推） | `:38-43`、`:81-89` |
| 6 | `MoveInnateCardsToTop`：把带 `innate` tag 的牌按原相对顺序挪到堆顶 | `:45-49`、`:93-104` |
| 7 | 起始状态：**走真管线**（入队 `ApplyStatusEffectRequest` 再排空），所以合并/叠加语义生效 | `:51-57`、`:144-162` |
| 8 | 开局的临时规则：入队再排空 | `:59-61`、`:129-142` |

战斗员的构造（`:106-127`）：

* `current = clamp(CurrentHealth ?? MaxHealth, 1, MaxHealth)` —— **至少 1 点血**
* `definition_id = DefinitionId ?? Id`
* 资源：逐条 `AddResource(Resource, ValuePoolState(Current, Max, CanExceedMax))`
* 位置：`Position` 为空就不设（flat arena）

**本内核 v1 的取舍（响亮拒绝，不静默跳过）**：
`SimultaneousTeamTurns`、友方（`Allies`）、位置、`innate` tag、起始状态、开局临时规则
**全部为空/关**时才能建 —— 非空就报错。理由：它们各自需要内核还没有的能力
（同时队伍回合 / 位置系统 / 卡 tag 上的 innate 查询 / 事件队列），
而"静默忽略"会让建出来的战斗**看起来正常但语义已经错**。

## 2. 四种步进（`ScenarioRunner.cs:75-252`）

### 通用外壳（每一步都一样，`:32-68`）

1. 取 `before`（trace 切片起点）、清空 `problems`
2. `Result != Ongoing` ⇒ 记 `CombatAlreadyEnded`，**这一步不执行**（`:40-44`）
3. 英雄不在/已倒下 ⇒ 记 `HeroDowned`，不执行（`:45-51`）
4. 否则 `ExecuteStep(...)`；**抛出的异常被捕获**成 `StepThrew`（`:52-63`）
5. 记下这一步的 `(round, turn, actor, problems)`

⚠️ `round`/`turn` 取的是**执行前**的上下文（`:106`、`:140`、`:164`、`:203` 都在执行前构造
`StepContext`）—— 所以"这一步把回合推到了 3"记下来的仍然是 3 之前的值。这一点极易写错。

### 2.1 `HeroPlaysCard`（`:95-128`）

```
:102  行动者不是英雄 ⇒ 记 NotHeroTurn（但**继续**）
:105  EnsureTurnStarted（只在 Result==Ongoing 且 phase==WaitingToStartTurn 时 StartCurrentTurn，`:254-258`）
:108  按**卡定义 id** 在手牌里找**第一张**
:113  找不到 ⇒ 记 CardNotInHand，返回
:121  入队 PlayCardEffectRequest(heroId, instanceId, target, outcome)
:122  排空队列
:124  outcome.WasPlayed == false ⇒ 记 CardNotPlayed
```

### 2.2 `HeroEndsTurn`（`:130-146`）

```
:132  行动者不是英雄 ⇒ 记 NotHeroTurnToEnd
:139  EnsureTurnStarted
:143  只有在 Result==Ongoing 时才 EndCurrentTurnAndStartNextTurn
```

### 2.3 `EnemyActs`（`:148-194`）

```
:158  敌人不存在 ⇒ NoSuchEnemy
:163  AdvanceTurnsUntilActive(enemyId)：逐个结束非英雄回合直到轮到它（`:226-252`）
        —— 如果当前是英雄回合 ⇒ 记 `It is still the hero's turn` 并放弃
:166  战斗已结束 ⇒ CombatEndedBeforeEnemy
:172  推不到 ⇒ CannotReachEnemyTurn
:178  敌人已倒下 ⇒ EnemyNotAlive，**动作跳过**
:184  动作没注册 ⇒ UnknownEnemyAction
:191  入队 ExecuteEnemyActionEffectRequest 再排空
```

### 2.4 `NextRound`（`:196-222`）

```
:202  EnsureTurnStarted
:206  若当前就是英雄回合 ⇒ 先结束它
:211-219  只要 Result==Ongoing 且行动者不是英雄，就一直 EndCurrentTurnAndStartNextTurn；
          guard > TurnOrder.Count + 2 ⇒ 记 CouldNotWrapToHero 并停
```

## 3. 与内核的四处已知不对齐（别当 bug 改回去）

1. **队列中介 vs 就地**：参考 `EnqueueEffect` + `ResolvePendingQueues`（`:121-122`、`:191-192`）；
   内核没有三队列，出牌就是 `play::play_card` 就地执行。可观察后果：`CardPlayed` 触发器不 fire、
   卡在程序中途仍留在手牌（这一点 `play.rs` 已按三终态建模）。
2. **`EnsureTurnStarted` 需要宿主**：内核的 `turn::start_current_turn` 要 `&mut H: TurnHost`，
   宿主由调用方提供（本模块不自己造）。
3. **`problems` 是字符串 vs 枚举**：对拍只比**条数与类别**。
4. **`ScenarioReport` 持有 `CombatState` vs 调用方提供 `&mut CombatState`**：状态 180 KB，不复制。

## 4. 整局对拍方案（两阶段）

### 阶段 1（本轮）：内核自己能跑完一局

* `battle.rs` + `kernel/rd-fightdump`：从**真实内容镜像**建战斗（用镜像里真有的卡与敌人），
  按脚本跑完，输出每步的 `(round, turn, problems)`、终局 `result` 与**每步之后的哈希**。
* 判据（自证，不跨语言）：同一 `(plan, steps, seed)` 跑两遍 ⇒ 哈希序列**逐字节相同**；
  不同的 seed ⇒ 序列**不同**（证明 RNG 真的被消耗了，而不是恒等）。
* 还需要一条：整局能跑到 `Result != Ongoing`（有人死了），说明伤害/治疗真的结算了。

### 阶段 2（下一步）：和 C# oracle 对一局

障碍是**卡定义 id 必须逐字节相同**才能比哈希：oracle 的合成场景用的是 `strike`/`ogre`/`knight`，
而镜像里的卡是 `paper_cut` 之类。两条路：

* **(a) 让 oracle 按镜像的 id author 同一张卡**（推荐）：在 `native/RogueDeck.Oracle` 加一个导出
  `rd_oracle_fight_run(seed, variant)`，里面的卡用**镜像里那张卡的 id + 程序 + 费用 + 落区**
  （这些值从镜像里读出来写死，并配一条"镜像与 oracle 假设一致"的闸门测试）。
  敌人类似：用镜像里的 `EACT` 动作 id 与程序。
* **(b) 只比观测量**（哈希之外的 12 个数）：heroHp / enemyHp / round / turn / randomStep /
  energy / block / hand/discard/exhaust 计数 / steps / problems 条数。这条路更快，
  但它**证明不了指纹一致**，只能证明"战斗进程一致"。

先做 (b) 拿到第一条端到端证据，再做 (a) 把哈希也钉上。**顺序不能倒**：
(b) 一旦红了，说明进程都对不上，此时去查哈希是浪费。

## 5. 未验证

* `ScenarioCombatFactory` 里 `MoveInnateCardsToTop`（`:93-104`）在内核侧的等价物**没有实现**
  （镜像里没有带 innate tag 的卡，所以本轮按"非空即拒绝"处理）。
* 起始状态"走真管线"（`:51-57`）在内核侧需要事件队列才能逐字复刻；本轮按"非空即拒绝"处理。
* `CompiledScenario` 里 `Allies`、`CellExclusive`、`SimultaneousTeamTurns` 的语义**没读**，
  本轮不实现、遇到就拒绝。
