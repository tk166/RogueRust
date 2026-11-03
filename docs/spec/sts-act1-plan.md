# StS 第一幕（出发 → Boss）里程碑计划

> **本文是什么**：把"复刻 Slay the Spire 铁甲战士第一张地图"拆成可执行的里程碑，并把
> "哪些内容现有引擎就能跑、哪些要补能力"对号入座。
>
> **本文不是什么**：不是设计文档、不含实现代码、不动 `kernel/`。
>
> **数值唯一真相**：`docs/spec/sts-act1-inventory.md`（下称 **`inv`**）。本文**不重新查任何数值**，
> 只引用；引用格式 `inv:§4.1`。凡本文需要而 `inv` 没有的数，一律标 `【待补】` 并写明在哪一步能查到。
> 引擎侧事实一律带 `文件:行号`，且都是我**这次实际读过**的（不是转抄）。

---

## 0. 三句话结论（先看这个）

1. **卡与战斗不是瓶颈，敌人 AI 与触发事件才是。** 25 个敌人实体里 **10 个今天就能跑**（**一个精英都没有**），
   **4 个各差一个小能力**（其中 `sentry` 是唯一"补一件小事就能打的精英"），**11 个差一个大能力**；
   而这 11 个里有 **7 个只差同一件事：事件队列**（受伤/出牌/死亡三种触发）。
2. **最大的方法论变化不在工程量，而在"能不能对拍"**：战斗仍可跨语言逐字节对拍（四层），
   但**敌人的动作选择一旦要"加权随机 + 不能连用 N 次"，就永远不可能对拍**（C# 参考实现里没有这个模型），
   run 层更是从头到尾没有 oracle。⇒ 从 M1 起，"证据"的形态从"和 C# 比"变成"规则 + 确定性回归 + 分布闸门"。
3. **M1 的 Boss 只能选 Hexaghost**：另外两个各自卡在"大能力"上（Guardian 要出牌/受伤触发 + 阶段机，
   Slime Boss 要战斗中途改阵容），只有 Hexaghost 的机制全部落在"小能力 + 内容"这一侧。

---

## 1. 现状锚点（本文其余部分都建立在这张表上）

| # | 事实 | 锚点（我实际读到的） |
|---|---|---|
| 1 | 节点执行器 **15 种**，全部实现 | `kernel/rd-core/src/ir.rs:82-112`（`NodeKind` 15 个变体）、`exec.rs:898`（`dispatch` 穷尽） |
| 2 | 表达式：`const/compare/add/subtract/multiply/divide/min/max/and/or/not/combatantCounter/combatantStatusStacks/combatantCurrentResource` 等已实现 | `expr.rs:321`（`INT_KINDS` 白名单）、`eval_int`（`expr.rs:408` 起） |
| 3 | `currentHealth` / `maxHealth` **已实现**（2026-10-19）；字段名 `Selector`，是镜像自己给同一个概念用的名字（11 个 opcode 在用，其中 3 个是已在读的单目标标量读）。`missingHealth` 仍 `UnsupportedKind`（镜像里连 opcode 都没有，且等于 `subtract(maxHealth, currentHealth)`） | `expr.rs` 模块头第 4 条；实现是 `eval_int` 的两个分支（`expr.rs:504`/`:507`，都走 `health_target` 那个单目标读）；测试 `expr::tests::divider_is_current_health_divided_by_twelve_plus_one` |
| 4 | 选择器 **10 种**（`sel.source/eventTarget/iterationTarget/allAllies/allEnemies/allCombatants/lowestHealthEnemy/alliesWithStatus/enemiesWithStatus/withStatus`）；`sel.random` **不支持** | `sel.rs:344-353`；`sel.rs:991` |
| 5 | 敌方动作选择：入参 `(遭遇, 槽位)`、`Priority` 降序、落回 `Actions[(round-1) % count]`、**零 RNG、不写状态** | `intent.rs:509`（`select_action`）、模块头 `intent.rs:13-24`、`intent.rs:99`（D6） |
| 6 | 触发事件**只有 4 个**接了钩子：`TurnStarted` / `TurnEnded` / `RoundStarted` / `RoundEnded`；其余 21 个（`DamageTaken`/`DamageDealt`/`CardPlayed`/`Downed`/`BlockGained`…）解析成功但归 `NotHandled` | `host.rs:300-331` |
| 7 | 意图**不进状态**：没有"当前意图"字段可打断 | `state.rs` 无 `intent` 字段；`snapshot.rs:91`（`IntentKey` 在"未建模"清单里） |
| 8 | `TurnHost` 9 个必做钩子 + 8 个默认钩子（回合起 7 步 / 回合末 4 步的顺序就长在这上面） | `turn.rs:150-279` |
| 9 | 出牌校验器**硬编码 5 个**：`Stun / Decree / PlayCondition / OneAttackPerTurn / Unplayable` | `play.rs:936-988` |
| 10 | `LifecyclePrograms`（"牌在手里过回合"节目）**已实现**（2026-10-19）：解 `CARD.LifecyclePrograms[TurnEndInHand]` 并派发节目；镜像 62/62 卡是 `{}` ⇒ 今天一条都不跑 | `host.rs::try_hand_turn_end_lifecycle`；`host.rs::card_lifecycle_turn_end_program` |
| 11 | 建战斗入口 `FightPlan` 只有 `(id, max_health)`；**没有起始状态、没有 innate 卡**（两处都响亮拒绝） | `battle.rs:121-134`、`battle.rs:553-560`、`battle.rs:645-653` |
| 12 | 敌人**动作程序**可以跑（`execute_action`）、`setCombatantCounter` 支持**相对加**（`Relative` 默认 true） | `intent.rs:725`、`exec.rs:1153-1215` |
| 13 | 内容编译器把 `*.roguedeck.json` 编成 RDCF，**opcode 表由文档本身派生**（一个 kind / 一种对象形状 = 一个 opcode），opcode 是 **u8** ⇒ 硬上限 256 | `tools/contentc/compile.py:204`（`LayoutDeriver`）、`compile.py:281`（超限 `SystemExit`） |
| 14 | 当前镜像用掉 **131/256** 个 opcode（73 IR kind + 50 对象形状）、3140 个串、62 卡 / 23 状态 / 394 敌动作 / 109 遭遇 / 49 遗物 | `tools/contentc/out/manifest.json` |
| 15 | 跨语言对拍有 **4 层**（`FIGHT_DIFF` / `CARD_DIFF` / `CARD_MULTI` / `ENEMY_DIFF`），各带闸门 | `native/fight_diff.py:1634/1645/1657/1667` |
| 16 | 聚合验收一条命令 9 条闸门，加测试要顺手抬 `-UnitsFloor` | `tools/acceptance.ps1:1-13` |
| 17 | 浏览器侧已有 ABI 实现 + 静态页（写死一个 `queue_imp` 场景） | `web/index.html`、`web/rd_wasm.wasm`、`kernel/rd-wasm/src/lib.rs` |

### 1.1 对本文输入（任务书）里的事实更正 —— 现实与描述冲突处，以现实为准

| # | 任务书/旧文档的说法 | 现实 | 
|---|---|---|
| C1 | "`native\fight_diff.py` 已有**三层**" | **四层**：`FIGHT_DIFF`(182 条) / `CARD_DIFF`(逐卡) / `CARD_MULTI`(逐卡跨回合) / `ENEMY_DIFF`(逐敌动作)。`fight_diff.py:1634-1667` |
| C2 | "`rd-wasm` 的 Gap 1：`content.rs` 没有 encounter→actions 读器" | **已过期**。`content.rs:754` 有 `encounter()` 行读器，`intent.rs` 能自己从 ENCT 行里读敌人名单并选动作。真正缺的只是 **wasm 里的接线**（`rd-wasm/src/lib.rs:545-546` 仍写死 `-1`） |
| C3 | "`currentHealth` 等 3 个表达式在 kind 表白名单里" | **已过期（2026-10-19 更正）**：`currentHealth` / `maxHealth` **实现了**，字段名 `Selector`（§9-4、`expr.rs` 模块头第 4 条）。只有 `missingHealth` 仍然"白名单里但 `UnsupportedKind`"——它连 opcode 都没有，而且等于 `subtract(maxHealth, currentHealth)`，所以**别写它**，写那两个减法。上一版本行说的是"不要照着白名单写内容（会响亮失败）"——这句话对 `missingHealth` 仍然成立 |
| C4 | "`inv` §3.5 说卡牌奖励池按'是否第一幕'筛" | `inv:§3.5` 自己已经标了这条更正（**只有角色 + 稀有度两维**）。本文照 `inv`。 |
| C5 | 现有 `sts/` 目录像是"半成品 run 层" | `status_catalog.rs:552` 的注释写明：那是 **plan B，已放弃**。可当**格式先例**引用（`sts/content/cards.json` 的扁平 `{"op":…}` DSL），**不可当语义来源**（它的时钟是层数、不是 `DurationTurns`）。顺带：内核目录里**已经有这 8 个原型状态**的元数据（`status_catalog.rs:563`、查询入口 `:630`），`metallicize`/`ritual` 这种"参考包里没有、StS 才有"的 id 已经能查到 ⇒ 内容侧有现成模板 |

