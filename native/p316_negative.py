"""§316 负控：Shapes 的两条机制各自抓什么。

1. 去掉 `exploder.explode` 的 `destroyCombatant` ⇒ `the_exploder_hits_for_thirty_and_then_dies`
   必须红（"打完还站着"）。
2. 把 `repulsor.daze` 的落区改成 `DiscardPile` ⇒ `the_repulsor_puts_two_dazed_into_the_draw_pile`
   必须红（"张数对、落区错"—— 只数张数的判据会放过它）。
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


def drop_destroy(doc):
    action = next(a for a in doc['EnemyActions'] if a['Id'] == 'exploder.explode')
    children = action['Program']['Root']['value']['Children']
    kept = [c for c in children if c['kind'] != 'node.destroyCombatant']
    assert len(kept) == len(children) - 1
    action['Program']['Root']['value']['Children'] = kept


def wrong_zone(doc):
    action = next(a for a in doc['EnemyActions'] if a['Id'] == 'repulsor.daze')
    for child in action['Program']['Root']['value']['Children']:
        if child['kind'] == 'node.createCardInstance':
            assert child['value']['ToZone'] == 'DrawPile'
            child['value']['ToZone'] = 'DiscardPile'
            return
    raise AssertionError('no createCardInstance')


CASES = [
    ('Explode 不自毁', drop_destroy, 'the_exploder_hits_for_thirty'),
    ('Daze 进弃牌堆', wrong_zone, 'the_repulsor_puts_two_dazed'),
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
                print('%-16s -> BUILD FAILED' % label)
                bad += 1
                continue
            out = run([CARGO, 'test', '-p', 'rd-wasm', '--manifest-path', MANIFEST, '--release',
                       '--', '--test-threads=1', test])
            blob = (out.stdout or '') + (out.stderr or '')
            red = 'test result: FAILED' in blob or 'panicked' in blob or 'error[' in blob
            print('%-16s -> %s' % (label, 'RED (good)' if red else 'STILL GREEN (bad!)'))
            if not red:
                bad += 1
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(original)
        run(['python', '-X', 'utf8', BUILD, '--package', 'sts'])
    print('负控完成：%d/%d 按预期变红' % (len(CASES) - bad, len(CASES)))
    sys.exit(1 if bad else 0)


main()
