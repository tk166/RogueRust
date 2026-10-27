//! 回合宿主的**真实实现** —— 把 `turn.rs` 那 9 个钩子接到效果执行器上。
//!
//! **规格**：`docs/spec/battle-loop-hooks.md`（927 行，逐行核对过参考实现）。
//!
//! # 为什么需要这个模块
//!
//! `turn.rs` 把"回合里的效果"切成了 9 个钩子，唯一的实现是 `NullHost` —— **全是空实现**。
//! 于是内核今天能推进回合（阶段流转、补能量、抽牌、清格挡、弃手牌），
//! 但**回合里的真实效果一件都不会发生**：
//!
//! * poison / paperwork 的层数衰减不会发生（挂在 turn-end 触发器上）⇒ **毒会永久叠加**；
//! * turn-start / turn-end 触发程序一条都不跑；
//! * DoT 不结算；
//! * `panic` 的"每回合少抽 1"不生效（`turn_start_draw_count` 的默认值不够）。
//!
//! 参考实现里这些都不是"回合机"的一部分，而是挂在回合机上的**处理器**；
//! `TurnHost` 就是那条缝，本模块是缝的另一侧。
//!
//! # 契约已经冻结在别处
//!
//! 本模块**不重新定义**接口：语义契约就是 `turn.rs` 的 `TurnHost`（9 个必做钩子 +
//! 7 个带默认值的策略钩子），行为契约是上面那份规格书。所以这里没有"冻结的结构体签名"
//! 要遵守 —— 实现形状（要不要 `ContentHost`、持不持 `Content`、怎么记触发器深度）由实现方定。
//!
//! 三条必须守的：
//!
//! 1. **钩子里的错误必须能区分"内容配错了"和"内核还没做到"** —— 后者要响亮拒绝，
//!    不能退化成"这一步什么都不做"（那正是 `NullHost` 的错，只是换了个地方）。
//! 2. **DoT 必须走 `DamageKind::Dot` 的那条修正器路径**，不能复用 `Direct`：
//!    否则力量/虚弱/易伤会把 DoT 一起放大，而那是**静默算错**。
//!    （裁决见 `docs/port-plan.md` §36.4-5.4：另加 `exec::resolve_damage_of_kind`，不改老签名。）
//! 3. **每条"这一步现在无事可做"的判定都要有实测依据**（例如"镜像 23/23 状态的
//!    `UsesDuration = false`"），不能靠"大概不需要"。
//!
//! # 错误面：`HostError`（细节）与 `TurnError::Host`（类别）是两个粒度，不是两条通道
//!
//! `TurnHost` 的 9 个方法返回 `Result<(), TurnError>`。`TurnError` 原来只有参考实现的八个
//! `Ensure*` 理由 + `Capacity`，**没有"宿主失败"这一条** —— 参考的效果处理器是从
//! `ResolvePendingQueues` 里直接抛异常出去的，那个位置在 `CombatTurnProcessor` 之外。
//!
//! 本模块的第一版把这件事实现在 `Capacity(Full(Container::Statuses))` 上，**那是骗人的**：
//! `Full` 的字面意思是"容器满了"，读到它的人会去找溢出的容器，而真相可能是"镜像里少一个串"。
//! 2026-10-17 的裁决给 `TurnError` 补了 [`TurnError::Host`]（载荷 [`HostFailure`]），现在的分工是：
//!
//! | 层 | 类型 | 粒度 | 谁写 |
//! |---|---|---|---|
//! | 冻结的回合机接口 | `TurnError` / `HostFailure` | **类别**（Unsupported / Content / Effect） | [`bridge`] |
//! | 宿主自己 | [`HostError`] | 细节（哪个串、哪条 `IrError`、需要几格） | [`Host::record`] |
//!
//! ⇒ **两个粒度都拿得到**：只读 `TurnError` 的调用方至少能分辨"我们去补"还是"内容要改"，
//! 而 `last_failure()` 给出到底哪一句不对。细节**不是唯一通道**，类别**也不是唯一通道**。
//!
//! 三个 `&self` 的策略钩子（`hand_is_retained` / `block_is_retained` /
//! `turn_start_draw_count`）连 `Result` 都没有 —— 它们的失败记在 `core::cell::Cell` 里
//! （诊断用，不参与哈希、不影响确定性），由**下一个** `try_*` 入口弹出成真正的错误。
//! 那座桥的边界写在 [`Host::flush_deferred`] 上。
//!
//! # 九个钩子今天各自有多少活（我在镜像上量过）
//!
//! | 钩子 | 今天有活吗 | 实测依据 |
//! |---|---|---|
//! | `activate_pending_statuses` | 否 | 23/23 状态 `IncomingStatusDelay = null` ⇒ `pending_turns` 恒 0 |
//! | `run_turn_started_triggers` | **是** | `TurnStarted` 触发器 **3** 条：`fatigue` / `bookworm` / `queue_advances` |
//! | `resolve_card_queue` | 否（内容侧） | 62/62 卡 `QueueOnPlay` 为空 **且** 全镜像 0 条 `node.queueCard`；解析器本身是真的 |
//! | `resolve_pending_queues` | 否 | 本宿主每个钩子都**就地**把效果写进状态（`exec::execute` 是同步递归的） |
//! | `damage_over_time` | **是** | 2 个状态带 `damage_over_time`：`paperwork` / `poison` |
//! | `hand_turn_end_lifecycle` | 否（内容侧） | **机制是真的**（跑 `CARD.LifecyclePrograms[TurnEndInHand]`，`CardLifecyclePrograms.cs:21-46`），但 62/62 卡 `LifecyclePrograms = {}`（实测是 0 字段的 `_obj`，term 11）⇒ 一条节目都不跑 |
//! | `run_turn_ended_triggers` | **是** | `TurnEnded` 触发器 **6** 条；**poison 的层数衰减就在这条路上** |
//! | `decrease_timed_statuses` | 否 | 23/23 状态 `UsesDuration = false`（`F_BOOL` 原始值 1） |
//! | `hand_is_retained` | 否 | 23/23 状态不带 `retain_hand` 标签（`status_bind::has_tag` 逐条读过） |
//!
//! "否"的那些**不是空实现**：每一个都真的做了它能做的判断（解码标签/标记/动作），
//! 只是今天的数据让那个判断恒假。做不成真事的分支是**响亮拒绝**（[`HostError::Unsupported`]），
//! 不是 `Ok(())`。
//!
//! # 沿用 `exec.rs` 的两条简化（照抄那里的说法，别让它们变成隐藏假设）
//!
//! 1. **没有三队列**（效果/事件/续延）。本宿主在钩子里**就地**生效，所以
//!    [`Host::resolve_pending_queues`] 恒为 no-op —— 这正是规格书 §2.3 给出的
//!    "空实现就够"的**准确条件**（"每个钩子在返回前就把自己的效果直接写进状态"）。
//!    ⚠️ 它也因此**不**解析 `CardZone::QueuePile`：那是 [`Host::resolve_card_queue`]。
//! 2. **没有"触发器链"的深度/重入账本**。参考的 `SuppressRecursiveReentry`（同一条链里
//!    同一个触发器不重复进入）与深度上限 64（`CombatEffectChain.cs:10`）都依赖"当前链"，
//!    而本内核没有链、也没有"程序跑到一半再入队一个事件"的路径 ⇒ 触发器**不可能**递归。
//!    这条等价性是结构性的，不是"看起来不会发生"。
//!
//! # `chain_num` / `exec_num`
//!
//! 每跑一次节目本宿主都调一次 [`CombatState::allocate_program_execution_id`]
//! （参考在 `EffectProgramExecutor.Execute` 里就做，`Programs/EffectProgramExecution.cs:27`）。
//!
//! **`chain_num` 也会前进**（2026-10-19 的整局对拍修正了本节旧说法"不会前进"）。
//! 参考只在"顶层入队"时建根链：`CombatState.cs:386`/`:446` 的
//! `CurrentEffectChain ?? CreateRootEffectChain()`，而 `ResolvePendingEffects` /
//! `ResolvePendingEvents` 都在 `using (combat.EnterEffectChain(entry.EffectChain))` 里跑
//! （`CombatEffectQueueProcessor.cs:32`、`CombatEventHandling.cs:60`），所以**一次排空
//! 内部的入队全部复用外层链、不发号**。
//!
//! 内核没有队列 ⇒ 等价物是"回合机把这条事件交给处理器"的那一刻。逐条对齐：
//!
//! | 参考的顶层入队 | 它的处理器 | 内核的落点 | 实测 Δchain |
//! |---|---|---|---|
//! | `EnqueueEvent(TurnStartedCombatEvent)`（`CombatTurnProcessor.cs:28-32`） | 7 个 turn-start 处理器（含 [`Host::try_damage_over_time`]） | [`TurnHost::run_turn_started_triggers`] | +1 |
//! | `EnqueueEvent(TurnEndedCombatEvent)`（`:61-65`） | 弃手牌 / turn-end 触发器 / 时长 | [`TurnHost::run_turn_ended_triggers`] | +1 |
//! | `EnqueueEvent(RoundEndedCombatEvent)`（`:192-195`） | round-end 触发器 | [`TurnHost::on_round_ended`] | +1 |
//! | `EnqueueEvent(RoundStartedCombatEvent)`（`:199-200`） | round-start 触发器 | [`TurnHost::on_round_started`] | +1 |
//!
//! 依据是**数据**不是猜想：四个场景 14 个步边界，每步的 `(chain_num, exec_num)` 都由
//! "把 C# 规范文本里的这两个数改成候选值再算 SHA-256"反推出**唯一解**，
//! 而"每个 turn 事件 +1、回合绕回再 +2（RoundEnded + RoundStarted）"这套计数把
//! 14 个点**全部**对上（`finish` 的 `AdvanceToNextRound` 一步 +6：结束英雄回合 +1、
//! 开敌方回合 +1、结束敌方回合 +1、RoundEnded +1、RoundStarted +1、开英雄新回合 +1）。
//!
//! **证据强度**：上表右列那个"+1"是**每步总数**（实测且唯一）减去别的账之后剩下的量，
//! 而"一条事件恰好一个号"的依据是 `CombatState.cs:386`/`:446` 的 `??` 写法
//! （**我真的读过那两行**）。逐条的归属没有被单独观测过 —— 例如"TurnStarted 那 +1 到底
//! 挂在哪个处理器上"在内核里是**由本模块选的**：它挂在 `run_turn_started_triggers` 上而不是
//! `damage_over_time` 上，因为参考的 DoT 是同一个事件里的第 7 个处理器。
//! 反过来，`dot_kill` 的 step1 只 +2（TurnEnded + TurnStarted）这件事**直接把它钉住了**：
//! 如果 DoT 也发号，那一步会是 +3。
//!
//! ⚠️ 一个**没有**对应的：`resolve_pending_queues`（内核里恒 no-op）、
//! `resolve_card_queue`（本内容 62/62 卡 `QueueOnPlay` 为空）、`activate_pending_statuses`
//! （23/23 状态 `IncomingStatusDelay = null`）都**不是**独立事件，是同一批处理器里的步骤，
//! 所以它们**不许**发号 —— 发了就会把上面那张表全部推歪。

use core::cell::Cell;

use crate::content::{Content, ABSENT16, EK_CARD, NULL16};
use crate::exec::{self, ExecContext};
use crate::expr::ExprError;
use crate::ir::{IrError, NodeRef, Value};
use crate::state::{
    CapacityError, CardSlot, CardZone, CombatEvent, CombatResult, CombatState,
    CombatantId, Continuation, EventItem, StatusDefinitionId, StatusInstance,
    ZonePlacement, ID_CAP, MAX_CARDS_PER_ZONE, MAX_EFFECTS_PER_CYCLE, MAX_EVENTS_PER_CYCLE,
    MAX_QUEUE_CYCLES, MAX_STATUSES_PER_COMBATANT,
};
use crate::status_bind::{self, BindError, DamageKind};
use crate::turn::{HostFailure, TurnError, TurnHost};

// =============================================================================================
// 常量（每一条都在注释里带出处或实测数字）
// =============================================================================================

/// `DamageOverTimeTag = "damage_over_time"`（`StandardCombatIds.cs:45`）。
///
/// 镜像里带它的两个状态：`paperwork` / `poison`（实测，`tools/contentc/reader.py`）。
pub const TAG_DAMAGE_OVER_TIME: &str = "damage_over_time";

/// `RetainHandTag = "retain_hand"`（`StandardCombatIds.cs:55`）。
///
/// 镜像 23/23 状态都不带它 ⇒ [`Host::hand_is_retained`] 恒 `false`（与参考的默认路径一致）。
pub const TAG_RETAIN_HAND: &str = "retain_hand";

/// `RetainBlockTag = "retain_block"`（`StandardCombatIds.cs:56`）。
///
/// 镜像 23/23 状态都不带它 ⇒ [`Host::block_is_retained`] 恒 `false`。
pub const TAG_RETAIN_BLOCK: &str = "retain_block";

/// 节目信封上 `MaxProgramSteps` 缺席时的兜底：参考构造函数要求 `> 0`，默认 1024
/// （`EffectProgramContracts.cs:560-563`）。镜像里 25 条触发器信封实测都是 1024。
const DEFAULT_MAX_PROGRAM_STEPS: u32 = 1024;

/// 一个状态最多解出几条触发器（暂存区）。
///
/// 镜像实测**单个状态最多 5 条**（`paper_seals_wax`），全镜像 25 条。给 8 是余量；
/// 超了就 [`HostError::TooManyTriggers`]（**不截断**：少读一条 = 内容静默不发作）。
pub const MAX_TRIGGERS_PER_STATUS: usize = 8;

/// 一次收集里最多几条触发器同时命中同一个事件（暂存区）。
///
/// 上界的来源：参考的注册表里**没有**条数限制，能命中多少取决于"在场状态数 × 每个状态的
/// 同事件触发器数"。本内核一个战斗员最多 [`MAX_STATUSES_PER_COMBATANT`] = 24 条状态实例，
/// 所以"每个在身定义各 1 条同事件触发器"这个最常见的形状正好装满 24；给 32 是那之外的余量。
/// 超了照样**响亮失败**，不静默跑前 32 条。
pub const MAX_TRIGGER_ENTRIES: usize = 32;

/// `{statusSlug}_trigger{index}` 的最长字节数（`SB:StatusDataRebuild.cs:19`）。
///
/// `statusSlug` ≤ [`ID_CAP`]（内核 id 类型的上限，40）；`"_trigger"` 是 8 字节；
/// `index` 是 `u16` ⇒ 最多 5 位十进制。40 + 8 + 5 = 53，给 56。
const TRIGGER_ID_CAP: usize = ID_CAP + 8 + 8;

// =============================================================================================
// 错误
// =============================================================================================

/// 宿主做不下去的原因。**"内核还没做到"与"内容配错了"必须是两个变体**
/// （理由同 `play.rs:248-258` 的 `PlayError::UnsupportedContent`）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HostError {
    /// 节目执行失败（`exec::ExecError` 里有 Ir / Expr / Sel / Bind / StepLimit 等细分）。
    ///
    /// ⚠️ 这里有两类东西被**故意**放在一起：节目本身不合法（内容问题）与
    /// `ExecError::UnsupportedNode` 那类"内核还没做到"。分不开是因为 `ExecError` 是
    /// `exec.rs` 冻结的枚举 —— 但 `exec.rs` 的预检**在动手之前**拒绝，所以"部分执行"不会发生，
    /// 而具体是哪一条在 `ExecError` 里是可读的。
    Exec(exec::ExecError),
    /// 内容镜像里的状态元数据读不出来（`status_bind::BindError`）。
    Bind(BindError),
    /// 定容容器满了 / 战斗员不存在（`state::CapacityError`）。
    Capacity(CapacityError),
    /// **内核还没做到**：内容真的用到了 v1 没实现的那条路。载荷点名是哪一样。
    ///
    /// 今天真正的取值只有一个：`"CardLifecycleTrigger"`（`CARD.LifecyclePrograms` 里出现了
    /// `TurnEndInHand` 之外的键 —— 参考的 `CardLifecycleTrigger` 枚举今天只有那一个成员，
    /// `CardLifecyclePrograms.cs:8-11`，见 [`card_lifecycle_turn_end_program`]）。
    /// 它今天不可达（62/62 卡的 `LifecyclePrograms` 是 `{}`），但内容一用就必须响亮。
    ///
    /// ⚠️ **2026-10-19 之前**这里唯一的取值是 `"CardLifecyclePrograms"`：那时候"卡在手里
    /// 过回合的节目"整条路都是拒绝的。现在它是**真实现**
    /// （[`Host::try_hand_turn_end_lifecycle`]）—— 拒绝换成了"解不出来才拒绝"，
    /// 因为一个静默 `Ok(())` 会让"烧牌/悔恨"这类卡永远不发作且没有任何信号。
    ///
    /// ⚠️ 另有两条"内核还没做到"走的是 [`Self::Exec`]，因为**拒绝发生在 `exec.rs` 里**，
    /// 而它已经有自己的词表了：`"cardsPlayedLastTurn"`（表达式求值器缺这个 int 表达式，
    /// `queue_advances` 的 TurnStarted 触发器会撞上）报
    /// `ExecError::Expr(ExprError::UnsupportedKind)`；缺节点种类报 `ExecError::UnsupportedNode`。
    /// 两者都是"内核缺能力"的**可读**表达，只是不在这个变体上 ——
    /// 合并进 `Unsupported` 反而会让 `exec.rs` 的细分丢掉。
    Unsupported(&'static str),
    /// **内容配错了**：镜像里的结构读得出来但表示的不是一个合法的语义
    /// （`TriggerEvent` 串不认识、触发器少了 `Program`/`Root`、卡的落区是第 8 个区名…）。
    Content(&'static str),
    /// 暂存区装不下（**不截断**）。`needed`/`have` 都带上，别只给一句"太多了"。
    TooManyTriggers {
        /// 实际命中几条。
        needed: usize,
        /// 调用方给了几格。
        have: usize,
    },
    /// 排空循环没能在上限内收敛（参考在这里**抛**，`CombatEventHandling.cs:99-102`）。
    ///
    /// 这是参考自己的上限（`MaxQueueCycles` = 1024），不是移植引入的：**卡在循环里**
    /// 与**队列满**是两种不同的响亮失败，所以分成两个变体（后者是
    /// [`capacity`](Self::Capacity) + [`CapacityError::Full`]）。
    /// 参考的抛出消息还带 `WhatIsLooping(combat)`（`:121-141`，把三个队列的现场打出来）；
    /// 内核的载荷只留**类别与轮数**，现场读 [`Host::last_failure`] 与三个
    /// `pending_*_count()` —— 不是因为现场没用，而是因为 `HostError` 是 `Copy` 的窄枚举。
    QueueCycleLimit {
        /// 已经跑了几轮。
        cycles: u32,
        /// 上限（`MAX_QUEUE_CYCLES` 或调用方给的值）。
        limit: u32,
    },
    /// 单相位的解析条数超限（同一上限族的另外两个：`MaxEffectsPerCycle` / `MaxEventsPerCycle`）。
    QueuePhaseLimit {
        /// `"effect"` 或 `"event"`。
        phase: &'static str,
        /// 这一相位已经解析了几条。
        resolved: u32,
        /// 上限。
        limit: u32,
    },
}

impl From<exec::ExecError> for HostError {
    fn from(e: exec::ExecError) -> Self {
        HostError::Exec(e)
    }
}
impl From<BindError> for HostError {
    fn from(e: BindError) -> Self {
        HostError::Bind(e)
    }
}
impl From<CapacityError> for HostError {
    fn from(e: CapacityError) -> Self {
        HostError::Capacity(e)
    }
}
impl From<IrError> for HostError {
    fn from(e: IrError) -> Self {
        // `IrError` 是"镜像里的结构读不出来" —— 与 `play.rs` 的处置同形
        // （`play.rs:274-278`：也归到节目执行失败那一桶，而不是另开一个变体）。
        HostError::Exec(exec::ExecError::Ir(e))
    }
}

/// [`HostError`] → [`TurnError`] 的**真映射**（一次 2026-10-17 的裁决把它从"借用"改成了映射）。
///
/// 分档的依据只有一条：**排查方向**。
///
/// | `HostError` | `TurnError` | 排查方向 |
/// |---|---|---|
/// | `Capacity(e)` | `Capacity(e)` | 容器满 / 缺战斗员 —— **唯一无损的一档**（语义本来一致） |
/// | `Unsupported(_)` | `Host(Unsupported)` | 我们去补 |
/// | `TooManyTriggers{..}` | `Host(Unsupported)` | **我们的**暂存区太小，内容是对的 |
/// | `Content(_)` | `Host(Content)` | 内容去改 |
/// | `Bind(_)` | `Host(Content)` | 镜像里的状态元数据读不出来 ⇒ 内容 |
/// | `Exec(UnsupportedNode)` | `Host(Unsupported)` | 内核缺节点 |
/// | `Exec(Expr(UnsupportedKind))` | `Host(Unsupported)` | 内核缺表达式 |
/// | `Exec(其它)` | `Host(Effect)` | 节目 fault |
///
/// 为什么 `Exec` 里那两只要单独挑出来：`ExecError` 自己的词表已经把"内核缺能力"
/// （`UnsupportedNode` / `UnsupportedKind`）与"内容/程序坏了"分开了，直接折进
/// `Host(Effect)` 会把这层信息压平 —— 而它正是排查时最要紧的那一格。
///
/// 细节载荷（哪个串不认识、`IrError` 是什么）**不在这条路上**：它们在
/// [`Host::last_failure`] 里。这个函数只保证**类别**不丢、不错。
fn bridge(e: HostError) -> TurnError {
    match e {
        HostError::Capacity(error) => TurnError::Capacity(error),
        HostError::Unsupported(_) => TurnError::Host(HostFailure::Unsupported),
        HostError::TooManyTriggers { .. } => TurnError::Host(HostFailure::Unsupported),
        HostError::Content(_) => TurnError::Host(HostFailure::Content),
        HostError::Bind(_) => TurnError::Host(HostFailure::Content),
        // 一个转不出来的排空循环是**内容**写的循环（参考把它当异常抛，排查方向是"谁在互相喂"），
        // 不是"内核缺能力" —— 所以归 `Content` 那一档，载荷留在 `last_failure` 里。
        HostError::QueueCycleLimit { .. } => TurnError::Host(HostFailure::Content),
        HostError::QueuePhaseLimit { .. } => TurnError::Host(HostFailure::Content),
        HostError::Exec(exec::ExecError::UnsupportedNode) => {
            TurnError::Host(HostFailure::Unsupported)
        }
        HostError::Exec(exec::ExecError::Expr(ExprError::UnsupportedKind)) => {
            TurnError::Host(HostFailure::Unsupported)
        }
        HostError::Exec(_) => TurnError::Host(HostFailure::Effect),
    }
}

// =============================================================================================
// 触发器：事件名 / 解码结果 / 暂存区
// =============================================================================================

/// 参考的 `TriggerEvent`（**Sandbox 层**的枚举，`SB:EffectVocabulary.cs:29-71`，25 个成员）。
///
/// 本模块处理其中 5 个有钩子接的（回合开始/结束、轮次开始/结束、**以及 `DamageDealt`**），
/// 其余 20 个名字**必须认得**：认不出来就会把"内容写了一条 `DamageTaken` 触发器"
/// 误报成"内容配错了"，而真相是"这个事件今天没有钩子接"。
///
/// ⇒ 认识的 20 个归 [`Self::NotHandled`]，**不认识的串**才是 [`HostError::Content`]。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TriggerEvent {
    /// `TurnStarted` —— 拥有者回合开始（`SB:StatusDataRebuild.cs:39-42`）。
    TurnStarted,
    /// `TurnEnded` —— 拥有者回合结束（`:43-46`）。
    TurnEnded,
    /// `RoundStarted` —— 每轮开始（`:121-122`，**没有 gate、没有过滤器**）。
    RoundStarted,
    /// `RoundEnded` —— 每轮结束（`:123-124`，同上）。镜像里 4 条（`sustained` 等）。
    RoundEnded,
    /// `DamageDealt` —— 有人造成伤害（`DamageEffects.cs:186-194` 入队）。
    ///
    /// **Bearer 是"出手方"**，不是承受者：`StatusDataRebuild.cs:53-55` 给这个事件挂的
    /// Bearer 过滤器是 `DamageDealtSourceHasStatusTriggerFilter`（`Scope` 默认值是 `Bearer`，
    /// 而镜像 25 条触发器**一个 `Scope` 都没出现**）。`doubt` 的触发器就长在这上面：
    /// 敌人戴着 doubt 打人 ⇒ 触发 ⇒ `modifyStatusStacks(doubt, -1)` 落到 `sel.source`。
    DamageDealt,
    /// 参考有、但今天的 `TurnHost` 没有对应钩子的 20 个成员之一。
    NotHandled,
}

impl TriggerEvent {
    /// 镜像里的字面串 → 变体。**25 个名字一个不落地列在这里**，别的串返回 `None`。
    #[must_use]
    pub fn from_wire_name(name: &str) -> Option<Self> {
        match name {
            "TurnStarted" => Some(TriggerEvent::TurnStarted),
            "TurnEnded" => Some(TriggerEvent::TurnEnded),
            "RoundStarted" => Some(TriggerEvent::RoundStarted),
            "RoundEnded" => Some(TriggerEvent::RoundEnded),
            "DamageDealt" => Some(TriggerEvent::DamageDealt),
            // ── 参考有、本内核今天没有钩子接的 20 个（按 `EffectVocabulary.cs` 的声明序）──
            "DamageTaken" | "Healed" | "CardPlayed" | "Downed" | "StatusExpired"
            | "ResourceGained" | "CardCostPaid" | "StatusApplied" | "StatusRemoved"
            | "StatusMerged" | "StatusStacksChanged" | "BlockGained" | "CardsDrawn"
            | "CardMovedToZone" | "CardInstanceCreated" | "StatusApplicationPrevented"
            | "StatusApplicationAmplified" | "ActionResolved" | "RuleAnnounced"
            | "ActionStarting" => Some(TriggerEvent::NotHandled),
            _ => None,
        }
    }

    /// 变体 → 参考里的字面串（[`Self::NotHandled`] 没有唯一的名字，给空串）。
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            TriggerEvent::TurnStarted => "TurnStarted",
            TriggerEvent::TurnEnded => "TurnEnded",
            TriggerEvent::RoundStarted => "RoundStarted",
            TriggerEvent::RoundEnded => "RoundEnded",
            TriggerEvent::DamageDealt => "DamageDealt",
            TriggerEvent::NotHandled => "",
        }
    }
}

/// 一条触发器的解码结果（`STAT.Triggers[i]`）。
///
/// **实测形状**（二进制层面量的，不是从 JSON dump 反推的）：
///
/// ```text
/// STAT.Triggers  F_TERM → term 289: op=4 (_arr), 槽=(416, 1)
///   aux(416) = 288: op=112 (_obj, opclass=1) 字段 = [(Event, F_STR), (Program, F_TERM)]
///     Event   = 串 "TurnEnded"
///     Program = term 287: op=116 (_obj) 字段 = [Id(F_STR,wrap), MaxNodeDepth(F_INT),
///                                              MaxProgramSteps(F_INT), Root(F_TERM)]
///       Root  = 效果程序的根节点
/// ```
///
/// 只有 `Event` + `Program` 两个键 —— 全镜像 25 条都是（`Scope` 一次都没出现 ⇒ 全是默认
/// `Bearer`，`SB:StatusDataRebuild.cs:25`）。
#[derive(Debug, Clone, Copy)]
pub struct TriggerEntry<'a> {
    /// 解出来的事件。
    pub event: TriggerEvent,
    /// 节目根节点。
    pub root: NodeRef<'a>,
    /// 信封上的 `MaxProgramSteps`（缺席 ⇒ 1024）。
    pub max_steps: u32,
    /// `STAT.Triggers` 里的下标（参考的 id 是 `{slug}_trigger{index}`，`:19`）。
    pub index: u16,
}

/// 收集一个事件要跑的全部触发器 —— 平坦暂存区。
///
/// 为什么不是 `[Option<TriggerEntry>; N]`：`TriggerEntry` 里有 [`NodeRef`]，
/// 而 `NodeRef::new` 不是 `const fn` ⇒ 装不出"空槽"。所以这里存
/// `(渲染好的 id, term 句柄, 步数)`，全部是 `const` 可初始化的东西。
///
/// **id 在这里就渲染成字节**，因为排序键是 `{slug}_trigger{index}` 的**字符串序**
/// （`TriggeredProgramDefinition.cs:91-92` 的 `OrderBy(Priority).ThenBy(Id.value)`），
/// 而状态触发器的 `Priority` 恒 0（`SB:StatusDataRebuild.cs:19` 不传 priority）
/// ⇒ 次序**完全**由 id 字符串决定。分两段（slug 再 index）比较是错的：
/// `"a_trigger0"` 与 `"a0_trigger0"` 的先后由第 2 个字节 `'_'`(0x5F) vs `'0'`(0x30) 决定，
/// 而 slug 比较会给出相反的答案。渲染成整串再按字节比，才与参考同序。
struct TriggerBatch {
    /// `MAX_TRIGGER_ENTRIES × TRIGGER_ID_CAP` 的字符池。
    ids: [u8; MAX_TRIGGER_ENTRIES * TRIGGER_ID_CAP],
    /// 第 `i` 条 id 的长度。
    id_len: [u16; MAX_TRIGGER_ENTRIES],
    /// 第 `i` 条的 term 句柄。
    root: [u16; MAX_TRIGGER_ENTRIES],
    /// 第 `i` 条的步数预算。
    max_steps: [u32; MAX_TRIGGER_ENTRIES],
    /// 第 `i` 条在它自己那个 `STAT.Triggers` 里的下标。
    index: [u16; MAX_TRIGGER_ENTRIES],
    /// 装了几条。
    len: usize,
}

impl TriggerBatch {
    const fn new() -> Self {
        Self {
            ids: [0u8; MAX_TRIGGER_ENTRIES * TRIGGER_ID_CAP],
            id_len: [0u16; MAX_TRIGGER_ENTRIES],
            root: [0u16; MAX_TRIGGER_ENTRIES],
            max_steps: [0u32; MAX_TRIGGER_ENTRIES],
            index: [0u16; MAX_TRIGGER_ENTRIES],
            len: 0,
        }
    }

    /// 第 `i` 条的 id 字节。
    fn id(&self, i: usize) -> &[u8] {
        let start = i.saturating_mul(TRIGGER_ID_CAP);
        let len = usize::from(self.id_len.get(i).copied().unwrap_or(0));
        let end = start.saturating_add(len).min(self.ids.len());
        self.ids.get(start..end).unwrap_or(&[])
    }

