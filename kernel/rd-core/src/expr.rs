//! 表达式求值 —— 效果程序里的 `Amount` / `Stacks` / `Condition` 都是表达式树。
//!
//! ## 边界
//!
//! 本模块**只求值**：给定一棵表达式子树 + 一个上下文，算出 `i32` 或 `bool`。
//! 它不改状态、不触发效果、不消费 RNG（`sel.random` 那种有副作用的表达式不在 v1 范围）。
//!
//! ## 范围：按真实镜像的数据定
//!
//! 下面两列是**两种不同的计数**，混用会得出假的覆盖率：
//!
//! * 「源」= 内容源 JSON 里的**出现次数**（同一个 term 复用几次算几次）。源文件是
//!   `ref/RogueDeck-Core/src/RogueDeck.Sandbox.Run/SampleContent/bureaucrats.roguedeck.json`；
//!   本行原来写的是 `tools/_core_dump.json`，那是它的一次性转储，**仓库里没有这个文件**
//!   （2026-10-19 实测 `Test-Path` = False），所以出处改指源文件本身；
//! * 「镜像」= `tools/contentc/out/content.core.rdcf` 里 **term DAG 的去重条数**
//!   （内容寻址：`const{Value:6}` 全镜像只有一条 term）。
//!
//! | kind | 源 | 镜像 | v1 |
//! |---|---|---|---|
//! | `const` | 3695 | 25 | ✅ |
//! | `compare` | 739 | 41 | ✅ |
//! | `combatantCounter` | 550 | 16 | ✅ |
//! | `combatantStatusStacks` | 495 | 13 | ✅ |
//! | `and` | 177 | 15 | ✅ |
//! | `multiply` | 20 | 12 | ✅ |
//! | `subtract` | 15 | 3 | ✅ |
//! | `add` | 12 | 8 | ✅ |
//! | `min` | 12 | 8 | ✅ |
//! | `max` | **0** | **0** | ✅（实现了，但镜像里一条都没有） |
//! | `divide` | 10（5+5 两种拼法） | 4（2+2） | ✅ 见下 |
//! | `currentHealth` | 7 | 1 | ⚠️ **要 `Selector` 字段**，镜像里那 1 条没有 ⇒ 见下面第 4 条 |
//! | `maxHealth` | 5 | 1 | ⚠️ 同上（同一个 opcode 形状问题） |
//! | `or` | 4 | 4 | ✅ |
//! | `combatantCurrentResource` | 1 | 1 | ✅ |
//!
//! 这张表只统计**镜像里出现过的** kind。`missingHealth` 不在表里：它**在镜像里连 opcode 都没有**
//! （源 JSON 0 次，opcode 表里也没有这个名字），而且它等于 `subtract(maxHealth, currentHealth)`，
//! 所以它仍然报 `UnsupportedKind` —— 那不是缺口，是"这条内容还没写过"。
//!
//! ⚠️ **`max` 的两处数字都是 0**。本模块头原来写的「`max` 12」是把 `add`/`min` 的 12 抄错了一行；
//! 实测源 JSON 里 `max` **一次都没出现**（`min` 12、`add` 12、`max` 0）。
//!
//! v1 **不支持**（报 `UnsupportedKind`，不许静默给 0）：
//! * `cardsPlayedThisTurn` / `cardsPlayedLastTurn` / `cardsPlayedThisTurnWithTag` /
//!   `firstCardPlayedHasTag` —— 需要**每回合出牌统计**，内核没有（`CardPlayTurnStats` 整块未移植）；
//! * `cardInstance.iterated` / `card.upgradeLevel` —— 需要卡实例表达式上下文；
//! * `eventAmount` / `event.bool` / `intent.*` —— 需要**触发事件上下文**，v1 的效果执行还没有事件队列；
//! * `fx.*` / `reward.*` / `meta.*` / `tpl.*` —— run 层；
//! * `abs` / `negate` / `remainder` / `clamp` —— 参考实现里有（`EffectProgramExpressions.cs:219/532/587/622`），
//!   但**镜像里一条都没有**，字段名（`Operand` / `Inner` / `Value,Min,Max`）无法用真实数据核实，
//!   编一个字段名就是编一个语义 —— 所以留 `UnsupportedKind`。
//!
//! **这张表里没有 `currentHealth` / `maxHealth`**：它们实现了（字段名 `Selector` 由我们定，
//! 见下面第 4 条）。`missingHealth` 仍然 `UnsupportedKind`（它连 opcode 都没有，而且等价于
//! `subtract(maxHealth, currentHealth)`）。
//!
//! ## 四条**从真实产物里读出来**的坑（每条都带行号与实测出处）
//!
//! 1. **`divide` 有两种拼法，而且它们是两个不同的类。**
//!    * `{Dividend, Divisor, ZeroPolicy}` = 战斗层 `DivideExpression`
//!      （`EffectProgramExpressions.cs:551-585`）：`ZeroPolicy` 默认 `ReturnZero`（`:561`），
//!      除零返 0；`Fault` 抛 `InvalidOperationException`（`:575-576`）；商用 `(long)` 中间量再饱和
//!      （`:579-580`），所以 `int.MinValue / -1` 不炸。镜像里 2 条（term 650 / 1158）。
//!    * `{Left, Right}` = **run 层** `DivideExpression`（`RunExpressions.cs:278-296`）：
//!      **没有** `ZeroPolicy`，除零直接抛（`:292-294`），商是 `int` 除法 ——
//!      `int.MinValue / -1` 在 C# 里抛 `OverflowException`。镜像里 2 条（term 1733 / 1860，
//!      都在 run 层的 `fx.computedHeal` 里）。
//!
//!    ⇒ 内核：两种拼法**都支持**、正常值同上；除零时战斗层按 `ZeroPolicy`、run 层给
//!    `ExprError::DivideByZero`；run 层 `MIN / -1` 给 `ExprError::Overflow`（战斗层按 `(long)` 饱和）。
//!    字段表是**并集**（`divide` 的 opcode 有 5 个字段：`Dividend/Divisor/Left/Right/ZeroPolicy`），
//!    缺的键是 `ABSENT16`，所以判据是「`Dividend` 有没有值」而不是「字段在不在」。
//!
//! 2. **`compare.Op` 的串跨两个枚举。** 战斗层 `ComparisonOperator`
//!    （`EffectProgramExpressions.cs:360-368`：`Equal/NotEqual/Less/LessOrEqual/Greater/GreaterOrEqual`）
//!    与 run 层 `RunComparisonOperator`（`RunExpressions.cs:482-490`：
//!    `Equal/NotEqual/LessThan/LessOrEqual/GreaterThan/GreaterOrEqual`）**拼写不同**。
//!    镜像里实测出现 5 种：`Equal` / `Less` / `LessThan` / `Greater` / `GreaterOrEqual`
//!    （`LessThan` 那条在 run 层 `sel.matching.Predicate`，term 1737）。两边语义逐条相同
//!    （`LessThan` 就是 `<`，`GreaterThan` 就是 `>`），所以内核 8 个串全认。
//!
//! 3. **单目标读：零个目标给 0，多于一个目标在参考里是**错误**。**
//!    `CombatantStatusStacksExpression.Evaluate` 先 `if (targets.Count == 0) return 0;`（`:796`），
//!    再 `ScalarTargetExpression.RequireSingle`（`:28-36`）—— 后者对 `Count > 1` **抛**
//!    `InvalidOperationException`，注释明说「不要静默用第一个」。而且构造期就先拦一次
//!    （`:16-26` `RequireSingleSelector` 要求 `Cardinality.IsAtMostOneTarget()`）。
//!    ⇒ [`single_target`] 先查静态基数（对照构造期那道闸），再查解出的个数（对照求值期那道闸）；
//!    两道都用 [`ExprError::SelectorNotSingle`]。
//!
//! 4. **`currentHealth` / `maxHealth`：实现了；字段名 `Selector` 是**我们定的**，不是从镜像里读出来的。**
//!
//!    * **镜像的事实没变**：这两个 opcode 的字段表仍然 **`nfields = 0`**（op 28 / op 48；
//!      2026-10-19 直接读 `OPD` 实测 `field_off=100/nfields=0` 与 `field_off=240/nfields=0`），
//!      term 1527 / 1728 的 body 都是空 `{}`。
//!      ⚠️ **op 28 / op 48 只是这份镜像里的编号**：opcode 号由编译器按 kind 名字排序派生
//!      （`compile.py` 的 `LayoutDeriver`），换一份内容就会变（实测：给 sts 包加一条带
//!      `Selector` 的 `currentHealth` 之后它是 **op 19**）。⇒ 内核里**任何地方都不许把这两个
//!      数字写死**，认的一直是 `OPD[op].name` 这个串。
//!      参考实现的这两个类**必须**带选择器：
//!      `CombatantCurrentHealthExpression`（类声明 `EffectProgramExpressions.cs:656`，
//!      构造函数 `:661-665` 里 `RequireSingleSelector`）、`CombatantMaxHealthExpression`
//!      （类声明 `:676`，构造函数 `:681-685`）。⇒ 线上这个字段是**丢了**，不是「可选」。
//!    * **丢在哪一层已经查清**：这两个 term **只**从 ROOT 的 `Events`（term 1902，run 层事件表）
//!      可达；1527 的祖先链是 `subtract.Left ← min.Right ← fx.computedDamage.Amount ←
//!      situations.{act_1_shop, lost_and_found_desk, misfiling_cabinet, witness_queue,
//!      certified_copy_drawer, clerk_who_almost_helps, sealed_back_door}`，1728 的是
//!      `multiply.Left ← add.Left ← divide.Left ← fx.computedHeal.Amount ←
//!      situations.{clerks_tea_break, rest:act_1_d09_n00…n03}`（**验证过**：2026-10-19 遍历全部
//!      2143 条 term 的 `F_TERM`/`F_TERMLIST` 槽建父指针）。run 层有自己的一对**无选择器**实现
//!      （`RunExpressions.cs:85-93`，读的是 `context.Run.Health`）⇒ **`{}` 是 run 层那对类的
//!      合法形状**，不是"战斗层这个类丢了字段"的产物。所以把 `{}` 解读成"没有选择器的战斗层读"
//!      本来就是错的 —— 我们的 `Selector` 是**另一条**（战斗层的）编码，两者不冲突。
//!    * **字段名为什么是 `Selector`**：同一份镜像里**已经有 11 个 opcode** 用 `Selector`
//!      （op 20/21/22/23/24/25/32/38/43/44/45，全部 `Selector: F_TERM`），其中三个正是本模块
//!      已经在读的单目标标量读：`combatantStatusStacks`（op 25）、`combatantCounter`（op 23）、
//!      `combatantCurrentResource`（op 24）。[`read_single_target`] 读的就是这个键
//!      （`child(node, "Selector")`，本文件）。⇒ 这不是新发明的名字，是**镜像自己**给同一个
//!      概念用的名字。定义权归属见 `docs/spec/sts-act1-plan.md` §9-4
//!      （"不存在于镜像 ⇒ 定义权在我们"）。
//!      **编译器不用改**（实测 2026-10-19）：给 `sts` 包的一份**临时拷贝**加一条
//!      `{"kind":"currentHealth","value":{"Selector":{…}}}`，`compile.py` **零改动**就派生出
//!      `currentHealth: nfields=1, Selector:F_TERM`，`reader.py` 解回来正是这个形状
//!      （`packages/**` 一个字节都没动；命令见本轮报告的"内容侧 smoke"）。
//!    * **对 `roguedeck` 这份内容的后果**：CARD/STATUS/EACT/ENCT/REL 五张表
//!      （62/23/394/109/49 行）**一行都到不了** term 1527 / 1728（**自己扫的**，2026-10-19：
//!      从全部 5 张表的每个 `F_TERM`/`F_TERMLIST` 槽出发做可达集，1527/1728 都不在里面）。
//!      所以在这份内容里，这两个 term 依然**响亮失败**：
//!      `ExprError::Ir(IrError::Missing("Selector"))` —— 键不在字段表里，与"键在、值是
//!      `ABSENT16`"在 [`NodeRef::field`] 里是同一个答案（两者都表示"这个节点没有选择器"）。
//!      **不新增变体**：这与 `combatantStatusStacks` 缺 `Selector` 走的是同一条路、同一种错。
//!      给 0 或退回英雄都是错的：前者让 `maxHealth*10` 安静算成 0，后者算成"英雄血量的 10 倍"。
//!    * **什么会让旧结论重新成立**：若将来某份内容里出现"op 28 的 `nfields` 还是 0，而某个
//!      CARD / STATUS / EACT / ENCT / REL 行真的引用了它"，就说明我们猜错了名字（或参考里还有
//!      第三种形状）—— 那时**不许**改成"取第一个"或"取英雄"，要先问出那份内容把选择器放在了哪里。
//!    * 另外：`compounded_penalty`（CARD[20]）**不需要**它们 —— 它的 `Amount` 是
//!      `multiply{combatantStatusStacks(eventTarget, paperwork), 4}`，纯战斗层。

use crate::ir::{IrError, NodeRef};
use crate::sel::{CompiledSelector, SelError};
use crate::state::{CardInstanceId, CombatState, Combatant, CombatantId, MAX_COMBATANTS};
use crate::targets::{self, SelectionContext};

