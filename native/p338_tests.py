"""§338 判据：修掉固化错公式的旧断言，补两条新判据。

## 为什么必须先改测试

`the_courier_restocks_the_slot_it_sells` 里那句
`assert_eq!(run.shop_price(100), 30, "the two discounts add up (50 + 20)")`
**把错公式写成了规范** —— 只改实现不改它，修完反而红（而且看起来像"实现错了"）。
同类：`the_gold_and_shop_relics_change_only_their_own_number` 里的 `SHOP_REMOVE_BASE / 2`
（75/2 = 37，截断），wiki 说删卡服务是"每次 +12.5，**向上取整**" ⇒ 75 * 0.5 = 37.5 → **38**。

## 新判据两条

1. `shop_discounts_stack_multiplicatively_and_round_up` —— **字面量**断言（不用生产函数生成预期）：
   `100→50`（MC）、`100→80`（Courier）、`100→40`（两者）、`101→51`、`99→50`、`107→43`、`75→38`。
   `107` 那一格是"一次 ceil vs 每次 ceil"的分水岭（43 vs 44）。
2. `every_purchase_charges_the_price_the_page_shows` —— 四排货架各一次：
   `gold = due-1` 被拒且**错误里的数 == 页面显示的数**；`gold = due` 成交且金币归零；
   并且 `due < 挂牌价`（旧实现会因为"校验用挂牌价"而在 `due-1` 这一档就拒，`gold = due` 那档也拒）。
   外加一条"买 Membership Card 本身不打折"：挂牌 100、金币 100 ⇒ 成交、金币 0。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── ① 旧断言：加法 → 乘法 ─────────────────────────────────────────────────────
t = sub(t, '''        // ---- 折扣：20%（与 `membership_card` 的 50% 相加）。''',
        '''        // ---- 折扣：20%（与 `membership_card` 的 50% **相乘**，§338）。''', 'courier comment')
t = sub(t, '''        assert_eq!(run.shop_price(100), 30, "the two discounts add up (50 + 20)");''',
        '''        // §338：wiki 的公式是 `0.5 * 0.8 = 0.4` ⇒ 100 → 40（总折扣 60%），不是加法 30。
        // 这条断言原来写的是 30 —— **它把错公式写成了规范**，所以修实现时必须同时修它。
        assert_eq!(run.shop_price(100), 40, "the two discounts multiply (0.5 * 0.8 = 0.4)");''',
        'courier 30 -> 40')

# ── ② 删卡：截断 → 向上取整 ──────────────────────────────────────────────────
t = sub(t, '''        // ⚠️ `remove_card_price()` **本身已经**含折扣（它内部就调 `shop_price`），所以这里不能再
        // 套一层 —— 第一版套了，得到 18 而不是 37（"半价的半价"）。
        assert_eq!(
            run.remove_card_price(),
            SHOP_REMOVE_BASE / 2,
            "the removal service is a product too"
        );''',
        '''        // ⚠️ `remove_card_price()` **本身已经**含折扣（它内部就调 `shop_price`），所以这里不能再
        // 套一层 —— 第一版套了，得到 18 而不是 37（"半价的半价"）。
        // §338：取整方向是**向上**（wiki：删卡服务"每次 +12.5，rounded up"），
        // 所以 75 * 0.5 = 37.5 → 38，不是截断的 37。
        assert_eq!(
            run.remove_card_price(),
            (SHOP_REMOVE_BASE + 1) / 2,
            "the removal service is a product too, rounded up"
        );''',
        'remove price ceil')

# ── ③ 新增两条判据（插在 `a_discounted_purchase_charges_the_discounted_price` 之前）──
ANCHOR = '''    /// §270：一次**真的**购买 —— 折扣后的钱扣掉、`maw_bank` 从此失效。'''

NEW_TESTS = '''    /// §338：折扣**乘法叠加**，且最后**向上取整一次**。
    ///
    /// 全部是**字面量**：预期值不许用 `shop_price` 自己生成 —— 那样"公式错了"和"公式对了"
    /// 会一起绿（旧测试就是拿生产函数的加法结果当预期，于是加法被写成了规范）。
    ///
    /// 两处最容易写错的地方：
    /// * `107` 是"一次 ceil"与"每次 ceil"的分水岭：`ceil(107*0.4) = 43`，
    ///   而 `ceil(ceil(107*0.5)*0.8) = ceil(54*0.8) = 44`。wiki 把公式写成一次性的 `0.4`。
    /// * `101` 是 wiki 自己举的例子（`101 * 0.5 = 50.5 → 51`），奇数价**向上**而不是截断。
    #[test]
    fn shop_discounts_stack_multiplicatively_and_round_up() {
        let mut run = ironclad();
        assert_eq!(run.shop_price(100), 100, "no discount relic ⇒ the shelf price");
        assert_eq!(run.shop_price(-1), -1, "the sold-out sentinel must pass through");

        run.push_relic("membership_card", &TYPED_CARDS).expect("membership_card");
        assert_eq!(run.shop_price(100), 50, "membership_card: 50% off");
        assert_eq!(run.shop_price(101), 51, "odd prices round **up** (wiki's own example)");
        assert_eq!(run.shop_price(99), 50, "99 * 0.5 = 49.5 → 50");
        assert_eq!(
            run.shop_price(SHOP_REMOVE_BASE),
            38,
            "75 * 0.5 = 37.5 → 38 (the removal service rounds up too)"
        );

        let mut courier = ironclad();
        courier.push_relic("the_courier", &TYPED_CARDS).expect("the_courier");
        assert_eq!(courier.shop_price(100), 80, "the_courier: 20% off");

        let mut both = ironclad();
        both.push_relic("the_courier", &TYPED_CARDS).expect("the_courier");
        both.push_relic("membership_card", &TYPED_CARDS).expect("membership_card");
        assert_eq!(
            both.shop_price(100),
            40,
            "wiki: 0.5 * 0.8 = 0.4 ⇒ 40 (a 60% reduction, not 70%)"
        );
        assert_eq!(
            both.shop_price(107),
            43,
            "ceil once at the end: ceil(107*0.4) = 43, not ceil(ceil(107*0.5)*0.8) = 44"
        );
    }

    /// §338：**页面显示的价格就是扣款的价格**，四排货架都一样。
    ///
    /// 旧实现的形状：校验用**挂牌价**、扣款用**折后价**。于是持有 Membership Card、金币 60、
    /// 货架 100 时，页面按 50 判断"买得起"⇒ 按钮是启用的，点下去却被拒，还回一句
    /// `NotEnoughGold { price: 100, gold: 60 }` —— **屏幕上写着 50，内核说 100 不够**。
    ///
    /// 判据用 `gold = due - 1` 与 `gold = due` 两档夹住它：旧实现在第一档就报 `price: 挂牌价`
    /// （数字不对），第二档直接拒绝（成交不了）。
    #[test]
    fn every_purchase_charges_the_price_the_page_shows() {
        // 四排各挑一格，用**手工摆出来**的货架（不走 `stock_shop`：价格要可预期）。
        let mut run = ironclad();
        run.push_relic("membership_card", &TYPED_CARDS).expect("membership_card");
        run.pending = Pending::Shop;
        run.shop = ShopStock::empty();
        let card = TYPED_CARDS
            .iter()
            .find(|card| card.id == "strike")
            .copied()
            .expect("a strike in the pool");
        run.shop.cards[0] = Offer {
            id: RunId::new("strike").expect("id"),
            price: 100,
        };
        run.shop.cards_len = 1;
        run.shop.colorless[0] = Offer {
            id: RunId::new("strike").expect("id"),
            price: 100,
        };
        run.shop.colorless_len = 1;
        run.shop.potions[0] = Offer {
            id: RunId::new("fire_potion").expect("id"),
            price: 100,
        };
        run.shop.potions_len = 1;
        run.shop.relics[0] = Offer {
            id: RunId::new("anchor").expect("id"),
            price: 100,
        };
        run.shop.relics_len = 1;

        // `due` 是**页面看到的那个数**（`rd_run_shop_*_price` 走的就是 `shop_price`）。
        let due = run.shop_price(100);
        assert_eq!(due, 50, "membership_card halves the shelf price");

        // ---- 每一排：`due - 1` 被拒，且**错误里的数 == due**。
        for (name, buy) in [
            ("cards", 0usize),
            ("colorless", 1usize),
            ("potions", 2usize),
            ("relics", 3usize),
        ] {
            let mut short = run;
            short.adjust_gold(-short.gold() + due - 1);
            let refused = match buy {
                0 => short.buy_card(0, card, &TYPED_CARDS),
                1 => short.buy_colorless(0, &TYPED_CARDS),
                2 => short.buy_potion(0),
                _ => short.buy_relic(0, &TYPED_CARDS, &RELICS),
            };
            assert_eq!(
                refused,
                Err(RunError::NotEnoughGold { price: due, gold: due - 1 }),
                "{name}: the refusal must quote the price the page shows ({due}), not the shelf price"
            );
            // 被拒 ⇒ 一个字节都不改。
            assert_eq!(short.gold(), due - 1, "{name}: a refused purchase spends nothing");
            assert_eq!(short.deck().len(), run.deck().len(), "{name}: …and adds nothing");
        }

        // ---- 每一排：`due` 刚好够 ⇒ 成交，金币归零，扣的正好是 `due`。
        for (name, buy) in [
            ("cards", 0usize),
            ("colorless", 1usize),
            ("potions", 2usize),
            ("relics", 3usize),
        ] {
            let mut exact = run;
            exact.adjust_gold(-exact.gold() + due);
            let bought = match buy {
                0 => exact.buy_card(0, card, &TYPED_CARDS),
                1 => exact.buy_colorless(0, &TYPED_CARDS),
                2 => exact.buy_potion(0),
                _ => exact.buy_relic(0, &TYPED_CARDS, &RELICS),
            };
            assert_eq!(bought, Ok(()), "{name}: exactly `due` gold must be enough");
            assert_eq!(exact.gold(), 0, "{name}: the charge is exactly `due`");
        }
    }

    /// §338：买 **Membership Card 本身**不打折 —— `due` 必须在 `push_relic` **之前**冻结。
    ///
    /// wiki 的原话是 *"Membership Card immediately applies its discount to ALL Shops on purchase,
    /// meaning **the rest of** the items in the same Shop … will benefit"* —— "the rest of" 就是
    /// 自身不享受。旧实现先 `push_relic` 再算价，于是那一次交易自己给自己打了 5 折。
    #[test]
    fn buying_the_discount_relic_does_not_discount_itself() {
        let mut run = ironclad();
        run.pending = Pending::Shop;
        run.shop = ShopStock::empty();
        run.shop.relics[0] = Offer {
            id: RunId::new("membership_card").expect("id"),
            price: 100,
        };
        run.shop.relics_len = 1;
        // 第二格留一件普通遗物，用来证明"**后续**购买享受折扣"。
        run.shop.relics[1] = Offer {
            id: RunId::new("anchor").expect("id"),
            price: 100,
        };
        run.shop.relics_len = 2;
        run.adjust_gold(-run.gold() + 150);

        assert_eq!(run.shop_price(100), 100, "no discount before the purchase");
        assert_eq!(
            run.buy_relic(0, &TYPED_CARDS, &RELICS),
            Ok(()),
            "100 gold buys a 100-gold relic when there is no discount yet"
        );
        assert_eq!(run.gold(), 50, "the full shelf price was charged (no self-discount)");
        assert!(run.holds_relic("membership_card"), "…and the relic is now held");
        assert_eq!(
            run.shop_price(100),
            50,
            "the discount applies to the **rest** of the shop"
        );
    }

'''

t = sub(t, ANCHOR, NEW_TESTS + ANCHOR, 'new tests')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('tests updated + 3 new')
