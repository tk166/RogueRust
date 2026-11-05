"""§231 (part 1b): 抽牌节点认 `standard.no_draw` + 新节点 + ir 词表。"""
import io

EXEC = 'kernel/rd-core/src/exec.rs'
IR = 'kernel/rd-core/src/ir.rs'


def rewrite(path, edits):
    src = io.open(path, encoding='utf-8').read()
    for old, new in edits:
        assert src.count(old) == 1, (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)


rewrite(EXEC, [
    # ① 解析完选择器就问"禁不禁抽"
    ('''    let resolved = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(resolved) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::DrawCards {
                owner: *target,
                count,
            },''',
     '''    let resolved = resolve_targets(selector, ctx, &mut targets)?;
    // §231: `standard.no_draw` (Battle Trance) -- while it is present, an **effect-driven** draw
    // draws nothing. The turn-start draw goes through `turn::start_current_turn`, not through this
    // node, so "additional" stays exactly what the card says.
    let blocked = draw_is_blocked(ctx, selector)?;
    for target in targets.iter().take(resolved) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::DrawCards {
                owner: *target,
                count: if blocked { 0 } else { count },
            },'''),

    # ② 预检 + 分发
    ('''        // §230：`dealDamageWithTagBonus`（数牌 + 打伤害）。同上。
        | NodeKind::DealDamageWithTagBonus''',
     '''        // §230：`dealDamageWithTagBonus`（数牌 + 打伤害）。同上。
        | NodeKind::DealDamageWithTagBonus
        // §231：`dealDamageAndHealByLoss`（打伤害 + 按掉血回血）。同上。
        | NodeKind::DealDamageAndHealByLoss'''),
    ('''        NodeKind::DealDamageWithTagBonus => {''',
     '''        NodeKind::DealDamageAndHealByLoss => {
            deal_damage_and_heal_by_loss_node(node, ctx, frame, slot, stats)
        }
        NodeKind::DealDamageWithTagBonus => {'''),

    # ③ 实体
    ('''/// §230：`node.dealDamageWithTagBonus` 的实体''',
     '''/// §231：这批抽牌的目标身上有 `standard.no_draw` 吗（`Battle Trance`）。
///
/// 抽牌节点是单目标语义（`DrawCards { owner }`），所以只看解析出来的第一个目标。
/// 解不出目标 ⇒ `false`：没有对象就没有禁令（抽牌本身也会是空操作）。
fn draw_is_blocked(ctx: &ExecContext<'_>, selector: NodeRef<'_>) -> Result<bool, ExecError> {
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    let Some(owner) = targets.first().copied().filter(|_| count > 0) else {
        return Ok(false);
    };
    let Some(combatant) = ctx.state.combatant(&owner) else {
        return Ok(false);
    };
    Ok(total_status_stacks(combatant, "standard.no_draw") > 0)
}

/// §231：`node.dealDamageAndHealByLoss` 的实体 —— 打伤害，然后按**实际掉的血**给来源回血。
///
/// `Reaper`：`Deal 4 (5) damage to ALL enemies. Heal unblocked damage dealt.`
///
/// 为什么必须是一个节点：参考用 `ResultKey` 把"这一击掉了多少血"传给下一个节点，而本内核
/// **明确不支持 ResultKey**。`resolve_damage` 返回 `(blocked, health_lost)`，所以节点自己算。
///
/// ⚠️ 代价是这一击**立刻生效**（而不是入队后再结算）。这一条是有意为之：格挡/易伤/力量的读取
/// 时点都在 `resolve_damage` 内部，与入队版一致；不同的只是它与**同一节目里后续节点**的相对顺序。
/// `Reaper` 需要的恰恰是"先掉血、再按掉的血回血"，那个顺序在入队模型里拿不到。
fn deal_damage_and_heal_by_loss_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let ignores_block = node.bool_field("IgnoresBlock")?.unwrap_or(false);
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let source = ctx.source;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    if count == 0 {
        return resume_later(ctx.state, frame, slot);
    }
    let mut lost_total = 0i32;
    for target in targets.iter().take(count) {
        let (_, lost) = resolve_damage(ctx, target, amount, ignores_block)?;
        stats.effects = stats.effects.saturating_add(1);
        lost_total = lost_total.saturating_add(lost);
    }
    // 回血走**请求**（不是同步写）：它要过与其它治疗同一条管线（上限钳制、`Healed` 事件）。
    if lost_total > 0 {
        if let Some(owner) = source {
            ctx.state.enqueue_effect_with_owner(
                EffectRequest::Heal {
                    target: owner,
                    amount: lost_total,
                },
                Some(frame),
            )?;
            stats.effects = stats.effects.saturating_add(1);
        }
    }
    resume_later(ctx.state, frame, slot)
}

/// §230：`node.dealDamageWithTagBonus` 的实体'''),
])

rewrite(IR, [
    ('''    /// `node.dealDamageWithTagBonus` —— **基础伤害 + 每张带某个 tag 的牌一份加成**（§230）。''',
     '''    /// `node.dealDamageAndHealByLoss` —— 打伤害，然后按**实际掉的血**给来源回血（§231，`Reaper`）。
    ///
    /// 参考靠 `ResultKey` 把"这一击掉了多少血"传给下一个节点；本内核不支持 `ResultKey`，而
    /// `resolve_damage` 本来就返回 `(blocked, health_lost)` —— 所以这个节点自己当场算。
    DealDamageAndHealByLoss,
    /// `node.dealDamageWithTagBonus` —— **基础伤害 + 每张带某个 tag 的牌一份加成**（§230）。'''),
    ('''            NodeKind::DealDamageWithTagBonus => "node.dealDamageWithTagBonus",''',
     '''            NodeKind::DealDamageAndHealByLoss => "node.dealDamageAndHealByLoss",
            NodeKind::DealDamageWithTagBonus => "node.dealDamageWithTagBonus",'''),
    ('''        const ALL: [NodeKind; 27] = [''', '''        const ALL: [NodeKind; 28] = ['''),
    ('''            // §230：按"带某个 tag 的牌数"加伤的伤害（Perfected Strike）。
            NodeKind::DealDamageWithTagBonus,''',
     '''            // §230：按"带某个 tag 的牌数"加伤的伤害（Perfected Strike）。
            NodeKind::DealDamageWithTagBonus,
            // §231：打伤害并按实际掉血回血（Reaper）。
            NodeKind::DealDamageAndHealByLoss,'''),
])
print('ok kernel')
