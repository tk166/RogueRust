"""§297 内容：`strike_dummy` / `velvet_choker` / `runic_dome`。

三件的规则各在哪儿（**这是这一节最要紧的一张表**）：

| 遗物 | 规则住哪 | 内容那一行 |
|---|---|---|
| `strike_dummy` | **内容**（`DamageDealt / AddFlat 3 / RestrictSourceCardTag: strike`） | 真程序 |
| `velvet_choker` | 内核（`play.rs` 的 `card_limit_validator`，上限 6 是常量） | 开战状态 = 开关 |
| `runic_dome` | 内核 + 观测（`play.rs` 没它；`rd-wasm::refresh_intents` 把意图变 unknown） | 开战状态 = 开关 |

`velvet_choker` 与 `runic_dome` 还各要"每回合 +1 能量"（`TurnStartEnergy` 修饰器）。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def sel_source():
    return {'kind': 'sel.source',
            'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'Source'}}


def status(status_id, name, description, *, modifiers=None, triggers=None):
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
        'PassiveModifiers': modifiers or [],
        'Triggers': triggers or [],
    }


ENERGY = {
    'Pipeline': 'TurnStartEnergy',
    'Operation': 'AddPerStack',
    'Magnitude': 1,
    'Priority': 100,
    'RestrictDamageKind': None,
    'AppliesToStatusId': None,
    'RestrictSourceCardTag': None,
}

# `strike_dummy`：伤害 +3，但**只对带 `strike` 标签的牌**。
# 这条 spec 的形状抄 `standard.akabeko`（`DamageDealt / AddFlat 8 / Direct`），
# 只是把"伤害种类"的门换成"来源卡标签"的门 —— `akabeko` 也用着 `RestrictSourceCardTag: attack`。
STRIKE_BONUS = {
    'Pipeline': 'DamageDealt',
    'Operation': 'AddFlat',
    'Magnitude': 3,
    'Priority': 100,
    'RestrictDamageKind': None,
    'AppliesToStatusId': None,
    'RestrictSourceCardTag': {'value': 'strike'},
}


def main():
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    have = {row['Id'] for row in doc['Statuses']}
    wanted = [
        status('standard.strike_dummy', 'Strike Dummy',
               'Cards containing "Strike" deal 3 additional damage.',
               modifiers=[STRIKE_BONUS]),
        status('standard.velvet_choker', 'Velvet Choker',
               'Gain 1 Energy at the start of your turn. You cannot play more than 6 cards per turn.',
               modifiers=[ENERGY]),
        status('standard.runic_dome', 'Runic Dome',
               'Gain 1 Energy at the start of your turn. You can no longer see enemy intents.',
               modifiers=[ENERGY]),
    ]
    for row in wanted:
        if row['Id'] in have:
            continue
        doc['Statuses'].append(row)

    relics = {row['Id'] for row in doc['Relics']}
    for rid, name, rarity in (
        ('strike_dummy', 'Strike Dummy', 'Uncommon'),
        ('velvet_choker', 'Velvet Choker', 'Boss'),
        ('runic_dome', 'Runic Dome', 'Boss'),
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
