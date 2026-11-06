# 卡牌批量推进的方法论（§225–§242 沉淀）

> 读者：**上下文被压缩之后接手的新会话**。目标是在不重读 4 万行内核的前提下，
> 用 10 分钟知道"下一张牌该怎么做、做完怎么证明、哪些坑一定存在"。
>
> 证据来源：提交 `8088ae3 → 1997fd1`（§225 到 §242，共 18 节），
> 期间红卡从零星几张（§235 那批 14 张是起点）铺到 **75/75 齐**，单测 915 → 958，
> 闸门 18 道 → **21 道**，内容 145 卡行 → **187 卡行**。
> 逐节叙事仍在 `docs/port-plan.md`（§225–§242），本文只沉淀**可复用的方法**。

---

## 0. 一句话总纲

> **一张牌 = 一条语义 + 一个载体 + 两条判据（响 / 不响）+ 一行数字。**
> 缺任何一样，那一节就不算做完 —— 数字不对是内容 bug，判据缺一侧是"以后会静默变错"。

---

## 1. 一节的固定节拍

按顺序做，每一步都有它挡住的失败模式（括号里是真实出过的事）：

| # | 步骤 | 挡住的失败 |
|---|---|---|
| 1 | **抓原文**：`web_search` 或 `native/wiki_cards/<id>.txt`，把 `Description / Cost / CostPlus / Type / Rarity` 抄进脚本注释 | 按牌名猜语义（§235 `sever_soul`、§242 `spot_weakness` 的 Strength≠Weak、`feel_no_pain` 猜成掉血其实是消耗） |
| 2 | **逐节点扫现有载体**：node 表 / `ChoiceThen` / `ChoiceSource` / 费用阶段 / 触发器事件，能拼就用拼的 | 一上手就加节点（§228 Sword Boomerang 发现 `dealDamageToRandomTarget` 早就在；§235 14 张牌**内核零改动**） |
| 3 | **写 `native/p<NNN>_content.py`**（可重跑、带 `assert not (have & ids)` 守卫） | 手改 JSON 之后无法复现（§239 我丢了 `/tmp` 备份，只能重写脚本） |
| 4 | **`tools/contentc/build.py --package sts`** | 内容编不过 |
| 5 | **补三张表**：`sts_content_check.py` 的 `INV_CARDS`（含 `Facts`/`Cost`/`Tags`）、`card_wiki_inventory.py` 的 facts + `DEVIATIONS`、`status_catalog.rs`（新状态必须有"内核有规则"或"声明 inert"） | §242 `corruption` 被 `the_status_catalogue_is_honest` 抓到"内容声明了、内核不认识 ⇒ 安静地什么都不做" |
| 6 | **跑内容门** `python native/sts_content_check.py` | 关键字/落区/数量与 wiki 不符（每张牌都过一次） |
| 7 | **写判据**（见 §5），每条先单独跑 | 一次写 5 条一起 debug（§236 就因为连带错误多花了两轮） |
| 8 | **三 crate 全测**：`cargo test -p rd-core -p rd-run -p rd-wasm --release -- --test-threads=1` | 只测 rd-core，`ChoiceSource` 新变体的穷尽 match 会在 wasm 侧报错 |
| 9 | **重建 wasm**：`cargo build -p rd-wasm --release --target=wasm32-unknown-unknown` + `cp .../rd_wasm.wasm web/` | 页面测的还是旧内核（`web-package` 会比对 sha） |
| 10 | **四条对拍** `python native/fight_diff.py` | 改了内核语义却没发现破坏 C# oracle 契约（§225 的 `archive_the_evidence` 就是这么挡回来的） |
| 11 | **矩阵** `coverage_matrix.py` + **全套闸门** `tools\acceptance.ps1`（21 道） | 页面/驱动/走图层的回归（`ACT1_SLICE`、`SOAK`、`BROWSER`） |
| 12 | **写 §NNN 文档 + 提交**，提交信息里**必须带数字** | 下一节无法判断"上次到哪了" |

