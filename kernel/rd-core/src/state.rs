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
///
/// ⚠️ §257: it was **4**, and that number was a lie about `Reptomancer`: the wiki lets it keep
/// **four Daggers** alive (`Reptomancer + 4 = 5`) on top of the two the encounter starts with.
/// At 4 the summon action failed with `Capacity(Full(Combatants))` -- loudly, which is why this
/// showed up at all -- but a loudly-refused *correct* action is still wrong. 6 matches the
/// observation's six enemy slots (`MAX_ENEMY_SLOTS`), so "the cap" and "the things the page can
/// show" are now the same number instead of two numbers that disagree.
pub const MAX_ENEMIES_IN_FIGHT: usize = 6;
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
    /// `node.destroyCombatant` asked to remove the combatant whose turn it is (§178).
    ///
    /// The turn processor addresses the active combatant **by id**, so removing it mid-turn would
    /// leave the loop holding a dangling id. Loud, and nothing is mutated.
    ActiveCombatant,
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
    /// 待决选牌的**合法选项表**（§161.3）。调用方给的缓冲区装不下整张清单就是它满。
    ChoiceOptions,
}
impl Container {
    /// 容器的数字代号（§152）。
    ///
    /// 装进 FightOutcome.step_capacity: [u8; MAX_STEPS] 的就是它：定容容器装满时
    /// 哪一个 是唯一 actionable 的信息，而内核 no_std、不能格式化，所以数字+名字表分开放。
    /// **名字只在这一个地方写**（name_of），宿主不许抄第二份。
    #[must_use]
    pub const fn code(self) -> u8 {
        match self {
            Container::TurnOrder => 1,
            Container::Combatants => 2,
            Container::CardZones => 3,
            Container::CardInstances => 4,
            Container::CardsInZone(_) => 5,
            Container::GlobalStatuses => 6,
            Container::Statuses => 7,
            Container::Resources => 8,
            Container::DefensivePools => 9,
            Container::Counters => 10,
            Container::Tags => 11,
            Container::Marks => 12,
            Container::MarkCounters => 13,
            Container::TemporaryRules => 14,
            Container::PendingEffects => 15,
            Container::PendingEffectChains => 16,
            Container::PendingEffectOwners => 17,
            Container::PendingEvents => 18,
            Container::PendingEventChains => 19,
            Container::PendingContinuations => 20,
            Container::Chains => 21,
            Container::EventIdList => 22,
            Container::ProgramFrames => 23,
            Container::ProgramNodeSlots => 24,
            Container::ProgramLoops => 25,
            Container::ChoiceOptions => 26,
        }
    }

    /// 代号 → 短名；不认识的代号给 ?。
    #[must_use]
    pub const fn name_of(code: u8) -> &'static str {
        match code {
            1 => "TurnOrder",
            2 => "Combatants",
            3 => "CardZones",
            4 => "CardInstances",
            5 => "CardsInZone",
            6 => "GlobalStatuses",
            7 => "Statuses",
            8 => "Resources",
            9 => "DefensivePools",
            10 => "Counters",
            11 => "Tags",
            12 => "Marks",
            13 => "MarkCounters",
            14 => "TemporaryRules",
            15 => "PendingEffects",
            16 => "PendingEffectChains",
            17 => "PendingEffectOwners",
            18 => "PendingEvents",
            19 => "PendingEventChains",
            20 => "PendingContinuations",
            21 => "Chains",
            22 => "EventIdList",
            23 => "ProgramFrames",
            24 => "ProgramNodeSlots",
            25 => "ProgramLoops",
            26 => "ChoiceOptions",
            _ => "?",
        }
    }
}




impl core::fmt::Display for CapacityError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            Self::IdTooLong { cap, len } => write!(f, "id of {len} bytes exceeds capacity {cap}"),
            Self::IdNotAscii => f.write_str("id is not ASCII"),
            Self::Full(c) => write!(f, "{c:?} is full"),
            Self::DuplicateKey => f.write_str("key already present"),
            Self::DuplicateCombatant => f.write_str("combatant id already present"),
            Self::ActiveCombatant => f.write_str("cannot remove the active combatant"),
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

/// 装一个 `<prefix>%06d` 的栈上缓冲要多大。
///
/// 最长情形：`status_`(7) + `i32` 的 10 位十进制 = 17 B。取 32 是"怎么都不会撞上"的余量，
/// 真正越界时 [`numbered_text`] 返回 `None` 而不是截断。
pub const INSTANCE_TEXT_CAP: usize = 32;

/// `<prefix>%06d` 的**零分配**版（`format!` 在 `no_std` 里没有）。
///
/// 逐字对应 C# 的 `$"{prefix}{number:000000}"`：负数在参考里不可能出现（生成器从 1 开始），
/// 真出现时按 **0** 写（与旧实现一致，那不是"猜"，是"不可能发生"）。
/// 返回的 `&str` 借用 `buffer`，所以调用方持有它、并立刻用完。
///
/// §161.5：从 `exec.rs` 搬到这里（`create_card_instance` 在这里用它）。`exec.rs` 的
/// `status_%06d` 与 `summoned_%06d` 也读这一份 —— 一处实现，三处读。
#[must_use]
pub fn numbered_text<'b>(
    prefix: &[u8],
    number: i32,
    buffer: &'b mut [u8; INSTANCE_TEXT_CAP],
) -> Option<&'b str> {
    // 10 位十进制够装下 `u32::MAX`（10 位），再补前导 0 到 6 位。
    let mut digits = [b'0'; 12];
    let mut len = 0usize;
    let mut value = if number < 0 { 0u32 } else { number as u32 };
    loop {
        let slot = digits.get_mut(len)?;
        *slot = b'0' + (value % 10) as u8;
        len += 1;
        value /= 10;
        if value == 0 {
            break;
        }
    }
    while len < 6 {
        let slot = digits.get_mut(len)?;
        *slot = b'0';
        len += 1;
    }
    let head = buffer.get_mut(..prefix.len())?;
    head.copy_from_slice(prefix);
    for index in 0..len {
        let slot = buffer.get_mut(prefix.len() + index)?;
        // 反着写：`digits` 是低位在前。
        *slot = digits[len - 1 - index];
    }
    core::str::from_utf8(&buffer[..prefix.len() + len]).ok()
}

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

    /// §241：删掉一个 mark counter（"这张牌的强制价格撤销了"）。
    ///
    /// 与 `set_mark_counter(key, 0)` **不是**一回事：0 是一个合法的绝对价格（"它就是 0 费"），
    /// 而"没有这个键"才是"听内容"。两者的区别正是 Havoc 打出一张被拒的牌时要恢复的东西。
    pub fn remove_mark_counter(&mut self, key: CounterId) {
        self.mark_counters.retain(|counter| counter.key != key);
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
    /// §242：这场战斗里**失去生命**的次数（`Blood for Blood` 的费用递减）。
    ///
    /// 与 `cards_played_this_turn` 同一类内核记账：它是一条**规则**的输入（"每次掉血减 1 费"），
    /// 不是某张牌的状态。伤害造成的掉血与 `Lose HP` 都算（StS 的措辞是 "each time you lose HP"，
    /// 不区分来源）。
    ///
    /// ⚠️ model-only：参考没有这个字段 ⇒ 不进 `hash_golden`（参考规范文本里没有它）。
    pub hp_losses: i32,
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
        // §242: 本场战斗失去生命的次数（model-only）。
        hp_losses: 0,
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

/// 一张牌**自己的**价格：`standard.card_cost_delta`（`StandardCombatIds.cs:93`）。
///
/// 参考的模型（`Cards/CardInstanceCostModifier.cs:13-34`）：这是一个**每张牌副本**的 mark
/// counter，加到这张牌的**每一条**资源代价上、**钳到 0**、并且**在出牌付款之后清零**
/// （`Cards/CardPlay.cs:176-183`：*"A per-copy price is a promise to ONE card and is kept once"*）。
///
/// 它为什么不能用一个状态表达：状态是**按持有者**给每张牌定价的（"你的技能牌便宜 1"），而
/// "你刚拿回来的那张牌这次免费"是一个**只属于那一张牌**的承诺，得跟着它穿过弃牌堆与手牌。
///
/// ⚠️ **与 StS 的差别（写明了的不对称）**：StS 的 "costs 0 **this turn**" 在回合结束时过期；
/// 参考引擎的模型是"被出牌消费"，所以一张没被打出的折扣牌会一直带着它。我们照参考实现 ——
/// 给回合结束加一次清除等于发明一条参考没有的规则（§159.3 的教训是"不要实现一个关于不存在的
/// 事件的分数"），而这条差别由 `the_per_copy_price_is_consumed_by_the_play` 钉住。
pub const CARD_COST_DELTA_COUNTER: &str = "standard.card_cost_delta";

/// 一张牌**自己的、不被出牌消费的**价格（§179：Snecko Oil）。
///
/// 和 [`CARD_COST_DELTA_COUNTER`] 的区别只有一条，但那一条就是全部：**它不随出牌清零**。
/// 参考的 delta 是"一次性承诺"（`CardPlay.cs:176-183`），而 wiki 的 Snecko Oil 说
/// "Randomize the costs of all cards in your hand **for the rest of combat**" —— 一张 0 费的牌
/// 第二次抽到手里也还是 0 费。用 delta 表达会让这条药水的效果在第一次出牌后消失。
///
/// 它是**绝对价**而不是增量：随机出来的就是那张牌这一场战斗的价格，`Amount` 与全局修饰器
/// （Snecko Eye 之类）都在这之上照常折叠 —— 顺序见 `play.rs` 的 `CostStage::CardInstance`。
pub const CARD_COST_OVERRIDE_COUNTER: &str = "standard.card_cost_override";

/// 一张牌的**升级版定义 id**：`<id>+`（本内容的约定，§195.7）。
///
/// 这是那个拼法的**唯一**实现：`exec::upgrade_cards_node`（按定义 id 批量升级）与
/// [`CombatState::resolve_upgrade`]（升级玩家选中的那张）都调它 —— 两处各写一遍 `push(b'+')`
/// 就是"同一个词表被两处认识"，迟早一处改成 `<id>+1` 而另一处没改。
///
/// 返回 `None` 只有一种情形：`+` 之后超出 [`ID_CAP`]（装不下就会被截断成一个**别的** id，那是撞名）。
///
/// §229：**这里不再拒绝"已经以 `+` 结尾"**。那条规则是"防 `strike+` 变成 `strike++`"，而它真正该问
/// 的是"内容里有没有 `strike++` 这一行" —— 那个问题只有拿得到内容的人能回答，所以它归
/// `exec::upgradable_definition`（以及 `rd_run::upgrade_at` 的查表）。把"能加几次"写在**内容**里，
/// `Searing Blow` 的 "Can be Upgraded any number of times" 就不需要任何新模型：
/// 行写到哪儿，就能升到哪儿。
#[must_use]
pub fn upgraded_id(definition: &str) -> Option<CardDefinitionId> {
    let bytes = definition.as_bytes();
    if bytes.len() + 1 > ID_CAP {
        return None;
    }
    let mut buffer = [0u8; ID_CAP];
    buffer[..bytes.len()].copy_from_slice(bytes);
    buffer[bytes.len()] = b'+';
    CardDefinitionId::new(core::str::from_utf8(&buffer[..bytes.len() + 1]).ok()?).ok()
}

/// 一次候选最多几张（StS 的三张；留到 8 是因为 Attack/Skill/Power 三瓶都要同一个数，
/// 而"三"写在三处的常量迟早只有一个被改）。
pub const MAX_CHOICE_OFFERED: usize = 8;

/// 一次待决的选牌：玩家（或任何战斗员）**必须**先回答它，才能继续（§161.3）。
///
/// # 为什么这是一个状态，而不是一个 UI 回调
///
/// 参考引擎的 `CardChooser` 是一个宿主委托（`CombatStateSnapshot.cs` 里连它一起排除），因为
/// 那边是单人同步程序：问一句、当场答。但本项目要的是**可存档、可回放、可训练**：
/// 「正在等玩家从手牌里选 3 张」必须是能从状态里读出来的东西，否则一局只能在线性时间里重放。
/// ⇒ 这里的选牌是 `CombatState` 的一个字段，`resolve_choice` 是唯一把它消掉的人。
///
/// # 为什么它**不**进 `hash_golden`
///
/// `hash_golden` 是参考引擎规范文本的**逐字节**复刻（`snapshot.rs`），参考没有这个字段，
/// 写进去就等于伪造参考的输出。它属于 `snapshot.rs` 那张「状态里有、指纹里没有」的清单
/// —— 与 `mark_source_combatant_id` 同一类，**`hash_full` 落地时必须覆盖它**。
/// 这也是加它**不动任何基线**（85 份语料一个字节都不变）的原因。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PendingChoice {
    /// 谁在选。选谁的手牌/弃牌堆由它决定，内核**不**假定是英雄。
    pub chooser: CombatantId,
    /// 从哪儿选。
    pub source: ChoiceSource,
    /// 最少选几张。`0` 合法，含义是「可以什么都不选」，于是**取消永远可用**。
    pub min: u8,
    /// 最多选几张。
    pub max: u8,
    /// 选完之后做什么。
    pub then: ChoiceThen,
    /// [`ChoiceSource::Offered`] 的候选：**卡定义**，不是实例（§161.5）。
    ///
    /// 其余来源必须留空；`begin_choice` 两边都校验，因为「候选」和「来源」不一致，等于问一个
    /// 玩家答不出来的问题。
    pub offered: Bounded<CardDefinitionId, MAX_CHOICE_OFFERED>,
    /// **收窄后的合法清单**（§226）：非空 ⇒ 只有这些实例能被选。
    ///
    /// 为什么它必须在状态里：StS 的 `Dual Wield` 是「选一张 **Attack 或 Power** 牌复制」，而这个
    /// 过滤要读**卡定义的 tag 表** —— 那是内容（`Content`）才有的东西，`CombatState` 里没有内容。
    /// 所以由**节点**（它拿得到内容）在提问那一刻把清单算好，状态只负责守着它：`choice_legal`
    /// 按这份清单出选项，`resolve_choice` 也只认这份清单里的牌。
    ///
    /// 空 = 不过滤（Elixir / Gambler's Brew / Liquid Memories 的老问句，逐字不变 ——
    /// 这也是加它**不动任何基线**的原因）。`begin_choice` 校验每一项**现在真的在来源牌区里**。
    pub candidates: Bounded<CardInstanceId, MAX_CHOICE_OFFERED>,
}

/// 选牌的**来源**。
///
/// ⚠️ `Offered` 是**第二个形态**：它的候选不是牌堆的一部分，而是三条**卡定义**（§161.5）。
/// 它不能落到任何一个 [`CardZone`] 上 —— 这也是 [`Self::zone`] 返回 `Option` 的原因：
/// `match` 会逼着每个读者回答「候选从哪来」，而不是把它当成一个空牌区。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u8)]
pub enum ChoiceSource {
    /// 手牌（Elixir「消耗任意张手牌」/ Gambler's Brew「弃任意张，抽同样多」）。
    #[default]
    Hand,
    /// 弃牌堆（Liquid Memories「把弃牌堆里一张拿回手牌」）。
    DiscardPile,
    /// §238：**消耗堆**（Exhume「把消耗堆里一张拿回手牌」）。
    ExhaustPile,
    /// §244：**抽牌堆**（Secret Technique / Secret Weapon「从抽牌堆里挑一张」）。
    ///
    /// 与 `Hand` / `DiscardPile` 的区别只在于"候选人看得见什么"：抽牌堆的顺序对玩家是已知的
    /// （牌堆是公开信息），所以这里**不需要**打乱候选。
    DrawPile,
    /// **三条候选**（Attack / Skill Potion「从三张随机 X 牌里选一张加进手牌」）。
    Offered,
}

