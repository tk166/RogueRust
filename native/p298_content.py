"""§298 内容：`magic_flower` / `medical_kit` / `blue_candle`。

| 遗物 | 规则住哪 | 内容那一行 |
|---|---|---|
| `magic_flower` | 内核（`heal_for` 的 ×150%，常量 `MAGIC_FLOWER`） | 开关 |
| `medical_kit` | 内核（`unplayable_validator` 放行 Status 牌 + 落区 ExhaustPile） | 开关 |
| `blue_candle` | 内核（放行 Curse 牌）+ **内容**（`CardPlayed` + `card.hasTag.curse` → 失去 1 生命） | 单触发器 |
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def sel_source():
    return {'kind': 'sel.source',
            'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'Source'}}


def status(status_id, name, description, *, triggers=None):
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
        'Triggers': triggers or [],
    }


def blue_candle_trigger():
    """`CardPlayed` 且打出的牌带 `curse` 标签 ⇒ 失去 1 点生命。

    形状抄已有的 `CardPlayed` + `card.hasTag.attack` 程序（`standard.nunchaku` / `sharp_hide`），
    只把标签门换成 `curse`、动作换成 `loseHp 1`。
    """
    return [{
        'Event': 'CardPlayed',
        'Program': {
            'Id': {'Value': '(unnamed)'},
            'Root': {
                'kind': 'node.conditional',
                'value': {
                    'Condition': {
                        'kind': 'event.bool',
                        'value': {'FieldKey': 'card.hasTag.curse'},
                    },
                    'Then': {
                        'kind': 'node.loseHp',
                        'value': {
                            'TargetSelector': sel_source(),
                            'Amount': {'kind': 'const', 'value': {'Value': 1}},
                            'ResultKey': None,
                        },
                    },
                    'Else': None,
                },
            },
        },
    }]


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    have = {row['Id'] for row in doc['Statuses']}
    wanted = [
        status('standard.magic_flower', 'Magic Flower',
               'During combat, healing is 50% more effective.'),
        status('standard.medical_kit', 'Medical Kit',
               'Unplayable Status cards can now be played. Whenever you play a Status card, '
               'Exhaust it.'),
        status('standard.blue_candle', 'Blue Candle',
               'Unplayable Curse cards can now be played. Whenever you play a Curse, lose 1 HP '
               'and Exhaust it.', triggers=blue_candle_trigger()),
    ]
    for row in wanted:
        if row['Id'] in have:
            continue
        doc['Statuses'].append(row)

    relics = {row['Id'] for row in doc['Relics']}
    for rid, name, rarity in (
        ('magic_flower', 'Magic Flower', 'Rare'),
        ('medical_kit', 'Medical Kit', 'Shop'),
        ('blue_candle', 'Blue Candle', 'Uncommon'),
    ):
        if rid in relics:
            continue
        doc['Relics'].append({
            'Id': rid,
            'DisplayName': name,
            'RunPrograms': None,
            'CombatRules': None,
            'Rarity': rarity,
        })
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('statuses', len(doc['Statuses']), 'relics', len(doc['Relics']))


main()