> ⚠️ 第 9/10/11 步**不能省**：只跑单测会漏掉"wasm 没重建"和"奖励池漂移把闸门走图改了"这两类。

---

## 1b. 文件地图（改什么碰哪里）

| 要做的事 | 文件 |
|---|---|
| 新内容（卡/状态/敌人动作） | `native/p<NNN>_content.py` → `tools/contentc/packages/sts/sts.roguedeck.json` → `tools/contentc/build.py` |
| 新的执行节点 | `kernel/rd-core/src/ir.rs`（变体 + `ALL` 计数 + 两个名字映射）→ `exec.rs`（预检表 + 派发 + 实体） |
| 新的事件/触发器 | `state.rs::CombatEvent` → `host.rs::TriggerEvent`（变体/from_wire_name/wire_name/dispatch）→ 入队点（**生命周期节目在哪它在哪**） |
| 新的表达式 | `expr.rs`（`INT_KINDS`/`BOOL_KINDS`/`CARD_KINDS` + 求值臂）；需要内容的用 `ExprContext::content` |
| 新的"选完做什么" | `state.rs::ChoiceThen`（+ `destination()` 穷尽 match）→ `exec.rs::choose_cards_node` 的 `Then` 解析 |
| 新的"从哪儿选" | `state.rs::ChoiceSource`（+ `zone()` 穷尽 match）→ `exec.rs` 的 `FromZone` → `rd-wasm/src/lib.rs` 的 source 编号 |
| 新的费用规则 | `play.rs::CostStage`（变体 + `priority` + `modifier_id` + `COST_STAGE_ORDER` 计数与顺序） |
| 新的落区规则 | `play.rs::played_card_destination`（Corruption 是包一层的先例） |
| 新的出击/请求类型 | `state.rs::EffectRequest` → `exec.rs`（三处穷尽 match：`resolve_request`/`request_target`/`request_source`） |
| 状态目录登记 | `kernel/rd-core/src/status_catalog.rs`（*没有* 触发器/被动修饰的状态必须在这里声明"内核有规则"） |
| 内容三张表 | `native/sts_content_check.py::INV_CARDS` + `native/card_wiki_inventory.py`（facts + `DEVIATIONS`） |
| 具名测试 | `kernel/rd-core/src/host.rs` 的 `mod tests`（`arena()` / `duel()` / `give_card` / `card_in_hand` / `zone_definitions`） |
| 页面/驱动 | `web/*.mjs`（只在**行为可观察层**变化时动，页面缓存要 `?bust=`） |

## 1c. 节次索引（找先例用）

| 节 | 提交 | 拿到了什么载体 | 牌 |
|---|---|---|---|
| §225 | `5f7fbe9` | 消耗审计（三条入堆路径同落点） | Second Wind / Fiend Fire |
| §226 | `9492461` | **复制**（`ChoiceThen::Copy`）+ `cardInstance.resolving` | Dual Wield / Nightmare |
| §227 | `7aa3e8c` | `ChoiceThen` 的三种"选完再改它" | Armaments / Warcry |
| §228 | `592855c` | 随机目标、按格挡打伤害 | Sword Boomerang / Body Slam |
| §229 | `b43dfdad` | **每副本 mark counter** | Rampage / Rip and Tear / Searing Blow |
| §230 | `27ecace` | 按 tag 数牌加伤 | Perfected Strike / Flex / Limit Break |
| §231 | `c40b81c` | 单节点读自己结果（Reaper）、`no_draw` | True Grit / Battle Trance / Reaper |
| §232 | `18d8114` | X 费（`x.cost`） | Skewer / Malaise |
| §233 | `7772e12` | `setDefensivePool`（绝对值） | Entrench |
| §235 | `0f3913a` | 纯内容一批（**内核零改动**） | 14 张红卡 |
| §236 | `87c049a` | **`loseHp` 动作 + `HpLost` 事件 + `hpLoss.fromCard`** | Bloodletting / Hemokinesis / Offering / Brutality / Rupture |
| §237 | `6a134bb` | **`BlockGained`/`CardsDrawn`/`CardExhausted` 钩子 + `curse` 位** | Juggernaut / Evolve / Fire Breathing / Dark Embrace / Feel No Pain |
| §238 | `d762edf` | **If Fatal 单节点**、复制作用域表、`ChoiceSource::ExhaustPile` | Feed / Double Tap / Exhume / Heavy Blade |
| §239 | `f8613fa` | **`PlayCondition` 事实位（u16）**、问完继续的顺序偏差 | Clash / Burning Pact |
| §240 | `1a4975d` | **随机造牌**（按 tag，绝对价 0） | Infernal Blade |
| §241 | `a147cd5` | **强制出牌**（不付费 / 强制落区 / 随机目标） | Havoc |
| §242 | `1997fd1` | **意图纯函数 + `state.encounter`**、费用阶段键在状态 id、落区规则 | Spot Weakness / Blood for Blood / Corruption |

