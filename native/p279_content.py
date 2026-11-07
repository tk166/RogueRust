"""§279 内容：`forgotten_altar` 补成真事件（条件选项 + 三支各自一段）。

wiki（wiki.gg `Forgotten_Altar` + slayspiredb 逐屏表，两处一致）：
  [Offer: Golden Idol]  只在**持有金像**时出现（否则是 `[Locked] Requires: Golden Idol`）
                        → 失去金像、得到血像（`Bloody Idol`：每次得金币回 5 血）
  [Sacrifice]           +5 最大 HP，然后掉 X HP，X = 25% (A15 35%) 最大 HP
  [Desecrate]           诅咒 Decay
  [Leave]               （解谜后每一屏都有）

`Sacrifice` 的**顺序**也是 wiki 的：⚠️ patch 记录 "Forgotten Altar now gives you the Max HP
**before** damaging you. This way you won't die if the damage hits you first." —— 所以
`max_hp +5` 必须排在 `damage_pct` **前面**（顺序就是效果列表的顺序）。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

BODY = ('In front of you sits an altar to a forgotten god. Atop the altar sits an ornate female '
        'statue with arms outstretched. She calls out to you, demanding sacrifice.')
OFFER = ('As you gently set the idol onto the altar a cold wind swirls throughout the room. Your '
         'golden idol begins to dull in color and begins bleeding from its eyes.')
SACRIFICE = ('You stand on the altar and cut your wrists. Everything goes dark. You wake up a '
             'short time later feeling a new potential surging through you.')
DESECRATE = ('You lash out and smash the statue in front of you. A dark wail echoes all around you, '
             'and you can feel the cursed magic seep into your bones.')


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    nodes = {node['Id']: node for node in doc['EventNodes']}
    rooms = {room['Id']: room for room in doc['UnknownRooms']}
    assert 'forgotten_altar' in nodes and rooms['forgotten_altar']['NameKey']

    fresh = {
        'Id': 'forgotten_altar',
        'TextKey': BODY,
        'Options': [
            {
                'Label': 'Offer: Golden Idol',
                # ★ 条件：**持有**金像。没有它时，wiki 的屏幕上是 `[Locked] Requires: Golden Idol`。
                'Requires': [{'Kind': 'relic', 'Op': 'has', 'Id': 'golden_idol'}],
                'Effects': [
                    {'Effect': 'relic_lose:golden_idol', 'Amount': 1},
                    {'Effect': 'relic:bloody_idol', 'Amount': 1},
                ],
                'Next': 'forgotten_altar.offer',
            },
            {
                'Label': 'Sacrifice',
                # ⚠️ 顺序是 wiki 的：**先**给上限，再扣血（否则先掉血可能直接死）。
                'Effects': [
                    {'Effect': 'max_hp', 'Amount': 5},
                    {'Effect': 'damage_pct:25', 'Amount': 0},
                ],
                'EffectsAsc': [
                    {'Effect': 'max_hp', 'Amount': 5},
                    {'Effect': 'damage_pct:35', 'Amount': 0},
                ],
                'Next': 'forgotten_altar.sacrifice',
            },
            {
                'Label': 'Desecrate',
                'Effects': [{'Effect': 'curse:decay', 'Amount': 1}],
                'Next': 'forgotten_altar.desecrate',
            },
            {
                'Label': 'Leave',
                'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                'Next': '',
            },
        ],
    }
    # ⚠️ 必须**替换列表里的那一项**：只改 `nodes[...]` 的话，`doc['EventNodes']` 里仍是旧对象，
    # 于是新写的 `Next` 指向的段全变成孤儿（内容门当场抓到）。
    for index, node in enumerate(doc['EventNodes']):
        if node['Id'] == 'forgotten_altar':
            doc['EventNodes'][index] = fresh
            nodes['forgotten_altar'] = fresh
    # 幂等：上一次跑可能已经留下这些段（脚本失败过一次），先删掉再 append。
    doc['EventNodes'] = [node for node in doc['EventNodes']
                         if node['Id'] not in ('forgotten_altar.offer',
                                               'forgotten_altar.sacrifice',
                                               'forgotten_altar.desecrate')]
    for node_id, text in (
        ('forgotten_altar.offer', OFFER),
        ('forgotten_altar.sacrifice', SACRIFICE),
        ('forgotten_altar.desecrate', DESECRATE),
    ):
        doc['EventNodes'].append({
            'Id': node_id,
            'TextKey': text,
            'Options': [
                {'Label': 'Leave', 'Effects': [{'Effect': 'nothing', 'Amount': 0}], 'Next': ''},
            ],
        })

    # `the_ssssserpent`：Agree 的金币 A15 是 **150**（旧内容两处都写 175 —— 一条 wiki 偏差）。
    serpent = nodes['the_ssssserpent']
    agree = serpent['Options'][0]
    assert agree['Label'] == 'Agree'
    agree['Effects'] = [{'Effect': 'gold', 'Amount': 175},
                        {'Effect': 'curse:doubt', 'Amount': 1}]
    agree['EffectsAsc'] = [{'Effect': 'gold', 'Amount': 150},
                           {'Effect': 'curse:doubt', 'Amount': 1}]
    agree['Next'] = 'the_ssssserpent.wealth'
    for node_id, text in (
        ('the_ssssserpent.wealth',
         '"Yeeeeeeessssssssssessss! Thisss will all be worthhh it. The serpent rears its head and '
         'blasts a stream of gold upwards! You gather all the gold and get going."'),
        ('the_ssssserpent.refusal',
         'The serpent stares at you with a look of extreme disappointment.'),
    ):
        if node_id in nodes:
            continue
        doc['EventNodes'].append({
            'Id': node_id,
            'TextKey': text,
            'Options': [
                {'Label': 'Leave', 'Effects': [{'Effect': 'nothing', 'Amount': 0}], 'Next': ''},
            ],
        })
    serpent['Options'][1]['Next'] = 'the_ssssserpent.refusal'

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('forgotten_altar: 4 options (1 conditional) + 3 follow-up steps; '
          'the_ssssserpent: 2 steps + A15 gold 150')


main()
