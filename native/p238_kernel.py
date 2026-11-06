"""§238 内核：三块小基建。

1. `node.gainMaxHealth` —— `Feed` 的 "If Fatal, raise your Max HP by 3"（也是事件/遗物
   "gain 2 Max HP" 的载体）。
2. 复制的作用域表 —— `Duplication Potion`（任意牌）与 `Double Tap`（只认 Attack）共用一条
   "下一张牌打两次"的机制，但**范围不同**；把范围写成一张表，而不是两个 if。
3. `ChoiceSource::ExhaustPile` —— `Exhume` 的"从消耗堆拿一张回手牌"。
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


# ------------------------------------------------------------------ 1) ir.rs：新节点
patch('ir.rs', [
    ('''    LoseHp,''', '''    LoseHp,
    /// §238：**抬高最大生命**（`Feed` 的 "If Fatal, raise your Max HP by 3"）。
    ///
    /// 与 `Heal` 分开：`Heal` 只动当前值（且被最大生命夹住），这条动的是**上限**，
    /// 并顺手把当前值一起抬高（StS 的 "raise your Max HP by N" 同时给你 N 点血）。
    GainMaxHealth,'''),
    ('''            NodeKind::LoseHp => "node.loseHp",''',
     '''            NodeKind::LoseHp => "node.loseHp",
            NodeKind::GainMaxHealth => "node.gainMaxHealth",'''),
])

# ------------------------------------------------------------------ 2) exec.rs：节点实现 + 消耗堆选牌
patch('exec.rs', [
    # 预检表（无孩子节点）
    ('''        // §233：`setDefensivePool`（把防御池设成某个值）。同上。
        | NodeKind::SetDefensivePool''',
     '''        // §238：`gainMaxHealth`（抬高上限）。无孩子。
        | NodeKind::GainMaxHealth
        // §233：`setDefensivePool`（把防御池设成某个值）。同上。
        | NodeKind::SetDefensivePool'''),
    # 派发
    ('''        NodeKind::LoseHp => lose_hp_node(node, ctx, frame, slot, stats),''',
     '''        NodeKind::LoseHp => lose_hp_node(node, ctx, frame, slot, stats),
        NodeKind::GainMaxHealth => gain_max_health_node(node, ctx, frame, slot, stats),'''),
    # 选牌来源：消耗堆
    ('''    let source = match from_zone {
        CardZone::Hand => crate::state::ChoiceSource::Hand,
        CardZone::DiscardPile => crate::state::ChoiceSource::DiscardPile,
        _ => return Err(ExecError::Ir(IrError::UnknownKind)),
    };''',
     '''    let source = match from_zone {
        CardZone::Hand => crate::state::ChoiceSource::Hand,
        CardZone::DiscardPile => crate::state::ChoiceSource::DiscardPile,
        // §238：`Exhume`（"把消耗堆里一张拿回手牌"）—— 问句的来源牌区就是消耗堆，
        // 页面按 zone id 3 读它（§161.5 的契约），所以那边不用改。
        CardZone::ExhaustPile => crate::state::ChoiceSource::ExhaustPile,
        _ => return Err(ExecError::Ir(IrError::UnknownKind)),
    };'''),
])

# gain_max_health_node 的实现：放在 lose_hp_node 之后
path = K + 'exec.rs'
s = io.open(path, encoding='utf-8').read()
anchor = '/// `LoseHp`：**失去生命**（不是伤害）'
assert s.count(anchor) == 1
IMPL = '''/// `GainMaxHealth`：**抬高最大生命**，并把当前生命一起抬高 `Amount`（§238）。
///
/// StS 的写法是 "raise your Max HP by 3" —— 上限 +3 **并且**当前血 +3（`Feed` 就是这么回血的）。
/// `Amount <= 0` ⇒ 抛（镜像里没有"降低上限"的牌，负数只可能是内容写错 ⇒ 响亮拒绝）。
fn gain_max_health_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    _frame: ProgramExecutionSlot,
    _slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    if amount <= 0 {
        return Err(ExecError::Modifier);
    }
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
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
}

'''
s = s[:s.index(anchor)] + IMPL + s[s.index(anchor):]
io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
print('patched exec.rs (gain_max_health_node)')

# ------------------------------------------------------------------ 3) state.rs：ChoiceSource::ExhaustPile
patch('state.rs', [
    ('''    /// 弃牌堆（Liquid Memories「把弃牌堆里一张拿回手牌」）。
    DiscardPile,''',
     '''    /// 弃牌堆（Liquid Memories「把弃牌堆里一张拿回手牌」）。
    DiscardPile,
    /// §238：**消耗堆**（Exhume「把消耗堆里一张拿回手牌」）。
    ExhaustPile,'''),
    ('''            Self::Hand => Some(CardZone::Hand),
            Self::DiscardPile => Some(CardZone::DiscardPile),''',
     '''            Self::Hand => Some(CardZone::Hand),
            Self::DiscardPile => Some(CardZone::DiscardPile),
            Self::ExhaustPile => Some(CardZone::ExhaustPile),'''),
])

# ------------------------------------------------------------------ 4) play.rs：复制作用域表
patch('play.rs', [
    ('''    let duplicate = state
        .combatant(&plan.source)
        .is_some_and(|combatant| total_status_stacks(combatant, DUPLICATION_STATUS) > 0);
    if duplicate {
        // 先把那一次花掉：否则第二遍的终态回调/下一次出牌又会看到它。
        spend_one_charge(state, &plan.source, DUPLICATION_STATUS)?;
    }''',
     '''    // §238：**谁允许"打两次"，以及它认哪一种牌**。
    //
    // Duplication Potion 是"下一张牌"，Double Tap 是"下一张 **Attack**"。两者是同一条机制的两个
    // 作用域，所以是一张**表**而不是两个 if —— 加第三种（将来的 Burst："下一张 Skill"）只加一行。
    // 每次出牌**最多**消费一条（StS 里两层"打两次"叠着也还是一张牌打两次，不是四次）。
    let duplicate_status = DUPLICATION_SCOPES.iter().find(|(status, tag)| {
        state.combatant(&plan.source).is_some_and(|combatant| {
            total_status_stacks(combatant, status) > 0
                && tag.map_or(true, |tag| plan.tags.contains(tag))
        })
    });
    let duplicate = duplicate_status.is_some();
    if let Some((status, _)) = duplicate_status {
        // 先把那一次花掉：否则第二遍的终态回调/下一次出牌又会看到它。
        spend_one_charge(state, &plan.source, status)?;
    }'''),
    ('''const DUPLICATION_STATUS: &str = "standard.duplication";''',
     '''const DUPLICATION_STATUS: &str = "standard.duplication";

/// §238：`(状态 id, 只认哪个标签)` —— `None` = 任意牌（Duplication Potion），
/// `Some("attack")` = 只认 Attack（Double Tap）。
///
/// 顺序有意义：先命中先生效（今天的两个范围不重叠，所以顺序只在"两者都有"时决定花掉哪一个）。
pub(crate) const DUPLICATION_SCOPES: &[(&str, Option<&str>)] = &[
    (DUPLICATION_STATUS, None),
    ("standard.double_tap", Some("attack")),
];'''),
])
print('done')
