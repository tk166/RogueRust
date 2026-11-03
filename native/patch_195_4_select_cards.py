"""§195.4 (D1): card selection -- `node.selectCards`, the first primitive that can *ask which card*.

`sel.rs` deliberately refuses `sel.deckCards` / `sel.matching` / `sel.random` / `sel.choose`
("card selectors / player selectors", `UnsupportedKind`, never silently empty). What the content had
no way to say, then, was "the highest-rarity card in the draw pile" (Bronze Orb's `Stasis`).

This adds one node, spelled out rather than a general predicate language:

    node.selectCards {
        OwnerSelector,      // whose piles (the *target*, e.g. `sel.allEnemies` from an orb)
        FromZone,           // "DrawPile" | "DiscardPile" | "Hand" | "ExhaustPile"
        FallbackZone,       // optional: used when `FromZone` is empty (Stasis: draw, else discard)
        Order,              // "HighestRarity" | "First" | "Random"
        Count,              // 1..=8, literal
        ToZone,             // where the chosen cards go (`SetAsidePile` for Stasis)
        Placement,          // optional, default Bottom
    }

It moves cards by **enqueueing** `EffectRequest::MoveCardToZone` per card -- the same request the
existing `node.moveCardToZone` uses, so triggers still see the moves and the "one request, one effect"
accounting (`ExecStats::effects`) stays true.

Rarity rank -- what "highest" means, stated once:

    Rare 4 > Uncommon 3 > Common 2 > Basic 1 > Status 0 = Curse 0

(The card table's own strings are `Basic`/`Common`/`Uncommon`/`Rare`/`Status`/`Curse`; the rank is
about **value**, so Status/Curse sit at the bottom rather than at the enum's numeric position --
that is the behaviour "it steals your best card" describes.)

`Random` is the one order that consumes a `random_step`: unlike an intent (§195.3) an effect is not
re-derived for display, so drawing here cannot make a preview flicker.
"""
import io


