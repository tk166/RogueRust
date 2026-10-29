# 对照 StS wiki 的功能缺口清单

> 目的：**在上轻量 Live2D 之前**，把"玩家会感觉到的缺失"列清楚。
> 每一条都标了**它需要哪种活**：`内容`（只写 JSON）/ `内核`（要新机制）/ `页面`（ABI 已经够）。
> 依据：本仓库的实现现状（每个数字都能在 `port-plan.md` 找到出处）+ StS wiki 的关键词/机制页
> （`slaythespire.wiki.gg/wiki/Keywords`，fetch 于本次会话）。**wiki 有、我们没做的，一条条列在下面。**

---

## A. 卡牌关键词（最影响手感的一层）

| 关键词 | wiki 语义 | 我们的状态 | 需要 |
|---|---|---|---|
| **Exhaust** | 用完移出战斗，进 Exhaust pile | **有**（`CardZone::ExhaustPile` + 卡的 `PlayedCardDestinationZone` 内容格）| 内容 |
| **Ethereal** | 回合结束还在手里 ⇒ 消耗 | **有**（§144：`CARD.TurnEndHandDestinationZone = ExhaustPile`）| — |
| **Innate** | 开局必在手牌 | **有**（§144：`MoveInnateCardsToTop`，照参考的"倒着挪"实现）| — |
| **Retain** | 回合结束不弃 | **有**（§144：`CARD.RetainInHandOnTurnEnd`）| — |
| **Unplayable** | 不能从手里打出 | **有**（`play.rs` 受理校验的五条之一：stun / decree / play_condition / one_attack / **unplayable**）| — |
| **X 费** | 消耗全部能量，效果按消耗量 | **有**（§146：`x_cost` tag + `x.cost` 表达式 + `node.repeat`；Whirlwind 是第一个载体）。⚠️ 参考仓里**没有**这个概念（grep 零命中）⇒ 这一条是**新造**的，不是移植 | Chemical X 那种"X +2 不多花钱"的遗物；`repeat` 体里的 `iterationIndex` |

> §146 之后 X 费也有了（`whirlwind`）。§144 之后，内容里已经有三种关键字的载体：`sentinel`（Ethereal，真卡）、`patient_guard`（Retain，
> fixture —— Ironclad 没有 Retain 卡）、`swift_strike`（Innate，fixture）。`x_cost` 是**唯一**
> 内核还不许出现的 tag：内容门 `[6d]` 会拒，建战斗与出牌两处也会拒。

## B. 状态 / buff（战斗内的"第二套语言"）

**已有 17 个**：strength / vulnerable / weak / frail / ritual / metallicize / thorns / artifact /
regen / rage / flame_barrier / combust / spore_cloud / enrage / time_warp / phase_split / split。

**wiki 常见、我们没有的**（按"对铁甲战士第一幕的影响"排序）：

| 状态 | 语义 | 需要 |
|---|---|---|
| **Intangible** | 本回合受到的伤害变 1 | 内核（伤害管线的最后一道）|
| **Buffer** | 免疫下一次伤害 | 内核（同一条管线）|
| **Plated Armor** | 回合结束 +N 格挡，受击时 -1 | 内核（钩子已有，缺"受击减层"）|
| **Barricade / Blur** | 格挡不被清 | 内核（回合开始的清格挡要能跳过）|
| **Entangled** | 本回合不能打攻击牌 | 内核（`can_play_card` 的判据 + 回合末清）|
| **Slow** | 每打一张牌它受的伤害 +10% | 内核（伤害管线的修饰器）|
| **Constricted** | 回合结束掉 N 血 | **内容**（`TurnEnded` 触发器，已有钩子）|
| **Draw / Energized**（下一回合多抽/多能量）| — | 内核（回合开始的发牌/能量结算）|

> 后 4 条里，**Constricted 是纯内容**（我们现在就能写）；其余都要动"伤害管线"或"回合边界"。

## C. 战斗流程