---

## 2. 能力 × 内容矩阵

口径：**"最小可行"= 做到"这一张地图能跑、且与原作的差异被登记在 §7 的降级表里"**，不是做完整方案。
工作量：**小** ≈ 一两个文件、不碰冻结语义；**中** ≈ 新增一个节点/表达式/钩子，要动冻结文档但不改顺序契约；
**大** ≈ 新增子系统（事件队列 / 阵容变更 / run 层），必须新开语义版本。

### G1 意图可被打断 / 敌人阶段机

| 项 | 内容 |
|---|---|
| **具体到谁** | `the_guardian`（Mode Shift 归零 ⇒ 打断当前意图 + 立刻切防御态 + 20 Block；防御态 Twin Slam 移除 Sharp Hide 并切回，切回时 Mode Shift +10，`inv:§4.3`）；`slime_boss`（HP ≤ 50% ⇒ 打断当前意图并分裂，`inv:§4.3`）；`lagavulin`（穿透格挡的 HP 伤害 ⇒ 打断睡眠 + 眩晕 1 回合，`inv:§4.2`） |
| **为什么是"大"** | 状态里**没有意图**（§1 第 7 行）：动作是每回合由 `select_action` **现算**的纯函数。"打断当前意图"在今天的模型里**没有指称对象**。而且打断的触发点是伤害管线内部（`exec::resolve_damage`，`exec.rs:515`），在那里加钩子会碰哈希基线 |
| **最小可行（降级版）** | **不改内核**：阶段用 `setCombatantCounter`（相对加，`exec.rs:1153`）表示，阶段切换发生在**回合边界**（下一个回合边界 triggers），动作靠 `IntentRules` 的 `selfHasCounter` 分支（`intent.rs:339`，**今天唯一能求值的条件**）。可观察差异：本回合剩余的那次出手仍会按旧阶段执行 ⇒ 登记为降级 |
| **最小可行（真做）** | 在 `state.rs` 给 `Combatant` 加"意图/阶段"字段 + 一个 `EnemyPhaseHost` 钩子，挂在伤害管线的 S8 之后。**会和 C# 对拍基线分叉**（C# 没有这个字段）⇒ 必须升 `SEMANTICS-v2` 并重跑语料 |
| **能不能对拍** | 降级版：只能和**自己的降级表**对。真做版：**不能**（C# 侧无对应模型） |

### G2 被动在"伤害 / 出牌 / 死亡"上触发（= 事件队列）

| 项 | 内容 |
|---|---|
| **具体到谁** | `louse_red`/`louse_green`（Curl Up：第一次受到攻击伤害 ⇒ 获得等量 Block，只一次）；`mad_gremlin`（Angry：每次受到攻击伤害 +1 Str）；`fungi_beast`（Spore Cloud：死亡 ⇒ 玩家 2 Vulnerable）；`gremlin_nob`（Enrage：玩家每打出一张 Skill ⇒ +2 Str）；`the_guardian`（Sharp Hide：玩家每**打出**一张 Attack ⇒ 受 3 伤害） |
| **卡侧** | `combust`（回合末失 1 HP 并 AOE）、`rupture`（失 HP ⇒ +Str）、`dark_embrace`/`feel_no_pain`（Exhaust ⇒ 抽牌/格挡）、`juggernaut`（获得 Block ⇒ 伤害）、`evolve`/`fire_breathing`（抽到 Status ⇒ …）、`flame_barrier`/`rage`（被打/出攻击 ⇒ …）。`inv:§3.3` |
| **为什么是"大"** | `host.rs:300-331`：21 个事件名**认得但没钩子**（解析成功、归 `NotHandled`）。这是本项目**最危险的一种静默**：内容里写一条 `DamageTaken` 触发器，它**永远不会跑、也不会报错** |
| **最小可行** | 不引入三队列，只加一个 `CombatEventHost`（`TurnHost` 的兄弟 trait），在 **3 个点**同步调用：①`exec::resolve_damage` 的 S8 之后（`DamageReceived`/`DamageDealt`）②`play::play_card` 成功之后（`CardPlayed`）③生命值归零之后（`Downed`）。顺序契约只新增一条：**hook 在 S8 之后同步跑**，与 O21（Trace→OutcomeSlot→日志→事件）的"事件"位置对齐。≈300 行 + 冻结文档新增一节 |
| **同时必须做的** | 内容编译器**白名单**：凡写出 `NotHandled` 的事件 ⇒ 翻译器**硬失败**（不是警告）。否则我们会在 M2 花一周调试"为什么 Curl Up 不触发" |
| **能不能对拍** | **不能**（C# 的等价物是三队列，语义更细）。只能规则测试 + 逐敌动作的"进入/退出状态"断言 |
| **覆盖量** | **25 个敌人里 7 个**只需要它（见 §3）⇒ 它是全项目投入产出比最高的"大" |

### G3 伤害依赖玩家状态

| 项 | 内容 |
|---|---|
| **具体到谁** | `hexaghost` 的 `Divider = 6 × (1 + floor(玩家当前HP / 12))`（`inv:§4.3`）；顺带它的"绿火计数"驱动 7 步序列（`inv:§4.3`） |
| **为什么是"小"** | `multiply` / `add` / `divide` 都已实现（`expr.rs` 的 `int_pair` / `divide`），缺的只有 `currentHealth`：**一个表达式 + 一个目标字段**。当初 `UnsupportedKind` 的唯一理由是**镜像里那个 opcode 的字段表是空的**（`expr.rs` 模块头第 4 条）—— 而 StS 内容是我们自己 authored，**字段名由我们自己定** ⇒ "测不出来"这个理由在这里不成立。**2026-10-19：做完了** |
| **最小可行（已落地）** | `currentHealth` / `maxHealth` 两个，目标字段名 = **`Selector`**（不是"例如 `Target`"：镜像里 11 个 opcode 已经在用 `Selector` 表示同一个概念，其中 3 个是本内核已在读的单目标标量读 ⇒ 用它不是发明新名字）。实测 ≈30 行 + 6 条测试（其中一条把 `(currentHealth / 12) + 1` 整棵树在 HP=11/12/143 三点上钉住）。**`missingHealth` 没做**：镜像里没有它的 opcode，而且它等于 `subtract(maxHealth, currentHealth)` |
| **能不能对拍** | 不能（镜像里没有非空形状）⇒ 规则测试。已落地的那一种拼法是 `(currentHealth / 12) + 1`，在 HP=**11/12/143** 三点上期望 **1/2/12**（`expr::tests::divider_is_current_health_divided_by_twelve_plus_one`）。⚠️ **本文上一版这一格写的是"HP=12/24/25 ⇒ 12/18/24"，与它自己写的 `6×(1+floor(HP/12))` 公式不自洽**：floor 下 25 ⇒ `6×3 = 18`，只有**向上取整**才能得到 24（`6×(1+ceil(25/12))`）。原作到底是 floor 还是 ceil **未验证**（`inv:§4.3` 的表述没定这一点）⇒ M1 写内容前必须先在实机/权威资料上确认，**不许照这一行抄数字** |

### G4 战斗中途改阵容（Split）

| 项 | 内容 |
|---|---|
| **具体到谁** | `acid_slime_l` / `spike_slime_l`（HP ≤ 50% ⇒ 死 + 生成 2 只 M，HP = 分裂瞬间当前 HP）；`slime_boss`（⇒ 1× Acid L + 1× Spike L，HP = 当前 HP）。`inv:§4.1/§4.3` |
| **为什么是"大"** | 三件事都缺：①**触发点**（HP 阈值）—— 要么靠 G2 的 `DamageReceived`，要么"每个动作后检查"，后者是**在驱动层新增战斗语义**，违反 `battle.rs:9-16` 的铁律；②**新战员带当前 HP** —— `FightPlan::PlanCombatant` 只有 `max_health`（`battle.rs:121-134`），`Combatant::new` 走的是 `current = max`；③**回合序插入位置**（`set_turn_order` 存在，`state.rs:1758`，但"插在死者原位还是队尾"是语义） |
| **可行性（已核对，不是猜测）** | `add_combatant`（`state.rs:1708`）/ `set_turn_order`（`:1758`）都是公开 API，`MAX_COMBATANTS = 12`（`state.rs:95`）够用（L→2×M，最坏 4 只同时在场）。**所以"大"不在状态容器，在语义与验收** |
| **最小可行** | 只做"分裂 = 死 2 只 + 生成 2 只 + 生成者放队尾"，HP 阈值用 `intent.healthPercent`（**同样是"测不出字段名"而被冻的 10 条件之一**，`intent.rs:270-291`）在**回合边界**判定 ⇒ 降级：分裂可能晚一回合发生 |
| **能不能对拍** | 不能 |

### G5 非玩家目标 / 非战斗终态

