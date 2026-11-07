"""§282：`Confusion`（wiki 的 *Confused*）—— **每次抽牌**把这张牌的费用重掷成 0..3。

wiki（wiki.gg `Snecko` / `Confused` / `Snecko Eye`，两处独立来源一致）：

* "Whenever you draw a card, randomize its cost." —— **四档等概率**（每个 25%），平均 1.5；
* **只有从抽牌堆抽进手牌**才重掷（`Seek` 那种"放入手牌"不算）；
* **X 费牌不受影响**（它们本来就用 `x.cost`）；
* 重掷会**覆盖**已有的费用改动 —— 正对应我们的 `CARD_COST_OVERRIDE_COUNTER`（绝对覆盖）；
* 不叠加，整场有效。

落点：`exec::draw_for` 的内层循环 —— 那是**所有**抽牌的必经之路
（`node.drawCards` 与药水的 `EffectRequest::DrawCards` 都过它），而且它手上有 content。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ① 钩子：抽到一张之后（在 `Drawn` 节目之前 —— 参考的顺序见注释）
    s = patch(s, '''            let Some(slot) = ctx.state.draw_card(owner)? else {
                break;
            };
            // §220：抽到了 ⇒ 跑它的 `Drawn` 节目（没有节目就什么都不做，链号也不动）。''',
'''            let Some(slot) = ctx.state.draw_card(owner)? else {
                break;
            };
            // §282：`Confusion`（wiki: *Confused*）—— "Whenever you draw a card, randomize its
            // cost"，四档等概率（每个 25%）。**在这里**而不是在节点里：抽牌有两个入口
            // （`node.drawCards` 与药水的 `EffectRequest::DrawCards`），而 `draw_for` 是两者
            // 共同的落点。
            //
            // 三个"不做"与 wiki 逐条对应：
            // * **X 费牌不动**（它们的费用是 `x.cost`，掷了也没人读）；
            // * 不可打出（Unplayable，费用 -2）不动 —— 掷成 0 会让一张诅咒变成免费的；
            // * 重掷是**绝对覆盖**（`CARD_COST_OVERRIDE_COUNTER`），所以它会盖掉此前的一切
            //   费用改动（wiki: "Overwrite the current cost of Blood for Blood …"）。
            confuse_drawn_card(ctx, owner, slot);
            // §220：抽到了 ⇒ 跑它的 `Drawn` 节目（没有节目就什么都不做，链号也不动）。''')

    # ② 助手
    s = patch(s, '''/// `GainResource`：`Amount` / `DefaultMax` → `TargetSelector` → **每个目标一条请求**。''',
'''/// §282：`Confusion` 的重掷 —— 抽到的那一张，费用变成 `draw_in_range(0, 3)`。
///
/// `fn` 而不是内联：这一段有四个早退条件，内联进 `draw_for` 的循环会把那个循环的
/// "抽到 / 洗牌 / 抽不满"三层结构埋掉。
fn confuse_drawn_card(ctx: &mut ExecContext<'_>, owner: &CombatantId, slot: crate::state::CardSlot) {
    // 只有**持有者**有这条状态时才掷（不叠加，所以"有没有"就够了 —— 参考的 stack 上限是 1）。
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
    if let Some(card) = ctx.state.card_mut(slot) {
        // 装不下就是容量问题（每副本的计数器表很小），而**静默失败**会让这张牌按印刷价出牌 ——
        // 那正是"屏幕说 0 费、内核收 2"的形态，所以宁可什么都不做也不留一个错数：
        // 下面的 `ACT1_SLICE` 与 §179 的判据都会在"显示 ≠ 实收"上红。
        let _ = card.set_mark_counter(key, roll);
    }
}

/// `GainResource`：`Amount` / `DefaultMax` → `TargetSelector` → **每个目标一条请求**。''')

    # ③ 常量（与 §281 的 Snecko Oil 同一个 0..3，wiki 两处都写 "0 to 3"）
    s = patch(s, '''/// `GainResource` 的 `DefaultMax`''',
'''/// §282：`Confusion` 的状态 id（wiki 的 *Confused*；`Snecko` 的 Perplexing Glare 与
/// `Snecko Eye` 都挂这一条）。
pub const CONFUSION_STATUS: &str = "standard.confusion";
/// §282：重掷范围（wiki："randomize its cost … 0 to 3"，四档**等概率**）。
pub const CONFUSION_MIN: i32 = 0;
pub const CONFUSION_MAX: i32 = 3;

/// `GainResource` 的 `DefaultMax`''')
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('Confusion draw hook')


main()
