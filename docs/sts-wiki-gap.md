# 对照 StS wiki 的功能缺口清单

> **这份文件回答一个问题**：站在玩家视角，本仓库距离"像《杀戮尖塔》"还差什么。
>
> **数字不写死在正文里**：所有"我们有 N 个 / 差 M 条"的 N 都由
> `python -X utf8 native/gap_check.py`（内容与规则）与
> `python -X utf8 native/sts_content_check.py`（内容自洽 + 交叉引用）**重算**并打印。
> 正文只写结论与出处；数字对不上时，是正文过期了，不是脚本。
>
> **两份来源**：`slaythespire.wiki.gg`（每条带页面名）+ 本仓库实现（§ 号指向 `docs/port-plan.md`）。
> 只有两边都看过的结论才写成"有"或"没有"；只在一处看到的写成"未核对"。
>
> **最近一次重核：2026-11-03**（本轮把 7 瓶药水、3 张无色牌、Act 2/3 精英逐个回到 wiki 页面核对；
> 抓到一处**内容写错**：`blind` 的稀有度写成 Common、且被写成 Exhaust —— wiki 是
> **Uncommon**、**不 Exhaust**，已修）。

---

## 0. 方法与口径

* **口径是铁甲战士（Ironclad）**，加上"三幕骨架能走通"与"一整幕可以从头打到幕末"。
  其他角色的专属内容一律**不做**，不列进缺口。
* `需要` 一列区分四种活：
  * **内容** —— 只写 JSON（`tools/contentc/packages/sts/sts.roguedeck.json`），内核不动；
  * **内核** —— 要新机制（`rd-core` / `rd-run` 的规则）；
  * **页面** —— ABI 已经够了，只差前端；
  * **驱动** —— 闸门/场景要改（例如"重试到赢"，§185）。
* 每条状态/关键词都注明是**内容侧**（触发器 + 已有 opcode）还是**管线侧**（写在内核的伤害/回合代码里）。

---

## 1. 已经对上的部分（不再列进缺口）

| 层 | 现状 | 出处 |
|---|---|---|
| 战斗内核 | 出牌 / 结算 / 状态 / 意图 / 修饰器管线 / 效果程序 IR / 选择与目标 / 金色指纹 | `SEMANTICS-v1.md`，§1–§128 |
| 卡牌关键词 | Exhaust / Ethereal / Innate / Retain / Unplayable / X 费 全部有载体 | §144 / §146 |
| 状态 | 内容里每一条状态要么有内核规则、要么**显式声明为 inert**（`is_declared_inert()`，7 条，`gap_check.py` 打印）。⚠️ "在 inert 名单上"只说明"内核没有硬编码规则" —— 它的行为在内容的触发器里，**这不等价于"StS 语义全对"**（审阅 §4.2） | §147 / §149 / §158 / §180 / §181 / §195.1–§195.7 |
| 三幕骨架 | 地图 15 行 × 7 列 + Boss 行、每幕独立的遭遇/事件池、幕间切换 | §130 / §131 / §133 / §137 |
| 战斗流程 | 召唤随从（敌人槽上限 6）、Boss 分裂、半血换招、**销毁战斗员**（§178） | §121 / §124 / §138–§140 / §178 |
| 运行层 | 商店（卡/遗物/药水/删卡 + 价格）、篝火（休息/打铁）、宝箱、事件、奖励屏、**脱战**（§179） | §143 / §161.8 / §179 |
| 药水 | **全部 33 瓶**（Ironclad 口径）都能喝，效果词表见 `gap_check.py` | §152 / §158 / §179–§185 |
| Ascension | **20 / 20 条都有机制**（13 条运行层规则，每条在阈值两侧各测一次）+ **A2/A3/A4 与 A17/18/19 的数值**：**79 条变体 / 72 个动作**（`gap_check.py` 的 pastable 区块）+ 事件列表的 A15 变体 | §159 / §187–§192、`gap_check.py` |
| 存档 / 回放 | 单行文本 + CRC（`RDA1`）；动作序列 + 每步哈希（`RDR1`）；内容指纹 | §161.9 / §163 / §164 / §166 |
| 前端 | 战斗 + 运行层 + 存档 + 回放；真浏览器闸门（真指针点击 + 像素判据 + 切片五场景） | §165 / §168 / §185 |
| 诊断 | 一步之内的有序事件（beats）、**拒绝码**与**宿主失败原文**导出（§177） | `env-abi.md` §12 |


