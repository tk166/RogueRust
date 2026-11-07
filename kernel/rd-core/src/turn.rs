//! 回合状态机（`CombatTurnProcessor`）—— 叶子模块 W3c。
//!
//! 规格：`docs/spec/combat-state-and-turn.md` §3.1（轮转模式）。
//! 参考实现：`RogueDeck.Core/Combat/CombatTurnProcessor.cs:7-212`。
//!
//! ## 为什么这个模块能把"效果"切出去
//!
//! 回合机的职责是**什么时候**；效果做什么是**另一个模块**的事。参考实现两者是缠在一起的
//! （事件处理器既推进回合又解析效果），但它们的接缝很清楚：标准的 turn-start 处理器序列是
//! **固定顺序**的七步，其中四步需要效果系统，三步不需要：
//!
//! | # | 处理器 | 谁做 |
//! |---|---|---|
//! | 1 | `ResetCardPlayTurnStats` | ⚠️ **本内核没有每回合出牌统计**（见下） |
//! | 2 | `RefillResource(energy, 3)` | **本模块**（只读 `TurnConfig`） |
//! | 3 | `ActivatePendingStatuses` | 宿主 |
//! | 4 | turn-start 触发程序 | 宿主 |
//! | 5 | **`ResolveQueue`**（`ResolveOldest` 全部） | 宿主 |
//! | 6 | `DrawCards(5)` | **本模块**（就是 `draw_card` 循环） |
//! | 7 | `ClearBlock` | **本模块** |
//! | — | `DamageOverTime` | 宿主 |
//!
//! **顺序是规格的一部分，不是实现细节**：补能量 → 触发器 → **队列** → 抽牌 → 清 Block。
//! 队列卡的效果**一定发生在手牌到来之前**；清 Block 排在队列解析**之后**，
//! 所以队列里的 `gainBlock` 能活到它被排队的那一回合（`S:QueueTortureTests.cs:210-212` 断言 11 点 Block 存活）。
//!
//! ⚠️ **但"清不清"是在回合入口判定的，不是在第 7 步判定的**（2026-10-17 修，见
//! [`clear_turn_start_pool`]）：参考的清空请求在**处理器时点**采样 `pool.Current <= 0`
//! （`DefensivePoolEffects.cs:305`）就决定要不要入队，而那一刻本回合的**任何效果都还没生效**。
//! 把判定挪到第 7 步会让"回合末格挡=0 + 队列卡 +11"这一格从 11 变成 0 —— 那是一个
//! 能构造出来、却一直被写反的注释掩盖着的真分歧。
//!
//! ## 冻结契约
//!
//! 1. **每一步的可观察副作用顺序不可换**（见上表）。
//! 2. `start_current_turn` 在 `TurnPhase != WaitingToStartTurn` 时返回 `AlreadyInProgress`
//!    —— 参考实现是**抛**（`CombatState.cs:324-330`），`T:CombatTurnProcessorTests.cs:26-36` 钉住"Start 不能连调两次"。
//! 3. `end_current_turn` 在 `TurnPhase != TurnInProgress` 时返回 `NotInProgress`
//!    （`T:CombatTurnProcessorTests.cs:39-47`：未 Start 就 End 抛）。
//! 4. 任何一步之后 `result != Ongoing` ⇒ **立刻停**，不推进回合（`CombatTurnProcessor.cs:44`）。
//! 5. 绕回判定用**下标**而不是 id：`nxt <= cur` 即新一轮（`:185`）。
//! 6. `AdvanceTurn` / `AdvanceRound` 只移除**已到期**的临时规则（`CombatState.cs:572-592`）——
//!    没有到期字段的规则**活过**边界。⚠️ 本契约原先写的是"都清空"，那是**错的**，
//!    W3c 交付时如实指出了这一点（`tr=` 行是哈希可见的，所以这不是风格差异）。
//!    现在改用 `CombatState::expire_temporary_rules_at_{turn,round}_boundary`。
//! 7. 推进时跳过已倒下的：`while !Active.IsAlive`，且有 `guard <= TurnOrder.Count` 的循环上限；
//!    一个活人都没有时返回 `NoLivingCombatants`（参考是抛 `"no living combatants in the turn order"`）。
//!
//! ## `TurnHost` 是"效果系统还没做"这件事的正规表达
//!
//! 效果程序解释器（`effect-program-ir.md` 的 §3）是整个移植最大的一块，尚未实现。
//! 与其让回合机假装能解析效果，不如**把接缝显式化**：宿主 trait 上那七步里的效果步骤就是那些
//! 方法。`NullHost` 是全空实现，于是回合机**今天就能被测试** —— 测的是它自己的职责
//! （阶段流转、轮次推进、能量补充、抽牌、清 Block、弃手牌），而不是别人的。
//!
//! trait 上还挂着一组**带默认实现**的策略方法（`on_round_ended` / `block_is_retained` /
//! `turn_start_draw_count` / `unspent_energy_carries` …）。默认值 = "标准包在这一步什么都不
//! 额外做"，所以默认路径与参考的默认路径一致，而带相应法令/标记的内容可以覆盖它们。

use crate::state::{
    CapacityError, CardSlot, CardZone, CombatResult, CombatTurnPhase, CombatantId,
    CombatantLifecycleState, CombatState, Container, DefensivePoolId, ResourceId, ZonePlacement,
    MAX_CARDS_PER_ZONE,
};

/// 回合机自己需要知道的数字。它们来自内容（标准包 = 能量 3 / 抽 5），不是硬编码在引擎里。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TurnConfig {
    /// 每回合补充的资源（标准包 = `standard.energy`）。
    pub energy: ResourceId,
    /// 补到多少（标准包 = 3）。**默认是"补到"不是"加"** —— 参考实现 refill 到 `Max ?? 常量`。
    /// 只有当宿主说 `unspent_energy_carries`（`UnspentResourceCarries` 法令）时才变成"加"
    /// （`ResourceEffects.cs:84-96`）。
    pub energy_refill: i32,
    /// 每回合抽几张的**基值**（标准包 = 5）。真正抽多少还要过
    /// `host.turn_start_draw_count`（`TurnStartDraw` 修饰流水线）与 `max_hand_size` 的入口裁剪。
    pub draw_per_turn: i32,
    /// 回合开始清空的那个防御池（标准包 = `standard.block`）。
    pub block_pool: DefensivePoolId,
    /// `MaxHandSize` 法令的上限；没有该法令时给 `i32::MAX`（抽牌入口按它裁剪 `wanted`）。
    pub max_hand_size: i32,
}

/// 回合机的拒绝理由。**前八个全部来自参考实现里真实存在的断言**，不是自创的；
/// [`Self::Host`] 是本内核多出来的一条接缝（见它的文档）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TurnError {
    /// `result != Ongoing`（`CombatTurnProcessor.cs:120-125`）。
    NotOngoing,
    /// 已经在回合中，不能重复 Start（`CombatState.cs:324-330`）。
    AlreadyInProgress,
    /// 不在回合中，不能 End（`CombatState.cs:332-338`）。
    NotInProgress,
    /// `TurnOrder` 为空（`:139-168`）。
    NoTurnOrder,
    /// 没有活跃单位。
    NoActiveCombatant,
    /// 活跃单位不在 `TurnOrder` 里（`:139-168`）。
    ActiveNotInTurnOrder,
    /// 活跃单位已倒下（`:127-137`）。
    ActiveNotAlive,
    /// 转了一圈也没找到活人（`:192`）。
    NoLivingCombatants,
    /// 底层定容容器满了。
    Capacity(CapacityError),
    /// **宿主没做完它那一半**（一个 `TurnHost` 钩子拒绝了）。
    ///
    /// 这条**不是**参考实现的形状，而是本内核的接缝：参考那边效果处理器是从
    /// `ResolvePendingQueues` 里直接抛异常出去的，`CombatTurnProcessor` 自己的四个
    /// `Ensure*` 才对应上面那八个。内核不能抛，所以必须有变体接住它。
    ///
    /// ⚠️ **这个变体是 2026-10-17 补的，理由是前一个版本骗人**：宿主失败当时被借用
    /// `Capacity(Full(Container::Statuses))` 表达 —— 而 `Full` 的字面意思是"容器满了"。
    /// 读到它的人会去找哪个状态容器溢出了，而真相可能是"镜像里的触发器读不出来"或
    /// "内核缺少某个表达式"。**一个错的定位方向比一句"失败了"更贵**，所以类别必须分开。
    ///
    /// 载荷只有**类别**：`host::HostError` 有五个变体、还带细节载荷（哪个串不认识、
    /// `IrError` 是什么），把它整个搬进来会让 `turn.rs` 依赖效果层的错误类型，
    /// 而 `TurnError` 要保持 `Copy`、零依赖、能在裸机上值传递。细节在
    /// `host::Host::last_failure()`（宿主自己保管，不会丢）。
    Host(HostFailure),
}

/// [`TurnError::Host`] 的载荷：**宿主失败的类别**。
///
/// 只有三种，但这三种的**排查方向完全相反**，这就是把它做成枚举而不是
/// `&'static str` 的全部理由（字符串要靠约定，枚举靠编译器）：
///
/// * [`Self::Unsupported`] ⇒ **我们去补**（内容是对的，内核还没做到）；
/// * [`Self::Content`] ⇒ **内容去改**（内核没错，镜像/数据配错了）；
/// * [`Self::Effect`] ⇒ **效果层出错**（节目 fault；`exec` / `status_bind` 的细分在
///   `host::HostError` 里）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HostFailure {
    /// 内核缺能力：内容用到了 v1 没实现的那条路。
    Unsupported,
    /// 内容配错了：镜像里的结构读不出来，或者串表示不了。
    Content,
    /// 效果执行失败（节目 fault、越界、步数用尽……）。
    Effect,
}

impl From<CapacityError> for TurnError {
    fn from(e: CapacityError) -> Self {
        TurnError::Capacity(e)
    }
}

