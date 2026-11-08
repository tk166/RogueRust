"""§298 负控：治疗倍率与两件放行遗物，每条规则各改坏一次。

① `magic_flower` 的倍率改成 100（=不放大）；
② 倍率乘在**入队处**而不是 `heal_for`（漏一条路）—— 用"把 `amount` 从 ×150 改成 +50"模拟
   （加而不是乘：7 点会变 57 而不是 10，判据红）；
③ `medical_kit` 放行时不限牌的种类（Status **和** Curse 都放）⇒ ③ 那条反面断言红；
④ 放行后不强制 `ExhaustPile`（落回 `DiscardPile`）⇒ "进消耗堆"那条红。
"""
import io
import subprocess
import sys

EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'


def cargo_test(test):
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-core', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


CASES = [
    ('magic_flower 倍率改成 100', EXEC,
     '''pub const MAGIC_FLOWER: (&str, i32) = ("standard.magic_flower", 150);''',
     '''pub const MAGIC_FLOWER: (&str, i32) = ("standard.magic_flower", 100);''',
     'magic_flower_multiplies_healing_by_one_and_a_half'),
    ('magic_flower 用加法而不是乘法', EXEC,
     '''        amount.saturating_mul(MAGIC_FLOWER.1) / 100''',
     '''        amount.saturating_add(MAGIC_FLOWER.1)''',
     'magic_flower_multiplies_healing_by_one_and_a_half'),
    ('medical_kit 不限牌的种类', PLAY,
     '''    if card_has_tag(card.content, card.row, STATUS_TAG)?
        && has_status(source, MEDICAL_KIT_STATUS)
    {
        return Ok(());
    }''',
     '''    if (card_has_tag(card.content, card.row, STATUS_TAG)?
        || card_has_tag(card.content, card.row, CURSE_TAG)?)
        && has_status(source, MEDICAL_KIT_STATUS)
    {
        return Ok(());
    }''',
     'the_two_unplayable_relics_let_their_own_card_kind_through'),
    ('放行后不强制消耗', PLAY,
     '''        None if unplayable_is_free(state, &card)? => CardZone::ExhaustPile,''',
     '''        None if false => CardZone::ExhaustPile,''',
     'the_two_unplayable_relics_let_their_own_card_kind_through'),
]


def main():
    originals = {}
    for _, path, _, _, _ in CASES:
        originals.setdefault(path, io.open(path, encoding='utf-8').read())
    failures = 0
    try:
        for label, path, good, bad, test in CASES:
            text = originals[path]
            assert text.count(good) == 1, (label, text.count(good))
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(good, bad))
            passed, output = cargo_test(test)
            print('%-34s -> %s' % (label, 'RED as expected' if not passed
                                   else 'STILL GREEN (not watching)'))
            if passed:
                failures += 1
                print(output[-400:])
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    finally:
        for path, text in originals.items():
            io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    for _, _, _, _, test in CASES:
        passed, _ = cargo_test(test)
        assert passed, 'restore failed for ' + test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