### 1.1 数字只有一个来源（§195.9）

下面这一段是 `python -X utf8 native/gap_check.py` 的 **pastable 区块**原样贴进来 —— 文档里**不要**
再手写这些数字（README 里那份曾经写着"28 张基础 + 17 张升级 / 9 事件"，实际是 **27 + 18 / 12**，
而且没有任何闸门会红）。

```
monsters 46 / encounters 33 / cards 49 (base 29 + plus 20) / statuses 38 /
enemy actions 121 / relics 13 / potions 33 / events 12 (6+3+3) / start deck 10
ascension variants 79 over 72 actions
image full   content.sts.rdcf             71276 B
image core   content.sts.core.rdcf        60064 B
```

> ⚠️ **单位必须写清**（审阅 §8 第 5 条）：`45` 是**卡行**（27 基础 + 18 升级），不是 45 张职业卡；
> `79 / 72` 是**变体 / 动作**；`12` 是三个幕的事件池之和（`6+3+3`），不是单池大小。
---

## 2. 缺口

### A. 卡牌关键词 —— 只剩"没载体的"

| 关键词 | wiki 语义 | 我们的状态 | 需要 |
|---|---|---|---|
| Exhaust / Ethereal / Innate / Retain / Unplayable / X 费 | `Keywords` 页 | **有**（内容侧；X 费走 `x_cost` tag + `x.cost` + `node.repeat`） | — |
| **Duplication**（不是 Double Damage） | `Keywords` / `Duplication` 页 | **有**：`standard.duplication` + `play.rs` 把"下一张牌打两遍"做出来了（§181，Duplication Potion 在用） | — |
| **Double Damage**（"本回合攻击伤害 ×2"的倍率） | 同上 | **没有**，而且**与本项目无关**：它是 Watcher 的 Divinity / Blasphemy 语境；`standard.duplication` 是**追加打出一次**，不是倍率 | 不做（Ironclad 范围外） |
| **Double Tap / Entangled / Divinity** | 各自单卡页 | **Double Tap**（下一张 Attack 打两次）没有；**Entangled**（本回合不能打 Attack）没有；**Divinity** 是 Watcher 姿态，范围外 | 前两条见 §3 的顺序表 |
| **Exhaust 触发链**（"每当一张牌被消耗…"） | 触发器 | **载体有**（`LifecyclePrograms` 的 `CardExhausted`），**没有一张牌用它** | 内容 |
| **升级牌在战斗中回退**（"until end of combat" 的临时性） | — | **不适用**：我们照 wiki 的"for the rest of combat"，升级是**本场战斗内持久**的（§179） | — |

> ⚠️ 上一版写"X 费是唯一内核不许出现的 tag，内容门 [6d] 会拒"。**已过期**：§146 删掉了
> `reject_x_cost_deck`；内容检查反过来要求它的**印刷费用是 0**，因为代价走 `x_cost_payment`。

> ⚠️ **术语分开写**（审阅 §5.3）：**倍率**（Double Damage ×2）、**追加打出**（Duplication 任意牌 /
> Double Tap 限 Attack）、**姿态**（Divinity，Watcher）是三件不同的事。本项目只有第二件，
> 写文档时不要用"Double Damage"指它。

### B. 状态 —— wiki 常见而我们没有的

内容里目前的状态分三类（`gap_check.py` 打印全名）：

