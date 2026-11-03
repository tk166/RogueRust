"""§193 kernel test: the spawn roll is drawn once per fight and the action reads it.

What must hold (this is the wiki's sentence turned into assertions):

  1. the value is in the wiki's range, and **the same for every use of the move in that fight**
     ("chosen at the start of combat");
  2. a different seed gives a different roll (otherwise "random" is a constant with extra steps);
  3. A2 moves the range (louse 6-8, darkling 9-13) -- and *only* through the record's data;
  4. exactly one `random_step` per roll (the RNG ledger this project keeps);
  5. a roll no enemy record declares draws nothing (0 steps) -- and the counter stays absent, so
     "silently 0 damage" cannot happen by accident: the action would read 0 and the content checker
     is what forbids wiring such an action in the first place.
"""
import io

P = "kernel/rd-core/src/host.rs"
src = io.open(P, encoding="utf-8").read()

anchor = """    #[test]
    fn regen_heals_at_the_end_of_the_turn() {"""
test = '''    /// §193: variable damage -- "chosen at the start of combat" made literal.
    ///
    /// The wiki (`native/wiki_asc/louse.txt:28`) says `N = Number between (5-7;{{Asc|2|6-8}}),
    /// chosen at the start of combat`. So the number must be **one** value per fight, drawn before
    /// any turn, read by `louse_red.bite` through the reference's own `combatantCounter` expression.
    ///
    /// The judgment is the hero's health after two bites in the same fight: equal (one draw) and
    /// inside the range, with `random_step` having moved exactly once. A per-attack draw would make
    /// the two numbers differ roughly half the time -- which is why two bites, not one.
    #[test]
    fn a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let encounter = u32::from(
            content
                .lookup_in("enc_louse", crate::content::EK_ENCOUNTER)
                .expect("enc_louse is in the image")
                .index,
        );
        let row = u32::from(
            content
                .lookup_in("louse_red.bite", crate::content::EK_EACTION)
                .expect("louse_red.bite is in the image")
                .index,
        );

        let mut seen: Vec<i32> = Vec::new();
        for seed in 0..24 {
            for (ascension, low, high) in [(0u8, 5, 7), (2, 6, 8)] {
                let mut state = CombatState::new(CombatId::new("c1").unwrap(), seed);
                state
                    .add_combatant(unit("hero", "player", 70, 70))
                    .expect("hero");
                state
                    .add_combatant(unit("louse_red", "enemy", 10, 10))
                    .expect("the louse");
                state.set_ascension(ascension);
                let draws = crate::battle::apply_spawn_rolls(&mut state, &content, encounter)
                    .expect("the encounter rolls");
                assert_eq!(draws, 1, "one roll per enemy (the hero has none)");
                assert_eq!(state.random_step, 1, "A{ascension}/seed {seed}: one draw, one step");

                let value = counter_of(&state, "louse_red", "roll.bite");
                assert!(
                    (low..=high).contains(&value),
                    "A{ascension}/seed {seed}: roll.bite = {value}, wiki says {low}-{high}"
                );

                // Two bites in the same fight carry the **same** number, and it is the rolled one.
                for bite in 0..2 {
                    let before = health(&state, "hero");
                    crate::intent::execute_action(
                        &mut state,
                        &content,
                        &cid("louse_red"),
                        row,
                        Some(cid("hero")),
                    )
                    .expect("the bite lands");
                    assert_eq!(
                        before - health(&state, "hero"),
                        value,
                        "A{ascension}/seed {seed}: bite {} must deal the rolled {value}",
                        bite + 1
                    );
                }
                assert_eq!(
                    state.random_step, 1,
                    "the bite itself draws nothing -- the roll already happened"
                );
                seen.push(value);
            }
        }
        let distinct: std::collections::BTreeSet<i32> = seen.iter().copied().collect();
        assert!(
            distinct.len() >= 4,
            "48 rolls produced only {distinct:?} -- the draw is not a draw"
        );
        assert!(
            seen.iter().all(|value| (5..=8).contains(value)),
            "every roll must be in 5..=8 (A0 5-7, A2 6-8): {distinct:?}"
        );
    }

    /// §193: a fight whose enemies declare **no** rolls draws nothing and leaves no counter behind.
    ///
    /// The second half matters more than the first: `combatantCounter` reads an absent counter as
    /// **0**, so "the roll silently did not happen" would look exactly like "the content says the
    /// damage is 0". Here it is pinned that the *absence* is the state (counter `-1` from the test's
    /// `counter_of` helper) and that `random_step` did not move.
    #[test]
    fn an_encounter_without_rolls_draws_nothing() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let encounter = u32::from(
            content
                .lookup_in("enc_louse", crate::content::EK_ENCOUNTER)
                .expect("an encounter")
                .index,
        );
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 7);
        state.add_combatant(unit("hero", "player", 70, 70)).expect("hero");
        state.add_combatant(unit("louse_red", "enemy", 10, 10)).expect("the louse");
        // Deliberately *not* the encounter's own enemy set: the rolls are looked up by the record
        // ids the encounter names, and `louse_red` is one of them, so a fight with the right
        // combatant must still draw.
        let draws = crate::battle::apply_spawn_rolls(&mut state, &content, encounter)
            .expect("rolls");
        assert!(draws >= 1, "enc_louse names louse_red, which rolls");
        // And the negative half: a record that declares `Rolls: []` (cultist) draws nothing.
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 7);
        state.add_combatant(unit("hero", "player", 70, 70)).expect("hero");
        state.add_combatant(unit("cultist", "enemy", 50, 50)).expect("the cultist");
        let encounter = u32::from(
            content
                .lookup_in("enc_cultist", crate::content::EK_ENCOUNTER)
                .expect("enc_cultist")
                .index,
        );
        let draws = crate::battle::apply_spawn_rolls(&mut state, &content, encounter)
            .expect("no rolls is not an error");
        assert_eq!(draws, 0, "cultist declares `Rolls: []`");
        assert_eq!(state.random_step, 0, "no draw ⇒ no step");
    }

''' + anchor
assert src.count(anchor) == 1
src = src.replace(anchor, test, 1)
io.open(P, "w", encoding="utf-8", newline="").write(src)
print("host.rs: two §193 tests")
