"""§343 负控：四条，每条都必须让**指定的**判据红。

1. `remove_card` 不检查额度 ⇒ `buying_and_removing_are_paid_for_and_never_silent` 红
   （同一家店第二次删牌会成功）。
2. `enter_shop` 不清位 ⇒ 同一个测试红在"a new shop allows one more removal"。
3. 存档不还原这个字段 ⇒ `a_saved_run_round_trips_byte_identically` 红
   （`sample_full()` 显式设了它，所以"漏还原"能被整结构体相等抓到）。
4. 指纹里不写它 ⇒ `state-fields` 闸门红（这一条用 `native/check_state_fields.py` 验，
   不是 cargo test —— 那道闸门是 §308 为"加了字段忘了存/忘了算"设的）。
"""

import io
import subprocess
import sys

STATE = 'kernel/rd-run/src/state.rs'
ARCHIVE = 'kernel/rd-run/src/state/archive.rs'
HASH = 'kernel/rd-run/src/hash.rs'


def run(test_name):
    p = subprocess.run(['cargo', 'test', '-p', 'rd-run', '--release', test_name],
                       cwd='kernel', capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def case(label, path, pairs, test_name, needle):
    raw = io.open(path, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(broken)
        out = run(test_name)
        ok = needle in out and test_name in out
        print('  %-52s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'panicked' in line or 'error[' in line or 'test result' in line:
                    print('      ', line.strip()[:140])
                    break
    finally:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


def case_gate(label, path, pairs):
    """第 4 条走闸门而不是 cargo test：`check_state_fields.py` 就是为这件事存在的。"""
    raw = io.open(path, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(broken)
        p = subprocess.run([sys.executable, '-X', 'utf8', 'native/check_state_fields.py', '--check'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        out = p.stdout + p.stderr
        ok = p.returncode != 0 and 'removed_this_shop' in out
        print('  %-52s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            print('      exit=%d' % p.returncode)
            for line in out.splitlines()[:6]:
                print('      ', line.strip()[:130])
    finally:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

ok &= case(
    '① remove_card 不检查额度',
    STATE,
    [('''        if self.removed_this_shop {
            return Err(RunError::RemovalUsed);
        }''',
      '''        if false {
            return Err(RunError::RemovalUsed);
        }''')],
    'buying_and_removing_are_paid_for_and_never_silent',
    'assertion `left == right` failed',
)

ok &= case(
    '② enter_shop 不清位',
    STATE,
    [('''        self.removed_this_shop = false;''',
      '''        // 负控：不清位''')],
    'buying_and_removing_are_paid_for_and_never_silent',
    'a new shop allows one more removal',
)

ok &= case(
    '③ 存档不还原 removed_this_shop',
    ARCHIVE,
    [('''    restored.removed_this_shop = removed_this_shop != 0;''',
      '''    let _ = removed_this_shop;''')],
    'a_saved_run_round_trips_byte_identically',
    'the archive lost a field',
)

ok &= case_gate(
    '④ 指纹里不写 removed_this_shop',
    HASH,
    [('''        .str("removal_used=")
        .u32(u32::from(state.removed_this_shop))''',
      '''        .str("removal_used=")
        .u32(0)''')],
)

out = run('')
print('  还原后 rd-run：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
