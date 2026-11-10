"""§321 内容 —— `tomb_of_lord_red_mask`（Act 3，纯内容）与 `mind_bloom`（Act 3）。

wiki 原文：

**Tomb of Lord Red Mask**
- 已有 `Red Mask`：`[Don the Red Mask]` **+222 金币**（遗物留着）；`[Leave]`
- 没有 `Red Mask`：`[Offer: X Gold]` **失去全部金币**、获得 `Red Mask`；`[Leave]`

**Mind Bloom**（四个选项，第三个按楼层换）
- `[I am War]`：打一场**第 1 幕 Boss**，得稀有遗物 + 普通奖励 + 50（**A15 25**）金币
- `[I am Awake]`：**升级所有牌** + `Mark of the Bloom`（"You can no longer heal"）
- `[I am Rich]`（35–40 层）：**+999 金币** + **2 张 `Normality`**
- `[I am Healthy]`（41 层起）：**回满血** + 1 张 `Doubt`

层号口径：我们的 `RunState::floor()` 是**本幕内的行号**（1..=15），第三幕从绝对 35 层起算，
所以 35–40 ⇒ `at_most 6`、41+ ⇒ `at_least 7`。
"""

import io
import json

PATH = 'tools/contentc/packages/sts/sts.roguedeck.json'


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    ids = {node['Id'] for node in doc['EventNodes']}
    assert 'tomb_of_lord_red_mask' not in ids and 'mind_bloom' not in ids, 'already patched'

    tomb = [
        {
            'Id': 'tomb_of_lord_red_mask',
            'TextKey': ('An ornamented tomb waits across a floating path. A slot for coins sits '
                        'under an inscription somebody has scratched out.'),
            'Options': [
                {
                    'Label': 'Don the Red Mask (222 gold)',
                    'Requires': [{'Kind': 'relic', 'Op': 'has', 'Id': 'red_mask'}],
                    'Effects': [{'Effect': 'gold', 'Amount': 222}],
                    'Next': '',
                },
                {
                    'Label': 'Offer all Gold',
                    # 至少有一枚金币才有"全部金币"可付。
                    'Requires': [{'Kind': 'gold', 'Op': 'at_least', 'Amount': 1}],
                    'Effects': [{'Effect': 'gold_all', 'Amount': 0},
                                {'Effect': 'relic:red_mask', 'Amount': 0}],
                    'Next': '',
                },
                {
                    'Label': 'Leave',
                    'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                    'Next': '',
                },
            ],
        },
    ]

    bloom = [
        {
            'Id': 'mind_bloom',
            'TextKey': ('Your imagination takes shape around you. In this brief moment, whatever '
                        'you wish for can be true -- and it will cost you.'),
            'Options': [
                {
                    'Label': 'I am War (Act 1 Boss)',
                    'Effects': [{'Effect': 'fight_gold_bonus', 'Amount': 50},
                                {'Effect': 'fight_relic_rarity:rare', 'Amount': 0}],
                    # wiki：50（A15 25）
                    'EffectsAsc': [{'Effect': 'fight_gold_bonus', 'Amount': 25},
                                   {'Effect': 'fight_relic_rarity:rare', 'Amount': 0}],
                    'Fight': 'boss',
                    # 第 1 幕的 Boss 池：事件点名的池**不加幕后缀**（§287 的同一条规矩）。
                    'Encounter': 'Boss',
                    'After': '',
                    'Next': '',
                },
                {
                    'Label': 'I am Awake (upgrade all)',
                    'Effects': [{'Effect': 'upgrade_all', 'Amount': 0},
                                {'Effect': 'relic:mark_of_the_bloom', 'Amount': 0}],
                    'Next': '',
                },
                {
                    'Label': 'I am Rich (999 gold)',
                    'Requires': [{'Kind': 'floor', 'Op': 'at_most', 'Amount': 6}],
                    'Effects': [{'Effect': 'gold', 'Amount': 999},
                                {'Effect': 'curse:normality', 'Amount': 2}],
                    'Next': '',
                },
                {
                    'Label': 'I am Healthy (heal to full)',
                    'Requires': [{'Kind': 'floor', 'Op': 'at_least', 'Amount': 7}],
                    'Effects': [{'Effect': 'heal_full', 'Amount': 0},
                                {'Effect': 'curse:doubt', 'Amount': 1}],
                    'Next': '',
                },
            ],
        },
    ]

    doc['EventNodes'].extend(tomb + bloom)
    doc['EventTables']['Events3'].append({'Id': 'tomb_of_lord_red_mask'})
    doc['EventTables']['Events3'].append({'Id': 'mind_bloom'})
    doc['UnknownRooms'].append({'Id': 'tomb_of_lord_red_mask', 'NameKey': 'Tomb of Lord Red Mask',
                                'Entry': 'tomb_of_lord_red_mask'})
    doc['UnknownRooms'].append({'Id': 'mind_bloom', 'NameKey': 'Mind Bloom',
                                'Entry': 'mind_bloom'})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('event nodes %d events3 %d rooms %d'
          % (len(doc['EventNodes']), len(doc['EventTables']['Events3']),
             len(doc['UnknownRooms'])))


main()
