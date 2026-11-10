"""§331 修 rd-wasm 的两处类型/借用问题。

1. `RelRow::display_name()` 返回 `u16`（串号），不是 `Option`；
2. 掷候选时不能同时借 `session.state`（`relics()` 的 `&str` 借的是 state）—— 先把遗物
   **拷进定长缓冲**（`RunId` 是 `Copy`），再放手去改 `rng` / 写候选。
"""

import io

PATH = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

t = sub(t, """        let name = image
            .lookup_in(relic_id, rd_core::content::EK_RELIC)
            .and_then(|entry| image.relic(u32::from(entry.index)))
            .and_then(|row| row.display_name())
            .and_then(|index| image.string(index))
            .filter(|name| !name.is_empty())
            .unwrap_or(relic_id);""",
        """        // `RelRow::display_name()` 给的是**串号**（`u16`），不是 `Option` —— 与
        // `encounter.hero_display_name()` 同一个形状，所以这里自己 `string()` 一次。
        let name = image
            .lookup_in(relic_id, rd_core::content::EK_RELIC)
            .and_then(|entry| image.relic(u32::from(entry.index)))
            .and_then(|row| image.string(row.display_name()))
            .filter(|name| !name.is_empty())
            .unwrap_or(relic_id);""",
        'display name')

t = sub(t, """fn roll_event_relic_offer(session: &mut RunSession, count: u8) -> Result<(), String> {
    let held: Vec<&'static str> = session.state.relics().iter().map(|id| id.as_str()).collect();
    if held.len() < usize::from(count) {
        return Err(std::format!(
            "事件要 {count} 件遗物候选，手上只有 {} 件",
            held.len()
        ));
    }
    let mut picked: Vec<&'static str> = Vec::with_capacity(usize::from(count));
    for slot in 0..usize::from(count) {
        // 拒绝采样：只从"还没被选中"的那些里掷 —— 于是"两件不同"由掷法保证，
        // 而不是掷完再去重（后者会让分布偏向列表靠前的遗物）。
        let remaining: Vec<&'static str> = held
            .iter()
            .copied()
            .filter(|id| !picked.contains(id))
            .collect();
        let width = u32::try_from(remaining.len()).map_err(|_| "遗物太多".to_string())?;
        let pick = session
            .state
            .rng_mut()
            .roll(rd_run::streams::RunStream::Event, width)
            .map_err(|e| crate::detail(&e))?;
        let Some(id) = remaining.get(pick as usize).copied() else {
            return Err("遗物候选掷不出来".to_string());
        };
        session
            .state
            .set_event_relic_offer(slot, id)
            .map_err(|e| crate::detail(&e))?;
        picked.push(id);
    }
    Ok(())
}""",
        """fn roll_event_relic_offer(session: &mut RunSession, count: u8) -> Result<(), String> {
    // ⚠️ 先把遗物**拷进定长缓冲**：`relics()` 借的是 `session.state`，而下面要 `rng_mut()`
    // 与 `set_event_relic_offer()`（都是可变借）。`RunId` 是 `Copy`，所以拷贝不花什么。
    let mut held = [rd_run::state::RunId::EMPTY; rd_run::state::MAX_RUN_RELICS];
    let held_len = session.state.relics().len();
    if held_len > held.len() {
        return Err("遗物数超过容量".to_string());
    }
    held[..held_len].copy_from_slice(session.state.relics());
    if held_len < usize::from(count) {
        return Err(std::format!(
            "事件要 {count} 件遗物候选，手上只有 {held_len} 件"
        ));
    }
    let mut picked = [rd_run::state::RunId::EMPTY; rd_core::content::MAX_EVENT_RELIC_OFFER];
    for slot in 0..usize::from(count) {
        // 拒绝采样：只从"还没被选中"的那些里掷 —— 于是"两件不同"由掷法保证，
        // 而不是掷完再去重（后者会让分布偏向列表靠前的遗物）。
        let mut remaining = [rd_run::state::RunId::EMPTY; rd_run::state::MAX_RUN_RELICS];
        let mut width = 0usize;
        for candidate in held.iter().take(held_len) {
            if picked[..slot].contains(candidate) {
                continue;
            }
            remaining[width] = *candidate;
            width += 1;
        }
        let width = u32::try_from(width).map_err(|_| "遗物太多".to_string())?;
        let pick = session
            .state
            .rng_mut()
            .roll(rd_run::streams::RunStream::Event, width)
            .map_err(|e| crate::detail(&e))?;
        let Some(id) = remaining.get(pick as usize).copied() else {
            return Err("遗物候选掷不出来".to_string());
        };
        session
            .state
            .set_event_relic_offer(slot, id.as_str())
            .map_err(|e| crate::detail(&e))?;
        picked[slot] = id;
    }
    Ok(())
}""",
        'roll fn borrows')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-wasm fixed')