impl ChoiceSource {
    /// 这个来源对应的牌区；`None` = 它的候选**不在任何一个牌区里**（[`Self::Offered`]）。
    ///
    /// `const` 且有穷尽 `match`：加一种来源时，这里编译不过，而不是掉进一个默认分支。
    #[must_use]
    pub const fn zone(self) -> Option<CardZone> {
        match self {
            Self::Hand => Some(CardZone::Hand),
            Self::DiscardPile => Some(CardZone::DiscardPile),
            Self::ExhaustPile => Some(CardZone::ExhaustPile),
            Self::DrawPile => Some(CardZone::DrawPile),
            Self::Offered => None,
        }
    }
}

/// 选完之后做什么 —— 这是「待决」的**可列举**的那一半。
///
/// 每加一种药水/一张卡就要多一个变体，这是**有意的**：动作的语义必须能被列出来，
/// 否则「合法动作可枚举」就是一句空话。反过来说，内容只是挑一个变体，不是各写一套状态机。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[repr(u8)]
pub enum ChoiceThen {
    /// 把选中的牌**消耗**掉（Elixir）。
    #[default]
    Exhaust,
    /// 把选中的牌**丢弃**，然后**抽同样多张**（Gambler's Brew）。
    DiscardThenDraw,
    /// 把选中的牌**拿进手牌**，并给它一个每副本价格（§161.4，Liquid Memories）。
    ///
    /// 价格由 `resolve_choice` 的 `cost_delta` 参数给出，因为"免费"是**负数张牌代价**，
    /// 而那个数字只有知道内容的人算得出来（`CombatState` 里没有内容）。
    ToHand,
    /// **复制**选中的牌（§226，Dual Wield / Nightmare）：原件**不动**，造 `copies` 份到 `into`。
    ///
    /// 与 [`Self::ToHand`] 的区别是"搬"与"造"：那个把那一份**搬**过去（顺带给它一个每副本价格），
    /// 这个**造**新的 —— 新副本是印刷价（StS 的副本不是打折商品，所以 `cost_delta` 对它
    /// 不适用，`resolve_choice` 上游那条判据守住）。
    ///
    /// §227：`copies` / `into` 从 `PendingChoice` 的字段搬进**变体本身**。理由是"造几份、造到哪儿"
    /// 是"复制"这个词的一部分：留在外面就要靠 `begin_choice` 校验"`then` 是 Copy 时 `copies` 非零"
    /// 这类外部不变量，而**能构造出来的非法状态迟早会被构造出来**。
    Copy {
        /// 每张选中的牌造几份（`>= 1`）。
        copies: u8,
        /// 副本落在哪个牌区（Dual Wield = 手牌，Nightmare = `SetAsidePile`）。
        into: CardZone,
    },
    /// **原地升级**选中的牌（§227，Armaments）：定义 id 变成 `<id>+`，牌**不动**。
    ///
    /// 内核只守**机械**那半（"`+` 只能加一次、id 不能超长"）；"这张牌有没有 `+` 行"是内容的
    /// 事，所以由发问的节点把候选**收窄**到有 `+` 行的牌（`upgrade_cards_node` 用的是同一条规则）。
    Upgrade,
    /// §254：**选中的那张被立刻打出**（`Wish`）。
    ///
    /// wiki 的原话是 "Wish is the only card in the game that creates, then immediately plays a
    /// card. The three cards that Wish creates **never enter your hand**"。所以这个变体的语义是
    /// "造 → 打"一步完成：`resolve_offered` 把实例造进手牌（`plan_play` 的受理前提），
    /// 同时入队一条 [`EffectRequest::PlayCard`]；排空时它被真的打出去，
    /// 于是玩家看不到"手牌里多了一张废牌"这个中间态。
    ///
    /// ⚠️ 它打出去的牌**一定**是 `unplayable` 的（`Become Almighty` / `Live Forever` /
    /// `Fame and Fortune` 都是）—— 入队的那条请求带 `ignore_unplayable = true`（§253）。
    PlayChosen,
    /// §250：**拿进手牌，并且这一份的价格就是 0**（`Discovery`）。
    ///
    /// 与 [`Self::ToHand`] 的差别只有一点，但那一点必须由**内核**保证：`ToHand` 的价格来自
    /// 调用方传的 `cost_delta`（药水/页面算的），而 `Discovery` 是一张**卡**发起的问句 ——
    /// 页面没有任何理由知道"这次要传 0"。所以"免费"写进变体本身：
    /// 落手牌 + 把 `standard.card_cost_override` 设成 0。
    ///
    /// ⚠️ 与 StS 的差别（与 [`CARD_COST_DELTA_COUNTER`] 同一条，写明了的不对称）：StS 的
    /// "costs 0 **this turn**" 在回合结束过期；我们把"免费"记在**那一份副本**上、由出牌消费。
    ToHandFree,
    /// §250：**放到抽牌堆底，并且这一份的价格就是 0**（`Forethought`）。
    ///
    /// 为什么是"底"而不是"顶"：StS 的原文是 `the bottom of your draw pile` —— 那是"这一局
    /// 别指望很快再见到它"的意思。`ToDrawPileTop`（Warcry）已经占住"顶"那个语义，两者不可互换。
    ToDrawPileBottomFree,
    /// 把选中的牌放到**抽牌堆顶**（§227，Warcry）。
    ///
    /// `Top` 不是排版选择：`ZonePlacement::Top` 的注释写着"front is the draw top"，所以
    /// "下一张就抽它"与"塞进堆底"是两条不同的语义，内容不能靠顺序碰运气。
    ToDrawPileTop,
}

impl ChoiceThen {
    /// 选中的牌最终去哪儿。
    #[must_use]
    pub const fn destination(self) -> CardZone {
        match self {
            Self::Exhaust => CardZone::ExhaustPile,
            Self::DiscardThenDraw => CardZone::DiscardPile,
            Self::ToHand => CardZone::Hand,
            // 副本落在 `into`（**原件不搬**）；这个返回值的用途是给容量判据当"新卡落在哪儿"。
            Self::Copy { into, .. } => into,
            // 升级**不动牌**（`resolve_from_pile` 的 `Upgrade` 分支在搬牌之前就分流出去了），
            // 这里填原处；它不会被当成搬迁目的地。
            Self::Upgrade => CardZone::Hand,
            Self::ToDrawPileTop => CardZone::DrawPile,
            // §250：两个 `Free` 变体各自落在自己的牌区；价格不是牌区的一部分。
            Self::ToHandFree => CardZone::Hand,
            // §254：先造进手牌（受理前提），紧接着入队"打出它"。
            Self::PlayChosen => CardZone::Hand,
            Self::ToDrawPileBottomFree => CardZone::DrawPile,
        }
    }
}

/// 一个选牌问句的**答案**。
///
/// 两种形态是因为两种来源问的是不同的问题：牌区来源问"这些实例里选哪些"，候选来源问
/// "这三张里要哪个下标"。合成一个类型就会逼出一个"另一种随便填什么"的字段。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ChoiceAnswer<'a> {
    /// 从牌区里选中的**实例**（[`ChoiceSource::Hand`] / [`ChoiceSource::DiscardPile`]）。
    Instances(&'a [CardInstanceId]),
    /// 从候选里选中的**下标**（[`ChoiceSource::Offered`]），升序、不重复。
    Offered(&'a [usize]),
}

/// 这张牌还能不能再吃一个**每副本价格**？(`set_mark_counter` 的容量预检)
///
/// 字典语义：已经有这个键就是覆盖，不需要新槽位；否则要一个空槽。
fn card_can_take_price(card: &CardInstance) -> bool {
    card.mark_counters()
        .iter()
        .any(|counter| counter.key.as_str() == CARD_COST_DELTA_COUNTER)
        || card.mark_counters().len() < MAX_MARK_COUNTERS_PER_CARD
}

/// [`CombatState::resolve_choice`] 做完了什么。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ChoiceDone {
    /// 选了几张（全部成功移动）。
    pub picked: usize,
    /// 抽了几张。只有 [`ChoiceThen::DiscardThenDraw`] 会非零，而且**可能少于 `picked`**
    /// —— 两堆都空的时候抽不满，参考那边也是这个语义（`Cards/CardZones.cs:59-60`）。
    pub drawn: usize,
}

/// 选牌被拒绝的**原因**。
///
/// 与 [`CapacityError`] 分开：那条错误说的是「容器满了」，而这里的绝大多数拒绝跟容量无关。
/// 把一个「张数不在范围内」报成 `Full`，就让人去找哪个容器溢出 —— 本模块已经吃过一次
/// 这个亏（`TurnError::Host` 的注释记着另一例）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChoiceError {
    /// 已经有一个待决的选牌了。**不做嵌套**：两个待决问句叠在一起，界面无法表达顺序。
    AlreadyPending,
    /// 没有待决的选牌。
    NotPending,
    /// 张数不在 `min..=max` 里（`min > max` 这种内容错误也走这条）。
    Count {
        /// 实际选了几张。
        picked: usize,
        /// 下限。
        min: u8,
        /// 上限。
        max: u8,
    },
    /// 一张牌不在来源牌区里。也覆盖「这张牌不是这个战斗员的」与「它已经在弃牌堆了」。
    NotInSource,
    /// 同一张牌被选了两次。
    Duplicate,
    /// 答案的形状和问句的来源不匹配（`Instances` 回答 `Offered`，或反过来）。
    WrongAnswer,
    /// §227：选中的牌**升级不了**（id 已经以 `+` 结尾，或者 `+` 之后超出容量）。
    ///
    /// 这是**内核能看见的那一半**规则；"这张牌有没有 `+` 行"由发问的节点收窄候选来保证。
    NotUpgradable,
    /// 副本数与 `then` 不自洽（§226）：[`ChoiceThen::Copy`] 的 `copies` 是 0。
    ///
    /// **调用方（= 内容）的错，不是玩家的错**：静默取 `0` 或 `1` 都会把"复制"变成一个
    /// 看不出来的别的动作（零份 = 什么都没发生却扣了牌；一份 = 少了一份）。
    CopiesNotApplicable,
    /// 给了一个 `cost_delta`，但这个问句的 `then` 根本没有价格（只有 [`ChoiceThen::ToHand`] 有）。
    ///
    /// **调用方的错，不是玩家的错**：静默忽略一个折扣等于"这张牌本来就要钱，而且玩家以为它免费"。
    DeltaNotApplicable,
    /// 底层定容容器满了。
    Capacity(CapacityError),
}

impl From<CapacityError> for ChoiceError {
    fn from(e: CapacityError) -> Self {
        ChoiceError::Capacity(e)
    }
}

impl core::fmt::Display for ChoiceError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            Self::AlreadyPending => f.write_str("another choice is already pending"),
            Self::NotPending => f.write_str("no choice is pending"),
            Self::Count { picked, min, max } => {
                write!(f, "picked {picked} cards, expected {min}..={max}")
            }
            Self::NotUpgradable => f.write_str("the picked card cannot be upgraded any further"),
            Self::CopiesNotApplicable => {
                f.write_str("copies belong to `Copy` questions only, and `Copy` needs at least one")
            }
            Self::NotInSource => f.write_str("a picked card is not in the source pile"),
            Self::Duplicate => f.write_str("the same card was picked twice"),
            Self::WrongAnswer => f.write_str("the answer does not match the question's source"),
            Self::DeltaNotApplicable => {
                f.write_str("a cost delta was given to a choice whose then has no price")
            }
            Self::Capacity(e) => write!(f, "{e}"),
        }
    }
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

    /// §250：按 `placement` 追加或插到**头**。`Top` = 索引 0 = 抽牌堆头。
    ///
    /// 单独一层是为了让"从哪儿来"只有一个判断点：`create_card_instance_at` 与
    /// `push_card_at` 都走它，所以"造一份副本放牌堆顶"不可能漏掉 `Top`。
    fn push_slot_at(
        &mut self,
        zone: CardZone,
        slot: u16,
        placement: ZonePlacement,
    ) -> StateResult<()> {
        match placement {
            ZonePlacement::Bottom => self.push_slot(zone, slot),
            ZonePlacement::Top => self.insert_slot_front(zone, slot),
        }
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

/// §220：卡牌的**生命周期事件**（`CARD.LifecyclePrograms` 的键）。
///
/// 参考的 `CardLifecycleTrigger` 只有 `TurnEndInHand` 一个成员；这两个是**我们自己的扩展**，
/// 与 §198 的 `Operation::ScalePercentPerStack` 同级 —— 被真实内容逼出来的
/// （`void` 的"抽到时失去 1 能量"、`sentinel` 的"被消耗时 +2 能量"）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CardLifecycleEvent {
    /// 从**抽牌堆进手牌**的那一刻（手牌搬回手牌不算"抽到"）。
    Drawn,
    /// 进入**消耗堆**的那一刻（打出即消耗、虚无、内容里 `moveCardToZone` 到消耗堆都算）。
    Exhausted,
}

