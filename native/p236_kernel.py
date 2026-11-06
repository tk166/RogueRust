"""§236 (part 1)：「失去生命」—— 事件 + 内核函数 + 节点。

`Lose N HP` 与"受到 N 点伤害"是**两件不同的事**（StS 原文用 `Lose HP`，wiki 也分开写）：
* 不吃格挡、不吃力量/易伤、不触发"被打"的钩子（Thorns / Flame Barrier / Curl Up / Flying）；
* 但它**是**失去生命，所以 `Rupture`（"每当你因为一张牌失去生命，获得 1 力量"）要响。

所以这一节加三样：
1. `CombatEvent::HpLost { target, amount, from_card }` —— `from_card` 让 Rupture 能区分
   "牌付的代价"（Hemokinesis）与"状态每回合扣的"（Brutality，StS 里它**不**触发 Rupture）；
2. `exec::lose_health()` —— 直接写 `health_current`，但**复用掉血那套收尾**（0 血转 Downed、
   随从逃跑、`Downed` 事件、判胜负），否则"用一张牌把自己打死"不会结束战斗；
3. `node.loseHp { TargetSelector, Amount }`。
"""
import io

STATE = 'kernel/rd-core/src/state.rs'
EXEC = 'kernel/rd-core/src/exec.rs'
HOST = 'kernel/rd-core/src/host.rs'
EXPR = 'kernel/rd-core/src/expr.rs'
IR = 'kernel/rd-core/src/ir.rs'


def rewrite(path, edits):
    src = io.open(path, encoding='utf-8').read()
    for old, new in edits:
        assert src.count(old) == 1, (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)


# ── 1) 事件 ──────────────────────────────────────────────────────────────────
rewrite(STATE, [
    ('''    /// `CardPlayed`（`CardPlay.cs:144`）：**有人打出了一张牌**。''',
     '''    /// §236：**失去生命**（不是伤害）。`Lose N HP` 的载体。
    ///
    /// 与 `DamageTaken` 分开是**语义**要求，不是洁癖：`Lose HP` 不吃格挡、不吃力量/易伤，也**不**
    /// 触发"被打"的钩子（Thorns / Flame Barrier / Curl Up / Flying）。而 `Rupture`
    /// （"每当你因为一张牌失去生命"）要响的正是它。
    HpLost {
        /// 失去生命的那一方。
        target: CombatantId,
        /// 真的失去了几点（可能因为血量不够而少于请求额）。
        amount: i32,
        /// **是不是一张牌付的代价**（`ctx.resolving_card.is_some()`）。
        ///
        /// StS 的 Rupture 只认"因为一张牌失去生命"：Hemokinesis 算，Brutality 每回合扣的那 1 点
        /// **不算**。没有这一格就只能二选一，而两种选法都会错一张牌。
        from_card: bool,
    },
    /// `CardPlayed`（`CardPlay.cs:144`）：**有人打出了一张牌**。'''),
])

