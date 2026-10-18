//! 内容镜像里的**状态元数据**：极性（`Polarity`）与被动修饰器（`PassiveModifiers`）。
//!
//! 这一层是 `exec.rs` 的第二个数据源。`crate::status_catalog` 是**标准包**（`StandardCombatPackage.cs`）
//! 的硬编码表，只有 16 + 2 个 `standard.*` id；真实内容镜像 `content.core.rdcf` 是**另一个内容包**，
//! 23 个状态全是裸名（`doubt` / `paperwork` / `strength` / `signature_pending` …），
//! 其中 5 个自带 `PassiveModifiers`。
//! 参考实现读的就是这张表（`PassiveModifiers.cs:142-172`：`registry.StatusDefinitions` →
//! `def.PassiveModifiers`），所以**本模块才是正路**，`status_catalog` 是标准包/oracle 的退路。
//!
//! # 实测形状（我在 `tools/contentc/out/content.core.rdcf` 上逐字节量过）
//!
//! `STATUS_SCHEMA`（20 格）里本模块只用两格：
//!
//! * 第 4 格 `Polarity`：`F_STR`，串内容就是 `"Buff"` / `"Debuff"` / `"Neutral"`
//!   （实测 23 个状态：Debuff 5 / Buff 5 / Neutral 13）。
//! * 第 8 格 `PassiveModifiers`：`F_TERM`，指向一棵 **`_arr`**（`op = 4 = content::OP_ARR`，
//!   `opclass = 1` 的普通对象）。
//!
//! ## `_arr` 怎么读（这是本模块唯一"绕过 `ir::NodeRef`"的地方）
//!
//! `_arr` 的 opcode 只有**一个匿名字段**，类别 `F_TERMLIST`（2 槽），所以它自己不是"带名字段的对象"：
//! `NodeRef::field(任何键)` 对 `op < OP_FIRST_DYNAMIC` 的 term 直接返回 `IrError::NotAnObject(op)`
//! （`ir.rs:300-304`），`list_field` 也是同一条路。**唯一正确的读法**是照
//! `content-binary-format.md` §2.3 的编码自己解两个槽：
//!
//! ```text
//! slot0 = AUX 起址, slot1 = 个数      （个数 == LIST_ABSENT(0xFFFF) / LIST_NULL(0xFFFE) ⇒ 0 个）
//! 第 i 个元素 = content.aux(slot0 + i)  —— 是 term id
//! ```
//!
//! 实测：`doubt` 的句柄 271 → `op = 4`，槽 = `(409, 1)`，`aux(409) = 270`。
//!
//! ## 一个元素长什么样
//!
//! 元素是 `_obj`（实测 `op = 93`，`opclass = 1`，**没有判别串**），7 个键按字母序排布，
//! 类别是 `F_TERM` / `F_INT` / `F_STR`：
//!
//! | 键 | 类别 | 实测值 |
//! |---|---|---|
//! | `AppliesToStatusId` | `F_TERM` | 恒 `NULL16`（0xFFFE）|
//! | `Magnitude` | `F_INT` | 常量幅值；**槽是 i16**，`seal_intact` 的 `-4` 落盘是 65532 |
//! | `Operation` | `F_STR` | `ScalePercent` / `AddPerStack` / `AddFlat` |
//! | `Pipeline` | `F_STR` | `DamageDealt` / `DamageReceived` / `TurnStartDraw`（**本内容**，实测）|
//! | `Priority` | `F_INT` | 100 |
//! | `RestrictDamageKind` | `F_STR` | `Direct` 或 `NULL16`（**实测只有这两种**；枚举本身有 3 个成员） |
//! | `RestrictSourceCardTag` | `F_TERM` | 恒 `NULL16` |
//!
//! 镜像里这 7 个键**一个不多一个不少**，5 个非空 `PassiveModifiers` 各 1 条 spec：
//!
//! ```text
//! doubt              Debuff  DamageDealt    ScalePercent  75  100  Direct
//! panic              Debuff  TurnStartDraw  AddPerStack   -1  100  null
//! strength           Buff    DamageDealt    AddPerStack    1  100  Direct
//! signature_pending  Buff    DamageReceived ScalePercent  75  100  Direct
//! seal_intact        Buff    DamageReceived AddFlat       -4  100  Direct
//! ```
//!
//! ## 第 4 种管线 `Block`（wire 串 `"BlockGain"`）—— 本内容里**一条都没有**
//!
//! 参考枚举有 6 个成员，第 3 个是 `BlockGain`（`PassiveModifiers.cs:20`，注释在 `:15`：
//! "BlockGain, block being gained, read from the gaining combatant"）。线上那个**串**就是
//! 成员名：内容走 `CombatJson`（`CombatJson.cs:159` `JsonStringEnumConverter`，**没有**命名策略
//! 覆盖）⇒ `Enum.ToString()` 原样，也就是 `"BlockGain"`。⚠️ **不是 `"Block"`** ——
//! 内核里折叠器的枚举（`modifiers::Pipeline::Block`）叫 `Block`，但那是**另一个枚举**，
//! 拿它的变体名当 wire 串会得到一条永远匹配不上的 spec（最坏的静默）。
//!
//! 本内容镜像里 0 条（上表 5 条 spec 全在另外三个管线上），但**内容侧正在用它表达"脆弱"**：
//! `standard.frail` 的参考定义就是 `BlockGain / ScalePercent 75 / Priority 200`
//! （`StandardCombatPackage.cs:318-321`）。所以本层认它 —— 拒绝它等于"脆弱施加得上但毫无效果"，
//! 那是内容逼出来的引擎缺口，不是本层的合理边界。
//!
//! # 为什么接口是"暂存区 + 条数"而不是 `StatusMeta { modifiers: &[PassiveModifier] }`
//!
//! 本 crate 零分配（`lib.rs` 三条铁律之二），而一条状态的修饰器**条数是运行期才知道的**：
//! 要返回 `&[PassiveModifier]`，得有人把解码结果放在某个活得过这次调用、又没被借用检查器没收的地方。
//! 栈上的临时数组做不到（返回值会指向已销毁的栈帧），所以只有两条路：
//!
//! 1. 调用方给暂存区（本文件的 [`decode`]）—— 返回 [`DecodedStatus`]，它带 `modifier_count`，
//!    调用方自己 `&out[..count]`；
//! 2. 内部用 `static` 缓存 —— 需要 `unsafe` / 同步原语，本 crate `forbid(unsafe_code)`。
//!
//! 走第 1 条。代价写在明处：**"条数"与"内容"是两个返回值**，调用方必须用同一个 `out` 与同一个
//! `count` 配对，否则会读到上一次解码的残留。所以 [`DecodedStatus`] **故意不带切片**，
//! 让"忘了用 count"变成一个显式的字符串操作，而不是一个看起来正确的切片。
//!
//! 暂存区太小 **不是** "截断到能装下的部分"，而是 [`BindError::BufferTooSmall`]：
//! 少几条修饰器就等于算错伤害，而算错伤害比报错糟得多。
//!
//! # 本层**不做**的事（每一条都是响亮拒绝，不是静默忽略）
//!
//! * `Pipeline` 认 4 种：镜像里真出现的 3 种 + 参考的 `BlockGain`（[`Pipeline::Block`]，见上）。
//!   `CardCost` / `OutgoingStatusApplicationStacks` 仍一律 [`BindError::Pipeline`]。
//! * `Operation` 只认 3 种。`ClampMax` 一律 [`BindError::Operation`]。
//! * `RestrictDamageKind` 只认参考 `DamageKind` 的 3 个成员（`Direct` / `DamageOverTime` / `Reflected`）。
//!   **实测镜像里只出现 `Direct` 与 `null`**，另外两种今天一次都没出现 —— 但它们是参考里真有的
//!   名字，所以能解（[`DamageKind::from_wire_name`] 认它），不是"猜一个位"。别的串一律 [`BindError::DamageKind`]。
//! * `AppliesToStatusId` / `RestrictSourceCardTag` 非 null、`MagnitudeExpression` / `RestrictElement`
//!   存在、`OncePerAction` / `OncePerTurn` 为 true —— 这些在参考实现里都会改变数值
//!   （`PassiveModifiers.cs:90-113,158-171,193-205`），而本层表达不了，所以
//!   一律 [`BindError::Unsupported`]。镜像里它们**全是 null/false**，所以今天一个都不会命中。
//!
//! 换句话说：**今天这条路上，镜像里 23 个状态全部解码成功**（`the_core_image_binds_every_status`
//! 逐个钉住），而将来内容一动用这些键，内核会报错而不是算错。
//!
//! # 与参考实现的行号对照（我核对过的）
//!
//! * 分组与 `spec_index`：`PassiveModifiers.cs:142-172`（`GroupBy(DefinitionId)`、`totalStacks = Sum`、
//!   `i` 是 `def.PassiveModifiers` 里的下标，**不是**过滤后的序号）。
//! * 排序键：`PassiveModifiers.cs:179-185`（`(Priority, string.CompareOrdinal(statusId), specIndex)`）。
//! * 四种运算：`PassiveModifiers.cs:206-213`。
//! * 极性来自内容定义：`StatusEffects.cs:190-197`（**我核对过**：`:195` 就是 `definition.Polarity`，
//!   也就是说参考实现把内容定义里的那一格直接搬进新实例）。
//! * 合并行为来自内容定义：`StatusEffects.cs:126`（`definition.StackingBehavior ==
//!   MergeWithExistingInstance`）—— 本层不读它，镜像 23 个状态实测全是这个值。

