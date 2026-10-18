//! 出牌（Play a Card）—— 把"手牌里的一张卡"变成"一次真的效果"。
//!
//! **规格**：`docs/spec/play-card-flow.md`（748 行，逐行核对过参考实现）。本文只冻**接口**，
//! 行为一律以那份规格书为准；两者冲突时**规格书赢**，并把冲突报回冻结方。
//!
//! # 这一层为什么必须存在
//!
//! 在它之前，内核能读整份内容、能推进回合、能执行内容里全部 62 张卡的效果程序 —— 但
//! **一张牌都打不出去**：没有费用校验、没有受理校验、没有把卡从手牌搬到弃牌堆/消耗堆。
//! 「能结算一个节目」和「能打一局」之间的那道缝就是本模块。
//!
//! # v1 的范围（**故意窄**，窄得能说清）
//!
//! 收进来的：
//!
//! * **印刷费用** + 费用修饰器管线（`modifiers::Pipeline::Cost`，本模块是它的第一个消费者）。
//!   本内容实测：47 张卡各 1 条 `{Amount: 1|2, ResourceId: "standard.energy"}`、15 张指向
//!   共享的空列表 ⇒ 有效费用 = 印刷费用，X 费在引擎里**不存在**。
//! * **受理校验的五条**（stun / decree / play_condition / one_attack / unplayable），
//!   顺序是 `(Priority 升序, ModifierId 序数升序)` —— **不是**注册顺序，且参考实现的注释
//!   把这条写反了（`Cards/CardPlayValidators.cs:20-22` vs `CombatDefinitionRegistryBuilder.cs:584-592`）。
//! * **三个终态**：Completed ⇒ 入队移区、Faulted ⇒ 直接移区、Cancelled（战斗在程序中途结束）
//!   ⇒ **卡留在手牌**。三个终态是逐位必复刻的，不是"三种差不多的情况"。
//! * 落区：`PlayedCardDestinationZone`（本内容 `DiscardPile` 48 / `ExhaustPile` 14）。
//!
//! 故意**不在** v1 里的（每一条都响亮拒绝，不静默忽略）：
//!
//! 1. **事件队列 / 触发程序**。参考的出牌是队列中介的（build 请求 → 入队 → 排空），
//!    而 `CombatState` 里**没有** `PendingEffects`/`PendingEvents`/`PendingContinuations`
//!    三个字段。所以 v1 是**就地**执行：`CardPlayed` 事件不会入队，
//!    "卡被创建"这类触发器不会跑。这是本模块最大的一处偏差，见 §10 风险 1。
//! 2. **法令（decree）**。`CombatDecrees` 是一个注册表，内核没有；本内容的 23 条状态
//!    `CombatRules` 实测 **23/23 全是 ABSENT** ⇒ 这次内容里法令 0 命中。
//!    但 v1 不能假装"没有法令"就等于"没有法令这条路"，所以相关判定点要留成显式拒绝。
//! 3. **位置系统**（`ForwardSign` 等 9 个位置选择器）—— 与 `SEMANTICS-v1.md` §3-D2 一致。
//!
//! # 为什么 v1 **不**照规格书的 §9.3 做一个 `PlayHost` trait
//!
//! `turn.rs` 需要 `TurnHost`，是因为当时**效果系统根本不存在**，接缝是唯一能测回合机的办法。
//! 出牌这一步不一样：它要的东西（费用、校验、落区、执行）**今天全在**。
//! 为一个还没有第二个实现的 trait 冻 7 个方法，等于提前把语义推给宿主 —— 而本项目的
//! 纪律是「冻一个 trait 方法之后，立刻写一行调用它的代码；写不出来就是开错了」。
//! 所以 v1 是**具体函数**，接缝在注释里点名（将来接法令/事件队列时再抽 trait）。
//!
//! # 三条必须守的纪律（规格书 §9.4）
//!
//! 1. **严格面与请求面必须是两个函数**。参考的四个面里，A/B **抛**、C/D **no-op**；
//!    Rust 没有"抛 vs 静默"的双形态，合成一个函数就会丢掉一条真实语义
//!    （`outcome.WasPlayed == false` 是可观察的，`T:UnplayableCardTests.cs:52` 就在断言它）。
//! 2. **`can_play_card` 必须与 `play_card` 走同一条代码路径**（参考的
//!    `IsCardPlayAllowed` 就是 `try/catch` 同一个调用）。抄一份"只读校验"的实现
//!    迟早会和真路径分叉，而分叉的表现是"界面说能打、真打被拒"。
//! 3. **拒绝时状态必须逐字节不变**（RL 的 transition 成立的前提）。
//!    ⚠️ 但**不是"任何错误都不变"** —— 这是冻结方原先写错、实装时被顶回来的一条：
//!    参考在 `Faulted` 终态下**已经扣过费、且把卡直接搬到了落区**
//!    （`Cards/CardPlay.cs:254-261`，规格书 §7.1 最后一行明写"逐字节不变 = 否"）。
//!    所以"不变"只覆盖**受理拒绝**（校验器/付不起/卡不在手牌…），不覆盖程序执行失败。
//!    ⚠️ 另外"哈希不变"**不等于**"逐字节不变"：参考的 `GetCardPlayTurnStats` 是
//!    **读即创建**（`CombatState.cs:270-274`），被法令读到就会插一个空条目，
//!    而那东西**不进哈希**。本内核没有这张统计表，所以这条对我们是好消息，但要知道它存在。
//!
//! # 实现形状（**这一节是实装之后写的，不是原冻结方的说法**）
//!
//! 三个入口**共用一条路径**：`plan_play`（**纯读**，产出一个 `PlayPlan`）→ `apply_plan`（写状态）。
//!
//! ```text
//! play_card      = plan_play + apply_plan                （严格面：拒绝 = Err）
//! try_play_card  = play_card，但把"正常拒绝"折成 NOT_PLAYED（请求面）
//! can_play_card  = plan_play 一次、丢弃计划             （dry-run：与真路径**同一个** plan）
//! ```
//!
//! 这条分工是规格书 §7.3 / §9.4 的第 1 条纪律唯一可执行的形状：`can_play_card` 里没有
//! **任何**判据，它只问"计划算得出来吗"。
//!
//! ## 与参考实现的**已知偏离**（逐条都在下面代码里有锚点）
//!
//! | # | 偏离 | 为什么 |
//! |---|---|---|
//! | D1 | 落区**就地**搬（参考 Completed 是"入队一条 MoveCardToZone"、Faulted 是直接搬） | 内核没有效果队列。Completed 与 Faulted 因此在**状态层面**同形，只差"是否 fire 事件"（参考 Faulted 也不 fire，`Cards/CardPlay.cs:254-261` vs `Cards/CardZoneEffects.cs:207-211`）—— 所以这条偏差今天**没有可观察后果** |
//! | D2 | `next_effect_chain_number` 按参考的**顶层入队**记账（+1 / +2 / +3，见 [`apply_plan`] 的表） | ⚠️ 这一行原来写的是"**不动**、+0"，2026-10-19 的整局对拍**证伪**了它：C# 规范文本里一次正常出牌让 `chain_num` +3、一次 Cancelled 出牌 +1。原因是参考的每一次**顶层**入队都建根链（`CombatState.cs:386`/`:446`），而"一次排空内部的入队不发号"只对**排空内部**成立 —— 出牌的请求、搬区、动作收尾这三笔都发生在排空内部之外（后两笔在续延里，`CombatEventHandling.cs:107-111`）。内核没有队列，所以这三笔写成三行显式发号 |
//! | D3 | `next_program_execution_id` 在 `exec::execute` **之前**分配 | 参考是"预检 → 分配"（`Effects/Programs/EffectProgramExecution.cs:23` 早于 `:25-28`），风险 #9 要求同序；但 `exec::preflight` 是私有的，本模块拿不到"先验后跑"的缝。**后果**：一个在预检被拒的节目会白吃一个执行号（参考不会）。本内容 62 张卡**全部过预检**（`exec.rs` 的 `every_card_program_in_the_image_runs_because_no_kind_is_refused` 钉着），所以今天不可达 |
//! | D4 | 预检失败与运行期 fault **无法区分** ⇒ 两者都按 Faulted 处理（卡仍落区） | 参考里预检抛异常时终态回调**还没装上**，卡会留在手牌。`exec::execute` 把两件事合成了一个 `Err`。今天不可达（同 D3） |
//! | D5 | 行动作用域（`BeginActionScope`/`CloseAction`）不实现 | `CombatState` 里没有作用域存储，`CombatStateHasher` 也不写它（`CombatState.cs:95` 注释原话："deliberately not part of the snapshot or the state hash"） |
//! | D6 | 战斗日志不实现 | 内核没有日志结构；日志不进哈希（`CombatState.cs:175-184`） |
//! | D7 | 卡牌回合统计（`CardsPlayedThisTurn` 等）不实现 | `CombatState` 里**没有**这张表。它不进哈希（§6.3），但法令要读它 ⇒ 涉及它的两个判定点（`one_attack` 校验器、`first_attack_each_turn_free` 费用修饰器）**在触发条件下响亮失败**（[`PlayError::UnsupportedContent`]），而不是"按 0 算" |
//!
//! ## 冻结方 2026-10-17 的三条裁决（都已落到本文件里）
//!
//! 1. **`Refusal` 补了 [`Refusal::DecreeNoLikeness`]**（规格书 §9.2 草案有、冻结时被删掉的那一条）。
//!    它对应 `CombatDecrees.cs:160-174` 一条**真实存在**的拒绝路径，消息里带命中的那个 tag。
//!    今天不可达（法令闸门在前面），但**占位必须在**。
//! 2. **`PlayError` 补了 [`PlayError::UnsupportedContent`]**，替掉原来借用
//!    `Effect(Ir(IrError::Missing(..)))` 的四个地方（法令 / 回合统计 ×2 / `CardCost`）：
//!    `Ir(Missing)` 的字面意思是"**镜像缺字段**"（内容配错了），而真实原因是"**内核缺实现**"
//!    （我们该去补的）。这两个方向混在一起，排查会整天走错方向。
//!    ⚠️ `Container::CostTable` **没有**加（裁决：会牵动所有穷尽 `match`，收益不值），
//!    `cost_table_full` 继续**借** `Container::Resources`，注释里点名了这是借用。
//! 3. **Cancelled 终态补了成对测试**：`apply_plan` 与测试同文件，所以可以用
//!    `plan_play` → 手动把 `state.result` 改成非 `Ongoing` → `apply_plan` 来构造
//!    "程序跑到一半战斗结束"，不需要 `exec.rs` 配合。见
//!    `a_cancelled_play_leaves_the_card_in_hand_and_pays` 与它的成对反例。
//!
//!    ⚠️ 2026-10-19 之后这条分支**真实可达**了：胜负判定搬到了
//!    `exec::update_standard_combat_result`（就在目标倒下那一行），所以"这一击打死最后
//!    一个敌人"会让程序中途停下、卡留手牌。上面那对手工测试仍然留着 —— 它隔离的是
//!    "`apply_plan` 认不认 `result`"，与"真实路径能不能走到"是两条不同的判据；
//!    后者的测试在 `battle.rs`（`a_lethal_play_leaves_the_card_in_hand_and_the_combat_is_over`）。
//!
//! ## 三处**规格书有误**（都已按现实实现，并报回冻结方）
//!
//! 1. §1.4 第 6 条说"4 张卡（`archive_the_evidence(+)`/`shredder_drawer(+)`）今天跑不完，会报
//!    `ExecError::UnsupportedNode`"。**实测不成立**：W4f 之后 `exec.rs` 补上了
//!    `forEachCardInZone`/`moveCardToZone`，`every_card_program_in_the_image_runs_because_no_kind_is_refused`
//!    断言 **62/62 全跑通、拒绝集合为空**（`exec.rs:4023-4079`）。所以 play.rs 里没有"那 4 张必被拒"这条验收。
//! 2. §1.4 说 `IsAction` "62/62 = `0x0000`（格 8，present 且 false）"。**`0x0000` 是 `BOOL_ABSENT`**
//!    （`content.rs:147`），`content.rs:2158` 的断言就写着"键存在且为 false ≠ 键不存在"。
//!    对出牌路径无影响（缺席与 false 都 ⇒ 不是动作），但"present 且 false"这句话是错的。
//! 3. §0.4 说内核 `Pipeline` "有 4 条"是对的；但**参考的 `CardCost` 修饰器要的
//!    `status_bind::Pipeline` 只有 3 条串**（`status_bind.rs:134-140`），而 `status_bind::decode`
//!    遇到 `"CardCost"` 会报 `BindError::Pipeline` —— 这正是本模块"费用不静默按印刷价结算"的闸门
//!    （见 `declarative_cost`），不是缺口。

use crate::content::{
    CardRow, Content, ABSENT16, BOOL_TRUE, EK_CARD, LIST_ABSENT, LIST_NULL, NULL16, OP_ARR,
};
use crate::exec::{self, ExecContext};
use crate::expr::{self, ExprContext};
use crate::ir::{Ir, IrError, NodeRef, Value};
use crate::modifiers::{self, Candidate, ClaimLedger, Pipeline as ModifierPipeline};
use crate::state::{
    CardInstanceId, CardSlot, CardZone, CapacityError, CombatResult, Combatant, CombatantId,
    CombatantLifecycleState, CombatState, Container, Pool, ResourceId, TagId, ZonePlacement,
};
use crate::status_bind;

/// 一次出牌最多几条费用。
///
/// 参考用 `Dictionary<ResourceId, int>`，条目数无上限；本内容实测**每张卡最多 1 条**。
/// 4 是"够用且能进定长数组"的取法 —— 超出时 [`PaidCosts::push`] 返回 `false` 而不是截断。
pub const MAX_PAID_COSTS: usize = 4;

/// 一次出牌的请求。
///
/// **只接受卡实例**（`CardInstanceId`）：参考的实例面是唯一带落区、标记消费、
/// `CardCostPaid.CardInstanceId` 的路径；定义面对本内容是死路。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PlayRequest {
    /// 谁在出牌。参考在这里做三道检查：战斗进行中、来源存在、来源未倒下。
    pub source: CombatantId,
    /// 手牌里那张卡的**实例** id（不是卡定义 id）。
    pub card: CardInstanceId,
    /// 填进 build context 的 `EventTargetId`。
    ///
    /// ⚠️ 传 `None` **不是错误**：目标选择器会解析出空集，多目标节点打空，
    /// 单体节点则是"没有目标"。参考从不因为目标非法而拒绝出牌。
    pub target: Option<CombatantId>,
}

impl PlayRequest {
    /// 常用形状：给一个人、一张卡、一个目标。
    #[must_use]
    pub const fn new(source: CombatantId, card: CardInstanceId, target: Option<CombatantId>) -> Self {
        Self {
            source,
            card,
            target,
        }
    }
}

/// 受理校验拒绝的理由。**每个变体都来自参考里真实存在的一条校验器**，不是自创。
///
/// 顺序有意义：参考按 `(Priority 升序, ModifierId 序数升序)` 依次问，第一个说不的为止
/// —— 所以**先报哪一条**本身是语义（错误文本不进哈希，但 `Refusal` 进测试断言）。
///
/// ⚠️ **变体数 ≠ 校验器数**：参考一共注册 **5 个**校验器
/// （`StandardCombatPackage.cs:59-63`），而这里是 **6 个**变体 —— 因为
/// `DecreeCardPlayValidator` 内部有**两条**规则（`CombatDecrees.cs:150-158` 与 `:160-174`），
/// 各给一个变体才能把"拒的是哪一条"说清。判定顺序的权威是
/// `VALIDATOR_ORDER`（5 行）+ `DECREE_RULES`（2 行），**不是本枚举的书写顺序**。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Refusal {
    /// `standard.stun` 类的"被击晕"校验器（Priority 100）。
    Stunned,
    /// 卡定义带 `unplayable` 标记（Priority 200，**最后**才问 —— 参考注释写反了）。
    Unplayable,
    /// 卡的 `PlayCondition` 求值为 false（Priority 150）。本内容 62/62 全 ABSENT。
    PlayConditionFalse,
    /// 每回合最多出 N 张的法令（Priority 150）。本内容无法令 ⇒ 恒不触发。
    ///
    /// 判据与消息：`CombatDecrees.cs:150-158`（`played >= cap`，
    /// `"... may play no more than {cap} card(s) this turn by decree."`）。
    DecreeMaxCardsPerTurn {
        /// 上限（`CombatDecrees.Ceiling` 的 `Amount`）。
        cap: i32,
        /// 本回合已经出了几张（`CardPlayTurnStats.CardsPlayedThisTurn`）。
        played: i32,
    },
    /// 同名法令的**第二条**规则：不许拿一张带 `tag` 的牌接续"上一张也带这个 tag"的牌
    /// （Priority 150，`CombatDecrees.cs:160-174`；消息
    /// `"... may not follow a '{tag}' card with another by decree."`）。
    ///
    /// ⚠️ 这条变体是**冻结方 2026-10-17 补的**：规格书 §9.2 草案里有 `DecreeNoLikeness { tag }`，
    /// 冻结时被删掉了，而它对应一条**真实存在**的拒绝路径。`tag` 就是命中的那条
    /// `spec.LikenessTags` 元素（消息里那个 `{tag}`）。
    ///
    /// 今天不可达（本内容 23/23 状态 `CombatRules` 全是 `ABSENT16`，§8.2 实测 ⇒
    /// `refuse_if_any_decree` 一票否决在它前面），但**占位必须在**：少了它，
    /// 接法令的那天会静默少一条规则，而"少一条规则"是看不出来的（§8.3）。
    DecreeNoLikeness {
        /// 命中接续限制的那个 tag。
        tag: TagId,
    },
    /// 每回合最多一次"攻击开场"类限制（Priority 200）。
    OneAttackPerTurn,
}

