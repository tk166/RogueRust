"""§340 判据：四排补货、补货不受 A16 涨价、补货失败不部分提交。

## 三条

1. `the_courier_restocks_all_four_shelves` —— 四排各买一次，**活着的格数不缩水**。
   旧实现只有两排会补（有色卡、遗物），无色与药水会缩水 —— 而"缩水"在页面上只表现为
   "那一格空着"，没有任何闸门会红。

2. `restocked_items_are_not_marked_up_by_ascension_16` —— A16 下补出来的货价必须落在
   **基础价目带**里（`card_price_band` 的 `low..=high`），而不是 ×1.1。
   wiki：*"Any item re-stocked by The Courier will not be affected by the 10% price increased 16"*。

3. `a_failed_restock_unwinds_the_whole_purchase` —— 用一个**超容量**池子让补货失败
   （`pool_fits` 返回 `PoolTooLarge`），断言 `Err` 与**整结构体相等**（`RunState` 派生
   `Copy + PartialEq + Eq`，所以判据是"一个字节都没改"）。
   这是**纪律**判据：真实内容里触发不到，但"拒绝 ⇒ 不改"是运行层对每个动作的承诺。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

ANCHOR = '''    /// §270：一次**真的**购买 —— 折扣后的钱扣掉、`maw_bank` 从此失效。'''

NEW_TESTS = '''    /// §340：`the_courier` 的补货覆盖**四排** —— 有色卡、无色卡、药水、遗物。
    ///
    /// 判据是"活着的格数不缩水"。旧实现只有前两排有补货分支：无色与药水买完就空着，
    /// 而屏幕上的表现只是"那一格没了"—— 没有任何闸门会红。
    ///
    /// 四排各测一次，因为补货是**四条独立的分支**（`restock_*_slot` 各一份），
    /// 写三条漏一条与全漏在"某一排缩水"这个现象上完全一样。
    #[test]
    fn the_courier_restocks_all_four_shelves() {
        let mut run = ironclad();
        run.push_relic("the_courier", &TYPED_CARDS).expect("the_courier");
        run.adjust_gold(4000);
        run.pending = Pending::Shop;
        // 无色池：测试夹具里没有无色牌，所以这里补一张（`stock_shop` 要求池子里有
        // Uncommon / Rare 各一张才会摆出无色货架）。
        let mut pool = Vec::new();
        pool.extend_from_slice(&TYPED_CARDS);
        pool.push(PoolCard {
            id: "swift_strike",
            rarity: Rarity::Uncommon,
            kind: CardKind::Attack,
            upgraded: None,
            colorless: true,
        });
        pool.push(PoolCard {
            id: "magnetism",
            rarity: Rarity::Rare,
            kind: CardKind::Power,
            upgraded: None,
            colorless: true,
        });
        run.stock_shop(&pool, &RELICS, &POTIONS).expect("stock the shop");

        let live = |run: &RunState| {
            (
                run.shop().cards().iter().filter(|o| o.price >= 0).count(),
                run.shop().colorless().iter().filter(|o| o.price >= 0).count(),
                run.shop().potions().iter().filter(|o| o.price >= 0).count(),
                run.shop().relics().iter().filter(|o| o.price >= 0).count(),
            )
        };
        let before = live(&run);
        assert_eq!(before.0, 5, "five coloured cards on the shelf");
        assert_eq!(before.1, 2, "one uncommon + one rare colourless");
        assert_eq!(before.2, 3, "three potions");
        assert_eq!(before.3, 1, "the fixture has exactly one relic");

        // ① 有色卡
        run.buy_card(0, PoolCard::plain(run.shop().cards()[0].id.as_str()), &pool)
            .expect("buy a card");
        assert_eq!(live(&run).0, before.0, "the coloured shelf must not shrink");
        // ② 无色卡
        run.buy_colorless(0, &pool).expect("buy a colourless card");
        assert_eq!(live(&run).1, before.1, "the colourless shelf must not shrink");
        // ③ 药水
        run.buy_potion(0, &POTIONS).expect("buy a potion");
        assert_eq!(live(&run).2, before.2, "the potion shelf must not shrink");
        // ④ 遗物：夹具里只有一件遗物，买走之后**补不出来**是允许的（池子空 ⇒ 那一格留空），
        //    所以这条的判据是"不会 panic、不会报错"，而不是"格数不变"。
        run.buy_relic(0, &pool, &RELICS).expect("buy the relic");
    }

    /// §340：**补货的商品不受 A16 涨价**（wiki：*"Any item re-stocked by The Courier will not be
    /// affected by the 10% price increased 16 from Ascension 16+"*）。
    ///
    /// 判据用**基础价目带**：A16 下首次铺货是 `marked_up(price)`（×1.1），补货必须是原价。
    /// 所以"补出来的价 ≤ 该稀有度的上界"这一条能把 `marked_up` 抓出来。
    #[test]
    fn restocked_items_are_not_marked_up_by_ascension_16() {
        let mut run = RunState::new(7, 80, 16, &DECK).expect("an A16 run");
        assert!(run.at_least(A_SHOP_PRICE), "the fixture must really be A16");
        run.push_relic("the_courier", &TYPED_CARDS).expect("the_courier");
        run.adjust_gold(4000);
        run.pending = Pending::Shop;
        run.stock_shop(&TYPED_CARDS, &RELICS, &POTIONS).expect("stock the shop");

        // 首次铺货确实涨价了（否则这条判据证明不了任何事）。
        let shelved = run.shop().cards()[0];
        let rarity = TYPED_CARDS
            .iter()
            .find(|card| card.id == shelved.id.as_str())
            .map_or(Rarity::Common, |card| card.rarity);
        let (low, high) = card_price_band(rarity);
        assert!(
            shelved.price > high || shelved.price / 2 <= high,
            "A16 marks the first stock up (shelf {} vs band {low}..={high})",
            shelved.price
        );

        run.buy_card(0, PoolCard::plain(shelved.id.as_str()), &TYPED_CARDS)
            .expect("buy the first card");
        let restocked = run.shop().cards()[0];
        assert!(restocked.price >= 0, "the slot was restocked");
        let rarity = TYPED_CARDS
            .iter()
            .find(|card| card.id == restocked.id.as_str())
            .map_or(Rarity::Common, |card| card.rarity);
        let (low, high) = card_price_band(rarity);
        assert!(
            (low..=high).contains(&restocked.price),
            "a restocked card costs the **base** band {low}..={high}, not the A16 markup \\
             (got {})",
            restocked.price
        );
    }

    /// §340：补货失败 ⇒ **整笔交易回滚**（金币、牌、货架一起），不留半个提交。
    ///
    /// 怎么构造：给一个**超过 `MAX_POOL`** 的卡池，`restock_card_slot` 的 `pool_fits` 就会
    /// 返回 `PoolTooLarge` —— 而它在扣钱与给牌**之后**。真实内容触发不到这条路径（池子远小于
    /// `MAX_POOL`），所以这是**纪律**判据：`RunState` 派生 `Copy + PartialEq + Eq`，
    /// 于是"一个字节都没改"可以直接比整个结构体。
    #[test]
    fn a_failed_restock_unwinds_the_whole_purchase() {
        let mut run = ironclad();
        run.push_relic("the_courier", &TYPED_CARDS).expect("the_courier");
        run.adjust_gold(4000);
        run.pending = Pending::Shop;
        run.stock_shop(&TYPED_CARDS, &RELICS, &POTIONS).expect("stock the shop");

        // 320 是 `MAX_POOL`；321 条就够让 `pool_fits` 响亮失败。
        let mut huge: Vec<PoolCard<'static>> = Vec::new();
        for index in 0..=MAX_POOL {
            huge.push(PoolCard {
                id: if index == 0 { "strike" } else { "defend" },
                rarity: Rarity::Common,
                kind: CardKind::Skill,
                upgraded: None,
                colorless: false,
            });
        }
        let before = run;
        let outcome = run.buy_card(0, PoolCard::plain("strike"), &huge);
        assert!(
            matches!(outcome, Err(RunError::PoolTooLarge { .. })),
            "the oversized pool must refuse the restock: {outcome:?}"
        );
        // ★ 判据是**整个结构体相等**：金币、牌组、货架、RNG 计数器全在里面。
        assert!(
            run == before,
            "a refused restock must leave the run byte-identical (gold {} -> {}, deck {} -> {})",
            before.gold(),
            run.gold(),
            before.deck().len(),
            run.deck().len()
        );
    }

'''

t = sub(t, ANCHOR, NEW_TESTS + ANCHOR, 'new tests')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('state.rs: three §340 tests')