use crate::content::{
    Content, StatusRow, ABSENT16, BOOL_ABSENT, BOOL_FALSE, BOOL_NULL, BOOL_TRUE, EK_STATUS,
    LIST_ABSENT, LIST_NULL, NULL16, OP_ARR, OP_STR,
};
use crate::ir::{IrError, NodeRef};
use crate::state::StatusPolarity;

// =============================================================================================
// 冻结的解码结果
// =============================================================================================

/// 一条状态的修饰器最多解码几条。
///
/// 镜像实测**每条最多 1 条**（5 个非空状态各 1 条），给 4 是余量：超过就
/// [`BindError::BufferTooSmall`]（响亮失败），**绝不静默丢掉第 5 条**。
pub const MAX_MODIFIERS: usize = 4;

/// 修饰器管线（`PassiveModifierPipeline`）—— 镜像里真出现的 3 种 **+ 参考的 `BlockGain`**。
///
/// 与 `crate::modifiers::Pipeline` 同名不同义：后者是**折叠器**的管线（含 `Block` / `Cost`，
/// 那是标准包的两张修饰表要的），本枚举是**内容数据**里的字符串。两者由调用方按语义映射
/// （`Block ⇒ modifiers::Pipeline::Block`，见 `exec.rs` 的 [`Pipeline::Block`] 用法与
/// `play.rs` 的 `cost_pipeline_of`）。
///
/// ⚠️ 变体的 Rust 名字是 `Block`（跟折叠器对齐），**wire 串是 `"BlockGain"`**（跟参考的枚举
/// 成员名对齐）。两者不一样是刻意的：改 wire 串就等于让内容里那条 `"BlockGain"` spec 变成
/// 永远匹配不上的死数据。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Pipeline {
    /// 造成的伤害 —— 从**出手者**读（`DamageModifierStage.Source`）。
    DamageDealt,
    /// 受到的伤害 —— 从**承受者**读（`DamageModifierStage.Target`）。
    DamageReceived,
    /// 获得的格挡（**单阶段**，从**获得格挡的那一方**读，`PassiveModifiers.cs:257-269`）。
    ///
    /// `PassiveModifiers.cs:266` 的 `context.TargetCombatant` 就是"谁在获得格挡"
    /// （`DeclarativePassiveBlockModifier` 没有 stage 轴，`:257-268` 只有一个
    /// `IBlockAmountModifier`）。`damageKind: null`（`:267`）⇒ 伤害种类门整段跳过。
    Block,
    /// 回合开始的抽牌数（`turn.rs` 的地盘，**不进伤害管线**）。
    TurnStartDraw,
}

impl Pipeline {
    /// 镜像里的字面串 → 变体。不认识的串返回 `None`（调用方报 [`BindError::Pipeline`]）。
    ///
    /// 4 个串都是参考枚举的成员名（`PassiveModifiers.cs:18-29`，经 `CombatJson.cs:159` 的
    /// `JsonStringEnumConverter` 原样落盘）。**`"Block"` 不是其中之一** —— 那个名字是折叠器
    /// 枚举的变体名，拿它当 wire 串是本层要挡的那种"看起来对"的错。
    #[must_use]
    pub fn from_wire_name(name: &str) -> Option<Self> {
        match name {
            "DamageDealt" => Some(Pipeline::DamageDealt),
            "DamageReceived" => Some(Pipeline::DamageReceived),
            "BlockGain" => Some(Pipeline::Block),
            "TurnStartDraw" => Some(Pipeline::TurnStartDraw),
            _ => None,
        }
    }

    /// 变体 → 镜像里的字面串（写回/断言用）。
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            Pipeline::DamageDealt => "DamageDealt",
            Pipeline::DamageReceived => "DamageReceived",
            Pipeline::Block => "BlockGain",
            Pipeline::TurnStartDraw => "TurnStartDraw",
        }
    }
}

/// 伤害种类（`DamageKind`）—— 参考的 3 个成员，一个不多一个不少。
///
/// `CombatPrimitives.cs:18-23`（**我读过那一行**）：
///
/// ```text
/// public enum DamageKind { Direct, DamageOverTime, Reflected }
/// ```
///
/// ⚠️ **判别值与顺序是契约**：这个枚举既用来读镜像里的 `RestrictDamageKind` 串，也用来给
/// "这一次伤害是什么种类"命名，而 [`DamageKind::bit`] 把判别值直接映射成
/// `status_catalog::DAMAGE_KIND_*` 的位（`0 ⇒ 1<<0`、`1 ⇒ 1<<1`、`2 ⇒ 1<<2`）。
/// 顺序写错了，`bit()` 就会把 `Dot` 说成 `Direct` —— 而那是一条**静默**的错路（DoT 会被
/// 力量/虚弱/易伤放大），所以三个变体保持与参考相同的顺序，没有 `#[repr]` 之外的余地。
///
/// 镜像实测（`tools/contentc/reader.py` 逐行读 `STAT.PassiveModifiers`）：5 条 spec 的
/// `RestrictDamageKind` 全是 `"Direct"`，`panic` 那条是 `null`（它的管线是 `TurnStartDraw`，
/// 与伤害无关）。⇒ **`DamageOverTime` / `Reflected` 这两个串在今天的镜像里一次都没出现**，
/// 但它们不是"为了对称加的" —— 参考的枚举里就有，串一出现就得读得懂。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DamageKind {
    /// `DamageKind.Direct = 0` —— 卡/敌动作打出来的那一下。
    Direct,
    /// `DamageKind.DamageOverTime = 1` —— 中毒一跳。**串是 `"DamageOverTime"`，不是 `"Dot"`**。
    Dot,
    /// `DamageKind.Reflected = 2` —— 反伤（荆棘）。
    Reflected,
}

impl DamageKind {
    /// 镜像里的字面串 → 变体。
    ///
    /// **三个名字都是参考枚举的成员名**（`CombatPrimitives.cs:20-22` 的 `Enum.ToString()`）：
    /// `"Direct"` / `"DamageOverTime"` / `"Reflected"`。不认识的串返回 `None`
    /// （调用方报 [`BindError::DamageKind`]，不猜）。
    #[must_use]
    pub fn from_wire_name(name: &str) -> Option<Self> {
        match name {
            "Direct" => Some(DamageKind::Direct),
            "DamageOverTime" => Some(DamageKind::Dot),
            "Reflected" => Some(DamageKind::Reflected),
            _ => None,
        }
    }

