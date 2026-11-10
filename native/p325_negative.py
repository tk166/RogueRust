"""§325 负控：三处各弄坏一次，看判据是否**在预期位置**红，然后一定写回。"""

import io
import json
import subprocess
import sys

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CORE = 'kernel/rd-core/src/content.rs'


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


def content_mutated(mutate, label, action):
    raw = io.open(CONTENT, encoding='utf-8').read()
    doc = json.loads(raw)
    mutate(doc)
    try:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
        run([sys.executable, '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'])
        return action()
    finally:
        io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
        run([sys.executable, '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'])


ok = True

# ── 1. 事件池跳表少了 `Mushrooms` ────────────────────────────────────────────────
ok &= mutated(
    CORE,
    '            "Mushrooms" => "EncounterTables.Mushrooms",\n',
    '',
    '池跳表少 Mushrooms',
    lambda: report('池跳表少 Mushrooms', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-core', '--release',
                        'the_encounter_pools'], cwd='kernel')))

# ── 2. Mushrooms 少了 `MinFloor: 7`（层数门槛失效）──────────────────────────────
def drop_min_floor(doc):
    for row in doc['EventTables']['Events']:
        if isinstance(row, dict) and row.get('Id') == 'mushrooms':
            row.pop('MinFloor', None)


ok &= content_mutated(
    drop_min_floor,
    'Mushrooms 少了层数门槛',
    lambda: report('Mushrooms 少了层数门槛', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-core', '--release',
                        'the_unknown_room_events'], cwd='kernel')))

# ── 3. `[Stomp]` 的遭遇从 3 只变 2 只（组合记录写错）────────────────────────────
def two_beasts(doc):
    for enc in doc['Encounters']:
        if enc['Id']['Value'] == 'enc_three_fungi_beasts':
            enc['Enemies'] = enc['Enemies'][:2]


ok &= content_mutated(
    two_beasts,
    'Stomp 只给两只',
    lambda: report('Stomp 只给两只', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-wasm', '--release', '--',
                        '--test-threads=1', 'mushrooms_stomp'], cwd='kernel')))

print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
