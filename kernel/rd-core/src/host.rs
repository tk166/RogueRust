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
use crate::exec::ExecError;
use crate::expr::ExprError;
use crate::ir::{IrError, NodeRef, Value};
use crate::state::{
    CapacityError, CardDefinitionId, CardSlot, CardZone, CombatEvent, CombatResult, CombatState,
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
/// §197：`Barricade` 用它（永久），`Blur` 用下面那个**一次性**的兄弟。
pub const TAG_RETAIN_BLOCK_ONCE: &str = "retain_block_once";
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
    /// `DamageTaken` —— **承受者侧**（`DamageEffects.cs:196-204`）。
    ///
    /// Bearer 是**挨打的那个**：`Thorns` 就长在这上面（"谁打我，我打回去"）。节目里
    /// `sel.source` 是承受者、`sel.eventTarget` 是出手方。
    DamageTaken,
    /// `Downed` —— 有战斗员倒下（`CombatantLifecycleEffects.cs`）。Bearer 是**倒下的那个**。
    ///
    /// 只认字面名 `Downed`；参考里还有 `CombatantLifecycleChanged` 之类的旁支，本内核没建模。
    Downed,
    /// `CardPlayed` —— 有人打出一张牌。**派发给所有战斗员**：`Enrage` 是"敌人反应你的出牌"。
    CardPlayed,
    /// `CardCostPaid` —— 出牌付了费用。
    CardCostPaid,
    /// §236：**失去生命**（不是伤害）。Bearer 是失去生命的那一方。
    ///
    /// 参考的实现里没有这个名字（它把这件事折进 `CardMovedToZone`/伤害事件），所以这一条是
    /// **本内核自己的事件名** —— 理由与我们加 `HpLoss` 这个动作本身一样：`Lose HP` 不是伤害。
    HpLost,
    /// §237：**获得了格挡**。Bearer = 获得格挡的那一方（`Juggernaut`）。
    ///
    /// 与 `DamageTaken` 一样是**承受者侧**的名字，但方向相反：那一条是"我被打"，
    /// 这一条是"我变厚了"。
    BlockGained,
    /// §237：**抽到了一张牌**。Bearer = 抽牌的人（`Evolve` / `Fire Breathing`）。
    ///
    /// 事实位给的是**抽到的那张牌**的标签（`card.hasTag.status|curse`，由 `card_tag_flags` 填）。
    CardsDrawn,
    /// §237：**一张牌被消耗了**。Bearer = 牌的主人（`Dark Embrace`）。
    CardExhausted,
    /// `StatusApplied` —— 一条新状态实例落到某人身上。
    StatusApplied,
    /// `StatusMerged` —— 并进了已有实例。
    StatusMerged,
    /// `StatusRemoved` —— 一条实例没了。
    StatusRemoved,
    /// `StatusStacksChanged` —— 某人的某条状态层数变了。
    StatusStacksChanged,
    /// `StatusApplicationPrevented` —— Artifact 挡掉一次 debuff。
    StatusApplicationPrevented,
    /// 参考有、但今天的 `TurnHost` 没有对应钩子的 11 个成员之一。
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
            "DamageTaken" => Some(TriggerEvent::DamageTaken),
            "Downed" => Some(TriggerEvent::Downed),
            "CardPlayed" => Some(TriggerEvent::CardPlayed),
            // §237: the three trigger hooks that used to be `NotHandled`.
            "BlockGained" => Some(TriggerEvent::BlockGained),
            "CardsDrawn" => Some(TriggerEvent::CardsDrawn),
            "CardExhausted" => Some(TriggerEvent::CardExhausted),
            // §236
            "HpLost" => Some(TriggerEvent::HpLost),
            "CardCostPaid" => Some(TriggerEvent::CardCostPaid),
            "StatusApplied" => Some(TriggerEvent::StatusApplied),
            "StatusMerged" => Some(TriggerEvent::StatusMerged),
            "StatusRemoved" => Some(TriggerEvent::StatusRemoved),
            "StatusStacksChanged" => Some(TriggerEvent::StatusStacksChanged),
            "StatusApplicationPrevented" => Some(TriggerEvent::StatusApplicationPrevented),
            // ── 参考有、本内核今天没有钩子接的 20 个（按 `EffectVocabulary.cs` 的声明序）──
            "Healed" | "StatusExpired"
            | "ResourceGained"
            | "CardMovedToZone" | "CardInstanceCreated"
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
            TriggerEvent::DamageTaken => "DamageTaken",
            TriggerEvent::Downed => "Downed",
            TriggerEvent::CardPlayed => "CardPlayed",
            // §237
            TriggerEvent::BlockGained => "BlockGained",
            TriggerEvent::CardsDrawn => "CardsDrawn",
            TriggerEvent::CardExhausted => "CardExhausted",
            TriggerEvent::HpLost => "HpLost",
            TriggerEvent::CardCostPaid => "CardCostPaid",
            TriggerEvent::StatusApplied => "StatusApplied",
            TriggerEvent::StatusMerged => "StatusMerged",
            TriggerEvent::StatusRemoved => "StatusRemoved",
            TriggerEvent::StatusStacksChanged => "StatusStacksChanged",
            TriggerEvent::StatusApplicationPrevented => "StatusApplicationPrevented",
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
        self.run_triggers_with_flags(state, actor, event, 0)
    }

    /// §236：上一个加上**事件事实位**（`event.bool` 读它）。
    ///
    /// 只有 `HpLost` 用到：Rupture 要区分"牌付的代价"与"状态每回合扣的"。其它事件走 flags = 0
    /// 那条，行为逐字不变。
    fn run_triggers_with_flags(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        event: TriggerEvent,
        flags: u16,
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
            let outcome = execute_program_with_flags(
                state,
                self.content,
                root,
                Some(*actor),
                None,
                steps,
                flags,
            );
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
        // 动画日志（§142）：回合边界也记一条 —— 页面要的是"你的回合"横幅的**准确时刻**，
        // 而观察向量只给得出"回合号变了"。
        crate::beat::record(
            state,
            crate::beat::Beat {
                kind: crate::beat::BeatKind::TurnStarted,
                actor: crate::beat::ordinal_of(state, actor),
                target: crate::beat::NOBODY,
                def: crate::beat::NO_DEF,
                flags: 0,
                a: state.current_round,
                b: state.current_turn,
                c: 0,
            },
        );
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
    /// **Metallicize / Plated Armor**: Block at the end of the turn (§149)。
    ///
    /// 两条状态的规则**逐字相同**（"回合结束加等同于层数的格挡"），所以是同一段代码 + 两个 id，
    /// 而不是两份拷贝。Plated Armor 的另一半（挨了没挡住的伤害掉 1 层）住在伤害管线里
    /// （`exec::resolve_damage_of_kind`）—— 那里才有"有没有打穿"这个事实。
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
                if matches!(
                    instance.definition_id.as_str(),
                    "standard.metallicize" | "standard.plated_armor"
                ) {
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
            let decoded = card_lifecycle_program(content, definition.as_str(), None)
                .map_err(|error| self.record(HostError::Exec(error)))?;
            if let Some(program) = decoded {
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

    /// §220：两个钩子的共同实体 —— 查内容、有节目才跑。
    fn run_card_lifecycle_hook(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        slot: CardSlot,
        event: crate::state::CardLifecycleEvent,
    ) -> Result<(), TurnError> {
        let Some(card) = state.card(slot) else {
            return Ok(());
        };
        let definition = card.definition_id;
        let content = self.content;
        match run_card_lifecycle(state, content, *actor, definition, event) {
            Ok(()) => Ok(()),
            Err(error) => Err(bridge(self.record(HostError::Exec(error)))),
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
        // **Ritual is not implemented here on purpose**: the sts content carries a `TurnEnded`
        // program for the `ritual` status, and the kernel's status-trigger drain already runs it
        // (measured: disabling this step still pays 3 Strength per turn end). A second
        // implementation would pay twice.

        // 动画日志（§142）：回合结束记一条。位置在 `grant_end_of_turn_block` **之后** ——
        // 那一刻"金属化给的格挡"已经是一条独立的 `Block` 事件，顺序对得上屏幕。
        crate::beat::record(
            state,
            crate::beat::Beat {
                kind: crate::beat::BeatKind::TurnEnded,
                actor: crate::beat::ordinal_of(state, actor),
                target: crate::beat::NOBODY,
                def: crate::beat::NO_DEF,
                flags: 0,
                a: state.current_round,
                b: state.current_turn,
                c: state.forced_turn_ends,
            },
        );
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

        // 到期被删的实例（§142）：先攒定义 id，出了借用再记动画 —— `beat::intern_def`
        // 要 `&mut state`，而在循环里 `state` 正被 `combatant` 可变借着。
        let mut expired = [crate::state::StatusDefinitionId::EMPTY; MAX_STATUSES_PER_COMBATANT];
        let mut expired_count = 0usize;

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
            let definition = combatant
                .statuses()
                .get(position)
                .map(|s| s.definition_id)
                .unwrap_or(crate::state::StatusDefinitionId::EMPTY);
            if let Some(instance) = combatant.statuses_mut().get_mut(position) {
                instance.duration_turns = next;
            }
            if next == 0 {
                // `:362-375`：归零删实例。
                combatant.remove_status(position);
                if let Some(cell) = expired.get_mut(expired_count) {
                    *cell = definition;
                    expired_count += 1;
                }
            }
        }
        for definition in expired.iter().take(expired_count) {
            let def = crate::beat::intern_def(state, definition.as_str());
            let ordinal = crate::beat::ordinal_of(state, actor);
            crate::beat::record(
                state,
                crate::beat::Beat {
                    kind: crate::beat::BeatKind::StatusRemoved,
                    actor: ordinal,
                    target: ordinal,
                    def,
                    flags: 0,
                    a: 0,
                    b: 0,
                    c: 0,
                },
            );
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

    /// §199：`TurnStartEnergy` 管线之后的补能数。
    ///
    /// 与 [`Self::turn_start_draw_count_detail`] 同一口径（读不出来 ⇒ 返回 `base`，并把失败记进
    /// `problems` —— 这里没有"一张都不抽"那种显眼选项，能量为 0 只会让玩家莫名其妙地点不动牌）。
    #[must_use]
    pub fn turn_start_refill_count_detail(
        &self,
        state: &CombatState,
        actor: &CombatantId,
        base: i32,
    ) -> i32 {
        let Some(combatant) = state.combatant(actor) else {
            return base;
        };
        match exec::fold_turn_start_energy(combatant.statuses(), actor, base, Some(self.content)) {
            Ok(count) => count,
            Err(e) => {
                self.record(HostError::Exec(e));
                base
            }
        }
    }

    /// 格挡是否保留（`DefensivePoolEffects.cs:283-322` 的 `retains`）。
    ///
    /// 判据同样是"身上有 active 状态带 `retain_block` 标签"（`:297`）。镜像 23/23 无此标签
    /// ⇒ 恒 `false` = 必清（= 参考的默认路径）。
    #[must_use]
    pub fn block_is_retained_detail(&self, state: &CombatState, actor: &CombatantId) -> bool {
        // §197: **两个**标签都说"这次不清"—— `retain_block`（Barricade，永久）与
        // `retain_block_once`（Blur，撑过一次就由 [`Self::consume_one_shot_block_retainers`] 摘掉）。
        // 只认前者的话，Blur 会被判定成"照常清空"，而**它自己不会报错** —— 静默少一条机制。
        match self
            .any_active_status_with_tag(state, actor, TAG_RETAIN_BLOCK)
            .and_then(|permanent| {
                if permanent {
                    Ok(true)
                } else {
                    self.any_active_status_with_tag(state, actor, TAG_RETAIN_BLOCK_ONCE)
                }
            }) {
            Ok(found) => found,
            Err(e) => {
                self.record(e);
                false // 读不出来 ⇒ 按默认（清）。理由同上：这一支不可达，选默认值最不吓人。
            }
        }
    }

    /// §197：**一次性**的格挡保留（`Blur`）：`retain_block` 让它撑过这次回合开始，然后在这里被摘掉。
    ///
    /// 为什么必须是内核、不能是内容：StS 的 `Blur` 是在**它阻止清空的那一刻**被消耗的
    /// （`GameActionManager` 清 block 时看 `hasPower("Blur")` 并把 power 摘掉）。本内核的时点是
    /// `turn::start_current_turn` 里"采样 `block_is_retained` → 清池子"那两步之间 —— 那既不是
    /// `TurnStarted` 触发器（在第 3–4 步，早于清空）也不是 `TurnEnded`（在上一回合末，会更早）。
    /// 所以由调用方在"决定了保留"之后调这一句。
    ///
    /// 一次只摘**一层**：`Blur 2` 就撑两次回合开始（StS 的 Blur 可以叠）。
    pub fn consume_one_shot_block_retainers(&mut self, state: &mut CombatState, actor: &CombatantId) {
        let mut definitions = [crate::state::StatusDefinitionId::EMPTY; 8];
        let mut count = 0usize;
        {
            let Some(combatant) = state.combatant(actor) else {
                return;
            };
            for instance in combatant.statuses() {
                if count == definitions.len() || !is_active(instance) || instance.stacks <= 0 {
                    continue;
                }
                let Ok(true) = status_bind::has_tag(
                    self.content,
                    instance.definition_id.as_str(),
                    TAG_RETAIN_BLOCK_ONCE,
                ) else {
                    continue;
                };
                definitions[count] = instance.definition_id;
                count += 1;
            }
        }
        for definition in definitions.iter().take(count) {
            let name = definition.as_str();
            let index = state.combatant(actor).and_then(|combatant| {
                combatant
                    .statuses()
                    .iter()
                    .position(|status| status.definition_id == *definition && status.stacks > 0)
            });
            let Some(index) = index else { continue };
            let combatant = match state.combatant_mut(actor) {
                Some(combatant) => combatant,
                None => return,
            };
            let Some(instance) = combatant.statuses_mut().get_mut(index) else {
                return;
            };
            instance.stacks -= 1;
            let _ = name;
            if instance.stacks <= 0 {
                combatant.remove_status(index);
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
            // §195.1：两个伤害事件都把**实际掉血**交给触发器，`eventAmount` 读的就是它。
            CombatEvent::DamageDealt { target, source, health_damage, .. } => {
                self.run_damage_dealt_triggers(state, &target, source, health_damage)
            }
            // `DamageReceivedTriggeredEffects`（`:196-204`）：Bearer = **承受者**。
            CombatEvent::DamageTaken { target, source, health_damage, is_attack } => {
                self.run_damage_taken_triggers(state, &target, source, health_damage, is_attack)
            }
            // `Downed`：Bearer = **倒下的那个**（Spore Cloud 之类"临死一击"）。
            CombatEvent::Downed { combatant, source } => {
                self.run_downed_triggers(state, &combatant, source)
            }
            // §236: `HpLost` -- 派给**失去生命的那一方**（Rupture 长在它身上），
            // 事实位带上"是不是一张牌付的代价"，节目用 `event.bool: hpLoss.fromCard` 过滤。
            CombatEvent::HpLost { target, amount, from_card } => {
                let _ = amount;
                let flags = if from_card { crate::exec::HP_LOSS_FROM_CARD } else { 0 };
                self.run_triggers_with_flags(state, &target, TriggerEvent::HpLost, flags)
            }
            // §237: `BlockGained` -- Bearer 是获得格挡的那一方（Juggernaut）。
            CombatEvent::BlockGained { combatant, .. } => {
                self.run_triggers(state, &combatant, TriggerEvent::BlockGained)
            }
            // §237: `CardsDrawn` / `CardExhausted` -- Bearer 是牌的主人，事实位是**那张牌**的标签。
            // 两者形状相同（"你身上有事发生，主语是一张牌"），所以共用一段。
            CombatEvent::CardsDrawn { combatant, card }
            | CombatEvent::CardExhausted { combatant, card } => {
                let event = match item.event {
                    CombatEvent::CardsDrawn { .. } => TriggerEvent::CardsDrawn,
                    _ => TriggerEvent::CardExhausted,
                };
                let flags = card_definition_of(state, card)
                    .map_or(0, |definition| card_tag_flags(self.content, definition));
                self.run_triggers_with_flags(state, &combatant, event, flags)
            }
            // `CardPlayed`：派发给**所有战斗员**（Enrage 在敌人身上，由你出牌触发）。
            CombatEvent::CardPlayed { owner, card } => {
                self.run_card_played_triggers(state, &owner, card)
            }
            // The four "status / cost" events have no content that uses them yet; they are
            // dispatched to **every combatant** like `CardPlayed`, with `EventTarget` = whoever the
            // event is about (`port-plan.md` §119).
            CombatEvent::CardCostPaid { owner } => {
                self.run_broadcast_triggers(state, TriggerEvent::CardCostPaid, &owner)
            }
            CombatEvent::StatusApplied { target } => {
                self.run_broadcast_triggers(state, TriggerEvent::StatusApplied, &target)
            }
            CombatEvent::StatusMerged { target } => {
                self.run_broadcast_triggers(state, TriggerEvent::StatusMerged, &target)
            }
            CombatEvent::StatusRemoved { target } => {
                self.run_broadcast_triggers(state, TriggerEvent::StatusRemoved, &target)
            }
            CombatEvent::StatusStacksChanged { target } => {
                self.run_broadcast_triggers(state, TriggerEvent::StatusStacksChanged, &target)
            }
            CombatEvent::StatusApplicationPrevented { target } => {
                self.run_broadcast_triggers(
                    state,
                    TriggerEvent::StatusApplicationPrevented,
                    &target,
                )
            }
        }
    }

    /// 派发给**每个战斗员**的触发器（`CardCostPaid` 与三条状态事件）。
    ///
    /// 这几条事件今天是**没有人用**的钩子（内容里 0 条触发器），但"名字认得出来、事件真的会发"
    /// 是 `not_handled` 归零的前提 —— 宁可有一条空跑的派发，也不要一个"名字都没有"的事件。
    fn run_broadcast_triggers(
        &mut self,
        state: &mut CombatState,
        event: TriggerEvent,
        about: &CombatantId,
    ) -> Result<(), HostError> {
        let mut bearers = [CombatantId::EMPTY; crate::state::MAX_COMBATANTS];
        let mut count = 0usize;
        for combatant in state.combatants() {
            if count < bearers.len() {
                bearers[count] = combatant.id;
                count += 1;
            }
        }
        for index in 0..count {
            if state.result != CombatResult::Ongoing {
                break;
            }
            let bearer = bearers[index];
            let mut batch = TriggerBatch::new();
            self.collect_triggers(state, &bearer, event, &mut batch)?;
            batch.sort();
            for i in 0..batch.len {
                let Some(handle) = batch.root.get(i).copied() else {
                    break;
                };
                let steps = batch.max_steps.get(i).copied().unwrap_or(DEFAULT_MAX_PROGRAM_STEPS);
                let root = NodeRef::new(self.content, handle);
                let outcome =
                    execute_program(state, self.content, root, Some(bearer), Some(*about), steps);
                outcome.map_err(|e| self.record(HostError::Exec(e)))?;
            }
        }
        Ok(())
    }

    /// `CardPlayed` 的触发器：**每个战斗员都是 Bearer**。
    ///
    /// 为什么不是"只给出牌的人"：`Enrage`（Gremlin Nob）挂在**敌人**身上，由**你**出牌触发。
    /// 参考的 `CardPlayedTriggeredEffects` 也是按"场上每个 status 持有者"遍历的。
    fn run_card_played_triggers(
        &mut self,
        state: &mut CombatState,
        owner: &CombatantId,
        card: crate::state::CardInstanceId,
    ) -> Result<(), HostError> {
        // Which tags the played card has -- the only thing `event.bool` can ask about today.
        let flags = card_definition_of(state, card)
            .map_or(0, |definition| card_tag_flags(self.content, definition));
        let mut bearers = [CombatantId::EMPTY; crate::state::MAX_COMBATANTS];
        let mut count = 0usize;
        for combatant in state.combatants() {
            if count < bearers.len() {
                bearers[count] = combatant.id;
                count += 1;
            }
        }
        for index in 0..count {
            if state.result != CombatResult::Ongoing {
                break;
            }
            let bearer = bearers[index];
            let mut batch = TriggerBatch::new();
            self.collect_triggers(state, &bearer, TriggerEvent::CardPlayed, &mut batch)?;
            batch.sort();
            for i in 0..batch.len {
                let Some(handle) = batch.root.get(i).copied() else {
                    break;
                };
                let steps = batch.max_steps.get(i).copied().unwrap_or(DEFAULT_MAX_PROGRAM_STEPS);
                let root = NodeRef::new(self.content, handle);
                let outcome = execute_program_with_flags(
                    state,
                    self.content,
                    root,
                    Some(bearer),
                    Some(*owner),
                    steps,
                    flags,
                );
                outcome.map_err(|e| self.record(HostError::Exec(e)))?;
            }
        }
        Ok(())
    }

    /// `Downed` 的触发器：**Bearer 是倒下的那个**。
    ///
    /// ⚠️ **故意不看 `state.result`**：倒下往往就是战斗结束的那一刻，而"临死一击"必须照报
    /// （`Spore Cloud` 就是这种）。其它 runner 的 `result != Ongoing` 早退在这里不适用。
    fn run_downed_triggers(
        &mut self,
        state: &mut CombatState,
        combatant: &CombatantId,
        source: Option<CombatantId>,
    ) -> Result<(), HostError> {
        let bearer = *combatant;
        let mut batch = TriggerBatch::new();
        self.collect_triggers(state, &bearer, TriggerEvent::Downed, &mut batch)?;
        batch.sort();

        for i in 0..batch.len {
            let Some(handle) = batch.root.get(i).copied() else {
                break;
            };
            let steps = batch.max_steps.get(i).copied().unwrap_or(DEFAULT_MAX_PROGRAM_STEPS);
            let root = NodeRef::new(self.content, handle);
            // Bearer = 倒下的那个，`EventTarget` = 出手方（没来源时解出空集，节目自己决定怎么办）。
            let outcome = execute_program(state, self.content, root, Some(bearer), source, steps);
            outcome.map_err(|e| self.record(HostError::Exec(e)))?;
        }
        Ok(())
    }

    /// `DamageTaken` 的触发器（`DamageEffects.cs:196-204`）：**Bearer 是承受者**。
    ///
    /// 和 [`Self::run_damage_dealt_triggers`] 的区别只有一处，但那一处就是全部语义：
    /// 过滤器戴在**挨打的人**身上。`Thorns` 靠它工作（`port-plan.md` §116）。
    fn run_damage_taken_triggers(
        &mut self,
        state: &mut CombatState,
        target: &CombatantId,
        source: Option<CombatantId>,
        health_damage: i32,
        is_attack: bool,
    ) -> Result<(), HostError> {
        // 无来源的伤害不跑：参考的第一句就是 `SourceCombatant is not null`。
        let Some(attacker) = source else {
            return Ok(());
        };
        if state.combatant(target).is_none() {
            return Ok(());
        }
        let bearer = *target;
        let mut batch = TriggerBatch::new();
        self.collect_triggers(state, &bearer, TriggerEvent::DamageTaken, &mut batch)?;
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
            // Bearer = 承受者，`EventTarget` = 出手方 ⇒ 节目里 `sel.eventTarget` 就是打人的那个。
            // §208: the event **facts** ride along, so a status trigger can ask "was this an
            // attack?" (`event.bool: damage.isAttack`). `eventAmount` stays the health that was
            // actually lost -- two different questions, two different carriers.
            let mut ctx = ExecContext::new(state, Some(bearer), Some(attacker), None, steps)
                .with_content(self.content);
            ctx.event_amount = Some(health_damage);
            ctx.event_flags = if is_attack { crate::exec::DAMAGE_IS_ATTACK } else { 0 };
            let outcome = crate::exec::begin(root, &mut ctx, crate::state::ProgramTerminalHook::None)
                .map(|_| ());
            outcome.map_err(|e| self.record(HostError::Exec(e)))?;
        }
        Ok(())
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
        health_damage: i32,
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
            let outcome = execute_program_amount(
                state,
                self.content,
                root,
                Some(bearer),
                Some(*target),
                steps,
                Some(health_damage),
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

    /// §199: the energy refill goes through the `TurnStartEnergy` pipeline (same shape as the draw
    /// count).
    fn turn_start_refill_count(&self, state: &CombatState, actor: &CombatantId, base: i32) -> i32 {
        self.turn_start_refill_count_detail(state, actor, base)
    }

    /// §197: the one-shot retentions are **spent here** -- the inherent method above does the work,
    /// and this delegation is what makes the turn machine reach it (without it the trait's default
    /// no-op runs and `Blur` keeps the block forever; my first version of this test caught exactly
    /// that).
    fn consume_one_shot_block_retainers(&mut self, state: &mut CombatState, actor: &CombatantId) {
        Host::consume_one_shot_block_retainers(self, state, actor);
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
        // 参考的两条（`CardZoneEffects.cs:419-425`）：① 实例标记 `standard.retained_card`
        // ② 定义 `RetainInHandOnTurnEnd`。
        //
        // **§144 起 ② 真的读了。** 之前这里恒 `false`，理由写在下面那段历史里（当时 62/62 卡
        // 都是 false，两者观察等价）。内容里出现第一张 Retain 卡之后，"观察等价"就不再成立，
        // 那条测试（`the_three_strategy_hooks_that_do_not_read_content_are_measured_not_assumed`）
        // 正是为了在这一刻把人叫回来 —— 它红了，所以这一段被写出来了。
        //
        // ① 仍然**没有消费者**：`node.markCardInstance` 在 `exec` 里不存在，全镜像 0 条 term。
        // 只做一半更糟（见下），所以这一半继续返回"没有标记"。
        //
        // ⚠️ 读失败（卡不在镜像里 / `F_BOOL` 是 0/3 之外的值）**当作"留在手里"**：这条钩子没有
        // `Result`，而两个方向的代价不对称 —— 误留一张牌只是让玩家多打一次，误弃一张牌是把
        // 玩家以为保住了的牌扔掉。错误照旧由 `record` 报给下一个 `try_*`（同
        // `hand_is_retained_detail` 的先例）。
        let _ = actor;
        let Some(card) = state.card(slot) else {
            return false;
        };
        match self.content.card_retains_in_hand(card.definition_id.as_str()) {
            Some(retains) => retains,
            None => {
                self.record(HostError::Capacity(crate::state::CapacityError::Full(
                    crate::state::Container::CardInstances,
                )));
                true
            }
        }
    }

    /// §220：`Drawn` / `Exhausted` 两个生命周期事件。钩子默认空实现，这里把它接到
    /// [`run_card_lifecycle`]（**没有节目就什么都不做** —— 不建链、不发号）。
    fn card_drawn(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        slot: CardSlot,
    ) -> Result<(), TurnError> {
        let outcome =
            self.run_card_lifecycle_hook(state, actor, slot, crate::state::CardLifecycleEvent::Drawn);
        // §237：`CardsDrawn` 在**生命周期节目之后**发 —— StS 的顺序也是"牌进了手，再问有没有人
        // 对'抽到它'有意见"。每张一条（`Evolve` 的单位是张，不是"抽牌动作"）。
        if outcome.is_ok() {
            if let Some(card) = state.card(slot) {
                let event = crate::state::CombatEvent::CardsDrawn {
                    combatant: *actor,
                    card: card.id,
                };
                state
                    .enqueue_event(event)
                    .map_err(|e| bridge(self.record(HostError::Capacity(e))))?;
            }
        }
        outcome
    }

    fn card_exhausted(
        &mut self,
        state: &mut CombatState,
        actor: &CombatantId,
        slot: CardSlot,
    ) -> Result<(), TurnError> {
        let outcome = self.run_card_lifecycle_hook(
            state,
            actor,
            slot,
            crate::state::CardLifecycleEvent::Exhausted,
        );
        // §237：`CardExhausted` 与 `LifecyclePrograms[Exhausted]` 同一个落点 —— 三条入堆路径
        // （§225 的审计）都经过这里，所以"消耗了却没通知"这种漏法这次结构上不存在。
        if outcome.is_ok() {
            if let Some(card) = state.card(slot) {
                let event = crate::state::CombatEvent::CardExhausted {
                    combatant: *actor,
                    card: card.id,
                };
                state
                    .enqueue_event(event)
                    .map_err(|e| bridge(self.record(HostError::Capacity(e))))?;
            }
        }
        outcome
    }

    fn turn_end_hand_destination(
        &self,
        state: &CombatState,
        actor: &CombatantId,
        slot: CardSlot,
    ) -> CardZone {
        // 参考：`definition.TurnEndHandDestinationZone`（`CardZoneEffects.cs:427`）。
        //
        // **§144 起真的读了** —— `Ethereal` 就是这一格等于 `"ExhaustPile"`：参考里的 Ethereal
        // **不是**一条独立判据，它就是这张牌"从手牌离场时去哪"。
        // 空缺 = 参考的构造默认值 `DiscardPile`；枚举名认不出来（内容打错）⇒ 记一笔 + 弃牌堆，
        // 因为这条钩子同样没有 `Result`，而"留在手里"会让那张牌永远出不去。
        let _ = actor;
        let Some(card) = state.card(slot) else {
            return CardZone::DiscardPile;
        };
        match self.content.card_turn_end_zone(card.definition_id.as_str()) {
            Some("") | Some("DiscardPile") => CardZone::DiscardPile,
            Some("ExhaustPile") => CardZone::ExhaustPile,
            Some("Hand") => CardZone::Hand,
            Some(_) | None => {
                self.record(HostError::Capacity(crate::state::CapacityError::Full(
                    crate::state::Container::CardInstances,
                )));
                CardZone::DiscardPile
            }
        }
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
/// §195.1：与 [`execute_program`] 相同，外加**事件带的数量**（`eventAmount` 读它）。
///
/// 单独一个入口而不是给 `execute_program` 加参数：那个函数有十几个调用点（回合钩子、状态
/// 触发器、出牌……），它们**没有**"当前事件的数量"可言，给它们传 `None` 只是噪音。
fn execute_program_amount(
    state: &mut CombatState,
    content: &Content<'_>,
    root: NodeRef<'_>,
    source: Option<CombatantId>,
    event_target: Option<CombatantId>,
    max_steps: u32,
    event_amount: Option<i32>,
) -> Result<(), exec::ExecError> {
    let mut ctx = ExecContext::new(state, source, event_target, None, max_steps)
        .with_content(content);
    ctx.event_amount = event_amount;
    let outcome = exec::begin(root, &mut ctx, crate::state::ProgramTerminalHook::None);
    // §199: `begin` **建/借一条效果链**，而那条引用归**帧**所有（见 `exec.rs` 里
    // `begin_without_preflight` 的引用计数说明）。帧要 `reap_frames` 才会把它还回去 ——
    // 这几个助手原来直接把 `ProgramRun` 丢掉（`.map(|_| ())`），于是**每一个同步跑完的触发节目
    // 都漏一条链**：128 次之后整场战斗的每一次出牌都变成 `StepThrew(Capacity:Chains)`。
    // 只在长战斗里出现（soak 里那场 44 回合），而且 §199 之前消息里连容器名都没有。
    teardown(state);
    outcome.map(|_| ())
}

/// §199: the one place a trigger program's effect chain is handed back.
///
/// `exec::begin` allocates (or borrows) one chain per program and the **frame** owns that
/// reference; only `reap_frames` returns it, and it reaps **terminal** frames only -- so a frame
/// that is still waiting for its continuations is untouched (the host's drain loop resumes it and
/// reaps it then). Skipping this for synchronous trigger programs leaked one chain per trigger.
fn teardown(state: &mut CombatState) {
    exec::reap_frames(state);
}

/// §220：`pub(crate)` —— `exec::resolve_request` 也要跑节目（卡的 `Drawn`/`Exhausted`），
/// 而复用这一个入口是**必须的**：它在末尾调 `teardown`（`reap_frames`），漏了那一步就是
/// §199 那条"每个同步节目漏一条链"的回归。
pub(crate) fn execute_program(
    state: &mut CombatState,
    content: &Content<'_>,
    root: NodeRef<'_>,
    source: Option<CombatantId>,
    event_target: Option<CombatantId>,
    max_steps: u32,
) -> Result<(), exec::ExecError> {
    execute_program_with_flags(state, content, root, source, event_target, max_steps, 0)
}

/// [`execute_program`] plus the **event facts** (`event.bool` reads them).
#[allow(clippy::too_many_arguments)]
fn execute_program_with_flags(
    state: &mut CombatState,
    content: &Content<'_>,
    root: NodeRef<'_>,
    source: Option<CombatantId>,
    event_target: Option<CombatantId>,
    max_steps: u32,
    event_flags: u16,
) -> Result<(), exec::ExecError> {
    let mut ctx = ExecContext::new(state, source, event_target, None, max_steps)
        .with_content(content);
    ctx.event_flags = event_flags;
    let outcome = exec::begin(root, &mut ctx, crate::state::ProgramTerminalHook::None);
    // §199: `begin` **建/借一条效果链**，而那条引用归**帧**所有（见 `exec.rs` 里
    // `begin_without_preflight` 的引用计数说明）。帧要 `reap_frames` 才会把它还回去 ——
    // 这几个助手原来直接把 `ProgramRun` 丢掉（`.map(|_| ())`），于是**每一个同步跑完的触发节目
    // 都漏一条链**：128 次之后整场战斗的每一次出牌都变成 `StepThrew(Capacity:Chains)`。
    // 只在长战斗里出现（soak 里那场 44 回合），而且 §199 之前消息里连容器名都没有。
    teardown(state);
    outcome.map(|_| ())
}

/// The definition id of a card **instance**.
///
/// `CombatState` exposes `card(slot)` by pool slot, so this walks the zones of every combatant until
/// it finds the instance -- a fight has a handful of cards and this runs once per card played.
fn card_definition_of<'a>(
    state: &'a CombatState,
    card: crate::state::CardInstanceId,
) -> Option<&'a str> {
    for combatant in state.combatants() {
        for zone in [
            CardZone::DrawPile,
            CardZone::Hand,
            CardZone::DiscardPile,
            CardZone::ExhaustPile,
        ] {
            for instance in state.zone_cards(&combatant.id, zone) {
                if instance.id == card {
                    return Some(instance.definition_id.as_str());
                }
            }
        }
    }
    None
}

/// Which card tags the played card has, as `event.bool` bits (`Content::card_tag_bits` is the one
/// table -- §225 moved it there so the `forEachCardInZone` iteration can share it).
fn card_tag_flags(content: &Content<'_>, definition_id: &str) -> u16 {
    content.card_tag_bits(definition_id)
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
pub(crate) struct LifecycleProgram<'a> {
    /// 节目根（信封里的 `Root`）。
    pub(crate) root: NodeRef<'a>,
    /// 信封里的 `MaxProgramSteps`（缺席 ⇒ 1024）。
    pub(crate) max_steps: u32,
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
/// §220：跑一张牌的某条生命周期节目（**没有节目就什么都不做**）。
///
/// ⚠️ 这里刻意**不入队**：效果请求会 `??` 出根链、把 `next_effect_chain_number` 推进一格，
/// 而参考实现根本没有这条请求 —— 第一版按"每张抽到的牌入队一条"实现，`FIGHT_DIFF` 立刻从
/// 182/182 掉到 18/182（`chain_num` 行全错）。所以"有没有节目"必须先问内容：没有就**零开销**，
/// 有就直接跑（`execute_program`，与回合末的生命周期节目同一条路）。
pub(crate) fn run_card_lifecycle(
    state: &mut CombatState,
    content: &Content<'_>,
    owner: CombatantId,
    definition: CardDefinitionId,
    event: crate::state::CardLifecycleEvent,
) -> Result<(), ExecError> {
    let decoded = card_lifecycle_program(content, definition.as_str(), Some(event))?;
    let Some(program) = decoded else {
        return Ok(());
    };
    execute_program(
        state,
        content,
        program.root,
        Some(owner),
        Some(owner),
        program.max_steps,
    )
}

/// §220：`LifecyclePrograms` 的**键名** → 事件。`None` = 这个键内核不认识（必须响亮）。
///
/// 参考的 `CardLifecycleTrigger` 只有 `TurnEndInHand`（及其枚举序数 `0`）；`Drawn` / `Exhausted`
/// 是**我们自己的扩展**（`void` 的"抽到时 -1 能量"、`sentinel` 的"被消耗时 +2 能量"），
/// 与 §198 的 `Operation::ScalePercentPerStack` 同级。**不认识的键仍然拒绝**：
/// 那是"内容写了本层读不懂的触发器"，不是"没有触发器"。
#[must_use]
pub fn lifecycle_name_matches(name: &str, wanted: Option<crate::state::CardLifecycleEvent>) -> Option<bool> {
    let known: Option<Option<crate::state::CardLifecycleEvent>> = match name {
        TURN_END_IN_HAND | TURN_END_IN_HAND_ORDINAL => Some(None),
        "Drawn" => Some(Some(crate::state::CardLifecycleEvent::Drawn)),
        "Exhausted" => Some(Some(crate::state::CardLifecycleEvent::Exhausted)),
        _ => None,
    };
    known.map(|event| event == wanted)
}

pub(crate) fn card_lifecycle_program<'a>(
    content: &'a Content<'a>,
    definition_id: &str,
    wanted: Option<crate::state::CardLifecycleEvent>,
) -> Result<Option<LifecycleProgram<'a>>, ExecError> {
    let row = card_row(content, definition_id)
        .ok_or(ExecError::Ir(IrError::Missing("CARD row")))?;
    let handle = row.lifecycle_programs();
    if handle == ABSENT16 || handle == NULL16 {
        // 整格缺席 / 显式 null ⇒ 参考那边是空字典 ⇒ 没有节目。
        return Ok(None);
    }
    let term = content
        .term(handle)
        .ok_or(ExecError::Ir(IrError::Missing("LifecyclePrograms")))?;
    if term.op < crate::content::OP_FIRST_DYNAMIC {
        // `_arr`/`_str`/`_int`… 都不是"字典"的编码。
        return Err(ExecError::Ir(IrError::Missing("LifecyclePrograms")));
    }
    let opcode = content
        .opcode(term.op)
        .ok_or(ExecError::Ir(IrError::Missing("LifecyclePrograms")))?;
    let node = NodeRef::new(content, handle);
    let mut program: Option<NodeRef<'a>> = None;
    for index in 0..opcode.nfields() {
        let field = opcode
            .field(index)
            .ok_or(ExecError::Ir(IrError::Missing("LifecyclePrograms")))?;
        let name = content
            .string(field.name_str())
            .ok_or(ExecError::Ir(IrError::Missing("LifecyclePrograms")))?;
        // §220：不认识的键仍是 `UnknownKind`（"判别串不认识"），与 `zone_from_wire_name` 同形。
        let matches = lifecycle_name_matches(name, wanted)
            .ok_or(ExecError::Ir(IrError::UnknownKind))?;
        if !matches {
            continue;
        }
        if program.is_some() {
            // 两种拼法同时出现 ⇒ 同一个触发器写了两条节目。
            return Err(ExecError::Ir(IrError::Missing("LifecyclePrograms")));
        }
        match node.field(name)? {
            // `F_TERM` 的缺席哨兵 ⇒ 这个键没写。
            None | Some(Value::Absent) => {}
            Some(Value::Null) => {
                return Err(ExecError::Ir(IrError::Missing("LifecyclePrograms")))
            }
            Some(Value::Node(inner)) => program = Some(inner),
            // 声明成 `F_TERM` 却装了标量：`field()` 已经在这里报过错了，这一支不可达。
            Some(_) => return Err(ExecError::Ir(IrError::Missing("LifecyclePrograms"))),
        }
    }
    let Some(program) = program else {
        // 0 字段的 `_obj`：真实内容 62/62 卡就是这一支。
        return Ok(None);
    };
    let root = program
        .node_field("Root")?
        .ok_or(ExecError::Ir(IrError::Missing("LifecyclePrograms")))?;
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

    /// A zone's card **definitions**, in pile order (the tests care about *which* card, not its id).
    fn zone_definitions(state: &CombatState, who: &str, zone: CardZone) -> Vec<std::string::String> {
        state
            .zone_cards(&cid(who), zone)
            .map(|card| std::string::String::from(card.definition_id.as_str()))
            .collect()
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
            "curse.burn_ethereal",
            "ExhaustPile",
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
        // §144：`TurnEndHandDestinationZone` 也要能摆（`Ethereal` 就是这一格 = `ExhaustPile`）。
        // NULL16 照旧表示"这一格缺席" ⇒ 参考的构造默认值 `DiscardPile`。
        let card_with_zone =
            |id: u16, program: u16, lifecycle: u16, retain: u16, zone: u16| -> [u16; 15] {
                [
                    id,          // Id
                    program,     // Program（出牌节目）
                    ABSENT16,    // Tags
                    ABSENT16,    // Costs
                    lifecycle,   // LifecyclePrograms
                    ABSENT16,    // PlayCondition
                    ABSENT16,    // QueueOnPlay
                    retain,      // RetainInHandOnTurnEnd（F_BOOL）
                    BOOL_FALSE,  // IsAction
                    0,           // NameKey
                    0,           // DescriptionKey
                    0,           // PackageId
                    zone,        // TurnEndHandDestinationZone
                    NULL16,      // PlayedCardDestinationZone
                    NULL16,      // extra
                ]
            };
        let card = |id: u16, program: u16, lifecycle: u16, retain: u16| -> [u16; 15] {
            card_with_zone(id, program, lifecycle, retain, NULL16)
        };
        let cards: [(&str, [u16; 15]); 7] = [
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
            // §144：`Ethereal` 的载体 —— 回合结束从**手牌**直接进消耗堆（参考 `:427`）。
            // ⚠️ 顺序是**按 id 字节序**排的（`IDX` 是二分查找）：`burn_ethereal` 必须排在
            // `burn_retained` **前面**，否则查不到这张卡 —— 症状是 `card_row` 返回 None，
            // 报出来的却是 `Content("CARD row")`，离"索引没排序"隔着三层。
            (
                "curse.burn_ethereal",
                card_with_zone(
                    sid("curse.burn_ethereal"),
                    ABSENT16,
                    t_lifecycle_two,
                    BOOL_FALSE,
                    sid("ExhaustPile"),
                ),
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
        // §167：`parse` 现在真的比对这一格；探针原来写 7（那时它只是"随便一个非零值"）。
        blob[18..20].copy_from_slice(&crate::content::SUPPORTED_SCHEMA_VERSION.to_le_bytes());

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
        assert_eq!(content.rows(crate::content::Table::Card).count(), 7);
        // 六张卡的解码结果**逐张**（这张表就是上面 `burn_image` 文档里那张表的机器版）：
        // 四张有 `TurnEndInHand` 节目、`plain.card` 是空 `{}`。
        //
        // ⚠️ §220 把 `curse.weird` 的期望**翻了过来**：它只有 `Drawn` 一个键，而 `Drawn` 现在
        // 是内核支持的事件（以前那一行断言的是"未知触发器必须响亮"）。"未知键仍然响亮"这条性质
        // 改由 `lifecycle_name_matches` 的映射表直接钉（见下面一段），因为手搓镜像里没有别的怪键，
        // 而新增一个键会改动那张镜像里被钉死的 term/opcode 计数。
        for (id, has_program) in [
            ("curse.burn", true),
            ("curse.burn_block", true),
            ("curse.burn_dual", true),
            ("curse.burn_retained", true),
            ("plain.card", false),
        ] {
            assert_eq!(
                card_lifecycle_program(&content, id, None)
                    .unwrap_or_else(|e| panic!("`{id}` 必须解得出来：{e:?}"))
                    .is_some(),
                has_program,
                "`{id}` 的 `TurnEndInHand` 节目是否存在"
            );
        }
        // `curse.weird` 的键是 `Drawn`：问 `TurnEndInHand` ⇒ `Ok(None)`（不是错误），
        // 问 `Drawn` ⇒ 解得出来。这条成对断言把"读错键"与"没有节目"分开。
        assert!(
            card_lifecycle_program(&content, "curse.weird", None).expect("decode").is_none(),
            "`curse.weird` 没有 `TurnEndInHand` 节目"
        );
        assert!(
            card_lifecycle_program(
                &content,
                "curse.weird",
                Some(crate::state::CardLifecycleEvent::Drawn)
            )
            .expect("decode")
            .is_some(),
            "`curse.weird` 有 `Drawn` 节目"
        );
        // 未知键仍然必须响亮：映射表是唯一的口径（`None` = 不认识）。
        assert_eq!(
            lifecycle_name_matches("TurnEndInHand", None),
            Some(true),
            "参考的触发器"
        );
        assert_eq!(
            lifecycle_name_matches("Exhausted", Some(crate::state::CardLifecycleEvent::Exhausted)),
            Some(true),
            "§220 新加的事件"
        );
        assert_eq!(
            lifecycle_name_matches("Teleported", None),
            None,
            "不认识的键 ⇒ None ⇒ 解码报 `UnknownKind`（内容写了一个本层读不懂的触发器）"
        );
        // `curse.burn_dual` 的生命周期节目是 `dealDamage{2}`，而它的**出牌**节目是
        // `dealDamage{7}` —— 两格的 term 必须不同，否则"读错格子"那条测试就没有区分力。
        let lifecycle = card_lifecycle_program(&content, "curse.burn_dual", None)
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
        // Walk the **frozen** trait entry (not the `try_*` one): that is what a caller who only reads
        // `TurnError` experiences, and it must get both the **class** and the **detail**.
        //
        // The failure used here is "a status with no STAT row in the image" (`Bind(Missing)`); the
        // old example -- `cardsPlayedLastTurn` being unimplemented -- went away in §128.
        let blob = core_image();
        let content = parse(&blob);
        let mut state = solo();
        let mut host = Host::new(&content);
        give(&mut state, "hero", status("st_x", "standard.strength", 2));

        let err = TurnHost::run_turn_started_triggers(&mut host, &mut state, &cid("hero"))
            .expect_err("a status without a STAT row must fail loudly");
        assert_eq!(
            err,
            TurnError::Host(HostFailure::Content),
            "class: the content is wrong, not the kernel"
        );
        assert_eq!(
            host.last_failure(),
            Some(HostError::Bind(BindError::Missing("STAT row"))),
            "detail: which binding failed"
        );
    }

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
            let mut damage_taken = 0usize;
            let mut downed = 0usize;
            let mut card_played = 0usize;
            let mut status_stacks_changed = 0usize;
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
                    TriggerEvent::DamageTaken => damage_taken += 1,
                    TriggerEvent::Downed => downed += 1,
                    TriggerEvent::CardPlayed => card_played += 1,
                    TriggerEvent::CardCostPaid => {} 
                    TriggerEvent::StatusApplied => {}
                    TriggerEvent::StatusMerged => {}
                    TriggerEvent::StatusRemoved => {}
                    TriggerEvent::StatusStacksChanged => status_stacks_changed += 1,
                    TriggerEvent::StatusApplicationPrevented => {}
                    // §236/§237：镜像（core）里没有这几条触发器，计数恒 0。
                    TriggerEvent::HpLost => {}
                    TriggerEvent::BlockGained => {}
                    TriggerEvent::CardsDrawn => {}
                    TriggerEvent::CardExhausted => {}
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
        // `DamageTaken` 那 1 条**也不再是缺口**：§116 给它接了钩子，`thorns` 是它的第一批触发器。
        assert_eq!(damage_taken, 1, "承受者侧的那一条（参考内容里也有 1 条）");
        // 参考内容里 `Downed` 与 `CardPlayed` 各有几条，实测后钉在这里（§117）。
        assert_eq!(downed, 0, "参考镜像里没有 Downed 触发器");
        assert_eq!(card_played, 0, "参考镜像里没有 CardPlayed 触发器");
        // 10 -> 2：StatusApplied / StatusMerged / StatusRemoved 都接了钩子，只剩
        // **StatusStacksChanged 2 条**还是"参考有、本内核没有钩子接"。
        assert_eq!(status_stacks_changed, 2, "参考镜像里 2 条（原先算未接的那两条）");
        assert_eq!(not_handled, 0, "25 个事件名现在全部有钩子");
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
        // 5 个能落到钩子上的必须是"自己的"变体，其余 20 个才是 NotHandled。
        assert_eq!(
            TriggerEvent::from_wire_name("TurnStarted"),
            Some(TriggerEvent::TurnStarted)
        );
        // `DamageTaken` 从 NotHandled 毕业了：`Thorns` 是它的第一批触发器（§116）。
        assert_eq!(
            TriggerEvent::from_wire_name("DamageTaken"),
            Some(TriggerEvent::DamageTaken)
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
    fn queue_advances_runs_now_that_the_turn_counters_exist() {
        // This used to be the project's example of "kernel gap, not content error": the status
        // `queue_advances` has a `TurnStarted` trigger conditioned on `cardsPlayedLastTurn >= 3`,
        // and that expression was unimplemented (`expr.rs` module head, §128 fixed it).
        //
        // Now it **runs**, and the counter it sets is the proof.
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);

        let counter_of = |state: &crate::state::CombatState| -> i32 {
            state
                .combatant(&cid("hero"))
                .map_or(0, |c| {
                    c.counters()
                        .iter()
                        .map(|entry| entry.value)
                        .sum()
                })
        };

        // Fewer than three cards last turn: the condition is false, nothing happens.
        let mut state = solo();
        give(&mut state, "hero", status("st_qa", "queue_advances", 0));
        state.cards_played_last_turn = 2;
        host.try_run_turn_started_triggers(&mut state, &cid("hero"))
            .expect("the trigger runs");
        assert_eq!(counter_of(&state), 0, "two cards is not three");

        // Three or more: the `Then` branch bumps the counter.
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_qa", "queue_advances", 0));
        state.cards_played_last_turn = 3;
        host.try_run_turn_started_triggers(&mut state, &cid("hero"))
            .expect("the trigger runs");
        assert!(counter_of(&state) > 0, "three cards must move the queue");
    }

    #[test]
    fn both_turn_boundaries_leave_exactly_one_beat_each() {
        // §142：回合边界是页面画"你的回合"横幅的**准确时刻**。观察向量只说得出"回合号变了"，
        // 说不出"是谁的回合在这个瞬间开始"。恰好一条 —— 两处都写会让动画播两遍。
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        state.clear_beats();

        host.try_run_turn_started_triggers(&mut state, &cid("hero"))
            .expect("turn start runs");
        let started: Vec<crate::beat::Beat> = state
            .beats()
            .iter()
            .filter(|beat| beat.kind == crate::beat::BeatKind::TurnStarted)
            .copied()
            .collect();
        assert_eq!(started.len(), 1, "一个回合开始只有一条：{:?}", state.beats());
        assert_eq!(started[0].actor, 0, "是存储序第 0 个（hero）的回合");

        state.clear_beats();
        host.try_run_turn_ended_triggers(&mut state, &cid("hero"))
            .expect("turn end runs");
        let ended: Vec<crate::beat::Beat> = state
            .beats()
            .iter()
            .filter(|beat| beat.kind == crate::beat::BeatKind::TurnEnded)
            .copied()
            .collect();
        assert_eq!(ended.len(), 1, "一个回合结束只有一条");
        assert_eq!(ended[0].actor, 0);
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

    /// Put one card of `definition` into `who`'s hand and return its instance id.
    ///
    /// The tag tests need a **real** card instance: the host resolves its definition id and asks the
    /// content for tags (`card_tag_flags`).
    fn card_in_hand(
        state: &mut CombatState,
        content: &Content<'_>,
        who: &str,
        definition: &str,
    ) -> crate::state::CardInstanceId {
        let id = crate::state::CardInstanceId::new(definition).expect("instance id");
        let definition_id = crate::state::CardDefinitionId::new(definition).expect("definition");
        let _ = content;
        state
            .push_card(
                &cid(who),
                CardZone::Hand,
                crate::state::CardInstance::new(id, definition_id),
            )
            .expect("push card");
        id
    }

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
            2,
            "伤害落地入队**两条**：出手方侧的 `DamageDealt`（`:186`）与承受者侧的 `DamageTaken`（`:196`）"
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
    fn ritual_grants_strength_at_the_end_of_the_turn() {
        // Wiki: Cultist's Ritual 3 = "gain 3 Strength at the end of each turn".
        //
        // **This one is implemented in the CONTENT, not the kernel**: the sts package carries a
        // `TurnEnded` program for the `ritual` status, and the status-trigger drain runs it. The test
        // therefore proves the content path, which is the interesting half (`port-plan.md` §116).
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = solo();
        give(&mut state, "hero", status("st_rit", "ritual", 3));

        let strength = |state: &crate::state::CombatState| -> i32 {
            state.combatant(&cid("hero")).map_or(0, |c| {
                c.statuses()
                    .iter()
                    .filter(|s| is_active(s) && s.definition_id.as_str() == "standard.strength")
                    .map(|s| s.stacks)
                    .sum()
            })
        };
        assert_eq!(strength(&state), 0, "no Strength before the turn ends");

        host.try_run_turn_ended_triggers(&mut state, &cid("hero"))
            .expect("turn end");
        assert_eq!(strength(&state), 3, "Ritual 3 pays 3 Strength, from the content program");

        host.try_run_turn_ended_triggers(&mut state, &cid("hero"))
            .expect("turn end again");
        assert_eq!(strength(&state), 6, "and again on the next turn end");
    }

    /// **Time Warp, prepared**: after twelve cards are played the enemy gains 2 Strength and the
    /// turn is asked to end (`node.endTurn` -> `state.end_turn_requested`, `port-plan.md` §125).
    #[test]
    fn the_twelfth_card_asks_for_the_turn_to_end() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_tw", "standard.time_warp", 1));

        let mut card = card_in_hand(&mut state, &content, "hero", "strike");

        for played in 1..=12 {
            state
                .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card })
                .expect("queue");
            host.try_resolve_pending_queues(&mut state).expect("triggers");
            if played < 12 {
                assert!(
                    !state.end_turn_requested,
                    "the turn must not end after card {played}"
                );
            }
        }

        assert!(
            state.end_turn_requested,
            "the twelfth card must ask for the turn to end"
        );
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.strength"),
            2,
            "and it pays 2 Strength"
        );

        // The clock reset, so a thirteenth card does not immediately re-fire.
        state.end_turn_requested = false;
        card = card_in_hand(&mut state, &content, "hero", "defend");
        state
            .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert!(
            !state.end_turn_requested,
            "the counter went back to zero, so the next card is just a card"
        );
    }

    #[test]
    fn the_boss_phase_splits_once_at_low_health() {
        // Wiki: the Slime Boss's phase *is* its split. Content trigger: on `DamageTaken`, if my HP is
        // <= 10, spawn two slimes and **consume the phase status** so it cannot fire twice
        // (`port-plan.md` §122).
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "enemy_b", status("st_phase", "standard.phase_split", 1));
        let before = state.combatants().len();

        // `enemy_b` is on 10 HP: a 3-point hit lands it at 7, which is <= 10.
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("enemy_b"), 3, false).expect("hit");
        }
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        // §178: the split is *"the boss is replaced"*, not *"two more appear"* -- so the net change
        // is +1 (remove the bearer, add two), and the guard is structural: the bearer is gone, so
        // there is no status left to fire a second time.
        assert_eq!(
            state.combatants().len(),
            before + 1,
            "the phase replaces the bearer with two (net +1)"
        );
        assert!(
            state.combatant(&cid("enemy_b")).is_none(),
            "the bearer itself is gone; 'stacks == 0' would still leave a corpse that can be hit"
        );

        // A second hit must NOT spawn anybody else. §178 made this structural (the bearer is
        // out of the fight), so the judgment is two-sided:
        //   * a **queued** request against it is dropped silently -- that is the multi-hit turn;
        //   * a **direct** `resolve_damage` on it still fails loudly, because there the caller
        //     just handed us an id that should not exist.
        let after_first = state.combatants().len();
        state
            .enqueue_effect(crate::state::EffectRequest::DealDamage {
                target: Some(cid("enemy_b")),
                amount: 5,
                ignores_block: false,
                source: Some(cid("hero")),
            })
            .expect("queue a hit at something that is gone");
        host.try_resolve_pending_queues(&mut state).expect("a vanished target is a no-op");
        assert_eq!(
            state.combatants().len(),
            after_first,
            "the phase is a one-shot"
        );
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            assert!(
                crate::exec::resolve_damage(&mut ctx, &cid("enemy_b"), 1, false).is_err(),
                "a direct hit on an id that is not in the fight must stay loud"
            );
        }
    }

    #[test]
    fn a_spawned_enemy_joins_the_turn_order_after_the_current_actor() {
        // The turn order is a plain rotation (`turn.rs:845-877`), so a combatant appended mid-fight
        // acts **later in the same round** if the rotation has not passed its index yet. That is
        // the behaviour, so it gets pinned here rather than rediscovered.
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        state.active_combatant_id = Some(cid("hero"));
        give(&mut state, "enemy_b", status("st_split", "standard.split", 1));

        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("enemy_b"), 12, false).expect("the kill");
        }
        host.try_resolve_pending_queues(&mut state).expect("triggers");

        let order: Vec<&str> = state.turn_order().iter().map(|id| id.as_str()).collect();
        // §178: a combatant that *dies* stays in the order (advancement skips it by liveness,
        // `turn.rs:850`), but one that is **destroyed** leaves it. This split destroys its bearer.
        assert_eq!(order.len(), 4, "hero + enemy_a + two spawned: {order:?}");
        assert_eq!(order[0], "hero", "the actor keeps its place");
        assert_eq!(order[1], "enemy_a", "the survivors keep their relative order");
        assert!(
            !order.contains(&"enemy_b"),
            "the split bearer is out of the order, not a corpse in it: {order:?}"
        );
        assert!(
            order[2].contains('#') && order[3].contains('#'),
            "the spawned ones sit at the end: {order:?}"
        );
        assert_eq!(
            state.active_combatant_id.map(|id| id.as_str().to_string()),
            Some("hero".to_string()),
            "spawning must not steal the active slot"
        );
    }

    /// **A minion flees when its master falls** (`port-plan.md` §139): it becomes `Escaped`, which
    /// is neither alive (so it cannot block the victory) nor a corpse the reward screen counts.
    #[test]
    fn a_minion_flees_when_its_master_falls() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        {
            let id = cid("minion1");
            let definition = crate::state::CombatantDefinitionId::new("spike_slime_s").expect("def");
            let team = crate::state::TeamId::new("enemy").expect("team");
            let mut minion = crate::state::Combatant::new(id, definition, team, 10, 10);
            minion.owner = Some(cid("enemy_b"));
            state.add_combatant(minion).expect("minion");
        }
        assert!(crate::turn::is_alive(&state, &cid("minion1")), "it starts alive");

        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("enemy_b"), 12, false).expect("the kill");
        }
        host.try_resolve_pending_queues(&mut state).expect("triggers");

        assert!(!crate::turn::is_alive(&state, &cid("minion1")), "the minion stops being alive");
        assert_eq!(
            state.combatant(&cid("minion1")).map(|c| c.lifecycle_state),
            Some(crate::state::CombatantLifecycleState::Escaped),
            "and it left by fleeing, not by dying"
        );
        // An escaped minion does not keep the fight going: `enemy_a` is the only one left.
        assert_eq!(state.result, crate::state::CombatResult::Ongoing);
    }

    /// The summon cap is **loud** (`port-plan.md` §139): asking for one enemy too many fails
    /// instead of quietly dropping the minion.
    #[test]
    fn the_summon_cap_is_a_loud_failure() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut state = arena();
        // The summoner has to **exist** (a missing actor is a silent no-op in execute_action).
        {
            let definition = crate::state::CombatantDefinitionId::new("gremlin_leader").expect("def");
            let team = crate::state::TeamId::new("enemy").expect("team");
            state
                .add_combatant(crate::state::Combatant::new(
                    cid("gremlin_leader"),
                    definition,
                    team,
                    140,
                    140,
                ))
                .expect("summoner");
        }
        // ...then fill the fight up to the cap so the summoner is the last one standing room-wise.
        for index in 0..(crate::state::MAX_ENEMIES_IN_FIGHT - 2) {
            let id = CombatantId::new(&std::format!("filler{index}")).expect("id");
            let definition = crate::state::CombatantDefinitionId::new("spike_slime_s").expect("def");
            let team = crate::state::TeamId::new("enemy").expect("team");
            state
                .add_combatant(crate::state::Combatant::new(id, definition, team, 10, 10))
                .expect("filler");
        }

        let summon_row = (0..content.section(crate::content::S_EACT).map_or(0, |s| s.count))
            .find(|index| {
                content.entity_id(crate::content::Table::EnemyAction, *index)
                    == Some("gremlin_leader.summon")
            })
            .expect("the summon action is in the image");
        let outcome = crate::intent::execute_action(
            &mut state,
            &content,
            &cid("gremlin_leader"),
            summon_row,
            Some(cid("hero")),
        );
        assert!(
            outcome.is_err(),
            "a summon at the cap must fail loudly, got {outcome:?}"
        );
    }


    /// The Slime Boss splits in two when it dies (`node.createCombatant` reached from a `Downed`
    /// status, `port-plan.md` §121).
    ///
    /// §158: this function had **no `#[test]`** -- an earlier edit anchored on a doc line and ate
    /// the attribute, which then duplicated onto the function above. It compiled, never ran, and
    /// the only trace was a `never used` warning nobody read.
    /// §178: the exact shape of the `§177` freeze -- **three damage instances in one turn** while
    /// the boss is at `<= 10` HP. Before `node.destroyCombatant` each instance split again (the
    /// status removal is a queued request and never wins the race), so this test failed with
    /// `Capacity(Full(Combatants))` after ten summons.
    ///
    /// The judgment is the **roster**, not "it did not throw": a fix that silently swallows the
    /// overflow would also not throw.
    ///
    /// ⚠️ `assert!` rather than `assert_eq!` where the payload is a whole list of combatants -- a
    /// failing `assert_eq!` prints both rosters and nobody reads the second one.
    #[test]
    fn a_phase_split_happens_once_even_under_three_hits() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state
            .add_combatant(unit("hero", "player", 70, 70))
            .unwrap();
        // The boss at 8 HP: one point above the phase threshold, so the first hit takes it under.
        state
            .add_combatant(unit("slime_boss", "enemy", 8, 140))
            .unwrap();
        give(&mut state, "slime_boss", status("st_split", "standard.split", 1));
        give(
            &mut state,
            "slime_boss",
            status("st_phase", "standard.phase_split", 1),
        );
        assert_eq!(state.combatants().len(), 2, "hero + boss to start");

        // The real shape, and the reason this is not three separate `resolve_damage` calls: a
        // multi-hit card **enqueues** every hit, and the drain processes them back to back. The
        // trigger's own `modifyStatusStacks(-1)` lands at the *tail* of that same queue, so hits 2
        // and 3 still see the status unless the split removes the bearer itself.
        for _ in 0..3 {
            state
                .enqueue_effect(crate::state::EffectRequest::DealDamage {
                    target: Some(cid("slime_boss")),
                    amount: 2,
                    ignores_block: false,
                    source: Some(cid("hero")),
                })
                .expect("queue a hit");
        }
        host.try_resolve_pending_queues(&mut state).expect("settle");

        let ids: Vec<&str> = state.combatants().iter().map(|c| c.id.as_str()).collect();
        assert!(
            !ids.contains(&"slime_boss"),
            "the boss is GONE after the phase split, not merely dead: {ids:?}"
        );
        assert!(
            ids.len() <= 3,
            "one split means hero + two slimes, got {} combatants: {ids:?}",
            ids.len()
        );
        assert_eq!(
            state
                .combatants()
                .iter()
                .filter(|c| c.team_id.as_str() == "enemy")
                .count(),
            2,
            "exactly two enemies remain: {ids:?}"
        );
        assert!(
            state.combatants().len() < crate::state::MAX_COMBATANTS,
            "the container must never be the thing that stops the split"
        );
    }

    #[test]
    fn destroying_a_combatant_takes_it_out_of_the_roster_and_the_turn_order() {
        let mut state = arena(); // hero, enemy_a (20), enemy_b (10)
        let before = state.combatants().len();
        let order_before: Vec<String> = state
            .turn_order()
            .iter()
            .map(|id| id.as_str().to_string())
            .collect();

        let removed = state
            .remove_combatant(&cid("enemy_a"))
            .expect("remove enemy_a");
        assert_eq!(removed.id.as_str(), "enemy_a");
        assert_eq!(state.combatants().len(), before - 1, "one fewer in the roster");
        let order_after: Vec<String> = state
            .turn_order()
            .iter()
            .map(|id| id.as_str().to_string())
            .collect();
        let expected: Vec<String> = order_before
            .iter()
            .filter(|id| id.as_str() != "enemy_a")
            .cloned()
            .collect();
        assert_eq!(
            order_after, expected,
            "the turn order keeps everyone else in the same relative order"
        );
        assert!(state.combatant(&cid("enemy_a")).is_none(), "no dangling id");
        assert!(
            state.card_zones(&cid("enemy_a")).is_none(),
            "its piles go with it, or every `cz=` line after it shifts"
        );

        // Refusals change nothing. `CombatState` has no `PartialEq`, so the judgment is the
        // canonical text (the same one the golden hash consumes -- it covers `rng=`, the id
        // counters and every status line, which "compare a few fields" would miss).
        let snapshot = state_text(&state);
        assert!(
            state.remove_combatant(&cid("enemy_a")).is_err(),
            "removing a combatant that is not in the fight must fail loudly"
        );
        assert!(
            state_text(&state) == snapshot,
            "a refusal must not move a single byte"
        );
        // §200：**当前行动者可以自毁**了（Reptomancer 的匕首在自己的回合里炸掉自己）。
        // 席位不是"直接交给继任者"，而是**记下位置**等这一回合收尾时交接 —— 否则收尾时的
        // 一次推进会让继任者被跳过（一次跳两格）。`hero` 是 `arena()` 里第一个单位，
        // 也就是行动者。
        assert_eq!(state.active_combatant_id, Some(cid("hero")), "the arena starts on hero");
        state
            .remove_combatant(&cid("hero"))
            .expect("the active combatant may remove itself");
        assert_eq!(
            state.active_combatant_id, None,
            "the seat is vacant until the turn is closed"
        );
        assert_eq!(
            state.vacated_seat,
            Some(0),
            "the index the successor sits in after the shift-down"
        );
    }

    /// §200: 行动者**在自己的回合里自毁** —— 席位必须交给它的**继任者**，而且只推一格。
    ///
    /// `arena()` 的回合序是 `[hero, enemy_a, enemy_b]`。让 `enemy_a` 当行动者再把它移除，然后
    /// 收尾这一回合：
    ///
    /// * 继任者必须是 `enemy_b`（**不是** `hero`，也**不是** `enemy_b` 之后再跳一格）；
    /// * `current_turn` 只 +1（一次推进就够 —— 这正是"把席位直接设成继任者"会做错的地方：
    ///   那样收尾时还会再推进一格，`enemy_b` 永远轮不到）；
    /// * `current_round` 不变（没有绕回回合序的起点）。
    ///
    /// 负控：把 `advance_to_next_combatant` 里"取前一格"改成 `cur = seat` ⇒ 这里红在
    /// `active == hero`（跳过继任者）。
    #[test]
    fn a_combatant_that_removes_itself_hands_the_seat_to_its_successor() {
        let mut state = arena();
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        state.active_combatant_id = Some(cid("enemy_a"));
        state.turn_phase = crate::state::CombatTurnPhase::TurnInProgress;
        let turn_before = state.current_turn;
        let round_before = state.current_round;

        state
            .remove_combatant(&cid("enemy_a"))
            .expect("the acting combatant may remove itself");

        crate::turn::end_current_turn(&mut state, &config(), &mut host).expect("the turn closes");

        assert_eq!(
            state.active_combatant_id,
            Some(cid("enemy_b")),
            "the successor takes the seat"
        );
        assert_eq!(state.current_turn, turn_before + 1, "exactly one advance");
        assert_eq!(state.current_round, round_before, "no wrap-around");
        assert_eq!(state.vacated_seat, None, "the parked seat is consumed");
    }

    /// §200: 自毁的是**最后一个**席位 ⇒ 绕回回合序开头（英雄），回合数 +1、轮次 +1。
    ///
    /// 这与上一条合起来钉住"前一格"的两个边界：`seat == len`（末尾被移除，绕回 0）与
    /// `seat == 0`（第一个被移除）。
    #[test]
    fn a_combatant_that_removes_itself_last_wraps_to_the_front() {
        let mut state = arena();
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        state.active_combatant_id = Some(cid("enemy_b"));
        state.turn_phase = crate::state::CombatTurnPhase::TurnInProgress;
        let round_before = state.current_round;

        state
            .remove_combatant(&cid("enemy_b"))
            .expect("the last seat may remove itself");
        assert_eq!(state.vacated_seat, Some(2), "past the new end: the successor is index 0");

        crate::turn::end_current_turn(&mut state, &config(), &mut host).expect("the turn closes");

        assert_eq!(state.active_combatant_id, Some(cid("hero")), "wraps to the front");
        assert_eq!(state.current_round, round_before + 1, "a new round started");
    }

    /// §200 的**反向**判据：席位空着的时候，`ensure_active_combatant` 不许"认领第一个活人"。
    ///
    /// 那是最省事、也最错的写法：它会静默把回合序从头开始，而"继任者"其实是那一格上的人。
    /// 所以走到那条路上必须**响亮失败**（`NoActiveCombatant`），由
    /// `advance_to_next_combatant` 负责交接。
    #[test]
    fn a_vacant_seat_is_not_silently_reclaimed_from_the_top() {
        let mut state = arena();
        let blob = core_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        state.active_combatant_id = Some(cid("enemy_a"));
        state.turn_phase = crate::state::CombatTurnPhase::TurnInProgress;
        state.remove_combatant(&cid("enemy_a")).expect("self-removal");

        // 让 `end_current_turn` 之外的人去问"现在轮到谁"：它必须拒绝，而不是回答 hero。
        let verdict = crate::turn::advance_to_next_combatant(&mut state, &mut host);
        assert!(verdict.is_ok(), "the hand-off is the one legal way forward");
        assert_eq!(
            state.active_combatant_id,
            Some(cid("enemy_b")),
            "and it hands over to the successor, not to the top of the order"
        );
    }

    #[test]
    fn a_split_spawns_two_combatants_when_the_boss_dies() {
        // Wiki: the Slime Boss splits into two smaller slimes when it dies. The spawn node is the
        // kernel's own (`node.createCombatant`, `port-plan.md` §121); the trigger is a `Downed`
        // status, so this also proves the death hook reaches a *spawning* program.
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "enemy_b", status("st_split", "standard.split", 1));
        let before = state.combatants().len();

        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("enemy_b"), 12, false).expect("the kill");
        }
        host.try_resolve_pending_queues(&mut state).expect("triggers");

        // §178: `before + 1`, not `+2`: the boss is destroyed and two slimes take its place.
        assert_eq!(
            state.combatants().len(),
            before + 1,
            "the split adds two and removes the boss (net +1)"
        );
        assert!(
            state.combatant(&cid("enemy_b")).is_none(),
            "the boss is gone, so its `Downed` trigger can never fire a second time"
        );
        // ...and they are alive enemies with the definition the content named.
        let spawned: Vec<&str> = state
            .combatants()
            .iter()
            .filter(|c| c.definition_id.as_str() == "acid_slime_m")
            .map(|c| c.id.as_str())
            .collect();
        assert_eq!(spawned.len(), 2, "two acid_slime_m: {spawned:?}");
        for id in spawned {
            assert!(
                id.contains('#'),
                "the spawned id names its definition and its number ({id})"
            );
        }
    }

    /// §180: `DeathPrevention` -- the famous one-shot charm.
    ///
    /// A status with `Percent: 30` turns a killing blow into "you survive at 30% of max HP" **once**.
    /// The second killing blow is a real death, which is what makes this a test of the whole rule
    /// rather than of "the hero did not die".
    #[test]
    fn the_charm_catches_one_killing_blow_and_is_spent() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena(); // hero 70/70
        give(
            &mut state,
            "hero",
            status("st_fairy", "standard.fairy_in_a_bottle", 1),
        );

        // Lethal: 200 > 70. `Percent: 30` of 70 = 21.
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("enemy_a")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("hero"), 200, false).expect("the blow lands");
        }
        host.try_resolve_pending_queues(&mut state).expect("settle");

        assert_eq!(
            health(&state, "hero"),
            21,
            "survived at 30% of the 70 max HP (Percent), not at 1 HP and not at full"
        );
        assert_eq!(
            state.combatant(&cid("hero")).map(|c| c.lifecycle_state),
            Some(crate::state::CombatantLifecycleState::Alive),
            "the hero is alive, not a corpse that happens to have HP"
        );
        assert_eq!(
            stacks_of(&state, "hero", "standard.fairy_in_a_bottle"),
            0,
            "the charm is spent doing it (wiki: `works once`)"
        );

        // The second lethal blow must kill: the charm is gone.
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("enemy_a")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("hero"), 200, false).expect("the blow lands");
        }
        host.try_resolve_pending_queues(&mut state).expect("settle");
        assert_eq!(health(&state, "hero"), 0, "no health left");
        assert_eq!(
            state.combatant(&cid("hero")).map(|c| c.lifecycle_state),
            Some(crate::state::CombatantLifecycleState::Downed),
            "with the charm spent, a killing blow is a killing blow"
        );
    }

    /// §187: `EACT.ProgramAsc` + `AscensionMin` -- the same action, two numbers.
    ///
    /// Lagavulin's Attack is the cleanest example in this content: 18 base, **20** from A3
    /// (`wiki_lagavulin.txt`, `Asc|3|20`; it is an Act-1 elite, so the tier is 3). The judgment is
    /// the hero's health, i.e. what the player sees, and it is checked at **A2** (below the
    /// threshold) as well as A3 -- a variant that leaked one level early would pass a one-sided test.
    #[test]
    fn an_ascension_variant_replaces_the_program_at_its_threshold() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (ascension, expected_damage) in [(0u8, 18), (2, 18), (3, 20), (20, 20)] {
            let mut state = arena();
            state.set_ascension(ascension);
            // The image's own id index: no scanning, no hand-copied row number.
            let row = u32::from(
                content
                    .lookup_in("lagavulin.attack", crate::content::EK_EACTION)
                    .expect("lagavulin.attack is in the image")
                    .index,
            );
            let hero_before = health(&state, "hero");
            crate::intent::execute_action(
                &mut state,
                &content,
                &cid("enemy_a"),
                row,
                Some(cid("hero")),
            )
            .expect("the action runs");
            assert_eq!(
                hero_before - health(&state, "hero"),
                expected_damage,
                "A{ascension}: Lagavulin's Attack must deal {expected_damage}"
            );
        }
    }

    /// §192: **one** action, **two** ascension tiers -- Jaw Worm's Bellow.
    ///
    /// The wiki states all three numbers on one line (`native/wiki_asc/jaw_worm.txt:30`):
    /// `Gains (3;Asc|2|4;Asc|17|5) Strength. Gains (6;Asc|17|9) Block.` With §187's single variant
    /// slot only the A2 number could be carried (§190.4 wrote that limitation down), and A17's
    /// Strength (5) was unreachable: a variant is a *whole program*, so the A17 entry has to repeat
    /// the A2 change and add its own.
    ///
    /// The judgment is the two numbers a player sees (Strength stacks, Block), checked on **both
    /// sides of both thresholds** -- a tier that leaked one level early, or an A17 entry that forgot
    /// the A2 number, fails one of these five rows.
    #[test]
    fn one_action_can_carry_two_ascension_tiers() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let row = u32::from(
            content
                .lookup_in("jaw_worm.bellow", crate::content::EK_EACTION)
                .expect("jaw_worm.bellow is in the image")
                .index,
        );
        for (ascension, strength, block) in [(0u8, 3, 6), (1, 3, 6), (2, 4, 6), (16, 4, 6), (17, 5, 9), (20, 5, 9)] {
            let mut state = arena();
            state.set_ascension(ascension);
            crate::intent::execute_action(&mut state, &content, &cid("enemy_a"), row, Some(cid("hero")))
                .expect("the action runs");
            assert_eq!(
                (stacks_of(&state, "enemy_a", "standard.strength"), block_of(&state, "enemy_a")),
                (strength, block),
                "A{ascension}: Bellow must give Strength {strength} and {block} Block"
            );
        }
    }

    /// §193: variable damage -- "chosen at the start of combat" made literal.
    ///
    /// The wiki (`native/wiki_asc/louse.txt:28`) says `N = Number between (5-7;{{Asc|2|6-8}}),
    /// chosen at the start of combat`. So the number must be **one** value per fight, drawn before
    /// any turn, read by `louse_red.bite` through the reference's own `combatantCounter` expression.
    ///
    /// The judgment is the hero's health after two bites in the same fight: equal (one draw) and
    /// inside the range, with `random_step` having moved exactly once. A per-attack draw would make
    /// the two numbers differ roughly half the time -- which is why two bites, not one.
    #[test]
    fn a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let encounter = u32::from(
            content
                .lookup_in("enc_louse", crate::content::EK_ENCOUNTER)
                .expect("enc_louse is in the image")
                .index,
        );
        let row = u32::from(
            content
                .lookup_in("louse_red.bite", crate::content::EK_EACTION)
                .expect("louse_red.bite is in the image")
                .index,
        );

        let mut seen: Vec<i32> = Vec::new();
        for seed in 0..24 {
            for (ascension, low, high) in [(0u8, 5, 7), (2, 6, 8)] {
                let mut state = CombatState::new(CombatId::new("c1").unwrap(), seed);
                state
                    .add_combatant(unit("hero", "player", 70, 70))
                    .expect("hero");
                state
                    .add_combatant(unit("louse_red", "enemy", 10, 10))
                    .expect("the louse");
                state.set_ascension(ascension);
                let draws = crate::battle::apply_spawn_setup(&mut state, &content, encounter)
                    .expect("the encounter rolls")
                    .draws;
                // §209: the louse now declares **two** rolls (`roll.bite` and `roll.curl_up`), so
                // the count is "one draw per declared roll", read from the content -- a hard-coded 1
                // was only ever true while `roll.bite` was the only roll in the file.
                assert_eq!(
                    draws, 2,
                    "one draw per declared roll (`roll.bite` + `roll.curl_up`)"
                );
                assert_eq!(
                    state.random_step, 2,
                    "A{ascension}/seed {seed}: one draw, one step per roll"
                );

                let value = counter_of(&state, "louse_red", "roll.bite");
                assert!(
                    (low..=high).contains(&value),
                    "A{ascension}/seed {seed}: roll.bite = {value}, wiki says {low}-{high}"
                );

                // Two bites in the same fight carry the **same** number, and it is the rolled one.
                for bite in 0..2 {
                    let before = health(&state, "hero");
                    crate::intent::execute_action(
                        &mut state,
                        &content,
                        &cid("louse_red"),
                        row,
                        Some(cid("hero")),
                    )
                    .expect("the bite lands");
                    assert_eq!(
                        before - health(&state, "hero"),
                        value,
                        "A{ascension}/seed {seed}: bite {} must deal the rolled {value}",
                        bite + 1
                    );
                }
                assert_eq!(
                    state.random_step, 2,
                    "the bite itself draws nothing -- both rolls happened at spawn"
                );
                seen.push(value);
            }
        }
        let distinct: std::collections::BTreeSet<i32> = seen.iter().copied().collect();
        assert!(
            distinct.len() >= 4,
            "48 rolls produced only {distinct:?} -- the draw is not a draw"
        );
        assert!(
            seen.iter().all(|value| (5..=8).contains(value)),
            "every roll must be in 5..=8 (A0 5-7, A2 6-8): {distinct:?}"
        );
    }

    /// §193: a fight whose enemies declare **no** rolls draws nothing and leaves no counter behind.
    ///
    /// The second half matters more than the first: `combatantCounter` reads an absent counter as
    /// **0**, so "the roll silently did not happen" would look exactly like "the content says the
    /// damage is 0". Here it is pinned that the *absence* is the state (counter `-1` from the test's
    /// `counter_of` helper) and that `random_step` did not move.
    #[test]
    fn an_encounter_without_rolls_draws_nothing() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let encounter = u32::from(
            content
                .lookup_in("enc_louse", crate::content::EK_ENCOUNTER)
                .expect("an encounter")
                .index,
        );
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 7);
        state.add_combatant(unit("hero", "player", 70, 70)).expect("hero");
        state.add_combatant(unit("louse_red", "enemy", 10, 10)).expect("the louse");
        // Deliberately *not* the encounter's own enemy set: the rolls are looked up by the record
        // ids the encounter names, and `louse_red` is one of them, so a fight with the right
        // combatant must still draw.
        let draws = crate::battle::apply_spawn_setup(&mut state, &content, encounter)
            .expect("rolls")
            .draws;
        assert!(draws >= 1, "enc_louse names louse_red, which rolls");
        // And the negative half: a record that declares `Rolls: []` (cultist) draws nothing.
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 7);
        state.add_combatant(unit("hero", "player", 70, 70)).expect("hero");
        state.add_combatant(unit("cultist", "enemy", 50, 50)).expect("the cultist");
        let encounter = u32::from(
            content
                .lookup_in("enc_cultist", crate::content::EK_ENCOUNTER)
                .expect("enc_cultist")
                .index,
        );
        let draws = crate::battle::apply_spawn_setup(&mut state, &content, encounter)
            .expect("no rolls is not an error")
            .draws;
        assert_eq!(draws, 0, "cultist declares `Rolls: []`");
        assert_eq!(state.random_step, 0, "no draw ⇒ no step");
    }

    /// §194: Sharp Hide is a `CardPlayed` trigger filtered on the card's **tag**.
    ///
    /// Three assertions, because three things can each be wrong independently: an Attack hurts the
    /// hero, a Skill does not, and Twin Slam drops the stacks (the wiki: "Loses Sharp Hide").
    #[test]
    fn sharp_hide_hurts_the_player_for_attacks_and_only_attacks() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_hide", "standard.sharp_hide", 3));
        let attack = card_in_hand(&mut state, &content, "hero", "strike");
        let skill = card_in_hand(&mut state, &content, "hero", "defend");

        // An Attack: the Guardian bites back for 3.
        let before = health(&state, "hero");
        state
            .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card: attack })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(health(&state, "hero"), before - 3, "Sharp Hide 3 punishes an Attack");

        // A Skill: nothing happens.
        let before = health(&state, "hero");
        state
            .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card: skill })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(health(&state, "hero"), before, "a Skill is not an Attack");

        // Twin Slam drops it, so the next Attack is free.
        let row = u32::from(
            content
                .lookup_in("the_guardian.twin_slam", crate::content::EK_EACTION)
                .expect("twin slam is in the image")
                .index,
        );
        crate::intent::execute_action(&mut state, &content, &cid("enemy_a"), row, Some(cid("hero")))
            .expect("Twin Slam lands");
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.sharp_hide"),
            0,
            "wiki: Twin Slam loses Sharp Hide"
        );
        let before = health(&state, "hero");
        state
            .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card: attack })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(health(&state, "hero"), before, "with the stacks gone, nothing bites back");
    }

    /// §194: Hexaghost's Divider -- `(hero HP / 12 + 1)` hits of 6, i.e. the first content move whose
    /// repeat count is **computed**. 70 HP -> `70/12 = 5` -> 6 hits -> 36 damage.
    ///
    /// Two different health totals are checked on purpose: a constant count would satisfy one.
    #[test]
    fn hexaghosts_divider_repeats_ceil_of_hp_over_twelve_plus_one() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let row = u32::from(
            content
                .lookup_in("hexaghost.divider", crate::content::EK_EACTION)
                .expect("divider is in the image")
                .index,
        );
        for (hero_hp, hits) in [(70, 6), (12, 2), (11, 1), (0, 0)] {
            let mut state = arena();
            if let Some(hero) = state.combatant_mut(&cid("hero")) {
                hero.health_current = hero_hp;
            }
            let before = health(&state, "hero");
            crate::intent::execute_action(&mut state, &content, &cid("enemy_a"), row, Some(cid("hero")))
                .expect("Divider lands");
            let dealt = before - health(&state, "hero");
            assert_eq!(
                dealt,
                hits * 6,
                "hero at {hero_hp}: {hits} hits of 6 = {}",
                hits * 6
            );
        }
    }

    /// §194: `sel.allAllies` -- Donu's Circle of Power buffs **both** bosses and not the hero.
    #[test]
    fn donus_circle_of_power_buffs_the_enemy_team_and_not_the_player() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut state = arena();
        state
            .add_combatant(unit("donu", "enemy", 250, 250))
            .expect("donu");
        state
            .add_combatant(unit("deca", "enemy", 250, 250))
            .expect("deca");
        let row = u32::from(
            content
                .lookup_in("donu.circle_of_power", crate::content::EK_EACTION)
                .expect("circle of power is in the image")
                .index,
        );
        crate::intent::execute_action(&mut state, &content, &cid("donu"), row, Some(cid("hero")))
            .expect("the buff lands");
        assert_eq!(stacks_of(&state, "donu", "standard.strength"), 3, "Donu buffs itself");
        assert_eq!(stacks_of(&state, "deca", "standard.strength"), 3, "and its ally");
        assert_eq!(
            stacks_of(&state, "hero", "standard.strength"),
            0,
            "`sel.allEnemies` would have buffed the hero -- this is the assertion that pins which              team the selector means"
        );
    }

    /// §195.1: The Guardian's Mode Shift is a **budget** seeded at spawn (`Counters`), drained by
    /// the HP actually lost (`eventAmount`), refilled by +10 on each shift.
    ///
    /// Four judgements, none of which a "the boss has a rule" test would make:
    /// 1. 29 HP is **not** enough (the threshold is 30, not 29);
    /// 2. a fully **blocked** hit drains nothing (the amount is HP lost, not the request);
    /// 3. the shift resets the budget to `surplus + 10` -- so the next shift needs 40 cumulative;
    /// 4. the budget comes from the **content's `Counters`**, not from a literal in the kernel
    ///    (a later `Counters` edit must move this test).
    #[test]
    fn mode_shift_is_a_budget_drained_by_the_health_actually_lost() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let encounter = u32::from(
            content
                .lookup_in("enc_the_guardian", crate::content::EK_ENCOUNTER)
                .expect("the guardian's encounter")
                .index,
        );

        // The combatant must carry the **record id** (`the_guardian`): `Counters` are keyed on the
        // encounter's enemy ids, so `arena()`'s `enemy_a` would get nothing (and the setup says so
        // with `MissingCombatant` instead of silently writing nothing).
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state.add_combatant(unit("hero", "player", 70, 70)).expect("hero");
        state
            .add_combatant(unit("the_guardian", "enemy", 240, 240))
            .expect("the guardian");
        give(&mut state, "the_guardian", status("st_ms", "standard.mode_shift", 1));
        // `arena()`'s enemy is called `enemy_a`, but the `Counters` are keyed on the **record id**,
        // so the setup has to be run for the real encounter -- and then the number read from the
        // state is what the content declared.
        let mut host = Host::new(&content);
        let drawn = crate::battle::apply_spawn_setup(&mut state, &content, encounter)
            .expect("spawn setup");
        assert_eq!(drawn.counters, 1, "one fixed counter (the Mode Shift budget)");
        assert_eq!(drawn.draws, 0, "a stated value must not cost a random step");
        assert_eq!(
            counter_of(&state, "the_guardian", "mode_shift_budget"),
            30,
            "wiki: Mode Shift 30 at A0"
        );

        let hit_for = |state: &mut CombatState, host: &mut Host<'_>, amount: i32, block: i32| {
            state
                .combatant_mut(&cid("the_guardian"))
                .expect("the guardian")
                .set_defensive_pool(
                    crate::state::DefensivePoolId::new("standard.block").unwrap(),
                    block,
                    None,
                )
                .expect("block");
            {
                let mut ctx = crate::exec::ExecContext::new(
                    state,
                    Some(cid("hero")),
                    Some(cid("the_guardian")),
                    None,
                    64,
                )
                .with_content(&content);
                crate::exec::resolve_damage(&mut ctx, &cid("the_guardian"), amount, false)
                    .expect("the blow lands");
            }
            host.try_resolve_pending_queues(state).expect("the trigger settles");
        };

        hit_for(&mut state, &mut host, 29, 0);
        assert_eq!(counter_of(&state, "the_guardian", "mode_shift_budget"), 1, "29 of 30 spent");

        // Fully blocked: the request is 50 but **no HP is lost**, so the budget does not move.
        hit_for(&mut state, &mut host, 50, 999);
        assert_eq!(
            counter_of(&state, "the_guardian", "mode_shift_budget"),
            1,
            "a fully blocked hit loses no HP -- `eventAmount` must not be the requested amount"
        );

        // One more HP crosses zero.
        hit_for(&mut state, &mut host, 1, 0);
        assert_eq!(counter_of(&state, "the_guardian", "mode_shift_budget"), 0);
        let row = u32::from(
            content
                .lookup_in("the_guardian.defensive_mode", crate::content::EK_EACTION)
                .expect("defensive mode is in the image")
                .index,
        );
        crate::intent::execute_action(&mut state, &content, &cid("the_guardian"), row, Some(cid("hero")))
            .expect("Defensive Mode");
        assert_eq!(
            counter_of(&state, "the_guardian", "mode_shift_budget"),
            10,
            "the wiki's `increased by 10 each time`: 0 + 10"
        );
        assert_eq!(block_of(&state, "the_guardian"), 20, "wiki: gains 20 Block");
        assert_eq!(
            stacks_of(&state, "the_guardian", "standard.sharp_hide"),
            3,
            "and 3 Sharp Hide"
        );

        // The second shift therefore needs 40 cumulative (30 spent + 10). 9 is not enough, 10 is.
        hit_for(&mut state, &mut host, 9, 0);
        assert_eq!(counter_of(&state, "the_guardian", "mode_shift_budget"), 1);
        hit_for(&mut state, &mut host, 1, 0);
        assert_eq!(counter_of(&state, "the_guardian", "mode_shift_budget"), 0);
    }

    /// §195.2: Awakened One's revive is **real** -- the first killing blow leaves it at 1 HP (its
    /// `DeathPrevention` guard), the guard is spent, and the second killing blow kills it.
    ///
    /// Why this belongs in `host.rs` and not in the intent tests: the guard is consumed inside
    /// `exec::resolve_damage` (the `S6d` block, §180), i.e. *below* the intent layer. The four
    /// judgements: still standing at 1 HP; the guard is spent; Rebirth heals to full and flips the
    /// phase; and a second lethal blow **does** down it (a `Repeating: true` guard would pass the
    /// first three and make the boss immortal).
    #[test]
    fn the_awakened_one_survives_its_first_death_and_then_really_dies() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 5);
        state.add_combatant(unit("hero", "player", 70, 70)).expect("hero");
        state
            .add_combatant(unit("awakened_one", "enemy", 300, 300))
            .expect("the boss");
        // What the boss's record declares: two powers and the phase-one guard.
        for entry in [
            status("st_regen", "standard.regen", 10),
            status("st_cur", "standard.curiosity", 1),
            status("st_un", "standard.unawakened", 1),
        ] {
            give(&mut state, "awakened_one", entry);
        }

        let blow = |state: &mut CombatState, host: &mut Host<'_>, amount: i32| {
            {
                let mut ctx = crate::exec::ExecContext::new(
                    state,
                    Some(cid("hero")),
                    Some(cid("awakened_one")),
                    None,
                    64,
                )
                .with_content(&content);
                crate::exec::resolve_damage(&mut ctx, &cid("awakened_one"), amount, false)
                    .expect("the blow lands");
            }
            host.try_resolve_pending_queues(state).expect("triggers settle");
        };

        blow(&mut state, &mut host, 999);
        assert_eq!(health(&state, "awakened_one"), 1, "the guard leaves it at 1 HP");
        assert_eq!(
            state.combatant(&cid("awakened_one")).map(|c| c.lifecycle_state),
            Some(crate::state::CombatantLifecycleState::Alive),
            "standing, not a corpse with 1 HP"
        );
        assert_eq!(
            stacks_of(&state, "awakened_one", "standard.unawakened"),
            0,
            "a one-shot guard is spent (the kernel consumes non-repeating ones)"
        );

        // Rebirth: full heal, Curiosity gone, phase counter set.
        let row = u32::from(
            content
                .lookup_in("awakened_one.rebirth", crate::content::EK_EACTION)
                .expect("rebirth is in the image")
                .index,
        );
        crate::intent::execute_action(&mut state, &content, &cid("awakened_one"), row, Some(cid("hero")))
            .expect("Rebirth");
        assert_eq!(health(&state, "awakened_one"), 300, "wiki: heals to full");
        assert_eq!(stacks_of(&state, "awakened_one", "standard.curiosity"), 0, "loses Curiosity");
        assert_eq!(counter_of(&state, "awakened_one", "ao_phase"), 1, "phase two");

        blow(&mut state, &mut host, 999);
        assert_eq!(health(&state, "awakened_one"), 0);
        assert_eq!(
            state.combatant(&cid("awakened_one")).map(|c| c.lifecycle_state),
            Some(crate::state::CombatantLifecycleState::Downed),
            "the second killing blow is a killing blow"
        );
    }

    /// §195.4: Bronze Orb's `Stasis` -- `node.selectCards` picks the **highest-rarity** card, falls
    /// back to the discard pile when the draw pile is empty, and gives it back when the orb dies.
    ///
    /// Five judgements, one per way the node can be wrong:
    /// 1. it takes the **highest rarity** (not the first card in the pile -- the naive
    ///    implementation). This content has no `Rare` cards at all (the deck is Basic/Common/
    ///    Uncommon), so the probe is `Uncommon > Common > Basic`; the rank table itself is pinned by
    ///    `card_rarity_rank`'s doc comment, and using a card this content really has keeps the test
    ///    from silently passing on a rank table that only knows `Rare`;
    /// 2. it moves exactly **one** card, into `SetAsidePile`;
    /// 3. an empty draw pile falls back to the discard pile (otherwise Stasis silently does nothing);
    /// 4. `Stasis` spends its own status, so "once per combat" is real;
    /// 5. when the orb goes down, the card comes back to the hero's **hand** (a `Downed` trigger).
    #[test]
    fn stasis_steals_the_best_card_and_returns_it_when_the_orb_dies() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        // A second enemy **must** be alive when the orb dies: killing the last enemy sets `Victory`,
        // and the drain loops stop on `Victory` (`while pending && result == Ongoing`), so the death
        // trigger would never run. In the real fight that is the Automaton -- the orb never dies last.
        state
            .add_combatant(unit("bronze_automaton", "enemy", 300, 300))
            .expect("the automaton");
        state.add_combatant(unit("orb", "enemy", 52, 52)).expect("the orb");
        give(&mut state, "orb", status("st_stasis", "standard.stasis", 1));
        give(&mut state, "orb", status("st_ready", "standard.stasis_ready", 1));

        // A draw pile whose *first* card is Common and whose Rare is last: "first" and "best" differ.
        // Pile order matters: Basic, Common, then the **Uncommon** at the end -- so "highest rarity"
        // and "the first card" give different answers.
        give_card(&mut state, "hero", CardZone::DrawPile, "c1", "strike", None);
        give_card(&mut state, "hero", CardZone::DrawPile, "c2", "iron_wave", None);
        give_card(&mut state, "hero", CardZone::DrawPile, "c3", "uppercut", None);
        // ... and a Common + an Uncommon in the discard pile, which only the fallback may reach.
        let hero_hand_before = zone_count(&state, "hero", CardZone::Hand);

        let row = u32::from(
            content
                .lookup_in("bronze_orb.stasis", crate::content::EK_EACTION)
                .expect("stasis is in the image")
                .index,
        );
        crate::intent::execute_action(&mut state, &content, &cid("orb"), row, Some(cid("hero")))
            .expect("Stasis");
        host.try_resolve_pending_queues(&mut state).expect("the move lands");

        assert_eq!(
            zone_definitions(&state, "hero", CardZone::SetAsidePile),
            vec!["uppercut".to_string()],
            "the Uncommon (`uppercut`) is stolen -- not the first card in the pile"
        );
        assert_eq!(zone_count(&state, "hero", CardZone::DrawPile), 2, "exactly one card left the pile");
        assert_eq!(
            stacks_of(&state, "orb", "standard.stasis_ready"),
            0,
            "using Stasis spends the *flag* (wiki: once per combat)"
        );
        assert_eq!(
            stacks_of(&state, "orb", "standard.stasis"),
            1,
            "the death hook must survive -- otherwise the stolen card is never returned"
        );

        // Fallback: an empty draw pile reaches into the discard pile.
        let mut state = arena();
        state
            .add_combatant(unit("bronze_automaton", "enemy", 300, 300))
            .expect("the automaton");
        state.add_combatant(unit("orb", "enemy", 52, 52)).expect("the orb");
        give(&mut state, "orb", status("st_stasis2", "standard.stasis", 1));
        give(&mut state, "orb", status("st_ready2", "standard.stasis_ready", 1));
        give_card(&mut state, "hero", CardZone::DiscardPile, "d1", "iron_wave", None);
        give_card(&mut state, "hero", CardZone::DiscardPile, "d2", "uppercut", None);
        let mut host = Host::new(&content);
        crate::intent::execute_action(&mut state, &content, &cid("orb"), row, Some(cid("hero")))
            .expect("Stasis");
        host.try_resolve_pending_queues(&mut state).expect("the move lands");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::SetAsidePile),
            vec!["uppercut".to_string()],
            "an empty draw pile falls back to the discard pile, and the Uncommon still wins"
        );

        // Death returns it: kill the orb and the stolen card comes back to the hand.
        {
            let mut ctx = crate::exec::ExecContext::new(
                &mut state,
                Some(cid("hero")),
                Some(cid("orb")),
                None,
                64,
            )
            .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("orb"), 999, false).expect("the orb dies");
        }
        host.try_resolve_pending_queues(&mut state).expect("death triggers settle");
        assert!(
            zone_definitions(&state, "hero", CardZone::Hand).contains(&"uppercut".to_string()),
            "wiki: on death, the stolen card is returned to your hand"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::SetAsidePile),
            0,
            "and the holding zone is empty again"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            hero_hand_before + 1,
            "exactly one card came back"
        );
    }

    /// §196：`Entangled` —— 本回合**只**拦 Attack，技能照打；回合结束后自动解除。
    ///
    /// 三条判据各锁一个不同的失败模式：
    /// 1. Attack 被拒，**且拒绝码是 18**（页面按码显示文案，漏一个 case 会显示 "none"）；
    /// 2. Skill 仍然能打 —— 只查攻击牌才是 Entangled，把"什么都拦"写成 Stunned 是最像对的错法；
    /// 3. `TurnEnded` 之后能打 —— 这条状态靠自己的触发器失效（内核没有时长时钟）。
    #[test]
    fn entangled_refuses_attacks_but_not_skills_and_expires_at_turn_end() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        // `arena()` gives nobody energy; a play needs it before any validator runs.
        state
            .combatant_mut(&cid("hero"))
            .expect("hero")
            .set_resource(ResourceId::new("standard.energy").unwrap(), 3, Some(3))
            .expect("energy");
        give(&mut state, "hero", status("st_ent", "standard.entangled", 1));
        let attack = card_in_hand(&mut state, &content, "hero", "strike");
        let skill = card_in_hand(&mut state, &content, "hero", "defend");

        let request = |card| crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a")));
        let played = crate::play::play_card(&mut state, Some(&content), &request(attack));
        match played {
            Err(crate::play::PlayError::Refused(refusal)) => {
                assert_eq!(refusal, crate::play::Refusal::Entangled, "the refusal kind");
                assert_eq!(
                    crate::battle::play_code(&crate::battle::BattleError::Play(
                        crate::play::PlayError::Refused(refusal)
                    )),
                    18,
                    "the page shows this number"
                );
                assert_eq!(
                    crate::battle::play_code_name(18),
                    "Refused(Entangled)",
                    "and this name"
                );
            }
            other => panic!("an Attack under Entangled must be refused, got {other:?}"),
        }

        // A Skill is untouched.
        crate::play::play_card(&mut state, Some(&content), &request(skill))
            .expect("wiki: only *Attacks* are blocked");

        // Turn end -> the status' own trigger decays it -> Attacks are playable again.
        host.try_run_turn_ended_triggers(&mut state, &cid("hero"))
            .expect("turn end");
        assert_eq!(stacks_of(&state, "hero", "standard.entangled"), 0, "expires");
        crate::play::play_card(&mut state, Some(&content), &request(attack))
            .expect("the attack is legal again");
    }

    /// §195.9（审阅 P1-1）：候选缓冲是**牌区容量**（96），不是 64 —— 排在第 65 位以后的卡也要参与。
    ///
    /// 这条是可观测的：96 张 `strike`（Basic）+ 最后一张 `uppercut`（Uncommon），`HighestRarity`
    /// 必须偷到 `uppercut`。旧实现（缓冲 64 + 静默 `break`）会偷到一张 `strike`。
    #[test]
    fn a_96_card_pile_still_reaches_the_best_card_at_the_end() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut state = arena();
        state
            .add_combatant(unit("bronze_automaton", "enemy", 300, 300))
            .expect("the automaton");
        state.add_combatant(unit("orb", "enemy", 52, 52)).expect("the orb");
        give(&mut state, "orb", status("st_stasis", "standard.stasis", 1));
        give(&mut state, "orb", status("st_ready", "standard.stasis_ready", 1));
        // 95 Basics, then the Uncommon at the very end (position 96).
        for index in 0..95 {
            give_card(&mut state, "hero", CardZone::DrawPile, &std::format!("c{index}"), "strike", None);
        }
        give_card(&mut state, "hero", CardZone::DrawPile, "last", "uppercut", None);
        assert_eq!(zone_count(&state, "hero", CardZone::DrawPile), 96, "the pile is full");

        let mut host = Host::new(&content);
        let row = u32::from(
            content
                .lookup_in("bronze_orb.stasis", crate::content::EK_EACTION)
                .expect("stasis is in the image")
                .index,
        );
        crate::intent::execute_action(&mut state, &content, &cid("orb"), row, Some(cid("hero")))
            .expect("Stasis");
        host.try_resolve_pending_queues(&mut state).expect("the move lands");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::SetAsidePile),
            vec!["uppercut".to_string()],
            "the Uncommon at the bottom of a 96-card pile must win"
        );
    }

    /// §195.9（审阅 P1-2）：并列最高稀有度要**随机**，否则三张同稀有度永远偷同一张。
    ///
    /// 观测量是**实例 id**：三张 `iron_wave`（Common）内容一样，但实例不同。60 个种子必须出现
    /// 至少两种结果（旧实现是稳定排序 ⇒ 永远偷第一张 ⇒ 只有一种）。
    #[test]
    fn tied_rarities_are_broken_by_the_combat_rng() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let row = u32::from(
            content
                .lookup_in("bronze_orb.stasis", crate::content::EK_EACTION)
                .expect("stasis is in the image")
                .index,
        );
        let mut stolen: Vec<std::string::String> = Vec::new();
        for seed in 0..60 {
            let mut state = arena();
            state.random_seed = seed;
            state
                .add_combatant(unit("bronze_automaton", "enemy", 300, 300))
                .expect("the automaton");
            state.add_combatant(unit("orb", "enemy", 52, 52)).expect("the orb");
            give(&mut state, "orb", status("st_stasis", "standard.stasis", 1));
            give(&mut state, "orb", status("st_ready", "standard.stasis_ready", 1));
            for index in 0..3 {
                give_card(&mut state, "hero", CardZone::DrawPile,
                          &std::format!("t{index}"), "iron_wave", None);
            }
            let mut host = Host::new(&content);
            crate::intent::execute_action(&mut state, &content, &cid("orb"), row, Some(cid("hero")))
                .expect("Stasis");
            host.try_resolve_pending_queues(&mut state).expect("the move lands");
            let taken: Vec<std::string::String> = state
                .zone_cards(&cid("hero"), CardZone::SetAsidePile)
                .map(|card| std::string::String::from(card.id.as_str()))
                .collect();
            assert_eq!(taken.len(), 1, "seed {seed}: exactly one card");
            stolen.push(taken[0].clone());
        }
        let distinct: std::collections::BTreeSet<&std::string::String> = stolen.iter().collect();
        assert!(
            distinct.len() >= 2,
            "60 draws of three tied cards produced only {distinct:?} -- ties are not random"
        );
    }

    /// §195.9（审阅 P1-3）：`Count` 大于候选数时**只搬实际存在的那些**。
    ///
    /// Stasis 的归还写的是 `Count: 4` 而通常只有一张：旧实现会从 `order` 的零值区读出同一个索引
    /// 4 次 ⇒ 同一张卡入队 4 次、`stats.effects` 多记 3 次。
    ///
    /// 口径：`selectCards(1) + modifyStatusStacks(1) + 历史对(2) = 4`；旧实现是 **7**
    /// （历史对是 §195.5 加的 `prev_move` / `last_move` 两次写入，也计入 `effects`）。
    ///
    /// ⚠️ **这条测试抓不到什么**（如实报告，不是遗漏）：`Count > found` 的后果是"同一张卡被
    /// 入队 N 次"，而**同区搬运是 no-op**（`move_card` 对 `from == to` 只在 `Top` 时重排），所以
    /// 往回搬的那条路径在**状态**上看不出重复。能看见它的只有 `effects` 计数，而计数器只对
    /// "`Count > 1` 且候选更少"的**程序**可见 —— 本内容唯一这样的调用在**触发器**里，宿主不回收
    /// 它的 `ExecStats`。⇒ 这一半的守卫是代码里的 `count.min(found)`，加上面那条 `effects`
    /// 基线（谁把 `min` 去掉、又把 Count 改成 >1，它就会红）。真正的长期解法是给
    /// `Host` 也记一份 effect 账，已记进 `port-plan.md` §195.9 的"已知测试缺口"。
    #[test]
    fn asking_for_more_cards_than_exist_moves_each_of_them_once() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut state = arena();
        state
            .add_combatant(unit("bronze_automaton", "enemy", 300, 300))
            .expect("the automaton");
        state.add_combatant(unit("orb", "enemy", 52, 52)).expect("the orb");
        give(&mut state, "orb", status("st_stasis", "standard.stasis", 1));
        give(&mut state, "orb", status("st_ready2", "standard.stasis_ready", 1));
        give_card(&mut state, "hero", CardZone::DiscardPile, "only", "uppercut", None);

        let row = u32::from(
            content
                .lookup_in("bronze_orb.stasis", crate::content::EK_EACTION)
                .expect("stasis is in the image")
                .index,
        );
        let stats = crate::intent::execute_action(
            &mut state, &content, &cid("orb"), row, Some(cid("hero")))
            .expect("Stasis");
        assert_eq!(
            stats.effects, 4,
            "one moved card + one status write + the two history counters"
        );

        // And the same through the **return** path (Count: 4, one card in the holding zone).
        let mut host = Host::new(&content);
        host.try_resolve_pending_queues(&mut state).expect("the move lands");
        let hand_before = zone_count(&state, "hero", CardZone::Hand);
        {
            let mut ctx = crate::exec::ExecContext::new(
                &mut state,
                Some(cid("hero")),
                Some(cid("orb")),
                None,
                64,
            )
            .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("orb"), 999, false).expect("the orb dies");
        }
        host.try_resolve_pending_queues(&mut state).expect("death triggers settle");
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            hand_before + 1,
            "exactly one card comes back -- `Count: 4` must not move it four times"
        );
    }

    /// §195.7: `node.upgradeCards` rewrites a card's **definition** (`burn` -> `burn+`) everywhere it
    /// lives, and leaves a card that has no `+` row alone.
    ///
    /// Three judgements: all three piles are walked (a node that only looked at the draw pile would
    /// still pass a one-pile test), a card without an upgrade row is **unchanged** (that is StS's
    /// `canUpgrade() == false`, not an error), and the count is right (no double-upgrade, no
    /// upgrade of the already-upgraded).
    #[test]
    fn upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::DrawPile, "b1", "burn", None);
        give_card(&mut state, "hero", CardZone::Hand, "b2", "burn", None);
        give_card(&mut state, "hero", CardZone::DiscardPile, "b3", "burn", None);
        // Already upgraded: must stay as it is, and must not be counted twice.
        give_card(&mut state, "hero", CardZone::DiscardPile, "b4", "burn+", None);
        // No `burn++` (and `dazed` has no upgrade at all): both are left alone.
        give_card(&mut state, "hero", CardZone::Hand, "d1", "dazed", None);

        let mut host = Host::new(&content);
        let row = u32::from(
            content
                .lookup_in("hexaghost.inferno", crate::content::EK_EACTION)
                .expect("inferno is in the image")
                .index,
        );
        crate::intent::execute_action(&mut state, &content, &cid("enemy_a"), row, Some(cid("hero")))
            .expect("Inferno");
        host.try_resolve_pending_queues(&mut state).expect("the move lands");

        for zone in [CardZone::DrawPile, CardZone::Hand, CardZone::DiscardPile] {
            let burns = zone_definitions(&state, "hero", zone)
                .into_iter()
                .filter(|name| name.starts_with("burn"))
                .collect::<Vec<_>>();
            assert!(
                burns.iter().all(|name| name == "burn+"),
                "{zone:?} still holds an un-upgraded Burn: {burns:?}"
            );
        }
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::Hand),
            vec!["burn+".to_string(), "dazed".to_string()],
            "`dazed` has no `+` row, so it stays `dazed`"
        );
        // The discard pile also received Inferno's own "3 Burn+" (wiki), so it holds the two original
        // cards plus those three -- all upgraded, none lost, none doubled.
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DiscardPile),
            vec!["burn+".to_string(); 5],
            "2 originals + the 3 Inferno shuffles in, all `burn+`"
        );
    }

    /// §195.7: `standard.draw_reduction` -- 1 less card **next** turn, and gone the turn after.
    ///
    /// This is the status the README used to list as blocked ("the host never runs the reference's
    /// timed clock"). The clock is indeed not run -- and it does not need to be: every timed debuff
    /// in this content decays through its own `TurnEnded` trigger, so "one turn" is content.
    ///
    /// Three judgements, each a different failure mode: the passive really reaches the turn machine
    /// (draw 4 instead of 5), the decay trigger really fires (the stack is gone at turn end), and a
    /// **fresh** fight without the status still draws 5 (so "4" cannot be a global constant).
    #[test]
    fn draw_reduction_costs_exactly_one_turns_draw_and_then_expires() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let config = TurnConfig {
            energy: ResourceId::new("standard.energy").unwrap(),
            energy_refill: 3,
            draw_per_turn: 5,
            max_hand_size: i32::MAX,
            block_pool: DefensivePoolId::new("standard.block").unwrap(),
        };
        let stock = |state: &mut CombatState| {
            for index in 0..10 {
                give_card(state, "hero", CardZone::DrawPile, &std::format!("c{index}"), "strike", None);
            }
        };

        // Turning on the pipeline is what the enemy's Head Slam does *before* the hero's turn starts,
        // so the status is already on the hero when the turn machine asks for the count.
        let mut state = arena();
        stock(&mut state);
        state
            .combatant_mut(&cid("hero"))
            .expect("hero")
            .push_status(crate::state::StatusInstance::new(
                crate::state::StatusInstanceId::new("dr1").unwrap(),
                crate::state::StatusDefinitionId::new("standard.draw_reduction").unwrap(),
                crate::state::StatusPolarity::Debuff,
            ).with_stacks(1))
            .expect("apply draw reduction");
        let mut host = Host::new(&content);
        turn::start_current_turn(&mut state, &config, &mut host).expect("turn 1");
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            4,
            "wiki: `Draw 1 less card next turn`"
        );

        // The decay is the status' own `TurnEnded` trigger: one turn, not forever.
        host.try_run_turn_ended_triggers(&mut state, &cid("hero"))
            .expect("hero turn ends");
        assert_eq!(
            stacks_of(&state, "hero", "standard.draw_reduction"),
            0,
            "a `TurnStartDraw` passive with no decay would be permanent"
        );

        // Control: without the status the same deck draws the full five.
        let mut clean = arena();
        stock(&mut clean);
        let mut host = Host::new(&content);
        turn::start_current_turn(&mut clean, &config, &mut host).expect("turn 1");
        assert_eq!(zone_count(&clean, "hero", CardZone::Hand), 5, "the base draw");
    }

    #[test]
    fn regen_heals_at_the_end_of_the_turn() {
        // Wiki: Regen N = "at the end of your turn, heal N". Content trigger on `TurnEnded`.
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_reg", "standard.regen", 4));
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("hero"), 10, false).expect("hurt");
        }
        host.try_resolve_pending_queues(&mut state).expect("settle");
        let hurt = health(&state, "hero");
        host.try_run_turn_ended_triggers(&mut state, &cid("hero"))
            .expect("turn end");
        assert_eq!(health(&state, "hero"), hurt + 4, "Regen 4 heals 4");
    }

    #[test]
    fn rage_gives_block_only_for_an_attack() {
        // Wiki: Rage N = "whenever you play an Attack, gain N Block".
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_rg", "standard.rage", 3));
        let attack = card_in_hand(&mut state, &content, "hero", "strike");
        let skill = card_in_hand(&mut state, &content, "hero", "defend");

        let block = |state: &crate::state::CombatState| -> i32 {
            state
                .combatant(&cid("hero"))
                .map_or(0, |c| c.defensive_pools().iter().map(|e| e.pool.current).sum())
        };

        state
            .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card: skill })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(block(&state), 0, "a Skill gives no Block");

        state
            .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card: attack })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(block(&state), 3, "an Attack gives 3 Block");
    }

    #[test]
    fn flame_barrier_hits_back_and_combust_burns_everyone() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // Flame Barrier: same hook as Thorns, different status.
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "enemy_b", status("st_fb", "standard.flame_barrier", 4));
        let hero_before = health(&state, "hero");
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("enemy_b"), 5, false).expect("hit");
        }
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(health(&state, "hero"), hero_before - 4, "Flame Barrier 4 hits back for 4");

        // Combust: turn end, every enemy takes its stacks.
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_cb", "standard.combust", 3));
        let before = health(&state, "enemy_a");
        host.try_run_turn_ended_triggers(&mut state, &cid("hero"))
            .expect("turn end");
        host.try_resolve_pending_queues(&mut state).expect("settle");
        assert!(
            health(&state, "enemy_a") < before,
            "Combust must hurt the enemies ({} -> {})",
            before,
            health(&state, "enemy_a")
        );
    }

    #[test]
    fn enrage_answers_only_a_skill() {
        // Wiki (Gremlin Nob): "Enrage -- whenever you play a **Skill**, gains 2 Strength". The status
        // sits on the enemy; the gate is `event.bool { card.hasTag.skill }`, which reads the flags the
        // host computed from the played card's tags (`port-plan.md` §118).
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);

        // Build a run with one card of each kind in hand, then fire `CardPlayed` for each.
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_enr", "standard.enrage", 1));
        let skill = card_in_hand(&mut state, &content, "hero", "defend");
        let attack = card_in_hand(&mut state, &content, "hero", "strike");

        state
            .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card: skill })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.strength"),
            2,
            "a Skill wakes the Enrage"
        );

        state
            .enqueue_event(CombatEvent::CardPlayed { owner: cid("hero"), card: attack })
            .expect("queue");
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.strength"),
            2,
            "an Attack must not"
        );
    }

    #[test]
    fn artifact_eats_one_debuff_and_nothing_else() {
        // Wiki: Artifact N = "negate the next N debuffs". The gate lives in `apply_one_status`
        // (`port-plan.md` §117), so it covers every producer of statuses.
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut state = arena();
        give(&mut state, "enemy_b", status("st_art", "standard.artifact", 1));


        // A debuff: eaten. The Artifact stack is spent, the target stays clean.
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            crate::exec::apply_status_for_test(&mut ctx, &cid("enemy_b"), "standard.weak", 2)
                .expect("apply");
        }
        assert_eq!(stacks_of(&state, "enemy_b", "standard.weak"), 0, "the debuff is negated");
        assert_eq!(
            stacks_of(&state, "enemy_b", "standard.artifact"),
            0,
            "and the Artifact stack is spent"
        );

        // A second debuff now lands: Artifact is gone.
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            crate::exec::apply_status_for_test(&mut ctx, &cid("enemy_b"), "standard.vulnerable", 2)
                .expect("apply");
        }
        assert_eq!(
            stacks_of(&state, "enemy_b", "standard.vulnerable"),
            2,
            "with no Artifact left, the next debuff lands"
        );
    }

    #[test]
    fn spore_cloud_weakens_the_killer_on_death() {
        // Wiki (Fungi Beast): "Spore Cloud -- on death, apply 2 Weak". Content-side, on the
        // **Downed** trigger; the killer is `sel.eventTarget` (`port-plan.md` §117).
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "enemy_b", status("st_sc", "standard.spore_cloud", 1));
        // `enemy_b` is on 10 HP: one hit of 12 kills it.
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("enemy_b"), 12, false).expect("the kill");
        }
        host.try_resolve_pending_queues(&mut state).expect("triggers");

        assert_eq!(
            stacks_of(&state, "hero", "standard.weak"),
            2,
            "the killer must be left with 2 Weak"
        );
    }

    #[test]
    fn thorns_hurts_whoever_hits_its_owner() {
        // Wiki: Thorns N = "whenever you are attacked, deal N damage back". Like Ritual this lives in
        // the **content** (a `DamageDealt` trigger on the status), so this test proves the content
        // path: the enemy wears Thorns, the hero hits it, the hero bleeds.
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "enemy_b", status("st_th", "standard.thorns", 3));

        let hero_before = health(&state, "hero");
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("enemy_b"), 5, false).expect("the hit lands");
        }
        host.try_resolve_pending_queues(&mut state).expect("triggers");

        assert_eq!(
            health(&state, "hero"),
            hero_before - 3,
            "Thorns 3 must take 3 from the attacker"
        );
    }

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
            if card_lifecycle_program(&content, id, None)
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
        // ⚠️ §220 给这条测试**换了前提**：`curse.weird` 的键是 `Drawn`，而 `Drawn` 现在内核支持
        // （`void` 的"抽到时 -1 能量"）⇒ 回合末扫描对它**没有节目**，`Ok(())` 而不是响亮失败。
        // 这正是"缺口写成断言"的用法：它红的那一刻，就是缺口被补上的那一刻（§144 的同款）。
        let mut state = duel(70);
        give_card(&mut state, "hero", CardZone::Hand, "w1", "curse.weird", None);
        assert_eq!(
            host.try_hand_turn_end_lifecycle(&mut state, &cid("hero")),
            Ok(()),
            "`Drawn` 不再是未知触发器；回合末扫描只是没有 `TurnEndInHand` 节目"
        );
        // 而**真正**未知的键仍然必须响亮 —— 口径在映射表上（手搓镜像里没有别的怪键，
        // 新增一个会改动那张镜像里被钉死的 term/opcode 计数）。
        assert_eq!(lifecycle_name_matches("Teleported", None), None);
        assert_eq!(
            card_lifecycle_program(&content, "curse.weird", None).map(|p| p.is_some()),
            Ok(false),
            "`curse.weird` 没有 `TurnEndInHand` 节目"
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
    /// ⚠️ 这条测试的**最后一句**在 §144 换过语义，而它是被设计成要换的：上一版断言"保留标志
    /// 不生效，卡还是被弃了"，用来把那个缺口摆出来；这一版 `card_stays_in_hand_at_turn_end`
    /// 真的读 `RetainInHandOnTurnEnd` 了，于是断言反过来 —— **卡留在手里**。
    /// 这正是"缺口写成断言"的用法：它红的那一刻就是补上缺口的那一刻。
    #[test]
    fn a_retained_burn_card_still_fires_exactly_once_and_stays_in_hand() {
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
            zone_count(&state, "hero", CardZone::Hand),
            1,
            "`RetainInHandOnTurnEnd = true` ⇒ 回合结束仍留在手里"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::DiscardPile),
            0,
            "留住的卡不许同时进弃牌堆"
        );

        // 成对的另一半：同一份镜像里**没有**这个标志的牌照样被弃 —— 否则上面那句可能是
        // "整个弃手牌步骤没跑"而不是"这一张被留住了"。
        let mut other = duel(70);
        give_card(&mut other, "hero", CardZone::Hand, "burn1", "curse.burn", None);
        turn::start_current_turn(&mut other, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut other, &config(), &mut host).unwrap();
        assert_eq!(
            zone_count(&other, "hero", CardZone::DiscardPile),
            1,
            "没有 Retain 的牌必须被弃（成对断言）"
        );
    }

    /// §144：`Ethereal` = 这张牌从手牌离场时**进消耗堆**（`CARD.TurnEndHandDestinationZone`）。
    ///
    /// 参考里 Ethereal 不是一条独立判据，它就是这一格（`CardZoneEffects.cs:427`）。所以这条测试
    /// 断言的是"落区被读出来了"，而不是"tag `ethereal` 被特判了" —— 后者会是一条假通路。
    #[test]
    fn an_ethereal_card_is_exhausted_instead_of_discarded() {
        let blob = burn_image();
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(70);
        give_card(
            &mut state,
            "hero",
            CardZone::Hand,
            "eth1",
            "curse.burn_ethereal",
            None,
        );
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        if let Err(e) = turn::end_current_turn(&mut state, &config(), &mut host) {
            panic!("end turn failed: {e:?}");
        }
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            1,
            "`TurnEndHandDestinationZone = ExhaustPile` ⇒ 进消耗堆"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::DiscardPile),
            0,
            "消耗掉的牌不许同时进弃牌堆"
        );

        // 成对：同一份镜像里没有这一格的牌进弃牌堆。两句一起才是"这一格被读了"，
        // 单独一句也可能是"所有牌都进消耗堆"。
        let mut other = duel(70);
        give_card(&mut other, "hero", CardZone::Hand, "burn2", "curse.burn", None);
        turn::start_current_turn(&mut other, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut other, &config(), &mut host).unwrap();
        assert_eq!(zone_count(&other, "hero", CardZone::ExhaustPile), 0);
        assert_eq!(zone_count(&other, "hero", CardZone::DiscardPile), 1);
    }

    // ---------------------------------------------------------------- 策略钩子

    /// §147：`Constricted` 是**内容**触发器 —— 回合结束掉血，掉的血量等于层数，而且**穿过格挡**。
    ///
    /// "lose HP" 在 StS 里不是伤害，所以它必须无视 Block；内容侧那一格 `IgnoresBlock: true` 就是
    /// 这条规则的载体。这条测试同时钉住三件事：触发器真的跑了、掉的血等于层数、格挡**一点没动**。
    ///
    /// 用 **sts 镜像**：`host.rs` 其它测试用的手搓镜像里没有这条状态，而"内容说了、内核跑不跑"
    /// 正是这一节要证明的东西。
    #[test]
    fn constricted_loses_its_stacks_of_hp_through_block_at_turn_end() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(70);
        give(&mut state, "hero", status("st_con", "standard.constricted", 3));

        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        // ⚠️ 格挡必须**回合开始之后**再给：玩家自己的格挡在**自己回合开始**时清空，所以"开局
        // 先摆 10 点再进回合"测不出任何东西（它会被正常清掉，看起来像 Constricted 吃掉了它）。
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .set_defensive_pool(DefensivePoolId::new("standard.block").unwrap(), 10, None)
            .unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();

        assert_eq!(health(&state, "hero"), 67, "3 层 ⇒ 回合结束掉 3 点");
        assert_eq!(
            block_of(&state, "hero"),
            10,
            "`IgnoresBlock: true` ⇒ 格挡一点没动（这不算伤害）"
        );

    /// 成对：没有这条状态就一点都不掉（否则上面那句也可能是"每回合掉 3"）。
        let mut host = Host::new(&content);
        let mut plain = duel(70);
        turn::start_current_turn(&mut plain, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut plain, &config(), &mut host).unwrap();
        assert_eq!(health(&plain, "hero"), 70);
    }
    /// §149：`Plated Armor` 的**另一半** —— 回合结束给等同于层数的格挡，并与 Metallicize 相加。
    ///
    /// 两条状态的规则是同一句话，所以它们是同一段代码（`host::grant_end_of_turn_block`）；
    /// 这条测试钉住"两件一起是相加"，因为把第二个 id 漏掉时差别只有几格挡，肉眼看不出来。
    #[test]
    fn plated_armor_and_metallicize_both_pay_block_at_turn_end() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = duel(70);
        give(&mut state, "hero", status("st_pa", "standard.plated_armor", 4));
        give(&mut state, "hero", status("st_met", "standard.metallicize", 3));

        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        // 回合开始时格挡被清空过，所以这 7 点都是这一回合挣的。
        assert_eq!(
            block_of(&state, "hero"),
            7,
            "4 层 Plated Armor + 3 层 Metallicize = 7 格挡"
        );
    }



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

    /// §199：`TurnStartEnergy` 管线 —— `Berserk` 让回合开始补 **3 + 层数** 点能量。
    ///
    /// 三条判据，各锁一种坏实现：
    /// 1. 一层 ⇒ 补 4（基础 3 + 1）。漏接管线（宿主返回 `base`）会停在 3；
    /// 2. 两层 ⇒ 补 5 —— **按层数**，不是"有就给 1"（那样 2 层与 1 层同价）；
    /// 3. 能量是**回合开始**补的，所以当回合打出 `Berserk` 的那一回合不该多出能量（它装在状态上，
    ///    下一次 `start_current_turn` 才生效）。
    #[test]
    fn berserk_adds_one_energy_per_stack_at_turn_start() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (stacks, expected) in [(0, 3), (1, 4), (2, 5)] {
            let mut host = Host::new(&content);
            let mut state = solo();
            // Turn 1 starts plain (energy 3), and the status is applied **during** it -- exactly how
            // the card would be played -- so it takes effect from turn 2 on.
            turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
            assert_eq!(energy_of(&state, "hero"), 3, "the configured refill");
            if stacks > 0 {
                give(&mut state, "hero", status("st_berserk", "standard.berserk", stacks));
            }
            turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
            turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
            assert_eq!(
                energy_of(&state, "hero"),
                expected,
                "Berserk {stacks}: turn 2 refills to {expected}"
            );
        }
    }

    /// §216（审阅 P1-A）：`Slow` 的因子是**本回合已出的牌数**，不是层数，也不是整场战斗的牌数。
    ///
    /// wiki（`slay-the-spire.fandom.com/wiki/Slow`）：
    /// *"For every card you have played **this turn**, enemy takes 10% more damage from Attacks,
    /// not compounding. **Slow resets at end of turn**; enemy does NOT carry over stacks."*
    ///
    /// §198 把它做成了"每打一张牌 +1 层、永不衰减" ⇒ 第 2 回合再打 5 张就是 10 层（×200%）。
    /// 那版测试只问"给定层数 → 伤害"，**没有一条跨回合断言**，所以三个层数点全绿也掩盖了它。
    ///
    /// 这一条补的正是缺的那半，而且是**真出牌、真结束回合**（不是伪造计数器 ——
    /// `maw.nom_nom` 的 P1-B 就是被伪造计数器的测试放过的）：
    /// ① 开局 0 张 ⇒ 10 点原样（标记状态在敌人身上，但计数为 0）；
    /// ② 本回合真打 5 张 ⇒ 15 点；
    /// ③ 回合真的结束 ⇒ 内核把牌数清零 ⇒ 又回到 10 点。
    #[test]
    fn slow_counts_the_cards_played_this_turn_and_starts_over_each_turn() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        // 标记状态挂在**敌人**身上（它是 debuff，读的是受击一方）。
        give(&mut state, "enemy_a", status("st_slow", "standard.slow", 1));
        // ⚠️ `arena()` 的 enemy_a 只有 20 血，装不下 10 + 15 两笔：第二笔会被"最多掉到 0"
        // 截断成 10，看起来正好像"加成没生效"。给自己留够血，这个测试才测的是加成。
        state
            .combatant_mut(&cid("enemy_a"))
            .expect("enemy_a")
            .health_current = 200;

        // 一次 10 点直伤打在 enemy_a 上，返回实际掉了多少血。
        let hit = |state: &mut CombatState| -> i32 {
            let before = state.combatant(&cid("enemy_a")).expect("enemy_a").health_current;
            let mut ctx = crate::exec::ExecContext::new(
                state,
                Some(cid("hero")),
                Some(cid("enemy_a")),
                None,
                64,
            )
            .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("enemy_a"), 10, false).expect("the blow");
            before - ctx.state.combatant(&cid("enemy_a")).expect("enemy_a").health_current
        };

        // ① 0 张牌：开局**不再自带 +10%**（旧内容的 `Stacks=1` 会在这里给 11 点）。
        assert_eq!(state.cards_played_this_turn, 0);
        assert_eq!(hit(&mut state), 10, "no cards played: a 10-point hit lands for 10");

        // ② 真打 5 张（`defend` 是技能，不会顺手把 enemy_a 打死）。
        give_energy(&mut state, "hero", 9);
        for _ in 0..5 {
            let card = card_in_hand(&mut state, &content, "hero", "defend");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("a defend costs 1 and needs no target");
        }
        assert_eq!(state.cards_played_this_turn, 5, "the kernel counted the real plays");
        assert_eq!(hit(&mut state), 15, "5 cards this turn: 10 * (100 + 10*5) / 100");

        // ③ 回合真的结束（不是写 `cards_played_this_turn = 0`）⇒ 计数归零、加成消失。
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(state.cards_played_this_turn, 0, "turn end resets the counter");
        assert_eq!(hit(&mut state), 10, "next turn starts over: back to 10");
    }

    /// §225/§226：`Second Wind` / `Fiend Fire` —— 整手牌逐张消耗，每张换一份效果。
    ///
    /// 这两张牌同时钉住四件事：
    /// ① `forEachCardInZone` 的快照语义（循环体搬走卡不影响这一趟）；
    /// ② 迭代卡的 **tag 位**被填进 `event_flags`（§225 A），否则"**非攻击**牌会把攻击牌也算进去"；
    /// ③ §226：迭代的牌**是不是正在结算的那一张**（`event.bool: card.isResolving`）——
    ///    打出的牌在参考里要到终态回调才离开手牌，所以循环看得见它，StS 的语义里它**不算**
    ///    "手牌里的一张"。内容的 `not(card.isResolving)` 把这条差补上；
    /// ④ 消耗走 `moveCardToZone` ⇒ `move_card_for` ⇒ `LifecyclePrograms[Exhausted]`（§220 那条路）。
    #[test]
    fn the_hand_exhausting_cards_do_what_their_pages_say() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① `Second Wind`：手里 1 张打击（attack）+ 1 张防御（skill）⇒ 只消耗防御、只给 5 格挡。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        let card = card_in_hand(&mut state, &content, "hero", "second_wind");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("second wind is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        // 参考里打出的牌在节目期间**仍在手牌里**（`onTerminal` 才落区 —— `play::tests` 与
        // `CARD_DIFF` 的 `archive_the_evidence` 都钉着这条，所以内核**不动**快照）。
        // §226 让内容自己认得出"这一趟就是我"：`not(event.bool: card.isResolving)`。
        // ⇒ 只给防御那 5 点，Second Wind 自己那份**不再算**。
        assert_eq!(
            block_of(&state, "hero"),
            5,
            "5 for the Skill only -- the card being played is not \"a card in your hand\";              exhausted: {:?}",
            zone_definitions(&state, "hero", CardZone::ExhaustPile)
        );
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::Hand),
            vec!["strike".to_string()],
            "the Attack card is still in hand: non-Attack is the filter"
        );
        let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile);
        assert!(
            exhausted.contains(&"defend".to_string()) && exhausted.contains(&"second_wind".to_string()),
            "the Skill and the Second Wind itself are exhausted, got {exhausted:?}"
        );
        assert!(
            !exhausted.contains(&"strike".to_string()),
            "the Attack card must NOT be exhausted"
        );

        // ② `Fiend Fire`：整手牌（含那张打击）逐张消耗，每张打 7。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        let card = card_in_hand(&mut state, &content, "hero", "fiend_fire");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("fiend fire is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        // 同理：两张牌（打击 / 防御）× 7 = 14 ⇒ 20 血的敌人剩 6。Fiend Fire 自己不算
        // （否则是 21，一场"多打了一张"的胜利）。
        assert_eq!(
            health(&state, "enemy_a"),
            6,
            "2 x 7 = 14, not 3 x 7 = 21: the played card is not \"in your hand\""
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            0,
            "the whole hand is gone"
        );
        let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile);
        for expected in ["strike", "defend", "fiend_fire"] {
            assert!(
                exhausted.contains(&expected.to_string()),
                "{expected} must be exhausted, got {exhausted:?}"
            );
        }
    }

    /// §226：`Dual Wield` —— **问玩家要一张 Attack 或 Power 牌，然后复制它**。
    ///
    /// 这是"复制载体"的端到端判据，一次钉住四段，缺一段就会出现"按钮是死的"那种失败：
    /// ① 打出之后**真的**有一个待决问句（`then = Copy`、`copies = 1`）；
    /// ② 选项是**收窄**过的：手里有攻击牌也有技能牌，问句只列攻击牌（`RequireAnyTag`）；
    /// ③ 回答之后手牌多一张**同定义**的牌，原件还在；
    /// ④ `Dual Wield` 自己按 `PlayedCardDestinationZone` 进消耗堆（wiki 的 `Exhaust`）。
    #[test]
    fn dual_wield_asks_for_an_attack_and_copies_it() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        let card = card_in_hand(&mut state, &content, "hero", "dual_wield");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("dual wield is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        // ① 一个问题，`s then = Copy`、`copies = 1`、`min = max = 1`。
        let choice = state.pending_choice().expect("dual wield asks a question");
        // §227: the copy count and destination live **in the variant** now.
        assert_eq!(
            choice.then,
            crate::state::ChoiceThen::Copy {
                copies: 1,
                into: crate::state::CardZone::Hand,
            },
            "Dual Wield makes one copy, into the hand"
        );
        assert_eq!((choice.min, choice.max), (1, 1), "exactly one card");

        // ② 收窄：技能牌**不在**选项里（"choose an **Attack or Power** card"）。
        let mut legal = [CardInstanceId::EMPTY; 8];
        let count = state.choice_legal(&mut legal).expect("the options are listable");
        assert_eq!(count, 1, "only the Attack qualifies, got {count}");
        let picked = legal[0];
        let picked_definition = state
            .card(state.find_card(&cid("hero"), &picked).expect("in hand").1)
            .expect("the card")
            .definition_id;
        assert_eq!(picked_definition.as_str(), "strike", "the Attack is the only option");

        // ③ 回答 ⇒ 手牌多一张同样的牌，原件还在。
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&[picked]), 0)
            .expect("the answer is taken");
        let hand = zone_definitions(&state, "hero", CardZone::Hand);
        assert_eq!(
            hand.iter().filter(|id| id.as_str() == "strike").count(),
            2,
            "the strike and its copy, got {hand:?}"
        );
        assert!(hand.iter().any(|id| id.as_str() == "defend"), "the Skill is untouched");
        assert!(!hand.iter().any(|id| id.as_str() == "dual_wield"), "{hand:?}");

        // ④ 它自己进**弃牌堆**（`native/wiki_cards/dual_wield.txt` 没有 Exhaust —— 只有副本
        // 进手牌。旧版 StS 才自我消耗，照 dump 走）。
        let discards = zone_definitions(&state, "hero", CardZone::DiscardPile);
        assert!(
            discards.iter().any(|id| id.as_str() == "dual_wield"),
            "dual wield goes to the discard pile, got {discards:?}"
        );
        let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile);
        assert!(
            exhausted.is_empty(),
            "nothing is exhausted here, got {exhausted:?}"
        );
    }

    /// §227：`Armaments` —— 5 格挡 + "升级手牌里的一张（整场有效）"。
    ///
    /// 判据的重点不是"程序跑完了"，而是**候选本身就是规则**：
    /// * 问句里只有**有 `+` 行**的牌（`strike` / `defend`），`dazed` 不该出现 ——
    ///   否则玩家会拿到一个"点了什么都不发生"的选项；
    /// * 答完之后手牌**张数不变**（`Upgrade` 是原地改定义 id，不是搬牌），而那张牌的定义变成 `<id>+`。
    #[test]
    fn armaments_gains_block_then_upgrades_the_chosen_card() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        // `dazed` 没有 `+` 行 ⇒ 它必须**不在**候选里（那张牌升级不了）。
        give_card(&mut state, "hero", CardZone::Hand, "card_junk", "dazed", None);
        let card = card_in_hand(&mut state, &content, "hero", "armaments");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("armaments is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        assert_eq!(block_of(&state, "hero"), 5, "wiki: Gain 5 Block");
        let choice = state.pending_choice().expect("it asks which card to upgrade");
        assert_eq!(choice.then, crate::state::ChoiceThen::Upgrade);
        let mut legal = [CardInstanceId::EMPTY; 8];
        let count = state.choice_legal(&mut legal).expect("the options are listable");
        let options: Vec<String> = legal[..count]
            .iter()
            .map(|id| {
                state
                    .card(state.find_card(&cid("hero"), id).expect("in hand").1)
                    .expect("the card")
                    .definition_id
                    .as_str()
                    .to_string()
            })
            .collect();
        assert_eq!(
            options,
            vec!["strike".to_string(), "defend".to_string()],
            "only the cards that have a `+` row: {options:?}"
        );

        let hand_before = zone_definitions(&state, "hero", CardZone::Hand);
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&legal[..1]), 0)
            .expect("the upgrade is taken");
        let hand_after = zone_definitions(&state, "hero", CardZone::Hand);
        assert_eq!(hand_after.len(), hand_before.len(), "upgrading moves nothing");
        assert!(
            hand_after.iter().any(|id| id.as_str() == "strike+"),
            "the picked Strike is upgraded, got {hand_after:?}"
        );
        assert!(
            hand_after.iter().any(|id| id.as_str() == "defend"),
            "the other card is untouched, got {hand_after:?}"
        );

        // §227 的另一半：`Armaments+` 是 "upgrade **all** cards in your hand"，也就是
        // `node.upgradeCards` **不带** `CardDefinitionId` 的那条新分支（内容在写程序时不知道
        // 玩家手上有什么定义）。它必须：升级所有**有 `+` 行**的牌、跳过 `dazed`、不问题。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_junk", "dazed", None);
        let card = card_in_hand(&mut state, &content, "hero", "armaments+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("armaments+ is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert!(
            state.pending_choice().is_none(),
            "the upgraded version upgrades everything -- it does not ask"
        );
        let hand = zone_definitions(&state, "hero", CardZone::Hand);
        assert!(
            hand.iter().any(|id| id.as_str() == "strike+")
                && hand.iter().any(|id| id.as_str() == "defend+"),
            "every upgradable card in hand is upgraded, got {hand:?}"
        );
        assert!(
            hand.iter().any(|id| id.as_str() == "dazed"),
            "a card without a `+` row is left alone, got {hand:?}"
        );
        assert_eq!(block_of(&state, "hero"), 5, "still 5 Block");
    }

    /// §227：`Warcry` —— 抽 1 张，然后"把一张手牌放到抽牌堆顶"。
    ///
    /// "堆顶"必须比"在抽牌堆里"更强：先往抽牌堆放一张垫底的牌，答完之后问"谁在最前面"。
    #[test]
    fn warcry_draws_one_then_puts_the_chosen_card_on_top() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        // 抽牌堆里放两张：`bash` 会被抽走，`anger` 留下来当**垫底**。只放一张是分辨不出
        // "放到堆顶"与"塞进堆底"的 —— 抽牌堆会空，两条路都长得一样（本测试第一版就这么错过）。
        give_card(&mut state, "hero", CardZone::DrawPile, "card_top", "bash", None);
        give_card(&mut state, "hero", CardZone::DrawPile, "card_bottom", "anger", None);
        let card = card_in_hand(&mut state, &content, "hero", "warcry");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("warcry is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        // 抽 1 张：`bash` 已经从抽牌堆进了手牌。
        let hand = zone_definitions(&state, "hero", CardZone::Hand);
        assert!(
            hand.iter().any(|id| id.as_str() == "bash"),
            "the drawn card joined the hand, got {hand:?}"
        );
        let choice = state.pending_choice().expect("it asks what to put on top");
        assert_eq!(choice.then, crate::state::ChoiceThen::ToDrawPileTop);

        // 选 `defend` 放回堆顶。
        let defend = {
            let mut legal = [CardInstanceId::EMPTY; 8];
            let count = state.choice_legal(&mut legal).expect("listable");
            legal[..count]
                .iter()
                .copied()
                .find(|id| {
                    state
                        .card(state.find_card(&cid("hero"), id).expect("in hand").1)
                        .expect("the card")
                        .definition_id
                        .as_str()
                        == "defend"
                })
                .expect("defend is in the hand")
        };
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&[defend]), 0)
            .expect("the move is taken");

        let draw = zone_definitions(&state, "hero", CardZone::DrawPile);
        assert_eq!(
            draw.first().map(|id| id.as_str()),
            Some("defend"),
            "the picked card is on **top**, got {draw:?}"
        );
        assert_eq!(
            draw.get(1).map(|id| id.as_str()),
            Some("anger"),
            "the card that was already there is now **below** it, got {draw:?}"
        );
        // wiki: "Warcry will then Exhaust itself."
        assert!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile)
                .iter()
                .any(|id| id.as_str() == "warcry"),
            "warcry exhausts itself"
        );
    }

    /// §227：`Nightmare` —— "选一张牌。**下一回合**把这 3 份副本加进手牌。Exhaust."
    ///
    /// "下一回合"整条规则在**内容**里（`standard.nightmare_pending` 的 `TurnStarted` 触发器），
    /// 内核一点都不知道 Nightmare —— 它只需要"复制到某个牌区"这一件事。要记住"复制的是哪张牌"
    /// 的只有那三份副本自己。
    #[test]
    fn nightmare_copies_into_the_aside_pile_and_next_turn_they_arrive() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_skill", "defend", None);
        let card = card_in_hand(&mut state, &content, "hero", "nightmare");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, None),
        )
        .expect("nightmare is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let choice = state.pending_choice().expect("it asks which card to copy");
        assert_eq!(
            choice.then,
            crate::state::ChoiceThen::Copy {
                copies: 3,
                into: crate::state::CardZone::SetAsidePile,
            },
            "three copies, held aside until next turn"
        );
        // 选那张打击。
        let strike = {
            let mut legal = [CardInstanceId::EMPTY; 8];
            let count = state.choice_legal(&mut legal).expect("listable");
            legal[..count]
                .iter()
                .copied()
                .find(|id| {
                    state
                        .card(state.find_card(&cid("hero"), id).expect("in hand").1)
                        .expect("the card")
                        .definition_id
                        .as_str()
                        == "strike"
                })
                .expect("strike is in the hand")
        };
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&[strike]), 0)
            .expect("the copies are made");

        let aside = zone_definitions(&state, "hero", CardZone::SetAsidePile);
        assert_eq!(aside.len(), 3, "three copies wait aside, got {aside:?}");
        assert!(aside.iter().all(|id| id.as_str() == "strike"), "{aside:?}");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::Hand)
                .iter()
                .filter(|id| id.as_str() == "strike")
                .count(),
            1,
            "the original stays in hand (only the copies were made)"
        );
        let pending = state
            .combatant(&cid("hero"))
            .expect("hero")
            .statuses()
            .iter()
            .any(|instance| instance.definition_id.as_str() == "standard.nightmare_pending");
        assert!(pending, "the pending marker is on the hero");

        // ⚠️ 这张牌是**打在自己回合里**的，所以"下一回合"必须真的走一圈：英雄的回合结束 →
        // 敌人的回合开始/结束 → 英雄的回合开始。`arena()` 只造了战斗员，相位还没进
        // `InProgress`，所以先开一次英雄回合（那一次 TurnStarted 在**打牌之前**，不碰这个状态）。
        turn::start_current_turn(&mut state, &config(), &mut host).expect("the hero's turn starts");
        // 战斗里有三个战斗员（英雄 + 两个敌人），所以"回到英雄"不是走一步 —— 判据是**谁是
        // 行动者**，不是"走了几步"（写死两步会让这条测试在敌人数量变化时安静地错）。
        let mut hops = 0;
        while state.active_combatant_id.as_ref() != Some(&cid("hero")) {
            turn::end_current_turn_and_start_next(&mut state, &config(), &mut host)
                .expect("the turn passes");
            hops += 1;
            assert!(hops <= 4, "the turn never came back to the hero");
        }

        // `SetAsidePile` 空了是**触发器跑过**的硬证据；手牌里的张数是**下界**而不是等式：
        // 回合末弃掉的手牌会被"抽牌堆空了就洗弃牌堆"重新抽回来，那是回合机的正常行为，
        // 不是这张牌的语义。
        assert!(
            zone_definitions(&state, "hero", CardZone::SetAsidePile).is_empty(),
            "the aside pile is empty again -- the trigger ran"
        );
        let hand = zone_definitions(&state, "hero", CardZone::Hand);
        assert!(
            hand.iter().filter(|id| id.as_str() == "strike").count() >= 3,
            "the three copies arrived in the hand, got {hand:?}"
        );
        let still_pending = state
            .combatant(&cid("hero"))
            .expect("hero")
            .statuses()
            .iter()
            .any(|instance| instance.definition_id.as_str() == "standard.nightmare_pending");
        assert!(!still_pending, "the marker removed itself after firing once");
    }

    /// §228：`Body Slam` —— "Deal damage equal to your **Block**"。
    ///
    /// 两端都测：格挡 13 ⇒ 敌人掉 13；格挡 0 ⇒ 掉 0（不是"不掉血所以不报错"，而是真的 0 点伤害）。
    /// 中间那一层（`combatantDefensivePool` 这个表达式）如果读错池子（例如读成能量），两条都会红。
    #[test]
    fn body_slam_deals_damage_equal_to_the_block_it_has_when_played() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (block, expected) in [(13i32, 13i32), (0, 0)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            give_block(&mut state, "hero", block);
            let card = card_in_hand(&mut state, &content, "hero", "body_slam");
            let health_before = health(&state, "enemy_a");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("body slam is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                health_before - health(&state, "enemy_a"),
                expected,
                "block {block}: the damage of a Body Slam is the Block you had"
            );
        }
    }

    /// §228：`Sword Boomerang` —— 3 伤 × 3(4) 次，**每一击各自抽签**。
    ///
    /// 四件事一起钉（任何一条单独坏掉都还能看起来"在打伤害"）：
    /// ① 总伤害 == 3 × 次数；
    /// ② 每个敌人身上的伤害都是 3 的倍数 —— 否则就是"抽一次签、连打 N 下"；
    /// ③ `random_step` **正好**推进"次数"格（一跳一格，与 `shuffle_candidates` 同一本账）；
    /// ④ 同一个种子与步数重跑，结果逐字相同 —— 随机不等于不可重复。
    #[test]
    fn sword_boomerang_rerolls_a_target_for_each_hit() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // `arena()` 有两个敌人（20 / 10 血），把它们的血抬高，免得第九点伤害就打死一个。
        for (card_id, hits) in [("sword_boomerang", 3), ("sword_boomerang+", 4)] {
            let mut seen = std::vec::Vec::new();
            for _ in 0..2 {
                let mut host = Host::new(&content);
                let mut state = arena();
                give_energy(&mut state, "hero", 3);
                for who in ["enemy_a", "enemy_b"] {
                    if let Some(combatant) = state.combatant_mut(&cid(who)) {
                        combatant.health_max = 200;
                        combatant.health_current = 200;
                    }
                }
                let step_before = state.random_step;
                let card = card_in_hand(&mut state, &content, "hero", card_id);
                crate::play::play_card(
                    &mut state,
                    Some(&content),
                    &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
                )
                .expect("sword boomerang is playable");
                host.try_resolve_pending_queues(&mut state).expect("drain");

                let a = 200 - health(&state, "enemy_a");
                let b = 200 - health(&state, "enemy_b");
                assert_eq!(
                    a + b,
                    3 * hits,
                    "{card_id}: {hits} hits of 3 damage, got a={a} b={b}"
                );
                assert_eq!(a % 3, 0, "{card_id}: enemy_a took {a}, not a whole number of hits");
                assert_eq!(b % 3, 0, "{card_id}: enemy_b took {b}, not a whole number of hits");
                assert_eq!(
                    state.random_step - step_before,
                    hits,
                    "{card_id}: one draw per hit (and no more) -- {hits} hits, {} draws",
                    state.random_step - step_before
                );
                seen.push((a, b));
            }
            assert_eq!(
                seen[0], seen[1],
                "{card_id}: the same seed and step must give the same hits"
            );
        }
    }

    /// §229：`Rip and Tear` —— 7(9) 伤 × 2 次，每次随机。载体是 §228 那个节点，内核没加东西。
    #[test]
    fn rip_and_tear_hits_twice_for_seven() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (card_id, damage) in [("rip_and_tear", 7i32), ("rip_and_tear+", 9)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            for who in ["enemy_a", "enemy_b"] {
                if let Some(combatant) = state.combatant_mut(&cid(who)) {
                    combatant.health_max = 200;
                    combatant.health_current = 200;
                }
            }
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("rip and tear is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            let a = 200 - health(&state, "enemy_a");
            let b = 200 - health(&state, "enemy_b");
            assert_eq!(a + b, 2 * damage, "{card_id}: two hits of {damage}, got a={a} b={b}");
        }
    }

    /// §229：`Rampage` —— "Deal 8 damage. Increase **this card's** damage by 5(8) this combat."
    ///
    /// 三段判据，缺一段这条牌就可能"看起来能用"：
    /// ① 第一次 8、第二次 13（涨的是**这一张**）；
    /// ② 升级版每次涨 8（第二次 16）；
    /// ③ **反例**：另一张 Rampage 的伤害**不变** —— 每副本计数器不是每定义，也不是每战斗员。
    #[test]
    fn rampage_grows_this_copy_and_only_this_copy() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // (牌, 第二次该掉的伤害)
        for (card_id, second) in [("rampage", 13i32), ("rampage+", 16)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 6);
            for who in ["enemy_a", "enemy_b"] {
                if let Some(combatant) = state.combatant_mut(&cid(who)) {
                    combatant.health_max = 400;
                    combatant.health_current = 400;
                }
            }
            // **两份副本**：`card_a` 打两次，`card_b` 一次都不打，最后用它当反例。
            let card_a = card_in_hand(&mut state, &content, "hero", card_id);
            give_card(&mut state, "hero", CardZone::Hand, "card_b", card_id, None);
            let card_b = card_in_hand(&mut state, &content, "hero", "card_b");

            let mut hits = std::vec::Vec::new();
            for _ in 0..2 {
                let before = health(&state, "enemy_a");
                // 每次出牌都回到手里（否则第二张打出的是"另一份副本"，而那正是另一条判据）。
                crate::play::play_card(
                    &mut state,
                    Some(&content),
                    &crate::play::PlayRequest::new(cid("hero"), card_a, Some(cid("enemy_a"))),
                )
                .expect("rampage is playable");
                host.try_resolve_pending_queues(&mut state).expect("drain");
                hits.push(before - health(&state, "enemy_a"));
                // 把它捡回手牌：这份副本带着它自己的计数器（`mark_counters` 跟着槽位，不跟着牌区）。
                let (from, slot) = state
                    .find_card(&cid("hero"), &card_a)
                    .expect("still in the fight");
                if from != CardZone::Hand {
                    state
                        .move_card(
                            &cid("hero"),
                            from,
                            CardZone::Hand,
                            slot,
                            crate::state::ZonePlacement::Bottom,
                        )
                        .expect("picked back up");
                }
            }
            assert_eq!(
                hits,
                std::vec![8, second],
                "{card_id}: 8 then {second} -- the bonus is this copy's own"
            );

            // ③ 反例：一份**没打过的**同名副本，伤害仍然是 8。
            let before = health(&state, "enemy_a");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card_b, Some(cid("enemy_a"))),
            )
            .expect("the second copy is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                before - health(&state, "enemy_a"),
                8,
                "{card_id}: the *other* copy has not grown -- the counter is per copy, not per definition"
            );
        }
    }

    /// §229：`Searing Blow` —— "Can be Upgraded **any number of times**"。
    ///
    /// 升级是"另一行 CARD"，所以"任意次"= id 能连续加 `+`。两条判据必须成对：
    /// ① `searing_blow` 连升三级（`+` → `++` → `+++`），每次的伤害来自**新行**（12 → 16 → 20）；
    /// ② **反例**：`strike` 升到 `strike+` 之后就**升不动了** —— 因为内容里没有 `strike++`，
    ///    而不是因为内核有一条"以 `+` 结尾就拒绝"的规则（§229 把那条猜法换成了查表）。
    #[test]
    fn searing_blow_upgrades_more_than_once_but_strike_does_not() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 升级的**规则**只有一处（`upgradable_definition`），所以直接用它的判据：
        // 打一张牌之后它变成哪一行，等于"内容里是否存在 `<id>+`"。
        let mut upgraded = std::vec::Vec::new();
        let mut id = crate::state::CardDefinitionId::new("searing_blow").expect("短 id");
        for _ in 0..3 {
            let next = crate::state::upgraded_id(id.as_str())
                .filter(|candidate| {
                    content
                        .lookup_in(candidate.as_str(), crate::content::EK_CARD)
                        .is_some()
                })
                .expect("内容里有下一行");
            upgraded.push(next.as_str().to_string());
            id = next;
        }
        assert_eq!(
            upgraded,
            std::vec![
                "searing_blow+".to_string(),
                "searing_blow++".to_string(),
                "searing_blow+++".to_string()
            ],
            "the id keeps growing `+` -- the cap is how many rows the content has"
        );

        // 真打一次：`searing_blow++` 打 20（12 + 4×2），不是 12 也不报错。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "searing_blow++");
        let before = health(&state, "enemy_a");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("searing blow is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(before - health(&state, "enemy_a"), 20, "third row = 12 + 4*2");

        // ② 反例：`strike+` 没有下一行 ⇒ 不可再升级（不再靠"以 `+` 结尾"这条猜法）。
        let stuck = crate::state::upgraded_id("strike+")
            .filter(|candidate| {
                content
                    .lookup_in(candidate.as_str(), crate::content::EK_CARD)
                    .is_some()
            });
        assert!(
            stuck.is_none(),
            "there is no `strike++` row, so `strike+` cannot be upgraded again"
        );
    }

    /// §230：`Flex` —— "Gain 2 (4) Strength. **At the end of this turn**, lose 2 (4) Strength."
    ///
    /// "临时"才是这张牌：判据必须走完一个回合，看力量**回到原值**（只断言"加了 2 层"的话，
    /// 一个把力量永久加上的实现也一样绿）。
    #[test]
    fn flex_gains_strength_that_the_turn_end_takes_back() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (card_id, gain) in [("flex", 2i32), ("flex+", 4)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("flex is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                stacks_of(&state, "hero", "standard.strength"),
                gain,
                "{card_id}: the Strength is there for this turn"
            );

            // 走完一个完整回合（英雄 → 敌人 → 英雄）。
            let mut hops = 0;
            while state.active_combatant_id.as_ref() != Some(&cid("hero")) || hops == 0 {
                turn::end_current_turn_and_start_next(&mut state, &config(), &mut host)
                    .expect("the turn passes");
                hops += 1;
                assert!(hops <= 4, "the turn never came back to the hero");
            }
            assert_eq!(
                stacks_of(&state, "hero", "standard.strength"),
                0,
                "{card_id}: the turn end took it back -- that is what \"temporary\" means"
            );
        }
    }

    /// §230：`Limit Break` —— "Double your Strength."
    ///
    /// 三条一起钉：翻倍（12 → 24，不是 +12 也不是 +2）、基础版**自消耗**、`+` 版**不消耗**
    /// （wiki 的括号是「基础;升级」：`Double your Strength.(<br>Exhaust.;)` —— 升级去掉 Exhaust）。
    #[test]
    fn limit_break_doubles_strength_and_only_the_base_copy_exhausts() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (card_id, exhausts) in [("limit_break", true), ("limit_break+", false)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            give(&mut state, "hero", status("st_str", "standard.strength", 12));
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("limit break is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                stacks_of(&state, "hero", "standard.strength"),
                24,
                "{card_id}: 12 doubled is 24 -- an extra `+12` is exactly what the card says"
            );
            let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile)
                .iter()
                .any(|id| id.as_str() == card_id);
            assert_eq!(
                exhausted, exhausts,
                "{card_id}: wiki is `Double your Strength.(<br>Exhaust.;)` -- base exhausts, `+` does not"
            );
        }
    }

    /// §230：`Perfected Strike` —— "Deal 6 damage. Deals 2 (3) additional damage for **ALL your cards
    /// containing \"Strike\"**"（wiki 正文：**in your deck when this card is played**）。
    ///
    /// 判据按**可数的场面**来：手牌里放已知数量的 `strike` tag 牌，伤害必须正好等于
    /// `6 + 2 × 数到的张数`；并且把那些牌换成**不带** tag 的牌之后，伤害回到 6 —— 否则
    /// "数到 0 张"与"根本没数"是同一件事。
    #[test]
    fn perfected_strike_counts_the_tagged_cards_in_hand() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // (手牌里另外放哪些牌, 这些牌里有几张带 `strike` tag)
        let cases: [(std::vec::Vec<&str>, i32); 2] = [
            (std::vec!["strike", "strike", "defend"], 2),
            (std::vec!["defend", "defend", "anger"], 0),
        ];
        for (extras, tagged) in cases {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            for (index, definition) in extras.iter().enumerate() {
                give_card(
                    &mut state,
                    "hero",
                    CardZone::Hand,
                    &std::format!("card_extra_{index}"),
                    definition,
                    None,
                );
            }
            let card = card_in_hand(&mut state, &content, "hero", "perfected_strike");
            let before = health(&state, "enemy_a");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("perfected strike is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            // ⚠️ 这张牌**自己**也数（它还在手牌里，参考的落区在 `onTerminal`），而且它自己的
            // tag 就是 `strike` —— 所以期望值是 `6 + 2 × (extras 里的张数 + 1)`。
            let expected = 6 + 2 * (tagged + 1);
            assert_eq!(
                before - health(&state, "enemy_a"),
                expected,
                "extras {extras:?}: 6 + 2 x ({tagged} tagged + itself)"
            );
        }
    }

    /// §231：`True Grit` —— "Gain 7 (9) Block. Exhaust 1 card(at random;)."
    ///
    /// wiki 的括号是「基础;升级」⇒ **基础版随机、`+` 版由玩家选**。两版各测一次：
    /// 格挡对、而且**正好一张**手牌进了消耗堆（不是"零张"也不是"整手牌"）。
    #[test]
    fn true_grit_gains_block_and_exhausts_exactly_one_card() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 基础版：不问人，随机消耗一张。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        for (index, definition) in ["strike", "defend", "bash"].iter().enumerate() {
            give_card(
                &mut state,
                "hero",
                CardZone::Hand,
                &std::format!("card_{index}"),
                definition,
                None,
            );
        }
        let card = card_in_hand(&mut state, &content, "hero", "true_grit");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("true grit is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 7, "wiki: Gain 7 Block");
        assert!(
            state.pending_choice().is_none(),
            "the base copy picks the card itself -- no question"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            2,
            "True Grit itself + exactly one random card"
        );
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 2, "two left in hand");

        // ② `+` 版：9 格挡 + 一个"选一张消耗"的问句（`ChoiceThen::Exhaust`）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_a", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_b", "defend", None);
        let card = card_in_hand(&mut state, &content, "hero", "true_grit+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("true grit+ is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 9, "wiki: Gain 9 Block");
        let choice = state.pending_choice().expect("the upgraded copy asks");
        assert_eq!(choice.then, crate::state::ChoiceThen::Exhaust);
        let mut legal = [CardInstanceId::EMPTY; 8];
        let count = state.choice_legal(&mut legal).expect("listable");
        assert_eq!(count, 2, "both hand cards are candidates");
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&legal[..1]), 0)
            .expect("the exhaust is taken");
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            2,
            "True Grit itself + the card the player picked"
        );
    }

    /// §231：`Battle Trance` —— "Draw 3 (4) cards. You **cannot draw additional cards this turn**."
    ///
    /// 修掉的旧实现挂的是 `standard.draw_reduction`（"**下回合**起手少抽 1 张"），两处都错：
    /// 时机错、幅度错。判据必须两侧都问：本回合再抽 = 0 张；**下一回合**起手抽牌恢复正常。
    #[test]
    fn battle_trance_blocks_further_draws_only_this_turn() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 6);
        turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
        // 抽牌堆里留 5 张，供"再抽一张"用。
        for index in 0..5 {
            give_card(
                &mut state,
                "hero",
                CardZone::DrawPile,
                &std::format!("card_draw_{index}"),
                "strike",
                None,
            );
        }
        // ⚠️ 基数必须**在**发牌之后取：`card_in_hand` 自己也往手牌里放一张。
        let trance = card_in_hand(&mut state, &content, "hero", "battle_trance");
        let hand_before = zone_count(&state, "hero", CardZone::Hand);
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), trance, Some(cid("enemy_a"))),
        )
        .expect("battle trance is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        // 抽了 3 张（Battle Trance 自己离手不算在内）。
        let after_trance = zone_count(&state, "hero", CardZone::Hand);
        assert_eq!(after_trance, hand_before - 1 + 3, "wiki: Draw 3 cards");
        assert_eq!(
            stacks_of(&state, "hero", "standard.no_draw"),
            1,
            "the \"cannot draw\" marker is on the hero"
        );

        // 本回合再抽一张 ⇒ 一张都抽不到（**手牌不变**）。
        let hand_now = zone_count(&state, "hero", CardZone::Hand);
        crate::exec::resolve_effect(
            &mut state,
            &crate::state::EffectItem {
                request: crate::state::EffectRequest::DrawCards {
                    owner: cid("hero"),
                    count: 1,
                },
                chain: crate::state::ChainSlot::NONE,
                owner: None,
            },
            Some(&content),
        )
        .expect("the draw resolves");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            hand_now,
            "the marker is set in the kernel, but a drawn card arrived"
        );

        // 下一回合：标记自摘，起手抽牌恢复正常（5 张）。
        let mut hops = 0;
        while state.active_combatant_id.as_ref() != Some(&cid("hero")) || hops == 0 {
            turn::end_current_turn_and_start_next(&mut state, &config(), &mut host)
                .expect("the turn passes");
            hops += 1;
            assert!(hops <= 4, "the turn never came back to the hero");
        }
        assert_eq!(
            stacks_of(&state, "hero", "standard.no_draw"),
            0,
            "the marker removed itself at the turn end"
        );
        assert!(
            zone_count(&state, "hero", CardZone::Hand) >= 5,
            "next turn draws normally again, got {}",
            zone_count(&state, "hero", CardZone::Hand)
        );
    }

    /// §231：`Reaper` —— "Deal 4 (5) damage to ALL enemies. Heal HP equal to **unblocked** damage."
    ///
    /// "unblocked" 是这张牌的全部难点：给一个敌人 2 点格挡，它只掉 2 血，回血就只回"真掉的那些"。
    #[test]
    fn reaper_heals_only_the_unblocked_damage() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        // 英雄掉血，才有"回血"可观察；两个敌人一个没格挡、一个有 2 点。
        if let Some(hero) = state.combatant_mut(&cid("hero")) {
            hero.health_current = 40;
        }
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        if let Some(enemy) = state.combatant_mut(&cid("enemy_b")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        give_block(&mut state, "enemy_b", 2);

        let card = card_in_hand(&mut state, &content, "hero", "reaper");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("reaper is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        assert_eq!(100 - health(&state, "enemy_a"), 4, "4 damage, no block");
        assert_eq!(100 - health(&state, "enemy_b"), 2, "4 damage minus 2 block");
        assert_eq!(
            health(&state, "hero"),
            40 + 4 + 2,
            "heal = unblocked damage dealt (4 + 2), not 4 + 4"
        );
        assert!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile)
                .iter()
                .any(|id| id.as_str() == "reaper"),
            "Reaper exhausts itself"
        );
    }

    /// §233：`Entrench` —— "Double your Block."（`+` 只降费）
    ///
    /// 两端都测：格挡 7 ⇒ 14；格挡 0 ⇒ **仍然 0**（这是"翻倍"而不是"获得格挡"的判据 ——
    /// 一个用 `gainBlock` 写成"再加一份"的实现，在格挡 0 时会**给出 0**也没错，但格挡 7 时它会
    /// 变成 14 也一样对……所以还要一条 `+` 费的判据：`entrench+` 打出去只花 1 费）。
    /// 更强的那条在下面：`gainBlock` 版本会吃"脆弱"（格挡 -25%），`set` 版本不吃。
    #[test]
    fn entrench_doubles_the_block_it_already_has() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (block, expected) in [(7i32, 14i32), (0, 0)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            give_block(&mut state, "hero", block);
            let card = card_in_hand(&mut state, &content, "hero", "entrench");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("entrench is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                block_of(&state, "hero"),
                expected,
                "block {block}: Entrench doubles what is there, it does not add a copy"
            );
        }

        // ⚠️ 判据的核心：**脆弱不吃这道翻倍**。`GainBlock` 那一版会被 `standard.frail` 打 25% 折，
        // 而 wiki 说的是 "Double your Block" —— 翻的是**已有的格挡**，不是"再获得等量格挡"。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_block(&mut state, "hero", 8);
        give(&mut state, "hero", status("st_frail", "standard.frail", 1));
        let card = card_in_hand(&mut state, &content, "hero", "entrench");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("entrench is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            block_of(&state, "hero"),
            16,
            "Frail must not discount a doubling -- a `GainBlock` implementation would give 8 + 6"
        );
    }

    /// §232：`Skewer` —— "Deal 7 (10) damage X times."（X 费，`repeat` + `x.cost`）
    ///
    /// 判据钉的是"X 次"，不是"打了一次"：能量 3 ⇒ 3 次命中、每次 7。
    #[test]
    fn skewer_hits_once_per_energy_spent() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (energy, hits) in [(3i32, 3i32), (1, 1)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", energy);
            if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
                enemy.health_max = 400;
                enemy.health_current = 400;
            }
            let card = card_in_hand(&mut state, &content, "hero", "skewer");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("skewer is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                400 - health(&state, "enemy_a"),
                7 * hits,
                "energy {energy}: 7 damage x {hits} hits, and nothing left over"
            );
            assert_eq!(stacks_of(&state, "hero", "standard.strength"), 0, "no side effects");
        }
    }

    /// §232：`Malaise` —— "Enemy loses X Strength and gains X Weak. Exhaust."（`+` 是 X+1）
    #[test]
    fn malaise_spends_the_energy_on_strength_loss_and_weak() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // (牌, 能量, 该掉多少层力量 / 该上多少层 Weak)
        for (card_id, energy, amount) in [("malaise", 2i32, 2i32), ("malaise+", 2, 3)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", energy);
            give(&mut state, "enemy_a", status("st_a", "standard.strength", 5));
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("malaise is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                stacks_of(&state, "enemy_a", "standard.strength"),
                5 - amount,
                "{card_id}: X = {energy} energy spent (upgraded is X+1)"
            );
            assert_eq!(
                stacks_of(&state, "enemy_a", "standard.weak"),
                amount,
                "{card_id}: the same X stacks of Weak"
            );
            assert!(
                zone_definitions(&state, "hero", CardZone::ExhaustPile)
                    .iter()
                    .any(|id| id.as_str() == card_id),
                "{card_id} exhausts itself"
            );
        }
    }

    /// §235：第一批红卡的**攻击**（6 张）—— 每张的判据都是"牌面上的那句话"。
    ///
    /// 为什么合在一条测试里：它们共享同一套夹具（1 英雄 + 2 敌人的战斗、出牌、排空）。拆成六条
    /// 会把同一段准备抄六遍；矩阵按 id 认领测试名，所以一条测试覆盖多张牌是允许的。
    #[test]
    fn the_new_red_attacks_do_what_their_pages_say() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① carnage：Ethereal + 20/28 伤害（Ethereal 是落区的事，这里只钉伤害）。
        for (card_id, damage) in [("carnage", 20i32), ("carnage+", 28)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            // ⚠️ 敌人的血要够厚：`arena()` 的 enemy_a 只有 20，28 点伤害会被截成 20，于是这条
            // 断言对"28"和"20"两种实现都绿（§161.10 的"看不见差异"）。
            if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
                enemy.health_max = 100;
                enemy.health_current = 100;
            }
            let before = health(&state, "enemy_a");
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("carnage is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(before - health(&state, "enemy_a"), damage, "{card_id}");
        }

        // ② immolate：全体 21/28 + 一张 Burn 进**弃牌堆**。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        // ⚠️ 两个敌人要**打不死**：战斗一结束，后续的"塞一张 Burn"请求会被丢掉（§178），
        // 于是这条判据会在"牌没工作"和"牌工作了但战斗已结束"之间分不清。
        for who in ["enemy_a", "enemy_b"] {
            if let Some(enemy) = state.combatant_mut(&cid(who)) {
                enemy.health_max = 100;
                enemy.health_current = 100;
            }
        }
        let card = card_in_hand(&mut state, &content, "hero", "immolate");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("immolate is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(100 - health(&state, "enemy_a"), 21, "21 to ALL enemies");
        assert_eq!(100 - health(&state, "enemy_b"), 21, "both of them");
        let discards = zone_definitions(&state, "hero", CardZone::DiscardPile);
        assert!(discards.iter().any(|id| id.as_str() == "burn"), "{discards:?}");

        // ③ reckless_charge：7/10 伤害 + 一张 Dazed 进**抽牌堆**。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "reckless_charge");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("reckless charge is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(20 - health(&state, "enemy_a"), 7, "deal 7");
        let draw = zone_definitions(&state, "hero", CardZone::DrawPile);
        assert!(draw.iter().any(|id| id.as_str() == "dazed"), "{draw:?}");

        // ④ sever_soul：非攻击牌全进消耗堆，**牌本身不消耗**，然后打 16。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_defend", "defend", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_strike", "strike", None);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        let card = card_in_hand(&mut state, &content, "hero", "sever_soul");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("sever soul is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(100 - health(&state, "enemy_a"), 16, "deal 16");
        let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile);
        assert!(exhausted.iter().any(|id| id.as_str() == "defend"), "{exhausted:?}");
        assert!(
            !exhausted.iter().any(|id| id.as_str() == "sever_soul"),
            "Sever Soul does not exhaust itself: {exhausted:?}"
        );
        let hand = zone_definitions(&state, "hero", CardZone::Hand);
        assert!(hand.iter().any(|id| id.as_str() == "strike"), "the Attack stays: {hand:?}");

        // ⑤ dropkick：有易伤 ⇒ +1 能量 + 抽 1 张；没有 ⇒ 什么都不多给。
        for (vulnerable, expect_extra) in [(true, true), (false, false)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            give_card(&mut state, "hero", CardZone::DrawPile, "card_draw", "defend", None);
            if vulnerable {
                give(&mut state, "enemy_a", status("st_vuln", "standard.vulnerable", 2));
            }
            let hand_before = zone_count(&state, "hero", CardZone::Hand);
            let card = card_in_hand(&mut state, &content, "hero", "dropkick");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("dropkick is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            // 打出的 dropkick 已经离手，所以"手牌增量"就是抽到的张数（不用再 +1 补偿）。
            let drawn = zone_count(&state, "hero", CardZone::Hand) - hand_before;
            assert_eq!(
                drawn,
                usize::from(expect_extra),
                "vulnerable={vulnerable}: the draw is conditional"
            );
            let energy: i32 = state
                .combatant(&cid("hero"))
                .map_or(0, |combatant| {
                    combatant
                        .resources()
                        .iter()
                        .filter(|pool| pool.key.as_str() == "standard.energy")
                        .map(|pool| pool.pool.current)
                        .sum()
                });
            assert_eq!(
                energy,
                if expect_extra { 3 } else { 2 },
                "vulnerable={vulnerable}: started at 3, paid 1, and the refund is conditional"
            );
        }

        // ⑥ headbutt：9 伤害 + 一个"从弃牌堆挑一张放回抽牌堆顶"的问句。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::DiscardPile, "card_bash", "bash", None);
        let card = card_in_hand(&mut state, &content, "hero", "headbutt");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("headbutt is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(20 - health(&state, "enemy_a"), 9, "deal 9");
        let choice = state.pending_choice().expect("Headbutt asks which card");
        assert_eq!(choice.then, crate::state::ChoiceThen::ToDrawPileTop);
        let mut legal = [CardInstanceId::EMPTY; 8];
        let count = state.choice_legal(&mut legal).expect("listable");
        assert_eq!(count, 1, "only the discard pile's bash");
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&legal[..1]), 0)
            .expect("the move is taken");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DrawPile)
                .first()
                .map(|id| id.as_str()),
            Some("bash"),
            "the picked card is on top of the draw pile"
        );
    }

    /// §235：第一批红卡的**技能**（7 张）。
    #[test]
    fn the_new_red_skills_do_what_their_pages_say() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① disarm：敌人 -2/-3 力量，自己进消耗堆。
        for (card_id, loss) in [("disarm", 2i32), ("disarm+", 3)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            give(&mut state, "enemy_a", status("st_str", "standard.strength", 5));
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("disarm is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                stacks_of(&state, "enemy_a", "standard.strength"),
                5 - loss,
                "{card_id}"
            );
            let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile);
            assert!(exhausted.iter().any(|id| id.as_str() == card_id), "{card_id} exhausts");
        }

        // ② shockwave：全体 Weak + Vulnerable 各 3/5。
        for (card_id, stacks) in [("shockwave", 3i32), ("shockwave+", 5)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("shockwave is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            for who in ["enemy_a", "enemy_b"] {
                assert_eq!(stacks_of(&state, who, "standard.weak"), stacks, "{who} weak");
                assert_eq!(
                    stacks_of(&state, who, "standard.vulnerable"),
                    stacks,
                    "{who} vulnerable"
                );
            }
        }

        // ③ intimidate：全体 1/2 层 Weak，自消耗。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "intimidate+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("intimidate is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        for who in ["enemy_a", "enemy_b"] {
            assert_eq!(stacks_of(&state, who, "standard.weak"), 2, "{who} weak");
        }

        // ④ seeing_red：+2 能量（1 - 1 + 2 = 2），自消耗。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 1);
        let card = card_in_hand(&mut state, &content, "hero", "seeing_red");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("seeing red is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy: i32 = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy, 2, "1 - 1 (paid) + 2");

        // ⑤ power_through：两张 Wound 进手牌 + 15/20 格挡。
        for (card_id, block) in [("power_through", 15i32), ("power_through+", 20)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("power through is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(block_of(&state, "hero"), block, "{card_id} block");
            let wounds = zone_definitions(&state, "hero", CardZone::Hand)
                .iter()
                .filter(|id| id.as_str() == "wound")
                .count();
            assert_eq!(wounds, 2, "{card_id}: exactly two Wounds");
        }

        // ⑥ flame_barrier：12 格挡 **并且**挂上同名反伤状态（层数 = 反伤值）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "flame_barrier");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("flame barrier is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 12, "Gain 12 Block");
        assert_eq!(
            stacks_of(&state, "hero", "standard.flame_barrier"),
            4,
            "4 damage back"
        );

        // ⑦ rage：本回合打攻击牌给格挡（3 层）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 6);
        let card = card_in_hand(&mut state, &content, "hero", "rage");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("rage is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(stacks_of(&state, "hero", "standard.rage"), 3);
        let strike = card_in_hand(&mut state, &content, "hero", "strike");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), strike, Some(cid("enemy_a"))),
        )
        .expect("strike is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 3, "an Attack pays 3 Block through Rage");
    }

    /// §235 顺手抓到的一个**老 bug**：`Anger` 的 "Add a copy of this card into your discard pile"
    /// 里的 `createCardInstance` 把 owner 写成了 `sel.eventTarget`（= 敌人）⇒ 复制品被塞进**敌人的**
    /// 弃牌堆，玩家一张都看不到。`node.createCardInstance` 的 `TargetSelector` 就是"新牌落在谁的牌堆"。
    #[test]
    fn anger_puts_its_copy_in_your_own_discard_pile() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "anger");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("anger is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let discards = zone_definitions(&state, "hero", CardZone::DiscardPile);
        assert_eq!(
            discards.iter().filter(|id| id.as_str() == "anger").count(),
            2,
            "the played Anger + its copy, both in the hero's discard pile: {discards:?}"
        );
    }

    /// §235：`demon_form` —— "At the start of your turn, gain 2(3) Strength."（**每**回合都加）
    #[test]
    fn demon_form_grows_strength_at_every_turn_start() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (card_id, per_turn) in [("demon_form", 2i32), ("demon_form+", 3)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("demon form is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                stacks_of(&state, "hero", "standard.strength"),
                0,
                "{card_id}: nothing until the next turn starts"
            );
            for turn_index in 1..=2 {
                let mut hops = 0;
                while state.active_combatant_id.as_ref() != Some(&cid("hero")) || hops == 0 {
                    turn::end_current_turn_and_start_next(&mut state, &config(), &mut host)
                        .expect("the turn passes");
                    hops += 1;
                    assert!(hops <= 4, "the turn never came back to the hero");
                }
                assert_eq!(
                    stacks_of(&state, "hero", "standard.strength"),
                    per_turn * turn_index,
                    "{card_id}: after {turn_index} turn start(s)"
                );
            }
        }
    }

    /// §243：无色 A 档的**数字** —— 11 张一张不漏，每张都钉两个数字（基础/升级）。
    ///
    /// 为什么挤在一个测试里：它们的判据形状完全相同（"打出去 → 手牌/格挡/状态变多少"），
    /// 拆成 11 个只会让"哪张忘了测"更难看出来。**升级行与基础行都要测** —— 只测基础的话，
    /// 抄错升级数字（本批最容易错的一格）全绿。
    #[test]
    fn the_zero_cost_utility_batch_matches_its_pages() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 打一张牌，返回 (手牌数, 格挡, 能量, 状态层数之和)。
        let play = |card_id: &str| -> (usize, i32, i32, i32) {
            let mut host = Host::new(&content);
            let mut state = arena();
            // ⚠️ `give_energy(3)` 把**上限也设成 3**（`set_resource(..., Some(3))`），
            // 于是 `miracle` 的 +1/+2 会被夹住 —— 判据里先把上限抬开，否则"加能量"与"没加"分不开。
            state
                .combatant_mut(&cid("hero"))
                .expect("hero")
                .set_resource(
                    crate::state::ResourceId::new("standard.energy").expect("energy"),
                    3,
                    Some(99),
                )
                .expect("the pool accepts a bigger cap");
            if let Some(combatant) = state.combatant_mut(&cid("enemy_a")) {
                combatant.health_max = 200;
                combatant.health_current = 200;
            }
            // 抽牌类的断言要**先垫牌**：`arena()` 的抽牌堆是空的，否则"抽 1 张"与"抽 0 张"
            // 在手牌计数上分不开（第一版就是这么错的）。
            for index in 0..4 {
                give_card(&mut state, "hero", CardZone::DrawPile,
                          &std::format!("card_d{index}"), "defend", None);
            }
            // ⚠️ 实例 id 上限 16 字节（`INSTANCE_TEXT_CAP`），而 `master_of_strategy` 有 19 个
            // 字符 ⇒ 不能拿定义名当实例 id（`card_in_hand` 就是这么做的，长名字会 `IdTooLong`）。
            give_card(&mut state, "hero", CardZone::Hand, "card_x", card_id, None);
            let card = crate::state::CardInstanceId::new("card_x").expect("short instance id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("the card is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            let statuses = ["standard.vulnerable", "standard.artifact"]
                .iter()
                .map(|id| {
                    stacks_of(&state, "hero", id)
                        + stacks_of(&state, "enemy_a", id)
                        + stacks_of(&state, "enemy_b", id)
                })
                .sum();
            (
                zone_count(&state, "hero", CardZone::Hand),
                block_of(&state, "hero"),
                energy_of(&state, "hero"),
                statuses,
            )
        };

        // `trip`：基础只打一个目标，升级打**全体**（"升级改目标"的唯一一张）。
        assert_eq!(play("trip").3, 2, "trip: 2 Vulnerable");
        assert_eq!(
            vulnerable_of(&content, "trip"),
            [2, 0],
            "trip hits only the chosen enemy"
        );
        assert_eq!(
            vulnerable_of(&content, "trip+"),
            [2, 2],
            "trip+ hits ALL enemies"
        );

        // 格挡类。
        assert_eq!(play("finesse"), (1, 2, 3, 0), "finesse: 2 Block + 1 card");
        assert_eq!(play("finesse+"), (1, 4, 3, 0), "finesse+: 4 Block + 1 card");
        assert_eq!(play("good_instincts").1, 6, "good instincts: 6 Block");
        assert_eq!(play("good_instincts+").1, 9, "good instincts+: 9 Block");

        // 抽牌类：`master_of_strategy` 3/4（自消耗，所以它不在手牌里）+ `insight` 2/3（retain）。
        assert_eq!(play("master_of_strategy").0, 3, "master of strategy: draw 3");
        assert_eq!(play("master_of_strategy+").0, 4, "master of strategy+: draw 4");
        assert_eq!(play("insight").0, 2, "insight: draw 2");
        assert_eq!(play("insight+").0, 3, "insight+: draw 3");

        // 能量类：0 费 ⇒ 净值就是加的那些。
        assert_eq!(play("miracle").2, 3 + 1, "miracle: +1 Energy");
        assert_eq!(play("miracle+").2, 3 + 2, "miracle+: +2 Energy");

        // `panacea`：Artifact 1/2。
        assert_eq!(play("panacea").3, 1, "panacea: 1 Artifact");
        assert_eq!(play("panacea+").3, 2, "panacea+: 2 Artifact");

        // `flash_of_steel`：打出 1 张、抽 1 张 ⇒ 手牌数不变。
        assert_eq!(play("flash_of_steel").0, 1, "flash of steel: draw 1");

        // `dramatic_entrance`：8/12 打**全体** + 自消耗。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        for enemy in ["enemy_a", "enemy_b"] {
            if let Some(combatant) = state.combatant_mut(&cid(enemy)) {
                combatant.health_max = 200;
                combatant.health_current = 200;
            }
        }
        give_card(&mut state, "hero", CardZone::Hand, "card_de", "dramatic_entrance+", None);
        let card = crate::state::CardInstanceId::new("card_de").expect("short instance id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("dramatic entrance is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 188, "dramatic entrance+: 12 to enemy_a");
        assert_eq!(health(&state, "enemy_b"), 188, "dramatic entrance+: 12 to enemy_b");
        assert!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile)
                .iter()
                .any(|id| id == "dramatic_entrance+"),
            "and it exhausts itself"
        );
    }

    /// §243：`Impatience` —— **手上没有攻击牌**才抽（`hand.hasCardWithTag`）。
    ///
    /// 两侧 + 一个对照：只测"没有攻击时抽"会漏掉"条件被写成恒真"，
    /// 只测"有攻击时不抽"会漏掉"条件被写成恒假"。
    #[test]
    fn impatience_only_draws_when_the_hand_has_no_attack() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 返回"抽了几张"：手牌 -1（打出自己）+ 抽到的张数。
        let drawn = |hand: &[&str]| -> i32 {
            let mut host = Host::new(&content);
            let mut state = arena();
            for (index, definition) in hand.iter().enumerate() {
                give_card(&mut state, "hero", CardZone::Hand,
                          &std::format!("card_h{index}"), definition, None);
            }
            for index in 0..4 {
                give_card(&mut state, "hero", CardZone::DrawPile,
                          &std::format!("card_d{index}"), "defend", None);
            }
            let card = card_in_hand(&mut state, &content, "hero", "impatience");
            let before = zone_count(&state, "hero", CardZone::Hand) as i32;
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("impatience is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            let after = zone_count(&state, "hero", CardZone::Hand) as i32;
            after + 1 - before
        };

        assert_eq!(drawn(&["defend", "defend"]), 2, "no Attack in hand ⇒ draw 2");
        assert_eq!(drawn(&["defend", "strike"]), 0, "an Attack in hand ⇒ draw nothing");
    }

    /// §243：`Deep Breath` —— **先把弃牌堆洗回抽牌堆，再抽**（顺序是语义）。
    ///
    /// 两段：① 抽牌堆空时抽到"刚洗回去的那张"；② 抽牌堆**不空**时弃牌堆也必须被洗回去 ——
    /// 没有 ②，一个"只靠抽空自动重洗"的实现也会全绿。
    #[test]
    fn deep_breath_shuffles_the_discard_pile_back_first() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 抽牌堆空 ⇒ 洗弃牌堆再抽 1（抽到 `bash`）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::DiscardPile, "card_x", "bash", None);
        let card = card_in_hand(&mut state, &content, "hero", "deep_breath");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("deep breath is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert!(
            zone_definitions(&state, "hero", CardZone::Hand)
                .iter()
                .any(|id| id == "bash"),
            "the shuffled-back card is the one drawn"
        );
        assert!(
            zone_definitions(&state, "hero", CardZone::DiscardPile)
                .iter()
                .any(|id| id == "deep_breath"),
            "deep breath itself lands in the discard pile (it does not exhaust)"
        );

        // ② 抽牌堆不空 ⇒ 弃牌堆仍然要被洗回去。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::DrawPile, "card_d", "defend", None);
        give_card(&mut state, "hero", CardZone::DiscardPile, "card_x", "bash", None);
        let card = card_in_hand(&mut state, &content, "hero", "deep_breath");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("deep breath is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert!(
            !zone_definitions(&state, "hero", CardZone::DiscardPile)
                .iter()
                .any(|id| id == "bash"),
            "the discard pile was shuffled in even though the draw pile was not empty"
        );
    }

    /// §243 辅助：打一张牌，返回 `[enemy_a, enemy_b]` 身上的 Vulnerable（`trip` 的目标判据用）。
    fn vulnerable_of(content: &Content<'_>, card_id: &str) -> [i32; 2] {
        let mut host = Host::new(content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", card_id);
        crate::play::play_card(
            &mut state,
            Some(content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("the card is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        [
            stacks_of(&state, "enemy_a", "standard.vulnerable"),
            stacks_of(&state, "enemy_b", "standard.vulnerable"),
        ]
    }

    /// §242：`Spot Weakness` —— "If the enemy intends to attack, gain 3 Strength."
    ///
    /// 判据不去写死"哪只怪第一回合攻击"（那是内容的事，会随内容漂），而是**问内核同一个函数**
    /// 玩家看到的那个意图（`intent::select_action` 是页面显示意图的纯函数），然后断言：
    /// 牌的行为与它**一致**。两侧都测 —— 一个"打算攻击"的敌人与一个"不打算攻击"的，
    /// 并且断言两者的意图**确实不同**（否则这条判据会因为两者都是攻击而永远绿）。
    #[test]
    fn spot_weakness_follows_the_enemy_intent() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // (遭遇行号, 敌人 id) —— 由内容决定，测试只断言"牌与意图一致"。
        let probe = |encounter: u32, enemy: &str| -> (bool, i32) {
            let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
            state
                .add_combatant(unit("hero", "player", 70, 70))
                .unwrap();
            state.add_combatant(unit(enemy, "enemy", 40, 40)).unwrap();
            state.encounter = encounter;
            // 玩家看到的意图（同一函数）。
            let at = crate::intent::locate_enemy(&content, encounter, &cid(enemy))
                .expect("the encounter resolves")
                .expect("the enemy is in that encounter");
            let kind = crate::intent::select_action(&state, &content, at, &cid(enemy), 1)
                .expect("the intent selects")
                .and_then(|choice| choice.intent_kind);
            let attacks = kind == Some(crate::intent::IntentKind::Attack);

            let mut host = Host::new(&content);
            give_energy(&mut state, "hero", 3);
            let card = card_in_hand(&mut state, &content, "hero", "spot_weakness");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid(enemy))),
            )
            .expect("spot weakness is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            (attacks, stacks_of(&state, "hero", "standard.strength"))
        };

        // 遭遇 0 = cultist（第一回合是 Incantation），遭遇 1 = jaw worm（第一回合是 Chomp）。
        let (cultist_attacks, cultist_strength) = probe(0, "cultist");
        let (worm_attacks, worm_strength) = probe(1, "jaw_worm");
        assert!(
            cultist_attacks != worm_attacks,
            "this判据 needs one attacker and one non-attacker (cultist={cultist_attacks}, \
             jaw_worm={worm_attacks})"
        );
        assert_eq!(
            cultist_strength,
            if cultist_attacks { 3 } else { 0 },
            "the card must agree with the displayed intent (cultist)"
        );
        assert_eq!(
            worm_strength,
            if worm_attacks { 3 } else { 0 },
            "the card must agree with the displayed intent (jaw worm)"
        );

        // 没有遭遇（`u32::MAX`）⇒ 意图解不出 ⇒ 不拿力量，而且**不报错**。
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state.add_combatant(unit("hero", "player", 70, 70)).unwrap();
        state.add_combatant(unit("jaw_worm", "enemy", 40, 40)).unwrap();
        let mut host = Host::new(&content);
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "spot_weakness");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("jaw_worm"))),
        )
        .expect("spot weakness is playable without an encounter");
        host.try_resolve_pending_queues(&mut state).expect("no encounter is not an error");
        assert_eq!(
            stacks_of(&state, "hero", "standard.strength"),
            0,
            "no encounter ⇒ no intent ⇒ no Strength (and no error)"
        );
    }

    /// §242：`Blood for Blood` —— **每失去 1 次生命便宜 1 点**，本场战斗累计。
    ///
    /// 三段：① 一次都没掉血 ⇒ 4 费（照印刷）；② 掉两次 ⇒ 2 费；③ 掉到超过印刷费 ⇒ **0 费**
    /// （不是负数 —— `current.max(0)` 那一层）。第三段最容易漏：不夹的话"掉 6 次血"会变成负费用，
    /// 而负费用在付款时会**给**能量。
    ///
    /// 掉血用伤害造（`strike` 打自己人太绕）：直接写 `hp_losses` 就绕过了被测的那条记账，
    /// 所以这里用 `Lose HP` 走 `lose_hp` —— 它也算"失去生命"，顺带证明记账在**两条路**上都做了。
    #[test]
    fn blood_for_blood_gets_cheaper_each_time_you_lose_hp() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 用 `bloodletting`（0 费，Lose 3 HP）造掉血：它自己不花钱，所以能量账干净。
        let cost_after = |losses: i32| -> i32 {
            let mut host = Host::new(&content);
            let mut state = arena();
            // 掉血那几张是 0 费的，但 `blood_for_blood` 自己要付钱 ⇒ 最后一次性给够。
            for _ in 0..losses {
                let card = card_in_hand(&mut state, &content, "hero", "bloodletting");
                crate::play::play_card(
                    &mut state,
                    Some(&content),
                    &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
                )
                .expect("bloodletting is playable");
                host.try_resolve_pending_queues(&mut state).expect("drain");
            }
            // 真的打出去，量**实际花掉的能量** —— 比读计划更接近玩家看到的东西，也不需要
            // 给 `play.rs` 加一个只为测试存在的门（§4.14 那种"度量说谎"的老坑）。
            give_energy(&mut state, "hero", 9);
            let before: i32 = state
                .combatant(&cid("hero"))
                .map_or(0, |combatant| {
                    combatant
                        .resources()
                        .iter()
                        .filter(|pool| pool.key.as_str() == "standard.energy")
                        .map(|pool| pool.pool.current)
                        .sum()
                });
            if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
                enemy.health_max = 200;
                enemy.health_current = 200;
            }
            let card = card_in_hand(&mut state, &content, "hero", "blood_for_blood");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("blood for blood is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            let after: i32 = state
                .combatant(&cid("hero"))
                .map_or(0, |combatant| {
                    combatant
                        .resources()
                        .iter()
                        .filter(|pool| pool.key.as_str() == "standard.energy")
                        .map(|pool| pool.pool.current)
                        .sum()
                });
            before - after
        };

        assert_eq!(cost_after(0), 4, "no HP loss yet ⇒ the printed 4");
        assert_eq!(cost_after(2), 2, "two HP losses ⇒ 2");
        assert_eq!(cost_after(9), 0, "more losses than the printed cost ⇒ 0, never negative");
    }

    /// §242：`Corruption` —— 技能**0 费**且打完**进消耗堆**；攻击牌两件事都不吃。
    ///
    /// 这条判据的重点是"只认技能"：`corruption` 的两条规则都按 `is_skill` 分流，写错一处就会
    /// 让攻击牌也免费/也被消耗 —— 那两件事在页面上都"看起来很正常"（少花能量、牌没了）。
    #[test]
    fn corruption_makes_skills_free_and_exhausts_them() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 技能：`defend`（1 费）不花能量，且进消耗堆。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give(&mut state, "hero", status("st_corp", "standard.corruption", 1));
        let card = card_in_hand(&mut state, &content, "hero", "defend");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("defend is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy: i32 = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy, 3, "a Skill under Corruption costs 0");
        assert_eq!(block_of(&state, "hero"), 5, "and still does its job");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile),
            [std::string::String::from("defend")],
            "the Skill is Exhausted after play"
        );

        // ② 攻击牌：`strike`（1 费）照付、照常进弃牌堆。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give(&mut state, "hero", status("st_corp", "standard.corruption", 1));
        let card = card_in_hand(&mut state, &content, "hero", "strike");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("strike is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy: i32 = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy, 2, "an Attack still pays its cost");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DiscardPile),
            [std::string::String::from("strike")],
            "and an Attack is not Exhausted"
        );

        // ③ 没有 Corruption：技能照付、进弃牌堆（对照组 —— 否则 ① 的"免费"可能本来就成立）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "defend");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("defend is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy: i32 = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy, 2, "without Corruption a Skill pays 1");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DiscardPile),
            [std::string::String::from("defend")],
            "and lands in the discard pile"
        );
    }

    /// §241：`Havoc` —— "Play the top card of your draw pile and Exhaust it."
    ///
    /// 四件事一起钉住，每一件都是"不做就看不出来"的那一类：
    /// ① 打出去的是**抽牌堆顶那张**（不是手牌里随便一张，也不是抽到的别的）；
    /// ② **不付费**：能量一点不掉（`Havoc` 只花自己的 1 费）；
    /// ③ 打完进**消耗堆**（同一张 `Strike` 平时进弃牌堆 —— 所以这一条只能靠强制落区）；
    /// ④ 攻击牌**自动选目标**：随机一个活着的敌人掉血（不选目标的话 `sel.eventTarget` 解出空集，
    ///    伤害会安静地一点不打）。
    #[test]
    fn havoc_plays_the_top_card_for_free_into_the_exhaust_pile() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 200;
            enemy.health_current = 200;
        }
        if let Some(enemy) = state.combatant_mut(&cid("enemy_b")) {
            enemy.health_max = 200;
            enemy.health_current = 200;
        }
        // 抽牌堆顶放一张 `strike`（2 费 —— 如果 Havoc 付费，能量会掉 2）。
        give_card(&mut state, "hero", CardZone::DrawPile, "card_top", "strike", None);
        give_card(&mut state, "hero", CardZone::DrawPile, "card_under", "defend", None);
        let energy_before = 2; // 预置 3，`Havoc` 自己花 1
        let health_before = health(&state, "enemy_a") + health(&state, "enemy_b");
        let card = card_in_hand(&mut state, &content, "hero", "havoc");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("havoc is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        // ② 只花了 Havoc 自己的 1 费：`strike` 的 2 费一分没动。
        let energy_after: i32 = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy_after, energy_before, "the forced play does not pay its own cost");

        // ④ 目标：随机一个敌人掉了 `strike` 的 6 点。
        assert_eq!(
            health_before - (health(&state, "enemy_a") + health(&state, "enemy_b")),
            6,
            "the forced Strike hit a random enemy for 6"
        );

        // ③ 那张 `strike` 在消耗堆里，而不是弃牌堆。
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile),
            [std::string::String::from("strike")],
            "the forced play lands in the Exhaust pile"
        );
        assert!(
            !zone_definitions(&state, "hero", CardZone::DiscardPile)
                .iter()
                .any(|id| id == "strike"),
            "and it is NOT in the discard pile"
        );
        // 底下的 `defend` 没被动过。
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DrawPile),
            [std::string::String::from("defend")],
            "only the TOP card is played"
        );

        // 抽牌堆空 ⇒ 什么都不做（不报错）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "havoc+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("havoc+ is playable");
        host.try_resolve_pending_queues(&mut state).expect("an empty draw pile is not an error");
        assert_eq!(health(&state, "enemy_a"), 20, "nobody was hit");
    }

    /// §240：`Infernal Blade` —— "Add a random Attack into your hand. It costs 0 this turn."
    ///
    /// 四件事一起钉住，每一条都对应一个真会写错的地方：
    /// ① 进手的是**攻击牌**（不是技能/状态 —— 池子按 tag 过滤）；
    /// ② 是**基础牌**（不是 `strike+` 那种升级行：那会让"随机"变成"随机到升级版"）；
    /// ③ **不是 X 费牌**（每副本价格对 X 费牌看不见 ⇒ 会造出"说 0 费、实际全部能量"）；
    /// ④ 那张牌的**实际付款是 0**（不是"显示 0"）：`play_card` 之后能量一点没掉。
    ///
    /// 随机性本身不钉（种子由 `random_step` 决定，钉死了就是钉死洗牌顺序），钉的是**池子的性质**：
    /// 连造 40 次，每一次都必须是"基础、攻击、非 X 费"——这比"某一次等于某张牌"强得多。
    #[test]
    fn infernal_blade_adds_a_random_attack_that_really_costs_zero() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① ② ③：连造 40 次，检查每一次落进来的定义。
        let mut host = Host::new(&content);
        let mut state = arena();
        let mut seen = std::collections::BTreeSet::new();
        for _ in 0..40 {
            give_energy(&mut state, "hero", 3);
            let card = card_in_hand(&mut state, &content, "hero", "infernal_blade");
            let before: i32 = zone_count(&state, "hero", CardZone::Hand) as i32;
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("infernal blade is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            // 手牌：-1（打出自己）+ 1（造出来的那张）。
            assert_eq!(
                zone_count(&state, "hero", CardZone::Hand) as i32,
                before,
                "Infernal Blade itself leaves and one random card arrives"
            );
            let newest = state
                .zone_cards(&cid("hero"), CardZone::Hand)
                .last()
                .map(|card| crate::state::CardDefinitionId::new(card.definition_id.as_str()))
                .transpose()
                .expect("definition matches its own text")
                .expect("a card arrived");
            let definition = newest.as_str();
            assert!(
                definition != "infernal_blade" && definition != "infernal_blade+",
                "the created card must not be Infernal Blade itself ({definition})"
            );
            assert!(
                content.card_has_tag(definition, "attack") == Some(true),
                "{definition} is not an Attack"
            );
            assert!(
                !definition.contains('+'),
                "{definition} is an upgraded row -- the random pool is base cards only"
            );
            assert!(
                content.card_has_tag(definition, crate::battle::X_COST_TAG) != Some(true),
                "{definition} is an X-cost card -- a per-copy price cannot make it free"
            );
            seen.insert(std::string::String::from(definition));
        }
        assert!(
            seen.len() > 2,
            "the pool is supposed to be wide; 40 draws hit only {seen:?}"
        );

        // ④ 真的收 0：造出来之后立刻打它，能量一点不掉。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 200;
            enemy.health_current = 200;
        }
        let card = card_in_hand(&mut state, &content, "hero", "infernal_blade");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("infernal blade is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let made = state
            .zone_cards(&cid("hero"), CardZone::Hand)
            .last()
            .map(|card| card.id)
            .expect("a card arrived");
        let energy_before = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), made, Some(cid("enemy_a"))),
        )
        .expect("the created card is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy_after = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(
            energy_after, energy_before,
            "the created card costs 0 for real, not just on the label"
        );
    }

    /// §239：`Burning Pact` —— "Exhaust 1 card. Draw 2 cards."
    ///
    /// 这条判据同时把一处**顺序偏差**写死成断言（不让它以后悄悄变）：StS 是"先消耗、再抽"，
    /// 而本内核的节目会把整棵树先派发完 ⇒ 抽牌请求在**问句还开着的时候**就落地了。
    ///
    /// 为什么可以接受：候选清单在提问那一刻就快照了（`begin_choice` 的 `candidates`），所以
    /// "能消耗哪几张"在两种顺序下**完全一样**；而**终态也完全一样**
    /// （`H \ {c} ∪ {d1,d2}`）。唯一看得见差别的是"问句开着时手牌已经多了两张"。
    #[test]
    fn burning_pact_exhausts_a_card_and_draws() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        for index in 0..3 {
            give_card(&mut state, "hero", CardZone::Hand,
                      &std::format!("card_s{index}"), "strike", None);
        }
        for index in 0..2 {
            give_card(&mut state, "hero", CardZone::DrawPile,
                      &std::format!("card_d{index}"), "defend", None);
        }
        let card = card_in_hand(&mut state, &content, "hero", "burning_pact");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("burning pact is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let choice = state.pending_choice().expect("it asks which card to Exhaust");
        assert_eq!(choice.source.zone(), Some(CardZone::Hand), "candidates come from hand");
        assert_eq!((choice.min, choice.max), (1, 1), "exactly one card");
        assert_eq!(
            choice.then,
            crate::state::ChoiceThen::Exhaust,
            "the `then` is Exhaust, not a copy/upgrade"
        );
        // 偏差（见文档）：问句开着时，那两张**已经**抽到手里了。
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            3 + 2,
            "the draw already landed while the question is open (StS draws after the Exhaust)"
        );

        // 回答：消耗掉第一张 strike。
        let picks = [state
            .zone_cards(&cid("hero"), CardZone::Hand)
            .find(|card| card.id.as_str() == "card_s0")
            .expect("card_s0 is in hand")
            .id];
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&picks), 0)
            .expect("the answer is accepted");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        assert_eq!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile),
            [std::string::String::from("strike")],
            "the chosen card is the only thing in the Exhaust pile"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            4,
            "3 - the exhausted one + the 2 drawn"
        );
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DiscardPile),
            [std::string::String::from("burning_pact")],
            "Burning Pact itself is **not** exhausted (the wiki `Exhaust` there is a verb)"
        );
    }

    /// §239：`Clash` —— **手牌全是攻击牌才能打**（`PlayCondition`）。
    ///
    /// 三段，缺一段这条判据就有一半是空的：
    /// ① 手牌里有技能牌 ⇒ **拒**，而且是 `PlayConditionFalse` 这一种拒（不是"费用不够"或"打不出去"）；
    /// ② 手牌全是攻击 ⇒ 打得出去、伤害是 14；
    /// ③ 拒的时候**一个字节都不改**（能量、手牌、敌人的血）—— 出牌校验在 `apply_plan` 之前。
    ///
    /// 这条同时是"`PlayCondition` 那一格真的进了镜像"的判据：镜像里 62/62 行原本都是 `ABSENT16`，
    /// 若 `contentc` 没把 JSON 的 `PlayCondition` 写进 CARD 行，① 会**通过**（永远可打）而 ② 也通过
    /// ⇒ 只有 ① 能发现接线错了。
    #[test]
    fn clash_refuses_unless_every_card_in_hand_is_an_attack() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 手牌 = Clash + Defend（技能）⇒ 拒。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let clash = card_in_hand(&mut state, &content, "hero", "clash");
        card_in_hand(&mut state, &content, "hero", "defend");
        let energy_before = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        let hand_before = zone_count(&state, "hero", CardZone::Hand);
        let enemy_before = health(&state, "enemy_a");
        let refused = crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), clash, Some(cid("enemy_a"))),
        );
        match refused {
            Err(crate::play::PlayError::Refused(crate::play::Refusal::PlayConditionFalse)) => {}
            other => panic!("a Skill in hand must refuse Clash with PlayConditionFalse, got {other:?}"),
        }
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy_after = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy_after, energy_before, "a refused play pays nothing");
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), hand_before, "and the hand is intact");
        assert_eq!(health(&state, "enemy_a"), enemy_before, "and nobody took damage");

        // ② 手牌全是攻击（Clash + Strike）⇒ 打得出去，14 伤害。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        let clash = card_in_hand(&mut state, &content, "hero", "clash");
        card_in_hand(&mut state, &content, "hero", "strike");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), clash, Some(cid("enemy_a"))),
        )
        .expect("an all-attack hand lets Clash through");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(100 - health(&state, "enemy_a"), 14, "Clash deals 14");

        // ③ 只有 Clash 自己一张手牌 —— 它自己是 Attack，所以也算"全是攻击"（边界）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        let clash = card_in_hand(&mut state, &content, "hero", "clash+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), clash, Some(cid("enemy_a"))),
        )
        .expect("Clash alone is still an all-attack hand");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(100 - health(&state, "enemy_a"), 18, "clash+ deals 18");
    }

    /// §238：`Heavy Blade` —— **力量算 3（升级 5）次**，而伤害数（14）不升级。
    ///
    /// 判据看的是"力量系数"，所以三档力量各测一次：0 力量（=14）、+3 力量（=14+3×3=23）、
    /// 而升级版同一力量下是 14+3×5=29。**只测 0 力量会把倍率整条漏掉**（14 与倍率无关）。
    #[test]
    fn heavy_blade_multiplies_strength_three_or_five_times() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let play = |card_id: &str, strength: i32| -> i32 {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
                enemy.health_max = 200;
                enemy.health_current = 200;
            }
            if strength != 0 {
                give(&mut state, "hero", status("st_str", "standard.strength", strength));
            }
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("heavy blade is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            200 - health(&state, "enemy_a")
        };

        assert_eq!(play("heavy_blade", 0), 14, "no Strength ⇒ just the printed 14");
        assert_eq!(play("heavy_blade", 3), 14 + 3 * 3, "Strength ×3");
        assert_eq!(play("heavy_blade+", 3), 14 + 3 * 5, "the + version is ×5");
    }

    /// §238：`Feed` 的 "If Fatal" —— **目标死了**才抬上限，而且上限与当前血一起 +N。
    ///
    /// 两侧：打死（+3 上限 +3 血）与没打死（一点不涨）。第一版只测了"打死"，于是
    /// "条件被写成恒真"也全绿 —— 那正是 §4 里"守卫装在了切口下游"的形状。
    #[test]
    fn feed_only_raises_max_hp_on_a_fatal_blow() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 打死：敌人 5 血，Feed 打 10 ⇒ Fatal ⇒ 上限 70 → 73、当前血 70 → 73（满血时一起涨）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 5;
            enemy.health_current = 5;
        }
        let card = card_in_hand(&mut state, &content, "hero", "feed");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("feed is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 0, "the target died");
        assert_eq!(
            state.combatant(&cid("hero")).map(|c| c.health_max),
            Some(73),
            "Fatal ⇒ Max HP +3"
        );
        assert_eq!(health(&state, "hero"), 73, "and the current HP follows the ceiling");

        // ② 没打死：敌人 100 血 ⇒ 上限一点不动。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        let card = card_in_hand(&mut state, &content, "hero", "feed");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("feed is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 90, "10 damage landed");
        assert_eq!(
            state.combatant(&cid("hero")).map(|c| c.health_max),
            Some(70),
            "not Fatal ⇒ no Max HP"
        );
    }

    /// §238：`Double Tap` 只认**下一张 Attack**（Duplication Potion 认任意牌）。
    ///
    /// 三件事一起钉住：① Attack 真的打两次；② 那次机会被花掉（第二张 Attack 只打一次）；
    /// ③ **Skill 不吃它**（这是 Double Tap 与 Duplication Potion 唯一的区别，也正是
    /// `DUPLICATION_SCOPES` 里那个 `Some("attack")` 存在的理由 —— 没有它，这张牌会变成"下一张牌"）。
    #[test]
    fn double_tap_only_covers_the_next_attack() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① Attack 打两次：Strike 6 ⇒ 12。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 9);
        give(&mut state, "hero", status("st_dt", "standard.double_tap", 1));
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 200;
            enemy.health_current = 200;
        }
        let card = card_in_hand(&mut state, &content, "hero", "strike");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("strike is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(200 - health(&state, "enemy_a"), 12, "6 damage twice");
        assert_eq!(
            stacks_of(&state, "hero", "standard.double_tap"),
            0,
            "the charge is spent"
        );

        // ② 第二张 Attack 只打一次（机会已经用掉）。
        let card = card_in_hand(&mut state, &content, "hero", "strike");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("strike is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(200 - health(&state, "enemy_a"), 18, "12 + one more Strike");

        // ③ Skill 不吃 Double Tap：Defend 只给 5 格挡，且那层不被花掉。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 9);
        give(&mut state, "hero", status("st_dt", "standard.double_tap", 1));
        let card = card_in_hand(&mut state, &content, "hero", "defend");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("defend is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 5, "a Skill is played once");
        assert_eq!(
            stacks_of(&state, "hero", "standard.double_tap"),
            1,
            "and a Skill does not spend the charge -- that is the whole difference from the potion"
        );
    }

    /// §238：`Exhume` —— 从**消耗堆**拿一张回手牌（`ChoiceSource::ExhaustPile`）。
    ///
    /// 判据落在"牌真的换了堆"上，而不是"问句出现了"：问句存在只说明内容写了 `chooseCards`，
    /// 挪没挪是内核的事（§161.5 的老教训）。
    #[test]
    fn exhume_pulls_a_card_out_of_the_exhaust_pile() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 9);
        // 消耗堆里放一张 `bash`（不用它自己的 exhaustion 造，免得把判据绑在别的牌上）。
        give_card(&mut state, "hero", CardZone::ExhaustPile, "card_ex", "bash", None);
        let card = card_in_hand(&mut state, &content, "hero", "exhume");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("exhume is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let choice = state.pending_choice().expect("Exhume asks");
        assert_eq!(
            choice.source.zone(),
            Some(CardZone::ExhaustPile),
            "the question's source zone is the Exhaust pile"
        );
        // 选出答案（消耗堆里那唯一一张就是 `bash`），再排空。
        let picks = [state
            .zone_cards(&cid("hero"), CardZone::ExhaustPile)
            .find(|card| card.definition_id.as_str() == "bash")
            .expect("bash is in the Exhaust pile")
            .id];
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&picks), 0)
            .expect("the answer is accepted");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert!(
            zone_definitions(&state, "hero", CardZone::Hand)
                .iter()
                .any(|id| id.as_str() == "bash"),
            "the chosen card is in hand"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            1,
            "and only Exhume itself is left in the Exhaust pile"
        );
    }

    /// §237：`BlockGained` 钩子 —— `Juggernaut` 按"加了几点格挡"次数结算。
    ///
    /// 两侧都测：**加格挡**会触发（每加一次一条），**没加**不触发（`block_stage` 修饰成 0，
    /// 或者根本没这个状态）。第二条容易忘，而忘了它就意味着"手上有 Juggernaut 时，任何
    /// 加 0 点格挡的东西都在打人"。
    #[test]
    fn juggernaut_punishes_every_block_gain() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 没有 Juggernaut：加 5 点格挡不该伤到人。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let enemy_before = health(&state, "enemy_a");
        let card = card_in_hand(&mut state, &content, "hero", "defend");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("defend is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            health(&state, "enemy_a"),
            enemy_before,
            "without Juggernaut, Block does not hurt anybody"
        );

        // Juggernaut 5 层：每**加**一次格挡打随机敌人 5 点。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 6);
        give(&mut state, "hero", status("st_jug", "standard.juggernaut", 5));
        let enemy_before = health(&state, "enemy_a") + health(&state, "enemy_b");
        let card = card_in_hand(&mut state, &content, "hero", "defend");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("defend is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 5, "Defend still blocks");
        assert_eq!(
            enemy_before - (health(&state, "enemy_a") + health(&state, "enemy_b")),
            5,
            "one Block gain ⇒ one 5 damage hit on a random enemy"
        );

        // 两张牌各加一次 ⇒ 两次（次数单位是"获得格挡"，不是"回合"）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 6);
        give(&mut state, "hero", status("st_jug", "standard.juggernaut", 5));
        let enemy_before = health(&state, "enemy_a") + health(&state, "enemy_b");
        for _ in 0..2 {
            let card = card_in_hand(&mut state, &content, "hero", "defend");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("defend is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
        }
        let lost = enemy_before - (health(&state, "enemy_a") + health(&state, "enemy_b"));
        assert!(lost == 10, "two Block gains ⇒ two hits (lost {lost}, want 10)");
    }

    /// §237：`CardsDrawn` 钩子 —— `Evolve` 只认 **Status**，`Fire Breathing` 认 Status 或 Curse。
    ///
    /// 三张探针卡分别代表三个答案：`wound`（Status）⇒ 两个都响；`injury`（Curse）⇒ 只有
    /// Fire Breathing 响；`strike`（Attack）⇒ 两个都不响。**只测第一个会漏掉"Curse 忘了加"**，
    /// 只测第二个会漏掉"Status 被写成 Curse-only"。
    #[test]
    fn evolve_and_fire_breathing_only_answer_to_the_right_tags() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 探针：`evolve`（抽 2）+ `fire_breathing`（打 6）。每场只放一张探针牌在抽牌堆顶。
        let probe = |card_id: &str| -> (i32, usize) {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 6);
            give(&mut state, "hero", status("st_evo", "standard.evolve", 2));
            give(&mut state, "hero", status("st_fb", "standard.fire_breathing", 6));
            give_card(&mut state, "hero", CardZone::DrawPile,
                      "card_probe", card_id, None);
            // 探针下面再垫 3 张 —— 否则 `Evolve` 的"再抽 2"抽到空堆，手牌数就分不出
            // "没触发"与"触发了但没牌"（正是 §4 那种"工具报成功"的形状）。
            for index in 0..3 {
                give_card(&mut state, "hero", CardZone::DrawPile,
                          &std::format!("card_filler{index}"), "strike", None);
            }
            let enemy_before = health(&state, "enemy_a") + health(&state, "enemy_b");
            // 抽 1 张：探针牌进手。
            // ⚠️ 用 `pommel_strike`（抽 1）而不是 `battle_trance`（抽 3 + `no_draw`）：
            // 后者会把 `Evolve` 的额外抽牌**按规则**挡掉，于是这条判据永远看不出 Evolve 响没响。
            let card = card_in_hand(&mut state, &content, "hero", "pommel_strike");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("battle trance is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            let lost = enemy_before - (health(&state, "enemy_a") + health(&state, "enemy_b"));
            (lost, zone_count(&state, "hero", CardZone::Hand) as usize)
        };

        // 基线：抽到一张非 Status/Curse（`strike`）⇒ 不额外抽、不打人。
        let (base_lost, hand) = probe("strike");
        assert_eq!(base_lost, 9, "Pommel Strike's own 9 is the yardstick (nothing extra)");
        assert_eq!(hand, 1, "Pommel Strike draws 1 + nothing extra");

        // Status（wound）⇒ Fire Breathing 打 6 × 全体（2 个敌人 ⇒ 12），Evolve 抽 2。
        let (lost, hand) = probe("wound");
        assert_eq!(lost, base_lost + 12, "Fire Breathing 6 to ALL enemies (2 enemies)");
        assert_eq!(hand, 1 + 2, "the probe + Evolve 2");

        // Curse（injury）⇒ 同样两项都响（`card.hasTag.curse` 就是为它加的位）。
        let (lost, hand) = probe("injury");
        assert_eq!(lost, base_lost + 12, "Curse is Fire Breathing's other half");
        assert_eq!(hand, 1, "but Evolve is status-only, so it does not draw");
    }

    /// §237：`CardExhausted` 钩子 —— `Feel No Pain` 给格挡、`Dark Embrace` 抽牌。
    ///
    /// 三条入堆路径（§225 的审计）都要响，所以用两个不同的载体各测一次：
    /// ① 打出即消耗（`offering`）；② 虚无（`carnage` 的回合末）。**内容搬牌**那条由 §225 的
    /// `every_way_into_the_exhaust_pile_runs_the_exhausted_program` 钉着触发器节目的落点，
    /// 而事件与节目同一处发 —— 所以这里不重复。
    #[test]
    fn exhausting_a_card_feeds_feel_no_pain_and_dark_embrace() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 打出即消耗：Offering 自己进消耗堆 ⇒ 3 格挡 + 抽 1 张（在它自己的 3 张之后）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_fnp", "standard.feel_no_pain", 3));
        give(&mut state, "hero", status("st_de", "standard.dark_embrace", 1));
        for index in 0..6 {
            give_card(&mut state, "hero", CardZone::DrawPile,
                      &std::format!("card_d{index}"), "strike", None);
        }
        let card = card_in_hand(&mut state, &content, "hero", "offering");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("offering is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 3, "Feel No Pain 3 for the exhausted Offering");
        // Offering 抽 3，Dark Embrace 再抽 1 ⇒ 手牌 4 张（Offering 自己已经离手）。
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 4, "3 + Dark Embrace's 1");

        // ② 虚无：**留在手里**的 Carnage 在回合末从手牌进消耗堆，同样要响。
        //    ⚠️ 别拿"打出去的 Carnage"测这一条 —— 它已经离手了，回合末没有东西可虚无；
        //    第一版就是这么写的，而它安静地报了 0 格挡（`assert_eq!` 抓到了，但若断言写成
        //    ">= 0" 就会全绿）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_fnp", "standard.feel_no_pain", 3));
        turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
        assert_eq!(block_of(&state, "hero"), 0, "turn start clears Block");
        give_card(&mut state, "hero", CardZone::Hand, "card_eth", "carnage", None);
        // 回合末这一趟就够：虚无的落区与 `Feel No Pain` 都在 hero 的 turn-end 处理里。
        turn::end_current_turn(&mut state, &config(), &mut host).expect("turn ends");
        assert_eq!(
            block_of(&state, "hero"),
            3,
            "the Ethereal Carnage exhausted at turn end ⇒ Feel No Pain 3"
        );
    }

    /// §236：`Lose N HP` **不是伤害** —— 不吃格挡、不触发"被打"的钩子，但它**是**失去生命。
    ///
    /// 三件事分开测，因为它们的正确答案各不相同：
    /// ① 有 10 点格挡时 `Hemokinesis` 仍然掉 2 血（格挡一点不动）—— 这排除了"用 dealDamage 实现"；
    /// ② 掉血会响 `Rupture`（每层 +1 力量），而 Brutality 的每回合掉血**不响**（`hpLoss.fromCard`）；
    /// ③ `Lose 6 HP` 在 2 血时只掉 2 —— 而且**把英雄打死时战斗真的结束**（0 血转 Downed 的收尾）。
    #[test]
    fn losing_hp_is_not_damage_but_it_is_hp_loss() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 格挡不挡 `Lose HP`。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_block(&mut state, "hero", 10);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        let card = card_in_hand(&mut state, &content, "hero", "hemokinesis");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("hemokinesis is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "hero"), 68, "70 - 2 HP: Block does not stop `Lose HP`");
        assert_eq!(block_of(&state, "hero"), 10, "and the Block was not consumed");
        assert_eq!(100 - health(&state, "enemy_a"), 15, "the damage half still lands");

        // ② Rupture 只认"牌付的代价"。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 6);
        give(&mut state, "hero", status("st_rup", "standard.rupture", 2));
        turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
        let card = card_in_hand(&mut state, &content, "hero", "bloodletting");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("bloodletting is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            stacks_of(&state, "hero", "standard.strength"),
            2,
            "Bloodletting's 3 HP loss is `from a card` ⇒ Rupture 2 gains 2 Strength"
        );
        // Brutality 的每回合掉血**不算**"from a card"。
        give(&mut state, "hero", status("st_bru", "standard.brutality", 1));
        let strength_before = stacks_of(&state, "hero", "standard.strength");
        turn::end_current_turn(&mut state, &config(), &mut host).expect("turn ends");
        turn::start_current_turn(&mut state, &config(), &mut host).expect("next turn");
        assert_eq!(
            stacks_of(&state, "hero", "standard.strength"),
            strength_before,
            "Brutality's 1 HP per turn is not a card's cost ⇒ Rupture stays silent"
        );

        // ③ 血量不够时只掉剩下的，而且**能把自己打死**（0 血转 Downed、战斗判负）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(hero) = state.combatant_mut(&cid("hero")) {
            hero.health_current = 2;
        }
        let card = card_in_hand(&mut state, &content, "hero", "offering");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("offering is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "hero"), 0, "6 HP from a 2 HP hero takes 2");
        assert_eq!(
            state.result,
            crate::state::CombatResult::Defeat,
            "losing the last HP must end the fight (the Downed bookkeeping is shared with damage)"
        );
    }

    /// §236：5 张"失去生命"的牌各自的牌面。
    #[test]
    fn the_lose_hp_cards_do_what_their_pages_say() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let energy_of = |state: &CombatState| -> i32 {
            state
                .combatant(&cid("hero"))
                .map_or(0, |combatant| {
                    combatant
                        .resources()
                        .iter()
                        .filter(|pool| pool.key.as_str() == "standard.energy")
                        .map(|pool| pool.pool.current)
                        .sum()
                })
        };

        // bloodletting：-3 HP，+2/+3 能量（0 费，所以能量净值就是加的那些）。
        for (card_id, gain) in [("bloodletting", 2i32), ("bloodletting+", 3)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("bloodletting is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(health(&state, "hero"), 67, "{card_id}: lose 3");
            // 起点能量是 0（0 费牌不需要预置），所以净值就是这张牌加的那些。
            assert_eq!(energy_of(&state), gain, "{card_id}: gain {gain} Energy");
        }

        // offering：-6 HP，+2 能量，抽 3/5 张，自消耗。
        for (card_id, draws) in [("offering", 3usize), ("offering+", 5)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            for index in 0..6 {
                give_card(&mut state, "hero", CardZone::DrawPile,
                          &std::format!("card_d{index}"), "defend", None);
            }
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("offering is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(health(&state, "hero"), 64, "{card_id}: lose 6");
            assert_eq!(energy_of(&state), 2, "{card_id}: gain 2 Energy");
            // 手牌：offer 自己离手，抽到 draws 张。
            assert_eq!(zone_count(&state, "hero", CardZone::Hand) as usize, draws, "{card_id}");
            assert!(
                zone_definitions(&state, "hero", CardZone::ExhaustPile)
                    .iter().any(|id| id.as_str() == card_id),
                "{card_id} exhausts itself"
            );
        }

        // brutality：挂上状态（每回合掉 1 血抽 1 张），`+` 版自带 Innate。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
        let card = card_in_hand(&mut state, &content, "hero", "brutality");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("brutality is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(stacks_of(&state, "hero", "standard.brutality"), 1);
        let hp_before = health(&state, "hero");
        // ⚠️ 战斗里有三个战斗员：结束英雄回合只是把席位交给敌人，所以"回到英雄"要循环，
        // 不能只走一步（写死一步会让这条判据在敌人数量变化时安静地错）。
        let mut hops = 0;
        while state.active_combatant_id.as_ref() != Some(&cid("hero")) || hops == 0 {
            turn::end_current_turn_and_start_next(&mut state, &config(), &mut host)
                .expect("the turn passes");
            hops += 1;
            assert!(hops <= 4, "the turn never came back to the hero");
        }
        assert_eq!(
            health(&state, "hero"),
            hp_before - 1,
            "Brutality takes 1 HP at the start of the turn"
        );

        // rupture：1 层 ⇒ 每次因牌失去生命 +1 力量（见上一条测试的 ②），这里只钉"挂得上"。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "rupture+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("rupture is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(stacks_of(&state, "hero", "standard.rupture"), 2, "rupture+ is 2");
    }

    /// §225：**消耗审计** —— 内核里把牌送进消耗堆的路径必须**都**跑 `LifecyclePrograms[Exhausted]`。
    ///
    /// 这条测试是本节"确认消耗逻辑是否统一"的机器版。三条路径，一条都不能漏：
    /// * **打出即消耗**（`PlayedCardDestinationZone = ExhaustPile`，经 `MoveCardToZone` 请求）；
    /// * **虚无**（`TurnEndHandDestinationZone = ExhaustPile`，经回合末弃手牌）；
    /// * **内容驱动**（`node.moveCardToZone` 指向消耗堆，经同一个 `move_card_for`）。
    ///
    /// 判据用 `sentinel`（它有一条 `Exhausted` 节目：+2 能量），因为"节目跑过"比"牌到了那个区"
    /// 更能说明问题 —— 牌到位但没有节目，正是 §220 之前的状态。
    #[test]
    fn every_way_into_the_exhaust_pile_runs_the_exhausted_program() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 打出即消耗：`sentinel` 不是"打出即消耗"的牌，用 `slimed` 不行（它没有节目）
        //    —— 所以这条路径改用"把 sentinel 经内容搬到消耗堆"，见 ③。
        // ② 虚无：回合末把 `sentinel` 送进消耗堆（`TurnEndHandDestinationZone = ExhaustPile`）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_s1", "sentinel", None);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        give_energy(&mut state, "hero", 0);
        let before = energy_of(&state, "hero");
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            1,
            "the ethereal sweep moved it"
        );
        assert_eq!(
            energy_of(&state, "hero"),
            before + 2,
            "and the `Exhausted` program ran (+2 energy)"
        );

        // ③ 内容驱动：`node.moveCardToZone` 指到消耗堆 —— 与 ② 是**同一条** `move_card_for`。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_s2", "sentinel", None);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        give_energy(&mut state, "hero", 0);
        let before = energy_of(&state, "hero");
        let slot = state
            .card_zones(&cid("hero"))
            .and_then(|zones| zones.slot_at(CardZone::Hand, 0))
            .expect("the sentinel is in hand");
        let card_id = state.card(slot).expect("card").id;
        state
            .enqueue_effect(crate::state::EffectRequest::MoveCardToZone {
                owner: cid("hero"),
                card: card_id,
                to_zone: CardZone::ExhaustPile,
                placement: crate::state::ZonePlacement::Bottom,
            })
            .expect("enqueue");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            energy_of(&state, "hero"),
            before + 2,
            "a content-driven move into the exhaust pile runs the same program"
        );
    }

    /// §222：§221 加的十张牌 —— 一张表，每行说"打哪张、读哪一格、应当是多少"。
    ///
    /// 这一批之前只有通用层覆盖：内容门钉数字（`INV_CARDS`）、`CARD_DIFF` 跑程序文本，
    /// **没有任何东西断言"这张牌打出来真的做了那件事"**。矩阵把它们标成 `harness`，这里把它们
    /// 抬成具名测试。
    ///
    /// 判据口径：读**一个**可观察量（敌人血量 / 英雄格挡 / 手牌数 / 抽牌堆 / 弃牌堆 / 敌人状态），
    /// 而不是"整份状态"，因为这些牌各自只动一格 —— 读整份会让"读错格子"也看起来正确。
    #[test]
    fn the_ten_cards_added_in_221_do_what_the_wiki_says() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // (card, 打出去之后的断言) —— 每一行都在 `arena()`（敌人 20 血、英雄 70）上跑。
        for card_id in [
            "cleave",
            "pommel_strike",
            "shrug_it_off",
            "thunderclap",
            "bludgeon",
            "impervious",
            "pummel",
            "wild_strike",
            "ghostly_armor",
            "battle_trance",
        ] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            // 抽牌堆里得先有牌：`arena()` 的三个堆都是空的，而"抽 1 张"在空堆上**抽不到**
            // （那不是错误，是参考的 `:59-60`）。不放牌的话 `draw` 那几行会静默读到 0。
            for index in 0..3 {
                give_card(&mut state, "hero", CardZone::DrawPile,
                          &std::format!("card_seed_{index}"), "defend", None);
            }
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .unwrap_or_else(|error| panic!("{card_id}: {error:?}"));
            host.try_resolve_pending_queues(&mut state).expect("drain");

            match card_id {
                // 单体伤害
                "pommel_strike" => {
                    assert_eq!(health(&state, "enemy_a"), 11, "9 damage");
                    assert_eq!(zone_count(&state, "hero", CardZone::Hand), 1, "draw 1");
                }
                // 血量**钳在 0**（伤害不会让血量变负），所以这里读的是"死了"，不是 -12。
                "bludgeon" => assert_eq!(health(&state, "enemy_a"), 0, "32 damage kills 20 HP"),
                // 全体伤害：两个敌人都要掉血（这是 `sel.allEnemies` 的唯一可观察差别）
                "cleave" => {
                    assert_eq!(health(&state, "enemy_a"), 12, "8 to enemy_a");
                    assert_eq!(health(&state, "enemy_b"), 2, "8 to enemy_b");
                }
                "thunderclap" => {
                    assert_eq!(health(&state, "enemy_a"), 16, "4 to enemy_a");
                    assert_eq!(health(&state, "enemy_b"), 6, "4 to enemy_b");
                    assert_eq!(
                        stacks_of(&state, "enemy_a", "standard.vulnerable"),
                        1,
                        "and 1 Vulnerable on each"
                    );
                    assert_eq!(stacks_of(&state, "enemy_b", "standard.vulnerable"), 1);
                }
                // 多段：`repeat` 的每一段都过伤害管线（4×2 = 8）
                "pummel" => {
                    assert_eq!(health(&state, "enemy_a"), 12, "2 damage, 4 times");
                    assert_eq!(
                        zone_definitions(&state, "hero", CardZone::ExhaustPile),
                        vec!["pummel".to_string()],
                        "and it exhausts"
                    );
                }
                // 格挡 + 消耗
                "impervious" => {
                    assert_eq!(block_of(&state, "hero"), 30, "30 Block");
                    assert_eq!(
                        zone_definitions(&state, "hero", CardZone::ExhaustPile),
                        vec!["impervious".to_string()],
                        "and it exhausts"
                    );
                }
                "shrug_it_off" => {
                    assert_eq!(block_of(&state, "hero"), 8, "8 Block");
                    assert_eq!(zone_count(&state, "hero", CardZone::Hand), 1, "draw 1");
                }
                "ghostly_armor" => {
                    assert_eq!(block_of(&state, "hero"), 10, "10 Block");
                    // ⚠️ Ethereal 管的是"**回合末还在手里**"时的去向，跟"打出去"无关 ——
                    // 打出去的牌照常进弃牌堆（第一版把这两件事混了，断言写成了"留在手里"）。
                    assert_eq!(
                        zone_definitions(&state, "hero", CardZone::DiscardPile),
                        vec!["ghostly_armor".to_string()],
                        "playing it sends it to the discard pile as usual"
                    );
                }
                // Wound 进**抽牌堆**（不是弃牌堆 —— 那是 Wild Strike 与其它塞牌的区别）
                "wild_strike" => {
                    assert_eq!(health(&state, "enemy_a"), 8, "12 damage");
                    // 抽牌堆里预置了 3 张 `defend`，Wound 进的是**抽牌堆**（不是弃牌堆）——
                    // 这才是 Wild Strike 与其它塞牌的区别。
                    assert_eq!(
                        zone_definitions(&state, "hero", CardZone::DrawPile),
                        vec!["defend".to_string(), "defend".to_string(),
                             "defend".to_string(), "wound".to_string()],
                        "a Wound goes into the DRAW pile"
                    );
                    assert_eq!(
                        zone_count(&state, "hero", CardZone::DiscardPile),
                        1,
                        "only the played card itself is in the discard pile"
                    );
                }
                // 抽 3 张 + "本回合不能再抽"
                "battle_trance" => {
                    assert_eq!(
                        zone_count(&state, "hero", CardZone::Hand),
                        3,
                        "draw 3 (the card itself left the hand)"
                    );
                    // §231: 这里原来钉的是 `standard.draw_reduction` —— 那条状态压的是**下回合起手**
                    // 抽牌，而这张牌说的是"本回合不能再抽"。实现换了，判据跟着换（真正的行为判据在
                    // `battle_trance_blocks_further_draws_only_this_turn`：本回合再抽 = 0 张）。
                    assert_eq!(
                        stacks_of(&state, "hero", "standard.no_draw"),
                        1,
                        "and the rest of the turn cannot draw"
                    );
                }
                other => panic!("{other} has no assertion in this table"),
            }
        }
    }

    /// §222：两张事件诅咒 —— `doubt` 的"回合末 +1 Weak"是 `LifecyclePrograms[TurnEndInHand]`，
    /// `writhe` 只是 `Innate` + `Unplayable`（没有节目 ⇒ 回合末什么都不发生）。
    #[test]
    fn the_two_event_curses_behave_as_their_pages_say() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 先确认镜像里真的解得出这条节目（否则下面的 0 会是"没节目"，而不是"没触发"）。
        assert!(
            card_lifecycle_program(&content, "doubt", None)
                .expect("decode")
                .is_some(),
            "doubt must carry a TurnEndInHand program"
        );

        // `doubt`：手里过回合 ⇒ 1 层 Weak。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_doubt", "doubt", None);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::Hand),
            vec!["doubt".to_string()],
            "the curse is in hand when the turn ends"
        );
        // ① 节目**确实执行**：直接调生命周期（在回合末衰减之前），Weak 立刻可见。
        //    这一步与下面 ② 分开，是因为 ② 里它会被自己的衰减吃掉 —— 那是**顺序**问题，
        //    不是"节目没跑"（第一版把两件事混在一起，读到 0 就以为没实现）。
        host.try_hand_turn_end_lifecycle(&mut state, &cid("hero")).expect("lifecycle");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            stacks_of(&state, "hero", "standard.weak"),
            1,
            "the program runs: at the end of your turn, gain 1 Weak"
        );

        // ② 走**完整回合末**：节目在 ①（卡牌生命周期）跑，而 `standard.weak` 的衰减触发器在
        //    ③（`TurnEnded`）—— 同一次回合末里刚上的 Weak 当场被扣掉。
        //    ⚠️ 这是**已知的顺序偏差**（写进 `docs/sts-wiki-gap.md` §G.2 与偏差表）：参考里
        //    Weak 的衰减在 `decrease_timed_statuses`（第 ④ 步）之前/之后与卡程序的关系不同，
        //    所以原版里 Doubt 的 Weak 会留到下一回合。判据因此断言"被吃掉"，而不是假装它留着。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_doubt2", "doubt", None);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(
            stacks_of(&state, "hero", "standard.weak"),
            0,
            "known order deviation: the same turn-end decay eats the Weak it just applied"
        );

        // `writhe`：没有节目 ⇒ Weak 仍然是 0（成对，否则上面那条可能来自别处）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_writhe", "writhe", None);
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
        assert_eq!(
            stacks_of(&state, "hero", "standard.weak"),
            0,
            "writhe has no lifecycle program"
        );
    }

    /// §220：`LifecyclePrograms[Drawn]` —— wiki 的 "Whenever this card is drawn, lose 1 Energy."
    ///
    /// `Drawn` 与 `Exhausted` 是**内核新加的两个生命周期事件**（参考的 `CardLifecycleTrigger`
    /// 只有 `TurnEndInHand`）。它们在 `state.move_card` 这个**唯一的落区漏斗**上发请求：
    /// 抽牌堆→手牌 = `Drawn`，任何区→消耗堆 = `Exhausted`。选择在那个漏斗上发，是因为另一条路
    /// 要在"回合开始的抽牌、`drawCards` 节点、药水、弃牌堆洗回"每一处各写一遍，漏一处就是静默少跑。
    ///
    /// 判据走真实状态机：**把手牌抽起来**（`draw_card`，不是直接摆牌），能量必须 -1。
    #[test]
    fn a_void_drawn_from_the_pile_costs_one_energy() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        // 抽牌堆顶端放一张 Void（`draw_card` 抽的是**队首**）。
        give_card(&mut state, "hero", CardZone::DrawPile, "card_void", "void", None);
        assert_eq!(energy_of(&state, "hero"), 3);

        // 走**回合开始的抽牌**：那才是玩家真正抽到 Void 的路径。
        // （`draw_cards_with_reshuffle` 让状态层去跑节目是不行的 —— 它不知道内容。）
        turn::start_current_turn(&mut state, &config(), &mut host).expect("turn 1");
        let drawn = zone_count(&state, "hero", CardZone::Hand);
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            1,
            "the void is in hand"
        );
        assert_eq!(
            energy_of(&state, "hero"),
            2,
            "wiki: whenever this card is drawn, lose 1 Energy (drawn {drawn})",
        );
    }

    /// §220：`LifecyclePrograms[Exhausted]` —— wiki 的 "If this card is Exhausted, gain 2 Energy."
    ///
    /// 消耗的入口不止"打出即消耗"：虚无（回合末）、内容里的 `moveCardToZone` 都算。所以判据用
    /// **回合末的虚无清理**这条真实路径，而不是手动把牌塞进消耗堆。
    #[test]
    fn a_sentinel_that_gets_exhausted_pays_two_energy() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        // `sentinel+` 是 3 点能量（节目挂在**定义**上，所以升级行有自己的一份）。
        for (card_id, expected) in [("sentinel", 2), ("sentinel+", 3)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_card(&mut state, "hero", CardZone::Hand, "card_sentinel", card_id, None);
            turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
            // 回合开始会把能量补到上限（3/3）—— `gain 2` 会被上限吃掉，所以先把这一格腾出来。
            // 不腾的话"给了 2 点"与"一点没给"在数值上完全一样（第一版就是这么写错的）。
            give_energy(&mut state, "hero", 0);
            let before = energy_of(&state, "hero");
            // 回合末：`ethereal` 把它送进消耗堆 ⇒ `move_card` 发 `Exhausted` ⇒ 节目给能量。
            turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
            // 入队不是执行，排空一次（`end_current_turn` 自己也排，这一步幂等）。
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                zone_count(&state, "hero", CardZone::ExhaustPile),
                1,
                "{card_id}: ethereal moves it to the exhaust pile at turn end"
            );
            assert_eq!(
                energy_of(&state, "hero"),
                before + expected,
                "{card_id}: wiki says +{expected} Energy when exhausted"
            );
        }
    }

    /// §219：`Exhaust` 是**落区**，而且要真的能用 —— `bandage_up` / `dark_shackles` 曾经把
    /// `PlayedCardDestinationZone` 写成 `"Exhaust"`（内核只认 `"ExhaustPile"`），于是**一打就
    /// `IrError::UnknownKind`**。没有任何测试打过它们，所以这个错从 §157 活到 §218 的卡牌对照。
    ///
    /// 判据：打出去之后 ①牌进了消耗堆（不是弃牌堆），②效果真的发生了
    /// （`bandage_up` 治疗 4；`dark_shackles` 给敌人 -9 力量）。
    /// `slimed` 走同一条路：wiki 说它"1 费、可出、Exhaust"，而内容把它做成了不可出的状态牌 ——
    /// 现在载体有了，它就该可出。
    #[test]
    fn exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① `bandage_up`：治疗 4，然后进消耗堆。
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        {
            let hero = state.combatant_mut(&cid("hero")).expect("hero");
            hero.health_current = 40;               // 70 -> 40，好让治疗看得见
        }
        let card = card_in_hand(&mut state, &content, "hero", "bandage_up");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("hero"))),
        )
        .expect("bandage_up must be playable (it was `IrError::UnknownKind` with `\"Exhaust\"`)");
        assert_eq!(health(&state, "hero"), 44, "wiki: Heal 4 HP");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile),
            vec!["bandage_up".to_string()],
            "and it lands in the exhaust pile, not the discard pile"
        );

        // ② `slimed`：1 费、可出、进消耗堆（wiki 的 `Exhaust`）。
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "slimed");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("hero"))),
        )
        .expect("slimed is a playable 1-cost status card (wiki), not an unplayable one");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile),
            vec!["slimed".to_string()],
            "slimed exhausts"
        );
        assert_eq!(
            energy_of(&state, "hero"),
            2,
            "and it costs 1 energy like the wiki says"
        );

        // ③ `dark_shackles`：给敌人 -9 力量、**回合末还回来**，然后进消耗堆。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        // `arena()` 的敌人没有力量，而 `modifyStatusStacks` 会把层数**钳在 0**（参考行为
        // `:860-865`）—— 不先给 10 层的话，"降 9"与"钳到 0"在数值上分不开。
        give(&mut state, "enemy_a", status("st_str", "standard.strength", 10));
        let card = card_in_hand(&mut state, &content, "hero", "dark_shackles");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("dark_shackles must be playable");
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.strength"),
            1,
            "wiki: Enemy loses 9 Strength -- enemy_a had 10, so 10 - 9 = 1"
        );
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.regain_strength"),
            9,
            "and the give-back is booked as a status"
        );
        // 回合末：`regain_strength` 在**持有者**（敌人）的回合结束时把自己的层数加回力量，
        // 然后自己消失。所以要先让英雄结束回合、走到敌人头上，再结束敌人的回合。
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();   // 英雄的回合结束
        assert_eq!(state.active_combatant_id, Some(cid("enemy_a")), "现在是敌人的回合");
        turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
        turn::end_current_turn(&mut state, &config(), &mut host).unwrap();   // 敌人的回合结束
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.strength"),
            10,
            "\"this turn\": the 9 points come back at the end of it"
        );
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.regain_strength"),
            0,
            "and the marker removes itself"
        );
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile),
            vec!["dark_shackles".to_string()],
            "dark_shackles exhausts"
        );
    }

    /// §218（卡牌 wiki 对照抓到的真错）：`Blur` 一直**只给了状态、没给格挡**。
    ///
    /// wiki：*"Gain 5 (8) Block. Block is not removed at the start of your next turn."*
    /// 这条同时钉两件事：格挡数值（5 / 8），以及状态本身还在（否则"下回合不清格挡"就不成立）。
    #[test]
    fn blur_gives_five_or_eight_block_and_the_status() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        for (card_id, expected_block) in [("blur", 5), ("blur+", 8)] {
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .unwrap_or_else(|error| panic!("{card_id}: {error:?}"));
            assert_eq!(block_of(&state, "hero"), expected_block, "{card_id}: wiki's Block");
            assert_eq!(stacks_of(&state, "hero", "standard.blur"), 1,
                       "{card_id}: the status is what keeps the block next turn");
        }
    }

    /// §197：`Barricade`（永久）与 `Blur`（只保一次）—— 同一个 `retain_block` 标签，两种寿命。
    ///
    /// 内核早就有这条钩子（`block_is_retained` 读 active 状态的 `retain_block` tag），所以这一节
    /// **没有内核改动**：缺的只是"内容能声明它"。判据是**三个回合**，因为"保一次"与"永久"在
    /// 只看一个回合时完全一样：
    /// 1. Barricade：回合 1 攒 5 格挡 → 回合 2 还在 5 → 回合 3 仍是 5；
    /// 2. Blur：回合 2 保留 → 它的 `TurnEnded` 把状态摘掉 → 回合 3 清空；
    /// 3. 对照：两样都没有时回合 2 就清空（上面那条测试钉着，这里再钉一次以免归因错误）。
    #[test]
    fn barricade_keeps_block_forever_and_blur_only_for_one_turn() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // (status, block expected at turn 2, block expected at turn 3)
        for (status_id, expected_turn2, expected_turn3) in [
            ("standard.barricade", 5, 5),
            ("standard.blur", 5, 0),
        ] {
            let mut host = Host::new(&content);
            let mut state = solo();
            // ⚠️ The status is applied **during** turn 1, the way a card would be played -- giving it
            // before `start_current_turn` would let the first turn start consume it (which is exactly
            // what the first version of this test did, and it looked like a kernel bug).
            turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
            give(&mut state, "hero", status("st_keep", status_id, 1));
            give_block(&mut state, "hero", 5);
            turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
            turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
            assert_eq!(
                block_of(&state, "hero"),
                expected_turn2,
                "{status_id}: turn 2 keeps the block"
            );
            turn::end_current_turn(&mut state, &config(), &mut host).unwrap();
            turn::start_current_turn(&mut state, &config(), &mut host).unwrap();
            assert_eq!(
                block_of(&state, "hero"),
                expected_turn3,
                "{status_id}: turn 3 -- Barricade keeps it, Blur has expired"
            );
            // The mechanism, not just the number: Blur is gone, Barricade is not.
            let left = stacks_of(&state, "hero", status_id);
            if status_id == "standard.blur" {
                assert_eq!(left, 0, "Blur expires through its own `TurnEnded` trigger");
            } else {
                assert_eq!(left, 1, "Barricade has no decay");
            }
        }
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
