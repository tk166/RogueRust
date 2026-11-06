"""§238 修正：`Feed` 的 "If Fatal" 必须是**一个节点**。

`sequence[dealDamage, conditional(...)]` 在结构上做不到：本内核与参考一样"先把整棵树派发完，
再让请求落地"（`dispatch_sequence` 一次性派发所有孩子），所以条件节点在求值时**伤害还没落地**。
`dealDamageAndHealByLoss`（Reaper）之所以存在，正是同一个原因 —— 它在一个节点里同步
`resolve_damage` 再读自己造成的损失。

⇒ 加 `node.dealDamageAndGainMaxHealthIfFatal`（`{TargetSelector, Amount, IgnoresBlock, MaxHealthGain}`），
并把抬上限的写法抽成**一个** helper（`gain_max_health`），让两个节点共用。
"""
import io

K = 'D:/Vibe/sts-tui/kernel/rd-core/src/'


def patch(name, pairs):
    path = K + name
    s = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70], s.count(old))
        s = s.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('patched', name)


patch('ir.rs', [
    ('''    GainMaxHealth,''', '''    GainMaxHealth,
    /// §238：**打伤害，如果打死了就抬高自己的最大生命**（`Feed` 的 "If Fatal, raise your Max HP"）。
    ///
    /// 为什么必须是一个节点：整棵树**先派发完**再让请求落地，所以
    /// `sequence[dealDamage, conditional]` 里的条件求值时伤害还没落地（结构上做不到）。
    /// 同一个原因生出了 `DealDamageAndHealByLoss`（Reaper）—— 这里照那个形状办。
    DealDamageAndGainMaxHealthIfFatal,'''),
    ('''        const ALL: [NodeKind; 31] = [''', '''        const ALL: [NodeKind; 32] = ['''),
    ('''            // §238：抬高最大生命（Feed 的 "If Fatal"）。
            NodeKind::GainMaxHealth,''',
     '''            // §238：抬高最大生命（Feed 的 "If Fatal"）。
            NodeKind::GainMaxHealth,
            NodeKind::DealDamageAndGainMaxHealthIfFatal,'''),
    ('''            NodeKind::GainMaxHealth => "node.gainMaxHealth",''',
     '''            NodeKind::GainMaxHealth => "node.gainMaxHealth",
            NodeKind::DealDamageAndGainMaxHealthIfFatal => "node.dealDamageAndGainMaxHealthIfFatal",'''),
])

patch('exec.rs', [
    ('''        // §238：`gainMaxHealth`（抬高上限）。无孩子。
        | NodeKind::GainMaxHealth''',
     '''        // §238：`gainMaxHealth`（抬高上限）与它的 "If Fatal" 变体。无孩子。
        | NodeKind::GainMaxHealth
        | NodeKind::DealDamageAndGainMaxHealthIfFatal'''),
    ('''        NodeKind::GainMaxHealth => gain_max_health_node(node, ctx, frame, slot, stats),''',
     '''        NodeKind::GainMaxHealth => gain_max_health_node(node, ctx, frame, slot, stats),
        NodeKind::DealDamageAndGainMaxHealthIfFatal => {
            deal_damage_and_gain_max_health_if_fatal_node(node, ctx, frame, slot, stats)
        }'''),
    # 抬上限抽成一个 helper（两个节点共用一份实现）
    ('''    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        let combatant = ctx
            .state
            .combatant_mut(target)
            .ok_or(ExecError::MissingCombatant)?;
        combatant.health_max = combatant.health_max.saturating_add(amount);
        combatant.health_current = combatant.health_current.saturating_add(amount);
    }
    Ok(())
}''',
     '''    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        gain_max_health(ctx.state, target, amount)?;
    }
    Ok(())
}

/// "抬高最大生命"的**唯一**实现：上限 +N，当前血也 +N（StS 的 "raise your Max HP by N"）。
///
/// 两个节点共用（`gainMaxHealth` 与 `dealDamageAndGainMaxHealthIfFatal`）—— 同一个语义写两遍，
/// 迟早有一遍会漂。
fn gain_max_health(
    state: &mut crate::state::CombatState,
    target: &CombatantId,
    amount: i32,
) -> Result<(), ExecError> {
    let combatant = state
        .combatant_mut(target)
        .ok_or(ExecError::MissingCombatant)?;
    combatant.health_max = combatant.health_max.saturating_add(amount);
    combatant.health_current = combatant.health_current.saturating_add(amount);
    Ok(())
}

/// §238：`node.dealDamageAndGainMaxHealthIfFatal` 的实体 —— 与 `dealDamageAndHealByLoss` 同形，
/// 只是"读完自己的结果"之后做的是抬上限而不是回血。
fn deal_damage_and_gain_max_health_if_fatal_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let ignores_block = node.bool_field("IgnoresBlock")?.unwrap_or(false);
    let gain = node
        .int_field("MaxHealthGain")?
        .ok_or(IrError::Missing("MaxHealthGain"))?;
    if gain <= 0 {
        return Err(ExecError::Modifier);
    }
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let source = ctx.source;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    if count == 0 {
        return resume_later(ctx.state, frame, slot);
    }
    let mut fatal = false;
    for target in targets.iter().take(count) {
        resolve_damage(ctx, target, amount, ignores_block)?;
        stats.effects = stats.effects.saturating_add(1);
        // "Fatal" 的判据是**目标真的倒了**（血量 ≤ 0），不是"伤害超过血量" —— 被格挡吃掉的
        // 伤害不会让人死，而这条判据以后加"死亡拦截"（Fairy in a Bottle）时仍然对。
        if ctx
            .state
            .combatant(target)
            .is_some_and(|combatant| combatant.health_current <= 0)
        {
            fatal = true;
        }
    }
    if fatal {
        if let Some(owner) = source {
            gain_max_health(ctx.state, &owner, gain)?;
        }
    }
    resume_later(ctx.state, frame, slot)
}'''),
])
print('done')
