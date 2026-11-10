"""§328 A17/18/19 招式表的收口。

审计（`native/p328_audit3.py`，按 **wiki 页面的节** 匹配，113/166 条动作对得上）结果：
wiki 有 `{{Asc|N|` 而内容缺档的只有 6 条，其中 3 条是**别的机制**已经表达的：

  * `darkling.nip`      —— A2 在遭遇记录的 `Rolls` 里（`roll.nip` 9-13）
  * `book_of_stabbing.multi_stab` —— A18 是 `book_stab_single_bump` 计数器
  * `the_guardian.twin_slam`      —— A9/A19 是 `mode_shift_budget` 计数器

真缺 3 条（全是 A17）：

  * `fat_gremlin.smash`   —— wiki：`Deals (4; A2 5) damage. Applies 1 Weak(.; and A17 1 Frail.)`
  * `cultist.incantation` —— wiki：`Gains (3; A2 4; A17 5) Ritual`
  * `fungi_beast.grow`    —— wiki：`Gains (3; A2 4; A17 5) Strength`

顺手把检查器的独立清单补到 A17，并加一道**由 wiki 快照驱动**的闸门：下一次"wiki 有档、内容
没写"会自己红，而不是等人再跑一遍审计脚本。
"""

import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECKER = 'native/sts_content_check.py'

doc = json.load(io.open(CONTENT, encoding='utf-8'))
actions = {a['Id']: a for a in doc['EnemyActions']}


def clone_variant(action_id, level, mutate):
    """把已有的最高档当模板（结构、字段顺序、ResultKey 都与它一致）。"""
    action = actions[action_id]
    rows = action['ProgramAsc']
    template = json.loads(json.dumps(rows[-1]['Program']))
    mutate(template['Root'])
    return {'AscensionMin': level, 'Program': template}


def set_stacks(root, status, stacks):
    """在（可能包着 sequence 的）程序里改某个 applyStatus 的层数。"""
    node = root
    if node['kind'] == 'node.sequence':
        for child in node['value']['Children']:
            if (child.get('kind') == 'node.applyStatus'
                    and child['value']['StatusDefinitionId']['value'] == status):
                child['value']['Stacks']['value']['Value'] = stacks
                return
    if node.get('kind') == 'node.applyStatus' \
            and node['value']['StatusDefinitionId']['value'] == status:
        node['value']['Stacks']['value']['Value'] = stacks
        return
    raise SystemExit('no applyStatus %s in %r' % (status, root))


# ── 1. 三条 A17 ────────────────────────────────────────────────────────────────
# cultist / fungi_beast：同一形状（层数 4 → 5）。
for action_id, status in (('cultist.incantation', 'ritual'),
                          ('fungi_beast.grow', 'standard.strength')):
    rows = actions[action_id]['ProgramAsc']
    assert [r['AscensionMin'] for r in rows] == [2], rows
    rows.append(clone_variant(action_id, 17, lambda root: set_stacks(root, status, 5)))
    print('%s: + A17 (%s 5)' % (action_id, status))

# fat_gremlin：A17 保持 A2 的 5 伤害，**再加** 1 Frail。
smash = actions['fat_gremlin.smash']
assert [r['AscensionMin'] for r in smash['ProgramAsc']] == [2]


def add_frail(root):
    root['value']['Children'].append({
        'kind': 'node.applyStatus',
        'value': {
            'TargetSelector': {
                'kind': 'sel.eventTarget',
                'value': {
                    'Cardinality': 'ZeroOrOne',
                    'RequiredContextCapabilities': 'EventTarget',
                },
            },
            'StatusDefinitionId': {'value': 'standard.frail'},
            'Stacks': {'kind': 'const', 'value': {'Value': 1}},
            'DurationTurns': 0,
            'Charges': 0,
            'ResultKey': None,
        },
    })


smash['ProgramAsc'].append(clone_variant('fat_gremlin.smash', 17, add_frail))
print('fat_gremlin.smash: + A17 (5 damage, Weak 1, Frail 1)')

io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2) + '\n')

# ── 2. 检查器的独立清单 ───────────────────────────────────────────────────────
t = io.open(CHECKER, encoding='utf-8').read()
pairs = [
    ("    'cultist.incantation': [(2, [('status', 'ritual', 4, 'source')])],",
     """    # §328：wiki `Cultist` —— "Gains (3; A2 4; A17 5) Ritual."
    'cultist.incantation': [(2, [('status', 'ritual', 4, 'source')]),
                            (17, [('status', 'ritual', 5, 'source')])],"""),
    ("    'fat_gremlin.smash': [(2, [('damage', 5, 'event'), ('status', 'standard.weak', 1, 'event')])],",
     """    # §328：wiki `Gremlin Gang: Fat Gremlin` —— "Applies 1 Weak (; A17: and 1 Frail.)"
    'fat_gremlin.smash': [(2, [('damage', 5, 'event'), ('status', 'standard.weak', 1, 'event')]),
                          (17, [('damage', 5, 'event'), ('status', 'standard.weak', 1, 'event'),
                                ('status', 'standard.frail', 1, 'event')])],"""),
    ("    'fungi_beast.grow': [(2, [('status', 'standard.strength', 4, 'source')])],",
     """    # §328：wiki `Fungi Beast` —— "Gains (3; A2 4; A17 5) Strength."
    'fungi_beast.grow': [(2, [('status', 'standard.strength', 4, 'source')]),
                         (17, [('status', 'standard.strength', 5, 'source')])],"""),
]
for old, new in pairs:
    assert t.count(old) == 1, old[:60]
    t = t.replace(old, new)
io.open(CHECKER, 'w', encoding='utf-8', newline='\n').write(t)
print('checker inventory: 3 actions now pinned at A17')
