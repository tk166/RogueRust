"""§273 负控：证明两条判据会红。

  1. `?`→商店 回到 `stock_shop`（不走 `enter_shop`）⇒ `meal_ticket` 那条该红；
  2. `buy_card` 的补货去掉 ⇒ "货架不缩水"那条该红。
"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    ('unknown shop heal', STATE,
     '''                    UnknownRoom::Shop => {
                        // §273：**同一个** `enter_shop` —— `?` 房变成商店也要触发 `meal_ticket`
                        // （wiki 的 Planisphere 页：*"a ? that turns into a shop triggers both"*）。
                        self.enter_shop(card_pool, relic_pool)?;
                        Pending::Shop
                    }''',
     '''                    UnknownRoom::Shop => {
                        self.stock_shop(card_pool, relic_pool)?;
                        Pending::Shop
                    }''',
     'an_unknown_room_that_becomes_a_shop_pays_the_shop_entry_relics', 'entry heal'),
    ('courier restock', STATE,
     '''        if self.holds_relic("the_courier") {
            self.restock_card_slot(slot, card_pool)?;
        }''',
     '''        if false {
            self.restock_card_slot(slot, card_pool)?;
        }''',
     'the_courier_restocks_the_slot_it_sells', 'restock'),
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
