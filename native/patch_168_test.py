"""Rewrite `taking_and_skipping_a_reward` for §161.8's contract.

The screen's three rows are independent: taking the card leaves the potion and the relic on the
table, taking the same slot twice is `EmptyOffer` (not `WrongPhase`), and `skip_reward` is what
leaves.
"""
import io

PATH = "kernel/rd-run/src/state.rs"

OLD = '''    /// Taking a card adds exactly one and leaves the phase; skipping adds none. Both are one-shot.
    #[test]
    fn taking_and_skipping_a_reward() {
        let mut run = RunState::new(3, 80, 0, &DECK).expect("a run");
        run.roll_reward(&basic_pool(), &[], &[], FightKind::Normal).unwrap();
        let wanted = run.reward().cards()[1].as_str().to_string();
        let deck_before = run.deck().len();
        run.take_card(1).expect("take the second card");
        assert_eq!(run.deck().len(), deck_before + 1);
        assert_eq!(run.deck()[deck_before].as_str(), wanted);
        assert_eq!(run.pending(), Pending::None);
        // A second take from the same screen is an out-of-order action.
        assert_eq!(run.take_card(0), Err(RunError::WrongPhase));

        // Skipping takes nothing.
        run.roll_reward(&basic_pool(), &[], &[], FightKind::Normal).unwrap();
        let deck_before = run.deck().len();
        run.skip_reward().expect("skip");
        assert_eq!(run.deck().len(), deck_before);
        assert_eq!(run.pending(), Pending::None);
        assert_eq!(run.skip_reward(), Err(RunError::WrongPhase));
    }'''

NEW = '''    /// Taking a card adds exactly one; **the screen stays open**; skipping adds none.
    ///
    /// §161.8 changed the first half of this test. `take_card` used to leave the phase, which meant
    /// the potion and the relic rows vanished with it -- an elite's relic was lost by any player who
    /// took the card first (i.e. by everyone). The three rows are independent in StS, and
    /// `take_relic`/`take_potion` already behaved that way; `take_card` was the odd one out.
    #[test]
    fn taking_and_skipping_a_reward() {
        let mut run = RunState::new(3, 80, 0, &DECK).expect("a run");
        run.roll_reward(&basic_pool(), &[], &[], FightKind::Normal).unwrap();
        let wanted = run.reward().cards()[1].as_str().to_string();
        let deck_before = run.deck().len();
        run.take_card(1).expect("take the second card");
        assert_eq!(run.deck().len(), deck_before + 1);
        assert_eq!(run.deck()[deck_before].as_str(), wanted);
        assert_eq!(
            run.pending(),
            Pending::Reward,
            "taking the card must leave the other rows on the table"
        );

        // The same slot again: that row is spent (`EmptyOffer`), not an out-of-order action.
        assert_eq!(run.take_card(1), Err(RunError::EmptyOffer(1)));

        // A different row still works, so two cards can be taken from one screen (StS allows this;
        // the screen only closes when you leave).
        let other = run.reward().cards()[0].as_str().to_string();
        run.take_card(0).expect("the first card is still there");
        assert_eq!(run.deck().len(), deck_before + 2);
        assert_eq!(run.deck()[deck_before + 1].as_str(), other);

        // Leaving is `skip_reward`, and it settles the node.
        run.skip_reward().expect("leave the screen");
        assert_eq!(run.pending(), Pending::None);
        assert_eq!(run.skip_reward(), Err(RunError::WrongPhase));

        // Skipping a fresh screen takes nothing.
        run.roll_reward(&basic_pool(), &[], &[], FightKind::Normal).unwrap();
        let deck_before = run.deck().len();
        run.skip_reward().expect("skip");
        assert_eq!(run.deck().len(), deck_before);
        assert_eq!(run.pending(), Pending::None);
    }'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(OLD) == 1, text.count(OLD)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(OLD, NEW))
    print("test rewritten for the independent rows")


if __name__ == "__main__":
    main()
