"""§259 第 1 层：`RunState` 加两个篝火字段（`girya_lifts` / `ruby_key`），并进存档与哈希。

⚠️ 这两个字段**进存档**，所以存档 `VERSION: 2 → 3`。计划里（`port-plan.md` §234.2）写明了
"先做这一层，因为它决定了后面所有层能不能落盘"。

`ruby_key` 用 `bool` 而不是 `u8`：它只有"有没有"两种状态，而存档里已经有一个 `flags` 字节
（`map_generation_failed` / `boss_beaten`），第 3 位给它。⚠️ 但 `flags` 是 `u8` 且已有 2 位 ——
第 3 位够用，**不要**顺手把 `girya_lifts` 也塞进字节里：它是 0..=3 的计数，混进位域会让
"读回一个 4"变成"两个无关的布尔都亮了"。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
ARCHIVE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'
HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'

EDITS = [
    # ---- 字段 ----
    (STATE,
     '''    removed_cards: i32,
    deck: [RunId; MAX_RUN_DECK],''',
     '''    removed_cards: i32,
    /// §259：`Girya` 用过几次 `Lift`（0..=`GIRYA_MAX_LIFTS`）。
    ///
    /// 它**不是**"力量层数"：力量是每场战斗开始时按这个数折算出来的（`combat_bonus`），
    /// 所以这个字段跨战斗留存、而战斗里的力量不留存。用满 3 次之后 `Lift` 选项消失。
    girya_lifts: u8,
    /// §259：`Recall` 拿到的红钥匙（Act 4 的门票）。一个布尔就够 —— wiki 只有"拿没拿"。
    ruby_key: bool,
    deck: [RunId; MAX_RUN_DECK],'''),
    # ---- 初值 ----
    (STATE,
     '''            removed_cards: 0,
            deck: [RunId::EMPTY; MAX_RUN_DECK],''',
     '''            removed_cards: 0,
            girya_lifts: 0,
            ruby_key: false,
            deck: [RunId::EMPTY; MAX_RUN_DECK],'''),
    # ---- 读取器 ----
    (STATE,
     '''    pub const fn removed_cards(&self) -> i32 {
        self.removed_cards
    }''',
     '''    pub const fn removed_cards(&self) -> i32 {
        self.removed_cards
    }

    /// §259：`Girya` 已经用过几次 `Lift`。
    #[must_use]
    pub const fn girya_lifts(&self) -> u8 {
        self.girya_lifts
    }

    /// §259：拿到红钥匙了吗（`Recall`）。
    #[must_use]
    pub const fn ruby_key(&self) -> bool {
        self.ruby_key
    }'''),
    # ---- 存档：版本 + 写入 ----
    (ARCHIVE,
     '''/// payload 的版本号（在 CRC 覆盖范围内）。§166：2 = 带内容指纹。
const VERSION: u8 = 2;''',
     '''/// payload 的版本号（在 CRC 覆盖范围内）。§166：2 = 带内容指纹；§259：3 = 篝火字段
/// （`girya_lifts` / `ruby_key`）。
///
/// 加字段就**必须**抬版本：旧读法会把新字节当成下一个字段的开头，于是"存档能读、
/// 但读出来是另一局游戏" —— 那是最坏的一种兼容。抬高之后旧存档是 `ArchiveError::Version`，
/// 响亮且可解释。
const VERSION: u8 = 3;'''),
    (ARCHIVE,
     '''    let flags = u8::from(state.map_generation_failed) | (u8::from(state.boss_beaten) << 1);''',
     '''    // §259：第 3 位是红钥匙。`girya_lifts` 单独一个字节 —— 它是计数（0..=3），
    // 塞进位域会让"读到 4"变成"两个无关的布尔都亮"。
    let flags = u8::from(state.map_generation_failed)
        | (u8::from(state.boss_beaten) << 1)
        | (u8::from(state.ruby_key) << 2);'''),
    (ARCHIVE,
     '''    writer.int(state.removed_cards)?;''',
     '''    writer.int(state.removed_cards)?;
    writer.byte(state.girya_lifts)?;'''),
    # ---- 存档：读回 ----
    (ARCHIVE,
     '''    let removed_cards = reader.int()?;''',
     '''    let removed_cards = reader.int()?;
    let girya_lifts = reader.byte()?;'''),
    (ARCHIVE,
     '''    restored.removed_cards = removed_cards;''',
     '''    restored.removed_cards = removed_cards;
    // §259：容量是语义 —— 读到 4 不是"夹到 3"，是**存档坏了**。
    if girya_lifts > crate::state::GIRYA_MAX_LIFTS {
        return Err(ArchiveError::BadField("girya_lifts"));
    }
    restored.girya_lifts = girya_lifts;
    restored.ruby_key = flags & 0b100 != 0;'''),
    # ---- 常量：Girya 的上限 ----
    (STATE,
     '''pub const REST_HEAL_PERCENT: i32 = 30;''',
     '''pub const REST_HEAL_PERCENT: i32 = 30;

/// §259：`Girya` 的 `Lift` 最多用 3 次（wiki：`Lift` up to 3 times）。
///
/// 它是**容量**也是**语义**：存档读到 4 不是夹到 3，而是存档坏了（`ArchiveError::BadField`）。
/// 用满之后选项从 `campfire_options()` 里消失。
pub const GIRYA_MAX_LIFTS: u8 = 3;'''),
    # ---- 哈希 ----
    (HASH,
     '''    writer.str("removed=").i32(state.removed_cards()).str("\\n");''',
     '''    writer.str("removed=").i32(state.removed_cards()).str("\\n");
    // §259：新的**运行期状态**必须进指纹，否则"两局只差一次 Lift"会哈希相同。
    writer.str("girya=").i32(i32::from(state.girya_lifts())).str("\\n");
    writer
        .str("ruby=")
        .i32(i32::from(state.ruby_key()))
        .str("\\n");'''),
]


def main():
    for path, old, new in EDITS:
        src = io.open(path, encoding='utf-8').read()
        assert src.count(old) == 1, (path, src.count(old), old[:60])
        io.open(path, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new))
    print('layer 1: %d edits' % len(EDITS))


main()
