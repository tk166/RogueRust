"""§249.3 探针 runner：把一条临时测试塞进 `host.rs`，跑完自动摘掉。

用途：确认"某张牌的节目在运行时到底报什么"。测试体由 `PYTEST` 环境变量给 —— 这里只做
**插入 / 运行 / 还原** 三件事，绝不改别的行。
"""
import io
import os
import subprocess
import sys

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
BEGIN = '    // ---- §249 临时探针（脚本插入，自动摘掉）----\n'
END = '    // ---- §249 临时探针结束 ----\n'


def restore():
    src = io.open(PATH, encoding='utf-8').read()
    if BEGIN in src:
        start = src.index(BEGIN)
        stop = src.index(END) + len(END)
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src[:start] + src[stop:])


def main():
    restore()
    body = io.open(sys.argv[1], encoding='utf-8').read()
    src = io.open(PATH, encoding='utf-8').read()
    anchor = '    /// §248：`Enlightenment` —— **降到至多 1**'
    assert src.count(anchor) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        src.replace(anchor, BEGIN + body + END + '\n' + anchor))
    try:
        run = subprocess.run(
            ['cargo', 'test', '-p', 'rd-core', '--release',
             '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine', '--',
             '--test-threads=1', sys.argv[2]],
            cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True)
        out = run.stdout + run.stderr
    finally:
        restore()
    keep = [line for line in out.splitlines()
            if any(mark in line for mark in
                   ('error[', 'error:', 'panicked', 'assertion', 'left:', 'right:',
                    'test result', 'FAILED', 'warning: unused'))]
    print('\n'.join(keep[:40]))


main()