# ── 2) 内核函数 + 节点 + 标志位 ──────────────────────────────────────────────
src = io.open(EXEC, encoding='utf-8').read()
anchor = '''/// `StandardCombatIds.PlayerTeam`（`StandardCombatIds.cs`：`new("player")`）。'''
assert src.count(anchor) == 1
lose_hp = '''/// §236：「失去 N 点生命」—— `Lose HP`，**不是**伤害。
///
/// 直接写 `health_current`，但**复用掉血那套收尾**：0 血转 `Downed`、主人的随从逃跑、发 `Downed`
/// 事件、判胜负。少了这一段，"用一张牌把自己打死"不会结束战斗（一个只在自伤牌上出现的死锁）。
///
/// 返回**真的**失去的血量：血量不够时就是剩下的那些（`Lose 6 HP` 在 2 血时只掉 2）。
pub fn lose_health(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    amount: i32,
) -> Result<i32, ExecError> {
    if amount < 0 {
        return Err(ExecError::Modifier);
    }
    let Some(combatant) = ctx.state.combatant(target) else {
        return Err(ExecError::MissingCombatant);
    };
    if combatant.lifecycle_state != crate::state::CombatantLifecycleState::Alive {
        return Ok(0);
    }
    let current = combatant.health_current;
    let lost = amount.min(current.max(0));
    let after = current - lost;
    // `from_card` 由上下文回答：节目里有没有"正在结算的那张牌"。
    let from_card = ctx.resolving_card.is_some();
    let combatant = ctx
        .state
        .combatant_mut(target)
        .ok_or(ExecError::MissingCombatant)?;
    combatant.health_current = after;
    let went_down = lost > 0
        && after == 0
        && combatant.lifecycle_state == crate::state::CombatantLifecycleState::Alive;
    if went_down {
        combatant.lifecycle_state = crate::state::CombatantLifecycleState::Downed;
        for other in ctx.state.combatants_mut() {
            if other.owner == Some(*target)
                && other.lifecycle_state == crate::state::CombatantLifecycleState::Alive
            {
                other.lifecycle_state = crate::state::CombatantLifecycleState::Escaped;
            }
        }
        ctx.state
            .enqueue_event(crate::state::CombatEvent::Downed {
                combatant: *target,
                source: ctx.source,
            })
            .map_err(ExecError::Capacity)?;
    }
    if lost > 0 {
        ctx.state
            .enqueue_event(crate::state::CombatEvent::HpLost {
                target: *target,
                amount: lost,
                from_card,
            })
            .map_err(ExecError::Capacity)?;
    }
    update_standard_combat_result(ctx.state);
    Ok(lost)
}

/// §236：`node.loseHp` 的实体 —— `{TargetSelector, Amount}`，每个目标各失去一次。
///
/// 与 `dealDamage` 的分工写在 [`lose_health`] 的文档里（一句话：不吃格挡、不吃修饰器、
/// 不触发"被打"的钩子）。`Amount` 在**解析目标之前**求值，与其它产出型节点同一条口径。
fn lose_hp_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        lose_health(ctx, target, amount)?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

''' + anchor
src = src.replace(anchor, lose_hp)

# 标志位
old = '''pub const CARD_IS_RESOLVING: u8 = 1 << 5;'''
new = '''pub const CARD_IS_RESOLVING: u8 = 1 << 5;

/// §236：这次失去生命是不是**一张牌**付的代价（`Rupture` 只认这一种）。
pub const HP_LOSS_FROM_CARD: u8 = 1 << 6;'''
assert src.count(old) == 1
src = src.replace(old, new)

# 预检 + 分发
old = '''        // §231：`dealDamageAndHealByLoss`（打伤害 + 按掉血回血）。同上。
        | NodeKind::DealDamageAndHealByLoss'''
new = '''        // §231：`dealDamageAndHealByLoss`（打伤害 + 按掉血回血）。同上。
        | NodeKind::DealDamageAndHealByLoss
        // §236：`loseHp`（失去生命）。同上。
        | NodeKind::LoseHp'''
assert src.count(old) == 1
src = src.replace(old, new)
old = '''        NodeKind::DealDamageAndHealByLoss => {'''
new = '''        NodeKind::LoseHp => lose_hp_node(node, ctx, frame, slot, stats),
        NodeKind::DealDamageAndHealByLoss => {'''
assert src.count(old) == 1
src = src.replace(old, new)
io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)

# ── 3) ir 词表 ───────────────────────────────────────────────────────────────
rewrite(IR, [
    ('''    /// `node.dealDamageAndHealByLoss` —— 打伤害，然后按**实际掉的血**给来源回血（§231，`Reaper`）。''',
     '''    /// `node.loseHp` —— **失去生命**（§236）。不是伤害：不吃格挡、不吃修饰器、不触发"被打"的钩子。
    LoseHp,
    /// `node.dealDamageAndHealByLoss` —— 打伤害，然后按**实际掉的血**给来源回血（§231，`Reaper`）。'''),
    ('''            NodeKind::DealDamageAndHealByLoss => "node.dealDamageAndHealByLoss",''',
     '''            NodeKind::LoseHp => "node.loseHp",
            NodeKind::DealDamageAndHealByLoss => "node.dealDamageAndHealByLoss",'''),
    ('''        const ALL: [NodeKind; 29] = [''', '''        const ALL: [NodeKind; 30] = ['''),
    ('''            // §231：打伤害并按实际掉血回血（Reaper）。
            NodeKind::DealDamageAndHealByLoss,''',
     '''            // §231：打伤害并按实际掉血回血（Reaper）。
            NodeKind::DealDamageAndHealByLoss,
            // §236：失去生命（Hemokinesis / Offering / Bloodletting / Brutality）。
            NodeKind::LoseHp,'''),
])

