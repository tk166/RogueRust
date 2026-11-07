"""§270 判据：加牌类 6 件 + 金币/商店类 5 件。

每组都**两面**：该生效的场景生效、**不该生效**的场景一动不动。没有反面，
`omamori` 就会变成"任何牌都挡 2 次"，而判据全绿。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
ANCHOR = '''    /// §269：**战斗类型层** —— 同一个遗物在不同 `FightKind` 下给出不同的加成。'''

TESTS = r'''    /// §270：**加牌类** —— 所有落点都在 `push_card` 一处。
    #[test]
    fn the_add_card_relics_fire_at_the_one_add_point() {
        // ---- `omamori`：挡掉接下来 2 个**诅咒**，第 3 个进牌组；非诅咒完全不挡。
        let mut run = ironclad();
        run.push_relic("omamori").expect("omamori");
        assert_eq!(run.omamori_charges(), OMAMORI_CHARGES, "grant gives 2");

        let curse = PoolCard { kind: CardKind::Curse, ..PoolCard::plain("injury") };
        let deck_before = run.deck().len();
        run.push_card(curse).expect("a negated curse is not an error");
        assert_eq!(run.deck().len(), deck_before, "the first curse is negated");
        assert_eq!(run.omamori_charges(), 1);
        run.push_card(curse).expect("the second is negated too");
        assert_eq!(run.deck().len(), deck_before, "still nothing added");
        assert_eq!(run.omamori_charges(), 0, "both charges spent");
        run.push_card(curse).expect("the third arrives");
        assert_eq!(run.deck().len(), deck_before + 1, "out of charges ⇒ it lands");

        // 非诅咒：一次都不能被挡（这条是反面 —— 没有它，`omamori` 会挡住整副牌）。
        let mut run = ironclad();
        run.push_relic("omamori").expect("omamori");
        let before = run.deck().len();
        run.push_card(PoolCard { kind: CardKind::Attack, ..PoolCard::plain("anger") })
            .expect("an attack");
        assert_eq!(run.deck().len(), before + 1, "attacks are never negated");
        assert_eq!(run.omamori_charges(), OMAMORI_CHARGES, "…and cost no charge");

        // ---- `darkstone_periapt`：诅咒 ⇒ 上限 +6。**被 `omamori` 挡掉的那个不算**（顺序即规则）。
        let mut run = ironclad();
        run.push_relic("darkstone_periapt").expect("periapt");
        let max_before = run.health_max();
        run.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain("injury") })
            .expect("curse");
        assert_eq!(run.health_max(), max_before + 6, "a curse raises the max by 6");
        run.push_card(PoolCard { kind: CardKind::Attack, ..PoolCard::plain("anger") })
            .expect("attack");
        assert_eq!(run.health_max(), max_before + 6, "a non-curse does not");

        let mut both = ironclad();
        both.push_relic("omamori").expect("omamori");
        both.push_relic("darkstone_periapt").expect("periapt");
        let max_before = both.health_max();
        both.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain("injury") })
            .expect("negated curse");
        assert_eq!(both.deck().len(), 10, "omamori took it");
        assert_eq!(
            both.health_max(),
            max_before,
            "a **negated** curse is not 'obtained' ⇒ darkstone must stay quiet"
        );

        // ---- 三个蛋：类型对上就换成 `+` 行，对不上原样。
        for (relic, kind, other) in [
            ("molten_egg", CardKind::Attack, CardKind::Skill),
            ("toxic_egg", CardKind::Skill, CardKind::Attack),
            ("frozen_egg", CardKind::Power, CardKind::Attack),
        ] {
            let mut run = ironclad();
            run.push_relic(relic).expect("an egg");
            let matching = PoolCard {
                id: "bash",
                rarity: Rarity::Common,
                kind,
                upgraded: Some("bash+"),
            };
            let before = run.deck().len();
            run.push_card(matching).expect("matching card");
            assert_eq!(
                run.deck()[before].as_str(),
                "bash+",
                "{relic} must upgrade a card of its own type"
            );

            let wrong = PoolCard {
                id: "bash",
                rarity: Rarity::Common,
                kind: other,
                upgraded: Some("bash+"),
            };
            run.push_card(wrong).expect("other type");
            assert_eq!(
                run.deck()[before + 1].as_str(),
                "bash",
                "{relic} must NOT touch another type"
            );
        }

        // 没有 `+` 行时保持原样（内容的事，不报错）。
        let mut run = ironclad();
        run.push_relic("molten_egg").expect("egg");
        let before = run.deck().len();
        run.push_card(PoolCard {
            id: "bash",
            rarity: Rarity::Common,
            kind: CardKind::Attack,
            upgraded: None,
        })
        .expect("no `+` row");
        assert_eq!(run.deck()[before].as_str(), "bash");

        // ---- `ceramic_fish`：加任何牌 +9 金币。
        let mut run = ironclad();
        run.push_relic("ceramic_fish").expect("fish");
        let gold_before = run.gold();
        run.push_card(PoolCard { kind: CardKind::Skill, ..PoolCard::plain("defend") })
            .expect("a skill");
        assert_eq!(run.gold(), gold_before + 9, "ceramic_fish: +9 per card");

        // `omamori` 挡掉的那一张**不给钱**（没进牌组 ⇒ 不算"add a card"）。
        let mut both = ironclad();
        both.push_relic("omamori").expect("omamori");
        both.push_relic("ceramic_fish").expect("fish");
        let gold_before = both.gold();
        both.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain("injury") })
            .expect("negated");
        assert_eq!(both.gold(), gold_before, "a negated curse pays no gold");
    }

    /// §270：**金币/商店类** —— 四个落点：`adjust_gold` / `enter_node` / 价格 / 删牌服务。
    #[test]
    fn the_gold_and_shop_relics_change_only_their_own_number() {
        // ---- `ectoplasm`：得金币变 0（**花出去**不受影响），且每回合 +1 能量的载体照旧。
        let mut run = ironclad();
        run.push_relic("ectoplasm").expect("ectoplasm");
        let gold = run.gold();
        run.adjust_gold(100);
        assert_eq!(run.gold(), gold, "ectoplasm: you can no longer gain Gold");
        run.adjust_gold(-gold.min(10));
        assert!(run.gold() < gold, "spending still works");
        assert_eq!(
            run.combat_bonus_for(FightKind::Normal).status_count,
            1,
            "ectoplasm's second half (the energy carrier) must still be granted"
        );

        // ---- `bloody_idol`：**真的**得到金币才回 5 血。
        let mut run = ironclad();
        run.push_relic("bloody_idol").expect("idol");
        run.adjust_health(-10);
        let hp = run.health();
        run.adjust_gold(12);
        assert_eq!(run.health(), hp + 5, "bloody_idol: +5 HP per gold gain");
        run.adjust_gold(-5);
        assert_eq!(run.health(), hp + 5, "spending heals nothing");

        // 与 `ectoplasm` 一起：金币没涨 ⇒ **不回血**（"gained" 判的是实际差，不是 `delta > 0`）。
        let mut both = ironclad();
        both.push_relic("bloody_idol").expect("idol");
        both.push_relic("ectoplasm").expect("ectoplasm");
        both.adjust_health(-10);
        let hp = both.health();
        both.adjust_gold(12);
        assert_eq!(
            both.health(),
            hp,
            "ectoplasm blocked the gold, so there was nothing to heal from"
        );

        // ---- `maw_bank`：爬一层 +12；在商店花过钱之后失效。
        let mut run = ironclad();
        run.push_relic("maw_bank").expect("maw_bank");
        let gold = run.gold();
        let target = run.reachable().first().expect("a floor-1 node");
        run.enter_node(target).expect("climb");
        assert_eq!(run.gold(), gold + 12, "maw_bank: +12 per floor climbed");
        let gold = run.gold();
        run.enter_node(run.reachable().first().expect("the next node"))
            .expect("climb again");
        assert_eq!(run.gold(), gold + 12, "…and again");

        // 没有这件遗物时一分钱都不多。
        let mut plain = ironclad();
        let gold = plain.gold();
        plain
            .enter_node(plain.reachable().first().expect("a node"))
            .expect("climb");
        assert_eq!(plain.gold(), gold, "no maw_bank ⇒ no climb gold");

        // ---- `smiling_mask`：删牌服务固定 50（`removed_cards` 的 +25/次 对它失效）。
        let mut run = ironclad();
        assert_eq!(run.remove_card_price(), SHOP_REMOVE_BASE, "the first removal");
        run.push_relic("smiling_mask").expect("mask");
        assert_eq!(
            run.remove_card_price(),
            SHOP_REMOVE_FLAT,
            "smiling_mask: always 50"
        );

        // ---- `membership_card`：所有商品半价；**显示价与实付价是同一个函数**。
        let mut run = ironclad();
        assert_eq!(run.shop_price(100), 100, "no discount without the relic");
        run.push_relic("membership_card").expect("membership_card");
        assert_eq!(run.shop_price(100), 50, "membership_card: 50% off");
        assert_eq!(
            run.shop_price(run.remove_card_price()),
            SHOP_REMOVE_BASE / 2,
            "the removal service is a product too"
        );
    }

    /// §270：一次**真的**购买 —— 折扣后的钱扣掉、`maw_bank` 从此失效。
    #[test]
    fn a_discounted_purchase_charges_the_discounted_price() {
        let mut run = ironclad();
        run.push_relic("membership_card").expect("membership_card");
        run.push_relic("maw_bank").expect("maw_bank");
        // 先把金币垫高，否则买不起。
        run.adjust_gold(2000);
        let target = run.reachable().first().expect("a node");
        run.enter_node(target).expect("climb");
        let shop_node = (0..run.reachable().len())
            .find(|index| {
                let node = run.reachable().nth(*index).expect("a node");
                run.map().kind(node) == Some(crate::map::NodeKind::Shop)
            });
        // 这张图的第一层未必是商店：找不到就退化成"直接摆货架"，判据照样只测价格。
        if let Some(index) = shop_node {
            let node = run.reachable().nth(index).expect("a node");
            run.enter_node(node).expect("walk into the shop");
            run.begin_node(&CARDS, &RELICS).expect("stock the shop");
            assert_eq!(run.pending(), Pending::Shop);
            assert!(!run.maw_bank_broken());
            let offer = run.shop().cards()[0];
            let gold = run.gold();
            buy_card_at(&mut run, 0).expect("buy the first card");
            assert_eq!(
                run.gold(),
                gold - run.shop_price(offer.price),
                "the price charged is `shop_price`, not the shelf price"
            );
            assert!(run.maw_bank_broken(), "spending at a shop breaks maw_bank");
        }
    }

'''

CARDS_CONST = '''    const CARDS: [PoolCard<'static>; 3] = [
        PoolCard { id: "strike", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None },
        PoolCard { id: "defend", rarity: Rarity::Common, kind: CardKind::Skill, upgraded: None },
        PoolCard { id: "anger", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None },
    ];
'''


def main():
    src = io.open(P, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'the_add_card_relics_fire_at_the_one_add_point' not in src
    src = src.replace(ANCHOR, TESTS + ANCHOR)
    # 一份测试用的卡池（带类型）
    anchor2 = '''mod tests {
    use super::*;
'''
    assert src.count(anchor2) == 1
    src = src.replace(anchor2, anchor2 + '\n' + CARDS_CONST)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('§270 tests appended')


main()
