"""§282（重做）：把 Confusion 的钩子写成 `pub fn confuse_drawn_card`，并挂到**两条**抽牌路径。

背景（第一版为什么不够）：抽牌有**两条**路径 ——
  * `exec::draw_for`（`node.drawCards` / 药水的 `DrawCards` 请求）；
  * `state::draw_cards_with_reshuffle`（回合开始的 5 张，`turn.rs::draw_for_turn_start`）。
只在第一处装钩子 ⇒ "有 Confusion 时回合开始那 5 张不重掷"，而屏幕上一切正常。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'

HELPER = '''/// §282：`Confusion` 的重掷 —— 抽到的那一张，费用变成 `draw_in_range(0, 3)`。
///
/// **两个调用点**（抽牌有两条路，见 `draw_for` 与 `turn::draw_for_turn_start`）：
/// 抄两份必然漂，所以它是 `pub`。
///
/// 三个"不做"与 wiki 逐条对应：
/// * **X 费牌不动**（费用是 `x.cost`，掷了没人读）。只能按 **tag** 判 —— "印刷价 0 就不掷"
///   会让 0 费普通牌免疫，而 wiki 的表格明说 0 费牌有 75% 会**变贵**；
/// * **不可打出的牌不动**（印刷价 -2，掷成 0 会把诅咒变成免费的）；
/// * 重掷是**绝对覆盖**（`CARD_COST_OVERRIDE_COUNTER`），会盖掉此前一切费用改动
///   （wiki: "Overwrite the current cost of Blood for Blood …"）。
pub fn confuse_drawn_card(
    state: &mut crate::state::CombatState,
    content: Option<&crate::content::Content<'_>>,
    owner: &CombatantId,
    slot: crate::state::CardSlot,
) {
    // 只有**持有者**有这条状态时才掷（不叠加，所以"有没有"就够了 —— 参考的 stack 上限是 1）。
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
    if let Some(content) = content {
        if content.card_has_tag(definition.as_str(), crate::battle::X_COST_TAG) == Some(true) {
            return;
        }
    }
    if card.printed_energy_cost(&definition) < 0 {
        return;
    }
    // §281 的唯一入口：派生 → 取模 → `random_step += 1`。
    let roll = draw_random(state, CONFUSION_MIN, CONFUSION_MAX);
    let Ok(key) = crate::state::CounterId::new(crate::state::CARD_COST_OVERRIDE_COUNTER) else {
        return;
    };
    if let Some(card) = state.card_mut(slot) {
        // 装不下就是容量问题（每副本的计数器表很小）。**静默失败**会让这张牌按印刷价出牌 ——
        // 那正是"屏幕说 0 费、内核收 2"的形态，所以交给"显示 = 实收"那几条判据去红。
        let _ = card.set_mark_counter(key, roll);
    }
}

'''


def main():
    s = io.open(P, encoding='utf-8').read()

    # ① 助手插在 `fn draw_for(` 之前
    anchor = '''fn draw_for(
    ctx: &mut ExecContext<'_>,'''
    assert s.count(anchor) == 1
    s = s.replace(anchor, HELPER + anchor)

    # ② 调用点：draw_for 里抽到之后（`Drawn` 节目之前）
    hook_anchor = '''            // §220：抽到了 ⇒ 跑它的 `Drawn` 节目（没有节目就什么都不做，链号也不动）。'''
    assert s.count(hook_anchor) == 1
    s = s.replace(hook_anchor, '''            // §282：`Confusion` —— "Whenever you draw a card, randomize its cost"（wiki）。
            // 放在 `Drawn` 节目**之前**：那张牌的节目读到的是"这次抽到的价"。
            confuse_drawn_card(ctx.state, ctx.content, owner, slot);
''' + hook_anchor)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('helper + draw_for hook')
    print('NEXT: turn.rs')


main()