---

## 2. 内容侧的硬规则（每条都是踩出来的）

1. **数字只能来自原文，不能来自记忆。** 一次都别例外：
   - `heavy_blade` 的升级改的是**力量倍率**（3→5），伤害数不变；
   - `dark_embrace+` 的升级改的是**费用**（2→1），抽牌数不变（wiki `CostPlus`）；
   - `spot_weakness` 的 dump 是 gain **Strength**；
   - `feel_no_pain` 是**消耗**触发（我先按牌名猜成"掉血"，错了）。
2. **`{{KW|Exhaust}}` 有宾语时是动词，不是关键字。** 已出现 4 次：
   `sever_soul`（消耗非攻击牌）/ `burning_pact`（消耗 1 张）/ `havoc`（Exhaust **it**）/ `corruption`（Exhaust **it**）。
   ⇒ 这类牌**自己进弃牌堆**，必须在 `card_wiki_inventory.DEVIATIONS` 里写 `content_keywords: []` + `why`。
3. **`(a;b)` 括号是"基础;升级"**，不是两个数字都要。若解析器分不出"只属于升级"（如 `brutality` 的 Innate），
   就把该卡记进 `DEVIATIONS`，并放宽升级行规则（§236 加了 `base_tags + ["innate"]`）。
4. **升级行可以改的是：费用 ↓、关键字增删（`ethereal` 可少、`innate` 可多）、数字**。改别的就是抄错。
5. **每张牌的两级都要有行**（`x` 与 `x+`），除非 wiki 明确只有一级。
6. **`PlayedCardDestinationZone` 与 `TurnEndHandDestinationZone` 是内容的两格**：
   自消耗 = 前者 `ExhaustPile`；虚无 = 后者 `ExhaustPile`。

---

## 3. 载体决策树

从**最便宜**往上找，**不许跳级**：

```
这个动作内核有吗？
├─ 有现成 node/expr/request ────────────────→ 纯内容（§235 一次 14 张）
├─ 现有 node 只是"少一个字段/一个取值" ────→ 扩字段或加枚举值（§229 ToDrawPileTop、§238 ExhaustPile）
├─ 现有语义但"顺序/时点"做不到 ─────────────→ 加一个**合并节点**（§238 If Fatal、§231 Reaper）
├─ 需要一个"事情发生了" ───────────────────→ 接一个**触发器事件**（§237 三个钩子一次解锁 5 张）
├─ 需要"全局规则改某类牌" ──────────────────→ 加一个**费用阶段 / 落区规则**，键在内容的状态 id 上（§242）
└─ 需要"随机/强制/造牌" ────────────────────→ 加**请求变体 + 节点**（§240 造牌、§241 强制出牌）
```

