# SEMANTICS-v1 —— 战斗内核跨语言重写的冻结语义规范（W0 产出）

> **性质**：本文是**汇总与冻结**，不是设计文档。只收录三份规格书与 golden 语料里**已有依据**的语义；
> 凡本次未读到依据的，一律进 §7，不猜、不补。
> **出处记号**：`E:§x` = `docs/spec/effect-program-ir.md`；`C:§x` = `docs/spec/combat-state-and-turn.md`；
> `M:§x` = `docs/spec/modifier-pipeline.md`；`S:§x` = `docs/spec/content-schema.md`；
> 裸 `文件:行号` / `T:` / `S测试:` 前缀同规格书约定，相对 `ref/RogueDeck-Core`。
> **⚠ 列** = 该行是规格书明确标记「重写最易踩」的顺序契约。

## 1. 基线与版本

| 项 | 值 | 来源 |
|---|---|---|
| 冻结 commit | `fd43e68ab91f40b475b745725abb17134b951c51`（浅克隆，`git log -1` 本机实测） | 仓库 |
| 冻结日期 | **2026-10-09**（commit 日期） | 仓库 |
| 源仓库 / 许可 | `RogueDeck-Core`，C# / .NET 10，MIT；743 个 `.cs` / 135,496 行 | 任务书基线 |
| 目标平台 | ESP32-P4：双核 RISC-V @360MHz、单精度 FPU、**可用 SRAM 592 KB**、PSRAM 16/32 MB | 任务书 |
| 语料 | `corpus/golden_v1.jsonl`；`schema = "roguedeck-golden-v1"`；1 行头 + **128 条**用例 | 文件实测 |
| 语料生成器 | `native/make_corpus.py` → NativeAOT oracle `native/RogueDeck.Oracle`（`rd_oracle_run`） | E 无关，见 §6.5 |
| 规格书输入 | `effect-program-ir.md`(52 KB, 15 向量) / `combat-state-and-turn.md`(58 KB, 14 向量) / `modifier-pipeline.md`(43 KB, 17 向量) / `content-schema.md`(46 KB) | 文件实测 |
| **本文档版本** | **v1**（2026-10-17 起草；基线 = 上述 commit + `golden_v1.jsonl`） | — |

**变更规则（任何后续语义改动必须遵守）**

| 变更类型 | 动作 |
|---|---|
| 任何**可观察行为**的改动 | 升版本（v1 → v2）；在 §3 追加/修改偏离条目；**必须重新生成语料**（`golden_v2.jsonl`），旧语料只读保留 |
| 新增/删除 IN·OUT 条目 | 同上（升版本 + 重生成语料 + 重跑 §6 全部对拍） |
| 冻结 commit 变化（上游新提交） | 视为**新基线**：升版本、重生成语料、重跑对拍、复核 §7-4 |
| 只补出处、只改措辞、修正笔误 | 允许同版本内修订；**不得**借机改语义 |
| 撤销一条偏离（回归 C# 行为） | 必须显式注明并升版本 —— 偏离条目**不可静默删除** |

## 2. v1 支持范围

### 2.1 IN（v1 必须实现并纳入对拍）

| 子系统 | 具体内容 | 出处 |
|---|---|---|
| 战斗状态容器 | `CombatState` 标量（Id/Seed/Step/Round/Turn/Phase/Active/Result/4 个发号器）+ 战员数组 + 7 卡区 + 状态实例 + 资源池 + 防御池 + 计数器 + 临时规则 | C:§2.1–2.3 |
| 回合状态机 | **轮转模式**：`StartCurrentTurn`/`EndCurrentTurn`/`EndCurrentTurnAndStartNextTurn`/`AdvanceToNextCombatant` + `TurnPhase` 闸门 + 轮次回绕 | C:§3.1 |
| 效果队列与链 | 效果/事件/续延三队列 + 三平行元数据队列 + 排空主循环 + 子循环预算 + `CombatEffectChainContext`（不可变单链表、重入抑制、深度墙） | C:§4.1–4.5、E:§3.1、E:§4.2 |
| 效果程序 IR | 54 节点（10 控制流 + 44 原生操作）、92 表达式、37 选择器中的 **28 个非位置选择器**；求值全整数（饱和不抛、除零默认 0/可切 Fault）；结果键与 33 个 outcome | E:§2.2–2.6 |
| 伤害管线 | S0 受理 → S1 分担短路 → S2 三阶段修饰 → S3 分裂 → S4 防御池吸收 → S5 生命损失 → S6 死亡前拦截 → S7 提交 → S8 输出 → S9 队列 → S10 事件分派 | M:§3 |
| 格挡与防御池 | `GainBlock`（单阶段修饰、无 stage、`modifiedAmount==0` 仍写 OutcomeSlot、只有真正落地才发事件）+ 池吸收序 | M:§3.2、C:§2.6 |
| 状态 | 标准包 **16 个**：Poison / Weak / Vulnerable / Frail / Artifact / Strength / Rage / Dexterity / Thorns / Stun / ActionFails / OneAttackPerTurn / FreeNextCard / FirstAttackEachTurnFree / SkillComboDraw / SkillCostReduction（`StandardCombatPackage.cs:26-43`）；三轴语义 + 合并规则 + 三个状态施加拦截器 | M:§2.2–2.5、C:§2.3 |
| 触发式效果 | 触发程序分发（按 event 类型 → `(Priority,Id)` 序）、58 个事件处理器的**顺序契约**、GatingStatus、过滤器、重入抑制、**临时规则**（5 种生命周期） | M:§2.4、M:§3 S10、C:§4.3–4.4 |
| 出牌 / 牌堆 / 费用 | 7 区（Draw/Discard/Exhaust/Banish/Queue/SetAside/Hand）+ `ZonePlacement` + 卡实例可变标记 + `CalculateCosts` + 校验器链 + 队列卡两段式解析 + 付费即时/效果延后 | C:§2.4、§3.3–3.4、§4.5④ |
| 确定性 RNG | SplitMix64 的 32 位变体（黄金比增量 + 两轮 xor-shift-multiply）+ Fisher–Yates 倒序 + `(RandomSeed, RandomStep)` 纯函数派生 | C:§5.1 |
| 快照与哈希 | 快照 POD 全体 + `hash_golden`（逐字节等价）+ `hash_full`（覆盖全部快照字段）—— 见 §6 | C:§5.2–5.4 |
| 资源补充 | 四条资源请求语义差异（refill 创建缺失池/gain 夹 Max/lose 地板 0/modify 依次夹 `[Min,Max,pool.Max,0]`）+ **overfill 合法** | C:§2.5、§3.3④ |
| 回合/轮次生命周期（法令） | **7 条法令**：MaxCardsPerTurn / NoLikenessInSuccession / NthCardOfTurnIsFree / MinimumCardCost / UnspentResourceCarries / PlayedCardsExhaust / MaxHandSize（`CombatDecrees.cs:5-51`）；turn-start 7 步序列、turn-end 4 步序列、RoundEnded/RoundStarted | C:§3.1、§3.3 |
| 单场预算 | 4v3 / 200 卡实例的可变状态 **≈9 KB** | C:§6.2 |

### 2.2 OUT（明确延后）

