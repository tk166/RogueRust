"""§287 内容：Wing Statue 的条件、Dead Adventurer 的战后补偿、醒着的 Lagavulin 池。

## ① `Wing Statue` 的 `[Destroy]`

wiki："Shown only if your deck holds a card dealing **10 or more damage per hit**."
⇒ `Requires: [{Kind: "card_damage", Op: "at_least", Amount: 10}]`。

## ② `Dead Adventurer` 的战后补偿

伏击段按"还剩下哪些奖励"分叉（7 种，与搜索段一一对应），每段带**进入效果**：

* 金币还没搜到 ⇒ `fight_gold_bonus: 30`（这一场战斗多掉 30 金币）；
* 遗物已经搜到 ⇒ `fight_no_relic`（这一场不掉遗物，否则重复）。

## ③ 醒着的 Lagavulin

`EncounterTables.EliteEvent` = 三个 Act 1 精英，其中 Lagavulin 用 `enc_lagavulin_awake`：
没有 `standard.lagavulin_asleep`、`lagavulin_step` 初值 2 ⇒ 第一回合就是 Siphon Soul。
伏击的选项写 `{"Fight": "elite", "Encounter": "EliteEvent"}`。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
ALL = ('g', 'r', 'n')


def suffix(remaining):
    return ''.join(remaining) if remaining else 'none'


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    nodes = {n['Id']: n for n in doc['EventNodes']}

    # ── ① Wing Statue 的 [Destroy] 条件
    wing = nodes['wing_statue']
    destroy = wing['Options'][1]
    assert destroy['Label'] == 'Destroy', destroy['Label']
    destroy['Requires'] = [{'Kind': 'card_damage', 'Op': 'at_least', 'Amount': 10}]

    # ── ② 伏击段按"剩余奖励"分叉
    ambush_old = nodes['dead_adventurer.ambush']
    generated = []
    for attempt in (1, 2, 3):
        count = len(ALL) - (attempt - 1)
        from itertools import combinations
        for remaining in combinations(ALL, count):
            remaining = list(remaining)
            node_id = 'dead_adventurer.ambush.%s' % suffix(remaining)
            effects = []
            if 'g' in remaining:
                # 30 金币还没搜到 ⇒ 这一场战斗补发。
                effects.append({'Effect': 'fight_gold_bonus', 'Amount': 30})
            if 'r' not in remaining:
                # 遗物已经拿到过 ⇒ 这一场不掉遗物（wiki 明写"不会重复掉"）。
                effects.append({'Effect': 'fight_no_relic', 'Amount': 0})
            generated.append({
                'Id': node_id,
                'TextKey': ambush_old['TextKey'],
                'Effects': effects,
                'Options': [{
                    'Label': 'Fight',
                    'Effects': [],
                    'Fight': 'elite',
                    # §287：事件自己的精英池 —— 里面的 Lagavulin 是**醒着**的。
                    'Encounter': 'EliteEvent',
                    'Next': '',
                }],
            })
    # 搜索段的分支改指向对应的伏击段
    for node in doc['EventNodes']:
        if not node['Id'].startswith('dead_adventurer'):
            continue
        for option in node['Options']:
            for key in ('Branches', 'BranchesAsc'):
                for branch in option.get(key) or []:
                    if branch['Next'] == 'dead_adventurer.ambush':
                        # 这一段搜索知道"还剩下哪些"：从自己的 id 里读。
                        ident = node['Id']
                        if ident == 'dead_adventurer':
                            rest = ['g', 'r', 'n']
                        else:
                            rest = ident.split('.')[-1]
                            rest = [c for c in rest]
                        branch['Next'] = 'dead_adventurer.ambush.%s' % suffix(rest)

    doc['EventNodes'] = [n for n in doc['EventNodes']
                         if n['Id'] != 'dead_adventurer.ambush'] + generated

    # ── ③ 醒着的 Lagavulin + 事件精英池
    encounters = doc['Encounters']
    base = None
    for entry in encounters:
        if entry['Id'] == {'Value': 'enc_lagavulin'}:
            base = entry
    assert base is not None, 'enc_lagavulin is missing'
    awake = json.loads(json.dumps(base))
    awake['Id'] = {'Value': 'enc_lagavulin_awake'}
    enemy = awake['Enemies'][0]
    enemy['StartingStatuses'] = [s for s in enemy['StartingStatuses']
                                 if s['StatusDefinitionId']['value'] != 'standard.lagavulin_asleep']
    # 意图规则按 `lagavulin_step` 选招（0/1 → 攻击，2 → Siphon Soul）⇒ 初值 2 让它先抽魂。
    enemy['Counters'] = [{'Key': 'lagavulin_step', 'Value': 2}]
    encounters = [e for e in encounters if e['Id'] != awake['Id']]
    encounters.append(awake)
    doc['Encounters'] = encounters

    doc['EncounterTables']['EliteEvent'] = [
        {'Id': 'enc_three_sentries', 'Weight': 1},
        {'Id': 'enc_gremlin_nob', 'Weight': 1},
        {'Id': 'enc_lagavulin_awake', 'Weight': 1},
    ]
    doc['EncounterTables']['Note'] = (
        (doc['EncounterTables'].get('Note') or '') +
        ' §287：`EliteEvent` 是**事件**引来的精英（今天的唯一用户是 `Dead Adventurer` 的伏击），'
        '其中的 Lagavulin 用醒着的变体（wiki：这场伏击里它不进入睡眠，第一回合 Siphon Soul）。')

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: wing statue condition / ambush debt (%d nodes) / awake lagavulin'
          % len(generated))


main()
