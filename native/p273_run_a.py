"""§273 商店族收尾：一个 `enter_shop` + `the_courier`（-20% + 买完补货）。

## 为什么是"收尾这一族"

StS1 的 `?` 房那一族（`wiki Module:Relics/data` 里描述含 `?` 的行）**只有三件**：
`Juzu Bracelet` / `Tiny Chest` / `Ssserpent Head` —— §272 已 3/3。`Planisphere` 与
`Golden Compass` 是 **StS2** 的，不在本内容里（已核：dump 193 行里两个都没有）。

所以"同族"真正还缺的是**商店那一侧**：

1. **§272 留下的真缺口**：`?` 房掷出商人时走的是 `begin_node` 的 Unknown 分支，只 `stock_shop`，
   **不经过** `NodeKind::Shop` 分支 ⇒ `meal_ticket` 不回血。wiki 的 Planisphere 页把这条明写过：
   "a ? that turns into a shop triggers both"。修法是把它抽成一个 `enter_shop`，两处共用。
2. `the_courier`（Uncommon）："The Merchant restocks cards, relics, and potions. All prices are
   reduced by 20%." —— 折扣走既有的 `ShopDiscountPercent`；"restock" 是"买走一格就补一格"。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


ENTER_SHOP = '''    /// §273：**进一次商店** —— 摆货架 + `meal_ticket` 的 15 血。
    ///
    /// 为什么必须是一个函数：`?` 房掷出商人时走的是 `begin_node` 的 Unknown 分支，而商店节点走
    /// 的是 `NodeKind::Shop` 分支。§272 之前只有后者调用这里的效果，于是
    /// "`?` 房变成商店"**不回血** —— 而 wiki 明确说这两件事都要触发
    /// （Planisphere 页：*"a ? that turns into a shop triggers both"*）。
    /// 一处实现、两个调用方，才能让"进商店"只有一个意思。
    fn enter_shop(
        &mut self,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<(), RunError> {
        self.stock_shop(card_pool, relic_pool)?;
        // `meal_ticket` —— "Whenever you enter a shop, heal 15 HP"。与 `Eternal Feather`
        // 同一条规矩：**进门就付**，不是"买了东西才付"。
        if let Some(RelicEffect::ShopEntryHeal(amount)) =
            self.first_relic_effect_of(RelicEffect::ShopEntryHeal(15))
        {
            self.heal_after_combat(amount);
        }
        Ok(())
    }

    /// §273：`the_courier` 的**第二半** —— 买走一格就补一格（同价位的重新掷一次）。
    ///
    /// 只补被买走的那一格，不重摆整个货架：wiki 说的是 "The Merchant **restocks** cards,
    /// relics, and potions"，也就是"货架不会因为你买了就变少"。
    ///
    /// 池子里没货了（牌池就这么大 / 遗物已经全在手上）⇒ 那一格留空（`price = -1`），
    /// **不是**错误：那正是"商人的货卖完了"。
    fn restock_card_slot(&mut self, slot: usize, card_pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        // 货架上还活着的卡（含其它格子）都不能再被补进来：货架不该出现两张一样的牌。
        let mut used = [false; MAX_POOL];
        let mut eligible = [0usize; MAX_POOL];
        let mut eligible_len = 0usize;
        Self::pool_fits(card_pool.len())?;
        for index in 0..card_pool.len() {
            if matches!(
                card_pool[index].rarity,
                Rarity::Status | Rarity::Curse | Rarity::Special
            ) {
                continue;
            }
            let mut on_shelf = false;
            for other in 0..self.shop.cards_len as usize {
                if other != slot && self.shop.cards[other].price >= 0
                    && self.shop.cards[other].id == RunId::new(card_pool[index].id)
                        .unwrap_or(RunId::EMPTY)
                {
                    on_shelf = true;
                    break;
                }
            }
            if !on_shelf {
                eligible[eligible_len] = index;
                eligible_len += 1;
            }
        }
        if eligible_len == 0 {
            self.shop.cards[slot] = Offer {
                id: RunId::EMPTY,
                price: -1,
            };
            return Ok(());
        }
        let pick = self.rng.roll(RunStream::Shop, eligible_len as u32)? as usize;
        let card = card_pool[eligible[pick]];
        let (low, high) = card_price_band(card.rarity);
        let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
        self.shop.cards[slot] = Offer {
            id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
            // 与陈列时同一条规矩：涨价在**挂牌**那一刻算，折扣在付款时算（`shop_price`）。
            price: self.marked_up(price),
        };
        used[0] = false;
        Ok(())
    }

    /// §273：`the_courier` 的遗物那一半（同上）。
    fn restock_relic_slot(
        &mut self,
        slot: usize,
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<(), RunError> {
        let mut shelved: [RunId; MAX_SHOP_RELICS] = [RunId::EMPTY; MAX_SHOP_RELICS];
        let mut len = 0usize;
        for other in 0..self.shop.relics_len as usize {
            if other != slot && self.shop.relics[other].price >= 0 {
                shelved[len] = self.shop.relics[other].id;
                len += 1;
            }
        }
        let picked = self.pick_relic_avoiding(RunStream::Shop, relic_pool, &shelved[..len])?;
        if picked.as_str().is_empty() {
            self.shop.relics[slot] = Offer {
                id: RunId::EMPTY,
                price: -1,
            };
            return Ok(());
        }
        let price = 143 + self.rng.roll(RunStream::Shop, 15)? as i32;
        self.shop.relics[slot] = Offer {
            id: picked,
            price: self.marked_up(price),
        };
        Ok(())
    }

'''


def main():
    src = io.open(P, encoding='utf-8').read()

    # ---- ① `enter_shop` + 两个补货函数（放在 `stock_shop` 之前）
    src = patch(src, '    fn stock_shop(&mut self, card_pool: &[PoolCard<\'_>], relic_pool: &[PoolRelic<\'_>]) -> Result<(), RunError> {',
                ENTER_SHOP + '    fn stock_shop(&mut self, card_pool: &[PoolCard<\'_>], relic_pool: &[PoolRelic<\'_>]) -> Result<(), RunError> {',
                'enter_shop helpers')

    # ---- ② 商店节点走共享入口
    src = patch(src, '''            NodeKind::Shop => {
                self.stock_shop(card_pool, relic_pool)?;
                // §271：`meal_ticket` —— "Whenever you enter a shop, heal 15 HP"。
                // 与 `Eternal Feather` 同一条规矩：**进门就付**，不是"买了东西才付"。
                if let Some(RelicEffect::ShopEntryHeal(amount)) =
                    self.first_relic_effect_of(RelicEffect::ShopEntryHeal(15))
                {
                    self.heal_after_combat(amount);
                }
                Pending::Shop
            }''',
                '''            NodeKind::Shop => {
                // §273：与 `?` 房掷出商人时**同一条路**（摆货架 + `meal_ticket`）。
                self.enter_shop(card_pool, relic_pool)?;
                Pending::Shop
            }''', 'shop node branch')

    # ---- ③ `?` 房掷出商人：走共享入口（这是 §272 的真缺口）
    src = patch(src, '''                    UnknownRoom::Shop => {
                        self.stock_shop(card_pool, relic_pool)?;
                        Pending::Shop
                    }''',
                '''                    UnknownRoom::Shop => {
                        // §273：**同一个** `enter_shop` —— `?` 房变成商店也要触发 `meal_ticket`
                        // （wiki 的 Planisphere 页：*"a ? that turns into a shop triggers both"*）。
                        self.enter_shop(card_pool, relic_pool)?;
                        Pending::Shop
                    }''', 'unknown shop branch')

    # ---- ④ 新变体
    src = patch(src, '''    /// §272：`juzu_bracelet` —— `?` 房不再出**普通**战斗''',
                '''    /// §273：`the_courier` —— 商人**补货**（买走一格就补一格）。
    CourierRestock,
    /// §272：`juzu_bracelet` —— `?` 房不再出**普通**战斗''', 'variant')

    # ---- ⑤ 遗物行
    src = patch(src, '''            // §272：`?` 房分流的两件（规则在 `roll_unknown_room` 里）。''',
                '''            // §273：`the_courier` —— 两个半：-20% 折扣（`ShopDiscountPercent`）+ 买完补货。
            "the_courier" => Some(RelicEffect::ShopDiscountPercent(20)),
            // §272：`?` 房分流的两件（规则在 `roll_unknown_room` 里）。''', 'row')

    # ---- ⑥ 第二半表 +1（补货那一半）
    src = patch(src, '''const RELIC_SECOND_HALVES: [(&str, RelicEffect); 3] = [''',
                '''const RELIC_SECOND_HALVES: [(&str, RelicEffect); 4] = [''', 'second halves len')
    src = patch(src, '''    ("sozu", RelicEffect::StartCombatStatus("standard.sozu", 1)),
];''',
                '''    ("sozu", RelicEffect::StartCombatStatus("standard.sozu", 1)),
    // §273：`the_courier` 的第一半是 -20%（`ShopDiscountPercent`），第二半是"买完补货"。
    ("the_courier", RelicEffect::CourierRestock),
];''', 'second halves entry')

    # ---- ⑦ buy_card / buy_relic：补货
    src = patch(src, '''        self.push_card(card)?;
        self.adjust_gold(-self.shop_price(offer.price));
        self.maw_bank_broken = true;
        self.shop.cards[slot].price = -1;
        Ok(())''',
                '''        self.push_card(card)?;
        self.adjust_gold(-self.shop_price(offer.price));
        self.maw_bank_broken = true;
        self.shop.cards[slot].price = -1;
        // §273：`the_courier` —— "The Merchant restocks cards, relics, and potions"：买走的那一格
        // **立刻补上**（而不是留空）。走 `RELIC_SECOND_HALVES` 的同一张表，所以"这件遗物有哪两半"
        // 仍然只有一处。
        if self.holds_relic("the_courier") {
            self.restock_card_slot(slot, card_pool)?;
        }
        Ok(())''', 'buy_card restock')

    src = patch(src, '''        self.adjust_gold(-self.shop_price(offer.price));
        // §270：`maw_bank` "No longer works when you spend any Gold at a shop"。
        self.maw_bank_broken = true;
        self.shop.relics[slot].price = -1;
        Ok(())''',
                '''        self.adjust_gold(-self.shop_price(offer.price));
        // §270：`maw_bank` "No longer works when you spend any Gold at a shop"。
        self.maw_bank_broken = true;
        self.shop.relics[slot].price = -1;
        // §273：`the_courier` 补货（同上）。
        if self.holds_relic("the_courier") {
            self.restock_relic_slot(slot, relic_pool)?;
        }
        Ok(())''', 'buy_relic restock')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs: enter_shop + the_courier')


main()
