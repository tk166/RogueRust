"""§293 负控：把加牌问句的每条规则改坏，对应判据必须红。"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    ('orrery 不记欠账', STATE,
     '                self.pickup_add = self.pickup_add.saturating_add(count);',
     '                let _ = count;',
     'orrery_owes_five_cards_and_rolls_a_new_hand_each_time'),
    ('挑完不换一手（同一手给两次）', STATE,
     '            self.roll_pickup_offer(pool)?;\n        }\n        Ok(())\n    }\n\n    /// §293：跳过这一次',
     '        }\n        Ok(())\n    }\n\n    /// §293：跳过这一次',
     'orrery_owes_five_cards_and_rolls_a_new_hand_each_time'),
    ('满牌组也把欠账吃掉', STATE,
     '        self.push_card(row)?;\n        self.pickup_add -= 1;',
     '        let _ = self.push_card(row);\n        self.pickup_add -= 1;',
     'a_full_deck_refuses_the_pick_without_eating_the_debt'),
    ('singing_bowl 没有遗物也允许换', STATE,
     '            return Err(RunError::UnsupportedRelic { index: 0 });\n        };\n        if self.pickup_add == 0 {',
     '        };\n        if self.pickup_add == 0 {',
     'singing_bowl_trades_a_card_for_two_max_hp_in_both_places'),
    ('奖励屏换上限不花掉卡牌行', STATE,
     '        self.adjust_health(amount);' + chr(10) + '        for row in self.reward.cards.iter_mut() {' + chr(10) + '            *row = RunId::EMPTY;' + chr(10) + '        }' + chr(10) + '        self.reward.cards_len = 0;',
     '        self.adjust_health(amount);',
     'singing_bowl_trades_a_card_for_two_max_hp_in_both_places'),
    ('tiny_house 只给金币', STATE,
     '                self.adjust_gold(TINY_HOUSE_GOLD);\n                self.health_max += TINY_HOUSE_MAX_HEALTH;',
     '                self.adjust_gold(TINY_HOUSE_GOLD);',
     'tiny_house_does_all_four_things'),
]


def run(path, test):
    package = 'rd-wasm' if path == WASM else 'rd-run'
    out = subprocess.run(
        [CARGO, 'test', '-p', package, '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    originals = {path: io.open(path, encoding='utf-8').read() for path in (STATE, WASM)}
    failures = 0
    try:
        for label, path, good, bad, test in CASES:
            text = originals[path]
            assert text.count(good) == 1, (label, text.count(good))
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(good, bad))
            passed, output = run(path, test)
            print('%-34s -> %s' % (label, 'RED as expected' if not passed
                                   else 'STILL GREEN (not watching)'))
            if passed:
                failures += 1
                print(output[-400:])
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    finally:
        for path, text in originals.items():
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    for _, path, _, _, test in CASES:
        passed, _ = run(path, test)
        assert passed, 'restore failed for ' + test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
