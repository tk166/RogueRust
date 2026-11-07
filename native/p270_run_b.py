"""§270 第二批：调用点迁移 + `adjust_gold` + 价格折扣 + 爬层金币 + `push_relic` 的 omamori。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def main():
    src = io.open(P, encoding='utf-8').read()

    # ---- ① 开场牌组 / Ascender's Bane
    src = patch(src, '            state.push_card(id)?;',
                '            state.push_card(PoolCard::plain(id))?;', 'starting deck')
    src = patch(src, '            state.push_card(ASCENDERS_BANE)?;',
                '            // Ascender\'s Bane 是**诅咒**：类型要写对，否则 `omamori` 将来拦不住它。\n'
                '            state.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain(ASCENDERS_BANE) })?;',
                'ascenders bane')

    # ---- ② 事件：从池子里随机加牌
    src = patch(src, '''            let id = pool[eligible[picked]].id;
            self.push_card(id)?;''',
                '''            let card = pool[eligible[picked]];
            self.push_card(card)?;''', 'event random card')

    # ---- ③ 事件的 `curse:` 载荷
    src = patch(src, '''                self.push_card(id)?;
            }
            EventEffect::GainRelic => {''',
                '''                // `curse:` 载荷按定义就是诅咒（上面刚验过池子里它是 `Rarity::Curse`）。
                self.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain(id) })?;
            }
            EventEffect::GainRelic => {''', 'event curse')

    # ---- ④ take_card / buy_card 签名
    src = patch(src, '''    pub fn take_card(&mut self, slot: usize) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let Some(id) = self.reward.cards().get(slot).copied() else {
            return Err(RunError::EmptyOffer(slot as u8));
        };
        if id == RunId::EMPTY {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        self.push_card(id.as_str())?;''',
                '''    /// §270：`card` 是**这一屏那一张牌**（由调用方从内容里带过来 —— 运行层不存内容）。
    ///
    /// 两个来源必须对得上：调用方说"我拿的是 X"、屏幕上也写着 X。对不上就是调用方的错
    /// （拿了第 2 张的 id 去填第 1 个槽，页面上会变成"点了 1 拿走了 3"），所以这里**拒绝**。
    pub fn take_card(&mut self, slot: usize, card: PoolCard<'_>) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let Some(id) = self.reward.cards().get(slot).copied() else {
            return Err(RunError::EmptyOffer(slot as u8));
        };
        if id == RunId::EMPTY {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        if card.id != id.as_str() {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        self.push_card(card)?;''', 'take_card')

    src = patch(src, '''    pub fn buy_card(&mut self, slot: usize) -> Result<(), RunError> {''',
                '''    pub fn buy_card(&mut self, slot: usize, card: PoolCard<'_>) -> Result<(), RunError> {''',
                'buy_card sig')

    src = patch(src, '''        // 不会失败）。REVIEW 的 P0，判据是 `a_refused_purchase_leaves_the_run_untouched`。
        self.push_card(offer.id.as_str())?;
        self.adjust_gold(-offer.price);''',
                '''        // 不会失败）。REVIEW 的 P0，判据是 `a_refused_purchase_leaves_the_run_untouched`。
        // §270：同上，调用方带来的牌必须**就是**货架上那一张。
        if card.id != offer.id.as_str() {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        self.push_card(card)?;
        self.adjust_gold(-self.shop_price(offer.price));
        self.maw_bank_broken = true;''', 'buy_card body')

    # ---- ⑤ buy_relic：折扣 + maw_bank 失效
    src = patch(src, '''        // §160: the same commit-point rule as `buy_card` -- the failing half must come first.
        self.push_relic(offer.id.as_str())?;
        self.adjust_gold(-offer.price);
        self.shop.relics[slot].price = -1;
        Ok(())''',
                '''        // §160: the same commit-point rule as `buy_card` -- the failing half must come first.
        self.push_relic(offer.id.as_str())?;
        self.adjust_gold(-self.shop_price(offer.price));
        // §270：`maw_bank` "No longer works when you spend any Gold at a shop"。
        self.maw_bank_broken = true;
        self.shop.relics[slot].price = -1;
        Ok(())''', 'buy_relic body')

    # ---- ⑥ remove_card：折扣 + maw_bank 失效
    src = patch(src, '''        self.remove_deck_card(card)?;
        self.adjust_gold(-price);''',
                '''        self.remove_deck_card(card)?;
        self.adjust_gold(-price);
        // §270：删牌也是"在商店花钱"。
        self.maw_bank_broken = true;''', 'remove_card body')

    # ---- ⑦ 删牌价格：smiling_mask 固定 50，再打折
    src = patch(src, '''    pub const fn remove_card_price(&self) -> i32 {
        // §159 `A16`: the removal service is a shop price too, so it carries the same markup.
        self.marked_up(SHOP_REMOVE_BASE + SHOP_REMOVE_STEP * self.removed_cards)
    }''',
                '''    /// §270：删牌服务的价格**现算**（三项各自独立：升阶涨价、`smiling_mask` 固定价、商店折扣）。
    ///
    /// ⚠️ 不再是 `const fn`：`smiling_mask` 要看遗物表。调用点（商店页与 `remove_card`）都是普通
    /// 函数，所以没有传播成本。
    #[must_use]
    pub fn remove_card_price(&self) -> i32 {
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
    }

    /// §270：商店的**实付价** —— 所有 `ShopDiscountPercent` 相加（`membership_card` 50%）。
    ///
    /// ⚠️ 货架上存的是**挂牌价**（`roll_shop` 在陈列时就把 A16 的涨价算进去了，见那里的注释）。
    /// 折扣**只在付款时**算，所以"页面显示的数"与"真的扣的数"必须是**同一个函数** ——
    /// `rd_run_shop_card_price` / `rd_run_shop_relic_price` / `buy_*` / `remove_card_price`
    /// 全部走这里。两条路各算一次，就会变成"显示 45 扣 90"。
    #[must_use]
    pub fn shop_price(&self, base: i32) -> i32 {
        let mut percent = 100i32;
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::ShopDiscountPercent(discount)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                percent -= discount;
            }
        }
        (base * percent / 100).max(0)
    }''', 'remove price + shop_price')

    # ---- ⑧ adjust_gold：ectoplasm 拦截 + bloody_idol 回血
    src = patch(src, '''    pub fn adjust_gold(&mut self, delta: i32) {
        self.gold = (self.gold + delta).max(0);
    }''',
                '''    /// §270：**唯一**改金币的地方 —— 所以两条"金币方向"的遗物都挂在这里。
    ///
    /// | 遗物 | 规则 | 落点 |
    /// |---|---|---|
    /// | `ectoplasm` | "You can no longer gain Gold" | 正增量变 0（**花出去**不受影响） |
    /// | `bloody_idol` | "Whenever you gain Gold, heal 5 HP" | 金币**真的**涨了才回血 |
    ///
    /// ⚠️ `bloody_idol` 判的是**实际涨了多少**（`self.gold` 前后的差），不是 `delta > 0`：
    /// 否则 `ectoplasm` 挡住的那一笔也会回血 —— 玩家没得到金币却回了 5 点血，
    /// 而这条在页面上完全看不出来（两个数字各自都"合理"）。
    pub fn adjust_gold(&mut self, delta: i32) {
        let delta = if delta > 0 && self.holds_relic_effect(RelicEffect::NoGoldGain) {
            0
        } else {
            delta
        };
        let before = self.gold;
        self.gold = (self.gold + delta).max(0);
        let gained = self.gold - before;
        if gained > 0 {
            if let Some(RelicEffect::GoldGainHeal(amount)) =
                self.first_relic_effect_of(RelicEffect::GoldGainHeal(5))
            {
                self.heal_after_combat(amount);
            }
        }
    }''', 'adjust_gold')

    # ---- ⑨ enter_node：maw_bank 爬层金币
    src = patch(src, '''        self.node = probe.node;
        self.floor = probe.floor;
        self.check_invariants()''',
                '''        let climbed = probe.floor > self.floor;
        self.node = probe.node;
        self.floor = probe.floor;
        // §270：`maw_bank` —— "Whenever you climb a floor, gain 12 Gold"。
        // 判据是**楼层涨了**（`climbed`），不是"进了一个节点"：Boss 节点（第 16 层）与普通节点
        // 走的是同一条路，而"重进当前层"是不可能的（`reachable` 只给下层）。
        if climbed && !self.maw_bank_broken {
            if let Some(RelicEffect::FloorClimbGold(amount)) =
                self.first_relic_effect_of(RelicEffect::FloorClimbGold(12))
            {
                self.adjust_gold(amount);
            }
        }
        self.check_invariants()''', 'enter_node maw_bank')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('state.rs: call sites + gold/price/floor')


main()
