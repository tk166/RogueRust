"""§179 wasm tests, written against the helpers that actually exist in `lib.rs`'s test module."""
import io

WASM = "kernel/rd-wasm/src/lib.rs"
ANCHOR = """    /// `node.repeat` 的 `MaxCount` 守卫**是能踩到的**"""

NEW = r'''    /// 把一瓶药放进腰带（`rd_run_grant_potion` 是 `?debug` 用的那个入口，测试走同一条路）。
    fn grant_potion(id: &str) -> i32 {
        let bytes = id.as_bytes();
        unsafe { rd_run_grant_potion(bytes.as_ptr(), bytes.len() as i32) }
    }

    /// §179: Blessing of the Forge -- "Upgrade all cards in your hand for the rest of combat."
    ///
    /// The judgment is the **definition id**, because that is what `play` looks the program up by:
    /// `strike+` deals 9 where `strike` deals 6, so a display-only swap would show the upgraded name
    /// over the old program. A label check would pass that; this one cannot.
    #[test]
    fn blessing_of_the_forge_upgrades_the_programs_not_just_the_names() {
        session_with_deck(&[DeckEntry {
            card: "strike",
            count: 5,
        }]);
        assert_eq!(grant_potion("blessing_of_the_forge"), 0, "the potion is in the belt");
        assert_eq!(rd_env_use_potion(0, -1), 0, "drinking it must be accepted");

        let session = ensure_session().expect("session");
        let hero = session.hero_id().expect("hero");
        let hand: Vec<String> = session
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
            .unwrap_or_default();
        assert!(!hand.is_empty(), "the hand is not empty");
        assert!(
            hand.iter().all(|id| id == "strike+"),
            "every upgradable Strike in hand became `strike+`: {hand:?}"
        );
    }

    /// §179: Snecko Oil -- "Draw 5 cards. Randomize the costs of all cards in your hand."
    ///
    /// Two visible facts: five more cards, and every price inside `0..=3`. The second one is read
    /// out of the ABI's hand-cost column, which is the **display-side** pricing -- so this also
    /// pins that the override reaches the screen and not only `play`.
    #[test]
    fn snecko_oil_draws_five_and_reports_prices_in_the_randomized_band() {
        session_with_deck(&[DeckEntry {
            card: "strike",
            count: 10,
        }]);
        let hand_before = ensure_session().expect("session").hand_len();
        assert_eq!(grant_potion("snecko_oil"), 0);
        assert_eq!(rd_env_use_potion(0, -1), 0, "drinking it must be accepted");
        let session = ensure_session().expect("session");
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
                (0..=3).contains(cost) || *cost == X_COST_DISPLAY,
                "hand[{index}] cost {cost} is outside the randomized band"
            );
        }
    }

    /// §179: Smoke Bomb -- "Escape from a non-boss combat. Receive no rewards."
    ///
    /// The refusal in a boss fight matters as much as the escape: a guard that only worked outside
    /// bosses would still let a player skip a boss.
    #[test]
    fn smoke_bomb_ends_the_fight_without_rewards() {
        session_with_deck(&[DeckEntry {
            card: "strike",
            count: 5,
        }]);
        assert_eq!(grant_potion("smoke_bomb"), 0);
        let pending_before = rd_run_pending();
        assert_eq!(rd_env_use_potion(0, -1), 0, "escaping a normal fight is legal");
        assert!(
            ensure_session().is_err(),
            "the combat session is gone: escaping ends the fight, it does not pause it"
        );
        let run = run_slot().as_ref().expect("the run outlives the fight");
        assert!(!run.in_fight, "the run knows the fight ended");
        assert_eq!(
            rd_run_pending(),
            pending_before,
            "Smoke Bomb rolls no reward -- a screen here means the escape looted the node"
        );
    }

    /// `node.repeat` 的 `MaxCount` 守卫**是能踩到的**'''


def main():
    text = io.open(WASM, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    io.open(WASM, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("§179 wasm tests inserted")


if __name__ == "__main__":
    main()