* **wiki 有、我们有规则**：`strength / vulnerable / weak / frail / dexterity / metallicize / thorns /
  spore_cloud / artifact / enrage / regen / rage / flame_barrier / combust / constricted /
  intangible / buffer / plated_armor / lose_strength / lose_dexterity / ritual / time_warp`；
* **本移植自己的载体**（wiki 没有同名状态，是我们拿来表达机制的最小零件）：
  `standard.fairy_in_a_bottle`（死亡拦截，§180）、`standard.duplication`（打两次，§181）、
  `standard.phantom_veil`（Nemesis 的"隔回合无形"，§175）、`standard.split` 与
  `standard.phase_split`（Boss 分裂的两半：`Downed` 与"血量 ≤10"）。**它们不是缺口**，
  写在这里是为了下一次有人看到"内容里有 wiki 没有的状态"时不用再查一遍。

wiki 常见而我们**没有**的：

| 状态 | wiki 语义 | 需要 |
|---|---|---|
| **Barricade / Blur** | 格挡不被清 / 本回合不清 | 内核（回合开始的清格挡要能跳过；`Block` 页点名这两个） |
| **Entangled** | 本回合不能打攻击牌 | 内核（`can_play_card` 的判据 + 回合末清） |
| **Slow** | 每打一张牌它受的伤害 +10% | 内核（伤害管线的修饰器） |
| **Draw / Energized（下一回合多抽 / 多能量）** | 回合开始结算 | 内核（回合开始的发牌/能量）—— 现在只有**本回合**的 `combat_draw` / `combat_energy` |
| **Poison / Focus / Orbs / Stance / Scry** | 其他角色的语言 | **不做**（口径之外） |

**已实现但值得记下的偏差**：`standard.poison` 若将来引入，参考实现的毒**不随回合衰减**（只有层数轴），
与《杀戮尖塔》不同 —— 别照 StS 直觉写。

### C. 战斗流程

| 机制 | 状态 | 需要 |
|---|---|---|
| 敌人召唤随从 | **有**（槽上限 6、主人死则随从逃） | — |
| Boss 分裂 | **有**，但目前**只有 Slime Boss**（`destroyCombatant` 到位后，"消失 + 两只顶替"才第一次能正确表达，§178） | 内容（另两只 Boss 各有新东西） |
| Boss 半血换招 | **有**（`intent.healthPercent`） | — |
| **销毁战斗员** | **有**（`node.destroyCombatant`，§178）：名册 / 回合序 / 牌堆表一起移位 | — |
| **死亡拦截** | **有**（`STAT.DeathPrevention` + PreDown 拦截，§180）：`Percent` 是本移植的扩展 | — |
| **自动打出** | **有**（`combat_autoplay_top`，§182，走普通 `play_card` + 每副本 0 费） | — |
| **整手牌升级 / 整手牌改费** | **有**（§179：`combat_upgrade_hand`、`combat_randomize_costs`） | — |
| **偷钱后逃跑**（Looter） | 没有 | 内容 + 一个"偷金币并 Escaped"的节目 |
| **往牌库塞牌**（Hexaghost 的 Burn） | 机制**有**（`createCardInstance` + 区） | 内容 |
| ~~形态切换 / 复活~~ | ✅ **已完成**（§195.1 Mode Shift 真累计受伤 / §195.2 `DeathPrevention` 真复活 / §195.8 Cultist 逃跑） | — |
| **Giant Head 的 "It Is Time" 递增**（30 点、每次 +5） | **没有**：本项目是**简化版**（320 HP + Metallicize 4 + Glare/Count 两招，§130 记录） | 内容（wiki 的 500 HP 对一局切片太长） |
| **逃跑（flee）** | **有**，但只在**运行层**（`result = 3`：不给奖励、节点算用掉、Boss 战拒绝，§179）。内核的 `CombatResult` 仍是参考的三种 | 内核（若要让敌人也能"逃走"并带走金币） |
| **自己行动时自毁**（Reptomancer 的匕首 Explode） | **做不到**：`remove_combatant` 拒绝移除**当前行动者**（回合循环按 id 找它） | 内核（"行动者消失后回合怎么收尾"的判据） |

