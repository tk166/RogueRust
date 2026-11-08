"""§286 内容：`Chance`/`NextFail` → `Branches`，加 `EntryEffects`（到达时兑）与 Dead Adventurer。

## `Branches` 的写法

    "Branches": [{"Weight": 70, "Next": "the_joust.murderer_won"},
                 {"Weight": 30, "Next": "the_joust.murderer_lost"}]

权重和 = 100（内容门查）。A15 那一版写 `BranchesAsc`。

## Dead Adventurer 的形状（wiki 两个来源一致）

* 一次 `[Search]`：**25%**（A15 **35%**）精英伏击；否则从"还没拿到的奖励"里**随机**一个：
  30 金币 / 一件随机遗物 / 什么都没有。
* 每个奖励**只出现一次** ⇒ 树按"还剩下哪些"分叉：搜索段 1 + 3 + 3 = 7，奖励段 3 + 6 + 3 = 12。
* 每次搜索 +25 个百分点（25/50/75，A15 35/60/85）。
* 被伏击 ⇒ `[Fight]`，**战斗结算这个房间**（战后不回到事件）。

## 奖励在**到达**时兑

"你找到了 30 金币"这一屏的 `Effects` 就是"进入这一段时给 30 金币"。它替掉了 §285 那种
"在 `[Leave]` 上兑"的写法 —— 玩家不用为了领奖多点一次。
"""
import io
import json
from itertools import combinations

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
ALL = ('g', 'r', 'n')
TEXT = {
    'g': 'You found some gold! Continue searching?',
    'r': 'You found a relic! Continue searching?',
    'n': 'Hmm, couldn\'t find anything... Continue searching?',
}
EFFECT = {
    'g': [{'Effect': 'gold', 'Amount': 30}],
    'r': [{'Effect': 'relic_random', 'Amount': 0}],
    'n': [{'Effect': 'nothing', 'Amount': 0}],
}
NOTHING = [{'Effect': 'nothing', 'Amount': 0}]
ENSEMBLE = (('You come across a dead adventurer on the floor. His pants have been stolen! '
             'Though his possessions are still intact, you\'re in no mind to find out what '
             'happened here...'))
CONTINUE_TEXT = 'Continue searching?'
AMBUSH_TEXT = 'While searching the adventurer you are caught off guard!'
AMBUSH = [25, 50, 75]
AMBUSH_ASC = [35, 60, 85]


def branches(*pairs):
    return [{'Weight': w, 'Next': n} for w, n in pairs]


def share(total, count):
    """把 `total` 分成 `count` 份，余数给最后一档（权重和必须**恰好** 100）。"""
    each = total // count
    weights = [each] * count
    weights[-1] += total - each * count
    return weights


def suffix(remaining):
    return ''.join(remaining) if remaining else 'none'


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    nodes = {n['Id']: n for n in doc['EventNodes']}

    # ── ① Scrap Ooze：Chance/NextFail → Branches
    for index, chance in enumerate([25, 35, 45, 55, 65, 75, 85, 95], start=1):
        node_id = 'scrap_pile' if index == 1 else 'scrap_pile.try%d' % index
        reach = nodes[node_id]['Options'][0]
        fail = reach.pop('NextFail')
        del reach['Chance']
        reach['Branches'] = branches((chance, reach.pop('Next')), (100 - chance, fail))

    # ── ② The Joust：70/30 与 30/70
    offer = nodes['the_joust.offer']
    for option, some, other in ((offer['Options'][0], 'the_joust.murderer_won',
                                 'the_joust.murderer_lost'),
                                (offer['Options'][1], 'the_joust.owner_won',
                                 'the_joust.owner_lost')):
        chance = option.pop('Chance')
        fail = option.pop('NextFail')
        del option['Next']
        option['Branches'] = branches((chance, some), (100 - chance, fail))

    # ── ③ 奖赏改成"到达时兑"：The Joust 的赢屏（Scrap Ooze 的发现屏本来就在 Leave 上）
    for node_id in ('scrap_pile.found', 'the_joust.murderer_won', 'the_joust.owner_won'):
        node = nodes[node_id]
        leave = node['Options'][0]
        carried = [e for e in leave['Effects'] if e['Effect'] != 'nothing']
        leave['Effects'] = list(NOTHING)
        if carried:
            node['Effects'] = carried

    # ── ④ Dead Adventurer
    built = []
    for attempt in (1, 2, 3):
        for remaining in combinations(ALL, len(ALL) - (attempt - 1)):
            remaining = list(remaining)
            node_id = ('dead_adventurer' if attempt == 1
                       else 'dead_adventurer.%d.%s' % (attempt, suffix(remaining)))
            ambush, ambush_asc = AMBUSH[attempt - 1], AMBUSH_ASC[attempt - 1]
            pick = [('dead_adventurer.found.%d.%s.%s'
                     % (attempt, reward, suffix([r for r in remaining if r != reward])))
                    for reward in remaining]
            weights = share(100 - ambush, len(remaining))
            weights_asc = share(100 - ambush_asc, len(remaining))
            built.append({
                'Id': node_id,
                'TextKey': ENSEMBLE if attempt == 1 else CONTINUE_TEXT,
                'Options': [
                    {
                        'Label': 'Search' if attempt == 1 else 'Continue',
                        'Effects': list(NOTHING),
                        'Branches': branches(*([[ambush, 'dead_adventurer.ambush']]
                                               + [[weights[i], pick[i]]
                                                  for i in range(len(remaining))])),
                        'BranchesAsc': branches(*([[ambush_asc, 'dead_adventurer.ambush']]
                                                  + [[weights_asc[i], pick[i]]
                                                     for i in range(len(remaining))])),
                    },
                    {'Label': 'Leave', 'Effects': list(NOTHING), 'Next': ''},
                ],
            })
            for reward in remaining:
                rest = [r for r in remaining if r != reward]
                found_id = ('dead_adventurer.found.%d.%s.%s'
                            % (attempt, reward, suffix(rest)))
                options = [{'Label': 'Leave', 'Effects': list(NOTHING), 'Next': ''}]
                if rest:
                    options.insert(0, {
                        'Label': 'Continue',
                        'Effects': list(NOTHING),
                        'Next': 'dead_adventurer.%d.%s' % (attempt + 1, suffix(rest)),
                    })
                built.append({
                    'Id': found_id,
                    'TextKey': TEXT[reward],
                    # §286：**到达时**兑。
                    'Effects': EFFECT[reward],
                    'Options': options,
                })
    built.append({
        'Id': 'dead_adventurer.ambush',
        'TextKey': AMBUSH_TEXT,
        'Options': [{'Label': 'Fight', 'Effects': [], 'Fight': 'elite', 'Next': ''}],
    })

    drop = {n['Id'] for n in doc['EventNodes'] if n['Id'].startswith('dead_adventurer')}
    doc['EventNodes'] = [n for n in doc['EventNodes'] if n['Id'] not in drop] + built
    doc['UnknownRooms'] = [r for r in doc['UnknownRooms'] if r['Id'] != 'dead_adventurer']
    doc['UnknownRooms'].append({'Id': 'dead_adventurer', 'NameKey': 'Dead Adventurer',
                                'Entry': 'dead_adventurer'})
    rows = [row for row in doc['EventTables']['Events'] if row['Id'] != 'dead_adventurer']
    rows.append({'Id': 'dead_adventurer'})
    doc['EventTables']['Events'] = rows

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: Branches + entry effects + Dead Adventurer (%d steps)' % len(built))


main()