进决定前先查这五张表（一屏就能看完）：
`kernel/rd-core/src/ir.rs`（34 个 node）· `state.rs::ChoiceThen`（6 个）· `state.rs::ChoiceSource`（4 个）·
`host.rs::TriggerEvent`（18 个）· `play.rs::CostStage`（8 个）。

---

## 4. 七个结构陷阱（看到就要停一下）

1. **整棵树先派发完，请求后才落地** ⇒ `sequence[dealDamage, conditional(读结果)]` **结构上不可能**
   （§238 `feed` 的 If Fatal）。凡"读自己刚才那一下的结果"，必须**一个节点**里同步做完
   （先例：`dealDamageAndHealByLoss`、`dealDamageAndGainMaxHealthIfFatal`）。
2. **事件必须跟生命周期节目同落点**（§237）：`Drawn` 节目有两个入口（`exec::draw_for` 中途抽牌 /
   `Host::card_drawn` 回合开始），所以 `CardsDrawn` 也必须两处都发；`Exhausted` 同理
   （`move_card_for` + `Host::card_exhausted`）。**只写一处 = 某些路径安静地不触发。**
3. **"同一份事实只有一份实现"**：语义写两遍一定漂。已经清理掉的两处：
   ① `printed_energy_cost`（把 `Costs` 又读一遍）→ 改用现成的**绝对价**计数器，函数删除；
   ② 抬最大生命的写法抽成 `gain_max_health()` 一个 helper 给两个节点共用。
   新增"复制两次"这类规则时同理：写成**表**（`DUPLICATION_SCOPES`）而不是两个 if。
4. **零选项死锁**：问句的候选里若含"正在结算的那张牌"，出牌一结束它就离手 ⇒ 候选变 0 ⇒
   页面画出"确认键永久禁用、× 也被挡住"的弹窗（§236 `warcry` 在 boss 战卡死 soak）。
   ⇒ 建候选时跳过 `ctx.resolving_card`。
5. **事实位既要有位宽也要有边界**：`event_flags` bit 0..7 全满后加宽到 `u16`（§239）；
   只在某处有效的事实（`playCondition.*`）必须配一条**内容侧判据**（只许出现在 `PlayCondition` 里），
   否则别处问它得到 0 而没人知道。
6. **"拒绝 ⇒ 一个字节都不改"** 要用**整个结构体相等**证明，`assert!` 而不是 `assert_eq!`
   （后者把两遍整个状态打进日志，只有"哪个动作"值得读）。
7. **关卡闸门的种子表随内容增长**（§223、§239 各加一次）：奖励池一变，整条走图就重掷，
   "哪个种子能赢 boss"就换人。**加样本可以，断言形状不许改** ——
   "列表里存在一个能赢的种子"仍然会在"谁都赢不了"时报红。
   ⚠️ 遇到这种红，先证明**不是真阻断**（本次：加种子后 seed 1217 以 90 血赢），再补列表。

---

## 5. 判据的三条硬要求

1. **两侧**（或多侧）：不只测"响"，还要测"不响"。
   - `juggernaut`：有状态打一次 / 没状态不伤人 / 两次获得打两次；
   - `evolve`+`fire_breathing`：`wound`(Status) / `injury`(Curse) / `strike`(Attack) **三张探针卡**；
   - `corruption`：技能免费+消耗 / 攻击照付+不消耗 / **没有状态时技能照付**（对照组）。
2. **防真空**：断言"这个测试确实有区分度"。
   - `spot_weakness` 断言"一攻击一非攻击，两者意图**确实不同**"；
   - `infernal_blade` 断言"40 次至少抽到 3 种定义"（否则池子退化成一张牌也全绿）。