### D. 运行层

| 项 | 状态 | 需要 |
|---|---|---|
| 地图 6 种节点 + Boss 行 / 每幕独立地图 | **有** | — |
| 遭遇池按幕分 | **有**（`gap_check.py` 打印每幕的数量） | 内容（第二幕的普通池只有 2 个） |
| **精英池** | 每幕 **3 个**：Act1 `three_sentries / gremlin_nob / lagavulin`、Act2 `gremlin_leader / book_of_stabbing / slavers`、Act3 `giant_head / nemesis / reptomancer` | — （wiki 的每幕 3 个齐了） |
| ~~Boss 池~~ | ✅ **每幕三只**（§194）：Slime Boss / Guardian / Hexaghost，Champ / Automaton / Collector，Time Eater / Awakened One / Donu & Deca | — |
| 药水 | **33 / 33**（Ironclad 口径） | — （见 §D.1，全部落地） |
| 遗物 | **13 件**（7 Common / 4 Uncommon / 1 Rare / 1 Event）。效果是 `rd-run` 里的**手写规则**，不是数据 | 内容 + 内核（每件一条规则）；总数**未核对**（wiki 的 `Relics List` 是模板生成的，取不到可直接引用的清单） |
| 篝火选项 | **只有 Rest / Smith**；wiki 的 `Rest Sites` 页另有 **Recall**（红钥匙，依赖第四幕）与三件遗物开启的 **Lift / Toke / Dig** | 内核（新选项类型）+ 内容 |
| 商店 | **有**（卡/遗物/药水/删卡，价格按稀有度；A16 加价）。⚠️ **无色牌不出售**：我们没有 StS 的无色货架，无色牌的唯一来源是 Colorless Potion（§185） | 内核（无色货架）+ 内容 |
| 事件 | **9 个**，每个选项是**一串**效果（§188），从 A15 起换用 `Effects*Asc` 的糟版本。词表仍是闭集：`heal / gold / damage / max_hp / nothing / remove_card / upgrade_card / transform_card / curse:<id> / relic:<id>` | 内容（缺真实事件的剧情分支：Golden Idol 的 Outrun/Smash/Hide 三选一在我们这里压成两选项，见 inventory §7） |
| 塔底 Neow | **9 项**祝福 | 内容（缺"用初始遗物换 Boss 遗物"这类交易） |
| **钥匙（红/蓝/绿）与第四幕** | 没有 | 内核 + 内容 |
| **Ascension 1–20** | **9 条 / 20 条**，见 §E | 内核（其余 11 条） |

#### D.1 药水池：**7 瓶全部落地**（留档，不再算缺口）

这一节原来逐瓶列"缺什么机制"，现在改成"每瓶最后是怎么做的"，方便下一次有人问
"Fairy in a Bottle 为什么是个状态"时有答案。

| 药水 | wiki 稀有度 | wiki 效果 | 落地方案 | § |
|---|---|---|---|---|
| Blessing of the Forge | Common | 本场战斗升级手牌里所有牌 | 换 `definition_id` 到 `id+` 那一行（`play` 按定义 id 查节目 ⇒ 升级是真的） | §179 |
| Snecko Oil | Rare | 抽 5；手牌费用随机化（本场战斗） | `standard.card_cost_override`：**绝对价**、不被出牌消费（delta 是"一次承诺"，表达不了 "for the rest of combat"） | §179 |
| Smoke Bomb | Rare | 逃离非 Boss 战斗，无奖励 | 运行层 `result = 3`（不是第四种 `CombatResult`，那会动黄金指纹） | §179 |
| Fairy in a Bottle | Rare | 致死改为回复 30% 最大生命 | `STAT.DeathPrevention`（参考的 PreDown 拦截器）+ `Percent` 扩展 | §180 |
| Duplication Potion | Uncommon | 本回合下一张牌打两次 | `standard.duplication` + 在 `apply_plan_in_chain` **跑两遍**（只付一次费、只算一次出牌） | §181 |
| Distilled Chaos | Uncommon | 打出抽牌堆顶 3 张 | 抽到手 → 每副本 0 费 → 走**普通** `play_card` | §182 |
| Colorless Potion | Common | 三选一无色牌进手牌（本回合 0 费） | `choice_offered:colorless` + 三张无色牌（不进任何牌组） | §183 / §185 |

