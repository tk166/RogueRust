"""§270 第四批：测试调用点 + 助手 + 两个新字段进 hash/archive。"""
import io
import re

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'
ARCH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def main():
    # ---- ① state.rs 测试助手 + 调用点
    src = io.open(STATE, encoding='utf-8').read()

    src, n1 = re.subn(r'\brun\.take_card\((\d+)\)', r'take_card_at(&mut run, \1)', src)
    src, n2 = re.subn(r'\brun\.buy_card\((\d+)\)', r'buy_card_at(&mut run, \1)', src)
    src, n3 = re.subn(r'\bshop\.buy_card\((\d+)\)', r'buy_card_at(&mut shop, \1)', src)
    src, n4 = re.subn(r'\bagain\.buy_card\((\d+)\)', r'buy_card_at(&mut again, \1)', src)
    print('call sites: take %d buy %d shop %d again %d' % (n1, n2, n3, n4))

    HELPERS = '''mod tests {
    use super::*;

    /// §270：这次"拿牌"的**那一张**。`take_card` / `buy_card` 现在要把牌本身交进去
    /// （三个蛋与两条诅咒规则要看类型），所以测试里从 run 自己存的那一格造一张裸卡 ——
    /// 这正是运行层要的"两个来源对得上"（id 一样、其余字段运行层不看）。
    fn take_card_at(run: &mut RunState, slot: usize) -> Result<(), RunError> {
        let id = run.reward().cards()[slot];
        run.take_card(slot, PoolCard::plain(id.as_str()))
    }

    /// 同上，货架那一格。
    fn buy_card_at(run: &mut RunState, slot: usize) -> Result<(), RunError> {
        let id = run.shop().cards()[slot].id;
        run.buy_card(slot, PoolCard::plain(id.as_str()))
    }
'''
    src = patch(src, 'mod tests {\n    use super::*;\n', HELPERS, 'test helpers')

    src = patch(src, '''            let pool = [PoolCard {
                id: "strike",
                rarity: Rarity::Common,
            }];''',
                '''            let pool = [PoolCard {
                id: "strike",
                rarity: Rarity::Common,
                kind: CardKind::Other,
                upgraded: None,
            }];''', 'pool literal')

    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(src)

    # ---- ② hash.rs：两个新字段进指纹
    h = io.open(HASH, encoding='utf-8').read()
    h = patch(h, '''    writer
        .str("rarity_offset=")
        .i32(state.rarity_offset())
        .str("\\n");''',
              '''    writer
        .str("rarity_offset=")
        .i32(state.rarity_offset())
        .str("\\n");
    // §270：两件遗物各自的**计数器**。不进指纹的话，"`omamori` 还剩 1 次"与"还剩 2 次"、
    // "`maw_bank` 已经失效"与"还有效"都会哈希相同 —— 而那正是两条规则的**全部**区别。
    writer
        .str("omamori=")
        .u32(u32::from(state.omamori_charges()))
        .str("\\n");
    writer
        .str("maw_bank=")
        .u32(u32::from(state.maw_bank_broken()))
        .str("\\n");''', 'hash fields')
    io.open(HASH, 'w', encoding='utf-8', newline='\n').write(h)
    print('hash.rs: two fields')


main()
