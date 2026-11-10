"""§338 商店价格与交易时序（审阅 1.1 / 1.2 / 1.3 + 复核 B1）。

## 三件事

### 1. `shop_price`：乘法叠加 + **一次**向上取整（1.2 / B1）

原来：`percent -= discount`（50 + 20 = 70 ⇒ 100 打 3 折），且 `base * percent / 100` 截断。
wiki 明文：`0.5 * 0.8 = 0.4` ⇒ **100 → 40**；奇数价**向上取整**（`101 * 0.5 = 50.5 → 51`）。

为什么"一次 ceil"而不是"每个折扣各 ceil 一次"：`107` 上两者不同 ——
`ceil(ceil(107*0.5)*0.8) = ceil(54*0.8) = ceil(43.2) = 44`，而 `ceil(107*0.4) = ceil(42.8) = 43`。
wiki 把公式写成 `0.5 * 0.8 = 0.4`（一次性 40%），所以按**有理数相乘、最后 ceil 一次**。
实现用 `i64` 的分子/分母，避免 `base * 4000` 在 i32 里溢出（base 最大约 200，乘 4000 才 80 万，
其实不会溢出；用 i64 是给"以后加第三件折扣遗物"留余量）。

### 2. 四类 `buy_*`：**先冻结实付价**，用它做校验、错误消息与扣款（1.1）

原来：`if self.gold < offer.price`（**挂牌价**）但 `adjust_gold(-self.shop_price(offer.price))`（**实付价**）。
持有 Membership Card、金币 60、货架 100 时，页面按 50 判断"买得起"（`rd_run_shop_card_price` 走的就是
`shop_price`），按钮是**启用的**，点下去却回 `NotEnoughGold { price: 100, gold: 60 }` ——
屏幕上写着 50、内核说 100 不够。

### 3. `due` 必须在 `push_*` **之前**冻结（1.3）

`buy_relic` 原来是 `push_relic(...)` 然后 `shop_price(...)`：买 **Membership Card 本身**时，
价格计算会看到**已经入库的**那件遗物 ⇒ 自己给自己打折。
wiki 的原话是 "**the rest of** the items in the same Shop … will benefit"，即自身不享受。

## 判据

见 `state.rs` 里新增的 `shop_discounts_stack_multiplicatively_and_round_up` 与
`every_purchase_charges_the_price_the_page_shows`。两条都**不**用生产函数生成预期值。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── 1. shop_price：乘法 + 一次 ceil ────────────────────────────────────────────
OLD_PRICE = '''    /// §270：商店的**实付价** —— 所有 `ShopDiscountPercent` 相加（`membership_card` 50%）。
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
    }'''

NEW_PRICE = '''    /// §270 / §338：商店的**实付价** —— 折扣**乘法叠加**，最后**向上取整一次**。
    ///
    /// ⚠️ 货架上存的是**挂牌价**（`roll_shop` 在陈列时就把 A16 的涨价算进去了，见那里的注释）。
    /// 折扣**只在付款时**算，所以"页面显示的数"与"真的扣的数"必须是**同一个函数** ——
    /// `rd_run_shop_card_price` / `rd_run_shop_relic_price` / `buy_*` / `remove_card_price`
    /// 全部走这里。两条路各算一次，就会变成"显示 45 扣 90"。
    ///
    /// # 为什么是乘法，不是加法（§338）
    ///
    /// wiki 的原文把公式写了出来：*"Having both this and Membership Card will reduce prices by a
    /// total 60%. (**0.5 * 0.8 = 0.4**) 40% price is a 60% reduction."* —— `100 → 40`，不是
    /// `100 - 50 - 20 = 30`。旧实现是加法，而**旧测试把这个错公式写成了规范**
    /// （`assert_eq!(shop_price(100), 30)`），所以只改实现不改测试会"修完反而红"。
    ///
    /// # 为什么只 ceil 一次
    ///
    /// wiki 另有一句：*"For prices which are an odd number before purchasing Membership Card, the
    /// new price will round **up**"*（`101 * 0.5 = 50.5 → 51`）。所以取整方向是 `ceil`，不是截断。
    /// 而"每个折扣各 ceil 一次"与"乘完只 ceil 一次"在 `107` 上会差 1：
    /// `ceil(ceil(107*0.5)*0.8) = 44`，`ceil(107*0.4) = 43`。wiki 把公式写成一次性的 `0.4`，
    /// 所以这里是**分子分母各自相乘、最后 ceil 一次**。
    ///
    /// ⚠️ 待核偏差：fandom 说 Courier 与 Membership Card 在**删卡服务**上"取更好的那一个折扣"
    /// （⇒ 50%），wiki.gg 说 Courier 对删卡"照常"生效（⇒ 40%）。两源互斥，单源不足以定规则，
    /// 所以这里**不**为删卡开特例，按统一公式算。见 `docs/port-plan.md` §338。
    #[must_use]
    pub fn shop_price(&self, base: i32) -> i32 {
        // 售罄哨兵（`-1`）不参与折扣：`-1` 必须原样穿过去。`.max(0)` 那版会把它变成 0，
        // 于是页面把卖掉的格子画成"0 金可买"（§276 在 ABI 那一侧也挡了一次，这里是第二道）。
        if base < 0 {
            return base;
        }
        let mut numerator = 1i64;
        let mut denominator = 1i64;
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::ShopDiscountPercent(discount)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                // `discount` 是"便宜多少个百分点"，所以留下的是 `100 - discount`。
                numerator *= i64::from(100 - discount.clamp(0, 100));
                denominator *= 100;
            }
        }
        if denominator == 1 {
            return base;
        }
        let scaled = i64::from(base) * numerator;
        // ceil：`(a + b - 1) / b`，全为正数，不需要处理负数分支。
        ((scaled + denominator - 1) / denominator) as i32
    }'''

t = sub(t, OLD_PRICE, NEW_PRICE, 'shop_price')

# ── 2/3. 四类 buy_*：due 先冻结 ───────────────────────────────────────────────
OLD_CARD = '''        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        if self.gold < offer.price {
            return Err(RunError::NotEnoughGold {
                price: offer.price,
                gold: self.gold,
            });
        }
        // §160: **提交点只有一个，而且失败的那一半在前面。**'''

NEW_CARD = '''        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        // §338：**实付价在这里冻结一次**，校验 / 错误消息 / 扣款全用它。
        //
        // 三件事都靠这一行：
        // ① 校验用挂牌价、扣款用折后价 ⇒ 页面按折后价启用按钮、内核按挂牌价拒绝（审阅 1.1）；
        // ② 错误消息里报的数必须与屏幕上的数相同，否则玩家看到"50 买不起，你有 60"；
        // ③ 冻结发生在任何 `push_*` **之前** ⇒ 买 Membership Card 本身不打折（审阅 1.3）。
        let due = self.shop_price(offer.price);
        if self.gold < due {
            return Err(RunError::NotEnoughGold {
                price: due,
                gold: self.gold,
            });
        }
        // §160: **提交点只有一个，而且失败的那一半在前面。**'''
t = sub(t, OLD_CARD, NEW_CARD, 'buy_card check')

t = sub(t, '''        self.push_card(card)?;
        self.adjust_gold(-self.shop_price(offer.price));''',
        '''        self.push_card(card)?;
        self.adjust_gold(-due);''', 'buy_card charge')

# buy_relic
OLD_RELIC = '''        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        if self.gold < offer.price {
            return Err(RunError::NotEnoughGold {
                price: offer.price,
                gold: self.gold,
            });
        }
        // §160: the same commit-point rule as `buy_card` -- the failing half must come first.
        self.push_relic(offer.id.as_str(), card_pool)?;
        self.adjust_gold(-self.shop_price(offer.price));'''

NEW_RELIC = '''        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        // §338：与 `buy_card` 同一个 `due` 纪律，而且这里**必须**先冻结 ——
        // `push_relic` 之后 `shop_price` 会看到刚入库的那件遗物：买 `membership_card`
        // 时它给自己打 5 折，而 wiki 的原话是 "**the rest of** the items … will benefit"。
        let due = self.shop_price(offer.price);
        if self.gold < due {
            return Err(RunError::NotEnoughGold {
                price: due,
                gold: self.gold,
            });
        }
        // §160: the same commit-point rule as `buy_card` -- the failing half must come first.
        self.push_relic(offer.id.as_str(), card_pool)?;
        self.adjust_gold(-due);'''

t = sub(t, OLD_RELIC, NEW_RELIC, 'buy_relic')

# buy_colorless
OLD_COLORLESS = '''        if offer.price < 0 {
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
        self.adjust_gold(-self.shop_price(offer.price));'''

NEW_COLORLESS = '''        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        // §338：同一个 `due` 纪律（校验 / 消息 / 扣款三处一个数）。
        let due = self.shop_price(offer.price);
        if self.gold < due {
            return Err(RunError::NotEnoughGold {
                price: due,
                gold: self.gold,
            });
        }
        let Some(row) = card_pool.iter().find(|card| card.id == offer.id.as_str()).copied()
        else {
            return Err(RunError::NoSuchCard);
        };
        self.push_card(row)?;
        self.adjust_gold(-due);'''

t = sub(t, OLD_COLORLESS, NEW_COLORLESS, 'buy_colorless')

# buy_potion
OLD_POTION = '''        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        if self.gold < offer.price {
            return Err(RunError::NotEnoughGold {
                price: offer.price,
                gold: self.gold,
            });
        }
        self.push_potion(offer.id.as_str())?;
        self.adjust_gold(-self.shop_price(offer.price));'''

NEW_POTION = '''        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        // §338：同一个 `due` 纪律。
        let due = self.shop_price(offer.price);
        if self.gold < due {
            return Err(RunError::NotEnoughGold {
                price: due,
                gold: self.gold,
            });
        }
        self.push_potion(offer.id.as_str())?;
        self.adjust_gold(-due);'''

t = sub(t, OLD_POTION, NEW_POTION, 'buy_potion')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('state.rs: shop_price multiplicative+ceil, buy_* frozen due')
