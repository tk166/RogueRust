"""§304 收尾（第二版）：`OpenChoices` 字段/结构体 + 5 处初始化 + 掩码从**运行状态**读。"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def main():
    t = io.open(RUN, encoding='utf-8').read()

    # ① 结构体
    old = 'struct RunSession {'
    assert t.count(old) == 1, t.count(old)
    if 'struct OpenChoices' not in t:
        t = t.replace(old, '''/// §304：开战时欠着的问句（位掩码，见 `rd_run::state::COMBAT_OPEN_*`）。
///
/// 不是"一共几次"，是"**还没问出口**的那几位"：`ask_next_open_choice` 每问一个清一位，
/// 而"已经有问句挂着"时它一位都不清（谁来问只有一个来源）。
#[derive(Default)]
struct OpenChoices {
    mask: u8,
    /// `toolbox` 给几张候选（`0` = 没有 `toolbox`）。
    offer: u8,
}

struct RunSession {''')

    # ② 字段：插在 `state:` 之后
    if 'open_choices: OpenChoices,' not in t:
        anchor = None
        start = t.index('struct RunSession {')
        seg = t[start:start + 2000]
        line = '    state: rd_run::state::RunState,'
        assert line in seg, seg[:400]
        at = t.index(line, start) + len(line)
        t = t[:at] + '\n    /// §304：这一场开战时欠着的问句（见 [`OpenChoices`]）。\n    open_choices: OpenChoices,' + t[at:]

    # ③ 5 处初始化
    added = 0
    out = []
    index = 0
    while True:
        at = t.find('*run_slot() = Some(RunSession {', index)
        if at < 0:
            out.append(t[index:])
            break
        head_end = at + len('*run_slot() = Some(RunSession {')
        out.append(t[index:head_end])
        out.append('\n        open_choices: OpenChoices::default(),')
        index = head_end
        added += 1
    t = ''.join(out)
    assert added == 5, added

    # ④ 掩码从**运行状态**读（`combat_open_choices` 是 `RunState` 的方法）
    old = '''                    let (mask, offer) = crate::slot()
                        .as_ref()
                        .map(|combat| combat.state.combat_open_choices())
                        .unwrap_or((0, 0));
                    let Some(session) = run_slot().as_mut() else {
                        return Ok(());
                    };
                    session.open_choices.mask = mask;
                    session.open_choices.offer = offer;'''
    new = '''                    let Some(session) = run_slot().as_mut() else {
                        return Ok(());
                    };
                    let (mask, offer) = session.state.combat_open_choices();
                    session.open_choices.mask = mask;
                    session.open_choices.offer = offer;'''
    assert t.count(old) == 1, t.count(old)
    t = t.replace(old, new)

    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)
    print('RunSession wired; initialisers:', added)


main()
