//! 一步之内的**有序动画事件**（`port-plan.md` §142）。
//!
//! # 为什么不能靠观察向量相减
//!
//! 页面到今天为止是从 `diffObservations(before, after)` **反推**"刚才发生了什么"的。那对
//! "还剩几点血"够用，对动画不够 —— 敌人 7×3 的多段攻击减完只有"掉了 21 血"，
//! **分不出三段**；"先加格挡再挨打"和"先挨打再加格挡"两种顺序减出同一个向量。
//! 相减丢掉的是**顺序与分段**，而这两样恰好是动画的全部输入。
//!
//! 所以这里记的是**已经落地的事实**，不是请求、不是待分发事件：每一条都在效果真正
//! 写进状态的那一行动手（见下表），因此顺序 = 实际发生的顺序。
//!
//! # 它与 `pending_events` 不是一回事
//!
//! `CombatEvent`（`state.rs`）是参考的**触发器**事件：它驱动内容里的状态钩子，而
//! "加了 5 点格挡""回了 8 点血""抽了 2 张牌"这三种事实**根本没有对应的事件变体**
//! （参考自己也不为它们发事件）。所以动画日志只能单开一本账，不能从事件队列里捞。
//!
//! # 埋点：每条都只有一个写点
//!
//! | 事实 | 写点 |
//! |---|---|
//! | 掉血 | `exec::resolve_damage_of_kind`（伤害管线的**唯一出口**，卡/DoT/药水都走它）|
//! | 格挡 | `exec::gain_block_for` |
//! | 治疗 | `exec::heal_for` |
//! | 状态增减 / 被 Artifact 挡下 | `exec::apply_one_status`、`exec::modify_one_status_stacks`、`exec::push_new_status` 的删除点 |
//! | 倒下 / 随从逃跑 | 同一处（`lifecycle_state` 翻转的那一行）|
//! | 出牌 | `play::play_card` 的 `CardPlayed` 入队点 |
//! | 回合边界 | `host` 的三个 `enqueue_event_at_root`（TurnStarted / TurnEnded）|
//! | 召唤 | `exec::create_combatant_node` |
//!
//! ⚠️ **一个事实一个写点**。两处都写 = 同一次掉血在动画里播两遍，而那**不会**让任何测试
//! 变红 —— 除非测试数条数。所以本模块的测试数的是 `beats().len()`，不是"有没有某条"。
//!
//! # 容量与"满了怎么办"
//!
//! 日志是**派生视图**，不是游戏状态：它满不会改变任何一个局面的后续行为，所以它
//! **不该**像六条事件队列那样"到顶就响亮失败"（那会把一次出牌变成错误）。
//! 但它也**不许静默丢**：满了就把 [`CombatState::beats_dropped`] 加一，页面能读到并说
//! 出来。这正是本项目对"工具骗人"的一贯要求 —— 少报了要能看见。
//!
//! 64 条的上限是**量出来的**，不是猜的：`exec::tests::a_heavy_turn_fits_in_the_log` 在一步里
//! 打 5x3 段伤害 + 一块 + 两状态（18 条），断言 `beats_dropped() == 0`。

use crate::state::{CombatantId, CombatState, Empty, Ident, ID_CAP};

/// 一步最多留多少条。见模块头"容量与满了怎么办"。
pub const MAX_BEATS: usize = 64;

/// 一步最多留多少个**定义名**（状态定义 / 卡牌定义）。
///
/// 名字走旁表而不是塞进 [`Beat`]：`Ident<40>` 是 41 B，塞进每条就是 2.6 KB；而一步里
/// 真正被点到的名字通常不到五个。
pub const MAX_BEAT_DEFS: usize = 24;

/// `actor` / `target` 的"没有人"。
pub const NOBODY: u8 = u8::MAX;

/// `def` 的"没有名字"。
pub const NO_DEF: u8 = u8::MAX;

