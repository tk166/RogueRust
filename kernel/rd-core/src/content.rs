//! RDCF 内容镜像的读取器 —— 把 `tools/contentc/` 编出来的二进制解析成可借用的表。
//!
//! **规格**：`docs/spec/content-binary-format.md`（写端/读端共用的唯一事实来源）。
//! 真实产物：`tools/contentc/out/content.core.rdcf`（85,616 B）与 `content.rdcf`（158,296 B），
//! 各表的条目数见 `tools/contentc/out/manifest.json`。
//!
//! 设计约束（与内核其余部分一致）：
//! * **零分配**：解析结果全部借用传入的字节切片，不复制、不分配。
//! * **零 panic**：一切越界/畸形输入都走 `Result` 或 `Option`，绝不 `unwrap` 到 panic ——
//!   镜像是构建期产物，但它坏了的表现必须是"拒绝加载"，不是"设备重启"。
//! * 本模块**不依赖状态模型**（`state.rs`），所以它可以独立开发与验收。
//!
//! # 实测校准（spec / `reader.py` / 真实镜像三者对照的结论）
//!
//! 1. **目录项是 12 字节**：`offset:u32, bytes:u32, count:u32` 紧密排列（`reader.py` 与
//!    `rdcfmt.unpack_dir()` 都是这么读的）。
//! 2. **头部字段只占 28 字节**：spec §2 列的字段（magic…content_hash/reserved）加起来正好 28 B，
//!    而 `HEADER_BYTES` = `dir_off` = 32 —— 第 28..31 字节**没有任何字段描述**（实测全 0）。
//!    本模块按头里的 `dir_off` 找目录，不假设目录紧贴在"最后一个字段"后面。
//! 3. **行宽是 `align4(2×格数)`，末尾填充不是格**：`CARD` 15 格 = 30 B → **stride 32**、
//!    `STAT` 20 格 = 40 B → stride 40、`EACT` 7 格 = 14 B → 16、`ENCT` 8 格 = 16 B → 16、
//!    `REL` 5 格 = 10 B → 12。与 `manifest.json` 的 `stride`、`rdcfmt.row_stride()` 完全一致。
//! 4. **`IDX` 不是"id → 唯一实体"**：真实镜像里 `overfilled_inbox` 同时是卡牌（`CARD[42]`）
//!    和遗物（`REL[33]`），两条相邻记录。`reader.py` 用 `setdefault` 静默保留**第一条**；
//!    本模块的 `lookup` 采用同一规则，需要区分实体类别时用 `lookup_in(id, kind)`。
//! 5. **保留 opcode 0..15 的 `opclass` 不都是 0**：0..7 实测是 `1`（"普通对象"），8..15 是全零空洞。
//!    所以**必须先判 `op < 16` 再碰 `opclass`** —— `reader.py` 正是这么做的。
//! 6. `reader.py::Rom.__init__` 要求 `len(blob) == header.total_size`；本模块只要求 `>=`：
//!    MCU 上镜像常常躺在比它大的 flash 分区/PSRAM 缓冲里，`total_size` 才是权威边界
//!    （所有段的区间都被限制在 `total_size` 之内，尾巴一律不看）。

// ===========================================================================
// 文件头与段目录
// ===========================================================================

/// 小端 `0x46434452`（文件头前 4 字节）。
pub const MAGIC: u32 = 0x4643_4452;
/// 头部字节数。
pub const HEADER_BYTES: usize = 32;
/// 目录项字节数：`(offset: u32, bytes: u32, count: u32)` 紧密排列，**不是 16 字节**。
/// （这一条是实测出来的：见 `tools/rdcf_verify.py` 的注释。）
pub const DIRECTORY_ENTRY_BYTES: usize = 12;
/// 格式版本（头里 `version`）。
/// 2: `CARD` gained a `Rarity` cell（stride 没变 —— 那一格落在原有对齐填充里）。
///
/// 内核的格表是**固定**的，而镜像原本既不记格数、也不随 schema 动版本号 ⇒ 15 格的旧镜像
/// 配 16 格的新内核会**解析成功并读出垃圾**（把旧的 `extra` 当 `Rarity`，`content.string`
/// 碰巧拿到合法串号就返回一段像样的文本）。schema 变更必须响亮，所以版本号跟着 schema 走。
pub const FORMAT_VERSION: u16 = 4;
/// 目录项数（头里 `nsec`）。0..=14 有名字，15..19 保留。
pub const SECTION_COUNT: usize = 20;
/// 头部 `flags` 的 bit0：表现层已剥（`content.core.rdcf`）。
pub const FLAG_PRESENTATION_STRIPPED: u16 = 1;

// 段号。名字与 `rdcfmt.SEC_NAMES` 逐字一致。
pub const S_STR: usize = 0;
pub const S_STRO: usize = 1;
pub const S_OPD: usize = 2;
pub const S_OPF: usize = 3;
pub const S_TRM: usize = 4;
pub const S_TRW: usize = 5;
pub const S_AUX: usize = 6;
pub const S_CARD: usize = 7;
pub const S_STAT: usize = 8;
pub const S_EACT: usize = 9;
pub const S_ENCT: usize = 10;
pub const S_REL: usize = 11;
/// The `?`-room table (`EV`). `rdcfmt.S_EV`, same number -- and, like every section id, it must be
/// the index of its entry in `rdcfmt.SEC_ORDER`.
pub const S_EV: usize = 15;
/// The potion table (`POT`). `rdcfmt.S_POT`, and -- like every section id -- the index of its entry
/// in `rdcfmt.SEC_ORDER`.
pub const S_POT: usize = 16;
pub const S_ROOT: usize = 12;
pub const S_IDX: usize = 13;
pub const S_TAGS: usize = 14;

/// 段号 → 段名；15..19 是保留段，名字为空串。
pub const SECTION_NAMES: [&str; SECTION_COUNT] = [
    "STR", "STRO", "OPD", "OPF", "TRM", "TRW", "AUX", "CARD", "STAT", "EACT", "ENCT", "REL", "ROOT",
    "IDX", "TAGS", "", "", "", "", "",
];

/// 段名 → 段号（大小写敏感，只认 spec 里的那 15 个名字）。
/// 注意状态表的段名是 `STAT`（`rdcfmt.SEC_NAMES`），行 schema 的键才是 `STATUS`。
#[must_use]
pub fn section_id_by_name(name: &str) -> Option<usize> {
    SECTION_NAMES
        .iter()
        .position(|n| !n.is_empty() && *n == name)
}

// 头部字段偏移（实测：见模块文档第 2 条）。
const HDR_VERSION: usize = 4;
const HDR_FLAGS: usize = 6;
const HDR_TOTAL_SIZE: usize = 8;
const HDR_DIR_OFF: usize = 12;
const HDR_NSEC: usize = 16;
const HDR_SCHEMA_VERSION: usize = 18;
const HDR_CONTENT_HASH: usize = 20;

// ===========================================================================
// 段内词汇：opcode、字段类别、哨兵、实体类别
// ===========================================================================

// 保留 opcode（固定语义）。
pub const OP_NULL: u16 = 0;
pub const OP_STR: u16 = 1;
pub const OP_INT: u16 = 2;
pub const OP_BOOL: u16 = 3;
pub const OP_ARR: u16 = 4;
pub const OP_JSON: u16 = 5;
pub const OP_WRAP_LOWER: u16 = 6;
pub const OP_WRAP_UPPER: u16 = 7;
/// 第一个动态分配的 opcode（≥ 此值的 opcode 才可能是 IR 节点或普通对象形状）。
pub const OP_FIRST_DYNAMIC: u16 = 16;
/// `OPD[op].opclass == 0`：IR 节点，结果形如 `{kind: name, value: {...}}`。
pub const OPCLASS_IR: u8 = 0;
/// `OPD[op].opclass == 1`：普通对象形状，结果就是那个字典。
pub const OPCLASS_GENERIC: u8 = 1;

// 字段类别（`OPF` 里的 `field_kind`）。
pub const F_STR: u8 = 1;
pub const F_INT: u8 = 2;
pub const F_BOOL: u8 = 3;
pub const F_TERM: u8 = 4;
pub const F_TERMLIST: u8 = 5;
pub const F_STRLIST: u8 = 6;
pub const F_JSON: u8 = 7;

/// 字段类别 → 占几个 u16 槽（下标即类别；`[0]` 是无效类别）。
pub const FIELD_SLOTS: [u8; 8] = [0, 1, 1, 1, 1, 2, 2, 1];

/// 字段类别 → 槽数；未知类别返回 `None`（**不 panic**，`reader.py` 在这种输入上会抛 `KeyError`）。
#[must_use]
pub fn field_slots(kind: u8) -> Option<u8> {
    match FIELD_SLOTS.get(kind as usize) {
        Some(&n) if n > 0 => Some(n),
        _ => None,
    }
}

/// 该字段的 JSON 值写成 `{"value": s}`（小写包装）。
pub const FLAG_WRAP_LOWER: u8 = 1;
/// 该字段的 JSON 值写成 `{"Value": s}`（大写包装）。
pub const FLAG_WRAP_UPPER: u8 = 2;

// 哨兵：让"键不存在"与"键存在且为 null"可区分。
/// `F_STR` / `F_TERM` / `F_JSON` 的"键不存在"。
pub const ABSENT16: u16 = 0xFFFF;
/// `F_STR` / `F_TERM` / `F_JSON` 的"键存在且为 null"。
pub const NULL16: u16 = 0xFFFE;
/// `F_INT` 的"键不存在"（= -32768）。
pub const ABSENT_INT: u16 = 0x8000;
/// `F_INT` 的"键存在且为 null"（= -32767）。
pub const NULL_INT: u16 = 0x8001;
/// `F_BOOL` 的"键不存在"。
pub const BOOL_ABSENT: u16 = 0;
/// `F_BOOL` 的 false。
pub const BOOL_FALSE: u16 = 1;
/// `F_BOOL` 的 true。
pub const BOOL_TRUE: u16 = 2;
/// `F_BOOL` 的"键存在且为 null"。
pub const BOOL_NULL: u16 = 3;
/// `F_TERMLIST` / `F_STRLIST` 的"键不存在"（第二个槽）。
pub const LIST_ABSENT: u16 = 0xFFFF;
/// `F_TERMLIST` / `F_STRLIST` 的"键存在且为 null"。
pub const LIST_NULL: u16 = 0xFFFE;

// 实体类别（`IDX` 里的 `ekind`）。
pub const EK_CARD: u8 = 1;
pub const EK_STATUS: u8 = 2;
pub const EK_EACTION: u8 = 3;
pub const EK_ENCOUNTER: u8 = 4;
pub const EK_RELIC: u8 = 5;
pub const EK_MAPNODE: u8 = 6;
pub const EK_EVENT: u8 = 7;
pub const EK_SHOP: u8 = 8;
pub const EK_CHARACTER: u8 = 9;
/// Potions. Not indexed in `SEC_IDX` (they are looked up in their own table), so
/// `Table::from_entity_kind` keeps returning `None` for it.
pub const EK_POTION: u8 = 10;

/// 实体类别 → 名字（`card` / `status` / … / `character`）。
#[must_use]
pub fn entity_kind_name(kind: u8) -> Option<&'static str> {
    match kind {
        EK_CARD => Some("card"),
        EK_STATUS => Some("status"),
        EK_EACTION => Some("enemy_action"),
        EK_ENCOUNTER => Some("encounter"),
        EK_RELIC => Some("relic"),
        EK_MAPNODE => Some("map_node"),
        EK_EVENT => Some("event"),
        EK_SHOP => Some("shop"),
        EK_CHARACTER => Some("character"),
        _ => None,
    }
}

// ===========================================================================
// 小工具（全部无 panic：一律 `get` + `checked_*`）
// ===========================================================================

const fn align4(n: u32) -> u32 {
    (n + 3) & !3
}

fn u16_at(bytes: &[u8], off: usize) -> Option<u16> {
    Some(u16::from_le_bytes([
        *bytes.get(off)?,
        *bytes.get(off + 1)?,
    ]))
}

fn u32_at(bytes: &[u8], off: usize) -> Option<u32> {
    Some(u32::from_le_bytes([
        *bytes.get(off)?,
        *bytes.get(off + 1)?,
        *bytes.get(off + 2)?,
        *bytes.get(off + 3)?,
    ]))
}

/// 串号 → 串（`STR` 池 + `STRO` 偏移表）。串号 0 固定是空串。
///
/// 与 `reader.py::string_at` 同规则：取 `[STRO[i-1], STRO[i]-1)`，即丢掉结尾的 NUL。
/// `STRO` 只有一项（空池）或串号越界 → `None`；非法 UTF-8 → `None`。
fn string_at<'a>(pool: &'a [u8], stro: &'a [u8], index: u16) -> Option<&'a str> {
    if index == 0 {
        return Some("");
    }
    let entries = stro.len() / 4;
    let i = index as usize;
    if i >= entries {
        return None;
    }
    let start = u32_at(stro, (i - 1) * 4)? as usize;
    let end = u32_at(stro, i * 4)? as usize;
    let stop = if end > start { end - 1 } else { start };
    core::str::from_utf8(pool.get(start..stop)?).ok()
}

// ===========================================================================
// 段视图 / 错误
// ===========================================================================

/// 一段表的只读视图。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Section<'a> {
    pub offset: u32,
    pub bytes: u32,
    pub count: u32,
    pub data: &'a [u8],
}

impl<'a> Section<'a> {
    /// `data` 是否为空（空段的 `count == 0, bytes == 0`，`offset` 实测是 0）。
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.data.is_empty()
    }

    /// 本段最后一字节之后的位置。
    #[must_use]
    pub fn end(&self) -> u64 {
        self.offset as u64 + self.bytes as u64
    }

    /// 第 `index` 个 u16（小端）。越界 `None`。
    #[must_use]
    pub fn u16_at(&self, index: usize) -> Option<u16> {
        u16_at(self.data, index.checked_mul(2)?)
    }

    /// 第 `index` 个 u32（小端）。越界 `None`。
    #[must_use]
    pub fn u32_at(&self, index: usize) -> Option<u32> {
        u32_at(self.data, index.checked_mul(4)?)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContentError {
    TooSmall,
    BadMagic(u32),
    UnsupportedVersion(u16),
    /// 目录项里的 offset/bytes 落在文件之外。
    SectionOutOfRange { index: usize },
    /// 头部声明的段数与目录区放不下。
    DirectoryTruncated,
}

/// `validate()` 的失败原因。
///
/// 比 `ContentError` 细：`ContentError` 是**冻结**的 6 个码（`parse` 用），塞不下
/// "段重叠 / 未对齐 / count 与 bytes 不自洽"这三种只有结构自检才看得见的毛病。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ValidationError {
    /// 第 `index` 段的 `[offset, offset+bytes)` 不在镜像声明的 `total_size` 之内。
    OutOfRange { index: usize },
    /// 第 `index` 段的 `offset` 没有 4 字节对齐（spec：每段 4 字节对齐）。
    Misaligned { index: usize },
    /// 第 `index` 段声明 `count` 个元素、每个至少 `stride` 字节，但只有 `bytes` 字节。
    CountExceedsBytes {
        index: usize,
        count: u32,
        stride: u32,
        bytes: u32,
    },
    /// 第 `a` 段与第 `b` 段的字节区间重叠（两段都非空）。
    Overlap { a: usize, b: usize },
    /// `STRO` 的第 `entry` 项不合规：不严格递增、越过池尾、或所指字符串没有 NUL 结尾。
    BadStringIndex { entry: usize },
    /// `STR`/`STRO` 的 `count` 与索引表长度对不上（串号空间自相矛盾）。
    StringCountMismatch {
        /// `STRO` 的实际项数（`bytes / 4`）。
        entries: usize,
        str_count: u32,
        stro_count: u32,
    },
}

// ===========================================================================
// 镜像本体
// ===========================================================================

/// 一份已解析的镜像。所有表都是对 `blob` 的借用。
pub struct Content<'a> {
    blob: &'a [u8],
    version: u16,
    section_count: usize,
}

/// 只打摘要，**不打 blob**：这份结构通常会在日志/断言里出现，几十 KB 的字节数组没人想看。
impl core::fmt::Debug for Content<'_> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_struct("Content")
            .field("version", &self.version)
            .field("section_count", &self.section_count)
            .field("total_size", &self.total_size())
            .field("buffer_len", &self.blob.len())
            .finish()
    }
}

impl<'a> Content<'a> {
    /// 解析头部与段目录。**不校验段内语义** —— 那是 `validate` 与调用方的事。
    ///
    /// 这里只保证"拿得到段视图"这件事成立：头在、magic/版本对、`total_size` 真的在缓冲区里
    /// （`blob.len() >= total_size`，截断 → `TooSmall`）、目录区在声明的镜像内、
    /// 每个目录项都落在声明的镜像内（否则 `SectionOutOfRange`）。
    pub fn parse(blob: &'a [u8]) -> Result<Self, ContentError> {
        // 1. 头本身。
        if blob.len() < HEADER_BYTES {
            return Err(ContentError::TooSmall);
        }
        let magic = u32_at(blob, 0).ok_or(ContentError::TooSmall)?;
        if magic != MAGIC {
            return Err(ContentError::BadMagic(magic));
        }
        let version = u16_at(blob, HDR_VERSION).ok_or(ContentError::TooSmall)?;
        if version != FORMAT_VERSION {
            return Err(ContentError::UnsupportedVersion(version));
        }

        // 2. 头声明的总长必须真的在缓冲区里：短了就是被截断。
        let total = u32_at(blob, HDR_TOTAL_SIZE).ok_or(ContentError::TooSmall)? as usize;
        if total < HEADER_BYTES || blob.len() < total {
            return Err(ContentError::TooSmall);
        }

        // 3. 目录区：不许压在文件头里，且必须落在**声明的**镜像之内。
        //    `nsec` 上限是 `SECTION_COUNT`：本格式只有 20 段（15 个有名字 + 5 个保留），
        //    多出来的头部直接判目录不合规 —— 也让后面所有循环天然有界（`reader.py` 会照单全收）。
        let dir_off = u32_at(blob, HDR_DIR_OFF).ok_or(ContentError::TooSmall)? as usize;
        let nsec = u16_at(blob, HDR_NSEC).ok_or(ContentError::TooSmall)? as usize;
        if dir_off < HEADER_BYTES || nsec > SECTION_COUNT {
            return Err(ContentError::DirectoryTruncated);
        }
        let dir_end = dir_off as u64 + (nsec as u64) * (DIRECTORY_ENTRY_BYTES as u64);
        if dir_end > total as u64 {
            return Err(ContentError::DirectoryTruncated);
        }

        // 4. 每个目录项都要落在声明的镜像之内。
        let mut i = 0;
        while i < nsec {
            let base = dir_off + i * DIRECTORY_ENTRY_BYTES;
            let offset = u32_at(blob, base).ok_or(ContentError::DirectoryTruncated)? as u64;
            let bytes = u32_at(blob, base + 4).ok_or(ContentError::DirectoryTruncated)? as u64;
            if offset + bytes > total as u64 {
                return Err(ContentError::SectionOutOfRange { index: i });
            }
            i += 1;
        }

        Ok(Self {
            blob,
            version,
            section_count: nsec,
        })
    }

    #[must_use]
    pub fn version(&self) -> u16 {
        self.version
    }

    #[must_use]
    pub fn section_count(&self) -> usize {
        self.section_count
    }