| # | 条目 | 为什么延后 | 会不会影响已验证的部分 |
|---|---|---|---|
| 1 | **run 层**（地图/房间/奖励/商店/火堆/事件） | 与战斗内核只有一个接口：进入战斗时的初始状态。注册表是只读 ROM 表、不入快照不入哈希（C:§1.2）；语料内容里 `Consumables/Shreds/Recipes/Workbenches` 全空、`MapGeneration=null`（S:§1.1） | **不会**。既有 128 条语料与全部向量都不经过 run 层 |
| 2 | **运行时 JSON** | 只属作者工具/内容编译链；`CombatJson.cs:132-137` 实测每场战斗开始 1.7 s 里 1.6 s 花在 STJ 类型元数据反射（E:§5.5）。二进制格式由 W2 出（§7-1） | **不会**影响 `hash_golden`（那是**规范文本**不是 JSON，C:§6.1）；**会**影响旧 JSON 存档兼容 —— 该项本就延后 |
| 3 | **位置系统**（`PositionalTargetSelectors`，9 选择器 + 4 基元） | 引擎自身 opt-in（`CombatPrimitives.cs:55-59`）；flat 战斗里位置类选择器**恒空**（E:§2.5）；唯一浮点所在（E:§2.1） | **不会**：语料战斗是 flat，三份规格书的 **46 条向量**与全部语料都无一触发位置代码路径。将来实现必须改整数叉积（§3-D2） |
| 4 | **同时队伍回合**（`SimultaneousTeamTurns`） | 默认 `false`；且 `CurrentPhaseTeam`/`_endedThisPhase` **既不入快照也不入哈希**（C:§2.1.2、§3.2⚠）⇒ 即便实现了也无法用 `hash_golden` 对拍 | **不会**。代价：该模式的中途存档**永远无法忠实还原**，这是延后本身造成的（C:§5.2） |
| 5 | **消耗品/药水** | run 层概念（`RunBlueprint.Consumables` 本内容为空，S:§2.1）；无战斗语义 | **不会** |
| 6 | **Shred / Recipe** | 碎片合成系统，本内容未使用（S:§1.1 全空）；属 run 层 | **不会** |
| 7 | **Blazor 沙盒与 Studio** | UI/编辑器模型，非运行时（E:§1）；`CombatProgramModel` 是编辑器模型、**不是线格式**（S:§7.4） | **不会**，且二进制 opcode 表**必须**用 `CombatJson.cs:364-421` 注册表而不是编辑器模型 |
| 8 | **Bot / FightPlanner** | 宿主消费者（E:§1「不负责 AI/UI」）；RL 训练侧真正需要的是 `hash_full`（§3-D4、§6.3） | **不会** |

### 2.3 实现期扩展（v1 契约之外，2026-11-03 补记）

v1 的范围（§2.1 IN）没有包含下面这些；它们是**内容逼出来的**机制，实现时按"最小、可拒绝、可指纹"
的原则加进来。**都不改 §2.1 的既有语义**：参考的三种 `CombatResult`、`hash_golden` 的规范文本、
队列与链的编号规则一个字都没动。

| 扩展 | 语义 | 为什么 v1 没有 | 出处 |
|---|---|---|---|
| `node.destroyCombatant` | 把一个战斗员**移出**战斗（名册 / 回合序 / 牌堆表三处一起移位）。被销毁者不再被 `collect_triggers` 收集。拒绝移除**当前行动者**（回合循环按 id 找它） | 参考没有这个词；StS 的"Boss 分裂"是"本体消失、两只顶替"，而"消失"无法用状态表达（状态写入是**入队请求**，同一批伤害里来不及落地） | §178 |
| `STAT.DeathPrevention`（PreDown 拦截） | 血量落到 0 之后、转 `Downed` **之前**拦截：生存血量 = `max(SurvivingHealth, maxHP × Percent / 100, 1)`；状态被消耗（`Repeating` 才留） | 参考有这个字段与拦截器，本内核一直只解析不执行 | §180 |
| `standard.card_cost_override` | 每副本**绝对价**，读在 `card_cost_delta` 之前，**不被出牌消费** | 参考的 delta 是"一次承诺、付款即清零"；"整场战斗随机费用"（Snecko Oil）在 delta 上表达不出来 | §179 |
| `standard.duplication` | 出牌节目跑**两遍**（只付一次费、只算一次出牌），跑完消耗一层 | 参考没有"打两次"的原语 | §181 |
| 运行层动词（不在内核） | `combat_upgrade_hand` / `combat_randomize_costs` / `combat_flee` / `combat_autoplay_top`；脱战是运行层 `result = 3`，不是第四种 `CombatResult` | 都是 StS 的药水语义，参考是引擎不是 StS | §179 / §182 |

**一条要记住的队列语义**（§177 的实测，比上面任何一行都重要）：

> 触发器程序里的每个效果都是**入队请求**。同一个伤害批次里，后续伤害的触发器在"移除"落地
> **之前**就被收进 batch ⇒ **"只触发一次"不能由内容表达**（自摘状态、计数器都不行）。
> 需要"一次性"的地方要么用 `node.destroyCombatant`（立即生效），要么在内核改排空顺序。

## 3. 有意偏离清单（新内核**故意**与 C# 不一致）

> 「豁免」列 = 该条偏离是否要求对拍用例**按新行为**记期望值（C# 侧会给出不同/抛异常的答案）。

