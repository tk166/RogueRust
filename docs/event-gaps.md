# 事件缺口（扫描结果，§280）

> 口径：**真事件**（Act 1–3 的 `?` 房事件）逐条对照 wiki 的 `Options` / `Requires:` 行。
> 列的是**内容层**的缺口 —— 机制层的能力边界写在 `docs/mechanism-gaps-analysis.md`。
>
> 状态四类：**已做**（内容在、行为有判据）、**做了但简化**（有意偏差，写在 Deviation 列）、
> **缺**（内容不在）、**挡住**（内容在但机制表达不了，写明缺什么）。

## 1. 我们已有的 13 条

| 事件 | 幕 | 状态 | 条件选项 | 备注 |
|---|---|---|---|---|
| `golden_idol` | 1 | 已做 | — | 两段三选一（§278）：Take → 巨石 → Outrun/Smash/Hide |
| `the_cleric` | 1 | 已做 | **2 条**（35 / 50·A15 75 金币） | §280：`gold_cost` + `heal_pct` + `RequiresAsc` |
| `forgotten_altar` | 2 | 已做 | **1 条**（有金像） | §279：`relic_lose` 换血像 |
| `the_ssssserpent` | 1 | 已做 | — | §279：两段 + A15 金币 150 |
| `the_moai_head` | 3 | 已做 | **1 条**（有金像） | §280：`heal_full` + `max_hp_pct:12.5` |
| `the_mausoleum` | 2 | 已做 | — | |
| `purification_shrine` | 2/3 | 已做 | — | 跨幕复用 |
| `ancient_forge` | 2/3 | 已做 | — | 跨幕复用 |
| `ancient_writing` | 1 | 已做 | — | |
| `shining_light` | 1 | 已做 | — | |
| `old_shrine` | 1 | 已做 | — | |
| `scrap_pile` | 1 | 已做 | — | |
| `wandering_merchant` | 3 | 已做 | — | 我们自己写的事件（参考里没有） |

## 2. 缺的、**能用现有机制补**的（下一批候选）

| 事件 | 幕 | 缺什么 | 需要的机制 | 成本 |
|---|---|---|---|---|
| `the_joust` | 2 | 整条 | `gold at_least 50`（选项级）+ `gold_cost` + **随机结果**（70/30） | 中 —— 随机是 `randomInt`，还没做 |
| `the_moai_head` | 3 | 事件级条件（有金像**或** HP ≤ 50% 才遇到） | **事件级**条件（进入前判） | 小 —— 见 §3 |
| `the_cleric` | 1 | 事件级条件（≥35 金币才遇到） | 同上 | 小 |
| `vampires` | 2 | 整条 | `relic has blood_vial` ✅、`relic_lose` ✅、`max_hp_pct:30` ✅、**"移除所有 Strike"**、**"得到 5 张 Bite"**、Bite 这张牌本身（含 `+` 行与"打出时回血"） | 大 —— 要 `remove_all:<id>` + `card:<id>`×N + 一张新牌 |
| `n'loth` | 2 | 整条 | "从手上**任选一件**遗物失去" —— 我们没有"选遗物"这个问句 | 大 —— 新问句 + 新 `Pending` |
| `wing_statue` | 2 | 整条 | "牌组里有一张**单次伤害 >10** 的攻击牌" | 中 —— 条件要读卡表数值，不是"有没有这张牌" |
| `knowing_skull` | 2 | 整条 | 事件级"HP > 12" + 每次点击 HP 代价递增（状态） | 中 |
| `tomb_of_lord_red_mask` | 2 | 整条 | 事件级"有红面具" + 222 金币 | 小 |
| `designer_in_spire` / `duplicator` / `knowing_skull` 等 | 2/3 | 整条 | 各自机制 | 逐条评估 |

## 3. 扫描出来的**机制缺口**（不是内容缺口）

### 3.1 事件级条件（"这个事件本身出不出现"）

wiki 对 `The Cleric` / `The Moai Head` / `The Joust` / `Tomb of Lord Red Mask` 都有一句
"**can only be encountered if …**"。这是**池子过滤**，不是选项过滤：

* 我们的 `EventTables` 是静态 id 列表；
* `rd-wasm` 抽事件时按 `RunStream::Event` 掷骰选一条**然后**打开它。

要补的地方很小（**在选完之后、打开之前**判一次"这条事件的条件成立吗"，不成立就重掷/跳过），
但需要：
1. `EV` 行加一格 `Requires`（与 `EVND.Options[i].Requires` **同一个词表** —— 一份求值器）；
2. **拒绝**必须响亮：抽中的事件全都不可选 ⇒ 这是我们还没做的"退回一个普通战斗"路径；
3. 判据要两侧：同一个 seed、金币 30 vs 40 ⇒ 抽到的 `?` 房结果不同。

⚠️ 但先别做：它与"`?` 房的分流"（§272：事件 / 战斗 / 商人 / 宝箱）**叠在同一个掷骰上**。
在该分流上加一层过滤会改变每一次 `?` 房的抽取结果，于是所有跑法（`ACT1_SLICE` /
`SOAK`）的覆盖会整片重掷。要么单独一节、单独一组数字，要么等 `?` 房本身再改一次时顺手做。

### 3.2 随机结果（`The Joust` 的 70/30）

**战斗侧**已经做了（§281：`randomInt` + 统一入口），但 `The Joust` 要的是**运行层**的
概率（70/30 的胜负），走 `RunStream::Event` 那条流 —— 那是事件那一节的活，与战斗随机不同流。
同一类还缺：`Scrap Ooze` 的 25%→35%…（每次失败 +10% 且 HP 代价 +1）—— 它还要一个
"可重复的选项 + 递增状态"，属于事件机制的下一次改动。

### 3.3 "从手上任选一件遗物"（`N'loth`）

需要一个**新的待决问句**（现在的 `PendingChoice` 只选**牌**）。它与选牌共用一套模式
（来源 + 候选 + 一个 `then`），所以成本主要在 UI 与 ABI 的第二组导出，不在内核。

## 4. 这一轮做了什么（§280）

* 机制：`RequiresAsc`（A15 的条件变体）、`gold_cost`（付钱要**响亮拒绝**，不是夹到 0）、
  `heal_pct`、`heal_full`、百分比支持**一位小数**（12.5%，内部按千分存）。
* 内容：`the_cleric`（Act 1，2 条条件）、`the_moai_head`（Act 3，1 条条件），并顺手修正
  `the_ssssserpent`（Act 1）与 `forgotten_altar`（Act 2）的幕数归属。
* 判据：付钱拒绝 / `heal_full` / 12.5% 进算术 / `RequiresAsc` 两侧（A0 与 A15 各一档）/
  两条 A15 常量对齐；负控四条（`RequiresAsc == base`、两位小数、`gold_cost:0`、
  删掉 `RequiresAsc` ⇒ A15 判据红）。

## 5. 下一步的排序建议

1. **`randomInt`**（§281）：解锁 `The Joust`、`Mad Gremlin` 的伤害浮动、`Gremlin Wizard` 的
   50/50 —— 也是"每回合重掷"这类规则的总闸。★ 真坑：预检也会求值，结果必须在计划里固化。
2. **事件级条件**（见 §3.1）：一次解锁 4 条真事件的"何时出现"，但要单独一节（它会重掷
   `?` 房的每一次抽取）。
3. `remove_all:<id>` + `card:<id>`×N + `Bite` 那张牌（`Vampires`）—— 内容工作量大，
   机制只多两个原子。
