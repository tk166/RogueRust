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
//! # 现在的状态：实现了；两处冻结面的洞已按裁决补上（2026-10-18）
//!
//! `build_fight` / `run_fight` 照规格书逐行落地，测试全部接真实镜像
//! （`tools/contentc/out/content.core.rdcf`）。落地时撞到的两个**接口层面的洞**已经
//! 由冻结方裁决修掉，历史记录在本文件底部 §"冻结面的四个洞（已裁决）"，现在的形状是：
//!
//! * `run_fight` 收 **`&FightPlan`** ⇒ 抽牌数与补能配置有正规来路（不再是硬编码标准包）；
//! * 英雄 id 取自 `plan.hero.id`（不再按队推断）；
//! * [`Problem::StillHeroTurn`] 补上了（`:241` 与 `:248` 是两件修法相反的事）。
//!
//! # 牌组从内容来（2026-10-19，"内容到一局"的最后一米）
//!
//! [`build_fight_from_content`] 把内容文档里声明的**起始牌组**接进一局：三处副本按参考
//! `RunSetup.CreateInitialRun` 的顺序解析（`Characters[0].Start.Deck` → `Start.Deck` →
//! 根 `Deck`，行号见那个函数的文档），调用方显式给的 [`FightPlan::deck`] 仍然**优先**。
//! [`build_fight`] 的语义**一字未变**（空牌组就是 0 张，不会去内容里找）。
//!
//! 为什么它是第二条入口而不是 `FightPlan` 的一个新字段：加字段会让每一个
//! `FightPlan { … }` 字面量都要跟着改，而 `rd-fightdump` / `rd-wasm` 里各有一处、本轮冻结。
//!
//! ⚠️ `docs/` 本轮冻结，所以 `docs/port-plan.md` 里**没有**对应的 §（下一轮补）；
//! 这一段与 [`crate::content::Content::start_deck`] 的节头（三行表 + 实测形态表）就是
//! 这件事的**当下权威描述**。
//!
//! 仍然留着的两条（都是**参考实现里真实存在、而 v1 缺一层能力**的地方，见 [`DEVIATIONS`]）：
//!
//! * 胜负**在战斗员倒下那一行**由 [`exec::update_standard_combat_result`] 判（2026-10-19 起，
//!   与参考的 `Downed → CombatantLifecycleChanged → SetCombatResult` 同粒度），本模块
//!   **另外**在每次引擎调用之后用 [`settle_result`] 幂等复核一次（参考的驱动层也这么复核，
//!   `ScenarioRunner.cs:143/206/211/237`）—— 剩下的粒度差异见 [`FROZEN_GAP_RESULT`]；
//! * `Problem::HeroDowned` 在当前能力下**最多只能观测到一次**：v1 没有友军，英雄一倒
//!   玩家队就没有活人 ⇒ 当场判 `Defeat` ⇒ 下一步先撞 `:40` 的终态门。参考要它持续
//!   存在得有"a summoned ally keeps the team alive"（`:46-48` 的原注释）—— 那不是缺陷，
//!   是这条分支可达性的上界。

use crate::content::{Content, ABSENT16, DeckError, DeckRoots, EK_CARD, EK_EACTION, F_TERM,
    LIST_ABSENT, LIST_NULL, NULL16, OP_ARR, OP_WRAP_LOWER, StartDeck};
use crate::exec;
use crate::intent;
use crate::play::{self, PlayError, PlayRequest};
use crate::rng;
use crate::state::{
    CapacityError, CardDefinitionId, CardInstance, CardInstanceId, CardSlot, CardZone, CombatId,
    CombatResult, CombatState, CombatTurnPhase, Combatant, CombatantDefinitionId, CombatantId,
    DefensivePoolId, ResourceId, TeamId, ZonePlacement, MAX_CARDS_PER_ZONE,
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

/// 仍然存在的**偏差 / 可达上界**（裁决后剩下的两条）。
///
/// 公开它是因为它要**打出来**：`rd-fightdump` 每个场景头上把这行印出来，
/// 好让读输出的人第一眼知道"这份输出是在什么偏差下产生的"。
pub const DEVIATIONS: [&str; 2] = [
    "result-settled-per-engine-call-not-per-queue-drain",
    "hero-downed-observable-at-most-once-v1-has-no-allies",
];

/// # `FROZEN_GAP_RESULT` —— 已收窄（2026-10-19），但仍然在
///
/// 参考的胜负由 `UpdateStandardCombatResultOnLifecycleChangedHandler`
/// （`RogueDeck.Core/Combat/Effects/CombatStateEffects.cs:28-60`）在
/// `CombatantLifecycleChanged` 事件上算，靠事件队列在**下一次排空**时生效；
/// `SetResult` 又会立刻取消在飞帧（`CombatState.cs:358-367`），所以"倒下即判、判了就停"。
///
/// **2026-10-19 的整局对拍把这条修掉了**（`native/fight_diff.py` 的 `finish` 场景）：
/// 原来本内核只在每次引擎调用之后算，于是 `play::play_card` 执行期间 `state.result`
/// 一直是 `Ongoing` —— 程序打死最后一个敌人那一下没人立刻知道，`play.rs` 的
/// "Cancelled ⇒ 卡不搬"分支**从来没有被真实路径走到过**。现在判定点在
/// [`exec::update_standard_combat_result`]，就在 `exec.rs` 把目标打成 `Downed` 的那一行。
///
/// 剩下的粒度差异：本模块**仍然**在每次引擎调用之后用 [`settle_result`] 幂等复核一次
/// （参考的驱动层同样复核，`ScenarioRunner.cs:143`、`:206`、`:211`、`:237`）。复核本身
/// 不会掩盖漏判 —— 它只在 `Result == Ongoing` 时动手，而"程序中途停下来"只能来自
/// 下判点那一次。真正仍比参考粗的一格是**内容层**的：一个不经"打倒"就改结果的节点
/// （`node.setCombatResult`，`EffectProgramNodeExecutors.cs:1968`）本内核没有实现，
/// 镜像里也 0 条 —— 那时它会被预检拒，而不是被算错。
///
/// 测试：`a_lethal_play_leaves_the_card_in_hand_and_the_combat_over`（battle.rs）钉住
/// "程序中途结束 ⇒ 卡留手牌 + `landed == None` + 费用已付"。
pub const FROZEN_GAP_RESULT: &str = "result-settled-per-engine-call-not-per-queue-drain";

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
/// ⚠️ `cards_drawn_per_turn` 与 `turn_start_refills` 现在是**真的**喂给回合机的
/// （[`turn_config_for`]）。后者有一处表达不了的形状：回合机只有一个能量资源
/// （`TurnConfig::energy`），所以补能表**多于一条**会被响亮拒绝，而不是静默丢掉后面的。
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
    ///
    /// ⚠️ 这是**参考的形状**，不是"该怎么打牌"：它是场景脚本的一步，脚本是文本、没有实例号，
    /// 所以只能按定义点名（`ScenarioRunner.cs:109-111`）。四条对拍流水线驱动的就是它，改语义会
    /// 移动基线 ⇒ 它的含义**冻着**。
    HeroPlays {
        /// 卡定义 id。
        card: &'a str,
        /// 目标（`None` = 没有目标，不是错误）。
        target: Option<&'a str>,
    },
    /// **按实例**打牌（本内核自己的扩展，§161.4）。
    ///
    /// 页面是**按手牌位置**点的，而按定义点名时"两份同定义副本"不可区分：如果一张普通
    /// `strike` 排在前面，玩家永远打不出后面那张带每副本价格的 `strike` —— 一个点了没反应的
    /// 按钮。§161.3 之前副本之间没有可观察的差别，所以这条一直没露出来；每副本价格是第一个
    /// 让"哪一张"变得有意义的东西。
    HeroPlaysInstance {
        /// 卡**实例** id。
        card: CardInstanceId,
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
    /// **只结束一个回合**：把行动位交给回合序里下一个**活着**的战斗员，然后停下。
    ///
    /// # 为什么需要它
    ///
    /// `HeroEndsTurn` / `EnemyActs` / `NextRound` 三个都回答不了"让**下一个**敌人出手"：
    /// * `HeroEndsTurn` 只把行动位交给**一个**战斗员（回合机的 `AdvanceToNextCombatant`
    ///   一次只前进一步），所以两个敌人时它只解锁第一个；
    /// * `EnemyActs` 是"推进到**指定**敌人"，调用方得先知道轮到谁；
    /// * `NextRound` 是"一直结束到英雄回合"，会跨过所有敌人 —— 中间的敌人一次都轮不到
    ///   （`rd-wasm` 的 Gap 4 就是这件事：一次"结束回合"只让一个敌人行动）。
    ///
    /// 参考实现里承担这件事的是 `ScenarioRunner.cs:226-252` 的
    /// `AdvanceTurnsUntilActive`：**逐个** `EndCurrentTurnAndStartNextTurn`，每一跳之后
    /// 都看结果。本变体是它的"没有指定目标"版本 —— 推**一步**就停。
    ///
    /// # 语义（严格按参考，别在这里加战斗语义）
    ///
    /// 1. `EnsureTurnStarted`（与 `HeroEndsTurn` / `NextRound` 同一个入口）；
    /// 2. **先推一格**（这一步的语义就是"结束当前这一回合"，当前上场的是英雄也一样）；
    ///    之后只在接手的战斗员**已倒下**（它自己的 turn-start 触发器/DoT 把它打死了）时
    ///    继续推 —— 这就是"跳过已倒下的"；轮到活着的战斗员 ⇒ 停（一步只让一个上场）；
    /// 3. **每一跳之后立刻复核胜负**（[`end_turn_and_start_next`]，见 [`FROZEN_GAP_RESULT`]）：
    ///    战斗一结束就停，绝不把终局之后的回合推下去。
    EndOneTurn,
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
    /// `EnemyActs` 推进时轮到**英雄**，驱动层不替英雄结束回合（`:239-243`）。
    ///
    /// ⚠️ 这个变体是 2026-10-18 冻结方补的（执行方报的缺口）。它与
    /// [`Self::CannotReachEnemyTurn`] 必须分开，因为**修法相反**：
    /// 这条是"脚本顺序写错了（先调 `HeroEndsTurn`）"，那条是"回合序没绕回它"。
    /// 今天两条的参考原文分别是 `:241`（"It is still the hero's turn — call
    /// HeroEndsTurn before EnemyActs."）与 `:248`（"Could not advance to enemy …'s turn."）。
    StillHeroTurn,
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
    /// [`Step::EndOneTurn`] 在 `turn_order.len() + 2` 圈的守卫内没停住（参考 `:236`/`:248`
    /// 那两处守卫的同形物）。
    ///
    /// **今天不可达**：每一圈要么停、要么把行动位往前推一格，而 `advance_to_next_combatant`
    /// 保证落到一个活着的战斗员上。它存在是因为"转不出来"必须响亮 —— 与
    /// [`Self::CouldNotWrapToHero`] 同一个理由。
    CouldNotEndOneTurn,
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
            Problem::StillHeroTurn => "StillHeroTurn",
            Problem::NoSuchEnemy => "NoSuchEnemy",
            Problem::CombatEndedBeforeEnemy => "CombatEndedBeforeEnemy",
            Problem::CannotReachEnemyTurn => "CannotReachEnemyTurn",
            Problem::EnemyNotAlive => "EnemyNotAlive",
            Problem::UnknownEnemyAction => "UnknownEnemyAction",
            Problem::CouldNotWrapToHero => "CouldNotWrapToHero",
            Problem::CouldNotEndOneTurn => "CouldNotEndOneTurn",
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

/// [`Problem::StepThrew`] 背后的粗分类（`port-plan.md` §152）。
///
/// 粒度是有意**粗**的：它是"去哪一层查"的指针，不是错误本身 —— 精确的错误在 `Debug` 里，
/// 而那东西进不了 wasm 的一格 `i32`。
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum StepCause {
    /// 没有错误。
    #[default]
    None,
    /// 枚举/脚本层（`BattleError::Card` / `Step` / `Ir` …）。
    Script,
    /// 执行程序（`ExecError`）。
    Exec,
    /// 回合机（`Turn`/`Host`）。
    Turn,
    /// 容量（某个定容表满了）。
    ///
    /// ⚠️ **不带"哪一个容器"的载荷**：`FightOutcome` 是 wasm 里的一个信封，`rd_env_bench_sizes`
    /// 有一条"它必须是几 KB"的断言（`step_causes` 带 `&'static str` 时当场把它撑过 4 KB）。
    /// 所以容器走**数字代号**：`step_capacity: [u8; MAX_STEPS]`，名字表只有一份
    /// （`state::Container::name_of`），宿主拿它来把 `Capacity` 说成 `Capacity:Statuses`。
    Capacity,
    /// 其它。
    Other,
}

impl StepCause {
    /// 从被吞掉的那个错误里分类。
    #[must_use]
    pub fn of(error: &BattleError) -> Self {
        match error {
            BattleError::TooManySteps
            | BattleError::TooManyProblems
            | BattleError::Capacity(_) => StepCause::Capacity,
            BattleError::Turn(turn) => match turn {
                crate::turn::TurnError::Capacity(_) => StepCause::Capacity,
                crate::turn::TurnError::Host(failure) => match failure {
                    crate::turn::HostFailure::Effect => StepCause::Exec,
                    _ => StepCause::Turn,
                },
                _ => StepCause::Turn,
            },
            BattleError::Deck(_) | BattleError::Play(_) => StepCause::Script,
            _ => StepCause::Other,
        }
    }

    /// 这个错误装满的那个容器的代号（0 = 不是容量错误 / 不知道）。
    #[must_use]
    pub fn capacity_code(error: &BattleError) -> u8 {
        let capacity = match error {
            BattleError::Capacity(failure) => Some(failure),
            BattleError::Turn(crate::turn::TurnError::Capacity(failure)) => Some(failure),
            _ => None,
        };
        match capacity {
            Some(crate::state::CapacityError::Full(container)) => container.code(),
            _ => 0,
        }
    }

    /// 一个稳定的短名（宿主/日志用）。
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            StepCause::None => "",
            StepCause::Script => "Script",
            StepCause::Exec => "Exec",
            StepCause::Turn => "Turn",
            StepCause::Capacity => "Capacity",
            StepCause::Other => "Other",
        }
    }
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
    /// 每步被**吞掉的那个错误**的类别（0 = 没有）。
    ///
    /// [`Problem::StepThrew`] 是参考的语义（"抛了"），但它把**具体哪个错**丢掉了 —— 于是
    /// "这一步抛了"在页面上和"内核里某处返回了 Err"长得一样，谁也查不下去（§152 的 soak 撞了
    /// 很久）。这一格不改变 `Problem` 的线上形状，只是让宿主能多说一句 `StepThrew(Exec)`。
    pub step_causes: [StepCause; MAX_STEPS],
    /// 装不下时**是哪个容器**（`state::Container::code()`；0 = 不是容量错误）。
    ///
    /// 与 `step_causes` 分开，是为了让信封保持小：这个名字只用来让宿主把
    /// `StepThrew(Capacity)` 说成 `StepThrew(Capacity:Statuses)`。
    pub step_capacity: [u8; MAX_STEPS],
    /// §177: **which** `Deck`/`Play` refusal a step hit (`0` = none). `step_causes` says only
    /// "Script", which is exactly the level of detail that cannot be acted on: `Refused(Unplayable)`
    /// and `Unaffordable { need: 2, have: 1 }` are different bugs with the same family name.
    pub step_codes: [u8; MAX_STEPS],
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
            step_causes: [StepCause::None; MAX_STEPS],
            step_capacity: [0; MAX_STEPS],
        step_codes: [0; MAX_STEPS],
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
    /// 内容里声明的**起始牌组**读不出来（[`build_fight_from_content`]）。
    ///
    /// 没有并进 `Turn(Host(HostFailure::Content))`：那个桶的文档是"内容配错了"这个**结论**，
    /// 而这里要把"坏在哪一跳、坏成什么样"（[`crate::content::DeckError`]）带出去 ——
    /// 一个只报"内容错了"的失败要人把整条解析链重新挖一遍。
    Deck(DeckError),
    /// 牌组容量/状态容器装不下。
    Capacity(crate::state::CapacityError),
    /// 回合机报错。
    Turn(TurnError),
    /// 出牌报错。
    Play(PlayError),
}