| # | 偏离（v1 怎么做） | 理由 | 影响面 | 出处 | 豁免 |
|---|---|---|---|---|---|
| **D1** | 防御池清理入队顺序改为**显式按 `(AbsorbPriority, Id 序数)` 排序**（C# 用 `ImmutableDictionary.Values` 遍历序） | `.NET` string 哈希**每进程随机化** ⇒ 当**多于一个**池带 `ClearsOnOwnerTurnStart` 时入队顺序跨进程不稳定 | 只在 ≥2 个池带该标记时可观察；标准包只有 Block 一个池 ⇒ 现有语料与向量不受影响。**这是内核里唯一一处「集合遍历序影响队列顺序」** | `DefensivePoolEffects.cs:301`；C:§4.5、§5.4#3 | **需要**（新增用例「多池同时清理」按新序记期望） |
| **D2** | **不实现**位置系统；将来若实现，`ForwardSign` 必须改**整数叉积** `sign(enemySum*srcCnt − srcSum*enemyCnt)`（C# 用两次 `Average()` 取 `Math.Sign`） | P4 只有单精度 FPU；用 `float` 重实现会在「两队均深几乎相等」时**翻转符号** | v1 零影响（代码不存在）。将来：整数叉积只能「多数情况下」等价 ⇒ 必须专门对拍确认该分支在语料上永不触发符号差别 | `PositionalTargetSelectors.cs:43-52`；E:§2.1、C:§5.4#1 | v1 **不需要**；将来实现时需要 |
| **D3** | 引擎自身两个 bug **按修好的写**：① `ApplyTriggerEventStatusNode` 在 JSON 注册了但**漏在 executor 注册表** ⇒ v1 注册它；② `GainBlockNode` 声明 `ResultKey`/`GetProducedResult()` 却从不 `Store` ⇒ v1 补 `Store` | 规格书明说这「属修 bug 而非移植」 | ① 修好后含该节点的程序能跑（C# 里 preflight 直接抛）；② 修好后 `gainBlock` 的结果键可读（C# 里预检过、运行期取值抛） | `CombatJson.cs:381` vs `NodeExecutors.cs:60-112`；`NativeNodes.cs:166,181-184` vs `NodeExecutors.cs:765-781`；E:§5.9、§3.5 | **需要**（含这两处的用例，C# 会抛/不可读，重写侧按新行为记期望） |
| **D4** | **两级哈希**：`hash_golden`（与 C# **逐字节等价**，用于对拍与旧存档）+ `hash_full`（覆盖**全部**快照字段，训练用，可换 xxHash/CRC 并支持增量） | `CombatStateHasher` 只覆盖快照**子集**：`CardPlayTurnStats` 整块、`TriggerActivity`、`NextSummonedCombatantNumber` **不在哈希里** | 任何「只比 `hash_golden` 就宣称通过」的验收都会**漏检** §6.3 的 8 类字段；训练状态去重必须用 `hash_full`；SHA-256 在训练步频下太贵 | C:§5.2、§5.4 表；C:§5.4「给重写的规格建议」 | 不需要（两条哈希都产出即可），但**强制**要求 `hash_full` 也进对拍产物流水线 |
| **D5** | 消灭 `TContext` 泛型（C# 靠 `MakeGenericType` 运行期闭合）→ **`EventKind` tagged union + 静态函数表** | 运行期类型身份在 `no_std` 不可用；`EventAmountExpression` 的 `switch(SourceContext)` 本来就是 tag 分派 | 可观察行为必须原样：哪些表达式在哪种触发器下有效、`EventAmount` 的 **11 种**分支集合、未知兜底 `_=>0`/`_=>null`；同时消灭 44 节点 × N 上下文的单态化膨胀 | `Contracts.cs:68,536-539`、`CombatJson.cs:44`、`Expressions.cs:970-998,2102-2115`；E:§5.3、M:§5#1 | 不需要（纯实现机制）。**但**「未知上下文 = `All`」的宽容兜底必须保留（`EffectProgramTargetingContracts.cs:54-81`），否则第三方内容被误拒 |
| **D6** | 异常作控制流 → **错误码**（`FaultCode` + `Result<(),Fault>`），**但保留语义差异**：`RepeatUntil` 超限 = **静默正常完成**；`Repeat`/`ForEachTarget`/`ForEachCardInZone`/`RandomTargets` 超限 = **抛** | `no_std` 无 unwind；RL 批量自对弈不能因一份非法内容杀整进程（内容加载期校验可 panic） | 队列 cycle/数量、程序步数、活跃作用域、链深、标量读多目标、结果槽二次完成、缺 executor 全部改错误码；**「RepeatUntil 不抛」不可统一** | E:§4.2⚠、E:§5.6、M:§5#7；`NodeExecutors.cs:351-355` | 不需要（表示层），但必须**逐条保留**「抛 / 静默」的划分，且 frame 进 `Faulted` 的单终态语义不变（E:§4.3） |
| **D7** | 同一事件的多 handler **无排序键**（顺序 = 注册顺序）→ **固化成显式顺序表**，且与标准包注册顺序一致 | handler 顺序由 `List.Add` 决定（`CombatDefinitionRegistryBuilder.cs:334-354`）；`DamageDealt` 挂了 **4 个**（`StandardCombatPackage.cs:144→148→149→157`）；重排注册顺序会改变可观察行为 | 全部 58 个 handler 的每事件序。典型后果：反伤（`Kind=Reflected`）在段内还是段间命中、`Downed` 与触发器的相对次序 | M:§3 S10、M:§4.1 末行、M:§4.4；`CombatEventHandling.cs:58-63` | 不需要（顺序必须一致）。**但**必须把 §4-O5 表逐行固化 |
| **D8** | 卡区查找改 **owner 索引**（C# `ContainsCard`/`GetCard` 是对 `AllCards` 的**线性扫描**，`AddCard` 还用它去重 ⇒ 每次抽/移牌 O(总牌数)） | 嵌入式 200 张卡 × 每次移动的 O(N) 不可接受 | **去重语义必须仍是「按 `card.Id` 判重」**（不是实例身份）；`AllCards` 拼接序 `draw→hand→discard→exhaust→banished→queue→setAside` 若被任何观察者读到必须保持 | `CardZones.cs:173-205`、`:182-190`；C:§2.4 不变量②③、C:§6.1、M:§6.1 | **需要**（用例须含「同 Id 重复 `AddCard` 被拒」与「7 区拼接序」） |
| **D9** | 实体 id 全部 intern 成 `u16`；但 `(Priority, Id)` 排序的**次级键仍是字符串序**（保留按字符串预排序的 id 表或显式 `u16 order` 字段） | `Id.value` 的**字典序**被用作触发器/修饰器/校验器的排序键；intern 后数字序 ≠ 字符串序 | 所有 `(Priority, Id)` 排序点（触发器 O6 / 修饰器 O12 / 校验器 O49）；错了会**静默**改变次序 | E:§5.4⚠、M:§4.1 C；`TriggeredProgramDefinition.cs:105` | 不需要，但需一条「数字 id ≠ 字符串序」安排下的 V10 类用例 |
| **D10** | `CombatLog`（append-only、**无上限**）→ 环形缓冲（建议 256 条）或 MCU 下编译掉；**但必须逐条计数** | 长战斗轻松 数百 KB–MB；且没有任何规则读日志（纯观察） | `hash_golden` **不含**日志 ⇒ 哈希对拍看不出差异；但语料记了 `log_count` ⇒「丢文本但保计数」是**强制**要求；V3/V4 还要断言日志**类型序** | C:§2.1.3、§1.2、§6.2⚠ | **需要**（MCU 构建只计数不存文本 ⇒ 训练/对拍构建必须存文本） |
| **D11** | 状态 active/pending 分离为两个数组 + active 计数（C# `Statuses` getter 每次读都 `Where().ToList()` 分配） | 热路径每次读取都分配（C:§2.2⚠） | **实例加入序必须保持**：快照用 `AllStatuses`（含 pending）的**列表序**，哈希逐实例写 ⇒ 顺序错则哈希错 | `CombatantState.cs:24-33`；C:§2.2、§5.3 | 不需要 |
| **D12** | `CardPlayTurnStats` 改定长数组（C# 每战员 6 字典 + 3 HashSet） | 每战员 9 个容器是热路径主要分配源；且**整块不入 `hash_golden`** | 「超过上一回合」「又以 Attack 开场」「本回合第三张」这类规则还原后读 0 的真实事故必须不再发生；只在 `hash_full` 下可对拍 | `CardPlayTurnStats.cs:5-34,196-202`；C:§5.2、§5.4 表、C:§6.1 | **需要**（`hash_golden` 无法覆盖 ⇒ 必须以 `hash_full` + 逐规则用例验收） |
| **D13** | 规范文本的整数格式化**固定为 ASCII 十进制 + 负号 `-`**（不依赖默认 locale）；内容 id **必须 ASCII-only** | C# 用 `StringBuilder.Append(int)`（内部 `ToString()`，文化相关）与 `$"card_{n:000000}"`；且 UTF-16 序数序 ≡ UTF-8 字节序只在 ASCII 下成立 | `hash_golden` 逐字节等价；非 ASCII id 会让 `strcmp` 与 `StringComparer.Ordinal` 分叉 | `CombatStateHasher.cs:30-39`；C:§5.4#2/#4 | 不需要 |
| **D14** | 遍历可变集合前一律**显式物化到预分配缓冲**（C# 靠 `ToArray()`/`ToList()`） | 消 LINQ 分配；对象池/arena 化 | **快照语义必须保留**：`ForEachCardInZone` 的列表在**循环开始快照**（`Nodes.cs:286`）、回合推进前物化 `TurnOrder`、临时规则安装/剪枝前物化 | C:§4.5③、E:§5.7、`Nodes.cs:286` | 不需要 |
| **D15** | 执行限额**默认值**可下调（固件建议环形 256 / cycle 128 / 链深 16–32），但**对拍构建必须用 1024/1024/1024/64** | 嵌入式要小容量、要"越界停表报错而不是 panic"；规格书自己给了这组建议值 | 若固件默认值 ≠ 1024，则 §5.1 中「超限 throw」类用例（如 V5 注入 `maxQueueCycles=3`、V9(a) 注入 `maxProgramSteps`）的期望值在**两侧都必须显式注入**，不能靠默认 | M:§6.5、C:§4.3、`CombatExecutionLimits.cs:11-14` | **需要**（两侧用例都显式写限额参数，禁止依赖默认值） |

## 4. 不可协商的顺序契约

> 全部 O 行均为**必须**（规格书标【必须】/硬锁级）。`⚠` = 规格书标记「重写最易踩」。

