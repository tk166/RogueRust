"""§229 (part 1): `Rampage` 需要的两件内核能力（每份副本的计数器）。

* `ExprContext::resolving_card` —— 表达式上下文第一次能看见"正在结算的那张牌"（§226 只用它置了
  一个 `event_flags` 位；这次要**读一个整数**，位图不够用）。
* `card.counter { CounterId }` —— 这张牌（正在结算的那份副本）的 mark counter 当前值。
* `cardInstance.resolving` —— 卡实例表达式里的"正在结算的那张"，与 `cardInstance.iterated` 并列。
* `node.addCardCounter { CardExpression, OwnerSelector, CounterId, Delta }` —— 给那份副本加一个计数器。

为什么必须是**每份副本**：`Rampage` 的原文是 "Increase **this card's** damage"。挂在战斗员身上的
计数器会让牌组里的三张 Rampage 共享同一份加成 —— 那不是"这张牌变强了"，是"这张牌定义变强了"，
一个可观察的语义错（打 A 之后 B 也变强）。
"""
import io
import re

EXPR = 'kernel/rd-core/src/expr.rs'
EXEC = 'kernel/rd-core/src/exec.rs'
PLAY = 'kernel/rd-core/src/play.rs'
IR = 'kernel/rd-core/src/ir.rs'


def rewrite(path, edits, count=None):
    src = io.open(path, encoding='utf-8').read()
    for old, new, *rest in edits:
        want = rest[0] if rest else 1
        assert src.count(old) == want, (path, src.count(old), want, old[:60])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)


# ── 1) ExprContext 多一个槽 ──────────────────────────────────────────────────
src = io.open(EXPR, encoding='utf-8').read()
old = '''    pub event_amount: Option<i32>,
    /// **X 费牌的 X**（§146）：这一次出牌真的花掉了多少能量。'''
new = '''    pub event_amount: Option<i32>,

    /// §229：**正在结算的那张牌**（出牌时由 `play.rs` 填；`card.counter` 读它）。
    ///
    /// §226 只把"是不是这一张"压成了一个 `event_flags` 位（`card.isResolving`）；`Rampage` 要读
    /// 一个**整数**（这份副本已经涨了多少），位图不够用，所以这里第一次把槽本身交给表达式层。
    ///
    /// 没有它时（状态/遗物/敌人招式的节目）是 `None` —— 读它的两种表达式各自**响亮**处理，
    /// 不许静默给 0：`cardInstance.resolving` 报 `NoTarget`，`card.counter` 也报 `NoTarget`。
    pub resolving_card: Option<CardSlot>,

    /// X 费牌的 X（§146）：这一次出牌真的花掉了多少能量。'''
assert src.count(old) == 1
src = src.replace(old, new)

# 所有 ExprContext 字面量补一行（expr.rs 里 `iteration_card:` 只出现在字面量里）
lines = src.split('\n')
out = []
filled = 0
for line in lines:
    out.append(line)
    stripped = line.strip()
    if stripped.startswith('iteration_card:'):
        indent = line[: len(line) - len(line.lstrip())]
        out.append(indent + 'resolving_card: None,')
        filled += 1
src = '\n'.join(out)
assert filled == 11, filled

# 词表
old = '''    "x.cost",
];'''
new = '''    "x.cost",
    // §229：正在结算的那份副本的 mark counter（`Rampage` 的 "increase **this card's** damage"）。
    "card.counter",
];'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''const CARD_KINDS: &[&str] = &["cardInstance.iterated"];'''
new = '''const CARD_KINDS: &[&str] = &[
    "cardInstance.iterated",
    // §229: the card whose program is running -- the pair of §226's `card.isResolving` bit, but as a
    // **value** instead of a fact (a counter write needs the instance, not the yes/no).
    "cardInstance.resolving",
];'''
assert src.count(old) == 1
src = src.replace(old, new)
io.open(EXPR, 'w', encoding='utf-8', newline='\n').write(src)

# ── 2) 两个新表达式的求值 ────────────────────────────────────────────────────
rewrite(EXPR, [
    ('''        "x.cost" => Ok(ctx.x_cost),''',
     '''        "x.cost" => Ok(ctx.x_cost),

        // §229: the mark counter of **this copy**. Absent counter ⇒ `0` (an unbuffed card is not an
        // error); no resolving card ⇒ `NoTarget` (`Rampage` outside a card program is a content bug,
        // and "0 bonus damage" would hide it).
        "card.counter" => {
            let key = node.str_field("CounterId")?.ok_or(IrError::Missing("CounterId"))?;
            let slot = ctx.resolving_card.ok_or(ExprError::NoTarget)?;
            let card = ctx.state.card(slot).ok_or(ExprError::NoTarget)?;
            let wanted = crate::state::CounterId::new(key).map_err(|_| ExprError::NoTarget)?;
            for counter in card.mark_counters() {
                if counter.key == wanted {
                    return Ok(counter.value);
                }
            }
            Ok(0)
        }'''),
    ('''        "cardInstance.iterated" => ctx.iteration_card.ok_or(ExprError::NoTarget),''',
     '''        "cardInstance.iterated" => ctx.iteration_card.ok_or(ExprError::NoTarget),

        // §229: "the card being resolved". Separate from `iterated` on purpose -- inside a
        // `forEachCardInZone` over the hand both exist and they are **different** cards (§226).
        "cardInstance.resolving" => ctx.resolving_card.map_or(Err(ExprError::NoTarget), |slot| {
            ctx.state.card(slot).map(|card| card.id).ok_or(ExprError::NoTarget)
        }),'''),
])