/// 出牌失败的理由。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlayError {
    /// `Result != Ongoing`（`Cards/CardPlay.cs:82-86`）。
    NotOngoing,
    /// 来源不存在或已倒下（`:88-94`）。
    SourceUnavailable,
    /// 卡定义不在内容注册表里。**这是内核今天唯一能给的答案**：
    /// 内容镜像的 `CARD` 表就是定义表，查不到就是查不到。
    UnknownCard,
    /// 实例不存在、不属于该来源、或不在手牌（`Cards/CardZones.cs:192-200`、`:48-58`）。
    CardNotInHand,
    /// 校验器链拒绝。**带上是哪一条**，因为顺序是语义。
    Refused(Refusal),
    /// 资源池不存在（`Cards/CardPlay.cs:521-525`）。
    MissingResource {
        /// 缺的是哪条资源。
        resource: ResourceId,
    },
    /// 付不起（`:527-531`）。`need`/`have` 都带上，别只给一个字符串 ——
    /// 界面上"2/3 能量"和"付不起"是两件事。
    Unaffordable {
        /// 需要的量。
        need: i32,
        /// 现有的量。
        have: i32,
        /// 哪条资源。
        resource: ResourceId,
    },
    /// 印刷费用是负数（`:449-453`）。内容配错，不是玩家能触发的。
    NegativePrintedCost {
        /// 哪条资源是负的。
        resource: ResourceId,
    },
    /// 效果程序执行失败（透传 [`exec::ExecError`]）。
    Effect(exec::ExecError),
    /// **内核缺能力**：内容真的用到了 v1 没实现的那条路。
    ///
    /// 载荷点名是哪一样（今天的三个取值：`"CombatRules"` 法令、`"CardPlayTurnStats"`
    /// 卡牌回合统计、`"CardCost"` 声明式费用管线）。
    ///
    /// ⚠️ **这个变体是冻结方 2026-10-17 补的，理由值得写下来**：本模块原来把这三处借给
    /// `Effect(Ir(IrError::Missing(_)))`，而 `Ir(Missing)` 的字面意思是"**镜像缺字段**"
    /// —— 那是"内容配错了"。真实原因是"**内核缺实现**" —— 那是我们该去补的。
    /// 混在一起，排查会整天走错方向（去查镜像，而镜像是对的）。
    /// 所以"内核缺能力"与"内容缺字段"必须永远分得开。
    UnsupportedContent(&'static str),
    /// 定容容器满（透传 [`crate::state::CapacityError`]）。
    Capacity(CapacityError),
}

impl From<exec::ExecError> for PlayError {
    fn from(e: exec::ExecError) -> Self {
        PlayError::Effect(e)
    }
}
impl From<CapacityError> for PlayError {
    fn from(e: CapacityError) -> Self {
        PlayError::Capacity(e)
    }
}
impl From<IrError> for PlayError {
    /// `ir::NodeRef` 读字段时的结构错误 —— 内容是"读不出来"，不是"规则拒绝"，
    /// 所以归到 [`PlayError::Effect`] 这一桶（与 `exec` 的处置一致）。
    fn from(e: IrError) -> Self {
        PlayError::Effect(exec::ExecError::Ir(e))
    }
}

/// 一条实际付出的费用。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PaidCost {
    /// 资源 id。
    pub resource: ResourceId,
    /// 实际扣掉的量（**修饰器之后**的值，不是印刷值）。
    pub amount: i32,
}

impl PaidCost {
    /// 空槽。
    pub const EMPTY: Self = Self {
        resource: ResourceId::EMPTY,
        amount: 0,
    };
}

/// 实际付出的费用清单（对应参考的 `CalculatedResourceCost[]`）。
///
/// 做成定长数组是为了零分配；`push` 满了返回 `false`，**绝不静默丢弃**。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PaidCosts {
    entries: [PaidCost; MAX_PAID_COSTS],
    len: u8,
}

impl PaidCosts {
    /// 空清单（0 费卡就是它）。
    pub const EMPTY: Self = Self {
        entries: [PaidCost::EMPTY; MAX_PAID_COSTS],
        len: 0,
    };

    /// 追加一条。**满了返回 `false`**，调用方必须处理。
    pub fn push(&mut self, resource: ResourceId, amount: i32) -> bool {
        let index = self.len as usize;
        if index >= MAX_PAID_COSTS {
            return false;
        }
        self.entries[index] = PaidCost { resource, amount };
        self.len += 1;
        true
    }

    /// 条目数。
    #[must_use]
    pub const fn len(&self) -> usize {
        self.len as usize
    }

    /// 是否为空。
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.len == 0
    }

    /// 按下标取；越界 `None`。
    #[must_use]
    pub fn get(&self, index: usize) -> Option<&PaidCost> {
        if index < self.len as usize {
            Some(&self.entries[index])
        } else {
            None
        }
    }

    /// 按资源 id 查实付额。**没付过就 `None`**（不是 0 —— 0 费卡与"没这条资源"要分得开）。
    #[must_use]
    pub fn amount_for(&self, resource: &ResourceId) -> Option<i32> {
        self.entries[..self.len as usize]
            .iter()
            .find(|c| c.resource == *resource)
            .map(|c| c.amount)
    }
}

/// 一次出牌的报告。做成返回值是为了让测试能断言"确实付了钱、确实落了区"，
/// 而不是只能看哈希。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PlayReport {
    /// 对应参考的 `PlayCardOutcome.WasPlayed`。
    ///
    /// [`try_play_card`] 拒绝时返回 `Ok(PlayReport { played: false, .. })`，
    /// 与参考请求面的 no-op 同构 —— **这条差异就是两个函数存在的理由**。
    pub played: bool,
    /// 实际付出的每条费用。0 费时是 [`PaidCosts::EMPTY`]。
    pub paid: PaidCosts,
    /// 卡最终所在区。
    ///
    /// `None` 有两种成因，都真实存在：**没出牌**，或者**战斗在程序中途结束**
    /// （Cancelled 终态：卡留在手牌，不入队、不搬）。
    pub landed: Option<CardZone>,
    /// 是否算作"打出了一张牌"（`IsAction` 时是 `false`，`Cards/CardPlay.cs:130-150`）。
    pub counted_as_card_played: bool,
}

impl PlayReport {
    /// "什么都没发生"的报告。请求面被拒时返回它。
    pub const NOT_PLAYED: Self = Self {
        played: false,
        paid: PaidCosts::EMPTY,
        landed: None,
        counted_as_card_played: false,
    };
}

// ===========================================================================
// 常量：参考实现里的 id 字面串（`StandardCombatIds.cs`，我逐行核对过）
// ===========================================================================

/// `StandardCombatIds.StunStatus`（`StandardCombatIds.cs:31`）。
const STUN_STATUS: &str = "standard.stun";
/// `StandardCombatIds.FreeNextCardStatus`（`:36`）。
const FREE_NEXT_CARD_STATUS: &str = "standard.free_next_card";
/// `StandardCombatIds.FirstAttackEachTurnFreeStatus`（`:37`）。
const FIRST_ATTACK_FREE_STATUS: &str = "standard.first_attack_each_turn_free";
/// `StandardCombatIds.SkillCostReductionStatus`（`:40`）。
const SKILL_COST_REDUCTION_STATUS: &str = "standard.skill_cost_reduction";
/// `StandardCombatIds.OneAttackPerTurnStatus`（`:35`）。
const ONE_ATTACK_PER_TURN_STATUS: &str = "standard.one_attack_per_turn";
/// `StandardCombatIds.AttackCardTag`（`:77`）。
const ATTACK_TAG: &str = "attack";
/// `StandardCombatIds.SkillCardTag`（`:79`）。
const SKILL_TAG: &str = "skill";
/// `StandardCombatIds.UnplayableTag`（`:88`）。
const UNPLAYABLE_TAG: &str = "unplayable";
/// `StandardCombatIds.CardCostDeltaCounter`（`:131`）。
const CARD_COST_DELTA_COUNTER: &str = "standard.card_cost_delta";

/// `EffectProgram<TContext>.DefaultMaxProgramSteps = 1024`（`EffectProgramContracts.cs:540`）。
/// 本内容 62 个信封都显式写了 1024，这条只兜"缺席"。
const DEFAULT_MAX_PROGRAM_STEPS: u32 = 1024;

// ===========================================================================
// 三个公开入口
// ===========================================================================

/// 严格面：拒绝 = `Err`，与参考实现 A/B 两个面的"抛"同构。
///
/// # Errors
///
/// 见 [`PlayError`]。**拒绝路径保证状态逐字节不变**。
///
/// ⚠️ **程序 fault 不在这句保证里**（这是本模块对冻结文档的一处更正）：
/// 参考在 `Faulted` 终态下**已经**扣过费、且把卡**直接搬**到了落区（`Cards/CardPlay.cs:254-261`），
/// 规格书 §7.1 最后一行明写"状态是否逐字节不变 = **否**"。所以本函数在 effect fault 时
/// 返回 `Err(PlayError::Effect(..))`，而状态**已经变了**（费用已付、卡已落区）。
pub fn play_card(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    req: &PlayRequest,
) -> Result<PlayReport, PlayError> {
    let plan = plan_play(state, content, req)?;
    apply_plan(state, &plan, Face::Strict)
}

/// 请求面（**游戏真实路径**）：拒绝 = `Ok(PlayReport::NOT_PLAYED)`。
///
/// 参考的命令面把 `PlayCardCommand` 改写成 `PlayCardEffectRequest` 再排空
/// （`CombatReplayRunner.cs:29-36`），请求面对"不合格"的处理是 **no-op 而不是抛**。
///
/// 实现上**直接复用**[`play_card`] 的同一个 `plan_play` + `apply_plan`，只把
/// [`Face`] 标成 `Queued` —— "先按严格面跑一遍、再把正常拒绝折成 NOT_PLAYED"与参考的
/// no-op 逐位同构，而且两份语义**不可能漂移**（纪律 1 的可执行形状）。
/// 唯一的差别就是 [`Face`] 文档里那一次顶层入队（+1 个链号）。
///
/// # Errors
///
/// 只有"真的坏了"（内容读不出、容器满、程序执行失败）才 `Err`；
/// "这张牌现在不能打"是 `Ok(PlayReport::NOT_PLAYED)`。
pub fn try_play_card(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    req: &PlayRequest,
) -> Result<PlayReport, PlayError> {
    match play_card_queued(state, content, req) {
        Ok(report) => Ok(report),
        Err(error) if is_normal_refusal(&error) => Ok(PlayReport::NOT_PLAYED),
        Err(error) => Err(error),
    }
}

/// [`try_play_card`] 的那条路：与 [`play_card`] **同一份** plan/apply，只把面标对。
fn play_card_queued(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    req: &PlayRequest,
) -> Result<PlayReport, PlayError> {
    match plan_play(state, content, req) {
        Ok(plan) => apply_plan(state, &plan, Face::Queued),
        Err(error) => {
            // ⚠️ **被拒的那次出牌也发一个链号**（2026-10-19 逐卡对拍实测）。
            //
            // 参考的请求面是"先入队、后校验"：`ScenarioRunner.cs:121` 的
            // `EnqueueEffect(new PlayCardEffectRequest(…))` 在没有环境链时立刻
            // `CreateRootEffectChain()`（`CombatState.cs:386`），而**拒绝发生在 handler 里**
            // （`Cards/PlayCardEffects.cs:54-58` 的 unplayable tag、`:64-69` 的
            // `IsCardPlayAllowed`、`:74-82` 的付不起）⇒ 那次发号**已经发生过**。
            //
            // 两个例外，都在入队**之前**就被挡掉了，所以是 +0：
            // * `CardNotInHand`：`ScenarioRunner.cs:113-117` 用 `FirstOrDefault` 先找卡；
            // * `NotOngoing`：`ScenarioRunner.cs:40-44` 根本不下发这一步。
            //
            // 这条偏移原来被记成"在本内容上不可观察"，理由是"唯一被拒的出牌是卡不在手牌"。
            // **实测证伪**：`red_tape` / `unsigned_form` 带着 `unplayable` 标签，它们的出牌
            // 走的是校验器那一支，参考 +1、内核原来是 +0 ⇒ `chain_num` 差 1。
            if is_normal_refusal(&error)
                && !matches!(error, PlayError::CardNotInHand | PlayError::NotOngoing)
            {
                let _refused_request_chain = state.create_root_effect_chain();
            }
            Err(error)
        }
    }
}

/// dry-run：只回答"能不能打"，**绝不动状态**。
///
/// ⚠️ 必须由 [`play_card`] 的同一条代码路径实现（参考的 `IsCardPlayAllowed` 就是
/// `try/catch` 同一个调用）。抄一份"只读校验"迟早会和真路径分叉，
/// 而分叉的表现是"界面说能打、真打被拒"。
///
/// 本实现里它就是 `plan_play` 的一次调用、把计划丢掉 —— **一行判据都没有**。
/// 与参考的一处有意差别：参考的 `IsCardPlayAllowed` **只跑校验器**、不看付不付得起
/// （付得起是它调用方自己另查的，`Cards/PlayCardEffects.cs:74-82`）；本函数把"付得起"
/// 也算进计划里，因为冻结签名给的是 [`PlayError`]、而规格书 §9.4 要求它与真路径答案一致。
///
/// # Errors
///
/// 与 [`play_card`] 同集合（程序执行期的错误不算 —— 它不可能在 dry-run 里出现）。
pub fn can_play_card(
    state: &CombatState,
    content: Option<&Content<'_>>,
    req: &PlayRequest,
) -> Result<(), PlayError> {
    plan_play(state, content, req).map(|_| ())
}

/// "这张牌现在不能打"这一类**正常拒绝**（请求面把它们折成 no-op）。
///
/// 逐个对应参考请求面的早退分支：
/// * `NotOngoing`：请求处理器自己**没有**这条检查，靠外层队列循环
///   `while (hasPending && Result == Ongoing)` 停下来（`CombatEventHandling.cs:99-111`）⇒ 不执行 = no-op；
/// * `SourceUnavailable`：`Cards/PlayCardEffects.cs:28-32`；
/// * `CardNotInHand`：`:36-48`；
/// * `Refused`：`:64-69`（`IsCardPlayAllowed` 吞掉）；
/// * `MissingResource` / `Unaffordable`：`:74-82`。
///
/// **不在**这张表里的五种：
/// * `UnknownCard`：请求面在定义未注册时也**会抛**（`Cards/PlayCardEffects.cs:50` 的 `registry.GetCard`）；
/// * `NegativePrintedCost`：内容配错了（`:449-453`），请求面的预检也会抛（`:71-72`）；
/// * `Effect` / `Capacity`：执行期失败；
/// * [`PlayError::UnsupportedContent`]：**内核缺实现**。它必须响亮穿过请求面 ——
///   折成 no-op 等于"这张牌安静地打不出去"，而原因是我们自己没写。
const fn is_normal_refusal(error: &PlayError) -> bool {
    matches!(
        error,
        PlayError::NotOngoing
            | PlayError::SourceUnavailable
            | PlayError::CardNotInHand
            | PlayError::Refused(_)
            | PlayError::MissingResource { .. }
            | PlayError::Unaffordable { .. }
    )
}

// ===========================================================================
// 计划（纯读）与执行（写状态）
// ===========================================================================

/// 这一次出牌走的是参考的**哪一面** —— 两面只差一处记账：请求面会先**入队**一条请求。
///
/// * `Queued`：`ScenarioRunner.cs:121`（以及 `CombatReplayRunner.cs:31`）那一层的
///   `combat.EnqueueEffect(new PlayCardEffectRequest(…))`。那一刻没有环境链 ⇒
///   `CurrentEffectChain ?? CreateRootEffectChain()`（`CombatState.cs:386`）⇒ **根链 +1**。
/// * `Strict`：`CombatCardPlayProcessor.PlayCard` / `PlayCardInstance` 被直接调用
///   （`Cards/CardPlay.cs:17-68`），没有那次入队 ⇒ +0。
///
/// 这一处差别**不是我推的，是量出来的**：整局对拍里内核每张牌少 3 个链号，
/// 拆开正好是"请求 +1、节目跑完的搬区 +1、动作收尾 +1"（后两个见 [`apply_plan`]）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Face {
    /// 严格面：直接调处理器，没有任何顶层入队。
    Strict,
    /// 请求面：先入队一条 `PlayCardEffectRequest`（+1 个链号），再由处理器排空。
    Queued,
}

/// 一次出牌的**计划**：算得出来就能打，算不出来就是拒绝。
///
/// 它只装"纯读阶段学到的事实"，不持有 `CombatState` 的借用 —— 这正是
/// [`can_play_card`] 能与 [`play_card`] 共用路径而不打架的原因。
struct PlayPlan<'a> {
    source: CombatantId,
    instance: CardInstanceId,
    destination: CardZone,
    paid: PaidCosts,
    is_action: bool,
    /// 卡的 on-play 节目根（`None` = 卡定义没有 `Program`，走 5.12 分支）。
    program: Option<NodeRef<'a>>,
    max_steps: u32,
    target: Option<CombatantId>,
    content: &'a Content<'a>,
}

/// 出牌校验/算费时的"这张卡在这张桌上"的视图。
///
/// **故意不存 `&Combatant`**：那会把 `CombatState` 的不可变借用带进 [`PlayPlan`]，
/// 于是 `apply_plan` 想改状态就得先等计划析构。要人的地方按 id 现查（代价是几次线性扫，
/// 比一个多活的借用便宜）。
struct CardOnTable<'a> {
    content: &'a Content<'a>,
    row: CardRow<'a>,
    source: CombatantId,
    instance: CardInstanceId,
    target: Option<CombatantId>,
    is_action: bool,
    is_attack: bool,
    is_skill: bool,
}

