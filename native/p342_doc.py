"""§342 的 port-plan 章节 + wiki-gap 更新。"""

import io

PLAN = 'docs/port-plan.md'
GAP = 'docs/sts-wiki-gap.md'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


SECTION = """
## §342 商店三处收尾 —— 以及一个"四排其实只有两排"的发现

第九轮 Review 的 P1-1 / P1-2 / P2。三条本身都不大，但**给 P1-1 写负控时**发现了一件更严重的事。

### ★ 发现：§332 的四排货架，从 ABI 入口只走得到两排

给 P1-1 写 ABI 级判据，负控却**抓不到**"无色价改回挂牌价"。打印一看：

```
DEBUG shelf cards: count=5      ← 有
DEBUG shelf colorless: count=0  ← 空
DEBUG shelf potions: count=0    ← 空
DEBUG shelf relics: count=3     ← 有
```

两个原因，都在 `rd-wasm` 的入口，**屏幕上完全看不出来**（页面按 `count()` 画行，0 就是没画）：

1. `rd_run_begin_node` 调 `full_pool(content, **false**)` —— 那个 `false` 是 §183/§185 留下的
   "无色牌永不进牌组"过滤器 ⇒ `stock_shop` 的**无色那一排**永远没有候选。
2. 同一个函数调的是 `state.begin_node(&cards, &relics)` —— 旧签名，**没有药水池**
   （`begin_node` 委托给 `begin_node_stocked(.., &[])`）⇒ **药水那一排**永远空着。
   §332 加这个货架时专门写了 `begin_node_stocked`，注释里说"忘了传池子不会编译不过、
   但会**看得见**" —— 它确实看得见，只是没人看。

⇒ §332 的"四排齐全"在真实路径上是**两排**。而 §332 的判据直接调 `stock_shop` 并传了两个池子，
**绕过了入口**，所以一直是绿的。这是"加了一排货架，但从入口根本走不到"的典型。

修法：入口 `full_pool(content, true)` + `begin_node_stocked(.., &potions)`；
`restock_card_slot` **显式**跳过无色牌（补货也不能把无色牌补进有色格，§185 的不变量）；
三个 `buy_*` 的补货池也换成带无色的。

### 1. 两个 ABI 仍展示挂牌价（P1-1）

`rd_run_shop_colorless_price` / `rd_run_shop_potion_price` 返回 `offer.price`，而有色卡与遗物
那两行走 `shop_price`。页面用 ABI 价判断"买得起"（`price > gold` ⇒ 禁用），于是持
Membership Card、金币 60、无色牌挂牌 100 时：内核会收 50，页面显示 100 **并把按钮禁用**
—— **玩家根本点不到**。比"点了被拒"更糟：禁用连话都不说。

⇒ 两处都改走 `shop_price`，`-1` 哨兵原样穿过去。

**为什么 §338 的判据没抓到**：`every_purchase_charges_the_price_the_page_shows` 只测到
`RunState` 层 —— 它证明"校验/扣款/错误消息三处一个数"，但**没证明"内核告诉页面的数"是那一个数**。
新判据 `the_page_price_is_the_price_the_kernel_charges` 在 **ABI 层**对四排各测一次：

* `p <= g` ⇒ 买必须成功，金币**正好少 p**（抓"显示比实收高"）；
* `p > g` ⇒ 必须被拒（抓"显示比实收低/高到判断反了"）；
* 买完那一格必须读 `-1`（售罄哨兵不过折扣）。

两个方向都能抓：若导出价是挂牌价而内核按折后价收，"`p <= g`"那支会看到金币少得比 p 少；
"`p > g`"那支会看到内核**接受**（0 而不是 -2）。

### 2. 遗物补货不按稀有度定价（P1-2）

`restock_relic_slot` 硬编码 `143 + rng(15)`（Common 档）⇒ Uncommon / Rare 的补货也按 143-157 卖。
而 `relic_price_band(rarity)` 早就在（143-158 / 238-263 / 285-315）。
fandom 的补丁记录写着 *"Relics and Potions in the shop now correctly set their prices when
restocked with the Courier"* —— 这曾经是**官方**的 bug。

### 3. Smiling Mask 是**硬价**（P2）

wiki.gg：*"Smiling Mask **overrides** the reduced price of the Card Removal Service to 50 Gold
**even with Membership Card**"*；Courier 页：*"Smiling Mask will **negate** The Courier's price
reduction … always locked at a price of 50 gold"*。

旧实现 `shop_price(marked_up(50))`：A16 → 55、MC → 25、两件都在 → 20。三条全错，
而每一条都只是**一个数**，屏幕上毫无异常。现在持有那件遗物时**直接返回 50**。

⚠️ "删卡在 A16 是否加价"是**另一件事**（`marked_up` 那一支），没有可靠来源
（wiki 只给 75，teemo.dev 标 *"exact / Variance: None"*）⇒ **不动**，记成待核偏差。

### 4. 没有采纳的一条（P1-3）

Review 说"Courier 有色卡补货应保留 Attack/Skill/Power"。复核后**证据不足**：

* fandom 原文 *"replaced by a random item of the same type"* 里的 type 指**商品类别**
  （card / relic / potion），紧接着它**专门**补一句 *"The Colorless cards may be replaced by a
  colorless card of a **different rarity**"* —— 说的是稀有度会重掷；
* teemo.dev 的 StS1 分析：*"without respecting the original slot's **rarity**"* —— 只提稀有度；
* 唯一明确写"卡以**同类型**回来"的是 **StS 2** 的攻略，而 StS 2 的补丁记录写着
  **2025-10-02 "The Courier relic now respects the rarity/type constraints of the slot"**
  —— 说明在 StS 2 里这曾经是 bug、后来才修。

⇒ 不按 StS 2 的规则改 StS 1。记入 `docs/sts-wiki-gap.md` 的"与 StS 2 的差异（未证实 StS 1 如此）"。

### 判据与负控

| 判据 | 钉住什么 |
|---|---|
| `the_page_price_is_the_price_the_kernel_charges`（rd-wasm） | 四排 ABI 价 == 实付；**并且**四排必须从**入口**就摆满（5/2/3/3）—— 这一条同时是"四排其实只有两排"的回归守卫 |
| `restocked_relics_are_priced_by_their_own_rarity`（rd-run） | 补出来的遗物按**它自己**的稀有度定价；三档必须都出现过（否则"只补 Common"也会绿） |
| `smiling_mask_locks_removal_at_fifty_whatever_the_discounts`（rd-run） | 2×2×2（MC × Courier × A16）全为 50；对照组（无 Smiling Mask）MC ⇒ 38、MC+Courier ⇒ 30 |
| `the_courier_restocks_all_four_shelves`（扩写） | 补货**不许**把无色牌补进有色格（§185 的不变量，因为入口现在传的是带无色的池子） |

负控 **4/4**（`native/p342_negative.py`）：无色 ABI 改回挂牌价 / 遗物补货改回 Common 硬编码 /
Smiling Mask 改回打折 / **入口退回 `begin_node`（空药水池）**。

★ 第 ① 条**第一次是 NOT CAUGHT** —— 因为那两排货架根本是空的，判据没有东西可测。
"负控抓不到"本身就是发现：它把"四排其实只有两排"顶出来了。

### 数字

`rd-run 223`（221 + 2）、`rd-wasm 184`（183 + 1）、`rd-core 819`、units **1226**（下限 1223 → 1226）；
四条对拍不动；`WEB_SMOKE PASS`；23/23 闸门。
"""