| 项 | 内容 | 工作量 |
|---|---|---|
| **给另一个敌人上格挡** | `shield_gremlin` 的 `Protect`（**永远** Protect 队友、绝不 Protect 自己，`inv:§4.1`）。已有 `sel.allAllies`（`sel.rs:344`）但**含自己**；缺一个 `sel.otherAllies`（或等价过滤）。附带：`conditional` 存在（`exec.rs:985`），但"目标 == 来源"这种比较表达式没有 ⇒ 走选择器而不是表达式 | **小** |
| **偷金币 + 逃跑** | `looter`（`Thievery 15`：每次攻击偷 15 金币；`Escape` 带走金币并结束战斗；击杀则全数归还，`inv:§4.1`）。`CombatantLifecycleState::Escaped` **已存在**（`state.rs:465`），但"金币"是 run 层、"战斗以敌方逃跑结束"要一个新的终局类别（今天只有 `Ongoing/Victory/Defeat/Draw/Aborted`，`state.rs:446-452`） | **大**（跨 run 层，必须等 M2b） |

### G6 run 层（完全没有参考实现可对拍）

| 项 | 内容 | 工作量 |
|---|---|---|
| **地图** | 7 列 × 15 行、6 条路径、不可交叉、前两条起点不同、裁孤点（`inv:§7.1`）；固定层 1 战斗 / 9 宝箱 / 15 篝火 / 16 Boss / 17 Boss 宝箱（`inv:§7.2`）；类型掷点 53/8/12/5/22%（`inv:§7.3`）；5 条覆写规则（`inv:§7.4`）；`?` 房 10/2/3% 累计递增（`inv:§7.5`） | **中**（规则都写清了；难在**验证**，见 §5） |
| **房间** | 篝火（Rest 30% / Smith，`inv:§8.1`）、商店（价格区间 + 删卡 75→+25，`inv:§8.2`）、宝箱（三种箱型，`inv:§8.3`） | **中** |
| **事件** | 26 个事件、14+ 分支（`inv:§8.4`）。⚠️ **事件抽取权重三个来源都没给**（`inv:§12-1`）⇒ 只能等概率，且必须标成推断 | **中**（分支全是"改动 run 状态"，没有战斗语义；但**分支数量**是主要成本） |
| **奖励 / 药水 / 遗物** | 金币 10-20 / 25-35 / 95-105；卡牌稀有度 3/37/60（普通）10/40/50（精英）100% Rare（Boss）+ 偏移 −5%→+40%；药水 40% 基准 ±10%、65/25/10；遗物 140 件按渠道分池（`inv:§6/§9`） | **大**（量在内容：140 遗物 + 33 药水，绝大多数是 run 层被动） |

### G7 敌方 AI 的"加权随机 + 历史约束" —— **我加的，且我认为它是最容易被忽略的一条**

| 项 | 内容 |
|---|---|
| **现实** | `inv:§4.1` 里 19 个普通敌人的 AI 大多是"**30%/40%/30%** + **同一招不能连用 N 次**"这种形状；而本内核的决策层是**确定性循环 + 条件规则、零 RNG**（`intent.rs:21-24`），`EACT` 行也**没有权重格**（`docs/spec/enemy-intent.md:34,529-551`）。⇒ **两套模型不兼容**，这不是"参数没填" |
| **为什么它不是"中"，而是"方法论问题"** | ① C# 参考实现里**没有**加权选择 ⇒ 加了以后**无对拍物**，只能靠统计闸门；② 让决策消费 `random_step` 会把"敌人这一步消耗了几个随机数"写进哈希 —— 一旦和之后的内容对不上，**哈希序列会整体漂移**，而这是本项目最贵的回归 |
| **最小可行（推荐 v1 采用）** | **不加**。每个敌人都 authored 成**确定性脚本**（用 §G1 的 counter 惯用法：`Actions` 顺序 + 最多 8 条 `IntentRules`，`intent.rs:139`），并**逐敌登记**"我们的出招分布 = 原作分布？"到 §7 降级表。理由：原作**没有可对拍的实现**，忠实度的判据只能是"数值与约束"，而"约束"（不能连用）确定性脚本天然满足 |
| **真做（推荐推后）** | 给 ENCT 规则加 `Weight` + 一个"最近 N 次动作"环形缓冲，并让决策推进 `random_step`。**必须单独立项**，因为它改的是"确定性由 (seed,step) 唯一决定"这条最底层的承诺 |
| **附带结论（有用）** | 只要走"确定性脚本"，`cultist`（第 1 回合 Incantation，之后永远 Dark Strike）**不需要** `intent.round`：一个"回合计数"counter + 一条 `selfHasCounter` 规则就能表达。**桥是内容，不是内核** |

### G8 X 费 / 多段攻击 —— **多段不是缺口（重要更正）**

| 项 | 内容 |
|---|---|
| **多段攻击** | `twin_strike`（5×2）、`pummel`（2×4(5)）、`hexaghost` 的 Tackle（5×2）/ Inferno（2×6）、`the_guardian` 的 Whirlwind（5×4）/ Twin Slam（8×2）：**都不需要新节点** —— `sequence` 里放 N 个 `dealDamage` 就是它，且 O29（段间反应先跑完）与此一致。**本文最初打算把 `repeat` 当缺口，核对后发现是我记错了** |
| **X 费** | 只有 `whirlwind`（`inv:§3.3`；`inv:§3.3` 记"X 费"）。需要"按剩余能量重复"⇒ 一个 `repeat` 节点（重复次数是表达式）+ X 费在 `CalculateCosts` 里的展开 ⇒ **中**。M1/M2 可以先不做这张卡（第一幕 72 张奖励池里就 1 张） |
| **随机目标** | `sword_boomerang`（随机敌人 3 次）、`juggernaut`（随机敌人）、`havoc`/`infernal_blade`（随机牌）⇒ `sel.random` 今天 `UnsupportedKind`（`sel.rs:991`）⇒ **小 + 要消费 RNG**（同 G7 的顾虑：进哈希前先想清楚） |

### G9 建战斗入口的缺口（起始状态 / innate）

| 项 | 内容 |
|---|---|
| **具体到谁** | `sentry`（开场 Artifact 1，`inv:§4.2`）、`louse_red`/`louse_green`（开场 Curl Up 3–7，`inv:§4.1`）、`the_guardian`（Mode Shift 30）、`lagavulin`（Asleep + Metallicize 8）；卡侧 `brutality`（Innate）、`writhe`-类诅咒 |
| **现状** | `FightPlan` 没有起始状态字段，`battle.rs:553-560` 明确"非空即拒绝"；innate 卡同样拒绝（`battle.rs:645-653`） |
| **最小可行** | `FightPlan` 加 `starting_statuses: &[(combatant, status, stacks, duration)]`，建战斗第 7 步**直接施加**（不走"真管线"）。差异：C# 走管线会触发状态拦截器 ⇒ 登记降级。**小** |
| **innate** | 加 `MoveInnateCardsToTop`（洗牌后挪牌，`fight-driver.md:29`）⇒ **小**；但注意 StS 的 innate 牌是**起手必有**，与"挪到堆顶"等价 |

### G10 状态时钟的映射（**不是缺口，是必须写死的格式约定**）

| 项 | 内容 |
|---|---|
| **现实** | 本内核的状态有**三根独立轴**：`Stacks +=` / `DurationTurns max` / `Charges +=`，任一到 0 即移除（SEMANTICS-v1 O25）。而 StS 的"易伤 3 层"= **3 回合** |
| **实测依据 ①（修饰器与层数无关）** | `standard.vulnerable` 的修饰器是**固定** `ScalePercent 150`（`status_catalog.rs:131,154`），`standard.weak` 是 75（`status_catalog.rs:9-10`）—— 层数只当时钟，不缩放效果 |
| **实测依据 ②（内核的时钟只有一根轴）** | 内置的回合末衰减 `host.try_decrease_timed_statuses`（`host.rs:1200-1258`）**只减 `duration_turns`**，且只对内容声明了 `uses_duration` 的定义生效（同一函数体里那道 `continue` 门）；它**从不碰 stacks**。而 `standard.vulnerable` 自己在目录里就是 `axes: DURATION`（`status_catalog.rs:493-497`）⇒ 用它就拿到 `max` 合并 |
| **⇒ 唯一正确的映射** | 层数落在 **`Stacks`**（合并是 `+=`，正是 StS 语义），再用一个 `TurnEnded` 触发器 `modifyStatusStacks(-1)` 当"回合时钟"（层数归零即删实例，见 `exec.rs` 的 `modify_status_stacks_node` 文档第 4 条，与 StS 一致）。**不能**落在 `DurationTurns`：那边合并是 `max` ⇒ 连加两次"2 层"只给 2 回合（应为 4） |
| **为什么单列一条** | 这种错**不会让任何测试变红**，只会让数值整体偏低且"看起来很合理"。内容格式必须把这条写成**硬约定 + 成对测试**（施加 2 层→再施加 2 层 ⇒ 断言 4 层、且断言它**不是** 2 层） |

