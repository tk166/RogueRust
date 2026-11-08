"""§292 Wave 1 的负控：把每条规则**改坏**，对应判据必须红。

判据本身绿不算证据 —— 只有"改坏了会红"才证明它真的在看那件事（§4 的老账）。
"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    # (说明, 原串, 改坏的串, 应当红的判据)
    ('face_of_cleric 不回血（只涨上限）',
     '                    self.health_max += amount;\n                    self.adjust_health(amount);',
     '                    self.health_max += amount;',
     'face_of_cleric_raises_the_maximum_after_every_fight'),
    ('matryoshka 的第二件没给',
     '        if extra_relic && !hungry {',
     '        if false && extra_relic && !hungry {',
     'matryoshka_queues_two_chests_and_pays_a_second_relic'),
    ('空宝箱照旧扣金币',
     '        if hungry {\n            gold = 0;\n        } else {\n            self.adjust_gold(gold);\n        }',
     '        self.adjust_gold(gold);',
     'nloths_hungry_face_empties_exactly_one_chest'),
    ('cursed_key 的诅咒不塞牌',
     '        if curse_key && !hungry {\n            self.add_random_curse(card_pool)?;\n        }',
     '        if false && curse_key && !hungry {\n            self.add_random_curse(card_pool)?;\n        }',
     'cursed_key_carries_its_energy_and_its_chest_curse'),
    ('calling_bell 的欠账不记',
     '                self.pickup_relics = self.pickup_relics.saturating_add(relics);',
     '                let _ = relics;',
     'calling_bell_pays_a_curse_and_owes_three_relics'),
    ('cauldron 的欠账不记',
     '                self.pickup_potions = self.pickup_potions.saturating_add(count);',
     '                let _ = count;',
     'cauldron_owes_five_potions_and_the_belt_caps_it'),
    ('dollys_mirror 复制成空操作',
     '                let copy = *row;\n                self.push_card(copy)?;',
     '                let _ = row;',
     'dollys_mirror_duplicates_the_chosen_card_and_refuses_a_full_deck'),
    ('nloths_gift 的倍率读不出来',
     '            Some(RelicEffect::RareCardChanceMultiplier(times)) if times > 0 => times,',
     '            Some(RelicEffect::RareCardChanceMultiplier(times)) if times < 0 => times,',
     'nloths_gift_triples_the_rare_band_and_never_passes_uncommon'),
    ('sacred_bark 的倍率读不出来',
     '            Some(RelicEffect::PotionEffectPercent(percent)) if percent > 0 => percent,',
     '            Some(RelicEffect::PotionEffectPercent(percent)) if percent < 0 => percent,',
     'sacred_bark_doubles_potion_effectiveness'),
    ('商店看不见 Shop 档',
     '            let shoppable = allow_shop && entry.rarity == Rarity::Shop;',
     '            let shoppable = false;',
     'shop_rarity_relics_are_reachable_only_from_the_shelf'),
]


def run(test):
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-run', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    original = io.open(STATE, encoding='utf-8').read()
    failures = 0
    try:
        for label, good, bad, test in CASES:
            assert original.count(good) == 1, (label, original.count(good))
            io.open(STATE, 'w', encoding='utf-8', newline='\n').write(
                original.replace(good, bad))
            passed, text = run(test)
            print('%-38s -> %s' % (label, 'RED as expected' if not passed
                                   else 'STILL GREEN (the gate is not watching)'))
            if passed:
                failures += 1
                print(text[-400:])
    finally:
        io.open(STATE, 'w', encoding='utf-8', newline='\n').write(original)
    # 恢复后复验一次（防止"改坏的串没恢复干净"）
    for _, _, _, test in CASES:
        passed, _ = run(test)
        assert passed, 'restore failed for ' + test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
