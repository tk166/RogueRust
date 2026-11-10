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
> **最近一次重核：§233 之后**（刷新了四件事：① §1.1 的 pastable 数字；② 状态清单与
> "声明为 inert"的条数；③ **新增 §A.1 的卡牌盘点** —— 与 wiki 的 Cargo 卡表逐张对账，工具是
> `native/audit_card_gap.py`，离线索引 `native/wiki_card_index.json`；④ 篝火/无色货架两节的现状）。
> 上一版写着 §195 时代的数字（"49 卡行 / 39 状态 / 71,848 B"）与本轮之前的状态清单，**都已过期**。

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
| 状态 | **148 条**；每一条要么有内核规则、要么**显式声明为 inert**（`is_declared_inert()`，**37 条**，`gap_check.py` 打印全名）。⚠️ "在 inert 名单上"只说明"内核没有硬编码规则" —— 它的行为在内容的触发器里，**这不等价于"StS 语义全对"**（审阅 §4.2） | §147 / §149 / §158 / §180 / §181 / §195.1–§195.7 |
| 三幕骨架 | 地图 15 行 × 7 列 + Boss 行、每幕独立的遭遇/事件池、幕间切换 | §130 / §131 / §133 / §137 |
| 战斗流程 | 召唤随从（敌人槽上限 6）、Boss 分裂、半血换招、**销毁战斗员**（§178） | §121 / §124 / §138–§140 / §178 |
| 运行层 | 商店（卡/遗物/药水/删卡 + 价格）、篝火（休息/打铁）、宝箱、事件、奖励屏、**脱战**（§179） | §143 / §161.8 / §179 |
| 药水 | **全部 33 瓶**（Ironclad 口径）都能喝，效果词表见 `gap_check.py` | §152 / §158 / §179–§185 |
| 遗物 | **152 / 193**；分桶与载体清单见 §D.2，逐条清单在 `docs/relic-inventory.md` | §259–§274 / §292–§305 |
| 卡牌（**数量**） | **295 行 = 155 张基础 + 140 条升级行**；口径内 **147 / 220（齐的 147 张里 Red 75/75 + Colorless 70/70 + 诅咒/状态）**，**缺的 73 张全是观者**。**逐张盘点见 §A.1** | §218–§233 / §306 核对 / `audit_card_gap.py` |
| Ascension | **20 / 20 条都有机制**，但分成两半：**14 条是 `rd-run` 的规则常量**（A1 A5–A16 A20，`gap_check.py` 打印），**6 条走内容数据**（A2/A3/A4 与 A17/18/19 的 `EACT.ProgramAsc`）。数值侧：**128 条变体 / 107 个动作**（**59 个动作仍无 wiki 出处**，`gap_check.py` 打印 `without a variant: 59`）+ 事件列表的 A15 变体。⚠️ §328 起有**闸门**：wiki 写了 `{{Asc|N|` 而内容缺档的动作必须是 **0** 条（`sts_content_check.py` 的 `[7b]`）；人跑的对账是 `audit_asc_gap.py`（§330 修好了它只读第一个档位的解析 bug）。逐条见 §E | §159 / §187–§192 / §306 / §328–§330 |
| 存档 / 回放 | 单行文本 + CRC（`RDA1`）；动作序列 + 每步哈希（`RDR1`）；内容指纹 | §161.9 / §163 / §164 / §166 |
| 前端 | 战斗 + 运行层 + 存档 + 回放；真浏览器闸门（真指针点击 + 像素判据 + 切片五场景） | §165 / §168 / §185 |
| 诊断 | 一步之内的有序事件（beats）、**拒绝码**与**宿主失败原文**导出（§177） | `env-abi.md` §12 |


### 1.1 数字只有一个来源（§195.9）

下面这一段是 `python -X utf8 native/gap_check.py` 的 **pastable 区块**原样贴进来 —— 文档里**不要**
再手写这些数字（README 里那份曾经写着"28 张基础 + 17 张升级 / 9 事件"，实际是 **27 + 18 / 12**，
而且没有任何闸门会红）。

```
monsters 61 / encounters 64 / cards 295 (base 155 + plus 140) / statuses 148 /
enemy actions 166 / relics 152 / potions 33 / events 38 (13+15+10) / start deck 10
ascension variants 128 over 107 actions
image full   content.sts.rdcf            189024 B
image core   content.sts.core.rdcf       151460 B
```

> ⚠️ **单位必须写清**（审阅 §8 第 5 条）：`295` 是**卡行**（155 基础 + 140 升级行），不是 295 张不同的牌
> —— 而且其中包含状态/诅咒牌与多档升级行（`searing_blow+`…`++++++`）；
> `128 / 107` 是**变体 / 动作**；`38` 是三个幕的事件池之和（`13+15+10`），**不是**不同事件数 ——
> `golden_idol` / `ancient_forge` / `purification_shrine` 跨幕复用，去重之后是 **35 条**
> （§318–§325 把 Act 1/2/3 补到 11/12/7，与 wiki 的 31 条比是 **28 条**，只差 `cursed_tome`）。
> `relics 152` 是**内容行**（§330 之前这里是 153 —— 那多出来的一行是 `mutagenic_strength`
> 的**重复行**，现在有闸门 `[7g]` 挡着）；wiki 有 193 条，缺 41 条（§D.2）。
---

## 2. 缺口

### A. 卡牌关键词 —— 只剩"没载体的"

| 关键词 | wiki 语义 | 我们的状态 | 需要 |
|---|---|---|---|
| Exhaust / Ethereal / Innate / Retain / Unplayable / X 费 | `Keywords` 页 | **有**（内容侧；X 费走 `x_cost` tag + `x.cost` + `node.repeat`） | — |
| **Duplication**（不是 Double Damage） | `Keywords` / `Duplication` 页 | **有**：`standard.duplication` + `play.rs` 把"下一张牌打两遍"做出来了（§181，Duplication Potion 在用） | — |
| **Double Damage**（"本回合攻击伤害 ×2"的倍率） | 同上 | **没有**，而且**与本项目无关**：它是 Watcher 的 Divinity / Blasphemy 语境；`standard.duplication` 是**追加打出一次**，不是倍率 | 不做（Ironclad 范围外） |
| **Double Tap / Entangled / Divinity** | 各自单卡页 | **Double Tap**（下一张 Attack 打两次）**还没有**（缺的是"限 Attack 的追加打出"，`standard.duplication` 是不限牌的）；**Entangled 有**（`standard.entangled` + `play::Validator::Entangled`，Red Slaver 在用）；**Divinity** 是 Watcher 姿态，口径外 | Double Tap 见 §3 的顺序表 |
| **Exhaust 触发链**（"每当一张牌被消耗…"） | 触发器 | **载体有**（`LifecyclePrograms` 的 `CardExhausted`），**没有一张牌用它** | 内容 |
| **升级牌在战斗中回退**（"until end of combat" 的临时性） | — | **不适用**：我们照 wiki 的"for the rest of combat"，升级是**本场战斗内持久**的（§179） | — |

> ⚠️ 上一版写"X 费是唯一内核不许出现的 tag，内容门 [6d] 会拒"。**已过期**：§146 删掉了
> `reject_x_cost_deck`；内容检查反过来要求它的**印刷费用是 0**，因为代价走 `x_cost_payment`。

> ⚠️ **术语分开写**（审阅 §5.3）：**倍率**（Double Damage ×2）、**追加打出**（Duplication 任意牌 /
> Double Tap 限 Attack）、**姿态**（Divinity，Watcher）是三件不同的事。本项目只有第二件，
> 写文档时不要用"Double Damage"指它。

### A.1 卡牌盘点：与 wiki 的 **Cargo 卡表**逐张对账（§233 起）

口径：wiki 的 `Color` 字段（Red=铁甲战士 / Colorless=无色 / Curse / Status），**只把
Red + Colorless + Curse + Status 算进范围**；其它颜色只统计、不算缺口。StS2 的行（`Slay the Spire 2:`
前缀，共 604 条）一律剔除。名字 → id 的归一是 `lower().replace(" ", "_").replace("'", "")`。

跑法（会重新拉表并写离线索引）：

```
python -X utf8 native/audit_card_gap.py --write     # 需要代理；写 native/wiki_card_index.json
python -X utf8 native/audit_card_gap.py --offline   # 只读索引，CI/无网时用
```

**§306 核对的最新账**（`--offline`，wiki 索引 `native/wiki_card_index.json`，990 行）：

```
in-scope missing: 73   (have 147 of 220)
Red     75 / 75   （齐）
Colorless 70 / 70 （齐）
Purple  0 / 72    （缺 73 里的一张是 Purple Power；这 73 张全部属于观者）
content-only: blur, buffer, malaise, nightmare, patient_guard, rip_and_tear, skewer
             （wiki 归在别的颜色下，或本移植自有）
```