    /// 追加一条：把 `{slug}_trigger{index}` 渲染进字符池。
    fn push(
        &mut self,
        slug: &str,
        index: u16,
        root: u16,
        max_steps: u32,
    ) -> Result<(), HostError> {
        if self.len >= MAX_TRIGGER_ENTRIES {
            return Err(HostError::TooManyTriggers {
                needed: self.len.saturating_add(1),
                have: MAX_TRIGGER_ENTRIES,
            });
        }
        if slug.len() + 8 + 5 > TRIGGER_ID_CAP {
            // id 比内核自己的 id 上限还长：那不是"内容太大"，是内容里有个野 id。
            return Err(HostError::Content("trigger id too long"));
        }
        let slot = self.len;
        let start = slot.saturating_mul(TRIGGER_ID_CAP);
        let mut cursor = start;
        for byte in slug.as_bytes() {
            let Some(cell) = self.ids.get_mut(cursor) else {
                return Err(HostError::Content("trigger id too long"));
            };
            *cell = *byte;
            cursor += 1;
        }
        for byte in b"_trigger" {
            let Some(cell) = self.ids.get_mut(cursor) else {
                return Err(HostError::Content("trigger id too long"));
            };
            *cell = *byte;
            cursor += 1;
        }
        // `index` 的十进制（参考是 `$"{slug}_trigger{index}"`，默认 `int.ToString()`）。
        let mut digits = [0u8; 5];
        let mut count = 0usize;
        let mut value = u32::from(index);
        loop {
            digits[count] = b'0' + (value % 10) as u8;
            count += 1;
            value /= 10;
            if value == 0 {
                break;
            }
        }
        for i in 0..count {
            let byte = digits.get(count - 1 - i).copied().unwrap_or(b'0');
            let Some(cell) = self.ids.get_mut(cursor) else {
                return Err(HostError::Content("trigger id too long"));
            };
            *cell = byte;
            cursor += 1;
        }
        let Some(len_slot) = self.id_len.get_mut(slot) else {
            return Err(HostError::Content("trigger id too long"));
        };
        *len_slot = u16::try_from(cursor.saturating_sub(start))
            .map_err(|_| HostError::Content("trigger id too long"))?;
        let Some(root_slot) = self.root.get_mut(slot) else {
            return Err(HostError::Content("trigger id too long"));
        };
        *root_slot = root;
        let Some(steps_slot) = self.max_steps.get_mut(slot) else {
            return Err(HostError::Content("trigger id too long"));
        };
        *steps_slot = max_steps;
        let Some(index_slot) = self.index.get_mut(slot) else {
            return Err(HostError::Content("trigger id too long"));
        };
        *index_slot = index;
        self.len += 1;
        Ok(())
    }

    /// 按 id 字节序原地插入排序（n ≤ 32，且这个列表每回合只排一次）。
    ///
    /// ⚠️ **【未验证】**：参考的次级键是 `ThenBy(d => d.Id.value)`，用的是
    /// `Comparer<string>.Default`（culture-sensitive）而不是 `Ordinal`
    /// （规格书 §6.2 第 2 条点名了这条疑点，我也没验证）。这里按**字节序**实现：
    /// 对当前镜像的 25 条触发器（`{slug}_trigger{n}`，全小写 ASCII）两种比较给同一序列，
    /// 但这条等价性**没有证据**，所以写在这里。
    fn sort(&mut self) {
        let mut i = 1usize;
        while i < self.len {
            let mut j = i;
            while j > 0 {
                let left = self.id(j - 1);
                let right = self.id(j);
                if left <= right {
                    break;
                }
                self.swap(j - 1, j);
                j -= 1;
            }
            i += 1;
        }
    }

    fn swap(&mut self, a: usize, b: usize) {
        let (Some(a_len), Some(b_len)) = (self.id_len.get(a).copied(), self.id_len.get(b).copied())
        else {
            return;
        };
        let (Some(a_root), Some(b_root)) = (self.root.get(a).copied(), self.root.get(b).copied())
        else {
            return;
        };
        let (Some(a_steps), Some(b_steps)) = (
            self.max_steps.get(a).copied(),
            self.max_steps.get(b).copied(),
        ) else {
            return;
        };
        let (Some(a_index), Some(b_index)) = (self.index.get(a).copied(), self.index.get(b).copied())
        else {
            return;
        };
        // 字符池里两段定长区交换（逐字节，长度可能不同 ⇒ 先各自读出来）。
        let mut left = [0u8; TRIGGER_ID_CAP];
        let mut right = [0u8; TRIGGER_ID_CAP];
        let a_start = a.saturating_mul(TRIGGER_ID_CAP);
        let b_start = b.saturating_mul(TRIGGER_ID_CAP);
        let a_len = usize::from(a_len).min(TRIGGER_ID_CAP);
        let b_len = usize::from(b_len).min(TRIGGER_ID_CAP);
        copy_out(&self.ids, a_start, &mut left[..a_len]);
        copy_out(&self.ids, b_start, &mut right[..b_len]);
        copy_in(&mut self.ids, a_start, &right[..b_len]);
        copy_in(&mut self.ids, b_start, &left[..a_len]);
        if let Some(slot) = self.id_len.get_mut(a) {
            *slot = b_len as u16;
        }
        if let Some(slot) = self.id_len.get_mut(b) {
            *slot = a_len as u16;
        }
        if let Some(slot) = self.root.get_mut(a) {
            *slot = b_root;
        }
        if let Some(slot) = self.root.get_mut(b) {
            *slot = a_root;
        }
        if let Some(slot) = self.max_steps.get_mut(a) {
            *slot = b_steps;
        }
        if let Some(slot) = self.max_steps.get_mut(b) {
            *slot = a_steps;
        }
        if let Some(slot) = self.index.get_mut(a) {
            *slot = b_index;
        }
        if let Some(slot) = self.index.get_mut(b) {
            *slot = a_index;
        }
    }
}

/// 把 `src[at..at+out.len()]` 拷进 `out`。越界就什么都不做
/// （调用点只在自己的定长字符池上用，所以这一支不可达 —— 但它不是 `unwrap`）。
fn copy_out(src: &[u8], at: usize, out: &mut [u8]) {
    if let Some(slice) = src.get(at..at.saturating_add(out.len())) {
        out.copy_from_slice(slice);
    }
}

/// [`copy_out`] 的反向。
fn copy_in(dst: &mut [u8], at: usize, src: &[u8]) {
    if let Some(slice) = dst.get_mut(at..at.saturating_add(src.len())) {
        slice.copy_from_slice(src);
    }
}

// =============================================================================================
// 宿主
// =============================================================================================

/// 把 `turn.rs` 的 9 个钩子接到 `exec.rs` 上的宿主。
///
/// 持有一份内容镜像（`&Content`，`Copy`），**没有别的状态**：9 个钩子都是
/// "读状态 → 跑节目 → 写状态"，两次调用之间不留下任何跨钩子的东西
/// （这正是 [`Host::resolve_pending_queues`] 能诚实地做 no-op 的原因）。
///
/// 唯一一个字段 [`Self::failure`] 是**诊断**（`Cell`，不参与哈希、不影响确定性）：
/// 三个 `&self` 的策略钩子没有 `Result` 通道，它们的失败记在这里，由下一个 `try_*` 弹出。
#[derive(Debug)]
pub struct Host<'a> {
    content: &'a Content<'a>,
    failure: Cell<Option<HostError>>,
}

impl<'a> Host<'a> {
    /// 接上一份内容镜像。
    #[must_use]
    pub const fn new(content: &'a Content<'a>) -> Self {
        Self {
            content,
            failure: Cell::new(None),
        }
    }

    /// 这一层脚下的镜像。
    #[must_use]
    pub const fn content(&self) -> &'a Content<'a> {
        self.content
    }

    /// 最近一次失败（**细节**：哪个串、哪条 `IrError`、需要几格）。
    ///
    /// 与 [`bridge`] 的分工：`TurnError::Host(..)` 只带**类别**（三种），细节在这里。
    /// 两条通道都有，所以"只读 `TurnError` 的调用方"也能分辨是他去补还是内容要改。
    ///
    /// ⚠️ 它记的是**最后一次**：同一回合里前一次的失败已经被后面的成功调用覆盖过一次
    /// （例如一个 `&self` 钩子记下的失败被下一个 `try_*` 吐出之后，槽是空的）。
    /// 要"一次都不许漏"的用法是先 `take_failure()` 再继续。
    #[must_use]
    pub fn last_failure(&self) -> Option<HostError> {
        self.failure.get()
    }

    /// 取走并清空最近一次失败。
    pub fn take_failure(&mut self) -> Option<HostError> {
        self.failure.take()
    }

    /// 记账：把失败记进诊断槽（不丢原因）。
    fn record(&self, e: HostError) -> HostError {
        self.failure.set(Some(e));
        e
    }

    /// 三个 `&self` 策略钩子上记下的失败 —— 在**下一个** `try_*` 入口弹出。
    ///
    /// # 这座桥的两条边界（写清楚，因为它不是一条正常的错误通道）
    ///
    /// 1. **只在"下一个 `try_*` 之前"有效**。它是 `Cell` 里的一个槽，下一次
    ///    [`Self::record`] 会覆盖它、下一次本函数会取走它。`start_current_turn` /
    ///    `end_current_turn` 的每一步都以一个 `try_*` 开头，所以那条路上"一定有人接"；
    ///    但一个**只**调 `block_is_retained` / `turn_start_draw_count` 而不走回合机的调用方，
    ///    得自己看 [`Self::last_failure`]。这就是为什么它是 `pub` 的。
    /// 2. **为什么不能更早发现**：那三个钩子的签名是 `&self -> bool` / `&self -> i32`
    ///    （`turn.rs:184, 212, 221`），没有 `Result`。把它们改成 `Result` 要动 trait 与
    ///    每个实现，收益只是"语法更干净" —— 所以 2026-10-17 的裁决是**接受现状**。
    ///
    /// 三个钩子在读不出来时各自返回什么，见它们自己的文档（保守值 + 说明为什么是那个值）。
    fn flush_deferred(&mut self) -> Result<(), HostError> {
        match self.failure.take() {
            Some(e) => Err(e),
            None => Ok(()),
        }
    }

    // -----------------------------------------------------------------------------------------
    // 触发器：解码 + 收集 + 跑
    // -----------------------------------------------------------------------------------------

