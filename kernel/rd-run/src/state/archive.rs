//! **存档**：整局状态的单行、压缩、自校验文本（§161.9，REVIEW §六 第 4 步的第一半）。
//!
//! # 为什么是**单行**
//!
//! 这份文本是给人**复制粘贴**的：`web/index.html` 底部有一个"复制档案"按钮和一个"回档"文本框。
//! 多行文本在复制、粘贴、邮件、聊天窗口里会被悄悄改写（行尾空格、CRLF、缩进），而**任何一处改动
//! 都会让存档变成另一局**。单行 + 首尾定界符 + CRC 让"被改过"变成一个响亮的拒绝，而不是一个
//! 看起来正常的错误局面。
//!
//! # 格式
//!
//! ```text
//! RDA1-<base64(RLE(payload))>-<crc32 八位十六进制>
//! ```
//!
//! * `RDA1` 是**头**，尾部是**定界的校验和**，两处都是"基本完整性"的便宜判据。
//! * `payload` 是二进制字段序列（varint + 原始字节），**不含**浮点、不含时间戳：同一局永远编出
//!   同一串（`a_saved_run_round_trips_byte_identically` 钉住这一点）。
//! * RLE 吃 payload 里成片的零与重复的 id 尾巴；base64 让它能贴在任何地方。
//! * CRC32 覆盖 **payload**，所以它同时挡住"粘贴时少了一段"和"改了一个字符"。
//!
//! # 不存的东西，以及为什么
//!
//! * **战斗状态**。一场战斗是 `CombatState`（213 KB、每场重建），而这一层是**运行层**。
//!   战斗进行中调 [`write`] 是允许的（它只看运行层），但 `rd-wasm` 的 `rd_run_archive_*` 在战斗里
//!   **拒绝**并说明原因：一个把战斗丢掉、只回到"进了这个节点"的存档，会让玩家以为自己在打同一场
//!   仗，而敌人其实满血。**那比没有存档更糟。**
//! * **内容版本**。存档里只有 id：id 变了就是"这张牌不存在"，在进战斗时响亮报错（`UnknownCard`），
//!   而不是在回档时假装成功。

use crate::map::{MapNode, MapRow, NodeKind, RunMap, MAX_OUT_EDGES, NODES_PER_ROW, ROWS};
use super::RunId;
use crate::state::{
    BlessingFollowUp, DeckChange, Offer, Pending, Reward, RunState, ShopStock, MAX_REWARD_CARDS,
    MAX_RUN_DECK, MAX_RUN_POTIONS, MAX_RUN_RELICS, MAX_SHOP_CARDS, MAX_SHOP_RELICS,
};
use crate::streams::{RunRng, RunStream};

/// 头部的定界串。改格式就改它（`RDA2`），旧存档于是**响亮**地不认识。
pub const MAGIC: &str = "RDA1";
/// payload 的版本号（在 CRC 覆盖范围内）。
const VERSION: u8 = 1;
/// payload 缓冲。实测一局约 300–900 B；4 KB 是"内容翻倍也不会撞上"的余量。
pub const MAX_PAYLOAD: usize = 4096;
/// 一行文本的缓冲：base64 是 4/3，RLE 最坏 2×（每个字节都是 0xFF 时）。
pub const MAX_ARCHIVE: usize = 16384;

/// 存档失败的原因。每一条都**别**降级成"差不多能用"。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ArchiveError {
    /// 文本不以 [`MAGIC`] 开头。
    BadMagic,
    /// 尾部没有校验和，或者它的形状不对。
    BadTail,
    /// base64 里有非法字符，或者长度不可能是编码产物。
    BadBase64,
    /// payload 放不下（写）或解码后超长（读）。
    TooLong,
    /// CRC 不匹配：文本被改过或被截断。
    BadCrc,
    /// 版本号不认识。
    BadVersion,
    /// 字段形状不对（长度越界、枚举不认识、id 非法）。名字指出是哪一格。
    BadField(&'static str),
    /// payload 读完了还有剩余字节 —— 这不是这个版本的产物。
    Trailing,
}

impl core::fmt::Display for ArchiveError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            Self::BadMagic => f.write_str("not an rd-run archive (missing RDA1)"),
            Self::BadTail => f.write_str("archive has no checksum tail"),
            Self::BadBase64 => f.write_str("archive body is not base64"),
            Self::TooLong => f.write_str("archive does not fit its buffer"),
            Self::BadCrc => f.write_str("archive checksum mismatch (edited or truncated?)"),
            Self::BadVersion => f.write_str("archive version is not supported"),
            Self::BadField(what) => write!(f, "archive field {what} is not valid"),
            Self::Trailing => f.write_str("archive has trailing bytes"),
        }
    }
}

