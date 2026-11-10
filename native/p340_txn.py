"""§340 第二半：四个 `buy_*` 都变成**事务**（失败不部分提交），并接上两排补货。

形状（四个函数一致）：

```rust
let before = *self;              // RunState: Copy —— 与 rd-wasm 的 fight_begin 同一条纪律
...
self.push_x(...)?;               // 会失败的那一半先做
self.adjust_gold(-due);
self.shop.<shelf>[slot].price = -1;
if self.holds_relic("the_courier") {
    if let Err(error) = self.restock_x_slot(slot, pool) {
        *self = before;          // 补货失败 ⇒ 整状态回滚（含金币与货架）
        return Err(error);
    }
}
```

`buy_potion` 需要多一个 `potion_pool` 参数（补货要用），与 `buy_relic` 要 `relic_pool` 同一个理由。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── buy_card ────────────────────────────────────────────────────────────────
t = sub(t, '''        // §160: **提交点只有一个，而且失败的那一半在前面。**
        // 原来的顺序是"先扣钱、再 `push_card?`"：牌组满（`MAX_RUN_DECK`）时 `push_card` 返回
        // `Capacity`，而金币已经扣掉、货架也还在 —— 一次**被拒绝的**操作改变了可观察状态。
        // `push_card` 自己先校验再写，失败时什么都不动，所以调换顺序就是完整修复（`adjust_gold`
        // 不会失败）。REVIEW 的 P0，判据是 `a_refused_purchase_leaves_the_run_untouched`。''',
        '''        // §160: **提交点只有一个，而且失败的那一半在前面。**
        // 原来的顺序是"先扣钱、再 `push_card?`"：牌组满（`MAX_RUN_DECK`）时 `push_card` 返回
        // `Capacity`，而金币已经扣掉、货架也还在 —— 一次**被拒绝的**操作改变了可观察状态。
        // `push_card` 自己先校验再写，失败时什么都不动，所以调换顺序就是完整修复（`adjust_gold`
        // 不会失败）。REVIEW 的 P0，判据是 `a_refused_purchase_leaves_the_run_untouched`。
        //
        // §340：补货**也可能失败**（`pool_fits` / `rng.roll` / `BadId`），而它在扣钱之后。
        // 于是整笔交易包一层快照：补货失败就把 `RunState` 整个还回去（`RunState: Copy`，
        // 与 `rd-wasm` 的 `fight_begin` 用同一条纪律）。''', 'buy_card comment')

t = sub(t, '''        self.push_card(card)?;
        self.adjust_gold(-due);
        self.maw_bank_broken = true;
        self.shop.cards[slot].price = -1;
        // §273：`the_courier` —— "The Merchant restocks cards, relics, and potions"：买走的那一格
        // **立刻补上**（而不是留空）。走 `RELIC_SECOND_HALVES` 的同一张表，所以"这件遗物有哪两半"
        // 仍然只有一处。
        if self.holds_relic("the_courier") {
            self.restock_card_slot(slot, card_pool)?;
        }
        Ok(())''',
        '''        let before = *self;
        self.push_card(card)?;
        self.adjust_gold(-due);
        self.maw_bank_broken = true;
        self.shop.cards[slot].price = -1;
        // §273：`the_courier` —— "The Merchant restocks cards, relics, and potions"：买走的那一格
        // **立刻补上**（而不是留空）。走 `RELIC_SECOND_HALVES` 的同一张表，所以"这件遗物有哪两半"
        // 仍然只有一处。
        if self.holds_relic("the_courier") {
            if let Err(error) = self.restock_card_slot(slot, card_pool) {
                // §340：补货失败 ⇒ **整笔交易**回滚（金币、牌、货架一起），不留半个提交。
                *self = before;
                return Err(error);
            }
        }
        Ok(())''', 'buy_card body')

# ── buy_relic ───────────────────────────────────────────────────────────────
t = sub(t, '''        // §160: the same commit-point rule as `buy_card` -- the failing half must come first.
        self.push_relic(offer.id.as_str(), card_pool)?;
        self.adjust_gold(-due);
        // §270：`maw_bank` "No longer works when you spend any Gold at a shop"。
        self.maw_bank_broken = true;
        self.shop.relics[slot].price = -1;
        // §273：`the_courier` 补货（同上）。
        if self.holds_relic("the_courier") {
            self.restock_relic_slot(slot, relic_pool)?;
        }
        Ok(())''',
        '''        // §160: the same commit-point rule as `buy_card` -- the failing half must come first.
        let before = *self;
        self.push_relic(offer.id.as_str(), card_pool)?;
        self.adjust_gold(-due);
        // §270：`maw_bank` "No longer works when you spend any Gold at a shop"。
        self.maw_bank_broken = true;
        self.shop.relics[slot].price = -1;
        // §273：`the_courier` 补货（同上）。§340：失败 ⇒ 整笔回滚。
        if self.holds_relic("the_courier") {
            if let Err(error) = self.restock_relic_slot(slot, relic_pool) {
                *self = before;
                return Err(error);
            }
        }
        Ok(())''', 'buy_relic body')

# ── buy_colorless：接上补货 ─────────────────────────────────────────────────
t = sub(t, '''        self.push_card(row)?;
        self.adjust_gold(-due);
        self.maw_bank_broken = true;
        self.shop.colorless[slot].price = -1;
        Ok(())''',
        '''        let before = *self;
        self.push_card(row)?;
        self.adjust_gold(-due);
        self.maw_bank_broken = true;
        self.shop.colorless[slot].price = -1;
        // §340：无色那一排也要补货 —— wiki 的 Courier 说的是 "cards, relics, and potions"，
        // 无色牌是 cards；fandom 另补一句"may be replaced by a colorless card of a different
        // rarity"。§332 加这一排时漏了这条，于是持 Courier 时只有两排会补货。
        if self.holds_relic("the_courier") {
            if let Err(error) = self.restock_colorless_slot(slot, card_pool) {
                *self = before;
                return Err(error);
            }
        }
        Ok(())''', 'buy_colorless body')

# ── buy_potion：加 potion_pool 参数 + 补货 ──────────────────────────────────
t = sub(t, '''    pub fn buy_potion(&mut self, slot: usize) -> Result<(), RunError> {''',
        '''    pub fn buy_potion(
        &mut self,
        slot: usize,
        potion_pool: &[PoolPotion<'_>],
    ) -> Result<(), RunError> {''', 'buy_potion signature')

t = sub(t, '''        self.push_potion(offer.id.as_str())?;
        self.adjust_gold(-due);
        self.maw_bank_broken = true;
        self.shop.potions[slot].price = -1;
        Ok(())''',
        '''        let before = *self;
        self.push_potion(offer.id.as_str())?;
        self.adjust_gold(-due);
        self.maw_bank_broken = true;
        self.shop.potions[slot].price = -1;
        // §340：药水那一排也补货（`the_courier` 的原话里有 "potions"）。
        if self.holds_relic("the_courier") {
            if let Err(error) = self.restock_potion_slot(slot, potion_pool) {
                *self = before;
                return Err(error);
            }
        }
        Ok(())''', 'buy_potion body')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('state.rs: four buy_* are transactions')