/// 效果系统在回合机四个点上的接缝。**实现这个 trait 就等于实现那四步。**
pub trait TurnHost {
    /// §282：`Confusion` 的重掷需要**内容**（豁免按 tag 判）。trait 上给一个默认实现
    /// （`None` ⇒ 不重掷），由 `Host` 覆写成真的内容 —— 不覆写就是"回合开始的牌不重掷"，
    /// 而那有判据（`confusion_randomizes_the_cost_of_every_drawn_card` 的第二半）。
    ///
    /// 为什么不是"把 content 塞进 `CombatState`"：`CombatState` 是**局面**（进指纹、要可复制），
    /// 而内容是只读的外部表；两者混在一起会让快照语义变糊。
    fn confusion_content(&self) -> Option<&crate::content::Content<'_>> {
        None
    }

    /// turn-start 处理器 #3：`pending_turns--`，归零的转正（`StatusEffects.cs:409`）。
    fn activate_pending_statuses(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError>;

    /// turn-start 处理器 #4：全部 turn-start 触发程序，按 `(priority, id)` 序
    /// （`TriggeredProgramDefinition.cs:78`）。
    fn run_turn_started_triggers(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError>;

    /// turn-start 处理器 #5：**卡牌队列**（`Cards/QueueResolution.cs:133-137`，
    /// `ResolveOldest(owner, int.MaxValue)`）。
    ///
    /// ⚠️ 这个钩子是 2026-10-17 补的，理由值得记：在那之前，第 5 步只调
    /// [`Self::resolve_pending_queues`]，而那个方法的文档说的是"**任何**入队之后的排空"
    /// （效果 / 事件 / 续延三队列）。两件事在参考里是**不同的处理器**，混在一个钩子里
    /// 的后果是：宿主照文档实现（只排空效果队列，而效果队列恒空），就**没有任何钩子
    /// 会把 `CardZone::QueuePile` 里的牌解析掉** —— 队列卡永久滞留，`cz=` 行永久不同，
    /// `counter` 那种"每张队列牌 +3 伤害"的卡一直算错，而且**不报错**。
    ///
    /// 所以它是**必做**方法，没有默认实现：默认实现（什么都不做）正是那个静默洞本身。
    fn resolve_card_queue(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError>;

    /// **任何**入队之后的排空（`CombatEventHandling.cs:81-115`）。
    /// 回合机在五个位置调它：TurnStarted 之后、TurnEnded 之后、Advance 之后各一次，
    /// 以及跳过倒下单位时的每一轮。
    ///
    /// ⚠️ 它**不**负责解析 `CardZone::QueuePile` —— 那是 [`Self::resolve_card_queue`]。
    fn resolve_pending_queues(&mut self, state: &mut CombatState) -> Result<(), TurnError>;

    /// turn-start 最后一步：DoT 结算（`StandardCombatPackage.cs:139`）。
    fn damage_over_time(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError>;

    /// turn-end：牌在手里过回合的**生命周期节目**（`CardLifecyclePrograms.cs:21-46`）。
    ///
    /// ⚠️ 2026-10-19 更正：这里原来写的是 `CardTurnLifecycleEventHandlers.cs` —— 那是弃手牌
    /// 与抽牌的文件；生命周期节目（Burn/Decay 的机制）在 `CardLifecyclePrograms.cs`。
    /// 真实实现见 `host::try_hand_turn_end_lifecycle`（镜像 62/62 卡是 `{}` ⇒ 今天恒空转）。
    fn hand_turn_end_lifecycle(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError>;

    /// turn-end：触发程序。
    fn run_turn_ended_triggers(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError>;

    /// turn-end：按时长的状态减 1（`StatusEffects.cs:390-404`）。
    fn decrease_timed_statuses(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError>;

    /// 手牌是否因 `standard.retained_card` 之类的标记而**不被**回合末弃掉。
    /// 默认 `false`。做成宿主回调是因为"哪些标记保留手牌"是**内容**决定的。
    fn hand_is_retained(&self, state: &CombatState, actor: &CombatantId) -> bool;

    // ── 下面这些**全部带默认实现** ──────────────────────────────────────────────────────────────
    //
    // 加它们是为了给 W3c 交付时如实报出的那几个缺口补上接缝。默认实现 = "标准包在这一步
    // 什么都不额外做"，所以**已有的宿主和测试一行都不用改**，而需要这些语义的宿主可以覆盖。
    //
    // 默认实现不是"以后再实现"的托词：每一条的默认值都对应参考实现在**没有对应法令/标记/修饰器**
    // 时的行为，所以默认路径与参考的默认路径一致。

    /// 轮次边界：**旧轮结束**事件（`RoundEndedCombatEvent`，`CombatTurnProcessor.cs:186`）。
    ///
    /// 在 `current_round` 自增**之前**调用，参数是即将结束的那一轮。
    /// 宿主在这里做"回合/轮次边界的触发程序"—— 本方法就是那个入队点。
    fn on_round_ended(&mut self, state: &mut CombatState, ended_round: i32) -> Result<(), TurnError> {
        let _ = (state, ended_round);
        Ok(())
    }

    /// 轮次边界：**新轮开始**事件（`RoundStartedCombatEvent`，`:188`）。
    /// 在 `current_round` 自增**之后**调用，参数是新的那一轮。
    fn on_round_started(&mut self, state: &mut CombatState, new_round: i32) -> Result<(), TurnError> {
        let _ = (state, new_round);
        Ok(())
    }

    /// `standard.retain_block` 之类的标记是否让该单位的格挡**不被**回合开始清空
    /// （`DefensivePoolEffects.cs:294-314`）。默认 `false` = 必清。
    /// §197：一次性格挡保留的消耗（默认什么都不做 —— 只有带内容的那层知道 tag）。
    fn consume_one_shot_block_retainers(&mut self, _state: &mut CombatState, _actor: &CombatantId) {}

    fn block_is_retained(&self, state: &CombatState, actor: &CombatantId) -> bool {
        let _ = (state, actor);
        false
    }

    /// §261: **回合开始时留下多少格挡**（`Calipers`："失去 15 点格挡而不是全部"）。
    ///
    /// 与 [`Self::block_is_retained`] 是两个钩子，不是一个带参数的：`block_is_retained` 是
    /// **布尔**判定、"清不清"，参考在处理器时点就采样（那时本回合任何效果都还没生效）；
    /// 而"留多少"作用在**清空那一刻的实时值**上 —— "失去 15"说的就是此刻这 15 点。
    /// 一个布尔表达不了 `max(0, current - 15)`，硬塞进去会让那个时点语义跟着一起漂。
    ///
    /// 默认 0 = 一点不留（= 参考的 `ClearBlock`）。
    fn block_kept_at_turn_start(
        &self,
        state: &CombatState,
        actor: &CombatantId,
        live: i32,
    ) -> i32 {
        let _ = (state, actor, live);
        0
    }

    /// `TurnStartDraw` 修饰流水线后的抽牌张数（`CardTurnLifecycleEventHandlers.cs:25-31`）。
    /// 默认返回 `base`（= `TurnConfig::draw_per_turn` 原值）。
    ///
    /// ⚠️ 返回值仍然要过 `max_hand_size` 的**入口裁剪** —— 宿主不该自己去裁。
    fn turn_start_draw_count(&self, state: &CombatState, actor: &CombatantId, base: i32) -> i32 {
        let _ = (state, actor);
        base
    }

    /// §199：回合开始**补给多少能量**（`TurnStartEnergy` 管线之后的数）。默认 `base`。
    ///
    /// 判据与折叠全在 [`crate::exec::fold_turn_start_energy`]（复用 `exec.rs` 已经交付的候选表 +
    /// `crate::modifiers::apply`，**不另写一份折叠**）。
    fn turn_start_refill_count(&self, state: &CombatState, actor: &CombatantId, base: i32) -> i32 {
        let _ = (state, actor);
        base
    }

    /// 回合结束时这一张是否**留在手里**（`CardZoneEffects.cs:413-428` 的第 ①② 条：
    /// `standard.retained_card` 标记、或卡定义的 `RetainInHandOnTurnEnd`）。默认 `false`。
    fn card_stays_in_hand_at_turn_end(
        &self,
        state: &CombatState,
        actor: &CombatantId,
        slot: crate::state::CardSlot,
    ) -> bool {
        let _ = (state, actor, slot);
        false
    }

    /// 回合结束时这一张的**落点**（`TurnEndHandDestinationZone`，`CardZoneEffects.cs:413-428` 的第 ③ 条）。
    /// 默认 `DiscardPile`。返回 `Hand` 等价于"留在手里"。
    fn turn_end_hand_destination(
        &self,
        state: &CombatState,
        actor: &CombatantId,
        slot: crate::state::CardSlot,
    ) -> CardZone {
        let _ = (state, actor, slot);
        CardZone::DiscardPile
    }

    /// §220：一张牌**被抽到**（从抽牌堆进手牌）—— 跑它的 `LifecyclePrograms[Drawn]`。
    ///
    /// 默认什么都不做：只有知道内容的宿主（[`crate::host::Host`]）才有节目可跑。做成钩子而不是
    /// 写进 `move_card`，是因为"有没有节目"是**内容**知识，而状态层不该依赖效果队列/内容。
    fn card_drawn(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        slot: CardSlot,
    ) -> Result<(), TurnError> {
        let _ = (state, actor, slot);
        Ok(())
    }

    /// §220：一张牌**进了消耗堆**（虚无、打出即消耗、内容搬牌）—— 跑 `LifecyclePrograms[Exhausted]`。
    fn card_exhausted(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        slot: CardSlot,
    ) -> Result<(), TurnError> {
        let _ = (state, actor, slot);
        Ok(())
    }

    /// `UnspentResourceCarries` 法令：回合开始补能量时是"补到"还是"累加"
    /// （`ResourceEffects.cs:84-96`：`refillTarget = (Max ?? DefaultMax) + Current`，且允许超上限）。
    /// 默认 `false` = 补到。
    fn unspent_energy_carries(&self, state: &CombatState, actor: &CombatantId) -> bool {
        let _ = (state, actor);
        false
    }
}

/// 什么都不做的宿主。存在的意义：**让回合机今天就能被测试**。
///
/// ⚠️ 用它跑的测试**只覆盖回合机自己的职责**。任何"效果发生了没有"的断言都必须用真实的宿主，
/// 用 `NullHost` 去断言效果 = 断言"我什么都没做"，那种测试是空断言。
#[derive(Debug, Default)]
pub struct NullHost;

impl TurnHost for NullHost {
    fn activate_pending_statuses(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
        Ok(())
    }
    fn run_turn_started_triggers(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
        Ok(())
    }
            fn resolve_card_queue(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
    fn resolve_pending_queues(&mut self, _: &mut CombatState) -> Result<(), TurnError> {
        Ok(())
    }
    fn damage_over_time(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
        Ok(())
    }
    fn hand_turn_end_lifecycle(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
        Ok(())
    }
    fn run_turn_ended_triggers(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
        Ok(())
    }
    fn decrease_timed_statuses(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
        Ok(())
    }
    fn hand_is_retained(&self, _: &CombatState, _: &CombatantId) -> bool {
        false
    }
}

/// 存活判定。**用 `lifecycle_state == Alive`**，与参考的 `IsAlive` 同义
/// （`Alive` 是唯一的存活态；`Downed`/`Dead`/`Removed`/`Escaped`/`Banished` 都不是）。
#[must_use]
pub fn is_alive(state: &CombatState, id: &CombatantId) -> bool {
    state
        .combatant(id)
        .is_some_and(|c| c.lifecycle_state == CombatantLifecycleState::Alive)
}

// ---------------------------------------------------------------------------------------------
// The reference's four `Ensure*` primitives, as returned errors instead of thrown exceptions
// ---------------------------------------------------------------------------------------------

/// `EnsureCombatIsOngoing`（`CombatTurnProcessor.cs:120-125`）。
fn ensure_ongoing(state: &CombatState) -> Result<(), TurnError> {
    if state.result != CombatResult::Ongoing {
        return Err(TurnError::NotOngoing);
    }
    Ok(())
}

/// 冻结契约 #4：任何一步之后 `result != Ongoing` ⇒ **立刻停**。
///
/// 与参考实现的对应关系值得写清楚，因为两者形状不同、结果相同：C# 在 `CombatEventHandling.cs:62-63`
/// 用一个 `foreach` 跑完一个事件的**全部**处理器（不检查 `Result`），但队列解析的 while 条件里带着
/// `Result == Ongoing`（`:97`）⇒ 某个处理器在结果变成终态**之后**入队的请求永远不会被解析。
/// 本内核把"入队 + 解析"合并成一次同步调用，于是"入队了但永不解析"与"根本不调用"在可观察副作用上
/// 等价 —— 而后者正是契约 #4 要求的（`CombatTurnProcessor.cs:72-73` 是它在 turn-end 上的写法）。
fn stopped(state: &CombatState) -> bool {
    state.result != CombatResult::Ongoing
}

/// `EnsureActiveCombatantExistsInTurnOrder`（`CombatTurnProcessor.cs:139-168`），返回活跃单位。
///
/// ⚠️ 它**不是纯检查**：`ActiveCombatantId` 为空时，它把 `TurnOrder` 里第一个**存活**单位设为
/// 活跃单位（`:146-156`）。照抄 —— 一局的第一个回合就是靠这一步起步的。
fn ensure_active_combatant(state: &mut CombatState) -> Result<CombatantId, TurnError> {
    if state.turn_order().is_empty() {
        return Err(TurnError::NoTurnOrder);
    }

    if let Some(active) = state.active_combatant_id {
        if !state.turn_order().contains(&active) {
            return Err(TurnError::ActiveNotInTurnOrder);
        }
        if state.combatant(&active).is_none() {
            // `turn_order` 只装已存在的单位（`add_combatant` / `set_turn_order` 都保证这点），
            // 所以这一支今天不可达。留着是因为 C# 也查了（`:165-167`）："不可达的分支"与
            // "没写这个分支"是两件事，而它真要能触发，说明状态已经被写坏了。
            return Err(TurnError::NoActiveCombatant);
        }
        return Ok(active);
    }

    // §200: 席位刚被腾空（行动者在自己的回合里自毁）。这一支**不许**走下面那条"认领第一个
    // 活人" —— 那会把回合序从头开始，而正确的位置信息在 `vacated_seat` 里。正常出口是
    // `advance_to_next_combatant`；走到这里说明有人绕过了它，响亮失败好过静默重排。
    if state.vacated_seat.is_some() {
        return Err(TurnError::NoActiveCombatant);
    }

    // 没有活跃单位 ⇒ 认领回合序里第一个活人。`is_alive` 只读，两次不可变借用可以共存。
    match state
        .turn_order()
        .iter()
        .copied()
        .find(|id| is_alive(state, id))
    {
        Some(id) => {
            state.active_combatant_id = Some(id);
            Ok(id)
        }
        None => Err(TurnError::NoLivingCombatants),
    }
}

/// `EnsureActiveCombatantCanStartTurn`（`CombatTurnProcessor.cs:127-137`）。
fn ensure_active_can_start_turn(state: &mut CombatState) -> Result<CombatantId, TurnError> {
    let active = ensure_active_combatant(state)?;
    if !is_alive(state, &active) {
        return Err(TurnError::ActiveNotAlive);
    }
    Ok(active)
}

/// turn-start 处理器 #2：`RefillResourceOnTurnStartedHandler(energy, defaultMax)`
/// （注册在 `StandardCombatPackage.cs:124`；语义在 `Resources/ResourceEffects.cs:40-119`）。
///
/// 是**补到**不是**加**：目标 = `pool.Max ?? DefaultMax`（`:85`）。池不存在时**创建**它并令
/// `current = max = DefaultMax`（`:50-56`）。池存在时 **max 原样保留**（`None` 仍是 `None`，
/// 不因为补一次能量就凭空长出一个上限）。
///
/// `UnspentResourceCarries` 法令（`:87-96`）：`host.unspent_energy_carries` 为真时目标变成
/// `(Max ?? DefaultMax) + Current`，并且**允许超上限**（`:94` 的
/// `checked(refillTarget + previousCurrent)`，以及 `:96` 的
/// `SetCurrent(refillTarget, allowExceedingMax: carries)`）。`Pool::current` 本来就允许高于
/// `max`（规格 §2.5 的 overfill），所以这里**不动 max**、只把 current 写高。
///
/// 两处如实说明：
/// * **池不存在**时走创建分支，参考实现在那里**提前 return**，法令不参与（`:50-81`）—— 所以
///   `unspent_energy_carries` 在那条路上**不会被调用**，本函数也照此办理（不是漏调）。
/// * `checked` 在 C# 抛 `OverflowException`；内核没有对应的 `TurnError` 变体，
///   这里用 `saturating_add`（**有意偏离**，只在 `i32` 溢出的病态配置上可见）。
fn refill_resource<H: TurnHost>(
    state: &mut CombatState,
    actor: &CombatantId,
    config: &TurnConfig,
    host: &H,
) -> Result<(), TurnError> {
    let existing = state
        .combatant(actor)
        .and_then(|c| c.resources().iter().find(|p| p.key == config.energy).copied());

    // §199: the **base** the modifiers see is the configured refill (the pool's max when the pool
    // declares one, which is how `standard.energy 3/3` reads), and the pipeline's result is what the
    // resource is set to. Folding *before* `unspent_energy_carries` keeps the two knobs independent:
    // "carry over" adds the leftover on top of the (possibly modified) refill.
    let (target, max) = match existing {
        Some(pool) => {
            let base = pool.pool.max.unwrap_or(config.energy_refill);
            let base = host.turn_start_refill_count(state, actor, base);
            let target = if host.unspent_energy_carries(state, actor) {
                base.saturating_add(pool.pool.current)
            } else {
                base
            };
            (target, pool.pool.max)
        }
        None => {
            let base = host.turn_start_refill_count(state, actor, config.energy_refill);
            (base, Some(base))
        }
    };

    state
        .combatant_mut(actor)
        .ok_or(CapacityError::MissingCombatant)?
        .set_resource(config.energy, target, max)?;
    Ok(())
}

/// turn-start 处理器 #6 的**张数**：`wanted = clamp(handCeiling - hand.Count, 0, requested)`
/// （`Effects/CardZoneEffects.cs:31-46`）。
///
/// 这是"抽牌**入口**"的裁剪，不是"抽完再丢"：越过上限的牌**根本没被抽**，所以它们还留在抽牌堆里
/// （`:28-30` 的原话：a hand ceiling is subtracted from the DRAW, not from the hand）。手牌已经
/// 到/超上限 ⇒ `wanted == 0`，一张都不抽。
///
/// `requested` 是**过完修饰流水线之后**的张数（`host.turn_start_draw_count`，见
/// `Cards/CardTurnLifecycleEventHandlers.cs:25-31`）：C# 的裁剪对象是
/// `DrawCardsEffectRequest.Count`，也就是修饰后的值，**不是**配置原值 —— 宿主不该自己裁。
///
/// 本内核把"有没有 `MaxHandSize` 法令"编码成 `config.max_hand_size`（没有该法令时给 `i32::MAX`），
/// 与 C# 的 `CombatDecrees.Ceiling(...) is { } handCeiling` 等价。
fn capped_draw_count(
    state: &CombatState,
    actor: &CombatantId,
    config: &TurnConfig,
    requested: i32,
) -> usize {
    // C# 对负数抽牌是**抛**（`CardZoneEffects.cs:16-17`），但修饰流水线本身就会把张数夹到 >= 0
    // （`CardTurnLifecycleEventHandlers.cs:24` 的注释：the fold clamps at zero）。宿主不是
    // 内容表，不能让它把回合机推进 panic 分支，所以这里一律当 0 处理（"什么都不抽"）。
    let requested = requested.max(0);
    // 手牌 ≤ `MAX_CARDS_PER_ZONE`(96)，`as i32` 不会截断；`saturating_sub` 防的是
    // "负的 max_hand_size"这类坏配置在整数上溢出。
    let hand = hand_size(state, actor) as i32;
    // `requested >= 0` 保证 `clamp` 的区间非空；`i32::clamp` 在 `min > max` 时会 panic，
    // 而"裁剪后为负"（上限已经低于手牌数）在这里变成 0。
    config.max_hand_size.saturating_sub(hand).clamp(0, requested) as usize
}

/// 某一堆的牌数。抽牌循环要问"弃牌堆还空不空"（`CardZoneEffects.cs:59`）。
fn zone_count(state: &CombatState, owner: &CombatantId, zone: CardZone) -> usize {
    state.card_zones(owner).map_or(0, |z| z.count(zone))
}

/// turn-start 处理器 #6：抽牌。返回**实际抽到**的张数。
///
/// 逐张从抽牌堆**堆顶**（index 0，`Cards/CardZones.cs:251` 的 `RemoveAt(0)`）取，所以顺序就是
/// 堆序；抽牌堆抽空而弃牌堆非空时**重洗**再接着抽（`CardZoneEffects.cs:49-82`）：
///
/// ```text
/// while drawn < wanted:
///     newlyDrawn = zones.DrawCards(wanted - drawn)
///     drawn += newlyDrawn
///     if drawn >= wanted: break
///     if discardPile.Count == 0: break        // ← 两堆都空 ⇒ 抽不满，**不是**错误
///     order = CreateShuffledIndexes(discard.Count, seed, step)
///     zones.MoveDiscardPileToDrawPile(order)
///     AdvanceRandomStep()                      // ← 由 reshuffle_discard_into_draw 内部完成
/// ```
///
/// 于是"抽不满"只剩一个成因：**抽牌堆与弃牌堆都空了**（`:59-60` 的 `break`），与参考一致。
/// 洗牌顺序与随机步推进都是哈希可见的（`step=` 行 + 牌序），所以重洗必须走
/// [`CombatState::reshuffle_discard_into_draw`]，不能在这里自己打乱。
///
/// 循环一定会停：重洗会**搬空弃牌堆**，而本循环体内没有任何东西会再往里放牌 ⇒ 每次调用最多
/// 重洗一次；重洗之后抽牌堆非空，下一圈必然抽到牌。`reshuffles` 那个计数器是结构性兜底
/// （将来若有人在循环里加"往弃牌堆放牌"的动作，它保证这里不会变成死循环）。
fn draw_for_turn_start(
    state: &mut CombatState,
    actor: &CombatantId,
    config: &TurnConfig,
    requested: i32,
) -> Result<usize, TurnError> {
    let wanted = capped_draw_count(state, actor, config, requested);
    // 循环体（抽满 / 重洗一次 / 两堆都空就停）搬到了
    // [`CombatState::draw_cards_with_reshuffle`]：§161.3 的 `ChoiceThen::DiscardThenDraw`
    // 是第二个消费者，而两份重洗策略迟早会分叉。这里只剩「想要几张」的**修饰器计算**。
    Ok(state.draw_cards_with_reshuffle(actor, wanted)?)
}

/// turn-start 处理器 #7：`ClearBlockOnTurnStartedHandler`（注册在 `StandardCombatPackage.cs:133-135`；
/// 行为在 `Effects/DefensivePoolEffects.cs:283-322` → `ClearDefensivePoolEffectHandler:169-…`）。
///
/// 三条**可观察**的细节照抄：
/// * 池**不存在**就什么都不做（`:305` 的 `TryGetValue` 失败即 `continue`）—— 不能"清零"出一个
///   参考实现里根本没有的池条目，那会改变快照。
/// * `current <= 0` 也跳过（`:305`）。
/// * 清零**保留 max**（`:197` 的 `pool.SetCurrent(0)` 不动 `Max`）。
///
/// `RetainBlockTag`（Barricade 之类）**抑制**清空（`:294-314`）：`host.block_is_retained` 为真时
/// 直接返回，**池保留原值**（不是删掉，也不是清零）。判定位置与参考一致 —— 在"池存在且
/// `current > 0`"之后（`:305-314`），所以一条不存在的池不会因为"保留了"而凭空出现。
///
/// 注册表里"哪些池在回合开始清空"由 `DefensivePoolDefinition.ClearsOnOwnerTurnStart` 决定
/// （`:299-304`）；本内核用 `config.block_pool` 表达这一条（标准包只有一个这样的池）。
fn clear_turn_start_pool<H: TurnHost>(
    state: &mut CombatState,
    actor: &CombatantId,
    config: &TurnConfig,
    observed_current: Option<i32>,
    retained: bool,
    host: &H,
) -> Result<(), TurnError> {
    // ⚠️ "清不清"用的是**回合入口采样到的** `observed_current`，不是这里的实时值。
    //
    // 参考在**处理器时点**判定（`DefensivePoolEffects.cs:305`）：
    // ```
    // :305  if (!combatant.DefensivePools.TryGetValue(poolDef.Id, out var pool) || pool.Current <= 0)
    // :306      continue;            // 池此刻是 0 ⇒ 根本不入队清空请求
    // ```
    // 而所有处理器的**效果**都要等到七步跑完才排空 ⇒ 判定时本回合任何效果都还没生效。
    // 内核是就地生效的，所以"处理器时点"必须等价成"回合入口"。
    //
    // 同一个道理也适用于 `retained`：`retains` 也在 `:308-314` 的处理器时点读，
    // 所以它是回合入口的宿主决定，不能等到第 7 步再问（那时触发器可能刚给了"保留格挡"）。
    //
    // 不清（池不存在 / 采样值 ≤ 0 / 保留）⇒ 一行都不写。
    if observed_current.is_none_or(|current| current <= 0) {
        return Ok(());
    }
    if retained {
        return Ok(()); // `:308-314`：记一条日志就跳过，池原样保留
    }

    // 清的时候清**实时值**：这一刻的池可能已经被队列卡的 `gainBlock` 加过了，
    // 而参考里"清空请求"排在那些请求之后生效 —— 两者都是"把当下这个值抹成 0"。
    let live_max = state.combatant(actor).and_then(|c| {
        c.defensive_pools()
            .iter()
            .find(|p| p.key == config.block_pool)
            .and_then(|p| p.pool.max)
    });
    // §261: **清多少**问宿主（`Calipers` 留 `max(0, live - 15)`）。默认 0 = 全清。
    // 读实时值是刻意的：参考里"清空请求"排在队列效果之后生效，而"失去 15"说的就是
    // 那一刻的 15 —— 见 `block_kept_at_turn_start` 的文档。
    let live = state
        .combatant(actor)
        .and_then(|c| {
            c.defensive_pools()
                .iter()
                .find(|p| p.key == config.block_pool)
                .map(|p| p.pool.current)
        })
        .unwrap_or(0);
    let kept = host.block_kept_at_turn_start(state, actor, live).clamp(0, live.max(0));
    state
        .combatant_mut(actor)
        .ok_or(CapacityError::MissingCombatant)?
        .set_defensive_pool(config.block_pool, kept, live_max)?;
    Ok(())
}

/// C# 那句 `combat.ActiveCombatantId is { } id && combat.TryGetCombatant(id, out c) && !c.IsAlive`
/// （`CombatTurnProcessor.cs:87-89`）：活跃单位**存在且不存活**才算"需要跳过"。id 为空或指向一个
/// 不存在的单位 ⇒ `false`（循环不进入），与 `TryGetCombatant` 失败时的短路一致。
fn active_exists_and_is_downed(state: &CombatState) -> bool {
    state
        .active_combatant_id
        .and_then(|id| state.combatant(&id))
        .is_some_and(|c| c.lifecycle_state != CombatantLifecycleState::Alive)
}

/// 开始当前回合（`CombatTurnProcessor.StartCurrentTurn`，`:7-38`）。
///
/// 实现必须严格按文件头那张表的顺序，七个 turn-start 处理器一个不落、顺序不换。
pub fn start_current_turn<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
) -> Result<(), TurnError> {
    // C# 的顺序：`EnsureCombatIsOngoing`（`:15`）→ `EnsureActiveCombatantCanStartTurn`（`:16`）
    // → `MarkTurnStarted`（`:18`）。第三次检查才是阶段，所以"战斗已结束"报的是 `NotOngoing`
    // 而不是 `AlreadyInProgress`（`T:CombatTurnProcessorTests.cs:26-36` 钉的是后者）。
    ensure_ongoing(state)?;
    let actor = ensure_active_can_start_turn(state)?;

    if state.turn_phase != CombatTurnPhase::WaitingToStartTurn {
        return Err(TurnError::AlreadyInProgress);
    }

    // 第 7 步"清不清"的判定必须在**这里**采样，见 [`clear_turn_start_pool`] 的长注释：
    // 参考在处理器时点判定，而那一刻本回合的效果一件都还没生效。晚一步采样就会把
    // 队列卡刚加上的格挡当成"回合开始时就有的"。
    let observed_block = state
        .combatant(&actor)
        .and_then(|c| c.defensive_pools().iter().find(|p| p.key == config.block_pool).map(|p| p.pool.current));
    let block_retained = host.block_is_retained(state, &actor);
    // §197: a **one-shot** retention (`Blur`) is spent the moment it prevents this clear -- StS removes
    // the power in the same place. Content cannot reach this instant (it is neither a `TurnStarted`
    // trigger, which runs earlier, nor `TurnEnded`), so the host does it here.
    if block_retained {
        host.consume_one_shot_block_retainers(state, &actor);
    }

    state.turn_phase = CombatTurnPhase::TurnInProgress;

    // `EnqueueEvent(new TurnStartedCombatEvent(...))`（`:28-32`）之后 `ResolvePendingQueues`
    // （`:34-37`）会按**注册序**跑完下面这七个处理器。顺序是规格的一部分
    // （`StandardCombatPackage.cs:121-139` 的注册序 + `:122-133` 的设计注释），不是"读起来顺"
    // 的排列：补能量 → pending 转正 → 触发器 → **队列** → 抽牌 → 清 Block。
    //
    // 1. `ResetCardPlayTurnStatsOnTurnStartedHandler`（`Cards/CardPlayTurnStats.cs:296-309`）。
    //    ⚠️ **故意留空（未做到）**：本内核没有"每回合出牌统计"—— 出牌路径还没移植，状态模型里
    //    也没有对应字段。这一步在参考实现里只改那些统计，不碰本模块读写的任何字段，所以留空不会
    //    让别的步骤算错；但它是七个处理器里唯一没有落地的那个（见报告）。
    //
    // 2. 补能量。它在 `activate_pending_statuses` **之前** —— 位置本身就是规格。
    refill_resource(state, &actor, config, host)?;
    if stopped(state) {
        return Ok(());
    }

    // 3. pending 状态 `pending_turns--`，归零的转正（`Effects/StatusEffects.cs:409`）。
    host.activate_pending_statuses(state, &actor)?;
    if stopped(state) {
        return Ok(());
    }

    // 4. 全部 turn-start 触发程序，按 `(priority, id)` 序（`TriggeredProgramDefinition.cs:78`）。
    host.run_turn_started_triggers(state, &actor)?;
    if stopped(state) {
        return Ok(());
    }

    // 5. **队列**：两个处理器，顺序是注册序。
    //    5a. `ResolveQueueOnTurnStartedHandler` → `ResolveOldest(owner, int.MaxValue)`
    //        （`Cards/QueueResolution.cs:133-137`）—— 把 `QueuePile` 里的队列卡解析掉。
    //    5b. 排空这一步里入队的效果/事件。
    //    这一步排在触发程序之后、抽牌之前，于是"队列卡的效果**一定**发生在手牌到来之前"。
    host.resolve_card_queue(state, &actor)?;
    if stopped(state) {
        return Ok(());
    }
    host.resolve_pending_queues(state)?;
    if stopped(state) {
        return Ok(());
    }

    // 6. 抽牌。张数先过宿主（`TurnStartDraw` 修饰流水线），再在**入口**按 `max_hand_size` 裁剪；
    //    抽牌堆空了就重洗弃牌堆（两堆都空才抽不满，且那不是错误）。
    //    `drawn < wanted` 唯一可能的成因是"抽牌堆与弃牌堆都空了"（`CardZoneEffects.cs:59-60`）。
    let requested = host.turn_start_draw_count(state, &actor, config.draw_per_turn);
    // §220：抽到的那几张可能有 `LifecyclePrograms[Drawn]`（`void` 的"抽到时 -1 能量"）。
    // 手牌底部的"新尾巴"就是刚抽到的牌（`move_card` 用 `Bottom` 追加），所以先记下手牌长度，
    // 抽完再把越界出来的那几张逐张交给宿主 —— 顺序按堆序，与抽牌顺序一致。
    let hand_before = hand_size(state, &actor);
    let _drawn = draw_for_turn_start(state, &actor, config, requested)?;
    if !stopped(state) {
        let hand_after = hand_size(state, &actor);
        for index in hand_before..hand_after {
            let Some(slot) = state
                .card_zones(&actor)
                .and_then(|zones| zones.slot_at(CardZone::Hand, index))
            else {
                continue;
            };
            // §282：`Confusion` —— 回合开始的这 5 张**也**要重掷。抽牌有两条路
            // （`exec::draw_for` 与这里的 `draw_cards_with_reshuffle`），只在一条上装钩子
            // 会让"回合开始的牌不重掷"，而屏幕上一切正常。所以两个调用点都调**同一个**
            // `exec::confuse_drawn_card`（`pub` 就是为了这个）。
            //
            // 顺序：重掷在 `Drawn` 节目**之前** —— 那张牌的节目读到的是"这次抽到的价"。
            let confusion_content = host.confusion_content();
            crate::exec::confuse_drawn_card(state, confusion_content, &actor, slot);
            host.card_drawn(state, &actor, slot)?;
            if stopped(state) {
                break;
            }
        }
    }
    if stopped(state) {
        return Ok(());
    }

    // 7. 清 Block。它在队列解析**之后** —— 所以第 5 步里排队的 `gainBlock` 会被这一次清空抹掉，
    //    **前提**是回合入口那一刻池里已经有格挡（判定用的是入口采样值，见 `observed_block`）。
    clear_turn_start_pool(state, &actor, config, observed_block, block_retained, host)?;
    if stopped(state) {
        return Ok(());
    }

    // 末位：`DamageOverTimeOnTurnStartedHandler`（`StandardCombatPackage.cs:139`）。
    host.damage_over_time(state, &actor)?;
    if stopped(state) {
        return Ok(());
    }

    // TurnStarted 事件跑完之后再排空一次：上面每个宿主回调都可能入队了东西
    // （这就是"回合机在 TurnStarted 之后调一次 resolve_pending_queues"）。
    host.resolve_pending_queues(state)?;
    Ok(())
}

/// 结束当前回合（`EndCurrentTurn`，`:40-99`）。
///
/// 注意第 ② 步：`TurnEnded` 消化完之后若战斗已结束就 **return，不推进回合**。
pub fn end_current_turn<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
) -> Result<(), TurnError> {
    // `config` 在 turn-end 上用不上：这一步只碰手牌与回合计数，没有"补到多少 / 抽几张 / 清哪个池"
    // 这类由内容配置的数字。它留在签名里是因为 `end_current_turn_and_start_next` 必须把**同一份**
    // `TurnConfig` 交给紧随其后的 `start_current_turn`，而冻结签名不许改。
    let _ = config;

    ensure_ongoing(state)?; // `:48`
    // §200: 行动者在自己的回合里自毁 ⇒ 没有行动者了，但**这个回合还欠一次收尾**。它连牌堆都被
    // 摘掉了，所以每一段 per-actor 的工作（手牌生命周期、弃手牌、回合末触发器、按时长衰减）
    // 都没有对象 —— 整段跳过，只翻相位、把席位交给继任者、消化队列。
    let vacated = state.active_combatant_id.is_none() && state.vacated_seat.is_some();
    let actor = if vacated {
        None
    } else {
        Some(ensure_active_combatant(state)?) // `:49`（`EnsureActiveCombatantExistsInTurnOrder`）
    };

    // `combat.MarkTurnEnded()`（`:51`）：不在回合中就抛（`CombatState.cs:332-338`）。
    if state.turn_phase != CombatTurnPhase::TurnInProgress {
        return Err(TurnError::NotInProgress);
    }
    state.turn_phase = CombatTurnPhase::WaitingToStartTurn;

    // `EnqueueEvent(TurnEndedCombatEvent(...))`（`:61-65`）+ `ResolvePendingQueues`（`:67-70`）。
    // 该事件的注册序（规格书 §3.1 的 "TurnEndedCombatEvent 顺序"，`:135-138`）：
    //   ① 牌在手里过回合的生命周期节目（`Cards/CardLifecyclePrograms.cs:21-46`
    //      —— ⚠️ 2026-10-19 更正：这里原来写的是 `CardTurnLifecycleEventHandlers.cs`，那是
    //      **弃手牌**与**抽牌**所在的文件，放生命周期节目的是 `CardLifecyclePrograms.cs`）
    //   ② **弃手牌**，被 `RetainHandTag` 抑制 —— 本内核走 `host.hand_is_retained`
    //   ③ turn-end 触发程序
    //   ④ 按时长的状态减 1（`Effects/StatusEffects.cs:390-404`）
    //
    // ⚠️ ① 在参考里是**同一个事件的分发**里的一个处理器，所以它不花链号（整批只花事件那一个）；
    // 本内核把 ② ③ ④ 拆成了钩子/直接调用，① 仍然排在最前（Burn 的伤害因此在弃手牌**之前**
    // 就进了效果队列 —— 与参考"before the end-of-turn discard, which is deferred"同构）。
    if let Some(actor) = actor {
        host.hand_turn_end_lifecycle(state, &actor)?;
        if stopped(state) {
            return Ok(());
        }
        discard_hand(state, &actor, host)?;
        if stopped(state) {
            return Ok(());
        }
        host.run_turn_ended_triggers(state, &actor)?;
        if stopped(state) {
            return Ok(());
        }
        host.decrease_timed_statuses(state, &actor)?;
        if stopped(state) {
            return Ok(());
        }
    }

    // ① 消化 TurnEnded。
    host.resolve_pending_queues(state)?;

    // ② 战斗在回合结束时结束了 ⇒ **不推进回合**（`:72-73`）。
    if stopped(state) {
        return Ok(());
    }

    // ③ 推进到下一个存活单位。
    advance_to_next_combatant(state, host)?;

    // ④ 消化 RoundEnded / RoundStarted。
    host.resolve_pending_queues(state)?;

    // ⑤ 刚推进到的单位可能被 ④ 打死（例如一个 round-start 触发器），而战斗仍在继续（别人还活着）：
    //    在交接点上跳过它，保证下一个回合总是从活人开始（`:82-98`）。
    //    上限与参考一致（`:85-90`）：`guard++ <= TurnOrder.Count`（后自增 ⇒ 先比较后加，所以最多
    //    进 Count+1 次循环体）。没有这个上限，一个"永远把下一个单位打死"的触发器会让这里转不出来。
    let mut guard = 0usize;
    while !stopped(state) && active_exists_and_is_downed(state) && guard <= state.turn_order().len() {
        guard += 1;
        advance_to_next_combatant(state, host)?;
        host.resolve_pending_queues(state)?;
    }
    Ok(())
}

/// `EndCurrentTurnAndStartNextTurn`（`:101-118`）：结束，若战斗仍继续则开始下一个回合。
pub fn end_current_turn_and_start_next<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
) -> Result<(), TurnError> {
    // 规格书 §3.1 的 `EndCurrentTurnAndStartNextTurn`（`:101-118`）：结束，若战斗仍继续才开始下一个。
    end_current_turn(state, config, host)?;
    if stopped(state) {
        return Ok(());
    }
    start_current_turn(state, config, host)
}

/// 推进到下一个存活单位（`AdvanceToNextCombatant`，`:170-212`）。
///
/// 绕回（`nxt <= cur`）⇒ `host.on_round_ended(旧轮)` → `current_round += 1`、`current_turn = 1`
/// → **移除已到期**的临时规则 → `host.on_round_started(新轮)`；
/// 否则 `current_turn += 1` → **移除已到期**的临时规则（轮次事件**都不发**）。
///
/// ⚠️ **顺序是契约**，三个地方各错一次都会造出参考实现里不存在的状态：
/// 1. `on_round_ended` 在自增**之前**：它的参数是**旧轮**，而且 C# 在那一刻读的
///    `ActiveCombatantId` 还是**要退场**的那个（`:192-195`）。
/// 2. 自增在到期判定**之前**（`CombatState.cs:574,577` / `:583-589`）：反了会让"本回合到期"
///    的规则早一回合消失。
/// 3. `on_round_started` 在自增**之后**：它的参数是**新轮**。
///
/// 参考实现在这里只**入队**两个事件（处理器要到调用方那次 `ResolvePendingQueues` 才跑），
/// 所以本函数**不检查** `result`：边界上的宿主回调哪怕立刻把战斗判成终态，回合机也照参考的
/// 形状走完这一格，由 `end_current_turn` 的 ④ 之后统一判停。
    /// **An extra turn beats the rotation** (`port-plan.md` §127): the actor that asked for one stays
    /// active, the candidate enemy does not get its turn yet, and the marker is consumed.
    #[test]
    fn an_extra_turn_keeps_the_same_actor_active() {
        use crate::state::{Combatant, CombatantDefinitionId, TeamId};
        let id = |name: &str| CombatantId::new(name).unwrap();
        let unit = |name: &str, team: &str| {
            Combatant::new(
                id(name),
                CombatantDefinitionId::new(name).unwrap(),
                TeamId::new(team).unwrap(),
                10,
                10,
            )
        };
        let mut state = CombatState::new(crate::state::CombatId::new("t").unwrap(), 1);
        state.add_combatant(unit("hero", "player")).unwrap();
        state.add_combatant(unit("enemy_a", "enemy")).unwrap();
        let mut host = NullHost;
        let hero = id("hero");
        let enemy = id("enemy_a");
        state.active_combatant_id = Some(hero);

        // Ordinary rotation: the enemy takes over.
        advance_to_next_combatant(&mut state, &mut host).unwrap();
        assert_eq!(state.active_combatant_id, Some(enemy));

        // Now the enemy asks for one more turn: ending it keeps the enemy active.
        state.extra_turn_for = Some(enemy);
        let turn_before = state.current_turn;
        advance_to_next_combatant(&mut state, &mut host).unwrap();
        assert_eq!(
            state.active_combatant_id,
            Some(enemy),
            "the enemy acts again instead of handing over"
        );
        assert_eq!(state.current_turn, turn_before + 1, "the turn clock still moves");
        assert_eq!(state.extra_turn_for, None, "the marker is spent");

        // ...and the one after that rotates normally.
        advance_to_next_combatant(&mut state, &mut host).unwrap();
        assert_eq!(state.active_combatant_id, Some(hero));
    }

/// Roll "cards played this turn" into "last turn" and clear it (port-plan.md §128).
fn roll_card_play_counters(state: &mut CombatState) {
    state.cards_played_last_turn = state.cards_played_this_turn;
    state.cards_played_this_turn = 0;
}

pub fn advance_to_next_combatant<H: TurnHost>(
    state: &mut CombatState,
    host: &mut H,
) -> Result<(), TurnError> {
    // §200: 行动者在自己的回合里自毁之后 `active` 是空的，但"它坐在哪一格"还在
    // `vacated_seat` 里 —— 那一格现在坐着它的**继任者**。`cur` 取它的**前一格**，于是下面那个
    // `(cur + offset) % len` 的第一站正好是继任者（它要是也倒了，循环照旧往下跳）。
    //
    // 三个分支都只算出 `cur`（"刚结束的那个席位"），推进本身仍然只有下面那一段。
    let active = if state.active_combatant_id.is_some() || state.vacated_seat.is_none() {
        ensure_active_combatant(state)?; // `:172`
        state.active_combatant_id
    } else {
        // 席位被腾空：`ensure_active_combatant` 会**拒绝**认领（见那里的注释），所以不走它。
        None
    };
    let cur = match (active, state.vacated_seat.take()) {
        (Some(active), _) => {
            // `:174-177`：`First(x => x.id == activeId)` —— 找不到就是"活跃单位不在回合序里"。
            let Some(position) = state.turn_order().iter().position(|id| *id == active) else {
                return Err(TurnError::ActiveNotInTurnOrder);
            };
            position
        }
        (None, Some(seat)) => {
            let len = state.turn_order().len();
            if len == 0 {
                return Err(TurnError::NoTurnOrder);
            }
            // 前一格：`seat == 0` 时是末尾（于是 `(cur + 1) % len == 0`），`seat == len` 时也是
            // 末尾（于是绕回 0）—— 两种都对。
            let seat = usize::from(seat);
            if seat == 0 {
                len - 1
            } else {
                (seat - 1) % len
            }
        }
        (None, None) => return Err(TurnError::NoActiveCombatant),
    };

    // **An extra turn beats the rotation** (`node.extraTurn`, `port-plan.md` §127): the actor that
    // asked for one simply stays active, and only the turn clock moves.
    // §200: 行动者自毁时 `extra_turn_for` 已经在 `remove_combatant` 里清掉，所以这一支不会命中。
    if state.active_combatant_id.is_some() && state.extra_turn_for == state.active_combatant_id {
        state.extra_turn_for = None;
        state.current_turn += 1;
        state.expire_temporary_rules_at_turn_boundary();
        return Ok(());
    }
    let len = state.turn_order().len(); // 非 0：上面那次 ensure 已经保证

    for offset in 1..=len {
        let nxt = (cur + offset) % len;
        let Some(next_id) = state.turn_order().get(nxt).copied() else {
            continue; // C# 的 `TryGetCombatant` 失败 ⇒ `continue`（`:184-185`）
        };
        if !is_alive(state, &next_id) {
            continue; // `:187-188`
        }

        if nxt <= cur {
            // `EnqueueEvent(new RoundEndedCombatEvent(combat.CurrentRound, combat.ActiveCombatantId))`
            // （`:192-195`）—— 参数是**即将结束**的那一轮，活跃单位此时还没换。
            let ended_round = state.current_round;
            host.on_round_ended(state, ended_round)?;

            // `AdvanceRound()`（`CombatState.cs:581-592`）：先自增，再做**两个**到期判定。
            state.current_round += 1;
            state.current_turn = 1;
            state.expire_temporary_rules_at_round_boundary();

            // `EnqueueEvent(new RoundStartedCombatEvent(combat.CurrentRound))`（`:199-200`）。
            let new_round = state.current_round;
            host.on_round_started(state, new_round)?;
        } else {
            // `AdvanceTurn()`（`CombatState.cs:572-579`）：同样先自增再判定，
            // **只**做 `expires_after_turn` 那一个 Mark（轮次到期不归它管）。
            state.current_turn += 1;
            roll_card_play_counters(state);
            state.expire_temporary_rules_at_turn_boundary();
        }

        state.active_combatant_id = Some(next_id); // `SetActiveCombatant`（`:207`）
        return Ok(());
    }

    Err(TurnError::NoLivingCombatants) // `:211`
}

/// 手牌张数。回合末弃手牌与 `MaxHandSize` 裁剪都要用它。
#[must_use]
pub fn hand_size(state: &CombatState, actor: &CombatantId) -> usize {
    state.card_zones(actor).map_or(0, |z| z.count(CardZone::Hand))
}

/// 把当前活跃单位的手牌按**回合末落点逐张**搬走（`MoveHandCardsOnTurnEndEffectHandler`，
/// `Effects/CardZoneEffects.cs:346-428`）。
///
/// 被 `host.hand_is_retained(...)` 抑制（`Cards/CardTurnLifecycleEventHandlers.cs:46-55`）——
/// 那是**整手**保留，先短路，一张都不碰。返回**实际搬走**的张数。
///
/// 其余三档逐张判定，顺序就是手牌原序（参考也先 `zones.Hand.ToArray()` 再逐张处理，
/// `CardZoneEffects.cs:355`，因为下面的移动改的正是这个堆）：
///
/// 1. `host.card_stays_in_hand_at_turn_end` ⇒ 这张留下（`:419-425`：实例上的
///    `standard.retained_card` 标记 / 定义里的 `RetainInHandOnTurnEnd`）；
/// 2. `host.turn_end_hand_destination` ⇒ 落点（`:427` 的 `definition.TurnEndHandDestinationZone`，
///    可能不是弃牌堆，例如消耗堆）。返回 `Hand` 等价于"留下"（`:366-367` 的
///    `if (destinationZone == CardZone.Hand) continue;`）；
/// 3. 落点一律 `Bottom`（`MoveCardToZone` 的默认 `ZonePlacement`，`:369`）⇒ 每个目的堆内部
///    **保持手牌原序**。
///
/// 目的堆容量**先整体验一遍**再动手：C# 的 `List.Add` 不会失败，本内核的槽位表会，
/// 所以这里沿用 `move_all_cards` 的契约 —— 不允许"搬了一半才发现装不下"。
pub fn discard_hand<H: TurnHost>(
    state: &mut CombatState,
    actor: &CombatantId,
    host: &mut H,
) -> Result<usize, TurnError> {
    // 被 `RetainHandTag` 抑制（`Cards/CardTurnLifecycleEventHandlers.cs:46-55`）—— 本内核走
    // `host.hand_is_retained`，因为"哪些标记保留手牌"是内容决定的。抑制时返回 0（"一张都没弃"）。
    if host.hand_is_retained(state, actor) {
        return Ok(0);
    }

    // 先把"哪张去哪"按手牌原序定下来。`CardSlot` 不带隐含顺序信息，所以顺序靠这个数组保持。
    //
    // ⚠️ 这里**必须**先取一次 `card_zones`：未知单位要报 `MissingCombatant`，不能因为
    // `zone_count` 把"没有牌区"折叠成 0 张就静默返回 `Ok(0)`（旧实现走 `move_all_cards`，
    // 对未知单位是报错的；有测试钉着这条）。
    if state.card_zones(actor).is_none() {
        return Err(TurnError::Capacity(CapacityError::MissingCombatant));
    }
    let hand_len = zone_count(state, actor, CardZone::Hand);
    let mut moves = [(CardSlot::from_index(0), CardZone::Hand); MAX_CARDS_PER_ZONE];
    let mut planned = 0usize;
    for i in 0..hand_len {
        // `slot_at` 是越界安全的版本：裸机上没有 unwind，索引一律走 `get()`。
        let Some(slot) = state
            .card_zones(actor)
            .and_then(|z| z.slot_at(CardZone::Hand, i))
        else {
            continue; // 不可达（`hand_len` 与堆同源），但没有 panic 路径
        };
        if planned == MAX_CARDS_PER_ZONE {
            break; // 不可达：手牌本身就在同一个上限里
        }
        if host.card_stays_in_hand_at_turn_end(state, actor, slot) {
            continue;
        }
        let destination = host.turn_end_hand_destination(state, actor, slot);
        if destination == CardZone::Hand {
            continue;
        }
        // 落点先记下来：真正的 `move_card` 在下面统一的循环里做，届时按同一个 (from, to) 发通知。
        moves[planned] = (slot, destination);
        planned += 1;
    }
    if planned == 0 {
        return Ok(0);
    }

    // 容量预检：按目的堆汇总，超了就在**动手之前**报错。
    for zone in CardZone::ALL {
        let incoming = moves[..planned].iter().filter(|m| m.1 == zone).count();
        if incoming == 0 {
            continue;
        }
        if zone_count(state, actor, zone) + incoming > MAX_CARDS_PER_ZONE {
            return Err(TurnError::Capacity(CapacityError::Full(
                Container::CardsInZone(zone),
            )));
        }
    }

    let mut moved = 0usize;
    for (slot, destination) in moves[..planned].iter().copied() {
        if state.move_card(actor, CardZone::Hand, destination, slot, ZonePlacement::Bottom)? {
            // §220：虚无（`TurnEndHandDestinationZone = ExhaustPile`）走的就是这一条 ⇒
            // `sentinel` 的"被消耗时给能量"从这里触发（经宿主，因为只有它知道内容）。
            if destination == CardZone::ExhaustPile {
                host.card_exhausted(state, actor, slot)?;
            }
            moved += 1;
        }
    }
    Ok(moved)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn is_alive_counts_only_the_alive_lifecycle_state() {
        use crate::state::{Combatant, CombatantDefinitionId, TeamId};
        let mut s = CombatState::new(crate::state::CombatId::new("t").unwrap(), 1);
        let id = CombatantId::new("hero").unwrap();
        s.add_combatant(Combatant::new(
            id,
            CombatantDefinitionId::new("hero").unwrap(),
            TeamId::new("player").unwrap(),
            10,
            10,
        ))
        .unwrap();
        assert!(is_alive(&s, &id));
        // 五种非存活态一个都不能算活着 —— 这是"跳过倒下单位"那条逻辑的地基。
        for dead in [
            CombatantLifecycleState::Downed,
            CombatantLifecycleState::Dead,
            CombatantLifecycleState::Removed,
            CombatantLifecycleState::Escaped,
            CombatantLifecycleState::Banished,
        ] {
            s.combatant_mut(&id).unwrap().lifecycle_state = dead;
            assert!(!is_alive(&s, &id), "{dead:?} 不该被算作存活");
        }
        // 未知 id 也不是活着。
        assert!(!is_alive(&s, &CombatantId::new("nobody").unwrap()));
    }

    #[test]
    fn the_null_host_is_a_real_host_so_the_machine_can_be_driven_without_effects() {
        // 这条测试的价值不在于断言什么结果，而在于**证明接缝是可用的**：
        // 一个全空的宿主就能让回合机跑起来，说明效果系统的缺失被正确地隔离在 trait 后面，
        // 而不是渗进回合机的每一步。
        let mut s = CombatState::new(crate::state::CombatId::new("t").unwrap(), 1);
        let mut host = NullHost;
        assert!(!host.hand_is_retained(&s, &CombatantId::new("nobody").unwrap()));
        let actor = CombatantId::new("nobody").unwrap();
        assert!(host.resolve_pending_queues(&mut s).is_ok());
        assert!(host.activate_pending_statuses(&mut s, &actor).is_ok());
        assert!(host.damage_over_time(&mut s, &actor).is_ok());
        assert_eq!(hand_size(&s, &actor), 0);
    }

    /// 回合机自己的测试。
    ///
    /// 单独开一层模块，只为了**不碰**上面那两条已冻结的测试。
    ///
    /// 大多数用例由 `NullHost` 驱动：它什么都不做，所以每条断言都是**回合机自己的职责** ——
    /// 阶段流转、轮次推进、能量补充、抽牌、清 Block、弃手牌。"某个效果发生了没有"这类断言用
    /// `NullHost` 写出来是**空断言**（只证明"我什么都没做"），所以这里一条都没有：需要"效果"的
    /// 地方用 `EndsCombatAt` 显式扮演"把战斗判成终态的效果"，而断言的对象仍然是回合机
    /// （**停没停、推没推进**），不是那个效果本身。
    mod turn_machine {
        use crate::state::{
            CapacityError, CardDefinitionId, CardInstance, CardInstanceId, CardSlot, CardZone,
            CombatId, CombatResult, CombatState, CombatTurnPhase, Combatant,
            CombatantDefinitionId, CombatantId, CombatantLifecycleState, DefensivePoolId,
            EventTypeName, ResourceId, TeamId, TemporaryRule, TriggeredEffectDefinitionId,
        };

        use super::super::{
            advance_to_next_combatant, discard_hand, end_current_turn,
            end_current_turn_and_start_next, hand_size, start_current_turn, NullHost, TurnConfig,
            TurnError, TurnHost,
        };

        const ENERGY: &str = "standard.energy";
        const BLOCK: &str = "standard.block";

        fn cid(s: &str) -> CombatantId {
            CombatantId::new(s).unwrap()
        }
        fn rid(s: &str) -> ResourceId {
            ResourceId::new(s).unwrap()
        }
        fn dpid(s: &str) -> DefensivePoolId {
            DefensivePoolId::new(s).unwrap()
        }

        fn config(energy_refill: i32, draw_per_turn: i32, max_hand_size: i32) -> TurnConfig {
            TurnConfig {
                energy: rid(ENERGY),
                energy_refill,
                draw_per_turn,
                block_pool: dpid(BLOCK),
                max_hand_size,
            }
        }

        /// 标准包形状：能量 3 / 抽 5 / 没有 `MaxHandSize` 法令 / Block = `standard.block`。
        fn standard() -> TurnConfig {
            config(3, 5, i32::MAX)
        }

        fn fight(ids: &[&str]) -> CombatState {
            let mut s = CombatState::new(CombatId::new("c1").unwrap(), 42);
            for (i, id) in ids.iter().enumerate() {
                let team = if i == 0 { "player" } else { "enemy" };
                s.add_combatant(Combatant::new(
                    cid(id),
                    CombatantDefinitionId::new(id).unwrap(),
                    TeamId::new(team).unwrap(),
                    70,
                    70,
                ))
                .unwrap();
            }
            s
        }

        /// 往某人的抽牌堆放一副"只认序号"的牌：`card_000001` 是堆顶（最先被抽到）。
        fn stock_deck(s: &mut CombatState, owner: &CombatantId, n: usize) {
            for i in 1..=n {
                s.push_card(owner, CardZone::DrawPile, card(i)).unwrap();
            }
        }

        fn card(n: usize) -> CardInstance {
            CardInstance::new(
                CardInstanceId::new(&format!("card_{n:06}")).unwrap(),
                CardDefinitionId::new("strike").unwrap(),
            )
        }

        fn hand(s: &CombatState, owner: &CombatantId) -> usize {
            hand_size(s, owner)
        }

        fn pile(s: &CombatState, owner: &CombatantId, zone: CardZone) -> usize {
            s.card_zones(owner).map_or(0, |z| z.count(zone))
        }

        fn pile_ids(s: &CombatState, owner: &CombatantId, zone: CardZone) -> Vec<String> {
            s.zone_cards(owner, zone)
                .map(|c| c.id.as_str().to_string())
                .collect()
        }

        /// 临时规则的 id 列表。`tr=` 行是哈希可见的，所以"还在不在"与"顺序"都必须能被断言。
        fn rule_ids(s: &CombatState) -> Vec<String> {
            s.temporary_rules()
                .iter()
                .map(|r| r.id.as_str().to_string())
                .collect()
        }

        fn resource(s: &CombatState, owner: &CombatantId) -> Option<(i32, Option<i32>)> {
            s.combatant(owner).and_then(|c| {
                c.resources()
                    .iter()
                    .find(|p| p.key == rid(ENERGY))
                    .map(|p| (p.pool.current, p.pool.max))
            })
        }

        fn pool(s: &CombatState, owner: &CombatantId, key: &str) -> Option<(i32, Option<i32>)> {
            s.combatant(owner).and_then(|c| {
                c.defensive_pools()
                    .iter()
                    .find(|p| p.key == dpid(key))
                    .map(|p| (p.pool.current, p.pool.max))
            })
        }

        fn down(s: &mut CombatState, id: &str) {
            s.combatant_mut(&cid(id)).unwrap().lifecycle_state = CombatantLifecycleState::Downed;
        }

        /// `NullHost` + 一条"手牌保留"（参考实现里那是 `RetainHandTag` 状态，
        /// `Cards/CardTurnLifecycleEventHandlers.cs:46-55`）。它是观测"手牌过回合不掉"这件事的
        /// **唯一**接缝，所以几条测试需要它。
        #[derive(Default)]
        struct RetainingHost(NullHost);

        impl TurnHost for RetainingHost {
            fn resolve_card_queue(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.0.resolve_card_queue(s, a)
            }
            fn activate_pending_statuses(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.0.activate_pending_statuses(s, a)
            }
            fn run_turn_started_triggers(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.0.run_turn_started_triggers(s, a)
            }
            fn resolve_pending_queues(&mut self, s: &mut CombatState) -> Result<(), TurnError> {
                self.0.resolve_pending_queues(s)
            }
            fn damage_over_time(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.0.damage_over_time(s, a)
            }
            fn hand_turn_end_lifecycle(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.0.hand_turn_end_lifecycle(s, a)
            }
            fn run_turn_ended_triggers(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.0.run_turn_ended_triggers(s, a)
            }
            fn decrease_timed_statuses(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.0.decrease_timed_statuses(s, a)
            }
            fn hand_is_retained(&self, _: &CombatState, _: &CombatantId) -> bool {
                true
            }
        }

        /// `NullHost` + "第 5 步解析队列时给格挡" —— 队列卡 `gainBlock` 的替身。
        ///
        /// 存在的唯一理由是钉住一件事：**"清不清格挡"的判定在回合入口，不在第 7 步**
        /// （参考 `DefensivePoolEffects.cs:305-306` 在**处理器时点**采样 `pool.Current <= 0`
        /// 才决定要不要入队清空请求，而那一刻本回合任何效果都还没生效）。
        /// `S:QueueTortureTests.cs:210-212` 那个用例**区分不出**两种实现 —— 两种解释都给 11 ——
        /// 所以那个用例的注释一直写反着，也没人发现。分歧必须自己造出来。
        ///
        /// 参数化 `inner` 是为了和"保留格挡"那条策略钩子组合出第三格（保留 + 队列加格挡）。
        ///
        /// `queued` 是**队列的替身**：一次 turn-start 里 `resolve_pending_queues` 会被调
        /// **两次**（第 5 步一次、`TurnStarted` 跑完再排空一次，见 `start_current_turn` 末尾），
        /// 而真实队列里只有一张卡 ⇒ 第二次调用必须什么都没找到。用一个"事件"而不是
        /// "每次调用都加"，就是为了让这个替身和参考的队列同构；否则测出来的数是 22。
        struct QueueGainsBlock<H: TurnHost> {
            inner: H,
            amount: i32,
            retain_block: bool,
            queued: bool,
        }

        impl<H: TurnHost> TurnHost for QueueGainsBlock<H> {
            fn resolve_card_queue(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
            fn activate_pending_statuses(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.activate_pending_statuses(s, a)
            }
            fn run_turn_started_triggers(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.run_turn_started_triggers(s, a)
            }
            fn resolve_pending_queues(&mut self, s: &mut CombatState) -> Result<(), TurnError> {
                self.inner.resolve_pending_queues(s)?;
                if !self.queued {
                    return Ok(()); // 队列空了：第二次排空是 no-op
                }
                self.queued = false;
                let Some(actor) = s.active_combatant_id else {
                    return Ok(());
                };
                let (current, max) = s
                    .combatant(&actor)
                    .and_then(|c| {
                        c.defensive_pools()
                            .iter()
                            .find(|p| p.key == dpid(BLOCK))
                            .map(|p| (p.pool.current, p.pool.max))
                    })
                    .unwrap_or((0, None));
                s.combatant_mut(&actor)
                    .ok_or(CapacityError::MissingCombatant)?
                    .set_defensive_pool(dpid(BLOCK), current + self.amount, max)?;
                Ok(())
            }
            fn damage_over_time(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.damage_over_time(s, a)
            }
            fn hand_turn_end_lifecycle(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.hand_turn_end_lifecycle(s, a)
            }
            fn run_turn_ended_triggers(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.run_turn_ended_triggers(s, a)
            }
            fn decrease_timed_statuses(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.decrease_timed_statuses(s, a)
            }
            fn hand_is_retained(&self, s: &CombatState, a: &CombatantId) -> bool {
                self.inner.hand_is_retained(s, a)
            }
            fn block_is_retained(&self, s: &CombatState, a: &CombatantId) -> bool {
                // 显式给的答案优先；否则问内层（`NullHost` 是 false）。
                self.retain_block || self.inner.block_is_retained(s, a)
            }
        }

        /// 把**每次**钩子调用记成一个字节。用来钉"钩子的相对位置"，而不是"钩子被调了几次"。
        ///
        /// 为什么需要它：`turn-start` 的七步顺序是这个模块唯一不可协商的东西，
        /// 而其中第 5 步在 2026-10-17 被拆成了**两个**钩子
        /// （`resolve_card_queue` 解析 `QueuePile`、`resolve_pending_queues` 排空效果队列）。
        /// 拆开之后"谁先谁后"只写在注释里，只有这一条测试能证明它真的没被写反。
        struct OrderProbe<'a> {
            log: &'a mut std::vec::Vec<u8>,
        }

        impl OrderProbe<'_> {
            fn mark(&mut self, tag: u8) {
                self.log.push(tag);
            }
        }

        impl TurnHost for OrderProbe<'_> {
            fn activate_pending_statuses(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                self.mark(b'p'); // step 2：pending 转正
                Ok(())
            }
            fn run_turn_started_triggers(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                self.mark(b't'); // step 3：turn-start 触发器
                Ok(())
            }
            fn resolve_card_queue(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                self.mark(b'q'); // step 4a：QueuePile
                Ok(())
            }
            fn resolve_pending_queues(&mut self, _: &mut CombatState) -> Result<(), TurnError> {
                self.mark(b'd'); // step 4b（以及 TurnStarted 之后的再排空）
                Ok(())
            }
            fn damage_over_time(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                self.mark(b'o'); // step 7：DoT
                Ok(())
            }
            fn hand_turn_end_lifecycle(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                self.mark(b'h');
                Ok(())
            }
            fn run_turn_ended_triggers(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                self.mark(b'e');
                Ok(())
            }
            fn decrease_timed_statuses(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                self.mark(b'c');
                Ok(())
            }
            fn hand_is_retained(&self, _: &CombatState, _: &CombatantId) -> bool {
                false
            }
        }

        /// 在某一步把战斗判成终态的宿主 —— **效果系统的替身**。
        ///
        /// 这不是空断言：宿主把 `result` 改成终态，就是"某个效果结束了战斗"的等价物；被断言的
        /// 始终是**回合机**：一步之后 `result != Ongoing` 就该停下、不推进（冻结契约 #4）。
        /// `NullHost` 做不了这件事 —— 它什么都不做，于是永远走完全程。
        struct EndsCombatAt(Hook);

        #[derive(Clone, Copy, PartialEq, Eq)]
        enum Hook {
            /// turn-start 第 4 步（触发器）。
            TurnStartTriggers,
            /// turn-end 第 ① 步（手牌生命周期钩子）。
            TurnEndLifecycle,
        }

        impl TurnHost for EndsCombatAt {
            fn resolve_card_queue(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
            fn activate_pending_statuses(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
            fn run_turn_started_triggers(&mut self, s: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                if self.0 == Hook::TurnStartTriggers {
                    s.result = CombatResult::Victory;
                }
                Ok(())
            }
            fn resolve_pending_queues(&mut self, _: &mut CombatState) -> Result<(), TurnError> {
                Ok(())
            }
            fn damage_over_time(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
            fn hand_turn_end_lifecycle(&mut self, s: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                if self.0 == Hook::TurnEndLifecycle {
                    s.result = CombatResult::Defeat;
                }
                Ok(())
            }
            fn run_turn_ended_triggers(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
            fn decrease_timed_statuses(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
            fn hand_is_retained(&self, _: &CombatState, _: &CombatantId) -> bool {
                false
            }
        }

        /// 一个"只覆盖**一条**策略"的宿主：其余行为全走 `NullHost`。
        ///
        /// 每条策略断言都拿**同一份剧本**在默认宿主（`NullHost`）与它之间对拍（`assert_ne!`）：
        /// 两侧给出同一个值就说明"宿主根本没被问过"，那是空断言。
        #[derive(Default)]
        struct PolicyHost {
            /// `block_is_retained`：`RetainBlockTag`（Barricade）。
            block_retained: bool,
            /// `turn_start_draw_count` = `base + draw_delta`（`TurnStartDraw` 修饰流水线）。
            draw_delta: i32,
            /// `unspent_energy_carries`：`UnspentResourceCarries` 法令。
            carries_energy: bool,
            inner: NullHost,
        }

        impl TurnHost for PolicyHost {
            fn resolve_card_queue(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
            fn activate_pending_statuses(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.activate_pending_statuses(s, a)
            }
            fn run_turn_started_triggers(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.run_turn_started_triggers(s, a)
            }
            fn resolve_pending_queues(&mut self, s: &mut CombatState) -> Result<(), TurnError> {
                self.inner.resolve_pending_queues(s)
            }
            fn damage_over_time(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.damage_over_time(s, a)
            }
            fn hand_turn_end_lifecycle(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.hand_turn_end_lifecycle(s, a)
            }
            fn run_turn_ended_triggers(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.run_turn_ended_triggers(s, a)
            }
            fn decrease_timed_statuses(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.decrease_timed_statuses(s, a)
            }
            fn hand_is_retained(&self, _: &CombatState, _: &CombatantId) -> bool {
                false
            }
            fn block_is_retained(&self, _: &CombatState, _: &CombatantId) -> bool {
                self.block_retained
            }
            fn turn_start_draw_count(&self, _: &CombatState, _: &CombatantId, base: i32) -> i32 {
                base.saturating_add(self.draw_delta)
            }
            fn unspent_energy_carries(&self, _: &CombatState, _: &CombatantId) -> bool {
                self.carries_energy
            }
        }

        /// 轮次边界上的两个事件。
        #[derive(Clone, Copy, PartialEq, Eq, Debug)]
        enum Boundary {
            RoundEnded,
            RoundStarted,
        }

        /// 记录"轮次边界回调"的宿主：`(哪个回调, 传进来的轮次, 回调时 state.current_round)`。
        ///
        /// 第三个字段是**顺序契约**的探针：`on_round_ended` 必须在自增**之前**被调用（于是它看到的
        /// `current_round` 就是它自己的参数），`on_round_started` 在自增**之后**。
        #[derive(Default)]
        struct BoundaryLog {
            inner: NullHost,
            calls: Vec<(Boundary, i32, i32)>,
        }

        impl TurnHost for BoundaryLog {
            fn resolve_card_queue(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
            fn activate_pending_statuses(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.activate_pending_statuses(s, a)
            }
            fn run_turn_started_triggers(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.run_turn_started_triggers(s, a)
            }
            fn resolve_pending_queues(&mut self, s: &mut CombatState) -> Result<(), TurnError> {
                self.inner.resolve_pending_queues(s)
            }
            fn damage_over_time(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.damage_over_time(s, a)
            }
            fn hand_turn_end_lifecycle(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.hand_turn_end_lifecycle(s, a)
            }
            fn run_turn_ended_triggers(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.run_turn_ended_triggers(s, a)
            }
            fn decrease_timed_statuses(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.decrease_timed_statuses(s, a)
            }
            fn hand_is_retained(&self, _: &CombatState, _: &CombatantId) -> bool {
                false
            }
            fn on_round_ended(&mut self, s: &mut CombatState, ended_round: i32) -> Result<(), TurnError> {
                self.calls
                    .push((Boundary::RoundEnded, ended_round, s.current_round));
                Ok(())
            }
            fn on_round_started(&mut self, s: &mut CombatState, new_round: i32) -> Result<(), TurnError> {
                self.calls
                    .push((Boundary::RoundStarted, new_round, s.current_round));
                Ok(())
            }
        }

        // ---- 轮次边界事件 ----

        #[test]
        fn a_round_boundary_reports_ended_then_started_while_a_turn_boundary_reports_neither() {
            // `CombatTurnProcessor.cs:190-205` 的顺序是**规格**：
            //   `EnqueueEvent(RoundEnded(旧轮, 当前活跃))` → `AdvanceRound()` → `EnqueueEvent(RoundStarted(新轮))`；
            // 而 `AdvanceTurn` 分支**两个事件都不发**。
            let mut s = fight(&["a", "b"]);
            let mut host = BoundaryLog::default();

            // ① AdvanceTurn（a → b）：一个轮次事件都不该有。
            advance_to_next_combatant(&mut s, &mut host).unwrap();
            assert_eq!((s.current_round, s.current_turn), (1, 2));
            assert!(host.calls.is_empty(), "AdvanceTurn 分支不该发轮次事件");

            // ② AdvanceRound（b → a）：先 `RoundEnded(旧轮 = 1)`，且**那一刻** `current_round`
            //    还是 1（自增发生在它之后）；再 `RoundStarted(新轮 = 2)`，那一刻已经是 2。
            advance_to_next_combatant(&mut s, &mut host).unwrap();
            assert_eq!((s.current_round, s.current_turn), (2, 1));
            assert_eq!(
                host.calls,
                vec![
                    (Boundary::RoundEnded, 1, 1),
                    (Boundary::RoundStarted, 2, 2),
                ],
                "顺序、参数、以及「自增发生在两者之间」都必须对得上"
            );

            // 默认宿主（`NullHost`）走同一条剧本：一次回调都没有 ⇒ 上面那两条不是空断言。
            let mut s2 = fight(&["a", "b"]);
            let mut null = NullHost;
            advance_to_next_combatant(&mut s2, &mut null).unwrap();
            advance_to_next_combatant(&mut s2, &mut null).unwrap();
            assert_ne!(host.calls.len(), 0);
            assert_eq!((s2.current_round, s2.current_turn), (2, 1));
        }

        #[test]
        fn a_round_boundary_reports_the_outgoing_active_combatant_before_the_handoff() {
            // `RoundEndedCombatEvent` 的第二个参数是**即将退场**的活跃单位（`:193-195`）。
            // 用一个"在回调里记下活跃单位"的探针钉住它 —— 落到下一个单位之后就不是这个值了。
            #[derive(Default)]
            struct ActiveAtBoundary {
                calls: Vec<(Boundary, i32, String)>,
            }
            impl TurnHost for ActiveAtBoundary {
            fn resolve_card_queue(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
                fn activate_pending_statuses(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn run_turn_started_triggers(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn resolve_pending_queues(&mut self, _: &mut CombatState) -> Result<(), TurnError> {
                    Ok(())
                }
                fn damage_over_time(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn hand_turn_end_lifecycle(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn run_turn_ended_triggers(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn decrease_timed_statuses(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn hand_is_retained(&self, _: &CombatState, _: &CombatantId) -> bool {
                    false
                }
                fn on_round_ended(&mut self, s: &mut CombatState, ended_round: i32) -> Result<(), TurnError> {
                    let who = s
                        .active_combatant_id
                        .map_or_else(String::new, |id| id.as_str().to_string());
                    self.calls.push((Boundary::RoundEnded, ended_round, who));
                    Ok(())
                }
                fn on_round_started(&mut self, s: &mut CombatState, new_round: i32) -> Result<(), TurnError> {
                    let who = s
                        .active_combatant_id
                        .map_or_else(String::new, |id| id.as_str().to_string());
                    self.calls.push((Boundary::RoundStarted, new_round, who));
                    Ok(())
                }
            }

            let mut s = fight(&["a", "b"]);
            let mut host = ActiveAtBoundary::default();
            advance_to_next_combatant(&mut s, &mut host).unwrap(); // a → b（AdvanceTurn）
            advance_to_next_combatant(&mut s, &mut host).unwrap(); // b → a（AdvanceRound）

            // 绕回发生在 b 的回合结束时：两个回调都在 `SetActiveCombatant(nxt)`（`:207`）**之前**，
            // 所以它们看到的活跃单位还是**退场者** b。
            //
            // ⚠️ 这里钉的是**入队点**语义，不是 C# **处理器**语义：C# 的两个事件只是入队，
            // 处理器要到调用方的 `ResolvePendingQueues` 才跑，那时 `SetActiveCombatant` 已经执行，
            // 于是处理器看到的活跃单位是 **a**。本内核的接缝是同步的（宿主在入队点就被调用），
            // 所以一个"在 `on_round_started` 里立刻跑 round-start 触发器"的宿主会看到旧值 ——
            // 这是同步交付与延迟交付的固有差别，已在报告"与 C# 不一致"一节写明。
            assert_eq!(
                host.calls,
                vec![
                    (Boundary::RoundEnded, 1, "b".to_string()),
                    (Boundary::RoundStarted, 2, "b".to_string()),
                ]
            );
            assert_eq!(s.active_combatant_id, Some(cid("a")), "交接在事件之后");
        }

        /// 回合末**逐张**落点策略（`CardZoneEffects.cs:413-428` 的三档）。
        ///
        /// 真实实现按"实例标记 / 卡定义"判定；turn.rs 只把 `CardSlot` 交给宿主，所以这个替身
        /// 按**卡实例 id** 判定，用来验证"逐张"这件事本身（哪张留下、哪张改道）。
        struct CardPolicyHost {
            inner: NullHost,
            /// 退化成 `standard.retained_card` 标记的那张（留在手里）。
            stay: Option<&'static str>,
            /// 落点是消耗堆的那张（`TurnEndHandDestinationZone` 不是弃牌堆）。
            to_exhaust: Option<&'static str>,
            /// 落点是 `Hand` 的那张 ⇒ 等价于留下（`:366-367` 的 `continue`）。
            to_hand: Option<&'static str>,
        }

        impl CardPolicyHost {
            fn id_of(state: &CombatState, slot: CardSlot) -> &str {
                state.card(slot).map_or("", |c| c.id.as_str())
            }
        }

        impl TurnHost for CardPolicyHost {
            fn resolve_card_queue(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
            fn activate_pending_statuses(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.activate_pending_statuses(s, a)
            }
            fn run_turn_started_triggers(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.run_turn_started_triggers(s, a)
            }
            fn resolve_pending_queues(&mut self, s: &mut CombatState) -> Result<(), TurnError> {
                self.inner.resolve_pending_queues(s)
            }
            fn damage_over_time(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.damage_over_time(s, a)
            }
            fn hand_turn_end_lifecycle(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.hand_turn_end_lifecycle(s, a)
            }
            fn run_turn_ended_triggers(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.run_turn_ended_triggers(s, a)
            }
            fn decrease_timed_statuses(&mut self, s: &mut CombatState, a: &CombatantId) -> Result<(), TurnError> {
                self.inner.decrease_timed_statuses(s, a)
            }
            fn hand_is_retained(&self, _: &CombatState, _: &CombatantId) -> bool {
                false // 整手保留是另一条路（默认宿主那条测试钉着），这里只测逐张
            }
            fn card_stays_in_hand_at_turn_end(
                &self,
                s: &CombatState,
                _: &CombatantId,
                slot: CardSlot,
            ) -> bool {
                self.stay == Some(Self::id_of(s, slot))
            }
            fn turn_end_hand_destination(
                &self,
                s: &CombatState,
                _: &CombatantId,
                slot: CardSlot,
            ) -> CardZone {
                let id = Self::id_of(s, slot);
                if self.to_exhaust == Some(id) {
                    CardZone::ExhaustPile
                } else if self.to_hand == Some(id) {
                    CardZone::Hand
                } else {
                    CardZone::DiscardPile
                }
            }
        }

        // ---- 阶段与轮次：一个三整轮的剧本 ----

        #[test]
        fn a_three_round_script_walks_the_documented_round_and_turn_sequence() {
            let cfg = standard();
            let mut host = NullHost;
            let mut s = fight(&["hero", "foe"]);
            let where_are_we = |s: &CombatState| {
                (
                    s.current_round,
                    s.current_turn,
                    s.active_combatant_id.unwrap().as_str().to_string(),
                )
            };

            // 开局：`CombatState::new` 给 round = 1 / turn = 1，`add_combatant` 把第一个加入者
            // 设为活跃单位，阶段是 WaitingToStartTurn。
            assert_eq!(where_are_we(&s), (1, 1, "hero".to_string()));
            assert_eq!(s.turn_phase, CombatTurnPhase::WaitingToStartTurn);

            let mut seen = Vec::new();
            for _ in 0..6 {
                start_current_turn(&mut s, &cfg, &mut host).unwrap();
                // start 之前 WaitingToStartTurn → 之后 TurnInProgress。
                assert_eq!(s.turn_phase, CombatTurnPhase::TurnInProgress);
                seen.push(where_are_we(&s));

                end_current_turn(&mut s, &cfg, &mut host).unwrap();
                // MarkTurnEnded 的副作用：回到 WaitingToStartTurn。
                assert_eq!(s.turn_phase, CombatTurnPhase::WaitingToStartTurn);
            }

            // 六个回合 = 三整轮。每两条一次**绕回**（`nxt <= cur`）：round + 1、turn 回 1。
            assert_eq!(
                seen,
                vec![
                    (1, 1, "hero".to_string()),
                    (1, 2, "foe".to_string()),
                    (2, 1, "hero".to_string()), // ← 绕回 ①（第 2 个回合结束时）
                    (2, 2, "foe".to_string()),
                    (3, 1, "hero".to_string()), // ← 绕回 ②
                    (3, 2, "foe".to_string()),
                ]
            );

            // 第 6 个回合结束再把回合开起来 ⇒ 进入第 4 轮的第 1 个回合：这是绕回那一步的完整效果。
            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(where_are_we(&s), (4, 1, "hero".to_string()));
        }

        #[test]
        fn end_then_start_next_advances_exactly_like_end_followed_by_start() {
            let cfg = standard();
            let mut host = NullHost;
            let mut s = fight(&["hero", "foe"]);
            start_current_turn(&mut s, &cfg, &mut host).unwrap();

            end_current_turn_and_start_next(&mut s, &cfg, &mut host).unwrap();
            assert_eq!((s.current_round, s.current_turn), (1, 2));
            assert_eq!(s.active_combatant_id, Some(cid("foe")));
            assert_eq!(s.turn_phase, CombatTurnPhase::TurnInProgress);
        }

        // ---- 拒绝：三个真实存在的断言 ----

        #[test]
        fn starting_twice_is_already_in_progress_and_ending_before_starting_is_not_in_progress() {
            let cfg = standard();
            let mut host = NullHost;
            let mut s = fight(&["hero"]);

            // 没 start 就 end ⇒ NotInProgress（`CombatState.cs:332-338`）。
            assert_eq!(end_current_turn(&mut s, &cfg, &mut host), Err(TurnError::NotInProgress));

            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            let before = s.turn_phase;
            // 已经在回合中再 start ⇒ AlreadyInProgress（`CombatState.cs:324-330`，
            // 钉在 `T:CombatTurnProcessorTests.cs:26-36`）。
            assert_eq!(
                start_current_turn(&mut s, &cfg, &mut host),
                Err(TurnError::AlreadyInProgress)
            );
            // 被拒绝的那次调用**没有**副作用。
            assert_eq!(s.turn_phase, before);
        }

        #[test]
        fn a_finished_combat_refuses_start_end_and_end_then_start() {
            let cfg = standard();
            let mut host = NullHost;
            let mut s = fight(&["hero"]);
            s.result = CombatResult::Victory;

            assert_eq!(start_current_turn(&mut s, &cfg, &mut host), Err(TurnError::NotOngoing));
            assert_eq!(end_current_turn(&mut s, &cfg, &mut host), Err(TurnError::NotOngoing));
            assert_eq!(
                end_current_turn_and_start_next(&mut s, &cfg, &mut host),
                Err(TurnError::NotOngoing)
            );
            // `Ongoing` 是**第一**道闸：它连阶段都不许改（顺序见 `:15-18`）。
            assert_eq!(s.turn_phase, CombatTurnPhase::WaitingToStartTurn);

            // 已经在回合中、但战斗结束了 ⇒ 仍然是 NotOngoing（不是"照常结束回合"）。
            s.result = CombatResult::Ongoing;
            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            s.result = CombatResult::Defeat;
            assert_eq!(end_current_turn(&mut s, &cfg, &mut host), Err(TurnError::NotOngoing));
            assert_eq!(s.turn_phase, CombatTurnPhase::TurnInProgress);
        }

        #[test]
        fn an_empty_turn_order_has_nothing_to_start_end_or_advance() {
            let cfg = standard();
            let mut host = NullHost;
            // `CombatState::new` 不带任何单位 ⇒ TurnOrder 为空（`:141-142`）。
            let mut s = CombatState::new(CombatId::new("empty").unwrap(), 1);
            assert_eq!(start_current_turn(&mut s, &cfg, &mut host), Err(TurnError::NoTurnOrder));
            assert_eq!(end_current_turn(&mut s, &cfg, &mut host), Err(TurnError::NoTurnOrder));
            assert_eq!(advance_to_next_combatant(&mut s, &mut host), Err(TurnError::NoTurnOrder));
        }

        #[test]
        fn a_downed_active_combatant_cannot_start_a_turn() {
            let cfg = standard();
            let mut host = NullHost;
            let mut s = fight(&["hero", "foe"]);
            down(&mut s, "hero");
            assert_eq!(start_current_turn(&mut s, &cfg, &mut host), Err(TurnError::ActiveNotAlive));
            assert_eq!(s.turn_phase, CombatTurnPhase::WaitingToStartTurn);
        }

        #[test]
        fn an_active_combatant_outside_the_turn_order_is_rejected() {
            let cfg = standard();
            let mut host = NullHost;
            let mut s = fight(&["hero", "foe"]);
            // 回合序里只留 foe，而活跃单位仍是 hero（`set_turn_order` 只要求 id 存在）。
            s.set_turn_order(&[cid("foe")]).unwrap();
            assert_eq!(s.active_combatant_id, Some(cid("hero")));

            assert_eq!(
                start_current_turn(&mut s, &cfg, &mut host),
                Err(TurnError::ActiveNotInTurnOrder)
            );
            assert_eq!(
                end_current_turn(&mut s, &cfg, &mut host),
                Err(TurnError::ActiveNotInTurnOrder)
            );
            assert_eq!(
                advance_to_next_combatant(&mut s, &mut host),
                Err(TurnError::ActiveNotInTurnOrder)
            );
        }

        #[test]
        fn a_combat_without_an_active_combatant_adopts_the_first_living_one() {
            // `EnsureActiveCombatantExistsInTurnOrder` 的**副作用**（`CombatTurnProcessor.cs:146-156`）：
            // 没有活跃单位时，认领回合序里第一个**存活**单位 —— 第 1 个倒下了就取第 2 个。
            let cfg = standard();
            let mut host = NullHost;
            let mut s = fight(&["hero", "foe"]);
            s.active_combatant_id = None;
            down(&mut s, "hero");
            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(s.active_combatant_id, Some(cid("foe")));

            // 一个活人都没有 ⇒ NoLivingCombatants（`:158`，与 `:211` 同一句话）。
            let mut s2 = fight(&["a", "b"]);
            s2.active_combatant_id = None;
            down(&mut s2, "a");
            down(&mut s2, "b");
            assert_eq!(
                start_current_turn(&mut s2, &cfg, &mut host),
                Err(TurnError::NoLivingCombatants)
            );
        }

        // ---- 能量补充 ----

        #[test]
        fn turn_start_refills_energy_to_the_configured_amount_not_a_hardcoded_three() {
            // 7 / 11 都不是标准包的 3：硬编码 3 的实现会在这里红。
            let mut host = NullHost;
            let hero = cid("hero");
            let mut s = fight(&["hero"]);

            for (refill, expected) in [(3, 3), (7, 7), (11, 11)] {
                // 同一份状态形状（池存在、current = 0、max = None），只换配置。
                s.combatant_mut(&hero)
                    .unwrap()
                    .set_resource(rid(ENERGY), 0, None)
                    .unwrap();
                start_current_turn(&mut s, &config(refill, 0, i32::MAX), &mut host).unwrap();
                assert_eq!(
                    resource(&s, &hero).map(|(current, _)| current),
                    Some(expected),
                    "energy_refill = {refill} 必须被读进来"
                );
                end_current_turn(&mut s, &config(refill, 0, i32::MAX), &mut host).unwrap();
            }
        }

        #[test]
        fn the_refill_target_is_the_pools_max_falling_back_to_the_configured_refill() {
            // `ResourceEffects.cs:85`：`refillTarget = resource.Max ?? DefaultMax`。
            let cfg = config(7, 0, i32::MAX);
            let mut host = NullHost;
            let hero = cid("hero");

            // ① 池存在且有 Max ⇒ 补到 Max（配置里的 7 被忽略）。
            let mut s = fight(&["hero"]);
            s.combatant_mut(&hero)
                .unwrap()
                .set_resource(rid(ENERGY), 2, Some(4))
                .unwrap();
            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(resource(&s, &hero), Some((4, Some(4))));

            // ② 池不存在 ⇒ 建一个 `current = max = DefaultMax` 的池（`:50-56`）。
            let mut s2 = fight(&["hero"]);
            start_current_turn(&mut s2, &cfg, &mut host).unwrap();
            assert_eq!(resource(&s2, &hero), Some((7, Some(7))));

            // ③ `Max = None` ⇒ 补到 DefaultMax，并且**不长出** Max。
            let mut s3 = fight(&["hero"]);
            s3.combatant_mut(&hero)
                .unwrap()
                .set_resource(rid(ENERGY), 0, None)
                .unwrap();
            start_current_turn(&mut s3, &cfg, &mut host).unwrap();
            assert_eq!(resource(&s3, &hero), Some((7, None)));
        }

        #[test]
        fn an_unspent_energy_host_carries_the_leftover_on_top_of_the_refill_and_may_exceed_the_max() {
            // `ResourceEffects.cs:84-96`：`refillTarget = (Max ?? DefaultMax) + Current`，以
            // `allowExceedingMax: carries` 写入 ⇒ **Max 不动、Current 允许超上限**。
            let cfg = config(3, 0, i32::MAX);
            let hero = cid("hero");

            // 默认宿主：补到 3。
            let mut s = fight(&["hero"]);
            s.combatant_mut(&hero)
                .unwrap()
                .set_resource(rid(ENERGY), 2, Some(3))
                .unwrap();
            let mut default_host = NullHost;
            start_current_turn(&mut s, &cfg, &mut default_host).unwrap();
            let plain = resource(&s, &hero);

            // 带法令：3 + 2 = 5，而且**超过** Max = 3 是合法的（overfill，规格 §2.5）。
            let mut s2 = fight(&["hero"]);
            s2.combatant_mut(&hero)
                .unwrap()
                .set_resource(rid(ENERGY), 2, Some(3))
                .unwrap();
            let mut carrying = PolicyHost {
                carries_energy: true,
                ..Default::default()
            };
            start_current_turn(&mut s2, &cfg, &mut carrying).unwrap();
            let carried = resource(&s2, &hero);

            assert_eq!(plain, Some((3, Some(3))));
            assert_eq!(carried, Some((5, Some(3))), "Max 不动，Current 允许超上限");
            assert_ne!(plain, carried, "两个宿主必须给出不同结果，否则断言是空的");

            // 池不存在的创建分支**先**返回（`:50-81`），法令不参与：仍是 `current = max = 3`。
            let mut s3 = fight(&["hero"]);
            let mut carrying = PolicyHost {
                carries_energy: true,
                ..Default::default()
            };
            start_current_turn(&mut s3, &cfg, &mut carrying).unwrap();
            assert_eq!(resource(&s3, &hero), Some((3, Some(3))));
        }

        // ---- 抽牌 ----

        #[test]
        fn turn_start_draws_draw_per_turn_cards_in_pile_order() {
            // 每回合 3 张（不是标准包的 5）：手牌过回合会被弃掉（另一条职责，另有用例），
            // 所以"两轮累积"要靠手牌保留的宿主来观察。
            let cfg = config(3, 3, i32::MAX);
            let hero = cid("hero");
            let mut host = RetainingHost::default();
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 10);

            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(hand(&s, &hero), 3);
            end_current_turn_and_start_next(&mut s, &cfg, &mut host).unwrap();
            // 第二轮**再抽 3 张** ⇒ 6。硬编码 5 会给 8，"抽到手牌上限 5"会给 5。
            assert_eq!(hand(&s, &hero), 6);
            assert_eq!(pile(&s, &hero, CardZone::DrawPile), 4);

            // 顺序：先入库的牌在堆顶、先被抽走（`CardZones.cs:251` 的 `RemoveAt(0)`）。
            assert_eq!(
                pile_ids(&s, &hero, CardZone::Hand),
                vec![
                    "card_000001".to_string(),
                    "card_000002".to_string(),
                    "card_000003".to_string(),
                    "card_000004".to_string(),
                    "card_000005".to_string(),
                    "card_000006".to_string(),
                ]
            );
            assert_eq!(
                pile_ids(&s, &hero, CardZone::DrawPile),
                vec![
                    "card_000007".to_string(),
                    "card_000008".to_string(),
                    "card_000009".to_string(),
                    "card_000010".to_string(),
                ]
            );
        }

        #[test]
        fn a_null_host_discards_at_turn_end_so_each_start_draws_a_fresh_draw_per_turn() {
            let cfg = config(3, 3, i32::MAX);
            let mut host = NullHost;
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 10);

            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(hand(&s, &hero), 3);
            end_current_turn_and_start_next(&mut s, &cfg, &mut host).unwrap();
            // 上一轮那 3 张进了弃牌堆，新一轮又抽 3 张。
            assert_eq!(hand(&s, &hero), 3);
            assert_eq!(pile(&s, &hero, CardZone::DiscardPile), 3);
            assert_eq!(pile(&s, &hero, CardZone::DrawPile), 4);
        }

        #[test]
        fn the_turn_start_draw_count_is_the_hosts_number_and_the_hand_ceiling_still_applies() {
            // `Cards/CardTurnLifecycleEventHandlers.cs:25-31`：张数先过 `TurnStartDraw` 修饰流水线
            // （宿主），**再**在抽牌入口按 `MaxHandSize` 裁剪（`:31-46`）。宿主返回的值**不是**
            // 最终值 —— 裁剪仍然归回合机，所以宿主不该自己裁。
            let hero = cid("hero");

            // ① 默认 = `draw_per_turn` 原值 3；覆盖 +2 ⇒ 5。
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 20);
            let mut default_host = NullHost;
            start_current_turn(&mut s, &config(3, 3, i32::MAX), &mut default_host).unwrap();
            let plain = hand(&s, &hero);

            let mut s2 = fight(&["hero"]);
            stock_deck(&mut s2, &hero, 20);
            let mut generous = PolicyHost {
                draw_delta: 2,
                ..Default::default()
            };
            start_current_turn(&mut s2, &config(3, 3, i32::MAX), &mut generous).unwrap();
            let modified = hand(&s2, &hero);

            assert_eq!(plain, 3);
            assert_eq!(modified, 5);
            assert_ne!(plain, modified, "宿主没被问过的话这里会相等");

            // ② 上限 4、修饰后要 5 ⇒ 回合机裁到 4，第 5 张**留在抽牌堆里**（不是抽出来再丢）。
            let mut s3 = fight(&["hero"]);
            stock_deck(&mut s3, &hero, 20);
            let mut generous = PolicyHost {
                draw_delta: 2,
                ..Default::default()
            };
            start_current_turn(&mut s3, &config(3, 3, 4), &mut generous).unwrap();
            assert_eq!(hand(&s3, &hero), 4, "宿主不该自己裁，回合机的入口裁剪必须还在");
            assert_eq!(pile(&s3, &hero, CardZone::DrawPile), 16);

            // ③ 修饰把张数压到 <= 0 ⇒ 一张都不抽（参考的 `cardsToDraw <= 0 → return`）。
            let mut s4 = fight(&["hero"]);
            stock_deck(&mut s4, &hero, 20);
            let mut stingy = PolicyHost {
                draw_delta: -5,
                ..Default::default()
            };
            start_current_turn(&mut s4, &config(3, 3, i32::MAX), &mut stingy).unwrap();
            assert_eq!(hand(&s4, &hero), 0);
            assert_eq!(pile(&s4, &hero, CardZone::DrawPile), 20);
        }

        #[test]
        fn max_hand_size_clamps_the_draw_at_the_entry_not_after_the_fact() {
            // 上限 4、每回合要抽 5、牌组 10 ⇒ 一轮之后手牌必须是 **4**（不是 5），
            // 而且第 5 张**根本没被抽**（还在抽牌堆里）：`CardZoneEffects.cs:28-46`。
            let cfg = config(3, 5, 4);
            let hero = cid("hero");
            let mut host = RetainingHost::default();
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 10);

            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(hand(&s, &hero), 4);
            assert_eq!(
                pile(&s, &hero, CardZone::DrawPile),
                6,
                "越过上限的牌不该先抽出来再丢掉"
            );

            // 手牌已经在上限上（保留宿主让它活过回合末）⇒ `wanted == 0`：一张都不抽，
            // 也没有牌被凭空丢掉（`:36-45`）。
            end_current_turn_and_start_next(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(hand(&s, &hero), 4);
            assert_eq!(pile(&s, &hero, CardZone::DrawPile), 6);
            assert_eq!(pile(&s, &hero, CardZone::DiscardPile), 0);
        }

        #[test]
        fn a_dry_draw_pile_reshuffles_the_discard_in_engine_order_and_pays_one_random_step() {
            // `CardZoneEffects.cs:49-82` 的循环：抽光抽牌堆 → **重洗弃牌堆**继续抽，并
            // `AdvanceRandomStep()`（`:69`）。重洗的置换来自
            // `CreateShuffledIndexes(discard.Count, RandomSeed, RandomStep)`，目标是
            // 「旧抽牌堆 ++ [弃牌堆[order[0..]]]」（`CardZones.cs:260-297`）。
            //
            // ⚠️ 旧实现只抽到抽牌堆空就停（且本文件曾有一条用例钉住"不重洗"）—— 那条契约是错的。
            let cfg = standard(); // 每回合抽 5
            let mut host = NullHost;
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 2);
            for n in [90, 91, 92] {
                s.push_card(&hero, CardZone::DiscardPile, card(n)).unwrap();
            }
            assert_eq!(s.random_step, 0);

            start_current_turn(&mut s, &cfg, &mut host).unwrap();

            assert_eq!(hand(&s, &hero), 5, "抽牌堆 2 + 弃牌堆 3 = 5 张，全部抽到手（旧实现只有 2）");
            assert_eq!(pile(&s, &hero, CardZone::DiscardPile), 0, "弃牌堆被搬空");
            assert_eq!(pile(&s, &hero, CardZone::DrawPile), 0);
            assert_eq!(s.random_step, 1, "重洗消耗**一次**随机步，而 `step=` 是哈希可见的");

            // 顺序也必须逐位一致：先抽牌堆原序，再按 `shuffle_indexes(seed, 0)` 的置换追加。
            let mut order = [0u8; 3];
            crate::rng::shuffle_indexes(&mut order, s.random_seed, 0);
            let discard = ["card_000090", "card_000091", "card_000092"];
            let mut expected = vec!["card_000001".to_string(), "card_000002".to_string()];
            for i in 0..3 {
                expected.push(discard[order[i] as usize].to_string());
            }
            assert_eq!(pile_ids(&s, &hero, CardZone::Hand), expected);

            // 对照：同一个剧本但**弃牌堆为空** ⇒ 不得重洗、不得推进随机步、只能抽到 2 张。
            // 两条路必须给出不同结果，否则上面那条与"什么都没做"没法区分。
            let mut plain = fight(&["hero"]);
            stock_deck(&mut plain, &hero, 2);
            let mut host2 = NullHost;
            start_current_turn(&mut plain, &cfg, &mut host2).unwrap();
            assert_eq!(hand(&plain, &hero), 2);
            assert_eq!(plain.random_step, 0, "没洗牌就不该消耗随机步");
            assert_ne!(hand(&s, &hero), hand(&plain, &hero));
        }

        #[test]
        fn a_dry_pile_whose_discard_is_smaller_than_the_draw_draws_short_without_an_error() {
            // 抽牌堆 2 + 弃牌堆 1、要抽 5：重洗一次、再抽 1 张，然后弃牌堆空了 ⇒ `break`
            // （`CardZoneEffects.cs:59-60` 的提前退出）。**抽不满不是错误**，参考实现也一样。
            let cfg = standard();
            let mut host = NullHost;
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 2);
            s.push_card(&hero, CardZone::DiscardPile, card(99)).unwrap();

            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(hand(&s, &hero), 3);
            assert_eq!(pile(&s, &hero, CardZone::DrawPile), 0);
            assert_eq!(pile(&s, &hero, CardZone::DiscardPile), 0);
            assert_eq!(s.random_step, 1);
        }

        // ---- 清 Block ----

        #[test]
        fn the_turn_start_hooks_run_in_the_reference_order_and_the_card_queue_comes_before_the_drain() {
            // 七步顺序里第 5 步被拆成了两个钩子（见 `TurnHost::resolve_card_queue` 的文档）。
            // 这条测试把"谁先谁后"钉成字节序列，顺序写反就红：
            //
            //   p  step 2  pending 转正
            //   t  step 3  turn-start 触发器
            //   q  step 4a QueuePile 解析        ← 2026-10-17 新加的那个
            //   d  step 4b 效果队列排空
            //   o  step 7  DoT
            //   d  TurnStarted 跑完之后的再排空（`start_current_turn` 末尾）
            //
            // 抽牌与清 Block 不是钩子（本模块自己做），所以它们不在这串里 ——
            // 它们的位置由别的测试钉（`turn_start_draws_…`、`turn_start_clears_…`）。
            let cfg = standard();
            let mut log: std::vec::Vec<u8> = std::vec::Vec::new();
            {
                let mut host = OrderProbe { log: &mut log };
                let mut s = fight(&["hero"]);
                start_current_turn(&mut s, &cfg, &mut host).unwrap();
            }
            assert_eq!(
                std::string::String::from_utf8(log).unwrap(),
                "ptqdod",
                "turn-start 的钩子顺序变了 —— 顺序是规格的一部分，不是实现细节"
            );
        }

        #[test]
        fn a_queue_card_that_gains_block_survives_a_turn_that_started_at_zero_block() {
            // 参考：回合入口（处理器时点）格挡 = 0 ⇒ 清空请求**根本不入队**
            // （`DefensivePoolEffects.cs:305-306`），于是队列卡后加的 11 点活下来。
            // 这是"判定时点 ≠ 生效时点"唯一能被观察到的格子。
            let cfg = standard();
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            let mut host = QueueGainsBlock {
                inner: NullHost,
                amount: 11,
                retain_block: false,
                queued: true,
            };

            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(
                pool(&s, &hero, BLOCK),
                Some((11, None)),
                "入口格挡=0 ⇒ 不清；队列卡加的 11 必须活着"
            );
        }

        #[test]
        fn a_queue_card_that_gains_block_is_wiped_when_the_turn_started_with_block() {
            // 同一份内容、同一个宿主，只把入口格挡改成 10：清空请求入队，且排在
            // `gainBlock` 之后生效 ⇒ 最终是 0（`10+11=21` 被抹成 0，不是 21、也不是 11）。
            // 与上一条成对：**两条必须给出不同结果**，否则说明采样点根本没被读到。
            let cfg = standard();
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            s.combatant_mut(&hero)
                .unwrap()
                .set_defensive_pool(dpid(BLOCK), 10, Some(10))
                .unwrap();
            let mut host = QueueGainsBlock {
                inner: NullHost,
                amount: 11,
                retain_block: false,
                queued: true,
            };

            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(
                pool(&s, &hero, BLOCK),
                Some((0, Some(10))),
                "入口格挡=10 ⇒ 清；队列卡加的 11 一起被抹掉，但 Max 不动"
            );
        }

        #[test]
        fn a_retaining_host_skips_the_queue_gained_block_too() {
            // 保留判定同样在**回合入口**采样（`DefensivePoolEffects.cs:308-314` 也在处理器时点）。
            // 这条钉住"保留 + 队列加格挡 ⇒ 两者都保留"，也就是 10+11=21 原样。
            let cfg = standard();
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            s.combatant_mut(&hero)
                .unwrap()
                .set_defensive_pool(dpid(BLOCK), 10, Some(10))
                .unwrap();
            let mut host = QueueGainsBlock {
                inner: NullHost,
                amount: 11,
                retain_block: true,
                queued: true,
            };

            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(pool(&s, &hero, BLOCK), Some((21, Some(10))));
        }

        #[test]
        fn turn_start_clears_the_configured_block_pool_and_keeps_its_max() {
            let cfg = standard();
            let mut host = NullHost;
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            s.combatant_mut(&hero)
                .unwrap()
                .set_defensive_pool(dpid(BLOCK), 11, Some(11))
                .unwrap();

            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            // 清零但保留 Max（`DefensivePoolEffects.cs:197` 的 `pool.SetCurrent(0)` 不动 Max）。
            assert_eq!(pool(&s, &hero, BLOCK), Some((0, Some(11))));
        }

        #[test]
        fn turn_start_clears_only_the_configured_pool() {
            let cfg = standard(); // block_pool = standard.block
            let mut host = NullHost;
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            s.combatant_mut(&hero)
                .unwrap()
                .set_defensive_pool(dpid(BLOCK), 5, Some(5))
                .unwrap();
            s.combatant_mut(&hero)
                .unwrap()
                .set_defensive_pool(dpid("standard.other_guard"), 9, Some(9))
                .unwrap();

            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(pool(&s, &hero, BLOCK), Some((0, Some(5))));
            // `TurnConfig.block_pool` 真的被读了：别的池一根汗毛都不动。
            assert_eq!(pool(&s, &hero, "standard.other_guard"), Some((9, Some(9))));
        }

        #[test]
        fn turn_start_does_not_create_a_block_pool_that_was_never_there() {
            // 参考实现是 `TryGetValue` 失败即跳过（`DefensivePoolEffects.cs:305`）：凭空"清零"出
            // 一个池条目会改变快照，所以这里必须什么都不做。
            let cfg = standard();
            let mut host = NullHost;
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            assert_eq!(pool(&s, &hero, BLOCK), None);

            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(pool(&s, &hero, BLOCK), None);
        }

        #[test]
        fn a_retaining_host_keeps_the_block_pool_alive_while_the_default_host_clears_it() {
            // `DefensivePoolEffects.cs:294-314`：带 `RetainBlockTag` 的状态（Barricade）让**每一个**
            // "回合开始清空"的池跳过清空。跳过 ≠ 删池 ≠ 清零：池连 Max 一起原样保留。
            let cfg = standard();
            let hero = cid("hero");

            let mut s = fight(&["hero"]);
            s.combatant_mut(&hero)
                .unwrap()
                .set_defensive_pool(dpid(BLOCK), 11, Some(11))
                .unwrap();
            let mut default_host = NullHost;
            start_current_turn(&mut s, &cfg, &mut default_host).unwrap();
            let cleared = pool(&s, &hero, BLOCK);

            let mut s2 = fight(&["hero"]);
            s2.combatant_mut(&hero)
                .unwrap()
                .set_defensive_pool(dpid(BLOCK), 11, Some(11))
                .unwrap();
            let mut retaining = PolicyHost {
                block_retained: true,
                ..Default::default()
            };
            start_current_turn(&mut s2, &cfg, &mut retaining).unwrap();
            let kept = pool(&s2, &hero, BLOCK);

            assert_eq!(cleared, Some((0, Some(11))));
            assert_eq!(kept, Some((11, Some(11))), "抑制清空，但池不能被删掉");
            assert_ne!(cleared, kept, "两个宿主必须给出不同结果");

            // 抑制也不会凭空造出一个原来没有的池（参考在 `TryGetValue` 失败时先 `continue`）。
            let mut s3 = fight(&["hero"]);
            let mut retaining = PolicyHost {
                block_retained: true,
                ..Default::default()
            };
            start_current_turn(&mut s3, &cfg, &mut retaining).unwrap();
            assert_eq!(pool(&s3, &hero, BLOCK), None);
        }

        // ---- 弃手牌 ----

        #[test]
        fn turn_end_discards_the_hand_and_a_retaining_host_leaves_it_alone() {
            // 抽 3 张（不是标准包的 5），手牌里就正好是那 3 张。
            let cfg = config(3, 3, i32::MAX);
            let hero = cid("hero");

            // ① `NullHost`：手牌 3 张，end 之后 Hand 空、DiscardPile 3。
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 10);
            let mut null_host = NullHost;
            start_current_turn(&mut s, &cfg, &mut null_host).unwrap();
            assert_eq!(hand(&s, &hero), 3);
            end_current_turn(&mut s, &cfg, &mut null_host).unwrap();
            let discarded = hand(&s, &hero);
            assert_eq!(discarded, 0);
            assert_eq!(pile(&s, &hero, CardZone::DiscardPile), 3);
            assert_eq!(pile(&s, &hero, CardZone::DrawPile), 7);

            // ② 同一个剧本、换一个"手牌保留"的宿主：手牌**没被动**。
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 10);
            let mut retaining = RetainingHost::default();
            start_current_turn(&mut s, &cfg, &mut retaining).unwrap();
            end_current_turn(&mut s, &cfg, &mut retaining).unwrap();
            let kept = hand(&s, &hero);

            assert_eq!(kept, 3, "保留宿主下弃手牌必须被抑制");
            assert_eq!(pile(&s, &hero, CardZone::DiscardPile), 0);
            assert_eq!(pile(&s, &hero, CardZone::Hand), 3);
            // 两条路必须给出**不同**的结果，否则上面两条都是空断言。
            assert_ne!(discarded, kept);
        }

        #[test]
        fn turn_end_moves_each_card_to_its_own_destination_while_the_default_host_discards_all() {
            // `CardZoneEffects.cs:413-428` 是**逐张**判定，不是"整堆搬"：
            //   ① `card_stays_in_hand_at_turn_end`（实例标记 / 定义标记）⇒ 留下；
            //   ② 落点写 `Hand` ⇒ 等价于留下（`:366-367` 的 `continue`）；
            //   ③ 其余按 `turn_end_hand_destination`（默认弃牌堆），落点 `Bottom` 且**保序**。
            let cfg = config(3, 5, i32::MAX);
            let hero = cid("hero");

            // ① 默认宿主：整手 5 张全进弃牌堆，按原序。
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 10);
            let mut default_host = NullHost;
            start_current_turn(&mut s, &cfg, &mut default_host).unwrap();
            let default_moved = discard_hand(&mut s, &hero, &mut default_host).unwrap();
            assert_eq!(default_moved, 5);
            assert_eq!(hand(&s, &hero), 0);
            assert_eq!(
                pile_ids(&s, &hero, CardZone::DiscardPile),
                vec![
                    "card_000001".to_string(),
                    "card_000002".to_string(),
                    "card_000003".to_string(),
                    "card_000004".to_string(),
                    "card_000005".to_string(),
                ]
            );

            // ② 逐张策略宿主：2 号留下（①档）、4 号改道消耗堆（③档里"不是弃牌堆"的那种）、
            //    3 号落点写 `Hand`（②档）；1 号与 5 号进弃牌堆且**保序**。
            //    搬走 3 张（1、4、5）—— "改道消耗堆"也是搬走，只是目的地不同。
            let mut s2 = fight(&["hero"]);
            stock_deck(&mut s2, &hero, 10);
            let mut host = CardPolicyHost {
                inner: NullHost,
                stay: Some("card_000002"),
                to_exhaust: Some("card_000004"),
                to_hand: Some("card_000003"),
            };
            start_current_turn(&mut s2, &cfg, &mut host).unwrap();
            let moved = discard_hand(&mut s2, &hero, &mut host).unwrap();

            assert_eq!(moved, 3, "1 号与 5 号进弃牌堆、4 号进消耗堆；2 号与 3 号留下");
            assert_eq!(
                pile_ids(&s2, &hero, CardZone::Hand),
                vec!["card_000002".to_string(), "card_000003".to_string()]
            );
            assert_eq!(
                pile_ids(&s2, &hero, CardZone::DiscardPile),
                vec!["card_000001".to_string(), "card_000005".to_string()],
                "同一个目的堆内部必须保持手牌原序"
            );
            assert_eq!(
                pile_ids(&s2, &hero, CardZone::ExhaustPile),
                vec!["card_000004".to_string()]
            );
            // 两个宿主必须给出不同结果，否则上面每一条都是空断言。
            assert_ne!(default_moved, moved);
        }

        #[test]
        fn turn_end_discard_returns_zero_when_the_only_card_left_is_scheduled_to_stay() {
            // 只剩一张、且它的落点写着 `Hand` ⇒ 返回 0，**不是**错误（`:366-367` 的 `continue`）。
            let cfg = config(3, 3, i32::MAX);
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 10);
            let mut default_host = NullHost;
            start_current_turn(&mut s, &cfg, &mut default_host).unwrap();
            assert_eq!(hand(&s, &hero), 3);

            // 只有 1 号的落点是 `Hand` ⇒ 它留下，2/3 号进弃牌堆（逐张性的第二次物证：
            // 同一份手牌里"一张不动、两张动"）。
            let mut host = CardPolicyHost {
                inner: NullHost,
                stay: None,
                to_exhaust: None,
                to_hand: Some("card_000001"),
            };
            assert_eq!(discard_hand(&mut s, &hero, &mut host).unwrap(), 2);
            assert_eq!(
                pile_ids(&s, &hero, CardZone::Hand),
                vec!["card_000001".to_string()]
            );
            assert_eq!(pile(&s, &hero, CardZone::DiscardPile), 2);

            // 手牌只剩那张"不动"的 ⇒ 一张都不搬、也不是错误。
            assert_eq!(discard_hand(&mut s, &hero, &mut host).unwrap(), 0);
            assert_eq!(hand(&s, &hero), 1);
            // 对照：默认宿主会把它弃掉 ⇒ 两条路结果不同。
            assert_eq!(discard_hand(&mut s, &hero, &mut default_host).unwrap(), 1);
            assert_eq!(hand(&s, &hero), 0);
        }

        #[test]
        fn discard_hand_moves_the_hand_to_the_discard_pile_in_order_and_reports_the_count() {
            let cfg = config(3, 3, i32::MAX);
            let mut host = NullHost;
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 10);
            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            assert_eq!(hand(&s, &hero), 3);

            // 保留宿主 ⇒ 一张不动、返回 0（`hand_is_retained` 先判）。
            assert_eq!(discard_hand(&mut s, &hero, &mut RetainingHost::default()).unwrap(), 0);
            assert_eq!(pile(&s, &hero, CardZone::Hand), 3);
            assert_eq!(pile(&s, &hero, CardZone::DiscardPile), 0);

            // `NullHost` ⇒ 整堆按 `Bottom` 搬到弃牌堆，**保序**。
            assert_eq!(discard_hand(&mut s, &hero, &mut NullHost).unwrap(), 3);
            assert_eq!(hand(&s, &hero), 0);
            assert_eq!(
                pile_ids(&s, &hero, CardZone::DiscardPile),
                vec![
                    "card_000001".to_string(),
                    "card_000002".to_string(),
                    "card_000003".to_string(),
                ]
            );

            // 已经空了再弃一次 ⇒ 0 张，不是错误。
            assert_eq!(discard_hand(&mut s, &hero, &mut NullHost).unwrap(), 0);

            // 未知单位 ⇒ 报错，不静默"成功弃了 0 张"。
            assert_eq!(
                discard_hand(&mut s, &cid("nobody"), &mut NullHost),
                Err(TurnError::Capacity(CapacityError::MissingCombatant))
            );
        }

        // ---- 推进：跳过倒下单位、绕回、清临时规则 ----

        #[test]
        fn advancing_skips_downed_combatants_and_wraps_the_round_by_index() {
            let mut host = NullHost;
            let mut s = fight(&["a", "b", "c"]);
            down(&mut s, "b");
            assert_eq!(s.active_combatant_id, Some(cid("a")));

            let mut seen = vec![s.active_combatant_id.unwrap().as_str().to_string()];
            let mut counters = Vec::new();
            for _ in 0..3 {
                advance_to_next_combatant(&mut s, &mut host).unwrap();
                seen.push(s.active_combatant_id.unwrap().as_str().to_string());
                counters.push((s.current_round, s.current_turn));
            }

            // 倒下的 b 一次都没被激活：a → c → a → c。
            assert_eq!(seen, vec!["a", "c", "a", "c"]);
            // a → c 是同轮内的推进（turn + 1）；c → a 是绕回（round + 1、turn = 1）。
            assert_eq!(counters, vec![(1, 2), (2, 1), (2, 2)]);
        }

        #[test]
        fn advancing_past_every_downed_combatant_reports_no_living_combatants() {
            let mut host = NullHost;
            let mut s = fight(&["a", "b", "c"]);
            down(&mut s, "a");
            down(&mut s, "b");
            down(&mut s, "c");

            assert_eq!(
                advance_to_next_combatant(&mut s, &mut host),
                Err(TurnError::NoLivingCombatants)
            );
            // 失败不改坏状态：计数与活跃单位原地不动（`CombatTurnProcessor.cs:211`）。
            assert_eq!((s.current_round, s.current_turn), (1, 1));
            assert_eq!(s.active_combatant_id, Some(cid("a")));
        }

        #[test]
        fn advancing_a_turn_or_a_round_removes_only_the_expired_temporary_rules() {
            // 参考实现（`CombatState.cs:572-592`）：
            //   `AdvanceTurn`  = `CurrentTurn++` 然后标记 + 移除；
            //   `AdvanceRound` = `CurrentRound++; CurrentTurn = 1` 然后**两个 Mark 都做**再移除。
            // 所以**没有到期字段**的规则会活过两种边界，而到期判定在"递增之后" —— 顺序反了会让
            // "本回合到期"的规则早一回合消失。
            //
            // ⚠️ 这条用例**反转**了本文件曾钉过的错误契约（"边界清空一切"）。旧契约是错的：
            // `tr=` 行是哈希可见的，整表清空与"只过期"在快照上就是两种状态。
            let mut host = NullHost;
            let mut s = fight(&["a", "b"]);
            let rule = |n: usize| {
                TemporaryRule::new(
                    TriggeredEffectDefinitionId::new(&format!("tr_{n:06}")).unwrap(),
                    EventTypeName::new("RogueDeck.Core.Combat.RoundEndedCombatEvent").unwrap(),
                    1,
                    1,
                )
            };
            assert_eq!(rule_ids(&s), Vec::<String>::new());

            // 三条规则：① 无到期字段 ② 本回合到期 ③ 本轮到期。
            s.add_temporary_rule(rule(1)).unwrap();
            s.add_temporary_rule(rule(2).with_expires_after_turn(1)).unwrap();
            s.add_temporary_rule(rule(3).with_expires_after_round(1)).unwrap();
            assert_eq!((s.current_round, s.current_turn), (1, 1));

            // ② AdvanceTurn（a → b，turn 1 → 2）：只有"本回合到期"的那条消失。
            //    `tr_000003` 只带 `expires_after_round`，它**不**在回合边界判定 —— 那正是
            //    "不能提前一回合消失"的那一半断言。
            advance_to_next_combatant(&mut s, &mut host).unwrap();
            assert_eq!((s.current_round, s.current_turn), (1, 2));
            assert_eq!(
                rule_ids(&s),
                vec!["tr_000001".to_string(), "tr_000003".to_string()],
                "回合边界只移除 `expires_after_turn` 已经过去的规则（旧实现会清空整表 ⇒ 这里红）"
            );
            // 两个方向都必须排除，否则"全部清空"和"一条都不动"这两种坏实现里总有一种能骗过断言。
            assert_ne!(rule_ids(&s), Vec::<String>::new(), "不是全清 —— 那是旧实现的错契约");
            assert_ne!(
                rule_ids(&s),
                vec![
                    "tr_000001".to_string(),
                    "tr_000002".to_string(),
                    "tr_000003".to_string(),
                ],
                "也不是一条都不动 —— 那说明到期判定恒为 false"
            );

            // ③ AdvanceRound（b → a，round 2 / turn 1）：只有"本轮到期"的那条消失；
            //    无到期字段的 `tr_000001` 活过了两种边界。
            advance_to_next_combatant(&mut s, &mut host).unwrap();
            assert_eq!((s.current_round, s.current_turn), (2, 1));
            assert_eq!(
                rule_ids(&s),
                vec!["tr_000001".to_string()],
                "没有到期字段的规则必须活过轮次边界"
            );

            // ④ 再装一条"本轮到期、但轮次还没到"的规则：回合边界不许动它。
            s.add_temporary_rule(rule(4).with_expires_after_round(2)).unwrap();
            advance_to_next_combatant(&mut s, &mut host).unwrap(); // AdvanceTurn：turn 1 → 2
            assert_eq!((s.current_round, s.current_turn), (2, 2));
            assert_eq!(
                rule_ids(&s),
                vec!["tr_000001".to_string(), "tr_000004".to_string()],
                "还没到期的规则一条都不许提前消失"
            );

            // ⑤ AdvanceRound（round 2 → 3）：`tr_000004` 到期走了，`tr_000001` 四个边界之后仍在。
            advance_to_next_combatant(&mut s, &mut host).unwrap();
            assert_eq!((s.current_round, s.current_turn), (3, 1));
            assert_eq!(rule_ids(&s), vec!["tr_000001".to_string()]);
        }

        // ---- 冻结契约 #4：一步之后战斗结束就立刻停 ----

        #[test]
        fn a_combat_that_ends_in_the_start_steps_stops_there_and_does_not_advance() {
            // 在 turn-start 的**第 4 步**（触发器）把战斗判成 Victory ⇒
            // 第 6 步（抽牌）与第 7 步（清 Block）必须**没有**发生，而第 2 步（补能量）必须
            // **已经**发生 —— 后半句同时钉住了"补能量在触发器之前"这个顺序。
            let cfg = standard();
            let hero = cid("hero");
            let mut s = fight(&["hero"]);
            stock_deck(&mut s, &hero, 10);
            s.combatant_mut(&hero)
                .unwrap()
                .set_defensive_pool(dpid(BLOCK), 5, Some(5))
                .unwrap();
            let mut host = EndsCombatAt(Hook::TurnStartTriggers);

            // 战斗结束不是错误：回合机把"结束"当正常终止。
            start_current_turn(&mut s, &cfg, &mut host).unwrap();

            assert_eq!(s.result, CombatResult::Victory);
            assert_eq!(
                s.turn_phase,
                CombatTurnPhase::TurnInProgress,
                "阶段在第 4 步之前就已经转了（`MarkTurnStarted`）"
            );
            assert_eq!(
                resource(&s, &hero).map(|(current, _)| current),
                Some(3),
                "第 2 步必须已经跑过"
            );
            assert_eq!(hand(&s, &hero), 0, "第 6 步不该跑");
            assert_eq!(pool(&s, &hero, BLOCK), Some((5, Some(5))), "第 7 步不该跑");
            assert_eq!((s.current_round, s.current_turn), (1, 1), "不推进回合");
            assert_eq!(s.active_combatant_id, Some(hero));
        }

        #[test]
        fn a_combat_that_ends_in_the_turn_ended_handlers_neither_discards_nor_advances() {
            // 契约 #4 在 turn-end 上的写法（`CombatTurnProcessor.cs:72-73`）：TurnEnded 消化完之后
            // 若战斗已结束就 return。这里在 TurnEnded 的**第 ① 步**结束战斗 ⇒ 第 ② 步（弃手牌）
            // 不该发生，③④ 与 Advance 都不该发生。
            let cfg = standard();
            let hero = cid("hero");
            let mut s = fight(&["hero", "foe"]);
            stock_deck(&mut s, &hero, 10);
            let mut null_host = NullHost;
            start_current_turn(&mut s, &cfg, &mut null_host).unwrap();
            assert_eq!(hand(&s, &hero), 5);

            let mut host = EndsCombatAt(Hook::TurnEndLifecycle);
            end_current_turn(&mut s, &cfg, &mut host).unwrap();

            assert_eq!(s.result, CombatResult::Defeat);
            assert_eq!(
                s.turn_phase,
                CombatTurnPhase::WaitingToStartTurn,
                "`MarkTurnEnded` 已经跑过"
            );
            assert_eq!(hand(&s, &hero), 5, "弃手牌不该发生");
            assert_eq!(pile(&s, &hero, CardZone::DiscardPile), 0);
            assert_eq!((s.current_round, s.current_turn), (1, 1), "没有推进");
            assert_eq!(s.active_combatant_id, Some(hero), "活跃单位没换");
        }

        #[test]
        fn the_skip_loop_hands_the_next_turn_to_a_living_combatant() {
            // 契约 #7 的另一半：`end_current_turn` 的 ⑤ 步会在交接点上跳过被 ④ 打死的单位。
            // 这里让"回合结束"的第 ① 步先把**下一个**单位打倒，回合机必须自己再推一格。
            let cfg = standard();
            let mut s = fight(&["hero", "foe", "third"]);
            // hero 结束回合 ⇒ 推进到 foe 之前，foe 先倒下。
            down(&mut s, "foe");
            let mut host = NullHost;
            start_current_turn(&mut s, &cfg, &mut host).unwrap();
            end_current_turn(&mut s, &cfg, &mut host).unwrap();
            // 直接推一格会落到 foe 上，但它倒着 —— 所以这里必须先跳过它到 third。
            assert_eq!(s.active_combatant_id, Some(cid("third")));
            assert_eq!((s.current_round, s.current_turn), (1, 2));
        }

        #[test]
        fn the_skip_loop_keeps_advancing_while_the_handed_off_combatant_keeps_dying() {
            // ⑤ 步是"刚交接到的单位被 ④ 打死了就再推一格"。用一个"在某次排空里把活跃单位打倒"的
            // 宿主让它连续发生：三个单位一个个倒下之后没有可交接的人 —— 参考实现在那里抛
            // `"no living combatants in the turn order"`（`:211`），本内核返回 `NoLivingCombatants`。
            //
            // ⑤ 的 `guard <= TurnOrder.Count` 是这条路的**结构性兜底**：万一"每轮至少打倒一个"这个
            // 收敛理由不成立，上限保证循环一定会停。这条用例走的是收敛那条路（走不到上限）。
            struct DownsTheActive {
                armed: bool,
            }
            impl TurnHost for DownsTheActive {
            fn resolve_card_queue(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                Ok(())
            }
                fn activate_pending_statuses(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn run_turn_started_triggers(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn resolve_pending_queues(&mut self, s: &mut CombatState) -> Result<(), TurnError> {
                    if self.armed {
                        if let Some(active) = s.active_combatant_id {
                            down(s, active.as_str());
                        }
                    }
                    Ok(())
                }
                fn damage_over_time(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn hand_turn_end_lifecycle(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn run_turn_ended_triggers(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn decrease_timed_statuses(&mut self, _: &mut CombatState, _: &CombatantId) -> Result<(), TurnError> {
                    Ok(())
                }
                fn hand_is_retained(&self, _: &CombatState, _: &CombatantId) -> bool {
                    false
                }
            }

            let cfg = standard();
            let mut s = fight(&["a", "b", "c"]);
            let mut host = DownsTheActive { armed: false };
            start_current_turn(&mut s, &cfg, &mut host).unwrap(); // 未武装：start 内部不动手
            host.armed = true;

            assert_eq!(
                end_current_turn(&mut s, &cfg, &mut host),
                Err(TurnError::NoLivingCombatants)
            );
            // ⑤ 确实转了几圈才收场：a → b → c 两次交接都发生了（turn 走到 3），第三个交接点没人可交接。
            assert_eq!((s.current_round, s.current_turn), (1, 3));
            assert_eq!(s.active_combatant_id, Some(cid("c")));
            // 状态没被改坏。
            assert_eq!(s.turn_order().len(), 3);
            assert_eq!(s.combatants().len(), 3);
        }
    }
}
