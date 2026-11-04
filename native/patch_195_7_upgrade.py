"""§195.7: card upgrades (`node.upgradeCards`) -- and Draw Reduction, which needed no new clock.

# A. `node.upgradeCards`

StS's "upgrade" is a property of a card; in this content model it is the **definition id** (`burn` vs
`burn+`, `strike` vs `strike+`). So the node says exactly that:

    node.upgradeCards { OwnerSelector, CardDefinitionId, FromZone?, Count? }

* matches every instance of `CardDefinitionId` in the owner's piles (all four if `FromZone` is
  absent), up to `Count` (absent = all);
* rewrites each match's definition to `<id>+` **if the content has that row** -- a card with no `+`
  row (`dazed`) is left alone, which is StS's `canUpgrade() == false`, not an error;
* writes **directly** instead of enqueueing: a card's definition is not something any trigger can
  observe (`CardMovedToZone`/`CardInstanceCreated` are the card *events* this kernel has), and the
  reference's own upgrade path is a direct mutation too.

Hexaghost's Inferno is the first user: wiki says "Adds 3 Burns+ into your discard pile. **Upgrades
all Burns**." -- the second half had no vocabulary at all until now.

# B. Draw Reduction: the reference's timed clock is the wrong lever

§195.6's README said `Draw Reduction` was blocked because "the host never runs
`decrease_timed_statuses`". That diagnosis was half right: the host indeed does not run the
reference's timed clock (`DurationTurns` is stored and never decremented), **but every status in this
content already decays through a `TurnEnded` trigger** (`standard.weak` & co.) -- so a "one turn"
debuff is content, not kernel:

    standard.draw_reduction {
      PassiveModifiers: [{Pipeline: "TurnStartDraw", Operation: "AddPerStack", Magnitude: -1, ...}],
      Triggers: [{Event: "TurnEnded", modifyStatusStacks(self, -1)}],
    }

Applied during the enemy's turn, it lowers the *next* turn's draw and is gone by the one after --
which is exactly the wiki's "Draw 1 less card next turn".

Turning the reference's clock on instead would be **worse**: the decaying statuses would then tick
twice (trigger + clock) and every existing debuff would halve its duration. That is written down
here so the next reader does not "fix" it into a regression.
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

# ===========================================================================
# A. kernel: the node
# ===========================================================================
KERNEL = "kernel/rd-core/src/ir.rs"
src = io.open(KERNEL, encoding="utf-8").read()


def sub(text, old, new, what=""):
    assert text.count(old) == 1, "%s: %d x %r" % (what, text.count(old), old[:70])
    return text.replace(old, new)


src = sub(src,
"""    /// `node.selectCards` —— **挑卡并搬卡**（§195.4，本内核自己的节点）。""",
"""    /// `node.upgradeCards` —— **把牌升级**（§195.7，本内核自己的节点）。
    ///
    /// StS 的"升级"在这份内容里是**定义 id**（`burn` / `burn+`），所以这个节点做的事就是把匹配到的
    /// 实例的定义改成 `<id>+`。没有 `+` 行的卡（`dazed`）**保持原样** —— 那是 StS 的
    /// `canUpgrade() == false`，不是错误。
    UpgradeCards,
    /// `node.selectCards` —— **挑卡并搬卡**（§195.4，本内核自己的节点）。""",
    "NodeKind")
src = sub(src,
"""            NodeKind::SelectCards => "node.selectCards",""",
"""            NodeKind::UpgradeCards => "node.upgradeCards",
            NodeKind::SelectCards => "node.selectCards",""",
    "wire name")
src = sub(src,
"""            NodeKind::SelectCards,
            NodeKind::Repeat,""",
"""            NodeKind::UpgradeCards,
            NodeKind::SelectCards,
            NodeKind::Repeat,""",
    "ALL")
src = sub(src,
"""        const ALL: [NodeKind; 21] = [""",
"""        const ALL: [NodeKind; 22] = [""",
    "ALL size")
io.open(KERNEL, "w", encoding="utf-8", newline="").write(src)
print("patched", KERNEL)

