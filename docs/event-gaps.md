# 事件缺口（§306 全面核对）

> **口径**：**真事件**（三幕的 `?` 房事件）逐条对照 wiki。列的是**内容层**的缺口 ——
> 机制层的能力边界写在 `docs/mechanism-gaps-analysis.md`，载体清单在 `docs/sts-wiki-gap.md` §D.4。
>
> 状态四类：**已做**（内容在、行为有判据）、**做了但简化**（有意偏差，写在"偏差"列）、
> **缺**（内容不在）、**挡住**（内容在但机制表达不了，写明缺什么）。
>
> **数字只有一个来源**：池子与选项数都是直接读 `tools/contentc/packages/sts/sts.roguedeck.json`
> 的 `EventTables` / `EventNodes` 得到的；wiki 侧用 `Exordium` / `The City` / `The Beyond`
> 三页的 *Regular events: Full List*。**不要手抄**，改完内容请重跑本文 §1 的读法。

---

## 1. 现状：**19 个事件**，22 条池条目

| 幕 | 池 | 条目（按池内顺序） |
|---|---|---|
| 1 | `Events` | 10：`golden_idol` `shining_light` `old_shrine` `ancient_writing` `the_ssssserpent` `the_cleric` `scrap_pile` `world_of_goop` `wing_statue` `dead_adventurer` |
| 2 | `Events2` | 8：`ancient_forge` `golden_idol` `purification_shrine` `the_mausoleum` `forgotten_altar` `the_joust` `the_colosseum` `the_nest` |
| 3 | `Events3` | 4：`wandering_merchant` `ancient_forge` `purification_shrine` `the_moai_head` |

`golden_idol` / `ancient_forge` / `purification_shrine` **跨幕复用** ⇒ 去重后 **19 条**
（`gap_check.py` 打印的是池条目之和 `22 (10+8+4)`，不是 22 个不同事件）。

### 1.1 逐条：选项数、条件、分支深度

`kids` = 这条事件产生的**后续屏**数（`EVND` 里 `<id>.` 前缀的行）。它是"剧情树"的深度指标：
1 就是"一段文本两个按钮"，25 就是 `Dead Adventurer` 那棵 21 分支的树。

| 事件 | 幕 | 选项 | 条件选项 | 后续屏 | 备注 |
|---|---|---|---|---|---|
| `golden_idol` | 1, 2 | 2 | 0 | 1 | 两段三选一（§278） |
| `shining_light` | 1 | 2 | 0 | 0 | |
| `old_shrine` | 1 | 2 | 0 | 0 | 本移植自有（shrine 类：Pray / Leave） |
| `ancient_writing` | 1 | 2 | 0 | 0 | **同名但不是 wiki 的那条**：我们用"升级一张牌"，wiki 的 Ancient Writing 是另一条事件（§311 记下这个命名冲突） |
| `the_ssssserpent` | 1 | 2 | 0 | 2 | 两段 + A15 金币 150（§279） |
| `the_cleric` | 1 | **3** | **2**（35 / 50·A15 75 金币） | 3 | §280：`gold_cost` + `heal_pct` + `RequiresAsc` |
| `scrap_pile` | 1 | 2 | 0 | 9 | 9 段升级链（§285：`Chance` + `NextFail`） |
| `world_of_goop` | 1 | 2 | 0 | 2 | |
| `wing_statue` | 1 | **3** | **1**（牌组里有单次 ≥10 伤害的牌） | 2 | §287：读卡表数值的选项条件 |
| `dead_adventurer` | 1 | 2 | 0 | **25** | §288/§289：楼层门槛 + 21 个分支屏 + 精英伏击 |
| `ancient_forge` | 2, 3 | 2 | 0 | 0 | 本移植自有（升一张牌 / 拿煤） |
| `purification_shrine` | 2, 3 | 2 | 0 | 0 | 本移植自有（删一张牌） |
| `the_mausoleum` | 2 | 2 | 0 | 0 | |
| `forgotten_altar` | 2 | **4** | **1**（有金像） | 3 | §279：`relic_lose` 换血像 |
| `the_joust` | 2 | 1 | 0 | 5 | §285：70/30（`Chance` + `NextFail`），`MinGold: 51` |
| `the_colosseum` | 2 | 1 | 0 | 1 | §286：事件中途开战斗（两场），`MaxFloor: 7` |
| `the_nest` | 2 | 2 | 0 | 2 | §300：`gold_all` + `card:ritual_dagger` |
| `the_moai_head` | 3 | 3 | **1**（有金像） | 3 | §280：`heal_full` + `max_hp_pct:12.5` |
| `wandering_merchant` | 3 | 2 | 0 | 0 | **我们自己写的事件**（wiki 没有） |

