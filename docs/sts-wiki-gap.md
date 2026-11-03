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
| 状态 | 内容里**每一条状态都有规则**，`is_declared_inert()` 的名单是**空的**（`gap_check.py` 打印） | §147 / §149 / §158 / §180 / §181 |
| 三幕骨架 | 地图 15 行 × 7 列 + Boss 行、每幕独立的遭遇/事件池、幕间切换 | §130 / §131 / §133 / §137 |
| 战斗流程 | 召唤随从（敌人槽上限 6）、Boss 分裂、半血换招、**销毁战斗员**（§178） | §121 / §124 / §138–§140 / §178 |
| 运行层 | 商店（卡/遗物/药水/删卡 + 价格）、篝火（休息/打铁）、宝箱、事件、奖励屏、**脱战**（§179） | §143 / §161.8 / §179 |
| 药水 | **全部 33 瓶**（Ironclad 口径）都能喝，效果词表见 `gap_check.py` | §152 / §158 / §179–§185 |
| Ascension | **20 / 20 条都有机制**：13 条运行层规则（A1 A5–A9 A10 A11 A12 A13 A14 A15 A16 A20，每条在阈值两侧各测一次）+ **A2/A3/A4 与 A17/18/19 的数据维度**（13 个动作有升档变体，§187）+ 事件列表的 A15 变体（§188） | §159 / §187 / §188 / §189、`gap_check.py` |
| 存档 / 回放 | 单行文本 + CRC（`RDA1`）；动作序列 + 每步哈希（`RDR1`）；内容指纹 | §161.9 / §163 / §164 / §166 |
| 前端 | 战斗 + 运行层 + 存档 + 回放；真浏览器闸门（真指针点击 + 像素判据 + 切片五场景） | §165 / §168 / §185 |
| 诊断 | 一步之内的有序事件（beats）、**拒绝码**与**宿主失败原文**导出（§177） | `env-abi.md` §12 |

---

## 2. 缺口

### A. 卡牌关键词 —— 只剩"没载体的"

| 关键词 | wiki 语义 | 我们的状态 | 需要 |
|---|---|---|---|
| Exhaust / Ethereal / Innate / Retain / Unplayable / X 费 | `Keywords` 页 | **有**（内容侧；X 费走 `x_cost` tag + `x.cost` + `node.repeat`） | — |
| **Double Damage**（Blasphemy / Divinity：下一张攻击打两次） | `Keywords` 页 | **部分**：`standard.duplication` + `play.rs` 已经把"下一张牌打两遍"做出来了（§181，Duplication Potion 在用），但它挂在**状态**上，不是卡牌关键词，也不消费"攻击牌"这个条件 | 内容（一张带该关键词的牌） |
| **Exhaust 触发链**（"每当一张牌被消耗…"） | 触发器 | **载体有**（`LifecyclePrograms` 的 `CardExhausted`），**没有一张牌用它** | 内容 |
| **升级牌在战斗中回退**（"until end of combat" 的临时性） | — | **不适用**：我们照 wiki 的"for the rest of combat"，升级是**本场战斗内持久**的（§179） | — |

> ⚠️ 上一版写"X 费是唯一内核不许出现的 tag，内容门 [6d] 会拒"。**已过期**：§146 删掉了
> `reject_x_cost_deck`；内容检查反过来要求它的**印刷费用是 0**，因为代价走 `x_cost_payment`。

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
| **形态切换 / 复活**（Awakened One / The Guardian Mode Shift） | 没有 | 内核（复活 + 换招式表） |
| **Giant Head 的 "It Is Time" 递增**（30 点、每次 +5） | **没有**：本项目是**简化版**（320 HP + Metallicize 4 + Glare/Count 两招，§130 记录） | 内容（wiki 的 500 HP 对一局切片太长） |
| **逃跑（flee）** | **有**，但只在**运行层**（`result = 3`：不给奖励、节点算用掉、Boss 战拒绝，§179）。内核的 `CombatResult` 仍是参考的三种 | 内核（若要让敌人也能"逃走"并带走金币） |
| **自己行动时自毁**（Reptomancer 的匕首 Explode） | **做不到**：`remove_combatant` 拒绝移除**当前行动者**（回合循环按 id 找它） | 内核（"行动者消失后回合怎么收尾"的判据） |

