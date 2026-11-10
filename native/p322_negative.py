"""§322 负控：三处各弄坏一次，看判据是否**在预期位置**红，然后一定写回。"""

import io
import subprocess
import sys

STATE = 'kernel/rd-run/src/state.rs'
NODE = 'C:/Program Files/nodejs/node.exe'


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

# ── 1. `card:` / `curse:` 的张数又被丢掉（回到一行 `push_card`）────────────────────
ok &= mutated(
    STATE,
    """                for _ in 0..count {
                    self.push_card(*row)?;
                }""",
    """                self.push_card(*row)?;""",
    'card: 张数被丢掉',
    lambda: report('card: 张数被丢掉', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-run', '--release',
                        'a_card_payload_is_granted'], cwd='kernel')))

# ── 2. `remove_all` 变成"只删第一张" ────────────────────────────────────────────
ok &= mutated(
    STATE,
    """                let mut index = self.deck_len as usize;
                while index > 0 {
                    index -= 1;""",
    """                let mut index = 1usize;
                while index > 0 {
                    index -= 1;""",
    'remove_all 只删一张',
    lambda: report('remove_all 只删一张', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-run', '--release',
                        'remove_all_deletes'], cwd='kernel')))

# ── 3. `card_count` 恒为 1（内容里的 5 张变 1 张，wasm 端到端必须红）────────────
ok &= mutated(
    STATE,
    """        1..=5 => u8::try_from(amount).ok(),""",
    """        1..=5 => Some(1),""",
    'card_count 恒为 1',
    lambda: report('card_count 恒为 1', 'test result: FAILED',
                   run(['cargo', 'test', '-p', 'rd-wasm', '--release',
                        'vampires_swaps'], cwd='kernel')))

print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
