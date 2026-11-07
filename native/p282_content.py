"""§282 内容：`standard.confusion` 状态 + `snecko` 怪 + `enc_snecko` + Act 2 池。

wiki（`Module:Enemies/data` 的 Snecko 段 + slayspiredb，两处一致）：

* HP **114-120**（A7+：120-125）；Act 2 **普通**敌人，**独自**出现；
* `Perplexing Glare`：**第 1 回合必用**，对玩家挂 *Confused*；
* 之后每回合 **Bite 60%**（15 伤害；A2+ 18）或 **Tail Whip 40%**（8 伤害；A2+ 10；
  2 层易伤；A17+ 另有 2 层虚弱）。
* "Bite 不会连用三次" —— 这条**需要**"最近两次招式"的状态；`selfHasCounter(last_move)`
  只能记住**上一条**，所以这里先按加权 Choice 做，偏差写进 `docs/sts-wiki-gap.md`。

*Confused*（`standard.confusion`）："Whenever you draw a card, randomize its cost"（0..3，
四档等概率），不叠加，整场有效。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

DAMAGE = lambda amount: {
    'kind': 'node.sequence',
    'value': {
        'Children': [{
            'kind': 'node.dealDamage',
            'value': {
                'TargetSelector': {
                    'kind': 'sel.eventTarget',
                    'value': {'Cardinality': 'ZeroOrOne',
                              'RequiredContextCapabilities': 'EventTarget'},
                },
                'Amount': {'kind': 'const', 'value': {'Value': amount}},
                'ResultKey': None,
                'IgnoresBlock': False,
                'Element': None,
            },
        }],
    },
}


def apply_status(status, stacks):
    entry = {
        'kind': 'node.applyStatus',
        'value': {
            'TargetSelector': {
                'kind': 'sel.eventTarget',
                'value': {'Cardinality': 'ZeroOrOne',
                          'RequiredContextCapabilities': 'EventTarget'},
            },
            'StatusDefinitionId': {'value': status},
            'Stacks': {'kind': 'const', 'value': {'Value': stacks}},
            'DurationTurns': 0,
            'Charges': 0,
            'ResultKey': None,
        },
    }
    return entry


def seq(*children):
    return {'kind': 'node.sequence', 'value': {'Children': list(children)}}


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))

    # ── ① 状态：`standard.confusion` ────────────────────────────────────────────
    if not any(s['Id'] == 'standard.confusion' for s in doc['Statuses']):
        doc['Statuses'].append({
            'Id': 'standard.confusion',
            'PackageId': 'sts',
            'NameKey': 'Confused',
            'DescriptionKey': 'Whenever you draw a card, randomize its cost (0-3).',
            'Polarity': 'Debuff',
            # 不叠加（wiki: "Does not stack"，上限 1）⇒ 不用层数、不用回合、不用充能。
            # 内核在 `exec::draw_for` 里按 **id** 看"有没有"，所以这三格必须是 false。
            'UsesStacks': False,
            'UsesDuration': False,
            'UsesCharges': False,
            'StackingBehavior': 'MergeWithExistingInstance',
            'Tags': ['debuff', 'confusion'],
            'PassiveModifiers': [],
            'Triggers': [],
        })

    # ── ② 三个动作 ─────────────────────────────────────────────────────────────
    actions = {a['Id']: a for a in doc['EnemyActions']}
    actions['snecko.perplexing_glare'] = {
        'Id': 'snecko.perplexing_glare',
        'PackageId': 'sts',
        'NameKey': 'Perplexing Glare',
        'DescriptionKey': 'Perplexing Glare - Applies Confused',
        'Intent': {'Kind': 'Debuff', 'Label': 'Perplexing Glare - Applies Confused'},
        'Program': {'Id': {'Value': '(unnamed)'}, 'Root': seq(
            apply_status('standard.confusion', 1))},
    }
    actions['snecko.bite'] = {
        'Id': 'snecko.bite',
        'PackageId': 'sts',
        'NameKey': 'Bite',
        'DescriptionKey': 'Bite - 15 damage',
        'Intent': {'Kind': 'Attack', 'Label': 'Bite - 15 damage'},
        'Program': {'Id': {'Value': '(unnamed)'}, 'Root': DAMAGE(15)},
        # A2+：18 伤害（wiki：`Deals 15 (18) damage`）。
        'ProgramAsc': [{'AscensionMin': 2, 'Program': {'Id': {'Value': '(unnamed)'},
                                                       'Root': DAMAGE(18)}}],
    }
    actions['snecko.tail_whip'] = {
        'Id': 'snecko.tail_whip',
        'PackageId': 'sts',
        'NameKey': 'Tail Whip',
        'DescriptionKey': 'Tail Whip - 8 damage, 2 Vulnerable',
        'Intent': {'Kind': 'AttackDebuff', 'Label': 'Tail Whip - 8 damage, 2 Vulnerable'},
        'Program': {'Id': {'Value': '(unnamed)'}, 'Root': seq(
            DAMAGE(8), apply_status('standard.vulnerable', 2))},
        # A2+：10 伤害。A17+：再加 2 层虚弱（ProgramAsc 是**变体列表**，两条阈值各自生效）。
        'ProgramAsc': [
            {'AscensionMin': 2, 'Program': {'Id': {'Value': '(unnamed)'},
                                            'Root': seq(DAMAGE(10),
                                                        apply_status('standard.vulnerable', 2))}},
            {'AscensionMin': 17, 'Program': {'Id': {'Value': '(unnamed)'},
                                             'Root': seq(DAMAGE(10),
                                                         apply_status('standard.vulnerable', 2),
                                                         apply_status('standard.weak', 2))}},
        ],
    }
    doc['EnemyActions'] = list(actions.values())

    # ── ③ 怪 ───────────────────────────────────────────────────────────────────
    doc['Monsters'] = [m for m in doc['Monsters'] if m['Id'] != 'snecko']
    doc['Monsters'].append({
        'Id': 'snecko',
        'NameKey': 'Snecko',
        'HpMin': 114,
        'HpMax': 120,
        # A7+：120-125（参考的"升档血量"由 `MaxHealthAsc` 那一格表达，见 ENCT/Monster 的约定）。
        'MaxHealth': 114,
        'MaxHealthAsc': 120,
        'Actions': [{'value': 'snecko.perplexing_glare'},
                    {'value': 'snecko.bite'},
                    {'value': 'snecko.tail_whip'}],
        'StartingStatuses': [],
        'IntentRules': [
            # 第 1 回合：Perplexing Glare（wiki: "Always starts with Perplexing Glare"）。
            {'Condition': {'kind': 'intent.round',
                           'value': {'Op': 'Equal', 'Round': 1}},
             'Action': {'value': 'snecko.perplexing_glare'},
             'Priority': 90},
            # 之后：Bite 60% / Tail Whip 40%（加权 `Choice`）。
            # ⚠️ 偏差："Bite 不会连用三次"要记**最近两次**招式，而 `selfHasCounter(last_move)`
            # 只记住上一条 ⇒ 这里先不做，写进 `docs/sts-wiki-gap.md`。
            {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': []}},
             'Priority': 10,
             'Choice': [{'Action': {'value': 'snecko.bite'}, 'Weight': 60},
                        {'Action': {'value': 'snecko.tail_whip'}, 'Weight': 40}]},
        ],
    })

    # ── ④ 遭遇（独自出现）─────────────────────────────────────────────────────
    doc['Encounters'] = [e for e in doc['Encounters']
                         if e['Id']['Value'] != 'enc_snecko']
    doc['Encounters'].append({
        'Id': {'Value': 'enc_snecko'},
        'Enemies': [{
            'Id': 'snecko',
            'MaxHealth': 114,
            'MaxHealthAsc': 120,
            'Actions': [{'value': 'snecko.perplexing_glare'},
                        {'value': 'snecko.bite'},
                        {'value': 'snecko.tail_whip'}],
            'StartingStatuses': [],
            'Position': None,
            'IntentRules': [
                {'Condition': {'kind': 'intent.round',
                               'value': {'Op': 'Equal', 'Round': 1}},
                 'Action': {'value': 'snecko.perplexing_glare'},
                 'Priority': 90},
                {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': []}},
                 'Priority': 10,
                 'Choice': [{'Action': {'value': 'snecko.bite'}, 'Weight': 60},
                            {'Action': {'value': 'snecko.tail_whip'}, 'Weight': 40}]},
            ],
        }],
    })

    # ── ⑤ Act 2 的普通池（`Weak2`）────────────────────────────────────────────
    pool = [row for row in doc['EncounterTables']['Weak2'] if isinstance(row, dict)]
    if not any(row.get('Id') == 'enc_snecko' for row in pool):
        pool.append({'Id': 'enc_snecko', 'Weight': 50})
    doc['EncounterTables']['Weak2'] = pool

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('snecko + confusion added; Weak2 =', doc['EncounterTables']['Weak2'])


main()
