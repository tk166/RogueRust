"""§228 (part 1): 两件内核能力。

1. `combatantDefensivePool` —— 读某个战斗员某个**防御池**的当前值（Body Slam 的"等于你的格挡"）。
   形状照 `combatantCurrentResource`（`Selector` + 池的 key），字段名是**我们定的**（理由同
   `currentHealth`：镜像里没有这条 op，定义权在 `docs/spec/sts-act1-plan.md` §9-4）。
2. `node.dealDamageToRandomTarget` —— `TargetSelector` 给出**候选池**，每次命中从池里**随机**挑一个
   （Sword Boomerang 的"随机敌人 3(4) 次"）。

为什么第 2 条必须是一个节点而不是"随机选择器"：选择器解析拿的是 `&CombatState`（只读），
而随机要**推进 `random_step`**（与洗牌/掷骰同一条账）。节点拿的是 `&mut ExecContext`，所以它是
唯一能既读状态又推进 RNG 的地方。`sel.random*` 这个串在 `sel.rs` 里一直是**明确拒绝**的。
"""
import io

EXPR = 'kernel/rd-core/src/expr.rs'
IR = 'kernel/rd-core/src/ir.rs'
EXEC = 'kernel/rd-core/src/exec.rs'


def rewrite(path, edits):
    src = io.open(path, encoding='utf-8').read()
    for old, new in edits:
        assert src.count(old) == 1, (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)


# ── 1) 表达式：防御池 ────────────────────────────────────────────────────────
rewrite(EXPR, [
    ('''    "combatantCurrentResource",''',
     '''    "combatantCurrentResource",
    // §228：某个战斗员某个**防御池**的当前值（"等于你的格挡"）。本内核自己的 kind —— 名字与
    // 字段（`Selector` / `PoolId`）照 `combatantCurrentResource` 的形状，理由同 `currentHealth`：
    // 镜像里没有这条 op，定义权在我们（`docs/spec/sts-act1-plan.md` §9-4）。
    "combatantDefensivePool",'''),
    ('''        "combatantCurrentResource" => {''',
     '''        // §228: `DefensivePool.Current` for the named pool of one combatant. Missing pool ⇒ `0`
        // (same rule as `combatantCurrentResource`: a pool that was never written reads as empty,
        // not as an error -- "no block" is the normal state).
        "combatantDefensivePool" => {
            let key = node.str_field("PoolId")?.ok_or(IrError::Missing("PoolId"))?;
            let Some(target) = read_single_target(node, ctx)? else {
                return Ok(0);
            };
            let Some(combatant) = ctx.state.combatant(&target) else {
                return Ok(0);
            };
            for pool in combatant.defensive_pools() {
                if pool.key.as_str() == key {
                    return Ok(pool.pool.current);
                }
            }
            Ok(0)
        }

        "combatantCurrentResource" => {'''),
])

# ── 2) 节点词表 ──────────────────────────────────────────────────────────────
rewrite(IR, [
    ('''    /// `node.chooseCards` —— **问玩家要哪几张牌，然后复制它们**（§226，本内核自己的节点）。''',
     '''    /// `node.dealDamageToRandomTarget` —— **每次命中从候选池里随机挑一个目标**（§228）。
    ///
    /// StS 的 `Sword Boomerang` 是 "Deal 3 damage to a random enemy 3 (4) times"：不是"打所有敌人"，
    /// 也不是"打同一个敌人"，而是**每一击各自重掷**。`TargetSelector` 给出的是**候选池**
    /// （内容写 `sel.allEnemies`），抽签在节点里做。
    ///
    /// 为什么不是"随机选择器"：选择器解析拿的是 `&CombatState`（只读），而随机要推进
    /// `random_step`（与洗牌/掷骰同一条账）—— 只有拿 `&mut ExecContext` 的节点能同时做这两件事。
    DealDamageToRandomTarget,
    /// `node.chooseCards` —— **问玩家要哪几张牌，然后复制它们**（§226，本内核自己的节点）。'''),
    ('''            NodeKind::ChooseCards => "node.chooseCards",''',
     '''            NodeKind::DealDamageToRandomTarget => "node.dealDamageToRandomTarget",
            NodeKind::ChooseCards => "node.chooseCards",'''),
    ('''        const ALL: [NodeKind; 24] = [''',
     '''        const ALL: [NodeKind; 25] = ['''),
    ('''            // §226：问玩家要哪几张牌，然后复制（Dual Wield）。
            NodeKind::ChooseCards,''',
     '''            // §226：问玩家要哪几张牌，然后复制（Dual Wield）。
            NodeKind::ChooseCards,
            // §228：每次命中随机挑一个目标（Sword Boomerang）。
            NodeKind::DealDamageToRandomTarget,'''),
])