/// 一条动画事件的种类。
///
/// 数值是 **ABI 值**（`rd_env_beat_field` 的 `kind` 列），已经发给页面，**不要重排**：
/// 新种类往后加，删掉一个就让它的号空着。
#[repr(u8)]
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum BeatKind {
    /// 掉血。`a` = 实际掉血、`b` = 被防御池吸收、`c` = 请求额（修饰后）。
    /// `flags` 的 bit0 = 痛伤（DoT tick）而不是直接伤害。
    Damage = 1,
    /// 加了格挡。`a` = 实际加了（修饰后、可能为 0 就没这条）。
    Block = 2,
    /// 回了血。`a` = 实际回的血（受上限约束后的真值）。
    Heal = 3,
    /// 状态层数变了。`a` = **净变化**（可负）、`def` = 状态定义、
    /// `flags` 的 bit0 = 这一次是**新建实例**（否则是并入/改层）。
    StatusChanged = 4,
    /// 一条状态实例没了（层数归零被删 / 到期）。`def` = 状态定义。
    StatusRemoved = 5,
    /// 一次 debuff 被 Artifact 挡下。`def` = 被挡下的状态定义。
    StatusPrevented = 6,
    /// 某个战斗员倒下了。`actor` = 送他上路的人（可无）。
    Downed = 7,
    /// 随从在主人倒下后逃跑（§139）。`target` = 逃跑的那个。
    Escaped = 8,
    /// 出了一张牌。`def` = 卡牌定义、`actor` = 出牌的人。
    CardPlayed = 9,
    /// 谁的回合开始了。
    TurnStarted = 10,
    /// 谁的回合结束了。
    TurnEnded = 11,
    /// 造了一个战斗员（分裂 / 召唤）。`target` = 新人的 **ordinal**、`def` = 定义。
    Summoned = 12,
}

impl BeatKind {
    /// 把 ABI 里的数字读回枚举（本模块内部与测试用）。
    #[must_use]
    pub fn from_code(code: i32) -> Option<Self> {
        Some(match code {
            1 => Self::Damage,
            2 => Self::Block,
            3 => Self::Heal,
            4 => Self::StatusChanged,
            5 => Self::StatusRemoved,
            6 => Self::StatusPrevented,
            7 => Self::Downed,
            8 => Self::Escaped,
            9 => Self::CardPlayed,
            10 => Self::TurnStarted,
            11 => Self::TurnEnded,
            12 => Self::Summoned,
            _ => return None,
        })
    }
}

/// `StatusChanged.flags` / `Damage.flags` 的位。
pub const FLAG_DOT: u8 = 1 << 0;
/// 这一次是**新建**状态实例（否则是并入已有实例 / 改层数）。
pub const FLAG_NEW_INSTANCE: u8 = 1 << 1;

/// 一条动画事件。
///
/// `actor` / `target` 是 **`state.combatants()` 的下标**（`ordinal`），不是墙位：
/// 墙位（英雄 = -1、敌人 0..5）是 `rd-wasm` 的事情，内核不知道墙有几格。
/// `NOBODY` = 没有这一方（例如无来源的 DoT）。
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Beat {
    /// 种类。
    pub kind: BeatKind,
    /// 出手方 / 主体。
    pub actor: u8,
    /// 承受方。
    pub target: u8,
    /// 旁表下标（`NO_DEF` = 没有名字）。
    pub def: u8,
    /// 位标记，见 [`FLAG_DOT`] / [`FLAG_NEW_INSTANCE`]。
    pub flags: u8,
    /// 第一个数（含义见 [`BeatKind`]）。
    pub a: i32,
    /// 第二个数。
    pub b: i32,
    /// 第三个数。
    pub c: i32,
}

impl Empty for Beat {
    /// 空槽 = 一条"谁都不是"的 `TurnStarted`。它**不会被读**：读出走 `len`，
    /// 而 `len` 之后不会有条目。
    const EMPTY: Self = Self {
        kind: BeatKind::TurnStarted,
        actor: NOBODY,
        target: NOBODY,
        def: NO_DEF,
        flags: 0,
        a: 0,
        b: 0,
        c: 0,
    };
}

impl core::fmt::Debug for Beat {
    // 无分配：`no_std` 里没有 `format!`，所以 `None`/`Some` 直接交给格式化器。
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(
            f,
            "{:?}({:?}->{:?} def={:?} flags={:#04b} a={} b={} c={})",
            self.kind,
            if self.actor == NOBODY {
                None
            } else {
                Some(self.actor)
            },
            if self.target == NOBODY {
                None
            } else {
                Some(self.target)
            },
            if self.def == NO_DEF {
                None
            } else {
                Some(self.def)
            },
            self.flags,
            self.a,
            self.b,
            self.c
        )
    }
}

/// 一本**每一步**都被清空的动画日志。
#[derive(Clone, Copy)]
pub struct BeatLog {
    list: [Beat; MAX_BEATS],
    len: u8,
    defs: [Ident<ID_CAP>; MAX_BEAT_DEFS],
    defs_len: u8,
    /// 被容量拒掉的条目数（条 + 名字）。**永远会报出来**，见模块头。
    dropped: u16,
}

impl BeatLog {
    /// 空账本。
    #[must_use]
    pub const fn new() -> Self {
        Self {
            list: [Beat::EMPTY; MAX_BEATS],
            len: 0,
            defs: [Ident::EMPTY; MAX_BEAT_DEFS],
            defs_len: 0,
            dropped: 0,
        }
    }