| # | 契约（一句话） | 出处 | ⚠ |
|---|---|---|---|
| O1 | 同一 cycle 内 **effect 全部排空先于 event 全部排空**（"先生效后广播"） | C:§4.2①；`T:CombatQueueProcessorTests.cs:57-80` | ⚠ |
| O2 | continuation **只在 effect 与 event 队列都空**时执行，且**每 cycle 至多一条**（不是 while） | C:§4.2②；`CombatEventHandling.cs:107-111` | ⚠ |
| O3 | effect 严格 **FIFO**，且以**入队时绑定的 chain** 解析（快照进平行元数据队列，出队时恢复） | C:§4.1、E:O4；`CombatState.cs:394-407` | |
| O4 | 入队顺序 = **先请求、后自己的完成 continuation** ⇒ 读取者一定看到已结算 outcome | E:O5；`NodeExecutors.cs:614-641` | |
| O5 | 同事件的多 handler **无排序键，顺序 = 注册顺序**；`DamageDealt` 四个：`TrackDamageDealt` → `TriggeredDamageOnDamageDealt` → `MarkCombatantDownedOnZeroHealth` → `TriggeredProgramHandler` | M:§3 S10、M:§4.1；`StandardCombatPackage.cs:144,148,149,157` | ⚠ |
| O6 | 触发器顺序 = **`(Priority asc, Id 字符串序 asc)`**，**与注册顺序无关**；常驻触发器 ⊕ 临时规则合并后再排 | E:O11、M:§4.1 C；`TriggeredProgramDefinition.cs:88-106` | ⚠ |
| O7 | 触发器**晚至少一个 cycle**：事件 handler 里 `EnqueueEffect` 的请求要等**整个事件队列排空**才解析 | M:§3 S9/S10 | ⚠ |
| O8 | 触发执行次序**不可交换**：重入抑制 → 深度墙 → GatingStatus 快跳 → 构造 ctx → Filters → 执行（用 `IndexOf` 位置断言硬锁） | C:§4.4；`TriggeredProgramDefinition.cs:114-161` | ⚠ |
| O9 | **递归抑制优先于深度墙**：同一定义第 64 层的自我重入被"已经进过"挡掉，而不是撞深度墙 | C:§4.4；`T:CombatEffectChainDepthLimitTests.cs:138-187` | ⚠ |
| O10 | 触发链深度上限 **64**，检查**在过滤器之前** | C:§4.3、§4.4；`CombatEffectChain.cs:10,64-72` | |
| O11 | 伤害阶段序**硬编码 Source → Target → Global**（不是按 Priority 全局排） | M:§3 S2；`DamageEffects.cs:7-13` | ⚠ |
| O12 | 阶段内修饰器按 **(对象 Priority, ModifierId)** 升序折叠；**Strength=100 加法 / Weak=200 乘法 / Vulnerable=300 且在 Target 阶段** | M:§2.2、§4.1 A、§4.2；`StandardCombatPackage.cs:280-283,339-342,428-431` | ⚠ |
| O13 | 声明式 spec 折叠键 **(spec.Priority, statusId 序数, specIndex)**；多实例**先求和再乘**；`OncePerAction/Turn` 的 claim **在所有门控之后** | M:§3 S2；`PassiveModifiers.cs:148,179-185,191-201` | ⚠ |
| O14 | 每步 `max(0,·)`；`amount<=0` 是唯一早退短路；`ScalePercent` = `cur*mag/100` **整数向下取整** | M:§3 S2；`PassiveModifiers.cs:137-138,210-216` | ⚠ |
| O15 | 修饰器**不能取消**命中：降到 0 也照走后续阶段，并发 `HealthDamage=0` 的事件 | M:§3 S2/S8 | |
| O16 | 伤害修饰**默认只对 `Kind==Direct`** 生效（DoT/Reflected 不受影响；可改成显式位掩码） | M:§1.4、§4.4；`PassiveModifiers.cs:87` | ⚠ |
| O17 | 分裂：取**第一个返回 `Split`** 的 splitter；每个 `share.Amount>0` 作**新请求**入队（`IsRedistributedShare=true`，**不继承** `OutcomeSlot/Element/RedirectionDepth`）；**原命中立即 return**（不掉血/不发事件/不写槽） | M:§3 S3；`DamageEffects.cs:66-68,209-247` | |
| O18 | 防御池按 **(AbsorbPriority, Id 序数)** 升序 drain；`IgnoresBlock` 全跳；`remaining<=0` 中途 break；trace 只报**第一个**吸收池而 `BlockedAmount` 是**所有池之和** | M:§3 S4；`CombatDefinitionRegistry.cs:68-71` | |
| O19 | 死亡前拦截触发条件**三者全满足**：`newHealth==0 ∧ healthBefore>0 ∧ RedirectionDepth<4`；取**第一个非 `Allow`** 的拦截器 | M:§3 S6；`DamageEffects.cs:110-136,207,249-271` | ⚠ |
| O20 | `Redirect` 语义：原目标 `newHealth=healthBefore`（**完全免伤**），**整笔剩余伤害**作新命中给 `to` 且 depth+1，**新命中不带 `OutcomeSlot`** | M:§3 S6；`DamageEffects.cs:130-134` | |
| O21 | S8 输出次序：Trace → OutcomeSlot → 日志 → 动作记账 → **先 `DamageDealt` 后 `DamageReceived`** | M:§3 S8；`DamageEffects.cs:144-203` | |
| O22 | 完全被格挡仍发 `DamageDealt(HealthDamage=0)`，且仍算"造成伤害的动作"（Direct ∧ 双方在场 ∧ 不同队）；状态跳伤不算 | M:§1.4、§3 S8；`StatusEffects.cs:523-524` | |
| O23 | 状态施加拦截链 **Artifact(100) → 禁止令(200) → 放大(300)**；"被拒绝的永不被放大"；放大是 `Replace` ⇒ **重新入队**再走一遍链；替换链深度上限 **3** | M:§2.3、§4.3；`StatusEffects.cs:48,100-104,277-278` | ⚠ |
| O24 | 禁止令内部顺序 **(Prevention.Priority 降序, 实例年龄升序)**；充能消耗**同步**执行（不走队列） | M:§4.3；`StatusEffects.cs:128-155,181` | |
| O25 | 状态三轴独立：`Stacks +=` / `DurationTurns max` / `Charges +=`；任一到 0 ⇒ 移除 + `StatusExpired`；`PendingTurns` 回合开始 -1，到 0 发 `StatusActivated` | M:§2.5；`StatusEffects.cs:135-139,333-406` | ⚠ |
| O26 | pending 状态（`PendingTurns>0`）"可见可清但**无效**"：不带修饰器、不触发、对"你有没有这个状态"隐身，且**不发 `StatusApplied`** | C:§2.3、M:§2.5；`CombatantState.cs:24-33` | ⚠ |
| O27 | `Result!=Ongoing` ⇒ 队列**立即停止排空**（残余效果永久丢弃），活跃程序帧全部 `CancelDueToCombatEnd()` | C:§4.2③；`CombatState.cs:358-366` | |
| O28 | **Causal**：每个孩子**完全结算（含其引发的全部反应）**才走下一个；**Batch(Sequence)**：全部孩子**先入队**，反应最后跑 | E:O1/O2；`T:EffectProgramCausalSequenceTests.cs:46-90`（向量 V11） | ⚠ |
| O29 | 由 O2 推出"段间完整结算"：多段攻击的每段之间反应先跑完 | M:§3.1 末；`T:MechanicalChallengeTests.cs:353-385` | ⚠ |
| O30 | `Repeat.Count` **只求值一次**；`RepeatUntil.StopCondition` 在**每次体后、pop 之前**求值（体里仍可见 `IterationIndex`） | E:O6；`NodeExecutors.cs:287,363-365` | ⚠ |
| O31 | 每轮迭代 `OpenScope` + 压迭代变量，**在 continuation 里成对关闭/弹出**（外层值自动恢复，无需保存/恢复） | E:O7 | |
| O32 | `IterationTarget/Card/Index` 是**词法**的（最内层），空则 null/0；聚合表达式手动压/弹 | E:O8 | |
| O33 | 结果键：同作用域**唯一生产者**、**先生产后消费**、读取类型一致、标量读要求生产者单目标 | E:O9；`Contracts.cs:601-622,687-701` | |
| O34 | 分支内结果键**不外泄**；Sequence 兄弟共享外层可见集；Causal 兄弟逐个累积 | E:O10 | |
| O35 | 结果槽**恰完成一次**，二次赋值抛（重复结算的哨兵，必须保留） | E:O15；`Outcomes.cs:161-180` | |
| O36 | **陈旧 continuation 丢弃**：frame 已终态时 `ExecuteNode` 直接 return | E:O13；`Execution.cs:104-105` | |
| O37 | `Result!=Ongoing` ⇒ 各循环进入下一轮前检查并**丢弃剩余迭代（不抛）** | E:O12 | |
| O38 | `Repeat`/`ForEachTarget`/`ForEachCardInZone`/`RandomTargets` 超限 **throw**；`RepeatUntil` 超限 **静默正常完成** —— **不可统一** | E:§4.2⚠；`NodeExecutors.cs:294-297,390-393,467-470,519-522,351-355` | ⚠ |
| O39 | 队列 cycle(1024) / 每 cycle effects(1024) / events(1024) 超限 **throw** | C:§4.3；`CombatExecutionLimits.cs:12-14` | |
| O40 | RNG = `(seed,step)` 纯函数派生 + Fisher–Yates **倒序**；抽单个元素**也必须跑完整趟**（`step` 只 +1）；每次随机读后 `step++` | C:§5.1；`CombatRandom.cs:5-56` | ⚠ |
| O41 | `RandomTargets`：`count=clamp(count,0,len)`，`CreateShuffledIndexes(len,seed,step)` 取前 count，**`AdvanceRandomStep` 一次** | E:§3.4 | |
| O42 | 队列解析**两段式**：先快照待解析卡 id → **逐个串行**；每张开始前**重新校验**；`_resolvingQueuedCards` 阻止自递归（否则 stack overflow）；**只有 `Completed` 才继续下一张**（`Faulted` 直接 return，否则两个提问并存） | C:§4.5④；`QueueResolution.cs:29-33,51-56,100-110` | ⚠ |
| O43 | 遍历可变集合前一律**物化**（回合推进 / 临时规则安装剪枝 / 同时队伍成员） | C:§4.5③ | |
| O44 | 回合开始：`TurnPhase←TurnInProgress` → **入队** `TurnStarted`（不是同步调用）→ 排空。回合结束：`MarkTurnEnded`（非 `TurnInProgress` 抛）→ 入队 `TurnEnded` → 排空 → 仍 `Ongoing` 才推进 → 排空 → 跳过被打死的 | C:§3.1 | ⚠ |
| O45 | turn-start handler 序：`ResetCardPlayTurnStats` → **`RefillResource`(在触发器之前)** → `ActivatePendingStatuses` → turn-start 触发程序 → **`ResolveQueue`** → `DrawCards(5)` → **`ClearBlock`** → `DamageOverTime` | C:§3.1 表；`StandardCombatPackage.cs:121-139` | ⚠ |
| O46 | turn-end handler 序：`CardLifecycleTurnEndInHand` → `DiscardHand`（被 `RetainHandTag` 抑制）→ turn-end 触发程序 → `DecreaseTimedStatusDurations` | C:§3.1；`StandardCombatPackage.cs:135-138` | |
| O47 | 轮次回绕：绕回时先 `RoundEnded` → `AdvanceRound`（`Round++`/`Turn=1`/清临时规则）→ `RoundStarted` | C:§3.1；`CombatTurnProcessor.cs:170-212` | |
| O48 | 法令读取：收集顺序 **`(statusId 序数, specIndex)`**；重复法令**不互相放松**（Ceiling 取 `Min` / Floor 取 `Max`）；三个读取点 = 150 出牌前拒绝 / 300 第 N 张免费（只降不升）/ `MinimumCardCost` 在 `CalculateCosts` **末尾兜底** | C:§3.3；`CombatDecrees.cs:70-125` | |
| O49 | 出牌拒绝分层（越靠前越早拒）：`Result` → `TurnPhase` → `!IsAlive` → 校验器链 `(Priority, ModifierId)` → `EnsureCostsCanBePaid`（**在效果入队之前**） | C:§3.4；`CardPlay.cs:82-94,122-126,514-533` | |
| O50 | 两条 surface 语义**不同**：直接处理器路径拒绝 = **抛**；`PlayCardEffectRequest` 拒绝 = **静默 no-op + `WasPlayed=false`**（卡留手里、战斗继续） | C:§3.4⑦；`CardPlay.cs:356-382` | ⚠ |
| O51 | 原生操作统一模式：**先**入队全部请求、**后**入队 continuation 写结果键；`DeterministicIndex` = 目标**解析顺序** | E:§3.5；`NodeExecutors.cs:596-643` | |
| O52 | `OutputScale` 只缩放**正数的向下产出**、向下取整；**不**作用费用/命中数/目标数/移动 | E:§2.6；`Outcomes.cs:394-405,430-452` | |
| O53 | 快照/哈希的规范序：集合按 `StringComparer.Ordinal` 显式排序或以列表原序写出；分隔符统一 **LF**（不是 `Environment.NewLine`） | C:§5.3 | ⚠ |

