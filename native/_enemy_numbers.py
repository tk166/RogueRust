"""把敌人动作程序里的**数字**摊平，用于与 wiki 逐条比对。

只认"数值"这一类节点（dealDamage 的 Amount、applyStatus 的 Stacks、createCardInstance 的
Count…），并且把 `const` 与 `repeat/forEach` 的次数一起打印 —— 这样"6×3"这种写法看得见。
"""
import io
import json
import sys

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def walk(node, out, depth=0):
    if isinstance(node, dict):
        kind = node.get('kind')
        value = node.get('value')
        if kind == 'node.dealDamage' and isinstance(value, dict):
            amount = value.get('Amount')
            out.append('damage(%s)' % describe(amount))
        elif kind == 'node.applyStatus' and isinstance(value, dict):
            out.append('applyStatus(%s x %s)' % (
                pick(value, 'StatusDefinitionId'), describe(value.get('Stacks'))))
        elif kind == 'node.modifyStatusStacks' and isinstance(value, dict):
            out.append('modifyStatus(%s, %s)' % (
                pick(value, 'StatusDefinitionId'), describe(value.get('Delta'))))
        elif kind == 'node.createCardInstance' and isinstance(value, dict):
            out.append('createCard(%s, %s)' % (
                pick(value, 'CardDefinitionId'), describe(value.get('Count'))))
        elif kind == 'node.repeat' and isinstance(value, dict):
            out.append('repeat x %s' % describe(value.get('Count')))
        elif kind == 'node.dealDamageToRandomTarget' and isinstance(value, dict):
            out.append('randomDamage(%s)' % describe(value.get('Amount')))
        elif kind == 'node.gainBlock' and isinstance(value, dict):
            out.append('block(%s)' % describe(value.get('Amount')))
        elif kind == 'node.createCombatant' and isinstance(value, dict):
            out.append('summon(%s, hp %s)' % (value.get('DefinitionId'), describe(value.get('Health'))))
        elif kind == 'node.destroyCombatant' and isinstance(value, dict):
            out.append('destroy')
        elif kind == 'node.setCombatantCounter' and isinstance(value, dict):
            cid = value.get('CounterId')
            cid = cid.get('value') if isinstance(cid, dict) else cid
            out.append('setCounter(%s %s)%s' % (
                cid, describe(value.get('Amount')), ' +=' if value.get('Relative') else ' ='))
        elif kind == 'node.gainResource' and isinstance(value, dict):
            out.append('resource(%s, %s)' % (pick(value, 'ResourceId'), describe(value.get('Amount'))))
        for child in node.values():
            walk(child, out, depth + 1)
    elif isinstance(node, list):
        for item in node:
            walk(item, out, depth + 1)


def pick(value, key):
    field = value.get(key)
    if isinstance(field, dict):
        return field.get('value') or field.get('Value') or '?'
    return str(field)


def describe(expr):
    if not isinstance(expr, dict):
        return str(expr)
    kind = expr.get('kind')
    value = expr.get('value')
    if kind == 'const':
        return str(value.get('Value'))
    if kind in ('add', 'subtract', 'multiply'):
        parts = [describe(x) for x in (value.get('Operands') or [])]
        op = {'add': '+', 'subtract': '-', 'multiply': '×'}[kind]
        return '(%s)' % op.join(parts)
    if kind == 'combatantCounter':
        return 'counter[%s]' % pick(value, 'CounterId')
    if kind == 'combatantStatusStacks':
        return 'stacks[%s]' % pick(value, 'StatusDefinitionId')
    if kind == 'roundNumber':
        return 'round'
    return kind


def main():
    want = sys.argv[1:] or ['lagavulin', 'book_of_stabbing', 'nemesis', 'blue_slaver',
                            'slaver_red', 'taskmaster', 'reptomancer', 'dagger']
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    ids = lambda row: row['Id']['Value'] if isinstance(row.get('Id'), dict) else row['Id']
    for action in doc['EnemyActions']:
        aid = ids(action)
        if not any(aid.startswith(prefix + '.') for prefix in want):
            continue
        print('=== %s   intent=%s' % (aid, (action.get('Intent') or {}).get('Label', '?')))
        body = []
        walk((action.get('Program') or {}).get('Root'), body)
        print('    base :', ' '.join(body) or '(empty)')
        for variant in action.get('ProgramAsc') or []:
            body = []
            walk((variant.get('Program') or {}).get('Root'), body)
            print('    A%-3d :' % variant['AscensionMin'], ' '.join(body) or '(empty)')


main()