// =============================================================================================
// 信封：RLE + base64 + CRC32
// =============================================================================================

/// RLE 的转义字节。任何字面 0xFF 都写成 `FF 01 FF`。
const RLE_ESCAPE: u8 = 0xFF;
/// 短于此长度的重复不值得编码（3 字节的控制序列换 3 字节）。
const RLE_MIN_RUN: usize = 4;

/// 字节级 RLE：`FF n b` = `b` 重复 n 次（n ≥ 4），`FF 01 FF` = 一个字面 0xFF。
fn rle_encode(src: &[u8], out: &mut [u8]) -> Result<usize, ArchiveError> {
    let mut at = 0usize;
    let mut put = |byte: u8, out: &mut [u8]| -> Result<(), ArchiveError> {
        *out.get_mut(at).ok_or(ArchiveError::TooLong)? = byte;
        at += 1;
        Ok(())
    };
    let mut read = 0usize;
    while read < src.len() {
        let byte = src[read];
        let mut run = 1usize;
        while read + run < src.len() && src[read + run] == byte && run < 255 {
            run += 1;
        }
        if run >= RLE_MIN_RUN {
            let n = run.min(255);
            put(RLE_ESCAPE, out)?;
            put(n as u8, out)?;
            put(byte, out)?;
            read += n;
        } else if byte == RLE_ESCAPE {
            put(RLE_ESCAPE, out)?;
            put(1, out)?;
            put(RLE_ESCAPE, out)?;
            read += 1;
        } else {
            put(byte, out)?;
            read += 1;
        }
    }
    Ok(at)
}

fn rle_decode(src: &[u8], out: &mut [u8]) -> Result<usize, ArchiveError> {
    let mut at = 0usize;
    let mut read = 0usize;
    while read < src.len() {
        let byte = src[read];
        read += 1;
        if byte != RLE_ESCAPE {
            *out.get_mut(at).ok_or(ArchiveError::TooLong)? = byte;
            at += 1;
            continue;
        }
        let count = *src.get(read).ok_or(ArchiveError::BadField("rle"))?;
        read += 1;
        if count == 1 {
            let literal = *src.get(read).ok_or(ArchiveError::BadField("rle"))?;
            read += 1;
            if literal != RLE_ESCAPE {
                return Err(ArchiveError::BadField("rle"));
            }
            *out.get_mut(at).ok_or(ArchiveError::TooLong)? = RLE_ESCAPE;
            at += 1;
            continue;
        }
        if count < RLE_MIN_RUN as u8 {
            return Err(ArchiveError::BadField("rle"));
        }
        let value = *src.get(read).ok_or(ArchiveError::BadField("rle"))?;
        read += 1;
        for _ in 0..count {
            *out.get_mut(at).ok_or(ArchiveError::TooLong)? = value;
            at += 1;
        }
    }
    Ok(at)
}

const BASE64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

fn base64_encode(src: &[u8], out: &mut [u8]) -> Result<usize, ArchiveError> {
    let mut at = 0usize;
    let mut read = 0usize;
    while read + 3 <= src.len() {
        let chunk =
            (src[read] as u32) << 16 | (src[read + 1] as u32) << 8 | src[read + 2] as u32;
        read += 3;
        for shift in [18, 12, 6, 0] {
            *out.get_mut(at).ok_or(ArchiveError::TooLong)? = BASE64[((chunk >> shift) & 0x3f) as usize];
            at += 1;
        }
    }
    match src.len() - read {
        0 => {}
        1 => {
            let chunk = (src[read] as u32) << 16;
            for shift in [18, 12] {
                *out.get_mut(at).ok_or(ArchiveError::TooLong)? =
                    BASE64[((chunk >> shift) & 0x3f) as usize];
                at += 1;
            }
        }
        2 => {
            let chunk = (src[read] as u32) << 16 | (src[read + 1] as u32) << 8;
            for shift in [18, 12, 6] {
                *out.get_mut(at).ok_or(ArchiveError::TooLong)? =
                    BASE64[((chunk >> shift) & 0x3f) as usize];
                at += 1;
            }
        }
        _ => return Err(ArchiveError::TooLong),
    }
    Ok(at)
}

fn base64_value(byte: u8) -> Option<u32> {
    Some(match byte {
        b'A'..=b'Z' => (byte - b'A') as u32,
        b'a'..=b'z' => (byte - b'a') as u32 + 26,
        b'0'..=b'9' => (byte - b'0') as u32 + 52,
        b'+' => 62,
        b'/' => 63,
        _ => return None,
    })
}