3. **测玩家看得见的东西，不测代理**：
   - 费用测**实际扣掉的能量**，不测"计划里的数字"（§240 第一版读计划读错，判据抓到）；
   - "消耗"测**牌真的在消耗堆**且**不在弃牌堆**（§241 两句话分开断言）；
   - 顺序偏差也要写进断言（§239 `burning_pact` 的"问句开着时已抽了 2 张"），
     这样将来顺序变了会有东西响。

---

## 6. 收尾工序与数字口径

- **数字的权威来源**：单测数 = `cargo test` 三行之和；内容数 = `sts_content_check.py` 的 PASS 行；
  对账 = `audit_card_gap.py --offline` 的 `in-scope missing` / `-- Red ... miss`；矩阵 = `coverage_matrix.py`。
- **提交信息模板**（照抄结构，别省）：
  `§NNN <一句话>` + 为什么这样切载体 + **被挡回/被纠正的那一次** + 判据覆盖了哪几侧 + `数字段`。
- **每次提交后复跑一次闸门**（不是提交前）—— 提交本身会改 `web/` 里的东西（`rd_wasm.wasm` 是
  git-ignored，但 `smoke.mjs` 的对账会读）。
- **文档写在 `docs/port-plan.md` 末尾新开 §NNN**，并在里面写清"还剩什么、每个缺口缺哪块载体"。

---

## 7. 工具骗人的已知形态（本仓库实测，先怀疑工具）

| 形态 | 本次实例 |
|---|---|
| 度量报"成功"，被测对象没动 | §237 事件只写在 `Host::card_drawn`（回合开始专用），中途抽牌不触发 ⇒ `Evolve` 安静不响 |
| 判据装在了切口**下游** | §236 拿"打出去的 carnage"测虚无（它已离手），断言写 `>= 0` 就会全绿 |
| 顺序测试形同虚设 | §242 我把新费用阶段插在数组末尾，`priority` 顺序断言当场红（真抓到） |
| 备份没落地就以为有 | §239 `/tmp` 在 Windows bash 里没写成 ⇒ 只能重写内容脚本 |
| "整棵树先派发"被当成同步 | §238 If Fatal 第一版按同步写，Max HP 一点没涨 |
| 升级行被当成独立卡 | §240 随机池必须排 `+` 行，否则"随机"变成"随机到升级版" |

---

## 8. 无色卡：现状与 56 张的分档

**现状**：口径内 89/145 已实现；**红卡 75/75 齐**，无色 **14/70**。
已实现的 14 张：`apparition` `bandage_up` `blind` `dark_shackles` `swift_strike`（真无色 5 张）+
`slimed` `injury` `wound` `burn` `dazed` `void` `doubt` `writhe` `ascenders_bane`（状态/诅咒 9 张）。
⚠️ `swift_strike` 是**内容自己的 tag（`attack/strike/innate`）**，没有"无色"维度 —— 见下面的内容约定。

**第一批动作（必须先做）**：`native/wiki_cards/` 里只有 4 张无色牌的 dump ⇒
**56 张里有 52 张没有原文**。按 §2 第 1 条，第一批的活是**抓 dump**（`web_search`
`slaythespire.wiki.gg/wiki/<Card>` 一次能拿全描述 + 费用 + 稀有度），
没有 dump 就写内容 = 直接违反硬规则。下面三档是**预判**，抓完原文要重判。

### A 档 · 纯内容（现有 node 够，零内核改动）

| 牌 | 需要的能力 | 现成载体 |
|---|---|---|
| `trip` `panacea` | 全体 Weak / Artifact | `applyStatus(sel.allEnemies)`、`applyStatus(sel.source)` |
| `master_of_strategy` `deep_breath` `finesse` `flash_of_steel` | 抽牌 / 洗弃牌堆再抽 / 格挡+抽 | `drawCards`（重洗在抽牌实体里）、`sequence` |
| `impatience` `good_instincts` | 条件抽牌（"手上没有攻击时抽 2"） | `conditional` + 一条"手牌里有没有某 tag"的事实（§239 已有 family） |
| `j.a.x.` `bite` `shiv` `smite` `safety` `insight` `miracle` | 生成牌（Special 基础行） | `createCardInstance` |
| `clumsy` `parasite`(部分) | 虚无 / 洗入牌组 | `TurnEndHandDestinationZone` |

