"""§249 内核：`Sadistic Nature` 的两个事实位（"是 debuff" / "落在别人身上"）。

`Whenever you apply a **debuff** to an **enemy**, they take (5;7) damage.`

`StatusApplied` 是**广播**事件（所有战斗员各跑一遍自己的触发器，`eventTarget` = 承受者），
所以触发器要能回答两件事：

1. 刚落下的那条状态**是不是 debuff** —— 极性在**入队那一刻**才知道（`status_polarity` 就在
   手边），事后问不出来（事件只带 `target`）；
2. 是不是落在**别人**身上 —— 玩家给自己挂 Weak 不该触发。

两条都做成事实位（`event.bool`），与 `damage.isAttack` 同一套仓位；内容侧问
`status.isDebuff` / `status.appliedToOther`。

⚠️ 为什么不让内容自己判断：极性在 `STAT` 表里（`Polarity`），而 `ExprContext` 拿不到"刚落下
的是哪条状态"—— 事件不带定义。**事件必须在知道它的地方带事实**（§245 `from_card` 同一条教训）。
"""
import io

K = 'D:/Vibe/sts-tui/kernel/rd-core/src/'


def patch(name, pairs):
    path = K + name
    src = io.open(path, encoding='utf-8').read()
    for old, new, label in pairs:
        assert src.count(old) == 1, (name, label, src.count(old))
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('patched', name)


patch('state.rs', [(
    '''    StatusApplied {
        /// 承受者。
        target: CombatantId,
    },''',
    '''    StatusApplied {
        /// 承受者。
        target: CombatantId,
        /// §249：落下的这条是 **debuff** 吗（`Sadistic Nature` 只认 debuff）。
        ///
        /// 极性在**入队那一刻**才知道（事件本身不带定义），所以事实必须随事件一起走 ——
        /// 与 §245 的 `GainBlock.from_card` 同一条理由。
        debuff: bool,
        /// §249：承受者**不是**施法者自己（`Sadistic Nature` 说的是 "to an **enemy**"）。
        applied_to_other: bool,
    },''', 'variant fields')])

patch('exec.rs', [
    ('''    ctx.state
        .enqueue_event(crate::state::CombatEvent::StatusApplied { target: *target })
        .map_err(ExecError::Capacity)?;''',
     '''    ctx.state
        .enqueue_event(crate::state::CombatEvent::StatusApplied {
            target: *target,
            // §249：极性此刻才知道（`polarity` 就是上一行算出来的那个）。
            debuff: matches!(polarity, crate::state::StatusPolarity::Debuff),
            // §249："落在别人身上" —— 给自己挂 debuff 不该触发 `Sadistic Nature`。
            applied_to_other: ctx.source.map_or(true, |source| source != *target),
        })
        .map_err(ExecError::Capacity)?;''', 'enqueue'),
    ('''/// §239：**这次出牌时，手牌里每一张都是 Attack**''',
     '''/// §249：刚落下的那条状态是 **debuff**（`Sadistic Nature`）。
pub const STATUS_IS_DEBUFF: u16 = 1 << 9;

/// §249：刚落下的那条状态**不是**施法者给自己的（`Sadistic Nature` 说 "to an **enemy**"）。
pub const STATUS_APPLIED_TO_OTHER: u16 = 1 << 10;

/// §239：**这次出牌时，手牌里每一张都是 Attack**''', 'bits'),
])

patch('expr.rs', [(
    '''                "playCondition.handIsAllAttacks" => crate::exec::PLAY_CONDITION_HAND_ALL_ATTACKS,''',
    '''                "playCondition.handIsAllAttacks" => crate::exec::PLAY_CONDITION_HAND_ALL_ATTACKS,
                // §249: the two facts `Sadistic Nature` asks about.
                "status.isDebuff" => crate::exec::STATUS_IS_DEBUFF,
                "status.appliedToOther" => crate::exec::STATUS_APPLIED_TO_OTHER,''', 'field keys')])

patch('host.rs', [
    ('''            CombatEvent::StatusApplied { target } => {
                self.run_broadcast_triggers(state, TriggerEvent::StatusApplied, &target)
            }''',
     '''            CombatEvent::StatusApplied {
                target,
                debuff,
                applied_to_other,
            } => {
                // §249：两个事实位随事件走（`event.bool` 读它们）。
                let mut flags = 0u16;
                if debuff {
                    flags |= crate::exec::STATUS_IS_DEBUFF;
                }
                if applied_to_other {
                    flags |= crate::exec::STATUS_APPLIED_TO_OTHER;
                }
                self.run_broadcast_triggers_with_flags(
                    state,
                    TriggerEvent::StatusApplied,
                    &target,
                    flags,
                )
            }''', 'dispatch'),
    ('''    fn run_broadcast_triggers(
        &mut self,
        state: &mut CombatState,
        event: TriggerEvent,
        about: &CombatantId,
    ) -> Result<(), HostError> {''',
     '''    fn run_broadcast_triggers(
        &mut self,
        state: &mut CombatState,
        event: TriggerEvent,
        about: &CombatantId,
    ) -> Result<(), HostError> {
        self.run_broadcast_triggers_with_flags(state, event, about, 0)
    }

    /// §249：同上，但带**事件事实位**（`event.bool` 读它）。
    fn run_broadcast_triggers_with_flags(
        &mut self,
        state: &mut CombatState,
        event: TriggerEvent,
        about: &CombatantId,
        flags: u16,
    ) -> Result<(), HostError> {''', 'with_flags'),
    ('''                let outcome =
                    execute_program(state, self.content, root, Some(bearer), Some(*about), steps);''',
     '''                let outcome = execute_program_with_flags(
                    state,
                    self.content,
                    root,
                    Some(bearer),
                    Some(*about),
                    steps,
                    flags,
                );''', 'flags into program'),
])
