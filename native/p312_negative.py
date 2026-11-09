"""§312 负控：两种"看起来能跑"的实现都必须让 `malleable_...` 红。

1. 计数器**不递增**（`Relative: false`）⇒ 每下都只给 3（"越挨越多"没了）；
2. 去掉 `TurnStarted` 的清零 ⇒ 下一回合第一下给 4（"每回合重置"没了）。

只测"会长"的判据会放过第 2 种，只测"会清"的会放过第 1 种 —— 所以判据两侧都测，这里两侧
都反证一次。
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


def malleable(doc):
    return next(s for s in doc['Statuses'] if s['Id'] == 'standard.malleable')


def main():
    original = io.open(CONTENT, encoding='utf-8').read()
    bad = 0
    try:
        for label, mutate in (
            ('计数器不递增', 'relative'),
            ('去掉回合清零', 'noreset'),
        ):
            doc = json.loads(original)
            status = malleable(doc)
            if mutate == 'relative':
                for trigger in status['Triggers']:
                    if trigger['Event'] == 'DamageTaken':
                        node = trigger['Program']['Root']['value']['Then']['value']['Children'][1]
                        assert node['kind'] == 'node.setCombatantCounter'
                        node['value']['Relative'] = False
            else:
                status['Triggers'] = [t for t in status['Triggers']
                                      if t['Event'] != 'TurnStarted']
                assert len(status['Triggers']) == 1
            io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
                json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
            built = run(['python', '-X', 'utf8', BUILD, '--package', 'sts'])
            if 'CONTENTC_BUILD OK' not in (built.stdout or '') + (built.stderr or ''):
                print('build failed for', label)
                bad += 1
                continue
            out = run([CARGO, 'test', '-p', 'rd-wasm', '--manifest-path', MANIFEST, '--release',
                       '--', '--test-threads=1', 'malleable'])
            blob = (out.stdout or '') + (out.stderr or '')
            red = 'test result: FAILED' in blob or 'panicked' in blob or 'error[' in blob
            print('%-16s -> %s' % (label, 'RED (good)' if red else 'STILL GREEN (bad!)'))
            if not red:
                bad += 1
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
        run(['python', '-X', 'utf8', BUILD, '--package', 'sts'])
    print('负控完成：%d/2 按预期变红' % (2 - bad))
    sys.exit(1 if bad else 0)


main()
