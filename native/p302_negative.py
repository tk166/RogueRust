"""§302/§303 负控：每一环各改坏一次，确认判据会红。

① spoon 忘读状态（变成"所有消耗牌都有 50% 被救"）；
② spoon 概率改成 100%（`<= 50` → `<= 100`）；
③ spoon 把"免费"也算进去（不对齐 `ExhaustPile` 判断 ⇒ 打普通牌也掷骰）；
④ boots 飞行不扣次数；
⑤ boots 免费的路也扣次数；
⑥ boots 允许飞到 Boss（哨兵）。
"""
import io
import subprocess
import sys

PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    ('spoon 忘读状态', PLAY,
     '''    if !carries {
        return plan.destination;
    }''',
     '''    if false {
        return plan.destination;
    }''',
     'rd-wasm', 'strange_spoon_turns_about_half_of_the_exhausts_into_discards'),
    ('spoon 概率 100%', PLAY,
     '''    if state.draw_in_range(1, 100) <= STRANGE_SPOON_PERCENT {''',
     '''    if state.draw_in_range(1, 100) <= 100 {''',
     'rd-wasm', 'strange_spoon_turns_about_half_of_the_exhausts_into_discards'),
    ('spoon 对弃牌也掷骰', PLAY,
     '''    if plan.destination != CardZone::ExhaustPile {
        return plan.destination;
    }''',
     '''    if plan.destination == CardZone::BanishedPile {
        return plan.destination;
    }''',
     'rd-wasm', 'strange_spoon_never_rolls_for_discards_or_forced_exhausts'),
    ('boots 飞行不扣次数', STATE,
     '''        if flying {
            self.wing_boots_used = self.wing_boots_used.saturating_add(1);
        }''',
     '''        if flying && false {
            self.wing_boots_used = self.wing_boots_used.saturating_add(1);
        }''',
     'rd-run', 'wing_boots_lets_you_fly_three_times_and_never_charges_the_free_paths'),
    ('boots 免费的路也扣', STATE,
     '''        if flying {
            self.wing_boots_used = self.wing_boots_used.saturating_add(1);
        }''',
     '''        if true {
            self.wing_boots_used = self.wing_boots_used.saturating_add(1);
        }''',
     'rd-run', 'wing_boots_lets_you_fly_three_times_and_never_charges_the_free_paths'),
    # ⚠️ "Boss 步不算飞行"这条**不可单独失败**（Boss 在 `free` 里 ⇒ 结构上扣不到），
    # 所以负控换成"用完次数之后还能飞" —— 那是同一个窗口判断的另一侧。
    ('boots 用完之后还能飞', STATE,
     '''        self.wing_boots_left() > 0
            && self.node >= 0''',
     '''        self.wing_boots_left() >= 0
            && self.node >= 0''',
     'rd-run', 'wing_boots_lets_you_fly_three_times_and_never_charges_the_free_paths'),
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
    originals = {path: io.open(path, encoding='utf-8').read() for path in (PLAY, STATE)}
    failures = 0
    try:
        for label, path, good, bad, package, test in CASES:
            text = originals[path]
            assert text.count(good) == 1, (label, text.count(good))
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(good, bad))
            passed, output = cargo_test(package, test)
            print('%-24s -> %s' % (label, 'RED as expected' if not passed else 'STILL GREEN'))
            if passed:
                failures += 1
                print(output[-300:])
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
