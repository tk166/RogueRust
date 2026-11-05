"""§220 phase B: put the notices on the real funnels (draw / hand sweep / played destination)."""
import io

STATE = 'kernel/rd-core/src/state.rs'
TURN = 'kernel/rd-core/src/turn.rs'
PLAY = 'kernel/rd-core/src/play.rs'
HOST = 'kernel/rd-core/src/host.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


# ① 抽牌漏斗（回合开始抽牌与 `DiscardThenDraw` 都走这里）
one(STATE, """        let mut drawn = 0usize;
        while drawn < wanted {
            while drawn < wanted {
                if self.draw_card(owner)?.is_none() {
                    break;
                }
                drawn += 1;
            }""",
    """        let mut drawn = 0usize;
        while drawn < wanted {
            while drawn < wanted {
                let Some(slot) = self.draw_card(owner)? else {
                    break;
                };
                // §220：抽到了 ⇒ 记一条 `Drawn`（`void` 的"抽到时 -1 能量"）。
                // 放在这个**抽牌漏斗**上，而不是 `draw_card` 上：后者也被纯状态测试直接调用
                // （一次 1000 次），让"抽一张"依赖效果队列深度是错的。
                self.note_card_transition(owner, CardZone::DrawPile, CardZone::Hand, slot)?;
                drawn += 1;
            }""",
    'draw funnel')

# ② 回合末手牌清扫
one(TURN, """        if state.move_card(actor, CardZone::Hand, destination, slot, ZonePlacement::Bottom)? {
            moved += 1;
        }""",
    """        if state.move_card(actor, CardZone::Hand, destination, slot, ZonePlacement::Bottom)? {
            // §220：虚无（`TurnEndHandDestinationZone = ExhaustPile`）走的就是这一条 ⇒
            // `sentinel` 的"被消耗时给能量"从这里触发。
            state.note_card_transition(actor, CardZone::Hand, destination, slot)?;
            moved += 1;
        }""",
    'hand sweep')

# ③ 出牌落区（`PlayedCardDestinationZone = ExhaustPile` ⇒ 打出即消耗）
one(PLAY, """    let destination = played_card_destination(&card)?;""",
    """    let destination = played_card_destination(&card)?;
    // §220：打出即消耗的那些牌（`slimed` / `bandage_up` / `dark_shackles` / `apparition`）
    // 从这一格进入消耗堆 ⇒ `Exhausted` 通知在真正搬牌之后发（见下面的 `move_card`）。
    let exhausted_by_play = destination == CardZone::ExhaustPile;""",
    'play destination flag')

io.open(PLAY, 'a', encoding='utf-8', newline='\n').write('')
print('phase B part 1 done')
