"""§317 负控：两条判据各自抓什么。

1. `Fading` 只自减、不判"到点消失" ⇒ `the_transient_scales_its_attack_and_fades_away` 的
   第 5 回合断言必须红（层数减到 0 会把实例连同触发器一起删掉，于是它**活着**）。
2. 攻击改成固定的 30（不随回合涨）⇒ 第 2 回合那条断言必须红。
"""
import io
import json
import subprocess
import sys

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
BUILD = 'D:/Vibe/sts-tui/tools/contentc/build.py'
CARGO = 'C:/Users/TK11/.cargo/bin/cargo.exe'
MANIFEST = 'D:/Vibe/sts-tui/kernel/Cargo.toml'
TEST = 'the_transient_scales_its_attack_and_fades_away'


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors='replace')


def fade_never_kills(doc):
    fading = next(s for s in doc['Statuses'] if s['Id'] == 'standard.fading')
    program = fading['Triggers'][0]['Program']['Root']
    assert program['kind'] == 'node.conditional'
    # 条件恒假 ⇒ 只剩"每回合 -1"这一半。
    program['value']['Condition'] = {
        'kind': 'compare',
        'value': {'Left': {'kind': 'const', 'value': {'Value': 0}},
                  'Right': {'kind': 'const', 'value': {'Value': 1}},
                  'Op': 'LessOrEqual'},
    }


def flat_attack(doc):
    action = next(a for a in doc['EnemyActions'] if a['Id'] == 'transient.attack')
    for program in [action['Program']] + [v['Program'] for v in action.get('ProgramAsc') or []]:
        damage = program['Root']['value']['Children'][0]
        assert damage['kind'] == 'node.dealDamage'
        damage['value']['Amount'] = {'kind': 'const', 'value': {'Value': 30}}


CASES = [('Fading 不杀', fade_never_kills), ('攻击不递增', flat_attack)]


def main():
    original = io.open(CONTENT, encoding='utf-8').read()
    bad = 0
    try:
        for label, mutate in CASES:
            doc = json.loads(original)
            mutate(doc)
            io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
                json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
            built = run(['python', '-X', 'utf8', BUILD, '--package', 'sts'])
            if 'CONTENTC_BUILD OK' not in (built.stdout or '') + (built.stderr or ''):
                print('%-14s -> BUILD FAILED' % label)
                bad += 1
                continue
            out = run([CARGO, 'test', '-p', 'rd-wasm', '--manifest-path', MANIFEST, '--release',
                       '--', '--test-threads=1', TEST])
            blob = (out.stdout or '') + (out.stderr or '')
            red = 'test result: FAILED' in blob or 'panicked' in blob or 'error[' in blob
            print('%-14s -> %s' % (label, 'RED (good)' if red else 'STILL GREEN (bad!)'))
            if not red:
                bad += 1
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
        run(['python', '-X', 'utf8', BUILD, '--package', 'sts'])
    print('负控完成：%d/%d 按预期变红' % (len(CASES) - bad, len(CASES)))
    sys.exit(1 if bad else 0)


main()
