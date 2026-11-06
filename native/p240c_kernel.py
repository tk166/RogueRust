"""§240 内核（下二）：随机造牌的节点与请求实体。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
s = io.open(P, encoding='utf-8').read()

# 1) 请求解析臂
old = '''        EffectRequest::MoveCardToZone {
            owner,
            card,
            to_zone,
            placement,
        } => move_card_for(ctx, &owner, &card, to_zone, placement),'''
new = '''        EffectRequest::CreateRandomCard {
            owner,
            tag,
            count,
            to_zone,
            cost_zero,
        } => create_random_card_for(ctx, &owner, &tag, count, to_zone, cost_zero),
        EffectRequest::MoveCardToZone {
            owner,
            card,
            to_zone,
            placement,
        } => move_card_for(ctx, &owner, &card, to_zone, placement),'''
assert s.count(old) == 1
s = s.replace(old, new)

# 2) 节点 + 实体
anchor = '''/// `MoveCardToZone`：求卡实例表达式 → 解析 owner → **一条请求**（`:1936-1941`）。'''
assert s.count(anchor) == 1
IMPL = '''/// §240：`node.createRandomCardInstance` —— `{Tag, ToZone, Count, CostZero}`。
///
/// 只求值 + 入队（与其它产出型节点同一条口径）；**抽签在排空那一刻**发生，所以一局里两次
/// `Infernal Blade` 拿到的牌由 `random_step` 的顺序决定，与洗牌/随机目标同一本账。
fn create_random_card_instance_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let tag_text = node.str_field("Tag")?.ok_or(IrError::Missing("Tag"))?;
    let tag = crate::state::TagId::new(tag_text)?;
    let zone_text = node.str_field("ToZone")?.ok_or(IrError::Missing("ToZone"))?;
    let zone = zone_from_wire_name(zone_text).ok_or(ExecError::Ir(IrError::UnknownKind))?;
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
    let cost_zero = node.bool_field("CostZero")?.unwrap_or(false);
    let owner = ctx.source.ok_or(ExecError::MissingCombatant)?;
    ctx.state.enqueue_effect_with_owner(
        EffectRequest::CreateRandomCard {
            owner,
            tag,
            count,
            to_zone: zone,
            cost_zero,
        },
        Some(frame),
    )?;
    resume_later(ctx.state, frame, slot)
}

/// §240：`CreateRandomCard` 的实体 —— 按 tag 从卡表里抽一个定义，造实例，必要时把费用压到 0。
///
/// 池子（**有原因的排除**，见 `port_state` 那条 §240 注）：
/// * 只收带该 tag 的；
/// * 不收 `+` 行（升级行是同一张牌的另一个定义，StS 的随机池是基础牌）；
/// * 不收 **X 费牌**（本内核的每副本价格对 X 费牌看不见 ⇒ 造出来会"说 0 费、实际仍是全部能量"）。
fn create_random_card_for(
    ctx: &mut ExecContext<'_>,
    owner: &CombatantId,
    tag: &crate::state::TagId,
    count: i32,
    zone: CardZone,
    cost_zero: bool,
) -> Result<(), ExecError> {
    if count < 0 {
        return Err(ExecError::Modifier);
    }
    if count == 0 {
        return Ok(());
    }
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };
    for _ in 0..count {
        let (definition, printed) = pick_random_card_of_tag(ctx, content, tag, cost_zero)?;
        let Some(definition) = definition else {
            // 池子空 ⇒ 什么都不做（内容没给这个 tag 任何基础牌，这是内容的事，不是运行时错误）。
            return Ok(());
        };
        let slot = ctx
            .state
            .create_card_instance(owner, definition, zone)
            .map_err(ExecError::Capacity)?;
        if cost_zero {
            // §161.4：每副本价格。`-印刷费用` ⇒ 本回合 0 费；出牌付款后计数器被清掉。
            if let Some(printed) = printed {
                let key = crate::state::CounterId::new(crate::state::CARD_COST_DELTA_COUNTER)?;
                let card = ctx
                    .state
                    .card_mut(slot)
                    .ok_or(ExecError::MissingCombatant)?;
                let _ = card.set_mark_counter(key, -printed);
            }
        }
    }
    Ok(())
}

/// 按 tag 抽一张（同一次调用里 `random_step` 前进一格）。
///
/// 扫两遍：第一遍数池子有多大，第二遍取第 `picked` 个 —— 这样不需要把候选表存下来
/// （定容缓冲 + 卡表行数会撞上限，而"数一遍再取"只用两个计数器）。
fn pick_random_card_of_tag(
    ctx: &mut ExecContext<'_>,
    content: &crate::content::Content<'_>,
    tag: &crate::state::TagId,
    want_cost: bool,
) -> Result<(Option<CardDefinitionId>, Option<i32>), ExecError> {
    let mut total = 0usize;
    for row in content.rows(crate::content::Table::Card) {
        let index = row.index();
        let Some(card) = content.card(index) else { continue };
        let Some(definition) = content.definition_id(crate::content::EK_CARD, index) else {
            continue;
        };
        let _ = card;
        if !in_random_pool(content, definition.as_str(), tag) {
            continue;
        }
        total += 1;
    }
    if total == 0 {
        return Ok((None, None));
    }
    let picked = crate::rng::shuffled_pick_index(
        total,
        ctx.state.random_seed,
        ctx.state.random_step,
    );
    ctx.state.random_step = ctx.state.random_step.saturating_add(1);
    let mut seen = 0usize;
    for row in content.rows(crate::content::Table::Card) {
        let index = row.index();
        let Some(definition) = content.definition_id(crate::content::EK_CARD, index) else {
            continue;
        };
        if !in_random_pool(content, definition.as_str(), tag) {
            continue;
        }
        if seen == picked {
            let printed = if want_cost {
                crate::play::printed_energy_cost(
                    content,
                    definition.as_str(),
                    ctx.source.unwrap_or(CombatantId::EMPTY),
                )
            } else {
                None
            };
            return Ok((Some(definition), printed));
        }
        seen += 1;
    }
    Ok((None, None))
}

/// §240：这张定义进不进"随机造牌"的池子。
fn in_random_pool(
    content: &crate::content::Content<'_>,
    definition: &str,
    tag: &crate::state::TagId,
) -> bool {
    // `+` 行是同一张牌的另一个定义（随机池只收基础牌）。
    if definition.contains('+') {
        return false;
    }
    if content.card_has_tag(definition, tag.as_str()) != Some(true) {
        return false;
    }
    // X 费牌没有"印刷费用"这个数（`printed_energy_cost` 返回 `None`），排除。
    content.card_has_tag(definition, crate::battle::X_COST_TAG) != Some(true)
}

'''
s = s[:s.index(anchor)] + IMPL + s[s.index(anchor):]
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
print('impl inserted')
