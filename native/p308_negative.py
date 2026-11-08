"""§308 负控：把某一条 `writer...` 删掉，`round_trips` 必须**红**。

只改数字不算验证（FACT §4.23）。这里做两次真正的反证：
  1. 去掉 `writer.byte(state.chest_extra)?` —— 一个标量；
  2. 去掉 marks 的写循环 —— 一个结构性容器。
两次都必须让 `a_saved_run_round_trips_byte_identically` 失败；跑完立刻还原。
"""
import io
import subprocess
import sys

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'
CARGO = 'C:/Users/TK11/.cargo/bin/cargo.exe'
MANIFEST = 'D:/Vibe/sts-tui/kernel/Cargo.toml'

CASES = [
    ('chest_extra 的写入', '    writer.byte(state.chest_extra)?;\n'),
    ('marks 的写循环', '''    for mark in state.marks.iter().take(state.deck_len as usize) {
        writer.id(mark.key)?;
        writer.int(mark.value)?;
    }
'''),
]


def main():
    original = io.open(PATH, encoding='utf-8').read()
    failures = 0
    try:
        for label, snippet in CASES:
            assert original.count(snippet) == 1, label
            io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
                original.replace(snippet, '', 1))
            out = subprocess.run(
                [CARGO, 'test', '-p', 'rd-run', '--manifest-path', MANIFEST, '--release',
                 'round_trips'], capture_output=True, text=True, errors='replace')
            text = (out.stdout or '') + (out.stderr or '')
            red = 'test result: FAILED' in text or 'panicked' in text
            print('%-22s -> %s' % (label, 'RED (good)' if red else 'STILL GREEN (bad!)'))
            if not red:
                failures += 1
                print(text[-1500:])
    finally:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(original)
    print('负控完成：%d/2 条按预期变红' % (2 - failures))
    sys.exit(1 if failures else 0)


main()
