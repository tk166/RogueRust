"""§346 负控：五条。

1. `rd_run_has_relic` 恒返回 1 ⇒ "没有那件遗物"那一格红。
2. `rd_run_start_offer_count` 恒返回 0 ⇒ "至少两个祝福"红。
3. `rd_run_event_id_*` 没有事件时返回垃圾（不是空串）⇒ "no event open" 红。
4. `rd_env_active_slot` 用回 `ensure_session()`（会懒建会话）⇒ `-3` 那一格红。
5. 页面把 `data-encounter-id` 挂回 `renderTopBar`（不在战斗重绘路径上）⇒ 浏览器判据红。
"""

import io
import subprocess
import sys

RUN = 'kernel/rd-wasm/src/run.rs'
LIB = 'kernel/rd-wasm/src/lib.rs'
PAGE = 'web/index.html'


def run_cargo(test_name):
    p = subprocess.run(['cargo', 'test', '-p', 'rd-wasm', '--release', '--',
                        '--test-threads=1', test_name],
                       cwd='kernel', capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def run_browser():
    p = subprocess.run(['C:\\Program Files\\nodejs\\node.exe', 'web/browser_test.mjs'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode, p.stdout + p.stderr


def case(label, path, pairs, needle, test_name=None):
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
            code, out = run_browser()
            ok = code != 0 and needle in out
        print('  %-50s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'panicked' in line or 'error[' in line or 'FAIL' in line:
                    print('      ', line.strip()[:140])
                    break
    finally:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

ok &= case(
    '① has_relic 恒返回 1',
    RUN,
    [('''    i32::from(session.state.holds_relic(id))''', '''    let _ = id;
    let _ = session;
    1i32''')],
    'we do not hold singing_bowl',
    'the_run_facts_the_ui_asks_about',
)

ok &= case(
    '② offer_count 恒返回 0',
    RUN,
    [('''        .map_or(0, |s| s.state.start_offers().map_or(0, |offers| offers.len() as i32))''',
      '''        .map_or(0, |_s| 0)''')],
    'must offer at least two',
    'the_run_facts_the_ui_asks_about',
)

ok &= case(
    '③ event_id 没事件时返回垃圾',
    RUN,
    [('''    session.state.event().len() as i32''',
      '''    if session.state.event().is_empty() { return 3; }
    session.state.event().len() as i32''')],
    'no event open',
    'the_run_facts_the_ui_asks_about',
)

ok &= case(
    '④ active_slot 用回 ensure_session()（懒建会话）',
    LIB,
    [('''    let Some(session) = slot().as_ref() else {
        return -3;
    };''',
      '''    let Ok(session) = ensure_session() else {
        return -3;
    };''')],
    'no combat session',
    'the_run_facts_the_ui_asks_about',
)

ok &= case(
    '⑤ 遭遇 id 挂回 renderTopBar（不在战斗重绘路径上）',
    PAGE,
    [('''  enemiesEl.dataset.encounterId =
    readText(() => ex.rd_run_encounter_id_len(), (ptr) => ex.rd_run_encounter_id_into(ptr));''',
      '''  enemiesEl.dataset.encounterId = "";''')],
    'must expose data-encounter-id',
)

out = run_cargo('')
print('  还原后 rd-wasm：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
code, _ = run_browser()
print('  还原后浏览器：%s' % ('green' if code == 0 else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
