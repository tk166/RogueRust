//! 敌方决策层 —— 决定"这个敌人这一回合做什么"。
//!
//! **规格**：`docs/spec/enemy-intent.md`（1015 行，124 处 `文件:行号`）。行为以那份为准。
//!
//! # 为什么需要这个模块
//!
//! 内核能读内容镜像里的 `EACT`（394 条敌人动作）和 `ENCT`（109 条遭遇），但**没有一行代码
//! 挑过动作、也没有一行代码执行过它** —— 敌人站着不动。它不属于回合机、不属于效果执行器，
//! 它是**缺一个模块**，这也是为什么它一直没进任何计划清单。
//!
//! # 两个已经量出来的、会决定设计的事实
//!
//! 1. **驱动选择器的是 `ENCT`，不是 `EACT`。**
//!    选择规则（脚本 + 条件）挂在遭遇上，`EACT` 只是**动作库**。
//!    ⇒ `select_action` 的入参必须是 **`(遭遇, 敌人槽位)`**，不能只是 `CombatantId`。
//!    一个只看 `EACT` 的实现会"跑得通、但永远走循环分支"，而且**看起来一切正常** ——
//!    因为本内容 5 条 `IntentRule` 里 4 条依赖触发器系统、1 条依赖 `CardPlayTurnStats`，
//!    内核两样都没有 ⇒ 忠实实现在这份内容上**必然**永远走循环分支。
//!    **不要为了"看起来有动作"而特判**：那是把"内容依赖没到位"伪装成"功能已实现"。
//!
//! 2. **选择算法 100% 是引擎硬编码，而且零 RNG**（`EnemyIntentRules.cs:149-168`，全文 19 行）。
//!    已知的四个分支：敌人不在遭遇里 → `None`；有匹配规则 → 该规则的动作（Priority **降序**）；
//!    **有规则但全不匹配 → 落回循环，不是跳过**（这一条最容易被写错成"跳过这个敌人的回合"）；
//!    否则 `Actions[(round - 1) % count]`（1-based）。RNG 一次都不推进。
//!
//! # 一条会咬人的类型约束
//!
//! **39/394 个动作 id 超过 `ID_CAP = 40`**（最长 54 B：
//! `queue_crier_homunculus.call_a_number_that_is_not_yours`）。
//! ⇒ 这里**不许**复用 `state.rs` 的 `Ident<40>` 类型。要么借用内容镜像里的 `&'a str`
//! （零成本、无需存储），要么用一个容量 ≥ 56 的独立类型。选哪个取决于"选中的动作要不要
//! 存进状态"—— 按规格书，参考是**每次现算**的纯函数，不存状态，所以借用是最自然的。
//!
//! 本模块选了**借用**：[`ActionChoice::action_id`] 是 `&'a str`，指向镜像的串池。
//!
//! # 实测复核（执行方自己量的，不是转抄；`tools\contentc\reader.py`，只读）
//!
//! 规格书 §5.1/§5.2/§5.3 给的是**解码后 JSON** 的形状，而写代码要的是**二进制**形状。
//! 两者在三个地方不一样，照 JSON 写会读到不相干的数据：
//!
//! | 位置 | 规格书（JSON 视图） | 二进制真实形状（实测） |
//! |---|---|---|
//! | `ENCT.Enemies` 格 | `F_TERM` | 格是 `F_TERM`，但**指向的 term 是 `_arr`（op 4）**，其唯一字段是 `F_TERMLIST` ⇒ 槽 = `(AUX 起址, 个数)`，元素是 **term id** |
//! | enemy record 的 `Actions` | "term 列表，每个元素是 `_wrap_lower`" | **`F_STRLIST` + `FLAG_WRAP_LOWER`**（op 91 的字段表实测）⇒ AUX 里装的是**串号**，`_wrap_lower` term 一个都没有 |
//! | enemy record 的 `IntentRules` | term 列表 | `F_TERMLIST` ⇒ AUX 里装的是 **term id**（这一条与 JSON 视图一致） |
//!
//! 其余实测（全部 109 条 `ENCT` / 149 条 enemy record / 394 条 `EACT`）：
//!
//! * enemy record 是 op **91** 的普通对象，6 个键恒存在：`Actions`(F_STRLIST)、`Id`(F_STR)、
//!   `IntentRules`(F_TERMLIST)、`MaxHealth`(F_INT)、`Position`(F_TERM，149/149 是 `NULL16`)、
//!   `StartingStatuses`(F_TERMLIST)。`DisplayName` 不存在（与 §5.2 一致）。
//! * 规则记录是 op **90** 的普通对象，3 个键：`Action`(**F_STR + `FLAG_WRAP_LOWER`**)、
//!   `Condition`(F_TERM)、`Priority`(F_INT)。
//! * 条件节点是真 IR 节点（`opclass == 0`），判别串在 `OPD[op].name` 上。
//!   **core 镜像里只有两种**：op 46 `intent.opponentCardsPlayed`（`LastTurn` F_BOOL / `Op` F_STR /
//!   `Value` F_INT）、op 47 `intent.selfHasCounter`（`Counter` **F_STR + `FLAG_WRAP_LOWER`** /
//!   `Op` F_STR / `Value` F_INT）。**另外 8 种判别串在镜像里连 opcode 都没有**（§3.6 的说法成立）。
//! * `EACT.Program` 格指向 op 116 `_obj(Id,MaxNodeDepth,MaxProgramSteps,Root)`，槽
//!   `[1, 64, 1024, <root>]`（394/394 的 `MaxProgramSteps` 都是 1024）。
//! * `EACT.Intent` 指向 op 118 `_obj(Kind)`，`Kind` 只有 5 个值：Attack 110 / Defend 44 /
//!   Buff 21 / Debuff 51 / Special 168（与 §4.4 逐项一致）。
//! * 结构性分布复核：每遭遇敌人数 `{1:76, 2:26, 3:7}`、每敌人动作数 `{1:1,2:9,3:107,4:20,5:12}`、
//!   每敌人规则数 `{0:146, 1:2, 3:1}`；**同一遭遇内没有重复的 enemy `Id`**（所以参考的
//!   `ToDictionary(e => e.CombatantId)` 在这份内容上不会抛）；389 + 5 = 394 个动作 id **全部**
//!   能在 `IDX` 里解析成 `EK_EACTION` 且行内 `Id` 逐字节相符（0 条悬空）。
//!
//! # 接口：为什么入参是 `(遭遇, 槽位)` 而不是 `CombatantId`
//!
//! 参考的选择器是 `Func<CombatState, CombatantId, int, EnemyActionDefinitionId?>`，看起来
//! 只要 combatant —— 但它闭包里抓了 `compiled.Enemies`（`EnemyIntentRules.cs:153`），
//! 也就是**那一个遭遇的敌人名单**。C# 用闭包把"遭遇"藏起来了；Rust 没有闭包捕获，
//! 所以那个参数必须显式出现在签名里。
//!
//! 于是本模块的入参是 [`EnemySlot`]（`encounter` = ENCT 行号，`index` = `Enemies` 列表下标）
//! **加** `actor: &CombatantId`。两个都要，因为它们回答两个不同的问题：
//!
//! * `EnemySlot` 定位"哪个敌人的哪条脚本"。**同一份 `ENCT` 行的 `Enemies` 列表顺序就是上场序、
//!   也就是回合序**（`Encounters.cs:211-220` 按 `foreach (var spec in encounter.Enemies)` 追加，
//!   `ScenarioCombatFactory.cs:19-24` 再按 `[Hero, Allies…, Enemies…]` 建回合序）。
//! * `actor` 只用来做参考 `:156` 的那次**查表命中判定**：`byId.TryGetValue(enemyId)` 不命中
//!   ⇒ `null`（[`select_action`] 的 B0 分支）。用 `actor.as_str()` 与 record 的 `Id` 逐字节比。
//!
//! `locate_enemy` 是给宿主用的反向查找（有 combatant 要找槽位）；它返回 `None` 与 B0 是同一件事。
//!
//! **没有 `EnemyScript` 借用视图**（规格书 §8.1 建议过一个 `actions: &'a [u16]` +
//! `rules: &'a [RuleRef]` 的结构体）：那两个切片需要一个能活过调用的数组，而本 crate
//! **零分配**，造不出来。所以脚本是**每次现读**的（几个 `u16` 读，代价可忽略），
//! 这同时消掉了整整一类"视图与镜像不同步"的 bug。
//!
//! # 已知偏离（逐条都在下面代码里有锚点）
//!
//! | # | 偏离 | 为什么 |
//! |---|---|---|
//! | D1 | `round < 1` **响亮拒绝**（[`IntentError::InvalidRound`]） | 参考没有这个检查（`EnemyIntentRules.cs:165` 直接下标），C# 里 `(0-1) % 3 == -1` 会让 `List[-1]` 抛，Rust 里 `-1 % 3 == -1` 同样负 ⇒ 两边都是崩溃面。规格书 §8.3 第 4 条要求内核**响亮拒绝**并记录为有意偏差。**只在真的要用 `round` 时拒绝**：规则命中时参考根本不碰 `round`，那就不该因为我们更严格而失败。 |
//! | D2 | 没有 `EnemyScript` 借用视图 | 零分配下造不出 `&'a [T]`，见上一节。 |
//! | D3 | 10 种条件里只有 `intent.selfHasCounter` 能求值，其余 9 种一律 [`IntentError::UnsupportedCondition`] | 两类原因：`intent.opponentCardsPlayed` 要 `CardPlayTurnStats`，内核**故意没有**这张表（`play.rs:50-60` 记录的 D7）；另外 8 种在 core 镜像里**连 opcode 都不存在**（实测只有 op 46/47）⇒ 它们的**字段名无法测量**，照着 C# 构造参数猜一个名字就是"发明一个假的求值器"。宁可响亮拒绝，等真内容用到时再量一次（每次一个 `reader.py` 探针的功夫）。 |
//! | D4 | `execute_action` 把"请求面"折了进来：actor 已倒下 ⇒ `Ok(ExecStats::default())` | 参考 `EnemyActionEffects.cs:20-21` 对这个情况是**静默 return**（不是抛）。规格书 §8.1 建议的 `try_execute_action` 在本层没有第二个可用分支（"动作未注册"在内核里不存在 —— 没有注册表；"先宣布"分支要事件队列），为一个空壳冻一个新函数不值得。**`nodes == 0` 就是"什么都没做"的可观察信号。** |
//! | D5 | 同 `Priority` 的 tie 按**作者列表顺序**（稳定排序） | 参考的 `OrderByDescending` 是 LINQ-to-Objects，**文档说它是稳定排序**，规格书 §3.2 标为 ✘ 未实测。本内容唯一的同优先级对（`contradictory_signpost` 的两条 P20）条件互斥 ⇒ 不可观察。我实现稳定读法（`equal_priority_keeps_author_order` 钉住），并在此**明确标注这是复刻文档行为而不是实测行为**。 |
//! | D6 | 选择过程**不写任何状态**（`&CombatState`） | 参考的 `OpponentCardsPlayedCondition` 会调 `state.GetCardPlayTurnStats(id)`，而它是**读即创建**（`CombatState.cs:270-274`，见 `play.rs:58-60`）⇒ 参考在一次"纯投影"里插一个空条目。那东西不进哈希，本内核也没有这张表，所以**这条偏差今天不可观察**；但它确实是"参考的选择器不是纯函数"的一个证据。 |
//!
//! # 本内容上的真实行为（149 个敌人）
//!
//! * **146 个**敌人 `IntentRules` 为空 ⇒ 纯循环，每回合拿 `Actions[(round-1) % count]`。
//! * `a_very_official_line` / `minute_moth`：规则条件 `intent.selfHasCounter` **能求值**，
//!   但计数器 `queue_position` / `stolen_minute` 只由**触发器程序**递增
//!   （`STAT[7].Triggers`、`ENCT.TriggeredEffects`，§3.7），内核没有触发器 ⇒ 计数恒为 0
//!   ⇒ 规则恒假 ⇒ **落回循环分支**。这不是"实现错了"，是依赖没到位。
//! * `contradictory_signpost`：两条 P20 的 `selfHasCounter` 恒假之后，第三条 P10 是
//!   `intent.opponentCardsPlayed` ⇒ **`Err(UnsupportedCondition(OpponentCardsPlayed))`**。
//!   所以这个敌人**今天一次动作都选不出来**，而且是响亮的、指名道姓的失败 —— 不是 `None`
//!   （那会被宿主当成"这回合它不做任何事"），也不是"落回循环"（那是假装条件能求值）。
//!
//! ⇒ 规格书 §8.4 那句"在这份内容上它能做的正好是 146/149 个敌人的循环"需要修正：
//! **148/149**（那 2 个 `selfHasCounter` 敌人也走循环 —— 它们的条件能求值、只是恒假），
//! **1 个响亮失败**。这个数字由 `every_cycle_action_in_the_image_resolves_to_its_own_row`
//! 钉着（149 个敌人 × round 1..=5 ⇒ 740 个 `Ok(Some)` + 5 个 `Err`）。

use crate::content::{
    Content, Row, Table, ABSENT16, EK_EACTION, F_TERM, LIST_ABSENT, LIST_NULL, NULL16, OP_ARR,
};
use crate::exec::{self, ExecContext, ExecError, ExecStats};
use crate::ir::{IrError, NodeRef};
use crate::state::{CombatState, CombatantId};
use crate::turn::is_alive;

// ===========================================================================
// 容量常量（全部按"实测值 × 余量"取，超出**响亮失败**而不是截断）
// ===========================================================================

/// 一条遭遇最多几个敌人。**实测 `{1:76, 2:26, 3:7}`**，最大 3 ⇒ 8 是 2.6 倍余量。
///
/// 超出 ⇒ [`IrError::List`]（`term_list_field` 的合约：不截断 —— 少看一个敌人比报错糟得多）。
pub const MAX_ENEMIES: usize = 8;

/// 一个敌人最多几条 `Actions`。**实测 `{1:1, 2:9, 3:107, 4:20, 5:12}`**，最大 5 ⇒ 8。
pub const MAX_ACTIONS: usize = 8;

/// 一个敌人最多几条 `IntentRules`。**实测 `{0:146, 1:2, 3:1}`**，最大 3 ⇒ 8。
pub const MAX_INTENT_RULES: usize = 8;

/// 节目信封的步数上限兜底值 —— 参考的构造函数默认 1024
/// （`EffectProgramContracts.cs:560-563`，`play.rs:1496` 同一条），镜像实测 394/394 都是 1024。
const DEFAULT_MAX_PROGRAM_STEPS: u32 = 1024;

// ===========================================================================
// 词表
// ===========================================================================

/// 动作的**表现类别**（`EACT.Intent.Kind`）。
///
/// 枚举成员与参考的 `IntentKind` 逐项相同（`ActionIntent.cs:5-13`，规格书 §4.4）。
/// 本内容没有用到 `Unknown`。**`Label` 在 core 镜像里不存在**（§2.6）⇒ 内核只能显示这个类别。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IntentKind {
    /// 作者显式写的 `Unknown`（参考里存在这个成员）。
    Unknown,
    /// ⚔
    Attack,
    /// 🛡
    Defend,
    /// ▲
    Buff,
    /// ▼
    Debuff,
    /// ✦
    Special,
}

impl IntentKind {
    /// 全部成员（顺序 = 参考枚举顺序）。
    pub const ALL: [IntentKind; 6] = [
        IntentKind::Unknown,
        IntentKind::Attack,
        IntentKind::Defend,
        IntentKind::Buff,
        IntentKind::Debuff,
        IntentKind::Special,
    ];

