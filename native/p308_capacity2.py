"""§308（五）：存档容量。

60 个牌位各带一条成长（最坏情况）撞上了 `MAX_PAYLOAD = 4096`。**这是本轮唯一一处
"容量常量放大之后行为变更"的地方**，按 §162 的裁决：常量是语义，改它要写清楚账。

做法：`MAX_PAYLOAD` 4096 → 8192（`MAX_ARCHIVE` 16384 → 24576 给 base64 留位），
并把实测数字写进注释 —— 然后再跑一遍那条最坏情况判据确认它变绿。
"""
import io
import subprocess
import sys

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'
CARGO = 'C:/Users/TK11/.cargo/bin/cargo.exe'
MANIFEST = 'D:/Vibe/sts-tui/kernel/Cargo.toml'
PROBE = '        assert!(len <= MAX_ARCHIVE, "the archive must fit its published capacity");'


def main():
    text = io.open(PATH, encoding='utf-8').read()
    old_payload = '/// payload 缓冲。实测一局约 300–900 B；4 KB 是"内容翻倍也不会撞上"的余量。\npub const MAX_PAYLOAD: usize = 4096;'
    new_payload = ('/// payload 缓冲。实测一局约 300–900 B；§308 之后**最坏情况**（60 张牌各带一条 mark）\n'
                   '/// 是 MEASURED_WORST B —— 8 KB 是它上面一层。这个数不是拍的：\n'
                   '/// `a_deck_where_every_copy_carries_a_mark_still_fits` 就是拿它压出来的。\n'
                   'pub const MAX_PAYLOAD: usize = 8192;')
    assert text.count(old_payload) == 1
    text = text.replace(old_payload, new_payload)

    old_archive = 'pub const MAX_ARCHIVE: usize = 16384;'
    new_archive = ('/// §308：16 KB → 24 KB。payload 抬到 8 KB 之后，base64（4/3）与 RLE（最坏 2×）\n'
                   '/// 一起算下来要 21.8 KB —— 24 KB 是那个上界的余量，而不是"看着宽裕"。\n'
                   'pub const MAX_ARCHIVE: usize = 24576;')
    assert text.count(old_archive) == 1
    text = text.replace(old_archive, new_archive)

    # 临时探针：把实测长度打出来（跑一次就删）。
    assert text.count(PROBE) == 1
    text = text.replace(PROBE, PROBE + '\n        std::println!("WORST_PAYLOAD_PROBE text_bytes={}", len);')
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text)

    out = subprocess.run([CARGO, 'test', '-p', 'rd-run', '--manifest-path', MANIFEST,
                          '--release', 'every_copy_carries_a_mark', '--', '--nocapture'],
                         capture_output=True, text=True, errors='replace')
    blob = (out.stdout or '') + (out.stderr or '')
    for line in blob.splitlines():
        if 'WORST_PAYLOAD_PROBE' in line or 'test result' in line:
            print(line.strip())
    if 'test result: ok' not in blob:
        print(blob[-1200:])
        sys.exit(1)


main()