---

## 3. 第一幕内容按能力分档（**这是 M0/M1 能做多大的依据**）

### 3.1 分档定义

| 档 | 定义 | 判据 |
|---|---|---|
| **A** | **不需要任何新内核能力**：现有 15 节点 + 4 个触发事件 + `selfHasCounter` 规则 + 标准状态集 + 内容侧惯用法（回合计数 counter） | 只写内容就能跑完整机制 |
| **B** | 差 **一个小能力**（§2 的 G3/G5-格挡/G8-随机/G9，各 ≤ 半天~1 天） | 一个能力就通 |
| **C** | 差 **一个大能力**（G2 事件队列 / G4 阵容变更 / G5-逃跑） | 一个子系统就通 |

### 3.2 25 个敌人实体，逐个点名（`inv:§4.1/§4.2/§4.3`）

| # | `id` | 档 | 卡在哪 | 备注（跑起来需要什么） |
|---|---|---|---|---|
| 1 | `spike_slime_s` | **A** | — | 只有一招 ⇒ 无需 AI 桥，**完全忠实** |
| 2 | `fat_gremlin` | **A** | — | 同上 |
| 3 | `sneaky_gremlin` | **A** | — | 同上 |
| 4 | `blue_slaver` | **A** | — | 两招循环（`Actions[(round-1)%2]`）；只有**分布**与原作不同 |
| 5 | `acid_slime_s` | **A** | — | 两招交替 = 天然循环；首回合的 50/50 退化成固定首招（降级） |
| 6 | `acid_slime_m` | **A** | — | 三招循环 + `Slimed` 进弃牌堆（`createCardInstance`+`moveCardToZone` 已够） |
| 7 | `spike_slime_m` | **A** | — | 同上（`Frail` 是标准状态） |
| 8 | `jaw_worm` | **A** | — | 首回合 Chomp 用 counter 规则；之后 3 步循环天然满足"不能连用"三条约束 |
| 9 | `cultist` | **A** | — | `Ritual` = 状态 + `TurnEnded` 触发器（+3 Str）；首回合脚本同上 |
| 10 | `gremlin_wizard` | **A** | — | 纯计数脚本（2 充能→Blast→3 充能→Blast…），`conditional` 做计数归零 |
| 11 | `sentry` | **B** | G9 起始状态 | 三只**各自不同的 `Actions` 顺序**（ENCT 每敌独立）⇒ 首回合差异是 C0；只差开场 **Artifact 1** |
| 12 | `red_slaver` | **B** | 一个校验器 | `Entangled`（本回合不能打 Attack）= 把 `Stun`（`play.rs:952`）从"禁全部"缩到"禁 Attack 一类"，5 个硬编码校验器里加第 6 个 |
| 13 | `shield_gremlin` | **B** | G5 `sel.otherAllies` | Protect 另一个敌人；`sel.allAllies` 含自己 ⇒ 必须新选择器 |
| 14 | `hexaghost` | **B**（3 个小） | G3 + `Burn` 生命期 + Burn→Burn+ | 无事件队列、无分裂、无逃跑。**机制最"干净"的 Boss** |
| 15 | `louse_red` | **C** | G2（`DamageTaken`） | `Curl Up` 一次性 + Bite 伤害开场随机（后者可固定为 6，降级） |
| 16 | `louse_green` | **C** | G2 | 同上 |
| 17 | `fungi_beast` | **C** | G2（`Downed`） | `Spore Cloud 2` |
| 18 | `mad_gremlin` | **C** | G2（`DamageTaken`） | `Angry 1` |
| 19 | `looter` | **C** | G5 逃跑 + run 金币 | 唯一需要"非战斗终态"的普通敌人 |
| 20 | `acid_slime_l` | **C** | G4 Split | 顺带需要 G2 的触发点（HP 阈值） |
| 21 | `spike_slime_l` | **C** | G4 Split | 同上 |
| 22 | `gremlin_nob`（精英） | **C** | G2（`CardPlayed`） | `Enrage 2`（打出 Skill 时触发） |
| 23 | `lagavulin`（精英） | **C** | G2（`DamageTaken`）+ G1 | 睡眠期 +8 Block 本身是 A（`TurnStarted` 触发器）；差的是"穿透伤害唤醒 + 眩晕 1 回合" |
| 24 | `the_guardian`（Boss） | **C** | G1 + G2 | Mode Shift（伤害触发）+ Sharp Hide（`CardPlayed`）+ 阶段打断 |
| 25 | `slime_boss`（Boss） | **C** | G4 Split | 分裂打断当前意图 |

### 3.3 统计结果（**这是任务要的那个数**）

| 档 | 数量 | 名单 |
|---|---|---|
| **A（零新能力）** | **10 / 25** | `spike_slime_s` `fat_gremlin` `sneaky_gremlin` `blue_slaver` `acid_slime_s` `acid_slime_m` `spike_slime_m` `jaw_worm` `cultist` `gremlin_wizard` |
| **B（一个小能力）** | **4 / 25** | `sentry`(起始状态) `red_slaver`(校验器) `shield_gremlin`(选择器) `hexaghost`(表达式×3) |
| **C（一个大能力）** | **11 / 25** | `louse_red` `louse_green` `fungi_beast` `mad_gremlin` `looter` `acid_slime_l` `spike_slime_l` `gremlin_nob` `lagavulin` `the_guardian` `slime_boss` |

**C 档的 11 个按"差哪一个"拆开（这一列决定先补谁）**：

| 缺口 | 敌人 | 数量 |
|---|---|---|
| **事件队列**（G2） | `louse_red` `louse_green` `fungi_beast` `mad_gremlin` `gremlin_nob` `lagavulin` `the_guardian` | **7** |
| **阵容变更**（G4） | `acid_slime_l` `spike_slime_l` `slime_boss` | **3** |
| **逃跑 + run 金币**（G5） | `looter` | **1** |

> **一句话**：**一个事件队列 = 7 个敌人**（含 1 精英 1 Boss），**一个 Split = 3 个敌人**（含 1 Boss）。

### 3.4 遭遇层面的可用性（决定 M0/M1 的战斗池有多大）

| 池 | 遭遇（`inv:§5.2/§5.3`） | 编成 | 全 A 可跑？ |
|---|---|---|---|
| weak | `enc_cultist` | Cultist | ✅ |
| weak | `enc_jaw_worm` | Jaw Worm | ✅ |
| weak | `enc_small_slimes` | M + S（酸/刺各半） | ✅ |
| weak | `enc_two_louses` | Louse ×2 | ❌（C） |
| strong | `enc_blue_slaver` | Blue Slaver | ✅ |
| strong | `enc_lots_of_slimes` | Spike S ×3 + Acid S ×2 | ✅ |
| strong | `enc_gremlin_gang` | 4 gremlins | ⚠️ 含 `mad_gremlin`(C) 与 `shield_gremlin`(B) ⇒ 需排除两者（降级） |
| strong | `enc_exordium_thugs` / `_wildlife` | 两段各自随机 | ⚠️ 固定取 A 档那一段即可 |
| strong | `enc_large_slime` / `enc_red_slaver` / `enc_three_louses` / `enc_two_fungi_beasts` / `enc_looter` | — | ❌ |
| 精英 | `enc_gremlin_nob` / `enc_lagavulin` / `enc_three_sentries` | — | ❌（C）/ ❌（C）/ **⚠️ B（`sentry` 只差 G9 一件小事）** |
| Boss | `enc_the_guardian` / `enc_hexaghost` / `enc_slime_boss` | — | ❌（C）/ **⚠️ B（M1 就选它）** / ❌（C） |

⇒ **M0/M1 的战斗池 = 3 个 weak 遭遇 + 2~4 个 strong 遭遇 + 1 个 Boss（Hexaghost）**，
比"先用假敌人占位"好得多：**每一场都是原作真遭遇**。
⚠️ 由此得到一条不太舒服但必须说清的话：**M0 里没有精英**（10 个 A 档全是普通敌人 + 小史莱姆），
第一个能打的精英是 `sentry`，而它要等 G9（起始状态）—— 这决定了"补 G9 的成本"直接决定 M2a 的精英什么时候能上。

### 3.5 卡侧分档（只列会影响 M1/M2 的项，75 张不逐张列）

