"""§312 Act 2 缺的两条里最重的一条：`standard.malleable` + Snake Plant（wiki 权重 6/29）。

## Malleable 是什么（wiki 两个来源）

`Malleable` 页：*"Upon receiving attack damage, gains X Block. Block gain increases as Malleable
is triggered. Resets at the start of your turn."*（另一句："The Block given grows by 1 and
resets at the end of the turn."）

所以语义是三条：
1. **只对攻击**（`damage.isAttack`）生效 —— 毒/失去生命不算（`plated_armor` 的 `eventAmount > 0`
   条件也是同一个口径：只有**掉血**的那次才算）；
2. 每次触发给 **X 块**，X 每次 **+1**（基数是层数）；
3. **每回合开始**把"+1 的增量"清零。

## 为什么可以纯内容

内核已经有这套零件：`DamageTaken` 触发器 + `damage.isAttack` 事实（Flying / Plated Armor 在用）、
`combatantStatusStacks`（Regen 在用）、`setCombatantCounter{Relative}`（Looter 的记账在用）。
唯一"新"的东西是一个**每战斗员计数器** `malleable_bonus` —— 计数器的语义内核早有（不必声明
在怪物行里：`stolen_gold` 就是这么用的）。

## Snake Plant（wiki `Snake Plant` 页 + `SlaySpireDB`）

* HP 75-79（A7 78-82），开场 Malleable 3；
* 两招：`Chomp Chomp` 7×3（A2 8×3）、`Enfeebling Spores`（Frail 2 + Weak 2）；
* 每回合 65% / 35%；**不能连用 Chomp 三次**、**不能连用 Spores 两次**；
* A17 起第一次 Spores 之后进入固定 Chomp/Chomp/Spores —— 这条**不做**（见 `docs/sts-wiki-gap.md`
  §D.3.2：那是"出招序列被改写"，本移植的 A17 只做到禁令那一层，与其它怪物一致）。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

BONUS_COUNTER = 'malleable_bonus'


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


def counter(counter_id, selector=None):
    return {'kind': 'combatantCounter',
            'value': {'Selector': selector or sel_source(), 'CounterId': counter_id}}


def status_stacks(status_id):
    return {'kind': 'combatantStatusStacks',
            'value': {'Selector': sel_source(), 'StatusId': ident(status_id)}}


def add(left, right):
    return {'kind': 'add', 'value': {'Left': left, 'Right': right}}


def compare(left, right, op='Greater'):
    return {'kind': 'compare', 'value': {'Left': left, 'Right': right, 'Op': op}}


def and_all(conditions):
    result = conditions[0]
    for condition in conditions[1:]:
        result = {'kind': 'and', 'value': {'Left': result, 'Right': condition}}
    return result


def damage(amount, target='event', times=1):
    children = []
    for _ in range(times):
        children.append({'kind': 'node.dealDamage',
                         'value': {'TargetSelector': sel_event() if target == 'event'
                                   else sel_source(),
                                   'Amount': const(amount), 'ResultKey': None,
                                   'IgnoresBlock': False, 'Element': None}})
    return children


def status_node(definition, stacks):
    return {'kind': 'node.applyStatus',
            'value': {'TargetSelector': sel_event(),
                      'StatusDefinitionId': ident(definition),
                      'Stacks': const(stacks), 'Duration': None, 'ResultKey': None}}


def block_node(amount_expr):
    return {'kind': 'node.gainBlock',
            'value': {'TargetSelector': sel_source(), 'Amount': amount_expr,
                      'ResultKey': None}}


def set_counter(counter_id, amount, relative=False):
    return {'kind': 'node.setCombatantCounter',
            'value': {'TargetSelector': sel_source(), 'CounterId': ident(counter_id),
                      'Amount': amount if isinstance(amount, dict) else const(amount),
                      'Relative': relative}}


def history(move):
    """`prev_move = last_move; last_move = move`（§195.5 的记账，检查器会把它剥掉）。"""
    return [set_counter('prev_move', counter('last_move')),
            set_counter('last_move', move)]


def sequence(children):
    return {'kind': 'node.sequence', 'value': {'Children': children}}


def program(root):
    return {'Id': ident('(unnamed)'), 'Root': root, 'MaxNodeDepth': 64, 'MaxProgramSteps': 1024}


def action(action_id, name, intent_kind, label, root, asc_root=None):
    row = {'Id': action_id, 'PackageId': 'sts', 'NameKey': name,
           'DescriptionKey': label, 'Intent': {'Kind': intent_kind, 'Label': label},
           'Program': program(root)}
    if asc_root is not None:
        row['ProgramAsc'] = [{'AscensionMin': 2, 'Program': program(asc_root)}]
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


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    statuses = {s['Id']: s for s in doc['Statuses']}
    assert 'standard.malleable' not in statuses

    # ── 1. `standard.malleable` ────────────────────────────────────────────────────────────
    hit_condition = and_all([
        {'kind': 'event.bool', 'value': {'FieldKey': 'damage.isAttack'}},
        compare({'kind': 'eventAmount', 'value': {}}, const(0), 'Greater'),
    ])
    malleable = {
        'Id': 'standard.malleable',
        'PackageId': 'sts',
        'NameKey': 'Malleable',
        'DescriptionKey': ('Upon receiving attack damage, gains X Block. Block gain increases as '
                           'Malleable is triggered. Resets at the start of your turn.'),
        'Polarity': 'Buff',
        'UsesStacks': True,
        'UsesDuration': False,
        'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': ['buff'],
        'PassiveModifiers': [],
        'Triggers': [
            {
                'Event': 'DamageTaken',
                'Program': program({
                    'kind': 'node.conditional',
                    'value': {
                        'Condition': hit_condition,
                        'Then': sequence([
                            # 这次给的是 **层数 + 本回合已经触发过几次**。
                            block_node(add(status_stacks('standard.malleable'),
                                           counter(BONUS_COUNTER))),
                            # 然后这次触发让下一次多 1 块。
                            set_counter(BONUS_COUNTER, 1, relative=True),
                        ]),
                        'Else': None,
                    },
                }),
            },
            {
                'Event': 'TurnStarted',
                'Program': program(set_counter(BONUS_COUNTER, 0)),
            },
        ],
    }

    # ── 2. Snake Plant 的两招 ──────────────────────────────────────────────────────────────
    chomp = action(
        'snake_plant.chomp_chomp', 'Chomp Chomp', 'Attack', 'Chomp Chomp — 7×3 damage',
        sequence(damage(7, times=3) + history(1)),
        asc_root=sequence(damage(8, times=3) + history(1)),
    )
    spores = action(
        'snake_plant.enfeebling_spores', 'Enfeebling Spores', 'Debuff',
        'Enfeebling Spores — 2 Frail, 2 Weak',
        sequence([status_node('standard.frail', 2), status_node('standard.weak', 2)] + history(2)),
    )

    # ── 3. Snake Plant ────────────────────────────────────────────────────────────────────
    plant_rules = [
        # 不能连用 Chomp 三次：上一次和上上次都是 Chomp ⇒ 只能 Spores。
        rule([prev_move_is(1), last_move_is(1)], 90, 'snake_plant.enfeebling_spores'),
        # 不能连用 Spores 两次。
        rule([last_move_is(2)], 80, 'snake_plant.chomp_chomp'),
        # 其余 65/35。
        rule([], 10, choice=[('snake_plant.chomp_chomp', 65),
                             ('snake_plant.enfeebling_spores', 35)]),
    ]
    plant = {
        'Id': 'snake_plant',
        'NameKey': 'Snake Plant',
        'HpMin': 75,
        'HpMax': 79,
        'MaxHealth': 75,
        'MaxHealthAsc': [{'AscensionMin': 7, 'MaxHealth': 78}],
        'Actions': [ident('snake_plant.chomp_chomp'), ident('snake_plant.enfeebling_spores')],
        'StartingStatuses': [{'StatusDefinitionId': ident('standard.malleable'), 'Stacks': 3}],
        'IntentRules': plant_rules,
        'Tier': 'Normal',
        'InvRef': 'wiki:The_City#Hard_Pool',
        'AiNote': ('wiki：Malleable 3；Chomp Chomp 7×3（A2 8×3）/ Enfeebling Spores（Frail 2 + Weak 2）；'
                   '65/35，不能连 Chomp 三次、不能连 Spores 两次（§312）。'
                   'A17 的"第一次 Spores 之后改成固定序列"没做 —— 与其它怪物的 A17 只做到禁令一致。'),
        'Counters': [],
        'Spawn': True,
    }

    # ── 4. 遭遇 + 池 ───────────────────────────────────────────────────────────────────────
    def enemy_row(monster):
        return {
            'Id': monster['Id'],
            'MaxHealth': monster['MaxHealth'],
            'Actions': monster['Actions'],
            'StartingStatuses': monster['StartingStatuses'],
            'Position': None,
            'IntentRules': monster['IntentRules'],
            'DisplayName': monster['NameKey'],
            'Rolls': [],
            'Counters': [],
            'Spawn': True,
            'MaxHealthAsc': monster['MaxHealthAsc'],
        }

    encounter = {
        'Id': {'Value': 'enc_snake_plant'},
        'Enemies': [enemy_row(plant)],
        'HeroResources': [{'Resource': ident('standard.energy'), 'Current': 3, 'Max': 3}],
        'HeroStartingStatuses': [],
        'TriggeredEffects': [],
        'HeroDisplayName': None,
        'CardsDrawnPerTurn': None,
    }
    assert not any(e['Id']['Value'] == 'enc_snake_plant' for e in doc['Encounters'])

    doc['Statuses'].append(malleable)
    doc['EnemyActions'].extend([chomp, spores])
    doc['Monsters'].append(plant)
    doc['Encounters'].append(encounter)
    doc['EncounterTables']['Weak2'].append({'Id': 'enc_snake_plant', 'Weight': 30})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('statuses %d actions %d monsters %d encounters %d weak2 %d'
          % (len(doc['Statuses']), len(doc['EnemyActions']), len(doc['Monsters']),
             len(doc['Encounters']), len(doc['EncounterTables']['Weak2'])))


main()
