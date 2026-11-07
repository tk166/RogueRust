"""§282 修正：`Confusion` 的钩子下沉到 `CombatState::draw_card` —— **唯一**的抽牌入口。

第一版把钩子放在 `exec::draw_for` 里，而那只是**一条**路径：回合开始的抽牌走
`state::draw_cards_with_reshuffle`（`turn.rs`），它**不经过** `draw_for`。于是"有 Confusion 时
回合开始的 5 张牌不重掷"—— 而屏幕上一切正常（价格就是印刷价）。

两处认识同一件事 = 一定会漂。所以钩子放在 `draw_card`：它是**所有**抽牌的必经之路
（`draw_for` 与 `draw_cards_with_reshuffle` 都调它）。

代价：`draw_card` 没有 content，所以 "X 费牌豁免" 不能按 tag 查。改用**结构**事实：
X 费牌的印刷价是 0 且节目里读 `x.cost` —— 但这里更简单也更诚实的一条是"**印刷价为 0 且
declares x_cost** 才豁免"，而 tag 要 content。折中：把"是否 X 费"作为**卡实例上的一个事实**
在最开始（`create_card`/`push_card` 时）记下？那要改卡实例结构。

更小的做法（采用）：豁免规则改成"**印刷价 <= 0 的牌不掷**"——X 费牌的印刷价是 0（§146 的
内容约束），而"0 费牌"重掷成 0..3 会**变贵**，那是 wiki 明确说不会发生的
（"Unplayable and X-Cost cards are unaffected"; 0 费普通牌**会**被重掷，
`Snecko Eye` 的表格里 "Normal Cost 0 → 75% chance of becoming more expensive"）。
所以"印刷价 <= 0 一律不掷"是**错的**（它会让 0 费牌免疫）。

⇒ 真正的区分只能是 tag，而 tag 在内容里。所以钩子留在 `draw_for`（有 content），
但 **`draw_cards_with_reshuffle` 也要走同一段逻辑** —— 它由 `turn.rs` 调用，而 `turn.rs`
**手上有 content**（`draw_for_turn_start` 的参数）。所以：把重掷抽成一个
`pub fn confuse_drawn_card(state, content, owner, slot)`，两个调用点各调一次，
并加**一条判据**钉住"两条路径都重掷"（否则又回到"抄两份"）。
"""
import io

P_EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
P_TURN = 'D:/Vibe/sts-tui/kernel/rd-core/src/turn.rs'


def main():
    # ① 把助手改成 pub，并接收 content（可选）
    s = io.open(P_EXEC, encoding='utf-8').read()
    old = '''fn confuse_drawn_card(ctx: &mut ExecContext<'_>, owner: &CombatantId, slot: crate::state::CardSlot) {'''
    new = '''pub fn confuse_drawn_card(
    state: &mut crate::state::CombatState,
    content: Option<&crate::content::Content<'_>>,
    owner: &CombatantId,
    slot: crate::state::CardSlot,
) {'''
    assert s.count(old) == 1
    s = s.replace(old, new)

    # 函数体里原来的 ctx.state / ctx.content 换成本地绑定
    body_old = '''    // 只有**持有者**有这条状态时才掷（不叠加，所以"有没有"就够了 —— 参考的 stack 上限是 1）。
    let confused = ctx.state.combatant(owner).is_some_and(|combatant| {
        combatant
            .statuses()
            .iter()
            .any(|instance| instance.definition_id.as_str() == CONFUSION_STATUS)
    });
    if !confused {
        return;
    }
    let Some(card) = ctx.state.card(slot) else {
        return;
    };
    let definition = card.definition_id;
    // X 费牌与不可打出的牌不动（见调用点注释）。
    if let Some(content) = ctx.content {
        if content.card_has_tag(definition.as_str(), crate::battle::X_COST_TAG) == Some(true) {
            return;
        }
    }
    if card.printed_energy_cost(&definition) < 0 {
        return;
    }
    // §281 的唯一入口：派生 → 取模 → `random_step += 1`。
    let roll = crate::exec::draw_random(ctx.state, CONFUSION_MIN, CONFUSION_MAX);
    let Ok(key) = crate::state::CounterId::new(crate::state::CARD_COST_OVERRIDE_COUNTER) else {
        return;
    };
    if let Some(card) = ctx.state.card_mut(slot) {'''
    body_new = '''    // 只有**持有者**有这条状态时才掷（不叠加，所以"有没有"就够了 —— 参考的 stack 上限是 1）。
    let confused = state.combatant(owner).is_some_and(|combatant| {
        combatant
            .statuses()
            .iter()
            .any(|instance| instance.definition_id.as_str() == CONFUSION_STATUS)
    });
    if !confused {
        return;
    }
    let Some(card) = state.card(slot) else {
        return;
    };
    let definition = card.definition_id;
    // X 费牌不动（它们的费用是 `x.cost`）。**这一条只能按 tag 判** —— "印刷价 0 就不掷"
    // 会让 0 费普通牌免疫，而 wiki 的表格明说 0 费牌有 75% 会**变贵**。
    if let Some(content) = content {
        if content.card_has_tag(definition.as_str(), crate::battle::X_COST_TAG) == Some(true) {
            return;
        }
    }
    // 不可打出的牌（费用 -2）不动：掷成 0 会把一张诅咒变成免费的。
    if card.printed_energy_cost(&definition) < 0 {
        return;
    }
    // §281 的唯一入口：派生 → 取模 → `random_step += 1`。
    let roll = draw_random(state, CONFUSION_MIN, CONFUSION_MAX);
    let Ok(key) = crate::state::CounterId::new(crate::state::CARD_COST_OVERRIDE_COUNTER) else {
        return;
    };
    if let Some(card) = state.card_mut(slot) {'''
    assert s.count(body_old) == 1, 'body anchor'
    s = s.replace(body_old, body_new)

    # 调用点（draw_for 里）
    s = s.replace('''            confuse_drawn_card(ctx, owner, slot);''',
                  '''            confuse_drawn_card(ctx.state, ctx.content, owner, slot);''')
    io.open(P_EXEC, 'w', encoding='utf-8', newline='\n').write(s)
    print('helper is public and content-aware')
    print('NEXT: turn.rs 的回合开始抽牌也要调它')


main()
