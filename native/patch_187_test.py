"""§187 tests: the ascension dimension, judged on **observable numbers**, both sides of the threshold.

Three things have to be true and none of them is implied by the others:

1. `EACT.ProgramAsc` really replaces the program (`Lagavulin` hits for 20 at A3, 18 at A2);
2. `intent.ascensionAtLeast` really reaches a rule (content that switches a move set);
3. at **A0 nothing moves** -- the 85-case golden corpus and every existing fight are ascension 0, so
   a variant leaking into the base game would be a silent balance change with a green corpus.
"""
import io

HOST = "kernel/rd-core/src/host.rs"
INTENT = "kernel/rd-core/src/intent.rs"

HOST_ANCHOR = """    #[test]
    fn regen_heals_at_the_end_of_the_turn() {"""

HOST_NEW = r'''    /// §187: `EACT.ProgramAsc` + `AscensionMin` -- the same action, two numbers.
    ///
    /// Lagavulin's Attack is the cleanest example in this content: 18 base, **20** from A3
    /// (`wiki_lagavulin.txt`, `Asc|3|20`; it is an Act-1 elite, so the tier is 3). The judgment is
    /// the hero's health, i.e. what the player sees, and it is checked at **A2** (below the
    /// threshold) as well as A3 -- a variant that leaked one level early would pass a one-sided test.
    #[test]
    fn an_ascension_variant_replaces_the_program_at_its_threshold() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (ascension, expected_damage) in [(0u8, 18), (2, 18), (3, 20), (20, 20)] {
            let mut state = arena();
            state.set_ascension(ascension);
            // The image's own id index: no scanning, no hand-copied row number.
            let row = u32::from(
                content
                    .lookup_in("lagavulin.attack", crate::content::EK_EACTION)
                    .expect("lagavulin.attack is in the image")
                    .index,
            );
            let hero_before = health(&state, "hero");
            crate::intent::execute_action(
                &mut state,
                &content,
                &cid("enemy_a"),
                row,
                Some(cid("hero")),
            )
            .expect("the action runs");
            assert_eq!(
                hero_before - health(&state, "hero"),
                expected_damage,
                "A{ascension}: Lagavulin's Attack must deal {expected_damage}"
            );
        }
    }

    #[test]
    fn regen_heals_at_the_end_of_the_turn() {'''


INTENT_ANCHOR = """    /// `CompareOp::apply` is the shared arithmetic behind **nine** of the ten condition kinds, so it"""

INTENT_NEW = r'''    /// §187: `intent.ascensionAtLeast` -- **both** sides of the threshold.
    ///
    /// The comparison is extracted into [`ascension_at_least`] because `condition_matches` needs a
    /// *content term* to run, and this content has no rule using the condition yet (every sourced
    /// A17/18/19 change is a **number**, i.e. `EACT.ProgramAsc`). The dispatch itself -- "the kind is
    /// registered and reachable" -- is pinned by
    /// `condition_kinds_are_the_eleven_registered_wire_names`.
    #[test]
    fn the_ascension_condition_compares_the_fight_level() {
        for (level, value, want) in [
            (0u8, 0, true),
            (0, 1, false),
            (2, 2, true),
            (2, 3, false),
            (3, 17, false),
            (18, 17, true),
            (19, 19, true),
            (20, 19, true),
        ] {
            assert_eq!(
                ascension_at_least(level, value),
                want,
                "ascension {level} >= {value} must be {want}"
            );
        }
    }

    /// The helper the condition uses must agree with the state it reads: `set_ascension` writes the
    /// field `ascension()` returns, and `0` is what a fresh state carries (the corpus depends on it).
    #[test]
    fn a_fresh_state_is_ascension_zero() {
        let state = CombatState::new(crate::state::CombatId::new("c1").unwrap(), 7);
        assert_eq!(state.ascension(), 0);
        assert!(ascension_at_least(state.ascension(), 0));
        assert!(!ascension_at_least(state.ascension(), 1));
    }

    /// `CompareOp::apply` is the shared arithmetic behind **nine** of the ten condition kinds, so it'''


def main():
    for path, anchor, new, label in (
        (HOST, HOST_ANCHOR, HOST_NEW, "host"),
        (INTENT, INTENT_ANCHOR, INTENT_NEW, "intent"),
    ):
        text = io.open(path, encoding="utf-8").read()
        assert text.count(anchor) == 1, (label, text.count(anchor))
        io.open(path, "w", encoding="utf-8", newline="").write(text.replace(anchor, new))
        print("test inserted into", label)


if __name__ == "__main__":
    main()
