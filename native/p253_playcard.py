"""§253 内核（1/2）：`node.playCard` —— 让"由别的牌把它打出来"这条通道存在。

## 参考的形状（`EffectProgramContracts.cs:527-536`）

```
IPlayCardNodeCore:
  PlayerSelector        : ICombatantTargetSelector
  CardExpression        : CardInstanceId?   (求值出要打的那一份实例)
  CardTargetSelector?   : ICombatantTargetSelector  (可选：给它指定目标)
  ResultKey?            : (本内核不支持 ResultKey，见 `reject_result_key`)
```

处理器（`Cards/PlayCardEffects.cs:21-96`）走**完整出牌管线**，但在四种情况下 **no-op（不抛）**：
玩家不在/倒了、那一份不在主人牌区、**不在手牌**、**付不起费用**、以及
**卡带 `unplayable` tag**（`:54-58` 那条注释写得很明白："An unplayable card (a curse) is never
played — no-op it like an unaffordable card"）。

## 我们为什么要多一个 `IgnoreUnplayable`

StS 的 `Wish` 是"选一张，**这张牌被打出**"，而它的三个选项
（`Become Almighty` / `Live Forever` / `Fame and Fortune`）**都是 unplayable** —— 玩家在手上打不出，
`Wish` 却能打出它们。所以"照抄参考的 no-op"会让 `Wish` 这件事根本表达不出来。

⇒ 加一个**显式**的 `IgnoreUnplayable`（默认 `false`：与参考逐字相同）。这不是偷偷发明规则：
它的理由写在 wiki 的 `Wish`/`Become Almighty` 正文里（"It can only be obtained and **played**
through Watcher's Wish"），而且**默认值保持参考行为**，只有明确写 `true` 的内容才越过那道门。

⚠️ 越过的是**只有** `unplayable` 这一道。`stun`/法令/`PlayCondition` 仍然照旧 —— 那些是
"这一回合不许出牌"，与"这张牌天生不可打出"不是一回事；`Wish` 的语义只推翻后者。
"""
import io

IR = 'D:/Vibe/sts-tui/kernel/rd-core/src/ir.rs'
EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'

IR_PATCH = (
    '''    /// §250：**问玩家三选一：从"职业牌池"里随机取 N 张**（`Discovery`）。''',
    '''    /// §253：**由别的牌把一张牌打出来**（`Wish` 的三个选项；参考的 `node.playCard`）。
    ///
    /// 字段：`{PlayerSelector, CardExpression, CardTargetSelector?, IgnoreUnplayable?}`。
    ///
    /// 与 `node.playTopCardOfDrawPile`（`Havoc`）的区别：那个"从抽牌堆顶拿一张、强制 Exhaust"，
    /// 这个"把**指定的**那一份按它自己的落区打出去"。两者共用底层的 `play_card` 管线，
    /// 所以费用、事件、触发器、修饰器都只有一份实现。
    ///
    /// `IgnoreUnplayable` 是本内核多出来的一格，理由写在 `play.rs::play_card_from_program`：
    /// StS 的 `Wish` **会**打出 `unplayable` 的牌，而参考的 `playCard` 对它是 no-op。
    /// 默认 `false` ⇒ 与参考逐字相同。
    PlayCard,
    /// §250：**问玩家三选一：从"职业牌池"里随机取 N 张**（`Discovery`）。''')

IR_WIRE = (
    '''            NodeKind::GainGold => "node.gainGold",''',
    '''            NodeKind::GainGold => "node.gainGold",
            NodeKind::PlayCard => "node.playCard",''')

IR_LIST = (
    '''            NodeKind::GainGold,
            NodeKind::CreateCardCopy,''',
    '''            NodeKind::GainGold,
            NodeKind::PlayCard,
            NodeKind::CreateCardCopy,''')

EXEC_DISPATCH = (
    '''        NodeKind::GainGold => gain_gold_node(node, ctx, frame, slot, stats),''',
    '''        NodeKind::GainGold => gain_gold_node(node, ctx, frame, slot, stats),
        NodeKind::PlayCard => play_card_node(node, ctx, frame, slot, stats),''')

EXEC_CHILDLESS = (
    '''        | NodeKind::GainGold
        | NodeKind::CreateCardCopy''',
    '''        | NodeKind::GainGold
        | NodeKind::PlayCard
        | NodeKind::CreateCardCopy''')

IMPLEMENTATION = r'''
/// §253：`node.playCard` 的实体 —— `{PlayerSelector, CardExpression, CardTargetSelector?,
/// IgnoreUnplayable?}`。
///
/// 它**不自己实现出牌**：把"哪一份、谁打、打谁、要不要越过 `unplayable`"整理成一个请求，
/// 剩下的交给 [`crate::play::play_card_from_program`] —— 费用、事件、触发器、修饰器因此
/// 只有一份实现（与 `Havoc` 的 `play_top_card_for` 同一层）。
fn play_card_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let player_selector = node
        .node_field("PlayerSelector")?
        .ok_or(IrError::Missing("PlayerSelector"))?;
    let mut players = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(player_selector, ctx, &mut players)?;
    let Some(player) = players.first().copied().filter(|player| count > 0) else {
        // 参考：`TryGetCombatant` 失败 ⇒ no-op（`PlayCardEffects.cs:33-37`）。
        return resume_later(ctx.state, frame, slot);
    };
    let card_expression = node
        .node_field("CardExpression")?
        .ok_or(IrError::Missing("CardExpression"))?;
    let card = {
        let expr_ctx = ctx.expr_context();
        crate::expr::eval_card(card_expression, &expr_ctx)?
    };
    let target = match node.node_field("CardTargetSelector")? {
        Some(selector) => {
            let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
            let resolved = resolve_targets(selector, ctx, &mut targets)?;
            targets.first().copied().filter(|_| resolved > 0)
        }
        None => None,
    };
    let ignore_unplayable = node.bool_field("IgnoreUnplayable")?.unwrap_or(false);
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };
    // 四种"跳过"由 `play_card_from_program` 自己判定并返回 `Ok(false)`（参考全是 no-op，
    // 不是错误）—— 只有"内容坏了"才走 `Err`。
    crate::play::play_card_from_program(
        ctx.state,
        content,
        &player,
        &card,
        target,
        ignore_unplayable,
    )?;
    resume_later(ctx.state, frame, slot)
}

'''


def patch(path, pairs, label):
    src = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert src.count(old) == 1, (label, old[:60], src.count(old))
        src = src.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print('patched', label)


def main():
    patch(IR, [IR_PATCH, IR_WIRE, IR_LIST], 'ir.rs')
    # `ALL` 的长度也要 +1
    src = io.open(IR, encoding='utf-8').read()
    old = '        const ALL: [NodeKind; 39] = ['
    assert src.count(old) == 1
    io.open(IR, 'w', encoding='utf-8', newline='\n').write(
        src.replace(old, '        const ALL: [NodeKind; 40] = ['))
    print('ir.rs: ALL -> 40')

    src = io.open(EXEC, encoding='utf-8').read()
    for old, new in [EXEC_DISPATCH, EXEC_CHILDLESS]:
        assert src.count(old) == 1, (old[:60], src.count(old))
        src = src.replace(old, new)
    anchor = '/// §250：`node.gainGold` 的实体 —— `{Amount}`。'
    assert src.count(anchor) == 1
    src = src.replace(anchor, IMPLEMENTATION.lstrip('\n') + anchor)
    io.open(EXEC, 'w', encoding='utf-8', newline='\n').write(src)
    print('exec.rs: dispatch + childless list + implementation')


main()