### 1.2 wiki 三幕清单 vs 我们

| 幕 | wiki 清单 | 已有 | 缺 |
|---|---|---|---|
| 1（Exordium，11 条） | Big Fish / The Cleric / Dead Adventurer / Golden Idol / Living Wall / Hypnotizing Colored Mushrooms / Scrap Ooze / Shining Light / The Ssssserpent / Wing Statue / World of Goop | **8** | `big_fish` / `living_wall` / `mushrooms` |
| 2（The City，13 条） | Ancient Writing / Augmenter / The Colosseum / Council of Ghosts / Cursed Tome / Forgotten Altar / The Library / Masked Bandits / The Mausoleum / The Nest / Pleading Vagrant / Old Beggar / Vampires | **5**（另有 `the_joust`：wiki 这一版页面没列它，我们按 2 幕放） | `augmenter` / `council_of_ghosts` / `cursed_tome` / `the_library` / `masked_bandits` / `pleading_vagrant` / `old_beggar` / `vampires` |
| 3（The Beyond，7 条） | Falling / Mind Bloom / The Moai Head / Mysterious Sphere / Sensory Stone / Tomb of Lord Red Mask / Winding Halls | **4**（§318 补了 `Mysterious Sphere` / `Winding Halls`，§319 补了 `Falling`） | 其余 **3**：`sensory_stone` 要"无色牌 N 选 1"、`tomb_of_lord_red_mask` 要事件级遗物条件、`mind_bloom` 要 `upgrade_all` + `Normality` + "不能治疗"的载体 |

★ **结论**：**Act 1 基本齐（8/11），Act 2 与 Act 3 是主要缺口（5/13、1/7）**。
旧版本文档写"13 条已做"，其中 3 条（`old_shrine` / `ancient_forge` / `purification_shrine`）
是**我们自写的 shrine 类事件**，不在 wiki 的三幕清单里 —— 统计口径必须写清，否则"13 条"
会让人以为覆盖了 wiki 的 13 条。

---

## 2. 缺的、按"缺什么"分组

### 2.1 只缺内容（机制已够）

