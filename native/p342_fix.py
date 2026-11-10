"""§342 三处修复（第九轮 Review P1-1 / P1-2 / P2）。

## 1. 两个 ABI 仍展示挂牌价（P1-1）

`rd_run_shop_colorless_price` / `rd_run_shop_potion_price` 直接返回 `offer.price`，而有色卡与遗物
那两行走 `shop_price`。页面用 ABI 价判断"买得起"（`ui_panels.js` 的 `price > gold` ⇒ 禁用），
于是持 Membership Card、金币 60、无色牌挂牌 100 时：内核会收 50，页面却显示 100 **并把按钮禁用**
—— 玩家**根本点不到**。比"点了被拒"更糟：禁用连话都不说。

## 2. 遗物补货不按稀有度定价（P1-2）

`restock_relic_slot` 硬编码 `143 + rng(15)`（Common 档），于是 Uncommon / Rare 的补货也按
143-157 卖。而 `relic_price_band(rarity)` 早就在（143-158 / 238-263 / 285-315）。
fandom 的补丁记录写着 "Relics and Potions in the shop now correctly set their prices when
restocked with the Courier" —— 这曾经是**官方**的 bug。

## 3. Smiling Mask 是**硬价**（P2）

wiki.gg：*"Smiling Mask **overrides** the reduced price of the Card Removal Service to 50 Gold
**even with Membership Card**"*；Courier 页：*"Smiling Mask will **negate** The Courier's price
reduction … always locked at a price of 50 gold"*。

现状 `self.shop_price(self.marked_up(50))`：A16 → 55、MC → 25、MC+Courier → 20。全错。
修法：持有那件遗物时**直接返回 50**，既不涨价也不折扣。

⚠️ 与"删卡在 A16 加价吗"是**两件事**：后者没有可靠来源（wiki 只给 75，teemo.dev 标 "exact"），
所以**不动**，记成待核偏差。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'
STATE = 'kernel/rd-run/src/state.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① 两个 ABI 走 shop_price ────────────────────────────────────────────────
t = io.open(RUN, encoding='utf-8').read()

t = sub(t, '''    session
        .state
        .shop()
        .colorless()
        .get(slot.max(0) as usize)
        .map_or(-1, |offer| offer.price)
}''',
        '''    session
        .state
        .shop()
        .colorless()
        .get(slot.max(0) as usize)
        .map_or(-1, |offer| {
            // §342：**与有色卡、遗物同一个规矩** —— 页面看到的价格就是付款时的价格。
            // 售罄的 `-1` 不过折扣（`shop_price` 会原样穿过去，这里再挡一次是为了让
            // "哨兵"这件事在调用点也读得出来）。
            if offer.price < 0 {
                return offer.price;
            }
            session.state.shop_price(offer.price)
        })
}''', 'colorless price')

t = sub(t, '''    session
        .state
        .shop()
        .potions()
        .get(slot.max(0) as usize)
        .map_or(-1, |offer| offer.price)
}''',
        '''    session
        .state
        .shop()
        .potions()
        .get(slot.max(0) as usize)
        .map_or(-1, |offer| {
            // §342：同上（无色那一排的同一条注释）。
            if offer.price < 0 {
                return offer.price;
            }
            session.state.shop_price(offer.price)
        })
}''', 'potion price')
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② 遗物补货按稀有度定价 ──────────────────────────────────────────────────
t = io.open(STATE, encoding='utf-8').read()

t = sub(t, '''        let price = 143 + self.rng.roll(RunStream::Shop, 15)? as i32;
        self.shop.relics[slot] = Offer {
            id: picked,
            // §340：补货不受 A16 涨价（见 `restock_card_slot` 的同一条注释）。
            price,
        };
        Ok(())''',
        '''        // §342：**按补出来的那一件的稀有度定价**。原来这里硬编码 Common 档（143-157），
        // 于是 Uncommon / Rare 的补货也按 Common 卖 —— fandom 的补丁记录写着
        // "Relics and Potions in the shop now correctly set their prices when restocked with the
        // Courier"，说明这曾经是**官方**的 bug。
        let rarity = relic_pool
            .iter()
            .find(|entry| entry.id == picked.as_str())
            .map_or(Rarity::Common, |entry| entry.rarity);
        let (low, high) = relic_price_band(rarity);
        let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
        self.shop.relics[slot] = Offer {
            id: picked,
            // §340：补货不受 A16 涨价（见 `restock_card_slot` 的同一条注释）。
            price,
        };
        Ok(())''', 'restock relic price by rarity')

# ── ③ Smiling Mask 硬价 ─────────────────────────────────────────────────────
t = sub(t, '''    pub fn remove_card_price(&self) -> i32 {
        // §159 `A16`: the removal service is a shop price too, so it carries the same markup.
        let base = if self.holds_relic_effect(RelicEffect::RemovePriceFlat(50)) {
            // §270：`smiling_mask` —— "The merchant's card removal service now always costs 50
            // Gold"。**固定**：`removed_cards` 的 +25/次 对它失效（那是"服务涨价"，而它的原话是
            // "always costs 50"）。折扣仍然在（`Membership Card` 是另一件遗物）。
            SHOP_REMOVE_FLAT
        } else {
            SHOP_REMOVE_BASE + SHOP_REMOVE_STEP * self.removed_cards
        };
        self.shop_price(self.marked_up(base))
    }''',
        '''    pub fn remove_card_price(&self) -> i32 {
        // §342：`smiling_mask` 是**硬价** —— 既不涨价也不折扣，直接 50。
        //
        // wiki.gg：*"Smiling Mask **overrides** the reduced price of the Card Removal Service to 50
        // Gold **even with Membership Card**"*；Courier 页：*"Smiling Mask will **negate** The
        // Courier's price reduction … always locked at a price of 50 gold"*。
        //
        // 旧实现在这里 `shop_price(marked_up(50))`：A16 → 55、Membership Card → 25、
        // 两件都在 → 20。三条全错，而**每一条都只有一个数**，屏幕上看起来毫无异常。
        //
        // ⚠️ "删卡在 A16 是否加价"是**另一件事**（下面那条 `marked_up`），没有可靠来源
        // （wiki 只给 75，teemo.dev 标 "exact / Variance: None"），所以不动，记成待核偏差。
        if self.holds_relic_effect(RelicEffect::RemovePriceFlat(50)) {
            return SHOP_REMOVE_FLAT;
        }
        // §159 `A16`: the removal service is a shop price too, so it carries the same markup.
        let base = SHOP_REMOVE_BASE + SHOP_REMOVE_STEP * self.removed_cards;
        self.shop_price(self.marked_up(base))
    }''', 'remove_card_price hard 50')

io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
print('§342: two ABI prices, relic rarity band, smiling_mask hard 50')
