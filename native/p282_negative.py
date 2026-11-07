"""§282 负控：Confusion 的三条判据必须真的会红。

手法是改**内核源码**（随机/钩子坏掉不是内容能表达的事），每次改一处 → 跑判据 → 还原，
最后断言"还原后又绿"。
"""
import io
import subprocess
import sys

EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
TURN = 'D:/Vibe/sts-tui/kernel/rd-core/src/turn.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'
TEST = 'confusion_randomizes_the_cost_of_every_drawn_card'


def run():
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-wasm', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', TEST],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    failures = 0

    def mutate(path, name, old, new, label):
        nonlocal failures
        original = io.open(path, encoding='utf-8').read()
        assert original.count(old) == 1, ('anchor moved: ' + label, original.count(old))
        io.open(path, 'w', encoding='utf-8', newline='\n').write(original.replace(old, new))
        passed, text = run()
        print('%-30s -> %s' % (label, 'RED as expected' if not passed else 'STILL GREEN'))
        if passed:
            failures += 1
            print(text[-400:])
        io.open(path, 'w', encoding='utf-8', newline='\n').write(original)

    # ① 钩子退化成"不掷"（写回印刷价 1）
    mutate(EXEC, 'no-roll',
           '''    let roll = draw_random(state, CONFUSION_MIN, CONFUSION_MAX);''',
           '''    let roll = 1;''',
           'the hook writes a constant 1')

    # ② 豁免判据失效（不可打出的牌也被重掷）
    mutate(EXEC, 'no-exempt',
           '''        if content.card_has_tag(definition.as_str(), "unplayable") == Some(true) {
            return;
        }''',
           '''        // negative control: the unplayable exemption is gone''',
           'unplayable cards get randomized')

    # ③ 状态判据失效（没状态也掷）
    mutate(EXEC, 'no-status-check',
           '''    if !confused {
        return;
    }''',
           '''    // negative control: the status check is gone''',
           'no Confusion still randomizes')

    # ④ `turn.rs` 那条路径不调钩子（"只修了一条路"的回归）
    mutate(TURN, 'turn-path',
           '''            let confusion_content = host.confusion_content();
            crate::exec::confuse_drawn_card(state, confusion_content, &actor, slot);''',
           '''            // negative control: the turn-start path no longer confuses''',
           'turn-start path does not confuse')

    passed, _ = run()
    assert passed, 'restore must make the test green again'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