    /// `System.Text.Json` 写出来的字符串（= C# 枚举成员名）。
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            IntentKind::Unknown => "Unknown",
            IntentKind::Attack => "Attack",
            IntentKind::Defend => "Defend",
            IntentKind::Buff => "Buff",
            IntentKind::Debuff => "Debuff",
            IntentKind::Special => "Special",
        }
    }

    /// 从判别串解析；不认识 ⇒ `None`（调用方转成 [`IntentError::UnknownIntentKind`]）。
    #[must_use]
    pub fn from_wire_name(name: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|kind| kind.wire_name() == name)
    }
}

/// 一条 `intent.*Of` / `intent.not` 最多几个子条件。实测镜像里 0 条组合条件 ⇒ 取 8 余量。
pub const MAX_CONDITION_CHILDREN: usize = 8;

/// 这个战斗员是否戴着条件里点名的状态（层数 >= `MinStacks`，缺省 1）。
fn carries_status(combatant: &crate::state::Combatant, condition: NodeRef<'_>) -> bool {
    let Ok(Some(status_id)) = condition.str_field("Status") else {
        return false;
    };
    let min_stacks = condition.int_field("MinStacks").ok().flatten().unwrap_or(1);
    combatant.statuses().iter().any(|status| {
        status.definition_id.as_str() == status_id && status.stacks >= min_stacks
    })
}

/// 比较算子（参考的 `ComparisonOperator`，`EnemyIntentRules.cs:26-35`）。
///
/// 字符串拼法来自 `System.Text.Json` 的枚举序列化，**六个名字逐字相同**。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CompareOp {
    /// `Equal`
    Equal,
    /// `NotEqual`
    NotEqual,
    /// `Less`
    Less,
    /// `LessOrEqual`
    LessOrEqual,
    /// `Greater`
    Greater,
    /// `GreaterOrEqual`
    GreaterOrEqual,
}

impl CompareOp {
    /// 全部成员（顺序 = 参考枚举顺序）。
    pub const ALL: [CompareOp; 6] = [
        CompareOp::Equal,
        CompareOp::NotEqual,
        CompareOp::Less,
        CompareOp::LessOrEqual,
        CompareOp::Greater,
        CompareOp::GreaterOrEqual,
    ];

    /// JSON 里的拼法（`EnemyIntentRules.cs:28-33` 的 `switch` 逐臂对照）。
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            CompareOp::Equal => "Equal",
            CompareOp::NotEqual => "NotEqual",
            CompareOp::Less => "Less",
            CompareOp::LessOrEqual => "LessOrEqual",
            CompareOp::Greater => "Greater",
            CompareOp::GreaterOrEqual => "GreaterOrEqual",
        }
    }

    /// 从拼法解析；不认识 ⇒ `None`（参考在这里**抛异常**，`:34`）。
    #[must_use]
    pub fn from_wire_name(name: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|op| op.wire_name() == name)
    }

    /// 参考 `Compare(int left, int right, op)` 的逐臂搬运（`EnemyIntentRules.cs:26-35`）。
    #[must_use]
    pub const fn apply(self, left: i32, right: i32) -> bool {
        match self {
            CompareOp::Equal => left == right,
            CompareOp::NotEqual => left != right,
            CompareOp::Less => left < right,
            CompareOp::LessOrEqual => left <= right,
            CompareOp::Greater => left > right,
            CompareOp::GreaterOrEqual => left >= right,
        }
    }
}

/// `IntentRule.Condition` 的 10 种原语（判别串 = `OPD[op].name`）。
///
/// 名字**逐字**来自 `Run\Serialization\RunJson.cs:141-151` 的注册表（规格书 §3.5 把 10 条都
/// 读到了），不是猜的。但**只有两种在 core 镜像里真的有 opcode**（实测 op 46/47）——
/// 其余 8 种的字段名无从测量，所以 [`ConditionKind::is_supported`] 只对**实现过的**为真
/// （今天两个：`selfHasCounter` 与 `healthPercent`），另外 8 种一律
/// [`IntentError::UnsupportedCondition`]。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConditionKind {
    /// `intent.healthPercent`（C# 参数 `Op, Percent`）
    HealthPercent,
    /// `intent.round`（`Op, Round`）
    Round,
    /// `intent.selfHasStatus`（`Status, MinStacks = 1`）
    SelfHasStatus,
    /// `intent.opponentHasStatus`（`Status, MinStacks = 1`）
    OpponentHasStatus,
    /// `intent.selfHasCounter`（`Counter, Op, Value`）—— **本模块唯一实现的一种**
    SelfHasCounter,
    /// `intent.selfResource`（`Resource, Op, Value`）
    SelfResource,
    /// `intent.opponentCardsPlayed`（`Op, Value, LastTurn = true`）
    OpponentCardsPlayed,
    /// `intent.allOf`（子条件列表；空 ⇒ true）
    AllOf,
    /// `intent.anyOf`（子条件列表；空 ⇒ false）
    AnyOf,
    /// `intent.not`（一个内层条件）
    Not,
    /// `intent.ascensionAtLeast`（`Value`）：本场战斗的 Ascension 等级 ≥ `Value`。
    ///
    /// 本移植自己的条件（§187）：StS 的 A17/A18/A19 是**换招式表**，而它的数据不是一个
    /// 可声明的表，是每只怪 `getMove` 里的一段 `if`。内核不给每只怪写代码，所以把那个
    /// `if` 交给内容：`AscensionMin` 管"同一个招式换数值"，这个条件管"哪条规则先生效"。
    AscensionAtLeast,
}

impl ConditionKind {
    /// 全部成员（顺序 = 规格书 §3.5 那张表的顺序）。
    pub const ALL: [ConditionKind; 11] = [
        ConditionKind::HealthPercent,
        ConditionKind::Round,
        ConditionKind::SelfHasStatus,
        ConditionKind::OpponentHasStatus,
        ConditionKind::SelfHasCounter,
        ConditionKind::SelfResource,
        ConditionKind::OpponentCardsPlayed,
        ConditionKind::AllOf,
        ConditionKind::AnyOf,
        ConditionKind::Not,
        ConditionKind::AscensionAtLeast,
    ];

    /// 判别串（= `OPD[op].name`，也 = `RunJson.cs:141-151` 注册的那个键）。
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            ConditionKind::HealthPercent => "intent.healthPercent",
            ConditionKind::Round => "intent.round",
            ConditionKind::SelfHasStatus => "intent.selfHasStatus",
            ConditionKind::OpponentHasStatus => "intent.opponentHasStatus",
            ConditionKind::SelfHasCounter => "intent.selfHasCounter",
            ConditionKind::SelfResource => "intent.selfResource",
            ConditionKind::OpponentCardsPlayed => "intent.opponentCardsPlayed",
            ConditionKind::AllOf => "intent.allOf",
            ConditionKind::AnyOf => "intent.anyOf",
            ConditionKind::Not => "intent.not",
            ConditionKind::AscensionAtLeast => "intent.ascensionAtLeast",
        }
    }

    /// 从判别串解析；不在这 10 种里 ⇒ `None`。
    #[must_use]
    pub fn from_wire_name(name: &str) -> Option<Self> {
        Self::ALL
            .into_iter()
            .find(|kind| kind.wire_name() == name)
    }

    /// 本模块今天**能不能求值**它。
    ///
    /// 只有 [`ConditionKind::SelfHasCounter`] 为真，理由见模块头的偏离 D3：
    /// `opponentCardsPlayed` 要一张内核故意没有的表，另外 8 种在镜像里连 opcode 都不存在
    /// ⇒ 字段名不可测量 ⇒ 实现它等于发明一个求值器。
    #[must_use]
    fn is_supported(self) -> bool {
        // **All ten** are implemented now (`port-plan.md` §128).
        true
    }
}

// ===========================================================================
// 错误
// ===========================================================================

/// 决策层的错误。
///
/// **两种"没有"必须分开**：[`select_action`] 的 `Ok(None)` 是**合法的 no-op**
/// （参考返回 `null`，宿主照常结束这个敌人的回合，规格书 §7.1：turn-start/turn-end 的自动化
/// 仍全部发生）；`Err(..)` 是**内容坏了 / 内核还没做到**，调用方不该把它当成"这回合不做"。
///
/// 判别串一律**不带载荷**（与 `ir.rs:74` 的 [`IrError::UnknownKind`] 同一条约定）：
/// 要看原字符串，调用 `NodeRef::kind_str()` / `str_field()` 自己取。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IntentError {
    /// 内容镜像读不出来（IR 层的结构错）。
    Ir(IrError),
    /// 结构上必须有的格/字段/行缺席。
    Missing(&'static str),
    /// [`EnemySlot::index`] 越出这条遭遇的敌人名单。
    Slot { encounter: u32, index: u16 },
    /// `round < 1`（有意偏离 D1；参考在这里是负数下标崩溃）。
    InvalidRound(i32),
    /// 内核还没有求值这种条件的能力（偏离 D3）。
    UnsupportedCondition(ConditionKind),
    /// 条件判别串不在这 10 种里（`NodeRef::kind_str()` 给出原文）。
    UnknownConditionKind,
    /// `Intent.Kind` 的串不认识（参考的 `JsonStringEnumConverter` 同样会抛）。
    UnknownIntentKind,
    /// `Op` 的串不认识（参考 `EnemyIntentRules.cs:34` **抛异常**）。
    UnknownOperator,
    /// 动作 id 在 `IDX` 里解析不出 `EACT` 行，或解析出的行 `Id` 不符。
    UnknownAction,
    /// 执行期错误（只有 [`execute_action`] 会产出）。
    Exec(ExecError),
}

impl From<IrError> for IntentError {
    fn from(error: IrError) -> Self {
        IntentError::Ir(error)
    }
}

impl From<ExecError> for IntentError {
    fn from(error: ExecError) -> Self {
        IntentError::Exec(error)
    }
}

// ===========================================================================
// 定位：(遭遇, 敌人槽位)
// ===========================================================================

/// 一个敌人在内容里的坐标：`ENCT[encounter].Enemies[index]`。
///
/// 这就是规格书 §8.1 第 1 条硬约束要的那个入参 —— 规则挂在**遭遇**上，`EACT` 只是动作库，
/// 所以"只看 `CombatantId`"的签名在信息上是不够的（见模块头"为什么入参是 (遭遇, 槽位)"）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EnemySlot {
    /// `ENCT` 表内行号（0 起，本内容 0..=108）。
    pub encounter: u32,
    /// `Enemies` 列表下标（0 起）。**列表顺序 = 上场序 = 回合序**（`Encounters.cs:211-220`）。
    pub index: u16,
}

/// 在一条遭遇里按 combatant id 找敌人的槽位（宿主用：手上只有 combatant，要找脚本）。
///
/// 匹配是**逐字节相等**（参考 `EnemyIntentRules.cs:153` 的 `ToDictionary(e => e.CombatantId)`
/// 同样是按 id 建表）。返回 `Ok(None)` 与 [`select_action`] 的 B0 分支是**同一件事**：
/// 这个 combatant 不是这条遭遇的敌人（它是英雄 / 它属于别的遭遇 / 它是运行时召唤出来的，
/// 规格书 §7.9）。
pub fn locate_enemy(
    content: &Content<'_>,
    encounter: u32,
    combatant: &CombatantId,
) -> Result<Option<EnemySlot>, IntentError> {
    let mut ids = [0u16; MAX_ENEMIES];
    let count = encounter_enemy_ids(content, encounter, &mut ids)?;
    // A spawned combatant is named `<definition>#<n>` (`node.createCombatant`, port-plan.md §121), so
    // an exact id match would miss it and it would show "unknown intent" forever. Fall back to the
    // **definition part** -- the slime that split off is still that slime.
    let raw = combatant.as_str();
    let definition = raw.split('#').next().unwrap_or(raw);
    let mut by_definition: Option<u16> = None;
    for (index, id) in ids.iter().enumerate().take(count) {
        // 借用视图的"根"取 `&'a Content<'a>`；这里只需要读一个 `F_STR`，用短生命周期即可。
        let record = NodeRef::new(content, *id);
        let Some(record_id) = record.str_field("Id")? else {
            continue;
        };
        if record_id == raw {
            return Ok(Some(EnemySlot {
                encounter,
                index: index as u16,
            }));
        }
        if by_definition.is_none() && record_id == definition {
            by_definition = Some(index as u16);
        }
    }
    if let Some(index) = by_definition {
        return Ok(Some(EnemySlot { encounter, index }));
    }

    // The reference's B0 lookup is "by the *current* encounter's id map" -- an actor that is simply
    // a stranger must stay None. Only a **spawned** id (it carries the #<n> suffix) is allowed to
    // resolve outside this encounter, because that is the summoning case.
    if !raw.contains('#') {
        return Ok(None);
    }

    // **A summoned minion is not in this encounter's roster** (`port-plan.md` §138): an elite that
    // calls for help brings a monster the encounter never listed. The definition still names a real
    // monster in the *image*, so fall back to "the first encounter that does list it" -- the intent
    // rules are keyed on the definition, not on which fight it showed up in.
    for row in content.rows(Table::Encounter) {
        let mut ids = [0u16; MAX_ENEMIES];
        let Ok(count) = encounter_enemy_ids(content, row.index(), &mut ids) else {
            continue;
        };
        for (index, id) in ids.iter().enumerate().take(count) {
            let record = NodeRef::new(content, *id);
            let Some(record_id) = record.str_field("Id")? else {
                continue;
            };
            if record_id == definition {
                return Ok(Some(EnemySlot {
                    encounter: row.index(),
                    index: index as u16,
                }));
            }
        }
    }
    Ok(None)
}

// ===========================================================================
// 选择
// ===========================================================================

/// 为什么选中了这个动作（测试与 UI 都要能问"是规则赢的还是循环轮到的"）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChoiceReason {
    /// 循环分支：`Actions[(round - 1) % len]`，`slot` 是取到的下标。
    ///
    /// `round` 是**传进来的那个 1-based 轮次**（不是 `state.current_round`）—— 参考的两个入口
    /// 都显式传 `_combat.CurrentRound`（`InteractiveCombat.cs:361`、`PartyCombat.cs:140`），
    /// 而预告路径传的是 `CurrentRound + ahead`（`:122`）。做成入参才能既复刻预告的 lookahead
    /// 又让测试不受 `state` 影响。
    Cycled {
        /// 1-based 轮次（= 入参 `round`）。
        round: i32,
        /// `Actions` 里的下标（0 起）。
        slot: u16,
    },
    /// 规则分支：命中了**降序重排之后**的第 `index` 条（0 起）。
    ///
    /// `index` 是**排序后**的位置（规格书 §8.1 的字面语义），不是作者列表里的位置 ——
    /// 两者只在存在更高优先级规则时不同，`priority` 也在里面，所以仍能反推。
    Rule {
        /// 降序序列里的位置（0 起）。
        index: u16,
        /// 这条规则的 `Priority`（缺席按参考的默认值 0，`EnemyIntentRules.cs:19`）。
        priority: i32,
    },
}

