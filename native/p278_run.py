"""§278：run 层加 `event_step` / `event_next`，`resolve_event_effects` 收 `next`。"""
import io
import re

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ---------------------------------------------------------------- 字段
    s = patch(s, '''    /// The `?`-room event under the cursor, while `Pending::Event`.
    event: RunId,''','''    /// The `?`-room event under the cursor, while `Pending::Event`.
    event: RunId,
    /// §278：这个事件**现在走到哪一段**（`EVND.Id`）。空 = 还没开事件。
    ///
    /// 为什么不把它放在 `rd-wasm`：页面要知道"现在显示哪段正文、有哪几个按钮"，而那是
    /// **局面**的一部分 —— 同一句 `event=golden_idol` 可以是两个完全不同的屏幕。
    event_step: RunId,
    /// §278：这一段选完之后要去的那一段，**在等一次牌组编辑的时候**先记在这里。
    ///
    /// 与 `event_follow` 是两件事：一个是"欠哪次编辑"，一个是"编辑完了去哪儿"。
    event_next: RunId,''')

    s = patch(s, '''            event: RunId::EMPTY,''','''            event: RunId::EMPTY,
            event_step: RunId::EMPTY,
            event_next: RunId::EMPTY,''')

    # ---------------------------------------------------------------- 访问器
    s = patch(s, '''    /// The event under the cursor (empty until [`RunState::begin_event`]).
    #[must_use]
    pub fn event(&self) -> &str {
        self.event.as_str()
    }''','''    /// The event under the cursor (empty until [`RunState::begin_event`]).
    #[must_use]
    pub fn event(&self) -> &str {
        self.event.as_str()
    }

    /// §278：事件**当前所在的那一段**（`EVND.Id`）。空 = 这个事件只有一段（或还没开）。
    #[must_use]
    pub fn event_step(&self) -> &str {
        self.event_step.as_str()
    }''')

    # ---------------------------------------------------------------- begin_event
    s = patch(s, '''    pub fn begin_event(&mut self, id: &str) -> Result<(), RunError> {
        if self.node_resolved() {
            return Err(RunError::NodeResolved);
        }
        let id = RunId::new(id).map_err(|_| RunError::NoSuchEvent)?;
        self.event = id;
        self.pending = Pending::Event;
        Ok(())
    }''','''    /// 打开 `?` 房的事件。`entry` 是内容里这一段事件的**入口节点**（`EV.Entry`）。
    ///
    /// 为什么入口由调用方给：run 层**不读内容**（这条纪律从 §133 就在）。它只记住
    /// "这个事件从哪一段开始"，于是页面要显示哪一段正文是**状态**，不是每次重算的推导。
    pub fn begin_event(&mut self, id: &str, entry: &str) -> Result<(), RunError> {
        if self.node_resolved() {
            return Err(RunError::NodeResolved);
        }
        let id = RunId::new(id).map_err(|_| RunError::NoSuchEvent)?;
        let entry = RunId::new(entry).map_err(|_| RunError::NoSuchEvent)?;
        self.event = id;
        self.event_step = entry;
        self.event_next = RunId::EMPTY;
        self.pending = Pending::Event;
        Ok(())
    }''')

    # ---------------------------------------------------------------- resolve_event（单条）
    s = patch(s, '''        self.apply_event_effect(effect, named, pool)?;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }''','''        self.apply_event_effect(effect, named, pool)?;
        self.pending = Pending::None;
        self.event_step = RunId::EMPTY;
        self.mark_resolved();
        Ok(())
    }''')

    # ---------------------------------------------------------------- resolve_event_effects
    s = patch(s, '''    /// 改牌类效果（`remove_card` / `upgrade_card` / `transform_card`）**最多一条**：它们变成一个
    /// 待答问题（`Pending::EventCard`），而队列里只有一个位置 ⇒ 两个就是内容错误。
    pub fn resolve_event_effects(
        &mut self,
        effects: &[(EventEffect, Option<&str>)],
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::Event {
            return Err(RunError::WrongPhase);
        }''','''    /// 改牌类效果（`remove_card` / `upgrade_card` / `transform_card`）**最多一条**：它们变成一个
    /// 待答问题（`Pending::EventCard`），而队列里只有一个位置 ⇒ 两个就是内容错误。
    ///
    /// `next`（§278）是这一段选完之后要去的那一段：`Some` ⇒ 应用完效果**收在同一段事件的下一步**，
    /// `Pending` 仍是 `Event`、房间**不结算**；`None` ⇒ 照旧收尾。这就是"事件是一棵树"的全部
    /// 运行层实现 —— 没有第二套状态机，只有"这一段做完了"与"还有下一段"。
    pub fn resolve_event_effects(
        &mut self,
        effects: &[(EventEffect, Option<&str>)],
        next: Option<&str>,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::Event {
            return Err(RunError::WrongPhase);
        }
        // `next` 在动手之前就要验：一个坏 id 必须在**一个字节都没改**之前被拒。
        let next_id = match next {
            Some(next) => RunId::new(next).map_err(|_| RunError::NoSuchEvent)?,
            None => RunId::EMPTY,
        };''')

    s = patch(s, '''        match follow {
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
    }''','''        match follow {
            Some(change) => {
                self.event_follow = Some(change);
                // 编辑完了还要去下一段：**先记下来**，等 `pick_event_card` 收尾时再走。
                self.event_next = next_id;
                self.pending = Pending::EventCard;
            }
            None if next_id.as_str().is_empty() => {
                self.pending = Pending::None;
                self.event_step = RunId::EMPTY;
                self.mark_resolved();
            }
            None => {
                self.event_step = next_id;
                self.event_next = RunId::EMPTY;
                // 还留在 `Pending::Event`：玩家面前换了一段正文/一组按钮，房间没结算。
                self.pending = Pending::Event;
            }
        }
        Ok(())
    }''')

    # ---------------------------------------------------------------- pick_event_card
    s = patch(s, '''        self.apply_deck_change(change, index, pool)?;
        self.event_follow = None;
        self.pending = Pending::None;
        // The room is settled **now**: picking a card is the last thing the choice asked for.
        self.mark_resolved();
        Ok(())
    }''','''        self.apply_deck_change(change, index, pool)?;
        self.event_follow = None;
        // §278：这一段还可能把玩家带去下一段 —— 那么选牌只是它的**一件**事，房间不结算。
        if !self.event_next.as_str().is_empty() {
            self.event_step = self.event_next;
            self.event_next = RunId::EMPTY;
            self.pending = Pending::Event;
            return Ok(());
        }
        self.pending = Pending::None;
        self.event_step = RunId::EMPTY;
        // The room is settled **now**: picking a card is the last thing the choice asked for.
        self.mark_resolved();
        Ok(())
    }''')

    # ---------------------------------------------------------------- 测试调用点
    s = re.sub(r'run\.resolve_event_effects\(\n(\s*)&\[', 'run.resolve_event_effects(\n\1&[', s)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('run layer: event_step/event_next wired')


main()
