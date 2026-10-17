//! 一局战斗的驱动层 —— 把 `turn` / `play` / `host` / `intent` 串成一条时间线。
//!
//! **规格**：`docs/spec/fight-driver.md`（从参考实现的 `ScenarioRunner` 逐行抄来的语义）。
//!
//! # 为什么需要它
//!
//! 到此为止内核有六个模块，但它们**互相不认识**：`play.rs` 会打牌但没人叫它，
//! `turn.rs` 会推回合但没有宿主，`host.rs` 实现了宿主但没人驱动它，`intent.rs` 会挑敌人动作
//! 但没人问它。本模块是那根线。
//!
//! # 语义不是发明的，是抄的
//!
//! 参考实现里承担这件事的是 `RogueDeck.Scenario.Scripting.ScenarioRunner`
//! （`ref/RogueDeck-Core/src/RogueDeck.Scenario/Scripting/ScenarioRunner.cs`，267 行）。
//! 它的自述值得逐字记住：
//!
//! > It adds NO combat semantics — it only sequences engine calls and observes the result.
//! > Every problem it surfaces … is a real observation about how the engine behaved,
//! > not an authored assertion.
//!
//! 所以本模块的两条设计铁律：
//!
//! 1. **绝不在这里新增战斗语义**。每一步只做两件事：调已有的模块、记下发生了什么。
//!    一旦本模块开始"顺手把某件事做对"，它就从驱动器变成了第二套规则 —— 而两套规则
//!    迟早不一致，且**对拍会因为它自己而被掩盖**。
//! 2. **"问题"是观测，不是失败**。参考的 `problems` 里装的既有"这张牌打出去了但没生效"，
//!    也有"战斗已经结束、这一步没执行"。这些东西**不抛异常**，它们被记录下来继续往下走。
//!    本模块把它们建模成 [`Problem`] 枚举而不是 `Err`，就是为了不让调用方把
//!    "引擎这样反应了"误当成"驱动层坏了"。
//!
//! # 与参考的四处**故意**不对齐（都记在规格书里，别当成 bug 改回去）
//!
//! 1. 参考的 `EnsureTurnStarted` 在 `TurnPhase == WaitingToStartTurn` 时调 `StartCurrentTurn`；
//!    内核的对应物是 `turn::start_current_turn`，但**它需要 `&mut H: TurnHost`** —— 宿主从哪来
//!    由调用方决定（本模块不自己造宿主，否则就把"谁提供效果"这件事写死了）。
//! 2. 参考用 `combat.EnqueueEffect(...)` + `_queues.ResolvePendingQueues(...)`（**队列中介**）；
//!    内核没有事件队列，出牌是**就地**执行的（`play::play_card`）。这是内核 v1 最大的
//!    一处已知偏差，规格书 §"队列中介 vs 就地" 写了它的可观察后果。
//! 3. 参考的 `problems` 是字符串；内核这边是 [`Problem`] 枚举（`no_std` 零分配）。
//!    对拍只比较**条数**和**类别**，不比较文本。
//! 4. 参考的 `ScenarioReport` 持有一整份 `CombatState`；内核这边**状态由调用方提供**
//!    （`&mut CombatState`），因为它在裸机上 180 KB，不该被复制来复制去。
//!
//! # 现在的状态：实现了，但有三处"冻结面没给够"（每一处都写在自己的小节里）
//!
//! `build_fight` / `run_fight` 已经照规格书逐行落地，测试全部接真实镜像
//! （`tools/contentc/out/content.core.rdcf`）。落地过程中撞到**三个接口层面的洞**，
//! 每一个都在下面那一节里写明"我怎么办的"以及"正确的修法是什么"：
//!
//! * [`FROZEN_GAP_TURN_CONFIG`] —— `run_fight` 收不到 `TurnConfig`，也收不到 `FightPlan`；
//! * [`FROZEN_GAP_HERO_ID`] —— `run_fight` 收不到英雄 id；
//! * [`FROZEN_GAP_RESULT`] —— 全仓**没有任何代码**算胜负（`state.result` 永远是 `Ongoing`）。
//!
//! 另外 [`Problem`] 少一个变体（参考 `ScenarioRunner.cs:241` 的 "it is still the hero's turn"
//! 与 `:248` 的 "could not advance" 是**两条不同的**问题），见 [`FROZEN_GAP_PROBLEM`]。

use crate::content::{Content, ABSENT16, EK_CARD, EK_EACTION, F_TERM, LIST_ABSENT, LIST_NULL, NULL16,
    OP_ARR, OP_WRAP_LOWER};
use crate::intent;
use crate::play::{self, PlayError, PlayRequest};
use crate::rng;
use crate::state::{
    CapacityError, CardDefinitionId, CardInstance, CardInstanceId, CardSlot, CardZone, CombatId,
    CombatResult, CombatState, CombatTurnPhase, Combatant, CombatantDefinitionId, CombatantId,
    CombatantLifecycleState, DefensivePoolId, ResourceId, TeamId, ZonePlacement, MAX_CARDS_PER_ZONE,
};
use crate::turn::{self, HostFailure, TurnConfig, TurnError, TurnHost};

/// 一次驱动最多几步。
///
/// 参考的脚本都很短（`BuildScript` 最长 6 步），但**不是**靠"脚本短"来定这个上限的：
/// 它是驱动层自己的信封，超了就 [`BattleError::TooManySteps`]，绝不截断。
pub const MAX_STEPS: usize = 64;
/// 每步最多记几条"问题"。
///
/// 参考里一步最多记 2～3 条；32 是"内容怎么坏都装得下"的取法，超了同样是响亮失败。
pub const MAX_PROBLEMS_PER_STEP: usize = 32;

/// 三条**接口层面的洞**的说明（冻结方 2026-10-18 交给执行方时留下的，执行方按现实实现）。
///
/// 它们不是"注释"，是**已经发生的偏差**。任何读到本模块的人第一件该知道的事就是这三条。
///
/// # `FROZEN_GAP_TURN_CONFIG`
///
/// `run_fight` 的签名是 `(state, content, steps, host, out)` —— 里面**没有** `TurnConfig`，
/// 也没有 `FightPlan`。而回合机三个入口（`start_current_turn` / `end_current_turn` /
/// `end_current_turn_and_start_next`）**都要** `&TurnConfig`，参考那边这组数字来自标准包
/// （`StandardCombatPackage.cs:7` 的抽牌数、`:124` 的能量补到几点）。
///
/// ⇒ 本模块用一份**硬编码的标准包配置** [`standard_turn_config`]。后果是
/// [`FightPlan::cards_drawn_per_turn`] 与 [`FightPlan::turn_start_refills`] 这两个字段
/// **到不了回合机** ⇒ `build_fight` 会把"蓝图要的和本模块会给的不一致"直接拒掉
/// （[`check_turn_knobs`]），而不是静默按标准包跑。
///
/// **正确的修法**：给 `run_fight` 补一个 `config: &TurnConfig` 参数（或 `plan: &FightPlan`），
/// 那时 [`check_turn_knobs`] 整段删掉。
///
/// 公开它是因为它要**打出来**：`rd-fightdump` 每个场景头上把这四条印成一行，
/// 好让读输出的人第一眼知道"这份输出是在什么偏差下产生的"。
pub const FROZEN_GAP_TURN_CONFIG: &str = "run_fight-cannot-see-TurnConfig";

/// # `FROZEN_GAP_HERO_ID`
///
/// 参考的 `Run` 先取一次 `compiled.Hero.CombatantId`（`ScenarioRunner.cs:29`），
/// 之后每一步都在用它（`:102`、`:136`、`:172`、`:206`、`:239`）。内核的 `run_fight` 收不到
/// 英雄 id，只看得到一个 `CombatState`。
///
/// ⇒ 本模块从**状态**里推：[`hero_of`] 取回合序里第一个 `team_id == "player"` 的单位。
/// 这个推断在 `build_fight` 建出来的状态上**恰好正确**（英雄是第一个加进去的、队是 `player`），
/// 但它是推断，不是契约。推不出来（没有 player 队）时**不报错**：参考在那种状态下走的是
/// `:45-51` 的"英雄不在/已倒下"分支，本模块照抄（每步记一条 [`Problem::HeroDowned`]）。
pub const FROZEN_GAP_HERO_ID: &str = "run_fight-cannot-see-hero-id";

/// # `FROZEN_GAP_RESULT`
///
/// 参考的胜负由 `UpdateStandardCombatResultOnLifecycleChangedHandler`
/// （`RogueDeck.Core/Combat/Effects/CombatStateEffects.cs:28-60`）在
/// `CombatantLifecycleChanged` 事件上算，靠事件队列生效。
///
/// 本内核**没有事件队列**，也没有那条 handler：`exec.rs` 把"扣到 0 转 `Downed`"就地做了，
/// 但 `state.result` 全仓**没有任何生产代码**会写它（`host.rs:2900-2903` 的测试注释明确写着
/// "本内核今天算不出胜负"）。⇒ 如果驱动层不算，`run_fight` 永远报 `Ongoing`，
/// 规格书 §4 阶段 1 的那条判据（"整局能跑到 `Result != Ongoing`"）**不可能成立**。
///
/// ⇒ 本模块在**每一步之后**调 [`settle_result`]（逐行照 `CombatStateEffects.cs:36-58`）。
/// 这是本模块唯一一处"做了引擎该做的事"，理由与代价：
///
/// * 它是**参考实现里真实存在的语义**，不是发明 —— 只是它该住在宿主/事件层，而 v1 没有那一层；
/// * 粒度更粗：参考在"生命周期变化"那一刻入队、在**下一次队列排空**时生效，本模块只在
///   **步边界**算。对"一步 = 打一张牌"是可观察等价的（一张牌的程序跑完才排空队列）；
///   对 `HeroEndsTurn` / `NextRound` 这类**一步里推好几次回合**的步则更粗 —— 见 §"未验证"。
///
/// **正确的修法**：在 `host.rs` 里实现那条 handler（或给 `CombatState` 加事件队列），
/// 那时 [`settle_result`] 整段删掉。
pub const FROZEN_GAP_RESULT: &str = "no-code-computes-CombatResult";

/// # `FROZEN_GAP_PROBLEM`
///
/// [`Problem`] 少一个变体：参考在 `AdvanceTurnsUntilActive` 里有**两条**不同的"推不到"：
///
/// * `:241` "It is still the hero's turn — call HeroEndsTurn before EnemyActs."（轮到英雄，
///   驱动层不替英雄结束回合）；
/// * `:248` "Could not advance to enemy …'s turn."（转了 `TurnOrder.Count + 1` 次还没轮到）。
///
/// 冻结的枚举只有 [`Problem::CannotReachEnemyTurn`] 一个桶，所以**两条都塌进它**。
/// 对拍比"类别与条数"时这一条会少一个类别 —— 除非观察 `EnemyActs` 一步的具体条数
/// （轮到英雄时是 **2 条**：`:241` 一条 + `:172` 的 "active 不是它" 一条）。
/// 测试 `the_still_heroes_turn_problem_collapses_into_cannot_reach_enemy_turn` 把它钉住了。
pub const FROZEN_GAP_PROBLEM: &str = "Problem-has-no-StillHeroTurn-variant";

/// 蓝图里的一个战斗员。
#[derive(Clone, Copy, Debug)]
pub struct PlanCombatant<'a> {
    /// 战斗员 id（进哈希）。
    pub id: &'a str,
    /// 最大生命（当前生命一开始等于它）。
    pub max_health: i32,
}

/// 牌组里的一项：卡**定义** id 与张数。
#[derive(Clone, Copy, Debug)]
pub struct DeckEntry<'a> {
    /// 卡定义 id。必须能在 `Content` 的 `CARD` 表里找到，否则建战斗时就响亮失败。
    pub card: &'a str,
    /// 张数。
    pub count: u16,
}

/// 一局战斗的蓝图（对应参考的 `ScenarioBlueprint`）。
///
/// ⚠️ 卡**定义**来自内容镜像（`Content`），不是这里 authored 的 —— 参考的蓝图可以把
/// 程序直接写进蓝图（`Effects.Program(...)`），内核这边没有"在 Rust 里造 IR"的能力
/// （`ir.rs` 是只读视图），所以**卡必须是镜像里真有的卡**。这是本模块与参考最大的一处
/// 结构差异，也是"整局对拍"必须先在 C# 侧把同一张卡按镜像的 id 与程序 author 出来的原因。
///
/// ⚠️ 另外两个字段今天**到不了回合机**（见 [`FROZEN_GAP_TURN_CONFIG`]）：
/// `cards_drawn_per_turn` 与 `turn_start_refills` 只被 [`build_fight`] 用来**拒绝**
/// 它所兑现不了的蓝图，`run_fight` 用的是标准包那一组数字。
#[derive(Clone, Copy, Debug)]
pub struct FightPlan<'a> {
    /// 战斗 id（进哈希）。
    pub combat_id: &'a str,
    /// RNG 种子（状态里只存 `(seed, step)`）。
    pub seed: i32,
    /// 英雄。
    pub hero: PlanCombatant<'a>,
    /// 敌人（顺序即回合序）。
    pub enemies: &'a [PlanCombatant<'a>],
    /// 英雄牌组。
    pub deck: &'a [DeckEntry<'a>],
    /// 每回合抽几张。
    pub cards_drawn_per_turn: i32,
    /// 开局是否洗牌（**不洗就一次随机数都不消耗**，参考的注释专门强调过这一点）。
    pub shuffle_draw_pile_on_start: bool,
    /// 开局资源（例如能量 `Current: 3, Max: 3`）。
    pub resources: &'a [(ResourceId, i32, Option<i32>)],
    /// 回合开始补到多少（例如能量补到 3）。空 = 不补。
    pub turn_start_refills: &'a [(ResourceId, i32)],
}

