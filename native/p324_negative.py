"""§324 负控：两处各弄坏一次，看判据是否**在预期位置**红，然后一定写回。"""

import io
import subprocess
import sys

STATE = 'kernel/rd-run/src/state.rs'


def run(argv, cwd=None):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return p.stdout + p.stderr


def report(label, needle, output):
    hit = needle in output
    print('  %-42s %s' % (label, 'RED at the expected place' if hit
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

# 1. 欠账只记 1 次（"选 2 张"退化成"选 1 张"）
ok &= mutated(
    STATE,
    '                self.pickup_picks = count;',
    '                self.pickup_picks = 1;',
    '欠账只记一次',
    lambda: report('欠账只记一次', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-run', '--release',
                        'transform_choose_owes_two'], cwd='kernel')))

# 2. 覆盖别人的欠账（去掉那条守卫）
ok &= mutated(
    STATE,
    """                if self.pickup_change.is_some() {
                    return Err(RunError::WrongPhase);
                }""",
    '                if false {\n                    return Err(RunError::WrongPhase);\n                }',
    '覆盖别人的欠账',
    lambda: report('覆盖别人的欠账', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-run', '--release',
                        'transform_choose_refuses'], cwd='kernel')))

print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
