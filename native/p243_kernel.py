"""§243 内核：无色 A 档要的两个小载体。

1. `node.shuffleDiscardIntoDraw` —— `Deep Breath`："Shuffle your discard pile into your draw
   pile, then draw". 内核里"重洗"只发生在**抽牌抽空**那条路上（`draw_for`），而 Deep Breath
   要的是**无条件重洗一次**再抽 —— 顺序是语义（重洗后抽到的可能是刚洗回去的牌）。
2. `hand.hasCardWithTag` —— `Impatience`："If you have no Attacks in your hand".
   §242 把 `Content` 放进 `ExprContext`（按值）之后，这种"按 tag 数手牌"的表达式
   才**做得出来**：卡牌 tag 在 CARD 表里，`CombatState` 不拥有内容。
"""
import io

K = 'D:/Vibe/sts-tui/kernel/rd-core/src/'


def patch(name, pairs):
    path = K + name
    s = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70], s.count(old))
        s = s.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('patched', name)


# ------------------------------------------------------------------ state.rs：请求变体
patch('state.rs', [
    ('''    /// §241：**强制打出抽牌堆顶那张，然后把它消耗掉**（`Havoc`）。''',
     '''    /// §243：**把弃牌堆洗回抽牌堆**（`Deep Breath`）。
    ///
    /// 为什么是请求而不是节点里直接做：它必须**排在后面的抽牌之前**落地（`sequence` 是
    /// "先派发完、再按队列顺序解析"，所以入队顺序就是语义）。
    ShuffleDiscardIntoDraw {
        /// 洗谁的牌。
        owner: CombatantId,
    },
    /// §241：**强制打出抽牌堆顶那张，然后把它消耗掉**（`Havoc`）。'''),
])

# ------------------------------------------------------------------ ir.rs：新节点
patch('ir.rs', [
    ('''    PlayTopCardOfDrawPile,''',
     '''    PlayTopCardOfDrawPile,
    /// §243：**把弃牌堆洗回抽牌堆**（`Deep Breath`）。`{OwnerSelector}`。
    ShuffleDiscardIntoDraw,'''),
    ('''        const ALL: [NodeKind; 34] = [''', '''        const ALL: [NodeKind; 35] = ['''),
    ('''            NodeKind::PlayTopCardOfDrawPile,''',
     '''            NodeKind::PlayTopCardOfDrawPile,
            NodeKind::ShuffleDiscardIntoDraw,'''),
    ('''            NodeKind::PlayTopCardOfDrawPile => "node.playTopCardOfDrawPile",''',
     '''            NodeKind::PlayTopCardOfDrawPile => "node.playTopCardOfDrawPile",
            NodeKind::ShuffleDiscardIntoDraw => "node.shuffleDiscardIntoDraw",'''),
])

# ------------------------------------------------------------------ exec.rs：节点 + 解析 + 三处穷尽 match
s = io.open(K + 'exec.rs', encoding='utf-8').read()
s = s.replace('''        // §241：`playTopCardOfDrawPile`（把抽牌堆顶打出去）。无孩子。
        | NodeKind::PlayTopCardOfDrawPile''',
'''        // §241：`playTopCardOfDrawPile`（把抽牌堆顶打出去）。无孩子。
        | NodeKind::PlayTopCardOfDrawPile
        // §243：`shuffleDiscardIntoDraw`（把弃牌堆洗回去）。无孩子。
        | NodeKind::ShuffleDiscardIntoDraw''', 1)

s = s.replace('''        NodeKind::PlayTopCardOfDrawPile => {
            play_top_card_of_draw_pile_node(node, ctx, frame, slot, stats)
        }''',
'''        NodeKind::PlayTopCardOfDrawPile => {
            play_top_card_of_draw_pile_node(node, ctx, frame, slot, stats)
        }
        NodeKind::ShuffleDiscardIntoDraw => {
            shuffle_discard_into_draw_node(node, ctx, frame, slot, stats)
        }''', 1)

s = s.replace('''            | EffectRequest::PlayTopCardOfDrawPile { .. }
            | EffectRequest::MoveCardToZone { .. }''',
'''            | EffectRequest::PlayTopCardOfDrawPile { .. }
            | EffectRequest::ShuffleDiscardIntoDraw { .. }
            | EffectRequest::MoveCardToZone { .. }''', 1)
s = s.replace('''        | EffectRequest::PlayTopCardOfDrawPile { .. }
        | EffectRequest::MoveCardToZone { .. }''',
'''        | EffectRequest::PlayTopCardOfDrawPile { .. }
        | EffectRequest::ShuffleDiscardIntoDraw { .. }
        | EffectRequest::MoveCardToZone { .. }''', 1)
