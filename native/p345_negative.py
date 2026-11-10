"""§345 负控：四条。

1. `prettifyId` 不处理 `+` 后缀 ⇒ `defend+` 变 `Defend`（升级标记丢了）。
2. `prettifyId` 不去命名空间 ⇒ `standard.constricted` 变 `Standard Constricted`。
3. `displayName` 的优先级反过来（美化 id 压过替换表）⇒ 替换表不再能覆盖内核名 ——
   **这条是"规避版权"能不能做到的分界**。
4. `rd_run_boss_id_*` 永远返回第一幕的池 ⇒ 三幕显示同一个 Boss（写死的等价物）。
"""

import io
import subprocess
import sys

RENDER = 'web/ui_render.js'
RUN = 'kernel/rd-wasm/src/run.rs'


def run_node():
    p = subprocess.run(['C:\\Program Files\\nodejs\\node.exe', 'web/ui_test.mjs'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode, p.stdout + p.stderr


def run_cargo(test_name):
    p = subprocess.run(['cargo', 'test', '-p', 'rd-wasm', '--release', '--',
                        '--test-threads=1', test_name],
                       cwd='kernel', capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def case_ui(label, pairs, needle):
    raw = io.open(RENDER, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(RENDER, 'w', encoding='utf-8', newline='\n').write(broken)
        code, out = run_node()
        ok = code != 0 and needle in out
        print('  %-52s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'FAIL' in line:
                    print('      ', line.strip()[:140])
                    break
    finally:
        io.open(RENDER, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


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


ok = True

ok &= case_ui(
    '① prettifyId 丢掉 `+` 后缀',
    [('''    let plus = "";
    while (text.endsWith("+")) { plus += "+"; text = text.slice(0, -1); }''',
      '''    let plus = "";
    while (text.endsWith("+")) { text = text.slice(0, -1); }''')],
    'prettifyId("defend+")',
)

ok &= case_ui(
    '② prettifyId 不去命名空间',
    [('''    const dot = text.lastIndexOf(".");
    if (dot >= 0) text = text.slice(dot + 1);''',
      '''    const dot = -1;
    if (dot >= 0) text = text.slice(dot + 1);''')],
    'prettifyId("standard.constricted")',
)

ok &= case_ui(
    '③ displayName 优先级反过来（替换表压不过美化）',
    [('''    if (id && Object.prototype.hasOwnProperty.call(NAMES, id)) return NAMES[id];
    if (kernelName) return kernelName;
    return prettifyId(id);''',
      '''    if (kernelName) return kernelName;
    return prettifyId(id);''')],
    'replacement table must override',
)

ok &= case_rust(
    '④ Boss id 永远返回第一幕的池',
    [('''    let pool = match act {
        1 => "Boss",
        2 => "Boss2",
        3 => "Boss3",
        _ => return None,
    };''',
      '''    let pool = match act {
        1 => "Boss",
        2 => "Boss",
        3 => "Boss",
        _ => return None,
    };''')],
    'the_boss_id_follows_the_act',
    'act 2 must not show act 1',
)

out = run_cargo('')
print('  还原后 rd-wasm：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
code, _ = run_node()
print('  还原后 ui_test：%s' % ('green' if code == 0 else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