/// §177: the `u8` code for a `Deck`/`Play` refusal (see [`play_code_name`]). `0` for everything else.
///
/// One table, in the kernel: the page prints `play_code_name(code)` and never owns a second copy of
/// these numbers.
#[must_use]
pub fn play_code(error: &BattleError) -> u8 {
    let BattleError::Play(play_error) = error else {
        return match error {
            BattleError::Deck(_) => 17,
            _ => 0,
        };
    };
    match play_error {
        PlayError::NotOngoing => 1,
        PlayError::SourceUnavailable => 2,
        PlayError::UnknownCard => 3,
        PlayError::CardNotInHand => 4,
        PlayError::Refused(refusal) => match refusal {
            crate::play::Refusal::Stunned => 5,
            crate::play::Refusal::Unplayable => 6,
            crate::play::Refusal::PlayConditionFalse => 7,
            crate::play::Refusal::DecreeMaxCardsPerTurn { .. } => 8,
            crate::play::Refusal::DecreeNoLikeness { .. } => 9,
            crate::play::Refusal::OneAttackPerTurn => 10,
            // §196: the page prints this name; 11..17 are taken, so the code is 18.
            crate::play::Refusal::Entangled => 18,
        },
        PlayError::MissingResource { .. } => 11,
        PlayError::Unaffordable { .. } => 12,
        PlayError::NegativePrintedCost { .. } => 13,
        PlayError::Effect(_) => 14,
        PlayError::UnsupportedContent(_) => 15,
        PlayError::Capacity(_) => 16,
    }
}

/// The name of a [`play_code`] value (`"none"` for `0`).
#[must_use]
pub fn play_code_name(code: u8) -> &'static str {
    match code {
        1 => "NotOngoing",
        2 => "SourceUnavailable",
        3 => "UnknownCard",
        4 => "CardNotInHand",
        5 => "Refused(Stunned)",
        6 => "Refused(Unplayable)",
        7 => "Refused(PlayConditionFalse)",
        8 => "Refused(DecreeMaxCardsPerTurn)",
        9 => "Refused(DecreeNoLikeness)",
        10 => "Refused(OneAttackPerTurn)",
        18 => "Refused(Entangled)",
        11 => "MissingResource",
        12 => "Unaffordable",
        13 => "NegativePrintedCost",
        14 => "Effect",
        15 => "UnsupportedContent",
        16 => "Capacity",
        17 => "Deck",
        _ => "none",
    }
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
/// §144 起**有消费者**：`move_innate_cards_to_top` 真的按它挑牌了（之前只用来拒绝）。
const INNATE_TAG: &str = "innate";

/// `x_cost`：本内核**自己的**约定，参考里没有它（§144 引入，§146 变成真能力）。
///
/// 参考全仓没有 X 费概念（`XCost` / `EnergySpent` 零命中），所以这是**新造**的一条费用形态，
/// 而不是"还没移植的字段"。§144 时它只是一个响亮拒绝的判据；§146 起 `play.rs` 真的把它
/// 算成"花掉全部能量"，`expr` 的 `x.cost` 把它交给节目。这个字面量现在是两处共用的那一份。
pub const X_COST_TAG: &str = "x_cost";
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
/// 第 1 步为什么要**重置**：参考在那一行**新建**一份状态，而内核的电牌面是"调用方提供
/// 存储"。不重置的话 `card_num=` / `random_step=` / `status_num=` 会带着别处的残留进哈希
/// —— 那种偏差不会报错，只会让指纹对不上。`CombatState` 的容器字段是私有的，所以走
/// [`CombatState::reset_in_place`]（**不是**整体赋值 `*state = CombatState::new(..)`：
/// 后者会把 184 KB 的常量模板带进 `.wasm`，见 `state.rs` 里那个方法的注释）。
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
///
/// # 牌组从哪来
///
/// **这一条入口的牌组就是 [`FightPlan::deck`]，一个字节的语义都没变**：空就是空
/// （0 张牌的局），**不会**去内容里找。要"从内容读牌组"请用
/// [`build_fight_from_content`] —— 两条入口分开是刻意的，见那边的"为什么不合并"。
pub fn build_fight(
    state: &mut CombatState,
    content: &Content<'_>,
    plan: &FightPlan<'_>,
) -> Result<(), BattleError> {
    build_fight_with(state, content, plan, DeckPath::new_plan(plan.deck))
}

/// 同一局战斗，但**牌组从内容镜像里读**（`battle.rs` 接上"内容到一局"的最后一米）。
///
/// # 读哪一份副本（三条都带行号，`ref/RogueDeck-Core` 钉死 commit `fd43e68`）
///
/// 内容文档里有三处写着起始牌组，参考只读其中一处、另外两处是回退：
///
/// | 顺序 | 位置 | 什么时候读 | 参考 |
/// |---|---|---|---|
/// | 1 | `Characters[0].Start.Deck` | 花名册非空 | `RunBlueprint.cs:167-176`（`ResolveStart`）+ `RunSetup.cs:44` |
/// | 2 | `Start.Deck` | 花名册**为空** | `RunBlueprint.cs:169-170` + `RunSetup.cs:44` |
/// | 3 | 根 `Deck` | 上两者**为空**（"声明了没有"） | `RunSetup.cs:44` 的 `: blueprint.Deck` |
///
/// "空 = 没声明、接着看下一处"不是我发明的哨兵，是参考自己的约定
/// （`RunBlueprint.cs:214-216`：*Empty (the default) ⇒ fall back to the blueprint's shared
/// Deck*）。解析本身在 [`Content::start_deck`]，形态差异（根 `Deck` 是 `F_TERMLIST`、
/// `Start.Deck` 是 `F_STRLIST`）在那里逐格解释。
///
/// # 调用方显式给的牌组**优先**
///
/// `plan.deck` 非空 ⇒ 走 [`build_fight`]，**内容里的牌组一个字节都不读**。这与参考同形
/// （`RunSetup.cs:44` 的 `start.Deck.Count > 0 ? start.Deck : …`：非空的声明词赢），
/// 也是"549 条手写牌组的测试一条都不许坏"的落地方式。
///
/// # 为什么不给 [`FightPlan`] 加一个字段
///
/// 加字段会让 `FightPlan { … }` 的**每一个字面量**都要跟着改（`rd-fightdump` 与
/// `rd-wasm` 各一处，本轮冻结）。所以"牌组来自内容"做成了第二条入口：它只多认出
/// 一个事实（"这次牌组从内容来"），不改 [`FightPlan`] 的形状。
///
/// # Errors
///
/// 内容里的起始牌组读不出来 ⇒ [`BattleError::Deck`]（三处候选都没有 / 都是空的 /
/// 某一跳形态坏了）；内容里点名的卡在 `CARD` 表里查不到 ⇒ [`BattleError::UnknownCard`]
/// （与手写牌组同一条闸门）；其余同 [`build_fight`]。
pub fn build_fight_from_content(
    state: &mut CombatState,
    content: &Content<'_>,
    plan: &FightPlan<'_>,
) -> Result<(), BattleError> {
    // 显式牌组优先（见上一节）。
    if !plan.deck.is_empty() {
        return build_fight(state, content, plan);
    }
    // 三处候选的**根键名**留在这里而不是 `content.rs`：`native/sts_content_check.py` 的
    // 第 4 层（INERT）判定"内核读了这个根键"的唯一证据，就是内核规则代码里出现
    // `root_by_name("<Key>")`。把这三个名字挪进 `content.rs`（那一层把它排除在扫描之外）
    // ⇒ 闸门再也看不见消费者 ⇒ 清单里"内核零消费者"那三条会一直**是假话**。
    let roots = DeckRoots {
        characters: content.root_by_name("Characters"),
        start: content.root_by_name("Start"),
        deck: content.root_by_name("Deck"),
    };
    let deck = content.start_deck(roots).map_err(BattleError::Deck)?;
    build_fight_with(state, content, plan, DeckPath::new_content(deck))
}

/// 建战斗的**唯一**实现体：两条入口只差 `deck` 这一格。
fn build_fight_with(
    state: &mut CombatState,
    content: &Content<'_>,
    plan: &FightPlan<'_>,
    deck: DeckPath<'_>,
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
    // 步 6 的判定（`MoveInnateCardsToTop`）：参考的**挪牌**必须在洗牌之后（`:45-47`）。
    // `innate` §144 起是**真的挪**，不再在步 0 拒绝；`x_cost` §146 起默认被支持，
    // 也不再在这里被拒 —— 见下面步 6b。
    // 蓝图里"喂回合机"的两项能不能被表达（抽牌数、补能表）—— 在这里先算一遍配置，
    // 免得建完一局才发现那条路通向 `Turn(Host(Unsupported))`。
    let _ = turn_config_for(plan)?;
    // 牌定义表（`:75`）。参考在这一步**不查**（它的注册表就是蓝图的一部分），
    // 内核的卡定义表**就是**镜像的 `CARD` 表，所以查不到必须响亮。
    //
    // ⚠️ 这条闸门对**两条入口都是同一条**：内容里点名的卡查不到也一样响亮失败
    // （那份内容自己点了一个不存在的卡 ⇒ 内容缺陷，不是"这张牌跳过"）。
    let mut declared = deck;
    while let Some(item) = declared.next_entry() {
        let (card, _count) = item?;
        if content.lookup_in(card, EK_CARD).is_none() {
            return Err(BattleError::UnknownCard(CardDefinitionId::new(card)?));
        }
    }

    // ── 步 1：`new CombatState(combatId, seed)`（`:13-17`）=====================
    // `CellExclusive` / `SimultaneousTeamTurns` 不进内核模型（规格 §1 的取舍），
    // 它们是**同时回合/格子战斗**的开关，v1 一个都不支持；蓝图里也没有这两个字段。
    //
    // ⚠️ 这里**不**写 `*state = CombatState::new(..)`：语义一样，但那样会把 184 KB 的
    // 空状态常量模板带进 `.wasm`（实测占 `rd_wasm.wasm` 的 33%）。`reset_in_place`
    // 逐字段清零，字节等价（`state.rs` 的 `reset_in_place_matches_new_field_for_field`）。
    state.reset_in_place(combat_id, plan.seed);

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
    let mut to_deal = deck;
    while let Some(item) = to_deal.next_entry() {
        let (card, count) = item?;
        let definition = CardDefinitionId::new(card)?;
        for _ in 0..count {
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

    // ── 步 6：MoveInnateCardsToTop（`:45-49`、`:93-104`）======================
    // 参考（`ScenarioCombatFactory.cs:91-104`）：
    //   ① 按**抽牌堆顺序**收集带 `innate` tag 的实例 id；
    //   ② **从后往前**逐个 `MoveCardToZone(DrawPile, Top)` —— 注释原话："Moving from last to
    //      first lands the first innate card at index 0"，即这样才保住它们之间的相对顺序。
    // 挪在**洗牌之后**（`:49`），这正是"起手必有它"的实现方式。
    move_innate_cards_to_top(state, content, &hero_id)?;

    // ── 步 6b：`x_cost`（§146 起是**真能力**，不再拒绝）========================
    // §144 时这里有一道 `reject_x_cost_deck`；§146 把 X 费做出来了（`play.rs` 算钱、
    // `expr` 的 `x.cost` 读值、`node.repeat` 跑 X 遍），所以那道闸**被删掉**。
    // 建战斗这一层现在不需要认识 X 费：一张 X 费牌和别的牌一样进抽牌堆。

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

/// §193/§195.1：把内容里写的**开局计数**落到战斗员身上 —— 掷骰（`Rolls`）与明写的值（`Counters`）。
///
/// 两件事一起做，是因为它们的位置、失败桶、选档规则都一样，而分开写就会出现**两份**"找到这个
/// 敌人并把数写上去"的代码（§161.3 的老路）。唯一必须分开的是 RNG 账：掷骰花步、固定值不花。
///
/// 内容的一行（`ENCT[i].Enemies[j].Rolls[k]`）是 `{Key, Min, Max, AscensionMin}`；这里按
/// `state.ascension()` 选好档位（[`Content::spawn_rolls`]），抽一次，把值写进**那个敌人**的
/// 同名计数器。动作节目里的 `dealDamage{Amount: combatantCounter(source, Key)}` 之后读到的就是它。
///
/// 返回值是**抽了几次**（不是"写了几条"）：一条被升档阴影掉的条目、一个没有敌人的槽位都不抽，
/// 所以"`random_step` 涨了几个"与这个数逐个相等 —— 这是本函数唯一的可观察副作用账本。
///
/// # 为什么在**建战斗之后、开第一回合之前**
///
/// * 战斗员得先存在（要按 `ENCT` 的 id 找到它）；
/// * 值必须在第一次 `bite` 之前就在（否则第一次读到 0）；
/// * 它**不**是回合开始动作：`apply_starting_statuses`（§175b）在同一位置，理由一样。
///
/// # 为什么直接写、不排队
///
/// `EffectRequest::SetCombatantCounter` 是**入队**的，而伤害节点的 `Amount` 在**入队时**求值
/// （参考的顺序）。把掷骰也排队 ⇒ 同一段节目里"先掷后打"读到的永远是旧值（0），而且没有任何
/// 数值测试会红 —— 只有"伤害突然变成 0"这种看起来像内容错的假象。所以这里直接写。
///
/// # Errors
///
/// 内容读不出来 / 值域不合法 / 计数器容器满 ⇒ 对应的桶。**不吞**任何一条：一条读不懂的掷骰
/// 会让某一个招式的伤害静默变成 0，而那种错只会表现为"这一局有点奇怪"。
/// §195.1：建战斗时的**计数**账本，一次跑完两条列表。
///
/// `draws = 0` 的局是常态（本内容只有两只怪掷骰）：`Counters` 是**明写的数**，一个随机步都不该花。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct SpawnSetup {
    /// `Rolls` 抽了几次（= `random_step` 涨了几个）。
    pub draws: u32,
    /// `Counters` 写了几条（不消耗随机步）。
    pub counters: u32,
}

pub fn apply_spawn_setup(
    state: &mut CombatState,
    content: &Content<'_>,
    encounter: u32,
) -> Result<SpawnSetup, SpawnRollError> {
    let enemies = content
        .encounter_enemies(encounter)
        .map_err(SpawnRollError::Encounter)?;
    let ascension = i32::from(state.ascension());
    let mut draws = 0u32;
    let mut counters_written = 0u32;
    for slot in 0..enemies.len() {
        let spec = enemies.get(slot).map_err(SpawnRollError::Encounter)?;
        let id = spec.id().map_err(SpawnRollError::Encounter)?;
        let mut rolls = [crate::content::SpawnRoll {
            key: "",
            min: 0,
            max: 0,
        }; crate::content::MAX_SPAWN_ROLLS];
        // §195.1: the fixed counters first -- they cost no random step, so their order relative to
        // the rolls is unobservable; doing them first keeps the `draws` bookkeeping in one tail
        // (the RNG ledger is the thing a reader has to be able to check).
        let mut fixed = [crate::content::SpawnCounter { key: "", value: 0 };
            crate::content::MAX_SPAWN_COUNTERS];
        let fixed_count = content
            .spawn_counters(spec, ascension, &mut fixed)
            .map_err(SpawnRollError::Encounter)?;
        if fixed_count > 0 {
            let combatant = CombatantId::new(id).map_err(|_| SpawnRollError::BadCombatantId)?;
            if state.combatant(&combatant).is_none() {
                return Err(SpawnRollError::MissingCombatant);
            }
            for entry in fixed.iter().take(fixed_count) {
                let key = crate::state::CounterId::new(entry.key)?;
                state
                    .combatant_mut(&combatant)
                    .ok_or(SpawnRollError::MissingCombatant)?
                    .set_counter(key, entry.value)?;
                counters_written = counters_written.saturating_add(1);
            }
        }
        let count = content
            .spawn_rolls(spec, ascension, &mut rolls)
            .map_err(SpawnRollError::Encounter)?;
        if count == 0 {
            continue;
        }
        let combatant = CombatantId::new(id).map_err(|_| SpawnRollError::BadCombatantId)?;
        if state.combatant(&combatant).is_none() {
            // 记录里有掷骰却没有这个战斗员 ⇒ 调用方建的局与遭遇不是同一份。不猜一个目标。
            return Err(SpawnRollError::MissingCombatant);
        }
        for roll in rolls.iter().take(count) {
            let span = roll
                .max
                .checked_sub(roll.min)
                .and_then(|width| width.checked_add(1))
                .ok_or(SpawnRollError::BadRange {
                    min: roll.min,
                    max: roll.max,
                })?;
            if span < 1 || span > crate::content::MAX_SPAWN_ROLL_SPAN {
                return Err(SpawnRollError::BadRange {
                    min: roll.min,
                    max: roll.max,
                });
            }
            // 一次抽签 = 一次完整置换（`CombatRandom` 的形状），然后推进一步。
            let pick = crate::rng::shuffled_pick_index(
                span as usize,
                state.random_seed,
                state.random_step,
            );
            state.random_step = state.random_step.saturating_add(1);
            draws = draws.saturating_add(1);
            let value = roll.min + pick as i32;
            let key = crate::state::CounterId::new(roll.key)?;
            state
                .combatant_mut(&combatant)
                .ok_or(SpawnRollError::MissingCombatant)?
                .set_counter(key, value)?;
        }
    }
    Ok(SpawnSetup {
        draws,
        counters: counters_written,
    })
}

/// [`apply_spawn_setup`] 的失败桶。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SpawnRollError {
    /// 内容侧读不出来（`Rolls` 的形态/字段坏了）。
    Encounter(crate::content::EncounterError),
    /// `ENCT` 里点名的敌人不在这个局里。
    MissingCombatant,
    /// 敌人 id 不是能用的战斗员 id。
    BadCombatantId,
    /// `Max < Min`（或宽度超过 [`crate::content::MAX_SPAWN_ROLL_SPAN`]）。
    BadRange {
        /// 内容写的下界。
        min: i32,
        /// 内容写的上界。
        max: i32,
    },
    /// 计数器键不是能用的 id（太长 / 非 ASCII）。
    Counter(crate::state::CapacityError),
    /// 计数器容器满。
    Capacity(crate::state::CapacityError),
}

impl From<crate::state::CapacityError> for SpawnRollError {
    fn from(error: crate::state::CapacityError) -> Self {
        Self::Capacity(error)
    }
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

/// 把带 `innate` tag 的牌挪到抽牌堆顶（`MoveInnateCardsToTop`，`:45-49`、`:91-104`）。
///
/// 逐行照参考：
/// * 按**抽牌堆顺序**收集（`:96-100` 的 `zones.DrawPile.Where(...)`）；
/// * **从后往前**逐个挪到顶部（`:102-103`，注释解释了为什么是倒序：倒着挪，第一张 innate
///   才会落在 index 0，它们之间的相对顺序才保得住）；
/// * 挪在**洗牌之后** —— 这正是"起手必有它"的实现方式。
///
/// `MAX_CARDS_PER_ZONE` 是抽牌堆的容量（`state.rs` 的同一常量），所以这个快照不会截断。
fn move_innate_cards_to_top(
    state: &mut CombatState,
    content: &Content<'_>,
    owner: &CombatantId,
) -> Result<(), BattleError> {
    let mut innate = [CardSlot::from_index(0); MAX_CARDS_PER_ZONE];
    let mut count = 0usize;
    {
        let Some(zones) = state.card_zones(owner) else {
            return Err(BattleError::Capacity(CapacityError::MissingCombatant));
        };
        for index in 0..zones.count(CardZone::DrawPile) {
            let Some(slot) = zones.slot_at(CardZone::DrawPile, index) else {
                continue;
            };
            let Some(card) = state.card(slot) else {
                continue;
            };
            match card_has_tag(content, card.definition_id.as_str(), INNATE_TAG) {
                Ok(true) => {
                    let Some(cell) = innate.get_mut(count) else {
                        return Err(BattleError::Capacity(CapacityError::Full(
                            crate::state::Container::CardsInZone(CardZone::DrawPile),
                        )));
                    };
                    *cell = slot;
                    count += 1;
                }
                Ok(false) => {}
                Err(()) => return Err(content_error()),
            }
        }
    }
    // 倒着挪：第一张 innate 最后挪 ⇒ 落在 index 0。
    for slot in innate[..count].iter().rev() {
        state.move_card(
            owner,
            CardZone::DrawPile,
            CardZone::DrawPile,
            *slot,
            ZonePlacement::Top,
        )?;
    }
    Ok(())
}

// §146 删掉了 `reject_x_cost_deck`：X 费不再是"内核造不出来的机制"。

/// 建战斗时牌组的**实际来源** —— [`build_fight`] 与 [`build_fight_from_content`]
/// 唯一的差别就是这一格。
///
/// 两项都只用**借用**表示（`&[DeckEntry]` / [`StartDeck`]），所以这个枚举不占
/// `CombatState` 的任何一个字节：SRAM 上界（`state.rs` 的 `state_fits_the_sram_plan`）
/// 与本轮之前**逐字节相同**。
#[derive(Clone, Copy, Debug)]
enum DeckPath<'a> {
    /// 调用方手写（[`FightPlan::deck`]）：一项 = `(卡定义 id, 张数)`。
    Plan {
        /// 蓝图里的 `(定义, 张数)` 项。
        entries: &'a [DeckEntry<'a>],
        /// 已取到第几项。
        next: usize,
    },
    /// 内容声明的起始牌组（[`Content::start_deck`]）：一项 = **一张牌**（张数恒 1）。
    Content {
        /// 内容里的那份牌组。
        deck: StartDeck<'a>,
        /// 已取到第几张。
        next: usize,
    },
}

