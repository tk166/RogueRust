"""§332 商店三排：**无色货架** + **药水货架** + 遗物货架的价目/档位。

wiki（`slaythespire.wiki.gg/wiki/The_Merchant`，与 fandom 一致）的商店是五排：

| 排 | 内容 | 价格 |
|---|---|---|
| **5 张有色卡** | 永远 **2 攻 / 2 技 / 1 能力**；**随机一张 5 折** | Common 45-55、Uncommon 68-83、Rare 135-165 |
| **2 张无色卡** | 永远 **1 张 Uncommon + 1 张 Rare**；无色**贵 20%** | 81-99 / 162-198 |
| **3 瓶药水** | 稀有度权重 **65 / 25 / 10** | 48-53 / 71-79 / 95-105 |
| **3 件遗物** | **最右那一格永远是 `Shop` 档** | Shop/Common 143-158、Uncommon 238-263、Rare 285-315 |
| 删卡服务 | 每店一次 | 75 起、每次 +25（`smiling_mask` 固定 50） |

现状（§332 之前）：只有"5 张卡（**任意**池子，含无色）+ 3 件遗物（**一律** 143-157）"，
药水与无色**完全没有**，删卡服务是全的。

这一节做三件事：

1. **无色货架**：2 张（1 Uncommon + 1 Rare），价格用 wiki 的两段（贵 20%）；
2. **药水货架**：3 瓶，65/25/10 权重 + 三档价目；
3. **遗物货架**：最右一格锁 `Shop` 档，价格按**稀有度**（原来一律按 Common 收，稀有遗物卖白菜价）；
   有色卡那排也按 wiki 的 **2/2/1** 构成取，并且**随机一张 5 折**。

⚠️ 有色卡那排**必须排除无色牌**：`full_pool` 里两者混在一起，而"无色牌也能出现在有色格里"
会让无色货架看起来只是"多两格"。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── 1. 常量与价目 ─────────────────────────────────────────────────────────────
t = sub(t, """pub const MAX_SHOP_RELICS: usize = 3;""",
        """pub const MAX_SHOP_RELICS: usize = 3;
/// §332：无色货架**两格**（wiki：一张 Uncommon + 一张 Rare）。
pub const MAX_SHOP_COLORLESS: usize = 2;
/// §332：药水货架**三格**。
pub const MAX_SHOP_POTIONS: usize = 3;

/// §332：无色牌的价目（wiki：*"Colorless cards cost 20% more than normal cards"*）。
///
/// 直接写 wiki 的两段而不是"基础价 ×1.2 再取整"：`68..=82` ×1.2 = `81.6..=98.4`，而 wiki 写
/// `81-99` —— 取整规则（下取上取各一处）会让两个来源对不上，而这两段是**抄来的定值**。
pub const fn colorless_price_band(rarity: Rarity) -> (i32, i32) {
    match rarity {
        Rarity::Rare => (162, 198),
        // 其余一律 Uncommon 档：无色池只有 Uncommon / Rare 两档，走到这里说明池子被喂了别的。
        _ => (81, 99),
    }
}

/// §332：药水价目（wiki：Common 48-53、Uncommon 71-79、Rare 95-105）。
pub const fn potion_price_band(rarity: Rarity) -> (i32, i32) {
    match rarity {
        Rarity::Rare => (95, 105),
        Rarity::Uncommon => (71, 79),
        _ => (48, 53),
    }
}

/// §332：遗物价目（wiki：Shop/Common 143-158、Uncommon 238-263、Rare 285-315）。
///
/// ⚠️ 这条修的是一个**经济偏差**：原来三格一律 `143 + roll(15)`，于是稀有遗物（285-315）
/// 和普通遗物一个价 —— 玩家在商店里永远优先买稀有，而那让商店的稀有度权重失去意义。
pub const fn relic_price_band(rarity: Rarity) -> (i32, i32) {
    match rarity {
        Rarity::Rare => (285, 315),
        Rarity::Uncommon => (238, 263),
        // `Shop` 与 `Common` 同价（wiki 的两行是同一个区间）。
        _ => (143, 158),
    }
}""",
        'constants')

# ── 2. ShopStock 两个新排 ─────────────────────────────────────────────────────
t = sub(t, """pub struct ShopStock {
    cards: [Offer; MAX_SHOP_CARDS],
    cards_len: u8,
    relics: [Offer; MAX_SHOP_RELICS],
    relics_len: u8,
}""",
        """pub struct ShopStock {
    cards: [Offer; MAX_SHOP_CARDS],
    cards_len: u8,
    /// §332：无色货架（1 Uncommon + 1 Rare）。
    colorless: [Offer; MAX_SHOP_COLORLESS],
    colorless_len: u8,
    /// §332：药水货架（3 瓶，65/25/10）。
    potions: [Offer; MAX_SHOP_POTIONS],
    potions_len: u8,
    relics: [Offer; MAX_SHOP_RELICS],
    relics_len: u8,
}""",
        'stock struct')

t = sub(t, """        Self {
            cards: [Offer::EMPTY; MAX_SHOP_CARDS],
            cards_len: 0,
            relics: [Offer::EMPTY; MAX_SHOP_RELICS],
            relics_len: 0,
        }""",
        """        Self {
            cards: [Offer::EMPTY; MAX_SHOP_CARDS],
            cards_len: 0,
            colorless: [Offer::EMPTY; MAX_SHOP_COLORLESS],
            colorless_len: 0,
            potions: [Offer::EMPTY; MAX_SHOP_POTIONS],
            potions_len: 0,
            relics: [Offer::EMPTY; MAX_SHOP_RELICS],
            relics_len: 0,
        }""",
        'stock empty')

t = sub(t, """    /// The relic offers.
    #[must_use]
    pub fn relics(&self) -> &[Offer] {
        &self.relics[..self.relics_len as usize]
    }""",
        """    /// §332：无色货架的报价。
    #[must_use]
    pub fn colorless(&self) -> &[Offer] {
        &self.colorless[..self.colorless_len as usize]
    }

    /// §332：药水货架的报价。
    #[must_use]
    pub fn potions(&self) -> &[Offer] {
        &self.potions[..self.potions_len as usize]
    }

    /// The relic offers.
    #[must_use]
    pub fn relics(&self) -> &[Offer] {
        &self.relics[..self.relics_len as usize]
    }""",
        'accessors')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-run: constants + ShopStock shelves')