**现状（§252 之后没再变过）**：口径内 **147 / 220**，**缺的 73 张全是观者（紫）** ——
Red **75 / 75**、Colorless **70 / 70**、诅咒与状态齐。上面那段 pastable 区块里的
`cards 295 (base 155 + plus 140)` 是**卡行**，与这里的"张数"不是一个单位。

观者的 73 张不是"一张张补"能收的：它们成堆挂在**姿态系统**（`calm` / `wrath` / `divinity`，
约 30 张）、**Mantra / Divinity**、**Scry**、**Retain + `Establishment`**、
**`Alpha` → `Beta` → `Omega`** 上。所以下一批要按**基建**聚类做（先做姿态机与 Scry 两条载体，
再成批补牌），而不是照 §A.1 的清单从上往下写。

> ⚠️ **已删掉的一段**（§330）：这里原来是 §246 时期的"施工单"，按"需要什么载体"列了 30 多张
> 红卡与无色牌（`exhume` 要 `ExhaustPile` 问句、`clash` 要 `PlayCondition` 读整手牌、
> `double_tap` 要"下一张 Attack 打两次"、`havoc` / `infernal_blade` 要随机生成与强制打出、
> `burning_pact` 要"问完再继续"、`spot_weakness` 要读敌人意图……）。那些载体在 §247–§252
> 全部补齐了，无色也从 38/70 做到了 70/70 —— 留着那张单子会让人以为还得再做一遍，
> 而且它与同一页的"Colorless 70 / 70（齐）"直接矛盾。

> ⚠️ **口径**：只把 Red + Colorless + Curse + Status 算进范围；别的颜色只统计。同一张牌在我们
> 的内容里也可能挂在别的颜色下（`malaise` / `nightmare` / `rip_and_tear` / `skewer` 是静默猎手牌、
> `blur` / `buffer` 是故障机器人牌，都在本内容里做过）。脚本把它们列成 "content-only"，
> 这是**有意的**：口径是"能玩的机制"，不是"只抄一个职业"。

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
| **Draw / Energized（**下一回合**多抽 / 多能量）** | 回合开始结算 | 内核（回合开始的发牌/能量）—— 现在只有**本回合**的 `combat_draw` / `combat_energy`，以及"下一回合**少**抽"的 `standard.draw_reduction` |
| **Poison / Focus / Orbs / Stance / Scry** | 其他角色的语言 | **不做**（口径之外） |

> §233 修正：上一版把 **Barricade / Blur / Entangled / Slow** 列在这里 —— 四条**都已经实现了**
> （`standard.barricade` / `.blur` / `.entangled` / `.slow`，其中 slow 走 `RestrictDamageKind`，
> 见 §G.2 那条"只用 Direct 伤害放大"的声明）。删掉它们是因为缺口清单不能留着已经做完的条目 ——
> 那种陈旧比漏写更坏，它让人以为还得再做一次。

**已实现但值得记下的偏差**：`standard.poison` 若将来引入，参考实现的毒**不随回合衰减**（只有层数轴），
与《杀戮尖塔》不同 —— 别照 StS 直觉写。

### C. 战斗流程

| 机制 | 状态 | 需要 |
|---|---|---|
| 敌人召唤随从 | **有**（槽上限 6、主人死则随从逃） | — |
| Boss 分裂 | **有**，但目前**只有 Slime Boss**（`destroyCombatant` 到位后，"消失 + 两只顶替"才第一次能正确表达，§178）。⚠️ "相位"是另一件事，六个 Boss 的相位规则已在 §329–§330 逐条对过 wiki | 内容（另两只 Boss 各有新东西） |
| Boss 半血换招 | **有**（`intent.healthPercent`） | — |
| **销毁战斗员** | **有**（`node.destroyCombatant`，§178）：名册 / 回合序 / 牌堆表一起移位 | — |
| **死亡拦截** | **有**（`STAT.DeathPrevention` + PreDown 拦截，§180）：`Percent` 是本移植的扩展 | — |
| **自动打出** | **有**（`combat_autoplay_top`，§182，走普通 `play_card` + 每副本 0 费） | — |
| **整手牌升级 / 整手牌改费** | **有**（§179：`combat_upgrade_hand`、`combat_randomize_costs`） | — |
| ~~**偷钱后逃跑**（Looter）~~ | ✅ **已完成**（§201：`Thievery 15` 用 `setCombatantCounter` 记在敌人身上；`node.carryAwayStolenGold` 把逃走时带走的钱搬进 `CombatState::gold_carried_away`；运行层在 `fight_end` 扣 —— 死掉的小偷不扣，因为它的计数器不算「被带走」） | — |
| **往牌库塞牌**（Hexaghost 的 Burn） | 机制**有**（`createCardInstance` + 区） | 内容 |
| ~~形态切换 / 复活~~ | ✅ **已完成**（§195.1 Mode Shift 真累计受伤 / §195.2 `DeathPrevention` 真复活 / §195.8 Cultist 逃跑） | — |
| **Giant Head 的 "It Is Time" 递增**（30 点、每次 +5） | **没有**：本项目是**简化版**（320 HP + Metallicize 4 + Glare/Count 两招，§130 记录） | 内容（wiki 的 500 HP 对一局切片太长） |
| **逃跑（flee）** | **有**，但只在**运行层**（`result = 3`：不给奖励、节点算用掉、Boss 战拒绝，§179）。内核的 `CombatResult` 仍是参考的三种 | 内核（若要让敌人也能"逃走"并带走金币） |
| ~~**自己行动时自毁**（Reptomancer 的匕首 Explode）~~ | ✅ **已完成**（§200：`remove_combatant` 允许移除当前行动者，席位按**腾空的那一格**交给继任者 —— 不是"设成继任者"（会跳两格）也不是"认领第一个活人"（会从头开始）；`dagger.explode` = 25 伤害 + 自毁） | — |

### D. 运行层

| 项 | 状态 | 需要 |
|---|---|---|
| 地图 6 种节点 + Boss 行 / 每幕独立地图 | **有** | — |
| 遭遇池按幕分 | **有**（`gap_check.py` 打印每幕的数量）：普通池 Act 1 **17** / Act 2 **13/13** / Act 3 **10/10** | — |
| **精英池** | 每幕 **3 个**：Act1 `three_sentries / gremlin_nob / lagavulin`、Act2 `gremlin_leader / book_of_stabbing / slavers`、Act3 `giant_head / nemesis / reptomancer` | — （wiki 的每幕 3 个齐了；§327 补了升档数值：Slaver 的 HP 档位 A7、Taskmaster 的 Whip A2/A18） |
| **招式表升档** | §328：wiki 写了 `{{Asc\|N\|` 而内容缺档的动作 **0** 条（审计 115/166 条意图行；3 条由别的机制表达：`darkling.nip` 走 `Rolls`、`book_of_stabbing.multi_stab` 走 A18 计数器、`the_guardian.twin_slam` 走 `mode_shift_budget` 计数器） | — （`native/sts_content_check.py` 的 `[7b]` 每次验收都重比一遍） |
| **Boss 相位** | §329：六个 Boss 的相位规则逐条对过 wiki —— Champ 的 Anger/Execute、Awakened One 的 unawakened→Rebirth、Collector 的两条召唤分支、Automaton 的 A19 Boost 顶替 Stunned、Time Eater 的一次性 Haste、Donu/Deca 的交替；本轮补了 Rebirth/Haste 的 **清 Debuff**与 Collector 的 **再召唤 + up to 2** | — （余下只有"A19 的具体数值"这类，已由 `[7]`/`[7b]` 钉住） |
| ~~Boss 池~~ | ✅ **每幕三只**（§194）：Slime Boss / Guardian / Hexaghost，Champ / Automaton / Collector，Time Eater / Awakened One / Donu & Deca | — |
| 药水 | **33 / 33**（Ironclad 口径） | — （见 §D.1，全部落地） |
| 遗物 | **152 / 193**（`audit_relic_gap.py` 的账：`MISSING: 41`、`METADATA: 0`、`IMPLEMENTED: 内核不认识 0`）。分档、载体决策树与逐条清单见 §D.2 与 `docs/relic-inventory.md` | 内容（缺的 41 件：Blight 13 / 别的角色 20 / `bottled_*` 3 / `necronomicon` / `circlet` 2 / 其余 2） |
| 篝火选项 | **六个全通**（§259）：Rest / Smith / **Recall**（红钥匙）/ **Lift**（`Girya`，最多 3 次、之后每场战斗带这些力量）/ **Toke**（`Peace Pipe`，删牌免费）/ **Dig**（`Shovel`，只抽 Common/Uncommon/Rare）；`Coffee Dripper` / `Mark of the Bloom` 关 Rest、`Fusion Hammer` 关 Smith、`Dream Catcher` 让休息额外给一次卡牌奖励 | — （`Recall` 的用处是第四幕，见最后一行） |
| 商店 | **有**（卡/遗物/药水/删卡，价格按稀有度；A16 加价；`the_courier` 刷新货架、`membership_card` 打折）。⚠️ **无色牌仍不出售**：没有 StS 的无色货架 —— 内容侧的无色池已经 **70/70**（§243–§252），缺的只是**商店里那一排**（`stock_shop` 加一排即可） | 内核（无色货架） |
| 事件 | **35 条**（三幕池 13+15+10 = 38 条，110 个 `EVND` 段）。剧情分支是**真树**（`EVND` 段表 + `EV.Entry`，选项数不固定），选项支持 `Requires` / `RequiresAsc`、按类型的选牌问句（`the_library` / `sensory_stone` / `falling`）、事件中途开战斗（`dead_adventurer` / `mysterious_sphere` / `colosseum`）与 A15 的糟化分支。与 wiki 的 31 条比是 **28 条**（Act 1 11/11、Act 2 12/13、Act 3 7/7） | 内容（`cursed_tome` 明确不做 —— `necronomicon` 不在范围）。机制侧仍缺**事件级条件**与"任选一件遗物失去"（`N'loth`），见 §2 与 `docs/event-gaps.md` |
| 塔底 Neow | **9 项**祝福 | 内容（缺"用初始遗物换 Boss 遗物"这类交易） |
| **钥匙（红/蓝/绿）与第四幕** | 没有 | 内核 + 内容 |
| **Ascension 1–20** | **20 / 20 条有机制**：14 条是运行层规则常量（A1 A5–A16 A20，`gap_check.py` 打印），A2/A3/A4 与 A17/18/19 走内容的 `EACT.ProgramAsc`。**wiki 写了 `{{Asc|N|` 而内容缺档的动作是 0 条**（闸门 `[7b]`，§328），档位按**怪物**钉（§315/§327） | — （`without a variant: 59` 是 wiki 本来就没写升档的动作） |

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