fn base64_decode(src: &[u8], out: &mut [u8]) -> Result<usize, ArchiveError> {
    if src.len() % 4 == 1 {
        // 编码产物不可能这样：4 字符 → 3 字节，余 2 → 1 字节，余 3 → 2 字节。
        return Err(ArchiveError::BadBase64);
    }
    let mut at = 0usize;
    let mut read = 0usize;
    while read + 4 <= src.len() {
        let mut chunk = 0u32;
        for index in 0..4 {
            chunk = chunk << 6 | base64_value(src[read + index]).ok_or(ArchiveError::BadBase64)?;
        }
        read += 4;
        for shift in [16, 8, 0] {
            *out.get_mut(at).ok_or(ArchiveError::TooLong)? = ((chunk >> shift) & 0xff) as u8;
            at += 1;
        }
    }
    match src.len() - read {
        0 => {}
        2 => {
            let mut chunk = 0u32;
            for index in 0..2 {
                chunk = chunk << 6 | base64_value(src[read + index]).ok_or(ArchiveError::BadBase64)?;
            }
            chunk <<= 12;
            *out.get_mut(at).ok_or(ArchiveError::TooLong)? = ((chunk >> 16) & 0xff) as u8;
            at += 1;
        }
        3 => {
            let mut chunk = 0u32;
            for index in 0..3 {
                chunk = chunk << 6 | base64_value(src[read + index]).ok_or(ArchiveError::BadBase64)?;
            }
            chunk <<= 6;
            for shift in [16, 8] {
                *out.get_mut(at).ok_or(ArchiveError::TooLong)? = ((chunk >> shift) & 0xff) as u8;
                at += 1;
            }
        }
        _ => return Err(ArchiveError::BadBase64),
    }
    Ok(at)
}

/// CRC-32（IEEE 802.3，反射、初值与异或全 1）。一个存档算一次，不查表。
fn crc32(bytes: &[u8]) -> u32 {
    let mut crc = 0xffff_ffffu32;
    for &byte in bytes {
        crc ^= u32::from(byte);
        for _ in 0..8 {
            let mask = 0u32.wrapping_sub(crc & 1);
            crc = (crc >> 1) ^ (0xedb8_8320 & mask);
        }
    }
    !crc
}

// =============================================================================================
// payload
// =============================================================================================

struct Writer<'a> {
    buf: &'a mut [u8],
    len: usize,
}

impl<'a> Writer<'a> {
    fn byte(&mut self, value: u8) -> Result<(), ArchiveError> {
        *self.buf.get_mut(self.len).ok_or(ArchiveError::TooLong)? = value;
        self.len += 1;
        Ok(())
    }

    /// 无符号 varint（LEB128）：小数字省字节，这是"压缩"的真正来源之一。
    fn var(&mut self, mut value: u64) -> Result<(), ArchiveError> {
        loop {
            let low = (value & 0x7f) as u8;
            value >>= 7;
            if value == 0 {
                return self.byte(low);
            }
            self.byte(low | 0x80)?;
        }
    }

    /// 有符号：zigzag 之后当无符号写（`-1` 于是只占一个字节）。
    fn int(&mut self, value: i32) -> Result<(), ArchiveError> {
        let zig = ((value << 1) ^ (value >> 31)) as u32;
        self.var(u64::from(zig))
    }

    fn id(&mut self, id: RunId) -> Result<(), ArchiveError> {
        let bytes = id.as_str().as_bytes();
        if bytes.len() > u8::MAX as usize {
            return Err(ArchiveError::BadField("id"));
        }
        self.byte(bytes.len() as u8)?;
        for &byte in bytes {
            self.byte(byte)?;
        }
        Ok(())
    }
}

struct Reader<'a> {
    buf: &'a [u8],
    at: usize,
}

impl<'a> Reader<'a> {
    fn byte(&mut self) -> Result<u8, ArchiveError> {
        let value = *self.buf.get(self.at).ok_or(ArchiveError::BadField("eof"))?;
        self.at += 1;
        Ok(value)
    }

    fn var(&mut self) -> Result<u64, ArchiveError> {
        let mut value = 0u64;
        let mut shift = 0u32;
        loop {
            let byte = self.byte()?;
            value |= u64::from(byte & 0x7f) << shift;
            if byte & 0x80 == 0 {
                return Ok(value);
            }
            shift += 7;
            if shift > 63 {
                return Err(ArchiveError::BadField("varint"));
            }
        }
    }