**边界契约（非顺序，但同属不可协商）**

| # | 契约 | 出处 |
|---|---|---|
| B1 | 内核**不**强制"只能由当前行动者出牌"：`PlayCardCore` 只查 `Result==Ongoing` 与 `source.IsAlive`，**没有** `ActiveCombatantId==source` 校验 ⇒ 何时谁能出牌是**宿主责任**（规格书明说「必须显式写进重写规格，否则对拍会跑偏」） | C:§1.3、`CardPlay.cs:82-94` |
| B2 | 快照**只在静默点**取（队列与程序帧为空）；带活跃临时规则的快照在无 registry 时 `Restore` **拒绝**；带过期副作用的临时规则一律拒绝 | C:§1.3；`CombatState.cs:727-736,767-769` |
| B3 | `CombatLog` 与 trace 流是**纯观察**：没有任何规则读日志；trace 仅当 `TraceListener != null` 时产生 | C:§1.2；`CombatState.cs:173-184,710-712` |
| B4 | `DefinitionRegistry` **不入快照、不入哈希** ⇒ 重写为只读 ROM 表 + 整数句柄 | C:§1.2；`CombatState.cs:54-57` |

## 5. 限额与预算表

### 5.1 硬上限（**超限行为必须逐条保留**）

| 限额 | 默认 | 超限行为 | 出处 | 嵌入式影响 |
|---|---|---|---|---|
| 队列 cycle `MaxQueueCycles` | **1024** | 抛 + `WhatIsLooping` 诊断（队首 6 个效果/事件 + 末 10 条日志） | C:§4.3 | **SRAM** 环形缓冲计数；固件建议 128（M:§6.5）⇒ 超限用例两侧都必须**显式注入**参数（§3-D15） |
| 每 cycle effects `MaxEffectsPerCycle` | **1024** | 抛 | C:§4.3 | 队列条目 ≈16 B/项 × 512 ≈ **8 KB，必须在 SRAM** |
| 每 cycle events `MaxEventsPerCycle` | **1024** | 抛 | C:§4.3 | 同上 |
| （三者必须 `> 0`） | — | 构造期 `ArgumentOutOfRangeException` | `CombatExecutionLimits.cs:16-29` | 加载期校验 ⇒ 可进 ROM 常量 |
| 触发链深度 `MaximumTriggerDepth` | **64** | 抛（**在过滤器之前**） | C:§4.3；`CombatEffectChain.cs:10` | 队列条目元数据；建议 16–32（M:§6.5） |
| 节点树静态深度 `MaxNodeDepth` | **64** | 构建期抛 | E:§4.2 | ★ **P4 任务栈仅几 KB ⇒ 这是硬约束**：续体必须用显式帧数组而非 C 递归（E:§6.3） |
| 程序步数 `MaxProgramSteps` | **1024** | 运行期抛（含循环重入） | C:§4.3、E:§4.2 | 计数器在 SRAM；⚠ **实测合法内容有单程序 1,725 节点 ⇒ 需复核**（S:§6.2#11、§7-5） |
| 活跃作用域 `MaxActiveScopes` | **32** | 先 trace `LimitExceeded` 再抛 | E:§4.2；`Outcomes.cs:500,522-536` | scope arena 定长：`32 × N_RESULT_KEY` slot，**SRAM**（E:§5.4） |
| `RepeatEffectNode.MaxCount` | **32** | **抛** | E:§4.2 | — |
| `ForEachTargetEffectNode.MaxIterations` | **32** | **抛** | E:§4.2 | — |
| `ForEachCardInZoneNode.MaxIterations` | **64** | **抛** | E:§4.2 | 迭代列表快照到预分配缓冲（O43 / §3-D14） |
| `RandomTargetSelectionNode.MaxIterations` | **32** | **抛** | E:§4.2 | — |
| `RepeatUntilEffectNode.MaxIterations` | **32** | **静默正常完成** ⚠ | E:§4.2⚠ | **不可统一**（§3-D6） |
| 死亡前重定向深度 `MaxRedirectionDepth` | **4** | 不再走 S6 拦截（不抛） | M:§3 S6；`DamageEffects.cs:207` | 原样保留（M:§6.5 建议也是 4） |
| 状态施加替换深度 | **3** | 不再替换 | M:§4.3；`StatusEffects.cs:48` | 原样保留 |
| 临时规则数 | **无上限** | — | M:§6.5 | 定容数组，建议 **32**（内容普查后定） |
| `CombatLog` | **无上限** ⚠ | — | C:§2.1.3、§6.2⚠ | **必须**环形缓冲（256 条 ≈32 KB → **PSRAM**）或编译掉，**但计数必须保留**（§3-D10） |

