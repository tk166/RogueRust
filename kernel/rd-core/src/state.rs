//! The combat state model: the hash-relevant projection of the reference engine's `CombatState`.
//!
//! Ported from `RogueDeck-Core` at commit `fd43e68ab91f40b475b745725abb17134b951c51` (MIT).
//! The format this model feeds is frozen in `docs/spec/SEMANTICS-v1.md` §6.1.
//!
//! # What this type is, and what it deliberately is NOT
//!
//! This struct holds **exactly the fields that [`crate::snapshot::write_hash_input`] writes**, plus
//! the container structure needed to write them in the reference's order. That is not a shortcut:
//! the reference hasher covers a *subset* of the snapshot, and the snapshot covers a subset of the
//! live state (`CombatStateHasher.cs:26-164`, spec §6.3 / §5.4#5). Modelling the superset and
//! hashing a subset is how a port silently starts hashing a field the original never hashed -
//! the fingerprint would diverge and nothing would say so. Here the boundary is a **type**: a field
//! that is in this struct is in the canonical text, and a field that is not cannot be.
//!
//! The live-state fields that are out of scope are listed in one place,
//! [`crate::snapshot`]'s module header (the D12 list and the W1 scope list).
//!
//! # No allocator, no silent drops
//!
//! Everything is `no_std` and allocation-free: collections are fixed-capacity arrays plus a count
//! (`[T; N]` + `u8`). A write that does not fit returns [`CapacityError`] - it never truncates and
//! never overwrites. `docs/spec/SEMANTICS-v1.md` §3-D6 draws the same line for the whole port:
//! out-of-range must become an error code, not a panic and not a silent partial result.
//!
//! # Capacities
//!
//! | constant | value | why this number |
//! |---|---|---|
//! | [`MAX_COMBATANTS`] | 12 | the reference's heavy fight is 4v3 = 7 (spec §5.2); units can be summoned mid-fight (`summoned_%06d`, `CombatState.cs:698-708`), so 12 leaves room for five |
//! | [`MAX_CARD_INSTANCES`] | 224 | **one pool for the whole fight**: the heavy fight measures ~200 card instances (spec §5.2); 224 leaves 12% headroom for summons and queued cards |
//! | [`MAX_CARDS_PER_ZONE`] | 96 | one pile (whole deck in the draw pile). The pool cap above bites first in any legal fight: 224 instances over 7 piles averages 32, and the measured heavy fight averages ~28 per combatant (spec §5.2) |
//! | [`MAX_GLOBAL_STATUSES`] | 32 | global statuses are rare; the whole standard package registers 16 status *definitions* (`StandardCombatPackage.cs:26-43`) |
//! | [`MAX_STATUSES_PER_COMBATANT`] | 24 | the heavy fight measures ~20 status instances across 7 combatants (spec §5.2) |
//! | [`MAX_RESOURCES`] | 8 | one in the standard package (`standard.energy`); 8 covers content with several pools |
//! | [`MAX_DEFENSIVE_POOLS`] | 8 | one in the standard package (`standard.block`) |
//! | [`MAX_COUNTERS_PER_COMBATANT`] | 16 | content-defined named integers, few in practice |
//! | [`MAX_TAGS_PER_COMBATANT`] | 8 | measured **always empty** in the reference (spec §2.2), so this is pure headroom |
//! | [`MAX_MARKS_PER_CARD`] | 4 | per-instance marks; the standard package gives meaning to one (`standard.retained_card`) plus a few content marks |
//! | [`MAX_MARK_COUNTERS_PER_CARD`] | 4 | three reserved ids are documented (`StandardCombatIds.cs:85-93`), so 4 |
//! | [`MAX_TEMPORARY_RULES`] | 32 | spec §5.1 suggests 32 for temporary rules |
//!
//! # Memory
//!
//! Measured, not estimated (`state_fits_the_sram_plan` prints these on every run):
//!
//! | part | bytes |
//! |---|---|
//! | card pool (`MAX_CARD_INSTANCES` x `size_of::<CardInstance>()` = 224 x 440) | 98,560 |
//! | combatants (`MAX_COMBATANTS` x `size_of::<Combatant>()` = 12 x 4,876) | 58,512 |
//! | piles (`MAX_COMBATANTS` x `size_of::<CardZones>()` = 12 x 1,392) | 16,704 |
//! | **those three parts** | **173,776** |
//! | event queues (批次 1)：64x(180+4+4) + 64x(96+4) + 64x44 + 128x16（`EffectRequest` / `ChainSlot` / `Option<ProgramExecutionSlot>` / `CombatEvent` / `Continuation` / `ChainRecord`）| 23,296 |
//! | residual: scalar fields, ids, `StatusInstance` arrays, resources, temporary rules, the six queues' `head`/`len`, `current_chain` | 11,228 |
//! | program frame arenas (批次 2): frames 8x216 + node slots 64x12 + loop snapshots 4x546 | 5,512 |
//! | animation log (§142): beats 64x20 + def side table 24x41 + `len`/`defs_len`/`dropped` = `size_of::<BeatLog>()` | 2,268 |
//! | **`size_of::<CombatState>()`** | **216,080 (211 KiB)** |
//!
//! ⚠️ 这张表是**实测量出来的**，不是估的；每次改 `CombatState` 的字段都要重新核，核的是**每一行**
//! 而不只是总量 —— 这张表就烂过一次：总量那行是对的，而 `combatants` 那行写着
//! `12 x 3,872 = 46,464`（旧的 `size_of::<Combatant>()`），真值 `12 x 4,832 = 57,984`，
//! 差 11,520 B 谁也看不出来，因为没有任何一行去和别的行对账。所以现在表里多了
//! "三个分量之和" 与 "残差" 两行：前四行加不出总量就是当场可见的算术错误
//! （`state_fits_the_sram_plan` 只盯着上界，盯不住"表格里的数字过期"）。
//! 残差那一行是**总量减三个分量**推出来的，它不会单独过期，但它的含义（哪些字段住在残差里）
//! 会随字段增删改变，所以它也要跟着看。
//!
//! ⚠️ **它又烂了两行，都在 §142 这一轮被发现**：
//!
//! * `combatants` 写的 `12 x 4,832 = 57,984` 早已过期（实例化后实测 **4,876** ⇒ 58,512）；
//! * `event queues` 写的 23,040 也对不上（按今天实测的四个尺寸算是 **23,296**，差 256 B）。
//!
//! 而 **§142 的 diff 一行都没碰 `Combatant`、也一行都没碰那六个队列** —— 也就是说这两行在
//! 本轮之前就已经错了，只是没人加字段时去核它们。这正是上面那条警告的意思：表格里
//! "这次没变化的那几行"才是最容易烂的地方。数字已按今天重测的填，且现在
//! `state_fits_the_sram_plan` 会把 `beats` 那一行的两个数（分量和 / `size_of::<BeatLog>()`）
//! 一起打出来 —— 对不上的时候看得见是哪一边。
//!
//! 最近三次变化：
//!
//! 1. `StatusInstance` 加了 `source_combatant_id: Option<CombatantId>`
//!    （DoT 要能归属出手方，见 `port-plan` §41.4），**171,848 → 184,648 B（+12.8 KB）**。
//!    原因是 `Option<CombatantId>` = **42 B**（`Ident<40>` 是 41 B 且没有 niche，`Option` 多一个 tag），
//!    乘上约 300 个状态槽。SRAM 占比 28.3% → **30.5%**。
//! 2. **事件队列批次 1**（六队列 + 链 arena）：**184,648 → 207,712 B（+23,064 B，+11.2%）**，
//!    SRAM 占比 30.5% → **34.3%**。分量逐列打在上面那张表的队列行里，算术：
//!    64×(176+2+4) + 64×(96+2) + 64×44 + 128×16 = 23,040，余下 24 B 是六个队列的
//!    `head`/`len`、`current_chain` 与结构体对齐（所以残差从 11,400 涨到 11,424）。
//! 3. **事件队列批次 2**（节目帧 + 节点槽 + 循环快照）：**207,712 → 213,224 B（+5,512 B，+2.7%）**，
//!    SRAM 34.3% → **35.2%**。分量逐项打在上面那行：8×216（帧：执行号 / 链 / 三个 id 槽 /
//!    两个迭代绑定 / 计步 / 终态 / 终态回调）+ 64×12（节点槽：父 / 计数 / 快照号）+
//!    4×546（循环快照：目标 12×41+1 与卡 96×2+1 取大者 + 两格保存位）。上界 245,760 仍然成立
//!    （余量 32,536 B）。⚠️ 这三样**不进哈希**（参考把它们等同构在 GC 堆上）⇒ 基线不动。
//!
//!    ⚠️ 207,712 **小于** `event-queue-interface.md` §10.2 探针的**忠实档 231,256 B**：
//!    探针按"事件枚举 = 参考全集 41 个变体"量形状，而批次 1 只声明了接了线的那 5 个变体
//!    （`CombatEvent` 因此是 96 B 而不是 492 B）。差的是**还没有生产者的变体**，不是能力。
//! 4. **动画日志**（§142）：**213,224 → 216,080 B（+2,856 B，+1.3%）**，SRAM 35.2% → **35.6%**。
//!    日志本体 `size_of::<BeatLog>()` = **2,268 B**（64 条 × 20 B + 24 个名字 × 41 B + 4），
//!    连同它带进来的对齐是 2,856 B；同时上面两条**旧错行**被改正（`Combatant` +528、
//!    队列 +256），所以这一版的总量不能只用"加了一个日志"来解释 —— 差额逐项列在表里。
//!    ⚠️ 它**不进哈希也不要进快照**：日志记的是"已经发生过什么"，两个只在日志上不同的局面
//!    后续行为逐字相同 ⇒ 加它**不移动任何基线**（`hash_golden` 的字节一个都没变，这是
//!    §142 提交里 `golden` 闸门仍然绿的原因，而不是"跑了没红"）。
//!
//! That is 35.6% of the P4's 592 KiB of SRAM in the worst case, and about 7x the reference's *packed*
//! estimate of ~9 KB for the same 4v3/200-card fight (spec §5.2) - because §5.2 assumes interned
//! `u16` ids and 24 B per card, while this stage stores **ASCII strings** (the task's stage-1
//! instruction, §3-D9) and pays both per-card mark arrays in full: of a card's 440 B, 280 B are the
//! two 4-slot mark arrays and 82 B are its two id strings, and both are usually empty.
//!
//! ⚠️ 关于"要不要把 `source_combatant_id` 存成 `u16` 槽位索引省回 ~12 KB"：**不做**，理由不是懒。
//! `CombatantId` 出现在**很多**字段里（`active_combatant_id`、`queued_target_id`、
//! `mark_source_combatant_id`、临时规则所有者……）。只把其中一个换成索引，会得到一个
//! **两套寻址并存的混合体**，而混合体的危险不是"多写几行转换"，是"某一处忘了转换"时
//! 它**照样能跑**（把 3 当成 id 用，或者把 id 的低 16 位当槽位）。要做就整族一起换，
//! 那是另一个量级的重构（§3-D9 的 intern），不是一次局部优化。
//!
//! Levers, largest first: intern the ids (§3-D9 - the card pool drops from ~95 KB to a few KB);
//! lower [`MAX_MARKS_PER_CARD`]/[`MAX_MARK_COUNTERS_PER_CARD`]; lower [`MAX_CARD_INSTANCES`]; or
//! place the state in PSRAM - it is `Copy`, has no pointers and no interior references, so the
//! caller decides where it lives.
//!
//! # Identity: ASCII, and ordered as bytes
//!
//! Ids are fixed-length ASCII strings ([`Ident`]) because the canonical text writes raw strings.
//! `docs/spec/SEMANTICS-v1.md` §3-D9 warns that when these become interned `u16` handles the
//! `(Priority, Id)` ordering is **still string order** - so [`Ident`] implements `Ord` as
//! `self.as_str().cmp(other.as_str())`, i.e. ASCII byte order, and `ident_order_is_ascii_byte_order`
//! pins that down. Non-ASCII is rejected at construction (§3-D13: `StringComparer.Ordinal` on
//! UTF-16 and UTF-8 byte order only agree below U+0080).

use core::cmp::Ordering;

// ---------------------------------------------------------------------------------------------
// Capacities
// ---------------------------------------------------------------------------------------------

/// See the module table. 4v3 = 7 in the reference's heavy fight, plus summons.
pub const MAX_COMBATANTS: usize = 12;

/// How many **living enemies** a fight may hold (port-plan.md §139).
///
/// The reference caps summons the same way; the number is 4 because the player has to be able to see
/// and target every one of them, and the observation publishes six slots in total.
pub const MAX_ENEMIES_IN_FIGHT: usize = 4;
/// Total card *instances* in one fight - not per combatant. See the module table.
pub const MAX_CARD_INSTANCES: usize = 224;
/// Entries in a single pile of a single combatant.
pub const MAX_CARDS_PER_ZONE: usize = 96;
/// Global status instances.
pub const MAX_GLOBAL_STATUSES: usize = 32;
/// Status instances on one combatant (includes pending ones).
pub const MAX_STATUSES_PER_COMBATANT: usize = 24;
/// Resource pools on one combatant.
pub const MAX_RESOURCES: usize = 8;
/// Defensive pools on one combatant.
pub const MAX_DEFENSIVE_POOLS: usize = 8;
/// Named integer counters on one combatant.
pub const MAX_COUNTERS_PER_COMBATANT: usize = 16;
/// Tags on one combatant.
pub const MAX_TAGS_PER_COMBATANT: usize = 8;
/// Per-instance marks on one card.
pub const MAX_MARKS_PER_CARD: usize = 4;
/// Per-instance mark counters on one card.
pub const MAX_MARK_COUNTERS_PER_CARD: usize = 4;
/// Installed temporary triggered programs.
pub const MAX_TEMPORARY_RULES: usize = 32;

/// Number of card zones. Kept beside [`CardZone`] so the two cannot drift apart.
pub const CARD_ZONE_COUNT: usize = 7;

// ---------------------------------------------------------------------------------------------
// Identifiers
// ---------------------------------------------------------------------------------------------

/// Capacity for the ordinary entity ids. The longest id in the standard package is
/// `standard.first_attack_each_turn_free` (36 bytes, `StandardCombatIds.cs:33`).
pub const ID_CAP: usize = 40;
/// Capacity for tags. Longest standard tag: `status_application_interceptor` (30 bytes).
pub const TAG_CAP: usize = 32;
/// Capacity for counter ids. Longest standard counter: `standard.card_output_scale_num` (30 bytes).
pub const COUNTER_CAP: usize = 32;
/// Capacity for generated instance ids: `card_%06d` (11), `status_%06d` (13), `summoned_%06d` (15).
pub const INSTANCE_ID_CAP: usize = 16;
/// Capacity for the temporary-rule event type: the reference stores a .NET `Type.FullName`
/// (`CombatStateSnapshotter.cs:29`). The longest in the frozen baseline is
/// `RogueDeck.Core.Combat.DiscardPileShuffledIntoDrawPileCombatEvent` (64 bytes); 96 leaves room.
/// §3-D5 replaces this with an `EventKind` tag - until then the string is what the golden hash sees.
pub const EVENT_TYPE_CAP: usize = 96;

/// Everything a bounded write can fail with. Never a panic, never a partial write.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CapacityError {
    /// The id is longer than its type's capacity.
    IdTooLong { cap: usize, len: usize },
    /// The id contains a byte >= 0x80, which would break `StringComparer.Ordinal` equivalence
    /// with UTF-8 byte order (spec §3-D13).
    IdNotAscii,
    /// A fixed-capacity container was full. Which one is in the payload.
    Full(Container),
    /// A keyed insert found the key already present (the reference throws for these cases, e.g.
    /// `AddTemporaryTriggeredProgram` with a live id).
    DuplicateKey,
    /// `AddCombatant` with an id that is already in the fight (`CombatState.cs:228-229`).
    DuplicateCombatant,
    /// A card or zone was addressed to a combatant the state does not know.
    MissingCombatant,
    /// The queue's parallel columns have different lengths.
    ///
    /// This is the reference's `EnsureEffectQueueMetadataAligned` / `EnsureEventQueueMetadataAligned`
    /// (`CombatState.cs:401-406, 436-440`) as a **real** check, not a `debug_assert!`: the release
    /// build is what runs on the bare-metal target, and misaligned metadata means "this effect got
    /// someone else's chain" - which the hash reports only as a different number.
    QueueMetadataMisaligned {
        /// `"effect"` or `"event"`.
        column: &'static str,
        /// Length of the record column.
        records: usize,
        /// Length of the chain column.
        chains: usize,
        /// Length of the owner column (equals `chains` for the event column, which has no owners).
        owners: usize,
    },
    /// A triggered chain was asked for a parent that is not live.
    ///
    /// Unreachable in the reference (`CurrentEffectChain` is non-null when a triggered chain is
    /// created, `CombatEffectChain.cs:12, 492-498`) and unreachable here today (batch 1 creates no
    /// triggered chains at all). **Deliberately loud rather than defaulted**: `ChainRecord::id` is
    /// the hashed `chain_num`, so inventing a fallback id would make "where did this chain number
    /// come from" unaccountable.
    ChainHasNoParent,
}

/// Which container overflowed. Separate from [`CapacityError`] so callers can tell a full pool
/// from a full turn order.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Container {
    TurnOrder,
    Combatants,
    CardZones,
    CardInstances,
    CardsInZone(CardZone),
    GlobalStatuses,
    Statuses,
    Resources,
    DefensivePools,
    Counters,
    Tags,
    Marks,
    MarkCounters,
    TemporaryRules,
    // ---- 事件队列（批次 1）----
    //
    // ⚠️ 这七个是**新增的响亮失败点**，不是新增的静默截断点：参考的三个 `Queue<T>` 无界
    // （`CombatState.cs:5-10`，全仓没有 `new Queue<T>(capacity)`），所以"队列满"是移植
    // **独有**的错误。它必须和参考自己的 1024 轮超限同级（`CombatEventHandling.cs:99-102`
    // 抛 `InvalidOperationException`），而不是"满了就丢"。
    PendingEffects,
    PendingEffectChains,
    PendingEffectOwners,
    PendingEvents,
    PendingEventChains,
    PendingContinuations,
    /// 效果链 arena（`MAX_LIVE_CHAINS`）。参考靠 GC 回收链，我们靠 `ChainRecord::refs`。
    Chains,
    /// 集合型事件携带的 id 列表（`MAX_EVENT_ID_LIST`）。**装满就是错误**（永不截断）。
    EventIdList,
    // ---- 节目帧调度（批次 2）----
    //
    // 参考把这三样都存在 GC 堆上（帧对象、闭包里的计数数组、闭包捕获的迭代快照），
    // 我们是定容数组。**三个都是"到顶就响亮失败"，不是预算杠杆** —— 放大它们
    // 不会改变任何一个已能跑通的局面的行为，只会把"这个局面跑不了"推远。
    /// 同时在飞的节目帧（`EffectProgramExecutionFrame`）。
    ProgramFrames,
    /// 同时在飞的"等完成"节点槽（参考是闭包捕获的 `remaining` 数组）。
    ProgramNodeSlots,
    /// 同时在飞的循环迭代快照（参考是闭包捕获的 `CardInstanceId[]` / `CombatantId[]`）。
    ProgramLoops,
}

impl core::fmt::Display for CapacityError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            Self::IdTooLong { cap, len } => write!(f, "id of {len} bytes exceeds capacity {cap}"),
            Self::IdNotAscii => f.write_str("id is not ASCII"),
            Self::Full(c) => write!(f, "{c:?} is full"),
            Self::DuplicateKey => f.write_str("key already present"),
            Self::DuplicateCombatant => f.write_str("combatant id already present"),
            Self::MissingCombatant => f.write_str("no such combatant"),
            Self::QueueMetadataMisaligned {
                column,
                records,
                chains,
                owners,
            } => write!(
                f,
                "{column} queue columns are not aligned: records {records}, chains {chains}, \
                 owners {owners}"
            ),
            Self::ChainHasNoParent => f.write_str("triggered chain without a live parent chain"),
        }
    }
}

impl core::fmt::Display for Container {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "{self:?}")
    }
}

/// `Result` shorthand for the model's mutating API.
pub type StateResult<T> = Result<T, CapacityError>;

/// Element of a fixed-capacity container: supplies the value of a vacant slot, so containers can
/// be built without an allocator (and, later, in `static` storage).
pub trait Empty: Copy {
    /// The vacant slot.
    const EMPTY: Self;
}

/// A fixed-length, ASCII-only identifier.
///
/// `Ord` is the reference's `StringComparer.Ordinal` restricted to ASCII, i.e. byte order, so
/// `"Z" < "a"`, `"card_10" < "card_9"` and `"a" < "ab"`. See `ident_order_is_ascii_byte_order`.
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct Ident<const CAP: usize> {
    bytes: [u8; CAP],
    len: u8,
}

impl<const CAP: usize> Ident<CAP> {
    /// The vacant identifier: an empty string.
    pub const EMPTY: Self = Self {
        bytes: [0u8; CAP],
        len: 0,
    };

    /// The capacity in bytes.
    pub const CAP: usize = CAP;

    /// Builds an identifier, rejecting anything too long or non-ASCII.
    ///
    /// An empty string is *allowed*: the reference's ids are plain strings and `AddCombatant("")`
    /// is only rejected for being a duplicate, so refusing empty here would be stricter than the
    /// original. (`active=` cannot tell `Some("")` from `None` for the same reason - so neither
    /// does this model.)
    pub fn new(value: &str) -> StateResult<Self> {
        let src = value.as_bytes();
        if src.len() > CAP {
            return Err(CapacityError::IdTooLong {
                cap: CAP,
                len: src.len(),
            });
        }
        if !src.is_ascii() {
            return Err(CapacityError::IdNotAscii);
        }
        let mut out = Self::EMPTY;
        out.bytes[..src.len()].copy_from_slice(src);
        out.len = src.len() as u8;
        Ok(out)
    }

    /// The identifier as a string. Always valid: construction is ASCII-checked and the tail is
    /// never touched.
    #[must_use]
    pub fn as_str(&self) -> &str {
        core::str::from_utf8(&self.bytes[..self.len as usize]).unwrap_or("")
    }

    /// Length in bytes.
    #[must_use]
    pub fn len(&self) -> usize {
        self.len as usize
    }

    /// True for the vacant identifier.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
}

impl<const CAP: usize> Empty for Ident<CAP> {
    const EMPTY: Self = Self {
        bytes: [0u8; CAP],
        len: 0,
    };
}

impl<const CAP: usize> Ord for Ident<CAP> {
    fn cmp(&self, other: &Self) -> Ordering {
        // Deliberately *not* the derived array comparison. The derived one would happen to agree
        // here (the tail is zero and 0x00 sorts below every ASCII byte), but "happens to agree"
        // is exactly what a future interning change would quietly break. This is the contract.
        self.as_str().cmp(other.as_str())
    }
}

impl<const CAP: usize> PartialOrd for Ident<CAP> {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl<const CAP: usize> core::fmt::Debug for Ident<CAP> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "{:?}", self.as_str())
    }
}

impl<const CAP: usize> core::fmt::Display for Ident<CAP> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str(self.as_str())
    }
}

macro_rules! id_kind {
    ($(#[$attr:meta])* $name:ident, $cap:expr) => {
        $(#[$attr])*
        #[derive(Clone, Copy, PartialEq, Eq, Hash)]
        pub struct $name(Ident<$cap>);

        impl $name {
            /// The vacant identifier.
            pub const EMPTY: Self = Self(Ident::<$cap>::EMPTY);
            /// The capacity in bytes.
            pub const CAP: usize = $cap;
            /// Builds the identifier; see [`Ident::new`].
            pub fn new(value: &str) -> StateResult<Self> {
                Ok(Self(Ident::new(value)?))
            }
            /// The identifier as a string.
            #[must_use]
            pub fn as_str(&self) -> &str {
                self.0.as_str()
            }
            /// Length in bytes.
            #[must_use]
            pub fn len(&self) -> usize {
                self.0.len()
            }
            /// True for the vacant identifier.
            #[must_use]
            pub fn is_empty(&self) -> bool {
                self.0.is_empty()
            }
        }

        impl Empty for $name {
            const EMPTY: Self = Self(Ident::<$cap>::EMPTY);
        }

        impl Ord for $name {
            fn cmp(&self, other: &Self) -> Ordering {
                self.as_str().cmp(other.as_str())
            }
        }

        impl PartialOrd for $name {
            fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
                Some(self.cmp(other))
            }
        }

        impl core::fmt::Debug for $name {
            fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
                write!(f, concat!(stringify!($name), "({:?})"), self.as_str())
            }
        }

        impl core::fmt::Display for $name {
            fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
                f.write_str(self.as_str())
            }
        }
    };
}

id_kind!(
    /// Identifies one fight (`CombatId`).
    CombatId,
    ID_CAP
);
id_kind!(
    /// Identifies one combatant within a fight.
    CombatantId,
    ID_CAP
);
id_kind!(
    /// References a combatant definition (content).
    CombatantDefinitionId,
    ID_CAP
);
id_kind!(
    /// A team: `player` / `enemy` in the standard package.
    TeamId,
    ID_CAP
);
id_kind!(
    /// Generated card instance id, `card_%06d` (`CombatState.cs:689-696`).
    CardInstanceId,
    INSTANCE_ID_CAP
);
id_kind!(
    /// References a card definition (content).
    CardDefinitionId,
    ID_CAP
);
id_kind!(
    /// Generated status instance id, `status_%06d` (`CombatState.cs:680-687`).
    StatusInstanceId,
    INSTANCE_ID_CAP
);
id_kind!(
    /// References a status definition (content).
    StatusDefinitionId,
    ID_CAP
);
id_kind!(
    /// A tag.
    TagId,
    TAG_CAP
);
id_kind!(
    /// A named integer counter.
    CounterId,
    COUNTER_CAP
);
id_kind!(
    /// A resource pool id, e.g. `standard.energy`.
    ResourceId,
    ID_CAP
);
id_kind!(
    /// A defensive pool id, e.g. `standard.block`.
    DefensivePoolId,
    ID_CAP
);
id_kind!(
    /// A triggered-effect definition id - the `tr=` line's first field.
    TriggeredEffectDefinitionId,
    ID_CAP
);

/// The event type of a temporary rule, as the reference writes it: a namespace-qualified .NET
/// type name (`CombatStateSnapshotter.cs:29`). Not an `Id` in the content sense, so it is not
/// defined through the same macro - but it is still ASCII and still bounded.
pub type EventTypeName = Ident<EVENT_TYPE_CAP>;

// ---------------------------------------------------------------------------------------------
// Enums (values must match the reference: the canonical text writes `(int)`)
// ---------------------------------------------------------------------------------------------

/// `CombatPrimitives.cs:3-10`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum CombatResult {
    Ongoing = 0,
    Victory = 1,
    Defeat = 2,
    Draw = 3,
    Aborted = 4,
}

/// `CombatPrimitives.cs:12-16`. Only meaningful in the rotating (non-simultaneous) mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum CombatTurnPhase {
    WaitingToStartTurn = 0,
    TurnInProgress = 1,
}

/// `CombatPrimitives.cs:25-33`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum CombatantLifecycleState {
    Alive = 0,
    Downed = 1,
    Dead = 2,
    Removed = 3,
    Escaped = 4,
    Banished = 5,
}

/// `CombatPrimitives.cs:35-40`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum StatusVisibility {
    Visible = 0,
    Hidden = 1,
    DebugOnly = 2,
}

/// `CombatPrimitives.cs:42-47`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum StatusPolarity {
    Buff = 0,
    Debuff = 1,
    Neutral = 2,
}

/// `Cards/CardZones.cs:3-22`. The order is the order the canonical text writes the piles in
/// (`draw`, `hand`, `disc`, `exh`, `ban`, `queue`, `aside`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum CardZone {
    DrawPile = 0,
    Hand = 1,
    DiscardPile = 2,
    ExhaustPile = 3,
    BanishedPile = 4,
    QueuePile = 5,
    SetAsidePile = 6,
}

impl CardZone {
    /// All zones, in enum order.
    pub const ALL: [CardZone; CARD_ZONE_COUNT] = [
        CardZone::DrawPile,
        CardZone::Hand,
        CardZone::DiscardPile,
        CardZone::ExhaustPile,
        CardZone::BanishedPile,
        CardZone::QueuePile,
        CardZone::SetAsidePile,
    ];

    /// Index into a per-zone array.
    #[must_use]
    pub const fn index(self) -> usize {
        self as usize
    }

    /// The short name the canonical text uses - and note that the zone is written as the *key* of
    /// each card line, so a card never carries its own `Zone` (`CombatStateHasher.cs:137-164`).
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            CardZone::DrawPile => "draw",
            CardZone::Hand => "hand",
            CardZone::DiscardPile => "disc",
            CardZone::ExhaustPile => "exh",
            CardZone::BanishedPile => "ban",
            CardZone::QueuePile => "queue",
            CardZone::SetAsidePile => "aside",
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Fixed-capacity containers
// ---------------------------------------------------------------------------------------------

/// A push-only, fixed-capacity list. Overflow is reported, never absorbed.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Bounded<T, const N: usize> {
    items: [T; N],
    len: u8,
}

impl<T: Empty, const N: usize> Default for Bounded<T, N> {
    fn default() -> Self {
        Self::new()
    }
}

impl<T: Empty, const N: usize> Bounded<T, N> {
    /// An empty container. `const` so larger containers can be built in constants.
    pub const fn new() -> Self {
        Self {
            items: [T::EMPTY; N],
            len: 0,
        }
    }

    /// Number of elements.
    #[must_use]
    pub fn len(&self) -> usize {
        self.len as usize
    }

    /// True when empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    /// The used prefix.
    #[must_use]
    pub fn as_slice(&self) -> &[T] {
        &self.items[..self.len as usize]
    }

    /// The used prefix, mutably.
    #[must_use]
    pub fn as_mut_slice(&mut self) -> &mut [T] {
        &mut self.items[..self.len as usize]
    }

    /// The element at `index`.
    #[must_use]
    pub fn get(&self, index: usize) -> Option<&T> {
        self.as_slice().get(index)
    }

    /// The element at `index`, mutably.
    #[must_use]
    pub fn get_mut(&mut self, index: usize) -> Option<&mut T> {
        self.as_mut_slice().get_mut(index)
    }

    /// Appends. Returns [`CapacityError::Full`] instead of dropping the value.
    pub fn push(&mut self, value: T, what: Container) -> StateResult<usize> {
        let at = self.len as usize;
        if at == N {
            return Err(CapacityError::Full(what));
        }
        self.items[at] = value;
        self.len += 1;
        Ok(at)
    }

    /// Removes and returns the last element.
    pub fn pop(&mut self) -> Option<T> {
        if self.len == 0 {
            return None;
        }
        self.len -= 1;
        let at = self.len as usize;
        let value = self.items[at];
        self.items[at] = T::EMPTY;
        Some(value)
    }

    /// Empties the container.
    pub fn clear(&mut self) {
        while self.pop().is_some() {}
    }

    /// Keeps only the elements the predicate returns `true` for, **preserving order**.
    ///
    /// Needed because the reference's `RemoveExpiredTemporaryTriggeredPrograms` (`CombatState.cs:572-592`)
    /// drops individual temporary rules, not the whole list — and [`Bounded`] had no way to remove
    /// from the middle. Compaction is in place, so no scratch buffer and no allocation.
    pub fn retain(&mut self, mut keep: impl FnMut(&T) -> bool) {
        let len = self.len as usize;
        let mut write = 0usize;
        for read in 0..len {
            if keep(&self.items[read]) {
                if write != read {
                    self.items[write] = self.items[read];
                }
                write += 1;
            }
        }
        // Clear the tail so a removed element does not linger as a stale copy behind `len`.
        for slot in write..len {
            self.items[slot] = T::EMPTY;
        }
        self.len = write as u8;
    }
}

