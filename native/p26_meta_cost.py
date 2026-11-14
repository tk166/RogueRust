"""§379：`cardMeta.ts` 加上 `cost` 与 `rarity`（悬浮详情要用）。

## 为什么加在生成物里

商店/奖励屏只知道**内容 id**（`bludgeon`），要显示"3 费 / 稀有"必须查内容包。
`cardMeta.ts` 已经是"内容包 → 前端的卡牌元数据"那一层（种类 + 要不要目标），
把费用与稀有度加在同一张表里，就不必为了一张提示条再引一次内容包。

## 三个取值规则（都来自内容包本身）

* `cost`：`Costs[]` 里 `standard.energy` 那一项的 `Amount`；
* X 费：`Tags` 含 `x_cost` ⇒ `cost: "X"`（内容里 `Amount` 是 0，直接显示会变成"0 费"）；
* 不可打出：`Tags` 含 `unplayable` ⇒ `cost: "-"`（诅咒/状态牌）。
"""

import io

PATH = 'native/build_zh_i18n.py'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''    meta = {}
    for card in content['Cards']:
        tags = [tag.get('value') for tag in (card.get('Tags') or [])]
        kind = next((tag for tag in ('attack', 'skill', 'power', 'status', 'curse')
                     if tag in tags), 'skill')
        program = (json.dumps(card.get('Program'), ensure_ascii=False)
                   + json.dumps(card.get('LifecyclePrograms'), ensure_ascii=False))
        meta[card['Id']] = {
            'kind': kind,
            'targeting': 'singleEnemy' if 'sel.eventTarget' in program else 'none',
        }
    print('  元数据     %3d 张（要目标 %d）' % (
        len(meta), sum(1 for row in meta.values() if row['targeting'] == 'singleEnemy')))'''

NEW = '''    meta = {}
    for card in content['Cards']:
        tags = [tag.get('value') for tag in (card.get('Tags') or [])]
        kind = next((tag for tag in ('attack', 'skill', 'power', 'status', 'curse')
                     if tag in tags), 'skill')
        program = (json.dumps(card.get('Program'), ensure_ascii=False)
                   + json.dumps(card.get('LifecyclePrograms'), ensure_ascii=False))
        # §379：费用与稀有度。三条规则都来自内容包，不猜：
        #   * 能量费 = `Costs[]` 里 `standard.energy` 的 `Amount`；
        #   * `x_cost` 标签 ⇒ "X"（内容里 Amount 是 0，直接显示会变成"0 费"）；
        #   * `unplayable` 标签 ⇒ "-"（诅咒/状态牌，没有可支付的费用）。
        energy = 0
        for cost in card.get('Costs') or []:
            if (cost.get('ResourceId') or {}).get('value') == 'standard.energy':
                energy = cost.get('Amount') or 0
                break
        if 'x_cost' in tags:
            cost = 'X'
        elif 'unplayable' in tags:
            cost = '-'
        else:
            cost = energy
        meta[card['Id']] = {
            'kind': kind,
            'targeting': 'singleEnemy' if 'sel.eventTarget' in program else 'none',
            'cost': cost,
            'rarity': card.get('Rarity') or 'Common',
        }
    print('  元数据     %3d 张（要目标 %d、X 费 %d、不可打出 %d）' % (
        len(meta),
        sum(1 for row in meta.values() if row['targeting'] == 'singleEnemy'),
        sum(1 for row in meta.values() if row['cost'] == 'X'),
        sum(1 for row in meta.values() if row['cost'] == '-')))'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD2 = '''            'export interface CardMeta {',
            '  readonly kind: "attack" | "skill" | "power" | "status" | "curse";',
            '  readonly targeting: "none" | "singleEnemy";',
            '}','''
NEW2 = '''            'export interface CardMeta {',
            '  readonly kind: "attack" | "skill" | "power" | "status" | "curse";',
            '  readonly targeting: "none" | "singleEnemy";',
            '  /** 能量费；`"X"` = X 费牌，`"-"` = 不可打出（诅咒/状态）。 */',
            '  readonly cost: number | "X" | "-";',
            '  /** 内容包的 `Rarity`（`Common` / `Uncommon` / `Rare` / …）。 */',
            '  readonly rarity: string;',
            '}','''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)

OLD3 = '''            '// 「种类」与「要不要玩家选目标」都来自内容包（`Cards[].Tags` + 程序里的 `sel.eventTarget`）。','''
NEW3 = '''            '// 「种类」「要不要玩家选目标」「费用」「稀有度」都来自内容包',
            '// （`Cards[].Tags` + `Costs[]` + `Rarity` + 程序里的 `sel.eventTarget`）。','''
assert t.count(OLD3) == 1
t = t.replace(OLD3, NEW3)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('build_zh_i18n.py: cost + rarity')
