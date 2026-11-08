"""§285 内容：Scrap Ooze / World of Goop / Wing Statue（Act 1）+ The Joust（Act 2）。

两套原语就够：**选项带概率分支**（`Chance` + `NextFail`）与**区间金币**（`gold_random`）。

wiki（两处独立来源一致）：

* `Scrap Ooze`（Act 1）：`[Reach Inside]` 掉 3（A15 5）血、**25%** 找遗物；失败可再来，
  每次 +1 血、+10% 概率，最多 9 次（9 次是 105% ⇒ 必得）。
* `World of Goop`（Act 1）：`[Gather Gold]` 得 75 金币、掉 11 血；
  `[Leave It]` 掉 **20-50（A15 35-75）** 金币，且"不会超过手上金币"。
* `Wing Statue`（Act 1）：`[Pray]` 删一张牌、掉 7 血；`[Destroy]` 得 **50-80** 金币
  （wiki 还要求"牌组里有单次 ≥10 伤害的攻击牌" —— **我们还没有那个条件**，见偏差）。
* `The Joust`（Act 2，>50 金币才遇到）：`[Murderer]` 押 50、**70%** 赢 100；
  `[Owner]` 押 50、**30%** 赢 250；**没有 Leave**。

两条实现上的约定（都写进偏差表）：

1. **奖励在"结果屏"的 Leave 上兑**：效果挂在**选项**上，而"赢了多少"由掷骰决定去哪个屏 ——
   所以赢屏的 `[Leave]` 带 `gold:100`。代价是多一次点击；机制上不需要新东西。
2. `Wing Statue` 的"牌组里有 ≥10 伤害的攻击牌"这个条件**表达不了**（我们的条件词表只有
   "有没有这张牌"，没有"某张牌的伤害"）⇒ 该选项**总是出现**，记偏差。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

LEAVE = [{'Label': 'Leave', 'Effects': [{'Effect': 'nothing', 'Amount': 0}], 'Next': ''}]


def leave_with(*effects, label='Leave'):
    return {'Label': label, 'Effects': list(effects), 'Next': ''}


def node(node_id, text, options):
    return {'Id': node_id, 'TextKey': text, 'Options': options}


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    rooms = {room['Id'] for room in doc['UnknownRooms']}
    drop = {'scrap_pile', 'world_of_goop', 'wing_statue', 'the_joust'}
    drop |= {n['Id'] for n in doc['EventNodes']
             if any(n['Id'].startswith(prefix + '.') for prefix in
                    ('scrap_pile', 'world_of_goop', 'wing_statue', 'the_joust'))}
    doc['UnknownRooms'] = [r for r in doc['UnknownRooms'] if r['Id'] not in drop]
    doc['EventNodes'] = [n for n in doc['EventNodes'] if n['Id'] not in drop]
    doc['EventTables']['Events'] = [r for r in doc['EventTables']['Events']
                                    if r['Id'] not in drop]
    doc['EventTables']['Events2'] = [r for r in doc['EventTables']['Events2']
                                     if r['Id'] not in drop]
    rooms = {room['Id'] for room in doc['UnknownRooms']}

    # ── ① Scrap Ooze：9 段链，每段一个"再来一次" ────────────────────────────
    # wiki 的表就是 9 行：HP 3..11（A15 5..13）、概率 25..105（105 视作 100）。
    OOZE = ('As you walk into the room you hear a gurgling and the grinding of metals. Before you is '
            'a slime-like creature that ate too much scrap for its own good.')
    OOZE_FAIL = ('Ouch! All you find is corroded metal and a bit of burning pain. However, you are '
                 'still convinced there is a relic in there.')
    OOZE_FOUND = ('Success! After rummaging through the metal and burning acid, you finally grab hold '
                  'of a relic and yank it out.')
    hp = [3, 4, 5, 6, 7, 8, 9, 10, 11]
    chance = [25, 35, 45, 55, 65, 75, 85, 95, 100]

    def ooze_step(index):
        """第 `index`（0 基）次尝试的那一段。"""
        is_first = index == 0
        is_last = index == len(hp) - 1
        node_id = 'scrap_pile' if is_first else 'scrap_pile.try%d' % (index + 1)
        next_fail = ('scrap_pile.found' if is_last
                     else ('scrap_pile.try2' if index == 0 else 'scrap_pile.try%d' % (index + 2)))
        reach = {
            'Label': 'Reach Inside' if is_first else 'Deeper',
            'Effects': [{'Effect': 'damage', 'Amount': hp[index]}],
            'EffectsAsc': [{'Effect': 'damage', 'Amount': hp[index] + 2}],
            'Next': 'scrap_pile.found',
        }
        # 最后一次是必然成功（wiki: 105%），所以**不掷骰**：没有 `Chance` 就不消耗随机流。
        if not is_last:
            reach['Chance'] = chance[index]
            reach['NextFail'] = next_fail
        text = OOZE if is_first else OOZE_FAIL
        doc['EventNodes'].append(node(node_id, text, [reach, *LEAVE]))

    for index in range(len(hp)):
        ooze_step(index)
    doc['EventNodes'].append(node('scrap_pile.found', OOZE_FOUND, [
        # 遗物在这一屏的 Leave 上兑（见文件头的约定 1）。
        leave_with({'Effect': 'relic_random', 'Amount': 0}),
    ]))
    doc['UnknownRooms'].append({'Id': 'scrap_pile', 'NameKey': 'Scrap Ooze',
                                'Entry': 'scrap_pile'})

    # ── ② World of Goop ──────────────────────────────────────────────────────
    GOOP = ('You fall into a puddle. IT\'S MADE OF SLIME GOOP!! Frantically, you claw yourself out '
            'over several minutes as you feel the goop starting to burn. Some of your gold is missing.')
    doc['EventNodes'].extend([
        node('world_of_goop', GOOP, [
            {'Label': 'Gather Gold',
             'Effects': [{'Effect': 'gold', 'Amount': 75},
                         {'Effect': 'damage', 'Amount': 11}],
             'Next': 'world_of_goop.gathered'},
            {'Label': 'Leave It',
             # 20-50（A15 35-75），且 `adjust_gold` 把结果夹在 0 ⇒ 正好是 wiki 的
             # "never more than the Gold you are carrying"。
             'Effects': [{'Effect': 'gold_random:-20:-50', 'Amount': 0}],
             'EffectsAsc': [{'Effect': 'gold_random:-35:-75', 'Amount': 0}],
             'Next': 'world_of_goop.left'},
        ]),
        node('world_of_goop.gathered',
             'Feeling the sting of the goop, you manage to fish out the gold.', LEAVE),
        node('world_of_goop.left', 'You decide that mess is not worth it.', LEAVE),
    ])
    doc['UnknownRooms'].append({'Id': 'world_of_goop', 'NameKey': 'World of Goop',
                                'Entry': 'world_of_goop'})

    # ── ③ Wing Statue ────────────────────────────────────────────────────────
    WING = 'A winged statue waits in the dark, wings folded over a stone basin.'
    doc['EventNodes'].extend([
        node('wing_statue', WING, [
            {'Label': 'Pray',
             'Effects': [{'Effect': 'remove_card', 'Amount': 0},
                         {'Effect': 'damage', 'Amount': 7}],
             'Next': 'wing_statue.prayed'},
            {'Label': 'Destroy',
             # ⚠️ 偏差：wiki 要求"牌组里有一张单次 ≥10 伤害的攻击牌"，而我们的条件词表
             # 只能问"有没有这张牌"，问不了"某张牌打多少" ⇒ 本项**总是**出现。
             'Effects': [{'Effect': 'gold_random:50:80', 'Amount': 0}],
             'Next': 'wing_statue.destroyed'},
            *LEAVE,
        ]),
        node('wing_statue.prayed', 'The wings close. Something in you is lighter.', LEAVE),
        node('wing_statue.destroyed', 'Gold spills out of the broken basin.', LEAVE),
    ])
    doc['UnknownRooms'].append({'Id': 'wing_statue', 'NameKey': 'Wing Statue',
                                'Entry': 'wing_statue'})

    # ── ④ The Joust（Act 2）─────────────────────────────────────────────────
    JOUST_1 = ('As you make your way through the large buildings you come across a long narrow '
               'bridge and spot knights on either side, facing one another.')
    JOUST_2 = ('"Today is the day I must settle the score with the murderer of my beloved pet, '
               'Noodles. Fellow witness, why don\'t you bet on who you think will emerge victorious?"')
    WATCH = 'CRASH!!! KLAAAANG! POW!'
    doc['EventNodes'].extend([
        node('the_joust', JOUST_1, [{'Label': 'Continue', 'Effects': [],
                                    'Next': 'the_joust.offer'}]),
        node('the_joust.offer', JOUST_2, [
            # 押 50 立刻付掉（`gold_cost` 付不起就拒），掷骰决定去赢屏还是输屏。
            {'Label': 'Murderer (bet 50)',
             'Effects': [{'Effect': 'gold_cost:50', 'Amount': 0}],
             'Chance': 70, 'Next': 'the_joust.murderer_won',
             'NextFail': 'the_joust.murderer_lost'},
            {'Label': 'Owner (bet 50)',
             'Effects': [{'Effect': 'gold_cost:50', 'Amount': 0}],
             'Chance': 30, 'Next': 'the_joust.owner_won',
             'NextFail': 'the_joust.owner_lost'},
        ]),
        node('the_joust.murderer_won', WATCH + ' The owner died. You win the bet.',
             [leave_with({'Effect': 'gold', 'Amount': 100})]),
        node('the_joust.murderer_lost', WATCH + ' The nemesis was slain. You lost the bet.',
             LEAVE),
        node('the_joust.owner_won', WATCH + ' The nemesis was slain. You win the bet.',
             [leave_with({'Effect': 'gold', 'Amount': 250})]),
        node('the_joust.owner_lost', WATCH + ' The owner died. You lost the bet.', LEAVE),
    ])
    doc['UnknownRooms'].append({'Id': 'the_joust', 'NameKey': 'The Joust',
                                'Entry': 'the_joust'})

    # ── ⑤ 池子：三个 Act 1 进 `Events`，The Joust 进 `Events2` ────────────────
    for pool, ident in (('Events', 'scrap_pile'), ('Events', 'world_of_goop'),
                        ('Events', 'wing_statue'), ('Events2', 'the_joust')):
        rows = [row for row in doc['EventTables'][pool] if row['Id'] != ident]
        if not any(row['Id'] == ident for row in rows):
            rows.append({'Id': ident})
        doc['EventTables'][pool] = rows

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('events: scrap_pile(9 steps) / world_of_goop / wing_statue / the_joust')
    print('pools:', {k: len(v) for k, v in doc['EventTables'].items()})


main()