impl<T, const N: usize> core::fmt::Debug for Bounded<T, N>
where
    T: Empty + core::fmt::Debug,
{
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_list().entries(self.as_slice()).finish()
    }
}

/// A value in a container addressed by a key. The key is what the canonical text sorts on, so the
/// key must expose the reference's `StringComparer.Ordinal` order (see [`Ident`]).
pub trait Keyed {
    /// The key type.
    type Key: Ord;
    /// The key of this value.
    fn key(&self) -> &Self::Key;
}

impl<T: Keyed + Empty, const N: usize> Bounded<T, N> {
    /// First index whose key is >= `key`, and whether it is equal.
    fn locate(&self, key: &T::Key) -> (usize, bool) {
        let mut i = 0;
        while i < self.len as usize {
            match self.items[i].key().cmp(key) {
                Ordering::Equal => return (i, true),
                Ordering::Greater => break,
                Ordering::Less => i += 1,
            }
        }
        (i, false)
    }

    fn insert_at(&mut self, at: usize, value: T, what: Container) -> StateResult<usize> {
        let len = self.len as usize;
        if len == N {
            return Err(CapacityError::Full(what));
        }
        self.items.copy_within(at..len, at + 1);
        self.items[at] = value;
        self.len += 1;
        Ok(at)
    }

    /// Inserts keeping the container sorted by key, replacing an existing equal key.
    ///
    /// Matches the reference's `Dictionary<Key, Value>`: the snapshot builder emits
    /// `OrderBy(key.value, StringComparer.Ordinal)` (`CombatStateSnapshotter.cs:81-97`), and the
    /// underlying store is a dictionary whose insert overwrites.
    pub fn upsert(&mut self, value: T, what: Container) -> StateResult<usize> {
        let (at, equal) = self.locate(value.key());
        if equal {
            self.items[at] = value;
            return Ok(at);
        }
        self.insert_at(at, value, what)
    }

    /// Inserts keeping the container sorted by key; an equal key is [`CapacityError::DuplicateKey`].
    pub fn insert_sorted(&mut self, value: T, what: Container) -> StateResult<usize> {
        let (at, equal) = self.locate(value.key());
        if equal {
            return Err(CapacityError::DuplicateKey);
        }
        self.insert_at(at, value, what)
    }
}

// ---------------------------------------------------------------------------------------------
// Leaves
// ---------------------------------------------------------------------------------------------

/// A pool's value. Mirrors `PoolSnapshot(Current, Max, CanExceedMax)` (`CombatStateSnapshot.cs:6`)
/// with `CanExceedMax` **omitted**: the hasher writes only `Current` and `Max`
/// (`CombatStateHasher.cs:85,90`), and a field that cannot be hashed does not belong in a type
/// whose whole purpose is "what the fingerprint sees". `CanExceedMax` is a `hash_full` concern.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Pool {
    /// Current amount. `>= 0`, and legally above `max` (overfill is a real state, spec §2.5).
    pub current: i32,
    /// Upper bound, `None` = unbounded. Written as `null`.
    pub max: Option<i32>,
}

impl Empty for Pool {
    const EMPTY: Self = Self {
        current: 0,
        max: None,
    };
}

/// One resource pool on a combatant.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ResourcePool {
    pub key: ResourceId,
    pub pool: Pool,
}

impl Empty for ResourcePool {
    const EMPTY: Self = Self {
        key: ResourceId::EMPTY,
        pool: Pool::EMPTY,
    };
}

impl Keyed for ResourcePool {
    type Key = ResourceId;
    fn key(&self) -> &ResourceId {
        &self.key
    }
}

/// One defensive pool on a combatant.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DefensivePool {
    pub key: DefensivePoolId,
    pub pool: Pool,
}

impl Empty for DefensivePool {
    const EMPTY: Self = Self {
        key: DefensivePoolId::EMPTY,
        pool: Pool::EMPTY,
    };
}

impl Keyed for DefensivePool {
    type Key = DefensivePoolId;
    fn key(&self) -> &DefensivePoolId {
        &self.key
    }
}

/// A named integer counter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Counter {
    pub key: CounterId,
    pub value: i32,
}

impl Empty for Counter {
    const EMPTY: Self = Self {
        key: CounterId::EMPTY,
        value: 0,
    };
}

impl Keyed for Counter {
    type Key = CounterId;
    fn key(&self) -> &CounterId {
        &self.key
    }
}

impl Keyed for TagId {
    type Key = TagId;
    fn key(&self) -> &TagId {
        self
    }
}

/// One status instance.
///
/// # 哪些字段进指纹，哪些只进模型
///
/// **进 `hash_golden` 的七个**（就是 `CombatStateHasher.AppendStatus` 写的那些，
/// `CombatStateHasher.cs:108-119`）：`id`、`definition_id`、`stacks`、`duration_turns`、
/// `charges`、`polarity`、`pending_turns`。
///
/// **模型里有、指纹里没有**（与 `CardInstance` 的 `marks` / `mark_source_combatant_id`
/// 同一类，这正是 `hash_full` 存在的理由）：
///
/// * [`Self::source_combatant_id`] —— 参考的实例构造函数收它
///   （`StatusEffects.cs:183-197` 的 `SourceCombatantId` 参数），但哈希器**不写**它。
///   它有一个真正的消费者：`DamageOverTimeTickEffectRequest` 把它塞进
///   `DealDamageEffectRequest.SourceCombatantId`（`StatusEffects.cs:501-509`），
///   而伤害的 **Source 阶段**要按它读出手方身上的 `DamageDealt` 修饰器。
///   没有它，`poison` 的"施加者力量加伤"永远缺席（那是 O16 之外的另一件事）。
///
/// 仍然**不在**这里（每个都写明理由，别让"缺字段"变成猜谜）：`SourceCardId`
/// （唯一的消费者是 `RestrictSourceCardTag` 的 spec，而 `status_bind` 见到非 null 就
/// 响亮拒绝，`status_bind.rs:82-85`）、`Tags`（走定义查表等价，`status_bind::has_tag` 的
/// 文档解释了为什么）、`Counters` / `AppliedRound` / `AppliedTurn` / `Visibility` /
/// `OwnerCombatantId`（本内核零消费者）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StatusInstance {
    pub id: StatusInstanceId,
    pub definition_id: StatusDefinitionId,
    pub stacks: i32,
    pub duration_turns: i32,
    pub charges: i32,
    pub polarity: StatusPolarity,
    /// Turns this instance still waits before it takes effect. `> 0` appends ` pend=<n>`; a
    /// pending status behaves differently from one in force, which is why the reference does hash it
    /// (`CombatStateSnapshot.cs:40-42`).
    pub pending_turns: i32,
    /// 谁施加的（`SourceCombatantId`）。**不进指纹**（见上面那段），但 DoT 的出手方靠它。
    ///
    /// 语义与参考一致的两条：新实例**原样收下**（`StatusEffects.cs:187`）；**合并时不动它**
    /// —— 参考在合并分支里只改层数/时长/充能，并留了一段注释解释为什么
    /// （`:159-165`：*"The instance keeps its own source, untouched"*）。
    pub source_combatant_id: Option<CombatantId>,
}

impl Empty for StatusInstance {
    const EMPTY: Self = Self {
        id: StatusInstanceId::EMPTY,
        definition_id: StatusDefinitionId::EMPTY,
        stacks: 0,
        duration_turns: 0,
        charges: 0,
        polarity: StatusPolarity::Buff,
        pending_turns: 0,
        source_combatant_id: None,
    };
}

impl StatusInstance {
    /// A status with everything at zero except its identity.
    #[must_use]
    pub fn new(
        id: StatusInstanceId,
        definition_id: StatusDefinitionId,
        polarity: StatusPolarity,
    ) -> Self {
        Self {
            id,
            definition_id,
            stacks: 0,
            duration_turns: 0,
            charges: 0,
            polarity,
            pending_turns: 0,
            source_combatant_id: None,
        }
    }

    /// Builder: who applied it (`SourceCombatantId`).
    ///
    /// 与 [`CardInstance::with_mark_source`] 同形：收**一个** id，`None` 就是"没有记录来源"
    /// （这条状态不是由任何战斗员施加的 —— 例如测试直接造出来的实例）。
    #[must_use]
    pub fn with_source_combatant(mut self, source: CombatantId) -> Self {
        self.source_combatant_id = Some(source);
        self
    }

    /// Builder: stacks.
    #[must_use]
    pub fn with_stacks(mut self, stacks: i32) -> Self {
        self.stacks = stacks;
        self
    }

    /// Builder: duration in turns.
    #[must_use]
    pub fn with_duration_turns(mut self, duration_turns: i32) -> Self {
        self.duration_turns = duration_turns;
        self
    }

    /// Builder: charges.
    #[must_use]
    pub fn with_charges(mut self, charges: i32) -> Self {
        self.charges = charges;
        self
    }

    /// Builder: pending turns.
    #[must_use]
    pub fn with_pending_turns(mut self, pending_turns: i32) -> Self {
        self.pending_turns = pending_turns;
        self
    }
}

/// One card instance.
///
/// The reference's `CardInstanceSnapshot` also carries `Zone`; it is not modelled because the
/// hasher writes the zone as the *line's key* and never the value (`CombatStateHasher.cs:137-164`),
/// and here the zone is implied by which pile index-list the card's slot sits in.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CardInstance {
    pub id: CardInstanceId,
    pub definition_id: CardDefinitionId,
    marks: Bounded<TagId, MAX_MARKS_PER_CARD>,
    mark_counters: Bounded<Counter, MAX_MARK_COUNTERS_PER_CARD>,
    pub mark_source_combatant_id: Option<CombatantId>,
    /// Who a queued card was aimed at (`QueuedTargetId`). `None` writes nothing.
    pub queued_target_id: Option<CombatantId>,
}

impl Empty for CardInstance {
    const EMPTY: Self = Self {
        id: CardInstanceId::EMPTY,
        definition_id: CardDefinitionId::EMPTY,
        marks: Bounded::new(),
        mark_counters: Bounded::new(),
        mark_source_combatant_id: None,
        queued_target_id: None,
    };
}

impl CardInstance {
    /// A bare card instance.
    #[must_use]
    pub fn new(id: CardInstanceId, definition_id: CardDefinitionId) -> Self {
        Self {
            id,
            definition_id,
            marks: Bounded::new(),
            mark_counters: Bounded::new(),
            mark_source_combatant_id: None,
            queued_target_id: None,
        }
    }

    /// Marks, in byte order (the reference sorts them: `CombatStateSnapshotter.cs:137-139`).
    #[must_use]
    pub fn marks(&self) -> &[TagId] {
        self.marks.as_slice()
    }

    /// Adds a mark, keeping the list sorted. A repeated mark is stored once, which is what the
    /// reference's `HashSet<TagId>` does.
    pub fn add_mark(&mut self, mark: TagId) -> StateResult<()> {
        if self.marks.as_slice().contains(&mark) {
            return Ok(());
        }
        self.marks.push(mark, Container::Marks)?;
        let len = self.marks.len();
        self.marks.as_mut_slice().sort_unstable();
        debug_assert_eq!(self.marks.len(), len);
        Ok(())
    }

    /// Mark counters, in key byte order (`CombatStateSnapshotter.cs:140-143`).
    #[must_use]
    pub fn mark_counters(&self) -> &[Counter] {
        self.mark_counters.as_slice()
    }

    /// Sets a mark counter (dictionary semantics).
    pub fn set_mark_counter(&mut self, key: CounterId, value: i32) -> StateResult<()> {
        self.mark_counters
            .upsert(Counter { key, value }, Container::MarkCounters)?;
        Ok(())
    }

    /// Builder: mark source combatant.
    #[must_use]
    pub fn with_mark_source(mut self, source: CombatantId) -> Self {
        self.mark_source_combatant_id = Some(source);
        self
    }

    /// Builder: queued target.
    #[must_use]
    pub fn with_queued_target(mut self, target: CombatantId) -> Self {
        self.queued_target_id = Some(target);
        self
    }
}

/// One combatant, limited to the fields `AppendCombatant` writes.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Combatant {
    pub id: CombatantId,
    pub definition_id: CombatantDefinitionId,
    pub team_id: TeamId,
    /// Who summoned this combatant (`None` for anything the encounter placed).
    ///
    /// A minion **flees when its master falls** (`port-plan.md` §139) -- that is the whole reason
    /// the link is stored rather than inferred from a naming convention.
    pub owner: Option<CombatantId>,
    pub lifecycle_state: CombatantLifecycleState,
    pub health_current: i32,
    pub health_max: i32,
    resources: Bounded<ResourcePool, MAX_RESOURCES>,
    defensive_pools: Bounded<DefensivePool, MAX_DEFENSIVE_POOLS>,
    statuses: Bounded<StatusInstance, MAX_STATUSES_PER_COMBATANT>,
    tags: Bounded<TagId, MAX_TAGS_PER_COMBATANT>,
    counters: Bounded<Counter, MAX_COUNTERS_PER_COMBATANT>,
}

impl core::fmt::Debug for Combatant {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_struct("Combatant")
            .field("id", &self.id)
            .field("definition_id", &self.definition_id)
            .field("team_id", &self.team_id)
            .field("lifecycle_state", &self.lifecycle_state)
            .field("health", &(self.health_current, self.health_max))
            .field("resources", &self.resources)
            .field("defensive_pools", &self.defensive_pools)
            .field("statuses", &self.statuses)
            .field("tags", &self.tags)
            .field("counters", &self.counters)
            .finish()
    }
}

impl Empty for Combatant {
    const EMPTY: Self = Self {
        id: CombatantId::EMPTY,
        definition_id: CombatantDefinitionId::EMPTY,
        team_id: TeamId::EMPTY,
        owner: None,
        // The reference's default lifecycle value is `Alive`; only a `default(CombatantId)` id
        // marks the slot as vacant, and vacant slots are never read.
        lifecycle_state: CombatantLifecycleState::Alive,
        health_current: 0,
        health_max: 0,
        resources: Bounded::new(),
        defensive_pools: Bounded::new(),
        statuses: Bounded::new(),
        tags: Bounded::new(),
        counters: Bounded::new(),
    };
}

impl Combatant {
    /// A combatant at full health, alive.
    #[must_use]
    pub fn new(
        id: CombatantId,
        definition_id: CombatantDefinitionId,
        team_id: TeamId,
        health_current: i32,
        health_max: i32,
    ) -> Self {
        Self {
            id,
            definition_id,
            team_id,
            owner: None,
            lifecycle_state: CombatantLifecycleState::Alive,
            health_current,
            health_max,
            ..Self::EMPTY
        }
    }

    /// Builder: lifecycle state.
    #[must_use]
    pub fn with_lifecycle_state(mut self, state: CombatantLifecycleState) -> Self {
        self.lifecycle_state = state;
        self
    }

    /// Resource pools, sorted by key.
    #[must_use]
    pub fn resources(&self) -> &[ResourcePool] {
        self.resources.as_slice()
    }

    /// Sets a resource pool (dictionary semantics; the snapshot sorts by key).
    pub fn set_resource(&mut self, key: ResourceId, current: i32, max: Option<i32>) -> StateResult<()> {
        self.resources
            .upsert(ResourcePool { key, pool: Pool { current, max } }, Container::Resources)?;
        Ok(())
    }

    /// Defensive pools, sorted by key.
    #[must_use]
    pub fn defensive_pools(&self) -> &[DefensivePool] {
        self.defensive_pools.as_slice()
    }

    /// Sets a defensive pool.
    pub fn set_defensive_pool(
        &mut self,
        key: DefensivePoolId,
        current: i32,
        max: Option<i32>,
    ) -> StateResult<()> {
        self.defensive_pools.upsert(
            DefensivePool { key, pool: Pool { current, max } },
            Container::DefensivePools,
        )?;
        Ok(())
    }

    /// Status instances **in instance order** - the reference writes `AllStatuses` in list order and
    /// does *not* sort them (`CombatStateSnapshotter.cs:89-90`). Pending instances are included.
    #[must_use]
    pub fn statuses(&self) -> &[StatusInstance] {
        self.statuses.as_slice()
    }

    /// 状态实例的**可变视图** —— 合并层数/时长/充能时用。
    ///
    /// 为什么要暴露它：参考实现在**同一个实例上**合并（`StatusEffects.cs:126-180`：
    /// 层数 `+=`、时长取 `max`、充能 `+=`），而此前只有 `push_status`（追加新实例）。
    /// 只追加的后果不是"看不到"—— 所有求和型读取者（`combatantStatusStacks`、修饰器候选表）
    /// 算出的**总层数完全一样**；差别在**实例个数**：快照/哈希里会多一行、回合末按时长衰减会多减一次，
    /// 而且会提前吃光 `MAX_STATUSES_PER_COMBATANT`。
    ///
    /// ⚠️ 这是低层逃生口：调用方**只该改** `stacks` / `duration_turns` / `charges`，
    /// 不该改 `id` / `definition_id`（那会破坏"实例 id 唯一"与状态目录的对应关系）。
    pub fn statuses_mut(&mut self) -> &mut [StatusInstance] {
        self.statuses.as_mut_slice()
    }

    /// 按实例下标删掉一条状态实例，**保持其余实例的相对顺序**。
    ///
    /// 为什么需要它：参考在层数掉到 0 时**删掉实例**（`StatusEffects.cs:830-838`），
    /// 而不是留一条 0 层的。留 0 层不是"看不到"—— 它会让快照/哈希里多一行 `s=`、
    /// 让回合末的时长衰减多减一次、并提前吃光 `MAX_STATUSES_PER_COMBATANT`。
    ///
    /// 越界（含空表）⇒ `false`，不是 panic。
    ///
    /// 在此之前，执行层只能靠"重建整条 `Combatant`"绕过 —— 那在读的时候等价，
    /// 但一旦 `Combatant` 加了字段而重建处没跟上，就会**静默丢数据**。有了这个方法，
    /// 那种绕法应当删掉。
    pub fn remove_status(&mut self, index: usize) -> bool {
        let len = self.statuses.as_slice().len();
        if index >= len {
            return false;
        }
        {
            let items = self.statuses.as_mut_slice();
            for i in index..len - 1 {
                items[i] = items[i + 1];
            }
        }
        self.statuses.pop();
        true
    }

    /// Appends a status instance.
    pub fn push_status(&mut self, status: StatusInstance) -> StateResult<()> {
        self.statuses.push(status, Container::Statuses)?;
        Ok(())
    }

    /// Tags, in byte order. Measured always empty in the reference (spec §2.2).
    #[must_use]
    pub fn tags(&self) -> &[TagId] {
        self.tags.as_slice()
    }

    /// Adds a tag (set semantics), keeping the list sorted.
    pub fn add_tag(&mut self, tag: TagId) -> StateResult<()> {
        if self.tags.as_slice().contains(&tag) {
            return Ok(());
        }
        self.tags.push(tag, Container::Tags)?;
        self.tags.as_mut_slice().sort_unstable();
        Ok(())
    }

    /// Named counters, sorted by key.
    #[must_use]
    pub fn counters(&self) -> &[Counter] {
        self.counters.as_slice()
    }

    /// Sets a counter.
    pub fn set_counter(&mut self, key: CounterId, value: i32) -> StateResult<()> {
        self.counters.upsert(Counter { key, value }, Container::Counters)?;
        Ok(())
    }
}

/// An installed temporary triggered program (the `tr=` line).
///
/// `HasExpiryEffects` (`CombatStateSnapshot.cs:110-112`) is in the snapshot but is not hashed - it
/// is a restore guard signal - so it is not here.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TemporaryRule {
    pub id: TriggeredEffectDefinitionId,
    pub event_type: EventTypeName,
    /// `None` writes `inf` (`CombatStateHasher.cs:64`).
    pub remaining_activations: Option<i32>,
    /// `None` writes `none`.
    pub expires_after_round: Option<i32>,
    /// `None` writes `none`.
    pub expires_after_turn: Option<i32>,
    /// Appends ` ownerbound` when set.
    pub expires_when_owner_removed: bool,
    /// `None` writes `none`.
    pub owner_combatant_id: Option<CombatantId>,
    pub installed_round: i32,
    pub installed_turn: i32,
    /// Appends ` dead` when set.
    pub is_expired: bool,
}

impl Keyed for TemporaryRule {
    type Key = TriggeredEffectDefinitionId;
    fn key(&self) -> &TriggeredEffectDefinitionId {
        &self.id
    }
}

impl Empty for TemporaryRule {
    const EMPTY: Self = Self {
        id: TriggeredEffectDefinitionId::EMPTY,
        event_type: EventTypeName::EMPTY,
        remaining_activations: None,
        expires_after_round: None,
        expires_after_turn: None,
        expires_when_owner_removed: false,
        owner_combatant_id: None,
        installed_round: 0,
        installed_turn: 0,
        is_expired: false,
    };
}

impl TemporaryRule {
    /// A rule with no expiry and no owner.
    #[must_use]
    pub fn new(
        id: TriggeredEffectDefinitionId,
        event_type: EventTypeName,
        installed_round: i32,
        installed_turn: i32,
    ) -> Self {
        Self {
            id,
            event_type,
            installed_round,
            installed_turn,
            ..Self::EMPTY
        }
    }

    /// Builder: remaining activations.
    #[must_use]
    pub fn with_remaining_activations(mut self, remaining: i32) -> Self {
        self.remaining_activations = Some(remaining);
        self
    }

    /// Builder: round expiry.
    #[must_use]
    pub fn with_expires_after_round(mut self, round: i32) -> Self {
        self.expires_after_round = Some(round);
        self
    }

    /// Builder: turn expiry.
    #[must_use]
    pub fn with_expires_after_turn(mut self, turn: i32) -> Self {
        self.expires_after_turn = Some(turn);
        self
    }

    /// Builder: owner.
    #[must_use]
    pub fn with_owner(mut self, owner: CombatantId) -> Self {
        self.owner_combatant_id = Some(owner);
        self
    }

    /// Builder: owner-bound.
    #[must_use]
    pub fn owner_bound(mut self) -> Self {
        self.expires_when_owner_removed = true;
        self
    }

    /// Builder: expired.
    #[must_use]
    pub fn expired(mut self) -> Self {
        self.is_expired = true;
        self
    }
}

/// A pool slot: an index into [`CombatState`]'s card pool.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct CardSlot(u16);

impl CardSlot {
    /// The pool index.
    #[must_use]
    pub const fn index(self) -> usize {
        self.0 as usize
    }

    /// Rebuilds a slot from a pool index.
    ///
    /// Exists because `CardZones::slots(zone)` hands back raw `u16`s: a caller that wants to walk a
    /// pile card by card (the turn machine does, to ask "does *this* card stay in hand?") has the
    /// index but no way to name the slot. Without this the whole per-card path is unreachable from
    /// outside the module, because the tuple field is module-private.
    ///
    /// ⚠️ It does **not** validate: an out-of-range index yields a slot that matches no pile, and
    /// every consumer (`remove_slot`, `move_card`, `card`) already returns `None`/`false`/`Err`
    /// for one of those rather than panicking. Prefer [`CardZones::slot_at`] when you have a zone
    /// and an offset — it checks for you.
    #[must_use]
    pub const fn from_index(index: u16) -> Self {
        Self(index)
    }
}

impl Empty for CardSlot {
    /// 空槽 = 槽位 0（与 `Bounded` 的不变式"`len` 之后全是 `EMPTY`"配合）。
    ///
    /// ⚠️ 它**不是**"没有卡"的意思：`CardSlot` 是池下标，没有"空"的概念。
    /// 本实现只为了让 `Bounded<CardSlot, N>` 能 `new()`（[`ProgramLoopList`] 的卡快照）。
    /// 任何"用 `len` 判断有没有卡"的读者都必须看 `len`，不是看槽里的值。
    const EMPTY: Self = Self(0);
}

/// Where a moved card lands in its destination pile (`ZonePlacement`, `Cards/CardZones.cs:27-31`).
///
/// The distinction is load-bearing, not cosmetic: `Top` on the draw pile is what a tutor does, and
/// the pile order is written into the canonical text, so getting it wrong changes the hash.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ZonePlacement {
    /// Append. The reference default (`MoveCardToZone(..., placement = Bottom)`).
    Bottom,
    /// Insert at index 0. "The front is the draw top."
    Top,
}

/// One combatant's seven piles.
///
/// The cards themselves live in the state-wide pool; a pile stores pool slots. That is what bounds
/// the fight's card memory once instead of `combatants x zones x per-zone-cap`, and it is the
/// lookup-by-owner structure §3-D8 asks for in place of `CombatantCardZones.ContainsCard`'s linear
/// scan of every card in the fight.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct CardZones {
    combatant_id: CombatantId,
    slots: [[u16; MAX_CARDS_PER_ZONE]; CARD_ZONE_COUNT],
    counts: [u8; CARD_ZONE_COUNT],
}

impl core::fmt::Debug for CardZones {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_struct("CardZones")
            .field("combatant_id", &self.combatant_id)
            .field("draw", &self.count(CardZone::DrawPile))
            .field("hand", &self.count(CardZone::Hand))
            .field("disc", &self.count(CardZone::DiscardPile))
            .field("exh", &self.count(CardZone::ExhaustPile))
            .field("ban", &self.count(CardZone::BanishedPile))
            .field("queue", &self.count(CardZone::QueuePile))
            .field("aside", &self.count(CardZone::SetAsidePile))
            .finish()
    }
}

impl Empty for CardZones {
    const EMPTY: Self = Self {
        combatant_id: CombatantId::EMPTY,
        slots: [[0u16; MAX_CARDS_PER_ZONE]; CARD_ZONE_COUNT],
        counts: [0u8; CARD_ZONE_COUNT],
    };
}

impl CardZones {
    fn new(combatant_id: CombatantId) -> Self {
        Self {
            combatant_id,
            ..Self::EMPTY
        }
    }

    /// Whose piles these are.
    #[must_use]
    pub fn combatant_id(&self) -> &CombatantId {
        &self.combatant_id
    }

    /// Number of entries in one pile.
    #[must_use]
    pub fn count(&self, zone: CardZone) -> usize {
        self.counts[zone.index()] as usize
    }

    /// True when the pile holds nothing.
    #[must_use]
    pub fn is_empty(&self, zone: CardZone) -> bool {
        self.count(zone) == 0
    }

    /// The pile's pool slots, in pile order (`index 0` = top of the draw pile).
    #[must_use]
    pub fn slots(&self, zone: CardZone) -> &[u16] {
        &self.slots[zone.index()][..self.count(zone)]
    }

    /// The slot at `index` within one pile, bounds-checked.
    ///
    /// The checked sibling of `slots(zone)[index]` — walking a pile card by card is what the turn
    /// machine does at turn end, and an unchecked index there would be a panic on the bare metal.
    #[must_use]
    pub fn slot_at(&self, zone: CardZone, index: usize) -> Option<CardSlot> {
        self.slots(zone).get(index).map(|raw| CardSlot(*raw))
    }

    fn push_slot(&mut self, zone: CardZone, slot: u16) -> StateResult<()> {
        let at = self.count(zone);
        if at == MAX_CARDS_PER_ZONE {
            return Err(CapacityError::Full(Container::CardsInZone(zone)));
        }
        self.slots[zone.index()][at] = slot;
        self.counts[zone.index()] = (at + 1) as u8;
        Ok(())
    }

    /// Inserts at the **front** of a pile. The reference's `ZonePlacement.Top` is
    /// `destination.Insert(0, card)` with the comment "the front is the draw top"
    /// (`Cards/CardZones.cs:219-220`), so a tutor that puts a card on top of the draw pile needs
    /// this rather than [`Self::push_slot`].
    fn insert_slot_front(&mut self, zone: CardZone, slot: u16) -> StateResult<()> {
        let zi = zone.index();
        let count = self.counts[zi] as usize;
        if count == MAX_CARDS_PER_ZONE {
            return Err(CapacityError::Full(Container::CardsInZone(zone)));
        }
        self.slots[zi].copy_within(0..count, 1);
        self.slots[zi][0] = slot;
        self.counts[zi] = (count + 1) as u8;
        Ok(())
    }

    fn remove_slot(&mut self, zone: CardZone, slot: u16) -> bool {
        let zi = zone.index();
        let count = self.counts[zi] as usize;
        let found = self.slots[zi][..count].iter().position(|s| *s == slot);
        match found {
            Some(i) => {
                self.slots[zi].copy_within(i + 1..count, i);
                self.counts[zi] = (count - 1) as u8;
                true
            }
            None => false,
        }
    }

    fn clear(&mut self, zone: CardZone) {
        let zi = zone.index();
        let count = self.counts[zi] as usize;
        self.slots[zi][..count].fill(0);
        self.counts[zi] = 0;
    }
}

// ---------------------------------------------------------------------------------------------
// 事件队列（批次 1）：六个队列 + 效果链 arena + 续延
// ---------------------------------------------------------------------------------------------
//
// 参考实现在 `CombatState` 上挂了**六个**队列（`CombatState.cs:5-10`，【验证】，逐行读过）：
//
// | # | 字段 | 类型 | 与谁并列 |
// |---|---|---|---|
// | 1 | `_pendingEffects` | `Queue<IEffectRequest>` | 效果列（主） |
// | 2 | `_pendingEffectChains` | `Queue<CombatEffectChainContext>` | 效果列（元数据） |
// | 3 | `_pendingEffectOwners` | `Queue<EffectProgramExecutionId?>` | 效果列（元数据） |
// | 4 | `_pendingEvents` | `Queue<ICombatEvent>` | 事件列（主） |
// | 5 | `_pendingEventChains` | `Queue<CombatEffectChainContext>` | 事件列（元数据） |
// | 6 | `_pendingContinuations` | `Queue<Action<CombatState>>` | 续延列（独） |
//
// 三列**并行数组**是 C# 的表示问题（`Queue<T>` 装不了元组，且作者不想装箱），不是语义问题 ——
// 但它带了两条**断言不变式**（`EnsureEffectQueueMetadataAligned` / `EnsureEventQueueMetadataAligned`，
// `CombatState.cs:401-406, 436-440`），那两条是语义的守门人：三列长度不一致就意味着
// "某条效果拿到了别人的链"。本模块照参考保**三列 + 两条断言**（批次 1 的任务书要求），
// 断言在**每次出队前**跑（同参考），而不是只在 `debug_assert!` 里 —— 发布版也要红。
//
// 第六个队列**做不到照抄**：`Queue<Action<CombatState>>` 在 `no_std` + 零分配 +
// `forbid(unsafe_code)` 下不存在 ⇒ 续延必须是**数据**（[`Continuation`]）。这是
// `docs/spec/event-queue-interface.md` §4.1.3 唯一一条"最重要"的结论。

