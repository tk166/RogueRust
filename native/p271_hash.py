"""§271 第三批：`tea_set_pending` 进指纹 + 存档 v5。"""
import io

HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'
ARCH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'

# ⚠️ raw string：`\n` 必须是**两个字符**（Rust 源码里的转义），不能变成真的换行。
# 上一版用普通三引号 + heredoc，`\\n` 被吃掉 ⇒ 锚点静默匹配不上（FACTS §161.5）。
HASH_OLD = r'''    writer
        .str("maw_bank=")
        .u32(u32::from(state.maw_bank_broken()))
        .str("\n");'''

HASH_NEW = r'''    writer
        .str("maw_bank=")
        .u32(u32::from(state.maw_bank_broken()))
        .str("\n");
    // §271：`ancient_tea_set` 欠着的那一场（进篝火之后、下一场战斗之前）。
    writer
        .str("tea_set=")
        .u32(u32::from(state.tea_set_pending()))
        .str("\n");'''


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def main():
    h = io.open(HASH, encoding='utf-8').read()
    h = patch(h, HASH_OLD, HASH_NEW, 'hash field')
    io.open(HASH, 'w', encoding='utf-8', newline='\n').write(h)

    a = io.open(ARCH, encoding='utf-8').read()
    a = patch(a, '/// §270：3 → 4（`omamori_charges` + `maw_bank_broken`）。',
              '/// §271：4 → 5（`tea_set_pending`）。\n'
              '/// §270：3 → 4（`omamori_charges` + `maw_bank_broken`）。', 'version doc')
    a = patch(a, 'const VERSION: u8 = 4;', 'const VERSION: u8 = 5;', 'version')
    a = patch(a, '''    let omamori_charges = reader.byte()?;
    let maw_bank_broken = reader.byte()?;''',
              '''    let omamori_charges = reader.byte()?;
    let maw_bank_broken = reader.byte()?;
    // §271
    let tea_set_pending = reader.byte()?;''', 'read')
    a = patch(a, '''    writer.byte(state.omamori_charges)?;
    writer.byte(u8::from(state.maw_bank_broken))?;''',
              '''    writer.byte(state.omamori_charges)?;
    writer.byte(u8::from(state.maw_bank_broken))?;
    // §271
    writer.byte(u8::from(state.tea_set_pending))?;''', 'write')
    a = patch(a, '    restored.maw_bank_broken = maw_bank_broken != 0;',
              '    restored.maw_bank_broken = maw_bank_broken != 0;\n'
              '    restored.tea_set_pending = tea_set_pending != 0;', 'restore')
    io.open(ARCH, 'w', encoding='utf-8', newline='\n').write(a)
    print('hash + archive v5')


main()
