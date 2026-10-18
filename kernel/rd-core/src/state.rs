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
//! | combatants (12 x 3,872) | 46,464 |
//! | piles (12 x 1,392) | 16,704 |
//! | **`size_of::<CombatState>()`** | **184,648 (180 KiB)** |
//!
//! ⚠️ 这张表是**实测量出来的**，不是估的；每次改 `CombatState` 的字段都要重新量并把这里改掉，
//! 否则它就会变成一句谎（`state_fits_the_sram_plan` 只盯着上界，盯不住"表格里的数字过期"）。
//! 最近一次变化：`StatusInstance` 加了 `source_combatant_id: Option<CombatantId>`
//! （DoT 要能归属出手方，见 `port-plan` §41.4），**171,848 → 184,648 B（+12.8 KB）**。
//! 原因是 `Option<CombatantId>` = **42 B**（`Ident<40>` 是 41 B 且没有 niche，`Option` 多一个 tag），
//! 乘上约 300 个状态槽。SRAM 占比 28.3% → **30.5%**。
//!
//! That is 30.5% of the P4's 592 KiB of SRAM in the worst case, and about 6x the reference's *packed*
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
    pub next_status_instance_number: i32,
    pub next_card_instance_number: i32,
    pub next_effect_chain_number: i64,
    pub next_program_execution_id: i64,
    turn_order: Bounded<CombatantId, MAX_COMBATANTS>,
    combatants: Bounded<Combatant, MAX_COMBATANTS>,
    global_statuses: Bounded<StatusInstance, MAX_GLOBAL_STATUSES>,
    card_zones: Bounded<CardZones, MAX_COMBATANTS>,
    cards: Bounded<CardInstance, MAX_CARD_INSTANCES>,
    temporary_rules: Bounded<TemporaryRule, MAX_TEMPORARY_RULES>,
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
        next_status_instance_number: 0,
        next_card_instance_number: 0,
        next_effect_chain_number: 0,
        next_program_execution_id: 0,
        turn_order: Bounded::new(),
        combatants: Bounded::new(),
        global_statuses: Bounded::new(),
        card_zones: Bounded::new(),
        cards: Bounded::new(),
        temporary_rules: Bounded::new(),
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
            next_status_instance_number: 0,
            next_card_instance_number: 0,
            next_effect_chain_number: 0,
            next_program_execution_id: 0,
            turn_order: Bounded::new(),
            combatants: Bounded::new(),
            global_statuses: Bounded::new(),
            card_zones: Bounded::new(),
            cards: Bounded::new(),
            temporary_rules: Bounded::new(),
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
        assert!(
            size <= 192 * 1024,
            "CombatState grew to {size} bytes, past the 192 KB ceiling this model was sized for"
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
}
