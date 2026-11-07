"""§274 负控：四处切口，每个都必须让判据变红。

  1. `old_coin` 不走 `adjust_gold` 而是直接 `self.gold += n` ⇒ `ectoplasm` 那条该红；
  2. `war_paint`/`whetstone` 不再看 `CardKind` ⇒ "只升自己那一类"该红；
  3. `pandoras_box` 的命中分支也 `index += 1`（off-by-one 回来）⇒ 该红；
  4. `pickup_card` 拒之后也扣额度 ⇒ "拒绝不消耗额度"该红。
"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    ('old_coin bypass', STATE,
     '''            RelicEffect::PickupGold(amount) => self.adjust_gold(amount),''',
     '''            RelicEffect::PickupGold(amount) => self.gold += amount,''',
     'the_pickup_number_relics_change_only_their_own_number', 'gold rule'),
    ('upgrade kind', STATE,
     '''                    if facts.kind == kind && facts.upgraded.is_some() {''',
     '''                    if facts.upgraded.is_some() {''',
     'the_upgrade_eggs_upgrade_two_of_their_own_kind', 'kind'),
    ('staple off-by-one', STATE,
     '''                    if card == STAPLE_STRIKE || card == STAPLE_DEFEND {
                        self.apply_deck_change(DeckChange::Transform, index, pool)?;
                    } else {
                        index += 1;
                    }''',
     '''                    if card == STAPLE_STRIKE || card == STAPLE_DEFEND {
                        self.apply_deck_change(DeckChange::Transform, index, pool)?;
                    }
                    index += 1;''',
     'pandoras_box_transforms_every_staple_and_nothing_else', 'off-by-one'),
    ('pickup refusal', STATE,
     '''        self.apply_deck_change(change, index, pool)?;
        self.pickup_picks = self.pickup_picks.saturating_sub(1);''',
     '''        self.pickup_picks = self.pickup_picks.saturating_sub(1);
        self.apply_deck_change(change, index, pool)?;''',
     'the_pickup_picks_do_not_take_over_the_screen', 'refusal must not spend'),
]


def run(test):
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-run', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True, encoding='utf-8',
        errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    original = io.open(STATE, encoding='utf-8').read()
    failures = 0
    for name, path, old, new, test, why in CASES:
        assert original.count(old) == 1, '%s: anchor %d' % (name, original.count(old))
        io.open(path, 'w', encoding='utf-8', newline='\n').write(original.replace(old, new))
        ok, text = run(test)
        red = (not ok) and ('FAILED' in text or 'panicked' in text)
        print('%-20s -> %s  (%s)' % (name, 'RED as expected' if red else 'STILL GREEN', why))
        if not red:
            failures += 1
            print(text[-1200:])
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(original)
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