| 特性 | 代表卡（`inv:§3`） | 档 | 说明 |
|---|---|---|---|
| 直伤 / 格挡 / 上状态 / 抽牌 / 造牌 | `strike` `defend` `bash` `pommel_strike` `anger` | **A** | M0 的 10 张起手牌全在这一行 |
| 多段 | `twin_strike` `pummel` | **A** | `sequence` + N 个 `dealDamage`（见 G8） |
| 格挡当伤害 | `body_slam` | **A** | `combatantCurrentResource`（`expr.rs:296`）能读格挡 |
| 条件收益 | `dropkick` `uppercut` | **A** | `conditional` + `combatantStatusStacks` |
| Power（永久被动） | `inflame` `metallicize` `demon_form` | **A** | 做成"带 `TurnStarted`/`TurnEnded` 触发器的状态"（C# 参考实现没有 Power 概念，StS 的 Power 就是状态） |
| 消耗手牌 / 摸到手就触发 | `second_wind` `fiend_fire` `true_grit` | **A**（消耗）/ **C**（"消耗时触发"） | 前者靠 `forEachCardInZone`；后者要 G2 |
| Ethereal / 回合末在手里受伤 | `carnage` `ghostly_armor` `Burn` | **A** | `LifecyclePrograms` **已实现**（2026-10-19，`host.rs::try_hand_turn_end_lifecycle`）：`dealDamage{2, sel.source}` 这种节目直接可跑。剩余的是**内容侧**：把节目写进 `*.roguedeck.json` 并重编镜像 |
| 战斗中升级 / 永久成长 | `armaments` `rampage` `searing_blow` | **C** | 本内容里"升级"是**另一张 CARD 行**（`paper_cut` vs `paper_cut+`，`rd-wasm/src/lib.rs` Gap 5）⇒ 要就地改 `definition_id`。`searing_blow` 多级升级 `inv:§12-5` 更是 `【待补】` |
| X 费 / 随机目标 | `whirlwind` / `sword_boomerang` `juggernaut` | **C** / **B** | 见 G8 |
| 特殊修饰 | `heavy_blade`（力量 ×3）`perfected_strike`（数"Strike"字样）`blood_for_blood`（失 HP 降价） | **B/C** | 都需要"按卡定制的修饰器"或"扫描牌堆"，不在标准管线里 |

---

## 4. 里程碑

设计原则（沿用项目既有纪律）：
* **每个里程碑的判据必须是可跑的命令 + 一句"证据串"**（不只退出码 0，见 `tools/acceptance.ps1:80` 的 MustMatch 惯例）。
* **产物陈旧/缺席必须响亮失败**，不许"跳过"。
* **加测试就抬 `-UnitsFloor`**（这一步最容易忘，已犯过多次）。

### 4.0 我对任务书方案的反驳

| # | 任务书方案 | 我的意见 | 理由 |
|---|---|---|---|
| R1 | M0 只做"能跑赢一场" | **赞成，但要拆成 M0a/M0b** | "内核能跑完一局"（`rd-fightdump`）与"UI 能看到"（`rd-wasm` 接线、`web/index.html`）**故障模式完全不同**：前者红了是内核问题，后者红了是 wasm/JS 接线问题。混在一起时"M0 卡住"的原因不明 |
| R2 | M1 = 骨架 + 战斗 + 篝火 + 宝箱 + 1 Boss | **赞成，但要显式禁止两件事**：① 不许用"假 Boss"占位 ② 不许把 `?` 房静默当空房间 | 前者会让"Boss 能不能打"这件事无限期悬空；后者是本项目最恨的静默形态（`?` 房在 M1 是**有内容的空**：它是一个"事件池还没实现"的**可观察占位**，必须在地图 UI 上显示"（未实现）"并在 run 日志里记一条） |
| R3 | M2 = 3 精英 + 3 Boss + 商店 + 事件 + 遗物 + 药水 | **反对，必须拆 M2a / M2b** | M2a（战斗侧：G2/G4/G5 ⇒ 25 敌人全通）**仍有一部分可对拍/可逐敌断言**；M2b（run 层：商店/事件/遗物/药水）**永远不能对拍**。混在一起会让"因为事件池没有权重表"挡住"事件队列做完了没有"的验收 |
| R4 | （任务书没提） | **新增 M0.5「语义扩展的接口冻结」** | G2 会改战斗语义。如果等到 M2a 才动，M0/M1 期间建起来的确定性/哈希基线要**全部重跑**。所以 M0.5 只做一件事：把 `CombatEventHost` 的 trait 签名冻下来（默认空实现），并把它接进 `TurnHost` 家族的文档。**一行实现代码都先不写** |

### M0a —— 「一场普通战斗（内核）」

| 项 | 内容 |
|---|---|
| **进入条件** | ① `sts` 内容第一版能被 `compile.py` 编出来（零改编译器，见 §6）；② authored 完毕：3 张卡（`strike`/`defend`/`bash`）+ 1 个状态（`vulnerable`，否则 `bash` 只打伤害、机制不完整）+ 1 个遭遇 + 3 个敌动作；③ `tools\acceptance.ps1` 仍 9/9 |
| **做什么** | 选 `enc_jaw_worm`（`inv:§5.2`，HP 40–44）：敌人 3 招、4 个约束、无触发、无起始状态、无分裂。玩家 10 张起手牌（`inv:§2.1`），HP 80、能量 3、每回合抽 5（`inv:§2`） |
| **完成判据（命令 + 证据串）** | ① `powershell -File tools\cargo.ps1 run -p rd-fightdump --release -- --sts-m0` ⇒ 退出 0 且 stdout 含 `sts_m0 result=Victory`；<br>② 同一命令跑两遍，`step=…hash=…` 序列**逐字节相同**（`fc /b` 两个 dump 文件）；<br>③ 换 seed 后哈希序列**必须不同**（证明洗牌真的消费了 RNG）；<br>④ `tools\acceptance.ps1` 9/9，其中 units 门槛含新增测试（抬 `-UnitsFloor`） |
| **明确不做** | 敌人 AI 加权随机（G7）、任何 B/C 档敌人、奖励、地图、起始状态、`?` 房 |
| **风险** | 镜像里的 62 卡/85 语料/`CARD_DIFF` 是**旧内容**。新内容进同一份镜像会让"逐卡 62"变成"逐卡 65+" ⇒ **旧的 62 条必须仍然全绿**（新增内容只能追加、不能改旧的 id 与程序），否则 `native/card_specs.json` 的陈旧闸门会红 |

### M0b —— 「一场普通战斗（界面）」

| 项 | 内容 |
|---|---|
| **进入条件** | M0a 全绿 |
| **做什么** | 把 `rd-wasm` 的写死场景换成 M0a 的那一局；补 `intent_kind`/`intent_damage` 的接线（`intent::select_action` 已可用，`content.rs:754` 的读器也有 ⇒ 见 §1.1-C2）；修 `rd-wasm` Gap 4（"一次结束回合只能让一个敌人行动"）—— M0a 只有 1 个敌人，但 M1 会踩到 |
| **完成判据** | 手工：打开 `web/index.html`，能打出 `bash`→敌人显示易伤→敌人意图（⚔11/🛡/Buff）与 HP 正确→打赢。<br>自动：`rd_env_selfcheck`-等价的相邻断言（同种子同动作 ⇒ 观察流相同），若 wasm 侧不开放就退化成"金文件比对" |
| **明确不做** | 美术、动画、拖拽；只看数字与意图 |

### M0.5 —— 「语义扩展的接口冻结」

| 项 | 内容 |
|---|---|
| **进入条件** | M0a 绿（可以先于 M0b） |
| **做什么** | 冻结 `CombatEventHost`：3 个方法（`on_damage_received` / `on_card_played` / `on_combatant_downed`）、调用点（`exec.rs` S8 之后、`play.rs` 成功之后、生命归零之后）、默认空实现、"事件名白名单"（`NotHandled` 的 21 个一律拒绝）。同时冻结内容编译器的**事件白名单闸门** |
| **完成判据** | 冻好的 trait 至少有**一行调用它的代码**（项目纪律：冻一个 trait 方法后立刻写一行调用它的代码）；`acceptance.ps1` 9/9；`docs/spec/` 新增一节（或 `SEMANTICS-v2` 的 §2.3 预表）并注明"尚未实现任何事件" |
| **明确不做** | 不实现任何触发语义 |

### M1 —— 「一条最短路径」

| 项 | 内容 |
|---|---|
| **进入条件** | M0a 绿 + M0.5 冻完；G3 的 `currentHealth`（小）**已就位（2026-10-19，`maxHealth` 顺带）**、`LifecyclePrograms`（小）**已就位（2026-10-19，`host.rs::try_hand_turn_end_lifecycle`）**；**`run_rng` 的形状已定**（见 §5.4，这条不能后补） |

