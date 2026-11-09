"""§317 Transient：Act 3 的最后一条普通遭遇（10 / 10）。

wiki（`Transient` 页 + 两个独立攻略页，数字一致）：

| 项 | wiki |
|---|---|
| HP | **999**（不随升阶变） |
| `Fading` | **5** 回合后自己消失（**A17：6**） |
| `Shifting` | 每受一次伤害，**临时**失去等量力量（回合末还回来） |
| Attack | 第 1 回合 30（A2：40），**每回合 +10** |

三条规则各用一种既有零件，都不需要新内核分支：

1. `Fading`：层数就是时钟 —— `TurnEnded` 触发器，剩 1 层就 `destroyCombatant(self)`，
   否则 `modifyStatusStacks(-1)`。
2. `Shifting`：`DamageTaken` 触发 —— `applyStatus(strength, -eventAmount)` +
   `applyStatus(regain_strength, eventAmount)`。「回合末还回来」这半条用 §219 的
   `standard.regain_strength`（Dark Shackles 就是它）。
3. 伤害递增：直接用表达式 `20 + 10 × roundNumber`（第 1 回合 30、第 2 回合 40……），
   A2 档再加 10。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


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


def add(left, right):
    return {'kind': 'add', 'value': {'Left': left, 'Right': right}}


def multiply(left, right):
    return {'kind': 'multiply', 'value': {'Left': left, 'Right': right}}


def negate(inner):
    return {'kind': 'negate', 'value': {'Inner': inner}}


def compare(left, right, op):
    return {'kind': 'compare', 'value': {'Left': left, 'Right': right, 'Op': op}}


def event_amount():
    return {'kind': 'eventAmount', 'value': {}}


def round_number():
    return {'kind': 'roundNumber', 'value': {}}


def status_stacks(status_id):
    return {'kind': 'combatantStatusStacks',
            'value': {'Selector': sel_source(), 'StatusId': ident(status_id)}}


def sequence(children):
    return {'kind': 'node.sequence', 'value': {'Children': children}}


def conditional(condition, then, otherwise=None):
    return {'kind': 'node.conditional',
            'value': {'Condition': condition, 'Then': then, 'Else': otherwise}}


def apply_status(selector, definition, stacks, duration=0, charges=0):
    return {'kind': 'node.applyStatus',
            'value': {'TargetSelector': selector, 'StatusDefinitionId': ident(definition),
                      'Stacks': stacks, 'DurationTurns': duration, 'Charges': charges,
                      'ResultKey': None}}


def modify_status(definition, delta):
    return {'kind': 'node.modifyStatusStacks',
            'value': {'TargetSelector': sel_source(), 'StatusDefinitionId': ident(definition),
                      'Delta': delta}}


def destroy_self():
    return {'kind': 'node.destroyCombatant', 'value': {'TargetSelector': sel_source()}}


def damage(amount):
    return {'kind': 'node.dealDamage',
            'value': {'TargetSelector': sel_event(), 'Amount': amount, 'ResultKey': None,
                      'IgnoresBlock': False, 'Element': None}}


def program(root):
    return {'Id': ident('(unnamed)'), 'Root': root, 'MaxNodeDepth': 64, 'MaxProgramSteps': 1024}


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    statuses = {s['Id']: s for s in doc['Statuses']}
    assert 'standard.fading' not in statuses and 'standard.shifting' not in statuses
    assert 'transient' not in {m['Id'] for m in doc['Monsters']}

    # ── 1. `standard.fading` ───────────────────────────────────────────────────────────────
    fading = {
        'Id': 'standard.fading',
        'PackageId': 'sts',
        'NameKey': 'Fading',
        'DescriptionKey': 'Dies in X turns.',
        'Polarity': 'Buff',
        'UsesStacks': True,
        'UsesDuration': False,
        'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': ['buff'],
        'PassiveModifiers': [],
        'Triggers': [{
            'Event': 'TurnEnded',
            'Program': program(conditional(
                # 剩 1 层 ⇒ 这一回合结束就消失（不是"减到 0 再消失"：减到 0 的实例会被删掉，
                # 那时触发器已经跟着状态一起没了，永远等不到"死"那一步）。
                compare(status_stacks('standard.fading'), const(1), 'LessOrEqual'),
                sequence([destroy_self()]),
                modify_status('standard.fading', const(-1)),
            )),
        }],
    }

    # ── 2. `standard.shifting` ─────────────────────────────────────────────────────────────
    shifting = {
        'Id': 'standard.shifting',
        'PackageId': 'sts',
        'NameKey': 'Shifting',
        'DescriptionKey': ('Upon losing HP, loses that much Strength until the end of the turn.'),
        'Polarity': 'Buff',
        'UsesStacks': False,
        'UsesDuration': False,
        'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': ['buff'],
        'PassiveModifiers': [],
        'Triggers': [{
            'Event': 'DamageTaken',
            'Program': program(conditional(
                compare(event_amount(), const(0), 'Greater'),
                sequence([
                    # 力量立刻减等量；回合末由 `regain_strength` 加回来（§219 的同一个零件）。
                    apply_status(sel_source(), 'standard.strength', negate(event_amount())),
                    apply_status(sel_source(), 'standard.regain_strength', event_amount()),
                ]),
            )),
        }],
    }

    # ── 3. Transient ──────────────────────────────────────────────────────────────────────
    attack_program = sequence([damage(add(const(20), multiply(round_number(), const(10))))])
    attack = {
        'Id': 'transient.attack',
        'PackageId': 'sts',
        'NameKey': 'Attack',
        'DescriptionKey': 'Attack - 20 + 10×turn damage',
        'Intent': {'Kind': 'Attack', 'Label': 'Attack - 20 + 10×turn damage'},
        'Program': program(attack_program),
        # A2：整条 +10（第 1 回合 40 而不是 30）。
        'ProgramAsc': [{'AscensionMin': 2, 'Program': program(sequence([
            damage(add(const(30), multiply(round_number(), const(10)))),
        ]))}],
    }

    transient = {
        'Id': 'transient',
        'NameKey': 'Transient',
        'HpMin': 999,
        'HpMax': 999,
        'MaxHealth': 999,
        'Actions': [ident('transient.attack')],
        'StartingStatuses': [
            {'StatusDefinitionId': ident('standard.fading'), 'Stacks': 5,
             'Asc': [{'AscensionMin': 17, 'Stacks': 6}]},
            {'StatusDefinitionId': ident('standard.shifting'), 'Stacks': 1},
        ],
        'IntentRules': [],
        'Tier': 'Normal',
        'InvRef': 'wiki:Transient',
        'AiNote': ('wiki：HP **999**（不随升阶变）；`Fading 5`（A17: 6）；`Shifting`（受伤时临时'
                   '失去等量力量，回合末还回来）；Attack 第 1 回合 30（A2: 40），每回合 +10（§317）。'),
        'Counters': [],
        'Spawn': True,
    }

    encounter = {
        'Id': {'Value': 'enc_transient'},
        'Enemies': [{
            'Id': 'transient',
            'MaxHealth': 999,
            'Actions': transient['Actions'],
            'StartingStatuses': transient['StartingStatuses'],
            'Position': None,
            'IntentRules': [],
            'DisplayName': 'Transient',
            'Rolls': [],
            'Counters': [],
            'Spawn': True,
        }],
        'HeroResources': [{'Resource': ident('standard.energy'), 'Current': 3, 'Max': 3}],
        'HeroStartingStatuses': [],
        'TriggeredEffects': [],
        'HeroDisplayName': None,
        'CardsDrawnPerTurn': None,
    }

    doc['Statuses'].extend([fading, shifting])
    doc['EnemyActions'].append(attack)
    doc['Monsters'].append(transient)
    doc['Encounters'].append(encounter)
    doc['EncounterTables']['Weak3'].append({'Id': 'enc_transient', 'Weight': 10})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('statuses %d monsters %d actions %d encounters %d weak3 %d'
          % (len(doc['Statuses']), len(doc['Monsters']), len(doc['EnemyActions']),
             len(doc['Encounters']), len(doc['EncounterTables']['Weak3'])))


main()
