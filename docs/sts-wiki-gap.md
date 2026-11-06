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
| 状态 | 内容里每一条状态要么有内核规则、要么**显式声明为 inert**（`is_declared_inert()`，**18 条**，`gap_check.py` 打印全名）。⚠️ "在 inert 名单上"只说明"内核没有硬编码规则" —— 它的行为在内容的触发器里，**这不等价于"StS 语义全对"**（审阅 §4.2） | §147 / §149 / §158 / §180 / §181 / §195.1–§195.7 |
| 三幕骨架 | 地图 15 行 × 7 列 + Boss 行、每幕独立的遭遇/事件池、幕间切换 | §130 / §131 / §133 / §137 |
| 战斗流程 | 召唤随从（敌人槽上限 6）、Boss 分裂、半血换招、**销毁战斗员**（§178） | §121 / §124 / §138–§140 / §178 |
| 运行层 | 商店（卡/遗物/药水/删卡 + 价格）、篝火（休息/打铁）、宝箱、事件、奖励屏、**脱战**（§179） | §143 / §161.8 / §179 |
| 药水 | **全部 33 瓶**（Ironclad 口径）都能喝，效果词表见 `gap_check.py` | §152 / §158 / §179–§185 |
| 卡牌（**数量**） | **117 行 = 61 张基础 + 56 条升级行**；其中 Red（铁甲战士）**40 / 75**，Colorless **14 / 70**（含诅咒与衍生牌）。**逐张盘点见 §A.1** | §218–§233 / `audit_card_gap.py` |
| Ascension | **20 / 20 条都有机制**，但分成两半：**14 条是 `rd-run` 的规则常量**（A1 A5–A16 A20，`gap_check.py` 打印），**6 条走内容数据**（A2/A3/A4 与 A17/18/19 的 `EACT.ProgramAsc`）。数值侧：**89 条变体 / 80 个动作** + 事件列表的 A15 变体。逐条见 §E | §159 / §187–§192、`gap_check.py` |
| 存档 / 回放 | 单行文本 + CRC（`RDA1`）；动作序列 + 每步哈希（`RDR1`）；内容指纹 | §161.9 / §163 / §164 / §166 |
| 前端 | 战斗 + 运行层 + 存档 + 回放；真浏览器闸门（真指针点击 + 像素判据 + 切片五场景） | §165 / §168 / §185 |
| 诊断 | 一步之内的有序事件（beats）、**拒绝码**与**宿主失败原文**导出（§177） | `env-abi.md` §12 |


### 1.1 数字只有一个来源（§195.9）

下面这一段是 `python -X utf8 native/gap_check.py` 的 **pastable 区块**原样贴进来 —— 文档里**不要**
再手写这些数字（README 里那份曾经写着"28 张基础 + 17 张升级 / 9 事件"，实际是 **27 + 18 / 12**，
而且没有任何闸门会红）。

```
monsters 47 / encounters 34 / cards 117 (base 61 + plus 56) / statuses 46 /
enemy actions 130 / relics 15 / potions 33 / events 14 (6+4+4) / start deck 10
ascension variants 89 over 80 actions
image full   content.sts.rdcf             92644 B
image core   content.sts.core.rdcf        76448 B
```

> ⚠️ **单位必须写清**（审阅 §8 第 5 条）：`117` 是**卡行**（61 基础 + 56 升级行），不是 117 张不同的牌
> —— 而且其中包含状态/诅咒牌与多档升级行（`searing_blow+`…`++++++`）；
> `89 / 80` 是**变体 / 动作**；`14` 是三个幕的事件池之和（`6+4+4`），不是单池大小。
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

当前结果（`audit_card_gap.py --offline` 的输出，**数字照抄脚本**，别手写）：

| 桶（颜色 / 类型 / 稀有度） | wiki | 有 | 缺 |
|---|---:|---:|---:|
| Red · Attack · Basic | 2 | 2 | 0 |
| Red · Attack · Common | 14 | 12 | 2 |
| Red · Attack · Uncommon | 11 | 9 | 2 |
| Red · Attack · Rare | 5 | 4 | 1 |
| Red · Skill · Basic | 1 | 1 | 0 |
| Red · Skill · Common | 6 | 5 | 1 |
| Red · Skill · Uncommon | 17 | 13 | 4 |
| Red · Skill · Rare | 5 | 2 | 3 |
| Red · Power · Uncommon | 8 | 3 | 5 |
| Red · Power · Rare | 6 | 3 | 3 |
| **Red 小计** | **75** | **68** | **7** |
| Colorless · Attack（Uncommon / Rare / Special） | 11 | 1 | 10 |
| Colorless · Skill（Uncommon / Rare / Special） | 33 | 4 | 29 |
| Colorless · Power（Rare / Special） | 7 | 0 | 7 |
| Colorless · Curse | 14 | 4 | 10 |
| Colorless · Status 牌 | 5 | 5 | 0 |
| **Colorless 小计** | **70** | **14** | **56** |
| **合计（口径内）** | **145** | **82** | **63** |