    fn int(&mut self) -> Result<i32, ArchiveError> {
        let zig = self.var()? as u32;
        Ok(((zig >> 1) as i32) ^ -((zig & 1) as i32))
    }

    fn id(&mut self) -> Result<RunId, ArchiveError> {
        let len = self.byte()? as usize;
        let end = self.at.checked_add(len).ok_or(ArchiveError::BadField("id"))?;
        let slice = self.buf.get(self.at..end).ok_or(ArchiveError::BadField("id"))?;
        let text = core::str::from_utf8(slice).map_err(|_| ArchiveError::BadField("id"))?;
        self.at = end;
        RunId::new(text).map_err(|_| ArchiveError::BadField("id"))
    }

    fn at_end(&self) -> bool {
        self.at == self.buf.len()
    }
}

/// `Pending` ↔ 一个字节。**穷尽 match**：加一个变体这里就编译不过。
const fn pending_to_u8(pending: Pending) -> u8 {
    match pending {
        Pending::None => 0,
        Pending::Rest => 1,
        Pending::Shop => 2,
        Pending::Chest => 3,
        Pending::Reward => 4,
        Pending::Event => 5,
        Pending::Start => 6,
        Pending::BlessingCard => 7,
        Pending::EventCard => 8,
    }
}

fn pending_from_u8(value: u8) -> Result<Pending, ArchiveError> {
    Ok(match value {
        0 => Pending::None,
        1 => Pending::Rest,
        2 => Pending::Shop,
        3 => Pending::Chest,
        4 => Pending::Reward,
        5 => Pending::Event,
        6 => Pending::Start,
        7 => Pending::BlessingCard,
        8 => Pending::EventCard,
        _ => return Err(ArchiveError::BadField("pending")),
    })
}

const fn deck_change_to_u8(change: DeckChange) -> u8 {
    match change {
        DeckChange::Remove => 1,
        DeckChange::Upgrade => 2,
        DeckChange::Transform => 3,
    }
}

fn deck_change_from_u8(value: u8) -> Result<DeckChange, ArchiveError> {
    Ok(match value {
        1 => DeckChange::Remove,
        2 => DeckChange::Upgrade,
        3 => DeckChange::Transform,
        _ => return Err(ArchiveError::BadField("deck_change")),
    })
}

const fn blessing_to_u8(follow: BlessingFollowUp) -> u8 {
    match follow {
        BlessingFollowUp::None => 0,
        BlessingFollowUp::GainThreeCards => 1,
        BlessingFollowUp::Deck(DeckChange::Remove) => 2,
        BlessingFollowUp::Deck(DeckChange::Upgrade) => 3,
        BlessingFollowUp::Deck(DeckChange::Transform) => 4,
    }
}

fn blessing_from_u8(value: u8) -> Result<BlessingFollowUp, ArchiveError> {
    Ok(match value {
        0 => BlessingFollowUp::None,
        1 => BlessingFollowUp::GainThreeCards,
        2 => BlessingFollowUp::Deck(DeckChange::Remove),
        3 => BlessingFollowUp::Deck(DeckChange::Upgrade),
        4 => BlessingFollowUp::Deck(DeckChange::Transform),
        _ => return Err(ArchiveError::BadField("blessing_follow")),
    })
}

/// `NodeKind` ↔ 一个字节。**不**依赖 `repr(u8)` 的数值：只认列出来的那七个。
const fn node_kind_to_u8(kind: NodeKind) -> u8 {
    match kind {
        NodeKind::Combat => 0,
        NodeKind::Elite => 1,
        NodeKind::Rest => 2,
        NodeKind::Shop => 3,
        NodeKind::Unknown => 4,
        NodeKind::Treasure => 5,
        NodeKind::Boss => 6,
        NodeKind::Unassigned => 7,
    }
}

fn node_kind_from_u8(value: u8) -> Result<NodeKind, ArchiveError> {
    Ok(match value {
        0 => NodeKind::Combat,
        1 => NodeKind::Elite,
        2 => NodeKind::Rest,
        3 => NodeKind::Shop,
        4 => NodeKind::Unknown,
        5 => NodeKind::Treasure,
        6 => NodeKind::Boss,
        7 => NodeKind::Unassigned,
        _ => return Err(ArchiveError::BadField("node_kind")),
    })
}

