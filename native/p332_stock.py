"""§332（续）：`stock_shop` 按 wiki 的四排铺货 + `buy_potion`。

铺货顺序是**语义**：wiki 的构成（2/2/1、1+1、3、最右 Shop）决定"这一店有什么"，而
随机流的位置决定"是哪几张"。所以先把"哪些牌属于哪一类"分好，再各掷各的。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

OLD_STOCK = t[t.index("    fn stock_shop(&mut self, card_pool: &[PoolCard<'_>], relic_pool: &[PoolRelic<'_>]) -> Result<(), RunError> {"):]
OLD_STOCK = OLD_STOCK[:OLD_STOCK.index("\n    }\n") + len("\n    }\n")]

NEW_STOCK = '''    /// §332：按 wiki 的**四排**铺货。
    ///
    /// | 排 | 构成 | 价目 |
    /// |---|---|---|
    /// | 有色卡 5 | 2 攻 / 2 技 / 1 能力，**随机一张 5 折** | `card_price_band` |
    /// | 无色卡 2 | 1 Uncommon + 1 Rare | `colorless_price_band`（贵 20%） |
    /// | 药水 3 | 稀有度权重 65/25/10 | `potion_price_band` |
    /// | 遗物 3 | **最右一格锁 `Shop` 档**，其余按 50/33/17 | `relic_price_band` |
    ///
    /// ⚠️ 有色卡那排**排除无色牌**：`full_pool` 里两者混在一起，而"无色牌也能出现在有色格里"
    /// 会让无色货架看起来只是"多两格"，同时把 wiki 的 2/2/1 构成打乱。
    fn stock_shop(
        &mut self,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[PoolRelic<'_>],
        potion_pool: &[PoolPotion<'_>],
    ) -> Result<(), RunError> {
        if card_pool.is_empty() {
            return Err(RunError::EmptyPool("cards"));
        }
        Self::pool_fits(card_pool.len())?;
        self.shop = ShopStock::empty();

        // ── 有色卡：2 攻 / 2 技 / 1 能力 ────────────────────────────────────────
        // 先把"这一类有几张"数出来，再在**类内**洗牌取前 N 张 —— 分类是构成，洗牌是随机。
        let wanted = [(CardKind::Attack, 2usize), (CardKind::Skill, 2), (CardKind::Power, 1)];
        let mut shelved_cards = 0usize;
        for (kind, count) in wanted {
            let mut members = [0u8; MAX_POOL];
            let mut found = 0usize;
            for (index, card) in card_pool.iter().enumerate() {
                if card.colorless || card.kind != kind {
                    continue;
                }
                if found == MAX_POOL {
                    return Err(RunError::EmptyPool("cards"));
                }
                members[found] = index as u8;
                found += 1;
            }
            self.rng.shuffle(RunStream::Shop, &mut members[..found]);
            for slot in 0..count.min(found) {
                let card = card_pool[members[slot] as usize];
                let (low, high) = card_price_band(card.rarity);
                let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
                self.shop.cards[shelved_cards] = Offer {
                    id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
                    price: self.marked_up(price),
                };
                shelved_cards += 1;
                if shelved_cards == MAX_SHOP_CARDS {
                    break;
                }
            }
            if shelved_cards == MAX_SHOP_CARDS {
                break;
            }
        }
        // wiki: *"One random card will have a 50% discount applied."* —— 挂牌价直接减半，
        // 于是"页面显示的数"与"真的扣的数"仍然是同一个数（§270 的规矩）。
        if shelved_cards > 0 {
            let slot = self.rng.roll(RunStream::Shop, shelved_cards as u32)? as usize;
            self.shop.cards[slot].price = self.shop.cards[slot].price / 2;
        }
        self.shop.cards_len = shelved_cards as u8;

        // ── 无色卡：1 Uncommon + 1 Rare ─────────────────────────────────────────
        let mut colorless = 0usize;
        for rarity in [Rarity::Uncommon, Rarity::Rare] {
            let mut members = [0u8; MAX_POOL];
            let mut found = 0usize;
            for (index, card) in card_pool.iter().enumerate() {
                if !card.colorless || card.rarity != rarity {
                    continue;
                }
                if found == MAX_POOL {
                    return Err(RunError::EmptyPool("cards"));
                }
                members[found] = index as u8;
                found += 1;
            }
            if found == 0 {
                // 内容里没有这一档无色牌 ⇒ 这一格空着（不是错误：无色池是内容的事）。
                continue;
            }
            let pick = self.rng.roll(RunStream::Shop, found as u32)? as usize;
            let card = card_pool[members[pick] as usize];
            let (low, high) = colorless_price_band(card.rarity);
            let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
            self.shop.colorless[colorless] = Offer {
                id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
                price: self.marked_up(price),
            };
            colorless += 1;
        }
        self.shop.colorless_len = colorless as u8;

        // ── 药水：3 瓶，稀有度权重 65/25/10 ──────────────────────────────────────
        // `pick_potion` 已经按权重掷档位（`POTION_RARITY_WEIGHTS`），这里只补价目。
        // 三瓶**互不相同**：wiki 没有明说，但同一瓶摆三次是明显的重复（而且玩家会以为看错了）。
        let mut shelved_potions: [RunId; MAX_SHOP_POTIONS] = [RunId::EMPTY; MAX_SHOP_POTIONS];
        for slot in 0..MAX_SHOP_POTIONS {
            if potion_pool.is_empty() {
                break;
            }
            let picked = self.pick_potion_avoiding(potion_pool, &shelved_potions[..slot])?;
            if picked.as_str().is_empty() {
                break;
            }
            let rarity = potion_pool
                .iter()
                .find(|entry| entry.id == picked.as_str())
                .map_or(Rarity::Common, |entry| entry.rarity);
            let (low, high) = potion_price_band(rarity);
            let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
            self.shop.potions[slot] = Offer {
                id: picked,
                price: self.marked_up(price),
            };
            shelved_potions[slot] = picked;
            self.shop.potions_len = (slot + 1) as u8;
        }

        // ── 遗物：3 件，最右一格锁 `Shop` 档 ────────────────────────────────────
        // wiki: *"The rightmost slot will always be a Shop Relic."*
        let mut shelved: [RunId; MAX_SHOP_RELICS] = [RunId::EMPTY; MAX_SHOP_RELICS];
        for slot in 0..MAX_SHOP_RELICS {
            let last = slot + 1 == MAX_SHOP_RELICS;
            let picked = if last {
                // 最右：只在 `Shop` 档里挑；挑不到（内容没有 Shop 遗物了）就退回按权重。
                let mut found = false;
                let forced = self.pick_shop_relic_of_rarity(
                    RunStream::Shop,
                    relic_pool,
                    &shelved[..slot],
                    Rarity::Shop,
                )?;
                if !forced.as_str().is_empty() {
                    found = true;
                }
                if found {
                    forced
                } else {
                    self.pick_shop_relic_avoiding(RunStream::Shop, relic_pool, &shelved[..slot])?
                }
            } else {
                self.pick_shop_relic_avoiding(RunStream::Shop, relic_pool, &shelved[..slot])?
            };
            if picked.as_str().is_empty() {
                break;
            }
            let rarity = relic_pool
                .iter()
                .find(|entry| entry.id == picked.as_str())
                .map_or(Rarity::Common, |entry| entry.rarity);
            let (low, high) = relic_price_band(rarity);
            let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
            self.shop.relics[slot] = Offer {
                id: picked,
                price: self.marked_up(price),
            };
            shelved[slot] = picked;
            self.shop.relics_len = (slot + 1) as u8;
        }
        Ok(())
    }

    /// §332：在**指定稀有度**里挑一件遗物（`Shop` 货架最右那一格用）。
    ///
    /// 与 `pick_shop_relic_avoiding` 分开：那一个是"按权重掷档位"，这个是"档位已经定了"。
    /// 挑不到 ⇒ 空 id（调用方退回按权重），**不报错** —— 内容里没有 Shop 遗物不是运行层的错。
    fn pick_shop_relic_of_rarity(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
        rarity: Rarity,
    ) -> Result<RunId, RunError> {
        self.pick_relic_inner_with(stream, pool, reserved, Some(rarity), true)
    }

    /// §332：与 [`Self::pick_potion`] 相同，但跳过已经在货架上的那几瓶。
    fn pick_potion_avoiding(
        &mut self,
        pool: &[PoolPotion<'_>],
        reserved: &[RunId],
    ) -> Result<RunId, RunError> {
        let mut filtered = [PoolPotion {
            id: "",
            rarity: Rarity::Common,
        }; MAX_POOL];
        let mut count = 0usize;
        for entry in pool {
            if reserved.iter().any(|id| id.as_str() == entry.id) {
                continue;
            }
            if count == MAX_POOL {
                return Err(RunError::EmptyPool("potions"));
            }
            filtered[count] = *entry;
            count += 1;
        }
        if count == 0 {
            return Ok(RunId::EMPTY);
        }
        self.pick_potion(RunStream::Shop, &filtered[..count])
    }
'''

t = t.replace(OLD_STOCK, NEW_STOCK)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('stock_shop rewritten + helpers')
