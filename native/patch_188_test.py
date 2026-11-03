"""§188 tests: an option is a **list**, and the list is all-or-nothing.

Three properties, none implied by the others:

1. two effects both land (Golden Idol: relic **and** curse) -- the thing effect lists exist for;
2. a refusal in the middle leaves the run **byte-for-byte** where it was (`RunState` is `Copy`, so the
   snapshot is exact and the assertion can be `assert!(run == before)`);
3. two deck edits are refused (`TwoDeckChanges`) instead of silently dropping one.
"""
import io

STATE = "kernel/rd-run/src/state.rs"

ANCHOR = """    #[test]
    fn an_event_can_give_a_curse_but_only_a_real_one() {"""

NEW = r'''    /// §188: one option, two effects -- the "relic **and** curse" pair the gap doc named in §143.
    #[test]
    fn an_event_option_can_apply_several_effects_at_once() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol").expect("opening the event");
        let gold_before = run.gold();
        let deck_before = run.deck_len;

        run.resolve_event_effects(
            &[
                (EventEffect::GainRelic, Some("golden_idol")),
                (EventEffect::GainCurse, Some("injury")),
                (EventEffect::Gold(7), None),
            ],
            &pool,
        )
        .expect("the list applies");

        assert_eq!(run.gold(), gold_before + 7, "the gold half landed");
        assert_eq!(run.deck_len, deck_before + 1, "the curse half landed");
        assert!(
            run.deck().iter().any(|card| card.as_str() == "injury"),
            "the deck holds the curse"
        );
        assert_eq!(run.pending(), Pending::None, "no pick is owed");
    }

    /// §188: a list that fails **in the middle** must not half-apply.
    ///
    /// The second entry is a curse naming a card the pool does not know, which `apply_event_effect`
    /// refuses; the gold from the first entry must be rolled back with it.
    #[test]
    fn a_failing_effect_rolls_the_whole_list_back() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol").expect("the event");
        let before = run;

        let outcome = run.resolve_event_effects(
            &[
                (EventEffect::Gold(30), None),
                (EventEffect::GainCurse, Some("no_such_curse")),
            ],
            &pool,
        );
        assert!(outcome.is_err(), "an unknown curse must be refused");
        // `RunState` is `Copy` and `PartialEq` precisely so this is one assertion, not a field list.
        assert!(run == before, "a refused list must not move a single byte");
    }

    /// §188: two deck edits cannot both be honoured (there is one pending pick), so they are refused
    /// rather than silently losing one.
    #[test]
    fn two_deck_edits_in_one_option_are_refused() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("ancient_forge").expect("the event");
        let before = run;
        let outcome = run.resolve_event_effects(
            &[(EventEffect::RemoveCard, None), (EventEffect::UpgradeCard, None)],
            &pool,
        );
        assert_eq!(outcome, Err(RunError::TwoDeckChanges));
        assert!(run == before, "nothing was applied");
    }

    #[test]
    fn an_event_can_give_a_curse_but_only_a_real_one() {'''


def main():
    text = io.open(STATE, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    io.open(STATE, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("rd-run tests inserted")


if __name__ == "__main__":
    main()
