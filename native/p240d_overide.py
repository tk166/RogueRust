"""§240 修正：用**绝对**每副本价格（`standard.card_cost_override`）表达"本回合 0 费"。

第一版拿 `-印刷费用` 的 delta 去表达它，为此还写了个 `printed_energy_cost`（把 `Costs` 列表
再读一遍）。判据当场抓到它没生效（能量掉了 1 点），而查下去发现 `play.rs` 早就有**绝对**价格这一格
—— `mark_counter_opt(instance, CARD_COST_OVERRIDE_COUNTER)` 在 delta 之前生效。用现成的那个：
既不用算印刷费用，也不用第二份 `Costs` 读者（§4.20 的"同一个词表两处认识就会漂"）。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
s = io.open(P, encoding='utf-8').read()

old = '''        let (definition, printed) = pick_random_card_of_tag(ctx, content, tag, cost_zero)?;'''
new = '''        let definition = pick_random_card_of_tag(ctx, content, tag)?;'''
assert s.count(old) == 1
s = s.replace(old, new)

old = '''        if cost_zero {
            // §161.4：每副本价格。`-印刷费用` ⇒ 本回合 0 费；出牌付款后计数器被清掉。
            if let Some(printed) = printed {
                let key = crate::state::CounterId::new(crate::state::CARD_COST_DELTA_COUNTER)?;
                let card = ctx
                    .state
                    .card_mut(slot)
                    .ok_or(ExecError::MissingCombatant)?;
                let _ = card.set_mark_counter(key, -printed);
            }
        }'''
new = '''        if cost_zero {
            // §161.4：**绝对**每副本价格（`standard.card_cost_override`）—— 它在 delta 之前生效，
            // 正是"这一份的价格就是 0"要的那一格。出牌付款后计数器被清掉（同一条承诺）。
            let key = crate::state::CounterId::new(crate::state::CARD_COST_OVERRIDE_COUNTER)?;
            let card = ctx
                .state
                .card_mut(slot)
                .ok_or(ExecError::MissingCombatant)?;
            if !card.set_mark_counter(key, 0) {
                return Err(ExecError::Capacity(crate::state::CapacityError::Full(
                    crate::state::Container::MarkCounters,
                )));
            }
        }'''
assert s.count(old) == 1
s = s.replace(old, new)

old = '''fn pick_random_card_of_tag(
    ctx: &mut ExecContext<'_>,
    content: &crate::content::Content<'_>,
    tag: &crate::state::TagId,
    want_cost: bool,
) -> Result<(Option<CardDefinitionId>, Option<i32>), ExecError> {'''
new = '''fn pick_random_card_of_tag(
    ctx: &mut ExecContext<'_>,
    content: &crate::content::Content<'_>,
    tag: &crate::state::TagId,
) -> Result<Option<CardDefinitionId>, ExecError> {'''
assert s.count(old) == 1
s = s.replace(old, new)

s = s.replace('''    if total == 0 {
        return Ok((None, None));
    }''', '''    if total == 0 {
        return Ok(None);
    }''')

s = s.replace('''        if seen == picked {
            let printed = if want_cost {
                crate::play::printed_energy_cost(
                    content,
                    definition,
                    ctx.source.unwrap_or(CombatantId::EMPTY),
                )
            } else {
                None
            };
            let definition_id = CardDefinitionId::new(definition)?;
            return Ok((Some(definition_id), printed));
        }
        seen += 1;
    }
    Ok((None, None))''', '''        if seen == picked {
            return Ok(Some(CardDefinitionId::new(definition)?));
        }
        seen += 1;
    }
    Ok(None)''')
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
print('exec.rs 改成绝对价格')

# play.rs：把 printed_energy_cost 删掉（它就是为了 delta 才写的，而绝对价格不需要它）
P = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
s = io.open(P, encoding='utf-8').read()
start = s.index('/// §240：**一张定义的能量印刷费用**')
end = s.index('fn calculate_costs(state: &CombatState, card: &CardOnTable<\'_>)')
s = s[:start] + s[end:]
io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
print('play.rs 删掉 printed_energy_cost')