impl<'a> DeckPath<'a> {
    /// 手写牌组。
    const fn new_plan(entries: &'a [DeckEntry<'a>]) -> Self {
        Self::Plan { entries, next: 0 }
    }

    /// 内容牌组。
    const fn new_content(deck: StartDeck<'a>) -> Self {
        Self::Content { deck, next: 0 }
    }

    /// 下一项：`(卡定义 id, 张数)`。`None` = 读完了；`Some(Err(..))` = 内容形态坏了。
    ///
    /// 取两份（`let mut cursor = deck;`）就是从头再读一遍：这个类型是 `Copy`，
    /// 建战斗要过三遍（innate 判定 / 定义是否存在 / 真正发牌）而每一遍都不能共享游标。
    fn next_entry(&mut self) -> Option<Result<(&'a str, u16), BattleError>> {
        match self {
            Self::Plan { entries, next } => {
                let entry = entries.get(*next)?;
                *next = next.saturating_add(1);
                Some(Ok((entry.card, entry.count)))
            }
            Self::Content { deck, next } => {
                if *next >= deck.len() {
                    return None;
                }
                let index = *next;
                *next = next.saturating_add(1);
                Some(
                    deck.get(index)
                        .map(|card| (card, 1u16))
                        .map_err(BattleError::Deck),
                )
            }
        }
    }
}

