"""§231 (part 1): 两件内核能力。

* `standard.no_draw` —— "本回合不能再抽牌"。`Battle Trance` 的原文是 "You cannot draw additional
  cards **this turn**"，而内容里原来给它挂的是 `standard.draw_reduction`（那条只压**下回合起手抽牌**，
  是另一根轴）⇒ 那条实现是错的，这一节修。规则落在 `draw_cards_node`：回合起手抽牌不算"additional"，
  所以只拦**效果驱动**的抽牌，正好是这张牌说的那件事。
* `node.dealDamageAndHealByLoss` —— 先打伤害，再按**实际掉的血**给来源回血（`Reaper`）。
  `resolve_damage` 一直返回 `(blocked, health_lost)`，只是从来没有人把第二个数用于"回血"。
"""
import io

CATALOG = 'kernel/rd-core/src/status_catalog.rs'
EXEC = 'kernel/rd-core/src/exec.rs'
IR = 'kernel/rd-core/src/ir.rs'


def rewrite(path, edits):
    src = io.open(path, encoding='utf-8').read()
    for old, new in edits:
        assert src.count(old) == 1, (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)


# ── 1) 状态目录：声明这条规则 ───────────────────────────────────────────────
rewrite(CATALOG, [
    ('''        "standard.draw_reduction"''',
     '''        "standard.draw_reduction" |
        // §231: "You cannot draw additional cards this turn" -- the kernel rule lives in
        // `exec::draw_cards_node` (it zeroes the count of an **effect-driven** draw, and only while
        // the status is present). The turn-start draw is deliberately not affected: that is not an
        // "additional" card. The status removes itself with a content `TurnEnded` trigger.
        "standard.no_draw"'''),
])

# ── 2) 抽牌节点认它 + 新节点 ────────────────────────────────────────────────
src = io.open(EXEC, encoding='utf-8').read()
old = '''    let count = eval_amount(node, "Count", ctx)?;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;'''
new = '''    let count = eval_amount(node, "Count", ctx)?;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    // §231: `standard.no_draw` (Battle Trance) -- while it is present, an **effect-driven** draw draws
    // nothing. The turn-start draw goes through `turn::start_current_turn`, not through this node, so
    // "additional" stays exactly what the card says.
    let blocked = draw_is_blocked(ctx, &selector)?;'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    ctx.state.enqueue_effect_with_owner(
        EffectRequest::DrawCards {
            owner,
            count,'''
new = '''    ctx.state.enqueue_effect_with_owner(
        EffectRequest::DrawCards {
            owner,
            count: if blocked { 0 } else { count },'''
assert src.count(old) == 1
src = src.replace(old, new)

# 辅助函数 + 新节点实体
anchor = '''/// §230：`node.dealDamageWithTagBonus` 的实体'''
assert src.count(anchor) == 1
impl = '''/// §231：这批抽牌的目标身上有 `standard.no_draw` 吗（`Battle Trance`）。
///
/// 只看**解析出来的第一个目标**（抽牌节点是单目标语义：`DrawCards { owner }`），而且
/// `count` 为 0 时它没有意义。选择器解不出目标 ⇒ `false`（没有对象就没有禁令；抽牌本身也会是空操作）。
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
/// **明确不支持 ResultKey**（§"没有 outcome slot"）。`resolve_damage` 返回 `(blocked, health_lost)`，
/// 所以节点可以自己当场算出来 —— 代价是这一击**立刻生效**（而不是入队后再结算）。
///
/// ⚠️ 这条"立刻生效"是有意为之，写清楚：格挡/易伤/力量的读取时点都在 `resolve_damage` 内部，
/// 与入队版完全一致；不同的只是它与**同一节目里后续节点**的相对顺序。`Reaper` 需要的恰恰是
/// "先掉血、再按掉的血回血"，而这个顺序在入队模型里拿不到。
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
    // 回血走**请求**（不是同步写）：它要经过与其它治疗同一条管线（上限钳制、`Healed` 事件）。
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

''' + anchor
src = src.replace(anchor, impl)
io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)

# ── 3) ir 词表 + 预检 + 分发 ────────────────────────────────────────────────
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

rewrite(EXEC, [
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
])
print('ok kernel')