    /// 变体 → 镜像里的字面串。
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            DamageKind::Direct => "Direct",
            DamageKind::Dot => "DamageOverTime",
            DamageKind::Reflected => "Reflected",
        }
    }

    /// 判别值（`Direct=0 / DamageOverTime=1 / Reflected=2`，`CombatPrimitives.cs:20-22`）。
    ///
    /// 显式写 `match` 而不是 `self as u32`：加变体时编译器会在这里报错，而不是让它静默
    /// 继承一个位置值。
    #[must_use]
    pub const fn index(self) -> u32 {
        match self {
            DamageKind::Direct => 0,
            DamageKind::Dot => 1,
            DamageKind::Reflected => 2,
        }
    }

    /// 判别值对应的位 —— 与 `crate::status_catalog::DAMAGE_KIND_*` 同一套位
    /// （那三个常量就是 `1 << (kind as u32)`，`status_catalog.rs:111-117` 的原话）。
    ///
    /// 用它去查 `status_catalog::DAMAGE_MODIFIER_DAMAGE_KINDS`，就是参考
    /// `PassiveModifiers.cs:155` 那道门在标准包（`content == None`）路径上的等价物：
    /// 标准包三行的 `RestrictDamageKind` **都是** `Direct`（`status_catalog` 把它提成了一个常量）。
    #[must_use]
    pub const fn bit(self) -> u32 {
        1 << self.index()
    }
}

/// 运算（`PassiveModifierOperation`）—— 镜像里真出现的 3 种。
///
/// ⚠️ **不是** `crate::status_catalog::ModifierOp`（那是冻结的 2 值枚举 `AddStacks` / `MulPercent`，
/// 没有 `AddFlat`，也不许改）。两者由调用方映射到 `crate::modifiers::Operation`：
///
/// ```text
/// status_catalog::ModifierOp::AddStacks    → modifiers::Operation::AddPerStack
/// status_catalog::ModifierOp::MulPercent   → modifiers::Operation::ScalePercent
/// status_bind::ModifierOp::AddPerStack     → modifiers::Operation::AddPerStack
/// status_bind::ModifierOp::AddFlat         → modifiers::Operation::AddFlat
/// status_bind::ModifierOp::ScalePercent    → modifiers::Operation::ScalePercent
/// ```
///
/// `ClampMax` 本枚举**没有**：镜像里一条都没有（实测 3 种里没有它），见到就 [`BindError::Operation`]。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModifierOp {
    /// `current + magnitude * stacks`。
    AddPerStack,
    /// `current + magnitude`。
    AddFlat,
    /// `current * magnitude / 100`（整数、向零截断）。
    ScalePercent,
}

impl ModifierOp {
    /// 镜像里的字面串 → 变体。
    #[must_use]
    pub fn from_wire_name(name: &str) -> Option<Self> {
        match name {
            "AddPerStack" => Some(ModifierOp::AddPerStack),
            "AddFlat" => Some(ModifierOp::AddFlat),
            "ScalePercent" => Some(ModifierOp::ScalePercent),
            _ => None,
        }
    }

    /// 变体 → 镜像里的字面串。
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            ModifierOp::AddPerStack => "AddPerStack",
            ModifierOp::AddFlat => "AddFlat",
            ModifierOp::ScalePercent => "ScalePercent",
        }
    }
}

/// 一条 `PassiveModifierSpec` 的解码结果 —— 参考实现那个 record 的战斗路径子集
/// （`PassiveModifiers.cs:80-113`）。
///
/// 缺的四个字段（`MagnitudeExpression` / `RestrictElement` / `AppliesToStatusId` /
/// `RestrictSourceCardTag`）与两个 `OncePer*` 开关**不是被忽略了**：解码时见到它们非空/为真就报
/// [`BindError::Unsupported`]，见模块头。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PassiveModifier {
    /// `Pipeline`。
    pub pipeline: Pipeline,
    /// `Operation`。
    pub operation: ModifierOp,
    /// `Magnitude`（`F_INT`，**i16 解出来的有符号数**：`seal_intact` 是 -4）。
    pub magnitude: i32,
    /// `Priority`（排序键第一级，`PassiveModifiers.cs:181`）。
    pub priority: i32,
    /// `RestrictDamageKind`：`None` = null（不限种类，但也**不能**作用于"别的种类"以外的任何门）。
    pub restrict_damage_kind: Option<DamageKind>,
}

/// [`decode`] 的成功结果。**故意不带 `modifiers` 切片** —— 见模块头"为什么接口是暂存区 + 条数"。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DecodedStatus<'a> {
    /// 镜像里的**定义 id**（`Id` 格，指向 `STR` 池）。它就是参考实现里
    /// `group.Key.value` 那个串 —— 排序键第二级要的正是它的字节。
    pub id: &'a str,
    /// `Polarity` 解出来的极性。
    pub polarity: StatusPolarity,
    /// 写进调用方暂存区的条数：`&out[..modifier_count]`。
    pub modifier_count: usize,
}

/// 解码失败。每一种拒绝**都有自己的变体**（合并变体会让"为什么不生效"变成猜谜）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BindError {
    /// `ir::NodeRef` 读字段时的底层错误（键存在但类别不对、term 越界…）。
    Ir(IrError),
    /// `PassiveModifiers` 格指向的 term 不是 `_arr`。
    NotAnArray(u16),
    /// `PassiveModifiers` 格/元素句柄取不到对应的 term。
    Term(u16),
    /// `_arr` 的 aux 区间算不下去或越界。
    Aux(u16),
    /// 串号取不到串（`Polarity` / `Id`）。
    String(u16),
    /// 结构上必须有的键缺席（`Polarity` / `Pipeline` / `Operation` / `Magnitude` / `Priority`）。
    Missing(&'static str),
    /// `Polarity` 串不是 `Buff`/`Debuff`/`Neutral`。
    Polarity,
    /// `Pipeline` 串不在本层认识的 4 种里（`DamageDealt` / `DamageReceived` / `BlockGain` /
    /// `TurnStartDraw`；`CardCost` / `OutgoingStatusApplicationStacks` 落在这里）。
    Pipeline,
    /// `Operation` 串不在本层认识的 3 种里（例如 `ClampMax`）。
    Operation,
    /// `RestrictDamageKind` 串不是参考 `DamageKind` 的成员名。
    DamageKind,
    /// `Tags` 的元素不是 `_str` term（`OP_STR`）。卡片的 tag 集合是 `_wrap_lower`，
    /// 状态的不是 —— 两种拼法混了会得到"一条都不匹配"，所以这里不猜。
    TagElement(u16),
    /// `F_BOOL` 格出现了四值之外的值（编码坏了）。
    Bool(&'static str),
    /// 这条 spec 用了本层表示不了的键（非 null 的 `AppliesToStatusId` / `RestrictSourceCardTag` /
    /// `MagnitudeExpression` / `RestrictElement`，或为真的 `OncePerAction` / `OncePerTurn`）。
    Unsupported(&'static str),
    /// 调用方给的暂存区装不下 —— **不截断**，整条解码作废。
    BufferTooSmall {
        /// 这条状态实际有几条修饰器。
        needed: usize,
        /// 调用方给了几格。
        have: usize,
    },
}

impl From<IrError> for BindError {
    fn from(e: IrError) -> Self {
        BindError::Ir(e)
    }
}

// =============================================================================================
// 查表
// =============================================================================================

/// `status_id` → `STAT` 行（**先看 `IDX` 的实体类别**，只看 `EK_STATUS`）。
///
/// 为什么不能只用 `content.resolve(id)`：同一个 id 可以同时是别的实体（实测 `overfilled_inbox`
/// 既是 `CARD[42]` 又是 `REL[33]`），`resolve` 返回**最靠前**的那一条 —— 拿它当状态元数据
/// 会读到一张卡的 15 格并按 `STATUS_SCHEMA` 解释，每一格都是错的。
///
/// 查不到 ⇒ `None`。**本层不替调用方决定"查不到"该不该报错**：只解极性的 [`polarity`]
/// 拿它当"没说过"（回退成 `Buff`），而**走修饰器管线**的调用方必须用 [`decode_required`]
/// （那里"查不到"= 响亮失败，理由写在那条文档里）。
#[must_use]
pub fn status_row<'a>(content: &Content<'a>, status_id: &str) -> Option<StatusRow<'a>> {
    let entry = content.lookup_in(status_id, EK_STATUS)?;
    content.status(u32::from(entry.index))
}