impl CardLifecycleEvent {
    /// 镜像里 `LifecyclePrograms` 的键名。
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            CardLifecycleEvent::Drawn => "Drawn",
            CardLifecycleEvent::Exhausted => "Exhausted",
        }
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
        /// §264：**来源卡的定义**（与 `ApplyStatus::source_card` 同一个形状）。
        ///
        /// 为什么必须随请求走：卡片的伤害是**入队**的（`deal_damage_node` → 排空时才结算），
        /// 而排空那一刻的上下文里没有"正在结算哪张牌"（`resolving_card` 是节目帧的东西）。
        /// 于是 `RestrictSourceCardTag` 这类**只在折叠时问**的门会拿到 `None` —— 静默不生效。
        source_card: Option<CardDefinitionId>,
    },
    /// `GainBlockEffectRequest`（`DefensivePoolEffects.cs:3-167`）。
    GainBlock {
        /// 目标。
        target: Option<CombatantId>,
        /// 金额。
        amount: i32,
        /// §245：**这一次格挡是不是一张牌给的**（`Panic Button`："cannot gain Block **from cards**"）。
        ///
        /// 为什么必须带在请求上：请求是**排空时才落地**的，那一刻既没有"正在结算的牌"，
        /// 也没有内容 —— 事实只能在**派发时**（还在牌节目里）记下来。第一版拿
        /// `ctx.resolving_card` 判断，判据立刻红（Defend 照样给了 5 点格挡）。
        from_card: bool,
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
    /// §243：**把弃牌堆洗回抽牌堆**（`Deep Breath`）。
    ///
    /// 为什么是请求而不是节点里直接做：它必须**排在后面的抽牌之前**落地（`sequence` 是
    /// "先派发完、再按队列顺序解析"，所以入队顺序就是语义）。
    ShuffleDiscardIntoDraw {
        /// 洗谁的牌。
        owner: CombatantId,
    },
    /// §254：**把一张牌打出去**（`Wish` 的"选中的那张立刻被打出"）。
    ///
    /// 为什么在请求这一层而不是在 `resolve_choice` 里直接打：那个函数住在 `CombatState` 上，
    /// 而那个结构**没有内容** —— 出牌要 `Content` 才判得出费用与 tag。所以"打出"只能发生在
    /// **排空期**（`ctx.content` 在那儿）。与 §241 `Havoc` 的 `play_top_card_for` 同层。
    PlayCard {
        /// 谁在打（`Wish` 的施法者）。
        owner: CombatantId,
        /// 打哪一份实例。
        card: CardInstanceId,
        /// 给这张牌指定的出牌目标（`None` = 由选择器自己解）。
        target: Option<CombatantId>,
        /// §253：**越过 `unplayable`** —— `Wish` 的三个选项全是 unplayable，而 wiki 说
        /// Wish 就是**会**打出它们。
        ignore_unplayable: bool,
    },
    /// §241：**强制打出抽牌堆顶那张，然后把它消耗掉**（`Havoc`）。
    ///
    /// 为什么是一条请求而不是若干节点：出牌本身是 `play.rs` 的事（受理校验五条 + 费用 + 节目），
    /// 而"从抽牌堆顶打一张"只是**选哪张**与**打完落哪儿**的差别 —— 中间那条路必须走同一个
    /// `play_card`，否则"打出去的牌"会有两套语义（触发器的 `CardPlayed`、`cards_played_this_turn`、
    /// 每副本价格的消费……全都要写第二遍）。
    PlayTopCardOfDrawPile {
        /// 谁在打。
        owner: CombatantId,
    },
    /// §240：**造一张随机牌**（`Infernal Blade`："Add a random Attack into your hand."）。
    ///
    /// 与 [`Self::CreateCardInstance`] 的唯一区别是"定义不是内容写死的，而是按 tag 从卡表里抽"。
    /// 抽签用 `random_step`，与其它随机（洗牌、随机目标）同一条账。
    CreateRandomCard {
        /// 归属战斗员。
        owner: CombatantId,
        /// 只从这个 tag 的牌里抽（`attack`）。
        tag: crate::state::TagId,
        /// 张数。
        count: i32,
        /// 落到哪个区。
        to_zone: CardZone,
        /// 造出来的这张**本回合费用为 0**（每副本价格 `-印刷费用`）。`false` = 不动费用。
        cost_zero: bool,
    },
    CreateCardInstance {
        /// 归属战斗员。
        owner: CombatantId,
        /// 卡定义。
        definition: CardDefinitionId,
        /// 张数。
        count: i32,
        /// 落到哪个区。
        to_zone: CardZone,
        /// §255：造出来时给它写一个**每副本计数器**（`Conjure Blade` 的 "X 等于我花的能量"）。
        ///
        /// 为什么必须在**造**的那一步写：`Expunger` 的 X 存在它自己的 mark counter 上，
        /// 而"造出来但 X 是 0"与 wiki 说的"能造出打 0 次的 Expunger"**完全不可区分** ——
        /// 分成两步就会出现一个无法观测、也无法证伪的中间态。
        mark: Option<(CounterId, i32)>,
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
        /// **实际掉的血**（`§195.1`：`eventAmount` 读的就是这个数）。
        ///
        /// 不是请求额、也不是被格挡吸收的那部分：wiki 把 Mode Shift 写成 "after losing X HP"，
        /// 而一次被完全挡住的攻击**一点血都没掉**。`DamageDealt` 三个数都有，这条只要一个。
        health_damage: i32,
        /// §208: 这次伤害是不是**攻击伤害**（`damage_kind == Direct`）。
        ///
        /// 为什么要有这一格：wiki 里"受到攻击时"与"受到伤害时"是两件事 —— Flying（Byrd）
        /// "loses 1 Flying when hit by an **attack**"、Thorns 也只在被打时装上。此前
        /// `event.bool` 只认**卡牌标签**（`card.hasTag.attack`，那是 `CardPlayed` 的事实），
        /// 受击侧一个事实都没有，于是这类状态只能"受任何伤害都触发"，数值就错了。
        is_attack: bool,
    },
    /// §236：**失去生命**（不是伤害）。`Lose N HP` 的载体。
    ///
    /// 与 `DamageTaken` 分开是**语义**要求，不是洁癖：`Lose HP` 不吃格挡、不吃力量/易伤，也**不**
    /// 触发"被打"的钩子（Thorns / Flame Barrier / Curl Up / Flying）。而 `Rupture`
    /// （"每当你因为一张牌失去生命"）要响的正是它。
    HpLost {
        /// 失去生命的那一方。
        target: CombatantId,
        /// 真的失去了几点（可能因为血量不够而少于请求额）。
        amount: i32,
        /// **是不是一张牌付的代价**（`ctx.resolving_card.is_some()`）。
        ///
        /// StS 的 Rupture 只认"因为一张牌失去生命"：Hemokinesis 算，Brutality 每回合扣的那 1 点
        /// **不算**。没有这一格就只能二选一，而两种选法都会错一张牌。
        from_card: bool,
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
    /// §237：**有人获得了格挡**。Bearer = 获得格挡的那一方。
    ///
    /// `amount` 是**真的加了**多少（修饰后），不是请求额 —— `Juggernaut` 不看这个数，但把它带上
    /// 才对得起"事实"二字：将来有状态问"一次加了多少"时不用再改一次事件形状。
    BlockGained {
        /// 获得格挡的一方。
        combatant: CombatantId,
        /// 实际增量（被 `block_stage` 修饰之后）。
        amount: i32,
    },
    /// §237：**有人抽到了一张牌**（每张一次，不是"抽了几张"一次）。
    ///
    /// StS 的 `Evolve` / `Fire Breathing` 都是"每当你**抽到**一张 Status/Curse" ⇒ 计数单位是**张**，
    /// 所以这个事件必须一张一条。带 `card` 是为了让触发器能问"这张牌有 status tag 吗"
    /// （`event.bool: card.hasTag.status`）。
    CardsDrawn {
        /// 抽牌的人。
        combatant: CombatantId,
        /// 抽到的那张牌。
        card: crate::state::CardInstanceId,
    },
    /// §237：**一张牌被消耗了**（进了消耗堆）。`Dark Embrace` 就长在这上面。
    ///
    /// 三条入堆路径（§225 的审计：打出即消耗 / 虚无 / 内容 `moveCardToZone`）都在宿主侧汇到
    /// `Host::card_exhausted`，事件就发在那一处 —— 与 `LifecyclePrograms[Exhausted]` 同一个落点。
    CardExhausted {
        /// 牌的主人。
        combatant: CombatantId,
        /// 被消耗的那张牌。
        card: crate::state::CardInstanceId,
    },
    /// §294：**有人把弃牌堆洗回了抽牌堆**（`the_abacus` / `sundial`）。
    ///
    /// 参考的 25 个触发器里没有这一个（它把洗牌折进 `CardMovedToZone`）。这是**本内核自己的
    /// 事件名**，与 §237 的 `CardsDrawn` / `CardExhausted` 同级：被真实内容逼出来的扩展。
    ///
    /// Bearer 是**洗牌的那个人**（弃牌堆的主人）。发在
    /// [`CombatState::reshuffle_discard_into_draw`] 里 —— 三条洗牌的路都经过它。
    DeckShuffled {
        /// 洗牌的人。
        combatant: CombatantId,
    },
    /// §295：**有人把另一方的格挡打穿了**（`hand_drill`）。
    ///
    /// 参考的 25 个触发器里没有它；这是**本内核自己的事件名**（与 §237 的 `CardsDrawn`、
    /// §294 的 `DeckShuffled` 同级：被真实内容逼出来的扩展）。
    ///
    /// * `combatant` = **打破格挡的人**（Bearer ⇒ 遗物/状态的"你的"指它）；
    /// * `target` = **格挡被打穿的那一方**（`sel.eventTarget` ⇒ "apply 2 Vulnerable" 落在它身上）。
    ///
    /// 与 [`Self::DamageDealt`] 同一形状（Bearer = 出手方、EventTarget = 承受方），所以不新造方向。
    BlockBroken {
        /// 出手方（打破格挡的人）。
        combatant: CombatantId,
        /// 格挡被打穿的那一方。
        target: CombatantId,
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
        /// §264：**落下的那条状态是哪个定义**（`champion_belt`："施加易伤时也给 1 层虚弱"）。
        ///
        /// 与下面两个 bool 事实同一套理由（"事件那一刻才知道的东西随事件走"），但**不能**压成
        /// 位：状态 id 是开放词汇，一位装不下。所以这是第一个"事件带字符串"的槽 ——
        /// 表达式侧由 `event.statusIs` 读它。
        definition: StatusDefinitionId,
        /// §249：落下的这条是 **debuff** 吗（`Sadistic Nature` 只认 debuff）。
        ///
        /// 极性在**入队那一刻**才知道（事件本身不带定义），所以事实必须随事件一起走 ——
        /// 与 §245 的 `GainBlock.from_card` 同一条理由。
        debuff: bool,
        /// §249：承受者**不是**施法者自己（`Sadistic Nature` 说的是 "to an **enemy**"）。
        applied_to_other: bool,
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
        /// §181: 这个节目在镜像里的根（`term` 号）。**只有"再打一遍"的路径读它** ——
        /// Duplication Potion 要在第一遍**跑完之后**把同一个节目再跑一遍，而那时
        /// `plan` 已经不在了，帧上只剩这些数据。
        program: u16,
        /// 出牌时瞄的目标（`PlayRequest.target`）。第二遍必须瞄同一个，
        /// 否则"打两次"会变成"打两个不同的目标"。
        target: Option<CombatantId>,
        /// X 费的 `X`（第一遍付了多少遍，第二遍就一样多）。
        x_cost: i32,
        /// 步数预算（第二遍用同一个，否则同一个节目会有两种预算）。
        max_steps: u32,
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
    /// §225：正在结算的那张牌（`play.rs` 出牌时填）—— 续延重建上下文时要拿得回来。
    pub resolving_card: Option<CardSlot>,
    /// §225：`event_flags` 的帧内副本。
    ///
    /// 为什么它必须上帧：`forEachCardInZone` 每趟把**这一趟那张卡**的 tag 位填进 flags
    /// （"消耗所有非攻击牌"要靠它），而续延会把上下文**从帧重建** —— flags 只在 `ExprContext`
    /// 里、不上帧的话，退栈与续延两条路上都会读到最后一张/外层那张卡的 tag。
    pub event_flags: u16,
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
        resolving_card: None,
        event_flags: 0,
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
    /// §225：进循环前的 `event_flags`。
    ///
    /// 循环体里每趟都把**这一趟那张卡**的 tag 位填进 `ctx.event_flags`（"消耗所有非攻击牌"要靠它），
    /// 所以出循环时必须把它还原 —— 否则循环之后的节点会读到最后一张卡的 tag。
    pub saved_flags: u16,
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
        saved_flags: 0,
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
    /// §242：这场战斗来自哪个**遭遇**（`ENCT` 行号）。
    ///
    /// 为什么需要它：`spot_weakness` 要问"敌人这回合是不是打算攻击"，而那件事是
    /// `intent::select_action(content, encounter, slot, actor, round)` 的**纯函数**结果 ——
    /// 页面显示意图用的就是它。没有 `encounter` 就定位不到敌人槽位。
    ///
    /// ⚠️ **model-only**：参考没有这个字段，`hash_golden` 是参考规范文本的逐字节复刻
    /// （`snapshot.rs`），所以加它**不移动任何基线**。`u32::MAX` = "没有遭遇"（纯内核测试的默认值）
    /// ⇒ 意图查询一律解不出，`intent.*` 事实为假 —— 响亮而安全的那一侧。
    pub encounter: u32,
    pub current_turn: i32,
    pub turn_phase: CombatTurnPhase,
    pub active_combatant_id: Option<CombatantId>,
    /// §200: **哪一格被腾空了** —— 行动者在自己的回合里自毁时记下它的下标。
    ///
    /// 记的是**移除之后**数组里的位置：`turn_order` 是 shift-down 的，所以"被移除者原来那一格"
    /// 现在正好坐着它的继任者。`None` = 没有腾空。
    ///
    /// 为什么不是"直接把 `active_combatant_id` 设成继任者"：那一刻行动者的回合**还没收尾**，
    /// 收尾时回合机还会往前推一格 —— 继任者就永远轮不到了（一次性跳两格，静默）。
    /// 为什么不是"`active = None`，让 `ensure_active_combatant` 认领第一个活人"：那会把回合序
    /// **从头开始**，是另一种静默漂移。所以位置信息必须显式带着走，见
    /// [`Self::vacate_active_seat`] 与 `turn::advance_to_next_combatant`。
    ///
    /// 不进哈希、不进快照：参考没有这个字段（与 `end_turn_requested` 同一类**瞬时**状态）。
    pub vacated_seat: Option<u8>,
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
    /// §201: 逃走的敌人**带走**的金币（Looter 的 `Escape`）。
    ///
    /// 内核里没有金币 —— 金币是运行层的。这一格是唯一的跨层约定：内容用
    /// `node.carryAwayStolenGold` 把某个战斗员 `stolen_gold` 计数器的当前值搬进来，运行层在
    /// `fight_end` 只看这一个数（活着的/被打死的敌人身上的钱**不算**丢失：wiki
    /// `Stolen gold is returned if this enemy is killed`）。
    ///
    /// 不进哈希、不进快照（参考没有这个字段，写进 `hash_golden` 会移动全部 85 个语料基线）。
    /// 它是**一场战斗内部**的账，而回放重放的是整场战斗，所以不需要进 `RDR1` 的每一行 ——
    /// 只需要在 `fight_end` 那一行里带上（`run.rs` 把它写进了记录）。
    pub gold_carried_away: i32,
    /// §250：**战斗里赚到的金币**（`Hand of Greed` 的 "If Fatal, gain 20 Gold"）。
    ///
    /// 与 [`Self::gold_carried_away`] 是**两本独立的账**，方向相反：那一本是"被偷走、要减"，
    /// 这一本是"赚到手、要加"。合成一个 `gold_delta` 会让"偷 20 又赚 20"变成 0 —— 那在
    /// 页面显示上看起来完全正常，而玩家的钱少了 20。
    ///
    /// 由内容节点 `node.gainGold` 累加，运行层在 `fight_end` 读一次（`rd-wasm` 的桥）。
    /// ⚠️ **不进 `hash_golden`**：参考实现里没有这个字段，而那个指纹是逐字节复刻的。
    pub gold_gained: i32,
    /// The run's Ascension level, 0–20 (§187). **Not** in the snapshot text: the reference has no
    /// such field, so writing it into `hash_golden` would move all 85 corpus cases. It is a
    /// fight-level constant (set once at build, never mutated mid-fight), and `hash_full` must
    /// cover it when that lands.
    ///
    /// 它在这里而不是在 `FightPlan` 里：读它的是 `intent::select_action` 与
    /// `intent::execute_action`，两者都已经拿到 `&CombatState`；放进 plan 会让 49 处
    /// `FightPlan { .. }` 字面量全部要改一个字段。
    pub ascension: u8,
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
    /// 待决的选牌（§161.3）。`None` = 没有。
    ///
    /// ⚠️ **不进 `hash_golden`**：参考引擎没有这个字段（它把选牌做成一个宿主委托
    /// `CardChooser`），写进指纹就等于伪造参考的输出。它与 `mark_source_combatant_id`、
    /// `CardPlayTurnStats` 同属 `snapshot.rs` 那张「状态里有、指纹里没有」的清单，
    /// `hash_full` 落地时必须把它算进去。
    choice: Option<PendingChoice>,
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
        // §242：空槽没有遭遇。
        encounter: u32::MAX,
        current_turn: 0,
        turn_phase: CombatTurnPhase::WaitingToStartTurn,
        active_combatant_id: None,
        vacated_seat: None,
        gold_carried_away: 0,
        gold_gained: 0,
        end_turn_requested: false,
        forced_turn_ends: 0,
        ascension: 0,
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
        choice: None,
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
            // §242：纯内核测试没有遭遇 ⇒ 意图查询一律解不出（见字段文档）。
            encounter: u32::MAX, 
            current_turn: 0,
            turn_phase: CombatTurnPhase::WaitingToStartTurn,
            active_combatant_id: None,
            vacated_seat: None,
            gold_carried_away: 0,
            gold_gained: 0,
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
            ascension: 0,
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
            choice: None,
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
        // §216（review P1-C）：这三个字段是后加的，`reset_scalars` 一度**没有**它们 ——
        // `new()` / `Empty::EMPTY` 给了默认值，而"先打过一场（有人逃跑、掉了钱、A20）再复用"
        // 的状态会带着上一场的 `gold_carried_away` 进新战斗，`apply_fight_outcome` 会按它
        // **重复扣**一次金币（`run.rs:3491` 是 `adjust_gold(-carried)`）。
        self.vacated_seat = None;
        self.gold_carried_away = 0;
        self.ascension = 0;
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
        // §199: 这里是 `enqueue_event_at_root` 的同一条陷阱，只是藏在**效果**队列里：
        // `new_root_chain_in_arena` 建出来的那一次引用**归调用方**（refs = 1），队列条目自己又
        // `acquire` 一次（出队时还）。所以"建链"那一次也必须在入队成功之后还掉 —— 否则
        // **每次顶层入队都漏一格链**，而表现是"打到一百多次出牌之后，每一次出牌都变成
        // `StepThrew(Capacity:Chains)`"。soak 在一场 44 回合的战斗里撞到它（§199）。
        let (chain, created) = match self.current_chain {
            ChainSlot::NONE => (self.new_root_chain_in_arena()?, true),
            chain => (chain, false),
        };
        // ⚠️ **队列条目持一次链引用**。参考靠 GC（条目里的链对象有人指着就活着）；
        // 我们靠 `ChainRecord::refs`。漏了这一句的后果不是"多一条链"，而是**链被提前回收**：
        // 帧的引用一放（`reap_frames`）条目手里的链就没了，下一次 `acquire` 报
        // `Full(Chains)` —— 实测在 `e2e_16` 上撞到过，而且它伪装成"容量不够"。
        //
        // 成功与每一条回滚路径都只走一次下面的 `release`（`created` 为真时），所以"建链那一次"
        // 三条出口一条都不漏。
        let outcome = self.enqueue_effect_rows(request, owner, chain);
        if created {
            self.chains.release(chain);
        }
        outcome
    }

    /// [`Self::enqueue_effect_with_owner`] 的三列同推（链已定），失败时自己回滚。
    fn enqueue_effect_rows(
        &mut self,
        request: EffectRequest,
        owner: Option<ProgramExecutionSlot>,
        chain: ChainSlot,
    ) -> StateResult<()> {
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
        // 建链那一次引用**归调用方**（`new_root_chain_in_arena` 里 `refs: 1`）。队列条目自己
        // 在 `enqueue_event_with_chain` 里又 `acquire` 了一次，所以这里必须把"建链"那一次还掉 ——
        // 否则**每条根事件漏一格链**，而表现是"打到十几回合突然 `Full(Chains)`"
        // （§152 的 soak 在 3 × Sentry 的第 12 回合上撞到；`a_turn_boundary_leaves_no_chain_referenced`
        // 把它钉成 +1/回合）。参考那边靠 GC，条目出队后对象自然没人指了；我们的引用计数必须手工对齐。
        let chain = self.new_root_chain_in_arena()?;
        if let Err(e) = self.enqueue_event_with_chain(event, chain) {
            // 入队失败时队列没拿到引用 ⇒ 建链那一次也要还，不然失败会漏。
            self.chains.release(chain);
            return Err(e);
        }
        self.chains.release(chain);
        Ok(())
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

    /// The Ascension level this fight runs at (§187). `0` = the base game.
    #[must_use]
    pub const fn ascension(&self) -> u8 {
        self.ascension
    }

    /// Sets the Ascension level (called once, right after the fight is built).
    ///
    /// ⚠️ 它不是"战斗中途可以改的数"：没有任何规则会在 fight 里改它，而 `A17/18/19` 依赖
    /// "整场一致"。做成 `pub` 字段是为了让 `build` 之后能写；不提供"中途修改"的入口。
    pub fn set_ascension(&mut self, level: u8) {
        self.ascension = level;
    }

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

    /// **Removes** a combatant from the fight (`node.destroyCombatant`, `port-plan.md` §178).
    ///
    /// Three lists hold a combatant and they must move together or `card_zones` stops lining up with
    /// `combatants`: the roster, the turn order, and that combatant's piles.
    ///
    /// ⚠️ Distinct from *dying*: a dead combatant **stays** in the roster and in the turn order (the
    /// turn advance skips it, `CombatState.cs:139-168`), and its statuses stay collectable -- that is
    /// how `Downed` triggers work. **Removal** is the stronger act: the bearer is gone, so no trigger
    /// can be collected from it ever again. That distinction is the whole point of this method.
    ///
    /// §200: removing the combatant **whose turn it is** is legal now (Reptomancer's dagger
    /// explodes on its own turn). It used to be refused, which is why that Explode could only
    /// damage the hero and never take the dagger with it.
    ///
    /// The seat is **not** handed over here: the removed actor's turn still has to be closed, and
    /// closing it advances the rotation by one. So the position is parked in
    /// [`Self::vacated_seat`] and `turn::advance_to_next_combatant` hands it to the successor --
    /// the combatant that now sits in that grid cell. Anything else would either skip the
    /// successor (one advance too many) or restart the order from the top.
    pub fn remove_combatant(&mut self, id: &CombatantId) -> StateResult<Combatant> {
        let removing_active = self.active_combatant_id == Some(*id);
        let mut index = None;
        for i in 0..self.combatants.len() {
            if self.combatants.get(i).map(|c| c.id) == Some(*id) {
                index = Some(i);
                break;
            }
        }
        let Some(index) = index else {
            return Err(CapacityError::MissingCombatant);
        };
        let combatant = *self.combatants.get(index).ok_or(CapacityError::MissingCombatant)?;
        // Turn order: shift down so the *relative* order of everyone else is untouched (the order is
        // semantics -- `turn_order` decides who acts next).
        let len = self.turn_order.len();
        let mut turn_index = None;
        for i in 0..len {
            if self.turn_order.get(i) == Some(id) {
                turn_index = Some(i);
                break;
            }
        }
        if let Some(from) = turn_index {
            if removing_active {
                // §200: the seat is vacant from now on; `from` is the grid cell the **successor**
                // sits in once the shift-down below has run (or `len - 1`, i.e. past the end, when
                // the actor was last -- the successor then wraps to index 0).
                self.active_combatant_id = None;
                self.vacated_seat = Some(u8::try_from(from).unwrap_or(0));
                // "Another turn in a row" has no owner left: nobody is going to take it.
                self.extra_turn_for = None;
            }
            for j in from..len - 1 {
                if let Some(moved) = self.turn_order.get(j + 1).copied() {
                    if let Some(slot) = self.turn_order.get_mut(j) {
                        *slot = moved;
                    }
                }
            }
            self.turn_order.pop();
        }
        // Roster: same shift-down.
        let len = self.combatants.len();
        for j in index..len - 1 {
            if let Some(moved) = self.combatants.get(j + 1).copied() {
                if let Some(slot) = self.combatants.get_mut(j) {
                    *slot = moved;
                }
            }
        }
        self.combatants.pop();
        // Piles: `detach_card_zones` already knows how to shift that list.
        self.detach_card_zones(id);
        // Obstacles/statuses keyed by combatant are dropped with the combatant itself: they live
        // inside `Combatant`, so nothing else to clean.
        Ok(combatant)
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
    /// §281：**一次**战斗随机抽取，返回 `min..=max`（含两端）。
    ///
    /// 这是战斗随机流的**唯一入口**：`random_step` 推进一次，`random_seed` **不动** ——
    /// 与洗牌同一条约定（`(seed, step)` 派生，见 `crate::rng`）。之前的 `Snecko Oil` 在
    /// `rd-wasm` 里手抄了这条规则，而且**同时改 seed**，于是两条路会分家。
    ///
    /// `max <= min` ⇒ 直接返回 `min` 且**不推进** step（没有掷骰就没有消耗）：
    /// 内容写 `randomInt(3,3)` 是"常数"而不是"一次随机"，让它消耗随机流会让同一个种子
    /// 因为一句无害的内容改写而整局偏移。
    ///
    /// ⚠️ 取模有**偏置**（`value % span`）：`span` 不是 2 的幂时低值略多。参考实现的
    /// `Random.Next(min, max)` 也带同样的偏置形态，而"除以 `u32::MAX` 再缩放"会引入浮点。
    /// 这条偏差**写在测试里**（只钉"每一档都到过"与"同种子同序列"，不钉分布均匀性）。
    pub fn draw_in_range(&mut self, min: i32, max: i32) -> i32 {
        if max <= min {
            return min;
        }
        let value = crate::rng::draw_u32(self.random_seed, self.random_step);
        self.random_step = self.random_step.saturating_add(1);
        // i64 算跨度：`max - min + 1` 在 `min = i32::MIN` 时会溢出。
        let span = (i64::from(max) - i64::from(min) + 1) as u64;
        let offset = (u64::from(value) % span) as i64;
        let answer = i64::from(min) + offset;
        i32::try_from(answer).unwrap_or(max)
    }

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
        // §294：洗完了才通知（空弃牌堆**不算**洗过牌 —— `sundial` 的"每 3 次"不能数空的）。
        // ⚠️ 入队而不是立刻派发：这里没有 `Host`；事件由回合机的事件循环解析，
        // 与 `CardsDrawn` / `CardExhausted` 同一条路。
        self.enqueue_event(CombatEvent::DeckShuffled {
            combatant: *owner,
        })?;
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
        self.push_card_at(owner, zone, card, ZonePlacement::Bottom)
    }

    /// §250：[`Self::push_card`] + 落在**哪一头**（`Top` = 索引 0 = 抽牌堆头）。
    pub fn push_card_at(
        &mut self,
        owner: &CombatantId,
        zone: CardZone,
        card: CardInstance,
        placement: ZonePlacement,
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
        zones.push_slot_at(zone, slot, placement)?;
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

    // ── 待决的选牌（§161.3）────────────────────────────────────────────────────────────────────
    //
    // REVIEW §四.2 的要求原话是「战斗侧补一个边界明确的待决操作即可，例如选牌来源、最少/最多
    // 张数、选完后的操作。同一机制应能服务卡牌、药水和事件」。下面四个函数就是那句话的全部：
    // `begin_choice` 提出问题、`choice_legal` 把合法选项**列出来**、`resolve_choice` 收答案并
    // 执行、`pending_choice` 让宿主知道现在该问什么。
    //
    // 三条纪律：
    //
    // 1. **拒绝不改任何东西。** 这是 §161.2(a) 在战斗层的同一条话：`resolve_choice` 先做完
    //    全部校验（张数、来源、重复、两个目的牌区的容量），再动第一张牌。半途而废比拒绝更糟
    //    —— 拒绝是可见的，半途是「两张被消耗、一张还在」。
    // 2. **选牌不嵌套。** 两个待决问句叠在一起，界面无法表达先后，回放也无法表达。
    //    `begin_choice` 见到已经有一个就拒绝（不是排队）。
    // 3. **`min == 0` 时取消永远可用。** 这不是方便，是语义：Elixir 与 Gambler's Brew 的
    //    原文都是「任意张」，选 0 张就是玩家的合法答案。

    /// 当前待决的选牌（`None` = 没有）。
    #[must_use]
    pub const fn pending_choice(&self) -> Option<PendingChoice> {
        self.choice
    }

    /// 提出一个待决的选牌。
    ///
    /// 三道前置校验，全部**响亮**：
    ///
    /// * 已经有一个待决的 ⇒ [`ChoiceError::AlreadyPending`]（不排队）；
    /// * `min > max` ⇒ [`ChoiceError::Count`]：这是内容错误，不是玩家输入错误；
    /// * `min` 超过来源牌区的实际张数 ⇒ [`ChoiceError::Count`]：那样的问句**永远无法回答**，
    ///   而一个答不出来的问句会把这一局钉死。宁可在这里红。
    pub fn begin_choice(&mut self, choice: PendingChoice) -> Result<(), ChoiceError> {
        if self.choice.is_some() {
            return Err(ChoiceError::AlreadyPending);
        }
        // 候选来源和牌区来源的"有多少可选"完全不是一件事：前者数**定义**，后者数牌区里的牌。
        // 两边都校验，因为一个"候选和来源对不上"的问句，玩家永远回答不了。
        let available = match choice.source.zone() {
            Some(zone) => {
                if !choice.offered.is_empty() {
                    return Err(ChoiceError::WrongAnswer);
                }
                self.card_zones(&choice.chooser)
                    .ok_or(ChoiceError::NotInSource)?
                    .count(zone)
            }
            None => choice.offered.len(),
        };
        if choice.min > choice.max || choice.min as usize > available {
            return Err(ChoiceError::Count {
                picked: available,
                min: choice.min,
                max: choice.max,
            });
        }
        // §227：`copies` 已经在变体里了，所以只剩"0 份"这一种非法值 —— 它是一次**成功**的空
        // 操作，那是最难发现的一种错。
        if matches!(choice.then, ChoiceThen::Copy { copies: 0, .. }) {
            return Err(ChoiceError::CopiesNotApplicable);
        }
        // §226：收窄清单只能挂在**牌区来源**上，而且每一项**现在**都得在来源牌区里 ——
        // 否则玩家会看到一个点了没反应的选项。
        if !choice.candidates.is_empty() {
            let Some(zone) = choice.source.zone() else {
                return Err(ChoiceError::WrongAnswer);
            };
            for id in choice.candidates.as_slice() {
                match self.find_card(&choice.chooser, id) {
                    Some((where_it_is, _)) if where_it_is == zone => {}
                    _ => return Err(ChoiceError::NotInSource),
                }
            }
            // 清单比下限还短 ⇒ 这个问句永远答不出来（与上面那条 `available` 判据同一条理由，
            // 只是 `available` 数的是**整个牌区**，而玩家只能从清单里挑）。
            if choice.min as usize > choice.candidates.len() {
                return Err(ChoiceError::Count {
                    picked: choice.candidates.len(),
                    min: choice.min,
                    max: choice.max,
                });
            }
        }
        self.choice = Some(choice);
        Ok(())
    }

    /// 合法的卡，按**来源牌区的顺序**写进 `out`，返回个数。
    ///
    /// 「可枚举」在这里是字面意思：宿主/训练器不需要知道 Elixir 和 Gambler's Brew 的区别，
    /// 它问一次就拿到完整的候选清单。`out` 装不下整份清单 ⇒ [`Container::ChoiceOptions`]，
    /// **不截断**（截断掉的选项等于一个不存在的规则）。
    pub fn choice_legal(&self, out: &mut [CardInstanceId]) -> Result<usize, ChoiceError> {
        let choice = self.choice.ok_or(ChoiceError::NotPending)?;
        // 候选来源没有实例可列：它的选项是**下标 + 定义**，用 [`Self::choice_offered`] 读，
        // 这里**响亮拒绝**而不是返回 0 个（"零个选项"会被读成一个合法的空清单）。
        let Some(zone) = choice.source.zone() else {
            return Err(ChoiceError::WrongAnswer);
        };
        // §226：收窄清单优先 —— 它**就是**"哪些选项合法"的答案，顺序也照它（节点给的顺序，
        // 不是牌区顺序）。这一步同时是 `resolve_choice` 的镜像：两边认同一份清单，才不会出现
        // "页面能点、内核说不在来源里"。
        if !choice.candidates.is_empty() {
            let mut narrowed = 0usize;
            for id in choice.candidates.as_slice() {
                // 清单是提问那一刻的快照。问句挂着的时候牌区**不可能**变（`begin_choice` 挡掉
                // 了嵌套），所以"找不到"只可能是坏状态 —— 但跳过一项也比 panic 好，而且
                // `resolve_choice` 会在同一种情形下响亮拒绝。
                let Some((where_it_is, _)) = self.find_card(&choice.chooser, id) else {
                    continue;
                };
                if where_it_is != zone {
                    continue;
                }
                if narrowed == out.len() {
                    return Err(ChoiceError::Capacity(CapacityError::Full(
                        Container::ChoiceOptions,
                    )));
                }
                out[narrowed] = *id;
                narrowed += 1;
            }
            return Ok(narrowed);
        }
        let zones = self
            .card_zones(&choice.chooser)
            .ok_or(ChoiceError::NotInSource)?;
        let mut count = 0usize;
        for index in 0..zones.count(zone) {
            // 槽位表与卡池必须一致；不一致的槽位跳过（`card()` 的 `Option` 兜住，不 panic）。
            let Some(slot) = zones.slot_at(zone, index) else {
                continue;
            };
            let Some(card) = self.card(slot) else {
                continue;
            };
            if count == out.len() {
                return Err(ChoiceError::Capacity(CapacityError::Full(
                    Container::ChoiceOptions,
                )));
            }
            out[count] = card.id;
            count += 1;
        }
        Ok(count)
    }

    /// 候选来源的选项（[`ChoiceSource::Offered`]）：三条**卡定义**，按抽出的顺序。
    ///
    /// 牌区来源调用它 ⇒ [`ChoiceError::WrongAnswer`]（与 [`Self::choice_legal`] 互补：两个函数
    /// 各自只回答一种形态，而不是一个函数返回一个"看情况"的联合体）。
    pub fn choice_offered(&self) -> Result<&[CardDefinitionId], ChoiceError> {
        // `as_ref`（不是 `?` 拷一份）：返回的切片借的是**状态里的**那份候选，不是本地副本。
        let choice = self.choice.as_ref().ok_or(ChoiceError::NotPending)?;
        if choice.source.zone().is_some() {
            return Err(ChoiceError::WrongAnswer);
        }
        Ok(choice.offered.as_slice())
    }

    /// 结算待决的选牌：把选中的牌按 [`ChoiceThen`] 送走，然后清掉问句。
    ///
    /// `answer` 的形状必须和问句的**来源**一致（[`ChoiceError::WrongAnswer`]）：牌区来源回答
    /// 实例，候选来源回答下标。
    ///
    /// `cost_delta` 是**每副本价格**（[`CARD_COST_DELTA_COUNTER`]），只有
    /// [`ChoiceThen::ToHand`] 用得上；其余 `then` 必须传 `0`，否则
    /// [`ChoiceError::DeltaNotApplicable`] —— 静默忽略一个折扣会让"它免费"变成一句谎。
    ///
    /// **全部校验在动手之前**（见本节头第 1 条）。成功之后 [`Self::pending_choice`] 是 `None`。
    pub fn resolve_choice(
        &mut self,
        answer: ChoiceAnswer<'_>,
        cost_delta: i32,
    ) -> Result<ChoiceDone, ChoiceError> {
        let choice = self.choice.ok_or(ChoiceError::NotPending)?;
        // §250：`Free` 变体自带价格语义（"就是 0"），所以调用方**不该**再传一个 delta ——
        // 传了就是两个来源给同一份牌定价。
        if cost_delta != 0
            && !matches!(
                choice.then,
                ChoiceThen::ToHand
                    | ChoiceThen::ToHandFree
                    | ChoiceThen::ToDrawPileBottomFree
            )
        {
            return Err(ChoiceError::DeltaNotApplicable);
        }
        match (choice.source, answer) {
            (ChoiceSource::Offered, ChoiceAnswer::Offered(indices)) => {
                self.resolve_offered(choice, indices, cost_delta)
            }
            (ChoiceSource::Offered, ChoiceAnswer::Instances(_))
            | (_, ChoiceAnswer::Offered(_)) => Err(ChoiceError::WrongAnswer),
            (_, ChoiceAnswer::Instances(picks)) => {
                self.resolve_from_pile(choice, picks, cost_delta)
            }
        }
    }

    /// 牌区来源的答案（[`ChoiceSource::Hand`] / [`ChoiceSource::DiscardPile`]）。
    fn resolve_from_pile(
        &mut self,
        choice: PendingChoice,
        picks: &[CardInstanceId],
        cost_delta: i32,
    ) -> Result<ChoiceDone, ChoiceError> {
        let source = choice.source.zone().ok_or(ChoiceError::WrongAnswer)?;
        let destination = choice.then.destination();
        let picked = picks.len();
        if picked < choice.min as usize || picked > choice.max as usize {
            return Err(ChoiceError::Count {
                picked,
                min: choice.min,
                max: choice.max,
            });
        }

        let Some(zones) = self.card_zones(&choice.chooser) else {
            return Err(ChoiceError::NotInSource);
        };
        // (a) 每张都在来源牌区里，而且不重复。重复直接比 id —— 卡实例 id 在整场里唯一，
        //     所以「同一个 id 出现两次」就是「同一张牌被选了两次」，不需要第二张表。
        let mut slots = [CardSlot::from_index(0); MAX_CARDS_PER_ZONE];
        for (index, id) in picks.iter().enumerate() {
            let Some((zone, slot)) = self.find_card(&choice.chooser, id) else {
                return Err(ChoiceError::NotInSource);
            };
            if zone != source {
                return Err(ChoiceError::NotInSource);
            }
            if picks[..index].iter().any(|earlier| earlier == id) {
                return Err(ChoiceError::Duplicate);
            }
            // §226：有收窄清单时，清单之外的牌**不是**这个问句的答案（页面根本不会列它）。
            if !choice.candidates.is_empty() && !choice.candidates.as_slice().contains(id) {
                return Err(ChoiceError::NotInSource);
            }
            slots[index] = slot;
        }
        // §226：`Copy` 是"造"而不是"搬"—— 原件留在原处，所以它和下面的目的牌区容量判据
        // 是两件事（这里要的是 `into` 的空位，那要的是"要搬进去的那个区"）。分支放在
        // "一个字节都没改"这条线之前，两支各自保证自己全验证完再动手。
        if let ChoiceThen::Copy { copies, into } = choice.then {
            return self.resolve_copy(choice, &slots[..picked], copies, into);
        }
        // §227：`Upgrade` 也不搬牌，只改那份副本的定义 id。
        if choice.then == ChoiceThen::Upgrade {
            return self.resolve_upgrade(choice, &slots[..picked]);
        }
        // (b) 目的牌区装得下。三条一起看，因为「搬第一张时才发现第三张装不下」正是要避免的。
        let destination_room = MAX_CARDS_PER_ZONE.saturating_sub(zones.count(destination));
        if picked > destination_room {
            return Err(ChoiceError::Capacity(CapacityError::Full(
                Container::CardsInZone(destination),
            )));
        }
        // (c) **每副本价格写不写得进去**。`set_mark_counter` 会因那张牌自己的计数器表满了而失败，
        //     而它发生在 `move_card` **之后** —— 那正是"预校验的覆盖范围不等于全部失败来源"
        //     （REVIEW P1，§161.10）。所以搬牌之前先问：这张牌能不能再吃一个 `card_cost_delta`。


        // `DiscardThenDraw` **不需要**额外的手牌容量判据：先丢掉 `picked` 张、再抽 `picked` 张，
        // 手牌最终回到 `picked` 之前那么多。原来的判据是 `hand + picked > MAX` ⇒ 拒绝，那是**错**
        // 的（不是保守）：手牌 90、选 10 张明明做得成它却拒绝（REVIEW P1/P2，§161.10）。

        // §250：`Free` 变体要占一个 mark counter（`card_cost_override`），所以与 `ToHand`
        // 走同一条容量预检 —— 否则"搬完才发现那张牌的计数器表满了"。
        let writes_a_price = matches!(
            choice.then,
            ChoiceThen::ToHandFree | ChoiceThen::ToDrawPileBottomFree
        ) || (choice.then == ChoiceThen::ToHand && cost_delta != 0);
        if writes_a_price {
            for &slot in &slots[..picked] {
                let Some(card) = self.card(slot) else {
                    return Err(ChoiceError::NotInSource);
                };
                if !card_can_take_price(card) {
                    return Err(ChoiceError::Capacity(CapacityError::Full(
                        Container::MarkCounters,
                    )));
                }
            }
        }

        // §227：`ToDrawPileTop` 与其它"搬"只差**落在哪一头**（`Top` = 下一张就抽它）。
        let placement = match choice.then {
            ChoiceThen::ToDrawPileTop => ZonePlacement::Top,
            _ => ZonePlacement::Bottom,
        };

        // ---- 到这里为止一个字节都没改。----
        for &slot in &slots[..picked] {
            self.move_card(&choice.chooser, source, destination, slot, placement)?;
            match choice.then {
                ChoiceThen::ToHand if cost_delta != 0 => self.write_price(slot, cost_delta)?,
                // §250：`Free` 变体写的是**绝对**价格 0（`standard.card_cost_override`），
                // 与 `createRandomCardInstance{CostZero}` 同一格 —— 它在 delta 之前生效，
                // 也正是"这一份的价格就是 0"要的那一格。
                ChoiceThen::ToHandFree | ChoiceThen::ToDrawPileBottomFree => {
                    self.write_free_price(slot)?
                }
                _ => {}
            }
        }
        self.choice = None;

        let mut drawn = 0usize;
        if choice.then == ChoiceThen::DiscardThenDraw {
            drawn = self.draw_cards_with_reshuffle(&choice.chooser, picked)?;
        }
        Ok(ChoiceDone { picked, drawn })
    }

    /// **复制**的答案（[`ChoiceThen::Copy`]，§226/§227）。
    ///
    /// 语义：选中的每一张**留在原处**，往 `into` 再造 `copies` 份**同定义**的副本。
    /// 副本是全新的实例 ⇒ 印刷价、没有每副本价格、没有 `queued_target_id`（StS 的副本就是
    /// 印刷的那张牌，不是被打折或被瞄过的那一份）。
    ///
    /// 两条容量判据都在动手之前：手牌装得下**全部**副本、卡池还有**全部**槽位。
    /// `ChoiceDone::picked` 报的是**造出来几份**（不是选中几张）：调用方要能分辨
    /// "选了一张、造了两份"和"选了两张、各一份"，而这两件事对手牌的影响相同，对日志不同。
    fn resolve_copy(
        &mut self,
        choice: PendingChoice,
        slots: &[CardSlot],
        copies: u8,
        into: CardZone,
    ) -> Result<ChoiceDone, ChoiceError> {
        let copies = usize::from(copies);
        if copies == 0 {
            return Err(ChoiceError::CopiesNotApplicable);
        }
        let picked = slots.len();
        let total = picked.saturating_mul(copies);
        {
            let Some(zones) = self.card_zones(&choice.chooser) else {
                return Err(ChoiceError::NotInSource);
            };
            if total > MAX_CARDS_PER_ZONE.saturating_sub(zones.count(into)) {
                return Err(ChoiceError::Capacity(CapacityError::Full(
                    Container::CardsInZone(into),
                )));
            }
        }
        if self.cards.len() + total > MAX_CARD_INSTANCES {
            return Err(ChoiceError::Capacity(CapacityError::Full(
                Container::CardInstances,
            )));
        }
        // 定义 id 先抄出来：`create_card_instance` 要可变借用，抄完就放掉。
        let mut definitions = [CardDefinitionId::EMPTY; MAX_CHOICE_OFFERED];
        if picked > definitions.len() {
            return Err(ChoiceError::Count {
                picked,
                min: choice.min,
                max: choice.max,
            });
        }
        for (at, slot) in slots.iter().enumerate() {
            let Some(card) = self.card(*slot) else {
                return Err(ChoiceError::NotInSource);
            };
            definitions[at] = card.definition_id;
        }

        // ---- 到这里为止一个字节都没改。----
        let mut created = 0usize;
        for definition in &definitions[..picked] {
            for _ in 0..copies {
                self.create_card_instance(&choice.chooser, *definition, into)?;
                created += 1;
            }
        }
        self.choice = None;
        Ok(ChoiceDone {
            picked: created,
            drawn: 0,
        })
    }

    /// **原地升级**的答案（[`ChoiceThen::Upgrade`]，§227，Armaments）。
    ///
    /// 语义：把每一张选中的牌的定义 id 换成 [`upgraded_id`]（`<id>+`），牌**不搬**。
    ///
    /// 内核只守**机械**那半：`+` 不能加两次、id 不能超长。**"这张牌有没有 `+` 行"是内容的事**，
    /// 由发问的节点把候选收窄（这里没有 `Content`，也不该为了这一件事把它拖进来）——
    /// 两条判据合起来才是完整规则，缺哪条都会让"升级了一张没有升级版的牌"变成一次静默成功。
    fn resolve_upgrade(
        &mut self,
        choice: PendingChoice,
        slots: &[CardSlot],
    ) -> Result<ChoiceDone, ChoiceError> {
        let picked = slots.len();
        let mut upgraded = [CardDefinitionId::EMPTY; MAX_CHOICE_OFFERED];
        if picked > upgraded.len() {
            return Err(ChoiceError::Count {
                picked,
                min: choice.min,
                max: choice.max,
            });
        }
        // ---- 先把新 id 全部算出来：一张算不出来就整体拒绝，一个字节都不改。----
        for (at, slot) in slots.iter().enumerate() {
            let Some(card) = self.card(*slot) else {
                return Err(ChoiceError::NotInSource);
            };
            upgraded[at] =
                upgraded_id(card.definition_id.as_str()).ok_or(ChoiceError::NotUpgradable)?;
        }
        for (at, slot) in slots.iter().enumerate() {
            let Some(card) = self.cards.as_mut_slice().get_mut(slot.index()) else {
                return Err(ChoiceError::NotInSource);
            };
            card.definition_id = upgraded[at];
        }
        self.choice = None;
        Ok(ChoiceDone {
            picked,
            drawn: 0,
        })
    }

    /// 候选来源的答案（[`ChoiceSource::Offered`]，§161.5）。
    ///
    /// 选中的那一张在这一刻**才**被造出来。三张候选里没被选的两张**从来没有存在过** ——
    /// 如果先把三张造成实例再扔掉两张，`card_num=` 与两条 `aside=` 卡行会凭空出现，
    /// 而参考引擎里那个局面根本没有这些牌。指纹要像参考，就不能为了内部方便多造牌。
    fn resolve_offered(
        &mut self,
        choice: PendingChoice,
        indices: &[usize],
        cost_delta: i32,
    ) -> Result<ChoiceDone, ChoiceError> {
        let offered = choice.offered.as_slice();
        let picked = indices.len();
        if picked < choice.min as usize || picked > choice.max as usize {
            return Err(ChoiceError::Count {
                picked,
                min: choice.min,
                max: choice.max,
            });
        }
        let mut definitions = [CardDefinitionId::EMPTY; MAX_CHOICE_OFFERED];
        for (at, index) in indices.iter().enumerate() {
            let Some(definition) = offered.get(*index) else {
                return Err(ChoiceError::NotInSource);
            };
            if indices[..at].contains(index) {
                return Err(ChoiceError::Duplicate);
            }
            definitions[at] = *definition;
        }
        let destination = choice.then.destination();
        // 两张容量一起看：牌区装不下、或者卡池没有多余槽位，都在动手之前拒绝。
        {
            let Some(zones) = self.card_zones(&choice.chooser) else {
                return Err(ChoiceError::NotInSource);
            };
            if picked > MAX_CARDS_PER_ZONE.saturating_sub(zones.count(destination)) {
                return Err(ChoiceError::Capacity(CapacityError::Full(
                    Container::CardsInZone(destination),
                )));
            }
        }
        if self.cards.len() + picked > MAX_CARD_INSTANCES {
            return Err(ChoiceError::Capacity(CapacityError::Full(
                Container::CardInstances,
            )));
        }

        // ---- 到这里为止一个字节都没改。----
        let mut created = 0usize;
        for definition in &definitions[..picked] {
            let slot = self.create_card_instance(&choice.chooser, *definition, destination)?;
            if choice.then == ChoiceThen::ToHand && cost_delta != 0 {
                self.write_price(slot, cost_delta)?;
            }
            // §254：`Wish` —— 造完立刻入队"打出它"。
            //
            // 顺序是语义：**先**入队再继续（同一轮循环里不会有别的请求插到它前面），
            // 而那条请求带 `ignore_unplayable`（这三张牌都是 unplayable）。
            // 目标给 `None`：Wish 的三个选项都不需要目标（它们打的是自己/运行层）。
            if choice.then == ChoiceThen::PlayChosen {
                let instance = self
                    .card(slot)
                    .map(|card| card.id)
                    .ok_or(ChoiceError::NotInSource)?;
                self.enqueue_effect(EffectRequest::PlayCard {
                    owner: choice.chooser,
                    card: instance,
                    target: None,
                    ignore_unplayable: true,
                })
                .map_err(ChoiceError::Capacity)?;
            }
            // §250：候选来源的**免费**变体（`Discovery`）。这一支与 `resolve_from_pile` 是两条
            // 结算路（一个造新实例、一个搬旧实例），所以"免费"必须在两处都写 —— 只写一处就会
            // 出现"从牌堆里拿的免费、从三选一里拿的不免费"，而那在页面上完全看不出来。
            if matches!(
                choice.then,
                ChoiceThen::ToHandFree | ChoiceThen::ToDrawPileBottomFree
            ) && self.write_free_price(slot).is_err()
            {
                return Err(ChoiceError::Capacity(CapacityError::Full(
                    Container::MarkCounters,
                )));
            }
            created += 1;
        }
        self.choice = None;
        Ok(ChoiceDone {
            picked: created,
            drawn: 0,
        })
    }

    /// 铸一张**新卡**：取号 → 建实例 → 按底插入牌区。返回它的池槽位。
    ///
    /// 参考 `CombatState.CreateNextCardInstanceId`（`CombatState.cs:689-696`）：
    /// `$"card_{NextCardInstanceNumber:000000}"`，**先取号再自增**（`exec.rs` 那条
    /// `next_card_instance_number == 1` 的测试就是钉这个的）。
    ///
    /// §161.5 把铸号从 `exec.rs` 搬到这里：发号器是 `CombatState` 的字段，铸号也该在同一个模块。
    /// 两条铸号路径会给出两个"下一个是几"，而那是一种最难看的错 —— 每条路径单独看都对。
    pub fn create_card_instance(
        &mut self,
        owner: &CombatantId,
        definition: CardDefinitionId,
        zone: CardZone,
    ) -> StateResult<CardSlot> {
        self.create_card_instance_at(owner, definition, zone, ZonePlacement::Bottom)
    }

    /// §250：同 [`Self::create_card_instance`]，但能指定落在牌区的**哪一头**。
    ///
    /// `Pride`（"put a copy of this card **on top of** your draw pile"）要 `Top`。
    /// 默认那条走 `Bottom`（追加），因为那是参考 `MoveCardToZone(placement = Bottom)` 的默认值 ——
    /// 只有一个调用方需要"头"，所以**不改**老入口的含义。
    pub fn create_card_instance_at(
        &mut self,
        owner: &CombatantId,
        definition: CardDefinitionId,
        zone: CardZone,
        placement: ZonePlacement,
    ) -> StateResult<CardSlot> {
        let number = self.next_card_instance_number;
        let mut buffer = [0u8; INSTANCE_TEXT_CAP];
        // 装不下是**不可能**的（`INSTANCE_TEXT_CAP` 是 32，最长情形 17）；真发生时返回 `None`
        // 而不是截断 —— 一个被截断的 id 会和另一张牌撞名。
        let text = numbered_text(b"card_", number, &mut buffer)
            .ok_or(CapacityError::IdNotAscii)?;
        let id = CardInstanceId::new(text)?;
        let slot = self.push_card_at(owner, zone, CardInstance::new(id, definition), placement)?;
        self.next_card_instance_number = number.saturating_add(1);
        Ok(slot)
    }

    /// §250：把"这一份免费"写到**那一份副本**上（`standard.card_cost_override = 0`）。
    ///
    /// 与 [`Self::write_price`] 的区别是**哪一格**：那个是"加/减多少"（随出牌清零），
    /// 这个是"价格就是 0"（绝对覆盖）。两条结算路（搬旧实例 / 造新实例）都调它 ——
    /// 一份实现，两个调用点，所以不可能只改一处。
    fn write_free_price(&mut self, slot: CardSlot) -> Result<(), ChoiceError> {
        let key = CounterId::new(CARD_COST_OVERRIDE_COUNTER)
            .map_err(|_| ChoiceError::NotInSource)?;
        let Some(card) = self.cards.as_mut_slice().get_mut(slot.index()) else {
            return Err(ChoiceError::NotInSource);
        };
        card.set_mark_counter(key, 0)
            .map_err(ChoiceError::Capacity)
    }

    /// 把每副本价格写到**那一份副本**上（[`CARD_COST_DELTA_COUNTER`]）。
    fn write_price(&mut self, slot: CardSlot, delta: i32) -> Result<(), ChoiceError> {
        let key = CounterId::new(CARD_COST_DELTA_COUNTER)
            .map_err(|_| ChoiceError::NotInSource)?;
        let Some(card) = self.cards.as_mut_slice().get_mut(slot.index()) else {
            return Err(ChoiceError::NotInSource);
        };
        card.set_mark_counter(key, delta)?;
        Ok(())
    }

    /// 在**一个战斗员**的七个牌区里按 id 找卡，返回 `(在哪个区, 池槽位)`。
    ///
    /// 参考的 `zones.GetCard(id)`（`Cards/CardZones.cs:192-200`）的等价物：只在这套牌区里找，
    /// 所以「找不到」同时覆盖了「卡不存在」与「卡的主人不是这个战斗员」。
    #[must_use]
    pub fn find_card(
        &self,
        owner: &CombatantId,
        card_id: &CardInstanceId,
    ) -> Option<(CardZone, CardSlot)> {
        let zones = self.card_zones(owner)?;
        for zone in CardZone::ALL {
            for index in 0..zones.count(zone) {
                let Some(slot) = zones.slot_at(zone, index) else {
                    continue;
                };
                if self.card(slot).map(|card| card.id == *card_id) == Some(true) {
                    return Some((zone, slot));
                }
            }
        }
        None
    }

    /// 抽 `wanted` 张，抽牌堆空了就**重洗弃牌堆**（每次调用最多一次），返回真抽到的张数。
    ///
    /// 这是从 `turn.rs::draw_for_turn_start` 的循环体里搬出来的，因为消费者从**一个变成了两个**
    /// （回合开始抽牌，以及 §161.3 的 `ChoiceThen::DiscardThenDraw`）。抄第二份的后果是可预测的：
    /// 两边的重洗策略会分叉，而「少重洗一次」只表现为某一步的 `step=` 与牌序不同 —— 那是最难
    /// 从失败信息里读回来的错。
    ///
    /// 循环一定会停：重洗会**搬空弃牌堆**，而循环体内没有任何东西会再往里放牌 ⇒ 最多重洗一次，
    /// 重洗后抽牌堆非空 ⇒ 下一圈必然抽到牌。「抽不满」的唯一成因是**两堆都空**，与参考一致
    /// （`Cards/CardZones.cs:59-60`）。
    pub fn draw_cards_with_reshuffle(
        &mut self,
        owner: &CombatantId,
        wanted: usize,
    ) -> StateResult<usize> {
        let mut drawn = 0usize;
        while drawn < wanted {
            while drawn < wanted {
                if self.draw_card(owner)?.is_none() {
                    break;
                }
                drawn += 1;
            }
            if drawn >= wanted {
                break;
            }
            if self
                .card_zones(owner)
                .is_none_or(|zones| zones.count(CardZone::DiscardPile) == 0)
            {
                break;
            }
            if self.reshuffle_discard_into_draw(owner)? == 0 {
                break;
            }
        }
        Ok(drawn)
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

    // ── 待决的选牌（§161.3）────────────────────────────────────────────────────────────────────
    //
    // 这一组测试盯的是 REVIEW §四.2 的那句话：机制要「可枚举、可存档、可回放」。
    // 所以除了"选完真的动了牌"，还各有一条钉住**枚举**（`choice_legal` 的顺序与截断）
    // 与**拒绝的原子性**（§161.2(a) 在战斗层的同一条话）。

    fn hand_of(n: usize) -> CombatState {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        for i in 0..n {
            let id = std::format!("card_{:06}", i + 1);
            s.push_card(
                &cid("hero"),
                CardZone::Hand,
                CardInstance::new(ciid(&id), cdid("standard.strike")),
            )
            .unwrap();
        }
        s
    }

    /// 一个牌区的卡实例 id，按牌堆顺序。**从状态派生**，不自己记。
    fn pile_ids(s: &CombatState, zone: CardZone) -> std::vec::Vec<CardInstanceId> {
        let zones = s.card_zones(&cid("hero")).unwrap();
        (0..zones.count(zone))
            .filter_map(|index| zones.slot_at(zone, index))
            .filter_map(|slot| s.card(slot))
            .map(|card| card.id)
            .collect()
    }

    /// 一个牌区来源的问句（`offered` 必须留空 —— `begin_choice` 会校验这一点）。
    fn elixir(min: u8, max: u8) -> PendingChoice {
        PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min,
            max,
            then: ChoiceThen::Exhaust,
            offered: Bounded::new(),
            candidates: Bounded::new(),
        }
    }

    /// 一个**候选**来源的问句（§161.5）：三条定义，选一张进手牌。
    fn offered_choice(definitions: &[&str]) -> PendingChoice {
        let mut offered = Bounded::new();
        for definition in definitions {
            offered
                .push(CardDefinitionId::new(definition).expect("短 id"), Container::ChoiceOptions)
                .expect("候选装得下");
        }
        PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Offered,
            min: 1,
            max: 1,
            then: ChoiceThen::ToHand,
            offered,
            candidates: Bounded::new(),
        }
    }

    fn gamblers_brew(max: u8) -> PendingChoice {
        PendingChoice {
            then: ChoiceThen::DiscardThenDraw,
            ..elixir(0, max)
        }
    }

    #[test]
    fn the_legal_options_are_the_source_pile_in_pile_order() {
        let mut s = hand_of(3);
        // 没有待决问句时，枚举是**一个错误**，不是"空清单" —— 空清单会被读成
        // "可以选的东西是零个"，而那是一个不存在的状态。
        let mut buf = [CardInstanceId::EMPTY; 8];
        assert_eq!(s.choice_legal(&mut buf), Err(ChoiceError::NotPending));

        s.begin_choice(elixir(0, 3)).unwrap();
        assert_eq!(s.choice_legal(&mut buf), Ok(3));
        assert_eq!(
            &buf[..3],
            pile_ids(&s, CardZone::Hand).as_slice(),
            "候选清单必须就是来源牌区，且顺序与牌堆一致"
        );

        // 缓冲区装不下 ⇒ 响亮失败，**不截断**。截断掉的选项等于一条不存在的规则，而
        // 「只能选前两张」这种错只会在玩家真的想选第三张时才被发现。
        let mut tiny = [CardInstanceId::EMPTY; 2];
        assert_eq!(
            s.choice_legal(&mut tiny),
            Err(ChoiceError::Capacity(CapacityError::Full(
                Container::ChoiceOptions
            )))
        );
        assert_eq!(s.pending_choice(), Some(elixir(0, 3)), "枚举失败不改问句");
    }

    #[test]
    fn exhausting_the_chosen_cards_moves_exactly_them_and_clears_the_question() {
        // Elixir：「消耗任意张手牌」。选 2 张。
        let mut s = hand_of(3);
        let hand = pile_ids(&s, CardZone::Hand);
        s.begin_choice(elixir(0, 3)).unwrap();
        let done = s.resolve_choice(ChoiceAnswer::Instances(&[hand[0], hand[2]]), 0).unwrap();
        assert_eq!(done, ChoiceDone { picked: 2, drawn: 0 });
        assert_eq!(s.pending_choice(), None, "结算之后问句必须消失");

        assert_eq!(
            pile_ids(&s, CardZone::ExhaustPile),
            std::vec![hand[0], hand[2]],
            "被选中的两张按选择顺序进消耗堆"
        );
        assert_eq!(pile_ids(&s, CardZone::Hand), std::vec![hand[1]], "没被选的必须留手");
    }

    #[test]
    fn discarding_then_drawing_returns_as_many_cards_as_were_dropped() {
        // Gambler's Brew：「弃任意张，然后抽同样多」。
        let mut s = hand_of(3);
        for i in 0..4 {
            let id = std::format!("draw_{:06}", i + 1);
            s.push_card(
                &cid("hero"),
                CardZone::DrawPile,
                CardInstance::new(ciid(&id), cdid("standard.defend")),
            )
            .unwrap();
        }
        let hand = pile_ids(&s, CardZone::Hand);
        s.begin_choice(gamblers_brew(3)).unwrap();
        let done = s.resolve_choice(ChoiceAnswer::Instances(&[hand[0], hand[1]]), 0).unwrap();
        assert_eq!(done, ChoiceDone { picked: 2, drawn: 2 });
        assert_eq!(pile_ids(&s, CardZone::DiscardPile), std::vec![hand[0], hand[1]]);
        assert_eq!(s.card_zones(&cid("hero")).unwrap().count(CardZone::Hand), 3);
        // 抽到的是**抽牌堆的最上面两张**（`draw_card` 取 front），顺序照抄。
        assert_eq!(
            pile_ids(&s, CardZone::Hand),
            std::vec![hand[2], ciid("draw_000001"), ciid("draw_000002")]
        );
        // 抽牌堆少了 2 张，弃牌堆多了 2 张 —— 池子不长（移动复用槽位）。
        assert_eq!(s.card_count(), 7);
    }

    #[test]
    fn drawing_past_an_empty_draw_pile_reshuffles_like_the_turn_start_does() {
        // 抽牌堆空、弃牌堆有牌 ⇒ 必须走 `reshuffle_discard_into_draw`（一次，且推进 random_step）。
        // 不做这一步的话"弃 2 抽 2"会安静地只抽到 0 张 —— 那看起来像是玩家选错了。
        let mut s = hand_of(3);
        let hand = pile_ids(&s, CardZone::Hand);
        let step_before = s.random_step;
        s.begin_choice(gamblers_brew(3)).unwrap();
        let done = s.resolve_choice(ChoiceAnswer::Instances(&[hand[0], hand[1]]), 0).unwrap();
        assert_eq!(done.picked, 2);
        // 弃牌堆里的 2 张被洗回抽牌堆，于是这 2 张**又**被抽了回来。
        assert_eq!(done.drawn, 2, "重洗之后抽得满");
        assert_eq!(s.random_step, step_before + 1, "重洗推进一次随机步");
    }

    #[test]
    fn a_refused_choice_leaves_the_combat_byte_identical() {
        // §161.2(a) 在战斗层的同一条话：拒绝 ⇒ 一个字节都没改。
        //
        // 判据用规范文本（`canonical_text`），因为 `CombatState` 没有派生 `PartialEq`
        // （18 个字段里有 6 个定容容器，逐字段写一份"等价"没法确认自己没漏）。
        // ⚠️ 规范文本**不含** `choice` 本身（参考引擎没有这个字段，见 §161.3 的文档），
        // 所以下面每一种拒绝都额外断言 `pending_choice()` 没变 —— 两边都看才完整。
        let mut s = hand_of(3);
        let hand = pile_ids(&s, CardZone::Hand);
        s.begin_choice(elixir(1, 2)).unwrap();
        let before = canonical_text(&s);
        let before_choice = s.pending_choice();

        let refused = [
            // (a) 张数：0 张低于下限 1、3 张高于上限 2。
            (
                s.clone().resolve_choice(ChoiceAnswer::Instances(&[]), 0),
                ChoiceError::Count {
                    picked: 0,
                    min: 1,
                    max: 2,
                },
            ),
            (
                s.clone()
                    .resolve_choice(ChoiceAnswer::Instances(&[hand[0], hand[1], hand[2]]), 0),
                ChoiceError::Count {
                    picked: 3,
                    min: 1,
                    max: 2,
                },
            ),
            // (b) 来源：库里没有这张牌。
            (
                s.clone().resolve_choice(ChoiceAnswer::Instances(&[ciid("not_a_card")]), 0),
                ChoiceError::NotInSource,
            ),
            // (c) 重复：同一张选两次。
            (
                s.clone().resolve_choice(ChoiceAnswer::Instances(&[hand[0], hand[0]]), 0),
                ChoiceError::Duplicate,
            ),
        ];
        for (outcome, expected) in refused {
            assert_eq!(outcome, Err(expected), "拒绝原因必须具体");
        }

        // 真·原子性：**不是**用 `s.clone()` 试错，而是在真身上走一遍再比。
        assert_eq!(s.resolve_choice(ChoiceAnswer::Instances(&[hand[0], hand[0]]), 0), Err(ChoiceError::Duplicate));
        assert_eq!(canonical_text(&s), before, "被拒绝的选牌改了战斗");
        assert_eq!(s.pending_choice(), before_choice, "被拒绝的选牌改了问句");

        // 一张已经不在来源牌区里的牌：先把它丢掉，再从手牌里选它。
        let mut moved = hand_of(3);
        let hand = pile_ids(&moved, CardZone::Hand);
        moved
            .move_card(
                &cid("hero"),
                CardZone::Hand,
                CardZone::DiscardPile,
                CardSlot::from_index(0),
                ZonePlacement::Bottom,
            )
            .unwrap();
        moved.begin_choice(elixir(0, 2)).unwrap();
        let before = canonical_text(&moved);
        assert_eq!(
            moved.resolve_choice(ChoiceAnswer::Instances(&[hand[0]]), 0),
            Err(ChoiceError::NotInSource),
            "来源是手牌，选一张弃牌堆里的牌必须被拒"
        );
        assert_eq!(canonical_text(&moved), before);
    }

    #[test]
    fn a_choice_reads_its_source_pile_instead_of_assuming_the_hand() {
        // §161.3 ships `ChoiceSource::{Hand, DiscardPile}` and **only `Hand` has content today**
        // (Elixir, Gambler's Brew). `DiscardPile` is Liquid Memories' half of the mechanism, and it
        // waits for §161.4's per-copy price -- so it is here without a caller.
        //
        // That is only defensible if the variant is **tested**, otherwise "the source is read"
        // is a claim nobody checked and the next potion would find out. Both directions:
        let mut s = hand_of(2);
        let hand = pile_ids(&s, CardZone::Hand);
        s.move_card(
            &cid("hero"),
            CardZone::Hand,
            CardZone::DiscardPile,
            CardSlot::from_index(0),
            ZonePlacement::Bottom,
        )
        .unwrap();
        let discarded = pile_ids(&s, CardZone::DiscardPile);
        assert_eq!(discarded.len(), 1);

        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::DiscardPile,
            min: 0,
            max: 1,
            then: ChoiceThen::Exhaust,
            offered: Bounded::new(),
            candidates: Bounded::new(),
        })
        .unwrap();
        let mut buf = [CardInstanceId::EMPTY; 8];
        assert_eq!(s.choice_legal(&mut buf), Ok(1));
        assert_eq!(&buf[..1], discarded.as_slice(), "the options are the discard pile");

        // A hand card is **not** an option, even though it is the same combatant's card.
        assert_eq!(s.resolve_choice(ChoiceAnswer::Instances(&[hand[1]]), 0), Err(ChoiceError::NotInSource));
        // The discarded one is, and it lands where `then` says.
        assert_eq!(
            s.resolve_choice(ChoiceAnswer::Instances(&discarded), 0),
            Ok(ChoiceDone {
                picked: 1,
                drawn: 0
            })
        );
        assert_eq!(pile_ids(&s, CardZone::ExhaustPile), discarded);
    }

    #[test]
    fn a_card_taken_into_hand_carries_its_own_price() {
        // Liquid Memories: take one card out of the discard pile into your hand, free this turn.
        // The price is a **mark counter on that copy** (`standard.card_cost_delta`), which is the
        // reference's model -- a status cannot say "the card you chose is free", because a status
        // prices every card its wearer holds.
        let mut s = hand_of(2);
        let hand = pile_ids(&s, CardZone::Hand);
        s.move_card(
            &cid("hero"),
            CardZone::Hand,
            CardZone::DiscardPile,
            CardSlot::from_index(0),
            ZonePlacement::Bottom,
        )
        .unwrap();
        let discarded = pile_ids(&s, CardZone::DiscardPile);
        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::DiscardPile,
            min: 1,
            max: 1,
            then: ChoiceThen::ToHand,
            offered: Bounded::new(),
            candidates: Bounded::new(),
        })
        .unwrap();
        // The delta is "minus the printed cost", which only the caller can compute. -2 here.
        assert_eq!(
            s.resolve_choice(ChoiceAnswer::Instances(&discarded), -2),
            Ok(ChoiceDone {
                picked: 1,
                drawn: 0
            })
        );
        assert_eq!(
            pile_ids(&s, CardZone::Hand),
            std::vec![hand[1], discarded[0]],
            "the card is back in hand"
        );
        assert!(
            pile_ids(&s, CardZone::DiscardPile).is_empty(),
            "and no longer in the discard pile"
        );

        // The price rides on the **copy**, so a zone change does not lose it.
        let (_, slot) = s.find_card(&cid("hero"), &discarded[0]).expect("in hand");
        let counter = s.card(slot).expect("a card").mark_counters().iter()
            .find(|counter| counter.key.as_str() == CARD_COST_DELTA_COUNTER)
            .copied()
            .expect("the price is on the card");
        assert_eq!(counter.value, -2);
    }

    #[test]
    fn a_price_given_to_a_choice_that_has_none_is_a_caller_bug() {
        // Three `then`s, one price. Handing a discount to `Exhaust` would either be ignored (a lie:
        // "it is free" -- no) or applied to cards that then get exhausted (pointless). Loud instead.
        let mut s = hand_of(2);
        let hand = pile_ids(&s, CardZone::Hand);
        s.begin_choice(elixir(0, 2)).unwrap();
        assert_eq!(
            s.resolve_choice(ChoiceAnswer::Instances(&[hand[0]]), -2),
            Err(ChoiceError::DeltaNotApplicable)
        );
        assert_eq!(s.pending_choice(), Some(elixir(0, 2)), "and nothing moved");
        // The same answer with the right argument works, so the refusal is about the delta only.
        assert_eq!(
            s.resolve_choice(ChoiceAnswer::Instances(&[hand[0]]), 0),
            Ok(ChoiceDone {
                picked: 1,
                drawn: 0
            })
        );
    }

    /// **每副本价格写不进去时，选牌必须一张牌都不动**（REVIEW P1，§161.10）。
    ///
    /// 旧实现先 `move_card` 再 `write_price`，而后者会因那张牌自己的计数器表满了而失败 ——
    /// 于是"被拒绝"的选牌已经搬走了一张。判据是 §161.2(a) 的老规矩：**规范文本相等，且问句还在**。
    #[test]
    fn a_choice_that_cannot_write_its_price_moves_nothing() {
        let mut s = hand_of(2);
        let hand = pile_ids(&s, CardZone::Hand);
        // 把第一张牌的计数器表塞满（不含 `card_cost_delta`），于是它再也吃不下一个价格。
        let (_, slot) = s.find_card(&cid("hero"), &hand[0]).expect("in hand");
        for index in 0..MAX_MARK_COUNTERS_PER_CARD {
            let key = CounterId::new(&std::format!("filler_{index}")).expect("short id");
            s.card_mut(slot)
                .expect("card")
                .set_mark_counter(key, index as i32)
                .expect("counter room");
        }
        assert!(
            !card_can_take_price(s.card(slot).expect("card")),
            "the fixture must actually be full"
        );

        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min: 1,
            max: 1,
            then: ChoiceThen::ToHand,
            offered: Bounded::new(),
            candidates: Bounded::new(),
        })
        .unwrap();
        let before = canonical_text(&s);
        assert_eq!(
            s.resolve_choice(ChoiceAnswer::Instances(&[hand[0]]), -1),
            Err(ChoiceError::Capacity(CapacityError::Full(
                Container::MarkCounters
            ))),
            "a price that cannot be written must be refused"
        );
        assert_eq!(canonical_text(&s), before, "and nothing may have moved");
        assert_eq!(s.pending_choice().is_some(), true, "the question is still open");
    }

    /// `DelayedThenDraw` 在容量边缘：先丢再抽，手牌最终回到原样 ⇒ **必须允许**。
    ///
    /// 旧的判据是 `hand + picked > MAX_CARDS_PER_ZONE ⇒ 拒绝`，那不是"保守"而是**错**。
    #[test]
    fn discarding_before_drawing_does_not_need_extra_hand_room() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        // 手牌塞到只剩 2 格：选 2 张丢弃之后，手牌空出 2 格，抽 2 张正好填回。
        for index in 0..(MAX_CARDS_PER_ZONE - 2) {
            let id = std::format!("card_{:06}", index + 1);
            s.push_card(
                &cid("hero"),
                CardZone::Hand,
                CardInstance::new(ciid(&id), cdid("standard.strike")),
            )
            .unwrap();
        }
        for index in 0..4 {
            let id = std::format!("draw_{:06}", index + 1);
            s.push_card(
                &cid("hero"),
                CardZone::DrawPile,
                CardInstance::new(ciid(&id), cdid("standard.defend")),
            )
            .unwrap();
        }
        let hand_before = s.card_zones(&cid("hero")).unwrap().count(CardZone::Hand);
        assert_eq!(
            hand_before,
            MAX_CARDS_PER_ZONE - 2,
            "the fixture must sit exactly two slots below the cap -- that is the edge the old              check got wrong"
        );
        let picks = pile_ids(&s, CardZone::Hand);
        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min: 0,
            max: 2,
            then: ChoiceThen::DiscardThenDraw,
            offered: Bounded::new(),
            candidates: Bounded::new(),
        })
        .unwrap();
        let done = s.resolve_choice(ChoiceAnswer::Instances(&picks[..2]), 0).expect(
            "discarding two cards frees exactly the two slots the draw needs -- this must be legal",
        );
        assert_eq!(done.picked, 2);
        assert_eq!(done.drawn, 2);
        assert_eq!(
            s.card_zones(&cid("hero")).unwrap().count(CardZone::Hand),
            hand_before,
            "two out, two in"
        );
    }

    #[test]
    fn an_offered_choice_creates_only_the_card_that_was_picked() {
        // §161.5：三张候选里只有被选的那一张**曾经存在**。
        //
        // 反过来的做法（先把三张造成实例放进一个牌区，再扔掉两张）会凭空多出三张牌：
        // `card_num=` 与两张 `aside=` 卡行都会出现在指纹里，而参考引擎那个局面根本没有它们。
        // 这条测试盯的就是"牌池里只多了一张"。
        // 空手牌起步是**必须的**：`hand_of` 用 `push_card` 手搓 id（`card_000001`…），而
        // `push_card` **不发号** —— 发号器仍然停在 1，于是铸出来的新卡会和手搓的那张**撞 id**，
        // `find_card` 找到的是先扫到的那一张。（这不是实现的问题，是夹具的问题；第一版就是这么红的。）
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        let cards_before = s.card_count();
        let next_number = s.next_card_instance_number;
        s.begin_choice(offered_choice(&["card.anger", "card.bash", "card.cleave"]))
            .unwrap();
        assert_eq!(
            s.choice_offered(),
            Ok(&[
                CardDefinitionId::new("card.anger").unwrap(),
                CardDefinitionId::new("card.bash").unwrap(),
                CardDefinitionId::new("card.cleave").unwrap(),
            ][..]),
            "候选按抽出的顺序，原样可读"
        );
        // 牌区来源的读取器对它必须**响亮拒绝**，而不是返回一个空清单。
        let mut buf = [CardInstanceId::EMPTY; 8];
        assert_eq!(s.choice_legal(&mut buf), Err(ChoiceError::WrongAnswer));
        assert_eq!(s.card_count(), cards_before, "提问本身不造牌");

        let done = s.resolve_choice(ChoiceAnswer::Offered(&[1]), -1).unwrap();
        assert_eq!(done, ChoiceDone { picked: 1, drawn: 0 });
        assert_eq!(s.pending_choice(), None);
        assert_eq!(
            s.card_count(),
            cards_before + 1,
            "只多了一张：没被选的两张从来没存在过"
        );
        assert_eq!(s.next_card_instance_number, next_number + 1, "发号器只动了 1");
        // 造出来的那张用的是**参考的 id 形状**，进的是手牌，带着每副本价格。
        let hand = pile_ids(&s, CardZone::Hand);
        let picked = *hand.last().expect("手牌非空");
        assert_eq!(
            picked.as_str(),
            std::format!("card_{:06}", next_number),
            "`card_%06d` 且先取号再自增"
        );
        let (_, slot) = s.find_card(&cid("hero"), &picked).expect("在手牌里");
        let card = s.card(slot).expect("卡在");
        assert_eq!(card.definition_id.as_str(), "card.bash", "选的是第 2 张候选");
        let price = card
            .mark_counters()
            .iter()
            .find(|counter| counter.key.as_str() == CARD_COST_DELTA_COUNTER)
            .map(|counter| counter.value);
        assert_eq!(price, Some(-1), "每副本价格也写上了");

        // 候选来源的问句读完了就没了：`choice_offered` 回到"没有待决问句"。
        assert_eq!(s.choice_offered(), Err(ChoiceError::NotPending));
    }

    /// §226：`Copy` —— **原件不动、副本进手牌**，而收窄清单是唯一的合法集合。
    ///
    /// 四件事各一条断言，因为它们各自能单独坏掉：
    /// ① 清单外的牌不能答这个问句（页面根本不会列它，绕过页面也不能成）；
    /// ② 拒绝**一个字节都不改**（§161.2(a) 的老规矩）；
    /// ③ 造出 `copies` 份**同定义**的副本，原件仍在原处；
    /// ④ `copies` 与 `then` 不自洽时 `begin_choice` 当场拒绝（"复制 0 份"是一次成功的空操作）。
    #[test]
    fn a_copy_question_leaves_the_original_alone() {
        // ⚠️ 手牌必须用 `create_card_instance` 造，**不能**抄 `hand_of()` 的 `push_card("card_000001")`：
        // 那个帮手绕过了发号器，于是 `create_card_instance` 会把同一个 id 再发一次，副本与原件
        // **同名**（本测试第一次跑就这么栽了，读数见 §226）。真实战斗里每一张牌都从发号器来，
        // 所以这不是内核缺陷；但"手抄 id 的测试"必须知道这一点。
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        for _ in 0..2 {
            s.create_card_instance(&cid("hero"), cdid("standard.strike"), CardZone::Hand)
                .expect("the pool has room");
        }
        let ids = pile_ids(&s, CardZone::Hand);
        let mut candidates = Bounded::new();
        candidates
            .push(ids[0], Container::ChoiceOptions)
            .expect("one candidate fits");
        let question = PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min: 1,
            max: 1,
            then: ChoiceThen::Copy {
                copies: 2,
                into: CardZone::Hand,
            },
            offered: Bounded::new(),
            candidates,
        };
        // ④ "复制 0 份"仍要拒 —— 它是一次**成功**的空操作，那是最难发现的一种错。
        //   （§227 之后"副本数"长在变体里，所以"`then = Exhaust` 却带 copies"已经构造不出来。）
        assert_eq!(
            s.begin_choice(PendingChoice {
                then: ChoiceThen::Copy {
                    copies: 0,
                    into: CardZone::Hand,
                },
                ..question
            }),
            Err(ChoiceError::CopiesNotApplicable)
        );
        s.begin_choice(question).expect("the question is answerable");

        // ① 清单说"只有第一张"，枚举就只能枚举出第一张。
        let mut buf = [CardInstanceId::EMPTY; 8];
        assert_eq!(s.choice_legal(&mut buf), Ok(1));
        assert_eq!(buf[0], ids[0]);

        // ② 清单外的牌被拒，而且状态一个字节都没变。`CombatState` 没有 `PartialEq`（§161.10），
        // 所以按"同一组可观察量"比：手牌清单 + 卡池长度 + 还有没有问句。
        let before = pile_ids(&s, CardZone::Hand);
        let pool_before = s.cards.len();
        assert_eq!(
            s.resolve_choice(ChoiceAnswer::Instances(&ids[1..2]), 0),
            Err(ChoiceError::NotInSource)
        );
        assert_eq!(pile_ids(&s, CardZone::Hand), before, "a refusal moves no card");
        assert_eq!(s.cards.len(), pool_before, "a refusal creates no card");
        assert_eq!(
            s.pending_choice().map(|choice| choice.then),
            Some(ChoiceThen::Copy {
                copies: 2,
                into: CardZone::Hand,
            }),
            "a refusal keeps the question open"
        );

        // ③ 原件不动 + 两份副本进手牌（同一个定义 id）。
        let original = s.card(s.find_card(&cid("hero"), &ids[0]).expect("it is there").1)
            .expect("the card")
            .definition_id;
        let done = s.resolve_choice(ChoiceAnswer::Instances(&ids[..1]), 0).expect("copied");
        assert_eq!(done.picked, 2, "two copies were created");
        assert_eq!(s.pending_choice(), None, "the question is gone");
        let hand = pile_ids(&s, CardZone::Hand);
        assert_eq!(hand.len(), 4, "2 originals + 2 copies, got {hand:?}");
        assert!(
            hand.contains(&ids[0]),
            "the picked card itself must stay in the hand"
        );
        let mut copies = 0;
        for id in &hand {
            let slot = s.find_card(&cid("hero"), id).expect("in hand").1;
            let slot = s.find_card(&cid("hero"), id).expect("in hand").1;
            if s.card(slot).expect("card").definition_id == original
                && *id != ids[0]
                && *id != ids[1]
            {
                copies += 1;
            }
        }
        assert_eq!(copies, 2, "both new instances carry the picked definition");
    }

    /// §227：`Upgrade` —— 选中的牌**原地**升级（定义 id 变 `<id>+`），牌不搬。
    ///
    /// 三件事：升级真的发生、牌还在原处、而"已经带 `+` 的牌"再升级是**响亮拒绝**
    /// （`NotUpgradable`，不是"什么都不做"）—— 后者是内核能看见的那一半规则，
    /// 另一半（有没有 `+` 行）由发问的节点收窄候选。
    #[test]
    fn an_upgrade_choice_rewrites_the_definition_in_place() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        s.create_card_instance(&cid("hero"), cdid("standard.strike"), CardZone::Hand)
            .expect("the pool has room");
        let ids = pile_ids(&s, CardZone::Hand);
        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min: 1,
            max: 1,
            then: ChoiceThen::Upgrade,
            offered: Bounded::new(),
            candidates: Bounded::new(),
        })
        .expect("the question is answerable");

        let done = s
            .resolve_choice(ChoiceAnswer::Instances(&ids[..1]), 0)
            .expect("upgraded");
        assert_eq!(done.picked, 1);
        // 牌还在手牌里的**同一个位置**（`Upgrade` 不搬牌）。
        assert_eq!(pile_ids(&s, CardZone::Hand), ids, "the card did not move");
        let definition = s
            .card(s.find_card(&cid("hero"), &ids[0]).expect("still there").1)
            .expect("the card")
            .definition_id;
        assert_eq!(definition.as_str(), "standard.strike+");

        // §229：**内核只守机械那一半**。"能不能再升一次"要问内容（有没有 `<id>+` 那一行），而
        // `CombatState` 里没有内容 —— §229 把原来那条"见到 `+` 结尾就拒绝"的**猜法**换成了查表，
        // 查表发生在发问的节点里（`upgradable_definition`，判据见
        // `armaments_gains_block_then_upgrades_the_chosen_card`：没有 `+` 行的 `dazed` 不进候选）。
        //
        // 于是这里能拒绝的只剩**装不下**：40 字节的 id 再加一个 `+` 会被截断成另一个 id（撞名）。
        let long = "x".repeat(CardDefinitionId::CAP);
        assert!(
            upgraded_id(&std::format!("{long}+")).is_none(),
            "a `+` that does not fit is refused -- truncating would mint a *different* id"
        );
    }

    /// §227：`ToDrawPileTop` —— 选中的牌搬到抽牌堆**顶**（`ZonePlacement::Top` = 下一张就抽它）。
    ///
    /// 判据必须比"它在抽牌堆里"更强：先往抽牌堆放一张垫底的牌，然后问"谁在最前面"。
    #[test]
    fn a_to_draw_pile_top_choice_lands_on_the_draw_top() {
        let mut s = fight();
        s.add_combatant(hero()).unwrap();
        s.create_card_instance(&cid("hero"), cdid("standard.strike"), CardZone::Hand)
            .expect("the pool has room");
        // 垫底：`standard.defend` 先进抽牌堆，所以它**不该**是下一张。
        s.create_card_instance(&cid("hero"), cdid("standard.defend"), CardZone::DrawPile)
            .expect("the pool has room");
        let ids = pile_ids(&s, CardZone::Hand);
        s.begin_choice(PendingChoice {
            chooser: cid("hero"),
            source: ChoiceSource::Hand,
            min: 1,
            max: 1,
            then: ChoiceThen::ToDrawPileTop,
            offered: Bounded::new(),
            candidates: Bounded::new(),
        })
        .expect("the question is answerable");
        s.resolve_choice(ChoiceAnswer::Instances(&ids[..1]), 0)
            .expect("moved");

        assert!(pile_ids(&s, CardZone::Hand).is_empty(), "it left the hand");
        let draw = pile_ids(&s, CardZone::DrawPile);
        assert_eq!(draw.len(), 2, "two cards in the draw pile, got {draw:?}");
        assert_eq!(
            draw[0], ids[0],
            "the picked card is on **top** (index 0 is the draw top), got {draw:?}"
        );
    }

    #[test]
    fn an_offered_choice_and_a_pile_choice_cannot_answer_each_other() {
        // 两种答案形状不能互换 —— 否则"从手牌选"会拿着三个候选下标去查手牌，
        // 而结果**看起来像成功**（0 张或别的一张）。形状不匹配必须响。
        let mut s = hand_of(2);
        let hand = pile_ids(&s, CardZone::Hand);
        s.begin_choice(elixir(0, 2)).unwrap();
        assert_eq!(
            s.resolve_choice(ChoiceAnswer::Offered(&[0]), 0),
            Err(ChoiceError::WrongAnswer)
        );
        assert_eq!(s.pending_choice(), Some(elixir(0, 2)), "拒绝不改问句");

        let mut offered = hand_of(1);
        offered
            .begin_choice(offered_choice(&["card.anger", "card.bash", "card.cleave"]))
            .unwrap();
        assert_eq!(
            offered.resolve_choice(ChoiceAnswer::Instances(&[hand[0]]), 0),
            Err(ChoiceError::WrongAnswer)
        );
        // 越界的下标也要响，不能悄悄换成别的候选。
        assert_eq!(
            offered.resolve_choice(ChoiceAnswer::Offered(&[3]), 0),
            Err(ChoiceError::NotInSource)
        );
        // 同一个候选选两次：`min = max = 1` 先撞**张数**，所以换一个能收两张的问句来测重复。
        assert_eq!(
            offered.resolve_choice(ChoiceAnswer::Offered(&[0, 0]), 0),
            Err(ChoiceError::Count {
                picked: 2,
                min: 1,
                max: 1
            })
        );
        let mut two = fight();
        two.add_combatant(hero()).unwrap();
        let mut question = offered_choice(&["card.anger", "card.bash", "card.cleave"]);
        question.max = 2;
        two.begin_choice(question).unwrap();
        assert_eq!(
            two.resolve_choice(ChoiceAnswer::Offered(&[1, 1]), 0),
            Err(ChoiceError::Duplicate)
        );
    }

    #[test]
    fn a_choice_that_has_candidates_must_not_also_name_a_pile() {
        // 「候选」与「来源」不一致 = 一个玩家答不出来的问题。两边都校验。
        let mut s = hand_of(2);
        let mut wrong = offered_choice(&["card.anger"]);
        wrong.source = ChoiceSource::Hand;
        assert_eq!(s.begin_choice(wrong), Err(ChoiceError::WrongAnswer));
        let mut wrong = elixir(0, 2);
        wrong.offered = offered_choice(&["card.anger"]).offered;
        assert_eq!(s.begin_choice(wrong), Err(ChoiceError::WrongAnswer));
        assert_eq!(s.pending_choice(), None, "被拒绝的问句一个都不留");
    }

    #[test]
    fn a_choice_that_could_never_be_answered_is_refused_up_front() {
        // `min` 超过来源牌区的张数 ⇒ 这个问句永远无法回答。把它放行的话，这一局会被一个
        // 玩家答不出来的弹窗钉死，而内核里没有任何东西会报错 —— 正是本项目最怕的那种形态。
        let mut s = hand_of(2);
        assert_eq!(
            s.begin_choice(elixir(3, 3)),
            Err(ChoiceError::Count {
                picked: 2,
                min: 3,
                max: 3,
            })
        );
        assert_eq!(s.pending_choice(), None, "被拒绝的问句不许留下");

        // `min > max` 是内容错误（不是玩家输入错误），同样响亮。
        assert_eq!(
            s.begin_choice(elixir(2, 1)),
            Err(ChoiceError::Count {
                picked: 2,
                min: 2,
                max: 1,
            })
        );

        // 选 0 张（下限 0）是合法答案，而且**真的**把问句消掉 —— 这就是"取消"。
        s.begin_choice(elixir(0, 2)).unwrap();
        assert_eq!(s.resolve_choice(ChoiceAnswer::Instances(&[]), 0), Ok(ChoiceDone { picked: 0, drawn: 0 }));
        assert_eq!(s.pending_choice(), None);
    }

    #[test]
    fn a_second_choice_is_refused_instead_of_queued() {
        // 不排队：两个待决问句叠在一起，界面无法表达先后，回放也无法表达。
        let mut s = hand_of(2);
        s.begin_choice(elixir(0, 2)).unwrap();
        assert_eq!(
            s.begin_choice(gamblers_brew(2)),
            Err(ChoiceError::AlreadyPending),
            "第二个问句必须被拒，而不是覆盖或排队"
        );
        assert_eq!(s.pending_choice(), Some(elixir(0, 2)), "第一个问句原样留下");
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
    /// §281：`draw_in_range` —— **每一档都到过**（不是"总是 min"），而且 `step` 每次恰好 +1。
    ///
    /// 两侧都要：只看"落在范围内"的话，一个**永远返回 min** 的实现也全绿（范围检查是它的
    /// 子集）。所以这里钉"跨度 4 的抽取里四个值都出现过"。
    #[test]
    fn a_draw_covers_its_whole_range_and_advances_one_step() {
        let mut state = CombatState::new(CombatId::new("fight").unwrap(), 1234);
        let step_before = state.random_step;
        let seed_before = state.random_seed;
        let mut seen = [false; 4];
        for index in 0..64 {
            let value = state.draw_in_range(0, 3);
            assert!(
                (0..=3).contains(&value),
                "draw {index} gave {value}, outside 0..=3"
            );
            seen[value as usize] = true;
        }
        assert_eq!(seen, [true; 4], "64 draws over 0..=3 must hit every value");
        assert_eq!(
            state.random_step - step_before,
            64,
            "one draw = one step (the shuffle's convention)"
        );
        assert_eq!(
            state.random_seed, seed_before,
            "the seed must NOT move -- only `step` does (that is what makes a seed replayable)"
        );
        // `max <= min` 是常数，**不消耗**随机流。
        let step = state.random_step;
        assert_eq!(state.draw_in_range(7, 7), 7);
        assert_eq!(state.draw_in_range(9, 3), 9, "an inverted range is the low end");
        assert_eq!(state.random_step, step, "a constant range draws nothing");
    }

    /// §281：同一个种子 ⇒ 同一个序列；换一个种子 ⇒ 换一条序列（两侧）。
    #[test]
    fn a_draw_sequence_replays_from_its_seed() {
        let mut a = CombatState::new(CombatId::new("fight").unwrap(), 4242);
        let mut b = CombatState::new(CombatId::new("fight").unwrap(), 4242);
        let mut c = CombatState::new(CombatId::new("fight").unwrap(), 4243);
        let mut same = 0;
        let mut differ = 0;
        for _ in 0..32 {
            let x = a.draw_in_range(0, 9);
            let y = b.draw_in_range(0, 9);
            let z = c.draw_in_range(0, 9);
            assert_eq!(x, y, "the same seed must replay the same sequence");
            if x != z {
                differ += 1;
            } else {
                same += 1;
            }
        }
        assert!(
            differ > 0,
            "a different seed produced the same 32 draws -- the seed is not being read"
        );
        assert!(same < 32, "and they must not agree on everything either");
        // 抽取与洗牌共用 `(seed, step)` 的派生：把 step 推到同一个值，两种随机的
        // "下一个数"必须一致（否则两条路对同一个种子的看法会分家）。
        let mut d = CombatState::new(CombatId::new("fight").unwrap(), 77);
        d.random_step = 5;
        assert_eq!(
            d.draw_in_range(0, 1000),
            (crate::rng::draw_u32(77, 5) % 1001) as i32,
            "the draw must derive from (seed, step) exactly like the shuffle does"
        );
    }

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

    /// §216（审阅 P1-C）：上一场留下的三个标量必须被 `reset_in_place` 清掉 —— **逐字段**，
    /// 不是"按规范哈希文本相等"。
    ///
    /// 为什么不能复用上面那条：`reset_in_place_matches_new_field_for_field` 比的是
    /// `canonical_text`，而 `vacated_seat` / `gold_carried_away` / `ascension` **都不在
    /// `snapshot.rs` 里**（参考实现没有这三个字段）⇒ 它们脏着也照样"逐字段等价"。名字里的
    /// "field for field" 因此是假的，而且会继续放过下一个新字段。
    ///
    /// 后果不是学术性的：`gold_carried_away` 被 `apply_fight_outcome` 用来 `adjust_gold(-n)`
    /// （`rd-wasm/src/run.rs:3491`），复用一份脏状态下一次结算时会**重复扣**一笔被偷的金币。
    #[test]
    fn reset_in_place_also_clears_the_three_scalars_the_hash_text_cannot_see() {
        let mut state = CombatState::new(CombatId::new("dirty").unwrap(), 7);
        state.vacated_seat = Some(3);
        state.gold_carried_away = 40;
        state.set_ascension(20);

        state.reset_in_place(CombatId::new("clean").unwrap(), 9);

        assert_eq!(state.vacated_seat, None, "no seat is left vacant by the previous fight");
        assert_eq!(state.gold_carried_away, 0, "and no gold walks into the next one");
        assert_eq!(state.ascension(), 0, "the run layer sets the level afterwards");
        // 成对：这三个字段确实进过状态（否则上面三行可能只是在比两份默认值）。
        let mut fresh = CombatState::new(CombatId::new("dirty").unwrap(), 7);
        fresh.vacated_seat = Some(3);
        fresh.gold_carried_away = 40;
        fresh.set_ascension(20);
        assert_eq!(fresh.vacated_seat, Some(3));
        assert_eq!(fresh.gold_carried_away, 40);
        assert_eq!(fresh.ascension(), 20);
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
                from_card: false,
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
                    source_card: None,
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