/// 六阶段里的前五阶段：**纯读**，任何拒绝都不改状态。
///
/// 阶段序照 `Cards/CardPlay.cs:70-109`：静态守卫 → 来源 → 定义 → 受理校验链 → 费用。
/// 第 6 阶段（排空队列）在 v1 里不存在（没有队列）。
fn plan_play<'c>(
    state: &CombatState,
    content: Option<&'c Content<'c>>,
    req: &PlayRequest,
) -> Result<PlayPlan<'c>, PlayError> {
    // ── 阶段 1（`Cards/CardPlay.cs:82-86`）：战斗必须还在进行。
    if state.result != CombatResult::Ongoing {
        return Err(PlayError::NotOngoing);
    }

    // ── 阶段 2（`:88-94`）：`GetCombatant` 缺人即抛；`!IsAlive` 即抛。
    // `IsAlive` 的定义是 `LifecycleState == Alive`（`CombatantState.cs:79`，我读过那一行）。
    let source = state
        .combatant(&req.source)
        .ok_or(PlayError::SourceUnavailable)?;
    if source.lifecycle_state != CombatantLifecycleState::Alive {
        return Err(PlayError::SourceUnavailable);
    }

    // ── 内容：内核的卡定义表**就是**镜像的 `CARD` 表（没有独立注册表）。
    // 没有镜像 ⇒ 查不到任何定义 ⇒ `UnknownCard`。**响亮**：`try_play_card` 不会把
    // 这一条折成 no-op（参考在这一步也抛，`Cards/PlayCardEffects.cs:50`）。
    let content = content.ok_or(PlayError::UnknownCard)?;

    // ── 阶段 2.5（`Cards/CardPlay.cs:45-58`）：实例存在、且**在手牌**。
    let (zone, slot) =
        find_card_slot(state, &req.source, &req.card).ok_or(PlayError::CardNotInHand)?;
    if zone != CardZone::Hand {
        return Err(PlayError::CardNotInHand);
    }
    let definition = state
        .card(slot)
        .map(|card| card.definition_id)
        .ok_or(PlayError::CardNotInHand)?;

    // ── 阶段 3（`:96`）：取定义。`registry.GetCard` 未注册即抛
    // （`CombatDefinitionRegistry.cs:133-138`）。
    let entry = content
        .lookup_in(definition.as_str(), EK_CARD)
        .ok_or(PlayError::UnknownCard)?;
    let index = u32::from(entry.index);
    let row = content.card(index).ok_or(PlayError::UnknownCard)?;

    let card = CardOnTable {
        content,
        row,
        source: req.source,
        instance: req.card,
        target: req.target,
        // `IsAction` 本内容 62/62 是 `BOOL_ABSENT`（= 0），缺席 ⇒ 不是动作。
        is_action: row.is_action() == BOOL_TRUE,
        is_attack: card_has_tag(content, row, ATTACK_TAG)?,
        is_skill: card_has_tag(content, row, SKILL_TAG)?,
    };

    // ── 法令闸门（规格书 §8.2/§8.3）：v1 没有法令实现，所以"内容里真的有法令"
    // 必须**响亮失败**，而不是按"没有法令"照算。放在校验器之前是因为它是
    // "这场战斗的规则我们读不懂"，不是一条游戏规则。
    refuse_if_any_decree(state, &card)?;

    // ── 阶段 4（`:98-104` → `:384-402`）：受理校验器链。
    validate_card_play(state, &card)?;

    // ── 阶段 5（`:106` → `:114-294`）：算费用 + 付得起校验（`EnsureCostsCanBePaid`）。
    let paid = calculate_costs(state, &card)?;
    ensure_affordable(state, &card.source, &paid)?;

    // ── 落点（`:298-302`）：法令 `PlayedCardsExhaust` 已被上面那道闸门否决，
    // 所以这里只剩卡定义自己的 `PlayedCardDestinationZone`。
    let destination = played_card_destination(&card)?;

    // ── 节目与步数预算（`EffectProgram` 信封）。
    let (program, max_steps) = card_program(&card)?;

    Ok(PlayPlan {
        source: card.source,
        instance: card.instance,
        destination,
        paid,
        is_action: card.is_action,
        program,
        max_steps,
        target: card.target,
        content,
    })
}

/// 把计划落到状态上。**这是唯一会写状态的地方**。
///
/// 顺序逐字照 `Cards/CardPlay.cs:123-294`：付费 → （分配执行号）→ 跑节目 → 终态落区。
///
/// # `next_effect_chain_number` 的四笔账（2026-10-19 整局对拍实测）
///
/// 参考只在**顶层入队**时建根链（`CombatState.cs:386`/`:446` 的
/// `CurrentEffectChain ?? CreateRootEffectChain()`），而效果/事件的解析都在
/// `using (EnterEffectChain(entry.EffectChain))` 里跑（`CombatEffectQueueProcessor.cs:32`、
/// `CombatEventHandling.cs:60`），所以**一次排空里的入队不再发号**。
///
/// 一次出牌因此有 3 笔（严格面 2 笔），每一笔都能指出参考的哪一行：
///
/// | 笔 | 参考 | 什么时候发生 | Δchain |
/// |---|---|---|---|
/// | 请求 | `ScenarioRunner.cs:121` 的 `EnqueueEffect(PlayCardEffectRequest)` | [`Face::Queued`] | +1 |
/// | 搬区 | `Cards/CardPlay.cs:251-252` 的 `EnqueueEffect(MoveCardToZone)`，由 `onTerminal` 触发，而 `onTerminal` 是**从续延里**跑的（`CombatEventHandling.cs:107-111`，在 `EnterEffectChain` 之外） | Completed | +1 |
/// | 收尾 | `:280` 的 `CloseAction` ⇒ `EnqueueEvent(ActionResolved)`（`:311`），同一个 `onTerminal` | Completed | +1 |
///
/// ⇒ 一张**正常打完**的牌 = +3；**Cancelled**（程序中途战斗结束）= **+1**
/// （`CloseAction` 那次入队落在还开着的链上 ⇒ +0，搬区根本不发生）；
/// **Faulted** = +1（搬区是**直接搬**，`:254-261`；`MarkFaulted` 在节点的
/// `using (EnterEffectChain)` 里跑 ⇒ 收尾 +0）；**无节目的卡** = +2
/// （`:286` 的搬区在链里 +0，`:292` 的 `CloseAction` 从续延里跑 +1）。
///
/// **证据强度（别把这两层混起来读）**：
/// * **总数是实测的、且唯一**：四个场景 14 个步边界的 `chain_num` 由"把 C# 规范文本里
///   这一个数改成候选值再算 SHA-256"反推出**每组唯一解**；`+3 / +1 / +2` 是那些数相减得到的。
/// * **拆成三笔是读源码拆的、没有逐笔单独验证**：内核没有队列，无法让"只发生第一笔"的
///   局面出现一次，所以"请求 / 搬区 / 收尾"各占 1 这件事的依据是 `CombatState.cs:386`、
///   `Cards/CardPlay.cs:251`、`:311` 与 `CombatEventHandling.cs:107-111`（续延跑在
///   `EnterEffectChain` 之外）—— **我读过这几段，但"每笔恰好 1"只由总数反证**。
///   如果将来出现一个总数对不上的场景，第一个该怀疑的就是这个拆法。
///
/// ⚠️ **2026-10-19 修正（逐卡对拍实测）**：这一节原来的两处记账都是错的，两处都已改掉：
///
/// 1. 原来写"被校验器/付不起拒掉的出牌 **+0**，因为内核在 [`plan_play`] 里就拒了"。**错**。
///    参考在 `ScenarioRunner.cs:121` 先入队（`CombatState.cs:386` 建根链），拒绝发生在
///    handler 里面 ⇒ **+1**。现在 [`play_card_queued`] 在正常拒绝时补发一个链号
///    （`CardNotInHand` / `NotOngoing` 除外 —— 那两个参考在入队前就挡掉了）。
///    证据：`red_tape` / `unsigned_form`（带 `unplayable` 标签）的规范文本 `chain_num`。
/// 2. 原来写"Completed ⇒ 搬区 +1"。**只在卡还在手牌时对**：`onTerminal` 的守卫
///    （`Cards/CardPlay.cs:245-247`）在卡已被自己的节目挪出手牌时直接 return，那次入队
///    不发生 ⇒ +0。证据：`archive_the_evidence` / `shredder_drawer`（`forEachCardInZone`
///    → `moveCardToZone`）的 `chain_num` 原来比参考多 1。
/// 3. **已知偏差、故意留着红（2026-10-19 逐卡多层对拍）**：上面那张表的"收尾 +1"也不是无条件的。
///    节目里的 `forEachCardInZone` 走过 **≥2** 张牌时（卡把自己和另一张一起搬出去），
///    参考的**收尾也不发号** ⇒ 出牌只 +1。`shredder_drawer` / `shredder_drawer+` 的
///    `play_again` 变体（牌组 2 张）因此在 `CARD_MULTI` 里有 2 格红（step0 `chain_num`
///    4 / 3）。**内核没有跟着改** —— 依据强度、机制（续延调度次序）与"为什么不改"全写在
///    [`apply_plan`] 里账 2/账 3 那一段的 `⚠️⚠️ 已知偏差` 注释里，改之前先读它。
///
/// 今天实测的四笔账：**正常打完 = +3**（请求 / 搬区 / 收尾）；**Cancelled** = +1；
/// **Faulted** = +1（搬区是直接搬，`Cards/CardPlay.cs:254-261`）；**无节目的卡** = +2
/// （`:286` 的搬区在链里 +0，`:292` 的 `CloseAction` 从续延里跑 +1）；**被校验器拒绝** = +1。
fn apply_plan(
    state: &mut CombatState,
    plan: &PlayPlan<'_>,
    face: Face,
) -> Result<PlayReport, PlayError> {
    // ── 账 1：请求面那一次顶层入队（见本函数的表）。
    if face == Face::Queued {
        let _request_chain = state.create_root_effect_chain();
    }

    // `:125` EnsureCostsCanBePaid 已经在计划里做过；`:126` PayCosts。
    // 这里再查一次是**防御式**的（计划与付款之间不可能有别人插进来，但"半付"是
    // 最脏的一种中间态，多一次只读检查换它不出现）。
    ensure_affordable(state, &plan.source, &plan.paid)?;
    pay_costs(state, &plan.source, &plan.paid)?;

    let counted_as_card_played = !plan.is_action;

    // ── 无节目分支（`Cards/CardPlay.cs:283-293`，5.12）。
    // 参考在这里入队一条 MoveCardToZone 再关作用域；本内核就地搬（D1）。
    let Some(root) = plan.program else {
        let settled = settle_card(state, plan)?;
        // 账 2'：`:292` 的 `EnqueueContinuation(CloseAction)` —— 续延在 `EnterEffectChain`
        // 之外跑 ⇒ 那一次 `EnqueueEvent(ActionResolved)` 建根链。搬区那次（`:286`）在链里 ⇒ +0。
        let _wrap_up_chain = state.create_root_effect_chain();
        return Ok(PlayReport {
            played: true,
            paid: plan.paid,
            landed: settled.landed,
            counted_as_card_played,
        });
    };

    // ── 节目分支（`:221-281`，5.11）。参考的 `EffectProgramExecutor.Execute` 一进来就
    // `AllocateProgramExecutionId()`（`Effects/Programs/EffectProgramExecution.cs:25-28`），
    // 顺序偏差见模块头 D3。
    let _execution_id = state.allocate_program_execution_id();

    // 目标走 `EventTargetId` 这一条：程序里的 `sel.eventTarget` 读的就是它
    // （`Cards/CardPlay.cs:404-418` 建 build context；`exec.rs` 的 `ExecContext::event_target`）。
    let outcome = {
        let mut ctx = ExecContext::new(
            state,
            Some(plan.source),
            plan.target,
            None,
            plan.max_steps,
        )
        .with_content(plan.content);
        exec::execute(root, &mut ctx)
    };

    // 三个终态（`Cards/CardPlay.cs:240-263`）：
    // * Cancelled：程序执行中途战斗结束（`SetResult` 取消在飞帧，`CombatState.cs:358-359`）
    //   ⇒ 什么都不做，**卡留在手牌**（`:240-241`、`:262`；测试
    //   `T:CardProgramTerminalCleanupTests.cs:62-78` 断言卡仍在 Hand）。
    // * Completed：正常落区。
    // * Faulted：**仍然落区**（`:254-261`），错误照实透传。
    //
    // ⚠️ `cancelled` 从 2026-10-19 起**真的会**为真：胜负判定搬到了
    // `exec::update_standard_combat_result`，就在目标倒下那一行（见那里与
    // `battle.rs` 的 `FROZEN_GAP_RESULT`）。在那之前这一支只有手工改 `state.result`
    // 才走得到。
    let cancelled = state.result != CombatResult::Ongoing;
    match outcome {
        Ok(_) if cancelled => Ok(PlayReport {
            played: true,
            paid: plan.paid,
            landed: None,
            counted_as_card_played,
        }),
        Ok(_) => {
            let settled = settle_card(state, plan)?;
            // 账 2 + 账 3：`onTerminal(Completed)` 里的两次入队（`:251-252` 的搬区、
            // `:280` 的 `CloseAction`）。两次都在续延里跑 ⇒ 各建一条根链 ——
            // **但搬区那笔要先过 `:245-247` 的手牌守卫**：卡被自己的节目挪走了，参考就
            // 直接 return，不会入队，所以这里也不发号（逐卡对拍实测：无条件发号会多 1）。
            //
            // ⚠️⚠️ **已知偏差，故意留着红（2026-10-19）**：`CARD_MULTI` 里
            // `shredder_drawer` / `shredder_drawer+` 的 `play_again` 变体在这一笔上与参考差 1 ——
            // 牌组 2 张（两张都带 `junk`、开局都在手牌）、节目把**两张**都搬进消耗堆时：
            // step0 `chain_num` 内核 **4** / 参考 **3**，规范文本其余 23 行逐字节相同
            // （牌区也对：两张都在 `ExhaustPile`，`enemy_hp` 491）。只差这 1 个链号，
            // 而且它从 step0 一直带到底（step1 6/5、step2 10/9）。
            // 复现：`python native\_diag_card_multi.py 38 0 --full`
            //（`%39` 是它的 `+` 版，同一格；只差 index）。
            //
            // 参考的**实测**账（全 62 卡 × 2 变体的 `chain_num` 读出来的，已扣掉"开回合 +1"
            // 这个常量；下面三个数都是**结果实测**，不是推的）：
            //   | 节目形状 | forEach 走牌次数 | 出牌合计 Δchain | 拆开 |
            //   |---|---|---|---|
            //   | 没有 `forEachCardInZone`（如 `paper_cut`） | 0 | **+3** | 请求 / 搬区 / 收尾 |
            //   | 走牌 + 卡把自己搬出去（`archive_the_evidence`：`takeFirst=1`，牌组 2 张也只走 1 次） | 1 | **+2** | 请求 / ~~搬区~~ / 收尾 |
            //   | 走牌 + 把**两张**都搬出去（`shredder_drawer` 牌组 2） | ≥2 | **+1** | 请求 / ~~搬区~~ / ~~收尾~~ |
            // 第三个 **+1（不是 +2）** 就是本内核与参考差的那 1：搬区被守卫吃掉（内核一致），
            // 但**连收尾也不发号**了。
            //
            // **为什么收尾会变成 0**（这一半是读源码推的，见下面"依据强度"）：
            // 收尾是 `onTerminal` → `CloseAction` → `EnqueueEvent(ActionResolved)`
            // （`Cards/CardPlay.cs:277-281`、`:306-312`），它**本身不建根链** —— 建不建取决于
            // 那一刻 `CurrentEffectChain` 是不是 null（`CombatState.cs:442-452`；搬区那条
            // `EnqueueEffect` 同理，`:382-392`）。而 `onTerminal` 是在节目帧进入终态时跑的
            // （`Effects/Programs/EffectProgramIdentity.cs:104-111`、`:121-129`），
            // 所以问题变成"节目是在**哪一段代码里**到达终态的"：
            //   * `ForEachCardInZoneNodeExecutor.ExecuteIteration` 在**续延里**用
            //     `using (c.EnterEffectChain(ctx.EffectChain!))` 接着走剩下的迭代
            //     （`EffectProgramNodeExecutors.cs:496-504`）⇒ 走牌**走完**那一刻，链**在**；
            //   * 兄弟节点自己的完成是 `EnqueueContinuation(onComplete)`
            //     （`dealDamage` `:638-641` / `gainBlock` `:779`），而续延在**顶层**跑
            //     （`CombatEventHandling.cs:97-113`）⇒ 兄弟完成那一刻，链**不在**；
            //   * `SequenceNodeExecutor` 是**先把所有子节点都派发下去**、再数剩余个数
            //     （`:202-211`），于是"最后一个完成的是谁"决定了终态落在链里还是链外：
            //     走 1 次时最后完成的是兄弟节点（收尾 +1）；走 ≥2 次时（续延 FIFO：
            //     兄弟的续延在走牌第二趟之前）最后完成的是走牌循环本身（终态在链里 ⇒ 收尾 +0）。
            //
            // **依据强度（别把这两层混起来读）**：
            // * "1 次 ⇒ +2、≥2 次 ⇒ +1"是**实测的**：同一张卡、同一段节目，牌组 1 张时
            //   `chain_num`=4（+2，内核绿）、牌组 2 张时 =3（+1，内核多 1）；
            //   `archive_the_evidence` 的 `takeFirst=1` 让它在牌组 2 张时仍走 1 次 ⇒ 仍是 +2（绿）。
            //   "≥2"里的"2"只有这一个观测点，机制预测 ≥3 也一样，但**没有第三个变体量过**
            //   （`native/fight_diff.py` 的 `MULTI_VARIANTS` 只有牌组 2 与 1 两个）。
            // * "续延 FIFO 决定谁最后完成"这一段是**读源码推的、没有逐行验证**：参考运行时的
            //   续延排队次序无法在不改 `native/` 的前提下观测。
            //
            // **为什么内核不改（保留这 2 格红）**：要表达"收尾发不发号"，就得在内核里复现参考的
            // **续延调度次序**。内核没有队列，`exec` 也不报告"节目终态落在哪一段链里"；在
            // `apply_plan` 里唯一够得着的判据是"这次节目里那个 forEach 走了几张"这种**形状判断**——
            // 那等于把参考的一个调度副作用硬编码成内容形状规则，也正是"把 4 改成 3 试出来的绿"。
            // 真要修，正路是让 `exec` 回报"节目终态是否落在某条在用的链里"，那是另一个文件、
            // 另一轮的事（本轮硬约束只准动 `play.rs`）。
            if settled.moved {
                let _move_chain = state.create_root_effect_chain();
            }
            let _wrap_up_chain = state.create_root_effect_chain();
            Ok(PlayReport {
                played: true,
                paid: plan.paid,
                landed: settled.landed,
                counted_as_card_played,
            })
        }
        Err(error) => {
            // ⚠️ 这一支**会写状态**（卡落区），然后才把错误还回去 —— 规格书 §5.2/§7.1 定的。
            // 落区是**直接搬**（`:256` 的 `zones.MoveCardToZone`），不入队 ⇒ 不建根链。
            settle_card(state, plan)?;
            Err(PlayError::Effect(error))
        }
    }
}

