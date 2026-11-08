"""§292 Wave 1 收尾：`Rarity::Shop` + 商店货架来源 + 两个 accessor + 判据（**插在 `mod tests` 末尾**）。

⚠️ 判据块必须插在模块**末尾**：上一轮插在 `#[test]` 与 `fn` 之间，于是那个函数**编译、跑零次**
（§3b 的老坑，这一轮又踩了一次）。末尾插法不可能把属性与函数分开。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
TESTS_FILE = 'D:/Vibe/sts-tui/native/p292_tests.rs.txt'


def patch(text, old, new, count=1):
    assert text.count(old) == count, (text.count(old), old[:100])
    return text.replace(old, new)


def main():
    s = io.open(STATE, encoding='utf-8').read()

    # ── 1. `Rarity::Shop`
    s = patch(s, '''    /// See [`Self::Starter`].
    Boss = 9,''', '''    /// See [`Self::Starter`].
    Boss = 9,
    /// §292：wiki 的 `Shop` 桶（`cauldron` / `dollys_mirror` / `membership_card` … 共 14 件）。
    ///
    /// ⚠️ **这个桶此前不存在**，于是内容里 `Rarity: "Shop"` 的行在 [`Self::from_name`] 里
    /// 解析成 `None`、整条被 `relic_pool` 丢掉 —— `membership_card` 因此**永远拿不到**，
    /// 而没有任何闸门会红（"池子里没有它"看起来就像"这件遗物是事件专属"）。
    ///
    /// 它同样**不在** `RELIC_RARITY_WEIGHTS` 里（宝箱/精英奖励抽不到），唯一来源是商店货架
    /// （`pick_shop_relic_avoiding`，按 Rare 档计权与计价 —— 见那里的注释）。
    Shop = 10,''')

    s = patch(s, '''            "Boss" => Some(Self::Boss),
            _ => None,''', '''            "Boss" => Some(Self::Boss),
            // §292
            "Shop" => Some(Self::Shop),
            _ => None,''')

    s = patch(s, '''        | Rarity::Starter
        | Rarity::Boss => (45, 55),''', '''        | Rarity::Starter
        // §292：`Shop` 同样是**遗物**的桶（`cauldron` 那一批），牌不可能带着它。
        | Rarity::Shop
        | Rarity::Boss => (45, 55),''')

    s = patch(s, '''        Rarity::Starter => 9,
        Rarity::Boss => 10,
    }''', '''        Rarity::Starter => 9,
        Rarity::Boss => 10,
        // §292
        Rarity::Shop => 11,
    }''')
    s = patch(s, '''        10 => Rarity::Boss,
        _ => Rarity::Common,''', '''        10 => Rarity::Boss,
        // §292
        11 => Rarity::Shop,
        _ => Rarity::Common,''')

    # ── 2. 商店货架也能卖 Shop 档
    s = patch(s, '''        for slot in 0..MAX_SHOP_RELICS {
            let picked = self.pick_relic_avoiding(
                RunStream::Shop,
                relic_pool,
                &shelved[..slot],
            )?;''', '''        for slot in 0..MAX_SHOP_RELICS {
            // §292：商店还要卖 **Shop 稀有度** 的那批（`cauldron` / `dollys_mirror` / …）。
            let picked = self.pick_shop_relic_avoiding(
                RunStream::Shop,
                relic_pool,
                &shelved[..slot],
            )?;''')

    s = patch(s, '''    /// [`Self::pick_relic`] 的实体：`forced` = 锁定档位（`None` = 按权重掷）。''',
                 '''    /// §292：商店的遗物抽样 —— 与 [`Self::pick_relic`] 同一条权重路，但候选集是
    /// **可掉落三档 ∪ `Shop` 档**。
    ///
    /// 为什么需要它：`Shop` 稀有度（wiki 的 14 件）不在 `RELIC_RARITY_WEIGHTS` 里，所以
    /// `pick_relic` 永远抽不到它 —— 而"商人卖的遗物"正是它们**唯一**的来源。§292 之前
    /// 内容里的 `membership_card` 就因此**永远拿不到**（没有任何闸门会红）。
    ///
    /// ⚠️ `Shop` 档按 **Rare** 的档位计权：wiki 只给了商店价（143–157，不看稀有度），
    /// 没说"Shop 档该多常见" —— 这个数是**模型**，不是 wiki 的数字。
    fn pick_shop_relic_avoiding(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
    ) -> Result<RunId, RunError> {
        self.pick_relic_inner_with(stream, pool, reserved, None, true)
    }

    /// [`Self::pick_relic`] 的实体：`forced` = 锁定档位（`None` = 按权重掷）。''')

    s = patch(s, '''    fn pick_relic_inner(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
        forced: Option<Rarity>,
    ) -> Result<RunId, RunError> {''', '''    fn pick_relic_inner(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
        forced: Option<Rarity>,
    ) -> Result<RunId, RunError> {
        self.pick_relic_inner_with(stream, pool, reserved, forced, false)
    }

    /// 实体：`allow_shop` = 候选集里要不要让 `Shop` 档也进来（商店货架要，宝箱/精英奖励不要）。
    fn pick_relic_inner_with(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
        forced: Option<Rarity>,
        allow_shop: bool,
    ) -> Result<RunId, RunError> {''')

    s = patch(s, '''        for (slot, entry) in pool.iter().enumerate() {
            if !Self::relic_rarity_is_droppable(entry.rarity) {
                continue;
            }''', '''        for (slot, entry) in pool.iter().enumerate() {
            let shoppable = allow_shop && entry.rarity == Rarity::Shop;
            if !Self::relic_rarity_is_droppable(entry.rarity) && !shoppable {
                continue;
            }''')

    s = patch(s, '''            candidates[count] = slot;
            rarities[count] = entry.rarity;
            count += 1;''', '''            candidates[count] = slot;
            // §292：`Shop` 档按 **Rare** 档计权（见 `pick_shop_relic_avoiding`）。
            rarities[count] = if entry.rarity == Rarity::Shop {
                Rarity::Rare
            } else {
                entry.rarity
            };
            count += 1;''')

    # ── 3. 两个 accessor
    s = patch(s, '''    /// §292：拾取时**欠着**的遗物件数（`calling_bell` 的 3）。调用方用它的遗物池兑现。''',
                 '''    /// §292：还剩几个非 Boss 宝箱会给两件遗物（`matryoshka` 的 2）。
    #[must_use]
    pub const fn chest_extra_remaining(&self) -> u8 {
        self.chest_extra
    }

    /// §292：还剩几个非 Boss 宝箱是空的（`nloths_hungry_face` 的 1）。
    #[must_use]
    pub const fn chest_empty_remaining(&self) -> u8 {
        self.chest_empty
    }

    /// §292：拾取时**欠着**的遗物件数（`calling_bell` 的 3）。调用方用它的遗物池兑换。''')

    # ── 4. 判据：插在 `mod tests` 的**最后**（模块收尾的 `}` 之前）
    tests = io.open(TESTS_FILE, encoding='utf-8').read()
    marker = '\n#[cfg(test)]\nmod tests {'
    assert s.count(marker) == 1, s.count(marker)
    tail_start = s.index(marker)
    tail = s[tail_start:]
    # 模块的收尾 `}` 是文件最后一个 `\n}`。
    assert tail.rstrip('\n').endswith('}'), tail[-40:]
    cut = s.rstrip('\n').rfind('\n}')
    s = s[:cut] + '\n' + tests + s[cut:]

    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('shop + accessors + tests at module end')


main()