/// 读一整格货架：`len` + **每一格**（不只是前 `len` 格）。
fn read_offers(reader: &mut Reader<'_>, out: &mut [Offer]) -> Result<u8, ArchiveError> {
    let count = reader.byte()? as usize;
    if count > out.len() {
        return Err(ArchiveError::BadField("offers"));
    }
    for slot in out.iter_mut() {
        *slot = Offer {
            id: reader.id()?,
            price: reader.int()?,
        };
    }
    Ok(count as u8)
}

/// 把一局写进 `payload`（不含信封）。返回 payload 长度。
fn write_payload(state: &RunState, payload: &mut [u8]) -> Result<usize, ArchiveError> {
    let mut writer = Writer { buf: payload, len: 0 };

    writer.byte(VERSION)?;
    writer.int(state.seed)?;
    writer.byte(state.ascension)?;
    writer.int(state.floor)?;
    writer.int(state.node)?;
    writer.int(state.health)?;
    writer.int(state.health_max)?;
    writer.int(state.gold)?;
    writer.int(state.removed_cards)?;
    writer.int(state.potion_chance)?;
    writer.int(state.rarity_offset)?;
    writer.byte(state.act)?;
    let flags = u8::from(state.map_generation_failed) | (u8::from(state.boss_beaten) << 1);
    writer.byte(flags)?;
    writer.byte(pending_to_u8(state.pending))?;

    writer.byte(state.deck_len)?;
    for card in state.deck.iter().take(state.deck_len as usize) {
        writer.id(*card)?;
    }
    writer.byte(state.relics_len)?;
    for relic in state.relics.iter().take(state.relics_len as usize) {
        writer.id(*relic)?;
    }
    writer.byte(state.potions_len)?;
    for potion in state.potions.iter().take(state.potions_len as usize) {
        writer.id(*potion)?;
    }
    writer.id(state.event)?;
    writer.id(state.last_encounter)?;
    for counter in state.unknown {
        writer.int(counter)?;
    }

    // **Unused slots are written too**, not just the readable prefix: `ShopStock::empty()` starts
    // every price at -1 and a real stock starts at 0, so "the tail does not matter to a reader" is
    // not the same as "the tail is not part of the value". The round-trip test compares whole
    // structs and caught exactly this.
    writer.byte(state.shop.cards_len)?;
    for offer in &state.shop.cards {
        writer.id(offer.id)?;
        writer.int(offer.price)?;
    }
    writer.byte(state.shop.relics_len)?;
    for offer in &state.shop.relics {
        writer.id(offer.id)?;
        writer.int(offer.price)?;
    }

    writer.int(state.reward.gold)?;
    writer.byte(state.reward.cards_len)?;
    for card in state.reward.cards.iter().take(state.reward.cards_len as usize) {
        writer.id(*card)?;
    }
    writer.id(state.reward.potion)?;
    writer.id(state.reward.relic)?;

    for word in state.resolved {
        writer.var(word)?;
    }
    for slot in state.start_offers {
        writer.byte(slot)?;
    }
    writer.byte(match state.blessing_follow {
        None => u8::MAX,
        Some(follow) => blessing_to_u8(follow),
    })?;
    writer.byte(match state.event_follow {
        None => u8::MAX,
        Some(change) => deck_change_to_u8(change),
    })?;

    for counter in state.rng.counters() {
        writer.int(*counter)?;
    }

    // Every slot of every row, pruned ones included (see `MapRow::slots`). RLE eats the zeros.
    for row in state.map.rows() {
        writer.byte(row.count())?;
        for node in row.slots() {
            writer.byte(node.col)?;
            writer.byte(node_kind_to_u8(node.kind))?;
            writer.byte(node.out_degree())?;
            for target in node.out_targets() {
                writer.byte(*target)?;
            }
        }
    }

    Ok(writer.len)
}

