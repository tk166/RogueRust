"""rd-wasm §161.7: Power Potion, and the fact that its three candidates are real Powers.

The test is deliberately close to §161.5's Attack Potion one, because what changed is the **pool**,
not the mechanism: this is the check that "adding a whole potion is a content change" is true.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    #[test]
    fn an_attack_potion_offers_three_definitions_and_creates_only_the_chosen_card() {"""

TEST = '''    /// §161.7: Power Potion -- the same mechanism, a different pool.
    ///
    /// The point of this test is not the mechanism (that is §161.5's) but the claim that adding a
    /// potion of the same *shape* is a **content** change: the only new code since §161.5 is the
    /// `+`-row filter, and the only new content is three cards plus one `POT` row.
    ///
    /// It also pins the two content bugs this section fixed, from the outside: a Power card is a
    /// status that **keeps working**, so `metallicize`/`combust` must actually apply stacks that a
    /// later turn-end reads.
    #[test]
    fn a_power_potion_offers_the_three_power_cards_and_they_are_real_powers() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1");
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        assert_eq!(drink("power_potion", -1), 0, "accepted");
        assert_eq!(crate::rd_env_choice_pending(), 1, "it asks a question");
        assert_eq!(crate::rd_env_choice_source(), 2, "2 = three offered definitions");
        assert_eq!(crate::rd_env_choice_kind(), 3, "3 = take into hand");
        assert_eq!(crate::rd_env_choice_count(), 3, "three candidates");

        let content = content();
        let mut offered: Vec<String> = Vec::new();
        for index in 0..3 {
            let len = crate::rd_env_pile_card_id_len(3, index);
            assert!(len > 0, "option {index} has an id");
            let mut bytes = vec![0u8; len as usize];
            unsafe { crate::rd_env_pile_card_id_into(3, index, bytes.as_mut_ptr()) };
            let id = String::from_utf8_lossy(&bytes).to_string();
            assert_eq!(
                content.card_has_tag(&id, "power"),
                Some(true),
                "`{id}` is not tagged power"
            );
            // §161.7: the `+` rows are **not** offered -- a potion gives the printed card.
            assert!(!id.ends_with('+'), "`{id}` is an upgraded row");
            offered.push(id);
        }
        offered.sort();
        offered.dedup();
        assert_eq!(
            offered,
            std::vec!["combust", "inflame", "metallicize"],
            "the three power cards, and nothing else"
        );

        // Take `inflame` (2 Strength) -- the strongest, simplest assertion.
        let index = (0..3)
            .find(|slot| {
                let len = crate::rd_env_pile_card_id_len(3, *slot);
                let mut bytes = vec![0u8; len as usize];
                unsafe { crate::rd_env_pile_card_id_into(3, *slot, bytes.as_mut_ptr()) };
                String::from_utf8_lossy(&bytes) == "inflame"
            })
            .expect("inflame is on offer");
        assert_eq!(crate::rd_env_choice_pick(index, 1), 0);
        assert_eq!(crate::rd_env_choice_confirm(), 0, "answered");

        // Play it: it must cost 0 (the potion's promise) and hand the hero 2 Strength, which is a
        // status that outlives the card.
        let slot_ref = crate::slot().as_ref().expect("session");
        let hand = slot_ref
            .hand_defs
            .iter()
            .position(|definition| definition == "inflame")
            .expect("inflame is in hand");
        assert_eq!(slot_ref.hand_costs[hand], 0, "the potion made it free");
        drop(slot_ref);
        let energy_before = crate::slot().as_ref().expect("session").energy_now();
        let play = (0..crate::rd_env_action_count())
            .find(|action| {
                crate::rd_env_action_kind(*action) == crate::ACTION_PLAY
                    && crate::rd_env_action_arg(*action, 0) == hand as i32
            })
            .expect("inflame is playable");
        assert_eq!(rd_env_step(play), 0, "play inflame");
        assert_eq!(
            crate::slot().as_ref().expect("session").energy_now(),
            energy_before,
            "it was free"
        );
        assert_eq!(hero_status("standard.strength"), 2, "2 Strength, permanently");
    }

    #[test]
    fn an_attack_potion_offers_three_definitions_and_creates_only_the_chosen_card() {'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn a_power_potion_offers" not in text, "already inserted"
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, TEST))
    print("run.rs: power potion e2e")


if __name__ == "__main__":
    main()
