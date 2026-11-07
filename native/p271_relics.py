"""§271 内容：`standard.ancient_tea_set`（抄 `lantern` 的程序，只改两个数）+ `standard.sozu`。

`lantern` 的形状是"`TurnStarted` + 计数器 == 0 ⇒ 加 1 能量，然后计数器 +1"，也就是
"**第一回合** +1 能量"。`ancient_tea_set` 是同一句话、数字变 2 —— 所以**复制**那条程序并改
`Amount` 与计数器名，而不是手写一份 IR（手写 IR 是这一批最容易出错的地方，而错法很隐蔽）。
"""
import copy
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def spec(pipeline, operation, magnitude):
    return {
        'Pipeline': pipeline, 'Operation': operation, 'Magnitude': magnitude,
        'Priority': 100, 'RestrictDamageKind': None,
        'AppliesToStatusId': None, 'RestrictSourceCardTag': None,
    }


def buff(definition_id, name, text, modifiers=None, triggers=None):
    return {
        'Id': definition_id, 'PackageId': 'sts', 'NameKey': name, 'DescriptionKey': text,
        'Polarity': 'Buff', 'UsesStacks': True, 'UsesDuration': False, 'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        'Tags': ['buff'], 'PassiveModifiers': modifiers or [], 'Triggers': triggers or [],
    }


def iter_nodes(node):
    """把 JSON 里所有 `{"kind": ..., "value": ...}` 节点摊平。"""
    if isinstance(node, dict):
        if 'kind' in node:
            yield node
        for value in node.values():
            yield from iter_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_nodes(item)


def rename_energy(program, counter):
    """把 `lantern` 的程序改成"第一回合 +2 能量、计数器叫 `counter`"。

    ⚠️ 必须**总是**递归：IR 的中间节点（`node.conditional` 的 `value`）本身没有 `kind`，
    只按 `kind` 判断就会在那一层停住 —— 第一版就是这么写的，自检 `amounts == [2]` 立刻报
    "got [1]"。这就是自检存在的理由。
    """
    def walk(node):
        if isinstance(node, dict):
            kind = node.get('kind')
            if kind == 'node.gainResource':
                node['value']['Amount']['value']['Value'] = 2
            elif kind == 'combatantCounter':
                node['value']['CounterId'] = counter
            elif kind == 'node.setCombatantCounter':
                node['value']['CounterId']['value'] = counter
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(program)
    return program


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    statuses = {row['Id']: row for row in doc['Statuses']}

    lantern = statuses.get('standard.lantern')
    assert lantern is not None, 'the lantern row must exist (its program is the shape we copy)'

    # ---- `ancient_tea_set`：同一句话、数字 2。
    row = buff(
        'standard.ancient_tea_set', 'Ancient Tea Set',
        'Gain 2 Energy on the first turn of the next combat after a Rest Site.',
        triggers=copy.deepcopy(lantern['Triggers']))
    rename_energy(row['Triggers'], 'tea_set_turns')
    # 自检：真的改成 2 了，而且没有再引用 lantern 的计数器（抄错就是这个样子）。
    blob = json.dumps(row['Triggers'], ensure_ascii=False, separators=(',', ':'))
    # ⚠️ 比**解析后的数**，不比 `"Value": 2` 这种带空格的文本：`json.dumps` 的间距不是判据。
    amounts = [n['value']['Amount']['value']['Value'] for n in iter_nodes(row['Triggers'])
               if n.get('kind') == 'node.gainResource']
    assert amounts == [2], 'the energy amount must be 2, got %r' % (amounts,)
    assert 'lantern_turns' not in blob, 'the copied program must not share lantern counters'
    assert 'tea_set_turns' in blob, 'the counter must be renamed'
    if row['Id'] in statuses:
        statuses[row['Id']].update(row)
    else:
        doc['Statuses'].append(row)
        statuses[row['Id']] = row
    print('status standard.ancient_tea_set: +2 energy on turn 1 (copied lantern shape)')

    # ---- `sozu`：每回合 +1 能量（"不能再获得药水"在运行层）。
    row = buff('standard.sozu', 'Sozu',
               'Gain 1 Energy at the start of your turn. You can no longer obtain potions.',
               modifiers=[spec('TurnStartEnergy', 'AddPerStack', 1)])
    if row['Id'] in statuses:
        statuses[row['Id']].update(row)
    else:
        doc['Statuses'].append(row)
        statuses[row['Id']] = row
    print('status standard.sozu: +1 energy per turn')

    ROWS = [
        ('meal_ticket', 'Meal Ticket', 'Common', 'shop entry heals 15'),
        ('ancient_tea_set', 'Ancient Tea Set', 'Common', '+2 energy on the next combat'),
        ('toy_ornithopter', 'Toy Ornithopter', 'Common', 'using a potion heals 5'),
        ('sozu', 'Sozu', 'Boss', '+1 energy / turn, no potions'),
        ('ssserpent_head', 'Ssserpent Head', 'Event', '+50 gold per ? room'),
    ]
    relics = {row['Id']: row for row in doc['Relics']}
    for rid, display, rarity, note in ROWS:
        relics[rid] = {
            'Id': rid, 'DisplayName': display, 'Rarity': rarity,
            'RunPrograms': None, 'CombatRules': None,
        }
        print('relic %-18s %-9s %s' % (rid, rarity, note))

    doc['Relics'] = [relics[k] for k in sorted(relics)]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: statuses %d, relics %d' % (len(doc['Statuses']), len(doc['Relics'])))


main()