# ── 4) Host：HpLost 触发器 ──────────────────────────────────────────────────
rewrite(HOST, [
    ('''    /// `CardCostPaid` —— 出牌付了费用。
    CardCostPaid,''',
     '''    /// `CardCostPaid` —— 出牌付了费用。
    CardCostPaid,
    /// §236：**失去生命**（不是伤害）。Bearer 是失去生命的那一方。
    ///
    /// 参考的实现里没有这个名字（它把这件事折进 `CardMovedToZone`/伤害事件），所以这一条是
    /// **本内核自己的事件名** —— 理由与我们加 `HpLoss` 这个动作本身一样：`Lose HP` 不是伤害。
    HpLost,'''),
    ('''            "CardPlayed" => Some(TriggerEvent::CardPlayed),''',
     '''            "CardPlayed" => Some(TriggerEvent::CardPlayed),
            // §236
            "HpLost" => Some(TriggerEvent::HpLost),'''),
    ('''            TriggerEvent::CardPlayed => "CardPlayed",''',
     '''            TriggerEvent::CardPlayed => "CardPlayed",
            TriggerEvent::HpLost => "HpLost",'''),
    ('''            // `CardPlayed`：派发给**所有战斗员**（Enrage 在敌人身上，由你出牌触发）。''',
     '''            // §236: `HpLost` -- 派给**失去生命的那一方**（Rupture 长在它身上），
            // 事实位带上"是不是一张牌付的代价"，节目用 `event.bool: hpLoss.fromCard` 过滤。
            CombatEvent::HpLost { target, amount, from_card } => {
                let _ = amount;
                let flags = if from_card { crate::exec::HP_LOSS_FROM_CARD } else { 0 };
                self.run_triggers_with_flags(state, &target, TriggerEvent::HpLost, flags)
            }
            // `CardPlayed`：派发给**所有战斗员**（Enrage 在敌人身上，由你出牌触发）。'''),
])

# `run_triggers_with_flags`：把 `run_triggers` 改成带 flags 的版本（flags 默认 0）
src = io.open(HOST, encoding='utf-8').read()
old = '''    fn run_triggers(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        event: TriggerEvent,
    ) -> Result<(), HostError> {'''
new = '''    fn run_triggers(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        event: TriggerEvent,
    ) -> Result<(), HostError> {
        self.run_triggers_with_flags(state, actor, event, 0)
    }

    /// §236：[`Self::run_triggers`] 加上**事件事实位**（`event.bool` 读它）。
    ///
    /// 只有 `HpLost`（本节的）用到：Rupture 要区分"牌付的代价"与"状态每回合扣的"。其它事件走
    /// flags = 0 的那条，行为逐字不变。
    fn run_triggers_with_flags(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        event: TriggerEvent,
        flags: u8,
    ) -> Result<(), HostError> {'''
assert src.count(old) == 1
src = src.replace(old, new)
old = '''            let outcome = execute_program(state, self.content, root, Some(*actor), None, steps);
            outcome.map_err(|e| self.record(HostError::Exec(e)))?;'''
new = '''            let outcome = execute_program_with_flags(
                state,
                self.content,
                root,
                Some(*actor),
                None,
                steps,
                flags,
            );
            outcome.map_err(|e| self.record(HostError::Exec(e)))?;'''
assert src.count(old) == 1
io.open(HOST, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new))

# ── 5) event.bool: hpLoss.fromCard ─────────────────────────────────────────
rewrite(EXPR, [
    ('''                "card.isResolving" => crate::exec::CARD_IS_RESOLVING,''',
     '''                "card.isResolving" => crate::exec::CARD_IS_RESOLVING,
                // §236: was this HP loss paid by a card? (Rupture only counts those.)
                "hpLoss.fromCard" => crate::exec::HP_LOSS_FROM_CARD,'''),
])
print('ok kernel part A')