### 5.2 实测规模与预算

| 项 | 实测 / 给定值 | 出处 | 放哪 / 嵌入式影响 |
|---|---|---|---|
| 单场可变状态（4v3、200 卡、20 状态） | **≈ 9 KB**（打包后；C# 现状 ≈55 KB；规范文本量 10–15 KB） | C:§6.2 | **SRAM**。卡实例（≈5 KB）建议留 SRAM **不要赶到 PSRAM** |
| 单场可变合计（含环形日志/队列） | ≈ 25–60 KB | C:§6.2 | SRAM 分项合计 25–40 KB = 592 KB 的 **5–7%**，绰绰有余 |
| RNG 持久状态 | **8 B**（两个 int32；`uint` state 每次从 `(seed,step)` 重派生） | C:§5.1 | SRAM；哈希只存 `step`（O40） |
| 快照规范文本 buffer | ≈ 10 KB/次 | C:§6.2 | **PSRAM**；SHA-256 每步重算的 PSRAM 带宽是训练瓶颈 ⇒ 用 `hash_full` 增量（§3-D4） |
| SHA-256（若自实现） | ~1.5–2 KB 代码 + 96 B 状态 | C:§6.1 | ROM |
| 内容：IR 对象总数 | **16,890** 个（`kind` 出现次数） | E:§6.1、S:§3.2 | — |
| 内容：剥冗余 `Children` 后节点实例 | **6,182**；互异子树 **875** | S:§5.2 | 程序体池可内容寻址共享（875 个 root） |
| 内容：内核 ROM | **≈ 88 KB**（core，模型估算）；含表现 ≈206 KB | S:§5.2 | **ROM/flash**。不确定性：不剥 `Children` → ≈130 KB；不删派生字段 → +118 KB |
| 内容（按每对象 24–40 B 估） | **360–600 KB** | E:§6.1 | ★ **必须 PSRAM**（SRAM 592 KB 还要分给战斗状态与栈） |
| 标准包注册量 | 16 状态 / **2** 常驻触发器定义 / 2 伤害 + 1 格挡修饰器 / 5 卡费修饰器 / 5 卡牌校验器 / 3 状态拦截器 / **0 分裂器 / 0 死亡前拦截器**（全在内容侧）/ 1 防御池（Block, AbsorbPriority=0）/ **58** 事件处理器 / 43 请求处理器 / 54 节点执行器 | M:§6.2；`StandardCombatPackage.cs:26-248` | 编译期静态表 ⇒ **ROM**（M:§6.4、M:§5.1「零对象」结论） |
| 内置样例内容规模 | 62 张卡 / 109 场遭遇 | M:§6.2 | — |
| CPU：oracle 吞吐 | **≈ 10,700 场/秒**（NativeAOT，本机） | 任务书实测；`make_corpus.py --bench` 打印同口径 | 重写侧目标：**全整数**，无浮点（P4 FPU 用不上） |
| CPU：一次命中 | S2 阶段循环 `3 × N_dmg`（标准 `N_dmg=2`，真正调用 2 次）+ 1 次池循环；声明式折叠内部成本 `O(S log S)` 状态分组 + `O(k log k)` 排序 | M:§6.1、§6.2 | 热点在 `GroupBy`/排序/LINQ/类型查找 —— 三项在 C/Rust 里天然消失（M:§6.5） |
| CPU：JSON 预热 | 每场战斗开始 1.7 s 中 **1.6 s** 花在 STJ 类型元数据反射 | E:§5.5 | 预编译后应为 **0** |
| 效果程序池规模 | 本文档内容用到 **73 个节点 opcode** / 875 互异子树（注册了 173 个战斗种类，多余的是引擎能力不是内容需求） | S:§3.2、§5.2 | ROM 表按需裁剪 |

## 6. 一致性契约（对拍怎么算通过）

### 6.1 `hash_golden` = 规范文本 → UTF-8 → SHA-256 → **小写十六进制（64 字符）**

规范文本是**逐行拼接、每行以 LF 结尾**（`'\n'`，**不是** `Environment.NewLine`）。字段顺序**固定**，集合元素以 `,` 结尾、空集合留空行。逐行定义（`CombatStateHasher.cs:26-164`）：

| 序 | 行 | 说明 |
|---|---|---|
| 1 | `id=` / `seed=` / `step=` / `result=` / `round=` / `turn=` / `phase=` | 枚举一律写成 `(int)` |
| 2 | `active=` | 可空 ⇒ 空字符串 |
| 3 | `status_num=` / `card_num=` / `chain_num=` / `exec_num=` | **注意：无 `summon_num`**（`NextSummonedCombatantNumber` 不参与，见 6.3） |
| 4 | `turn_order=` | id 逐个 + `,`；空则空行 |
| 5 | `gs=` + status 行 | 每条**全局**状态一行（列表原序） |
| 6 | `c=<id> def=<..> team=<..> lc=<int> hp=<cur>/<max>` | 每战员一行，**按 `TurnOrder` 遍历** |
| 7 | `res=` / `dp=` | `<key> <cur>/<max 或 "null">`，**按 key 的 `Ordinal` 序** |
| 8 | `s=` + status 行 | **`AllStatuses`（含 pending）的列表原序** |
| 9 | `tags=` / `cnt=` | tags 逐个 + `,`（实测恒空）；counters 为 `<key>=<value>`（按 key 序） |
| 10 | `cz=<id>` + 7 区 | 按 `TurnOrder`；`draw/hand/disc/exh/ban` **恒写**；`queue`/`aside` **为空时整段省略** |
| 11 | 卡行 | `<zone>=<id> <def>[ m:<mark>][ mc:<k>=<v>][ msrc:<id>][ qat:<id>]`（区名本身即 key ⇒ 卡不写 `Zone`） |
| 12 | `tr=` | 临时规则：`Id EventType act=… expR=… expT=… owner=… [ownerbound] inst=<R>.<T> [dead]` |