/// 从 `payload` 还原一局。**全有或全无**。
fn read_payload(payload: &[u8]) -> Result<RunState, ArchiveError> {
    let mut reader = Reader { buf: payload, at: 0 };
    if reader.byte()? != VERSION {
        return Err(ArchiveError::BadVersion);
    }
    let seed = reader.int()?;
    let ascension = reader.byte()?;
    let floor = reader.int()?;
    let node = reader.int()?;
    let health = reader.int()?;
    let health_max = reader.int()?;
    let gold = reader.int()?;
    let removed_cards = reader.int()?;
    let potion_chance = reader.int()?;
    let rarity_offset = reader.int()?;
    let act = reader.byte()?;
    let flags = reader.byte()?;
    let pending = pending_from_u8(reader.byte()?)?;

    let mut deck = [RunId::EMPTY; MAX_RUN_DECK];
    let deck_len = reader.byte()? as usize;
    if deck_len > MAX_RUN_DECK {
        return Err(ArchiveError::BadField("deck"));
    }
    for slot in 0..deck_len {
        deck[slot] = reader.id()?;
    }
    let mut relics = [RunId::EMPTY; MAX_RUN_RELICS];
    let relics_len = reader.byte()? as usize;
    if relics_len > MAX_RUN_RELICS {
        return Err(ArchiveError::BadField("relics"));
    }
    for slot in 0..relics_len {
        relics[slot] = reader.id()?;
    }
    let mut potions = [RunId::EMPTY; MAX_RUN_POTIONS];
    let potions_len = reader.byte()? as usize;
    if potions_len > MAX_RUN_POTIONS {
        return Err(ArchiveError::BadField("potions"));
    }
    for slot in 0..potions_len {
        potions[slot] = reader.id()?;
    }
    let event = reader.id()?;
    let last_encounter = reader.id()?;
    let mut unknown = [0i32; 3];
    for slot in &mut unknown {
        *slot = reader.int()?;
    }

    // `ShopStock` / `Reward` 的字段是私有的：本模块是 `state` 的子模块，够得着。
    let mut shop = ShopStock::empty();
    let mut shop_cards = [Offer {
        id: RunId::EMPTY,
        price: 0,
    }; MAX_SHOP_CARDS];
    shop.cards_len = read_offers(&mut reader, &mut shop_cards)?;
    shop.cards = shop_cards;
    let mut shop_relics = [Offer {
        id: RunId::EMPTY,
        price: 0,
    }; MAX_SHOP_RELICS];
    shop.relics_len = read_offers(&mut reader, &mut shop_relics)?;
    shop.relics = shop_relics;

    let mut reward = Reward::empty();
    reward.gold = reader.int()?;
    let reward_cards = reader.byte()? as usize;
    if reward_cards > MAX_REWARD_CARDS {
        return Err(ArchiveError::BadField("reward_cards"));
    }
    reward.cards_len = reward_cards as u8;
    for slot in 0..reward_cards {
        reward.cards[slot] = reader.id()?;
    }
    reward.potion = reader.id()?;
    reward.relic = reader.id()?;

    let mut resolved = [0u64; 2];
    for word in &mut resolved {
        *word = reader.var()?;
    }
    let mut start_offers = [0u8; 2];
    for slot in &mut start_offers {
        *slot = reader.byte()?;
    }
    let blessing_byte = reader.byte()?;
    let blessing_follow = if blessing_byte == u8::MAX {
        None
    } else {
        Some(blessing_from_u8(blessing_byte)?)
    };
    let event_byte = reader.byte()?;
    let event_follow = if event_byte == u8::MAX {
        None
    } else {
        Some(deck_change_from_u8(event_byte)?)
    };

    let mut counters = [0i32; RunStream::COUNT];
    for slot in &mut counters {
        *slot = reader.int()?;
    }

    let mut rows = [MapRow::blank(); ROWS];
    for row in &mut rows {
        let count = reader.byte()?;
        if count as usize > NODES_PER_ROW {
            return Err(ArchiveError::BadField("map_row"));
        }
        let mut nodes = [MapNode::empty(0); NODES_PER_ROW];
        for slot in nodes.iter_mut() {
            let col = reader.byte()?;
            let kind = node_kind_from_u8(reader.byte()?)?;
            let degree = reader.byte()? as usize;
            if degree > MAX_OUT_EDGES {
                return Err(ArchiveError::BadField("map_edges"));
            }
            let mut out = [0u8; MAX_OUT_EDGES];
            for edge in &mut out[..degree] {
                *edge = reader.byte()?;
            }
            *slot = MapNode::from_parts(col, kind, &out[..degree])
                .ok_or(ArchiveError::BadField("map_node"))?;
        }
        *row = MapRow::from_slots(count, nodes).ok_or(ArchiveError::BadField("map_row"))?;
    }
    if !reader.at_end() {
        return Err(ArchiveError::Trailing);
    }

    // 借 `new` 造一个合法骨架（它会生成同 seed 的地图，随后被存档里的地图**整个覆盖**）。
    // 这样"某个字段忘了还原"仍然是一个结构合法的状态，而 round-trip 测试会当场抓到它。
    let mut restored =
        RunState::new_with_ascension(seed, health_max, gold, &[], ascension).map_err(|_| ArchiveError::BadField("seed"))?;
    restored.seed = seed;
    restored.floor = floor;
    restored.node = node;
    restored.health = health;
    restored.health_max = health_max;
    restored.gold = gold;
    restored.removed_cards = removed_cards;
    restored.deck = deck;
    restored.deck_len = deck_len as u8;
    restored.relics = relics;
    restored.relics_len = relics_len as u8;
    restored.potions = potions;
    restored.potions_len = potions_len as u8;
    restored.potion_chance = potion_chance;
    restored.map = RunMap::from_rows(rows);
    restored.map_generation_failed = flags & 1 != 0;
    restored.rng = RunRng::from_counters(seed, counters);
    restored.unknown = unknown;
    restored.pending = pending;
    restored.shop = shop;
    restored.reward = reward;
    restored.boss_beaten = flags & 2 != 0;
    restored.resolved = resolved;
    restored.act = act;
    restored.event = event;
    restored.last_encounter = last_encounter;
    restored.start_offers = start_offers;
    restored.blessing_follow = blessing_follow;
    restored.event_follow = event_follow;
    restored.rarity_offset = rarity_offset;
    restored.ascension = ascension;
    Ok(restored)
}