// ===========================================================================
// 阶段 1-3 的小工具
// ===========================================================================

/// 在某个战斗员的 7 个牌区里找一张卡的 `(区, 池槽位)`。
///
/// 参考的 `CombatantCardZones.GetCard(id)` 是**线性扫全部 7 个区**
/// （`Cards/CardZones.cs:192-200`），这里同形。内核的 `move_card` 要调用方自己给 `from`
/// （`state.rs:1939`），所以这一步是必需的，不是多余。
fn find_card_slot(
    state: &CombatState,
    owner: &CombatantId,
    card: &CardInstanceId,
) -> Option<(CardZone, CardSlot)> {
    let zones = state.card_zones(owner)?;
    for zone in CardZone::ALL {
        for index in 0..zones.count(zone) {
            let Some(slot) = zones.slot_at(zone, index) else {
                continue;
            };
            if state.card(slot).map(|instance| instance.id) == Some(*card) {
                return Some((zone, slot));
            }
        }
    }
    None
}

/// 卡定义上有没有这个 tag（参考 `context.Card.Tags.Contains(tag)`）。
///
/// ⚠️ 形状是**实测**的，而且是 `exec.rs` 里踩过一次坑的形状（`exec.rs:1843-1847` 记录了
/// 那次"把另一个列表当 tag 集合、于是静默匹配 0 张"）：格是 `F_TERM` → `_arr` →
/// 唯一字段是 `F_TERMLIST`，AUX 里装的是**term id**，每个元素是 `_wrap_lower`（op 6），
/// tag 串在那个 term 的槽 0。
///
/// 三个"不是错误"的分支（`exec.rs:1838-1841`）：定义不在 `CARD` 表 / 格是哨兵 / 列表里没有。
///
/// ⚠️ 这里**抄了一份** `exec::card_definition_has_tag`（它是私有的）。抄的理由与代价都写明：
/// 冻结面没把它公开，而"只准改 play.rs"这条约束禁止我去 `exec.rs` 加 `pub`。
/// 将来把它提升成 `content.rs` 的公共函数时，这一份应当删掉。
fn card_has_tag(content: &Content<'_>, row: CardRow<'_>, tag: &str) -> Result<bool, PlayError> {
    let Some(cell) = row.row().cell_index("Tags") else {
        return Err(IrError::Missing("Tags").into());
    };
    if row.row().cell_kind(cell) != Some(crate::content::F_TERM) {
        return Err(IrError::WrongKind("F_TERM").into());
    }
    let handle = row.tags();
    let list_id = match handle {
        ABSENT16 | NULL16 => return Ok(false),
        id => id,
    };
    let list = content.term(list_id).ok_or(IrError::Term(list_id))?;
    if list.op != OP_ARR {
        return Err(IrError::WrongKind("_arr").into());
    }
    let start = list.slot(0).ok_or(IrError::Slot)?;
    let count = list.slot(1).ok_or(IrError::Slot)?;
    if count == LIST_ABSENT || count == LIST_NULL {
        return Ok(false);
    }
    for index in 0..count {
        let cell = start.checked_add(index).ok_or(IrError::List)?;
        let element = content.aux(cell).ok_or(IrError::List)?;
        let element_term = content.term(element).ok_or(IrError::Term(element))?;
        if element_term.op != crate::content::OP_WRAP_LOWER {
            return Err(IrError::WrongKind("_wrap_lower").into());
        }
        let string = element_term.slot(0).ok_or(IrError::Slot)?;
        if content.string(string) == Some(tag) {
            return Ok(true);
        }
    }
    Ok(false)
}

// ===========================================================================
// 阶段 4：受理校验器链（五条，按 `(Priority, ModifierId)` 升序）
// ===========================================================================

/// 标准包注册的四/五个校验器。
///
/// 注册点：`StandardCombatPackage.cs:59-63`（注册顺序 Unplayable→Stun→PlayCondition→
/// OneAttackPerTurn→Decree）；**执行顺序是升序重排后的**（`CombatDefinitionRegistryBuilder.cs:199`
/// 的 `SortByPriorityThenId`，比较器 `:584-592`），所以是
/// stun(100) → decree(150) → play_condition(150) → one_attack(200) → unplayable(200)。
///
/// ⚠️ 参考实现的注释（`Cards/CardPlayValidators.cs:20-22`："Highest priority so it short-circuits
/// before other checks"、`CombatDecrees.cs:135`）**与它自己的实现相反**：200 是**最后**跑的那一档。
/// 本模块按真实排序实现，并用 `the_validator_order_is_priority_then_modifier_id` 钉住。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Validator {
    Stun,
    Decree,
    PlayCondition,
    OneAttackPerTurn,
    Unplayable,
}

impl Validator {
    /// 升序重排后的执行序（`CombatDefinitionRegistryBuilder.cs:588` 升序 + 同优先级按 id 字节序）。
    ///
    /// 生产路径不需要这个数（顺序已经在 [`VALIDATOR_ORDER`] 里定死），它只被
    /// `the_validator_order_is_priority_then_modifier_id` 用来**证明**那张表是按 (priority, id) 排的。
    #[cfg(test)]
    const fn priority(self) -> i32 {
        match self {
            Validator::Stun => 100,
            Validator::Decree | Validator::PlayCondition => 150,
            Validator::OneAttackPerTurn | Validator::Unplayable => 200,
        }
    }

    /// `ModifierId`（排序第二级，`string.CompareOrdinal`）；也是这条校验器的身份。
    #[cfg(test)]
    const fn modifier_id(self) -> &'static str {
        match self {
            Validator::Stun => "standard.stun_validator",
            Validator::Decree => "standard.decree_validator",
            Validator::PlayCondition => "standard.play_condition_validator",
            Validator::OneAttackPerTurn => "standard.one_attack_per_turn_validator",
            Validator::Unplayable => "standard.unplayable_validator",
        }
    }
}

/// 执行序 = 升序后的固定表。**顺序就是语义**：第一个说不的为止。
const VALIDATOR_ORDER: [Validator; 5] = [
    Validator::Stun,
    Validator::Decree,
    Validator::PlayCondition,
    Validator::OneAttackPerTurn,
    Validator::Unplayable,
];

/// 逐条问，第一条说不的立刻返回（`Cards/CardPlay.cs:400-401` 的 `foreach` + 抛）。
fn validate_card_play(state: &CombatState, card: &CardOnTable<'_>) -> Result<(), PlayError> {
    for validator in VALIDATOR_ORDER {
        let verdict = match validator {
            Validator::Stun => stun_validator(state, card),
            Validator::Decree => decree_validator(card),
            Validator::PlayCondition => play_condition_validator(state, card),
            Validator::OneAttackPerTurn => one_attack_per_turn_validator(state, card),
            Validator::Unplayable => unplayable_validator(card),
        };
        verdict?;
    }
    Ok(())
}

/// #1 stun（Priority 100，`standard.stun_validator`）。
///
/// `Cards/CardPlayValidators.cs:58-75`：来源身上**有** `standard.stun` 这个定义 id 的实例即拒。
/// 只看 definition id，不看层数/时长（参考也没有）。**我验证过**这段 13 行源码。
fn stun_validator(state: &CombatState, card: &CardOnTable<'_>) -> Result<(), PlayError> {
    let source = source_of(state, &card.source)?;
    if has_status(source, STUN_STATUS) {
        return Err(PlayError::Refused(Refusal::Stunned));
    }
    Ok(())
}

/// `DecreeCardPlayValidator` 内部的**两条规则**（`CombatDecrees.cs:131-176`）。
///
/// ⚠️ **为什么这是一张单独的表，而不是往 [`VALIDATOR_ORDER`] 里加一行**：
/// 参考里这两条规则住在**同一个** `ICardPlayValidator` 里 —— `ModifierId` 都是
/// `standard.decree_validator`、`Priority` 都是 150（`CombatDecrees.cs:136-140`），
/// 而且 `StandardCombatPackage.cs:59-63` 注册的校验器**一共 5 个**。
/// 往那张按 `(priority, modifier_id)` 升序的表里插一条同 id 同优先级的记录，会让
/// "升序"这条排序语义变成空话，也会把"参考注册了 5 个校验器"说错。
///
/// 但"**占位不能少**"这条要求照办，而且落得更硬：
/// `DecreeRule` 的变体各自带行号锚点、各自的拒绝形态（`Refusal::DecreeMaxCardsPerTurn`
/// / `Refusal::DecreeNoLikeness`），[`decree_validator`] 里对它的 `match` 是**穷尽**的
/// —— 少一条编译期就红，运行期还有 `the_decree_validator_carries_both_rules…` 钉住
/// "两条都在表里、顺序照参考"。将来接法令时少写一条规则**不会**是"看不出来"的。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum DecreeRule {
    /// `CombatDecrees.cs:150-158`：`Ceiling(MaxCardsPerTurn)` 与
    /// `GetCardPlayTurnStats(source).CardsPlayedThisTurn` 比，`played >= cap` ⇒ 拒。
    MaxCardsPerTurn,
    /// `CombatDecrees.cs:160-174`：`InForce(NoLikenessInSuccession)` 的每条 spec 里，
    /// 若**本卡带 `tag`** 且**本回合上一张牌也带 `tag`** ⇒ 拒（消息里就带那个 `tag`）。
    NoLikenessInSuccession,
}

/// 两条规则的**执行序**（参考在同一个 `Validate` 里先 `Ceiling` 后 `InForce`）。
const DECREE_RULES: [DecreeRule; 2] = [
    DecreeRule::MaxCardsPerTurn,
    DecreeRule::NoLikenessInSuccession,
];

impl DecreeRule {
    /// 这条规则读哪两样东西（v1 两样都没有）。写成方法是为了让"接法令时要补什么"
    /// 出现在**一个**地方，而不是散在注释里。
    #[cfg(test)]
    const fn needs(self) -> (&'static str, &'static str) {
        match self {
            // ① 法令本身（`MaxCardsPerTurn` 的 ceiling）；② 这张回合统计表。
            DecreeRule::MaxCardsPerTurn => ("CombatRules", "CardPlayTurnStats"),
            // ① 法令本身（`NoLikenessInSuccession` 的 `LikenessTags`）；② 上一张牌是谁。
            DecreeRule::NoLikenessInSuccession => ("CombatRules", "CardPlayTurnStats"),
        }
    }
}

/// #2 decree（Priority 150，`standard.decree_validator`）。
///
/// 参考在这里读两条法令（`CombatDecrees.cs:150-158` 的 `MaxCardsPerTurn`、
/// `:160-174` 的 `NoLikenessInSuccession`），而两条都要求 `GetCardPlayTurnStats(...)`。
///
/// v1 **恒定放行**，理由不是"我忘了"：
/// * 内核**没有法令注册表**（`CombatState` 里没有 `CombatRules` 存储，镜像 23/23 `ABSENT`，§8.2 实测）；
/// * 也**没有** `CardPlayTurnStats`（`CardsPlayedThisTurn`/`LastCardPlayedDefinitionId`）。
///
/// 但"没有法令"这条前提是**被检查过**的：`refuse_if_any_decree` 在进入校验器链之前
/// 一票否决"内容里真的有法令"的场面。所以"法令被静默忽略"这条路是堵死的。
///
/// ⇒ [`Refusal::DecreeMaxCardsPerTurn`] 与 [`Refusal::DecreeNoLikeness`] 今天**都不可达**
/// （如实报告，不是遗漏；`the_decree_validator_carries_both_rules…` 把这句话钉成断言）。
fn decree_validator(card: &CardOnTable<'_>) -> Result<(), PlayError> {
    // 与参考同形的早退：动作（`IsAction`）不吃法令（`CombatDecrees.cs:144-145`）。
    if card.is_action {
        return Ok(());
    }
    // 走到这里时法令集合已被证明为空（见 `refuse_if_any_decree`）⇒ 两条规则都不成立。
    // 逐条过一遍不是为了"看起来像参考"，而是为了让"少一条"变成编译期错误。
    for rule in DECREE_RULES {
        run_decree_rule(card, rule)?;
    }
    Ok(())
}

/// 跑一条法令规则。**今天恒定放行**：两份输入（法令 + 回合统计）v1 都拿不到。
///
/// ⚠️ 这里**不许**改成"按 0 算"：`played`/`LastCardPlayedDefinitionId` 按 0 算等于
/// 把法令静默废掉，而两张表都不进哈希（§6.3）⇒ 对拍永远看不出来。
fn run_decree_rule(_card: &CardOnTable<'_>, rule: DecreeRule) -> Result<(), PlayError> {
    match rule {
        // ceiling 缺席（`refuse_if_any_decree` 保证）⇒ 这条规则整体不成立，连 `played` 都不用读。
        DecreeRule::MaxCardsPerTurn => Ok(()),
        // `InForce(...)` 空集 ⇒ 没有一条 spec，`LikenessTags` 一个都不用比。
        DecreeRule::NoLikenessInSuccession => Ok(()),
    }
}

/// #3 play_condition（Priority 150，`standard.play_condition_validator`）。
///
/// `Cards/CardPlayValidators.cs:39-56`：`PlayCondition` 为 null ⇒ 放行；否则**求值**，
/// false ⇒ 拒。求值上下文是出牌自己的 build context（来源 + 请求目标）。
///
/// ⚠️ **形状未验证（规格书 U2）**：镜像 62/62 的 `PlayCondition` 格都是 `ABSENT16`，
/// 一条实例都没有 ⇒ 这条分支在真实内容里**不可达**，它的形状是照"表达式格"的常识写的。
/// 接带"仅当…"型内容时必须先用 `tools/contentc/reader.py` 量一遍形状。
fn play_condition_validator(state: &CombatState, card: &CardOnTable<'_>) -> Result<(), PlayError> {
    let handle = card.row.play_condition();
    let term_id = match handle {
        ABSENT16 | NULL16 => return Ok(()),
        id => id,
    };
    let condition = NodeRef::new(card.content, term_id);
    let context = ExprContext {
        state,
        source: Some(card.source),
        event_target: card.target,
        iteration_target: None,
        iteration_card: None,
    };
    match expr::eval_bool(condition, &context) {
        Ok(true) => Ok(()),
        Ok(false) => Err(PlayError::Refused(Refusal::PlayConditionFalse)),
        Err(error) => Err(PlayError::Effect(exec::ExecError::Expr(error))),
    }
}

/// #4 one_attack_per_turn（Priority 200，`standard.one_attack_per_turn_validator`）。
///
/// `Cards/CardPlayTurnValidators.cs:3-29`：卡带 `attack` + 来源有该状态 +
/// **本回合已打过 ≥1 张 attack** ⇒ 拒。
///
/// 最后那一条要 `GetCardsPlayedWithTagThisTurn`，而内核**没有** `CardPlayTurnStats`
/// 这张表（`CombatState` 里不存在）。所以：
/// * 卡不带 `attack` / 来源没这个状态 ⇒ 正常放行（两个早退，参考同形）；
/// * 真走到第三个判据 ⇒ **响亮失败**。**不许**"按 0 算"——那等于把一条规则静默废掉，
///   而它**不进哈希**（§6.3），对拍永远看不出来。
///
/// ⇒ [`Refusal::OneAttackPerTurn`] 今天**不可达**（如实报告）。
fn one_attack_per_turn_validator(
    state: &CombatState,
    card: &CardOnTable<'_>,
) -> Result<(), PlayError> {
    if !card.is_attack {
        return Ok(());
    }
    let source = source_of(state, &card.source)?;
    if !has_status(source, ONE_ATTACK_PER_TURN_STATUS) {
        return Ok(());
    }
    Err(unsupported_content("CardPlayTurnStats"))
}

/// #5 unplayable（Priority 200，`standard.unplayable_validator`）。
///
/// `Cards/CardPlayValidators.cs:23-35`：卡带 `unplayable` 标签即拒。
/// 本内容 2 张（`red_tape` / `unsigned_form`，都是 0 费咒卡，§1.4 实测）。
fn unplayable_validator(card: &CardOnTable<'_>) -> Result<(), PlayError> {
    if card_has_tag(card.content, card.row, UNPLAYABLE_TAG)? {
        return Err(PlayError::Refused(Refusal::Unplayable));
    }
    Ok(())
}

// ===========================================================================
// 阶段 5：费用（`Cards/CardPlay.cs:436-544`）
// ===========================================================================

/// 六个费用修饰器的执行序（升序重排后，`Cards/CardPlay.cs:469-478` 的 `foreach`）。
///
/// 注册点：`StandardCombatPackage.cs:57`（declarative）、`:65-69`（其余 5 个）。
/// 每条后面的数字是它的 `Priority`。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CostStage {
    FreeNextCard,
    FirstAttackEachTurnFree,
    SkillCostReduction,
    DecreeNthCardFree,
    DeclarativePassive,
    CardInstance,
}

impl CostStage {
    /// 同 `Validator::priority`：只给顺序测试用。
    #[cfg(test)]
    const fn priority(self) -> i32 {
        match self {
            CostStage::FreeNextCard => 100,
            CostStage::FirstAttackEachTurnFree => 150,
            CostStage::SkillCostReduction => 200,
            CostStage::DecreeNthCardFree => 300,
            CostStage::DeclarativePassive => 1000,
            CostStage::CardInstance => 1100,
        }
    }