# ── 3) 节点实体 + 预检 + 分发 ────────────────────────────────────────────────
rewrite(EXEC, [
    ('''        // §226：`chooseCards`（问玩家 + 复制）。同上，只有字段没有孩子。
        | NodeKind::ChooseCards''',
     '''        // §226：`chooseCards`（问玩家 + 复制）。同上，只有字段没有孩子。
        | NodeKind::ChooseCards
        // §228：`dealDamageToRandomTarget`（抽签 + 打伤害）。同上。
        | NodeKind::DealDamageToRandomTarget'''),
    ('''        NodeKind::ChooseCards => choose_cards_node(node, ctx, frame, slot, stats),''',
     '''        NodeKind::ChooseCards => choose_cards_node(node, ctx, frame, slot, stats),
        NodeKind::DealDamageToRandomTarget => {
            deal_damage_to_random_target_node(node, ctx, frame, slot, stats)
        }'''),
    ('''/// `GainBlock`：`Amount` → `TargetSelector` → **每个目标一条请求**（`:775`）。''',
     '''/// §228：`node.dealDamageToRandomTarget` 的实体 —— `Times` 次命中，**每次**从候选池里重掷一个目标。
///
/// 三条语义（都能单独坏掉，所以各有一条判据）：
/// * **每一击各自抽签**：不是"抽一次、打 N 下"。抽签用
///   [`crate::rng::shuffled_pick_index`]（与洗牌同一个生成器），并且**每一击推进一格
///   `random_step`** —— 与 `shuffle_candidates` 同一本账，否则两次同种抽签会给出同一个结果；
/// * 候选池是**派发那一刻**解析出来的（`TargetSelector`），所以这一击抽到谁就是谁，中途死掉的目标
///   不会再被抽到（`resolve_effect` 对已离场目标是 no-op，见 §178）；
/// * 池子是空的 ⇒ **一击都没有**（不是错误）：一条对所有活敌的抽签，在没有活敌时本来就没有答案。
fn deal_damage_to_random_target_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    // 求值顺序与 `dealDamage` 一致：先 `Amount`，再解析目标。
    let amount = eval_amount(node, "Amount", ctx)?;
    let ignores_block = node.bool_field("IgnoresBlock")?.unwrap_or(false);
    let times = node.int_field("Times")?.ok_or(IrError::Missing("Times"))?;
    if !(1..=MAX_RANDOM_HITS as i32).contains(&times) {
        return Err(ExecError::Ir(IrError::Missing("Times")));
    }
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let source = ctx.source;

    let mut pool = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut pool)?;
    if count == 0 {
        return resume_later(ctx.state, frame, slot);
    }

    for _ in 0..times {
        let picked = crate::rng::shuffled_pick_index(
            count,
            ctx.state.random_seed,
            ctx.state.random_step,
        );
        // 一格 `random_step` 一次抽签（`shuffle_candidates` 同一条账）。
        ctx.state.random_step = ctx.state.random_step.saturating_add(1);
        let Some(target) = pool.get(picked).copied() else {
            // `shuffled_pick_index` 的返回值必在 `[0, count)`；走到这里说明那个不变量破了。
            return Err(ExecError::Ir(IrError::List));
        };
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::DealDamage {
                target: Some(target),
                amount,
                ignores_block,
                source,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// `GainBlock`：`Amount` → `TargetSelector` → **每个目标一条请求**（`:775`）。'''),
])

# 每次最多几击
src = io.open(EXEC, encoding='utf-8').read()
anchor = '''/// §226：`node.chooseCards` 一次最多造几份副本（`Copies` 的上限）。'''
assert src.count(anchor) == 1
src = src.replace(anchor, '''/// §228：`node.dealDamageToRandomTarget` 的 `Times` 上限。
///
/// 24 是 `MAX_COMBATANTS` 的两倍，也是"一次出牌最多几条伤害请求"的量级上界（§225 的整手牌消耗
/// 也是这个数量级）。再往上不是"更强的牌"，而是把效果队列（`MAX_PENDING_EFFECTS`）当无限用 ——
/// 那条线会在运行期以 `Capacity` 响亮失败，但**内容层就该先说不像话**。
pub const MAX_RANDOM_HITS: usize = 24;

/// §226：`node.chooseCards` 一次最多造几份副本（`Copies` 的上限）。''')
io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)
print('ok kernel')