// =============================================================================================
// 公开入口
// =============================================================================================

/// 写一局成**一行**文本，返回写进 `out` 的字节数。
pub fn write(state: &RunState, out: &mut [u8]) -> Result<usize, ArchiveError> {
    let mut payload = [0u8; MAX_PAYLOAD];
    let payload_len = write_payload(state, &mut payload)?;

    let mut packed = [0u8; MAX_PAYLOAD * 2];
    let packed_len = rle_encode(&payload[..payload_len], &mut packed)?;

    let mut at = 0usize;
    for &byte in MAGIC.as_bytes() {
        *out.get_mut(at).ok_or(ArchiveError::TooLong)? = byte;
        at += 1;
    }
    *out.get_mut(at).ok_or(ArchiveError::TooLong)? = b'-';
    at += 1;
    let encoded = base64_encode(&packed[..packed_len], &mut out[at..])?;
    at += encoded;
    *out.get_mut(at).ok_or(ArchiveError::TooLong)? = b'-';
    at += 1;
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let sum = crc32(&payload[..payload_len]);
    for shift in [28, 24, 20, 16, 12, 8, 4, 0] {
        *out.get_mut(at).ok_or(ArchiveError::TooLong)? = HEX[((sum >> shift) & 0xf) as usize];
        at += 1;
    }
    Ok(at)
}