**§238 之后还剩 7 张红卡**，按"要什么载体"分组（这是下一批的施工单）：

| 需要的载体 | 牌 |
|---|---|
| **触发器接钩子**（`BlockGained` / `CardsDrawn` / 卡被消耗 三个事件名都在词表里，但声明为 `NotHandled`） | `juggernaut` `evolve` `fire_breathing` `dark_embrace` `feel_no_pain` |
| **`ChoiceSource::ExhaustPile`**（现在只有 Hand / DiscardPile / Offered） | `exhume` |
| **动态费用 / 力量倍率 / Fatal / 技能 0 费 + 打出即消耗** | `blood_for_blood` `heavy_blade` `feed` `corruption` |
| **"下一张 Attack 打两次"**（`standard.duplication` 不限牌型） | `double_tap` |
| **"手牌全是攻击才能打"**（`PlayCondition` 目前只是 bool 表达式，读不到整手牌） | `clash` |
| **随机生成/打出手牌** | `havoc` `infernal_blade` |
| **"问完再继续"**（问句是异步的，程序没法在答案之后接着跑） | `burning_pact` |
| **读敌人意图** | `spot_weakness` |

> ⚠️ 注意 `flame_barrier` / `rage` / `evolve` 这类：它们的**状态**（`standard.flame_barrier` /
> `standard.rage`）早就在内容里、触发器和管线都对，缺的只是**那张 Power 卡**本身 —— 也就是说
> 这批红卡里有一半只差内容行。

> ⚠️ **"缺 91 张"不等于"91 张都要写"**：其中 12 张是别的角色的衍生牌（口径外），
> 31 张无色牌需要**无色货架**（商店）作为入口 —— 这两块在 §D 里单列。
> 铁甲战士本体缺的 **35 张**才是"内容工作量"的主干，且多数只差内容行（载体在 §218–§233 已经补齐）。

> ⚠️ 同一张牌在我们的内容里也可能挂在别的颜色下（`malaise` / `nightmare` / `rip_and_tear` /
> `skewer` 是静默猎手牌、`blur` / `buffer` 是故障机器人牌，都在本内容里做过）。脚本把它们列成
> "content-only"，这是**有意的**：口径是"能玩的机制"，不是"只抄一个职业"。

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
| Boss 分裂 | **有**，但目前**只有 Slime Boss**（`destroyCombatant` 到位后，"消失 + 两只顶替"才第一次能正确表达，§178） | 内容（另两只 Boss 各有新东西） |
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
| 遭遇池按幕分 | **有**（`gap_check.py` 打印每幕的数量） | 内容（第二幕的普通池只有 2 个） |
| **精英池** | 每幕 **3 个**：Act1 `three_sentries / gremlin_nob / lagavulin`、Act2 `gremlin_leader / book_of_stabbing / slavers`、Act3 `giant_head / nemesis / reptomancer` | — （wiki 的每幕 3 个齐了） |
| ~~Boss 池~~ | ✅ **每幕三只**（§194）：Slime Boss / Guardian / Hexaghost，Champ / Automaton / Collector，Time Eater / Awakened One / Donu & Deca | — |
| 药水 | **33 / 33**（Ironclad 口径） | — （见 §D.1，全部落地） |
| 遗物 | **15 件**（9 Common / 4 Uncommon / 1 Rare / 1 Event，`gap_check.py` 打印）。效果是 `rd-run` 里的**手写规则**，不是数据 | 内容 + 内核（每件一条规则）。⚠️ 总数**仍未核对**（wiki 的 `Relics List` 是模板生成的；`Relics` 的 Cargo 表可以像卡表那样查，但还没做 —— 下一轮补 `audit_relic_gap.py`） |
| 篝火选项 | **只有 Rest / Smith**。wiki 的 `Rest Sites` 页有三组：① 标准 = Rest（30%，`Coffee Dripper`/`Mark of the Bloom` 灰掉，满血也可用）/ Smith（`Fusion Hammer` 或全升完则灰）/ **Recall**（拿 Ruby Key，只在 Act 4 已解锁且本幕没拿过时出现）；② 遗物开启 = `Girya`→**Lift**（每次 +1 力量、最多 3 次，之后**每场战斗开始**都带这些力量）/ `Peace Pipe`→**Toke**（删一张）/ `Shovel`→**Dig**（随机遗物，只要 Common/Uncommon/Rare）；③ 被动 = `Regal Pillow`（休息 +15，**已有**）/ `Eternal Feather`（进篝火按牌数回血，**已有**）/ `Dream Catcher`（休息后给一张卡奖励，**没有**） | 内核（新选项类型 + "每场战斗开始加力量"的跨层传递）+ 内容（`girya` / `peace_pipe` / `shovel` / `coffee_dripper` / `fusion_hammer` / `dream_catcher` 六件遗物） |
| 商店 | **有**（卡/遗物/药水/删卡，价格按稀有度；A16 加价）。⚠️ **无色牌不出售**：没有 StS 的无色货架，无色牌的唯一来源是 Colorless Potion（§185）。**且内容里只有 3 张 `colorless` tag 的牌**（`audit_card_gap.py` 说 Colorless 桶 14/70） | 内核（无色货架：`stock_shop` 再加一排）+ 内容（31 张商店三档无色牌，见 §A.1） |
| 事件 | **14 个**（三幕 6+4+4，`gap_check.py` 打印），每个选项是**一串**效果（§188），从 A15 起换用 `Effects*Asc` 的糟版本。词表仍是闭集：`heal / gold / damage / max_hp / nothing / remove_card / upgrade_card / transform_card / curse:<id> / relic:<id>` | 内容（缺真实事件的剧情分支：Golden Idol 的 Outrun/Smash/Hide 三选一在我们这里压成两选项，见 inventory §7） |
| 塔底 Neow | **9 项**祝福 | 内容（缺"用初始遗物换 Boss 遗物"这类交易） |
| **钥匙（红/蓝/绿）与第四幕** | 没有 | 内核 + 内容 |
| **Ascension 1–20** | **20 / 20 条有机制**：14 条是运行层规则常量（A1 A5–A16 A20，`gap_check.py` 打印），A2/A3/A4 与 A17/18/19 走内容的 `EACT.ProgramAsc`。⚠️ A17/18/19 仍是**部分覆盖**（还有动作没有 wiki 出处），见 §E 与 §A.1 的说明 | 内容（补 17/18/19 的剩余动作） |

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

