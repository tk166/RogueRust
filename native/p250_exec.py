"""§250 内核（2b/3）：`exec.rs` 的常量与四个节点的实现。

与 `p250_ir.py`（枚举/wire 名/反查表）分开是因为这一半的文本里有大量花括号与反引号 ——
一次 `write` 写清楚，比在一个大脚本里拼字符串安全（FACT §2）。
"""
import io

EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'

CONST_PATCH = (
    '''const DEFAULT_CARD_INSTANCE_COUNT: i32 = 1;''',
    '''const DEFAULT_CARD_INSTANCE_COUNT: i32 = 1;

/// §250：`node.offerRandomCards` 的默认候选数（StS 的 "choose 1 of 3"）与它的上限。
///
/// 上限与 `MAX_SELECTED_CARDS` 同一个理由：候选表是**定容**的（`Container::ChoiceOptions`），
/// 而"内容写了 200"会让 `Bounded::push` 在跑了一半的时候失败 —— 那是部分执行。
pub const MAX_OFFERED_CARDS: usize = 8;
const DEFAULT_OFFERED_CARDS: i32 = 3;''')

IMPLEMENTATIONS = r'''
/// §250：`node.dealDamageAndIfFatal` 的实体 —— `{TargetSelector, Amount, IgnoresBlock?, Element?,
/// Program}`。
///
/// 三条顺序都是语义：
/// 1. `Amount` **先**求值（`Ritual Dagger` 这一次的伤害不含"这一次涨的 3 点"）；
/// 2. 每个目标依次挨打，`fatal` = "**有任何一个**目标真的倒了"；
/// 3. 子节目在**伤害全部落地之后**才跑 —— 这正是"必须是一个节点"的理由（`sequence` 做不到）。
fn deal_damage_and_if_fatal_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    depth: u32,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let ignores_block = node.bool_field("IgnoresBlock")?.unwrap_or(false);
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    let mut fatal = false;
    for target in targets.iter().take(count) {
        resolve_damage(ctx, target, amount, ignores_block)?;
        stats.effects = stats.effects.saturating_add(1);
        // 与 §238 逐字相同：Fatal = 目标**真的倒了**（血量 <= 0），不是"伤害超过血量"。
        if ctx
            .state
            .combatant(target)
            .is_some_and(|combatant| combatant.health_current <= 0)
        {
            fatal = true;
        }
    }
    let branch = if fatal { node.node_field("Program")? } else { None };
    match branch {
        Some(body) => {
            // 在**本节点的槽位**里就地跑子节目（与 `dispatch_conditional` 同一个手法）：
            // 不新开节目槽，所以深度/步数预算仍然算在这棵树上。
            dispatch_node(body, ctx, frame, slot, depth + 1, stats)?;
            Ok(())
        }
        None => {
            if let Some(cell) = ctx.state.program_nodes_mut().get_mut(slot) {
                cell.kind = ProgramNodeKind::Pass;
            }
            Ok(())
        }
    }
}

/// §250：`node.gainGold` 的实体 —— `{Amount}`。
///
/// 直接写 `CombatState.gold_gained`（不走请求）：金币不是任何触发器看得见的东西。
/// `Amount` 为负 => 拒绝（内容写错了，不许悄悄当 0）。
fn gain_gold_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    if amount < 0 {
        return Err(ExecError::Modifier);
    }
    ctx.state.gold_gained = ctx.state.gold_gained.saturating_add(amount);
    resume_later(ctx.state, frame, slot)
}

/// §250：`node.createCardCopy` —— `{ToZone, Count?, Placement?}`，造**当前正在结算的那一份**的副本。
///
/// "当前这一份"取自 `ctx.resolving_card` —— 与 `card.counter` 读同一个东西。那不是巧合，
/// 而是"这一张牌自己"在内核里的唯一身份；没有它就没有答案（`MissingCombatant`）。
fn create_card_copy_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let zone_text = node.str_field("ToZone")?.ok_or(IrError::Missing("ToZone"))?;
    let zone = zone_from_wire_name(zone_text).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    let placement = match node.str_field("Placement")? {
        None | Some("Bottom") => crate::state::ZonePlacement::Bottom,
        Some("Top") => crate::state::ZonePlacement::Top,
        Some(_) => return Err(ExecError::Ir(IrError::UnknownKind)),
    };
    let count = match node.node_field("Count")? {
        None => DEFAULT_CARD_INSTANCE_COUNT,
        Some(term) => {
            let expr_ctx = ctx.expr_context();
            expr::eval_int(term, &expr_ctx)?
        }
    };
    if count < 0 {
        return Err(ExecError::Modifier);
    }
    let Some(resolving) = ctx.resolving_card else {
        return Err(ExecError::MissingCombatant);
    };
    let Some(definition) = ctx.state.card(resolving).map(|card| card.definition_id) else {
        return Err(ExecError::MissingCombatant);
    };
    let Some(owner) = ctx.source else {
        return Err(ExecError::MissingCombatant);
    };
    for _ in 0..count {
        ctx.state
            .create_card_instance_at(&owner, definition, zone, placement)
            .map_err(ExecError::Capacity)?;
    }
    resume_later(ctx.state, frame, slot)
}

/// §250：`node.offerRandomCards` 的实体 —— `{Count?, Min?, Max?}`：**三选一**。
///
/// 与 `chooseCards` 的分工：那个问"**已有的**哪几张"（候选是实例），这个问"这几张**新的**
/// 里要哪个"（候选是定义，`ChoiceSource::Offered`）。`then` 是 [`ChoiceThen::ToHandFree`] ——
/// "加进手牌，它这次免费"的整个语义都在内核里，页面只管显示。
///
/// 抽签走 `random_step`（与随机造牌/洗牌同一本账）并且**去重**：三张候选不许重复。
/// 池子不够 / 抽签凑不齐 => **不问**（一个凑不出候选的问句会把这局钉死；与 `chooseCards`
/// 的"候选比 `Min` 还少就不问"同一条裁决）。
fn offer_random_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let count = match node.node_field("Count")? {
        None => DEFAULT_OFFERED_CARDS,
        Some(term) => {
            let expr_ctx = ctx.expr_context();
            expr::eval_int(term, &expr_ctx)?
        }
    };
    if count <= 0 {
        return Err(ExecError::Modifier);
    }
    let want = usize::try_from(count)
        .unwrap_or(MAX_OFFERED_CARDS)
        .min(MAX_OFFERED_CARDS);
    let min = node.int_field("Min")?.unwrap_or(1);
    let max = node.int_field("Max")?.unwrap_or(1);
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };
    let Some(chooser) = ctx.source else {
        return Err(ExecError::MissingCombatant);
    };

    // 池子有多大 —— 先数一遍，再按去重的下标取定义（与 `pick_random_card_of_tag` 同一个手法）。
    let mut total = 0usize;
    for row in content.rows(crate::content::Table::Card) {
        let Some(definition) = content.entity_id(crate::content::Table::Card, row.index()) else {
            continue;
        };
        if in_offer_pool(content, definition) {
            total += 1;
        }
    }
    if total < want {
        return resume_later(ctx.state, frame, slot);
    }
    let mut picked = [0usize; MAX_OFFERED_CARDS];
    let mut picked_len = 0usize;
    let mut guard = 0usize;
    let guard_cap = total.saturating_mul(8).saturating_add(64);
    while picked_len < want && guard < guard_cap {
        let index =
            crate::rng::shuffled_pick_index(total, ctx.state.random_seed, ctx.state.random_step);
        ctx.state.random_step = ctx.state.random_step.saturating_add(1);
        guard += 1;
        if picked[..picked_len].contains(&index) {
            continue;
        }
        let Some(entry) = picked.get_mut(picked_len) else {
            break;
        };
        *entry = index;
        picked_len += 1;
    }
    if picked_len < want {
        return resume_later(ctx.state, frame, slot);
    }

    let mut offered = crate::state::Bounded::new();
    let mut seen = 0usize;
    for row in content.rows(crate::content::Table::Card) {
        let Some(definition) = content.entity_id(crate::content::Table::Card, row.index()) else {
            continue;
        };
        if !in_offer_pool(content, definition) {
            continue;
        }
        let wanted = picked[..picked_len].contains(&seen);
        seen += 1;
        if !wanted {
            continue;
        }
        let definition = CardDefinitionId::new(definition)?;
        offered
            .push(definition, crate::state::Container::ChoiceOptions)
            .map_err(ExecError::Capacity)?;
    }

    let question = crate::state::PendingChoice {
        chooser,
        source: crate::state::ChoiceSource::Offered,
        min,
        max,
        then: crate::state::ChoiceThen::ToHandFree,
        offered,
        candidates: crate::state::Bounded::new(),
    };
    // 已经有一个待决问句 => 嵌套提问，本内核明确不支持（与 `chooseCards` 同一条）。
    ctx.state
        .begin_choice(question)
        .map_err(|_| ExecError::Modifier)?;
    resume_later(ctx.state, frame, slot)
}

/// §250：`offerRandomCards` 的池子规则 —— **"你职业牌池里的真牌"**。
///
/// 从"排除了什么"来定义，因为我们的内容没有职业 tag（唯一的分色标记是 `colorless`）：
/// * `+` 行是同一张牌的另一个定义（池子只收基础牌，与 `in_random_pool` 同一条）；
/// * 无色牌 / 诅咒 / 状态 / 垃圾牌不是"职业牌池"的一部分；
/// * 不可打出的牌进候选等于给玩家几张废纸；
/// * X 费牌没有印刷费用（"免费"对它没有意义）。
fn in_offer_pool(content: &crate::content::Content<'_>, definition: &str) -> bool {
    if definition.contains('+') {
        return false;
    }
    for tag in ["colorless", "curse", "status", "junk", "unplayable"] {
        if content.card_has_tag(definition, tag) == Some(true) {
            return false;
        }
    }
    content.card_has_tag(definition, crate::battle::X_COST_TAG) != Some(true)
}

'''

ANCHOR = '/// §238：`node.dealDamageAndGainMaxHealthIfFatal` 的实体 —— 与 `dealDamageAndHealByLoss` 同形，'


def main():
    src = io.open(EXEC, encoding='utf-8').read()
    assert 'fn deal_damage_and_if_fatal_node' not in src, 'already patched'
    for old, new in [CONST_PATCH]:
        assert src.count(old) == 1, (old[:50], src.count(old))
        src = src.replace(old, new)
    assert src.count(ANCHOR) == 1
    src = src.replace(ANCHOR, IMPLEMENTATIONS.lstrip('\n') + ANCHOR)
    io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)
    print('exec.rs: const + 4 implementations inserted')


main()