| 事件 | 幕 | 需要的原料 | 成本 |
|---|---|---|---|
| `big_fish` | 1 | `heal_pct` / `max_hp` / `relic` 三选一 + "拿到诅咒" | 小（三个原子都有） |
| `living_wall` | 1 | "复制 / 升级 / 移除一张牌" | 小（`duplicate` / `upgrade` / `remove` 都有） |
| `mushrooms` | 1 | "打一场（3 只真菌）" 或 "被迷惑（掉血）" | 小（§286 已能事件开战斗） |
| `augmenter` | 2 | "两张**随机**变形" | 小（`transform_random` 有） |
| `the_library` | 2 | "从 20 张里选一张" 需要 **N 选 1 的候选问句** | 中（`Offered` 问句只有 3 张的上限语义，需要"20 张任选"） |
| `pleading_vagrant` | 2 | `gold_cost` / 给诅咒 / 给两层虚弱 | 小 |
| `old_beggar` | 2 | 事件级"≥75 金币" + 给遗物 / 给诅咒 | 小（`MinGold` 已能筛池） |
| ~~`winding_halls`~~ | 3 | **§318 已做**：Madness ×2 + 12.5%（A15 18%）掉血 / Writhe + 25%（A15 20%）回血 / 5% 最大生命 | — |
| ~~`mysterious_sphere`~~ | 3 | **§318 已做**：`[Open Sphere]` 打**两只 Orb Walker**（`enc_two_orb_walkers`），Rare 遗物 + 普通战斗奖励 | — |
| `sensory_stone` | 3 | "从一堆**无色**牌里选一张" | 中（同 `the_library`） |
| `mind_bloom` | 3 | **wiki 的四个选项**（§311 更正：旧版这一格写错过）：① *I am War* —— 打一场第 1 幕 Boss，得稀有遗物 + 50（A15 25）金币；② *I am Awake* —— 升级所有牌 + `Mark of the Bloom`（**不能治疗**）；③ *I am Rich* —— 999 金币 + 2 张 `Normality`；④ *I am Healthy* —— 回满血 + `Doubt`；第三项按血量在 Rich / Healthy 之间换 | 大：要 `upgrade_all`、两条新诅咒、`mark_of_the_bloom`（"不能治疗"的载体）与"打一场**第 1 幕** Boss"（事件开战斗有了，**指定 Boss 池**还没有） |

### 2.2 缺机制

| 事件 | 幕 | 缺的机制 |
|---|---|---|
| `vampires` | 2 | `remove_all:<id>`（移除**所有**打击）+ `card:<id>` ×5（5 张 `bite`）+ 新牌 `bite`（含 `+` 行与"打出时回血"） |
| `n'loth` | 2 | "从自己的**遗物**里任选一件失去" —— 现在的 `PendingChoice` 只选**牌** |
| `masked_bandits` | 2 | 三名册外敌人（Pointy / Romeo / Bear）+ **金币区间**（25–35，今天只有定数） |
| `tomb_of_lord_red_mask` | 3 | 事件级"有红面具" + `gold_all`（**§300 已做**）⇒ 现在只差事件级条件与内容 |
| ~~`falling`~~ | 3 | **§319 已做**：`remove_card_random:<kind>`（随机删一张该类型）+ 条件原子 `card_tag`（没有该类型 ⇒ 按钮不画；三种都没有 ⇒ wiki 那条兜底 `[Land]`） |
| `council_of_ghosts` | 2 | `card:<id>` ×5 + 最大生命 -X% ⇒ 两个原子都有（`card:<id>` §300） |
| `cursed_tome` | 2 | "从三本里选一本，读几次掉血，最后给`necronomicon`" —— `necronomicon` **明确不做**，所以这条也不做 |
| `secret_portal` | 3 | "直接传送进 Boss 房"（跳过本幕剩余地图） |
| `designer_in_spire` | 2, 3 | 事件级"≥75 金币"（有 `MinGold`）+ 给一件"自定义"遗物等级 |

---

## 3. 机制缺口（不是内容缺口）

### 3.1 事件级条件：**部分有**，其余没有

**已经有了**（这一点旧文档说错了）：`EventTables` 的每一条可以带 `MinFloor` / `MaxFloor` /
`MinGold`，`rd-wasm` 在**掷骰之前先筛池**（`event_pool_at(floor, gold)`，§288/§291）：

| 已有 | 用户 |
|---|---|
| `MinFloor: 7` | `dead_adventurer`（wiki：floor 7 以上才出现） |
| `MaxFloor: 7` | `the_colosseum`（wiki：只在保底宝箱**之上**） |
| `MinGold: 51` | `the_joust`（wiki：≥50 金币） |

**还没有**的是另外几类：

* 遗物（`tomb_of_lord_red_mask` 要红面具）、
* HP 百分比（`the_moai_head` 要 ≤50%）、
* 牌组内容（没有 wiki 事件需要这条，但 `wing_statue` 是**选项级**的同类条件，已能做）、
* 计时（`secret_portal` 要"这一局已经 800 秒"）。

