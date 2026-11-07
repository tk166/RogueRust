"""§280 内容：`the_cleric`（Act 1，花金币）与 `the_moai_head`（Act 3，换金像）。

wiki（wiki.gg + slayspiredb，两处一致）：

The Cleric（Act 1，**只在有 35 金币以上时才遇得到**）
  [Heal]   35 金币 → 回复最大 HP 的 25%（A15 不变）
  [Purify] 50 金币（**A15 75**）→ 删一张牌
  [Leave]
  → 三支各有一个"段"

The Moai Head（Act 3，**只在有金像或 HP ≤ 50% 时遇得到**）
  [Jump Inside]      回满血，**然后**失去最大 HP 的 12.5%（A15 18%）
  [Offer: Golden Idol] 只在**持有金像**时出现 → 失去金像、得 333 金币
  [Leave]

⚠️ 两条事件的"何时出现"是**事件级**条件（进入前就要判），而我们的条件只在**选项**上。
所以这里实现的是选项级的那一半，事件级的那一半记在 `docs/event-gaps.md` 里当缺口 ——
不假装它已经做了。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

CLERIC_BODY = ('A strange blue humanoid with a golden helm approaches you with a huge smile. '
               '"Hello friend! I am Cleric! Are you interested in my services?!" he shouts, loudly.')
CLERIC_HEAL = ('A warm golden light envelops your body and dissipates. The creature grins. '
               '"Cleric best healer. Have a good day!"')
CLERIC_PURIFY = ('A cold blue flame envelops your body and dissipates. The creature grins. '
                 '"Cleric talented. Have a good day!"')
CLERIC_LEAVE = 'You don\'t trust this "Cleric", so you leave.'

MOAI_BODY = ('Before you, an enormous stony head emerges from a large wall segment. The head\'s '
             'mouth is wide open, and it reveals large intimidating teeth stained red with blood.')
MOAI_INSIDE = ('The huge molars slam down from above, crushing you whole. Darkness. Sometime later '
               'you see a sliver of light, and hear the sound of stony teeth slowly rising upwards.')
MOAI_OFFER = ('You jump back as the gigantic molars smash down on the idol, grinding it into dust. '
              'As the teeth rise again, gold pours forth in a torrent from the opening.')
MOAI_LEAVE = 'You leave, wondering what could have been.'

LEAVE_ONLY = [{'Label': 'Leave', 'Effects': [{'Effect': 'nothing', 'Amount': 0}], 'Next': ''}]


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    rooms = {room['Id']: room for room in doc['UnknownRooms']}

    # ── The Cleric ────────────────────────────────────────────────────────────
    if 'the_cleric' not in rooms:
        doc['UnknownRooms'].append({'Id': 'the_cleric', 'NameKey': 'The Cleric',
                                    'Entry': 'the_cleric'})
    doc['EventNodes'] = [node for node in doc['EventNodes']
                         if node['Id'] not in ('the_cleric', 'the_cleric.heal',
                                               'the_cleric.purify', 'the_cleric.declined')]
    doc['EventNodes'].append({
        'Id': 'the_cleric',
        'TextKey': CLERIC_BODY,
        'Options': [
            {
                'Label': 'Heal (35 Gold)',
                # 付得起才画：35 金币以下这一项不该出现（wiki 的 `[Locked] Requires: 35 Gold`）。
                'Requires': [{'Kind': 'gold', 'Op': 'at_least', 'Amount': 35}],
                'Effects': [
                    {'Effect': 'gold_cost:35', 'Amount': 0},
                    {'Effect': 'heal_pct:25', 'Amount': 0},
                ],
                'Next': 'the_cleric.heal',
            },
            {
                'Label': 'Purify (50 Gold)',
                # ★ A15 的价格是 75，所以**条件**也要有 A15 变体 —— 否则 50..74 金币的
                # A15 玩家会看到一个点下去被拒的按钮。
                'Requires': [{'Kind': 'gold', 'Op': 'at_least', 'Amount': 50}],
                'RequiresAsc': [{'Kind': 'gold', 'Op': 'at_least', 'Amount': 75}],
                'Effects': [
                    {'Effect': 'gold_cost:50', 'Amount': 0},
                    {'Effect': 'remove_card', 'Amount': 0},
                ],
                'EffectsAsc': [
                    {'Effect': 'gold_cost:75', 'Amount': 0},
                    {'Effect': 'remove_card', 'Amount': 0},
                ],
                'Next': 'the_cleric.purify',
            },
            {
                'Label': 'Leave',
                'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                'Next': 'the_cleric.declined',
            },
        ],
    })
    for node_id, text in (
        ('the_cleric.heal', CLERIC_HEAL),
        ('the_cleric.purify', CLERIC_PURIFY),
        ('the_cleric.declined', CLERIC_LEAVE),
    ):
        doc['EventNodes'].append({'Id': node_id, 'TextKey': text, 'Options': LEAVE_ONLY})

    # ── The Moai Head ─────────────────────────────────────────────────────────
    if 'the_moai_head' not in rooms:
        doc['UnknownRooms'].append({'Id': 'the_moai_head', 'NameKey': 'The Moai Head',
                                    'Entry': 'the_moai_head'})
    doc['EventNodes'] = [node for node in doc['EventNodes']
                         if node['Id'] not in ('the_moai_head', 'the_moai_head.inside',
                                               'the_moai_head.offer', 'the_moai_head.leave')]
    doc['EventNodes'].append({
        'Id': 'the_moai_head',
        'TextKey': MOAI_BODY,
        'Options': [
            {
                'Label': 'Jump Inside',
                # ⚠️ 顺序是 wiki 的：**先回满血**，再失去最大 HP（否则先掉上限会少回血）。
                'Effects': [
                    {'Effect': 'heal_full', 'Amount': 0},
                    {'Effect': 'max_hp_pct:12.5', 'Amount': 0},
                ],
                'EffectsAsc': [
                    {'Effect': 'heal_full', 'Amount': 0},
                    {'Effect': 'max_hp_pct:18', 'Amount': 0},
                ],
                'Next': 'the_moai_head.inside',
            },
            {
                'Label': 'Offer: Golden Idol',
                'Requires': [{'Kind': 'relic', 'Op': 'has', 'Id': 'golden_idol'}],
                'Effects': [
                    {'Effect': 'relic_lose:golden_idol', 'Amount': 1},
                    {'Effect': 'gold', 'Amount': 333},
                ],
                'Next': 'the_moai_head.offer',
            },
            {
                'Label': 'Leave',
                'Effects': [{'Effect': 'nothing', 'Amount': 0}],
                'Next': 'the_moai_head.leave',
            },
        ],
    })
    for node_id, text in (
        ('the_moai_head.inside', MOAI_INSIDE),
        ('the_moai_head.offer', MOAI_OFFER),
        ('the_moai_head.leave', MOAI_LEAVE),
    ):
        doc['EventNodes'].append({'Id': node_id, 'TextKey': text, 'Options': LEAVE_ONLY})

    # ── 幕数归属（顺手修两条错位：ssssserpent 是 Act 1、forgotten_altar 是 Act 2）───
    tables = doc['EventTables']
    tables['Events'] = [row for row in tables['Events'] if row['Id'] != 'the_ssssserpent']
    tables['Events3'] = [row for row in tables['Events3'] if row['Id'] != 'the_ssssserpent']
    tables['Events'] = [row for row in tables['Events'] if row['Id'] != 'forgotten_altar']
    for name, wanted in (('Events', 'the_ssssserpent'), ('Events2', 'forgotten_altar'),
                         ('Events', 'the_cleric'), ('Events3', 'the_moai_head')):
        rows = tables[name]
        if not any(row['Id'] == wanted for row in rows):
            rows.append({'Id': wanted})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('the_cleric (Act 1, 2 conditional options) + the_moai_head (Act 3, 1 conditional); '
          'pools: %s' % {k: len(v) for k, v in tables.items()})


main()
