"""§182 test: Distilled Chaos plays the top 3 **and pays nothing**.

The "pays nothing" half is the one a naive implementation gets wrong (it would just call
`play_card`, which charges energy), so energy is asserted as a number, not as "it worked".
"""
import io

RUN = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// The hand's definition ids, in pile order (`hand_costs` has the prices)."""

NEW = r'''    /// §182: Distilled Chaos -- "Play the top 3 cards of your draw pile."
    ///
    /// Four judgments, because "the enemy lost HP" is satisfied by almost any implementation:
    /// the draw pile shrank by three, the discard pile grew by three (they really were *played*,
    /// which is what puts them there), the enemy took damage, and **energy did not move**.
    #[test]
    fn distilled_chaos_plays_the_top_three_for_free() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        let piles = |zone: rd_core::state::CardZone| {
            let session = crate::slot().as_ref().expect("env session");
            let hero = session.hero_id().expect("hero");
            session
                .state
                .card_zones(&hero)
                .map_or(0, |zones| zones.count(zone))
        };
        let draw_before = piles(rd_core::state::CardZone::DrawPile);
        assert!(draw_before >= 3, "the draw pile needs three cards, has {draw_before}");
        let discard_before = piles(rd_core::state::CardZone::DiscardPile);
        let energy_before = hero_energy();
        let hp_before = enemy_hp(0);

        assert_eq!(drink("distilled_chaos", -1), 0, "drinking it must work");

        assert_eq!(
            piles(rd_core::state::CardZone::DrawPile),
            draw_before - 3,
            "three cards left the draw pile"
        );
        assert_eq!(
            piles(rd_core::state::CardZone::DiscardPile),
            discard_before + 3,
            "and they were **played**, so they are in the discard pile -- not still in hand"
        );
        assert!(
            enemy_hp(0) < hp_before,
            "three Strikes went somewhere: enemy {hp_before} -> {}",
            enemy_hp(0)
        );
        assert_eq!(
            hero_energy(),
            energy_before,
            "the potion pays, the player does not -- energy must not move"
        );
    }

    /// The hand's definition ids, in pile order (`hand_costs` has the prices).'''


def main():
    text = io.open(RUN, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    io.open(RUN, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("§182 test inserted")


if __name__ == "__main__":
    main()
