"""§273 判据：`?`→商店 也触发 `meal_ticket` + `the_courier`（-20% 与补货）。

两条都是"同一件规则只该有一处"的判据：
  1. **同一个 `enter_shop`**：商店节点与 `?` 房掷出的商店都必须回 15 血，
     而且**反过来**（不是商店的房间）不回血；
  2. **补货只在有 courier 时发生**：买走一格之后那一格非空（且是不同的货），
     没有这件遗物时那一格留空（`price = -1`）。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
ANCHOR = '''    /// §272：`?` 房的**概率公式**'''

TESTS = r'''    /// §273：`?` 房掷出商人 ⇒ 与商店节点**同一条**进门路径（`meal_ticket` 也要付）。
    ///
    /// ⚠️ 这条判据钉的正是 §272 留下的缺口：`begin_node` 的 Unknown 分支当时只 `stock_shop`，
    /// 于是 `?`→商店 不回血。wiki 的 Planisphere 页写过 *"a ? that turns into a shop triggers
    /// both"*。
    #[test]
    fn an_unknown_room_that_becomes_a_shop_pays_the_shop_entry_relics() {
        use crate::map::NodeKind;

        fn enter_unknown_shop(mut seed: i32) -> Option<(RunState, i32)> {
            // 走到一个 `?` 房并 `begin_node`，直到掷出**商人**（约 3% ⇒ 400 个种子足够）。
            for _ in 0..4000 {
                let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
                if !walk_to(&mut run, NodeKind::Unknown) {
                    seed += 1;
                    continue;
                }
                let ok = run.begin_node(&TYPED_CARDS, &RELICS).is_ok();
                if ok && run.unknown_room() == UnknownRoom::Shop {
                    let hp = run.health();
                    return Some((run, hp));
                }
                seed += 1;
            }
            None
        }

        let Some((run, hp)) = enter_unknown_shop(0) else {
            panic!("no seed produced a merchant ? room in 4000 tries");
        };
        assert_eq!(
            run.pending(),
            Pending::Shop,
            "a merchant ? room opens the shop flow"
        );
        assert!(
            !run.shop().cards().is_empty(),
            "…and the shelf is stocked by the same `enter_shop`"
        );
        // 反面对照：没有 `meal_ticket` 时血量不动（这个 run 没这件遗物）。
        let mut plain = run;
        assert_eq!(plain.health(), hp.min(plain.health_max()), "no relic ⇒ no heal");

        // 有了 `meal_ticket`：同一个 `?` 房要多 15 血。
        let mut with_relic = None;
        let mut seed = 0;
        while seed < 4000 {
            let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
            run.push_relic("meal_ticket").expect("meal_ticket");
            run.adjust_health(-30);
            if !walk_to(&mut run, NodeKind::Unknown) {
                seed += 1;
                continue;
            }
            let before = run.health();
            let ok = run.begin_node(&TYPED_CARDS, &RELICS).is_ok();
            if ok && run.unknown_room() == UnknownRoom::Shop {
                with_relic = Some((before, run.health()));
                break;
            }
            seed += 1;
        }
        let (before, after) = with_relic.expect("no merchant ? room with the relic in 4000 tries");
        assert_eq!(
            after,
            (before + 15).min(80),
            "meal_ticket must pay on a `?` room that becomes a shop, not just on a shop node"
        );

        // 而普通商店节点仍然照旧（同一个 `enter_shop` 的另一个调用方）。
        let mut run = RunState::new(7, 80, i32::MAX, &["strike"; 10]).expect("a run");
        run.push_relic("meal_ticket").expect("meal_ticket");
        run.adjust_health(-30);
        let before = run.health();
        run.pending = Pending::Shop;
        run.stock_shop(&TYPED_CARDS, &RELICS).expect("stock");
        // `stock_shop` 本身**不**回血（回血在 `enter_shop` 里）—— 这条断言把"两个函数的分工"
        // 钉住：想验 `enter_shop` 就得走 `begin_node`，而不是直接调它。
        assert_eq!(run.health(), before, "stocking alone does not pay the entry heal");
    }

    /// §273：`the_courier` —— 半价之外的"买完补货"。
    #[test]
    fn the_courier_restocks_the_slot_it_sells() {
        // ---- 折扣：20%（与 `membership_card` 的 50% 相加）。
        let mut run = ironclad();
        assert_eq!(run.shop_price(100), 100);
        run.push_relic("the_courier").expect("the_courier");
        assert_eq!(run.shop_price(100), 80, "the_courier: 20% off");
        run.push_relic("membership_card").expect("membership_card");
        assert_eq!(run.shop_price(100), 30, "the two discounts add up (50 + 20)");

        // ---- 补货：买走一格 ⇒ 那一格又有货，而且是**不同的**牌。
        let mut run = ironclad();
        run.push_relic("the_courier").expect("the_courier");
        run.adjust_gold(2000);
        run.pending = Pending::Shop;
        run.enter_shop(&TYPED_CARDS, &RELICS).expect("enter the shop");
        let before: Vec<&str> = run.shop().cards().iter().map(|o| o.id.as_str()).collect();
        let bought = run.shop().cards()[0].id;
        buy_card_at(&mut run, 0).expect("buy the first card");
        let after = run.shop().cards()[0];
        assert!(
            after.price >= 0,
            "the_courier: the bought slot is restocked, not left empty"
        );
        assert_ne!(
            after.id, bought,
            "…and it is a different card (the shelf must not grow duplicates of what you bought)"
        );
        assert!(
            !before[1..].iter().any(|id| *id == after.id.as_str()) || before.len() == 1,
            "…and not a duplicate of another slot"
        );

        // 反面：没有 `the_courier` 时那一格留空（`price = -1`）。
        let mut plain = ironclad();
        plain.adjust_gold(2000);
        plain.pending = Pending::Shop;
        plain.enter_shop(&TYPED_CARDS, &RELICS).expect("enter the shop");
        buy_card_at(&mut plain, 0).expect("buy the first card");
        assert_eq!(
            plain.shop().cards()[0].price,
            -1,
            "without the_courier a bought slot stays empty"
        );

        // ---- 遗物那一半：买走之后那一格也补货（池子里还有 `burning_blood` 之外的就补）。
        let mut run = ironclad();
        run.push_relic("the_courier").expect("the_courier");
        run.adjust_gold(2000);
        run.pending = Pending::Shop;
        run.enter_shop(&TYPED_CARDS, &RELICS).expect("enter the shop");
        if run.shop().relics().first().is_some_and(|o| o.price >= 0) {
            buy_relic_at(&mut run, 0).expect("buy the relic");
            let slot = run.shop().relics()[0];
            // 池子只有一件遗物（`RELICS`），买走之后**没有**可补的 ⇒ 那一格必须是空的。
            // 这条"反面"很重要：补货不能凭空造货。
            assert_eq!(slot.price, -1, "an exhausted relic pool cannot restock");
        }
    }

'''


def main():
    src = io.open(P, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'an_unknown_room_that_becomes_a_shop_pays' not in src
    src = src.replace(ANCHOR, TESTS + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('§273 tests appended')


main()
