"""§227 (part 3): `node.upgradeCards` 的 `CardDefinitionId` 变成**可选**（缺席 = 整片牌区）。

Armaments+ 是 "upgrade **all** cards in your hand" —— 手上有什么定义，内容在写程序时并不知道。
"能不能升级"的判据也只留**一处**（`upgradable_definition`），因为这张牌要走两条路：
批量（`upgradeCards`）与玩家选的那一张（`chooseCards{Then: Upgrade}`）。
"""
import io

EXEC = 'kernel/rd-core/src/exec.rs'
src = io.open(EXEC, encoding='utf-8').read()

start = src.index('fn upgrade_cards_node(')
end = src.index('/// §195.4：**挑** `FromZone`')
old = src[start:end]

new = '''fn upgrade_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    // §227: absent = "every definition in the zone" (Armaments+ upgrades the **whole hand**, and
    // the content cannot name the definitions because it does not know what the player holds).
    let definition = node.str_field("CardDefinitionId")?;
    let only_zone = match node.str_field("FromZone")? {
        Some(name) => Some(zone_from_wire_name(name).ok_or(ExecError::Ir(IrError::UnknownKind))?),
        None => None,
    };
    let limit = match node.int_field("Count")? {
        Some(count) if count >= 0 => count as usize,
        Some(_) => return Err(ExecError::Ir(IrError::Missing("Count"))),
        None => usize::MAX,
    };

    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let owner_count = resolve_targets(owner_selector, ctx, &mut owners)?;
    let Some(owner) = owners.first().copied().filter(|_| owner_count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };

    let Some(content) = ctx.content else {
        return resume_later(ctx.state, frame, slot);
    };
    let wanted = match definition {
        Some(text) => Some(crate::state::CardDefinitionId::new(text)?),
        None => None,
    };

    let mut changed = 0usize;
    // `CardZone::ALL` 一格一个牌区（7 个）；只点名一个区时只走那一个槽。
    let zones: [crate::state::CardZone; crate::state::CARD_ZONE_COUNT] = match only_zone {
        Some(zone) => [zone; crate::state::CARD_ZONE_COUNT],
        None => crate::state::CardZone::ALL,
    };
    let zone_count = if only_zone.is_some() { 1 } else { zones.len() };
    for zone in zones.iter().take(zone_count).copied() {
        if changed >= limit {
            break;
        }
        let mut slots = [0u16; crate::state::MAX_CARDS_PER_ZONE];
        let count = match ctx.state.card_zones(&owner) {
            Some(data) => {
                let listed = data.slots(zone);
                let count = listed.len().min(slots.len());
                slots[..count].copy_from_slice(&listed[..count]);
                count
            }
            None => break,
        };
        for raw in slots.iter().take(count).copied() {
            if changed >= limit {
                break;
            }
            let slot_ref = crate::state::CardSlot::from_index(raw);
            let Some(card) = ctx.state.card(slot_ref) else {
                continue;
            };
            if let Some(wanted) = wanted {
                if card.definition_id != wanted {
                    continue;
                }
            }
            // §227: **one** answer to "can this be upgraded" -- the same helper the player-facing
            // `chooseCards{Then: Upgrade}` uses to narrow its options.
            let Some(upgraded) = upgradable_definition(content, card.definition_id.as_str()) else {
                continue;
            };
            if let Some(card) = ctx.state.card_mut(slot_ref) {
                card.definition_id = upgraded;
                changed += 1;
                stats.effects = stats.effects.saturating_add(1);
            }
        }
    }
    resume_later(ctx.state, frame, slot)
}

/// §227：这张定义**升级版的样子**，只在内容真的有一行 `+` 时给出。
///
/// 两条路必须给出同一个答案：`upgrade_cards_node`（批量/整片牌区）与 `chooseCards` 的
/// `Upgrade`（玩家选中的那一张）。所以判定只写这一遍，拼法只写 `state::upgraded_id` 那一遍。
fn upgradable_definition(
    content: &crate::content::Content<'_>,
    definition: &str,
) -> Option<crate::state::CardDefinitionId> {
    let upgraded = crate::state::upgraded_id(definition)?;
    if content
        .lookup_in(upgraded.as_str(), crate::content::EK_CARD)
        .is_none()
    {
        return None;
    }
    Some(upgraded)
}

'''
src = src[:start] + new + src[end:]

# `chooseCards` 的 Upgrade 收窄改用同一个 helper
old2 = '''        if matches!(then, crate::state::ChoiceThen::Upgrade) {
            let Some(content) = ctx.content else {
                return Err(ExecError::Ir(IrError::Missing("content")));
            };
            let definition = card.definition_id.as_str();
            let Some(upgraded) = crate::state::upgraded_id(definition) else {
                continue;
            };
            if content
                .lookup_in(upgraded.as_str(), crate::content::EK_CARD)
                .is_none()
            {
                continue;
            }
        }'''
new2 = '''        if matches!(then, crate::state::ChoiceThen::Upgrade) {
            let Some(content) = ctx.content else {
                return Err(ExecError::Ir(IrError::Missing("content")));
            };
            // §227: same helper as `upgrade_cards_node` -- "can this be upgraded" has one answer.
            if upgradable_definition(content, card.definition_id.as_str()).is_none() {
                continue;
            }
        }'''
assert src.count(old2) == 1
src = src.replace(old2, new2)

io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)
print('ok upgrade node')