/// 一步脚本（对应参考的 `ScenarioStep` 的四个子类型）。
#[derive(Clone, Copy, Debug)]
pub enum Step<'a> {
    /// `HeroPlaysCard`：英雄打出**手里第一张**该定义的卡。
    HeroPlays {
        /// 卡定义 id。
        card: &'a str,
        /// 目标（`None` = 没有目标，不是错误）。
        target: Option<&'a str>,
    },
    /// `HeroEndsTurn`：结束当前回合并开始下一个。
    HeroEndsTurn,
    /// `EnemyActs`：推进到该敌人的回合，让它执行指定动作。
    EnemyActs {
        /// 敌人 id。
        enemy: &'a str,
        /// 敌人动作 id。
        action: &'a str,
        /// 目标。
        target: Option<&'a str>,
    },
    /// `AdvanceToNextRound`：结束英雄回合并把回合序推到下一个英雄回合。
    NextRound,
}

/// 一条"这是引擎的真实反应"的观测（对应参考的 `problems` 字符串）。
///
/// **不是错误**：参考在遇到它们时继续往下跑，只是把观测记下来。
/// 建模成枚举而不是 `&str`，是因为 `no_std` 零分配，且对拍比较的是**类别与条数**。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Problem {
    /// `combat.Result != Ongoing`，这一步没有执行（`ScenarioRunner.cs:40-44`）。
    CombatAlreadyEnded,
    /// 英雄倒下了，驱动层无法继续（`:45-51`）。
    HeroDowned,
    /// 这一步抛了异常，被捕获并记下（`:57-62`）。
    StepThrew,
    /// 英雄打出时行动者不是英雄（`:102-103`）。
    NotHeroTurn,
    /// 要打的那张卡不在手里（`:113-117`）。
    CardNotInHand,
    /// 卡打出去了但没生效（付不起/被校验器拒绝，`:124-125`）。
    CardNotPlayed,
    /// 结束回合时行动者不是英雄（`:132-133`）。
    NotHeroTurnToEnd,
    /// 指定敌人不存在（`:158-161`）。
    NoSuchEnemy,
    /// 战斗在敌人行动前就结束了（`:166-170`）。
    CombatEndedBeforeEnemy,
    /// 推不到那个敌人的回合（`:172-176`、`:240-250`）。
    CannotReachEnemyTurn,
    /// 敌人已经倒下（`:178-182`）。
    EnemyNotAlive,
    /// 敌人动作没注册（`:184-189`）。
    UnknownEnemyAction,
    /// `NextRound` 没能转回英雄回合（`:214-218`）。
    CouldNotWrapToHero,
}

impl Problem {
    /// 这个观测的名字（给 `rd-fightdump` 的机器可读输出用；**不进哈希**）。
    ///
    /// 与参考的字符串不是逐字对应（参考是整句英文，`no_std` 侧不装字符串表），
    /// 对应的是**类别**。名字取变体名本身，好让两边一对就明白说的是哪条分支。
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            Problem::CombatAlreadyEnded => "CombatAlreadyEnded",
            Problem::HeroDowned => "HeroDowned",
            Problem::StepThrew => "StepThrew",
            Problem::NotHeroTurn => "NotHeroTurn",
            Problem::CardNotInHand => "CardNotInHand",
            Problem::CardNotPlayed => "CardNotPlayed",
            Problem::NotHeroTurnToEnd => "NotHeroTurnToEnd",
            Problem::NoSuchEnemy => "NoSuchEnemy",
            Problem::CombatEndedBeforeEnemy => "CombatEndedBeforeEnemy",
            Problem::CannotReachEnemyTurn => "CannotReachEnemyTurn",
            Problem::EnemyNotAlive => "EnemyNotAlive",
            Problem::UnknownEnemyAction => "UnknownEnemyAction",
            Problem::CouldNotWrapToHero => "CouldNotWrapToHero",
        }
    }
}

/// 一步的观测结果（对应参考的 `ScenarioStepReport`，去掉 trace）。
#[derive(Clone, Copy, Debug)]
pub struct StepOutcome {
    /// 这一步开始时的轮次（参考在**执行前**取上下文）。
    pub round: i32,
    /// 这一步开始时的回合。
    pub turn: i32,
    /// 这一步记下了几条问题。
    pub problems: u8,
}

impl StepOutcome {
    /// 空观测（`round`/`turn` 都是 0，问题 0 条）。未使用的槽用它填。
    pub const EMPTY: Self = Self {
        round: 0,
        turn: 0,
        problems: 0,
    };
}

/// 整局的观测结果。**装不下时响亮失败**，绝不静默截断。
#[derive(Clone, Copy, Debug)]
pub struct FightOutcome {
    /// 每步的观测。
    pub steps: [StepOutcome; MAX_STEPS],
    /// 实际步数。
    pub step_count: usize,
    /// 每步的问题，`problems[i]` 最多 `MAX_PROBLEMS_PER_STEP` 条。
    pub problems: [[Problem; MAX_PROBLEMS_PER_STEP]; MAX_STEPS],
    /// 终局结果。
    pub result: CombatResult,
}

impl FightOutcome {
    /// 全空的观测结果。`run_fight` 会覆盖前 `step_count` 项，其余留 [`StepOutcome::EMPTY`]。
    ///
    /// 未使用的问题槽填 [`Problem::CombatAlreadyEnded`] —— 这是个**填充值**，
    /// 不可见：[`Self::problems_of`] 只暴露前 `steps[i].problems` 条。
    #[must_use]
    pub fn new() -> Self {
        Self {
            steps: [StepOutcome::EMPTY; MAX_STEPS],
            step_count: 0,
            problems: [[Problem::CombatAlreadyEnded; MAX_PROBLEMS_PER_STEP]; MAX_STEPS],
            result: CombatResult::Ongoing,
        }
    }

    /// 第 `index` 步的观测量；越界 `None`。
    #[must_use]
    pub fn step(&self, index: usize) -> Option<StepOutcome> {
        if index < self.step_count {
            self.steps.get(index).copied()
        } else {
            None
        }
    }

    /// 第 `index` 步的**有效**问题清单（正好 `steps[index].problems` 条）。
    ///
    /// 越界或该步没执行（`index >= step_count`）⇒ 空切片。
    #[must_use]
    pub fn problems_of(&self, index: usize) -> &[Problem] {
        let Some(step) = self.step(index) else {
            return &[];
        };
        let count = usize::from(step.problems);
        self.problems
            .get(index)
            .and_then(|slots| slots.get(..count))
            .unwrap_or(&[])
    }
}

impl Default for FightOutcome {
    fn default() -> Self {
        Self::new()
    }
}

/// 驱动一局时可能真的坏掉的事（**不是** [`Problem`] —— 那些是观测）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BattleError {
    /// 步数超过信封。
    TooManySteps,
    /// 一步记的问题超过信封。
    TooManyProblems,
    /// 建战斗时用到的卡定义在镜像里不存在。
    UnknownCard(CardDefinitionId),
    /// 牌组容量/状态容器装不下。
    Capacity(crate::state::CapacityError),
    /// 回合机报错。
    Turn(TurnError),
    /// 出牌报错。
    Play(PlayError),
}

impl From<crate::state::CapacityError> for BattleError {
    fn from(e: crate::state::CapacityError) -> Self {
        BattleError::Capacity(e)
    }
}
impl From<TurnError> for BattleError {
    fn from(e: TurnError) -> Self {
        BattleError::Turn(e)
    }
}
impl From<PlayError> for BattleError {
    fn from(e: PlayError) -> Self {
        BattleError::Play(e)
    }
}

// =============================================================================================
// 标准包的常量（`StandardCombatIds` / `StandardCombatPackage`，我逐行核对过）
// =============================================================================================

/// `StandardCombatIds.PlayerTeam`（`StandardCombatIds.cs`：`new("player")`）。
const PLAYER_TEAM: &str = "player";
/// `StandardCombatIds.EnemyTeam`（同文件：`new("enemy")`）。
const ENEMY_TEAM: &str = "enemy";
/// `StandardCombatIds.EnergyResource`（同文件：`new("standard.energy")`）。实测串池 id 1265。
const ENERGY: &str = "standard.energy";
/// `StandardCombatIds.BlockDefensivePool`（同文件：`new("standard.block")`）。
const BLOCK: &str = "standard.block";
/// 标准包 turn-start 补到几点能量（`StandardCombatPackage.cs:124` 的 `defaultMax: 3`）。
const ENERGY_REFILL: i32 = 3;
/// 标准包每回合抽几张（`StandardCombatPackage.cs:7` 的构造参数默认值 `cardsDrawnPerTurn = 5`）。
const CARDS_DRAWN_PER_TURN: i32 = 5;
/// `StandardCombatIds.InnateTag`（`StandardCombatIds.cs`：`new("innate")`）。
///
/// ⚠️ 实测：**core 镜像的串池里根本没有这个串**（1375 个串里没有 `innate`），
/// 62 张卡的 `Tags` 里也没有它 ⇒ [`reject_innate_deck`] 今天不可达。
const INNATE_TAG: &str = "innate";
/// `CreateNextCardInstanceId` 的前缀（`CombatState.cs:689-696`：`$"card_{n:000000}"`）。
const CARD_ID_PREFIX: &[u8] = b"card_";
/// 装 `<prefix>%06d` 的栈上缓冲（与 `exec.rs:2125` 同值，理由见那边的注释）。
const INSTANCE_TEXT_CAP: usize = 32;

/// 回合机要的那组数字，**来自标准包而不是蓝图**（[`FROZEN_GAP_TURN_CONFIG`]）。
///
/// 五条逐个带出处：
/// * `energy` = `standard.energy`（`StandardCombatIds.EnergyResource`）；
/// * `energy_refill` = 3（`StandardCombatPackage.cs:124`）；
/// * `draw_per_turn` = 5（`StandardCombatPackage.cs:7` 的默认参数）；
/// * `block_pool` = `standard.block`（`StandardCombatIds.BlockDefensivePool`）；
/// * `max_hand_size` = `i32::MAX` —— 因为**镜像里没有 `MaxHandSize` 法令**：
///   `STAT.CombatRules` 23/23 全是 `ABSENT16`、`REL.CombatRules` 49/49 是空 `[]`
///   （`host.rs:1578-1580` 的实测），而 `turn.rs` 的契约是"没有该法令时给 `i32::MAX`"。
///
/// # Errors
///
/// 两个常量 id 短得不可能超容量；返回 `Result` 只是为了让生产路径**没有** `unwrap`
/// （`ResourceId::new` 的拒绝理由是"超 40 字节"或"非 ASCII"，对这两个字面串恒为假）。
pub fn standard_turn_config() -> Result<TurnConfig, BattleError> {
    Ok(TurnConfig {
        energy: ResourceId::new(ENERGY)?,
        energy_refill: ENERGY_REFILL,
        draw_per_turn: CARDS_DRAWN_PER_TURN,
        block_pool: DefensivePoolId::new(BLOCK)?,
        max_hand_size: i32::MAX,
    })
}

/// "内容/蓝图要求 v1 没实现的能力"。
///
/// `BattleError` 没有专门的桶，`TurnError::Host(HostFailure::Unsupported)` 是唯一**字面正确**
/// 的那一个（`turn.rs` 的 `HostFailure::Unsupported` 文档：*内核缺能力：内容用到了 v1
/// 没实现的那条路*）。用 `Host` 这个桶会让人以为"宿主失败了"，所以每一处调用点都写清了
/// 为什么 —— 见 [`FROZEN_GAP_TURN_CONFIG`] 与 [`reject_innate_deck`]。
fn unsupported() -> BattleError {
    BattleError::Turn(TurnError::Host(HostFailure::Unsupported))
}

/// "镜像里的结构读不出来"（`HostFailure::Content` 的字面意思：内容配错了）。
fn content_error() -> BattleError {
    BattleError::Turn(TurnError::Host(HostFailure::Content))
}

// =============================================================================================
// 建战斗
// =============================================================================================