/// 蓝图 → 回合机的 [`TurnConfig`]（`run_fight` 唯一一处把蓝图喂给回合机的地方）。
///
/// 三项**由蓝图说了算**：`draw_per_turn` ← [`FightPlan::cards_drawn_per_turn`]；
/// `energy` / `energy_refill` ← [`FightPlan::turn_start_refills`] 的第一条。
/// 两项仍是标准包的：`block_pool` = `standard.block`、`max_hand_size` = `i32::MAX`
/// （镜像里没有 `MaxHandSize` 法令，见 [`standard_turn_config`]）—— 蓝图没有这两个字段。
///
/// 三处如实说明（都不是"以后再说"，是**今天就是这样**）：
///
/// 1. **空补能表**：回合机没有"完全不补"这条路径（参考的标准包恒注册
///    `RefillResourceOnTurnStartedHandler`，`StandardCombatPackage.cs:124`），所以空表
///    保留标准包的 3。而只要蓝图给的能量池带 `max`，补到几点就由 `max` 决定
///    （`turn.rs:438-449`：`let base = pool.pool.max.unwrap_or(config.energy_refill)`）
///    ⇒ 那时这个字段**观察不可见**。"空 = 不补"这句蓝图文档因此只能近似表达。
/// 2. **多于一条**：`TurnConfig` 只有一个能量资源（回合机只补一个池）⇒ 第二条及以后
///    **表达不了**。静默丢掉等于让蓝图说谎，所以拒绝（[`unsupported`]）。
/// 3. **负数抽牌**：`turn.rs:477-480` 把 `requested` 夹到 0（"一张都不抽"）；参考在
///    `StandardCombatPackage.cs:9-11` 构造包时就抛。两者都不 panic，这里不额外拒绝。
///
/// # Errors
///
/// 补能资源 id 超容量 ⇒ [`BattleError::Capacity`]；补能表多于一条 ⇒ `Turn(Host(Unsupported))`。
fn turn_config_for(plan: &FightPlan<'_>) -> Result<TurnConfig, BattleError> {
    let mut config = standard_turn_config()?;
    config.draw_per_turn = plan.cards_drawn_per_turn;
    match plan.turn_start_refills {
        // 空表：保留标准包那一组（理由见上第 1 条）。
        [] => {}
        [only] => {
            config.energy = only.0;
            config.energy_refill = only.1;
        }
        // 回合机只有一个能量资源，第二条表达不了。
        _ => return Err(unsupported()),
    }
    Ok(config)
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
/// 蓝图要两处信息：回合机的配置（[`turn_config_for`]）与**英雄 id**（`plan.hero.id`，
/// 对应参考 `ScenarioRunner.cs:29` 的 `compiled.Hero.CombatantId`）。两者都只从蓝图来
/// —— 不从状态里猜（"回合序里第一个 player 队"是 2026-10-18 之前那版的推断，已删）。
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
/// 一步的问题超 [`MAX_PROBLEMS_PER_STEP`] ⇒ [`BattleError::TooManyProblems`]；蓝图里
/// 读不出的东西（`plan.hero.id` 超容量、补能表多于一条）⇒ `Capacity` / `Turn(Host(..))`。
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
    plan: &FightPlan<'_>,
    steps: &[Step<'_>],
    host: &mut H,
    out: &mut FightOutcome,
) -> Result<(), BattleError> {
    if steps.len() > MAX_STEPS {
        return Err(BattleError::TooManySteps);
    }
    let config = turn_config_for(plan)?;
    // `ScenarioRunner.cs:29`：参考先取一次英雄 id，之后每一步都用它。
    let hero = CombatantId::new(plan.hero.id)?;
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
        } else if !turn::is_alive(state, &hero) {
            // `:45` 是 `!TryGetCombatant(heroId, out hero) || !hero.IsAlive`。英雄是蓝图给的，
            // 所以第一条只在"状态被别处改坏"时成立，仍然照抄：两者都记同一条。
            problems.push(Problem::HeroDowned)?;
            context_of(state)
        } else {
            match execute_step(state, content, &config, &step, host, &hero, &mut problems) {
                Ok(context) => context,
                // 信封错误不许被吞成 StepThrew：那会把"问题记不下了"伪装成"这一步抛了"。
                Err(BattleError::TooManyProblems) => return Err(BattleError::TooManyProblems),
                // `:57-62`：异常 → 一条问题 + **当下的**上下文（`:61`），循环继续。
                Err(error) => {
                    // 记下类别**再**吞掉：两个流（给玩家的 `Problem`、给宿主的类别）在这一处分开。
                    let cause = StepCause::of(&error);
                    problems.push(Problem::StepThrew)?;
                    if let Some(slot) = out.step_causes.get_mut(index) {
                        *slot = cause;
                    }
                    if let Some(slot) = out.step_capacity.get_mut(index) {
                        *slot = StepCause::capacity_code(&error);
                    }
                    if let Some(slot) = out.step_codes.get_mut(index) {
                        *slot = play_code(&error);
                    }
                    context_of(state)
                }
            }
        };

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
    /// 按**定义**点名（参考的形状，见 [`Step::HeroPlays`]）。
    card: &'a str,
    /// 打**这一份副本**（[`Step::HeroPlaysInstance`]）；`Some` 时 `card` 被忽略。
    ///
    /// 不并进 `card` 是因为两者的**查法不同**：定义要"找第一张"，实例要"找那一张"，
    /// 而后者找不到时必须报 `CardNotInHand`，不能悄悄退回按定义找。
    instance: Option<CardInstanceId>,
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
    hero: &CombatantId,
    problems: &mut Problems,
) -> Result<Context, BattleError> {
    match *step {
        Step::HeroPlays { card, target } => hero_plays(
            state,
            content,
            config,
            Play {
                card,
                instance: None,
                target,
            },
            host,
            hero,
            problems,
        ),
        Step::HeroPlaysInstance { card, target } => hero_plays(
            state,
            content,
            config,
            Play {
                card: "",
                instance: Some(card),
                target,
            },
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
        Step::EndOneTurn => end_one_turn(state, config, host, problems),
    }
}

/// `ExecuteHeroPlays`（`ScenarioRunner.cs:95-128`）。
fn hero_plays<H: TurnHost>(
    state: &mut CombatState,
    content: &Content<'_>,
    config: &TurnConfig,
    play: Play<'_>,
    host: &mut H,
    hero: &CombatantId,
    problems: &mut Problems,
) -> Result<Context, BattleError> {
    let Play {
        card,
        instance,
        target,
    } = play;

    // `:102-103`：行动者不是英雄 ⇒ 记一条，**但继续**（参考没有 return）。
    if state.active_combatant_id.as_ref() != Some(hero) {
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
    //
    // §161.4：`instance` 非空时改成"找**这一张**"。找不到同样报 `CardNotInHand` —— **绝不**退回
    // 按定义找：那会把"这个位置已经空了"变成"打了别的一张牌"，正是死按钮的另一种形状。
    let instance = match instance {
        Some(id) => {
            let in_hand = state
                .card_zones(hero)
                .map(|zones| {
                    zones
                        .slots(CardZone::Hand)
                        .iter()
                        .any(|raw| state.card(CardSlot::from_index(*raw)).map(|c| c.id == id) == Some(true))
                })
                .unwrap_or(false);
            if in_hand {
                Some(id)
            } else {
                None
            }
        }
        None => first_card_in_hand(state, hero, card),
    };
    let Some(instance) = instance else {
        problems.push(Problem::CardNotInHand)?; // `:113-117`
        return Ok(context);
    };

    // `:121-122`：入队 + 排空。内核的**请求面**替掉了"入队一条 PlayCard 请求"
    // （`ScenarioRunner.cs:121` 的 `EnqueueEffect(PlayCardEffectRequest)`，见 `play.rs` 的四笔账），
    // 但**排空是真的**：出牌期间 `exec.rs` 会把 `DamageDealt` 入队（`DamageEffects.cs:186-194`），
    // 那批事件必须在这里排掉 —— 参考的 `ExecuteHeroPlays` 也是"入队/执行一步，然后排空"。
    let request = PlayRequest::new(*hero, instance, parse_target(target)?);
    let report = play::try_play_card(state, Some(content), &request)?;
    // 排空：`DamageDealt` 的触发器（`doubt` 就在这上面）在这里跑。
    // ⚠️ 顺序是 `排空 → settle_result`：参考的队列循环条件是 `Result == Ongoing`
    // （`CombatEventHandling.cs:97`），而胜负可能**在排空里**被触发器节目决定。
    host.resolve_pending_queues(state)?;
    // 一次出牌就是一次排空（参考在队列排空时判胜负，`CombatStateEffects.cs:28-60`）。
    settle_result(state);
    // **`node.endTurn` 的兑现点**（本内核自己的机制，`port-plan.md` §125）：节目只是把
    // `end_turn_requested` 立起来，回合的推进留在这里 —— 方向和 `state.result` 一致（效果层立旗，
    // 循环层推进），而且"谁兑现了请求"这件事是可读的。
    if state.end_turn_requested && state.result == CombatResult::Ongoing {
        state.end_turn_requested = false;
        state.forced_turn_ends = state.forced_turn_ends.saturating_add(1);
        end_turn_and_start_next(state, config, host)?;
    }
    // `:124` 的原话是 `if (outcome.Value is { WasPlayed: false })` —— 它匹配的是 **false**，
    // 不匹配 **null**。而"战斗在这一步里已经结束"时参考的队列循环
    // （`CombatEventHandling.cs:99-111`）根本不会解析那个请求 ⇒ outcome 是 null ⇒
    // **不记问题**。内核的请求面把这种"没解析"折成 `NOT_PLAYED`，所以这里必须再问一次
    // "战斗是不是还在进行"，否则会凭空多记一条参考里没有的 `CardNotPlayed`。
    if !report.played && state.result == CombatResult::Ongoing {
        problems.push(Problem::CardNotPlayed)?; // `:124-125`
    }
    Ok(context)
}

/// `ExecuteHeroEndsTurn`（`ScenarioRunner.cs:130-146`）。
fn hero_ends_turn<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
    hero: &CombatantId,
    problems: &mut Problems,
) -> Result<Context, BattleError> {
    // `:132-133`：记一条，但**继续**（参考没有 return）。
    if state.active_combatant_id.as_ref() != Some(hero) {
        problems.push(Problem::NotHeroTurnToEnd)?;
    }

    ensure_turn_started(state, config, host)?; // `:139`
    let context = context_of(state); // `:140`（在推进之前！）

    // `:141-143`：开回合本身可能结束战斗（"turn-start 触发器打死最后一个敌人"），
    // 那就**不要**在结束了的战斗上推回合。`state.result` 之所以是新的，是因为
    // `ensure_turn_started` 之后立刻算过一次胜负（见 [`settle_result`]）。
    if state.result == CombatResult::Ongoing {
        end_turn_and_start_next(state, config, host)?; // `:144`
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
    hero: &CombatantId,
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
    // `:191-192`：入队 + 排空 ⇒ 内核就地执行动作节目（`intent::execute_action` 与参考同一个执行器），
    // 再在这里**排空**它入队的事件。这一步是 `CARD_MULTI` 那 10 格的根因：
    // 敌人出手 ⇒ `exec.rs` 入队 `DamageDealt`（`DamageEffects.cs:186-194`）⇒
    // 戴着 `doubt` 的敌人（= 出手方）触发 `modifyStatusStacks(doubt, -1)`。
    intent::execute_action(
        state,
        content,
        &enemy_id,
        u32::from(entry.index),
        parse_target(target)?,
    )
    .map_err(intent_failure)?;
    host.resolve_pending_queues(state)?;
    // 敌人动作也是一次排空 ⇒ 立刻判一次胜负（英雄可能在这一下里倒下）。
    settle_result(state);
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
    hero: &CombatantId,
    problems: &mut Problems,
) -> Result<Context, BattleError> {
    ensure_turn_started(state, config, host)?; // `:202`
    let context = context_of(state); // `:203`（在推进之前！）

    // `:206-207`：已经是英雄的回合 ⇒ 先结束它，这样"一整轮"才真的过去。
    if state.active_combatant_id.as_ref() == Some(hero) && state.result == CombatResult::Ongoing {
        end_turn_and_start_next(state, config, host)?;
    }

    // `:209-219`：只要还在进行中且行动者不是英雄，就一直结束+开始下一个。
    // `guard > TurnOrder.Count + 2` ⇒ 记一条并停（没有这个上限，一个"永远把下一个单位
    // 打死"的触发器会让这里转不出来）。
    //
    // ⚠️ 条件里的 `state.result == Ongoing` 每圈都**真的**是新的：`end_turn_and_start_next`
    // 之后立刻算过一次胜负。这就是"某一步里第一次推回合就把敌人打死"之后**不再继续推**
    // 的那个守门点（参考的 `:211` 同形）。
    let mut guard = 0i32;
    let max_steps = state.turn_order().len() as i32 + 2;
    while state.result == CombatResult::Ongoing && state.active_combatant_id.as_ref() != Some(hero) {
        end_turn_and_start_next(state, config, host)?;
        guard += 1;
        if guard > max_steps {
            problems.push(Problem::CouldNotWrapToHero)?; // `:216`
            break;
        }
    }
    Ok(context)
}

/// [`Step::EndOneTurn`]：**只**结束一个回合，停在下一个活着的战斗员身上。
///
/// 参考里没有"只推一步"这个脚本步（`ScenarioRunner` 的三个步进都得带着目标），但它的
/// **推进本身**是逐跳的：`AdvanceTurnsUntilActive`（`:226-252`）就是
/// `while (Ongoing && active != target) EndCurrentTurnAndStartNextTurn()`，
/// 每一跳之后重新读 `Result`。本函数是同一段循环，只是判据从"轮到 target 了吗"
/// 换成"轮到一个**活着**的战斗员了吗" —— 因此它**不新增任何战斗语义**。
///
/// 三条守门点（都在循环里，顺序就是语义）：
/// 1. `state.result != Ongoing` ⇒ 停（`:230` 的条件前一半）；
/// 2. **第一圈总是推一格**（这一步的语义就是"结束当前这一回合"，无论当前上场的是英雄
///    还是敌人）；之后的圈只在接手的战斗员**已倒下**时继续推 —— 那就是"跳过已倒下的"；
/// 3. 每一跳都走 [`end_turn_and_start_next`]（它内部立刻复核胜负），所以第 1 条看到的是
///    **新值** —— "某个敌人的 turn-start 触发器把最后一个敌人打死"之后不会再往前推。
///
/// 守卫（`turn_order.len() + 2`）与 `NextRound` 的 `:214-218` 同形：正常情况下不可达，
/// 但"转不出来"必须留一条响亮的路（[`Problem::CouldNotEndOneTurn`]），不许安静地停。
fn end_one_turn<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
    problems: &mut Problems,
) -> Result<Context, BattleError> {
    ensure_turn_started(state, config, host)?; // 与 `HeroEndsTurn` / `NextRound` 同一入口
    let context = context_of(state); // 执行**前**的上下文（`ScenarioRunner.cs:203` 同形）

    let max_steps = state.turn_order().len() as i32 + 2;
    let mut guard = 0i32;
    loop {
        if state.result != CombatResult::Ongoing {
            break;
        }
        // `active_combatant_id == None`（状态被别处改坏）**不在这里兜底**：让回合机的
        // `ensure_active_combatant` 去响亮失败，别把"没有行动者"伪装成"没什么可推的"。
        let skip_dead = match state.active_combatant_id {
            Some(active) => !turn::is_alive(state, &active),
            None => true,
        };
        // 第一圈**总是**推（这一步的语义就是"结束当前这一回合"）；之后的圈只在
        // 接手的战斗员已经倒下时继续推（"跳过已倒下的"）。
        if guard > 0 && !skip_dead {
            break;
        }
        end_turn_and_start_next(state, config, host)?;
        guard += 1;
        if guard > max_steps {
            problems.push(Problem::CouldNotEndOneTurn)?;
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
    hero: &CombatantId,
    problems: &mut Problems,
) -> Result<(), BattleError> {
    ensure_turn_started(state, config, host)?; // `:233`

    let mut guard = 0i32;
    let max_steps = state.turn_order().len() as i32 + 1; // `:236`（注意是 +1，不是 +2）
    while state.result == CombatResult::Ongoing && state.active_combatant_id.as_ref() != Some(target)
    {
        // `:239-243`：轮到英雄 ⇒ 记一条"这仍然是英雄的回合"并放弃。
        // 与 `:248` 的"推不到"是**两条不同的问题**（修法相反），所以两个变体。
        if state.active_combatant_id.as_ref() == Some(hero) {
            problems.push(Problem::StillHeroTurn)?;
            return Ok(());
        }
        end_turn_and_start_next(state, config, host)?; // `:245`
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
///
/// 开完立刻判一次胜负：`ScenarioRunner.cs:141-143` 的注释说的正是这件事
/// ——"starting the turn can end combat (a turn-start trigger downs the last enemy)"。
/// 开始当前回合（若还停在 `WaitingToStartTurn`）。
///
/// # 为什么这是一个**公开**入口，而不是 `build_fight` 的一部分
///
/// `build_fight` 故意停在 `WaitingToStartTurn`（见文件头 §1），因为参考的 scenario 驱动器
/// （`ScenarioRunner.cs:105` `EnsureTurnStarted`）就是**第一次出牌时**才开始回合并抽手牌 ——
/// 四层对拍（`FIGHT_DIFF` 182 例）比的就是"同样的步骤序列，两边状态一致"，所以构建语义必须与它对齐。
///
/// 但 **StS 不是这样**：战斗一开始英雄的第 1 回合就开始了，玩家立刻看到 5 张手牌。参考那套
/// DSL 是给对拍用的脚手架，不是游戏流程。⇒ 面向玩家的驱动器（浏览器那一侧）在构建之后调一次
/// 本函数，就把"回合 1 空手牌"这个只在参考 DSL 里成立的中间态消掉了。
///
/// 幂等：不在 `WaitingToStartTurn` 时什么也不做。
pub fn start_first_turn<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
) -> Result<(), BattleError> {
    ensure_turn_started(state, config, host)
}

fn ensure_turn_started<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
) -> Result<(), BattleError> {
    if state.result == CombatResult::Ongoing && state.turn_phase == CombatTurnPhase::WaitingToStartTurn
    {
        turn::start_current_turn(state, config, host)?;
        settle_result(state);
    }
    Ok(())
}

/// `EndCurrentTurnAndStartNextTurn` + **立刻判一次胜负**。
///
/// 单独包一层是 [`FROZEN_GAP_RESULT`] 的落点：参考在这条调用里会经过若干次队列排空，
/// 排空点上胜负就得是新的（否则 `:143`/`:206`/`:211`/`:237` 那些守门点看到的全是旧值）。
/// 内核没有队列，所以在**调用返回处**补一次 —— 这样上面四个守门点的判据与参考一致。
fn end_turn_and_start_next<H: TurnHost>(
    state: &mut CombatState,
    config: &TurnConfig,
    host: &mut H,
) -> Result<(), BattleError> {
    turn::end_current_turn_and_start_next(state, config, host)?;
    settle_result(state);
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

/// 算胜负（`UpdateStandardCombatResultOnLifecycleChangedHandler`，`CombatStateEffects.cs:28-60`）。
///
/// # ⚠️ 它**不再是唯一通道**（2026-10-19 改）
///
/// 规则本体现在在 [`exec::update_standard_combat_result`]，因为它必须在**战斗员倒下那一行**
/// 生效 —— 参考的链路是"`Downed` → `CombatantLifecycleChanged` 事件 → `SetCombatResult`
/// （`CombatStateEffects.cs:36-58`）→ `SetResult` 取消在飞帧（`CombatState.cs:358-367`）"，
/// 所以程序打死最后一个敌人时会**立刻**判胜、并且**立刻**停住后续节点。
///
/// 本函数保留的理由只剩一条：它是**幂等的复核**。参考的驱动层同样在每次引擎调用之后重算
/// 一次（`ScenarioRunner.cs:143`、`:206`、`:211`、`:237`），粒度见 [`FROZEN_GAP_RESULT`]。
/// 复核不会掩盖"漏判"：`settle_result` 只会在 `Result == Ongoing` 时动手，而
/// "程序中途停下来"这件事**只能**来自下判点那一次调用。
///
/// 逐行（与 `exec::update_standard_combat_result` 同一份，那里有完整出处）：
/// ```text
/// :36  Result != Ongoing            → return（只在"还没结束"时算）
/// :39  hasLivingPlayer = 玩家队还有活人
/// :41  hasLivingEnemy  = 敌人队还有活人
/// :43  两者都没有                    → Draw
/// :49  没有玩家                      → Defeat
/// :55  没有敌人                      → Victory
/// ```
fn settle_result(state: &mut CombatState) {
    exec::update_standard_combat_result(state);
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
    run_fight(state, content, plan, steps, host, out)
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
    use crate::content::{DeckError, DeckOrigin};
    use crate::hash::{sha256, to_hex_lower};
    use crate::host::Host;
    use crate::snapshot;
    use crate::state::CombatantLifecycleState;
    use crate::state::{StatusDefinitionId, StatusInstance, StatusInstanceId, StatusPolarity};
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
            run_fight(state, content, plan, core::slice::from_ref(step), host, &mut out)
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

    /// §161.4：**两份同定义副本，打的是哪一张**。
    ///
    /// `Step::HeroPlays` 是参考的形状（按定义找**第一张**，`ScenarioRunner.cs:109-111`），
    /// `Step::HeroPlaysInstance` 是页面需要的形状（按实例）。两者的差别只有在副本**可区分**时
    /// 才看得见 —— §161.4 的每副本价格是第一个让它可区分的东西，而差别本身是一个死按钮：
    /// 一张带折扣的 `paper_cut` 排在普通 `paper_cut` 后面时，玩家点了它，引擎打了前面那张。
    ///
    /// 所以这条测试**同时**钉住两半：按定义打第一张（照旧）、按实例打指定的那一张（新的）。
    #[test]
    fn the_by_instance_step_plays_the_named_copy_not_the_first_one() {
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
            combat_id: "copy_pick_01",
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
        let mut state = CombatState::new(CombatId::new("scratch").expect("短 id"), 0);
        build_fight(&mut state, &content, &plan).expect("蓝图与镜像必须一致");
        let hero = cid("hero");
        // Get a hand, then take the **last** card in it as "the one the player clicked".
        let mut host = Host::new(&content);
        let mut out = FightOutcome::new();
        run_fight(
            &mut state,
            &content,
            &plan,
            &[Step::NextRound],
            &mut host,
            &mut out,
        )
        .expect("开一回合");
        let hand: Vec<CardInstanceId> = state
            .card_zones(&hero)
            .expect("牌区")
            .slots(CardZone::Hand)
            .iter()
            .filter_map(|raw| state.card(CardSlot::from_index(*raw)))
            .map(|card| card.id)
            .collect();
        assert!(hand.len() >= 2, "手牌至少两张才有得选：{}", hand.len());
        let last = *hand.last().expect("非空");

        // 给**最后那张**挂一个 -1 的每副本价格（= 免费，`paper_cut` 印刷 1）。
        let (_, slot) = {
            let mut found = None;
            for zone in CardZone::ALL {
                for index in 0..state.card_zones(&hero).expect("牌区").count(zone) {
                    let Some(candidate) = state
                        .card_zones(&hero)
                        .expect("牌区")
                        .slot_at(zone, index)
                    else {
                        continue;
                    };
                    if state.card(candidate).map(|card| card.id) == Some(last) {
                        found = Some((zone, candidate));
                    }
                }
            }
            found.expect("最后那张还在牌区里")
        };
        state
            .card_mut(slot)
            .expect("卡在")
            .set_mark_counter(
                crate::state::CounterId::new(crate::state::CARD_COST_DELTA_COUNTER).expect("短"),
                -1,
            )
            .expect("写价格");

        let energy = |s: &CombatState| {
            s.combatant(&hero)
                .expect("英雄")
                .resources()
                .iter()
                .find(|pool| pool.key.as_str() == "standard.energy")
                .map_or(-1, |pool| pool.pool.current)
        };
        let before = energy(&state);

        // 按**实例**打那一张 ⇒ 免费（价格生效），所以能量不变。
        let mut out = FightOutcome::new();
        run_fight(
            &mut state,
            &content,
            &plan,
            &[Step::HeroPlaysInstance {
                card: last,
                target: Some("queue_imp"),
            }],
            &mut host,
            &mut out,
        )
        .expect("按实例打牌不该坏");
        assert_eq!(
            energy(&state),
            before,
            "打的是那张带折扣的副本：每副本价格必须生效"
        );
        assert_eq!(
            state.card_zones(&hero).expect("牌区").count(CardZone::Hand),
            hand.len() - 1,
            "手牌少一张"
        );

        // 反面：按**定义**打，拿的是手里第一张（普通价）⇒ 能量必须掉 1。
        let before = energy(&state);
        let mut out = FightOutcome::new();
        run_fight(
            &mut state,
            &content,
            &plan,
            &[Step::HeroPlays {
                card: "paper_cut",
                target: Some("queue_imp"),
            }],
            &mut host,
            &mut out,
        )
        .expect("按定义打牌不该坏");
        assert_eq!(
            energy(&state),
            before - 1,
            "按定义走的是**第一张**（没有折扣），所以照付 —— 两种 step 确实不同"
        );
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

    /// 手工给英雄挂一条**致死**的 `paperwork`（带 `damage_over_time` tag ⇒ turn-start 扣层数）。
    ///
    /// v1 的 `FightPlan` 没有"起始状态"字段（规格 §1 的取舍），所以"第一回合开场就被 DoT
    /// 打死"这个前置条件只能这样造 —— 与 `a_downed_hero_…` 手工按倒英雄是同一类做法。
    fn give_hero_lethal_paperwork(state: &mut CombatState, stacks: i32) {
        use crate::state::{StatusDefinitionId, StatusInstance, StatusInstanceId, StatusPolarity};
        let status = StatusInstance::new(
            StatusInstanceId::new("manual_dot").expect("短"),
            StatusDefinitionId::new("paperwork").expect("短"),
            StatusPolarity::Debuff,
        )
        .with_stacks(stacks);
        state
            .combatant_mut(&cid("hero"))
            .expect("英雄在")
            .push_status(status)
            .expect("状态槽够");
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

    /// **裁决 2 的守门点**：一步里"第一次推回合就把最后一个敌人打死"之后，
    /// 后面的推进**不再发生**。
    ///
    /// 场景（全真实内容）：敌人 5 血 + `permit_a38` 给 5 层 `paperwork`
    /// （带 `damage_over_time`）⇒ 它的**回合一开始**就被 DoT 打死，而它是**最后一个**敌人
    /// ⇒ 那一刻 `settle_result` 判 `Victory`。
    ///
    /// `NextRound` 此时还在它的 `while (Ongoing && active != hero)` 里。正确的实现
    /// 在判负之后**不再推进**：停在"敌人回合、敌人已倒"。错误的实现（胜负只在步末算）
    /// 会看不见终态，继续把敌人的回合也结束掉 ⇒ 绕回英雄的回合：
    /// `round` 变 2、`turn` 变 1、英雄重新抽 5 张。
    ///
    /// 所以这条断言的三个数（`round` / `turn` / 英雄手牌）在两种实现下**都不一样** ——
    /// 变异测试（把 `settle_result` 挪回步边界）会红。
    #[test]
    fn a_lethal_turn_start_stops_the_rest_of_that_steps_turn_advancement() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 5,
        }];
        let deck = [DeckEntry {
            card: "permit_a38",
            count: 12,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "lethal_turn_start",
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
            Step::NextRound,
        ];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        assert_eq!(trace.kinds(1), &[] as &[Problem], "推到它、开回合、DoT 打死它 —— 没有异常");
        assert_eq!(health(&state, "queue_imp"), 0);
        assert_eq!(trace.result, CombatResult::Victory);
        // 守门点在 `end_current_turn_and_start_next` **之后**：敌人的回合确实开起来了
        // （轮次没变、回合 2、行动者是它），但**没有**再被结束。
        assert_eq!(state.current_round, 1, "没有绕回新一轮");
        assert_eq!(state.current_turn, 2, "停在敌人那一回合");
        assert_eq!(state.active_combatant_id, Some(cid("queue_imp")));
        // 英雄的手牌在结束回合时被弃掉了，而且**没有**因为"又轮到英雄"而重抽 5 张。
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            0,
            "英雄没有重新抽牌 ⇒ 这一轮没绕回来"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::DrawPile),
            7,
            "12 张抽 5 张 ⇒ 还剩 7；错误实现会再抽 5 张、只剩 2"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::DiscardPile),
            5,
            "出了 1 张 + 回合末弃了手里 4 张"
        );
    }

    /// **`CombatEndedBeforeEnemy`**（`:166-170`）：推进到敌人的路上战斗就结束了。
    ///
    /// 这条分支要求"最后一个活着的敌人在**推进内部**死掉"，所以场景必须精确：
    ///
    /// * 两个敌人各 2 血，各上 **2 层** `paperwork`（`form_12_b+`：0 费、2 层、消耗），
    ///   而 DoT 金额 = 层数 ⇒ 谁在自己回合开场都会当场倒下；
    /// * `HeroEndsTurn` 只推到**第一个**敌人（X）⇒ X 死在自己的回合开场，而 Y 还活着
    ///   ⇒ 那一格必须仍是 `Ongoing`（否则走不到 `EnemyActs`）；
    /// * 接着 `EnemyActs{Y}`：推进时先把"已经倒下但仍占着行动位"的 X 的回合结束掉，
    ///   再开 Y 的回合 ⇒ Y 也倒在自己的回合开场，而它是**最后一个** ⇒ `Victory`。
    ///
    /// 判决发生在 `:163` 的推进**内部** ⇒ 回到 `:166` 时结果已不是 `Ongoing`
    /// ⇒ 记 `CombatEndedBeforeEnemy`（不是 `:172` 的 `CannotReachEnemyTurn`，也不是
    /// `:178` 的 `EnemyNotAlive`）。
    #[test]
    fn combat_can_end_while_advancing_to_the_enemy() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [
            PlanCombatant {
                id: "queue_imp",
                max_health: 2,
            },
            PlanCombatant {
                id: "stamp_goblin",
                max_health: 2,
            },
        ];
        // 0 费、2 层、落区 ExhaustPile：两次都打得起（能量一点不动）。
        let deck = [DeckEntry {
            card: "form_12_b+",
            count: 5,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "ends_while_advancing",
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
                card: "form_12_b+",
                target: Some("queue_imp"),
            },
            Step::HeroPlays {
                card: "form_12_b+",
                target: Some("stamp_goblin"),
            },
            // 推到 X：X 死在自己的回合开场，Y 还活着 ⇒ Ongoing。
            Step::HeroEndsTurn,
            // 再从"已倒下的 X 还占着行动位"推进到 Y：Y 死在自己的回合开场 ⇒ 全灭。
            Step::EnemyActs {
                enemy: "stamp_goblin",
                action: "stamp_goblin.rubber_stamp_rush",
                target: Some("hero"),
            },
        ];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        // 步 2（HeroEndsTurn）之后：X 倒了，但战斗还在继续 —— 这一步不该有终态。
        // ⚠️ 中间态只能从 `trace` 取（`drive` 会把整个脚本跑完，`state` 是最后一步之后的样子）。
        assert_eq!(trace.kinds(2), &[] as &[Problem]);
        assert_eq!(trace.hp(2, "queue_imp"), 0);
        assert_eq!(trace.hp(2, "stamp_goblin"), 2, "Y 还活着");
        // 步 3：推进内部全灭 ⇒ `:166` 先命中。
        assert_eq!(trace.kinds(3), &[Problem::CombatEndedBeforeEnemy]);
        assert_eq!(trace.result, CombatResult::Victory);
        assert_eq!(trace.hp(3, "stamp_goblin"), 0);
        assert_eq!(trace.hp(3, "hero"), 70, "Y 的动作一下都没出");
    }

    /// **`Step::EndOneTurn` 的核心判据**：一步只让**一个**战斗员上场（多敌人战斗的地基）。
    ///
    /// 场景（全真实内容；`queue_imp.desk_jab` = 8 伤、`stamp_goblin.rubber_stamp_rush` = 5 伤，
    /// 都是实测的 `dealDamage{const}`）：
    ///
    /// ```text
    /// 步 0  EndOneTurn                 英雄回合结束 ⇒ 行动位给 queue_imp（回合 2）
    /// 步 1  EnemyActs{queue_imp}       英雄 70 - 8 = 62
    /// 步 2  EndOneTurn                 **只**结束 imp 的回合 ⇒ 行动位给 goblin（回合 3），
    ///                                  英雄一滴血都不该掉（goblin 还没出手）
    /// 步 3  EnemyActs{stamp_goblin}    英雄 62 - 5 = 57
    /// ```
    ///
    /// 三种错误实现都会红，而且各自红的数不同：
    /// * 把 `EndOneTurn` 实现成 `NextRound`（一路推回英雄）⇒ 步 2 之后 `round=2`/`turn=1`、
    ///   行动者变回英雄，步 3 撞 `StillHeroTurn`，英雄停在 62；
    /// * 把它实现成"什么都不做"⇒ 步 3 的 `EnemyActs{goblin}` 会先自己推一格（那是
    ///   `AdvanceTurnsUntilActive` 的活），英雄照样掉到 57 —— 所以**必须**同时断言
    ///   步 2 之后行动者与回合号（步 3 的结果区分不出这两者）；
    /// * 让它推两步以上 ⇒ 步 2 会绕过 goblin 回到英雄，`round`/`turn` 直接不对。
    #[test]
    fn one_end_one_turn_step_puts_exactly_one_combatant_on_stage() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [
            PlanCombatant {
                id: "queue_imp",
                max_health: 22,
            },
            PlanCombatant {
                id: "stamp_goblin",
                max_health: 22,
            },
        ];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 2,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "one_turn_step",
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
            Step::EndOneTurn,
            Step::EnemyActs {
                enemy: "queue_imp",
                action: "queue_imp.desk_jab",
                target: Some("hero"),
            },
            Step::EndOneTurn,
            Step::EnemyActs {
                enemy: "stamp_goblin",
                action: "stamp_goblin.rubber_stamp_rush",
                target: Some("hero"),
            },
        ];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        // 步 0：英雄的回合真的走完了（一步 = 一个战斗员），英雄自己没掉血。
        assert_eq!(trace.kinds(0), &[] as &[Problem], "EndOneTurn 不该记问题");
        assert_eq!(trace.hp(0, "hero"), 70);
        assert_eq!(trace.hp(1, "hero"), 62, "desk_jab 是 8 点");

        // 步 2：**一步只放一个敌人上场** —— 这是整个变体存在的理由。
        assert_eq!(trace.kinds(2), &[] as &[Problem], "EndOneTurn 不该记问题");
        assert_eq!(
            trace.hp(2, "hero"),
            62,
            "goblin 还没有出手（错误实现会在这里再掉 5 点）"
        );
        assert_eq!(trace.hp(2, "queue_imp"), 22, "敌人自己不掉血");
        assert_eq!(trace.hp(2, "stamp_goblin"), 22, "另一个敌人的血不许动");
        assert_eq!(
            (trace.steps[2].round, trace.steps[2].turn, trace.steps[2].problems),
            // 上下文取在**执行前**（`ScenarioRunner.cs:203` 同形）：执行前还是 imp 的回合。
            (1, 2, 0)
        );

        // 步 3：第二个敌人这才出手 ⇒ 62 - 5 = 57。
        assert_eq!(trace.hp(3, "hero"), 57, "rubber_stamp_rush 是 5 点");
        assert_eq!(trace.kinds(3), &[] as &[Problem]);

        // 终局：还在第一轮、回合号是 goblin 那一格（1 英雄 → 2 imp → 3 goblin）。
        assert_eq!(trace.result, CombatResult::Ongoing);
        assert_eq!(state.current_round, 1, "一次都没绕回新一轮");
        assert_eq!(state.current_turn, 3, "英雄 1 → imp 2 → goblin 3");
        assert_eq!(state.active_combatant_id, Some(cid("stamp_goblin")));
        // "状态不变"的另一半：两个敌人都没被挂上任何状态。
        for who in ["queue_imp", "stamp_goblin"] {
            assert!(
                state.combatant(&cid(who)).expect("敌人在").statuses().is_empty(),
                "`{who}` 不该被挂状态"
            );
        }
    }

    /// **`Step::EndOneTurn` 第二守门点**：推进到"下一个战斗员的回合开场"时战斗就结束了 ⇒
    /// 停，绝不把终局之后的回合推下去。
    ///
    /// 场景：敌人 5 血 + `permit_a38` 给 5 层 `paperwork`（`damage_over_time`）⇒
    /// 它的回合一开始就被 DoT 打死，而它是唯一的敌人 ⇒ `Victory`。
    ///
    /// 判据与 `a_lethal_turn_start_stops_the_rest_of_that_steps_turn_advancement` 同一组数
    /// （`round`/`turn`/手牌/抽牌堆/弃牌堆），只是入口换成 `EndOneTurn`：一个"不看 Result
    /// 就继续推"的实现在这里会**绕过**终态、把回合推回英雄（`round=2`、手牌重抽 5 张）。
    #[test]
    fn end_one_turn_stops_the_loop_when_the_combat_ends() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 5,
        }];
        let deck = [DeckEntry {
            card: "permit_a38",
            count: 12,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "one_turn_stops",
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
            Step::EndOneTurn,
        ];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        assert_eq!(trace.kinds(1), &[] as &[Problem], "推到它、开回合、DoT 打死它 —— 无异常");
        assert_eq!(trace.hp(1, "queue_imp"), 0);
        assert_eq!(trace.result, CombatResult::Victory);
        // 停在"敌人死在自己的回合开场"那一格，没有继续结束它的回合。
        assert_eq!(state.current_round, 1, "没有绕回新一轮");
        assert_eq!(state.current_turn, 2, "停在敌人那一回合");
        assert_eq!(state.active_combatant_id, Some(cid("queue_imp")));
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            0,
            "英雄没有重新抽牌 ⇒ 这一轮没绕回来"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::DrawPile),
            7,
            "12 张抽 5 张 ⇒ 还剩 7；错误实现会再抽 5 张、只剩 2"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::DiscardPile),
            5,
            "出了 1 张 + 回合末弃了手里 4 张"
        );
    }

    /// **`HeroDowned` 之外的第二种"回合开场就结束战斗"**：英雄自己的回合一开始就被打死。
    ///
    /// v1 没有"起始状态"字段，所以只能手工挂一条 `paperwork`（70 层 ≥ 70 血）。
    /// 这条测试钉住两件事，都是"变异不红 ⇒ 覆盖洞"的那种：
    ///
    /// 1. `ensure_turn_started` **之后**必须立刻算胜负 —— 否则 `HeroEndsTurn` 里
    ///    `if (Result == Ongoing)`（`:141-143`）看到的仍是旧值，驱动层会替一个**已经倒下**的
    ///    英雄把他的回合结束掉、把回合推给敌人（`turn` 变 2、行动者变敌人）。
    /// 2. `HeroPlays` 在"战斗已在这一步里结束"时**不记** `CardNotPlayed`
    ///    （参考 `:124` 的 `{ WasPlayed: false }` 不匹配 null：请求根本没被解析）。
    #[test]
    fn a_lethal_turn_start_on_the_hero_stops_the_driver_before_anything_else() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 5,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "hero_dot",
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

        // ① 英雄的回合开场就被打死 ⇒ **不再**替他结束回合。
        let script = [Step::HeroEndsTurn];
        let mut state = CombatState::new(CombatId::new("dot_a").expect("短"), 0);
        let mut host = Host::new(&content);
        build_fight(&mut state, &content, &plan).expect("蓝图合法");
        give_hero_lethal_paperwork(&mut state, 70);
        let mut out = FightOutcome::new();
        run_fight(&mut state, &content, &plan, &script, &mut host, &mut out)
            .expect("步进不该坏");
        assert_eq!(out.problems_of(0), &[] as &[Problem], "结束回合本身没有异常");
        assert_eq!(health(&state, "hero"), 0);
        assert_eq!(
            out.result,
            CombatResult::Defeat,
            "英雄在自己的回合开场被打死 ⇒ 当场判负"
        );
        assert_eq!(state.current_turn, 1, "没有替倒下的英雄推回合");
        assert_eq!(state.active_combatant_id, Some(cid("hero")));
        assert_eq!(state.turn_phase, CombatTurnPhase::TurnInProgress);

        // ② 同一时刻"打一张牌"：请求没被解析 ⇒ **没有** `CardNotPlayed`。
        let script = [Step::HeroPlays {
            card: "paper_cut",
            target: Some("queue_imp"),
        }];
        let mut state = CombatState::new(CombatId::new("dot_b").expect("短"), 0);
        let mut host = Host::new(&content);
        build_fight(&mut state, &content, &plan).expect("蓝图合法");
        give_hero_lethal_paperwork(&mut state, 70);
        let mut out = FightOutcome::new();
        run_fight(&mut state, &content, &plan, &script, &mut host, &mut out)
            .expect("步进不该坏");
        assert_eq!(
            out.problems_of(0),
            &[] as &[Problem],
            "战斗在这一步里结束 ⇒ 参考连 `CardNotPlayed` 都不记（`outcome` 是 null 不是 false）"
        );
        assert_eq!(out.result, CombatResult::Defeat);
        assert_eq!(health(&state, "queue_imp"), 22, "牌没打出去");
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
    fn a_missing_enemy_and_an_unregistered_action_are_distinct_problems() {        let blob = core_image();
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

    /// 轮到英雄时 `EnemyActs`：`:241` 记一条 [`Problem::StillHeroTurn`]（"先调 HeroEndsTurn"），
    /// 然后 `:172` 再记一条 [`Problem::CannotReachEnemyTurn`]（"active 不是它"）。
    ///
    /// 两条必须**分得开**：一条是脚本顺序写错了，另一条是回合序没绕回它 —— 修法相反。
    #[test]
    fn the_still_heroes_turn_problem_is_distinct_from_cannot_reach_enemy_turn() {
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
            &[Problem::StillHeroTurn, Problem::CannotReachEnemyTurn],
            "`:241` 的'轮到你该先调 HeroEndsTurn' + `:172` 的'active 不是它'，两条分开记"
        );
        assert_eq!(health(&state, "hero"), 70);
        // 英雄的回合没有被偷偷结束（`:239-243` 的原话：call HeroEndsTurn first）。
        assert_eq!(state.active_combatant_id, Some(cid("hero")));
    }

    /// 英雄倒下的分支（`:45-51`）。**前置条件是手工造的**，因为 v1 没有友军：
    /// 真实路径上英雄一倒玩家队就没活人 ⇒ 一次引擎调用之后 [`settle_result`] 当场判
    /// `Defeat` ⇒ 下一步先撞 `:40` 的终态门（那条路径见下一条测试）。
    ///
    /// 所以这条测的是**分支本身**：`result` 仍是 `Ongoing`（因为本步没有回过引擎）而英雄
    /// 已倒下 ⇒ 这一步不执行、记一条 `HeroDowned`，状态冻结。
    /// 参考也一样：`:46-48` 的原注释说这条是给 "a summoned ally keeps the team alive" 用的
    /// —— 也就是说 `HeroDowned` 的可达上界由"有没有友军"决定，v1 没有友军。
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
        run_fight(&mut state, &content, &plan, &script, &mut host, &mut out)
            .expect("步进不该坏");
        // 两步都没有回过引擎（外壳在 `:45` 就早退了）⇒ 胜负没被重算 ⇒ 两步都记 HeroDowned。
        assert_eq!(out.problems_of(0), &[Problem::HeroDowned]);
        assert_eq!(out.problems_of(1), &[Problem::HeroDowned]);
        assert_eq!(
            state.result,
            CombatResult::Ongoing,
            "没有引擎调用 ⇒ 胜负不变（参考只在生命周期事件上算）"
        );
        let frozen = state_hash(&state);
        let mut out = FightOutcome::new();
        run_fight(
            &mut state,
            &content,
            &plan,
            &[Step::EnemyActs {
                enemy: "queue_imp",
                action: "queue_imp.desk_jab",
                target: Some("hero"),
            }],
            &mut host,
            &mut out,
        )
        .expect("步进不该坏");
        assert_eq!(out.problems_of(0), &[Problem::HeroDowned]);
        assert_eq!(state_hash(&state), frozen, "英雄倒下的步一律不执行");
    }

    /// 真实路径：敌人的动作把英雄打死 ⇒ **同一步内**就判 `Defeat`（`CombatStateEffects.cs:49-53`），
    /// 下一步先撞 `:40` 的终态门 ⇒ `CombatAlreadyEnded`。
    ///
    /// 这条也顺带钉住 [`settle_result`] 的**调用点**：如果它挪回"步边界"以外的地方
    /// （例如只在步末算），`Defeat` 的时机会变，而这里断言的正是"敌动之后立刻就是 Defeat"。
    #[test]
    fn an_enemy_action_that_downs_the_hero_ends_the_fight_in_the_same_step() {
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
            combat_id: "hero_dies",
            seed: 1,
            // 5 血对 8 点伤害：`queue_imp.desk_jab` 一下就打死。
            hero: PlanCombatant {
                id: "hero",
                max_health: 5,
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
            Step::HeroPlays {
                card: "paper_cut",
                target: Some("queue_imp"),
            },
        ];

        let mut state = CombatState::new(CombatId::new("scratch").expect("短"), 0);
        let mut host = Host::new(&content);
        let mut out = FightOutcome::new();
        play_out(&mut state, &content, &plan, &script, &mut host, &mut out).expect("步进不该坏");

        assert_eq!(health(&state, "hero"), 0);
        assert_eq!(
            lifecycle(&state, "hero"),
            CombatantLifecycleState::Downed
        );
        assert_eq!(out.problems_of(1), &[] as &[Problem], "这一动本身没问题");
        assert_eq!(
            out.result,
            CombatResult::Defeat,
            "敌动之后立刻判负 —— 不用等步末"
        );
        assert_eq!(
            out.problems_of(2),
            &[Problem::CombatAlreadyEnded],
            "英雄已经倒下 ⇒ 下一步先撞终态门（HeroDowned 走不到）"
        );
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

    /// `cards_drawn_per_turn` **现在真的生效**（成对，2026-10-18 裁决 1）。
    ///
    /// 抽 3 ⇒ 起手 3 张；抽 5（标准包）⇒ 起手 5 张。两条一起，才证明这个字段不是装饰品
    /// —— 只测一条的话，"抽 3 张"可能只是"牌组里只有 3 张"。
    #[test]
    fn cards_drawn_per_turn_is_the_blueprints_number_not_a_constant() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 22,
        }];
        // 12 张牌，两张蓝图都用它 ⇒ 差异只能来自抽牌数。
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 12,
        }];
        let res = resources();
        let refill = refills();
        let base = FightPlan {
            combat_id: "draw_count",
            seed: 1,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: 3,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let script = [Step::HeroEndsTurn];

        let mut state = CombatState::new(CombatId::new("three").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(
            &mut state,
            &content,
            &FightPlan {
                cards_drawn_per_turn: 3,
                ..base
            },
            &script,
            &mut host,
        );
        // 步 0 结束英雄的回合之前，回合已经在步内被开起来 ⇒ 手牌是 3 张，然后被弃掉。
        // 所以观测量取"弃牌堆 3 张 + 抽牌堆 9 张"（12 - 3）。
        assert_eq!(trace.kinds(0), &[] as &[Problem]);
        assert_eq!(zone_count(&state, "hero", CardZone::DiscardPile), 3);
        assert_eq!(zone_count(&state, "hero", CardZone::DrawPile), 9);

        let mut state = CombatState::new(CombatId::new("five").expect("短"), 0);
        let mut host = Host::new(&content);
        let trace = drive(
            &mut state,
            &content,
            &FightPlan {
                cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
                ..base
            },
            &script,
            &mut host,
        );
        assert_eq!(trace.kinds(0), &[] as &[Problem]);
        assert_eq!(
            zone_count(&state, "hero", CardZone::DiscardPile),
            5,
            "标准包 5 张（`StandardCombatPackage.cs:7`）"
        );
        assert_eq!(zone_count(&state, "hero", CardZone::DrawPile), 7);
    }

    /// 补能表**多于一条** ⇒ 拒绝：`TurnConfig` 只有一个能量资源
    /// （回合机只补一个池），第二条**表达不了** —— 静默丢掉等于让蓝图说谎。
    #[test]
    fn a_second_refill_resource_is_refused_because_the_turn_machine_has_one() {
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

        let two = [(energy(), 3), (energy(), 1)];
        let error = build_fight(
            &mut state,
            &content,
            &FightPlan {
                turn_start_refills: &two,
                ..base
            },
        )
        .expect_err("两条补能表达不了，必须拒");
        assert_eq!(error, unsupported());

        // 对照：一条（标准那一份）能建；空表也能建（=[`turn_config_for`] 的"保留标准包"）。
        build_fight(&mut state, &content, &base).expect("一条能建");
        build_fight(
            &mut state,
            &content,
            &FightPlan {
                turn_start_refills: &[],
                ..base
            },
        )
        .expect("空表能建（语义见 turn_config_for 的文档第 1 条）");
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

    /// §144：`Innate` 是**真的挪**了 —— 一张 innate 卡从抽牌堆的**最后**被拉到顶。
    ///
    /// 成对设计：`shuffle: false` 时牌的初始顺序就是牌组顺序（`swift_strike` 在最后），
    /// 所以"建完之后它在第 0 张"只可能是被挪过 —— 不挪的实现会让它留在第 4 张。
    /// 参考的顺序细节也一并钉住：挪是**倒着**做的（`ScenarioCombatFactory.cs:102-103`）。
    #[test]
    fn an_innate_card_is_pulled_to_the_top_of_the_draw_pile() {
        let blob = sts_image();
        let entries = [
            DeckEntry {
                card: "strike",
                count: 4,
            },
            DeckEntry {
                card: "swift_strike",
                count: 1,
            },
        ];
        let state = build_sts_fight(&blob, &entries, false).expect("a fight");
        let pile = draw_pile_definitions(&state, "hero");
        assert_eq!(pile.len(), 5, "5 张牌都进了抽牌堆");
        assert_eq!(
            pile[0], "swift_strike",
            "innate 卡必须在抽牌堆**顶**上（挪之前在最后一张）"
        );
        assert_eq!(
            pile[1..].iter().filter(|id| *id == "strike").count(),
            4,
            "其余顺序不动"
        );

        // 两张 innate：相对顺序必须保住（参考的"倒着挪"正是为了这个）。
        let two = [
            DeckEntry {
                card: "strike",
                count: 3,
            },
            DeckEntry {
                card: "swift_strike",
                count: 2,
            },
        ];
        let state = build_sts_fight(&blob, &two, false).expect("a fight");
        let pile = draw_pile_definitions(&state, "hero");
        assert_eq!(
            &pile[..2],
            &["swift_strike", "swift_strike"],
            "两张 innate 都在顶上"
        );
        assert_eq!(pile.len(), 5);
    }

    /// §147：`whirlwind+` **必须真的在镜像里** —— 运行层的"升级"只是往卡 id 后面加一个 `+`，
    /// 所以一张没有 `+` 行的牌升完级之后，下一场战斗会在建战斗那一步**响亮失败**
    /// （`BattleError::UnknownCard`）。这条测试就是那个失败模式的守门人。
    #[test]
    fn an_upgraded_card_row_is_buildable() {
        let blob = sts_image();
        let entries = [
            DeckEntry {
                card: "whirlwind",
                count: 1,
            },
            DeckEntry {
                card: "whirlwind+",
                count: 1,
            },
        ];
        let state = build_sts_fight(&blob, &entries, true).expect("both rows must be buildable");
        let mut defs = draw_pile_definitions(&state, "hero");
        defs.sort();
        assert_eq!(defs, vec!["whirlwind", "whirlwind+"]);

        // 成对：一个**不存在**的 `+` 行照样要响亮失败 —— 否则这条测试也可能是"建战斗从不查定义"。
        let broken = [DeckEntry {
            card: "no_such_card+",
            count: 1,
        }];
        assert!(
            build_sts_fight(&blob, &broken, true).is_err(),
            "an upgraded row that does not exist must fail loudly"
        );
    }

    /// §154：**每一张能升级的牌都必须建得起来**，成对：假 `+` 行照样响亮失败。
    ///
    /// 这条比 `an_upgraded_card_row_is_buildable` 宽：那条只钉了 `whirlwind`（§147 的教训就写在
    /// 它上面），而用户实际撞到的是 `iron_wave+` —— 运行层的升级就是往 id 后面加 `+`，所以
    /// **任何**一张没有 `+` 行的牌，都会在升完级之后的下一场战斗里 `UnknownCard`。
    ///
    /// 遍历的是**镜像里的所有 `+` 行**，所以内容新增一张牌时它会自动覆盖到。
    #[test]
    fn every_upgraded_card_row_builds_a_fight() {
        let blob = sts_image();
        let content = parse(&blob);
        // 遍历 `CARD` 段的行：行里那一格是**串槽**，`content.string(...)` 才是 id。
        let rows = content.section(crate::content::S_CARD).map_or(0, |s| s.count);
        let mut upgraded: Vec<&str> = Vec::new();
        for index in 0..rows {
            let Some(card) = content.card(index) else {
                continue;
            };
            let Some(id) = content.string(card.id()) else {
                continue;
            };
            if id.ends_with('+') {
                upgraded.push(id);
            }
        }
        assert!(
            upgraded.len() >= 14,
            "expected the upgraded rows to be there, got {upgraded:?}"
        );
        for id in upgraded {
            let entries = [DeckEntry { card: id, count: 1 }];
            let state = build_sts_fight(&blob, &entries, true)
                .unwrap_or_else(|e| panic!("{id} must be buildable: {e:?}"));
            let defs = draw_pile_definitions(&state, "hero");
            assert_eq!(defs, vec![id], "{id} did not land in the draw pile");
        }
        // 成对：不存在的 `+` 行仍然响亮失败（否则上面那些断言也可能是"建战斗从不查定义"）。
        assert!(
            build_sts_fight(
                &blob,
                &[DeckEntry {
                    card: "no_such_card+",
                    count: 1
                }],
                true
            )
            .is_err(),
            "an upgraded row that does not exist must fail loudly"
        );
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

    // ---------------------------------------------------------------- 倒下即判、判了就停
    //
    // 这一节是跨语言整局对拍（`native/fight_diff.py`）定位出的第三处偏差的闸门：
    // 参考实现在目标倒下那一行就把胜负判上（`CombatStateEffects.cs:36-58`），所以
    // `play::play_card` 执行期间 `state.result` **会**变成非 `Ongoing`，
    // 它的 Cancelled 分支"卡不搬"因此是**真实可达**的。内核原来是"每次引擎调用之后"才算，
    // 于是这一击总是被判成 Completed：卡被搬走，整局终局的 `hand`/`discard` 各差 1。

    /// 打死**最后一个敌人**的那一击：卡**留手牌**、不搬区、费用已付、战斗判胜。
    ///
    /// 数据依据（`native/fight_diff.py` 的 `finish` 场景，C# 侧是
    /// `CombinedStateHasher` 逐字节复现的规范文本）：C# 终局 `hand=5 discard=5`，
    /// 而修正前的内核是 `hand=4 discard=6` —— 差的正是这一张 `card_000006`。
    #[test]
    fn a_lethal_play_leaves_the_card_in_hand_and_the_combat_is_over() {
        let blob = core_image();
        let content = parse(&blob);
        // 敌人只有 5 血、`paper_cut` 打 6 ⇒ 第一张就打死（不必凑三张）。
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 5,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 3,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "lethal_play",
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
        let script = [Step::HeroPlays {
            card: "paper_cut",
            target: Some("queue_imp"),
        }];

        let mut state = CombatState::new(CombatId::new("lethal_play").expect("短"), 1);
        let mut host = Host::new(&content);
        let trace = drive(&mut state, &content, &plan, &script, &mut host);

        assert_eq!(trace.kinds(0), &[] as &[Problem], "打出去的牌不该记问题");
        assert_eq!(health(&state, "queue_imp"), 0, "这一击真的打死了");
        assert_eq!(lifecycle(&state, "queue_imp"), CombatantLifecycleState::Downed);
        assert_eq!(
            state.result,
            CombatResult::Victory,
            "倒下即判（`CombatStateEffects.cs:55-58`）：不再是 `Ongoing`"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            3,
            "Cancelled ⇒ 卡**留在手牌**（`Cards/CardPlay.cs:240-241`、`:262`）"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::DiscardPile),
            0,
            "一张都没落区（成对：手牌 3 里含那张被打出去的）"
        );
        let pool = state
            .combatant(&cid("hero"))
            .and_then(|c| c.resources().iter().find(|p| p.key == energy()).copied())
            .expect("英雄必须有能量池");
        assert_eq!(pool.pool.current, 2, "费用**已经付过**（付款早于跑节目）");
    }

    /// 同一件事的另一半：战斗结束之后，程序里**剩下的节点一个都不再派发**。
    ///
    /// `counter_signature` 实测：费用 0、节目 = `sequence(dealDamage 3 @eventTarget,
    /// drawCards 1 @source)` —— 第二个节点**与那个死掉的敌人无关**（抽牌打的是自己），
    /// 所以它是这条判据唯一能区分的形状。
    ///
    /// ⚠️ **别换成 `stamp_barrage` / `compliance_review`**（`dmg + applyStatus paperwork`）：
    /// 那两个看着更自然，但抓不到这个 bug —— `applyStatus` 的目标是 `sel.eventTarget`，
    /// 而目标选择器**本来就会把已倒下的单位滤掉**（`targets.rs`，
    /// `exec.rs` 的 `a_downed_target_is_filtered_out_by_the_selector` 钉着），
    /// 于是"节点跑了但选到空集"与"节点没跑"在状态上一样。我第一版就是那么写的，
    /// 变异测试里它**照样绿**（覆盖洞），改成抽牌才真的红。
    ///
    /// 参考：`SetResult` 取消在飞帧（`CombatState.cs:358-367`）＋排空循环
    /// `while (… && Result == Ongoing)`（`CombatEventHandling.cs:97`）。
    #[test]
    fn a_program_stops_dispatching_nodes_once_the_combat_is_over() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 3,
        }];
        // 6 张 ⇒ 起手 5、抽牌堆剩 1。第二个节点要是跑了就会把最后那张抽进手里。
        let deck = [DeckEntry {
            card: "counter_signature",
            count: 6,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "stop_midway",
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
        let script = [Step::HeroPlays {
            card: "counter_signature",
            target: Some("queue_imp"),
        }];

        let mut state = CombatState::new(CombatId::new("stop_midway").expect("短"), 1);
        let mut host = Host::new(&content);
        drive(&mut state, &content, &plan, &script, &mut host);

        assert_eq!(health(&state, "queue_imp"), 0, "第一个节点打死了它（3 血 - 3 伤）");
        assert_eq!(state.result, CombatResult::Victory);
        // 区分点是**抽牌堆**：起手 5 张之后还剩 1 张。第二个节点跑了就会把它抽走。
        assert_eq!(
            zone_count(&state, "hero", CardZone::DrawPile),
            1,
            "第二个节点（drawCards 1）**不许执行** —— 抽牌堆最后一张还在"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            5,
            "手牌 5：Cancelled ⇒ 那张牌没落区所以没少（成对见下面的对照）"
        );

        // 对照：同一条链在战斗还在进行时两个节点都跑（否则上面那个 1 可能只是
        // "这条动作本来就不抽牌"）。注意这里的 `hand` 也是 5 —— 因为那张牌打出去了 ⇒
        // **手牌数区分不出这两种局面，抽牌堆才区分得出**。写在这里免得下一个人以为
        // 加一条 `hand == 5` 就够了。
        let alive = [PlanCombatant {
            id: "queue_imp",
            max_health: 9,
        }];
        let mut ongoing = CombatState::new(CombatId::new("stop_midway2").expect("短"), 1);
        let mut host = Host::new(&content);
        let plan_alive = FightPlan {
            enemies: &alive,
            ..plan
        };
        drive(&mut ongoing, &content, &plan_alive, &script, &mut host);
        assert_eq!(health(&ongoing, "queue_imp"), 6);
        assert_eq!(ongoing.result, CombatResult::Ongoing);
        assert_eq!(zone_count(&ongoing, "hero", CardZone::DrawPile), 0, "抽牌真的发生了");
        assert_eq!(zone_count(&ongoing, "hero", CardZone::Hand), 5);
        assert_eq!(
            zone_count(&ongoing, "hero", CardZone::ExhaustPile),
            1,
            "这张牌正常落区（它实测的落区是 ExhaustPile 而不是 DiscardPile；Cancelled 那一半里它还在手里）"
        );
    }

    // =========================================================================================
    // 牌组从内容来（`build_fight_from_content`）
    // =========================================================================================
    //
    // 这一组全部接 **sts 包的真实镜像**（`tools/contentc/packages/sts/`），而不是上面那些
    // 测试用的 roguedeck 镜像：sts 那 10 张起始牌组（`inv:§2.1` strike×5 / defend×4 / bash×1）
    // 正是被 `native/sts_content_check.py` 的 InertKeys 闸门盯着的那三处副本。

    /// sts 包的 core 镜像。
    const STS_IMAGE_REL: &str = "../../tools/contentc/packages/sts/out/content.sts.core.rdcf";

    fn sts_image() -> Vec<u8> {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(STS_IMAGE_REL);
        std::fs::read(&path).unwrap_or_else(|e| {
            panic!(
                "sts 内容镜像缺失或读不到：{}\n  {e}\n  它是构建产物，生成命令：\n    \
                 python tools/contentc/build.py --package sts",
                path.display()
            )
        })
    }

    /// sts 的起始牌组按 `inv:§2.1` 展开成 10 个 id（**顺序就是内容里的顺序**）。
    fn sts_deck_ids() -> Vec<String> {
        let mut ids: Vec<String> = vec!["strike".to_string(); 5];
        ids.extend(vec!["defend".to_string(); 4]);
        ids.push("bash".to_string());
        ids
    }

    /// 按名字查那三个根键（与 `build_fight_from_content` 里的三行**故意分开写**）：
    /// 它在这里的身份是"这份内容确实有这三处候选"的**期望**，而不是实现的一部分。
    fn sts_roots(content: &Content<'_>) -> DeckRoots {
        DeckRoots {
            characters: content.root_by_name("Characters"),
            start: content.root_by_name("Start"),
            deck: content.root_by_name("Deck"),
        }
    }

    /// §152：链的引用计数在**回合边界**上必须回到 0。
    ///
    /// soak 在 3 × Sentry 的第 12 回合撞到 `StepThrew(Capacity:Chains)` —— 那时 arena 已经满了
    /// （`MAX_LIVE_CHAINS = 128`），而每一步都在**漏**。这里把它拆到最小：回合开始/结束各跑
    /// 一次，看是谁的引用没还。
    #[test]
    fn a_turn_boundary_leaves_no_chain_referenced() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let enemies = [PlanCombatant { id: "sentry_1", max_health: 39 }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "sts_one_sentry",
            seed: 11,
            hero: PlanCombatant { id: "hero", max_health: 200 },
            enemies: &enemies,
            deck: &[],
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: true,
            resources: &res,
            turn_start_refills: &refill,
        };
        let mut state = CombatState::new(CombatId::new("scratch").expect("短 id"), 0);
        build_fight_from_content(&mut state, &content, &plan).expect("builds");
        let config = turn_config_for(&plan).expect("config");
        let mut host = Host::new(&content);
        let hero = cid("hero");
        let mut report = Vec::new();
        for round in 0..3 {
            turn::start_current_turn(&mut state, &config, &mut host).expect("start");
            report.push((round, "start", state.live_chain_count()));
            turn::end_current_turn(&mut state, &config, &mut host).expect("end");
            report.push((round, "end", state.live_chain_count()));
        }
        let leaked: Vec<_> = report.iter().filter(|entry| entry.2 > 0).copied().collect();
        assert!(leaked.is_empty(), "leaked after: {leaked:?} (round, phase, live)");
    }

    /// §158: **Dexterity really adds Block for this content.**
    ///
    /// `standard.dexterity` is a new `STAT` row, and its whole behaviour is one spec in
    /// `PassiveModifiers`: `BlockGain / AddPerStack / 1 / Priority 100`. Get the pipeline string
    /// wrong and the spec never matches -- the status applies, the number does not move, and
    /// **nothing says so** (`status_bind.rs` calls that "the worst kind of silent"). So this plays
    /// the content's own `defend` with 2 Dexterity on the hero and asks for **7**, not 5.
    #[test]
    fn dexterity_from_the_content_scales_a_real_defend() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "sentry_1",
            max_health: 99,
        }];
        let res = resources();
        let refill = refills();
        // Eight Defends, so the opening hand of five is all Defend and the play is deterministic.
        let deck = [DeckEntry {
            card: "defend",
            count: 8,
        }];
        let plan = FightPlan {
            combat_id: "sts_dex",
            seed: 11,
            hero: PlanCombatant {
                id: "hero",
                max_health: 200,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: true,
            resources: &res,
            turn_start_refills: &refill,
        };
        let mut state = CombatState::new(CombatId::new("dex").expect("短 id"), 0);
        build_fight_from_content(&mut state, &content, &plan).expect("builds");
        let config = turn_config_for(&plan).expect("config");
        let mut host = Host::new(&content);
        turn::start_current_turn(&mut state, &config, &mut host).expect("start");
        let hero = cid("hero");
        // Exactly what Dexterity Potion applies (`combat_status:standard.dexterity`, amount 2).
        state
            .combatant_mut(&hero)
            .expect("hero")
            .push_status(
                StatusInstance::new(
                    StatusInstanceId::new("status_dex").expect("id"),
                    StatusDefinitionId::new("standard.dexterity").expect("definition"),
                    StatusPolarity::Buff,
                )
                .with_stacks(2),
            )
            .expect("push");
        let mut problems = Problems::new();
        hero_plays(
            &mut state,
            &content,
            &config,
            Play {
                card: "defend",
                instance: None,
                target: None,
            },
            &mut host,
            &hero,
            &mut problems,
        )
        .expect("defend is playable");
        let block = state
            .combatant(&hero)
            .expect("hero")
            .defensive_pools()
            .iter()
            .find(|pool| pool.key.as_str() == "standard.block")
            .map_or(-1, |pool| pool.pool.current);
        assert_eq!(block, 7, "defend's 5 Block plus 2 from Dexterity");
    }

    /// §152：一场**长**战斗里每一步都必须**没有问题**。
    ///
    /// 这条测试是 soak 逼出来的：那道闸门在第 12 回合的 3 × Sentry 上撞到 `StepThrew`，
    /// 而 `Problem::StepThrew` 是外壳把 `execute_step` 的 `Err(_)` **吞掉**之后的残渣 ——
    /// 页面看到的只有"这一步抛了"，没有哪一步、为什么。所以这里直接把每一步的 `problems`
    /// 数出来：只要有一层错误，测试就红，而不是留下一局"回合结束了但新回合没开始"的死局。
    ///
    /// 覆盖的是回合边界那一段（`EndOneTurn` × N）：§149 在伤害管线里加了三条状态的钩子，
    /// 它们都在敌人回合里跑。
    #[test]
    fn a_long_fight_never_reports_a_step_problem() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let enemies = [
            PlanCombatant { id: "sentry_1", max_health: 39 },
            PlanCombatant { id: "sentry_2", max_health: 39 },
            PlanCombatant { id: "sentry_3", max_health: 39 },
        ];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "sts_sentries",
            seed: 11,
            hero: PlanCombatant { id: "hero", max_health: 200 },
            enemies: &enemies,
            deck: &[],
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: true,
            resources: &res,
            turn_start_refills: &refill,
        };
        let mut state = CombatState::new(CombatId::new("scratch").expect("短 id"), 0);
        build_fight_from_content(&mut state, &content, &plan).expect("the sentry fight builds");
        // §149 的 Plated Armor 也在管线里：让英雄戴着它，敌人回合就一定会走到那条钩子。
        if let Some(hero) = state.combatant_mut(&cid("hero")) {
            hero.push_status(crate::state::StatusInstance::new(
                crate::state::StatusInstanceId::new("st_pa").expect("id"),
                crate::state::StatusDefinitionId::new("standard.plated_armor").expect("id"),
                crate::state::StatusPolarity::Buff,
            )
            .with_stacks(4))
            .expect("room");
        }

        let mut host = Host::new(&content);
        // 一步一步跑，每步之后看**链的引用计数**是否回到 0：这是本模块唯一的"GC"，
        // 不平衡的表现不是"多一条链"，而是 128 个节目之后 `Full(Chains)` 到处炸
        // （`exec.rs::a_program_hands_back_the_chain_references_it_took` 钉住的是节目内部那一层）。
        let mut leaked = Vec::new();
        for round in 0..24 {
            let steps = [Step::EndOneTurn];
            let mut out = FightOutcome::new();
            run_fight(&mut state, &content, &plan, &steps, &mut host, &mut out).expect("one turn");
            let live = state.live_chain_count();
            if live > 0 {
                leaked.push((round, live));
            }
        }
        assert!(
            leaked.is_empty(),
            "chains still referenced after a turn (round, live): {leaked:?}"
        );
        let steps = [Step::EndOneTurn; 24];
        let mut out = FightOutcome::new();
        run_fight(&mut state, &content, &plan, &steps, &mut host, &mut out).expect("24 turns");
        let mut offenders = Vec::new();
        for index in 0..steps.len() {
            let count = out.steps[index].problems;
            if count > 0 {
                offenders.push(index);
            }
        }
        assert!(
            offenders.is_empty(),
            "steps with problems (StepThrew = an error the shell swallowed): {offenders:?}"
        );
    }

    /// 抽牌堆里的卡定义 id（按堆序）。
    fn draw_pile_definitions(state: &CombatState, who: &str) -> Vec<String> {
        state
            .zone_cards(&cid(who), CardZone::DrawPile)
            .map(|card| card.definition_id.as_str().to_string())
            .collect()
    }

    /// 用 sts 的镜像建一局（英雄 80 血、敌人 `cultist` 48 血 = `inv:§4.1` 的 HpMin）。
    ///
    /// `deck` 传空 = "牌组从内容来"；传非空 = 显式牌组（那条路必须仍然有效且优先）。
    fn build_sts_fight(
        blob: &[u8],
        deck: &[DeckEntry<'_>],
        shuffle: bool,
    ) -> Result<CombatState, BattleError> {
        let content = parse(blob);
        let enemies = [PlanCombatant {
            id: "cultist",
            max_health: 48,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "sts_ironclad",
            seed: 3,
            hero: PlanCombatant {
                id: "hero",
                max_health: 80,
            },
            enemies: &enemies,
            deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: shuffle,
            resources: &res,
            turn_start_refills: &refill,
        };
        let mut state = CombatState::new(CombatId::new("scratch").expect("短 id"), 0);
        build_fight_from_content(&mut state, &content, &plan)?;
        Ok(state)
    }

    /// `term` 的第 `slot` 个槽在**镜像字节**里的绝对偏移。
    ///
    /// 之所以用"`slots_bytes()` 的指针 − `blob` 的指针"而不是手抄 `TRM`/`TRW` 的布局：
    /// 本项目已经因为"手抄第二份布局常量"腐烂过一次（`tools/rdcf_verify.py` 的 stride）。
    fn term_slot_offset(blob: &[u8], content: &Content<'_>, term_id: u16, slot: usize) -> usize {
        let term = content.term(term_id).expect("term 必须存在");
        let base = term.slots_bytes().as_ptr() as usize - blob.as_ptr() as usize;
        assert!(base < blob.len(), "term 的槽必须落在镜像里");
        base + slot * 2
    }

    fn patch16(blob: &mut [u8], at: usize, value: u16) {
        blob[at..at + 2].copy_from_slice(&value.to_le_bytes());
    }

    /// 从 `sts` 包读到的牌组**真的进了抽牌堆**，且顺序与内容声明的一致。
    #[test]
    fn the_sts_content_deck_reaches_the_draw_pile_in_the_declared_order() {
        let blob = sts_image();
        let state = build_sts_fight(&blob, &[], false).expect("内容里的牌组必须读得出来");

        assert_eq!(zone_count(&state, "hero", CardZone::DrawPile), 10);
        assert_eq!(
            draw_pile_definitions(&state, "hero"),
            sts_deck_ids(),
            "牌数与顺序都必须是内容里那 10 张（`inv:§2.1`）"
        );
        // 成对：不开洗牌 ⇒ 一次随机数都没抽，所以上面那条"顺序"断言测的是**读牌组**，
        // 不是洗牌恰好把序洗回了原样。
        assert_eq!(state.random_step, 0, "不洗牌 ⇒ random_step 不动");
        // 别的堆都空着：这条排除"10 张里有一部分是从别处漏进来的"。
        for zone in [CardZone::Hand, CardZone::DiscardPile, CardZone::ExhaustPile] {
            assert_eq!(zone_count(&state, "hero", zone), 0, "{zone:?} 应当是空的");
        }
    }

    /// 内容那三处候选里，**优先读的是角色自己那份**（`Characters[0].Start.Deck`）。
    #[test]
    fn the_content_deck_is_read_through_the_character_copy_first() {
        let blob = sts_image();
        let content = parse(&blob);
        let deck = content
            .start_deck(sts_roots(&content))
            .expect("三处候选都在，且都读得出来");

        assert_eq!(
            deck.origin(),
            DeckOrigin::CharacterStart,
            "花名册非空 ⇒ 参考 `RunBlueprint.cs:174` 取 `Characters[0].Start`"
        );
        assert_eq!(deck.len(), 10);
        let ids: Vec<String> = (0..deck.len())
            .map(|index| deck.get(index).expect("下标在 len 内").to_string())
            .collect();
        assert_eq!(ids, sts_deck_ids());
        // 成对：`get(len)` 越界必须响亮（不是"给个空串"）—— 否则上面的逐张断言可能
        // 在长度算错时仍然全绿。
        assert!(deck.get(deck.len()).is_err());
    }

    /// **调用方显式给的牌组优先**，不被内容覆盖。
    #[test]
    fn an_explicit_deck_wins_over_the_content_deck() {
        let blob = sts_image();
        let explicit = [DeckEntry {
            card: "strike",
            count: 1,
        }];
        let state = build_sts_fight(&blob, &explicit, false).expect("显式牌组必须仍然有效");
        assert_eq!(
            draw_pile_definitions(&state, "hero"),
            vec!["strike".to_string()],
            "显式牌组**不被内容覆盖**（内容那份是 10 张）"
        );
        // 成对：同一张蓝图、只是牌组留空 ⇒ 10 张。少了这一半，"1 张"可能来自别处。
        let from_content = build_sts_fight(&blob, &[], false).expect("内容牌组");
        assert_eq!(zone_count(&from_content, "hero", CardZone::DrawPile), 10);
    }

    /// 角色**声明了空的**牌组 ⇒ 回退到根 `Deck`（参考的 `blueprint.Deck` 分支）。
    ///
    /// 造法：`Start` 与 `Characters[0].Start` 在镜像里是**同一个 term**（实测 sts 140/140），
    /// 所以把它的 `Deck` 个数槽写成 0 会同时清空这两处 —— 正是"角色声明了没有"。
    /// 如果内核把根 `Deck` 误当成同一份 STRLIST 读，它会读到 0 张（`EmptyDeck`）而不是 10 张。
    #[test]
    fn the_fallback_walks_to_the_blueprint_deck_when_the_character_declares_none() {
        // 空列表有两种拼法，仓库里两种都出现过（`Start.StartingRelics` 是 `count = 0`，
        // 而 149 条敌人记录里 146 条的 `IntentRules` 是**哨兵**）—— 两种都必须读成
        // "声明了没有"并接着往下找，不能读成"内容坏了"。
        for empty in [0u16, LIST_NULL, LIST_ABSENT] {
            let mut blob = sts_image();
            let start_count = {
                let content = parse(&blob);
                let start = content.root_by_name("Start").expect("sts 有 Start");
                term_slot_offset(&blob, &content, start, 1) // `Deck` 的个数槽
            };
            patch16(&mut blob, start_count, empty);

            let content = parse(&blob);
            let deck = content
                .start_deck(sts_roots(&content))
                .expect("还有根 Deck");
            assert_eq!(
                deck.origin(),
                DeckOrigin::RootDeck,
                "两处 Start 都空（{empty:#06x}）⇒ 参考 `RunSetup.cs:44` 的 `: blueprint.Deck`"
            );
            let state = build_sts_fight(&blob, &[], false).expect("根 Deck 读得出来");
            assert_eq!(
                draw_pile_definitions(&state, "hero"),
                sts_deck_ids(),
                "根 `Deck` 是另一份 term：值必须与 Start.Deck 相同（{empty:#06x}）"
            );
        }
    }

    /// 花名册**为空** ⇒ 回退到根 `Start.Deck`（参考 `RunBlueprint.cs:169-170`）。
    #[test]
    fn the_fallback_walks_to_start_when_the_roster_is_empty() {
        let mut blob = sts_image();
        let roster_count = {
            let content = parse(&blob);
            let characters = content
                .root_by_name("Characters")
                .expect("sts 有 Characters");
            term_slot_offset(&blob, &content, characters, 1)
        };
        patch16(&mut blob, roster_count, 0);

        let content = parse(&blob);
        let deck = content
            .start_deck(sts_roots(&content))
            .expect("Start.Deck 还在");
        assert_eq!(
            deck.origin(),
            DeckOrigin::RootStart,
            "花名册空 ⇒ 第 2 跳（`RunBlueprint.cs:169-170`），**不是**直接跳到根 `Deck`"
        );
        let state = build_sts_fight(&blob, &[], false).expect("Start.Deck 读得出来");
        assert_eq!(draw_pile_definitions(&state, "hero"), sts_deck_ids());
    }

    /// 三处候选**全是空的** ⇒ 响亮失败（不是"一局 0 张牌的安静战斗"）。
    #[test]
    fn a_content_with_no_starting_deck_at_all_is_a_loud_failure() {
        let mut blob = sts_image();
        let offsets = {
            let content = parse(&blob);
            let characters = content.root_by_name("Characters").expect("Characters");
            let start = content.root_by_name("Start").expect("Start");
            let deck = content.root_by_name("Deck").expect("Deck");
            (
                term_slot_offset(&blob, &content, characters, 1),
                term_slot_offset(&blob, &content, start, 1),
                term_slot_offset(&blob, &content, deck, 1),
            )
        };
        patch16(&mut blob, offsets.0, 0);
        patch16(&mut blob, offsets.1, 0);
        patch16(&mut blob, offsets.2, 0);

        let content = parse(&blob);
        assert_eq!(
            content.start_deck(sts_roots(&content)).err(),
            Some(DeckError::EmptyDeck),
            "三处都在但都是空的 ⇒ `EmptyDeck`"
        );
        assert_eq!(
            build_sts_fight(&blob, &[], false).err(),
            Some(BattleError::Deck(DeckError::EmptyDeck))
        );
        // 成对：三处候选**一个都没有**（不是"都空"）是另一条错误 —— 它才是"这份内容
        // 根本没写牌组"，而 `EmptyDeck` 是"写了但没写牌"。两者都被 `BattleError::Deck` 带出去。
        let none = DeckRoots {
            characters: None,
            start: None,
            deck: None,
        };
        assert_eq!(content.start_deck(none).err(), Some(DeckError::NoDeckKey));
    }

    /// 内容点名的卡在 `CARD` 表里查不到 ⇒ [`BattleError::UnknownCard`]（与手写牌组同一条闸门）。
    ///
    /// **成对实验**：`sts` 那份内容里三处牌组点名的都是真卡，所以这条闸门在真内容上不可达
    /// ⇒ 只能把镜像里第一张牌的**串号**改成另一个真实存在的串（`ironclad`，它是
    /// `EK_CHARACTER` 不是 `EK_CARD`）。只改一个 `AUX` 格，其余字节与真镜像一致。
    #[test]
    fn a_content_deck_naming_a_card_with_no_row_is_a_loud_failure() {
        let mut blob = sts_image();
        let (aux_offset, first_card_cell, not_a_card) = {
            let content = parse(&blob);
            let start = content.root_by_name("Start").expect("sts 有 Start");
            let deck_start = content
                .term(start)
                .expect("Start 是对象")
                .slot(0)
                .expect("Deck 的起址槽");
            let aux = content.section(crate::content::S_AUX).expect("AUX 段");
            // 串号 = `Strings` 的位置 + 1（串号 0 是空串）。
            let string_id = content
                .strings()
                .position(|s| s == Some("ironclad"))
                .expect("串池里必须有 ironclad（它是 `Characters[0].Id`）")
                + 1;
            (aux.offset as usize, usize::from(deck_start) * 2, string_id)
        };
        assert!(
            content_lookup_is_not_a_card(&blob, "ironclad"),
            "成对前提：`ironclad` 真的不是一张卡（否则这条测试什么也没测）"
        );
        patch16(&mut blob, aux_offset + first_card_cell, not_a_card as u16);

        assert_eq!(
            build_sts_fight(&blob, &[], false).err(),
            Some(BattleError::UnknownCard(
                CardDefinitionId::new("ironclad").expect("短")
            )),
            "内容点名了一个没有 CARD 行的 id ⇒ 响亮失败（不是跳过这张牌）"
        );
    }

    /// `id` 在镜像里**不是**一张卡（成对前提用）。
    fn content_lookup_is_not_a_card(blob: &[u8], id: &str) -> bool {
        let content = parse(blob);
        content.lookup_in(id, EK_CARD).is_none() && content.lookup(id).is_some()
    }

    /// 从内容牌组建出来的一局**真的能打**：开回合抽 5、`strike` 打 6 点（`inv:§3.1`）。
    ///
    /// 前面那些测试只证明"牌进了抽牌堆"；这一条证明那份牌组是一局**能推进**的战斗的输入
    /// （回合机能起来、费用付得掉、节目跑得动、伤害落到敌人身上）。
    #[test]
    fn a_fight_built_from_the_content_deck_can_play_a_strike() {
        let blob = sts_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "cultist",
            max_health: 48,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "sts_ironclad",
            seed: 3,
            hero: PlanCombatant {
                id: "hero",
                max_health: 80,
            },
            enemies: &enemies,
            deck: &[],
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: false,
            resources: &res,
            turn_start_refills: &refill,
        };
        let mut state = CombatState::new(CombatId::new("scratch").expect("短 id"), 0);
        build_fight_from_content(&mut state, &content, &plan).expect("内容牌组");

        let mut host = Host::new(&content);
        let mut out = FightOutcome::new();
        let script = [Step::HeroPlays {
            card: "strike",
            target: Some("cultist"),
        }];
        run_fight(&mut state, &content, &plan, &script, &mut host, &mut out)
            .expect("step 本身不该坏");

        assert_eq!(out.problems_of(0), &[] as &[Problem], "这一步不该记问题");
        assert_eq!(health(&state, "cultist"), 42, "strike 6 点（`inv:§3.1`）");
        // 不洗牌 ⇒ 起手是内容里的前 5 张全 strike；打掉 1 张之后：手 4 / 抽牌堆 5 / 弃牌 1。
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 4);
        assert_eq!(zone_count(&state, "hero", CardZone::DrawPile), 5);
        assert_eq!(zone_count(&state, "hero", CardZone::DiscardPile), 1);
    }

    /// **反过来的成对**：老入口 [`build_fight`] 的"空牌组"就是 0 张 —— 它**不会**去内容里找。
    ///
    /// 这一条钉的是"没有静默降级"。把"空 = 去内容里找"这种方便的后门塞进 `build_fight`，
    /// 会让上面 549 条手写牌组的测试里"牌组为空"的那几条**含义变了却仍然全绿**（它们都
    /// 显式给牌，所以一条都不会变红）—— 所以"空就是空"必须有自己的钉子。
    #[test]
    fn build_fight_still_treats_an_empty_deck_as_empty() {
        let blob = sts_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "cultist",
            max_health: 48,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "sts_ironclad",
            seed: 3,
            hero: PlanCombatant {
                id: "hero",
                max_health: 80,
            },
            enemies: &enemies,
            deck: &[],
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: true,
            resources: &res,
            turn_start_refills: &refill,
        };
        let mut state = CombatState::new(CombatId::new("scratch").expect("短 id"), 0);
        build_fight(&mut state, &content, &plan).expect("空牌组是合法的蓝图");

        assert_eq!(state.card_count(), 0, "老入口不读内容里的牌组");
        assert_eq!(zone_count(&state, "hero", CardZone::DrawPile), 0);
        assert_eq!(state.random_step, 0, "0 张 ⇒ 连洗牌都不发生");
    }
}
