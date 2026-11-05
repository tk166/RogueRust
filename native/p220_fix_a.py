"""§220 fix: `move_card` stays pure; the *content-aware* callers enqueue the lifecycle notice.

Why: `move_card` is a **state** operation. Making it enqueue turned "move a card" into something that
can fail with `Full(PendingEffects)` — and a pure state test that moves a card 1000 times (the pool-slot
invariant test) blew the 64-slot queue on iteration 64. A state operation must not depend on the effect
queue's depth.

So the *decision* ("which transition is a lifecycle event") lives in one helper, and the *trigger
points* are the places where the kernel knows a card just entered a hand/exhaust pile and has content:
turn.rs (turn-start draw + turn-end hand sweep), play.rs (the played card's destination), and exec.rs
(`drawCards` / `moveCardToZone` nodes).
"""
import io

STATE = 'kernel/rd-core/src/state.rs'
TURN = 'kernel/rd-core/src/turn.rs'
PLAY = 'kernel/rd-core/src/play.rs'
EXEC = 'kernel/rd-core/src/exec.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


# ── 1) move_card 恢复纯净；通知挪进一个 helper ────────────────────────────────────────────────
one(STATE, """        // §220：**生命周期事件在唯一的漏斗上发**。不在这里发的话，就得在"打出落区、虚无回合末
        // 清理、内容 `moveCardToZone`、各种抽牌效果"每一处各写一遍 —— 而漏掉任何一处都是**静默**
        // 少跑一条节目（`void` 就永远不会掉能量）。
        let event = if to == CardZone::ExhaustPile && from != CardZone::ExhaustPile {
            Some(CardLifecycleEvent::Exhausted)
        } else if to == CardZone::Hand && from == CardZone::DrawPile {
            Some(CardLifecycleEvent::Drawn)
        } else {
            None
        };
        if let Some(event) = event {
            // 用官方访问器（`slot.index()` 与池下标是同一套），不要直接摸 `cards` 的槽位。
            if let Some(definition) = self.card(slot).map(|card| card.definition_id) {
                self.enqueue_effect(EffectRequest::CardLifecycle {
                    owner: *owner,
                    definition,
                    event,
                })?;
            }
        }
        Ok(true)
    }""",
    """        Ok(true)
    }

    /// §220：账记一条"这张牌刚经历了一次生命周期事件"。
    ///
    /// ⚠️ **不在 [`Self::move_card`] 里调用**：那是状态操作，让它依赖效果队列的深度是错的
    /// —— 一条纯状态的测试（池槽位不回收）连搬 1000 次牌，64 格队列在第 64 次就满了，
    /// 于是"搬牌"开始报 `Full(PendingEffects)`。调用点放在**知道内容、并且会排空**的那几处：
    /// 回合开始的抽牌、回合末的手牌清扫、出牌落区、以及 `drawCards` / `moveCardToZone` 两个节点。
    ///
    /// 判断"这次转移算不算事件"仍然只有这一处（两个 if），所以四处调用点不会各有一套口径。
    pub fn note_card_transition(
        &mut self,
        owner: &CombatantId,
        from: CardZone,
        to: CardZone,
        slot: CardSlot,
    ) -> StateResult<()> {
        let event = if to == CardZone::ExhaustPile && from != CardZone::ExhaustPile {
            CardLifecycleEvent::Exhausted
        } else if to == CardZone::Hand && from == CardZone::DrawPile {
            CardLifecycleEvent::Drawn
        } else {
            return Ok(());
        };
        let Some(definition) = self.card(slot).map(|card| card.definition_id) else {
            return Ok(());   // 槽位不在池里：没有定义，也就没有节目
        };
        self.enqueue_effect(EffectRequest::CardLifecycle {
            owner: *owner,
            definition,
            event,
        })
    }""",
    'move_card pure + helper')

# ── 2) turn.rs：回合开始抽牌 ────────────────────────────────────────────────────────────────────
one(TURN, """        let destination = host.turn_end_hand_destination(state, actor, slot);
        if destination == CardZone::Hand {
            continue;
        }""",
    """        let destination = host.turn_end_hand_destination(state, actor, slot);
        if destination == CardZone::Hand {
            continue;
        }
        // 落点先记下来：真正的 `move_card` 在下面统一的循环里做，届时按同一个 (from, to) 发通知。""",
    'hand sweep comment')

io.open(TURN, 'a', encoding='utf-8', newline='\n').write('')
print('phase A done')