**status 行**：`<id> <def> stk=<n> dur=<n> chg=<n> pol=<int>` + 当 `PendingTurns>0` 追加 ` pend=<n>`。
**刻意跳过**（哈希不覆盖）：状态的 `Tags`/`Counters`/`SourceCombatantId`/`SourceCardId`/`AppliedRound`/`AppliedTurn`/`Visibility`。

### 6.2 必须**逐字节哈希相等**的清单

| 项 | 要求 | 出处 |
|---|---|---|
| `expect.hash` | **`hash_golden` 逐字节相等**（128 条全量） | 语料 + C:§5.3 |
| `expect.random_step` | 相等（**头号确定性 bug 的探针**：抽随机数的**次数**不一致） | `OracleExports.cs:172-178` |
| `expect.steps` / `log_count` / `pending` | 相等（`pending` 应恒为 0；语料实测 128/128） | 语料 |
| `expect.hero_hp` / `enemy_hp` / `round` / `turn` / `problems` | 相等（`problems` 是布尔标志 `HasProblems ? 1 : 0`，不是计数） | 语料 + `OracleExports.cs:91` |
| §4 全部 O 行 + B 行 | 行为级相等（顺序类向量**单独跑**，别混进数值向量） | M:§7 末 |
| E/C/M 三份规格书的 46 条向量（15 + 14 + 17） | 语义期望相等；`hash_golden` 一栏需先在 C# 上跑出来填死 | E:§7、C:§7、M:§7 |

### 6.3 `hash_full` 必须覆盖（`hash_golden` 的**漏检项**）

| 漏检项 | 后果 | 出处 |
|---|---|---|
| `NextSummonedCombatantNumber` | 召唤物 id 发号器分叉，哈希看不出来 | C:§5.4；快照 `Snapshotter.cs:57` / 哈希器无此项 |
| **`CardPlayTurnStats` 整块**（本回合/上回合出牌数、按定义/标签计数、draws/damage/hits/gained/spent/claims、整场出牌表） | "超过上一回合""又以 Attack 开场""本回合第三张"这类规则在还原后**全读 0**，而哈希**不报错**（真实事故） | C:§5.4；`CardPlayTurnStats.cs:196-202` |
| `TriggerActivity` | 宿主展示用的"某规则触发多少次"，还原后重新计数 | C:§5.4；`Snapshotter.cs:65-70` |
| `CurrentPhaseTeam` / `_endedThisPhase` | **快照与哈希都没有** ⇒ 同时队伍模式中途存档无法忠实还原 | C:§2.1.2、§5.2 |
| 状态 `Tags`/`Counters`、战员 `Position`/`IntentKey` | 位姿/标记变化不可见 | C:§5.4 |

`hash_full` 允许换非加密哈希（xxHash/CRC）并做**增量更新**（每次状态变更更新 rolling hash），不必每步重算（C:§5.4 建议）。

### 6.4 允许不同（**仅限 §3 豁免列打「需要」的行**）

| 偏离 | 允许不同的内容 | 记期望值的方式 |
|---|---|---|
| D1 | 多防御池清理的**入队顺序** | 按 `(AbsorbPriority, Id)` 新序记哈希 |
| D3 | 含 `ApplyTriggerEventStatus` 的程序 / 读 `gainBlock` 结果键 | C# 侧抛异常，重写侧成功 ⇒ 用例**不比对** C# 输出，按 §3-D3 记文档期望 |
| D8 | 重复 `AddCard` 判重、7 区拼接序 | 新用例按新实现记期望，并注明这是行为等价而非字节等价 |
| D10 | 日志**文本**（MCU 构建可只计数） | 只比 `log_count` + 类型序（对拍构建必须存文本） |
| D12 | `CardPlayTurnStats` 的存储形态 | 只比 `hash_full` + 逐规则可观察值，**不比 `hash_golden`** |
| D14（遍历物化） | 无 | 纯实现机制，不改变可观察行为 |
| D15（限额默认值） | 固件若把 1024 改成 128 | 超限用例两侧**显式注入**限额参数，不依赖默认值 |

### 6.5 语料的生成方式与覆盖

| 项 | 值 |
|---|---|
| 生成链 | `native/make_corpus.py`（ctypes 调 NativeAOT oracle `native/RogueDeck.Oracle` 的 `rd_oracle_*` 导出）→ `corpus/golden_v1.jsonl` |
| 规模 | 变体 `{0..7}` × 种子 `{1,7,42,1234}` × 数值组 `{(30,6,12,5),(30,9,20,5),(50,6,40,12),(20,3,8,2)}` = **128 条**（`make_corpus.py:86-117`） |
| 用例形状 | `{"case", "inputs":{variant,seed,hero_hp,card_damage,enemy_hp,enemy_damage}, "expect":{hash,steps,problems,hero_hp,enemy_hp,round,turn,random_step,pending,log_count}}` |
| 变体语义 | `variant % 4` 决定脚本：0 = 出牌+结束回合+敌行动；1 = 敌挥两次；2 = 出三张+两轮；3 = 只结束回合+下一轮。`variant >= 4` 打开**洗牌+回合补能量+12 张牌组**（否则引擎**从不抽随机数**，`random_step` 恒 0） |
| 生成器自检 | ① 确定性：同一 case 跑两次必须完全一致（否则 assert 失败）；② 区分度：不同哈希数必须 > 半数；③ 维度：同 seed 下 4 个变体哈希互不相同 |
| 本机实测统计 | 128 条**哈希全互异**；`random_step ∈ {0(44), 1(76), 2(8)}`；`steps ∈ {2,3,4,7}`；`log_count ∈ {12..17,32,36}`；`pending` 全 0；`problems=1` **24 条**（变体 2/6） |
| 吞吐 | **≈ 10,700 场/秒**（任务书给定实测；生成器自身打印同口径吞吐） |

### 6.6 新增用例的最低要求

1. **必须能区分**：新用例在 C# 侧的 `hash_golden` 必须与既有 128 条**不重复**，且同 seed 不同变体互不相同（沿用 `make_corpus.py` 的三条自检）。
2. **必须有确定性自检**：同一输入连续跑两次，全部观测量与哈希完全一致。
3. **必须落盘完整快照**（不只哈希）—— 因为 `hash_golden` 有 §6.3 的漏检项（C:§7 建议①）。
4. **必须补 C# 侧跑出的期望值**：规格书的向量只给**语义期望**，`hash_golden` 一栏需在真实实现上填死（C:§7 建议①）。
5. **顺序类向量单独跑**：向量 #16/#17（触发器顺序 / effect 先于 event）别混进数值向量（M:§7 末）。
6. **三条最易被"顺手优化掉"的语义必须专测**：计数单次求值（V5）、注册顺序无关（V10）、causal/batch 差异（V11）（E:§7 末）。
7. **必补两条原文没有的向量**：(a)「**非当前行动者出牌**」记录 C# 实际行为（会被接受，B1）；(b)「多防御池同时 `ClearsOnOwnerTurnStart`」的入队顺序，按 §3-D1 新序（C:§7 建议④）。
8. **覆盖缺口必须补齐**（§7-6）：修饰器、格挡、状态、队列卡、法令、拦截器、触发器、控制流节点 —— 现有 128 条**一条都没覆盖**；需要扩 oracle 变体（新语料 = `golden_v2.jsonl`）或独立向量表。