    /// 按段号取表。越界返回 `None`。
    #[must_use]
    pub fn section(&self, index: usize) -> Option<Section<'a>> {
        if index >= self.section_count {
            return None;
        }
        let base = self
            .directory_offset()?
            .checked_add(index.checked_mul(DIRECTORY_ENTRY_BYTES)?)?;
        let offset = u32_at(self.blob, base)?;
        let bytes = u32_at(self.blob, base + 4)?;
        let count = u32_at(self.blob, base + 8)?;
        let start = offset as usize;
        let end = start.checked_add(bytes as usize)?;
        Some(Section {
            offset,
            bytes,
            count,
            data: self.blob.get(start..end)?,
        })
    }

    /// 按段名取表（`STR`/`STRO`/`OPD`/`OPF`/`TRM`/`TRW`/`AUX`/`CARD`/`STAT`/`EACT`/`ENCT`/`REL`/`ROOT`/`IDX`/`TAGS`）。
    /// 段名到段号的对应关系见 `docs/spec/content-binary-format.md`。
    #[must_use]
    pub fn section_by_name(&self, name: &str) -> Option<Section<'a>> {
        self.section(section_id_by_name(name)?)
    }

    /// 字符串池取串（`STR` + `STRO`）。越界或非法 UTF-8 返回 `None`。
    ///
    /// 串号 0 是空串（`ABSENT16`/`NULL16` 这类哨兵**不是**串号，`string_count()` 之外的号一律 `None`）。
    #[must_use]
    pub fn string(&self, index: u16) -> Option<&'a str> {
        let stro = self.section(S_STRO)?;
        let pool = self.section(S_STR)?;
        string_at(pool.data, stro.data, index)
    }

    // ---------------------------------------------------------------- 头部
    /// 头部原始 `flags`（bit0 = 表现层已剥）。
    #[must_use]
    pub fn flags(&self) -> u16 {
        u16_at(self.blob, HDR_FLAGS).unwrap_or(0)
    }

    /// `flags & 1`：这是 `content.core.rdcf` 那种剥掉表现层的镜像，`NameKey`/`Label` 不可假设存在。
    #[must_use]
    pub fn presentation_stripped(&self) -> bool {
        self.flags() & FLAG_PRESENTATION_STRIPPED != 0
    }

    /// 头部声明的镜像字节数（段区间一律以它为准）。
    #[must_use]
    pub fn total_size(&self) -> u32 {
        u32_at(self.blob, HDR_TOTAL_SIZE).unwrap_or(0)
    }

    /// 文档自己的 `SchemaVersion`（独立于 `FORMAT_VERSION`）。
    #[must_use]
    pub fn schema_version(&self) -> u16 {
        u16_at(self.blob, HDR_SCHEMA_VERSION).unwrap_or(0)
    }

    /// 原文 JSON 的 FNV-1a-32（判镜像是否过期用）。
    #[must_use]
    pub fn content_hash(&self) -> u32 {
        u32_at(self.blob, HDR_CONTENT_HASH).unwrap_or(0)
    }

    fn directory_offset(&self) -> Option<usize> {
        u32_at(self.blob, HDR_DIR_OFF).map(|v| v as usize)
    }

    // ------------------------------------------------------------ 字符串池
    /// 池内串数 = `STRO` 项数 - 1（串号 1..=此值有效；串号 0 是空串）。
    #[must_use]
    pub fn string_count(&self) -> usize {
        self.section(S_STRO)
            .map(|s| s.bytes as usize / 4)
            .unwrap_or(0)
            .saturating_sub(1)
    }

    /// 遍历串号 1..=`string_count()`。元素是 `Option`：池坏掉时该项是 `None` 而不是 panic。
    #[must_use]
    pub fn strings(&self) -> Strings<'a> {
        let (stro, pool) = match (self.section(S_STRO), self.section(S_STR)) {
            (Some(stro), Some(pool)) => (stro.data, pool.data),
            _ => (&[][..], &[][..]),
        };
        Strings {
            stro,
            pool,
            next: 0,
            end: (stro.len() / 4).saturating_sub(1) as u32,
        }
    }

    // ------------------------------------------------------ opcode / term
    /// `OPD` 里的 opcode 条数（`bytes / 8`，本内容 = 130）。
    #[must_use]
    pub fn opcode_count(&self) -> usize {
        self.section(S_OPD)
            .map(|s| (s.bytes as usize / 8).min(s.count as usize))
            .unwrap_or(0)
    }

    /// 取一条 opcode 描述（含它那 `nfields` 条字段描述）。越界 `None`。
    #[must_use]
    pub fn opcode(&self, op: u16) -> Option<Opcode<'a>> {
        let opd = self.section(S_OPD)?;
        if op as usize >= self.opcode_count() {
            return None;
        }
        let base = (op as usize).checked_mul(8)?;
        let name_str = u16_at(opd.data, base + 4)?;
        let nfields = *opd.data.get(base + 6)?;
        let opclass = *opd.data.get(base + 7)?;
        let field_off = u32_at(opd.data, base)? as usize;
        let opf = self.section(S_OPF)?;
        let start = field_off;
        let end = start.checked_add((nfields as usize).checked_mul(4)?)?;
        Some(Opcode {
            op,
            name_str,
            opclass,
            fields: opf.data.get(start..end)?,
        })
    }

    /// opcode 的名字（保留 opcode 是空串；越界 `None`）。
    #[must_use]
    pub fn opcode_name(&self, op: u16) -> Option<&'a str> {
        self.string(self.opcode(op)?.name_str)
    }

    /// `TRW` 里的 term 条数（本内容 = 2143）。
    #[must_use]
    pub fn term_count(&self) -> usize {
        self.section(S_TRW)
            .map(|s| (s.bytes as usize / 2).min(s.count as usize))
            .unwrap_or(0)
    }

    /// 取一条 term 记录：`op` + 按字段类别推出的 `nslots` 个槽。越界/描述不合法 `None`。
    #[must_use]
    pub fn term(&self, tid: u16) -> Option<Term<'a>> {
        let trw = self.section(S_TRW)?;
        let trm = self.section(S_TRM)?;
        if tid as usize >= self.term_count() {
            return None;
        }
        let word = trw.u16_at(tid as usize)? as usize;
        let base = word.checked_mul(4)?;
        let op = u16_at(trm.data, base)?;
        let nslots = self.opcode(op)?.nslots()?;
        let start = base.checked_add(2)?;
        let end = start.checked_add(nslots.checked_mul(2)?)?;
        Some(Term {
            id: tid,
            op,
            slots: trm.data.get(start..end)?,
        })
    }

    /// `AUX` 的格数（本内容 = 2078）。
    #[must_use]
    pub fn aux_cells(&self) -> usize {
        self.section(S_AUX)
            .map(|s| (s.bytes as usize / 2).min(s.count as usize))
            .unwrap_or(0)
    }

    /// `AUX[index]`（`F_TERMLIST` / `F_STRLIST` 的列表体）。越界 `None`。
    #[must_use]
    pub fn aux(&self, index: u16) -> Option<u16> {
        if index as usize >= self.aux_cells() {
            return None;
        }
        self.section(S_AUX)?.u16_at(index as usize)
    }

    // ------------------------------------------------------------ 根指针
    /// `ROOT` 的表项数（本内容的 core 镜像 = 16，full = 17）。
    #[must_use]
    pub fn root_count(&self) -> usize {
        self.section(S_ROOT)
            .map(|s| (s.bytes as usize / 4).min(s.count as usize))
            .unwrap_or(0)
    }

    /// 第 `index` 个顶层键 → term。越界 `None`。
    #[must_use]
    pub fn root(&self, index: usize) -> Option<RootEntry<'a>> {
        if index >= self.root_count() {
            return None;
        }
        let root = self.section(S_ROOT)?;
        let base = index.checked_mul(4)?;
        let key_str = u16_at(root.data, base)?;
        let term = u16_at(root.data, base + 2)?;
        Some(RootEntry {
            key: self.string(key_str)?,
            term,
        })
    }

    /// 按顶层键名取 term（线性扫 16/17 条；`Map`、`Events`、`Start`…）。
    #[must_use]
    pub fn root_by_name(&self, name: &str) -> Option<u16> {
        (0..self.root_count())
            .find_map(|i| self.root(i).filter(|r| r.key == name))
            .map(|r| r.term)
    }

    // ---------------------------------------------------------- 符号表
    /// `IDX` 的条目数（本内容 = 691）。
    #[must_use]
    pub fn id_count(&self) -> usize {
        self.section(S_IDX)
            .map(|s| (s.bytes as usize / 8).min(s.count as usize))
            .unwrap_or(0)
    }

    /// 第 `index` 条 id 记录。越界或串号不可解析 → `None`。
    #[must_use]
    pub fn id_entry(&self, index: usize) -> Option<IdEntry<'a>> {
        if index >= self.id_count() {
            return None;
        }
        let idx = self.section(S_IDX)?;
        let base = index.checked_mul(8)?;
        let str_id = u16_at(idx.data, base)?;
        let entity_kind = *idx.data.get(base + 2)?;
        let flags = *idx.data.get(base + 3)?;
        let row = u16_at(idx.data, base + 4)?;
        Some(IdEntry {
            position: index as u32,
            id: self.string(str_id)?,
            entity_kind,
            flags,
            index: row,
        })
    }

    /// `IDX` 里第一个 `id >= 目标` 的位置（`IDX` 按字符串 id 排序，可二分）。
    fn id_lower_bound(&self, id: &str) -> usize {
        let n = self.id_count();
        let (mut lo, mut hi) = (0usize, n);
        while lo < hi {
            let mid = lo + (hi - lo) / 2;
            match self.id_entry(mid) {
                Some(e) if e.id < id => lo = mid + 1,
                Some(_) => hi = mid,
                // 目录项由 `parse` 保证存在；真取不到就停在这里（不 panic）。
                None => return lo,
            }
        }
        lo
    }

    /// id 字符串 → 实体。找不到 `None`。
    ///
    /// **同一个 id 可以出现在多个实体类别里**（实测：`overfilled_inbox` 既是卡牌也是遗物），
    /// 这时返回**最靠前的那一条** —— 与 `reader.py` 的 `setdefault` 语义一致；
    /// 要指定类别请用 `lookup_in`。
    #[must_use]
    pub fn lookup(&self, id: &str) -> Option<IdEntry<'a>> {
        let entry = self.id_entry(self.id_lower_bound(id))?;
        if entry.id == id {
            Some(entry)
        } else {
            None
        }
    }

    /// id 字符串 + 实体类别 → 实体（处理同 id 跨类别的情况）。
    #[must_use]
    pub fn lookup_in(&self, id: &str, entity_kind: u8) -> Option<IdEntry<'a>> {
        let n = self.id_count();
        let mut p = self.id_lower_bound(id);
        while p < n {
            let entry = self.id_entry(p)?;
            if entry.id != id {
                return None;
            }
            if entry.entity_kind == entity_kind {
                return Some(entry);
            }
            p += 1;
        }
        None
    }

    // ------------------------------------------------------------ 实体表
    /// 定长实体表的一行。越界（行号 ≥ `count`，或字节不够）→ `None`。
    #[must_use]
    pub fn row(&self, table: Table, index: u32) -> Option<Row<'a>> {
        let section = self.section(table.section_id())?;
        if index >= section.count {
            return None;
        }
        let stride = table.stride() as usize;
        let start = (index as usize).checked_mul(stride)?;
        let end = start.checked_add(stride)?;
        Some(Row {
            table,
            index,
            data: section.data.get(start..end)?,
        })
    }

    /// 迭代表内所有行（行数取 `count` 与"字节装得下的行数"的较小者）。
    #[must_use]
    pub fn rows(&self, table: Table) -> Rows<'a> {
        let stride = table.stride() as usize;
        match self.section(table.section_id()) {
            Some(section) if stride > 0 => Rows {
                table,
                data: section.data,
                next: 0,
                end: (section.count as usize).min(section.data.len() / stride) as u32,
            },
            _ => Rows {
                table,
                data: &[],
                next: 0,
                end: 0,
            },
        }
    }

    /// 卡牌行（`CARD`，stride 32）。
    #[must_use]
    pub fn card(&self, index: u32) -> Option<CardRow<'a>> {
        CardRow::new(self.row(Table::Card, index)?)
    }

    /// 状态行（`STAT`，stride 40）。
    #[must_use]
    pub fn status(&self, index: u32) -> Option<StatusRow<'a>> {
        StatusRow::new(self.row(Table::Status, index)?)
    }

    /// 敌人动作行（`EACT`，stride 16）。
    #[must_use]
    pub fn enemy_action(&self, index: u32) -> Option<EactRow<'a>> {
        EactRow::new(self.row(Table::EnemyAction, index)?)
    }

    /// 遭遇行（`ENCT`，stride 16）。
    #[must_use]
    pub fn encounter(&self, index: u32) -> Option<EnctRow<'a>> {
        EnctRow::new(self.row(Table::Encounter, index)?)
    }

    /// 一条遭遇的**敌人名单**（`ENCT[index].Enemies`，每条是 id / 生命 / 动作 / 起始状态 / 规则）。
    ///
    /// 这是 `intent::select_action` 那个 `(遭遇, 槽位)` 入参的**内容侧来路**：
    /// 扁平 `EACT` 表只给"动作库"，"哪只敌人按什么顺序用哪些动作"只在 `ENCT` 里。
    ///
    /// 形状不对（`Enemies` 格缺席/为 null、指到的 term 不是 `_arr`、列表越界）⇒
    /// `Err(EncounterError)`，**绝不**静默返回一个空名单 —— 空名单在下游会变成
    /// "这只敌人这一回合什么都不做"，而那种错误看起来完全正常。
    pub fn encounter_enemies(&self, index: u32) -> Result<EncounterEnemies<'_>, EncounterError> {
        let row = self
            .encounter(index)
            .ok_or(EncounterError::NoSuchEncounter(index))?;
        // `EnctRow` 的格号来自 schema，但**类别**还是核一遍：镜像被改坏时格号仍在、
        // 类别可以变，而按错的类别硬读会给出一个像模像样的越界值。
        let cell = row
            .row()
            .cell_index("Enemies")
            .ok_or(EncounterError::MissingField("Enemies"))?;
        if row.row().cell_kind(cell) != Some(F_TERM) {
            return Err(EncounterError::WrongFieldKind("Enemies"));
        }
        let array = match row.enemies() {
            ABSENT16 | NULL16 => return Err(EncounterError::MissingEnemies),
            id => id,
        };
        let term = self
            .term(array)
            .ok_or(EncounterError::NotAnArray(array))?;
        if term.op != OP_ARR {
            return Err(EncounterError::NotAnArray(array));
        }
        let start = term
            .slot(0)
            .ok_or(EncounterError::MalformedList("Enemies"))?;
        let count = term
            .slot(1)
            .ok_or(EncounterError::MalformedList("Enemies"))?;
        if count == LIST_ABSENT || count == LIST_NULL {
            // `_arr` 的两个槽是 `(AUX 起址, 个数)`；个数是哨兵 ⇒ 列表根本不存在。
            // 本内容 109/109 条遭遇都有敌人，所以这里响亮失败。
            return Err(EncounterError::MissingEnemies);
        }
        let end = usize::from(start)
            .checked_add(usize::from(count))
            .ok_or(EncounterError::MalformedList("Enemies"))?;
        if end > self.aux_cells() {
            return Err(EncounterError::MalformedList("Enemies"));
        }
        Ok(EncounterEnemies {
            content: self,
            encounter: index,
            start,
            count,
        })
    }

    /// 遗物行（`REL`，stride 12）。
    #[must_use]
    pub fn relic(&self, index: u32) -> Option<RelRow<'a>> {
        RelRow::new(self.row(Table::Relic, index)?)
    }

    /// 某表第 `index` 行的 `Id` 格（每张表的第 0 格都是 `F_STR` 的 `Id`）解出来的串。
    #[must_use]
    pub fn entity_id(&self, table: Table, index: u32) -> Option<&'a str> {
        self.string(self.row(table, index)?.cell(0)?)
    }

    /// id → 行（只对五张定长表有意义；`map_node`/`event`/`shop`/`character` 没有表，返回 `None`）。
    #[must_use]
    pub fn resolve(&self, id: &str) -> Option<Row<'a>> {
        let entry = self.lookup(id)?;
        self.row(Table::from_entity_kind(entry.entity_kind)?, entry.index as u32)
    }

    // ------------------------------------------------------------ 结构自检
    /// 结构自检：**每段都在镜像内、段间不重叠、`count × stride ≤ bytes`**，
    /// 外加字符串池的自洽性（`STR`/`STRO` 的 `count` 与索引表长度、`STRO` 严格递增、
    /// 每个偏移都指向池内且以 NUL 结尾）。
    ///
    /// 内核在加载镜像时调它；失败即"拒绝加载"。
    pub fn validate(&self) -> Result<(), ValidationError> {
        let total = self.total_size() as u64;
        let n = self.section_count();

        // 1..3：逐段查范围、对齐、count × stride。
        for i in 0..n {
            let section = self.section(i).ok_or(ValidationError::OutOfRange { index: i })?;
            if section.end() > total {
                return Err(ValidationError::OutOfRange { index: i });
            }
            if section.offset % 4 != 0 {
                return Err(ValidationError::Misaligned { index: i });
            }
            let stride = section_stride(i);
            let need = (section.count as u64) * (stride as u64);
            if need > section.bytes as u64 {
                return Err(ValidationError::CountExceedsBytes {
                    index: i,
                    count: section.count,
                    stride,
                    bytes: section.bytes,
                });
            }
        }

        // 4：段间不重叠（空段不占字节，跳过）。
        for a in 0..n {
            let Some(sa) = self.section(a) else { continue };
            if sa.bytes == 0 {
                continue;
            }
            for b in (a + 1)..n {
                let Some(sb) = self.section(b) else { continue };
                if sb.bytes == 0 {
                    continue;
                }
                if (sa.offset as u64) < sb.end() && (sb.offset as u64) < sa.end() {
                    return Err(ValidationError::Overlap { a, b });
                }
            }
        }

        // 5：字符串池。
        let stro = self.section(S_STRO).ok_or(ValidationError::OutOfRange {
            index: S_STRO,
        })?;
        let pool = self.section(S_STR).ok_or(ValidationError::OutOfRange {
            index: S_STR,
        })?;
        let entries = stro.bytes as usize / 4;
        if entries > 0 && (pool.count as usize) != entries - 1 {
            return Err(ValidationError::StringCountMismatch {
                entries,
                str_count: pool.count,
                stro_count: stro.count,
            });
        }
        let mut prev = 0u32;
        for i in 0..entries {
            let off = stro.u32_at(i).ok_or(ValidationError::BadStringIndex {
                entry: i,
            })?;
            if i > 0 && off <= prev {
                return Err(ValidationError::BadStringIndex { entry: i });
            }
            if off as usize > pool.bytes as usize {
                return Err(ValidationError::BadStringIndex { entry: i });
            }
            // 串尾的 NUL（`string()` 会把它当分隔符丢掉，缺了就是半个串）。
            if i > 0 && pool.data.get(off as usize - 1).copied() != Some(0) {
                return Err(ValidationError::BadStringIndex { entry: i });
            }
            prev = off;
        }

        Ok(())
    }
}

/// 段号 → 每元素最小字节数，用来做 `count × stride ≤ bytes` 这一条自检。
///
/// 定长表就是行宽；`STR` 是 blob（按 1 字节算）、`TRM` 的记录是变长的（最短 4 字节：
/// `u16 op` + 补齐），`TAGS` 在真实镜像里是空段所以按 1 字节算。
#[must_use]
pub const fn section_stride(index: usize) -> u32 {
    match index {
        S_STR => 1,
        S_STRO => 4,
        S_OPD => 8,
        S_OPF => 4,
        S_TRM => 4,
        S_TRW => 2,
        S_AUX => 2,
        S_CARD => 32,
        S_STAT => 40,
        S_EACT => 16,
        S_ENCT => 16,
        S_REL => 12,
        S_ROOT => 4,
        S_IDX => 8,
        _ => 1,
    }
}

// ===========================================================================
// 五张定长实体表
// ===========================================================================

/// 卡牌 / 状态 / 敌人动作 / 遭遇 / 遗物。段号与行宽见 `section_id` / `stride`。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Table {
    Card,
    Status,
    EnemyAction,
    Encounter,
    Relic,
    /// The `?` room's content (`EV`, from the document key `UnknownRooms`).
    Event,
    /// Potions (`POT`, from the document key `Potions`).
    Potion,
}

impl Table {
    /// 全部五张表，顺序 = 段号顺序。
    pub const ALL: [Table; 5] = [
        Table::Card,
        Table::Status,
        Table::EnemyAction,
        Table::Encounter,
        Table::Relic,
    ];

    /// 段号（`rdcfmt.S_*`）。
    #[must_use]
    pub const fn section_id(self) -> usize {
        match self {
            Table::Card => S_CARD,
            Table::Status => S_STAT,
            Table::EnemyAction => S_EACT,
            Table::Encounter => S_ENCT,
            Table::Relic => S_REL,
            Table::Event => S_EV,
            Table::Potion => S_POT,
        }
    }

    /// 段名（`manifest.json` 里的 `name`）。
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Table::Card => "CARD",
            Table::Status => "STAT",
            Table::EnemyAction => "EACT",
            Table::Encounter => "ENCT",
            Table::Relic => "REL",
            Table::Event => "EV",
            Table::Potion => "POT",
        }
    }

    /// 行 schema 的键（`rdcfmt.ROW_SCHEMAS` 用的名字；状态表在这里叫 `STATUS`）。
    #[must_use]
    pub const fn schema_name(self) -> &'static str {
        match self {
            Table::Card => "CARD",
            Table::Status => "STATUS",
            Table::EnemyAction => "EACT",
            Table::Encounter => "ENCT",
            Table::Relic => "REL",
            Table::Event => "EV",
            Table::Potion => "POT",
        }
    }

    /// `IDX` 里的实体类别（`EK_*`）。
    #[must_use]
    pub const fn entity_kind(self) -> u8 {
        match self {
            Table::Card => EK_CARD,
            Table::Status => EK_STATUS,
            Table::EnemyAction => EK_EACTION,
            Table::Encounter => EK_ENCOUNTER,
            Table::Relic => EK_RELIC,
            // Events are found through their own list, never through `SEC_IDX` -- which is why
            // `from_entity_kind(EK_EVENT)` stays `None`.
            Table::Event => EK_EVENT,
            Table::Potion => EK_POTION,
        }
    }

    /// 实体类别 → 表（只有 `EK_*` 1..=5 有表）。
    #[must_use]
    pub const fn from_entity_kind(kind: u8) -> Option<Table> {
        match kind {
            EK_CARD => Some(Table::Card),
            EK_STATUS => Some(Table::Status),
            EK_EACTION => Some(Table::EnemyAction),
            EK_ENCOUNTER => Some(Table::Encounter),
            EK_RELIC => Some(Table::Relic),
            _ => None,
        }
    }

    /// 行 schema：`(JSON 键名, 字段类别, 包装 flags)`，顺序即格序。
    #[must_use]
    pub const fn schema(self) -> &'static [CellSpec] {
        match self {
            Table::Card => &CARD_SCHEMA,
            Table::Status => &STATUS_SCHEMA,
            Table::EnemyAction => &EACT_SCHEMA,
            Table::Encounter => &ENCT_SCHEMA,
            Table::Relic => &REL_SCHEMA,
            Table::Event => &EV_SCHEMA,
            Table::Potion => &POT_SCHEMA,
        }
    }

    /// 行内格数（不含 `stride` 末尾的对齐填充）。
    #[must_use]
    pub const fn cells(self) -> usize {
        self.schema().len()
    }

    /// 行宽 = `align4(2 × 格数)`，与 `manifest.json` 的 `stride` 相同。
    #[must_use]
    pub const fn stride(self) -> u32 {
        align4(2 * self.cells() as u32)
    }
}

/// 一个格的 schema 项（写端 `rdcfmt.ROW_SCHEMAS` 的 Rust 版）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CellSpec {
    /// JSON 键名（逐字抄 `rdcfmt.py`）。
    pub name: &'static str,
    /// 字段类别 `F_*`。
    pub kind: u8,
    /// `FLAG_WRAP_LOWER` / `FLAG_WRAP_UPPER`（`F_STR` 与 `F_STRLIST` 才有意义）。
    pub flags: u8,
}

const fn cell(name: &'static str, kind: u8, flags: u8) -> CellSpec {
    CellSpec { name, kind, flags }
}

// ===========================================================================
// 行的借用视图
// ===========================================================================

/// 定长实体表的一行：`stride` 个字节的借用视图。
///
/// **只有 `cells()` 个格是数据**，末尾 `stride - 2×cells` 个字节是对齐填充。
/// 格一律按小端 u16 读，**不解释哨兵**（`ABSENT16`/`NULL16`/`BOOL_*` 原样返回）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Row<'a> {
    table: Table,
    index: u32,
    data: &'a [u8],
}

impl<'a> Row<'a> {
    #[must_use]
    pub fn table(&self) -> Table {
        self.table
    }

    /// 表内行号（0 起）。
    #[must_use]
    pub fn index(&self) -> u32 {
        self.index
    }

    /// 整行原始字节（`stride` 字节，含末尾填充）。
    #[must_use]
    pub fn bytes(&self) -> &'a [u8] {
        self.data
    }

    /// 行内 u16 个数 = `stride / 2`（含末尾那 0/1 个对齐填充格）。
    #[must_use]
    pub fn u16_len(&self) -> usize {
        self.data.len() / 2
    }

    /// 第 `cell` 格（0 起，**只有 `cells()` 个格存在**；末尾的对齐填充不是格）。越界 `None`。
    #[must_use]
    pub fn cell(&self, cell: u32) -> Option<u16> {
        if cell as usize >= self.table.cells() {
            return None;
        }
        u16_at(self.data, (cell as usize).checked_mul(2)?)
    }

    /// schema 里 `name` 落在第几格。
    #[must_use]
    pub fn cell_index(&self, name: &str) -> Option<usize> {
        self.table.schema().iter().position(|c| c.name == name)
    }

    /// 按 schema 的键名取格（不解释哨兵）。
    #[must_use]
    pub fn cell_by_name(&self, name: &str) -> Option<u16> {
        self.cell(self.cell_index(name)? as u32)
    }

    /// 第 `cell` 格的字段类别（`F_*`）；越界 `None`。
    #[must_use]
    pub fn cell_kind(&self, cell: usize) -> Option<u8> {
        self.table.schema().get(cell).map(|c| c.kind)
    }
}

/// 泛型行迭代器（`Content::rows`）。
#[derive(Debug, Clone)]
pub struct Rows<'a> {
    table: Table,
    data: &'a [u8],
    next: u32,
    end: u32,
}

impl<'a> Rows<'a> {
    #[must_use]
    pub fn table(&self) -> Table {
        self.table
    }

    /// 还剩几行。
    #[must_use]
    pub fn remaining(&self) -> u32 {
        self.end.saturating_sub(self.next)
    }
}

impl<'a> Iterator for Rows<'a> {
    type Item = Row<'a>;

    fn next(&mut self) -> Option<Row<'a>> {
        if self.next >= self.end {
            return None;
        }
        let stride = self.table.stride() as usize;
        let start = (self.next as usize).checked_mul(stride)?;
        let end = start.checked_add(stride)?;
        let data = self.data.get(start..end)?;
        let index = self.next;
        self.next += 1;
        Some(Row {
            table: self.table,
            index,
            data,
        })
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let n = self.remaining() as usize;
        (n, Some(n))
    }
}

impl<'a> ExactSizeIterator for Rows<'a> {}

