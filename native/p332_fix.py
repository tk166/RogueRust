"""§332 修判据的**独立性**，并把"Shop 档只出现在最右"这条 wiki 规则做对。

两个问题（负控抓出来的）：

1. **判据自证**：四条价目断言用 `colorless_price_band(...)` / `relic_price_band(...)` 去算
   期望区间，而那两个函数正是被测对象 —— 改坏它，判据跟着改坏，照样绿。
   ⇒ 补一组**字面量**断言（wiki 的数字），那是独立的那一份。
2. **`Shop` 档不只在最右**：wiki 说 *"The rightmost slot will always be a Shop Relic.
   **This is the only way to access Shop relics.**"* —— 所以前两格**不能**出 Shop 档。
   原来三格都 `allow_shop = true`，于是 Shop 遗物可能落在任意一格（"只有最右"就不成立了）。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── 1. 前两格排除 Shop 档 ─────────────────────────────────────────────────────
t = sub(t, """    fn pick_shop_relic_avoiding(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
    ) -> Result<RunId, RunError> {
        self.pick_relic_inner_with(stream, pool, reserved, None, true)
    }""",
        """    fn pick_shop_relic_avoiding(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
    ) -> Result<RunId, RunError> {
        self.pick_relic_inner_with(stream, pool, reserved, None, true)
    }

    /// §332：商店的**前三格**（最右之外）—— **不许出 `Shop` 档**。
    ///
    /// wiki：*"The rightmost slot will always be a Shop Relic. **This is the only way to access
    /// Shop relics.**"* —— 所以 `Shop` 档只走最右那一格（`pick_shop_relic_of_rarity`）。
    fn pick_shop_relic_no_shop(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
    ) -> Result<RunId, RunError> {
        self.pick_relic_inner_with(stream, pool, reserved, None, false)
    }""",
        'no-shop helper')

t = sub(t, """                if found {
                    forced
                } else {
                    self.pick_shop_relic_avoiding(RunStream::Shop, relic_pool, &shelved[..slot])?
                }
            } else {
                self.pick_shop_relic_avoiding(RunStream::Shop, relic_pool, &shelved[..slot])?
            };""",
        """                if found {
                    forced
                } else {
                    self.pick_shop_relic_no_shop(RunStream::Shop, relic_pool, &shelved[..slot])?
                }
            } else {
                // §332：前三格**排除** `Shop` 档（wiki：只有最右那一格能拿到 Shop 遗物）。
                self.pick_shop_relic_no_shop(RunStream::Shop, relic_pool, &shelved[..slot])?
            };""",
        'use no-shop')

# ── 2. 判据：补字面量（wiki 的数字），那是独立的一份 ───────────────────────────
t = sub(t, """        // ── 有色卡：5 张，2 攻 / 2 技 / 1 能力 ──────────────────────────────────""",
        """        // §332：**价目表的独立副本**。上面那些"落在区间里"的断言用的是同一个函数，
        // 所以它们只能证明"货架与函数一致"，证明不了"函数与 wiki 一致" —— 这两句才是。
        assert_eq!(colorless_price_band(Rarity::Uncommon), (81, 99), "wiki: 81-99");
        assert_eq!(colorless_price_band(Rarity::Rare), (162, 198), "wiki: 162-198");
        assert_eq!(potion_price_band(Rarity::Common), (48, 53), "wiki: 48-53");
        assert_eq!(potion_price_band(Rarity::Uncommon), (71, 79), "wiki: 71-79");
        assert_eq!(potion_price_band(Rarity::Rare), (95, 105), "wiki: 95-105");
        assert_eq!(relic_price_band(Rarity::Common), (143, 158), "wiki: 143-158");
        assert_eq!(relic_price_band(Rarity::Shop), (143, 158), "wiki: Shop = 143-158");
        assert_eq!(relic_price_band(Rarity::Uncommon), (238, 263), "wiki: 238-263");
        assert_eq!(relic_price_band(Rarity::Rare), (285, 315), "wiki: 285-315");

        // ── 有色卡：5 张，2 攻 / 2 技 / 1 能力 ──────────────────────────────────""",
        'literal bands')

# ── 3. 判据：前两格**不许**是 Shop 档 ────────────────────────────────────────
t = sub(t, """        assert_eq!(
            last_rarity,
            Rarity::Shop,
            "wiki: the rightmost slot is always a Shop relic (got {:?})",
            last.id.as_str()
        );""",
        """        assert_eq!(
            last_rarity,
            Rarity::Shop,
            "wiki: the rightmost slot is always a Shop relic (got {:?})",
            last.id.as_str()
        );
        // §332：**只有**最右那一格能出 `Shop` 档（wiki: "This is the only way to access Shop
        // relics"）。少了这一句，"三格都允许 Shop"照样绿 —— 而那样一来"最右必为 Shop"就没意义了。
        for offer in &relics[..relics.len() - 1] {
            let rarity = RELIC_POOL
                .iter()
                .find(|entry| entry.id == offer.id.as_str())
                .expect("from the pool")
                .rarity;
            assert_ne!(
                rarity,
                Rarity::Shop,
                "only the rightmost slot may hold a Shop relic (got {:?})",
                offer.id.as_str()
            );
        }""",
        'no shop elsewhere')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('state: shop-tier exclusion + independent bands')