/// 求值错误。**全部是"这棵树我读不懂/不支持"，不是"游戏规则拒绝"**。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExprError {
    /// 底层 IR 读取失败。
    Ir(IrError),
    /// 选择器编译/解析失败。
    Sel(SelError),
    /// 这一种表达式不在 v1 范围（见模块头）。
    UnsupportedKind,
    /// 这棵子树根本不是表达式（例如把 `node.dealDamage` 当表达式求值）。
    NotAnExpression,
    /// 值类别错配：int / bool / 卡实例三种值域，问的和给的不是同一个。
    ///
    /// 三种错配都归这里（不是只区分 int↔bool）：三者的处置完全一样
    /// —— 内容配错了，整条程序作废，**绝不隐式转换**。
    WrongValueKind,
    /// 除法除零且 `ZeroPolicy` 不是"返回 0"。
    DivideByZero,
    /// 单目标读（`combatantStatusStacks` 之类）的选择器**不是**至多一个目标。
    SelectorNotSingle,
    /// 需要目标，但上下文里**没有**目标。
    ///
    /// 两条来源，两者的参考行为都是"整条程序作废"而不是给个默认值：
    /// 1. 单目标读（`combatantStatusStacks` 之类）在**单目标选择器解析出空集**时 ——
    ///    但参考在那种情况下给 **0**（`EffectProgramExpressions.cs:796`），所以那些读法
    ///    **不返回**这个变体，它们返回 0。
    /// 2. [`eval_card`] 在上下文里**没有绑定迭代卡**时（`cardInstance.iterated` 不在
    ///    任何 `ForEachCardInZone` 里被求值）。参考是空引用解引用 ⇒ 整条程序作废。
    NoTarget,
    /// 算术溢出（参考用 `long` 中间量再饱和；这里按饱和实现，此变体留给真正无法表示的情形）。
    ///
    /// 唯一可达的路径：**run 层拼法**的 `divide`（`{Left,Right}`）是 `int` 除法，
    /// `int.MinValue / -1` 在 C# 里抛 `OverflowException`（`RunExpressions.cs:294`）——
    /// 内核如实报 `Overflow`，而战斗层拼法走 `(long)` 饱和成 `i32::MAX`。
    Overflow,
}

impl From<IrError> for ExprError {
    fn from(e: IrError) -> Self {
        ExprError::Ir(e)
    }
}
impl From<SelError> for ExprError {
    fn from(e: SelError) -> Self {
        ExprError::Sel(e)
    }
}

/// 求值上下文。**与状态同寿命，但与被求值的 IR 无关**（两个生命周期是独立的）。
#[derive(Debug, Clone, Copy)]
pub struct ExprContext<'a> {
    pub state: &'a CombatState,
    /// 事件的来源单位（出牌时 = 出牌者）。
    pub source: Option<CombatantId>,
    /// 事件的目标（攻击牌的目标）。
    pub event_target: Option<CombatantId>,
    /// `ForEach` 的当前迭代目标。
    pub iteration_target: Option<CombatantId>,
    /// `ForEachCardInZone` 的当前迭代卡实例。
    ///
    /// 和 `iteration_target` 是**两个独立的槽**：参考的 `ForEachTarget` 绑战斗员、
    /// `ForEachCardInZone` 绑卡实例，两者可以嵌套，所以不能共用一个槽。
    /// 唯一读它的是 `cardInstance.iterated`（见 [`eval_card`]）。
    pub iteration_card: Option<CardInstanceId>,
}

impl ExprContext<'_> {
    /// 转成选择器解析用的上下文（三个目标槽**逐字**搬过去）。
    fn selection(&self) -> SelectionContext<'_> {
        SelectionContext {
            state: self.state,
            source: self.source,
            event_target: self.event_target,
            iteration_target: self.iteration_target,
        }
    }
}

// =============================================================================================
// 算术：**饱和**，绝不让一次求值 panic
// =============================================================================================

/// `long` → `int` 饱和（逐字对应 `EffectProgramExpressions.cs:211-217` 的
/// `ArithmeticSaturation.Saturate`）。
///
/// 参考实现把每个二元算术都写成 `Saturate((long)l OP (long)r)`，理由写在 `:208-210`：
/// 病态输入（例如读出 `int.MaxValue` 的池乘一个大操作数）**钳到 int 范围，而不是让效果程序抛**。
const fn saturate(value: i64) -> i32 {
    if value > i32::MAX as i64 {
        i32::MAX
    } else if value < i32::MIN as i64 {
        i32::MIN
    } else {
        value as i32
    }
}

/// 除数为 0 时怎么办（`DivideByZeroPolicy`，`EffectProgramExpressions.cs:549`）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ZeroPolicy {
    /// 接口默认（`:561`）：返回 0。
    ReturnZero,
    /// 抛（`:575-576`）。
    Fault,
}

/// 战斗层 `divide`（`EffectProgramExpressions.cs:570-581`）。
fn combat_divide(dividend: i32, divisor: i32, policy: ZeroPolicy) -> Result<i32, ExprError> {
    if divisor == 0 {
        return match policy {
            ZeroPolicy::ReturnZero => Ok(0),
            ZeroPolicy::Fault => Err(ExprError::DivideByZero),
        };
    }
    // `(long)` 中间量：`(long)i32::MIN / -1` = 2_147_483_648，在 i64 里合法，
    // 再饱和回 int（`:579-580`）。i64 除法在这里**不可能**溢出（被除数在 i32 范围）。
    Ok(saturate(i64::from(dividend) / i64::from(divisor)))
}

/// run 层 `divide`（`RunExpressions.cs:289-295`）：没有 `ZeroPolicy`，除零直接抛。
fn run_divide(dividend: i32, divisor: i32) -> Result<i32, ExprError> {
    if divisor == 0 {
        return Err(ExprError::DivideByZero);
    }
    // C# 的 `int / int` 在 `int.MinValue / -1` 上抛 `OverflowException` —— 那正是这个分支。
    if dividend == i32::MIN && divisor == -1 {
        return Err(ExprError::Overflow);
    }
    Ok(dividend / divisor)
}

/// 读 `ZeroPolicy`。**缺席 = 默认 `ReturnZero`**（`:561` 的接口默认值）；
/// 不认识的串**不许**悄悄当 `ReturnZero`（冻结的 `ExprError` 没有"坏枚举值"这个变体，
/// 所以落进 `UnsupportedKind` 这个响亮的口袋）。
fn zero_policy(node: NodeRef<'_>) -> Result<ZeroPolicy, ExprError> {
    match node.str_field("ZeroPolicy")? {
        None | Some("ReturnZero") => Ok(ZeroPolicy::ReturnZero),
        Some("Fault") => Ok(ZeroPolicy::Fault),
        Some(_) => Err(ExprError::UnsupportedKind),
    }
}

// =============================================================================================
// kind 分类：int / bool / 根本不是表达式 / 不认识的表达式
// =============================================================================================

/// 一个 kind 属于哪一类。
///
/// 分五类是因为**四种失败必须能区分**（见 `expr.rs` 的测试
/// `the_error_variants_are_all_distinguishable`）：
/// 语句节点当表达式用 = `NotAnExpression`；值类别不对 = `WrongValueKind`；
/// 同类但 v1 没实现 = `UnsupportedKind`。把 `node.dealDamage` 报成 `UnsupportedKind`
/// 会让人以为"v1 以后会支持它当表达式"。
///
/// `Card` 是 2026-10-17 加的第 5 类：`cardInstance.iterated` **不是 int**
/// （参考里是 `ICombatExpression<_, CardInstance>`），把它塞进 `INT_KINDS` 会让
/// `eval_int` 先过值类别闸、再在实现里掉进 `UnsupportedKind` —— 那是在用"没实现"
/// 掩盖"问错了问题"。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Class {
    /// 求值结果是 `i32`。
    Int,
    /// 求值结果是 `bool`。
    Bool,
    /// 求值结果是**卡实例**（`CardInstanceId`）。
    Card,
    /// 语句节点（`node.*`），不是表达式。
    NotAnExpression,
    /// 认不出值类别的 kind —— 当"不支持的表达式"，绝不猜一个值。
    Unknown,
}

/// 求值为 `i32` 的 kind（参考实现里 `ICombatExpression<_, int>` 的那些）。
///
/// 表里**有**但没实现的（`abs` / `eventAmount` / `card.upgradeLevel` 等）走 `UnsupportedKind` ——
/// 表的意义是"它的值类别是 int"，让 `eval_bool` 能给出 `WrongValueKind` 而不是
/// `UnsupportedKind`（问错了问题 ≠ 还没实现）。
const INT_KINDS: &[&str] = &[
    "const",
    "add",
    "subtract",
    "multiply",
    "divide",
    "min",
    "max",
    "abs",
    "negate",
    "remainder",
    "clamp",
    "currentHealth",
    "maxHealth",
    "missingHealth",
    "combatantStatusStacks",
    "combatantStatusStacksFromSource",
    "combatantStacksByPolarity",
    "combatantCounter",
    "combatantCurrentResource",
    "combatantCoord",
    "gridDistance",
    "roundNumber",
    "turnNumber",
    "iterationIndex",
    "iterationTargetStatusStacks",
    "eventAmount",
    "cardsPlayedThisTurn",
    "cardsPlayedLastTurn",
    "cardsPlayedThisTurnWithTag",
    "card.upgradeLevel",
];

/// 求值为**卡实例**的 kind（参考里 `ICombatExpression<_, CardInstance>` 的那些）。
///
/// 镜像里只出现过 `cardInstance.iterated`（0 字段，`trecon:236` 实测 t152 这一条），
/// 它读的是 `ForEachCardInZone` 绑定的当前迭代卡 —— 见 [`eval_card`] 与
/// [`ExprContext::iteration_card`]。
const CARD_KINDS: &[&str] = &["cardInstance.iterated"];

/// 求值为 `bool` 的 kind（`ICombatExpression<_, bool>` 的那些）。
const BOOL_KINDS: &[&str] = &[
    "compare",
    "and",
    "or",
    "not",
    "event.bool",
    "firstCardPlayedHasTag",
    "iterationTargetHasStatus",
    "intent.selfHasCounter",
    "intent.opponentCardsPlayed",
];

fn classify(kind: &str) -> Class {
    if INT_KINDS.contains(&kind) {
        return Class::Int;
    }
    if BOOL_KINDS.contains(&kind) {
        return Class::Bool;
    }
    if CARD_KINDS.contains(&kind) {
        return Class::Card;
    }
    // 只有 `node.*` 能确定"不是表达式"。`fx.*`/`reward.*`/`meta.*`/`tpl.*`/`sel.*` 是
    // run 层语句或选择器 —— 当表达式用是本内核不支持，报 `UnsupportedKind`
    // （模块头那条范围表就是这么承诺的）。
    if kind.starts_with("node.") {
        return Class::NotAnExpression;
    }
    Class::Unknown
}

/// 取一个必需的子节点字段。
///
/// `IrError::Missing` 只收 `&'static str`，所以键名一律传字面量（各调用点都是字面量）。
fn child<'c>(node: NodeRef<'c>, key: &'static str) -> Result<NodeRef<'c>, ExprError> {
    node.node_field(key)?.ok_or(ExprError::Ir(IrError::Missing(key)))
}

// =============================================================================================
// 求值
// =============================================================================================

/// 求一个整数表达式。
///
/// `node` 的镜像寿命与 `ctx` 的状态寿命是**独立的两个 `'a`** —— 这是本文件最容易写错的地方：
/// 用一个 `'a` 会把调用方逼去让两个本来无关的借用等长。
pub fn eval_int<'c>(node: NodeRef<'c>, ctx: &ExprContext<'_>) -> Result<i32, ExprError> {
    let kind = node.kind_str()?;
    match classify(kind) {
        Class::Int => {}
        Class::Bool => return Err(ExprError::WrongValueKind),
        Class::Card => return Err(ExprError::WrongValueKind),
        Class::NotAnExpression => return Err(ExprError::NotAnExpression),
        Class::Unknown => return Err(ExprError::UnsupportedKind),
    }

    match kind {
        // `ConstantExpression.Evaluate => Value`（`EffectProgramExpressions.cs:61`）。
        "const" => Ok(node.int_field("Value")?.ok_or(IrError::Missing("Value"))?),

        // `Saturate((long)l + r / - r / * r)`（`:256 / :280 / :304`）。
        "add" => {
            let (left, right) = int_pair(node, ctx)?;
            Ok(saturate(i64::from(left) + i64::from(right)))
        }
        "subtract" => {
            let (left, right) = int_pair(node, ctx)?;
            Ok(saturate(i64::from(left) - i64::from(right)))
        }
        "multiply" => {
            let (left, right) = int_pair(node, ctx)?;
            // |i32 × i32| ≤ 2^62 < i64::MAX —— 这一步乘法在 i64 里不可能溢出。
            Ok(saturate(i64::from(left) * i64::from(right)))
        }
        // `Math.Min` / `Math.Max`（`:328 / :352`）—— 不饱和，也不会溢出。
        "min" => {
            let (left, right) = int_pair(node, ctx)?;
            Ok(if left < right { left } else { right })
        }
        "max" => {
            let (left, right) = int_pair(node, ctx)?;
            Ok(if left > right { left } else { right })
        }

        "divide" => divide(node, ctx),

        // `CombatantStatusStacksExpression`（`:792-799`）：单目标读，各实例层数**求和**。
        "combatantStatusStacks" => {
            let status = node.str_field("StatusId")?.ok_or(IrError::Missing("StatusId"))?;
            let Some(target) = read_single_target(node, ctx)? else {
                return Ok(0); // `:796` 零个目标 ⇒ 0
            };
            let Some(combatant) = ctx.state.combatant(&target) else {
                return Ok(0); // `:797` 拿不到这个单位（TryGetCombatant 失败）⇒ 0
            };
            let mut total: i64 = 0;
            for instance in combatant.statuses() {
                if instance.definition_id.as_str() == status {
                    // 实例数有上限（固定容量），i64 累加不可能溢出。
                    total += i64::from(instance.stacks);
                }
            }
            Ok(saturate(total)) // `:798` 求和后饱和
        }

        // `CombatantCounterExpression`（`:915-922`）：`c.GetCounter(id)`，缺席 ⇒ 0。
        "combatantCounter" => {
            let key = node.str_field("CounterId")?.ok_or(IrError::Missing("CounterId"))?;
            let Some(target) = read_single_target(node, ctx)? else {
                return Ok(0); // `:918`
            };
            let Some(combatant) = ctx.state.combatant(&target) else {
                return Ok(0); // `:919-921`
            };
            for counter in combatant.counters() {
                if counter.key.as_str() == key {
                    return Ok(counter.value);
                }
            }
            Ok(0) // `GetCounter` 的缺席值
        }

        // `CombatantCurrentResourceExpression`（`:890-897`）：`TryGetValue(ResourceId) ⇒ Current : 0`。
        "combatantCurrentResource" => {
            let key = node.str_field("ResourceId")?.ok_or(IrError::Missing("ResourceId"))?;
            let Some(target) = read_single_target(node, ctx)? else {
                return Ok(0); // `:894`
            };
            let Some(combatant) = ctx.state.combatant(&target) else {
                return Ok(0); // `:895`
            };
            for pool in combatant.resources() {
                if pool.key.as_str() == key {
                    return Ok(pool.pool.current);
                }
            }
            Ok(0)
        }

        // `CombatantCurrentHealthExpression.Evaluate`（`:667-673`）：`Health.Current`。
        // 字段名 `Selector` 是**我们定的**（模块头第 4 条），不是镜像带给我们的：
        // 那份内容的 op 28 是 `nfields = 0`，所以那里**必然**走 `Missing("Selector")`。
        "currentHealth" => Ok(health_target(node, ctx)?.map_or(0, |c| c.health_current)),

        // `CombatantMaxHealthExpression.Evaluate`（`:687-693`）：`Health.Max`。
        "maxHealth" => Ok(health_target(node, ctx)?.map_or(0, |c| c.health_max)),

        // 其余（`eventAmount` / `cardsPlayedThisTurn` / `card.upgradeLevel` / `missingHealth` …）
        // —— 值类别是 int，但 v1 没有它需要的上下文。**绝不返回 0**。
        _ => Err(ExprError::UnsupportedKind),
    }
}

