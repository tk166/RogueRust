"""§322 内容 —— Act 2 的四条：`council_of_ghosts` / `pleading_vagrant` / `old_beggar` / `vampires`。

wiki 原文：

**Council of Ghosts**：`[Accept]` 得 **5**（A15 **3**）张 `Apparition`，失去 **50% 最大生命**
（四舍五入向上）；`[Refuse]` 什么也不发生，然后给一个 `[Leave]`。

**Pleading Vagrant**：`[Give 85 Gold]`（Requires 85 gold）得**随机一件遗物**；
`[Rob]` 得随机一件遗物 + 诅咒 `Shame`；`[Leave]`。

**Old Beggar**：**只在金币 ≥ 75 时出现**（池子的 `MinGold`）；`[Offer Gold]` 付 **75** 金币、
**删一张牌**；`[Leave]`。

**Vampires(?)**：`[Offer: Blood Vial]`（**只在有 `blood_vial` 时出现**）失去血瓶、移除**所有**
打击、得 **5** 张 `Bite`；`[Accept]` 同样但**再失去 30% 最大生命**；`[Refuse]` 什么也不发生 → `[Leave]`。
"""

import io
import json

PATH = 'tools/contentc/packages/sts/sts.roguedeck.json'


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    ids = {node['Id'] for node in doc['EventNodes']}
    wanted = ['council_of_ghosts', 'pleading_vagrant', 'old_beggar', 'vampires']
    assert not any(name in ids for name in wanted), 'already patched'

    nodes = [
        # ── Council of Ghosts ────────────────────────────────────────────────────────
        {
            'Id': 'council_of_ghosts',
            'TextKey': ('Three hooded shapes fade into being, offering a shard of themselves. '
                        'It costs a piece of you.'),
            'Options': [
                {
                    'Label': 'Accept (5 Apparitions)',
                    'Effects': [{'Effect': 'card:apparition', 'Amount': 5},
                                {'Effect': 'max_hp_pct:50', 'Amount': 0}],
                    # wiki：A15 只给 3 张。
                    'EffectsAsc': [{'Effect': 'card:apparition', 'Amount': 3},
                                   {'Effect': 'max_hp_pct:50', 'Amount': 0}],
                    'Next': 'council_of_ghosts.after',
                },
                {
                    'Label': 'Refuse',
                    'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                    'Next': 'council_of_ghosts.after',
                },
            ],
        },
        {
            'Id': 'council_of_ghosts.after',
            'TextKey': 'The hooded shapes thin out and are gone. The corridor is just a corridor.',
            'Options': [{'Label': 'Leave', 'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                         'Next': ''}],
        },
        # ── Pleading Vagrant ────────────────────────────────────────────────────────
        {
            'Id': 'pleading_vagrant',
            'TextKey': ('A shrouded figure steps out of the group ahead. "Got anything for me, '
                        'friend? Coin, maybe? I have treasures to trade..."'),
            'Options': [
                {
                    'Label': 'Give 85 Gold',
                    'Requires': [{'Kind': 'gold', 'Op': 'at_least', 'Amount': 85}],
                    'Effects': [{'Effect': 'gold_cost:85', 'Amount': 85},
                                {'Effect': 'relic_random', 'Amount': 0}],
                    'Next': 'pleading_vagrant.thanks',
                },
                {
                    'Label': 'Rob',
                    'Effects': [{'Effect': 'relic_random', 'Amount': 0},
                                {'Effect': 'curse:shame', 'Amount': 1}],
                    'Next': 'pleading_vagrant.shame',
                },
                {
                    'Label': 'Leave',
                    'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                    'Next': '',
                },
            ],
        },
        {
            'Id': 'pleading_vagrant.thanks',
            'TextKey': '"Oh yes, yes! Here here, a fair trade!"',
            'Options': [{'Label': 'Leave', 'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                         'Next': ''}],
        },
        {
            'Id': 'pleading_vagrant.shame',
            'TextKey': ('You snatch the relic from his clutches and walk on. Behind you: "Have you '
                        'no shame? HAVE YOU NO SHAAAAAME?!" You do, a little.'),
            'Options': [{'Label': 'Leave', 'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                         'Next': ''}],
        },
        # ── Old Beggar ──────────────────────────────────────────────────────────────
        {
            'Id': 'old_beggar',
            'TextKey': ('An old beggar holds out a bowl. "Seventy-five for a look at your deck, '
                        'friend. I know old tricks."'),
            'Options': [
                {
                    'Label': 'Offer 75 Gold',
                    'Requires': [{'Kind': 'gold', 'Op': 'at_least', 'Amount': 75}],
                    'Effects': [{'Effect': 'gold_cost:75', 'Amount': 75},
                                {'Effect': 'remove_card', 'Amount': 0}],
                    'Next': '',
                },
                {
                    'Label': 'Leave',
                    'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                    'Next': '',
                },
            ],
        },
        # ── Vampires ────────────────────────────────────────────────────────────────
        {
            'Id': 'vampires',
            'TextKey': ('Hooded figures circle something on the ground, and one of them turns. '
                        '"Join us, and feel the warmth of the Spire."'),
            'Options': [
                {
                    'Label': 'Offer: Blood Vial',
                    'Requires': [{'Kind': 'relic', 'Op': 'has', 'Id': 'blood_vial'}],
                    'Effects': [{'Effect': 'relic_lose:blood_vial', 'Amount': 0},
                                {'Effect': 'remove_all:strike', 'Amount': 0},
                                {'Effect': 'card:bite', 'Amount': 5}],
                    'Next': 'vampires.after',
                },
                {
                    'Label': 'Accept (30% max HP)',
                    'Effects': [{'Effect': 'remove_all:strike', 'Amount': 0},
                                {'Effect': 'card:bite', 'Amount': 5},
                                {'Effect': 'max_hp_pct:30', 'Amount': 0}],
                    'Next': 'vampires.after',
                },
                {
                    'Label': 'Refuse',
                    'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                    'Next': 'vampires.after',
                },
            ],
        },
        {
            'Id': 'vampires.after',
            'TextKey': 'The circle closes, then opens again. Whatever they were doing, it is done.',
            'Options': [{'Label': 'Leave', 'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                         'Next': ''}],
        },
    ]

    doc['EventNodes'].extend(nodes)
    for name in ('council_of_ghosts', 'pleading_vagrant', 'vampires'):
        doc['EventTables']['Events2'].append({'Id': name})
    # Old Beggar 只在**金币 ≥ 75** 时出现（wiki："will only appear if … at least 75 Gold"）。
    doc['EventTables']['Events2'].append({'Id': 'old_beggar', 'MinGold': 75})
    for node in nodes:
        if '.' in node['Id']:
            continue
        doc['UnknownRooms'].append({'Id': node['Id'],
                                    'NameKey': node['Id'].replace('_', ' ').title(),
                                    'Entry': node['Id']})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('event nodes %d events2 %d rooms %d'
          % (len(doc['EventNodes']), len(doc['EventTables']['Events2']),
             len(doc['UnknownRooms'])))


main()
