"""§326 负控：三处各弄坏一次，看判据是否**在预期位置**红，然后一定写回。"""

import io
import subprocess
import sys

RUNSTATE = 'kernel/rd-run/src/state.rs'
EXEC = 'kernel/rd-core/src/exec.rs'
RUN = 'kernel/rd-wasm/src/run.rs'


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

# ① parasite 的惩罚不被触发（把常量改成别的 id）
ok &= mutated(
    RUNSTATE,
    'pub const PARASITE: &str = "parasite";',
    'pub const PARASITE: &str = "regret";',
    'parasite 惩罚不触发',
    lambda: report('parasite 惩罚不触发', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-run', '--release', 'parasite'],
                       cwd='kernel')))

# ② 战斗内 gate 失效
ok &= mutated(
    EXEC,
    '    if ctx.state.heal_blocked {',
    '    if false {',
    '战斗内治疗没被挡',
    lambda: report('战斗内治疗没被挡', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-core', '--release', 'a_blocked_fight'],
                       cwd='kernel')))

# ③ wasm 没把位接进战斗
ok &= mutated(
    RUN,
    '                crate::set_combat_heal_blocked(session.state.blocks_healing());',
    '                crate::set_combat_heal_blocked(false);',
    'wasm 没接这位',
    lambda: report('wasm 没接这位', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-wasm', '--release', '--',
                        '--test-threads=1', 'mark_of_the_bloom_reaches'], cwd='kernel')))

print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
