"""§301 负控：`neows_lament` 的每一环各改坏一次。

① 窗口改成"永远"（`<= fights` 去掉上界）⇒ 第 4 场仍压血；
② 窗口改成 2 场 ⇒ 第 3 场就恢复；
③ wasm 里不调 `set_enemy_health` ⇒ 运行层说压、战斗里没压（"有人问了没人写"）。
"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    ('窗口无上界（永远压血）', STATE,
     '''        if self.fights >= 1 && self.fights <= fights {''',
     '''        if self.fights >= 1 {''',
     'rd-run', 'neows_lament_covers_exactly_the_first_three_fights'),
    ('窗口只有 2 场', STATE,
     '''        if self.fights >= 1 && self.fights <= fights {''',
     '''        if self.fights >= 1 && self.fights <= fights.saturating_sub(1) {''',
     'rd-run', 'neows_lament_covers_exactly_the_first_three_fights'),
    ('wasm 不写敌人血量（有人问没人写）', RUN,
     '''                if let Some(health) = session.state.enemy_health_override() {
                    crate::set_enemy_health(health);
                }''',
     '''                if let Some(_health) = session.state.enemy_health_override() {}''',
     'rd-wasm', 'neows_lament_gives_the_first_three_fights_one_hp_enemies'),
]


def cargo_test(package, test):
    out = subprocess.run(
        [CARGO, 'test', '-p', package, '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    originals = {path: io.open(path, encoding='utf-8').read() for path in (STATE, RUN)}
    failures = 0
    try:
        for label, path, good, bad, package, test in CASES:
            text = originals[path]
            assert text.count(good) == 1, (label, text.count(good))
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(good, bad))
            passed, output = cargo_test(package, test)
            print('%-34s -> %s' % (label, 'RED as expected' if not passed
                                   else 'STILL GREEN (not watching)'))
            if passed:
                failures += 1
                print(output[-400:])
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    finally:
        for path, text in originals.items():
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    for _, _, _, _, package, test in CASES:
        passed, _ = cargo_test(package, test)
        assert passed, 'restore failed for ' + test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
