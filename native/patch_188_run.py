"""§188: the run layer applies **a list** of effects, atomically.

Three properties, and each one is why the old single-effect signature could not just be called in a
loop:

1. **atomic** -- "拒绝 ⇒ 一个字节都不改" is this project's rule for every refusal. `RunState` is `Copy`
   (that is not an accident: it exists so this is possible), so a snapshot/restore is exact.
2. **at most one deck edit** -- `remove_card` / `upgrade_card` / `transform_card` become a *pending
   pick* (`Pending::EventCard`), and there is room for exactly one pending pick. A second one is a
   content bug, and it must be refused rather than silently replacing the first.
3. **the phase closes once** -- with no deck edit the event finishes here (`Pending::None` +
   `mark_resolved`), which is the same tail the single-effect version had.
"""
import io

PATH = "kernel/rd-run/src/state.rs"

NEW_FN = '''    /// §188：**一串**效果，按顺序应用；任何一条失败 ⇒ 整个 `RunState` 回到调用前（逐字节）。
    ///
    /// 为什么不是"循环调 `resolve_event`"：那样第二次调用会看到 `Pending::None`（第一次已经收尾），
    /// 于是"遗物 + 诅咒"变成"遗物，然后拒绝"；而如果第一次就成功收尾，第二半就丢了。
    ///
    /// 改牌类效果（`remove_card` / `upgrade_card` / `transform_card`）**最多一条**：它们变成一个
    /// 待答问题（`Pending::EventCard`），而队列里只有一个位置。两个就是内容错误 ⇒ `TwoDeckChanges`。
    pub fn resolve_event_effects(
        &mut self,
        effects: &[(EventEffect, Option<&str>)],
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::Event {
            return Err(RunError::WrongPhase);
        }
        let before = *self;
        let mut follow: Option<DeckChange> = None;
        for (effect, _named) in effects {
            if let Some(change) = effect.deck_change() {
                if follow.is_some() {
                    *self = before;
                    return Err(RunError::TwoDeckChanges);
                }
                if before.deck_len == 0 {
                    *self = before;
                    return Err(RunError::DeckEmpty);
                }
                follow = Some(change);
                continue;
            }
            if let Err(error) = self.apply_event_effect(*effect, *_named, pool) {
                *self = before;
                return Err(error);
            }
        }
        match follow {
            Some(change) => {
                self.event_follow = Some(change);
                self.pending = Pending::EventCard;
            }
            None => {
                self.pending = Pending::None;
                self.mark_resolved();
            }
        }
        Ok(())
    }

'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    if "pub fn resolve_event_effects" in text:
        print("already there")
        return
    anchor = """    /// One closed-vocabulary effect. Shared by `?` rooms and by the pre-run blessing, so the two
    /// cannot drift."""
    assert text.count(anchor) == 1, text.count(anchor)
    text = text.replace(anchor, NEW_FN + anchor)

    # the new error variant, next to the event-effect ones
    err_anchor = """    /// An effect that needs a deck index while the deck is empty. There is nothing to point at, so
    /// "pick a card" would be a screen with no way forward.
    DeckEmpty,"""
    assert text.count(err_anchor) == 1
    text = text.replace(
        err_anchor,
        err_anchor + """
    /// §188：一个事件选项里出现了**两个**改牌效果。待答问题只有一个位置，所以第二个会被静默丢掉
    /// —— 拒绝比丢一半好。
    TwoDeckChanges,""",
    )
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("resolve_event_effects + TwoDeckChanges added")


if __name__ == "__main__":
    main()
