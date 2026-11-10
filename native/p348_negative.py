"""§348 负控：四条，对应第十轮 Review 的四条实质发现。

| # | 弄坏什么 | 谁该红 |
|---|---|---|
| ① | `boss_enemy_id` 退回"取池子第一条"（P1-1 的原 bug） | `the_boss_id_names_the_actual_boss_not_the_pool_head` |
| ② | 从源码里**删掉** `rd_run_over` 导出（P1-2 的后果） | `ui_state_check.py` 必须报 `MISSING` |
| ③ | `noRun` 退回 `rd_run_seed() === i32::MIN`（P2-1） | 需要真实 wasm —— 用"seed = i32::MIN 能开局"的 ABI 判据钉住 |
| ④ | 兜底退回无条件（P2-2） | `ui_test` 的 `pending=99` 夹具 |

⚠️ ② 是这次新加的一种负控：**删掉一个真导出**，而不是塞一个假名字。前者证明"删除会让闸门红"
（那是这道闸门的主要目的），后者只证明"拼错会被抓"。
"""

import io
import subprocess
import sys

RUN = 'kernel/rd-wasm/src/run.rs'
PAGE = 'web/index.html'
PANELS = 'web/ui_panels.js'


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


def run_check():
    p = subprocess.run([sys.executable, '-X', 'utf8', 'native/ui_state_check.py'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode, p.stdout + p.stderr


def case_rust(label, pairs, test_name, needle):
    raw = io.open(RUN, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(RUN, 'w', encoding='utf-8', newline='\n').write(broken)
        out = run_cargo(test_name)
        ok = needle in out and test_name in out
        print('  %-52s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'panicked' in line or 'error[' in line:
                    print('      ', line.strip()[:140])
                    break
    finally:
        io.open(RUN, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


def case_check(label, pairs, needle):
    raw = io.open(RUN, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(RUN, 'w', encoding='utf-8', newline='\n').write(broken)
        code, out = run_check()
        ok = code != 0 and needle in out
        print('  %-52s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            print('      exit=%d' % code)
            for line in out.splitlines()[:4]:
                print('      ', line.strip()[:130])
    finally:
        io.open(RUN, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


def case_ui(label, pairs, needle):
    raw = io.open(PANELS, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(PANELS, 'w', encoding='utf-8', newline='\n').write(broken)
        code, out = run_ui()
        ok = code != 0 and needle in out
        print('  %-52s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'FAIL' in line:
                    print('      ', line.strip()[:140])
                    break
    finally:
        io.open(PANELS, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

# ① P1-1 的原 bug：取池子第一条
ok &= case_rust(
    '① boss id 退回"取池子第一条"（P1-1 原 bug）',
    [('''    let ids = content.encounter_pool(pool)?;
    if !ids.iter().any(|id| !id.is_empty() && *id == last_encounter) {
        return None;
    }
    let entry = content.lookup_in(last_encounter, rd_core::content::EK_ENCOUNTER)?;''',
      '''    let ids = content.encounter_pool(pool)?;
    let head = ids.iter().find(|id| !id.is_empty())?;
    let entry = content.lookup_in(head, rd_core::content::EK_ENCOUNTER)?;''')],
    'the_boss_id_names_the_actual_boss_not_the_pool_head',
    'assertion `left == right` failed',
)

# ② P1-2：删掉一个真导出 ⇒ 闸门必须报 MISSING
ok &= case_check(
    '② 删掉 `rd_run_over` 导出（闸门必须报 MISSING）',
    [('''pub extern "C" fn rd_run_over() -> i32 {''',
      '''pub extern "C" fn rd_run_over_renamed_for_negative_control() -> i32 {''')],
    'MISSING',
)

# ③ P2-1：把"seed 哨兵"塞回 `rd_run_exists` —— 用 `i32::MIN` 开的那一局会被判成"没有局"。
ok &= case_rust(
    '③ `rd_run_exists` 退回 seed 哨兵（P2-1 的原 bug）',
    [("""pub extern "C" fn rd_run_exists() -> i32 {
    i32::from(run_slot().as_ref().is_some())
}""",
      """pub extern "C" fn rd_run_exists() -> i32 {
    run_slot()
        .as_ref()
        .map_or(0, |s| i32::from(s.state.seed() != i32::MIN))
}""")],
    'the_boss_id_names_the_actual_boss_not_the_pool_head',
    'still EXISTS',
)

# ④ P2-2：兜底退回无条件 ⇒ pending=99 落到地图
ok &= case_ui(
    '④ 兜底退回无条件（pending=99 静默落地图）',
    [('''    { id: "SC-02", overlay: false, test: (s) => s.pending === 0 },''',
      '''    { id: "SC-02", overlay: false, test: () => true },''')],
    'pending=99 must classify as SC-??',
)

out = run_cargo('')
print('  还原后 rd-wasm：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
code, _ = run_ui()
print('  还原后 ui_test：%s' % ('green' if code == 0 else 'STILL RED'))
code, _ = run_check()
print('  还原后 ui_state_check：%s' % ('green' if code == 0 else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
