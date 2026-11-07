"""§271 负控：证明四条判据会红。

四处切口各改一次、跑一次、**必须看到 FAILED**，然后还原：
  1. `meal_ticket` 改挂到 Rest 分支 → 节点那条判据该红；
  2. `sozu` 的 `push_potion` 拒绝去掉 → `sozu_refuses_potions_at_both_doors` 该红；
  3. `roll_reward` 不按 `NoPotionGain` 压 drop → 同一条判据该红（第二个门）；
  4. `clear_tea_set()` 挪到**算加成之前** → wasm 那条 `the_tea_set_charge_is_spent_by_the_next_fight`
     该红（"清掉了但状态没挂上" / "根本没挂"）。
"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    ('meal_ticket room', STATE,
     '''                if let Some(RelicEffect::ShopEntryHeal(amount)) =
                    self.first_relic_effect_of(RelicEffect::ShopEntryHeal(15))
                {
                    self.heal_after_combat(amount);
                }''',
     '''                if let Some(RelicEffect::ShopEntryHeal(amount)) =
                    self.first_relic_effect_of(RelicEffect::ShopEntryHeal(15))
                {
                    let _ = amount;
                }''',
     'the_node_relics_pay_on_the_right_kind_of_room', 'room'),
    ('sozu push door', STATE,
     '''        if self.holds_relic_effect(RelicEffect::NoPotionGain) {
            return Err(RunError::PotionGainBlocked);
        }''',
     '''        if false {
            return Err(RunError::PotionGainBlocked);
        }''',
     'sozu_refuses_potions_at_both_doors', 'push door'),
    ('sozu reward door', STATE,
     '''        let drop = rolled && self.potion_room() && !self.holds_relic_effect(RelicEffect::NoPotionGain);''',
     '''        let drop = rolled && self.potion_room();''',
     'sozu_refuses_potions_at_both_doors', 'reward door'),
    ('tea set order', WASM,
     '''    let bonus = session.state.combat_bonus_for(fight_kind);
    // §271：`ancient_tea_set` —— 加成**已经算出来**，现在才允许清掉"欠一场"。
    // ⚠️ 顺序反了（先清再算）它就永远读不到，`ancient_tea_set` 变成一件什么都不做的遗物，
    // 而所有判据仍然绿 —— 没有任何东西"错"。
    session.state.clear_tea_set();''',
     '''    session.state.clear_tea_set();
    let bonus = session.state.combat_bonus_for(fight_kind);''',
     'the_tea_set_charge_is_spent_by_the_next_fight', 'tea set order'),
]


def run(pkg, test):
    out = subprocess.run(
        [CARGO, 'test', '-p', pkg, '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True, encoding='utf-8',
        errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    originals = {}
    failures = 0
    for name, path, old, new, test, why in CASES:
        if path not in originals:
            originals[path] = io.open(path, encoding='utf-8').read()
        base = originals[path]
        assert base.count(old) == 1, '%s: anchor %d' % (name, base.count(old))
        io.open(path, 'w', encoding='utf-8', newline='\n').write(base.replace(old, new))
        pkg = 'rd-wasm' if path == WASM else 'rd-run'
        ok, text = run(pkg, test)
        red = (not ok) and ('FAILED' in text or 'panicked' in text)
        print('%-20s -> %s  (%s)' % (name, 'RED as expected' if red else 'STILL GREEN', why))
        if not red:
            failures += 1
            print(text[-1500:])
        io.open(path, 'w', encoding='utf-8', newline='\n').write(base)
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
