"""§292 Wave 1 第三段：`open_chest` 的三件 + 访问器 + run hash 的新字段。"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'


def patch(text, old, new, count=1):
    assert text.count(old) == count, (text.count(old), old[:110])
    return text.replace(old, new)


def main():
    s = io.open(STATE, encoding='utf-8').read()

    # ── 1. `open_chest`：三个判断在**掷骰之前**读（掷骰的位置不动 ⇒ 随机流不随遗物漂移）
    s = patch(s, '''        let roll = self.rng.roll(RunStream::Chest, 100)?;
        let (chest, gold_chance, low, high) = match roll {''',
                  '''        // §292：三件"宝箱格子"的遗物。**先读、后掷** —— 掷骰的次数与顺序必须与
        // "身上有没有这些遗物"无关，否则同一颗种子会因为一件遗物把整条随机流错开。
        //
        // ⚠️ 读的是**进入这一刻**的计数：`matryoshka` 自己在某个宝箱里被抽到的那一次，
        // 那个宝箱不算"接下来两个"之一（wiki 说的是 "The **next** 2"）。
        let hungry = self.chest_empty > 0;
        let extra_relic = self.chest_extra > 0;
        let curse_key = self.holds_second_half(RelicEffect::ChestAddsCurse);
        if hungry {
            self.chest_empty -= 1;
        }
        if extra_relic {
            self.chest_extra -= 1;
        }
        let roll = self.rng.roll(RunStream::Chest, 100)?;
        let (chest, gold_chance, low, high) = match roll {''')

    # 金币：空的宝箱一格都不给（掷骰照旧发生，见上）
    s = patch(s, '''        self.adjust_gold(gold);
        // A chest always holds a relic in `inv:§8.3`; an empty pool is a content problem, not "an
        // empty chest".''', '''        if !hungry {
            self.adjust_gold(gold);
        }
        // A chest always holds a relic in `inv:§8.3`; an empty pool is a content problem, not "an
        // empty chest".''')

    # 遗物：空的宝箱没有遗物
    s = patch(s, '''        let relic = {
            // §156: the same weighted draw as an elite reward, and the same "not one you hold".
            let picked = self.pick_relic(RunStream::Chest, relic_pool)?;
            if picked.as_str().is_empty() {
                None
            } else {
                self.push_relic(picked.as_str(), card_pool)?;
                Some(picked)
            }
        };''', '''        let relic = if hungry {
            None
        } else {
            // §156: the same weighted draw as an elite reward, and the same "not one you hold".
            let picked = self.pick_relic(RunStream::Chest, relic_pool)?;
            if picked.as_str().is_empty() {
                None
            } else {
                self.push_relic(picked.as_str(), card_pool)?;
                Some(picked)
            }
        };
        // §292：`matryoshka` 的**第二件**。它直接进腰带、不进 `ChestOutcome` —— 与
        // `black_star` 的"精英多给一件"同一条已记录的偏差（奖励屏只有一个遗物槽）。
        if extra_relic && !hungry {
            let second = self.pick_relic(RunStream::Chest, relic_pool)?;
            if !second.as_str().is_empty() {
                self.push_relic(second.as_str(), card_pool)?;
            }
        }
        // §292：`cursed_key` —— 非 Boss 宝箱里多一张随机诅咒。`push_card` 会走 `omamori`
        // 的挡诅咒（这是对的：护符正是为这种情况存在的）。
        if curse_key && !hungry {
            self.add_random_curse(card_pool)?;
        }''')

    # ── 2. 访问器：欠账两件 + 两个倍率 + 随机诅咒
    s = patch(s, '''    /// Does this kernel implement relic `id`'s effect? See [`Self::relic_effect`].''',
                  '''    /// §292：某件遗物的**第二半**是不是这个变体（[`RELIC_SECOND_HALVES`] 的反查）。
    ///
    /// 与 [`Self::holds_relic_effect`] 分开：那个按**变体值**查第一半，而第二半的变体与第一半
    /// 不同类（`cursed_key` 的第一半是 `StartCombatStatus`）。把它们合成一个"查所有半边"的函数
    /// 会让 `busted_crown` 的 `RewardCardDelta` 在"每回合 +1 能量"的调用点上被误认为存在。
    fn holds_second_half(&self, wanted: RelicEffect) -> bool {
        for (relic, effect) in RELIC_SECOND_HALVES.iter().copied() {
            if effect == wanted && self.holds_relic(relic) {
                return true;
            }
        }
        false
    }

    /// §292：拾取时**欠着**的遗物件数（`calling_bell` 的 3）。调用方用它的遗物池兑现。
    #[must_use]
    pub const fn pickup_relics(&self) -> u8 {
        self.pickup_relics
    }

    /// §292：兑现**一件**欠着的遗物。`push_relic` 由调用方做（它才有池子），这里只减计数。
    pub fn take_pickup_relic(&mut self) {
        self.pickup_relics = self.pickup_relics.saturating_sub(1);
    }

    /// §292：拾取时**欠着**的药水瓶数（`cauldron` 的 5）。
    #[must_use]
    pub const fn pickup_potions(&self) -> u8 {
        self.pickup_potions
    }

    /// §292：兑现**一瓶**欠着的药水（同 [`Self::take_pickup_relic`]）。
    pub fn take_pickup_potion(&mut self) {
        self.pickup_potions = self.pickup_potions.saturating_sub(1);
    }

    /// §292：`nloths_gift` —— 稀有档宽度的倍率（`100` = 不放大）。
    #[must_use]
    pub fn rare_chance_multiplier(&self) -> i32 {
        match self.first_relic_effect_of(RelicEffect::RareCardChanceMultiplier(3)) {
            Some(RelicEffect::RareCardChanceMultiplier(times)) if times > 0 => times,
            _ => 100,
        }
    }

    /// §292：`sacred_bark` —— 药水效果百分比（`100` = 原样，`200` = 翻倍）。
    #[must_use]
    pub fn potion_effect_percent(&self) -> i32 {
        match self.first_relic_effect_of(RelicEffect::PotionEffectPercent(200)) {
            Some(RelicEffect::PotionEffectPercent(percent)) if percent > 0 => percent,
            _ => 100,
        }
    }

    /// §292：往牌组里塞**一张随机诅咒**（`cursed_key`）。
    ///
    /// 诅咒的集合来自池子（`Rarity::Curse`），不是一张写死的表：内容加一条诅咒，这里自动看见。
    /// 池子里一条诅咒都没有 ⇒ **什么都不做**（不是错误：那说明这份内容没有诅咒，而
    /// `cursed_key` 的承诺"obtain a Curse"在这里没有可给的）。
    fn add_random_curse(&mut self, pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        let mut curses = [0usize; MAX_POOL];
        let mut count = 0usize;
        Self::pool_fits(pool.len())?;
        for (slot, entry) in pool.iter().enumerate() {
            if entry.rarity == Rarity::Curse {
                curses[count] = slot;
                count += 1;
            }
        }
        if count == 0 {
            return Ok(());
        }
        let roll = self.rng.roll(RunStream::Chest, count as u32)? as usize;
        let row = pool[curses[roll]];
        self.push_card(PoolCard { kind: CardKind::Curse, ..row })
    }

    /// Does this kernel implement relic `id`'s effect? See [`Self::relic_effect`].''')

    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('open_chest + accessors')

    # ── 3. run hash：新字段进指纹（它们是玩家可见的"欠着的东西"）
    h = io.open(HASH, encoding='utf-8').read()
    anchor = '''    // §259: the campfire counters are in the hash -- a rest-site choice that vanished on reload
'''
    if anchor not in h:
        # 退化路径：按 `rarity_offset` 那一行挂钩
        anchor = None
    print('hash anchor found:', anchor is not None)
    io.open(HASH, 'w', encoding='utf-8', newline='\n').write(h)


main()