## 7. 未完事项与已知风险

| # | 事项 / 风险 | 现状与依据 | 影响 |
|---|---|---|---|
| 1 | **内容 schema 的二进制格式由另一路（W2）产出** | `content-schema.md` §5 只是**提案**：88 KB 是模型估算（计数实测、字段长度是模型假设），§5.2 明列不确定性；ROM header / 符号表 / opcode 布局表 / 语境标签编码**都还没定**；且「同一程序体的上下文由**使用点**决定」不可写进共享体（S:§7.1 末） | 本文已冻结的**语义接口**（`Id(u16)`、`NodeKind(u8)`、`OutcomeKind`、`ResultKeyId`、`EventKind`）可直接用；**编码**未冻结 |
| 2 | **位置系统未实现** | 9 个位置选择器 + 4 个基元（E:§2.5）；唯一浮点在 `ForwardSign`（E:§2.1）；flat 战斗恒空 | v1 不受影响（§3-D2）；将来实现必须整数叉积 + 专门对拍 |
| 3 | **四个触发族尚未逐行核对** | 任务书点名 `StatusLifecycleTriggeredEffects.cs`(16,934 B)；同量级还需核对的：`TriggeredProgramContextAdapters.cs`(23,914 B)、`ExtraTriggeredEffectContexts.cs`(15,151 B)、`TriggeredEffects.cs`(7,069 B)。`Effects/` 下共 **23 个** `*TriggeredEffects.cs` | 本次只做「按规格书交叉引用」，**没有**逐行核对 58 个 handler 的实现体 ⇒ `EventAmount` 的 11 种分支表、`TriggerEventStatus.Of`、每事件的字段集**必须在 W1 逐事件复核后才能冻结为常量表**（§6.2 的事件语义因此只是部分冻结） |
| 4 | **上游仓库仍在演进** | 基线只保证到 commit `fd43e68…`（2026-10-09）；浅克隆无历史；基线之后可能有新 commit | 新 commit ⇒ 按 §1 变更规则视为新基线（升版本 + 重生成语料 + 重跑对拍） |
| 5 | `MaxProgramSteps=1024` 会被**合法内容**突破 | 实测单程序 **1,725 节点**（最深 9 层）⇒ 1024 的步数门禁需要复核（注：步数是运行期计数，与静态节点数是两个量，但内容侧必须复核） | §5.1 该行未定；v1 先按 1024 并对内容编译器设同一门禁 |
| 6 | **语料覆盖面窄（最重要的风险）** | oracle 只造「一张 `strike`（单个 `DealDamage`）+ 一个 ogre 的 `smash`」；无状态、无格挡、无队列卡、无法令、无触发器、无控制流节点。变体 0–3 **完全不消耗随机数**，4–7 才开洗牌/补能量（`OracleExports.cs:60-83`） | `golden_v1` 只能验收「出牌/回合/轮次/伤害/死亡/能量/洗牌」；**§6.6-8 列出的七类语义一条都没被覆盖**。在补齐前，「语料全绿」**不等于**内核正确 |
| 7 | **`problems` 是宿主级观测** | 它是**布尔标志**（`_problems = report.HasProblems ? 1 : 0`，`OracleExports.cs:91`），不是计数。128 条中 **24 条 `=1`**（全是变体 2/6，且这些用例的敌方 HP 已为 0 而 `steps` 仍等于脚本全长 ⇒ 由 `ScenarioRunner` 的早停分支产生，如 `Combat already ended (…); step not executed.`）；`ScenarioRunner` 还负责「卡不在手里」「付不起/被校验器拒绝」等判定（`ScenarioRunner.cs:40-63,113-125`） | 重写侧若不带这层宿主逻辑，`steps`/`log_count` 会对不上 ⇒ §6 要求对拍 harness **复刻 `ScenarioRunner` 的早停与问题记录** |
| 8 | 同时队伍回合模式完全 OUT | `CurrentPhaseTeam`/`_endedThisPhase` 既不入快照也不入哈希（C:§2.1.2、§5.2） | 该模式的**中途存档忠实还原永远无法验证**（不是延后造成，是引擎本身如此） |
| 9 | **trace 契约未冻结** | E:§7 建议比对「规范化 trace」（8 种 kind + 四元身份 `ExecutionId/NodePath/ScopeId/ChainId`，`EffectProgramTrace.cs:5-42`，两者必须是**整数**身份）—— 但三份规格书都**没有**给出哪些 kind 在哪些代码路径发出、字段级定义 | v1 只冻结「四元身份必须保留（可换整数）」；字段级 trace 清单留待 W1 |
| 10 | 快照 POD 布局 / 存档格式未定 | `hash_golden` 要求能逐字节产生规范文本（C:§6.1）是**已定**的；但快照结构体的二进制布局、旧 JSON 存档兼容、`CombatReplayRunner`/`CombatSaveJson` 全在 OUT | `hash_full` 的字段顺序、增量哈希策略需 W1 定 |
| 11 | 未逐行核对的相关文件 | `CombatantLifecycleEffects.cs`(7,903 B)、`CardZoneEffects.cs`(16,756 B)、`CardPlayTurnStats.cs`、`TriggeredEffectActionRequestFactory.cs`(6,168 B)、`TemporaryTriggeredProgram.cs`(6,884 B) | 本文中涉及这些文件的断言均来自规格书转述，未二次核对源码 |
| 12 | `MaximumTriggerDepth` 不入快照 | 是**构造参数**（C:§2.1.2），快照里没有 ⇒ 重写当常量 | 若内容需要别的值，快照/哈希都不覆盖；§6 对拍只在默认 64 下有效 |

---
**改动记录**（同版本内只允许补出处/改措辞）

| 日期 | 版本 | 改动 |
|---|---|---|
| 2026-10-17 | v1 | 初版：基线冻结、IN/OUT、15 条偏离、53 条顺序契约 + 4 条边界契约、限额预算表、一致性契约、12 条未完事项 |

### 2.4 §187 补记：Ascension 影响战斗的方式

`A2/3/4`（伤害）与 `A17/18/19`（招式表）不改 §2.1 任何一条语义，它们只改**内容选哪一个节目**：

* `CombatState.ascension`（`u8`，建战斗时写一次）。它**不在规范文本里** —— 参考没有这个字段，
  写进去会移动全部 85 份语料；`hash_full` 落地时必须覆盖它。
* `EACT.ProgramAsc`：同一个动作的**变体列表** `[{AscensionMin, Program}]`（§192 起；之前是
  "一个信封 + 一个阈值"，装不下两个档位）。取 `AscensionMin <= ascension` 里阈值最大的一个。
* `intent.ascensionAtLeast`：让内容能"在 A18 以上用另一条规则"。

所以 Ascension 对核心的影响**只在入口**：一个动作要么走基础节目、要么走变体，
两者都是**已有的**执行器（`intent::execute_action` → `exec::execute`）。

§193 另加一条：**开局掷骰**（`ENCT[i].Enemies[j].Rolls`）在建战斗时写进战斗员的计数器
（`battle::apply_spawn_rolls`，每抽一次 `random_step += 1`），动作里的 `combatantCounter`
读到它。规则本身不动 §2.1 —— 它只是给"伤害是多少"提供了一个**在第一次出招之前就固定**的值，
这正是 wiki 的 *chosen at the start of combat*。