    /// `STAT.Triggers` → 解码后的条目写进 `out`（**全量**，不按事件过滤）。
    ///
    /// 读不出来（结构坏）⇒ [`HostError::Content`] / [`HostError::Bind`]，**不"跳过这一条
    /// 当作没有"** —— 那会让"内容写了规则但内核不跑"变成隐性算错。
    pub fn triggers_of(
        &self,
        status_id: &str,
        out: &mut [TriggerEntry<'a>],
    ) -> Result<usize, HostError> {
        let mut handles = [0u16; MAX_TRIGGERS_PER_STATUS];
        let count = status_bind::trigger_handles(self.content, status_id, &mut handles)?;
        if count > out.len() {
            return Err(HostError::TooManyTriggers {
                needed: count,
                have: out.len(),
            });
        }
        for i in 0..count {
            let Some(handle) = handles.get(i).copied() else {
                return Err(HostError::TooManyTriggers {
                    needed: count,
                    have: out.len(),
                });
            };
            let entry = decode_trigger(self.content, handle, i as u16)?;
            let Some(slot) = out.get_mut(i) else {
                return Err(HostError::TooManyTriggers {
                    needed: count,
                    have: out.len(),
                });
            };
            *slot = entry;
        }
        Ok(count)
    }

    /// 收集"行动者身上、指定事件"的全部触发器，按 `(priority=0, id 字节序)` 排好。
    ///
    /// 三条与参考对齐的细节：
    ///
    /// 1. **只收 active 状态**（`pending_turns == 0`）。参考的 Bearer 过滤器读的是
    ///    `TurnCombatant.Statuses`（`TurnStartedTriggeredEffects.cs:29`），而 `Statuses`
    ///    本来就只列 active（`CombatantState.cs:27-28`）—— 待转正的实例**不触发**。
    /// 2. **按定义去重**：过滤器问的是 `Statuses.Any(s => s.DefinitionId == x)`
    ///    （存在性），所以同一个定义的两条实例只跑一次触发器。
    /// 3. **`gatingStatus` 与 Bearer 过滤器在这里合成一步**：参考先用 `GatingStatus`
    ///    问"场上有人带吗"（`TriggeredProgramDefinition.cs:139-144`），再用过滤器问
    ///    "行动者带吗"（`:156-161`）。从**行动者**的状态出发收集，两条同时成立。
    fn collect_triggers(
        &self,
        state: &CombatState,
        actor: &CombatantId,
        event: TriggerEvent,
        batch: &mut TriggerBatch,
    ) -> Result<(), HostError> {
        let Some(combatant) = state.combatant(actor) else {
            return Ok(()); // 参考：`TryGetCombatant` 失败 ⇒ 上下文工厂返回 null ⇒ 跳过
        };
        // 去重表：参考的过滤器问的是"行动者身上**有没有**这个定义"（存在性），
        // 所以同一个定义的两条实例只跑一次。存**拥有所有权的 id**（`StatusDefinitionId`
        // 是定容的 `Copy` 类型）而不是 `&str` —— 后者会借住 `state`，而跑节目要 `&mut state`。
        let mut seen_ids = [StatusDefinitionId::EMPTY; MAX_STATUSES_PER_COMBATANT];
        let mut seen_len = 0usize;

        for instance in combatant.statuses() {
            if !is_active(instance) {
                continue;
            }
            let definition = instance.definition_id;
            if seen_ids.get(..seen_len).unwrap_or(&[]).contains(&definition) {
                continue;
            }
            let Some(slot) = seen_ids.get_mut(seen_len) else {
                // 不可达：状态实例数 ≤ `MAX_STATUSES_PER_COMBATANT`，与 `seen_ids` 同源。
                return Err(HostError::Content("status table"));
            };
            *slot = definition;
            seen_len += 1;

            let mut entries = [empty_trigger(self.content); MAX_TRIGGERS_PER_STATUS];
            let count = self.triggers_of(definition.as_str(), &mut entries)?;
            for i in 0..count {
                let Some(entry) = entries.get(i).copied() else {
                    return Err(HostError::Content("status table"));
                };
                if entry.event != event {
                    continue;
                }
                batch.push(
                    definition.as_str(),
                    entry.index,
                    entry.root.id(),
                    entry.max_steps,
                )?;
            }
        }
        Ok(())
    }

    /// 跑一个事件的触发器程序（按排好的次序）。
    ///
    /// 参考的顺序（`TriggeredProgramDefinition.cs:110-198`）：逐个 →
    /// **重入抑制** → **深度闸**（超了**抛**）→ GatingStatus → 建上下文 → 过滤器 → 跑节目。
    ///
    /// 本内核的三条差异，每条都是结构性的（不是"忘了"）：
    ///
    /// * **重入抑制与深度闸不适用**：它们管的是"同一条效果链里再触发自己"
    ///   （`CombatEffectChain.cs:49-72`）。本宿主没有事件队列，节目跑完就结束，
    ///   **不可能**在跑节目时再触发一个触发器 ⇒ 这两条闸今天恒不成立。
    /// * **上下文必成功**：TurnStarted/TurnEnded 的工厂只有一句
    ///   `TryGetCombatant(e.CombatantId)`（`TriggeredProgramContextAdapters.cs:46-62`），
    ///   而这里的 `actor` 就是那个 id。
    /// * **过滤器就是第 3 条的去重收集**。
    ///
    /// `sel.source` 在两种上下文里都是**本回合行动者**
    /// （`TurnStartedTriggeredEffects.cs:55-62`、`TurnEndedTriggeredEffects.cs:55-62`），
    /// 且上下文**不设 EventTarget** ⇒ 程序里的 `sel.eventTarget` 解出空集（与参考同）。
    fn run_triggers(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        event: TriggerEvent,
    ) -> Result<(), HostError> {
        let mut batch = TriggerBatch::new();
        self.collect_triggers(state, actor, event, &mut batch)?;
        batch.sort();

        for i in 0..batch.len {
            // 参考的排空循环条件是 `while (hasPending…) && Result == Ongoing`
            // （`CombatEventHandling.cs:97`）⇒ 战斗一结束，后面入队的节目不会再落地。
            if state.result != CombatResult::Ongoing {
                break;
            }
            let Some(handle) = batch.root.get(i).copied() else {
                break;
            };
            let steps = batch.max_steps.get(i).copied().unwrap_or(DEFAULT_MAX_PROGRAM_STEPS);
            let root = NodeRef::new(self.content, handle);
            // 执行号由 `exec::begin` 发（`EffectProgramExecution.cs:27`）。**这里不许再发一次**
            // （`event-queue-interface.md` §5.2 末的"双倍发号"警告）。
            let outcome = execute_program(state, self.content, root, Some(*actor), None, steps);
            outcome.map_err(|e| self.record(HostError::Exec(e)))?;
        }
        Ok(())
    }

    // -----------------------------------------------------------------------------------------
    // 9 个必做钩子的"有原因"版本
    // -----------------------------------------------------------------------------------------

    /// turn-start 处理器 #3：`pending_turns--`，归零的转正（`StatusEffects.cs:409-447`）。
    ///
    /// 逐条照参考：
    ///
    /// 1. 战斗员不存在 ⇒ **静默返回**（`:417-418`）。
    /// 2. 只处理 `pending_turns >= 1` 的实例（参考的 `PendingStatuses` = `!IsActive`
    ///    而 `IsActive` 就是 `PendingTurns == 0`，`StatusInstance.cs:22`）。
    /// 3. **每次 −1**，只有原本为 1 的那次转正（`:426-428`）。
    /// 4. 转正**不重置** stk/dur/chg（整个 handler 只调 `SetPendingTurns`，`:420-445`）。
    ///
    /// 今天恒空转：镜像 23/23 状态的 `IncomingStatusDelay = null` ⇒ `pending_turns` 永远是 0
    /// （规格书 §4.2）。**但它不是空实现** —— 内容一开这个口子，转正就自动正确。
    ///
    /// ⚠️ 两处如实说明：参考在转正时**入队** `StatusActivatedCombatEvent`（`:434-443`），
    /// 本内核没有事件队列 ⇒ 镜像里 0 条 `StatusActivated` 触发器（实测 9 种事件里没有它）
    /// 所以这条事件今天没有观察者；`RecountActiveStatuses`（`:445`）是纯缓存，内核没有概念。
    pub fn try_activate_pending_statuses(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), HostError> {
        self.flush_deferred()?;
        let Some(combatant) = state.combatant_mut(actor) else {
            return Ok(());
        };
        let statuses = combatant.statuses_mut();
        for instance in statuses.iter_mut() {
            if instance.pending_turns <= 0 {
                continue;
            }
            // `SetPendingTurns(-1)`：参考对负数抛，而这里 `> 0` 才减 ⇒ 不会到 −1。
            instance.pending_turns -= 1;
        }
        Ok(())
    }

    /// turn-start 处理器 #4：全部 turn-start 触发器（镜像 3 条）。
    ///
    /// ⚠️ **批次 1 起改走事件队列**（`CombatTurnProcessor.cs:28-32` 的
    /// `EnqueueEvent(TurnStartedCombatEvent)` + `:34-37` 的 `ResolvePendingQueues`）：
    ///
    /// 1. 顶层入队 ⇒ 建一条根链（`CombatState.cs:446` 的 `CurrentEffectChain ?? CreateRoot…`）
    ///    ⇒ **链号 +1**。这一笔以前写在本函数的 `TurnHost` 适配器里（`let _turn_started_chain`），
    ///    现在挪进 [`CombatState::enqueue_event_at_root`] —— **笔数不变，位置更诚实**。
    /// 2. 立刻排空：本事件此刻是队列里唯一一条，所以"谁在什么时候跑触发器"没有变
    ///    （参考的 turn-start 七个处理器里，第 4 个就是同一个 handler 体）。
    /// 3. 排空会把**这个处理器期间**入队的东西也消化掉 —— 数组里 3 条触发器各跑一个节目，
    ///    `exec_num` 仍然一个节目 +1。
    pub fn try_run_turn_started_triggers(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), HostError> {
        self.flush_deferred()?;
        state
            .enqueue_event_at_root(CombatEvent::TurnStarted {
                combatant: *actor,
            })
            .map_err(|e| self.record(HostError::Capacity(e)))?;
        self.try_resolve_pending_queues(state)
    }

    /// turn-start 处理器 #5：卡牌队列（`QueueResolution.cs:18-138`）。
    ///
    /// 参考语义，逐条（**【验证】**，我读过那 138 行）：
    ///
    /// 1. `count <= 0` 或战斗员不存在 ⇒ 返回（`:24-25`）。
    /// 2. **解析窗口在跑第一张之前快照**（`:29-33` 的 `.ToList()`）⇒ 解析期间入队的牌
    ///    等下一个窗口。本内核同步执行，等价于"快照 = 进来那一刻的 `QueuePile` 内容"。
    /// 3. 逐张**串行**：上一张的节目跑完才轮到下一张（`:100-110`）。
    /// 4. 牌必须还在 `QueuePile` 里（`:51-56`，否则跳过 —— 窗口期间被别的东西搬走了）。
    /// 5. **目标锁定**：`QueuedTargetId` 若已离场 ⇒ 目标为空，**不重定向**（`:66-70`）。
    /// 6. 跑节目时 `sel.source` = 拥有者、`sel.eventTarget` = 锁定的目标（`:84`）。
    ///    **不是第二次出牌**：没有费用、没有 `CardPlayed` 事件、不过受理校验器（`:6-8`）。
    /// 7. 节目跑完 ⇒ `Finish`：清锁定、把牌搬到 `PlayedCardDestination`（`:116-128`）。
    ///    没有节目（`card.Program == null`）⇒ 直接 `Finish`（`:76-81`）。
    /// 8. 节目 **Faulted** ⇒ `onTerminal` 在 `:106-107` 提前返回 ⇒ **卡留在队列里、窗口停**。
    ///
    /// ⚠️ 与参考的两处偏差（都写明，不改结构）：
    ///
    /// * 参考的 `Finish` 是**入队**一个 `MoveCardToZoneEffectRequest`（`:127`），本内核就地搬
    ///   （同 `play.rs` 的 D1）。语义等价：没有反应窗口。
    /// * 卡定义查不到时参考**跳过**（`:59-64` 的 `continue`），本内核**响亮拒绝**
    ///   （[`HostError::Content`]）。理由：`CARD` 表就是内核的卡定义表（`play.rs:572-575`），
    ///   查不到说明镜像/调用方已经不一致；静默跳过会让那张牌永远卡在队列里且没有任何信号。
    ///   本镜像 62/62 卡都在表里 ⇒ 今天不可达。
    ///
    /// **今天有活吗**：没有，两个独立实测都指向同一结论 —— 62/62 卡 `QueueOnPlay` 为空，
    /// 而且整个镜像里**没有一个** `node.queueCard` term（实测 0 条；`node.resolveQueuedCards`
    /// 也是 0 条）。所以出牌流程永远造不出队列卡。但这不改变它是**必做**钩子的理由：
    /// 不做的话，任何进入 `QueuePile` 的牌（将来的 `node.queueCard` / `QueueOnPlay`）
    /// 都会永久滞留、`cz=` 行永久不同，而且**不报错**。
    pub fn try_resolve_card_queue(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), HostError> {
        self.flush_deferred()?;
        // `:24-25`：`count <= 0 || !TryGetCombatant(ownerId)` ⇒ 返回。这里 count 恒为
        // `int.MaxValue`（turn-start 的用法，`:137`），所以只剩"战斗员不存在"。
        if state.combatant(actor).is_none() {
            return Ok(());
        }

        // `:29-33`：窗口在跑第一张之前快照。
        let mut waiting = [CardSlot::from_index(0); MAX_CARDS_PER_ZONE];
        let mut count = 0usize;
        {
            let Some(zones) = state.card_zones(actor) else {
                return Ok(());
            };
            for index in 0..zones.count(CardZone::QueuePile) {
                let Some(slot) = zones.slot_at(CardZone::QueuePile, index) else {
                    continue;
                };
                let Some(cell) = waiting.get_mut(count) else {
                    // QueuePile 的容量就是 `MAX_CARDS_PER_ZONE`，不可达。
                    return Err(HostError::Capacity(CapacityError::Full(
                        crate::state::Container::CardsInZone(CardZone::QueuePile),
                    )));
                };
                *cell = slot;
                count += 1;
            }
        }
        if count == 0 {
            return Ok(());
        }

        for index in 0..count {
            let Some(&slot) = waiting.get(index) else {
                break;
            };
            // `:51-56`：牌必须还在 `QueuePile` 里（窗口期间可能被别的东西搬走；程序自己
            // 也可以搬它 —— 参考用 `IsResolvingQueuedCard` 处理"正在解析的那一张"，
            // 本内核同步执行，跑到这里时它一定不在"正在解析"状态）。
            if !in_queue_pile(state, actor, slot) {
                continue;
            }
            let Some(instance) = state.card(slot) else {
                continue;
            };
            let definition = instance.definition_id;
            // `:66-70`：目标锁定，离场即失效（**不重定向**）。
            let target = instance
                .queued_target_id
                .filter(|locked| state.combatant(locked).is_some());

            // `:59-64`：定义必须在注册表里。参考 `continue`，这里响亮拒绝（见函数头）。
            let Some(row) = card_row(self.content, definition.as_str()) else {
                return Err(self.record(HostError::Content("CARD row")));
            };
            let card_index = row.index();

            // `:76-81`：没有节目 ⇒ 直接 Finish。
            let program = card_program_root(self.content, card_index)?;
            if let Some(root) = program {
                let steps = card_max_steps(self.content, card_index);
                let outcome = execute_program(state, self.content, root, Some(*actor), target, steps);
                if let Err(e) = outcome {
                    // `:106-107`：Faulted ⇒ 不 Finish、不继续，卡留在队列里。
                    return Err(self.record(HostError::Exec(e)));
                }
            }

            // `:120-122`：**Finish 自己也有一道前置** —— 牌必须还在 `QueuePile` 里。
            // "节目把这张牌搬走了"是合法行为，那时 Finish 什么都不做
            // （不清锁定、不搬牌、也不覆盖节目给它的落点）。
            if !in_queue_pile(state, actor, slot) {
                continue;
            }
            // 落点在这里才算：参考的 `PlayedCardDestination(registry, owner, card)`
            // 是在 `Finish` 里求值的（`:124-127`），不是解析之前。
            let destination = played_card_zone(self.content, row)?;
            // `:116-128` 的 `Finish`：清锁定 + 搬牌（就地，见函数头偏差）。
            if let Some(instance) = state.card_mut(slot) {
                instance.queued_target_id = None;
            }
            state.move_card(
                actor,
                CardZone::QueuePile,
                destination,
                slot,
                ZonePlacement::Bottom,
            )?;
        }
        Ok(())
    }

    /// **任何**入队之后的排空：三相位排空循环。
    ///
    /// 参考实现排空三个队列（效果 / 事件 / 续延，`CombatEventHandling.cs:81-115`）；
    /// 语义与逐行对照写在 [`Self::resolve_pending_queues_with`] 的文档里，这里只是
    /// "用参考的默认上限调它"。
    ///
    /// ⚠️ **2026-10-19 之前这个函数是恒 no-op，而且文档论证过它为什么可以**：
    /// "本宿主不在钩子之间保留任何待处理队列"（`exec::execute` 同步递归、触发器当场跑完）。
    /// 那个论证在批次 1 **失效了** —— 事件队列现在真的有内容（四个回合边界 + `DamageDealt`），
    /// 所以它必须真的排空。留下的结论只有一半：`exec` 仍然是同步递归的 ⇒
    /// **效果队列没有生产者**（见 [`Self::resolve_pending_effects`]）。
    ///
    /// ⚠️ 它**不**解析 `CardZone::QueuePile`（那是 [`Self::try_resolve_card_queue`]）——
    /// `turn.rs:130-152` 把这两件事分成了两个钩子，正是为了防止"同一个函数名两个语义"。
    pub fn try_resolve_pending_queues(&mut self, state: &mut CombatState) -> Result<(), HostError> {
        self.flush_deferred()?;
        self.resolve_pending_queues_with(state, QueueLimits::DEFAULT)
    }

    /// turn-start 最后一步：DoT 结算（`StatusEffects.cs:449-510`）。
    ///
    /// 参考的两段（**【验证】**）：
    ///
    /// **A. 处理器时点**（`:457-471`）
    /// 1. 战斗员不存在 ⇒ 返回。
    /// 2. 遍历 `combatant.Statuses`（**active-only** ⇒ 待转正的 DoT **不跳**）。
    /// 3. 判据是**实例上的标签** `damage_over_time`（`:462`），实例标签在创建时从定义拷贝
    ///    （`:196`）⇒ 走定义查表等价（[`status_bind::has_tag`]）。
    /// 4. `Stacks <= 0` ⇒ 不跳（`:465-466`）。
    /// 5. 每条实例一个请求，按实例序入队（`:468-471`），**请求里没有金额**。
    ///
    /// **B. 效果生效时点**（`:495-509`）
    /// 6. 按 id 重找实例，`Stacks <= 0` / 标签没了 ⇒ 什么都不做。
    /// 7. `Amount = status.Stacks`（`:504`，**没有任何系数**）、
    ///    `Kind = DamageKind::DamageOverTime`（`:507`）、`IgnoresBlock` 不传 ⇒ **吃格挡**
    ///    （默认 false，`:21-24`）、`SourceCombatantId = status.SourceCombatantId`
    ///    （`:505-506`）。
    /// 8. 走**同一条** `DealDamage` 管线；力量/虚弱/易伤被它们自己的
    ///    `RestrictDamageKind = Direct` 门挡掉（`PassiveModifiers.cs:154-156`）。
    ///
    /// ⇒ 这就是"必须传 `DamageKind::Dot`"的那一处。传 `Direct` 会让 DoT 吃上力量/易伤，
    /// 而每一个数字都看起来合理。
    ///
    /// ⚠️ 出手方（第 7 条）：`source_combatant_id` 是 2026-10-17 补进
    /// `state::StatusInstance` 的（裁决 2），在那之前这一格不存在 ⇒ Source 阶段
    /// **整段跳过**，于是"下毒者的 `DamageDealt` 加成"永远缺席，且**看不出来**
    /// （数字小一点，不会报错）。现在它被真的用上了，成对测试在
    /// `dot_takes_the_source_side_specs_now_that_the_field_exists` 那一条。
    ///
    /// ⚠️ 唯一的偏差：**A→B 之间不留时间**（本内核就地生效）。参考里那一段时间里可以插进
    /// 别的效果（例如一条"解毒"触发器把层数减掉，`:476-479` 的注释是在说这个）。今天没有
    /// 任何 DamageTaken/StatusChanged 触发器接上（21 个未接事件之一），所以两者观察等价；
    /// 而**层数**读的是生效时点的值（见 B 段的实现），这一半与参考一致。
    /// **Metallicize**: Block at the end of the turn (`standard.metallicize`, wiki: Lagavulin 8).
    ///
    /// A status implemented as a **host step**, the same shape [`Self::try_damage_over_time`] uses for
    /// poison -- this kernel has no trigger interpreter (`port-plan.md` §111/§112), so a status with a
    /// rule has a function, and `status_catalog::has_behaviour` names it.
    fn grant_end_of_turn_block(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), HostError> {
        let mut total = 0i32;
        {
            let Some(combatant) = state.combatant(actor) else {
                return Ok(());
            };
            for instance in combatant.statuses() {
                if !is_active(instance) || instance.stacks <= 0 {
                    continue;
                }
                if instance.definition_id.as_str() == "standard.metallicize" {
                    total += instance.stacks as i32;
                }
            }
        }
        if total <= 0 {
            return Ok(());
        }
        let Ok(pool) = crate::state::DefensivePoolId::new("standard.block") else {
            return Ok(());
        };
        if let Some(combatant) = state.combatant_mut(actor) {
            let current = combatant
                .defensive_pools()
                .iter()
                .find(|entry| entry.key.as_str() == "standard.block")
                .map_or(0, |entry| entry.pool.current);
            combatant
                .set_defensive_pool(pool, current + total, None)
                .map_err(|e| self.record(HostError::Capacity(e)))?;
        }
        Ok(())
    }

    pub fn try_damage_over_time(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), HostError> {
        self.flush_deferred()?;
        // A. 处理器时点：快照（定义 id、出手方），按实例序。
        let mut ticks = [(StatusDefinitionId::EMPTY, None); MAX_STATUSES_PER_COMBATANT];
        let mut count = 0usize;
        {
            let Some(combatant) = state.combatant(actor) else {
                return Ok(());
            };
            for instance in combatant.statuses() {
                if !is_active(instance) {
                    continue; // `:460` 用 `Statuses`（active-only）
                }
                if instance.stacks <= 0 {
                    continue; // `:465-466`
                }
                if !status_bind::has_tag(self.content, instance.definition_id.as_str(), TAG_DAMAGE_OVER_TIME)? {
                    continue; // `:462-463`
                }
                let Some(cell) = ticks.get_mut(count) else {
                    return Err(HostError::Capacity(CapacityError::Full(
                        crate::state::Container::Statuses,
                    )));
                };
                // 快照**来源**（`SourceCombatantId`）：它是这一次伤害的出手方，
                // 也就是 Source 阶段要读谁身上的 `DamageDealt` 修饰器。
                *cell = (instance.definition_id, instance.source_combatant_id);
                count += 1;
            }
        }

        // B. 效果生效时点：每条实例一次伤害，金额 = 层数（`:504`）。
        for index in 0..count {
            if state.result != CombatResult::Ongoing {
                break; // 参考的排空循环条件（`CombatEventHandling.cs:97`）
            }
            let Some((definition, source)) = ticks.get(index).copied() else {
                break;
            };
            // `:495-499`：重找实例；层数掉到 0 ⇒ 不做。**层数读的是生效时点的值**
            // （参考的模块注释 `:476-479` 专门解释过：先跑完的 turn-start 触发器可能
            // 已经把层数改小了，"解毒"效果必须能影响它自己前面排的那一跳）。
            // 出手方用的是**装箱时（处理器时点）**记下的那个 id —— 与参考
            // `SourceCombatantId: status.SourceCombatantId`（`:505-506`）同源。
            let Some(live_stacks) = state
                .combatant(actor)
                .and_then(|c| {
                    c.statuses()
                        .iter()
                        .find(|s| is_active(s) && s.definition_id == definition)
                })
                .map(|s| s.stacks)
            else {
                continue;
            };
            if live_stacks <= 0 {
                continue;
            }
            // ⚠️ **出手方是那条状态的来源，不是承受者**。参考把 `status.SourceCombatantId`
            // 塞进 `DealDamageEffectRequest`（`StatusEffects.cs:501-509`），而这条伤害的
            // Source 阶段（`PassiveModifiers.cs:242-254`）读的是**出手方**身上的
            // `DamageDealt` spec。传 `None` 会让"下毒者的力量加成"永远缺席，
            // 而且那个错**看不出来**（数字小一点，不像 bug）。
            //
            // 来源已离场（或这条状态没有来源）⇒ `ctx.source = None` ⇒ 整个 Source 阶段跳过，
            // 与参考"`combatant is null ⇒ return currentAmount`"（`:248-249`）一致。
            let mut ctx = ExecContext::new(state, source, None, None, DEFAULT_MAX_PROGRAM_STEPS)
                .with_content(self.content);
            exec::resolve_damage_of_kind(&mut ctx, actor, live_stacks, false, DamageKind::Dot)?;
        }
        Ok(())
    }

    /// turn-end 处理器 #1：牌在手里过回合的**生命周期节目**
    /// （`CardLifecyclePrograms.cs:21-46`，注册在 `StandardCombatPackage.cs:135`）。
    ///
    /// 这就是 Burn / Decay / Regret 那一类"在手里就会发作"的卡的机制：行为挂在**卡定义**上
    /// （`CardDefinition.LifecyclePrograms`，`CardDefinitions.cs:24-26`），不是一个按卡 id
    /// 过滤的全局触发规则。
    ///
    /// # 参考做什么（逐行读过，行号可查）
    ///
    /// 1. `TryGetCombatant(combatEvent.CombatantId)` 失败 ⇒ 返回（`CardLifecyclePrograms.cs:28-29`）。
    /// 2. `foreach (var card in combat.GetCardZones(combatEvent.CombatantId).GetCardsInZone(CardZone.Hand))`
    ///    （`:31`）—— **正在结束回合的那个战斗员的 `Hand`**，手牌序。
    /// 3. 定义查不到 ⇒ `continue`（`:33-34`）。
    /// 4. `definition.LifecyclePrograms.TryGetValue(CardLifecycleTrigger.TurnEndInHand, out var program)`
    ///    失败 ⇒ `continue`（`:35-36`）。`CardLifecycleTrigger` 今天**只有这一个成员**
    ///    （`:8-11`，【已验证】读过那 4 行）。
    /// 5. `EffectProgramExecutor.Execute(program, new CardLifecycleContext(definition, card.Id, owner.Id),
    ///    CardLifecycleTriggeredEffectSupport.CreateActionBuildContext(combat, owner), …)`（`:38-43`）。
    ///    那份上下文是 `Source = owner`、`EventTargetId = owner.Id`
    ///    （`Effects/CardLifecycleTriggeredEffects.cs:49-55`，【已验证】）
    ///    ⇒ 节目里的 `sel.source` **和** `sel.eventTarget` 都是正在结束回合的那个人。
    ///
    /// # 三条与参考对齐的细节
    ///
    /// * **跑的是 `LifecyclePrograms[TurnEndInHand]`，不是卡的 `Program`**（`:35` 那一格）。
    ///   镜像里它们是 `CARD` 行的**两格**（第 1 格 `Program` / 第 4 格 `LifecyclePrograms`，
    ///   `content.rs:1330`、`:1336`）⇒ 混用会让"每张在手里的卡都按出牌节目发作"。
    /// * **每个节目 +1 执行号，但 +0 链号**：执行号由 `Execute` 里发
    ///   （`Programs/EffectProgramExecution.cs:27`）；而处理器跑在 `TurnEndedCombatEvent` 的
    ///   **分发**里，那一刻 `CurrentEffectChain` 是事件自己那条链
    ///   （`CombatEventHandling.cs:60` 的 `using (combat.EnterEffectChain(entry.EffectChain))`），
    ///   所以节目链的 `??=`（`:31`）不会建新根链。内核把 `TurnEnded` 那**一个**链号发在
    ///   [`Self::try_run_turn_ended_triggers`] 里，而本钩子跑在它之前 ⇒ 这里用
    ///   [`CombatState::adopt_root_chain`]（**只建链、不推进 `next_effect_chain_number`**）
    ///   表达"复用一条已经发过号的链"。
    ///   ⚠️ 那条链的 **id** 在参考里是 TurnEnded 事件的号，内核此刻还没有它，拿到的是
    ///   "上一个已发的号"。id **不进哈希**（哈希里是 `chain_num` 计数器，`snapshot.rs:165`），
    ///   也没有任何按 id 的查表（`ChainRecord.id` 只被 `create_triggered_chain` 继承，
    ///   `state.rs:3441`）⇒ 可观察量（`chain_num`）与参考一致。
    /// * **节目只派发、不排空**（`Execute` 就是"派发"，`:38-43`）：Burn 的 2 点伤害在
    ///   [`Self::try_run_turn_ended_triggers`] 的排空里落地，与参考"整批 turn-end 处理器
    ///   跑完之后才排空"同构。
    ///
    /// # 今天的量（实测）
    ///
    /// 62/62 卡 `LifecyclePrograms = {}`（`CARD` 行第 4 格指向一个 **0 字段的 `_obj`**，term 11）
    /// ⇒ 真实内容上本钩子**一个节目都不跑**：不改一格状态、不发执行号、不建链。
    /// 那条"空"路径是 [`card_lifecycle_turn_end_program`] 的两次格读取，**不是特判**：
    /// 有节目的卡走的是同一条解码路。
    ///
    /// # 偏离参考的地方（都写在这里，别让它们变成隐藏假设）
    ///
    /// 1. **定义查不到 ⇒ 响亮失败**（[`HostError::Content`]），参考是 `continue`（`:33-34`）。
    ///    理由：手牌里有一张定义不在内容里的卡是**状态坏了**；静默跳过正好是"这张卡永远不发作
    ///    且没有任何信号"。真实内容走不到这一支（每张手牌的定义都在 `CARD` 表里）。
    /// 2. **节目上下文的"卡槽"没有对应物**：参考的 `CardLifecycleContext` 带
    ///    `(CardDefinition, CardInstanceId, OwnerId)`（`:15`），而 [`ExecContext`] 只有一个卡槽
    ///    `iteration_card`，它的语义被钉死为 `forEachCardInZone` 的迭代卡（`exec.rs:305-310`）
    ///    ⇒ **故意不绑**（绑了会让 `cardInstance.iterated` 静默读到这张卡，而参考里那个槽指的是
    ///    别的东西）。读卡槽的表达式在 `expr.rs::eval_card` 上得到
    ///    `ExprError::NoTarget`（**响亮**），与出牌那条路一致（`play.rs:1239` 同样传 `None`）。
    /// 3. **先快照手牌槽位**再逐个跑：参考的注释（`:17-20`）说"we snapshot the hand first"，
    ///    但 `:31` 的 `foreach` 里**没有**显式 `.ToArray()`，`CardZones.GetCardsInZone` 返回
    ///    拷贝还是活视图 **【未验证】**（没读 `CardZones.cs`）。选快照是因为"节目把自己的卡
    ///    搬走"在活视图下会让 C# 的 `foreach` 抛，而参考的注释明确说那种节目是合法的。
    /// 4. **先解码全部手牌、再跑第一个节目**：参考是边跑边解（第一张跑了一半才发现第二张的
    ///    节目坏了）。这里选"先全解"是 `exec` 的预检纪律（不留半执行的痕迹），只在"内容坏了"
    ///    时可观察。
    /// 5. **"已结束"就不跑**：`state.result != Ongoing` 时直接返回。参考里这条事件根本不会被
    ///    分发（排空循环条件 `CombatEventHandling.cs:97`），效果等价。
    ///
    /// 栈上两张 96 格的表（`hand` 192 B + `programs` ≈1.5 KB，32 位目标）—— 与 `state.rs` /
    /// `exec.rs` 里既有的 `[_; MAX_CARDS_PER_ZONE]` 缓冲同一量级；`CombatState` 自己是 207 KB，
    /// 所以这不是新量级的开销。写在这里是为了它别变成隐藏假设。
    ///
    /// 时点：它在 turn-end 处理器序里是**第 1 位**（`:135`），在弃手牌（`:136`）之前 ——
    /// 参考的注释（`:17-20`）说得很清楚：「before the end-of-turn discard, which is deferred」。
    /// 本内核的 `end_current_turn` 正是这个顺序（`turn.rs:747-751`）。
    pub fn try_hand_turn_end_lifecycle(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), HostError> {
        self.flush_deferred()?;
        let content = self.content;
        if state.result != CombatResult::Ongoing {
            return Ok(()); // 偏离 5：战斗已结束 ⇒ 这条事件不会被分发
        }

        // 1. 快照手牌的**槽位**（`CardSlot` 是牌池下标，节目搬牌也不会让它漂）。
        //    `count` 装不下是不可能的：一个区的上限就是 `MAX_CARDS_PER_ZONE`。真超了照样响亮。
        let mut hand: [Option<CardSlot>; MAX_CARDS_PER_ZONE] = [None; MAX_CARDS_PER_ZONE];
        let count = {
            let Some(zones) = state.card_zones(actor) else {
                return Ok(()); // `:28-29`：战斗员不在场 ⇒ 返回
            };
            let mut count = 0usize;
            for index in 0..zones.count(CardZone::Hand) {
                let Some(slot) = zones.slot_at(CardZone::Hand, index) else {
                    continue;
                };
                let Some(cell) = hand.get_mut(count) else {
                    return Err(self.record(HostError::Capacity(CapacityError::Full(
                        crate::state::Container::CardsInZone(CardZone::Hand),
                    ))));
                };
                *cell = Some(slot);
                count += 1;
            }
            count
        };

        // 2. 解码每一张的 `TurnEndInHand` 节目（**纯读**，不动状态）。
        let mut programs: [Option<LifecycleProgram<'_>>; MAX_CARDS_PER_ZONE] =
            [None; MAX_CARDS_PER_ZONE];
        let mut runs = 0usize;
        for index in 0..count {
            let Some(Some(slot)) = hand.get(index).copied() else {
                continue;
            };
            let Some(instance) = state.card(slot) else {
                continue;
            };
            let definition = instance.definition_id;
            if let Some(program) = card_lifecycle_turn_end_program(content, definition.as_str())? {
                if let Some(cell) = programs.get_mut(index) {
                    *cell = Some(program);
                }
                runs += 1;
            }
        }
        if runs == 0 {
            // 真实内容的日常路径（62/62 卡没有节目）：**一格状态都不动**、不发号、不建链。
            return Ok(());
        }

        // 3. 跑。链号：见上面"三条与参考对齐的细节"第 2 条 —— 复用一条已发过号的链，
        //    不推进 `next_effect_chain_number`（参考：这一批 turn-end 只有事件那一个号）。
        let chain = state
            .adopt_root_chain()
            .map_err(|e| self.record(HostError::Capacity(e)))?;
        let saved = state.current_chain();
        state.set_current_chain(chain);
        let mut failure: Option<HostError> = None;
        for index in 0..count {
            if state.result != CombatResult::Ongoing {
                break; // 参考的排空条件（`CombatEventHandling.cs:97`）：判了就停
            }
            let Some(Some(program)) = programs.get(index).copied() else {
                continue;
            };
            // `sel.source` / `sel.eventTarget` = 正在结束回合的那个人（`:49-55`）。
            let outcome = execute_program(
                state,
                content,
                program.root,
                Some(*actor),
                Some(*actor),
                program.max_steps,
            );
            if let Err(e) = outcome {
                failure = Some(self.record(HostError::Exec(e)));
                break;
            }
        }
        state.set_current_chain(saved);
        state.release_chain(chain);
        match failure {
            Some(e) => Err(e),
            None => Ok(()),
        }
    }

    /// turn-end 处理器 #3：触发程序（镜像 6 条）。
    /// turn-end 处理器 #3：全部 turn-end 触发器（镜像里 2 条）。
    ///
    /// 批次 1 起走事件队列，形状与 [`Self::try_run_turn_started_triggers`] 完全一致
    /// （`CombatTurnProcessor.cs:61-65` 入队 + `:67-70` 排空 ⇒ 链号 +1，位置从
    /// `TurnHost` 适配器挪到这里）。
    pub fn try_run_turn_ended_triggers(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), HostError> {
        self.flush_deferred()?;
        // Metallicize pays out **before** the turn-ended event, so the Block is there for whatever
        // the event's handlers read.
        self.grant_end_of_turn_block(state, actor)?;
        state
            .enqueue_event_at_root(CombatEvent::TurnEnded {
                combatant: *actor,
            })
            .map_err(|e| self.record(HostError::Capacity(e)))?;
        self.try_resolve_pending_queues(state)
    }

    /// turn-end 处理器 #4：按时长的状态减 1（`StatusEffects.cs:379-406` + `:333-377`）。
    ///
    /// 逐条照参考：
    ///
    /// 1. 战斗员不存在 ⇒ 返回（`:387-388`）。
    /// 2. 遍历 `Statuses`（**active-only** ⇒ pending 实例的时长**等待期间不衰减**，`:390`）。
    /// 3. 判据是**定义上的** `UsesDuration`（`:394`）—— 不是"时长轴 > 0"那种推断。
    /// 4. `DurationTurns <= 0` ⇒ 跳过（`:397-398`）。
    /// 5. `newDuration = max(0, old - 1)`（`:353-354`，`Amount` 默认 1，`:330`）。
    /// 6. **归零 ⇒ 删实例**（`:365` 的 `RemoveStatus`）。留一条 0 层实例不是等价物：
    ///    它会出现在 `s=` 行、参与 `statuses()`、并多吃一格 24 条的容量
    ///    （`exec.rs:1066-1079` 已经为同一条理由写过一段）。
    ///
    /// **今天恒空转**：镜像 23/23 状态 `UsesDuration = false`（实测，`F_BOOL` 原始值 1）。
    ///
    /// ⚠️ 一处如实说明：参考在归零后**入队** `StatusExpiredCombatEvent`（`:371-375`），
    /// 本内核没有事件队列。镜像里 **0 条** `StatusExpired` 触发器（实测 9 种事件里没有它），
    /// 所以今天没有观察者；内容一加，这里就要跟着开口 —— 那时正确的处置是**响亮拒绝**
    /// （借 `StatusExpired` 这个名字），而不是静默不发。
    pub fn try_decrease_timed_statuses(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), HostError> {
        self.flush_deferred()?;
        // 先快照"要处理的实例 id"（**实例序**），再逐个处理：删除会让下标移位，
        // 而按 id 重找是参考的做法（按实例处理、按实例删）。
        let mut targets = [None; MAX_STATUSES_PER_COMBATANT];
        let mut count = 0usize;
        {
            let Some(combatant) = state.combatant(actor) else {
                return Ok(());
            };
            for instance in combatant.statuses() {
                if !is_active(instance) {
                    continue; // `:390`
                }
                if instance.duration_turns <= 0 {
                    continue; // `:397-398`
                }
                if !status_bind::uses_duration(self.content, instance.definition_id.as_str())? {
                    continue; // `:394`
                }
                let Some(cell) = targets.get_mut(count) else {
                    return Err(HostError::Capacity(CapacityError::Full(
                        crate::state::Container::Statuses,
                    )));
                };
                *cell = Some(instance.id);
                count += 1;
            }
        }

        for index in 0..count {
            let Some(Some(id)) = targets.get(index).copied() else {
                continue;
            };
            let Some(combatant) = state.combatant_mut(actor) else {
                return Ok(());
            };
            let Some(position) = combatant.statuses().iter().position(|s| s.id == id) else {
                continue; // `:343-348`：实例已经没了
            };
            let current = combatant
                .statuses()
                .get(position)
                .map(|s| s.duration_turns)
                .unwrap_or(0);
            if current <= 0 {
                continue; // `:350-351`
            }
            let next = current.saturating_sub(1); // `Math.Max(0, old - 1)`（`:353-354`）
            if let Some(instance) = combatant.statuses_mut().get_mut(position) {
                instance.duration_turns = next;
            }
            if next == 0 {
                // `:362-375`：归零删实例。
                combatant.remove_status(position);
            }
        }
        Ok(())
    }

    /// 手牌是否整手保留（`CardTurnLifecycleEventHandlers.cs:39-59`）。
    ///
    /// 判据是**身上有任意一条 active 状态实例带 `retain_hand` 标签**
    /// （`:48-55` 的 `Statuses.Any(...)`）：不看层数、不看时长，`Any` 就够。
    ///
    /// 镜像 23/23 状态不带这个标签（实测）⇒ 恒 `false`，而 `false` 恰好就是参考在没有
    /// 该标签时的行为。**读标签失败**（镜像坏了）记进诊断槽并由下一个 `try_*` 弹出 ——
    /// 这个签名没有 `Result`，见模块头"错误面"。
    #[must_use]
    pub fn hand_is_retained_detail(&self, state: &CombatState, actor: &CombatantId) -> bool {
        match self.any_active_status_with_tag(state, actor, TAG_RETAIN_HAND) {
            Ok(found) => found,
            Err(e) => {
                self.record(e);
                true // 读不出来 ⇒ **保留**：弃掉一手牌是数据丢失，保留是可恢复的错。
            }
        }
    }

    /// 格挡是否保留（`DefensivePoolEffects.cs:283-322` 的 `retains`）。
    ///
    /// 判据同样是"身上有 active 状态带 `retain_block` 标签"（`:297`）。镜像 23/23 无此标签
    /// ⇒ 恒 `false` = 必清（= 参考的默认路径）。
    #[must_use]
    pub fn block_is_retained_detail(&self, state: &CombatState, actor: &CombatantId) -> bool {
        match self.any_active_status_with_tag(state, actor, TAG_RETAIN_BLOCK) {
            Ok(found) => found,
            Err(e) => {
                self.record(e);
                false // 读不出来 ⇒ 按默认（清）。理由同上：这一支不可达，选默认值最不吓人。
            }
        }
    }

    /// `TurnStartDraw` 管线后的抽牌数（`CardTurnLifecycleEventHandlers.cs:25-31`）。
    ///
    /// 判据与折叠全在 [`exec::fold_turn_start_draw`]（它复用 `exec.rs` 已经交付的候选表 +
    /// `crate::modifiers::apply`，**不另写一份折叠**）。
    ///
    /// 镜像有 1 条 `TurnStartDraw` spec：`panic` 的 `AddPerStack -1` ⇒ 带 `panic N` 的战斗员
    /// 少抽 N 张。**默认实现（返回 `base`）在这里是错的**，这就是本钩子非做不可的理由。
    #[must_use]
    pub fn turn_start_draw_count_detail(
        &self,
        state: &CombatState,
        actor: &CombatantId,
        base: i32,
    ) -> i32 {
        let Some(combatant) = state.combatant(actor) else {
            return base; // 参考：`TryGetCombatant` 失败 ⇒ 上下文工厂 null ⇒ 不跑
        };
        match exec::fold_turn_start_draw(combatant.statuses(), actor, base, Some(self.content)) {
            Ok(count) => count,
            Err(e) => {
                self.record(HostError::Exec(e));
                0 // 读不出来 ⇒ **一张都不抽**：一个空手牌回合是最显眼的错，不是最安静的。
            }
        }
    }

    /// 身上有没有**在生效**的状态实例带这个标签。
    ///
    /// active-only 是规格：`retain_hand` / `retain_block` 读的都是 `Statuses`
    /// （`CardTurnLifecycleEventHandlers.cs:48`、`DefensivePoolEffects.cs:297`），
    /// 而待转正的实例不在 `Statuses` 里（`CombatantState.cs:27-28`）。
    fn any_active_status_with_tag(
        &self,
        state: &CombatState,
        actor: &CombatantId,
        tag: &str,
    ) -> Result<bool, HostError> {
        let Some(combatant) = state.combatant(actor) else {
            return Ok(false);
        };
        for instance in combatant.statuses() {
            if !is_active(instance) {
                continue;
            }
            if status_bind::has_tag(self.content, instance.definition_id.as_str(), tag)? {
                return Ok(true);
            }
        }
        Ok(false)
    }

    // -----------------------------------------------------------------------------------------
    // 可选钩子：轮次边界（内容里有 4 条 RoundEnded 触发器，所以它**不是**空的）
    // -----------------------------------------------------------------------------------------

    /// `RoundEndedCombatEvent` 的触发器（`CombatTurnProcessor.cs:190-195`）。
    ///
    /// ⚠️ **与 TurnStarted/TurnEnded 的关键差异**：状态触发器在 `RoundEnded` 上
    /// **既不传 `gatingStatus` 也不传过滤器**（`SB:StatusDataRebuild.cs:121-124`，
    /// 【验证】我读过那四行）。⇒ 它**无条件**每次轮末都跑，谁在身都不问；
    /// 节目想限定对象只能靠自己的 `TargetSelector`。
    ///
    /// 镜像里 4 条全是 `node.setCombatantCounter`，其中 `sustained` 的选择器是
    /// `sel.withStatus(allCombatants, sustained)` ⇒ 没人在身时选择器解出空集，
    /// 于是"无条件跑"在观察上是 no-op。这解释了规格书 §3.6 留下的疑问
    /// （【未验证】→ 现在是**已验证**）。
    ///
    /// 上下文：`sel.source` = **正在结束回合的那个战斗员**
    /// （`RoundEndedCombatantTriggeredEffectContext` 读 `e.LastActiveCombatantId`，
    /// `TriggeredProgramContextAdapters.cs:74-82`），而 `turn.rs` 在自增轮次**之前**调本钩子、
    /// 那一刻 `active_combatant_id` 还是它（`turn.rs:809-812`）。
    pub fn try_on_round_ended(
        &mut self,
        state: &mut CombatState,
        ended_round: i32,
    ) -> Result<(), HostError> {
        self.flush_deferred()?;
        // `EnqueueEvent(new RoundEndedCombatEvent(round, LastActiveCombatantId))`
        // （`CombatTurnProcessor.cs:192-195`）：`LastActiveCombatantId` 是**入队那一刻**的
        // 行动者。`turn.rs:809-812` 在自增轮次**之前**调本钩子，所以 `active_combatant_id`
        // 还是它 —— 但载荷从哪里来是语义：事件**带着**那个 id（`TriggeredProgramContextAdapters.cs:74-82`
        // 拿的就是 `e.LastActiveCombatantId`），所以在这里快照进事件，而不是在分发时去读当前值。
        state
            .enqueue_event_at_root(CombatEvent::RoundEnded {
                round: ended_round,
                last_active: state.active_combatant_id,
            })
            .map_err(|e| self.record(HostError::Capacity(e)))?;
        self.try_resolve_pending_queues(state)
    }

    /// `RoundStartedCombatEvent` 的触发器（`:199-200`）。
    ///
    /// 同 [`Self::try_on_round_ended`] 的"无 gate、无过滤器"（`SB:StatusDataRebuild.cs:121-122`）。
    /// 上下文用的是**当前**的 `ActiveCombatantId`，而 `turn.rs` 在自增轮次**之后**、设新活跃
    /// 单位**之前**调本钩子（`turn.rs:815-829`）⇒ 上下文里的"行动者"是**上一轮**那个人
    /// —— 这与参考 `CombatTurnProcessor.cs:199-207` 的顺序一致（规格书 §3.6 点过这个坑）。
    ///
    /// 镜像里 **0 条** `RoundStarted` 触发器（实测 9 种事件里没有它）⇒ 今天恒 no-op。
    /// 仍然实现，是因为它与 [`Self::try_on_round_ended`] 共用同一段代码，而"内容一加就跑"
    /// 比"内容一加就静默不跑"值钱。
    pub fn try_on_round_started(
        &mut self,
        state: &mut CombatState,
        new_round: i32,
    ) -> Result<(), HostError> {
        self.flush_deferred()?;
        // `EnqueueEvent(new RoundStartedCombatEvent(CurrentRound))`（`:199-200`）⇒ 顶层入队 ⇒ 链号 +1。
        // 上下文读**当前** `ActiveCombatantId`（分发时读，见 `dispatch_event` 的注释）。
        state
            .enqueue_event_at_root(CombatEvent::RoundStarted { round: new_round })
            .map_err(|e| self.record(HostError::Capacity(e)))?;
        self.try_resolve_pending_queues(state)
    }

    /// 轮次事件的触发器：**不收 Bearer 过滤**（见 [`Self::try_on_round_ended`]）。
    ///
    /// 所以收集源是"场上**每一个**带触发器的状态定义"，而 `sel.source` 仍是那个战斗员。
    /// 按定义去重（同一个定义在场多个实例只跑一次），与其它事件一致。
    fn run_round_triggers(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        event: TriggerEvent,
    ) -> Result<(), HostError> {
        let mut batch = TriggerBatch::new();
        let mut seen_ids = [StatusDefinitionId::EMPTY; MAX_STATUSES_PER_COMBATANT];
        let mut seen_len = 0usize;
        // 先收集（借用 `state`），再跑（要 `&mut state`）。
        for combatant in state.combatants() {
            for instance in combatant.statuses() {
                if !is_active(instance) {
                    continue;
                }
                let definition = instance.definition_id;
                if seen_ids.get(..seen_len).unwrap_or(&[]).contains(&definition) {
                    continue;
                }
                let Some(slot) = seen_ids.get_mut(seen_len) else {
                    return Err(HostError::Content("status table"));
                };
                *slot = definition;
                seen_len += 1;

                let mut entries = [empty_trigger(self.content); MAX_TRIGGERS_PER_STATUS];
                let count = self.triggers_of(definition.as_str(), &mut entries)?;
                for i in 0..count {
                    let Some(entry) = entries.get(i).copied() else {
                        return Err(HostError::Content("status table"));
                    };
                    if entry.event != event {
                        continue;
                    }
                    batch.push(
                        definition.as_str(),
                        entry.index,
                        entry.root.id(),
                        entry.max_steps,
                    )?;
                }
            }
        }
        batch.sort();
        for i in 0..batch.len {
            if state.result != CombatResult::Ongoing {
                break;
            }
            let Some(handle) = batch.root.get(i).copied() else {
                break;
            };
            let steps = batch.max_steps.get(i).copied().unwrap_or(DEFAULT_MAX_PROGRAM_STEPS);
            let root = NodeRef::new(self.content, handle);
            let outcome = execute_program(state, self.content, root, Some(*actor), None, steps);
            outcome.map_err(|e| self.record(HostError::Exec(e)))?;
        }
        Ok(())
    }
}

// =============================================================================================
// 排空循环（`ResolvePendingQueues`，`CombatEventHandling.cs:81-115`）
// =============================================================================================

/// 排空的上限族（参考的 `CombatExecutionLimits`，`CombatExecutionLimits.cs:7-14`）。
///
/// 为什么做成**参数**而不是直接读常量：上限是"卡在循环里"的唯一出口，而"卡住"这种局面
/// 用真内容造不出来（要么转不出来，要么要等 1024 轮）。做成参数，测试就能用
/// `max_cycles: 0` / `max_events_per_cycle: 0` 把它**当场**撞出来 —— 那正是
/// `docs/spec/event-queue-interface.md` §6.2 的 V4 想证伪的东西（"队列满/超限必须响亮"）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct QueueLimits {
    /// `MaxQueueCycles`（`:12`，默认 1024）。
    pub max_cycles: u32,
    /// `MaxEffectsPerCycle`（`:13`）。
    pub max_effects_per_cycle: u32,
    /// `MaxEventsPerCycle`（`:14`）。
    pub max_events_per_cycle: u32,
}

impl QueueLimits {
    /// 参考的默认值（三个 1024）。
    pub const DEFAULT: Self = Self {
        max_cycles: MAX_QUEUE_CYCLES,
        max_effects_per_cycle: MAX_EFFECTS_PER_CYCLE,
        max_events_per_cycle: MAX_EVENTS_PER_CYCLE,
    };
}

impl Default for QueueLimits {
    fn default() -> Self {
        Self::DEFAULT
    }
}

impl Host<'_> {
    /// **排空循环**：`ResolvePendingQueues`（`CombatEventHandling.cs:81-115`）。
    ///
    /// 三相位，逐行照参考：
    ///
    /// ```text
    /// while ((HasPendingEffects || HasPendingEvents || HasPendingContinuations)
    ///        && Result == Ongoing)                          // :97  ← 两条条件**都在**
    /// {
    ///     if (resolvedCycles >= MaxQueueCycles) throw;       // :99-102
    ///     ResolvePendingEffects(...);                        // :104  相位 1：**抽干**
    ///     ResolvePendingEvents(...);                         // :105  相位 2：**抽干**
    ///     if (!HasPendingEffects && !HasPendingEvents
    ///         && TryDequeueContinuation(out var c)) c(combat); // :107-111 相位 3：**只跑一个**
    ///     resolvedCycles++;                                  // :113
    /// }
    /// ```
    ///
    /// 三条**不是风格**的细节：
    ///
    /// 1. **相位是"抽干"不是"一条"**：效果队列全空才轮到事件队列（`:104-105`）。所以
    ///    触发器节目入队的效果**晚于同批所有事件**生效 —— 把两相位塌成"入队即执行"
    ///    会让多段攻击的第二段读到第一段改过的状态（§2.3 的 D1/D2）。
    /// 2. **续延每轮只跑一个，且必须等前两相都空**（`:107-111`）。所以"续延永远晚于它
    ///    派生的效果"—— 这是"节目真的结束了"的定义。
    /// 3. **`Result == Ongoing` 是循环条件，不是入口检查**：战斗一结束，已经排队的条目
    ///    **不会再落地**（`run_triggers` 里那条 `break` 是同一件事的内层表达）。
    ///    实现成"入口查一次"会让战斗结束后仍分发事件 —— 表现是 `exec_num` 多涨。
    pub fn resolve_pending_queues_with(
        &mut self,
        state: &mut CombatState,
        limits: QueueLimits,
    ) -> Result<(), HostError> {
        let mut cycles = 0u32;
        while state.has_pending_queues() && state.result == CombatResult::Ongoing {
            if cycles >= limits.max_cycles {
                return Err(self.record(HostError::QueueCycleLimit {
                    cycles,
                    limit: limits.max_cycles,
                }));
            }
            // 相位 1：效果队列抽干。
            self.resolve_pending_effects(state, limits)?;
            // 相位 2：事件队列抽干。
            self.resolve_pending_events(state, limits)?;
            // 相位 3：**只跑一个**续延，且只有前两相都空了才跑。
            if !state.has_pending_effects() && !state.has_pending_events() {
                if let Some(continuation) = state.try_dequeue_continuation() {
                    self.run_continuation(state, continuation)?;
                }
            }
            cycles += 1;
        }
        // 排空结束 ⇒ 回收所有已到终态的节目帧（帧槽的下标被续延引用着，只在**静止点**回收）。
        exec::reap_frames(state);
        Ok(())
    }

