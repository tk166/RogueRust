"""§181 test: Duplication Potion -- one payment, one card played, two applications.

The three-sided judgment matters here: "the enemy lost 12 HP" is also satisfied by paying twice,
or by counting the card twice (`cards_played_this_turn` feeds `Time Warp`-style rules and the
"nth card" decrees), so each of those is asserted separately.
"""
import io

PLAY = "kernel/rd-core/src/play.rs"

ANCHOR = """    #[test]
    fn the_per_copy_price_is_consumed_by_the_play() {"""

NEW = r'''    /// §181: Duplication Potion -- "This turn, your next card is played twice."
    ///
    /// Three assertions, because "the enemy lost 2× damage" alone is also what a bug that charges
    /// twice (or counts the card twice) would produce:
    /// 1. the damage landed **twice**;
    /// 2. energy was paid **once**;
    /// 3. the card counted as **one** play;
    /// and the charge is spent, so the **next** card is played once.
    #[test]
    fn duplication_plays_the_program_twice_but_pays_and_counts_once() {
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "strike");
        give_card(&mut state, "hero", CardZone::Hand, "card_h2", "strike");
        // `strike` deals 6; `enemy_a` has 20 HP.
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .push_status(
                crate::state::StatusInstance::new(
                    crate::state::StatusInstanceId::new("st_dup").unwrap(),
                    crate::state::StatusDefinitionId::new("standard.duplication").unwrap(),
                    crate::state::StatusPolarity::Buff,
                )
                .with_stacks(1),
            )
            .unwrap();
        let energy_before = energy_of(&state, "hero");
        let played_before = state.cards_played_this_turn;

        let report = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("a duplicated Strike is still playable");
        // Drain so the queued damage actually lands.
        crate::exec::drain(&mut state, Some(&content), None).expect("the effects settle");

        assert!(report.played);
        assert_eq!(
            health_of(&state, "enemy_a"),
            14,
            "6 damage, applied twice -- 20 - 12 = 8 would be `20 - 12`; 14 means once. \
             Read the number, not the intent."
        );
        assert_eq!(
            energy_of(&state, "hero"),
            energy_before - 1,
            "the card is paid for **once**"
        );
        assert_eq!(
            state.cards_played_this_turn,
            played_before + 1,
            "and it counts as **one** card played"
        );

        // The charge is spent: the second Strike is an ordinary one.
        let report = play_card(
            &mut state,
            Some(&content),
            &request("card_h2", Some("enemy_a")),
        )
        .expect("the second Strike plays");
        crate::exec::drain(&mut state, Some(&content), None).expect("the effects settle");
        assert!(report.played);
        assert_eq!(
            health_of(&state, "enemy_a"),
            8,
            "one more Strike is 6, not 12 -- the charge was consumed by the first"
        );
        assert_eq!(
            total_status_stacks(&state.combatant(&cid("hero")).unwrap(), "standard.duplication"),
            0,
            "no charges left"
        );
    }

    #[test]
    fn the_per_copy_price_is_consumed_by_the_play() {'''


def main():
    text = io.open(PLAY, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    io.open(PLAY, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("§181 test inserted")


if __name__ == "__main__":
    main()
