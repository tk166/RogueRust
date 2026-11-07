"""§279：wasm 侧接上条件（事实 + 可用性 + 拒绝不可选的槽）。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:80])
    return s.replace(old, new)


FACTS = '''/// §279：把局面摊成条件求值要的事实。
///
/// 为什么在这里摊、而不是让 `run_expr` 直接拿 `&RunState`：`RunState` 住在 `rd-run`，而
/// `rd-run` **不读内容**（§133 的纪律）。条件引用的是**内容里的 id**（遗物 id / 卡 id），
/// 所以求值只能在同时握有内容与局面的这一层发生。
fn run_facts<'a>(
    session: &'a RunSession,
    relics: &'a [&'a str],
    deck: &'a [&'a str],
) -> rd_core::run_expr::RunFacts<'a> {
    rd_core::run_expr::RunFacts {
        gold: session.state.gold(),
        health: session.state.health(),
        health_max: session.state.health_max(),
        ascension: session.state.ascension(),
        relics,
        deck,
    }
}

/// §279：选项 `slot` 的条件现在成立吗？`None` = 没有这个槽。
///
/// 返回 `Some(Err)` 是**内容/镜像**的问题（认不出的 kind、缺字段），要响亮 —— 绝不能
/// 默认成立（"条件坏了 ⇒ 按钮全亮"比"按钮全灭"更难发现，因为屏幕看起来一切正常）。
fn option_available(session: &RunSession, slot: i32) -> Option<Result<bool, rd_core::run_expr::RequirementError>> {
    if slot < 0 {
        return None;
    }
    let step = open_step(session)?;
    let option = *step.options.get(slot as usize)?;
    let relics: Vec<&str> = session.state.relics().iter().map(|id| id.as_str()).collect();
    let deck: Vec<&str> = session.state.deck().iter().map(|id| id.as_str()).collect();
    let facts = run_facts(session, &relics, &deck);
    Some(rd_core::run_expr::option_is_available(content(), option.term, &facts))
}

/// §279：选项 `slot` 现在可不可选（`1` 可选 / `0` 不可选 / `-1` 没有这个槽）。
///
/// 页面用它来决定**画不画**这个按钮。与 `rd_run_choose` 判的是同一个函数，所以
/// "显示的按钮点下去没用"与"藏起来的按钮其实能点"这两种错都不可能只在一侧出现。
#[no_mangle]
pub extern "C" fn rd_run_event_option_available(slot: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    match option_available(session, slot) {
        Some(Ok(true)) => 1,
        Some(Ok(false)) => 0,
        // 条件坏了：**不可选**（0），并留一条消息给页面 —— 不是"可选"。
        Some(Err(error)) => {
            set_error(&std::format!("事件的 `Requires` 读不出来: {error:?}"));
            0
        }
        None => -1,
    }
}

'''

def main():
    s = io.open(P, encoding='utf-8').read()

    # ① 事实 + 可用性 + ABI（放在 lookup_entry 之前）
    s = patch(s, '''/// §278：事件 id → 它的入口段 id（`EV.Entry`）。''',
              FACTS + '''/// §278：事件 id → 它的入口段 id（`EV.Entry`）。''')

    # ② rd_run_choose：相位之后、取选项之前，判条件
    s = patch(s, '''    let Some(choice) = event_choice(slot) else {
        return -1;
    };
    // §188：选项是**一串**效果，而 A15（事件变糟）给的是**另一串**。''',
              '''    let Some(choice) = event_choice(slot) else {
        return -1;
    };
    // §279：**条件不成立的槽**要在这里拒。页面已经按 `rd_run_event_option_available`
    // 把它藏起来了，但"藏起来"不等于"点不到"（页面可能是旧快照，或者有人直接调 ABI）。
    // 拒绝用 `fail`（-2 + 文本），因为它和"相位没了"是同一类事：这个操作现在不合法。
    {
        let Some(session) = run_slot().as_ref() else {
            return -1;
        };
        match option_available(session, slot) {
            Some(Ok(true)) => {}
            Some(Ok(false)) => {
                let Some(session) = run_slot().as_mut() else {
                    return -1;
                };
                return fail(session, "这个选项的条件现在不成立（`Requires`）");
            }
            Some(Err(error)) => {
                let message = std::format!("事件的 `Requires` 读不出来: {error:?}");
                let Some(session) = run_slot().as_mut() else {
                    return -1;
                };
                return fail(session, &message);
            }
            None => return -1,
        }
    }
    // §188：选项是**一串**效果，而 A15（事件变糟）给的是**另一串**。''')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('wasm: facts + available + refusal')


main()
