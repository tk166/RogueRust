"""§304 负控。

① 没有遗物也问（掩码不读遗物）；
② `gambling_chip` 的 `min` 写成 1（"any number" 变成"至少一张"）；
③ `toolbox` 的候选池不筛 `colorless`（拿到非无色牌）；
④ ★ `toolbox` 误用 `ToHand`（会写一个 `-printed` 折扣 ⇒ 那张牌当回合免费，而 wiki 没这句）。
"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    ('没有遗物也问', STATE,
     '''        if matches!(
            self.first_relic_effect_of(RelicEffect::CombatOpenDiscardThenDraw),
            Some(RelicEffect::CombatOpenDiscardThenDraw)
        ) {
            mask |= COMBAT_OPEN_GAMBLING_CHIP;
        }''',
     '''        if matches!(
            self.first_relic_effect_of(RelicEffect::CombatOpenDiscardThenDraw),
            Some(RelicEffect::CombatOpenDiscardThenDraw)
        ) || self.relics_len == 0 {
            mask |= COMBAT_OPEN_GAMBLING_CHIP;
        }''',
     'rd-run', 'the_combat_open_relics_are_a_bitmask_and_absent_without_the_relics'),
    ('chip 的 min 写成 1', RUN,
     '''                min: 0,
                max: hand.min(u8::MAX as usize) as u8,
                then: rd_core::state::ChoiceThen::DiscardThenDraw,''',
     '''                min: 1,
                max: hand.min(u8::MAX as usize) as u8,
                then: rd_core::state::ChoiceThen::DiscardThenDraw,''',
     'rd-wasm', 'gambling_chip_asks_at_combat_start_and_discards_then_draws'),
    ('toolbox 池不筛无色', RUN,
     '''        if image.card_has_tag(id, "colorless") != Some(true) {
            continue;
        }''',
     '''        if image.card_has_tag(id, "colorless") != Some(true) && index > 4 {
            continue;
        }''',
     'rd-wasm', 'toolbox_offers_three_colorless_cards_and_charges_the_printed_price'),
    ('toolbox 误用 ToHand（写折扣）', RUN,
     '''            then: rd_core::state::ChoiceThen::ToHandPrinted,''',
     '''            then: rd_core::state::ChoiceThen::ToHand,''',
     'rd-wasm', 'toolbox_offers_three_colorless_cards_and_charges_the_printed_price'),
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
            print('%-30s -> %s' % (label, 'RED as expected' if not passed
                                   else 'STILL GREEN'))
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