EXEC = "kernel/rd-core/src/exec.rs"
src = io.open(EXEC, encoding="utf-8").read()
src = sub(src,
"""        NodeKind::SelectCards => select_cards_node(node, ctx, frame, slot, stats),""",
"""        NodeKind::SelectCards => select_cards_node(node, ctx, frame, slot, stats),
        NodeKind::UpgradeCards => upgrade_cards_node(node, ctx, frame, slot, stats),""",
    "dispatch")
src = sub(src,
"""        // §195.4：`selectCards`（挑卡 + 搬卡）。没有孩子，预检只登记它。
        | NodeKind::SelectCards""",
"""        // §195.4：`selectCards`（挑卡 + 搬卡）。没有孩子，预检只登记它。
        | NodeKind::SelectCards
        // §195.7：`upgradeCards`（改定义 id），同上。
        | NodeKind::UpgradeCards""",
    "preflight")
src = sub(src,
"""/// §195.4：**挑** `FromZone`（空则 `FallbackZone`）里按 `Order` 排好的前 `Count` 张，搬去 `ToZone`。""",
"""/// §195.7：把 `OwnerSelector` 的牌堆里所有 `CardDefinitionId` 的实例升级成 `<id>+`。
///
/// **直接写**，不入队：一张牌的定义不是任何触发器看得见的东西（本内核的卡事件只有
/// `CardMovedToZone` / `CardInstanceCreated`），参考的升级路径也是直接改。
///
/// 没有 `+` 行的定义（例如 `dazed`）**平静跳过**：那是 StS 的 `canUpgrade() == false`，不是内容错。
fn upgrade_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    let definition = node
        .str_field("CardDefinitionId")?
        .ok_or(IrError::Missing("CardDefinitionId"))?;
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

    // The upgraded definition. `None` = this card has no `+` row -> nothing to do.
    let Some(content) = ctx.content else {
        return resume_later(ctx.state, frame, slot);
    };
    let mut buffer = [0u8; 64];
    let text = definition.as_str();
    if text.len() + 1 >= buffer.len() {
        return Err(ExecError::Ir(IrError::Missing("CardDefinitionId")));
    }
    buffer[..text.len()].copy_from_slice(text.as_bytes());
    buffer[text.len()] = b'+';
    let upgraded_text = core::str::from_utf8(&buffer[..text.len() + 1])
        .map_err(|_| ExecError::Ir(IrError::Missing("CardDefinitionId")))?;
    if content.lookup_in(upgraded_text, crate::content::EK_CARD).is_none() {
        return resume_later(ctx.state, frame, slot);
    }
    let upgraded = crate::state::CardDefinitionId::new(upgraded_text)?;

    let zones: &[crate::state::CardZone] = match only_zone {
        Some(zone) => core::slice::from_ref(&zone),
        None => &crate::state::CardZone::ALL,
    };
    let mut changed = 0usize;
    for zone in zones {
        let Some(zones_data) = ctx.state.card_zones(&owner) else {
            break;
        };
        // Copy the slots out first: the loop below needs `&mut` on the card table.
        let mut slots = [0u16; crate::state::MAX_CARDS_PER_ZONE];
        let listed = zones_data.slots(*zone);
        let count = listed.len().min(slots.len());
        slots[..count].copy_from_slice(&listed[..count]);
        for raw in slots.iter().take(count) {
            if changed >= limit {
                break;
            }
            let Some(card) = ctx.state.card(crate::state::CardSlot(*raw)) else {
                continue;
            };
            if card.definition_id != crate::state::CardDefinitionId::new(text)? {
                continue;
            }
            if let Some(card) = ctx.state.card_mut(crate::state::CardSlot(*raw)) {
                card.definition_id = upgraded;
                changed += 1;
                stats.effects = stats.effects.saturating_add(1);
            }
        }
    }
    resume_later(ctx.state, frame, slot)
}

/// §195.4：**挑** `FromZone`（空则 `FallbackZone`）里按 `Order` 排好的前 `Count` 张，搬去 `ToZone`。""",
    "impl")
io.open(EXEC, "w", encoding="utf-8", newline="").write(src)
print("patched", EXEC)