/// 按蓝图建出一局战斗的初始状态（对应参考的 `ScenarioCombatFactory.Build`）。
///
/// 顺序照 `ScenarioCombatFactory`：战斗员（含生命、资源、回合序）→ 牌组 → 抽牌堆 →
/// 开局洗牌 → 回合阶段停在 `WaitingToStartTurn`（**不**替调用方开始第一回合）。
///
/// # 参考的行号（`ScenarioCombatFactory.cs`）
///
/// | # | 步 | 行号 | 本内核 |
/// |---|---|---|---|
/// | 1 | `new CombatState(combatId, seed)` | `:13-17` | **整体重置** `*state`（见下） |
/// | 2 | 英雄（player 队）→ 友方 → 敌人（enemy 队） | `:19-24` | 英雄 + 敌人；友方无字段 ⇒ 天然为空 |
/// | 3 | `SetActiveCombatant(hero)` | `:26` | 显式写一次 |
/// | 4 | `DealDeck(hero)` | `:31`、`:67-77` | 每张一个新实例 id，进 `DrawPile` |
/// | 5 | `ShuffleDrawPileOnStart` | `:38-43`、`:81-89` | `Count > 1` 才洗、才推 `random_step` |
/// | 6 | `MoveInnateCardsToTop` | `:45-49`、`:93-104` | **不支持** ⇒ 有 innate 卡就拒绝 |
/// | 7 | 起始状态（走真管线） | `:51-57` | 无字段 ⇒ 天然为空 |
/// | 8 | 开局临时规则 | `:59-61` | 无字段 ⇒ 天然为空 |
///
/// 第 1 步为什么要**整体重置**：参考在那一行**新建**一份状态，而内核的电牌面是"调用方提供
/// 存储"。不重置的话 `card_num=` / `random_step=` / `status_num=` 会带着别处的残留进哈希
/// —— 那种偏差不会报错，只会让指纹对不上。`CombatState` 的容器字段是私有的，
/// 所以只能整体赋值。
///
/// # Errors
///
/// 卡定义在镜像里找不到 ⇒ [`BattleError::UnknownCard`]；容器装不下 ⇒ `Capacity`；
/// 蓝图要求 v1 做不到的事（非标准回合旋钮、带 `innate` 的卡）⇒ `Turn(Host(..))`，理由见
/// [`FROZEN_GAP_TURN_CONFIG`] 与 [`reject_innate_deck`]。
///
/// ⚠️ **失败时 `state` 是半成品**这件事被尽量推到边上：凡是**纯读**就能做的检查
/// 全在"步 0"里做（`state` 一个字节都还没改）。只有容量类错误可能发生在动手之后
/// —— 参考在这些位置是 `List.Add`/`Dictionary.Add` 永远成功，内核是定容容器会满。
pub fn build_fight(
    state: &mut CombatState,
    content: &Content<'_>,
    plan: &FightPlan<'_>,
) -> Result<(), BattleError> {
    // ── 步 0：纯校验（**一个字节都不改 `state`**）==============================
    // 参考在第 1 步新建一份状态、错了就抛；内核的存储是调用方的，所以先做的检查越多，
    // "建到一半的局"这种参考实现里不存在的状态就越不可能出现。
    let combat_id = CombatId::new(plan.combat_id)?;
    let hero_id = CombatantId::new(plan.hero.id)?;
    for enemy in plan.enemies {
        // 只验不改：`add_combatant` 里再建一次（幂等、无副作用）。
        CombatantId::new(enemy.id)?;
    }
    // 步 6 的判定（`MoveInnateCardsToTop`）：参考的**挪牌**必须在洗牌之后（`:45-47`），
    // 但**判定**没有顺序依赖 ⇒ 提前到这里，失败时 state 还是干净的。
    reject_innate_deck(content, plan)?;
    // 蓝图里那两个喂给回合机的旋钮（[`FROZEN_GAP_TURN_CONFIG`]）：拒绝兑现不了的蓝图，
    // 别等到"跑起来了但抽牌数是错的"。
    check_turn_knobs(plan)?;
    // 牌定义表（`:75`）。参考在这一步**不查**（它的注册表就是蓝图的一部分），
    // 内核的卡定义表**就是**镜像的 `CARD` 表，所以查不到必须响亮。
    for entry in plan.deck {
        if content.lookup_in(entry.card, EK_CARD).is_none() {
            return Err(BattleError::UnknownCard(CardDefinitionId::new(entry.card)?));
        }
    }

    // ── 步 1：`new CombatState(combatId, seed)`（`:13-17`）=====================
    // `CellExclusive` / `SimultaneousTeamTurns` 不进内核模型（规格 §1 的取舍），
    // 它们是**同时回合/格子战斗**的开关，v1 一个都不支持；蓝图里也没有这两个字段。
    *state = CombatState::new(combat_id, plan.seed);

    // ── 步 2：战斗员（`:19-24`）==============================================
    add_combatant(state, &hero_id, plan.hero.max_health, PLAYER_TEAM)?;
    for enemy in plan.enemies {
        let id = CombatantId::new(enemy.id)?;
        add_combatant(state, &id, enemy.max_health, ENEMY_TEAM)?;
    }

    // 英雄的开局资源（`:120-122` 的 `blueprint.Resources`）。蓝图只给一份，参考是**逐人**
    // 一份；本内核把它给英雄 —— 镜像里只有 `HeroResources` 这一格有内容
    // （`ENCT` 的 `HeroResources: [{Current:3, Max:3, standard.energy}]`，敌人那一侧没有）。
    for (resource, current, max) in plan.resources {
        state
            .combatant_mut(&hero_id)
            .ok_or(CapacityError::MissingCombatant)?
            .set_resource(*resource, *current, *max)?;
    }

    // ── 步 3：`SetActiveCombatant(hero)`（`:26`）==============================
    // `add_combatant` 已经把**第一个**加进去的设为活跃（`state.rs:1723-1725`），
    // 所以这一行今天恒等；照抄它是因为参考显式写了，而"活跃单位是谁"是这一步的语义。
    state.active_combatant_id = Some(hero_id);

    // ── 步 4：DealDeck（`:31`、`:67-77`）=====================================
    for entry in plan.deck {
        let definition = CardDefinitionId::new(entry.card)?;
        for _ in 0..entry.count {
            // `combat.CreateNextCardInstanceId()`（`:75`）：**先取号、再自增**
            // （`CombatState.cs:689-696`）。与 `exec.rs:1719-1723` 同形（那边也是"先读号、
            // 建实例、推号"），这样两张卡不可能是同一个 id。
            let number = state.next_card_instance_number;
            let instance = CardInstance::new(card_instance_id(number)?, definition);
            state.push_card(&hero_id, CardZone::DrawPile, instance)?;
            state.next_card_instance_number = number.saturating_add(1);
        }
    }

    // ── 步 5：ShuffleDrawPileOnStart（`:38-43`、`:81-89`）=====================
    if plan.shuffle_draw_pile_on_start {
        shuffle_draw_pile(state, &hero_id)?;
    }

    // ── 步 6：MoveInnateCardsToTop（`:45-49`、`:93-104`）—— **不支持** =========
    // 判定已经在步 0 做掉了（`reject_innate_deck`）。为什么"不支持"是响亮的：
    // 真有 innate 卡时，参考会在洗牌**之后**把它挪到堆顶 ⇒ 起手牌序不同，
    // 而那种偏差看起来完全正常（数字全都合理）。

    // ── 步 7/8：起始状态 / 开局临时规则（`:51-61`）============================
    // 两者都是"入队 + 排空"（要事件队列），而 `FightPlan` 里没有对应字段 ⇒ 恒为空。
    // 这正是规格 §1 要的"响亮拒绝"：字段不存在，调用方**写不出**一局带起始状态的战斗，
    // 所以这里不需要（也没有地方可以）说一句话。
    Ok(())
}

/// 加一个战斗员（`AddCombatant`，`ScenarioCombatFactory.cs:106-127`）。
///
/// 三条照抄的语义：
/// * `current = clamp(CurrentHealth ?? MaxHealth, 1, MaxHealth)`（`:109-110`）—— 蓝图没有
///   `CurrentHealth`，所以当前生命 = 最大生命；
/// * `definition_id = DefinitionId ?? Id`（`:114`）—— 蓝图没有 `DefinitionId`，所以取 id；
/// * 资源**不**在这里加（英雄那一份在 [`build_fight`] 里加，敌人没有）。
///
/// ⚠️ **偏离 D1（有意）**：`MaxHealth < 1` 时参考的 `Math.Clamp(v, 1, max)` **抛**
/// （`ArgumentException: min > max`）。内核把 `max` 抬到 1。理由：`BattleError` 没有
/// "蓝图不合法"的桶，而我不许改冻结类型；同时生产路径不许 panic。⇒ 一个 `max_health <= 0`
/// 的蓝图会得到 1/1 而不是报错。它与 `debug_assert!` 一起兜住"我这边的测试写错了"。
fn add_combatant(
    state: &mut CombatState,
    id: &CombatantId,
    max_health: i32,
    team: &str,
) -> Result<(), BattleError> {
    debug_assert!(max_health >= 1, "蓝图的 max_health 必须 >= 1（参考在这里会抛）");
    let max_health = max_health.max(1);
    let combatant = Combatant::new(
        *id,
        CombatantDefinitionId::new(id.as_str())?,
        TeamId::new(team)?,
        max_health,
        max_health,
    );
    state.add_combatant(combatant)?;
    Ok(())
}

/// 开局洗一次抽牌堆（`ShuffleDrawPile`，`ScenarioCombatFactory.cs:81-89`）。
///
/// 三条逐字照抄：
/// 1. `Count <= 1` ⇒ **什么都不做**，连 `random_step` 都不推（`:84-85`）；
/// 2. 置换来自 `CombatRandom.CreateShuffledIndexes(Count, RandomSeed, RandomStep)`（`:86`），
///    内核是 [`crate::rng::shuffle_indexes`]（与它逐位一致，已用 33,768 个下标对拍）；
/// 3. `AdvanceRandomStep()`（`:88`）—— **只在这条路径上**，这是"洗牌真的消耗了 RNG"的唯一
///    可观察证据（`step=` 行进哈希）。删掉它以后每一次后续随机都错位，而**没有任何测试会变红**
///    —— 除非有一条测试直接断言 `random_step`（`the_start_shuffle_advances_the_random_step_…`）。
///
/// `zones.ReorderDrawPile(order)`（`:87`）在内核里没有对应原语（`state.rs` 没有 `reorder`
/// 方法，而我不许改它）。这里用 `move_card(DrawPile → DrawPile, Bottom)` 逐张"挪到堆底"
/// 实现同一置换：按目标序**正序**挪，最后一张挪到最底下 ⇒ 堆顶就是 `order[0]`。
/// （`move_card` 的 `from == to` 是允许的，`state.rs:1985-1986` 写明它"在一堆内重排"。）
fn shuffle_draw_pile(state: &mut CombatState, owner: &CombatantId) -> Result<(), BattleError> {
    let mut slots = [0u16; MAX_CARDS_PER_ZONE];
    let count = {
        let Some(zones) = state.card_zones(owner) else {
            return Err(BattleError::Capacity(CapacityError::MissingCombatant));
        };
        let pile = zones.slots(CardZone::DrawPile);
        if pile.len() <= 1 {
            return Ok(()); // `:84-85`：0/1 张 ⇒ 不洗、不推 step
        }
        slots[..pile.len()].copy_from_slice(pile);
        pile.len()
    };

    let mut order = [0u8; MAX_CARDS_PER_ZONE];
    rng::shuffle_indexes(&mut order[..count], state.random_seed, state.random_step);

    // ⚠️ 必须**先快照槽位**再挪：`order` 是"旧下标"的置换，而每挪一次下标就变了。
    for index in order[..count].iter().copied() {
        let Some(&raw) = slots.get(usize::from(index)) else {
            // 不可达：`shuffle_indexes` 只吐 `0..count`，而 `count == 洗牌前的张数`。
            return Err(BattleError::Capacity(CapacityError::MissingCombatant));
        };
        state.move_card(
            owner,
            CardZone::DrawPile,
            CardZone::DrawPile,
            CardSlot::from_index(raw),
            ZonePlacement::Bottom,
        )?;
    }
    state.random_step += 1; // `:88` `AdvanceRandomStep()`
    Ok(())
}

/// 拒绝"牌组里有 innate 卡"的蓝图（`MoveInnateCardsToTop`，`:45-49`、`:93-104`）。
///
/// 参考在开局把带 `innate` tag 的牌挪到抽牌堆顶上，好让**起手必有它**。本内核 v1 没有
/// "按 tag 挑牌"的能力，而"静默不挪"的后果是**开局手牌本身就不对**（少一张、顺序不同）
/// —— 那是最难发现的一种错（数字全都合理）。所以只要蓝图里有一张 innate 卡就拒绝。
///
/// 判据是**镜像**（牌的 tag 只有镜像说了算），不是蓝图。
/// 实测今天不可达：`innate` 这个串**不在** core 镜像的串池里，62/62 卡的 `Tags` 都没有它
/// （测试 `no_card_in_the_image_is_innate_today` 钉住，且成对断言 tag 读取器**不是**恒假）。
fn reject_innate_deck(content: &Content<'_>, plan: &FightPlan<'_>) -> Result<(), BattleError> {
    for entry in plan.deck {
        match card_has_tag(content, entry.card, INNATE_TAG) {
            Ok(false) => {}
            Ok(true) => return Err(unsupported()),
            Err(()) => return Err(content_error()),
        }
    }
    Ok(())
}

/// 蓝图里那两个"喂给回合机"的旋钮必须与 [`standard_turn_config`] 一致（见
/// [`FROZEN_GAP_TURN_CONFIG`]）。
///
/// 为什么**拒**而不是"照蓝图跑"：`run_fight` 收不到 `FightPlan`，它只能用标准包那一组数字。
/// 于是"蓝图说抽 7 张、实际抽 5 张"会安静地发生 —— 而安静是这里最不能接受的失败。
fn check_turn_knobs(plan: &FightPlan<'_>) -> Result<(), BattleError> {
    if plan.cards_drawn_per_turn != CARDS_DRAWN_PER_TURN {
        return Err(unsupported());
    }
    // 参考的 `RefillResourceOnTurnStartedHandler` 是**一个**处理器、一个资源、补到 3
    // （`StandardCombatPackage.cs:124`）。蓝图给空表 = "不补"，那也是 run_fight 兑现不了的。
    let [only] = plan.turn_start_refills else {
        return Err(unsupported());
    };
    if only.0.as_str() != ENERGY || only.1 != ENERGY_REFILL {
        return Err(unsupported());
    }
    Ok(())
}

