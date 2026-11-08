"""§286 负控：四条判据各自必须真的会红。

① 进入效果不应用 ⇒ `entry_effects_land_on_arrival_and_roll_back_together` 红；
② 四选一退化成"永远第一档" ⇒ `a_four_way_branch_reaches_every_branch` 红；
③ `mark_resolved` 不清档位 ⇒ `an_event_can_turn_the_room_into_a_fight` 红；
④ `fight_begin` 不认事件战斗 ⇒ `an_event_fight_begins_and_settles_as_an_elite` 红。
"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    (STATE, 'entry effects never applied',
     '''        if let Some(effects) = entry
            .iter()''',
     '''        if let Some(effects) = entry
            .iter()
            .take(0)''',
     'rd-run', 'entry_effects_land_on_arrival'),
    (STATE, 'branches always take the first',
     '''            let mut edge = 0u32;
            let mut picked = branches[branches.len() - 1].1;''',
     '''            let mut edge = 1000u32;
            let mut picked = branches[0].1;''',
     'rd-run', 'a_four_way_branch_reaches_every_branch'),
    (STATE, 'mark_resolved keeps the band',
     '''        self.event_fight = 0;
        let node = self.node;''',
     '''        let node = self.node;''',
     'rd-run', 'an_event_can_turn_the_room_into_a_fight'),
    (STATE, 'relic_random goes back to the payload arm',
     '''            "relic_random" => (Self::GainRandomRelic, None),
            // §280''',
     '''            // §280''',
     'rd-wasm', 'every_event_effect_word_in_the_image_parses'),
    (STATE, 'gold_random uses the raw order',
     '''                                    && low.abs() <= high.abs() =>''',
     '''                                    && low <= high =>''',
     'rd-wasm', 'every_event_effect_word_in_the_image_parses'),
    (WASM, 'fight_begin ignores event fights',
     '''    if kind != 1 && kind != 2 && kind != 7 && !unknown_fight && event_fight == 0 {''',
     '''    if kind != 1 && kind != 2 && kind != 7 && !unknown_fight {''',
     'rd-wasm', 'an_event_fight_begins_and_settles_as_an_elite'),
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