/// 生成一张表的行视图类型：`new` 收窄、`row()` 拿回通用视图、命名 getter 取格。
macro_rules! entity_row {
    (
        $(#[$meta:meta])*
        $name:ident, $table:ident, $schema:ident, $stride:expr, $cells:expr,
        { $( $(#[$cell_meta:meta])* ($cell_name:literal, $cell_kind:expr, $cell_flag:expr)
             => $getter:ident => $cell:expr, )* }
    ) => {
        /// 这张表的格表：**名字 + 类别 + 包装标志 + 格号**。
        ///
        /// 与下面那些 getter 出自**同一份列表** —— 加一格只改一处。以前这里和 getter 各有一份，
        /// 加 `CARD.Rarity` 时只改了一份，两条"格表不许漂"的守卫立刻报红。
        pub static $schema: [CellSpec; $cells] =
            [ $( cell($cell_name, $cell_kind, $cell_flag) ),* ];

        // `$cells` 还是手写的，所以钉住它和列表长度一致。
        const _: () = assert!([ $( $cell ),* ].len() == $cells);

        $(#[$meta])*
        #[derive(Debug, Clone, Copy, PartialEq, Eq)]
        pub struct $name<'a> {
            row: Row<'a>,
        }

        impl<'a> $name<'a> {
            /// 这张表。
            pub const TABLE: Table = Table::$table;
            /// 行宽（字节，= `manifest.json` 的 `stride`）。
            pub const STRIDE: u32 = $stride;
            /// 行内格数（不含末尾填充）。
            pub const CELLS: usize = $cells;

            /// 收窄成这一行；表不对返回 `None`。
            #[must_use]
            pub fn new(row: Row<'a>) -> Option<Self> {
                if row.table() == Self::TABLE {
                    Some(Self { row })
                } else {
                    None
                }
            }

            /// 底下的通用行视图。
            #[must_use]
            pub fn row(&self) -> Row<'a> {
                self.row
            }

            /// 行号（0 起）。
            #[must_use]
            pub fn index(&self) -> u32 {
                self.row.index()
            }

            $(
                $(#[$cell_meta])*
                #[must_use]
                pub fn $getter(&self) -> u16 {
                    // 格号是本文件里的常量且 < CELLS，所以兜底值永远用不上。
                    self.row.cell($cell).unwrap_or(ABSENT16)
                }
            )*
        }

        impl<'a> From<$name<'a>> for Row<'a> {
            fn from(value: $name<'a>) -> Row<'a> {
                value.row
            }
        }
    };
}

entity_row!(
    /// 卡牌行（`CARD`，stride 32，15 格）。
    ///
    /// 格序 = `CARD_SCHEMA`，与 `rdcfmt.CARD_ROW` 逐项一致。
    CardRow, Card, CARD_SCHEMA, 32, 16, {
        /// `Id`（串号）。
        ("Id", F_STR, 0) => id => 0,
        /// `Program`（term 句柄）。
        ("Program", F_TERM, 0) => program => 1,
        /// `Tags`（term 句柄）。
        ("Tags", F_TERM, 0) => tags => 2,
        /// `Costs`（term 句柄）。
        ("Costs", F_TERM, 0) => costs => 3,
        /// `LifecyclePrograms`（term 句柄）。
        ("LifecyclePrograms", F_TERM, 0) => lifecycle_programs => 4,
        /// `PlayCondition`（term 句柄）。
        ("PlayCondition", F_TERM, 0) => play_condition => 5,
        /// `QueueOnPlay`（term 句柄）。
        ("QueueOnPlay", F_TERM, 0) => queue_on_play => 6,
        /// `RetainInHandOnTurnEnd`（`F_BOOL` 格：0=absent 1=false 2=true 3=null）。
        ("RetainInHandOnTurnEnd", F_BOOL, 0) => retain_in_hand_on_turn_end => 7,
        /// `IsAction`（`F_BOOL` 格）。
        ("IsAction", F_BOOL, 0) => is_action => 8,
        /// `NameKey`（串号）。
        ("NameKey", F_STR, 0) => name_key => 9,
        /// `DescriptionKey`（串号）。
        ("DescriptionKey", F_STR, 0) => description_key => 10,
        /// `PackageId`（串号）。
        ("PackageId", F_STR, 0) => package_id => 11,
        /// `TurnEndHandDestinationZone`（串号）。
        ("TurnEndHandDestinationZone", F_STR, 0) => turn_end_hand_destination_zone => 12,
        /// `PlayedCardDestinationZone`（串号）。
        ("PlayedCardDestinationZone", F_STR, 0) => played_card_destination_zone => 13,
        /// `Rarity`（串号）：`Basic` / `Common` / `Uncommon` / `Rare` / `Status` / `Curse`。
        ///
        /// 加这一格**没有改动 stride**（`align4(2×15) = align4(2×16) = 32`），但它改了 schema，
        /// 所以 `FORMAT_VERSION` 一起从 1 变成 2。
        ("Rarity", F_STR, 0) => rarity => 14,
        /// schema 不认识的键（`_obj` term 句柄；NULL16 = 没有）。
        ("extra", F_TERM, 0) => extra => 15,
    }
);

entity_row!(
    /// 状态行（`STAT`，stride 40，20 格）。
    StatusRow, Status, STATUS_SCHEMA, 40, 20, {
        /// `Id`（串号）。
        ("Id", F_STR, 0) => id => 0,
        /// `NameKey`（串号）。
        ("NameKey", F_STR, 0) => name_key => 1,
        /// `DescriptionKey`（串号）。
        ("DescriptionKey", F_STR, 0) => description_key => 2,
        /// `PackageId`（串号）。
        ("PackageId", F_STR, 0) => package_id => 3,
        /// `Polarity`（串号）。
        ("Polarity", F_STR, 0) => polarity => 4,
        /// `StackingBehavior`（串号）。
        ("StackingBehavior", F_STR, 0) => stacking_behavior => 5,
        /// `Tags`（term 句柄）。
        ("Tags", F_TERM, 0) => tags => 6,
        /// `Triggers`（term 句柄）。
        ("Triggers", F_TERM, 0) => triggers => 7,
        /// `PassiveModifiers`（term 句柄）。
        ("PassiveModifiers", F_TERM, 0) => passive_modifiers => 8,
        /// `CombatRules`（term 句柄）。
        ("CombatRules", F_TERM, 0) => combat_rules => 9,
        /// `DeathPrevention`（term 句柄）。
        ("DeathPrevention", F_TERM, 0) => death_prevention => 10,
        /// `DebuffBlock`（term 句柄）。
        ("DebuffBlock", F_TERM, 0) => debuff_block => 11,
        /// `IncomingStatusDelay`（term 句柄）。
        ("IncomingStatusDelay", F_TERM, 0) => incoming_status_delay => 12,
        /// `Disclosure`（term 句柄）。
        ("Disclosure", F_TERM, 0) => disclosure => 13,
        /// `Prevention`（term 句柄）。
        ("Prevention", F_TERM, 0) => prevention => 14,
        /// `Amplification`（term 句柄）。
        ("Amplification", F_TERM, 0) => amplification => 15,
        /// `UsesStacks`（`F_BOOL` 格）。
        ("UsesStacks", F_BOOL, 0) => uses_stacks => 16,
        /// `UsesDuration`（`F_BOOL` 格）。
        ("UsesDuration", F_BOOL, 0) => uses_duration => 17,
        /// `UsesCharges`（`F_BOOL` 格）。
        ("UsesCharges", F_BOOL, 0) => uses_charges => 18,
        /// schema 不认识的键（term 句柄）。
        ("extra", F_TERM, 0) => extra => 19,
    }
);

entity_row!(
    /// 敌人动作行（`EACT`，stride 16，7 格）。
    EactRow, EnemyAction, EACT_SCHEMA, 16, 7, {
        /// `Id`（串号）。
        ("Id", F_STR, 0) => id => 0,
        /// `NameKey`（串号）。
        ("NameKey", F_STR, 0) => name_key => 1,
        /// `DescriptionKey`（串号）。
        ("DescriptionKey", F_STR, 0) => description_key => 2,
        /// `PackageId`（串号）。
        ("PackageId", F_STR, 0) => package_id => 3,
        /// `Intent`（term 句柄）。
        ("Intent", F_TERM, 0) => intent => 4,
        /// `Program`（term 句柄）。
        ("Program", F_TERM, 0) => program => 5,
        /// schema 不认识的键（term 句柄）。
        ("extra", F_TERM, 0) => extra => 6,
    }
);

entity_row!(
    /// 遭遇行（`ENCT`，stride 16，8 格）。`Id` 的包装拼法是大写 `{"Value": s}`。
    EnctRow, Encounter, ENCT_SCHEMA, 16, 8, {
        /// `Id`（串号；JSON 里写成 `{"Value": s}`）。
        ("Id", F_STR, FLAG_WRAP_UPPER) => id => 0,
        /// `Enemies`（term 句柄）。
        ("Enemies", F_TERM, 0) => enemies => 1,
        /// `HeroResources`（term 句柄）。
        ("HeroResources", F_TERM, 0) => hero_resources => 2,
        /// `HeroStartingStatuses`（term 句柄）。
        ("HeroStartingStatuses", F_TERM, 0) => hero_starting_statuses => 3,
        /// `TriggeredEffects`（term 句柄）。
        ("TriggeredEffects", F_TERM, 0) => triggered_effects => 4,
        /// `HeroDisplayName`（串号）。
        ("HeroDisplayName", F_STR, 0) => hero_display_name => 5,
        /// `CardsDrawnPerTurn`（`F_INT` 格；`NULL_INT` 表示"存在且为 null"）。
        ("CardsDrawnPerTurn", F_INT, 0) => cards_drawn_per_turn => 6,
        /// schema 不认识的键（term 句柄）。
        ("extra", F_TERM, 0) => extra => 7,
    }
);

entity_row!(
    /// 药水行（`POT`，stride 16，7 格）。
    ///
    /// `Effect` 是**闭词表**（`combat_damage` / `combat_block` / `combat_energy` / `heal`）：run 层
    /// 没有节目解释器，遇到词表外的效果必须响亮拒绝。
    PotRow, Potion, POT_SCHEMA, 16, 7, {
        ("Id", F_STR, 0) => id => 0,
        ("NameKey", F_STR, 0) => name_key => 1,
        ("DescriptionKey", F_STR, 0) => description_key => 2,
        ("Effect", F_STR, 0) => effect => 3,
        ("Amount", F_INT, 0) => amount => 4,
        ("Rarity", F_STR, 0) => rarity => 5,
        ("extra", F_TERM, 0) => extra => 6,
    }
);

entity_row!(
    /// `?` 房事件行（`EV`，stride 20，10 格）。
    EvRow, Event, EV_SCHEMA, 20, 10, {
        ("Id", F_STR, 0) => id => 0,
        ("NameKey", F_STR, 0) => name_key => 1,
        ("DescriptionKey", F_STR, 0) => description_key => 2,
        ("Label0", F_STR, 0) => label0 => 3,
        ("Effect0", F_STR, 0) => effect0 => 4,
        ("Amount0", F_INT, 0) => amount0 => 5,
        ("Label1", F_STR, 0) => label1 => 6,
        ("Effect1", F_STR, 0) => effect1 => 7,
        ("Amount1", F_INT, 0) => amount1 => 8,
        ("extra", F_TERM, 0) => extra => 9,
    }
);

entity_row!(
    /// 遗物行（`REL`，stride 12，5 格）。
    RelRow, Relic, REL_SCHEMA, 12, 6, {
        /// `Id`（串号）。
        ("Id", F_STR, 0) => id => 0,
        /// `DisplayName`（串号）。
        ("DisplayName", F_STR, 0) => display_name => 1,
        /// `RunPrograms`（term 句柄）。
        ("RunPrograms", F_TERM, 0) => run_programs => 2,
        /// `CombatRules`（term 句柄）。
        ("CombatRules", F_TERM, 0) => combat_rules => 3,
        /// `Rarity`（§156：`Common` / `Uncommon` / `Rare`）。
        ("Rarity", F_STR, 0) => rarity => 4,
        /// schema 不认识的键（term 句柄）。
        ("extra", F_TERM, 0) => extra => 5,
    }
);

// ===========================================================================
// 遭遇里的敌人记录（`ENCT[i].Enemies[j]`）
// ===========================================================================
//
// **形状是量出来的，不是从 JSON 抄的**（`reader.py` 的 dump + 真实镜像互相印证；
// `intent.rs` 也独立量过同一件事）。照 JSON 视图写会静默读错三处：
//
// | 位置 | JSON 视图 | 二进制真实形状 |
// |---|---|---|
// | `ENCT.Enemies` 格 | `F_TERM` | 格是 `F_TERM`，但**指向的 term 是 `_arr`（op 4）**，它唯一的字段是 `F_TERMLIST` ⇒ 两个槽是 `(AUX 起址, 个数)`，每个 `AUX` 格是 **term id** |
// | enemy record 的 `Actions` | "term 列表，元素是 `{"value": id}`" | **`F_STRLIST` + `FLAG_WRAP_LOWER`** ⇒ `AUX` 里装的是**串号**，一个 `_wrap_lower` term 都没有 |
// | enemy record 的 `IntentRules` / `StartingStatuses` | term 列表 | `F_TERMLIST` ⇒ `AUX` 里装的是 **term id** |
//
// enemy record 是 op **91** 的普通对象，6 个键恒存在（149/149）：
// `Actions`(`F_STRLIST`) / `Id`(`F_STR`) / `IntentRules`(`F_TERMLIST`) / `MaxHealth`(`F_INT`) /
// `Position`(`F_TERM`，149/149 是 `NULL16`) / `StartingStatuses`(`F_TERMLIST`)。
// **没有** `DisplayName`。
//
// 实测分布（core 镜像，109 条遭遇 / 149 条敌人记录 / 480 条动作）：
// 每遭遇敌人数 `{1:76, 2:26, 3:7}`；每敌人动作数 `{1:1, 2:9, 3:107, 4:20, 5:12}`；
// **3** 条记录带 `IntentRules`（`a_very_official_line` / `contradictory_signpost` /
// `minute_moth`）、**20** 条记录带 `StartingStatuses`。这些数由
// `every_encounter_enemy_record_reads` 逐条钉住（多一条少一条都红）。

/// 读一条遭遇的敌人记录时可能的失败。
///
/// **每一种都是"内容形态变了/我读错了"**，不是"这条遭遇恰好没有敌人"：
/// 后者在驱动层会被当成"这回合它不做任何事"，而那正是本项目最恨的静默。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EncounterError {
    /// `ENCT` 行号越界（本内容 109 条）。
    NoSuchEncounter(u32),
    /// `Enemies` 下标越界。
    NoSuchEnemy {
        /// 遭遇行号。
        encounter: u32,
        /// `Enemies` 列表下标。
        index: u16,
    },
    /// `Enemies` 格缺席 / 为 null / 列表的个数是哨兵 —— **不是**"这条遭遇没有敌人"。
    MissingEnemies,
    /// `Enemies` 指到的 term 不是 `_arr`（换成 `_wrap_lower` 之类就是形态变了）。
    NotAnArray(u16),
    /// 敌人记录 / 规则记录不是对象（`op < 16` 的标量 term）。
    NotAnObject(u16),
    /// 字段表里没有这个键，或字段表本身读不出来。
    MissingField(&'static str),
    /// 字段类别不是期望的那一种（例如 `Actions` 不是 `F_STRLIST`）。
    WrongFieldKind(&'static str),
    /// 列表的 `(起址, 个数)` 落在 `AUX` 之外（会退化成静默的 `None`）。
    MalformedList(&'static str),
    /// 串号解不出串。
    BadString(u16),
}

/// 一段槽列表（`F_TERMLIST` 或 `F_STRLIST`）的借用视图：`(AUX 起址, 个数)`。
///
/// ⚠️ **两种 kind 的格含义不同**：`F_STRLIST` 的格是**串号**（用 [`Self::string`]），
/// `F_TERMLIST` 的格是 **term id**（用 [`Self::term`]）。本视图不替调用方猜 —— 两个入口
/// 都给，[`Self::kind`] 说明这一段是哪种。
#[derive(Debug, Clone, Copy)]
pub struct SlotList<'a> {
    content: &'a Content<'a>,
    start: u16,
    count: u16,
    kind: u8,
}

impl<'a> SlotList<'a> {
    /// 项数。
    #[must_use]
    pub const fn len(&self) -> usize {
        self.count as usize
    }

    /// 是不是空的。
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.count == 0
    }

    /// 这一段是哪种列表（`F_TERMLIST` / `F_STRLIST`）。
    #[must_use]
    pub const fn kind(&self) -> u8 {
        self.kind
    }

    /// 第 `index` 格的原始值（**不解释含义**）。越界 `None`。
    #[must_use]
    pub fn cell(&self, index: usize) -> Option<u16> {
        if index >= self.len() {
            return None;
        }
        let offset = usize::from(self.start).checked_add(index)?;
        let offset = u16::try_from(offset).ok()?;
        self.content.aux(offset)
    }

    /// `F_STRLIST` 的第 `index` 项，解成 `&str`。串号坏了 ⇒ `None`（不编一个空串出来）。
    #[must_use]
    pub fn string(&self, index: usize) -> Option<&'a str> {
        self.content.string(self.cell(index)?)
    }

    /// `F_TERMLIST` 的第 `index` 项（term id）。
    #[must_use]
    pub fn term(&self, index: usize) -> Option<u16> {
        self.cell(index)
    }
}

/// `ENCT` 里一个敌人记录（`ENCT[i].Enemies[j]`）的借用视图。
#[derive(Debug, Clone, Copy)]
pub struct EnemySpec<'a> {
    content: &'a Content<'a>,
    term: u16,
}

impl<'a> EnemySpec<'a> {
    /// 这个记录的 term id（要交给 `ir::NodeRef::new` 时用）。
    #[must_use]
    pub const fn term(&self) -> u16 {
        self.term
    }

    /// `Id`（`F_STR`）。**这就是回合序/查表用的那个 id**，缺席 ⇒ `MissingField`。
    pub fn id(&self) -> Result<&'a str, EncounterError> {
        let (kind, at) = self.field_at("Id")?;
        if kind != F_STR {
            return Err(EncounterError::WrongFieldKind("Id"));
        }
        match self.slot(at)? {
            ABSENT16 | NULL16 => Err(EncounterError::MissingField("Id")),
            index => self.content.string(index).ok_or(EncounterError::BadString(index)),
        }
    }

    /// `MaxHealth`（`F_INT`，槽是 **i16**）。缺席 / 为 null ⇒ `Ok(None)`。
    ///
    /// ⚠️ `raw as i32` 会把 `-1` 读成 65535（`content-binary-format.md` 的实测结论）。
    pub fn max_health(&self) -> Result<Option<i32>, EncounterError> {
        let (kind, at) = self.field_at("MaxHealth")?;
        if kind != F_INT {
            return Err(EncounterError::WrongFieldKind("MaxHealth"));
        }
        match self.slot(at)? {
            ABSENT_INT | NULL_INT => Ok(None),
            raw => Ok(Some(i32::from(raw as i16))),
        }
    }

    /// `Actions`（**`F_STRLIST`**）：动作 id 列表。元素是**串号**，用 [`SlotList::string`] 解。
    ///
    /// 列表顺序就是循环分支的取用顺序（`Actions[(round - 1) % count]`）。
    pub fn actions(&self) -> Result<SlotList<'a>, EncounterError> {
        self.list("Actions", F_STRLIST)
    }

    /// `IntentRules`（`F_TERMLIST`）：规则记录（op 90，键 `Action`/`Condition`/`Priority`）。
    pub fn intent_rules(&self) -> Result<SlotList<'a>, EncounterError> {
        self.list("IntentRules", F_TERMLIST)
    }

    /// `StartingStatuses`（`F_TERMLIST`）：起始状态的 spec 对象
    /// （键 `Stacks` / `DurationTurns` / `Charges` / `Status`）。
    pub fn starting_statuses(&self) -> Result<SlotList<'a>, EncounterError> {
        self.list("StartingStatuses", F_TERMLIST)
    }

    /// 这个记录的 term（opcode 的字段表决定了"键 → 槽"的映射）。
    fn record(&self) -> Result<Term<'a>, EncounterError> {
        let term = self
            .content
            .term(self.term)
            .ok_or(EncounterError::NotAnObject(self.term))?;
        if term.op < OP_FIRST_DYNAMIC {
            return Err(EncounterError::NotAnObject(term.op));
        }
        Ok(term)
    }

    /// 一个键的 `(字段类别, 首槽下标)`。
    ///
    /// 槽位是**按字段表顺序累加**出来的（`content-binary-format.md` §5）：没有名字索引表。
    fn field_at(&self, key: &'static str) -> Result<(u8, usize), EncounterError> {
        let term = self.record()?;
        let opcode = self
            .content
            .opcode(term.op)
            .ok_or(EncounterError::NotAnObject(term.op))?;
        let mut at = 0usize;
        for index in 0..opcode.nfields() {
            let field = opcode.field(index).ok_or(EncounterError::MissingField(key))?;
            let width = usize::from(
                field
                    .slots()
                    .ok_or(EncounterError::WrongFieldKind(key))?,
            );
            let name = self
                .content
                .string(field.name_str())
                .ok_or(EncounterError::MissingField(key))?;
            if name == key {
                return Ok((field.kind(), at));
            }
            at = at.checked_add(width).ok_or(EncounterError::MissingField(key))?;
        }
        Err(EncounterError::MissingField(key))
    }

    /// 一个字段的原始槽值（越界 ⇒ `MissingField`）。
    fn slot(&self, at: usize) -> Result<u16, EncounterError> {
        self.record()?
            .slot(at)
            .ok_or(EncounterError::MissingField("slot"))
    }

    /// 一个列表字段 → [`SlotList`]。
    ///
    /// ⚠️ **空列表在这份镜像里的拼法是"个数 = 哨兵"**（`LIST_ABSENT` / `LIST_NULL`），
    /// **不是** `count == 0`：实测 149 条敌人记录里 146 条 `IntentRules` 用的是哨兵，
    /// 只有 3 条真的带规则。所以哨兵 ⇒ **空列表**，两种拼法都收（`ir.rs:364-394` 的
    /// `list_field` 同一条读法）。把哨兵当"形态坏了"会当场拒掉 146 条合法记录 ——
    /// 这一点是被 `every_encounter_enemy_record_reads` 的 149 条逐条读抓出来的。
    fn list(&self, key: &'static str, want: u8) -> Result<SlotList<'a>, EncounterError> {
        let (kind, at) = self.field_at(key)?;
        if kind != want {
            return Err(EncounterError::WrongFieldKind(key));
        }
        let term = self.record()?;
        let start = term.slot(at).ok_or(EncounterError::MalformedList(key))?;
        let count = term
            .slot(at.checked_add(1).ok_or(EncounterError::MalformedList(key))?)
            .ok_or(EncounterError::MalformedList(key))?;
        let count = if count == LIST_ABSENT || count == LIST_NULL {
            0
        } else {
            count
        };
        // 每一格都真的在 `AUX` 里：否则 `SlotList::cell` 会静默给 `None`。
        // 空列表**不查**：个数是哨兵时起址槽是垃圾值（实测 146 条 `IntentRules`
        // 就是这么存的），拿它去比 `AUX` 长度等于用一个没人会读的槽判失败。
        if count > 0 {
            let end = usize::from(start)
                .checked_add(usize::from(count))
                .ok_or(EncounterError::MalformedList(key))?;
            if end > self.content.aux_cells() {
                return Err(EncounterError::MalformedList(key));
            }
        }
        Ok(SlotList {
            content: self.content,
            start,
            count,
            kind,
        })
    }
}

/// 一条遭遇的敌人名单（`ENCT[index].Enemies`）。
///
/// **列表顺序 = 上场序 = 回合序**（`Encounters.cs:211-220` 按 `foreach (var spec in
/// encounter.Enemies)` 追加；`ScenarioCombatFactory.cs:19-24` 再按 `[Hero, Allies…, Enemies…]`
/// 建回合序）。所以 `intent::select_action` 的 `EnemySlot.index` 与这里的下标是同一个东西。
#[derive(Debug, Clone, Copy)]
pub struct EncounterEnemies<'a> {
    content: &'a Content<'a>,
    encounter: u32,
    start: u16,
    count: u16,
}

impl<'a> EncounterEnemies<'a> {
    /// 这是第几行 `ENCT`。
    #[must_use]
    pub const fn encounter(&self) -> u32 {
        self.encounter
    }

    /// 敌人个数。
    #[must_use]
    pub const fn len(&self) -> usize {
        self.count as usize
    }

    /// 有没有敌人。
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.count == 0
    }

    /// 第 `index` 个敌人记录。越界 ⇒ `NoSuchEnemy`（不是 `None`，也不是空记录）。
    pub fn get(&self, index: usize) -> Result<EnemySpec<'a>, EncounterError> {
        let index = u16::try_from(index).map_err(|_| EncounterError::NoSuchEnemy {
            encounter: self.encounter,
            index: u16::MAX,
        })?;
        if index >= self.count {
            return Err(EncounterError::NoSuchEnemy {
                encounter: self.encounter,
                index,
            });
        }
        let offset = usize::from(self.start)
            .checked_add(usize::from(index))
            .ok_or(EncounterError::MalformedList("Enemies"))?;
        let offset = u16::try_from(offset).map_err(|_| EncounterError::MalformedList("Enemies"))?;
        let term = self
            .content
            .aux(offset)
            .ok_or(EncounterError::MalformedList("Enemies"))?;
        Ok(EnemySpec {
            content: self.content,
            term,
        })
    }

    /// 逐个敌人记录（每一项都是 `Result`：坏掉的那一条**不会**被跳过）。
    #[must_use]
    pub fn iter(&self) -> EncounterEnemiesIter<'a> {
        EncounterEnemiesIter {
            list: *self,
            next: 0,
        }
    }
}

/// [`EncounterEnemies::iter`] 的迭代器。
#[derive(Debug, Clone)]
pub struct EncounterEnemiesIter<'a> {
    list: EncounterEnemies<'a>,
    next: usize,
}

impl<'a> Iterator for EncounterEnemiesIter<'a> {
    type Item = Result<EnemySpec<'a>, EncounterError>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.next >= self.list.len() {
            return None;
        }
        let index = self.next;
        self.next += 1;
        Some(self.list.get(index))
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let left = self.list.len().saturating_sub(self.next);
        (left, Some(left))
    }
}

impl<'a> ExactSizeIterator for EncounterEnemiesIter<'a> {}

// ===========================================================================
// 起始牌组（三份副本：`Characters[i].Start.Deck` / `Start.Deck` / 根 `Deck`）
// ===========================================================================
//
// WHY THIS ACCESSOR EXISTS
// ------------------------
// 内容文档里有**三处**写着起始牌组，而且它们互相是 gated 的（`native/sts_content_check.py`
// 的 `check_relations` 逐条比对）。参考实现只读其中一处，另外两处是回退：
//
// | # | 位置 | 什么时候读 | 参考出处 |
// |---|---|---|---|
// | 1 | `Characters[0].Start.Deck` | 花名册非空（**选中角色自己的牌组**） | `RunBlueprint.cs:167-176`（`ResolveStart` 有花名册时返回 `Characters[0].Start`）、`RunSetup.cs:44`（`start.Deck.Count > 0 ? start.Deck : blueprint.Deck`） |
// | 2 | `Start.Deck` | 花名册**为空**（老式单人蓝图） | `RunBlueprint.cs:169-170`（`if (Characters.Count == 0) return Start;`）+ 同一条 `:44` |
// | 3 | 根 `Deck` | 1/2 的牌组**为空**（"声明了没有"） | `RunSetup.cs:44` 的 `: blueprint.Deck` 分支 |
//
// 三条都验证过（`git grep` 于钉死的 commit `fd43e68`）。`RunStart.Deck` 的文档注释把这条
// 规则写成了散文（`RunBlueprint.cs:214-216`：*"Empty (the default) ⇒ fall back to the
// blueprint's shared Deck … A character roster gives each character its own deck here; that
// is what makes character selection meaningful."*），所以"空 = 没声明"是**参考自己的约定**，
// 不是我发明的哨兵。
//
// WHY THE ROOT-KEY NAMES ARE *NOT* HERE
// -------------------------------------
// 三处候选的根键名由调用方按名字查好后用 [`DeckRoots`] 传进来。原因不是洁癖：
// `native/sts_content_check.py` 第 4 层（INERT）判定"内核读了这个根键"的**唯一**证据是
// 内核规则代码里出现 `root_by_name("<Key>")`，而 `content.rs` 被那条闸门**排除**在扫描之外
// （它自己就是那一堆 `root_by_name` 的实现）。把名字写在这里 ⇒ 闸门永远看不见消费者 ⇒
// 清单里"内核零消费者"那几条会一直是**假话**。
//
// MEASURED SHAPES（两份镜像实测，2026-10-19；⚠️ 三份**值相等、形态不等**）
// ----------------------------------------------------------------
// | 拼法 | 形态 | 实测 |
// |---|---|---|
// | 根 `Deck` | `F_TERMLIST`（元素是 **`_wrap_lower`，op 6**，1 槽 = 串号） | sts `[75, 10]`、roguedeck `[1521, 10]`；元素 term 的 op 全是 6 |
// | `Start.Deck` | `F_STRLIST`（元素**直接是串号**） | sts `[64, 10]`、roguedeck `[1510, 10]` |
// | `Characters[0].Start.Deck` | **同一个 term**（`Characters[0].Start` 指向的 term id == 根 `Start` 的 term id：sts 140/140、roguedeck 1440/1440） | 两份镜像都如此 |
//
// 所以"等价"只在**值**上成立：三份都是 `strike×5, defend×4, bash×1`（sts）/
// `paper_cut×4, cower_behind_a_desk×4, strong_binder, permit_a38`（roguedeck）。
// 形态不同意味着**读法必须不同** —— 把 `Start.Deck` 当 `F_TERMLIST` 读会得到一个非法的
// term id，把根 `Deck` 当 `F_STRLIST` 读会拿到一堆串号恰好落不进串池的整数。所以
// [`StartDeck`] 记着自己是哪种拼法（[`StartDeck::origin`]）并按那一份的形态解。