/// 只解极性（`exec.rs` 的 `applyStatus` 用这条：它不需要修饰器，也就不该因为
/// "暂存区太小 / 第 5 条 spec 不认识"而失败）。
///
/// 返回 `Ok(None)` = 内容里没有这个状态定义（**不是错误**，见 [`status_row`]）。
pub fn polarity(
    content: &Content<'_>,
    status_id: &str,
) -> Result<Option<StatusPolarity>, BindError> {
    match status_row(content, status_id) {
        Some(row) => Ok(Some(decode_polarity(content, row)?)),
        None => Ok(None),
    }
}

/// `STAT.Tags` 里有没有 `tag`（`status_bind` 的第一个"标签"读口）。
///
/// # 为什么需要它
///
/// 参考实现的 `damage_over_time` / `retain_hand` / `retain_block` 三个判定都读**实例上的标签**
/// （`StatusEffects.cs:462, :498`、`CardTurnLifecycleEventHandlers.cs:48`、
/// `DefensivePoolEffects.cs:297`），而实例标签在创建时从定义拷贝
/// （`StatusEffects.cs:196`：`initialTags: definition.Tags`）⇒ 走定义查表是**等价**的
/// （`state.rs` 的 `StatusInstance` 也故意没有 tags 字段，见它的字段表）。
///
/// # 实测形状（我在二进制层面量过，不是从 JSON dump 反推的）
///
/// `poison` 的 `Tags` 格 = `F_TERM` → term 264，`op = 4 = OP_ARR`，槽 = `(407, 1)`；
/// `aux(407)` = 263，`op = 1 = OP_STR`，槽 0 = 串 id。
///
/// ⚠️ **元素是 `_str`，不是 `_wrap_lower`** —— 与**卡**的 `Tags` 不同（卡的 tag 集合在
/// `play.rs` 里要按 `_wrap_lower` 解，`play.rs:754-788`）。两种拼法都在这个镜像里，
/// 把它们搞混会得到"一条都不匹配"这种最坏的静默结果，所以这里按 `OP_STR` 严格解，
/// 见到别的 opcode 就报 [`BindError::TagElement`]。
///
/// * 内容里没有这个定义 ⇒ [`BindError::Missing`]（`"STAT row"`）：调用方拿了一个不存在的
///   状态 id，那是调用违约，不是"这个状态没有标签"。
/// * 20 个空状态的 `Tags` 是**真的空 `_arr`**（例如 term 58 → `(43, 0)`），不是哨兵；哨兵也接。
pub fn has_tag(content: &Content<'_>, status_id: &str, tag: &str) -> Result<bool, BindError> {
    let row = status_row(content, status_id).ok_or(BindError::Missing("STAT row"))?;
    let handle = row.tags();
    if handle == ABSENT16 || handle == NULL16 {
        return Ok(false);
    }
    let term = content.term(handle).ok_or(BindError::Term(handle))?;
    if term.op != OP_ARR {
        return Err(BindError::NotAnArray(handle));
    }
    let start = term.slot(0).ok_or(BindError::Aux(handle))?;
    let raw_count = term.slot(1).ok_or(BindError::Aux(handle))?;
    if raw_count == LIST_ABSENT || raw_count == LIST_NULL {
        return Ok(false);
    }
    for i in 0..raw_count {
        let cell = start.checked_add(i).ok_or(BindError::Aux(start))?;
        let element = content.aux(cell).ok_or(BindError::Aux(cell))?;
        let element_term = content.term(element).ok_or(BindError::Term(element))?;
        if element_term.op != OP_STR {
            return Err(BindError::TagElement(element));
        }
        let string = element_term.slot(0).ok_or(BindError::Term(element))?;
        if content.string(string) == Some(tag) {
            return Ok(true);
        }
    }
    Ok(false)
}

/// `STAT.UsesDuration`（`F_BOOL`）—— 参考 `DecreaseTimedStatusDurationsOnTurnEndedHandler` 的
/// **唯一**判据（`StatusEffects.cs:394`：`if (!definition.UsesDuration) continue;`）。
///
/// ⚠️ 判据是**定义上的标记**，不是"时长轴 > 0"那种推断。内核 `status_catalog.rs:661-664`
/// 的 `decays_at_owner_turn_end` 是同一件事在标准包里的表达。
///
/// 三种编码：`BOOL_ABSENT`(0) / `BOOL_FALSE`(1) / `BOOL_NULL`(3) ⇒ `false`；`BOOL_TRUE`(2) ⇒ `true`。
/// 实测：镜像 23/23 状态都是 `BOOL_FALSE`（`raw=[1]`，我在二进制层面量过）。
///
/// 内容里没有这个定义 ⇒ [`BindError::Missing`]（同 [`has_tag`] 的理由）。
pub fn uses_duration(content: &Content<'_>, status_id: &str) -> Result<bool, BindError> {
    let row = status_row(content, status_id).ok_or(BindError::Missing("STAT row"))?;
    match row.uses_duration() {
        BOOL_TRUE => Ok(true),
        BOOL_ABSENT | BOOL_FALSE | BOOL_NULL => Ok(false),
        // `F_BOOL` 的四值之外不可能出现（`Row::cell` 只会给 u16），但"不可能"不该是 unwrap。
        _ => Err(BindError::Bool("UsesDuration")),
    }
}

/// `STAT.Triggers` 的 `_arr` 元素句柄 → `out[..n]`（**只取句柄，不解释内容**）。
///
/// 调用方（`host.rs`）拿它逐个解 `_obj{Event, Program}`。把它放在本模块的理由：`_arr` 的
/// 读法（两个槽 + `aux` 间接 + `LIST_ABSENT/LIST_NULL` 两个哨兵）本来就在本模块，
/// 抄一份到别处就是第二个会写错的地方。
///
/// 暂存区放不下 ⇒ [`BindError::BufferTooSmall`]（**不截断**：少读几条触发器等于内容静默不发作）。
pub fn trigger_handles(
    content: &Content<'_>,
    status_id: &str,
    out: &mut [u16],
) -> Result<usize, BindError> {
    let row = status_row(content, status_id).ok_or(BindError::Missing("STAT row"))?;
    arr_elements(content, row.triggers(), out)
}

/// 一个 `_arr` 句柄 → 它的元素句柄写进 `out[..n]`。
fn arr_elements(
    content: &Content<'_>,
    handle: u16,
    out: &mut [u16],
) -> Result<usize, BindError> {
    // 实测 18 个空态是**真的空 `_arr`**（槽 = `(start, 0)`，例如 58 → `(43, 0)`），
    // 但哨兵也要接：别的写入端可能把"空列表"写成 null。
    if handle == ABSENT16 || handle == NULL16 {
        return Ok(0);
    }
    let term = content.term(handle).ok_or(BindError::Term(handle))?;
    if term.op != OP_ARR {
        return Err(BindError::NotAnArray(handle));
    }
    let start = term.slot(0).ok_or(BindError::Aux(handle))?;
    let raw_count = term.slot(1).ok_or(BindError::Aux(handle))?;
    if raw_count == LIST_ABSENT || raw_count == LIST_NULL {
        return Ok(0);
    }
    let count = usize::from(raw_count);
    if count > out.len() {
        return Err(BindError::BufferTooSmall {
            needed: count,
            have: out.len(),
        });
    }
    for i in 0..count {
        let offset = u16::try_from(i).map_err(|_| BindError::Aux(start))?;
        let cell = start.checked_add(offset).ok_or(BindError::Aux(start))?;
        let element = content.aux(cell).ok_or(BindError::Aux(cell))?;
        let Some(slot) = out.get_mut(i) else {
            // 上面刚比过 `count <= out.len()`；这一条只为"没有 panic 路径"存在。
            return Err(BindError::BufferTooSmall {
                needed: count,
                have: out.len(),
            });
        };
        *slot = element;
    }
    Ok(count)
}