| 机制 | 状态 | 需要 |
|---|---|---|
| 敌人**召唤随从** | **有**（§138/§139：上限 4、主人死则逃）| — |
| Boss **分裂** | **有**（§121）| — |
| Boss **半血换招** | **有**（§124：`intent.healthPercent`）| — |
| **偷钱后逃跑**（Looter）| 没有 | 内容 + 一个"偷金币并 Escaped"的节目 |
| **往你牌库塞牌**（Hexaghost 的 Burn）| **有机制**（`createCardInstance` + 区）| 内容 |
| **敌人形态/多段**（Awakened One 复活）| 没有 | 内核（复活 + 换形态）|
| **精英的"必须一次打完"**（不能逃跑）| 无逃跑概念 | — |

## D. 运行层（地图/事件/商店/篝火）

| 项 | 状态 | 需要 |
|---|---|---|
| 地图节点 6 种 + Boss 行 | **有** | — |
| 每幕**独立的**池子（遭遇/事件/药水/精英）| **有**（§130/§133/§135/§137）| — |
| 每幕**独立的地图** | **有**（§131）| — |
| **篝火选项**：休息 / 打铁 | **只有这两种** | 内容之外的第三种（举重/挖宝）要新效果类型 |
| **商店**：卡/遗物/药水/删卡 | **有**（`RunState::remove_card` 是商店动作；篝火的升级是 `smith`）| — |
| **商店价格** | 按稀有度定（inv:§8.2）| — |
| **事件**：闭集效果 | `heal/gold/damage/max_hp/nothing` + **`remove_card`/`upgrade_card`/`transform_card`/`curse:<id>`/`relic:<id>`**（§143）| 一个选择只能有**一条**效果（Golden Idol 那种"遗物+诅咒"还不行）|
| **钥匙**（红/蓝/绿）与**第四幕** | 没有 | 内容 + 运行层 |
| **爬塔等级（Ascension）** | 没有 | 运行层（一个难度参数 + 若干规则）|
| **塔底 Neow** | **8 项**（§98/§100）| 缺"用初始遗物换 Boss 遗物"这类交易 |
| **遗物** | **5 件**（§145：burning_blood / anchor / vajra / pear / blood_vial），三个派发点（授予时、开战时、结束战斗）| 稀有度与掉落权重、精英战给遗物 |

## E. 给 Live2D 用：ABI 现在够不够

**够用的**：`rd_env_observe_into`（148 slot 状态）、动作表、牌堆/手牌读名、`rd_env_enemy_*`、
`rd_run_*` 的运行状态、`rd_env_forced_turns`（§126）、`rd_env_enemy_is_minion`（§140）。

**不够的（Live2D 一定会要）**：

| 缺什么 | 为什么 |
|---|---|
| ~~**一步之内的事件序列**~~ | **已做**：§142 的 `rd_env_beat_*`（有序 beats + 墙位 + DoT 标记 + 丢条计数）。页面还没改用它（等 Live2D 那次重写）|
| **攻击/受击的"意图-结果"配对** | 动画要知道"这一拳是为哪条意图落地的" |
| **牌离手 → 目标 → 弃牌堆**的行进轨迹 | beats 已经有"谁打了谁"，但"牌从手牌第 3 格飞到目标"这一段轨迹没有 |

⇒ beats 把**顺序与分段**补齐了（多段攻击、先格挡后挨打、状态增减、倒下/逃跑、回合边界、召唤）。
剩下的两项都是"位置/来源"级别的问题，不是硬前提。

---

## 建议顺序

1. ~~**`rd_env_beat_*`**~~（**已完成**，§142）
2. ~~**事件解释器**~~（**第一层已完成**，§143：删卡/升级/转化/诅咒/遗物）
3. ~~**卡牌关键词**~~（**已完成**，§144：Retain/Ethereal/Innate；X 费仍是"要新造机制"）
4. ~~**遗物池**~~（**已完成**，§145：1 → 5 件，三个派发点；`relic:` 事件现在有东西可给）
5. **状态**：Constricted（内容，最便宜）→ Intangible/Buffer（伤害管线）
