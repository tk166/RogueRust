"""P1-1 wiring (3): the deck entries must own their strings.

The blocker was not cosmetic. `DeckEntry<'static>` needed `&'static str`, and `RunId::as_str()` hands
out a reference **into `RunState`'s own storage** -- so the leaked slice pointed at memory the run
still owns. That is why "snapshot, restore on failure" would not compile: restoring writes over the
bytes the deck entries read.

Two ways out, and only one of them is honest:
  * keep aliasing `RunState` and drop the rollback  -- keeps a hazard AND loses the fix;
  * give the entries their own storage (copy the ids out, leak those).

This takes the second. It costs one small permanent allocation per distinct deck card per fight --
the same trade `build_session` already makes for the plan itself, and the reason `P2-3` (the per-fight
`Box::leak`) exists at all. In exchange, a failure after the fight was built can be rolled back
without any reference into the run.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

OLD = """        // The run's deck, compressed into (id, count) entries. Leaked because `FightPlan` borrows them
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
            );"""

NEW = """        // The run's deck, compressed into (id, count) entries, **owning its strings**.
        //
        // §170 `P1-1`: 原来写成 `Vec<(&'static str, u16)>` 直接借 `RunId::as_str()` —— 那是指进
        // `RunState` 自己的存储。于是"失败就恢复 `*session.state = before`"与"牌组项还指着那块内存"
        // 只能二选一：借用检查器拒绝它，而如果绕过检查，回滚会覆写战斗正在读的字节。
        // 拷贝出独立字符串之后，`FightPlan` 与 `RunState` 再无别名，回滚才是安全的。
        let mut counts: Vec<(std::string::String, u16)> = Vec::new();
        for id in session.state.deck() {
            let id = id.as_str();
            match counts.iter_mut().find(|(name, _)| name.as_str() == id) {
                Some((_, count)) => *count += 1,
                None => counts.push((std::string::String::from(id), 1)),
            }
        }
        let entries: &'static [rd_core::battle::DeckEntry<'static>] =
            Box::leak(
                counts
                    .into_iter()
                    .map(|(card, count)| rd_core::battle::DeckEntry {
                        card: Box::leak(card.into_boxed_str()),
                        count,
                    })
                    .collect::<Vec<_>>()
                    .into_boxed_slice(),
            );"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(OLD) == 1, text.count(OLD)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(OLD, NEW))
    print("deck entries own their strings; RunState is no longer aliased by the fight")


if __name__ == "__main__":
    main()
