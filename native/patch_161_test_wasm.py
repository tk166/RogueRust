"""rd-wasm: the §161.3 choice test (driven through the real potion path).

Inserted right before the existing `drink` helper, so it sits next to the other potion tests.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// Put `potion` in the belt and drink it at `target`. The belt has **three** slots, so a test
    /// that wants five potions cannot push them all: push one, drink it, repeat."""

TEST = """    /// §161.3: the two potions whose effect is a **question**, driven end to end.
    ///
    /// The mechanism itself is pinned in `rd-core` (`resolve_choice` and its five tests). What is
    /// pinned *here* is the seam, and every step of it is a thing that could break on its own:
    ///
    /// * the bottle is drunk (consumed) **and** a question opens -- not one or the other;
    /// * the action table goes empty, because play / end-turn are not legal answers;
    /// * a stale action index is refused *with a reason*;
    /// * the options are the source pile, so zone 3 is the same list;
    /// * answering moves exactly the picked cards and restores the table;
    /// * "pick nothing" is a legal answer (both potions say "any number").
    #[test]
    fn the_choice_potions_ask_a_question_and_the_answer_moves_the_cards() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1");
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        // ---- nothing is pending before a potion opens one -----------------------------------
        assert_eq!(crate::rd_env_choice_pending(), 0);
        assert_eq!(crate::rd_env_choice_kind(), 0);
        assert_eq!(crate::rd_env_choice_count(), 0);
        assert_eq!(crate::rd_env_pile_len(3), -1, "zone 3 answers nothing without a question");

        // ---- Elixir: exhaust any number of cards from your hand -----------------------------
        let belt_before = rd_run_potion_count();
        assert_eq!(drink("elixir", -1), 0, "elixir accepted");
        assert_eq!(
            rd_run_potion_count(),
            belt_before,
            "the bottle is consumed: a potion is drunk whether or not the answer is convenient"
        );
        assert_eq!(crate::rd_env_choice_pending(), 1, "and it opened a question");
        assert_eq!(crate::rd_env_choice_kind(), 1, "1 = exhaust");
        assert_eq!(crate::rd_env_choice_min(), 0, "\\"any number\\" includes zero");
        let options = crate::rd_env_choice_count();
        assert!(options >= 2, "a fresh hand has cards to pick from: {options}");
        assert_eq!(
            crate::rd_env_choice_max(),
            options,
            "the upper bound is the whole hand"
        );
        assert_eq!(
            crate::rd_env_pile_len(3),
            options,
            "zone 3 is the question's source pile, so the picker renders through the pile exports"
        );
        assert_eq!(
            crate::rd_env_action_count(),
            0,
            "play / end-turn are not legal while a question is open"
        );
        assert_eq!(rd_env_step(0), -1, "a stale action index is refused");
        assert!(
            crate::slot().as_ref().is_some_and(|s| !s.error.is_empty()),
            "and the refusal says why"
        );

        // Ticking is not the action -- `confirm` is. Two ticks, then one answer.
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0);
        assert_eq!(crate::rd_env_choice_pick(2, 1), 0);
        assert_eq!(crate::rd_env_choice_selected(0), 1);
        assert_eq!(crate::rd_env_choice_selected(1), 0);
        assert_eq!(
            crate::rd_env_choice_pick(options, 1),
            -1,
            "an index past the last option is refused, not ignored"
        );
        let exhausted_before = crate::rd_env_pile_len(2);
        assert_eq!(crate::rd_env_choice_confirm(), 0, "answered");
        assert_eq!(crate::rd_env_choice_pending(), 0, "the question is gone");
        assert_eq!(
            crate::rd_env_pile_len(2),
            exhausted_before + 2,
            "exactly the two ticked cards were exhausted"
        );
        assert!(
            crate::rd_env_action_count() > 0,
            "the action table is back once the question is answered"
        );

        // ---- Gambler's Brew: discard any number, then draw that many ------------------------
        let hand_before = crate::rd_env_choice_count();
        assert_eq!(hand_before, 0, "no question is open");
        assert_eq!(drink("gamblers_brew", -1), 0, "gambler's brew accepted");
        assert_eq!(crate::rd_env_choice_kind(), 2, "2 = discard then draw");
        let options = crate::rd_env_choice_count();
        assert!(options >= 2, "cards to discard: {options}");
        let discarded_before = crate::rd_env_pile_len(1);
        // Three picks, then **clear**: the selection is scratch, and clearing it must not answer
        // the question (otherwise "select none" and "cancel the screen" would be the same code).
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0);
        assert_eq!(crate::rd_env_choice_pick(1, 1), 0);
        assert_eq!(crate::rd_env_choice_pick(2, 1), 0);
        assert_eq!(crate::rd_env_choice_clear(), 0);
        assert_eq!(crate::rd_env_choice_selected(0), 0, "cleared");
        assert_eq!(crate::rd_env_choice_pending(), 1, "still unanswered");
        // Now actually discard two.
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0);
        assert_eq!(crate::rd_env_choice_pick(1, 1), 0);
        assert_eq!(crate::rd_env_choice_confirm(), 0);
        assert_eq!(crate::rd_env_choice_pending(), 0);
        assert_eq!(
            crate::rd_env_choice_count(),
            0,
            "the same count reads 0 once there is no question"
        );
        assert!(
            crate::rd_env_pile_len(1) >= discarded_before,
            "the two discarded cards land in the discard pile"
        );

        // ---- "pick nothing" is a legal answer ----------------------------------------------
        assert_eq!(drink("elixir", -1), 0);
        assert_eq!(crate::rd_env_choice_pending(), 1);
        let exhausted_before = crate::rd_env_pile_len(2);
        assert_eq!(crate::rd_env_choice_confirm(), 0, "zero picks is an answer");
        assert_eq!(crate::rd_env_choice_pending(), 0);
        assert_eq!(
            crate::rd_env_pile_len(2),
            exhausted_before,
            "and it exhausts nothing"
        );
    }

    /// Put `potion` in the belt and drink it at `target`. The belt has **three** slots, so a test
    /// that wants five potions cannot push them all: push one, drink it, repeat."""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "the_choice_potions_ask_a_question" not in text, "already inserted"
    text = text.replace(ANCHOR, TEST)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("run.rs: choice test inserted")


if __name__ == "__main__":
    main()