/// 求一个**卡实例**表达式。
///
/// 镜像里这类 kind 只有一种：`cardInstance.iterated`（0 字段，`trecon:236` 实测只有 t152
/// 这一条 term）。它读的是 `ForEachCardInZone` 在每轮循环里绑定的那张卡 ——
/// 也就是 [`ExprContext::iteration_card`]。
///
/// 为什么它必须是**独立入口**而不是 `eval_int` 的一个分支：参考里它是
/// `ICombatExpression<_, CardInstance>`，值域是卡实例 id 而不是数字。塞进 `eval_int`
/// 只有两种结局 —— 要么丢掉类型（拿 id 当数字），要么在实现里报 `UnsupportedKind`
/// （用"没实现"掩盖"问错了问题"）。所以这里给 `ExprError::WrongValueKind`：
/// `WrongValueKind` 是**三态**（int / bool / card 互相错配都算），
/// 它的名字恰好是这个意思，注释也一并更新了。
///
/// 没有绑定迭代卡时返回 [`ExprError::NoTarget`]：参考在上下文里没有迭代卡时
/// 是空引用解引用（整条程序作废），**不是给一个空卡 id**。给 `CardInstanceId::EMPTY`
/// 会让 `moveCardToZone` 去找一张不存在的卡并静默不动 —— 那是最坏的一种"通过"。
pub fn eval_card<'c>(node: NodeRef<'c>, ctx: &ExprContext<'_>) -> Result<CardInstanceId, ExprError> {
    let kind = node.kind_str()?;
    match classify(kind) {
        Class::Card => {}
        Class::Int => return Err(ExprError::WrongValueKind),
        Class::Bool => return Err(ExprError::WrongValueKind),
        Class::NotAnExpression => return Err(ExprError::NotAnExpression),
        Class::Unknown => return Err(ExprError::UnsupportedKind),
    }

    match kind {
        // `IteratedCardExpression.Evaluate => ctx.IteratedCard`。
        "cardInstance.iterated" => ctx.iteration_card.ok_or(ExprError::NoTarget),
        // 值类别是卡、但 v1 没有它的读法。**绝不返回空 id**。
        _ => Err(ExprError::UnsupportedKind),
    }
}

/// 求一个布尔表达式（`Condition` 用）。
pub fn eval_bool<'c>(node: NodeRef<'c>, ctx: &ExprContext<'_>) -> Result<bool, ExprError> {
    let kind = node.kind_str()?;
    match classify(kind) {
        Class::Bool => {}
        Class::Int => return Err(ExprError::WrongValueKind),
        Class::Card => return Err(ExprError::WrongValueKind),
        Class::NotAnExpression => return Err(ExprError::NotAnExpression),
        Class::Unknown => return Err(ExprError::UnsupportedKind),
    }

    match kind {
        // `ComparisonExpression.Evaluate`（`EffectProgramExpressions.cs:390-406`）。
        "compare" => {
            let left = eval_int(child(node, "Left")?, ctx)?;
            let right = eval_int(child(node, "Right")?, ctx)?;
            let op = node.str_field("Op")?.ok_or(IrError::Missing("Op"))?;
            compare_ints(left, right, op)
        }

        // `Left.Evaluate(...) && Right.Evaluate(...)`（`:431-432`）—— **必须短路**：
        // C# 的 `&&` 在左支 false 时根本不求右支，所以右支是一棵跑不通的树也不影响结果。
        "and" => {
            if eval_bool(child(node, "Left")?, ctx)? {
                eval_bool(child(node, "Right")?, ctx)
            } else {
                Ok(false)
            }
        }

        // `Left.Evaluate(...) || Right.Evaluate(...)`（`:455-456`）。
        "or" => {
            if eval_bool(child(node, "Left")?, ctx)? {
                Ok(true)
            } else {
                eval_bool(child(node, "Right")?, ctx)
            }
        }

        _ => Err(ExprError::UnsupportedKind),
    }
}

/// 比较操作符的字符串分派。
///
/// 8 个串来自**两个枚举**（模块头第 2 条）：战斗层 `Equal / NotEqual / Less / LessOrEqual /
/// Greater / GreaterOrEqual`（`EffectProgramExpressions.cs:360-368`），run 层把它们叫
/// `LessThan` / `GreaterThan`（`RunExpressions.cs:482-490`）。语义逐条相同，所以这里合并。
///
/// 不认识的串 ⇒ `UnsupportedKind`（冻结的 `ExprError` 没有"坏操作符"变体）。**不许**把它
/// 当成 `Equal` 或 `false` —— 那会让一张牌的整条分支安静地走错方向。
fn compare_ints(left: i32, right: i32, op: &str) -> Result<bool, ExprError> {
    match op {
        "Equal" => Ok(left == right),
        "NotEqual" => Ok(left != right),
        "Less" | "LessThan" => Ok(left < right),
        "LessOrEqual" => Ok(left <= right),
        "Greater" | "GreaterThan" => Ok(left > right),
        "GreaterOrEqual" => Ok(left >= right),
        _ => Err(ExprError::UnsupportedKind),
    }
}

/// `divide` 的两种拼法（模块头第 1 条）。
fn divide<'c>(node: NodeRef<'c>, ctx: &ExprContext<'_>) -> Result<i32, ExprError> {
    // 战斗层拼法：`{Dividend, Divisor, ZeroPolicy}`。
    // 两个拼法共用同一张字段表（并集），所以判据是**这个键有没有值**。
    if let Some(dividend_node) = node.node_field("Dividend")? {
        // 参考先算除数（`:572`），再算被除数（`:580`）。
        let divisor = eval_int(child(node, "Divisor")?, ctx)?;
        let policy = zero_policy(node)?;
        let dividend = eval_int(dividend_node, ctx)?;
        return combat_divide(dividend, divisor, policy);
    }
    // run 层拼法：`{Left, Right}`，没有 `ZeroPolicy`。
    if let Some(left_node) = node.node_field("Left")? {
        let divisor = eval_int(child(node, "Right")?, ctx)?;
        let dividend = eval_int(left_node, ctx)?;
        return run_divide(dividend, divisor);
    }
    // `divide` 的字段表里两套键都在，却两套都没值 —— 这棵树确实坏了。
    Err(ExprError::Ir(IrError::Missing("Dividend")))
}

/// 两个 int 子表达式的值（`Left` / `Right`，先左后右，与参考的求值序一致）。
fn int_pair<'c>(node: NodeRef<'c>, ctx: &ExprContext<'_>) -> Result<(i32, i32), ExprError> {
    let left = eval_int(child(node, "Left")?, ctx)?;
    let right = eval_int(child(node, "Right")?, ctx)?;
    Ok((left, right))
}

/// 单目标读的 `Selector` 字段 → 目标。
fn read_single_target<'c>(
    node: NodeRef<'c>,
    ctx: &ExprContext<'_>,
) -> Result<Option<CombatantId>, ExprError> {
    let selector = child(node, "Selector")?;
    let mut buf = [CombatantId::EMPTY; MAX_COMBATANTS];
    single_target(selector, ctx, &mut buf)
}

/// `Selector` 字段 → **一个战斗员**（`currentHealth` / `maxHealth` 用的单目标读）。
///
/// 参考的两个类是逐行同构的，差别只在最后取哪个字段：
/// `CombatantCurrentHealthExpression.Evaluate`（`EffectProgramExpressions.cs:667-673`）与
/// `CombatantMaxHealthExpression.Evaluate`（`:687-693`）都是
/// `ResolveTargets` → `Count == 0 ⇒ 0`（`:671` / `:691`）→ `RequireSingle`（`:28-36`，多于一个**抛**）
/// → `TryGetCombatant` 失败 ⇒ 0（`:672` / `:692`）→ `Health.Current` / `Health.Max`。
/// 所以这里只把"选择器 → 单位"这一段抽出来，`None` 覆盖两个"给 0"的分支
/// （没有目标 / 状态里查不到这个 id）；**取哪个字段由调用方两行分别写死**，
/// 免得一个 `bool` 参数让 `maxHealth` 读成 `currentHealth` 时没人看得出来。
///
/// 键缺席 ⇒ [`ExprError::Ir`]`(IrError::Missing("Selector"))`，与 `combatantStatusStacks`
/// 那条路完全一样（不是新变体）；**绝不退回英雄、绝不给 0** —— 见模块头第 4 条。
fn health_target<'c, 's>(
    node: NodeRef<'c>,
    ctx: &ExprContext<'s>,
) -> Result<Option<&'s Combatant>, ExprError> {
    let Some(target) = read_single_target(node, ctx)? else {
        return Ok(None); // 零个目标 ⇒ 调用方给 0（`:671` / `:691`）
    };
    Ok(ctx.state.combatant(&target)) // 查不到 ⇒ 也是 0（`:672` / `:692`）
}