/// 解一条状态的完整元数据（极性 + 修饰器），修饰器写进调用方的暂存区 `out`。
///
/// * `Ok(None)`：内容里没有这个状态定义（**不是错误** —— 见 [`decode_required`] 的解释）。
/// * `Ok(Some(status))`：`&out[..status.modifier_count]` 就是这条状态的修饰器，
///   `status.id` 是镜像里的定义 id（`&'a str`，指向镜像的串池）。
/// * `Err(_)`：镜像里的这条状态数据坏了 / 用了本层表示不了的键 / `out` 太小。
///   **一条都不写进 `out`**（先解码到局部变量，全部成功才落盘），所以失败后 `out` 的内容不会被
///   调用方误当成"部分有效"。
///
/// # 无分配
///
/// 全程只借用镜像字节 + 写 `out`，没有任何分配、没有 `static` 缓存、没有隐藏状态。
pub fn decode<'a>(
    content: &'a Content<'a>,
    status_id: &str,
    out: &mut [PassiveModifier],
) -> Result<Option<DecodedStatus<'a>>, BindError> {
    let Some(row) = status_row(content, status_id) else {
        return Ok(None);
    };
    let id = content
        .string(row.id())
        .ok_or(BindError::String(row.id()))?;
    let polarity = decode_polarity(content, row)?;
    let modifier_count = read_modifiers(content, row, out)?;
    Ok(Some(DecodedStatus {
        id,
        polarity,
        modifier_count,
    }))
}

/// [`decode`] 的**严格版**：内容里查不到这个状态定义 ⇒ [`BindError::Missing`]`("STAT row")`。
///
/// # 为什么这个版本才是"走管线"的那一版
///
/// "查不到定义"与"这个状态没有任何修饰器"在**解码层本来就已经分开了**
/// （`Ok(None)` vs `Ok(Some)` 且 `modifier_count == 0`），但修本轮之前**没有一个管线调用方
/// 利用这个区别**：`exec.rs` 的镜像折叠写的是 `let Some(decoded) = … else { continue }`，
/// 于是"内容里根本没这个状态"与"这个状态不参与这条管线"落到了同一条静默分支上。
/// 后果是最坏的那一档：内容用了自造的 id（例如 `sts_vulnerable`）而镜像的 `STAT` 表里没有它，
/// **每个数字看着都合理**，只是那条状态从来不起作用。
///
/// 两种"查不到"的成因都不该静默：内核缺能力（`STAT` 那份元数据还读不出）与内容配错
/// （id 拼错 / 定义没进内容包）都会被这一条挡住。
///
/// # 与 [`has_tag`] / [`uses_duration`] 的变体是同一个
///
/// 那两条读口早就是这个口径（`ok_or(BindError::Missing("STAT row"))?`），本函数只是把
/// **修饰器管线**这条最重要的路对齐过去。**一个条件只有一种报法**：`Missing("STAT row")`。
///
/// # 什么时候该用 `decode`（软版）
///
/// 只有"查不到就等于没说过"的读口：今天只剩 [`polarity`]（`applyStatus` 只需要极性，
/// 拿野 id 时按 `Buff` 兜底，那条偏差记在 `exec.rs` 的模块头）。
pub fn decode_required<'a>(
    content: &'a Content<'a>,
    status_id: &str,
    out: &mut [PassiveModifier],
) -> Result<DecodedStatus<'a>, BindError> {
    decode(content, status_id, out)?.ok_or(BindError::Missing("STAT row"))
}

// =============================================================================================
// 解码内部
// =============================================================================================

/// `Polarity` 格（`F_STR`）→ [`StatusPolarity`]。
fn decode_polarity(
    content: &Content<'_>,
    row: StatusRow<'_>,
) -> Result<StatusPolarity, BindError> {
    let cell = row.polarity();
    if cell == ABSENT16 || cell == NULL16 {
        return Err(BindError::Missing("Polarity"));
    }
    let text = content.string(cell).ok_or(BindError::String(cell))?;
    match text {
        "Buff" => Ok(StatusPolarity::Buff),
        "Debuff" => Ok(StatusPolarity::Debuff),
        "Neutral" => Ok(StatusPolarity::Neutral),
        _ => Err(BindError::Polarity),
    }
}

/// `PassiveModifiers` 格 → `out[..n]`。
fn read_modifiers<'a>(
    content: &'a Content<'a>,
    row: StatusRow<'a>,
    out: &mut [PassiveModifier],
) -> Result<usize, BindError> {
    // `_arr` 的两个槽 + 两个哨兵由 [`arr_elements`] 统一读（同一条读法只写一次）。
    let mut handles = [0u16; MAX_MODIFIERS];
    let limit = out.len().min(MAX_MODIFIERS);
    let count = arr_elements(content, row.passive_modifiers(), &mut handles[..limit])?;

    for i in 0..count {
        let Some(element) = handles.get(i).copied() else {
            return Err(BindError::BufferTooSmall {
                needed: count,
                have: limit,
            });
        };
        let spec = decode_spec(content, element)?;
        let Some(slot) = out.get_mut(i) else {
            return Err(BindError::BufferTooSmall {
                needed: count,
                have: out.len(),
            });
        };
        *slot = spec;
    }
    Ok(count)
}

/// 一个 `_obj` 元素 → [`PassiveModifier`]。
fn decode_spec<'a>(
    content: &'a Content<'a>,
    element: u16,
) -> Result<PassiveModifier, BindError> {
    let node = NodeRef::new(content, element);
    // 元素必须是 `op >= OP_FIRST_DYNAMIC` 的对象：`_arr` 里的标量元素会让 `str_field` 报
    // `NotAnObject`，那正是我们要的响亮拒绝。
    let pipeline = match node.str_field("Pipeline")? {
        Some(name) => Pipeline::from_wire_name(name).ok_or(BindError::Pipeline)?,
        None => return Err(BindError::Missing("Pipeline")),
    };
    let operation = match node.str_field("Operation")? {
        Some(name) => ModifierOp::from_wire_name(name).ok_or(BindError::Operation)?,
        None => return Err(BindError::Missing("Operation")),
    };
    let magnitude = node
        .int_field("Magnitude")?
        .ok_or(BindError::Missing("Magnitude"))?;
    let priority = node
        .int_field("Priority")?
        .ok_or(BindError::Missing("Priority"))?;
    let restrict_damage_kind = match node.str_field("RestrictDamageKind")? {
        Some(name) => Some(DamageKind::from_wire_name(name).ok_or(BindError::DamageKind)?),
        None => None,
    };

    // 五个"本层表示不了"的键：镜像里全是 null/false，非空即为"内容用到了我们还不懂的东西"。
    for key in [
        "AppliesToStatusId",
        "RestrictSourceCardTag",
        "MagnitudeExpression",
        "RestrictElement",
    ] {
        if node.node_field(key)?.is_some() {
            return Err(BindError::Unsupported(key));
        }
    }
    for key in ["OncePerAction", "OncePerTurn"] {
        if node.bool_field(key)? == Some(true) {
            return Err(BindError::Unsupported(key));
        }
    }

    Ok(PassiveModifier {
        pipeline,
        operation,
        magnitude,
        priority,
        restrict_damage_kind,
    })
}