# ── 3) exec 的上下文搬运 + 新节点 ────────────────────────────────────────────
rewrite(EXEC, [
    ('''            iteration_card: self.iteration_card,
            event_flags: self.event_flags,''',
     '''            iteration_card: self.iteration_card,
            resolving_card: self.resolving_card,
            event_flags: self.event_flags,'''),
])
src = io.open(EXEC, encoding='utf-8').read()
old = '''        // §228：`dealDamageToRandomTarget`（抽签 + 打伤害）。同上。
        | NodeKind::DealDamageToRandomTarget'''
new = '''        // §228：`dealDamageToRandomTarget`（抽签 + 打伤害）。同上。
        | NodeKind::DealDamageToRandomTarget
        // §229：`addCardCounter`（给这份副本加计数器）。同上。
        | NodeKind::AddCardCounter'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''        NodeKind::DealDamageToRandomTarget => {'''
new = '''        NodeKind::AddCardCounter => add_card_counter_node(node, ctx, frame, slot, stats),
        NodeKind::DealDamageToRandomTarget => {'''
assert src.count(old) == 1
src = src.replace(old, new)

anchor = '''/// §228：`node.dealDamageToRandomTarget` 的实体'''
assert src.count(anchor) == 1
impl = '''/// §229：`node.addCardCounter` 的实体 —— 给**一份副本**的某个 mark counter 加一个增量。
///
/// `{CardExpression, OwnerSelector, CounterId, Delta}`。`CardExpression` 通常是
/// `cardInstance.resolving`（"这张牌自己变强"），也可以是 `cardInstance.iterated`。
///
/// 三条纪律：
/// * 计数器**不存在**时按 0 起算（`set_mark_counter` 是字典语义）；
/// * `Delta` 是**相对**量 —— 绝对值写 0 会把"已经涨过"抹掉，那种 bug 只在第二张以后才看得出来；
/// * 计数器表满了 ⇒ `set_mark_counter` 自己报 `Capacity`（§161.4 那条预校验的反面：这里没有
///   "先搬后写"的顺序问题，写入失败就是整体失败）。
fn add_card_counter_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let card_expression = node
        .node_field("CardExpression")?
        .ok_or(IrError::Missing("CardExpression"))?;
    let counter = node.str_field("CounterId")?.ok_or(IrError::Missing("CounterId"))?;
    let delta = eval_amount(node, "Delta", ctx)?;
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    let card_id = {
        let expr_ctx = ctx.expr_context();
        expr::eval_card(card_expression, &expr_ctx)?
    };
    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let owner_count = resolve_targets(owner_selector, ctx, &mut owners)?;
    let Some(owner) = owners.first().copied().filter(|_| owner_count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };
    let Some((_, card_slot)) = ctx.state.find_card(&owner, &card_id) else {
        return Err(ExecError::Ir(IrError::Missing("CardExpression")));
    };
    let key = crate::state::CounterId::new(counter).map_err(|_| IrError::Missing("CounterId"))?;
    let current = ctx
        .state
        .card(card_slot)
        .and_then(|card| {
            card.mark_counters()
                .iter()
                .find(|entry| entry.key == key)
                .map(|entry| entry.value)
        })
        .unwrap_or(0);
    if let Some(card) = ctx.state.card_mut(card_slot) {
        card.set_mark_counter(key, current.saturating_add(delta))?;
    }
    resume_later(ctx.state, frame, slot)
}

''' + anchor
src = src.replace(anchor, impl)
io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)

# ── 4) ir 词表 ───────────────────────────────────────────────────────────────
rewrite(IR, [
    ('''    /// `node.dealDamageToRandomTarget` —— **每次命中从候选池里随机挑一个目标**（§228）。''',
     '''    /// `node.addCardCounter` —— 给**一份副本**的 mark counter 加一个增量（§229，`Rampage`）。
    ///
    /// 参考引擎里 `Rampage` 涨的是 `CardInstance.misc` 这类**每副本**数据；本内核里每副本数据的
    /// 唯一载体就是 mark counter（每副本价格 `standard.card_cost_delta` 已经在用）。所以这个节点
    /// 是"这张牌记住了一件事"的一般形态，而不是给 Rampage 写的特例。
    AddCardCounter,
    /// `node.dealDamageToRandomTarget` —— **每次命中从候选池里随机挑一个目标**（§228）。'''),
    ('''            NodeKind::DealDamageToRandomTarget => "node.dealDamageToRandomTarget",''',
     '''            NodeKind::AddCardCounter => "node.addCardCounter",
            NodeKind::DealDamageToRandomTarget => "node.dealDamageToRandomTarget",'''),
    ('''        const ALL: [NodeKind; 25] = [''', '''        const ALL: [NodeKind; 26] = ['''),
    ('''            // §228：每次命中随机挑一个目标（Sword Boomerang）。
            NodeKind::DealDamageToRandomTarget,''',
     '''            // §228：每次命中随机挑一个目标（Sword Boomerang）。
            NodeKind::DealDamageToRandomTarget,
            // §229：给这份副本加一个计数器（Rampage）。
            NodeKind::AddCardCounter,'''),
])

# ── 5) play.rs 的那个字面量 ──────────────────────────────────────────────────
rewrite(PLAY, [
    ('''        iteration_target: None,
        iteration_card: None,''',
     '''        iteration_target: None,
        iteration_card: None,
        resolving_card: None,'''),
])
print('ok kernel')
