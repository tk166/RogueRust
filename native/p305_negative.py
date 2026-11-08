"""§305 负控：视图规则的两侧各改坏一次。

① 无论有没有遗物都"按真实顺序"（≡ 遗物不存在）⇒ 浏览器判据的 `differsBefore` 红；
② 有遗物了还排序（≡ 遗物不生效）⇒ `matchesAfter` 红。

两条都落在**页面**上，因为这一轮的规则只有一句话：视图由标志选。内核那侧只说明"标志 0/1"。
"""
import io
import subprocess
import sys

WEB = 'D:/Vibe/sts-tui/web/index.html'
NODE = 'node'

CASES = [
    ('总是按真实顺序（遗物不存在）', '''  if (zone === 0 && ex.rd_env_frozen_eye() !== 1 && entries.length > 1) {''',
     '''  if (zone === 0 && false && entries.length > 1) {'''),
    ('有遗物也排序（遗物不生效）', '''  if (zone === 0 && ex.rd_env_frozen_eye() !== 1 && entries.length > 1) {''',
     '''  if (zone === 0 && entries.length > 1) {'''),
]


def run_gate():
    out = subprocess.run([NODE, 'web/browser_test.mjs'], cwd='D:/Vibe/sts-tui',
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return out.returncode == 0 and 'BROWSER_TEST PASS' in text, text


def main():
    original = io.open(WEB, encoding='utf-8').read()
    failures = 0
    try:
        for label, good, bad in CASES:
            assert original.count(good) == 1, (label, original.count(good))
            io.open(WEB, 'w', encoding='utf-8', newline='\n').write(original.replace(good, bad))
            passed, output = run_gate()
            print('%-30s -> %s' % (label, 'RED as expected' if not passed else 'STILL GREEN'))
            if passed:
                failures += 1
            else:
                for line in output.split('\n'):
                    if line.strip().startswith('- '):
                        print('    ' + line.strip()[:110])
                        break
    finally:
        io.open(WEB, 'w', encoding='utf-8', newline='\n').write(original)
    passed, _ = run_gate()
    assert passed, 'restore failed'
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
