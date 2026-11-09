"""§320 内容 —— `the_library`（Act 2）与 `sensory_stone`（Act 3）。

wiki 原文：

- **The Library**（Act 2）：`[Sleep]` Heal **33%（A15 20%）** of max HP /
  `[Read]` **Choose 1 of 20 cards** to add to your deck（不可退回 Sleep）。
- **Sensory Stone**（Act 3）：三个 `[Recall]` ——
  **Add 1 Colorless card** / **Add 2 Colorless cards, lose 5 HP** /
  **Add 3 Colorless cards, lose 10 HP**。

"1/2/3 张"用**段链**表达（每一步摊一张候选，取走后 `Next` 去下一段）：候选面板本身
只知道"这一次摊几张"，而 `event_next` 是既有的那条尾巴 —— 不引入第二个状态机。
"""

import io
import json

PATH = 'tools/contentc/packages/sts/sts.roguedeck.json'


def recall(label, hp, cards, next_id):
    effects = []
    if hp:
        effects.append({'Effect': 'damage:%d' % hp, 'Amount': hp})
    effects.append({'Effect': 'offer_cards:%d:colorless' % cards, 'Amount': 0})
    return {'Label': label, 'Effects': effects, 'Next': next_id}


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    ids = {node['Id'] for node in doc['EventNodes']}
    assert 'the_library' not in ids and 'sensory_stone' not in ids, 'already patched'

    library = [
        {
            'Id': 'the_library',
            'TextKey': ('A plaque lies face down on the floor: THE LIBRARY. Inside, rows of '
                        'scrolls and chairs out of a better century.'),
            'Options': [
                {
                    'Label': 'Sleep',
                    'Effects': [{'Effect': 'heal_pct:33', 'Amount': 0}],
                    # wiki：(20%) at A15.
                    'EffectsAsc': [{'Effect': 'heal_pct:20', 'Amount': 0}],
                    'Next': '',
                },
                {
                    'Label': 'Read (1 of 20)',
                    'Effects': [{'Effect': 'offer_cards:20:any', 'Amount': 0}],
                    'Next': '',
                },
            ],
        },
        {
            'Id': 'the_library.read',
            'TextKey': ('You pull a volume at random and lose an hour in it. Somewhere in there '
                        'is a technique worth keeping.'),
            'Options': [],
        },
    ]

    stone = [
        {
            'Id': 'sensory_stone',
            'TextKey': ('A glowing tesseract turns slowly in the air, humming a memory that is '
                        'not yours.'),
            'Options': [
                recall('Recall (1 card)', 0, 1, ''),
                recall('Recall (2 cards, 5 HP)', 5, 1, 'sensory_stone.again1'),
                recall('Recall (3 cards, 10 HP)', 10, 1, 'sensory_stone.again2'),
            ],
        },
        {
            'Id': 'sensory_stone.again1',
            'TextKey': 'The memory unfolds further; it wants to be looked at again.',
            'Options': [recall('Recall (2nd card)', 0, 1, '')],
        },
        {
            'Id': 'sensory_stone.again2',
            'TextKey': 'A second memory arrives before the first has faded.',
            'Options': [recall('Recall (2nd card)', 0, 1, 'sensory_stone.again3')],
        },
        {
            'Id': 'sensory_stone.again3',
            'TextKey': 'The tesseract dims as the last of it settles into your hands.',
            'Options': [recall('Recall (3rd card)', 0, 1, '')],
        },
    ]

    doc['EventNodes'].extend(library + stone)
    doc['EventTables']['Events2'].append({'Id': 'the_library'})
    doc['EventTables']['Events3'].append({'Id': 'sensory_stone'})
    doc['UnknownRooms'].append({'Id': 'the_library', 'NameKey': 'The Library',
                                'Entry': 'the_library'})
    doc['UnknownRooms'].append({'Id': 'sensory_stone', 'NameKey': 'Sensory Stone',
                                'Entry': 'sensory_stone'})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('event nodes %d events2 %d events3 %d rooms %d'
          % (len(doc['EventNodes']), len(doc['EventTables']['Events2']),
             len(doc['EventTables']['Events3']), len(doc['UnknownRooms'])))


main()