/// 起始牌组读的是**哪一份副本**（见本节头部的三行表）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeckOrigin {
    /// `Characters[0].Start.Deck` —— 花名册非空时的**优先**项。
    CharacterStart,
    /// 根键 `Start.Deck` —— 只在花名册为空时看它（`RunBlueprint.cs:169-170`）。
    RootStart,
    /// 根键 `Deck` —— 参考的 `blueprint.Deck` 回退（`RunSetup.cs:44`）。
    RootDeck,
}

impl DeckOrigin {
    /// 这份副本在源文档里的位置（报告/断言里用，别在这里第二份维护"哪一份优先"）。
    #[must_use]
    pub const fn path(self) -> &'static str {
        match self {
            Self::CharacterStart => "Characters[0].Start.Deck",
            Self::RootStart => "Start.Deck",
            Self::RootDeck => "Deck",
        }
    }
}

/// 三个候选根键的 term id（`None` = 镜像里**没有**这个根键）。
///
/// 名字由调用方（`battle.rs`）用 `root_by_name("…")` 查 —— 理由见本节头部
/// "WHY THE ROOT-KEY NAMES ARE *NOT* HERE"。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeckRoots {
    /// 根键 `Characters`（`F_TERMLIST`：花名册）。
    pub characters: Option<u16>,
    /// 根键 `Start`（对象：`Deck` / `HeroName` / `MaxHealth` / …）。
    pub start: Option<u16>,
    /// 根键 `Deck`（`F_TERMLIST`：蓝图共享牌组）。
    pub deck: Option<u16>,
}

/// 读起始牌组时可能的失败。
///
/// **每一种都是"内容形态变了 / 我读错了"**，不是"这个角色没有起始牌组"：后者参考有明确的
/// 写法（空列表 ⇒ 回退），在本类型里表现为"接着看下一处候选"。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeckError {
    /// 三处候选**一个都没出现**（镜像里既没有 `Characters`/`Start`，也没有 `Deck` 根键）。
    ///
    /// 不是"空牌组"：空牌组要 [自己长这样](Self::EmptyDeck)。
    NoDeckKey,
    /// 三处候选都在，但**全解析成空**。参考允许（`Array.Empty<CardDefinitionId>()`），
    /// 但那意味着这一局一张牌都没有 —— 对"从内容建一局"来说这是内容缺陷，所以响亮。
    EmptyDeck,
    /// 某一跳的结构读不出来（不是对象 / 字段缺 / 字段类别不对 / 列表越界）。
    ///
    /// 带的是**那一跳的名字**（`"Characters"` / `"Characters[0].Start"` / `"Start"` /
    /// `"Deck"`），因为"内容坏了"这条消息一旦不说坏在哪，人就得从头挖一遍。
    Malformed(&'static str),
    /// 槽里的串号解不出串（串池被改坏）。
    BadString(u16),
}

/// 角色起始的三个数值（`Characters[0].Start`，见
/// [`Content::character_start_facts`]）。
///
/// 刻意**只有一个结构体、三个标量**：它存在的唯一目的是让 run 层不必认识内容格式，
/// 而不是充当"内容里所有起始字段的镜像"。每多一格就多一处会和内容漂移的地方。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CharacterStart {
    /// `Start.MaxHealth`。
    pub max_health: i32,
    /// `Start.StartingHealth`，缺席时等于 `max_health`。
    pub starting_health: i32,
    /// `Start.Resources.gold`，缺席时为 0。
    pub gold: i32,
}

/// 一份起始牌组的借用视图（已按各自形态归一成"第 i 张牌的定义 id"）。
#[derive(Debug, Clone, Copy)]
pub struct StartDeck<'a> {
    content: &'a Content<'a>,
    origin: DeckOrigin,
    list: SlotList<'a>,
    /// `true` ⇒ 元素是 `_obj(value: F_STR)` 的 **term id**（根 `Deck` 的形态）；
    /// `false` ⇒ 元素**直接是串号**（`Start.Deck` 的形态）。见本节头部的形态表。
    wrapped: bool,
}

impl<'a> StartDeck<'a> {
    /// 这份牌组来自哪一处副本（[`DeckOrigin`]）。
    #[must_use]
    pub const fn origin(&self) -> DeckOrigin {
        self.origin
    }

    /// 牌数（**不含**"牌组为空"之外的任何裁剪：这里没有容量概念）。
    #[must_use]
    pub const fn len(&self) -> usize {
        self.list.len()
    }

    /// 有没有牌。
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.list.is_empty()
    }

    /// 第 `index` 张牌的定义 id。
    ///
    /// `index` 由调用方保证 `< len()`：越界也只可能是调用方算错了，所以它和
    /// "内容形态坏了"共用 [`DeckError::Malformed`]（不 panic、不返回空串）。
    pub fn get(&self, index: usize) -> Result<&'a str, DeckError> {
        let hop = self.origin.path();
        if index >= self.len() {
            return Err(DeckError::Malformed(hop));
        }
        let cell = self.list.cell(index).ok_or(DeckError::Malformed(hop))?;
        if !self.wrapped {
            return self.content.string(cell).ok_or(DeckError::BadString(cell));
        }
        let term = self
            .content
            .term(cell)
            .ok_or(DeckError::Malformed(hop))?;
        // 根 `Deck` 的元素有两种形态（实测）：
        // * `_wrap_lower`（**op 6**，1 个空名字段 / `F_STR` / `FLAG_WRAP_LOWER`）——
        //   `{"value": "strike"}` 被编译器降级之后的样子，槽 0 **就是串号**
        //   （`card_has_tag` 读 `Tags` 元素用的是同一条实测形状）；两份镜像都是它。
        // * 真对象（op ≥ 16）：字段表里有一个叫 `value` 的 `F_STR` 字段 —— 按**名字**找，
        //   因为对象可以有别的键、位置会漂。
        if term.op == OP_WRAP_LOWER || term.op == OP_WRAP_UPPER {
            let string = term.slot(0).ok_or(DeckError::Malformed(hop))?;
            return self
                .content
                .string(string)
                .ok_or(DeckError::BadString(string));
        }
        if term.op < OP_FIRST_DYNAMIC {
            return Err(DeckError::Malformed(hop));
        }
        let opcode = self
            .content
            .opcode(term.op)
            .ok_or(DeckError::Malformed(hop))?;
        let mut at = 0usize;
        for position in 0..opcode.nfields() {
            let field = opcode.field(position).ok_or(DeckError::Malformed(hop))?;
            let width = usize::from(field.slots().ok_or(DeckError::Malformed(hop))?);
            let name = self
                .content
                .string(field.name_str())
                .ok_or(DeckError::Malformed(hop))?;
            if name == "value" {
                if field.kind() != F_STR {
                    return Err(DeckError::Malformed(hop));
                }
                let string = term.slot(at).ok_or(DeckError::Malformed(hop))?;
                return self
                    .content
                    .string(string)
                    .ok_or(DeckError::BadString(string));
            }
            at = at.checked_add(width).ok_or(DeckError::Malformed(hop))?;
        }
        Err(DeckError::Malformed(hop))
    }
}

impl<'a> Content<'a> {
    /// 内容声明的**起始牌组**，按参考 `RunSetup.CreateInitialRun` 的顺序解析
    /// （三行表在本节头部，含每一跳的行号）。
    ///
    /// 规则逐字：**花名册非空** ⇒ 看 `Characters[0].Start.Deck`，空了才退到根 `Deck`；
    /// **花名册为空** ⇒ 看 `Start.Deck`，空了才退到根 `Deck`。第三处不会再退 ——
    /// 参考的 `blueprint.Deck` 就是最后一个回退项。
    ///
    /// 字段`Deck` **缺席**按参考的默认值处理（`RunStart.Deck = []`，`RunBlueprint.cs:214-216`）
    /// ⇒ 当成"这一处声明了空"，接着看下一处。**出现在场但类别不对**则是内容坏了
    /// （[`DeckError::Malformed`]）—— 两者的区别正是"参考写明的默认"与"我读错了"。
    /// 角色起始的**数值**事实：`Characters[0].Start` 下的 `MaxHealth` / `StartingHealth` /
    /// `Resources.gold`。
    ///
    /// 为什么要有它：run 层（`rd-run`）刻意不认识内容（它的模块头写了理由），
    /// 所以"这一局从多少血、多少钱开始"必须由**内容**告诉他，而不是由调用方抄三个常数。
    /// 实测 `tools/contentc/packages/sts` 里 `Characters[0].Start` 是
    /// `{MaxHealth: 80, StartingHealth: 80, Resources: {gold: 0}, Deck: [...10 张...],
    /// StartingRelics: []}`。
    ///
    /// ⚠️ **`StartingRelics` 是空的**，而 `inv:§2` 说起始遗物是 `Burning Blood`
    /// （"战斗结束回 6 血"）—— 也就是说**这份内容还没把起始遗物写进去**。
    /// 这一条不是本函数的缺陷，是内容的缺口，已记在 `docs/spec/run-layer.md` §4.5；
    /// 在内容补上之前，run 层的 `Burning Blood` 效果没有来源可读，M1 的 HP 账就是错的。
    ///
    /// 缺席的语义：`MaxHealth` **缺席 ⇒ 响亮失败**（[`DeckError::Malformed`]）——
    /// 一个没有最大生命的角色会让整局的 HP 账静默变成 0；`StartingHealth` 缺席则退回
    /// `MaxHealth`（参考的默认是"满血开局"）；`Resources` / `Resources.gold` 缺席 ⇒ 0 金
    /// （参考的默认是空资源表）。
    pub fn character_start_facts(
        &self,
        roots: DeckRoots,
    ) -> Result<Option<CharacterStart>, DeckError> {
        let Some(term) = character_start(self, roots.characters)? else {
            return Ok(None);
        };
        let hop = DeckOrigin::CharacterStart.path();
        let node = crate::ir::NodeRef::new(self, term);
        let max_health = node
            .int_field("MaxHealth")
            .map_err(|_| DeckError::Malformed(hop))?
            .ok_or(DeckError::Malformed(hop))?;
        let starting_health = node
            .int_field("StartingHealth")
            .map_err(|_| DeckError::Malformed(hop))?
            .unwrap_or(max_health);
        let gold = match node.node_field("Resources") {
            Ok(Some(resources)) => resources.int_field("gold").ok().flatten().unwrap_or(0),
            _ => 0,
        };
        Ok(Some(CharacterStart {
            max_health,
            starting_health,
            gold,
        }))
    }

    pub fn start_deck(&self, roots: DeckRoots) -> Result<StartDeck<'_>, DeckError> {
        let mut seen_any = false;
        // 第 1 跳：花名册非空 ⇒ `Characters[0].Start`；第 2 跳：花名册为空 ⇒ 根 `Start`。
        let start = match character_start(self, roots.characters)? {
            Some(term) => {
                seen_any = true;
                Some((DeckOrigin::CharacterStart, term))
            }
            None => roots.start.map(|term| {
                seen_any = true;
                (DeckOrigin::RootStart, term)
            }),
        };
        if let Some((origin, term)) = start {
            if let Some(list) = deck_field(self, term, origin.path())? {
                if !list.is_empty() {
                    return Ok(StartDeck {
                        content: self,
                        origin,
                        wrapped: list.kind() == F_TERMLIST,
                        list,
                    });
                }
            }
        }
        // 第 3 跳：根 `Deck`（参考的 `blueprint.Deck`）。
        if let Some(term) = roots.deck {
            seen_any = true;
            let list = deck_root(self, term, DeckOrigin::RootDeck.path())?;
            if !list.is_empty() {
                return Ok(StartDeck {
                    content: self,
                    origin: DeckOrigin::RootDeck,
                    wrapped: list.kind() == F_TERMLIST,
                    list,
                });
            }
        }
        if seen_any {
            Err(DeckError::EmptyDeck)
        } else {
            Err(DeckError::NoDeckKey)
        }
    }
}

impl<'a> Content<'a> {
    /// 起始遗物（`Start.StartingRelics`，两跳规则与 [`Content::start_deck`] 逐字相同：
    /// 花名册非空就看 `Characters[0].Start`，否则看根 `Start`）。
    ///
    /// 返回 `Ok(None)` = **这份内容没有声明起始遗物** —— 与"有声明但是空表"同义，
    /// 因为参考的"空 = 没声明"两种拼法都表示同一件事（`content-schema.md` §2.2）。
    /// 内容坏了（花名册非空而第 0 项没有 `Start`、字段类别不对）才是错误。
    ///
    /// 为什么复用 [`StartDeck`] 这个类型：它就是一个"借用视图 + 按序取 id"的东西，
    /// 与遗物列表的形状完全一样；再写一个同构的结构体只会多一处会漂的地方。
    pub fn start_relics(&self, roots: DeckRoots) -> Result<Option<StartDeck<'_>>, DeckError> {
        // 这一跳的名字进所有错误消息（与 `DeckOrigin::path()` 同一惯例：不说坏在哪，人要挖一遍）。
        const HOP: &str = "Start.StartingRelics";
        let start = match character_start(self, roots.characters)? {
            Some(term) => Some((DeckOrigin::CharacterStart, term)),
            None => roots.start.map(|term| (DeckOrigin::RootStart, term)),
        };
        let Some((origin, term)) = start else {
            return Ok(None);
        };
        let Some(list) = list_field(self, term, "StartingRelics", HOP)? else {
            return Ok(None);
        };
        if list.is_empty() {
            return Ok(None);
        }
        Ok(Some(StartDeck {
            content: self,
            origin,
            wrapped: list.kind() == F_TERMLIST,
            list,
        }))
    }
}

impl<'a> Content<'a> {
    /// 这张卡的 `Tags` 里有没有 `tag`。
    ///
    /// `Some(false)` = 没有（`Tags` 缺席、空表、或者读完了都没有）。`None` = **读不出来**
    /// （卡不在镜像里、`Tags` 不是 `_arr`、元素不是字符串也不是带 `value` 的对象）——
    /// 调用方必须把 `None` 当错误，不能当"没有这个标签"：那正是"静默降级"的形状。
    ///
    /// 元素两种拼法都收：裸字符串，或**一字段包装**（`STRLIST(wrap)`，`layout.txt` 第 37 行）。
    /// ⚠️ 后者在镜像里**不是** `_obj{value: "..."}`，而是"op 6 + 一条无名 `F_STR` 字段"
    /// —— 按名字找 `value` 会一个标签都读不出来（实测，见下面的注释）。
    #[must_use]
    pub fn card_has_tag(&self, card: &str, tag: &str) -> Option<bool> {
        let entry = self.lookup_in(card, EK_CARD)?;
        let row = CardRow::new(self.row(Table::Card, entry.index as u32)?)?;
        let handle = row.tags();
        if handle == ABSENT16 || handle == NULL16 {
            return Some(false);
        }
        let term = self.term(handle)?;
        if term.op != OP_ARR {
            return None;
        }
        let start = term.slot(0)?;
        let count = term.slot(1)?;
        if count == LIST_ABSENT || count == LIST_NULL {
            return Some(false);
        }
        for index in 0..count {
            let cell = start.checked_add(index)?;
            let element = self.aux(cell)?;
            let element_term = self.term(element)?;
            // Two encodings, both measured on this image:
            //   * a bare string (`OP_STR`, value in slot 0);
            //   * the `{"value": "..."}` wrapper, which the compiler collapses into a **one-field
            //     term with an unnamed `F_STR` field** (measured: op 6, one field, kind `F_STR`,
            //     value in slot 0) -- *not* an `_obj` with a field called `value`, which is what
            //     the document suggests and what I assumed first. That assumption made every card
            //     tag unreadable (`None`), and the reward screen offered `slimed`.
            let text = if element_term.op == OP_STR {
                self.string(element_term.slot(0)?)?
            } else {
                let opcode = self.opcode(element_term.op)?;
                let field = opcode.field(0)?;
                if field.kind() != F_STR {
                    return None;
                }
                self.string(element_term.slot(0)?)?
            };
            if text == tag {
                return Some(true);
            }
        }
        Some(false)
    }
}

impl<'a> Content<'a> {
    /// 这张卡的 `Rarity`。`None` = 没声明或读不出来。
    #[must_use]
    pub fn card_rarity(&self, card: &str) -> Option<&'a str> {
        let entry = self.lookup_in(card, EK_CARD)?;
        let row = CardRow::new(self.row(Table::Card, entry.index as u32)?)?;
        let cell = row.rarity();
        if cell == ABSENT16 || cell == NULL16 {
            return None;
        }
        self.string(cell)
    }

    /// `Retain` 关键字：这张牌回合结束时**留在手里**吗？（`CARD.RetainInHandOnTurnEnd`）
    ///
    /// `None` = 这张卡不在镜像里 / 那一格读不出来 —— 调用方必须把"读不出来"和"false"分开，
    /// 因为两者的处置方向相反（见 `host::card_stays_in_hand_at_turn_end`）。
    ///
    /// `F_BOOL` 的四个原始值是 **0 = 缺席、1 = false、2 = true、3 = null**（不是 `bool` 的两位）。
    #[must_use]
    pub fn card_retains_in_hand(&self, card: &str) -> Option<bool> {
        let entry = self.lookup_in(card, EK_CARD)?;
        let row = CardRow::new(self.row(Table::Card, entry.index as u32)?)?;
        let cell = row.retain_in_hand_on_turn_end();
        if cell == ABSENT16 || cell == NULL16 {
            // 缺席 / null **就是** false（参考的默认值），不是"读不出来"。
            return Some(false);
        }
        // 其余任何值都必须能判成真假，判不出来就是镜像坏了。
        match cell {
            // `F_BOOL` 的四个原始值：0 = 缺席（上面已处理）、1 = false、2 = true、3 = null
            // （上面已处理）。**不是** `bool` 的 0/1 —— 这一格把 `1` 当 true 会正好反过来。
            1 => Some(false),
            2 => Some(true),
            _ => None,
        }
    }

    /// 这张牌从**手牌**在回合结束时去哪儿（`CARD.TurnEndHandDestinationZone`）。
    ///
    /// `Ethereal` 就是这一格等于 `"ExhaustPile"`：参考实现的 Ethereal **不是**一个独立的判据，
    /// 它落在 `CardZoneEffects.cs:427` 的落区里（`host::turn_end_hand_destination`）。
    /// `None` = 这张卡不在镜像里；字符串本身原样返回，让调用方自己认枚举名（认不出要响）。
    #[must_use]
    pub fn card_turn_end_zone(&self, card: &str) -> Option<&'a str> {
        let entry = self.lookup_in(card, EK_CARD)?;
        let row = CardRow::new(self.row(Table::Card, entry.index as u32)?)?;
        let cell = row.turn_end_hand_destination_zone();
        if cell == ABSENT16 || cell == NULL16 {
            // 缺席 = 参考的构造默认值 `DiscardPile`。用一个**明确的空串**表示它，
            // 而不是让调用方把 `None`（"卡不在镜像里"）当成"默认落区"。
            return Some("");
        }
        self.string(cell)
    }
}

impl<'a> Content<'a> {
    /// The encounter ids in one pool of `EncounterTables` (`inv:§5.2` weak / `inv:§5.3` elite).
    ///
    /// `pool` is `"Weak"` or `"Elite"`. The document also carries a `Weight` per entry; `ENCT` has no
    /// weight cell (`rdcfmt.py`), so a pool is a **set** here and the weights stay documentation.
    ///
    /// `None` = the table, the pool, or the root key is missing -- a caller must treat that as
    /// "cannot tell", not as "an empty pool".
    pub fn encounter_pool(&self, pool: &str) -> Option<[&'a str; MAX_POOL_IDS]> {
        // The hop strings are spelled out: `sts_content_check.py` decides "the kernel reads
        // `EncounterTables.Weak`" by finding that literal in kernel code, and a pool name passed
        // through a variable is invisible to it. They are also the name that goes into every error.
        let hop = match pool {
            "Weak" => "EncounterTables.Weak",
            "Elite" => "EncounterTables.Elite",
            "Boss" => "EncounterTables.Boss",
            // §130: acts 2 and 3 have their own pools, suffixed by the act number.
            "Weak2" => "EncounterTables.Weak2",
            "Weak3" => "EncounterTables.Weak3",
            "Elite2" => "EncounterTables.Elite2",
            "Elite3" => "EncounterTables.Elite3",
            "Boss2" => "EncounterTables.Boss2",
            "Boss3" => "EncounterTables.Boss3",
            _ => return None,
        };
        self.id_pool("EncounterTables", pool, hop)
    }

    /// The `?`-room event ids of one act (`port-plan.md` §133).
    ///
    /// `pool` is `"Events"` (act 1), `"Events2"` or `"Events3"`.
    #[must_use]
    pub fn event_pool(&self, pool: &str) -> Option<[&'a str; MAX_POOL_IDS]> {
        let hop = match pool {
            "Events" => "EventTables.Events",
            "Events2" => "EventTables.Events2",
            "Events3" => "EventTables.Events3",
            _ => return None,
        };
        self.id_pool("EventTables", pool, hop)
    }

    /// The shared walker behind the two public pool readers.
    ///
    /// `hop` is passed in (not rebuilt) so the literal stays in the public reader, where the content
    /// gate can see it.
    ///
    /// ⚠️ **There is no potion pool** (§158). `PotionTables` used to hold one list per act, and the
    /// wiki has no such split: every potion of a rarity is equally likely in every act. Keeping the
    /// three lists would also have needed `MAX_POOL_IDS >= 33` or it would have **silently truncated**
    /// the drop pool to eight entries. The potion pool is now "every `POT` row", which cannot fall out
    /// of sync with the potions that exist.
    fn id_pool(
        &self,
        table_name: &str,
        pool: &str,
        hop: &'static str,
    ) -> Option<[&'a str; MAX_POOL_IDS]> {
        // Literals on purpose: `sts_content_check` decides "the kernel reads this root table" by
        // finding `root_by_name("X")` in kernel code. A variable there is invisible to it.
        let root = match table_name {
            "EncounterTables" => self.root_by_name("EncounterTables")?,
            "EventTables" => self.root_by_name("EventTables")?,
            _ => return None,
        };
        let table = self.term(root)?;
        if table.op < OP_FIRST_DYNAMIC {
            return None;
        }
        let opcode = self.opcode(table.op)?;
        let mut at = 0usize;
        for position in 0..opcode.nfields() {
            let field = opcode.field(position)?;
            let width = usize::from(field.slots()?);
            let name = self.string(field.name_str())?;
            if name == pool {
                let list = slot_list(self, &table, at, field.kind(), hop).ok()?;
                let mut out = [""; MAX_POOL_IDS];
                for index in 0..list.len().min(MAX_POOL_IDS) {
                    // Each element is an `_obj{Id, Weight}`; the id is an `F_STR` field.
                    let element = list.cell(index)?;
                    let element_term = self.term(element)?;
                    if element_term.op < OP_FIRST_DYNAMIC {
                        return None;
                    }
                    let element_opcode = self.opcode(element_term.op)?;
                    let mut offset = 0usize;
                    for slot in 0..element_opcode.nfields() {
                        let sub = element_opcode.field(slot)?;
                        let sub_width = usize::from(sub.slots()?);
                        let sub_name = self.string(sub.name_str())?;
                        // The field name lives in a const on purpose: `sts_content_check.py` looks
                        // for `name == "<Key>"` to decide whether the kernel reads a sub-key, and an
                        // inline `"Id"` here made it report `Characters[].Id` as read (a false
                        // positive -- that string is an `EncounterTables` field).
                        if sub_name == ENCOUNTER_ID_FIELD && sub.kind() == F_STR {
                            out[index] = self.string(element_term.slot(offset)?)?;
                            break;
                        }
                        offset = offset.checked_add(sub_width)?;
                    }
                }
                return Some(out);
            }
            at = at.checked_add(width)?;
        }
        None
    }

