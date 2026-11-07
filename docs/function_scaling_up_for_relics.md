# 遗物批量推进的方法论（§259–§274 沉淀）

> 读者：**上下文被压缩之后接手的新会话**。目标是在不重读 4 万行内核的前提下，
> 用 10 分钟知道"下一件遗物该怎么做、做完怎么证明、哪些坑一定存在"。
>
> 证据来源：提交 `32d1439 → §274`（§259 到 §274，共 16 节），
> 期间遗物从 **15 件**铺到 **115/193**，单测 `rd-run` 118 → **146**，闸门 21 道（未增），
> 内容 122 状态 / 115 遗物行 / 镜像 145 KB。
> 逐节叙事仍在 `docs/port-plan.md`（§259–§274），本文只沉淀**可复用的方法**。

---

## 0. 一句话总纲

> **一件遗物 = 一条语义 + 一个**既有**载体 + 两条判据（响 / 不响）+ 一行数字。**
> 遗物比卡牌便宜的地方：绝大多数规则只是"在某个**已经存在**的位置加一个判断"。
> 贵的地方只有一个：**你要动的那一层还不存在**（那就先问"这是哪一档资产"）。

---

## 1. 一节的固定节拍

| # | 步骤 | 挡住的失败 |
|---|---|---|
| 1 | **抓原文**：`native/wiki_relics/relics_data.lua.txt`（`Module:Relics/data` 的离线留档）按**显示名**取 `Description`/`Rarity` | 按遗物名猜规则（`darkstone_periapt` 是"得诅咒 +6 上限"，不是"加牌 +6"；`omamori` 是"挡掉"不是"删掉"） |
| 2 | **确认它属于哪个桶**：`Common/Uncommon/Rare/Boss/Shop/Event/Starter/Special/Blight`。`Blight` 是**无尽模式**，本移植不做 | 把不可掉落的桶（`Starter`/`Boss`/`Shop`/`Event`）当普通池子摆上货架 |
| 3 | **查 §268.3 的钩子位置表 + 本文 §3 的决策树**，先找零基建的写法 | 一上手就加字段（§259 之前"回合末"那一类还以为要内核改动，其实只要一条带触发器的内容状态） |
| 4 | 写 `native/p<NNN>_relics.py`（**可重跑**、带 `assert` 守卫、id 用 wiki 的 snake_case） | 手改 JSON 无法复现；id 拼错（`lee's_waffle` vs `lees_waffle` —— 见 §4.7） |
| 5 | `tools/contentc/build.py --package sts` | 内容编不过 |
| 6 | 补两张表：`sts_content_check.py` 的 `INV_RELICS`（id 清单）、以及**每条新状态**在 `status_catalog.rs` 的登记 | 内容门报"内容里有、内核不认识" |
| 7 | `python native/sts_content_check.py` | 数量/关键字不符 |
| 8 | **写判据**（§5），每条先单独跑 | 一次写 5 条一起 debug |
| 9 | 三 crate 全测 + **负控**（§5.4） | 判据写在下游、切口没被覆盖 |
| 10 | 重建 wasm + 四条对拍 + 四道页面门 + `coverage_matrix.py` + `acceptance.ps1` | 页面/驱动/走图回归（遗物池一变，走图就重掷） |
| 11 | 写 `§NNN` + 提交，**数字必须带** | 下一节无法判断"上次到哪了" |

> ⚠️ 第 10 步里 **`ACT1_SLICE` / `SOAK` / `MAP_RENDER` / `BROWSER_TEST` 四道都要跑**：
> 遗物改的是**池子内容**，而池子决定奖励、奖励决定走图、走图决定哪个种子能赢 boss。

---

## 1b. 文件地图（改什么碰哪里）