> ⚠️ 上一版写"差的 13 瓶"。**已过期两轮**：§158/§160 之后剩 7 瓶，§179–§185 全部做完。
> 核对时还抓到我们自己的一个内容错误（`blind` 的稀有度与 Exhaust），说明**词表对了不等于每条
> 数据都对** —— 所以这一节的每一行都应该能点回 wiki 页面。

### G. ★ 基础值偏差：§191 修掉了 8 条，剩 3 条是写明了的简化

§190 补 A 数值时发现"有招式的基础值就和 wiki 不一致"。**这些不能加升档变体**（在错的地基上加层
只会更错），所以 §191 先修基础，再给它们补升档。

已修（数字全部来自 `native/wiki_asc/*.txt`）：

| 招式 | 原值 | 现在 | 升档 |
|---|---|---|---|
| `spiker.cut` | 8 | **7** | 有（A2: 9） |
| `the_champ.heavy_slash` | 18（写成了 A4 值） | **16** | 有（A4: 18） |
| `chosen.poke` | 6+6 | **5+5** | 有（A2: 6+6） |
| `darkling.chomp` | 单段 11 | **8×2** | 有（A2: 9×2） |
| `gremlin_leader.slash` | 单段 16 | **6×3** | 无（wiki 无升档值） |
| `the_champ.execute` | 单段 30 | **10×2** | 无 |
| `sentry.bolt` | 10 伤害 | **塞 2 张 Dazed** | 有（A18: 3 张） |
| `spire_growth.strategic` | Constricted 2 | **10** | 有（A2: 12） |

`dazed` 是新加的状态牌（Unplayable / Ethereal / 无效果），与 `slimed`、`wound` 同一族 ——
Sentry 的 Bolt 塞的就是它。

仍然**故意不修**（写在明处的简化，不是漏）：

| 招式 | 我们 | wiki | 为什么留着 |
|---|---|---|---|
| `giant_head.glare` / `count` | 12 伤害 + Weak / 26 伤害 | Weak 1（无伤害）/ 13 | 本项目是 **320 HP 的简化版**（§130），招式表跟着简化 |
| `maw.*`（3 招） | 自家设计 | **wiki 无此页**（404） | 没有出处就不编数字 |

**两条"模型表达不了"的现在都能表达了**（§192/§193），所以它们不再是缺口：

| 曾经的形状 | 现在 |
|---|---|
| 同一招两个档位（`jaw_worm.bellow`：Strength @A2、Block @A17） | `EACT.ProgramAsc` 是**变体列表**，A2 = Str 4 + Block 6，A17 = Str 5 + Block 9 |
| 可变伤害（`louse_*.bite` 5-7 / 6-8、`darkling.nip` 7-11 / 9-13） | 敌人记录里的 `Rolls` + 动作读 `combatantCounter`；值在**建战斗时**抽一次（wiki：*chosen at the start of combat*） |

⚠️ `louse_green.bite` 仍是**常量 6**：这份内容有 `louse_green.*` 动作却**没有** `louse_green`
敌人记录（`enc_louse` 只有一只红虱）。把它改成计数器读取等于给一个永远不会被抽的键写一个读 —
也就是"伤害 0"的地雷。`sts_content_check.py` 的 `INV_UNWIRED` 同时钉住两件事："它仍然读常量"
与"它仍然没有记录"；哪天真接上绿虱，那条检查当场红，逼着把记录和 `Rolls` 一起写。

