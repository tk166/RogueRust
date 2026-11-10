"""§323 负控：三处各弄坏一次，看判据是否**在预期位置**红，然后一定写回。"""

import io
import json
import subprocess
import sys

CHECK = 'native/sts_content_check.py'
CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'


def run(argv, cwd=None):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return p.stdout + p.stderr


def report(label, needle, output):
    hit = needle in output
    print('  %-40s %s' % (label, 'RED at the expected place' if hit
                          else 'NO -- not caught (%r)' % needle))
    return hit


def mutated(path, old, new, label, action):
    raw = io.open(path, encoding='utf-8').read()
    assert old in raw, '%s: pattern missing' % label
    broken = raw.replace(old, new)
    assert broken != raw
    ok = False
    try:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(broken)
        ok = action()
    finally:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

# ── 1. 内核跳表少了 `MaskedBandits`（事件池名解析不出来）─────────────────────────
ok &= mutated(
    'kernel/rd-core/src/content.rs',
    '            "MaskedBandits" => "EncounterTables.MaskedBandits",\n',
    '',
    '事件池跳表少一条',
    lambda: report('事件池跳表少一条', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-core', '--release',
                        'the_encounter_pools'], cwd='kernel')))

# ── 2. 内容门的意图闭集（把 `AttackDefend` 放回内容）────────────────────────────
raw = io.open(CONTENT, encoding='utf-8').read()
doc = json.loads(raw)
for a in doc['EnemyActions']:
    if a['Id'] == 'bear.lunge':
        a['Intent']['Kind'] = 'AttackDefend'
try:
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    run([sys.executable, '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'])
    out = run([sys.executable, '-X', 'utf8', 'native/sts_content_check.py'])
    ok &= report('意图词表外的 AttackDefend', 'outside the kernel', out)
finally:
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
    run([sys.executable, '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'])

# ── 3. 怪物名单少一条（roster / 计数两边都对不上）──────────────────────────────
ok &= mutated(
    CHECK,
    '    ("pointy", 30, 30, ["pointy.special"]),\n',
    '',
    '怪物名单少 Pointy',
    lambda: report('怪物名单少 Pointy', 'STS_CONTENT FAIL',
                   run([sys.executable, '-X', 'utf8', 'native/sts_content_check.py'])))

print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