/// 待解析的**效果**队列容量（参考无界，见模块头）。
pub const MAX_PENDING_EFFECTS: usize = 64;
/// 待分发**事件**的容量（同上）。
pub const MAX_PENDING_EVENTS: usize = 64;
/// 待跑**续延**的容量（同上）。
pub const MAX_PENDING_CONTINUATIONS: usize = 64;
/// 活跃效果链的 arena 容量。
///
/// 为什么是队列容量的 **2 倍**而不是相等：最坏局面是"事件队列装满（64 条，每条各持一条链）
/// **加**正在分发的那一条派生出的触发链（+1）" ⇒ 65。取 128 是给这条 +1 留出整倍余量，
/// 而且它只值 128 × 16 B = 2,048 B。**这个常量的作用是"到顶就响亮失败"，不是"省内存"**
/// —— 调小它会把本来正确的局面变成 `CapacityError::Full(Chains)`。
pub const MAX_LIVE_CHAINS: usize = 128;
/// **集合型事件**携带的 id 列表容量。**不是截断上限。**
///
/// 参考在这里是 `IReadOnlyCollection<…>`、**无界**（`CombatEvents.cs:85-105, 246-255` 那 8 条）。
/// 超出容量必须**响亮失败**（[`EventIdList::push`] 返回错误），永不静默截断 ——
/// 静默截断是**语义降级**，不是实现选择（`docs/spec/event-queue-interface.md` §4.3 末的硬规则）。
/// 24 = `MAX_STATUSES_PER_COMBATANT`：一条"按极性移除状态"的事件最多带走一个战斗员的全部状态。
pub const MAX_EVENT_ID_LIST: usize = 24;
/// 排空循环的轮数上限（参考 `CombatExecutionLimits.cs:12`，默认 1024，**超限抛**）。
pub const MAX_QUEUE_CYCLES: u32 = 1024;
/// 单轮效果相位里最多解析多少条（`CombatExecutionLimits.cs:13`）。
pub const MAX_EFFECTS_PER_CYCLE: u32 = 1024;
/// 单轮事件相位里最多分发多少条（`CombatExecutionLimits.cs:14`）。
pub const MAX_EVENTS_PER_CYCLE: u32 = 1024;
/// 触发器嵌套深度上限（`CombatEffectChain.cs:10` 的 `MaximumTriggerDepth`）。
///
/// ⚠️ 与 `exec.rs::MAX_NODE_DEPTH = 64` **是两件事**（节目树深度 vs 触发器嵌套深度），
/// 参考里也是两个独立的数。**不许共用同一个常量**（`event-queue-interface.md` §4.1.1）。
pub const MAX_TRIGGER_DEPTH: u8 = 64;

/// 效果链在 arena 里的槽位。**只存槽位，不存整条链**（§4.1.4：整条链是值类型就是灾难）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ChainSlot(u16);

impl ChainSlot {
    /// "没有链"（顶层入队时 `CurrentEffectChain` 为 null 的那些路径，或还没建立链作用域）。
    ///
    /// 用**哨兵值**而不是 `Option<ChainSlot>`：`Option<u16>` 是 4 B，而队列每条都要带一个，
    /// 差值会直接进 SRAM 预算（`PendingEvent` 每条约 2 B × 64）。
    pub const NONE: Self = Self(u16::MAX);

    /// 由 arena 下标构造。
    #[must_use]
    pub const fn from_index(index: usize) -> Self {
        Self(index as u16)
    }

    /// arena 下标。
    #[must_use]
    pub const fn index(self) -> usize {
        self.0 as usize
    }

    /// 是否"没有链"。
    #[must_use]
    pub const fn is_none(self) -> bool {
        self.0 == u16::MAX
    }
}

impl Empty for ChainSlot {
    const EMPTY: Self = Self::NONE;
}

/// 节目执行帧的**槽位**（参考的 `EffectProgramExecutionId?`，`CombatState.cs:7`）。
///
/// 存槽位而不是 64 位的 id：它唯一的用途是"效果解析抛错时把帧绑回去"
/// （`CombatEffectQueueProcessor.cs:35-49`），**不排序、不进哈希**（§1.2 末）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProgramExecutionSlot(u32);

impl ProgramExecutionSlot {
    /// 由下标构造。
    #[must_use]
    pub const fn from_index(index: usize) -> Self {
        Self(index as u32)
    }

    /// 下标。
    #[must_use]
    pub const fn index(self) -> usize {
        self.0 as usize
    }
}

/// `Option<ProgramExecutionSlot>` 的空槽就是 `None`（"这条效果不是任何帧发起的"）。
impl Empty for Option<ProgramExecutionSlot> {
    const EMPTY: Self = None;
}

/// 一条效果链：**持久化链表**（父指针 + 自己这个触发器），语义等价于参考的不可变快照
/// （`CombatEffectChain.cs:8-41`）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ChainRecord {
    /// `chain_num` 那个数字（哈希行）。**只在建根链时自增**（`CombatState.cs:545-555`）。
    pub id: i64,
    /// 父链槽位；根链是 [`ChainSlot::NONE`]。
    pub parent: ChainSlot,
    /// 触发这个子链的触发器（intern 序号）；根链是 `NO_TRIGGER`。
    pub trigger: u16,
    /// `= parent.depth + 1`，冗余存一份免得走链（参考 `CombatEffectChain.cs:16`）。
    pub depth: u8,
    /// 引用计数（队列条目 + 作用域栈）。归零可回收 —— 参考靠 GC，我们没有。
    pub refs: u8,
}

/// `ChainRecord::trigger` 的"不是触发链"。
pub const NO_TRIGGER: u16 = u16::MAX;

impl Empty for ChainRecord {
    const EMPTY: Self = Self {
        id: 0,
        parent: ChainSlot::NONE,
        trigger: NO_TRIGGER,
        depth: 0,
        refs: 0,
    };
}

/// 效果链 arena：定容数组 + "refs == 0 即空槽"。
///
/// 为什么不是 [`Bounded`]：链会被**中途**回收（引用计数归零），而 `Bounded` 只能 push/pop/retain，
/// 且下标必须稳定（队列条目里存的是下标）。所以这里用"扫空槽"分配。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ChainArena {
    records: [ChainRecord; MAX_LIVE_CHAINS],
    len: u8,
}

impl ChainArena {
    /// 空的 arena。
    #[must_use]
    pub const fn new() -> Self {
        Self {
            records: [ChainRecord::EMPTY; MAX_LIVE_CHAINS],
            len: 0,
        }
    }

    /// 在用的链条数（`refs > 0`）。
    #[must_use]
    pub fn live(&self) -> usize {
        self.records.iter().filter(|r| r.refs > 0).count()
    }

    /// 分配一条链。**装不下就报错，不覆盖任何人**。
    pub fn alloc(&mut self, record: ChainRecord) -> StateResult<ChainSlot> {
        for index in 0..MAX_LIVE_CHAINS {
            let Some(slot) = self.records.get_mut(index) else {
                continue;
            };
            if slot.refs != 0 {
                continue;
            }
            *slot = record;
            self.len = self.len.saturating_add(1);
            return Ok(ChainSlot::from_index(index));
        }
        Err(CapacityError::Full(Container::Chains))
    }

    /// 读一条链。
    #[must_use]
    pub fn get(&self, slot: ChainSlot) -> Option<&ChainRecord> {
        if slot.is_none() {
            return None;
        }
        self.records.get(slot.index()).filter(|r| r.refs > 0)
    }

    /// 写一条链（调用方已经确认槽位有效）。
    #[must_use]
    pub fn get_mut(&mut self, slot: ChainSlot) -> Option<&mut ChainRecord> {
        if slot.is_none() {
            return None;
        }
        let record = self.records.get_mut(slot.index())?;
        if record.refs == 0 { None } else { Some(record) }
    }

    /// 加一次引用（"还有一条队列条目 / 一层作用域持着它"）。
    pub fn acquire(&mut self, slot: ChainSlot) -> StateResult<()> {
        let Some(record) = self.get_mut(slot) else {
            return Err(CapacityError::Full(Container::Chains));
        };
        // u8 上限不可达：`MAX_PENDING_EVENTS` + 作用域深度 ≤ 66。
        record.refs = record.refs.saturating_add(1);
        Ok(())
    }

    /// 放一次引用；归零即回收（把槽写回 `EMPTY`，与 `Bounded` 的"腾出的槽是空值"同一条不变式）。
    pub fn release(&mut self, slot: ChainSlot) {
        if slot.is_none() {
            return;
        }
        let Some(index) = self.records.get(slot.index()).map(|_| slot.index()) else {
            return;
        };
        let Some(record) = self.records.get_mut(index) else {
            return;
        };
        if record.refs == 0 {
            return;
        }
        record.refs -= 1;
        if record.refs == 0 {
            *record = ChainRecord::EMPTY;
            self.len = self.len.saturating_sub(1);
        }
    }

    /// 清空。
    pub fn clear(&mut self) {
        self.records = [ChainRecord::EMPTY; MAX_LIVE_CHAINS];
        self.len = 0;
    }
}

impl Empty for ChainArena {
    const EMPTY: Self = Self::new();
}

impl Default for ChainArena {
    fn default() -> Self {
        Self::new()
    }
}

/// 一条**待解析的效果**。参考的 `IEffectRequest`。
///
/// ⚠️ 批次 1 只声明**会被解析的四种**（也是本内容最常产生的那四种）。其余变体随
/// 解析器一起落地（§4.1.5 那张表的其余行）—— 声明一个没有解析器的变体，等于给
/// "效果永远不会生效"配一个好听的类型名。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EffectRequest {
    /// **End the current turn** (not in the reference's request list: it is the kernel's own,
    /// `port-plan.md` §125).
    ///
    /// Why a *request* and not a jump: an effect program runs deep inside the effect queue, and
    /// turn advancement lives in `turn.rs`. Setting a flag and letting the battle loop end the turn
    /// keeps the direction of control one-way -- exactly how `state.result` already works.
    EndTurn,
    /// **The target acts again when its turn ends** (the kernel's own, `port-plan.md` §127).
    ExtraTurn {
        /// Who gets it (`None` = the selector resolved to nobody ⇒ nothing happens).
        target: Option<CombatantId>,
    },
    /// `DealDamageEffectRequest`（`DamageEffects.cs:15-53`）。
    ///
    /// ⚠️ **必须带 `source`**：参考的请求里带着 `SourceCombatantId`，因为**修饰器在解析时
    /// 才读**（来源侧的 `DamageDealt` 阶段）——`DamageEffects.cs:273-320` 用的是解析那一刻的
    /// 状态，而不是派发那一刻。少了它，"先加力量再打"与"先打再加力量"就分不开了。
    DealDamage {
        /// 目标（派发时已解出的那个单位；`None` = 解出空集 ⇒ 参考跳过，不是错误）。
        target: Option<CombatantId>,
        /// 金额（**派发时**求值的表达式结果）。
        amount: i32,
        /// `IgnoresBlock`。
        ignores_block: bool,
        /// 出手方（修饰器来源阶段读它；也是 `DamageDealt` 事件的 `SourceCombatantId`）。
        source: Option<CombatantId>,
    },
    /// `GainBlockEffectRequest`（`DefensivePoolEffects.cs:3-167`）。
    GainBlock {
        /// 目标。
        target: Option<CombatantId>,
        /// 金额。
        amount: i32,
    },
    /// `ApplyStatusEffectRequest`（`StatusEffects.cs:12-326`）。
    ApplyStatus {
        /// 目标。
        target: Option<CombatantId>,
        /// 状态定义。
        definition: StatusDefinitionId,
        /// 层数。
        stacks: i32,
        /// 持续回合（`0` = 不带时长）。
        duration: i32,
        /// 充能。
        charges: i32,
        /// 来源单位（`SourceCombatantId`）。
        source: Option<CombatantId>,
        /// 来源卡（`SourceCardId`）。
        source_card: Option<CardDefinitionId>,
    },
    /// `ModifyStatusStacksEffectRequest`（`StatusEffects.cs:806-874`；`doubt` 的触发器就是这一种）。
    ModifyStatusStacks {
        /// 目标。
        target: Option<CombatantId>,
        /// 状态定义。
        definition: StatusDefinitionId,
        /// 增量（可负）。
        delta: i32,
    },
    /// `HealEffectRequest`（`DamageEffects.cs:323-377`）。
    Heal {
        /// 目标。
        target: Option<CombatantId>,
        /// 金额。
        amount: i32,
    },
    /// `SetCombatantCounterEffectRequest`（`CombatantCounterEffects.cs:6-…`）。
    SetCombatantCounter {
        /// 目标。
        target: Option<CombatantId>,
        /// 计数器。
        key: CounterId,
        /// 金额。
        amount: i32,
        /// `Relative`（缺席 ⇒ `true`，`EffectProgramNativeNodes.cs:670`）。
        relative: bool,
    },
    /// `DrawCardsEffectRequest`（`CardZoneEffects.cs:3-107`）。
    DrawCards {
        /// 谁的抽牌堆。
        owner: CombatantId,
        /// 抽几张。
        count: i32,
    },
    /// `GainResourceEffectRequest`。
    GainResource {
        /// 目标。
        target: Option<CombatantId>,
        /// 资源。
        key: ResourceId,
        /// 金额。
        amount: i32,
        /// `DefaultMax`（**派发时**求值的表达式；`None` = 镜像里那一格是 `null`）。
        ///
        /// 它必须跟着请求走：解析时"池不存在 ⇒ 建池，`current = min(amount, DefaultMax)`"
        /// （`ResourceEffects.cs:157-168`）要用它，而那一刻已经离开了节点。
        default_max: Option<i32>,
    },
    /// `LoseResourceEffectRequest`。
    LoseResource {
        /// 目标。
        target: Option<CombatantId>,
        /// 资源。
        key: ResourceId,
        /// 金额。
        amount: i32,
    },
    /// `CreateCardInstanceEffectRequest`（`CardCreationEffects.cs:3-…`）。
    CreateCardInstance {
        /// 归属战斗员。
        owner: CombatantId,
        /// 卡定义。
        definition: CardDefinitionId,
        /// 张数。
        count: i32,
        /// 落到哪个区。
        to_zone: CardZone,
    },
    /// `MoveCardToZoneEffectRequest`（`CardZoneEffects.cs:155-216`）。
    ///
    /// 来源有三个：出牌终态的落区（`Cards/CardPlay.cs:251-252`）、
    /// `moveCardToZone` 节点、以及 `cardInstance.iterated` 的循环体。
    MoveCardToZone {
        /// 归属战斗员。
        owner: CombatantId,
        /// 哪一张实例。
        card: CardInstanceId,
        /// 落哪个区。
        to_zone: CardZone,
        /// 插入位置。
        placement: ZonePlacement,
    },
}

impl Empty for EffectRequest {
    const EMPTY: Self = Self::ModifyStatusStacks {
        target: None,
        definition: StatusDefinitionId::EMPTY,
        delta: 0,
    };
}

/// 一条**待分发的事件**。参考的 `ICombatEvent`（39 + 2 条 `record`）。
///
/// ⚠️ 批次 1 只声明**接了线的那五种**（批次 1 的接线范围：四个回合边界 + `DamageDealt`）。
/// 变体是**数据形状**，接线是**行为**：接口按全集冻（41 个），但一个"没有任何生产者、
/// 也没有分发器"的变体只是噪声 —— 所以它跟着它的 raise 点一起进来（§4.1.5 末）。
///
/// **不带 `Kind`（伤害种类）**：参考的 `DamageDealtCombatEvent.Kind` 只被
/// `DamageDealtDamageKindTriggerFilter` 读，而触发器滤镜在本内核里**整体没有建模**
/// （镜像的 `Triggers[i]` 只有 `Event` + `Program`，没有 `Filters`、也没有 `Scope` ——
/// 见 `host.rs::decode_trigger` 的注释）。不带它意味着"按伤害种类过滤"**不可表达**，
/// 而不是"按错的种类过滤"；补它时要连滤镜层一起补。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CombatEvent {
    /// `TurnStartedCombatEvent`（`CombatTurnProcessor.cs:28-32`）。
    TurnStarted {
        /// 谁的回合开始了。
        combatant: CombatantId,
    },
    /// `TurnEndedCombatEvent`（`:61-65`）。
    TurnEnded {
        /// 谁的回合结束了。
        combatant: CombatantId,
    },
    /// `RoundStartedCombatEvent`（`:199-200`）。
    RoundStarted {
        /// 新的轮次号。
        round: i32,
    },
    /// `RoundEndedCombatEvent`（`:190-195`）。上下文读的是 `LastActiveCombatantId`。
    RoundEnded {
        /// 结束的轮次号。
        round: i32,
        /// 那一轮最后的行动者（参考的 `LastActiveCombatantId`）。
        last_active: Option<CombatantId>,
    },
    /// `DamageDealtCombatEvent`（`DamageEffects.cs:186-194` 的入队点）。
    ///
    /// 四个数字是参考的四个参数（`CombatEvents.cs:120-128`）：`HealthDamage` / `BlockedDamage` /
    /// `RequestedAmount` / `SourceCombatantId`。`SourceCardId` 今天没有读者（滤镜没建模），
    /// 所以不带 —— 它一进枚举就值 42 B/条。
    DamageDealt {
        /// 承受者（`TargetCombatantId`；上下文里的 `EventTargetId`）。
        target: CombatantId,
        /// 真的掉了几点血。
        health_damage: i32,
        /// 被防御池吸收了几点。
        blocked_damage: i32,
        /// 请求的金额（吸收前）。
        requested: i32,
        /// 出手方（`SourceCombatantId`）。`None` = 没有来源（选择器解出空集 / DoT 没有归属）。
        source: Option<CombatantId>,
    },
    /// `DamageReceivedCombatEvent`（`DamageEffects.cs:196-204`）：**承受者侧**的那一条。
    ///
    /// `DamageDealt` 的 Bearer 是**出手方**（所以 `doubt` 挂在打人的人身上）；这一条的 Bearer 是
    /// **承受者**，`Thorns` 就长在它上面（"谁打我，我打回去"）。
    ///
    /// 携带的字段只有两侧的 id：触发器节目要的是"谁打谁"，伤害数字在那条状态上已经读得到。
    DamageTaken {
        /// 承受者。
        target: CombatantId,
        /// 出手方（`None` = 无来源的伤害，触发器不跑 —— 参考的第一句就是 `SourceCombatant is not null`）。
        source: Option<CombatantId>,
    },
    /// `CardPlayed`（`CardPlay.cs:144`）：**有人打出了一张牌**。
    ///
    /// 派发给**所有战斗员**：`Enrage` 长在**敌人**身上而由**你出牌**触发，所以"只给出手的人"
    /// 这种过滤器在这里是错的（`port-plan.md` §117）。
    CardPlayed {
        /// 出牌的人。
        owner: CombatantId,
        /// 打出的那张牌（实例）。带上它，触发器才能问"这张牌有技能 tag 吗"
        /// （`Enrage` 只认技能牌）。
        card: crate::state::CardInstanceId,
    },
    /// `CardCostPaid`（`CardPlay.cs:138`）：出牌付了费用。
    CardCostPaid {
        /// 付钱的人。
        owner: CombatantId,
    },
    /// `StatusApplied`（新实例）/ `StatusMerged`（并入已有实例）：**状态落到了某个战斗员身上**。
    StatusApplied {
        /// 承受者。
        target: CombatantId,
    },
    /// 同上，但合进了已有实例（`StatusEffects.cs:135-139`）。
    StatusMerged {
        /// 承受者。
        target: CombatantId,
    },
    /// `StatusStacksChanged`：**层数变了**（`StatusEffects.cs:826-827` 的净变化非 0 才发）。
    StatusStacksChanged {
        /// 承受者。
        target: CombatantId,
    },
    /// `StatusApplicationPrevented`：**Artifact 挡掉了一次 debuff**。
    StatusApplicationPrevented {
        /// 挡住的那一方（Artifact 的主人）。
        target: CombatantId,
    },
    /// `StatusRemoved`：**一条状态实例没了**（层数归零被删、或到期）。
    StatusRemoved {
        /// 原承受者。
        target: CombatantId,
    },
    /// `Downed`（`CombatantLifecycleEffects.cs`）：**某个战斗员倒下了**。
    ///
    /// Bearer 是**倒下的那个**，`EventTarget` 是送他上路的人 —— `Spore Cloud` 就长在这上面
    /// （"我死了，给你 2 层虚弱"）。它**不受胜负判定约束**：整场打完也要报，所以分发时不看
    /// `state.result`。
    Downed {
        /// 倒下的战斗员。
        combatant: CombatantId,
        /// 出手方。
        source: Option<CombatantId>,
    },
}

impl Empty for CombatEvent {
    /// 空槽 = 一条"谁的回合开始了、那个人是空 id"的 `TurnStarted`。
    ///
    /// 它**不会被分发**：队列的 `len` 之后不会有条目，而 `pop_front` 只在 `len > 0` 时取值。
    /// 选这个变体是因为它是枚举里最大的几个之一（`CombatantId` 41 B），占位不会让
    /// `size_of::<Fifo<CombatEvent, 64>>()` 变小 —— 免得"空槽特别小"掩盖一条真实条目的尺寸。
    const EMPTY: Self = Self::TurnStarted {
        combatant: CombatantId::EMPTY,
    };
}

/// **续延**：参考的 `Queue<Action<CombatState>>` 的**数据**替代物（§4.1.3）。
///
/// 参考把闭包塞进队列，靠 GC 活着；内核是 `no_std` + 零分配 + `forbid(unsafe_code)`，
/// 装不下 `Box<dyn FnMut>`。⇒ 每一种"等会儿再做"都必须能写成数据。
///
/// ⚠️ **允许**把闭包当参数传进来立刻调用（`with_chain`）；**禁止**把闭包存进队列。
/// 这条不是风格问题：写成闭包后裸机目标直接编不过（`acceptance.ps1` 的第 3/5/6 道闸门会红）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Continuation {
    /// "某个节点槽的完成续延可以跑了"（`EffectProgramExecution.EnterContinuation` 的等价物）。
    ///
    /// ⚠️ **批次 2 的形状**：`node` 是**节点槽**下标（[`ProgramNodeSlot`]），不是 IR 节点下标 ——
    /// 一个 IR 节点可以被派发多次（`forEachTarget` / `forEachCardInZone` 的每一趟都派发一次
    /// `Body`），所以"哪一个**派发**完成了"只能由槽说，不能由节点说。
    ProgramResume {
        /// 节目帧槽。
        frame: ProgramExecutionSlot,
        /// 节点槽下标。
        node: u16,
    },
    /// 出牌动作的收尾（`Cards/CardPlay.cs:217` / `:292` 的 `EnqueueContinuation(CloseAction)`）。
    ///
    /// 它跑在**顶层**（`CombatEventHandling.cs:107-111`，此时 `CurrentEffectChain` 为 null）
    /// ⇒ 它内部那次 `EnqueueEvent(ActionResolved)` 会**建一条根链**（`CombatState.cs:442-452`）。
    /// 内核批次 1 用它表达的就是"这一笔发号"，见 `host.rs::run_continuation`。
    CloseAction {
        /// 收尾的是谁的动作。
        actor: CombatantId,
    },
}

/// ⚠️ **批次 2 删掉了 `ProgramTerminal` 这个变体。** 理由不是省内存，是它**做不到对的事**：
///
/// 参考的终态回调（`onTerminal`）是**同步**跑的 —— `MarkCompleted` → `RunTerminalCleanup`
/// （`Effects/Programs/EffectProgramIdentity.cs:121-129, 104-111`），也就是在"最后一个节点完成"
/// 那个续延体的**同一栈帧**里。把它塞进续延队列会把它挪到**顶层**（`CombatEventHandling.cs:107-111`
/// 时 `CurrentEffectChain` 为 null），于是它里面每一次 `EnqueueEffect`/`EnqueueEvent` 都会
/// `?? CreateRootEffectChain()` ⇒ **每次出牌多一个 `chain_num`**。
/// 那不是"晚一点跑"，是**换了一条链**。⇒ 终态回调由 `exec.rs` 同步调用（见 `exec::finish_frame`），
/// 它需要的那点数据（谁的牌、落哪个区）作为**数据**存在帧上（[`ProgramTerminalHook`]），
// 不是闭包 —— §4.1.3 那条"续延只能是数据"仍然成立。
impl Empty for Continuation {
    const EMPTY: Self = Self::CloseAction {
        actor: CombatantId::EMPTY,
    };
}

// =============================================================================================
// 节目帧调度（批次 2）：帧 / 节点槽 / 循环快照
// =============================================================================================
//
// # 参考里的三样东西，以及这里为什么是定容数组
//
// 参考把**完成**推迟成 `Action<CombatState>` 闭包塞进 `_pendingContinuations`
// （`CombatState.cs:461-470`）：
//
// * 一个闭包捕获"我完成后要减谁的计数" —— 本模块用 [`ProgramNodeSlot::parent`]（显式父链）；
// * `SequenceNodeExecutor` 捕获 `var remaining = new[] { children.Length }`（`EffectProgramNodeExecutors.cs:202`）
//   —— 本模块用 [`ProgramNodeSlot::remaining`]；
// * `ForEach*NodeExecutor` 捕获 `CardInstanceId[]` / `CombatantId[]` 快照
//   （`:465`、`:386-388`）—— 本模块用 [`ProgramLoop`] 的定容列表。
//
// ⇒ 闭包**一个都不存**（`no_std` + 零分配 + `forbid(unsafe_code)` 下也存不了），
// 存的是"闭包捕获了什么"这件事本身。语义上的等价物是：
// **一个完成续延 = `(frame, 节点槽)`；节点槽带着父与计数。**

/// 同时在飞的节目帧数上限（`EffectProgramExecutionFrame`）。
///
/// **不是预算杠杆**：放大它不改变任何一个已能跑通的局面的行为，只把"这个局面跑不了"推远。
/// 需要 >1 的理由是**嵌套**：外层节目的效果还在队列里等解析时，那条效果的解析可以派发
/// 一个触发器节目（`host.rs::run_damage_dealt_triggers`），两个帧同时活着。
pub const MAX_PROGRAM_FRAMES: usize = 8;
/// 同时在飞的"等完成"节点槽上限。一次节目派发**先把整棵树派发完**再开始完成
/// （`EffectProgramNodeExecutors.cs:202-211`），所以峰值 ≈ 节目树节点数。
/// 64 是当前镜像最大树（`_recon_card.py census`）的若干倍，**到顶响亮失败**。
pub const MAX_PROGRAM_NODE_SLOTS: usize = 64;
/// 同时在飞的循环迭代快照上限。每层 `forEach*` 占一个；嵌套循环 + 嵌套帧同时循环才 >1。
pub const MAX_PROGRAM_LOOPS: usize = 4;

/// "没有父节点槽"（= 这个节点直接挂在帧根上）。
pub const NO_NODE_SLOT: u16 = u16::MAX;
/// "没有循环快照"。
pub const NO_LOOP: u8 = u8::MAX;

/// 帧的生命周期状态（`EffectProgramExecutionState`，`EffectProgramIdentity.cs:5-14`）。
///
/// 只保留四个：`Created`/`Running` 在参考里区分的唯一后果是 `MarkRunning` 那条断言，
/// 而 `WaitingFor*` 三个变体在 v1 的战斗路径上**没有生产者**（原生操作/反应边界还没移植）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProgramFrameState {
    /// 在跑（还有节点槽没完成）。
    Running,
    /// 正常走完（`MarkCompleted`）。
    Completed,
    /// 战斗中途结束被取消（`CancelDueToCombatEnd`）。
    Cancelled,
    /// 节点/解析抛错（`MarkFaulted`）。
    Faulted,
}

/// 帧的**终态回调**：参考的 `onTerminal`（`EffectProgramIdentity.cs:96-111`）。
///
/// 参考是闭包；这里是**数据**。今天唯一的生产者是出牌（`Cards/CardPlay.cs:242-263`）：
/// 节目终态时把打出的那张牌落区、然后 `CloseAction`。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProgramTerminalHook {
    /// 没有终态回调（触发器节目、敌人动作节目都是这一类）。
    None,
    /// 出牌节目的落区回调（`Cards/CardPlay.cs:245-263`）。
    CardPlay {
        /// 谁打的。
        player: CombatantId,
        /// 哪一张实例。
        card: CardInstanceId,
        /// 落哪个区（`PlayedCardDestination`，`:298-302`）。
        destination: CardZone,
    },
}

impl Empty for ProgramTerminalHook {
    const EMPTY: Self = Self::None;
}

/// 一个在飞的节目帧。
///
/// 字段与参考的对应关系（全部逐行读过）：
/// * `execution_number` ← `EffectProgramExecutor.Execute` 里那次
///   `AllocateProgramExecutionId()`（`EffectProgramExecution.cs:27`）；
/// * `chain` ← `executionContext.EffectChain ??= combat.CurrentEffectChain ?? CreateRootEffectChain()`
///   （`:31`）—— **程序自己的链**；`forEach*` 的下一趟在它里面接着跑（`:502`、`:244`）；
/// * `steps` / `max_steps` ← `executionContext.ProgramStepCount` / `MaxProgramSteps`（`:109-114`）；
/// * `source` / `target` / `iteration_target` / `iteration_card` ← 执行上下文里那几个槽
///   （`ExecContext` 的同名字段；参考靠闭包捕获，我们靠帧）；
/// * `state` / `terminal_chain` ← `State` 与"终态那一刻的 `CurrentEffectChain`"。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProgramExecutionFrame {
    /// 已分配的执行号（`exec_num` 那一列）。**分配发生在帧建立时**，与参考同序。
    pub execution_number: i64,
    /// 节目根节点（IR 下标）。
    pub root: u16,
    /// 节目自己的效果链（arena 槽）。
    pub chain: ChainSlot,
    /// 出手方（`sel.source`）。
    pub source: Option<CombatantId>,
    /// 事件目标（`sel.eventTarget`）。
    pub target: Option<CombatantId>,
    /// 当前迭代目标（`sel.iterationTarget`）。
    pub iteration_target: Option<CombatantId>,
    /// **进来时**的迭代目标（`Execute` 那一刻的 `ctx.iteration_target`）。
    ///
    /// 用途只有一个：帧进入终态时把"当前"那两个字段还原成它 —— 参考里"作用域在 continuation
    /// 里关闭"是**无条件**的（`EffectProgramNodeExecutors.cs:484-485`），异常路径上外层上下文
    /// 原样保留。没有这两个字段，`forEachCardInZone` 的 Body 一报错就会把迭代卡**留在帧上**
    /// （`e2e_19h` 的 (b) 半钉的正是这一条）。
    pub entry_iteration_target: Option<CombatantId>,
    /// **进来时**的迭代卡（同上）。
    pub entry_iteration_card: Option<CardInstanceId>,
    /// 当前迭代卡（`cardInstance.iterated`）。
    ///
    /// 与 `ExecContext::iteration_card` **同型**（`CardInstanceId`）：循环快照存的是**槽位**
    /// （省内存），每一趟开始时再换成 id —— 换的那一刻卡必须还在池里（换不到 ⇒ `IrError::Slot`）。
    pub iteration_card: Option<CardInstanceId>,
    /// 已走的步数（`ProgramStepCount`）。
    pub steps: u32,
    /// 步数上限（信封上的 `MaxProgramSteps`）。
    pub max_steps: u32,
    /// **X 费牌的 X**（§146）：这一次出牌花掉了多少能量。
    ///
    /// 存在帧上而不是只放上下文里：节目的后续节点是在**续延**里派的，那时上下文是从这一帧
    /// 重建出来的（`exec::frame_context`）；只放上下文里的结果就是"第一趟读到 X，第二趟读到 0"。
    pub x_cost: i32,
    /// 生命周期状态。
    pub state: ProgramFrameState,
    /// **终态那一刻**的环境链 —— 它是 `chain_num` 的唯一判据，见 `exec::finish_frame`。
    pub terminal_chain: ChainSlot,
    /// 终态回调。
    pub hook: ProgramTerminalHook,
    /// 槽是否在用。
    pub live: bool,
}