⚠️ **先别做**的理由和旧版一致：它加在 `?` 房的分流上，会改变**每一次** `?` 房的抽取
（`SOAK` / `ACT1_SLICE` 的覆盖会整片重掷）。要么单独一节、单独一组数字，要么等 `?` 房
本身再改一次时顺手做。

### 3.2 "从手上任选一件遗物失去"（`N'loth`）

需要一个**新的待决问句**：现在的 `PendingChoice` 有三类来源（手牌/弃牌堆/消耗堆/抽牌堆/三张候选），
**全是牌**。遗物问句与它同构（来源 + 候选 + `then`），成本主要在 ABI 与页面，不在内核。

### 3.3 卡牌侧的三个删/造原子

| 原子 | 谁要它 |
|---|---|
| `remove_all:<id>`（移除所有同 id 的牌） | `vampires` |
| `dup_deck`（整副牌复制一份） | `mind_bloom` |
| `upgrade_all`（升级所有牌） | `mind_bloom`（半血那条已经能用 `upgrade_random`） |

### 3.4 ~~随机结果~~ / ~~事件中途开战斗~~ —— 都已做完

* **随机**（§285）：`Chance` + `NextFail`，掷骰走 `RunStream::Event`。用户：`the_joust` 的 70/30、
  `scrap_pile` 的 9 段升级链。
* **事件中途开战斗**（§286）：`EventEffect::Fight` → 打完回到事件的下一屏。用户：`the_colosseum`
  的两场、`dead_adventurer` 的精英伏击（`EliteEvent` 池，Lagavulin 用**醒着**的变体）。

---

## 4. 最近几轮做了什么

| 节 | 做了什么 |
|---|---|
| §278–§280 | `EVND` 段表（选项数不固定）+ `EV.Entry` + `Requires`/`RequiresAsc` + `gold_cost` / `heal_pct` / `heal_full` / 小数百分比（千分）+ 第 1/2 幕的 `the_cleric` / `the_moai_head` |
| §285 | `Chance`/`NextFail`（`the_joust` 70/30、`scrap_pile` 9 段链）；`standard.confusion` / `snecko_eye` |
| §286 | 事件中途开战斗（`the_colosseum`、`dead_adventurer` 伏击）、`rd_run_event_fight` |
| §287 | 选项级"牌组里有单次 ≥10 伤害的牌"（`wing_statue`）、`[Destroy]` 的隐藏 |
| §288 | `MinFloor` 筛池（`dead_adventurer`）、`The Ambush` 的 Lagavulin 醒着变体 |
| §289–§291 | 奖励族与楼层门槛、`the_colosseum` 的 `MaxFloor`、`gold_cost` 的"付不起就别画"审计 |
| §300 | 三个原子：`gold_all`（`the_nest` 的 Ritual Dagger）、`card:<id>`、事件池剔无色 |
| §301–§305 | 遗物侧三批（`neows_lament` / `strange_spoon` / `wing_boots` / `gambling_chip` / `toolbox` / `frozen_eye`） |
| §306 | 事件侧无改动；核对本文与 `mechanism-gaps-analysis.md` 的口径 |

---

## 5. 下一步的排序建议

1. **Act 2 的普通遭遇池**（`docs/sts-wiki-gap.md` §D.3）：只有 3 条对 wiki 的 13 种组合，
   比事件更影响"每一局像不像 StS"。要 3 只新怪物（`spheric_guardian` / `snake_plant` /
   `centurion` + `mystic`），其余 6 条用现有怪物就能拼。
2. **只缺内容的 6 条事件**（§2.1）：`big_fish` / `living_wall` / `mushrooms` / `augmenter` /
   `pleading_vagrant` / `winding_halls` —— 每一条都只用已有原子，成本小、玩家感受直接。
3. **`remove_all:<id>` + `bite`**（`vampires`）：机制只多一个原子，但内容要一张新牌
   （`+` 行 + 打出回血），是"事件 + 卡牌"两条线一起验证的好样本。
4. **事件级条件**（§3.1）：先只做**遗物**与**HP%** 两类（不碰随机流），仍然要单独一节。
