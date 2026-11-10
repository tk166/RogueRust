"""§327 负控：把 A2 那一档改回 A3（修之前的样子），判据必须红在预期位置。

⚠️ 这条负控要**重编内容镜像**才有意义（内核读的是 `out/content.sts.rdcf`），所以它比
别处的负控慢一点；跑完一定把内容与镜像都还原。
"""

import io
import json
import subprocess
import sys

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'


def build():
    subprocess.run(['python', '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')


def run_test():
    p = subprocess.run(
        ['cargo', 'test', '-p', 'rd-wasm', '--release', '--', '--test-threads=1',
         'taskmaster_scouring'],
        cwd='kernel', capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


raw = io.open(CONTENT, encoding='utf-8').read()
doc = json.loads(raw)
whip = [a for a in doc['EnemyActions'] if a['Id'] == 'taskmaster.scouring_whip'][0]
assert [r['AscensionMin'] for r in whip['ProgramAsc']] == [2, 18], whip['ProgramAsc']

ok = False
try:
    whip['ProgramAsc'][0]['AscensionMin'] = 3  # 回到修之前：A2 那一档不见了
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    build()
    out = run_test()
    red = 'test result: FAILED' in out
    print('  负控：A2 档改回 A3 → %s' % ('RED at the expected place' if red else 'NOT CAUGHT'))
    for line in out.splitlines():
        if 'A2: Wounds' in line or 'panicked' in line:
            print('   ', line.strip()[:120])
    ok = red
finally:
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
    build()
    out = run_test()
    print('  还原后：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))

print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