    /// The **weights** of one encounter pool (`port-plan.md` §153).
    ///
    /// Same hop mapping as [`Self::encounter_pool`]; the difference is which field is read (`Weight`
    /// instead of `Id`). Both live on the same element, so a reader that takes only the ids throws
    /// the weights away -- which is what this kernel did until §153.
    ///
    /// `None` = the pool is absent. A row without a `Weight` reads as `0`; the caller falls back to
    /// uniform when every weight is zero rather than dropping such a row.
    #[must_use]
    pub fn encounter_weights(&self, pool: &str) -> Option<[u16; MAX_POOL_IDS]> {
        // The hops are spelled out for the same reason as in `encounter_pool`: the content gate
        // decides "the kernel reads `EncounterTables.Weak`" by finding that literal in kernel code.
        let hop = match pool {
            "Weak" => "EncounterTables.Weak",
            "Elite" => "EncounterTables.Elite",
            "Boss" => "EncounterTables.Boss",
            "Weak2" => "EncounterTables.Weak2",
            "Weak3" => "EncounterTables.Weak3",
            "Elite2" => "EncounterTables.Elite2",
            "Elite3" => "EncounterTables.Elite3",
            "Boss2" => "EncounterTables.Boss2",
            "Boss3" => "EncounterTables.Boss3",
            _ => return None,
        };
        let root = self.root_by_name("EncounterTables")?;
        let table = self.term(root)?;
        if table.op < OP_FIRST_DYNAMIC {
            return None;
        }
        let opcode = self.opcode(table.op)?;
        let mut at = 0usize;
        for position in 0..opcode.nfields() {
            let field = opcode.field(position)?;
            let width = usize::from(field.slots()?);
            let name = self.string(field.name_str())?;
            if name == pool {
                let list = slot_list(self, &table, at, field.kind(), hop).ok()?;
                let mut out = [0u16; MAX_POOL_IDS];
                for index in 0..list.len().min(MAX_POOL_IDS) {
                    let element = list.cell(index)?;
                    let element_term = self.term(element)?;
                    if element_term.op < OP_FIRST_DYNAMIC {
                        return None;
                    }
                    let element_opcode = self.opcode(element_term.op)?;
                    let mut offset = 0usize;
                    for slot in 0..element_opcode.nfields() {
                        let sub = element_opcode.field(slot)?;
                        let sub_width = usize::from(sub.slots()?);
                        let sub_name = self.string(sub.name_str())?;
                        if sub_name == WEIGHT_FIELD && sub.kind() == F_INT {
                            let raw = element_term.slot(offset)?;
                            out[index] = u16::try_from(i64::from(raw).max(0)).unwrap_or(u16::MAX);
                            break;
                        }
                        offset = offset.checked_add(sub_width)?;
                    }
                }
                return Some(out);
            }
            at = at.checked_add(width)?;
        }
        None
    }
}
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Potion<'a> {
    /// The id (`fire_potion` ...).
    pub id: &'a str,
    /// Display name.
    pub name: &'a str,
    /// What it does, in the closed vocabulary.
    pub effect: &'a str,
    /// How much of it.
    pub amount: i16,
    /// `Common` / `Uncommon` / `Rare` (`inv:§9`).
    pub rarity: &'a str,
}

impl<'a> Content<'a> {
    /// How many potions the image declares.
    #[must_use]
    pub fn potion_count(&self) -> u32 {
        self.section(S_POT).map_or(0, |section| section.count)
    }

    /// Potion `index`. `None` when the row is unusable.
    #[must_use]
    pub fn potion(&self, index: u32) -> Option<Potion<'a>> {
        let row = PotRow::new(self.row(Table::Potion, index)?)?;
        Some(Potion {
            id: self.string(row.id()).filter(|id| !id.is_empty())?,
            name: self.string(row.name_key()).unwrap_or(""),
            effect: self.string(row.effect()).unwrap_or(""),
            amount: {
                let cell = row.amount();
                if cell == ABSENT16 || cell == NULL16 {
                    0
                } else {
                    cell as i16
                }
            },
            rarity: self.string(row.rarity()).unwrap_or(""),
        })
    }
}

/// One choice of a `?`-room event: the button text, the effect's name, and its amount.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct EventChoice<'a> {
    /// What the button says.
    pub label: &'a str,
    /// `heal` / `gold` / `damage` / `max_hp` / `nothing` -- a **closed** vocabulary, because the run
    /// layer has no program interpreter.
    pub effect: &'a str,
    /// How much of it.
    pub amount: i16,
}

impl<'a> Content<'a> {
    /// The `?`-room events in the image, in table order: `(id, choices)`.
    ///
    /// `count` is the table's row count; a row whose id cannot be read is skipped rather than
    /// reported as an empty event -- `usize::MAX` marks "unreadable" so a caller cannot mistake it
    /// for a valid event with no text.
    #[must_use]
    pub fn event_count(&self) -> u32 {
        self.section(S_EV).map_or(0, |section| section.count)
    }

    /// Event `index`: its id, its body text, and its two choices. `None` when the row is unusable.
    #[must_use]
    pub fn event(&self, index: u32) -> Option<(&'a str, &'a str, [EventChoice<'a>; 2])> {
        let row = EvRow::new(self.row(Table::Event, index)?)?;
        let id = self.string(row.id())?;
        let text = self
            .string(row.description_key())
            .filter(|text| !text.is_empty())
            .unwrap_or("");
        let mut choices = [EventChoice {
            label: "",
            effect: "nothing",
            amount: 0,
        }; 2];
        for (slot, (label_cell, effect_cell, amount_cell)) in [
            (row.label0(), row.effect0(), row.amount0()),
            (row.label1(), row.effect1(), row.amount1()),
        ]
        .into_iter()
        .enumerate()
        {
            choices[slot] = EventChoice {
                label: self.string(label_cell).unwrap_or(""),
                effect: self.string(effect_cell).unwrap_or("nothing"),
                amount: self.amount(amount_cell),
            };
        }
        Some((id, text, choices))
    }

    /// An `F_INT` cell as a number. `ABSENT16` / `NULL16` are zero; everything else is `i16`.
    fn amount(&self, cell: u16) -> i16 {
        if cell == ABSENT16 || cell == NULL16 {
            0
        } else {
            cell as i16
        }
    }
}

/// 花名册第 0 人的 `Start` 对象 term（`RunBlueprint.cs:171-174`：`Characters[0].Start`）。
///
/// `Ok(None)` = **花名册为空 / 没有这个根键**（⇒ 走根 `Start`）；`Ok(Some(t))` = 有。
/// ⚠️ 花名册**非空但第 0 项没有 `Start`** 是形态坏了（`Malformed`），不是"没有花名册"：
/// 把前者当成后者会让内核悄悄改用 `Start.Deck`（内容一漂就选错牌组，而且看不出来）。
fn character_start<'a>(
    content: &'a Content<'a>,
    characters: Option<u16>,
) -> Result<Option<u16>, DeckError> {
    const HOP: &str = "Characters";
    let Some(term_id) = characters else {
        return Ok(None);
    };
    let list = deck_root(content, term_id, HOP)?;
    if list.is_empty() {
        return Ok(None);
    }
    let first = list.cell(0).ok_or(DeckError::Malformed(HOP))?;
    let term = content.term(first).ok_or(DeckError::Malformed(HOP))?;
    if term.op < OP_FIRST_DYNAMIC {
        return Err(DeckError::Malformed(HOP));
    }
    let opcode = content
        .opcode(term.op)
        .ok_or(DeckError::Malformed(HOP))?;
    let mut at = 0usize;
    for position in 0..opcode.nfields() {
        let field = opcode.field(position).ok_or(DeckError::Malformed(HOP))?;
        let width = usize::from(field.slots().ok_or(DeckError::Malformed(HOP))?);
        let name = content
            .string(field.name_str())
            .ok_or(DeckError::Malformed(HOP))?;
        if name == "Start" {
            if field.kind() != F_TERM {
                return Err(DeckError::Malformed(HOP));
            }
            let start = term.slot(at).ok_or(DeckError::Malformed(HOP))?;
            if start == ABSENT16 || start == NULL16 {
                return Err(DeckError::Malformed("Characters[0].Start"));
            }
            return Ok(Some(start));
        }
        at = at.checked_add(width).ok_or(DeckError::Malformed(HOP))?;
    }
    Err(DeckError::Malformed("Characters[0].Start"))
}

/// 一个对象 term 的 `Deck` 字段 → [`SlotList`]；字段**缺席** ⇒ `Ok(None)`（参考的空默认）。
fn deck_field<'a>(
    content: &'a Content<'a>,
    term_id: u16,
    hop: &'static str,
) -> Result<Option<SlotList<'a>>, DeckError> {
    list_field(content, term_id, "Deck", hop)
}

/// 一个对象 term 的任意 `F_STRLIST` / `F_TERMLIST` 字段 → [`SlotList`]；字段**缺席** ⇒
/// `Ok(None)`。按**字段名**找，不按位置：镜像里的字段表是按名字排序派生的（`_obj(...)` 的
/// 字段字母序），所以位置会随内容变化，名字不会。
fn list_field<'a>(
    content: &'a Content<'a>,
    term_id: u16,
    wanted: &str,
    hop: &'static str,
) -> Result<Option<SlotList<'a>>, DeckError> {
    let term = content.term(term_id).ok_or(DeckError::Malformed(hop))?;
    if term.op < OP_FIRST_DYNAMIC {
        return Err(DeckError::Malformed(hop));
    }
    let opcode = content
        .opcode(term.op)
        .ok_or(DeckError::Malformed(hop))?;
    let mut at = 0usize;
    for position in 0..opcode.nfields() {
        let field = opcode.field(position).ok_or(DeckError::Malformed(hop))?;
        let width = usize::from(field.slots().ok_or(DeckError::Malformed(hop))?);
        let name = content
            .string(field.name_str())
            .ok_or(DeckError::Malformed(hop))?;
        if name == wanted {
            return slot_list(content, &term, at, field.kind(), hop).map(Some);
        }
        at = at.checked_add(width).ok_or(DeckError::Malformed(hop))?;
    }
    Ok(None)
}

/// 一个池里最多认多少个遭遇 id（`EncounterTables` 的条目数，本内容 4）。
pub const MAX_POOL_IDS: usize = 8;

/// The field name of each entry in an `EncounterTables` pool.
const ENCOUNTER_ID_FIELD: &str = "Id";

/// The `Weight` of each entry in an `EncounterTables` pool (`port-plan.md` §153).
///
/// It sat in the content **unread** for twenty sections: the rows declared `Weight: 20/16/16/…`, the
/// content gate checked they sum to 100, and `rd_wasm::run::fight_begin` picked `roll(len)`
/// (uniform). Declared, validated, unused.
const WEIGHT_FIELD: &str = "Weight";

/// 一个**根键**本身的列表读数（`F_TERMLIST` / `F_STRLIST`）。
///
/// 根键的列表没有"外层对象"：term 自己的 opcode 只有一条匿名字段，两个槽就是
/// `(AUX 起址, 个数)`（实测根 `Deck` = `[75, 10]` / `[1521, 10]`，根 `Characters` = `[74, 1]`）。
fn deck_root<'a>(
    content: &'a Content<'a>,
    term_id: u16,
    hop: &'static str,
) -> Result<SlotList<'a>, DeckError> {
    let term = content.term(term_id).ok_or(DeckError::Malformed(hop))?;
    let opcode = content
        .opcode(term.op)
        .ok_or(DeckError::Malformed(hop))?;
    let field = opcode.field(0).ok_or(DeckError::Malformed(hop))?;
    slot_list(content, &term, 0, field.kind(), hop)
}

/// `(AUX 起址, 个数)` 两个槽 → [`SlotList`]，并把"个数是哨兵"读成空列表。
///
/// ⚠️ 空列表在镜像里是**个数 = 哨兵**（`LIST_ABSENT` / `LIST_NULL`），不是 `count == 0`：
/// 与 [`EnemySpec::list`] 同一条读法（那边 149 条记录里 146 条是哨兵）。两种拼法都收，
/// 因为参考的"空 = 没声明"必须两种都能表达，否则一份合法内容会被当成形态坏了。
fn slot_list<'a>(
    content: &'a Content<'a>,
    term: &Term<'a>,
    at: usize,
    kind: u8,
    hop: &'static str,
) -> Result<SlotList<'a>, DeckError> {
    if kind != F_STRLIST && kind != F_TERMLIST {
        return Err(DeckError::Malformed(hop));
    }
    let start = term.slot(at).ok_or(DeckError::Malformed(hop))?;
    let count = term
        .slot(at.checked_add(1).ok_or(DeckError::Malformed(hop))?)
        .ok_or(DeckError::Malformed(hop))?;
    let count = if count == LIST_ABSENT || count == LIST_NULL {
        0
    } else {
        count
    };
    // 每一格都必须真的在 `AUX` 里，否则 `SlotList::cell` 会静默给 `None`
    // （空列表不查：个数是哨兵时起址槽是垃圾值，与 `EnemySpec::list` 同理）。
    if count > 0 {
        let end = usize::from(start)
            .checked_add(usize::from(count))
            .ok_or(DeckError::Malformed(hop))?;
        if end > content.aux_cells() {
            return Err(DeckError::Malformed(hop));
        }
    }
    Ok(SlotList {
        content,
        start,
        count,
        kind,
    })
}

// ===========================================================================
// opcode / term / 根指针 / 符号表
// ===========================================================================

/// 一条 opcode 描述 + 它那 `nfields` 条 `OPF` 记录（裸字节，靠 `Field` 解释）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Opcode<'a> {
    pub op: u16,
    /// 名字串号（保留 opcode 是 0 = 空串）。
    pub name_str: u16,
    /// `OPCLASS_IR` 或 `OPCLASS_GENERIC`（**op < 16 时先按保留语义处理，别看这个**）。
    pub opclass: u8,
    fields: &'a [u8],
}

impl<'a> Opcode<'a> {
    /// 逻辑字段数。
    #[must_use]
    pub fn nfields(&self) -> usize {
        self.fields.len() / 4
    }

    /// 是不是 IR 节点（`{kind, value}` 信封）。
    #[must_use]
    pub fn is_ir(&self) -> bool {
        self.opclass == OPCLASS_IR
    }

    /// 第 `j` 条字段描述。越界 `None`。
    #[must_use]
    pub fn field(&self, j: usize) -> Option<Field<'a>> {
        let start = j.checked_mul(4)?;
        let end = start.checked_add(4)?;
        Some(Field {
            raw: self.fields.get(start..end)?,
        })
    }

    /// 遍历字段描述。
    #[must_use]
    pub fn fields(&self) -> Fields<'a> {
        Fields {
            raw: self.fields,
            next: 0,
        }
    }

    /// 本 opcode 的 term 记录有几个槽（= 各字段槽数之和）。
    /// 字段类别不合法时 `None`（`reader.py` 在这种输入上会抛 `KeyError`）。
    #[must_use]
    pub fn nslots(&self) -> Option<usize> {
        let mut n = 0usize;
        for j in 0..self.nfields() {
            n = n.checked_add(self.field(j)?.slots()? as usize)?;
        }
        Some(n)
    }
}

/// `OPF` 里的一条 4 字节字段描述。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Field<'a> {
    raw: &'a [u8],
}

impl<'a> Field<'a> {
    /// JSON 键的串号（0 = 空串）。
    #[must_use]
    pub fn name_str(&self) -> u16 {
        u16_at(self.raw, 0).unwrap_or(0)
    }

    /// 字段类别 `F_*`（越界/坏数据给 0，`field_slots` 会拒绝它）。
    #[must_use]
    pub fn kind(&self) -> u8 {
        self.raw.get(2).copied().unwrap_or(0)
    }

    /// `FLAG_WRAP_*`。
    #[must_use]
    pub fn flags(&self) -> u8 {
        self.raw.get(3).copied().unwrap_or(0)
    }

    /// 这个字段占几个 u16 槽。
    #[must_use]
    pub fn slots(&self) -> Option<u8> {
        field_slots(self.kind())
    }
}

/// `Opcode::fields()` 的迭代器。
#[derive(Debug, Clone)]
pub struct Fields<'a> {
    raw: &'a [u8],
    next: usize,
}

impl<'a> Iterator for Fields<'a> {
    type Item = Field<'a>;

    fn next(&mut self) -> Option<Field<'a>> {
        let start = self.next.checked_mul(4)?;
        let end = start.checked_add(4)?;
        let raw = self.raw.get(start..end)?;
        self.next += 1;
        Some(Field { raw })
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let n = (self.raw.len() / 4).saturating_sub(self.next);
        (n, Some(n))
    }
}

/// 一条 term 记录：`u16 op` + 按 opcode 字段类别推出的槽。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Term<'a> {
    pub id: u16,
    pub op: u16,
    slots: &'a [u8],
}

impl<'a> Term<'a> {
    /// 槽的原始字节（`nslots × 2`）。
    #[must_use]
    pub fn slots_bytes(&self) -> &'a [u8] {
        self.slots
    }

    /// 槽数。
    #[must_use]
    pub fn nslots(&self) -> usize {
        self.slots.len() / 2
    }

    /// 第 `i` 个槽。越界 `None`。
    #[must_use]
    pub fn slot(&self, i: usize) -> Option<u16> {
        u16_at(self.slots, i.checked_mul(2)?)
    }
}

/// `STR` + `STRO` 的串迭代器（串号 1..=`string_count()`）。
#[derive(Debug, Clone)]
pub struct Strings<'a> {
    stro: &'a [u8],
    pool: &'a [u8],
    next: u32,
    end: u32,
}

impl<'a> Iterator for Strings<'a> {
    /// 坏项是 `None`（**不 panic、不静默跳过**）。
    type Item = Option<&'a str>;

    fn next(&mut self) -> Option<Option<&'a str>> {
        if self.next >= self.end {
            return None;
        }
        self.next += 1;
        Some(string_at(self.pool, self.stro, self.next as u16))
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let n = self.end.saturating_sub(self.next) as usize;
        (n, Some(n))
    }
}

impl<'a> ExactSizeIterator for Strings<'a> {}

/// `ROOT` 的一项：顶层键名 → term。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RootEntry<'a> {
    pub key: &'a str,
    pub term: u16,
}

/// `IDX` 的一项：id 字符串 → `(实体类别, 表内行号)`。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct IdEntry<'a> {
    /// 在 `IDX` 里的位置（0 起）。同 id 多条时给出稳定的区分依据。
    pub position: u32,
    pub id: &'a str,
    /// `EK_*`。
    pub entity_kind: u8,
    /// `IDX` 的 flags 字节（真实镜像全是 0）。
    pub flags: u8,
    /// 表内行号（`map_node`/`event`/`shop`/`character` 没有表，意义由调用方定）。
    pub index: u16,
}

#[cfg(test)]
mod tests {
    // 真实镜像不在仓库里（它是构建产物），所以测试按**绝对路径**找；找不到就 panic 并说明
    // 怎么生成它 —— 一个在产物缺席时安静通过的测试，等于没有测试。
    // 路径：tools/contentc/out/content.core.rdcf

    use super::*;

    const CORE_IMAGE: &str = r"D:\Vibe\sts-tui\tools\contentc\out\content.core.rdcf";
    const FULL_IMAGE: &str = r"D:\Vibe\sts-tui\tools\contentc\out\content.rdcf";

    /// `manifest.json` → `variants.core.sections`（逐字抄写，不改）。
    const CORE_SECTIONS: [(usize, &str, u32, u32, u32); 15] = [
        (0, "STR", 272, 31_051, 1_375),
        (1, "STRO", 31_324, 5_504, 1_376),
        (2, "OPD", 36_828, 1_040, 130),
        (3, "OPF", 37_868, 1_412, 353),
        (4, "TRM", 39_280, 20_760, 2_143),
        (5, "TRW", 60_040, 4_286, 2_143),
        (6, "AUX", 64_328, 4_156, 2_078),
        (7, "CARD", 68_484, 1_984, 62),
        (8, "STAT", 70_468, 920, 23),
        (9, "EACT", 71_388, 6_304, 394),
        (10, "ENCT", 77_692, 1_744, 109),
        (11, "REL", 79_436, 588, 49),
        (12, "ROOT", 80_024, 64, 16),
        (13, "IDX", 80_088, 5_528, 691),
        (14, "TAGS", 0, 0, 0),
    ];

    /// `manifest.json` → `variants.full.sections`。
    const FULL_SECTIONS: [(usize, &str, u32, u32, u32); 15] = [
        (0, "STR", 272, 76_799, 3_140),
        (1, "STRO", 77_072, 12_564, 3_141),
        (2, "OPD", 89_636, 1_112, 139),
        (3, "OPF", 90_748, 2_996, 749),
        (4, "TRM", 93_744, 34_004, 2_895),
        (5, "TRW", 127_748, 5_790, 2_895),
        (6, "AUX", 133_540, 7_620, 3_810),
        (7, "CARD", 141_160, 1_984, 62),
        (8, "STAT", 143_144, 920, 23),
        (9, "EACT", 144_064, 6_304, 394),
        (10, "ENCT", 150_368, 1_744, 109),
        (11, "REL", 152_112, 588, 49),
        (12, "ROOT", 152_700, 68, 17),
        (13, "IDX", 152_768, 5_528, 691),
        (14, "TAGS", 0, 0, 0),
    ];

    fn read_image(path: &str) -> Vec<u8> {
        std::fs::read(path).unwrap_or_else(|e| {
            panic!(
                "RDCF 镜像缺失或读不到：{path}\n  {e}\n  它是 tools/contentc 的构建产物，\
                 用 `python tools/contentc/compile.py` 生成（同时写出 content.rdcf 与 content.core.rdcf）"
            )
        })
    }