/// 从一行文本还原一局。**全有或全无**：任何一步不合规都返回 `Err`，`state` 一个字节都不改。
pub fn restore(text: &str, state: &mut RunState) -> Result<(), ArchiveError> {
    let bytes = text.trim().as_bytes();
    let magic = MAGIC.as_bytes();
    if bytes.len() < magic.len() + 10 || &bytes[..magic.len()] != magic || bytes[magic.len()] != b'-' {
        return Err(ArchiveError::BadMagic);
    }
    let body = &bytes[magic.len() + 1..];
    // 尾部必须是 `-` + 8 位小写十六进制。
    if body.len() < 10 || body[body.len() - 9] != b'-' {
        return Err(ArchiveError::BadTail);
    }
    let tail_start = body.len() - 9;
    let encoded = &body[..tail_start];
    let mut sum = 0u32;
    for &byte in &body[tail_start + 1..] {
        let digit = match byte {
            b'0'..=b'9' => byte - b'0',
            b'a'..=b'f' => byte - b'a' + 10,
            _ => return Err(ArchiveError::BadTail),
        };
        sum = sum << 4 | u32::from(digit);
    }

    let mut packed = [0u8; MAX_ARCHIVE];
    let packed_len = base64_decode(encoded, &mut packed)?;
    let mut payload = [0u8; MAX_PAYLOAD];
    let payload_len = rle_decode(&packed[..packed_len], &mut payload)?;
    if crc32(&payload[..payload_len]) != sum {
        return Err(ArchiveError::BadCrc);
    }
    let restored = read_payload(&payload[..payload_len])?;
    *state = restored;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> RunState {
        let deck = [
            "strike", "strike", "strike", "strike", "strike", "defend", "defend", "defend",
            "defend", "bash",
        ];
        let mut run = RunState::new_with_ascension(2024, 80, 99, &deck, 3).expect("a run");
        run.adjust_gold(23);
        run.adjust_health(-11);
        run.push_potion("fire_potion").expect("belt room");
        run.push_relic("burning_blood").expect("relic room");
        run
    }

    #[test]
    fn a_saved_run_round_trips_byte_identically() {
        let run = sample();
        let mut first = [0u8; MAX_ARCHIVE];
        let first_len = write(&run, &mut first).expect("write");
        let text = core::str::from_utf8(&first[..first_len]).expect("ascii");

        // 同一局写两次**逐字节相同**：否则"存档"就不是一局的函数，而回放/对拍都建在这一点上。
        let mut second = [0u8; MAX_ARCHIVE];
        let second_len = write(&run, &mut second).expect("write");
        assert_eq!(first[..first_len], second[..second_len], "two writes differ");

        let mut restored = RunState::new_with_ascension(1, 80, 0, &[], 0).expect("a skeleton");
        restore(text, &mut restored).expect("restore");
        // `RunState` 派生 `PartialEq`，所以判据是**整局相等** —— 漏还原一个字段就红。
        assert_eq!(restored, run, "the archive lost a field");
    }

    #[test]
    fn the_archive_is_one_line_with_a_head_and_a_tail() {
        let mut out = [0u8; MAX_ARCHIVE];
        let len = write(&sample(), &mut out).expect("write");
        let text = core::str::from_utf8(&out[..len]).expect("ascii");
        assert!(!text.contains('\n') && !text.contains('\r'), "an archive is ONE line");
        assert!(text.starts_with("RDA1-"), "head: {}", &text[..12]);
        assert!(text.rfind('-').is_some_and(|at| text.len() - at == 9), "tail: 8 hex digits");
        // 一行 = 可直接复制粘贴的字符串；比键盘可读性更重要的是**不会被换行改写**。
        // 一局（15 行地图 + 10 张牌）实测约 1 KB 的单行文本：能贴进任何聊天窗口。
        assert!(len < 4096, "unexpectedly large archive: {len} bytes");
        std::println!("archive of the sample run: {len} bytes");
    }

    #[test]
    fn an_edited_or_truncated_archive_is_refused_not_guessed() {
        let mut out = [0u8; MAX_ARCHIVE];
        let len = write(&sample(), &mut out).expect("write");
        let text = core::str::from_utf8(&out[..len]).expect("ascii");
        let mut run = sample();

        // 改一个字符（payload 的一部分）⇒ CRC 不匹配。
        let mut edited = std::string::String::from(text);
        let at = 8 + 4;
        let byte = edited.as_bytes()[at];
        let replacement = if byte == b'A' { 'B' } else { 'A' };
        edited.replace_range(at..at + 1, &replacement.to_string());
        assert_eq!(restore(&edited, &mut run), Err(ArchiveError::BadCrc));

        // 截掉尾巴 ⇒ 没有校验和。
        let cut = &text[..text.len() - 5];
        assert_eq!(restore(cut, &mut run), Err(ArchiveError::BadTail));

        // 不是存档 ⇒ 头部就不认。
        assert_eq!(restore("hello", &mut run), Err(ArchiveError::BadMagic));
        assert_eq!(restore("RDA2-AAAA-badc0de0", &mut run), Err(ArchiveError::BadMagic));

        // 被拒绝之后**一局都没变**（判据 `RunState` 相等，与 §161.2(a) 同一条）。
        assert_eq!(run, sample(), "a refused restore changed the run");
    }

    #[test]
    fn the_envelope_round_trips_and_rejects_nonsense() {
        let payload = b"\x00\x00\x00\x00strike\xff\xff\x01\x02\x03";
        let mut packed = [0u8; 256];
        let packed_len = rle_encode(payload, &mut packed).expect("rle");
        assert!(packed_len < payload.len() + 4);
        let mut back = [0u8; 256];
        let back_len = rle_decode(&packed[..packed_len], &mut back).expect("rle back");
        assert_eq!(&back[..back_len], payload);

        let mut encoded = [0u8; 512];
        let encoded_len = base64_encode(&packed[..packed_len], &mut encoded).expect("b64");
        let mut decoded = [0u8; 512];
        let decoded_len = base64_decode(&encoded[..encoded_len], &mut decoded).expect("b64 back");
        assert_eq!(&decoded[..decoded_len], &packed[..packed_len]);

        // 一个非法字符、一个不可能的余数，都必须响亮。
        assert_eq!(base64_decode(b"AAA!", &mut decoded), Err(ArchiveError::BadBase64));
        assert_eq!(base64_decode(b"AAAAA", &mut decoded), Err(ArchiveError::BadBase64));
        // CRC 自己的已知值（"123456789" 是 CRC-32/ISO-HDLC 的标准校验向量）。
        assert_eq!(crc32(b"123456789"), 0xcbf4_3926);
    }
}