### D.2 遗物：**152 / 193** —— 已实现的规则与剩下的分档（§259–§274，§292–§305）

> 这一节原先长在 `README.md` 里。搬到这里的理由：README 只留**统计数字**，
> "某件遗物靠哪条管线成立"属于缺口/载体文档。方法论另有
> `docs/function_scaling_up_for_relics.md`。

**账**（`native/audit_relic_gap.py`，数据源 wiki 的 `Module:Relics/data`，Lua 表离线留档）：

| 桶 | 有 / 总 | 说明 |
|---|---|---|
| Common | 34 / 36 | 缺 `damaru` / `data_disk`（Defect 专属） |
| Uncommon | 29 / 36 | 缺 7 件，**6 件是别的角色专属**（`bottled_*` 三件 + `gold_plated_cables` / `symbiotic_virus` / `teardrop_locket`）与静默的 `ninja_scroll` |
| Rare | 30 / 34 | 缺 `emotion_chip` / `golden_eye` / `tingsha` / `tough_bandages` |
| Boss | 23 / 30 | 缺 7 件，**全是别的角色的能量/球**（`frozen_core` `holy_water` `hovering_kite` `inserter` `nuclear_battery` `violet_lotus` `wrist_blade`） |
| Shop | 17 / 20 | 缺 `melange` / `prismatic_shard` / `runic_capacitor` |
| Event | 17 / 18 | 只差 `necronomicon`（**明确不做**：打两次） |
| Starter | 2 / 4 | 铁甲战士的 `burning_blood` + 通用的 `black_blood`；缺 `cracked_core` / `pure_water` |
| Special | 0 / 2 | `circlet` 一类，**不做**（wiki 自己也标无用） |
| Blight | 0 / 13 | **无尽模式，不做** |

> 口径（§306 核对）：`native/audit_relic_gap.py` → `内容 152 条（152 条内核认识）`、
> `MISSING: 41`、`METADATA（两边都有但写错）: 0`、`IMPLEMENTED: … 内核不认识: 0`。
> 41 件里 **13 件 Blight + 2 件 Special + 约 18 件别的角色专属** ⇒ 铁甲战士这条线上真正
> 可做的只有 `necronomicon`（不做）、`tingsha` / `tough_bandages`（缺 `CardDiscarded` 事实）、
> `golden_eye` / `bottled_*`（拾取时绑牌）这几类。

**效果怎么实现的**（不是"每件一个 if"，而是按载体归类）：

| 载体 | 遗物 |
|---|---|
| **零内核改动**：开战挂一条带触发器/修饰器的**内容状态**（§260） | `orichalcum` `mercury_hourglass` `horn_cleat` `captains_wheel` `stone_calendar` `cloak_clasp` `incense_burner` `pocketwatch` |
| 走**标签**（`ice_cream` / `calipers`）、"数牌组"（`du_vu_doll`）、"每第 N 张某类型牌"（§262） | `kunai` `shuriken` `ornamental_fan` `letter_opener` `nunchaku` `ink_bottle` `pen_nib` |
| "敌人死亡时"（`gremlin_horn` / `the_specimen`，后者靠新事件 `FoeDowned`）、"伤害管线数值改写" | `the_boot` `torii` `tungsten_rod` |
| **改写别的状态幅值**（`PassiveModifiers.AppliesToStatusId`）、"施加易伤时附带虚弱"（`event.statusIs`） | `paper_phrog` `paper_krane` `champion_belt` |
| **改状态施加**：多施一层毒 / 让虚弱、脆弱撒不上（本移植自己的两条管线 `StatusStacks` / `StatusImmunity`） | `snecko_skull` `ginger` `turnip` |
| **条件修饰器**（`PassiveModifiers.Condition` 布尔表达式）/ **同侧改写**（`OverrideScope = Self`） | `red_skull`（HP ≤ 50% 时 +3 力量）`odd_mushroom`（你有易伤时只受 25%） |
| **战斗类型**（`KindMask`，§269） | `preserved_insect` `pantograph` `slavers_collar` `sling_of_courage` |
| **奖励屏**（§269） | `question_card` `busted_crown` `prayer_wheel` `white_beast_statue` `black_star` |
| **加牌那一刻**（`push_card`，§270） | `omamori` `darkstone_periapt` 三个蛋 `ceramic_fish` |
| **金币 / 商店价**（`adjust_gold` / `shop_price`，§270–§273） | `bloody_idol` `ectoplasm` `maw_bank` `smiling_mask` `membership_card` `the_courier` |
| **进房间**（`begin_node`，§271） | `meal_ticket` `ssserpent_head` `ancient_tea_set` |
| **药水**（§271） | `sozu` `toy_ornithopter` |
| **`?` 房分流**（§272） | `tiny_chest` `juzu_bracelet` |
| **拾取那一刻**（`push_relic`，§274） | `old_coin` `lees_waffle` `war_paint` `whetstone` `astrolabe` `pandoras_box` `empty_cage` |
| 篝火六选项（§259） | `girya` `peace_pipe` `shovel` `dream_catcher` `coffee_dripper` `fusion_hammer` `mark_of_the_bloom` |

**内容门要求"内容里的每件遗物内核都实现"**，所以缺的那 41 件不会半吊子地出现在池子里
（`audit_relic_gap.py` 的 `IMPLEMENTED: … 内核不认识` 必须为 0）。

**§292 之后又做了 37 件**（§292–§305 逐节清单见 `port-plan.md` 对应小节）。剩下的 41 件按
"缺哪块载体"分档：

| 档 | 件数 | 缺什么 | 例子 |
|---|---|---|---|
| 别的角色的语言 | ~18 | 球 / 姿态 / 毒 / 弃牌事实 | `frozen_core` `nuclear_battery` `teardrop_locket` `emotion_chip` `tingsha` |
| 拾取时绑牌 | 3 | "选一张**攻击/技能/能力**牌绑进遗物" | `bottled_flame` / `bottled_lightning` / `bottled_tornado` |
| 静默的 | ~5 | 有钩子、缺一条判断 | `golden_eye`（`Scry`）`tough_bandages`（`CardDiscarded`）`ninja_scroll`（手上全是攻击） |
| 明确不做 | 15 | 无尽模式 / 无意义 | `necronomicon` + 13 件 `Blight` + 2 件 `circlet` |

### D.3 遭遇：三幕的池子（§275 / §287 / §306 / §311 核对）

当前事实（`sts.roguedeck.json` 的 `EncounterTables`，数字直接读出来）：