| **做什么** | ① 地图生成（`inv:§7.1-§7.4`）：7×15、6 路径、不交叉、前两起点不同、固定层 1/9/15/16/17、类型掷点 + 5 条覆写；② 战斗节点（池 = §3.4 的全 A 遭遇 + Hexaghost）；③ 篝火（Rest 30% / Smith，`inv:§8.1`）；④ 宝箱（三箱型 + Boss 宝箱 3 选 1，`inv:§8.3`）；⑤ Boss = **`hexaghost`** |
| **为什么 Boss 是 Hexaghost**（三条理由，可反驳） | ① **不需要事件队列**：它没有任何"受伤/出牌/死亡"触发（`inv:§4.3`），机制是"自身固定序列 + 一个纯函数伤害"；② **不需要改阵容**（Guardian 与 Slime Boss 各要一项"大"）；③ 它需要的三个小能力里有 **两个是纯内容侧**（绿火计数 = counter + 8 条规则；Burn→Burn+ 可以用"第一次 Inferno 之后就造 Burn+"来近似，差异只在玩家牌堆里已有的 Burn —— 起手牌组里没有 Burn，`inv:§2.1`）。⇒ **它是"能把 M1 关掉"的唯一 Boss** |
| **完成判据** | ① **确定性回归**：`sts_run --seed 7 --script a.json` 跑两遍 ⇒ `run_hash` 序列逐字节相同；② **规则单测**：`inv:§7.4` 的 5 条覆写各一条，且每条都成对（"合法图通过" + "构造的违规图被拒"）；③ **分布闸门**：固定 200 个 seed，断言"精英 8%±2 / 篝火 12%±2 / 商店 5%±1 / ? 22%±2 / 战斗 53%±2"（**带容差、固定 seed 列表**，否则 flaky），并先断言"样本里存在 ≥1 个三岔口"（否则"从不生成三岔口"的实现也能过）；④ **端到端**：一条脚本从 floor1 打到 floor16 赢 Hexaghost，输出 `STS_M1 PASS (floors=16 fights=N)`；⑤ `acceptance.ps1` 9/9 |
| **明确不做** | 商店、事件、精英、遗物、药水、`?` 房内容（占位）、Boss 宝箱以外的遗物、路径选择（沿最左路径走） |
| **风险** | ⚠️ **地图"合法性"闸门最容易假绿**：只断言"生成的地图满足 5 条规则"时，一个"只生成 1 条直路"的实现也能全绿 ⇒ 必须同时断言**产量类**（三岔口数量、路径条数、层级连通） |

### M2a —— 「战斗侧收全」（25 敌人全可跑）

| 项 | 内容 |
|---|---|
| **进入条件** | M1 绿；`SEMANTICS-v2` 已开（G2 落地） |
| **做什么** | ① `CombatEventHost` 真实现（3 个事件：`DamageReceived`/`CardPlayed`/`Downed`）；② Split（G4）；③ Looter 的逃跑 + 偷金币（G5-大）；④ 3 精英 + 3 Boss 全通；⑤ `sentry` 起始状态（G9）、`red_slaver` 的 `Entangled` 校验器、`shield_gremlin` 的 `sel.otherAllies` |
| **完成判据** | ① **逐敌动作层**照 `ENEMY_DIFF` 的形状扩一层 `STS_ENEMY`：25 敌 × 各自全部动作 × 固定种子，断言"每步之后的哈希 + `(round,turn,problems)`"（**注意：这一层比的是"我们自己两次跑一致"+"动作效果符合 `inv` 的逐条期望"，不是比 C#**）；② 每个 C 档敌人一条"机制存在性"测试（Curl Up 只触发一次 / Enrage 在 Skill 后 +2 / Split 生成 2 只且 HP 相等 / Looter 逃跑后金币减少）；③ `acceptance.ps1` 9/9 |
| **明确不做** | 加权随机 AI（G7，仍用确定性脚本 + 降级表）、X 费、战斗中升级、随机目标 |

### M2b —— 「run 层收全」

| 项 | 内容 |
|---|---|
| **进入条件** | M2a 绿（或并行，但**不与 M2a 共用一个验收**） |
| **做什么** | 商店（`inv:§8.2`）、26 个事件（`inv:§8.4`）、140 遗物（`inv:§6`）、33 药水（`inv:§9.4`）、`?` 房 10/2/3 累计递增（`inv:§7.5`）、奖励（`inv:§9.1-§9.3`） |
| **完成判据** | 见 §5.3 的 12 条判据清单 + 一条"同 seed 同操作序列 ⇒ 同 run_hash"的端到端回归 |
| **明确不做** | Ascension（`inv:§11` 全部）；事件**权重**（`inv:§12-1` 无来源 ⇒ 等概率 + 标注推断） |

---

## 5. 验证方式：两层，方法论不同

### 5.1 战斗层 —— 仍然可以对拍（**这是本里程碑的"舒服区"**）

| 层 | 现在比什么 | 加 StS 内容后 |
|---|---|---|
| `FIGHT_DIFF` | 4 个整局场景，182 条断言 | 不改；**继续当回归闸门**（证明"加了新内容没碰坏旧语义"） |
| `CARD_DIFF` | 62 张卡逐卡一局 | 变成 62 + StS 卡。⚠️ **StS 的卡在 C# 侧 author 不出来**（C# 没有加权 AI、没有我们的扩展节点）⇒ **新卡只能进"自证"层**（见 5.2） |
| `CARD_MULTI` | 逐卡跨回合 | 同上 |
| `ENEMY_DIFF` | 394 条 `EACT` 逐动作 | StS 的敌动作可以照做**自证版**（"同输入两次一致"+"效果符合 `inv` 期望"） |

⇒ **规则**：**凡是与 C# 共享的语义（回合机、伤害管线、状态三轴、费用、牌区、洗牌 RNG）继续对拍；
凡是 StS 独有的（敌人脚本、新节点、新表达式、run 层）只能靠规则测试。** 这一条必须写进每个里程碑的验收口径，
否则会有人拿"对拍全绿"去声称"StS 内容正确"。

### 5.2 自证层（新加，用于 StS 内容）

三条，缺一不可：
1. **确定性**：`(内容版本, seed, 脚本)` 相同 ⇒ 每步哈希逐字节相同；换 seed ⇒ 必须不同（证明 RNG 真的被消耗）。
2. **数值契约**：每张卡 / 每个敌动作的"效果"必须能从 `inv` 的表格**机械导出**再比对，且**多余也算失败**
   （只比"期望的键都在"会让"内容里又多写了一条没人核对的事实"静默通过）。
3. **陈旧闸门**：`sts/content/*.json` 与 `inv` 的派生结果不一致 ⇒ 红（照 `native/card_specs.json` 的 `--check` 形状）。

### 5.3 run 层 —— 没有 oracle，判据必须换（**我对任务书方案的修改**）

任务书的方案是"可读规则 + 逐条单元测试 + 一条确定性回归"。**方向对，但有三处必须改**：

| # | 任务书 | 我的修改 | 理由 |
|---|---|---|---|
| V1 | 确定性回归 = "同种子同操作序列 ⇒ 同一地图 / 同一奖励" | 改成 **"同种子同操作序列 ⇒ 逐步 `run_hash` 序列逐字节相同"** | 只比"终局地图相同/奖励相同"证明力太弱：一个"奖励取整错一位但每次错得一样"的实现会全绿。run 层没有哈希器 ⇒ **要造一个 run 层规范文本**（逐字段固定序、LF、集合按 id 序，照 `hash_golden` 的做法，`SEMANTICS-v1:§6.1`） |
| V2 | 逐条单元测试 | 加两条硬约束：① 每条规则测试**必须绑 `inv` 的行号**；② **必须成对**（"合法通过" + "构造的违规被拒"），并在测试名里写出"这个期望能区分出什么错误实现" | 项目纪律第 4 条：问"这个期望能区分出错误实现吗"。§7.4 规则 3（多出边目的节点类型互异）若只测合法图，一个"从不生成三岔口"的实现照样通过 |
| V3 | （未提） | **加分布闸门 + 加"推断标记"闸门**：凡 `inv:§12` 列为未决的量（事件抽取权重、Boss/精英内部权重、AI 取整细节），测试里**必须带 `inferred` 标记**，且断言里不能出现"等于原作"的字样 | 否则"等概率"会悄悄变成"已验证" —— 这正是纪律第 13 条说的"把'我不知道'改成'否'是最危险的撤销" |

**run 层判据清单（12 条，M2b 的验收就是它）**

| # | 判据 | 依据 |
|---|---|---|
| 1 | 版式：7 列 × 15 行、每行 ≤ 6 节点、**恰好 6 条路径**、前两条起点不同 | `inv:§7.1` |
| 2 | **路径不交叉**（同层相对左右序保持） | `inv:§7.1` |
| 3 | 裁孤点：每个保留节点至少有 1 条入边或出边 | `inv:§7.1` |
| 4 | 每节点出边 1–3、目的节点取"最近的 3 个" | `inv:§7.1` |
| 5 | 固定层：1 全战斗 / 9 全宝箱 / 15 全篝火 / 16 唯一 Boss / 17 Boss 宝箱 | `inv:§7.2` |
| 6 | 类型掷点 53/8/12/5/22（**+ 分布闸门**） | `inv:§7.3` |
| 7 | 5 条覆写（不入 floor<6 精英篝火 / 不连续同类 / 多出边目的类型互异 / 不出 floor14 篝火 / 违规重掷） | `inv:§7.4` |
| 8 | `?` 房 10/2/3 累计递增、命中后重置、每幕重置 | `inv:§7.5` |
| 9 | 篝火 Rest = `floor(0.3 × maxHP)`、Smith 升级 1 张、每次只选一项 | `inv:§8.1` |
| 10 | 商店价格区间 + 删卡 75 起、每次 +25 跨店累计；**商店不修改稀有度偏移** | `inv:§8.2` |
| 11 | 奖励：金币区间、卡牌 3 选 1 稀有度 + 偏移（−5% 起 / Common +1% / Rare 重置 / 上限 +40%）、**第一幕升级概率 0%** | `inv:§3.5`、`inv:§9.1` |
| 12 | 药水基准 40% ±10%、每幕重置；稀有度 65/25/10；持有上限 3 | `inv:§9.3` |