    #[cfg(test)]
    const fn modifier_id(self) -> &'static str {
        match self {
            CostStage::FreeNextCard => "standard.free_next_card_cost",
            CostStage::FirstAttackEachTurnFree => "standard.first_attack_each_turn_free_cost",
            CostStage::SkillCostReduction => "standard.skill_cost_reduction_cost",
            CostStage::DecreeNthCardFree => "standard.decree_free_nth_card",
            CostStage::DeclarativePassive => "standard.declarative_card_cost",
            CostStage::CardInstance => "standard.card_instance_cost",
        }
    }

    /// `PricesActions`（`Cards/CardCostModifiers.cs:29` 默认 false）。
    ///
    /// 只有 `DeclarativePassiveCostModifier` 声明 true（`Effects/PassiveModifiers.cs:278`），
    /// 而且它内部还再加 `onlyCardTagged: context.Card.IsAction`（`:288`）——
    /// 所以"动作只吃按标签命名的 spec"。`Cards/CardPlay.cs:471-472` 就是 `continue` 那一行。
    const fn prices_actions(self) -> bool {
        matches!(self, CostStage::DeclarativePassive)
    }
}

/// 执行序 = 升序后的固定表（`(priority, modifier_id)`）。
const COST_STAGE_ORDER: [CostStage; 6] = [
    CostStage::FreeNextCard,
    CostStage::FirstAttackEachTurnFree,
    CostStage::SkillCostReduction,
    CostStage::DecreeNthCardFree,
    CostStage::DeclarativePassive,
    CostStage::CardInstance,
];

/// 算最终费用，逐条照 `Cards/CardPlay.cs:436-512`。
///
/// 取整/夹紧规则（规格书 §3.4，**顺序敏感**）：
/// 1. 逐条目取 `cost.Amount`；`< 0` 立即拒（`:447-453`）；
/// 2. 逐 modifier 折叠，**每过一个就夹一次 `max(0, ·)`**（`:474`）—— 不是"最后夹一次"。
///    反例：printed 1 → (-99) → 0 → (+5) = 5，而"最后夹一次"给 0；
/// 3. 结果 `== 0` ⇒ **丢弃这个条目**（`:488-489`）；
/// 4. 同资源多条目 ⇒ 累加（`:491-492`，参考用 `checked`）；
/// 5. 法令 `MinimumCardCost` 兜底（`:501-507`）—— 已被法令闸门否决；
/// 6. 转成清单返回（`:509-511`）。
///
/// ⚠️ 参考的返回顺序来自 `Dictionary<ResourceId,int>` 的枚举序（U4 未验证）。
/// 本实现按**印刷条目的出现序**（同资源合并时保持首次出现的位次）—— 这是**有意偏离**：
/// 参考的顺序是 .NET 实现细节，而本内容每张卡最多 1 条费用，造不出区别。
fn calculate_costs(state: &CombatState, card: &CardOnTable<'_>) -> Result<PaidCosts, PlayError> {
    let content = card.content;
    let handle = card.row.costs();
    // `Costs` 是列表格（`F_TERM` → `_arr`）。哨兵 ⇒ 没有费用条目。
    // 本内容 62/62 都有这一格（47 张 1 条、15 张 0 条），所以哨兵分支今天不可达。
    let list_id = match handle {
        ABSENT16 | NULL16 => return Ok(PaidCosts::EMPTY),
        id => id,
    };
    let list = content.term(list_id).ok_or(IrError::Term(list_id))?;
    if list.op != OP_ARR {
        return Err(IrError::WrongKind("_arr").into());
    }
    let start = list.slot(0).ok_or(IrError::Slot)?;
    let count = list.slot(1).ok_or(IrError::Slot)?;
    if count == LIST_ABSENT || count == LIST_NULL {
        return Ok(PaidCosts::EMPTY);
    }

    // 同资源累加用的小表（参考是 `Dictionary<ResourceId,int>`）。
    let mut totals = [(ResourceId::EMPTY, 0i32); MAX_PAID_COSTS];
    let mut total_len = 0usize;

    for index in 0..count {
        let cell = start.checked_add(index).ok_or(IrError::List)?;
        let element_id = content.aux(cell).ok_or(IrError::List)?;
        let element = NodeRef::new(content, element_id);

        // `{"Amount": n, "ResourceId": {"value": "standard.energy"}}`
        // （实测：`Amount` 是 `F_INT`，`ResourceId` 是 `F_STR` + `FLAG_WRAP_LOWER`）。
        let amount = match element.field("Amount")? {
            Some(Value::Int(value)) => value,
            Some(Value::Absent | Value::Null) | None => {
                return Err(IrError::Missing("Amount").into());
            }
            Some(_) => return Err(IrError::WrongKind("F_INT").into()),
        };
        let resource = match element.field("ResourceId")? {
            Some(Value::Str(text)) => ResourceId::new(text)?,
            Some(Value::Absent | Value::Null) | None => {
                return Err(IrError::Missing("ResourceId").into());
            }
            Some(_) => return Err(IrError::WrongKind("F_STR").into()),
        };

        // 步骤 1（`:449-453`）：印刷费用是负数 ⇒ 抛（内容配错）。
        if amount < 0 {
            return Err(PlayError::NegativePrintedCost { resource });
        }

        // 步骤 2（`:469-478`）：逐 modifier 折叠，**每个之后夹一次**。
        let mut modified = amount;
        for stage in COST_STAGE_ORDER {
            // `:471-472`：动作不吃不声明 `PricesActions` 的 modifier。
            if card.is_action && !stage.prices_actions() {
                continue;
            }
            let after = run_cost_stage(state, card, stage, modified)?;
            modified = after.max(0);
        }

        // 步骤 3（`:488-489`）：归零 ⇒ 这个条目不进最终费用表。
        if modified == 0 {
            continue;
        }

        // 步骤 4（`:491-492`）：同资源累加（参考用 `checked`，溢出即抛）。
        let mut merged = false;
        for slot in &mut totals[..total_len] {
            if slot.0 == resource {
                slot.1 = slot.1.checked_add(modified).ok_or_else(cost_table_full)?;
                merged = true;
                break;
            }
        }
        if merged {
            continue;
        }
        if total_len == MAX_PAID_COSTS {
            return Err(cost_table_full());
        }
        totals[total_len] = (resource, modified);
        total_len += 1;
    }

    // 步骤 5（`:501-507`）法令 `MinimumCardCost` 兜底：法令闸门已否决，故无此步。

    // 步骤 6（`:509-511`）：转成清单。
    let mut paid = PaidCosts::EMPTY;
    for entry in &totals[..total_len] {
        if !paid.push(entry.0, entry.1) {
            return Err(cost_table_full());
        }
    }
    Ok(paid)
}

/// 一条费用过一个修饰器（`modifier.ModifyCostAmount(context, before)`）。
fn run_cost_stage(
    state: &CombatState,
    card: &CardOnTable<'_>,
    stage: CostStage,
    current: i32,
) -> Result<i32, PlayError> {
    match stage {
        // `Cards/FreeNextCardCostModifier.cs:11-27`：有 `standard.free_next_card` 且 `Charges > 0`
        // ⇒ 归 0。**我核对过**那段 17 行源码（含 `currentAmount <= 0` 的早退）。
        CostStage::FreeNextCard => {
            if current <= 0 {
                return Ok(current);
            }
            let source = source_of(state, &card.source)?;
            if has_status_with_charges(source, FREE_NEXT_CARD_STATUS) {
                return Ok(0);
            }
            Ok(current)
        }

        // `Cards/CardPlayTurnCostModifiers.cs:11-33`：卡带 attack + 来源有该状态 +
        // **本回合还没打过 attack** ⇒ 归 0。最后那条要回合统计表，内核没有 ⇒ 响亮失败。
        CostStage::FirstAttackEachTurnFree => {
            if current <= 0 || !card.is_attack {
                return Ok(current);
            }
            let source = source_of(state, &card.source)?;
            if !has_status(source, FIRST_ATTACK_FREE_STATUS) {
                return Ok(current);
            }
            Err(unsupported_content("CardPlayTurnStats"))
        }

        // `Cards/SkillCostReductionCostModifier.cs:11-29`：卡带 skill + 该状态层数和 ⇒ 减。
        // 本内容 `skill` 标签的卡 **0 张**（§3.7 实测）⇒ 这条今天永不生效，但它是活的。
        CostStage::SkillCostReduction => {
            if current <= 0 || !card.is_skill {
                return Ok(current);
            }
            let source = source_of(state, &card.source)?;
            let reduction = total_status_stacks(source, SKILL_COST_REDUCTION_STATUS);
            if reduction <= 0 {
                return Ok(current);
            }
            // 负值由 `:474` 的 `max(0, ·)` 兜住（除数/截断方向问题不存在）。
            Ok(current.wrapping_sub(reduction))
        }

        // `CombatDecrees.cs:181-203`：本回合第 `Amount` 张免费。法令闸门已否决 ⇒ 恒定原值。
        CostStage::DecreeNthCardFree => Ok(current),

        // `Effects/PassiveModifiers.cs:271-290`：折叠所有 `CardCost` 规格。
        CostStage::DeclarativePassive => declarative_cost(state, card, current),

        // `Cards/CardInstanceCostModifier.cs:13-34`：卡实例上的 `standard.card_cost_delta` 标记。
        CostStage::CardInstance => {
            let Some((_, slot)) = find_card_slot(state, &card.source, &card.instance) else {
                // 参考：实例不在区里 ⇒ 原值返回（不是错误）。
                return Ok(current);
            };
            let Some(instance) = state.card(slot) else {
                return Ok(current);
            };
            let delta = mark_counter(instance, CARD_COST_DELTA_COUNTER);
            if delta == 0 {
                return Ok(current);
            }
            Ok(current.max(0) + delta)
        }
    }
}

/// 声明式费用修饰器（`priority 1000`，`standard.declarative_card_cost`）。
///
/// 参考实现在这里 `GroupBy(DefinitionId)` 折叠来源身上所有 `CardCost` 管线的 spec
/// （`Effects/PassiveModifiers.cs:271-290`）。
///
/// # 本内容下它为什么是恒等，以及**为什么"恒等"不是猜的**
///
/// 1. 逐条把来源身上每个状态的 `PassiveModifiers` 交给 [`status_bind::decode`]。
///    镜像里能解出的 5 条 spec 全是 `DamageDealt`/`DamageReceived`/`TurnStartDraw`，
///    **0 条 `CardCost`**（§3.2 实跑）。所以候选表恒空。
/// 2. 一旦内容里真的出现 `"CardCost"`，`status_bind::Pipeline::from_wire_name` 会返回 `None`
///    （`status_bind.rs:134-140` 只认 3 个串）⇒ `BindError::Pipeline` ⇒ **这里响亮失败**。
///    **这是本模块最重要的一条闸门**：费用静默按印刷价结算，是这个项目里最难发现的错之一
///    （§8.3 原话："哈希对拍会通过"）。
/// 3. 折叠本身调的是**真的** [`modifiers::apply`]（`Pipeline::Cost`），带真账本
///    （`ClaimLedger`）—— 所以"管线接上了"不是一句注释：`status_bind` 长出 `Cost` 变体时，
///    这里唯一的改动是让候选表非空（编译器会在 [`cost_pipeline_of`] 的穷尽 `match` 上提醒你）。
fn declarative_cost(
    state: &CombatState,
    card: &CardOnTable<'_>,
    current: i32,
) -> Result<i32, PlayError> {
    // 先扫一遍"内容声明了什么"，**再**动折叠器 —— 顺序上先拒绝、后计算。
    let mut buffer = [NO_SPEC; status_bind::MAX_MODIFIERS];
    if let Ok(combatant) = source_of(state, &card.source) {
        for status in combatant.statuses() {
            match status_bind::decode(card.content, status.definition_id.as_str(), &mut buffer) {
                // 内容里没有这个状态定义 ⇒ 没有 spec（参考：未注册的定义没有修饰器）。
                Ok(None) => continue,
                Ok(Some(decoded)) => {
                    for spec in &buffer[..decoded.modifier_count] {
                        if cost_pipeline_of(spec.pipeline) == Some(ModifierPipeline::Cost) {
                            // 结构上不可达（`status_bind::Pipeline` 没有 `Cost` 变体）；
                            // 写出来是因为"`status_bind` 读不懂某条费用 spec"必须响亮，
                            // 绝不能落进下面的恒等折叠里。
                            return Err(unsupported_content("CardCost"));
                        }
                    }
                }
                // `BindError::Pipeline` 就是"内容声明了一条本层读不懂的管线"（含 `"CardCost"`）。
                Err(error) => return Err(PlayError::Effect(exec::ExecError::Bind(error))),
            }
        }
    }

    // 管线**接上了**：调的是真的折叠器（`Pipeline::Cost` 的消费者），带真账本。
    // 候选表恒空 —— 上面那道闸门保证了"能读到的 spec 里没有一条是 Cost 管线"。
    // `status_bind` 长出 `Cost` 变体时，要改的只有这一处：把通过的 spec 摊成 `Candidate`。
    let mut ledger = ClaimLedger::new();
    let mut candidates: [Candidate; 0] = [];
    let applied = modifiers::apply(current, &mut candidates, &[], &mut ledger, 0, &[]);
    Ok(applied.amount)
}

/// `status_bind::Pipeline` → 折叠器的 [`ModifierPipeline`]。
///
/// `None` = 这条 spec 不落在"被折叠成一个数量"的管线上。
///
/// ⚠️ 这个 `match` 是**编译期接缝**：`status_bind::Pipeline` 一旦长出 `Block`/`Cost`
/// （参考有 6 条管线，`Effects/PassiveModifiers.cs:16-30`），穷尽性检查会在这里报错，
/// 逼着接的人想清楚那条管线在本模块里归哪一步。
const fn cost_pipeline_of(pipeline: status_bind::Pipeline) -> Option<ModifierPipeline> {
    match pipeline {
        status_bind::Pipeline::DamageDealt => Some(ModifierPipeline::DamageDealt),
        status_bind::Pipeline::DamageReceived => Some(ModifierPipeline::DamageReceived),
        // ⚠️ 本轮被这条接缝逼着加的（`status_bind` 长出 `Block`，走格挡管线的那条路在
        // `exec::block_stage` 里）。这里给 `Some(Block)` 是**如实回答**："它落在哪条管线上"；
        // 本函数的**唯一调用方**（`declarative_cost` 上面那个 `== Some(Cost)` 的判定）因此
        // 与从前一字不差 —— 一条 `BlockGain` spec 仍然不会被误当成费用 spec。
        status_bind::Pipeline::Block => Some(ModifierPipeline::Block),
        status_bind::Pipeline::TurnStartDraw => None,
    }
}

/// 付得起校验（`Cards/CardPlay.cs:514-533`），**在付款之前**（`:125` 早于 `:126`）。
///
/// 两条顺序固定的判据：资源池不存在 ⇒ `MissingResource`；不够 ⇒ `Unaffordable`。
/// 整个循环跑完才轮到付款，所以"付了一半发现第二条不够"永远不可能发生。
fn ensure_affordable(
    state: &CombatState,
    source: &CombatantId,
    paid: &PaidCosts,
) -> Result<(), PlayError> {
    let combatant = source_of(state, source)?;
    for index in 0..paid.len() {
        let Some(cost) = paid.get(index) else {
            continue;
        };
        // 顺序照抄 `:521-525` 然后 `:527-531`。
        let pool = pool_of(combatant, &cost.resource)
            .ok_or(PlayError::MissingResource {
                resource: cost.resource,
            })?;
        if pool.current < cost.amount {
            return Err(PlayError::Unaffordable {
                need: cost.amount,
                have: pool.current,
                resource: cost.resource,
            });
        }
    }
    Ok(())
}

/// 付钱（`Cards/CardPlay.cs:535-544`）：`resource.SetCurrent(resource.Current - amount)`。
///
/// **不退、不夹紧**：付完有剩就留着，付完正好 0 也是 0（超额支付在这里不成立，
/// 因为 `ensure_affordable` 已经保证了够）。
fn pay_costs(
    state: &mut CombatState,
    source: &CombatantId,
    paid: &PaidCosts,
) -> Result<(), PlayError> {
    for index in 0..paid.len() {
        let Some(cost) = paid.get(index) else {
            continue;
        };
        let (current, max) = {
            let combatant = source_of(state, source)?;
            let pool = pool_of(combatant, &cost.resource).ok_or(PlayError::MissingResource {
                resource: cost.resource,
            })?;
            (pool.current, pool.max)
        };
        let combatant = state
            .combatant_mut(source)
            .ok_or(PlayError::SourceUnavailable)?;
        combatant.set_resource(cost.resource, current - cost.amount, max)?;
    }
    Ok(())
}

// ===========================================================================
// 落区（`Cards/CardPlay.cs:240-302`）
// ===========================================================================

/// 卡的落点。
///
/// 参考（`:298-302`）：法令 `PlayedCardsExhaust` ⇒ `ExhaustPile`，否则卡定义的
/// `PlayedCardDestinationZone`（构造默认 `DiscardPile`，`Cards/CardDefinitions.cs:106`）。
/// 法令那一半由 `refuse_if_any_decree` 否决，剩下这一半是**读卡定义**的 ——
/// 本内容实测 `DiscardPile` 48 / `ExhaustPile` 14（§5.3）。
fn played_card_destination(card: &CardOnTable<'_>) -> Result<CardZone, PlayError> {
    let handle = card.row.played_card_destination_zone();
    if handle == ABSENT16 || handle == NULL16 {
        return Ok(CardZone::DiscardPile);
    }
    let name = card
        .content
        .string(handle)
        .ok_or(IrError::Missing("PlayedCardDestinationZone"))?;
    // 不认识的**枚举名**归 `IrError::UnknownKind`（"判别串不认识"），与 `exec.rs:1293`
    // 对 `ToZone` 的处理逐字同形。⚠️ 这**不是** [`PlayError::UnsupportedContent`]：
    // 那说的是"内核缺能力"，而这里内核有全部 7 个区，是内容写了一个第 8 个名字。
    zone_from_wire_name(name).ok_or_else(|| IrError::UnknownKind.into())
}

/// C# 的 `CardZone` 枚举名 → 内核的 [`CardZone`]（`Cards/CardZones.cs:3-22`）。
///
/// 镜像里这一格存的是**枚举名原文**（实测 `"DiscardPile"` / `"ExhaustPile"`，裸串、flags 0）。
/// ⚠️ 不能用 [`CardZone::wire_name`] 反查：那是**哈希的**短名（`disc`/`exh`），两套词。
///
/// 与 `exec.rs:1901-1912` 的同名函数重复（那边是私有的）—— 理由同 [`card_has_tag`]。
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