    /// 已经记了几条。
    #[must_use]
    pub fn len(&self) -> usize {
        usize::from(self.len)
    }

    /// 是否一条都没有。
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    /// 条目切片。
    #[must_use]
    pub fn beats(&self) -> &[Beat] {
        &self.list[..usize::from(self.len)]
    }

    /// 被拒掉的条目数。
    #[must_use]
    pub fn dropped(&self) -> u16 {
        self.dropped
    }

    /// 旁表里的第 `index` 个名字。
    #[must_use]
    pub fn def(&self, index: u8) -> Option<&Ident<ID_CAP>> {
        if index == NO_DEF || usize::from(index) >= usize::from(self.defs_len) {
            return None;
        }
        self.defs.get(usize::from(index))
    }

    /// 清空（**整块**写回空值，不只是把 `len` 归零 —— 与 `Fifo::clear` 同一条不变式）。
    pub fn clear(&mut self) {
        self.list = [Beat::EMPTY; MAX_BEATS];
        self.len = 0;
        self.defs = [Ident::EMPTY; MAX_BEAT_DEFS];
        self.defs_len = 0;
        self.dropped = 0;
    }

    /// 记一条。满了就**加一个丢条计数**，不静默、也不报错。
    pub fn push(&mut self, beat: Beat) {
        if usize::from(self.len) == MAX_BEATS {
            self.dropped = self.dropped.saturating_add(1);
            return;
        }
        if let Some(slot) = self.list.get_mut(usize::from(self.len)) {
            *slot = beat;
            self.len += 1;
        } else {
            // 不可达：上面已经查过上限。留着是为了不写 `unwrap`。
            self.dropped = self.dropped.saturating_add(1);
        }
    }

    /// 把一个名字放进旁表，返回它的下标（放不下就是 `NO_DEF` + 丢条计数）。
    pub fn intern(&mut self, text: &str) -> u8 {
        for index in 0..usize::from(self.defs_len) {
            if self.defs.get(index).map(Ident::as_str) == Some(text) {
                return index as u8;
            }
        }
        if usize::from(self.defs_len) == MAX_BEAT_DEFS {
            self.dropped = self.dropped.saturating_add(1);
            return NO_DEF;
        }
        let Ok(ident) = Ident::<ID_CAP>::new(text) else {
            // 不可达：进来的都是已经被 `Ident<ID_CAP>` 校验过的定义 id。
            self.dropped = self.dropped.saturating_add(1);
            return NO_DEF;
        };
        if let Some(slot) = self.defs.get_mut(usize::from(self.defs_len)) {
            *slot = ident;
            self.defs_len += 1;
            (self.defs_len - 1) as u8
        } else {
            self.dropped = self.dropped.saturating_add(1);
            NO_DEF
        }
    }
}

impl Empty for BeatLog {
    const EMPTY: Self = Self::new();
}

impl Default for BeatLog {
    fn default() -> Self {
        Self::new()
    }
}

impl core::fmt::Debug for BeatLog {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_list().entries(self.beats()).finish()
    }
}

// ---------------------------------------------------------------------------------------------
// CombatState 上的读接口 + 写点的三个小工具
// ---------------------------------------------------------------------------------------------

impl CombatState {
    /// 一步之内的有序事实（见模块头）。
    #[must_use]
    pub fn beats(&self) -> &[Beat] {
        self.beat_log().beats()
    }

    /// 被容量拒掉的条目数（`0` = 这一步一条都没丢）。
    #[must_use]
    pub fn beats_dropped(&self) -> u16 {
        self.beat_log().dropped()
    }

    /// 第 `beat` 条的名字（状态定义 / 卡牌定义）。
    #[must_use]
    pub fn beat_def_text(&self, beat: usize) -> Option<&str> {
        let entry = self.beats().get(beat)?;
        self.beat_log().def(entry.def).map(Ident::as_str)
    }

    /// 清空日志。**每一步**在动作入口调用（`rd_env_step` / `rd_env_use_potion` / 开局）。
    pub fn clear_beats(&mut self) {
        self.beat_log_mut().clear();
    }
}

/// 一个战斗员在 `state.combatants()` 里的下标（`NOBODY` = 不在场）。
///
/// ⚠️ 这是**下标**不是 id：同一个 `CombatantId` 在整场里下标不变（数组只追加），
/// 而 id 是 41 B —— 一条动画事件不该为它付 82 B。
#[must_use]
pub fn ordinal_of(state: &CombatState, id: &CombatantId) -> u8 {
    for (index, combatant) in state.combatants().iter().enumerate() {
        if combatant.id == *id {
            return index.min(usize::from(NOBODY) - 1) as u8;
        }
    }
    NOBODY
}

