"""§349 负控：四条，对应第十一轮 Review 的两条 P1 与两条 P2。

| # | 弄坏什么 | 谁该红 |
|---|---|---|
| ① | 去掉 A20 的"双 Boss 之间"判据（P1-1 的原 bug） | `the_boss_id_names_the_actual_boss_not_the_pool_head` |
| ② | 把 `boss_beaten` 从那条判据里去掉（通关屏退化成"本幕 Boss"） | 同上 |
| ③ | `resolveScene` 把覆盖层也算进 base（P2-A 的两层合并） | `ui_test` 的 `resolveScene` 段 |
| ④ | 快照只留 `bossName`、不留 `bossId`（P2-B） | 浏览器判据（`data-*` 钩子之外，页面快照没法按 id 绑定）—— 用 `ui_test` 的静态检查钉 |

⚠️ ② 是这次最容易写错的地方：`bosses_fought == 1` 在**通关屏**上仍然是 1，所以"双 Boss 之间"
必须排除 `boss_beaten`。第一版只写 `bosses_fought == 1` 会让通关屏显示"本幕 Boss 已击败"。
"""

import io
import subprocess
import sys

RUN = 'kernel/rd-wasm/src/run.rs'
PANELS = 'web/ui_panels.js'
PAGE = 'web/index.html'


def run_cargo(test_name):
    p = subprocess.run(['cargo', 'test', '-p', 'rd-wasm', '--release', '--',
                        '--test-threads=1', test_name],
                       cwd='kernel', capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def run_ui():
    p = subprocess.run(['C:\\Program Files\\nodejs\\node.exe', 'web/ui_test.mjs'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode, p.stdout + p.stderr


def case(path, label, pairs, needle, test_name=None):
    raw = io.open(path, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(broken)
        if test_name:
            out = run_cargo(test_name)
            ok = needle in out and test_name in out
        else:
            code, out = run_ui()
            ok = code != 0 and needle in out
        print('  %-52s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'panicked' in line or 'error[' in line or 'FAIL' in line:
                    print('      ', line.strip()[:140])
                    break
    finally:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

# ① 去掉 A20 窗口判据
ok &= case(
    RUN,
    '① 去掉 A20 双 Boss 窗口判据（P1-1 原 bug）',
    [('''    if !in_fight && !boss_beaten && bosses_fought == 1 {
        return None;
    }''',
      '''    if false {
        return None;
    }''')],
    'between the two A20 bosses',
    'the_boss_id_names_the_actual_boss_not_the_pool_head',
)

# ② 那条判据里去掉 boss_beaten
ok &= case(
    RUN,
    '② 判据里去掉 boss_beaten（通关屏退化）',
    [('''    if !in_fight && !boss_beaten && bosses_fought == 1 {''',
      '''    if !in_fight && bosses_fought == 1 {''')],
    'victory screen must still name the boss',
    'the_boss_id_names_the_actual_boss_not_the_pool_head',
)

# ③ resolveScene 把覆盖层算进 base
ok &= case(
    PANELS,
    '③ resolveScene 把覆盖层也算进 base（两层合并）',
    [('''    const base = SCENES.find((entry) => !entry.overlay && entry.test(s));''',
      '''    const base = SCENES.find((entry) => entry.test(s));''')],
    'layered base must be SC-04',
)

# ④ 快照只留名字、不留 id（P2-B）
ok &= case(
    PAGE,
    '④ 快照只留 bossName、不留 bossId（P2-B）',
    [('''    bossId: readText(() => ex.rd_run_boss_id_len(), (ptr) => ex.rd_run_boss_id_into(ptr)),''',
      '''    bossId: "",''')],
    'bossId',
)

code, _ = run_ui()
print('  还原后 ui_test：%s' % ('green' if code == 0 else 'STILL RED'))
out = run_cargo('')
print('  还原后 rd-wasm：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
