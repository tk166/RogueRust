"""§308 的编译修正：`archive.rs` 的 `use` 里少了 `RunMark`；两处 `.str()` 要 `.as_str()`。"""
import io

ARCHIVE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'
HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:80])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    text = io.open(ARCHIVE, encoding='utf-8').read()
    import re
    match = re.search(r'use super::\{[^}]*\};', text)
    assert match, 'no use super block'
    block = match.group(0)
    assert 'RunMark' not in block
    new_block = block.replace('use super::{', 'use super::{RunMark, ', 1)
    io.open(ARCHIVE, 'w', encoding='utf-8', newline='\n').write(
        text.replace(block, new_block, 1))

    patch(HASH, 'writer.str("event_resume=").str(state.event_resume()).str("\\n");',
          'writer.str("event_resume=").str(state.event_resume().as_str()).str("\\n");')
    patch(HASH, 'writer.str("event_next=").str(state.event_next()).str("\\n");',
          'writer.str("event_next=").str(state.event_next().as_str()).str("\\n");')
    print('fixups applied')


main()