impl Empty for ProgramExecutionFrame {
    const EMPTY: Self = Self {
        execution_number: 0,
        root: 0,
        chain: ChainSlot::NONE,
        source: None,
        target: None,
        iteration_target: None,
        iteration_card: None,
        entry_iteration_target: None,
        entry_iteration_card: None,
        steps: 0,
        max_steps: 0,
        x_cost: 0,
        state: ProgramFrameState::Running,
        terminal_chain: ChainSlot::NONE,
        hook: ProgramTerminalHook::None,
        live: false,
    };
}

/// 帧 arena：定容数组 + `live` 标记（下标必须稳定 —— 续延里存的是下标）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProgramFrameArena {
    frames: [ProgramExecutionFrame; MAX_PROGRAM_FRAMES],
    len: u8,
}

impl ProgramFrameArena {
    /// 空 arena。
    #[must_use]
    pub const fn new() -> Self {
        Self {
            frames: [ProgramExecutionFrame::EMPTY; MAX_PROGRAM_FRAMES],
            len: 0,
        }
    }

    /// 在用的帧数。
    #[must_use]
    pub fn live(&self) -> usize {
        self.len as usize
    }

    /// 分配一帧。装不下 ⇒ `Full(Container::ProgramFrames)`（**不覆盖别人的帧**）。
    pub fn alloc(&mut self, frame: ProgramExecutionFrame) -> StateResult<ProgramExecutionSlot> {
        for (index, slot) in self.frames.iter_mut().enumerate() {
            if slot.live {
                continue;
            }
            *slot = ProgramExecutionFrame { live: true, ..frame };
            self.len += 1;
            return Ok(ProgramExecutionSlot::from_index(index));
        }
        Err(CapacityError::Full(Container::ProgramFrames))
    }

    /// 读一帧。
    #[must_use]
    pub fn get(&self, slot: ProgramExecutionSlot) -> Option<&ProgramExecutionFrame> {
        self.frames.get(slot.index()).filter(|frame| frame.live)
    }

    /// 写一帧。
    pub fn get_mut(&mut self, slot: ProgramExecutionSlot) -> Option<&mut ProgramExecutionFrame> {
        self.frames.get_mut(slot.index()).filter(|frame| frame.live)
    }

    /// 回收一帧（下标可以被后来者复用）。
    pub fn free(&mut self, slot: ProgramExecutionSlot) {
        if let Some(frame) = self.frames.get_mut(slot.index()) {
            if frame.live {
                *frame = ProgramExecutionFrame::EMPTY;
                self.len -= 1;
            }
        }
    }

    /// 清空。
    pub fn clear(&mut self) {
        self.frames = [ProgramExecutionFrame::EMPTY; MAX_PROGRAM_FRAMES];
        self.len = 0;
    }

    /// 逐个在用帧（下标升序）。
    pub fn iter_live(&self) -> impl Iterator<Item = (usize, &ProgramExecutionFrame)> {
        self.frames
            .iter()
            .enumerate()
            .filter(|(_, frame)| frame.live)
    }
}

impl Default for ProgramFrameArena {
    fn default() -> Self {
        Self::new()
    }
}

/// 一个"派发出去、还没完成"的节点。
///
/// 参考里它是闭包捕获的两样东西的合体：**父是谁**（谁数剩余）与**我自己数到几了**。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProgramNodeKind {
    /// 空槽。
    Free,
    /// 叶子节点：它自己的完成 `EnqueueContinuation` 一发，就只剩"通知父"。
    Leaf,
    /// `Sequence`：`remaining` 是**还没完成的子节点数**（`:202-211`）。
    Sequence,
    /// 直通节点（`Conditional` 的分支、循环体）：完成即通知父。
    Pass,
    /// `forEach*` 循环：`remaining` 是**下一个要跑的下标**。
    Loop,
}

/// 一个节点槽。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProgramNodeSlot {
    /// 属于哪个帧（arena 下标）。
    pub frame: u8,
    /// 槽的种类。
    pub kind: ProgramNodeKind,
    /// 派发的那个 IR 节点（循环要重派 `Body` 时用它）。
    pub node: u16,
    /// 父槽；[`NO_NODE_SLOT`] = 直接挂在帧根上（它的完成 = 节目的完成）。
    pub parent: u16,
    /// `Sequence`：未完成子节点数；`Loop`：下一个下标。
    pub remaining: u16,
    /// `Loop`：迭代快照下标；[`NO_LOOP`] = 没有。
    pub loop_at: u8,
    /// 槽是否在用。
    pub live: bool,
}

impl Empty for ProgramNodeSlot {
    const EMPTY: Self = Self {
        frame: 0,
        kind: ProgramNodeKind::Free,
        node: 0,
        parent: NO_NODE_SLOT,
        remaining: 0,
        loop_at: NO_LOOP,
        live: false,
    };
}

/// 节点槽 arena。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProgramNodeArena {
    slots: [ProgramNodeSlot; MAX_PROGRAM_NODE_SLOTS],
    len: u8,
}

impl ProgramNodeArena {
    /// 空 arena。
    #[must_use]
    pub const fn new() -> Self {
        Self {
            slots: [ProgramNodeSlot::EMPTY; MAX_PROGRAM_NODE_SLOTS],
            len: 0,
        }
    }

    /// 在用的槽数。
    #[must_use]
    pub fn live(&self) -> usize {
        self.len as usize
    }

    /// 分配一个槽。
    pub fn alloc(&mut self, slot: ProgramNodeSlot) -> StateResult<u16> {
        for (index, cell) in self.slots.iter_mut().enumerate() {
            if cell.live {
                continue;
            }
            *cell = ProgramNodeSlot { live: true, ..slot };
            self.len += 1;
            return u16::try_from(index)
                .map_err(|_| CapacityError::Full(Container::ProgramNodeSlots));
        }
        Err(CapacityError::Full(Container::ProgramNodeSlots))
    }

    /// 读一个槽。
    #[must_use]
    pub fn get(&self, index: u16) -> Option<&ProgramNodeSlot> {
        self.slots.get(usize::from(index)).filter(|slot| slot.live)
    }

    /// 写一个槽。
    pub fn get_mut(&mut self, index: u16) -> Option<&mut ProgramNodeSlot> {
        self.slots
            .get_mut(usize::from(index))
            .filter(|slot| slot.live)
    }

    /// 回收一个槽。
    pub fn free(&mut self, index: u16) {
        if let Some(slot) = self.slots.get_mut(usize::from(index)) {
            if slot.live {
                *slot = ProgramNodeSlot::EMPTY;
                self.len -= 1;
            }
        }
    }

    /// 回收某个帧的全部槽（帧结束时兜底；正常路径上它们已经各自完成）。
    pub fn free_frame(&mut self, frame: u8) {
        for index in 0..self.slots.len() {
            let dead = self
                .slots
                .get(index)
                .is_some_and(|slot| slot.live && slot.frame == frame);
            if dead {
                self.free(u16::try_from(index).unwrap_or(0));
            }
        }
    }

    /// 清空。
    pub fn clear(&mut self) {
        self.slots = [ProgramNodeSlot::EMPTY; MAX_PROGRAM_NODE_SLOTS];
        self.len = 0;
    }
}

impl Default for ProgramNodeArena {
    fn default() -> Self {
        Self::new()
    }
}

/// 循环迭代的**快照**（参考在派发那一刻就 `ToArray()`，之后不再重解，`:465`、`:386-388`）。
///
/// 为什么必须快照、不能每轮重解：`forEachCardInZone` 的 Body 常常**把卡搬走**
/// （`shredder_drawer` 把整只手进消耗堆），重解会让"第二趟"看到一张不同的牌区。
/// 参考的注释把这件事写明在 `:447-448`。
///
/// ⚠️ `clippy::large_enum_variant`：两个变体的尺寸差就是**这一层的全部内容**
/// （目标快照 12 × 41 B、卡快照 96 × 2 B）。压平它需要 `unsafe` 的 union
/// （`#![forbid(unsafe_code)]` 禁止）或装箱（零分配禁止）⇒ 这里显式 allow，
/// 并把"差多少"写出来而不是藏起来。
#[allow(clippy::large_enum_variant)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProgramLoopList {
    /// 空槽。
    None,
    /// 目标快照（`forEachTarget`，`CombatantId[]`）。
    Targets(Bounded<CombatantId, MAX_COMBATANTS>),
    /// 卡快照（`forEachCardInZone`，`CardInstanceId[]` 的槽位表示，见 `exec.rs` 的说明）。
    Cards(Bounded<CardSlot, MAX_CARDS_PER_ZONE>),
    /// **次数**（`node.repeat`，§146）：没有可绑的变量，只有"跑几遍"。
    ///
    /// 单独一个变体而不是复用 `Targets` 造一堆假目标：`repeat` 的语义里**没有**迭代对象
    /// （`sel.iterationTarget` 在 X 费牌里必须还是外层那个），造点假人会让选择器读到错的东西。
    Count(u16),
}

impl ProgramLoopList {
    /// 快照长度。
    #[must_use]
    pub fn len(&self) -> usize {
        match self {
            Self::None => 0,
            Self::Targets(list) => list.len(),
            Self::Cards(list) => list.len(),
            Self::Count(count) => usize::from(*count),
        }
    }

    /// 是否为空。
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

/// 一层循环的迭代状态。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProgramLoop {
    /// 快照。
    pub list: ProgramLoopList,
    /// 进循环前的迭代目标（`PushIterationTarget` 的旧值，`:419`）。
    pub saved_target: Option<CombatantId>,
    /// 进循环前的迭代卡（`PushIterationCard` 的旧值，`:495`）。
    pub saved_card: Option<CardInstanceId>,
    /// 迭代体（`Body` 的 IR 下标）。
    pub body: u16,
    /// 槽是否在用。
    pub live: bool,
}

impl Empty for ProgramLoop {
    const EMPTY: Self = Self {
        list: ProgramLoopList::None,
        saved_target: None,
        saved_card: None,
        body: 0,
        live: false,
    };
}

/// 循环快照 arena。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProgramLoopArena {
    loops: [ProgramLoop; MAX_PROGRAM_LOOPS],
    len: u8,
}

impl ProgramLoopArena {
    /// 空 arena。
    #[must_use]
    pub const fn new() -> Self {
        Self {
            loops: [ProgramLoop::EMPTY; MAX_PROGRAM_LOOPS],
            len: 0,
        }
    }

    /// 在用的层数。
    #[must_use]
    pub fn live(&self) -> usize {
        self.len as usize
    }

    /// 分配一层。
    pub fn alloc(&mut self, entry: ProgramLoop) -> StateResult<u8> {
        for (index, cell) in self.loops.iter_mut().enumerate() {
            if cell.live {
                continue;
            }
            *cell = ProgramLoop { live: true, ..entry };
            self.len += 1;
            return u8::try_from(index).map_err(|_| CapacityError::Full(Container::ProgramLoops));
        }
        Err(CapacityError::Full(Container::ProgramLoops))
    }

    /// 读一层。
    #[must_use]
    pub fn get(&self, index: u8) -> Option<&ProgramLoop> {
        self.loops.get(usize::from(index)).filter(|entry| entry.live)
    }

    /// 写一层。
    pub fn get_mut(&mut self, index: u8) -> Option<&mut ProgramLoop> {
        self.loops
            .get_mut(usize::from(index))
            .filter(|entry| entry.live)
    }

    /// 回收一层。
    pub fn free(&mut self, index: u8) {
        if let Some(entry) = self.loops.get_mut(usize::from(index)) {
            if entry.live {
                *entry = ProgramLoop::EMPTY;
                self.len -= 1;
            }
        }
    }

    /// 清空。
    pub fn clear(&mut self) {
        self.loops = [ProgramLoop::EMPTY; MAX_PROGRAM_LOOPS];
        self.len = 0;
    }
}

impl Default for ProgramLoopArena {
    fn default() -> Self {
        Self::new()
    }
}

/// **集合型事件**携带的 id 列表。容量 [`MAX_EVENT_ID_LIST`]，**超出响亮失败**。
///
/// 为什么元素是 `Ident<INSTANCE_ID_CAP>`（17 B）而不是各事件的真实 id 类型：集合型事件带的是
/// `StatusInstanceId` / `CardInstanceId` 两种（参考的 `IReadOnlyCollection<CardInstanceId>` 等），
/// 两者的线上形状都是 `status_%06d` / `card_%06d`（≤16 B）。合成一个 17 B 的元素，
/// 就让"一条事件的集合载荷"有**一个**尺寸，而不是每个事件各带一份。真需要类型区分时
/// 由**事件自己的变体**区分（`StatusRemoved` 里的 id 一定是状态实例号）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventIdList {
    ids: [Ident<INSTANCE_ID_CAP>; MAX_EVENT_ID_LIST],
    len: u8,
}

impl EventIdList {
    /// 空列表。
    #[must_use]
    pub const fn new() -> Self {
        Self {
            ids: [Ident::EMPTY; MAX_EVENT_ID_LIST],
            len: 0,
        }
    }

    /// 已有几条。
    #[must_use]
    pub fn len(&self) -> usize {
        self.len as usize
    }

    /// 是否为空。
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    /// 用到的前缀。
    #[must_use]
    pub fn as_slice(&self) -> &[Ident<INSTANCE_ID_CAP>] {
        &self.ids[..self.len as usize]
    }

    /// 追加一个 id。**装不下就是错误，永不截断、永不覆盖**（§4.3 末的硬规则）。
    ///
    /// 调用方（事件的生产者）该把 `CapacityError::Full(Container::EventIdList)` 映射成
    /// `BindError::BufferTooSmall { needed, have }` —— 那个变体的注释原文就是
    /// "**不截断**：少读几条触发器等于内容静默不发作"（`status_bind.rs:378`）。
    pub fn push(&mut self, id: Ident<INSTANCE_ID_CAP>) -> StateResult<()> {
        let at = self.len as usize;
        if at == MAX_EVENT_ID_LIST {
            return Err(CapacityError::Full(Container::EventIdList));
        }
        let Some(slot) = self.ids.get_mut(at) else {
            return Err(CapacityError::Full(Container::EventIdList));
        };
        *slot = id;
        self.len += 1;
        Ok(())
    }
}

impl Empty for EventIdList {
    const EMPTY: Self = Self::new();
}

impl Default for EventIdList {
    fn default() -> Self {
        Self::new()
    }
}

/// 定容 **FIFO 队列**：环形缓冲（`head` + `len`），语义逐字对照 `Queue<T>`。
///
/// 为什么不是 [`Bounded`]：`Bounded` 是 push-only（只有 `pop` 从**尾部**取），而队列必须从
/// **头部**取（`Queue<T>.Dequeue`，`CombatState.cs:429-440` / `:480-490`）。用 `Bounded` 的
/// `remove(0)` 会让每次出队搬 64 条 × 176 B ≈ 11 KB —— 在裸机上那是"能跑但很蠢"。
///
/// `N` 必须是 ≤ 255：`head`/`len` 是 `u8`（与 `Bounded` 同一条约定，省 14 B/队列）。
/// ⚠️ 这条约束**由下面的 `const` 断言守**，不是靠注释：把容量调到 300 时 `self.len += 1`
/// 会在 255 处**回绕**，于是队列"看起来没满"却覆盖第 0 条 —— 又一个静默截断。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Fifo<T, const N: usize> {
    items: [T; N],
    head: u8,
    len: u8,
}

// 三条队列的实际容量必须在 `u8` 范围内（见上）。放成 `const _` ⇒ **编译期**失败，
// 而不是运行时静默回绕。
const _: () = assert!(
    MAX_PENDING_EFFECTS <= u8::MAX as usize
        && MAX_PENDING_EVENTS <= u8::MAX as usize
        && MAX_PENDING_CONTINUATIONS <= u8::MAX as usize,
    "Fifo 的 head/len 是 u8：队列容量一旦超过 255，`len += 1` 会回绕成 0"
);

impl<T: Empty, const N: usize> Fifo<T, N> {
    /// 空队列。
    #[must_use]
    pub const fn new() -> Self {
        Self {
            items: [T::EMPTY; N],
            head: 0,
            len: 0,
        }
    }

    /// 已有几条。
    #[must_use]
    pub fn len(&self) -> usize {
        self.len as usize
    }

    /// 是否为空。
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    /// 入队（尾部）。满了返回 [`CapacityError::Full`] —— **不丢条目**。
    pub fn push(&mut self, value: T, what: Container) -> StateResult<()> {
        if self.len as usize == N {
            return Err(CapacityError::Full(what));
        }
        let at = (usize::from(self.head) + usize::from(self.len)) % N;
        let Some(slot) = self.items.get_mut(at) else {
            return Err(CapacityError::Full(what));
        };
        *slot = value;
        self.len += 1;
        Ok(())
    }

    /// 出队（头部）。腾出的槽写回 `T::EMPTY`（与 `Bounded::pop` 同一条不变式）。
    pub fn pop_front(&mut self) -> Option<T> {
        if self.len == 0 {
            return None;
        }
        let at = usize::from(self.head);
        let value = *self.items.get(at)?;
        if let Some(slot) = self.items.get_mut(at) {
            *slot = T::EMPTY;
        }
        self.head = ((at + 1) % N) as u8;
        self.len -= 1;
        Some(value)
    }

    /// 清空（**整块**写回空值，不只是把 `len` 归零）。
    pub fn clear(&mut self) {
        self.items = [T::EMPTY; N];
        self.head = 0;
        self.len = 0;
    }
}

impl<T: Empty, const N: usize> Empty for Fifo<T, N> {
    const EMPTY: Self = Self::new();
}

impl<T: Empty, const N: usize> Default for Fifo<T, N> {
    fn default() -> Self {
        Self::new()
    }
}

/// 出队的一条效果（参考的 `PendingEffectQueueEntry`，`CombatEffectChain.cs:86-88`）。
///
/// 参考把三列分开存；出队时合成**一条记录**再交给解析器 —— 本模块的
/// [`CombatState::dequeue_effect`] 就是那一步。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EffectItem {
    /// 请求本体。
    pub request: EffectRequest,
    /// 它属于哪条链（`ChainSlot::NONE` = 顶层、没有链）。
    pub chain: ChainSlot,
    /// 解析失败时要绑回去的节目帧（`None` = 不是任何帧发起的）。
    pub owner: Option<ProgramExecutionSlot>,
}

/// 出队的一条事件（参考的 `PendingEventQueueEntry`，`CombatEffectChain.cs:89-91`）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventItem {
    /// 事件本体。
    pub event: CombatEvent,
    /// 它属于哪条链。
    pub chain: ChainSlot,
}

// ---------------------------------------------------------------------------------------------
// The state
// ---------------------------------------------------------------------------------------------

/// The hash-relevant state of one fight. See the module header.
#[derive(Clone, Copy)]
pub struct CombatState {
    pub id: CombatId,
    pub random_seed: i32,
    pub random_step: i32,
    pub result: CombatResult,
    pub current_round: i32,
    pub current_turn: i32,
    pub turn_phase: CombatTurnPhase,
    pub active_combatant_id: Option<CombatantId>,
    /// Set by [`EffectRequest::EndTurn`]; the battle loop ends the turn and clears it. It is **not**
    /// cleared by the effect itself, because "who honours the request" must stay visible.
    pub end_turn_requested: bool,
    /// How many times a turn has been **cut short** by `node.endTurn` (`port-plan.md` §126).
    ///
    /// A counter, not a flag: the UI polls it and shows "your turn was ended" when it changes, which
    /// survives the fact that the flag itself is consumed inside the battle loop.
    pub forced_turn_ends: i32,
    /// Who gets **another turn in a row** when their current one ends (`node.extraTurn`,
    /// `port-plan.md` §127). Cleared when honoured.
    pub extra_turn_for: Option<CombatantId>,
    /// Cards played **this turn** and **last turn** (`port-plan.md` §128).
    ///
    /// Turn-scoped totals, not per-combatant: only the hero plays cards today, and the intent
    /// condition that needs them (`opponentCardsPlayed`) asks about "the other side" as a whole.
    /// Rolled at every turn boundary in `turn.rs`.
    pub cards_played_this_turn: i32,
    /// See [`Self::cards_played_this_turn`].
    pub cards_played_last_turn: i32,
    pub next_status_instance_number: i32,
    /// 下一个 `node.createCombatant` 造出来的战斗员的编号（分裂/召唤）。
    ///
    /// 单独一个计数器而不是复用别的：实例号进哈希、进快照，混用会让"同一局面"因为
    /// 之前造过几张牌而分叉。
    pub next_combatant_number: i32,
    pub next_card_instance_number: i32,
    pub next_effect_chain_number: i64,
    pub next_program_execution_id: i64,
    turn_order: Bounded<CombatantId, MAX_COMBATANTS>,
    combatants: Bounded<Combatant, MAX_COMBATANTS>,
    global_statuses: Bounded<StatusInstance, MAX_GLOBAL_STATUSES>,
    card_zones: Bounded<CardZones, MAX_COMBATANTS>,
    cards: Bounded<CardInstance, MAX_CARD_INSTANCES>,
    temporary_rules: Bounded<TemporaryRule, MAX_TEMPORARY_RULES>,
    // ---- 事件队列（批次 1）。**六个队列 + 一条拿链的作用域**，见上面那一节的模块注释。 ----
    //
    // 六个队列**都不进哈希、不进快照**（`CombatStateHasher.cs:26-72` 里没有它们，
    // `CombatStateSnapshot.cs:120-151` 也没有）：参考自己把它们划成**输出**
    // （"Excludes transient execution queues"，`CombatStateSnapshot.cs:94`）。
    // ⇒ 加这些字段**不移动任何基线**，除非它们的**后果**（`exec_num` / `chain_num`）变了。
    pending_effects: Fifo<EffectRequest, MAX_PENDING_EFFECTS>,
    pending_effect_chains: Fifo<ChainSlot, MAX_PENDING_EFFECTS>,
    pending_effect_owners: Fifo<Option<ProgramExecutionSlot>, MAX_PENDING_EFFECTS>,
    pending_events: Fifo<CombatEvent, MAX_PENDING_EVENTS>,
    pending_event_chains: Fifo<ChainSlot, MAX_PENDING_EVENTS>,
    pending_continuations: Fifo<Continuation, MAX_PENDING_CONTINUATIONS>,
    chains: ChainArena,
    /// `EnterEffectChain` 的作用域（`CombatState.cs:500-511`）。
    ///
    /// 参考是 `CurrentEffectChain { get; private set; }`，只在 `using (EnterEffectChain(c))` 里非 null。
    /// 它决定两件事：①入队时要不要**新建根链**（`CurrentEffectChain ?? CreateRootEffectChain()`，
    /// `:386`/`:446`）；②触发链的**父**是谁（`:492-498`）。
    ///
    /// ⚠️ **批次 2 起这个字段真的被填满了**：出牌/敌动作的节目在
    /// `with_chain(节目链, ..)` 里派发（`exec::begin`），效果的解析在
    /// `with_chain(条目链, ..)` 里跑（`host.rs::resolve_pending_effects`），触发器分发同理。
    /// 于是"入队要不要发号"这个判断（`CombatState.cs:386`/`:446` 的 `??`）在**每一步**都有
    /// 真实输入 —— 不再是批次 1 那种"恒为 None、恰好同数"。
    current_chain: ChainSlot,
    // ---- 节目帧调度（批次 2），见上面那一节的模块注释 ----
    //
    // 三样都**不进哈希、不进快照**（`CombatStateHasher.cs:26-72` 里没有它们）：参考把它们
    // 等同构在 GC 堆上的帧对象/闭包里。⇒ 加它们不移动基线，除非它们的**后果**
    // （`exec_num` / `chain_num`）变了。
    program_frames: ProgramFrameArena,
    program_nodes: ProgramNodeArena,
    program_loops: ProgramLoopArena,
    // ---- 动画日志（§142）----
    //
    // **不进哈希、不进快照**，理由与节目帧那一节同型：它记的是"已经发生过什么"，
    // 不是"以后会怎样"。两个只在日志上不同的局面，后续行为逐字相同 —— 所以它不该
    // 移动任何基线（加它之前与之后 `hash_golden` 的字节完全一样）。
    beat_log: crate::beat::BeatLog,
}

impl CombatState {
    // ---- 节目帧调度（批次 2）------------------------------------------------------------------

    /// 帧 arena（读）。
    #[must_use]
    pub fn program_frames(&self) -> &ProgramFrameArena {
        &self.program_frames
    }

    /// 帧 arena（写）。
    pub fn program_frames_mut(&mut self) -> &mut ProgramFrameArena {
        &mut self.program_frames
    }

    /// 节点槽 arena（读）。
    #[must_use]
    pub fn program_nodes(&self) -> &ProgramNodeArena {
        &self.program_nodes
    }

    /// 节点槽 arena（写）。
    pub fn program_nodes_mut(&mut self) -> &mut ProgramNodeArena {
        &mut self.program_nodes
    }

    /// 循环快照 arena（读）。
    #[must_use]
    pub fn program_loops(&self) -> &ProgramLoopArena {
        &self.program_loops
    }

    /// 循环快照 arena（写）。
    pub fn program_loops_mut(&mut self) -> &mut ProgramLoopArena {
        &mut self.program_loops
    }

    /// 还有没有在飞的节目帧（诊断 + 排空循环用）。
    #[must_use]
    pub fn live_program_frames(&self) -> usize {
        self.program_frames.live()
    }

    /// 动画日志（读）。对外接口在 [`crate::beat`]：`beats()` / `beat_def_text()` /
    /// `beats_dropped()` / `clear_beats()`。
    #[must_use]
    pub(crate) fn beat_log(&self) -> &crate::beat::BeatLog {
        &self.beat_log
    }

    /// 动画日志（写）。**只有 [`crate::beat`] 的埋点函数该调它。**
    pub(crate) fn beat_log_mut(&mut self) -> &mut crate::beat::BeatLog {
        &mut self.beat_log
    }
}

impl core::fmt::Debug for CombatState {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_struct("CombatState")
            .field("id", &self.id)
            .field("random_seed", &self.random_seed)
            .field("random_step", &self.random_step)
            .field("result", &self.result)
            .field("current_round", &self.current_round)
            .field("current_turn", &self.current_turn)
            .field("turn_phase", &self.turn_phase)
            .field("active_combatant_id", &self.active_combatant_id)
            .field("next_status_instance_number", &self.next_status_instance_number)
            .field("next_card_instance_number", &self.next_card_instance_number)
            .field("next_effect_chain_number", &self.next_effect_chain_number)
            .field("next_program_execution_id", &self.next_program_execution_id)
            .field("turn_order", &self.turn_order)
            .field("combatants", &self.combatants)
            .field("global_statuses", &self.global_statuses)
            .field("card_zones", &self.card_zones)
            .field("cards", &self.cards)
            .field("temporary_rules", &self.temporary_rules)
            .finish()
    }
}

/// ⚠️ **别拿它做“整体重置”**（`*state = CombatState::EMPTY` / `*state = CombatState::new(..)`）：
/// 184,648 B 的常量值会原样进 `.wasm` 的 rodata，并被 `memcpy` 一次。要重置请用
/// [`CombatState::reset_in_place`]。这个常量本身仍然有用（`Bounded`/`Default` 那条路要它，
/// 而且 `blank_matches_empty` 拿它当基准），只是**不该被复制**。
impl Empty for CombatState {
    const EMPTY: Self = Self {
        id: CombatId::EMPTY,
        random_seed: 0,
        random_step: 0,
        result: CombatResult::Ongoing,
        current_round: 0,
        current_turn: 0,
        turn_phase: CombatTurnPhase::WaitingToStartTurn,
        active_combatant_id: None,
        end_turn_requested: false,
        forced_turn_ends: 0,
        extra_turn_for: None,
        cards_played_this_turn: 0,
        cards_played_last_turn: 0,
        next_status_instance_number: 0,
            next_combatant_number: 0,
        next_card_instance_number: 0,
        next_effect_chain_number: 0,
        next_program_execution_id: 0,
        turn_order: Bounded::new(),
        combatants: Bounded::new(),
        global_statuses: Bounded::new(),
        card_zones: Bounded::new(),
        cards: Bounded::new(),
        temporary_rules: Bounded::new(),
        pending_effects: Fifo::new(),
        pending_effect_chains: Fifo::new(),
        pending_effect_owners: Fifo::new(),
        pending_events: Fifo::new(),
        pending_event_chains: Fifo::new(),
        pending_continuations: Fifo::new(),
        chains: ChainArena::new(),
        current_chain: ChainSlot::NONE,
        program_frames: ProgramFrameArena::new(),
        program_nodes: ProgramNodeArena::new(),
        program_loops: ProgramLoopArena::new(),
        beat_log: crate::beat::BeatLog::new(),
    };
}

impl CombatState {
    /// A fresh fight: round 1, turn 1, waiting to start the first turn, ongoing, and every
    /// generator at 1 - matching the reference's constructor and field initialisers
    /// (`CombatState.cs:12-13,150-152,202-222`).
    ///
    /// ⚠️ **别把它写回 `Self { …, ..Self::EMPTY }`**（也别写 `let mut s = Self::EMPTY;`）。
    /// 那个形状会让整份“空状态”（184,648 B）被编成**一块 rodata 常量模板**，于是每一次
    /// `new()` 都是一次 184 KB 的 `memcpy`，而且那块模板**留在 `.wasm` 文件里** ——
    /// 实测 `web/rd_wasm.wasm` 里就是一段 184,651 B 的连续零，占整个文件的 33%。
    /// 现在 `new()` 走 [`Self::blank`]（逐字段给出）+ [`Self::reset_scalars`]，与
    /// [`Self::reset_in_place`] 共用同一份定义，编译结果里没有那块模板。
    #[must_use]
    pub fn new(id: CombatId, random_seed: i32) -> Self {
        let mut state = Self::blank();
        state.reset_scalars(id, random_seed);
        state
    }

    /// **就地重置**：语义（以及**字节**）等价于 `*self = CombatState::new(id, random_seed)`，
    /// 但**不产生**那 184 KB 的常量模板。
    ///
    /// 为什么要这个入口：调用方（`battle::build_fight`、`rd-wasm` 的 `rd_env_reset`）手里
    /// 已经有一份状态，唯一的诉求是“把它变回刚开局的样子”。整体赋值 `*self = new(..)` 在
    /// 语义上完全正确，代价是把 `new()` 的 const 值当成 rodata 再 `memcpy` 回来 ——
    /// 在 `wasm32-unknown-unknown` 上那 184 KB 会**原样进产物**（占 `.wasm` 的 33%），
    /// 而任何调用方都躲不掉它。就地重置没有这个代价：逐字段赋值 + 逐个容器 `clear()`。
    ///
    /// **为什么是字节等价、不只是可观察等价**：`Bounded` 的不变式是“`len` 之后的槽全是
    /// `T::EMPTY`”（`push` 只写在 `len` 上，`pop`/`retain` 把腾出来的槽写回 `T::EMPTY`），
    /// 所以 `clear()` 之后每个容器与刚构造的一模一样，`len` 之后的尾巴也是零 ——
    /// 与 `new()` 逐字节相同（`reset_in_place_matches_new_field_for_field` 钉住。
    ///
    /// 语义边界（与 `new()` 完全一致，别在这里加东西）：
    /// * `round` / `turn` 回到 1，`turn_phase` 回到 `WaitingToStartTurn`（**不**开第一回合）；
    /// * 四个发号器回到 1（参考的构造函数就是这个初值，见 `CombatState.cs:202-222`）；
    /// * 回合序、战斗员、牌区/牌池、全局状态、临时规则**全部清空**。
    pub fn reset_in_place(&mut self, id: CombatId, random_seed: i32) {
        self.reset_scalars(id, random_seed);
        // 顺序无所谓（六个容器互不相干），但**一个都不能漏**：漏掉 `cards` 会让
        // `card_num=` 与牌区槽位带着上一局的残留进哈希。
        self.turn_order.clear();
        self.combatants.clear();
        self.global_statuses.clear();
        self.card_zones.clear();
        self.cards.clear();
        self.temporary_rules.clear();
        // 六个队列 + 链 arena + 作用域。**参考在静止点存档时队列是空的**
        // （"no in-flight effect queue / program frames"，`CombatState.cs:718`、`:795-796`），
        // 所以"重置 = 队列全空"与参考一致；漏清一个会让上一局的残留事件在下一局开打时被分发。
        self.pending_effects.clear();
        self.pending_effect_chains.clear();
        self.pending_effect_owners.clear();
        self.pending_events.clear();
        self.pending_event_chains.clear();
        self.pending_continuations.clear();
        self.chains.clear();
        self.current_chain = ChainSlot::NONE;
        // 节目帧调度（批次 2）：参考在静止点存档时"没有在飞的节目帧"
        // （"no in-flight effect queue / program frames"，`CombatState.cs:718`）⇒ 一起清。
        // 漏清一个会让上一局的帧被本局的续延 `ProgramResume` 撞上。
        self.program_frames.clear();
        self.program_nodes.clear();
        self.program_loops.clear();
        // 动画日志（§142）：上一局的"发生过什么"绝不能出现在新局的第一步里。
        self.beat_log.clear();
    }

