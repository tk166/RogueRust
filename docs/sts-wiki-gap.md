# 对照 StS wiki 的功能缺口清单

> **这份文件回答一个问题**：站在玩家视角，本仓库距离"像《杀戮尖塔》第一幕"还差什么。
>
> **数字不写死在正文里**：所有"我们有 N 个 / 差 M 条"的 N 都由 `python -X utf8 native/gap_check.py`
> 从内容 JSON 与代码里**重算**并打印。正文只写结论与出处的 §号；数字对不上时，是正文过期了，不是脚本。
>
> **两份来源**：`slaythespire.wiki.gg`（下面每条都带页面名）+ 本仓库实现（§ 号指向 `docs/port-plan.md`）。
> 只有两边都看过的结论才写成"有"或"没有"；只在一处看到的写成"未核对"。

---

## 0. 方法与口径

* **口径是铁甲战士（Ironclad）第一幕**，加上"三幕的骨架能走通"。其他角色的专属内容一律**不做**，
  不列进缺口。
* `需要` 一列区分三种活：
  * **内容** —— 只写 JSON（`tools/contentc/packages/sts/sts.roguedeck.json`），内核不动；
  * **内核** —— 要新机制（`rd-core` 或 `rd-run` 的规则）；
  * **页面** —— ABI 已经够了，只差前端。
* 每条状态/关键词都注明它是**内容侧**（靠 `TurnEnded` 之类的触发器 + 已有的 opcode 表达）还是
  **管线侧**（写在内核的伤害/回合代码里）。这条区分很有用：内容侧的条目成本近乎零。

---

## 1. 已经对上的部分（不再列进缺口）

| 层 | 现状 | 出处 |
|---|---|---|
| 战斗内核 | 出牌 / 结算 / 状态 / 意图 / 修饰器管线 / 效果程序 IR（70 条 opcode）/ 选择与目标 / 金色指纹 | `SEMANTICS-v1.md`，§1–§128 |
| 卡牌关键词 | **Exhaust / Ethereal / Innate / Retain / Unplayable / X 费** 全部有载体（内容里各有多行） | §144 / §146 |
| 状态 | 内容里 **24 个状态全部有规则**，`is_declared_inert()` 的名单是**空的** | §147 / §149 / §158 |
| 三幕骨架 | 地图 15 行 × 7 列 + Boss 行、每幕独立的遭遇/事件池、幕间切换 | §130 / §131 / §133 / §137 |
| 战斗流程 | 召唤随从（上限 6 槽）、Boss 分裂（Slime Boss）、半血换招（`intent.healthPercent`） | §121 / §124 / §138–§140 |
| 运行层 | 商店（卡/遗物/药水/删卡 + 价格）、篝火（休息/打铁）、宝箱、`?` 房 9 个事件、奖励屏 | §143 / §161.8 |
| Ascension | 框架 0–20 + **9 条规则已实现**（A5 A6 A7 A8 A9 A11 A13 A14 A16），每条在阈值两侧各测一次 | §159、`gap_check.py` |
| 存档 / 回放 | 单行文本 + CRC（`RDA1`）；动作序列 + 每步哈希（`RDR1`）；内容指纹 | §161.9 / §163 / §164 / §166 |
| 前端 | 战斗 + 运行层 + 存档 + 回放，真浏览器闸门（含**真指针**点击与**像素**判据） | §165 / §168 |

---

## 2. 缺口

### A. 卡牌关键词 —— 只剩"没载体的"

| 关键词 | wiki 语义 | 我们的状态 | 需要 |
|---|---|---|---|
| Exhaust / Ethereal / Innate / Retain / Unplayable / X 费 | 见 `Keywords` 页 | **有**（内容侧；X 费走 `x_cost` tag + `x.cost` + `node.repeat`） | — |
| **Double Damage**（双倍伤害，Blasphemy/Divinity 一类） | 下一张攻击打两次 | **没有** | 内核（`play.rs` 的出牌次数） |
| **Exhaust 触发链**（"每当一张牌被消耗…"） | 触发器 | **部分**：`CardExhausted` 触发器在（`LifecyclePrograms` 为空的原因是本内容还没用），但**没有一张牌用它** | 内容 |