| 要做的事 | 文件 |
|---|---|
| 遗物规则 | `kernel/rd-run/src/state.rs` —— `RelicEffect`（新变体）+ `relic_effect()`（id → 变体）+ 一个消费点 |
| 需要在**战斗里**生效 | `RunState::combat_bonus_for(kind)` → 挂一条**内容状态**（`standard.<relic>`），规则写在 `sts.roguedeck.json` 的 `Statuses`（`PassiveModifiers` / `Triggers`） |
| 需要"每回合/回合末" | 同上：内容是 `TurnStarted` / `TurnEnded` 触发器（§260 起零内核改动） |
| 需要改伤害/状态数值 | `PassiveModifiers`：`Pipelines`（`DamageDealt`/`BlockGained`/…）、`Operation`（`Add`/`Multiply`/`Override`）、`AppliesToStatusId`（改写别的状态幅值）、`Condition`（布尔表达式，`red_skull` 的先例）、`OverrideScope = Self`（`odd_mushroom`） |
| 加牌时 | `push_card(PoolCard)`（§270）—— **唯一**加牌点 |
| 拾取时 | `push_relic(id, pool)` 的副作用区（§274）—— **唯一**授予点 |
| 金币 | `adjust_gold`（§270）—— **唯一**改金币的地方 |
| 商店价格 | `shop_price(base)`（§270）+ `remove_card_price`（§271）—— 显示价与实付价**同一个函数** |
| 进房间 | `begin_node` 的 `NodeKind` 分支（§271）+ `?` 房分流 `roll_unknown_room`（§272） |
| 药水 | `push_potion`（§271）/ `rd_env_use_potion`（`rd-wasm`） |
| 内容门 | `native/sts_content_check.py::INV_RELICS` |
| 状态目录 | `kernel/rd-core/src/status_catalog.rs` |
| 遗物账 | `native/audit_relic_gap.py`（`--write` 生成 `docs/relic-inventory.md`，193 行） |
| 页面 | `web/ui_panels.js`（面板）+ `web/index.html`（快照/动作）；只在**行为可观察层**变化时动 |

---

## 1c. 节次索引（找先例用）

| 节 | 拿到了什么载体 | 遗物 |
|---|---|---|
| §259 | 篝火六选项（`Recall`/`Lift`/`Toke`/`Dig`）| `girya` `peace_pipe` `shovel` `dream_catcher` `coffee_dripper` `fusion_hammer` `mark_of_the_bloom` |
| §260 | **零基建**：开战挂一条带触发器的内容状态 | `orichalcum` `mercury_hourglass` `horn_cleat` `captains_wheel` `stone_calendar` `cloak_clasp` `incense_burner` `pocketwatch` |
| §261 | 每张诅咒折算一层（`per_curse_statuses`）| `du_vu_doll` |
| §262 | "每第 N 张某类型牌"（按 tag 数牌）| `kunai` `shuriken` `ornamental_fan` `letter_opener` `nunchaku` `ink_bottle` `pen_nib` |
| §263 | 条件修饰器（`Condition`）/ 同侧改写（`OverrideScope`）| `red_skull` `odd_mushroom` `paper_phrog` `paper_krane` |
| §267 | **资产分档表**（零 / 轻 / 中）| —— |
| §268 | 零基建收尾 + **钩子位置表** | `self_forming_clay` `bird_faced_urn` `runic_pyramid` `lizard_tail` `black_blood` `unceasing_top` |
| §269 | **`FightKind` 参数**（`KindMask`）+ 奖励层 | `preserved_insect` `pantograph` `slavers_collar` `sling_of_courage` `question_card` `busted_crown` `prayer_wheel` `white_beast_statue` `black_star` |
| §270 | **`push_card(PoolCard)`**（类型 / `+` 行）+ **`shop_price`** | `omamori` `ceramic_fish` `darkstone_periapt` 三个蛋 `bloody_idol` `ectoplasm` `maw_bank` `smiling_mask` `membership_card` |
| §271 | `begin_node` 的 `NodeKind` 分支 + "欠一场"字段 | `meal_ticket` `ssserpent_head` `ancient_tea_set` `sozu` `toy_ornithopter` |
| §272 | **`?` 房分流**（`UnknownRoom` + 三条概率计数器）| `tiny_chest` `juzu_bracelet` |
| §273 | 一个 `enter_shop`（两条路共用）+ 买完补货 | `the_courier` |
| §274 | **`push_relic(id, pool)`** + **拾取队列**（`pickup_change`/`pickup_picks`）| `old_coin` `lees_waffle` `war_paint` `whetstone` `astrolabe` `pandoras_box` `empty_cage` |