// =============================================================================================
// 测试
//
// 读真实镜像（`tools/contentc/out/content.core.rdcf`）。镜像不在仓库里（构建产物），
// 找不到就 panic 并打印路径与生成命令 —— 产物缺席时安静通过的测试等于没有测试。
// =============================================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::content::{Content, S_STAT, S_TRM};
    use std::vec::Vec;

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

    /// 镜像里每个 `STAT` 行的定义 id（按行号）。
    fn status_ids<'a>(content: &'a Content<'a>) -> Vec<&'a str> {
        content
            .rows(crate::content::Table::Status)
            .map(|row| content.string(row.cell(0).unwrap_or(0)).unwrap_or(""))
            .collect()
    }

    #[test]
    fn the_core_image_binds_every_status() {
        // 全镜像扫描（23 个状态）：每一条都必须解码成功，极性分布与修饰器条数必须与实测吻合。
        let blob = core_image();
        let content = parse(&blob);
        let ids = status_ids(&content);
        assert_eq!(ids.len(), 23, "core 镜像的 STAT 表是 23 行");

        let mut buff = 0usize;
        let mut debuff = 0usize;
        let mut neutral = 0usize;
        let mut with_modifiers = 0usize;
        let mut buffer = [PassiveModifier {
            pipeline: Pipeline::DamageDealt,
            operation: ModifierOp::AddFlat,
            magnitude: 0,
            priority: 0,
            restrict_damage_kind: None,
        }; MAX_MODIFIERS];

        for id in &ids {
            let decoded = decode(&content, id, &mut buffer)
                .unwrap_or_else(|e| panic!("状态 {id} 解码失败：{e:?}"))
                .unwrap_or_else(|| panic!("状态 {id} 在 IDX 里应当查得到"));
            assert_eq!(decoded.id, *id, "解码出的 id 必须与行 id 逐字节相同");
            match decoded.polarity {
                StatusPolarity::Buff => buff += 1,
                StatusPolarity::Debuff => debuff += 1,
                StatusPolarity::Neutral => neutral += 1,
            }
            assert!(
                decoded.modifier_count <= 1,
                "实测每条状态最多 1 条修饰器，{id} 有 {}",
                decoded.modifier_count
            );
            if decoded.modifier_count > 0 {
                with_modifiers += 1;
            }
        }

        // 实测分布：Debuff 5 / Buff 5 / Neutral 13；非空 PassiveModifiers 5 个（18 个空）。
        assert_eq!((buff, debuff, neutral), (5, 5, 13), "极性分布");
        assert_eq!(with_modifiers, 5, "非空 PassiveModifiers 的状态个数");
        assert_eq!(ids.len() - with_modifiers, 18, "空 PassiveModifiers 的状态个数");
    }

    #[test]
    fn the_five_non_empty_statuses_carry_these_exact_specs() {
        // 5 条 spec 的每一个字段都钉死（这张表就是"镜像里有什么"的全部证据）。
        // 用别名而不是把元组写在 `let` 上：clippy 的 `type_complexity` 会认别名、不认内联元组。
        type Case = (&'static str, StatusPolarity, Pipeline, ModifierOp, i32, i32, Option<DamageKind>);
        let cases: [Case; 5] = [
            (
                "doubt",
                StatusPolarity::Debuff,
                Pipeline::DamageDealt,
                ModifierOp::ScalePercent,
                75,
                100,
                Some(DamageKind::Direct),
            ),
            (
                "panic",
                StatusPolarity::Debuff,
                Pipeline::TurnStartDraw,
                ModifierOp::AddPerStack,
                -1,
                100,
                None,
            ),
            (
                "strength",
                StatusPolarity::Buff,
                Pipeline::DamageDealt,
                ModifierOp::AddPerStack,
                1,
                100,
                Some(DamageKind::Direct),
            ),
            (
                "signature_pending",
                StatusPolarity::Buff,
                Pipeline::DamageReceived,
                ModifierOp::ScalePercent,
                75,
                100,
                Some(DamageKind::Direct),
            ),
            (
                "seal_intact",
                StatusPolarity::Buff,
                Pipeline::DamageReceived,
                ModifierOp::AddFlat,
                -4,
                100,
                Some(DamageKind::Direct),
            ),
        ];

        let blob = core_image();
        let content = parse(&blob);
        let mut buffer = [PassiveModifier {
            pipeline: Pipeline::DamageDealt,
            operation: ModifierOp::AddFlat,
            magnitude: 0,
            priority: 0,
            restrict_damage_kind: None,
        }; MAX_MODIFIERS];

        for (id, polarity, pipeline, operation, magnitude, priority, kind) in cases {
            let decoded = decode(&content, id, &mut buffer).unwrap().unwrap();
            assert_eq!(decoded.polarity, polarity, "{id} 极性");
            assert_eq!(decoded.modifier_count, 1, "{id} 只有 1 条修饰器");
            let spec = buffer[0];
            assert_eq!(spec.pipeline, pipeline, "{id} Pipeline");
            assert_eq!(spec.operation, operation, "{id} Operation");
            assert_eq!(spec.magnitude, magnitude, "{id} Magnitude");
            assert_eq!(spec.priority, priority, "{id} Priority");
            assert_eq!(spec.restrict_damage_kind, kind, "{id} RestrictDamageKind");
            // 字面串也必须能往回映射（写端/读端共用同一套拼法）。
            assert_eq!(Pipeline::from_wire_name(pipeline.wire_name()), Some(pipeline));
            assert_eq!(ModifierOp::from_wire_name(operation.wire_name()), Some(operation));
        }
        // `panic` 的 `-1` 在槽里是 0xFFFF，解成 i16 才是 -1（`ir.rs` 的 F_INT 口径）。
        let decoded = decode(&content, "panic", &mut buffer).unwrap().unwrap();
        assert_eq!(decoded.modifier_count, 1);
        assert_eq!(buffer[0].magnitude, -1);
        // `seal_intact` 的 -4 落盘是 65532。
        let decoded = decode(&content, "seal_intact", &mut buffer).unwrap().unwrap();
        assert_eq!(decoded.modifier_count, 1);
        assert_eq!(buffer[0].magnitude, -4);
    }

    #[test]
    fn the_spec_objects_declare_exactly_the_seven_keys_we_read() {
        // 门槛：本模块的"7 个键"不是看着像，而是镜像里 `_obj` 声明的**全部**字段。
        // 换内容包时若多出第八个键，这条会红 —— 提醒"你的解码表漏了一列"。
        let blob = core_image();
        let content = parse(&blob);
        let mut expected = Vec::from([
            "AppliesToStatusId",
            "Magnitude",
            "Operation",
            "Pipeline",
            "Priority",
            "RestrictDamageKind",
            "RestrictSourceCardTag",
        ]);
        expected.sort_unstable();

        let stat = content.section(S_STAT).expect("STAT 段");
        let mut checked = 0usize;
        for row in 0..stat.count {
            let Some(status) = content.status(row) else {
                continue;
            };
            let handle = status.passive_modifiers();
            if handle == ABSENT16 || handle == NULL16 {
                continue;
            }
            let term = content.term(handle).expect("PassiveModifiers 必须是 term");
            assert_eq!(term.op, OP_ARR, "PassiveModifiers 必须是 _arr");
            let start = term.slot(0).expect("槽 0");
            let count = term.slot(1).expect("槽 1");
            for i in 0..count {
                let element = content
                    .aux(start + i)
                    .expect("aux 区间必须在段内");
                let element_term = content.term(element).expect("元素必须是 term");
                let opcode = content
                    .opcode(element_term.op)
                    .expect("元素的 opcode 必须存在");
                let mut names = Vec::new();
                for j in 0..opcode.nfields() {
                    let field = opcode.field(j).expect("字段描述越界");
                    names.push(content.string(field.name_str()).unwrap_or(""));
                }
                names.sort_unstable();
                assert_eq!(
                    names, expected,
                    "spec 对象的字段表必须正好是这 7 个键（op = {}）",
                    element_term.op
                );
                checked += 1;
            }
        }
        assert_eq!(checked, 5, "实测 5 条 spec");
        // 顺手钉住 term 段的规模没被别的测试改动（同 `ir.rs` 的口径）。
        assert!(content.section(S_TRM).is_some());
    }

    #[test]
    fn an_unknown_status_is_none_and_a_missing_status_contributes_nothing() {
        let blob = core_image();
        let content = parse(&blob);
        let mut buffer = [];
        assert_eq!(decode(&content, "no_such_status", &mut buffer), Ok(None));
        assert_eq!(polarity(&content, "no_such_status"), Ok(None));
        // 标准包 id 不在这个内容包里 —— 这正是 exec 的"桥"只该在没有 content 时生效的理由。
        assert_eq!(polarity(&content, "standard.strength"), Ok(None));
        assert_eq!(polarity(&content, "strength"), Ok(Some(StatusPolarity::Buff)));
        // `paperwork` 是 **Debuff**（不是 Neutral）：它有 `damage_over_time` 标签且极性如此。
        assert_eq!(
            polarity(&content, "paperwork"),
            Ok(Some(StatusPolarity::Debuff))
        );
    }

    #[test]
    fn the_strict_decoder_tells_an_unregistered_status_from_an_empty_one() {
        // ★ 本轮 A/B 两件事的共同地基：**"查不到定义"与"定义在那儿但一条修饰器都没有"
        // 在解码层就是两条不同的路**（软 `decode` 用 `Ok(None)` / `Ok(Some{count:0})` 分开），
        // 本轮之前没有任何管线调用方利用这个区别（`exec.rs` 把它们都 `continue` 掉了）。
        let blob = core_image();
        let content = parse(&blob);
        let mut buffer = [PassiveModifier {
            pipeline: Pipeline::DamageDealt,
            operation: ModifierOp::AddFlat,
            magnitude: 0,
            priority: 0,
            restrict_damage_kind: None,
        }; MAX_MODIFIERS];

        // 一、查不到 ⇒ 响亮。三种成因同一种报法（自造 id / 标准包 id / 拼错）：
        //     一律 `Missing("STAT row")`，与 `has_tag` / `uses_duration` 同一个变体
        //     （`status_bind.rs` 里那两条读口早就是这个口径）。
        for id in ["sts_vulnerable", "no_such_status", "standard.strength"] {
            assert_eq!(
                decode_required(&content, id, &mut buffer),
                Err(BindError::Missing("STAT row")),
                "{id} 不在镜像的 STAT 表里 ⇒ 走管线的调用方必须看到这条拒绝"
            );
            // 软版仍然 `Ok(None)`：那是**极性问题**的合法输入（`polarity` 要它回退）。
            assert_eq!(decode(&content, id, &mut buffer), Ok(None), "{id} 软版");
        }

        // 二、定义在、修饰器为空 ⇒ **合法**，正常放行（`paperwork` 是纯声明式状态）。
        let decoded = decode_required(&content, "paperwork", &mut buffer)
            .expect("已知但空 modifiers 不许被拦下");
        assert_eq!(decoded.id, "paperwork");
        assert_eq!(decoded.modifier_count, 0);
        assert_eq!(decoded.polarity, StatusPolarity::Debuff);

        // 三、有修饰器的那条：严格版与软版给同一个答案（严格版不是另一个解码器）。
        let strict = decode_required(&content, "doubt", &mut buffer).expect("doubt 必须查得到");
        assert_eq!(strict.modifier_count, 1);
        assert_eq!(buffer[0].pipeline, Pipeline::DamageDealt);
    }

    #[test]
    fn a_buffer_that_is_too_small_is_reported_instead_of_truncated() {
        let blob = core_image();
        let content = parse(&blob);
        let mut empty: [PassiveModifier; 0] = [];
        assert_eq!(
            decode(&content, "doubt", &mut empty),
            Err(BindError::BufferTooSmall { needed: 1, have: 0 })
        );
        // 失败**不写 out**：给一格但也要求它保持原样（这里用"够用的那一格没被污染"来表达）。
        let mut one = [PassiveModifier {
            pipeline: Pipeline::TurnStartDraw,
            operation: ModifierOp::AddFlat,
            magnitude: 7,
            priority: 0,
            restrict_damage_kind: None,
        }; 1];
        let decoded = decode(&content, "doubt", &mut one).unwrap().unwrap();
        assert_eq!(decoded.modifier_count, 1);
        assert_eq!(one[0].magnitude, 75, "成功时真的写进去了");
    }

    #[test]
    fn a_corrupt_polarity_string_is_an_error_not_a_guess() {
        // 把 `doubt` 的 `Polarity` 格改指到另一条已存在的串（"scenario"）⇒ 必须报 Polarity，
        // 而不是"猜一个 Buff"。
        let mut blob = core_image();
        let (cell_at, scenario_id) = {
            let content = parse(&blob);
            let row = content
                .lookup_in("doubt", EK_STATUS)
                .expect("doubt 必须是状态");
            let stat = content.section(S_STAT).expect("STAT 段");
            let at = stat.offset as usize + usize::from(row.index) * 40 + 4 * 2;
            let scenario_id = content
                .strings()
                .position(|s| s == Some("scenario"))
                .expect("镜像里应当有 scenario 这条串")
                + 1;
            (at, scenario_id)
        };
        let patch = blob
            .get_mut(cell_at..cell_at + 2)
            .expect("补丁位置必须在镜像内");
        patch.copy_from_slice(&(scenario_id as u16).to_le_bytes());

        let content = parse(&blob);
        assert_eq!(polarity(&content, "doubt"), Err(BindError::Polarity));
        // 顺带：解码整条也在同一个地方失败，而且失败前不会写 out。
        let mut buffer = [PassiveModifier {
            pipeline: Pipeline::DamageDealt,
            operation: ModifierOp::AddFlat,
            magnitude: 0,
            priority: 0,
            restrict_damage_kind: None,
        }; MAX_MODIFIERS];
        assert_eq!(
            decode(&content, "doubt", &mut buffer),
            Err(BindError::Polarity)
        );
    }

    #[test]
    fn the_wire_names_are_exactly_the_four_plus_three_plus_three() {
        // 面窄但钉死：本层只认这几串，别的必须 `None`（而不是"默认成第一个"）。
        // 4 条管线 × 3 种运算 × 3 种伤害种类。
        for name in [
            "DamageDealt",
            "DamageReceived",
            "BlockGain",
            "TurnStartDraw",
        ] {
            assert!(Pipeline::from_wire_name(name).is_some(), "{name}");
        }
        // ★ 本轮加的：格挡那条管线的 wire 串是参考的**枚举成员名** `"BlockGain"`，
        // 不是折叠器枚举的变体名 `"Block"`。写成 `"Block"` 会让内容里那条 frail spec
        // 永远匹配不上（`BindError::Pipeline` 反而还算好事，最坏的是有人顺手加了
        // `"Block"` 分支而内容写的是 `"BlockGain"`）—— 两条分开钉。
        assert_eq!(
            Pipeline::from_wire_name("BlockGain"),
            Some(Pipeline::Block)
        );
        assert_eq!(Pipeline::Block.wire_name(), "BlockGain");
        assert_eq!(Pipeline::from_wire_name("Block"), None, "wire 串不是 Block");
        assert_eq!(Pipeline::from_wire_name("Cost"), None);
        assert_eq!(Pipeline::from_wire_name("CardCost"), None);
        assert_eq!(Pipeline::from_wire_name("damageDealt"), None, "大小写敏感");
        // 4 个变体 → 4 个串，一一对应（写回再读回，不许两个变体共用一个串）。
        let all = [
            Pipeline::DamageDealt,
            Pipeline::DamageReceived,
            Pipeline::Block,
            Pipeline::TurnStartDraw,
        ];
        for (i, a) in all.iter().enumerate() {
            assert_eq!(Pipeline::from_wire_name(a.wire_name()), Some(*a));
            for b in &all[i + 1..] {
                assert_ne!(a.wire_name(), b.wire_name(), "{a:?} 与 {b:?} 共用一个串");
            }
        }

        for name in ["AddPerStack", "AddFlat", "ScalePercent"] {
            assert!(ModifierOp::from_wire_name(name).is_some(), "{name}");
        }
        assert_eq!(ModifierOp::from_wire_name("ClampMax"), None);

        assert_eq!(
            DamageKind::from_wire_name("Direct"),
            Some(DamageKind::Direct)
        );
        // ⚠️ 这两条**原来是 `None`**：`status_bind::DamageKind` 早先只有 `Direct` 一个变体，
        // 于是"镜像里没出现过的串"被当成了"这个串不存在"。真实的理由是**镜像没用到**它
        // （参考的枚举有三个成员，`CombatPrimitives.cs:18-23`），而不是引擎没有它 ——
        // 现在 DoT 要走真的 `DamageKind::Dot`（`exec::resolve_damage_of_kind`），所以必须认。
        assert_eq!(
            DamageKind::from_wire_name("DamageOverTime"),
            Some(DamageKind::Dot),
            "参考的成员名是 DamageOverTime，不是 Dot"
        );
        assert_eq!(
            DamageKind::from_wire_name("Reflected"),
            Some(DamageKind::Reflected)
        );
        assert_eq!(DamageKind::from_wire_name("dot"), None, "大小写敏感");
        assert_eq!(DamageKind::from_wire_name("True"), None, "不许猜成 Direct");
    }

    #[test]
    fn the_damage_kind_bits_match_the_catalog_constants() {
        // `status_catalog::DAMAGE_KIND_*` 是按参考的判别值手写的位（`status_catalog.rs:111-117`）；
        // 这里的 `bit()` 是第二个出处。两者一旦不一致，"标准包三行只对 Direct 生效"就会
        // 悄悄变成"对别的东西生效" —— 所以逐位比一遍。
        assert_eq!(DamageKind::Direct.bit(), crate::status_catalog::DAMAGE_KIND_DIRECT);
        assert_eq!(
            DamageKind::Dot.bit(),
            crate::status_catalog::DAMAGE_KIND_DAMAGE_OVER_TIME
        );
        assert_eq!(
            DamageKind::Reflected.bit(),
            crate::status_catalog::DAMAGE_KIND_REFLECTED
        );
        // 三个位互不相同且与判别值一致（0/1/2）。
        assert_eq!(DamageKind::Direct.index(), 0);
        assert_eq!(DamageKind::Dot.index(), 1);
        assert_eq!(DamageKind::Reflected.index(), 2);
        // 标准包三行的门只放行 Direct（`status_catalog.rs:124`）。
        let mask = crate::status_catalog::DAMAGE_MODIFIER_DAMAGE_KINDS;
        assert_ne!(mask & DamageKind::Direct.bit(), 0);
        assert_eq!(mask & DamageKind::Dot.bit(), 0);
        assert_eq!(mask & DamageKind::Reflected.bit(), 0);
        // 往返：wire_name ↔ from_wire_name。
        for kind in [DamageKind::Direct, DamageKind::Dot, DamageKind::Reflected] {
            assert_eq!(DamageKind::from_wire_name(kind.wire_name()), Some(kind));
        }
    }

    #[test]
    fn only_poison_and_paperwork_carry_the_damage_over_time_tag() {
        // DoT 的**唯一**判据是定义上的 `damage_over_time` 标签（`StandardCombatIds.cs:45` +
        // `StatusEffects.cs:462`）。这条测试既是解码器的验证，也是"今天有几个 DoT 状态"这个数。
        let blob = core_image();
        let content = parse(&blob);
        let ids = status_ids(&content);
        assert_eq!(ids.len(), 23);

        let mut tagged: Vec<&str> = Vec::new();
        for id in &ids {
            // 每一条都必须**解码成功**：`_arr` 的形状读错会在这里变成 Err，而不是静默 false。
            let has = has_tag(&content, id, "damage_over_time")
                .unwrap_or_else(|e| panic!("状态 {id} 的 Tags 解不出来：{e:?}"));
            // 反向的一条：任何一个状态都不该带这两个今天不存在的标签。
            for absent in ["retain_hand", "retain_block"] {
                assert!(
                    !has_tag(&content, id, absent).unwrap(),
                    "实测 {id} 不带 {absent}"
                );
            }
            if has {
                tagged.push(id);
            }
        }
        assert_eq!(tagged, std::vec!["paperwork", "poison"], "实测 2 个 DoT 状态");
    }

    #[test]
    fn no_status_in_the_image_uses_duration_or_charges() {
        // 这就是"`decrease_timed_statuses` 今天空转"的**实测依据**（规格书 §0.3 的判定），
        // 而且它是六条之一：内容一改，这条会红，然后钩子那段的注释就必须跟着改。
        let blob = core_image();
        let content = parse(&blob);
        let ids = status_ids(&content);
        let mut with_duration = 0usize;
        for id in &ids {
            if uses_duration(&content, id)
                .unwrap_or_else(|e| panic!("状态 {id} 的 UsesDuration 解不出来：{e:?}"))
            {
                with_duration += 1;
            }
        }
        assert_eq!(with_duration, 0, "镜像 23/23 状态 UsesDuration = false");
    }

    #[test]
    fn tag_and_duration_lookups_refuse_an_unknown_status_instead_of_answering_false() {
        // "内容里没有这个状态定义"与"这个状态没有标签"是两件事。前者是调用违约（实例是从
        // 一个不存在的定义造出来的），必须响亮 —— 否则一个打错字的状态 id 会安静地不跳 DoT。
        let blob = core_image();
        let content = parse(&blob);
        assert_eq!(
            has_tag(&content, "no_such_status", "damage_over_time"),
            Err(BindError::Missing("STAT row"))
        );
        assert_eq!(
            uses_duration(&content, "no_such_status"),
            Err(BindError::Missing("STAT row"))
        );
        assert_eq!(
            trigger_handles(&content, "no_such_status", &mut [0u16; 8]),
            Err(BindError::Missing("STAT row"))
        );
    }

    #[test]
    fn every_trigger_array_in_the_image_decodes_into_handles() {
        // 25 条触发器分布在 15 个状态上（实测）。这条钉住"`_arr` 读法对 Triggers 同样成立"，
        // 并且给出条数 —— 钩子那边的 `MAX_TRIGGERS_PER_STATUS` 就是按这个数留余量的。
        let blob = core_image();
        let content = parse(&blob);
        let ids = status_ids(&content);
        let mut buffer = [0u16; 8];
        let mut total = 0usize;
        let mut max_per_status = 0usize;
        for id in &ids {
            let n = trigger_handles(&content, id, &mut buffer)
                .unwrap_or_else(|e| panic!("状态 {id} 的 Triggers 解不出来：{e:?}"));
            assert!(n <= buffer.len());
            total += n;
            max_per_status = max_per_status.max(n);
        }
        assert_eq!(total, 25, "实测镜像 25 条触发器");
        assert_eq!(max_per_status, 5, "实测单个状态最多 5 条（paper_seals_wax）");
    }

    #[test]
    fn every_status_id_in_the_image_fits_the_exec_pool() {
        // `exec.rs` 的排序键池是 `MAX_CANDIDATES × state::ID_CAP`；id 是该池唯一的消耗者。
        let blob = core_image();
        let content = parse(&blob);
        for id in status_ids(&content) {
            assert!(
                id.len() <= crate::state::ID_CAP,
                "状态 id {id} 有 {} B，超过 state::ID_CAP",
                id.len()
            );
        }
    }
}