/// 选中的动作。
///
/// `action_id` **借用镜像串池**：39/394 个 id 超过 `ID_CAP = 40`，最长 54 B（模块头那条约束），
/// 而复用 `Ident<40>` 会在最长那 39 个上直接 `Err(IdTooLong)`。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ActionChoice<'a> {
    /// `EACT` 表内行号（0 起），可直接喂给 [`execute_action`]。
    pub action_row: u32,
    /// `EACT.Id`（最长实测 54 B），指向镜像串池。
    pub action_id: &'a str,
    /// `EACT.Intent.Kind`；`None` = 那一格缺席或为 null（本内容 394/394 有值）。
    ///
    /// 只有 `Kind` 没有 `Label`：core 镜像剥了表现层（规格书 §2.6）。
    pub intent_kind: Option<IntentKind>,
    /// 选中原因。
    pub reason: ChoiceReason,
}

/// **纯函数**：给定状态 + `(遭遇, 槽位)` + 出手者 + 1-based 轮次，回答"它这一回合用哪个动作"。
///
/// 零副作用：`state` 是 `&CombatState`（**借不到可变引用就不可能推进 RNG**），不分配，
/// 不写任何状态。`random_step` 前后必然相等，`zero_rng_the_selector_never_touches_random_step`
/// 钉住它。
///
/// 分支树（逐条对应 `EnemyIntentRules.cs:156-166`）：
///
/// ```text
/// B0  record.Id != actor            → Ok(None)      :156-157（查表不命中）
/// B1  有规则且首条匹配              → Ok(Some(..))  :159-162（Priority 降序，首个匹配胜）
/// B2  有规则但全不匹配              → 落到 B3       :159 循环走完不返回，:164 继续
/// B3  Actions 非空                  → Ok(Some(..))  :164-165  下标 = (round-1) % count
/// B4  Actions 为空                  → Ok(None)      :166
/// Err 条件求不出来 / 内容坏了        → Err(..)        条件求值器**抛**，不是"当作不匹配"
/// ```
///
/// **B2 与 B0 的区别是本模块最容易被写错的地方**：B2 是"规则失败 ≠ 放弃行动"，
/// 它会落回循环（§7.4 原文："If no rule matches, the enemy falls back to its plain Actions
/// cycle"）；B0 才是"这个敌人不在名单里 ⇒ 这次没有动作"。两者一个 `Some` 一个 `None`，
/// `rules_that_all_miss_fall_back_to_the_cycle_not_to_none` 与
/// `b0_actor_not_in_this_encounter_has_no_action` 成对钉住。
///
/// ⚠️ 条件求值**在排序后的顺序上进行**，遇到第一个 `Err` 就**立刻返回 `Err`**（不跳过这条
/// 继续看后面的规则）：参考的 `rule.Condition.Matches(...)` 抛出会让整个选择器抛出，
/// 而我们这边"内核还没做到"的错误同理 —— 把它当"不匹配"跳过去，就是在用假数据继续选。
pub fn select_action<'a>(
    state: &CombatState,
    content: &'a Content<'a>,
    at: EnemySlot,
    actor: &CombatantId,
    round: i32,
) -> Result<Option<ActionChoice<'a>>, IntentError> {
    let record = enemy_record(content, at)?;

    // ── B0：`byId.TryGetValue(enemyId, out var enemy)` 不命中（`:156-157`）。
    let record_id = record.str_field("Id")?.ok_or(IntentError::Missing("Id"))?;
    // Same rule as locate_enemy: a spawned combatant is <definition>#<n>, and it is still that
    // definition for the purpose of choosing a move (§123).
    let raw = actor.as_str();
    let definition = raw.split('#').next().unwrap_or(raw);
    if record_id != raw && record_id != definition {
        return Ok(None);
    }

    // ── B1/B2：规则（`if (enemy.IntentRules.Count > 0)`，`:159`）。
    let mut rule_ids = [0u16; MAX_INTENT_RULES];
    let rule_count = record.term_list_field("IntentRules", &mut rule_ids)?;
    if rule_count > 0 {
        // `OrderByDescending(r => r.Priority)`（`:160`）：降序，等值保持作者顺序（偏离 D5）。
        let mut priorities = [0i32; MAX_INTENT_RULES];
        for (slot, id) in rule_ids.iter().enumerate().take(rule_count) {
            priorities[slot] = rule_priority(record.child(*id))?;
        }
        let order = sorted_by_priority_desc(&priorities, rule_count);

        for (rank, index) in order.iter().enumerate() {
            let index = usize::from(*index);
            let rule = record.child(rule_ids[index]);
            let condition = rule
                .node_field("Condition")?
                .ok_or(IntentError::Missing("Condition"))?;
            // 求不出来就**立刻**响亮失败（不是"当作不匹配"，见函数文档最后一段）。
            if condition_matches(state, content, actor, condition)? {
                let action_id = rule.str_field("Action")?.ok_or(IntentError::Missing("Action"))?;
                let reason = ChoiceReason::Rule {
                    index: rank as u16,
                    priority: priorities[index],
                };
                return Ok(Some(choice(content, action_id, reason)?));
            }
        }
    }

    // ── B3/B4：循环（`enemy.Actions.Count > 0 ? … : null`，`:164-166`）。
    let mut action_ids = [0u16; MAX_ACTIONS];
    let action_count = record.str_list_field("Actions", &mut action_ids)?;
    if action_count == 0 {
        return Ok(None);
    }
    if round < 1 {
        // 有意偏离 D1：参考在这里是 `(round-1) % n` 的负数下标。
        return Err(IntentError::InvalidRound(round));
    }
    // 1-based：round=1 取第 0 个（`EnemyIntentRulesTests.cs:63-71` 钉住的就是这条）。
    let slot = ((round - 1) % action_count as i32) as usize;
    let action_id = content
        .string(action_ids[slot])
        .ok_or(IntentError::Missing("Actions"))?;
    Ok(Some(choice(
        content,
        action_id,
        ChoiceReason::Cycled {
            round,
            slot: slot as u16,
        },
    )?))
}

/// `intent.ascensionAtLeast` 的那一次比较（§187）。
///
/// 单独成函数不是为了好看：`condition_matches` 需要一个**内容里的 term** 才能跑，而本内容
/// 目前没有任何规则用这条条件（所有有出处的 A17/18/19 改动都是数值，走 `EACT.ProgramAsc`）。
/// 把比较抽出来，判据就能在两侧各测一次，而"这条条件真的被分派到了"由
/// `every_condition_kind_is_reachable`（下面）钉住。
#[must_use]
pub const fn ascension_at_least(level: u8, value: i32) -> bool {
    (level as i32) >= value
}

/// 求值一条 `IntentRule.Condition`。
///
/// 单独公开是因为 10 个原语的语义是引擎硬编码（规格书 §8.2），测试要逐个打。
///
/// **不需要 `Content`**（规格书 §8.1 的建议签名里带着它，理由是"把 CounterId/StatusId 串解析
/// 出来"）：本实现拿条件自己那个 `F_STR` 字段的 `&str` 直接与
/// `Combatant::counters()` 里的 `CounterId::as_str()` 比，**不构造任何定容 id 类型** ⇒
/// 既不需要镜像，也不会给计数器名引入一个参考实现没有的容量上限
/// （`CounterId` 是 `Ident<32>`，本内容最长 16 B，但那是内容的性质、不是规则）。
///
/// 三种"求不出来"要分清：
///
/// * 结构坏了（缺字段、类型不对）⇒ [`IntentError::Ir`] / [`IntentError::Missing`]。
/// * 判别串不在这 10 种里 ⇒ [`IntentError::UnknownConditionKind`]。
/// * 是这 10 种之一但内核还没有这个能力 ⇒ [`IntentError::UnsupportedCondition`]（偏离 D3）。
///
/// 与参考逐行对齐的语义（`EnemyIntentRules.cs:85-93`）：
/// * 出手者**不在状态里** ⇒ `false`（`:89-90` 的 `!TryGetCombatant(...) ⇒ return false`），
///   **不是错误** —— 注意这与 B0 是两件事：B0 查的是**内容名单**，这里查的是**状态**。
/// * 计数器**缺席读 0**（`CombatantState.cs:64` 的 `GetCounter` 原话："Absent counter reads as 0"）。
/// * `Op` 不认识 ⇒ 抛（`:34`）。
pub fn condition_matches(
    state: &CombatState,
    content: &Content<'_>,
    actor: &CombatantId,
    condition: NodeRef<'_>,
) -> Result<bool, IntentError> {
    let kind = ConditionKind::from_wire_name(condition.kind_str()?)
        .ok_or(IntentError::UnknownConditionKind)?;
    match kind {
        // `intent.ascensionAtLeast`（§187）：本场战斗的 Ascension 等级 ≥ `Value`。
        //
        // 它是"内容能换招式表"的唯一入口：A17/18/19 在 StS 里是每只怪 `getMove` 里的一段 `if`，
        // 我们不给每只怪写代码，而是让内容写一条**更高优先级**的 `IntentRule`。
        ConditionKind::AscensionAtLeast => {
            let value = condition
                .int_field("Value")?
                .ok_or(IntentError::Missing("Value"))?;
            Ok(ascension_at_least(state.ascension(), value))
        }
        ConditionKind::SelfHasCounter => {
            let counter = condition
                .str_field("Counter")?
                .ok_or(IntentError::Missing("Counter"))?;
            let op = compare_op(condition)?;
            let value = condition
                .int_field("Value")?
                .ok_or(IntentError::Missing("Value"))?;
            // `:89-90`：出手者不在状态里 ⇒ false（不是错误）。
            let Some(combatant) = state.combatant(actor) else {
                return Ok(false);
            };
            // `c.GetCounter(Counter)`（`:91`）⇒ 缺席读 0（`CombatantState.cs:64`）。
            let current = combatant
                .counters()
                .iter()
                .find(|entry| entry.key.as_str() == counter)
                .map_or(0, |entry| entry.value);
            Ok(op.apply(current, value))
        }
        // `intent.healthPercent`（`Run\Serialization\RunJson.cs` 注册表里的一条；C# 签名的参数是
        // `Op, Percent`）。判据是**出手者当前生命的百分比**：
        //   `Percent = current * 100 / max`（整数除法，`max <= 0` 时按 0 处理）。
        // 这是"Boss 半血换招"唯一需要的那种条件（`port-plan.md` §123）。
        ConditionKind::HealthPercent => {
            let op = compare_op(condition)?;
            let percent = condition
                .int_field("Percent")?
                .ok_or(IntentError::Missing("Percent"))?;
            let Some(combatant) = state.combatant(actor) else {
                return Ok(false);
            };
            let max = combatant.health_max;
            let current = combatant.health_current;
            let ratio = if max > 0 { current * 100 / max } else { 0 };
            Ok(op.apply(ratio, percent))
        }
        // `intent.round`：当前轮次（`Op, Round`）。
        ConditionKind::Round => {
            let op = compare_op(condition)?;
            let round = condition
                .int_field("Round")?
                .ok_or(IntentError::Missing("Round"))?;
            Ok(op.apply(state.current_round, round))
        }
        // `intent.selfHasStatus`：出手者戴着 `Status`，层数 >= `MinStacks`（缺省 1）。
        ConditionKind::SelfHasStatus => {
            let Some(combatant) = state.combatant(actor) else {
                return Ok(false);
            };
            Ok(carries_status(combatant, condition))
        }
        // `intent.opponentHasStatus`：**对手阵营**里有人戴着它（出手者是敌人时，对手就是英雄）。
        ConditionKind::OpponentHasStatus => {
            let Some(me) = state.combatant(actor) else {
                return Ok(false);
            };
            let team = me.team_id;
            let mut found = false;
            for other in state.combatants() {
                if other.team_id == team || !is_alive(state, &other.id) {
                    continue;
                }
                if carries_status(other, condition) {
                    found = true;
                    break;
                }
            }
            Ok(found)
        }
        // `intent.selfResource`：出手者的某个资源池（`Resource, Op, Value`）。
        ConditionKind::SelfResource => {
            let resource = condition
                .str_field("Resource")?
                .ok_or(IntentError::Missing("Resource"))?;
            let op = compare_op(condition)?;
            let value = condition
                .int_field("Value")?
                .ok_or(IntentError::Missing("Value"))?;
            let Some(combatant) = state.combatant(actor) else {
                return Ok(false);
            };
            let current = combatant
                .resources()
                .iter()
                .find(|entry| entry.key.as_str() == resource)
                .map_or(0, |entry| entry.pool.current);
            Ok(op.apply(current, value))
        }
        // `intent.allOf`：子条件全真；**空列表 ⇒ true**（空合取）。
        ConditionKind::AllOf => {
            let mut ids = [0u16; MAX_CONDITION_CHILDREN];
            let count = condition.term_list_field("Conditions", &mut ids)?;
            let mut all = true;
            for id in ids.iter().take(count) {
                if !condition_matches(state, content, actor, NodeRef::new(content, *id))? {
                    all = false;
                    break;
                }
            }
            Ok(all)
        }
        // `intent.anyOf`：子条件任一真；**空列表 ⇒ false**。
        ConditionKind::AnyOf => {
            let mut ids = [0u16; MAX_CONDITION_CHILDREN];
            let count = condition.term_list_field("Conditions", &mut ids)?;
            let mut any = false;
            for id in ids.iter().take(count) {
                if condition_matches(state, content, actor, NodeRef::new(content, *id))? {
                    any = true;
                    break;
                }
            }
            Ok(any)
        }
        // `intent.not`：内层条件取反。
        ConditionKind::Not => {
            let inner = condition
                .node_field("Condition")?
                .ok_or(IntentError::Missing("Condition"))?;
            Ok(!condition_matches(state, content, actor, inner)?)
        }
        // `intent.opponentCardsPlayed`：**对手阵营**这一回合（或上一回合）打了几张牌。
        // `LastTurn` 缺省 **true**（参考的默认值）。
        ConditionKind::OpponentCardsPlayed => {
            let op = compare_op(condition)?;
            let value = condition
                .int_field("Value")?
                .ok_or(IntentError::Missing("Value"))?;
            let last_turn = condition.bool_field("LastTurn")?.unwrap_or(true);
            let Some(me) = state.combatant(actor) else {
                return Ok(false);
            };
            let team = me.team_id;
            let mut played = 0i32;
            for other in state.combatants() {
                if other.team_id == team {
                    continue;
                }
                played = played.saturating_add(if last_turn {
                    state.cards_played_last_turn
                } else {
                    state.cards_played_this_turn
                });
                // The counters are fight-wide, not per combatant: break after the first opponent so
                // a two-enemy fight does not double-count.
                break;
            }
            Ok(op.apply(played, value))
        }
        // 到这里只可能是未来新增的 kind —— 响亮拒绝，**不**当作"不匹配"。
        unsupported => Err(IntentError::UnsupportedCondition(unsupported)),
    }
}

// ===========================================================================
// 执行
// ===========================================================================

/// 取 `EACT` 第 `action_row` 行的**效果程序根节点**。
///
/// 路径与卡的完全同形（`ir.rs:481-506` 的 `card_program_root`）：行 → `Program` 格（`F_TERM`）
/// → `_obj(Id,MaxNodeDepth,MaxProgramSteps,Root)`（op 116，**没有判别式**）→ `Root` 字段。
///
/// 为什么在 `intent.rs` 里而不是 `ir.rs` 里：`Ir` 只有 `card_program_root`（硬编码
/// `Table::Card`），规格书 §8.1 也提议补一个 `enemy_action_program_root`。本轮任务的约束是
/// **只准改 `intent.rs`**，所以它是这里的一个自由函数；将来应当挪进 `ir.rs`
/// （那时这一份删掉，与 `play.rs:751-753` 处理同类问题的办法一致）。
///
/// 每一条断链都报错而不是返回半个东西：行号越界 ⇒ `Missing("EACT row")`、
/// `Program` 缺席/null ⇒ `Missing("Program")`（本内容 394/394 有值，所以缺席就是内容坏了）、
/// 格声明成非 `F_TERM` ⇒ `Ir( WrongKind("F_TERM") )`、`Root` 缺席 ⇒ `Missing("Root")`。
pub fn enemy_action_program_root<'a>(
    content: &'a Content<'a>,
    action_row: u32,
) -> Result<NodeRef<'a>, IntentError> {
    envelope(content, action_row)?
        .node_field("Root")?
        .ok_or(IntentError::Missing("Root"))
}