| 幕 | 普通池 | 精英池 | Boss 池 |
|---|---|---|---|
| 1 | **17** | 3（`three_sentries` / `gremlin_nob` / `lagavulin`） | 3（Slime Boss / Guardian / Hexaghost） |
| 2 | **13**（wiki 13/13，§311–§314） | 3（`gremlin_leader` / `book_of_stabbing` / `slavers`） | 3（Champ / Automaton / Collector） |
| 3 | **10**（wiki 10/10，§316–§317） | 3（`giant_head` / `nemesis` / `reptomancer`） | 3（Time Eater / Awakened One / Donu & Deca） |

另外两处专用池：`EliteEvent`（3 条，`Dead Adventurer` 的伏击）与 `ColosseumSlavers` /
`ColosseumChampions`（各 1 条，`The Colosseum` 的两场）。

### D.3.1 Act 2：wiki 的 13 条，**13 条齐了**（§311–§314）

| wiki（`The_City`） | 池 | 权重 | 状态 |
|---|---|---|---|
| Spheric Guardian | Easy | 2 | ✅ §311（新怪物） |
| Chosen | Easy | 2 | ✅ |
| Shelled Parasite | Easy | 2 | ✅ |
| 3 Byrds | Easy | 2 | ✅ §311（顺手修了 `enc_byrds` 只有 1 只的 bug） |
| 2 Thieves | Easy | 2 | ✅ §314（`mugger` + 1 Looter 在左、1 Mugger 在右） |
| Chosen and Byrds | Hard | 2 | ✅ §311（1 Chosen + **1** Byrd） |
| Cultist and Chosen | Hard | 3 | ✅ §311 |
| Sentry and Spheric Guardian | Hard | 2 | ✅ §315（`(monster, tier)` 的 HP 建模） |
| Snake Plant | Hard | 6 | ✅ §312（`standard.malleable` + 新怪物） |
| Snecko | Hard | 4 | ✅ |
| Centurion and Mystic | Hard | 6 | ✅ §313（`sel.alliesWithDefinition` + `intent.allyMissingHealth`） |
| 3 Cultists | Hard | 3 | ✅ §311 |
| Shelled Parasite and Fungi | Hard | 3 | ✅ §311 |

**13 条全都在池子里了。** 曾经的两次误判都留在这里当记号：

1. `mugger` 被记成"wiki 上只有一张表，照 Looter 写等于发明规则" —— **错**：`Thieves` 页原文
   就是 *"Mugger has the same pattern as Looter."*（§314）。**把"我没找到出处"写成"没有出处"，
   会让一条本来很便宜的内容永远排不上队。**
2. `Sentry and Spheric Guardian` 被记成"要等跨档位建模" —— 那一条是真的（§315），
   但**卡住的是判据模型，不是内容**：`MaxHealthAsc` 的档位原先按**池子**推（精英 A8 / 普通 A7），
   而 Sentry 同一只怪跨两个池子。改法是"档位按**怪物自己**钉"。

### D.3.1b Mugger = Looter 的规则表 + Act 2 的数字（§314）

| 项 | Looter | Mugger |
|---|---|---|
| HP | 44-48（A7 46-50） | 48-52（A7 50-54） |
| Mug | 10（A2 11） | 10（A2 11） |
| Lunge | 12（A2 14） | 16（A2 18） |
| Smoke Bomb | 6 Block | 11 Block（A17 17） |
| Thievery | 15（A17 20） | 15（A17 20） |
| Escape | 带钱跑 | 同 |

顺手补上两个贼的 **Thievery A17 = 20**：它不是新规则，只是 `stolen_gold += X` 的第二个阈值
（wiki 两处表都写 `15 (20 17)`）。

### D.3.1c `MaxHealthAsc` 的档位按**怪物**钉，不按池子（§315）

判据原先这样推档位：精英池 ⇒ A8、Boss 池 ⇒ A9、其余 ⇒ A7。多数怪物确实如此 —— 但
**Sentry** 是 Act 1 的精英（wiki：38-42，**A8** 起 39-45）**同时**是 Act 2 的普通敌人：
同一只怪、同一张 wiki 表。按池子推，同一条记录会被要求**同时**是 A7 与 A8，两条不可能同时
成立 —— 这就是 `Sentry and Spheric Guardian` 一直做不了的真实原因（**不是内容没写**）。

改法：档位来自 wiki 那张表，用 `INV_ASC_HP_LEVEL` 显式写出"Sentry 是 A8"，
其余怪物仍按池子推（存量 100 多条记录一个字都不用改）。于是同一条 `{A8, 39}` 在精英池与
普通池的**两处记录里都是正确答案**；A7 时没有可用的行 ⇒ 血量仍是 38（内核取"≤ ascension 的
最大阈值"，`+10%` 回退在跑层是 0）。

判据 `the_sentry_keeps_one_hp_table_across_two_tiers`：两处记录的 `MaxHealthAsc` **一字不差**，
且 A7 时 38、A8 时 39（在**普通**遭遇里也一样）。负控 2/2 红：把 `INV_ASC_HP_LEVEL` 清空
⇒ 清单判据红；把 Act 2 那条记录写成 `{A7, 39}` ⇒ A7 的断言红。

### D.3.2 Malleable（§312）

`Malleable X`（wiki 两处：`Malleable` 页与 `Snake Plant` 页）= "受到**攻击伤害**时获得 X 块，
X 随着触发**+1**，每回合开始**重置**"。它**可以纯内容实现**，因为零件都已有：

| 需要 | 已有的东西 |
|---|---|
| 只在挨攻击时触发 | `DamageTaken` 触发器 + `damage.isAttack`（Flying / Plated Armor 在用） |
| 只有**掉血**才算 | `eventAmount > 0`（与 Plated Armor 同一口径） |
| "X 每次 +1" | 每战斗员计数器 `malleable_bonus`（Looter 的 `stolen_gold` 同一种机制） |
| 每回合重置 | `TurnStarted` 触发器把计数器置 0 |
| 给块 | `node.gainBlock` + `add(combatantStatusStacks, combatantCounter)` |

判据 `malleable_grows_by_one_per_hit_and_resets_when_the_turn_starts` 四侧：给 3/4/5、回合
开始后又给 3、毒（`DamageKind::Dot`）只吃块不给块。**负控两条**（计数器不递增 / 去掉回合清零）
都红 —— 只测"会长"会放过"不清零"的实现，反之亦然。

⚠️ **已知偏差**：wiki 的 A17 "第一次 Spores 之后改成固定 Chomp/Chomp/Spores 序列"**没做**。
本移植的 A17 在其他怪物上一律只做到"禁令"那一层（§187–§192），这条也是同一类。

**⛔ `Sentry and Spheric Guardian` 是另一个问题**：判据 `check_ascension_health` 按**池子的
档位**钉一条 `MaxHealthAsc`（精英 A8 / 普通 A7），而一只怪物只允许**一条**。Sentry 的 wiki
数字是"38-42，**A8** 起 39-45"，它同时出现在 Act 1 的**精英**池与 Act 2 的**普通**池 —— 两条
要求不可能同时成立。要做这一条，先得让"同一只怪物跨档位"被建模（按 (monster, tier) 钉 HP）。

> ⚠️ **与 wiki 的已知偏差**：wiki 是 Easy（前两场）/ Hard（其余）两段式；我们每幕只有一个
> **带权重**的单池（`EncounterTables.Weak2` 的 `Weight` 已经是 wiki 的数字 ×5）。所以
> "前两场一定简单"这条规则没有 —— 与 Act 1 是同一条偏差。

### D.3.3 Centurion + Mystic 带来的三块新零件（§313）

| 零件 | 形状 | 为什么不能复用旧的 |
|---|---|---|
| `sel.alliesWithDefinition` | 叶子 `AllAlliesOfSource` + 一层 `DefinitionFilter` | `Protect` 要给 **Mystic**（按**定义**）。`sel.lowestHealthAlly` 在 Centurion 掉到 10 血时会返回 Centurion —— 那是另一个行为，负控就是把它换上去，判据当场红 |
| `intent.allyMissingHealth` | `{Op, Value}`，数**自己阵营**里缺 ≥ Value 血的人 | `intent.healthPercent` 只看出手者自己；Mystic 是后排奶妈，"自己缺 16 血"几乎是另一条规则 |
| `combatantCount`（表达式） | `{Selector, AliveOnly}` | `Protect` 的"独自时自保"要在**动作程序**里数活着的友军。`intent.enemyAliveCount` 只活在**意图规则**的条件求值器里 —— 写进程序会 `Expr(UnsupportedKind)`（实测撞过） |

⚠️ 一条**踩过两次**的坑：`intent.not` 的内层必须是 `intent.allOf`，不能写表达式的 `and`
（那是**表达式**的布尔与，条件求值器不认识 ⇒ `UnknownConditionKind`）。第一次改的时候只在
`Monsters` 里改、忘了 `Encounters` 里那份**敌人记录副本**还在用旧规则，于是"改完还是红"。