s = s.replace('''        EffectRequest::PlayTopCardOfDrawPile { owner } => play_top_card_for(ctx, &owner),''',
'''        EffectRequest::PlayTopCardOfDrawPile { owner } => play_top_card_for(ctx, &owner),
        EffectRequest::ShuffleDiscardIntoDraw { owner } => {
            // 重洗 0 张不是错误（弃牌堆空 ⇒ 什么都不做，`reshuffle_discard_into_draw` 自己返回 0）。
            ctx.state
                .reshuffle_discard_into_draw(&owner)
                .map_err(ExecError::Capacity)?;
            Ok(())
        }''', 1)
io.open(K + 'exec.rs', 'w', encoding='utf-8', newline='\n').write(s)
print('patched exec.rs (matches + resolve)')

# 节点实体，插在 playTopCard 实体之前
s = io.open(K + 'exec.rs', encoding='utf-8').read()
anchor = '/// §241：`node.playTopCardOfDrawPile` —— 零字段，一条请求。'
assert s.count(anchor) == 1
NODE = '''/// §243：`node.shuffleDiscardIntoDraw` —— `{OwnerSelector}`，一条请求。
///
/// 只入队不直接洗：`sequence[shuffle, draw]` 靠**队列顺序**表达"先洗后抽"，
/// 在派发时就把牌洗了会让同一棵树里的抽牌请求读到一个"已经洗过"的牌堆 ——
/// 那在单测里看起来一样，但在"抽到刚洗回去的那张"这种局面里是另一个结果。
fn shuffle_discard_into_draw_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut owners)?;
    for owner in owners.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::ShuffleDiscardIntoDraw { owner: *owner },
            Some(frame),
        )?;
    }
    resume_later(ctx.state, frame, slot)
}

'''
s = s[:s.index(anchor)] + NODE + s[s.index(anchor):]
io.open(K + 'exec.rs', 'w', encoding='utf-8', newline='\n').write(s)
print('patched exec.rs (node)')

# ------------------------------------------------------------------ expr.rs：hand.hasCardWithTag
patch('expr.rs', [
    ('''    "intent.targetIntendsAttack",
];''',
     '''    "intent.targetIntendsAttack",
    // §243：**手牌里有没有带某个 tag 的牌**（`Impatience`："If you have no Attacks in your hand"）。
    //
    // 为什么现在才做得出来：它要读 CARD 表的 tag，而 §242 才把 `Content` 按值放进
    // `ExprContext`（`CombatState` 不拥有内容）。
    "hand.hasCardWithTag",
];'''),
    ('''        // §242: "does the chosen target intend to attack this turn" (Spot Weakness).''',
     '''        // §243: "is there a card with this tag in the hand" (Impatience).
        //
        // 三处细节都是判据钉住的：
        // * **正在结算的那张牌不算手牌**（§236 同一条洞见）—— `Impatience` 是技能，包不包含它
        //   答案一样，但"换个牌名就可能不同"，所以按**规则**跳过，而不是靠巧合；
        // * 没有内容 ⇒ 响亮失败（`UnsupportedKind`），不当成"手上没有"；
        // * 没有 `OwnerSelector` ⇒ 用 `sel.source`（牌自己的主人），这是内容用到的那一种。
        "hand.hasCardWithTag" => {
            let Some(content) = ctx.content else {
                return Err(ExprError::UnsupportedKind);
            };
            let tag = node.str_field("Tag")?.ok_or(IrError::Missing("Tag"))?;
            let owner = match node.node_field("OwnerSelector")? {
                None => ctx.source,
                Some(selector) => {
                    let mut owners = [crate::state::CombatantId::EMPTY; crate::state::MAX_COMBATANTS];
                    let count = crate::exec::resolve_targets_for_expr(selector, ctx, &mut owners)?;
                    owners.iter().take(count).next().copied()
                }
            };
            let Some(owner) = owner else {
                return Ok(false);
            };
            let resolving = ctx
                .resolving_card
                .and_then(|slot| ctx.state.card(slot))
                .map(|card| card.id);
            let mut found = false;
            for card in ctx.state.zone_cards(&owner, crate::state::CardZone::Hand) {
                if Some(card.id) == resolving {
                    continue;
                }
                if content.card_has_tag(card.definition_id.as_str(), tag) == Some(true) {
                    found = true;
                    break;
                }
            }
            Ok(found)
        }

        // §242: "does the chosen target intend to attack this turn" (Spot Weakness).'''),
])
print('done')
