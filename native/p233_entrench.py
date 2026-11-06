"""§233: `node.setDefensivePool`（Entrench 的载体）+ `Entrench` 两行内容。

复现 `act1_slice` 的那 13 条（第一次提交前被撤回）。这一版把三条已知的坑都带上：
* 检查器的 `amount()` 只在含"动态尺寸"时才展开 `multiply`（`card.counter` **或**
  `combatantDefensivePool`）；
* `INV_CARDS` / `INV_CARD_WIKI` 里 `multiply` 的事实形状；
* 内容行的 `+` 只降费（wiki: Cost 2 / CostPlus 1，Uncommon）。
"""
import io
import json

IR = 'kernel/rd-core/src/ir.rs'
EXEC = 'kernel/rd-core/src/exec.rs'
CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'native/sts_content_check.py'
INV = 'native/card_wiki_inventory.py'


def rewrite(path, edits):
    src = io.open(path, encoding='utf-8').read()
    for old, new in edits:
        assert src.count(old) == 1, (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)


rewrite(IR, [
    ('''    /// `node.dealDamageAndHealByLoss` —— 打伤害，然后按**实际掉的血**给来源回血（§231，`Reaper`）。''',
     '''    /// `node.setDefensivePool` —— 把某个防御池**设成**某个值（§233，`Entrench`）。
    ///
    /// 与 `node.gainBlock` 的分工是**设**与**加**：那个走格挡修饰管线（灵巧/脆弱），这个不走 ——
    /// "Double your Block" 翻倍的是当前格挡本身，不是"再获得等量格挡"。
    SetDefensivePool,
    /// `node.dealDamageAndHealByLoss` —— 打伤害，然后按**实际掉的血**给来源回血（§231，`Reaper`）。'''),
    ('''            NodeKind::DealDamageAndHealByLoss => "node.dealDamageAndHealByLoss",''',
     '''            NodeKind::SetDefensivePool => "node.setDefensivePool",
            NodeKind::DealDamageAndHealByLoss => "node.dealDamageAndHealByLoss",'''),
    ('''        const ALL: [NodeKind; 28] = [''', '''        const ALL: [NodeKind; 29] = ['''),
    ('''            // §231：打伤害并按实际掉血回血（Reaper）。
            NodeKind::DealDamageAndHealByLoss,''',
     '''            // §231：打伤害并按实际掉血回血（Reaper）。
            NodeKind::DealDamageAndHealByLoss,
            // §233：把防御池设成某个值（Entrench）。
            NodeKind::SetDefensivePool,'''),
])

rewrite(EXEC, [
    ('''        // §231：`dealDamageAndHealByLoss`（打伤害 + 按掉血回血）。同上。
        | NodeKind::DealDamageAndHealByLoss''',
     '''        // §231：`dealDamageAndHealByLoss`（打伤害 + 按掉血回血）。同上。
        | NodeKind::DealDamageAndHealByLoss
        // §233：`setDefensivePool`（把防御池设成某个值）。同上。
        | NodeKind::SetDefensivePool'''),
    ('''        NodeKind::DealDamageAndHealByLoss => {''',
     '''        NodeKind::SetDefensivePool => set_defensive_pool_node(node, ctx, frame, slot, stats),
        NodeKind::DealDamageAndHealByLoss => {'''),
    ('''fn gain_block_node(''',
     '''/// §233：`node.setDefensivePool` 的实体 —— `{TargetSelector, PoolId, Amount}`。
///
/// **每个目标直接写**（不入队）：这是一个"设"，不是"加"，所以没有修饰器要跑、也没有事件要发。
/// `max` 传 `None` ⇒ 保持那一格原有的上限（`set_defensive_pool` 的字典语义）。
///
/// 负值是**内容 bug**，借 [`ExecError::Modifier`] 响亮失败（与 `gainBlock` 的受理不变量同一条）。
fn set_defensive_pool_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let pool = node.str_field("PoolId")?.ok_or(IrError::Missing("PoolId"))?;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    if amount < 0 {
        return Err(ExecError::Modifier);
    }
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    let key = crate::state::DefensivePoolId::new(pool)?;
    for target in targets.iter().take(count) {
        let Some(combatant) = ctx.state.combatant_mut(target) else {
            continue;
        };
        combatant.set_defensive_pool(key, amount, None)?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

fn gain_block_node('''),
])

