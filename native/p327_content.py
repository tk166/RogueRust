"""§327 四条精英遭遇的**保真度收口**（内容在 §173/§175 就齐了，这次补的是升档数值）。

审计对照 `native/wiki_asc/*.txt`（项目自己的 wiki 快照），发现两处真偏差：

1. **`blue_slaver` / `slaver_red` 的 HP 档位**：它们是 **Normal** 型（wiki infobox
   `| Type = Normal`），`AscHP` 落在 **A7**（"普通敌人更硬"），不是 A8（"精英更硬"）。
   项目原来的规则是"档位按**池子**推"，于是这两个在 `enc_slavers`（精英池）里被写成了 A8。
   wiki.gg 与 SlaySpireDB 两个来源都写 A7，所以改 A7 + 检查器按**怪物**钉档位。
   （同一形状的镜像案例早就有了：`Sentry` 是精英怪出现在普通池里，§315 用
   `INV_ASC_HP_LEVEL` 钉成 A8。）

2. **`taskmaster.scouring_whip` 的升档**：wiki 原话
   *"Deals 7 damage. Adds (1 Wound; **A2: 2**; **A18: 3** Wounds) into your discard pile.
   (; **A18: Gains 1 Strength**.)"* —— 内容里只有一条 A3 的**空档**（与基础一模一样，
   正是"升档什么都没做"的形状）。
"""

import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECKER = 'native/sts_content_check.py'

doc = json.load(io.open(CONTENT, encoding='utf-8'))


def find_action(action_id):
    for a in doc['EnemyActions']:
        if a['Id'] == action_id:
            return a
    raise SystemExit('missing action %s' % action_id)


def find_encounter(enc_id):
    for e in doc['Encounters']:
        if e['Id']['Value'] == enc_id:
            return e
    raise SystemExit('missing encounter %s' % enc_id)


def enemy_of(encounter, enemy_id):
    hits = [en for en in encounter['Enemies'] if en['Id'] == enemy_id]
    assert len(hits) == 1, (enemy_id, len(hits))
    return hits[0]


# ── 1. Slaver 的 HP 档位 A8 → A7 ───────────────────────────────────────────────
slavers = find_encounter('enc_slavers')
for enemy_id in ('slaver_red', 'blue_slaver'):
    enemy = enemy_of(slavers, enemy_id)
    rows = enemy['MaxHealthAsc']
    assert len(rows) == 1, rows
    assert rows[0]['AscensionMin'] == 8, rows
    rows[0]['AscensionMin'] = 7
    print('enc_slavers/%s: MaxHealthAsc A8 -> A7 (%s)' % (enemy_id, rows[0]['MaxHealth']))

# ── 2. Taskmaster 的 Scouring Whip 升档 ───────────────────────────────────────
whip = find_action('taskmaster.scouring_whip')
old_asc = whip.get('ProgramAsc') or []
assert len(old_asc) == 1, 'expected the single no-op A3 row, got %r' % (old_asc,)
assert old_asc[0]['AscensionMin'] == 3

base = whip['Program']
# 基础：7 伤害 + 1 Wound（保持原样，只把它当模板）。
wound_node = None
for child in base['Root']['value']['Children']:
    if child.get('kind') == 'node.createCardInstance':
        wound_node = child
assert wound_node is not None, 'the base program adds a Wound'


def variant(wounds, strength):
    program = json.loads(json.dumps(base))  # deep copy
    for child in program['Root']['value']['Children']:
        if child.get('kind') == 'node.createCardInstance':
            child['value']['Count']['value']['Value'] = wounds
    if strength:
        program['Root']['value']['Children'].append({
            'kind': 'node.applyStatus',
            'value': {
                'TargetSelector': {
                    'kind': 'sel.source',
                    'value': {
                        'Cardinality': 'ZeroOrOne',
                        'RequiredContextCapabilities': 'Source',
                    },
                },
                'StatusDefinitionId': {'value': 'standard.strength'},
                'Stacks': {'kind': 'const', 'value': {'Value': strength}},
                'DurationTurns': 0,
                'Charges': 0,
                'ResultKey': None,
            },
        })
    return program


whip['ProgramAsc'] = [
    {'AscensionMin': 2, 'Program': variant(2, 0)},
    {'AscensionMin': 18, 'Program': variant(3, 1)},
]
# 描述与意图标签跟着走（它们会被页面直接读）。
whip['DescriptionKey'] = 'Scouring Whip — 7 damage, 1 Wound (A2: 2, A18: 3 + 1 Strength)'
print('taskmaster.scouring_whip: A3 no-op -> A2 (2 Wounds) / A18 (3 Wounds + 1 Strength)')

io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2) + '\n')

# ── 3. 检查器：档位按**怪物**，不按池子 ────────────────────────────────────────
t = io.open(CHECKER, encoding='utf-8').read()
old = """# Which ascension level owns "tougher enemies" (§187's three rules).
INV_ASC_HP_LEVEL = {'Elite': 8, 'Boss': 9}"""
new = """# Which ascension level owns "tougher enemies" (§187's three rules).
INV_ASC_HP_LEVEL = {'Elite': 8, 'Boss': 9}

# §327：**档位属于怪物，不属于池子**。默认按池子推（普通 A7 / 精英 A8 / Boss A9）是因为
# 绝大多数怪物只出现在一个档位里；但 wiki 的 `AscHP` 行是按**怪物自己**的 `Type` 定的
# （`Enemy Infobox` 的 `| Type = Normal`），所以"普通怪出现在精英遭遇里"就必须单独钉。
#
#   * `Sentry`（§315）：精英怪出现在 Act 2 的**普通**池里 ⇒ 钉 A8；
#   * `Blue Slaver` / `Red Slaver`（§327）：普通怪出现在 Act 2 的**精英**池（`Slavers`）里
#     ⇒ 钉 A7（wiki.gg 与 SlaySpireDB 都写 "Ascension 7 and up"）。
INV_ASC_HP_LEVEL_BY_MONSTER = {
    'sentry_1': 8, 'sentry_2': 8, 'sentry_3': 8,
    'blue_slaver': 7, 'slaver_red': 7,
}"""
assert t.count(old) == 1, 'checker anchor'
t = t.replace(old, new)
io.open(CHECKER, 'w', encoding='utf-8', newline='\n').write(t)
print('checker: INV_ASC_HP_LEVEL_BY_MONSTER added')
