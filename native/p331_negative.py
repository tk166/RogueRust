"""§331 负控：两块机制各弄坏一次。

1. **事件级条件**：删掉 `tomb_of_lord_red_mask` 的 `Requires` ⇒ 内容侧判据红在
   "without the Red Mask the tomb is not in the pool at all"；
2. **候选遗物**：把 `resolve_event_effects` 里那行"清遗物候选"加回去（即修之前的 bug）
   ⇒ `N'loth` 的端到端判据红在 `UnsupportedEventEffect`。

每条都要重编内容镜像（第 1 条）或重编内核（第 2 条），跑完一定还原。
"""

import io
import json
import subprocess
import sys

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
STATE = 'kernel/rd-run/src/state.rs'


def build_content():
    subprocess.run(['python', '-X', 'utf8', 'tools/contentc/build.py', '--package', 'sts'],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')


def run(crate, name):
    p = subprocess.run(['cargo', 'test', '-p', crate, '--release', '--', '--test-threads=1', name],
                       cwd='kernel', capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return p.stdout + p.stderr


ok = True

# ── ① 删掉事件级条件 ─────────────────────────────────────────────────────────
raw = io.open(CONTENT, encoding='utf-8').read()
doc = json.loads(raw)
try:
    for row in doc['EventTables']['Events3']:
        if row['Id'] == 'tomb_of_lord_red_mask':
            row.pop('Requires', None)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    build_content()
    out = run('rd-core', 'event_level_requirements')
    hit = 'not in the pool at all' in out
    print('  ① 删掉事件级条件 -> %s' % ('RED at "not in the pool at all"' if hit else 'NOT CAUGHT'))
    ok &= hit
finally:
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(raw)
    build_content()

# ── ② 把"清遗物候选"加回去（回到修之前的 bug）───────────────────────────────
raw = io.open(STATE, encoding='utf-8').read()
needle = """        self.event_offer = [RunId::EMPTY; MAX_EVENT_OFFER];
        let mut follow: Option<DeckChange> = None;"""
assert needle in raw, 'state anchor'
try:
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(
        raw.replace(needle,
                    """        self.event_offer = [RunId::EMPTY; MAX_EVENT_OFFER];
        self.event_relic_offer_len = 0;
        let mut follow: Option<DeckChange> = None;""", 1))
    out = run('rd-wasm', 'nloth_offers_two')
    hit = 'UnsupportedEventEffect' in out
    print('  ② 清掉遗物候选 -> %s' % ('RED at UnsupportedEventEffect' if hit else 'NOT CAUGHT'))
    ok &= hit
finally:
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(raw)

out = run('rd-wasm', 'nloth')
print('  还原后：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