    /// 一份全空的状态 —— [`Empty::EMPTY`] 的**逐字段**版本。
    ///
    /// 两个必须永远一致（`blank_matches_empty` 钉住）：拆成函数写是为了让 `new()` 的
    /// 机器码里出现的是“逐字段赋值”而不是“从只读段拷一整块常量”。
    fn blank() -> Self {
        Self {
            id: CombatId::EMPTY,
            random_seed: 0,
            random_step: 0,
            result: CombatResult::Ongoing,
            current_round: 0,
            current_turn: 0,
            turn_phase: CombatTurnPhase::WaitingToStartTurn,
            active_combatant_id: None,
            end_turn_requested: false,
            forced_turn_ends: 0,
            extra_turn_for: None,
            cards_played_this_turn: 0,
            cards_played_last_turn: 0,
            next_status_instance_number: 0,
            next_combatant_number: 0,
            next_card_instance_number: 0,
            next_effect_chain_number: 0,
            next_program_execution_id: 0,
            turn_order: Bounded::new(),
            combatants: Bounded::new(),
            global_statuses: Bounded::new(),
            card_zones: Bounded::new(),
            cards: Bounded::new(),
            temporary_rules: Bounded::new(),
            pending_effects: Fifo::new(),
            pending_effect_chains: Fifo::new(),
            pending_effect_owners: Fifo::new(),
            pending_events: Fifo::new(),
            pending_event_chains: Fifo::new(),
            pending_continuations: Fifo::new(),
            chains: ChainArena::new(),
            current_chain: ChainSlot::NONE,
            program_frames: ProgramFrameArena::new(),
            program_nodes: ProgramNodeArena::new(),
            program_loops: ProgramLoopArena::new(),
            beat_log: crate::beat::BeatLog::new(),
        }
    }

    /// `new()` 与 `reset_in_place()` 共用的那 `12` 个标量（**唯一**一处定义它们的初值）。
    ///
    /// 初值的出处：`CombatState.cs:12-13`（`_nextCombatantNumber` 等）、`:150-152`、
    /// `:202-222` —— 四个发号器都从 **1** 开始，而且发号器**返回自增前的值**，
    /// 所以第一张卡的实例号是 `card_000001` 而不是 `card_000000`。
    fn reset_scalars(&mut self, id: CombatId, random_seed: i32) {
        self.id = id;
        self.random_seed = random_seed;
        self.random_step = 0;
        self.result = CombatResult::Ongoing;
        self.current_round = 1;
        self.current_turn = 1;
        self.turn_phase = CombatTurnPhase::WaitingToStartTurn;
        self.active_combatant_id = None;
        self.end_turn_requested = false;
        self.forced_turn_ends = 0;
        self.extra_turn_for = None;
        self.cards_played_this_turn = 0;
        self.cards_played_last_turn = 0;
        self.next_status_instance_number = 1;
        self.next_card_instance_number = 1;
        self.next_effect_chain_number = 1;
        self.next_program_execution_id = 1;
    }

    /// Builder: RNG stream position.
    #[must_use]
    pub fn with_random_step(mut self, random_step: i32) -> Self {
        self.random_step = random_step;
        self
    }

    // ---- generators ---------------------------------------------------------------------------
    //
    // ⚠️ 这两个发号器是 2026-10-17 补的。在那之前它们**只有字段、只有初值、只进哈希，
    // 全仓没有一处 `+=`** —— 也就是说状态里有两个计数器，参考实现每次跑节目/每次入队都会
    // 把它们推进，而内核永远停在 1。后果不是"少个功能"，是**指纹必然发散**：
    // 只要宿主真的跑了一次节目，`chain_num=` / `exec_num=` 两行就对不上。
    //
    // 两个方法都刻意保持"**返回自增前**的值"：参考的实现是先 `new Id(_next…)` 再 `_next…++`
    // （`CombatState.cs:513-518`、`:545-555`），所以第一次发出去的号是**初值 1**。
    // 写成"先加再返回"会让整场每一个 id 都偏移 1，而且**偏移不会自己暴露** ——
    // 它只是让 `exec_num` 比参考大 1，任何只比对"变了没变"的测试都看不出来。

    /// 分配一个节目执行号（`CombatState.cs:513-518`）。
    ///
    /// 参考的调用点：`Effects/Programs/EffectProgramExecution.cs:27`，**每次
    /// `EffectProgramExecutor.Execute` 一次**（不是每个节点一次）。
    #[must_use]
    pub fn allocate_program_execution_id(&mut self) -> i64 {
        let id = self.next_program_execution_id;
        self.next_program_execution_id += 1;
        id
    }

    /// 新建一条**根**效果链（`CombatState.cs:545-555`）。
    ///
    /// ⚠️ 只在"当前没有环境链"时才该调 —— 参考的两个入队口
    /// （`:386` `EnqueueEffect`、`:446` `EnqueueEvent`）都是
    /// `CurrentEffectChain ?? CreateRootEffectChain()`。也就是说**一条链内的后续入队不再发号**。
    /// 内核没有环境链这个概念，所以这条规则由宿主承担：宿主在自己那一层持有"当前链"，
    /// 只有最外层入队才调这里。写成"每次入队都调"会让链号狂涨。
    #[must_use]
    pub fn create_root_effect_chain(&mut self) -> i64 {
        let id = self.next_effect_chain_number;
        self.next_effect_chain_number += 1;
        id
    }

    // ---- 事件队列（批次 1）：入队 / 出队 / 链作用域 -------------------------------------------
    //
    // 三条入队规则逐字照 `CombatState.cs`：
    //   * `EnqueueEffect`（`:382-392`）与 `EnqueueEvent`（`:442-452`）都是
    //     `var chain = CurrentEffectChain ?? CreateRootEffectChain();`
    //   * `EnqueueContinuation`（`:461-470`）**不带链**（`Queue<Action<CombatState>>` 没有链字段）。
    //   * `CreateTriggeredEffectChain`（`:492-498`）**不发号**：父链 id 不变、深度 +1。
    //
    // ⚠️ 本模块把"当前有没有链"做成**显式参数**而不是"读 `current_chain` 再兜底"：
    // 无链时**不建根链**，条目带 `ChainSlot::NONE`。这不是省一个号 —— 是照实说
    // "这段时间没有链"。谁要发号，调 [`Self::enqueue_event_at_root`]（那是参考的
    // `?? CreateRootEffectChain()` 分支，明确写出来）。批次 1 只有四个回合边界事件走那条路，
    // 而它们今天各自已经发过一个号（`host.rs` 的四个钩子里那四行 `create_root_effect_chain`）——
    // 所以**链号一个都不多、一个都不少**，基线不动。

    /// 入队一条效果：链 = `CurrentEffectChain ?? CreateRootEffectChain()`（`CombatState.cs:382-392`）。
    ///
    /// ⚠️ **批次 2 起这条规则是照参考写的，不是"没有链就记 NONE"**。批次 1 那样写是因为
    /// 队列当时没有生产者；现在有生产者了，`??` 那一支**真的会发生**（出牌终态的搬区
    /// `Cards/CardPlay.cs:251-252` 就在顶层、没有环境链），而它**恰好是 `chain_num` 的一笔**。
    /// 写成"没有链就 NONE"会让那一笔静默消失 —— 那正是本节要杀的那类静默。
    ///
    /// `owner` 是"谁在跑、解析失败时把帧绑回去"的那个槽位（§1.2 末）。
    pub fn enqueue_effect(&mut self, request: EffectRequest) -> StateResult<()> {
        self.enqueue_effect_with_owner(request, None)
    }

    /// 同 [`Self::enqueue_effect`]，但带上归属节目帧。
    pub fn enqueue_effect_with_owner(
        &mut self,
        request: EffectRequest,
        owner: Option<ProgramExecutionSlot>,
    ) -> StateResult<()> {
        // 三列**一起**进：任何一列失败都不许留下"多出来的那一列"（否则下一次出队的
        // 对齐断言会红在一个完全无关的地方）。所以先查容量，再三列同推。
        if self.pending_effects.len() == MAX_PENDING_EFFECTS {
            return Err(CapacityError::Full(Container::PendingEffects));
        }
        // `var chain = CurrentEffectChain ?? CreateRootEffectChain();`（`:386`）——
        // **发号发生在检查三列之前**（参考也是先 `??` 再 `Enqueue`）。一个"队列满了"的入队
        // 因此在参考里也已经消耗过一个链号；这里的顺序与它一致。
        let chain = match self.current_chain {
            ChainSlot::NONE => self.new_root_chain_in_arena()?,
            chain => chain,
        };
        // ⚠️ **队列条目持一次链引用**。参考靠 GC（条目里的链对象有人指着就活着）；
        // 我们靠 `ChainRecord::refs`。漏了这一句的后果不是"多一条链"，而是**链被提前回收**：
        // 帧的引用一放（`reap_frames`）条目手里的链就没了，下一次 `acquire` 报
        // `Full(Chains)` —— 实测在 `e2e_16` 上撞到过，而且它伪装成"容量不够"。
        self.chains.acquire(chain)?;
        self.pending_effects.push(request, Container::PendingEffects)?;
        if let Err(e) = self
            .pending_effect_chains
            .push(chain, Container::PendingEffectChains)
        {
            // 回滚：主列已经进了一条，不撤销就会让三列错位（而错位是**静默**的语义漂移）。
            let _ = self.pending_effects.pop_front();
            self.chains.release(chain);
            return Err(e);
        }
        if let Err(e) = self
            .pending_effect_owners
            .push(owner, Container::PendingEffectOwners)
        {
            let _ = self.pending_effect_chains.pop_front();
            let _ = self.pending_effects.pop_front();
            self.chains.release(chain);
            return Err(e);
        }
        Ok(())
    }

    /// 入队一条事件：链 = 当前作用域链（没有就是 [`ChainSlot::NONE`]）。
    pub fn enqueue_event(&mut self, event: CombatEvent) -> StateResult<()> {
        let chain = self.current_chain;
        self.enqueue_event_with_chain(event, chain)
    }

    /// 入队一条事件，并**建一条根链**（参考的 `CurrentEffectChain ?? CreateRootEffectChain()`）。
    ///
    /// 这是"顶层入队"那一支：回合机把 `TurnStartedCombatEvent` 交给处理器
    /// （`CombatTurnProcessor.cs:28-32`）时没有环境链 ⇒ `+1`。
    pub fn enqueue_event_at_root(&mut self, event: CombatEvent) -> StateResult<()> {
        let chain = self.new_root_chain_in_arena()?;
        self.enqueue_event_with_chain(event, chain)
    }

    /// 入队一条事件，链由调用方给。
    pub fn enqueue_event_with_chain(
        &mut self,
        event: CombatEvent,
        chain: ChainSlot,
    ) -> StateResult<()> {
        if self.pending_events.len() == MAX_PENDING_EVENTS {
            return Err(CapacityError::Full(Container::PendingEvents));
        }
        // 先拿到"这条链还在"的引用，再改两列 —— 反过来的话，`acquire` 失败会留下
        // 一条**已入队但没持引用的**事件（链可能被回收，而队列里还指着它）。
        if !chain.is_none() {
            self.chains.acquire(chain)?;
        }
        self.pending_events.push(event, Container::PendingEvents)?;
        if let Err(e) = self
            .pending_event_chains
            .push(chain, Container::PendingEventChains)
        {
            let _ = self.pending_events.pop_front();
            self.chains.release(chain);
            return Err(e);
        }
        Ok(())
    }

    /// 入队一条续延。**不带链**（`EnqueueContinuation`，`CombatState.cs:461-470`）。
    ///
    /// ⚠️ 入队**不会**执行它（那是"立刻跑"的变异，见 `host.rs` 的排空循环与它的测试）。
    pub fn enqueue_continuation(&mut self, continuation: Continuation) -> StateResult<()> {
        self.pending_continuations
            .push(continuation, Container::PendingContinuations)
    }

    /// 出队一条效果（连带它的链与归属帧）。**出队前先跑对齐断言**（`CombatState.cs:429-440`）。
    pub fn dequeue_effect(&mut self) -> StateResult<Option<EffectItem>> {
        self.ensure_effect_queue_aligned()?;
        let Some(request) = self.pending_effects.pop_front() else {
            return Ok(None);
        };
        // 对齐断言刚刚过了 ⇒ 这两次 pop 一定拿得到。**但仍然不用 `unwrap_or`**：
        // 用兜底值的话，"断言被删掉/被破坏"那天这里会静默把链换成 `NONE`，
        // 而 `NONE` 恰好是一个合法值 —— 于是错位的效果会被当成"顶层效果"照常跑。
        let Some(chain) = self.pending_effect_chains.pop_front() else {
            return Err(self.misaligned("effect"));
        };
        let Some(owner) = self.pending_effect_owners.pop_front() else {
            return Err(self.misaligned("effect"));
        };
        Ok(Some(EffectItem {
            request,
            chain,
            owner,
        }))
    }

    fn misaligned(&self, column: &'static str) -> CapacityError {
        CapacityError::QueueMetadataMisaligned {
            column,
            records: self.pending_effects.len(),
            chains: self.pending_effect_chains.len(),
            owners: self.pending_effect_owners.len(),
        }
    }

    /// 出队一条事件（连带它的链）。**出队前先跑对齐断言**（`CombatState.cs:480-490`）。
    pub fn dequeue_event(&mut self) -> StateResult<Option<EventItem>> {
        self.ensure_event_queue_aligned()?;
        let Some(event) = self.pending_events.pop_front() else {
            return Ok(None);
        };
        // 同 `dequeue_effect`：不用兜底值，见那里的注释。
        let Some(chain) = self.pending_event_chains.pop_front() else {
            return Err(CapacityError::QueueMetadataMisaligned {
                column: "event",
                records: self.pending_events.len(),
                chains: self.pending_event_chains.len(),
                owners: self.pending_event_chains.len(),
            });
        };
        Ok(Some(EventItem { event, chain }))
    }

    /// 出队一条续延（`TryDequeueContinuation`，`CombatState.cs:472-473`）。
    pub fn try_dequeue_continuation(&mut self) -> Option<Continuation> {
        self.pending_continuations.pop_front()
    }

    // ---- 两条对齐断言 ------------------------------------------------------------------------
    //
    // 参考用两条断言守"三列并行数组"这条不变式（`EnsureEffectQueueMetadataAligned`
    // `CombatState.cs:401-406`；`EnsureEventQueueMetadataAligned` `:436-440`）。
    // 它们的意义不是"防御性编程"：三列长度不一致就意味着**某条效果拿到了别人的链**，
    // 而那种错误在哈希里看起来只是一串不同的链号。所以它们必须是**真的检查**，
    // 不是 `debug_assert!`（发布版会把它们编掉，而裸机跑的就是发布版）。

    /// 效果列三列必须等长。
    pub fn ensure_effect_queue_aligned(&self) -> StateResult<()> {
        let effects = self.pending_effects.len();
        let chains = self.pending_effect_chains.len();
        let owners = self.pending_effect_owners.len();
        if effects == chains && effects == owners {
            return Ok(());
        }
        Err(CapacityError::QueueMetadataMisaligned {
            column: "effect",
            records: effects,
            chains,
            owners,
        })
    }

    /// 事件列两列必须等长。
    pub fn ensure_event_queue_aligned(&self) -> StateResult<()> {
        let events = self.pending_events.len();
        let chains = self.pending_event_chains.len();
        if events == chains {
            return Ok(());
        }
        Err(CapacityError::QueueMetadataMisaligned {
            column: "event",
            records: events,
            chains,
            owners: chains,
        })
    }

    // ---- 队列的可观察面 ---------------------------------------------------------------------

    /// 效果队列深度（对应参考的 `PendingEffectCount`，`CombatState.cs:192-194`）。
    #[must_use]
    pub fn pending_effect_count(&self) -> usize {
        self.pending_effects.len()
    }

    /// 事件队列深度（`PendingEventCount`，`:196-198`）。
    #[must_use]
    pub fn pending_event_count(&self) -> usize {
        self.pending_events.len()
    }

    /// 续延队列深度。
    #[must_use]
    pub fn pending_continuation_count(&self) -> usize {
        self.pending_continuations.len()
    }

    /// 三个队列有没有活（`HasPendingEffects || HasPendingEvents || HasPendingContinuations`，`:97`）。
    #[must_use]
    pub fn has_pending_queues(&self) -> bool {
        !self.pending_effects.is_empty()
            || !self.pending_events.is_empty()
            || !self.pending_continuations.is_empty()
    }

    /// 效果队列是否为空。
    #[must_use]
    pub fn has_pending_effects(&self) -> bool {
        !self.pending_effects.is_empty()
    }

    /// 事件队列是否为空。
    #[must_use]
    pub fn has_pending_events(&self) -> bool {
        !self.pending_events.is_empty()
    }

    /// 续延队列是否为空。
    #[must_use]
    pub fn has_pending_continuations(&self) -> bool {
        !self.pending_continuations.is_empty()
    }

    // ---- 链作用域（`EnterEffectChain`） -------------------------------------------------------

    /// 当前作用域链。
    #[must_use]
    pub const fn current_chain(&self) -> ChainSlot {
        self.current_chain
    }

    /// 直接把作用域链设成 `chain`（`with_chain` 的**非闭包**形式）。
    ///
    /// 为什么需要两个：`with_chain` 要一个**立刻调用**的闭包，而节目派发那一半的函数全都
    /// 收 `&mut ExecContext`（它自己握着 `&mut CombatState`）—— 闭包拿不到它。
    /// 于是 `exec::begin` 采用"存旧值 → 设新值 → 派发 → 还原"，与 `with_chain` 逐字同效。
    pub fn set_current_chain(&mut self, chain: ChainSlot) {
        self.current_chain = chain;
    }

    /// 在 `chain` 的作用域里跑 `f`，退出时**还原**（`CombatState.cs:500-511` 的 `using`）。
    ///
    /// ⚠️ 闭包**立刻调用**，不入队 —— 这是 §4.1.3 允许的那一种用法。
    pub fn with_chain<R>(&mut self, chain: ChainSlot, f: impl FnOnce(&mut Self) -> R) -> R {
        let saved = self.current_chain;
        self.current_chain = chain;
        let out = f(self);
        self.current_chain = saved;
        out
    }

    /// 建一条根链并**放进 arena**（引用计数 1），返回槽位。
    ///
    /// 与 [`Self::create_root_effect_chain`] 的分工：那个只发号（给 `play.rs` 的显式记账用，
    /// 那边不需要链的内容）；这个既发号又建链，给"队列条目真的要带着一条链"用。
    pub fn new_root_chain_in_arena(&mut self) -> StateResult<ChainSlot> {
        let id = self.create_root_effect_chain();
        self.chains.alloc(ChainRecord {
            id,
            parent: ChainSlot::NONE,
            trigger: NO_TRIGGER,
            depth: 0,
            refs: 1,
        })
    }

    /// 建一条根链，但**不发号**：`id` 沿用"调用方刚发掉的那个号"
    /// （`next_effect_chain_number - 1`）。
    ///
    /// 两个调用点，同一件事："参考在这里**没有**建新根链"：
    ///
    /// * `exec::execute`（**遗留入口**）：`intent.rs::execute_action` / `exec` 的旧调用方已经
    ///   手工记过"请求"那一笔（`create_root_effect_chain()`），参考里节目的链
    ///   **就是那条**（`EffectProgramExecution.cs:31` 的 `??=` 读到非空的 `CurrentEffectChain`）
    ///   ⇒ 再发一个号会让 `chain_num` 多 1（实测：`intent.rs:1853` 那条断言 3 vs 2）。
    /// * `host::try_hand_turn_end_lifecycle`（2026-10-19 加的）：卡的生命周期节目跑在
    ///   参考的 `TurnEndedCombatEvent` 分发里，那一刻 `CurrentEffectChain` 是**事件自己那条链**
    ///   （`CombatEventHandling.cs:60` 的 `using (EnterEffectChain(…))`）⇒ 节目里的 `??=` 不发号。
    ///   内核把 `TurnEnded` 的那一个号发在 `try_run_turn_ended_triggers` 里（在本钩子之后）
    ///   ⇒ 这里同样只能"建链、不发号"。
    ///
    /// ⚠️ 它的 `id` 是**上一个已发的号**，不是参考里那条事件链的号。链 id 不进哈希
    /// （哈希里是 `chain_num` 计数器，`snapshot.rs:165`），也没有按 id 的查表
    /// （`ChainRecord.id` 只被 [`Self::create_triggered_chain`] 继承）⇒ 可观察量一致。
    pub fn adopt_root_chain(&mut self) -> StateResult<ChainSlot> {
        let id = self.next_effect_chain_number.saturating_sub(1);
        self.chains.alloc(ChainRecord {
            id,
            parent: ChainSlot::NONE,
            trigger: NO_TRIGGER,
            depth: 0,
            refs: 1,
        })
    }

    /// 建一条**触发**链：父链不变、深度 +1、**不发号**（`CombatState.cs:492-498`）。
    ///
    /// 深度到顶 ⇒ 响亮失败（参考的 `EnsureCanAppendTriggeredEffectDefinition` **抛**，
    /// `CombatEffectChain.cs:64-72`，不是跳过）。
    pub fn create_triggered_chain(
        &mut self,
        parent: ChainSlot,
        trigger: u16,
    ) -> StateResult<ChainSlot> {
        // **父链必须还在**。参考里 `CurrentEffectChain` 恒非 null（入队那一刻兜底建了根链，
        // `CombatState.cs:446`），所以"没有父链"在参考里不可达；内核今天不可达的原因是
        // 批次 1 里根本没人建触发链（`exec.rs` 还没拆成"请求 + 解析"）。
        //
        // ⚠️ 这里**不给兜底 id**：`ChainRecord::id` 就是哈希里的 `chain_num`，瞎填一个 0
        // 会让"链号从哪来"变成不可对账的一笔。宁可响亮失败。
        let Some(record) = self.chains.get(parent) else {
            return Err(CapacityError::ChainHasNoParent);
        };
        let (id, depth) = (record.id, record.depth);
        let next_depth = depth.saturating_add(1);
        if next_depth > MAX_TRIGGER_DEPTH {
            return Err(CapacityError::Full(Container::Chains));
        }
        self.chains.alloc(ChainRecord {
            id,
            parent,
            trigger,
            depth: next_depth,
            refs: 1,
        })
    }

    /// 拿一条链的一次引用（`ChainRecord::refs += 1`）。
    ///
    /// 谁持有链、谁就要 `acquire`/`release` 平衡：参考靠 GC，我们靠这个计数器。
    /// 例：节目帧 `??=` 到一条**已经存在**的环境链时要 `acquire`（它不是我们建的），
    /// 这样 `reap_frames` 的 `release` 才不会把别人的链弄没。
    pub fn acquire_chain(&mut self, chain: ChainSlot) -> StateResult<()> {
        self.chains.acquire(chain)
    }

    /// 放掉一条链的一次引用（归零即回收）。
    pub fn release_chain(&mut self, chain: ChainSlot) {
        self.chains.release(chain);
    }

    /// 在用的链条数（诊断用：`refs > 0` 的槽位数）。
    #[must_use]
    pub fn live_chain_count(&self) -> usize {
        self.chains.live()
    }

    /// 读一条链（触发链的父/深度）。
    #[must_use]
    pub fn chain_record(&self, chain: ChainSlot) -> Option<&ChainRecord> {
        self.chains.get(chain)
    }

    // ---- reads -------------------------------------------------------------------------------

    /// Combatant ids in turn order. The canonical text writes `turn_order=` from this, and walks it
    /// again for the `c=` and `cz=` sections.
    #[must_use]
    pub fn turn_order(&self) -> &[CombatantId] {
        self.turn_order.as_slice()
    }

    /// Combatants in add order, which is also turn order (`CombatState.cs:231-232`).
    #[must_use]
    pub fn combatants(&self) -> &[Combatant] {
        self.combatants.as_slice()
    }

    /// Mutable view of every combatant -- for the few rules that must touch more than one at a time
    /// (a master's fall taking its minions with it, port-plan.md §139).
    #[must_use]
    pub fn combatants_mut(&mut self) -> &mut [Combatant] {
        self.combatants.as_mut_slice()
    }

    /// Finds a combatant by id.
    #[must_use]
    pub fn combatant(&self, id: &CombatantId) -> Option<&Combatant> {
        self.combatants().iter().find(|c| &c.id == id)
    }

    /// Finds a combatant by id, mutably.
    #[must_use]
    pub fn combatant_mut(&mut self, id: &CombatantId) -> Option<&mut Combatant> {
        self.combatants.as_mut_slice().iter_mut().find(|c| &c.id == id)
    }

    /// Global status instances, in instance order (not sorted).
    #[must_use]
    pub fn global_statuses(&self) -> &[StatusInstance] {
        self.global_statuses.as_slice()
    }

    /// A combatant's piles, if it has any. `None` mirrors the reference's dictionary: `CardZones` is
    /// emitted only for combatants that have an entry (`CombatStateSnapshotter.cs:16-19`).
    #[must_use]
    pub fn card_zones(&self, id: &CombatantId) -> Option<&CardZones> {
        self.card_zones
            .as_slice()
            .iter()
            .find(|z| z.combatant_id() == id)
    }

    /// Temporary rules, sorted by id - the snapshot builder orders them
    /// (`CombatStateSnapshotter.cs:39`).
    #[must_use]
    pub fn temporary_rules(&self) -> &[TemporaryRule] {
        self.temporary_rules.as_slice()
    }

    /// A card instance by pool slot.
    #[must_use]
    pub fn card(&self, slot: CardSlot) -> Option<&CardInstance> {
        self.cards.get(slot.index())
    }

    /// A card instance by pool slot, mutably.
    #[must_use]
    pub fn card_mut(&mut self, slot: CardSlot) -> Option<&mut CardInstance> {
        self.cards.get_mut(slot.index())
    }

