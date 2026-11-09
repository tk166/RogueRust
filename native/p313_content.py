"""§313（二）：Centurion + Mystic（Act 2 最后一条组合，wiki 权重 6）。

wiki（`Centurion and Mystic` 页）：

**Centurion**：HP 76-80（A7 78-83）。
* `Slash` 12（A2 14）；`Protect` —— **Mystic** 得 15 格挡（A17 20），**独自时自己得** 15；
* `Fury` 6×3（A2 7×3）—— 只在 Mystic 死后替代 `Protect`；
* Mystic 活着时 65% Slash / 35% Protect；**任何一招都不能连三次**。

**Mystic**：HP 48-56（A7 50-58）。
* `Attack` 8 + 2 Frail（A2 9）；`Buff` 全体敌人 +2 力量（A2 3 / A17 4）；`Heal` 全体敌人回 16（A17 20）；
* 有敌人缺 ≥16 血时用 Heal（最多连两次）；否则 60% Attack / 40% Buff；Attack 或 Buff 不能连三次；
  A17 起 Attack 不能连两次。

两条新零件正好够用：`sel.alliesWithDefinition`（Protect 找 Mystic）与
`intent.allyMissingHealth`（Heal 的优先级）。「独自 / Mystic 活着」用既有的
`intent.enemyAliveCount`（它数的是**出手者自己的阵营**，含自己 ⇒ 2 / 1）。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

SLASH, PROTECT, FURY = 1, 2, 3
M_ATTACK, M_BUFF, M_HEAL = 1, 2, 3


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


def sel_all_allies():
    return {'kind': 'sel.allAllies',
            'value': {'Cardinality': 'ZeroOrMore',
                      'RequiredContextCapabilities': 'Source'}}


def sel_allies_with_definition(definition):
    return {'kind': 'sel.alliesWithDefinition',
            'value': {'Cardinality': 'ZeroOrMore',
                      'RequiredContextCapabilities': 'Source',
                      'CombatantDefinitionId': definition}}


def const(value):
    return {'kind': 'const', 'value': {'Value': value}}


def counter(counter_id):
    return {'kind': 'combatantCounter',
            'value': {'Selector': sel_source(), 'CounterId': counter_id}}


def compare(left, right, op='GreaterOrEqual'):
    return {'kind': 'compare', 'value': {'Left': left, 'Right': right, 'Op': op}}


def and_all(conditions):
    result = conditions[0]
    for condition in conditions[1:]:
        result = {'kind': 'and', 'value': {'Left': result, 'Right': condition}}
    return result


def damage(amount, times=1):
    return [{'kind': 'node.dealDamage',
             'value': {'TargetSelector': sel_event(), 'Amount': const(amount),
                       'ResultKey': None, 'IgnoresBlock': False, 'Element': None}}
            for _ in range(times)]


def block_to(selector, amount):
    return {'kind': 'node.gainBlock',
            'value': {'TargetSelector': selector, 'Amount': const(amount), 'ResultKey': None}}


def block_self(amount):
    return block_to(sel_source(), amount)


def status_to(selector, definition, stacks):
    return {'kind': 'node.applyStatus',
            'value': {'TargetSelector': selector, 'StatusDefinitionId': ident(definition),
                      'Stacks': const(stacks), 'Duration': None, 'ResultKey': None}}


def heal_to(selector, amount):
    return {'kind': 'node.heal',
            'value': {'TargetSelector': selector, 'Amount': const(amount), 'ResultKey': None}}


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


def conditional(condition, then, otherwise=None):
    return {'kind': 'node.conditional',
            'value': {'Condition': condition, 'Then': then, 'Else': otherwise}}


def program(root):
    return {'Id': ident('(unnamed)'), 'Root': root, 'MaxNodeDepth': 64, 'MaxProgramSteps': 1024}


def action(action_id, name, intent_kind, label, root, asc=()):
    row = {'Id': action_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': label,
           'Intent': {'Kind': intent_kind, 'Label': label}, 'Program': program(root)}
    if asc:
        row['ProgramAsc'] = [{'AscensionMin': level, 'Program': program(program_root)}
                             for level, program_root in asc]
    return row


def rule(conditions, priority, action_id=None, choice=None):
    row = {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': conditions}},
           'Priority': priority}
    if action_id is not None:
        row['Action'] = ident(action_id)
    if choice is not None:
        row['Choice'] = [{'Action': ident(a), 'Weight': w} for a, w in choice]
    return row


def last_move_is(n):
    return {'kind': 'intent.selfHasCounter',
            'value': {'Counter': ident('last_move'), 'Op': 'Equal', 'Value': n}}


def prev_move_is(n):
    return {'kind': 'intent.selfHasCounter',
            'value': {'Counter': ident('prev_move'), 'Op': 'Equal', 'Value': n}}


def alive_at_least(n):
    return {'kind': 'intent.enemyAliveCount', 'value': {'Op': 'GreaterOrEqual', 'Value': n}}


def alive_equals(n):
    return {'kind': 'intent.enemyAliveCount', 'value': {'Op': 'Equal', 'Value': n}}


def ascension_at_least(n):
    return {'kind': 'intent.ascensionAtLeast', 'value': {'Value': n}}


def ally_missing(amount):
    return {'kind': 'intent.allyMissingHealth',
            'value': {'Op': 'GreaterOrEqual', 'Value': amount}}


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    ids = {m['Id'] for m in doc['Monsters']}
    assert 'centurion' not in ids and 'mystic' not in ids

    # ── Centurion 的三招 ────────────────────────────────────────────────────────────────────
    centurion_actions = [
        action('centurion.slash', 'Slash', 'Attack', 'Slash — 12 damage',
               sequence(damage(12) + history(SLASH)),
               asc=[(2, sequence(damage(14) + history(SLASH)))]),
        # `Protect`：Mystic 活着 ⇒ 它得 15 块；独自 ⇒ 自己得 15 块（wiki 明写了两半）。
        action('centurion.protect', 'Protect', 'Defend', 'Protect — Mystic gains 15 Block',
               conditional(
                   alive_equals(1),
                   sequence([block_self(15)] + history(PROTECT)),
                   sequence([block_to(sel_allies_with_definition('mystic'), 15)]
                             + history(PROTECT))),
               asc=[(17, conditional(
                   alive_equals(1),
                   sequence([block_self(20)] + history(PROTECT)),
                   sequence([block_to(sel_allies_with_definition('mystic'), 20)]
                             + history(PROTECT))))]),
        action('centurion.fury', 'Fury', 'Attack', 'Fury — 6×3 damage',
               sequence(damage(6, times=3) + history(FURY)),
               asc=[(2, sequence(damage(7, times=3) + history(FURY)))]),
    ]

    centurion_rules = [
        # Mystic 活着：65% Slash / 35% Protect，且任何一招不能连三次。
        rule([alive_at_least(2), prev_move_is(SLASH), last_move_is(SLASH)], 96,
             'centurion.protect'),
        rule([alive_at_least(2), prev_move_is(PROTECT), last_move_is(PROTECT)], 95,
             'centurion.slash'),
        rule([alive_at_least(2)], 90,
             choice=[('centurion.slash', 65), ('centurion.protect', 35)]),
        # Mystic 死了：Protect 换成 Fury（同样不能连三次）。
        rule([alive_equals(1), prev_move_is(SLASH), last_move_is(SLASH)], 86,
             'centurion.fury'),
        rule([alive_equals(1), prev_move_is(FURY), last_move_is(FURY)], 85,
             'centurion.slash'),
        rule([alive_equals(1)], 80,
             choice=[('centurion.slash', 65), ('centurion.fury', 35)]),
        rule([], 10, 'centurion.slash'),
    ]
    centurion = {
        'Id': 'centurion',
        'NameKey': 'Centurion',
        'HpMin': 76,
        'HpMax': 80,
        'MaxHealth': 76,
        'MaxHealthAsc': [{'AscensionMin': 7, 'MaxHealth': 78}],
        'Actions': [ident('centurion.slash'), ident('centurion.protect'),
                    ident('centurion.fury')],
        'StartingStatuses': [],
        'IntentRules': centurion_rules,
        'Tier': 'Normal',
        'InvRef': 'wiki:Centurion_and_Mystic',
        'AiNote': ('wiki：Slash 12（A2 14）/ Protect（Mystic 得 15 块，独自时自己得）/ Fury 6×3'
                   '（A2 7×3，只在 Mystic 死后替代 Protect）；65/35，任一招不连三次（§313）。'),
        'Counters': [],
        'Spawn': True,
    }

    # ── Mystic 的三招 ──────────────────────────────────────────────────────────────────────
    mystic_actions = [
        action('mystic.attack', 'Attack', 'Attack', 'Attack — 8 damage, 2 Frail',
               sequence(damage(8) + [status_to(sel_event(), 'standard.frail', 2)]
                        + history(M_ATTACK)),
               asc=[(2, sequence(damage(9) + [status_to(sel_event(), 'standard.frail', 2)]
                                 + history(M_ATTACK)))]),
        action('mystic.buff', 'Buff', 'Buff', 'Buff — all enemies gain 2 Strength',
               sequence([status_to(sel_all_allies(), 'standard.strength', 2)]
                        + history(M_BUFF)),
               asc=[(2, sequence([status_to(sel_all_allies(), 'standard.strength', 3)]
                                 + history(M_BUFF))),
                    (17, sequence([status_to(sel_all_allies(), 'standard.strength', 4)]
                                  + history(M_BUFF)))]),
        action('mystic.heal', 'Heal', 'Buff', 'Heal — all enemies heal 16 HP',
               sequence([heal_to(sel_all_allies(), 16)] + history(M_HEAL)),
               asc=[(17, sequence([heal_to(sel_all_allies(), 20)] + history(M_HEAL)))]),
    ]

    mystic_rules = [
        # 有人缺 ≥16 血 ⇒ Heal，但**最多连两次**（`prev`/`last` 都是 Heal ⇒ 走下面的概率）。
        rule([ally_missing(16),
              {'kind': 'intent.not',
               'value': {'Condition': and_all([prev_move_is(M_HEAL), last_move_is(M_HEAL)])}},
              ], 96, 'mystic.heal'),
        # A17：Attack 不能连两次 ⇒ 上一次是 Attack 就只能 Buff。
        rule([ascension_at_least(17), last_move_is(M_ATTACK)], 94, 'mystic.buff'),
        # Attack / Buff 不能连三次。
        rule([prev_move_is(M_ATTACK), last_move_is(M_ATTACK)], 92, 'mystic.buff'),
        rule([prev_move_is(M_BUFF), last_move_is(M_BUFF)], 91, 'mystic.attack'),
        # 其余 60% Attack / 40% Buff（连治两次之后也落到这里）。
        rule([], 10, choice=[('mystic.attack', 60), ('mystic.buff', 40)]),
    ]
    mystic = {
        'Id': 'mystic',
        'NameKey': 'Mystic',
        'HpMin': 48,
        'HpMax': 56,
        'MaxHealth': 48,
        'MaxHealthAsc': [{'AscensionMin': 7, 'MaxHealth': 50}],
        'Actions': [ident('mystic.attack'), ident('mystic.buff'), ident('mystic.heal')],
        'StartingStatuses': [],
        'IntentRules': mystic_rules,
        'Tier': 'Normal',
        'InvRef': 'wiki:Centurion_and_Mystic',
        'AiNote': ('wiki：Attack 8 + 2 Frail（A2 9）/ Buff 全体 +2 力量（A2 3、A17 4）/ Heal 全体 16'
                   '（A17 20）；有敌人缺 ≥16 血时优先 Heal（最多连两次），否则 60/40，不连三次，'
                   'A17 起 Attack 不连两次（§313）。'),
        'Counters': [],
        'Spawn': True,
    }

    # ── 遭遇 + 池 ──────────────────────────────────────────────────────────────────────────
    def enemy_row(monster, position):
        return {
            'Id': monster['Id'],
            'MaxHealth': monster['MaxHealth'],
            'Actions': monster['Actions'],
            'StartingStatuses': monster['StartingStatuses'],
            'Position': position,
            'IntentRules': monster['IntentRules'],
            'DisplayName': monster['NameKey'],
            'Rolls': [],
            'Counters': [],
            'Spawn': True,
            'MaxHealthAsc': monster['MaxHealthAsc'],
        }

    encounter = {
        'Id': {'Value': 'enc_centurion_and_mystic'},
        'Enemies': [enemy_row(centurion, 0), enemy_row(mystic, 1)],
        'HeroResources': [{'Resource': ident('standard.energy'), 'Current': 3, 'Max': 3}],
        'HeroStartingStatuses': [],
        'TriggeredEffects': [],
        'HeroDisplayName': None,
        'CardsDrawnPerTurn': None,
    }
    assert not any(row['Id'] == 'enc_centurion_and_mystic'
                   for row in doc['EncounterTables'].get('Weak2', []))
    assert not any(e['Id']['Value'] == 'enc_centurion_and_mystic' for e in doc['Encounters'])

    doc['EnemyActions'].extend(centurion_actions + mystic_actions)
    doc['Monsters'].extend([centurion, mystic])
    doc['Encounters'].append(encounter)
    doc['EncounterTables']['Weak2'].append({'Id': 'enc_centurion_and_mystic', 'Weight': 30})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('monsters %d actions %d encounters %d weak2 %d'
          % (len(doc['Monsters']), len(doc['EnemyActions']), len(doc['Encounters']),
             len(doc['EncounterTables']['Weak2'])))


main()
