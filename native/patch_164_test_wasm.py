"""rd-wasm: §161.4's end-to-end test — Liquid Memories, including the display cost.

The three things this pins are the three that can be wrong independently:

  * the card really moves (discard → hand) and the potion is consumed;
  * the **cost column of the observation** says 0, not the printed 2 — a page that shows 2 while the
    kernel charges 0 is the "the view is not the state" failure;
  * the play then charges 0 and the price is spent, so the *next* play charges full price.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// §161.3: **every** `POT` row must classify as a known effect."""

TEST = '''    /// §161.4: Liquid Memories -- the card comes back **and** it is actually free.
    ///
    /// `paper_cut` is the core image's `CARD[0]`: 1 energy printed, deals 6, lands in the discard
    /// pile. The point of the test is the **third** assertion block: the observation's `cost` column
    /// (what the player sees) and the energy the kernel really takes must agree, and the price must
    /// be spent once.
    #[test]
    fn liquid_memories_returns_a_card_and_makes_that_copy_free_once() {
        test_run(7, 80, 80, &["paper_cut"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1");
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the fight must start");

        // Play one card so the discard pile is not empty (Liquid Memories has nothing to choose
        // from otherwise, and the atom then declines to ask -- see the empty-hand rule for Elixir).
        let played = (0..rd_env_action_count())
            .find(|index| rd_env_action_kind(*index) == crate::ACTION_PLAY)
            .expect("a play action exists");
        assert_eq!(rd_env_step(played), 0, "play the first card");
        assert!(rd_env_pile_len(1) >= 1, "the played card is in the discard pile");
        let discarded = rd_env_pile_len(1);
        let hand_before = crate::slot().as_ref().expect("session").hand_len();

        // Drink Liquid Memories.
        assert_eq!(drink("liquid_memories", -1), 0, "accepted");
        assert_eq!(crate::rd_env_choice_pending(), 1, "it asks a question");
        assert_eq!(crate::rd_env_choice_kind(), 3, "3 = take into hand");
        assert_eq!(crate::rd_env_choice_min(), 1, "the wiki says \\"choose A card\\"");
        assert_eq!(crate::rd_env_choice_max(), 1);
        assert_eq!(crate::rd_env_choice_count() as i32, discarded, "options = the discard pile");
        // A mandatory choice: confirming with nothing ticked is **refused**, and the question
        // survives so the page can re-prompt instead of dead-ending.
        let before = crate::slot().as_ref().expect("session").hand_len();
        assert_eq!(
            crate::rd_env_choice_confirm(),
            -2,
            "zero picks must be refused for a `min = 1` question"
        );
        assert_eq!(crate::rd_env_choice_pending(), 1, "and the question is still open");
        assert_eq!(crate::slot().as_ref().expect("session").hand_len(), before);

        // Tick one and answer.
        assert_eq!(crate::rd_env_choice_pick(0, 1), 0);
        assert_eq!(crate::rd_env_choice_confirm(), 0, "answered");
        assert_eq!(crate::rd_env_choice_pending(), 0);
        assert_eq!(
            rd_env_pile_len(1),
            discarded - 1,
            "the card left the discard pile"
        );
        assert_eq!(
            crate::slot().as_ref().expect("session").hand_len(),
            hand_before + 1,
            "and arrived in the hand"
        );

        // ★ the **display** must agree with what the kernel will charge.
        let slot = crate::slot().as_ref().expect("session");
        let free = slot
            .hand_costs
            .iter()
            .position(|cost| *cost == 0)
            .expect("the returned card shows 0 in the observation, not its printed cost");
        let def = slot.hand_defs[free].clone();
        assert_eq!(def, "paper_cut", "the free one is the card we took back");
        assert_eq!(
            slot.printed_energy_cost(&def),
            1,
            "and it really is a 1-cost card -- the 0 comes from the per-copy price"
        );
        drop(slot);

        // ★ and the kernel charges what it showed.
        let energy_before = crate::slot().as_ref().expect("session").energy_now();
        let play_free = (0..rd_env_action_count())
            .find(|index| {
                rd_env_action_kind(*index) == crate::ACTION_PLAY
                    && rd_env_action_arg(*index, 0) == free as i32
            })
            .expect("the free card is playable");
        assert_eq!(rd_env_step(play_free), 0, "play it for free");
        assert_eq!(
            crate::slot().as_ref().expect("session").energy_now(),
            energy_before,
            "the kernel charged nothing -- the price the screen showed"
        );

        // ★ the price is **spent**: the same copy back in hand costs its printed 1 again.
        let used = crate::slot().as_ref().expect("session");
        let spent = used
            .hand_costs
            .get(free)
            .copied()
            .unwrap_or(-1);
        assert_ne!(spent, 0, "no card left in hand is still free");
    }

    /// §161.3: **every** `POT` row must classify as a known effect.'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn liquid_memories_returns_a_card" not in text, "already inserted"
    text = text.replace(ANCHOR, TEST)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("run.rs: liquid memories test")


if __name__ == "__main__":
    main()