> ⚠️ 上一版写"X 费是唯一内核不许出现的 tag，内容门 [6d] 会拒"。**已过期**：§146 删掉了
> `reject_x_cost_deck`，X 费现在有载体（`whirlwind` 与 `whirlwind+`）；内容检查反过来要求它的
> **印刷费用是 0**（`native/sts_content_check.py`），因为它的代价走 `x_cost_payment`（全部能量），
> `Costs` 表对它没有意义。

### B. 状态 —— 内容里没有的那些

已实现 24 个（`gap_check.py` 会打印全名）。wiki 常见而我们**没有**的：

| 状态 | wiki 语义 | 需要 |
|---|---|---|
| **Barricade / Blur** | 格挡不被清 / 本回合不清 | 内核（回合开始的清格挡要能跳过；`Block` 页明确点名这两个） |
| **Entangled** | 本回合不能打攻击牌 | 内核（`can_play_card` 的判据 + 回合末清） |
| **Slow** | 每打一张牌它受的伤害 +10% | 内核（伤害管线的修饰器） |
| **Draw / Energized（下一回合多抽/多能量）** | 回合开始结算 | 内核（回合开始的发牌/能量）—— 现在只有**本回合**的 `combat_draw` / `combat_energy` |
| **Poison / Focus / Orbs / Stance / Scry** | 其他角色的语言（`Keywords` 页把它们分在各自角色下） | **不做**（口径之外） |

**已实现但值得记下的偏差**：`standard.poison` 若将来引入，参考实现的毒**不随回合衰减**
（只有层数轴，回合开始按层数跳一次），与《杀戮尖塔》不同 —— 别照 StS 直觉写。

### C. 战斗流程

| 机制 | 状态 | 需要 |
|---|---|---|
| 敌人召唤随从 | **有**（上限 6 槽、主人死则随从逃） | — |
| Boss 分裂 | **有**，但**只有 Slime Boss** | 内容（另两只 Boss 的机制各要新东西） |
| Boss 半血换招 | **有**（`intent.healthPercent`） | — |
| **偷钱后逃跑**（Looter） | 没有 | 内容 + 一个"偷金币并 Escaped"的节目 |
| **往牌库塞牌**（Hexaghost 的 Burn） | 机制**有**（`createCardInstance` + 区） | 内容 |
| **形态切换 / 复活**（Awakened One） | 没有 | 内核（复活 + 换招式表） |
| **逃跑（flee）** | 没有这个概念 —— 一局只有"打完"或"死" | 内核 |

### D. 运行层

