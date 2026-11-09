"""§309 负控：三条改错都必须让对应的判据**红**（"只改数字不算验证"）。

1. 容量退回 4 ⇒ `a_run_with_five_status_relics_keeps_all_five` 必须炸；
2. `push_relic` 的整局快照回滚拿掉 ⇒ `a_refused_tiny_house...` 必须红；
3. `pickup_add_card` 的回滚拿掉 ⇒ `a_pool_that_cannot_roll_again...` 必须红。
跑完自动还原。
"""
import io
import subprocess
import sys

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CARGO = 'C:/Users/TK11/.cargo/bin/cargo.exe'
MANIFEST = 'D:/Vibe/sts-tui/kernel/Cargo.toml'

CASES = [
    ('容量退回 4',
     'pub const MAX_COMBAT_STATUSES: usize = MAX_RUN_RELICS;',
     'pub const MAX_COMBAT_STATUSES: usize = 4;',
     'a_run_with_five_status_relics_keeps_all_five'),
    ('push_relic 不回滚',
     '''        let snapshot = *self;
        let outcome = self.push_relic_inner(relic_id, pool);
        if outcome.is_err() {
            *self = snapshot;
        }
        outcome''',
     '        self.push_relic_inner(relic_id, pool)',
     'a_refused_tiny_house'),
    ('pickup_add_card 不回滚',
     '''        let snapshot = *self;
        let outcome = self.pickup_add_card_inner(slot, pool);
        if outcome.is_err() {
            *self = snapshot;
        }
        outcome''',
     '        self.pickup_add_card_inner(slot, pool)',
     'a_pickup_add_that_cannot_roll_again'),
]


def main():
    original = io.open(PATH, encoding='utf-8').read()
    bad = 0
    try:
        for label, old, new, test in CASES:
            assert original.count(old) == 1, label
            io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
                original.replace(old, new, 1))
            out = subprocess.run([CARGO, 'test', '-p', 'rd-run', '--manifest-path', MANIFEST,
                                  '--release', test], capture_output=True, text=True,
                                 errors='replace')
            blob = (out.stdout or '') + (out.stderr or '')
            red = 'test result: FAILED' in blob or 'panicked' in blob
            print('%-24s -> %s' % (label, 'RED (good)' if red else 'STILL GREEN (bad!)'))
            if not red:
                bad += 1
                print(blob[-900:])
    finally:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(original)
    print('负控完成：%d/%d 条按预期变红' % (len(CASES) - bad, len(CASES)))
    sys.exit(1 if bad else 0)


main()
