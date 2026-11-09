"""§309 前置：开战状态的**最坏条数**到底是多少。

审阅报告说 `MAX_COMBAT_STATUSES = 4` 且"尚未验证能否触及上限"。核对发现比它想的更糟：
**每件带战斗程序的遗物都会推一条 `standard.<relic>` 标记状态**（`runic_pyramid` / `lantern` /
`ice_cream` / `calipers` …都是），也就是说上限应当由**腰带容量**决定（48），而不是 4。

这个脚本量出上界：`relic_effect` 的 match 表里每个 id 只出现一次（一个 match 臂），
所以主表每件遗物最多贡献 1 条；`RELIC_SECOND_HALVES` 再给少数遗物补 1 条。
"""
import io
import re

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

HERO = ('StartCombatStatus', 'StartCombatStatusInKinds', 'CampfireLift')
ENEMY = ('StartCombatStatusOnEnemies',)
PER_CURSE = ('StartCombatStatusPerCurse', 'StartCombatStatusPerCurseInKinds')


def main():
    text = io.open(PATH, encoding='utf-8').read()

    start = text.index('pub fn relic_effect(id: &str) -> Option<RelicEffect> {')
    end = text.index('\n    }\n', text.index('_ => None,', start))
    body = text[start:end]

    arms = re.findall(
        r'"([a-z0-9_]+)"\s*=>\s*(?:\(?\s*)?(?:{)?\s*(?:Some\(|)(?:RelicEffect::)?([A-Za-z]+)',
        body)
    main_table = {}
    for rid, variant in arms:
        main_table.setdefault(rid, variant)
    hero_main = {r: v for r, v in main_table.items() if v in HERO}
    enemy_main = {r: v for r, v in main_table.items() if v in ENEMY}
    per_curse_main = {r: v for r, v in main_table.items() if v in PER_CURSE}

    halves_start = text.index('RELIC_SECOND_HALVES')
    halves_end = text.index('];', halves_start)
    halves = re.findall(r'\("([a-z0-9_]+)",\s*RelicEffect::([A-Za-z]+)',
                        text[halves_start:halves_end])
    hero_halves = {r for r, v in halves if v in HERO}
    enemy_halves = {r for r, v in halves if v in ENEMY}
    per_curse_halves = {r for r, v in halves if v in PER_CURSE}

    print('主表遗物 %d 条；其中 hero 状态 %d / 敌人状态 %d / 每诅咒 %d'
          % (len(main_table), len(hero_main), len(enemy_main), len(per_curse_main)))
    print('second halves %d 条；其中 hero %d / 敌人 %d / 每诅咒 %d'
          % (len(halves), len(hero_halves), len(enemy_halves), len(per_curse_halves)))
    print('hero 上界 = 主表 hero ∪ second halves hero = %d'
          % len(set(hero_main) | hero_halves))
    print('  两项都占的遗物（会占 2 格）: %d' % len(set(hero_main) & hero_halves))
    print('敌人上界 = %d；每诅咒上界 = %d'
          % (len(set(enemy_main) | enemy_halves),
             len(set(per_curse_main) | per_curse_halves)))
    print('腰带容量 MAX_RUN_RELICS = 48 ⇒ hero 最坏 = 48 + %d = %d'
          % (len(set(hero_main) & hero_halves), 48 + len(set(hero_main) & hero_halves)))


main()
