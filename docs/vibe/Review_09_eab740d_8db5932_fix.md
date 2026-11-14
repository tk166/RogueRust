# RogueRust 第九轮增量代码 Review

- **审查范围**：`eab740d733dee144b29a3f2c90c08ca32a934651^..8db5932cb633d53da1630ba60df99ef72f1948e1`
- **提交**：§338 `eab740d`、§339 `b7a48d5`、§340–341 `8db5932`
- **审查方式**：固定 commit 终点版本源码 + 三个提交的 GitHub 记录 + StS1 Wiki 交叉静态审查；**未独立编译/运行**，也未取得完整 compare patch。
- **设计约束**：延续 V1，避免无关重构；按已证实缺陷、尚需运行验证的风险、已声明取舍分别标记。

## 结论

§338–341 的方向与上一轮建议一致：正确地将商店折扣改为乘法叠加、购买前冻结实际价格、Courier 四排补货、失败事务回滚；事件资格用一个受限的 `RequiresAny` 模型表达，并把 `in_fight` 升格为权威 WASM 事实。开发记录报告 1223 个单元测试、23/23 道门禁，但这些不是本次独立复验数据。

**仍有三项优先修复的实质问题：两排货架 ABI 仍展示挂牌价、Courier 遗物补货使用错误稀有度价格带、Courier 有色卡补货未保留原商品类型。** 另有一个与 StS1 Wiki 有明确不一致的既存问题：`Smiling Mask` 固定价格被额外折扣，建议作为局部补充复核。它并非这次提交直接新增。

## P1-1. 无色卡和药水价格 ABI 仍与实际扣款不一致

