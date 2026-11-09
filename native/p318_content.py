"""§318 Act 3 的事件（2 / 6）：`Winding Halls` 与 `Mysterious Sphere`。

wiki 事实（两处独立来源）。

**Winding Halls**（`Winding Halls` 页 + `SlaySpireDB`）三个选项：
| 选项 | 效果 | A15 |
|---|---|---|
| Embrace Madness | 得 2 张 **Madness**，失去 X HP（X = MaxHP 的 12.5%） | 18% |
| Focus | 得诅咒 **Writhe**，回复 X HP（X = MaxHP 的 25%） | 20% |
| Retrace Your Steps | 失去 X **最大** HP（5%） | 同 |

**Mysterious Sphere**（`Mysterious Sphere` 页 + Fandom 页）：
`[Open Sphere]` 打**两只 Orb Walker**；奖励是一件 **Rare 遗物** + 45-55 金币 + 一张卡
（+ 可能有药水）—— 也就是"一场普通战斗的奖励 + 指定稀有度的遗物"。`[Leave]` 什么都不发生。

两条都只用既有原子：`card:<id>` / `damage_pct` / `heal_pct` / `curse:<id>` / `max_hp_pct`
与 §286 的事件中途开战斗 + §288 的 `fight_*` 奖励覆盖。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    ids = {n['Id'] for n in doc['EventNodes']}
    assert 'winding_halls' not in ids and 'mysterious_sphere' not in ids

    # ── 1. Winding Halls ──────────────────────────────────────────────────────────────────
    winding = [
        {
            'Id': 'winding_halls',
            'TextKey': ('The twisting pathways keep folding back on themselves. The whispers '
                        'suggest three ways out.'),
            'Options': [
                {
                    'Label': 'Embrace Madness',
                    'Effects': [{'Effect': 'card:madness', 'Amount': 2},
                                {'Effect': 'damage_pct:12.5', 'Amount': 0}],
                    # A15：从 12.5% 变成 18%（wiki 的 `(18%)`）。
                    'EffectsAsc': [{'Effect': 'card:madness', 'Amount': 2},
                                   {'Effect': 'damage_pct:18', 'Amount': 0}],
                    'Next': 'winding_halls.madness',
                },
                {
                    'Label': 'Focus',
                    'Effects': [{'Effect': 'curse:writhe', 'Amount': 1},
                                {'Effect': 'heal_pct:25', 'Amount': 0}],
                    # A15：25% → 20%（回复**变少**，这就是这一档"变糟"的含义）。
                    'EffectsAsc': [{'Effect': 'curse:writhe', 'Amount': 1},
                                   {'Effect': 'heal_pct:20', 'Amount': 0}],
                    'Next': 'winding_halls.focus',
                },
                {
                    'Label': 'Retrace Your Steps',
                    'Effects': [{'Effect': 'max_hp_pct:5', 'Amount': 0}],
                    'Next': 'winding_halls.retrace',
                },
            ],
        },
        {
            'Id': 'winding_halls.madness',
            'TextKey': ('Something in you cracks. The chattering voices finally make sense — '
                        'and the way out is obvious.'),
            'Options': [],
        },
        {
            'Id': 'winding_halls.focus',
            'TextKey': ('You stop and stare at the shifting walls until they hold still. '
                        'Your head clears; something still itches under your skin.'),
            'Options': [],
        },
        {
            'Id': 'winding_halls.retrace',
            'TextKey': ('You spend what seems like an eternity lost, then retrace your steps '
                        'out of the passages. You feel drained.'),
            'Options': [],
        },
    ]

    # ── 2. Mysterious Sphere（事件中途开战斗，§286）────────────────────────────────────────
    sphere = [
        {
            'Id': 'mysterious_sphere',
            'TextKey': ('A bony sphere surrounds a mysterious glowing object. Sentries keep an '
                        'eye on it.'),
            'Options': [
                {
                    'Label': 'Open Sphere',
                    # 稀有遗物（wiki: "Reward: Rare Relic"）；金币/卡/药水由普通战斗奖励给。
                    'Effects': [{'Effect': 'fight_relic_rarity:rare', 'Amount': 0}],
                    'Fight': 'monster',
                    'Encounter': 'MysteriousSphere',
                    'After': 'mysterious_sphere.after',
                    'Next': '',
                },
                {
                    'Label': 'Leave',
                    'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                    'Next': '',
                },
            ],
        },
        {
            'Id': 'mysterious_sphere.after',
            'TextKey': ('The sentries collapse. Inside the broken sphere something old and '
                        'valuable is still humming.'),
            'Options': [],
        },
    ]

    # ── 3. 两只 Orb Walker 的遭遇（事件专属）──────────────────────────────────────────────
    orb = next(e for e in doc['Encounters'] if e['Id']['Value'] == 'enc_orb_walker')
    orb_enemy = json.loads(json.dumps(orb['Enemies'][0]))
    two_orbs = {
        'Id': {'Value': 'enc_two_orb_walkers'},
        'Enemies': [dict(orb_enemy, Position=None), dict(orb_enemy, Position=None)],
        'HeroResources': [{'Resource': {'value': 'standard.energy'}, 'Current': 3, 'Max': 3}],
        'HeroStartingStatuses': [],
        'TriggeredEffects': [],
        'HeroDisplayName': None,
        'CardsDrawnPerTurn': None,
    }

    doc['EventNodes'].extend(winding + sphere)
    doc['EventTables']['Events3'].extend(['winding_halls', 'mysterious_sphere'])
    doc['Encounters'].append(two_orbs)
    doc['EncounterTables']['MysteriousSphere'] = [{'Id': 'enc_two_orb_walkers'}]

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('event nodes %d events3 %d encounters %d'
          % (len(doc['EventNodes']), len(doc['EventTables']['Events3']),
             len(doc['Encounters'])))


main()
