"""§293：新字段进 run hash 与存档（VERSION 7 → 8）。

新字段是**玩家可见的欠账**（"还要加几张牌"、"这一手是哪三张"），所以两处都要写：
不进指纹 ⇒ 两局只差一次加牌会哈希相同；不进存档 ⇒ 读回来"不欠了"（牌永远拿不到）。
"""
import io

HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'
ARCHIVE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:100])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── hash
    patch(HASH, '''    writer.str("boss_beaten=").u32(u32::from(state.boss_beaten())).str("\\n");''',
                '''    // §293：欠着的"加牌"次数与**这一手是哪三张**。后者也要进：同一局、同一个欠账次数，
    // 换一手候选就是换了一次选择（而"挑到哪张"决定牌组）。
    writer
        .str("pickup_add=")
        .u32(u32::from(state.pickup_add()))
        .str("/");
    for card in state.pickup_offer() {
        writer.str(card.as_str()).str(",");
    }
    writer.str("\\n");
    writer.str("boss_beaten=").u32(u32::from(state.boss_beaten())).str("\\n");''')

    # ── 存档：版本 + 写 + 读
    patch(ARCHIVE, '''/// §274：6 → 7（`pickup_change` + `pickup_picks`）。''',
                   '''/// §293：7 → 8（`pickup_add` + `pickup_offer`）。
/// §274：6 → 7（`pickup_change` + `pickup_picks`）。''')
    patch(ARCHIVE, '''const VERSION: u8 = 7;''', '''const VERSION: u8 = 8;''')
    patch(ARCHIVE, '''    writer.byte(state.pickup_picks())?;

    writer.byte(state.deck_len)?;''',
                  '''    writer.byte(state.pickup_picks())?;
    // §293：欠着几张牌要加 + 这一手是哪几张（`pickup_offer` 的长度是 3 或 0）。
    writer.byte(state.pickup_add())?;
    writer.byte(state.pickup_offer().len() as u8)?;
    for card in state.pickup_offer() {
        writer.id(*card)?;
    }

    writer.byte(state.deck_len)?;''')

    # 读侧：找 `pickup_picks` 的读取点
    s = io.open(ARCHIVE, encoding='utf-8').read()
    idx = s.index('let pickup_picks = reader.byte()?;') if 'let pickup_picks = reader.byte()?;' in s else -1
    print('restore anchor found:', idx >= 0)
    if idx < 0:
        for line in s.split('\n'):
            if 'pickup' in line and 'reader' in line:
                print('  candidate:', line.strip())
    io.open(ARCHIVE, 'w', encoding='utf-8', newline='\n').write(s)


main()
