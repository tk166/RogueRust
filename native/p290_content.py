"""§290 内容 + 门：`The Nest`（Act 2）—— `card:<id>` 的第一位真实用户。

wiki（两个来源一致）：

    [Smash and Grab]  得 99 金币（A15 **50**）
    [Stay in Line]    得 Ritual Dagger，掉 6 血
    （没有"拒绝"选项：两个都得选一个）

`Ritual Dagger` 本身已经在内容里（1 费、Special Attack、Deal 15 damage、If Fatal 永久 +3（+ 版 +5）、
Exhaust），每副本成长 `standard.ritual_dagger_bonus` 也在 §253 实现过。所以这一节要做的只有
"事件怎么给这张牌"。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
GATE = 'D:/Vibe/sts-tui/native/sts_content_check.py'

DOUBLE = [{'Effect': 'nothing', 'Amount': 0}]


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))

    INTRO = ('A long line of hooded figures can be seen entering an unassuming cathedral. Naturally, '
             'you join the line and are quickly surrounded by Cultists! They ignore you as they '
             'gleefully chant and wave their weapons around. You eye a Donation Box...')
    GRABBED = 'They didn\'t even notice.'
    DAGGER = ('You decide to stay in line (out of fear) to see what will happen. A well-dressed '
              'cultist hands you an Ornate Dagger. Like the others before you, you slash your '
              'forearm and let the blood drip into a misshapen bowl.')

    built = [
        {
            'Id': 'the_nest',
            'TextKey': INTRO,
            'Options': [
                {
                    'Label': 'Smash and Grab',
                    # 99 → A15 50（wiki：`Obtain 99 (50) Gold`）。
                    'Effects': [{'Effect': 'gold', 'Amount': 99}],
                    'EffectsAsc': [{'Effect': 'gold', 'Amount': 50}],
                    'Next': 'the_nest.grabbed',
                },
                {
                    'Label': 'Stay in Line',
                    # §290：`card:<id>` 的第一位真实用户。
                    'Effects': [{'Effect': 'card:ritual_dagger', 'Amount': 0},
                                {'Effect': 'damage', 'Amount': 6}],
                    'Next': 'the_nest.dagger',
                },
            ],
        },
        {'Id': 'the_nest.grabbed', 'TextKey': GRABBED,
         'Options': [{'Label': 'Leave', 'Effects': list(DOUBLE), 'Next': ''}]},
        {'Id': 'the_nest.dagger', 'TextKey': DAGGER,
         'Options': [{'Label': 'Leave', 'Effects': list(DOUBLE), 'Next': ''}]},
    ]

    drop = {n['Id'] for n in doc['EventNodes'] if n['Id'].startswith('the_nest')}
    doc['EventNodes'] = [n for n in doc['EventNodes'] if n['Id'] not in drop] + built
    doc['UnknownRooms'] = [r for r in doc['UnknownRooms'] if r['Id'] != 'the_nest']
    doc['UnknownRooms'].append({'Id': 'the_nest', 'NameKey': 'The Nest', 'Entry': 'the_nest'})
    rows = [row for row in doc['EventTables']['Events2'] if row['Id'] != 'the_nest']
    rows.append({'Id': 'the_nest'})
    doc['EventTables']['Events2'] = rows

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: the_nest (3 steps)')

    # ── 门：两个新词
    g = io.open(GATE, encoding='utf-8').read()
    old = '''                    if kind == "curse" and payload:'''
    new = '''                    if kind == "card" and payload:
                        # §290：给**指定**的一张牌（`The Nest` 的 `Ritual Dagger`）。
                        # 稀有度不限制（`Special` 也要能加），但 id 必须在 `Cards` 里 ——
                        # 一个拼错的 id 会变成牌组里一张幽灵卡，直到某场战斗抽到它才暴露。
                        counts["effects"] += 1
                        if payload not in cards:
                            fail(where, "card:%s 不是内容里的卡" % payload)
                        continue
                    if kind == "curse" and payload:'''
    assert g.count(old) == 1, g.count(old)
    g = g.replace(old, new)

    old2 = '''                    if effect in EVENT_BARE_EFFECTS:'''
    new2 = '''                    if effect == "gold_all":
                        # §290：失去**全部**金币（`Masked Bandits` 的 `[Pay]`）。
                        if entry.get("Amount") not in (0, None):
                            fail(where, "gold_all takes no Amount (the run decides the sum)")
                        counts["bare"] += 1
                        counts["effects"] += 1
                        continue
                    if effect in EVENT_BARE_EFFECTS:'''
    assert g.count(old2) == 1, g.count(old2)
    g = g.replace(old2, new2)
    io.open(GATE, 'w', encoding='utf-8', newline='\n').write(g)
    print('gate: card:<id> / gold_all')


main()