// =============================================================================================
// 卡实例 id（与 `exec.rs` 的 `card_instance_id` 同形）
// =============================================================================================

/// `card_%06d`（`CombatState.cs:689-696`：`$"card_{NextCardInstanceNumber:000000}"`）。
///
/// ⚠️ 这里**抄了一份** `exec.rs:1979-1983` 的实现（连同它的 `numbered_instance_text`）。
/// 抄的理由与代价：`exec.rs` 里的那两个是私有的，而本轮只准改 `battle.rs`。
/// 将来若把它提升成 `content`/`state` 级的公共函数，这一份应当删掉 —— 两份实现漂移的
/// 后果是"同一局里造出来的卡有两种 id 拼法"，那会让指纹对不上却查不出原因。
fn card_instance_id(number: i32) -> Result<CardInstanceId, BattleError> {
    let mut buffer = [0u8; INSTANCE_TEXT_CAP];
    let text = numbered_instance_text(CARD_ID_PREFIX, number, &mut buffer)?;
    Ok(CardInstanceId::new(text)?)
}

/// `<prefix>%06d` 的**零分配**版（`format!` 在 `no_std` 里没有）。
///
/// 逐字对应 C# 的 `$"{prefix}{number:000000}"`。负数在参考里不可能出现（生成器从 1 开始），
/// 真出现时按 **0** 写。与 `exec.rs:2132-2176` 逐行相同（含每处越界的报错而非截断）。
fn numbered_instance_text<'b>(
    prefix: &[u8],
    number: i32,
    buffer: &'b mut [u8; INSTANCE_TEXT_CAP],
) -> Result<&'b str, BattleError> {
    let mut digits = [b'0'; 12];
    let mut len = 0usize;
    let mut value = if number < 0 { 0u32 } else { number as u32 };
    loop {
        let Some(slot) = digits.get_mut(len) else {
            return Err(unsupported());
        };
        *slot = b'0' + (value % 10) as u8;
        len += 1;
        value /= 10;
        if value == 0 {
            break;
        }
    }
    while len < 6 {
        let Some(slot) = digits.get_mut(len) else {
            return Err(unsupported());
        };
        *slot = b'0';
        len += 1;
    }

    let Some(head) = buffer.get_mut(..prefix.len()) else {
        return Err(unsupported());
    };
    head.copy_from_slice(prefix);
    for index in 0..len {
        let Some(slot) = buffer.get_mut(prefix.len() + index) else {
            return Err(unsupported());
        };
        let Some(digit) = digits.get(len - 1 - index) else {
            return Err(unsupported());
        };
        *slot = *digit;
    }
    let total = prefix.len().checked_add(len).ok_or_else(unsupported)?;
    let bytes = buffer.get(..total).ok_or_else(unsupported)?;
    core::str::from_utf8(bytes).map_err(|_| unsupported())
}

/// 卡的 `Tags` 里有没有 `tag`。
///
/// 形状是**实测**的（`play.rs:742-788` 有一份同形的，`exec.rs` 里还有一份）：
/// 格是 `F_TERM` → `_arr` → 唯一字段是 `F_TERMLIST`，AUX 里装 term id，每个元素是
/// `_wrap_lower`（op 6），tag 串在那个 term 的槽 0。
///
/// 三个"不是错误"的分支照 `exec.rs:1838-1841`：定义不在 `CARD` 表 / 格是哨兵 / 列表里没有。
/// `Err(())` = 那一格**读不出来**（结构坏了）—— 调用方把它变成 `HostFailure::Content`，
/// 绝不当成"没有这个 tag"（那会让 `innate` 检查静默失效）。
fn card_has_tag(content: &Content<'_>, definition: &str, tag: &str) -> Result<bool, ()> {
    let Some(entry) = content.lookup_in(definition, EK_CARD) else {
        return Ok(false);
    };
    let Some(row) = content.card(u32::from(entry.index)) else {
        return Ok(false);
    };
    let view = row.row();
    let Some(cell) = view.cell_index("Tags") else {
        return Err(());
    };
    if view.cell_kind(cell) != Some(F_TERM) {
        return Err(());
    }
    let list_id = match row.tags() {
        ABSENT16 | NULL16 => return Ok(false),
        id => id,
    };
    let list = content.term(list_id).ok_or(())?;
    if list.op != OP_ARR {
        return Err(());
    }
    let start = list.slot(0).ok_or(())?;
    let count = list.slot(1).ok_or(())?;
    if count == LIST_ABSENT || count == LIST_NULL {
        return Ok(false);
    }
    for index in 0..count {
        let cell = start.checked_add(index).ok_or(())?;
        let element = content.aux(cell).ok_or(())?;
        let element_term = content.term(element).ok_or(())?;
        if element_term.op != OP_WRAP_LOWER {
            return Err(());
        }
        let string = element_term.slot(0).ok_or(())?;
        if content.string(string) == Some(tag) {
            return Ok(true);
        }
    }
    Ok(false)
}

// =============================================================================================
// 跑脚本
// =============================================================================================

/// 一步的"执行前上下文"（参考的 `StepContext`，去掉 actor —— 它只用于 trace）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Context {
    round: i32,
    turn: i32,
}

/// 一步之内的观测收集器。
///
/// 参考每步 `new List<string>()`；内核这边是定长数组 + 计数，满了就
/// [`BattleError::TooManyProblems`]（绝不截断 —— 截断会让"撞了信封"看起来像"只记了 32 条"）。
#[derive(Clone, Copy, Debug)]
struct Problems {
    slots: [Problem; MAX_PROBLEMS_PER_STEP],
    count: usize,
}

impl Problems {
    const fn new() -> Self {
        Self {
            slots: [Problem::CombatAlreadyEnded; MAX_PROBLEMS_PER_STEP],
            count: 0,
        }
    }

    fn push(&mut self, problem: Problem) -> Result<(), BattleError> {
        let Some(slot) = self.slots.get_mut(self.count) else {
            return Err(BattleError::TooManyProblems);
        };
        *slot = problem;
        self.count += 1;
        Ok(())
    }
}

/// 跑一串脚本步。
///
/// 每一步的顺序照 `ScenarioRunner.Run`：取上下文 → 判断终态/英雄倒下 → 执行 →
/// 记录这一步的问题。**任何一步的 `Problem` 都不中断循环**（参考就是这么做的）。
///
/// # 外壳逐行（`ScenarioRunner.cs:32-68`）
///
/// ```text
/// :36  problems = new List
/// :40  Result != Ongoing            → CombatAlreadyEnded，这一步**不执行**
/// :45  英雄不在 / 已倒下             → HeroDowned，这一步**不执行**
/// :52  否则 ExecuteStep(...)；异常被捕获成 StepThrew（`:57-62`）
/// :66  记 (i, step, round, turn, actor, intent, trace, problems)
/// ```
///
/// 两条易错点，都由测试钉住：
/// * **`round`/`turn` 记的是执行前**（`:106`、`:140`、`:164`、`:203` 都在动作之前构造
///   `StepContext`）—— 所以"这一步把回合推到了 2"记下来的仍然是 1；
/// * `CombatAlreadyEnded` / `HeroDowned` 是"**这一步不执行**"，不是"提前退出循环"：
///   剩下的步照样走一遍、各记一条（`:40-51` 在 `for` 体内，没有任何 `break`）。
///
/// # Errors
///
/// 只有驱动层自己坏了才 `Err`：步数超 [`MAX_STEPS`] ⇒ [`BattleError::TooManySteps`]；
/// 一步的问题超 [`MAX_PROBLEMS_PER_STEP`] ⇒ [`BattleError::TooManyProblems`]；以及
/// `build_fight` 那一组（不会在这里出现）。
///
/// ⚠️ **一步里抛出来的东西不算 `Err`**：参考把它们 catch 成 [`Problem::StepThrew`]
/// 然后继续（`:52-63`）。本模块照抄 —— 所以回合机/出牌/敌人动作的 `TurnError`/`PlayError`
/// 都会变成一条 `StepThrew`，而**不是**函数返回值。这与本文件顶部那份冻结文档里
/// "回合机/出牌真的报错"读起来不一样：规格书 `docs/spec/fight-driver.md` §2 第 4 条
/// （"抛出的异常被捕获成 `StepThrew`"）才是权威，`Problem::StepThrew` 这个变体存在
/// 也只在那种读法下有意义。
pub fn run_fight<H: TurnHost>(
    state: &mut CombatState,
    content: &Content<'_>,
    steps: &[Step<'_>],
    host: &mut H,
    out: &mut FightOutcome,
) -> Result<(), BattleError> {
    if steps.len() > MAX_STEPS {
        return Err(BattleError::TooManySteps);
    }
    let config = standard_turn_config()?;
    let hero = hero_of(state);
    *out = FightOutcome::new();
    out.step_count = steps.len();

    for index in 0..steps.len() {
        let Some(step) = steps.get(index).copied() else {
            return Err(BattleError::TooManySteps); // 不可达：`index < steps.len()`
        };
        let mut problems = Problems::new();

        // ── 执行前的三道门（`:40-63`）。**注意没有任何 `break`**：不执行的步也占一个位置。
        let context = if state.result != CombatResult::Ongoing {
            // `:40-44`
            problems.push(Problem::CombatAlreadyEnded)?;
            context_of(state)
        } else if !hero.as_ref().is_some_and(|id| turn::is_alive(state, id)) {
            // `:45-51`：英雄不在（`hero_of` 推不出来）或已倒下，都是这一条 —— 一字不差照抄。
            problems.push(Problem::HeroDowned)?;
            context_of(state)
        } else {
            let hero = hero.as_ref();
            match execute_step(state, content, &config, &step, host, hero, &mut problems) {
                Ok(context) => context,
                // 信封错误不许被吞成 StepThrew：那会把"问题记不下了"伪装成"这一步抛了"。
                Err(BattleError::TooManyProblems) => return Err(BattleError::TooManyProblems),
                // `:57-62`：异常 → 一条问题 + **当下的**上下文（`:61`），循环继续。
                Err(_) => {
                    problems.push(Problem::StepThrew)?;
                    context_of(state)
                }
            }
        };

        // 参考在 `CombatantLifecycleChanged` 上算胜负（`CombatStateEffects.cs:28-60`）。
        // 本内核没有事件队列 ⇒ 在步边界补（[`FROZEN_GAP_RESULT`]，含代价说明）。
        settle_result(state);

        let count = problems.count;
        out.steps[index] = StepOutcome {
            round: context.round,
            turn: context.turn,
            problems: u8::try_from(count).unwrap_or(u8::MAX),
        };
        out.problems[index] = problems.slots;
    }

    out.result = state.result;
    Ok(())
}

/// 当下的上下文（参考 `new StepContext(combat.CurrentRound, combat.CurrentTurn, …)`）。
fn context_of(state: &CombatState) -> Context {
    Context {
        round: state.current_round,
        turn: state.current_turn,
    }
}

/// [`Step::HeroPlays`] 的两个字段，打包成一个参数。
///
/// 只为一件事：把 `hero_plays` 的参数个数压到 clippy 的 `too_many_arguments` 门槛以下
/// （7）。参数一多，调用点就会开始出现"第 4 个 `&str` 到底是卡还是目标"这种错。
#[derive(Clone, Copy, Debug)]
struct Play<'a> {
    card: &'a str,
    target: Option<&'a str>,
}

/// [`Step::EnemyActs`] 的三个字段，打包的理由同 [`Play`]。
#[derive(Clone, Copy, Debug)]
struct EnemyMove<'a> {
    enemy: &'a str,
    action: &'a str,
    target: Option<&'a str>,
}

/// 按 `Step` 分派（`ExecuteStep`，`ScenarioRunner.cs:75-87`）。
fn execute_step<H: TurnHost>(
    state: &mut CombatState,
    content: &Content<'_>,
    config: &TurnConfig,
    step: &Step<'_>,
    host: &mut H,
    hero: Option<&CombatantId>,
    problems: &mut Problems,
) -> Result<Context, BattleError> {
    match *step {
        Step::HeroPlays { card, target } => hero_plays(
            state,
            content,
            config,
            Play { card, target },
            host,
            hero,
            problems,
        ),
        Step::HeroEndsTurn => hero_ends_turn(state, config, host, hero, problems),
        Step::EnemyActs {
            enemy,
            action,
            target,
        } => enemy_acts(
            state,
            content,
            config,
            EnemyMove {
                enemy,
                action,
                target,
            },
            host,
            hero,
            problems,
        ),
        Step::NextRound => next_round(state, config, host, hero, problems),
    }
}

