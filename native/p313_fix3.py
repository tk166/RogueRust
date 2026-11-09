"""§313（八）：`Protect` 的条件改用表达式 `combatantCount`。

`intent.enemyAliveCount` 只活在**意图规则**里；写在动作程序里会被 `expr.rs` 判成
`UnsupportedKind`（这一轮实测撞过）。所以程序里改用新表达式
`combatantCount{Selector: sel.allAllies}` —— 独自时它等于 1。

规则里仍然用 `intent.enemyAliveCount`（那里才是它的地盘），两者**同一个事实、两种求值位置**，
所以都写成"友军个数"而不是"有没有 Mystic"。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def sel_all_allies():
    return {'kind': 'sel.allAllies',
            'value': {'Cardinality': 'ZeroOrMore',
                      'RequiredContextCapabilities': 'Source'}}


def sel_source():
    return {'kind': 'sel.source',
            'value': {'Cardinality': 'ZeroOrOne',
                      'RequiredContextCapabilities': 'Source'}}


def const(value):
    return {'kind': 'const', 'value': {'Value': value}}


def sel_allies_with_definition(definition):
    return {'kind': 'sel.alliesWithDefinition',
            'value': {'Cardinality': 'ZeroOrMore',
                      'RequiredContextCapabilities': 'Source',
                      'CombatantDefinitionId': definition}}


def counter(counter_id):
    return {'kind': 'combatantCounter',
            'value': {'Selector': sel_source(), 'CounterId': counter_id}}


def block(selector, amount):
    return {'kind': 'node.gainBlock',
            'value': {'TargetSelector': selector, 'Amount': const(amount), 'ResultKey': None}}


def set_counter(counter_id, amount, relative=False):
    return {'kind': 'node.setCombatantCounter',
            'value': {'TargetSelector': sel_source(), 'CounterId': {'value': counter_id},
                      'Amount': amount if isinstance(amount, dict) else const(amount),
                      'Relative': relative}}


def alone_condition():
    return {'kind': 'compare',
            'value': {'Left': {'kind': 'combatantCount',
                               'value': {'Selector': sel_all_allies(), 'AliveOnly': True}},
                      'Right': const(1),
                      'Op': 'Equal'}}


def program_for(amount):
    return {
        'Id': {'value': '(unnamed)'},
        'Root': {'kind': 'node.sequence',
                 'value': {'Children': [
                     {'kind': 'node.conditional',
                      'value': {
                          'Condition': alone_condition(),
                          'Then': block(sel_source(), amount),
                          'Else': block(sel_allies_with_definition('mystic'), amount),
                      }},
                     set_counter('prev_move', counter('last_move')),
                     set_counter('last_move', 2),
                 ]}},
        'MaxNodeDepth': 64,
        'MaxProgramSteps': 1024,
    }


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    action = next(a for a in doc['EnemyActions'] if a['Id'] == 'centurion.protect')
    action['Program'] = program_for(15)
    for variant in action.get('ProgramAsc') or []:
        variant['Program'] = program_for(20)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('protect condition -> combatantCount')


main()
