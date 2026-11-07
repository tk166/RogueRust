"""§270 负控：证明三条判据会红（FACTS §4.23 —— 只改数字不算验证）。

三处切口各改一次、跑一次、**必须看到 FAILED**，然后还原：
  1. `omamori` 的顺序：把"被挡掉的诅咒不算得到"破掉（先加牌再加血）→ `darkstone` 那条断言该红；
  2. `adjust_gold`：把 `gained` 判据换回 `delta > 0` → `bloody_idol` + `ectoplasm` 那条该红；
  3. `shop_price`：把折扣改回 100% → 购买那条该红。
"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    ('omamori order', '''        if card.kind == CardKind::Curse && self.omamori_charges > 0 {
            self.omamori_charges -= 1;
            return Ok(());
        }''',
     '''        if card.kind == CardKind::Curse && self.omamori_charges > 0 {
            self.omamori_charges -= 1;
        }''', 'the_add_card_relics_fire_at_the_one_add_point', 'negated curse'),
    # 变异必须是一个**真会犯的错**：前两版都把改动插在 `let delta = if … {0}` **之后**，
    # 而那时 `delta` 已经被清零 ⇒ 判据当然还是绿的（负控本身错了，不是判据弱）。
    # 会犯的错是"先按原始参数回血、再拦金币"：
    ('gold gain test',
     """        let delta = if delta > 0 && self.holds_relic_effect(RelicEffect::NoGoldGain) {
            0
        } else {
            delta
        };
        let before = self.gold;
        self.gold = (self.gold + delta).max(0);
        let gained = self.gold - before;""",
     """        if delta > 0 {
            if let Some(RelicEffect::GoldGainHeal(amount)) =
                self.first_relic_effect_of(RelicEffect::GoldGainHeal(5))
            {
                self.heal_after_combat(amount);
            }
        }
        let delta = if delta > 0 && self.holds_relic_effect(RelicEffect::NoGoldGain) {
            0
        } else {
            delta
        };
        let before = self.gold;
        self.gold = (self.gold + delta).max(0);
        let gained = 0;""",
     'the_gold_and_shop_relics_change_only_their_own_number', 'blocked gold'),
    ('shop discount', '''        (base * percent / 100).max(0)''',
     '''        base''', 'a_discounted_purchase_charges_the_discounted_price', 'discount'),
]


def run(test):
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-run', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True, encoding='utf-8',
        errors='replace')
    text = out.stdout + out.stderr
    return ('1 passed' in text or ' ok. 1 passed' in text), text


def main():
    original = io.open(STATE, encoding='utf-8').read()
    failures = 0
    for name, old, new, test, why in CASES:
        assert original.count(old) == 1, '%s: anchor %d' % (name, original.count(old))
        io.open(STATE, 'w', encoding='utf-8', newline='\n').write(original.replace(old, new))
        ok, text = run(test)
        # 负控成功 = 判据**红了**
        red = (not ok) and ('FAILED' in text or 'panicked' in text)
        print('%-16s -> %s  (%s)' % (name, 'RED as expected' if red else 'STILL GREEN', why))
        if not red:
            failures += 1
            print(text[-1200:])
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(original)
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
