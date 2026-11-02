"""§178: `node.destroyCombatant` -- the half of "split" that was missing.

`§177` found the freeze: `Exec(Capacity(Full(Combatants)))` on a Slime Boss fight. The root cause is
not the queue order, it is that **content cannot express "this combatant is gone"**:

* StS's Slime Boss split is *"the boss disappears, two slimes take its place"*.
* Our content could only say *"spawn two more"*, and it tried to make that "once only" by removing its
  own status -- but status writes are **queued requests**, so every damage instance of the same turn
  still saw the status and split again: 3 hits -> 6 summon -> `MAX_COMBATANTS` (12) -> loud throw.

`node.createCombatant` is applied **immediately** (`add_combatant`), so its counterpart must be too.
With destroy-then-spawn the guard is *structural*: the boss is no longer in the roster, so
`collect_triggers` has no bearer and the trigger cannot fire twice. No queue reordering needed.

Layer by layer:
* `state.rs`: `remove_combatant` (shifts `combatants`, `turn_order`, `card_zones` together, and refuses
  to touch the active combatant -- the turn loop addresses the active one by id).
* `ir.rs`: `NodeKind::DestroyCombatant` (`node.destroyCombatant`), appended so no wire value moves.
* `exec.rs`: the node itself (immediate, like `createCombatant`), dispatch, preflight list,
  and `kill` semantics: the target must exist and must not be the active combatant.
"""
import io

STATE = "kernel/rd-core/src/state.rs"
IR = "kernel/rd-core/src/ir.rs"
EXEC = "kernel/rd-core/src/exec.rs"

# ------------------------------------------------------------------ state.rs: remove_combatant

STATE_ANCHOR = """    /// Drops a combatant's pile entry, mirroring the reference's dictionary lookup: a combatant
    /// with no entry contributes no `cz=` line."""

STATE_NEW = '''    /// **Removes** a combatant from the fight (`node.destroyCombatant`, `port-plan.md` §178).
    ///
    /// Three lists hold a combatant and they must move together or `card_zones` stops lining up with
    /// `combatants`: the roster, the turn order, and that combatant's piles.
    ///
    /// ⚠️ Distinct from *dying*: a dead combatant **stays** in the roster and in the turn order (the
    /// turn advance skips it, `CombatState.cs:139-168`), and its statuses stay collectable -- that is
    /// how `Downed` triggers work. **Removal** is the stronger act: the bearer is gone, so no trigger
    /// can be collected from it ever again. That distinction is the whole point of this method.
    ///
    /// Refuses (`StateError::Active`) to remove the combatant whose turn it is: the turn processor
    /// addresses the active combatant **by id**, so deleting it mid-turn would leave a dangling id.
    pub fn remove_combatant(&mut self, id: &CombatantId) -> StateResult<Combatant> {
        if self.active_combatant_id == Some(*id) {
            return Err(CapacityError::ActiveCombatant);
        }
        let Some(index) = self.combatants.iter().position(|c| c.id == *id) else {
            return Err(CapacityError::MissingCombatant);
        };
        let combatant = *self.combatants.get(index).ok_or(CapacityError::MissingCombatant)?;
        // Turn order: shift down so the *relative* order of everyone else is untouched (the order is
        // semantics -- `turn_order` decides who acts next).
        let len = self.turn_order.len();
        let mut turn_index = None;
        for i in 0..len {
            if self.turn_order.get(i) == Some(id) {
                turn_index = Some(i);
                break;
            }
        }
        if let Some(from) = turn_index {
            for j in from..len - 1 {
                if let Some(moved) = self.turn_order.get(j + 1).copied() {
                    if let Some(slot) = self.turn_order.get_mut(j) {
                        *slot = moved;
                    }
                }
            }
            self.turn_order.pop();
        }
        // Roster: same shift-down.
        let len = self.combatants.len();
        for j in index..len - 1 {
            if let Some(moved) = self.combatants.get(j + 1).copied() {
                if let Some(slot) = self.combatants.get_mut(j) {
                    *slot = moved;
                }
            }
        }
        self.combatants.pop();
        // Piles: `detach_card_zones` already knows how to shift that list.
        self.detach_card_zones(id);
        // Obstacles/statuses keyed by combatant are dropped with the combatant itself: they live
        // inside `Combatant`, so nothing else to clean.
        Ok(combatant)
    }

    /// Drops a combatant's pile entry, mirroring the reference's dictionary lookup: a combatant
    /// with no entry contributes no `cz=` line.'''

# `CapacityError` is the shared error enum for `state.rs`; add the two new reasons next to the rest.
ERR_ANCHOR = """    /// `AddCombatant` with an id that is already in the fight (`CombatState.cs:228-229`).
    DuplicateCombatant,"""
ERR_NEW = """    /// `AddCombatant` with an id that is already in the fight (`CombatState.cs:228-229`).
    DuplicateCombatant,
    /// `node.destroyCombatant` asked to remove the combatant whose turn it is (§178).
    ///
    /// The turn processor addresses the active combatant **by id**, so removing it mid-turn would
    /// leave the loop holding a dangling id. Loud, and nothing is mutated.
    ActiveCombatant,
    /// `node.destroyCombatant` named a combatant that is not in the fight (§178).
    MissingCombatant,"""
# also the Display arm, next to DuplicateCombatant's
DISP_ANCHOR = """            Self::DuplicateCombatant => f.write_str("combatant id already present"),"""
DISP_NEW = """            Self::DuplicateCombatant => f.write_str("combatant id already present"),
            Self::ActiveCombatant => f.write_str("cannot remove the active combatant"),
            Self::MissingCombatant => f.write_str("no such combatant in the fight"),"""

