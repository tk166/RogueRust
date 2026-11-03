"""§189 tests for A10 / A12 / A20 (A1's test lives in `map.rs`).

Inserted **before** the first `#[test]` that mentions `Empty`-deck events, using the doc-comment +
attribute pair as the anchor (an earlier attempt anchored on a bare doc line and spliced the body into
the neighbouring function -- 2 375 lines gone, recovered from git).
"""
import io
import os

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PATH = os.path.join(ROOT, "kernel", "rd-run", "src", "state.rs")

ANCHOR = """    #[test]
    fn a_deck_edit_event_on_an_empty_deck_is_refused() {"""

NEW = r'''    /// §189 `A10`：Ascender's Bane 在 10 级进牌组、9 级不进，而且进了就**删不掉**
    /// （wiki 卡面写着 "Cannot be removed"，StS 也把这条写在这张卡自己的代码里）。
    #[test]
    fn a10_starts_with_a_curse_that_cannot_be_removed() {
        for (level, want) in [(0u8, false), (9, false), (10, true), (20, true)] {
            let run =
                RunState::new_with_ascension(7, 80, 0, &["strike"; 5], level).expect("a run");
            let has = run.deck().iter().any(|card| card.as_str() == ASCENDERS_BANE);
            assert_eq!(has, want, "A{level}: Ascender's Bane in the deck must be {want}");
            assert_eq!(
                run.deck_len,
                5 + u8::from(want),
                "A{level}: exactly one extra card"
            );
        }

        // Removing it is refused, and the refusal changes nothing -- the price is not charged.
        let mut run =
            RunState::new_with_ascension(7, 80, 500, &["strike"; 5], 10).expect("a run");
        // The test lives in this module, so it can put the run straight into the shop phase, which is
        // the only thing `remove_card` checks before refusing.
        run.pending = Pending::Shop;
        let index = run
            .deck()
            .iter()
            .position(|card| card.as_str() == ASCENDERS_BANE)
            .expect("the curse is in the deck");
        let before = run;
        assert_eq!(run.remove_card(index), Err(RunError::CannotRemove));
        assert!(run == before, "a refused removal must not spend gold");
    }

    /// §189 `A12`：基线规则（二三幕 12% / 25%）与 A12 的减半。
    ///
    /// 基线以前**不存在**（第一幕的 0% 被实现成了"哪一幕都 0%"），所以这条测试也是"基线在那儿"
    /// 的证明：64 个种子里第三幕必须出现升级牌，第一幕一张都不许有。
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

        // Six base cards plus their `+` rows: a reward screen needs three **distinct** base cards, so
        // a two-card pool would fail with `PoolTooSmall` before the rule could be observed.
        let mut pool = std::vec::Vec::new();
        for id in ["strike", "defend", "anger", "bash", "clash", "flex"] {
            pool.push(PoolCard {
                id,
                rarity: Rarity::Common,
            });
            pool.push(PoolCard {
                id: std::boxed::Box::leak(std::format!("{id}+").into_boxed_str()),
                rarity: Rarity::Common,
            });
        }

        let mut upgraded_in_act3 = 0;
        let mut upgraded_in_act1 = 0;
        for seed in 0..64 {
            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.act = 3;
            run.roll_reward(&pool, &[], &[], FightKind::Normal)
                .expect("reward");
            upgraded_in_act3 += run
                .reward_cards()
                .iter()
                .filter(|id| id.as_str().ends_with('+'))
                .count();

            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.roll_reward(&pool, &[], &[], FightKind::Normal)
                .expect("reward");
            upgraded_in_act1 += run
                .reward_cards()
                .iter()
                .filter(|id| id.as_str().ends_with('+'))
                .count();
        }
        assert_eq!(upgraded_in_act1, 0, "act 1 never offers an upgraded card");
        assert!(
            upgraded_in_act3 > 0,
            "act 3 must offer upgraded cards (25%), got none in 64 seeds"
        );
    }

    /// §189 `A20`：最后一幕的第一个 Boss 倒下后节点**重新可打**，只有第二个才算赢。
    #[test]
    fn a20_makes_the_last_act_have_two_bosses() {
        let finish = |level: u8| -> (bool, bool, u8) {
            let mut run =
                RunState::new_with_ascension(7, 80, 0, &["strike"; 5], level).expect("a run");
            run.act = MAX_ACT;
            run.node = i32::from(crate::map::BOSS_NODE);
            run.mark_boss_beaten();
            if level >= A_DOUBLE_BOSS {
                assert!(!run.boss_beaten(), "A20: the first boss must not win the run");
                assert!(!run.node_resolved(), "A20: the boss node must be open again");
                run.mark_boss_beaten();
            }
            (run.boss_beaten(), run.node_resolved(), run.act)
        };

        for level in [0u8, 19] {
            let (won, resolved, act) = finish(level);
            assert!(won, "A{level}: the last boss wins the run");
            assert!(resolved, "A{level}: the node stays settled");
            assert_eq!(act, MAX_ACT, "A{level}: no act past the last");
        }
        let (won, resolved, act) = finish(20);
        assert!(won, "A20: the second boss wins the run");
        assert!(resolved, "A20: and then the node settles");
        assert_eq!(act, MAX_ACT, "A20: still the last act");
    }

    #[test]
    fn a_deck_edit_event_on_an_empty_deck_is_refused() {'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "a10_starts_with_a_curse" not in text, "already inserted"
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("A10/A12/A20 tests inserted")


if __name__ == "__main__":
    main()