---

## 2. 内容侧的硬规则

1. **数字只来自原文。** `Module:Relics/data` 是唯一权威（不要用 `Relics List` 页 —— 那张是模板拼的，
   机器抽取会丢字段；这一条是 §259 用掉一次教训换来的）。
2. **id 用 wiki 的 snake_case**，而且**不要**自己发明人称所有格：
   `lee's_waffle` → **`lees_waffle`**。写错时症状是内容门那句"内容里有 1 条内核不认识"（§4.7）。
3. **桶决定可不可掉落**：`Starter` / `Boss` / `Shop` / `Event` / `Special` 是"特定来源"，
   `Blight` 是**无尽模式**（不做）。`Common/Uncommon/Rare` 才是普通池。
4. **"每回合 +1 能量"这类规则写在内容里**（`standard.<relic>` 的 `TurnStartEnergy` 修饰器），
   **不是**在运行层加一个 `energy_bonus` 字段 —— 那会让"能量从哪来"有两个来源。
5. **"开战挂一条状态"是零基建的默认答案**：`combat_bonus_for` 已经能把 `StartCombatStatus` 挂上，
   规则本身（触发器/修饰器）在内容里。
6. **两半的遗物写进 `RELIC_SECOND_HALVES`**（§270 起）：`relic_effect` 只返回**一个**变体。

---

## 3. 载体决策树（先便宜后贵，不许跳级）

```
这条规则在哪个"已经存在的位置"上？
├─ 开战/回合初/回合末/受击/击杀 ────────→ 内容状态（触发器或修饰器）      §260 一次 8 件
├─ 加牌那一刻 ───────────────────────────→ push_card(PoolCard)              §270
├─ 拾取那一刻 ───────────────────────────→ push_relic(id, pool)             §274
├─ 金币变了 ─────────────────────────────→ adjust_gold                      §270
├─ 商店价 / 删牌价 ──────────────────────→ shop_price / remove_card_price    §270/§271
├─ 进了某个房间 ─────────────────────────→ begin_node 的 NodeKind 分支       §271
├─ 只在某类战斗 ─────────────────────────→ combat_bonus_for(FightKind) + KindMask §269
├─ 奖励屏给什么 ─────────────────────────→ roll_reward / reward_card_count   §269
└─ 缺一个"事实"（洗牌 / 弃牌 / 破格挡 / 战斗中选牌）→ **中资产，先造事件再回来**
```

**中资产清单**（§268.3 与 §272 的结论，别再试一次性做完）：
`sundial`/`the_abacus`（缺 `DeckShuffled`）、`tough_bandages`/`tingsha`（缺 `CardDiscarded`）、
`hand_drill`（缺"这一下打穿格挡"）、`blue_candle`/`medical_kit`（诅咒可出）、`velvet_choker`、
`orange_pellets`、`chemical_x`、`strange_spoon`、`necronomicon`、`toolbox`、`enchiridion`、
`warped_tongs`、`gambling_chip`、`matryoshka`、`dollys_mirror`、`orrery`、`cauldron`、
`singing_bowl`（运行层问句）、`bottled_*`（拾取时要绑一张牌）。

---

## 4. 七个结构陷阱（看到就要停一下）

