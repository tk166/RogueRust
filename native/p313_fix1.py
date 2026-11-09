"""§313（四）：`Protect` 的 history 必须在**顶层**。

第一版把 `prev_move/last_move` 记账放在 cond 的两个分支里 —— 检查器的 `split_history` 只看
程序**顶层末尾**的那一对，于是它报"`centurion.protect` does not record `last_move`"
（真问题：那条规则确实读不到分支里的记账）。

改法：条件只管**给谁** 15 块，记账固定在顶层：
    sequence([ conditional(alive==1, block self, block mystic), prev=last, last=2 ])
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'D:/Vibe/sts-tui/native/sts_content_check.py'


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


def program_for(amount):
    return {
        'Id': {'value': '(unnamed)'},
        'Root': {'kind': 'node.sequence',
                 'value': {'Children': [
                     {'kind': 'node.conditional',
                      'value': {
                          'Condition': {'kind': 'intent.enemyAliveCount',
                                        'value': {'Op': 'Equal', 'Value': 1}},
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

    text = io.open(CHECK, encoding='utf-8').read()
    old = '''    "centurion.protect": ("Defend", [("block", 15, "alliesWithDefinition:mystic"),
                                     ("block", 15, "source")]),'''
    new = '''    # `Protect` 的两个分支各是一条 `when` 事实（条件不可静态求值 ⇒ `when None`，
    # 与 `impatience` 同一种写法）。
    "centurion.protect": ("Defend", [("when", None, "block", 15, "source"),
                                     ("when", None, "block", 15,
                                      "alliesWithDefinition:mystic")]),'''
    assert text.count(old) == 1
    text = text.replace(old, new)
    old_asc = '''    'centurion.protect': [(17, [('block', 20, 'alliesWithDefinition:mystic'),
                                ('block', 20, 'source')])],'''
    new_asc = '''    'centurion.protect': [(17, [('when', None, 'block', 20, 'source'),
                                ('when', None, 'block', 20,
                                 'alliesWithDefinition:mystic')])],'''
    assert text.count(old_asc) == 1
    text = text.replace(old_asc, new_asc)
    # 调试兜底改回严格：字段缺失就应该响亮失败。
    old_dbg = '''        "sel.alliesWithDefinition": "alliesWithDefinition:%s"
        % (selector.get("value") or {}).get("CombatantDefinitionId",
                                            "<MISSING:%r>" % (selector,)),'''
    new_dbg = '''        "sel.alliesWithDefinition": "alliesWithDefinition:%s"
        % selector["value"]["CombatantDefinitionId"],'''
    assert text.count(old_dbg) == 1
    text = text.replace(old_dbg, new_dbg)
    io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(text)
    print('protect restructured; inventory facts updated')


main()
