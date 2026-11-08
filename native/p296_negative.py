"""§296 负控：`chemical_x` 的三环各改坏一次，判据必须红。

① 加成没加（常量 0）⇒ X 不变；
② 加成加错地方（加到 `paid` —— 那会变成"多付 2 点能量"，而 X 不变）；
③ 不限于 X 费牌（所有牌都 +2）⇒ `strike` 那条反面断言红。
"""
import io
import subprocess
import sys

PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'
TEST = 'chemical_x_adds_two_to_the_x_of_an_x_cost_card'

CASES = [
    ('加成恒 0', '''        crate::exec::CHEMICAL_X.1''', '''        0'''),
    ('加成加到 paid 上（而不是 X）', '''    let x_cost = {
        let mut total = x_bonus;''', '''    let x_cost = {
        let mut total = 0;'''),
    # ③ "所有牌都 +2"：把加成挪到 `paid` 之前、对**每一张牌**生效 —— `strike` 那条反面断言必须红。
    ('对非 X 费牌也加（strike 6 -> 8）', '''    let x_bonus = if crate::exec::carries_status(state, &card.source, crate::exec::CHEMICAL_X.0) {''',
     '''    let x_bonus = if crate::exec::carries_status(state, &card.source, crate::exec::CHEMICAL_X.0) || true {'''),
]

CONTENT_CASE = '内容侧：chemical_x 状态没有上限（恒为 0 层 = 不触发）'


def cargo_test():
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-core', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', TEST],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    original = io.open(PLAY, encoding='utf-8').read()
    failures = 0
    try:
        for label, good, bad in CASES:
            assert original.count(good) == 1, (label, original.count(good))
            io.open(PLAY, 'w', encoding='utf-8', newline='\n').write(original.replace(good, bad))
            passed, output = cargo_test()
            print('%-34s -> %s' % (label, 'RED as expected' if not passed
                                   else 'STILL GREEN (not watching)'))
            if passed:
                failures += 1
                print(output[-400:])
            io.open(PLAY, 'w', encoding='utf-8', newline='\n').write(original)
    finally:
        io.open(PLAY, 'w', encoding='utf-8', newline='\n').write(original)

    passed, _ = cargo_test()
    assert passed, 'restore must make the test green again'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