| 项 | 状态 | 需要 |
|---|---|---|
| 地图 6 种节点 + Boss 行 / 每幕独立地图 | **有** | — |
| 遭遇池按幕分 | **有**：第一幕 7 个 weak，第二幕 2 个，第三幕 6 个（共 22 个遭遇） | 内容（第二幕只有 2 个，第三幕只有 6 个） |
| **精英池** | **7 个遭遇**：第一幕 `three_sentries` / `gremlin_nob` / **`lagavulin`**，第二幕 `gremlin_leader` / **`book_of_stabbing`** / **`slavers`**，第三幕 `giant_head`。第一、二幕都到 wiki 的三个（§173/§174） | 内容：第三幕还缺 **Nemesis**（"隔回合无形"要一个回合开始触发器的载体状态）与 **Reptomancer**（召唤有 `node.createCombatant`，但"Explode 后自身死亡"需要 `destroyCombatant`，内核没有） |
| **Boss 池** | 每幕各 **1** 个：Slime Boss / The Champ / Time Eater | 内容 + 内核（The Guardian 的 Mode Shift、Hexaghost 的 Burn 升级、Bronze Automaton 的召唤） |
| 药水 | **26 / 33**（铁甲战士口径）。缺 7 瓶，见 §D.1 | 见 §D.1 |
| 遗物 | **13 件**（7 Common / 4 Uncommon / 1 Rare / 1 Event）。效果是 `rd-run` 里的**手写规则**，不是数据 | 内容 + 内核（每件一条规则）；总数**未核对**（wiki 的 `Relics List` 是模板生成的，取不到可直接引用的清单） |
| 篝火选项 | **只有 Rest / Smith**；wiki 的 `Rest Sites` 页另有 **Recall**（拿红钥匙，依赖第四幕）与三件遗物开启的 **Lift / Toke / Dig** | 内核（新选项类型）+ 内容 |
| 商店 | **有**（卡/遗物/药水/删卡，价格按稀有度；A16 加价） | — |
| 事件 | **9 个**。内核的闭合词表是 `heal / gold / damage / max_hp / nothing / remove_card / upgrade_card / transform_card / curse:<id> / relic:<id>`；本内容的 9 个事件用到的是 `gold / heal / max_hp / nothing / remove_card / upgrade_card / curse`（`gap_check.py` 打印实际用到的） | 内容；**一个选项只能有一条效果**（Golden Idol 那种"遗物 + 诅咒"还不行）→ 内核（效果的**列表**） |
| 塔底 Neow | **9 项**祝福（`Start` 表） | 内容（缺"用初始遗物换 Boss 遗物"这类交易） |
| **钥匙（红/蓝/绿）与第四幕** | 没有 | 内核 + 内容 |
| **Ascension 1–20** | **9 条 / 20 条**，见 §E | 内核（其余 11 条） |

#### D.1 差的那 7 瓶药水

对照 `Module:Potions/data`（铁甲战士口径 33 瓶：17 Common / 9 Uncommon / 7 Rare），我们有 26 瓶。
缺的 7 瓶与它们各自要什么：

| 药水 | 稀有度 | wiki 效果 | 需要 |
|---|---|---|---|
| **Blessing of the Forge** | Common | 本场战斗升级**手牌里所有**牌 | 内核（整手牌升级 + 战斗内升级的临时性） |
| **Colorless Potion** | Common | 三选一**无色**牌加入手牌 | 内容（无色牌池；`choice_offered:` 已有三种 kind） |
| **Distilled Chaos** | Uncommon | 打出抽牌堆顶 3 张 | 内核（**自动打出**，且费用为 0） |
| **Duplication Potion** | Uncommon | 本回合下一张牌打两次 | 内核（出牌次数） |
| **Fairy in a Bottle** | Rare | 致死时改为回复 30% 最大生命 | 内核（**死亡拦截**；`status.DeathPrevention` 目前已解出但没人读） |
| **Smoke Bomb** | Rare | 逃离非 Boss 战斗，无奖励 | 内核（逃跑） |
| **Snecko Oil** | Rare | 抽 5 张，手牌费用**随机化** | 内核（整手牌改费） |

> 上一版写"差的 13 瓶"。**已过期**：§158/§160 之后只剩 7 瓶，而且其中 5 瓶的机制已经落地
> （三选一加手牌、从弃牌堆取回、消耗任意张手牌、随机填满腰带、每副本改费）。`gap_check.py` 打印
> 实际的效果词表 —— 词表里没有名字的，就是还差的那个机制。

### E. Ascension 逐条

`Module:Ascension`（wiki）列了 20 条，全部**累计**。我们的 9 条在阈值两侧各有一条测试。

