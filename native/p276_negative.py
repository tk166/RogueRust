"""§276 负控（结构化版）：直接改 JSON 结构，不靠缩进匹配。

两处切口都是"真会犯的错"：
1. **`destroyCombatant` 提到 spawn 之前** —— 既有的 `phase_split` 就是这么写的（它 spawn 常量），
   照抄过来就退化成"分裂出两只满血的"：数量对、类型对、**只有血量错**。
2. **阈值从"一半最大血"改成常量 10** —— 与 Slime Boss 那条同名规则混在一起时的典型错法。
"""
import io
import json
import subprocess
import sys

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
BUILD = 'D:/Vibe/sts-tui/tools/contentc/build.py'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'
TEST = 'a_large_slime_splits_at_half_health_with_its_current_hp'


def build():
    out = subprocess.run([sys.executable, '-X', 'utf8', BUILD, '--package', 'sts'],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    return 'CONTENTC_BUILD OK' in (out.stdout + out.stderr)


def run_test():
    out = subprocess.run(
        [CARGO, 'test', '-p', 'rd-core', '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', TEST],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True, encoding='utf-8',
        errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def split_children(doc, status_id):
    status = next(s for s in doc['Statuses'] if s['Id'] == status_id)
    root = status['Triggers'][0]['Program']['Root']
    return root['value']['Then']['value']['Children']


def main():
    original = io.open(CONTENT, encoding='utf-8').read()
    failures = 0

    # ① destroy 提到最前
    doc = json.loads(original)
    for sid in ('standard.split_spike_l', 'standard.split_acid_l'):
        children = split_children(doc, sid)
        assert [c['kind'] for c in children] == [
            'node.createCombatant', 'node.createCombatant', 'node.destroyCombatant'], \
            [c['kind'] for c in children]
        children.insert(0, children.pop())
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    ok = build()
    passed, text = run_test() if ok else (True, 'build failed')
    red = ok and (not passed)
    print('%-18s -> %s  (destroy before spawn)' % (
        'split order', 'RED as expected' if red else 'STILL GREEN'))
    if not red:
        failures += 1
        print(text[-700:])
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)

    # ② 阈值改成常量 10
    doc = json.loads(original)
    for sid in ('standard.split_spike_l', 'standard.split_acid_l'):
        children = split_children(doc, sid)
        condition = doc['Statuses'] and None
    status = next(s for s in doc['Statuses'] if s['Id'] == 'standard.split_spike_l')
    cond = status['Triggers'][0]['Program']['Root']['value']['Condition']
    assert cond['kind'] == 'compare'
    cond['value']['Left'] = {'kind': 'const', 'value': {'Value': 10}}
    other = next(s for s in doc['Statuses'] if s['Id'] == 'standard.split_acid_l')
    cond2 = other['Triggers'][0]['Program']['Root']['value']['Condition']
    cond2['value']['Left'] = {'kind': 'const', 'value': {'Value': 10}}
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    ok = build()
    passed, text = run_test() if ok else (True, 'build failed')
    red = ok and (not passed)
    print('%-18s -> %s  (threshold 10, not half HP)' % (
        'split threshold', 'RED as expected' if red else 'STILL GREEN'))
    if not red:
        failures += 1
        print(text[-700:])

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
    assert build(), 'restore must rebuild'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