    /// Card instances in one pile, in pile order.
    #[must_use]
    pub fn zone_cards(&self, owner: &CombatantId, zone: CardZone) -> ZoneCards<'_> {
        let slots = self.card_zones(owner).map_or(&[][..], |z| z.slots(zone));
        ZoneCards {
            state: self,
            slots,
            next: 0,
        }
    }

    /// Number of card instances in the fight.
    #[must_use]
    pub fn card_count(&self) -> usize {
        self.cards.len()
    }

    // ---- writes ------------------------------------------------------------------------------

    /// Adds a combatant: appends to the turn order, creates its (empty) piles, and makes it the
    /// active combatant if it is the first (`CombatState.cs:224-238`).
    pub fn add_combatant(&mut self, combatant: Combatant) -> StateResult<()> {
        if self.combatant(&combatant.id).is_some() {
            return Err(CapacityError::DuplicateCombatant);
        }
        // Check both capacities up front so a failure cannot leave the two lists out of step.
        if self.combatants.len() == MAX_COMBATANTS || self.turn_order.len() == MAX_COMBATANTS {
            return Err(CapacityError::Full(Container::Combatants));
        }
        if self.card_zones.len() == MAX_COMBATANTS {
            return Err(CapacityError::Full(Container::CardZones));
        }
        let id = combatant.id;
        self.combatants.push(combatant, Container::Combatants)?;
        self.turn_order.push(id, Container::TurnOrder)?;
        self.card_zones.push(CardZones::new(id), Container::CardZones)?;
        if self.active_combatant_id.is_none() {
            self.active_combatant_id = Some(id);
        }
        Ok(())
    }

    /// Drops a combatant's pile entry, mirroring the reference's dictionary lookup: a combatant
    /// with no entry contributes no `cz=` line.
    pub fn detach_card_zones(&mut self, id: &CombatantId) -> bool {
        let len = self.card_zones.len();
        for i in 0..len {
            if self.card_zones.get(i).map(CardZones::combatant_id) == Some(id) {
                // `Bounded` has no remove-at, and the pile list is only ever appended to, so shift.
                for j in i..len - 1 {
                    if let Some(moved) = self.card_zones.get(j + 1).copied() {
                        if let Some(slot) = self.card_zones.get_mut(j) {
                            *slot = moved;
                        }
                    }
                }
                self.card_zones.pop();
                return true;
            }
        }
        false
    }

    /// Replaces the turn order wholesale.
    ///
    /// The reference's `_turnOrder` is append-only in practice (`CombatState.cs:232`), but the
    /// canonical text is defined by *this list* - the snapshot builder walks `TurnOrder` and looks
    /// each combatant up (`CombatStateSnapshotter.cs:12-19`) - and on restore the order arrives as
    /// data (`CombatState.cs:799-800`). Every id must name a combatant already in the state: the
    /// reference would throw out of `GetCombatant` otherwise (`:240-243`), so this errors instead
    /// of quietly dropping a line.
    pub fn set_turn_order(&mut self, ids: &[CombatantId]) -> StateResult<()> {
        if ids.len() > MAX_COMBATANTS {
            return Err(CapacityError::Full(Container::TurnOrder));
        }
        for id in ids {
            if self.combatant(id).is_none() {
                return Err(CapacityError::MissingCombatant);
            }
            if ids.iter().filter(|other| *other == id).count() > 1 {
                return Err(CapacityError::DuplicateKey);
            }
        }
        self.turn_order.clear();
        for id in ids {
            self.turn_order.push(*id, Container::TurnOrder)?;
        }
        Ok(())
    }

    /// Appends a global status instance.
    pub fn push_global_status(&mut self, status: StatusInstance) -> StateResult<()> {
        self.global_statuses
            .push(status, Container::GlobalStatuses)?;
        Ok(())
    }

    /// Installs a temporary rule, keeping the list sorted by id. A duplicate id is an error, as in
    /// the reference (`AddTemporaryTriggeredProgram`, `CombatState.cs:594-616`).
    pub fn add_temporary_rule(&mut self, rule: TemporaryRule) -> StateResult<()> {
        self.temporary_rules
            .insert_sorted(rule, Container::TemporaryRules)?;
        Ok(())
    }

    /// Drops every temporary rule.
    ///
    /// ⚠️ **这不是参考实现的回合/轮次边界行为。** 参考的 `AdvanceTurn`/`AdvanceRound`
    /// （`CombatState.cs:572-592`）只移除**已到期**的规则，没有到期字段的规则会活过边界
    /// （`tr=` 行是哈希可见的，所以这个区别是真的）。用
    /// [`Self::expire_temporary_rules_at_turn_boundary`] / [`Self::expire_temporary_rules_at_round_boundary`]
    /// 做边界处理；本方法只在"显式清场"时用。
    pub fn clear_temporary_rules(&mut self) {
        self.temporary_rules.clear();
    }

    /// `AdvanceTurn` 的临时规则部分（`CombatState.cs:572-579`）。
    ///
    /// **调用顺序是契约：先 `current_turn += 1`，再调本方法。** 参考实现在递增之后才判定
    /// （`:574` 递增、`:577` 标记），顺序反了会让"本回合到期"的规则早一回合消失。
    ///
    /// 判定逐字照 `TemporaryTriggeredProgram.MarkExpiredIfPastTurn`（`:138-145`）：
    /// 只看到 `expires_after_turn`；到期轮次取 `expires_after_round ?? 当前轮`；
    /// 条件为 `current_round > 到期轮 || (同轮 && current_turn > 到期回合)`。
    /// 注意它**不看** `expires_after_round` 本身的"轮已过"判定 —— 那是 `AdvanceRound` 的事。
    pub fn expire_temporary_rules_at_turn_boundary(&mut self) {
        let round = self.current_round;
        let turn = self.current_turn;
        for rule in self.temporary_rules.as_mut_slice() {
            if let Some(expiry_turn) = rule.expires_after_turn {
                let expiry_round = rule.expires_after_round.unwrap_or(round);
                if round > expiry_round || (round == expiry_round && turn > expiry_turn) {
                    rule.is_expired = true;
                }
            }
        }
        self.temporary_rules.retain(|rule| !rule.is_expired);
    }

    /// `AdvanceRound` 的临时规则部分（`CombatState.cs:581-592`）。
    ///
    /// **先 `current_round += 1`、`current_turn = 1`，再调本方法。**
    /// 与回合边界不同，这里**两个判定都做**（`:588-589` 连续调两个 Mark）。
    pub fn expire_temporary_rules_at_round_boundary(&mut self) {
        let round = self.current_round;
        let turn = self.current_turn;
        for rule in self.temporary_rules.as_mut_slice() {
            if let Some(expiry_round) = rule.expires_after_round {
                if round > expiry_round {
                    rule.is_expired = true;
                }
            }
            if let Some(expiry_turn) = rule.expires_after_turn {
                let expiry_round = rule.expires_after_round.unwrap_or(round);
                if round > expiry_round || (round == expiry_round && turn > expiry_turn) {
                    rule.is_expired = true;
                }
            }
        }
        self.temporary_rules.retain(|rule| !rule.is_expired);
    }

    /// 把弃牌堆按**引擎的洗牌协议**整堆洗进抽牌堆，返回搬了几张。
    ///
    /// 这是确定性契约的一部分，不是"随便打乱一下"：
    ///
    /// 1. 置换来自 `CombatRandom.CreateShuffledIndexes(count, RandomSeed, RandomStep)`
    ///    （`CombatRandom.cs:5-27`，Fisher–Yates 从 `n-1` 递减、`j = next() % (i+1)`）；
    ///    内核的 [`crate::rng::shuffle_indexes`] 与它**逐位一致**（已用 33,768 个下标对拍）。
    /// 2. 目标堆 = **旧抽牌堆 ++ `[弃牌堆[order[0]], 弃牌堆[order[1]], …]`**，弃牌堆清空
    ///    （`CardZones.MoveDiscardPileToDrawPile`，`:260-297`：先校验 `order` 是排列、再 `Clear`、
    ///    再逐张 `Add` —— 所以是**追加**到抽牌堆末尾，不是替换）。
    /// 3. **洗完之后 `random_step += 1`**（`CardZoneEffects.cs:69` 的 `AdvanceRandomStep()`）。
    ///    少加或多加这一步，之后每一次随机都会错位，而 `step=` 行是哈希可见的。
    ///
    /// 容量不足时**在动手之前**返回 `Err`，一个字节也不改。
    pub fn reshuffle_discard_into_draw(&mut self, owner: &CombatantId) -> StateResult<usize> {
        let count = {
            let Some(zones) = self.card_zones.as_slice().iter().find(|z| z.combatant_id() == owner)
            else {
                return Err(CapacityError::MissingCombatant);
            };
            let n = zones.count(CardZone::DiscardPile);
            if n == 0 {
                return Ok(0);
            }
            // 预检：目标堆会变成「旧抽牌堆 ++ n 张」。
            if zones.count(CardZone::DrawPile) + n > MAX_CARDS_PER_ZONE {
                return Err(CapacityError::Full(Container::CardsInZone(CardZone::DrawPile)));
            }
            n
        };

        let mut order = [0u8; MAX_CARDS_PER_ZONE];
        crate::rng::shuffle_indexes(&mut order[..count], self.random_seed, self.random_step);

        let mut slots = [0u16; MAX_CARDS_PER_ZONE];
        {
            let Some(zones) = self.card_zones.as_slice().iter().find(|z| z.combatant_id() == owner)
            else {
                return Err(CapacityError::MissingCombatant);
            };
            slots[..count].copy_from_slice(zones.slots(CardZone::DiscardPile));
        }

        let Some(zones) = self
            .card_zones
            .as_mut_slice()
            .iter_mut()
            .find(|z| z.combatant_id() == owner)
        else {
            return Err(CapacityError::MissingCombatant);
        };
        zones.clear(CardZone::DiscardPile);
        for i in 0..count {
            zones.push_slot(CardZone::DrawPile, slots[order[i] as usize])?;
        }
        // 只有真的洗了才推进 —— 空弃牌堆上面已经早退，没有这一步。
        self.random_step += 1;
        Ok(count)
    }

    /// Adds a card instance to the front of a pile, at the *back* (append). `index 0` is the top of
    /// the draw pile, so a tutor that places a card on top needs its own front insert - part of the
    /// live engine, not of this model.
    pub fn push_card(
        &mut self,
        owner: &CombatantId,
        zone: CardZone,
        card: CardInstance,
    ) -> StateResult<CardSlot> {
        if self.cards.len() == MAX_CARD_INSTANCES {
            return Err(CapacityError::Full(Container::CardInstances));
        }
        let slot = self.cards.len() as u16;
        // Take the pile's capacity before touching the pool, so a full pile cannot orphan a slot.
        let zones = self
            .card_zones
            .as_mut_slice()
            .iter_mut()
            .find(|z| z.combatant_id() == owner)
            .ok_or(CapacityError::MissingCombatant)?;
        zones.push_slot(zone, slot)?;
        self.cards.push(card, Container::CardInstances)?;
        Ok(CardSlot(slot))
    }

    /// Removes a card from whichever pile holds it. The pool slot is retired rather than reused:
    /// slot recycling belongs to the live engine, which also has to keep the piles consistent.
    pub fn remove_card(&mut self, owner: &CombatantId, slot: CardSlot) -> bool {
        let Some(zones) = self
            .card_zones
            .as_mut_slice()
            .iter_mut()
            .find(|z| z.combatant_id() == owner)
        else {
            return false;
        };
        for zone in CardZone::ALL {
            if zones.remove_slot(zone, slot.0) {
                return true;
            }
        }
        false
    }

    /// Empties a pile, keeping its pool slots.
    pub fn clear_zone(&mut self, owner: &CombatantId, zone: CardZone) {
        if let Some(zones) = self
            .card_zones
            .as_mut_slice()
            .iter_mut()
            .find(|z| z.combatant_id() == owner)
        {
            zones.clear(zone);
        }
    }

    // ── Moving cards between piles ───────────────────────────────────────────────────────────────
    //
    // ⚠️ 这一段存在的理由，以及为什么不能用 push_card/remove_card 拼出来：
    //
    // 参考实现里"把一张牌从抽牌堆移到手牌"是**零成本**的 —— C# 里卡是对象，换堆不改身份
    // (`CardZones.MoveCardToZone`, `Cards/CardZones.cs:212-223`)。
    // 但本模型用"池槽位 + 每堆一张槽位表"表示卡区，而 `push_card` 永远**分配新槽位**、
    // `remove_card` 又**退休旧槽位不回收**。于是"移动 = 删了再建"会**一次吃掉一个
    // `MAX_CARD_INSTANCES` 槽位** —— 一副 10 张的牌组在 抽牌堆→手牌→弃牌堆 之间循环，
    // 约 22 轮就会撞上 `Full(CardInstances)`，而 224 这个容量是按"整场约 200 张卡实例"定的。
    //
    // 这种错**不会在小场景的单元测试里露出来**，只会在真打一局时暴露。所以下面这些原语
    // 一律**复用同一个池槽位**，并且有一条"移动 1000 次 card_count() 不增长"的测试把它钉死。

    /// Moves a card between two piles of one combatant, **reusing its pool slot**.
    ///
    /// Returns `Ok(true)` if the card was in `from` and is now in `to`, `Ok(false)` if it was not
    /// in `from` (a no-op, not an error — the reference's `RemoveFromCurrentZone` tolerates it).
    ///
    /// Destination capacity is taken **before** the card leaves `from`, so a full destination
    /// cannot lose the card. `from == to` is allowed and re-orders within one pile, which is how
    /// the reference's "put this card on top of the discard pile" reads.
    pub fn move_card(
        &mut self,
        owner: &CombatantId,
        from: CardZone,
        to: CardZone,
        slot: CardSlot,
        placement: ZonePlacement,
    ) -> StateResult<bool> {
        let Some(zones) = self
            .card_zones
            .as_mut_slice()
            .iter_mut()
            .find(|z| z.combatant_id() == owner)
        else {
            return Err(CapacityError::MissingCombatant);
        };
        // Reserve destination room first (see the doc comment).
        if zones.count(to) == MAX_CARDS_PER_ZONE {
            return Err(CapacityError::Full(Container::CardsInZone(to)));
        }
        if !zones.remove_slot(from, slot.0) {
            return Ok(false);
        }
        match placement {
            ZonePlacement::Top => zones.insert_slot_front(to, slot.0)?,
            ZonePlacement::Bottom => zones.push_slot(to, slot.0)?,
        }
        Ok(true)
    }

    /// Draws one card: takes the **front** of the draw pile and appends it to the hand.
    ///
    /// The front is the top — the reference is `_drawPile.RemoveAt(0)` (`Cards/CardZones.cs:251`).
    /// Returns `None` on an empty draw pile, which is what reshuffling exists to prevent.
    pub fn draw_card(&mut self, owner: &CombatantId) -> StateResult<Option<CardSlot>> {
        let Some(zones) = self.card_zones.as_slice().iter().find(|z| z.combatant_id() == owner)
        else {
            return Err(CapacityError::MissingCombatant);
        };
        let Some(&top) = zones.slots(CardZone::DrawPile).first() else {
            return Ok(None);
        };
        self.move_card(owner, CardZone::DrawPile, CardZone::Hand, CardSlot(top),
                       ZonePlacement::Bottom)?;
        Ok(Some(CardSlot(top)))
    }

    /// Moves **every** card from one pile to another, preserving order, all at the bottom.
    ///
    /// Mirrors `MoveAllCardsFromZone` (`Cards/CardZones.cs:225-238`), which snapshots the source
    /// first and then moves each card with the default placement.
    ///
    /// ⚠️ 目的堆装不下时**在动手之前**就报错，一个字节也不改 —— "部分移动"会让两堆都处于
    /// 参考实现里不存在的状态。
    pub fn move_all_cards(
        &mut self,
        owner: &CombatantId,
        from: CardZone,
        to: CardZone,
    ) -> StateResult<usize> {
        if from == to {
            return Ok(0);
        }
        let mut buf = [0u16; MAX_CARDS_PER_ZONE];
        let n = {
            let Some(zones) = self.card_zones.as_slice().iter().find(|z| z.combatant_id() == owner)
            else {
                return Err(CapacityError::MissingCombatant);
            };
            let src = zones.slots(from);
            buf[..src.len()].copy_from_slice(src);
            src.len()
        };
        if n == 0 {
            return Ok(0);
        }
        // 先整体验证容量，再逐个搬 —— 不允许"搬了一半才发现装不下"。
        {
            let zones = self.card_zones.as_slice().iter().find(|z| z.combatant_id() == owner)
                .ok_or(CapacityError::MissingCombatant)?;
            if zones.count(to) + n > MAX_CARDS_PER_ZONE {
                return Err(CapacityError::Full(Container::CardsInZone(to)));
            }
        }
        for &slot in &buf[..n] {
            self.move_card(owner, from, to, CardSlot(slot), ZonePlacement::Bottom)?;
        }
        Ok(n)
    }

    /// Adds a **new** card to the front of a pile (`ZonePlacement.Top`).
    ///
    /// Unlike [`Self::move_card`] this *does* allocate a pool slot — because it really is a new
    /// card instance, not a card changing piles.
    pub fn insert_card_front(
        &mut self,
        owner: &CombatantId,
        zone: CardZone,
        card: CardInstance,
    ) -> StateResult<CardSlot> {
        if self.cards.len() == MAX_CARD_INSTANCES {
            return Err(CapacityError::Full(Container::CardInstances));
        }
        let slot = self.cards.len() as u16;
        // Take the pile's capacity before touching the pool, so a full pile cannot orphan a slot.
        let zones = self
            .card_zones
            .as_mut_slice()
            .iter_mut()
            .find(|z| z.combatant_id() == owner)
            .ok_or(CapacityError::MissingCombatant)?;
        zones.insert_slot_front(zone, slot)?;
        self.cards.push(card, Container::CardInstances)?;
        Ok(CardSlot(slot))
    }
}

/// Iterator over the cards in one pile.
#[derive(Clone)]
pub struct ZoneCards<'a> {
    state: &'a CombatState,
    slots: &'a [u16],
    next: usize,
}

impl<'a> Iterator for ZoneCards<'a> {
    type Item = &'a CardInstance;

    fn next(&mut self) -> Option<Self::Item> {
        while self.next < self.slots.len() {
            let slot = self.slots[self.next];
            self.next += 1;
            if let Some(card) = self.state.card(CardSlot(slot)) {
                return Some(card);
            }
        }
        None
    }
}