### B 档 · 复用小载体（本轮 §237–§242 刚造好的，几乎白送）

| 牌 | 用它 | 缺什么 |
|---|---|---|
| `chrysalis` `metamorphosis` | §240 `createRandomCardInstance{T ag,ToZone}` | 只需**按稀有度+类型**收窄池子（可先只按 tag） |
| `discovery` | `ChoiceSource::Offered`（§227 起就有） | 造 3 张候选进 `Offered`，`Then: ToHand` |
| `jack_of_all_trades` `transmutation` | §240 `createRandomCardInstance` | 池子要能按 **colorless** 收窄（见下面的"缺一个内容约定"） |
| `secret_technique` `secret_weapon` `violence` | §238 `ChoiceSource::ExhaustPile` 的同形扩展 | 加一个 `ChoiceSource::DrawPile` + `RequireAnyTag` |
| `enlightenment` `madness` | §240 的**绝对价**计数器 | 一个"对整手牌写 `card_cost_override=0`"的内容组合（`forEachCardInZone` + `addCardCounter`，可能已够） |
| `mayhem` | §241 `playTopCardOfDrawPile` | 内容挂 `TurnStarted` 触发器即可能够 |
| `magnetism` `omega` | §237 钩子 + `TurnStarted`/`TurnEnded` | `magnetism` 还要 colorless 池（同下） |
| `panache` | `CardPlayed` 钩子 + 计数器 | "每 5 张"用 `remainder`（`INT_KINDS` 已有） |
| `sadistic_nature` | `StatusApplied` 钩子 | 要一条 **debuff 极性**事实位（新，1 位） |
| `hand_of_greed` | §238 `dealDamageAndGainMaxHealthIfFatal` 的同形 | 换"抬上限"为"加金"（`gold_carried_away` 只在 run 层，需一个"给金"节点） |
| `thinking_ahead` | `ChoiceThen::ToDrawPileTop`（§227） | 抽 2 再放 1 张回顶 —— 可能已够 |
| `purity` | `ChoiceThen::Exhaust` + `Min:0` | 可能已够（多张消耗） |
| `apotheosis` | `upgradeCards` | 需扩到"**所有牌区**"（现在只认手牌） |

### C 档 · 真新载体（一张要一节）

| 牌 | 为什么难 | 大概率的形状 |
|---|---|---|
| `the_bomb` | 延迟 3 回合的伤害 | 新"延迟效果"容器 + `TurnEnded` 递减（`Nightmare` 的 `SetAsidePile` 是同族先例） |
| `normality` `pride` | **"不能再打第 N 张"** / 不能重复打 | §239 `PlayCondition` 家族：加一个 bool 事实（`cardsPlayedThisTurn` 已有） |
| `regret` `decay` `pain` `shame` | 回合末/出牌时的自伤与加费 | §237 钩子 + §242 费用阶段（`Blood for Blood` 的表已开） |
| `become_almighty` `beta→omega` | 跨回合"变身" | 组合牌 + 状态载体 |
| `expunger` `ritual_dagger` `through_violence` `fame_and_fortune` | 依赖于 run 层（能量/金/连续出牌） | 需要 run 层配合 |
| `necronomicurse` `curse_of_the_bell` | 与遗物/牌组规则交互 | run 层 |

---

## 9. 经验 → 无色卡的复用矩阵（本轮的"存款"）

