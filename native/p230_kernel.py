"""§230 (part 1): `node.dealDamageWithTagBonus` —— "每张带这个 tag 的牌加一点伤害"。

`Perfected Strike`：`Deal 6 damage. Deals (2;3) additional damage for ALL your cards containing
"Strike".` wiki 正文说得很明确：**"in your deck when this card is played"** —— 所以数的是
手牌 + 抽牌堆 + 弃牌堆（消耗掉的牌不再是"your deck"）。

为什么是**节点**而不是表达式：

* "这张牌带不带 `strike` tag"要读**内容**（`Content::card_has_tag`），而 `ExprContext` 里没有内容
  —— 它这一层一直只拿 `&CombatState`（§225 把卡牌 tag 压成 `event_flags` 位，那是"一次事件的事
  实"，数不了整副牌）；
* 而"整片牌区里有几张带某个 tag 的牌"正是节点层已经在做的事（`forEachCardInZone` 的 `TagFilter`
  就在这一层读内容）。所以按本项目的惯例：**加一个具体节点，别开一套谓词语言**。
"""
import io

IR = 'kernel/rd-core/src/ir.rs'
EXEC = 'kernel/rd-core/src/exec.rs'


def rewrite(path, edits):
    src = io.open(path, encoding='utf-8').read()
    for old, new in edits:
        assert src.count(old) == 1, (path, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)


rewrite(IR, [
    ('''    /// `node.addCardCounter` —— 给**一份副本**的 mark counter 加一个增量（§229，`Rampage`）。''',
     '''    /// `node.dealDamageWithTagBonus` —— **基础伤害 + 每张带某个 tag 的牌一份加成**（§230）。
    ///
    /// `Perfected Strike`：`Deal 6 damage. Deals (2;3) additional damage for ALL your cards containing
    /// "Strike".`（wiki 正文：**in your deck when this card is played**）
    /// ⇒ `Amount + Bonus × (手牌 + 抽牌堆 + 弃牌堆里带该 tag 的牌数)`。
    ///
    /// 为什么不是表达式：查 tag 要读**内容**，而 `ExprContext` 只拿 `&CombatState`；"整片牌区里有几张"
    /// 是节点层已经在做的事（`forEachCardInZone` 的 `TagFilter` 就在这一层读内容）。
    DealDamageWithTagBonus,
    /// `node.addCardCounter` —— 给**一份副本**的 mark counter 加一个增量（§229，`Rampage`）。'''),
    ('''            NodeKind::AddCardCounter => "node.addCardCounter",''',
     '''            NodeKind::DealDamageWithTagBonus => "node.dealDamageWithTagBonus",
            NodeKind::AddCardCounter => "node.addCardCounter",'''),
    ('''        const ALL: [NodeKind; 26] = [''', '''        const ALL: [NodeKind; 27] = ['''),
    ('''            // §229：给这份副本加一个计数器（Rampage）。
            NodeKind::AddCardCounter,''',
     '''            // §229：给这份副本加一个计数器（Rampage）。
            NodeKind::AddCardCounter,
            // §230：按"带某个 tag 的牌数"加伤的伤害（Perfected Strike）。
            NodeKind::DealDamageWithTagBonus,'''),
])

rewrite(EXEC, [
    ('''        // §229：`addCardCounter`（给这份副本加计数器）。同上。
        | NodeKind::AddCardCounter''',
     '''        // §229：`addCardCounter`（给这份副本加计数器）。同上。
        | NodeKind::AddCardCounter
        // §230：`dealDamageWithTagBonus`（数牌 + 打伤害）。同上。
        | NodeKind::DealDamageWithTagBonus'''),
    ('''        NodeKind::AddCardCounter => add_card_counter_node(node, ctx, frame, slot, stats),''',
     '''        NodeKind::AddCardCounter => add_card_counter_node(node, ctx, frame, slot, stats),
        NodeKind::DealDamageWithTagBonus => {
            deal_damage_with_tag_bonus_node(node, ctx, frame, slot, stats)
        }'''),
])

src = io.open(EXEC, encoding='utf-8').read()
anchor = '''/// §229：`node.addCardCounter` 的实体'''
assert src.count(anchor) == 1
impl = '''/// §230：`node.dealDamageWithTagBonus` 的实体 —— `Amount + Bonus × 带该 tag 的牌数`。
///
/// 数牌的范围是**手牌 + 抽牌堆 + 弃牌堆**，正好是 wiki 正文说的 "your deck when this card is played"
/// （消耗/放逐/暂存里的牌不再是"你的牌组"）。正在结算的那张牌**仍在手牌里**（参考的落区在
/// `onTerminal`，§225），所以它自己也数进去 —— 与 wiki 的 "increases not only the damage of other
/// copies, but also of itself" 一致，不需要为它开特例。
///
/// 没有内容 ⇒ **响亮失败**（`Missing("content")`）：没有内容就查不了 tag，而"数到 0 张"会让这张牌
/// 安静地只打基础伤害 —— 那正是"工具报成功、被测对象在失败"的形状。
fn deal_damage_with_tag_bonus_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let base = eval_amount(node, "Amount", ctx)?;
    let bonus = eval_amount(node, "Bonus", ctx)?;
    let tag = node.str_field("Tag")?.ok_or(IrError::Missing("Tag"))?;
    let ignores_block = node.bool_field("IgnoresBlock")?.unwrap_or(false);
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let source = ctx.source;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    let Some(owner) = targets.first().copied().filter(|_| count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };

    let mut tagged = 0i32;
    for zone in [CardZone::Hand, CardZone::DrawPile, CardZone::DiscardPile] {
        for card in ctx.state.zone_cards(&owner, zone) {
            if content
                .card_has_tag(card.definition_id.as_str(), tag)
                .unwrap_or(false)
            {
                tagged = tagged.saturating_add(1);
            }
        }
    }
    let amount = base.saturating_add(bonus.saturating_mul(tagged));
    for target in targets.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::DealDamage {
                target: Some(*target),
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

''' + anchor
io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src.replace(anchor, impl))
print('ok kernel')
