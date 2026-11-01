"""P1-1 wiring (2): the deck borrow must live entirely inside the fallible block.

`counts` held `&'static str` from `session.state.deck()` and was declared *outside* the block, so its
borrow outlived it and the rollback (`&mut session`) could not be written. Moving the compression
inside the block is also the clearer statement: the deck slice is an input to *building* the fight,
and nothing after the commit needs it.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

OLD = """    // The run's deck, compressed into (id, count) entries. Leaked because `FightPlan` borrows them
    // for the session's lifetime -- one small slice per fight, same trade as `build_session`.
    let mut counts: Vec<(&'static str, u16)> = Vec::new();
    for id in session.state.deck() {
        let id = id.as_str();
        match counts.iter_mut().find(|(name, _)| *name == id) {
            Some((_, count)) => *count += 1,
            None => counts.push((id, 1)),
        }
    }
    let entries: &'static [rd_core::battle::DeckEntry<'static>] =
        Box::leak(
            counts
                .into_iter()
                .map(|(card, count)| rd_core::battle::DeckEntry { card, count })
                .collect::<Vec<_>>()
                .into_boxed_slice(),
        );

    let max_health = session.state.health_max();"""

NEW = """    let max_health = session.state.health_max();"""

OLD_BLOCK = """    let failure: Option<std::string::String> = {
        match crate::build_session_at("""

NEW_BLOCK = """    let failure: Option<std::string::String> = {
        // The run's deck, compressed into (id, count) entries. Leaked because `FightPlan` borrows them
        // for the session's lifetime -- one small slice per fight, same trade as `build_session`.
        // §170: 这段**必须在块内**，它借的是 `session.state`；借用活过提交点，回滚就拿不到 `session`。
        let mut counts: Vec<(&'static str, u16)> = Vec::new();
        for id in session.state.deck() {
            let id = id.as_str();
            match counts.iter_mut().find(|(name, _)| *name == id) {
                Some((_, count)) => *count += 1,
                None => counts.push((id, 1)),
            }
        }
        let entries: &'static [rd_core::battle::DeckEntry<'static>] =
            Box::leak(
                counts
                    .into_iter()
                    .map(|(card, count)| rd_core::battle::DeckEntry { card, count })
                    .collect::<Vec<_>>()
                    .into_boxed_slice(),
            );
        match crate::build_session_at("""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in [(OLD, NEW), (OLD_BLOCK, NEW_BLOCK)]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("P1-1: the deck borrow lives inside the build block")


if __name__ == "__main__":
    main()
