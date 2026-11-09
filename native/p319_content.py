"""§319 —— `falling`（Act 3，wiki 原文三条都是"**随机**失去一张该类型的牌"）。

| 选项 | 效果 | 条件（wiki：没有该类型就没有这个按钮） |
|---|---|---|
| Land | 随机失去一张 Skill | 牌组里有 skill |
| Channel | 随机失去一张 Power | 牌组里有 power |
| Strike | 随机失去一张 Attack | 牌组里有 attack |
| （兜底）Land | 什么都不发生 | 攻击/技能/能力**一种都没有** |

兜底那一条是 wiki 明写的特例：*"If the player somehow manages to lack even a single eligible
card … the only option listed is a special [Land] option that has no description."*
三条 `lacks` 原子正好用满 `MAX_REQUIREMENTS`（4）里的一格空余。
"""

import io
import json

PATH = 'tools/contentc/packages/sts/sts.roguedeck.json'


def kind(kind_name):
    return [{'Kind': 'card_tag', 'Op': 'has', 'Id': kind_name}]


def lacks(kind_name):
    return {'Kind': 'card_tag', 'Op': 'lacks', 'Id': kind_name}


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    ids = {node['Id'] for node in doc['EventNodes']}
    assert 'falling' not in ids, 'already patched'

    falling = {
        'Id': 'falling',
        'TextKey': ('Hopping from one floating shape to another, you slip. The void opens '
                    'beneath you and there is just a moment to choose how you meet it.'),
        'Options': [
            {
                'Label': 'Land (lose a random Skill)',
                'Requires': kind('skill'),
                'Effects': [{'Effect': 'remove_card_random:skill', 'Amount': 0}],
                'Next': '',
            },
            {
                'Label': 'Channel (lose a random Power)',
                'Requires': kind('power'),
                'Effects': [{'Effect': 'remove_card_random:power', 'Amount': 0}],
                'Next': '',
            },
            {
                'Label': 'Strike (lose a random Attack)',
                'Requires': kind('attack'),
                'Effects': [{'Effect': 'remove_card_random:attack', 'Amount': 0}],
                'Next': '',
            },
            {
                # wiki 的特例：一张能用的牌都没有时的唯一一条 [Land]。
                'Label': 'Land',
                'Requires': [lacks('attack'), lacks('skill'), lacks('power')],
                'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                'Next': '',
            },
        ],
    }

    doc['EventNodes'].append(falling)
    doc['EventTables']['Events3'].append('falling')

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('event nodes %d events3 %d'
          % (len(doc['EventNodes']), len(doc['EventTables']['Events3'])))


main()
