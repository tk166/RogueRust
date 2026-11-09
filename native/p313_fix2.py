"""§313（五）：规则重建 —— `intent.not` 的内层必须是 **`intent.allOf`**，不是表达式的 `and`。

丢掉的教训：我第一次把 not 的内层写成 `{"kind": "and"}`（那是**表达式**的布尔与），而条件求值器
只认识 `intent.*` ⇒ `UnknownConditionKind`。而它在**遭遇的敌人记录副本**里（我改 Monster 时
没同步那一份），于是"改完还是红"。

这个脚本从一份干净的定义重建 Centurion / Mystic 的 IntentRules，并**同时**写进 `Monsters`
与 `enc_centurion_and_mystic` 的敌人记录（两处必须是同一份规则 —— 它们是同一只怪）。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

SLASH, PROTECT, FURY = 1, 2, 3
M_ATTACK, M_BUFF, M_HEAL = 1, 2, 3


def counter_is(name, value):
    return {'kind': 'intent.selfHasCounter',
            'value': {'Counter': {'value': name}, 'Op': 'Equal', 'Value': value}}


def rule(conditions, priority, action=None, choice=None):
    row = {'Condition': {'kind': 'intent.allOf', 'value': {'Conditions': conditions}},
           'Priority': priority}
    if action is not None:
        row['Action'] = {'value': action}
    if choice is not None:
        row['Choice'] = [{'Action': {'value': a}, 'Weight': w} for a, w in choice]
    return row


def centurion_rules():
    alive2 = {'kind': 'intent.enemyAliveCount',
              'value': {'Op': 'GreaterOrEqual', 'Value': 2}}
    alive1 = {'kind': 'intent.enemyAliveCount', 'value': {'Op': 'Equal', 'Value': 1}}
    return [
        # Mystic 活着：65% Slash / 35% Protect，任一招不连三次。
        rule([alive2, counter_is('prev_move', SLASH), counter_is('last_move', SLASH)], 96,
             'centurion.protect'),
        rule([alive2, counter_is('prev_move', PROTECT), counter_is('last_move', PROTECT)], 95,
             'centurion.slash'),
        rule([alive2], 90,
             choice=[('centurion.slash', 65), ('centurion.protect', 35)]),
        # Mystic 死了：Protect 换成 Fury（同样不连三次）。
        rule([alive1, counter_is('prev_move', SLASH), counter_is('last_move', SLASH)], 86,
             'centurion.fury'),
        rule([alive1, counter_is('prev_move', FURY), counter_is('last_move', FURY)], 85,
             'centurion.slash'),
        rule([alive1], 80, choice=[('centurion.slash', 65), ('centurion.fury', 35)]),
        rule([], 10, 'centurion.slash'),
    ]


def mystic_rules():
    missing = {'kind': 'intent.allyMissingHealth',
               'value': {'Op': 'GreaterOrEqual', 'Value': 16}}
    # 「连续两次 Heal 之后不许再 Heal」——`not(prev==Heal 且 last==Heal)`。
    # ⚠️ 内层必须是 **`intent.allOf`**：`and` 是**表达式**的布尔与，条件求值器不认识它。
    not_two_heals = {
        'kind': 'intent.not',
        'value': {'Condition': {
            'kind': 'intent.allOf',
            'value': {'Conditions': [counter_is('prev_move', M_HEAL),
                                     counter_is('last_move', M_HEAL)]},
        }},
    }
    return [
        rule([missing, not_two_heals], 96, 'mystic.heal'),
        # A17：Attack 不能连两次。
        rule([{'kind': 'intent.ascensionAtLeast', 'value': {'Value': 17}},
              counter_is('last_move', M_ATTACK)], 94, 'mystic.buff'),
        # Attack / Buff 不能连三次。
        rule([counter_is('prev_move', M_ATTACK), counter_is('last_move', M_ATTACK)], 92,
             'mystic.buff'),
        rule([counter_is('prev_move', M_BUFF), counter_is('last_move', M_BUFF)], 91,
             'mystic.attack'),
        rule([], 10, choice=[('mystic.attack', 60), ('mystic.buff', 40)]),
    ]


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    centurion = next(m for m in doc['Monsters'] if m['Id'] == 'centurion')
    mystic = next(m for m in doc['Monsters'] if m['Id'] == 'mystic')
    centurion['IntentRules'] = centurion_rules()
    mystic['IntentRules'] = mystic_rules()

    encounter = next(e for e in doc['Encounters']
                     if e['Id']['Value'] == 'enc_centurion_and_mystic')
    encounter['Enemies'][0]['IntentRules'] = copy(centurion['IntentRules'])
    encounter['Enemies'][1]['IntentRules'] = copy(mystic['IntentRules'])
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('rules rebuilt in both the roster and the encounter record')


def copy(value):
    return json.loads(json.dumps(value))


main()
