"""§220 redesign: no request, no chain -- run the program **only if the card has one**.

The first attempt enqueued an `EffectRequest::CardLifecycle` for *every* card that entered a hand or
the exhaust pile. That bumped `next_effect_chain_number` on every draw, i.e. it changed the **hash**
for cards that have no lifecycle program at all -- `FIGHT_DIFF` went from 182/182 to 18/182 and
`CARD_DIFF` to 0/62, all on `chain_num`. The reference has no such request, so that was a contract
break, not a fix.

Now: the *host* (the only layer that knows the content) runs the program directly, and cards without a
program cost nothing -- zero queues, zero chain numbers, so the oracle hashes are untouched.

Trigger points stay the ones that know a card just crossed a boundary:
* turn start draw (`TurnHost::card_drawn` with the slots that were appended at the hand's tail),
* turn-end hand sweep (`TurnHost::card_exhausted`),
* `MoveCardToZone` / `drawCards` in exec (content is right there).
"""
import io

STATE = 'kernel/rd-core/src/state.rs'
TURN = 'kernel/rd-core/src/turn.rs'
EXEC = 'kernel/rd-core/src/exec.rs'
HOST = 'kernel/rd-core/src/host.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


# ── 1) state.rs：撤掉请求变体与 helper（它们会被链号污染） ─────────────────────────────────────
one(STATE, """    /// §220：一张牌的生命周期节目（`Drawn` / `Exhausted`）。在**入队那一刻**记下持有者与定义 id
    /// —— 不记槽位：节目可能把这张牌搬走，槽位会漂。
    CardLifecycle {
        /// 牌的持有者（也是节目里的 `sel.source` / `sel.eventTarget`）。
        owner: CombatantId,
        /// 定义 id（节目挂在定义上，不在实例上）。
        definition: CardDefinitionId,
        /// 哪一个事件。
        event: CardLifecycleEvent,
    },
""", "", 'request variant removed')

one(STATE, """    /// §220：账记一条"这张牌刚经历了一次生命周期事件"。
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
    }
""", "", 'helper removed')

one(STATE, """                let Some(slot) = self.draw_card(owner)? else {
                    break;
                };
                // §220：抽到了 ⇒ 记一条 `Drawn`（`void` 的"抽到时 -1 能量"）。
                // 放在这个**抽牌漏斗**上，而不是 `draw_card` 上：后者也被纯状态测试直接调用
                // （一次 1000 次），让"抽一张"依赖效果队列深度是错的。
                self.note_card_transition(owner, CardZone::DrawPile, CardZone::Hand, slot)?;
                drawn += 1;""",
    """                if self.draw_card(owner)?.is_none() {
                    break;
                }
                drawn += 1;""",
    'draw funnel reverted')

# ── 2) host.rs：一个"有节目才跑"的入口 + 两个 TurnHost 钩子 ────────────────────────────────────
one(HOST, """/// §220：`LifecyclePrograms` 的**键名** → 事件。""",
    """/// §220：跑一张牌的某条生命周期节目（**没有节目就什么都不做**）。
///
/// ⚠️ 这里刻意**不入队**：效果请求会 `??` 出根链、把 `next_effect_chain_number` 推进一格，
/// 而参考实现根本没有这条请求 —— 第一版按"每张抽到的牌入队一条"实现，`FIGHT_DIFF` 立刻从
/// 182/182 掉到 18/182（`chain_num` 行全错）。所以"有没有节目"必须先问内容：没有就**零开销**，
/// 有就直接跑（`execute_program`，与回合末的生命周期节目同一条路）。
pub(crate) fn run_card_lifecycle(
    state: &mut CombatState,
    content: &Content<'_>,
    owner: CombatantId,
    definition: CardDefinitionId,
    event: crate::state::CardLifecycleEvent,
) -> Result<(), ExecError> {
    let decoded = card_lifecycle_program(content, definition.as_str(), Some(event))?;
    let Some(program) = decoded else {
        return Ok(());
    };
    execute_program(
        state,
        content,
        program.root,
        Some(owner),
        Some(owner),
        program.max_steps,
    )
}

/// §220：`LifecyclePrograms` 的**键名** → 事件。""",
    'run_card_lifecycle')

io.open(HOST, 'a', encoding='utf-8', newline='\n').write('')
print('phase 1 done')
