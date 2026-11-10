"""§335：复核 `094d34e`（§308 RunState 字段清点）的修复**现在是否仍然成立**。

`094d34e` 修的是三件事：

1. **18 个漏网字段**补进存档与指纹（`event_step` 最坏：指纹有、存档没有）；
2. **`sample_full()` 夹具** —— 原夹具只设六个字段，于是"漏还原一个字段就红"是**假的**；
3. **闸门 22 `state-fields`** —— 穷举 `pub struct RunState` 的字段表，逐个要求出现在
   `write_payload` 与 `hash.rs` 里。

复核方式不是"读一遍代码觉得对"，而是**负控**：把某一个字段的存档写入删掉，看
`a_saved_run_round_trips_byte_identically` 是否变红。如果它不红，说明夹具又退化成默认值了 ——
那正是 `094d34e` 修的根因。

⚠️ 另外复核一件事：`094d34e` 之后我们又加了字段（§331 `event_relic_offer_*`、
§332 `shop` 的两排），所以"每加一个字段就加一行"这条纪律**有没有被遵守**也要验。
"""

import io
import subprocess
import sys

ARCHIVE = 'kernel/rd-run/src/state/archive.rs'
GATE = 'native/check_state_fields.py'


def run_test():
    p = subprocess.run(
        ['cargo', 'test', '-p', 'rd-run', '--release', '--', '--test-threads=1',
         'a_saved_run_round_trips_byte_identically'],
        cwd='kernel', capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def run_gate():
    p = subprocess.run(['python', '-X', 'utf8', GATE, '--check'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


ok = True

# ── ① 闸门本身还在跑（094d34e 的第 3 件事）──────────────────────────────────
gate_out = run_gate()
gate_ok = 'STATE_FIELDS PASS' in gate_out
print('  ① `state-fields` 闸门仍在跑 -> %s' % ('PASS' if gate_ok else 'FAIL'))
if gate_ok:
    for line in gate_out.splitlines():
        if 'STATE_FIELDS PASS' in line:
            print('      ', line.strip()[:100])
ok &= gate_ok

# ── ② 负控：删掉一个字段的存档写入，round-trip 必须红 ────────────────────────
raw = io.open(ARCHIVE, encoding='utf-8').read()
CASES = [
    # (说明, 要删掉的那一行)
    ('event_step（094d34e 里"最坏"的那个）', 'writer.id(state.event_step)?;'),
    ('bosses_fought', 'writer.byte(state.bosses_fought)?;'),
    ('pickup_potions（094d34e 的 18 个之一）', 'writer.byte(state.pickup_potions)?;'),
    ('event_relic_offer_len（§331 后加的）', 'writer.byte(state.event_relic_offer_len)?;'),
]
for label, needle in CASES:
    if needle not in raw:
        print('  %-40s SKIP (line not found: %r)' % (label, needle[:50]))
        continue
    broken = raw.replace(needle, '', 1)
    assert broken != raw
    caught = False
    try:
        io.open(ARCHIVE, 'w', encoding='utf-8', newline='\n').write(broken)
        out = run_test()
        caught = 'test result: FAILED' in out
        print('  %-40s %s' % (label, 'RED' if caught else 'NOT CAUGHT'))
    finally:
        io.open(ARCHIVE, 'w', encoding='utf-8', newline='\n').write(raw)
    ok &= caught

out = run_test()
print('  还原后：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('REVIEW_094d34e', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