1. **`relic_effect` 只返回一个变体。** 一件遗物要做两件事时，第二半写进 `RELIC_SECOND_HALVES`
   （唯一一张表，两个消费者各挑自己认识的变体）。现在表里四条：`busted_crown`（卡数 -2）、
   `ectoplasm`（能量载体）、`sozu`（能量载体）、`the_courier`（买完补货）。
2. **顺序就是规则。** `push_card` 里 `omamori` 必须在**最前**：被挡掉的诅咒不算"得到"，
   所以 `darkstone_periapt` 不加血、`ceramic_fish` 不给钱。换顺序它变成"付 6 上限加 9 金币"，
   而两条判据各自都看不出。
3. **同一个事实只有一种查法。** 已经踩过两次：
   ① `upgraded_id` 与 `PoolCard::upgraded` —— 前者按命名在池子里找、后者是字段，
   **字段优先**（§274 第一版只认命名，池里只有基础行时静默升不动）；
   ② `unknown_room_odds` 与 `roll_unknown_room` —— 公式必须只有一份（§272 抄了两份，负控锚点撞出 "2 matches"）。
4. **不要抢 `pending`。** 它是"这个节点要什么"，一个流程一个写者。拾取时欠的牌组编辑走
   `pickup_change`/`pickup_picks`（§274）：否则"打完 Boss 拿 Boss 遗物"会把还没拿的卡牌奖励顶掉。
5. **`const fn` 会拦住你查表。** `enemy_health_bonus_percent` 为了 `preserved_insect` 从
   `const fn` 变成 `fn` —— 先确认调用点能不能承受。
6. **"每第 N 次"要自己数，且换幕归零。** `tiny_chest` 的计数只在持有它时增长；三条 `?` 概率
   换幕归零（wiki 明写，而这条规则在 §272 之前**从没实现过** —— 因为那三个计数器没有消费者）。
7. **id 拼写是内容门的事，但症状会骗人。** `lee's_waffle` 被写成 `lee's_waffle`（带撇号）时，
   内容门报的是"内容里有 1 条内核不认识"——看起来像"内核漏了"，其实是 id 不一致。

---

## 5. 判据的三条硬要求

1. **两侧**：只测"响"会漏掉"该不响的响了"。
   - `sling_of_courage`：精英给 1 条状态、**普通/Boss 各 0 条**；
   - `war_paint`：技能 +2、**攻击 0**（`whetstone` 亦然）；
   - `pandoras_box`：Strike/Defend 全没了、**别的牌一张不动**；
   - `sozu`：24 个种子一个药水都不发、**对照组至少一个**。
2. **防真空**：断言"这个测试确实有区分度"。`whetstone` 的判据专门用"牌组里只有 1 张攻击 ⇒
   只升 1 张"和"全是 `strike+` ⇒ 一张都不加"两段证明它真的在数。
3. **测玩家看得见的东西**：`toy_ornithopter` 测**战斗员**的血（不是 `run.health` —— 那份会被
   折回覆盖）；商店折扣测"扣掉的钱"（不是"计划里的价格"）。

### 5.4 负控（每一批都做）

写一个 `native/p<NNN>_negative.py`：**每处切口改一次、跑一次、必须看到 FAILED、跑完还原**。
已知形态：

| 切口 | 结果 |
|---|---|
| `omamori` 拦下后仍加牌 | RED ✓ |
| `adjust_gold` 先回血再拦金币 | RED ✓ |
| `shop_price` 折扣改回 100% | RED ✓ |
| `?` 房概率去掉 `(1 + misses)` | RED ✓ |
| 掷骰前缀累加改成 `roll % 3` | RED ✓（**但要点分布判据**，不是公式判据） |
| `pandoras_box` 命中后也 `index += 1` | RED ✓ |
| `pickup_card` 拒之后也扣额度 | RED ✓ |