### D.3.5 Act 3：wiki 的 10 条，**10 条齐了**（§316–§317）

| wiki（`The_Beyond`） | 池 | 权重 | 状态 |
|---|---|---|---|
| 3 Darklings | Easy | 2 | ✅ §316（**顺带修了只有 2 只的 bug**） |
| Orb Walker | Easy | 2 | ✅ |
| 3 Shapes | Easy | 2 | ✅ §316（`Repulsor` / `Exploder` 两个新怪） |
| 4 Shapes | Hard | 1 | ✅ §316 |
| The Maw | Hard | 1 | ✅ |
| Spheric Guardian + 2 Shapes | Hard | 1 | ✅ §316 |
| 3 Darklings | Hard | 1 | ✅ §316（克隆一条 `enc_darklings_hard`：内核要求"一条遭遇只属于一个池"） |
| Spire Growth | Hard | 1 | ✅ |
| Jaw Worm Horde | Hard | 1 | ✅ §316（3 只 `jaw_worm`） |
| Transient | Hard | 1 | ✅ §317（`Fading` + 伤害递增；**`Shifting` 没做**，见 §D.6） |

⚠️ **两条已知偏差**（都写进内容的 `AiNote`）：① wiki 的 Shapes 是"2×Repulsor / 2×Exploder /
2×Spiker 的袋子里抽 3（不放回）"，我们的组合槽是**逐槽独立按权重挑** ⇒ 会出现三只同一个；
② 上一版挂在第三幕的 `enc_byrds` 删掉了 —— wiki 的第三幕回归名单里没有 Byrd（它是第二幕的），
而第二幕已经有 `enc_city_byrds`。

### D.6 **负的力量**：`Shifting` 做不了的那一条（§317）

`Transient` 的 `Shifting`（wiki：*"Upon losing HP, loses that much Strength until the end of the
turn."*）**没做**，而这不是"懒" —— 是今天的载体里**负层数不可表达**：

| 想用的原子 | 为什么不行 |
|---|---|
| `node.applyStatus(strength, -N)` | 负层数被拒（实测 `Exec(Modifier)`）——参考只让"施加"是正的 |
| `node.modifyStatusStacks(strength, -N)` | 在 `0` 处**夹断**，而且目标**没有这条状态时是 no-op**（参考 `:860-865` 的原样移植） |

所以"受伤时临时失去等量力量"要么给 `applyStatus` 开一个"允许负层数"的口子（会动到一条
120+ 动作都在走的路径，得配一整轮判据），要么加一个专门的原子。两者都超出"补一只怪"的范围，
所以这一轮只记在这里。

⚠️ 顺带记一笔：同一个缺口让 **`dark_shackles`（-9 力量）在"目标当前力量 ≤ 9"时也退化成
"减到 0 为止"**（wiki 是会到负数的）。它在 §219 落地时用的是 `modifyStatusStacks`，
所以同样是"夹断"而不是"负数"。

### D.4 两个机制缺口：**都已关闭**（§277 提，§278–§281 关）

| 缺口 | 状态 |
|---|---|
| 真实事件的**剧情分支**被合并 + 条件选项 | ✅ **已关**：`EVND` 段表（选项数不固定）+ `EV.Entry` + `Requires`/`RequiresAsc`（闭词表，6 数值 kind / 2 存在 kind）+ `relic_lose` / `gold_cost` / `gold_all` / `card:<id>` / `heal_pct` / `heal_full` / 小数百分比（千分）。**事件级条件（"这个事件出不出现"）仍未做**，但它不是"表达不了"，而是"会重掷 `?` 房的每一次抽取" —— 见 `docs/event-gaps.md` §3.1。 |
| 战斗中**每回合重掷**的随机没有值节点 | ✅ **已关**：`expr::randomInt{Min,Max}` + `CombatState::draw_in_range`（唯一入口，`random_step` 推进、`seed` 不动）。★ 当年的担心（"预检也求值会吃掉两次"）经核对是**错的**：`preflight` 只查结构不求值 —— 真正的约束是"求值器只读"，所以取数只能在派发点。§281 有记录。 |

⚠️ **这一节原先叫"两个表达不了"，现在是"两个已关闭"**：留在这里是因为它记录了当年
"内容表达不了"的判断如何被推翻（也包括两条**当时以为是坑、其实是误判**的结论）。


### F.4 Snecko（§282）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| Bite 连招 | "will not use Bite three times in a row" | **§283 已做**：内容多记一格 `prev_move`（`prev_move = last_move`），规则 `prev==Bite && last==Bite ⇒ Tail Whip` | 一致 |
| `Snecko Eye` 遗物 | 开局自挂 Confused + 每回合多抽 2 | **§283 已做**（`standard.snecko_eye` 的 `TurnStarted` 触发器） | 一致 |
| Confused 的"何时挂" | 开局挂一次；`Orange Pellets` 清掉后不再回来 | **开局挂一次**（`snecko_eye_turns` 计数器判第一次 `TurnStarted`） | 一致 —— §283 记的"每回合都挂"是**错记**，真因是 `sel.eventTarget` 在无目标事件里恒空 + 脚本幂等守卫让修正没落进镜像（见 §284） |
| `Snecko Eye` 的多抽 | `TurnStartDraw` 修饰器 | `TurnStarted` 触发器里的 `drawCards 2` | 可观察等价（`max_hand_size` 是 `i32::MAX`，上限不参与） |
| Confused 的清状态语义 | `Orange Pellets` 清掉后，已重掷的牌保留新价 | 天然一致（价格在副本计数器上） | 一致，无专门判据 |

### F.5 事件概率（§285）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| 奖赏/赔付的时机 | 到达结果屏就生效 | **已修**：段的进入效果（`Effects` 挂在 `EVND` 行上） | 一致（§286） |
| `Wing Statue` `[Destroy]` | 只在牌组有"单次 ≥10 伤害的攻击牌"时出现 | **已修**：`Requires: card_damage at_least 10`（从效果程序读） | 一致（§287） |
| `Scrap Ooze` 的遗物 | 50/33/17 稀有度、随机 | 同（`pick_relic`），并排除已持有 | 一致 |
| `Dead Adventurer` | 25%/35% 精英归来（事件中途开战斗） | **已修**：`Fight` + `Encounter` + 战后欠账 | 一致（§286 / §287） |
| `The Joust` 的**出现条件** | 只有 **>50 金币**时才遇到（且没有"不赌"的选项） | **已修**：`MinGold: 51` + 押注项 `Requires: gold at_least 50` | 一致（§291；此前会**卡死**） |

### F.6 事件中途开战斗（§286）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `Dead Adventurer` 战后补偿 | 战斗胜利补发"还没搜到"的奖励，另加 25-35 金币 | **已修**：`fight_gold_bonus` / `fight_no_relic` | 一致（§287） |
| `Dead Adventurer` 的 Lagavulin | 这场伏击**不睡觉**，开局直接 Siphon Soul | **已修**：事件自己的池 `EliteEvent` + `enc_lagavulin_awake` | 一致（§287） |
| `Dead Adventurer` 的出现楼层 | 只出现在第 7 层之后 | **已修**：`MinFloor: 7` | 一致（§288） |
| 奖赏时机（§285 的偏差） | 到达结果屏就生效 | **已修**：段落进入效果（§286） | 一致 |
| 伏击的档位 | 精英 | 精英（同一套 `elite_fight`） | 一致 |

### F.7 事件尾巴（§287）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `Wing Statue` `[Destroy]` 的条件 | 牌组里有单次 ≥10 伤害的牌 | **已做**（`Requires: card_damage at_least 10`，从效果程序读） | 一致 |
| `Wing Statue` 条件的口径 | "printed damage per hit" | 基础伤害（力量/附魔不算） | 一致（与 wiki 的措辞同义） |
| `Dead Adventurer` 战后补偿 | 补发"还没搜到"的奖励，且已搜到的从战斗奖励里去掉 | **已做**（`fight_gold_bonus` / `fight_no_relic`） | 一致 |
| `Dead Adventurer` 的 Lagavulin | 这场伏击**不睡**，第一回合 Siphon Soul | **已做**（`Encounter: "EliteEvent"` + `enc_lagavulin_awake`） | 一致 |
| `Dead Adventurer` 的出现楼层 | 第 7 层之后 | **已修**：`MinFloor: 7`（§288），§291 又把上界与金币门槛补齐 | 一致 |