/// 一个单目标读要用的目标：把选择器解出来，要求恰好/至多一个。
///
/// 参考实现的单目标读都带一个 `Selector`（`combatantStatusStacks` 等），且要求
/// `Cardinality::is_at_most_one()`；零个目标时参考给 **0**（不是错误）。
/// 本函数把"几个目标"这件事显式化，让调用方决定怎么处理。
///
/// 两道闸，对着参考实现的两次拦截：
/// * **静态基数**（`ScalarTargetExpression.RequireSingleSelector`，
///   `EffectProgramExpressions.cs:16-26`）：参考在**构造期**就拒绝多目标选择器；
/// * **解出的个数**（`ScalarTargetExpression.RequireSingle`，`:28-36`）：求值期再拒一次，
///   注释明说「不要静默用第一个」。
///
/// `out` 必须装得下 [`MAX_COMBATANTS`] 个目标 —— 装不下时 `resolve` 会**写满即停**，
/// 于是"没有目标"与"被截断"就分不开了。宁可响亮失败，所以给 `IrError::List`
/// （冻结的枚举里"缓冲区装不下"只有这一个诚实的名字）。
pub fn single_target<'c>(
    selector: NodeRef<'c>,
    ctx: &ExprContext<'_>,
    out: &mut [CombatantId],
) -> Result<Option<CombatantId>, ExprError> {
    if out.len() < MAX_COMBATANTS {
        return Err(ExprError::Ir(IrError::List));
    }
    let compiled = CompiledSelector::compile(selector)?;
    if !targets::cardinality(compiled.table()).is_at_most_one() {
        return Err(ExprError::SelectorNotSingle);
    }
    let selection = ctx.selection();
    // `resolve` 的 `SelectorError` 只可能来自坏下标/坏 id 引用/环 —— 也就是"编译出来的表自己坏了"。
    // [`SelError`] 里没有对应的变体，沿用 `sel.rs:216-221` 已有的映射（`TableFull`）：
    // 编译期已经保证表是好的，所以这条分支不可达，重要的是**不是 unwrap**。
    let count = compiled
        .resolve(&selection, out)
        .map_err(|_| ExprError::Sel(SelError::TableFull))?;
    match count {
        // 参考：`if (targets.Count == 0) return 0;` —— 零个目标**不是**错误。
        0 => Ok(None),
        1 => Ok(out.first().copied()),
        // 静态基数说"至多一个"而实际解出多个：表错了。**不截断成第一个**。
        _ => Err(ExprError::SelectorNotSingle),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_error_variants_are_all_distinguishable() {
        // 这个项目里"静默给 0"是最危险的失败模式（一张牌什么都不做但不报错），
        // 所以每种失败都必须有自己的变体，不能合并成大而化之的 Error。
        let all = [
            ExprError::UnsupportedKind,
            ExprError::NotAnExpression,
            ExprError::WrongValueKind,
            ExprError::DivideByZero,
            ExprError::SelectorNotSingle,
            ExprError::NoTarget,
            ExprError::Overflow,
        ];
        for (i, a) in all.iter().enumerate() {
            for (j, b) in all.iter().enumerate() {
                assert_eq!(i == j, a == b, "{a:?} 与 {b:?} 必须可分");
            }
        }
    }

    // =========================================================================================
    // W4c：`eval_int` / `eval_bool` / `single_target`
    //
    // 这些测试**读真实镜像**（`tools/contentc/out/content.core.rdcf`，85,616 B）。镜像不在仓库
    // 里（它是构建产物），所以找不到就 panic 并打印路径与生成命令 —— 产物缺席时安静通过的测试
    // 等于没有测试。期望值全部是实测出来的（`tools/contentc/reader.py` 遍历 2,143 条 term +
    // `tools/_core_dump.json` 的源出现次数），每条都写在断言旁边。
    //
    // 需要"镜像里根本不存在的那种树"（i32 饱和、除零、多目标选择器）时，就地**补丁**镜像字节，
    // 与 `sel.rs` 的补丁测试同一套做法：字段首槽偏移由字段表顺序算出，写 2 字节。
    // =========================================================================================

    use crate::content::{Content, F_TERM, S_OPD, S_OPF, S_TRM, S_TRW};
    use crate::ir::Ir;
    use crate::state::{
        CombatId, Combatant, CombatantDefinitionId, CounterId, ResourceId, StatusDefinitionId,
        StatusInstance, StatusInstanceId, StatusPolarity, TeamId,
    };

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

    fn node<'a>(content: &'a Content<'a>, id: u16) -> NodeRef<'a> {
        NodeRef::new(content, id)
    }

    /// 串池里某个串的串号（测试要往 `F_STR` 槽里写一个**真实存在**的串时用）。
    fn string_id(content: &Content<'_>, text: &str) -> u16 {
        for (i, s) in content.strings().enumerate() {
            if s == Some(text) {
                return u16::try_from(i + 1).expect("串号不超 u16");
            }
        }
        panic!("串池里没有 {text:?} —— 补丁测试要求目标是镜像里真实存在的串");
    }

    fn root_of<'a>(ir: &Ir<'a>, index: u32) -> NodeRef<'a> {
        ir.card_program_root(index)
            .unwrap_or_else(|e| panic!("CARD[{index}] 取不到程序根节点：{e:?}"))
    }

    // ---------------------------------------------------------------- 镜像补丁（2 字节）

    /// 一个 term 某字段**首槽**在 blob 里的字节偏移（与 `ir::NodeRef::field_spec` 同一套映射）。
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

    fn patch16(blob: &mut [u8], at: usize, value: u16) {
        let slot = blob.get_mut(at..at + 2).unwrap_or_else(|| panic!("patch16 越界：{at}"));
        slot.copy_from_slice(&value.to_le_bytes());
    }

    fn patch32(blob: &mut [u8], at: usize, value: u32) {
        let slot = blob.get_mut(at..at + 4).unwrap_or_else(|| panic!("patch32 越界：{at}"));
        slot.copy_from_slice(&value.to_le_bytes());
    }

    /// `OPD[op]` 的 `(field_off, nfields)`。8 字节一条：
    /// `field_off:u32` +0、`name_str:u16` +4、`nfields:u8` +6、`opclass:u8` +7
    /// （`content.rs` 的 `opcode()` 就是这么解的）。`field_off` 是 **`OPF` 段内**的字节下标。
    fn opd_field_span(content: &Content<'_>, op: u16) -> (u32, usize) {
        let opd = content.section(S_OPD).expect("OPD 段");
        let base = usize::from(op) * 8;
        let raw = opd.data.get(base..base + 8).unwrap_or_else(|| panic!("OPD[{op}] 越界"));
        (u32::from_le_bytes([raw[0], raw[1], raw[2], raw[3]]), usize::from(raw[6]))
    }

    /// 某 opcode 的某个字段在 `OPF` 段里的**记录**偏移 —— 与 `OPD.field_off` 同一套坐标。
    /// 每条记录固定 4 字节（`u16` 串号 + `u8` 类别 + `u8` 标志），与字段的槽宽无关。
    fn opf_record_offset(content: &Content<'_>, op: u16, key: &str) -> u32 {
        let (field_off, nfields) = opd_field_span(content, op);
        let opcode = content.opcode(op).expect("opcode 必须存在");
        for j in 0..nfields {
            let field = opcode.field(j).expect("字段描述越界");
            if content.string(field.name_str()) == Some(key) {
                return field_off + u32::try_from(j).expect("字段下标不超 u32") * 4;
            }
        }
        panic!("op {op} 没有字段 {key}");
    }

    /// 给 `currentHealth`（op 28）/ `maxHealth`（op 48）的 opcode **补上一个 `Selector` 字段**，
    /// 并把这个 term 的槽指到 `selector_term`。
    ///
    /// 为什么必须打补丁：真实镜像里这两个 opcode 的字段表是**空的**（`nfields = 0`，模块头第 4 条），
    /// 所以"带选择器"的形状在线上不存在 —— 补丁造出来的正是**我们定义的新格式**该有的样子。
    ///
    /// 三处字节，每一处都有实测出处（2026-10-19）：
    /// * `OPD[op].field_off` → **借** op 25（`combatantStatusStacks`）那条 `Selector:F_TERM` 记录
    ///   （实测在 `OPF` 的 76 号字节）。借来的记录同时决定**字段名** = `Selector`；
    /// * `OPD[op].nfields` → 1；
    /// * 该 term 记录的**填充槽** `TRM[word*4 + 2]` → 选择器 term id。0 槽 term 的记录是
    ///   `align4(2 + 0) = 4` 字节（`compile.py:178` 的 `record_size`），后 2 字节是**填充**；
    ///   且 `TRW` 的 word 下标**严格递增**（实测 2143 条里 0 处非递增）⇒ 这个槽不与别的 term 共享。
    ///
    /// 偏移一律在**原镜像**上算：`blob` 可能已经被 `patched()` 改过，但改的都是槽值，不动表结构。
    fn patch_in_selector(blob: &mut [u8], op: u16, tid: u16, selector_term: u16) {
        let pristine = core_image();
        let content = parse(&pristine);
        let opd = content.section(S_OPD).expect("OPD 段");
        let entry = opd.offset as usize + usize::from(op) * 8;
        let borrowed = opf_record_offset(&content, 25, "Selector");
        // 借来的记录必须**真的是** `Selector: F_TERM`：记录布局是
        // `name_str:u16 +0, kind:u8 +2, flags:u8 +3`。少了这条断言，镜像一换就可能把
        // 2 字节写进一个 `F_STR` 槽里，而测试会**安静地**测到别的东西（这是本项目
        // "工具骗人"那一类，不是假想的风险）。
        let opf = content.section(S_OPF).expect("OPF 段");
        let record = opf
            .data
            .get(borrowed as usize..borrowed as usize + 4)
            .expect("OPF 记录越界");
        assert_eq!(record[2], F_TERM, "借来的 OPF 记录必须是 F_TERM");
        assert_eq!(record[3], 0, "借来的 OPF 记录不能带 wrap 标志");
        patch32(blob, entry, borrowed);
        *blob.get_mut(entry + 6).expect("OPD nfields 越界") = 1;
        let trw = content.section(S_TRW).expect("TRW 段");
        let trm = content.section(S_TRM).expect("TRM 段");
        let word = usize::from(trw.u16_at(usize::from(tid)).expect("TRW 项越界"));
        patch16(blob, trm.offset as usize + word * 4 + 2, selector_term);
    }

    /// 某个单目标读节点的 `Selector` **子 term 的 id**（测试要把它塞进 `currentHealth` 的槽里）。
    fn selector_term(content: &Content<'_>, tid: u16) -> u16 {
        child(node(content, tid), "Selector")
            .expect("这个 term 必须有 Selector")
            .id()
    }

    /// 造一份**打过补丁**的镜像：`edits` 是 `(term, 字段名, 新的槽值 u16)`。
    ///
    /// 新值同时用在两种场合：指向子节点时是 term id，写 `F_INT` 时是 i16 的位模式
    /// （`-32767i16 as u16`）。偏移先在**原镜像**上算好（`Content` 借用的是原字节，
    /// 补丁写进副本，两者不冲突），再统一落盘、重新解析。
    fn patched(edits: &[(u16, &str, u16)]) -> Vec<u8> {
        let pristine = core_image();
        let mut blob = pristine.clone();
        {
            let content = parse(&pristine);
            for (tid, key, value) in edits {
                let at = field_slot_offset(&content, *tid, key);
                patch16(&mut blob, at, *value);
            }
        }
        blob
    }

    // ---------------------------------------------------------------- 一个真实的小战斗

    fn cid(s: &str) -> CombatantId {
        CombatantId::new(s).unwrap()
    }

    fn unit(id: &str, team: &str, health: i32, max: i32) -> Combatant {
        Combatant::new(
            cid(id),
            CombatantDefinitionId::new(&format!("def.{id}")).unwrap(),
            TeamId::new(team).unwrap(),
            health,
            max,
        )
    }

    fn status(slot: &str, definition: &str, stacks: i32) -> StatusInstance {
        StatusInstance::new(
            StatusInstanceId::new(slot).unwrap(),
            StatusDefinitionId::new(definition).unwrap(),
            StatusPolarity::Buff,
        )
        .with_stacks(stacks)
    }

    /// 存储序 `[hero, enemy_a, enemy_b]`：
    ///
    /// | 下标 | id | 队伍 | 血量 | 状态 | 计数器 | 资源 |
    /// |---|---|---|---|---|---|---|
    /// | 0 | hero | player | 30/50 | `paperwork` **3 和 4 两条实例**、`doubt` 2 | `queue_position`=4, `seen_paperwork`=2 | `standard.energy`=3 |
    /// | 1 | enemy_a | enemy | 20/20 | `paperwork` 5、`witness_the_seal` **参数** | — | — |
    /// | 2 | enemy_b | enemy | 10/10 | `fatigue` 2、`witness_the_seal` 2 | `seen_panic`=2, `seen_paperwork`=5 | — |
    ///
    /// `enemy_b` 血最低（10）⇒ `sel.lowestHealthEnemy` 解出它，用来区分三个目标槽。
    /// 全部 id 都是镜像里真实存在的（`paperwork` / `doubt` / `fatigue` / `witness_the_seal` /
    /// `queue_position` / `seen_paperwork` / `seen_panic` / `standard.energy`）。
    ///
    /// 两个参数只给短路测试用：它们要把某个 `compare(… == 0)` 压到 true/false 两侧。
    fn arena_with(enemy_a_witness: i32, enemy_a_signature_pending: i32) -> CombatState {
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);

        let mut hero = unit("hero", "player", 30, 50);
        hero.push_status(status("status_000001", "paperwork", 3)).unwrap();
        hero.push_status(status("status_000002", "paperwork", 4)).unwrap();
        hero.push_status(status("status_000003", "doubt", 2)).unwrap();
        hero.set_counter(CounterId::new("queue_position").unwrap(), 4).unwrap();
        hero.set_counter(CounterId::new("seen_paperwork").unwrap(), 2).unwrap();
        hero.set_resource(ResourceId::new("standard.energy").unwrap(), 3, Some(3)).unwrap();
        state.add_combatant(hero).unwrap();

        let mut enemy_a = unit("enemy_a", "enemy", 20, 20);
        enemy_a.push_status(status("status_000011", "paperwork", 5)).unwrap();
        if enemy_a_witness != 0 {
            enemy_a
                .push_status(status("status_000012", "witness_the_seal", enemy_a_witness))
                .unwrap();
        }
        if enemy_a_signature_pending != 0 {
            enemy_a
                .push_status(status(
                    "status_000013",
                    "signature_pending",
                    enemy_a_signature_pending,
                ))
                .unwrap();
        }
        state.add_combatant(enemy_a).unwrap();

        let mut enemy_b = unit("enemy_b", "enemy", 10, 10);
        enemy_b.push_status(status("status_000021", "fatigue", 2)).unwrap();
        enemy_b.push_status(status("status_000022", "witness_the_seal", 2)).unwrap();
        enemy_b.set_counter(CounterId::new("seen_panic").unwrap(), 2).unwrap();
        enemy_b.set_counter(CounterId::new("seen_paperwork").unwrap(), 5).unwrap();
        state.add_combatant(enemy_b).unwrap();

        state
    }

    /// 默认小战斗：`enemy_a` 身上 `witness_the_seal` 1、没有 `signature_pending`。
    fn arena() -> CombatState {
        arena_with(1, 0)
    }

    /// 三个目标槽都指向不同单位：source=hero、event_target=enemy_a、iteration_target=enemy_b。
    fn full_ctx<'a>(state: &'a CombatState) -> ExprContext<'a> {
        ExprContext {
            state,
            source: Some(cid("hero")),
            event_target: Some(cid("enemy_a")),
            iteration_target: Some(cid("enemy_b")),
            iteration_card: None,
        }
    }

    /// 只有一个 hero 的战斗，血量由参数给。
    ///
    /// `arena()` 的 hero 固定 30/50，读不出"当前值变了没有"；血量类的测试要自己指定 `(current, max)`。
    fn hero_at(current: i32, max: i32) -> CombatState {
        let mut state = CombatState::new(CombatId::new("c_hp").unwrap(), 11);
        state.add_combatant(unit("hero", "player", current, max)).unwrap();
        state
    }

    /// `source = hero`、其余两个目标槽都空着（选择器用 `sel.source` 时用这个）。
    fn source_ctx(state: &CombatState) -> ExprContext<'_> {
        ExprContext {
            state,
            source: Some(cid("hero")),
            event_target: None,
            iteration_target: None,
            iteration_card: None,
        }
    }

    // =========================================================================================
    // 1. 端到端最小切片：三张真牌的表达式
    // =========================================================================================

    #[test]
    fn paper_cut_amount_evaluates_to_six() {
        // CARD[0] = paper_cut，实测根是
        //   node.dealDamage { Amount: const{Value:6}, TargetSelector: sel.eventTarget }
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let state = arena();
        let ctx = full_ctx(&state);

        let root = root_of(&ir, 0);
        assert_eq!(root.kind_str(), Ok("node.dealDamage"));
        let amount = root.node_field("Amount").unwrap().expect("Amount");
        assert_eq!(amount.kind_str(), Ok("const"));
        assert_eq!(eval_int(amount, &ctx), Ok(6));
        // 常量与状态无关：**空状态**也给 6（证明上面那 6 不是被状态凑出来的）。
        let empty = CombatState::new(CombatId::new("c2").unwrap(), 7);
        let empty_ctx = ExprContext {
            state: &empty,
            source: None,
            event_target: None,
            iteration_target: None,
            iteration_card: None,
        };
        assert_eq!(eval_int(amount, &empty_ctx), Ok(6));
    }

    #[test]
    fn cower_behind_a_desk_amount_evaluates_to_five() {
        // CARD[2] = cower_behind_a_desk = node.gainBlock { Amount: const{Value:5} }
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let state = arena();
        let ctx = full_ctx(&state);
        let root = root_of(&ir, 2);
        assert_eq!(root.kind_str(), Ok("node.gainBlock"));
        let amount = root.node_field("Amount").unwrap().expect("Amount");
        assert_eq!(eval_int(amount, &ctx), Ok(5));
    }

    #[test]
    fn strong_binder_apply_status_stacks_evaluates_to_one() {
        // CARD[4] = strong_binder = node.sequence[ gainBlock, applyStatus ]，
        // 第二个孩子的 Stacks 是 const{Value:1}，StatusDefinitionId = "doubt"。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let state = arena();
        let ctx = full_ctx(&state);
        let root = root_of(&ir, 4);
        assert_eq!(root.kind_str(), Ok("node.sequence"));
        let mut kids = [0u16; 8];
        let n = root.list_field("Children", &mut kids).expect("Children");
        assert_eq!(n, 2);
        let apply = node(&content, kids[1]);
        assert_eq!(apply.kind_str(), Ok("node.applyStatus"));
        assert_eq!(apply.str_field("StatusDefinitionId"), Ok(Some("doubt")));
        let stacks = apply.node_field("Stacks").unwrap().expect("Stacks");
        assert_eq!(eval_int(stacks, &ctx), Ok(1));
    }

    #[test]
    fn compounded_penalty_needs_no_health_expression() {
        // 交付方原本的说法是「v1 需要 currentHealth 才能算 compounded_penalty」。实测**不需要**：
        // CARD[20] 的 Amount 是 multiply{ combatantStatusStacks{sel.eventTarget, paperwork}, 4 }。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let state = arena();
        let ctx = full_ctx(&state);
        let root = root_of(&ir, 20);
        assert_eq!(root.kind_str(), Ok("node.dealDamage"));
        let amount = root.node_field("Amount").unwrap().expect("Amount");
        assert_eq!(amount.kind_str(), Ok("multiply"));
        // enemy_a 身上 paperwork = 5 ⇒ 5 * 4 = 20。
        assert_eq!(eval_int(amount, &ctx), Ok(20));
        // 同一棵树换成 hero 当事件目标（hero 的 paperwork = 3+4 = 7）⇒ 28。
        // 两个宿主给出**不同**结果，证明读的确实是 event_target 而不是别的槽。
        let hero_ctx = ExprContext {
            state: &state,
            source: Some(cid("hero")),
            event_target: Some(cid("hero")),
            iteration_target: None,
            iteration_card: None,
        };
        assert_eq!(eval_int(amount, &hero_ctx), Ok(28));
    }

    // =========================================================================================
    // 2. 叶子：const 的符号、单目标读的三个槽
    // =========================================================================================

    #[test]
    fn const_reads_the_signed_i16_slot() {
        // 实测 term 265 = const{Value:-1}（raw 槽 0xFFFF）。`raw as i32` 会得到 65535 —— 错。
        let blob = core_image();
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);
        assert_eq!(eval_int(node(&content, 265), &ctx), Ok(-1));
        // 正例成对：term 1 = const{Value:6}。
        assert_eq!(eval_int(node(&content, 1), &ctx), Ok(6));
    }

    #[test]
    fn status_stacks_sums_every_instance_on_the_one_target() {
        // term 296 = combatantStatusStacks{ sel.source, "paperwork" }：hero 有 3 与 4 两条实例 ⇒ 7。
        let blob = core_image();
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);
        assert_eq!(eval_int(node(&content, 296), &ctx), Ok(7), "两条实例必须求和，不是取第一条");
        // 成对反例：hero 身上没有 bookworm（term 291）⇒ 0，而不是 7。
        assert_eq!(eval_int(node(&content, 291), &ctx), Ok(0));
    }

    #[test]
    fn the_three_target_slots_are_actually_distinct() {
        // 同一份状态、同一个 status（paperwork），三个槽解出三个不同单位：
        //   term 92  = eventTarget ⇒ enemy_a 的 5
        //   term 296 = source      ⇒ hero 的 3+4 = 7
        // 若把 `single_target` 接错槽（例如永远用 source），这两个数会变成同一个。
        let blob = core_image();
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);
        assert_eq!(eval_int(node(&content, 92), &ctx), Ok(5));
        assert_eq!(eval_int(node(&content, 296), &ctx), Ok(7));
        assert_ne!(eval_int(node(&content, 92), &ctx), eval_int(node(&content, 296), &ctx));

        // iterationTarget：term 1000 = combatantCounter{ sel.iterationTarget, "seen_panic" }。
        // enemy_b 身上 seen_panic = 2；event_target（enemy_a）身上没有 ⇒ term 337 = 0。
        assert_eq!(eval_int(node(&content, 1000), &ctx), Ok(2));
        assert_eq!(eval_int(node(&content, 337), &ctx), Ok(0));

        // 把 iteration_target 挪到 enemy_a ⇒ 0；把 event_target 挪到 enemy_b ⇒ 5。
        // 两个方向都动，且两个数都是实打实存在过的计数器值（enemy_b：seen_panic=2、seen_paperwork=5）。
        let swapped = ExprContext {
            state: &state,
            source: Some(cid("hero")),
            event_target: Some(cid("enemy_b")),
            iteration_target: Some(cid("enemy_a")),
            iteration_card: None,
        };
        assert_eq!(eval_int(node(&content, 1000), &swapped), Ok(0));
        assert_eq!(eval_int(node(&content, 337), &swapped), Ok(5));
    }

    #[test]
    fn counters_and_resources_read_the_named_entry_or_zero() {
        let blob = core_image();
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);
        // term 306 = combatantCounter{ sel.source, "queue_position" } ⇒ 4
        assert_eq!(eval_int(node(&content, 306), &ctx), Ok(4));
        // term 1131 = combatantCurrentResource{ sel.source, "standard.energy" } ⇒ Current=3
        assert_eq!(eval_int(node(&content, 1131), &ctx), Ok(3));
        // 成对反例：这两个**名字**在目标身上不存在时给 0。
        // term 337 = combatantCounter{ sel.eventTarget, "seen_paperwork" } ⇒ enemy_a 没有 ⇒ 0
        assert_eq!(eval_int(node(&content, 337), &ctx), Ok(0));
        // 资源池缺席也走 0：把 source 指向 enemy_b（没有任何资源池）。
        let enemy_src = ExprContext {
            state: &state,
            source: Some(cid("enemy_b")),
            event_target: None,
            iteration_target: None,
            iteration_card: None,
        };
        assert_eq!(eval_int(node(&content, 1131), &enemy_src), Ok(0));
    }

    // =========================================================================================
    // 3. 单目标读的边界：0 个目标 ⇒ 0；≥2 个目标 ⇒ SelectorNotSingle
    // =========================================================================================

    #[test]
    fn zero_targets_read_as_zero_not_an_error() {
        // 参考：`if (targets.Count == 0) return 0;`（EffectProgramExpressions.cs:796）。
        let blob = core_image();
        let content = parse(&blob);
        let state = arena();
        let no_target = ExprContext {
            state: &state,
            source: None,
            event_target: None,
            iteration_target: None,
            iteration_card: None,
        };
        assert_eq!(eval_int(node(&content, 92), &no_target), Ok(0));
        assert_eq!(eval_int(node(&content, 337), &no_target), Ok(0));
        // 成对：同一份状态、同一个 term，只要槽里有人就不是 0（证明上面不是空断言）。
        let ctx = full_ctx(&state);
        assert_eq!(eval_int(node(&content, 92), &ctx), Ok(5));

        // `single_target` 自己也要说"没有目标"，而不是 Err。
        let mut buf = [CombatantId::EMPTY; MAX_COMBATANTS];
        let selector = child(node(&content, 92), "Selector").expect("Selector");
        assert_eq!(single_target(selector, &no_target, &mut buf), Ok(None));
        assert_eq!(single_target(selector, &ctx, &mut buf), Ok(Some(cid("enemy_a"))));
    }

    #[test]
    fn a_multi_target_selector_is_selector_not_single() {
        // 参考在两处拦：构造期 `RequireSingleSelector`（:16-26，静态基数），
        // 求值期 `RequireSingle`（:28-36，解出的个数）。两处都是**错误**，不是"取第一个"。
        // 真镜像里 13 条 combatantStatusStacks 全是 ZeroOrOne 选择器，所以把 term 92 的
        // Selector 补丁成 term 182（sel.allEnemies，静态基数 ZeroOrMore，解出 2 个敌人）。
        let blob = patched(&[(92, "Selector", 182)]);
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);
        let mut buf = [CombatantId::EMPTY; MAX_COMBATANTS];
        let selector = child(node(&content, 92), "Selector").expect("Selector");
        assert_eq!(
            single_target(selector, &ctx, &mut buf),
            Err(ExprError::SelectorNotSingle)
        );
        // 求值路径也必须把这条错误**带出来**，不许安静地给 0。
        assert_eq!(eval_int(node(&content, 92), &ctx), Err(ExprError::SelectorNotSingle));

        // 成对：同一个 term 不补丁时是好的（ZeroOrOne）。
        let pristine = core_image();
        let pristine_content = parse(&pristine);
        let selector = child(node(&pristine_content, 92), "Selector").expect("Selector");
        assert_eq!(
            single_target(selector, &ctx, &mut buf),
            Ok(Some(cid("enemy_a")))
        );

        // sink 装不下 MAX_COMBATANTS 时响亮失败（否则"没有目标"与"被截断"分不开）。
        let mut small = [CombatantId::EMPTY; 2];
        assert_eq!(
            single_target(selector, &ctx, &mut small),
            Err(ExprError::Ir(IrError::List))
        );
    }

    // =========================================================================================
    // 3b. `currentHealth` / `maxHealth`：字段名是我们定的（`Selector`），语义是参考的
    //
    // 真实镜像里这两个 opcode 的字段表是 **空的**（`nfields = 0`，模块头第 4 条），所以
    // "带选择器"的形状**在线上不存在** —— 只能像 `sel.rs` 那样**补丁镜像字节**造出来：
    // 给 opcode 补一条 `Selector:F_TERM` 记录 + 把这个 0 槽 term 的**填充槽**写成选择器 id。
    // 补丁的每一处字节都在 `patch_in_selector` 的注释里说明了出处。
    // =========================================================================================

    #[test]
    fn current_health_reads_the_live_value_after_damage() {
        // term 1527 = `currentHealth`（镜像里唯一一条，op 28）。补上 `Selector = sel.source`
        // （= hero）之后，这一条同时钉住三件事：
        //   * 读到的是 `health_current`（30）而不是 `health_max`（50）—— **把 current 读成 max
        //     的实现会红**；
        //   * 把目标真的打一顿之后再读就是新值 —— **把数值缓存在节点上（或缓存成满血）的实现会红**；
        //   * 读的确实是 `sel.source` 那个单位：event_target（enemy_a）是 20、iteration_target
        //     （enemy_b）是 10、max 是 50，四个数互不相同 ⇒ 接错槽也藏不住。
        let source_sel = {
            let blob = core_image();
            let content = parse(&blob);
            selector_term(&content, 296) // t296 = combatantStatusStacks{sel.source, paperwork}
        };
        let mut blob = core_image();
        patch_in_selector(&mut blob, 28, 1527, source_sel);
        let content = parse(&blob);

        let mut state = arena(); // hero 30/50、enemy_a 20/20、enemy_b 10/10
        assert_eq!(eval_int(node(&content, 1527), &full_ctx(&state)), Ok(30));
        // 打它 —— 改的是**同一份状态**里的那个字段，不是另造一个 arena。
        state.combatant_mut(&cid("hero")).expect("hero").health_current = 11;
        assert_eq!(eval_int(node(&content, 1527), &full_ctx(&state)), Ok(11));
        state.combatant_mut(&cid("hero")).expect("hero").health_current = 11 + 1;
        assert_eq!(eval_int(node(&content, 1527), &full_ctx(&state)), Ok(12));
        // 成对：`health_max` 一次都没被碰过 ⇒ 上面三个数只可能来自 current。
        assert_eq!(
            state.combatant(&cid("hero")).expect("hero").health_max,
            50
        );
    }

    #[test]
    fn max_health_and_current_health_read_two_different_fields() {
        // 同一份状态、同一个选择器：current = 30、max = 50。**两个 kind 读同一个字段的实现
        // 会红**（30 ≠ 50）。
        //
        // ⚠️ 注意**满血**那一格（current == max）**区分不出任何东西**：读 current、读 max、
        // 两个都读同一个字段，三种实现都能过它。所以判据必须是受伤的状态；满血那一格留在这里
        // 只是为了让"为什么不能拿它当判据"变成可复现的，而不是一句口头纪律。
        let source_sel = {
            let blob = core_image();
            let content = parse(&blob);
            selector_term(&content, 296)
        };
        let mut blob = core_image();
        patch_in_selector(&mut blob, 28, 1527, source_sel);
        patch_in_selector(&mut blob, 48, 1728, source_sel);
        let content = parse(&blob);

        let mut state = arena(); // hero 30/50
        assert_eq!(eval_int(node(&content, 1527), &full_ctx(&state)), Ok(30));
        assert_eq!(eval_int(node(&content, 1728), &full_ctx(&state)), Ok(50));
        assert_ne!(
            eval_int(node(&content, 1527), &full_ctx(&state)),
            eval_int(node(&content, 1728), &full_ctx(&state)),
            "两个 kind 必须是两个字段"
        );

        // 受伤只动 current：max 读出来必须**还是** 50。
        state.combatant_mut(&cid("hero")).expect("hero").health_current = 7;
        assert_eq!(eval_int(node(&content, 1527), &full_ctx(&state)), Ok(7));
        assert_eq!(eval_int(node(&content, 1728), &full_ctx(&state)), Ok(50));

        // 满血那一格：两者相等（**不能当判据**，见上）。
        let full = hero_at(50, 50);
        assert_eq!(eval_int(node(&content, 1527), &source_ctx(&full)), Ok(50));
        assert_eq!(eval_int(node(&content, 1728), &source_ctx(&full)), Ok(50));
    }

    #[test]
    fn a_health_read_with_no_target_is_zero() {
        // 参考：`if (targets.Count == 0) return 0;`（`EffectProgramExpressions.cs:671` / `:691`）。
        // 选择器用 `sel.eventTarget`（静态基数 ZeroOrOne ⇒ 过得了静态那道闸），上下文里不给它。
        let event_target_sel = {
            let blob = core_image();
            let content = parse(&blob);
            selector_term(&content, 92) // t92 = combatantStatusStacks{sel.eventTarget, paperwork}
        };
        let mut blob = core_image();
        patch_in_selector(&mut blob, 28, 1527, event_target_sel);
        patch_in_selector(&mut blob, 48, 1728, event_target_sel);
        let content = parse(&blob);

        let mut state = arena();
        // 把 event_target 打成 12/20 ⇒ 下面"不是 0"的那两个数是**两个不同的**非零值，
        // 于是"零目标给 0"这条也顺带证明了 current / max 没有接反。
        state.combatant_mut(&cid("enemy_a")).expect("enemy_a").health_current = 12;

        let no_target = ExprContext {
            state: &state,
            source: Some(cid("hero")),
            event_target: None,
            iteration_target: Some(cid("enemy_b")),
            iteration_card: None,
        };
        assert_eq!(eval_int(node(&content, 1527), &no_target), Ok(0));
        assert_eq!(eval_int(node(&content, 1728), &no_target), Ok(0));

        // 成对：同一个 term、同一份状态，只要槽里有人（enemy_a 12/20）就不是 0。
        let ctx = full_ctx(&state);
        assert_eq!(eval_int(node(&content, 1527), &ctx), Ok(12));
        assert_eq!(eval_int(node(&content, 1728), &ctx), Ok(20));
    }

    #[test]
    fn a_health_read_with_a_multi_target_selector_is_selector_not_single() {
        // term 182 = `sel.allEnemies`（静态基数 ZeroOrMore，场上 2 个敌人）。参考在**构造期**
        // 就 `RequireSingleSelector` 拒绝（`EffectProgramExpressions.cs:16-26`），求值期还有
        // `RequireSingle`（`:28-36`，注释明说「不要静默用第一个」）。
        // ⇒ 必须报 `SelectorNotSingle`，不许悄悄读 enemy_a（20）。
        let mut blob = core_image();
        patch_in_selector(&mut blob, 28, 1527, 182);
        patch_in_selector(&mut blob, 48, 1728, 182);
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);
        assert_eq!(
            eval_int(node(&content, 1527), &ctx),
            Err(ExprError::SelectorNotSingle)
        );
        assert_eq!(
            eval_int(node(&content, 1728), &ctx),
            Err(ExprError::SelectorNotSingle)
        );
        assert_ne!(eval_int(node(&content, 1527), &ctx), Ok(20), "不许取第一个");

        // 成对：同一份状态、同两个 term，选择器换成 `sel.eventTarget`（ZeroOrOne）就正常。
        let event_target_sel = {
            let blob = core_image();
            let content = parse(&blob);
            selector_term(&content, 92)
        };
        let mut blob = core_image();
        patch_in_selector(&mut blob, 28, 1527, event_target_sel);
        patch_in_selector(&mut blob, 48, 1728, event_target_sel);
        let content = parse(&blob);
        assert_eq!(eval_int(node(&content, 1527), &ctx), Ok(20));
        assert_eq!(eval_int(node(&content, 1728), &ctx), Ok(20));
    }

    #[test]
    fn a_health_read_without_a_selector_is_a_loud_missing_field_error() {
        // **真实镜像**（不打补丁）的 op 28 / op 48 就是 `nfields = 0`（模块头第 4 条），
        // 所以这两个 term 今天在任何内容里都读不出来 —— 这正是要的行为：**给 0 或退回英雄都是错的**
        // （前者让 `maxHealth*10` 安静算成 0，后者算成"英雄血量的 10 倍"）。
        // 断言的是**具体那个错**，不是 `is_err()`：`Ir(Missing("Selector"))` 与
        // `UnsupportedKind` / `WrongValueKind` / `SelectorNotSingle` 必须分得开。
        let blob = core_image();
        let content = parse(&blob);
        let state = arena(); // hero 30/50、enemy_a 20/20、enemy_b 10/10
        let ctx = full_ctx(&state);
        // 先把"这两个 term id 确实是这两个 kind"钉住：下面那些断言的数字全靠它对，
        // 而 term id 只在**这一份**镜像里有效（换内容就变）。
        assert_eq!(node(&content, 1527).kind_str(), Ok("currentHealth"));
        assert_eq!(node(&content, 1728).kind_str(), Ok("maxHealth"));
        for tid in [1527u16, 1728] {
            assert_eq!(
                eval_int(node(&content, tid), &ctx),
                Err(ExprError::Ir(IrError::Missing("Selector"))),
                "term {tid}：字段表里没有 Selector（`nfields = 0`）"
            );
            // 三种"猜"逐个排除（它们在**这份状态**里各有不同的数字，所以每一条都不是空断言）。
            assert_ne!(eval_int(node(&content, tid), &ctx), Ok(0), "不许静默给 0");
            assert_ne!(eval_int(node(&content, tid), &ctx), Ok(30), "不许退回英雄的当前血量");
            assert_ne!(eval_int(node(&content, tid), &ctx), Ok(50), "不许退回英雄的最大血量");
        }
        // 值类别仍然是 int：当 bool 问 ⇒ `WrongValueKind`（问错了问题），不是"还没实现"。
        assert_eq!(
            eval_bool(node(&content, 1527), &ctx),
            Err(ExprError::WrongValueKind)
        );
        // 外层树也不许悄悄算出别的数：term 1731 = add{ multiply{maxHealth, 10}, const 99 }。
        // 这条补上了原来那条"`maxHealth*10+99` 不许变成 99"的断言 —— 现在它连 99 都算不出来，
        // 而是把同一个 `Missing("Selector")` 顶上来。
        assert_eq!(
            eval_int(node(&content, 1731), &ctx),
            Err(ExprError::Ir(IrError::Missing("Selector")))
        );
        assert_ne!(eval_int(node(&content, 1731), &ctx), Ok(99), "不许悄悄变成 99");
    }

    #[test]
    fn divider_is_current_health_divided_by_twelve_plus_one() {
        // 这条是整件事的动机：Hexaghost 的 Divider = `(目标当前 HP / 12) + 1`
        // （`docs/spec/sts-act1-plan.md` §2 G3）。整棵树用镜像里现成的 term 拼：
        //   term 307 = add{ Left, Right }                     ← Right 本来就是 const 1（term 29）
        //   Left → term 650 = divide{Dividend, Divisor, ZeroPolicy:ReturnZero}
        //   Dividend → term 1527 = currentHealth{Selector: sel.source}（Selector 由补丁加上）
        //   Divisor  → term 39   = const 2（Value 补丁成 12）
        // 三个 HP 点卡在除法边界上：11 → 1、12 → 2、143 → 12。
        // 这三个数把四种错实现都杀掉：漏 +1（11→0）、四舍五入而非截断（143→13）、
        // current 读成 max（11/50 → 5；143/160 → 14）、零目标给 0（这里选择器是有目标的）。
        let source_sel = {
            let blob = core_image();
            let content = parse(&blob);
            selector_term(&content, 296)
        };
        let mut blob = patched(&[
            (39, "Value", 12),        // const 2 → 12
            (650, "Dividend", 1527),  // 战斗层拼法的被除数 → currentHealth
            (650, "Divisor", 39),     // 除数 → const 12
            (307, "Left", 650),       // add.Left → divide
        ]);
        patch_in_selector(&mut blob, 28, 1527, source_sel);
        let content = parse(&blob);
        // 先确认拼出来的形状就是上面写的那棵树（否则循环里的数字可能是别的原因凑出来的）。
        assert_eq!(node(&content, 307).kind_str(), Ok("add"));
        assert_eq!(node(&content, 650).kind_str(), Ok("divide"));
        assert_eq!(node(&content, 650).str_field("ZeroPolicy"), Ok(Some("ReturnZero")));
        assert_eq!(node(&content, 29).int_field("Value"), Ok(Some(1)), "右支是 const 1");
        assert_eq!(node(&content, 39).int_field("Value"), Ok(Some(12)));

        let mut results = [0i32; 3];
        for (i, (hp, max, want)) in [(11, 50, 1), (12, 50, 2), (143, 160, 12)]
            .into_iter()
            .enumerate()
        {
            let state = hero_at(hp, max);
            let ctx = source_ctx(&state);
            // 叶子、中间量、整棵树三层各钉一次："商"必须是截断除法，"+1"在外面。
            assert_eq!(eval_int(node(&content, 1527), &ctx), Ok(hp), "HP={hp}");
            assert_eq!(eval_int(node(&content, 650), &ctx), Ok(hp / 12), "商（HP={hp}）");
            assert_eq!(eval_int(node(&content, 307), &ctx), Ok(want), "Divider（HP={hp}）");
            results[i] = want;
        }
        // 三个点必须是**三个不同的数**（否则"整棵树就是常数"也能过上面三条）。
        assert_eq!(results, [1, 2, 12]);
    }

    // =========================================================================================
    // 4. 算术：饱和不 panic；divide 两种拼法
    // =========================================================================================

    #[test]
    fn arithmetic_saturates_instead_of_panicking() {
        // 镜像里的常量是 **i16**（最大 32767），所以造不出一个 `i32::MAX + 1` 的常量;
        // 用 32767 的三层乘法/加法凑出真正的 i32 溢出。补丁表：
        //   const 1  → 32767      (原 const{6})
        //   const 12 → 32767      (原 const{8})
        //   const 17 → 32767      (原 const{5})
        //   const 25 → -30000     (原 const{7})
        //   const 29 → 1          (本来就是 1，不动)
        //   mul 98   = multiply{const 1, const 12}      = 32767² = 1_073_676_289（还在 i32 内）
        //   mul 93   = multiply{mul 98, const 17}       = 3.5e13 → i32::MAX（饱和）
        //   mul 247  = multiply{mul 98, const 25}       = -3.2e13 → i32::MIN（饱和）
        //   add 307  = add{mul 93, mul 98}              = i32::MAX + 1.07e9 → i32::MAX（饱和）
        //   sub 292  = subtract{mul 247, const 29}      = i32::MIN - 1 → i32::MIN（饱和）
        //
        // ⚠️ 加法的两个操作数必须一大一小都够：`32767² × 2 = 2_147_352_578` **还没到** i32::MAX
        // （2_147_483_647）—— 第一次写这条测试时就是这么错过的，所以这里用"已经饱和的 93"当左操作数。
        //
        // ⚠️ 负常数只能到 -30000：`F_INT` 的槽是 i16，而 `-32768` / `-32767` 的位模式
        // 正好是 `ABSENT_INT`(0x8000) / `NULL_INT`(0x8001) 两个哨兵（`content.rs:143-145`），
        // 写进去会被读成"没这个值"。这是实测踩到的坑，不是风格问题。
        let blob = patched(&[
            (1, "Value", 32767),
            (12, "Value", 32767),
            (17, "Value", 32767),
            (25, "Value", (-30000i16) as u16),
            (98, "Left", 1),
            (98, "Right", 12),
            (93, "Left", 98),
            (93, "Right", 17),
            (247, "Left", 98),
            (247, "Right", 25),
            (307, "Left", 93),
            (307, "Right", 98),
            (292, "Left", 247),
            (292, "Right", 29),
        ]);
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);

        // 先核对中间层真的**没有**饱和：32767² = 1_073_676_289。
        assert_eq!(eval_int(node(&content, 98), &ctx), Ok(1_073_676_289));

        // 再核对四个方向都饱和到正确的端点（不 panic、不绕回）。
        assert_eq!(eval_int(node(&content, 93), &ctx), Ok(i32::MAX), "乘法正溢出");
        assert_eq!(eval_int(node(&content, 247), &ctx), Ok(i32::MIN), "乘法负溢出");
        assert_eq!(eval_int(node(&content, 307), &ctx), Ok(i32::MAX), "加法正溢出");
        assert_eq!(eval_int(node(&content, 292), &ctx), Ok(i32::MIN), "减法负溢出");

        // 参考实现的 `Saturate` 只钳 int 范围（EffectProgramExpressions.cs:213-217）：
        // 端点值本身**不再**被二次钳制。这里用成对断言说明"端点是端点的样子"。
        assert_ne!(eval_int(node(&content, 93), &ctx), Ok(0));
    }

    #[test]
    fn min_picks_the_smaller_operand() {
        // ⚠️ 镜像里 **没有 `max`**（源 JSON 里也是 0 次），而且 `max` 的 opcode 根本不在 opcode
        // 表里 —— 所以 `eval_int` 的 `max` 分支**无法用真实数据端到端测**，只能靠代码审查。
        // 这里用 `min` 的两个真实实例方向各测一遍：两种操作数顺序都必须得到较小者
        // （`max` 会得到 7，所以每条断言都能把 `max` 的实现错误杀掉）。
        let state = arena();
        let ctx = full_ctx(&state);

        let blob = patched(&[
            (1, "Value", 7),
            (12, "Value", 3),
            // term 308 = min{ add{counter,const 1}, const 3 } → 换成 min{const 1, const 12}
            (308, "Left", 1),
            (308, "Right", 12),
        ]);
        let content = parse(&blob);
        assert_eq!(eval_int(node(&content, 308), &ctx), Ok(3), "min(7,3)");

        let blob = patched(&[
            (1, "Value", 3),
            (12, "Value", 7),
            (308, "Left", 1),
            (308, "Right", 12),
        ]);
        let content = parse(&blob);
        assert_eq!(eval_int(node(&content, 308), &ctx), Ok(3), "min(3,7)");
    }

    #[test]
    fn the_two_divide_spellings_agree_on_the_same_operands() {
        // 实测两种拼法（各 2 条 term）：
        //   term 650  = {Dividend: statusStacks(sel.source, paperwork), Divisor: const 2, ZeroPolicy: "ReturnZero"}
        //   term 1733 = {Left: add{multiply{maxHealth…}}, Right: const 100}   ← run 层拼法
        // 把 1733 的 Left/Right 补丁成 650 的两个操作数（296 与 const 2），两边必须算出同一个数。
        let blob = patched(&[(1733, "Left", 296), (1733, "Right", 39)]);
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);

        assert_eq!(node(&content, 1733).node_field("Left").unwrap().map(|n| n.id()), Some(296));
        assert_eq!(node(&content, 650).node_field("Divisor").unwrap().map(|n| n.id()), Some(39));
        let combat_spelling = eval_int(node(&content, 650), &ctx);
        let run_spelling = eval_int(node(&content, 1733), &ctx);
        // hero 的 paperwork = 7 ⇒ 7 / 2 = 3（C# 与 Rust 都是截断除法）。
        assert_eq!(combat_spelling, Ok(3));
        assert_eq!(run_spelling, Ok(3));
        assert_eq!(combat_spelling, run_spelling);
    }

    #[test]
    fn the_two_divide_spellings_disagree_on_a_zero_divisor() {
        // ⚠️ 这条是**如实报告**，不是设计：两个拼法在除零时行为不同，因为它们是两个类。
        //   战斗层 {Dividend,Divisor}：默认 ReturnZero ⇒ 0（EffectProgramExpressions.cs:573-578）
        //   run 层 {Left,Right}：没有策略字段，除零直接抛（RunExpressions.cs:292-294）
        let zero = 290; // const{Value:0}
        let blob = patched(&[(650, "Divisor", zero), (1733, "Left", 296), (1733, "Right", zero)]);
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);
        assert_eq!(eval_int(node(&content, 650), &ctx), Ok(0), "战斗层 ReturnZero");
        assert_eq!(
            eval_int(node(&content, 1733), &ctx),
            Err(ExprError::DivideByZero),
            "run 层除零必须响亮失败"
        );
        // `Fault` 策略在镜像里**没有实例**（串池里只有 "ReturnZero"），所以只能直接测分派函数。
        assert_eq!(
            combat_divide(7, 0, ZeroPolicy::Fault),
            Err(ExprError::DivideByZero)
        );
        assert_eq!(combat_divide(7, 0, ZeroPolicy::ReturnZero), Ok(0));
        // 不认识的 `ZeroPolicy` 串不许悄悄当 ReturnZero。
        assert_eq!(zero_policy(node(&content, 650)), Ok(ZeroPolicy::ReturnZero));
    }

    #[test]
    fn divide_by_minus_one_uses_a_long_intermediate() {
        // 战斗层：(long)i32::MIN / -1 = 2_147_483_648 → 饱和成 i32::MAX，**不 panic**
        // （EffectProgramExpressions.cs:579-580）。run 层是 int 除法，同样输入在 C# 抛
        // OverflowException（RunExpressions.cs:294）⇒ 内核给 ExprError::Overflow。
        let blob = patched(&[
            (247, "Left", 98),               // mul 247 先做成 MIN（同上面的饱和用例）
            (247, "Right", 25),
            (98, "Left", 1),
            (98, "Right", 12),
            (1, "Value", 32767),
            (12, "Value", 32767),
            (25, "Value", (-30000i16) as u16),
            (650, "Dividend", 247),          // 战斗层：{Dividend,Divisor,ZeroPolicy}
            (650, "Divisor", 265),           // 265 = const{-1}
            (1733, "Left", 247),             // run 层：{Left,Right}
            (1733, "Right", 265),
        ]);
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);
        assert_eq!(eval_int(node(&content, 247), &ctx), Ok(i32::MIN));
        assert_eq!(eval_int(node(&content, 650), &ctx), Ok(i32::MAX), "战斗层走 (long) 再饱和");
        assert_eq!(eval_int(node(&content, 1733), &ctx), Err(ExprError::Overflow), "run 层是 int 除法");
    }

    // =========================================================================================
    // 5. 比较：六个操作符 + 两个 run 层别名
    // =========================================================================================

    #[test]
    fn compare_dispatches_every_operator() {
        // 先用纯分派函数把 8 个串逐条验一遍（每个操作符**真、假各一条**，不是空断言）。
        let cases: &[(&str, i32, i32, bool)] = &[
            ("Equal", 2, 2, true),
            ("Equal", 2, 3, false),
            ("NotEqual", 2, 3, true),
            ("NotEqual", 2, 2, false),
            ("Less", 2, 3, true),
            ("Less", 2, 2, false),
            ("LessOrEqual", 2, 2, true),
            ("LessOrEqual", 3, 2, false),
            ("Greater", 3, 2, true),
            ("Greater", 2, 3, false),
            ("GreaterOrEqual", 2, 2, true),
            ("GreaterOrEqual", 2, 3, false),
            // run 层拼写（RunExpressions.cs:486,488）与战斗层同义。
            ("LessThan", 2, 3, true),
            ("LessThan", 2, 2, false),
            ("GreaterThan", 3, 2, true),
            ("GreaterThan", 2, 3, false),
        ];
        for (op, left, right, want) in cases {
            assert_eq!(compare_ints(*left, *right, op), Ok(*want), "{op}({left},{right})");
        }
        // 六个操作符在**同一对操作数**上不能给出同一个答案（否则上表就是空断言）。
        let ops = ["Equal", "NotEqual", "Less", "LessOrEqual", "Greater", "GreaterOrEqual"];
        let results: Vec<bool> = ops
            .iter()
            .map(|op| compare_ints(2, 3, op).expect("六个操作符都必须认得"))
            .collect();
        assert_eq!(results, vec![false, true, true, true, false, false]);
        assert!(results.iter().any(|r| *r) && results.iter().any(|r| !*r));
        // 不认识的串 ⇒ UnsupportedKind（不许当 Equal / false）。
        assert_eq!(compare_ints(2, 3, "LessThanOrEqual"), Err(ExprError::UnsupportedKind));

        // 真实镜像里的 compare：term 322 = compare{statusStacks(eventTarget, signature_pending), Equal, 0}
        // enemy_a 没有 signature_pending ⇒ 0 == 0 ⇒ true。成对：term 319 用 Greater ⇒ false。
        let blob = core_image();
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);
        assert_eq!(eval_bool(node(&content, 322), &ctx), Ok(true), "Equal(0,0)");
        assert_eq!(eval_bool(node(&content, 319), &ctx), Ok(false), "Greater(0,0)");
        assert_eq!(node(&content, 322).str_field("Op"), Ok(Some("Equal")));
        assert_eq!(node(&content, 319).str_field("Op"), Ok(Some("Greater")));

        // `LessThan` 在镜像里只有 1 条（term 1737，run 层）。把它的 Op 槽换到 term 322 上，
        // 端到端证明「线上真的会出现 run 层拼写、而它就是 `<`」。
        let blob = patched(&[(322, "Op", 94)]); // str[94] = "LessThan"（实测串号）
        let content = parse(&blob);
        assert_eq!(node(&content, 322).str_field("Op"), Ok(Some("LessThan")));
        assert_eq!(eval_bool(node(&content, 322), &ctx), Ok(false), "LessThan(0,0)");

        // 不认识的 Op 串（借一个真实存在的串 "paperwork"）⇒ UnsupportedKind。
        let blob = core_image();
        let content_for_id = parse(&blob);
        let paperwork = string_id(&content_for_id, "paperwork");
        let blob = patched(&[(322, "Op", paperwork)]);
        let content = parse(&blob);
        assert_eq!(eval_bool(node(&content, 322), &ctx), Err(ExprError::UnsupportedKind));
    }

    // =========================================================================================
    // 6. 布尔：短路（and / or）
    // =========================================================================================

    #[test]
    fn and_short_circuits_before_touching_a_poisoned_right_branch() {
        // term 959 = and{ compare(witness_the_seal on eventTarget == 0),
        //                 compare(witnessed_this_round on iterationTarget == 0) }
        // 把右支补丁成 term 986（cardsPlayedThisTurn，v1 不支持的**int**表达式）——
        // 右支一旦被求值就必然报 WrongValueKind，于是"有没有短路"变成可观测的。
        let blob = patched(&[(959, "Right", 986)]);
        let content = parse(&blob);
        // enemy_a 的 witness_the_seal = 1 ⇒ 左支 false ⇒ 必须短路成 Ok(false)。
        let state = arena();
        assert_eq!(eval_bool(node(&content, 959), &full_ctx(&state)), Ok(false));

        // 成对反例：enemy_a 身上没有 witness_the_seal ⇒ 左支 true ⇒ 右支真的被求值 ⇒ 报错。
        // （两个状态只差这一条状态实例，别的都一样 —— 所以 Ok(false) 只可能来自短路。）
        let state = arena_with(0, 0);
        let ctx = full_ctx(&state);
        assert_eq!(
            eval_bool(node(&content, 959), &ctx),
            Err(ExprError::WrongValueKind),
            "左支为真时右支必须被求值（否则上一条的 Ok(false) 可能是假的）"
        );
    }

    #[test]
    fn or_short_circuits_before_touching_a_poisoned_right_branch() {
        // term 913 = or{ or{...}, and{...} }；把**左支**补丁成 term 322（compare，支持），
        // **右支**补丁成 term 986（不支持）：
        //   左支 true  ⇒ 短路成 Ok(true)；
        //   左支 false ⇒ 右支被求值 ⇒ Err(UnsupportedKind)。
        // term 322 = compare{statusStacks(eventTarget, "signature_pending"), Equal, 0}。
        let blob = patched(&[(913, "Left", 322), (913, "Right", 986)]);
        let content = parse(&blob);
        // enemy_a 没有 signature_pending ⇒ 0 == 0 ⇒ 左支 true ⇒ 短路。
        let state = arena();
        let ctx = full_ctx(&state);
        assert_eq!(eval_bool(node(&content, 913), &ctx), Ok(true));

        // 成对反例：enemy_a 身上有一条 signature_pending 1 ⇒ 左支 false ⇒ 右支被求值 ⇒ 报错。
        // （右支是把 int 表达式塞进 bool 位置，所以错误是 `WrongValueKind`；
        //   换成 v1 不支持的 int 表达式就是 `UnsupportedKind` —— 两者都证明"真的求值了"。）
        let state = arena_with(1, 1);
        let ctx = full_ctx(&state);
        assert_eq!(
            eval_bool(node(&content, 913), &ctx),
            Err(ExprError::WrongValueKind),
            "左支为假时右支必须被求值"
        );
    }

    // =========================================================================================
    // 7. 值类别 / 非表达式 / 不支持 —— 三种错误必须分得开
    // =========================================================================================

    #[test]
    fn a_bool_in_an_int_slot_is_wrong_value_kind() {
        let blob = core_image();
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);
        // term 959 = and{...} —— 布尔表达式当 Amount 用。
        assert_eq!(eval_int(node(&content, 959), &ctx), Err(ExprError::WrongValueKind));
        // 成对：反过来把一个 int 表达式放进 Condition 位置。
        // term 1 = const{Value:6}。
        assert_eq!(eval_bool(node(&content, 1), &ctx), Err(ExprError::WrongValueKind));
        // 而且这**不是** UnsupportedKind —— 两个变体必须不同。
        assert_ne!(
            eval_int(node(&content, 959), &ctx).unwrap_err(),
            ExprError::UnsupportedKind
        );
    }

    #[test]
    fn a_statement_node_is_not_an_expression() {
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let state = arena();
        let ctx = full_ctx(&state);
        // CARD[0] 的根就是 node.dealDamage。
        let deal_damage = root_of(&ir, 0);
        assert_eq!(eval_int(deal_damage, &ctx), Err(ExprError::NotAnExpression));
        assert_eq!(eval_bool(deal_damage, &ctx), Err(ExprError::NotAnExpression));
        // 成对：它的 Amount 子节点是表达式，能算（6）。
        let amount = deal_damage.node_field("Amount").unwrap().expect("Amount");
        assert_eq!(eval_int(amount, &ctx), Ok(6));
        // node.sequence 也一样（CARD[4] 的根）。
        assert_eq!(eval_int(root_of(&ir, 4), &ctx), Err(ExprError::NotAnExpression));
    }

    #[test]
    fn unsupported_expressions_are_loud_and_never_zero() {
        let blob = core_image();
        let content = parse(&blob);
        let state = arena();
        let ctx = full_ctx(&state);
        // 四处真实实例，各自缺一种上下文：
        //   term 986  = cardsPlayedThisTurn{sel.source}      （每回合出牌统计）
        //   term 354  = eventAmount{}                        （触发事件上下文）
        //   term 1736 = card.upgradeLevel{}                  （卡实例上下文）
        //   term 1542 = fx.heal{Amount:10}                   （run 层节点）
        for (tid, why) in [
            (986u16, "cardsPlayedThisTurn"),
            (354, "eventAmount"),
            (1736, "card.upgradeLevel"),
            (1542, "fx.heal"),
        ] {
            let got = eval_int(node(&content, tid), &ctx);
            assert_eq!(got, Err(ExprError::UnsupportedKind), "term {tid}（{why}）不许给 0");
            assert_ne!(got, Ok(0), "term {tid}（{why}）不许给 0");
        }
        // 它们嵌在别的表达式里也一样（term 987 = compare{cardsPlayedThisTurn, Equal, 1}）。
        assert_eq!(eval_bool(node(&content, 987), &ctx), Err(ExprError::UnsupportedKind));
        // ⚠️ **`currentHealth` / `maxHealth` 不再是这一档**（2026-10-19 改了本文件：
        // 它们实现了，字段名 `Selector` 由我们定，见模块头第 4 条）。这条断言原来写的是
        // `UnsupportedKind`，现在改成**更具体的那种错** —— 真实镜像的 op 28 / op 48
        // `nfields = 0`，所以键缺席 ⇒ `Ir(Missing("Selector"))`（那两条 term 仍然读不出来，
        // 但理由是"没有选择器"而不是"还没实现"）。细节与成对断言见
        // `a_health_read_without_a_selector_is_a_loud_missing_field_error`。
        assert_eq!(
            eval_int(node(&content, 1527), &ctx),
            Err(ExprError::Ir(IrError::Missing("Selector")))
        );
        assert_eq!(
            eval_int(node(&content, 1728), &ctx),
            Err(ExprError::Ir(IrError::Missing("Selector")))
        );
        // `maxHealth*10+99` 这种外层树仍然**不许**悄悄变成 99（那正是猜错的形状）：
        // 错误从被乘数一路冒上来，而不是被"某个默认值"盖掉。
        assert_eq!(
            eval_int(node(&content, 1731), &ctx),
            Err(ExprError::Ir(IrError::Missing("Selector")))
        );
        assert_ne!(eval_int(node(&content, 1731), &ctx), Ok(99));
    }

    // =========================================================================================
    // 8. 全镜像扫描：v1 的表达式覆盖率
    //
    // 遍历 2,143 条 term，把每一个**是表达式**的求一遍，按 kind 统计
    // 成功 / UnsupportedKind / 其它错误。这条测试的价值是"覆盖率是一张表，不是一句感觉"。
    // =========================================================================================

    /// 这个 kind 是不是**层内的语句/选择器**（`node.*` 效果节点、`fx.*`/`reward.*`/`meta.*`/
    /// `tpl.*` 的 run 层动作、`sel.*` 选择器）。
    ///
    /// 这些不是"数值位置"，扫描时跳过；但**单独当表达式调用**仍然要报错
    /// （`node.*` ⇒ `NotAnExpression`，其余 ⇒ `UnsupportedKind`，见另外两条测试）。
    fn is_statement_or_selector(kind: &str) -> bool {
        ["node.", "fx.", "reward.", "meta.", "tpl.", "sel."]
            .iter()
            .any(|prefix| kind.starts_with(prefix))
    }

    #[test]
    fn the_whole_core_image_scan_reports_expression_coverage() {
        let blob = core_image();
        let content = parse(&blob);
        let state = arena();
        let hero = cid("hero");
        let ctx = ExprContext {
            state: &state,
            source: Some(hero),
            event_target: Some(cid("enemy_a")),
            iteration_target: Some(cid("enemy_b")),
            iteration_card: None,
        };

        // kind → (成功, UnsupportedKind, 其它错误)
        let mut rows: Vec<(&str, u32, u32, u32)> = Vec::new();
        let mut others: Vec<(u16, &str, ExprError)> = Vec::new();
        let (mut total, mut ok, mut unsupported, mut other) = (0u32, 0u32, 0u32, 0u32);
        let mut skipped_statement = 0u32;
        let mut skipped_unreadable = 0u32;
        // 卡实例表达式单独计数：它们**是**表达式，只是不在这条"标量求值"扫描里。
        // 混进 `skipped_statement` 会让报告读起来像"这些 term 是语句"。
        let mut skipped_card = 0u32;

        for tid in 0..content.term_count() {
            let Ok(id) = u16::try_from(tid) else { continue };
            let this = node(&content, id);
            let Ok(kind) = this.kind_str() else {
                skipped_unreadable += 1; // `_null` / `_arr` / 普通对象：本来就没有 kind
                continue;
            };
            if is_statement_or_selector(kind) {
                skipped_statement += 1;
                continue;
            }
            let result: Result<bool, ExprError> = match classify(kind) {
                Class::NotAnExpression => {
                    skipped_statement += 1;
                    continue;
                }
                Class::Bool => eval_bool(this, &ctx),
                Class::Int | Class::Unknown => eval_int(this, &ctx).map(|v| v != 0),
                // 卡实例表达式**不在这里**求值：这条扫描问的是"能不能当标量读"。
                // 把它算成 int 会让覆盖率的数字比实际能力大一号。
                Class::Card => {
                    skipped_card += 1;
                    continue;
                }
            };
            total += 1;
            let slot = match rows.iter().position(|r| r.0 == kind) {
                Some(i) => i,
                None => {
                    rows.push((kind, 0, 0, 0));
                    rows.len() - 1
                }
            };
            match result {
                Ok(_) => {
                    ok += 1;
                    rows[slot].1 += 1;
                }
                Err(ExprError::UnsupportedKind) => {
                    unsupported += 1;
                    rows[slot].2 += 1;
                }
                Err(e) => {
                    other += 1;
                    rows[slot].3 += 1;
                    others.push((id, kind, e));
                }
            }
        }

        rows.sort_by(|a, b| a.0.cmp(b.0));
        std::println!("=== 全镜像表达式扫描（{} 条 term）===", content.term_count());
        std::println!(
            "候选表达式 {total}：成功 {ok} / UnsupportedKind {unsupported} / 其它错误 {other}\
             \n跳过：语句或选择器 {skipped_statement}、无 kind {skipped_unreadable}、\
             卡实例表达式 {skipped_card}"
        );
        std::println!("{:<32} {:>4} {:>6} {:>6} {:>6}", "kind", "count", "ok", "unsup", "other");
        for (kind, o, u, e) in &rows {
            std::println!("{:<32} {:>4} {:>6} {:>6} {:>6}", kind, o + u + e, o, u, e);
        }
        for (tid, kind, err) in &others {
            std::println!("  其它错误：term {tid} {kind} → {err:?}");
        }

        // ---- 实测数字（一次跑出来后写死在这里，写错了就红）----
        assert_eq!(content.term_count(), 2143, "镜像的 term 总数");
        // 171 → 170：`cardInstance.iterated`（t152）从"标量候选"里**移出去了**，
        // 因为它的值域是卡实例而不是 int（见 `CARD_KINDS`）。它不是"不再被扫"，
        // 而是被 `skipped_card` 单独计数 —— 下面这条断言就是在钉这件事。
        assert_eq!(total, 170, "候选表达式条数（去重后的 term 条数）");
        assert_eq!(ok, 117, "v1 求得出值的");
        // 53 → 40：`currentHealth`(t1527) 与 `maxHealth`(t1728) 不再是 `UnsupportedKind`
        // （它们实现了，只是**这份内容**里没有 `Selector` 字段），它们的 11 个祖先也跟着变了
        // —— 见下面那条 id 清单。
        assert_eq!(unsupported, 40, "UnsupportedKind（见上面的按 kind 分布）");
        // 0 → 13：**两片叶子 + 它们的 11 个祖先**。这条断言的价值是把"其它错误"从 0 变成
        // **一个可以逐条念出来的清单**：
        //   * 叶子：1527 `currentHealth`、1728 `maxHealth`（`nfields = 0` ⇒ 缺 `Selector`）；
        //   * 祖先：1528 `subtract` → 1529 `min`（作用于 1527），1729 `multiply` → 1731 `add`
        //     → 1733 `divide`（作用于 1728），以及另外三处 `min`（1707/1721/1867）和
        //     1858/1859/1860（1731 那个形状的第二份拷贝）。
        // 换句话说：**错误一路冒到树顶**，没有任何一层把它盖成 0 或默认值 —— 这正是要的。
        // 将来多出第十四条 ⇒ 红，逼人先决定它是哪一种（而不是让它混进计数里）。
        assert_eq!(other, 13, "其它错误只允许是那 13 条缺 Selector 的树");
        for (tid, kind, err) in &others {
            assert_eq!(
                *err,
                ExprError::Ir(IrError::Missing("Selector")),
                "term {tid}（{kind}）的错必须是缺 `Selector` —— 不是别的结构错"
            );
        }
        let error_ids: Vec<u16> = others.iter().map(|(tid, _, _)| *tid).collect();
        assert_eq!(
            error_ids,
            vec![1527u16, 1528, 1529, 1707, 1721, 1728, 1729, 1731, 1733, 1858, 1859, 1860, 1867],
            "`roguedeck` 这份镜像里，缺 `Selector` 只可能有这 13 条 term（2 片叶子 + 11 个祖先）"
        );
        // 少掉的那一条必须恰好落在"卡实例表达式"这一格里，而不是凭空蒸发。
        assert_eq!(skipped_card, 1, "镜像里只有 t152 一种是卡实例表达式");
        assert_eq!(total + skipped_card, 171, "两条账加起来必须还是 171");
    }

    #[test]
    fn the_iterated_card_expression_reads_the_bound_slot_and_refuses_to_guess() {
        // 镜像里唯一的卡实例表达式是 t152 `cardInstance.iterated`（0 字段，`trecon:236`）。
        let blob = core_image();
        let content = parse(&blob);
        let iterated = node(&content, 152);
        assert_eq!(iterated.kind_str().unwrap(), "cardInstance.iterated");
        let state = arena();
        let card = CardInstanceId::new("card_000007").unwrap();

        // ---- 正例：绑了谁就返回谁 ----
        let bound = ExprContext {
            state: &state,
            source: Some(cid("hero")),
            event_target: None,
            iteration_target: None,
            iteration_card: Some(card),
        };
        assert_eq!(eval_card(iterated, &bound), Ok(card));

        // ---- 反例一：没有绑定 ⇒ NoTarget，**不是**一个空卡 id ----
        // 给空 id 会让 `moveCardToZone` 去找一张不存在的卡并静默不动 ——
        // 那是最坏的一种"通过"。
        let unbound = ExprContext {
            iteration_card: None,
            ..bound
        };
        assert_eq!(eval_card(iterated, &unbound), Err(ExprError::NoTarget));
        assert_ne!(
            eval_card(iterated, &unbound),
            Ok(CardInstanceId::EMPTY),
            "绝不允许用空 id 冒充'没有迭代卡'"
        );

        // ---- 反例二：值类别必须分得开 ----
        // 它是卡、不是 int ⇒ `eval_int` 报 `WrongValueKind`（问错了问题），
        // 而不是 `UnsupportedKind`（还没实现）。这两者的处置完全不同。
        assert_eq!(eval_int(iterated, &bound), Err(ExprError::WrongValueKind));
        assert_eq!(eval_bool(iterated, &bound), Err(ExprError::WrongValueKind));
        // 反过来：int 表达式当卡读，也是 `WrongValueKind`。
        let constant = node(&content, 12); // t12 = const 8
        assert_eq!(constant.kind_str().unwrap(), "const");
        assert_eq!(eval_card(constant, &bound), Err(ExprError::WrongValueKind));
        // 语句节点当卡读 ⇒ `NotAnExpression`，和当 int 读是同一个答案。
        let statement = node(&content, 266); // t266 = modifyStatusStacks
        assert_eq!(eval_card(statement, &bound), Err(ExprError::NotAnExpression));
        assert_eq!(eval_int(statement, &bound), Err(ExprError::NotAnExpression));
    }
}
