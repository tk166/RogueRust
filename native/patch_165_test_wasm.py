"""§161.5: the end-to-end test (Attack Potion) + the tripwire's third category.

The test pins the whole offered path: three candidates that are **definitions**, one card created
on answer, and that card free -- with the observation's cost column agreeing.
"""
import io

RUN = "kernel/rd-wasm/src/run.rs"


def main():
    t = io.open(RUN, encoding="utf-8").read()

    def sub(old, new):
        nonlocal t
        assert t.count(old) == 1, (t.count(old), old[:60])
        t = t.replace(old, new)

    # the "right category" half of the vocabulary tripwire
    sub(
        '        for id in ["elixir", "gamblers_brew", "liquid_memories"] {',
        '        for id in [\n'
        '            "elixir",\n'
        '            "gamblers_brew",\n'
        '            "liquid_memories",\n'
        '            // §161.5: the offered pair acts on the hand too.\n'
        '            "attack_potion",\n'
        '            "skill_potion",\n'
        '        ] {',
    )

    anchor = """    /// §161.4: Liquid Memories -- the card comes back **and** it is actually free."""
        # (anchor text differs; find the real one below)
    real_anchor = """    #[test]
    fn liquid_memories_returns_a_card_and_makes_that_copy_free_once() {"""
    assert t.count(real_anchor) == 1, t.count(real_anchor)

    test = '''    /// §161.5: Attack Potion -- three **definitions**, one card created, and it is free.
    ///
    /// The three things that can be wrong here are independent:
    /// * the candidates are instances created up front (then the fingerprint grows three cards that
    ///   the reference never had);
    /// * the picked card is created but not priced (the screen says 0, the kernel charges 1);
    /// * the pool filter is wrong (a Skill Potion offering attacks, or a tag with no carriers
    ///   silently offering fewer than three).
    #[test]
    fn an_attack_potion_offers_three_definitions_and_creates_only_the_chosen_card() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1");
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        let cards_before = crate::slot().as_ref().expect("session").state.card_count();
        assert_eq!(drink("attack_potion", -1), 0, "accepted");
        assert_eq!(crate::rd_env_choice_pending(), 1, "it asks a question");
        assert_eq!(crate::rd_env_choice_source(), 2, "2 = three offered definitions");
        assert_eq!(crate::rd_env_choice_kind(), 3, "3 = take into hand");
        assert_eq!(crate::rd_env_choice_min(), 1);
        assert_eq!(crate::rd_env_choice_max(), 1);
        assert_eq!(crate::rd_env_choice_count(), 3, "three candidates");
        assert_eq!(
            crate::rd_env_pile_len(3),
            3,
            "the picker reads its options through the pile exports (zone 3)"
        );
        // ★ the question itself must not create cards.
        assert_eq!(
            crate::slot().as_ref().expect("session").state.card_count(),
            cards_before,
            "asking must not mint the three candidates"
        );

        // Every option is an **attack**, and they are three **different** cards.
        let content = content();
        let mut offered: Vec<String> = Vec::new();
        for index in 0..3 {
            let len = crate::rd_env_pile_card_id_len(3, index);
            assert!(len > 0, "option {index} has an id");
            let mut bytes = vec![0u8; len as usize];
            unsafe { crate::rd_env_pile_card_id_into(3, index, bytes.as_mut_ptr()) };
            let id = String::from_utf8_lossy(&bytes).to_string();
            assert_eq!(
                content.card_has_tag(&id, "attack"),
                Some(true),
                "`{id}` is not an attack"
            );
            assert!(
                crate::rd_env_pile_card_title_len(3, index) > 0,
                "option {index} has a title"
            );
            offered.push(id);
        }
        offered.sort();
        offered.dedup();
        assert_eq!(offered.len(), 3, "three **distinct** cards");

        // Pick the first option and answer.
        let picked = {
            let len = crate::rd_env_pile_card_id_len(3, 0);
            let mut bytes = vec![0u8; len as usize];
            unsafe { crate::rd_env_pile_card_id_into(3, 0, bytes.as_mut_ptr()) };
            String::from_utf8_lossy(&bytes).to_string()
        };
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0);
        assert_eq!(crate::rd_env_choice_confirm(), 0, "answered");
        assert_eq!(crate::rd_env_choice_pending(), 0);
        assert_eq!(
            crate::slot().as_ref().expect("session").state.card_count(),
            cards_before + 1,
            "exactly one card was created: the two not chosen never existed"
        );

        // ★ The created card is the picked definition, it is in hand, and it shows **0**.
        let slot_ref = crate::slot().as_ref().expect("session");
        let free = slot_ref
            .hand_defs
            .iter()
            .position(|definition| *definition == picked)
            .expect("the picked card is in the hand");
        assert_eq!(
            slot_ref.hand_costs[free],
            0,
            "the observation must show what the kernel will charge"
        );
        assert!(
            slot_ref.hand_costs[free] != slot_ref.printed_energy_cost(&picked),
            "and that is not its printed cost -- the per-copy price is doing the work"
        );
        drop(slot_ref);

        // ★ …and the kernel charges it: play it, energy must not move.
        let energy_before = crate::slot().as_ref().expect("session").energy_now();
        let play = (0..crate::rd_env_action_count())
            .find(|index| {
                crate::rd_env_action_kind(*index) == crate::ACTION_PLAY
                    && crate::rd_env_action_arg(*index, 0) == free as i32
            })
            .expect("the new card is playable");
        assert_eq!(rd_env_step(play), 0);
        assert_eq!(
            crate::slot().as_ref().expect("session").energy_now(),
            energy_before,
            "a potion that says \\"it costs 0 this turn\\" must charge 0"
        );
    }

    #[test]
    fn liquid_memories_returns_a_card_and_makes_that_copy_free_once() {'''

    t = t.replace(real_anchor, test)
    io.open(RUN, "w", encoding="utf-8", newline="").write(t)
    print("run.rs: attack potion e2e + tripwire category")


if __name__ == "__main__":
    main()
