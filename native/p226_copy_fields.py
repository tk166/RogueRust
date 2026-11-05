"""§226 收尾：把所有 `PendingChoice { ... }` 字面量补齐 `copies` / `candidates`。

上一版用整块字符串匹配，被"缩进不同的同类字面量"（闭包里的是 12 空格 + `})`）挡住了 ——
这正是"改源码的小脚本会留残骸"的反面做法：按**字段行**匹配，逐个补齐，并且幂等（已经有
`copies:` 的跳过）。
"""
import io
import re

TARGETS = [
    ('kernel/rd-core/src/state.rs', 'copies: 0,', 'candidates: Bounded::new(),'),
    ('kernel/rd-wasm/src/run.rs', 'copies: 0,', 'candidates: rd_core::state::Bounded::new(),'),
]

for path, copies_line, candidates_line in TARGETS:
    src = io.open(path, encoding='utf-8').read()
    out = []
    added = 0
    for line in src.split('\n'):
        out.append(line)
        stripped = line.strip()
        if not stripped.startswith('offered:'):
            continue
        indent = line[: len(line) - len(line.lstrip())]
        out.append(indent + copies_line)
        out.append(indent + candidates_line)
        added += 1
    src = '\n'.join(out)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(src)
    print(path, 'added', added)
