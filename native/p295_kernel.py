"""§295 A2：`BlockBroken` 触发器 + `hand_drill`。

## 语义（wiki 那句话要拆成两个槽）

`Hand Drill`: *"Whenever you break an enemy's Block, apply 2 Vulnerable."*

拆开是两件事：

| 槽 | 谁 |
|---|---|
| **Bearer**（谁的遗物/状态在听） | **打破格挡的人**（出手方）—— "**you** break" |
| **EventTarget**（节目里 `sel.eventTarget`） | **格挡被打穿的那一方** —— "apply 2 Vulnerable" 落在它身上 |

这与 `DamageDealt` 同一形状（Bearer = 出手方、EventTarget = 承受方），所以不新造一种方向。

## 什么算"打破"

`block_before > 0` 且这一次伤害把**整池格挡全吃掉了**（`blocked == block_before`）。
两种边界都要注意：

* 格挡本来就是 0 ⇒ **不算**（没有"打破"这回事，否则 `hand_drill` 会变成"每次攻击都加易伤"）；
* `IgnoresBlock`（毒、`Constricted`）⇒ **不算** —— 它根本没碰格挡。

## 落点

`resolve_damage` 的 S4（防御池吸收）之后、S5（扣血）之前 —— 那里是"格挡发生了多少"唯一的
真相点。事件**入队**，由回合机的事件循环解析（与 `BlockGained` / `CardsDrawn` 同一条路）。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-core/src/state.rs'
HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:100])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── 1. 事件
    patch(STATE, '''    /// `CardCostPaid`（`CardPlay.cs:138`）：出牌付了费用。''',
                 '''    /// §295：**有人把另一方的格挡打穿了**（`hand_drill`）。
    ///
    /// 参考的 25 个触发器里没有它；这是**本内核自己的事件名**（与 §237 的 `CardsDrawn`、
    /// §294 的 `DeckShuffled` 同级：被真实内容逼出来的扩展）。
    ///
    /// * `combatant` = **打破格挡的人**（Bearer ⇒ 遗物/状态的"你的"指它）；
    /// * `target` = **格挡被打穿的那一方**（`sel.eventTarget` ⇒ "apply 2 Vulnerable" 落在它身上）。
    ///
    /// 与 [`Self::DamageDealt`] 同一形状（Bearer = 出手方、EventTarget = 承受方），所以不新造方向。
    BlockBroken {
        /// 出手方（打破格挡的人）。
        combatant: CombatantId,
        /// 格挡被打穿的那一方。
        target: CombatantId,
    },
    /// `CardCostPaid`（`CardPlay.cs:138`）：出牌付了费用。''')

    # ── 2. 触发枚举
    patch(HOST, '''    /// §294：**有人洗了牌**。Bearer = 洗牌的那个人（`the_abacus` / `sundial`）。''',
                '''    /// §295：**有人把另一方的格挡打穿了**。Bearer = 打破格挡的人，EventTarget = 挨打的那一方
    /// （`hand_drill`）。同样是本内核的扩展（参考没有这个名字）。
    BlockBroken,
    /// §294：**有人洗了牌**。Bearer = 洗牌的那个人（`the_abacus` / `sundial`）。''')

    patch(HOST, '''            // §294：本内核的扩展（参考没有这个名字）。
            "DeckShuffled" => Some(TriggerEvent::DeckShuffled),''',
                '''            // §294：本内核的扩展（参考没有这个名字）。
            "DeckShuffled" => Some(TriggerEvent::DeckShuffled),
            // §295：同上（"格挡被打穿"）。
            "BlockBroken" => Some(TriggerEvent::BlockBroken),''')

    patch(HOST, '''            TriggerEvent::DeckShuffled => "DeckShuffled",''',
                '''            TriggerEvent::DeckShuffled => "DeckShuffled",
            TriggerEvent::BlockBroken => "BlockBroken",''')

    # ── 3. 派发（Bearer = 出手方，EventTarget = 挨打方）
    patch(HOST, '''            // §294: `DeckShuffled` -- Bearer 是洗牌的人（`the_abacus` / `sundial`）。''',
                '''            // §295: `BlockBroken` -- Bearer 是**打破格挡的人**，`EventTarget` 是**格挡被打穿的
            // 那一方**。与 `DamageDealt` 同一方向（出手方 → 承受方），所以 `hand_drill` 的
            // 节目可以用 `sel.eventTarget` 把易伤落到挨打的那只怪身上。
            CombatEvent::BlockBroken { combatant, target } => {
                self.run_triggers_with_target(state, &combatant, TriggerEvent::BlockBroken, target)
            }
            // §294: `DeckShuffled` -- Bearer 是洗牌的人（`the_abacus` / `sundial`）。''')

    # ── 4. `run_triggers_with_target`（与 with_flags 同形，多一个 EventTarget）
    patch(HOST, '''    /// §236：上一个加上**事件事实位**（`event.bool` 读它）。''',
                '''    /// §295：上一个加上**事件目标**（节目里的 `sel.eventTarget`）。
    ///
    /// 与 [`Self::run_triggers`] 的区别只有一处：`execute_program` 的第 5 个参数。`Downed` 那条
    /// （`run_downed_triggers`）自己内联了同样的循环，因为它还要在之后派 `FoeDowned`；
    /// 这里只派一个事件，所以走这条通用路径。
    ///
    /// ⚠️ 不能"合并进 `run_triggers` 加一个 `Option<CombatantId>` 参数"：那会把 25 处调用点
    /// 全部改一遍，而其中 24 处要传 `None` —— "绝大多数传同一个值"的参数是签名在说谎。
    fn run_triggers_with_target(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        event: TriggerEvent,
        target: CombatantId,
    ) -> Result<(), HostError> {
        let mut batch = TriggerBatch::new();
        self.collect_triggers(state, actor, event, &mut batch)?;
        batch.sort();
        for i in 0..batch.len {
            if state.result != CombatResult::Ongoing {
                break;
            }
            let Some(handle) = batch.root.get(i).copied() else {
                break;
            };
            let steps = batch.max_steps.get(i).copied().unwrap_or(DEFAULT_MAX_PROGRAM_STEPS);
            let root = NodeRef::new(self.content, handle);
            let outcome = execute_program(
                state,
                self.content,
                root,
                Some(*actor),
                Some(target),
                steps,
            );
            outcome.map_err(|e| self.record(HostError::Exec(e)))?;
        }
        Ok(())
    }

    /// §236：上一个加上**事件事实位**（`event.bool` 读它）。''')

    # ── 5. 统计用的穷尽 match（core 镜像里 0 条）
    patch(HOST, '''                    // §294：同上（"洗了牌"）。core 镜像里 0 条，计数恒 0。
                    TriggerEvent::DeckShuffled => {}''',
                '''                    // §294：同上（"洗了牌"）。core 镜像里 0 条，计数恒 0。
                    TriggerEvent::DeckShuffled => {}
                    // §295：同上（"格挡被打穿"）。core 镜像里 0 条，计数恒 0。
                    TriggerEvent::BlockBroken => {}''')

    # ── 6. 伤害管线：S4 之后入队
    patch(EXEC, '''    // ── S5/S7：生命损失（`:103-104,138-141`）。
    let remaining = amount.saturating_sub(blocked);''',
               '''    // ── S4b：**§295 `BlockBroken`** —— 格挡**被打穿**的那一刻。
    //
    // 判据是三条同时成立（每一条都有反例）：
    //   ① 出手方存在且**不是**自己（`hand_drill` 是"an enemy's Block"，自己打自己不算）；
    //   ② 挨打方**原本有**格挡（`block_before > 0`）—— 否则"格挡 0 打掉 0"会变成"每次攻击都
    //      加易伤"（那件遗物会强得离谱，而且没有任何东西会红）；
    //   ③ 这一次伤害把**整池格挡全吃掉**（`blocked == block_before`）。
    //
    // `ignores_block`（毒 / `Constricted`）走不进这一段：那些伤害根本没碰格挡。
    // 事件**入队**而不是立刻执行 —— 与 `BlockGained` 同一条路，解析在回合机的事件循环里。
    if !ignores_block && block_before > 0 && blocked == block_before {
        if let Some(source) = ctx.source {
            if source != *target {
                ctx.state
                    .enqueue_event(crate::state::CombatEvent::BlockBroken {
                        combatant: source,
                        target: *target,
                    })
                    .map_err(ExecError::Capacity)?;
            }
        }
    }

    // ── S5/S7：生命损失（`:103-104,138-141`）。
    let remaining = amount.saturating_sub(blocked);''')
    print('kernel: BlockBroken')


main()
