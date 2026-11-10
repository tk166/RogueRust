"""§328 负控。

1. 内容侧：把 `cultist.incantation` 的 A17 档删掉（回到修之前），闸门必须红在
   `asc.wiki.cultist.incantation`；
2. 闸门侧：把 `INV_ASC_LEVELS_BY_OTHER_MEANS` 里的 `the_guardian.twin_slam` 删掉 ——
   这一条是**白名单**，删掉它应当让闸门报"wiki 写了 A9/A19、内容没有"，证明白名单不是摆设
   （白名单条目每一条都必须真的被用到，否则它就是个静音开关）。
"""

import io
import json
import subprocess
import sys

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECKER = 'native/sts_content_check.py'


def build():
    subprocess.run(['python', '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')


def check():
    p = subprocess.run(['python', '-X', 'utf8', 'native/sts_content_check.py'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


ok = True

# ── 1. 删掉 cultist 的 A17 ─────────────────────────────────────────────────────
raw = io.open(CONTENT, encoding='utf-8').read()
doc = json.loads(raw)
action = [a for a in doc['EnemyActions'] if a['Id'] == 'cultist.incantation'][0]
assert [r['AscensionMin'] for r in action['ProgramAsc']] == [2, 17]
try:
    action['ProgramAsc'] = [r for r in action['ProgramAsc'] if r['AscensionMin'] != 17]
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    build()
    out = check()
    red = 'asc.wiki.cultist.incantation' in out
    print('  1. 内容删掉 A17 -> %s' % ('RED at asc.wiki.cultist.incantation' if red
                                       else 'NOT CAUGHT'))
    for line in out.splitlines():
        if 'asc.wiki' in line:
            print('     ', line.strip()[:150])
    ok &= red
finally:
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
    build()

# ── 2. 删掉一条白名单 ─────────────────────────────────────────────────────────
raw = io.open(CHECKER, encoding='utf-8').read()
needle = """    'the_guardian.twin_slam':
        "A9/A19 are the `mode_shift_budget` counter rows on the encounter, not `ProgramAsc`",
"""
assert needle in raw
try:
    io.open(CHECKER, 'w', encoding='utf-8', newline='\n').write(raw.replace(needle, ''))
    out = check()
    red = 'asc.wiki.the_guardian.twin_slam' in out
    print('  2. 删掉白名单条目 -> %s' % ('RED at asc.wiki.the_guardian.twin_slam' if red
                                         else 'NOT CAUGHT'))
    for line in out.splitlines():
        if 'asc.wiki' in line:
            print('     ', line.strip()[:150])
    ok &= red
finally:
    io.open(CHECKER, 'w', encoding='utf-8', newline='\n').write(raw)

out = check()
print('  还原后：%s' % ('green' if 'STS_CONTENT PASS' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