**源码**：
- [rd-wasm/src/run.rs · `rd_run_shop_colorless_price`](https://github.com/tk166/RogueRust/blob/8db5932cb633d53da1630ba60df99ef72f1948e1/kernel/rd-wasm/src/run.rs#L1709-L1721)
- [rd-wasm/src/run.rs · `rd_run_shop_potion_price`](https://github.com/tk166/RogueRust/blob/8db5932cb633d53da1630ba60df99ef72f1948e1/kernel/rd-wasm/src/run.rs#L1781-L1793)
- [rd-run/src/state.rs · `buy_colorless` / `buy_potion`](https://github.com/tk166/RogueRust/blob/8db5932cb633d53da1630ba60df99ef72f1948e1/kernel/rd-run/src/state.rs#L5868-L5953)
- [web/index.html · 商店快照](https://github.com/tk166/RogueRust/blob/8db5932cb633d53da1630ba60df99ef72f1948e1/web/index.html#L938-L969)

`buy_*` 均以 `shop_price(offer.price)` 校验与扣款；但上面两个 ABI 仍直接 `map_or(-1, |offer| offer.price)`。页面直接读取 ABI，不再折扣。比如挂牌 100、Membership Card 5 折：界面显示 100、实际扣 50。此前新的测试只覆盖了 `RunState` 价格，未覆盖完整 WASM 对外协议。

**最小修复**：与有色卡和遗物 ABI 一样返回 `state.shop_price(offer.price)`；售罄负数哨兵保持不变。

**验收**：对四货架建立 ABI 级测试，分别比较导出显示价、内核 `NotEnoughGold.price`、购买前后 `gold` 差值。覆盖无折扣、单折扣、双折扣、售罄。

## P1-2. Courier 补货遗物没有按新遗物稀有度定价

**源码**：[rd-run/src/state.rs · `restock_relic_slot`](https://github.com/tk166/RogueRust/blob/8db5932cb633d53da1630ba60df99ef72f1948e1/kernel/rd-run/src/state.rs#L5137-L5166)

`pick_relic_avoiding()` 会按 Common/Uncommon/Rare 候选池选遗物，但随后统一 `let price = 143 + rng.roll(..., 15)`。于是 Uncommon 和 Rare 补货也按 Common 的 143–157 Gold 售卖。Wiki 的基础价为 Common 143–157，Uncommon 238–262，Rare 285–315（不同 Wiki 的端点有 ±1 取整差异）；Courier 补货不叠加 A16 涨价并不等于所有稀有度同价。

**最小修复**：使用 `picked` ID 在 `relic_pool` 中查稀有度，再调用已有 `relic_price_band`；不额外调用 `marked_up`。

**验收**：分别强制补出 Common/Uncommon/Rare，断言按本项目已确定的基础价带定价，且在 A16 与低升阶具有相同补货基础价带。

参考：[StS1 Merchant (Fandom)](https://slay-the-spire.fandom.com/wiki/Merchant)、[StS1 Merchant (wiki.gg)](https://slaythespire.wiki.gg/wiki/The_Merchant)。

## P1-3. Courier 有色卡补货没有保留 Attack/Skill/Power 类型

**源码**：[rd-run/src/state.rs · `restock_card_slot`](https://github.com/tk166/RogueRust/blob/8db5932cb633d53da1630ba60df99ef72f1948e1/kernel/rd-run/src/state.rs#L5088-L5136)

初次摆货按 2 Attack / 2 Skill / 1 Power 分类型抽取；补货时却只排除 Status/Curse/Special 与在架重复 ID，未限制被购买商品所属的卡牌类型，允许 Attack 槽被 Skill 或 Power 替代。StS1 Wiki/Fandom 对 Courier 描述为用相同类型商品替换；Colorless 是单独的商品类型，补货可重新抽其稀有度。

**最小修复**：在购买前取得原 `PoolCard.kind`，作为 `restock_card_slot` 参数进行同类筛选。保持无色卡补货独立函数不变。

**验收**：分别购买三个类型槽位，构造包含三类卡的候选池，强制验证类型不变，并覆盖候选耗尽时的既定行为。

参考：[The Courier (wiki.gg)](https://slaythespire.wiki.gg/wiki/Courier)、[Merchant (Fandom)](https://slay-the-spire.fandom.com/wiki/Merchant)。

## P2 / 既存 Wiki 差异：Smiling Mask 与折扣关系

**源码**：[rd-run/src/state.rs · `remove_card_price`](https://github.com/tk166/RogueRust/blob/8db5932cb633d53da1630ba60df99ef72f1948e1/kernel/rd-run/src/state.rs#L4524-L4540)

持有 Smiling Mask 时 `base=50`，随后仍执行 `shop_price(marked_up(base))`，在持有 Membership Card 时可能继续折扣。StS1 wiki.gg Merchant 页面明确写明 Smiling Mask 让移除价固定为 50，即使有 Membership Card 也覆盖折扣。建议核对参考版运行行为并为 `Smiling Mask × Membership Card × Courier × A16` 做小型矩阵测试；此外 A16 是否增加删卡价在公开二手资料中有分歧，不应在未独立验证前重写相关公式。

参考：[StS1 Merchant (wiki.gg)](https://slaythespire.wiki.gg/wiki/The_Merchant)。

## 已闭环的上轮问题与好实践

1. **折扣乘法与一次 ceil**：`shop_price` 使用 `i64` 分子/分母进行乘法叠加，最后一次向上取整，并保留负数售罄哨兵；新增 `107 → 43` 等字面量预期，纠正了旧测试对“30% 剩余价”的错误断言。
2. **购买时序**：四种 `buy_*` 在状态修改前计算 `due`，并统一使用其检查、错误文本和扣款，避免 Membership Card 给自身打折。
3. **补货失败原子性**：买货前保存 `RunState` 快照；补货错误会恢复金币、商品、货架以及 RNG 状态。测试利用超限池构造真实错误，不只依赖正常内容的成功路径。
4. **事件资格表达**：`RequiresAny` 实现 `AND(Requires) && (RequiresAny为空 || OR(RequiresAny))`，为 Moai Head 添加 `(HP<=50% || Golden Idol)`；Tomb of Lord Red Mask 移除了事件级错误限制，并将有无面具的互斥判定下沉到选项级。
5. **测试的反证能力**：三轮变异测试各自检查目标测试名和失败原因，且修正了旧规则预期；文档明确披露当前没有真实 AND+OR 同时出现的内容夹具。
6. **UI 权威状态**：新增 `rd_run_in_fight() → -1/0/1`；未来场景表可以区分战斗待开始和战斗进行时，不必借助页面私有历史标志。

## 仍属待办、但不应阻塞本轮的项目

- **UI 场景语义门禁**：第 23 门目前验证 ABI 导出名称对账，不验证参数/返回值及 19 个场景的可达性。`ui-state-model.md` §7b 已明确记录，建议正式 UI 开发时采用纯 `classifyScene(snapshot)` 与场景夹具，不需要现在为临时 UI 扩展像素级测试。
- **正交条件的组合测试**：当前真实内容对 `Requires` 与 `RequiresAny` 单独测试较好，但无同时带两组的真实条目。可以加一条小型合成 IR 测试验证 AND+OR 的组合和短路，不必扩展为布尔树 DSL。
- **永久泄漏/极端预算**：非本轮优先级；没有必要由这次商店闭环引入大规模 V2 重构。

## 下一轮最小行动清单

| 优先级 | 改动 | 必要验收 |
|---|---|---|
| P1 | 两类价格 ABI 返回折后价 | 四排 UI 报价、购买资格、实付价一致 |
| P1 | Courier 遗物补货按 rarity 定价 | C/U/R 三档价格带、A16 无额外涨价 |
| P1 | Courier 有色卡补货保留 kind | Attack/Skill/Power 槽位类型不变 |
| P2 | Smiling Mask 覆盖逻辑按原版再核 | 组合遗物及 A16 的独立预期矩阵 |
| 以后 | UI 场景语义测试 | 19 场景的纯函数分类及可达性 |

## 验证边界

本报告的 P1 来源于终点版本源码及其直接调用链，可以静态定位；未在本地编译、运行或测试。仓库提交记录中的 1223 个单元测试与 23/23 门禁均为项目自报，不能代替独立复验。未取得完整 Git compare 补丁，本报告是聚焦于三次修复与关键集成路径的增量静态审查，不等同逐行覆盖全量差异。

---

# 附：本地复核意见（第九轮，`8db5932` 上逐条核实）

> 仓库维护方在终点提交上逐条核对本报告。报告声明"未独立编译/运行"，这一节补的正是**代码级定位**
> 与**两个独立来源的对照**。行号以**本地**为准。
>
> 记号：**✅ 成立** = 代码确认 +（涉及规则时）两源一致；**⚠️ 证据不足** = 现象真实但"应当如何"
> 无据可查；**❌ 不成立** = 复核后否定。

## A. 结论：3 条 P1 中 2 条成立、1 条证据不足；P2 成立

| 报告项 | 复核 | 本地证据 | 备注 |
|---|---|---|---|
| **P1-1** 无色/药水 ABI 仍展示挂牌价 | **✅ 成立，且比报告说的更重** | `run.rs:1808` 与 `run.rs:1885` 都是 `map_or(-1, \|offer\| offer.price)`；有色卡 `run.rs:1694`、遗物 `run.rs:1733` 走 `shop_price` | 见 B：后果不是"显示错"，是**按钮被错误禁用** |
| **P1-2** Courier 遗物补货不按稀有度定价 | **✅ 成立**（§273 起就有；§340 我改过这个函数却没看出来） | `state.rs:5356` 硬编码 `143 + rng 15`；而 `relic_price_band(rarity)` 早就在（`state.rs:650`：143-158 / 238-263 / 285-315） | 旁证：fandom 补丁记录 "**Relics and Potions in the shop now correctly set their prices when restocked with the Courier**" —— 这曾是官方 bug |
| **P1-3** 有色卡补货应保留 Attack/Skill/Power | **⚠️ 证据不足 —— 不照单收** | 见 C | 报告把 **StS 2** 的规则当成了 StS 1 的 |
| **P2** Smiling Mask 不该再被折扣 | **✅ 成立**（两源明文） | `state.rs:4720` `self.shop_price(self.marked_up(base))`，`base = 50` | wiki.gg：*"Smiling Mask **overrides** the reduced price … to 50 Gold **even with Membership Card**"* |

## B. P1-1 的真实后果：**一个买得起的商品变成了死按钮**

页面用 ABI 价判断"买得起"（`web/ui_panels.js` 的 `disabled: card.price >= 0 && card.price > s.gold`）。
于是持 Membership Card、金币 60、无色牌挂牌 100 时：

* 内核会收 **50**（够）；
* 页面显示 **100** 且**把按钮禁用** ⇒ 玩家**根本点不到**。

比"点了被拒"更糟：拒了至少还有一句错误消息，禁用是**连话都不说**。

而 §338 的判据 `every_purchase_charges_the_price_the_page_shows` 只测到 `RunState` 层
（`buy_*` 的校验/扣款/错误消息三处一个数），**ABI 层没有一条判据** —— 报告这句批评成立，
而且这正是"两个数"能藏身的地方：内核自洽了，但**它告诉页面的数**是另一个。

## C. 为什么不接受 P1-3

报告引的两句 "same type" 在 StS 1 的语境里指**商品类别**（card / relic / potion），不是牌的
Attack/Skill/Power：

1. fandom 原文：*"replaced by a random item of the same type"*，紧接着**专门**补一句
   *"The **Colorless cards may be replaced by a colorless card of a different rarity**"* ——
   这句在说**稀有度会重掷**，全文没有一句说"牌的类型保持"。
2. teemo.dev 的 StS1 系统分析：买走一格后 *"replaces the emptied slot with a new random item of the
   same type **without respecting the original slot's rarity**"* —— 只提稀有度。
3. 唯一明确写"卡以**同类型**回来、稀有度重掷"的是 **StS 2** 的攻略；而 StS 2 的补丁记录写着
   **2025-10-02 "The Courier relic now respects the rarity/type constraints of the slot"** ——
   说明**在 StS 2 里这曾经是 bug、后来才修**。

⇒ StS 1 没有"补货保持牌类型"的证据，而"2 攻 / 2 技 / 1 能力"是**铺货**规则，不是**补货**规则。
**不改**，记入 `docs/sts-wiki-gap.md` 的"与 StS 2 的差异（未证实 StS 1 如此）"。

## D. 报告没提、复核时查出来的两处

| 发现 | 证据 | 影响 |
|---|---|---|
| **删卡服务没有"每店一次"限制** | wiki.gg：*"Can only be used **once per Shop**. Its price starts at 75 Gold and increases by 25 each time it is bought at a shop."*；fandom 同句 | 我们现在能在同一家店里连删多张（75 → 100 → 125）。这是**规则缺失**，不是数值偏差 |
| **A16 是否加价删卡，我们是在猜** | wiki.gg 只笼统说 *"A16 makes prices 10% more expensive"*，删卡价目只给 75；teemo.dev 列 *"Card removal, 1st purchase \| 75 \| 75, exact \| Variance: None"* | 我们 `marked_up(75)` = 83。**待核**，与 P2 是两件事（P2 的修法是"Smiling Mask 直接硬 50"，与 A16 无关） |

## E. 修复顺序（本次按此执行）

| 顺序 | 改动 | 不可缺少的判据 |
|---|---|---|
| 1 | 两个 ABI 走 `shop_price`，`-1` 哨兵原样穿过去 | **ABI 级**四排矩阵：导出价 == 扣款 == `NotEnoughGold.price`，覆盖 无折扣 / 单折扣 / 双折扣 / 售罄 |
| 2 | `restock_relic_slot` 用 `relic_price_band(picked 的稀有度)`，仍不 `marked_up` | 强制补出 C/U/R 三档，断言落在对应价带；A16 下同一价带 |
| 3 | Smiling Mask 时 `remove_card_price` **直接返回 50**（不过 `shop_price`、不过 `marked_up`） | 2×2×2 矩阵（MC × Courier × A16）全为 50 |
| 4（下一轮） | 删卡"每店一次"：新字段 `removed_this_shop`，`enter_shop` 清 | 同店第二次删卡必须被拒且**整状态不变**；跨店恢复可用；新字段要进 archive + hash（§308 闸门盯着） |
| — | **不改** P1-3，写进 `docs/sts-wiki-gap.md` | 文档行 + 不新增行为 |

## F. 证据来源

* [wiki.gg · The Merchant](https://slaythespire.wiki.gg/wiki/The_Merchant)：A16 涨价、2/2/1、价目表、
  "Can only be used once per Shop"、Smiling Mask "overrides … even with Membership Card"
* [wiki.gg · The Courier](https://slaythespire.wiki.gg/wiki/The_Courier)：补货范围、补货不受 A16、
  "Smiling Mask will negate The Courier's price reduction"
* [fandom · Merchant](https://slay-the-spire.fandom.com/wiki/Merchant)：补货 "same type"、
  "Colorless cards may be replaced by … different rarity"、补丁记录"restocked prices"
* [teemo.dev · Economy: Gold, Shops & Potions](https://teemo.dev/game-design/slay-the-spire/systems/economy-gold-shops-and-potions/)：
  StS1 的价目基线、补货 "without respecting the original slot's rarity"
* [sts.wiki（**StS 2**，仅用于说明 P1-3 的来源）](https://sts.wiki/relics/the-courier)：
  "respects the rarity/type constraints" 是 **2025-10 的修复**，不是 StS 1 的规则

> **一句话**：P1-1 与 P1-2 是实打实的缺陷（P1-1 比报告估得重：它让按钮变死），P2 成立且两源明确；
> **P1-3 把 StS 2 的规则当成了 StS 1 的**，本次不改。另补两处报告未提的偏差（删卡"每店一次"缺失、
> A16 删卡加价无据）。
