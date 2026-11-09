"""§320：给每个 `PoolCard` 字面量补 `colorless` 字段。

用手写正则改 116 处必然会漏（多行 / 单行 / 结构更新三种形状混在一起）。这里按**花括号配对**
找每个字面量的范围：带 `..`（结构更新）的跳过，其余在最后一个字段后面插一行。
"""

import io
import re

FILES = ['kernel/rd-run/src/state.rs']
FIELD_RE = re.compile(r'^(\s*)colorless: (true|false),\s*$', re.MULTILINE)


def patch(path):
    t = io.open(path, encoding='utf-8').read()
    out = []
    at = 0
    added = 0
    skipped = 0
    for match in re.finditer(r'PoolCard \{', t):
        start = match.end() - 1          # 指向 `{`
        if start < at:
            continue
        # 花括号配对（字面量里没有字符串带括号的情况：字段都是 id/枚举/None/Some("…")）。
        depth = 0
        index = start
        end = None
        while index < len(t):
            ch = t[index]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = index
                    break
            index += 1
        assert end is not None, 'unbalanced literal at %d' % start
        block = t[start:end]
        if '..' in block:
            skipped += 1
            continue
        if FIELD_RE.search(block):
            continue
        # 最后一个字段那一行的缩进 + 它的行首位置。
        body = block[1:]
        last_break = body.rstrip().rfind('\n')
        if last_break == -1:
            # 单行：`{ id: …, rarity: …, kind: …, upgraded: None }`
            inner = body.rstrip()
            indent = ' ' * (start - t.rfind('\n', 0, start) - 1)
            replacement = '\n' + indent + '    colorless: false,\n' + indent
            out.append((start + 1, start + 1 + len(inner), ' ' + inner + replacement.rstrip()))
        else:
            tail = body[last_break:]
            indent = ' ' * (len(tail) - len(tail.lstrip()))
            insert_at = start + 1 + last_break + 1
            out.append((insert_at, insert_at, indent + 'colorless: false,\n'))
        added += 1
    # 从后往前替换，位置不会漂。
    for begin, finish, text in sorted(out, reverse=True):
        t = t[:begin] + text + t[finish:]
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('%s: %d literal(s) got `colorless: false`, %d skipped (struct update)'
          % (path, added, skipped))


patch(FILES[0])