### E. Ascension 逐条

`Module:Ascension`（wiki）列了 20 条，全部**累计**。我们的 9 条在阈值两侧各有一条测试。

| # | wiki 效果 | 状态 | 若要做，卡在哪 |
|---|---|---|---|
| 1 | 精英出现更多 | **有**（8% → 16%，普通战斗让出 8 点，§189） | — |
| 2 | 普通敌人伤害提高 | **有**（`EACT.ProgramAsc`，内容覆盖 29 个动作；§193 起可变伤害也在这一档） | — |
| 3 | 精英伤害提高 | **有**（4 个动作） | — |
| 4 | Boss 伤害提高 | **有**（3 个动作） | — |
| 5 | Boss 战后只回复 75% | **有** | — |
| 6 | 开局掉 10% 生命 | **有** | — |
| 7 | 普通敌人更硬（生命 + 格挡） | **有** | — |
| 8 | 精英更硬 | **有** | — |
| 9 | Boss 更硬 | **有** | — |
| 10 | 开局带 Ascender's Bane（诅咒） | **有**（内容加 `ascenders_bane`；开局进牌组，且删不掉，§189） | — |
| 11 | 少一个药水栏 | **有** | — |
| 12 | 升级牌出现率减半 | **有**（基线 0/12/25% 按幕，A12 减半成 0/6/12%，§189） | — |
| 13 | Boss 少给 25% 金币 | **有** | — |
| 14 | 最大生命 −5 | **有** | — |
| 15 | 事件更糟 | **有**（每个选项带 `Effects*Asc`，从 A15 起换成更糟的列表，§188） | — |
| 16 | 商店贵 10% | **有** | — |
| 17 | 普通敌人换招式表 | **有**（同一批变体里含 Slaver 的 Weak/Vulnerable 层数） | 内容：还有 33 个动作没有 wiki 出处 |
| 18 | 精英换招式表 | **有**（Book of Stabbing 的 `N = turn + 1`） | 同上 |
| 19 | Boss 换招式表 | **有**（Nemesis 5 张 Burn、Reptomancer 2 只匕首） | 同上 |
| 20 | 双 Boss（第三幕两只） | **有**（第一只倒下后节点重开，第二只才算赢，§189） | §194 起 `Boss3` 池有 3 只，所以两场可以是不同的一对 |

**A2/3/4 与 A17/18/19 的机制已经落地**（§187）：`EACT` 有一个 `ProgramAsc` 变体列表
（§192 起是列表，能装两个档位），外加一个 `intent.ascensionAtLeast` 条件。分档按**怪的种类**
（普通 2/17、精英 3/18、Boss 4/19），数字取自 wiki 单页。

⚠️ **覆盖是部分的，而且这个数字由脚本报**：`gap_check.py` 会打印"多少个动作有变体、多少个还没有"
（当前 48 个动作 / 49 条变体，还有 31 个动作没有）。剩下的动作不是"忘了"，而是**没有 wiki 出处就不写**（`§186` 的教训：抄一个数字
比留空更贵）。要补的时候照 `native/patch_187_content.py` 的表加一行 + `INV_ASC_VARIANTS` 加一行。

**20 / 20 条全部有机制**（§189 补齐 A1 / A10 / A12 / A20），而且 **A2/3/4 与 A17/18/19 的数值
已经覆盖 42 / 79 个动作**（§190：13 → 42）。剩下的 37 个里，一部分本来就没有升档（`Does nothing`、
纯召唤、纯状态），另一部分是 §G 列的基础值不一致 —— 那要先修基础，不是补升档。
§194 起 `Boss3` 池有 3 只，所以 A20 的两场可以抽到不同的一对 Boss。

### F. 前端 / Live2D 需要的 ABI

**够用的**：战斗观察向量、动作表、牌堆/手牌读名、敌人读名与意图、运行层观察（19 个 slot）、
`rd_env_beat_*`（一步之内的有序事件 + 墙位 + DoT 标记 + 丢条计数）、`rd_env_forced_turns`、
`rd_env_enemy_is_minion`。

