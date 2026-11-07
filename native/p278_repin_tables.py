"""§278：格式加了段（`nsec` 20 → 21、`EV` 行宽 20 → 8），roguedeck 那两个"逐字抄 manifest"
的对照表必须重抄。**数字一律从 manifest 读出来**，不手写 —— 手写就是第二份常量。
"""
import io
import json

IMG = 'D:/Vibe/sts-tui/tools/contentc/out/manifest.json'
RUST = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'


def table(rows, indent):
    out = []
    for index, name, offset, size, count in rows:
        out.append('%s(%d, "%s", %d, %d, %d),' % (indent, index, name, offset, size, count))
    return '\n'.join(out)


def main():
    manifest = json.load(io.open(IMG, encoding='utf-8'))
    def fifteen(variant):
        """前 15 个有名字的段（`EV`/`POT`/`EVND` 不在那张对照表里）。"""
        return [(row["id"], row["name"], row["offset"], row["bytes"], row["count"])
                for row in manifest['variants'][variant]['sections']
                if row["id"] < 15]

    core = fifteen('core')
    full = fifteen('full')
    assert len(core) == 15 and len(full) == 15, (len(core), len(full))
    sizes = {name: manifest['totals'][name] for name in manifest['totals']}

    s = io.open(RUST, encoding='utf-8').read()

    old_core = '''    const CORE_SECTIONS: [(usize, &str, u32, u32, u32); 15] = ['''
    i = s.index(old_core)
    j = s.index('    ];', i)
    s = s[:i] + old_core + '\n' + table(core, '        ') + '\n' + s[j:]

    old_full = '''    const FULL_SECTIONS: [(usize, &str, u32, u32, u32); 15] = ['''
    i = s.index(old_full)
    j = s.index('    ];', i)
    s = s[:i] + old_full + '\n' + table(full, '        ') + '\n' + s[j:]

    # 总字节数 + nsec + 段号上界
    s = s.replace('assert_eq!(blob.len(), 85_616);',
                  'assert_eq!(blob.len(), %s);' % format(sizes['content.core.rdcf'], '_'))
    s = s.replace('assert_eq!(blob.len(), 158_296);',
                  'assert_eq!(blob.len(), %s);' % format(sizes['content.rdcf'], '_'))
    s = s.replace('''            assert_eq!(content.section_count(), 20, "头里 nsec = 20（15 有名字 + 5 保留）");''',
                  '''            // §278: 21 = 17 个有名字的段 + 4 个保留段（18..20）。
            assert_eq!(content.section_count(), 21, "头里 nsec = 21");''')
    s = s.replace('''            // 段外越界：nsec 是 20，段号 20 起就没有了。
            assert!(content.section(20).is_none());''',
                  '''            // 段外越界：nsec 是 21，段号 21 起就没有了。
            assert!(content.section(21).is_none());''')
    io.open(RUST, 'w', encoding='utf-8', newline='\n').write(s)
    print('repinned: core %d B, full %d B, 15-section tables regenerated from the manifest'
          % (sizes['content.core.rdcf'], sizes['content.rdcf']))


main()