    /// 相位 1：`ResolvePendingEffects`（`CombatEffectQueueProcessor.cs:20-60`）。
    ///
    /// 逐条：出队 → **进它自己的链作用域**（`CombatEffectQueueProcessor.cs:32` 的
    /// `using (combat.EnterEffectChain(entry.EffectChain))`）→ 交给 `exec::resolve_effect`。
    ///
    /// 两个**必须在这里**（而不是在 `exec` 里）做的动作：
    /// * 解析抛错 ⇒ 把帧绑回 `FaultDueToNativeHandler`（`EffectProgramIdentity.cs:156-162`）；
    /// * 解析把战斗打完了 ⇒ `CancelDueToCombatEnd`（`CombatState.cs:358-367`）—— 而且要
    ///   **带着这条效果的链**去取消：结果被设上那一刻的环境链就是那一条，Cancelled 的
    ///   收尾笔数由它决定。
    fn resolve_pending_effects(
        &mut self,
        state: &mut CombatState,
        limits: QueueLimits,
    ) -> Result<(), HostError> {
        let mut resolved = 0u32;
        while state.has_pending_effects() && state.result == CombatResult::Ongoing {
            if resolved >= limits.max_effects_per_cycle {
                return Err(self.record(HostError::QueuePhaseLimit {
                    phase: "effect",
                    resolved,
                    limit: limits.max_effects_per_cycle,
                }));
            }
            let Some(item) = state.dequeue_effect().map_err(HostError::Capacity)? else {
                break;
            };
            let chain = item.chain;
            let content = self.content;
            // `using (combat.EnterEffectChain(entry.EffectChain))`（`:32`）：解析期间
            // `current_chain` 就是这条 —— 于是解析过程中入队的东西**不再发号**（§1.4）。
            let outcome = state.with_chain(chain, |state| {
                exec::resolve_effect(state, &item, Some(content))
            });
            // 出队即放掉"队列条目持着这条链"那一次引用。
            state.release_chain(chain);
            if let Err(e) = outcome {
                exec::fail_frame(state, item.owner)
                    .map_err(|inner| self.record(HostError::Exec(inner)))?;
                return Err(self.record(HostError::Exec(e)));
            }
            if state.result != CombatResult::Ongoing {
                exec::cancel_live_frames(state, chain)
                    .map_err(|e| self.record(HostError::Exec(e)))?;
            }
            resolved += 1;
        }
        Ok(())
    }

    /// 相位 2：`ResolvePendingEvents`（`CombatEventHandling.cs:39-79`）。
    ///
    /// 逐条：出队 → **进它自己的链作用域**（`:60` 的 `using (EnterEffectChain(...))`）→
    /// 按注册序派发 handler。本内核每个事件类型**只有一个** handler（触发器分发），
    /// 所以"注册序"退化成"这个事件的那一个 handler"。
    ///
    /// ⚠️ 循环内部**再查一次** `Result == Ongoing`：相位 2 的每一条都可能结束战斗
    /// （触发器节目打死最后一个敌人），而参考的 `while` 也是逐圈读的（`:49-50`）。
    fn resolve_pending_events(
        &mut self,
        state: &mut CombatState,
        limits: QueueLimits,
    ) -> Result<(), HostError> {
        let mut resolved = 0u32;
        while state.has_pending_events() && state.result == CombatResult::Ongoing {
            if resolved >= limits.max_events_per_cycle {
                return Err(self.record(HostError::QueuePhaseLimit {
                    phase: "event",
                    resolved,
                    limit: limits.max_events_per_cycle,
                }));
            }
            let Some(item) = state.dequeue_event().map_err(HostError::Capacity)? else {
                break;
            };
            let chain = item.chain;
            let outcome = state.with_chain(chain, |state| self.dispatch_event(state, &item));
            state.release_chain(chain);
            outcome?;
            resolved += 1;
        }
        Ok(())
    }

    /// 分发一条事件：按**事件类型**找它那一个 handler。
    ///
    /// 五个变体对应参考的五条事件链，行号写在各自的臂上。没有 `_` 臂 —— 加变体时
    /// 编译器会在这里**拦住**（与 `exec.rs` 的分派同一条纪律）。
    pub fn dispatch_event(&mut self, state: &mut CombatState, item: &EventItem) -> Result<(), HostError> {
        match item.event {
            // `TurnStartedTriggeredEffects`（`SB:StatusDataRebuild.cs:39-42`，Bearer = 行动者）。
            CombatEvent::TurnStarted { combatant } => {
                self.run_triggers(state, &combatant, TriggerEvent::TurnStarted)
            }
            // `TurnEndedTriggeredEffects`（`:43-46`，Bearer = 行动者）。
            CombatEvent::TurnEnded { combatant } => {
                self.run_triggers(state, &combatant, TriggerEvent::TurnEnded)
            }
            // `RoundStartedTriggeredEffects`（`:121-122`）：**没有 gate、没有过滤器**，
            // 上下文读**当前** `ActiveCombatantId`（`TriggeredProgramContextAdapters.cs:66-70`）。
            CombatEvent::RoundStarted { .. } => {
                let Some(actor) = state.active_combatant_id else {
                    return Ok(());
                };
                self.run_round_triggers(state, &actor, TriggerEvent::RoundStarted)
            }
            // `RoundEndedTriggeredEffects`（`:123-124`）：同上，但上下文读事件里的
            // `LastActiveCombatantId`（`TriggeredProgramContextAdapters.cs:74-82`）——
            // 所以它从**事件载荷**取，而不是从当前 `active_combatant_id` 取。
            CombatEvent::RoundEnded { last_active, .. } => {
                let Some(actor) = last_active else {
                    return Ok(());
                };
                self.run_round_triggers(state, &actor, TriggerEvent::RoundEnded)
            }
            // `DamageDealtTriggeredEffects`（`:53-55`）：Bearer = **出手方**。
            CombatEvent::DamageDealt { target, source, .. } => {
                self.run_damage_dealt_triggers(state, &target, source)
            }
        }
    }

    /// `DamageDealt` 的触发器（`SB:StatusDataRebuild.cs:53-55`）。
    ///
    /// 三道与参考对齐的门，顺序是规格：
    ///
    /// 1. **上下文工厂**：承受者必须在场，否则返回 null ⇒ 跳过
    ///    （`TriggeredProgramContextAdapters.cs:89-97`）。出手方**可以为 null**（上下文欢迎它），
    ///    但下面第 3 条随即会拒。
    /// 2. **gating**：没人戴着这个状态就跳过（`TriggeredProgramDefinition.cs:139-144`）。
    ///    本层的 `collect_triggers` 是"从**佩戴者**的状态出发收集"，两条合成一步。
    /// 3. **Bearer 过滤器**：`DamageDealtSourceHasStatusTriggerFilter` —— **出手方**戴着它
    ///    （`DamageDealtTriggeredEffects.cs` 的 `Matches`：`SourceCombatant is not null &&
    ///    SourceCombatant.Statuses.Any(...)`）。出手方为 null ⇒ 不匹配。
    ///
    /// 节目上下文（`DamageDealtTriggeredEffectTargetResolver.CreateSelectionContext`）：
    /// `sel.source = SourceCombatant ?? TargetCombatant`、`EventTargetId = TargetCombatantId`。
    /// ⇒ `doubt` 的 `modifyStatusStacks(doubt, -1)` 落在**出手方**身上，不是承受者。
    fn run_damage_dealt_triggers(
        &mut self,
        state: &mut CombatState,
        target: &CombatantId,
        source: Option<CombatantId>,
    ) -> Result<(), HostError> {
        // 第 1 道：承受者不在场 ⇒ 上下文工厂返回 null（`:89-92`）。
        if state.combatant(target).is_none() {
            return Ok(());
        }
        // 第 2+3 道：Bearer = 出手方；它要是没戴着这个状态，收集出来就是空的。
        let Some(bearer) = source else {
            return Ok(());
        };
        let mut batch = TriggerBatch::new();
        self.collect_triggers(state, &bearer, TriggerEvent::DamageDealt, &mut batch)?;
        batch.sort();

        for i in 0..batch.len {
            if state.result != CombatResult::Ongoing {
                break;
            }
            let Some(handle) = batch.root.get(i).copied() else {
                break;
            };
            let steps = batch.max_steps.get(i).copied().unwrap_or(DEFAULT_MAX_PROGRAM_STEPS);
            let root = NodeRef::new(self.content, handle);
            // 执行号由 `exec::begin` 发（`EffectProgramExecution.cs:27`，**包括触发器节目**）。
            let outcome = execute_program(
                state,
                self.content,
                root,
                Some(bearer),
                Some(*target),
                steps,
            );
            outcome.map_err(|e| self.record(HostError::Exec(e)))?;
        }
        Ok(())
    }

    /// 跑一条续延（`CombatEventHandling.cs:107-111` 的 `c(combat)`）。
    ///
    /// ⚠️ **它跑在顶层**：`resolve_pending_queues_with` 在调用它之前把效果/事件两相都抽空了，
    /// 而且 `with_chain` 的作用域已经退出 ⇒ 此刻 `current_chain` 是 `NONE`。
    /// 这个位置本身就是语义：`CloseAction` 里那次 `EnqueueEvent(ActionResolved)`
    /// 会因此**建一条根链**（`CombatState.cs:442-452`）—— `play.rs` 今天用一句
    /// `create_root_effect_chain()` 手工记的就是这笔（`:785`、`:894` 的"账 2'"）。
    ///
    /// 两个变体各自去哪里：
    /// * `ProgramResume` ⇒ `exec::resume`（节点级续延调度，批次 2）；
    /// * `CloseAction` ⇒ `play::close_action`（与 `apply_plan` / 终态回调用的是**同一个函数**）。
    ///
    /// ⚠️ **它跑在顶层**：调用点已经退出所有 `EnterEffectChain` 作用域。这个位置本身就是
    /// 语义 —— 续延里每一次 `EnqueueEffect`/`EnqueueEvent` 会不会 `?? CreateRootEffectChain()`
    /// 全看此刻 `current_chain` 是不是 `NONE`（`CombatState.cs:386`/`:446`）。
    fn run_continuation(
        &mut self,
        state: &mut CombatState,
        continuation: Continuation,
    ) -> Result<(), HostError> {
        let anchor = NodeRef::new(self.content, 0);
        match continuation {
            Continuation::ProgramResume { frame, node } => {
                exec::resume(state, Some(self.content), Some(anchor), frame, node)
                    .map_err(|e| self.record(HostError::Exec(e)))
            }
            Continuation::CloseAction { actor } => {
                crate::play::close_action(state, actor);
                Ok(())
            }
        }
    }
}

// =============================================================================================
// `TurnHost`：错误**类别**的适配器（见模块头"错误面"）
// =============================================================================================

impl TurnHost for Host<'_> {
    fn activate_pending_statuses(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError> {
        self.try_activate_pending_statuses(state, actor)
            .map_err(|e| bridge(self.record(e)))
    }

    fn run_turn_started_triggers(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError> {
        // ⚠️ 这里**不再**手工发号：`try_run_turn_started_triggers` 现在真的
        // `enqueue_event_at_root(TurnStarted)`（`CombatTurnProcessor.cs:28-32`），
        // 号在那里发（`CombatState.cs:446` 的 `?? CreateRootEffectChain()`）。
        // 曾经是"这里发号 + 处理器直接跑"，那是**没有队列时**的等价写法；
        // 两处都发就是双倍发号（`event-queue-interface.md` §5.2 末的落地顺序警告）。
        self.try_run_turn_started_triggers(state, actor)
            .map_err(|e| bridge(self.record(e)))
    }

    fn resolve_card_queue(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError> {
        self.try_resolve_card_queue(state, actor)
            .map_err(|e| bridge(self.record(e)))
    }

    fn resolve_pending_queues(&mut self, state: &mut CombatState) -> Result<(), TurnError> {
        self.try_resolve_pending_queues(state)
            .map_err(|e| bridge(self.record(e)))
    }

    fn damage_over_time(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError> {
        self.try_damage_over_time(state, actor)
            .map_err(|e| bridge(self.record(e)))
    }

    fn hand_turn_end_lifecycle(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError> {
        self.try_hand_turn_end_lifecycle(state, actor)
            .map_err(|e| bridge(self.record(e)))
    }

    fn run_turn_ended_triggers(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError> {
        // 号在 `try_run_turn_ended_triggers` 的入队里发（同 turn-start 那条注释）。
        self.try_run_turn_ended_triggers(state, actor)
            .map_err(|e| bridge(self.record(e)))
    }

    fn decrease_timed_statuses(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
    ) -> Result<(), TurnError> {
        self.try_decrease_timed_statuses(state, actor)
            .map_err(|e| bridge(self.record(e)))
    }

    fn hand_is_retained(&self, state: &CombatState, actor: &CombatantId) -> bool {
        self.hand_is_retained_detail(state, actor)
    }

    // ── 带默认值的策略钩子 ──────────────────────────────────────────────────────────────────

    fn on_round_ended(&mut self, state: &mut CombatState, ended_round: i32) -> Result<(), TurnError> {
        // 号在 `try_on_round_ended` 的入队里发（同 turn-start 那条注释）。
        // ⚠️ **只有真的绕回**才有这条事件：`advance_to_next_combatant` 只在 `nxt <= cur`
        // 时调这个钩子，而参考也只在同一个分支里入队（`:190-201`）—— 两边的条件是同一条。
        self.try_on_round_ended(state, ended_round)
            .map_err(|e| bridge(self.record(e)))
    }

    fn on_round_started(&mut self, state: &mut CombatState, new_round: i32) -> Result<(), TurnError> {
        // 号在 `try_on_round_started` 的入队里发（同 turn-start 那条注释）。
        self.try_on_round_started(state, new_round)
            .map_err(|e| bridge(self.record(e)))
    }

    fn block_is_retained(&self, state: &CombatState, actor: &CombatantId) -> bool {
        self.block_is_retained_detail(state, actor)
    }

    fn turn_start_draw_count(&self, state: &CombatState, actor: &CombatantId, base: i32) -> i32 {
        self.turn_start_draw_count_detail(state, actor, base)
    }

    fn card_stays_in_hand_at_turn_end(
        &self,
        state: &CombatState,
        actor: &CombatantId,
        slot: CardSlot,
    ) -> bool {
        // 参考的两条：① 实例标记 `standard.retained_card` ② 定义 `RetainInHandOnTurnEnd`
        // （`CardZoneEffects.cs:419-425`）。
        //
        // ⚠️ 这里**故意**返回默认 `false`，而理由是**两条可复现的实测**（都钉在测试
        // `the_three_strategy_hooks_that_do_not_read_content_are_measured_not_assumed` 里）：
        //
        // * `CARD.RetainInHandOnTurnEnd` 是 `F_BOOL` 原始值 **1 = `BOOL_FALSE`，62/62**；
        // * ① 的标记来源是 `node.markCardInstance`，全镜像 **0 条 term**。
        //
        // ⇒ 今天两条判据都恒假，返回 `false` 与"逐张读出来"**观察等价**。
        // 为什么不去读：② 读一格就会多一条"读失败怎么办"的分支，而这条钩子没有 `Result`
        // （见 `flush_deferred` 的两条边界）；① 的节点 `exec` 根本不支持，只做一半更糟。
        // 内容一改成 `true`/一出现 `markCardInstance`，上面那条测试立刻红 —— 那时再来做。
        let _ = (state, actor, slot);
        false
    }

    fn turn_end_hand_destination(
        &self,
        state: &CombatState,
        actor: &CombatantId,
        slot: CardSlot,
    ) -> CardZone {
        // 参考：`definition.TurnEndHandDestinationZone`（`CardZoneEffects.cs:427`）。
        //
        // ⚠️ 返回默认 `DiscardPile` 的依据同样是实测，不是"应该没问题"：
        // `CARD.TurnEndHandDestinationZone` 这一格（`F_STR`）在**62/62 行**上都是
        // `"DiscardPile"`（同一格枚举名，不是哈希短名 `disc`）。所以返回默认值今天
        // 与"逐张读出来"观察等价。
        // 真要去读得先解决"枚举名不认识 / 串取不到"往哪儿报 —— 这条钩子没有 `Result`。
        let _ = (state, actor, slot);
        CardZone::DiscardPile
    }

    fn unspent_energy_carries(&self, state: &CombatState, actor: &CombatantId) -> bool {
        // 法令 `UnspentResourceCarries`（`ResourceEffects.cs:84-96`）。判据是**状态定义**上的
        // `CombatRules` 里有没有这个开关（`CombatDecrees.cs:39-42`）。
        //
        // ⚠️ 实测（同样钉在测试里）：`STAT.CombatRules` 在 **23/23** 状态上是
        // `ABSENT16`（整格不存在），`REL.CombatRules` 在 **49/49** 遗物上是空 `[]`。
        // ⇒ 恒 `false`，而 `false` 正是参考在没有该法令时的行为（"补到"，不是"累加"）。
        // `status_bind` 也根本不接 `CombatRules`（见到非空会怎样没有定义）——
        // 所以这一条是**今天正确的默认值**，不是"忘了做"；两条测试把它钉住。
        let _ = (state, actor);
        false
    }
}

// =============================================================================================
// 小工具
// =============================================================================================

/// 实例是否**在生效**（`IsActive == (PendingTurns == 0)`，`StatusInstance.cs:22`）。
///
/// 这一条是"active-only"视图的**唯一**判据，本模块 5 处依赖它（触发器收集、DoT、
/// 时长衰减、两个标签查询）。参考那边靠 `CombatantState.Statuses` 的性质实现
/// （`CombatantState.cs:27-28`），内核的 `statuses()` 返回全部实例 ⇒ 必须自己过滤。
const fn is_active(instance: &StatusInstance) -> bool {
    instance.pending_turns == 0
}

/// 这张牌现在在不在某个战斗员的 `QueuePile` 里（参考的 `zones.GetCard(id).Zone == QueuePile`，
/// `QueueResolution.cs:51-52` 与 `:120`）。
fn in_queue_pile(state: &CombatState, owner: &CombatantId, slot: CardSlot) -> bool {
    state.card_zones(owner).is_some_and(|zones| {
        zones
            .slots(CardZone::QueuePile)
            .iter()
            .any(|raw| usize::from(*raw) == slot.index())
    })
}

/// 暂存区用的"空触发器"（`NodeRef` 没有 `const` 构造，所以只能给一个**句柄**为 0 的占位）。
///
/// `NodeRef::new(content, 0)` 指向 `_null`（term 0），任何字段读取都会响亮报错 ——
/// 也就是说"占位被误用"不会静默成功。
fn empty_trigger<'a>(content: &'a Content<'a>) -> TriggerEntry<'a> {
    TriggerEntry {
        event: TriggerEvent::NotHandled,
        root: NodeRef::new(content, 0),
        max_steps: 0,
        index: 0,
    }
}

/// `STAT.Triggers[i]` 的 `_obj` → [`TriggerEntry`]。
///
/// 形状（二进制层面实测，见 [`TriggerEntry`] 的注释）：两个字段 `Event`(F_STR) +
/// `Program`(F_TERM → `_obj{Id,MaxNodeDepth,MaxProgramSteps,Root}`)。
///
/// 三条响亮拒绝，一条都不许"跳过当作没有"：
/// * `Event` 缺席 / 不是串 / 串不是 25 个名字之一 ⇒ [`HostError::Content`]；
/// * `Program` 缺席 ⇒ [`HostError::Content`]（参考的 `data.Program.Deserialize` 为 null 就抛，
///   `SB:StatusDataRebuild.cs:150-153`）；
/// * `Root` 缺席 ⇒ [`HostError::Content`]（节目信封里没有根就是坏信封）。
fn decode_trigger<'a>(
    content: &'a Content<'a>,
    handle: u16,
    index: u16,
) -> Result<TriggerEntry<'a>, HostError> {
    let node = NodeRef::new(content, handle);
    let name = node
        .str_field("Event")?
        .ok_or(HostError::Content("Trigger.Event"))?;
    let event = TriggerEvent::from_wire_name(name).ok_or(HostError::Content("TriggerEvent"))?;
    let program = node
        .node_field("Program")?
        .ok_or(HostError::Content("Trigger.Program"))?;
    let root = program
        .node_field("Root")?
        .ok_or(HostError::Content("Program.Root"))?;
    // 信封上还有 `Id`（`_wrap_upper` 的 `{Value: "(unnamed)"}`）与 `MaxNodeDepth`，
    // 两者本层都不用：`MaxNodeDepth` 由 `exec.rs` 的 `MAX_NODE_DEPTH` 兜住（同为 64），
    // `Id` 只是调试名。
    let max_steps = match program.int_field("MaxProgramSteps")? {
        Some(value) if value > 0 => u32::try_from(value).unwrap_or(DEFAULT_MAX_PROGRAM_STEPS),
        _ => DEFAULT_MAX_PROGRAM_STEPS,
    };
    Ok(TriggerEntry {
        event,
        root,
        max_steps,
        index,
    })
}

/// 跑一个节目：`source` 与 `event_target` 就是参考 `CreateActionBuildContext` 的两个槽。
///
/// `sel.source` / `sel.eventTarget` 由此解析；`iteration_target` 恒空（触发器上下文没有它）。
/// ⚠️ **它只派发**（批次 2）：节目造出来的效果请求进队列，等外层的排空循环解析
/// （`CombatEventHandling.cs:97-113` 的相位 1）。宿主**不在钩子里排空** —— 那是回合驱动
/// （`turn.rs`）与场景驱动的活，参考也是这么分的（`CombatTurnProcessor` 自己调
/// `ResolvePendingQueues`，`ScenarioRunner` 自己调）。
fn execute_program(
    state: &mut CombatState,
    content: &Content<'_>,
    root: NodeRef<'_>,
    source: Option<CombatantId>,
    event_target: Option<CombatantId>,
    max_steps: u32,
) -> Result<(), exec::ExecError> {
    let mut ctx = ExecContext::new(state, source, event_target, None, max_steps)
        .with_content(content);
    exec::begin(root, &mut ctx, crate::state::ProgramTerminalHook::None).map(|_| ())
}

/// `CARD` 行按定义 id 查（内核的"卡定义表"就是镜像的 `CARD` 表，`play.rs:572-575`）。
fn card_row<'a>(
    content: &'a Content<'a>,
    definition_id: &str,
) -> Option<crate::content::CardRow<'a>> {
    let entry = content.lookup_in(definition_id, EK_CARD)?;
    content.card(u32::from(entry.index))
}

/// 卡的**已出牌落区**（`PlayedCardDestinationZone`，构造默认 `DiscardPile`）。
///
/// 与 `play.rs:1411-1424` 的同名函数逐字同形 —— 那边是私有的，而"只准改这三个文件"
/// 这条约束禁止我去加 `pub`。**将来把它提升成公共函数时，这一份应当删掉。**
fn played_card_zone(content: &Content<'_>, row: crate::content::CardRow<'_>) -> Result<CardZone, HostError> {
    let handle = row.played_card_destination_zone();
    if handle == ABSENT16 || handle == NULL16 {
        return Ok(CardZone::DiscardPile);
    }
    let name = content
        .string(handle)
        .ok_or(HostError::Content("PlayedCardDestinationZone"))?;
    zone_from_wire_name(name).ok_or(HostError::Content("PlayedCardDestinationZone"))
}

/// C# 的 `CardZone` 枚举名 → 内核的 [`CardZone`]。
///
/// ⚠️ **不是** [`CardZone::wire_name`]：那是哈希用的短名（`disc`/`exh`），镜像里存的是
/// 枚举名原文（`"DiscardPile"` / `"QueuePile"` …）。同 `play.rs:1426-1443`。
fn zone_from_wire_name(name: &str) -> Option<CardZone> {
    match name {
        "DrawPile" => Some(CardZone::DrawPile),
        "Hand" => Some(CardZone::Hand),
        "DiscardPile" => Some(CardZone::DiscardPile),
        "ExhaustPile" => Some(CardZone::ExhaustPile),
        "BanishedPile" => Some(CardZone::BanishedPile),
        "QueuePile" => Some(CardZone::QueuePile),
        "SetAsidePile" => Some(CardZone::SetAsidePile),
        _ => None,
    }
}

/// 卡的效果程序根（`CARD.Program` → `_obj{…, Root}`）。
///
/// `Ok(None)` = 没有 `Program` 格（参考走"无节目"分支，`CardPlay.cs:283-293`）；
/// 其余断链响亮失败（同 `play.rs:1290-1310` 的 `card_program`）。
fn card_program_root<'a>(
    content: &'a Content<'a>,
    index: u32,
) -> Result<Option<NodeRef<'a>>, HostError> {
    match crate::ir::Ir::new(content).card_program_root(index) {
        Ok(root) => Ok(Some(root)),
        Err(IrError::Missing("Program")) => Ok(None),
        Err(e) => Err(e.into()),
    }
}

/// `CARD` 行信封上的 `MaxProgramSteps`（缺席 ⇒ 1024，`EffectProgramContracts.cs:560-563`）。
fn card_max_steps(content: &Content<'_>, index: u32) -> u32 {
    let Some(row) = content.card(index) else {
        return DEFAULT_MAX_PROGRAM_STEPS;
    };
    let envelope = NodeRef::new(content, row.program());
    match envelope.int_field("MaxProgramSteps") {
        Ok(Some(value)) if value > 0 => u32::try_from(value).unwrap_or(DEFAULT_MAX_PROGRAM_STEPS),
        _ => DEFAULT_MAX_PROGRAM_STEPS,
    }
}

/// `CardLifecycleTrigger` 的唯一成员（`Cards/CardLifecyclePrograms.cs:8-11`，【已验证】）。
///
/// JSON/镜像里的**键名**。参考的枚举今天只有它一个值 ⇒ 别的键 = 内容用了内核没有的路。
const TURN_END_IN_HAND: &str = "TurnEndInHand";

/// 同一个触发器的**第二种可能的拼法**：枚举序数（`TurnEndInHand` 的序数是 0）。
///
/// ⚠️ **【未验证】** 哪一种拼法会真的出现在镜像里：`LifecyclePrograms` 在 62/62 卡上都是
/// `{}`（空对象，一个键都没有），所以**没有任何实例能观察键名**。两种拼法都要么是
/// `System.Text.Json` 对"枚举键字典"的默认输出（序数），要么是挂了
/// `JsonStringEnumConverter` 之后的输出（名字）；`tools/contentc/compile.py` 按 JSON 的键名
/// 原样派生 `_obj(键…)` 的字段名。两种都接受、并且**两个同时出现就报错**（同一个触发器
/// 两条节目是内容自相矛盾）；两个都不是 ⇒ 响亮失败（见 [`HostError::Unsupported`]）。
const TURN_END_IN_HAND_ORDINAL: &str = "0";

/// `CARD.LifecyclePrograms[TurnEndInHand]` 的一个节目（`EffectProgram<CardLifecycleContext>`）。
#[derive(Clone, Copy)]
struct LifecycleProgram<'a> {
    /// 节目根（信封里的 `Root`）。
    root: NodeRef<'a>,
    /// 信封里的 `MaxProgramSteps`（缺席 ⇒ 1024）。
    max_steps: u32,
}

/// 解一张卡的 `TurnEndInHand` 生命周期节目：`Ok(None)` = 这张卡没有那条节目。
///
/// # 实测形状（二进制层面量的）
///
/// 62/62 卡这一格都指向 **term 11**：`op = 89`（`_obj`，opclass 通用）**零个字段**。
/// 也就是说"空"的编码是**0 字段的 `_obj`** —— 不是 `_arr`、不是哨兵 ⇒ 判据是
/// `opcode.nfields() == 0`（字段数是 **opcode** 的属性，不是 term 的，`content.rs:1427-1432`）。
///
/// # 非空时它长什么样（**推导，不是实测**）
///
/// 参考的类型是 `IReadOnlyDictionary<CardLifecycleTrigger, EffectProgram<CardLifecycleContext>>`
/// （`Cards/CardDefinitions.cs:26`）⇒ JSON 里是一个**对象**，键 = 触发器名，值 = 节目信封。
/// `tools/contentc/compile.py` 给每个"普通对象形状"派生一个 `_obj(排序后的键…)` opcode
/// （`rdcfmt.py:90-94`），所以镜像里就是 `_obj(TurnEndInHand)`，它那一格是 `F_TERM`，
/// 指向与卡自己的 `Program` **同一个**信封形状（`{Id, MaxNodeDepth, MaxProgramSteps, Root}`，
/// 见 `ir.rs::card_program_root`）。
/// ⇒ 本条解码路今天在真实内容上**永远走不到非空分支**（62/62 是 `{}`）；
/// 它是按"编译器的派生规则 + 参考的类型"写的，接线正确性靠 `host.rs` 测试里那几张
/// **手搓镜像**的卡（`burn`/`burn_dual`/`weird`…）钉住。
///
/// # 四条"响亮"（一条都不许静默当作没有）
///
/// * 卡定义不在 `CARD` 表里 ⇒ [`HostError::Content`]（偏离参考的 `continue`，理由写在
///   [`Host::try_hand_turn_end_lifecycle`] 的偏离 1）；
/// * 这一格不是动态对象（`_arr` / 标量）⇒ [`HostError::Content`]：参考的类型是字典，
///   `_arr` 不是它的编码（旧版本这里接 `_arr` 的 count，那是按"可能是列表"猜的）；
/// * 键名不是那两种拼法之一 ⇒ [`HostError::Unsupported`]（**内核缺能力**：参考的枚举今天
///   只有 `TurnEndInHand` 一个成员，别的键 = 内容用了 v1 没实现的生命周期触发器）；
/// * 值是 null、或信封里没有 `Root` ⇒ [`HostError::Content`]（前者参考会拿 null 节目去
///   `Execute` = 空引用；后者是坏信封）。
fn card_lifecycle_turn_end_program<'a>(
    content: &'a Content<'a>,
    definition_id: &str,
) -> Result<Option<LifecycleProgram<'a>>, HostError> {
    let row = card_row(content, definition_id).ok_or(HostError::Content("CARD row"))?;
    let handle = row.lifecycle_programs();
    if handle == ABSENT16 || handle == NULL16 {
        // 整格缺席 / 显式 null ⇒ 参考那边是空字典 ⇒ 没有节目。
        return Ok(None);
    }
    let term = content
        .term(handle)
        .ok_or(HostError::Content("LifecyclePrograms"))?;
    if term.op < crate::content::OP_FIRST_DYNAMIC {
        // `_arr`/`_str`/`_int`… 都不是"字典"的编码。
        return Err(HostError::Content("LifecyclePrograms"));
    }
    let opcode = content
        .opcode(term.op)
        .ok_or(HostError::Content("LifecyclePrograms"))?;
    let node = NodeRef::new(content, handle);
    let mut program: Option<NodeRef<'a>> = None;
    for index in 0..opcode.nfields() {
        let field = opcode
            .field(index)
            .ok_or(HostError::Content("LifecyclePrograms"))?;
        let name = content
            .string(field.name_str())
            .ok_or(HostError::Content("LifecyclePrograms"))?;
        if name != TURN_END_IN_HAND && name != TURN_END_IN_HAND_ORDINAL {
            return Err(HostError::Unsupported("CardLifecycleTrigger"));
        }
        if program.is_some() {
            // 两种拼法同时出现 ⇒ 同一个触发器写了两条节目。
            return Err(HostError::Content("LifecyclePrograms"));
        }
        match node.field(name)? {
            // `F_TERM` 的缺席哨兵 ⇒ 这个键没写。
            None | Some(Value::Absent) => {}
            Some(Value::Null) => return Err(HostError::Content("LifecyclePrograms")),
            Some(Value::Node(inner)) => program = Some(inner),
            // 声明成 `F_TERM` 却装了标量：`field()` 已经在这里报过错了，这一支不可达。
            Some(_) => return Err(HostError::Content("LifecyclePrograms")),
        }
    }
    let Some(program) = program else {
        // 0 字段的 `_obj`：真实内容 62/62 卡就是这一支。
        return Ok(None);
    };
    let root = program
        .node_field("Root")?
        .ok_or(HostError::Content("LifecyclePrograms"))?;
    let max_steps = match program.int_field("MaxProgramSteps")? {
        Some(value) if value > 0 => u32::try_from(value).unwrap_or(DEFAULT_MAX_PROGRAM_STEPS),
        _ => DEFAULT_MAX_PROGRAM_STEPS,
    };
    Ok(Some(LifecycleProgram { root, max_steps }))
}

