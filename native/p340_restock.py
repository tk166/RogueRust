"""§340 Courier 补货闭环（八轮 Review 2.1a/2.1b/1.4）。

## 三件事

### 1. 无色 / 药水也要补货（2.1a）

`the_courier` 的 wiki 原文：*"When a Card, Relic, or potion is purchased from the Merchant, it will
immediately be replaced by another item of the same type."* fandom 补了一句：
*"The Colorless cards may be replaced by a colorless card of a different rarity"*。

现状：`buy_colorless` / `buy_potion` 只把货架格置 `-1`，没有补货分支 ⇒ 持 Courier 时这两排
**会缩水**，而卡片/遗物两排不会。所以补 `restock_colorless_slot` / `restock_potion_slot`。

### 2. 补货的商品**不受 A16 涨价**（2.1b）

wiki：*"**Any item re-stocked** by The Courier will not be affected by the 10% price increased 16
from Ascension 16+."*

现状：`restock_card_slot` / `restock_relic_slot` 都走 `marked_up(price)` ⇒ 补出来的货按 A16 涨价，
与"首次铺货"同价 —— 而 wiki 明说这两者不同。去掉 `marked_up`。

### 3. 补货失败不许部分提交（1.4）

现状：`push_*` → `adjust_gold` → 货架置空 → `restock_*()?`。补货里的 `pool_fits` / `rng.roll` /
`RunId::new` 任一失败 ⇒ 返回 `Err` 但**金币已扣、货已给**。

修法用 `RunState: Copy` 的整结构体快照（与 `rd-wasm` 的 `fight_begin` 同一条纪律）：
`let before = *self;`，补货失败就 `*self = before;`。

⚠️ 触发条件在真实内容里几乎不可达（池子远小于 `MAX_POOL`、RNG 计数器不溢出、id 由内容门保证），
所以这是**纪律**而不是**故障**：判据用"注入一个超容量池"来构造它，而不是等玩家踩。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── ① 卡牌补货：去掉 A16 涨价 ────────────────────────────────────────────────
t = sub(t, '''        self.shop.cards[slot] = Offer {
            id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
            // 与陈列时同一条规矩：涨价在**挂牌**那一刻算，折扣在付款时算（`shop_price`）。
            price: self.marked_up(price),
        };
        used[0] = false;
        Ok(())''',
        '''        self.shop.cards[slot] = Offer {
            id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
            // §340：**补货不施加 A16 涨价**（wiki：*"Any item re-stocked by The Courier will not be
            // affected by the 10% price increased 16"*）。首次铺货才走 `marked_up`。
            // 折扣仍然在付款时算（`shop_price`），与陈列时同一条规矩。
            price,
        };
        used[0] = false;
        Ok(())''', 'restock card price')

# ── ② 遗物补货：同上 ────────────────────────────────────────────────────────
t = sub(t, '''        let price = 143 + self.rng.roll(RunStream::Shop, 15)? as i32;
        self.shop.relics[slot] = Offer {
            id: picked,
            price: self.marked_up(price),
        };
        Ok(())''',
        '''        let price = 143 + self.rng.roll(RunStream::Shop, 15)? as i32;
        self.shop.relics[slot] = Offer {
            id: picked,
            // §340：补货不受 A16 涨价（见 `restock_card_slot` 的同一条注释）。
            price,
        };
        Ok(())''', 'restock relic price')

# ── ③ 新增两排的补货 ────────────────────────────────────────────────────────
ANCHOR = '''    /// §332：按 wiki 的**四排**铺货。'''

NEW_RESTOCK = '''    /// §340：`the_courier` 的无色卡那一半 —— 与 [`Self::restock_card_slot`] 同一个形状，
    /// 候选集是**无色**那一半（wiki: "may be replaced by a colorless card of a **different
    /// rarity**"，所以这里**不**限制稀有度与原来那格相同）。
    fn restock_colorless_slot(
        &mut self,
        slot: usize,
        card_pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        Self::pool_fits(card_pool.len())?;
        let mut eligible = [0usize; MAX_POOL];
        let mut eligible_len = 0usize;
        for (index, card) in card_pool.iter().enumerate() {
            if !card.colorless {
                continue;
            }
            // 货架上还活着的无色卡不能再来一张（与有色那一排同一条规矩）。
            let mut on_shelf = false;
            for other in 0..self.shop.colorless_len as usize {
                if other != slot
                    && self.shop.colorless[other].price >= 0
                    && self.shop.colorless[other].id == RunId::new(card.id).unwrap_or(RunId::EMPTY)
                {
                    on_shelf = true;
                    break;
                }
            }
            if on_shelf {
                continue;
            }
            if eligible_len == MAX_POOL {
                return Err(RunError::EmptyPool("cards"));
            }
            eligible[eligible_len] = index;
            eligible_len += 1;
        }
        if eligible_len == 0 {
            self.shop.colorless[slot] = Offer {
                id: RunId::EMPTY,
                price: -1,
            };
            return Ok(());
        }
        let pick = self.rng.roll(RunStream::Shop, eligible_len as u32)? as usize;
        let card = card_pool[eligible[pick]];
        let (low, high) = colorless_price_band(card.rarity);
        let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
        self.shop.colorless[slot] = Offer {
            id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
            // §340：补货不受 A16 涨价。
            price,
        };
        Ok(())
    }

    /// §340：`the_courier` 的药水那一半 —— 与铺货同一套稀有度权重（`POTION_RARITY_WEIGHTS`），
    /// 并且**不与货架上还活着的药水重复**（铺货那边也是这么做的：同一瓶摆三次是明显的重复）。
    fn restock_potion_slot(
        &mut self,
        slot: usize,
        potion_pool: &[PoolPotion<'_>],
    ) -> Result<(), RunError> {
        let mut shelved: [RunId; MAX_SHOP_POTIONS] = [RunId::EMPTY; MAX_SHOP_POTIONS];
        let mut len = 0usize;
        for other in 0..self.shop.potions_len as usize {
            if other != slot && self.shop.potions[other].price >= 0 {
                shelved[len] = self.shop.potions[other].id;
                len += 1;
            }
        }
        let picked = self.pick_potion_avoiding(potion_pool, &shelved[..len])?;
        if picked.as_str().is_empty() {
            self.shop.potions[slot] = Offer {
                id: RunId::EMPTY,
                price: -1,
            };
            return Ok(());
        }
        let rarity = potion_pool
            .iter()
            .find(|entry| entry.id == picked.as_str())
            .map_or(Rarity::Common, |entry| entry.rarity);
        let (low, high) = potion_price_band(rarity);
        let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
        self.shop.potions[slot] = Offer {
            id: picked,
            // §340：补货不受 A16 涨价。
            price,
        };
        Ok(())
    }

'''

t = sub(t, ANCHOR, NEW_RESTOCK + ANCHOR, 'new restock fns')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('state.rs: restock for colorless/potion, no A16 markup')
