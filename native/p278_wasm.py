"""§278：wasm 侧改成"按当前段取正文/按钮"，并把 `next` 交给运行层。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:80])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ---------------------------------------------------------- event_choice
    s = patch(s, '''fn event_choice(slot: i32) -> Option<rd_core::content::EventChoice<'static>> {
    let session = run_slot().as_ref()?;
    if slot < 0 || slot > 1 {
        return None;
    }
    let (_, _, choices) = lookup_event(session)?;
    Some(choices[slot as usize])
}

fn open_event(session: &RunSession) -> Option<String> {
    let (id, text, _) = lookup_event(session)?;
    Some(std::format!("{id} — {text}"))
}

fn lookup_event(
    session: &RunSession,
) -> Option<(&'static str, &'static str, [rd_core::content::EventChoice<'static>; 2])> {
    let wanted = session.state.event();
    let image = content();
    for index in 0..image.event_count() {
        let event = image.event(index)?;
        if event.0 == wanted {
            return Some(event);
        }
    }
    None
}''','''fn event_choice(slot: i32) -> Option<rd_core::content::EventOption<'static>> {
    let session = run_slot().as_ref()?;
    if slot < 0 {
        return None;
    }
    let step = open_step(session)?;
    if slot as usize >= step.options().len() {
        return None;
    }
    Some(step.options()[slot as usize])
}

fn open_event(session: &RunSession) -> Option<String> {
    let (id, _name, _entry) = lookup_event(session)?;
    let step = open_step(session)?;
    Some(std::format!("{id} — {}", step.text))
}

/// §278：当前这一段有几个按钮。**由内容决定**，不是页面写死的 2（`golden_idol` 的第二段是三选一）。
#[no_mangle]
pub extern "C" fn rd_run_event_option_count() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    match open_step(session) {
        Some(step) => i32::from(step.count),
        None => -1,
    }
}

/// §278：打开的那一段（正文 + 按钮）。节点 id 来自**运行层**（`event_step`），不是页面猜的。
fn open_step(session: &RunSession) -> Option<rd_core::content::EventStep<'static>> {
    let image = content();
    image.event_step(session.state.event_step())
}

fn lookup_event(
    session: &RunSession,
) -> Option<(&'static str, &'static str, &'static str)> {
    let wanted = session.state.event();
    let image = content();
    for index in 0..image.event_count() {
        let event = image.event(index)?;
        if event.0 == wanted {
            return Some(event);
        }
    }
    None
}''')

    # ---------------------------------------------------------- begin_event 调用方
    s = patch(s, '''        .begin_event(event)''','''        .begin_event(event, entry)''', 0) if '.begin_event(event)' in s else s

    # ---------------------------------------------------------- rd_run_choose：传 next
    s = patch(s, '''    let outcome = session
        .state
        .resolve_event_effects(&parsed[..specs.len()], &pool)
        .map(|_| 0i32);
    finish(session, outcome)''','''    // §278：这一段选完之后还去不去下一段，**由内容**说（`option.Next`）。
    let next = choice.goes_on();
    let outcome = session
        .state
        .resolve_event_effects(&parsed[..specs.len()], next, &pool)
        .map(|_| 0i32);
    finish(session, outcome)''')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('wasm: steps wired')


main()