/// 执行一次敌方动作（**严格面**：除 actor 已倒下这个 no-op 外，失败一律 `Err`）。
///
/// 与 `play::play_card` 同构，和参考走**同一条**执行器（规格书 §6.4 的逐行对照表）：
/// `exec::execute(root, ctx)`，`source = Some(actor)`、`event_target = target`。
/// 本内容的 394 个程序只用了 `sequence`/`dealDamage`/`applyStatus`/`gainBlock`/
/// `setCombatantCounter` 五种节点与 `const`/算术/`combatantStatusStacks`/`combatantCounter`
/// 六种表达式，全部已在 `exec.rs` 实现（§4.3）—— 所以这一层**没有任何求值代码**。
///
/// 四件与参考对齐的事：
///
/// 1. **actor 不存在或已倒下 ⇒ 立刻 `Ok(ExecStats::default())`**（`EnemyActionEffects.cs:20-21`
///    的 `if (!TryGetCombatant(actor) || !actor.IsAlive) return;`）。存活判定用
///    [`crate::turn::is_alive`]（`lifecycle_state == Alive`，与参考 `IsAlive` 同义）。
///    `stats.nodes == 0` 就是"什么都没做"的可观察信号（偏离 D4）。
/// 2. **`target` 已倒下 / 不存在 ⇒ 不是错误**：`sel.eventTarget` 解出空集
///    （`CombatantTargetSelectors.cs:122-132`，`targets.rs:42` 已冻结"空集不是错"）。
///    这一段由 `exec.rs` 负责，本模块把它原样交给 `ExecContext::event_target`。
/// 3. **`MaxProgramSteps` 从信封读**（本内容 1024），缺席/非正数按参考构造函数的默认 1024。
/// 4. **战斗已结束 ⇒ `exec::execute` 自己返回零统计**（参考的三队列循环条件
///    `while (hasPending) && Result == Ongoing`）。本模块不重复判断。
///
/// ⚠️ 故意**不**做的（每条都有依据，不是遗漏）：
/// * `BeginActionScope`/`CloseAction`（`ActionResolved.DealtDamage`）：内核没有作用域存储，
///   它也不进快照/哈希（`play.rs` 的偏离 D5 同一条）。
/// * `standard.action_fails` 那条"先宣布"分支（`EnemyActionEffects.cs:33-62`）：要事件队列，
///   v1 不可达（规格书 §6.2 自己写了"所以这条分支在内核 v1 里必然不可达"）。
///
/// # `exec_num` / `chain_num` 两条发号器（2026-10-19 的整局对拍实测）
///
/// 参考的 `EffectProgramExecutor.Execute` 第一件事就是分配执行号
/// （`Effects/Programs/EffectProgramExecution.cs:27` 的 `combat.AllocateProgramExecutionId()`
/// —— **我读过那一行**），出牌与敌动作走**同一个**执行器。出牌侧内核早就分了
/// （`play.rs` 的 `apply_plan`），敌动作侧**漏了**，后果是 `exec_num` 少 1、指纹必然发散。
///
/// 数据（`native/fight_diff.py` + 用"改 C# 规范文本一个字段再 sha256"反推出每步的唯一解）：
///
/// | 场景·步 | 事件 | C# `(chain, exec)` | 修正前内核 |
/// |---|---|---|---|
/// | `enemy_hits` 0 | 开回合 + 结束回合 + 开敌方回合 | (4, 1) | (1, 1) |
/// | `enemy_hits` 1 | `desk_jab` 一次 | (6, 2) | (1, 1) |
/// | `refusals` 3 | 敌方动作**没**发生（还是英雄回合） | (8, 3) | (1, 3) |
///
/// ⇒ 一次**真的执行了的**敌方动作让 `exec_num +1`、`chain_num +2`。
///
/// **证据强度**：那两个增量是**实测且唯一**的（每步的 `(chain, exec)` 只有一组解）；
/// 拆成"请求 +1 / 收尾 +1"是读下面两段源码拆的，**没有逐笔单独观测**（内核没有队列，
/// 造不出"只发生第一笔"的局面）。`exec_num +1` 那一半是硬证据：它只可能来自
/// `EffectProgramExecution.cs:27`，而且出牌侧一直是对的、敌动作侧一直少 1。
///
/// `chain_num +2` 的来源（`CombatState.cs` 的 `CreateRootEffectChain` 是唯一的自增点，
/// 一共三个调用口：`:386` `EnqueueEffect`、`:446` `EnqueueEvent`、`:495`
/// `CreateTriggeredEffectChain`，外加 `EffectProgramExecution.cs:31`）：
///
/// 1. `ScenarioRunner.cs:191` 的 `combat.EnqueueEffect(new ExecuteEnemyActionEffectRequest(…))`
///    —— 顶层入队，`CurrentEffectChain` 为空 ⇒ 建根链 **+1**；
/// 2. 节目跑完之后 `onTerminal` → `CombatCardPlayProcessor.CloseAction` →
///    `EnqueueEvent(ActionResolvedCombatEvent)`（`EnemyActionEffects.cs:121`），
///    而 `onTerminal` 是**从续延里**跑的（`ResolvePendingQueues` 的
///    `TryDequeueContinuation`，`CombatEventHandling.cs:107-111`，在 `EnterEffectChain`
///    的 `using` 之外）⇒ 又一次顶层入队 **+1**。
///
/// 内核没有队列，所以这两次自增写成两行显式的
/// [`CombatState::create_root_effect_chain`] 调用，位置就是"受理这次请求"/"动作收尾"。
/// ⚠️ 三种**不涨**的情况也都对得上数据：action 没发出去（`enemy.IsAlive` / 注册表 /
/// 回合归属任一条挡在前面 —— 参考的 `ScenarioRunner.cs:163-189` 是在入队**之前**挡的）、
/// 节目跑到一半战斗结束（Cancelled，`CloseAction` 那次入队落在还开着的链里 ⇒ +0）、
/// 节目 fault（`MarkFaulted` 在节点的 `using (EnterEffectChain)` 里跑 ⇒ +0）。
pub fn execute_action(
    state: &mut CombatState,
    content: &Content<'_>,
    actor: &CombatantId,
    action_row: u32,
    target: Option<CombatantId>,
) -> Result<ExecStats, IntentError> {
    if !is_alive(state, actor) {
        // §6.1 `:20-21`：死掉的 actor 是**静默 no-op**。
        return Ok(ExecStats::default());
    }
    // ① 受理这次请求（`ScenarioRunner.cs:191` 的顶层入队）⇒ 根链 +1。
    //    放在读信封之前：请求已经入队了才轮到处理器读内容，与参考同序。
    let _request_chain = state.create_root_effect_chain();

    // §192：升档节目是一张**变体列表**（`[{AscensionMin, Program}, …]`），不是"一个信封 +
    // 一个阈值"。理由：一个招式可能有两个档位（`jaw_worm.bellow` 的 Strength 在 A2 升、
    // Block 在 A17 升），两格表达不了 —— §190 当时只能让较早的那个赢。
    //
    // 判定全在 `Content::ascension_program` 里（"阈值 ≤ 等级的里面取最大的"），这里只做一件事：
    // 没有变体就退回 `Program`。**顺序不参与判定**，所以内容里把 A17 那条写在前面也不会
    // 悄悄换档；"阈值必须升序且不重复"由内容门的独立第二份钉住（`sts_content_check.py`）。
    //
    // ⚠️ 变体是**与 `Program` 同形的信封**（`{Root, MaxProgramSteps, …}`），不是裸 `Root`：
    // §187 第一版塞了 `Root`，于是下一句 `envelope.node_field("Root")` 去 `node.dealDamage`
    // 里找 `Root`，当场 `Missing("Root")`。选的是"用哪个信封"，不是"用哪个 Root"。
    let envelope = {
        let base = envelope(content, action_row)?;
        let row = content
            .enemy_action(action_row)
            .ok_or(IntentError::Missing("EACT row"))?;
        match content.ascension_program(row, i32::from(state.ascension()))? {
            Some(variant) => variant,
            None => base,
        }
    };
    let root = envelope
        .node_field("Root")?
        .ok_or(IntentError::Missing("Root"))?;
    // `MaxProgramSteps`（信封，本内容 394/394 = 1024）；缺席/非正 ⇒ 参考默认 1024。
    let steps = match envelope.int_field("MaxProgramSteps")? {
        Some(value) if value > 0 => value as u32,
        _ => DEFAULT_MAX_PROGRAM_STEPS,
    };
    // ② 执行号（`EffectProgramExecution.cs:27`）。与 `play.rs` 的 D3 是**同一条**偏差：
    //    参考是"预检 → 分配"（`:23` 早于 `:25-28`），内核把分配放在 `exec::execute`
    //    之前、预检之外。本内容 394/394 个敌动作程序都过预检，所以今天不可达。
    let _execution_id = state.allocate_program_execution_id();
    let stats = {
        let mut context =
            ExecContext::new(state, Some(*actor), target, None, steps).with_content(content);
        exec::execute(root, &mut context)?
    };

    // ③ 收尾（`EnemyActionEffects.cs:121` 的 `CloseAction` ⇒ `EnqueueEvent(ActionResolved)`）。
    //    只有"节目正常跑完、战斗还在进行"才是参考那次**续延里的**顶层入队；
    //    Cancelled 那次入队落在还开着的链上（+0），fault 同理（错误已经在上面 `?` 出去了）。
    if state.result == crate::state::CombatResult::Ongoing {
        let _wrap_up_chain = state.create_root_effect_chain();
    }
    Ok(stats)
}

// ===========================================================================
// 内部：内容镜像的读取
// ===========================================================================

/// `ENCT[encounter].Enemies` 的元素（term id）写进 `out`，返回个数。
///
/// 二进制形状是**实测**的：格是 `F_TERM`，指向的 term 是 `_arr`（op 4），`_arr` 唯一的字段是
/// `F_TERMLIST` ⇒ 两个槽是 `(AUX 起址, 个数)`，每个 `AUX` 格装的是**term id**。
/// 这与 `play.rs:754-788` 读 `CARD.Tags` 的形状完全一样（那边元素是 `_wrap_lower`，这边是
/// `_obj` 的 enemy record）。
fn encounter_enemy_ids(
    content: &Content<'_>,
    encounter: u32,
    out: &mut [u16],
) -> Result<usize, IntentError> {
    let row = content
        .encounter(encounter)
        .ok_or(IntentError::Missing("ENCT row"))?;
    let list = match row.enemies() {
        ABSENT16 | NULL16 => return Err(IntentError::Missing("Enemies")),
        id => id,
    };
    arr_items(content, list, out)
}

/// 读一个 `_arr` term 的元素（`(AUX 起址, 个数)`）。
fn arr_items(
    content: &Content<'_>,
    list: u16,
    out: &mut [u16],
) -> Result<usize, IntentError> {
    let term = content.term(list).ok_or(IrError::Term(list))?;
    if term.op != OP_ARR {
        return Err(IrError::WrongKind("_arr").into());
    }
    let start = term.slot(0).ok_or(IrError::Slot)?;
    let count = term.slot(1).ok_or(IrError::Slot)?;
    if count == LIST_ABSENT || count == LIST_NULL {
        return Ok(0);
    }
    let count = usize::from(count);
    if count > out.len() {
        // **不截断**（`ir.rs:366` 同一条合约）。
        return Err(IrError::List.into());
    }
    for (offset, element) in out.iter_mut().enumerate().take(count) {
        let cell = usize::from(start).checked_add(offset).ok_or(IrError::List)?;
        let cell = u16::try_from(cell).map_err(|_| IrError::List)?;
        *element = content.aux(cell).ok_or(IrError::List)?;
    }
    Ok(count)
}

/// `ENCT[at.encounter].Enemies[at.index]` 这个 enemy record 对象。
fn enemy_record<'a>(content: &'a Content<'a>, at: EnemySlot) -> Result<NodeRef<'a>, IntentError> {
    let mut ids = [0u16; MAX_ENEMIES];
    let count = encounter_enemy_ids(content, at.encounter, &mut ids)?;
    let index = usize::from(at.index);
    if index >= count {
        return Err(IntentError::Slot {
            encounter: at.encounter,
            index: at.index,
        });
    }
    Ok(NodeRef::new(content, ids[index]))
}

/// `EACT[action_row]` 的 `Program` 格指向的信封（`_obj(Id,MaxNodeDepth,MaxProgramSteps,Root)`）。
fn envelope<'a>(content: &'a Content<'a>, action_row: u32) -> Result<NodeRef<'a>, IntentError> {
    let row = content
        .row(Table::EnemyAction, action_row)
        .ok_or(IntentError::Missing("EACT row"))?;
    let program = term_cell(row, "Program")?.ok_or(IntentError::Missing("Program"))?;
    Ok(NodeRef::new(content, program))
}

/// 取一行的 `F_TERM` 格，返回它指向的 term id（`ABSENT16`/`NULL16` ⇒ `Ok(None)`）。
///
/// 与 `play.rs:754-760` 同一个形状：先确认 schema 说这一格是 `F_TERM`，再读槽。
/// **不解释哨兵为 term id** —— `0xFFFF` 会被当成一个巨大下标。
fn term_cell(row: Row<'_>, name: &'static str) -> Result<Option<u16>, IntentError> {
    let cell = row.cell_index(name).ok_or(IntentError::Missing(name))?;
    if row.cell_kind(cell) != Some(F_TERM) {
        return Err(IrError::WrongKind("F_TERM").into());
    }
    match row.cell(cell as u32) {
        None => Err(IntentError::Missing(name)),
        Some(ABSENT16) | Some(NULL16) => Ok(None),
        Some(id) => Ok(Some(id)),
    }
}

/// 一条规则的 `Priority`；缺席按参考的默认值 0（`EnemyIntentRules.cs:19` 的 `int Priority = 0`）。
fn rule_priority(rule: NodeRef<'_>) -> Result<i32, IntentError> {
    Ok(rule.int_field("Priority")?.unwrap_or(0))
}

/// 稳定插入排序：`Priority` 降序，等值保持原下标顺序（偏离 D5）。
///
/// 返回**下标序列**（前 `count` 项有效），调用方用它遍历。用插入排序而不是 `sort_by`：
/// 这是 `no_std` 且**不许分配**，而 `slice::sort_by` 需要一个真的切片 —— 我们有定长数组，
/// 长度只有 1..=3（实测），O(n²) 完全无所谓。
fn sorted_by_priority_desc(
    priorities: &[i32; MAX_INTENT_RULES],
    count: usize,
) -> [u16; MAX_INTENT_RULES] {
    let mut order = [0u16; MAX_INTENT_RULES];
    for index in 0..count {
        let mut position = index;
        // 只在**严格更小**时前移 ⇒ 等值留在原位（稳定）。
        while position > 0 && priorities[usize::from(order[position - 1])] < priorities[index] {
            order[position] = order[position - 1];
            position -= 1;
        }
        order[position] = index as u16;
    }
    order
}

