"""§314 Mugger + `2 Thieves`：Act 2 的最后一条（13 / 13）。

wiki（`Thieves` 页，**原文明确**）：*"**Mugger** has the same pattern as **Looter**."*
所以这一节不是"猜出招序列"，而是**抄 Looter 的骨架 + 换数字**：

| 项 | Looter | Mugger |
|---|---|---|
| HP | 44-48（A7 46-50） | **48-52（A7 50-54）** |
| Mug | 10（A2 11） | 10（A2 11） |
| Lunge | 12（A2 14） | **16（A2 18）** |
| Smoke Bomb | 6 Block | **11 Block（A17 17）** |
| Thievery | 15（A17 20） | 15（A17 20） |
| Escape | 带着钱跑 | 同 |

顺手把两个贼的 **Thievery A17 = 20** 也补上（之前只有 A2 的伤害档；wiki 的两处表都写了
`15 (20 17)`）。它不是"新规则"，只是同一个 `stolen_gold += X` 的第二个阈值。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

MUG, LUNGE, SMOKE, ESCAPE = 1, 2, 3, 4


def ident(value):
    return {'value': value}


def sel_source():
    return {'kind': 'sel.source',
            'value': {'Cardinality': 'ZeroOrOne',
                      'RequiredContextCapabilities': 'Source'}}


def sel_event():
    return {'kind': 'sel.eventTarget',
            'value': {'Cardinality': 'ZeroOrOne',
                      'RequiredContextCapabilities': 'EventTarget'}}


def const(value):
    return {'kind': 'const', 'value': {'Value': value}}


def counter(counter_id):
    return {'kind': 'combatantCounter',
            'value': {'Selector': sel_source(), 'CounterId': ident(counter_id)}}


def damage(amount):
    return {'kind': 'node.dealDamage',
            'value': {'TargetSelector': sel_event(), 'Amount': const(amount),
                      'ResultKey': None, 'IgnoresBlock': False, 'Element': None}}


def block(amount):
    return {'kind': 'node.gainBlock',
            'value': {'TargetSelector': sel_source(), 'Amount': const(amount),
                      'ResultKey': None}}


def set_counter(counter_id, amount, relative=False):
    return {'kind': 'node.setCombatantCounter',
            'value': {'TargetSelector': sel_source(), 'CounterId': ident(counter_id),
                      'Amount': amount if isinstance(amount, dict) else const(amount),
                      'Relative': relative}}


def history(move):
    return [set_counter('prev_move', counter('last_move')),
            set_counter('last_move', move)]


def sequence(children):
    return {'kind': 'node.sequence', 'value': {'Children': children}}


def program(root):
    return {'Id': ident('(unnamed)'), 'Root': root, 'MaxNodeDepth': 64, 'MaxProgramSteps': 1024}


def action(action_id, name, intent_kind, label, root, asc=()):
    row = {'Id': action_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': label,
           'Intent': {'Kind': intent_kind, 'Label': label}, 'Program': program(root)}
    if asc:
        row['ProgramAsc'] = [{'AscensionMin': level, 'Program': program(root_at_level)}
                             for level, root_at_level in asc]
    return row


def steal_program(amount, stolen, move):
    return sequence([damage(amount), set_counter('stolen_gold', stolen, relative=True)]
                    + history(move))


def escape_program():
    return sequence([
        {'kind': 'node.carryAwayStolenGold',
         'value': {'TargetSelector': sel_source(),
                   'CounterId': ident('stolen_gold')}},
        {'kind': 'node.destroyCombatant', 'value': {'TargetSelector': sel_source()}},
    ] + history(ESCAPE))


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    assert 'mugger' not in {m['Id'] for m in doc['Monsters']}

    # ── 1. 两个贼的 Thievery A17 = 20（同一个 `stolen_gold += X` 的第二个阈值）──────────────
    for action_id, amount_v2, move in (('looter.mug', 11, MUG), ('looter.lunge', 14, LUNGE)):
        row = next(a for a in doc['EnemyActions'] if a['Id'] == action_id)
        row['ProgramAsc'] = [
            {'AscensionMin': 2, 'Program': program(steal_program(amount_v2, 15, move))},
            {'AscensionMin': 17, 'Program': program(steal_program(amount_v2, 20, move))},
        ]

    # ── 2. Mugger 的四招 ──────────────────────────────────────────────────────────────────
    mugger_actions = [
        action('mugger.mug', 'Mug', 'Attack', 'Mug - 10 damage',
               steal_program(10, 15, MUG),
               asc=[(2, steal_program(11, 15, MUG)), (17, steal_program(11, 20, MUG))]),
        action('mugger.lunge', 'Lunge', 'Attack', 'Lunge - 16 damage',
               steal_program(16, 15, LUNGE),
               asc=[(2, steal_program(18, 15, LUNGE)), (17, steal_program(18, 20, LUNGE))]),
        action('mugger.smoke_bomb', 'Smoke Bomb', 'Defend', 'Smoke Bomb - 11 Block',
               sequence([block(11)] + history(SMOKE)),
               asc=[(17, sequence([block(17)] + history(SMOKE)))]),
        action('mugger.escape', 'Escape', 'Special', 'Escape - flees with your gold',
               escape_program()),
    ]
    assert not any(a['Id'] in {x['Id'] for x in doc['EnemyActions']} for a in mugger_actions)

    # Looter 的规则骨架 —— wiki 原话是 "same pattern as Looter"，所以两条规则表**逐条同构**，
    # 只把 action id 换掉。抄而不是"重新设计"，是这一节唯一诚实的做法。
    looter_record = next(e for e in doc['Encounters'] if e['Id']['Value'] == 'enc_looter')
    looter_rules = json.loads(json.dumps(looter_record['Enemies'][0]['IntentRules']))

    def rewire(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'value' and isinstance(value, str) and value.startswith('looter.'):
                    node[key] = 'mugger.' + value.split('.', 1)[1]
                else:
                    rewire(value)
        elif isinstance(node, list):
            for item in node:
                rewire(item)

    rewire(looter_rules)

    mugger = {
        'Id': 'mugger',
        'NameKey': 'Mugger',
        'HpMin': 48,
        'HpMax': 52,
        'MaxHealth': 48,
        'MaxHealthAsc': [{'AscensionMin': 7, 'MaxHealth': 50}],
        'Actions': [ident('mugger.mug'), ident('mugger.lunge'),
                    ident('mugger.smoke_bomb'), ident('mugger.escape')],
        'StartingStatuses': [],
        'IntentRules': looter_rules,
        'Tier': 'Normal',
        'InvRef': 'wiki:Thieves',
        'AiNote': ('wiki `Thieves` 原话：**"Mugger has the same pattern as Looter."** ⇒ 规则表'
                   '从 Looter 逐条复制（只换 action id）。数字：HP 48-52（A7 50-54）、Mug 10'
                   '（A2 11）、Lunge 16（A2 18）、Smoke Bomb 11（A17 17）、Thievery 15（A17 20）。'),
        'Counters': [],
        'Spawn': True,
    }

    # ── 3. `2 Thieves`（wiki：1 Looter 在左、1 Mugger 在右）─────────────────────────────────
    looter_enemy = json.loads(json.dumps(looter_record['Enemies'][0]))
    looter_enemy['Position'] = 0
    mugger_enemy = {
        'Id': 'mugger',
        'MaxHealth': 48,
        'Actions': mugger['Actions'],
        'StartingStatuses': [],
        'Position': 1,
        'IntentRules': json.loads(json.dumps(looter_rules)),
        'DisplayName': 'Mugger',
        'Rolls': [],
        'Counters': [],
        'Spawn': True,
        'MaxHealthAsc': [{'AscensionMin': 7, 'MaxHealth': 50}],
    }
    encounter = {
        'Id': {'Value': 'enc_two_thieves'},
        'Enemies': [looter_enemy, mugger_enemy],
        'HeroResources': [{'Resource': ident('standard.energy'), 'Current': 3, 'Max': 3}],
        'HeroStartingStatuses': [],
        'TriggeredEffects': [],
        'HeroDisplayName': None,
        'CardsDrawnPerTurn': None,
    }
    assert not any(e['Id']['Value'] == 'enc_two_thieves' for e in doc['Encounters'])

    doc['EnemyActions'].extend(mugger_actions)
    doc['Monsters'].append(mugger)
    doc['Encounters'].append(encounter)
    # wiki 的 Easy 池权重 2 ⇒ ×5 = 10
    doc['EncounterTables']['Weak2'].append({'Id': 'enc_two_thieves', 'Weight': 10})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('monsters %d actions %d encounters %d weak2 %d'
          % (len(doc['Monsters']), len(doc['EnemyActions']), len(doc['Encounters']),
             len(doc['EncounterTables']['Weak2'])))


main()
