"""§336 负控：两处各弄坏一次。

1. **录制侧**：把提交点那段"记下战斗指纹"删掉 ⇒ 判据红在"fight_begin must carry the
   combat hash_full"（第 5 列空）。
2. **回放侧**：把 `K_FIGHT_BEGIN` 的比对删掉 ⇒ 判据红在"a changed combat hash must diverge"。

两侧都要独立可证：只测一侧的话，"记了但从不比"或"比了但记的是空的"都会绿。
"""

import io
import subprocess
import sys

PATH = 'kernel/rd-wasm/src/run.rs'


def run():
    p = subprocess.run(
        ['cargo', 'test', '-p', 'rd-wasm', '--release', '--', '--test-threads=1',
         'the_replay_verifies_the_combat'],
        cwd='kernel', capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def mutate(label, pairs, needle):
    raw = io.open(PATH, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r' % (label, old[:70])
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(broken)
        out = run()
        ok = needle in out
        print('  %-40s %s' % (label, 'RED' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'error[' in line or 'panicked' in line:
                    print('      ', line.strip()[:120])
                    break
    finally:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

# ① 录制侧：不再写第 5 列
ok &= mutate(
    '① 录制侧不写战斗指纹',
    [('''    if let Some(prefix) = combat_full_hash_prefix() {''',
      '''    if let Some(prefix) = None::<u64> {''')],
    # ① 会先在 `script_fill` 上红（`hash_failed` ⇒ 脚本导不出去）—— 那也是正确位置：
    # "记不下战斗指纹"就不该有一份能当证据用的脚本。两处任一命中都算抓到。
    'script_fill said',
)

# ② 回放侧：不比对
ok &= mutate(
    '② 回放侧不比对',
    [('''                if !payload.is_empty() {''',
      '''                if false {''')],
    'a changed combat hash must diverge',
)

out = run()
print('  还原后：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