# ── 内容 ────────────────────────────────────────────────────────────────────
SEL_SOURCE = {"kind": "sel.source",
              "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def entrench_root():
    return {
        "kind": "node.setDefensivePool",
        "value": {
            "TargetSelector": SEL_SOURCE,
            "PoolId": {"value": "standard.block"},
            "Amount": {
                "kind": "multiply",
                "value": {
                    "Left": const(2),
                    "Right": {"kind": "combatantDefensivePool",
                              "value": {"Selector": SEL_SOURCE,
                                        "PoolId": {"value": "standard.block"}}},
                },
            },
            "ResultKey": None,
        },
    }


raw = io.open(CONTENT, encoding='utf-8').read()
data = json.loads(raw)
assert 'entrench' not in {row['Id'] for row in data['Cards']}


def row(cid, name, cost):
    return {
        "Id": cid,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": "Double your Block.",
        "Costs": [{"ResourceId": {"value": "standard.energy"}, "Amount": cost}],
        "Tags": [{"value": "skill"}],
        "Rarity": "Uncommon",
        "Program": {"Id": {"Value": "(unnamed)"}, "Root": entrench_root(),
                    "MaxNodeDepth": 64, "MaxProgramSteps": 1024},
        "LifecyclePrograms": {},
        "RetainInHandOnTurnEnd": False,
        "TurnEndHandDestinationZone": "DiscardPile",
        "PlayedCardDestinationZone": "DiscardPile",
    }


data['Cards'].append(row('entrench', 'Entrench', 2))
data['Cards'].append(row('entrench+', 'Entrench+', 1))
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(data, ensure_ascii=False, indent=2) + '\n')

# ── 检查器 + wiki 清单 ──────────────────────────────────────────────────────
rewrite(CHECK, [
    ('''        elif kind == "node.dealDamageAndHealByLoss":''',
     '''        elif kind == "node.setDefensivePool":
            # §233: "set the pool to this" as a fact -- **gain** and **set** are different rules, so
            # they are different facts (a `GainBlock`-based Entrench would double *after* modifiers).
            out.append(("setPool", body["PoolId"]["value"], amount(body["Amount"]),
                        tgt(body["TargetSelector"])))
        elif kind == "node.dealDamageAndHealByLoss":'''),
    ('''    if expr.get("kind") == "card.counter":
        # §229: a size that is **this copy's** counter''',
     '''    if expr.get("kind") == "multiply" and _has_dynamic_size(expr):
        # §233: an `add`/`multiply` that mentions a **dynamic** size (this copy's counter, or a
        # defensive pool) is unwrapped; every other one keeps the old opaque shape (`('expr', ...)`),
        # because rewriting those would churn facts §193/§216 already froze.
        return ("multiply", amount(expr["value"]["Left"]), amount(expr["value"]["Right"]))
    if expr.get("kind") == "card.counter":
        # §229: a size that is **this copy's** counter'''),
    ('''    if expr.get("kind") == "add" and _has_card_counter(expr):''',
     '''    if expr.get("kind") == "add" and _has_dynamic_size(expr):'''),
    ('''def _has_card_counter(expr):
    """Does this expression tree mention `card.counter` anywhere?"""
    if not isinstance(expr, dict):
        return False
    if expr.get("kind") == "card.counter":
        return True''',
     '''def _has_dynamic_size(expr):
    """Does this expression tree mention a size the kernel has to read from state?

    Two kinds so far: `card.counter` (§229) and `combatantDefensivePool` (§233). Both make an
    `add`/`multiply` worth unwrapping; anything else stays opaque on purpose.
    """
    if not isinstance(expr, dict):
        return False
    if expr.get("kind") in ("card.counter", "combatantDefensivePool"):
        return True'''),
    ('''        return any(_has_card_counter(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_card_counter(item) for item in value)''',
     '''        return any(_has_dynamic_size(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_dynamic_size(item) for item in value)'''),
    ('''    # ---- §232：两张 X 费牌（载体全在：`repeat` + `x.cost`） -----------------------------------''',
     '''    # ---- §233：Entrench（格挡翻倍 = set 而不是 gain） ----------------------------------------
    "entrench": {"Cost": 2, "Tags": ["skill"],
                 "Facts": [("setPool", "standard.block",
                            ("multiply", 2, ("pool", "standard.block", "source")), "source")]},
    "entrench+": {"Cost": 1, "Tags": ["skill"],
                  "Facts": [("setPool", "standard.block",
                             ("multiply", 2, ("pool", "standard.block", "source")), "source")]},
    # ---- §232：两张 X 费牌（载体全在：`repeat` + `x.cost`） -----------------------------------'''),
])

rewrite(INV, [
    ('''    # 没有数字的牌：纯关键字/状态牌。''',
     '''    # §233：`Double your Block.`（`+` 只降费）—— `set` 语义，所以事实是 `setPool`。
    'entrench': ([('setPool', 'standard.block',
                   ('multiply', 2, ('pool', 'standard.block', 'source')), 'source')],
                 [('setPool', 'standard.block',
                   ('multiply', 2, ('pool', 'standard.block', 'source')), 'source')]),
    # 没有数字的牌：纯关键字/状态牌。'''),
])
print('ok §233 re-applied')