// =============================================================================================
// 测试
//
// 全部读真实镜像（`tools/contentc/out/content.core.rdcf`）。镜像不在仓库里（构建产物），
// 找不到就 panic 并打印路径与生成命令 —— 产物缺席时安静通过的测试等于没有测试。
// =============================================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::content::{Content, FORMAT_VERSION, MAGIC, OP_ARR};
    use crate::exec::ExecError;
    use crate::expr::ExprError;
    use crate::state::{
        CardDefinitionId, CardInstance, CardInstanceId, CombatId, Combatant, CombatantDefinitionId,
        CounterId, DefensivePoolId, EffectRequest, ProgramExecutionSlot, ResourceId,
        StatusInstanceId, StatusPolarity, TeamId,
    };
    use crate::turn::{self, TurnConfig};
    use std::vec::Vec;

    const CORE_IMAGE_REL: &str = "../../tools/contentc/out/content.core.rdcf";

    // ---------------------------------------------------------------- 脚手架

    fn core_image() -> Vec<u8> {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(CORE_IMAGE_REL);
        std::fs::read(&path).unwrap_or_else(|e| {
            panic!(
                "RDCF 镜像缺失或读不到：{}\n  {e}\n  \
                 它是 tools/contentc 的构建产物，生成命令：\n    \
                 python tools/contentc/compile.py\n  \
                 （同时写出 tools/contentc/out/content.rdcf 与 content.core.rdcf）",
                path.display()
            )
        })
    }

    fn parse(blob: &[u8]) -> Content<'_> {
        Content::parse(blob).expect("真实镜像必须能解析")
    }

    fn cid(s: &str) -> CombatantId {
        CombatantId::new(s).unwrap()
    }

    fn unit(id: &str, team: &str, health: i32, max: i32) -> Combatant {
        Combatant::new(
            cid(id),
            CombatantDefinitionId::new(id).unwrap(),
            TeamId::new(team).unwrap(),
            health,
            max,
        )
    }

    /// 只有英雄一个人 ⇒ `end_current_turn` 的推进必然绕回（`nxt <= cur`），
    /// 于是 `on_round_ended` 每次都被调到。回合机的这个性质在 `turn.rs` 的测试里钉着。
    fn solo() -> CombatState {
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state.add_combatant(unit("hero", "player", 70, 70)).unwrap();
        state
    }

    /// 英雄 + 两个敌人（`enemy_a` / `enemy_b`），用于"目标"与"目标已离场"两条路。
    fn arena() -> CombatState {
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state.add_combatant(unit("hero", "player", 70, 70)).unwrap();
        state.add_combatant(unit("enemy_a", "enemy", 20, 20)).unwrap();
        state.add_combatant(unit("enemy_b", "enemy", 10, 10)).unwrap();
        state
    }

    /// 英雄 + **一个**敌人（`foe`）：回合末推进到 `foe` 时 `nxt > cur` ⇒ **不绕回**，
    /// 于是没有 RoundEnded / RoundStarted 两条事件混进链号账里（那两条是别的测试的观察对象）。
    ///
    /// `hero_health` 是初始血量（致命那一条用 2）。
    fn duel(hero_health: i32) -> CombatState {
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state
            .add_combatant(unit("hero", "player", hero_health, 70))
            .unwrap();
        state.add_combatant(unit("foe", "enemy", 20, 20)).unwrap();
        state
    }

    fn config() -> TurnConfig {
        TurnConfig {
            energy: ResourceId::new("standard.energy").unwrap(),
            energy_refill: 3,
            draw_per_turn: 5,
            block_pool: DefensivePoolId::new("standard.block").unwrap(),
            max_hand_size: i32::MAX,
        }
    }

    fn status(instance: &str, definition: &str, stacks: i32) -> StatusInstance {
        StatusInstance::new(
            StatusInstanceId::new(instance).unwrap(),
            StatusDefinitionId::new(definition).unwrap(),
            StatusPolarity::Debuff,
        )
        .with_stacks(stacks)
    }

    fn give(state: &mut CombatState, who: &str, instance: StatusInstance) {
        state
            .combatant_mut(&cid(who))
            .unwrap()
            .push_status(instance)
            .unwrap();
    }

    fn give_pending(
        state: &mut CombatState,
        who: &str,
        mut instance: StatusInstance,
        pending: i32,
    ) {
        instance.pending_turns = pending;
        give(state, who, instance);
    }

    /// 挂一条**记了来源**的状态（DoT 的出手方就是它）。
    ///
    /// ⚠️ 实例 id 必须是短的：`StatusInstanceId` 的容量是 `INSTANCE_ID_CAP`（16 B，
    /// 为 `status_000001` 这种生成形状定的），而它和 `StatusDefinitionId` 的
    /// `ID_CAP`(40) **不是同一个数**。
    fn give_dot_from(
        state: &mut CombatState,
        who: &str,
        definition: &str,
        stacks: i32,
        source: &str,
    ) {
        let instance = status("s_dot", definition, stacks).with_source_combatant(cid(source));
        give(state, who, instance);
    }

    fn give_block(state: &mut CombatState, who: &str, current: i32) {
        state
            .combatant_mut(&cid(who))
            .unwrap()
            .set_defensive_pool(DefensivePoolId::new("standard.block").unwrap(), current, None)
            .unwrap();
    }

    fn give_energy(state: &mut CombatState, who: &str, current: i32) {
        state
            .combatant_mut(&cid(who))
            .unwrap()
            .set_resource(ResourceId::new("standard.energy").unwrap(), current, Some(3))
            .unwrap();
    }

    fn give_counter(state: &mut CombatState, who: &str, key: &str, value: i32) {
        state
            .combatant_mut(&cid(who))
            .unwrap()
            .set_counter(CounterId::new(key).unwrap(), value)
            .unwrap();
    }

    fn give_card(
        state: &mut CombatState,
        who: &str,
        zone: CardZone,
        instance: &str,
        definition: &str,
        target: Option<&str>,
    ) {
        let mut card = CardInstance::new(
            CardInstanceId::new(instance).unwrap(),
            CardDefinitionId::new(definition).unwrap(),
        );
        card.queued_target_id = target.map(cid);
        state.push_card(&cid(who), zone, card).unwrap();
    }

    /// 往抽牌堆塞 `n` 张 `paper_cut`。
    ///
    /// 有用处：`turn.rs` 的回合开始抽 5 张，而抽牌堆空、弃牌堆非空时会**重洗**
    /// （`CardZoneEffects.cs:49-82`）—— 那会把刚落到弃牌堆的队列卡抽回手里，
    /// 让"卡落到哪里"的断言飘。这些测试只关心队列，不需要那条重洗路径。
    fn give_draw_pile(state: &mut CombatState, who: &str, n: usize) {
        for i in 0..n {
            give_card(
                state,
                who,
                CardZone::DrawPile,
                &std::format!("draw{i}"),
                "paper_cut",
                None,
            );
        }
    }

    fn health(state: &CombatState, who: &str) -> i32 {
        state.combatant(&cid(who)).unwrap().health_current
    }

    fn block_of(state: &CombatState, who: &str) -> i32 {
        state
            .combatant(&cid(who))
            .unwrap()
            .defensive_pools()
            .iter()
            .find(|p| p.key == DefensivePoolId::new("standard.block").unwrap())
            .map_or(0, |p| p.pool.current)
    }

    fn energy_of(state: &CombatState, who: &str) -> i32 {
        state
            .combatant(&cid(who))
            .unwrap()
            .resources()
            .iter()
            .find(|p| p.key == ResourceId::new("standard.energy").unwrap())
            .map_or(-1, |p| p.pool.current)
    }

    fn counter_of(state: &CombatState, who: &str, key: &str) -> i32 {
        state
            .combatant(&cid(who))
            .unwrap()
            .counters()
            .iter()
            .find(|c| c.key == CounterId::new(key).unwrap())
            .map_or(-1, |c| c.value)
    }

    fn zone_count(state: &CombatState, who: &str, zone: CardZone) -> usize {
        state.card_zones(&cid(who)).map_or(0, |z| z.count(zone))
    }

    fn stacks_of(state: &CombatState, who: &str, definition: &str) -> i32 {
        state
            .combatant(&cid(who))
            .unwrap()
            .statuses()
            .iter()
            .filter(|s| s.definition_id.as_str() == definition)
            .map(|s| s.stacks)
            .sum()
    }

    fn instances_of(state: &CombatState, who: &str, definition: &str) -> usize {
        state
            .combatant(&cid(who))
            .unwrap()
            .statuses()
            .iter()
            .filter(|s| s.definition_id.as_str() == definition)
            .count()
    }

    fn pending_of(state: &CombatState, who: &str, definition: &str) -> i32 {
        state
            .combatant(&cid(who))
            .unwrap()
            .statuses()
            .iter()
            .find(|s| s.definition_id.as_str() == definition)
            .map_or(-1, |s| s.pending_turns)
    }

    fn duration_of(state: &CombatState, who: &str, definition: &str) -> i32 {
        state
            .combatant(&cid(who))
            .unwrap()
            .statuses()
            .iter()
            .find(|s| s.definition_id.as_str() == definition)
            .map_or(-1, |s| s.duration_turns)
    }

    /// 哈希的**输入文本**（`snapshot::write_hash_input`）—— 比"挑几个字段看"强得多的
    /// "什么都没动"判据，`exec.rs` 的测试用的是同一招。
    fn state_text(state: &CombatState) -> Vec<u8> {
        let mut buf = [0u8; 1 << 16];
        let mut w = crate::writer::TextWriter::new(&mut buf);
        crate::snapshot::write_hash_input(&mut w, state);
        assert!(!w.overflowed(), "指纹缓冲装不下");
        w.as_str().as_bytes().to_vec()
    }

    /// 规范文本去掉两个**计数器**行（`chain_num=` / `exec_num=`），其余逐字节保留。
    ///
    /// 用来写"这一笔只许动这两个数"那种断言：把它们抹掉再比，剩下的任何差异都是真差异。
    /// ⚠️ 不能反过来用（"抹掉之后相等 ⇒ 只有它们变了"），所以抹掉的**行数**在函数里另有一条断言
    /// —— 少了那一句，两行都被挤掉时这条判据就自证其说。
    fn strip_counters(text: &[u8]) -> Vec<u8> {
        let haystack = core::str::from_utf8(text).unwrap_or_default();
        let mut out = String::new();
        let mut dropped = 0usize;
        for line in haystack.lines() {
            if line.starts_with("chain_num=") || line.starts_with("exec_num=") {
                dropped += 1;
                continue;
            }
            out.push_str(line);
            out.push('\n');
        }
        assert_eq!(dropped, 2, "规范文本里应该正好有 chain_num 与 exec_num 各一行");
        out.into_bytes()
    }

    // =========================================================== 手搓镜像（生命周期节目）
    //
    // 真实镜像 **62/62 卡 `LifecyclePrograms = {}`** ⇒ "节目真的跑了"这件事在真实内容上
    // **没有观察对象**。所以这里手搓一份最小 RDCF 镜像，给 `try_hand_turn_end_lifecycle`
    // 用：一张"在手里过回合扣自己 2 点"的卡 —— 就是参考测试里的 `curse.burn`
    // （`ref/…/tests/RogueDeck.Core.Tests/Combat/CardLifecycleProgramTests.cs:13-29`）。
    //
    // 格式的权威是两头，都逐条对过：
    // * 写盘方 `tools/contentc/rdcfmt.py`（段号/行宽/`F_*` 的槽编码/哨兵值）；
    // * 读盘方 `content.rs`（`parse` 验目录，`validate` 验段内自洽）。
    //
    // ⚠️ 这份镜像是**测试脚手架**，不是"内容规范"：它只放断言需要的那 6 张卡、24 个 opcode、
    // 16 条 term。谁改它，`the_hand_rolled_burn_image_is_a_well_formed_mirror` 会先把
    // `validate()` 的每个码摆在面前。

    /// 动态 opcode 的下标（保留块 `0..=15` 之后按声明序，`rdcfmt.py:90-94`）。
    const OP_LIFECYCLE_OBJ: u16 = 16; // `_obj(TurnEndInHand)`：生命周期节目的键
    const OP_ENVELOPE: u16 = 17; // `_obj(MaxProgramSteps, Root)`：节目信封
    const OP_DEAL_DAMAGE: u16 = 18; // `node.dealDamage`
    const OP_GAIN_BLOCK: u16 = 19; // `node.gainBlock`
    const OP_CONST: u16 = 20; // `const`
    const OP_SEL_SOURCE: u16 = 21; // `sel.source`
    const OP_EMPTY_OBJ: u16 = 22; // 0 字段的 `_obj`（= 真实镜像 term 11 的形状）
    const OP_DRAWN_OBJ: u16 = 23; // `_obj(Drawn)`：内核没有的生命周期触发器

    /// `F_*` 字段类别（`rdcfmt.py:176`）。
    const F_STR: u8 = 1;
    const F_INT: u8 = 2;
    const F_BOOL: u8 = 3;
    const F_TERM: u8 = 4;
    const F_TERMLIST: u8 = 5;
    const F_JSON: u8 = 7;

    /// `F_BOOL` 的四个值（`rdcfmt.py:191`）。
    const BOOL_FALSE: u16 = 1;
    const BOOL_TRUE: u16 = 2;

    fn push_u16(out: &mut Vec<u8>, value: u16) {
        out.extend_from_slice(&value.to_le_bytes());
    }

    fn push_u32(out: &mut Vec<u8>, value: u32) {
        out.extend_from_slice(&value.to_le_bytes());
    }

    /// 一条 `OPF` 字段描述：`u16 name_str, u8 kind, u8 flags`（`rdcfmt.py:69-73`）。
    fn push_field(out: &mut Vec<u8>, name: u16, kind: u8) {
        push_u16(out, name);
        out.push(kind);
        out.push(0); // FLAG_WRAP_*
    }

    /// 手搓镜像。卡与节目一览（下面的测试按这张表挑卡）：
    ///
    /// | 定义 id | `Program`（出牌） | `LifecyclePrograms[TurnEndInHand]` | 用途 |
    /// |---|---|---|---|
    /// | `curse.burn` | 缺席 | `dealDamage{2, sel.source}` | 参考的 Burn 本体 |
    /// | `curse.burn_dual` | `dealDamage{7, sel.source}` | `dealDamage{2, sel.source}` | 读错格子（`Program` vs `LifecyclePrograms`）⇒ 7 |
    /// | `curse.burn_block` | 缺席 | `gainBlock{5, sel.source}` | 排空在判负那一刻**停住**（这一条不会落地） |
    /// | `curse.burn_retained` | 缺席 | `dealDamage{2, sel.source}`，`RetainInHandOnTurnEnd = true` | 保留标志与节目无关 |
    /// | `curse.weird` | 缺席 | `_obj{Drawn: …}` | 未知触发器 ⇒ **响亮** |
    /// | `plain.card` | `dealDamage{2, sel.source}` | `{}`（0 字段 `_obj`） | 空生命周期节目 **不跑** |
    fn burn_image() -> Vec<u8> {
        // ---- 字符串池：UTF-8 字节序（`rdcfmt.py:25`），串号 0 是空串 ----
        let mut strings: Vec<&'static str> = vec![
            "_null",
            "_str",
            "_int",
            "_bool",
            "_arr",
            "_json",
            "_wrap_lower",
            "_wrap_upper",
            "_obj",
            "node.dealDamage",
            "node.gainBlock",
            "const",
            "sel.source",
            "TurnEndInHand",
            "MaxProgramSteps",
            "Root",
            "Amount",
            "TargetSelector",
            "Value",
            "Drawn",
            "curse.burn",
            "curse.burn_block",
            "curse.burn_dual",
            "curse.burn_retained",
            "curse.weird",
            "plain.card",
        ];
        strings.sort();
        let sid = |name: &str| -> u16 {
            if name.is_empty() {
                return 0;
            }
            let mut index = 0usize;
            while index < strings.len() {
                if strings[index] == name {
                    return (index + 1) as u16;
                }
                index += 1;
            }
            panic!("手搓镜像里没有这个串：{name}")
        };
        // `string(i)` 取 `pool[STRO[i-1] .. STRO[i]-1)`（`content.rs::string_at`，
        // 与 `reader.py` 同规则）⇒ STRO 有 `n+1` 项，末项是池尾，池里**没有**前导 NUL。
        let mut pool: Vec<u8> = Vec::new();
        let mut stro: Vec<u8> = Vec::new();
        for text in &strings {
            push_u32(&mut stro, pool.len() as u32);
            pool.extend_from_slice(text.as_bytes());
            pool.push(0);
        }
        push_u32(&mut stro, pool.len() as u32); // 末项 = 池尾

        // ---- opcode 表：保留块 0..=15 + 8 个动态 ----
        // (名字, 每个字段的 kind)。保留块的字段名一律串号 0（内核不按名字查它们，
        // 只有 0 号 `_null` 会被 `content.term(0)` 用到，它 0 字段）。
        let reserved: [(&str, &[u8]); 16] = [
            ("_null", &[]),
            ("_str", &[F_STR]),
            ("_int", &[F_INT]),
            ("_bool", &[F_BOOL]),
            ("_arr", &[F_TERMLIST]),
            ("_json", &[F_JSON]),
            ("_wrap_lower", &[F_STR]),
            ("_wrap_upper", &[F_STR]),
            ("", &[]),
            ("", &[]),
            ("", &[]),
            ("", &[]),
            ("", &[]),
            ("", &[]),
            ("", &[]),
            ("", &[]),
        ];
        // (名字, opclass（0 = IR 节点 / 1 = 普通对象）, 字段表 [(名字, kind)])
        type FieldSpec = (&'static str, u8);
        type OpcodeSpec = (&'static str, u8, &'static [FieldSpec]);
        let dynamic: [OpcodeSpec; 8] = [
            ("_obj", 1, &[("TurnEndInHand", F_TERM)]),
            ("_obj", 1, &[("MaxProgramSteps", F_INT), ("Root", F_TERM)]),
            (
                "node.dealDamage",
                0,
                &[("Amount", F_TERM), ("TargetSelector", F_TERM)],
            ),
            (
                "node.gainBlock",
                0,
                &[("Amount", F_TERM), ("TargetSelector", F_TERM)],
            ),
            ("const", 0, &[("Value", F_INT)]),
            ("sel.source", 0, &[]),
            ("_obj", 1, &[]),
            ("_obj", 1, &[("Drawn", F_TERM)]),
        ];
        let mut opd: Vec<u8> = Vec::new();
        let mut opf: Vec<u8> = Vec::new();
        let mut opcode_count = 0usize;
        for (name, kinds) in reserved {
            push_u32(&mut opd, opf.len() as u32); // field_off
            push_u16(&mut opd, sid(name)); // name_str
            opd.push(kinds.len() as u8); // nfields
            opd.push(1); // opclass = generic
            for kind in kinds {
                push_field(&mut opf, 0, *kind);
            }
            opcode_count += 1;
        }
        for (name, opclass, fields) in dynamic {
            push_u32(&mut opd, opf.len() as u32);
            push_u16(&mut opd, sid(name));
            opd.push(fields.len() as u8);
            opd.push(opclass);
            for (field_name, kind) in fields {
                push_field(&mut opf, sid(field_name), *kind);
            }
            opcode_count += 1;
        }
        assert_eq!(opcode_count, 24, "保留块 16 + 动态 8");
        let opf_cells = (opf.len() / 4) as u32;

        // ---- term 表 ----
        // 一条 term = `u16 op` + 按字段类别的槽；记录 4 字节对齐，`TRW[i]` = 记录起点 / 4。
        // 槽序 = opcode 字段表序（`ir.rs::field_spec` 就是这么累加的）。
        let mut terms: Vec<(u16, Vec<u16>)> = Vec::new();
        // t0 = `_null`：排空循环拿 `NodeRef::new(content, 0)` 当 anchor，必须是条合法 term。
        terms.push((0, vec![]));
        let t_source = terms.len() as u16;
        terms.push((OP_SEL_SOURCE, vec![]));
        let t_two = terms.len() as u16;
        terms.push((OP_CONST, vec![2]));
        let t_five = terms.len() as u16;
        terms.push((OP_CONST, vec![5]));
        let t_seven = terms.len() as u16;
        terms.push((OP_CONST, vec![7]));
        let t_damage_two = terms.len() as u16;
        terms.push((OP_DEAL_DAMAGE, vec![t_two, t_source]));
        let t_damage_seven = terms.len() as u16;
        terms.push((OP_DEAL_DAMAGE, vec![t_seven, t_source]));
        let t_block_five = terms.len() as u16;
        terms.push((OP_GAIN_BLOCK, vec![t_five, t_source]));
        // 节目信封：`{MaxProgramSteps, Root}`（真实镜像里还有 `Id` / `MaxNodeDepth`，这里不需要）
        let t_envelope_two = terms.len() as u16;
        terms.push((OP_ENVELOPE, vec![1024, t_damage_two]));
        let t_envelope_seven = terms.len() as u16;
        terms.push((OP_ENVELOPE, vec![1024, t_damage_seven]));
        let t_envelope_block = terms.len() as u16;
        terms.push((OP_ENVELOPE, vec![1024, t_block_five]));
        let t_lifecycle_two = terms.len() as u16;
        terms.push((OP_LIFECYCLE_OBJ, vec![t_envelope_two]));
        let t_lifecycle_block = terms.len() as u16;
        terms.push((OP_LIFECYCLE_OBJ, vec![t_envelope_block]));
        let t_lifecycle_drawn = terms.len() as u16;
        terms.push((OP_DRAWN_OBJ, vec![t_envelope_two]));
        let t_lifecycle_empty = terms.len() as u16;
        terms.push((OP_EMPTY_OBJ, vec![]));

        let mut trm: Vec<u8> = Vec::new();
        let mut trw: Vec<u8> = Vec::new();
        for (op, slots) in &terms {
            assert_eq!(trm.len() % 4, 0, "term 记录必须 4 字节对齐");
            push_u16(&mut trw, (trm.len() / 4) as u16);
            push_u16(&mut trm, *op);
            for slot in slots {
                push_u16(&mut trm, *slot);
            }
            while !trm.len().is_multiple_of(4) {
                trm.push(0);
            }
        }

        // ---- CARD 行（15 格，stride 32；`rdcfmt.py:229-237` / `content.rs:1321-1358`）----
        let card = |id: u16, program: u16, lifecycle: u16, retain: u16| -> [u16; 15] {
            [
                id,        // Id
                program,   // Program（出牌节目）
                ABSENT16,  // Tags
                ABSENT16,  // Costs
                lifecycle, // LifecyclePrograms
                ABSENT16,  // PlayCondition
                ABSENT16,  // QueueOnPlay
                retain,    // RetainInHandOnTurnEnd（F_BOOL）
                BOOL_FALSE, // IsAction
                0,         // NameKey
                0,         // DescriptionKey
                0,         // PackageId
                NULL16,    // TurnEndHandDestinationZone（Host 走默认 = DiscardPile）
                NULL16,    // PlayedCardDestinationZone
                NULL16,    // extra
            ]
        };
        let cards: [(&str, [u16; 15]); 6] = [
            (
                "curse.burn",
                card(sid("curse.burn"), ABSENT16, t_lifecycle_two, BOOL_FALSE),
            ),
            (
                "curse.burn_block",
                card(sid("curse.burn_block"), ABSENT16, t_lifecycle_block, BOOL_FALSE),
            ),
            (
                "curse.burn_dual",
                card(sid("curse.burn_dual"), t_envelope_seven, t_lifecycle_two, BOOL_FALSE),
            ),
            (
                "curse.burn_retained",
                card(sid("curse.burn_retained"), ABSENT16, t_lifecycle_two, BOOL_TRUE),
            ),
            (
                "curse.weird",
                card(sid("curse.weird"), ABSENT16, t_lifecycle_drawn, BOOL_FALSE),
            ),
            (
                "plain.card",
                card(sid("plain.card"), t_envelope_two, t_lifecycle_empty, BOOL_FALSE),
            ),
        ];
        let mut card_bytes: Vec<u8> = Vec::new();
        let mut idx: Vec<u8> = Vec::new();
        for (row, (id, cells)) in cards.iter().enumerate() {
            for cell in cells {
                push_u16(&mut card_bytes, *cell);
            }
            card_bytes.extend_from_slice(&[0, 0]); // 15 × 2 = 30 → 32（`row_stride`）
            // IDX 项 8 B：`{u16 str, u8 ekind, u8 flags, u16 index, u16 rsvd}`（`rdcfmt.py:38`）。
            // 表按 id 的字节序**有序**（`content.rs::id_lower_bound` 是二分查找）。
            push_u16(&mut idx, sid(id));
            idx.push(1); // EK_CARD
            idx.push(0);
            push_u16(&mut idx, row as u16);
            push_u16(&mut idx, 0);
        }

        // ---- 目录 + 组装 ----
        const HEADER: usize = 32;
        const DIR_ENTRY: usize = 12;
        const NSEC: usize = 15;
        let dir_end = HEADER + DIR_ENTRY * NSEC;
        let mut blob = vec![0u8; dir_end];
        blob[0..4].copy_from_slice(&MAGIC.to_le_bytes());
        blob[4..6].copy_from_slice(&FORMAT_VERSION.to_le_bytes());
        blob[12..16].copy_from_slice(&(HEADER as u32).to_le_bytes()); // dir_off
        blob[16..18].copy_from_slice(&(NSEC as u16).to_le_bytes());
        blob[18..20].copy_from_slice(&7u16.to_le_bytes()); // SchemaVersion

        let sections: [(usize, Vec<u8>, u32); 10] = [
            (0, pool, strings.len() as u32),                      // STR
            (1, stro, (strings.len() + 1) as u32),               // STRO
            (2, opd, opcode_count as u32),                        // OPD
            (3, opf, opf_cells),                                  // OPF
            (4, trm, terms.len() as u32),                         // TRM
            (5, trw, terms.len() as u32),                         // TRW
            (6, Vec::new(), 0),                                   // AUX（没有列表）
            (7, card_bytes, cards.len() as u32),                  // CARD
            (13, idx, cards.len() as u32),                        // IDX
            (14, Vec::new(), 0),                                  // TAGS（真实镜像里也是空段）
        ];
        let mut offset = dir_end;
        for (index, bytes, count) in sections {
            let base = HEADER + DIR_ENTRY * index;
            blob[base..base + 4].copy_from_slice(&(offset as u32).to_le_bytes());
            blob[base + 4..base + 8].copy_from_slice(&(bytes.len() as u32).to_le_bytes());
            blob[base + 8..base + 12].copy_from_slice(&count.to_le_bytes());
            blob.extend_from_slice(&bytes);
            while !blob.len().is_multiple_of(4) {
                blob.push(0);
            }
            offset = blob.len();
        }
        let total = blob.len();
        blob[8..12].copy_from_slice(&(total as u32).to_le_bytes()); // total_size
        blob
    }

    /// 这份手搓镜像自己必须是**自洽的**（`validate()` 的每个码都要绿）。
    ///
    /// 没有这一条，任何"测试红"都会先让人怀疑是镜像写坏了 —— 而有了它，红只有一种可能：
    /// 被测的那段代码。
    #[test]
    fn the_hand_rolled_burn_image_is_a_well_formed_mirror() {
        let blob = burn_image();
        let content = Content::parse(&blob).expect("手搓镜像必须能解析");
        assert_eq!(content.validate(), Ok(()), "手搓镜像必须自洽");
        assert_eq!(content.section_count(), 15);
        assert_eq!(content.opcode_count(), 24);
        assert_eq!(content.term_count(), 15);
        assert_eq!(content.rows(crate::content::Table::Card).count(), 6);
        // 六张卡的解码结果**逐张**（这张表就是上面 `burn_image` 文档里那张表的机器版）：
        // 四张有 `TurnEndInHand` 节目、`plain.card` 是空 `{}`、`curse.weird` 只有一个
        // 内核没有的触发器 ⇒ 响亮。
        for (id, has_program) in [
            ("curse.burn", true),
            ("curse.burn_block", true),
            ("curse.burn_dual", true),
            ("curse.burn_retained", true),
            ("plain.card", false),
        ] {
            assert_eq!(
                card_lifecycle_turn_end_program(&content, id)
                    .unwrap_or_else(|e| panic!("`{id}` 必须解得出来：{e:?}"))
                    .is_some(),
                has_program,
                "`{id}` 的 `TurnEndInHand` 节目是否存在"
            );
        }
        // `LifecycleProgram` 没有 `PartialEq/Debug`（`NodeRef` 的身份是 term id，`match` 更诚实）。
        match card_lifecycle_turn_end_program(&content, "curse.weird") {
            Err(HostError::Unsupported("CardLifecycleTrigger")) => {}
            other => panic!(
                "`curse.weird` 只有 `Drawn`（内核没有的触发器）⇒ 必须响亮，实际 {:?}",
                other.map(|p| p.map(|p| p.root.id()))
            ),
        }
        // `curse.burn_dual` 的生命周期节目是 `dealDamage{2}`，而它的**出牌**节目是
        // `dealDamage{7}` —— 两格的 term 必须不同，否则"读错格子"那条测试就没有区分力。
        let lifecycle = card_lifecycle_turn_end_program(&content, "curse.burn_dual")
            .unwrap()
            .expect("有节目");
        let card_program = crate::ir::Ir::new(&content)
            .card_program_root(2)
            .expect("出牌节目");
        assert_ne!(
            lifecycle.root.id(),
            card_program.id(),
            "两格必须指向不同的 term"
        );
    }

    // ---------------------------------------------------------------- 错误面

    #[test]
    fn every_host_error_is_distinguishable() {
        // 这个项目里"安静地少做一半事"是最坏的失败模式，所以"内核还没做到"
        // （[`HostError::Unsupported`]）与"内容配错了"（[`HostError::Content`]）必须是两个变体。
        let all = [
            HostError::Exec(ExecError::UnsupportedNode),
            HostError::Bind(BindError::Polarity),
            HostError::Capacity(CapacityError::MissingCombatant),
            HostError::Unsupported("CardLifecycleTrigger"),
            HostError::Content("TriggerEvent"),
            HostError::TooManyTriggers { needed: 9, have: 8 },
        ];
        for (i, a) in all.iter().enumerate() {
            for (j, b) in all.iter().enumerate() {
                assert_eq!(i == j, a == b, "{a:?} 与 {b:?} 必须可分");
            }
        }
        // 两个 `Unsupported`/`Content` 的**载荷**也必须区分（同样的原因，不同的名字）。
        assert_ne!(
            HostError::Unsupported("a"),
            HostError::Unsupported("b"),
            "载荷就是原因，不能塌成一个"
        );
        assert_ne!(HostError::Content("a"), HostError::Content("b"));
    }

    #[test]
    fn the_bridge_maps_classes_instead_of_borrowing_a_wrong_variant() {
        // `TurnError::Host(HostFailure)` 是 2026-10-17 的裁决：宿主失败**不再**借用
        // `Capacity(Full(Statuses))`（那个变体的字面意思是"容器满了"，会把人送到完全错的
        // 方向）。这条测试钉住**每一档**的落点 —— 它不是"编译过了就算"，而是逐个类别过。
        //
        // 分档依据只有一条：**排查方向**。所以 `Unsupported`（我们去补）与 `Content`
        // （内容去改）绝不能合并，而 `Exec` 里的两个"内核缺能力"变体必须挑出来。
        let expected = [
            // 容器满：唯一无损的一档。
            (
                HostError::Capacity(CapacityError::MissingCombatant),
                TurnError::Capacity(CapacityError::MissingCombatant),
            ),
            (
                HostError::Capacity(CapacityError::Full(crate::state::Container::Statuses)),
                TurnError::Capacity(CapacityError::Full(crate::state::Container::Statuses)),
            ),
            // 内核缺能力。
            (
                HostError::Unsupported("CardLifecycleTrigger"),
                TurnError::Host(HostFailure::Unsupported),
            ),
            (
                HostError::TooManyTriggers { needed: 9, have: 8 },
                TurnError::Host(HostFailure::Unsupported),
            ),
            (
                HostError::Exec(ExecError::UnsupportedNode),
                TurnError::Host(HostFailure::Unsupported),
            ),
            (
                HostError::Exec(ExecError::Expr(ExprError::UnsupportedKind)),
                TurnError::Host(HostFailure::Unsupported),
            ),
            // 内容配错了。
            (
                HostError::Content("TriggerEvent"),
                TurnError::Host(HostFailure::Content),
            ),
            (
                HostError::Bind(BindError::Missing("STAT row")),
                TurnError::Host(HostFailure::Content),
            ),
            // 效果层出错（游戏规则内的 fault）。
            (
                HostError::Exec(ExecError::Modifier),
                TurnError::Host(HostFailure::Effect),
            ),
            (
                HostError::Exec(ExecError::Ir(IrError::NotAnObject(0))),
                TurnError::Host(HostFailure::Effect),
            ),
        ];
        for (host_error, turn_error) in expected {
            assert_eq!(bridge(host_error), turn_error, "{host_error:?}");
        }
        // 三个类别互不相同（否则"排查方向相反"这句就是空话）。
        assert_ne!(
            TurnError::Host(HostFailure::Unsupported),
            TurnError::Host(HostFailure::Content)
        );
        assert_ne!(
            TurnError::Host(HostFailure::Content),
            TurnError::Host(HostFailure::Effect)
        );
        // 而且宿主失败**不许**长得和"容器满了"一样 —— 那正是这次裁决要消灭的东西。
        assert_ne!(
            bridge(HostError::Content("x")),
            TurnError::Capacity(CapacityError::Full(crate::state::Container::Statuses))
        );
    }

    #[test]
    fn the_two_error_channels_agree_on_class_and_detail() {
        // 走**冻结的** trait 入口（不是 `try_*`）：这才是"只读 `TurnError` 的调用方"的经历。
        // 它必须同时得到 **类别**（`TurnError::Host(Unsupported)`）与**细节**
        // （`last_failure()` 里的 `Exec(Expr(UnsupportedKind))`）。
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        let mut host = Host::new(&content);
        // `queue_advances` 的 TurnStarted 触发器用的是 `cardsPlayedLastTurn`，表达式层没实现。
        give(&mut state, "hero", status("st_qa", "queue_advances", 0));
        let err = TurnHost::run_turn_started_triggers(&mut host, &mut state, &cid("hero"))
            .expect_err("必须报错");
        assert_eq!(
            err,
            TurnError::Host(HostFailure::Unsupported),
            "类别：这是'内核还没做到'，不是'内容配错了'"
        );
        assert_eq!(
            host.last_failure(),
            Some(HostError::Exec(ExecError::Expr(ExprError::UnsupportedKind))),
            "细节：原因记在宿主上，不丢"
        );
        // 反向的一档：内容里没有这个状态定义 ⇒ **类别必须不同**。
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_x", "standard.strength", 2));
        assert_eq!(
            TurnHost::run_turn_started_triggers(&mut host, &mut state, &cid("hero")),
            Err(TurnError::Host(HostFailure::Content)),
            "同一个钩子、不同原因 ⇒ 不同类别"
        );
        assert_eq!(
            host.last_failure(),
            Some(HostError::Bind(BindError::Missing("STAT row")))
        );
    }

    // ---------------------------------------------------------------- 解码入口

    #[test]
    fn the_image_has_exactly_the_three_plus_six_triggers_the_spec_claims() {
        // 规格书 §6.1-J 的实测数字：`TurnStarted` 3 / `TurnEnded` 6 / `RoundEnded` 4，
        // 全镜像 25 条、分布在 15 个状态上。一条一组数字，改镜像就会红。
        let blob = core_image();
        let content = parse(&blob);
        let host = Host::new(&content);

        let mut entries = [empty_trigger(&content); MAX_TRIGGERS_PER_STATUS];
        let mut total = 0usize;
        let mut turn_started = 0usize;
        let mut turn_ended = 0usize;
        let mut round_ended = 0usize;
        let mut round_started = 0usize;
        let mut damage_dealt = 0usize;
        let mut not_handled = 0usize;
        let mut with_triggers = 0usize;
        let mut statuses = 0usize;

        for row in content.rows(crate::content::Table::Status) {
            let Some(id) = content.string(row.cell(0).unwrap_or(ABSENT16)) else {
                continue;
            };
            statuses += 1;
            let count = host
                .triggers_of(id, &mut entries)
                .unwrap_or_else(|e| panic!("状态 {id} 的触发器解不出来：{e:?}"));
            if count > 0 {
                with_triggers += 1;
            }
            total += count;
            for entry in entries.get(..count).unwrap_or(&[]) {
                match entry.event {
                    TriggerEvent::TurnStarted => turn_started += 1,
                    TriggerEvent::TurnEnded => turn_ended += 1,
                    TriggerEvent::RoundEnded => round_ended += 1,
                    TriggerEvent::RoundStarted => round_started += 1,
                    TriggerEvent::DamageDealt => damage_dealt += 1,
                    TriggerEvent::NotHandled => not_handled += 1,
                }
                // 信封上的步数预算：实测 25/25 都是 1024。
                assert_eq!(entry.max_steps, 1024, "信封 MaxProgramSteps");
            }
        }
        assert_eq!(statuses, 23);
        assert_eq!(total, 25, "实测 25 条触发器");
        assert_eq!(with_triggers, 15, "分布在 15 个状态上");
        assert_eq!(turn_started, 3, "fatigue / bookworm / queue_advances");
        assert_eq!(turn_ended, 6);
        assert_eq!(round_ended, 4);
        assert_eq!(round_started, 0);
        // `DamageDealt` 那 1 条**不再是缺口**（批次 1 接了钩子，见 `TriggerEvent::DamageDealt`）：
        // `doubt` 的触发器就在这一条上，它正是 `CARD_MULTI` 那 10 格 NOT-COMPARABLE 的根因。
        assert_eq!(damage_dealt, 1, "doubt 的 DamageDealt 触发器");
        // 剩下 11 条是 5 种"参考有、本内核没有钩子接"的事件：`DamageTaken` 1 /
        // `StatusApplied` 3 / `StatusMerged` 3 / `StatusStacksChanged` 2 / `StatusRemoved` 2。
        assert_eq!(not_handled, 11);
    }

    #[test]
    fn all_twenty_five_trigger_event_names_are_known_and_typos_are_not() {
        // `SB:EffectVocabulary.cs:29-71` 的 25 个成员，按声明序。认不出来就会把
        // "内容写了 DamageTaken 触发器"误报成"内容配错了"。
        let known = [
            "TurnStarted",
            "TurnEnded",
            "DamageTaken",
            "DamageDealt",
            "Healed",
            "CardPlayed",
            "Downed",
            "StatusExpired",
            "ResourceGained",
            "CardCostPaid",
            "StatusApplied",
            "StatusRemoved",
            "StatusMerged",
            "StatusStacksChanged",
            "BlockGained",
            "CardsDrawn",
            "CardMovedToZone",
            "CardInstanceCreated",
            "RoundStarted",
            "RoundEnded",
            "StatusApplicationPrevented",
            "StatusApplicationAmplified",
            "ActionResolved",
            "RuleAnnounced",
            "ActionStarting",
        ];
        assert_eq!(known.len(), 25);
        for name in known {
            assert!(
                TriggerEvent::from_wire_name(name).is_some(),
                "{name} 是参考的成员"
            );
        }
        // 4 个能落到钩子上的必须是"自己的"变体，其余 21 个才是 NotHandled。
        assert_eq!(
            TriggerEvent::from_wire_name("TurnStarted"),
            Some(TriggerEvent::TurnStarted)
        );
        assert_eq!(
            TriggerEvent::from_wire_name("DamageTaken"),
            Some(TriggerEvent::NotHandled)
        );
        // 拼错/大小写错必须返回 None（**不许**默认成某个变体）。
        for typo in ["Turnstarted", "turnstarted", "TurnStarted ", "Damage", ""] {
            assert_eq!(TriggerEvent::from_wire_name(typo), None, "{typo:?}");
        }
        assert_eq!(TriggerEvent::NotHandled.wire_name(), "");
    }

    #[test]
    fn the_trigger_sort_is_by_the_whole_rendered_id_not_by_slug() {
        // 参考的次级键是**整条 id 字符串** `{slug}_trigger{index}`
        // （`TriggeredProgramDefinition.cs:91-92` + `SB:StatusDataRebuild.cs:19`）。
        // "按 slug 再按 index"是**错的**，而错法很隐蔽：
        //   "a_trigger0" 与 "a0_trigger0" 的第 2 个字节是 '_'(0x5F) vs '0'(0x30)
        //   ⇒ 整串序里 "a0_trigger0" < "a_trigger0"，而 slug 序会给出相反的答案。
        let mut batch = TriggerBatch::new();
        batch.push("a", 0, 1, 1024).unwrap();
        batch.push("a0", 0, 2, 1024).unwrap();
        batch.push("a", 10, 3, 1024).unwrap();
        batch.push("a", 2, 4, 1024).unwrap();
        batch.sort();
        let order: Vec<u16> = (0..batch.len)
            .map(|i| batch.root.get(i).copied().unwrap_or(0))
            .collect();
        // 整串序：a0_trigger0 < a_trigger0 < a_trigger10 < a_trigger2
        // （"a_trigger1…" < "a_trigger2" 是**字符串**比较，不是数字比较 —— 这就是参考的行为）。
        assert_eq!(order, std::vec![2, 1, 3, 4]);
    }

    #[test]
    fn a_batch_that_overflows_is_refused_instead_of_truncated() {
        // 少跑几条触发器 = 内容静默不发作，比报错糟得多。
        let mut batch = TriggerBatch::new();
        for i in 0..MAX_TRIGGER_ENTRIES {
            batch
                .push("s", u16::try_from(i).unwrap(), 1, 1024)
                .expect("还在容量内");
        }
        assert_eq!(
            batch.push("s", 0, 1, 1024),
            Err(HostError::TooManyTriggers {
                needed: MAX_TRIGGER_ENTRIES + 1,
                have: MAX_TRIGGER_ENTRIES,
            })
        );
    }

    // ---------------------------------------------------------------- 钩子 1：pending

    #[test]
    fn pending_statuses_activate_one_turn_at_a_time() {
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give_pending(&mut state, "hero", status("st_p", "strength", 2), 3);

        for expected in [2, 1, 0] {
            host.try_activate_pending_statuses(&mut state, &cid("hero"))
                .unwrap();
            assert_eq!(pending_of(&state, "hero", "strength"), expected);
            // 转正**不重置**层数（`StatusEffects.cs:420-445` 全文没有 `SetStacks`）。
            assert_eq!(stacks_of(&state, "hero", "strength"), 2);
        }

        // 无事可做的那一面：`pending_turns == 0` 的实例**不会再被减**（不会变成 −1；
        // 参考的 `SetPendingTurns(-1)` 对负数会抛 `ArgumentOutOfRangeException`，
        // `StatusInstance.cs:99-105`）。
        host.try_activate_pending_statuses(&mut state, &cid("hero"))
            .unwrap();
        assert_eq!(pending_of(&state, "hero", "strength"), 0);
        // 不存在的人也照参考静默返回（`:417-418`）。
        host.try_activate_pending_statuses(&mut state, &cid("nobody"))
            .unwrap();
    }

    #[test]
    fn a_pending_poison_does_not_tick_until_it_activates() {
        // 参考的 DoT 遍历 `combatant.Statuses`（active-only，`StatusEffects.cs:460`），
        // 待转正的实例**不在**里面。这条用一个 DoT 状态把"active-only"钉成可观察的行为：
        // pending 2 ⇒ 第一个回合开始只减到 1（不跳），第二个回合开始才转正并跳 4 点。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give_pending(&mut state, "hero", status("st_dot", "poison", 4), 2);

        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(pending_of(&state, "hero", "poison"), 1);
        assert_eq!(health(&state, "hero"), 70, "还没转正 ⇒ 不跳");

        turn::end_current_turn_and_start_next(&mut state, &config(), &mut host).unwrap();
        assert_eq!(pending_of(&state, "hero", "poison"), 0, "转正");
        // ⚠️ 等待期间**不衰减**：`poison` 的 turn-end 触发器只在它 active 时才被收集到
        // （Bearer 过滤器读 `Statuses`，待转正的不在里面）⇒ 层数还是 4，
        // 而上一个回合末的触发器那一次也没跑（它当时还没转正）。
        assert_eq!(stacks_of(&state, "hero", "poison"), 4, "等待期间不衰减");
        // 转正是 turn-start 第 3 步、DoT 是最后一步 ⇒ 本回合它跳了，金额是 4。
        assert_eq!(health(&state, "hero"), 66, "4 点 DoT");
    }

    // ---------------------------------------------------------------- 钩子 2/8：触发器

    #[test]
    fn fatigue_spends_one_energy_after_the_refill_and_removes_itself() {
        // 验收向量 V6 + §0.1 的顺序：补能量（第 2 步）**先**、turn-start 触发器（第 4 步）**后**。
        // ⇒ 能量池是 3 而不是 2；而疲惫（fatigue）的节目是
        // `sequence[loseResource(standard.energy, 1), modifyStatusStacks(fatigue, -1)]`
        // （实测 dump）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut tired = solo();
        give_energy(&mut tired, "hero", 1); // 上回合剩 1 点，补到 3
        give(&mut tired, "hero", status("st_f", "fatigue", 1));
        turn::start_current_turn(&mut tired, &config(), &mut host).unwrap();
        assert_eq!(energy_of(&tired, "hero"), 2, "补到 3 再花 1");
        assert_eq!(instances_of(&tired, "hero", "fatigue"), 0, "-1 到 0 ⇒ 删实例");

        // 无事可做的那一面：没有 fatigue ⇒ 能量停在补满的 3。
        let mut fresh = solo();
        give_energy(&mut fresh, "hero", 1);
        let mut host = Host::new(&content);
        turn::start_current_turn(&mut fresh, &config(), &mut host).unwrap();
        assert_eq!(energy_of(&fresh, "hero"), 3);
        assert_eq!(
            energy_of(&tired, "hero") + 1,
            energy_of(&fresh, "hero"),
            "两条路的结果必须不同，否则上面那条证明不了触发器跑过"
        );
    }

    #[test]
    fn bookworm_swaps_paperwork_for_itself_and_the_dot_reads_the_post_trigger_stacks() {
        // `bookworm` 的 TurnStarted 节目（实测 dump）是一个 `conditional`：
        //   Condition: paperwork >= bookworm
        //   Then : sequence[paperwork -= bookworm, bookworm -= bookworm]
        //   Else : sequence[bookworm -= paperwork, paperwork -= paperwork]
        // 取 Then 那一支（paperwork 3 >= bookworm 2）：
        //   paperwork 3 - 2 = 1；bookworm 2 - 2 = 0（⇒ 删实例）。
        // 然后 DoT 跳 1 点 —— 这个 1 是**触发器之后**的层数，正是参考
        // `StatusEffects.cs:476-479` 那段注释说的事（"tick reads the stacks when it RESOLVES"）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_b", "bookworm", 2));
        give(&mut state, "hero", status("st_pw", "paperwork", 3));

        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(stacks_of(&state, "hero", "bookworm"), 0);
        assert_eq!(instances_of(&state, "hero", "bookworm"), 0, "减到 0 ⇒ 删实例");
        assert_eq!(stacks_of(&state, "hero", "paperwork"), 1);
        assert_eq!(health(&state, "hero"), 69, "DoT 跳触发器之后的 1 点");
    }

    #[test]
    fn queue_advances_is_a_kernel_gap_not_a_content_error() {
        // `queue_advances` 的 TurnStarted 触发器是 `conditional`，它的条件是
        // `compare(cardsPlayedLastTurn(...) >= 3)` —— 而 `cardsPlayedLastTurn` 是
        // `expr.rs` **今天不实现**的 int 表达式（模块头第 35-44 行点过名）。
        //
        // ⚠️ **规格书 §2.2 在这里说错了一句**：它写"用到的节点种类全在 `exec.rs` 已交付的
        // 15 种里 ⇒ 执行层够用"。节点种类确实够（`conditional` + `setCombatantCounter`），
        // 但**表达式**种类不够。这条测试把那个反例钉住。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_qa", "queue_advances", 0));
        let err = host
            .try_run_turn_started_triggers(&mut state, &cid("hero"))
            .expect_err("必须响亮失败");
        assert_eq!(
            err,
            HostError::Exec(ExecError::Expr(ExprError::UnsupportedKind)),
            "这是'内核还没做到'（UnsupportedKind），不是'内容配错了'（Ir/Missing）"
        );
    }

    #[test]
    fn turn_end_triggers_run_and_poison_decays_one_stack_per_turn() {
        // 验收向量 V3：`poison` 的层数衰减**靠 turn-end 触发器**，不靠 duration 轴
        // （镜像 23/23 状态 `UsesDuration = false`）。空实现会让毒**永久叠加**。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_poi", "poison", 3));

        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(health(&state, "hero"), 67, "V1：回合开始先跳 3 点");

        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(stacks_of(&state, "hero", "poison"), 2, "回合结束 3 → 2");
        assert_eq!(instances_of(&state, "hero", "poison"), 1, "还活着，实例不删");

        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(health(&state, "hero"), 65, "第二跳 2 点");
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(stacks_of(&state, "hero", "poison"), 1, "第二回合 2 → 1");

        // 无事可做的那一面：一个**没有** turn-end 触发器的状态（`strength`）不衰减。
        let mut other = solo();
        give(&mut other, "hero", status("st_str", "strength", 3));
        let mut host = Host::new(&content);
        turn::start_current_turn(&mut other, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut other, &config(), &mut host).unwrap();
        assert_eq!(stacks_of(&other, "hero", "strength"), 3);
    }

    // ---------------------------------------------------------------------------------------
    // 排空循环（批次 1）：`ResolvePendingQueues`，`CombatEventHandling.cs:81-115`
    // ---------------------------------------------------------------------------------------
    //
    // 这一组是**变异测试的靶子**：三条最容易被"顺手简化"的规则，每条都有单独一条测试。
    //   M1 把 `while … && Result == Ongoing` 退化成"入口查一次" ⇒ `the_loop_condition…` 红
    //   M2 把续延改成"入队即执行" ⇒ `a_continuation_waits…` 红
    //   M3 把队列满了/超限改成"丢掉"或"跳过" ⇒ `a_full_queue…`（state.rs）
    //      与 `the_limits_are_loud…` 各红一面

    #[test]
    fn the_loop_condition_is_re_read_every_cycle_not_checked_once_at_the_door() {
        // 参考的循环条件是 `while (hasPending…) && Result == Ongoing`（`:97`）——
        // `Result` **每一圈都重读**。写成"入口查一次"的后果不是崩，是"战斗结束之后
        // 排队的事件照样分发"：多跑一个触发器节目 ⇒ `exec_num` 多 1，指纹静默发散。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);

        // 半边 1：战斗已结束 ⇒ 队列里那条事件**不许**落地，但也**不许**被丢掉。
        let mut dead = arena();
        give(&mut dead, "hero", status("st_fat", "fatigue", 0)); // TurnStarted 触发器（镜像 3 条之一）
        dead.enqueue_event_at_root(CombatEvent::TurnStarted {
            combatant: cid("hero"),
        })
        .unwrap();
        dead.result = CombatResult::Victory;
        let exec_before = dead.next_program_execution_id;
        host.try_resolve_pending_queues(&mut dead).unwrap();
        assert_eq!(
            dead.next_program_execution_id, exec_before,
            "战斗结束之后排队的事件不许再分发（`Result == Ongoing` 是**循环**条件）"
        );
        assert_eq!(
            dead.pending_event_count(),
            1,
            "它们只是没人捡，不是被丢掉 —— 丢掉会让'少跑一个触发器'变成不可观测"
        );

        // 半边 2（成对）：同一条事件，`Ongoing` 时它**会**跑。少了这一半，
        // 上面那条在"分发整个坏了"时也照样绿。
        let mut live = arena();
        give(&mut live, "hero", status("st_fat", "fatigue", 0));
        live.enqueue_event_at_root(CombatEvent::TurnStarted {
            combatant: cid("hero"),
        })
        .unwrap();
        let exec_before = live.next_program_execution_id;
        host.try_resolve_pending_queues(&mut live).unwrap();
        assert_eq!(
            live.next_program_execution_id,
            exec_before + 1,
            "event 分发 ⇒ 那个触发器节目发了一次执行号"
        );
        assert_eq!(live.pending_event_count(), 0, "排空之后队列干净");
    }

    #[test]
    fn a_continuation_waits_for_the_drain_and_runs_at_the_top_level() {
        // 参考：`Queue<Action<CombatState>>`（`CombatState.cs:10`）里的东西**入队时不跑**，
        // 排到相位 3（`:107-111`）才跑，而且那时 `CurrentEffectChain` 为 null
        // ⇒ 它内部那次 `EnqueueEvent(ActionResolved)` 建一条根链（`:442-452`）。
        //
        // 三件事分开断言，任何一件坏了都会红：
        //   ① 入队**不执行**（`chain_num` 不动）
        //   ② 排空之后它跑了（`chain_num` +1）
        //   ③ 它跑在**链作用域之外**（所以 +1 而不是 +0）
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();

        let before = state.next_effect_chain_number;
        state
            .enqueue_continuation(Continuation::CloseAction { actor: cid("hero") })
            .unwrap();
        assert_eq!(
            state.next_effect_chain_number, before,
            "① 入队不许执行它（参考入队的是闭包，不是调用）"
        );
        assert_eq!(state.pending_continuation_count(), 1);

        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(
            state.next_effect_chain_number,
            before + 1,
            "② ③ 排空之后跑了，且跑在顶层（链作用域为空 ⇒ 自己发一个号）"
        );
        assert_eq!(state.pending_continuation_count(), 0);

        // ③ 的**反例**（这条才让 ③ 有内容）：把同一条续延放进链作用域里跑，
        // 它落在 `current_chain` 里 ⇒ **不发号**。如果实现里"无条件发号"，这一半会红。
        let mut scoped = solo();
        let chain = scoped.new_root_chain_in_arena().unwrap();
        let before = scoped.next_effect_chain_number;
        scoped
            .with_chain(chain, |state| {
                let mut ctx_host = Host::new(&content);
                state
                    .enqueue_continuation(Continuation::CloseAction { actor: cid("hero") })
                    .unwrap();
                ctx_host.try_resolve_pending_queues(state).unwrap();
            });
        assert_eq!(
            scoped.next_effect_chain_number, before,
            "链作用域里跑 ⇒ 参考的 `CurrentEffectChain ?? …` 不会新建根链"
        );
    }

    #[test]
    fn the_effect_phase_resolves_the_request_it_dequeues() {
        // 批次 2：效果队列**有解析器**了。相位 1 出队一条 `GainBlock` 就必须真的加格挡
        // —— "出队了但什么都没做"是这一层最坏的形态（没有观察者）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        let chain = state.new_root_chain_in_arena().unwrap();
        state
            .with_chain(chain, |state| {
                state
                    .enqueue_effect(EffectRequest::GainBlock {
                        target: Some(cid("hero")),
                        amount: 3,
                    })
                    .unwrap();
            });
        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(
            state.pending_effect_count(),
            0,
            "解析过的条目离开队列（不是留着下次再解析一次）"
        );
        assert_eq!(
            block_of(&state, "hero"),
            3,
            "请求真的落地了"
        );
    }

    #[test]
    fn the_effect_phase_runs_before_the_event_phase() {
        // `CombatEventHandling.cs:104-105`：**先抽干效果队列，再抽干事件队列**。
        // 批次 1 这条次序没有可观察后果（效果队列没有生产者）；批次 2 有了。
        //
        // 场面（两个方向都能判）：
        // * `hero` 身上**没有** `doubt`；
        // * 效果队列里一条 `ApplyStatus(doubt, hero, 1)`；
        // * 事件队列里一条 `DamageDealt{ source: hero }` —— `doubt` 的触发器认的是
        //   **出手方戴不戴**（`DamageDealtSourceHasStatusTriggerFilter`）。
        //
        // * 正确次序（效果 → 事件）：状态先落地 ⇒ 事件分发时 hero 戴着 doubt ⇒ 触发器跑
        //   ⇒ `exec_num +1`，而且它那一笔 `-1` 在**下一轮**相位 1 落地 ⇒ doubt 回到 0；
        // * 掉序（事件 → 效果）：事件先分发，hero 还没戴 doubt ⇒ 触发器**收集不到**
        //   ⇒ `exec_num +0`，效果随后落地 ⇒ doubt 停在 1。
        //
        // ⇒ 两个数（`exec_num` 与 doubt 层数）都分开，任一方向坏了都会红。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();

        let chain = state.new_root_chain_in_arena().unwrap();
        state
            .with_chain(chain, |state| {
                state
                    .enqueue_effect(EffectRequest::ApplyStatus {
                        target: Some(cid("hero")),
                        definition: StatusDefinitionId::new("doubt").unwrap(),
                        stacks: 1,
                        duration: 0,
                        charges: 0,
                        source: None,
                        source_card: None,
                    })
                    .unwrap();
                state
                    .enqueue_event(CombatEvent::DamageDealt {
                        target: cid("enemy_a"),
                        health_damage: 1,
                        blocked_damage: 0,
                        requested: 1,
                        source: Some(cid("hero")),
                    })
                    .unwrap();
            });

        // 第二条事件：它的触发器门禁读的是**同一条** doubt 的层数，所以它把
        // "触发器入队的效果是不是当场落地了"也一起钉住（见下面的 README 段落）。
        state
            .enqueue_event(CombatEvent::DamageDealt {
                target: cid("enemy_a"),
                health_damage: 1,
                blocked_damage: 0,
                requested: 1,
                source: Some(cid("hero")),
            })
            .unwrap();

        let exec_before = state.next_program_execution_id;
        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(
            state.next_program_execution_id,
            exec_before + 2,
            "两条事件分发时 doubt 都必须还在身上：相位 1 的落地排在相位 2 **之后**"
        );
        assert_eq!(
            stacks_of(&state, "hero", "doubt"),
            0,
            "两笔 -1 都在**下一轮**相位 1 落地：1 → 0（第二笔是 no-op）"
        );
    }

    #[test]
    fn a_stale_node_level_continuation_is_dropped_and_a_live_one_runs() {
        // 批次 2 起 `ProgramResume` 真的会被恢复（节点级续延调度）。这里的两个方向：
        //
        // 1. **陈旧**续延（帧已经不在）⇒ 静默丢弃。这是参考的明确规定：
        //    `EffectProgramExecution.cs:51-54`"A stale completion can arrive after the frame
        //    was cancelled … ignore it"。
        // 2. **活着的**帧 ⇒ 走 `exec::resume` 并推进节目（那条路在 `exec.rs` 侧有专门测试，
        //    这里只钉"排空循环认识它、不报 Unsupported"）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        state
            .enqueue_continuation(Continuation::ProgramResume {
                frame: ProgramExecutionSlot::from_index(1),
                node: 0,
            })
            .unwrap();
        assert_eq!(
            host.try_resolve_pending_queues(&mut state),
            Ok(()),
            "帧不在 ⇒ 陈旧续延，丢弃而不是报错"
        );
        assert_eq!(state.pending_continuation_count(), 0);
    }

    #[test]
    fn the_limits_are_loud_and_parameterised_so_they_can_be_reached() {
        // 参考的三个上限（`CombatExecutionLimits.cs:12-14`）到顶都是**抛**，不是"跑一点试试"。
        // 它们做成参数（`QueueLimits`）就是为了让这条测试能把它们当场撞出来 ——
        // 用真内容撞 1024 轮要跑很久，而且"跑很久"本身不是断言。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);

        // 轮数上限：队列非空 + `max_cycles = 0` ⇒ 一条都不许跑。
        let mut state = solo();
        state
            .enqueue_event(CombatEvent::RoundStarted { round: 2 })
            .unwrap();
        let limits = QueueLimits {
            max_cycles: 0,
            ..QueueLimits::DEFAULT
        };
        assert_eq!(
            host.resolve_pending_queues_with(&mut state, limits),
            Err(HostError::QueueCycleLimit { cycles: 0, limit: 0 })
        );

        // 事件相位上限：`max_events_per_cycle = 0` ⇒ 同样是**报错**，不是"这一相位跳过"。
        let mut state = solo();
        state
            .enqueue_event(CombatEvent::RoundStarted { round: 2 })
            .unwrap();
        let limits = QueueLimits {
            max_events_per_cycle: 0,
            ..QueueLimits::DEFAULT
        };
        assert_eq!(
            host.resolve_pending_queues_with(&mut state, limits),
            Err(HostError::QueuePhaseLimit {
                phase: "event",
                resolved: 0,
                limit: 0,
            })
        );

        // 效果相位上限同理（它先跑，所以报的是 effect）。
        let mut state = solo();
        state
            .enqueue_effect(EffectRequest::GainBlock {
                target: None,
                amount: 1,
            })
            .unwrap();
        let limits = QueueLimits {
            max_effects_per_cycle: 0,
            ..QueueLimits::DEFAULT
        };
        assert_eq!(
            host.resolve_pending_queues_with(&mut state, limits),
            Err(HostError::QueuePhaseLimit {
                phase: "effect",
                resolved: 0,
                limit: 0,
            })
        );

        // 成对：默认上限下同样的队列**不报错**（否则上面三条只是证明"这个函数总报错"）。
        let mut state = solo();
        state
            .enqueue_event(CombatEvent::RoundStarted { round: 2 })
            .unwrap();
        assert_eq!(
            host.resolve_pending_queues_with(&mut state, QueueLimits::DEFAULT),
            Ok(())
        );
    }

    // ---------------------------------------------------------------------------------------
    // `DamageDealt` + 触发器：批次 1 真正换来的东西（`CARD_MULTI` 那 10 格的根因）
    // ---------------------------------------------------------------------------------------

    /// 用 `exec` 的伤害管线打一下（这是 `battle.rs` 之外唯一能造出 `DamageDealt` 的入口）。
    fn strike(state: &mut CombatState, content: &Content<'_>, source: &str, target: &str, amount: i32) {
        let mut ctx = crate::exec::ExecContext::new(
            state,
            Some(cid(source)),
            None,
            None,
            64,
        )
        .with_content(content);
        crate::exec::resolve_damage(&mut ctx, &cid(target), amount, false).unwrap();
    }

    #[test]
    fn damage_dealt_runs_the_bearers_trigger_and_takes_one_doubt_stack_from_the_source() {
        // `doubt` 的触发器（`bureaucrats.roguedeck.json`）：`DamageDealt` →
        // `modifyStatusStacks(doubt, -1)` 到 `sel.source`。Bearer 是**出手方**
        // （`SB:StatusDataRebuild.cs:53-55` 的 `DamageDealtSourceHasStatusTriggerFilter`）。
        //
        // 这条测试钉的是整条链路：伤害落地 ⇒ `exec` 入队 `DamageDealt`（`DamageEffects.cs:186-194`）
        // ⇒ 排空 ⇒ 收集（Bearer = 出手方）⇒ 跑一个节目（`exec_num` +1）⇒ 出手方少一层 doubt。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_dbt", "doubt", 2));

        strike(&mut state, &content, "enemy_a", "hero", 5);
        assert_eq!(
            state.pending_event_count(),
            1,
            "伤害落地就该入队一条 `DamageDealt`（参考在 `:186` 入队）"
        );

        let exec_before = state.next_program_execution_id;
        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(
            state.next_program_execution_id,
            exec_before + 1,
            "触发器节目发了一次执行号（`EffectProgramExecution.cs:27`）"
        );
        assert_eq!(
            stacks_of(&state, "enemy_a", "doubt"),
            1,
            "出手方（戴着 doubt 的那个）少一层"
        );
        assert_eq!(
            stacks_of(&state, "hero", "doubt"),
            0,
            "承受者身上没被写（`sel.source` 是出手方，不是 `eventTarget`）"
        );
    }

    #[test]
    fn the_damage_dealt_bearer_filter_reads_the_source_not_the_target() {
        // 成对的两个反例。少了它们，上面那条在"Bearer 写成承受者/写成任何人"时**照样绿**
        // —— 而 `doubt` 的被动（伤害 ×75%）恰好就是"看出手方"的，两者混了会静默算错。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);

        // 反例 1：doubt 戴在**承受者**（hero）身上，出手方（enemy_a）没戴 ⇒ 不触发。
        let mut target_side = arena();
        give(&mut target_side, "hero", status("st_dbt", "doubt", 2));
        strike(&mut target_side, &content, "enemy_a", "hero", 5);
        let exec_before = target_side.next_program_execution_id;
        host.try_resolve_pending_queues(&mut target_side).unwrap();
        assert_eq!(
            target_side.next_program_execution_id, exec_before,
            "戴在承受者身上不该触发（Bearer = 出手方）"
        );
        assert_eq!(stacks_of(&target_side, "hero", "doubt"), 2, "一层都不该少");

        // 反例 2：doubt 戴在**旁观者**（enemy_b）身上 ⇒ 也不触发。
        let mut bystander = arena();
        give(&mut bystander, "enemy_b", status("st_dbt", "doubt", 2));
        strike(&mut bystander, &content, "enemy_a", "hero", 5);
        let exec_before = bystander.next_program_execution_id;
        host.try_resolve_pending_queues(&mut bystander).unwrap();
        assert_eq!(
            bystander.next_program_execution_id, exec_before,
            "旁观者戴着不该触发（Bearer 是出手方，不是'场上有人戴'）"
        );
        assert_eq!(stacks_of(&bystander, "enemy_b", "doubt"), 2);

        // 反例 3：**没有出手方**的伤害（`source: None`）⇒ 也不触发。
        // 参考的过滤器第一句就是 `SourceCombatant is not null`。
        let mut sourceless = arena();
        give(&mut sourceless, "hero", status("st_dbt", "doubt", 2));
        {
            let mut ctx =
                crate::exec::ExecContext::new(&mut sourceless, None, None, None, 64)
                    .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("hero"), 5, false).unwrap();
        }
        let exec_before = sourceless.next_program_execution_id;
        host.try_resolve_pending_queues(&mut sourceless).unwrap();
        assert_eq!(
            sourceless.next_program_execution_id, exec_before,
            "没有出手方的伤害不该触发任何 `DamageDealt` 触发器"
        );
    }

    #[test]
    fn a_turn_ended_trigger_can_delete_the_instance_and_that_is_not_the_same_as_zero_stacks() {        // V4：`poison 1` ⇒ 回合末 0 ⇒ **实例被删**（`modifyStatusStacks` 的 0 层删实例规则，
        // `StatusEffects.cs:830-838`）。"留一条 0 层实例"不是等价物：它会进 `s=` 行、
        // 进 `statuses()`、并占一格 24 条容量（`exec.rs:1066-1079`）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_poi", "poison", 1));
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(instances_of(&state, "hero", "poison"), 0);
        assert_eq!(
            state.combatant(&cid("hero")).unwrap().statuses().len(),
            0,
            "整张状态表都空了（不是一条 0 层）"
        );
    }

    #[test]
    fn sustained_round_ended_trigger_runs_without_a_bearer_gate() {
        // `SB:StatusDataRebuild.cs:121-124`：**RoundEnded 既没有 `gatingStatus` 也没有过滤器**
        // （【验证】我读过那四行；规格书 §6.2 第 9 条把它列为"未验证"，这里是它的答案）。
        // ⇒ 轮末它**无条件**跑，限定对象只能靠节目自己的 `TargetSelector`。
        // `sustained` 的选择器是 `sel.withStatus(allCombatants, sustained)` ——
        // 所以"在身"时计数器被清 0，"不在身"时选择器解出空集、什么都不写。
        let blob = core_image();
        let content = parse(&blob);
        let mut carried = solo();
        give(&mut carried, "hero", status("st_sus", "sustained", 0));
        give_counter(&mut carried, "hero", "sustained_this_round", 5);
        let mut host = Host::new(&content);
        turn::start_current_turn(&mut carried, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut carried, &config(), &mut host).unwrap();
        assert_eq!(counter_of(&carried, "hero", "sustained_this_round"), 0);

        // 无事可做的那一面：同一段流程，只是英雄不带 `sustained` ⇒ 计数器原样。
        let mut without = solo();
        give_counter(&mut without, "hero", "sustained_this_round", 5);
        let mut host = Host::new(&content);
        turn::start_current_turn(&mut without, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut without, &config(), &mut host).unwrap();
        assert_eq!(counter_of(&without, "hero", "sustained_this_round"), 5);
    }

    #[test]
    fn round_started_has_no_triggers_in_this_image_so_the_hook_only_advances_the_chain_number() {
        // 实测 0 条 `RoundStarted` 触发器。钩子仍然实现（与 RoundEnded 共用同一段代码）。
        //
        // ⚠️ **2026-10-19（事件队列批次 1）改了这条断言，理由要写清**：以前它钉的是
        // "调用它一个字节都不该改"。那句话在**旧形状**下成立，但成立的方式是错的 ——
        // 链号当时在 `TurnHost` 的适配器里发（`let _round_started_chain = …`），
        // 所以直接调 `try_` 这个入口**看不到**那一笔。现在发号搬进了
        // `try_on_round_started`（参考的 `EnqueueEvent`，`CombatTurnProcessor.cs:199-200`
        // 的 `?? CreateRootEffectChain()`），于是入口处就能看见它。
        //
        // ⇒ 新断言**更强**：这场钩子只准动 `chain_num`（+1），`exec_num` 一个都不许动
        // （动了 = 有触发器跑了，而这场内容里一条都没有）。成对写：+1 与 +0 各一半，
        // 单看任何一半都可能是"恰好没变"。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_sus", "sustained", 0));
        let chain_before = state.next_effect_chain_number;
        let exec_before = state.next_program_execution_id;
        let before = strip_counters(&state_text(&state));

        host.try_on_round_started(&mut state, 2).unwrap();

        assert_eq!(
            state.next_effect_chain_number,
            chain_before + 1,
            "顶层入队一条事件 = 一条根链（CombatState.cs:446）"
        );
        assert_eq!(
            state.next_program_execution_id, exec_before,
            "这条事件在这份镜像上没有触发器 ⇒ 一个节目都不该跑"
        );
        assert_eq!(
            strip_counters(&state_text(&state)),
            before,
            "除那两个计数器以外，钩子不该动任何东西"
        );
    }

    #[test]
    fn a_status_definition_missing_from_the_content_is_loud_at_the_hook() {
        // 战斗员身上挂了一条**内容里没有**的状态定义（例如把这个镜像当成标准包用，
        // 于是出现 `standard.strength`）⇒ 触发器收集必须**响亮失败**，
        // 而不是"这个状态没有触发器"。
        //
        // ⚠️ 这条测试是**变异测试逼出来的**：我原来只有一条直接打 `triggers_of` 的测试，
        // 而把钩子里的"收集失败 ⇒ 静默跳过"改坏之后**全套测试仍然全绿**。
        // 差别在于：只测解码器 = 测了零件，没测"零件坏了钩子会不会喊"。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_x", "standard.strength", 2));

        assert_eq!(
            host.try_run_turn_started_triggers(&mut state, &cid("hero")),
            Err(HostError::Bind(BindError::Missing("STAT row")))
        );
        // 回合结束那一路同形（同一个收集器）。
        let mut host = Host::new(&content);
        assert_eq!(
            host.try_run_turn_ended_triggers(&mut state, &cid("hero")),
            Err(HostError::Bind(BindError::Missing("STAT row")))
        );
    }

    // ---------------------------------------------------------------- 钩子 5：DoT

    #[test]
    fn metallicize_grants_block_at_the_end_of_the_turn() {
        // Wiki: Metallicize N = "gain N Block at the end of each turn". A **host step**, not a
        // modifier and not a trigger (`port-plan.md` §112).
        //
        // The **full** sts image, not `core_image()`: the core image carries no `STAT` rows, so a
        // status handed to `solo()` cannot bind there (`port-plan.md` §113).
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_met", "standard.metallicize", 3));

        let block = |state: &crate::state::CombatState| -> i32 {
            state
                .combatant(&cid("hero"))
                .map_or(0, |c| c.defensive_pools().iter().map(|e| e.pool.current).sum())
        };
        assert_eq!(block(&state), 0, "no block before the turn ends");

        host.try_run_turn_ended_triggers(&mut state, &cid("hero"))
            .expect("turn end");
        assert_eq!(block(&state), 3, "Metallicize 3 pays 3 Block");

        // It stacks per instance value, and pays again next turn end.
        host.try_run_turn_ended_triggers(&mut state, &cid("hero"))
            .expect("turn end again");
        assert_eq!(block(&state), 6, "and again on the next turn end");
    }

    #[test]
    fn poison_ticks_for_its_stacks_and_never_changes_them() {
        // V1：`Amount = Stacks`（`StatusEffects.cs:504`），DoT **不扣层数**
        // （那个 handler 全文没有 `SetStacks`）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_poi", "poison", 3));
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(health(&state, "hero"), 67);
        assert_eq!(stacks_of(&state, "hero", "poison"), 3, "DoT 不扣层数");

        // 无事可做的那一面：没有任何 DoT 状态 ⇒ 一滴血都不掉。
        let mut clean = solo();
        let mut host = Host::new(&content);
        turn::start_current_turn(&mut clean, &config(), &mut host).unwrap();
        assert_eq!(health(&clean, "hero"), 70);
    }

    #[test]
    fn own_dot_is_the_second_status_with_the_tag() {
        // 两个带 `damage_over_time` 的状态：`poison` 与 `paperwork`（实测）。
        // 两条各跳各的层数（按实例序，一条一次伤害）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_poi", "poison", 3));
        give(&mut state, "hero", status("st_pw", "paperwork", 2));
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(health(&state, "hero"), 65, "3 + 2");
    }

    #[test]
    fn dot_respects_block_when_the_block_is_still_there_at_tick_time() {
        // `DamageOverTimeTick` 构造 `DealDamageEffectRequest` 时**不传** `IgnoresBlock`
        // ⇒ 默认 false ⇒ 吃格挡（`DamageEffects.cs:21-24` + `StatusEffects.cs:501-509`）。
        //
        // ⚠️ 这条必须**直接**打钩子，不能走 `start_current_turn`：
        // 回合开始第 7 步清格挡、第 8 步才 DoT（`StandardCombatPackage.cs:134` vs `:139`，
        // 【验证】我读过那两行），所以"回合开始时有 5 点格挡"在**跳毒之前**就被清掉了。
        // 规格书 §7 的验收向量 **V2 在这里写错了**（它说"格挡 −3 → 2"，那是把
        // 第 7 步和第 8 步的顺序搞反了）—— 见报告。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_poi", "poison", 3));
        give_block(&mut state, "hero", 5);
        host.try_damage_over_time(&mut state, &cid("hero")).unwrap();
        assert_eq!(block_of(&state, "hero"), 2, "5 - 3");
        assert_eq!(health(&state, "hero"), 70, "全被格挡吃掉");
    }

    #[test]
    fn the_turn_start_clears_block_before_the_dot_tick() {
        // 上一条的**另一面**，而且这才是回合机里真实发生的事：
        // 两个都是一次性效果，先进队列的先解析（`CombatState.cs:401-407` 的 FIFO），
        // 而清格挡（`StandardCombatPackage.cs:134`）注册在 DoT（`:139`）之前
        // ⇒ 回合开始的 5 点格挡**挡不住**这一跳。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_poi", "poison", 3));
        give_block(&mut state, "hero", 5);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(block_of(&state, "hero"), 0, "第 7 步清空");
        assert_eq!(health(&state, "hero"), 67, "所以毒直接打血");
    }

    #[test]
    fn dot_does_not_take_the_direct_only_modifiers() {
        // ⚠️ **这是本模块最重要的一条**。目标身上同时有 `poison 5` 与 `signature_pending`
        // （镜像里那条 `DamageReceived / ScalePercent 75 / RestrictDamageKind = Direct` 的 spec）。
        //
        // * 正确实现（`DamageKind::Dot`）：75% 那条门不进 ⇒ 5 点。
        // * 错误实现（复用 `Direct` 管线）：5 * 75 / 100 = **3** 点。
        //
        // 两个数字不同，所以这条测试对"复用 Direct"是敏感的（变异测试里验证过会红）。
        let blob = core_image();
        let content = parse(&blob);

        let mut state = solo();
        give(&mut state, "hero", status("st_poi", "poison", 5));
        give(&mut state, "hero", status("st_sig", "signature_pending", 0));
        let mut host = Host::new(&content);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(
            health(&state, "hero"),
            65,
            "DoT 5 点整；*75 会给出 67（= 3 点）"
        );

        // 同一个状态、同一个基数走 **Direct** 管线 ⇒ 3 点。两者必须不同。
        let mut direct = solo();
        give(&mut direct, "hero", status("st_sig", "signature_pending", 0));
        let mut ctx = ExecContext::new(&mut direct, None, None, None, 1024).with_content(&content);
        let (_blocked, lost) =
            exec::resolve_damage(&mut ctx, &cid("hero"), 5, false).unwrap();
        assert_eq!(lost, 3, "Direct 管线吃 ×75");
        assert_ne!(lost, 5, "同一条路不可能既吃 ×75 又不吃");
    }

    // ---------------------------------------------------------------- DoT 的出手方

    /// 把一个 spec 的 `RestrictDamageKind` 槽改成 `NULL16`（= JSON null = **不限种类**）。
    ///
    /// 为什么需要这么一手：镜像里 **5 条 spec 的 `RestrictDamageKind` 全是 `Direct`**
    /// （实测），所以"一条不限种类的 `DamageDealt` spec 会放大 DoT"这件事**在真实内容上
    /// 构造不出来**。而它恰恰是 `PassiveModifiers.cs:154-156` 那道门的另一半
    /// （`restrict == null` ⇒ 整条 `continue` 不成立）。
    ///
    /// 手法照抄 `exec.rs` 的"镜像补丁（2 字节）"（那边是私有的测试助手）：先解析出字段槽
    /// 的字节偏移 → 改内存里的那 2 个字节 → 重新解析。**只改副本，不碰磁盘上的镜像。**
    fn patch_kind_to_null(blob: &mut [u8], status_id: &str) {
        // 第一遍：只为算偏移。
        let at = {
            let content = parse(blob);
            let row = status_bind::status_row(&content, status_id)
                .unwrap_or_else(|| panic!("镜像里必须有状态 {status_id}"));
            let arr = content
                .term(row.passive_modifiers())
                .expect("PassiveModifiers 必须是 term");
            assert_eq!(arr.op, OP_ARR, "{status_id} 的 PassiveModifiers 必须是 _arr");
            let start = arr.slot(0).expect("_arr 槽 0");
            let spec = content
                .aux(start)
                .expect("_arr 的第一个元素必须在 AUX 里");
            field_slot_offset(&content, spec, "RestrictDamageKind")
        };
        // 第二遍之前：写字节。`field_slot_offset` 与 `ir::NodeRef::field_spec` 同一套映射
        // （字段按声明序累加槽位），`RestrictDamageKind` 是 `F_STR` 单槽。
        let cell = blob.get_mut(at..at + 2).expect("补丁偏移必须在镜像内");
        cell.copy_from_slice(&NULL16.to_le_bytes());
    }

    /// 一个 term 某字段**首槽**在 blob 里的字节偏移（`exec.rs` 的同名测试助手，抄一份）。
    ///
    /// 抄的理由与 `play.rs:751-753` 那条一样：它是 `exec.rs` 测试模块的私有函数，
    /// 而"只准改这几个文件"的约束不允许我去把它 `pub`。**只用于测试。**
    fn field_slot_offset(content: &Content<'_>, tid: u16, key: &str) -> usize {
        let trw = content
            .section(crate::content::S_TRW)
            .expect("TRW 段");
        let word = usize::from(trw.u16_at(usize::from(tid)).expect("TRW 项越界"));
        let trm = content
            .section(crate::content::S_TRM)
            .expect("TRM 段");
        let base = trm.offset as usize + word * 4 + 2;
        let term = content.term(tid).expect("term 必须存在");
        let opcode = content.opcode(term.op).expect("opcode 必须存在");
        let mut slot = 0usize;
        for j in 0..opcode.nfields() {
            let field = opcode.field(j).expect("字段描述越界");
            if content.string(field.name_str()) == Some(key) {
                return base + slot * 2;
            }
            slot += usize::from(field.slots().expect("槽宽非法"));
        }
        panic!("term {tid} 没有字段 {key}");
    }

    #[test]
    fn dot_takes_the_source_side_specs_now_that_the_field_exists() {
        // ⚠️ **这条是裁决 2 的证据**。参考把毒源塞进伤害请求（`StatusEffects.cs:501-509`），
        // 而 Source 阶段读的是**出手方**身上的 `DamageDealt` spec
        // （`PassiveModifiers.cs:242-254`）。在 `source_combatant_id` 补上之前，这一格不存在
        // ⇒ Source 阶段整段跳过 ⇒ "下毒者的力量加成"永远缺席，**而且看不出来**。
        //
        // 上半场：真实镜像（5 条 spec 全 `Direct` ⇒ DoT 被种类门挡掉，加成**不该**出现）；
        // 下半场：把 `strength` 的 `RestrictDamageKind` 补丁成 null（不限种类）⇒ 加成**必须**出现。
        // 同一个钩子、同一段代码，两种内容给出两个不同的数字 —— 这才证明 Source 阶段真的在跑。
        let mut blob = core_image();
        let original = blob.clone();
        let real = parse(&blob);

        // ── 上半场：真实镜像。poison 5，出手方 enemy_a 带 strength 3，但 `strength` 是
        // `Direct` 门 ⇒ DoT 只打 5 点。
        let mut state = arena();
        give_dot_from(&mut state, "hero", "poison", 5, "enemy_a");
        give(&mut state, "enemy_a", status("st_str", "strength", 3));
        let mut host = Host::new(&real);
        host.try_damage_over_time(&mut state, &cid("hero")).unwrap();
        assert_eq!(health(&state, "hero"), 65, "Direct 门的 spec 不许放大 DoT");

        // ── 下半场：补丁成 null ⇒ 同一个 spec 现在**必须**放大它（5 + 3 = 8）。
        patch_kind_to_null(&mut blob, "strength");
        assert_ne!(
            blob, original,
            "补丁必须真的改掉了镜像字节（否则下面那条断言证明不了任何事）"
        );
        let patched = parse(&blob);

        let mut state = arena();
        give_dot_from(&mut state, "hero", "poison", 5, "enemy_a");
        give(&mut state, "enemy_a", status("st_str", "strength", 3));
        let mut host = Host::new(&patched);
        host.try_damage_over_time(&mut state, &cid("hero")).unwrap();
        assert_eq!(
            health(&state, "hero"),
            62,
            "5 + 3（力量的 AddPerStack 1 × 3 层）：出手方的不限种类 spec 生效了"
        );

        // ── 反例一：同一个补丁内容，出手方**没有**那个 spec ⇒ 不放大。
        let mut state = arena();
        give_dot_from(&mut state, "hero", "poison", 5, "enemy_a");
        let mut host = Host::new(&patched);
        host.try_damage_over_time(&mut state, &cid("hero")).unwrap();
        assert_eq!(health(&state, "hero"), 65, "出手方没 spec ⇒ 5 点");

        // ── 反例二：出手方**有**那个 spec，但这条毒**没有记录来源** ⇒ 也不放大
        // （证明起作用的是这一格字段，而不是"出手方恰好也有 strength"）。
        let mut state = arena();
        give(&mut state, "hero", status("st_poi", "poison", 5)); // 没有 source
        give(&mut state, "enemy_a", status("st_str", "strength", 3));
        let mut host = Host::new(&patched);
        host.try_damage_over_time(&mut state, &cid("hero")).unwrap();
        assert_eq!(
            health(&state, "hero"),
            65,
            "没有来源 ⇒ Source 阶段整段跳过（`PassiveModifiers.cs:248-249`）"
        );
    }

    #[test]
    fn apply_status_records_the_source_and_the_row_survives_a_merge() {
        // 参考：新实例**原样收下**这一次施加的出手方（`StatusEffects.cs:187`），
        // 而**合并时不动它**（`:159-165` 的注释：*"The instance keeps its own source,
        // untouched"*）。两条都在这条测试里。
        //
        // 这里走的是端到端的**节目**路径：`one_remaining_seal` 的 TurnEnded 触发器
        // 会对 `sel.source`（= 本回合行动者）施加 `seal_intact` ⇒ 实例的来源必须被写成
        // 那个行动者，而不是 `None`。
        let blob = core_image();
        let content = parse(&blob);
        let mut state = solo();
        give(&mut state, "hero", status("st_ors", "one_remaining_seal", 0));
        let mut host = Host::new(&content);
        host.try_run_turn_ended_triggers(&mut state, &cid("hero"))
            .unwrap();
        let seal = state
            .combatant(&cid("hero"))
            .unwrap()
            .statuses()
            .iter()
            .find(|s| s.definition_id.as_str() == "seal_intact")
            .copied()
            .expect("触发器应当施加了 seal_intact");
        assert_eq!(
            seal.source_combatant_id,
            Some(cid("hero")),
            "节目里的 sel.source 就是 Context.Source ⇒ 实例收下它"
        );
        // 层数也照常（1 层），证明不是"只写了来源没施加"。
        assert_eq!(seal.stacks, 1);
    }

    #[test]
    fn source_combatant_id_does_not_enter_the_fingerprint() {
        // 裁决 2 的第三件事：这一格**不进** `write_hash_input`，而且那是**故意的**。
        //
        // 参考的 `CombatStateHasher.AppendStatus` 只写
        // `Id / DefinitionId / stk= / dur= / chg= / pol= / [pend=]`（`CombatStateHasher.cs:108-119`），
        // 没有 `SourceCombatantId` ⇒ 加这个字段不动任何指纹、85 份语料不用重生。
        // 这条测试把它钉住：两个状态**只有一个字段不同**，指纹必须逐字节相同。
        let mut without = solo();
        give(&mut without, "hero", status("st_poi", "poison", 3));
        let mut with = solo();
        let mut instance = status("st_poi", "poison", 3);
        instance.source_combatant_id = Some(cid("hero"));
        give(&mut with, "hero", instance);

        let text = state_text(&without);
        assert_eq!(state_text(&with), text, "来源不进指纹");
        // 非平凡：指纹里**有**这一行状态（否则"相等"可能因为两边都是空的而毫无意义）。
        let text = std::string::String::from_utf8(text).expect("指纹是 UTF-8");
        assert!(
            text.contains("poison"),
            "指纹里必须有这条状态：{text}"
        );
        // 而两个状态**确实**不同（字段真的写进去了，不是赋值没生效）。
        assert_ne!(
            without.combatant(&cid("hero")).unwrap().statuses()[0],
            with.combatant(&cid("hero")).unwrap().statuses()[0],
            "两个实例必须真的不同，否则上面那条相等是废话"
        );
    }

    #[test]
    fn a_finished_combat_stops_the_dot_ticks() {
        // 参考的排空循环条件是 `while (hasPending) && Result == Ongoing`
        // （`CombatEventHandling.cs:97`）⇒ 战斗一结束，后面入队的 tick 不再落地。
        //
        // ⚠️ 这一条测的是"钩子**认**这个条件"，所以它**手动**把 `result` 设成终态。
        // 从 2026-10-19 起 `result` 也会被真实路径写（`exec::update_standard_combat_result`
        // 在目标倒下那一行判），"DoT 真的打死最后一个敌人"那条真实路径的测试是
        // `a_lethal_tick_downs_the_target_and_the_combat_result_is_computed_right_there`。
        // 两条互补：一条隔离条件判定，一条证明条件真的会出现。
        let blob = core_image();
        let content = parse(&blob);

        let mut ongoing = solo();
        give(&mut ongoing, "hero", status("st_poi", "poison", 3));
        let mut host = Host::new(&content);
        host.try_damage_over_time(&mut ongoing, &cid("hero")).unwrap();
        assert_eq!(health(&ongoing, "hero"), 67);

        let mut finished = solo();
        give(&mut finished, "hero", status("st_poi", "poison", 3));
        finished.result = CombatResult::Defeat;
        let mut host = Host::new(&content);
        host.try_damage_over_time(&mut finished, &cid("hero"))
            .unwrap();
        assert_eq!(health(&finished, "hero"), 70, "战斗已结束 ⇒ 不再跳");
    }

    #[test]
    fn a_lethal_tick_downs_the_target_and_the_combat_result_is_computed_right_there() {
        // "DoT 打死目标"的完整形状：`resolve_damage` 把 HP 写到 0 并转 `Downed`
        // （`CombatantLifecycleEffects.cs:29-43` 的那条 handler，本内核同步做），
        // 紧接着**就在那一行**判胜负（`CombatStateEffects.cs:36-58`）。
        //
        // ⚠️ 2026-10-19 之前这条测试断言的是"`result` **不动**"，并把那条缺口写成
        // "判胜负的 handler 还没移植"。整局对拍（`native/fight_diff.py`）证明那个期望
        // **本身就是错的**：参考是"倒下即判、判了就停"，而"打死了但战斗没结束"
        // 正是 `play.rs` 的 Cancelled 分支不可达的根因。所以期望改了，不是实现错了。
        //
        // `solo()` 只有英雄一个人 ⇒ 他没有队友、而这一局也**没有敌人** ⇒
        // 两边都没有活人 ⇒ `Draw`（`CombatStateEffects.cs:43-47`）。这个"看起来怪"的
        // 结果恰恰是规则逐行照抄的证据：不是 Defeat（`:49-53` 要求"敌人还有活人"）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        state.combatant_mut(&cid("hero")).unwrap().health_current = 2;
        give(&mut state, "hero", status("st_poi", "poison", 5));
        host.try_damage_over_time(&mut state, &cid("hero")).unwrap();
        assert_eq!(health(&state, "hero"), 0);
        assert_eq!(
            state.combatant(&cid("hero")).unwrap().lifecycle_state,
            crate::state::CombatantLifecycleState::Downed
        );
        assert_eq!(
            state.result,
            CombatResult::Draw,
            "两边都没有活人 ⇒ Draw（`CombatStateEffects.cs:43-47`）"
        );

        // 成对：同一个钩子在有敌人、且倒下的是**敌人**时给 `Victory`
        // （`CombatStateEffects.cs:55-58`）—— 没有这一条，上面那个 `Draw` 可能只是
        // "不管死谁都判 Draw"。
        let mut state = arena();
        state.combatant_mut(&cid("enemy_a")).unwrap().health_current = 2;
        state.combatant_mut(&cid("enemy_b")).unwrap().health_current = 2;
        give(&mut state, "enemy_a", status("st_a", "poison", 5));
        give(&mut state, "enemy_b", status("st_b", "poison", 5));
        let mut host = Host::new(&content);
        host.try_damage_over_time(&mut state, &cid("enemy_a")).unwrap();
        assert_eq!(state.result, CombatResult::Ongoing, "敌人_b 还活着");
        host.try_damage_over_time(&mut state, &cid("enemy_b")).unwrap();
        assert_eq!(health(&state, "enemy_b"), 0);
        assert_eq!(state.result, CombatResult::Victory, "最后一个敌人倒下");
    }

    // ---------------------------------------------------------------- 钩子 9：QueuePile

    #[test]
    fn the_card_queue_really_runs_the_program_and_moves_the_card() {
        // 参考 `QueueResolution.cs:18-128`：队列卡**不是第二次出牌**（没有费用、没有事件、
        // 不过校验器），它的节目在这里跑，跑完牌搬到 `PlayedCardDestinationZone`。
        // `paper_cut` 的节目是 `dealDamage 6 → sel.eventTarget`（实测 dump）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give_draw_pile(&mut state, "hero", 10);
        give_card(
            &mut state,
            "hero",
            CardZone::QueuePile,
            "q1",
            "paper_cut",
            Some("enemy_a"),
        );

        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(health(&state, "enemy_a"), 14, "锁定目标吃了 6 点");
        assert_eq!(health(&state, "enemy_b"), 10, "别的目标不受影响");
        assert_eq!(zone_count(&state, "hero", CardZone::QueuePile), 0, "离队");
        assert_eq!(
            zone_count(&state, "hero", CardZone::DiscardPile),
            1,
            "落到 PlayedCardDestinationZone"
        );

        // 无事可做的那一面：队列本来就是空的 ⇒ 一条 zone 都不动。
        let mut empty = arena();
        let mut host = Host::new(&content);
        host.try_resolve_card_queue(&mut empty, &cid("hero")).unwrap();
        assert_eq!(zone_count(&empty, "hero", CardZone::QueuePile), 0);
        assert_eq!(zone_count(&empty, "hero", CardZone::DiscardPile), 0);
    }

    #[test]
    fn a_queued_card_whose_locked_target_left_fizzles_but_still_leaves_the_queue() {
        // `QueueResolution.cs:66-70`：目标在排队时锁定，离场后**不重定向** ——
        // 节目里绑定目标的那部分失效。而 `Finish`（`:116-128`）照样把牌搬走。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give_draw_pile(&mut state, "hero", 10);
        give_card(
            &mut state,
            "hero",
            CardZone::QueuePile,
            "q1",
            "paper_cut",
            Some("a_combatant_that_left"),
        );
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(health(&state, "enemy_a"), 20, "没有目标 ⇒ 没有伤害");
        assert_eq!(health(&state, "enemy_b"), 10);
        assert_eq!(
            zone_count(&state, "hero", CardZone::DiscardPile),
            1,
            "牌照样落区（Finish 与目标无关）"
        );
    }

    #[test]
    fn a_queued_card_without_a_locked_target_still_runs_its_source_side_program() {
        // `cower_behind_a_desk` = `gainBlock 5 → sel.source`（实测），不需要目标
        // ⇒ "没有锁定目标"不等于"节目不跑"。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give_card(
            &mut state,
            "hero",
            CardZone::QueuePile,
            "q1",
            "cower_behind_a_desk",
            None,
        );
        // `sel.source` 是**拥有者**（`CreateCardPlayBuildContext(combat, card.Id, owner, target)`）。
        host.try_resolve_card_queue(&mut state, &cid("hero")).unwrap();
        // ⚠️ 批次 2：`execute_program` 只**派发**，请求要等外层的相位 1 才落地
        // （参考的 `QueueResolution` 也一样：它自己不开排空循环）。
        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(block_of(&state, "hero"), 5);
        assert_eq!(zone_count(&state, "hero", CardZone::DiscardPile), 1);
    }

    // ---------------------------------------------------------------- 恒 no-op 的钩子

    #[test]
    fn resolve_pending_queues_is_a_no_op_and_that_is_measurable() {
        // 规格书 §2.3 的"空实现就够"的条件是：宿主不在钩子之间留任何待处理队列。
        // 条件成立与否**不是靠说**，这条测试逐字节比对哈希输入文本。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);

        let mut bare = solo();
        let before = state_text(&bare);
        host.try_resolve_pending_queues(&mut bare).unwrap();
        assert_eq!(state_text(&bare), before, "空状态：一个字节都不许改");

        // 一个有活要干的回合之后，重复调用仍然什么都不改（说明"活"都在钩子里就地做完了，
        // 没有任何东西堆在队列里等排空）。
        let mut busy = solo();
        give(&mut busy, "hero", status("st_poi", "poison", 3));
        give_card(
            &mut busy,
            "hero",
            CardZone::QueuePile,
            "q1",
            "cower_behind_a_desk",
            None,
        );
        turn::start_current_turn(&mut busy, &config(), &mut host).unwrap();
        let before = state_text(&busy);
        host.try_resolve_pending_queues(&mut busy).unwrap();
        host.try_resolve_pending_queues(&mut busy).unwrap();
        assert_eq!(state_text(&busy), before);
    }

    #[test]
    fn the_six_do_nothing_hooks_change_nothing_on_a_bare_turn() {
        // V9：没有任何 pending / UsesDuration / LifecyclePrograms / retain_* 时，
        // 那几个钩子**一个哈希行都不许变**。这里直接打 9 个钩子里的 6 个
        // （跳过的三个是"有活"的：触发器、DoT、队列）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        let before = state_text(&state);

        host.try_activate_pending_statuses(&mut state, &cid("hero"))
            .unwrap();
        host.try_decrease_timed_statuses(&mut state, &cid("hero"))
            .unwrap();
        host.try_hand_turn_end_lifecycle(&mut state, &cid("hero"))
            .unwrap();
        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(state_text(&state), before);

        // 三个 `&self` 判据也必须是"今天正确的默认值"。
        assert!(!host.hand_is_retained_detail(&state, &cid("hero")));
        assert!(!host.block_is_retained_detail(&state, &cid("hero")));
    }

    /// #1 的回归闸门：**四条回合事件各发一个链号**，而**同一批处理器里的步骤一个都不发**。
    ///
    /// 依据全是数据（见模块头那张表 + `native/fight_diff.py` 四个场景 14 个步边界的唯一解）：
    /// `finish` 的 `AdvanceToNextRound` 一步 `chain_num +6`，正好是
    /// "结束英雄回合 / 开敌方回合 / 结束敌方回合 / RoundEnded / RoundStarted / 开英雄新回合" 六条；
    /// `dot_kill` 的 `HeroEndsTurn` 一步 `+2`，其中 DoT 那一跳**一次都不发号** ——
    /// 所以这条测试把"DoT 不发号"钉成硬断言，它是 `dot_kill` 能不能逐字节对上的分界线。
    #[test]
    fn the_four_turn_events_each_allocate_one_effect_chain_and_the_other_steps_allocate_none() {
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        let actor = cid("hero");

        // 四步"处理器内部步骤"：一条 turn-start 事件里的 2/3/5a/5b 与 turn-end 里的 ①/④。
        // 它们**不是**独立事件（参考里都是同一次排空里的处理器），所以不许发号。
        let chain = state.next_effect_chain_number;
        host.activate_pending_statuses(&mut state, &actor).unwrap();
        host.resolve_card_queue(&mut state, &actor).unwrap();
        host.resolve_pending_queues(&mut state).unwrap();
        host.hand_turn_end_lifecycle(&mut state, &actor).unwrap();
        host.decrease_timed_statuses(&mut state, &actor).unwrap();
        assert_eq!(
            state.next_effect_chain_number, chain,
            "同一批处理器里的步骤不发号（发了 `finish` 就不是 +6 而是 +10 以上）"
        );

        // DoT 那一跳：它是 turn-start 处理器列表里的**第 7 个**，不是独立事件 ⇒ 不发号。
        give(&mut state, "hero", status("st_poi", "poison", 1));
        let chain = state.next_effect_chain_number;
        host.damage_over_time(&mut state, &actor).unwrap();
        assert_eq!(health(&state, "hero"), 69, "非平凡：这一跳真的落地了");
        assert_eq!(
            state.next_effect_chain_number, chain,
            "`dot_kill` 的 step1 只 +2（TurnEnded + TurnStarted）；DoT 要是发号就不止"
        );

        // 四条回合事件：各 +1。
        let chain = state.next_effect_chain_number;
        host.run_turn_started_triggers(&mut state, &actor).unwrap();
        assert_eq!(state.next_effect_chain_number, chain + 1, "TurnStarted");
        host.run_turn_ended_triggers(&mut state, &actor).unwrap();
        assert_eq!(state.next_effect_chain_number, chain + 2, "TurnEnded");
        host.on_round_ended(&mut state, 1).unwrap();
        assert_eq!(state.next_effect_chain_number, chain + 3, "RoundEnded");
        host.on_round_started(&mut state, 2).unwrap();
        assert_eq!(state.next_effect_chain_number, chain + 4, "RoundStarted");
    }

    #[test]
    fn decrease_timed_statuses_does_nothing_because_no_status_uses_duration() {
        // 实测依据：23/23 状态 `UsesDuration = false`（`F_BOOL` 原始值 1）。
        // 用一个**时长轴非零**的实例去试：`poison` 的 `duration_turns = 5`，但它不带
        // `UsesDuration` ⇒ 不该被减（判据是定义上的标记，不是"时长 > 0"这种推断，
        // `StatusEffects.cs:394`）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        let mut instance = status("st_poi", "poison", 3);
        instance.duration_turns = 5;
        give(&mut state, "hero", instance);

        let before = state_text(&state);
        host.try_decrease_timed_statuses(&mut state, &cid("hero"))
            .unwrap();
        assert_eq!(state_text(&state), before, "UsesDuration = false ⇒ 一格都不动");
        assert_eq!(duration_of(&state, "hero", "poison"), 5);
    }

    #[test]
    fn the_real_image_has_no_lifecycle_program_on_any_of_its_62_cards() {
        // 实测依据：62/62 卡 `LifecyclePrograms = {}`（0 字段的 `_obj`，term 11）。
        //
        // ⚠️ 这条**不是**"钩子是空实现"的证据（那个机制是真的，见下面 `burn` 那组手搓镜像的
        // 测试）；它证明的是**真实内容今天一个节目都没有**，所以四条对拍层的逐字节相等
        // 与这个钩子无关。它的第二条职责是**解码器在真实镜像上的回归闸门**：
        // 谁把"空"判错了（例如把 0 字段的 `_obj` 当成"有一条节目"），这里立刻红。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give_card(&mut state, "hero", CardZone::Hand, "c1", "paper_cut", None);
        give_card(
            &mut state,
            "hero",
            CardZone::Hand,
            "c2",
            "cower_behind_a_desk",
            None,
        );
        let before = state_text(&state);
        host.try_hand_turn_end_lifecycle(&mut state, &cid("hero"))
            .unwrap();
        assert_eq!(state_text(&state), before);

        let mut cards = 0usize;
        let mut with_programs = 0usize;
        for row in content.rows(crate::content::Table::Card) {
            let Some(id) = content.string(row.cell(0).unwrap_or(ABSENT16)) else {
                continue;
            };
            cards += 1;
            if card_lifecycle_turn_end_program(&content, id)
                .unwrap()
                .is_some()
            {
                with_programs += 1;
            }
        }
        assert_eq!(cards, 62);
        assert_eq!(with_programs, 0, "62/62 LifecyclePrograms = {{}}");
    }

    // ------------------------------------- 生命周期节目真的会跑（手搓镜像上的 6 条）

    /// Burn 的机制：牌在手里过回合 ⇒ 对**持有者**扣 2 点，**每回合末恰好一次**。
    ///
    /// 参考：`CardLifecycleProgramTests.cs:39-50`（`A_burn_held_at_turn_end_damages_its_owner`），
    /// 节目是 `dealDamage{TargetSelector: sel.source, Amount: 2}`（`:21-27`）。
    ///
    /// 判据能区分三种错实现：跑两次 ⇒ 66；一次都没跑 ⇒ 70；跑成**出牌**节目 ⇒ 70
    /// （`curse.burn` 没有出牌节目）。走完整回合末（`turn::end_current_turn`）而不是直接打钩子
    /// —— 这条同时钉住"钩子在回合机的第 1 位"。
    #[test]
    fn a_burn_card_in_hand_deals_two_to_its_bearer_once_per_turn_end() {
        let blob = burn_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(70);
        give_card(&mut state, "hero", CardZone::Hand, "burn1", "curse.burn", None);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(health(&state, "hero"), 70, "开局满血（非平凡）");

        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(health(&state, "hero"), 68, "恰好一次 2 点");
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 0, "回合末照样弃手牌");
        assert_eq!(zone_count(&state, "hero", CardZone::DiscardPile), 1);
    }

    /// 读的是 `LifecyclePrograms` 那一格，**不是**卡的出牌节目 `Program`。
    ///
    /// `curse.burn_dual` 两格都写了：出牌 `dealDamage{7}`、生命周期 `dealDamage{2}`。
    /// 读错格子 ⇒ 63；正解 68。镜像里这是 `CARD` 行的第 1 格与第 4 格（`content.rs:1330/:1336`）。
    #[test]
    fn the_lifecycle_program_runs_instead_of_the_card_play_program() {
        let blob = burn_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(70);
        give_card(&mut state, "hero", CardZone::Hand, "dual1", "curse.burn_dual", None);

        host.try_hand_turn_end_lifecycle(&mut state, &cid("hero"))
            .unwrap();
        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(health(&state, "hero"), 68, "跑的是 LifecyclePrograms 那一格");
    }

    /// 没有生命周期节目的卡**什么都不跑** —— 哪怕它有出牌节目。
    ///
    /// 两个镜像各来一张，判据都是"一格状态都不许动 + 不发执行号"：
    /// * 真实镜像 `paper_cut` 的出牌节目是 `node.dealDamage{Amount: 6, TargetSelector: sel.eventTarget}`
    ///   （`exec.rs:4242` 的实测注释），而本钩子上下文里 `sel.eventTarget` **就是持有者**
    ///   ⇒ 读错格子会立刻打 6 点；
    /// * 手搓镜像 `plain.card` = 出牌 `dealDamage{2, sel.source}`、生命周期 `{}`（0 字段的 `_obj`）。
    #[test]
    fn a_card_with_no_lifecycle_program_runs_nothing_even_though_it_has_one_on_play() {
        // (a) 真实镜像：62/62 卡都是这一支。
        let real = core_image();
        let real_content = parse(&real);
        let mut host = Host::new(&real_content);
        let mut state = duel(70);
        give_card(&mut state, "hero", CardZone::Hand, "c1", "paper_cut", None);
        let before = state_text(&state);
        host.try_hand_turn_end_lifecycle(&mut state, &cid("hero"))
            .unwrap();
        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(
            state_text(&state),
            before,
            "空 LifecyclePrograms ⇒ 一格都不动（含 chain_num / exec_num）"
        );

        // (b) 手搓镜像：同一份内容里"有出牌节目、没有生命周期节目"的卡。
        let blob = burn_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(70);
        give_card(&mut state, "hero", CardZone::Hand, "p1", "plain.card", None);
        let before = state_text(&state);
        host.try_hand_turn_end_lifecycle(&mut state, &cid("hero"))
            .unwrap();
        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(
            state_text(&state),
            before,
            "0 字段的 `_obj` 不是「有一条节目」"
        );
        assert_eq!(health(&state, "hero"), 70);
    }

    /// **每一张**有节目的手牌都跑（不是只跑第一张）。
    ///
    /// 两张 Burn ⇒ 68 - 4 = 66。只跑第一张的实现在这里给 68。
    #[test]
    fn every_hand_card_with_a_program_runs_once() {
        let blob = burn_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(70);
        give_card(&mut state, "hero", CardZone::Hand, "burn1", "curse.burn", None);
        give_card(&mut state, "hero", CardZone::Hand, "burn2", "curse.burn", None);

        host.try_hand_turn_end_lifecycle(&mut state, &cid("hero"))
            .unwrap();
        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(health(&state, "hero"), 66, "两张各扣 2 点");
    }

    /// 只在**手牌**里发作：抽牌堆 / 弃牌堆里的同一张卡不跑。
    ///
    /// "对手里所有卡都跑" 的实现会扣 6（这里 68）；只认手牌 ⇒ 68。
    #[test]
    fn a_burn_card_outside_the_hand_does_not_fire() {
        let blob = burn_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(70);
        give_card(&mut state, "hero", CardZone::Hand, "burn1", "curse.burn", None);
        give_card(&mut state, "hero", CardZone::DrawPile, "burn2", "curse.burn", None);
        give_card(&mut state, "hero", CardZone::DiscardPile, "burn3", "curse.burn", None);

        host.try_hand_turn_end_lifecycle(&mut state, &cid("hero"))
            .unwrap();
        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(health(&state, "hero"), 68, "只有手牌那一张");
    }

    /// 生命周期节目**可以致死**，而且死了之后排空就停：后面排队的东西不落地、回合不推进。
    ///
    /// 编排：英雄 2 点血，手里一张 `curse.burn`（扣 2）在前、一张 `curse.burn_block`
    /// （加 5 格挡）在后。两个节目都会跑（参考也是先把整批节目派发完），于是效果队列里
    /// 先有 `dealDamage 2`、后有 `gainBlock 5`。
    /// 排空的第一条就把英雄打到 0 ⇒ `Result != Ongoing` ⇒ 循环退出 ⇒ **格挡那条永远不落地**。
    ///
    /// 判据：`hp == 0`（而不是 -2：血量饱和在 0）、`block == 0`（排空没越过判负）、
    /// `result == Defeat`、回合没推进（`active_combatant_id` 还是英雄）。
    /// 一个不看 `Result` 的排空循环会在死后继续加 5 格挡 ⇒ `block == 5` 当场红。
    #[test]
    fn a_lethal_lifecycle_program_ends_the_fight_and_the_rest_of_the_drain_never_lands() {
        let blob = burn_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(2);
        give_card(&mut state, "hero", CardZone::Hand, "burn1", "curse.burn", None);
        give_card(
            &mut state,
            "hero",
            CardZone::Hand,
            "blk1",
            "curse.burn_block",
            None,
        );
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        let turn_before = state.current_turn;

        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();

        assert_eq!(state.result, CombatResult::Defeat, "Burn 是致命的");
        assert_eq!(health(&state, "hero"), 0, "2 - 2 = 0（血量饱和，不会到 -2）");
        assert_eq!(
            state
                .combatant(&cid("hero"))
                .unwrap()
                .lifecycle_state,
            crate::state::CombatantLifecycleState::Downed
        );
        assert_eq!(
            block_of(&state, "hero"),
            0,
            "判负之后的排空必须停住 ⇒ 后面那条 gainBlock 5 不落地"
        );
        assert_eq!(
            state.active_combatant_id,
            Some(cid("hero")),
            "回合没有推进（`end_current_turn` 的 ②）"
        );
        assert_eq!(state.current_turn, turn_before);
        assert_eq!(
            state.turn_phase,
            crate::state::CombatTurnPhase::WaitingToStartTurn
        );
    }

    /// 一个节目 = **执行号 +1、链号 +0**。
    ///
    /// 参考：执行号在 `EffectProgramExecutor.Execute` 里发（`EffectProgramExecution.cs:27`）；
    /// 链号不发，因为处理器跑在 `TurnEndedCombatEvent` 的分支里、那一刻 `CurrentEffectChain`
    /// 是事件自己那条链（`CombatEventHandling.cs:60`）。内核把 `TurnEnded` 的那一个号发在
    /// `try_run_turn_ended_triggers` 里，所以这里用 `adopt_root_chain`（建链、不推进计数器）。
    ///
    /// 三种错实现分别给：`new_root_chain` ⇒ 链号 +1；`exec::execute`（遗留入口）⇒ 执行号 +0；
    /// 什么都不跑 ⇒ 两个都不动（最后一条被"非平凡"那句挡住）。
    #[test]
    fn a_lifecycle_program_advances_the_execution_number_but_not_the_chain_number() {
        let blob = burn_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(70);
        give_card(&mut state, "hero", CardZone::Hand, "burn1", "curse.burn", None);
        // `start_current_turn` 自己会 +1 链号（TurnStarted 那一条），先把它跑掉。
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        let chain = state.next_effect_chain_number;
        let exec = state.next_program_execution_id;
        let live_chains = state.live_chain_count();

        host.try_hand_turn_end_lifecycle(&mut state, &cid("hero"))
            .unwrap();
        assert_eq!(
            state.next_effect_chain_number, chain,
            "链号不动：参考在 TurnEnded 事件链里跑（`CombatEventHandling.cs:60`）"
        );
        assert_eq!(
            state.next_program_execution_id,
            exec + 1,
            "执行号 +1（`EffectProgramExecution.cs:27`）"
        );

        host.try_resolve_pending_queues(&mut state).unwrap();
        assert_eq!(health(&state, "hero"), 68, "非平凡：节目真的跑了");
        // 链 arena 不许漏：节目帧拿了链、排空把它们放掉，钩子自己那一次引用也要还。
        // 漏一次的后果不是"看起来错"，而是**第 128 个回合末**才 `Capacity(Full(Chains))` ——
        // 那种迟到 128 步的失败，只有当场断言 live 数才能提前看见。
        assert_eq!(
            state.live_chain_count(),
            live_chains,
            "生命周期节目不许在链 arena 里留引用"
        );
    }

    /// 生命周期触发器不认识的键 ⇒ **响亮**（`HostError::Unsupported`），不是"跳过当没有"。
    ///
    /// 参考的 `CardLifecycleTrigger` 今天只有 `TurnEndInHand` 一个成员
    /// （`CardLifecyclePrograms.cs:8-11`），所以 `_obj{Drawn: …}` 意味着"内容用了内核没有的路"。
    /// 静默忽略会让那张卡**永远不发作且没有任何信号**。成对：同一份镜像里 `curse.burn` 不报错。
    #[test]
    fn a_lifecycle_trigger_other_than_turn_end_in_hand_is_loud() {
        let blob = burn_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(70);
        give_card(&mut state, "hero", CardZone::Hand, "w1", "curse.weird", None);
        assert_eq!(
            host.try_hand_turn_end_lifecycle(&mut state, &cid("hero")),
            Err(HostError::Unsupported("CardLifecycleTrigger")),
            "未知的生命周期触发器必须响亮"
        );

        let mut other = duel(70);
        give_card(&mut other, "hero", CardZone::Hand, "b1", "curse.burn", None);
        assert_eq!(
            host.try_hand_turn_end_lifecycle(&mut other, &cid("hero")),
            Ok(())
        );
    }

    /// `RetainInHandOnTurnEnd` 与生命周期节目**互不影响**：那张卡照样只发作一次。
    ///
    /// 参考里这条处理器只读手牌与卡定义（`CardLifecyclePrograms.cs:21-46`），
    /// `RetainInHandOnTurnEnd` 是**下一个**处理器（弃手牌，`CardZoneEffects.cs:419-425`）才读的
    /// ⇒ 一条 `retain` 分支都**不该有**。把保留的卡排除掉的实现会在这里给 70。
    ///
    /// ⚠️ **顺带发现的缺口（不是本钩子的）**：`Host::card_stays_in_hand_at_turn_end` 恒返回
    /// `false`（理由是"62/62 卡 `RetainInHandOnTurnEnd = false`"），所以这份手搓镜像里
    /// **真的** `true` 的 `curse.burn_retained` 回合末照样被弃。最后那句断言把缺口摆出来：
    /// 它一旦变红，说明那个钩子开始读内容了 —— 那时这条断言该按新语义改，别当成回归。
    #[test]
    fn a_retained_burn_card_still_fires_exactly_once() {
        let blob = burn_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(70);
        give_card(
            &mut state,
            "hero",
            CardZone::Hand,
            "keep1",
            "curse.burn_retained",
            None,
        );
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(health(&state, "hero"), 68, "保留标志不改变发作次数");
        assert_eq!(
            zone_count(&state, "hero", CardZone::DiscardPile),
            1,
            "缺口：`card_stays_in_hand_at_turn_end` 不读 `RetainInHandOnTurnEnd`（见文档）"
        );
    }

    // ---------------------------------------------------------------- 策略钩子

    #[test]
    fn panic_takes_cards_away_from_the_turn_start_draw() {
        // V5：`panic 2` ⇒ 抽 5 → 3。默认实现（返回 base）在这里是错的，
        // 这就是 `turn_start_draw_count` 非做不可的理由。
        let blob = core_image();
        let content = parse(&blob);
        let mut panicked = solo();
        give(&mut panicked, "hero", status("st_p", "panic", 2));
        for i in 0..10 {
            give_card(
                &mut panicked,
                "hero",
                CardZone::DrawPile,
                &std::format!("d{i}"),
                "paper_cut",
                None,
            );
        }
        let mut host = Host::new(&content);
        turn::start_current_turn(&mut panicked, &config(), &mut host).unwrap();
        assert_eq!(zone_count(&panicked, "hero", CardZone::Hand), 3);

        // 无事可做的那一面：没有 panic ⇒ 抽满配置的 5 张。
        let mut calm = solo();
        for i in 0..10 {
            give_card(
                &mut calm,
                "hero",
                CardZone::DrawPile,
                &std::format!("d{i}"),
                "paper_cut",
                None,
            );
        }
        let mut host = Host::new(&content);
        turn::start_current_turn(&mut calm, &config(), &mut host).unwrap();
        assert_eq!(zone_count(&calm, "hero", CardZone::Hand), 5);
    }

    #[test]
    fn the_strategy_defaults_are_correct_for_this_image_and_measured_not_assumed() {
        let blob = core_image();
        let content = parse(&blob);
        let host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_str", "strength", 2));
        give_card(&mut state, "hero", CardZone::Hand, "c1", "paper_cut", None);

        // `unspent_energy_carries`：法令 `UnspentResourceCarries` 由状态上的 `CombatRules` 承载，
        // 镜像 23/23 是 `ABSENT16` ⇒ 恒 false（= "补到"）。
        assert!(!TurnHost::unspent_energy_carries(&host, &state, &cid("hero")));
        // `card_stays_in_hand_at_turn_end`：62/62 `RetainInHandOnTurnEnd = false`，
        // 且没有任何内容加 `standard.retained_card` 标记（节点表里没有 `markCardInstance`）。
        let slot = state
            .card_zones(&cid("hero"))
            .and_then(|z| z.slot_at(CardZone::Hand, 0))
            .unwrap();
        assert!(!TurnHost::card_stays_in_hand_at_turn_end(
            &host,
            &state,
            &cid("hero"),
            slot
        ));
        // `turn_end_hand_destination`：62/62 卡 `TurnEndHandDestinationZone` 全是 DiscardPile。
        assert_eq!(
            TurnHost::turn_end_hand_destination(&host, &state, &cid("hero"), slot),
            CardZone::DiscardPile
        );
        // `turn_start_draw_count`：没有 `panic` 的 spec ⇒ 原值（含 base = 0 的原值返回）。
        assert_eq!(
            TurnHost::turn_start_draw_count(&host, &state, &cid("hero"), 5),
            5
        );
        assert_eq!(
            TurnHost::turn_start_draw_count(&host, &state, &cid("hero"), 0),
            0
        );
        // 两个标签钩子：镜像 23/23 状态既不带 `retain_hand` 也不带 `retain_block`。
        assert!(!TurnHost::hand_is_retained(&host, &state, &cid("hero")));
        assert!(!TurnHost::block_is_retained(&host, &state, &cid("hero")));
    }

    #[test]
    fn the_hand_is_actually_discarded_so_hand_is_retained_is_really_false() {
        // `hand_is_retained` 只有 `&self` + `bool` 一个通道，所以它的"false"必须靠
        // **可观察的后果**来证明：回合末手牌真的被搬走了（`turn.rs` 的 `discard_hand`）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give_card(&mut state, "hero", CardZone::Hand, "c1", "paper_cut", None);
        give_card(
            &mut state,
            "hero",
            CardZone::Hand,
            "c2",
            "cower_behind_a_desk",
            None,
        );
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 0);
        assert_eq!(zone_count(&state, "hero", CardZone::DiscardPile), 2);
    }

    #[test]
    fn block_is_cleared_at_the_next_turn_start_so_block_is_retained_is_really_false() {
        // V7/V8 的另一半：`retain_block` 标签不存在 ⇒ 格挡必清。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        give_block(&mut state, "hero", 5);
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(block_of(&state, "hero"), 5, "回合末不清格挡");
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(block_of(&state, "hero"), 0, "回合开始清空");
    }

    // ---------------------------------------------------------------- 失败面

    #[test]
    fn a_broken_trigger_entry_is_loud_instead_of_being_read_as_absent() {
        // 触发器表里的元素必须是 `_obj{Event, Program}`。这条测试打两种坏形状：
        //
        // 1. 句柄 0 是 `_null`（`op < 16`）⇒ 读字段直接报 `IrError::NotAnObject(0)`。
        //    **关键的"不许"**：不能把"读不出来"当成"这条触发器不存在"——那会让
        //    内容写了规则而内核安静不跑（这正是本项目最恨的失败形态）。
        // 2. 查一个内容里没有的状态 id ⇒ `BindError::Missing("STAT row")`（调用违约），
        //    而不是"这个状态有零条触发器"。
        let blob = core_image();
        let content = parse(&blob);
        let err = decode_trigger(&content, 0, 0).expect_err("不是对象就必须报错");
        assert_eq!(err, HostError::Exec(ExecError::Ir(IrError::NotAnObject(0))));

        let mut entries = [empty_trigger(&content); MAX_TRIGGERS_PER_STATUS];
        assert_eq!(
            Host::new(&content).triggers_of("no_such_status", &mut entries),
            Err(HostError::Bind(BindError::Missing("STAT row")))
        );
        // 暂存区太小 ⇒ `TooManyTriggers`（**不截断**）。`paper_seals_wax` 有 5 条。
        let mut narrow = [empty_trigger(&content); 2];
        assert_eq!(
            Host::new(&content).triggers_of("paper_seals_wax", &mut narrow),
            Err(HostError::TooManyTriggers { needed: 5, have: 2 })
        );
    }

    #[test]
    fn the_three_strategy_hooks_that_do_not_read_content_are_measured_not_assumed() {
        // 三个 `&self` 钩子今天**故意**不读内容（`card_stays_in_hand_at_turn_end` /
        // `turn_end_hand_destination` / `unspent_energy_carries`），因为它们没有 `Result`
        // 通道。而"今天恰好正确"这句话必须是**可复现的实测**，不是"应该没问题" ——
        // 所以这里把四条数字逐条量一遍。内容一改，这条测试立刻红。
        let blob = core_image();
        let content = parse(&blob);

        let mut cards = 0usize;
        let mut retain_true = 0usize;
        let mut destination_discard = 0usize;
        for row in content.rows(crate::content::Table::Card) {
            let Some(card) = content.card(row.index()) else {
                continue;
            };
            cards += 1;
            // `RetainInHandOnTurnEnd` 是 `F_BOOL` 格：2 = true，其余（含缺席/False/null）= false。
            if card.retain_in_hand_on_turn_end() == crate::content::BOOL_TRUE {
                retain_true += 1;
            }
            let handle = card.turn_end_hand_destination_zone();
            if handle != ABSENT16
                && handle != NULL16
                && content.string(handle) == Some("DiscardPile")
            {
                destination_discard += 1;
            }
        }
        assert_eq!(cards, 62);
        assert_eq!(retain_true, 0, "62/62 `RetainInHandOnTurnEnd` = false");
        assert_eq!(
            destination_discard, cards,
            "62/62 `TurnEndHandDestinationZone` = DiscardPile（枚举名原文，不是哈希短名）"
        );

        // `STAT.CombatRules`：23/23 是 `ABSENT16`（整格不存在）。
        let mut statuses = 0usize;
        let mut with_rules = 0usize;
        for row in content.rows(crate::content::Table::Status) {
            let Some(status) = content.status(row.index()) else {
                continue;
            };
            statuses += 1;
            if status.combat_rules() != ABSENT16 {
                with_rules += 1;
            }
        }
        assert_eq!(statuses, 23);
        assert_eq!(with_rules, 0, "23/23 状态的 CombatRules 缺席 ⇒ 没有法令");

        // `REL.CombatRules`：49/49 存在但是**空 `_arr`**（与状态那一路的编码不同，
        // 所以两条都要量 —— "没有"有两种拼法）。
        let mut relics = 0usize;
        for row in content.rows(crate::content::Table::Relic) {
            let Some(relic) = content.relic(row.index()) else {
                continue;
            };
            relics += 1;
            let handle = relic.combat_rules();
            assert_ne!(handle, ABSENT16, "遗物的 CombatRules 格是存在的（空数组）");
            let term = content.term(handle).expect("必须是 term");
            assert_eq!(term.op, OP_ARR, "遗物的 CombatRules 是 _arr");
            assert_eq!(term.slot(1), Some(0), "而且是**空的**");
        }
        assert_eq!(relics, 49);

        // ① 的另一半：`node.markCardInstance` 全镜像 **0 条 term**
        // （没有它就没有 `standard.retained_card` 标记）。
        let mut mark_terms = 0usize;
        let mut node_terms = 0usize;
        for tid in 0..content.term_count() {
            let Ok(tid) = u16::try_from(tid) else { continue };
            let term = content.term(tid).expect("term 必须存在");
            let Some(opcode) = content.opcode(term.op) else {
                continue;
            };
            let name = content.string(opcode.name_str).unwrap_or("");
            if !name.starts_with("node.") {
                continue;
            }
            node_terms += 1;
            if name == "node.markCardInstance" {
                mark_terms += 1;
            }
        }
        assert!(
            node_terms > 0,
            "这个循环必须真的扫到了 node term（否则下面那个 0 是空扫出来的）"
        );
        assert_eq!(mark_terms, 0, "全镜像没有 node.markCardInstance");
    }

    #[test]
    fn the_host_survives_a_turn_with_no_host_work_at_all() {
        // 端到端的一次"什么都没发生"的回合：没有状态、没有牌。
        // 它证明 9 个钩子在空输入上都是 `Ok(())`（没有一个在空表上 panic 或报错）。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(health(&state, "hero"), 70);
        assert_eq!(host.last_failure(), None, "一次失败都不该记下");
    }
}