**§177 补上的诊断**（原来"这一步抛了"只有一句家族名）：`rd_env_step_code` /
`rd_env_code_name_len|into` / `rd_env_host_failure_len|into`。前两个说"哪一类拒绝"，
最后一个直接给宿主**原始错误**（`Host::last_failure()` 一直存着，只是没有导出读它）。

**还不够的两项**（都不是硬前提，但 Live2D 一定会要）：

| 缺什么 | 为什么 |
|---|---|
| 攻击/受击的**"意图-结果"配对** | 动画要知道"这一拳是为哪条意图落地的"。beats 有"谁打了谁"，没有"对应哪条意图" |
| 牌离手 → 目标 → 弃牌堆的**行进轨迹** | beats 有"谁打了谁"，没有"牌从手牌第 3 格飞到目标"这一段空间信息 |

---

## 3. 建议顺序（按"玩家感受 / 成本"比）

> ⚠️ 这一节只列**当前**的缺口。已完成项不在这里（旧版本列的"事件效果列表 / A1·A10·A12 /
> 补 66 个 ascension 数字 / 第二三只 Boss / A20 双 Boss"都已在 §188、§189、§190–§191、§194 落地，
> 历史见 `port-plan.md` 对应节）。

1. ~~`Entangled` + Red Slaver 的第三招~~ ✅ **已完成**（§196：`Validator::Entangled` + 拒绝码 18 +
   Red Slaver 的 5 条规则）。
2. ~~`Barricade` / `Blur`~~ ✅ **已完成**（§197：`retain_block` / `retain_block_once` 两个 tag +
   两张卡；后者是一次性的，由内核在"它阻止了清空"那一刻摘掉）。
3. **`Slow`（Giant Head）与"下回合多抽/多能量"**（内核：回合边界的延迟结算）—— 后者是所有
   "Energized / Draw" 类卡与药水的前提。
4. **"行动者可以自毁"**（内核）—— 解锁 Reptomancer 匕首的 Explode；Looter 的偷钱逃走也走这条。
5. **内容规模**（卡池 / 遗物 / 事件 / Act2 普通池）—— 纯量，不阻塞机制；**不要**当 P1（见审阅
   报告 §10.4 的反对意见）。
6. **第四幕与钥匙**（运行层）—— 明确的范围外，等前面清完再说。

---

## 4. 这份文档怎么保持不烂

* 数字：`python -X utf8 native/gap_check.py`（内容/规则）与
  `python -X utf8 native/sts_content_check.py`（内容自洽）。
* wiki 侧引用（`slaythespire.wiki.gg`，最近核对 **2026-11-03**）：`Potions_List`、`Module:Potions/data`、
  `Colorless_Cards`、`Blind` / `Bandage_Up` / `Dark_Shackles` 单卡页、`Module:Ascension`、
  `Keywords`、`Rest Sites`、`Relics`、`Acts`、`Lagavulin` / `Book_of_Stabbing` / `Nemesis` /
  `Reptomancer` / `Slavers` / `Taskmaster`。**页面会变**，所以只引页面名 + 核对日期。
* 改了内容或内核规则之后，**跑一遍脚本**，把正文里对不上的句子改掉 —— 或者干脆改成"见脚本"。
  一句"我们有 26/33 瓶药水"如果没人重算，它会在下一次内容变更后变成谎话，而**没有任何闸门会红**。
* ⚠️ **闸门看不见 wiki**：本轮重核抓到 `blind` 的稀有度与 Exhaust 都写错了，而 20 道闸门全绿
  （内容门对照的是 `docs/spec/` 的清单，清单本身也是人抄的）。⇒ 新内容落地时，**至少把稀有度
  与"是否 Exhaust"这两列回到单卡页看一眼**，它们是最容易"顺手抄邻居"的两格。

