"""§332（续）：`buy_potion` + 存档 + 指纹。

`buy_potion` 照 `buy_relic` 的形状（**先做会失败的那一半**：`push_potion` 在扣钱之前，
所以"药水栏满了"不会先扣钱）；`courier` 补货用同一个 `restock_*` 机制。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'
ARCHIVE = 'kernel/rd-run/src/state/archive.rs'
HASH = 'kernel/rd-run/src/hash.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(STATE, encoding='utf-8').read()

# ── 1. buy_potion / buy_colorless ─────────────────────────────────────────────
t = sub(t, """    /// Pay to remove a card from the deck. Returns the price paid.
    pub fn remove_card(&mut self, card: usize) -> Result<i32, RunError> {""",
        """    /// §332：买无色货架上的第 `slot` 张（与 [`Self::buy_card`] 同一形状，池子是**无色**那一半）。
    pub fn buy_colorless(
        &mut self,
        slot: usize,
        card_pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::Shop {
            return Err(RunError::WrongPhase);
        }
        let offer = *self
            .shop
            .colorless()
            .get(slot)
            .ok_or(RunError::EmptyOffer(slot as u8))?;
        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        if self.gold < offer.price {
            return Err(RunError::NotEnoughGold {
                price: offer.price,
                gold: self.gold,
            });
        }
        let Some(row) = card_pool.iter().find(|card| card.id == offer.id.as_str()).copied()
        else {
            return Err(RunError::NoSuchCard);
        };
        self.push_card(row)?;
        self.adjust_gold(-self.shop_price(offer.price));
        self.maw_bank_broken = true;
        self.shop.colorless[slot].price = -1;
        Ok(())
    }

    /// §332：买药水货架上的第 `slot` 瓶。
    ///
    /// 与 `buy_relic` 同一条**提交点**纪律：`push_potion`（会失败的那一半 —— 腰带满了）在
    /// `adjust_gold` **之前**。反过来的话，"腰带满 + 钱够"会变成"扣了钱没拿到药水"。
    pub fn buy_potion(&mut self, slot: usize) -> Result<(), RunError> {
        if self.pending != Pending::Shop {
            return Err(RunError::WrongPhase);
        }
        let offer = *self
            .shop
            .potions()
            .get(slot)
            .ok_or(RunError::EmptyOffer(slot as u8))?;
        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        if self.gold < offer.price {
            return Err(RunError::NotEnoughGold {
                price: offer.price,
                gold: self.gold,
            });
        }
        self.push_potion(offer.id.as_str())?;
        self.adjust_gold(-self.shop_price(offer.price));
        self.maw_bank_broken = true;
        self.shop.potions[slot].price = -1;
        Ok(())
    }

    /// Pay to remove a card from the deck. Returns the price paid.
    pub fn remove_card(&mut self, card: usize) -> Result<i32, RunError> {""",
        'buy functions')
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-run: buy_potion / buy_colorless')

# ── 2. 存档 ───────────────────────────────────────────────────────────────────
a = io.open(ARCHIVE, encoding='utf-8').read()
import re
m = re.search(r'\n(\s*)// §320：事件候选列表', a)
assert m, 'archive shop anchor'
anchor_ws = m.group(1)
# 找 shop 的写侧：搜 `shop.cards` 的写入
m2 = re.search(r'\n(\s*)for slot in 0\.\.state\.shop\.cards\(\)\.len\(\) \{.*?\n\s*\}\n', a, re.S)
assert m2, 'archive shop card loop'
block = m2.group(0)
extra = block.rstrip('\n') + '''
    // §332：无色货架与药水货架（与上面同一条纪律：长度 + 每格一条 id + 价格）。
    for slot in 0..state.shop.colorless().len() {
        let offer = state.shop.colorless()[slot];
        writer.id(offer.id)?;
        writer.int(offer.price)?;
    }
    for slot in 0..state.shop.potions().len() {
        let offer = state.shop.potions()[slot];
        writer.id(offer.id)?;
        writer.int(offer.price)?;
    }
'''
a = a.replace(block, extra, 1)
io.open(ARCHIVE, 'w', encoding='utf-8', newline='\n').write(a)
print('archive: colorless + potion shelves written')
