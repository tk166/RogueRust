"""§304 收尾三处：`OpenChoices` 定义、`end_of_combat` 的裸清单、5 处 `RunSession {` 初始化。"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def main():
    s = io.open(STATE, encoding='utf-8').read()
    lines = s.split('\n')
    bare = [i for i, line in enumerate(lines)
            if line.strip().startswith('| RelicEffect::EnemyHealthInFirstFights')
            and not line.rstrip().endswith(',')
            and 'WingBoots' not in '\n'.join(lines[i:i + 4])]
    assert len(bare) == 1, bare
    i = bare[0]
    indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
    lines[i + 1:i + 1] = [f'{indent}// §304：两件"开战问一句"的遗物也不是回合末效果。',
                          f'{indent}| RelicEffect::CombatOpenDiscardThenDraw',
                          f'{indent}| RelicEffect::CombatOpenOfferColorless {{ .. }}']
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
    print('end_of_combat list')

    t = io.open(RUN, encoding='utf-8').read()
    # 结构体定义
    old = '''struct RunSession {'''
    assert t.count(old) == 1, t.count(old)
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

    # 5 处初始化
    count = t.count('RunSession {')
    assert count >= 5, count
    out = []
    added = 0
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
    assert added == 5, added
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(''.join(out))
    print('RunSession initialisers:', added)


main()
