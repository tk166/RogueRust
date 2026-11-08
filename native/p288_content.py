"""§288 内容：The Colosseum（Act 2）+ 事件池的楼层门槛。

## The Colosseum（wiki 两个来源一致）

    [Fight]  → 打 Blue Slaver + Red Slaver，**这场没有奖励**
    （赢了之后）[COWARDICE] 逃跑，事件结束
                [VICTORY]  → 打 Taskmaster + Gremlin Nob
                             奖励：100 金币、1 件稀有遗物、1 件罕见遗物、一次选牌、（有时药水）
                             打完事件结束

所以第一场必须**回到事件**（`After`），第二场按定数奖励结算（`fight_gold_set` /
`fight_relic_rarity` / `fight_extra_relic`）。

## 楼层门槛

`Dead Adventurer` 只在第 7 层之后出现（wiki）⇒ `EventTables.Events` 里给它 `MinFloor: 7`。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

DOUBLE = [{'Effect': 'nothing', 'Amount': 0}]


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    nodes = {n['Id']: n for n in doc['EventNodes']}

    # ── ① 楼层门槛
    for row in doc['EventTables']['Events']:
        if row['Id'] == 'dead_adventurer':
            row['MinFloor'] = 7

    # ── ② The Colosseum 的段
    INTRO = ('Groggy and with a throbbing head, you awaken to find yourself thrown in the center '
             'of a massive stadium with an overflowing audience of Slavers, Cultists, and other '
             'denizens of the City!')
    AFTER = 'The crowd roars. Across the arena, the gate of the champions grinds open.'
    built = [
        {
            'Id': 'the_colosseum',
            'TextKey': INTRO,
            'Options': [{
                'Label': 'Fight',
                'Effects': list(DOUBLE),
                'Fight': 'monster',
                'Encounter': 'ColosseumSlavers',
                # §288：打完**回到事件**（不是结算房间）。这一场没有奖励。
                'After': 'the_colosseum.after',
                'Next': '',
            }],
        },
        {
            'Id': 'the_colosseum.after',
            'TextKey': AFTER,
            'Options': [
                {
                    'Label': 'VICTORY',
                    'Effects': [
                        # §288：定数奖励 —— 100 金币、1 稀有遗物、1 罕见遗物。
                        {'Effect': 'fight_gold_set', 'Amount': 100},
                        {'Effect': 'fight_relic_rarity:rare', 'Amount': 0},
                        {'Effect': 'fight_extra_relic:uncommon', 'Amount': 0},
                    ],
                    'Fight': 'elite',
                    'Encounter': 'ColosseumChampions',
                    'Next': '',
                },
                {'Label': 'COWARDICE', 'Effects': list(DOUBLE), 'Next': ''},
            ],
        },
    ]
    drop = {n['Id'] for n in doc['EventNodes'] if n['Id'].startswith('the_colosseum')}
    doc['EventNodes'] = [n for n in doc['EventNodes'] if n['Id'] not in drop] + built
    doc['UnknownRooms'] = [r for r in doc['UnknownRooms'] if r['Id'] != 'the_colosseum']
    doc['UnknownRooms'].append({'Id': 'the_colosseum', 'NameKey': 'The Colosseum',
                                'Entry': 'the_colosseum'})
    rows = [row for row in doc['EventTables']['Events2'] if row['Id'] != 'the_colosseum']
    rows.append({'Id': 'the_colosseum'})
    doc['EventTables']['Events2'] = rows

    # ── ③ 两个遭遇（只在事件里出现）
    tpl = {}
    for entry in doc['Encounters']:
        value = entry['Id']['Value']
        tpl[value] = entry

    def clone(source_id, new_id, enemies):
        """按 `source_id` 的形状克隆，只换 id 与敌人列表（敌人行从同名的遭遇里抄）。"""
        base = json.loads(json.dumps(tpl[source_id]))
        base['Id'] = {'Value': new_id}
        base['Enemies'] = enemies
        for index, enemy in enumerate(base['Enemies']):
            enemy['Position'] = index
        return base

    def enemy_from(encounter_id, monster_id, position=0):
        for row in tpl[encounter_id]['Enemies']:
            if row['Id'] == monster_id:
                copy = json.loads(json.dumps(row))
                copy['Position'] = position
                return copy
        raise SystemExit('%s has no %s' % (encounter_id, monster_id))

    slavers = clone('enc_slavers',
                    'enc_colosseum_slavers',
                    [enemy_from('enc_blue_slaver', 'blue_slaver'),
                     enemy_from('enc_slaver_red', 'slaver_red', 1)])
    champions = clone('enc_slavers',
                      'enc_colosseum_champions',
                      [enemy_from('enc_slavers', 'taskmaster'),
                       enemy_from('enc_gremlin_nob', 'gremlin_nob', 1)])
    doc['Encounters'] = [e for e in doc['Encounters']
                         if e['Id']['Value'] not in ('enc_colosseum_slavers',
                                                     'enc_colosseum_champions')]
    doc['Encounters'].extend([slavers, champions])

    doc['EncounterTables']['ColosseumSlavers'] = [{'Id': 'enc_colosseum_slavers', 'Weight': 1}]
    doc['EncounterTables']['ColosseumChampions'] = [{'Id': 'enc_colosseum_champions', 'Weight': 1}]

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: the_colosseum (2 steps, 2 encounters) + MinFloor 7')


main()
