"""§287 负控：三条各自必须真的会红。

① `card_damage` 退化成常量 ⇒ `the_unknown_room_events_are_readable` 的 Wing Statue 段红；
② 欠账不消费（`roll_reward` 不读）⇒ `the_fight_reward_debt_is_paid_once` 红；
③ 事件池不看 `Encounter` ⇒ `the_ambush_lagavulin_starts_awake_with_siphon_soul` 红
   （不看池子就会抽到**睡着**的那一份，第一回合变成 `sleep`）。
"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
EXPR = 'D:/Vibe/sts-tui/kernel/rd-core/src/run_expr.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    (EXPR, 'card_damage is always satisfied',
     '''            "card_damage" => facts.max_hit_damage,''',
     '''            "card_damage" => 999,''',
     'rd-core', 'the_unknown_room_events_are_readable'),
    (STATE, 'the debt is never consumed',
     '''        let bonus = i32::from(self.fight_gold_bonus);''',
     '''        let bonus = 0;''',
     'rd-run', 'the_fight_reward_debt_is_paid_once'),
    (WASM, 'the event fight ignores its pool',
     '''    let pool_name: String = if !event_pool.is_empty() {''',
     '''    let pool_name: String = if false {''',
     'rd-wasm', 'the_ambush_lagavulin_starts_awake_with_siphon_soul'),
]


def run(package, test):
    out = subprocess.run(
        [CARGO, 'test', '-p', package, '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    failures = 0
    for path, label, old, new, package, test in CASES:
        original = io.open(path, encoding='utf-8').read()
        assert original.count(old) == 1, (label, original.count(old))
        io.open(path, 'w', encoding='utf-8', newline='\n').write(original.replace(old, new))
        passed, text = run(package, test)
        print('%-38s -> %s' % (label, 'RED as expected' if not passed else 'STILL GREEN'))
        if passed:
            failures += 1
            print(text[-300:])
        io.open(path, 'w', encoding='utf-8', newline='\n').write(original)
    for _, _, _, _, package, test in CASES:
        passed, _ = run(package, test)
        assert passed, 'restore must make %s green again' % test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
