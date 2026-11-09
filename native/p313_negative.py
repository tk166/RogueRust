"""§313 负控：两条判据各自抓什么。

1. `Protect` 的"按**定义**点名 Mystic"换成"**最低血量的友军**"（`sel.lowestHealthAlly`）⇒
   `protect_gives_the_block_to_the_mystic_even_when_the_centurion_is_hurt` 必须红 ——
   这正是这两个选择器的分界线。
2. 把"独自时自保"那一半拿掉（条件恒为 false）⇒
   `protect_falls_back_to_the_centurion_when_the_mystic_is_downed` 必须红。
"""
import io
import json
import subprocess
import sys

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
BUILD = 'D:/Vibe/sts-tui/tools/contentc/build.py'
CARGO = 'C:/Users/TK11/.cargo/bin/cargo.exe'
MANIFEST = 'D:/Vibe/sts-tui/kernel/Cargo.toml'


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors='replace')


def protect_action(doc):
    return next(a for a in doc['EnemyActions'] if a['Id'] == 'centurion.protect')


def lowest_health_ally(doc):
    def mutate(program):
        cond = program['Root']['value']['Children'][0]['value']['Condition']
        cond['value']['Left'] = {
            'kind': 'combatantCount',
            'value': {'Selector': {'kind': 'sel.lowestHealthAlly',
                                   'value': {'Cardinality': 'ZeroOrOne',
                                             'RequiredContextCapabilities': 'Source'}},
                      'AliveOnly': True},
        }
    action = protect_action(doc)
    mutate(action['Program'])
    for variant in action.get('ProgramAsc') or []:
        mutate(variant['Program'])


def always_not_alone(doc):
    def mutate(program):
        cond = program['Root']['value']['Children'][0]['value']['Condition']
        # `combatantCount == 0` 恒假 ⇒ "独自"分支永远不生效。
        cond['value']['Right'] = {'kind': 'const', 'value': {'Value': 0}}
    action = protect_action(doc)
    mutate(action['Program'])
    for variant in action.get('ProgramAsc') or []:
        mutate(variant['Program'])


CASES = [
    ('按最低血量选目标', lowest_health_ally, 'protect_gives_the_block_to_the_mystic'),
    ('去掉独自分支', always_not_alone, 'protect_falls_back_to_the_centurion'),
]


def main():
    original = io.open(CONTENT, encoding='utf-8').read()
    bad = 0
    try:
        for label, mutate, test in CASES:
            doc = json.loads(original)
            mutate(doc)
            io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
                json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
            built = run(['python', '-X', 'utf8', BUILD, '--package', 'sts'])
            if 'CONTENTC_BUILD OK' not in (built.stdout or '') + (built.stderr or ''):
                print('%-18s -> BUILD FAILED' % label)
                bad += 1
                continue
            out = run([CARGO, 'test', '-p', 'rd-wasm', '--manifest-path', MANIFEST, '--release',
                       '--', '--test-threads=1', test])
            blob = (out.stdout or '') + (out.stderr or '')
            red = 'test result: FAILED' in blob or 'panicked' in blob or 'error[' in blob
            print('%-18s -> %s' % (label, 'RED (good)' if red else 'STILL GREEN (bad!)'))
            if not red:
                bad += 1
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
        run(['python', '-X', 'utf8', BUILD, '--package', 'sts'])
    print('负控完成：%d/%d 按预期变红' % (len(CASES) - bad, len(CASES)))
    sys.exit(1 if bad else 0)


main()