### F.8 事件战斗与楼层门槛（§288）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `The Colosseum` 第一场 | 打 Blue Slaver + Red Slaver，**没有奖励**，打完继续事件 | **已做**（`After` + "回到事件不发奖励"） | 一致 |
| `The Colosseum` VICTORY | Taskmaster + Gremlin Nob；100 金币、1 稀有、1 罕见、选牌、（有时药水） | **已做**（`fight_gold_set:100` + 两个稀有度词）；药水走精英池概率 | 基本一致 |
| `The Colosseum` 出现位置 | 只有 Act 2，且只有**上半场** | 只在 `Events2`（Act 2）；"上半场"没做 | 缺 `MaxFloor` |
| `Dead Adventurer` 的出现楼层 | 第 7 层之后 | **已做**（`MinFloor: 7`） | 一致 |

### F.9 奖励族与楼层门槛（§289）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| 指名遗物奖励 | `Masked Bandits` 的 `Red Mask` | **机制已做**（`fight_relic:<id>`），内容未接 | 缺内容：三个名册外敌人 + `gold_all` |
| `The Colosseum` 出现位置 | 只有 Act 2 的**上半场** | **已做**（`MaxFloor: 7`） | 一致 |
| 事件战斗的药水 | 独立的一次掉落 | **已做**（`fight_potion_chance`，不移动追踪值） | 一致（口径见 §289.3） |
| `Masked Bandits` 的 `[Pay]` | 失去**全部**金币 | 没有"失去全部金币"原子 | 缺 |

### F.10 事件的两个原子（§290）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `The Nest` `[Smash and Grab]` | 99 金币（A15 50） | **已做** | 一致 |
| `The Nest` `[Stay in Line]` | 得 Ritual Dagger、掉 6 血 | **已做**（`card:<id>` 的第一位用户） | 一致 |
| `Ritual Dagger` 卡面 | 1 费 Special、15 伤害、Fatal 永久 +3（+5）、Exhaust | 内容里早就有；每副本成长 `standard.ritual_dagger_bonus` | 一致 |
| `Masked Bandits` `[Pay]` | 失去**全部**金币 | **原子已做**（`gold_all`），内容未接 | 缺：三个名册外敌人 + 25-35 的区间覆盖 |
| 无色牌的入口 | 事件 / 药水 / 商店无色格 | 事件与无色药水有；商店无色格没有 | 缺 |

### F.26 遗物：清负面状态（§310）

| 项 | wiki（两个独立来源） | 我们 | 性质 |
|---|---|---|---|
| `orange_pellets` | *"Whenever you play a Power, Attack, and Skill in the same turn, **remove all debuffs**"* | **§310 修正**：新节点 `node.removeDebuffs`，按**定义**的极性筛（`status_polarity`），删实例而不是把层数减到 0 | 一致（§310 之前是**内容错误**，不是简化） |

判据：`orange_pellets_removes_every_debuff_and_keeps_the_buffs`（rd-core，真打三张牌）——
四侧：只有两类 ⇒ 不清；三类齐 ⇒ Weak/Frail 清空；**正面状态一条不许动**；第四张牌不重复付。
负控：把"只清 Debuff"改成"清 Buff" ⇒ 判据红（这就是判据里"正面状态"那一侧存在的理由）。

⚠️ 实现里踩过一个坑，记在这里因为它是一个**通用形态**：第一版用
`StatusInstance.polarity` 判极性，结果把力量/敏捷也清了 —— 实例上的极性是
`applyStatus` 那一刻**抄**进去的字段，谁都可能写错（测试助手给每条都写 `Debuff`）。
内核里早就有唯一入口 `status_polarity(definition_id, content)`（内容 `STAT.Polarity` 优先、
目录兜底，Artifact 也用它）。**"字段里有一份现成的值"不等于"那是权威的值"。**

### F.24 遗物：只改视图（§305）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `frozen_eye` | *"When viewing your Draw Pile, the cards are now shown in order"* | **已做**：没有遗物时面板按 id **排序**并说明；有遗物时就是内核顺序 | 一致 |
| 面板显示什么 | 有哪些牌（公开信息），不是顺序（秘密） | 排序视图只显示标题 + 一行说明 | 一致 |
| 是否改状态 | 不改 | 抽牌堆序列逐张不变（判据 + 负控钉住） | 一致 |

### F.23 遗物：开战问一句（§304）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `gambling_chip` | 开战弃**任意张**、抽同样多 | **已做**（`DiscardThenDraw`，`min = 0`） | 一致 |
| `toolbox` | 开战三选一**无色**牌入**手牌** | **已做**（`Offered` + 新变体 `ToHandPrinted`） | 一致 |
| 入手的牌是否免费 | wiki 没有这句 ⇒ **按印刷价** | `ToHandPrinted` 一个字都不写；页面的句子也不说免费 | 一致 |
| 两件同时 | 各自触发一次 | 位掩码，先 chip 后 toolbox（内核一次只许一个问题） | 顺序是写明了的实现选择 |

### F.22 遗物：落区与地图（§302/§303）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `strange_spoon` | 打出即消耗的牌 50% 改为进弃牌堆 | **已做**（发牌落区那一格掷一次骰） | 一致 |
| 边界三行 | `Ethereal` / 被效果逼着消耗 / 不可打牌被 `Havoc` 消耗 ⇒ **不**受影响 | 三者都不经过出牌计划，天然不受影响 | 一致 |
| `wing_boots` | 下一层任意房间，**3 次**，用完即失效 | **已做**（`reachable()` 追加整层 + 收费计数） | 一致 |
| 每幕是否重置 | 两份来源**都没提**重置 | 不重置（3 次是全局次数） | 写明了的解读 |

### F.21 遗物：开局三场（§301）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `neows_lament` | 前 3 场战斗敌人 **1 血** | **已做**（运行层计数 + 开战时覆盖成 1/1） | 一致 |
| 计数口径 | 前 3 场（输掉也算） | 数**开始**过的战斗 | 一致 |
| 覆盖形状 | 绝对 1 血 | 当前血与**上限**都设 1（不走百分比通道） | 一致 |

### F.20 遗物：三个原子（§300）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `nilrys_codex` | 回合末三选一，**洗入**抽牌堆 | **已做**，但进的是抽牌堆**顶** | **偏差**（牌区只有 Top/Bottom） |
| `warped_tongs` | 回合初随机升级手牌一张 | **已做**（`upgradeCards.Random`） | 一致 |
| `mummified_hand` | 打 Power ⇒ 手牌随机一张变 0 费 | **已做**（新节点 `setCardCostOverride`） | 一致（0 费由出牌消费，见 §161.4） |

### F.19 遗物：C 类纯内容程序（§299）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `enchiridion` | 开战加一张随机 Power 牌、这次免费 | **已做**（纯内容） | 一致 |
| `orange_pellets` | 一回合内 Power+Attack+Skill ⇒ **清除所有 Debuff** | **§310 修正**（新节点 `node.removeDebuffs`；三个计数器仍在） | 曾是**偏差**（给 +3 力量/+3 敏捷 —— 那不是同一条规则）。⚠️ 旧版本这一行的"wiki"列写的就是我们自己的行为，所以"对账"永远通过 |
| `dead_branch` | 每消耗一张牌 ⇒ 手牌加一张随机牌 | **已做**（新增通配 tag `*`） | **偏差**：池子是"任意基础牌"（含无色），wiki 是"你的职业牌池" |
| `nilrys_codex` | 回合末三选一塞进抽牌堆 | **§300 已做**（`offerRandomCards.Then`；进**顶**不是洗入） | 已修 |
| `warped_tongs` | 回合初随机升级手牌一张 | **§300 已做**（`upgradeCards.Random`） | 已修 |
| `mummified_hand` | 打 Power ⇒ 手牌一张变 0 费 | **§300 已做**（新节点 `setCardCostOverride`） | 已修 |

> ⚠️ **这张表的"wiki"列必须来自 wiki，不能来自我们的代码。** §310 就是一次教训：
> `orange_pellets` 那一行两列都写"+3 力量/敏捷"，于是代码错、文档跟着错、对账一路绿。
> 判据的写法也跟着改了 —— 见 §F.26。

### F.18 遗物：治疗与放行（§298）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `magic_flower` | 战斗中治疗 +50% | **已做**（`heal_for` 一个乘法，×150 向下取整） | 一致 |
| `medical_kit` | `unplayable` 的 Status 牌可打，打掉即消耗 | **已做**（校验器放行 + 落区强制 `ExhaustPile`） | 一致 |
| `blue_candle` | `unplayable` 的 Curse 牌可打，失去 1 生命、打掉即消耗 | **已做**（放行在内核，掉血是**内容**触发器） | 一致 |
| 放行后的落区 | "Exhaust it" | 强制 `ExhaustPile`（少了它玩家能反复打同一张） | 一致 |