/// 读条件的 `Op` 字段并解析；缺席 ⇒ `Missing("Op")`，不认识 ⇒ `UnknownOperator`（参考抛）。
fn compare_op(condition: NodeRef<'_>) -> Result<CompareOp, IntentError> {
    let name = condition.str_field("Op")?.ok_or(IntentError::Missing("Op"))?;
    CompareOp::from_wire_name(name).ok_or(IntentError::UnknownOperator)
}

/// 把一个动作 id 变成一个可执行的 [`ActionChoice`]：解析 `IDX → EACT` 行、读 `Intent.Kind`。
///
/// 多做一步**一致性核对**：`IDX` 说这个 id 在第 `row` 行，那就要求该行的 `Id` 逐字节相符。
/// 不做这一步的话，一张被改坏的符号表会让"动作 id"和"动作程序"静默错位（跑的是别人的程序）。
fn choice<'a>(
    content: &'a Content<'a>,
    action_id: &'a str,
    reason: ChoiceReason,
) -> Result<ActionChoice<'a>, IntentError> {
    let entry = content
        .lookup_in(action_id, EK_EACTION)
        .ok_or(IntentError::UnknownAction)?;
    let action_row = u32::from(entry.index);
    let row = content
        .enemy_action(action_row)
        .ok_or(IntentError::Missing("EACT row"))?;
    if content.string(row.id()) != Some(action_id) {
        return Err(IntentError::UnknownAction);
    }
    Ok(ActionChoice {
        action_row,
        action_id,
        intent_kind: intent_kind_of(content, row.row())?,
        reason,
    })
}

/// `EACT.Intent` 格（`_obj(Kind)`）→ [`IntentKind`]。
///
/// 三态：格缺席/为 null ⇒ `Ok(None)`（本内容 394/394 有值）；有值但 `Kind` 字段缺席 ⇒
/// `Missing("Kind")`；`Kind` 串不认识 ⇒ `UnknownIntentKind`（参考的 `JsonStringEnumConverter`
/// 在这种输入上同样抛）。
fn intent_kind_of<'a>(
    content: &'a Content<'a>,
    row: Row<'_>,
) -> Result<Option<IntentKind>, IntentError> {
    let Some(id) = term_cell(row, "Intent")? else {
        return Ok(None);
    };
    let kind = NodeRef::new(content, id)
        .str_field("Kind")?
        .ok_or(IntentError::Missing("Kind"))?;
    IntentKind::from_wire_name(kind)
        .map(Some)
        .ok_or(IntentError::UnknownIntentKind)
}

#[cfg(test)]
mod tests {
    //! 测试**读真实镜像**（`tools/contentc/out/content.core.rdcf`，85,616 B，
    //! `content_hash=0xD1075DE5`）。镜像不在仓库里（它是构建产物），所以找不到就 panic 并打印
    //! 生成命令 —— 一个在产物缺席时安静通过的测试等于没有测试（`ir.rs` / `play.rs` 同一条约定）。
    //!
    //! 几条纪律：
    //! * 每个分支都**成对**写：正例旁边必须有一条能区分它的反例（本层最危险的混淆是
    //!   "B0"（不在名单里 ⇒ `None`）与"B2"（规则全不匹配 ⇒ 落回循环 ⇒ `Some`））。
    //! * 期望值全部是**量出来的**（`reader.py`），不是"看着像"。
    //! * 本内容**不存在**"两条都匹配、优先级不同"的规则对（实测 3 条规则的 Priority 是
    //!   20/20/10，前两条条件互斥）⇒ 降序/平局那两条测试在**内存里改两个 `u16`** 造出竞争用例，
    //!   改的是 `TRM` 段里那条规则/条件的槽字节（`term_slot_pos`），**不动磁盘上的产物**。

    use super::*;
    use crate::content::{EK_ENCOUNTER, S_TRM, S_TRW};
    use crate::ir::NodeKind;
    use crate::state::{
        CombatId, Combatant, CombatantDefinitionId, CombatantLifecycleState, CounterId, TeamId,
    };

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

    fn unit(id: &str, team: &str, health: i32) -> Combatant {
        Combatant::new(
            cid(id),
            CombatantDefinitionId::new(id).unwrap(),
            TeamId::new(team).unwrap(),
            health,
            health,
        )
    }

    /// 一个两单位战场：英雄 70/70 + 指定 id 的敌人 40/40（都是施法者的合法目标）。
    fn arena(enemy: &str) -> CombatState {
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state.add_combatant(unit("hero", "player", 70)).unwrap();
        state.add_combatant(unit(enemy, "enemy", 40)).unwrap();
        state
    }

    /// Push a status instance directly -- same shape as `host.rs`'s `give`.
    fn set_status(state: &mut CombatState, who: &CombatantId, definition: &str, stacks: i32) {
        // `StatusInstanceId` is 16 bytes, shorter than ids like `standard.unawakened` -- the instance
        // id is arbitrary (only the **definition** id is matched), so name it after the stacks.
        let instance = crate::state::StatusInstance::new(
            crate::state::StatusInstanceId::new(&std::format!("st{stacks}")).unwrap(),
            crate::state::StatusDefinitionId::new(definition).unwrap(),
            crate::state::StatusPolarity::Buff,
        )
        .with_stacks(stacks);
        state
            .combatant_mut(who)
            .unwrap()
            .push_status(instance)
            .unwrap();
    }

    /// Drop every status instance -- "the guard was spent" in one line.
    fn clear_statuses(state: &mut CombatState, who: &CombatantId) {
        let combatant = state.combatant_mut(who).unwrap();
        for index in (0..combatant.statuses().len()).rev() {
            combatant.remove_status(index);
        }
    }

    fn set_counter(state: &mut CombatState, who: &CombatantId, key: &str, value: i32) {
        state
            .combatant_mut(who)
            .unwrap()
            .set_counter(CounterId::new(key).unwrap(), value)
            .unwrap();
    }

    /// `ENCT` 行号（按遭遇 id 查 `IDX`）。
    fn encounter_row(content: &Content<'_>, id: &str) -> u32 {
        u32::from(
            content
                .lookup_in(id, EK_ENCOUNTER)
                .expect("遭遇 id 必须在 IDX 里")
                .index,
        )
    }

    fn slot(content: &Content<'_>, encounter: &str, index: u16) -> EnemySlot {
        EnemySlot {
            encounter: encounter_row(content, encounter),
            index,
        }
    }

    /// 某个槽位上 enemy record 的 `Id`（= 战斗员 id，规格书 §5.3 的关联方式）。
    fn record_id<'a>(content: &'a Content<'a>, at: EnemySlot) -> &'a str {
        enemy_record(content, at)
            .unwrap()
            .str_field("Id")
            .unwrap()
            .unwrap()
    }

    /// §148：`Spire Growth` 的**行动顺序**是"第一回合 Strategic，之后在两个 Aggressive 之间循环"。
    ///
    /// 这**不是**新机制：规则表（`IntentRules`）+ 10 条条件原语早就在，`intent.round` 就是
    /// "首回合"的表达方式。缺的只是有人用它 —— 上一版把 `strategic` 放进 `Actions` 三格循环里，
    /// 于是它每三回合重复一次，而 StS 里它只出现一次。
    ///
    /// 断言的是**三个回合**：1 走规则、2/3 走循环（`(round-1) % 2`），因为"规则没匹配"与
    /// "规则根本不存在"在只看第 1 回合时是同一种观察。
    #[test]
    fn a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let at = slot(&content, "enc_spire_growth", 0);
        let mut state = arena("spire_growth");
        let actor = cid("spire_growth");

        // ⚠️ `intent.round` 读的是**状态里的 `current_round`**，不是 `select_action` 的
        // `round` 实参（那是循环用的 1-based 回合）。真实战斗里两者一起前进，测试里就得手动
        // 让状态也前进 —— 否则状态停在开局那一轮，规则会**每一回合**都命中（第一版就踩了这个，
        // 报出来的是"第 2 回合还在 Strategic"）。
        let pick = |state: &mut CombatState, round: i32| {
            state.current_round = round;
            select_action(state, &content, at, &actor, round)
                .expect("intent")
                .expect("an action")
                .action_id
        };

