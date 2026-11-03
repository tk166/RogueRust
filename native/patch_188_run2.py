"""§188 part 2: the new refusal lives in `streams.rs` (where `RunError` is defined)."""
import io

STREAMS = "kernel/rd-run/src/streams.rs"
STATE = "kernel/rd-run/src/state.rs"

VARIANT_ANCHOR = """    /// An effect that needs a deck index while the deck is empty. There is nothing to point at, so
    /// "pick a card" would be a screen with no way forward.
    DeckEmpty,"""

VARIANT = VARIANT_ANCHOR + """
    /// §188：一个事件选项里出现了**两个**改牌效果（`remove_card` / `upgrade_card` /
    /// `transform_card`）。待答的选牌只有一个位置，第二个会被静默丢掉 —— 拒绝比丢一半好。
    TwoDeckChanges,"""

STATE_ANCHOR = """    /// One closed-vocabulary effect. Shared by `?` rooms and by the pre-run blessing, so the two
    /// cannot drift."""

NEW_FN = '''    /// §188：**一串**效果，按顺序应用；任何一条失败 ⇒ 整个 `RunState` 回到调用前（逐字节）。
    ///
    /// 为什么不"循环调 `resolve_event`"：那样第二次调用会看到 `Pending::None`（第一次已经收尾），
    /// 于是"遗物 + 诅咒"变成"遗物，然后拒绝"；而如果第一次就成功收尾，第二半就丢了。
    ///
    /// 改牌类效果（`remove_card` / `upgrade_card` / `transform_card`）**最多一条**：它们变成一个
    /// 待答问题（`Pending::EventCard`），而队列里只有一个位置 ⇒ 两个就是内容错误。
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
        for (effect, named) in effects {
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
            if let Err(error) = self.apply_event_effect(*effect, *named, pool) {
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
    streams = io.open(STREAMS, encoding="utf-8").read()
    if "TwoDeckChanges" not in streams:
        assert streams.count(VARIANT_ANCHOR) == 1, streams.count(VARIANT_ANCHOR)
        streams = streams.replace(VARIANT_ANCHOR, VARIANT)
        io.open(STREAMS, "w", encoding="utf-8", newline="").write(streams)
        print("variant added to RunError")

    state = io.open(STATE, encoding="utf-8").read()
    if "pub fn resolve_event_effects" not in state:
        assert state.count(STATE_ANCHOR) == 1, state.count(STATE_ANCHOR)
        state = state.replace(STATE_ANCHOR, NEW_FN + STATE_ANCHOR)
        io.open(STATE, "w", encoding="utf-8", newline="").write(state)
        print("resolve_event_effects added")


if __name__ == "__main__":
    main()