t = io.open(PLAN, encoding='utf-8').read()
assert '## §342' not in t
io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + '\n' + SECTION)

# ── wiki-gap：商店那一行补三件事 ────────────────────────────────────────────
g = io.open(GAP, encoding='utf-8').read()
g = sub(g, '''`membership_card` 折扣都在；折扣**乘法叠加**（0.5 × 0.8 = 40%）且**向上取整**（§338）。⚠️ 待核：删卡服务上 Courier 与 Membership Card 是否"取更好的那一个"（fandom 说取、wiki.gg 说照常，两源互斥） | — |''',
        '''`membership_card` 折扣都在；折扣**乘法叠加**（0.5 × 0.8 = 40%）且**向上取整**（§338）。
**四排的价格 ABI 都返回折后价**（§342：无色/药水两排曾经返回挂牌价 ⇒ 页面把买得起的商品禁用）；
遗物补货按**补出来那一件**的稀有度定价（§342）；`smiling_mask` 是**硬价 50**，不涨价不折扣（§342）。
⚠️ 待核三条：① 删卡服务上 Courier 与 Membership Card 是否"取更好的那一个"（fandom 说取、wiki.gg 说照常，两源互斥）；
② **删卡"每店一次"还没实现**（wiki.gg/fandom 都写 "Can only be used once per Shop"）—— 现在能同店连删；
③ A16 是否加价删卡无据（wiki 只给 75，teemo.dev 标 exact），我们按加价实现。
⚠️ 与 **StS 2** 的差异（未证实 StS 1 如此）：StS 2 的 Courier 补货"保留槽位的稀有度/类型约束"，
StS 1 的两份 wiki 只说"同一**类别**的商品"，且明说无色牌的**稀有度会重掷** ⇒ 我们**不**保留 Attack/Skill/Power | — |''',
        'shop row')
io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)
print('port-plan §342 + wiki-gap shop row')
