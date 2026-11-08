"""§306 负控：把刚修好的两半各改坏一次。

① 回到"整段短路"（原 bug 的形态）⇒ Ethereal 被赦免 ⇒ 判据的相等那一侧红；
② Ethereal 也当成"留下"（反过来错）⇒ 无遗物时 Ethereal 不再消耗 ⇒ 基线那一侧红。
"""
import io
import subprocess
import sys

TURN = 'D:/Vibe/sts-tui/kernel/rd-core/src/turn.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    ('整段短路（原 bug）',
     '''    let hand_retained = host.hand_is_retained(state, actor);''',
     '''    if host.hand_is_retained(state, actor) {
        return Ok(0);
    }
    let hand_retained = false;'''),
    ('Ethereal 也当"留下"',
     '''        if destination != CardZone::ExhaustPile
            && (hand_retained || host.card_stays_in_hand_at_turn_end(state, actor, slot))
        {''',
     '''        if hand_retained || host.card_stays_in_hand_at_turn_end(state, actor, slot)
        {'''),
]


def cargo_test():
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-wasm', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', 'runic_pyramid'],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    original = io.open(TURN, encoding='utf-8').read()
    failures = 0
    try:
        for label, good, bad in CASES:
            assert original.count(good) == 1, (label, original.count(good))
            io.open(TURN, 'w', encoding='utf-8', newline='\n').write(original.replace(good, bad))
            passed, output = cargo_test()
            print('%-24s -> %s' % (label, 'RED as expected' if not passed else 'STILL GREEN'))
            if passed:
                failures += 1
            else:
                for line in output.split('\n'):
                    if 'panicked' in line or 'ethereal' in line or 'discarded' in line:
                        print('    ' + line.strip()[:110])
    finally:
        io.open(TURN, 'w', encoding='utf-8', newline='\n').write(original)
    passed, _ = cargo_test()
    assert passed, 'restore failed'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
