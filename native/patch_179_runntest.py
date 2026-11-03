"""§179 potion tests, in `run.rs`'s module (potions live on the run, not on a bare fight)."""
import io

RUN = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// The hero's stacks of `definition`, read through the §147 ABI (works for any status)."""

NEW = r'''    /// §179: Blessing of the Forge -- "Upgrade all cards in your hand for the rest of combat."
    ///
    /// The judgment is the **definition id** because that is what `play` looks the program up by:
    /// `strike+` deals 9 where `strike` deals 6. A display-only swap (the upgraded name over the old
    /// program) would pass a label check and fail this one.
    ///
    /// ⚠️ The starting deck is **read from the run**, not assumed: §154's blessing may already have
    /// upgraded or removed cards, so the test asks the belt-side state which Strikes are in hand.
    #[test]
    fn blessing_of_the_forge_upgrades_every_strike_in_hand() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        let hand_before = hand_ids();
        assert!(
            hand_before.iter().any(|id| id == "strike"),
            "the fixture expects plain Strikes in hand: {hand_before:?}"
        );
        assert_eq!(drink("blessing_of_the_forge", -1), 0, "drinking it must work");

        let hand_after = hand_ids();
        assert_eq!(
            hand_after.len(),
            hand_before.len(),
            "upgrading a card does not move it out of the hand"
        );
        let strikes: Vec<&String> = hand_after.iter().filter(|id| id.starts_with("strike")).collect();
        assert!(!strikes.is_empty(), "the Strikes are still there: {hand_after:?}");
        assert!(
            strikes.iter().all(|id| id.as_str() == "strike+"),
            "every Strike in hand is the `+` row now: {hand_after:?}"
        );
        assert!(
            !hand_after.iter().any(|id| id == "strike"),
            "no plain `strike` survives in hand: {hand_after:?}"
        );
    }

    /// §179: Snecko Oil -- "Draw 5 cards. Randomize the costs of all cards in your hand."
    ///
    /// Two visible facts: five more cards, and every price inside `0..=3`. The prices are read from
    /// the **display** column (`hand_costs`), so this also pins that the override reaches the screen
    /// and not only `play` (the two-pricing-places problem from §161.4).
    #[test]
    fn snecko_oil_draws_five_and_randomizes_every_price_in_hand() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        let hand_before = hand_ids().len();
        assert_eq!(drink("snecko_oil", -1), 0, "drinking it must work");
        let session = crate::slot().as_ref().expect("env session");
        assert_eq!(
            session.hand_len(),
            hand_before + 5,
            "`Draw 5` -- hand went {hand_before} -> {}",
            session.hand_len()
        );
        let costs = session.hand_costs.clone();
        assert_eq!(costs.len(), session.hand_len(), "one price per hand card");
        for (index, cost) in costs.iter().enumerate() {
            assert!(
                (0..=3).contains(cost),
                "hand[{index}] costs {cost}, outside the randomized band 0..=3"
            );
        }
    }

    /// §179: Smoke Bomb -- "Escape from a non-boss combat. Receive no rewards."
    ///
    /// The refusal in a boss fight matters as much as the escape: a guard that only worked outside
    /// bosses would still let a player skip a boss.
    #[test]
    fn smoke_bomb_ends_a_normal_fight_and_refuses_a_boss() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");
        let gold_before = run_slot().as_ref().expect("run").state.gold();
        let pending_before = rd_run_pending();

        assert_eq!(drink("smoke_bomb", -1), 0, "escaping a normal fight is legal");
        assert!(
            crate::slot().is_none(),
            "the combat session is gone: escaping ends the fight, it does not pause it"
        );
        let run = run_slot().as_ref().expect("the run outlives the fight");
        assert!(!run.in_fight, "the run knows the fight ended");
        assert_eq!(
            run.state.gold(),
            gold_before,
            "Smoke Bomb pays nothing -- gold moved, so the escape looted the node"
        );
        assert_eq!(
            rd_run_pending(),
            pending_before,
            "no reward screen may open after an escape"
        );

        // The refusal: a boss fight. `boss_fight` is the run's own flag, so set it the way the
        // node walker does and try again.
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");
        run_slot().as_mut().expect("run").boss_fight = true;
        assert!(
            drink("smoke_bomb", -1) < 0,
            "a boss fight must refuse the escape (wiki: non-boss combat)"
        );
        assert!(
            crate::slot().is_some(),
            "a refusal must not end the fight"
        );
    }

    /// The hand's definition ids, in pile order (`hand_costs` has the prices).
    fn hand_ids() -> Vec<String> {
        let session = crate::slot().as_ref().expect("env session");
        let hero = session.hero_id().expect("hero");
        session
            .state
            .card_zones(&hero)
            .map(|zones| {
                zones
                    .slots(rd_core::state::CardZone::Hand)
                    .iter()
                    .filter_map(|slot| {
                        session
                            .state
                            .card(rd_core::state::CardSlot::from_index(*slot))
                            .map(|card| card.definition_id.as_str().to_string())
                    })
                    .collect()
            })
            .unwrap_or_default()
    }

    /// The hero's stacks of `definition`, read through the §147 ABI (works for any status).'''


def main():
    text = io.open(RUN, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    io.open(RUN, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("§179 run.rs tests inserted")


if __name__ == "__main__":
    main()
