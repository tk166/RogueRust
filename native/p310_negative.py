"""§310 负控：把"只清 Debuff"的判断改成"清 Buff"，判据必须红。

这是这一节唯一有意义的反证：如果判据只断言"清完之后 Weak/Frail 没了"，那"清全部状态"
也能通过 —— 而"清全部"正是把 Buff 一起清掉的那种错。所以负控就是*制造那一种错*。
"""
import io
import subprocess
import sys

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
CARGO = 'C:/Users/TK11/.cargo/bin/cargo.exe'
MANIFEST = 'D:/Vibe/sts-tui/kernel/Cargo.toml'

OLD = '''                if status_polarity(instance.definition_id.as_str(), ctx.content)?
                    == crate::state::StatusPolarity::Debuff
                {'''
NEW = '''                if status_polarity(instance.definition_id.as_str(), ctx.content)?
                    == crate::state::StatusPolarity::Buff
                {'''


def main():
    original = io.open(PATH, encoding='utf-8').read()
    assert original.count(OLD) == 1
    bad = 0
    try:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(original.replace(OLD, NEW, 1))
        out = subprocess.run([CARGO, 'test', '-p', 'rd-core', '--manifest-path', MANIFEST,
                              '--release', 'orange_pellets'], capture_output=True, text=True,
                             errors='replace')
        blob = (out.stdout or '') + (out.stderr or '')
        red = 'test result: FAILED' in blob or 'panicked' in blob
        print('只清 Debuff 改成清 Buff -> %s' % ('RED (good)' if red else 'STILL GREEN (bad!)'))
        if not red:
            bad = 1
            print(blob[-900:])
    finally:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(original)
    print('负控完成：%s' % ('1/1 按预期变红' if not bad else '0/1'))
    sys.exit(bad)


main()