### F.17 遗物：规则住在三处（§297）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `strike_dummy` | 带 "Strike" 的牌 +3 伤害 | **已做**（内容 `DamageDealt` + 来源卡标签门） | 一致 |
| `velvet_choker` | 每回合 +1 能量；最多 6 张 | **已做**（`card_limit_validator`，拒绝码 19） | 一致 |
| `runic_dome` | 每回合 +1 能量；看不见意图 | **已做**（观测里就没有意图） | 一致 |
| 出牌上限的数字 | 6 | 内核常量（与 `THE_BOOT` 同族） | 一致 |

### F.16 遗物：X 费牌（§296）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `chemical_x` | X 费牌的效果 +2 | **已做**（内核给 `x_cost` 加 2，内容那条状态是开关） | 一致 |
| X 的语义 | 你为这张牌付了多少 | 同一个数（**加成只加在效果里的 X**，不动付的钱） | 一致 |
| 每副本价格对 X 费牌 | 无意义（全部能量） | **仍看不见**（§161.5 的已知偏差） | 偏差（已记录） |

### F.15 遗物：打穿格挡（§295）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `hand_drill` | 打穿敌人的格挡 ⇒ 2 层易伤 | **已做**（`BlockBroken` + 内容 `applyStatus`） | 一致 |
| "打破"的口径 | 整池格挡被这次伤害打空 | 三条同时成立（原本有 / 打空 / 不是自己） | 一致 |
| 易伤落在谁身上 | 被打破格挡的那一方 | `sel.eventTarget`（判据反向断言英雄 0 层） | 一致 |

### F.14 遗物：洗牌触发器（§294）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `the_abacus` | 每次洗牌 +6 格挡 | **已做**（`DeckShuffled` + 内容 `gainBlock`） | 一致 |
| `sundial` | 每 3 次洗牌 +2 能量 | **已做**（计数器在内容里） | 一致 |
| 空弃牌堆算不算"洗过" | 不算 | **不算**（早退 ⇒ 不发事件） | 一致 |

### F.13 遗物：加牌问句（§293）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `orrery` | 拾取时挑 5 张加入牌组（5 张独立奖励屏） | **已做**（一个面板"还要选 N 张"，可跳过） | 一致（界面更紧） |
| `tiny_house` | +50 金、上限 +5、1 瓶药水、1 张牌 | **已做** | 一致 |
| `singing_bowl` | 加牌时可以不拿牌、改 +2 上限 | **已做**（战斗奖励屏 + 两个拾取问句） | 一致 |
| `singing_bowl` 在**事件**给牌的场合 | 同样可换 | **没挂**（事件给牌不走"加牌问句"） | **偏差**（已知不对称） |

### F.12 遗物：Wave 1 与 `Shop` 档（§292）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `Shop` 稀有度的遗物 | 只在商人处卖（14 件） | **已修**：`Rarity::Shop` + 货架抽样 | 一致（§292.1；此前**永远拿不到**） |
| `cultist_headpiece` / `spirit_poop` | 一句 flavor | **已做**：`RelicEffect::Nothing` | 一致 |
| `face_of_cleric` / `matryoshka` / `nloths_hungry_face` / `cursed_key` / `calling_bell` / `cauldron` / `dollys_mirror` / `nloths_gift` / `sacred_bark` | 见 §292.2 | **已做**（各带两侧判据） | 一致 |
| `cauldron` 装不下的 2 瓶 | 一瓶一瓶问"要不要丢掉旧的" | **丢在欠账上**（不静默消失，进 run hash） | **偏差**（缺丢弃问句） |
| `matryoshka` 的第二件 | 分别进奖励屏 | 直接进腰带 | **偏差**（与 `black_star` 同一条：奖励屏只有一个遗物槽） |

### F.11 F.5 的审计与"付不起就别画"（§291）

| 项 | wiki | 我们 | 性质 |
|---|---|---|---|
| `The Joust` 的出现条件 | 只有 >50 金币时遇到 | **已修**（`MinGold: 51`） | 一致 |
| `The Joust` 押注项的可用性 | 付不起就不该有这条路 | **已修**（`Requires: gold at_least 50` + 门 G1 强制） | 一致 |
| 某段**全部**选项都带条件 | （StS 用"事件根本不会出现"来避免） | 不可静态验证；今天内容里没有这种段（审计脚本 B 段） | 结构性假设 |

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

> ⚠️ 这里曾经还有一行 `maw.*`（3 招）"自家设计 / wiki 无此页（404）" —— **§212 起已经不成立**：
> `native/wiki_asc/the_maw.txt` 抓到了页面，四招（Roar / Slam / Nom Nom / Drool）与转移表都按 wiki
> 重写了。2026-11-05 的第六轮审阅又把 `Nom Nom` 的**时间变量**修了（§216：`turnNumber` → `roundNumber`，
> 前者是"一轮内的行动者序号"、单怪场景恒为 2 ⇒ 永远 1 击）。

### G.2 语义放宽：只放大"谁"的伤害（不是数值偏差）

| 实体 | 我们 | wiki | 为什么留着 |
|---|---|---|---|
> **`second_wind` / `fiend_fire` 的这一行已经删掉了（§226）**：它不是"表达不了"，而是"没人告诉内容
> 哪一张是自己"。内核现在在 `forEachCardInZone` 的每一趟里把"这一张是不是正在结算的那张"填进
> `event_flags`（`event.bool: card.isResolving`，只读、不改快照），内容用 `not(...)` 把它排除 ⇒
> Second Wind 给 5（wiki 5）、Fiend Fire 打 14（wiki 14）。`archive_the_evidence` 那条参考契约
> 一个字节都没动 —— 它不看这个位。

| ~~`doubt`~~ | **§326 已修**：回合末顺序改成 ③④①②（TurnEnded 触发/时长衰减 → 牌在手生命周期 → 弃手牌），所以 Doubt 给的 Weak 落在衰减**之后**、留到下一回合；`Burn`/`Regret` 仍在弃手牌之前 | — | 我们的 `standard.weak` 衰减是一条 `TurnEnded` **触发器**（第 ③ 步），而卡牌生命周期节目在第 ① 步 —— 同一次回合末里刚上的 Weak 当场被扣。参考把衰减放在 `decrease_timed_statuses`，与卡程序的关系不同。要修得动回合末的处理器顺序（影响 Burn 等所有生命周期节目），留作单独一节 |
| `standard.slow` | 放大**任何直接伤害**（`RestrictDamageKind: Direct`） | 只放大"**打出攻击牌**造成的伤害" | 要精确到卡牌标签需要 `RestrictSourceCardTag` 进镜像格式（`status_bind` 目前对非空值**响亮拒绝**），留作格式升级。基线（本回合牌数、每回合归零、不复合）已与 wiki 一致（§216） |

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

`Module:Ascension`（wiki）列了 20 条，全部**累计**。**14 条**运行层规则各自在阈值两侧各有一条测试
（`gap_check.py` 的 "consulted somewhere: 14"），**另 6 条**（A2/A3/A4/A17/18/19）靠内容的
`EACT.ProgramAsc` 变体实现 —— 所以机制层面是 **20/20**。§328 起，"wiki 写了 `{{Asc|N|` 而内容
缺档"的动作数是 **0**（闸门 `[7b]` 每次验收重比）；`without a variant: 59` 是 wiki 本来就没写升档的
动作，不是缺口。

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
| 17 | 普通敌人换招式表 | **有**（同一批变体里含 Slaver 的 Weak/Vulnerable 层数、Frail、`Fat Gremlin` 的 A17 附 1 Frail） | — |
| 18 | 精英换招式表 | **有**（Book of Stabbing 的 `N = turn + 1`、Reptomancer 召 2 只、Nemesis 5 张 Burn、Taskmaster 3 Wound + 1 力量） | — |
| 19 | Boss 换招式表 | **有**（Champ 的 Gloat→Defensive Stance、Collector 的 Buff 5 力量、Time Eater 的 32 Block / 2 Slimed / 1 Frail） | — |
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
3. ~~**`Slow`（Giant Head）**~~ ✅ **已完成**（§198：`ScalePercentPerStack` 运算 + `CardPlayed` 推动）。
   **"下回合多能量"仍缺**：`TurnStartDraw` 这条管线能表达"下回合多抽"（`Draw Reduction` 的反向），
   但**能量**没有对应管线（`turn_start_refill` 只读配置）—— 那是所有 Energized 类卡与药水的前提。
4. ~~**"行动者可以自毁"**（内核）~~ ✅ **已完成**（§200：`vacated_seat` 交接 + `dagger.explode` 自毁）。
   ~~**Looter 的偷钱逃走**~~ ✅ **已完成**（§201：`node.carryAwayStolenGold` +
   `CombatState::gold_carried_away` + `fight_end` 结算）。**工作包 B 到这里全部完成。**
