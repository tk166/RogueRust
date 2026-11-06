"""§241 内核（下）：强制出牌的实体。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
s = io.open(P, encoding='utf-8').read()

# 1) 三处穷尽 match
s = s.replace('''            | EffectRequest::CreateRandomCard { .. }
            | EffectRequest::MoveCardToZone { .. }''',
'''            | EffectRequest::CreateRandomCard { .. }
            | EffectRequest::PlayTopCardOfDrawPile { .. }
            | EffectRequest::MoveCardToZone { .. }''', 1)

s = s.replace('''        | EffectRequest::CreateRandomCard { .. }
        | EffectRequest::MoveCardToZone { .. }''',
'''        | EffectRequest::CreateRandomCard { .. }
        | EffectRequest::PlayTopCardOfDrawPile { .. }
        | EffectRequest::MoveCardToZone { .. }''', 1)

# 2) 解析臂
old = '''        EffectRequest::MoveCardToZone {
            owner,
            card,
            to_zone,
            placement,
        } => move_card_for(ctx, &owner, &card, to_zone, placement),'''
new = '''        EffectRequest::PlayTopCardOfDrawPile { owner } => play_top_card_for(ctx, &owner),
        EffectRequest::MoveCardToZone {
            owner,
            card,
            to_zone,
            placement,
        } => move_card_for(ctx, &owner, &card, to_zone, placement),'''
assert s.count(old) == 1
s = s.replace(old, new)

# 3) 节点（无字段，一个请求）
anchor = '''/// §240：`node.createRandomCardInstance` —— `{Tag, ToZone, Count, CostZero}`。'''
assert s.count(anchor) == 1
NODE = '''/// §241：`node.playTopCardOfDrawPile` —— 零字段，一条请求。
///
/// 求值只到"入队"为止：**抽牌堆顶是哪张**在排空那一刻才读（派发时读会让同一张牌被打两次）。
fn play_top_card_of_draw_pile_node(
    _node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let owner = ctx.source.ok_or(ExecError::MissingCombatant)?;
    ctx.state
        .enqueue_effect_with_owner(EffectRequest::PlayTopCardOfDrawPile { owner }, Some(frame))?;
    resume_later(ctx.state, frame, slot)
}

'''
s = s[:s.index(anchor)] + NODE + s[s.index(anchor):]

# 4) 实体
anchor2 = '''/// §240：`CreateRandomCard` 的实体'''
assert s.count(anchor2) == 1
IMPL = '''/// §241：`PlayTopCardOfDrawPile` 的实体 —— `Havoc`。
///
/// 四步，每一步都有一个"为什么不能省"：
/// 1. **移到手牌**：`plan_play` 的受理校验要求实例在**手牌**里（`CardNotInHand`）。这不是绕过校验，
///    而是 StS 的等价物 —— 它那时在 in-play 区，反正不在牌堆里；
/// 2. **绝对价格 = 0**：`Havoc` 不付这张牌的费。复用 §240 那一格（`standard.card_cost_override`），
///    不给 `PlayRequest` 再加一个 `free` 布尔；
/// 3. **目标**：攻击牌需要目标 ⇒ 随机一个活着的敌人（StS 的 Havoc 就是随机挑）。用 `random_step`
///    抽签，与随机目标/洗牌同一本账；
/// 4. **落区 `ExhaustPile`**：`PlayRequest::to_zone` 强制 —— `Havoc` 的文字是 "and Exhaust it"，
///    而同一张 `Strike` 平时进弃牌堆。
///
/// 被拒（例如抽到一张 `unplayable` 的牌）⇒ **放回抽牌堆顶**、什么都不发生。这是最保守的一条：
/// 既不假装"打出去了"（那会少一张牌），也不报错（那是一张合法牌让整场战斗炸掉）。
fn play_top_card_for(
    ctx: &mut ExecContext<'_>,
    owner: &CombatantId,
) -> Result<(), ExecError> {
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };
    let Some(slot) = ctx
        .state
        .card_zones(owner)
        .and_then(|zones| zones.slot_at(CardZone::DrawPile, 0))
    else {
        return Ok(()); // 抽牌堆空 ⇒ 什么都不做（不是错误）
    };
    let Some(card) = ctx.state.card(slot) else {
        return Ok(());
    };
    let instance = card.id;
    let definition = card.definition_id;
    // 1. 抽牌堆顶 → 手牌。
    ctx.state
        .move_card(owner, CardZone::DrawPile, CardZone::Hand, slot, ZonePlacement::Bottom)?;
    // 2. 这一份的价格就是 0。
    let price = crate::state::CounterId::new(crate::state::CARD_COST_OVERRIDE_COUNTER)?;
    if let Some(card) = ctx.state.card_mut(slot) {
        card.set_mark_counter(price, 0).map_err(ExecError::Capacity)?;
    }
    // 3. 攻击牌 ⇒ 随机一个活着的敌人。
    let target = if content.card_has_tag(definition.as_str(), "attack") == Some(true) {
        random_living_opponent(ctx, owner)
    } else {
        None
    };
    // 4. 打出去（落区强制消耗堆）。
    let request = crate::play::PlayRequest::to_zone(*owner, instance, target, CardZone::ExhaustPile);
    match crate::play::play_card(ctx.state, Some(content), &request) {
        Ok(_) => Ok(()),
        Err(_) => {
            // 被拒 ⇒ 放回抽牌堆顶，并把价格标记撤掉（否则它下次被抽到就莫名 0 费）。
            if let Some(card) = ctx.state.card_mut(slot) {
                if let Ok(key) = crate::state::CounterId::new(
                    crate::state::CARD_COST_OVERRIDE_COUNTER,
                ) {
                    let _ = card.clear_mark_counter(key);
                }
            }
            let Some((_, slot)) = ctx.state.find_card(owner, &instance) else {
                return Ok(());
            };
            ctx.state.move_card(
                owner,
                CardZone::Hand,
                CardZone::DrawPile,
                slot,
                ZonePlacement::Top,
            )?;
            Ok(())
        }
    }
}

/// §241：随机一个**活着的对手**（`None` = 场上没有）。
fn random_living_opponent(ctx: &mut ExecContext<'_>, owner: &CombatantId) -> Option<CombatantId> {
    let mut pool = [CombatantId::EMPTY; MAX_COMBATANTS];
    let mut count = 0usize;
    for combatant in ctx.state.combatants() {
        if combatant.id == *owner {
            continue;
        }
        if combatant.health_current <= 0 {
            continue;
        }
        if let Some(cell) = pool.get_mut(count) {
            *cell = combatant.id;
            count += 1;
        }
    }
    if count == 0 {
        return None;
    }
    let picked =
        crate::rng::shuffled_pick_index(count, ctx.state.random_seed, ctx.state.random_step);
    ctx.state.random_step = ctx.state.random_step.saturating_add(1);
    pool.get(picked).copied()
}

'''
s = s[:s.index(anchor2)] + IMPL + s[s.index(anchor2):]
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
print('impl inserted')