## H. Boss 机制：**当前**与 wiki 的剩余差异（§194 → §195.9）

数字全部来自 `native/wiki_asc/<boss>.txt`（`action=raw`）。这一张表**只写现在的差异**，
历史降级（"Guardian 只按 HP 切形态""Awakened One 没有死亡拦截 / 没有 Cultist""Bronze Orb 没有
Stasis""小兵预置"）已在 §195.1–§195.8 逐条修掉，过程见 `port-plan.md` 那几节。

| Boss | 现在的行为 | 与 wiki 的**剩余**差异 |
|---|---|---|
| The Guardian | 进攻 4 循环；Sharp Hide（`CardPlayed` + `hasTag.attack`）；**Mode Shift = 累计受伤**（`Counters` 种 30/35/40，`eventAmount` 扣减，切防御态 +10）；防御态 Roll → Twin Slam → Whirlwind | 无（switch 落在"下一次选意图"，敌人只在自己回合动作） |
| Hexaghost | Activate / Divider 两个开场规则 + 7 招轮转；Divider = `(HP/12 + 1) × 6`；**Inferno 升级所有已有 Burn**（`node.upgradeCards`） | Sear 后续塞的 Burn **不**自动升级（wiki："for the rest of combat"）；Divider 读结算时 HP |
| The Champ | 420 HP；**45/25/15/15 带权抽签** + 任何一招不能连续两次 + 每 4 回合 Taunt；≤50% 后 Anger → Execute | A19 的 "Gloat 换成 Defensive Stance" 未实现；Anger 按名清 debuff；第二阶段只做第一次 Execute |
| Bronze Automaton | 300 HP + Artifact 3；第 1 回合 **真召唤 2 Orb**（`Spawn: false`）；6 招循环；A19 用 Boost 顶替 Stunned | Orb 的 `Stasis` 用"最高稀有度"（并列随机），与 wiki 一致；"同一招不能三次"已做 |
| The Collector | 282 HP；第 1 回合 **真召唤 2 Torch Head**；70/30 带权 + 不能连 Buff + 不能三次 Fireball；第 4 回合 Mega Debuff | 25/45/30（0-1 只 Torch Head 时的权重）未分档 |
| Time Eater | 456 HP；45/35/20 带权 + 三次/两次的排除规则；≤50% 的 Haste 回血一次 | Haste 不清 debuff（没有"清空状态"节点）；`Draw Reduction` 已实现但 wiki 的"A19 另加 2 Slimed"没做 |
| Awakened One | 300 HP；`DeathPrevention` 真复活；一阶段 75/25 + Slash 不能三次；二阶段 Dark Echo 一次后 50/50；**带两只 Cultist，主人倒下时逃跑** | 二阶段"不能连续三次 Tackle/Sludge"未做（规则预算 8 条已满）；Regenerate/Curiosity 层数不随 A19 变 |
| Donu & Deca | 一对（250 HP 各 + Artifact 2）；Donu 交替 Circle / Beam；Deca 交替 Beam / Square | Artifact 层数不随 A19 变（`StartingStatuses` 没有升档轴） |

**两条全局的**（都不在 Boss 里）：

1. **A9 的 `AscHP` 不精确** —— 跑层对 `MaxHealth` 施加的是**百分比**（§159 的 A7/A8/A9 规则，
   420 → 525），不是 wiki 的定值。
2. **抽签是 `(seed, round, slot)` 的派生值** —— 不是随机流，两次抽签之间没有顺序关系（§195.3）。

**已知测试缺口**（如实报告，不是遗漏）：`selectCards` 的 `Count > found` 边界在**状态上不可观测**
（同区搬运是 no-op），能看见它的只有 `ExecStats::effects`，而计数器只对"`Count > 1` 且候选更少"的
**程序**可见 —— 本内容唯一这样的调用在触发器里，宿主不回收它的 stats。修法：给 `Host` 也记一份
effect 账（§195.9 记录，未做）。
