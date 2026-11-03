"""§189 tests: A1 / A10 / A12 / A20, each asserted on **both** sides of its threshold.

The pattern is the same for all four, and it is the only pattern that catches these: a rule that
fires one level early looks exactly like a rule that works, unless you check the level below it.
"""
import io

STATE = "kernel/rd-run/src/state.rs"
MAP = "kernel/rd-run/src/map.rs"

STATE_ANCHOR = """    #[test]
    fn a_deck_edit_event_on_an_empty_deck_is_refused() {"""

STATE_NEW = r'''    /// §189 `A10`: Ascender's Bane joins the starting deck at 10 and not at 9, and it cannot be
    /// removed afterwards (the wiki card says so, and StS hardcodes it on the card itself).
    #[test]
    fn a10_starts_with_a_curse_that_cannot_be_removed() {
        for (level, want) in [(0u8, false), (9, false), (10, true), (20, true)] {
            let run = RunState::new_with_ascension(7, 80, 0, &["strike"; 5], level)
                .expect("a run");
            let has = run.deck().iter().any(|card| card.as_str() == ASCENDERS_BANE);
            assert_eq!(has, want, "A{level}: Ascender's Bane in the deck must be {want}");
            assert_eq!(
                run.deck_len,
                5 + u8::from(want),
                "A{level}: exactly one extra card"
            );
        }

        // Removing it is refused, and the refusal changes nothing (the price is not charged either).
        let mut run = RunState::new_with_ascension(7, 80, 500, &["strike"; 5], 10)
            .expect("a run");
        run.begin_shop(&[]).expect("a shop");
        let index = run
            .deck()
            .iter()
            .position(|card| card.as_str() == ASCENDERS_BANE)
            .expect("the curse is in the deck");
        let before = run;
        assert_eq!(run.remove_card(index), Err(RunError::CannotRemove));
        assert!(run == before, "a refused removal must not spend gold");
    }

    /// §189 `A12`: the **base** rule (12% / 25% by act) and the halving.
    ///
    /// The base rule had never existed -- act 1 was implemented as "no act ever offers an upgrade",
    /// so this test is also the one that proves the base rule is there at all.
    #[test]
    fn a12_halves_the_upgrade_chance_in_acts_two_and_three() {
        for (act, ascension, want) in [
            (1u8, 0u8, 0),
            (1, 20, 0),
            (2, 0, 12),
            (2, 11, 12),
            (2, 12, 6),
            (3, 0, 25),
            (3, 12, 12),
            (3, 20, 12),
        ] {
            assert_eq!(
                upgrade_chance_percent(act, ascension),
                want,
                "act {act} at A{ascension}"
            );
        }

        // ...and it is *observable*: an act-3 reward really does contain a `+` card, an act-1 one
        // never does. Seeds are pinned so the assertion is about the rule, not about luck.
        let pool = [PoolCard {
            id: "strike",
            rarity: Rarity::Common,
        }, PoolCard {
            id: "strike+",
            rarity: Rarity::Common,
        }, PoolCard {
            id: "defend",
            rarity: Rarity::Common,
        }, PoolCard {
            id: "defend+",
            rarity: Rarity::Common,
        }];
        let mut upgraded_in_act3 = 0;
        let mut upgraded_in_act1 = 0;
        for seed in 0..64 {
            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.act = 3;
            run.roll_reward(&pool, &[], &[], FightKind::Normal).expect("reward");
            upgraded_in_act3 += (0..run.reward_cards_len())
                .filter(|slot| run.reward_card(*slot).is_some_and(|id| id.ends_with('+')))
                .count();

            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.roll_reward(&pool, &[], &[], FightKind::Normal).expect("reward");
            upgraded_in_act1 += (0..run.reward_cards_len())
                .filter(|slot| run.reward_card(*slot).is_some_and(|id| id.ends_with('+')))
                .count();
        }
        assert_eq!(upgraded_in_act1, 0, "act 1 never offers an upgraded card");
        assert!(
            upgraded_in_act3 > 0,
            "act 3 must offer upgraded cards (25%), got none in 64 seeds"
        );
    }

    /// §189 `A20`: in the last act the first boss leaves the node **fightable again**, and only the
    /// second one wins the run.
    #[test]
    fn a20_makes_the_last_act_have_two_bosses() {
        let finish = |level: u8| -> (bool, bool, u8) {
            let mut run = RunState::new_with_ascension(7, 80, 0, &["strike"; 5], level)
                .expect("a run");
            run.act = MAX_ACT;
            run.node = i32::from(crate::map::BOSS_NODE);
            run.mark_boss_beaten();
            let after_first = (run.boss_beaten(), run.is_resolved(0), run.act);
            if level >= A_DOUBLE_BOSS {
                // the node is fightable again => the caller can start the second boss
                assert!(!after_first.0, "A20: the first boss must not win the run");
                assert!(!after_first.1, "A20: the boss node must be open again");
                run.mark_boss_beaten();
            }
            (run.boss_beaten(), run.is_resolved(0), run.act)
        };

        // A0 / A19: one boss wins the run.
        for level in [0u8, 19] {
            let (won, resolved, act) = finish(level);
            assert!(won, "A{level}: the last boss wins the run");
            assert!(resolved, "A{level}: the node stays settled");
            assert_eq!(act, MAX_ACT, "A{level}: no act past the last");
        }
        // A20: the second boss wins it.
        let (won, resolved, act) = finish(20);
        assert!(won, "A20: the second boss wins the run");
        assert!(resolved, "A20: and then the node settles");
        assert_eq!(act, MAX_ACT, "A20: still the last act");
    }

    #[test]
    fn a_deck_edit_event_on_an_empty_deck_is_refused() {'''