impl core::fmt::Debug for ZoneCards<'_> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_list().entries(self.clone()).finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cid(s: &str) -> CombatantId {
        CombatantId::new(s).unwrap()
    }
    fn def(s: &str) -> CombatantDefinitionId {
        CombatantDefinitionId::new(s).unwrap()
    }
    fn team(s: &str) -> TeamId {
        TeamId::new(s).unwrap()
    }
    fn rid(s: &str) -> ResourceId {
        ResourceId::new(s).unwrap()
    }
    fn dpid(s: &str) -> DefensivePoolId {
        DefensivePoolId::new(s).unwrap()
    }
    fn sdid(s: &str) -> StatusDefinitionId {
        StatusDefinitionId::new(s).unwrap()
    }
    fn siid(s: &str) -> StatusInstanceId {
        StatusInstanceId::new(s).unwrap()
    }
    fn cdid(s: &str) -> CardDefinitionId {
        CardDefinitionId::new(s).unwrap()
    }
    fn ciid(s: &str) -> CardInstanceId {
        CardInstanceId::new(s).unwrap()
    }
    fn tag(s: &str) -> TagId {
        TagId::new(s).unwrap()
    }
    fn cnt(s: &str) -> CounterId {
        CounterId::new(s).unwrap()
    }

    fn hero() -> Combatant {
        Combatant::new(cid("hero"), def("bureaucrat"), team("player"), 70, 70)
    }

    fn fight() -> CombatState {
        CombatState::new(CombatId::new("c1").unwrap(), 42)
    }

    // ---- enums: the canonical text writes (int), so the values are part of the format ----

    #[test]
    fn combat_result_values_match_the_reference() {
        assert_eq!(CombatResult::Ongoing as i32, 0);
        assert_eq!(CombatResult::Victory as i32, 1);
        assert_eq!(CombatResult::Defeat as i32, 2);
        assert_eq!(CombatResult::Draw as i32, 3);
        assert_eq!(CombatResult::Aborted as i32, 4);
    }

    #[test]
    fn combat_turn_phase_values_match_the_reference() {
        assert_eq!(CombatTurnPhase::WaitingToStartTurn as i32, 0);
        assert_eq!(CombatTurnPhase::TurnInProgress as i32, 1);
    }

    #[test]
    fn combatant_lifecycle_state_values_match_the_reference() {
        assert_eq!(CombatantLifecycleState::Alive as i32, 0);
        assert_eq!(CombatantLifecycleState::Downed as i32, 1);
        assert_eq!(CombatantLifecycleState::Dead as i32, 2);
        assert_eq!(CombatantLifecycleState::Removed as i32, 3);
        assert_eq!(CombatantLifecycleState::Escaped as i32, 4);
        assert_eq!(CombatantLifecycleState::Banished as i32, 5);
    }

    #[test]
    fn status_polarity_values_match_the_reference() {
        assert_eq!(StatusPolarity::Buff as i32, 0);
        assert_eq!(StatusPolarity::Debuff as i32, 1);
        assert_eq!(StatusPolarity::Neutral as i32, 2);
    }

    #[test]
    fn status_visibility_values_match_the_reference() {
        assert_eq!(StatusVisibility::Visible as i32, 0);
        assert_eq!(StatusVisibility::Hidden as i32, 1);
        assert_eq!(StatusVisibility::DebugOnly as i32, 2);
    }

    #[test]
    fn card_zone_values_match_the_reference() {
        assert_eq!(CardZone::DrawPile as i32, 0);
        assert_eq!(CardZone::Hand as i32, 1);
        assert_eq!(CardZone::DiscardPile as i32, 2);
        assert_eq!(CardZone::ExhaustPile as i32, 3);
        assert_eq!(CardZone::BanishedPile as i32, 4);
        assert_eq!(CardZone::QueuePile as i32, 5);
        assert_eq!(CardZone::SetAsidePile as i32, 6);
        // `ALL` must be the same order, because that is the order the hash writes the piles in.
        for (i, zone) in CardZone::ALL.iter().enumerate() {
            assert_eq!(zone.index(), i);
            assert_eq!(*zone as i32, i as i32);
        }
        assert_eq!(CardZone::ALL.len(), CARD_ZONE_COUNT);
    }

    #[test]
    fn card_zone_wire_names_are_the_hashers_keys() {
        // Verbatim from CombatStateHasher.AppendCardZones.
        assert_eq!(CardZone::DrawPile.wire_name(), "draw");
        assert_eq!(CardZone::Hand.wire_name(), "hand");
        assert_eq!(CardZone::DiscardPile.wire_name(), "disc");
        assert_eq!(CardZone::ExhaustPile.wire_name(), "exh");
        assert_eq!(CardZone::BanishedPile.wire_name(), "ban");
        assert_eq!(CardZone::QueuePile.wire_name(), "queue");
        assert_eq!(CardZone::SetAsidePile.wire_name(), "aside");
    }

    // ---- identity ----

    #[test]
    fn id_is_bounded_and_ascii_only() {
        let longest = "standard.first_attack_each_turn_free";
        // 36 bytes: "standard." (9) + "first_attack_each_turn_free" (27). Counted, not guessed -
        // this is what ID_CAP = 40 has to leave room for.
        assert_eq!(longest.len(), 36);
        assert!(CombatantId::new(longest).is_ok(), "standard ids must fit");
        assert!(CombatantId::CAP > longest.len());

        assert_eq!(CombatantId::new("").unwrap().as_str(), "");
        assert!(CombatantId::new("").unwrap().is_empty());

        let too_long = "x".repeat(CombatantId::CAP + 1);
        assert_eq!(
            CombatantId::new(&too_long).unwrap_err(),
            CapacityError::IdTooLong {
                cap: CombatantId::CAP,
                len: CombatantId::CAP + 1
            }
        );

        // Non-ASCII is refused: above U+007F, UTF-16 ordinal order and UTF-8 byte order diverge
        // (spec §3-D13), so an id that compares one way in C# would compare another way here.
        assert_eq!(CombatantId::new("héro").unwrap_err(), CapacityError::IdNotAscii);
        assert_eq!(CombatantId::new("英雄").unwrap_err(), CapacityError::IdNotAscii);

        // Instance ids are generated as card_%06d / status_%06d / summoned_%06d.
        assert!(CardInstanceId::new("card_000001").is_ok());
        assert!(StatusInstanceId::new("status_000001").is_ok());
        assert_eq!(CardInstanceId::new("card_000001").unwrap().len(), 11);
        assert!(StatusInstanceId::new("status_000001").is_ok());
        assert!(CardInstanceId::CAP >= "status_000001".len());
        assert!(INSTANCE_ID_CAP >= "summoned_000001".len());
    }

    #[test]
    fn ident_order_is_ascii_byte_order() {
        // §3-D9: when ids become interned u16 handles, `(Priority, Id)` ordering is STILL string
        // order. So the model's `Ord` has to be `StringComparer.Ordinal` on ASCII == byte order.
        let unsorted = [
            "a", "ab", "a_", "Z", "card_9", "card_10", "standard.poison", "standard.poison.x", "",
            "0", "9", "10", "_",
        ];
        let mut ids: Vec<TagId> = unsorted.iter().map(|s| TagId::new(s).unwrap()).collect();
        ids.sort_unstable();

        let mut strings: Vec<&str> = unsorted.to_vec();
        strings.sort_unstable_by(|a, b| a.as_bytes().cmp(b.as_bytes()));

        let ordered: Vec<&str> = ids.iter().map(TagId::as_str).collect();
        assert_eq!(ordered, strings, "Ident order must equal byte order");

        // The orderings that C#'s Ordinal comparer gives, spelled out so a regression is loud:
        assert!(TagId::new("Z").unwrap() < TagId::new("a").unwrap()); // 0x5A < 0x61
        assert!(TagId::new("a").unwrap() < TagId::new("ab").unwrap()); // prefix sorts first
        assert!(TagId::new("card_10").unwrap() < TagId::new("card_9").unwrap()); // '1' < '9'
        assert!(TagId::new("9").unwrap() < TagId::new("_").unwrap()); // '9' < '_'
        assert!(TagId::new("").unwrap() < TagId::new("0").unwrap());
        assert_eq!(TagId::new("x").unwrap().cmp(&TagId::new("x").unwrap()), Ordering::Equal);
        // Above U+007F would break this, which is exactly why Ident::new refuses it.
        assert!(matches!(
            TagId::new("\u{4e2d}").unwrap_err(),
            CapacityError::IdNotAscii
        ));
    }

    // ---- containers ----

    #[test]
    fn a_full_container_reports_instead_of_dropping() {
        let mut list: Bounded<TagId, 2> = Bounded::new();
        assert!(list.is_empty());
        list.push(tag("a"), Container::Tags).unwrap();
        list.push(tag("b"), Container::Tags).unwrap();
        assert_eq!(
            list.push(tag("c"), Container::Tags).unwrap_err(),
            CapacityError::Full(Container::Tags)
        );
        // The two that fit are untouched, in order, and nothing was silently replaced.
        assert_eq!(list.len(), 2);
        assert_eq!(list.as_slice(), &[tag("a"), tag("b")]);
        assert_eq!(list.pop(), Some(tag("b")));
        list.clear();
        assert!(list.is_empty());
    }

    #[test]
    fn a_full_container_never_truncates_an_id() {
        // The container-level version of the writer's rule: out of room means an error, not a
        // half-written element.
        let mut list: Bounded<TagId, 1> = Bounded::new();
        list.push(tag("status_application_interceptor"), Container::Tags)
            .unwrap();
        assert_eq!(list.as_slice()[0].as_str(), "status_application_interceptor");
        assert_eq!(list.len(), 1);
    }

    #[test]
    fn counters_and_pools_upsert_in_key_byte_order() {
        let mut c = hero();
        // Inserted out of order on purpose.
        c.set_resource(rid("standard.energy"), 3, Some(3)).unwrap();
        c.set_resource(rid("standard.focus"), 1, None).unwrap();
        c.set_resource(rid("aaa"), 9, Some(1)).unwrap();
        let keys: Vec<&str> = c.resources().iter().map(|r| r.key.as_str()).collect();
        assert_eq!(keys, ["aaa", "standard.energy", "standard.focus"]);

        // Upsert, not append: the dictionary semantics of the reference.
        c.set_resource(rid("standard.energy"), 5, Some(3)).unwrap();
        assert_eq!(c.resources().len(), 3);
        assert_eq!(c.resources()[1].pool.current, 5);
        assert_eq!(c.resources()[1].pool.max, Some(3));

        c.set_defensive_pool(dpid("standard.block"), 6, Some(999)).unwrap();
        c.set_defensive_pool(dpid("aaa.block"), 1, None).unwrap();
        let keys: Vec<&str> = c.defensive_pools().iter().map(|p| p.key.as_str()).collect();
        assert_eq!(keys, ["aaa.block", "standard.block"]);

        c.set_counter(cnt("zzz"), 2).unwrap();
        c.set_counter(cnt("aaa"), 1).unwrap();
        c.set_counter(cnt("zzz"), 7).unwrap();
        let keys: Vec<&str> = c.counters().iter().map(|k| k.key.as_str()).collect();
        assert_eq!(keys, ["aaa", "zzz"]);
        assert_eq!(c.counters()[1].value, 7);

        c.add_tag(tag("skill")).unwrap();
        c.add_tag(tag("attack")).unwrap();
        c.add_tag(tag("attack")).unwrap(); // set semantics: no duplicate
        let tags: Vec<&str> = c.tags().iter().map(TagId::as_str).collect();
        assert_eq!(tags, ["attack", "skill"]);
    }

    #[test]
    fn too_many_resource_pools_is_an_error() {
        let mut c = hero();
        for i in 0..MAX_RESOURCES {
            c.set_resource(ResourceId::new(&format!("r{i:02}")).unwrap(), 1, None)
                .unwrap();
        }
        assert_eq!(
            c.set_resource(rid("overflow"), 1, None).unwrap_err(),
            CapacityError::Full(Container::Resources)
        );
        assert_eq!(c.resources().len(), MAX_RESOURCES);
    }

    #[test]
    fn statuses_keep_instance_order_and_are_not_sorted() {
        let mut c = hero();
        c.push_status(StatusInstance::new(siid("status_000003"), sdid("standard.weak"), StatusPolarity::Debuff))
            .unwrap();
        c.push_status(StatusInstance::new(siid("status_000001"), sdid("standard.poison"), StatusPolarity::Debuff))
            .unwrap();
        c.push_status(StatusInstance::new(siid("status_000002"), sdid("standard.strength"), StatusPolarity::Buff))
            .unwrap();
        let ids: Vec<&str> = c.statuses().iter().map(|s| s.id.as_str()).collect();
        assert_eq!(ids, ["status_000003", "status_000001", "status_000002"]);
    }

    #[test]
    fn too_many_statuses_is_an_error() {
        let mut c = hero();
        for i in 0..MAX_STATUSES_PER_COMBATANT {
            c.push_status(StatusInstance::new(
                StatusInstanceId::new(&format!("status_{i:06}")).unwrap(),
                sdid("standard.poison"),
                StatusPolarity::Debuff,
            ))
            .unwrap();
        }
        let extra = StatusInstance::new(siid("status_999999"), sdid("standard.poison"), StatusPolarity::Debuff);
        assert_eq!(
            c.push_status(extra).unwrap_err(),
            CapacityError::Full(Container::Statuses)
        );
        assert_eq!(c.statuses().len(), MAX_STATUSES_PER_COMBATANT);
    }

    #[test]
    fn temporary_rules_sort_by_id_and_reject_duplicates() {
        let mut s = fight();
        let et = EventTypeName::new("RogueDeck.Core.Combat.TurnStartedCombatEvent").unwrap();
        s.add_temporary_rule(TemporaryRule::new(
            TriggeredEffectDefinitionId::new("rule.b").unwrap(),
            et,
            1,
            1,
        ))
        .unwrap();
        s.add_temporary_rule(TemporaryRule::new(
            TriggeredEffectDefinitionId::new("rule.a").unwrap(),
            et,
            1,
            1,
        ))
        .unwrap();
        assert_eq!(s.temporary_rules().len(), 2);
        assert_eq!(s.temporary_rules()[0].id.as_str(), "rule.a");
        assert_eq!(s.temporary_rules()[1].id.as_str(), "rule.b");
        assert_eq!(
            s.add_temporary_rule(TemporaryRule::new(
                TriggeredEffectDefinitionId::new("rule.a").unwrap(),
                et,
                1,
                2,
            ))
            .unwrap_err(),
            CapacityError::DuplicateKey
        );
        assert_eq!(s.temporary_rules()[0].installed_turn, 1);
    }

    #[test]
    fn adding_a_duplicate_combatant_is_rejected_like_the_reference() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        assert_eq!(
            s.add_combatant(hero()).unwrap_err(),
            CapacityError::DuplicateCombatant
        );
        assert_eq!(s.combatants().len(), 1);
        assert_eq!(s.turn_order().len(), 1);
    }

    #[test]
    fn set_turn_order_reorders_without_moving_storage() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        s.add_combatant(Combatant::new(cid("ogre"), def("ogre"), team("enemy"), 30, 30)).unwrap();
        // Storage order is add order, and the turn order starts out the same.
        let stored: Vec<&str> = s.combatants().iter().map(|c| c.id.as_str()).collect();
        assert_eq!(stored, ["hero", "ogre"]);

        s.set_turn_order(&[cid("ogre"), cid("hero")]).unwrap();
        let order: Vec<&str> = s.turn_order().iter().map(|c| c.as_str()).collect();
        assert_eq!(order, ["ogre", "hero"]);
        // The combatants themselves did not move: only the order the canonical text walks.
        let stored: Vec<&str> = s.combatants().iter().map(|c| c.id.as_str()).collect();
        assert_eq!(stored, ["hero", "ogre"]);

        // An unknown id is an error, not a dropped line (the reference would throw out of
        // `GetCombatant`).
        assert_eq!(
            s.set_turn_order(&[cid("hero"), cid("nobody")]).unwrap_err(),
            CapacityError::MissingCombatant
        );
        assert_eq!(
            s.set_turn_order(&[cid("hero"), cid("hero")]).unwrap_err(),
            CapacityError::DuplicateKey
        );
        // Both failures left the previous order intact.
        let order: Vec<&str> = s.turn_order().iter().map(|c| c.as_str()).collect();
        assert_eq!(order, ["ogre", "hero"]);
    }

    #[test]
    fn the_first_combatant_becomes_the_active_one() {
        let mut s = fight();
        assert_eq!(s.active_combatant_id, None);
        s.add_combatant(hero()).unwrap();
        s.add_combatant(Combatant::new(
            cid("ogre"),
            def("ogre"),
            team("enemy"),
            30,
            30,
        ))
        .unwrap();
        assert_eq!(s.active_combatant_id, Some(cid("hero")));
        // Add order is turn order (CombatState.cs:231-232).
        let order: Vec<&str> = s.turn_order().iter().map(CombatantId::as_str).collect();
        assert_eq!(order, ["hero", "ogre"]);
    }

    #[test]
    fn combatant_capacity_is_enforced_and_lists_stay_in_step() {
        let mut s = fight();
        for i in 0..MAX_COMBATANTS {
            s.add_combatant(Combatant::new(
                CombatantId::new(&format!("c{i:02}")).unwrap(),
                def("test.unit"),
                team("enemy"),
                1,
                1,
            ))
            .unwrap();
        }
        assert_eq!(
            s.add_combatant(Combatant::new(
                cid("overflow"),
                def("test.unit"),
                team("enemy"),
                1,
                1
            ))
            .unwrap_err(),
            CapacityError::Full(Container::Combatants)
        );
        assert_eq!(s.combatants().len(), MAX_COMBATANTS);
        assert_eq!(s.turn_order().len(), MAX_COMBATANTS);
        // The rejected combatant left nothing behind - not in the list, not the active id.
        assert!(s.combatant(&cid("overflow")).is_none());
        assert_eq!(s.active_combatant_id, Some(cid("c00")));
    }

    #[test]
    fn cards_land_in_the_right_pile_and_in_pile_order() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        let a = s
            .push_card(&cid("hero"), CardZone::DrawPile, CardInstance::new(ciid("card_000001"), cdid("standard.strike")))
            .unwrap();
        let b = s
            .push_card(&cid("hero"), CardZone::DrawPile, CardInstance::new(ciid("card_000002"), cdid("standard.defend")))
            .unwrap();
        s.push_card(&cid("hero"), CardZone::Hand, CardInstance::new(ciid("card_000003"), cdid("standard.strike")))
            .unwrap();

        let draw: Vec<&str> = s.zone_cards(&cid("hero"), CardZone::DrawPile).map(|c| c.id.as_str()).collect();
        assert_eq!(draw, ["card_000001", "card_000002"]);
        let hand: Vec<&str> = s.zone_cards(&cid("hero"), CardZone::Hand).map(|c| c.id.as_str()).collect();
        assert_eq!(hand, ["card_000003"]);
        assert_eq!(s.card(a).unwrap().definition_id.as_str(), "standard.strike");
        assert_eq!(s.card(b).unwrap().definition_id.as_str(), "standard.defend");
        assert_eq!(s.card_count(), 3);
        assert_eq!(s.card_zones(&cid("hero")).unwrap().count(CardZone::Hand), 1);

        assert!(s.remove_card(&cid("hero"), a));
        let draw: Vec<&str> = s.zone_cards(&cid("hero"), CardZone::DrawPile).map(|c| c.id.as_str()).collect();
        assert_eq!(draw, ["card_000002"]);
        assert!(!s.remove_card(&cid("hero"), a), "already gone");
        assert_eq!(
            s.push_card(&cid("nobody"), CardZone::Hand, CardInstance::new(ciid("card_000009"), cdid("standard.strike")))
                .unwrap_err(),
            CapacityError::MissingCombatant
        );
    }

    #[test]
    fn a_card_cannot_enter_a_full_pile_even_with_pool_room() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        for i in 0..MAX_CARDS_PER_ZONE {
            s.push_card(
                &cid("hero"),
                CardZone::Hand,
                CardInstance::new(
                    CardInstanceId::new(&format!("card_{i:06}")).unwrap(),
                    cdid("standard.strike"),
                ),
            )
            .unwrap();
        }
        assert_eq!(
            s.push_card(&cid("hero"), CardZone::Hand, CardInstance::new(ciid("card_999999"), cdid("standard.strike")))
                .unwrap_err(),
            CapacityError::Full(Container::CardsInZone(CardZone::Hand))
        );
        // Both of the other piles still have room: the pool slot was not consumed by the failure.
        s.push_card(&cid("hero"), CardZone::DiscardPile, CardInstance::new(ciid("card_999999"), cdid("standard.strike")))
            .unwrap();
    }

    #[test]
    fn the_card_pool_is_bounded_for_the_whole_fight() {
        // The pool bound is on the whole fight, and it is deliberately NOT the same as the
        // per-pile bound: 224 instances spread over seven piles averages 32 each, well under the
        // 96-per-pile ceiling. Filling one pile is what hits that ceiling first (see
        // `a_card_cannot_enter_a_full_pile_even_with_pool_room`), so this test spreads the cards
        // out the way a real fight does and expects the POOL to be the wall.
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        for i in 0..MAX_CARD_INSTANCES {
            let zone = CardZone::ALL[i % CARD_ZONE_COUNT];
            let card = CardInstance::new(
                CardInstanceId::new(&format!("card_{i:06}")).unwrap(),
                cdid("standard.strike"),
            );
            s.push_card(&cid("hero"), zone, card).unwrap();
        }
        assert_eq!(s.card_count(), MAX_CARD_INSTANCES);

        let err = s
            .push_card(
                &cid("hero"),
                CardZone::Hand,
                CardInstance::new(ciid("card_999999"), cdid("standard.strike")),
            )
            .unwrap_err();
        assert_eq!(err, CapacityError::Full(Container::CardInstances));
        assert_eq!(s.card_count(), MAX_CARD_INSTANCES, "the failed push added nothing");

        // Each pile is still far from its own ceiling, which is the point: with MAX_CARD_INSTANCES
        // this small, a single pile can never reach MAX_CARDS_PER_ZONE in a legal fight.
        for zone in CardZone::ALL {
            let n = s.card_zones(&cid("hero")).unwrap().count(zone);
            assert!(n <= MAX_CARDS_PER_ZONE, "{zone:?} holds {n}");
        }
    }

    #[test]
    fn detaching_card_zones_mirrors_the_dictionary_lookup() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        s.add_combatant(Combatant::new(cid("ogre"), def("ogre"), team("enemy"), 30, 30))
            .unwrap();
        assert!(s.card_zones(&cid("hero")).is_some());
        assert!(s.detach_card_zones(&cid("hero")));
        assert!(!s.detach_card_zones(&cid("hero")));
        // The combatant stays in the turn order; only its `cz=` entry is gone.
        assert_eq!(s.turn_order(), &[cid("hero"), cid("ogre")]);
        assert!(s.card_zones(&cid("ogre")).is_some());
        assert!(matches!(
            s.push_card(&cid("hero"), CardZone::Hand, CardInstance::new(ciid("card_000001"), cdid("standard.strike"))),
            Err(CapacityError::MissingCombatant)
        ));
    }

    #[test]
    fn mark_helpers_keep_marks_sorted_and_deduplicated() {
        let mut card = CardInstance::new(ciid("card_000001"), cdid("standard.strike"));
        card.add_mark(tag("zzz")).unwrap();
        card.add_mark(tag("aaa")).unwrap();
        card.add_mark(tag("aaa")).unwrap();
        assert_eq!(card.marks().len(), 2);
        let marks: Vec<&str> = card.marks().iter().map(TagId::as_str).collect();
        assert_eq!(marks, ["aaa", "zzz"]);

        card.set_mark_counter(cnt("standard.card_cost_delta"), -1).unwrap();
        card.set_mark_counter(cnt("aaa"), 1).unwrap();
        card.set_mark_counter(cnt("standard.card_cost_delta"), -2).unwrap();
        assert_eq!(card.mark_counters().len(), 2);
        let keys: Vec<&str> = card.mark_counters().iter().map(|c| c.key.as_str()).collect();
        assert_eq!(keys, ["aaa", "standard.card_cost_delta"]);
        assert_eq!(card.mark_counters()[1].value, -2);

        // Fill a FRESH card to the cap: this one already holds two marks, so topping it up would
        // be testing the cap against the wrong starting point.
        let mut full = CardInstance::new(ciid("card_000002"), cdid("standard.strike"));
        for i in 0..MAX_MARKS_PER_CARD {
            full.add_mark(TagId::new(&format!("m{i}")).unwrap()).unwrap();
        }
        assert_eq!(full.marks().len(), MAX_MARKS_PER_CARD);
        assert_eq!(
            full.add_mark(tag("overflow")).unwrap_err(),
            CapacityError::Full(Container::Marks)
        );
        // The refusal left the four that fit exactly as they were.
        let marks: Vec<&str> = full.marks().iter().map(TagId::as_str).collect();
        assert_eq!(marks, ["m0", "m1", "m2", "m3"]);
    }

    #[test]
    fn a_fresh_state_matches_the_reference_constructor() {
        let s = fight();
        assert_eq!(s.current_round, 1);
        assert_eq!(s.current_turn, 1);
        assert_eq!(s.turn_phase, CombatTurnPhase::WaitingToStartTurn);
        assert_eq!(s.result, CombatResult::Ongoing);
        assert_eq!(s.random_step, 0);
        assert_eq!(s.next_status_instance_number, 1);
        assert_eq!(s.next_card_instance_number, 1);
        assert_eq!(s.next_effect_chain_number, 1);
        assert_eq!(s.next_program_execution_id, 1);
        assert!(s.turn_order().is_empty());
        assert!(s.combatants().is_empty());
        assert!(s.global_statuses().is_empty());
        assert!(s.temporary_rules().is_empty());
        assert_eq!(s.card_count(), 0);
    }

    #[test]
    fn event_type_name_holds_a_dotnet_full_name() {
        let longest = "RogueDeck.Core.Combat.DiscardPileShuffledIntoDrawPileCombatEvent";
        assert_eq!(longest.len(), 64);
        assert!(EventTypeName::new(longest).is_ok());
        assert!(EventTypeName::new(&"x".repeat(EVENT_TYPE_CAP + 1)).is_err());
    }

    #[test]
    fn state_fits_the_sram_plan() {
        // Not a "nice to have": the whole point of fixed capacities is that the cost is known
        // before the firmware is flashed. Measured on the reference host; ids are still ASCII
        // strings here, so this is the pessimistic end of the range (interning them - §3-D9 -
        // takes the card pool from ~95 KB to a few KB).
        let size = core::mem::size_of::<CombatState>();
        std::println!("size_of::<CombatState>() = {size} bytes ({} KiB)", size / 1024);
        std::println!(
            "  card pool  : {} x {} = {} bytes",
            MAX_CARD_INSTANCES,
            core::mem::size_of::<CardInstance>(),
            MAX_CARD_INSTANCES * core::mem::size_of::<CardInstance>()
        );
        std::println!(
            "  combatants : {} x {} = {} bytes",
            MAX_COMBATANTS,
            core::mem::size_of::<Combatant>(),
            MAX_COMBATANTS * core::mem::size_of::<Combatant>()
        );
        std::println!(
            "  piles      : {} x {} = {} bytes",
            MAX_COMBATANTS,
            core::mem::size_of::<CardZones>(),
            MAX_COMBATANTS * core::mem::size_of::<CardZones>()
        );
        // 动画日志（§142）：一行一个分量，再打**整个结构体** —— 两者的差就是对齐，
        // 而"对齐"必须看得见，否则"总量加不出来"又会变成一句看不懂的话。
        std::println!(
            "  beats      : {} x {} (beat) + {} x {} (def) + {} (len/defs_len/dropped) = {} B, \
             size_of::<BeatLog>() = {} B",
            crate::beat::MAX_BEATS,
            core::mem::size_of::<crate::beat::Beat>(),
            crate::beat::MAX_BEAT_DEFS,
            core::mem::size_of::<Ident<ID_CAP>>(),
            core::mem::size_of::<u16>() + 2 * core::mem::size_of::<u8>(),
            crate::beat::MAX_BEATS * core::mem::size_of::<crate::beat::Beat>()
                + crate::beat::MAX_BEAT_DEFS * core::mem::size_of::<Ident<ID_CAP>>()
                + core::mem::size_of::<u16>()
                + 2 * core::mem::size_of::<u8>(),
            core::mem::size_of::<crate::beat::BeatLog>()
        );
        // 事件队列这一块（批次 1）。**逐列打**，因为"总量对、分量烂"是这张账本栽过的坑：
        // 六个队列 + 链 arena 加起来必须能和"总量 − 上面三个分量"对上。
        std::println!(
            "  queue      : effects {} x {} | events {} x {} | conts {} x {} | chains {} x {} = {} B",
            MAX_PENDING_EFFECTS,
            core::mem::size_of::<EffectRequest>(),
            MAX_PENDING_EVENTS,
            core::mem::size_of::<CombatEvent>(),
            MAX_PENDING_CONTINUATIONS,
            core::mem::size_of::<Continuation>(),
            MAX_LIVE_CHAINS,
            core::mem::size_of::<ChainRecord>(),
            MAX_PENDING_EFFECTS
                * (core::mem::size_of::<EffectRequest>()
                    + core::mem::size_of::<ChainSlot>()
                    + core::mem::size_of::<Option<ProgramExecutionSlot>>())
                + MAX_PENDING_EVENTS
                    * (core::mem::size_of::<CombatEvent>() + core::mem::size_of::<ChainSlot>())
                + MAX_PENDING_CONTINUATIONS * core::mem::size_of::<Continuation>()
                + MAX_LIVE_CHAINS * core::mem::size_of::<ChainRecord>()
        );
        // 上限本身是一份**带数字的决定**，不是一句"留点余量"：
        //   192 KiB 是阶段一（无事件队列）的上界；224 KiB 是"中档"（`MAX_EVENT_ID_LIST = 8`）
        //   那一版决议的上界；**现在是 240 KiB**，换掉的是**忠实档**（集合型事件不截断）。
        //
        // ⚠️ **这次抬界换的是语义完整性，不是"让测试过"**。`MAX_EVENT_ID_LIST = 8` 会把
        //   集合型事件携带的 id 列表**静默截断**（参考在这里无界），而"一个容量常量放大后
        //   行为会变 ⇒ 它是语义，不是实现选择；不许拿它去换预算"（
        //   `docs/spec/event-queue-interface.md` §4.3 末的硬规则）。省下的 17.4 KiB 是那条
        //   降级的价格标签，不是它的理由。
        //
        // 余量：实测 `size_of::<CombatState>()` 见本测试的 println（诚实读数，不抄第二份）。
        //   决议的参照点是 §10.2 探针的**忠实档 231,256 B**（那是"事件枚举按参考全集 41 个
        //   变体"的形状）；批次 1 只声明了接了线的那 5 个变体，所以实测**小于**它 ——
        //   240 KiB = 245,760 B 对两者都成立（对探针值余 6.3%，对实测值余更多）。
        //
        // 既有事实（不是这次的论据，但每次抬界都该看一眼）：`CombatState` 是 **POD**
        //   （`Copy`、无指针、无内部引用），ESP32-P4 有 **16/32 MB PSRAM** ⇒ 省这些字节
        //   省的只是**片上** SRAM，而不是"这东西放不下"。真要多开，杠杆是 §3-D9 的 id intern
        //   （98,560 B 卡池 + 57,984 B 战斗员），不是砍事件的集合上限。
        //
        // 两处必须一起改：这里和 `kernel/rd-sizeprobe/src/lib.rs` 的
        //   `the_state_model_fits_the_sram_budget_and_we_know_its_exact_size`。
        assert!(
            size <= 240 * 1024,
            "CombatState grew to {size} bytes, past the 240 KB ceiling this model was sized for \
             (245,760 B = the 231,256 B faithful-tier event-queue measurement + 6.3% headroom, \
              and the ceiling is a *semantic* decision - see the comment above)"
        );
        // The reference's own packed estimate for the same fight is ~9 KB (spec §5.2); the
        // difference is the un-interned ASCII ids the task's D9 note schedules for later.
        assert!(size >= 64 * 1024, "unexpectedly small at {size} bytes - capacities changed?");
    }

    // ── Moving cards between piles ──────────────────────────────────────────────────────────────
    //
    // 下面这一对测试是**成对设计的**：第一个证明"删了再建"真的会把池子吃光，
    // 第二个证明 move_card 不会。单看第二个是空断言 —— 它需要一个反例来证明自己不是。

    fn deck_of(n: usize) -> CombatState {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        for i in 0..n {
            let id = std::format!("card_{:06}", i + 1);
            s.push_card(&cid("hero"), CardZone::DrawPile,
                        CardInstance::new(ciid(&id), cdid("standard.strike"))).unwrap();
        }
        s
    }

    #[test]
    fn the_naive_push_remove_way_really_does_run_the_pool_dry() {
        // 反例。这就是"移动 = 从一堆删掉、再往另一堆新建"的代价：
        // 每次移动吃一个 MAX_CARD_INSTANCES 槽位。10 张的牌组循环，最多撑
        // MAX_CARD_INSTANCES/10 轮就撞 Full(CardInstances)。
        //
        // ⚠️ 这条测试第一版写错了：抽到 Hand 却从 DiscardPile 补充，于是第 1 轮之后
        // 抽牌堆和弃牌堆都空着，循环空转到结束 —— 断言"应当报错"自然失败。
        // 循环必须闭合成 抽牌堆 → 手牌 → 弃牌堆 → 抽牌堆。
        let mut s = deck_of(10);
        let hero = cid("hero");
        let mut moves = 0usize;
        let mut failed_at = None;
        'outer: for round in 0..64 {
            // 弃牌堆 → 抽牌堆（同样用"删了再建"这个错误做法）
            let back: std::vec::Vec<u16> = s
                .card_zones(&hero).unwrap().slots(CardZone::DiscardPile).to_vec();
            for slot in back {
                let card = *s.card(CardSlot(slot)).unwrap();
                assert!(s.remove_card(&hero, CardSlot(slot)));
                moves += 1;
                if let Err(e) = s.push_card(&hero, CardZone::DrawPile, card) {
                    failed_at = Some((round, moves, e));
                    break 'outer;
                }
            }
            // 抽牌堆 → 手牌 → 弃牌堆
            while let Some(top) = s.card_zones(&hero).unwrap().slots(CardZone::DrawPile).first().copied() {
                let card = *s.card(CardSlot(top)).unwrap();
                assert!(s.remove_card(&hero, CardSlot(top)));
                moves += 1;
                if let Err(e) = s.push_card(&hero, CardZone::Hand, card) {
                    failed_at = Some((round, moves, e));
                    break 'outer;
                }
                let in_hand = *s.card_zones(&hero).unwrap().slots(CardZone::Hand).last().unwrap();
                let card = *s.card(CardSlot(in_hand)).unwrap();
                assert!(s.remove_card(&hero, CardSlot(in_hand)));
                moves += 1;
                if let Err(e) = s.push_card(&hero, CardZone::DiscardPile, card) {
                    failed_at = Some((round, moves, e));
                    break 'outer;
                }
            }
        }
        let (_round, moves, err) = failed_at.expect(
            "删了再建**应该**会吃光池子；如果这里没报错，说明池容量或语义变了，\
             而 move_card 的存在理由要重新论证");
        assert_eq!(err, CapacityError::Full(Container::CardInstances));
        // 池子从 10 张起步，每次移动 +1，所以在池子达到 MAX_CARD_INSTANCES 的那一次**尝试**上失败。
        // moves 在尝试之前自增，所以它读到的是"第几次尝试"，比"成功了几次"多 1。
        // （第一版这里写成了 MAX_CARD_INSTANCES - 10，差一 —— 是算错了，不是实现错了。）
        assert_eq!(moves, MAX_CARD_INSTANCES - 10 + 1,
                   "撞满的尝试次数与「每次移动吃一个槽位」不符 —— 说明槽位语义变了");
        assert_eq!(moves - 1, MAX_CARD_INSTANCES - 10, "成功移动 214 次刚好把池子从 10 填到 224");
        // 而且池子**确实**长到了上限 —— 这就是"移动在泄漏槽位"的直接证据。
        assert_eq!(s.card_count(), MAX_CARD_INSTANCES);
    }

    #[test]
    fn moving_a_card_reuses_its_pool_slot_so_a_long_fight_cannot_run_the_pool_dry() {
        // 正例。同样的循环，改用 move_card：池子永远不长。
        // 这条断言就是这个坑的封条 —— 它不需要"真打一局"也看得见。
        let mut s = deck_of(10);
        let hero = cid("hero");
        for round in 0..1000 {
            if s.card_zones(&hero).unwrap().is_empty(CardZone::DrawPile) {
                let moved = s.move_all_cards(&hero, CardZone::DiscardPile, CardZone::DrawPile).unwrap();
                assert_eq!(moved, 10, "第 {round} 轮：弃牌堆应当整堆搬回抽牌堆");
            }
            let slot = s.draw_card(&hero).unwrap().expect("抽牌堆非空");
            assert!(s.move_card(&hero, CardZone::Hand, CardZone::DiscardPile, slot,
                                ZonePlacement::Bottom).unwrap());
            assert_eq!(s.card_count(), 10,
                       "第 {round} 轮之后池子长了 —— 移动在分配新槽位，这就是 §27.8 那个坑");
        }
        // 1000 轮之后分布仍然正确：弃牌堆 10 张，其它为空。
        let z = s.card_zones(&hero).unwrap();
        assert_eq!(z.count(CardZone::DiscardPile), 10);
        assert_eq!(z.count(CardZone::DrawPile), 0);
        assert_eq!(z.count(CardZone::Hand), 0);
    }

    #[test]
    fn the_two_generators_hand_out_the_pre_increment_value() {
        // 参考：`new Id(_next…)` 之后才 `_next…++`（`CombatState.cs:513-518`、`:545-555`）。
        // 所以**第一个发出去的号是初值 1**。写成"先加再返回"会让整场每个 id 偏移 1，
        // 而偏移**不会自己暴露**：任何只比"变了没变"的测试都看不出来，只有逐字节对拍会。
        let mut s = fight();
        assert_eq!(s.next_program_execution_id, 1);
        assert_eq!(s.next_effect_chain_number, 1);

        assert_eq!(s.allocate_program_execution_id(), 1);
        assert_eq!(s.next_program_execution_id, 2);
        assert_eq!(s.allocate_program_execution_id(), 2);
        assert_eq!(s.next_program_execution_id, 3);

        assert_eq!(s.create_root_effect_chain(), 1);
        assert_eq!(s.next_effect_chain_number, 2);

        // 两个发号器**互不影响**（参考里是两个独立字段，不是共用一个计数器）。
        assert_eq!(s.next_program_execution_id, 3);
        assert_eq!(s.next_effect_chain_number, 2);
    }

    #[test]
    fn both_generators_are_hash_visible_so_a_host_that_forgets_them_diverges() {
        // 这条是上面那条的**封条**：光"能发号"不算修好，必须证明这两个数真的进了指纹。
        // 否则一个"永远不调发号器"的宿主会拿到一模一样的哈希 —— 而那正是补它们之前的状态。
        let render = |s: &CombatState| {
            let mut buf = [0u8; 8192];
            let mut w = crate::writer::TextWriter::new(&mut buf);
            crate::snapshot::write_hash_input(&mut w, s);
            assert!(!w.overflowed(), "8192 字节够一局空战斗的规范文本");
            std::string::String::from(w.as_str())
        };
        let mut s = fight();
        let before = render(&s);
        assert!(before.contains("chain_num=1"), "初值 1 必须出现在文本里");
        assert!(before.contains("exec_num=1"));

        let _ = s.allocate_program_execution_id();
        let _ = s.create_root_effect_chain();
        let after = render(&s);
        assert_ne!(before, after, "发了号但指纹没变 ⇒ 这两个字段没进哈希");
        assert!(after.contains("chain_num=2"));
        assert!(after.contains("exec_num=2"));
    }

    #[test]
    fn a_pool_slot_is_never_recycled_so_a_walk_over_indexes_stays_valid() {
        // ⚠️ 这条测试是给**另一个模块**立的闸门，所以要先说清它在保护谁：
        //
        // `exec.rs` 的 `forEachCardInZone` 在循环开始时快照的是**池槽位号**（`u16`），
        // 不是 `CardInstanceId`——因为每堆存的本来就是槽位号。它因此依赖一条此前
        // **只写在注释里、没有任何测试钉住**的不变量：
        //
        //   **一个池槽位在一局里永远只属于一张卡。**
        //
        // 机制是：`push_card` 取 `cards.len()` 作槽位、`remove_card` 只把槽位从牌堆里摘掉
        // （**不**缩短 `cards`）、`move_card` 复用同一槽位。所以池子只增不减，槽位天然不回收。
        //
        // 一旦将来有人给 `cards` 引入回收（为了让 224 个槽够打更长的局），
        // 循环途中被搬走的那张卡留下的槽位就可能被**另一张卡**占用 ——
        // 于是 `forEachCardInZone` 会**静默地换一张牌**：不报错、不 panic，只是结果不对。
        // 所以这条断言是那个改法的强制停点：它红了，改的人必须先重新审视
        // `exec.rs` 里"快照槽位"这个决定。
        let mut s = deck_of(3);
        let hero = cid("hero");
        let slots: std::vec::Vec<u16> = s
            .card_zones(&hero)
            .unwrap()
            .slots(CardZone::DrawPile)
            .to_vec();
        assert_eq!(slots, [0, 1, 2], "池槽位从 0 开始按分配序编");

        // 退休中间那张，再压一张新的：新卡**不许**捡回槽位 1。
        let retired = CardSlot::from_index(1);
        assert!(s.remove_card(&hero, retired), "槽位 1 在抽牌堆里");
        let fresh = s
            .push_card(
                &hero,
                CardZone::Hand,
                CardInstance::new(ciid("card_900001"), cdid("standard.strike")),
            )
            .unwrap();
        assert_eq!(fresh.index(), 3, "退休的槽位被回收了 —— 见上面的注释");
        assert_ne!(fresh, retired);

        // 再退休一次（这次是最新那张），下一条仍然往后编。
        assert!(s.remove_card(&hero, fresh));
        let again = s
            .push_card(
                &hero,
                CardZone::Hand,
                CardInstance::new(ciid("card_900002"), cdid("standard.defend")),
            )
            .unwrap();
        assert_eq!(again.index(), 4);
        assert_ne!(again, retired);
        assert_ne!(again, fresh);

        // 而且"移动"不产生新槽位 ⇒ 走 1000 轮之后槽位号一个都没变。
        // （这一半与 `moving_a_card_reuses_its_pool_slot…` 同源，但那条只看长度，
        //   这条看**编号集合**：长度不变也可能是"回收了又分配"。）
        let before: std::vec::Vec<u16> = s
            .card_zones(&hero)
            .unwrap()
            .slots(CardZone::DrawPile)
            .to_vec();
        for _ in 0..1000 {
            let slot = s.draw_card(&hero).unwrap().unwrap();
            assert!(s
                .move_card(&hero, CardZone::Hand, CardZone::DrawPile, slot, ZonePlacement::Bottom)
                .unwrap());
        }
        let after: std::vec::Vec<u16> = s
            .card_zones(&hero)
            .unwrap()
            .slots(CardZone::DrawPile)
            .to_vec();
        assert_eq!(before, after, "1000 轮移动之后槽位编号集合变了");
        assert_eq!(s.card_count(), 5, "3 张初始 + 2 张新建");
    }

    #[test]
    fn draw_card_takes_the_front_of_the_draw_pile() {
        // 参考实现是 `_drawPile.RemoveAt(0)`（Cards/CardZones.cs:251）—— 抽的是**前面**那张。
        let mut s = deck_of(3);
        let hero = cid("hero");
        let front = s.card_zones(&hero).unwrap().slots(CardZone::DrawPile)[0];
        let got = s.draw_card(&hero).unwrap().unwrap();
        assert_eq!(got, CardSlot(front));
        assert_eq!(s.card_zones(&hero).unwrap().count(CardZone::DrawPile), 2);
        assert_eq!(s.card_zones(&hero).unwrap().slots(CardZone::Hand), &[front]);
    }

    #[test]
    fn draw_card_on_an_empty_pile_is_none_not_an_error() {
        let mut s = deck_of(0);
        assert_eq!(s.draw_card(&cid("hero")).unwrap(), None);
        assert_eq!(s.card_count(), 0);
    }

    #[test]
    fn move_card_top_lands_at_the_front_and_bottom_at_the_back() {
        // 位次不是装饰：堆的顺序会被写进规范文本，写错就改哈希。
        let mut s = deck_of(3);
        let hero = cid("hero");
        let slots: std::vec::Vec<u16> = s.card_zones(&hero).unwrap().slots(CardZone::DrawPile).to_vec();
        let (a, b, c) = (CardSlot(slots[0]), CardSlot(slots[1]), CardSlot(slots[2]));
        // 抽走三张，手牌序应为 a,b,c。
        for _ in 0..3 { s.draw_card(&hero).unwrap(); }
        assert_eq!(s.card_zones(&hero).unwrap().slots(CardZone::Hand), &[a.0, b.0, c.0]);
        // 把 c 移到弃牌堆顶（Bottom ⇒ 追加）：[c]
        s.move_card(&hero, CardZone::Hand, CardZone::DiscardPile, c, ZonePlacement::Bottom).unwrap();
        // 把 a 移到弃牌堆顶（Top ⇒ 插到前面）：[a, c]
        s.move_card(&hero, CardZone::Hand, CardZone::DiscardPile, a, ZonePlacement::Top).unwrap();
        assert_eq!(s.card_zones(&hero).unwrap().slots(CardZone::DiscardPile), &[a.0, c.0]);
        assert_eq!(s.card_zones(&hero).unwrap().slots(CardZone::Hand), &[b.0]);
    }

    #[test]
    fn move_card_from_a_pile_that_does_not_hold_it_is_a_no_op_not_an_error() {
        let mut s = deck_of(2);
        let hero = cid("hero");
        let in_draw = s.card_zones(&hero).unwrap().slots(CardZone::DrawPile)[0];
        // 那张牌在抽牌堆里，不在弃牌堆 —— 从弃牌堆"移动"它应当是 Ok(false) 且什么都不变。
        assert!(!s.move_card(&hero, CardZone::DiscardPile, CardZone::Hand,
                             CardSlot(in_draw), ZonePlacement::Bottom).unwrap());
        assert_eq!(s.card_zones(&hero).unwrap().count(CardZone::DrawPile), 2);
        assert_eq!(s.card_zones(&hero).unwrap().count(CardZone::Hand), 0);
    }

    #[test]
    fn move_all_cards_is_all_or_nothing_when_the_destination_cannot_take_them() {
        // 目的堆装不下时**一个字节也不改** —— "搬了一半"是参考实现里不存在的状态。
        let mut s = deck_of(3);
        let hero = cid("hero");
        // 先把弃牌堆塞到只剩 2 个空位。
        let filler = MAX_CARDS_PER_ZONE - 2;
        for i in 0..filler {
            let id = std::format!("filler_{:06}", i);
            s.push_card(&hero, CardZone::DiscardPile,
                        CardInstance::new(ciid(&id), cdid("standard.defend"))).unwrap();
        }
        let before_pool = s.card_count();
        let before_draw = s.card_zones(&hero).unwrap().count(CardZone::DrawPile);
        let err = s.move_all_cards(&hero, CardZone::DrawPile, CardZone::DiscardPile).unwrap_err();
        assert_eq!(err, CapacityError::Full(Container::CardsInZone(CardZone::DiscardPile)));
        // 两边都没动，池子也没动。
        assert_eq!(s.card_zones(&hero).unwrap().count(CardZone::DiscardPile), filler);
        assert_eq!(s.card_zones(&hero).unwrap().count(CardZone::DrawPile), before_draw);
        assert_eq!(s.card_count(), before_pool);
    }

    #[test]
    fn insert_card_front_allocates_a_new_slot_because_it_is_a_new_card() {
        let mut s = deck_of(2);
        let hero = cid("hero");
        let before = s.card_count();
        let new = s.insert_card_front(&hero, CardZone::DrawPile,
                                      CardInstance::new(ciid("card_900001"), cdid("standard.strike")))
            .unwrap();
        assert_eq!(s.card_count(), before + 1, "插的是**新卡**，本来就该占一个新槽位");
        assert_eq!(s.card_zones(&hero).unwrap().slots(CardZone::DrawPile)[0], new.0,
                   "Top 语义要求它排在最前面");
    }

    #[test]
    fn move_card_rejects_an_unknown_combatant_without_panicking() {
        let mut s = deck_of(1);
        let slot = CardSlot(s.card_zones(&cid("hero")).unwrap().slots(CardZone::DrawPile)[0]);
        assert_eq!(s.move_card(&cid("nobody"), CardZone::DrawPile, CardZone::Hand, slot,
                               ZonePlacement::Bottom).unwrap_err(),
                   CapacityError::MissingCombatant);
        assert_eq!(s.draw_card(&cid("nobody")).unwrap_err(), CapacityError::MissingCombatant);
        assert_eq!(s.move_all_cards(&cid("nobody"), CardZone::DrawPile, CardZone::Hand).unwrap_err(),
                   CapacityError::MissingCombatant);
    }

    // ── Bounded::retain ─────────────────────────────────────────────────────────────────────────

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    struct N(i32);
    impl Empty for N {
        const EMPTY: Self = N(0);
    }

    #[test]
    fn bounded_retain_keeps_order_and_drops_the_rest() {
        let mut b: Bounded<N, 8> = Bounded::new();
        for i in 1..=6 {
            b.push(N(i), Container::TemporaryRules).unwrap();
        }
        b.retain(|n| n.0 % 2 == 0);
        // 顺序必须保留（不是"后进先出"、也不是被插入排序过）。
        assert_eq!(b.as_slice(), &[N(2), N(4), N(6)]);
        // 还能继续 push 到原容量 —— 说明 len 真的降下来了，不是只把元素藏起来。
        for i in 7..=11 {
            b.push(N(i), Container::TemporaryRules).unwrap();
        }
        assert_eq!(b.as_slice().len(), 8);
    }

    #[test]
    fn bounded_retain_that_keeps_nothing_empties_the_container() {
        let mut b: Bounded<N, 4> = Bounded::new();
        b.push(N(1), Container::TemporaryRules).unwrap();
        b.retain(|_| false);
        assert!(b.as_slice().is_empty());
    }

    // ── 临时规则到期（参考 `CombatState.cs:572-592` + `TemporaryTriggeredProgram.cs:130-145`）──

    fn rule(s: &mut CombatState, id: &str) -> TemporaryRule {
        let et = EventTypeName::new("RogueDeck.Core.Combat.TurnStartedCombatEvent").unwrap();
        let r = TemporaryRule::new(TriggeredEffectDefinitionId::new(id).unwrap(), et, 1, 1);
        s.add_temporary_rule(r).unwrap();
        r
    }

    fn rule_ids(s: &CombatState) -> std::vec::Vec<&str> {
        s.temporary_rules().iter().map(|r| r.id.as_str()).collect()
    }

    #[test]
    fn a_turn_boundary_removes_only_expired_rules_and_leaves_the_others() {
        // 这条就是"清空 vs 只移除到期"的分界线。参考实现只删到期的，所以
        // 没有到期字段的规则、以及"只按轮到期"的规则都必须活过回合边界。
        let mut s = fight();
        rule(&mut s, "rule.forever");
        {
            let et = EventTypeName::new("RogueDeck.Core.Combat.TurnStartedCombatEvent").unwrap();
            s.add_temporary_rule(
                TemporaryRule::new(TriggeredEffectDefinitionId::new("rule.turn1").unwrap(), et, 1, 1)
                    .with_expires_after_turn(1),
            )
            .unwrap();
            s.add_temporary_rule(
                TemporaryRule::new(TriggeredEffectDefinitionId::new("rule.round1").unwrap(), et, 1, 1)
                    .with_expires_after_round(1),
            )
            .unwrap();
        }
        assert_eq!(rule_ids(&s), ["rule.forever", "rule.round1", "rule.turn1"]);

        // 模拟 AdvanceTurn：**先**自增到 turn 2，再判定。
        s.current_round = 1;
        s.current_turn = 2;
        s.expire_temporary_rules_at_turn_boundary();

        // turn1 到期消失；forever 留下；**round1 在回合边界不判定，留下**（这一条最容易被写错）。
        assert_eq!(rule_ids(&s), ["rule.forever", "rule.round1"]);
    }

    #[test]
    fn a_round_boundary_applies_the_round_expiry_that_the_turn_boundary_ignores() {
        let mut s = fight();
        rule(&mut s, "rule.forever");
        {
            let et = EventTypeName::new("RogueDeck.Core.Combat.TurnStartedCombatEvent").unwrap();
            s.add_temporary_rule(
                TemporaryRule::new(TriggeredEffectDefinitionId::new("rule.round1").unwrap(), et, 1, 1)
                    .with_expires_after_round(1),
            )
            .unwrap();
        }
        // 模拟 AdvanceRound：round 2 / turn 1（绕回）。
        s.current_round = 2;
        s.current_turn = 1;
        s.expire_temporary_rules_at_round_boundary();

        // round 2 > 1 ⇒ 到期。forever 仍在。
        assert_eq!(rule_ids(&s), ["rule.forever"]);
    }

    #[test]
    fn a_turn_expiry_only_fires_within_its_own_round() {
        // 参考的 `MarkExpiredIfPastTurn` 用 `ExpiresAfterRound ?? currentRound` 当到期轮，
        // 所以"turn 1 到期"的规则**绕到下一轮的第 1 回合时并不消失** —— 只在同一轮内超过才消失。
        let mut s = fight();
        {
            let et = EventTypeName::new("RogueDeck.Core.Combat.TurnStartedCombatEvent").unwrap();
            s.add_temporary_rule(
                TemporaryRule::new(TriggeredEffectDefinitionId::new("rule.turn1").unwrap(), et, 1, 1)
                    .with_expires_after_turn(1),
            )
            .unwrap();
        }
        // 仍在本轮、turn 未超过 ⇒ 留下。
        s.current_round = 1;
        s.current_turn = 1;
        s.expire_temporary_rules_at_turn_boundary();
        assert_eq!(rule_ids(&s), ["rule.turn1"]);
        // 同一轮内 turn 2 > 1 ⇒ 到期。
        s.current_turn = 2;
        s.expire_temporary_rules_at_turn_boundary();
        assert!(rule_ids(&s).is_empty());
    }

    // ── 重洗（参考 `CardZoneEffects.cs:49-82` + `CardZones.cs:260-297`）──────────────────────

    #[test]
    fn reshuffling_appends_the_whole_discard_pile_in_the_rng_order_and_advances_the_step() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        let who = cid("hero");

        let mut discarded = std::vec::Vec::new();
        for i in 0..5 {
            let id = std::format!("card_{:06}", i + 1);
            discarded.push(
                s.push_card(&who, CardZone::DiscardPile,
                            CardInstance::new(ciid(&id), cdid("standard.strike"))).unwrap(),
            );
        }
        // 抽牌堆里先留一张，用来验证是**追加**而不是替换（参考 `:292` 是 `_drawPile.Add`）。
        let kept = s.push_card(&who, CardZone::DrawPile,
                               CardInstance::new(ciid("card_000099"), cdid("standard.defend")))
            .unwrap();

        let seed = s.random_seed;
        let step = s.random_step;
        let mut expected = [0u8; 5];
        crate::rng::shuffle_indexes(&mut expected, seed, step);

        assert_eq!(s.reshuffle_discard_into_draw(&who).unwrap(), 5);

        assert_eq!(s.random_step, step + 1, "洗牌必须**恰好**推进 random_step 一次");
        let z = s.card_zones(&who).unwrap();
        assert_eq!(z.count(CardZone::DiscardPile), 0, "弃牌堆必须被清空");
        assert_eq!(z.count(CardZone::DrawPile), 6, "旧抽牌堆 ++ 5 张");
        assert_eq!(z.slots(CardZone::DrawPile)[0], kept.0, "原有抽牌堆留在最前面");
        for i in 0..5 {
            assert_eq!(
                z.slots(CardZone::DrawPile)[1 + i],
                discarded[expected[i] as usize].0,
                "第 {i} 张不是 rng 置换给出的那一张"
            );
        }
    }

    #[test]
    fn reshuffling_an_empty_discard_pile_does_nothing_and_does_not_advance_the_step() {
        let mut s = deck_of(3);
        let who = cid("hero");
        let step = s.random_step;
        assert_eq!(s.reshuffle_discard_into_draw(&who).unwrap(), 0);
        // 没洗就不能推进步数 —— 否则"空洗一次"也会污染后续所有随机。
        assert_eq!(s.random_step, step);
        assert_eq!(s.card_zones(&who).unwrap().count(CardZone::DrawPile), 3);
    }

    #[test]
    fn reshuffling_refuses_before_touching_anything_when_the_draw_pile_cannot_take_it() {
        let mut s = deck_of(MAX_CARDS_PER_ZONE); // 抽牌堆塞满
        let who = cid("hero");
        s.push_card(&who, CardZone::DiscardPile,
                    CardInstance::new(ciid("card_900001"), cdid("standard.strike"))).unwrap();
        let step = s.random_step;
        let draw_before = s.card_zones(&who).unwrap().count(CardZone::DrawPile);
        assert_eq!(s.reshuffle_discard_into_draw(&who).unwrap_err(),
                   CapacityError::Full(Container::CardsInZone(CardZone::DrawPile)));
        // 两堆都没动、步数也没动。
        assert_eq!(s.card_zones(&who).unwrap().count(CardZone::DrawPile), draw_before);
        assert_eq!(s.card_zones(&who).unwrap().count(CardZone::DiscardPile), 1);
        assert_eq!(s.random_step, step);
    }

    #[test]
    fn a_pile_can_be_walked_card_by_card_through_slot_at() {
        // 回合机在回合末要逐张问"这一张留不留"，所以它必须能拿到每张卡的 slot。
        // 这条测试的存在理由是：`CardSlot` 的字段是模块私有的，没有这两个入口时
        // 逐张路径从 turn.rs **完全不可达**（W3c 的 agent 就是撞在这上面报的阻塞）。
        let s = deck_of(3);
        let who = cid("hero");
        let z = s.card_zones(&who).unwrap();

        // `slots` 给的原始 u16 与 `slot_at` 给的 CardSlot 必须逐项一致。
        let raw: std::vec::Vec<u16> = z.slots(CardZone::DrawPile).to_vec();
        for (i, &r) in raw.iter().enumerate() {
            assert_eq!(z.slot_at(CardZone::DrawPile, i), Some(CardSlot::from_index(r)));
            assert_eq!(z.slot_at(CardZone::DrawPile, i).unwrap().index(), r as usize);
        }
        // 越界是 None，不是 panic —— 裸机上没有 unwind。
        assert_eq!(z.slot_at(CardZone::DrawPile, raw.len()), None);
        assert_eq!(z.slot_at(CardZone::DrawPile, 999), None);
        // 空堆也是 None。
        assert_eq!(z.slot_at(CardZone::Hand, 0), None);
    }

    #[test]
    fn removing_a_status_instance_keeps_the_rest_in_order_and_shrinks_the_list() {
        // 参考在层数掉到 0 时**删实例**（`StatusEffects.cs:830-838`），不是留 0 层。
        // 留 0 层会让快照多一行 `s=`、让时长衰减多减一次、提前吃光容量。
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        let who = cid("hero");
        let c = s.combatant_mut(&who).unwrap();
        // **必须 4 条**：3 条时"整体左移"与"把尾巴搬过来"（swap_remove）结果相同，
        // 测不出是哪种。4 条删中间才分得开 —— 左移给 [a, c, d]，swap 给 [a, d, c]。
        for (i, id) in ["a", "b", "c", "d"].iter().enumerate() {
            c.push_status(
                StatusInstance::new(siid(&format!("st_{i}")), sdid(id), StatusPolarity::Debuff)
                    .with_stacks(i as i32 + 1),
            )
            .unwrap();
        }
        assert_eq!(c.statuses().len(), 4);

        // 删中间那条：剩下三条**保持相对顺序**，层数跟着各自的实例走。
        assert!(c.remove_status(1));
        let ids: std::vec::Vec<&str> = c.statuses().iter().map(|x| x.definition_id.as_str()).collect();
        assert_eq!(ids, ["a", "c", "d"]);
        let stacks: std::vec::Vec<i32> = c.statuses().iter().map(|x| x.stacks).collect();
        assert_eq!(stacks, [1, 3, 4], "层数不能在搬移中串行");

        // 删末尾那条也是左移（不动别人）。
        assert!(c.remove_status(2));
        let ids: std::vec::Vec<&str> = c.statuses().iter().map(|x| x.definition_id.as_str()).collect();
        assert_eq!(ids, ["a", "c"]);

        // 越界是 false，不是 panic（裸机上没有 unwind）。
        assert!(!c.remove_status(2));
        assert!(!c.remove_status(usize::MAX));
        // 删到空表也不 panic。
        assert!(c.remove_status(0));
        assert!(c.remove_status(0));
        assert!(c.statuses().is_empty());
        assert!(!c.remove_status(0), "空表再删也是 false");
    }

    // ---- 就地重置（`.wasm` 里那 184 KB 常量模板的替代品）-------------------------------------

    /// 状态的规范文本（`snapshot::write_hash_input`）—— 逐字段等价的最短判据。
    ///
    /// 用它而不是逐字段 `assert_eq!`：`CombatState` 有 18 个字段、其中 6 个是定容容器，
    /// 逐字段手写一份“等价”很难确认自己没漏；规范文本**本来就是**“什么进哈希”的定义
    /// （`snapshot.rs:144-205`），它相等即哈希相等。
    fn canonical_text(state: &CombatState) -> String {
        use crate::writer::TextWriter;
        let mut buf = vec![0u8; 1 << 20]; // 状态 184 KB，文本实测 ~3 KB
        let mut writer = TextWriter::new(&mut buf);
        crate::snapshot::write_hash_input(&mut writer, state);
        assert!(!writer.overflowed(), "规范文本缓冲不够");
        assert!(!writer.is_empty(), "规范文本不能是空的");
        writer.as_str().to_string()
    }

    /// `reset_in_place` 之后的状态与 `new(同 id, 同 seed)` **逐字段等价**。
    ///
    /// 场景要把**六个容器全部**弄脏，否则“漏清一个容器”这种错误（最典型的是漏 `cards`：
    /// `card_num=` 会带着上一局的残留，而任何只比“容器长度”的断言都看不见）不会变红。
    #[test]
    fn reset_in_place_matches_new_field_for_field() {
        let mut state = CombatState::new(CombatId::new("dirty").unwrap(), 99);

        // 战斗员 + 资源 + 状态 + 计数器 + tag（`combatants` 容器）
        let mut a = hero();
        a.set_resource(rid("standard.energy"), 2, Some(3)).unwrap();
        a.push_status(
            StatusInstance::new(siid("st_a"), sdid("paperwork"), StatusPolarity::Debuff)
                .with_stacks(3)
                .with_duration_turns(2),
        )
        .unwrap();
        a.set_counter(cnt("queue_position"), 7).unwrap();
        a.add_tag(tag("debuff")).unwrap();
        state.add_combatant(a).unwrap();
        state
            .add_combatant(Combatant::new(cid("imp"), def("imp"), team("enemy"), 9, 9))
            .unwrap();

        // 全局状态（`global_statuses` 容器）
        state
            .push_global_status(
                StatusInstance::new(siid("st_g"), sdid("weather"), StatusPolarity::Neutral)
                    .with_stacks(1),
            )
            .unwrap();

        // 牌区 + 牌池（`card_zones` / `cards` 两个容器）
        for number in 0..3i32 {
            let instance = CardInstance::new(
                ciid(&format!("card_{:06}", number + 1)),
                cdid("paper_cut"),
            );
            state.push_card(&cid("hero"), CardZone::Hand, instance).unwrap();
        }
        state
            .push_card(
                &cid("hero"),
                CardZone::DrawPile,
                CardInstance::new(ciid("card_000004"), cdid("permit_a38")),
            )
            .unwrap();

        // 临时规则（`temporary_rules` 容器）
        state
            .add_temporary_rule(
                TemporaryRule::new(
                    TriggeredEffectDefinitionId::new("rule_1").unwrap(),
                    EventTypeName::new("TurnStarted").unwrap(),
                    5,
                    3,
                )
                .with_remaining_activations(2),
            )
            .unwrap();

        // 把标量也推离初值（否则“忘了重置某个标量”测不出来）。
        state.random_step = 4;
        state.current_round = 5;
        state.current_turn = 3;
        state.result = CombatResult::Victory;
        state.turn_phase = CombatTurnPhase::TurnInProgress;
        state.active_combatant_id = Some(cid("imp"));
        state.next_status_instance_number = 11;
        state.next_card_instance_number = 12;
        state.next_effect_chain_number = 13;
        state.next_program_execution_id = 14;

        // 先确认这份“脏”状态真的脏 —— 否则下面那次相等是在比两份空状态。
        let dirty = canonical_text(&state);
        assert!(dirty.contains("card_num=12"), "发号器要被推离初值");
        assert!(dirty.contains("round=5"), "轮次要被推离初值");
        assert_eq!(state.card_count(), 4, "牌池里要真有牌");

        state.reset_in_place(CombatId::new("c1").unwrap(), 42);
        let after = canonical_text(&state);
        let fresh = canonical_text(&CombatState::new(CombatId::new("c1").unwrap(), 42));
        assert_eq!(after, fresh, "reset_in_place 之后必须与 new(同 id, 同 seed) 逐字段等价");

        // 与“脏”状态相比当然也不同（成对：上一条相等不能是“两边都没重置”）。
        assert_ne!(after, dirty);
        // 六个容器都空了。
        assert_eq!(state.combatants().len(), 0);
        assert_eq!(state.turn_order().len(), 0);
        assert_eq!(state.global_statuses().len(), 0);
        assert_eq!(state.card_count(), 0);
        assert!(state.card_zones(&cid("hero")).is_none());
        assert_eq!(state.temporary_rules().len(), 0);
    }

    /// 重置**之后**再往里塞东西，读到的必须只有新塞的 —— 尾巴上的残留不许漏出来。
    ///
    /// 这条盯的是“`clear()` 只降 `len`、不动元素”那种实现：本模块的 `Bounded` 不变式
    /// 让 `pop()` 顺手把腾出来的槽写回 `T::EMPTY`，所以不该有残留；但要真漏了，
    /// 这里第一张卡就会读到上一局的牌。
    #[test]
    fn a_reset_state_does_not_leak_what_the_previous_state_held() {
        let mut state = CombatState::new(CombatId::new("dirty").unwrap(), 3);
        state.add_combatant(hero()).unwrap();
        for number in 0..5i32 {
            state
                .push_card(
                    &cid("hero"),
                    CardZone::Hand,
                    CardInstance::new(
                        ciid(&format!("card_{:06}", number + 1)),
                        cdid("paper_cut"),
                    ),
                )
                .unwrap();
        }
        assert_eq!(state.zone_cards(&cid("hero"), CardZone::Hand).count(), 5);

        state.reset_in_place(CombatId::new("clean").unwrap(), 0);
        // 新的一局：加一个新战斗员、塞一张牌。
        state
            .add_combatant(Combatant::new(cid("other"), def("other"), team("player"), 5, 5))
            .unwrap();
        state
            .push_card(
                &cid("other"),
                CardZone::DrawPile,
                CardInstance::new(ciid("card_000001"), cdid("permit_a38")),
            )
            .unwrap();

        assert_eq!(state.combatants().len(), 1, "只该有新加的那一个战斗员");
        assert_eq!(state.combatant(&cid("hero")), None, "旧的战斗员不许留下");
        assert_eq!(state.card_count(), 1, "只该有新塞的那一张牌");
        let cards: std::vec::Vec<&str> = state
            .zone_cards(&cid("other"), CardZone::DrawPile)
            .map(|card| card.definition_id.as_str())
            .collect();
        assert_eq!(cards, ["permit_a38"], "读到旧的 `paper_cut` 就是尾巴漏了");
    }

    /// `blank()` 与 `Empty::EMPTY` 必须描述同一个“空状态”。
    ///
    /// 为什么值得一条测试：`new()` 走 `blank()`，而 `EMPTY` 仍是公开常量（`Default` 那条路
    /// 与测试基准都用它）。两边一旦漂开，`new()` 与 `*state = CombatState::EMPTY` 就不再是
    /// 同一件事 —— 而那种偏差不会报错，只会让某个字段悄悄从 1 变 0。
    #[test]
    fn blank_matches_empty() {
        assert_eq!(
            canonical_text(&CombatState::blank()),
            canonical_text(&CombatState::EMPTY)
        );
        // 成对：`blank()` 不是 `new()`（两者的发号器不同）。
        assert_ne!(
            canonical_text(&CombatState::blank()),
            canonical_text(&fight())
        );
    }

    // ---------------------------------------------------------------------------------------
    // 事件队列（批次 1）
    // ---------------------------------------------------------------------------------------
    //
    // 这一组测试的分工：**每一条都在瞄准一个"坏了也不会有人喊"的形态**。
    // 队列的默认失效模式是"少了一条、早了一条、多了一个号" —— 三种都不报错，
    // 只在几万步之后表现为一个哈希不同。所以这里成对写（满/未满、跑/不跑、发号/不发号）。

    fn hero_id() -> CombatantId {
        cid("hero")
    }

    fn a_turn_started() -> CombatEvent {
        CombatEvent::TurnStarted {
            combatant: hero_id(),
        }
    }

    #[test]
    fn a_full_queue_refuses_the_65th_entry_instead_of_dropping_it() {
        // 参考的 `Queue<T>` 无界；移植有界 ⇒ "满了"是**新增的**错误。它必须是 `Err`，
        // 而且队列深度必须**停在 64**（既不是 65，也不是 0 —— 后者等于把整队丢了）。
        let mut state = fight();
        for i in 0..MAX_PENDING_EVENTS {
            state
                .enqueue_event(a_turn_started())
                .unwrap_or_else(|e| panic!("第 {i} 条就该进得去：{e:?}"));
        }
        assert_eq!(state.pending_event_count(), MAX_PENDING_EVENTS);
        assert_eq!(
            state.enqueue_event(a_turn_started()),
            Err(CapacityError::Full(Container::PendingEvents))
        );
        assert_eq!(
            state.pending_event_count(),
            MAX_PENDING_EVENTS,
            "满了之后深度不许变（多 1 = 覆盖别人，到 0 = 整队丢了）"
        );
        // 成对：腾一格之后**进得去**，证明拒绝的是"满了"这件事，不是"入队坏了"。
        assert!(state.dequeue_event().unwrap().is_some());
        assert_eq!(state.enqueue_event(a_turn_started()), Ok(()));
        assert_eq!(state.pending_event_count(), MAX_PENDING_EVENTS);
    }

    #[test]
    fn the_fifo_wraps_around_and_still_pops_in_push_order() {
        // 环形缓冲的经典坏法：下标忘了取模 ⇒ 转第二圈时开始读垃圾。
        // 这里把一条 64 容量的队列真的转两整圈，顺序必须逐条对上。
        let mut state = fight();
        for round_base in [0i32, MAX_PENDING_EVENTS as i32] {
            for offset in 0..MAX_PENDING_EVENTS {
                state
                    .enqueue_event(CombatEvent::RoundStarted {
                        round: round_base + offset as i32,
                    })
                    .expect("没满");
            }
            for offset in 0..MAX_PENDING_EVENTS {
                let item = state.dequeue_event().expect("没空").expect("有货");
                match item.event {
                    CombatEvent::RoundStarted { round } => assert_eq!(
                        round,
                        round_base + offset as i32,
                        "第 {offset} 条的顺序错了（环形下标没取模就是这样）"
                    ),
                    other => panic!("出队拿到了别的事件：{other:?}"),
                }
            }
            assert!(!state.has_pending_queues(), "抽干一圈之后必须干净");
        }
    }

    #[test]
    fn the_effect_columns_are_checked_on_every_dequeue_not_just_in_debug() {
        // 参考的两条 `Ensure*QueueMetadataAligned`（`CombatState.cs:401-406/436-440`）是
        // **语义守门人**：三列错位 = "这条效果拿到了别人的链"，而它在哈希里只表现为一串不同的号。
        // ⇒ 这条测试亲手把一列掰歪，断言出队**响亮失败**（而不是照旧发出错位的记录）。
        let mut state = fight();
        state
            .enqueue_effect(EffectRequest::GainBlock {
                target: Some(hero_id()),
                amount: 3,
            })
            .unwrap();
        assert!(state.ensure_effect_queue_aligned().is_ok());

        // 掰歪：多推一条链（模拟"某处只推了元数据列"）。
        state
            .pending_effect_chains
            .push(ChainSlot::NONE, Container::PendingEffectChains)
            .unwrap();
        assert_eq!(
            state.dequeue_effect(),
            Err(CapacityError::QueueMetadataMisaligned {
                column: "effect",
                records: 1,
                chains: 2,
                owners: 1,
            })
        );

        // 事件列同理（它只有两列）。
        let mut events = fight();
        events.enqueue_event(a_turn_started()).unwrap();
        events
            .pending_event_chains
            .push(ChainSlot::NONE, Container::PendingEventChains)
            .unwrap();
        assert_eq!(
            events.dequeue_event(),
            Err(CapacityError::QueueMetadataMisaligned {
                column: "event",
                records: 1,
                chains: 2,
                owners: 2,
            })
        );
    }

    #[test]
    fn an_event_id_list_refuses_the_25th_id_instead_of_truncating_it() {
        // 这是第 0 步那条硬规则的**可执行版本**：集合型事件的 id 列表容量放大后行为会变
        // ⇒ 它是语义。第 25 个 id 必须**报错**，而且已经进去的 24 个必须原样还在。
        let mut list = EventIdList::new();
        for i in 0..MAX_EVENT_ID_LIST {
            let id = Ident::<INSTANCE_ID_CAP>::new(&format!("card_{i:06}")).unwrap();
            list.push(id).unwrap_or_else(|e| panic!("第 {i} 个该进得去：{e:?}"));
        }
        assert_eq!(list.len(), MAX_EVENT_ID_LIST);
        let extra = Ident::<INSTANCE_ID_CAP>::new("card_999999").unwrap();
        assert_eq!(
            list.push(extra),
            Err(CapacityError::Full(Container::EventIdList))
        );
        assert_eq!(list.len(), MAX_EVENT_ID_LIST, "满了之后长度不许动");
        assert_eq!(list.as_slice()[0].as_str(), "card_000000", "旧条目不许被覆盖");
    }

    #[test]
    fn a_root_chain_costs_one_number_and_a_triggered_chain_costs_none() {
        // `CombatState.cs:545-555`（建根链发号）与 `:492-498`（建触发链**不发号**，深度 +1）。
        // 这一对是整份"链号记账"的地基：反了就会让每个触发器偷偷把一个号用掉。
        let mut state = fight();
        let before = state.next_effect_chain_number;

        let root = state.new_root_chain_in_arena().unwrap();
        assert_eq!(state.next_effect_chain_number, before + 1);
        assert_eq!(state.chain_record(root).map(|r| r.depth), Some(0));
        assert_eq!(state.chain_record(root).map(|r| r.trigger), Some(NO_TRIGGER));

        let child = state.create_triggered_chain(root, 7).unwrap();
        assert_eq!(
            state.next_effect_chain_number,
            before + 1,
            "触发链**不发号**"
        );
        assert_eq!(state.chain_record(child).map(|r| r.depth), Some(1));
        assert_eq!(state.chain_record(child).map(|r| r.trigger), Some(7));
        assert_eq!(
            state.chain_record(child).map(|r| r.id),
            state.chain_record(root).map(|r| r.id),
            "父子同 id：链号是链的，不是节点的"
        );

        // 回收：`refs` 归零才回收（否则父子会指向同一槽）。
        state.release_chain(child);
        assert!(state.chain_record(child).is_none());
        assert!(state.chain_record(root).is_some());
        state.release_chain(root);
        assert_eq!(state.live_chain_count(), 0);
        assert!(state.chain_record(root).is_none());
    }

    #[test]
    fn the_trigger_depth_limit_is_loud() {
        // `CombatEffectChain.cs:64-72`：深度到顶**抛**，不是"跳过这个触发器"。
        let mut state = fight();
        let mut chain = state.new_root_chain_in_arena().unwrap();
        for _ in 0..MAX_TRIGGER_DEPTH {
            chain = state.create_triggered_chain(chain, 1).expect("还没到顶");
        }
        assert_eq!(
            state.chain_record(chain).map(|r| r.depth),
            Some(MAX_TRIGGER_DEPTH)
        );
        assert_eq!(
            state.create_triggered_chain(chain, 1),
            Err(CapacityError::Full(Container::Chains)),
            "第 {} 层必须报错（参考抛 `EnsureCanAppendTriggeredEffectDefinition`）",
            MAX_TRIGGER_DEPTH + 1
        );

        // 另一面：**没有父链**也必须响亮失败。填一个兜底 id 会让"链号从哪来"变成
        // 不可对账的一笔（`ChainRecord::id` 就是哈希里的 `chain_num`）。
        assert_eq!(
            state.create_triggered_chain(ChainSlot::from_index(MAX_LIVE_CHAINS - 1), 1),
            Err(CapacityError::ChainHasNoParent)
        );
        assert_eq!(
            state.create_triggered_chain(ChainSlot::NONE, 1),
            Err(CapacityError::ChainHasNoParent)
        );
    }

    #[test]
    fn the_queues_are_cleared_by_reset_and_are_not_in_the_hash() {
        // 两件事一起钉，因为它们是同一条结论的两面：
        // 1. 队列**不进哈希**（参考把三个队列划成输出，`CombatStateSnapshot.cs:94`）
        //    ⇒ 入队之后规范文本必须**逐字节相同**。
        // 2. `reset_in_place` **必须清它们**（否则上一局的残留会在下一局开打时分发出去）。
        let mut state = fight();
        // ⚠️ 批次 2 起入队**在链作用域里**做：没有环境链的 `EnqueueEffect` /
        // `EnqueueEvent` 会 `?? CreateRootEffectChain()`（`CombatState.cs:386`/`:446`），
        // 于是 `chain_num` 会动 —— 那是**队列的后果**（下面成对断言），不是"队列内容进了哈希"。
        // 所以基准文本取在"链已经建好"之后。
        let chain = state.new_root_chain_in_arena().unwrap();
        let clean = canonical_text(&state);

        state.with_chain(chain, |state| {
            state.enqueue_event(a_turn_started()).unwrap();
            state
                .enqueue_event(CombatEvent::DamageDealt {
                    target: hero_id(),
                    health_damage: 5,
                    blocked_damage: 0,
                    requested: 5,
                    source: None,
                })
                .unwrap();
            state
                .enqueue_continuation(Continuation::CloseAction { actor: hero_id() })
                .unwrap();
            state
                .enqueue_effect(EffectRequest::DealDamage {
                    target: Some(hero_id()),
                    amount: 2,
                    ignores_block: false,
                    source: None,
                })
                .unwrap();
        });

        assert_eq!(
            canonical_text(&state),
            clean,
            "队列进了哈希 ⇒ 每条改动都会移动指纹（参考没这么做）；链作用域里的入队也不发号"
        );
        assert!(state.has_pending_queues());

        // 成对：**顶层入队**多一个链号 —— 那是队列的**后果**（`CombatState.cs:446` 的
        // `?? CreateRootEffectChain()`），不是队列内容进了哈希。两者必须分开断言，
        // 否则"链号 +1"会被误当成"队列进了哈希"的证据。
        let chain_before = state.next_effect_chain_number;
        state.enqueue_event_at_root(a_turn_started()).unwrap();
        assert_eq!(state.next_effect_chain_number, chain_before + 1);

        state.reset_in_place(CombatId::new("c2").unwrap(), 7);
        assert!(!state.has_pending_queues(), "reset 必须清六个队列");
        assert_eq!(state.live_chain_count(), 0, "reset 必须清链 arena");
        assert_eq!(state.current_chain(), ChainSlot::NONE);
        // 成对：清干净之后与"刚建好的状态"逐字节相同
        // （与 `reset_in_place_matches_new_field_for_field` 同一条不变式）。
        let fresh = CombatState::new(CombatId::new("c2").unwrap(), 7);
        assert_eq!(canonical_text(&state), canonical_text(&fresh));
    }
}
