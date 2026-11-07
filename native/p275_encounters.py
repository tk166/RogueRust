"""§275 遭遇补齐：Act 1 的 4 个"只用现有怪物"的遭遇。

## 先纠正一条旧信息

FACTS §8 写着"精英只有 4 个遭遇，缺 Lagavulin / Book of Stabbing / Slavers / Nemesis /
Reptomancer"。**这条已经过期**：五个全在内容里、AI 接线、升阶变体齐全，而且六条具名运行时
判据在 `rd-wasm/src/lib.rs` 里通过（`the_five_elite_encounters_match_the_wiki_numbers`
等）。所以这一节补的是**弱池**，不是精英。

## 权威表（两个独立来源一致：wiki.gg `Exordium` 与 slayspiredb `Exordium`）

Act 1 有**两个池**：Easy（前三场：Cultist 2 / Jaw Worm 2 / 2 Louse 2 / Small Slimes 2）与
Hard（Gang of Gremlins 1 / Large Slime 2 / Swarm of Slimes 1 / **Blue Slaver 2** /
**Red Slaver 1** / **3 Louse 2** / **2 Fungi Beasts 2** / Exordium Thugs 1.5 /
Exordium Wildlife 1.5 / Looter 2）。

本移植只有**一个** `Weak` 池（easy 与 hard 合并）—— 既有简化，不是这一节新引入的。
按这张表对照，缺的是：

| 缺的 | 为什么这一节能做 |
|---|---|
| **3 Louse** | 怪物已有（`louse_green` / `louse_red`） |
| **2 Fungi Beasts** | 怪物已有（`fungi_beast`） |
| **Blue Slaver**（solo）| 怪物已有（只在 `enc_slavers` 里出现过） |
| **Swarm of Slimes**（3 spike S + 2 acid S）| 怪物已有 |
| Large Slime | **缺怪物**：我们是 M/S 两种史莱姆，没有 L 系 —— 新怪，另开一节 |
| Exordium Thugs / Wildlife | **动态组合**（"First enemy: Louse 或 Medium Slime；Second: Slaver/Cultist/Looter"），我们的遭遇是静态列表 —— 要一次规则层，另开一节 |

## 权重怎么定

wiki 的权重是 1 / 1.5 / 2 的相对值，而我们的池子用的是 14–15 的整数刻度（同一个简化）。
所以按同一比例放大：权重 2 ⇒ **14**、权重 1 ⇒ **7**。

## HP 口径

沿用既有的"逐遭遇写 `MaxHealth` + `MaxHealthAsc`（Act 1 用 A7）"的惯例：
`louse_red` 10/11、`louse_green` 11/12、`fungi_beast` 22/24、`blue_slaver` 46/48、
`spike_slime_s` 10/11、`acid_slime_s` 8/9。
（`acid_slime_s` 之前**没有**任何遭遇用到，这一节是它第一次上场 —— 所以 HP 按 wiki 的
8–12 取下界 8、A7 9，与 `spike_slime_s` 的 10/11 同一个取法。）
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def enemy(mid, hp, asc_hp, statuses, actions):
    return {
        'Id': mid,
        'MaxHealth': hp,
        'Actions': [{'value': a} for a in actions],
        'StartingStatuses': [
            {'StatusDefinitionId': {'value': sid}, 'Stacks': stacks} for sid, stacks in statuses
        ],
        'Position': None,
        'IntentRules': [],
        'DisplayName': mid.replace('_', ' ').title(),
        'Rolls': [],
        'Counters': [],
        'Spawn': True,
        'MaxHealthAsc': [{'AscensionMin': 7, 'MaxHealth': asc_hp}],
    }


def encounter(eid, name, enemies):
    """遭遇行的**完整键集**照抄 `enc_gremlin_gang` —— 我第一版多写了 `NameKey`/`NodeKind`，
    内容编译器报 `KeyError: ('NameKey', 'NodeKind')`（那两格不属于这个 schema）。"""
    del name
    return {
        'Id': {'Value': eid},
        'Enemies': enemies,
        'HeroResources': [{'Resource': {'value': 'standard.energy'}, 'Current': 3, 'Max': 3}],
        'HeroStartingStatuses': [],
        'TriggeredEffects': [],
        'HeroDisplayName': None,
        'CardsDrawnPerTurn': None,
    }


LOUSE_RED = ('louse_red', 10, 11, [('standard.curl_up', 1)], ['louse_red.bite', 'louse_red.grow'])
LOUSE_GREEN = ('louse_green', 11, 12, [('standard.curl_up', 1)],
               ['louse_green.bite', 'louse_green.spit_web'])
FUNGI = ('fungi_beast', 22, 24, [], ['fungi_beast.bite', 'fungi_beast.grow'])
BLUE = ('blue_slaver', 46, 48, [], ['blue_slaver.stab', 'blue_slaver.rake'])
SPIKE_S = ('spike_slime_s', 10, 11, [('standard.thorns', 3)], ['spike_slime_s.tackle'])
ACID_S = ('acid_slime_s', 8, 9, [], ['acid_slime_s.tackle', 'acid_slime_s.lick'])

NEW = {
    # 3 Louse：StS 每只独立掷色；静态内容只能写一种组合 —— 取 1 绿 2 红（写明偏差）。
    'enc_three_louses': ('3 Louses', [LOUSE_GREEN, LOUSE_RED, LOUSE_RED]),
    'enc_two_fungi_beasts': ('2 Fungi Beasts', [FUNGI, FUNGI]),
    'enc_blue_slaver': ('Blue Slaver', [BLUE]),
    # Swarm of Slimes：3× Spike (S) + 2× Acid (S)。
    'enc_swarm_of_slimes': ('Swarm of Slimes', [SPIKE_S, SPIKE_S, SPIKE_S, ACID_S, ACID_S]),
}

WEIGHTS = {
    'enc_three_louses': 14,
    'enc_two_fungi_beasts': 14,
    'enc_blue_slaver': 14,
    'enc_swarm_of_slimes': 7,
}


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    ids = lambda row: row['Id']['Value'] if isinstance(row.get('Id'), dict) else row['Id']
    have = {ids(row) for row in doc['Encounters']}
    assert not (have & set(NEW)), 'already present: %s' % sorted(have & set(NEW))

    known = {ids(row) for row in doc['EnemyActions']}
    for eid, (name, enemies) in NEW.items():
        for spec in enemies:
            mid, hp, asc, statuses, actions = spec
            for action in actions:
                assert action in known, '%s uses unknown action %s' % (eid, action)
        doc['Encounters'].append(encounter(eid, name, [enemy(*spec) for spec in enemies]))
        print('encounter %-22s %d enemies' % (eid, len(enemies)))

    for eid, weight in WEIGHTS.items():
        doc['EncounterTables']['Weak'].append({'Id': eid, 'Weight': weight})
        print('pool Weak += %-22s w=%d' % (eid, weight))

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: encounters %d, Weak pool %d' % (
        len(doc['Encounters']), len(doc['EncounterTables']['Weak'])))


main()