/// 终态把卡搬到落点（`Cards/CardPlay.cs:242-263`），返回卡**最终**所在的区。
///
/// 前置守卫（`:244-247`）：卡必须还在**手牌**里，否则**直接返回、不搬** ——
/// 这条让"程序自己把卡挪走了"的卡不被二次搬动（`T:CardPlayCompletionBoundaryTests.cs:90-121`）。
/// 这种情况下 `landed` 如实报卡现在所在的区。
///
/// 搬不动（目的区满）⇒ [`PlayError::Capacity`]。**不静默留在手牌**：那是"打出去了但没落地"，
/// 一张牌就此消失。
/// 落区（`Cards/CardPlay.cs:242-263` 的 `onTerminal`）。
///
/// `moved` 不是"卡最终在哪"，而是"参考那次入队**会不会发生**"：`onTerminal` 一进来就守着
///
/// ```text
/// var zones = c.GetCardZones(capturedPlayerId);
/// if (!zones.ContainsCard(capturedCardId) ||
///     zones.GetCard(capturedCardId).Zone != CardZone.Hand)
///     return;
/// ```
///
/// （`Cards/CardPlay.cs:245-247`）⇒ 卡被**它自己的节目**挪出手牌之后（`archive_the_evidence` /
/// `shredder_drawer` 的 `forEachCardInZone → moveCardToZone` 就是干这个），那次
/// `EnqueueEffect(MoveCardToZoneEffectRequest)`（`:251-252`）根本不发生，**链号也不发**。
/// 内核无条件发号会让 `chain_num` 比参考多 1 —— 2026-10-19 的逐卡对拍实测到的就是这个。
fn settle_card(
    state: &mut CombatState,
    plan: &PlayPlan<'_>,
) -> Result<Settled, PlayError> {
    let Some((zone, slot)) = find_card_slot(state, &plan.source, &plan.instance) else {
        return Ok(Settled {
            landed: None,
            moved: false,
        });
    };
    if zone != CardZone::Hand {
        return Ok(Settled { landed: Some(zone), moved: false });
    }
    state.move_card(
        &plan.source,
        CardZone::Hand,
        plan.destination,
        slot,
        ZonePlacement::Bottom,
    )?;
    Ok(Settled { landed: Some(plan.destination), moved: true })
}

/// [`settle_card`] 的结果：卡落在哪，以及那次搬区入队**会不会真的发生**。
struct Settled {
    landed: Option<CardZone>,
    moved: bool,
}

// ===========================================================================
// 节目与法令闸门
// ===========================================================================

/// 卡的 on-play 节目根 + 步数预算。
///
/// * 没有 `Program` 格 ⇒ `(None, 0)`：参考走 5.12 分支（`Cards/CardPlay.cs:283-293`），
///   **本内容 62/62 都有节目**，所以这条今天不可达（但它不是错误，别拒绝它）。
/// * 有 `Program` 但 `Root` 缺席/悬空 ⇒ 响亮失败（镜像坏了）。
fn card_program<'a>(card: &CardOnTable<'a>) -> Result<(Option<NodeRef<'a>>, u32), PlayError> {
    let ir = Ir::new(card.content);
    let index = card.row.index();
    let root = match ir.card_program_root(index) {
        Ok(root) => root,
        Err(IrError::Missing("Program")) => return Ok((None, 0)),
        Err(error) => return Err(error.into()),
    };

    // `MaxProgramSteps` 在信封上（`_obj(Id,MaxNodeDepth,MaxProgramSteps,Root)`）。
    let envelope = NodeRef::new(card.content, card.row.program());
    let steps = match envelope.field("MaxProgramSteps")? {
        Some(Value::Int(value)) if value > 0 => value as u32,
        // 参考的构造函数要求 `> 0`（`EffectProgramContracts.cs:560-563`），默认 1024。
        _ => DEFAULT_MAX_PROGRAM_STEPS,
    };
    Ok((Some(root), steps))
}

/// 法令闸门：本内容 23/23 `CombatRules` 全是 `ABSENT16`（§8.2 实测），所以 v1 的
/// "永远没有法令"与参考**逐位一致**。**但只在"真的没有"时才一致**。
///
/// 出牌路径上有 **5 个法令读点**（§8.1），本模块一个都没实现：
/// 1. `DecreeCardPlayValidator` 的 `MaxCardsPerTurn`（`CombatDecrees.cs:150-158`）；
/// 2. 同一个校验器的 `NoLikenessInSuccession`（`:160-174`）；
/// 3. `DecreeCardCostModifier` 的 `NthCardOfTurnIsFree`（`:181-203`）；
/// 4. `CalculateCosts` 末尾的 `MinimumCardCost` 兜底（`Cards/CardPlay.cs:501-507`）；
/// 5. `PlayedCardDestination` 的 `PlayedCardsExhaust`（`:298-302`）。
///
/// 所以这里做**一次**一票否决：只要出牌者身上任何一个状态声明了 `CombatRules`，
/// 这次出牌就**响亮失败**，而不是按"没有法令"照算（§8.3 说的正是这种静默错）。
///
/// ⇒ 接法令时该做的是**补这一个函数 + 那 5 个读点**，不是改流水线。
fn refuse_if_any_decree(state: &CombatState, card: &CardOnTable<'_>) -> Result<(), PlayError> {
    let Ok(combatant) = source_of(state, &card.source) else {
        return Ok(());
    };
    for status in combatant.statuses() {
        let Some(row) = status_bind::status_row(card.content, status.definition_id.as_str()) else {
            // 内容里没有这个状态定义 ⇒ 它当然也没有法令。
            continue;
        };
        let handle = row.combat_rules();
        if handle != ABSENT16 && handle != NULL16 {
            return Err(unsupported_content("CombatRules"));
        }
    }
    Ok(())
}

// ===========================================================================
// 小工具
// ===========================================================================

/// 来源战斗员（缺人 ⇒ `SourceUnavailable`，与阶段 2 同一个答案）。
fn source_of<'s>(state: &'s CombatState, id: &CombatantId) -> Result<&'s Combatant, PlayError> {
    state.combatant(id).ok_or(PlayError::SourceUnavailable)
}

/// 状态在不在（只比 definition id，比的是**字节**）。
fn has_status(combatant: &Combatant, definition: &str) -> bool {
    combatant
        .statuses()
        .iter()
        .any(|status| status.definition_id.as_str() == definition)
}

/// 有没有一条 `charges > 0` 的该状态（`FreeNextCardCostModifier` 读的是 `Charges`）。
fn has_status_with_charges(combatant: &Combatant, definition: &str) -> bool {
    combatant
        .statuses()
        .iter()
        .any(|status| status.definition_id.as_str() == definition && status.charges > 0)
}

/// 该状态的层数和（`SkillCostReductionCostModifier` 用 `.Sum(stacks)`）。
fn total_status_stacks(combatant: &Combatant, definition: &str) -> i32 {
    let mut total = 0i32;
    for status in combatant.statuses() {
        if status.definition_id.as_str() == definition {
            total = total.saturating_add(status.stacks);
        }
    }
    total
}

/// 某条资源池（缺席 ⇒ `None`）。
fn pool_of(combatant: &Combatant, key: &ResourceId) -> Option<Pool> {
    combatant
        .resources()
        .iter()
        .find(|pool| pool.key == *key)
        .map(|pool| pool.pool)
}

/// 卡实例上的命名标记计数器读数（缺席 ⇒ 0，`Cards/CardZones.cs` 的 `GetMarkCounter`）。
fn mark_counter(instance: &crate::state::CardInstance, key: &str) -> i32 {
    for counter in instance.mark_counters() {
        if counter.key.as_str() == key {
            return counter.value;
        }
    }
    0
}

/// **内核缺能力**（不是内容缺字段）：内容真的用到了 v1 没实现的那条路。
///
/// 与"镜像读不出来"严格分工：那条走 [`PlayError::Effect`]`(ExecError::Ir(..))`
/// （`Missing`/`WrongKind`/`Term`…），意思是**内容配错了**；本函数意思是**我们还没写**。
/// 混在一起会让排查方向整整错一天（冻结方 2026-10-17 的裁决）。
fn unsupported_content(what: &'static str) -> PlayError {
    PlayError::UnsupportedContent(what)
}

/// 费用表装不下（> [`MAX_PAID_COSTS`] 条不同资源）。
///
/// ⚠️ **借用** `Container::Resources`：`Container` 里没有"费用表"这一格。
/// 冻结方 2026-10-17 裁决**先不动** `state.rs` 的枚举（加一格会牵动所有穷尽 `match`，
/// 收益不值），所以这里是**有意的借用**，不是"费用表就是资源池"。
/// **绝不截断** —— 少扣一条资源比拒绝出牌糟得多（`state.rs:186` 的同一条理由）。
fn cost_table_full() -> PlayError {
    PlayError::Capacity(CapacityError::Full(Container::Resources))
}

/// 声明式费用候选表的空槽（`Candidate` 没有 `Default`）。
const NO_SPEC: status_bind::PassiveModifier = status_bind::PassiveModifier {
    pipeline: status_bind::Pipeline::DamageDealt,
    operation: status_bind::ModifierOp::AddFlat,
    magnitude: 0,
    priority: 0,
    restrict_damage_kind: None,
};

// ===========================================================================
// 测试
// ===========================================================================
//
// 纪律：**接真实内容镜像**，不手搓假卡。凡是"我期望这个数"的断言，注释里写清依据是
// 规格书哪一节 / 哪一行，或者"我用 reader.py 在 core 镜像上量出来的"。
#[cfg(test)]
mod tests {
    use super::*;
    use crate::content::{Table, S_TRM, S_TRW};
    use crate::state::{
        CardDefinitionId, CardInstance, CombatId, CombatantDefinitionId, StatusDefinitionId,
        StatusInstance, StatusInstanceId, StatusPolarity, TeamId,
    };
    use crate::writer;

    /// 与 `exec.rs` 的测试用同一条相对路径（`CARGO_MANIFEST_DIR` 是 `kernel/rd-core`）。
    const CORE_IMAGE_REL: &str = "../../tools/contentc/out/content.core.rdcf";

