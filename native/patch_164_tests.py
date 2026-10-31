"""rd-core: §161.4's two state-level tests.

The third half of §161.4 -- "the price is spent by the play" -- belongs in `play.rs`, where a real
card is played.
"""
import io

PATH = "kernel/rd-core/src/state.rs"

ANCHOR = """    #[test]
    fn a_choice_that_could_never_be_answered_is_refused_up_front() {"""

TESTS = '''    #[test]
    fn a_card_taken_into_hand_carries_its_own_price() {
        // Liquid Memories: take one card out of the discard pile into your hand, free this turn.
        // The price is a **mark counter on that copy** (`standard.card_cost_delta`), which is the
        // reference's model -- a status cannot say "the card you chose is free", because a status
        // prices every card its wearer holds.
        let mut s = hand_of(2);
        let hand = pile_ids(&s, CardZone::Hand);
        s.move_card(
            &cid("hero"),
            CardZone::Hand,
            CardZone::DiscardPile,
            CardSlot::from_index(0),
            ZonePlacement::Bottom,
        )
        .unwrap();
        let discarded = pile_ids(&s, CardZone::DiscardPile);
        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::DiscardPile,
            min: 1,
            max: 1,
            then: ChoiceThen::ToHand,
        })
        .unwrap();
        // The delta is "minus the printed cost", which only the caller can compute. -2 here.
        assert_eq!(
            s.resolve_choice(&discarded, -2),
            Ok(ChoiceDone {
                picked: 1,
                drawn: 0
            })
        );
        assert_eq!(
            pile_ids(&s, CardZone::Hand),
            std::vec![hand[1], discarded[0]],
            "the card is back in hand"
        );
        assert!(
            pile_ids(&s, CardZone::DiscardPile).is_empty(),
            "and no longer in the discard pile"
        );

        // The price rides on the **copy**, so a zone change does not lose it.
        let (_, slot) = s.find_card(&cid("hero"), &discarded[0]).expect("in hand");
        let counter = s.card(slot).expect("a card").mark_counters().iter()
            .find(|counter| counter.key.as_str() == CARD_COST_DELTA_COUNTER)
            .copied()
            .expect("the price is on the card");
        assert_eq!(counter.value, -2);
    }

    #[test]
    fn a_price_given_to_a_choice_that_has_none_is_a_caller_bug() {
        // Three `then`s, one price. Handing a discount to `Exhaust` would either be ignored (a lie:
        // "it is free" -- no) or applied to cards that then get exhausted (pointless). Loud instead.
        let mut s = hand_of(2);
        let hand = pile_ids(&s, CardZone::Hand);
        s.begin_choice(elixir(0, 2)).unwrap();
        assert_eq!(
            s.resolve_choice(&[hand[0]], -2),
            Err(ChoiceError::DeltaNotApplicable)
        );
        assert_eq!(s.pending_choice(), Some(elixir(0, 2)), "and nothing moved");
        // The same answer with the right argument works, so the refusal is about the delta only.
        assert_eq!(
            s.resolve_choice(&[hand[0]], 0),
            Ok(ChoiceDone {
                picked: 1,
                drawn: 0
            })
        );
    }

    #[test]
    fn a_choice_that_could_never_be_answered_is_refused_up_front() {'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "a_card_taken_into_hand_carries_its_own_price" not in text, "already inserted"
    text = text.replace(ANCHOR, TESTS)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("state.rs: §161.4 tests")


if __name__ == "__main__":
    main()