# ------------------------------------------------------------------ ir.rs: the new kind

IR_ANCHOR = """    /// `node.repeat` —— 把 `Body` 跑 `Count` 遍（**参考有、内核此前没移植**，§146）。"""
IR_NEW = """    /// `node.destroyCombatant` —— **把一个战斗员移出战斗**（§178）。
    ///
    /// `createCombatant` 的另一半。StS 的 Slime Boss 是"Boss 消失、两只史莱姆顶替"，
    /// 而在此之前内容只能说"再造两只" —— 于是"只分裂一次"只能靠自摘状态，而状态写入是
    /// **入队请求**（§177 实测：同一回合三次伤害各分裂一次，直到容器满 12）。
    ///
    /// 移出是**结构性**的守卫：不再在名册里，`collect_triggers` 就收不到这个承受者，
    /// 触发器不可能再响第二次。
    DestroyCombatant,
    /// `node.repeat` —— 把 `Body` 跑 `Count` 遍（**参考有、内核此前没移植**，§146）。"""

IR_WIRE_ANCHOR = """            NodeKind::EndTurn => "node.endTurn","""
IR_WIRE_NEW = """            NodeKind::DestroyCombatant => "node.destroyCombatant",
            NodeKind::EndTurn => "node.endTurn","""

IR_ALL_ANCHOR = """        const ALL: [NodeKind; 19] = ["""
IR_ALL_NEW = """        const ALL: [NodeKind; 20] = ["""

IR_ALL_LIST_ANCHOR = """            // 本内核自己的第 16 种（分裂 / 召唤）。
            NodeKind::CreateCombatant,"""
IR_ALL_LIST_NEW = """            // 本内核自己的第 16 种（分裂 / 召唤）。
            NodeKind::CreateCombatant,
            // §178：第 20 种（分裂的另一半 —— 把本体移出战斗）。
            NodeKind::DestroyCombatant,"""

# ------------------------------------------------------------------ exec.rs: node + dispatch + preflight

EXEC_INTERMEDIATE_ANCHOR = """        | NodeKind::CreateCombatant"""
EXEC_INTERMEDIATE_NEW = """        | NodeKind::CreateCombatant
        // §178：`destroyCombatant` 与 `createCombatant` 对称 —— 立即生效，不走效果队列。
        | NodeKind::DestroyCombatant"""

EXEC_DISPATCH_ANCHOR = """    NodeKind::CreateCombatant => create_combatant_node(node, ctx, frame, slot, stats),"""
EXEC_DISPATCH_NEW = """    NodeKind::CreateCombatant => create_combatant_node(node, ctx, frame, slot, stats),
    NodeKind::DestroyCombatant => destroy_combatant_node(node, ctx, frame, slot, stats),"""

EXEC_NODE_ANCHOR = """/// `node.createCombatant`：**造一个战斗员**（分裂 / 召唤）。"""
EXEC_NODE_NEW = '''/// `node.destroyCombatant`：**把一个战斗员移出战斗**（§178）。
///
/// 字段：`TargetSelector`（与其它节点同名同义）。解析出来的每个目标都会被移出；
/// 一个都解析不出来就是**响亮失败**（`ExecError::NoSource`），因为"分裂"少了一半会让
/// 内容以为自己成功了，而局面里什么都没变。
///
/// 立即生效，**不**入队 —— 与 [`create_combatant_node`] 对称。原因不是风格：
/// "移除"是`once only` 唯一能表达出来的形式（见 `ir.rs` 的注释）。
fn destroy_combatant_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let _ = &mut *stats;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    if count == 0 {
        return Err(ExecError::NoSource);
    }
    for target in targets.iter().take(count) {
        // A target that is already gone is **not** an error: a multi-hit card can name the same
        // combatant twice, and StS treats "damage/heal a corpse" as a no-op. Only the *selector*
        // producing nothing is a content bug.
        if ctx.state.combatant(target).is_none() {
            continue;
        }
        let removed = ctx.state.remove_combatant(target)?;
        // Animation log (§142/§178): the page fades this ordinal out.
        crate::beat::record(
            ctx.state,
            crate::beat::Beat {
                kind: crate::beat::BeatKind::Destroyed,
                actor: match ctx.source {
                    Some(source) => crate::beat::ordinal_of(ctx.state, &source),
                    None => crate::beat::NOBODY,
                },
                target: crate::beat::ordinal_of(ctx.state, target),
                def: crate::beat::intern_def(ctx.state, removed.definition_id.as_str()),
                flags: 0,
            },
        );
    }
    resume_later(ctx.state, frame, slot)
}

/// `node.createCombatant`：**造一个战斗员**（分裂 / 召唤）。'''


def patch(path, edits):
    text = io.open(path, encoding="utf-8").read()
    for old, new in edits:
        assert text.count(old) == 1, (path, text.count(old), old[:70])
        text = text.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(text)
    print("patched", path)


patch(STATE, [(ERR_ANCHOR, ERR_NEW), (DISP_ANCHOR, DISP_NEW), (STATE_ANCHOR, STATE_NEW)])
patch(IR, [
    (IR_ANCHOR, IR_NEW),
    (IR_WIRE_ANCHOR, IR_WIRE_NEW),
    (IR_ALL_ANCHOR, IR_ALL_NEW),
    (IR_ALL_LIST_ANCHOR, IR_ALL_LIST_NEW),
])
patch(EXEC, [
    (EXEC_INTERMEDIATE_ANCHOR, EXEC_INTERMEDIATE_NEW),
    (EXEC_DISPATCH_ANCHOR, EXEC_DISPATCH_NEW),
    (EXEC_NODE_ANCHOR, EXEC_NODE_NEW),
])