        assert_eq!(pick(&mut state, 1), "spire_growth.strategic", "round 1 opens with Strategic");
        assert_eq!(
            pick(&mut state, 2),
            "spire_growth.aggressive_heavy",
            "the cycle is `(round-1) % 2` ⇒ round 2 is slot 1"
        );
        assert_eq!(pick(&mut state, 3), "spire_growth.aggressive", "round 3 is slot 0");
        // 成对：Strategic 只该出现一次 —— 第 4 回合又回到循环的 slot 1。
        assert_eq!(pick(&mut state, 4), "spire_growth.aggressive_heavy");
    }

    // ================================================================ §194：Boss 池

    /// 三幕的 Boss 池各自三个（wiki：每幕三选一），而且每个成员都能真的建出一个遭遇。
    ///
    /// `encounter_pool` 是内核读 `EncounterTables.<Name>` 的唯一入口，所以这条同时证明了"池子里
    /// 有名字"和"名字指向的遭遇存在"—— 后者在内容门里也查，但这里查的是**内核读到的同一份**。
    #[test]
    fn every_act_has_three_bosses_and_each_one_is_a_buildable_encounter() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        for (pool, expected) in [
            ("Boss", ["enc_slime_boss", "enc_the_guardian", "enc_hexaghost"]),
            ("Boss2", ["enc_the_champ", "enc_bronze_automaton", "enc_the_collector"]),
            ("Boss3", ["enc_time_eater", "enc_awakened_one", "enc_donu_and_deca"]),
        ] {
            let ids = content
                .encounter_pool(pool)
                .unwrap_or_else(|| panic!("`EncounterTables.{pool}` must be readable"));
            let listed: Vec<&str> = ids.iter().copied().filter(|id| !id.is_empty()).collect();
            assert_eq!(listed, expected, "act pool `{pool}`");
            for id in listed {
                let row = encounter_row(&content, id);
                let enemies = content
                    .encounter_enemies(row)
                    .unwrap_or_else(|e| panic!("`{id}` must have enemies: {e:?}"));
                assert!(
                    (1..=3).contains(&enemies.len()),
                    "`{id}` places {} enemies (1..=3)",
                    enemies.len()
                );
            }
        }
    }

    /// Hexaghost 的 7 招循环**是从 wiki 的顺序轮转过的**：`Actions[(round-1) % 7]` 从第 3 回合起
    /// 必须正好落在 Sear, Tackle, Sear, Inflame, Tackle, Sear, Inferno 上。
    ///
    /// 这条测试是这一段唯一能发现"有人把列表理顺了"的判据：顺序错了 Boss 照样打，只是招式顺序漂了。
    #[test]
    fn hexaghost_plays_the_wikis_seven_move_pattern_after_its_two_openers() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let at = slot(&content, "enc_hexaghost", 0);
        let mut state = arena("hexaghost");
        let actor = cid("hexaghost");

        let mut seen = Vec::new();
        for round in 1..=9 {
            state.current_round = round;
            seen.push(
                select_action(&state, &content, at, &actor, round)
                    .expect("intent")
                    .expect("an action")
                    .action_id,
            );
        }
        let expected = [
            "hexaghost.activate",     // turn 1
            "hexaghost.divider",      // turn 2
            "hexaghost.sear",         // turn 3
            "hexaghost.tackle",       // turn 4
            "hexaghost.sear",         // turn 5
            "hexaghost.inflame",      // turn 6
            "hexaghost.tackle",       // turn 7
            "hexaghost.sear",         // turn 8
            "hexaghost.inferno",      // turn 9
        ];
        assert_eq!(seen, expected, "the wiki's pattern from `native/wiki_asc/hexaghost.txt`");
    }

    /// Bronze Automaton：`Stunned` 在**A19 才**被 `Boost` 顶替，而且只顶替那几轮。
    ///
    /// 两侧都测（A0 与 A19），因为"规则提前生效"与"规则根本不生效"在只看一侧时是同一种观察。
    #[test]
    fn the_automaton_swaps_stunned_for_boost_only_at_a19() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let at = slot(&content, "enc_bronze_automaton", 0);
        for (ascension, round_6, round_7) in [
            (0u8, "bronze_automaton.stunned", "bronze_automaton.flail"),
            (19, "bronze_automaton.boost", "bronze_automaton.flail"),
        ] {
            let mut state = arena("bronze_automaton");
            state.set_ascension(ascension);
            let actor = cid("bronze_automaton");
            state.current_round = 6;
            let six = select_action(&state, &content, at, &actor, 6).expect("intent").expect("an action");
            assert_eq!(six.action_id, round_6, "A{ascension} round 6");
            state.current_round = 7;
            let seven = select_action(&state, &content, at, &actor, 7).expect("intent").expect("an action");
            assert_eq!(seven.action_id, round_7, "A{ascension} round 7");
        }
    }

    /// The Champ：回合 4 是 Taunt；HP ≤ 50% 时先 Anger、下一回合 Execute。
    ///
    /// 三个判据各锁一条规则，而三者在"规则不生效"时都表现为"Boss 正常出招"。
    #[test]
    fn the_champ_taunts_every_fourth_round_and_enters_phase_two_below_half() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let at = slot(&content, "enc_the_champ", 0);
        let mut state = arena("the_champ");
        let actor = cid("the_champ");
        let pick = |state: &mut CombatState, round: i32| {
            state.current_round = round;
            select_action(state, &content, at, &actor, round)
                .expect("intent")
                .expect("an action")
                .action_id
        };

        assert_eq!(pick(&mut state, 4), "the_champ.taunt", "taunt lands every 4th round");
        assert_eq!(pick(&mut state, 5), "the_champ.heavy_slash", "and only on the 4th");

        // Drop the boss to half health: the *next* intent is Anger, then Execute.
        {
            let boss = state.combatant_mut(&actor).expect("the champ");
            boss.health_current = boss.health_max / 2;
        }
        assert_eq!(pick(&mut state, 6), "the_champ.anger", "phase two opens with Anger");
        // Anger sets the two counters; the fight would run the program, so set them the same way.
        set_counter(&mut state, &actor, "champ_phase", 1);
        set_counter(&mut state, &actor, "champ_exec", 0);
        assert_eq!(pick(&mut state, 7), "the_champ.execute", "then Execute");
        set_counter(&mut state, &actor, "champ_exec", 1);
        // ⚠️ 第 8 回合**还是** Taunt（每 4 回合一次），所以"循环恢复"要看第 9 回合:
        // `(9-1) % 4 = 0` ⇒ Heavy Slash。这一条是负控的旁证 —— 少写一个数就会在 8 上撞 Taunt。
        assert_eq!(pick(&mut state, 8), "the_champ.taunt", "every 4th round, phase two or not");
        assert_eq!(pick(&mut state, 9), "the_champ.heavy_slash", "afterwards the cycle resumes");
    }

    /// The Awakened One：≤ 25% 血时意图变 Rebirth；Rebirth 之后先 Dark Echo，然后 Tackle/Sludge 交替。
    #[test]
    fn the_awakened_one_flips_to_phase_two_through_its_counters() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let at = slot(&content, "enc_awakened_one", 0);
        let mut state = arena("awakened_one");
        let actor = cid("awakened_one");
        let pick = |state: &mut CombatState, round: i32| {
            state.current_round = round;
            select_action(state, &content, at, &actor, round)
                .expect("intent")
                .expect("an action")
                .action_id
        };

        // §195.2: the phase flip is keyed on the `standard.unawakened` guard being **spent**, not on a
        // health percentage (the guard is what survives the first lethal blow).
        set_status(&mut state, &actor, "standard.unawakened", 1);
        state.current_round = 1;
        assert_eq!(pick(&mut state, 1), "awakened_one.slash", "phase one opens with Slash");
        {
            let boss = state.combatant_mut(&actor).expect("the boss");
            boss.health_current = boss.health_max / 4;
        }
        assert_eq!(
            pick(&mut state, 2),
            "awakened_one.slash",
            "still phase one while the guard is up -- even at 25% HP"
        );
        // The killing blow spends the guard (that is what `DeathPrevention` does in `resolve_damage`).
        clear_statuses(&mut state, &actor);
        assert_eq!(pick(&mut state, 3), "awakened_one.rebirth", "guard spent => Rebirth");
        // Rebirth sets three counters; do what its program does.
        set_counter(&mut state, &actor, "ao_phase", 1);
        set_counter(&mut state, &actor, "ao_started", 0);
        set_counter(&mut state, &actor, "ao_toggle", 0);
        assert_eq!(pick(&mut state, 4), "awakened_one.dark_echo", "phase two opens with Dark Echo");
        set_counter(&mut state, &actor, "ao_started", 1);
        assert_eq!(pick(&mut state, 5), "awakened_one.tackle");
        set_counter(&mut state, &actor, "ao_toggle", 1);
        assert_eq!(pick(&mut state, 6), "awakened_one.sludge");
        set_counter(&mut state, &actor, "ao_toggle", 0);
        assert_eq!(pick(&mut state, 7), "awakened_one.tackle", "Tackle/Sludge alternate");
    }

    // ---------------------------------------------------------------- 补丁工具

    /// term 第 `slot` 个槽在**整个镜像缓冲区**里的绝对字节偏移。
    ///
    /// `TRM` 段的布局：`op`(u16) 紧跟槽数组；`TRW` 是 `u16[n_terms]`，装的是
    /// `byte_offset / 4`（`rdcfmt.py:30`、`content.rs:548-565` 一致）。
    fn term_slot_pos(content: &Content<'_>, term: u16, slot: usize) -> usize {
        let trm = content.section(S_TRM).expect("TRM 段");
        let trw = content.section(S_TRW).expect("TRW 段");
        let at = usize::from(term) * 2;
        let word = u16::from_le_bytes([trw.data[at], trw.data[at + 1]]) as usize;
        trm.offset as usize + word * 4 + 2 + slot * 2
    }

    /// 对象 term 里某个字段的首槽下标（按 `OPD` 字段表累加，与 `ir.rs:269-287` 同一条规则）。
    fn field_slot(content: &Content<'_>, term: u16, name: &str) -> usize {
        let raw = content.term(term).expect("term 必须存在");
        let opcode = content.opcode(raw.op).expect("opcode 必须存在");
        let mut slot = 0usize;
        for index in 0..opcode.nfields() {
            let field = opcode.field(index).expect("字段表");
            let field_name = content.string(field.name_str()).expect("字段名");
            if field_name == name {
                return slot;
            }
            slot += usize::from(field.slots().expect("字段槽数"));
        }
        panic!("term {term} 没有字段 {name}");
    }

    fn slot_value(content: &Content<'_>, term: u16, slot: usize) -> u16 {
        content.term(term).expect("term").slot(slot).expect("slot")
    }

    fn patched(patches: &[(usize, u16)]) -> Vec<u8> {
        let mut blob = core_image();
        for (at, value) in patches {
            blob[*at..*at + 2].copy_from_slice(&value.to_le_bytes());
        }
        blob
    }

    /// `contradictory_signpost`（本内容唯一有 3 条规则的敌人）在镜像里的槽字节位置。
    ///
    /// 顺带**自检**列表顺序：实测这条遭遇的 3 条规则依次是
    /// `P20 signposted_route Equal 1` / `P20 … Equal 2` / `P10 opponentCardsPlayed`
    /// （规格书 §3.6 的逐条输出）。
    struct Signpost {
        rule1_condition: u16,
        rule1_priority: usize,
        rule1_condition_value: usize,
        rule1_condition_op: usize,
    }

    fn signpost(content: &Content<'_>) -> Signpost {
        let at = slot(content, "city_normal_ordinance_04", 0);
        let record = enemy_record(content, at).unwrap();
        let mut rules = [0u16; MAX_INTENT_RULES];
        let count = record.term_list_field("IntentRules", &mut rules).unwrap();
        assert_eq!(count, 3, "§3.6：contradictory_signpost 有 3 条规则");
        let rule1 = rules[1];
        let condition = record
            .child(rule1)
            .node_field("Condition")
            .unwrap()
            .expect("Condition");
        let condition_id = condition.id();
        assert_eq!(
            condition.str_field("Counter").unwrap(),
            Some("signposted_route")
        );
        assert_eq!(condition.int_field("Value").unwrap(), Some(2));
        assert_eq!(record.child(rule1).int_field("Priority").unwrap(), Some(20));
        assert_eq!(
            record.child(rules[0]).int_field("Priority").unwrap(),
            Some(20)
        );
        Signpost {
            rule1_condition: condition_id,
            rule1_priority: term_slot_pos(content, rule1, field_slot(content, rule1, "Priority")),
            rule1_condition_value: term_slot_pos(
                content,
                condition_id,
                field_slot(content, condition_id, "Value"),
            ),
            rule1_condition_op: term_slot_pos(
                content,
                condition_id,
                field_slot(content, condition_id, "Op"),
            ),
        }
    }

    /// **A summoned minion gets an intent** even though the encounter never listed it
    /// (`port-plan.md` §138): the id carries `#<n>`, so `locate_enemy` falls back to the first
    /// encounter in the image that does list the definition.
    #[test]
    fn a_summoned_minion_resolves_through_the_image_not_the_encounter() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // `enc_giant_head` lists one enemy (giant_head); a summoned gremlin is not in it.
        let encounter = encounter_row(&content, "enc_giant_head");
        let summoned = cid("gremlin_wizard#000007");
        let slot = locate_enemy(&content, encounter, &summoned)
            .expect("lookup")
            .expect("a summoned minion must resolve");
        assert_ne!(
            slot.encounter, encounter,
            "it has to resolve to the encounter that actually lists it"
        );

        // ...and that slot really yields a move for the minion.
        let state = arena(summoned.as_str());
        assert!(
            select_action(&state, &content, slot, &summoned, 1)
                .expect("select")
                .is_some(),
            "a summoned minion must have an intent"
        );

        // The reference's B0 still holds for a **stranger** (no `#` suffix): an id from another
        // encounter is not a summon, it is a bug.
        let stranger = cid("minute_moth");
        assert_eq!(
            locate_enemy(&content, encounter, &stranger).expect("lookup"),
            None,
            "a stranger must stay unresolved"
        );
    }

    /// A **spawned** combatant (`acid_slime_m#000003`) still finds its enemy record, so it gets a
    /// real intent instead of "unknown" -- `locate_enemy` falls back to the definition part
    /// (`port-plan.md` §123).
    #[test]
    fn a_spawned_combatant_still_resolves_to_its_enemy_record() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let encounter = encounter_row(&content, "enc_small_slimes");

        let plain = cid("acid_slime_m");
        let spawned = cid("acid_slime_m#000003");
        let plain_slot = locate_enemy(&content, encounter, &plain).expect("lookup");
        let spawned_slot = locate_enemy(&content, encounter, &spawned).expect("lookup");
        assert!(plain_slot.is_some(), "the roster entry must be found by exact id");
        assert_eq!(
            spawned_slot, plain_slot,
            "the spawned one must resolve to the same slot"
        );

        // ...and that slot really yields an action for the spawned combatant.
        let slot = spawned_slot.expect("a slot");
        let state = arena(spawned.as_str());
        assert!(
            select_action(&state, &content, slot, &spawned, 1)
                .expect("select")
                .is_some(),
            "a spawned enemy must have an intent"
        );
    }

    /// **The boss changes its move at half health, from round 2 on.** The rule is a combinator
    /// (`intent.allOf` over `healthPercent` and `round`), so the child term list is exercised too.
    #[test]
    fn a_combinator_rule_switches_the_boss_move() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let at = slot(&content, "enc_slime_boss", 0);
        let owner = cid(record_id(&content, at));

        let mut state = arena(owner.as_str());
        {
            let combatant = state.combatant_mut(&owner).expect("the boss");
            combatant.health_max = 140;
            combatant.health_current = 70; // exactly 50%
        }
        state.current_round = 1;
        let round_one = select_action(&state, &content, at, &owner, 1)
            .expect("select")
            .expect("an action");
        assert_ne!(
            round_one.action_id.to_string(),
            "slime_boss.slam".to_string(),
            "round 1 must not fire the phase rule yet"
        );

        state.current_round = 2;
        let round_two = select_action(&state, &content, at, &owner, 2)
            .expect("select")
            .expect("an action");
        assert_eq!(
            round_two.action_id.to_string(),
            "slime_boss.slam".to_string(),
            "half health from round 2 on => the phase move"
        );

        state.combatant_mut(&owner).expect("the boss").health_current = 140;
        state.current_round = 5;
        let healthy = select_action(&state, &content, at, &owner, 5)
            .expect("select")
            .expect("an action");
        assert_ne!(
            healthy.action_id.to_string(),
            "slime_boss.slam".to_string(),
            "a healthy boss must not slam"
        );
    }

    // ---------------------------------------------------------------- B0

    #[test]
    fn b0_actor_not_in_this_encounter_has_no_action() {
        let blob = core_image();
        let content = parse(&blob);
        let at = slot(&content, "city_easy_01", 0);
        let owner = cid(record_id(&content, at));
        let state = arena(owner.as_str());

        // 正例：名单里的那个 combatant ⇒ 有动作（否则下面的 None 可能是别的原因造成的）。
        assert!(select_action(&state, &content, at, &owner, 1)
            .unwrap()
            .is_some());

        // B0（`EnemyIntentRules.cs:156-157`）：`byId.TryGetValue` 不命中 ⇒ `null`。
        // 用**另一个遭遇**的敌人 id（`minute_moth` 是 `city_normal_delay_07` 的）当出手者。
        let stranger = cid("minute_moth");
        assert_eq!(
            select_action(&state, &content, at, &stranger, 1).unwrap(),
            None,
            "不在名单里 ⇒ None（合法的 no-op，§7.1），**不是** Err、也不是跳过规则"
        );

        // 匹配是**逐字节**的（参考按 id 建字典），大小写不同也算不命中。
        assert_eq!(
            select_action(&state, &content, at, &cid("A_very_official_line"), 1).unwrap(),
            None
        );

        // `locate_enemy` 对同一件事给出同样的答案。
        assert_eq!(locate_enemy(&content, at.encounter, &stranger).unwrap(), None);
        assert_eq!(locate_enemy(&content, at.encounter, &owner).unwrap(), Some(at));
    }

    // ---------------------------------------------------------------- B1

    #[test]
    fn b1_a_matching_rule_beats_the_cycle() {
        let blob = core_image();
        let content = parse(&blob);
        let at = slot(&content, "city_normal_delay_07", 0);
        let actor = cid(record_id(&content, at));

        // 规则：`minute_moth.wingbeat_delay`，条件 `stolen_minute GreaterOrEqual 2`（§3.6）。
        // 计数器缺席 ⇒ 读 0（`CombatantState.cs:64`）⇒ 规则假 ⇒ 循环的第 0 个。
        let state = arena(actor.as_str());
        let cycled = select_action(&state, &content, at, &actor, 1)
            .unwrap()
            .expect("规则不匹配时落回循环");
        assert_eq!(cycled.action_id, "minute_moth.nibble_the_hour");
        assert_eq!(cycled.reason, ChoiceReason::Cycled { round: 1, slot: 0 });

        // 计数器到 2 ⇒ 规则命中 ⇒ **覆盖**循环（`EnemyIntentRules.cs:159-162`）。
        let mut state = arena(actor.as_str());
        set_counter(&mut state, &actor, "stolen_minute", 2);
        let ruled = select_action(&state, &content, at, &actor, 1)
            .unwrap()
            .expect("规则命中");
        assert_eq!(ruled.action_id, "minute_moth.wingbeat_delay");
        assert_eq!(
            ruled.reason,
            ChoiceReason::Rule {
                index: 0,
                priority: 10
            }
        );
        assert_ne!(cycled.action_id, ruled.action_id, "两条分支必须给出不同动作");
    }

    // ---------------------------------------------------------------- B2

    #[test]
    fn rules_that_all_miss_fall_back_to_the_cycle_not_to_none() {
        let blob = core_image();
        let content = parse(&blob);
        let at = slot(&content, "city_easy_01", 0);
        let actor = cid(record_id(&content, at));

        // B2（§7.4 原文："If no rule matches, the enemy falls back to its plain Actions cycle"）。
        // 这条敌人的唯一规则是 `queue_position GreaterOrEqual 3`，计数器缺席 ⇒ 假。
        let state = arena(actor.as_str());
        let choice = select_action(&state, &content, at, &actor, 1)
            .unwrap()
            .expect("规则失败 ≠ 放弃行动；这里必须落回循环，**不是** None");
        assert_eq!(choice.action_id, "a_very_official_line.shuffle_forward");
        assert_eq!(choice.reason, ChoiceReason::Cycled { round: 1, slot: 0 });

        // 正例配对：计数器到 3 ⇒ 同一条规则真的能赢。
        // 这条同时证明求值器不坏 —— "本内容上恒假"是**触发器没到位**（§3.7），不是我们把条件读死了。
        let mut state = arena(actor.as_str());
        set_counter(&mut state, &actor, "queue_position", 3);
        let ruled = select_action(&state, &content, at, &actor, 2)
            .unwrap()
            .expect("规则命中（round 不影响规则分支）");
        assert_eq!(ruled.action_id, "a_very_official_line.everyone_moves");
        assert_eq!(
            ruled.reason,
            ChoiceReason::Rule {
                index: 0,
                priority: 10
            }
        );
    }

    // ---------------------------------------------------------------- B3

    #[test]
    fn b3_the_cycle_is_one_based_and_wraps() {
        let blob = core_image();
        let content = parse(&blob);
        let at = slot(&content, "city_easy_01", 0);
        let actor = cid(record_id(&content, at));
        let state = arena(actor.as_str());

        // `a_very_official_line` 的 Actions 实测是 3 条（`shuffle_forward` / `compress_the_queue`
        // / `shuffle_backward`，§3.6 的逐条输出）。`(round-1) % 3`，round 是 **1-based**：
        // `EnemyIntentRulesTests.cs:63-71` 钉住的就是 round 1 → 第 0 个这条经典错法。
        let wanted = [
            "a_very_official_line.shuffle_forward",   // round 1 → slot 0
            "a_very_official_line.compress_the_queue", // round 2 → slot 1
            "a_very_official_line.shuffle_backward",  // round 3 → slot 2
            "a_very_official_line.shuffle_forward",   // round 4 → 绕回 slot 0
            "a_very_official_line.compress_the_queue", // round 5 → slot 1
        ];
        for (index, want) in wanted.iter().enumerate() {
            let round = index as i32 + 1;
            let expected_slot = ((round - 1) % 3) as u16;
            let choice = select_action(&state, &content, at, &actor, round)
                .unwrap()
                .expect("循环分支永远有动作");
            assert_eq!(choice.action_id, *want, "round {round}");
            assert_eq!(
                choice.reason,
                ChoiceReason::Cycled {
                    round,
                    slot: expected_slot
                }
            );
        }
    }

    // ---------------------------------------------------------------- B4

    #[test]
    fn b4_an_enemy_with_no_actions_has_no_action() {
        let blob = core_image();
        let base = parse(&blob);
        let at = slot(&base, "city_easy_01", 0);
        let actor = cid(record_id(&base, at));
        let record = enemy_record(&base, at).unwrap().id();
        // `Actions` 是 `F_STRLIST`（两个槽：AUX 起址 + 个数）⇒ 个数槽 = 首槽 + 1。
        let count_slot = field_slot(&base, record, "Actions") + 1;
        let count_pos = term_slot_pos(&base, record, count_slot);

        // 对照：未打补丁时确实有动作。
        assert!(select_action(&arena(actor.as_str()), &base, at, &actor, 1)
            .unwrap()
            .is_some());

        // B4（`EnemyIntentRules.cs:166`）：`Actions.Count == 0` ⇒ `null`。
        // 本内容没有这种敌人（实测每敌人 1..=5 条动作），所以把个数槽改成 0 造一个。
        let patched_blob = patched(&[(count_pos, 0)]);
        let content = parse(&patched_blob);
        let state = arena(actor.as_str());
        assert_eq!(
            select_action(&state, &content, at, &actor, 1).unwrap(),
            None,
            "没有动作 ⇒ None；与 B0 的 None 是**不同原因**（这里名单里有人、只是没脚本）"
        );
    }

    // ---------------------------------------------------------------- 优先级

    #[test]
    fn priority_descending_wins_a_real_competition() {
        let blob = core_image();
        let base = parse(&blob);
        let plan = signpost(&base);
        let at = slot(&base, "city_normal_ordinance_04", 0);
        let actor = cid(record_id(&base, at));

        // 造一个**两条规则都匹配、优先级不同**的真竞争用例：
        // 把第 2 条规则的 `Equal 2` 改成 `Equal 1`（于是 `signposted_route == 1` 时两条都真），
        // 并把它的 Priority 从 20 降到 5。
        let patched_blob = patched(&[(plan.rule1_condition_value, 1), (plan.rule1_priority, 5)]);
        let content = parse(&patched_blob);
        let mut state = arena(actor.as_str());
        set_counter(&mut state, &actor, "signposted_route", 1);

        let choice = select_action(&state, &content, at, &actor, 1)
            .unwrap()
            .expect("两条规则都匹配");
        // 降序（`EnemyIntentRules.cs:160` 的 `OrderByDescending`）⇒ P20 的赢。
        assert_eq!(
            choice.action_id,
            "contradictory_signpost.dangerous_shortcut",
            "P20 应当打败 P5"
        );
        assert_eq!(
            choice.reason,
            ChoiceReason::Rule {
                index: 0,
                priority: 20
            }
        );
        // 反例说明：升序会选到 P5 那条（`long_administrative_route`），动作 id 完全不同 ⇒
        // 这个断言能真的抓住"降序改成升序"的变异。
        assert_ne!(
            choice.action_id,
            "contradictory_signpost.long_administrative_route"
        );
    }

    #[test]
    fn equal_priority_keeps_author_order() {
        let blob = core_image();
        let base = parse(&blob);
        let plan = signpost(&base);
        let at = slot(&base, "city_normal_ordinance_04", 0);
        let actor = cid(record_id(&base, at));

        // 只把 `Equal 2` 改成 `Equal 1` ⇒ 两条 P20 规则同时命中 ⇒ **平局**。
        // 参考的 `OrderByDescending` 是 LINQ-to-Objects 的**稳定**排序（规格书 §3.2 标为 ✘ 未实测，
        // 本内容上不可观察）⇒ 平局取作者列表里靠前的那条。这是偏离 D5 的钉子。
        let patched_blob = patched(&[(plan.rule1_condition_value, 1)]);
        let content = parse(&patched_blob);
        let mut state = arena(actor.as_str());
        set_counter(&mut state, &actor, "signposted_route", 1);

        let choice = select_action(&state, &content, at, &actor, 1)
            .unwrap()
            .expect("两条 P20 都匹配");
        assert_eq!(
            choice.action_id,
            "contradictory_signpost.dangerous_shortcut",
            "平局按作者顺序取第一条"
        );
        assert_eq!(
            choice.reason,
            ChoiceReason::Rule {
                index: 0,
                priority: 20
            }
        );
    }

    // ---------------------------------------------------------------- 轮次

    #[test]
    fn round_below_one_is_refused_only_on_the_cycle_path() {
        let blob = core_image();
        let content = parse(&blob);
        let at = slot(&content, "city_easy_01", 0);
        let actor = cid(record_id(&content, at));
        let state = arena(actor.as_str());

        // 偏离 D1：参考在这里是 `(round-1) % n` 的负数下标（C# 抛 `ArgumentOutOfRange`，
        // Rust 的 `-1 % 3 == -1` 同样负）⇒ 响亮拒绝。规格书 §8.3 第 4 条要求的就是这条。
        assert_eq!(
            select_action(&state, &content, at, &actor, 0).unwrap_err(),
            IntentError::InvalidRound(0)
        );
        assert_eq!(
            select_action(&state, &content, at, &actor, -3).unwrap_err(),
            IntentError::InvalidRound(-3)
        );

        // 成对反例：规则命中时参考**根本不碰** `round`（`:161-162` 在 `:165` 之前返回）⇒
        // 那就不该因为我们更严格而失败。
        let at2 = slot(&content, "city_normal_delay_07", 0);
        let actor2 = cid(record_id(&content, at2));
        let mut state2 = arena(actor2.as_str());
        set_counter(&mut state2, &actor2, "stolen_minute", 5);
        assert_eq!(
            select_action(&state2, &content, at2, &actor2, 0)
                .unwrap()
                .expect("规则命中与 round 无关")
                .action_id,
            "minute_moth.wingbeat_delay"
        );
    }

    // ---------------------------------------------------------------- 零 RNG

    #[test]
    fn zero_rng_the_selector_never_touches_random_step() {
        // §3.4：参考的选择器函数体（`EnemyIntentRules.cs:154-167`）与 10 个条件实现（`:22-144`）
        // 里**没有任何随机源** ⇒ 推进 0 次。`select_action` 拿的是 `&CombatState`，
        // 结构上就推进不了；这条测试钉住"以后别为了省事把它改成 `&mut`"。
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena("a_very_official_line");
        state.random_step = 7;

        let owner = cid("a_very_official_line");
        // 四个分支各走一遍（B0 / B1 / B2+B3 / Err）。
        let _ = select_action(&state, &content, slot(&content, "city_easy_01", 0), &owner, 1);
        let _ = select_action(&state, &content, slot(&content, "city_easy_01", 0), &cid("minute_moth"), 1);
        let _ = select_action(&state, &content, slot(&content, "city_normal_delay_07", 0), &owner, 2);
        let _ = select_action(&state, &content, slot(&content, "city_normal_ordinance_04", 0), &owner, 3);
        assert_eq!(state.random_step, 7, "选择动作一次随机都不许消耗");

        // 执行侧：§3.4 的结论是"本内容的 394 个敌方动作程序一次都用不到随机源"
        // ⇒ 执行一个真实动作也不该动 `random_step`。这是内容的性质，不是本层的性质。
        let root = enemy_action_program_root(&content, 0).unwrap();
        assert_eq!(root.kind().unwrap(), NodeKind::Sequence);
        let stats = execute_action(&mut state, &content, &owner, 0, Some(cid("hero"))).unwrap();
        assert!(stats.nodes > 0);
        assert_eq!(state.random_step, 7, "本内容的敌方动作不推 RNG");
    }

    // ---------------------------------------------------------------- 条件

    #[test]
    fn opponent_cards_played_reads_the_turn_counters() {
        // §128 gave the kernel per-turn card statistics, so this condition now **answers** instead of
        // being refused. (Before it was the one loud `UnsupportedCondition` in the reference image.)
        let blob = core_image();
        let content = parse(&blob);
        let at = slot(&content, "city_normal_ordinance_04", 0);
        let actor = cid(record_id(&content, at));

        // The rule is reachable only when the two counter rules above it do not match, so it is
        // exercised with both a small and a large count; the point is that neither panics nor
        // errors, and that the answer really depends on the counter.
        let mut seen = Vec::new();
        for played in [0i32, 50] {
            let mut state = arena(actor.as_str());
            state.cards_played_last_turn = played;
            state.cards_played_this_turn = played;
            let choice = select_action(&state, &content, at, &actor, 1)
                .expect("no longer a loud error")
                .expect("an action is always available");
            seen.push(choice.action_id.to_string());
        }
        assert_eq!(seen.len(), 2);
        // Whatever the rule says, the two answers must be **stable** (a deterministic kernel) --
        // this pins "the condition is evaluated, not skipped".
        assert!(!seen[0].is_empty() && !seen[1].is_empty());
    }

    #[test]
    fn an_unknown_comparison_operator_is_refused() {
        let blob = core_image();
        let base = parse(&blob);
        let plan = signpost(&base);
        let at = slot(&base, "city_normal_ordinance_04", 0);
        let actor = cid(record_id(&base, at));
        // 拿 `Counter` 槽里那个串号（= "signposted_route"），它当然不是六个算子之一。
        let not_an_operator = slot_value(
            &base,
            plan.rule1_condition,
            field_slot(&base, plan.rule1_condition, "Counter"),
        );
        assert_ne!(not_an_operator, 0);

        let patched_blob = patched(&[(plan.rule1_condition_op, not_an_operator)]);
        let content = parse(&patched_blob);
        let mut state = arena(actor.as_str());
        // 5 让第一条 P20（`Equal 1`）为假 ⇒ 走到被改坏的第二条 ⇒ 抛。
        set_counter(&mut state, &actor, "signposted_route", 5);
        assert_eq!(
            select_action(&state, &content, at, &actor, 1).unwrap_err(),
            IntentError::UnknownOperator,
            "参考在 `EnemyIntentRules.cs:34` 抛异常；内核同样不许静默当成不匹配"
        );
    }

    #[test]
    fn an_actor_missing_from_the_state_makes_conditions_false_not_an_error() {
        let blob = core_image();
        let content = parse(&blob);
        let at = slot(&content, "city_easy_01", 0);
        let actor = cid(record_id(&content, at));

        // `EnemyIntentRules.cs:89-90`：`!TryGetCombatant(self) ⇒ return false`（不是抛）。
        // 注意这与 B0 是**两件事**：B0 查的是内容名单（命中），这里查的是状态（缺席）。
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state.add_combatant(unit("hero", "player", 70)).unwrap();
        let choice = select_action(&state, &content, at, &actor, 1)
            .unwrap()
            .expect("条件假 ⇒ 落回循环");
        assert_eq!(choice.action_id, "a_very_official_line.shuffle_forward");
        assert_eq!(choice.reason, ChoiceReason::Cycled { round: 1, slot: 0 });
    }

    // ---------------------------------------------------------------- 词表

    #[test]
    fn condition_kinds_are_the_eleven_registered_wire_names() {
        // 名字来自 `Run\Serialization\RunJson.cs:141-151` 的注册表（规格书 §3.5 逐条读过）。
        let names = [
            "intent.healthPercent",
            "intent.round",
            "intent.selfHasStatus",
            "intent.opponentHasStatus",
            "intent.selfHasCounter",
            "intent.selfResource",
            "intent.opponentCardsPlayed",
            "intent.allOf",
            "intent.anyOf",
            "intent.not",
            // §187：本移植自己的条件（StS 的 A17/18/19 是每只怪 `getMove` 里的一段 `if`）。
            "intent.ascensionAtLeast",
        ];
        assert_eq!(ConditionKind::ALL.len(), names.len());
        for (kind, name) in ConditionKind::ALL.into_iter().zip(names) {
            assert_eq!(kind.wire_name(), name);
            assert_eq!(ConditionKind::from_wire_name(name), Some(kind));
        }
        assert_eq!(ConditionKind::from_wire_name("node.dealDamage"), None);
        assert_eq!(ConditionKind::from_wire_name("intent.nope"), None);

        // 偏离 D3：今天只有一种能求值，其余 9 种一律 `UnsupportedCondition`。
        // （`opponentCardsPlayed` 缺 `CardPlayTurnStats`；另外 8 种在 core 镜像里**连 opcode
        // 都没有**，字段名无从测量 —— 实现它们等于发明一个假的求值器。）
        let supported: Vec<ConditionKind> = ConditionKind::ALL
            .into_iter()
            .filter(|kind| kind.is_supported())
            .collect();
        // **11/11 全部实现**（`opponentCardsPlayed` 在 §128 补上，靠回合级出牌统计；
        // `ascensionAtLeast` 在 §187 补上，读 `CombatState::ascension()`）。
        assert_eq!(
            supported,
            vec![
                ConditionKind::HealthPercent,
                ConditionKind::Round,
                ConditionKind::SelfHasStatus,
                ConditionKind::OpponentHasStatus,
                ConditionKind::SelfHasCounter,
                ConditionKind::SelfResource,
                ConditionKind::OpponentCardsPlayed,
                ConditionKind::AllOf,
                ConditionKind::AnyOf,
                ConditionKind::Not,
                ConditionKind::AscensionAtLeast,
            ]
        );
    }

    /// §187: `intent.ascensionAtLeast` -- **both** sides of the threshold.
    ///
    /// The comparison is extracted into [`ascension_at_least`] because `condition_matches` needs a
    /// *content term* to run, and this content has no rule using the condition yet (every sourced
    /// A17/18/19 change is a **number**, i.e. `EACT.ProgramAsc`). The dispatch itself -- "the kind is
    /// registered and reachable" -- is pinned by
    /// `condition_kinds_are_the_eleven_registered_wire_names`.
    #[test]
    fn the_ascension_condition_compares_the_fight_level() {
        for (level, value, want) in [
            (0u8, 0, true),
            (0, 1, false),
            (2, 2, true),
            (2, 3, false),
            (3, 17, false),
            (18, 17, true),
            (19, 19, true),
            (20, 19, true),
        ] {
            assert_eq!(
                ascension_at_least(level, value),
                want,
                "ascension {level} >= {value} must be {want}"
            );
        }
    }

    /// The helper the condition uses must agree with the state it reads: `set_ascension` writes the
    /// field `ascension()` returns, and `0` is what a fresh state carries (the corpus depends on it).
    #[test]
    fn a_fresh_state_is_ascension_zero() {
        let state = CombatState::new(crate::state::CombatId::new("c1").unwrap(), 7);
        assert_eq!(state.ascension(), 0);
        assert!(ascension_at_least(state.ascension(), 0));
        assert!(!ascension_at_least(state.ascension(), 1));
    }

    /// `CompareOp::apply` is the shared arithmetic behind **nine** of the ten condition kinds, so it
    /// gets its own table (`port-plan.md` §124).
    #[test]
    fn every_comparison_operator_orders_its_operands_correctly() {
        for (op, left, right, want) in [
            (CompareOp::Equal, 3, 3, true),
            (CompareOp::Equal, 3, 4, false),
            (CompareOp::NotEqual, 3, 4, true),
            (CompareOp::NotEqual, 3, 3, false),
            (CompareOp::Less, 3, 4, true),
            (CompareOp::Less, 4, 4, false),
            (CompareOp::LessOrEqual, 4, 4, true),
            (CompareOp::LessOrEqual, 5, 4, false),
            (CompareOp::Greater, 5, 4, true),
            (CompareOp::Greater, 4, 4, false),
            (CompareOp::GreaterOrEqual, 4, 4, true),
            (CompareOp::GreaterOrEqual, 3, 4, false),
        ] {
            assert_eq!(op.apply(left, right), want, "{op:?} {left} vs {right}");
        }
    }

    #[test]
    fn compare_ops_match_the_reference_switch() {
        // `EnemyIntentRules.cs:26-35` 的 6 条臂，逐条对照。
        let names = [
            "Equal",
            "NotEqual",
            "Less",
            "LessOrEqual",
            "Greater",
            "GreaterOrEqual",
        ];
        assert_eq!(CompareOp::ALL.len(), names.len());
        for (op, name) in CompareOp::ALL.into_iter().zip(names) {
            assert_eq!(op.wire_name(), name);
            assert_eq!(CompareOp::from_wire_name(name), Some(op));
        }
        assert_eq!(CompareOp::from_wire_name("gt"), None);
        assert!(CompareOp::Equal.apply(3, 3));
        assert!(!CompareOp::NotEqual.apply(3, 3));
        assert!(CompareOp::Less.apply(2, 3));
        assert!(CompareOp::LessOrEqual.apply(3, 3));
        assert!(CompareOp::Greater.apply(4, 3));
        assert!(CompareOp::GreaterOrEqual.apply(3, 3));
        assert!(!CompareOp::GreaterOrEqual.apply(2, 3));
    }

    #[test]
    fn intent_kinds_match_the_reference_enum() {
        // `ActionIntent.cs:5-13` 的 6 个成员；本内容用到 5 个（`Unknown` 未用，§4.4）。
        let names = ["Unknown", "Attack", "Defend", "Buff", "Debuff", "Special"];
        assert_eq!(IntentKind::ALL.len(), names.len());
        for (kind, name) in IntentKind::ALL.into_iter().zip(names) {
            assert_eq!(kind.wire_name(), name);
            assert_eq!(IntentKind::from_wire_name(name), Some(kind));
        }
        assert_eq!(IntentKind::from_wire_name("attack"), None);

        // `EACT.Intent` 真的能读出来：`a_very_official_line.shuffle_forward` 实测是 `Attack`。
        let blob = core_image();
        let content = parse(&blob);
        let entry = content
            .lookup_in("a_very_official_line.shuffle_forward", EK_EACTION)
            .expect("动作 id 必须在 IDX 里");
        let kind = intent_kind_of(&content, content.enemy_action(u32::from(entry.index)).unwrap().row())
            .unwrap();
        assert_eq!(kind, Some(IntentKind::Attack));
    }

    // ---------------------------------------------------------------- 全镜像扫描

    #[test]
    fn every_cycle_action_in_the_image_resolves_to_its_own_row() {
        let blob = core_image();
        let content = parse(&blob);
        let mut enemies = 0u32;
        let mut resolved = 0u32;
        let mut refused = 0u32;
        for row in content.rows(Table::Encounter) {
            let mut ids = [0u16; MAX_ENEMIES];
            let count = encounter_enemy_ids(&content, row.index(), &mut ids).unwrap();
            for element in ids.iter().take(count) {
                let record = NodeRef::new(&content, *element);
                let id = record.str_field("Id").unwrap().expect("enemy record 必有 Id");
                let actor = cid(id);
                let state = arena(id);
                enemies += 1;
                // 1..=5 覆盖所有可能的下标（实测每个敌人最多 5 条动作）。
                for round in 1..=5 {
                    let at = EnemySlot {
                        encounter: row.index(),
                        index: u16::try_from(
                            ids.iter().take(count).position(|x| x == element).unwrap(),
                        )
                        .unwrap(),
                    };
                    match select_action(&state, &content, at, &actor, round) {
                        Ok(Some(choice)) => {
                            assert!(
                                choice.action_row < 394,
                                "EACT 只有 394 行，拿到 {}",
                                choice.action_row
                            );
                            // 关键不变量：`IDX` 解析出来的行，行内 `Id` 必须就是这个串
                            // （否则"选中的动作"和"要跑的程序"会静默错位）。
                            assert_eq!(
                                content.entity_id(Table::EnemyAction, choice.action_row),
                                Some(choice.action_id),
                                "{id} round {round}"
                            );
                            assert!(choice.intent_kind.is_some(), "本内容 394/394 有 Kind");
                            resolved += 1;
                        }
                        // §128 之后 10 种条件**全部**实现 ⇒ 本内容一条都不该被拒。
                        Err(error) => {
                            panic!("{id} round {round} 不该失败：{error:?}");
                        }
                        Ok(None) => panic!("{id} 在名单里且有动作，不该返回 None"),
                    }
                }
            }
        }
        // 实测分布：109 条遭遇共 149 条 enemy record（§5.2）。
        assert_eq!(enemies, 149);
        assert_eq!(
            refused, 0,
            "10 种条件全部实现之后，参考内容里没有一条规则会被拒（§128）"
        );
        assert_eq!(resolved, 149 * 5);
    }

    /// 内容侧新加的 `Content::encounter_enemies` 借用视图与这里的**私有读器**必须读到同一批记录。
    ///
    /// 两处各自实现了同一个二进制形状（`ENCT.Enemies` 格 → `_arr` → AUX 里的 term id）：
    /// `content.rs` 那份是给外部（`rd-wasm` / `rd-fightdump`）用的，本模块这份是给选择器用的。
    /// 任何一边漂开，两条路就会看到**不同的敌人名单** —— 那种偏差不会报错，只会让
    /// "UI 上显示的敌人"与"内核推进回合用的敌人"错位。
    #[test]
    fn the_content_view_and_the_private_reader_agree_on_every_record() {
        let blob = core_image();
        let content = parse(&blob);
        let mut seen = 0usize;
        for row in content.rows(Table::Encounter) {
            let index = row.index();
            let view = content
                .encounter_enemies(index)
                .expect("视图必须能读每条遭遇");
            let mut ids = [0u16; MAX_ENEMIES];
            let count = encounter_enemy_ids(&content, index, &mut ids).unwrap();
            assert_eq!(count, view.len(), "ENCT[{index}] 的敌人数");
            for (slot, element) in ids.iter().take(count).enumerate() {
                let private = enemy_record(
                    &content,
                    EnemySlot {
                        encounter: index,
                        index: u16::try_from(slot).unwrap(),
                    },
                )
                .unwrap();
                assert_eq!(private.id(), *element, "ENCT[{index}][{slot}] 的 term");
                let spec = view.get(slot).expect("视图必须能读这一槽");
                assert_eq!(spec.term(), *element, "ENCT[{index}][{slot}] 的 term");
                // `Id` 是两边都要解的那一格；`MaxHealth` 与 `Actions` 的条数是动作选择的输入。
                assert_eq!(spec.id().unwrap(), private.str_field("Id").unwrap().unwrap());
                let mut actions = [0u16; MAX_ACTIONS];
                let private_actions = private.str_list_field("Actions", &mut actions).unwrap();
                assert_eq!(spec.actions().unwrap().len(), private_actions);
                assert!(
                    matches!(spec.max_health().unwrap(), Some(hp) if hp >= 1),
                    "MaxHealth 必须是正数（实测 11..=132）"
                );
                seen += 1;
            }
        }
        assert_eq!(seen, 149, "109 条遭遇共 149 条 enemy record");
    }

    #[test]
    fn every_enemy_record_id_fits_a_combatant_id() {
        // 宿主必须能用 `CombatantId`（`Ident<40>`）装敌人 id —— `CombatState` 按它建表。
        // 实测最长 24 B ⇒ 够；这条测试是"别把 `ID_CAP` 调小"的闸门。
        let blob = core_image();
        let content = parse(&blob);
        let mut longest = "";
        for row in content.rows(Table::Encounter) {
            let mut ids = [0u16; MAX_ENEMIES];
            let count = encounter_enemy_ids(&content, row.index(), &mut ids).unwrap();
            for element in ids.iter().take(count) {
                let id = NodeRef::new(&content, *element)
                    .str_field("Id")
                    .unwrap()
                    .unwrap();
                assert!(
                    CombatantId::new(id).is_ok(),
                    "{id}（{} B）超过 CombatantId::CAP={}",
                    id.len(),
                    CombatantId::CAP
                );
                if id.len() > longest.len() {
                    longest = id;
                }
            }
        }
        assert_eq!(longest, "counter_of_certification");
        assert_eq!(longest.len(), 24);
    }

    #[test]
    fn every_enemy_action_program_has_the_expected_envelope() {
        // 规格书 §4.3 的信封结论：394/394 都是 `_obj(Id="(unnamed)",
        // MaxNodeDepth=64, MaxProgramSteps=1024, Root)`，根节点只有 4 种。
        let blob = core_image();
        let content = parse(&blob);
        let mut rows = 0u32;
        for row in content.rows(Table::EnemyAction) {
            let index = row.index();
            let root = enemy_action_program_root(&content, index).unwrap();
            assert!(
                matches!(
                    root.kind().unwrap(),
                    NodeKind::Sequence
                        | NodeKind::DealDamage
                        | NodeKind::ApplyStatus
                        | NodeKind::GainBlock
                ),
                "EACT[{index}] 的根节点是 {:?}",
                root.kind().unwrap()
            );
            let envelope = envelope(&content, index).unwrap();
            assert_eq!(envelope.str_field("Id").unwrap(), Some("(unnamed)"));
            assert_eq!(envelope.int_field("MaxNodeDepth").unwrap(), Some(64));
            assert_eq!(envelope.int_field("MaxProgramSteps").unwrap(), Some(1024));
            rows += 1;
        }
        assert_eq!(rows, 394);
    }

    #[test]
    fn all_394_enemy_action_programs_execute() {
        // §4.3 的结论是"执行侧今天就是齐的"（5 种节点 + 3 种选择器 + 6 种表达式全在 `exec.rs`）。
        // `exec.rs` 有一条 62 张卡的同型测试（`every_card_program_in_the_image_runs_…`），
        // **没有任何一条覆盖这 394 个敌方动作程序** —— 这条补上那个缺口：每个都真跑一遍。
        // 每次用**全新**的战场，避免 `applyStatus` 累积到 `MAX_STATUSES_PER_COMBATANT`（24）。
        let blob = core_image();
        let content = parse(&blob);
        let actor = cid("a_very_official_line");
        let mut ran = 0u32;
        let mut failures: Vec<(u32, IntentError)> = Vec::new();
        for row in 0..394u32 {
            let mut state = arena(actor.as_str());
            match execute_action(&mut state, &content, &actor, row, Some(cid("hero"))) {
                Ok(stats) => {
                    assert!(stats.nodes > 0, "EACT[{row}] 一个节点都没跑");
                    ran += 1;
                }
                Err(error) => failures.push((row, error)),
            }
        }
        assert_eq!(ran, 394);
        assert_eq!(failures, Vec::new(), "有敌方动作程序被拒");
    }

    #[test]
    fn a_dead_actor_executes_nothing() {
        // §6.1 `:20-21`：`!TryGetCombatant || !actor.IsAlive ⇒ return`（静默 no-op，不是抛）。
        let blob = core_image();
        let content = parse(&blob);
        let actor = cid("a_very_official_line");
        let mut state = arena(actor.as_str());
        state.combatant_mut(&actor).unwrap().lifecycle_state = CombatantLifecycleState::Dead;
        let hero_health = state.combatant(&cid("hero")).unwrap().health_current;
        // 成对（2026-10-19 加）：死掉的 actor **连号都不发** —— 参考的
        // `ScenarioRunner.cs:178-189` 是在入队**之前**挡掉 `!enemy.IsAlive` 的。
        let chain_before = state.next_effect_chain_number;
        let exec_before = state.next_program_execution_id;

        let stats = execute_action(&mut state, &content, &actor, 0, Some(cid("hero"))).unwrap();
        // `nodes == 0` 就是"什么都没做"的可观察信号（偏离 D4）。
        assert_eq!(stats.nodes, 0);
        assert_eq!(stats.effects, 0);
        assert_eq!(
            state.combatant(&cid("hero")).unwrap().health_current,
            hero_health,
            "死掉的敌人不许伤到任何人"
        );
        assert_eq!(
            state.next_effect_chain_number, chain_before,
            "没入队的请求不发链号（`ScenarioRunner.cs:178-189` 在入队之前就 return）"
        );
        assert_eq!(
            state.next_program_execution_id, exec_before,
            "没跑节目就不发执行号"
        );
    }

    /// #2 的回归闸门：一次**真的执行了**的敌方动作让 `exec_num +1`、`chain_num +2`。
    ///
    /// 修正之前这里只 +1/+1（出牌侧分了执行号、敌动作侧漏了），整局对拍里表现为
    /// `enemy_hits` 的 `exec_num` 少 1。三个数的出处（都是实测，见 [`execute_action`] 的文档）：
    ///
    /// * `exec +1`：`EffectProgramExecution.cs:27` 每次 `Execute` 一个号；
    /// * `chain +1`：`ScenarioRunner.cs:191` 的顶层 `EnqueueEffect`；
    /// * `chain +1`：节目跑完 `CloseAction` → `EnqueueEvent(ActionResolved)`
    ///   （`EnemyActionEffects.cs:121`），从续延里跑 ⇒ 又一次顶层入队。
    #[test]
    fn an_enemy_action_allocates_one_execution_id_and_two_effect_chains() {
        let blob = core_image();
        let content = parse(&blob);
        let actor = cid("a_very_official_line");
        let mut state = arena(actor.as_str());
        let chain_before = state.next_effect_chain_number;
        let exec_before = state.next_program_execution_id;

        let stats = execute_action(&mut state, &content, &actor, 0, Some(cid("hero"))).unwrap();
        assert!(stats.nodes > 0, "这条动作真的跑了节点");
        assert!(stats.effects > 0, "而且真的对目标发起了效果（不是空跑）");
        assert_eq!(
            state.next_program_execution_id,
            exec_before + 1,
            "`EffectProgramExecution.cs:27`：跑一次节目发一个号（出牌与敌动作同一个执行器）"
        );
        assert_eq!(
            state.next_effect_chain_number,
            chain_before + 2,
            "请求入队 +1、动作收尾 +1（见本测试的文档）"
        );
    }

    #[test]
    fn a_slot_out_of_range_or_an_unknown_encounter_is_an_error() {
        let blob = core_image();
        let content = parse(&blob);
        let at = slot(&content, "city_easy_01", 0);
        let actor = cid(record_id(&content, at));
        let state = arena(actor.as_str());

        // 与 `None`（B0/B4）不同：这些是**宿主/内容出错**，不是"这回合没有动作"。
        let beyond = EnemySlot {
            encounter: at.encounter,
            index: 1, // 这条遭遇实测只有 1 个敌人
        };
        assert_eq!(
            select_action(&state, &content, beyond, &actor, 1).unwrap_err(),
            IntentError::Slot {
                encounter: beyond.encounter,
                index: 1
            }
        );
        let bogus = EnemySlot {
            encounter: 999,
            index: 0,
        };
        assert_eq!(
            select_action(&state, &content, bogus, &actor, 1).unwrap_err(),
            IntentError::Missing("ENCT row")
        );
        // 动作行号越界同样是错误（不是"没有动作"）。
        assert_eq!(
            enemy_action_program_root(&content, 394).unwrap_err(),
            IntentError::Missing("EACT row")
        );
    }
}