| 本轮沉淀的能力 | 出处 | 无色卡里谁直接吃它 |
|---|---|---|
| 触发器钩子 `BlockGained`/`CardsDrawn`/`CardExhausted` | §237 | `panache`（CardPlayed 同族）`sadistic_nature`（StatusApplied 同族）`omega` |
| 复制作用域**表** | §238 | `double_tap` 家族、`necronomicurse`（"复制一份给自己"） |
| `ChoiceThen` 已有 6 种（含 `ToDrawPileTop`/`Upgrade`/`Copy`） | §227 §229 §238 | `thinking_ahead` `purity` `secret_*` `madness` |
| `ChoiceSource` 4 种（Hand/Discard/Exhaust/**Offered**） | §227 §238 | `discovery`（Offered）`secret_*` `violence`（DrawPile，需加一种） |
| **If Fatal 单节点** | §238 | `hand_of_greed` `feed` 家族 |
| `PlayCondition` + 手牌事实位 | §239 | `normality` `pride` `clash` 家族 |
| **随机造牌**（按 tag，排 `+` 行与 X 费） | §240 | `chrysalis` `metamorphosis` `jack_of_all_trades` `transmutation` `fame_and_fortune` |
| **强制出牌**（不付费、强制落区、随机目标） | §241 | `mayhem` `havoc` 家族、`through_violence` |
| **费用阶段键在内容状态 id 上** | §242 | `corruption` 家族、`normality`（加费方向）、`pain` |
| **意图纯函数**（`intent.select_action`）+ `state.encounter` | §242 | 所有"如果敌人打算…"（无色里只有少数，但 `spot_weakness` 已通） |
| 掉血/出牌计数（`hp_losses` / `*_this_turn`） | §242 | `regret` `pain` `normality` |

> ⚠️ **一个还没建立的内容约定**：本内容的卡 tag 只有 `attack/skill/power/status/curse`
> （+ `ethereal`/`innate`/`x_cost`/`hp_loss_cost` 这类语义 tag），**没有"颜色"维度**。
> 而 `jack_of_all_trades` / `transmutation` / `magnetism` 三张要"随机**无色**牌" ⇒ 需要给无色 70 张
> 加上 `colorless` tag（纯内容字段，内核不用改：§240 的随机池本来就是按 tag 过滤的）。
> 稀有度同理：§240 现在只有 `Tag` 一个过滤条件，若要"随机 Rare 无色牌"得再加一个 `Rarity` 过滤
> —— 那是**一个字段**的活，不是一节。

**结论**：无色 56 张里，按预判 **B 档约 20 张**可以由"§237–§242 的存款"直接吃下
（每张只差一点内容或一个枚举值），**A 档约 9 张**纯内容，**C 档约 12 张**各需一节。
⇒ 合理的批次是：**先抓 52 份 dump（一节）** → **A 档一批（内容为主）** → **B 档两三批（每批一次小载体）**
→ C 档逐个。

---

## 10. 上手 checklist（复制这段，逐条打勾）

```
[ ] 我抓了每张牌的 wiki 原文（Description/Cost/CostPlus/Type/Rarity）并抄进脚本注释
[ ] 我扫过 node/ChoiceThen/ChoiceSource/TriggerEvent/CostStage 五张表，确认没有现成载体
[ ] 内容脚本可重跑（带 assert not (have & ids)），不是手改 JSON
[ ] INV_CARDS + card_wiki_inventory(facts, DEVIATIONS) + status_catalog 三处都补了
[ ] 每条判据都**两侧**，且有防真空断言
[ ] 费用/消耗/生成的判据测的是"玩家看得见的东西"（实际扣能量、牌真在消耗堆、池子多样性）
[ ] 三个 crate 全测过；wasm 重建并 cp 到 web/
[ ] fight_diff 四条对拍不变（变了就要解释，不能"顺手更新"）
[ ] coverage_matrix + acceptance 21/21
[ ] docs/port-plan.md 新开 §NNN，写清"还剩什么、缺哪块载体"
[ ] 提交信息带数字（单测/卡行/状态/镜像字节/口径内/矩阵）
[ ] 提交后**再跑一次** acceptance
```