    fn core_image() -> Vec<u8> {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(CORE_IMAGE_REL);
        std::fs::read(&path).unwrap_or_else(|e| {
            panic!(
                "RDCF 镜像缺失或读不到：{}\n  {e}\n  \
                 它是 tools/contentc 的构建产物，生成命令：\n    \
                 python tools/contentc/compile.py",
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
    fn rid(s: &str) -> ResourceId {
        ResourceId::new(s).unwrap()
    }
    fn energy() -> ResourceId {
        rid("standard.energy")
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

    /// hero 70/70 + 3 点能量；两个敌人在 `enemy` 队（`sel.allEnemies` 可测）。
    fn arena() -> CombatState {
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state.add_combatant(unit("hero", "player", 70, 70)).unwrap();
        state.add_combatant(unit("enemy_a", "enemy", 20, 20)).unwrap();
        state
            .add_combatant(unit("enemy_b", "enemy", 10, 10))
            .unwrap();
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .set_resource(energy(), 3, Some(3))
            .unwrap();
        state
    }

    fn give_card(state: &mut CombatState, who: &str, zone: CardZone, instance: &str, definition: &str) {
        let card = CardInstance::new(
            CardInstanceId::new(instance).unwrap(),
            CardDefinitionId::new(definition).unwrap(),
        );
        state.push_card(&cid(who), zone, card).unwrap();
    }

    fn give_status(state: &mut CombatState, who: &str, definition: &str) {
        let status = StatusInstance::new(
            StatusInstanceId::new("status_1").unwrap(),
            StatusDefinitionId::new(definition).unwrap(),
            StatusPolarity::Debuff,
        );
        state
            .combatant_mut(&cid(who))
            .unwrap()
            .push_status(status)
            .unwrap();
    }

    fn energy_of(state: &CombatState, who: &str) -> i32 {
        pool_of(state.combatant(&cid(who)).unwrap(), &energy())
            .expect("能量池")
            .current
    }

    fn health_of(state: &CombatState, who: &str) -> i32 {
        state.combatant(&cid(who)).unwrap().health_current
    }

    fn zone_of(state: &CombatState, who: &str, instance: &str) -> Option<CardZone> {
        find_card_slot(
            state,
            &cid(who),
            &CardInstanceId::new(instance).unwrap(),
        )
        .map(|(zone, _)| zone)
    }

    /// 指纹里去掉 `chain_num=` / `exec_num=` 两行之后的其余字节。
    ///
    /// 用来断言"除了发号器，状态逐字节不变"：这种断言比"整段文本相等"弱一点，但比"字段逐个比"
    /// 强得多（它仍然覆盖牌区顺序、状态顺序、计数器、临时规则……）。发号器必须**单独**断言
    /// （数字要精确到 +1 / +2），否则这一层就成了"什么都能过"的橡皮图章。
    fn strip_generator_lines(text: &[u8]) -> Vec<u8> {
        let text = std::str::from_utf8(text).expect("指纹一定是 UTF-8");
        let mut out = String::new();
        for line in text.lines() {
            if line.starts_with("chain_num=") || line.starts_with("exec_num=") {
                continue;
            }
            out.push_str(line);
            out.push('\n');
        }
        out.into_bytes()
    }

    /// 逐字节指纹：`snapshot::write_hash_input` 写出来的就是哈希的输入文本
    /// （含 7 个牌区的**堆内顺序**、`exec_num=`/`chain_num=` 两个发号器）。
    fn state_text(state: &CombatState) -> Vec<u8> {
        let mut buffer = [0u8; 1 << 16];
        let mut w = writer::TextWriter::new(&mut buffer);
        crate::snapshot::write_hash_input(&mut w, state);
        assert!(!w.overflowed(), "指纹缓冲装不下（本状态太大了，调大缓冲）");
        w.as_str().as_bytes().to_vec()
    }

    fn request(instance: &str, target: Option<&str>) -> PlayRequest {
        PlayRequest::new(
            cid("hero"),
            CardInstanceId::new(instance).unwrap(),
            target.map(cid),
        )
    }

    /// CARD 行号 → 定义 id（借用镜像是 `'a`）。
    fn definition_at<'a>(content: &'a Content<'a>, index: u32) -> &'a str {
        content.entity_id(Table::Card, index).expect("CARD 行必须有 Id")
    }

    // ------------------------------------------------------------- 镜像补丁

    /// 一个 term 某字段**首槽**在 blob 里的字节偏移（与 `ir::NodeRef::field_spec` 同一套映射；
    /// 抄自 `exec.rs` 的测试脚手架）。
    fn field_slot_offset(content: &Content<'_>, tid: u16, key: &str) -> usize {
        let trw = content.section(S_TRW).expect("TRW 段");
        let word = usize::from(trw.u16_at(usize::from(tid)).expect("TRW 项越界"));
        let trm = content.section(S_TRM).expect("TRM 段");
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

    /// 定长表第 `index` 行第 `cell` 格在 blob 里的字节偏移。
    fn row_cell_offset(content: &Content<'_>, table: Table, index: u32, cell: usize) -> usize {
        let section = content.section(table.section_id()).expect("表段存在");
        section.offset as usize + index as usize * table.stride() as usize + cell * 2
    }

    fn patch16(blob: &mut [u8], at: usize, value: u16) {
        let slot = blob
            .get_mut(at..at + 2)
            .unwrap_or_else(|| panic!("patch16 越界：{at}"));
        slot.copy_from_slice(&value.to_le_bytes());
    }

    /// 遍历所有 term，挑出判别串等于 `kind` 且 `Value` 字段等于 `wanted` 的 `const`。
    fn const_term_with_value(content: &Content<'_>, wanted: i32) -> Option<u16> {
        for tid in 0..content.term_count() {
            let Ok(tid) = u16::try_from(tid) else { continue };
            let node = NodeRef::new(content, tid);
            if node.kind_str() != Ok("const") {
                continue;
            }
            if let Ok(Some(Value::Int(value))) = node.field("Value") {
                if value == wanted {
                    return Some(tid);
                }
            }
        }
        None
    }

    /// 一个空的 `_arr` term（term 58 是"空费用列表"那个共享项，但我不硬编码 id）。
    fn empty_array_term(content: &Content<'_>) -> u16 {
        for tid in 0..content.term_count() {
            let Ok(tid) = u16::try_from(tid) else { continue };
            let Some(term) = content.term(tid) else { continue };
            if term.op != OP_ARR {
                continue;
            }
            if term.slot(1) == Some(0) {
                return tid;
            }
        }
        panic!("镜像里没有空的 `_arr` term");
    }

    fn card_cell_index(content: &Content<'_>, index: u32, key: &str) -> usize {
        content
            .card(index)
            .expect("CARD 行")
            .row()
            .cell_index(key)
            .unwrap_or_else(|| panic!("CARD 没有 {key} 格"))
    }

    fn status_row_of<'a>(content: &'a Content<'a>, definition: &str) -> crate::content::StatusRow<'a> {
        content
            .lookup_in(definition, crate::content::EK_STATUS)
            .and_then(|entry| content.status(u32::from(entry.index)))
            .unwrap_or_else(|| panic!("STAT 表里没有 {definition}"))
    }

    /// 把某张牌 `CARD[0]`（`paper_cut`）的 `dealDamage.Amount` 指到镜像里真实存在的
    /// `const{-1}` 上 —— 于是节目在**执行期** fault（`resolve_damage` 的负数闸门，
    /// `DamageEffects.cs:50-51` / `exec.rs:518-520`），而**不是**在预检里被拒。
    ///
    /// 选"运行期 fault"而不是"预检拒绝"是有意的：参考在预检拒绝时终态回调**还没装上**，
    /// 卡会留在手牌（`EffectProgramExecution.cs:23` 早于 `:36` 的 `ConfigureTerminalCleanup`）；
    /// 而在执行期 fault 时卡**已经**落到落点（§5.2）。本模块无法区分这两条（见模块头 D4），
    /// 所以测试钉的是**可达**的那一条。
    fn image_with_negative_paper_cut_amount() -> Vec<u8> {
        let pristine = core_image();
        let content = parse(&pristine);
        let root = Ir::new(&content)
            .card_program_root(0)
            .expect("CARD[0] 的节目根");
        let negative = const_term_with_value(&content, -1).expect("镜像里有 `const{-1}`");
        let at = field_slot_offset(&content, root.id(), "Amount");
        let mut blob = pristine;
        patch16(&mut blob, at, negative);
        blob
    }

    // ------------------------------------------------------------- 1. 真打一张牌

    #[test]
    fn a_real_deal_damage_card_is_paid_resolved_and_discarded() {
        // CARD[0] = `paper_cut`：印刷 1 能量、`node.dealDamage` 打 `sel.eventTarget` 6 点、
        // 落点 `DiscardPile`（`reader.py --entity CARD 0` 实测）。
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        assert_eq!(energy_of(&state, "hero"), 3);
        assert_eq!(health_of(&state, "enemy_a"), 20);

        let report = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("paper_cut 必须打得出去");

        assert!(report.played, "WasPlayed");
        assert_eq!(report.paid.len(), 1, "一条印刷费用");
        assert_eq!(report.paid.amount_for(&energy()), Some(1));
        assert_eq!(energy_of(&state, "hero"), 2, "付了 1 点（:535-544）");
        assert_eq!(health_of(&state, "enemy_a"), 14, "6 点伤害真的落地");
        assert_eq!(health_of(&state, "enemy_b"), 10, "别的人不许掉血");
        assert_eq!(report.landed, Some(CardZone::DiscardPile));
        assert_eq!(
            zone_of(&state, "hero", "card_h1"),
            Some(CardZone::DiscardPile),
            "§5.2 Completed：卡搬到 PlayedCardDestinationZone"
        );
        assert!(report.counted_as_card_played, "// IsAction 缺席 ⇒ 算作打出");
    }

    // ------------------------------------------------------------- 2. 落区读卡定义

    #[test]
    fn every_card_whose_definition_says_exhaust_lands_in_the_exhaust_pile() {
        // §5.3【实跑】：镜像里 `DiscardPile` 48 张 / `ExhaustPile` 14 张。
        // 这条测试把**全部 14 张**都打一遍 —— 它是"落区不是硬编码弃牌堆"的封条。
        let blob = core_image();
        let content = parse(&blob);

        let mut exhaust = 0usize;
        let mut index = 0u32;
        while content.card(index).is_some() {
            let name = definition_at(&content, index);
            let row = content.card(index).unwrap();
            let destination = content
                .string(row.played_card_destination_zone())
                .unwrap_or("");
            if destination != "ExhaustPile" {
                index += 1;
                continue;
            }

            let mut state = arena();
            give_card(&mut state, "hero", CardZone::Hand, "card_h1", name);
            let report = play_card(
                &mut state,
                Some(&content),
                &request("card_h1", Some("enemy_a")),
            )
            .unwrap_or_else(|e| panic!("{name}（CARD[{index}]）应当打得出去：{e:?}"));
            assert_eq!(
                report.landed,
                Some(CardZone::ExhaustPile),
                "{name} 的 `PlayedCardDestinationZone` 是 ExhaustPile"
            );
            assert_eq!(
                zone_of(&state, "hero", "card_h1"),
                Some(CardZone::ExhaustPile),
                "{name}"
            );
            exhaust += 1;
            index += 1;
        }

        assert_eq!(index, 62, "CARD 表 62 行（§1.4 实测）");
        assert_eq!(exhaust, 14, "§5.3 实测：14 张落在消耗堆");
    }

    // ------------------------------------------------------------- 3. 0 费卡

    #[test]
    fn a_zero_cost_card_pays_nothing() {
        // `temporary_authorization`（CARD[26]）：`Costs == []`（15 张里的一张，§3.1 实测）、
        // 落点 ExhaustPile、节目 `gainBlock 4` 打 `sel.source`。
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        give_card(
            &mut state,
            "hero",
            CardZone::Hand,
            "card_h1",
            "temporary_authorization",
        );

        let report = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("0 费卡必须打得出去（§3.5：无费用条目 ⇒ 必然付得起）");

        assert!(report.played);
        assert!(
            report.paid.is_empty(),
            "0 费 ⇒ 费用表为空（`:488-489` 把 0 值条目丢掉，这里根本没有条目）"
        );
        assert_eq!(energy_of(&state, "hero"), 3, "一滴能量都不该扣");
        assert_eq!(report.landed, Some(CardZone::ExhaustPile));
    }

    // ------------------------------------------------------------- 4. 付不起

    #[test]
    fn an_unaffordable_card_is_refused_and_the_state_is_byte_identical() {
        // `permit_a38`（CARD[6]）：印刷 2 能量（9 张 2 费卡之一，`reader.py` 实测）。
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .set_resource(energy(), 1, Some(3))
            .unwrap();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "permit_a38");
        let before = state_text(&state);

        let error = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .unwrap_err();

        // `need`/`have` 两个数都要对（`:527-531`：`resource.Current < cost.Amount`）。
        assert_eq!(
            error,
            PlayError::Unaffordable {
                need: 2,
                have: 1,
                resource: energy()
            }
        );
        assert_eq!(state_text(&state), before, "拒绝路径必须**逐字节**不变");
        assert_eq!(zone_of(&state, "hero", "card_h1"), Some(CardZone::Hand));
        assert_eq!(energy_of(&state, "hero"), 1);
    }

    // ------------------------------------------------------------- 5. 卡不在手牌

    #[test]
    fn a_card_outside_the_hand_is_refused() {
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        give_card(
            &mut state,
            "hero",
            CardZone::DrawPile,
            "card_h1",
            "paper_cut",
        );
        let error = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .unwrap_err();
        // `Cards/CardPlay.cs:54-58`：在别的区 ⇒ 抛。
        assert_eq!(error, PlayError::CardNotInHand);

        // 实例根本不存在也是同一条（`Cards/CardZones.cs:192-200`）。
        let error = play_card(
            &mut state,
            Some(&content),
            &request("card_nope", Some("enemy_a")),
        )
        .unwrap_err();
        assert_eq!(error, PlayError::CardNotInHand);
    }

    // ------------------------------------------------------------- 6. 来源已倒下

    #[test]
    fn a_downed_source_cannot_play() {
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .lifecycle_state = CombatantLifecycleState::Downed;
        let before = state_text(&state);

        // `IsAlive => LifecycleState == Alive`（`CombatantState.cs:79`），`!IsAlive` ⇒ 抛（`:88-94`）。
        let error = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .unwrap_err();
        assert_eq!(error, PlayError::SourceUnavailable);
        assert_eq!(state_text(&state), before);

        // 人根本不在场也是同一条。
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .lifecycle_state = CombatantLifecycleState::Alive;
        let ghost = PlayRequest::new(
            cid("nobody"),
            CardInstanceId::new("card_h1").unwrap(),
            Some(cid("enemy_a")),
        );
        assert_eq!(
            play_card(&mut state, Some(&content), &ghost).unwrap_err(),
            PlayError::SourceUnavailable
        );
    }

    // ------------------------------------------------------------- 7. 战斗已结束

    #[test]
    fn a_finished_combat_refuses_and_changes_nothing() {
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        state.result = CombatResult::Victory;
        let before = state_text(&state);

        // `Cards/CardPlay.cs:82-86`：`Result != Ongoing` ⇒ 抛。
        let error = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .unwrap_err();
        assert_eq!(error, PlayError::NotOngoing);
        assert_eq!(state_text(&state), before);
    }

    // ------------------------------------------------------------- 8. dry-run 封条

    #[test]
    fn can_play_card_changes_nothing_and_answers_exactly_what_play_card_does() {
        // 三个场面：能打 / 付不起 / 咒卡不可打。对每个都断言
        //   (a) `can_play_card` 前后指纹**一字不差**；
        //   (b) 它的答案与随后 `play_card` 的答案**完全一致**（纪律 2 的封条）。
        let scenarios: [(&str, i32, &str); 3] = [
            ("paper_cut", 3, "paper_cut"),              // 能打
            ("permit_a38", 1, "permit_a38"),            // 2 费、只有 1 能量 ⇒ 付不起
            ("red_tape", 3, "red_tape"),                // unplayable 咒卡
        ];
        for (instance, available, definition) in scenarios {
            let blob = core_image();
            let content = parse(&blob);
            let mut state = arena();
            state
                .combatant_mut(&cid("hero"))
                .unwrap()
                .set_resource(energy(), available, Some(3))
                .unwrap();
            give_card(&mut state, "hero", CardZone::Hand, instance, definition);
            let request = request(instance, Some("enemy_a"));

            let before = state_text(&state);
            let dry = can_play_card(&state, Some(&content), &request);
            assert_eq!(
                state_text(&state),
                before,
                "{instance}：dry-run 不许动状态（连 exec_num/chain_num 都不许动）"
            );

            let real = play_card(&mut state, Some(&content), &request);
            match (&dry, &real) {
                (Ok(()), Ok(report)) => assert!(report.played, "{instance}"),
                (Err(dry_error), Err(real_error)) => {
                    assert_eq!(dry_error, real_error, "{instance}：两条路径必须给同一个答案")
                }
                _ => panic!("{instance}：dry-run 说 {dry:?}，真打说 {real:?} —— 这就是\"界面说能打、真打被拒\""),
            }
        }
    }

    // ------------------------------------------------------------- 9. Faulted 仍然落区

    #[test]
    fn a_faulted_program_still_lands_the_card() {
        // 把 `paper_cut` 的伤害金额指到 `const{-1}` ⇒ 执行期 fault（负金额，`DamageEffects.cs:50-51`）。
        // 规格书 §5.2 表格 + `Cards/CardPlay.cs:254-261`：**Faulted ⇒ 仍然搬**，而且是**直接搬**
        // （绕开效果队列，所以不 fire `CardMovedToZone` 事件）。
        let blob = image_with_negative_paper_cut_amount();
        let content = parse(&blob);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");

        let error = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .unwrap_err();

        assert_eq!(
            error,
            PlayError::Effect(exec::ExecError::Modifier),
            "负数伤害金额让整个节目 fault（映射见 exec.rs:253-259）"
        );
        assert_eq!(
            zone_of(&state, "hero", "card_h1"),
            Some(CardZone::DiscardPile),
            "§5.2：faulted 的节目不许把牌留在手牌里"
        );
        assert_eq!(
            energy_of(&state, "hero"),
            2,
            "费用**已经付过**（付款 `:123-126` 早于跑节目 `:221`）"
        );
        assert_eq!(health_of(&state, "enemy_a"), 20, "负数伤害一滴血都没打掉");
    }

    // ------------------------------------------------------------- 10. 校验器顺序

    #[test]
    fn an_unplayable_card_is_refused_after_stun_because_of_the_real_validator_order() {
        // 规格书 §2.3：参考实现的注释（"unplayable 优先级最高、会短路"）与它自己的实现**相反** ——
        // 排序是**升序**，所以 stun(100) 先跑、unplayable(200) 最后跑。
        let blob = core_image();
        let content = parse(&blob);

        // (a) 只有 unplayable ⇒ 报 unplayable。
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "red_tape");
        let before = state_text(&state);
        assert_eq!(
            play_card(
                &mut state,
                Some(&content),
                &request("card_h1", Some("enemy_a"))
            )
            .unwrap_err(),
            PlayError::Refused(Refusal::Unplayable)
        );
        assert_eq!(state_text(&state), before);

        // (b) 同时被 stun ⇒ 报 stun（proves 顺序）。
        give_status(&mut state, "hero", STUN_STATUS);
        assert_eq!(
            play_card(
                &mut state,
                Some(&content),
                &request("card_h1", Some("enemy_a"))
            )
            .unwrap_err(),
            PlayError::Refused(Refusal::Stunned),
            "§2.3：stun 先于 unplayable，别照抄参考的注释"
        );
    }

    // ------------------------------------------------------------- 11. 目标为空不是拒绝

    #[test]
    fn a_missing_target_is_not_a_refusal() {
        // §4.3：参考里**不存在**"目标非法 ⇒ 拒绝出牌"。`target: None` ⇒ 选择器解出空集 ⇒
        // 效果哑火，但牌照样受理、照样付费、照样落区。
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");

        let report = play_card(&mut state, Some(&content), &request("card_h1", None))
            .expect("§4.3：target=None 不是错误");

        assert!(report.played);
        assert_eq!(energy_of(&state, "hero"), 2, "照样付费");
        assert_eq!(report.landed, Some(CardZone::DiscardPile), "照样落区");
        assert_eq!(health_of(&state, "enemy_a"), 20, "效果哑火（没有人被打到）");
        assert_eq!(health_of(&state, "enemy_b"), 10);
    }

    // ------------------------------------------------------------- 12. 请求面

    #[test]
    fn the_request_face_no_ops_on_a_refusal_but_errors_on_broken_state() {
        let blob = core_image();
        let content = parse(&blob);

        // (a) 付不起 ⇒ no-op（`Cards/PlayCardEffects.cs:74-82`）。
        // ⚠️ 这条原来断言"状态**逐字节**不变"，2026-10-19 的逐卡对拍证伪了它：参考在
        // `ScenarioRunner.cs:121` 就入队了（`CombatState.cs:386` 建根链），付不起是 handler 里
        // 才发现的 ⇒ **链号会动一格**。所以这里改成"只有链号动"：多一格不许，少一格也不许。
        let mut state = arena();
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .set_resource(energy(), 0, Some(3))
            .unwrap();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        let before = state_text(&state);
        let chain_before = state.next_effect_chain_number;
        let report = try_play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("请求面不抛");
        assert_eq!(report, PlayReport::NOT_PLAYED, "WasPlayed=false");
        assert_eq!(
            state.next_effect_chain_number,
            chain_before + 1,
            "拒绝之前那次入队已经发过号（`ScenarioRunner.cs:121` → `CombatState.cs:386`）"
        );
        assert_eq!(
            strip_generator_lines(&state_text(&state)),
            strip_generator_lines(&before),
            "除了那一格链号，状态逐字节不变（没付费、没落区、没跑节目）"
        );

        // (b) 战斗已结束 ⇒ 也是 no-op（外层队列循环只是不再调用它）。
        state.result = CombatResult::Victory;
        assert_eq!(
            try_play_card(
                &mut state,
                Some(&content),
                &request("card_h1", Some("enemy_a"))
            )
            .expect("请求面不抛"),
            PlayReport::NOT_PLAYED
        );

        // (c) 卡定义读不出来 ⇒ **Err**（参考在这一步也抛：`registry.GetCard`，`:50`）。
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        assert_eq!(
            try_play_card(&mut state, None, &request("card_h1", Some("enemy_a"))).unwrap_err(),
            PlayError::UnknownCard,
            "没有内容镜像 ⇒ 没有卡定义表 ⇒ 这一个**不许**被折成 no-op"
        );

        // (d) 节目 fault ⇒ **Err**（不是"正常拒绝"）。
        let broken = image_with_negative_paper_cut_amount();
        let broken_content = parse(&broken);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        assert_eq!(
            try_play_card(
                &mut state,
                Some(&broken_content),
                &request("card_h1", Some("enemy_a"))
            )
            .unwrap_err(),
            PlayError::Effect(exec::ExecError::Modifier)
        );
    }

    // ------------------------------------------------------------- 13. 顺序表

    #[test]
    fn the_validator_order_is_priority_then_modifier_id() {
        // §2.2：实际执行序 = (Priority 升序, ModifierId 序数升序)。
        for pair in VALIDATOR_ORDER.windows(2) {
            let (left, right) = (pair[0], pair[1]);
            let ordered = left.priority() < right.priority()
                || (left.priority() == right.priority() && left.modifier_id() < right.modifier_id());
            assert!(
                ordered,
                "{left:?}（{}/{}）必须排在 {right:?}（{}/{}）之前",
                left.priority(),
                left.modifier_id(),
                right.priority(),
                right.modifier_id()
            );
        }
        assert_eq!(
            VALIDATOR_ORDER.map(|validator| validator.modifier_id()),
            [
                "standard.stun_validator",
                "standard.decree_validator",
                "standard.play_condition_validator",
                "standard.one_attack_per_turn_validator",
                "standard.unplayable_validator",
            ],
            "§2.2 的五条执行序（150 档 'd' < 'p'，200 档 'o' < 'u'）"
        );

        // §3.3：六个费用修饰器的执行序同理。
        for pair in COST_STAGE_ORDER.windows(2) {
            let (left, right) = (pair[0], pair[1]);
            let ordered = left.priority() < right.priority()
                || (left.priority() == right.priority() && left.modifier_id() < right.modifier_id());
            assert!(ordered, "{left:?} 必须排在 {right:?} 之前");
        }
        assert_eq!(
            COST_STAGE_ORDER.map(|stage| stage.priority()),
            [100, 150, 200, 300, 1000, 1100]
        );
        assert!(
            !COST_STAGE_ORDER[0].prices_actions() && COST_STAGE_ORDER[4].prices_actions(),
            "只有 declarative 那条对动作也报价（`Cards/CardCostModifiers.cs:29` 默认 false、\
             `Effects/PassiveModifiers.cs:278` 声明 true）"
        );
    }

    // ------------------------------------------------------------- 14. 费用管线

    #[test]
    fn an_unreadable_cost_pipeline_fails_loudly_instead_of_charging_the_printed_cost() {
        // 把 `strength` 那条 spec 的 `Pipeline` 串改成一个**不是**管线名的串（用它自己的
        // `Polarity` 值 "Buff"）⇒ `status_bind::decode` 报 `BindError::Pipeline`。
        //
        // 这条测试钉的是规格书 §3.2 / §8.3 那个"静默错"：费用管线读不懂时，
        // 出牌必须**响亮失败**，绝不许按印刷价结算（那种错哈希对拍会通过）。
        let pristine = core_image();
        let content = parse(&pristine);
        let row = status_row_of(&content, "strength");
        let polarity = row.row().cell_by_name("Polarity").expect("Polarity 格");
        let passive = row.passive_modifiers();
        let list = content.term(passive).expect("PassiveModifiers 是 `_arr`");
        let start = list.slot(0).expect("AUX 起址");
        let element = content.aux(start).expect("第一条 spec 的 term id");
        let at = field_slot_offset(&content, element, "Pipeline");

        let mut blob = pristine;
        patch16(&mut blob, at, polarity);
        let content = parse(&blob);

        let mut state = arena();
        give_status(&mut state, "hero", "strength");
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        let before = state_text(&state);

        let error = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .unwrap_err();

        assert_eq!(
            error,
            PlayError::Effect(exec::ExecError::Bind(status_bind::BindError::Pipeline)),
            "读不懂的费用管线必须响亮，不许静默按印刷价"
        );
        assert_eq!(state_text(&state), before, "算费阶段拒绝 ⇒ 状态不变");
    }

    // ------------------------------------------------------------- 15. 法令闸门

    #[test]
    fn a_decree_in_the_content_is_refused_instead_of_being_ignored() {
        // 本内容 23/23 的 `CombatRules` 都是 `ABSENT16`（§8.2 实跑）。这里把 `strength` 那一格
        // 改成"一个非空的空列表 term" ⇒ 出牌路径上 5 个法令读点一个都没实现的 v1，
        // 必须**响亮失败**而不是按"没有法令"照算（§8.3）。
        let pristine = core_image();
        let content = parse(&pristine);
        let row = status_row_of(&content, "strength");
        let index = u32::from(
            content
                .lookup_in("strength", crate::content::EK_STATUS)
                .expect("strength 在 IDX 里")
                .index,
        );
        let cell = row.row().cell_index("CombatRules").expect("CombatRules 格");
        assert_eq!(
            row.combat_rules(),
            ABSENT16,
            "§8.2 实测：本内容所有状态的 CombatRules 都缺席"
        );
        let at = row_cell_offset(&content, Table::Status, index, cell);
        let empty = empty_array_term(&content);

        let mut blob = pristine;
        patch16(&mut blob, at, empty);
        let content = parse(&blob);

        let mut state = arena();
        give_status(&mut state, "hero", "strength");
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        let before = state_text(&state);

        let error = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .unwrap_err();
        assert_eq!(error, unsupported_content("CombatRules"));
        assert_eq!(state_text(&state), before);
    }

    // ------------------------------------------------------------- 16. IsAction

    #[test]
    fn the_card_played_flag_follows_is_action() {
        // 本内容 62/62 `IsAction` 缺席（⇒ false）。把它改成 `BOOL_TRUE` 之后，
        // 出牌照样付费、照样落区，但**不算"打出一张牌"**（`Cards/CardPlay.cs:130-150`：
        // 动作只写 `ActionUsed` 日志，不写 `CardPlayed`、不入队 `CardPlayedCombatEvent`）。
        let pristine = core_image();
        let content = parse(&pristine);
        let cell = card_cell_index(&content, 0, "IsAction");
        assert_eq!(
            content.card(0).unwrap().is_action(),
            crate::content::BOOL_ABSENT,
            "§1.4 实测的那一格是**缺席**（0x0000 = BOOL_ABSENT），不是 false"
        );
        let at = row_cell_offset(&content, Table::Card, 0, cell);

        let mut blob = pristine;
        patch16(&mut blob, at, BOOL_TRUE);
        let content = parse(&blob);

        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        let report = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("动作也走得通");

        assert!(!report.counted_as_card_played, "IsAction ⇒ 不算打出一张牌");
        assert_eq!(energy_of(&state, "hero"), 2, "动作照样付费用（`:128-129` 的注释）");
        assert_eq!(report.landed, Some(CardZone::DiscardPile));
        assert_eq!(health_of(&state, "enemy_a"), 14, "效果照样结算");
    }

    // ------------------------------------------------------------- 18. 无节目分支

    #[test]
    fn a_card_without_a_program_still_lands_where_its_definition_says() {
        // 5.12（`Cards/CardPlay.cs:283-293`）：卡定义**没有** `Program` 时，参考入队一条
        // `MoveCardToZone` 再关作用域 —— 出牌照样成立、照样付费、照样落区。
        //
        // 本内容 62/62 都有节目（§1.4 实测），所以这条分支在真实内容里不可达；
        // 把 CARD[0] 的 `Program` 格写成 `NULL16` 才走得到它。
        let pristine = core_image();
        let content = parse(&pristine);
        let program_cell = card_cell_index(&content, 0, "Program");
        let at = row_cell_offset(&content, Table::Card, 0, program_cell);

        let mut blob = pristine;
        patch16(&mut blob, at, NULL16);
        let content = parse(&blob);
        assert!(
            Ir::new(&content).card_program_root(0).is_err(),
            "补丁生效：CARD[0] 没有节目了"
        );

        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        let report = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("没有节目不影响出牌本身");

        assert!(report.played);
        assert_eq!(report.paid.amount_for(&energy()), Some(1), "照样付费");
        assert_eq!(report.landed, Some(CardZone::DiscardPile));
        assert_eq!(health_of(&state, "enemy_a"), 20, "没有节目 ⇒ 效果一件都不发生");
        assert_eq!(
            state.next_program_execution_id, 1,
            "没有节目 ⇒ **不**分配执行号（参考只在 Execute 里分配）"
        );
    }

    // ------------------------------------------------------------- 19. 两条法令规则占位

    #[test]
    fn the_decree_validator_carries_both_rules_even_though_neither_can_fire_today() {
        // 参考的 `DecreeCardPlayValidator.Validate` 里有**两条**规则，同一个校验器、同一个
        // `ModifierId`（`standard.decree_validator`）、同一个 Priority 150：
        //   ① `MaxCardsPerTurn`（`CombatDecrees.cs:150-158`，`played >= cap` ⇒ 拒）；
        //   ② `NoLikenessInSuccession`（`:160-174`，本卡带 tag 且上一张同类 ⇒ 拒）。
        //
        // ⚠️ 这张表**不是** `VALIDATOR_ORDER` 的副本：参考一共只注册 5 个校验器
        // （`StandardCombatPackage.cs:59-63`），两条法令规则住在同一个里。所以占位放在
        // 这张 `DECREE_RULES` 里（穷尽的 `match` + 本测试），校验器表仍是 5 行。
        assert_eq!(
            DECREE_RULES,
            [
                DecreeRule::MaxCardsPerTurn,
                DecreeRule::NoLikenessInSuccession
            ],
            "顺序照参考：先 Ceiling，后 InForce"
        );

        // 两条规则各要两样东西，v1 两样都拿不到 —— 这就是它们"今天不可达"的原因。
        for rule in DECREE_RULES {
            let (law, stats) = rule.needs();
            assert_eq!(law, "CombatRules", "{rule:?}：法令本身");
            assert_eq!(stats, "CardPlayTurnStats", "{rule:?}：那两张回合统计");
        }

        // 而"内容里真的有一条法令"的场面**不会**走到这两条规则：`refuse_if_any_decree`
        // 在校验器链之前就一票否决（见 a_decree_in_the_content_is_refused…）。
        // 所以 `Refusal::DecreeMaxCardsPerTurn` 与 `Refusal::DecreeNoLikeness` 今天
        // 一个都构造不出来 —— 下面的断言把"拒在闸门上、而不是拒在规则上"钉成行为：
        let pristine = core_image();
        let content = parse(&pristine);
        let row = status_row_of(&content, "strength");
        let index = u32::from(
            content
                .lookup_in("strength", crate::content::EK_STATUS)
                .expect("strength 在 IDX 里")
                .index,
        );
        let cell = row.row().cell_index("CombatRules").expect("CombatRules 格");
        let at = row_cell_offset(&content, Table::Status, index, cell);
        let empty = empty_array_term(&content);
        let mut blob = pristine;
        patch16(&mut blob, at, empty);
        let content = parse(&blob);

        let mut state = arena();
        give_status(&mut state, "hero", "strength");
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        let error = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .unwrap_err();
        assert_eq!(
            error,
            PlayError::UnsupportedContent("CombatRules"),
            "法令必须在闸门上被拒（内核缺能力），不能落到规则里假装'没有法令'"
        );

        // §8.2【实跑】：本内容 23 条状态的 `CombatRules` **23/23 全是 ABSENT16** ——
        // 所以"永久放行"与参考**逐位一致**，前提是那条闸门在。
        let pristine = core_image();
        let content = parse(&pristine);
        let mut statuses = 0usize;
        let mut index = 0u32;
        while let Some(row) = content.status(index) {
            assert_eq!(
                row.combat_rules(),
                ABSENT16,
                "STAT[{index}] 声明了法令 —— §8.2 的实测结论变了，法令闸门要重写"
            );
            statuses += 1;
            index += 1;
        }
        assert_eq!(statuses, 23, "STAT 表 23 行（§8.2 实测）");
    }

    // ------------------------------------------------------------- 20. Cancelled 终态

    /// 造一个"计划算得出来、还没执行"的场面 —— 与 [`play_card`] 的前半段完全同一条路径，
    /// 只是把 `apply_plan` 留给我们自己调。
    fn plan_for<'a>(
        content: &'a Content<'a>,
        instance: &str,
        definition: &str,
    ) -> (CombatState, PlayPlan<'a>) {
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, instance, definition);
        let plan = plan_play(&state, Some(content), &request(instance, Some("enemy_a")))
            .expect("paper_cut 的计划必须算得出来");
        (state, plan)
    }

    #[test]
    fn a_cancelled_play_leaves_the_card_in_hand_and_pays() {
        // §5.2 第三行 / `Cards/CardPlay.cs:240-241`、`:262`：程序执行到一半战斗结束 ⇒
        // **什么都不做**，卡留在手牌；`PlayReport.landed` 如实是 `None`。
        // 测试 `T:CardProgramTerminalCleanupTests.cs:62-78` 断言 Result=Victory 且卡仍在 Hand。
        //
        // ⚠️ 为什么在这里构造：`arena()` 里没有"这一击会打死最后一个敌人"的场面（两个敌人
        // 各 20/10 血，`paper_cut` 打 6），所以这份单元测试用"手动把 `result` 改掉"复刻
        // `SetResult` 取消在飞帧那一下（`CombatState.cs:358-359`）。
        //
        // **但这条分支 2026-10-19 起是真的可达的**（在此之前不可达，本注释原来写着
        // "真实内容下不可达"）：胜负判定搬到了 `exec::update_standard_combat_result`，
        // 就在目标倒下那一行。真实路径的覆盖在 `battle.rs` 的
        // `a_lethal_play_leaves_the_card_in_hand_and_the_combat_is_over`。
        let blob = core_image();
        let content = parse(&blob);
        let (mut state, plan) = plan_for(&content, "card_h1", "paper_cut");

        state.result = CombatResult::Victory; // ← `SetResult` 取消在飞帧（`CombatState.cs:358-359`）
        let report = apply_plan(&mut state, &plan, Face::Queued).expect("Cancelled 不是错误");

        assert!(report.played, "牌**已经打出去了**（费用付了、CardPlayed 也 fire 了）");
        assert_eq!(report.landed, None, "§5.2 Cancelled：`landed` 必须是 None");
        assert_eq!(
            zone_of(&state, "hero", "card_h1"),
            Some(CardZone::Hand),
            "卡留在手牌（不搬、不入队）"
        );
        assert_eq!(
            energy_of(&state, "hero"),
            2,
            "费用**已经付过**：付款在跑节目之前（`Cards/CardPlay.cs:123-126` 早于 `:221`）"
        );
        assert_eq!(health_of(&state, "enemy_a"), 20, "程序一步都没跑");
    }

    #[test]
    fn the_same_plan_lands_the_card_when_the_combat_is_still_ongoing() {
        // 成对反例：**同一张卡、同一份状态、同一个 `plan_play`**，只把 `result` 留成 `Ongoing`
        // ⇒ 卡落到目标区。两半合起来才证明"差别只来自 result"，而不是来自别的什么东西。
        let blob = core_image();
        let content = parse(&blob);
        let (mut state, plan) = plan_for(&content, "card_h1", "paper_cut");
        assert_eq!(state.result, CombatResult::Ongoing, "默认就是进行中");

        let report = apply_plan(&mut state, &plan, Face::Queued).expect("Completed 不是错误");

        assert!(report.played);
        assert_eq!(report.landed, Some(CardZone::DiscardPile));
        assert_eq!(
            zone_of(&state, "hero", "card_h1"),
            Some(CardZone::DiscardPile),
            "§5.2 Completed：卡搬到 PlayedCardDestinationZone"
        );
        assert_eq!(energy_of(&state, "hero"), 2, "费用同样付过（两半一致）");
        assert_eq!(health_of(&state, "enemy_a"), 14, "程序真的跑了 6 点伤害");
    }

    // ------------------------------------------------------------- 21. 两个发号器

    #[test]
    fn a_play_advances_both_counters_and_the_two_faces_differ_by_exactly_one() {
        // ⚠️ 这条测试的名字原来是 `…_but_not_the_effect_chain`，断言 `chain_num` **+0**。
        // 2026-10-19 的整局对拍（`native/fight_diff.py`）证明那个期望是错的：
        // C# 规范文本里一次正常出牌让 `chain_num` **+3**，一次 Cancelled 出牌 **+1**。
        // 反推依据见 `apply_plan` 文档里那张三笔账的表（每笔都带参考行号）。
        //
        // 这里同时钉两件事：
        // * 严格面（直接调处理器）**2 笔**：搬区 + 动作收尾；
        // * 请求面（先入队一条 `PlayCardEffectRequest`）**3 笔**：再多请求那一笔。
        //
        // 只钉"变了"是不够的 —— 那对"硬加一个 +1"也成立；钉成 2 和 3 才能把
        // "链号是不是恰好按参考那三笔走"变成可证伪的断言。
        let blob = core_image();
        let content = parse(&blob);

        let mut strict = arena();
        give_card(&mut strict, "hero", CardZone::Hand, "card_h1", "paper_cut");
        let chain_before = strict.next_effect_chain_number;
        let execution_before = strict.next_program_execution_id;
        play_card(
            &mut strict,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("paper_cut 必须打得出去");
        assert_eq!(
            strict.next_program_execution_id,
            execution_before + 1,
            "§6.1：节目执行一次发一个号（`EffectProgramExecution.cs:27`）"
        );
        assert_eq!(
            strict.next_effect_chain_number,
            chain_before + 2,
            "严格面：搬区 `Cards/CardPlay.cs:251` + 动作收尾 `:311`，两次都在续延里（顶层入队）"
        );

        let mut queued = arena();
        give_card(&mut queued, "hero", CardZone::Hand, "card_h1", "paper_cut");
        let chain_before = queued.next_effect_chain_number;
        let execution_before = queued.next_program_execution_id;
        try_play_card(
            &mut queued,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("请求面同样打得出去");
        assert_eq!(
            queued.next_program_execution_id,
            execution_before + 1,
            "请求面与严格面的执行号一致"
        );
        assert_eq!(
            queued.next_effect_chain_number,
            chain_before + 3,
            "请求面多一笔：`ScenarioRunner.cs:121` 的 EnqueueEffect"
        );
        // 两侧打出的是**同一张卡的同一段程序**（否则上面那个 +3 可能只是"多打了一次"）。
        assert_eq!(health_of(&strict, "enemy_a"), health_of(&queued, "enemy_a"));

        // 成对：卡不在手牌 ⇒ **两个号都不动**（参考的 `ScenarioRunner.cs:109-117` 在入队之前就挡了，
        // 这一点被 `refusals` 场景 step 0 的数据钉着：C# 那边 `chain_num` 只 +1，来自开回合）。
        let mut refused = arena();
        let chain_before = refused.next_effect_chain_number;
        let execution_before = refused.next_program_execution_id;
        let report = try_play_card(
            &mut refused,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("拒绝不是错误");
        assert!(!report.played);
        assert_eq!(refused.next_effect_chain_number, chain_before, "拒绝不动链号");
        assert_eq!(
            refused.next_program_execution_id, execution_before,
            "拒绝不动执行号"
        );

        // ⚠️ 另一半（2026-10-19 逐卡对拍补的）：卡**在**手里但被校验器拒绝（`red_tape` 带
        // `unplayable` 标签）⇒ 参考那次入队已经发过号了 ⇒ **链号 +1**、执行号 +0。
        // 这一条与上面那条配对：两条一起才把 "+0 还是 +1" 变成可证伪的断言
        // （只测其中一条，把规则写成"一律 +0"或"一律 +1"都能通过）。
        let mut unplayable = arena();
        give_card(&mut unplayable, "hero", CardZone::Hand, "card_h1", "red_tape");
        let chain_before = unplayable.next_effect_chain_number;
        let execution_before = unplayable.next_program_execution_id;
        let report = try_play_card(
            &mut unplayable,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("校验器拒绝不是错误");
        assert!(!report.played, "unplayable ⇒ WasPlayed=false");
        assert_eq!(
            unplayable.next_effect_chain_number,
            chain_before + 1,
            "校验器拒绝发生在入队之后（`ScenarioRunner.cs:121` → `Cards/PlayCardEffects.cs:54-58`）"
        );
        assert_eq!(
            unplayable.next_program_execution_id, execution_before,
            "节目一步都没跑 ⇒ 执行号不动"
        );

        // ⚠️ 第三笔账（同一次实测补的）：卡被**它自己的节目**挪出手牌时，参考 `onTerminal`
        // 的手牌守卫（`Cards/CardPlay.cs:245-247`）让那次搬区入队根本不发生 ⇒ 只 +2，不是 +3。
        let mut self_moving = arena();
        give_card(
            &mut self_moving,
            "hero",
            CardZone::Hand,
            "card_h1",
            "archive_the_evidence",
        );
        let chain_before = self_moving.next_effect_chain_number;
        let report = try_play_card(
            &mut self_moving,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("归档证据打得出去");
        assert!(report.played);
        assert_eq!(
            zone_of(&self_moving, "hero", "card_h1"),
            Some(CardZone::ExhaustPile),
            "节目里的 forEachCardInZone → moveCardToZone 把它自己搬去了 ExhaustPile"
        );
        assert_eq!(
            self_moving.next_effect_chain_number,
            chain_before + 2,
            "搬区那笔不发号（`:245-247` 的守卫），只剩请求 + 收尾"
        );
    }
}

