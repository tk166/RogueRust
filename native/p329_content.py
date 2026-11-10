"""§329 Boss 相位的三处规则缺口（都是"形状在、规则漏"）。

对照 `native/wiki_asc/*.txt` 逐条核，六个 Boss 的相位机制**基本都在**
（Champ 的 Anger 清三种 Debuff、Awakened One 的 unawakened 守卫与 rebirth 回满血、
Collector 的 Mega Debuff 与 Buff/Fireball 连用守卫、Automaton 的 A19 Boost 顶替 Stunned、
Time Eater 的 Haste 一次性与不连用、Donu/Deca 的交替）。真缺三处：

1. **`awakened_one.rebirth` 少了 "Removes all Debuffs"**
   wiki：*"Heals to full HP. Removes all Debuffs. Loses Curiosity."* —— 内容只做了后两件。
2. **`time_eater.haste` 少了 "Removes all Debuffs"**
   wiki：*"Removes all Debuffs. Heals to 50% HP. (A19: gains 32 Block.)"* —— 同一个形状。
3. **`the_collector` 少了"Torch Head 剩 0-1 个时可以再召唤"那一支，而且 `spawn` 无条件召 2 个**
   wiki：*"Summons **up to 2** Torch Heads"*；分支表是"0-1 只活着：Spawn 25% / Fireball 45% /
   Buff 30%"，"两只都活着：Fireball 70% / Buff 30%"。内容只有后者 —— 也就是说**两只 Torch Head
   死光之后 Collector 再也不会召唤**，而那是这场 Boss 战最核心的一条相位规则。

外加 **Awakened One 二阶段的"不能连用三次"**：wiki 说 Tackle / Sludge 都不能连用三次，
内容里只有一阶段的守卫。

三处都用**已有的节点**表达（`node.removeDebuffs` 是 §310 为 `orange_pellets` 加的；
`combatantCount` 是 §313 为 Mystic 的 Protect 加的），不需要动内核。
"""

import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'

doc = json.load(io.open(CONTENT, encoding='utf-8'))
actions = {a['Id']: a for a in doc['EnemyActions']}
encounters = {e['Id']['Value']: e for e in doc['Encounters']}


def source_selector():
    return {
        'kind': 'sel.source',
        'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'Source'},
    }


def remove_debuffs(target):
    """`node.removeDebuffs` —— 只写 `TargetSelector`（`remove_debuffs_node` 只读这一个字段）。"""
    return {'kind': 'node.removeDebuffs', 'value': {'TargetSelector': target}}


# ── 1/2. rebirth 与 haste 的 "Removes all Debuffs" ────────────────────────────
for action_id in ('awakened_one.rebirth', 'time_eater.haste'):
    action = actions[action_id]
    programs = [action['Program']] + [row['Program'] for row in (action.get('ProgramAsc') or [])]
    for program in programs:
        children = program['Root']['value']['Children']
        assert not any(c.get('kind') == 'node.removeDebuffs' for c in children), action_id
        # 紧跟在 heal 之后：wiki 的顺序就是 "Heals to full HP. Removes all Debuffs."
        heal_at = next(i for i, c in enumerate(children) if c.get('kind') == 'node.heal')
        children.insert(heal_at + 1, remove_debuffs(source_selector()))
    print('%s: + removeDebuffs (%d program(s))' % (action_id, len(programs)))

# ── 3. Collector 的 spawn 改成 "up to 2" ──────────────────────────────────────
spawn = actions['the_collector.spawn']
root = spawn['Program']['Root']
children = root['value']['Children']
spawns = [c for c in children if c.get('kind') == 'node.createCombatant']
assert len(spawns) == 2, len(spawns)
first_at = children.index(spawns[0])
rest = children[first_at + 2:]
assert children[first_at + 1] is spawns[1]


def spawn_node(count):
    return {
        'kind': 'node.sequence',
        'value': {'Children': [json.loads(json.dumps(spawns[0])) for _ in range(count)]},
    }


def count_of_enemies():
    return {
        'kind': 'combatantCount',
        'value': {
            'AliveOnly': True,
            'Selector': {'kind': 'sel.allEnemies', 'value': {}},
        },
    }


def at_least_enemies(n):
    return {
        'kind': 'compare',
        'value': {'Op': 'GreaterOrEqual', 'Left': count_of_enemies(),
                  'Right': {'kind': 'const', 'value': {'Value': n}}},
    }


# 3 个敌人（自己 + 2 只 Torch Head）⇒ 0 只；2 个 ⇒ 1 只；否则 ⇒ 2 只。
branch = {
    'kind': 'node.conditional',
    'value': {
        'Condition': at_least_enemies(3),
        'Then': spawn_node(0),
        'Else': {
            'kind': 'node.conditional',
            'value': {
                'Condition': at_least_enemies(2),
                'Then': spawn_node(1),
                'Else': spawn_node(2),
            },
        },
    },
}
root['value']['Children'] = children[:first_at] + [branch] + rest
print('the_collector.spawn: two unconditional spawns -> "up to 2"')

# ── 3b. Collector 的意图分支：0-1 只 Torch Head 活着时能再召唤 ────────────────
collector = [e for e in encounters['enc_the_collector']['Enemies'] if e['Id'] == 'the_collector'][0]
rules = collector['IntentRules']
assert not any('the_collector.spawn' in json.dumps(r) and r['Priority'] == 45 for r in rules)
rules.append({
    'Condition': {
        'kind': 'intent.enemyAliveCount',
        'value': {'Op': 'LessOrEqual', 'Value': 2},
    },
    'Priority': 45,
    'Choice': [
        {'Action': {'value': 'the_collector.spawn'}, 'Weight': 25},
        {'Action': {'value': 'the_collector.fireball'}, 'Weight': 45},
        {'Action': {'value': 'the_collector.buff'}, 'Weight': 30},
    ],
})
print('the_collector: + the "0-1 Torch Heads alive" branch (Spawn 25 / Fireball 45 / Buff 30)')

# ── 4. Awakened One 二阶段：Tackle / Sludge 不能连用三次 ──────────────────────
awakened = [e for e in encounters['enc_awakened_one']['Enemies'] if e['Id'] == 'awakened_one'][0]
rules = awakened['IntentRules']
# tackle=4, sludge=5（由动作里的 `last_move` 写死）
for same, other, other_id in ((4, 5, 'awakened_one.sludge'), (5, 4, 'awakened_one.tackle')):
    assert not any(json.dumps(r).count('"Value": %d' % same) and r['Priority'] == 75 for r in rules)
    rules.append({
        'Condition': {
            'kind': 'intent.allOf',
            'value': {
                'Conditions': [
                    {'kind': 'intent.selfHasCounter',
                     'value': {'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': same}},
                    {'kind': 'intent.selfHasCounter',
                     'value': {'Counter': {'value': 'prev_move'}, 'Op': 'Equal', 'Value': same}},
                ],
            },
        },
        'Priority': 75,
        'Action': {'value': other_id},
    })
print('awakened_one: + "Tackle/Sludge cannot be used three times in a row"')

io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
print('content written')