/// `ExecuteHeroPlays`（`ScenarioRunner.cs:95-128`）。
fn hero_plays<H: TurnHost>(
    state: &mut CombatState,
    content: &Content<'_>,
    config: &TurnConfig,
    play: Play<'_>,
    host: &mut H,
    hero: Option<&CombatantId>,
    problems: &mut Problems,
) -> Result<Context, BattleError> {
    let Play { card, target } = play;
    // 到这里英雄一定在、而且活着（外壳已经查过）。`None` 只为"没有 panic 路径"存在。
    let Some(hero) = hero.copied() else {
        problems.push(Problem::HeroDowned)?;
        return Ok(context_of(state));
    };

    // `:102-103`：行动者不是英雄 ⇒ 记一条，**但继续**（参考没有 return）。
    if state.active_combatant_id.as_ref() != Some(&hero) {
        problems.push(Problem::NotHeroTurn)?;
    }

    // `:105` `EnsureTurnStarted`：只在"进行中 + 还没开始这一回合"时才开。
    ensure_turn_started(state, config, host)?;
    // `:106`：上下文在 EnsureTurnStarted **之后**、动作**之前**取。
    // （`StartCurrentTurn` 不改 `CurrentRound`/`CurrentTurn`，所以与"步首取值"等价；
    //  但改成"动作之后"就会把本步推出来的回合算进来 —— 那是错的。）
    let context = context_of(state);

    // `:109-111`：按**卡定义 id** 在手牌里找**第一张**。
    // ⚠️ 找不到 ≠ 定义不存在：这里只查手牌，不查内容注册表（参考也不查）。
    let Some(instance) = first_card_in_hand(state, &hero, card) else {
        problems.push(Problem::CardNotInHand)?; // `:113-117`
        return Ok(context);
    };

    // `:121-122`：入队 + 排空。内核没有队列，走**请求面**（拒绝 = no-op）：
    // 参考的请求面对"不合格"的处理正是 no-op（`play.rs:437-460`），no-op 之后才记 `:124`。
    let request = PlayRequest::new(hero, instance, parse_target(target)?);
    let report = play::try_play_card(state, Some(content), &request)?;
    if !report.played {
        problems.push(Problem::CardNotPlayed)?; // `:124-125`
    }
    Ok(context)
}

/// `ExecuteHeroEndsTurn`（`ScenarioRunner.cs:130-146`）。
fn hero_ends_turn<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
    hero: Option<&CombatantId>,
    problems: &mut Problems,
) -> Result<Context, BattleError> {
    // `:132-133`：记一条，但**继续**（参考没有 return）。
    if hero.is_none_or(|id| state.active_combatant_id.as_ref() != Some(id)) {
        problems.push(Problem::NotHeroTurnToEnd)?;
    }

    ensure_turn_started(state, config, host)?; // `:139`
    let context = context_of(state); // `:140`（在推进之前！）

    // `:141-143`：开回合本身可能结束战斗（"turn-start 触发器打死最后一个敌人"），
    // 那就**不要**在结束了的战斗上推回合。
    if state.result == CombatResult::Ongoing {
        turn::end_current_turn_and_start_next(state, config, host)?; // `:144`
    }
    Ok(context)
}

/// `ExecuteEnemyActs`（`ScenarioRunner.cs:148-194`）。
///
/// 六个早退分支的顺序**就是语义**（`:157` → `:163` → `:166` → `:172` → `:178` → `:184`），
/// 换一个顺序就会给出另一条问题 —— 例如"敌人不存在"必须排在"推回合"前面。
fn enemy_acts<H: TurnHost>(
    state: &mut CombatState,
    content: &Content<'_>,
    config: &TurnConfig,
    mov: EnemyMove<'_>,
    host: &mut H,
    hero: Option<&CombatantId>,
    problems: &mut Problems,
) -> Result<Context, BattleError> {
    let EnemyMove {
        enemy,
        action,
        target,
    } = mov;
    let enemy_id = CombatantId::new(enemy)?;

    // `:157-161`：敌人不存在（**不是**"已倒下"）⇒ 直接返回。
    if state.combatant(&enemy_id).is_none() {
        problems.push(Problem::NoSuchEnemy)?;
        return Ok(context_of(state));
    }

    // `:163`：一个回合一个回合地结束，直到轮到它（每一跳都真的走 turn-start）。
    advance_turns_until_active(state, config, host, &enemy_id, hero, problems)?;
    let context = context_of(state); // `:164`（在推进**之后**、动作**之前**）

    // `:166-170`：推进过程中把战斗打完了。
    if state.result != CombatResult::Ongoing {
        problems.push(Problem::CombatEndedBeforeEnemy)?;
        return Ok(context);
    }
    // `:172-176`：推不到（turn order 没绕到它）。
    if state.active_combatant_id.as_ref() != Some(&enemy_id) {
        problems.push(Problem::CannotReachEnemyTurn)?;
        return Ok(context);
    }
    // `:178-182`：它是当前行动者，但已经倒下 ⇒ 动作跳过（英雄不掉血）。
    if !turn::is_alive(state, &enemy_id) {
        problems.push(Problem::EnemyNotAlive)?;
        return Ok(context);
    }
    // `:184-189`：动作没注册（内核的动作库**就是**镜像的 `EACT` 表）。
    let Some(entry) = content.lookup_in(action, EK_EACTION) else {
        problems.push(Problem::UnknownEnemyAction)?;
        return Ok(context);
    };
    // `:191-192`：入队 + 排空 ⇒ 内核就地执行（`intent::execute_action` 与参考同一个执行器）。
    intent::execute_action(
        state,
        content,
        &enemy_id,
        u32::from(entry.index),
        parse_target(target)?,
    )
    .map_err(intent_failure)?;
    Ok(context)
}

/// `IntentError` → `BattleError` 的**类别**映射。
///
/// `BattleError` 没有 intent 的桶（它只有 `Turn` / `Play` 两个领域桶），而本模块不许改冻结类型。
/// ⇒ 两类分开：
///
/// * **内核缺能力**（`UnsupportedCondition` / `Exec(UnsupportedNode)`）⇒ [`unsupported`]；
/// * 其余（镜像读不出、串不认识、`IDX` 里解析不到行）⇒ [`content_error`]。
///
/// ⚠️ 这个分类在外壳里**会被合并**：两者都会变成一条 [`Problem::StepThrew`]（参考也是
/// "任何异常都记成一条"）。也就是说"为什么抛"这条信息在 `no_std` 侧的观测里**丢了** ——
/// 这是 [`Problem`] 没有载荷的代价（规格 §3.3 只比类别与条数）。
fn intent_failure(error: intent::IntentError) -> BattleError {
    match error {
        intent::IntentError::UnsupportedCondition(_) => unsupported(),
        intent::IntentError::Exec(crate::exec::ExecError::UnsupportedNode) => unsupported(),
        _ => content_error(),
    }
}

/// `ExecuteNextRound`（`ScenarioRunner.cs:196-222`）。
fn next_round<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
    hero: Option<&CombatantId>,
    problems: &mut Problems,
) -> Result<Context, BattleError> {
    ensure_turn_started(state, config, host)?; // `:202`
    let context = context_of(state); // `:203`（在推进之前！）

    // `:206-207`：已经是英雄的回合 ⇒ 先结束它，这样"一整轮"才真的过去。
    let hero_active = hero.is_some_and(|id| state.active_combatant_id.as_ref() == Some(id));
    if hero_active && state.result == CombatResult::Ongoing {
        turn::end_current_turn_and_start_next(state, config, host)?;
    }

    // `:209-219`：只要还在进行中且行动者不是英雄，就一直结束+开始下一个。
    // `guard > TurnOrder.Count + 2` ⇒ 记一条并停（没有这个上限，一个"永远把下一个单位
    // 打死"的触发器会让这里转不出来）。
    let mut guard = 0i32;
    let max_steps = state.turn_order().len() as i32 + 2;
    while state.result == CombatResult::Ongoing
        && hero.is_none_or(|id| state.active_combatant_id.as_ref() != Some(id))
    {
        turn::end_current_turn_and_start_next(state, config, host)?;
        guard += 1;
        if guard > max_steps {
            problems.push(Problem::CouldNotWrapToHero)?; // `:216`
            break;
        }
    }
    Ok(context)
}

/// `AdvanceTurnsUntilActive`（`ScenarioRunner.cs:226-252`）。
///
/// **英雄的回合不替他了结**（`:239-243`）：驱动层不是玩家，替英雄结束回合会造出
/// 参考实现里不存在的时序。所以轮到英雄时只记一条问题就放弃。
fn advance_turns_until_active<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
    target: &CombatantId,
    hero: Option<&CombatantId>,
    problems: &mut Problems,
) -> Result<(), BattleError> {
    ensure_turn_started(state, config, host)?; // `:233`

    let mut guard = 0i32;
    let max_steps = state.turn_order().len() as i32 + 1; // `:236`（注意是 +1，不是 +2）
    while state.result == CombatResult::Ongoing && state.active_combatant_id.as_ref() != Some(target)
    {
        // `:239-243`：轮到英雄 ⇒ 记一条"这仍然是英雄的回合"并放弃。
        // ⚠️ 参考这条与 `:248` 那条是**两条不同的问题**，内核只有一个桶（[`FROZEN_GAP_PROBLEM`]）。
        if hero.is_some_and(|id| state.active_combatant_id.as_ref() == Some(id)) {
            problems.push(Problem::CannotReachEnemyTurn)?;
            return Ok(());
        }
        turn::end_current_turn_and_start_next(state, config, host)?; // `:245`
        guard += 1;
        if guard > max_steps {
            problems.push(Problem::CannotReachEnemyTurn)?; // `:248`
            return Ok(());
        }
    }
    Ok(())
}

/// `EnsureTurnStarted`（`ScenarioRunner.cs:254-258`）。
///
/// 只在**还在进行中**且**阶段停在"等待开始"**时才开 —— 已经开始的回合再开一次，
/// 参考的 `MarkTurnStarted` 会抛（`CombatState.cs:324-330`）。
fn ensure_turn_started<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
) -> Result<(), TurnError> {
    if state.result == CombatResult::Ongoing && state.turn_phase == CombatTurnPhase::WaitingToStartTurn
    {
        turn::start_current_turn(state, config, host)?;
    }
    Ok(())
}

/// 手上的第一张该定义的卡（参考 `GetCardsInZone(Hand).FirstOrDefault(card.DefinitionId == …)`）。
///
/// 顺序是**手牌顺序**（`zones.slots(Hand)` 的堆序），所以"第一张"是可复现的。
fn first_card_in_hand(
    state: &CombatState,
    owner: &CombatantId,
    definition: &str,
) -> Option<CardInstanceId> {
    let slots = state.card_zones(owner)?.slots(CardZone::Hand);
    for raw in slots {
        let slot = CardSlot::from_index(*raw);
        let Some(card) = state.card(slot) else {
            continue; // 不可达：牌区的槽位一定指向池里的实例
        };
        if card.definition_id.as_str() == definition {
            return Some(card.id);
        }
    }
    None
}

/// 英雄是谁：回合序里**第一个** `team_id == "player"` 的单位（[`FROZEN_GAP_HERO_ID`]）。
///
/// 推不出来 ⇒ `None`，`run_fight` 于是每步记 [`Problem::HeroDowned`] —— 那正是参考在
/// "英雄不在状态里"时走的分支（`:45-51`），不是错误。
fn hero_of(state: &CombatState) -> Option<CombatantId> {
    state
        .turn_order()
        .iter()
        .copied()
        .find(|id| hero_team_matches(state, id))
}

/// 这个单位是不是"玩家队"的（`HasLivingCombatantsOnTeam(PlayerTeam)` 的判据那一半）。
fn hero_team_matches(state: &CombatState, id: &CombatantId) -> bool {
    state
        .combatant(id)
        .is_some_and(|c| c.team_id.as_str() == PLAYER_TEAM)
}

/// 算胜负（`UpdateStandardCombatResultOnLifecycleChangedHandler`，`CombatStateEffects.cs:28-60`）。
///
/// 逐行：
/// ```text
/// :36  Result != Ongoing            → return（只在"还没结束"时算）
/// :39  hasLivingPlayer = 玩家队还有活人
/// :41  hasLivingEnemy  = 敌人队还有活人
/// :43  两者都没有                    → Draw
/// :49  没有玩家                      → Defeat
/// :55  没有敌人                      → Victory
/// ```
///
/// ⚠️ 这是本模块**唯一**一处"做了引擎该做的事"，理由与粒度代价见 [`FROZEN_GAP_RESULT`]。
/// 它在**每一步之后**被调一次；步内不调（参考的判决要等队列排空，而"一张牌的程序跑完"
/// 就是一次排空 ⇒ 对单步 = 打一张牌是可观察等价的）。
fn settle_result(state: &mut CombatState) {
    if state.result != CombatResult::Ongoing {
        return; // `:36-37`
    }
    let mut player_alive = false;
    let mut enemy_alive = false;
    for combatant in state.combatants() {
        if combatant.lifecycle_state != CombatantLifecycleState::Alive {
            continue;
        }
        if combatant.team_id.as_str() == PLAYER_TEAM {
            player_alive = true;
        } else if combatant.team_id.as_str() == ENEMY_TEAM {
            enemy_alive = true;
        }
    }
    if !player_alive && !enemy_alive {
        state.result = CombatResult::Draw; // `:43-47`
    } else if !player_alive {
        state.result = CombatResult::Defeat; // `:49-53`
    } else if !enemy_alive {
        state.result = CombatResult::Victory; // `:55-58`
    }
}

