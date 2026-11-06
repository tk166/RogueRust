"""§249.3 探针：只加 `Omega` 一条，构建后让 `report.md` 点名 JSON 回退的字段。

用 `report.md` 的 "Fields that fell back to `F_JSON`" 一节 —— 那是编译期就已经记录下来的
证据（`Deriver.json_fallback`），比运行时 `WrongKind("F_JSON")` 精确得多：**运行时只说
"某一格解不出来"，编译期知道是哪一 (opcode, field) 对**。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

SELF = {"kind": "sel.source",
        "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
ALL_ENEMIES = {"kind": "sel.allEnemies",
               "value": {"Cardinality": "Any", "RequiredContextCapabilities": "Source"}}

root = {
    "kind": "node.dealDamage",
    "value": {
        "TargetSelector": ALL_ENEMIES,
        "Amount": {"kind": "combatantStatusStacks",
                   "value": {"Selector": SELF,
                             "StatusId": {"value": "standard.omega"}}},
        "IgnoresBlock": False,
        "Element": None,
        "ResultKey": None,
    },
}

data = json.loads(io.open(CONTENT, encoding='utf-8').read())
data['Cards'].append({
    'Id': 'omega', 'PackageId': 'sts', 'NameKey': 'Omega',
    'DescriptionKey': 'At the end of your turn, deal 50 damage to ALL enemies.',
    'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': 3}],
    'Tags': [{'value': 'power'}, {'value': 'colorless'}],
    'Rarity': 'Special',
    'Program': {'Id': {'Value': '(unnamed)'}, 'Root': {
        'kind': 'node.applyStatus',
        'value': {'TargetSelector': SELF,
                  'StatusDefinitionId': {'value': 'standard.omega'},
                  'Stacks': {'kind': 'const', 'value': {'Value': 50}},
                  'DurationTurns': 0, 'Charges': 0, 'ResultKey': None}},
                'MaxNodeDepth': 64, 'MaxProgramSteps': 1024},
    'LifecyclePrograms': {}, 'RetainInHandOnTurnEnd': False,
    'TurnEndHandDestinationZone': 'DiscardPile',
    'PlayedCardDestinationZone': 'DiscardPile',
})
data['Statuses'].append({
    'Id': 'standard.omega', 'PackageId': 'sts', 'NameKey': 'Omega',
    'DescriptionKey': 'At the end of your turn, deal damage equal to its stacks to ALL enemies.',
    'Polarity': 'Buff', 'UsesStacks': True, 'UsesDuration': False, 'UsesCharges': False,
    'StackingBehavior': 'MergeWithExistingInstance', 'Tags': ['buff'],
    'PassiveModifiers': [],
    'Triggers': [{'Event': 'TurnEnded',
                  'Program': {'Id': {'Value': '(unnamed)'}, 'Root': root,
                              'MaxNodeDepth': 64, 'MaxProgramSteps': 1024}}],
})
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(data, ensure_ascii=False, indent=2) + '\n')
print('probe content written (cards %d, statuses %d)' % (len(data['Cards']), len(data['Statuses'])))