5. ~~**篝火选项**~~ ✅ **已完成**（§259：六个选项全通 + `Dream Catcher`）。**`Recall` 与红钥匙**
   本身也做了，缺的是第四幕（第 7 条）。
6. **卡池规模**：红卡与无色都**齐了**（`audit_card_gap.py`：Red 75/75、Colorless 70/70），
   剩下的 **73 张全是观者**（§A.1），它们成堆挂在姿态 / Mantra / Scry / Retain / `Alpha`→`Omega` 上，
   所以下一批要按**基建**聚类做。**无色货架**（商店里那一排）仍然没有 —— 那是内核的小改动
   （`stock_shop` 加一排），内容侧已经就绪。
7. **第四幕与钥匙**（运行层）—— 明确的范围外，等前面清完再说；`Recall` 挂在它上面。

---

## 4. 这份文档怎么保持不烂

* 数字：`python -X utf8 native/gap_check.py`（内容/规则）与
  `python -X utf8 native/sts_content_check.py`（内容自洽）。
* **新增的两道闸门**（都在 `sts_content_check.py` 里，验收时自动跑）：
  * `[7b]`（§328）：读 `native/wiki_asc/*.txt` 的意图行，要求内容的 `ProgramAsc` **覆盖** wiki 的
    `{{Asc|N|` —— "别的机制表达"的那几条走 `native/asc_other_means.py`（**只此一份**，审计脚本也读它）；
  * `[7g]`（§330）：**段内 id 不许重复**。它是被一条真 bug 逼出来的：`Relics` 里
    `mutagenic_strength` 重复了一行，22 道闸门一条都没红（`SEC_IDX` 照样索引得到、audit 用 `set`
    自动吃掉重复），只有把 `gap_check` 的 153 与 audit 的 152 放在一起读才看得出来。
* **工具自身也会说谎**（§330）：`audit_asc_gap.py` 的 `ROW` 正则非贪婪，遇到 `{{Asc|2|4}}` 的 `}}`
  就截断，于是每行只读到第一个档位 —— 它报了 18 条假 MISMATCH / 3 条假 MISSING。修好之后
  MISSING/MISMATCH 都是 0。**改工具时先问"它凭什么知道"**，别拿它的输出当证据。
* wiki 侧引用（`slaythespire.wiki.gg`，最近核对 **2026-11-03**）：`Potions_List`、`Module:Potions/data`、
  `Colorless_Cards`、`Blind` / `Bandage_Up` / `Dark_Shackles` 单卡页、`Module:Ascension`、
  `Keywords`、`Rest Sites`、`Relics`、`Acts`、`Lagavulin` / `Book_of_Stabbing` / `Nemesis` /
  `Reptomancer` / `Slavers` / `Taskmaster`。**页面会变**，所以只引页面名 + 核对日期。
* 改了内容或内核规则之后，**跑一遍脚本**，把正文里对不上的句子改掉 —— 或者干脆改成"见脚本"。
  一句"我们有 26/33 瓶药水"如果没人重算，它会在下一次内容变更后变成谎话，而**没有任何闸门会红**。
* **逐实体的账在 `docs/coverage-matrix.md`（生成物，闸门 13）**：它把"每个实体被验证到哪一步"写成 360 行 —— `Implemented` / `RuntimeTested`（`test:` 还是只有 `harness:`）/ `WikiVerified`（`wiki:<dump>` 还是只有 `spec:<TABLE>`）/ `Deviation` / `Evidence`。本文档 §G、§H 的两张表**被它直接解析**（改了这里而不改内容，那条闸门会点名是哪个 id 漂了）。`WikiVerified = —` 的那几类就是"还没回到 wiki 页看过"的清单。
* ⚠️ **闸门看不见 wiki**：本轮重核抓到 `blind` 的稀有度与 Exhaust 都写错了，而当时的 20 道闸门全绿
  （内容门对照的是 `docs/spec/` 的清单，清单本身也是人抄的）。⇒ 新内容落地时，**至少把稀有度
  与"是否 Exhaust"这两列回到单卡页看一眼**，它们是最容易"顺手抄邻居"的两格。

## H. Boss 机制：**当前**与 wiki 的剩余差异（§194 → §195.9）

数字全部来自 `native/wiki_asc/<boss>.txt`（`action=raw`）。这一张表**只写现在的差异** ——
§328–§330 逐条对过之后，"剩余差异"那一列基本是空的（这就是它该有的样子）。

历史降级（"Guardian 只按 HP 切形态""Awakened One 没有死亡拦截 / 没有 Cultist""Bronze Orb 没有
Stasis""小兵预置""Collector 死光后不再召唤""Champ 二阶段每回合 Execute"）都在
§195.1–§195.8 与 §329–§330 逐条修掉了，过程见 `port-plan.md` 那几节。

| Boss | 现在的行为 | 与 wiki 的**剩余**差异 |
|---|---|---|
| The Guardian | 进攻 4 循环；Sharp Hide（`CardPlayed` + `hasTag.attack`）；**Mode Shift = 累计受伤**（`Counters` 种 30/35/40，`eventAmount` 扣减，切防御态 +10）；防御态 Roll → Twin Slam → Whirlwind | 无（switch 落在"下一次选意图"，敌人只在自己回合动作） |
| Hexaghost | Activate / Divider 两个开场规则 + 7 招轮转；Divider = `(HP/12 + 1) × 6`；**Inferno 升级所有已有 Burn**（`node.upgradeCards`） | Sear 后续塞的 Burn **不**自动升级（wiki："for the rest of combat"）；Divider 读结算时 HP |
| The Champ | 420 HP；**45/25/15/15 带权抽签** + 任何一招不能连续两次 + 每 4 回合 Taunt；≤50% 后 Anger（清三种 Debuff + 力量）→ Execute；二阶段按 **随机 / 随机 / Execute** 循环（`champ_exec` 计数器）；A19 把 Gloat 换成 Defensive Stance 且连用则回退 | **Taunt 在二阶段仍每 4 回合触发**（wiki 的 "Random Move (Same chances as Phase One)" 措辞含糊，我们按"包含 Taunt"实现） |
| Bronze Automaton | 300 HP + Artifact 3；第 1 回合 **真召唤 2 Orb**（`Spawn: false`）；6 招循环；A19 用 Boost 顶替 Stunned；Orb 的 `Stasis` 按"最高稀有度"抓牌 | 无 |
| The Collector | 282 HP；第 1 回合 **真召唤**（**up to 2**：两只都在时不加、只剩一只时补一只）；第 4 回合 Mega Debuff；两条分支的权重 **25/45/30**（0-1 只）与 **70/30**（两只都在）；不能连 Buff、不能三次 Fireball | 无（§329 收口） |
| Time Eater | 456 HP；45/35/20 带权 + 三次/两次的排除规则；≤50% 的 Haste **回 50% 血 + 清所有 Debuff**（一次性，A19 另加 32 Block）；A19 的 Head Slam 另塞 2 张 Slimed、Ripple 另加 1 Frail | 无（§329 收口） |
| Awakened One | 300 HP；`DeathPrevention` 真复活 → **Rebirth（回满血 + 清所有 Debuff + 失 Curiosity）**；一阶段 75/25 + Slash 不能三次；二阶段 Dark Echo 一次后 50/50 + Tackle/Sludge 不能三次；**带两只 Cultist，主人倒下时逃跑**；Regenerate/Curiosity 的 A19 层数已钉（15/2） | ⚠️ `Curiosity` 的触发器（`card.hasTag.power`）在**本内容里永不触发** —— 因为卡池 0 张 `power` 牌（§A.1 的观者缺口） |
| Donu & Deca | 一对（250 HP 各 + Artifact 2，**A19 变 3**）；Donu 交替 Circle / Beam；Deca 交替 Beam / Square | 无 |

**两条全局的**（都不在 Boss 里）：

1. **A9 的 `AscHP` 不精确** —— 跑层对 `MaxHealth` 施加的是**百分比**（§159 的 A7/A8/A9 规则，
   420 → 525），不是 wiki 的定值。
2. **抽签是 `(seed, round, slot)` 的派生值** —— 不是随机流，两次抽签之间没有顺序关系（§195.3）。

**已知测试缺口**（如实报告，不是遗漏）：`selectCards` 的 `Count > found` 边界在**状态上不可观测**
（同区搬运是 no-op），能看见它的只有 `ExecStats::effects`，而计数器只对"`Count > 1` 且候选更少"的
**程序**可见 —— 本内容唯一这样的调用在触发器里，宿主不回收它的 stats。修法：给 `Host` 也记一份
effect 账（§195.9 记录，未做）。