### D. 运行层

| 项 | 状态 | 需要 |
|---|---|---|
| 地图 6 种节点 + Boss 行 / 每幕独立地图 | **有** | — |
| 遭遇池按幕分 | **有**（`gap_check.py` 打印每幕的数量） | 内容（第二幕的普通池只有 2 个） |
| **精英池** | 每幕 **3 个**：Act1 `three_sentries / gremlin_nob / lagavulin`、Act2 `gremlin_leader / book_of_stabbing / slavers`、Act3 `giant_head / nemesis / reptomancer` | — （wiki 的每幕 3 个齐了） |
| **Boss 池** | 每幕各 **1** 个：Slime Boss / The Champ / Time Eater（wiki 是每幕三选一） | 内容 + 内核（The Guardian 的 Mode Shift、Hexaghost 的 Burn 升级、Bronze Automaton 的召唤） |
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

### E. Ascension 逐条

`Module:Ascension`（wiki）列了 20 条，全部**累计**。我们的 9 条在阈值两侧各有一条测试。

| # | wiki 效果 | 状态 | 若要做，卡在哪 |
|---|---|---|---|
| 1 | 精英出现更多 | **有**（8% → 16%，普通战斗让出 8 点，§189） | — |
| 2 | 普通敌人伤害提高 | **有**（`EACT.ProgramAsc`，内容覆盖 4 个动作） | — |
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
| 20 | 双 Boss（第三幕两只） | **有**（第一只倒下后节点重开，第二只才算赢，§189） | 内容：`Boss3` 池仍只有 1 个 —— 两场打的是同一只 |

**A2/3/4 与 A17/18/19 的机制已经落地**（§187）：`EACT` 多了 `ProgramAsc` + `AscensionMin`
两格，外加一个 `intent.ascensionAtLeast` 条件。分档按**怪的种类**（普通 2/17、精英 3/18、Boss 4/19），
数字取自 wiki 单页。

⚠️ **覆盖是部分的，而且这个数字由脚本报**：`gap_check.py` 会打印"多少个动作有变体、多少个还没有"
（当前 13 / 79）。剩下的动作不是"忘了"，而是**没有 wiki 出处就不写**（`§186` 的教训：抄一个数字
比留空更贵）。要补的时候照 `native/patch_187_content.py` 的表加一行 + `INV_ASC_VARIANTS` 加一行。

**20 / 20 条全部有机制**（§189 补齐 A1 / A10 / A12 / A20）。剩下的都是**内容覆盖面**而不是规则：
A2/3/4 与 A17/18/19 只有 13 个动作有升档数值（还有 66 个等 wiki 出处）；`Boss3` 池只有 1 个，所以
A20 的两场打的是同一只 Boss。

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

1. **事件效果的列表**（内核小改动）—— 解锁 Golden Idol 那种"遗物 + 诅咒"，也让 A15 有落脚点。
2. **A1 / A10 / A12**（运行层）—— 三条都不需要新招式表，各是运行层的一条小规则。
3. **把剩下的 66 个动作的 ascension 数字补齐**（纯内容 + wiki 出处）—— 机制已经在那儿了，
   缺的只是有人去把每个数字读回来。
4. **每幕的第二、三只 Boss**（内容 + 内核各一条：Guardian 换形态、Hexaghost 的 Burn 升级、
   Bronze Automaton 的召唤）—— 顺带验"分裂/召唤/销毁"这三种已落地的机制在别处也能用。
5. **"行动者可以自毁"**（内核）—— 解锁 Reptomancer 匕首的 Explode 与 Looter 的偷钱逃走；
   需要"行动者消失后回合怎么收尾"的判据，不是加个参数。
6. **A20 双 Boss**（运行层 + 内容）—— 需要一个 Boss 池 ≥ 2 的第三幕。

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