/// 把一个已经定好的定义名记进旁表（写点用）。
pub fn intern_def(state: &mut CombatState, text: &str) -> u8 {
    state.beat_log_mut().intern(text)
}

/// 记一条（写点用）。满了只加丢条计数。
pub fn record(state: &mut CombatState, beat: Beat) {
    state.beat_log_mut().push(beat);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::{CombatId, StatusDefinitionId};

    #[test]
    fn a_fresh_log_is_empty_and_shares_nothing() {
        let log = BeatLog::new();
        assert!(log.is_empty());
        assert_eq!(log.len(), 0);
        assert_eq!(log.dropped(), 0);
        assert!(log.def(NO_DEF).is_none());
    }

    #[test]
    fn the_log_keeps_order_and_never_drops_below_capacity() {
        let mut log = BeatLog::new();
        for index in 0..MAX_BEATS {
            log.push(Beat {
                kind: BeatKind::Damage,
                actor: 0,
                target: 1,
                def: NO_DEF,
                flags: 0,
                a: index as i32,
                b: 0,
                c: 0,
            });
        }
        assert_eq!(log.len(), MAX_BEATS);
        assert_eq!(log.dropped(), 0, "装得下就不该丢");
        // 顺序：第 i 条的 `a` 就是 i。
        for (index, beat) in log.beats().iter().enumerate() {
            assert_eq!(beat.a, index as i32);
        }
        // 第 65 条：加丢条计数，**不覆盖**已有条目。
        log.push(Beat::EMPTY);
        assert_eq!(log.len(), MAX_BEATS);
        assert_eq!(log.dropped(), 1, "满了必须能被看见");
        assert_eq!(log.beats()[0].a, 0, "满了不许覆盖第一条");
    }

    #[test]
    fn the_def_table_is_a_side_table_not_a_copy_per_beat() {
        let mut log = BeatLog::new();
        let first = log.intern("standard.vulnerable");
        let again = log.intern("standard.vulnerable");
        let other = log.intern("standard.weak");
        assert_eq!(first, again, "同名必须复用同一格");
        assert_ne!(first, other);
        assert_eq!(log.def(first).map(Ident::as_str), Some("standard.vulnerable"));
        assert_eq!(log.def(other).map(Ident::as_str), Some("standard.weak"));
        assert!(log.def(7).is_none(), "没进过表的下标读不到名字");

        // 旁表满了 ⇒ `NO_DEF` + 丢条计数，**不是**静默截断。
        let mut full = BeatLog::new();
        for index in 0..MAX_BEAT_DEFS {
            assert_ne!(full.intern(&std::format!("status_{index}")), NO_DEF);
        }
        assert_eq!(full.intern("one_too_many"), NO_DEF);
        assert_eq!(full.dropped(), 1);
    }

    #[test]
    fn clear_wipes_the_names_too() {
        let mut log = BeatLog::new();
        log.intern("standard.vulnerable");
        log.push(Beat::EMPTY);
        log.push(Beat::EMPTY);
        log.clear();
        assert!(log.is_empty());
        assert_eq!(log.dropped(), 0);
        assert!(log.def(0).is_none(), "清空必须连旁表一起清");
        // 清完之后重新 intern，仍然从 0 开始。
        assert_eq!(log.intern("standard.weak"), 0);
    }

    #[test]
    fn every_beat_kind_round_trips_through_its_abi_code() {
        // 反过来也守：`from_code` 只认已发布的那几个号，新加的必须同时进两边。
        for kind in [
            BeatKind::Damage,
            BeatKind::Block,
            BeatKind::Heal,
            BeatKind::StatusChanged,
            BeatKind::StatusRemoved,
            BeatKind::StatusPrevented,
            BeatKind::Downed,
            BeatKind::Escaped,
            BeatKind::CardPlayed,
            BeatKind::TurnStarted,
            BeatKind::TurnEnded,
            BeatKind::Summoned,
        ] {
            assert_eq!(BeatKind::from_code(kind as i32), Some(kind));
        }
        assert_eq!(BeatKind::from_code(0), None);
        assert_eq!(BeatKind::from_code(13), None, "13 号还没发布");
    }

    #[test]
    fn the_ordinal_is_the_index_in_combatants_not_the_id() {
        // `StatusDefinitionId` 只是为了让 `use` 不空转：这条测试关心的是 `ordinal_of`
        // 对"不在场"的回答，而"在场"的那一半由 `exec`/`play` 的埋点测试覆盖。
        let state = CombatState::new(CombatId::EMPTY, 0);
        assert_eq!(ordinal_of(&state, &CombatantId::EMPTY), NOBODY);
        assert!(StatusDefinitionId::new("x").is_ok());
    }
}