### 5.4 `run_rng` 必须先定形状（**我认为这是最容易翻车的一条**）

内核的 RNG 是**单流** `(seed, step)`（`rng.rs`，且 `state.rs` 只有一个 `random_step`）。run 层如果共用一条流，
那么"多抽了一次药水"会改变**后面整张地图**（因为 step 前进了）—— 这会让
"同种子同操作 ⇒ 同地图"的回归**变成一条几乎不可用的判据**（任何无关操作都破坏它）。

⇒ **M1 开始前必须定**：run 层用**独立子流**（`map` / `reward` / `event` / `potion` / `shop` 各一条，
由 `(run_seed, stream_id, counter)` 派生），每条流独立计数。形状一旦定错，后面所有确定性回归都要重写。

---

## 6. 内容管线的形状（只给方向）

### 6.1 先说三条实测事实（它们决定"要改什么"）

1. **`compile.py` 已经是"文档 → RDCF"的通用编译器**：opcode 表与字段表**都从被编译的那份文档派生**
   （`compile.py:204` `LayoutDeriver`；docstring 第 17-20 行），**不是** 从一张写死的词表。
   ⇒ **卡牌的程序树本来就该由格式直接写出来，这一层不需要改编译器。**
2. **但实体段是写死的 5 张表**：`CARD / STATUS / EACT / ENCT / REL`（`compile.py:38`）。
   StS 需要的**事件、药水、地图、遗物池权重**都没有位置；RDCF 段目录里 `14..19` 是预留（`rdcfmt.py` 段表）。
   ⇒ 这是编译器的**真改动点**，而且它正好和"run 层在 `SEMANTICS-v1:§2.2` 里是 OUT"是同一件事。
3. **opcode 是 u8**：当前 131/256（`manifest.json`），超了就 `SystemExit`（`compile.py:281`）。
   StS 的 75 张卡 + 25 敌 + 26 事件会新增一些"对象形状" ⇒ **必须在 M0a 就量一次余量**，别等到 M2 才发现撞墙。

### 6.2 候选格式与选择

| 候选 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| **(a) 直接手写 `.roguedeck.json`**（C# 的序列化文档形状） | 零转换；编译器不用改 | 8.3 MB / 62 卡；`{"kind","value"}` 信封 + `Children` 冗余 + Id 三种拼法（`{"value":…}`/`{"Value":…}`/裸串）⇒ **人手写不动、diff 不可读、无法 review** | ❌ 作为**中间产物**可以，作为**作者格式**不行 |
| **(b) 紧凑 JSON（自定 schema）+ 一个标准库翻译器** | 与 `tools/contentc` 的"纯 stdlib、确定性、可 diff"风格一致；每行能对上 `inv` 的一行（可机读核对）；翻译层是唯一要写逻辑的地方 | 需要写翻译器（但**逻辑只有映射**，没有语义） | ✅ **推荐** |
| **(c) Python DSL**（`card("strike", cost=1, …)`） | 最可读；能写模板（62 张 strike-like） | "内容即代码" ⇒ diff 不可机读、编译期要执行代码（可复现性/供应链风险）、和 `inv` 的表格对不齐 | ❌（模板需求可以用 (b) 的 `{"like":"strike","dmg":6}` 小机制解决） |
| **(d) YAML** | 可读 | 本机/项目只用 stdlib，没有 YAML 解析器；缩进陷阱 | ❌ |

**推荐：紧凑 JSON（先例已经在仓库里）** —— `sts/content/cards.json` 的扁平 `{"op": "damage", "amount": 6}`
是 plan B 的遗产（`status_catalog.rs:552` 注明"已放弃"，但**格式**是好的先例）。理由一句话：
**它是唯一能同时满足"人能写 / 机器能核 / 编译器不用改"的形状。**

### 6.3 不需要改编译器的部分（明确点名）

* 卡：`Program` / `LifecyclePrograms` / `Costs` / `Tags` / 两种落区 / `RetainInHandOnTurnEnd`
  —— CARD 行实测 **15 格**（`docs/spec/content-binary-format.md`，`Id…extra`），`inv:§3` 的 75 张卡逐张都能填进这些格，
  **没有一格需要新增**（费用格承载 `inv:§3` 的 1/2/3 与"指向共享空列表"两种形状）
* 敌动作 `EACT.Program`（7 格：`Id/NameKey/DescriptionKey/PackageId/Intent/Program/extra`，`docs/spec/enemy-intent.md:34`）、
  遭遇 `ENCT.Enemies/IntentRules`
* 状态 `STAT.Triggers`（`Event` + `Program`，`host.rs:346-371`）与 `PassiveModifiers`
* 新增 **节点/表达式/选择器**：只要内核实现并**按名字**注册（`ir.rs:140` `from_wire_name`），
  编译器"看见新形状就派一个新 opcode" ⇒ **零改动**（唯一的约束是 256 上限）

### 6.4 翻译器必须做的两件"拒绝"（否则是最危险的静默）

1. **事件白名单**：写出 `DamageTaken`/`CardPlayed`/`Downed` 等（今天 `NotHandled`，`host.rs:323-328`）⇒ **硬失败**。
2. **能力白名单**：写出 `sel.random` / `missingHealth` / `X 费` / 战斗中升级 ⇒ **硬失败**并指向本文的 §2 编号。
   理由：它们今天都是"响亮失败"或"根本不存在"，而**内容层最容易绕过响亮失败**（例如把"随机取 6–7"
   写成常量 6 —— 这必须是**显式的 `{"deviates":"§7#3"}` 字段**，不能是默默写 6）。
   > 2026-10-19 更正：这一条原来写的是 `currentHealth`。`currentHealth` / `maxHealth` 已经**实现**
   > （字段名 `Selector`，§9-4 + `expr.rs` 模块头第 4 条），所以从这张表里换成 `missingHealth`
   > （它没有 opcode，写它就会响亮失败；需要"缺多少血"时写 `subtract(maxHealth, currentHealth)`）。

### 6.5 格式契约里必须写死的三条语义约定（否则数值会静默偏）

1. **状态层数落在 `Stacks`，不要落在 `DurationTurns`**（见 §2 G10，带实测依据）。
2. **"升级"= 另一张 CARD 行**（`+` 后缀），不是实例上的标志位（`rd-wasm` Gap 5 已证实）。
   因此 run 层"升级一张卡" = 把实例的 `definition_id` 换成 `+` 行 —— 这需要一个小节点（内容侧目前没有）。
3. **敌人"脚本"用 counter 惯用法表达**（`Actions` 顺序 + `IntentRules(selfHasCounter)` + `TurnStarted` 触发器自增）；
   **不许**为了让某只敌人"看起来对"而在内核里特判（`intent.rs:19` 的教训：那是把"内容依赖没到位"伪装成"功能已实现"）。

---

## 7. 降级表（**这份表是 M0/M1 的唯一"合法说谎"清单，也是闸门的输入**）

规则：表里每行 = 一条**已知的原作差异**。任何内容项引入了表里没有的新差异 ⇒ 闸门红。
每行都必须写清"什么时候会被发现"，因为**不可发现的降级等于撒谎**。

| # | 内容项 | 原作行为（`inv`） | 我们的行为 | 何时会被发现 |
|---|---|---|---|---|
| 1 | 所有敌人 | 加权随机 + 不能连用 N 次（`inv:§4.1`） | 确定性脚本（满足"不能连用"约束，但**分布不同**） | 统计 10k 局的动作频率 vs 原作权重（需要原作数据，今天没有） |
| 2 | `the_guardian` / `slime_boss`（阈值打断）· `lagavulin`（唤醒即换脚本 + 眩晕） | 达到阈值**立刻打断当前意图**（`inv:§4.2/§4.3`） | 阈值在**回合边界**判定 ⇒ 该回合的出手照旧、眩晕从下一回合起算 | 逐回合比对"阈值那一回合敌人做了什么" |
| 3 | `louse_red` / `louse_green` | Bite 伤害开场随机 5–7（`inv:§4.1`） | 固定 6 | 战斗开局的第一刀伤害 |
| 4 | `hexaghost` | 第一次 Inferno 把**所有** Burn 升级成 Burn+（`inv:§4.3`） | 只有 Inferno **之后**造的 Burn 是 Burn+（玩家牌堆里已有的 Burn 不升级） | 玩家牌堆里有 Burn 时（Immolate，`inv:§3.4`） |
| 5 | 26 个事件 | 抽取有权重（`inv:§12-1`，**来源缺失**） | 等概率 | 事件出现频率分布（**永远无法验证**） |
| 6 | `searing_blow` | 每级 +4/+5/+6… 递增（`inv:§12-5`【单源】） | `【待补】`：M2 前不支持战斗中升级 | 拿到这张卡时 |
| 7 | 商店价格 | 按稀有度分档（Common 45–55 / Uncommon 68–82 / Rare 135–165，`inv:§8.2`） | ~~全部按 Common 定价~~ **已修（2026-10-20）**：`CARD` 有了 `Rarity` 格，`card_price_band()` 直接查它；`FORMAT_VERSION` 升到 2 | —（推断已消除） |
| 8 | **Neow（floor 1 之前）** | 2 选 1：+10% 最大 HP（⇒ 88）或 `Neow's Lament`（`inv:§2.2`） | **M1 不做**，起始 HP 固定 **80** | 开局第一屏的 HP 数字；`Neow's Lament` 的那三场战斗 |

