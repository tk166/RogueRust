"""§270 内容：加牌类 6 件 + 金币/商店类 5 件 + 两条能量载体状态。

wiki 原文（离线 `native/wiki_relics/relics_data.lua.txt`）：

| 遗物 | 稀有度 | 原文 |
|---|---|---|
| Omamori | Common | "Negate the next 2 Curses you obtain." |
| Ceramic Fish | Common | "Whenever you add a card to your deck, gain 9 Gold." |
| Darkstone Periapt | Uncommon | "Whenever you obtain a Curse, increase your Max HP by 6" |
| Molten Egg | Uncommon | "Whenever you add an Attack card to your deck, Upgrade it." |
| Frozen Egg | Uncommon | "Whenever you add a Power card to your deck, Upgrade it." |
| Toxic Egg | Uncommon | "Whenever you add a Skill card to your deck, Upgrade it." |
| Bloody Idol | Event | "Whenever you gain Gold, heal 5 HP." |
| Ectoplasm | Boss | "Gain 1 Energy at the start of your turn. You can no longer gain Gold." |
| Maw Bank | Common | "Whenever you climb a floor, gain 12 Gold. No longer works when you spend any Gold at a shop." |
| Membership Card | Shop | "50% discount on all products!" |
| Smiling Mask | Common | "The merchant's card removal service now always costs 50 Gold." |

`Singing Bowl`（"you may raise your Max HP by 2 instead"）**不在这一批**：它是"加牌时**可以**换成
+2 上限"，也就是一个**运行层的问句**（`PendingChoice` 目前只存在于战斗里）。归中资产，见 §270.5。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def spec(pipeline, operation, magnitude, priority=100):
    return {
        'Pipeline': pipeline, 'Operation': operation, 'Magnitude': magnitude,
        'Priority': priority, 'RestrictDamageKind': None,
        'AppliesToStatusId': None, 'RestrictSourceCardTag': None,
    }


def buff(definition_id, name, text, modifiers):
    return {
        'Id': definition_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': text,
        'Polarity': 'Buff', 'UsesStacks': True, 'UsesDuration': False, 'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': ['buff'], 'PassiveModifiers': modifiers, 'Triggers': [],
    }


ROWS = [
    ('omamori', 'Omamori', 'Common', 'negate the next 2 curses'),
    ('ceramic_fish', 'Ceramic Fish', 'Common', '+9 gold per card added'),
    ('maw_bank', 'Maw Bank', 'Common', '+12 gold per floor climbed'),
    ('smiling_mask', 'Smiling Mask', 'Common', 'removal always 50'),
    ('darkstone_periapt', 'Darkstone Periapt', 'Uncommon', '+6 max HP per curse'),
    ('molten_egg', 'Molten Egg', 'Uncommon', 'Attack cards arrive upgraded'),
    ('toxic_egg', 'Toxic Egg', 'Uncommon', 'Skill cards arrive upgraded'),
    ('frozen_egg', 'Frozen Egg', 'Uncommon', 'Power cards arrive upgraded'),
    ('membership_card', 'Membership Card', 'Shop', '50% off everything'),
    ('ectoplasm', 'Ectoplasm', 'Boss', '+1 energy / turn, no more gold'),
    ('bloody_idol', 'Bloody Idol', 'Event', 'heal 5 whenever gold is gained'),
]


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    statuses = {row['Id']: row for row in doc['Statuses']}

    # §270：`ectoplasm` 的"每回合 +1 能量"与其他能量遗物同形 —— 一条 `TurnStartEnergy` 状态。
    # 它的另一半（"不能再得到金币"）在运行层的 `RelicEffect::NoGoldGain` 里。
    row = buff(
        'standard.ectoplasm', 'Ectoplasm',
        'Gain 1 Energy at the start of your turn. You can no longer gain Gold.',
        [spec('TurnStartEnergy', 'AddPerStack', 1)])
    if row['Id'] in statuses:
        statuses[row['Id']].update(row)
    else:
        doc['Statuses'].append(row)
        statuses[row['Id']] = row

    relics = {row['Id']: row for row in doc['Relics']}
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