def sub(path, pairs):
    src = io.open(path, encoding="utf-8").read()
    for old, new, what in pairs:
        assert src.count(old) == 1, "%s / %s: %d x %r" % (path, what, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(src)
    print("patched", path)


# ---------------------------------------------------------------- ir.rs: the node kind
sub("kernel/rd-core/src/ir.rs", [(
"""    /// `node.repeat` —— 把 `Body` 跑 `Count` 遍（**参考有、内核此前没移植**，§146）。""",
"""    /// `node.selectCards` —— **挑卡并搬卡**（§195.4，本内核自己的节点）。
    ///
    /// 参考的词表里有四个 `sel.*` 卡选择器，`sel.rs` 明确拒绝了它们（"卡选择器 / 玩家选择"），
    /// 于是内容无法说"抽牌堆里稀有度最高的那张"。Stasis 需要它，所以这里只加**一个**具体节点，
    /// 而不是一套谓词语言：`{OwnerSelector, FromZone, FallbackZone?, Order, Count, ToZone, Placement?}`。
    SelectCards,
    /// `node.repeat` —— 把 `Body` 跑 `Count` 遍（**参考有、内核此前没移植**，§146）。""",
    "NodeKind variant"), (
"""            NodeKind::Repeat => "node.repeat",""",
"""            NodeKind::SelectCards => "node.selectCards",
            NodeKind::Repeat => "node.repeat",""",
    "wire name"), (
"""            NodeKind::Repeat,
        ];""",
"""            NodeKind::SelectCards,
            NodeKind::Repeat,
        ];""",
    "ALL array")])

# ---------------------------------------------------------------- exec.rs: dispatch
sub("kernel/rd-core/src/exec.rs", [(
"""        NodeKind::MoveCardToZone => move_card_to_zone_node(node, ctx, frame, slot, stats),""",
"""        NodeKind::MoveCardToZone => move_card_to_zone_node(node, ctx, frame, slot, stats),
        NodeKind::SelectCards => select_cards_node(node, ctx, frame, slot, stats),""",
    "dispatch"), (
"""fn move_card_to_zone_node(""",
"""/// §195.4：**挑** `FromZone`（空则 `FallbackZone`）里按 `Order` 排好的前 `Count` 张，搬去 `ToZone`。
///
/// 搬卡走 `EffectRequest::MoveCardToZone`（与 `node.moveCardToZone` 同一个请求），所以触发器照样
/// 看得见、`ExecStats::effects` 的"一次请求一次效果"照样成立。
fn select_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    let from_name = node.str_field("FromZone")?.ok_or(IrError::Missing("FromZone"))?;
    let from_zone = zone_from_wire_name(from_name).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    let fallback = match node.str_field("FallbackZone")? {
        Some(name) => Some(zone_from_wire_name(name).ok_or(ExecError::Ir(IrError::UnknownKind))?),
        None => None,
    };
    let order_name = node.str_field("Order")?.ok_or(IrError::Missing("Order"))?;
    let count = node.int_field("Count")?.ok_or(IrError::Missing("Count"))?;
    if !(1..=MAX_SELECTED_CARDS as i32).contains(&count) {
        return Err(ExecError::Ir(IrError::Missing("Count")));
    }
    let count = count as usize;
    let to_name = node.str_field("ToZone")?.ok_or(IrError::Missing("ToZone"))?;
    let to_zone = zone_from_wire_name(to_name).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    let placement = match node.str_field("Placement")? {
        None => ZonePlacement::Bottom,
        Some(name) => placement_from_wire_name(name).ok_or(ExecError::Ir(IrError::UnknownKind))?,
    };

    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let owner_count = resolve_targets(owner_selector, ctx, &mut owners)?;
    // 与 `moveCardToZone` 同一条：解不出 owner ⇒ no-op（没有卡可搬，也不是错误）。
    let Some(owner) = owners.first().copied().filter(|_| owner_count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };

    // Candidates: `(card instance id, rarity rank)` in **pile order**.
    let mut candidates = [CardInstanceId::EMPTY; MAX_SELECTED_CARDS * 8];
    let mut ranks = [0u8; MAX_SELECTED_CARDS * 8];
    let mut found = 0usize;
    for zone in core::iter::once(from_zone).chain(fallback.into_iter()) {
        for card in ctx.state.zone_cards(&owner, zone) {
            if found == candidates.len() {
                break;
            }
            candidates[found] = card.id;
            ranks[found] = card_rarity_rank(ctx.content, &card.definition_id);
            found += 1;
        }
        if found > 0 {
            // `FallbackZone` is a fallback, not a second batch: stop at the first pile that has a card.
            break;
        }
    }
    if found == 0 {
        // 没有卡可挑 ⇒ 空操作（不是错误）：一张空牌堆不是内容缺陷，它是战斗里最正常的一件事。
        return resume_later(ctx.state, frame, slot);
    }

    let mut order = [0usize; MAX_SELECTED_CARDS * 8];
    for index in 0..found {
        order[index] = index;
    }
    match order_name {
        "HighestRarity" => {
            // Stable selection of the `count` highest ranks; ties keep pile order.
            for index in 0..found {
                let mut best = index;
                for other in (index + 1)..found {
                    let (a, b) = (order[other], order[best]);
                    if ranks[a] > ranks[b] {
                        best = other;
                    }
                }
                order.swap(index, best);
            }
        }
        "First" => {}
        "Random" => {
            // One draw for the whole batch, then a Fisher-Yates pass: a single `random_step` per use
            // keeps the RNG ledger as readable as every other draw in the kernel.
            let mut indexes = [0u8; MAX_SELECTED_CARDS * 8];
            for index in 0..found {
                indexes[index] = index as u8;
            }
            crate::rng::shuffle_indexes(&mut indexes[..found], ctx.state.random_seed, ctx.state.random_step);
            ctx.state.random_step = ctx.state.random_step.saturating_add(1);
            for index in 0..found {
                order[index] = usize::from(indexes[index]);
            }
        }
        _ => return Err(ExecError::Ir(IrError::UnknownKind)),
    }

    for index in order.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::MoveCardToZone {
                owner,
                card: candidates[*index],
                to_zone,
                placement,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// §195.4：一张牌的**稀有度排名**（"最高稀有度"取哪一张）。
///
/// `Rare 4 > Uncommon 3 > Common 2 > Basic 1 > Status 0 = Curse 0`。
/// 卡表里的六种串是 `Basic/Common/Uncommon/Rare/Status/Curse`；排序按**价值**而不是枚举序号
/// —— Status/Curse 在 StS 的枚举里排在 Rare **之后**，照序号降序会变成"先偷诅咒"。
fn card_rarity_rank(content: Option<&Content<'_>>, definition: &crate::state::CardDefinitionId) -> u8 {
    let Some(content) = content else {
        return 0;
    };
    match content.card_rarity(definition.as_str()) {
        Some("Rare") => 4,
        Some("Uncommon") => 3,
        Some("Common") => 2,
        Some("Basic") => 1,
        _ => 0,
    }
}

fn move_card_to_zone_node(""",
    "impl")])

# the cap constant
sub("kernel/rd-core/src/exec.rs", [(
"""pub const MAX_COMBATANTS: usize""",
"""/// §195.4：`node.selectCards` 一次最多搬几张（与 `Count` 的上限是同一个数）。
///
/// 8 是**容量**，不是规则：超了报 `Missing("Count")`（一个越界的 Count 是内容错，不是"少搬几张"）。
pub const MAX_SELECTED_CARDS: usize = 8;

pub const MAX_COMBATANTS: usize""",
    "cap")])

print("selectCards: ir + exec")
