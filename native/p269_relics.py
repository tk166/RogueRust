"""§269 轻资产批次：**战斗类型层**（4 件）+ **奖励层**（5 件）。

## 战斗类型层

| 遗物 | 稀有度 | wiki 原话 | 落点 |
|---|---|---|---|
| `preserved_insect` | Common | "Enemies in Elite combats have 25% less HP." | `enemy_health_bonus_percent(Elite)`（与升阶同一条通道） |
| `pantograph` | Uncommon | "At the start of Boss combats, heal 25 HP." | `CombatBonus::start_heal` |
| `slavers_collar` | Boss | "During Boss and Elite combats, gain 1 Energy at the start of your turn." | `StartCombatStatusInKinds` + `TurnStartEnergy` 状态 |
| `sling_of_courage` | Shop | "Start each Elite combat with 2 Strength." | `StartCombatStatusInKinds` |

## 奖励层

| 遗物 | 稀有度 | wiki 原话 | 落点 |
|---|---|---|---|
| `question_card` | Uncommon | "Future card rewards have 1 additional card to choose from." | `RewardCardDelta(+1, ALL)` |
| `busted_crown` | Boss | "…Future card rewards have 2 less cards to choose from." | `RewardCardDelta(-2, ALL)` + 能量状态 |
| `prayer_wheel` | Rare | "Normal enemies drop an additional card reward." | `RewardCardDelta(+1, NORMAL)` |
| `white_beast_statue` | Uncommon | "Potions always appear in combat rewards." | `PotionAlwaysDrops` |
| `black_star` | Boss | "Elites now drop an additional relic when defeated." | `EliteExtraRelic` |

`busted_crown` 与 `slavers_collar` 的"每回合 +1 能量"都是**内容状态**（`TurnStartEnergy`
修饰器），与 `philosophers_stone` 同一个形状 —— 运行层的 `KindMask` 只决定**挂不挂**它。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def spec(pipeline, operation, magnitude, priority, kind, applies_to=None, condition=None,
         card_tag=None, scope=None):
    row = {
        'Pipeline': pipeline, 'Operation': operation, 'Magnitude': magnitude,
        'Priority': priority, 'RestrictDamageKind': kind,
        'AppliesToStatusId': {'value': applies_to} if applies_to else None,
        'RestrictSourceCardTag': {'value': card_tag} if card_tag else None,
    }
    if scope:
        row['OverrideScope'] = scope
    if condition:
        row['Condition'] = condition
    return row


def buff(definition_id, name, text, triggers=(), modifiers=None, tags=None):
    return {
        'Id': definition_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': text,
        'Polarity': 'Buff', 'UsesStacks': True, 'UsesDuration': False, 'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': tags or ['buff'],
        'PassiveModifiers': modifiers or [],
        'Triggers': list(triggers),
    }


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    statuses = {row['Id']: row for row in doc['Statuses']}
    relics = {row['Id']: row for row in doc['Relics']}

    def add_status(row):
        if row['Id'] in statuses:
            statuses[row['Id']].update(row)
        else:
            doc['Statuses'].append(row)
            statuses[row['Id']] = row

    # ---- 两条"每回合 +1 能量"的载体（只在特定战斗类型里才被挂上，见运行层的 KindMask）
    add_status(buff(
        'standard.slavers_collar', "Slaver's Collar",
        'During Boss and Elite combats, gain 1 Energy at the start of your turn.',
        modifiers=[spec('TurnStartEnergy', 'AddPerStack', 1, 100, None)]))
    add_status(buff(
        'standard.busted_crown', 'Busted Crown',
        'Gain 1 Energy at the start of your turn. '
        'Future card rewards have 2 less cards to choose from.',
        modifiers=[spec('TurnStartEnergy', 'AddPerStack', 1, 100, None)]))

    # ---- 两件"只改一个数"的（没有载体状态，规则在运行层）
    #   preserved_insect → `EliteEnemyHealthPercent(-25)`
    #   pantograph       → `StartCombatHealInKinds(25, BOSS)`
    #
    # ⚠️ 这里**不建** `standard.preserved_insect` / `standard.pantograph` 状态：它们的规则
    # 不在战斗里跑，挂一条谁都读不到的状态只会让页面上多两行假信息。

    ROWS = [
        # 战斗类型层
        ('preserved_insect', 'Preserved Insect', 'Common', 'elite hp -25%'),
        ('pantograph', 'Pantograph', 'Uncommon', 'boss heal 25'),
        ('slavers_collar', "Slaver's Collar", 'Boss', 'energy in boss/elite'),
        ('sling_of_courage', 'Sling of Courage', 'Shop', 'elite +2 strength'),
        # 奖励层
        ('question_card', 'Question Card', 'Uncommon', 'reward cards +1'),
        ('busted_crown', 'Busted Crown', 'Boss', 'reward cards -2 + energy'),
        ('prayer_wheel', 'Prayer Wheel', 'Rare', 'normal reward cards +1'),
        ('white_beast_statue', 'White Beast Statue', 'Uncommon', 'potions always'),
        ('black_star', 'Black Star', 'Boss', 'elite extra relic'),
    ]
    for rid, display, rarity, note in ROWS:
        relics[rid] = {
            'Id': rid, 'DisplayName': display, 'Rarity': rarity,
            'RunPrograms': None, 'CombatRules': None,
        }
        print('relic %-20s %-9s %s' % (rid, rarity, note))

    doc['Relics'] = [relics[k] for k in sorted(relics)]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: statuses %d, relics %d' % (len(doc['Statuses']), len(doc['Relics'])))


main()
