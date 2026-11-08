"""§294 A1 内容：`standard.the_abacus` 与 `standard.sundial`（都用 `DeckShuffled` 触发器）。

两个程序都抄**已有的、被测过的**形状：

* `the_abacus` 抄 `standard.nunchaku` 的**触发信封**（`Event` + `Program`），只是把
  `gainResource` 换成 `gainBlock`，并去掉"每 N 次"那半个条件；
* `sundial` 抄 `nunchaku` 的 **`remainder(counter, N) == N-1`** 判断 + 第二个"自增"条件
  （两次 `setCombatantCounter`，一次在条件里读、一次无条件加）。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def sel_source():
    return {
        'kind': 'sel.source',
        'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'Source'},
    }


def counter(counter_id):
    return {
        'kind': 'combatantCounter',
        'value': {'Selector': sel_source(), 'CounterId': counter_id},
    }


def const(value):
    return {'kind': 'const', 'value': {'Value': value}}


def abacus_program():
    return {
        'Id': {'Value': '(unnamed)'},
        'Root': {
            'kind': 'node.gainBlock',
            'value': {
                'TargetSelector': sel_source(),
                'Amount': const(6),
                'ResultKey': None,
            },
        },
    }


def sundial_program():
    # 第 N 次洗牌时触发：`remainder(shuffles, 3) == 2`（0 基数：第 3 次是 2）。
    fire = {
        'kind': 'node.conditional',
        'value': {
            'Condition': {
                'kind': 'compare',
                'value': {
                    'Left': {
                        'kind': 'remainder',
                        'value': {'Left': counter('sundial_shuffles'), 'Right': const(3)},
                    },
                    'Right': const(2),
                    'Op': 'Equal',
                },
            },
            'Then': {
                'kind': 'node.gainResource',
                'value': {
                    'TargetSelector': sel_source(),
                    'ResourceId': 'standard.energy',
                    'Amount': const(2),
                    'ResultKey': None,
                },
            },
            'Else': None,
        },
    }
    # 然后无条件 +1（与 `nunchaku` 的第二个条件同一形状）。
    # ⚠️ 真实形状（抄 `nunchaku`）：`CounterId` 是**包装过的值** `{value: ...}`，
    # 自增用 `Amount` + `Relative: true` —— 不是 `Value: add(...)`。第一版按猜的写，
    # 内容门在解析时崩了（`string indices must be integers`），那正是它该做的。
    bump = {
        'kind': 'node.setCombatantCounter',
        'value': {
            'TargetSelector': sel_source(),
            'CounterId': {'value': 'sundial_shuffles'},
            'Amount': const(1),
            'Relative': True,
        },
    }
    return {
        'Id': {'Value': '(unnamed)'},
        'Root': {'kind': 'node.sequence', 'value': {'Children': [fire, bump]}},
    }


def status(status_id, name, description, program):
    return {
        'Id': status_id,
        'PackageId': 'sts',
        'NameKey': name,
        'DescriptionKey': description,
        'Polarity': 'Buff',
        'UsesStacks': True,
        'UsesDuration': False,
        'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': ['buff'],
        'PassiveModifiers': [],
        'Triggers': [{'Event': 'DeckShuffled', 'Program': program}],
    }


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    have = {row['Id'] for row in doc['Statuses']}
    wanted = [
        status('standard.the_abacus', 'The Abacus',
               'Whenever you shuffle your draw pile, gain 6 Block.', abacus_program()),
        status('standard.sundial', 'Sundial',
               'Every 3 times you shuffle your draw pile, gain 2 Energy.', sundial_program()),
    ]
    for row in wanted:
        if row['Id'] in have:
            continue
        doc['Statuses'].append(row)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('statuses', len(doc['Statuses']))


main()