/// 脚本里的目标 id → [`CombatantId`]（参考的 `ParseTarget`，`:263-264`）。
///
/// `None` 原样传下去（**没有目标是合法的**，不是错误）。参考的 `CombatantId` 没有长度上限，
/// 内核的 `Ident<40>` 有 ⇒ 超了就是 `Capacity`，由外壳记成 [`Problem::StepThrew`]。
fn parse_target(target: Option<&str>) -> Result<Option<CombatantId>, BattleError> {
    match target {
        None => Ok(None),
        Some(id) => Ok(Some(CombatantId::new(id)?)),
    }
}

/// 建好战斗 + 跑完脚本，一步到位（测试与 CLI 的主入口）。
///
/// # Errors
///
/// 见 [`build_fight`] 与 [`run_fight`]。
pub fn play_out<H: TurnHost>(
    state: &mut CombatState,
    content: &Content<'_>,
    plan: &FightPlan<'_>,
    steps: &[Step<'_>],
    host: &mut H,
    out: &mut FightOutcome,
) -> Result<(), BattleError> {
    build_fight(state, content, plan)?;
    run_fight(state, content, steps, host, out)
}

/// 蓝图里英雄的 id 是不是这个（参考的驱动层到处要它）。
#[must_use]
pub fn is_hero(plan: &FightPlan<'_>, id: &CombatantId) -> bool {
    id.as_str() == plan.hero.id
}

// =============================================================================================
// 测试
//
// 全部**接真实镜像**（`tools/contentc/out/content.core.rdcf`）。镜像不在仓库里（它是构建
// 产物），所以找不到就 panic 并打印路径与生成命令 —— 产物缺席时安静通过的测试等于没有测试。
//
// 用的卡与敌人都是镜像里真有的（`paper_cut` / `permit_a38` / `queue_imp` /
// `queue_imp.desk_jab`），血量是蓝图author 的（参考的蓝图也这么写）。
// =============================================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hash::{sha256, to_hex_lower};
    use crate::host::Host;
    use crate::snapshot;
    use crate::writer::TextWriter;

    const CORE_IMAGE_REL: &str = "../../tools/contentc/out/content.core.rdcf";

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

    /// 状态的逐字节指纹（`snapshot::write_hash_input` + SHA-256）。
    ///
    /// 缓冲 1 MiB：状态 171 KB，规范文本比它小得多（实测一局结束约 3 KB）。
    /// 溢出**必须**响亮 —— 一个被截断的指纹看起来仍然像一个指纹。
    fn state_hash(state: &CombatState) -> String {
        hash_text(state, false)
    }

    /// 去掉 `seed=` 那一行之后的指纹。
    ///
    /// 为什么要它：`seed=` 是规范文本的一行（`snapshot.rs:147`），所以"换个种子"**必然**
    /// 改变字节 —— 哪怕引擎一次随机数都没抽。要测"不洗牌 ⇒ 换种子什么都不该改变"就必须
    /// 把这一行排除掉，否则测的只是"指纹里有 seed 这一行"。
    fn layout_hash(state: &CombatState) -> String {
        hash_text(state, true)
    }

    fn hash_text(state: &CombatState, drop_seed_line: bool) -> String {
        let mut buf = vec![0u8; 1 << 20];
        let text = {
            let mut w = TextWriter::new(&mut buf);
            snapshot::write_hash_input(&mut w, state);
            assert!(!w.overflowed(), "指纹缓冲不够大");
            assert!(!w.is_empty(), "指纹不能是空的");
            w.as_str().to_string()
        };
        let text = if drop_seed_line {
            text.lines()
                .filter(|line| !line.starts_with("seed="))
                .map(|line| format!("{line}\n"))
                .collect::<String>()
        } else {
            text
        };
        assert!(text.contains("turn_order="), "去掉 seed 之后也得还剩东西");
        let digest = sha256(text.as_bytes());
        let mut hex = [0u8; 64];
        to_hex_lower(&mut hex, &digest);
        String::from_utf8(hex.to_vec()).expect("hex 是 ASCII")
    }

    fn cid(s: &str) -> CombatantId {
        CombatantId::new(s).expect("测试用的 id 都短")
    }

    fn energy() -> ResourceId {
        ResourceId::new("standard.energy").expect("常量串")
    }

    /// `turn_start_refills` 的标准那一份（`StandardCombatPackage.cs:124`）。
    fn refills() -> [(ResourceId, i32); 1] {
        [(energy(), ENERGY_REFILL)]
    }

    /// `resources` 的标准那一份（镜像 `ENCT.HeroResources: Current 3 / Max 3`）。
    fn resources() -> [(ResourceId, i32, Option<i32>); 1] {
        [(energy(), 3, Some(3))]
    }

    /// 一局观测的扁平结果（测试断言要的是这个形状，不是 `FightOutcome` 的并行数组）。
    struct Trace {
        /// 每步**之后**的状态指纹。
        hashes: Vec<String>,
        /// 每步**之后**去掉 `seed=` 那一行的指纹（见 [`layout_hash`]）。
        layouts: Vec<String>,
        /// 每步的执行前上下文与问题条数。
        steps: Vec<StepOutcome>,
        /// 每步的问题清单。
        problems: Vec<Vec<Problem>>,
        /// 每步**之后**的 `(id, 当前生命)` 快照，按回合序。
        health: Vec<Vec<(String, i32)>>,
        /// 最后一步之后的结果。
        result: CombatResult,
    }

    impl Trace {
        fn kinds(&self, index: usize) -> &[Problem] {
            self.problems.get(index).map_or(&[], |p| p.as_slice())
        }

        /// 第 `step` 步**之后**某人剩多少血（找不到 ⇒ -1）。
        ///
        /// ⚠️ 别在 `drive` 之后直接读 `state`：那时脚本已经全跑完了。中间态只能从这里取 ——
        /// 这个坑踩过一次（"步 0 一滴血都不该掉"断言读到的是最后一步之后的血量）。
        fn hp(&self, step: usize, who: &str) -> i32 {
            self.health.get(step).map_or(-1, |snapshot| {
                snapshot
                    .iter()
                    .find(|(id, _)| id == who)
                    .map_or(-1, |(_, hp)| *hp)
            })
        }
    }

    /// 建战斗 → 一步一调 `run_fight` → 每步之后取指纹与血量快照。
    ///
    /// **为什么一步一调**：`FightOutcome` 没有"游标"字段，所以"每步之后的指纹"只能靠
    /// 把同一步的切片再传一次来取。这不改变语义：外壳每一步都重新读 `result` / 英雄状态，
    /// 所以 N 次 1 步调用与 1 次 N 步调用给出**逐字节相同**的状态（确定性测试就靠这条）。
    fn drive(
        state: &mut CombatState,
        content: &Content<'_>,
        plan: &FightPlan<'_>,
        script: &[Step<'_>],
        host: &mut Host<'_>,
    ) -> Trace {
        build_fight(state, content, plan).expect("蓝图与镜像必须一致");
        let mut trace = Trace {
            hashes: Vec::with_capacity(script.len()),
            layouts: Vec::with_capacity(script.len()),
            steps: Vec::with_capacity(script.len()),
            problems: Vec::with_capacity(script.len()),
            health: Vec::with_capacity(script.len()),
            result: CombatResult::Ongoing,
        };
        for step in script {
            let mut out = FightOutcome::new();
            run_fight(state, content, core::slice::from_ref(step), host, &mut out)
                .expect("步进本身不该坏");
            assert_eq!(out.step_count, 1, "一次喂一步");
            let outcome = out.step(0).expect("第 0 步必须有观测");
            trace.hashes.push(state_hash(state));
            trace.layouts.push(layout_hash(state));
            trace.problems.push(out.problems_of(0).to_vec());
            trace.health.push(
                state
                    .turn_order()
                    .iter()
                    .map(|id| {
                        (
                            id.as_str().to_string(),
                            state.combatant(id).map_or(-1, |c| c.health_current),
                        )
                    })
                    .collect(),
            );
            trace.steps.push(outcome);
            trace.result = out.result;
        }
        trace
    }

    fn health(state: &CombatState, who: &str) -> i32 {
        state
            .combatant(&cid(who))
            .map_or(-1, |c| c.health_current)
    }

    fn lifecycle(state: &CombatState, who: &str) -> CombatantLifecycleState {
        state
            .combatant(&cid(who))
            .map_or(CombatantLifecycleState::Removed, |c| c.lifecycle_state)
    }

    fn zone_count(state: &CombatState, who: &str, zone: CardZone) -> usize {
        state.card_zones(&cid(who)).map_or(0, |z| z.count(zone))
    }

    // ---------------------------------------------------------------- 一局真的能打完

    /// 规格 §4 阶段 1 的第一条判据：**一局真的能跑到终态**。
    ///
    /// `paper_cut` 的节目是 `dealDamage{Amount: const 6, sel.eventTarget}`、费用 1 能量
    /// （实测 dump）。3 次出牌 + 过一个回合（能量补到 3）+ 1 次出牌 = 24 点，
    /// 敌人 22 血 ⇒ 死。这条测试同时证明伤害、费用、抽牌、回合推进、胜负判定都在动。
    #[test]
    fn a_fight_actually_finishes_and_the_enemy_loses_six_per_cut() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 12,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "city_easy_01",
            seed: 7,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: true,
            resources: &res,
            turn_start_refills: &refill,
        };
        let play = Step::HeroPlays {
            card: "paper_cut",
            target: Some("queue_imp"),
        };
        let script = [play, play, play, Step::NextRound, play];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短 id"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        assert_eq!(
            health(&state, "queue_imp"),
            0,
            "4 张 paper_cut × 6 = 24 ≥ 22 ⇒ 血量必须归零"
        );
        assert_eq!(
            lifecycle(&state, "queue_imp"),
            CombatantLifecycleState::Downed,
            "扣到 0 要转 Downed（`exec.rs:671-678`）"
        );
        assert_eq!(
            trace.result,
            CombatResult::Victory,
            "最后一个敌人倒下 ⇒ Victory（`CombatStateEffects.cs:55-58`）"
        );
        assert_eq!(trace.hashes.len(), 5);
        for (index, outcome) in trace.steps.iter().enumerate() {
            assert_eq!(outcome.problems, 0, "第 {index} 步不该有问题：{outcome:?}");
        }
        // 英雄一点血都没掉（敌人没动过），而且这局里英雄确实还是英雄。
        assert_eq!(health(&state, "hero"), 70);
        assert!(is_hero(&plan, &cid("hero")));
        assert!(!is_hero(&plan, &cid("queue_imp")));
        // 非平凡：每步之后指纹都在变（否则上面那些"每步哈希"是空的）。
        let unique: std::collections::BTreeSet<&String> = trace.hashes.iter().collect();
        assert_eq!(unique.len(), trace.hashes.len(), "5 步应当有 5 个不同指纹");
    }

    // ---------------------------------------------------------------- 确定性

    /// 同 `(plan, steps, seed)` 两遍 ⇒ 每步指纹**逐字节相同**。
    #[test]
    fn the_same_plan_and_seed_produce_byte_identical_hash_sequences() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 40,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 12,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "determinism",
            seed: 12345,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: true,
            resources: &res,
            turn_start_refills: &refill,
        };
        let script = [
            Step::HeroPlays {
                card: "paper_cut",
                target: Some("queue_imp"),
            },
            Step::HeroEndsTurn,
            Step::EnemyActs {
                enemy: "queue_imp",
                action: "queue_imp.desk_jab",
                target: Some("hero"),
            },
            Step::NextRound,
        ];

        let mut host_a = Host::new(&content);
        let mut state_a = CombatState::new(CombatId::new("a").expect("短"), 0);
        let a = drive(&mut state_a, &content, &plan, &script, &mut host_a);
        let mut host_b = Host::new(&content);
        let mut state_b = CombatState::new(CombatId::new("b").expect("短"), 0);
        let b = drive(&mut state_b, &content, &plan, &script, &mut host_b);

        assert_eq!(a.hashes.len(), script.len());
        assert_eq!(a.hashes, b.hashes, "同 (plan, seed) 必须逐字节相同");
        for (index, pair) in a.hashes.iter().zip(b.hashes.iter()).enumerate() {
            assert_eq!(pair.0, pair.1, "第 {index} 步");
        }
        // 成对：这条路真的动过 RNG（洗牌推了 step），否则"相同"可能因为什么都没发生。
        assert_eq!(state_a.random_step, 1, "开局洗了一次 ⇒ random_step = 1");
    }

    /// **成对**证明"改 seed 会改变序列"不是巧合：
    ///
    /// * 开局洗牌 ⇒ 一次随机数被消耗 ⇒ 种子必须改变整条序列；
    /// * **不**洗牌 ⇒ 一次随机数都不消耗 ⇒ 换种子必须**什么都**不改变。
    ///
    /// 只写前一半的话，"不同"可能来自别处（例如某个我还没意识到的地方读了种子）。
    #[test]
    fn a_shuffle_is_the_only_thing_the_seed_can_change_here() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 40,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 12,
        }];
        let small_deck = [DeckEntry {
            card: "paper_cut",
            count: 2,
        }];
        let res = resources();
        let refill = refills();
        let base = FightPlan {
            combat_id: "seed_probe",
            seed: 7,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: true,
            resources: &res,
            turn_start_refills: &refill,
        };
        let script = [Step::HeroPlays {
            card: "paper_cut",
            target: Some("queue_imp"),
        }];

        // 前一半：洗牌 + 换种子 ⇒ **牌序**不同（`seed=` 那一行当然也不同，所以看 layout）。
        let mut host = Host::new(&content);
        let mut s7 = CombatState::new(CombatId::new("s7").expect("短"), 0);
        let a = drive(
            &mut s7,
            &content,
            &FightPlan { seed: 7, ..base },
            &script,
            &mut host,
        );
        let mut host = Host::new(&content);
        let mut s8 = CombatState::new(CombatId::new("s8").expect("短"), 0);
        let b = drive(
            &mut s8,
            &content,
            &FightPlan { seed: 8, ..base },
            &script,
            &mut host,
        );
        assert_ne!(
            a.layouts, b.layouts,
            "开了洗牌 ⇒ 种子必须真的被消耗（12 张牌洗出不同顺序）"
        );
        assert_eq!(s7.random_step, 1, "洗过一次 ⇒ step 1");
        assert_eq!(s8.random_step, 1);

        // 后一半：**不**洗牌 ⇒ 换种子什么都不该改变（一次随机数都不消耗）。
        let no_shuffle = FightPlan {
            deck: &small_deck,
            shuffle_draw_pile_on_start: false,
            ..base
        };
        let mut host = Host::new(&content);
        let mut n7 = CombatState::new(CombatId::new("n7").expect("短"), 0);
        let c = drive(
            &mut n7,
            &content,
            &FightPlan { seed: 7, ..no_shuffle },
            &script,
            &mut host,
        );
        let mut host = Host::new(&content);
        let mut n8 = CombatState::new(CombatId::new("n8").expect("短"), 0);
        let d = drive(
            &mut n8,
            &content,
            &FightPlan { seed: 8, ..no_shuffle },
            &script,
            &mut host,
        );
        assert_eq!(
            c.layouts, d.layouts,
            "不洗牌 ⇒ 一个随机数都不消耗 ⇒ 换种子不该有任何影响（除了 `seed=` 那一行）"
        );
        assert_eq!(n7.random_step, 0);
        assert_eq!(n8.random_step, 0);
    }

    /// `random_step` 只在**真的洗了**（`Count > 1`）时才推（`ScenarioCombatFactory.cs:84-88`）。
    ///
    /// 这条是三向的，任意两条都不足以定位：`Count > 1 & 洗` / `Count > 1 & 不洗` / `Count == 1 & 洗`。
    /// 没有它，"删掉 `random_step += 1`"**不会让任何测试变红**（洗牌顺序仍然依赖种子，
    /// 所以"换种子序列不同"那条照样绿 —— 那是一处真实的覆盖洞，被这一条堵上）。
    #[test]
    fn the_start_shuffle_advances_the_random_step_once_and_only_when_it_shuffles() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 40,
        }];
        let many = [DeckEntry {
            card: "paper_cut",
            count: 12,
        }];
        let one = [DeckEntry {
            card: "paper_cut",
            count: 1,
        }];
        let res = resources();
        let refill = refills();
        let base = FightPlan {
            combat_id: "step_probe",
            seed: 3,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &many,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: true,
            resources: &res,
            turn_start_refills: &refill,
        };

        let mut state = CombatState::new(CombatId::new("many").expect("短"), 0);
        let mut host = Host::new(&content);
        build_fight(&mut state, &content, &base).expect("蓝图合法");
        assert_eq!(state.random_step, 1, "12 张 ⇒ 洗一次 ⇒ step 1");

        let mut state = CombatState::new(CombatId::new("one").expect("短"), 0);
        let mut host2 = Host::new(&content);
        build_fight(&mut state, &content, &FightPlan { deck: &one, ..base }).expect("蓝图合法");
        assert_eq!(state.random_step, 0, "1 张 ⇒ 连 step 都不推（`:84-85`）");

        let mut state = CombatState::new(CombatId::new("off").expect("短"), 0);
        build_fight(
            &mut state,
            &content,
            &FightPlan {
                shuffle_draw_pile_on_start: false,
                ..base
            },
        )
        .expect("蓝图合法");
        assert_eq!(state.random_step, 0, "不洗 ⇒ 不推");
        let _ = (&mut host, &mut host2);
    }

    // ---------------------------------------------------------------- 问题不中断循环

    /// `CardNotInHand` 是**观测**：记一条，然后**继续**跑后面的步（`:113-117` 只有 return，
    /// 循环在 `:32` 的 `for` 里 —— 没有 `break`）。
    ///
    /// ⚠️ 这条测试**必须一次喂完整个脚本**。`drive` 是一步一调，那种调法**测不出**
    /// "循环提前退出"：每一步都是一次独立的 `run_fight`，`break` 出去也没人看得见。
    /// 这不是假设 —— 第一版就是这么写的，变异测试（把 `CardNotInHand` 改成 `break`）
    /// 照样全绿 ⇒ 那个洞是靠变异测试发现的，不是靠读代码。
    #[test]
    fn a_card_that_is_not_in_hand_is_a_problem_and_the_loop_continues() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 1,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "missing_card",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let script = [
            Step::HeroPlays {
                card: "strong_binder",
                target: Some("queue_imp"),
            },
            Step::HeroPlays {
                card: "paper_cut",
                target: Some("queue_imp"),
            },
        ];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let mut out = FightOutcome::new();
        play_out(&mut state, &content, &plan, &script, &mut host, &mut out).expect("步进不该坏");

        assert_eq!(out.step_count, 2);
        // 步 0：`strong_binder` 是镜像里真有的卡，但不在手里 ⇒ 一条 CardNotInHand。
        assert_eq!(out.problems_of(0), &[Problem::CardNotInHand]);
        // 步 1：循环**继续**了（同一趟），纸片真的打出去 ⇒ 掉了 6 点。
        assert_eq!(out.problems_of(1), &[] as &[Problem], "步 1 不该有问题");
        assert_eq!(
            health(&state, "queue_imp"),
            16,
            "6 点伤害证明循环没被打断（22 - 6）"
        );
    }

    /// 战斗在某步结束后，**后面的步各记一条** `CombatAlreadyEnded`，且状态**逐字节不变**。
    #[test]
    fn after_the_combat_ends_every_later_step_records_it_and_changes_nothing() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 6,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 1,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "ends_early",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let script = [
            Step::HeroPlays {
                card: "paper_cut",
                target: Some("queue_imp"),
            },
            Step::HeroEndsTurn,
            Step::HeroPlays {
                card: "paper_cut",
                target: Some("queue_imp"),
            },
        ];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        assert_eq!(trace.result, CombatResult::Victory);
        assert_eq!(trace.kinds(0), &[] as &[Problem]);
        assert_eq!(trace.kinds(1), &[Problem::CombatAlreadyEnded]);
        assert_eq!(trace.kinds(2), &[Problem::CombatAlreadyEnded]);
        // 状态不再变化：三步之后的指纹必须与"战斗刚结束那一步"逐字节相同。
        assert_eq!(trace.hashes[1], trace.hashes[0], "已结束的步不许改状态");
        assert_eq!(trace.hashes[2], trace.hashes[0], "已结束的步不许改状态");

        // 再**一次喂完整个脚本**：`drive` 是一步一调，"终态之后仍然把剩下的步走完"
        // 这件事只有一次调用才证得了（理由见 `a_card_that_is_not_in_hand_…` 的文档）。
        let mut state = CombatState::new(CombatId::new("one_call").expect("短"), 0);
        let mut host = Host::new(&content);
        let mut out = FightOutcome::new();
        play_out(&mut state, &content, &plan, &script, &mut host, &mut out).expect("步进不该坏");
        assert_eq!(out.step_count, 3);
        assert_eq!(out.problems_of(0), &[] as &[Problem]);
        assert_eq!(out.problems_of(1), &[Problem::CombatAlreadyEnded]);
        assert_eq!(out.problems_of(2), &[Problem::CombatAlreadyEnded]);
        assert_eq!(out.result, CombatResult::Victory);
    }

    // ---------------------------------------------------------------- 回合推进

    /// `HeroEndsTurn` 之后 `turn`/`round` 真的前进了，而**记录的是执行前的值**。
    ///
    /// 第 2 步很关键：那时轮到敌人，`HeroEndsTurn` 记一条 `NotHeroTurnToEnd`
    /// （`:132-133`，**但继续**）然后把敌人回合也结束掉 ⇒ 轮次从 1 变 2，
    /// 而记下来的仍然是 `(1, 2)`。
    #[test]
    fn hero_ends_turn_advances_the_turn_and_keeps_the_pre_step_numbers() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 2,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "turns",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let script = [Step::HeroEndsTurn, Step::HeroEndsTurn];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        // 步 0：英雄(轮 1 回合 1)结束 ⇒ 轮到敌人（回合 2），轮次还是 1。
        assert_eq!((trace.steps[0].round, trace.steps[0].turn), (1, 1));
        assert_eq!(trace.kinds(0), &[] as &[Problem]);

        // 步 1：记的是**执行前**的 (1, 2) —— 这一步自己把轮次推到了 2。
        assert_eq!(
            (trace.steps[1].round, trace.steps[1].turn),
            (1, 2),
            "上下文必须在动作之前取（`ScenarioRunner.cs:140`）"
        );
        assert_eq!(trace.kinds(1), &[Problem::NotHeroTurnToEnd]);
        // 而**实际状态**确实前进了：轮次 2、回合 1、又轮到英雄。
        assert_eq!(state.current_round, 2, "回合序绕回英雄 ⇒ 新一轮");
        assert_eq!(state.current_turn, 1);
        assert_eq!(state.active_combatant_id, Some(cid("hero")));
        // 能量也被重补到 3（`StandardCombatPackage.cs:124`）。
        let pool = state
            .combatant(&cid("hero"))
            .and_then(|c| c.resources().iter().find(|p| p.key == energy()).copied())
            .expect("英雄必须有能量池");
        assert_eq!(pool.pool.current, ENERGY_REFILL);
    }

    // ---------------------------------------------------------------- 敌人行动

    /// `EnemyActs` 真的把伤害打到英雄身上（`queue_imp.desk_jab` = `dealDamage 8`，实测 dump）。
    #[test]
    fn an_enemy_action_lands_on_the_hero() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 2,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "enemy_hits",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let script = [
            Step::HeroEndsTurn,
            Step::EnemyActs {
                enemy: "queue_imp",
                action: "queue_imp.desk_jab",
                target: Some("hero"),
            },
        ];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        assert_eq!(health(&state, "hero"), 62, "desk_jab 是 8 点，70 - 8 = 62");
        assert_eq!(trace.kinds(1), &[] as &[Problem], "这一步不该有任何问题");
        // 上下文取在"推进到它的回合之后"（`ScenarioRunner.cs:163-164`）。
        assert_eq!((trace.steps[1].round, trace.steps[1].turn), (1, 2));
        assert_eq!(health(&state, "queue_imp"), 22, "它自己没掉血");
    }

    /// 敌人**已经倒下**时 `EnemyActs` 记 `EnemyNotAlive`，且英雄不掉血（`:178-182`）。
    ///
    /// 要走到这一支必须满足两个条件，缺一不可：`active == 该敌人`（否则先卡在
    /// `:172` 的 `CannotReachEnemyTurn`）且它已倒下（否则它会真的出手）。真实路径是
    /// **它在自己的回合开始时被 DoT 打死**：`permit_a38`（费用 2）给目标 5 层 `paperwork`
    /// （带 `damage_over_time` tag），而 turn-start 的 DoT 金额 = 层数（`host.rs:1058-1096`）
    /// ⇒ 5 血的敌人当场倒下，而队友还活着 ⇒ `result` 仍是 `Ongoing`。
    #[test]
    fn a_down_enemy_skips_its_action_and_the_hero_takes_nothing() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [
            PlanCombatant {
                id: "queue_imp",
                max_health: 5,
            },
            PlanCombatant {
                id: "stamp_goblin",
                max_health: 22,
            },
        ];
        let deck = [DeckEntry {
            card: "permit_a38",
            count: 5,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "dot_kill",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let script = [
            Step::HeroPlays {
                card: "permit_a38",
                target: Some("queue_imp"),
            },
            Step::HeroEndsTurn,
            Step::EnemyActs {
                enemy: "queue_imp",
                action: "queue_imp.desk_jab",
                target: Some("hero"),
            },
        ];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        // 步 0 只是上毒：它还活着。
        assert_eq!(trace.kinds(0), &[] as &[Problem]);
        assert_eq!(trace.hp(0, "queue_imp"), 5, "paperwork 不直接扣血");
        // 步 1 的 turn-start DoT 把它打死在**自己的回合**里。
        assert_eq!(trace.hp(1, "queue_imp"), 0, "5 层 DoT = 5 点");
        assert_eq!(lifecycle(&state, "queue_imp"), CombatantLifecycleState::Downed);
        assert_eq!(
            trace.result,
            CombatResult::Ongoing,
            "队友还活着 ⇒ 战斗没结束（所以下一步才走得到 EnemyNotAlive）"
        );
        // 步 2：它是行动者，但已经倒下 ⇒ 动作跳过。
        assert_eq!(trace.kinds(2), &[Problem::EnemyNotAlive]);
        assert_eq!(health(&state, "hero"), 70, "跳过动作 ⇒ 英雄一滴血都不掉");
        assert_eq!(health(&state, "stamp_goblin"), 22);
    }

    /// 敌人不存在 ⇒ `NoSuchEnemy`；动作没注册 ⇒ `UnknownEnemyAction`（`:157-161`、`:184-189`）。
    #[test]
    fn a_missing_enemy_and_an_unregistered_action_are_distinct_problems() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 2,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "bad_actor",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };

        // ① 敌人不存在（它**没进**战斗）。
        let script = [Step::EnemyActs {
            enemy: "nobody",
            action: "queue_imp.desk_jab",
            target: Some("hero"),
        }];
        let mut state = CombatState::new(CombatId::new("n1").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);
        assert_eq!(trace.kinds(0), &[Problem::NoSuchEnemy]);
        assert_eq!(health(&state, "hero"), 70);

        // ② 敌人在、也轮到它，但动作没注册。
        let script = [
            Step::HeroEndsTurn,
            Step::EnemyActs {
                enemy: "queue_imp",
                action: "queue_imp.no_such_action",
                target: Some("hero"),
            },
        ];
        let mut state = CombatState::new(CombatId::new("n2").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);
        assert_eq!(trace.kinds(1), &[Problem::UnknownEnemyAction]);
        assert_eq!(health(&state, "hero"), 70, "没注册的动作不许出手");
    }

    /// 轮到英雄时 `EnemyActs`：参考记**两条**（`:241` 一条 + `:172` 一条），
    /// 而内核只有一个桶 [`Problem::CannotReachEnemyTurn`]（[`FROZEN_GAP_PROBLEM`]）。
    #[test]
    fn the_still_heroes_turn_problem_collapses_into_cannot_reach_enemy_turn() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 2,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "hero_turn",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let script = [Step::EnemyActs {
            enemy: "queue_imp",
            action: "queue_imp.desk_jab",
            target: Some("hero"),
        }];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        assert_eq!(
            trace.kinds(0),
            &[Problem::CannotReachEnemyTurn, Problem::CannotReachEnemyTurn],
            "两条不同的参考问题塌进同一个桶（`:241` + `:172`）"
        );
        assert_eq!(health(&state, "hero"), 70);
        // 英雄的回合没有被偷偷结束（`:239-243` 的原话：call HeroEndsTurn first）。
        assert_eq!(state.active_combatant_id, Some(cid("hero")));
    }

    /// 英雄倒下的分支（`:45-51`）。**前置条件是手工造的**，而且**只可能被观测到一次**：
    ///
    /// * v1 没有友军，所以英雄一倒就没人守家 ⇒ [`settle_result`] 立刻判 `Defeat`；
    /// * 下一步先撞上 `:40` 的 `Result != Ongoing` ⇒ 记 `CombatAlreadyEnded`。
    ///
    /// 参考也一样：`:46-48` 的注释说 `HeroDowned` 是给"a summoned ally keeps the team alive"
    /// 那种情形用的。所以这条测试断言的是**分支本身**：结果仍是 `Ongoing` 而英雄已倒下 ⇒
    /// 这一步不执行、记一条 `HeroDowned`；而从下一步起状态**彻底冻结**。
    #[test]
    fn a_downed_hero_is_a_problem_and_the_state_stops_moving() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 2,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "downed_hero",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        build_fight(&mut state, &content, &plan).expect("蓝图合法");
        // 手工把英雄按倒，并**保持** `result == Ongoing`（v1 造不出这个前置条件）。
        state
            .combatant_mut(&cid("hero"))
            .expect("英雄在")
            .lifecycle_state = CombatantLifecycleState::Downed;

        let script = [
            Step::HeroPlays {
                card: "paper_cut",
                target: Some("queue_imp"),
            },
            Step::HeroEndsTurn,
        ];
        let mut out = FightOutcome::new();
        run_fight(&mut state, &content, &script, &mut host, &mut out).expect("步进不该坏");
        assert_eq!(out.problems_of(0), &[Problem::HeroDowned]);
        assert_eq!(
            out.problems_of(1),
            &[Problem::CombatAlreadyEnded],
            "英雄一倒就没有队友 ⇒ 第一步之后就被判成 Defeat ⇒ 下一步先撞上终态门"
        );
        // 结论：在 v1 里 `HeroDowned` 最多只能被观测到**一次**（它需要友军，而 v1 没有）。
        assert_eq!(
            state.result,
            CombatResult::Defeat,
            "玩家队没有活人 ⇒ Defeat（`CombatStateEffects.cs:49-53`）"
        );
        // 判定之后状态彻底冻结：再跑一步，指纹不变。
        let frozen = state_hash(&state);
        let mut out = FightOutcome::new();
        run_fight(
            &mut state,
            &content,
            &[Step::EnemyActs {
                enemy: "queue_imp",
                action: "queue_imp.desk_jab",
                target: Some("hero"),
            }],
            &mut host,
            &mut out,
        )
        .expect("步进不该坏");
        assert_eq!(out.problems_of(0), &[Problem::CombatAlreadyEnded]);
        assert_eq!(state_hash(&state), frozen, "终态之后的步一律不执行");
    }

    /// 卡打不出去（付不起）⇒ `CardNotPlayed`，卡留在手里、费用不动（`:124-125`）。
    #[test]
    fn an_unaffordable_card_is_not_played_and_stays_in_hand() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        let deck = [DeckEntry {
            card: "permit_a38",
            count: 2,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "broke",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        // `permit_a38` 费用 2。3 能量 ⇒ 第一张能打，第二张打不起。
        let script = [
            Step::HeroPlays {
                card: "permit_a38",
                target: Some("queue_imp"),
            },
            Step::HeroPlays {
                card: "permit_a38",
                target: Some("queue_imp"),
            },
        ];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        assert_eq!(trace.kinds(0), &[] as &[Problem]);
        assert_eq!(trace.kinds(1), &[Problem::CardNotPlayed]);
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            1,
            "没打出去的那张还在手里"
        );
        let pool = state
            .combatant(&cid("hero"))
            .and_then(|c| c.resources().iter().find(|p| p.key == energy()).copied())
            .expect("英雄必须有能量池");
        assert_eq!(pool.pool.current, 1, "只付了第一张的 2 点");
    }

    // ---------------------------------------------------------------- 信封

    /// 一步里"抛了"⇒ 一条 [`Problem::StepThrew`]，循环继续（`:52-63`）。
    ///
    /// 触发它要用**内核自己的**一条边界：目标 id 超过 `CombatantId` 的 40 字节容量。
    /// 参考在 `new CombatantId(targetId)`（`:263-264`）那一行**不会**失败（它的 id 没有上限），
    /// 所以这是内核侧多出来的一条拒绝 —— 它必须表现为一条**观测**，不是 `Err`：
    /// 驱动层没坏，是这一步的参数装不下。
    #[test]
    fn a_step_that_throws_is_recorded_and_the_loop_continues() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 2,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "throws",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        // 41 字节 > `CombatantId` 的 `ID_CAP = 40`。
        let too_long = "x".repeat(41);
        let script = [
            Step::HeroPlays {
                card: "paper_cut",
                target: Some(too_long.as_str()),
            },
            Step::HeroPlays {
                card: "paper_cut",
                target: Some("queue_imp"),
            },
        ];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let mut out = FightOutcome::new();
        play_out(&mut state, &content, &plan, &script, &mut host, &mut out).expect("步进不该坏");
        assert_eq!(out.step_count, 2);
        assert_eq!(out.problems_of(0), &[Problem::StepThrew]);
        assert_eq!(
            health(&state, "queue_imp"),
            16,
            "步 0 没打出去，步 1 打出去了（22 - 6）"
        );
    }

    /// 步数超过信封 ⇒ `TooManySteps`（**不截断**）。
    #[test]
    fn too_many_steps_is_an_envelope_error_not_a_truncation() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 1,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "too_long",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let script = [Step::HeroEndsTurn; MAX_STEPS + 1];
        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let mut out = FightOutcome::new();
        let error = play_out(&mut state, &content, &plan, &script, &mut host, &mut out)
            .expect_err("65 步必须被拒");
        assert_eq!(error, BattleError::TooManySteps);
    }

    // ---------------------------------------------------------------- 建战斗的拒绝面

    /// 蓝图里的卡定义必须**在镜像里**（`build_fight` 的 `UnknownCard`）。
    #[test]
    fn a_card_definition_that_is_not_in_the_image_is_refused_at_build_time() {
        let blob = core_image();
        let content = parse(&blob);
        let deck = [DeckEntry {
            card: "no_such_card_",
            count: 1,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "unknown",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &[],
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let error = build_fight(&mut state, &content, &plan).expect_err("镜像里没有这张卡");
        assert_eq!(
            error,
            BattleError::UnknownCard(CardDefinitionId::new("no_such_card_").expect("短"))
        );
    }

    /// 蓝图里那两个喂回合机的旋钮，`run_fight` 兑现不了 ⇒ **响亮拒绝**（不是静默按 5 抽）。
    #[test]
    fn turn_knobs_the_driver_cannot_honour_are_refused() {
        let blob = core_image();
        let content = parse(&blob);
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 1,
        }];
        let res = resources();
        let refill = refills();
        let base = FightPlan {
            combat_id: "knobs",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &[],
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);

        // 抽 7 张：`run_fight` 只会抽 5，所以拒。
        let error = build_fight(
            &mut state,
            &content,
            &FightPlan {
                cards_drawn_per_turn: 7,
                ..base
            },
        )
        .expect_err("抽牌数不一致必须被拒");
        assert_eq!(error, unsupported());

        // 空补能表 = "不补"，`run_fight` 会补到 3 ⇒ 也拒。
        let error = build_fight(
            &mut state,
            &content,
            &FightPlan {
                turn_start_refills: &[],
                ..base
            },
        )
        .expect_err("补能表不一致必须被拒");
        assert_eq!(error, unsupported());

        // 对照：标准那一份能建（否则上面两条"拒绝"可能只是因为什么都建不出来）。
        build_fight(&mut state, &content, &base).expect("标准旋钮必须能建");
    }

    /// 标准包那五个数字是**规格**，不是随手写的（`StandardCombatPackage.cs:7,124` +
    /// `StandardCombatIds`）。改它们必须同时改这份测试。
    #[test]
    fn the_standard_turn_config_matches_the_reference_package() {
        let config = standard_turn_config().expect("两个常量 id 不可能超容量");
        assert_eq!(config.energy.as_str(), "standard.energy");
        assert_eq!(config.energy_refill, 3, "`StandardCombatPackage.cs:124`");
        assert_eq!(config.draw_per_turn, 5, "`StandardCombatPackage.cs:7`");
        assert_eq!(config.block_pool.as_str(), "standard.block");
        assert_eq!(
            config.max_hand_size,
            i32::MAX,
            "镜像里没有 MaxHandSize 法令（STAT.CombatRules 23/23 ABSENT）"
        );
    }

    /// `innate` 拒绝面今天不可达，而**读 tag 的代码不是恒假**（成对）。
    ///
    /// 前半段：62/62 卡都不带 `innate`（core 镜像的串池里连这个串都没有）。
    /// 后半段：同一个读取器对 `paper_cut` 的 `attack` 返回 true ⇒ 它真的在读。
    #[test]
    fn no_card_in_the_image_is_innate_today() {
        let blob = core_image();
        let content = parse(&blob);
        let mut cards = 0usize;
        let mut innate = 0usize;
        for index in 0..u32::from(u16::MAX) {
            let Some(row) = content.card(index) else {
                break;
            };
            cards += 1;
            let Some(id) = content.string(row.id()) else {
                panic!("CARD[{index}] 的 Id 读不出来（镜像坏了）");
            };
            match card_has_tag(&content, id, INNATE_TAG) {
                Ok(true) => innate += 1,
                Ok(false) => {}
                Err(()) => panic!("CARD[{index}] 的 Tags 读不出来（镜像坏了）"),
            }
        }
        assert_eq!(cards, 62, "实测 CARD 表 62 行");
        assert_eq!(innate, 0, "今天一张 innate 卡都没有 ⇒ 拒绝面不可达");
        // 成对：读取器不是恒假。
        assert_eq!(card_has_tag(&content, "paper_cut", "attack"), Ok(true));
        assert_eq!(card_has_tag(&content, "paper_cut", INNATE_TAG), Ok(false));
        assert_eq!(card_has_tag(&content, "no_such_card_", "attack"), Ok(false));
    }

    /// 卡实例 id 的形状是 `card_%06d`（`CombatState.cs:689-696`），而且**每张一个新号**。
    #[test]
    fn card_instance_ids_are_card_underscore_six_digits_and_never_shared() {
        let blob = core_image();
        let content = parse(&blob);
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 3,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "ids",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &[],
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        build_fight(&mut state, &content, &plan).expect("蓝图合法");

        let slots = state
            .card_zones(&cid("hero"))
            .expect("英雄有牌区")
            .slots(CardZone::DrawPile)
            .to_vec();
        assert_eq!(slots.len(), 3, "3 张都在抽牌堆里");
        let ids: Vec<String> = slots
            .iter()
            .map(|raw| {
                state
                    .card(CardSlot::from_index(*raw))
                    .expect("槽位指向实例")
                    .id
                    .as_str()
                    .to_string()
            })
            .collect();
        assert_eq!(ids, vec!["card_000001", "card_000002", "card_000003"]);
        assert_eq!(state.next_card_instance_number, 4, "先取号再自增");
        assert_eq!(card_instance_id(1).map(|id| id.as_str().to_string()), Ok("card_000001".to_string()));
    }
}
