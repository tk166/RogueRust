"""§183 test: the Colorless Potion asks a question whose answers are colorless cards.

The atom (`choice_offered:<tag>`) already existed; what this pins is that the **pool it offers** is
the colorless one -- and that picking an answer really puts that card in the hand. A potion that
offered three Strikes would satisfy "a picker appeared" and be wrong.
"""
import io

RUN = "kernel/rd-wasm/src/run.rs"
ANCHOR = """    /// The hand's definition ids, in pile order (`hand_costs` has the prices)."""

NEW = r'''    /// §183: Colorless Potion -- "Choose 1 of 3 random Colorless cards to add to your hand."
    ///
    /// Three judgments: the question is an **offered** one (`source = 2`, §161.5), it has exactly
    /// three answers, and every answer is a colorless card from this content. Then the pick lands
    /// in the hand -- because "a picker appeared" is not the potion.
    #[test]
    fn colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        let hand_before = hand_ids();
        assert_eq!(drink("colorless_potion", -1), 0, "drinking it opens the question");

        // §161.5: `ChoiceSource::Offered` is `2` in the ABI, and the potion is consumed either way.
        assert_eq!(crate::rd_env_choice_pending(), 1, "the picker is waiting");
        assert_eq!(crate::rd_env_choice_source(), 2, "an Offered question");
        let options = crate::rd_env_choice_count();
        assert_eq!(options, 3, "`1 of 3`, exactly");

        let mut names = Vec::new();
        for slot in 0..options {
            let length = crate::rd_env_pile_card_len(3, slot);
            assert!(length > 0, "option {slot} has a name");
            let mut buffer = vec![0u8; length as usize];
            unsafe { crate::rd_env_pile_card_into(3, slot, buffer.as_mut_ptr()) };
            names.push(String::from_utf8(buffer).expect("ascii ids"));
        }
        let colorless = ["bandage_up", "blind", "dark_shackles"];
        for name in &names {
            assert!(
                colorless.contains(&name.as_str()),
                "{name} is not a colorless card -- the pool leaked: {names:?}"
            );
        }

        // Pick the first answer and confirm.
        assert_eq!(crate::rd_env_pile_pick(3, 0), 0, "tick the first option");
        assert_eq!(crate::rd_env_choice_confirm(), 0, "confirm it");
        assert_eq!(crate::rd_env_choice_pending(), 0, "the question is answered");

        let hand_after = hand_ids();
        assert_eq!(
            hand_after.len(),
            hand_before.len() + 1,
            "the chosen card is in the hand: {hand_after:?}"
        );
        let added: Vec<&String> = hand_after
            .iter()
            .filter(|id| colorless.contains(&id.as_str()))
            .collect();
        assert_eq!(added.len(), 1, "exactly one colorless card joined: {hand_after:?}");
    }

    /// The hand's definition ids, in pile order (`hand_costs` has the prices).'''


def main():
    text = io.open(RUN, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    io.open(RUN, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("§183 test inserted")


if __name__ == "__main__":
    main()