⚠️ **负控没变红先怀疑负控**：本仓库已经错三次（变异插在变量被清零之后、变异打在"不掷骰"的判据上、
变异锚点撞了两处）。所以每个负控脚本里都写了"为什么这处切口是**真会犯的错**"。

---

## 6. 收尾工序与数字口径

- **数字的权威来源**：单测 = `cargo test` 三行；内容 = `sts_content_check.py` 的 PASS 行；
  遗物账 = `audit_relic_gap.py`（`IMPLEMENTED: ... 内核不认识` 必须为 0）；矩阵 = `coverage_matrix.py`。
- **提交信息模板**：`§NNN <一句话>` + 为什么这样切载体 + **被挡回/被纠正的那一次** +
  判据覆盖了哪几侧 + 数字段。
- **每次提交后复跑一次闸门**（不是提交前）。
- **文档写在 `docs/port-plan.md` 末尾新开 §NNN**，并写清"还剩什么、每个缺口缺哪块载体"。

---

## 7. 工具骗人的已知形态（遗物侧实测）

| 形态 | 实例 |
|---|---|
| 度量报绿、被测对象早就不新鲜 | `MAX_SCRIPT` 24 KiB 的注释写着"~10x headroom"，是脚本还只有 2.4 KB 时量的（§270 被 `BROWSER_TEST` 撞爆） |
| 判据装在下游 | `whetstone` 第一版用 `upgrade_at`（按命名找 `+` 行），池里只有基础行 ⇒ 静默升 0 张，而"技能不动"那条照样绿 |
| off-by-one 藏在"删除"里 | `pandoras_box` 命中后 `index += 1`，而 `remove_at` 已经把后面的牌前移 ⇒ 5 张基础牌只改 2 张 |
| fixture 写死了一个不再成立的前提 | `?` 房不再是事件之后，四条老判据/驱动同时红（§272.5）：它们按 `kind` 结算，而 `pending` 才是答案 |
| 注释里的反引号截断模板串 | `web/*.mjs` 的注释在模板字符串里，一个反引号就是 `SyntaxError: missing ) after argument list` |
| heredoc 吃掉 `\\n` | 锚点静默匹配不上（FACTS §161.5），于是"改了但没生效" |

---

## 8. 现状与剩下的分档（115 / 193）

**已实现 115 件**：Common 34/36、Uncommon 23/36、Rare 26/34、Boss 16/30、Shop 5/20、Event 14/18、
Starter 4/4（`burning_blood` `ring_of_the_snake` 等）、Special 0/2、Blight 0/13（不做）。

**剩下 78 件里，可按"缺哪块载体"分三档**：

| 档 | 件数 | 缺什么 | 例子 |
|---|---|---|---|
| **轻资产**（有钩子，缺一条判断） | ~20 | 都在 §3 的树里 | `face_of_cleric`（战后上限 +1 → `end_of_combat`）、`sacred_bark`（药水翻倍 → 药水效果管线）、`golden_eye`（占卜）、`wing_boots`（改可达集） |
| **中资产**（缺一个事实/事件） | ~30 | `DeckShuffled` / `CardDiscarded` / "打穿格挡" / 战斗中选牌 / 拾取时绑牌 | `sundial` `the_abacus` `tough_bandages` `tingsha` `hand_drill` `bottled_*` `gambling_chip` `singing_bowl` |
| **不做**（不属于本移植范围） | 13 | 无尽模式的 `Blight` 桶 | `accursed` `hauntings` `muzzle` … |
| **其他角色** | ~15 | `Watcher`/`Silent`/`Defect` 专属 | `pure_water` `cracked_core` `ninja_scroll` `emotion_chip` |

**建议顺序**：先把轻资产那一档按"共用钩子"聚类扫掉（一次 5–10 件），
再造中资产里**收益最大**的那个事实（`DeckShuffled` 一次解锁 2 件、`CardDiscarded` 2 件）。
⚠️ 别按"稀有度"排序 —— 同一档资产内的遗物才是真的互相便宜。