MAP_ANCHOR = """    #[test]
    fn check_rejects_a_wrong_fixed_floor() {"""

MAP_NEW = r'''    /// §189 `A1`: elites go 8% -> 16%, and the combat share pays for it. Both tables must still sum
    /// to 100 -- a table that does not is a bug the share check catches, not a rounding detail.
    #[test]
    fn a1_gives_elites_eight_more_percent_at_the_combat_share_s_expense() {
        fn shares(ascension: u8) -> [u32; 5] {
            let mut out = [0u32; 5];
            for roll in 0..100u32 {
                match kind_for_roll_at(roll, ascension).expect("every roll is a kind") {
                    NodeKind::Combat => out[0] += 1,
                    NodeKind::Elite => out[1] += 1,
                    NodeKind::Rest => out[2] += 1,
                    NodeKind::Shop => out[3] += 1,
                    NodeKind::Unknown => out[4] += 1,
                    _ => panic!("unexpected kind for roll {roll}"),
                }
            }
            out
        }
        assert_eq!(shares(0), [53, 8, 12, 5, 22], "A0 is the inventory's table");
        assert_eq!(shares(1), [45, 16, 12, 5, 22], "A1 moves 8 points to elites");
        assert_eq!(shares(20), [45, 16, 12, 5, 22], "and nothing else moves, ever");
        for ascension in [0u8, 1, 2, 20] {
            assert_eq!(
                shares(ascension).iter().sum::<u32>(),
                100,
                "A{ascension}: the table must sum to 100"
            );
        }
        // The stream is untouched at A0: same seed, same map as before this rule existed.
        let mut plain = RunRng::new(7);
        let mut levelled = RunRng::new(7);
        assert_eq!(
            RunMap::generate(&mut plain).expect("A0 map"),
            RunMap::generate_at(&mut levelled, 0).expect("A0 map"),
        );
        // ...and A1 draws a **different** map from the same seed (that is the rule's whole effect).
        let mut plain = RunRng::new(7);
        let mut levelled = RunRng::new(7);
        assert_ne!(
            RunMap::generate(&mut plain).expect("A0 map"),
            RunMap::generate_at(&mut levelled, 1).expect("A1 map"),
        );
    }

    #[test]
    fn check_rejects_a_wrong_fixed_floor() {'''


def main():
    for path, anchor, new, label in (
        (STATE, STATE_ANCHOR, STATE_NEW, "state"),
        (MAP, MAP_ANCHOR, MAP_NEW, "map"),
    ):
        text = io.open(path, encoding="utf-8").read()
        assert text.count(anchor) == 1, (label, text.count(anchor))
        io.open(path, "w", encoding="utf-8", newline="").write(text.replace(anchor, new))
        print("tests inserted into", label)


if __name__ == "__main__":
    main()