| `doubt` | 回合末给 1 层 Weak，但它**在同一回合末就被自己的衰减吃掉** | 原版里 Doubt 的 Weak 会留到下一回合 | 我们的 `standard.weak` 衰减是一条 `TurnEnded` **触发器**（第 ③ 步），而卡牌生命周期节目在第 ① 步 —— 同一次回合末里刚上的 Weak 当场被扣。参考把衰减放在 `decrease_timed_statuses`，与卡程序的关系不同。要修得动回合末的处理器顺序（影响 Burn 等所有生命周期节目），留作单独一节 |
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
`EACT.ProgramAsc` 变体实现 —— 所以机制层面是 **20/20**，但 17/18/19 的**动作覆盖**还不全。

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
3. ~~**`Slow`（Giant Head）**~~ ✅ **已完成**（§198：`ScalePercentPerStack` 运算 + `CardPlayed` 推动）。
   **"下回合多能量"仍缺**：`TurnStartDraw` 这条管线能表达"下回合多抽"（`Draw Reduction` 的反向），
   但**能量**没有对应管线（`turn_start_refill` 只读配置）—— 那是所有 Energized 类卡与药水的前提。
4. ~~**"行动者可以自毁"**（内核）~~ ✅ **已完成**（§200：`vacated_seat` 交接 + `dagger.explode` 自毁）。
   ~~**Looter 的偷钱逃走**~~ ✅ **已完成**（§201：`node.carryAwayStolenGold` +
   `CombatState::gold_carried_away` + `fight_end` 结算）。**工作包 B 到这里全部完成。**
5. **篝火选项**（运行层 + 内容，§233 之后的第一件事）：`Lift` / `Toke` / `Dig` + 开它们的
   `girya` / `peace_pipe` / `shovel` 三件遗物，外加 `coffee_dripper` / `fusion_hammer` /
   `dream_catcher` 三个"关闭/追加选项"的遗物。**`Recall` 与红钥匙**属于第四幕，跟着第 7 条。
   *成本*：`toke`/`dig` 是既有能力的复用（删牌、抽遗物），`lift` 要多一条"每场战斗开始加力量"的
   跨层传递 —— 那是这个包里唯一的新东西。
6. **卡池规模**（§A.1 的 35 张红卡 + 31 张商店无色牌）—— 纯量，不阻塞机制；**不要**当 P1
   （见审阅报告 §10.4 的反对意见）。但**无色货架**（商店里那一排）是内核的小改动 + 那 31 张的内容，
   可以整批做。
7. **第四幕与钥匙**（运行层）—— 明确的范围外，等前面清完再说；`Recall` 挂在它上面。

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
* **逐实体的账在 `docs/coverage-matrix.md`（生成物，闸门 13）**：它把"每个实体被验证到哪一步"写成 360 行 —— `Implemented` / `RuntimeTested`（`test:` 还是只有 `harness:`）/ `WikiVerified`（`wiki:<dump>` 还是只有 `spec:<TABLE>`）/ `Deviation` / `Evidence`。本文档 §G、§H 的两张表**被它直接解析**（改了这里而不改内容，那条闸门会点名是哪个 id 漂了）。`WikiVerified = —` 的那几类就是"还没回到 wiki 页看过"的清单。
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
