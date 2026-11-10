"""§325 Act 1 的三条：`big_fish` / `living_wall` / `mushrooms`（Hypnotizing Colored Mushrooms）。

wiki 原文：

**Big Fish**
- `[Banana]` Heal **1/3** 上限（向下取整）→ `heal_pct:33`
- `[Donut]` 上限 **+5**（并且这 5 点直接补上）→ `max_hp:5`（`GainMaxHealth` 就是"上限与当前血一起加"）
- `[Box]` 得**随机**遗物 + 诅咒 **Regret** → `relic_random` + `curse:regret`
- 三个选项之后都给一个 `[Leave]`

**Living Wall**
- `[Forget]` 删一张 / `[Change]` 改造一张 / `[Grow]` 升级一张 —— 三条都是**既有的** `DeckChange`

**Hypnotizing Colored Mushrooms**（Act 1，**只在第 7 层及以后**出现）
- `[Stomp]` 打 **3 只 Fungus Beast**；胜利给专属遗物 **Odd Mushroom** + 常规战斗奖励
- `[Eat]` 回 **25%** 上限 + 诅咒 **Parasite**

⚠️ 两处需要记住的事实：
1. `odd_mushroom` 的"易伤只受 25%"**早就实现了**（§264 的 `OverrideScope: Self` 幅值改写），
   所以这里一句内核都不用改。
2. `parasite` 的程序是**空的**："被变形/移除时 -3 上限"**没有**实现 —— 这条如实记成偏差
   （`rd-run` 不读内容，把卡 id 写进 `remove_at` 会违反 §133 的分层）。
"""

import io
import json

PATH = 'tools/contentc/packages/sts/sts.roguedeck.json'


def leave_step(step_id, text):
    return {
        'Id': step_id,
        'TextKey': text,
        'Options': [{'Label': 'Leave', 'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                     'Next': ''}],
    }


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    have = {n['Id'] for n in doc['EventNodes']}
    wanted = ['big_fish', 'living_wall', 'mushrooms']
    assert not any(name in have for name in wanted), 'already patched'

    nodes = [
        # ── Big Fish ────────────────────────────────────────────────────────────────
        {
            'Id': 'big_fish',
            'TextKey': ('A banana, a donut and a box float in the corridor, tied to strings '
                        'from holes in the ceiling. Somewhere above, something giggles.'),
            'Options': [
                {'Label': 'Banana (heal 1/3)',
                 'Effects': [{'Effect': 'heal_pct:33', 'Amount': 0}],
                 'Next': 'big_fish.after'},
                {'Label': 'Donut (max HP +5)',
                 'Effects': [{'Effect': 'max_hp:5', 'Amount': 5}],
                 'Next': 'big_fish.after'},
                {'Label': 'Box (random relic + Regret)',
                 'Effects': [{'Effect': 'relic_random', 'Amount': 0},
                             {'Effect': 'curse:regret', 'Amount': 1}],
                 'Next': 'big_fish.after'},
            ],
        },
        leave_step('big_fish.after',
                   'Whatever you picked, the strings go slack and the cackling stops.'),
        # ── Living Wall ────────────────────────────────────────────────────────────
        {
            'Id': 'living_wall',
            'TextKey': ('Walls slam down from the ceiling. Three faces form in the stone: '
                        '"Forget what you know." "I require change." "You must grow."'),
            'Options': [
                {'Label': 'Forget (remove a card)',
                 'Effects': [{'Effect': 'remove_card', 'Amount': 0}],
                 'Next': 'living_wall.after'},
                {'Label': 'Change (transform a card)',
                 'Effects': [{'Effect': 'transform_card', 'Amount': 0}],
                 'Next': 'living_wall.after'},
                {'Label': 'Grow (upgrade a card)',
                 'Effects': [{'Effect': 'upgrade_card', 'Amount': 0}],
                 'Next': 'living_wall.after'},
            ],
        },
        leave_step('living_wall.after',
                   'Satisfied, the faces sink back into the stone and a path opens.'),
        # ── Hypnotizing Colored Mushrooms ──────────────────────────────────────────
        {
            'Id': 'mushrooms',
            'TextKey': ('A corridor of hypnotizing colored mushrooms. You cannot name a single '
                        'one of them, and yet you are suddenly very hungry.'),
            'Options': [
                {'Label': 'Stomp (fight 3 Fungi Beasts)',
                 'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                 'Fight': 'monster',
                 'Encounter': 'Mushrooms',
                 'After': 'mushrooms.after',
                 'Next': ''},
                {'Label': 'Eat (heal 25%, Parasite)',
                 'Effects': [{'Effect': 'heal_pct:25', 'Amount': 0},
                             {'Effect': 'curse:parasite', 'Amount': 1}],
                 'Next': 'mushrooms.ate'},
            ],
        },
        {
            'Id': 'mushrooms.after',
            'TextKey': ('The rodents stop moving. One of the mushrooms on them is oddly '
                        'familiar, and it fits in your pocket.'),
            'Options': [{'Label': 'Take the Odd Mushroom',
                         'Effects': [{'Effect': 'relic:odd_mushroom', 'Amount': 0}],
                         'Next': ''}],
        },
        leave_step('mushrooms.ate',
                   'You wake up some time later. Everything looks a little larger.'),
    ]

    # 三只 Fungus Beast 的遭遇：抄既有的两只那一行的**敌人记录**，再加一只。
    two = next(e for e in doc['Encounters'] if e['Id']['Value'] == 'enc_two_fungi_beasts')
    beast = json.loads(json.dumps(two['Enemies'][0]))
    three = {
        'Id': {'Value': 'enc_three_fungi_beasts'},
        'Enemies': [json.loads(json.dumps(beast)) for _ in range(3)],
        'HeroResources': [{'Resource': {'value': 'standard.energy'}, 'Current': 3, 'Max': 3}],
        'HeroStartingStatuses': [],
        'TriggeredEffects': [],
        'HeroDisplayName': None,
        'CardsDrawnPerTurn': None,
    }
    for enemy in three['Enemies']:
        enemy['Position'] = None

    doc['EventNodes'].extend(nodes)
    doc['Encounters'].append(three)
    doc['EncounterTables']['Mushrooms'] = [{'Id': 'enc_three_fungi_beasts'}]
    for name in ('big_fish', 'living_wall'):
        doc['EventTables']['Events'].append({'Id': name})
    # wiki：这一条**只在第 7 层及以后**出现。
    doc['EventTables']['Events'].append({'Id': 'mushrooms', 'MinFloor': 7})
    for name in wanted:
        doc['UnknownRooms'].append({'Id': name, 'NameKey': name.replace('_', ' ').title(),
                                    'Entry': name})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('event nodes %d encounters %d events-pool %d rooms %d'
          % (len(doc['EventNodes']), len(doc['Encounters']),
             len(doc['EventTables']['Events']), len(doc['UnknownRooms'])))


main()
