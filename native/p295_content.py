"""§295 内容：`standard.hand_drill`（`BlockBroken` → 给 `sel.eventTarget` 2 层易伤）+ 遗物行。

⚠️ 易伤必须落在 **`sel.eventTarget`**（格挡被打穿的那一方），不是 `sel.source`：
`sel.source` 是**出手方**（英雄自己）—— 写成 source 的话会变成"给自己上易伤"，
而那正是 §4.20 那类"同一个词表被两处认识就一定漂"的近亲：**目标槽选错，症状看着像没问题**。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def sel_event_target():
    return {
        'kind': 'sel.eventTarget',
        'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'EventTarget'},
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
        'Triggers': [{'Event': 'BlockBroken', 'Program': program}],
    }


def hand_drill_program():
    return {
        'Id': {'Value': '(unnamed)'},
        'Root': {
            'kind': 'node.applyStatus',
            'value': {
                'TargetSelector': sel_event_target(),
                'StatusDefinitionId': {'value': 'standard.vulnerable'},
                'Stacks': {'kind': 'const', 'value': {'Value': 2}},
                'Duration': None,
                'ResultKey': None,
            },
        },
    }


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    have = {row['Id'] for row in doc['Statuses']}
    if 'standard.hand_drill' not in have:
        doc['Statuses'].append(status(
            'standard.hand_drill', 'Hand Drill',
            "Whenever you break an enemy's Block, apply 2 Vulnerable.",
            hand_drill_program()))
    relics = {row['Id'] for row in doc['Relics']}
    if 'hand_drill' not in relics:
        doc['Relics'].append({
            'Id': 'hand_drill',
            'DisplayName': 'Hand Drill',
            'RunPrograms': None,
            'CombatRules': None,
            'Rarity': 'Shop',
        })
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('statuses', len(doc['Statuses']), 'relics', len(doc['Relics']))


main()
