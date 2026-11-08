"""§293 判据：加牌问句（`orrery` / `tiny_house` / `singing_bowl`）。

每条都要两侧：
* 欠账被记下 / 加进牌组 / 欠账递减；
* 没有欠账、没有遗物时**拒绝**（而不是静默成功）；
* 牌组满了 ⇒ `Capacity` 且欠账**不被吃掉**。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

TESTS = r'''
    // =============================================================================================
    // §293：拾取时"挑一张牌**加**进牌组"（`orrery` / `tiny_house` / `singing_bowl`）
    // =============================================================================================

    /// §293：`orrery` —— 欠 5 张，每一次挑都会**换一手新的候选**（同一手不能给两次）。
    #[test]
    fn orrery_owes_five_cards_and_rolls_a_new_hand_each_time() {
        let pool = [
            PoolCard { id: "strike", kind: CardKind::Attack, rarity: Rarity::Basic, upgraded: None },
            PoolCard { id: "defend", kind: CardKind::Skill, rarity: Rarity::Basic, upgraded: None },
            PoolCard { id: "bash", kind: CardKind::Attack, rarity: Rarity::Basic, upgraded: None },
            PoolCard { id: "anger", kind: CardKind::Attack, rarity: Rarity::Common, upgraded: None },
        ];
        let mut run = run_with(&[]);
        let deck_before = run.deck().len();
        run.push_relic("orrery", &pool).expect("pickup");
        assert_eq!(run.pickup_add(), 5, "five cards are owed");
        assert_eq!(run.pickup_offer().len(), 3, "and a hand of three is rolled");
        // 挑一张：牌组 +1、欠账 -1、候选**换一手**（不是同一手再给一次）。
        run.pickup_add_card(0, &pool).expect("the first pick");
        assert_eq!(run.deck().len(), deck_before + 1, "one card joined the deck");
        assert_eq!(run.pickup_add(), 4, "the debt went down");
        // 一路挑到 0：欠账清了、候选清空。
        for _ in 0..4 {
            run.pickup_add_card(0, &pool).expect("the next pick");
        }
        assert_eq!(run.pickup_add(), 0, "the debt is spent");
        assert!(run.pickup_offer().is_empty(), "and the hand is cleared");
        assert_eq!(run.deck().len(), deck_before + 5, "five cards arrived");
        // 另一侧：欠账为 0 时再加就是 `WrongPhase`（不是静默什么都不做）。
        assert_eq!(run.pickup_add_card(0, &pool), Err(RunError::WrongPhase));
        assert_eq!(run.pickup_add_skip(), Err(RunError::WrongPhase));
    }

    /// §293：`tiny_house` —— 四件事一次做完（+50 金、上限 +5、一瓶药水欠账、一张牌欠账）。
    #[test]
    fn tiny_house_does_all_four_things() {
        let pool = [
            PoolCard { id: "strike", kind: CardKind::Attack, rarity: Rarity::Basic, upgraded: None },
            PoolCard { id: "defend", kind: CardKind::Skill, rarity: Rarity::Basic, upgraded: None },
            PoolCard { id: "bash", kind: CardKind::Attack, rarity: Rarity::Basic, upgraded: None },
        ];
        let mut run = run_with(&[]);
        let (gold, health, max, potions) =
            (run.gold(), run.health(), run.health_max(), run.pickup_potions());
        run.push_relic("tiny_house", &pool).expect("pickup");
        assert_eq!(run.gold(), gold + 50, "+50 gold");
        assert_eq!(run.health_max(), max + 5, "+5 max HP");
        assert_eq!(run.health(), health + 5, "and the current HP followed it");
        assert_eq!(run.pickup_potions(), potions + 1, "one potion is owed");
        assert_eq!(run.pickup_add(), 1, "one card is owed");
        assert_eq!(run.pickup_offer().len(), 3, "with a hand to pick from");
    }

    /// §293：`singing_bowl` —— 两条"换成 +2 上限"的路：加牌问句、战斗奖励屏。
    #[test]
    fn singing_bowl_trades_a_card_for_two_max_hp_in_both_places() {
        let pool = [
            PoolCard { id: "strike", kind: CardKind::Attack, rarity: Rarity::Basic, upgraded: None },
            PoolCard { id: "defend", kind: CardKind::Skill, rarity: Rarity::Basic, upgraded: None },
            PoolCard { id: "bash", kind: CardKind::Attack, rarity: Rarity::Basic, upgraded: None },
        ];
        // ① 加牌问句上的那一个。
        let mut run = run_with(&["singing_bowl"]);
        run.push_relic("orrery", &pool).expect("pickup");
        let max_before = run.health_max();
        let deck_before = run.deck().len();
        run.pickup_add_max_hp().expect("trade the card for max HP");
        assert_eq!(run.health_max(), max_before + 2, "+2 max HP");
        assert_eq!(run.deck().len(), deck_before, "and no card was added");
        assert_eq!(run.pickup_add(), 4, "the pick was spent");
        // 另一侧：**没有** `singing_bowl` ⇒ `UnsupportedRelic`，而且局面不变。
        let mut plain = run_with(&[]);
        plain.push_relic("orrery", &pool).expect("pickup");
        let before = crate::hash::run_hash_hex(&plain).expect("hash");
        assert_eq!(
            plain.pickup_add_max_hp(),
            Err(RunError::UnsupportedRelic { index: 0 })
        );
        assert_eq!(crate::hash::run_hash_hex(&plain).expect("hash"), before, "nothing moved");

        // ② 战斗奖励屏上的那一个：不拿牌、改拿 +2 上限，金币/药水/遗物都还在屏上。
        let mut run = run_with(&["singing_bowl"]);
        run.begin_reward(FightKind::Normal, &pool, &[], &[], &[]).ok();
        if run.pending() == Pending::Reward {
            let max_before = run.health_max();
            run.take_max_hp_instead().expect("trade the reward");
            assert_eq!(run.health_max(), max_before + 2, "+2 max HP");
            assert_eq!(run.reward().cards().len(), 0, "and the card row is spent");
            assert_eq!(run.pending(), Pending::Reward, "the screen stays for the potion/relic");
            // 第二次调它就是 `EmptyOffer`（不能拿两次）。
            assert_eq!(run.take_max_hp_instead(), Err(RunError::EmptyOffer(0)));
        }
    }

    /// §293：牌组满了 ⇒ `Capacity`，而且**欠账不被吃掉**（§274 的 `pickup_card` 踩过同一个坑）。
    #[test]
    fn a_full_deck_refuses_the_pick_without_eating_the_debt() {
        let pool = [
            PoolCard { id: "strike", kind: CardKind::Attack, rarity: Rarity::Basic, upgraded: None },
            PoolCard { id: "defend", kind: CardKind::Skill, rarity: Rarity::Basic, upgraded: None },
            PoolCard { id: "bash", kind: CardKind::Attack, rarity: Rarity::Basic, upgraded: None },
        ];
        let mut run = run_with(&[]);
        run.push_relic("orrery", &pool).expect("pickup");
        while run.deck().len() < MAX_RUN_DECK {
            run.push_card(PoolCard::plain("strike")).expect("room");
        }
        let owed = run.pickup_add();
        assert_eq!(run.pickup_add_card(0, &pool), Err(RunError::Capacity));
        assert_eq!(run.pickup_add(), owed, "the debt survives a refused pick");
    }
'''

def main():
    s = io.open(STATE, encoding='utf-8').read()
    assert s.rstrip('\n').endswith('}')
    cut = s.rstrip('\n').rfind('\n}')
    # 插在 `mod tests` 的收尾 `}` 之前
    s = s[:cut] + '\n' + TESTS + s[cut:]
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('tests appended')


main()
