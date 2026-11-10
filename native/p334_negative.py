"""§334 负控：两处各弄坏一次。

1. 把 `hash_full` 里的 **`choice` 段**整段删掉 ⇒ `a_pending_choice_moves_the_full_hash...` 红；
2. 把 `status_src` 段整段删掉 ⇒ `a_status_source_moves_the_full_hash...` 红。

⚠️ 第 2 条第一版写的是"把 `status_src=` 改名"，结果**没红** —— 改名仍然会改变指纹，
判据只能证明"这一段被写过"，证明不了"它写的是 source"。所以必须**删掉**。
"""

import io
import subprocess
import sys

PATH = 'kernel/rd-core/src/snapshot.rs'


def run():
    p = subprocess.run(
        ['cargo', 'test', '-p', 'rd-core', '--release', '--', '--test-threads=1', 'full_hash'],
        cwd='kernel', capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def mutate(label, pairs, needle):
    raw = io.open(PATH, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r' % (label, old[:60])
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(broken)
        out = run()
        ok = needle in out
        print('  %-44s %s' % (label, 'RED' if ok else 'NOT CAUGHT'))
    finally:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


def block_from(text, first_line, until_trimmed):
    lines = text.split('\n')
    start = next(i for i, line in enumerate(lines) if first_line in line)
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == until_trimmed)
    return '\n'.join(lines[start:end + 1])


ok = True
raw = io.open(PATH, encoding='utf-8').read()

# ① 删掉 choice 段
start = raw.index('    match s.pending_choice() {')
end = raw.index('\n    }\n}\n', start) + len('\n    }\n}\n')
ok &= mutate('① 删掉 choice 段', [(raw[start:end], '    let _ = s;\n}\n')], 'must see it')

# ② 删掉 status_src 段
choice_block = block_from(raw, 'w.str("status_src=")', "w.char('\\n');")
ok &= mutate('② 删掉 status_src 段', [(choice_block, '')], 'hash_full carries the source')

out = run()
print('  还原后：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
