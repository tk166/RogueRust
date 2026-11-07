"""§270：两个新字段的存档（VERSION 3→4）+ 访问器。"""
import io

ARCH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'
STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def main():
    a = io.open(ARCH, encoding='utf-8').read()

    a = patch(a, 'const VERSION: u8 = 3;',
              '''/// §270：3 → 4（`omamori_charges` + `maw_bank_broken`）。
///
/// 为什么**必须**抬版本而不是"在末尾多写两个字节就行"：旧存档读到末尾会缺字段，
/// 而"缺字段"与"字段是 0"在字节上无法区分 —— 那正是版本号要回答的问题。
const VERSION: u8 = 4;''', 'version')

    a = patch(a, '''    let flags = reader.byte()?;
    let pending = pending_from_u8(reader.byte()?)?;''',
              '''    let flags = reader.byte()?;
    let pending = pending_from_u8(reader.byte()?)?;
    // §270
    let omamori_charges = reader.byte()?;
    let maw_bank_broken = reader.byte()?;''', 'read')

    a = patch(a, '''        | (u8::from(state.ruby_key) << 2);
    writer.byte(flags)?;
    writer.byte(pending_to_u8(state.pending))?;''',
              '''        | (u8::from(state.ruby_key) << 2);
    writer.byte(flags)?;
    writer.byte(pending_to_u8(state.pending))?;
    // §270：两件遗物的计数器。`omamori` 是 0..=2 的计数、`maw_bank` 是布尔 —— 都单独一个字节，
    // 因为"读到 3 次"必须是**存档坏了**（见下面 restore 的那条判据）。
    writer.byte(state.omamori_charges)?;
    writer.byte(u8::from(state.maw_bank_broken))?;''', 'write')

    a = patch(a, '''    restored.ruby_key = flags & 0b100 != 0;''',
              '''    restored.ruby_key = flags & 0b100 != 0;
    // §270：容量是语义 —— `omamori` 只有 2 次，读到 3 是**存档坏了**，不是"夹到 2"。
    if omamori_charges > crate::state::OMAMORI_CHARGES {
        return Err(ArchiveError::BadField("omamori_charges"));
    }
    restored.omamori_charges = omamori_charges;
    restored.maw_bank_broken = maw_bank_broken != 0;''', 'restore')

    io.open(ARCH, 'w', encoding='utf-8', newline='\n').write(a)

    # ---- 访问器 + 常量
    s = io.open(STATE, encoding='utf-8').read()
    s = patch(s, '/// §270：`smiling_mask` 之后删牌服务的**固定**价格',
              '''/// §270：`omamori` 能给几次"挡诅咒"（wiki："Negate the next 2 Curses"）。
pub const OMAMORI_CHARGES: u8 = 2;

/// §270：`smiling_mask` 之后删牌服务的**固定**价格''', 'omamori const')

    s = patch(s, '''    /// §270：身上有没有**这一件**遗物（按 id）。''',
              '''    /// §270：`omamori` 还剩几次挡诅咒（`0..=OMAMORI_CHARGES`）。给页面用。
    #[must_use]
    pub const fn omamori_charges(&self) -> u8 {
        self.omamori_charges
    }

    /// §270：`maw_bank` 是否已经失效（在商店花过钱）。
    #[must_use]
    pub const fn maw_bank_broken(&self) -> bool {
        self.maw_bank_broken
    }

    /// §270：身上有没有**这一件**遗物（按 id）。''', 'accessors')

    # `Omamori(2)` 用常量
    s = patch(s, '            "omamori" => Some(RelicEffect::Omamori(2)),',
              '            "omamori" => Some(RelicEffect::Omamori(OMAMORI_CHARGES)),', 'omamori row')

    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('archive v4 + accessors')


main()