    fn with_core<T>(f: impl FnOnce(&Content<'_>, &[u8]) -> T) -> T {
        let blob = read_image(CORE_IMAGE);
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        f(&content, &blob)
    }

    fn dir_base(index: usize) -> usize {
        HEADER_BYTES + DIRECTORY_ENTRY_BYTES * index
    }

    fn patch32(blob: &mut [u8], at: usize, value: u32) {
        let slot = blob
            .get_mut(at..at + 4)
            .unwrap_or_else(|| panic!("patch32 越界: {at}"));
        slot.copy_from_slice(&value.to_le_bytes());
    }

    fn patch16(blob: &mut [u8], at: usize, value: u16) {
        let slot = blob
            .get_mut(at..at + 2)
            .unwrap_or_else(|| panic!("patch16 越界: {at}"));
        slot.copy_from_slice(&value.to_le_bytes());
    }

    // ------------------------------------------------------------ 坏输入

    #[test]
    fn parse_rejects_short_buffers() {
        assert_eq!(Content::parse(&[]).unwrap_err(), ContentError::TooSmall);
        assert_eq!(
            Content::parse(&[0u8; HEADER_BYTES - 1]).unwrap_err(),
            ContentError::TooSmall
        );
        // 头是好的但声明了 85,616 字节，而缓冲区没那么长 → 截断。
        let blob = read_image(CORE_IMAGE);
        for cut in [HEADER_BYTES, 1_000, 40_000, blob.len() - 1] {
            assert_eq!(
                Content::parse(&blob[..cut]).unwrap_err(),
                ContentError::TooSmall,
                "截断到 {cut} 字节应当是 TooSmall"
            );
        }
    }

    #[test]
    fn parse_rejects_bad_magic() {
        let mut blob = read_image(CORE_IMAGE);
        blob[0] = b'X';
        match Content::parse(&blob).unwrap_err() {
            ContentError::BadMagic(m) => assert_eq!(m, 0x4643_4458),
            other => panic!("应当是 BadMagic，实际 {other:?}"),
        }

        let mut blob = read_image(CORE_IMAGE);
        patch32(&mut blob, 0, 0);
        assert_eq!(
            Content::parse(&blob).unwrap_err(),
            ContentError::BadMagic(0)
        );
    }

    #[test]
    fn parse_rejects_an_unsupported_version() {
        let mut blob = read_image(CORE_IMAGE);
        assert_eq!(u16_at(&blob, HDR_VERSION), Some(FORMAT_VERSION));
        // Not a literal: the point of the test is "a version this build does not speak", and `2`
        // *is* the version now that `CARD.Rarity` moved it.
        let other = FORMAT_VERSION + 1;
        patch16(&mut blob, HDR_VERSION, other);
        assert_eq!(
            Content::parse(&blob).unwrap_err(),
            ContentError::UnsupportedVersion(other)
        );

        patch16(&mut blob, HDR_VERSION, 0);
        assert_eq!(
            Content::parse(&blob).unwrap_err(),
            ContentError::UnsupportedVersion(0)
        );
    }

    #[test]
    fn parse_rejects_a_section_outside_the_declared_size() {
        // 把 IDX 段推到文件尾之外。
        let mut blob = read_image(CORE_IMAGE);
        patch32(&mut blob, dir_base(S_IDX), 85_000);
        assert_eq!(
            Content::parse(&blob).unwrap_err(),
            ContentError::SectionOutOfRange { index: S_IDX }
        );

        // 截断成 40,000 字节并把 total_size 也改成 40,000：第一个越界的段是 TRM（39280+20760）。
        let mut blob = read_image(CORE_IMAGE);
        patch32(&mut blob, HDR_TOTAL_SIZE, 40_000);
        assert_eq!(
            Content::parse(&blob[..40_000]).unwrap_err(),
            ContentError::SectionOutOfRange { index: S_TRM }
        );

        // offset + bytes 恰好越过 1 字节也算越界（不取巧、也不溢出）。
        let mut blob = read_image(CORE_IMAGE);
        patch32(&mut blob, dir_base(S_TAGS), 85_616);
        patch32(&mut blob, dir_base(S_TAGS) + 4, 1);
        patch32(&mut blob, dir_base(S_TAGS) + 8, 1);
        assert_eq!(
            Content::parse(&blob).unwrap_err(),
            ContentError::SectionOutOfRange { index: S_TAGS }
        );
    }

    #[test]
    fn parse_rejects_a_directory_that_does_not_fit() {
        // dir_off 指到文件外。
        let mut blob = read_image(CORE_IMAGE);
        patch32(&mut blob, HDR_DIR_OFF, 0x00FF_0000);
        assert_eq!(
            Content::parse(&blob).unwrap_err(),
            ContentError::DirectoryTruncated
        );

        // dir_off 压在文件头里。
        patch32(&mut blob, HDR_DIR_OFF, 0);
        assert_eq!(
            Content::parse(&blob).unwrap_err(),
            ContentError::DirectoryTruncated
        );

        // nsec 超过本格式的 20 段。
        let mut blob = read_image(CORE_IMAGE);
        patch16(&mut blob, HDR_NSEC, SECTION_COUNT as u16 + 1);
        assert_eq!(
            Content::parse(&blob).unwrap_err(),
            ContentError::DirectoryTruncated
        );

        // nsec 合法但目录区越过声明的 total_size。
        let mut blob = read_image(CORE_IMAGE);
        patch16(&mut blob, HDR_NSEC, 20);
        patch32(&mut blob, HDR_TOTAL_SIZE, 271);
        assert_eq!(
            Content::parse(&blob[..271]).unwrap_err(),
            ContentError::DirectoryTruncated
        );
    }

    /// 畸形/被改坏的镜像走遍整个读接口，**一个 panic 都不许有**。
    fn exercise(blob: &[u8]) {
        let Ok(content) = Content::parse(blob) else {
            return;
        };
        let _ = content.validate();

        // 头部标量
        let _ = (
            content.version(),
            content.flags(),
            content.presentation_stripped(),
            content.total_size(),
            content.schema_version(),
            content.content_hash(),
            content.section_count(),
            content.string_count(),
            content.opcode_count(),
            content.term_count(),
            content.aux_cells(),
            content.root_count(),
            content.id_count(),
        );

        // 段视图：全部段号 + 全部段名 + 越界
        for i in 0..=content.section_count() + 3 {
            if let Some(section) = content.section(i) {
                let _ = (section.is_empty(), section.end(), section.u16_at(0), section.u32_at(0));
                let _ = section.u16_at(usize::MAX);
                let _ = section.u32_at(usize::MAX);
            }
        }
        for name in SECTION_NAMES {
            let _ = content.section_by_name(name);
        }
        for name in ["", "STATUS", "stat", "STR ", "NOPE"] {
            let _ = content.section_by_name(name);
        }

        // 串号：代表性采样 + 两个哨兵 + 越界
        for id in (0..=u16::MAX).step_by(97) {
            let _ = content.string(id);
        }
        for id in [0u16, 1, 2, 1_375, 1_376, 1_377, NULL16, ABSENT16] {
            let _ = content.string(id);
        }
        let _ = content.strings().count();

        // opcode / term / aux：采样 + 越界
        for op in (0..u16::MAX).step_by(13) {
            if let Some(descriptor) = content.opcode(op) {
                let _ = descriptor.nslots();
                let _ = descriptor.fields().count();
                let _ = descriptor.field(usize::MAX);
            }
            let _ = content.opcode_name(op);
        }
        let _ = content.opcode_name(u16::MAX);
        for tid in (0..3_000u16).step_by(7) {
            if let Some(term) = content.term(tid) {
                let _ = term.slot(usize::MAX);
                let _ = term.nslots();
                let _ = term.slots_bytes().len();
            }
        }
        let _ = content.term(u16::MAX);
        for cell in (0..3_000u16).step_by(11) {
            let _ = content.aux(cell);
        }
        let _ = content.aux(u16::MAX);

        // 根指针 / 符号表
        for i in 0..content.root_count() + 2 {
            let _ = content.root(i);
        }
        let _ = content.root(usize::MAX);
        let _ = content.root_by_name("Map");
        for i in (0..800).step_by(3) {
            let _ = content.id_entry(i);
        }
        let _ = content.id_entry(usize::MAX);
        let _ = content.lookup("paperwork");
        let _ = content.lookup("");
        let _ = content.lookup_in("overfilled_inbox", EK_RELIC);
        let _ = content.resolve("paperwork");

        // 实体表：每张表采样 + 越界（含 u32::MAX，检查乘法不会溢出）
        for table in Table::ALL {
            let _ = content.rows(table).count();
            let _ = content.rows(table).last();
            for index in (0..420u32).step_by(5) {
                let _ = content.row(table, index);
            }
            let _ = content.row(table, u32::MAX);
            let _ = content.rows(table).count();
        }
        for index in (0..420u32).step_by(5) {
            let _ = content.card(index);
            let _ = content.status(index);
            let _ = content.enemy_action(index);
            let _ = content.encounter(index);
            let _ = content.relic(index);
            let _ = content.entity_id(Table::Card, index);
            let _ = content.entity_id(Table::EnemyAction, index);
        }
        let _ = content.card(u32::MAX);
        let _ = content.status(u32::MAX);
        let _ = content.enemy_action(u32::MAX);
        let _ = content.encounter(u32::MAX);
        let _ = content.relic(u32::MAX);
    }

    #[test]
    fn readers_never_panic_on_mutated_images() {
        let original = read_image(CORE_IMAGE);

        // 截断扫描（含 0 与 31 这类比头还短的）。
        let mut cut = 0usize;
        while cut < original.len() {
            exercise(&original[..cut]);
            cut += 997;
        }
        exercise(&original);

        // 头 + 目录区（前 272 字节）逐字节翻转：这里坏掉最危险。
        for at in 0..(HEADER_BYTES + SECTION_COUNT * DIRECTORY_ENTRY_BYTES) {
            let mut blob = original.clone();
            blob[at] ^= 0xFF;
            exercise(&blob);
        }

        // 段体内取样翻转（含 opcode/term/字符串池/五张表，都落在采样里）。
        for at in (272..original.len()).step_by(1013) {
            for mask in [0x01u8, 0x80, 0xFF] {
                let mut blob = original.clone();
                blob[at] ^= mask;
                exercise(&blob);
            }
        }
    }

    // ------------------------------------------------------ 真实镜像：对照表

    #[test]
    fn the_core_image_matches_the_manifest() {
        with_core(|content, blob| {
            assert_eq!(blob.len(), 85_616);
            assert_eq!(content.total_size() as usize, blob.len());
            assert_eq!(content.version(), FORMAT_VERSION);
            assert_eq!(content.flags(), 1);
            assert!(content.presentation_stripped());
            assert_eq!(content.schema_version(), 1);
            assert_eq!(content.content_hash(), 0xD107_5DE5);
            assert_eq!(content.section_count(), SECTION_COUNT);
            assert_eq!(content.section_count(), 20, "头里 nsec = 20（15 有名字 + 5 保留）");

            for (index, name, offset, bytes, count) in CORE_SECTIONS {
                let by_id = content
                    .section(index)
                    .unwrap_or_else(|| panic!("段 {index} ({name}) 取不到"));
                assert_eq!(by_id.offset, offset, "{name}.offset");
                assert_eq!(by_id.bytes, bytes, "{name}.bytes");
                assert_eq!(by_id.count, count, "{name}.count");
                assert_eq!(by_id.data.len(), bytes as usize, "{name}.data.len()");

                let by_name = content
                    .section_by_name(name)
                    .unwrap_or_else(|| panic!("段名 {name} 取不到"));
                assert_eq!(by_name, by_id, "{name} 按名取和按号取必须一样");
            }

            // 目录 + 各段正好铺满文件：第一段从目录尾（272）开始，最后一段接到文件尾。
            assert_eq!(content.section(S_STR).unwrap().offset, 272);
            assert_eq!(
                content.section(S_IDX).unwrap().end(),
                content.total_size() as u64
            );

            // 表的派生量（`reader.py --stats` 的同一批数字）。
            assert_eq!(content.string_count(), 1_375);
            assert_eq!(content.opcode_count(), 130);
            assert_eq!(content.term_count(), 2_143);
            assert_eq!(content.aux_cells(), 2_078);
            assert_eq!(content.root_count(), 16);
            assert_eq!(content.id_count(), 691);
            assert_eq!(content.section(S_TAGS).unwrap().count, 0);
            assert!(content.section(S_TAGS).unwrap().is_empty());

            // 段外越界：nsec 是 20，段号 20 起就没有了。
            assert!(content.section(20).is_none());
            assert!(content.section(usize::MAX).is_none());
            assert!(content.section_by_name("NOPE").is_none());
            assert!(content.section_by_name("").is_none());
            assert!(content.section_by_name("status").is_none(), "段名大小写敏感");
            assert!(
                content.section_by_name("STATUS").is_none(),
                "段名是 STAT；STATUS 只是行 schema 的键"
            );
        });
    }

    #[test]
    fn the_full_image_also_reads() {
        let blob = read_image(FULL_IMAGE);
        assert_eq!(blob.len(), 158_296);
        let content = Content::parse(&blob).expect("full 镜像必须能解析");
        assert_eq!(content.flags(), 0);
        assert!(!content.presentation_stripped());
        assert_eq!(content.content_hash(), 0xD107_5DE5);
        assert_eq!(content.section_count(), SECTION_COUNT);
        for (index, name, offset, bytes, count) in FULL_SECTIONS {
            let section = content
                .section(index)
                .unwrap_or_else(|| panic!("段 {index} ({name}) 取不到"));
            assert_eq!((section.offset, section.bytes, section.count), (offset, bytes, count));
            assert_eq!(content.section_by_name(name), Some(section));
        }
        assert_eq!(content.string_count(), 3_140);
        assert_eq!(content.opcode_count(), 139);
        assert_eq!(content.term_count(), 2_895);
        assert_eq!(content.aux_cells(), 3_810);
        assert_eq!(content.root_count(), 17);
        assert_eq!(content.id_count(), 691);
        assert_eq!(content.card(0).unwrap().row().table(), Table::Card);
        assert_eq!(content.validate(), Ok(()));
    }

    // ------------------------------------------------------ 真实镜像：内容

    #[test]
    fn strings_match_the_reference_reader() {
        // 期望值来自 `python reader.py out/content.core.rdcf --string N`（即 `reader.py` 读出的串）。
        const EXPECTED: [(u16, &str); 11] = [
            (0, ""),
            (1, "(unnamed)"),
            (2, "Action"),
            (3, "Actions"),
            (4, "AddFlat"),
            (5, "AddPerStack"),
            (10, "Balance"),
            (100, "Max"),
            (500, "city_normal_seal_08"),
            (1_000, "queue_bell"),
            (1_374, "your_number_is_fading"),
        ];
        with_core(|content, _| {
            for (id, want) in EXPECTED {
                assert_eq!(content.string(id), Some(want), "string({id})");
            }
            assert_eq!(content.string(1_375), Some("zero_cost"), "池里最后一条");
            assert_eq!(content.string(1_376), None, "串号上界是 string_count()");
            assert_eq!(content.string(NULL16), None, "0xFFFE 是哨兵，不是串号");
            assert_eq!(content.string(ABSENT16), None, "0xFFFF 是哨兵，不是串号");
            assert_eq!(content.string_count(), 1_375);
        });
    }

    #[test]
    fn the_string_pool_is_sorted_and_nul_terminated() {
        with_core(|content, _| {
            let stro = content.section(S_STRO).unwrap();
            let pool = content.section(S_STR).unwrap();
            assert_eq!(stro.count as usize, content.string_count() + 1);
            assert_eq!(pool.count as usize, content.string_count());

            let mut previous = "";
            let mut seen = 0usize;
            for (i, item) in content.strings().enumerate() {
                let text = item.unwrap_or_else(|| panic!("串号 {} 读不出来", i + 1));
                assert!(text >= previous, "池必须按字节序排：{previous:?} 之后是 {text:?}");
                assert!(!text.contains('\0'), "串里不该有 NUL");
                previous = text;
                seen += 1;
            }
            assert_eq!(seen, 1_375);
            assert_eq!(previous, "zero_cost", "按字节序最后一条");

            // STRO 严格递增、首项为 0、末项正好是池长。
            let mut offsets = Vec::new();
            for i in 0..(stro.bytes as usize / 4) {
                offsets.push(stro.u32_at(i).unwrap());
            }
            assert_eq!(offsets[0], 0);
            assert_eq!(*offsets.last().unwrap(), pool.bytes);
            assert!(offsets.windows(2).all(|w| w[0] < w[1]));
            // 每条串的最后一个字节是 NUL —— 去掉它就是正文。
            for off in offsets.iter().skip(1) {
                assert_eq!(pool.data[*off as usize - 1], 0);
            }
        });
    }

    #[test]
    fn entity_tables_decode_row_by_row() {
        with_core(|content, _| {
            // 行宽/格数：与 manifest 的 stride 和 rdcfmt 的 schema 一致。
            assert_eq!(Table::Card.stride(), 32);
            assert_eq!(Table::Status.stride(), 40);
            assert_eq!(Table::EnemyAction.stride(), 16);
            assert_eq!(Table::Encounter.stride(), 16);
            assert_eq!(Table::Relic.stride(), 12);
            assert_eq!(
                (CardRow::STRIDE, CardRow::CELLS),
                (32, 16),
                "CARD 16 格 = 32 B（15 格时 30 B 也取整到 32：那一格是免费的）"
            );
            assert_eq!((StatusRow::STRIDE, StatusRow::CELLS), (40, 20));
            assert_eq!((EactRow::STRIDE, EactRow::CELLS), (16, 7));
            assert_eq!((EnctRow::STRIDE, EnctRow::CELLS), (16, 8));
            // §156: REL gained a `Rarity` cell (5 -> 6). The 12-byte stride already had the room;
            // `align4(2 * 6) = 12` still matches, which the loop below re-checks for every table.
            assert_eq!((RelRow::STRIDE, RelRow::CELLS), (12, 6));
            for table in Table::ALL {
                assert_eq!(table.stride(), align4(2 * table.cells() as u32));
                assert_eq!(
                    table.stride(),
                    section_stride(table.section_id()),
                    "{table:?} 的段 stride 必须与行 stride 一致"
                );
                assert_eq!(content.row(table, 0).unwrap().bytes().len(), table.stride() as usize);
            }

            // 行数 = IDX 里该类实体的条数 = manifest 的 count。
            assert_eq!(content.rows(Table::Card).count(), 62);
            assert_eq!(content.rows(Table::Status).count(), 23);
            assert_eq!(content.rows(Table::EnemyAction).count(), 394);
            assert_eq!(content.rows(Table::Encounter).count(), 109);
            assert_eq!(content.rows(Table::Relic).count(), 49);
            assert_eq!(content.rows(Table::Card).last().unwrap().index(), 61);

            // 越界一律 `None`（含 u32::MAX：行号×行宽会溢出，必须走 checked）。
            assert!(content.card(62).is_none());
            assert!(content.status(23).is_none());
            assert!(content.enemy_action(394).is_none());
            assert!(content.encounter(109).is_none());
            assert!(content.relic(49).is_none());
            assert!(content.card(u32::MAX).is_none());
            assert!(content.status(u32::MAX).is_none());
            assert!(content.enemy_action(u32::MAX).is_none());
            assert!(content.encounter(u32::MAX).is_none());
            assert!(content.relic(u32::MAX).is_none());

            // 具体行：格值抄自 `reader.py`（`--entity`）读出来的同一行。
            let card = content.card(0).unwrap();
            assert_eq!(card.index(), 0);
            assert_eq!(card.row().u16_len(), 16, "16 格，没有对齐填充");
            assert_eq!(card.id(), 950);
            assert_eq!(content.string(card.id()), Some("paper_cut"));
            assert_eq!(card.program(), 4);
            assert_eq!(card.tags(), 8);
            assert_eq!(card.costs(), 10);
            assert_eq!(card.lifecycle_programs(), 11);
            assert_eq!(card.play_condition(), ABSENT16);
            assert_eq!(card.queue_on_play(), ABSENT16);
            assert_eq!(card.retain_in_hand_on_turn_end(), BOOL_FALSE);
            assert_eq!(card.is_action(), BOOL_ABSENT, "键存在且为 false ≠ 键不存在");
            assert_eq!(card.package_id(), 1_157);
            assert_eq!(card.turn_end_hand_destination_zone(), 52);
            assert_eq!(card.played_card_destination_zone(), 52);
            assert_eq!(card.extra(), NULL16);
            assert_eq!(content.entity_id(Table::Card, 0), Some("paper_cut"));
            assert_eq!(content.entity_id(Table::Card, 42), Some("overfilled_inbox"));
            assert_eq!(
                content.entity_id(Table::Card, 61),
                Some("approved_for_disposal+")
            );
            assert_eq!(content.entity_id(Table::Card, 62), None);

            let status = content.status(0).unwrap();
            assert_eq!(content.string(status.id()), Some("paperwork"));
            assert_eq!(status.name_key(), ABSENT16);
            assert_eq!(status.polarity(), 43);
            assert_eq!(status.stacking_behavior(), 108);
            assert_eq!(status.tags(), 264);
            assert_eq!(status.triggers(), 58);
            assert_eq!(status.uses_stacks(), BOOL_TRUE);
            assert_eq!(status.uses_duration(), BOOL_FALSE);
            assert_eq!(status.uses_charges(), BOOL_FALSE);
            assert_eq!(status.extra(), NULL16);
            assert_eq!(content.entity_id(Table::Status, 22), Some("sustained"));

            let action = content.enemy_action(0).unwrap();
            assert_eq!(
                content.entity_id(Table::EnemyAction, 0),
                Some("a_very_official_line.shuffle_forward")
            );
            assert_eq!(action.intent(), 422);
            assert_eq!(action.program(), 425);
            assert_eq!(action.extra(), NULL16);
            assert_eq!(
                content.entity_id(Table::EnemyAction, 393),
                Some("sealed_spear.long_reach")
            );

            let encounter = content.encounter(0).unwrap();
            assert_eq!(content.entity_id(Table::Encounter, 0), Some("city_easy_01"));
            assert_eq!(encounter.enemies(), 767);
            assert_eq!(encounter.hero_resources(), 769);
            assert_eq!(encounter.hero_starting_statuses(), 771);
            assert_eq!(encounter.triggered_effects(), 58);
            assert_eq!(encounter.hero_display_name(), ABSENT16);
            assert_eq!(
                encounter.cards_drawn_per_turn(),
                NULL_INT,
                "32769 = -32767 = 「键存在且为 null」"
            );
            assert_eq!(encounter.extra(), NULL16);
            assert_eq!(
                content.entity_id(Table::Encounter, 108),
                Some("city_easy_form_06")
            );

            let relic = content.relic(0).unwrap();
            assert_eq!(content.entity_id(Table::Relic, 0), Some("self_inking_stamp"));
            assert_eq!(relic.display_name(), ABSENT16);
            assert_eq!(relic.run_programs(), 1_219);
            assert_eq!(relic.combat_rules(), 58);
            assert_eq!(relic.extra(), NULL16);
            assert_eq!(content.entity_id(Table::Relic, 33), Some("overfilled_inbox"));
            assert_eq!(
                content.entity_id(Table::Relic, 48),
                Some("bottomless_inbox_tray")
            );

            // 表不对 → 收窄失败。
            let row = content.row(Table::Card, 0).unwrap();
            assert!(CardRow::new(row).is_some());
            assert!(RelRow::new(row).is_none());
            assert_eq!(Row::from(content.card(0).unwrap()), row);
        });
    }

    #[test]
    fn row_accessors_agree_with_the_written_schema() {
        with_core(|content, _| {
            assert_eq!(Table::Card.schema_name(), "CARD");
            assert_eq!(Table::Status.schema_name(), "STATUS");
            assert_eq!(Table::Card.name(), "CARD");
            assert_eq!(Table::Status.name(), "STAT");
            assert_eq!(Table::Card.entity_kind(), EK_CARD);
            assert_eq!(Table::from_entity_kind(EK_RELIC), Some(Table::Relic));
            assert_eq!(Table::from_entity_kind(EK_EVENT), None);
            assert_eq!(Table::from_entity_kind(0), None);
            assert_eq!(entity_kind_name(EK_ENCOUNTER), Some("encounter"));
            assert_eq!(entity_kind_name(0), None);

            // schema 的格序与 `rdcfmt.ROW_SCHEMAS` 逐项相同（键名、类别、包装 flags）。
            assert_eq!(CARD_SCHEMA[0], cell("Id", F_STR, 0));
            assert_eq!(CARD_SCHEMA[14], cell("Rarity", F_STR, 0));
            assert_eq!(CARD_SCHEMA[15], cell("extra", F_TERM, 0));
            assert_eq!(STATUS_SCHEMA[19], cell("extra", F_TERM, 0));
            assert_eq!(ENCT_SCHEMA[0], cell("Id", F_STR, FLAG_WRAP_UPPER));
            assert_eq!(ENCT_SCHEMA[6], cell("CardsDrawnPerTurn", F_INT, 0));
            assert_eq!(EACT_SCHEMA[5], cell("Program", F_TERM, 0));
            assert_eq!(REL_SCHEMA[2], cell("RunPrograms", F_TERM, 0));
            assert_eq!(Table::Card.schema().len(), 16);
            assert_eq!(Table::Status.schema().len(), 20);

            // 命名 getter 取的就是 schema 里那一格。
            let card = content.card(0).unwrap();
            let row = card.row();
            for (name, got) in [
                ("Id", card.id()),
                ("Program", card.program()),
                ("Tags", card.tags()),
                ("Costs", card.costs()),
                ("LifecyclePrograms", card.lifecycle_programs()),
                ("PlayCondition", card.play_condition()),
                ("QueueOnPlay", card.queue_on_play()),
                ("RetainInHandOnTurnEnd", card.retain_in_hand_on_turn_end()),
                ("IsAction", card.is_action()),
                ("NameKey", card.name_key()),
                ("DescriptionKey", card.description_key()),
                ("PackageId", card.package_id()),
                ("TurnEndHandDestinationZone", card.turn_end_hand_destination_zone()),
                ("PlayedCardDestinationZone", card.played_card_destination_zone()),
                ("Rarity", card.rarity()),
                ("extra", card.extra()),
            ] {
                assert_eq!(row.cell_by_name(name), Some(got), "CARD.{name}");
            }

            let status = content.status(0).unwrap();
            let row = status.row();
            for (name, got) in [
                ("Id", status.id()),
                ("NameKey", status.name_key()),
                ("DescriptionKey", status.description_key()),
                ("PackageId", status.package_id()),
                ("Polarity", status.polarity()),
                ("StackingBehavior", status.stacking_behavior()),
                ("Tags", status.tags()),
                ("Triggers", status.triggers()),
                ("PassiveModifiers", status.passive_modifiers()),
                ("CombatRules", status.combat_rules()),
                ("DeathPrevention", status.death_prevention()),
                ("DebuffBlock", status.debuff_block()),
                ("IncomingStatusDelay", status.incoming_status_delay()),
                ("Disclosure", status.disclosure()),
                ("Prevention", status.prevention()),
                ("Amplification", status.amplification()),
                ("UsesStacks", status.uses_stacks()),
                ("UsesDuration", status.uses_duration()),
                ("UsesCharges", status.uses_charges()),
                ("extra", status.extra()),
            ] {
                assert_eq!(row.cell_by_name(name), Some(got), "STATUS.{name}");
            }

            let action = content.enemy_action(0).unwrap();
            for (name, got) in [
                ("Id", action.id()),
                ("NameKey", action.name_key()),
                ("DescriptionKey", action.description_key()),
                ("PackageId", action.package_id()),
                ("Intent", action.intent()),
                ("Program", action.program()),
                ("extra", action.extra()),
            ] {
                assert_eq!(action.row().cell_by_name(name), Some(got), "EACT.{name}");
            }

            let encounter = content.encounter(0).unwrap();
            for (name, got) in [
                ("Id", encounter.id()),
                ("Enemies", encounter.enemies()),
                ("HeroResources", encounter.hero_resources()),
                ("HeroStartingStatuses", encounter.hero_starting_statuses()),
                ("TriggeredEffects", encounter.triggered_effects()),
                ("HeroDisplayName", encounter.hero_display_name()),
                ("CardsDrawnPerTurn", encounter.cards_drawn_per_turn()),
                ("extra", encounter.extra()),
            ] {
                assert_eq!(encounter.row().cell_by_name(name), Some(got), "ENCT.{name}");
            }

            let relic = content.relic(0).unwrap();
            for (name, got) in [
                ("Id", relic.id()),
                ("DisplayName", relic.display_name()),
                ("RunPrograms", relic.run_programs()),
                ("CombatRules", relic.combat_rules()),
                ("extra", relic.extra()),
            ] {
                assert_eq!(relic.row().cell_by_name(name), Some(got), "REL.{name}");
            }

            // schema 里没有的键 / 越界格。
            assert_eq!(card.row().cell_by_name("Nope"), None);
            assert_eq!(card.row().cell_index("Rarity"), Some(14));
            assert_eq!(card.row().cell_index("extra"), Some(15));
            assert_eq!(card.row().cell(16), None, "第 16 格越界（16 格都在行内）");
            assert_eq!(card.row().cell(u32::MAX), None);
            assert_eq!(card.row().cell_kind(0), Some(F_STR));
            assert_eq!(card.row().cell_kind(99), None);
        });
    }

    #[test]
    fn the_id_index_is_sorted_and_lookup_matches_the_reference() {
        with_core(|content, _| {
            assert_eq!(content.id_count(), 691);
            assert!(content.id_entry(691).is_none());
            assert!(content.id_entry(usize::MAX).is_none());

            // 全表按 id 字符串非递减（`reader.py` 直接靠这一点二分）。
            let mut previous = "";
            for i in 0..content.id_count() {
                let entry = content.id_entry(i).unwrap();
                assert!(entry.position == i as u32);
                assert!(entry.id >= previous, "IDX[{i}] 顺序坏了");
                assert_eq!(entry.flags, 0, "真实镜像的 flags 字节全是 0");
                previous = entry.id;
            }

            assert_eq!(content.id_entry(0).unwrap().id, "Bureaucrat");
            assert_eq!(content.id_entry(0).unwrap().entity_kind, EK_CHARACTER);
            // 同一个 index 被两个字符 id（只差大小写）指着。
            assert_eq!(content.id_entry(75).unwrap().id, "bureaucrat");
            assert_eq!(content.id_entry(75).unwrap().index, 0);

            let paperwork = content.lookup("paperwork").unwrap();
            assert_eq!(paperwork.entity_kind, EK_STATUS);
            assert_eq!(paperwork.index, 0);
            assert_eq!(content.id_entry(paperwork.position as usize), Some(paperwork));
            assert!(content.lookup("NOPE").is_none());
            assert!(content.lookup("").is_none());

            // 同一个 id 既是卡牌又是遗物：`lookup` 取最靠前的一条（= reader.py 的 setdefault）。
            let first = content.lookup("overfilled_inbox").unwrap();
            assert_eq!(first.position, 479);
            assert_eq!((first.entity_kind, first.index), (EK_CARD, 42));
            let second = content.id_entry(480).unwrap();
            assert_eq!(second.id, "overfilled_inbox");
            assert_eq!((second.entity_kind, second.index), (EK_RELIC, 33));
            assert_eq!(content.lookup_in("overfilled_inbox", EK_RELIC), Some(second));
            assert_eq!(content.lookup_in("overfilled_inbox", EK_CARD), Some(first));
            assert_eq!(content.lookup_in("overfilled_inbox", EK_MAPNODE), None);

            // id → 行。
            let row = content.resolve("paperwork").unwrap();
            assert_eq!(row.table(), Table::Status);
            assert_eq!(row.index(), 0);
            assert!(content.resolve("NOPE").is_none());
            // `Bureaucrat` 是 character，没有定长表。
            assert!(content.resolve("Bureaucrat").is_none());
        });
    }

    #[test]
    fn every_entity_id_resolves_to_its_own_row() {
        with_core(|content, _| {
            let mut seen = [Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new()];
            for i in 0..content.id_count() {
                let entry = content.id_entry(i).unwrap();
                let Some(table) = Table::from_entity_kind(entry.entity_kind) else {
                    continue;
                };
                let row = content
                    .row(table, entry.index as u32)
                    .unwrap_or_else(|| panic!("{}/{} 没有对应的行", entry.id, table.name()));
                assert_eq!(row.table(), table);
                assert_eq!(row.index(), entry.index as u32);
                let row_id = content
                    .entity_id(table, entry.index as u32)
                    .unwrap_or_else(|| panic!("{}/{} 的 Id 格读不出来", entry.id, table.name()));
                assert_eq!(row_id, entry.id, "IDX 与表里的 Id 必须一致");
                seen[entry.entity_kind as usize - 1].push(entry.index);
            }

            // 每类实体的 index 恰好把表铺满：0..count 一个不多一个不少。
            for (i, table) in Table::ALL.into_iter().enumerate() {
                let mut indices = seen[i].clone();
                indices.sort_unstable();
                let expected: Vec<u16> = (0..content.section(table.section_id()).unwrap().count as u16)
                    .collect();
                assert_eq!(indices, expected, "{} 的索引不连续", table.name());
                assert_eq!(indices.len(), content.rows(table).count());
            }
        });
    }

    #[test]
    fn opcodes_terms_roots_and_aux_decode() {
        with_core(|content, _| {
            assert_eq!(content.opcode_count(), 130);
            assert_eq!(content.term_count(), 2_143);
            assert_eq!(content.aux_cells(), 2_078);
            assert_eq!(content.root_count(), 16);

            // 保留 opcode：名字是空串。字段数由各自的固定语义决定（op 0 无字段、1..7 各一个、
            // 8..15 是空洞）。
            for op in 0..=15u16 {
                let descriptor = content.opcode(op).unwrap();
                assert_eq!(descriptor.name_str, 0, "保留 opcode {op} 没有名字");
                assert_eq!(content.opcode_name(op), Some(""));
            }
            assert_eq!(content.opcode(OP_NULL).unwrap().nfields(), 0);
            assert_eq!(content.opcode(OP_NULL).unwrap().nslots(), Some(0));
            assert_eq!(content.opcode(OP_STR).unwrap().nfields(), 1);
            assert_eq!(content.opcode(OP_STR).unwrap().field(0).unwrap().kind(), F_STR);
            assert_eq!(content.opcode(OP_ARR).unwrap().nslots(), Some(2), "TERMLIST 占两槽");
            assert_eq!(
                content.opcode(OP_JSON).unwrap().field(0).unwrap().kind(),
                F_JSON
            );
            assert_eq!(
                content.opcode(OP_WRAP_LOWER).unwrap().field(0).unwrap().flags(),
                FLAG_WRAP_LOWER
            );
            assert_eq!(
                content.opcode(OP_WRAP_UPPER).unwrap().field(0).unwrap().flags(),
                FLAG_WRAP_UPPER
            );
            for op in 8..=15u16 {
                let hole = content.opcode(op).unwrap();
                assert_eq!((hole.nfields(), hole.nslots()), (0, Some(0)));
                assert_eq!(hole.opclass, OPCLASS_IR, "空洞的 opclass 是 0");
            }
            // 0..7 的 opclass 是"普通对象"，8..15 才是 IR —— 所以 op < 16 必须先特判语义。
            assert_eq!(content.opcode(OP_NULL).unwrap().opclass, OPCLASS_GENERIC);
            assert_eq!(content.opcode(OP_STR).unwrap().opclass, OPCLASS_GENERIC);
            assert_eq!(content.opcode(OP_WRAP_UPPER).unwrap().opclass, OPCLASS_GENERIC);

            let add = content.opcode(16).unwrap();
            assert_eq!(content.opcode_name(16), Some("add"));
            assert!(add.is_ir());
            assert_eq!(add.nfields(), 2);
            assert_eq!(add.nslots(), Some(2));
            assert_eq!(content.string(add.field(0).unwrap().name_str()), Some("Left"));
            assert_eq!(content.string(add.field(1).unwrap().name_str()), Some("Right"));
            assert_eq!(add.field(0).unwrap().kind(), F_TERM);
            assert_eq!(add.field(0).unwrap().slots(), Some(1));
            assert_eq!(add.fields().count(), 2);
            assert!(add.field(2).is_none());
            assert!(add.field(usize::MAX).is_none());

            // 带包装 flag / 双槽字段的例子。
            let add_status = content.opcode(52).unwrap();
            assert_eq!(content.opcode_name(52), Some("node.applyStatus"));
            assert_eq!(add_status.nfields(), 7);
            assert_eq!(add_status.nslots(), Some(8));
            let status_field = add_status
                .fields()
                .find(|f| content.string(f.name_str()) == Some("StatusDefinitionId"))
                .unwrap();
            assert_eq!(status_field.kind(), F_STR);
            assert_eq!(status_field.flags(), FLAG_WRAP_LOWER);

            // 普通对象形状（opclass = 1），nslots 由字段类别求和（TERMLIST 占 2 槽）。
            let shape = content.opcode(129).unwrap();
            assert_eq!(content.opcode_name(129), Some("_obj"));
            assert!(!shape.is_ir());
            assert_eq!((shape.nfields(), shape.nslots()), (2, Some(3)));

            // opcode 越界。
            assert!(content.opcode(130).is_none());
            assert!(content.opcode(u16::MAX).is_none());
            assert!(content.opcode_name(130).is_none());

            // term：tid 0 是 `_null`（所以 0 是合法且永远存在的 term）。
            let null = content.term(0).unwrap();
            assert_eq!((null.id, null.op), (0, OP_NULL));
            assert_eq!(null.nslots(), 0);
            assert!(null.slots_bytes().is_empty());
            assert_eq!(content.term(0).unwrap().slot(0), None);

            let constant = content.term(1).unwrap();
            assert_eq!(constant.op, 27);
            assert_eq!(content.opcode_name(constant.op), Some("const"));
            assert_eq!(constant.nslots(), 1);
            assert_eq!(constant.slot(0), Some(6));
            assert_eq!(constant.slot(1), None);

            let selector = content.term(2).unwrap();
            assert_eq!(selector.op, 80);
            assert_eq!(content.opcode_name(selector.op), Some("sel.eventTarget"));
            assert_eq!(
                [selector.slot(0), selector.slot(1), selector.slot(2)],
                [Some(213), Some(70), None]
            );

            let last = content.term(2_142).unwrap();
            assert_eq!(last.op, 119);
            assert_eq!(content.opcode_name(last.op), Some("_obj"));
            assert_eq!([last.slot(0), last.slot(1)], [Some(6), Some(1)]);
            assert!(content.term(2_143).is_none(), "term id 上界 = term_count()");
            assert!(content.term(u16::MAX).is_none());

            // AUX 的列表体。
            assert_eq!(content.aux(0), Some(5));
            assert_eq!(content.aux(7), Some(7));
            assert_eq!(content.aux(2_078), None);
            assert_eq!(content.aux(u16::MAX), None);

            // ROOT：顶层键 → term。
            assert_eq!(content.root_count(), 16);
            assert_eq!(content.root_by_name("Map"), Some(2_124));
            assert_eq!(content.root_by_name("Events"), Some(1_902));
            assert_eq!(content.root_by_name("Start"), Some(1_440));
            assert_eq!(content.root_by_name("Deck"), Some(1_447));
            assert_eq!(
                content.root_by_name("MapGeneration"),
                Some(0),
                "顶层键可以指向 `_null`（tid 0）"
            );
            assert!(content.root_by_name("Presentation").is_none(), "core 镜像剥了表现层");
            assert_eq!(content.root(0).unwrap().key, "Balance");
            assert_eq!(content.root(0).unwrap().term, 1_438);
            assert!(content.root(16).is_none());
            assert!(content.root(usize::MAX).is_none());
            // 每个根指针都指向一条真实存在的 term。
            for i in 0..content.root_count() {
                let root = content.root(i).unwrap();
                assert!(content.term(root.term).is_some(), "根 {} 悬空", root.key);
            }
        });
    }

    // ------------------------------------------------------------ 结构自检

    /// `CARD.Tags` is a wrapped strlist (`STRLIST(wrap)`, `layout.txt` line 37), so reading it means
    /// looking through the wrapper. Without this the reward screen offers `slimed` -- a junk status
    /// card -- as a card you can pick.
    #[test]
    fn card_tags_are_readable_and_a_junk_card_is_not_a_reward() {
        let bytes = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = Content::parse(&bytes).expect("the image parses");

        // `inv:§3.1`: strike is attack/basic/strike, defend is skill/basic/defend.
        for tag in ["attack", "basic", "strike"] {
            assert_eq!(content.card_has_tag("strike", tag), Some(true), "strike/{tag}");
        }
        assert_eq!(content.card_has_tag("strike", "skill"), Some(false));
        assert_eq!(content.card_has_tag("defend", "skill"), Some(true));
        assert_eq!(content.card_has_tag("defend", "attack"), Some(false));
        // The upgraded rows keep their base card's tags.
        assert_eq!(content.card_has_tag("strike+", "attack"), Some(true));

        // The one that mattered: `slimed` is a status card, so a reward must be able to exclude it.
        assert_eq!(content.card_has_tag("slimed", "status"), Some(true));
        assert_eq!(content.card_has_tag("slimed", "attack"), Some(false));

        // A card that is not in the image is `None`, not `Some(false)`.
        assert_eq!(content.card_has_tag("no_such_card", "attack"), None);
    }

    /// `Rarity` is cell 14 of `CARD`, it cost no layout (`align4(2*15) == align4(2*16) == 32`), and
    /// it moved `FORMAT_VERSION` to 2 -- a schema change has to be visible to a reader whose cell
    /// table is fixed, or an old image decodes as garbage instead of failing.
    #[test]
    fn card_rarity_is_readable_and_the_schema_moved_the_version() {
        let bytes = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = Content::parse(&bytes).expect("the image parses");
        assert_eq!(content.card_rarity("strike"), Some("Basic"));
        assert_eq!(content.card_rarity("bash"), Some("Basic"));
        assert_eq!(content.card_rarity("slimed"), Some("Status"));
        assert_eq!(content.card_rarity("no_such_card"), None);
        assert_eq!((CardRow::STRIDE, CardRow::CELLS), (32, 16));
        assert_eq!(FORMAT_VERSION, 4);
        assert_eq!(content.version(), FORMAT_VERSION);
        // The roguedeck image has no `Rarity` key at all: the cell is there and reads as absent,
        // which is `None` rather than an error.
        let core = std::fs::read(CORE_IMAGE).expect("the roguedeck image");
        let core = Content::parse(&core).expect("parses");
        assert_eq!(core.card_rarity("paper_cut"), None);
    }

    /// **No encounter places more enemies than a fight allows** (`port-plan.md` §140).
    ///
    /// The kernel enforces the cap on *summons* (`node.createCombatant`); this pins the other half --
    /// the content may not author a fight the player cannot see or target.
    #[test]
    fn no_encounter_places_more_enemies_than_a_fight_allows() {
        let bytes = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = Content::parse(&bytes).expect("the image parses");
        let mut worst = 0usize;
        for row in content.rows(Table::Encounter) {
            let Ok(enemies) = content.encounter_enemies(row.index()) else {
                continue;
            };
            worst = worst.max(enemies.len());
        }
        assert!(
            worst <= crate::state::MAX_ENEMIES_IN_FIGHT,
            "an encounter places {worst} enemies; the cap is {}",
            crate::state::MAX_ENEMIES_IN_FIGHT
        );
        assert!(worst >= 1, "the image has encounters at all");
    }

    /// `EncounterTables` is the document's own statement of the two pools (`inv:§5.2/§5.3`), and it
    /// had no reader until the elite needed one: the run layer could only pick "any encounter".
    ///
    /// §158: this test had **lost its `#[test]`** -- an earlier edit anchored on this doc comment
    /// and swallowed the attribute of its own function, so `no_encounter_places_more_enemies_than_a
    /// _fight_allows` above carried two `#[test]`s and this function carried none. It compiled, ran
    /// zero times, and reported nothing. `cargo test` warned `duplicated attribute` / `never used`
    /// for a whole release; the fix is the missing attribute, not a silencer.
    ///
    /// The body had also gone **stale**: it pinned "the weak pool has three entries", which was true
    /// when it was written and had been seven for two releases. So the shape was replaced too -- it
    /// now checks the *structure* rather than today's numbers:
    ///
    /// 1. every id in a pool is a real `ENCT` row;
    /// 2. the ten pools **partition** the encounter table -- no encounter is unreachable, and none
    ///    is in two pools (a normal encounter cannot also be an elite);
    /// 3. every act has a weak / elite / boss pool, because the run layer asks for them by name and
    ///    a missing one would fall back to something.
    #[test]
    fn the_encounter_pools_are_readable() {
        let bytes = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = Content::parse(&bytes).expect("the image parses");
        // The ten names the run layer can ask for (`rd-wasm`'s act -> pool mapping). Hard-coded on
        // purpose: the pool names live in the caller, so a test that discovered them dynamically
        // would not notice a pool the caller asks for and the content lost.
        const POOLS: [&str; 9] = [
            "Weak", "Elite", "Boss", "Weak2", "Elite2", "Boss2", "Weak3", "Elite3", "Boss3",
        ];
        let mut seen: Vec<&str> = Vec::new();
        for name in POOLS {
            let pool = content
                .encounter_pool(name)
                .unwrap_or_else(|| panic!("the content has no `{name}` pool"));
            let ids: Vec<&str> = pool.iter().filter(|id| !id.is_empty()).copied().collect();
            assert!(!ids.is_empty(), "{name} is empty");
            for id in ids {
                assert!(
                    (0..content.rows(Table::Encounter).count()).any(|index| {
                        content.entity_id(Table::Encounter, index as u32) == Some(id)
                    }),
                    "{name} names `{id}`, which is not an ENCT row"
                );
                assert!(
                    !seen.contains(&id),
                    "`{id}` is in two pools -- an encounter belongs to exactly one"
                );
                seen.push(id);
            }
        }
        let total = content.rows(Table::Encounter).count();
        assert_eq!(
            seen.len(),
            total,
            "{} of {total} encounters are reachable: {:?}",
            seen.len(),
            seen
        );
        // A pool the document does not have is `None`, not an empty set.
        assert_eq!(content.encounter_pool("Sideboard"), None);
    }

    /// §144：三个关键字的**机制格**真的在镜像里，而且 tag 与机制一致。
    ///
    /// 这一条盯的是"内容说了，但内核读的那一格没写"——那种卡在游戏里就是一张普通牌，
    /// 而且**看不出来**（tag 只影响描述文本）。`native/sts_content_check.py` 的 `[6d]`
    /// 是同一句话的第二张嘴：那边查文档，这边查二进制。
    #[test]
    fn the_keyword_cells_are_in_the_image() {
        let bytes = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = Content::parse(&bytes).expect("the image parses");

        // Ethereal = TurnEndHandDestinationZone = ExhaustPile（参考 `CardZoneEffects.cs:427`）。
        assert_eq!(
            content.card_turn_end_zone("sentinel"),
            Some("ExhaustPile"),
            "sentinel 是 Ethereal"
        );
        assert_eq!(
            content.card_retains_in_hand("sentinel"),
            Some(false),
            "Ethereal 不是 Retain —— 两格必须各自成立"
        );

        // Retain = RetainInHandOnTurnEnd = true。
        assert_eq!(
            content.card_retains_in_hand("patient_guard"),
            Some(true),
            "patient_guard 是 Retain"
        );
        assert_eq!(
            content.card_turn_end_zone("patient_guard"),
            Some("DiscardPile"),
            "Retain 卡不消耗自己"
        );

        // 普通卡：两格都是默认值（成对，避免"读什么都返回同一个值"）。
        assert_eq!(content.card_retains_in_hand("strike"), Some(false));
        assert_eq!(content.card_turn_end_zone("strike"), Some("DiscardPile"));

        // 不在镜像里的卡：三态里"读不出来"这一态必须与 false 分得开。
        assert_eq!(content.card_retains_in_hand("no_such_card_"), None);
        assert_eq!(content.card_turn_end_zone("no_such_card_"), None);

        // Innate 在 **tag** 上（`battle.rs::move_innate_cards_to_top` 读的就是它）。
        assert_eq!(
            content.card_has_tag("swift_strike", "innate"),
            Some(true),
            "swift_strike 是 Innate"
        );
        assert_eq!(content.card_has_tag("strike", "innate"), Some(false));

        // §146：X 费牌的 tag 也必须真的在镜像里 —— 它是 `play.rs` 认 X 费的**唯一**判据。
        assert_eq!(
            content.card_has_tag("whirlwind", "x_cost"),
            Some(true),
            "whirlwind 是 X 费牌"
        );
        assert_eq!(content.card_rarity("whirlwind"), Some("Uncommon"));
        assert_eq!(content.card_has_tag("strike", "x_cost"), Some(false));
    }

    /// The `?` room's events, read out of the image: ids, body text, and both choices.
    #[test]
    fn the_unknown_room_events_are_readable() {
        let bytes = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = Content::parse(&bytes).expect("the image parses");
        assert_eq!(
            content.event_count(),
            9,
            "nine events: six for act 1, three for act 2, three for act 3 -- with `EventTables` \
             sharing `purification_shrine` (§133 / §143)"
        );
        let mut ids = Vec::new();
        for index in 0..content.event_count() {
            let (id, text, choices) = content.event(index).expect("event {index}");
            ids.push(id);
            assert!(!text.is_empty(), "{id} has no body text");
            assert!(!choices[0].label.is_empty(), "{id} choice 0 has no label");
            assert!(!choices[1].label.is_empty(), "{id} choice 1 has no label");
            // The **shape** of the vocabulary is the run layer's business (`EventEffect::parse`);
            // what is pinned here is that the image carries none of the outside: a parsing rule
            // this test cannot see is a rule the content gate alone would have to defend.
            let bare = [
                "heal",
                "gold",
                "damage",
                "max_hp",
                "nothing",
                "remove_card",
                "upgrade_card",
                "transform_card",
            ];
            for choice in &choices {
                let effect = choice.effect;
                let inside = bare.contains(&effect)
                    || (effect.starts_with("curse:") && effect.len() > "curse:".len())
                    || (effect.starts_with("relic:") && effect.len() > "relic:".len());
                assert!(inside, "{id}: unknown effect {effect:?}");
            }
        }
        ids.sort_unstable();
        assert_eq!(
            ids,
            vec![
                "ancient_forge",
                "ancient_writing",
                "forgotten_altar",
                "golden_idol",
                "old_shrine",
                "purification_shrine",
                "scrap_pile",
                "shining_light",
                "wandering_merchant"
            ]
        );
        // Spot-check one: the golden idol pays 30 gold, and leaving it does nothing.
        let index = (0..content.event_count())
            .find(|index| content.event(*index).map(|e| e.0) == Some("golden_idol"))
            .expect("golden_idol");
        let (_, _, choices) = content.event(index).unwrap();
        assert_eq!(choices[0].effect, "gold");
        assert_eq!(choices[0].amount, 30);
        assert_eq!(choices[1].effect, "nothing");

        // §143: the three new choices really carry the new vocabulary **out of the binary**, so a
        // writer that quietly dropped a colon would be caught here and not by a dead button.
        let effect_of = |id: &str| -> std::vec::Vec<std::string::String> {
            let index = (0..content.event_count())
                .find(|index| content.event(*index).map(|e| e.0) == Some(id))
                .unwrap_or_else(|| panic!("{id} must be in the image"));
            let (_, _, choices) = content.event(index).expect("event");
            std::vec![
                std::string::String::from(choices[0].effect),
                std::string::String::from(choices[1].effect),
            ]
        };
        assert_eq!(
            effect_of("ancient_writing")[0],
            "upgrade_card",
            "the upgrade event must survive the round trip"
        );
        assert_eq!(
            effect_of("forgotten_altar")[0],
            "curse:injury",
            "a `kind:payload` effect must survive the round trip **with its payload**"
        );
        assert_eq!(effect_of("purification_shrine")[0], "remove_card");

        // The roguedeck image has **no** `UnknownRooms` key, so it has no events -- not an error.
        let core = std::fs::read(CORE_IMAGE).expect("the roguedeck image");
        let core = Content::parse(&core).expect("parses");
        assert_eq!(core.event_count(), 0, "roguedeck has no events");
    }

    /// The twenty potions, read out of the image, with the **closed effect vocabulary** enforced:
    /// a potion whose effect the run layer cannot apply must fail here rather than do nothing.
    #[test]
    fn the_potions_are_readable() {
        let bytes = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = Content::parse(&bytes).expect("the image parses");
        assert_eq!(
            content.potion_count(),
            20,
            "§158: eleven after §157, plus the nine that need no new mechanic"
        );
        let mut ids = Vec::new();
        let mut bands = [0usize; 3];
        for index in 0..content.potion_count() {
            let potion = content.potion(index).expect("potion {index}");
            ids.push(potion.id);
            assert!(!potion.name.is_empty(), "{} has no name", potion.id);
            // §158: an effect is a **comma-separated list of atoms**, `kind` or `kind:<payload>`.
            // Flex Potion needs it: "+5 Strength" *and* "at the end of the turn, lose 5 Strength" are
            // two different statuses and the row has one `Effect` cell.
            let atoms: Vec<(&str, Option<&str>)> = potion
                .effect
                .split(',')
                .map(|atom| match atom.split_once(':') {
                    Some((kind, payload)) => (kind, Some(payload)),
                    None => (atom, None),
                })
                .collect();
            for (kind, payload) in &atoms {
                assert!(
                    [
                        "combat_damage",
                        "combat_block",
                        "combat_energy",
                        "combat_heal_percent",
                        "combat_draw",
                        "combat_damage_all",
                        "combat_status",
                        "combat_status_target",
                        // §157: the effects about the **run** rather than the fight.
                        "max_hp",
                        "potion_fill",
                    ]
                    .contains(kind),
                    "{}: unknown effect {:?}",
                    potion.id,
                    potion.effect
                );
                // The payload form is only for the two status kinds, and only those need it.
                assert_eq!(
                    payload.is_some(),
                    kind.starts_with("combat_status"),
                    "{}: payload presence does not match {:?}",
                    potion.id,
                    kind
                );
            }
            // `potion_fill` is the only atom that reads no amount (it fills whatever is empty), so
            // the rule is per-atom rather than per-row: a flat "amount > 0" would have forced a
            // meaningless `1` into Entropic Brew's row and pinned nothing.
            if atoms.iter().all(|(kind, _)| *kind == "potion_fill") {
                assert_eq!(potion.amount, 0, "{}: takes no amount", potion.id);
            } else {
                assert!(potion.amount > 0, "{} has no amount", potion.id);
            }
            bands[match potion.rarity {
                "Common" => 0,
                "Uncommon" => 1,
                "Rare" => 2,
                other => panic!("{}: unknown rarity {:?}", potion.id, other),
            }] += 1;
        }
        ids.sort_unstable();
        assert_eq!(
            ids,
            vec![
                "ancient_potion",
                "block_potion",
                "blood_potion",
                "cultist_potion",
                "dexterity_potion",
                "energy_potion",
                "entropic_brew",
                "essence_of_steel",
                "explosive_potion",
                "fear_potion",
                "fire_potion",
                "flex_potion",
                "fruit_juice",
                "heart_of_iron",
                "liquid_bronze",
                "regen_potion",
                "speed_potion",
                "strength_potion",
                "swift_potion",
                "weak_potion",
            ]
        );
        // §158: the wiki's counts for the only character this content has (`Potions`, Ironclad only:
        // **17 Common / 9 Uncommon / 7 Rare = 33**). Thirteen are still missing, and every one of
        // them needs a mechanic the kernel does not have yet -- an in-fight card choice (Attack /
        // Skill / Power / Colorless Potion), a card upgrade or multi-select in a fight (Blessing of
        // the Forge, Elixir, Gambler's Brew, Liquid Memories), an auto-play or a duplicate play
        // (Distilled Chaos, Duplication Potion), a cost rewrite (Snecko Oil), a death save (Fairy in
        // a Bottle), a flee (Smoke Bomb). Pinning the band sizes is what makes "we are at 20" a fact
        // instead of an impression.
        assert_eq!(
            bands,
            [12, 4, 4],
            "Common / Uncommon / Rare -- the wiki's Ironclad pool is 17 / 9 / 7"
        );

        let index = (0..content.potion_count())
            .find(|index| content.potion(*index).map(|p| p.id) == Some("fire_potion"))
            .expect("fire_potion");
        let fire = content.potion(index).unwrap();
        assert_eq!(fire.effect, "combat_damage");
        assert_eq!(fire.amount, 20);

        // roguedeck has no `Potions` key: zero rows, and that is not an error.
        let core = std::fs::read(CORE_IMAGE).expect("the roguedeck image");
        let core = Content::parse(&core).expect("parses");
        assert_eq!(core.potion_count(), 0, "roguedeck has no potions");
    }

    /// **Every status the content declares is either implemented or declared inert.**
    ///
    /// This is the "one concept, one account" rule made executable: a status used to be able to
    /// exist in the catalogue and in the content's `STAT` table while nothing acted on it, and that
    /// looks exactly like a finished feature. Reconnaissance for Metallicize/Ritual/Thorns found
    /// `standard.artifact` and `standard.thorns` **described** in the catalogue and **absent** from
    /// `host.rs` -- so the check is not hypothetical.
    #[test]
    fn the_status_catalogue_is_honest() {
        let bytes = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = Content::parse(&bytes).expect("the image parses");
        let rows = content
            .section(crate::content::S_STAT)
            .map_or(0, |section| section.count);
        assert!(rows >= 5, "the sts image declares statuses ({rows})");
        for index in 0..rows {
            let Some(status) = content.status(index) else { continue };
            let Some(id) = content.string(status.id()) else { continue };
            assert!(
                crate::status_catalog::has_behaviour(id)
                    || crate::status_catalog::is_declared_inert(id),
                "status `{id}` is declared by the content but the kernel has no rule for it, \
                 and it is not in the declared-inert list -- it would silently do nothing"
            );
        }
    }

    #[test]
    fn the_real_images_validate() {
        with_core(|content, _| {
            assert_eq!(content.validate(), Ok(()));
        });
    }

    #[test]
    fn validate_catches_every_structural_fault() {
        let original = read_image(CORE_IMAGE);

        // 段重叠：把 STRO 挪进 STR 里。
        let mut blob = original.clone();
        patch32(&mut blob, dir_base(S_STRO), 272);
        let content = Content::parse(&blob).expect("parse 只管范围，重叠要由 validate 抓");
        assert_eq!(
            content.validate(),
            Err(ValidationError::Overlap { a: S_STR, b: S_STRO })
        );

        // 未 4 字节对齐。
        let mut blob = original.clone();
        patch32(&mut blob, dir_base(S_STRO), 31_326);
        let content = Content::parse(&blob).unwrap();
        assert_eq!(
            content.validate(),
            Err(ValidationError::Misaligned { index: S_STRO })
        );

        // count × stride > bytes（CARD 声明 63 行，只有 62 行的字节）。
        let mut blob = original.clone();
        patch32(&mut blob, dir_base(S_CARD) + 8, 63);
        let content = Content::parse(&blob).unwrap();
        assert_eq!(
            content.validate(),
            Err(ValidationError::CountExceedsBytes {
                index: S_CARD,
                count: 63,
                stride: 32,
                bytes: 1_984,
            })
        );
        // 但按字节取行仍然是安全的：第 63 行拿不到。
        assert!(content.card(62).is_none());
        assert_eq!(content.rows(Table::Card).count(), 62);

        // 字符串池：STRO 不再严格递增。
        let mut blob = original.clone();
        patch32(&mut blob, 31_324, 100);
        let content = Content::parse(&blob).unwrap();
        assert_eq!(
            content.validate(),
            Err(ValidationError::BadStringIndex { entry: 1 })
        );
        // 坏池子读出来是空串（不是 panic、也不是越界读）。
        assert_eq!(content.string(1), Some(""));

        // 字符串池：STR 的 count 与索引表长度对不上。
        let mut blob = original.clone();
        patch32(&mut blob, dir_base(S_STR) + 8, 9_999);
        let content = Content::parse(&blob).unwrap();
        assert_eq!(
            content.validate(),
            Err(ValidationError::StringCountMismatch {
                entries: 1_376,
                str_count: 9_999,
                stro_count: 1_376,
            })
        );

        // 字符串池：末项越过池尾。
        let mut blob = original.clone();
        patch32(&mut blob, 31_324 + 4 * 1_375, 40_000);
        let content = Content::parse(&blob).unwrap();
        assert_eq!(
            content.validate(),
            Err(ValidationError::BadStringIndex { entry: 1_375 })
        );

        // 原始镜像是干净的。
        let content = Content::parse(&original).unwrap();
        assert_eq!(content.validate(), Ok(()));
    }

    #[test]
    fn a_synthetic_minimal_image_parses() {
        // 手搓一个小镜像：目录 7 项（段号 0..6 = STR…AUX），其中 STR/STRO 是空段
        // （`count == 0, bytes == 0`，实测真实镜像的 TAGS 就是这个形状），AUX 有 2 个格。
        const NSEC: usize = 7;
        let mut blob = vec![0u8; HEADER_BYTES + DIRECTORY_ENTRY_BYTES * NSEC];
        blob[0..4].copy_from_slice(&MAGIC.to_le_bytes());
        blob[HDR_VERSION..HDR_VERSION + 2].copy_from_slice(&FORMAT_VERSION.to_le_bytes());
        blob[HDR_NSEC..HDR_NSEC + 2].copy_from_slice(&(NSEC as u16).to_le_bytes());
        blob[HDR_DIR_OFF..HDR_DIR_OFF + 4].copy_from_slice(&(HEADER_BYTES as u32).to_le_bytes());
        blob[HDR_SCHEMA_VERSION..HDR_SCHEMA_VERSION + 2].copy_from_slice(&7u16.to_le_bytes());
        let section_base = HEADER_BYTES + DIRECTORY_ENTRY_BYTES * NSEC;
        let total = (section_base + 4) as u32;
        blob[HDR_TOTAL_SIZE..HDR_TOTAL_SIZE + 4].copy_from_slice(&total.to_le_bytes());
        blob.extend_from_slice(&[9, 0, 8, 0]); // AUX = [9, 8]

        for (index, offset, bytes, count) in [
            (S_STR, 0u32, 0u32, 0u32),   // 空段
            (S_STRO, 0, 0, 0),           // 空段
            (S_AUX, section_base as u32, 4, 2),
        ] {
            let base = dir_base(index);
            blob[base..base + 4].copy_from_slice(&offset.to_le_bytes());
            blob[base + 4..base + 8].copy_from_slice(&bytes.to_le_bytes());
            blob[base + 8..base + 12].copy_from_slice(&count.to_le_bytes());
        }

        let content = Content::parse(&blob).expect("小镜像必须能解析");
        assert_eq!(content.section_count(), NSEC);
        assert_eq!(content.version(), FORMAT_VERSION);
        assert_eq!(content.schema_version(), 7);
        assert_eq!(content.total_size(), total);
        assert_eq!(content.validate(), Ok(()));
        assert!(
            content.section_by_name("AUX").unwrap().data == [9u8, 0, 8, 0].as_slice(),
            "AUX 是两个小端 u16：9 和 8"
        );
        assert_eq!(content.aux(0), Some(9));
        assert_eq!(content.aux(1), Some(8));
        assert_eq!(content.aux(2), None);
        assert!(content.section(S_STR).unwrap().is_empty());
        assert!(content.section_by_name("STR").unwrap().is_empty());
        assert!(content.section(S_TRW).unwrap().is_empty(), "目录里没写的段是空的");
        // 空池：只有串号 0。
        assert_eq!(content.string_count(), 0);
        assert_eq!(content.string(0), Some(""));
        assert_eq!(content.string(1), None);
        assert_eq!(content.strings().count(), 0);
        // 缺席的表都是空的。
        assert_eq!(content.id_count(), 0);
        assert_eq!(content.term_count(), 0);
        assert_eq!(content.root_count(), 0);
        assert_eq!(content.opcode_count(), 0);
        assert_eq!(content.rows(Table::Card).count(), 0);
        assert!(content.card(0).is_none());
        assert!(content.lookup("paperwork").is_none());
        // 段号 7 不在目录里（nsec = 7）。
        assert!(content.section(NSEC).is_none());
        exercise(&blob);
    }

    // ------------------------------------------------------- ENCT → 敌人记录（借用视图）

    /// 某段的文件偏移（= 目录项里的 `offset`）。
    fn section_offset(blob: &[u8], index: usize) -> usize {
        u32_at(blob, dir_base(index)).expect("目录项在镜像内") as usize
    }

    /// 一条敌人在**内容里**的坐标 + 读出来的一切（测试里要逐个比对的东西）。
    #[derive(Debug, PartialEq, Eq)]
    struct EnemyRow {
        id: String,
        max_health: Option<i32>,
        actions: Vec<String>,
        starting_statuses: usize,
        intent_rules: usize,
    }

    fn enemy_rows(content: &Content<'_>, encounter: u32) -> Vec<EnemyRow> {
        let list = content
            .encounter_enemies(encounter)
            .unwrap_or_else(|e| panic!("ENCT[{encounter}].Enemies 必须能读：{e:?}"));
        let mut out = Vec::with_capacity(list.len());
        for spec in list.iter() {
            let spec = spec.unwrap_or_else(|e| panic!("ENCT[{encounter}] 的敌人记录必须能读：{e:?}"));
            let actions = spec.actions().expect("Actions 必须能读");
            out.push(EnemyRow {
                id: spec.id().expect("Id 必须能读").to_string(),
                max_health: spec.max_health().expect("MaxHealth 必须能读"),
                actions: (0..actions.len())
                    .map(|i| {
                        actions
                            .string(i)
                            .unwrap_or_else(|| panic!("Actions[{i}] 的串号解不出串"))
                            .to_string()
                    })
                    .collect(),
                starting_statuses: spec
                    .starting_statuses()
                    .expect("StartingStatuses 必须能读")
                    .len(),
                intent_rules: spec.intent_rules().expect("IntentRules 必须能读").len(),
            });
        }
        out
    }

    /// 逐条读 **109 条遭遇**的敌人名单，并与 `reader.py` 的 dump 交叉核对。
    ///
    /// 期望值全部是量出来的（`reader.py` 对 `content.core.rdcf` 的 dump + `manifest.json`）：
    ///
    /// | 量 | 值 |
    /// |---|---|
    /// | `ENCT` 行数 | **109**（`manifest.json`：`ENCT count=109`） |
    /// | 敌人记录总数 | **149** |
    /// | `Actions` 总条数 | **480** |
    /// | 每遭遇敌人数 | `{1:76, 2:26, 3:7}` |
    /// | 每敌人动作数 | `{1:1, 2:9, 3:107, 4:20, 5:12}` |
    /// | 带 `IntentRules` 的记录 | **3**（`a_very_official_line` / `contradictory_signpost` / `minute_moth`） |
    /// | 带 `StartingStatuses` 的记录 | **20** |
    ///
    /// **"总数 + 分布 + 抽样"三样一起比才有区分力**：只比抽样 → "少读一半遭遇"照样绿；
    /// 只比总数 → "两条记录互相搬了位置"照样绿；只比分布 → 抽样的 id/动作串错位看不出来。
    #[test]
    fn every_encounter_enemy_record_reads() {
        with_core(|content, _blob| {
            assert_eq!(content.rows(Table::Encounter).count(), 109, "ENCT 行数");

            let mut encounters = 0usize;
            let mut enemies = 0usize;
            let mut actions = 0usize;
            let mut with_rules = Vec::new();
            let mut with_statuses = 0usize;
            let mut enemies_per_encounter = [0usize; 4]; // 下标 = 敌人数（1..=3）
            let mut actions_per_enemy = [0usize; 6]; // 下标 = 动作数（1..=5）

            for row in content.rows(Table::Encounter) {
                let index = row.index();
                let list = content
                    .encounter_enemies(index)
                    .unwrap_or_else(|e| panic!("ENCT[{index}] 的 Enemies 必须能读：{e:?}"));
                encounters += 1;
                assert!(
                    (1..=3).contains(&list.len()),
                    "ENCT[{index}] 有 {} 个敌人（实测最多 3 个）",
                    list.len()
                );
                enemies_per_encounter[list.len()] += 1;

                for (slot, spec) in list.iter().enumerate() {
                    let spec = spec.unwrap_or_else(|e| panic!("ENCT[{index}][{slot}]：{e:?}"));
                    let id = spec.id().expect("Id");
                    // 每遭遇内**不重名**（参考的 `ToDictionary(e => e.CombatantId)` 靠这条不抛）。
                    for other in 0..slot {
                        let previous = list.get(other).expect("前面的槽").id().expect("Id");
                        assert_ne!(previous, id, "ENCT[{index}] 里 `{id}` 出现了两次");
                    }
                    enemies += 1;
                    let count = spec.actions().expect("Actions").len();
                    assert!((1..=5).contains(&count), "`{id}` 有 {count} 条动作（实测 1..=5）");
                    actions_per_enemy[count] += 1;
                    actions += count;
                    let rules = spec.intent_rules().expect("IntentRules").len();
                    if rules > 0 {
                        with_rules.push((id.to_string(), rules));
                    }
                    if !spec.starting_statuses().expect("StartingStatuses").is_empty() {
                        with_statuses += 1;
                    }
                    // `MaxHealth` 在实测里恒存在（11..=132）。
                    let hp = spec.max_health().expect("MaxHealth").expect("实测 149/149 有值");
                    assert!((11..=132).contains(&hp), "`{id}` 的生命 {hp} 越出实测区间");
                }
            }

            assert_eq!(encounters, 109, "一条遭遇都不许跳过");
            assert_eq!(enemies, 149, "敌人记录总数（reader.py dump）");
            assert_eq!(actions, 480, "动作总条数（reader.py dump）");
            assert_eq!(enemies_per_encounter[1..], [76, 26, 7], "每遭遇敌人数分布");
            assert_eq!(actions_per_enemy[1..], [1, 9, 107, 20, 12], "每敌人动作数分布");
            assert_eq!(with_statuses, 20, "带起始状态的记录数");
            with_rules.sort();
            assert_eq!(
                with_rules,
                // 3 条：两条 `selfHasCounter`、一条 `opponentCardsPlayed`（后者今天求不出值，
                // 但**读**得出来 —— 能不能求值不在这一层）。
                [
                    ("a_very_official_line".to_string(), 1),
                    ("contradictory_signpost".to_string(), 3),
                    ("minute_moth".to_string(), 1),
                ],
                "带 IntentRules 的记录"
            );

            // ---- 抽样：id / 生命 / 动作串**逐字**对（`Actions` 是 F_STRLIST 的串号，
            //      错当成 term id 会读到不相干的串 —— 只有逐字比能抓到那种错）。
            assert_eq!(
                enemy_rows(content, 0),
                [EnemyRow {
                    id: "a_very_official_line".to_string(),
                    max_health: Some(29),
                    actions: [
                        "a_very_official_line.shuffle_forward",
                        "a_very_official_line.compress_the_queue",
                        "a_very_official_line.shuffle_backward",
                    ]
                    .iter()
                    .map(|s| s.to_string())
                    .collect(),
                    starting_statuses: 1,
                    intent_rules: 1,
                }],
                "ENCT[0]"
            );
            assert_eq!(
                enemy_rows(content, 3)
                    .iter()
                    .map(|row| (row.id.as_str(), row.max_health, row.actions.len()))
                    .collect::<Vec<_>>(),
                [("queue_imp", Some(22), 3), ("stamp_goblin", Some(22), 3)],
                "ENCT[3] 是两个敌人"
            );
            assert_eq!(
                enemy_rows(content, 17),
                [EnemyRow {
                    id: "iron_warrant_avatar".to_string(),
                    max_health: Some(92),
                    actions: [
                        "iron_warrant_avatar.warrant_ignites",
                        "iron_warrant_avatar.iron_authority",
                        "iron_warrant_avatar.served_in_steel",
                        "iron_warrant_avatar.binding_order",
                        "iron_warrant_avatar.final_service",
                    ]
                    .iter()
                    .map(|s| s.to_string())
                    .collect(),
                    starting_statuses: 0,
                    intent_rules: 0,
                }],
                "ENCT[17] 是那条 5 动作记录（顺序也是语义：`Actions[(round-1)%5]`）"
            );
            assert_eq!(
                enemy_rows(content, 18)
                    .iter()
                    .map(|row| (row.id.as_str(), row.max_health, row.actions.len()))
                    .collect::<Vec<_>>(),
                [
                    ("seizure_marshal", Some(42), 4),
                    ("inventory_lantern", Some(26), 4),
                    ("lock_cart", Some(34), 4)
                ],
                "ENCT[18] 是三条记录的精英战"
            );
            // 末条遭遇（索引与 id 的对齐不能错位一行）。
            assert_eq!(
                enemy_rows(content, 108)
                    .iter()
                    .map(|row| (row.id.as_str(), row.max_health, row.actions.len()))
                    .collect::<Vec<_>>(),
                [("folded_affidavit_bat", Some(30), 3)],
                "ENCT[108]"
            );
            assert_eq!(
                content.entity_id(Table::Encounter, 108),
                Some("city_easy_form_06")
            );
        });
    }

    /// 形状不对时**响亮失败**，绝不静默给一个空名单。
    ///
    /// 三个坏形状各一条（在内存里改镜像，不动磁盘上的产物）：
    /// 1. `Enemies` 格写成 `NULL16` ⇒ `MissingEnemies`；
    /// 2. `Enemies` 指到的 term 不是 `_arr`（把它的 op 改成 `_null`）⇒ `NotAnArray`；
    /// 3. 列表个数超出 `AUX`（改成 4000 > 2078 格）⇒ `MalformedList`。
    ///
    /// 还有两条"下标越界"：遭遇号越界、敌人槽越界。
    #[test]
    fn a_broken_encounter_shape_is_an_error_not_an_empty_list() {
        let original = read_image(CORE_IMAGE);

        // 0. 原始镜像是好的，而且**不是**空名单（否则下面的断言可能全在比两个空值）。
        {
            let content = Content::parse(&original).unwrap();
            let list = content.encounter_enemies(0).unwrap();
            assert_eq!(list.len(), 1);
            assert_eq!(list.encounter(), 0);
            assert!(!list.is_empty());
        }

        let enct = section_offset(&original, S_ENCT);
        // 第 0 行第 1 格 = `Enemies`（ENCT stride 16，每格 2 字节）。
        let enemies_cell = enct + 2;
        let array_term = u16_at(&original, enemies_cell).expect("格在镜像内");
        assert_ne!(array_term, NULL16, "实测这一格指着 `_arr`");

        // 1. `Enemies` 格 = null。
        let mut blob = original.clone();
        patch16(&mut blob, enemies_cell, NULL16);
        let content = Content::parse(&blob).unwrap();
        assert_eq!(
            content.encounter_enemies(0).unwrap_err(),
            EncounterError::MissingEnemies
        );

        // 2. 把那个 term 的 op 从 `_arr`(4) 改成 `_null`(0)。
        let trw = section_offset(&original, S_TRW);
        let trm = section_offset(&original, S_TRM);
        let word = u16_at(&original, trw + 2 * usize::from(array_term)).expect("TRW 有这一项");
        let record = trm + 4 * usize::from(word);
        assert_eq!(
            u16_at(&original, record),
            Some(OP_ARR),
            "实测 ENCT[0].Enemies 指着一个 `_arr`"
        );
        let mut blob = original.clone();
        patch16(&mut blob, record, OP_NULL);
        let content = Content::parse(&blob).unwrap();
        assert_eq!(
            content.encounter_enemies(0).unwrap_err(),
            EncounterError::NotAnArray(array_term)
        );

        // 3. 列表个数 4000 > `AUX` 的 2078 格。
        let mut blob = original.clone();
        patch16(&mut blob, record + 4, 4_000);
        let content = Content::parse(&blob).unwrap();
        assert_eq!(
            content.encounter_enemies(0).unwrap_err(),
            EncounterError::MalformedList("Enemies")
        );

        // 4. 下标越界：遭遇号、敌人槽。
        let content = Content::parse(&original).unwrap();
        assert_eq!(
            content.encounter_enemies(109).unwrap_err(),
            EncounterError::NoSuchEncounter(109)
        );
        assert_eq!(
            content.encounter_enemies(0).unwrap().get(1).unwrap_err(),
            EncounterError::NoSuchEnemy {
                encounter: 0,
                index: 1
            }
        );
    }

    /// 同一个 id 可能是**另一种实体**：`overfilled_inbox` 既是卡牌（`CARD[42]`）也是遗物
    /// （`REL[33]`），而它**不是**遭遇。
    ///
    /// 为什么值得一条测试：`ENCT` 读器的调用方（wasm / fightdump）会拿一个 id 去`lookup`。
    /// 用不带类别的 [`Content::lookup`] 拿到"第一条"再把行号当遭遇行号用，就会读到
    /// **另一张表**的同一行号 —— 数据合法、语义全错。这条测试把"必须带类别查"钉住。
    #[test]
    fn an_id_that_is_a_card_and_a_relic_is_not_an_encounter() {
        with_core(|content, _blob| {
            let card = content
                .lookup_in("overfilled_inbox", EK_CARD)
                .expect("它是卡牌");
            let relic = content
                .lookup_in("overfilled_inbox", EK_RELIC)
                .expect("它也是遗物");
            assert!(
                card.index != relic.index || card.entity_kind != relic.entity_kind,
                "两条记录必须是不同的实体（不是同一条被读了两次）"
            );
            assert_eq!(content.entity_id(Table::Card, u32::from(card.index)), Some("overfilled_inbox"));
            assert_eq!(content.entity_id(Table::Relic, u32::from(relic.index)), Some("overfilled_inbox"));
            // 它不是遭遇 —— 而"按 id 找遭遇"这件事**没有**入口（`encounter_enemies` 只收行号），
            // 所以调用方必须自己先 `lookup_in(id, EK_ENCOUNTER)`。
            assert_eq!(content.lookup_in("overfilled_inbox", EK_ENCOUNTER), None);
            // 不带类别的 `lookup` 给的是最靠前那条（`reader.py` 的 `setdefault` 语义）。
            assert_eq!(content.lookup("overfilled_inbox").map(|e| e.entity_kind), Some(EK_CARD));
            // 而真正的遭遇在 `EK_ENCOUNTER` 下能查到，行号也真的指向那条 `ENCT` 行。
            let encounter = content
                .lookup_in("city_easy_01", EK_ENCOUNTER)
                .expect("它是遭遇");
            assert_eq!(u32::from(encounter.index), 0);
            assert_eq!(content.encounter_enemies(u32::from(encounter.index)).unwrap().len(), 1);
        });
    }
}