> **起始遗物 `burning_blood`（战斗结束 +6 HP，`inv:§2`）不算降级 —— M1 要真的实现它**，
> 理由见 `run-layer.md` §4.5：它每一场战斗都在改 HP，而这正是"从出发到 Boss"要复刻的那条
> 数值主线。按本表的规则（"还没做/已经做了都不进表"），它**不出现在这里**；但正因为不出现在
> 这里，M1 落地时它必须有一条自己的测试，否则"表里没有 ⇒ 没人记得做"。

> **"还没做"不进这张表**：Guardian / Slime Boss / Looter 在 M2a 之前根本不可用，那是 §4 的里程碑进度，
> 不是降级。混进来会让这张表变成"TODO 列表"，而它的唯一用途是**记录我们主动选择的不一致**。

> **闸门的形状**：`native/sts_deviations.json` 存这张表；内容编译时每条降级必须被某条内容"认领"，
> 且**不允许有未被认领的降级**（反过来也不允许内容里有未登记的降级）。这一条是防"把降级当完成"的唯一机械手段。

---

## 8. 我认为最可能翻车的地方（按概率 × 代价排序）

1. **把降级当完成。** G1/G7 的最小实现都是"语义降级"，它们**不会让任何测试变红** —— 只会让复刻
   "看起来对、玩起来不对"。对抗手段只有 §7 的降级表 + 闸门。**这是本项目已经踩过 13 次的那类错**
   （纪律第 13 条：把"我不知道"改成"否"是最危险的撤销），而 StS 复刻会是它最大的一次舞台。
2. **事件队列的时机。** 它是唯一"不做就挡住 7/25 敌人、做了就要动冻结语义基线"的东西。
   如果在 M2a 才动，M0/M1 期间建立的所有哈希/语料基线要重跑一遍。⇒ 所以我把"冻结接口"单列成 M0.5，
   **一行实现代码都不写，只冻签名**。
3. **`run_rng` 的形状（§5.4）。** 改起来便宜、改晚了极贵：所有确定性回归都建立在它上面。
   一条单流会让"多抽一瓶药水 ⇒ 地图变了"，届时会被误诊成"生成器有 bug"。
4. **内容与 `inv` 的漂移。** 没有 oracle，人对数字的信任度会随里程碑推进而下降。对抗手段：
   §5.2 第 2 条（机械导出 + 多余也算失败）+ §5.2 第 3 条（陈旧闸门）。
5. **地图闸门假绿。** 只测"生成之物合法"而不测"生成之物够多/够杂"，一个退化实现能全绿（§4 M1 判据 ③）。
6. **opcode 上限与体积。** 131/256 今天够用，但 StS 的 26 个事件（`inv:§8.4`）会带来大量**新对象形状**
   （每个不同的键集是一个 opcode）。⇒ M0a 就先量一次余量，别等 M2b。
7. **`CombatState` 184,648 B（30.5% SRAM）。** run 层状态（地图/牌组/遗物/药水）会再吃一块；
   若打算在 P4 上跑整局，`run` 状态的预算现在就该估。

---

## 9. 未决项 / `【待补】` 索引

| # | 项 | 现在怎么处理 | 在哪一步能查到 |
|---|---|---|---|
| 1 | 事件抽取权重 | 等概率，标 `inferred` | **无处可查**（`inv:§12-1` 三源皆无）⇒ 需要实机观测或社区逆向 |
| 2 | 敌人 AI 的取整/回退（"不能连用 N 次"在边界上的实际做法） | 确定性脚本绕开 | `inv:§12-2`；需要实机采样 |
| 3 | Boss/精英/遭遇是否真等概率 | 按等概率实现，标 `inferred` | `inv:§12-4` |
| 4 | `currentHealth` 的目标字段名 | **已定：`Selector`**（2026-10-19）。不是拍脑袋：同一份镜像里 **11 个 opcode** 已用 `Selector: F_TERM` 表示这个概念（op 20/21/22/23/24/25/32/38/43/44/45），其中 `combatantStatusStacks`(25) / `combatantCounter`(23) / `combatantCurrentResource`(24) 正是内核已在读的单目标标量读。`missingHealth` 没有 opcode ⇒ 继续不支持（用 `subtract` 写） | 镜像里**不存在**这两个字段（`nfields=0`）⇒ 定义权在我们；落地见 `expr.rs` 模块头第 4 条 + `compile.py` 零改动派生出该字段的实测（临时拷贝） |
| 5 | `Searing Blow` 逐级升级值 | M2 前不支持战斗中升级 | `inv:§12-5`（【单源】） |
| 6 | 诅咒卡清单（Regret/Injury/Doubt/Parasite/Pain/Decay）的精确机制 | 事件效果无法结算 ⇒ M2b 前这些分支标"未实现" | `inv:§12-6` |
| 7 | `Wheel of Change` 6 格是否等概率 | 等概率 + `inferred` | `inv:§12-7` |
| 8 | 事件"每局去重"规则 | 只实现"Shrine 每幕最多 1 次" | `inv:§12-8` |
| 9 | 内核对 `NotHandled` 事件的**静默**行为要不要升级成响亮失败 | 建议：内容编译器白名单（§6.4-1）；内核侧保留 `NotHandled`（不动冻结契约） | 本文 §6.4 |
| 10 | 本内容镜像与新 StS 内容是"同一份"还是"两份" | 建议**两份**：`content.core.rdcf`（受对拍保护，不许动）+ `sts.core.rdcf`（自由演进） | 本文 §4 M0a 风险行 |

---

**改动记录**

| 日期 | 版本 | 改动 |
|---|---|---|
| 2026-10-18 | v1 | 初版：17 条现状锚点 + 5 条对输入的更正、G1–G10 能力矩阵、25 敌人分档（10/4/11）、M0a/M0b/M0.5/M1/M2a/M2b、run 层 12 条判据、内容管线建议、6 行降级表 |
| 2026-10-19 | v1.1 | **G3 的 `currentHealth` / `maxHealth` 落地**（字段名 `Selector`，不是 §2 G3 原写的"例如 `Target`"）。原地改了：§1 第 3 行、§1.1 C3、§2 G3 两行、§6.4-2（白名单里把 `currentHealth` 换成 `missingHealth`）、§9-4（定案）、§4 M1 进入条件。**另更正两处旧错误**：①§2 G3 的"HP=25 ⇒ 24"与它自己的 floor 公式不自洽（floor 下是 18，只有 ceil 才是 24）—— 原作取整方式**未验证**；②`expr.rs` 模块头里 `tools/_core_dump.json` 这个出处文件**不存在**（改指源 JSON）。`missingHealth` 仍未实现（镜像里没有它的 opcode），理由写进 §2 G3 |

---

## 10. 现状（2026-11-03）

§1 的 17 条现状锚点写于实现之前；这份表**不再逐行改**（改历史没有意义），当前状态以
`docs/sts-wiki-gap.md` 与 `docs/port-plan.md` 的 §161.x–§186 为准。三句话：

* **能力**：三幕可从开局走到幕末；战斗内核与参考逐字节对拍（`FIGHT_DIFF 182/182`、
  `CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）；20 道闸门全绿。
* **内容**：卡 / 状态 / 药水 / 遗物 / 事件 / 每幕遭遇池的数字都由 `native/gap_check.py` 重算，
  **药水池已满**（33/33），三幕精英每幕 3 个。
* **仍然缺的**：`EACT` 的 ascension 维度（一根维度解锁 A2/3/4 + A17/18/19 六条）、事件效果的
  **列表**、每幕的第二三只 Boss、A1/A10/A12/A15/A20。逐条见 `sts-wiki-gap.md` §2–§3。

---

## 11. 现状补充（2026-11-03）：Ascension 的数据维度

§2 的 `G`-能力矩阵里，"A2/3/4 伤害"与 "A17/18/19 招式表"当时是"需要 `EACT` 加维度"。
§187 把它加了：`EACT.ProgramAsc` + `AscensionMin`（两格）+ `intent.ascensionAtLeast`。
当前内容接了 **13 个动作**（普通 4 / 精英 4 / Boss 3 / 招式表 2），剩下的由
`native/gap_check.py` 报数：**没有 wiki 出处就不写数字**。
