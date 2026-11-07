"""§276 L 史莱姆（第三版）：动作**维护 `last_move`/`prev_move`**，AI 规则按 wiki 逐条写。

前两版的错（都记下来）：
1. 追加了**同 id 的第二行动作**来表示 A17 档 —— id index 会重复。A17 是 `ProgramAsc`。
2. 动作**没有写 `last_move`/`prev_move`** —— 而"不连招"的规则全靠读它们。
   症状会是"规则永远不触发"（`last_move` 恒 0），而且**没有任何闸门会红**：
   随机权重那一条照样能选出招式。
3. A2 档用一个复合布尔表达式决定"要不要附带 Slimed"，读的人无法验证 —— 改成显式。

## wiki（wiki.gg `Slimes` + dood.gg 一致）

| 怪 | HP | A7 | 招式（base / A2） |
|---|---|---|---|
| Spike Slime (L) | 64–70 | 67–73 | Lick 2 Frail（A17: 3）；Flame Tackle 16→**18** + 2 Slimed |
| Acid Slime (L) | 65–69 | 68–72 | Corrosive Spit 11→**12** + 2 Slimed；Lick 2 Weak；Tackle 16→**18** |

AI：
* Spike (L)：30% Flame Tackle / 70% Lick；**不能连 3 次同一招**；A17 起 **Lick 不能连两次**。
* Acid (L)：30% Spit / 40% Tackle / 30% Lick；**Tackle 不能连两次**；其它不能连三次；
  **A17** 把 Tackle 与 Lick 的权重对调（30/30/40），且**Lick 不能连两次**。
* Split：HP ≤ 50% ⇒ 分裂 2 只 M，血量 = 当前血（详见 `standard.split_spike_l/acid_l`）。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

TARGET = {'kind': 'sel.eventTarget',
          'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'EventTarget'}}
SOURCE = {'kind': 'sel.source',
          'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'Source'}}


def const(n):
    return {'kind': 'const', 'value': {'Value': n}}


def counter(name):
    return {'kind': 'combatantCounter', 'value': {'Selector': SOURCE, 'CounterId': name}}


def seq(*children):
    return {'kind': 'node.sequence', 'value': {'Children': list(children)}}


def damage(n):
    return {'kind': 'node.dealDamage', 'value': {
        'TargetSelector': TARGET, 'Amount': const(n), 'ResultKey': None,
        'IgnoresBlock': False, 'Element': None}}


def apply_status(sid, stacks):
    return {'kind': 'node.applyStatus', 'value': {
        'TargetSelector': TARGET, 'StatusDefinitionId': {'value': sid},
        'Stacks': const(stacks), 'DurationTurns': 0, 'Charges': 0, 'ResultKey': None}}


def dump_card(card, count):
    # 键名是 （既有写法），不是  —— 我第一版写错了，内容门的 walker 直接 KeyError。
    return {'kind': 'node.createCardInstance', 'value': {
        'CardDefinitionId': {'value': card}, 'Count': const(count),
        'TargetSelector': TARGET, 'ToZone': 'DiscardPile', 'ResultKey': None}}


def set_counter(name, amount, relative=False):
    return {'kind': 'node.setCombatantCounter', 'value': {
        'TargetSelector': SOURCE, 'CounterId': {'value': name},
        'Amount': amount, 'Relative': relative}}


def bookkeeping(marker):
    """每个动作的尾巴：`prev_move = last_move`，然后 `last_move = marker`（既有的写法）。"""
    return (set_counter('prev_move', counter('last_move')),
            set_counter('last_move', const(marker)))


def program(root):
    return {'Id': {'Value': '(unnamed)'}, 'Root': root,
            'MaxNodeDepth': 64, 'MaxProgramSteps': 1024}


def action(aid, name, kind, label, body, marker, asc=()):
    row = {
        'Id': aid, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': label,
        'Intent': {'Kind': kind, 'Label': label},
        'Program': program(seq(*body, *bookkeeping(marker))),
    }
    if asc:
        row['ProgramAsc'] = [{'AscensionMin': at, 'Program': program(seq(*body_, *bookkeeping(marker)))}
                             for at, body_ in asc]
    return row


def split_status(sid, form):
    condition = {'kind': 'compare', 'value': {
        'Op': 'LessOrEqual',
        'Left': {'kind': 'multiply', 'value': {
            'Left': {'kind': 'currentHealth', 'value': {'Selector': SOURCE}},
            'Right': const(2)}},
        'Right': {'kind': 'maxHealth', 'value': {'Selector': SOURCE}},
    }}
    spawn = {'kind': 'node.createCombatant', 'value': {
        'DefinitionId': form, 'TeamId': 'enemy',
        'Health': {'kind': 'currentHealth', 'value': {'Selector': SOURCE}}}}
    # ⚠️ `destroyCombatant` **最后**：先删就没有"当前血"可继承。
    destroy = {'kind': 'node.destroyCombatant', 'value': {
        'TargetSelector': {'kind': 'sel.sourceIncludingDowned',
                           'value': {'Cardinality': 'ZeroOrOne',
                                     'RequiredContextCapabilities': 'Source'}}}}
    return {
        'Id': sid, 'PackageId': 'sts', 'NameKey': 'Split',
        'DescriptionKey': 'When its HP is at or below 50%, it splits into 2 smaller Slimes '
                          'with its current HP.',
        'Polarity': 'Buff', 'UsesStacks': False, 'UsesDuration': False, 'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance', 'Tags': ['buff'],
        'PassiveModifiers': [],
        'Triggers': [{'Event': 'DamageTaken', 'Program': program({
            'kind': 'node.conditional',
            'value': {'Condition': condition, 'Then': seq(spawn, spawn, destroy), 'Else': None},
        })}],
    }


def when(*conditions):
    chained = list(conditions)
    return chained[0] if len(chained) == 1 else {
        'kind': 'intent.allOf', 'value': {'Conditions': chained}}


def last_is(marker):
    return {'kind': 'intent.selfHasCounter', 'value': {
        'Counter': {'value': 'last_move'}, 'Op': 'Equal', 'Value': marker}}


def prev_is(marker):
    return {'kind': 'intent.selfHasCounter', 'value': {
        'Counter': {'value': 'prev_move'}, 'Op': 'Equal', 'Value': marker}}


def asc_at(level):
    return {'kind': 'intent.ascensionAtLeast', 'value': {'Value': level}}


def pick(priority, condition, *, one=None, choice=None):
    row = {'Condition': condition, 'Priority': priority}
    if choice:
        row['Choice'] = [{'Action': {'value': a}, 'Weight': w} for a, w in choice]
    else:
        row['Action'] = {'value': one}
    return row


# 招式 → 计数器标记（`last_move` 的值）
SPIKE_LICK = 2
SPIKE_TACKLE = 1
ACID_SPIT = 1
ACID_TACKLE = 2
ACID_LICK = 3

ACTIONS = [
    action('spike_slime_l.lick', 'Lick', 'Debuff', 'Lick - 2 Frail',
           [apply_status('standard.frail', 2)], SPIKE_LICK,
           asc=[(17, [apply_status('standard.frail', 3)])]),
    action('spike_slime_l.flame_tackle', 'Flame Tackle', 'Attack',
           'Flame Tackle - 16 damage, 2 Slimed',
           [damage(16), dump_card('slimed', 2)], SPIKE_TACKLE,
           asc=[(2, [damage(18), dump_card('slimed', 2)])]),
    action('acid_slime_l.corrosive_spit', 'Corrosive Spit', 'Attack',
           'Corrosive Spit - 11 damage, 2 Slimed',
           [damage(11), dump_card('slimed', 2)], ACID_SPIT,
           asc=[(2, [damage(12), dump_card('slimed', 2)])]),
    action('acid_slime_l.lick', 'Lick', 'Debuff', 'Lick - 2 Weak',
           [apply_status('standard.weak', 2)], ACID_LICK),
    action('acid_slime_l.tackle', 'Tackle', 'Attack', 'Tackle - 16 damage',
           [damage(16)], ACID_TACKLE, asc=[(2, [damage(18)])]),
]


def spike_rules():
    return [
        # A17：Lick 不能连两次 ⇒ 上回合 Lick 就换 Flame Tackle。
        pick(72, when(last_is(SPIKE_LICK), asc_at(17)), one='spike_slime_l.flame_tackle'),
        # 不能连三次同一招。
        pick(70, when(last_is(SPIKE_TACKLE), prev_is(SPIKE_TACKLE)), one='spike_slime_l.lick'),
        pick(70, when(last_is(SPIKE_LICK), prev_is(SPIKE_LICK)),
             one='spike_slime_l.flame_tackle'),
        # 30% Flame Tackle / 70% Lick。
        pick(10, when(), choice=[('spike_slime_l.flame_tackle', 30), ('spike_slime_l.lick', 70)]),
    ]


def acid_rules():
    return [
        # A17：Lick 不能连两次。
        pick(74, when(last_is(ACID_LICK), asc_at(17)),
             choice=[('acid_slime_l.corrosive_spit', 50), ('acid_slime_l.tackle', 50)]),
        # Tackle 不能连两次（任一升阶都一样）。
        pick(73, when(last_is(ACID_TACKLE)),
             choice=[('acid_slime_l.corrosive_spit', 50), ('acid_slime_l.lick', 50)]),
        # 其它招不能连三次。
        pick(70, when(last_is(ACID_SPIT), prev_is(ACID_SPIT)),
             choice=[('acid_slime_l.tackle', 50), ('acid_slime_l.lick', 50)]),
        pick(70, when(last_is(ACID_LICK), prev_is(ACID_LICK)),
             choice=[('acid_slime_l.corrosive_spit', 50), ('acid_slime_l.tackle', 50)]),
        # 基础 30/40/30。
        pick(10, when(), choice=[('acid_slime_l.corrosive_spit', 30),
                                 ('acid_slime_l.tackle', 40), ('acid_slime_l.lick', 30)]),
        # A17 把 Tackle 与 Lick 对调（40 ⇄ 30）：单独一条，优先级低于上面所有约束。
        pick(9, when(asc_at(17)), choice=[('acid_slime_l.corrosive_spit', 30),
                                          ('acid_slime_l.tackle', 30),
                                          ('acid_slime_l.lick', 40)]),
    ]


def monster(mid, name, hp_min, hp_max, max_hp, asc_hp, status_id, actions, rules):
    return {
        'Id': mid, 'NameKey': name, 'HpMin': hp_min, 'HpMax': hp_max, 'MaxHealth': max_hp,
        'Actions': [{'value': a} for a in actions],
        'StartingStatuses': [{'StatusDefinitionId': {'value': status_id}, 'Stacks': 1}],
        'IntentRules': rules, 'Tier': 'A', 'InvRef': 'inv:§4.1',
        'AiNote': '§276：加权选择 + 不连招（读 last_move/prev_move）+ 50% 分裂',
        'Counters': [], 'Spawn': True,
        'MaxHealthAsc': [{'AscensionMin': 7, 'MaxHealth': asc_hp}],
    }


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    ids = lambda row: row['Id']['Value'] if isinstance(row.get('Id'), dict) else row['Id']

    # 幂等：先清掉这一节可能留下的行
    drop_monsters = {'spike_slime_l', 'acid_slime_l'}
    doc['Monsters'] = [m for m in doc['Monsters'] if ids(m) not in drop_monsters]
    doc['Statuses'] = [s for s in doc['Statuses']
                       if s['Id'] not in ('standard.split_spike_l', 'standard.split_acid_l')]
    doc['EnemyActions'] = [a for a in doc['EnemyActions']
                           if not str(ids(a)).startswith(('spike_slime_l.', 'acid_slime_l.'))]
    doc['Encounters'] = [e for e in doc['Encounters']
                         if ids(e) not in ('enc_spike_slime_l', 'enc_acid_slime_l')]
    doc['EncounterTables']['Weak'] = [
        r for r in doc['EncounterTables']['Weak']
        if r['Id'] not in ('enc_spike_slime_l', 'enc_acid_slime_l')]

    doc['Statuses'].append(split_status('standard.split_spike_l', 'spike_slime_m'))
    doc['Statuses'].append(split_status('standard.split_acid_l', 'acid_slime_m'))
    doc['EnemyActions'].extend(ACTIONS)

    doc['Monsters'].append(monster(
        'spike_slime_l', 'Spike Slime (L)', 64, 70, 64, 67, 'standard.split_spike_l',
        ['spike_slime_l.lick', 'spike_slime_l.flame_tackle'], spike_rules()))
    doc['Monsters'].append(monster(
        'acid_slime_l', 'Acid Slime (L)', 65, 69, 65, 68, 'standard.split_acid_l',
        ['acid_slime_l.corrosive_spit', 'acid_slime_l.lick', 'acid_slime_l.tackle'],
        acid_rules()))

    # 原作 `Large Slime` = 随机 Spike L 或 Acid L；静态内容拆两条（各权重 7 = 原来的 2 折半）。
    for eid, mid in (('enc_spike_slime_l', 'spike_slime_l'),
                     ('enc_acid_slime_l', 'acid_slime_l')):
        roster = next(m for m in doc['Monsters'] if ids(m) == mid)
        doc['Encounters'].append({
            'Id': {'Value': eid},
            'Enemies': [{
                'Id': mid,
                'MaxHealth': roster['MaxHealth'],
                'Actions': roster['Actions'],
                'StartingStatuses': roster['StartingStatuses'],
                'Position': 0,
                'IntentRules': roster['IntentRules'],
                'DisplayName': roster['NameKey'],
                'Rolls': [],
                'Counters': [],
                'Spawn': True,
                'MaxHealthAsc': roster['MaxHealthAsc'],
            }],
            'HeroResources': [{'Resource': {'value': 'standard.energy'}, 'Current': 3, 'Max': 3}],
            'HeroStartingStatuses': [],
            'TriggeredEffects': [],
            'HeroDisplayName': None,
            'CardsDrawnPerTurn': None,
        })
        doc['EncounterTables']['Weak'].append({'Id': eid, 'Weight': 7})

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('monsters %d / actions %d / statuses %d / encounters %d / Weak %d' % (
        len(doc['Monsters']), len(doc['EnemyActions']), len(doc['Statuses']),
        len(doc['Encounters']), len(doc['EncounterTables']['Weak'])))


main()
