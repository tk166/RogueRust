"""§321 负控：三处各弄坏一次，看判据是否**在预期位置**红，然后一定写回。"""

import io
import subprocess
import sys

STATE = 'kernel/rd-run/src/state.rs'
EXPR = 'kernel/rd-core/src/run_expr.rs'


def run(argv, cwd=None):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace')
    return p.stdout + p.stderr


def report(label, needle, output):
    hit = needle in output
    print('  %-40s %s' % (label, 'RED at the expected place' if hit
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

# ── 1. "不能治疗"失效 ────────────────────────────────────────────────────────────
ok &= mutated(
    STATE,
    '        self.holds_relic_effect(RelicEffect::NoHeal)',
    '        false',
    '不能治疗失效',
    lambda: report('不能治疗失效', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-run', '--release',
                        'mark_of_the_bloom_blocks'], cwd='kernel')))

# ── 2. `upgrade_all` 变成空操作 ──────────────────────────────────────────────────
ok &= mutated(
    STATE,
    """            EventEffect::UpgradeAll => {
                for index in 0..self.deck_len as usize {
                    self.upgrade_at(index, pool)?;
                }
            }""",
    """            EventEffect::UpgradeAll => {}""",
    'upgrade_all 变空操作',
    lambda: report('upgrade_all 变空操作', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-run', '--release',
                        'upgrade_all_upgrades'], cwd='kernel')))

# ── 3. `floor` 恒真 ─────────────────────────────────────────────────────────────
ok &= mutated(
    EXPR,
    '            "floor" => facts.floor,',
    '            "floor" => 6,',
    'floor 恒为 6',
    lambda: report('floor 恒为 6', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-core', '--release',
                        'the_floor_requirement_follows'], cwd='kernel')))

print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
