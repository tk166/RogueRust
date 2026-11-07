"""§275 遭遇补齐（第二版）：Act 1 硬池里"只用现有怪物"的三场。

## 第一版的两个错（都值得记）

1. **遭遇里的 `IntentRules` 是 roster 的副本，必须逐字一致。** 我写了 `IntentRules: []`，
   内容门立刻报 `the inline IntentRules differ from the roster's copy` —— 恶心之处在于
   "空规则"在运行时不是崩溃，而是**那只怪永远用 Actions 的第一条**（静默的行为偏差）。
   修法：**克隆**同 id 的既有遭遇行（没有就克隆 roster 行），只改 HP/位置。
2. **`MAX_ENEMY_SLOTS` 是 4**，`Swarm of Slimes`（3 spike + 2 acid）要 5 个槽位。
   那是**容量常量 = 语义**（观察向量按它排布），所以这一节**不做**它，写进缺口。

## 权威表（wiki.gg `Exordium` 与 slayspiredb `Exordium` 一致）

Act 1 hard 池：Gang of Gremlins 1 / Large Slime 2 / Swarm of Slimes 1 / **Blue Slaver 2** /
Red Slaver 1 / **3 Louse 2** / **2 Fungi Beasts 2** / Exordium Thugs 1.5 / Exordium Wildlife 1.5 /
Looter 2。这一节做加粗的三场（怪物都已存在），权重按 2 ⇒ 14、1 ⇒ 7 的同一刻度。

三件仍然缺（写在 §275 文档里）：`Swarm of Slimes`（要 5 槽）、`Large Slime`（要 L 系史莱姆怪）、
`Exordium Thugs/Wildlife`（要动态组合规则）。
"""
import copy
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

# 三场：id → (显示名, [(怪物 id, HP, A7 HP), ...])
NEW = {
    'enc_three_louses': ('3 Louses', [
        ('louse_green', 11, 12),
        ('louse_red', 10, 11),
        ('louse_red', 10, 11),
    ]),
    'enc_two_fungi_beasts': ('2 Fungi Beasts', [
        ('fungi_beast', 22, 24),
        ('fungi_beast', 22, 24),
    ]),
    'enc_blue_slaver': ('Blue Slaver', [
        ('blue_slaver', 46, 48),
    ]),
}

WEIGHTS = {
    'enc_three_louses': 14,
    'enc_two_fungi_beasts': 14,
    'enc_blue_slaver': 14,
}


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    ids = lambda row: row['Id']['Value'] if isinstance(row.get('Id'), dict) else row['Id']

    # ① 每个怪物 id 的"权威副本"：优先既有遭遇行，其次 roster 行。
    template = {}
    for encounter in doc['Encounters']:
        for enemy in encounter['Enemies']:
            template.setdefault(enemy['Id'], enemy)
    for monster in doc['Monsters']:
        mid = ids(monster)
        if mid not in template:
            template[mid] = {
                'Id': mid,
                'MaxHealth': monster.get('MaxHealth', 10),
                'Actions': monster.get('Actions') or [],
                'StartingStatuses': monster.get('StartingStatuses') or [],
                'Position': None,
                'IntentRules': monster.get('IntentRules') or [],
                'DisplayName': monster.get('NameKey', mid),
                'Rolls': monster.get('Rolls') or [],
                'Counters': monster.get('Counters') or [],
                'Spawn': monster.get('Spawn', True),
                'MaxHealthAsc': monster.get('MaxHealthAsc') or [],
            }

    have = {ids(row) for row in doc['Encounters']}
    assert not (have & set(NEW)), 'already present: %s' % sorted(have & set(NEW))

    for eid, (name, specs) in NEW.items():
        del name
        enemies = []
        for position, (mid, hp, asc_hp) in enumerate(specs):
            row = copy.deepcopy(template[mid])
            row['MaxHealth'] = hp
            row['MaxHealthAsc'] = [{'AscensionMin': 7, 'MaxHealth': asc_hp}]
            row['Position'] = position
            enemies.append(row)
        doc['Encounters'].append({
            'Id': {'Value': eid},
            'Enemies': enemies,
            'HeroResources': [{'Resource': {'value': 'standard.energy'}, 'Current': 3, 'Max': 3}],
            'HeroStartingStatuses': [],
            'TriggeredEffects': [],
            'HeroDisplayName': None,
            'CardsDrawnPerTurn': None,
        })
        print('encounter %-22s %d enemies (rules copied from the roster)' % (eid, len(enemies)))

    for eid, weight in WEIGHTS.items():
        doc['EncounterTables']['Weak'].append({'Id': eid, 'Weight': weight})
        print('pool Weak += %-22s w=%d' % (eid, weight))

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: encounters %d, Weak pool %d' % (
        len(doc['Encounters']), len(doc['EncounterTables']['Weak'])))


main()