| # | wiki 效果 | 状态 |
|---|---|---|
| 1 | 精英出现更多（~60%） | **没有**（地图生成没有 elite 权重） |
| 2 | 普通敌人更致命（伤害提高） | **没有**（`EACT` 没有 ascension 列） |
| 3 | 精英更致命 | 没有（同上） |
| 4 | Boss 更致命 | 没有（同上） |
| 5 | Boss 战后只回复 75% | **有**（`A_BOSS_HEAL`） |
| 6 | 开局掉 10% 生命 | **有**（`A_START_DAMAGED`，在 `rd-wasm` 里应用） |
| 7 | 普通敌人更硬（生命 + 格挡） | **有**（`A_NORMAL_HP`，经 `enemy_health_percent(kind)`） |
| 8 | 精英更硬 | **有**（`A_ELITE_HP`） |
| 9 | Boss 更硬 | **有**（`A_BOSS_HP`） |
| 10 | 开局带 Ascender's Bane（诅咒） | **没有**（缺诅咒牌与"开局往牌库里塞牌"） |
| 11 | 少一个药水栏 | **有**（`A_POTION_SLOT`；腰带遗物仍在其上加 2） |
| 12 | 升级牌出现率减半（第二、三幕） | **没有**（奖励屏的升级概率没有幕参数） |
| 13 | Boss 少给 25% 金币 | **有**（`A_BOSS_GOLD`） |
| 14 | 最大生命 −5（铁甲战士） | **有**（`A_MAX_HP`） |
| 15 | 事件更糟 | **没有**（事件是闭集，没有"更糟的版本"） |
| 16 | 商店贵 10% | **有**（`A_SHOP_PRICE`，含删卡服务） |
| 17 | 普通敌人换招式表 | **没有**（`EACT` 每只怪只有一张招式表） |
| 18 | 精英换招式表 | 没有（同上） |
| 19 | Boss 换招式表 | 没有（同上） |
| 20 | 双 Boss（第三幕两只） | **没有**（`Boss3` 池只有 1 个） |

规律：**能落在"运行层的一个数"上的规则都做了**（金币/生命/药水栏/价格/回复）；
需要**第二套招式表**或**第二套伤害表**的（A2/3/4、A17/18/19）都要先给 `EACT` 加维度。

### F. 前端 / Live2D 需要的 ABI

**够用的**：战斗观察向量（`rd_env_observe_*`）、动作表、牌堆/手牌读名、敌人读名与意图、
运行层观察（19 个 slot）、`rd_env_beat_*`（一步之内的有序事件 + 墙位 + DoT 标记 + 丢条计数）、
`rd_env_forced_turns`、`rd_env_enemy_is_minion`。

**不够的两项**（都不是硬前提，但 Live2D 一定会要）：

| 缺什么 | 为什么 |
|---|---|
| 攻击/受击的**"意图-结果"配对** | 动画要知道"这一拳是为哪条意图落地的"。beats 有"谁打了谁"，没有"对应哪条意图" |
| 牌离手 → 目标 → 弃牌堆的**行进轨迹** | beats 有"谁打了谁"，没有"牌从手牌第 3 格飞到目标"这一段空间信息 |

---

## 3. 建议顺序（按"玩家感受 / 成本"比）

1. **事件效果的列表**（内核小改动）—— 解锁 Golden Idol 那种"遗物 + 诅咒"，也让 A15 有落脚点。
2. **逃跑**（内核）—— 一次改动同时解锁 Smoke Bomb 与 Looter 的偷钱逃走。
3. **出牌次数 / 费用修饰**（内核）—— 解锁 Duplication、Snecko Oil、Blessing of the Forge 的后半。
4. **死亡拦截**（内核，`status.DeathPrevention` 已经在解但没人读）—— 解锁 Fairy in a Bottle。
5. **加密与招式表**（内容 + 内核各一条）—— 精英池 4 → 9，A17/18/19 才有地方落。
6. **A1 / A10 / A12**（运行层）—— 三条都不需要新招式表，成本比 A2/3/4 低得多。

---

## 4. 这份文档怎么保持不烂

* 数字：`python -X utf8 native/gap_check.py`。
* wiki 侧引用（`slaythespire.wiki.gg`，取于 2026-11-01 的核对）：`Module:Potions/data`、
  `Module:Ascension`、`Keywords`、`Rest Sites`、`Relics`、`Acts`。**页面会变**，所以只引页面名，
  不引页面里的数字；数字以脚本重算的那一侧为准。
* 改了内容或内核规则之后，**跑一遍脚本**，把正文里对不上的句子改掉 —— 或者干脆改成"见脚本"。
  一句"我们有 26/33 瓶药水"如果没人重算，它会在下一次内容变更后变成谎话，而**没有任何闸门会红**。
