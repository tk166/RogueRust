"""rd-core: one more test — the choice mechanism honours its **source**.

`ChoiceSource::DiscardPile` has no content yet (Liquid Memories also needs a per-copy price, which
is §161.4). Leaving it in the enum without a test would be exactly the "frozen capability with no
caller" this project keeps refusing; leaving it out would make the next potion a second state
machine. So it stays, and this pins that the mechanism reads `source` instead of assuming `Hand`.
"""
import io

PATH = "kernel/rd-core/src/state.rs"

ANCHOR = """    #[test]
    fn a_choice_that_could_never_be_answered_is_refused_up_front() {"""

TEST = '''    #[test]
    fn a_choice_reads_its_source_pile_instead_of_assuming_the_hand() {
        // §161.3 ships `ChoiceSource::{Hand, DiscardPile}` and **only `Hand` has content today**
        // (Elixir, Gambler's Brew). `DiscardPile` is Liquid Memories' half of the mechanism, and it
        // waits for §161.4's per-copy price -- so it is here without a caller.
        //
        // That is only defensible if the variant is **tested**, otherwise "the source is read"
        // is a claim nobody checked and the next potion would find out. Both directions:
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
        assert_eq!(discarded.len(), 1);

        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::DiscardPile,
            min: 0,
            max: 1,
            then: ChoiceThen::Exhaust,
        })
        .unwrap();
        let mut buf = [CardInstanceId::EMPTY; 8];
        assert_eq!(s.choice_legal(&mut buf), Ok(1));
        assert_eq!(&buf[..1], discarded.as_slice(), "the options are the discard pile");

        // A hand card is **not** an option, even though it is the same combatant's card.
        assert_eq!(s.resolve_choice(&[hand[1]]), Err(ChoiceError::NotInSource));
        // The discarded one is, and it lands where `then` says.
        assert_eq!(
            s.resolve_choice(&discarded),
            Ok(ChoiceDone {
                picked: 1,
                drawn: 0
            })
        );
        assert_eq!(pile_ids(&s, CardZone::ExhaustPile), discarded);
    }

    #[test]
    fn a_choice_that_could_never_be_answered_is_refused_up_front() {'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "a_choice_reads_its_source_pile" not in text, "already inserted"
    text = text.replace(ANCHOR, TEST)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("state.rs: the source-pile test")


if __name__ == "__main__":
    main()
