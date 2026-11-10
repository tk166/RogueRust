"""§331 Phase 2（续）：rd-wasm 掷候选 + 标签替换，以及 N'loth 的内容。

**掷**：`begin_event` 之后，如果这一段声明了 `RelicOffer: N`，就从玩家现有的遗物里掷 N 件
**互不相同**的（wiki：`Relic A` / `Relic B` 从当前持有的遗物里随机挑）。用 `RunStream::Event`，
与事件抽取同一条流 —— 不开新流，否则 `run_hash` 的随机计数会多一格而语义没变。

**标签**：选项标签里的 `{0}` / `{1}` 换成那件遗物的**显示名**。替换放在 ABI 里做，
页面零改动（页面本来就是"读一段字节当按钮文字"）。
"""

import io

RUN_RS = 'kernel/rd-wasm/src/run.rs'
CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(RUN_RS, encoding='utf-8').read()

# ── 1. 掷候选 ─────────────────────────────────────────────────────────────────
t = sub(t, """        if let Err(e) = session.state.begin_event(id, entry) {
            let message = describe(&e);
            return fail(session, &message);
        }""",
        """        if let Err(e) = session.state.begin_event(id, entry) {
            let message = describe(&e);
            return fail(session, &message);
        }
        // §331：`N'loth` 的候选遗物 —— 开事件那一刻掷定（wiki: 从**当前持有**的遗物里随机挑两件）。
        // 用 `RunStream::Event`：与事件抽取同一条流，不开新流（多开一条只会让 `run_hash`
        // 的随机计数多一格，而语义没变）。
        let offer = image.event_step(entry).map_or(0, |step| step.relic_offer);
        if offer > 0 {
            if let Err(message) = roll_event_relic_offer(session, u8::from(offer)) {
                return fail(session, &message);
            }
        }""",
        'roll call')

# ── 2. 掷法本身 ───────────────────────────────────────────────────────────────
t = sub(t, """/// Rest: heal 30% of maximum HP. Returns the health restored, or `-2`.""",
        """/// §331：给事件掷 `count` 件**互不相同**的遗物候选（`N'loth` 的两件）。
///
/// 从**当前持有**的遗物里挑（wiki 原话），所以持有不足 `count` 件时是内容/条件错 —— 那种事件
/// 本来就不该出现（`N'loth` 的 `Requires` 是 `relic_count at_least 2`）。这里**响亮拒绝**，
/// 不静默少给一件：少给一件会让两个按钮指向同一件遗物，而屏幕上看起来一切正常。
fn roll_event_relic_offer(session: &mut RunSession, count: u8) -> Result<(), String> {
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
}

/// Rest: heal 30% of maximum HP. Returns the health restored, or `-2`.""",
        'roll fn')

# ── 3. 标签替换 ───────────────────────────────────────────────────────────────
OLD_LEN = """/// Choice `slot`'s button text.
#[no_mangle]
pub extern "C" fn rd_run_event_label_len(slot: i32) -> i32 {
    match event_choice(slot) {
        Some(choice) => choice.label.len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_event_label_len(slot)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_event_label_into(slot: i32, ptr: *mut u8) -> i32 {
    match event_choice(slot) {
        Some(choice) => write_out(choice.label, ptr),
        None => 0,
    }
}"""

NEW_LEN = """/// §331：把选项标签里的 `{0}` / `{1}` 换成那一件**候选遗物**的显示名（`N'loth` 的
/// `[Offer: Relic A]`）。
///
/// 替换放在这里而不是页面：页面本来就是"读一段字节当按钮文字"，所以页面零改动；
/// 而"页面自己拼文案"是 §274 记过的那类重复（两处认识同一个词表）。
///
/// 没有 `{n}` 的标签原样返回；候选缺席时保留原文（**不**悄悄换成空串 —— 那会让
/// "候选没掷出来"变成"按钮没有名字"，而后者看起来像样式问题）。
fn event_label_text(choice: rd_core::content::EventOption<'static>) -> std::string::String {
    let label = choice.label;
    if !label.contains('{') {
        return std::string::String::from(label);
    }
    let mut out = std::string::String::from(label);
    let Some(session) = run_slot().as_ref() else {
        return out;
    };
    let image = content();
    for slot in 0..rd_core::content::MAX_EVENT_RELIC_OFFER {
        let placeholder = std::format!("{{{slot}}}");
        if !out.contains(&placeholder) {
            continue;
        }
        let Some(relic_id) = session.state.event_relic_offer(slot) else {
            continue;
        };
        let name = image
            .lookup_in(relic_id, rd_core::content::EK_RELIC)
            .and_then(|entry| image.relic(u32::from(entry.index)))
            .and_then(|row| row.display_name())
            .and_then(|index| image.string(index))
            .filter(|name| !name.is_empty())
            .unwrap_or(relic_id);
        out = out.replace(&placeholder, name);
    }
    out
}

/// Choice `slot`'s button text.
#[no_mangle]
pub extern "C" fn rd_run_event_label_len(slot: i32) -> i32 {
    match event_choice(slot) {
        Some(choice) => event_label_text(choice).len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_event_label_len(slot)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_event_label_into(slot: i32, ptr: *mut u8) -> i32 {
    match event_choice(slot) {
        Some(choice) => write_out(&event_label_text(choice), ptr),
        None => 0,
    }
}"""
t = sub(t, OLD_LEN, NEW_LEN, 'label substitution')

io.open(RUN_RS, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-wasm: roll + label substitution')
