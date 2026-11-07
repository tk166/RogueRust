"""§278：把 `golden_idol` 补成**真事件树**（wiki 的两屏 + 三选一）。

旧的写法把两屏压成一行两个选项（Take = 遗物 + 诅咒；A15 = 遗物 + 20 伤害），
于是"巨石追来"那段文本、以及 Outrun/Smash/Hide 三个**不同**的代价根本不存在。

现在：
  golden_idol            Take →（拿到遗物）→ golden_idol.boulder
                         Leave →  什么也不发生（终点）
  golden_idol.boulder    Outrun → 诅咒 Injury
                         Smash  → 掉 25% 最大 HP（A15 35%）
                         Hide   → 扣 8% 最大 HP（A15 10%）

数值取自 wiki.gg（`Golden_Idol_(Event)`）+ slayspiredb 的逐屏表；两处独立来源一致：
Take → Screen 2（巨石）；Outrun = Injury；Smash = 25% (35%) Max HP 伤害；
Hide = `max(1, 8% (10%) Max HP)` 的上限损失。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

TAKE_TEXT = ('As you grab the Idol and stow it away, a giant boulder smashes through the ceiling '
             'into the ground next to you. You realize that the floor is slanted downwards as the '
             'boulder starts to roll towards you.')


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    rooms = {room['Id']: room for room in doc['UnknownRooms']}
    nodes = {node['Id']: node for node in doc['EventNodes']}
    assert 'golden_idol' in rooms and 'golden_idol' in nodes

    entry = nodes['golden_idol']
    take = entry['Options'][0]
    assert take['Label'] == 'Take it', take
    # 第一段：拿遗物**只是**一半，巨石那段是另一段文本。
    take['Effects'] = [{'Effect': 'relic:golden_idol', 'Amount': 1}]
    take.pop('EffectsAsc', None)
    take['Next'] = 'golden_idol.boulder'

    boulder = {
        'Id': 'golden_idol.boulder',
        'TextKey': TAKE_TEXT,
        'Options': [
            {
                'Label': 'Outrun',
                'Effects': [{'Effect': 'curse:injury', 'Amount': 1}],
                'Next': '',
            },
            {
                'Label': 'Smash',
                'Effects': [{'Effect': 'damage_pct:25', 'Amount': 0}],
                'EffectsAsc': [{'Effect': 'damage_pct:35', 'Amount': 0}],
                'Next': '',
            },
            {
                'Label': 'Hide',
                'Effects': [{'Effect': 'max_hp_pct:8', 'Amount': 0}],
                'EffectsAsc': [{'Effect': 'max_hp_pct:10', 'Amount': 0}],
                'Next': '',
            },
        ],
    }
    assert boulder['Id'] not in nodes, 'already migrated'
    doc['EventNodes'].append(boulder)

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('golden_idol: 2 steps, 3 escape options (wiki percentages)')


main()
