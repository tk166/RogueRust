"""§320 负控：三处各弄坏一次，看判据是否**在预期位置**红，然后**一定**写回。

（第一版没有 `try/finally`：第一条负控红了之后脚本在"第二遍读到的已经不是原文件"上断言失败，
于是把 `ui_panels.js` 的坏版本留在了盘上。这正是 §4.16 那条"负控失败先 `git diff`"的形状。）
"""

import io
import json
import subprocess
import sys

PANELS = 'web/ui_panels.js'
STATE = 'kernel/rd-run/src/state.rs'
CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
NODE = 'C:/Program Files/nodejs/node.exe'


def run(argv, cwd=None):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return p.stdout + p.stderr


def report(label, needle, output):
    hit = needle in output
    print('  %-42s %s' % (label, 'RED at the expected place' if hit
                          else 'NO -- not caught (%r)' % needle))
    return hit


def mutate_then_restore(path, old, new, label, action):
    raw = io.open(path, encoding='utf-8').read()
    assert old in raw, '%s: pattern missing (already broken?)' % label
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

# ── 1. 面板写死 3 行（20 选 1 那一侧必须红）─────────────────────────────────────
ok &= mutate_then_restore(
    PANELS,
    'const rows = (s.eventOffer || []).map((card) => ({',
    'const rows = (s.eventOffer || []).slice(0, 3).map((card) => ({',
    '面板写死 3 行',
    lambda: report('面板写死 3 行', 'the panel shows 3 rows', run([NODE, 'web/ui_test.mjs'])))

# ── 2. 内核忽略过滤（无色池会抽出有色牌）─────────────────────────────────────────
ok &= mutate_then_restore(
    STATE,
    '            Self::Colorless => card.colorless,',
    '            Self::Colorless => true,',
    '过滤被忽略',
    lambda: report('过滤被忽略', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-run', '--release',
                        'an_event_offer_shows'], cwd='kernel')))

# ── 3. 内容写 21 张（超过 `MAX_EVENT_OFFER`）────────────────────────────────────
raw = io.open(CONTENT, encoding='utf-8').read()
doc = json.loads(raw)
node = next(n for n in doc['EventNodes'] if n['Id'] == 'the_library')
original = node['Options'][1]['Effects'][0]['Effect']
node['Options'][1]['Effects'][0]['Effect'] = 'offer_cards:21:any'
try:
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    # ⚠️ 内容门第一条是"镜像与源码同代"：只改 JSON 会让它红在 [0]，那不算这条负控的证据。
    run([sys.executable, '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'])
    ok &= report('内容写 21 张候选', '不在 1..=20',
                 run([sys.executable, '-X', 'utf8', 'native/sts_content_check.py']))
finally:
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
    run([sys.executable, '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'])
    assert original == 'offer_cards:20:any'

print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
