//! 效果程序**执行** —— 把 IR 节点跑在真实的 `CombatState` 上。
//!
//! 这是效果解释器的最后一块（W4a `ir.rs` 读树、W4b `sel.rs` 翻译选择器、
//! W4c `expr.rs` 求值）。执行层负责：解析目标 → 求值数值 → 走修饰器管线 → 改状态。
//!
//! ## 范围：15 种节点里的 **15** 种（按真实镜像的节点分布定的，见 `docs/port-plan.md` §32.1）
//!
//! 第一轮（v1）支持 6 种：`sequence`(1273) / `conditional`(563) / `applyStatus`(936) /
//! `dealDamage`(260) / `gainBlock`(181) / `heal`(3)。
//!
//! 第二轮（W4e）加了 7 种节点 —— 名字后面的数字是**它们在 62 张牌的程序里出现的次数**
//! （实测，见 `tools/contentc` 的扫描）：
//!
//! | 节点 | 牌内出现 | 主要出现在 |
//! |---|---|---|
//! | `drawCards` | 12 | 12 张牌 |
//! | `createCardInstance` | 12 | 12 张牌 |
//! | `gainResource` | 2 | 2 张牌 |
//! | `setCombatantCounter` | 0 | 敌动作 / 触发程序（镜像共 30 个 term） |
//! | `modifyStatusStacks` | 0 | 敌动作 / 触发程序（15 个 term） |
//! | `forEachTarget` | 0 | 敌动作 / 触发程序（6 个 term） |
//! | `loseResource` | 0 | 敌动作（1 个 term） |
//!
//! 第三轮（W4f）补上最后 2 种 —— **卡实例这一层寻址**：
//!
//! | 节点 | 牌内出现 | 出现在 |
//! |---|---|---|
//! | `forEachCardInZone` | 2 个 term | `archive_the_evidence(+)` / `shredder_drawer(+)` |
//! | `moveCardToZone` | 1 个 term | 同上 4 张，**只作为上者的 `Body`** |
//!
//! ⇒ 62 张牌**全部可执行**（门槛测试
//! `every_card_program_in_the_image_runs_because_no_kind_is_refused` 把这条钉成数字）。
//! 它们靠 [`crate::expr::eval_card`]（`cardInstance.iterated`）+ [`ExecContext::iteration_card`]
//! 这一对已经冻结的口子，本文件只负责**循环、过滤、卡区搬迁**。
//!
//! ### `forEachCardInZone` 的三条实测语义（`EffectProgramNodeExecutors.cs:432-506`，我逐行核对过）
//!
//! 1. **列表在循环开始时快照**（`:447-448` 的注释 + `:465` 的 `ToArray()`；SEMANTICS-v1 D14）：
//!    循环体把卡搬走/换掉都不影响这一趟走完 —— 本文件快照的是**池槽位**
//!    （`state.rs` 里槽位是卡的稳定身份：`push_card` 只追加、`remove_card` 退休不回收，
//!    `move_card` **复用**同一槽位），所以"搬家不影响这一趟"与参考等价。
//! 2. **`TakeFirst` 是 `Enumerable.Take(n)`**（`:463-464`）：`n <= 0` ⇒ 空序列（**不是**截成 1、
//!    也**不是**错误）。
//! 3. **`MaxIterations` 超限是抛、不是截断**（`:467-470`，SEMANTICS-v1 O38 / D6）：
//!    比的是 `TakeFirst` **之后**的张数。它映射到 [`ExecError::Modifier`]（与 `forEachTarget` 同一条理由）。
//!
//! ### `TagFilter` 需要**卡定义**的 tag 表，而它只在内容镜像里
//!
//! 参考读 `combat.DefinitionRegistry.CardDefinitions[c.DefinitionId].Tags`（`:452-458`，`:454` 的注释
//! 原文："the tags live on its definition; an instance whose definition isn't registered has none"）。
//! 本内核没有独立的卡定义注册表，**内容镜像的 `CARD` 表就是它**（每行有 `Id` 与 `Tags` 两格），
//! 所以 `TagFilter` 走 `IDX` 查 `CARD` 行。
//!
//! ⇒ **`ctx.content == None` 时 `TagFilter` 无法求值 ⇒ 响亮拒绝**（[`IrError::Missing`]`("content")`），
//! **不许**静默成"一张都不匹配"：那会让"清空手牌里的废纸"安静地一张都不清（本模块最恨的失败形态）。
//! 反过来，`content == Some` 但某张卡的 definition 不在 `CARD` 表里 ⇒ **不算匹配**
//! （参考对"未注册的定义没有 tag"就是这条，`:454`），这不是错误。
//!
//! ### `DefinitionFilter` 非空 ⇒ 响亮拒绝
//!
//! ⚠️ **冻结方的描述有误**：`DefinitionFilter` **不是**卡选择器，而是 `CardDefinitionId?`
//! （`EffectProgramNodes.cs:294`，比较的是 `c.DefinitionId == filter`，`:451`）。
//! 它在镜像里是 `F_TERM` 且 2 条 term **全是 NULL**；非空时线上是一个 `_wrap_lower` 包装串，
//! 而 `ir.rs` 的 [`NodeRef::field`] 故意拒绝那种拼法（`WrongKind("F_TERM")`）。
//! 两条路都是响亮失败：包装串 ⇒ [`ExecError::Ir`]，别的对象 ⇒ [`SelError::UnsupportedKind`]。
//! 拒绝它的代码是 [`reject_definition_filter`]，与 `ResultKey` 的闸门同一位置（预检 + 分派各一次）。
//!
//! ## 三处**必须记录**的简化（都在本文件里，别让它们变成隐藏假设）
//!
//! 1. **没有事件队列 ⇒ `Sequence` 与 `CausalSequence` 观察等价。**
//!    参考实现里 `Sequence` 是"全部孩子入队后再处理反应"、`CausalSequence` 是
//!    "每个孩子完全结算（含反应）再走下一个"（`Nodes.cs:3-56`）。本内核**还没有触发程序/反应**，
//!    所以两者没有区别。**一旦接上触发器，这个等价就失效**，必须回头实现真正的队列。
//! 2. **没有 outcome slot。** 参考实现有 33 个 outcome 记录 + "每槽恰好完成一次"的不变量
//!    （`Outcomes.cs:161-257`），`ResultKey` 让后续节点读前面的结果。v1 不实现 ——
//!    `ResultKey` 字段**读了但不使用**，并在报告里标明。这意味着**读 `ResultKey` 的程序会算错**，
//!    所以执行时要**主动拒绝**这类程序（见下）。
//! 3. **没有 `MaxProgramSteps` 之外的预算。** 参考有七个限额（`MaxNodeDepth=64`、
//!    `ForEachTargetEffectNode.MaxIterations=32`、`ForEachCardInZoneNode.MaxIterations=64`、
//!    `RepeatEffectNode.MaxCount=32`…），本层只保留两个：步数预算与**节点深度**。
//!    ⚠️ 深度见 [`MAX_NODE_DEPTH`]（借 [`ExecError::StepLimit`] 表达，
//!    因为冻结的枚举里没有 `DepthLimit`）；两个循环节点的 `MaxIterations` 是**内容里的数**，
//!    由 [`for_each_target_node`] / [`for_each_card_in_zone_node`] 单独执行（超限**抛**，不截断）。
//!
//! ## 一条硬规则
//!
//! **`ResultKey` 非空 ⇒ 拒绝执行并报 [`ExecError::ResultKeyNotSupported`]。**
//! 理由：`ResultKey` 是"把这次的效果结果存进槽位供后面读"的机制。v1 没有槽位，
//! 如果读它的程序被**静默**执行，后面的表达式会读到 0 —— 一张牌安静地少做一半事。
//! 宁可报错。
//!
//! ⚠️ W4e 新增的 7 种节点里有 6 种**带 `ResultKey` 字段**（`EffectProgramNativeNodes.cs`：
//! `drawCards`/`createCardInstance`/`gainResource` 都声明了它）。它们在真实镜像里**全是
//! `null`**（实测 3 + 9 + 1 + 15 + 1 个 term，一个非空都没有），所以这条规则今天不挡任何真牌 ——
//! 但规则的实现是**先** [`reject_result_key`] **再**执行，与节点的种类无关。
//!
//! ## 预检（`ValidateNodeExecutors`）
//!
//! 参考实现在**执行前**先走一遍程序树，任何节点没有登记 executor 就**立即抛**
//! （`EffectProgramExecution.cs:23,184-196`），所以"不支持"永远不会**部分执行**。
//! 本模块照做：[`execute`] 先 [`preflight`] 再跑，于是"第 2 个孩子不可执行"的程序
//! （例如 `archive_the_evidence` = `sequence[forEachCardInZone, gainBlock]`，只要那个循环节点
//! 带着非空的 `DefinitionFilter`）一个 effect 都不会落地。
//!
//! W4f 之后 15 种节点**全都能跑**，所以预检剩下的活是那两条**结构硬规则**：
//! `ResultKey` 非空（[`reject_result_key`]）与 `DefinitionFilter` 非空
//! （[`reject_definition_filter`]）。它们**与节点种类无关**、在每个节点上都查。
//!
//! 预检走的是参考的这几条孩子边：`sequence.Children`、`conditional.Then/Else`、
//! **`forEachTarget.Body`**（`ForEachTargetEffectNode.Children => [Body]`，
//! `EffectProgramNodes.cs:255`）与 **`forEachCardInZone.Body`**（`:305`）——
//! 所以**循环体里**的违规也照样在第一次迭代之前被拒。
//! ⚠️ **不是**镜像里 `node.conditional` / `node.forEachTarget` 那些同名的 `Children` 字段
//! （`node.forEachTarget.Children` 是 `F_TERMLIST` 的**派生**属性，实测就是 `[Body]` 本身；
//! 按参考的边读 `Body` 才是不重复走、也不漏走的那一条）。
//!
//! ## 两条数据源：**镜像**（有 `content`）与**标准包**（没有 `content`）
//!
//! [`ExecContext::content`] 决定这一条分界线，**而且它是唯一的分界线**：
//!
//! | | `content == Some(镜像)` | `content == None` |
//! |---|---|---|
//! | 状态极性 | `status_bind::polarity`（`STAT.Polarity` 格，**参考实现读的那张表**） | `status_catalog::status_meta`（标准包 16 + 2 个 id） |
//! | 伤害/格挡修饰器 | 该状态自己的 `STAT.PassiveModifiers` | `status_catalog` 的两张硬编码表 |
//! | 状态 id 匹配 | **逐字节相等** | 逐字节相等 **+** [`modifier_applies_to`] 的命名空间桥 |
//! | 排序键第二级 | 镜像里的定义 id 字节（= 参考的 `group.Key.value`） | 目录行 id 字节 |
//!
//! `content == None` 这条路是 oracle/环境（`oracle`/`env`）要的：它跑的是标准包 id
//! （`standard.strength` 那些）。
//!
//! ### A. 状态 id 的命名空间桥（[`modifier_applies_to`]）—— **只在没有 `content` 时生效**
//!
//! `crate::status_catalog` 是**标准包**（`StandardCombatPackage.cs`）的表，行 id 是
//! `standard.strength` / `standard.weak` / `standard.vulnerable` / `standard.dexterity` /
//! `standard.frail`（`StandardCombatIds.cs:15-22`）。但**真实镜像 `content.core.rdcf` 是另一个
//! 内容包**，它的状态 id 是**裸名**（`strength` / `doubt` / `paperwork` / `fatigue` …，共 23 个），
//! 而且它**根本没有** `weak` / `vulnerable` / `dexterity` / `frail`。
//!
//! 这个桥是**未经验证的假设**（"场景内容里的 `strength` 与标准包的 `standard.strength` 同义"）：
//! 镜像自己的 `strength` 是 `AddPerStack 1 / Priority 100 / Direct`，标准包那一行刚好同值，
//! 但**另外 4 个带修饰器的镜像状态**（`doubt` / `panic` / `signature_pending` / `seal_intact`）
//! 在目录里**完全没有对应** —— 桥再怎么写也补不上它们，所以桥从来不可能是正路。
//!
//! ⇒ **有 `content` 时桥一刀不用**（[`StatusMatch::Exact`]），修饰器全部来自镜像
//! （`status_bind`）。桥只在 `content == None` 时生效，而且**只有这 5 条**（不做通用前缀剥离）。
//! 单测 `the_namespace_bridge_only_works_without_content` 把这条分工钉成断言。
//!
//! ### B. 状态实例的其余字段（`pending_turns` / 合并行为 / 延迟）
//!
//! 参考实现的 `ApplyStatusEffectHandler` 从**内容定义**取 `Polarity` / `DefaultVisibility` /
//! `StackingBehavior` / `IncomingStatusDelay`（`StatusEffects.cs:126-197`）。v1 只把 **`Polarity`
//! 接上了**（上面那张表的第一行）：
//!
//! * 极性：有 `content` ⇒ `status_bind`（**镜像里 `doubt` 是 `Debuff`**，旧实现默认 `Buff`，
//!   会让哈希的 `pol=` 与参考不同 —— 那个偏差已经修掉）；没有 `content` ⇒ 目录；
//!   **两边都查不到** ⇒ `Buff`。最后这一条是**最后兜底**：`Buff` 是 `StatusPolarity` 的零值，
//!   也是"什么都没说"时最不容易假装成结论的选择。它在"内容里真有这个状态"的前提下不可达
//!   （`status_bind::polarity` 查不到 = 内容里没有这个 id，那已经是内容/程序不一致），
//!   而在"调用方拿了个野 id"的前提下只能二选一 —— 所以它被写成显式的 `match` 而不是 `unwrap_or`。
//! * `pending_turns` 恒 0（延迟规格来自内容定义，v1 的 `status_bind` 还不读 `IncomingStatusDelay`）。
//! * 合并行为恒按 `MergeWithExistingInstance`（实测：镜像 23 个状态的定义全是它）。
//! * 出手方放大（`OutgoingStatusApplicationStacks`）没有实现 —— 镜像的 `PassiveModifiers` 里
//!   `AppliesToStatusId` 恒 null，标准包目录里也没有这条管线，`effectiveStacks = Stacks`。
//!
//! ## 其它已知偏差（逐条见 `docs/port-plan.md` 的报告）
//!
//! * 防御池吸收：参考按**注册表里的池定义**排的 `(AbsorbPriority, Id.value)` drain **全部**池
//!   （`CombatDefinitionRegistry.cs:68-71` + `DamageEffects.cs:80-101`）。本层 drain **全部在身的
//!   池**，顺序只剩第二级 —— **id 字节序**（`Combatant::defensive_pools()` 由 `Bounded::upsert`
//!   维持 key 字节序，所以切片顺序就是参考的顺序）。对所有 `AbsorbPriority == 0` 的池
//!   （标准包只注册 `standard.block`，`StandardCombatPackage.cs:54-55` 明写 `AbsorbPriority: 0`）
//!   **逐字相同**；⚠️ 内容若出现**非 0 优先级**的池，本层会按 id 排，与参考不同 ——
//!   那需要 `state.rs` 提供池定义（`DefensivePool` 今天只有 `key` + `pool`，没有优先级）。
//! * `drawCards` **不套手牌上限**：参考先算 `CombatDecrees.Ceiling(registry, drawer,
//!   CombatRule.MaxHandSize)`，命中就把要抽的数夹到 `min(上限 - 手牌数, Count)`（`CardZoneEffects.cs:31-46`）。
//!   本内核没有法令层（`state.rs` 没有 decree 存储，`turn.rs` 把上限放在 `TurnConfig` 里），
//!   所以执行层读不到上限 ⇒ 抽多少由 `Count` 决定。**内容用了 `MaxHandSize` 法令时会多抽**：
//!   镜像 23 个状态一条 `CombatRules` 都没有（`status_bind` 也不解它），标准包目录也没有，
//!   所以今天不改变任何结果。
//! * `createCardInstance` **不校验卡定义 id 存在**：参考先 `registry.GetCard(id)`，查不到就抛
//!   （`CardCreationEffects.cs:28`）。本层没有卡定义注册表（`Content` 的 `CARD` 表只有 62 行、
//!   而卡定义是**运行层**的 200+ 张），拿一个野 id 会造出一张"谁也解释不了"的卡。
//!   与 `applyStatus` 拿野状态 id 的处置同形（那条会兜底成 `Buff`），这里如实记录。
//! * `health_lost` **不会**超过扣血前的血量：`newHealth = max(0, hp - remaining)`、
//!   `healthLost = hpBefore - newHealth`（`DamageEffects.cs:103-104,138`），超出部分在参考里进
//!   另一个字段 `Overkill`；`resolve_damage` 的两元组里没有它。
//! * 扣到 0 会让目标转 `Downed`（`CombatantLifecycleEffects.cs` 的
//!   `MarkCombatantDownedOnZeroHealthHandler`），参考是**入队一个 effect** 异步做的，这里同步做
//!   （等价：v1 没有反应窗口）。
//! * `modifyStatusStacks` 把层数改到 0 时**删掉那条实例**（`StatusEffects.cs:830-838`），
//!   落点是 [`Combatant::remove_status`]（左移一格再 `pop()`，剩下的实例保持顺序）。
//!   见 [`remove_status_at`] 的文档；那里面解释过为什么"留一条 0 层实例"不是等价物。

use crate::content::{
    Content, ABSENT16, EK_CARD, F_TERM, LIST_ABSENT, LIST_NULL, NULL16, OP_ARR, OP_WRAP_LOWER,
};
use crate::expr::{self, ExprContext, ExprError};
use crate::ir::{IrError, NodeKind, NodeRef, Value};
use crate::modifiers::{self, Candidate, ClaimLedger, Operation, StatusKey};
use crate::sel::{CompiledSelector, SelError};
use crate::state::{
    Bounded, CapacityError, CardDefinitionId, CardInstanceId, CardSlot, CardZone,
    ChainSlot, CombatResult, Combatant, CombatantId, CombatantLifecycleState, CombatState,
    Container, Continuation, CounterId, DefensivePool, DefensivePoolId, EffectItem, EffectRequest,
    Empty, ProgramExecutionFrame, ProgramExecutionSlot, ProgramFrameState, ProgramLoop,
    ProgramLoopList, ProgramNodeKind, ProgramNodeSlot, ProgramTerminalHook, ResourceId,
    StatusDefinitionId, StatusInstance, StatusInstanceId, StatusPolarity, ZonePlacement, ID_CAP,
    MAX_CARDS_PER_ZONE, MAX_COMBATANTS, MAX_DEFENSIVE_POOLS, MAX_PROGRAM_FRAMES,
    MAX_QUEUE_CYCLES, NO_LOOP, NO_NODE_SLOT,
};
use crate::status_bind::{self, BindError, DamageKind as BindDamageKind, PassiveModifier};
use crate::status_catalog::{self, DamageModifierEntry, ModifierOp, ModifierTarget};
use crate::targets::SelectionContext;

// =============================================================================================
// 冻结的公开面（错误 / 上下文 / 统计 / 两个入口）
// =============================================================================================

/// 执行错误。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExecError {
    Ir(IrError),
    Expr(ExprError),
    Sel(SelError),
    /// 这一种节点不在本层范围。
    ///
    /// ⚠️ **今天不可达**（如实报告，不是遗漏）：镜像战斗侧只有 15 种节点，[`NodeKind`] 的 15 个
    /// 变体本层全部实现（W4f 之后），所以 [`preflight`] 与 [`dispatch`] 的两个分派都**穷尽**了
    /// 那 15 个变体、没有 `_` 臂（加了 `_` 编译器就报 `unreachable pattern`，`clippy` 要求零告警）。
    /// 于是能走到这里的只剩"第 16 种节点"，而那种节点在 [`NodeRef::kind`] 上就会以
    /// [`IrError::UnknownKind`] 拦下（[`NodeKind::from_wire_name`] 不认识的判别串）。
    /// 变体保留是因为它**冻结**，而且"节点不支持"与"判别串不认识"是两种不同的报告，
    /// 将来加节点时这条闸门还得在（那时把 `_` 臂加回去即可）。
    UnsupportedNode,
    /// 程序用了 `ResultKey`（结果槽），v1 没有槽位 —— 见模块头的硬规则。
    ResultKeyNotSupported,
    /// 需要一个来源单位（`source`），但上下文没给。
    ///
    /// ⚠️ **v1 没有任何路径构造它**，这是如实报告而不是遗漏：参考实现在"没有来源"时的行为
    /// 是**跳过 Source 阶段**（`PassiveModifiers.cs:248-249`：`combatant is null ⇒ return
    /// currentAmount`）与**选择器解出空集**（`CombatantTargetSelectors.cs:84-85`），
    /// 两者都不是错误。把这个变体拿去表达"少做了一半事"会与参考行为相反。
    NoSource,
    /// 目标单位在状态里不存在（选择器解出了它，但状态里没有）。
    MissingCombatant,
    /// 步数超出节目信封的 `MaxProgramSteps`。
    StepLimit,
    /// 底层定容容器满了。
    Capacity(CapacityError),
    /// 内容镜像里的状态元数据读不出来 / 表示不了（[`crate::status_bind::BindError`]）。
    ///
    /// 这是一个**新加的变体**（本轮任务之前没有）：它原来是挤在 [`Self::Modifier`] 里的 ——
    /// 而 `Modifier` 的语义是"修饰器管线拒绝了这次计算，本应不可达"，与"内容说了一件我们还不懂的
    /// 事"（`Pipeline: "CardCost"`、`Operation: ClampMax`、非 null 的 `RestrictElement`…）
    /// 完全不是同一种拒绝。**合并变体会让"为什么不生效"变成猜谜**，所以单独给一个。
    Bind(BindError),
    /// 修饰器管线拒绝了这次计算（本应不可达；出现即说明 v1 的候选表构造有 bug）。
    ///
    /// ⚠️ 也被借来表达**受理不变量**的违约：负的伤害/格挡/治疗/状态层数在参考里是
    /// 抛 `ArgumentOutOfRangeException` 让整个 program fault（`DamageEffects.cs:50-51,338-339`、
    /// `DefensivePoolEffects.cs:15-16`、`StatusEffects.cs:55-62`），而冻结的枚举没有
    /// `NegativeAmount` 变体。这一处借用**是有意的**（宁可响亮失败，也不把负数当 0 执行），
    /// 单测 `negative_amounts_are_refused_through_the_modifier_bucket` 钉住它。
    Modifier,
}

impl From<IrError> for ExecError {
    fn from(e: IrError) -> Self {
        ExecError::Ir(e)
    }
}
impl From<ExprError> for ExecError {
    fn from(e: ExprError) -> Self {
        ExecError::Expr(e)
    }
}
impl From<SelError> for ExecError {
    fn from(e: SelError) -> Self {
        ExecError::Sel(e)
    }
}
impl From<CapacityError> for ExecError {
    fn from(e: CapacityError) -> Self {
        ExecError::Capacity(e)
    }
}
impl From<BindError> for ExecError {
    fn from(e: BindError) -> Self {
        ExecError::Bind(e)
    }
}

/// 执行上下文：**拥有对状态的独占可变借用**，外加三个目标槽与一个卡实例槽。
///
/// 四个槽与 [`crate::expr::ExprContext`] 一一对应，执行时每次求值临时构造后者。
///
/// [`Self::content`] 是"这一条走哪套状态元数据"的开关（见模块头那张表）：
/// `Some(镜像)` ⇒ 极性/修饰器都从镜像读、命名空间桥一刀不用；`None` ⇒ 标准包路径。
#[derive(Debug)]
pub struct ExecContext<'a> {
    pub state: &'a mut CombatState,
    pub source: Option<CombatantId>,
    pub event_target: Option<CombatantId>,
    pub iteration_target: Option<CombatantId>,
    /// `forEachCardInZone` 当前迭代的卡实例（`cardInstance.iterated` 读它）。
    ///
    /// 与 `iteration_target` 分开是因为参考里 `ForEachTarget` 和 `ForEachCardInZone`
    /// 绑的是两种东西、而且可以互相嵌套。**只有控制流节点会写它**，
    /// 而且必须在退出时**无条件**恢复（含 Body 报错的路径）。
    pub iteration_card: Option<CardInstanceId>,
    /// §225：**正在结算的那张牌**（出牌时由 `play.rs` 填）。
    ///
    /// 为什么需要：`Second Wind` 的循环快照里会看到**它自己** —— 打出的牌要到终态回调才离开手牌
    /// （参考的落区也是在 `onTerminal`），而循环在结算期间跑。参考语义里"打出的牌已经不在手牌"，
    /// 所以这里让程序**知道**是哪一张，`forEachCardInZone` 的快照把它跳过。
    ///
    /// ⚠️ 不改成"打出时就把牌搬走"：那会改变每一步哈希里的牌区计数，直接打破与 C# oracle 的
    /// 逐字节契约（`CARD_DIFF` / `FIGHT_DIFF`）。牌留在原处，只是程序看得见它。
    pub resolving_card: Option<CardSlot>,
    /// 节目信封里的 `MaxProgramSteps`（core 镜像实测 1024）。
    pub max_steps: u32,
    /// 触发事件的**布尔事实**，按位。今天只有"这张牌有没有某个 tag"这四种
    /// （`exec::CARD_HAS_TAG_*`），由宿主在派发 `CardPlayed` 时算好。
    ///
    /// 为什么不把卡实例塞进表达式上下文：那要把 `Content` 的寿命也拖进 `ExprContext`，
    /// 而这四个比特是**唯一**被用到的信息（`port-plan.md` §118）。
    pub event_flags: u16,
    /// §195.1：当前事件带的**数量**（`eventAmount` 读它）。今天只有伤害事件会填；`None` 与 `0`
    /// 严格区分（见 `expr::eval_int` 的 `eventAmount` 分支）。
    pub event_amount: Option<i32>,
    /// 内容镜像。`Some` ⇒ 状态元数据走 [`crate::status_bind`]（参考实现的路）；
    /// `None` ⇒ 走标准包目录（oracle/env 的路）。**只有它决定命名空间桥开不开**。
    pub content: Option<&'a Content<'a>>,
    /// **X 费牌的 X**（§146）。0 = 这一次出牌没有 X（绝大多数节目）。
    pub x_cost: i32,
}

/// 执行统计。做成返回值是为了让测试能断言"确实做了事"，而不是只看状态。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct ExecStats {
    /// 执行过的节点数（含控制流节点）。
    pub nodes: u32,
    /// 对目标**发起过**一次效果的次数（一次 `dealDamage` 打 2 个目标算 2 次）。
    ///
    /// 口径是"节点对一个目标出的那一次手"，**不是**"状态真的变了"：参考里每个目标都会
    /// 入队一个 effect request，处理函数自己可能什么都不写（`modifyStatusStacks` 找不到那个状态、
    /// `gainResource` 撞上上限、`drawCards` 两堆都空）。那些情况仍然记 1 次 ——
    /// 它和"根本没走到这个目标"是两件事，测试要能分开（见 `e2e_15c`）。
    /// `createCardInstance` 是唯一按**卡**记的（造 3 张记 3 次），因为它一张卡一次写入。
    pub effects: u32,
}

impl<'a> ExecContext<'a> {
    /// 只给状态与三个目标槽 —— `content = None`（标准包路径）。
    ///
    /// 之所以要有构造函数：`content` 这条新字段会打断**每一个** `ExecContext { … }` 字面量，
    /// 而"标准包路径"是绝大多数调用点的意思。要接镜像就 `…new(…).with_content(content)`。
    #[must_use]
    pub fn new(
        state: &'a mut CombatState,
        source: Option<CombatantId>,
        event_target: Option<CombatantId>,
        iteration_target: Option<CombatantId>,
        max_steps: u32,
    ) -> Self {
        Self {
            state,
            source,
            event_target,
            iteration_target,
            iteration_card: None,
            resolving_card: None,
            max_steps,
            event_flags: 0, event_amount: None,
            content: None,
            x_cost: 0,
        }
    }

    /// 接上内容镜像（状态元数据改从 `STAT` 表读，命名空间桥关闭）。
    #[must_use]
    pub fn with_content(mut self, content: &'a Content<'a>) -> Self {
        self.content = Some(content);
        self
    }

    /// 带上这次出牌的 **X**（§146）。只有 X 费牌的节目需要它，其余一律 0。
    #[must_use]
    pub fn with_x_cost(mut self, x_cost: i32) -> Self {
        self.x_cost = x_cost;
        self
    }

    /// 三个目标槽 → 表达式求值上下文（逐字搬运，见 [`crate::expr::ExprContext`]）。
    ///
    /// ⚠️ **卡实例槽故意不在这里出现**：`iteration_card` 只在
    /// `forEachCardInZone` 的循环体里非空，而它是通过
    /// [`Self::with_iteration_card`] 临时装上的。
    fn expr_context(&self) -> ExprContext<'_> {
        ExprContext {
            state: self.state,
            source: self.source,
            event_target: self.event_target,
            iteration_target: self.iteration_target,
            iteration_card: self.iteration_card,
            resolving_card: self.resolving_card,
            content: self.content.copied(),
            event_flags: self.event_flags,
            event_amount: self.event_amount,
            x_cost: self.x_cost,
        }
    }

    /// 三个目标槽 → 选择器解析上下文（与 [`Self::expr_context`] 同一套搬运）。
    fn selection_context(&self) -> SelectionContext<'_> {
        SelectionContext {
            state: self.state,
            source: self.source,
            event_target: self.event_target,
            iteration_target: self.iteration_target,
        }
    }
}

// =============================================================================================
// 常量
// =============================================================================================

/// `standard.block`（`StandardCombatIds.cs:5`）—— 标准包唯一注册的防御池，
/// 也是 `GainBlockEffectHandler` 唯一写入的池（`DefensivePoolEffects.cs:44-72`）。
const BLOCK_POOL_ID: &str = "standard.block";

/// 三条**伤害管线里的状态**（§149）。id 是内核侧的约定（与 `standard.metallicize` 同型）：
/// 内容声明这一行，内核在这一行上动手。
///
/// * `standard.intangible` —— 进来的伤害与掉血压到 **1**；
/// * `standard.buffer` —— 挡住**下一次**掉血（消耗 1 层）；
/// * `standard.plated_armor` —— 挨到"没被挡住的伤害"时掉 1 层（另一半在 `host`，回合结束给格挡）。
const BUFFER_STATUS: &str = "standard.buffer";

/// 给 `definition` 减 **1 层**；减到 0 就把实例删掉。返回是否真的减了（没有这条实例 ⇒ `false`）。
///
/// "删掉"和"留一条 0 层实例"仍然不是等价物（理由同 `remove_status_at`：0 层实例会出现在
/// `statuses()`、快照与哈希的 `s=` 行里，还占容量）。
fn consume_one_status_stack(
    state: &mut CombatState,
    target: &CombatantId,
    definition: &str,
) -> Result<bool, ExecError> {
    let Some(combatant) = state.combatant(target) else {
        return Ok(false);
    };
    if !carries_status(state, target, definition) {
        return Ok(false);
    }
    let position = combatant
        .statuses()
        .iter()
        .position(|status| status.definition_id.as_str() == definition && status.stacks > 0);
    let Some(index) = position else {
        return Ok(false);
    };
    let combatant = state
        .combatant_mut(target)
        .ok_or(ExecError::MissingCombatant)?;
    let Some(instance) = combatant.statuses_mut().get_mut(index) else {
        return Err(ExecError::Modifier);
    };
    instance.stacks -= 1;
    if instance.stacks <= 0 {
        combatant.remove_status(index);
    }
    Ok(true)
}

/// 这个战斗员身上是否戴着 `definition`（层数 > 0 的**第一条**实例就够）。
/// 读一个战斗员身上**能救命**的那条 `DeathPrevention` 状态（§180）。
///
/// 返回 `(状态 id, 这一下之后剩多少血, 是否重复)`。`None` = 他身上没有这类状态，或者内容里
/// 那条数据读不出来 —— 两种都走"照常倒下"。
///
/// ⚠️ 这不是"静默降级"：这条分支只在**血量已经到 0** 时被调用，它的输出是"活下来还是死"；
/// 而"内容里的 `DeathPrevention` 写坏了"该由 `the_status_catalogue_is_honest` 在构建期喊，
/// 不该在一场战斗的最后一下里抛异常（那时候状态已经改了一半）。
///
/// 血量公式：`max(SurvivingHealth, 最大生命 * Percent / 100, 1)`。`Percent` 是本移植的扩展 ——
/// 参考的 `StatusDeathPreventionData` 只有平值，表达不了 wiki 的 "30% of Max HP"。
fn death_prevention_for(
    ctx: &ExecContext<'_>,
    target: &CombatantId,
) -> Result<Option<(crate::state::StatusDefinitionId, i32, bool)>, ExecError> {
    let Some(content) = ctx.content else {
        return Ok(None);
    };
    let Some(combatant) = ctx.state.combatant(target) else {
        return Ok(None);
    };
    let max_health = combatant.health_max;
    // Copy the definitions out first: the loop below reads the *content*, and holding a borrow of
    // the combatant's status list across that would tie two unrelated lifetimes together.
    let mut candidates = [crate::state::StatusDefinitionId::EMPTY; 16];
    let mut count = 0usize;
    for status in combatant.statuses() {
        if count == candidates.len() {
            break;
        }
        if status.stacks <= 0 {
            continue;
        }
        candidates[count] = status.definition_id;
        count += 1;
    }
    for definition in &candidates[..count] {
        let mut buffer = [0u8; 64];
        let text = definition.as_str();
        if text.len() >= buffer.len() {
            continue;
        }
        buffer[..text.len()].copy_from_slice(text.as_bytes());
        let Ok(name) = core::str::from_utf8(&buffer[..text.len()]) else {
            continue;
        };
        let Ok(Some(data)) = crate::status_bind::death_prevention(content, name) else {
            continue;
        };
        let percent = max_health.saturating_mul(data.percent) / 100;
        let surviving = data.surviving_health.max(percent).max(1);
        return Ok(Some((*definition, surviving, data.repeating)));
    }
    Ok(None)
}

fn carries_status(state: &CombatState, id: &CombatantId, definition: &str) -> bool {
    state
        .combatant(id)
        .map(|combatant| {
            combatant
                .statuses()
                .iter()
                .any(|status| status.definition_id.as_str() == definition && status.stacks > 0)
        })
        .unwrap_or(false)
}

/// `ForEachTargetEffectNode.DefaultMaxIterations = 32`（`EffectProgramNodes.cs:249`）。
///
/// 镜像实测 6 条 `node.forEachTarget` 的 `MaxIterations` **全是 32**（即序列化后的默认值），
/// 所以"缺席就用 32"这条今天走不到 —— 留它是因为参考的构造函数的默认值就是它，
/// 而"缺席"在本层是合法的（`F_INT` 的 `ABSENT`）。
const DEFAULT_MAX_ITERATIONS: i32 = 32;

/// `ForEachCardInZoneNode.DefaultMaxIterations = 64`（`EffectProgramNodes.cs:290`）。
/// 镜像实测 2 条 `node.forEachCardInZone` 的 `MaxIterations` 都是 64（即序列化后的默认值），
/// 所以"缺席就用 64"这条今天走不到 —— 留它是因为参考的构造函数默认值就是它。
const DEFAULT_CARD_IN_ZONE_MAX_ITERATIONS: i32 = 64;

/// `RepeatEffectNode.DefaultMaxCount = 32`（`EffectProgramNodes.cs:119`，§146）。
///
/// 超过就**抛**（参考逐字：`count > MaxCount ⇒ InvalidOperationException`），不截断。
const REPEAT_DEFAULT_MAX_COUNT: i32 = 32;

/// `CreateCardInstanceNode` 的 `count ?? new ConstantExpression(1)`
/// （`EffectProgramNativeNodes.cs:911`）—— `Count` 缺席 ⇒ **1 张**。
const DEFAULT_CARD_INSTANCE_COUNT: i32 = 1;

/// §250：`node.offerRandomCards` 的默认候选数（StS 的 "choose 1 of 3"）与它的上限。
///
/// 上限与 `MAX_SELECTED_CARDS` 同一个理由：候选表是**定容**的（`Container::ChoiceOptions`），
/// 而"内容写了 200"会让 `Bounded::push` 在跑了一半的时候失败 —— 那是部分执行。
pub const MAX_OFFERED_CARDS: usize = 8;
const DEFAULT_OFFERED_CARDS: i32 = 3;

/// 一次 `sequence` 最多几个孩子。
///
/// 实测（core 镜像全表）：最长的 `Children` 是 **5**（`EnemyActions[218]`）。这里给 32 是 6 倍余量；
/// 超界 ⇒ [`IrError::List`]（**不截断**：少跑几个孩子比报错糟得多，见 `ir.rs` 的 `list_field`）。
const MAX_CHILDREN: usize = 32;

/// 一层管线里最多几条候选。
///
/// 两个来源、两种上界：
///
/// * **标准包**（`content == None`）：伤害表 **3 行**、格挡表 **2 行**。
/// * **镜像**（`content == Some`）：每条候选来自"一个在身状态定义的一条 spec"
///   （`PassiveModifiers.cs:142-172` 的 `GroupBy(DefinitionId)`），而一个战斗员最多
///   [`crate::state::MAX_STATUSES_PER_COMBATANT`] = 24 条状态实例 ⇒ 取 **24**。
///   镜像实测每个状态最多 1 条 spec、且只有 5 个状态有 spec，所以真实用到的远小于 8；
///   取满 24 是为了"一个挂着 10 个 buff 的后期战斗"不会撞上**本来不需要**的硬失败。
///
/// 超出就是 [`ExecError::Modifier`] 响亮失败（**不静默丢弃候选**）：一个状态在同一管线里带
/// 2 条以上的 spec 时会超（24 条状态 × 2 条 = 48），那是"内容用了 v1 撑不住的形状"，
/// 应当报错而不是算少。
const MAX_CANDIDATES: usize = crate::state::MAX_STATUSES_PER_COMBATANT;

/// 状态 id 备份池容量：`MAX_CANDIDATES × ID_CAP(40)`。
///
/// 这个数**可证够用**：候选 ≤ 24 条（每条来自一个不同的状态定义），每个 id ≤
/// [`crate::state::ID_CAP`] = 40 B（内核自己的 id 类型上限），所以池永远不会成为瓶颈 ——
/// 真溢出只可能是调用违约，那时 [`intern`] 报 [`ExecError::Modifier`]。
const STATUS_ID_POOL_CAP: usize = MAX_CANDIDATES * ID_CAP;

/// 节点树深度上限（参考的 `MaxNodeDepth=64`，`docs/spec/effect-program-ir.md` §4.2）。
///
/// 它挡的不是"程序写得太深"，而是**镜像被改坏时的环**：`NodeRef` 是 term DAG 的视图，
/// 一个自指的孩子会让递归无限深。步数预算已经能终止（每进一层都 +1），但 1024 层递归在裸机上
/// 会先吃光栈 —— 所以先按参考的 64 层拦。
const MAX_NODE_DEPTH: u32 = 64;

/// 候选表的"空槽"。`Candidate` 没有 `Default`，而 `[T; N]` 的初始化要一个值。
const NO_CANDIDATE: Candidate = Candidate {
    priority: 0,
    status_key: StatusKey { offset: 0, len: 0 },
    spec_index: 0,
    stacks: 0,
    cards_played_this_turn: 0,
    operation: Operation::AddFlat,
    magnitude: 0,
    once_per_action: false,
    once_per_turn: false,
};

/// §216：**这条管线没有"本回合牌数"这个量**。`fold` 见到它就说明有人把 `Slow` 挂到了别的管线上
/// （格挡、回合开始抽牌/补能）—— 那是内容错误，必须响亮，而不是安静地按恒等算。
const NO_TURN_CARDS: i32 = -1;

/// 目录里**真实存在**的 5 个"伤害/格挡修饰状态" —— 见模块头假设 A。
///
/// 只列这 5 条（**不做通用前缀剥离**）：`status_catalog` 的两张修饰表就只有这 5 个 id，
/// 多一个都不是"桥"，而是猜。
///
/// ⚠️ **`content == Some` 时这张表一条都不许用**（[`StatusMatch::Exact`]）。
const NAMESPACE_BRIDGE: [(&str, &str); 5] = [
    ("standard.strength", "strength"),
    ("standard.weak", "weak"),
    ("standard.vulnerable", "vulnerable"),
    ("standard.dexterity", "dexterity"),
    ("standard.frail", "frail"),
];

// =============================================================================================
// 入口
// =============================================================================================

/// 执行一棵效果程序**并把它排空到静止**（测试与独立调用方的入口）。
///
/// 它 = [`begin`] + [`drain`] + 读回统计。**宿主路径不用它**：宿主自己拥有排空循环
/// （`host.rs::resolve_pending_queues_with`），因为事件相位要它来分发。
///
/// 顺序：预检（参考的 `ValidateNodeExecutors`）→ 派发 → 排空。
///
/// 战斗已经结束（`state.result != Ongoing`）时**什么都不做**并返回零统计：参考的三队列循环
/// 条件是 `while (hasPending) && Result == Ongoing`（`CombatEventHandling.cs:99-111`），
/// 所以战斗一结束，入队的 effect 再也不会解析 —— 等价于"整个程序不落地"。
pub fn execute(root: NodeRef<'_>, ctx: &mut ExecContext<'_>) -> Result<ExecStats, ExecError> {
    // 预检：整棵树先验一遍（`:23,184-196`）。任何**结构上不可执行**的东西都在这里拒绝，
    // 绝不部分执行（W4f 之后 15 种节点全能跑，剩下的闸门是 ResultKey 与 DefinitionFilter）。
    let mut check = Walk::default();
    preflight(root, preflight_budget(ctx.max_steps), &mut check)?;

    let mut stats = ExecStats::default();
    if ctx.state.result != CombatResult::Ongoing {
        return Ok(stats);
    }

    // ⚠️ **这是遗留入口（批次 2 起）**：它自己**不发号**。
    // 调用方（`intent.rs::execute_action`、`play.rs` 的旧写法和本文件的测试）已经手工记过
    // "请求"与"收尾"那两笔（`create_root_effect_chain` / `allocate_program_execution_id`），
    // 所以这里只把那条链**建出来**（编号沿用调用方刚发掉的那个），不推进任何计数器。
    //
    // 宿主与出牌走的是 [`begin`] —— 那里照参考的 `??` 发号（`EffectProgramExecution.cs:27/31`）。
    let Some(run) = open_frame(root, ctx, ProgramTerminalHook::None, FrameAllocation::CallerOwned)?
    else {
        return Ok(stats);
    };
    let outcome = drain_into(ctx.state, ctx.content, Some(root), &mut stats);
    // 把帧上的迭代绑定还原到调用方的 `ctx`（参考：作用域在 continuation 里**无条件**关闭，
    // 所以 `forEachTarget` / `forEachCardInZone` 跑完（或报错）之后，外层上下文原样保留）。
    // 这一步必须在 `reap_frames` **之前**：帧回收之后就没地方读了。
    if let Some(record) = ctx.state.program_frames().get(run.frame).copied() {
        ctx.iteration_target = record.iteration_target;
        ctx.iteration_card = record.iteration_card;
    }
    reap_frames(ctx.state);
    outcome?;
    // 派发期与续延期（循环的下一趟）都要算进统计：`stats.nodes` = 分派过的节点数。
    stats.nodes = stats.nodes.saturating_add(run.stats.nodes);
    stats.effects = stats.effects.saturating_add(run.stats.effects);
    Ok(stats)
}

/// 派发一个节目的根节点（参考 `EffectProgramExecutor.Execute`，`EffectProgramExecution.cs:7-64`）。
///
/// 返回 `None` = 战斗已经结束 ⇒ 一帧都没建（与参考的 `while … Result == Ongoing` 同效）。
///
/// ⚠️ **它只派发，不排空**：效果请求被塞进队列，节点完成被塞进续延队列。真正让它们落地的是
/// 排空循环（宿主的相位 1/3、或 [`drain`]）。这正是"请求 + 解析"这条拆分的意思。
pub fn begin<'c>(
    root: NodeRef<'_>,
    ctx: &mut ExecContext<'c>,
    hook: ProgramTerminalHook,
) -> Result<Option<ProgramRun>, ExecError> {
    let mut check = Walk::default();
    preflight(root, preflight_budget(ctx.max_steps), &mut check)?;
    begin_without_preflight(root, ctx, hook)
}

/// [`begin`] 去掉预检的内核（[`execute`] 已经自己预检过一次）。
fn begin_without_preflight(
    root: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    hook: ProgramTerminalHook,
) -> Result<Option<ProgramRun>, ExecError> {
    open_frame(root, ctx, hook, FrameAllocation::Fresh)
}

/// 帧是谁发的号。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum FrameAllocation {
    /// 参考的 `Execute`：**这里**发执行号（`:27`）与节目链（`:31` 的 `??`）。
    Fresh,
    /// 遗留入口（[`execute`]）：调用方已经发过这两个号，这里只**建链**、不推进计数器。
    CallerOwned,
}

fn open_frame(
    root: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    hook: ProgramTerminalHook,
    allocation: FrameAllocation,
) -> Result<Option<ProgramRun>, ExecError> {
    let mut stats = ExecStats::default();
    if ctx.state.result != CombatResult::Ongoing {
        return Ok(None);
    }

    // `EffectProgramExecution.cs:27`：每跑一个节目发一次号（**包括触发器节目**）。
    let execution_number = match allocation {
        FrameAllocation::Fresh => ctx.state.allocate_program_execution_id(),
        FrameAllocation::CallerOwned => ctx.state.next_program_execution_id.saturating_sub(1),
    };
    // `:31`：`executionContext.EffectChain ??= combat.CurrentEffectChain ?? combat.CreateRootEffectChain()`。
    // ⇒ 顶层跑一个节目**会发一个号**；在链里跑（效果解析、事件分发）**不发**。
    //
    // 引用计数：建出来的那条带 refs = 1（归我们）；**借用**别人的那条要 `acquire`，
    // 因为 `reap_frames` 会无条件 `release` 一次。不这么做的话，每跑一个顶层节目都会
    // 漏掉一条链（128 条以后 `Capacity(Full(Chains))` —— 实测踩到过）。
    let chain = match (ctx.state.current_chain(), allocation) {
        (ChainSlot::NONE, FrameAllocation::Fresh) => ctx.state.new_root_chain_in_arena()?,
        // 遗留入口：链号由调用方发过 ⇒ 只建链（`id` 沿用那个号），不再推进计数器。
        (ChainSlot::NONE, FrameAllocation::CallerOwned) => ctx.state.adopt_root_chain()?,
        (chain, _) => {
            ctx.state.acquire_chain(chain)?;
            chain
        }
    };
    let frame = ctx.state.program_frames_mut().alloc(ProgramExecutionFrame {
        execution_number,
        root: root.id(),
        chain,
        source: ctx.source,
        target: ctx.event_target,
        iteration_target: ctx.iteration_target,
        iteration_card: ctx.iteration_card,
        event_flags: ctx.event_flags,
        resolving_card: ctx.resolving_card,
        entry_iteration_target: ctx.iteration_target,
        entry_iteration_card: ctx.iteration_card,
        steps: 0,
        max_steps: ctx.max_steps,
        // §146：X 从**建立帧的那一刻**的上下文取，之后每一趟续延都从帧恢复。
        x_cost: ctx.x_cost,
        state: ProgramFrameState::Running,
        terminal_chain: ChainSlot::NONE,
        hook,
        live: true,
    })?;

    // `:60-61` 的 `using (combat.EnterEffectChain(executionContext.EffectChain)) ExecuteNode(root)`。
    // 闭包在这里**立刻调用**（§4.1.3 允许的唯一一种闭包用法）；用 `set_current_chain` 是因为
    // 闭包要同时借 `ctx`（它自己握着 `&mut CombatState`）。
    let previous = ctx.state.current_chain();
    ctx.state.set_current_chain(chain);
    let outcome = dispatch_node(root, ctx, frame, NO_NODE_SLOT, 0, &mut stats);
    ctx.state.set_current_chain(previous);
    if let Err(error) = outcome {
        // `ExecuteNode` 的 catch（`EffectProgramExecution.cs:151-159`）：帧 MarkFaulted
        // ⇒ 终态回调**当场**跑（出牌因此仍会落区，见 `Cards/CardPlay.cs:254-261`）。
        // 注意 `when (frame is { IsTerminal: false })`：已经在终态就不再处理。
        finish_frame(ctx.state, frame, ProgramFrameState::Faulted)?;
        return Err(error);
    }

    Ok(Some(ProgramRun { frame, stats }))
}

/// 一条 `ProgramResume` 续延（`CombatEventHandling.cs:107-111` 的 `c(combat)`）。
///
/// ⚠️ **它跑在顶层**：宿主在调用它之前把效果/事件两相都抽空了，而且 `with_chain` 的作用域
/// 已经退出 ⇒ 此刻 `current_chain` 是 `NONE`。这个位置本身就是语义：谁最后完成，决定了节目
/// 终态回调里的 `EnqueueEffect`/`EnqueueEvent` 会不会 `?? CreateRootEffectChain()`。
pub fn resume(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    anchor: Option<NodeRef<'_>>,
    frame: ProgramExecutionSlot,
    slot: u16,
) -> Result<(), ExecError> {
    let mut stats = ExecStats::default();
    resume_with_stats(state, content, anchor, frame, slot, &mut stats)
}

/// [`resume`] 带统计的版本（排空循环自己有一份要累加）。
pub fn resume_with_stats(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    anchor: Option<NodeRef<'_>>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    if state.program_frames().get(frame).is_none() {
        // 帧已经被回收（战斗结束取消 / 重置）：这条续延是**陈旧**的，照参考丢弃
        // （`EffectProgramExecution.cs:51-54`："A stale completion can arrive after the frame
        // was cancelled … ignore it"）。**不是**静默吞错：帧不在就没有"谁"可完成。
        return Ok(());
    }
    complete(state, content, anchor, frame, slot, stats)
}

/// 排空"效果队列 + 节目续延"，直到静止（**不碰事件队列**）。
///
/// 这不是第二个排空循环，它是宿主那个循环的**相位 1 + 相位 3**，抽出来给两个调用方用：
/// 宿主的 `resolve_pending_queues_with`（它中间夹相位 2）与独立调用方（[`execute`]、
/// `play::play_card`）。相位门禁（"前两相都空才跑续延"）由两个循环各自守：
///
/// * 宿主守**完整**的三相位门禁（`has_pending_effects && has_pending_events` 都空）；
/// * 本函数没有事件分派器，所以它只等效果队列空。
///
/// ⚠️ **这个差别必须说出来**：没有分派器时，一条已入队的事件**不产生任何后果**（触发器分发
/// 是 `host.rs` 的事）⇒ 在本层"事件待处理"与"事件不存在"观察等价。宿主路径没有这个等价，
/// 它的门禁由 `host.rs` 的 `a_continuation_waits_for_the_drain_and_runs_at_the_top_level` 钉着。
fn drain_into(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    anchor: Option<NodeRef<'_>>,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    drain_until_still(state, content, anchor, stats)
}

/// [`drain_into`] 的实体（不含回收）。
fn drain_until_still(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    anchor: Option<NodeRef<'_>>,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let mut cycles = 0u32;
    loop {
        if state.result != CombatResult::Ongoing {
            return Ok(());
        }
        // 相位 1：效果队列。
        while state.has_pending_effects() && state.result == CombatResult::Ongoing {
            let Some(item) = state.dequeue_effect()? else {
                break;
            };
            let chain = item.chain;
            let outcome = state.with_chain(chain, |state| resolve_effect(state, &item, content));
            state.release_chain(chain);
            if let Err(e) = outcome {
                // 解析抛错 ⇒ 绑回发起它的帧（`owner` 就是干这个的，§1.2 末）。
                fail_owner(state, item.owner, e)?;
                return Err(e);
            }
            if state.result != CombatResult::Ongoing {
                cancel_live_frames(state, chain)?;
                return Ok(());
            }
        }
        // 相位 2 **故意不动事件队列**：本层没有触发器分派器（那是 `host.rs` 的事），
        // 而**把事件出队丢掉**等于把它交给谁的责任推掉 —— 事件的唯一消费者就是触发器分发，
        // 少了它 `doubt` 那条 `DamageDealt` 触发器就永远不跑（CARD_MULTI 那 10 格立刻退回
        // "不可对照"，实测过一次）。⇒ 事件**原样留在队列里**，等宿主来分发。
        //
        // 代价：本层跑完一个节目后 `has_pending_events()` 可能为真。相位 3 的门禁
        // （前两相都空才跑续延）因此在这里**不成立** —— 本函数只等效果队列空。
        // 真正的三相位门禁由 `host::resolve_pending_queues_with` 守，它的测试钉着那一条。
        // 相位 3：**只跑一个**续延。
        if !state.has_pending_continuations() {
            return Ok(());
        }
        if cycles >= MAX_QUEUE_CYCLES {
            return Err(ExecError::Capacity(CapacityError::Full(
                Container::PendingContinuations,
            )));
        }
        if let Some(continuation) = state.try_dequeue_continuation() {
            run_continuation(state, content, anchor, continuation, stats)?;
        }
        cycles += 1;
    }
}

/// 跑一条续延（相位 3 的唯一入口，宿主与 [`drain_into`] 共用）。
fn run_continuation(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    anchor: Option<NodeRef<'_>>,
    continuation: Continuation,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    match continuation {
        Continuation::ProgramResume { frame, node } => {
            resume_with_stats(state, content, anchor, frame, node, stats)
        }
        Continuation::CloseAction { actor } => {
            // 出牌收尾那一笔由 `play::close_action` 负责（同一个函数，别抄第二份）：
            // 它内部那句 `EnqueueEvent(ActionResolved)` 的链规则见那里。
            crate::play::close_action(state, actor);
            Ok(())
        }
    }
}

/// 排空"效果队列 + 节目续延"直到静止（**不碰事件队列**）。
///
/// 给两个**不拥有宿主**的调用方用：`exec::execute`（测试/独立调用）与
/// `play::play_card`（严格面自己排空，`Cards/CardPlay.cs:108`）。
/// 宿主有自己的三相位循环（[`crate::host::Host::resolve_pending_queues_with`]），它中间要夹
/// 相位 2 —— 那一层才是参考的门禁，这里的注释写明了差别（见 [`drain_into`]）。
pub fn drain(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    anchor: Option<NodeRef<'_>>,
) -> Result<(), ExecError> {
    let mut stats = ExecStats::default();
    let outcome = drain_into(state, content, anchor, &mut stats);
    // 独立调用方（`play::play_card`）没有帧可读 ⇒ 排空结束就地回收。
    // 空闲帧不占语义，只占一个槽（`MAX_PROGRAM_FRAMES`），所以"静止点即回收"是对的。
    reap_frames(state);
    outcome
}

/// 解析失败 ⇒ 把发起它的帧打成 Faulted 并跑它的终态回调
/// （`FaultDueToNativeHandler`，`EffectProgramIdentity.cs:156-162`）。
pub fn fail_frame(
    state: &mut CombatState,
    owner: Option<ProgramExecutionSlot>,
) -> Result<(), ExecError> {
    let Some(frame) = owner else {
        return Ok(());
    };
    finish_frame(state, frame, ProgramFrameState::Faulted)
}

/// 相位 1 的一条效果：**把请求解析成状态变化**（`DamageEffects.cs` / `StatusEffects.cs` …）。
///
/// 这一层只做"解开发起方给的那几格"：金额、目标、状态定义都是**派发时**求好的
/// （`EffectProgramNodeExecutors.cs` 那 11 个 `EnqueueEffect` 的实参），修饰器/极性与
/// 上限判定则**在这里**才读（`DamageEffects.cs:273-320` 读的是解析那一刻的状态）。
pub fn resolve_effect(
    state: &mut CombatState,
    item: &EffectItem,
    content: Option<&Content<'_>>,
) -> Result<(), ExecError> {
    let request = item.request;
    // §178: **a request whose target left the fight is dropped.**
    //
    // The target existed when the request was *enqueued* (`deal_damage_node` resolves the selector
    // then), and the drain can run much later. `node.destroyCombatant` is the first thing in the
    // engine that can make a target disappear in between -- and the very case it exists for is a
    // multi-hit turn: the first hit splits the Slime Boss (the boss is removed), and hits two and
    // three are already queued against it. Throwing `MissingCombatant` there would kill a fight
    // that StS just continues ("damage to a corpse is nothing").
    //
    // ⚠️ This is **not** the same as a caller addressing a phantom: `resolve_damage` (the direct
    // entry used by card play and DoT) still fails loudly on a missing target, because there the id
    // was just handed to it by someone who should have known better.
    if let Some(target) = request_target(&request) {
        if state.combatant(&target).is_none() {
            return Ok(());
        }
    }
    let mut ctx = ExecContext::new(
        state,
        request_source(&request),
        match request {
            EffectRequest::DealDamage { target, .. }
            | EffectRequest::GainBlock { target, .. }
            | EffectRequest::ApplyStatus { target, .. }
            | EffectRequest::ModifyStatusStacks { target, .. }
            | EffectRequest::Heal { target, .. }
            | EffectRequest::SetCombatantCounter { target, .. }
            | EffectRequest::GainResource { target, .. }
            | EffectRequest::LoseResource { target, .. } => target,
            EffectRequest::DrawCards { .. }
            | EffectRequest::CreateCardInstance { .. }
            | EffectRequest::CreateRandomCard { .. }
            | EffectRequest::PlayTopCardOfDrawPile { .. }
            | EffectRequest::ShuffleDiscardIntoDraw { .. }
            | EffectRequest::MoveCardToZone { .. }
            // §254：见 `request_target` 的同一条注释。
            | EffectRequest::PlayCard { .. }
            | EffectRequest::EndTurn => None,
            EffectRequest::ExtraTurn { target } => target,
        },
        None,
        // 解析器**一个节点都不派发** ⇒ 步数预算无关。写 0 让"用错"当场报错。
        0,
    );
    if let Some(content) = content {
        ctx.content = Some(content);
    }
    resolve_request(&mut ctx, &request)
}

/// 请求指向的战斗员（`None` = 这条请求不针对某个战斗员）。
///
/// 与 [`resolve_effect`] 里那张表同源：新增变体时两处都要动，否则新变体会被当成
/// "没有目标"而跳过错位检查 —— 所以这里写成**穷尽** `match`（没有 `_` 臂）。
const fn request_target(request: &EffectRequest) -> Option<CombatantId> {
    match request {
        EffectRequest::DealDamage { target, .. }
        | EffectRequest::GainBlock { target, .. }
        | EffectRequest::ApplyStatus { target, .. }
        | EffectRequest::ModifyStatusStacks { target, .. }
        | EffectRequest::Heal { target, .. }
        | EffectRequest::SetCombatantCounter { target, .. }
        | EffectRequest::GainResource { target, .. }
        | EffectRequest::LoseResource { target, .. }
        | EffectRequest::ExtraTurn { target } => *target,
        EffectRequest::DrawCards { .. }
        | EffectRequest::CreateCardInstance { .. }
        | EffectRequest::CreateRandomCard { .. }
        | EffectRequest::PlayTopCardOfDrawPile { .. }
        | EffectRequest::ShuffleDiscardIntoDraw { .. }
        | EffectRequest::MoveCardToZone { .. }
        // §254：`PlayCard` 不针对战斗员（它的 `target` 是"给这张牌指定的出牌目标"，
        // 与"这条请求针对谁"不是一回事）—— 所以不进那张存在性检查表。
        | EffectRequest::PlayCard { .. }
        | EffectRequest::EndTurn => None,
    }
}

/// 请求自带的出手方（只有伤害真的用它，其余变体为 `None`）。
const fn request_source(request: &EffectRequest) -> Option<CombatantId> {
    match request {
        EffectRequest::DealDamage { source, .. } => *source,
        EffectRequest::ApplyStatus { source, .. } => *source,
        _ => None,
    }
}

/// 一条请求的**实体**。
///
/// 每个臂都只调一个既有的函数/一段既有的算术 —— 语义没有搬家，只是**时点**搬了：
/// 从"派发那一刻"搬到"排空那一刻"。
fn resolve_request(ctx: &mut ExecContext<'_>, request: &EffectRequest) -> Result<(), ExecError> {
    match *request {
        EffectRequest::DealDamage {
            target,
            amount,
            ignores_block,
            ..
        } => {
            let Some(target) = target else { return Ok(()) };
            // `DamageEffects.cs:45-54` 的受理不变量：负数金额让整个 program fault。
            if amount < 0 {
                return Err(ExecError::Modifier);
            }
            resolve_damage_of_kind(ctx, &target, amount, ignores_block, BindDamageKind::Direct)?;
            Ok(())
        }
        EffectRequest::GainBlock { target, amount, from_card } => {
            let Some(target) = target else { return Ok(()) };
            gain_block_for(ctx, &target, amount, from_card)
        }
        EffectRequest::ApplyStatus {
            target,
            definition,
            stacks,
            duration,
            charges,
            ..
        } => {
            let Some(target) = target else { return Ok(()) };
            apply_one_status(ctx, &target, definition, stacks, duration, charges)
        }
        EffectRequest::ModifyStatusStacks {
            target,
            definition,
            delta,
        } => {
            let Some(target) = target else { return Ok(()) };
            modify_one_status_stacks(ctx, &target, definition, delta)
        }
        EffectRequest::Heal { target, amount } => {
            let Some(target) = target else { return Ok(()) };
            heal_for(ctx, &target, amount)
        }
        EffectRequest::SetCombatantCounter {
            target,
            key,
            amount,
            relative,
        } => {
            let Some(target) = target else { return Ok(()) };
            set_counter_for(ctx, &target, key, amount, relative)
        }
        EffectRequest::ExtraTurn { target } => {
            if let Some(target) = target {
                ctx.state.extra_turn_for = Some(target);
            }
            Ok(())
        }
        // The kernel's own request: raise the flag, the battle loop does the advancing.
        EffectRequest::EndTurn => {
            ctx.state.end_turn_requested = true;
            Ok(())
        }
        // §231: `standard.no_draw` (Battle Trance) is honoured **here**, not in the node: a draw is a
        // draw whether it came from `node.drawCards` or from a potion's `EffectRequest::DrawCards`.
        // "Additional cards" excludes the turn-start draw, which never goes through this request.
        EffectRequest::DrawCards { owner, count } => {
            let blocked = ctx.state.combatant(&owner).is_some_and(|combatant| {
                combatant
                    .statuses()
                    .iter()
                    .filter(|instance| instance.definition_id.as_str() == "standard.no_draw")
                    .fold(0i32, |sum, instance| sum.saturating_add(instance.stacks))
                    > 0
            });
            draw_for(ctx, &owner, if blocked { 0 } else { count })
        }
        EffectRequest::GainResource {
            target,
            key,
            amount,
            default_max,
        } => {
            let Some(target) = target else { return Ok(()) };
            gain_one_resource(ctx, &target, key, amount, default_max)
        }
        EffectRequest::LoseResource {
            target,
            key,
            amount,
        } => {
            let Some(target) = target else { return Ok(()) };
            lose_resource_for(ctx, &target, key, amount)
        }
        EffectRequest::CreateCardInstance {
            owner,
            definition,
            count,
            to_zone,
            mark,
        } => create_card_for(ctx, &owner, definition, count, to_zone, mark),
        EffectRequest::CreateRandomCard {
            owner,
            tag,
            count,
            to_zone,
            cost_zero,
        } => create_random_card_for(ctx, &owner, &tag, count, to_zone, cost_zero),
        EffectRequest::PlayTopCardOfDrawPile { owner } => play_top_card_for(ctx, &owner),
        // §254：`Wish` 的那张牌 —— 与 `Havoc` 共用 `play_card_from_program`（§253）。
        EffectRequest::PlayCard {
            owner,
            card,
            target,
            ignore_unplayable,
        } => {
            let Some(content) = ctx.content else {
                return Err(ExecError::Ir(IrError::Missing("content")));
            };
            let played = crate::play::play_card_from_program(
                ctx.state,
                content,
                &owner,
                &card,
                target,
                ignore_unplayable,
            )?;
            // 参考对"打不出去"是 no-op（§253 的六种）；这里也一样 —— 但**必须**让那张牌留在
            // 原处而不是凭空消失。`play_card_from_program` 的 no-op 不改状态，所以什么都不用做。
            let _ = played;
            Ok(())
        }
        EffectRequest::ShuffleDiscardIntoDraw { owner } => {
            // 重洗 0 张不是错误（弃牌堆空 ⇒ 什么都不做，`reshuffle_discard_into_draw` 自己返回 0）。
            ctx.state
                .reshuffle_discard_into_draw(&owner)
                .map_err(ExecError::Capacity)?;
            Ok(())
        }
        EffectRequest::MoveCardToZone {
            owner,
            card,
            to_zone,
            placement,
        } => move_card_for(ctx, &owner, &card, to_zone, placement),
    }
}

/// 伤害管线：把"基础伤害"变成"实际掉的血"，返回 `(被格挡的, 实际掉血)`。
///
/// 这一步必须**走真的修饰器管线**（`crate::modifiers` + `crate::status_catalog`），
/// 而不是在 exec 里硬编码"力量 +1/层、虚弱 ×75%、易伤 ×150%"——
/// 那会把两张已经交付、已经有 31 + 17 条测试的表架空。
///
/// 顺序照参考：来源侧的 `DamageDealt` 阶段 → 目标侧的 `DamageReceived` 阶段，
/// 阶段内按 `(priority, status_id 字节序, spec_index)` 排序，运算整数截断。
///
/// **这一条恒等于 [`resolve_damage_of_kind`]`(…, Direct)`** —— 卡与敌动作打出来的伤害就是
/// `Direct`（`DamageEffects.cs` 的 `DealDamageEffectRequest.Kind` 默认值），所以老的调用点
/// 与老测试一行不用改。
///
/// 返回 `Ok((blocked, health_lost))`。
pub fn resolve_damage(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    base: i32,
    ignores_block: bool,
) -> Result<(i32, i32), ExecError> {
    resolve_damage_of_kind(ctx, target, base, ignores_block, BindDamageKind::Direct)
}

/// 同 [`resolve_damage`]，但**带伤害种类** —— 这是 DoT / 反伤唯一正确的入口。
///
/// # 为什么必须有这个参数（2026-10-17 补）
///
/// 参考实现的伤害修饰由**每条 spec 自己的门**控制
/// （`PassiveModifiers.cs:154-156`：`restrict != kind ⇒ continue`，而 `RestrictDamageKind`
/// 的默认值是 `Direct`，`:85-87`），不是"另有一条 DoT 管线"。所以"DoT 不吃力量/虚弱/易伤"
/// 这件事完全体现在 `kind` 这个实参上：
///
/// * 同一条 `DamageDealt` / `DamageReceived` 管线；
/// * `kind = Dot` 时，所有 `RestrictDamageKind = Direct` 的 spec 被自己的门挡掉
///   （标准包三行 + 镜像 5 条 spec 全是 `Direct`）；
/// * 内容若写一条 `RestrictDamageKind = null` 的 spec，它就**必须**作用于 DoT（门的第一半）。
///
/// 写成"给 DoT 另开一条管线"或"在宿主里另写一份折叠"都会架空 `crate::modifiers` 那两张
/// 已交付、已测试的表 —— 那正是本模块一直警告的事。
///
/// 三个入口：
/// * [`resolve_damage`] ⇒ `Direct`（卡 / 敌动作）；
/// * 本函数 + `Dot` ⇒ `DamageOverTimeOnTurnStartedHandler` 的 tick
///   （`StatusEffects.cs:501-509` 的 `Kind: DamageKind.DamageOverTime`）；
/// * `Reflected` 今天**没有调用点**：参考的反伤路径（`StatusEffects.cs:520-521`）在 v1 里
///   还没移植，所以 `DamageKind::Reflected` 现在是"能表达但不能产生"。
pub fn resolve_damage_of_kind(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    base: i32,
    ignores_block: bool,
    kind: BindDamageKind,
) -> Result<(i32, i32), ExecError> {
    // S0（`DamageEffects.cs:45-54`）：负数金额让整个 program fault；映射见 `ExecError::Modifier`。
    if base < 0 {
        return Err(ExecError::Modifier);
    }
    // S0：目标必须在场（参考 `combat.GetCombatant(...)` 缺席即抛）。
    if ctx.state.combatant(target).is_none() {
        return Err(ExecError::MissingCombatant);
    }

    // ── S2：数量修饰管线，Source 阶段 → Target 阶段（`DamageEffects.cs:273-320`）。
    // 两阶段**分开折叠**，因为 `modifiers::apply` 是单阶段折叠器（每个阶段后夹一次 `max(0,·)`，
    // 与 `:312` 的外层夹取逐字对应）。
    let mut amount = base;
    // `ctx.content` 是 `Copy`：先拷出来，后面每一处 `damage_stage` 都要它，而 `ctx.state`
    // 还要被可变借用 —— 拷一份是唯一能让借用检查器同时满意、又不引入隐藏状态的写法。
    let content = ctx.content;

    // Source 阶段读**出手者**的状态。没有来源 ⇒ 整个阶段跳过，**不是错误**
    // （`PassiveModifiers.cs:248-249` 的 `combatant is null ⇒ return currentAmount`）。
    if let Some(source) = ctx.source {
        if let Some(source_combatant) = ctx.state.combatant(&source) {
            amount = damage_stage(
                amount,
                source_combatant.statuses(),
                ModifierTarget::Source,
                &source,
                content,
                kind,
                ctx.state.cards_played_this_turn,
            )?;
        }
    }

    // Target 阶段读**承受者**的状态（易伤）；顺便把这一刻的血量与整张防御池表取出来，
    // 后面写状态时就不用再复制整个 `Combatant`（它在裸机上约 2 KB）。
    let health_before;
    let mut pools = [DefensivePool::EMPTY; MAX_DEFENSIVE_POOLS];
    let mut pool_count = 0usize;
    {
        let target_combatant = ctx
            .state
            .combatant(target)
            .ok_or(ExecError::MissingCombatant)?;
        amount = damage_stage(
            amount,
            target_combatant.statuses(),
            ModifierTarget::Target,
            target,
            content,
            kind,
            ctx.state.cards_played_this_turn,
        )?;
        health_before = target_combatant.health_current;
        // 池表**按吸收顺序**读出（见下面 S4 的说明）。切片本身是 key 排好序的，
        // 所以这一步就是"把顺序冻结成本地副本"，不会因为后面写池而失效。
        for pool in target_combatant.defensive_pools() {
            let Some(slot) = pools.get_mut(pool_count) else {
                // 不可达：`defensive_pools()` 的长度上限就是 `MAX_DEFENSIVE_POOLS`。
                return Err(ExecError::Modifier);
            };
            *slot = *pool;
            pool_count += 1;
        }
    }

    // ── S3b：**`Intangible`** —— §210 起是**内容**的一行 `DamageReceived / ClampMax 1`
    // （已经在上面的修饰器折叠里跑过）。它落在折叠里、**防御池吸收之前**，所以"格挡最多只挡到
    // 那 1 点"这条性质没变；"也压 Constricted 这类 `IgnoresBlock` 掉血"同样没变（同一条管线）。
    //
    // ⚠️ 这里原来是一段 `amount = amount.min(1)` 的硬编码。搬走的理由是它有两个**下不去的**偏差：
    // 硬编码只有内核认识（内容里那条 `standard.intangible` 是死数据），而 `ClampMax` 早就存在。

    // ── S4：防御池吸收（`DamageEffects.cs:80-101`）。
    //
    // 参考：`foreach (var poolDef in registry.GetDefensivePoolsInAbsorbOrder())`，而那张表的顺序是
    // **`(AbsorbPriority, Id.value)`**（`CombatDefinitionRegistry.cs:68-71`）。逐个池
    // `absorbed = Math.Min(pool.Current, remaining)`、`remaining -= absorbed`，伤害耗尽就停。
    //
    // 本层**没有池定义注册表**（`state::DefensivePool` 只有 `key` + `pool`，没有 `AbsorbPriority`），
    // 所以第一级排序键拿不到；第二级（`Id.value` 的 `StringComparer.Ordinal`）由
    // `Combatant::defensive_pools()` 的 key 字节序**直接就是**（`Bounded::upsert` 维护）。
    // ⇒ 对所有优先级相同的池（标准包只有 `standard.block`，`AbsorbPriority: 0`），
    // 这个顺序与参考**逐字相同**。见模块头的偏差说明。
    let mut blocked = 0;
    if !ignores_block {
        let mut remaining_for_pools = amount;
        for index in 0..pool_count {
            if remaining_for_pools <= 0 {
                break;
            }
            let Some(pool) = pools.get(index).copied() else {
                return Err(ExecError::Modifier);
            };
            // `:86`：池不在身或已经见底 ⇒ 跳过（**不建池**、不产生 0 写入）。
            if pool.pool.current <= 0 {
                continue;
            }
            let absorbed = if pool.pool.current < remaining_for_pools {
                pool.pool.current
            } else {
                remaining_for_pools
            };
            let combatant = ctx
                .state
                .combatant_mut(target)
                .ok_or(ExecError::MissingCombatant)?;
            combatant.set_defensive_pool(pool.key, pool.pool.current - absorbed, pool.pool.max)?;
            blocked += absorbed;
            remaining_for_pools -= absorbed;
        }
    }

    // ── S5/S7：生命损失（`:103-104,138-141`）。
    let remaining = amount.saturating_sub(blocked);
    let mut health_after = if remaining >= health_before {
        0
    } else {
        health_before - remaining
    };
    let mut health_lost = (health_before - health_after).max(0);

    // ── S6b：**`Buffer`**（§149）—— "挡下下一次掉血"。
    //
    // 判据是"**本来要掉血**"（`health_lost > 0`），所以**被格挡吃干净的那些不消耗 Buffer** ——
    // 这正是 StS 的行为，也是这条规则唯一值得写两行注释的地方：把判定放在 `amount` 上会变成
    // "每挨一下就消耗一层"，玩家会发现盾还在但 Buffer 没了。
    if health_lost > 0 && carries_status(ctx.state, target, BUFFER_STATUS) {
        if consume_one_status_stack(ctx.state, target, BUFFER_STATUS)? {
            health_after = health_before;
            health_lost = 0;
        }
    }

    // ── S6c：**`Plated Armor`** —— §210 起是**内容**的一条 `DamageTaken` 触发器
    // （`damage.isAttack && eventAmount > 0` ⇒ 自减一层）。它的另一半（回合结束给格挡）还在
    // `host::grant_end_of_turn_block`。
    //
    // ⚠️ 这里原来是一段 `if health_lost > 0 { consume(plated) }`。那**是错的**：它分不清攻击与
    // 毒 —— 一次 poison tick 也会剥掉一层，而 wiki 写的是 "unblocked **attack** damage"。
    // §208 的 `damage.isAttack` 事件事实让正确规则可以表达，所以这不是搬家，是**修 bug**。

    // ── S6d：**`DeathPrevention`**（§180）—— 参考的 `IPreDownInterceptor` 这一半。
    //
    // 位置是**语义**：这一下已经穿过格挡、Buffer、Plated Armor，血量确实落到 0，但**还没**转
    // `Downed`。参考的拦截点就在这里。
    //
    // 代价是这一下要**重新读一遍**持有者的状态：上面已经读过一次（伤害修饰），但中间那几个
    // 处理器会改状态表，所以"读到的那一份"不能复用。
    if health_lost > 0 && health_after == 0 {
        if let Some((definition, surviving, repeats)) = death_prevention_for(ctx, target)? {
            health_after = surviving;
            health_lost = health_after.saturating_sub(health_before).max(0);
            // `Repeating` 的才留下；其余是"一次性护符"（wiki 的 Fairy in a Bottle: "works once"）。
            // ⚠️ `false` 时**必须真的摘掉**：留着它，下一次致命伤还会被同一个状态救 ——
            // 那就是 `Repeating` 的语义，而不是这瓶药的。
            if !repeats {
                let mut buffer = [0u8; 64];
                let text = definition.as_str();
                buffer[..text.len()].copy_from_slice(text.as_bytes());
                if let Ok(name) = core::str::from_utf8(&buffer[..text.len()]) {
                    let _ = consume_one_status_stack(ctx.state, target, name)?;
                }
            }
        }
    }

    let combatant = ctx
        .state
        .combatant_mut(target)
        .ok_or(ExecError::MissingCombatant)?;
    combatant.health_current = health_after;
    // §242：每次真的掉血都记一笔（`Blood for Blood` 的费用递减；被格挡吃干净的不算）。
    if health_lost > 0 {
        combatant.hp_losses = combatant.hp_losses.saturating_add(1);
    }
    // S8 的 `DamageDealt` 事件 → `MarkCombatantDownedOnZeroHealthHandler`
    // （`CombatantLifecycleEffects.cs`）：只有**真的掉了血**且落到 0 才转 Downed。
    let went_down = health_lost > 0
        && health_after == 0
        && combatant.lifecycle_state == CombatantLifecycleState::Alive;
    if went_down {
        combatant.lifecycle_state = CombatantLifecycleState::Downed;
        // **Its minions flee** (`port-plan.md` §139). `Escaped` is a lifecycle state the reference
        // already has, and the victory check only counts `Alive` -- so an escaped minion neither
        // blocks the win nor contributes anything to it (its remaining HP stops mattering).
        for other in ctx.state.combatants_mut() {
            if other.owner == Some(*target)
                && other.lifecycle_state == CombatantLifecycleState::Alive
            {
                other.lifecycle_state = CombatantLifecycleState::Escaped;
            }
        }
        // `Downed` 事件：`Spore Cloud` 这一批触发器等它（`port-plan.md` §117）。
        ctx.state
            .enqueue_event(crate::state::CombatEvent::Downed {
                combatant: *target,
                source: ctx.source,
            })
            .map_err(ExecError::Capacity)?;
    }

    // ── 倒下就判胜负（`CombatStateEffects.cs:36-58`）。
    // 参考在同一个排空循环里把 `Downed` 变成 `CombatantLifecycleChanged` 事件、
    // 再变成 `SetCombatResult`；内核没有队列，所以在**这一行**同步判一次。
    // 这一句是 #3 的全部：没有它，程序打死最后一个敌人时 `state.result` 仍是
    // `Ongoing`，`play.rs` 的 Cancelled 分支永远不可达，卡会被搬进弃牌堆。
    if went_down {
        update_standard_combat_result(ctx.state);
    }

    // ── S8：`DamageDealt` 事件（`DamageEffects.cs:186-194`，参考在**这里**入队）。
    //
    // 顺序照参考：先落血、再判 Downed/胜负、**最后**入队事件。入队不动状态，
    // 所以它与"先判胜负"之间没有可观察的耦合；但事件里的四个数字都是**结算后**的
    // （`HealthDamage` 是实际掉血、`BlockedDamage` 是实际吸收、`RequestedAmount` 是请求额），
    // 提前入队会拿错数。
    //
    // ⚠️ 它**不会**在这里被分发：排空发生在引擎调用的边界（`battle.rs` 的 `hero_plays` /
    // `enemy_acts`，以及 `turn.rs` 的五个 `resolve_pending_queues` 点）。这正是两相位的意义
    // —— 触发器节目入队的效果要等到**整批**效果解析完才落地（`CombatEventHandling.cs:104-105`）。
    //
    // ⚠️ 参考入队**两条**事件：出手方侧与承受者侧（`:196-204`）。承受者侧那条今天有观察者了
    // —— `Thorns` 就是它的第一批触发器（`port-plan.md` §116）。
    let taken_source = ctx.source;
    ctx.state
        .enqueue_event(crate::state::CombatEvent::DamageDealt {
            target: *target,
            health_damage: health_lost,
            blocked_damage: blocked,
            requested: amount,
            source: ctx.source,
        })
        .map_err(ExecError::Capacity)?;

    // 承受者侧（`DamageReceivedCombatEvent`）：同一个结算点，Bearer 在宿主那边换成**承受者**。
    ctx.state
        .enqueue_event(crate::state::CombatEvent::DamageTaken {
            target: *target,
            source: taken_source,
            health_damage: health_lost,
            // §208: the fact the receiving side never had. `Direct` is what the content calls an
            // attack (`damageKind: Direct`); DoT ticks are `Dot` and must not count as "hit by an
            // attack" (Flying only loses a stack to attacks).
            is_attack: matches!(kind, BindDamageKind::Direct),
        })
        .map_err(ExecError::Capacity)?;

    // ── 动画日志（§142）：**掉血**。写在这里的理由与上面两条事件同一行 ——
    // 这是伤害管线的唯一出口（卡 / 敌动作 / DoT tick / 伤害药水都走到这）。
    // 三个数字各有其职：`a` 是动画要飘的那个数、`b` 是"格挡吸收"（盾牌闪光）、
    // `c` 是请求额（多段攻击里"这一下本来多疼"，被完全挡住时页面靠它才知道有攻击）。
    crate::beat::record(
        ctx.state,
        crate::beat::Beat {
            kind: crate::beat::BeatKind::Damage,
            actor: match ctx.source {
                Some(source) => crate::beat::ordinal_of(ctx.state, &source),
                None => crate::beat::NOBODY,
            },
            target: crate::beat::ordinal_of(ctx.state, target),
            def: crate::beat::NO_DEF,
            flags: match kind {
                BindDamageKind::Dot => crate::beat::FLAG_DOT,
                _ => 0,
            },
            a: health_lost,
            b: blocked,
            c: amount,
        },
    );
    // 倒下：**同一行**翻转 `lifecycle_state` 的地方已经在上面记过账，这里只补动画。
    // 倒下：**同一行**翻转 `lifecycle_state` 的地方已经在上面记过账，这里只补动画。
    if went_down {
        let actor = match ctx.source {
            Some(source) => crate::beat::ordinal_of(ctx.state, &source),
            None => crate::beat::NOBODY,
        };
        crate::beat::record(
            ctx.state,
            crate::beat::Beat {
                kind: crate::beat::BeatKind::Downed,
                actor,
                target: crate::beat::ordinal_of(ctx.state, target),
                def: crate::beat::NO_DEF,
                flags: 0,
                a: 0,
                b: 0,
                c: 0,
            },
        );
        // 随从逃跑（§139）也各记一条：屏幕上"人没了"但不该算被这一下打死的。
        // 先攒 ordinal 再记 —— `record` 要 `&mut state`，而遍历 `combatants()` 正借着它。
        let mut fled = [crate::beat::NOBODY; MAX_COMBATANTS];
        let mut fled_count = 0usize;
        for (index, other) in ctx.state.combatants().iter().enumerate() {
            if other.owner == Some(*target)
                && other.lifecycle_state == CombatantLifecycleState::Escaped
            {
                if let Some(cell) = fled.get_mut(fled_count) {
                    *cell = index.min(usize::from(crate::beat::NOBODY) - 1) as u8;
                    fled_count += 1;
                }
            }
        }
        let falling = crate::beat::ordinal_of(ctx.state, target);
        for ordinal in fled.iter().take(fled_count) {
            crate::beat::record(
                ctx.state,
                crate::beat::Beat {
                    kind: crate::beat::BeatKind::Escaped,
                    actor: falling,
                    target: *ordinal,
                    def: crate::beat::NO_DEF,
                    flags: 0,
                    a: 0,
                    b: 0,
                    c: 0,
                },
            );
        }
    }

    Ok((blocked, health_lost))
}

/// 标准包的胜负判定：**有人倒下就立刻判**（`Effects/CombatStateEffects.cs:28-60`）。
///
/// # 它为什么住在 `exec.rs` 而不是 `battle.rs`
///
/// 2026-10-19 的整局对拍（`native/fight_diff.py`）证明：参考实现是**倒下即判、判了即停**，
/// 内核原来是"步边界/每次引擎调用之后"才算（`battle.rs` 的 `settle_result`），于是
/// `play::play_card` 执行期间 `state.result` 一直是 `Ongoing` —— 程序打死最后一个敌人那一下
/// **没人立刻知道**，`play.rs` 里"Cancelled ⇒ 卡不搬"的分支因此从来没有被真实路径走到过。
///
/// 参考的链路是三步，逐行（我读过这三段源码，行号对得上）：
///
/// 1. 伤害把目标扣到 0 ⇒ `MarkCombatantDownedOnZeroHealthHandler` 把生命周期改成 `Downed`
///    （`Effects/CombatantLifecycleEffects.cs:29-43`：`SetLifecycleState` 之后
///    `EnqueueEvent(CombatantLifecycleChangedCombatEvent)`）；
/// 2. 那个事件进队列，处理器 [`UpdateStandardCombatResultOnLifecycleChangedHandler`] 就在
///    **同一次排空里** `EnqueueEffect(SetCombatResultEffectRequest(…))`（`:36-58`）；
/// 3. 下一次排空把 `Result` 设上，而 `CombatState.SetResult` 会**立刻取消在飞帧**
///    （`CombatState.cs:358-367` 的 `CancelDueToCombatEnd`）—— 这就是"判了就停"。
///
/// 内核没有三队列，所以 1+2+3 合并成"在 `Downed` 那一行同步判一次"。顺序与参考**同粒度**：
/// 都在"伤害已经落地、程序的后续节点还没派发"这个时刻。
///
/// 幂等：`Result != Ongoing` 时**什么都不做**（参考 `:36-37`）。
pub fn update_standard_combat_result(state: &mut CombatState) {
    if state.result != CombatResult::Ongoing {
        return; // `CombatStateEffects.cs:36-37`
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

/// §236：「失去 N 点生命」—— `Lose HP`，**不是**伤害。
///
/// 直接写 `health_current`，但**复用掉血那套收尾**：0 血转 `Downed`、主人的随从逃跑、发 `Downed`
/// 事件、判胜负。少了这一段，"用一张牌把自己打死"不会结束战斗（一个只在自伤牌上出现的死锁）。
///
/// 返回**真的**失去的血量：血量不够时就是剩下的那些（`Lose 6 HP` 在 2 血时只掉 2）。
pub fn lose_health(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    amount: i32,
) -> Result<i32, ExecError> {
    if amount < 0 {
        return Err(ExecError::Modifier);
    }
    let Some(combatant) = ctx.state.combatant(target) else {
        return Err(ExecError::MissingCombatant);
    };
    if combatant.lifecycle_state != crate::state::CombatantLifecycleState::Alive {
        return Ok(0);
    }
    let current = combatant.health_current;
    let lost = amount.min(current.max(0));
    let after = current - lost;
    // `from_card` 由上下文回答：节目里有没有"正在结算的那张牌"。
    let from_card = ctx.resolving_card.is_some();
    let combatant = ctx
        .state
        .combatant_mut(target)
        .ok_or(ExecError::MissingCombatant)?;
    combatant.health_current = after;
    let went_down = lost > 0
        && after == 0
        && combatant.lifecycle_state == crate::state::CombatantLifecycleState::Alive;
    if went_down {
        combatant.lifecycle_state = crate::state::CombatantLifecycleState::Downed;
        for other in ctx.state.combatants_mut() {
            if other.owner == Some(*target)
                && other.lifecycle_state == crate::state::CombatantLifecycleState::Alive
            {
                other.lifecycle_state = crate::state::CombatantLifecycleState::Escaped;
            }
        }
        ctx.state
            .enqueue_event(crate::state::CombatEvent::Downed {
                combatant: *target,
                source: ctx.source,
            })
            .map_err(ExecError::Capacity)?;
    }
    if lost > 0 {
        ctx.state
            .enqueue_event(crate::state::CombatEvent::HpLost {
                target: *target,
                amount: lost,
                from_card,
            })
            .map_err(ExecError::Capacity)?;
    }
    // §242：`Lose HP` 也算"失去生命"（`Blood for Blood` 的费用递减）。
    if lost > 0 {
        if let Some(combatant) = ctx.state.combatant_mut(target) {
            combatant.hp_losses = combatant.hp_losses.saturating_add(1);
        }
    }
    update_standard_combat_result(ctx.state);
    Ok(lost)
}

/// `GainMaxHealth`：**抬高最大生命**，并把当前生命一起抬高 `Amount`（§238）。
///
/// StS 的写法是 "raise your Max HP by 3" —— 上限 +3 **并且**当前血 +3（`Feed` 就是这么回血的）。
/// `Amount <= 0` ⇒ 抛（镜像里没有"降低上限"的牌，负数只可能是内容写错 ⇒ 响亮拒绝）。
fn gain_max_health_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    _frame: ProgramExecutionSlot,
    _slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    if amount <= 0 {
        return Err(ExecError::Modifier);
    }
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        gain_max_health(ctx.state, target, amount)?;
    }
    Ok(())
}

/// "抬高最大生命"的**唯一**实现：上限 +N，当前血也 +N（StS 的 "raise your Max HP by N"）。
///
/// 两个节点共用（`gainMaxHealth` 与 `dealDamageAndGainMaxHealthIfFatal`）—— 同一个语义写两遍，
/// 迟早有一遍会漂。
fn gain_max_health(
    state: &mut crate::state::CombatState,
    target: &CombatantId,
    amount: i32,
) -> Result<(), ExecError> {
    let combatant = state
        .combatant_mut(target)
        .ok_or(ExecError::MissingCombatant)?;
    combatant.health_max = combatant.health_max.saturating_add(amount);
    combatant.health_current = combatant.health_current.saturating_add(amount);
    Ok(())
}

/// §250：`node.dealDamageAndIfFatal` 的实体 —— `{TargetSelector, Amount, IgnoresBlock?, Element?,
/// Program}`。
///
/// 三条顺序都是语义：
/// 1. `Amount` **先**求值（`Ritual Dagger` 这一次的伤害不含"这一次涨的 3 点"）；
/// 2. 每个目标依次挨打，`fatal` = "**有任何一个**目标真的倒了"；
/// 3. 子节目在**伤害全部落地之后**才跑 —— 这正是"必须是一个节点"的理由（`sequence` 做不到）。
fn deal_damage_and_if_fatal_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    depth: u32,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    // 与 `dispatch_conditional` 逐字同形：先把自己的槽置 `Pass`（"分支的完成 = 我的完成"），
    // 再把子节目**派发到同一个槽**。不这么做就会出现 §250 踩到的那个错：
    // 完成时不 `resume_later` ⇒ 父的续延拿不到帧 ⇒ `dispatch_node` 报 `ExecError::Modifier`。
    if let Some(cell) = ctx.state.program_nodes_mut().get_mut(slot) {
        cell.kind = ProgramNodeKind::Pass;
    }
    let amount = eval_amount(node, "Amount", ctx)?;
    let ignores_block = node.bool_field("IgnoresBlock")?.unwrap_or(false);
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    let mut fatal = false;
    for target in targets.iter().take(count) {
        resolve_damage(ctx, target, amount, ignores_block)?;
        stats.effects = stats.effects.saturating_add(1);
        // 与 §238 逐字相同：Fatal = 目标**真的倒了**（血量 <= 0），不是"伤害超过血量"。
        if ctx
            .state
            .combatant(target)
            .is_some_and(|combatant| combatant.health_current <= 0)
        {
            fatal = true;
        }
    }
    let branch = if fatal { node.node_field("Program")? } else { None };
    match branch {
        Some(body) => {
            // 在**本节点的槽位**里就地跑子节目（与 `dispatch_conditional` 同一个手法）：
            // 不新开节目槽，所以深度/步数预算仍然算在这棵树上。
            dispatch_node(body, ctx, frame, slot, depth + 1, stats)?;
            Ok(())
        }
        // 没打死 ⇒ 本节点就是"做完了"（与 `conditional` 的 `None` 分支同一条）。
        None => resume_later(ctx.state, frame, slot),
    }
}

/// §253：`node.playCard` 的实体 —— `{PlayerSelector, CardExpression, CardTargetSelector?,
/// IgnoreUnplayable?}`。
///
/// 它**不自己实现出牌**：把"哪一份、谁打、打谁、要不要越过 `unplayable`"整理成一个请求，
/// 剩下的交给 [`crate::play::play_card_from_program`] —— 费用、事件、触发器、修饰器因此
/// 只有一份实现（与 `Havoc` 的 `play_top_card_for` 同一层）。
fn play_card_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let player_selector = node
        .node_field("PlayerSelector")?
        .ok_or(IrError::Missing("PlayerSelector"))?;
    let mut players = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(player_selector, ctx, &mut players)?;
    let Some(player) = players.first().copied().filter(|player| count > 0) else {
        // 参考：`TryGetCombatant` 失败 ⇒ no-op（`PlayCardEffects.cs:33-37`）。
        return resume_later(ctx.state, frame, slot);
    };
    let card_expression = node
        .node_field("CardExpression")?
        .ok_or(IrError::Missing("CardExpression"))?;
    let card = {
        let expr_ctx = ctx.expr_context();
        crate::expr::eval_card(card_expression, &expr_ctx)?
    };
    let target = match node.node_field("CardTargetSelector")? {
        Some(selector) => {
            let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
            let resolved = resolve_targets(selector, ctx, &mut targets)?;
            targets.first().copied().filter(|_| resolved > 0)
        }
        None => None,
    };
    let ignore_unplayable = node.bool_field("IgnoreUnplayable")?.unwrap_or(false);
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };
    // 四种"跳过"由 `play_card_from_program` 自己判定并返回 `Ok(false)`（参考全是 no-op，
    // 不是错误）—— 只有"内容坏了"才走 `Err`。
    crate::play::play_card_from_program(
        ctx.state,
        content,
        &player,
        &card,
        target,
        ignore_unplayable,
    )?;
    resume_later(ctx.state, frame, slot)
}

/// §250：`node.gainGold` 的实体 —— `{Amount}`。
///
/// 直接写 `CombatState.gold_gained`（不走请求）：金币不是任何触发器看得见的东西。
/// `Amount` 为负 => 拒绝（内容写错了，不许悄悄当 0）。
fn gain_gold_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    if amount < 0 {
        return Err(ExecError::Modifier);
    }
    ctx.state.gold_gained = ctx.state.gold_gained.saturating_add(amount);
    resume_later(ctx.state, frame, slot)
}

/// §250：`node.createCardCopy` —— `{ToZone, Count?, Placement?}`，造**当前正在结算的那一份**的副本。
///
/// "当前这一份"取自 `ctx.resolving_card` —— 与 `card.counter` 读同一个东西。那不是巧合，
/// 而是"这一张牌自己"在内核里的唯一身份；没有它就没有答案（`MissingCombatant`）。
fn create_card_copy_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let zone_text = node.str_field("ToZone")?.ok_or(IrError::Missing("ToZone"))?;
    let zone = zone_from_wire_name(zone_text).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    let placement = match node.str_field("Placement")? {
        None | Some("Bottom") => crate::state::ZonePlacement::Bottom,
        Some("Top") => crate::state::ZonePlacement::Top,
        Some(_) => return Err(ExecError::Ir(IrError::UnknownKind)),
    };
    let count = match node.node_field("Count")? {
        None => DEFAULT_CARD_INSTANCE_COUNT,
        Some(term) => {
            let expr_ctx = ctx.expr_context();
            expr::eval_int(term, &expr_ctx)?
        }
    };
    if count < 0 {
        return Err(ExecError::Modifier);
    }
    // §250：**优先**用内容写的 `CardDefinitionId`，否则用"正在结算的那一份"的定义。
    //
    // 为什么必须有第一条：这两张牌的节目挂在**生命周期**上（`Pride` 的 `TurnEndInHand`、
    // `Necronomicurse` 的 `Exhausted`），而生命周期上下文**故意不绑卡槽**（§220 的偏离 #2：
    // 参考的 `CardLifecycleContext` 有卡槽，本内核的 `ExecContext` 只有一个 `iteration_card`，
    // 它的语义被钉死给 `forEachCardInZone`）。所以那里 `ctx.resolving_card` 是 `None` ——
    // 一张诅咒的"自己"在那种上下文里只能由内容**指明**（它们没有 `+` 行，指明是精确的）。
    let definition = match node.str_field("CardDefinitionId")? {
        Some(text) => CardDefinitionId::new(text)?,
        None => {
            let Some(resolving) = ctx.resolving_card else {
                return Err(ExecError::MissingCombatant);
            };
            let Some(definition) = ctx.state.card(resolving).map(|card| card.definition_id) else {
                return Err(ExecError::MissingCombatant);
            };
            definition
        }
    };
    let Some(owner) = ctx.source else {
        return Err(ExecError::MissingCombatant);
    };
    for _ in 0..count {
        ctx.state
            .create_card_instance_at(&owner, definition, zone, placement)
            .map_err(ExecError::Capacity)?;
    }
    resume_later(ctx.state, frame, slot)
}

/// §254：`node.offerCards` 的实体 —— `{Definitions, Min?, Max?, Then?}`。
///
/// 三个候选是**内容写死的**（`Definitions` 是 `F_STRLIST`），按给定顺序进问句。
/// `Then` 决定选完做什么：`ToHandFree`（进手牌、这次免费，与 `Discovery` 同义）或
/// `PlayChosen`（**立刻打出它**，`Wish`）。
///
/// 与 `offerRandomCards` 共用"问句怎么建"这件事的形状（`PendingChoice` + `ChoiceSource::Offered`），
/// 但**不共用抽签**：这里一个随机都不掷 —— 抽签会让"Wish 的三个选项是固定的"变成运气。
fn offer_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let mut ids = [0u16; MAX_OFFERED_CARDS];
    let count = node.str_list_field("Definitions", &mut ids)?;
    if count == 0 || count > MAX_OFFERED_CARDS {
        return Err(ExecError::Modifier);
    }
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };
    let Some(chooser) = ctx.source else {
        return Err(ExecError::MissingCombatant);
    };
    let min = u8::try_from(node.int_field("Min")?.unwrap_or(1)).map_err(|_| ExecError::Modifier)?;
    let max = u8::try_from(node.int_field("Max")?.unwrap_or(1)).map_err(|_| ExecError::Modifier)?;
    if min > max {
        return Err(ExecError::Modifier);
    }
    // `Then` 缺席 ⇒ `ToHandFree`（与 `Discovery` 同一条默认）。
    let then = match node.str_field("Then")? {
        None | Some("ToHandFree") => crate::state::ChoiceThen::ToHandFree,
        Some("PlayChosen") => crate::state::ChoiceThen::PlayChosen,
        Some(_) => return Err(ExecError::Ir(IrError::UnknownKind)),
    };

    let mut offered = crate::state::Bounded::new();
    for index in 0..count {
        let Some(text) = ids.get(index).copied().and_then(|id| content.string(id)) else {
            return Err(ExecError::Ir(IrError::Missing("Definitions")));
        };
        // 定义必须在 `CARD` 表里 —— 一个指向不存在的牌的候选会让"选中"那一步炸，
        // 而那时玩家已经点了（不可回退）。所以**建问句之前**就验。
        // 与 `host::card_row` 同一条查法（`lookup_in(.., EK_CARD)`）：那个函数是 `host` 私有的，
        // 而这里只需要"这张定义在不在 CARD 表里"这一个答案。
        if content
            .lookup_in(text, crate::content::EK_CARD)
            .is_none()
        {
            return Err(ExecError::Ir(IrError::Missing("CARD row")));
        }
        let definition = CardDefinitionId::new(text)?;
        offered
            .push(definition, crate::state::Container::ChoiceOptions)
            .map_err(ExecError::Capacity)?;
    }

    let question = crate::state::PendingChoice {
        chooser,
        source: crate::state::ChoiceSource::Offered,
        min,
        max,
        then,
        offered,
        candidates: crate::state::Bounded::new(),
    };
    ctx.state
        .begin_choice(question)
        .map_err(|_| ExecError::Modifier)?;
    resume_later(ctx.state, frame, slot)
}

/// §250：`node.offerRandomCards` 的实体 —— `{Count?, Min?, Max?}`：**三选一**。
///
/// 与 `chooseCards` 的分工：那个问"**已有的**哪几张"（候选是实例），这个问"这几张**新的**
/// 里要哪个"（候选是定义，`ChoiceSource::Offered`）。`then` 是 [`ChoiceThen::ToHandFree`] ——
/// "加进手牌，它这次免费"的整个语义都在内核里，页面只管显示。
///
/// 抽签走 `random_step`（与随机造牌/洗牌同一本账）并且**去重**：三张候选不许重复。
/// 池子不够 / 抽签凑不齐 => **不问**（一个凑不出候选的问句会把这局钉死；与 `chooseCards`
/// 的"候选比 `Min` 还少就不问"同一条裁决）。
fn offer_random_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    // §250：`Count` 两种拼法都收 —— 字面整数（与 `Min`/`Max` 同一种字段类型）或表达式
    // （与 `createRandomCardInstance` 同一种字段类型）。原因是"3 张候选"是这个节点的
    // **语法**而不是运行期的值；但把表达式这条路堵死会让将来的"候选数 = 抽牌堆张数"要改节点。
    // ⚠️ **先问 `int_field`**：这一格在本内容里是普通整数（与 `Min`/`Max` 同族），
    // 而 `node_field` 对声明成 `F_INT` 的字段会**响亮报错**（`WrongKind("F_TERM")`）。
    // 反过来的顺序在这里是错的 —— 这正是 §250 判据第三次红的那个错。
    let count = match node.int_field("Count")? {
        Some(value) => value,
        None => match node.node_field("Count")? {
            None => DEFAULT_OFFERED_CARDS,
            Some(term) => {
                let expr_ctx = ctx.expr_context();
                expr::eval_int(term, &expr_ctx)?
            }
        },
    };
    if count <= 0 {
        return Err(ExecError::Modifier);
    }
    let want = usize::try_from(count)
        .unwrap_or(MAX_OFFERED_CARDS)
        .min(MAX_OFFERED_CARDS);
    // `PendingChoice` 的 `min`/`max` 是 `u8`；越界就是内容写错了（候选数上限 8）。
    let min = u8::try_from(node.int_field("Min")?.unwrap_or(1)).map_err(|_| ExecError::Modifier)?;
    let max = u8::try_from(node.int_field("Max")?.unwrap_or(1)).map_err(|_| ExecError::Modifier)?;
    if min > max {
        return Err(ExecError::Modifier);
    }
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };
    let Some(chooser) = ctx.source else {
        return Err(ExecError::MissingCombatant);
    };

    // 池子有多大 —— 先数一遍，再按去重的下标取定义（与 `pick_random_card_of_tag` 同一个手法）。
    let mut total = 0usize;
    for row in content.rows(crate::content::Table::Card) {
        let Some(definition) = content.entity_id(crate::content::Table::Card, row.index()) else {
            continue;
        };
        if in_offer_pool(content, definition) {
            total += 1;
        }
    }
    if total < want {
        return resume_later(ctx.state, frame, slot);
    }
    let mut picked = [0usize; MAX_OFFERED_CARDS];
    let mut picked_len = 0usize;
    let mut guard = 0usize;
    let guard_cap = total.saturating_mul(8).saturating_add(64);
    while picked_len < want && guard < guard_cap {
        let index =
            crate::rng::shuffled_pick_index(total, ctx.state.random_seed, ctx.state.random_step);
        ctx.state.random_step = ctx.state.random_step.saturating_add(1);
        guard += 1;
        if picked[..picked_len].contains(&index) {
            continue;
        }
        let Some(entry) = picked.get_mut(picked_len) else {
            break;
        };
        *entry = index;
        picked_len += 1;
    }
    if picked_len < want {
        return resume_later(ctx.state, frame, slot);
    }

    let mut offered = crate::state::Bounded::new();
    let mut seen = 0usize;
    for row in content.rows(crate::content::Table::Card) {
        let Some(definition) = content.entity_id(crate::content::Table::Card, row.index()) else {
            continue;
        };
        if !in_offer_pool(content, definition) {
            continue;
        }
        let wanted = picked[..picked_len].contains(&seen);
        seen += 1;
        if !wanted {
            continue;
        }
        let definition = CardDefinitionId::new(definition)?;
        offered
            .push(definition, crate::state::Container::ChoiceOptions)
            .map_err(ExecError::Capacity)?;
    }

    let question = crate::state::PendingChoice {
        chooser,
        source: crate::state::ChoiceSource::Offered,
        min,
        max,
        then: crate::state::ChoiceThen::ToHandFree,
        offered,
        candidates: crate::state::Bounded::new(),
    };
    // 已经有一个待决问句 => 嵌套提问，本内核明确不支持（与 `chooseCards` 同一条）。
    ctx.state
        .begin_choice(question)
        .map_err(|_| ExecError::Modifier)?;
    resume_later(ctx.state, frame, slot)
}

/// §250：`offerRandomCards` 的池子规则 —— **"你职业牌池里的真牌"**。
///
/// 从"排除了什么"来定义，因为我们的内容没有职业 tag（唯一的分色标记是 `colorless`）：
/// * `+` 行是同一张牌的另一个定义（池子只收基础牌，与 `in_random_pool` 同一条）；
/// * 无色牌 / 诅咒 / 状态 / 垃圾牌不是"职业牌池"的一部分；
/// * 不可打出的牌进候选等于给玩家几张废纸；
/// * X 费牌没有印刷费用（"免费"对它没有意义）。
fn in_offer_pool(content: &crate::content::Content<'_>, definition: &str) -> bool {
    if definition.contains('+') {
        return false;
    }
    for tag in ["colorless", "curse", "status", "junk", "unplayable"] {
        if content.card_has_tag(definition, tag) == Some(true) {
            return false;
        }
    }
    content.card_has_tag(definition, crate::battle::X_COST_TAG) != Some(true)
}

/// §238：`node.dealDamageAndGainMaxHealthIfFatal` 的实体 —— 与 `dealDamageAndHealByLoss` 同形，
/// 只是"读完自己的结果"之后做的是抬上限而不是回血。
fn deal_damage_and_gain_max_health_if_fatal_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let ignores_block = node.bool_field("IgnoresBlock")?.unwrap_or(false);
    let gain = node
        .int_field("MaxHealthGain")?
        .ok_or(IrError::Missing("MaxHealthGain"))?;
    if gain <= 0 {
        return Err(ExecError::Modifier);
    }
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let source = ctx.source;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    if count == 0 {
        return resume_later(ctx.state, frame, slot);
    }
    let mut fatal = false;
    for target in targets.iter().take(count) {
        resolve_damage(ctx, target, amount, ignores_block)?;
        stats.effects = stats.effects.saturating_add(1);
        // "Fatal" 的判据是**目标真的倒了**（血量 ≤ 0），不是"伤害超过血量" —— 被格挡吃掉的
        // 伤害不会让人死，而这条判据以后加"死亡拦截"（Fairy in a Bottle）时仍然对。
        if ctx
            .state
            .combatant(target)
            .is_some_and(|combatant| combatant.health_current <= 0)
        {
            fatal = true;
        }
    }
    if fatal {
        if let Some(owner) = source {
            gain_max_health(ctx.state, &owner, gain)?;
        }
    }
    resume_later(ctx.state, frame, slot)
}

/// §236：`node.loseHp` 的实体 —— `{TargetSelector, Amount}`，每个目标各失去一次。
///
/// 与 `dealDamage` 的分工写在 [`lose_health`] 的文档里（一句话：不吃格挡、不吃修饰器、
/// 不触发"被打"的钩子）。`Amount` 在**解析目标之前**求值，与其它产出型节点同一条口径。
fn lose_hp_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        lose_health(ctx, target, amount)?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// `StandardCombatIds.PlayerTeam`（`StandardCombatIds.cs`：`new("player")`）。
///
/// 与 `battle.rs` 的两个同名常量**是同一份事实**：那个模块用它们建战斗，
/// 这里用它们判胜负。放在两处是因为 `battle.rs` 依赖 `exec.rs`（反向依赖会把
/// "驱动层"塞进"执行层"）；两条串在 `update_standard_combat_result` 与
/// `build_fight` 里都被真实用到，所以没有"常量没人读"的风险。
const PLAYER_TEAM: &str = "player";
/// `StandardCombatIds.EnemyTeam`（同上）。
const ENEMY_TEAM: &str = "enemy";

// =============================================================================================
// 预检 / 执行骨架
// =============================================================================================

/// 步数与深度这两个预算的账本。
#[derive(Debug, Default, Clone, Copy)]
struct Walk {
    steps: u32,
    depth: u32,
}

/// 预检自己的节点预算。
///
/// 参考的 `ValidateNodeExecutors` **没有**步数预算（它只受树的形状约束），所以这里也不能
/// 拿执行预算去卡它 —— 否则一个 3 节点的程序在 `max_steps = 2` 时会**一步都走不出去**，
/// 而参考是先走一步再抛。给它 4 倍余量的理由只有一条：预检沿 term DAG 递归，**共享子树会被
/// 重复访问**，镜像是被改坏的时候 2^k 爆炸会把内核挂住（挂住比报错糟）。
fn preflight_budget(max_steps: u32) -> u32 {
    max_steps.saturating_mul(4).max(64)
}

/// 预检：`ValidateNodeExecutors`（`EffectProgramExecution.cs:184-196`）。
///
/// 只沿参考那两条边走：`sequence.Children`、`conditional.Then/Else`。
/// `conditional` 的镜像节点**另有一个** `Children` 字段 —— 那是共享字段表的产物，
/// 参考的 `ConditionalEffectNode.Children` 是 `[Then, Else]`，所以这里**不读**那个字段。
///
/// 自己的步数账（与执行账分开算）：环照样会撞 `max_steps` 而不是无限递归。
/// 这一步**不**计入 [`ExecStats::nodes`]（参考的 `ProgramStepCount` 只数执行期的分派）。
fn preflight(node: NodeRef<'_>, max_steps: u32, walk: &mut Walk) -> Result<(), ExecError> {
    walk.steps = walk.steps.saturating_add(1);
    if walk.steps > max_steps {
        return Err(ExecError::StepLimit);
    }
    if walk.depth >= MAX_NODE_DEPTH {
        return Err(ExecError::StepLimit);
    }

    let kind = node.kind()?;
    match kind {
        NodeKind::Sequence
        | NodeKind::Conditional
        | NodeKind::DealDamage
        | NodeKind::GainBlock
        | NodeKind::ApplyStatus
        | NodeKind::Heal
        // 本内核自己的第 16 种（分裂 / 召唤，`port-plan.md` §121）。
        | NodeKind::CreateCombatant
        // §178：`destroyCombatant` 与 `createCombatant` 对称 —— 立即生效，不走效果队列。
        | NodeKind::DestroyCombatant
        // §201：`carryAwayStolenGold` 同理 —— 它必须与 `destroyCombatant` **同一个 tick** 生效，
        // 否则"钱搬走了但人还在"（或反过来）会有一个可观察的中间态。
        | NodeKind::CarryAwayStolenGold
        | NodeKind::EndTurn
        | NodeKind::ExtraTurn
        // W4e 的 7 种（见模块头那张表）。
        | NodeKind::SetCombatantCounter
        | NodeKind::ModifyStatusStacks
        | NodeKind::ForEachTarget
        | NodeKind::DrawCards
        | NodeKind::GainResource
        | NodeKind::LoseResource
        | NodeKind::CreateCardInstance
        // W4f 的 2 种（卡实例这一层寻址）。
        | NodeKind::ForEachCardInZone
        | NodeKind::MoveCardToZone
        // §195.4：`selectCards`（挑卡 + 搬卡）。没有孩子，预检只登记它。
        | NodeKind::SelectCards
        // §226：`chooseCards`（问玩家 + 复制）。同上，只有字段没有孩子。
        | NodeKind::ChooseCards
        // §228：`dealDamageToRandomTarget`（抽签 + 打伤害）。同上。
        | NodeKind::DealDamageToRandomTarget
        // §229：`addCardCounter`（给这份副本加计数器）。同上。
        | NodeKind::AddCardCounter
        // §230：`dealDamageWithTagBonus`（数牌 + 打伤害）。同上。
        | NodeKind::DealDamageWithTagBonus
        // §231：`dealDamageAndHealByLoss`（打伤害 + 按掉血回血）。同上。
        | NodeKind::DealDamageAndHealByLoss
        // §236：`loseHp`（失去生命）。同上。
        | NodeKind::LoseHp
        // §240：`createRandomCardInstance`（造一张随机牌）。无孩子。
        | NodeKind::CreateRandomCardInstance
        // §241：`playTopCardOfDrawPile`（把抽牌堆顶打出去）。无孩子。
        | NodeKind::PlayTopCardOfDrawPile
        // §243：`shuffleDiscardIntoDraw`（把弃牌堆洗回去）。无孩子。
        | NodeKind::ShuffleDiscardIntoDraw
        // §238：`gainMaxHealth`（抬高上限）与它的 "If Fatal" 变体。无孩子。
        | NodeKind::GainMaxHealth
        | NodeKind::DealDamageAndGainMaxHealthIfFatal
        // §233：`setDefensivePool`（把防御池设成某个值）。同上。
        | NodeKind::SetDefensivePool
        // §195.7：`upgradeCards`（改定义 id），同上。
        | NodeKind::UpgradeCards
        // §250：四条（`dealDamageAndIfFatal` 的孩子在下面那道 match 里走，这里只登记）。
        | NodeKind::DealDamageAndIfFatal
        | NodeKind::GainGold
        | NodeKind::PlayCard
        | NodeKind::OfferCards
        | NodeKind::CreateCardCopy
        | NodeKind::OfferRandomCards
        // §146：`repeat`（X 费牌的"跑 X 遍"）。它有孩子，但预检只走一遍 Body ——
        // 次数是运行期的值，预检看不到它。
        | NodeKind::Repeat => {}
    }
    reject_result_key(node)?;
    // `DefinitionFilter` 非空同样是**结构上不可执行**（见模块头），所以也在预检这一道闸上拒：
    // 否则 `sequence[gainBlock, forEachCardInZone(带 DefinitionFilter)]` 会先加格挡再报错。
    reject_definition_filter(node)?;

    walk.depth += 1;
    let outcome = match kind {
        NodeKind::Sequence => {
            let mut ids = [0u16; MAX_CHILDREN];
            let count = node.list_field("Children", &mut ids)?;
            let mut result = Ok(());
            for index in 0..count {
                let Some(id) = ids.get(index).copied() else {
                    result = Err(ExecError::Ir(IrError::List));
                    break;
                };
                result = preflight(node.child(id), max_steps, walk);
                if result.is_err() {
                    break;
                }
            }
            result
        }
        NodeKind::Conditional => {
            // `Then` 是必填（参考 `ArgumentNullException.ThrowIfNull(then)`），`Else` 可缺席。
            let then = node.node_field("Then")?.ok_or(IrError::Missing("Then"))?;
            preflight(then, max_steps, walk)?;
            match node.node_field("Else")? {
                Some(else_branch) => preflight(else_branch, max_steps, walk),
                None => Ok(()),
            }
        }
        // §250：`DealDamageAndIfFatal` 的 `Program` 是**节点孩子**，与 `Then` 同一条理由：
        // 预检走不进去，一棵超深的树就能绕过步数预算（而且"先打伤害再报错"= 部分执行）。
        NodeKind::DealDamageAndIfFatal => {
            if let Some(body) = node.node_field("Program")? {
                preflight(body, max_steps, walk)?;
            }
            Ok(())
        }
        NodeKind::ForEachTarget => {
            // `ForEachTargetEffectNode.Children => [Body]`（`EffectProgramNodes.cs:255`）：
            // 循环体是**唯一**的节点孩子，所以预检必须走进它 —— 否则
            // `sequence[gainBlock, forEachTarget(forEachCardInZone)]` 会先加格挡再报错（部分执行）。
            let body = node.node_field("Body")?.ok_or(IrError::Missing("Body"))?;
            preflight(body, max_steps, walk)
        }
        NodeKind::ForEachCardInZone => {
            // 同一个理由：`ForEachCardInZoneNode.Children => [Body]`（`EffectProgramNodes.cs:305`）。
            let body = node.node_field("Body")?.ok_or(IrError::Missing("Body"))?;
            preflight(body, max_steps, walk)
        }
        // 其余 7 种"产出型"节点没有节点孩子（它们的孩子是表达式，不是节点）。
        _ => Ok(()),
    };
    walk.depth -= 1;
    outcome
}

// =============================================================================================
// 节目调度：派发 + 完成（批次 2）
// =============================================================================================
//
// 参考的形状（逐行读过，行号都写在下面）：
//
// * `EffectProgramExecutor.Execute`：预检 → 发号 → 拿/建节目链（`??`）→ 建帧 → 注册 →
//   `using (EnterEffectChain(chain)) ExecuteNode(root)`（`EffectProgramExecution.cs:22-61`）。
// * **节点执行器先干自己的事**（把效果请求塞进队列），再把"我完成了"塞进续延队列：
//   `dealDamage` `:638-641`、`gainBlock` `:779`、`heal` `:680`、`drawCards` `:1424`、
//   `NoOp` `:176-178`。
// * `Sequence` **先把所有孩子都派发完**，再用一个共享计数器数剩余（`:202-211`）。
// * `forEach*` 的每个迭代体完成后，**在节目链里**接着跑下一趟（`:496-504`、`:426-427`）。
// * 续延在**顶层**跑（`CombatEventHandling.cs:107-111`）⇒ "谁最后完成"决定了终态回调
//   落在链里还是链外，而那就是 `chain_num` 的那一笔（`shredder_drawer` 那 2 格就是它）。
//
// ⚠️ 这里**没有任何闭包进队列**：一条续延 = `(帧槽, 节点槽)`，节点槽带父与计数
// （见 `state::ProgramNodeSlot`）。

/// 一次节目派发的结果。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProgramRun {
    /// 帧槽。
    pub frame: ProgramExecutionSlot,
    /// 派发阶段（不含排空）的统计。
    pub stats: ExecStats,
}

/// 派发一个节点，返回它的节点槽（`NO_NODE_SLOT` = 没派发，例如战斗已结束）。
///
/// 参考的 `ExecuteNode`（`EffectProgramExecution.cs:91-160`）。计步与 `frame.IsTerminal`
/// 两道闸都在**计步之前**（`:104-114`），与参考同序。
fn dispatch_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    parent: u16,
    depth: u32,
    stats: &mut ExecStats,
) -> Result<u16, ExecError> {
    // 战斗结束 ⇒ 后续节点一个都不派发（`frame.IsTerminal` ⇒ `:104-105`）。
    if ctx.state.result != CombatResult::Ongoing {
        return Ok(NO_NODE_SLOT);
    }
    if depth >= MAX_NODE_DEPTH {
        return Err(ExecError::StepLimit);
    }
    // `ProgramStepCount++` 与上限（`:109-114`）。**计数存在帧里**：循环的下一趟是在续延里
    // 派的，那时没有栈上的 `Walk` 可以带过去。
    {
        let Some(record) = ctx.state.program_frames_mut().get_mut(frame) else {
            return Err(ExecError::Modifier);
        };
        record.steps = record.steps.saturating_add(1);
        if record.steps > record.max_steps {
            return Err(ExecError::StepLimit);
        }
    }
    stats.nodes = stats.nodes.saturating_add(1);

    let kind = node.kind()?;
    // 硬规则：`ResultKey` 非空 ⇒ 拒绝（预检里已经拦过一次，这里是第二道闸）。
    reject_result_key(node)?;
    // `DefinitionFilter` 非空 ⇒ 拒绝（同样是第二道闸，见模块头）。
    reject_definition_filter(node)?;

    let frame_index = u8::try_from(frame.index())
        .map_err(|_| ExecError::Capacity(CapacityError::Full(Container::ProgramFrames)))?;
    let slot = ctx.state.program_nodes_mut().alloc(ProgramNodeSlot {
        frame: frame_index,
        kind: ProgramNodeKind::Leaf,
        node: node.id(),
        parent,
        remaining: 0,
        loop_at: NO_LOOP,
        live: true,
    })?;

    let outcome = match kind {
        NodeKind::Sequence => dispatch_sequence(node, ctx, frame, slot, depth, stats),
        NodeKind::Conditional => dispatch_conditional(node, ctx, frame, slot, depth, stats),
        NodeKind::ForEachTarget => dispatch_for_each_target(node, ctx, frame, slot, depth, stats),
        NodeKind::ForEachCardInZone => {
            dispatch_for_each_card_in_zone(node, ctx, frame, slot, depth, stats)
        }
        NodeKind::Repeat => dispatch_repeat(node, ctx, frame, slot, stats),
        // 11 个产出型节点：**只造请求**，不写状态（`exec.rs` 的"请求 + 解析"拆分）。
        NodeKind::DealDamage => deal_damage_node(node, ctx, frame, slot, stats),
        // §250：四条新节点。
        NodeKind::DealDamageAndIfFatal => {
            deal_damage_and_if_fatal_node(node, ctx, frame, slot, depth, stats)
        }
        NodeKind::GainGold => gain_gold_node(node, ctx, frame, slot, stats),
        NodeKind::PlayCard => play_card_node(node, ctx, frame, slot, stats),
        NodeKind::OfferCards => offer_cards_node(node, ctx, frame, slot, stats),
        NodeKind::CreateCardCopy => create_card_copy_node(node, ctx, frame, slot, stats),
        NodeKind::OfferRandomCards => offer_random_cards_node(node, ctx, frame, slot, stats),
        NodeKind::GainBlock => gain_block_node(node, ctx, frame, slot, stats),
        NodeKind::ApplyStatus => apply_status_node(node, ctx, frame, slot, stats),
        NodeKind::Heal => heal_node(node, ctx, frame, slot, stats),
    NodeKind::EndTurn => end_turn_node(node, ctx, frame, slot, stats),
    NodeKind::ExtraTurn => extra_turn_node(node, ctx, frame, slot, stats),
    NodeKind::CreateCombatant => create_combatant_node(node, ctx, frame, slot, stats),
    NodeKind::DestroyCombatant => destroy_combatant_node(node, ctx, frame, slot, stats),
        NodeKind::CarryAwayStolenGold => {
            carry_away_stolen_gold_node(node, ctx, frame, slot, stats)
        }
        NodeKind::SetCombatantCounter => set_combatant_counter_node(node, ctx, frame, slot, stats),
        NodeKind::ModifyStatusStacks => modify_status_stacks_node(node, ctx, frame, slot, stats),
        NodeKind::DrawCards => draw_cards_node(node, ctx, frame, slot, stats),
        NodeKind::GainResource => gain_resource_node(node, ctx, frame, slot, stats),
        NodeKind::LoseResource => lose_resource_node(node, ctx, frame, slot, stats),
        NodeKind::CreateCardInstance => create_card_instance_node(node, ctx, frame, slot, stats),
        NodeKind::CreateRandomCardInstance => {
            create_random_card_instance_node(node, ctx, frame, slot, stats)
        }
        NodeKind::PlayTopCardOfDrawPile => {
            play_top_card_of_draw_pile_node(node, ctx, frame, slot, stats)
        }
        NodeKind::ShuffleDiscardIntoDraw => {
            shuffle_discard_into_draw_node(node, ctx, frame, slot, stats)
        }
        NodeKind::MoveCardToZone => move_card_to_zone_node(node, ctx, frame, slot, stats),
        NodeKind::SelectCards => select_cards_node(node, ctx, frame, slot, stats),
        NodeKind::ChooseCards => choose_cards_node(node, ctx, frame, slot, stats),
        NodeKind::AddCardCounter => add_card_counter_node(node, ctx, frame, slot, stats),
        NodeKind::SetDefensivePool => set_defensive_pool_node(node, ctx, frame, slot, stats),
        NodeKind::LoseHp => lose_hp_node(node, ctx, frame, slot, stats),
        NodeKind::GainMaxHealth => gain_max_health_node(node, ctx, frame, slot, stats),
        NodeKind::DealDamageAndGainMaxHealthIfFatal => {
            deal_damage_and_gain_max_health_if_fatal_node(node, ctx, frame, slot, stats)
        }
        NodeKind::DealDamageAndHealByLoss => {
            deal_damage_and_heal_by_loss_node(node, ctx, frame, slot, stats)
        }
        NodeKind::DealDamageWithTagBonus => {
            deal_damage_with_tag_bonus_node(node, ctx, frame, slot, stats)
        }
        NodeKind::DealDamageToRandomTarget => {
            deal_damage_to_random_target_node(node, ctx, frame, slot, stats)
        }
        NodeKind::UpgradeCards => upgrade_cards_node(node, ctx, frame, slot, stats),
    };
    outcome?;
    Ok(slot)
}

/// 把"这个节点完成了"塞进续延队列（参考的 `EnqueueContinuation(onComplete)`）。
fn resume_later(
    state: &mut CombatState,
    frame: ProgramExecutionSlot,
    slot: u16,
) -> Result<(), ExecError> {
    state.enqueue_continuation(Continuation::ProgramResume { frame, node: slot })?;
    Ok(())
}

/// 处理"节点槽 `slot` 完成了"（续延体）。**它就是参考那些闭包本身**。
///
/// 一次完成可能连锁触发好几层：子节点完成 → 序列的 `remaining` 减到 0 ⇒ 序列也完成 →
/// 它的父是循环 ⇒ 跑下一趟 …… 一路走到帧根 ⇒ 节目终态。
fn complete(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    anchor: Option<NodeRef<'_>>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let Some(frame_record) = state.program_frames().get(frame).copied() else {
        // 帧已经被回收 ⇒ 陈旧续延（`EffectProgramExecution.cs:51-54`）。
        return Ok(());
    };
    if frame_record.state != ProgramFrameState::Running {
        return Ok(());
    }
    let frame_index = u8::try_from(frame.index())
        .map_err(|_| ExecError::Capacity(CapacityError::Full(Container::ProgramFrames)))?;

    let mut finished = slot;
    loop {
        // 战斗中途结束 ⇒ 帧按 Cancelled 收尾（`CancelDueToCombatEnd`，`:164-171`）。
        // ⚠️ 这**不是**"跳过"：终态回调照样跑（参考的 `RunTerminalCleanup` 就在里面），
        // 只是出牌落的那个区什么都不做（`Cards/CardPlay.cs:262`）。
        if state.result != CombatResult::Ongoing {
            return finish_frame(state, frame, ProgramFrameState::Cancelled);
        }
        let Some(record) = state.program_nodes().get(finished).copied() else {
            return Ok(());
        };
        // 陈旧续延：槽已经被回收给别人了。
        if record.frame != frame_index {
            return Ok(());
        }
        let parent = record.parent;
        state.program_nodes_mut().free(finished);

        if parent == NO_NODE_SLOT {
            // 帧根完成 ⇒ 节目终态。**环境链此刻是什么，就是 `terminal_chain`**。
            return finish_frame(state, frame, ProgramFrameState::Completed);
        }

        let Some(parent_record) = state.program_nodes().get(parent).copied() else {
            return Ok(());
        };
        match parent_record.kind {
            ProgramNodeKind::Sequence => {
                let remaining = parent_record.remaining.saturating_sub(1);
                if let Some(cell) = state.program_nodes_mut().get_mut(parent) {
                    cell.remaining = remaining;
                }
                if remaining > 0 {
                    // 还有兄弟没完成 —— 参考里这就是"什么都不做"（`:205-210`）。
                    return Ok(());
                }
                finished = parent;
            }
            ProgramNodeKind::Pass => {
                // 直通（`Conditional` 的分支 / 循环体）：它自己的完成 = 父的完成。
                finished = parent;
            }
            ProgramNodeKind::Loop => {
                // ⚠️ "下一趟"的下标存在**循环槽**上（`start_iteration` 写的那个
                // `nextIndex`，`EffectProgramNodeExecutors.cs:496`）。
                // 读刚完成的那个槽的 `remaining` 是恒 0 ⇒ 循环会一直重跑第 0 趟
                // （实测：第 2 趟搬同一张卡，`move_card_for` 报 Modifier）。
                let next_index = parent_record.remaining;
                // ⚠️ 迭代快照挂在**循环槽**上（`parent_record.loop_at`），不是刚完成的那个
                // 子槽上 —— 子槽的 `loop_at` 恒 `NO_LOOP`。读错的结果是 `Full/Modifier` 而不是
                // "循环少跑一趟"，所以它会响，但报错了位置。
                let loop_at = parent_record.loop_at;
                let Some(loop_entry) = state.program_loops().get(loop_at).copied() else {
                    return Err(ExecError::Modifier);
                };
                // `:501-503`：`ctx.PopIterationCard()`（以及 `:425` 的 `PopIterationTarget`）
                // 在**下一趟之前**跑，所以嵌套循环恢复的是外层那一趟的绑定。
                if let Some(cell) = state.program_frames_mut().get_mut(frame) {
                    cell.iteration_target = loop_entry.saved_target;
                    cell.iteration_card = loop_entry.saved_card;
                }
                if usize::from(next_index) < loop_entry.list.len() {
                    if let Some(cell) = state.program_nodes_mut().get_mut(parent) {
                        cell.remaining = next_index;
                    }
                    // `:502-503`：`using (c.EnterEffectChain(ctx.EffectChain!))` —— 下一趟
                    // **在节目链里**跑。这一句就是 `shredder_drawer` 那 2 格的机制。
                    let chain = frame_record.chain;
                    return state.with_chain(chain, |state| {
                        let mut ctx = frame_context(state, content, frame)?;
                        start_iteration(&mut ctx, anchor, frame, parent, stats)
                    });
                }
                // 迭代走完：`ExecuteIteration` 在**同一个 `using` 里**调 `onComplete`
                // （`:489-493`），所以它也是**在节目链里**完成的 —— 这一支同样是那 2 格的机制。
                state.program_loops_mut().free(loop_at);
                let chain = frame_record.chain;
                return state.with_chain(chain, |state| {
                    complete_in_chain(state, content, anchor, frame, parent, stats)
                });
            }
            ProgramNodeKind::Leaf | ProgramNodeKind::Free => {
                // 不变量：叶子没有子节点。
                return Err(ExecError::Modifier);
            }
        }
    }
}

/// 在链作用域里继续"往上完成"（把 `complete` 的那条走链逻辑重入一次）。
///
/// 单独一个函数的理由只有一个：`with_chain` 的闭包拿不到 `&mut ExecContext`（`ctx` 自己
/// 握着 `&mut CombatState`），而 `complete` 的其余路径不需要它。
fn complete_in_chain(
    state: &mut CombatState,
    content: Option<&Content<'_>>,
    anchor: Option<NodeRef<'_>>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    complete(state, content, anchor, frame, slot, stats)
}

/// 用帧里存的上下文重建一个 [`ExecContext`]（续延里跑的时候没有栈上的 `ctx`）。
fn frame_context<'a>(
    state: &'a mut CombatState,
    content: Option<&'a Content<'a>>,
    frame: ProgramExecutionSlot,
) -> Result<ExecContext<'a>, ExecError> {
    let Some(record) = state.program_frames().get(frame).copied() else {
        return Err(ExecError::Modifier);
    };
    let mut ctx = ExecContext::new(
        state,
        record.source,
        record.target,
        record.iteration_target,
        record.max_steps,
    );
    ctx.iteration_card = record.iteration_card;
    // §225：解析/续延重建上下文时，**迭代卡的 tag 位**与**正在结算的牌**都要拿回来。
    ctx.event_flags = record.event_flags;
    ctx.resolving_card = record.resolving_card;
    ctx.x_cost = record.x_cost;
    ctx.content = content;
    Ok(ctx)
}

/// 帧终态：**同步**跑终态回调（`EffectProgramIdentity.cs:104-111`），记下终态那一刻的链。
///
/// ⚠️ **不回收帧槽**：续延里存的是帧下标，回收得太早会让后面那条陈旧续延撞上一个**新**帧。
/// 回收由 [`reap_frames`] 在排空结束时统一做。
fn finish_frame(
    state: &mut CombatState,
    frame: ProgramExecutionSlot,
    terminal: ProgramFrameState,
) -> Result<(), ExecError> {
    let Some(record) = state.program_frames().get(frame).copied() else {
        return Ok(());
    };
    if record.state != ProgramFrameState::Running {
        // 一个帧只有一个终态（`EffectProgramIdentity.cs:56-58` 的"exactly one terminal state"）。
        return Ok(());
    }
    let chain = state.current_chain();
    if let Some(cell) = state.program_frames_mut().get_mut(frame) {
        cell.state = terminal;
        cell.terminal_chain = chain;
        // 作用域**无条件**关闭（`EffectProgramNodeExecutors.cs:484-485`）：帧终态时把迭代绑定
        // 还原成进来时的样子。fault / cancel 两条路径都走这里，所以不会"留一张卡绑在帧上"。
        cell.iteration_target = cell.entry_iteration_target;
        cell.iteration_card = cell.entry_iteration_card;
    }
    // 终态回调（参考的 `RunTerminalCleanup`）。它是**数据**驱动的，不是闭包。
    crate::play::run_terminal_hook(state, record.hook, terminal)
}

/// 解析失败 ⇒ 绑回发起它的帧（`FaultDueToNativeHandler`，`EffectProgramIdentity.cs:156-162`）。
fn fail_owner(
    state: &mut CombatState,
    owner: Option<ProgramExecutionSlot>,
    error: ExecError,
) -> Result<(), ExecError> {
    fail_frame(state, owner)?;
    Err(error)
}

/// 战斗结束时取消所有在飞的帧（`CombatState.SetResult` → `CancelDueToCombatEnd`，`:358-367`）。
///
/// `at_chain` 是**结果被设上那一刻**的环境链（解析某条效果时 = 那条效果的链）。它必须由
/// 调用方给：本函数返回时那个作用域已经退出了，再读 `current_chain` 就变成 `NONE`，
/// 而 Cancelled 的收尾笔数恰恰取决于它。
pub fn cancel_live_frames(state: &mut CombatState, at_chain: ChainSlot) -> Result<(), ExecError> {
    let frames: [Option<ProgramExecutionSlot>; MAX_PROGRAM_FRAMES] = {
        let mut out = [None; MAX_PROGRAM_FRAMES];
        for (index, record) in state.program_frames().iter_live() {
            if record.state == ProgramFrameState::Running {
                out[index] = Some(ProgramExecutionSlot::from_index(index));
            }
        }
        out
    };
    for frame in frames.iter().flatten().copied() {
        state.with_chain(at_chain, |state| {
            finish_frame(state, frame, ProgramFrameState::Cancelled)
        })?;
    }
    Ok(())
}

/// 回收所有已到终态的帧（排空结束时调一次）。
pub fn reap_frames(state: &mut CombatState) {
    let frames: [Option<ProgramExecutionSlot>; MAX_PROGRAM_FRAMES] = {
        let mut out = [None; MAX_PROGRAM_FRAMES];
        for (index, record) in state.program_frames().iter_live() {
            if record.state != ProgramFrameState::Running {
                out[index] = Some(ProgramExecutionSlot::from_index(index));
            }
        }
        out
    };
    for frame in frames.iter().flatten().copied() {
        let Some(index) = u8::try_from(frame.index()).ok() else {
            continue;
        };
        // 帧持有的那一次链引用在这里还回去（见 `begin_without_preflight` 的引用计数说明）。
        if let Some(record) = state.program_frames().get(frame).copied() {
            state.release_chain(record.chain);
        }
        state.program_nodes_mut().free_frame(index);
        state.program_frames_mut().free(frame);
    }
}

// =============================================================================================
// 控制流节点（派发那一半）
// =============================================================================================

/// 硬规则的一道闸：`ResultKey` 字段**存在且有值**就拒绝。
///
/// `Absent`/`Null` 是"没写"的两种拼法（见 `ir.rs` 模块头事实 3），都放行。
fn reject_result_key(node: NodeRef<'_>) -> Result<(), ExecError> {
    match node.field("ResultKey")? {
        None | Some(Value::Absent) | Some(Value::Null) => Ok(()),
        Some(_) => Err(ExecError::ResultKeyNotSupported),
    }
}

/// 第二道硬闸：`DefinitionFilter` **存在且有值**就拒绝（见模块头）。
///
/// 为什么要拒（而不是实现它）：它是 `CardDefinitionId?`（`EffectProgramNodes.cs:294`），
/// 也就是"只取某种定义的卡"这一条过滤 —— 本内核**能**实现（按 `CardInstance::definition_id`
/// 逐字比较即可），但它在镜像里 2 条 term **全是 NULL**、从没有真实使用，
/// 而没有一处真实使用过的分支就无法被真实镜像验证。**宁可拒**：
/// 一张牌安静地少搬了几张卡，比报错糟得多。
///
/// 两种拼法都响亮失败，**都不静默放行**：
/// * 线上真正的非空值是 `_wrap_lower` 包装串 ⇒ [`NodeRef::field`] 报
///   [`IrError::WrongKind`]`("F_TERM")`（`ir.rs` 故意不收那个拼法）；
/// * 若镜像把它写成别的对象 ⇒ 这里报 [`SelError::UnsupportedKind`]
///   （该变体的含义就是"这一种选择器/判别串不在 v1 的战斗路径上"）。
fn reject_definition_filter(node: NodeRef<'_>) -> Result<(), ExecError> {
    match node.field("DefinitionFilter")? {
        None | Some(Value::Absent) | Some(Value::Null) => Ok(()),
        Some(_) => Err(ExecError::Sel(SelError::UnsupportedKind)),
    }
}


// =============================================================================================
// 6 种节点
// =============================================================================================

/// `Sequence`：**先把所有孩子都派发完**，再用共享计数器数剩余（`:202-211`）。
///
/// ⚠️ 这条形状是**语义**，不是风格：`remaining` 每减到 0 就调用父的 `onComplete`，
/// 而"谁把它减到 0"决定了节目终态回调落在**哪条链里**（见 `complete`）。
fn dispatch_sequence(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    depth: u32,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let mut ids = [0u16; MAX_CHILDREN];
    let count = node.list_field("Children", &mut ids)?;
    let remaining = u16::try_from(count).map_err(|_| ExecError::Ir(IrError::List))?;
    if let Some(cell) = ctx.state.program_nodes_mut().get_mut(slot) {
        cell.kind = ProgramNodeKind::Sequence;
        cell.remaining = remaining;
    }
    if count == 0 {
        // `:188-193`：空序列把 `onComplete` 塞进续延队列（不是立刻完成）。
        return resume_later(ctx.state, frame, slot);
    }
    for index in 0..count {
        let Some(id) = ids.get(index).copied() else {
            return Err(ExecError::Ir(IrError::List));
        };
        dispatch_node(node.child(id), ctx, frame, slot, depth + 1, stats)?;
    }
    Ok(())
}

/// `Conditional`：`Condition` 为真走 `Then`，否则走 `Else`（可缺席）。
///
/// 参考（`:250-279`）：选中的分支派发下去，**它的完成就是条件节点的完成**
/// （`DispatchWithScope` 的 `onComplete?.Invoke(c)`）；没有 `Else` 且条件为假 ⇒
/// `EnqueueContinuation(onComplete)`（`:261-262`）。
/// `OpenScope`/`CloseScope` 那一对是给 `ResultKey` 的，本内核在预检就拒绝 `ResultKey`。
fn dispatch_conditional(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    depth: u32,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    if let Some(cell) = ctx.state.program_nodes_mut().get_mut(slot) {
        cell.kind = ProgramNodeKind::Pass;
    }
    let condition = node
        .node_field("Condition")?
        .ok_or(IrError::Missing("Condition"))?;
    let truth = {
        let expr_ctx = ctx.expr_context();
        expr::eval_bool(condition, &expr_ctx)?
    };
    let branch = if truth {
        Some(
            node.node_field("Then")?
                .ok_or(IrError::Missing("Then"))?,
        )
    } else {
        node.node_field("Else")?
    };
    match branch {
        Some(branch) => {
            dispatch_node(branch, ctx, frame, slot, depth + 1, stats)?;
            Ok(())
        }
        None => resume_later(ctx.state, frame, slot),
    }
}

/// §195.9：`node.selectCards` 的候选缓冲 = **牌区容量**（96）。
///
/// 它曾经是 `MAX_SELECTED_CARDS * 8` = 64 且溢出时 `break` —— 一个 96 张的牌堆里排在 65 位之后
/// 的卡根本进不了排序。候选上限（容器容量）与 `Count`（搬几张）是**两个**数。
pub const MAX_CARD_CANDIDATES: usize = crate::state::MAX_CARDS_PER_ZONE;

/// §228：`node.dealDamageToRandomTarget` 的 `Times` 上限。
///
/// 24 是 `MAX_COMBATANTS` 的两倍，也是"一次出牌最多几条伤害请求"的量级上界（§225 的整手牌消耗
/// 也是这个数量级）。再往上不是"更强的牌"，而是把效果队列（`MAX_PENDING_EFFECTS`）当无限用 ——
/// 那条线会在运行期以 `Capacity` 响亮失败，但**内容层就该先说不像话**。
pub const MAX_RANDOM_HITS: usize = 24;

/// §226：`node.chooseCards` 一次最多造几份副本（`Copies` 的上限）。
///
/// 取 4 而不是 99：StS 里复制牌的牌最多要 3 份（`Nightmare`），4 留一格；而"一次造几十份"
/// 若真被写进内容，它撞的是手牌容量（`MAX_CARDS_PER_ZONE`）—— 两条界线都在，宁可在**内容**
/// 这一层就说出"这个数不像话"，而不是让它到运行期变成一次容量拒绝。
pub const MAX_COPIES_PER_CHOICE: usize = 4;

/// §195.4：`node.selectCards` 一次最多搬几张（与 `Count` 的上限是同一个数）。
///
/// 8 是**容量**，不是规则：超了报 `Missing("Count")`（越界的 Count 是内容错，不是"少搬几张"）。
pub const MAX_SELECTED_CARDS: usize = 8;

/// `DealDamage`：`Amount` → `TargetSelector` → **每个目标一条请求**（不写状态）。
///
/// 金额**先于**目标解析求值一次（`EffectProgramNodeExecutors.cs:608-609` 的顺序），
/// 修饰器管线（力量/虚弱/易伤）在**解析时**才读状态（`DamageEffects.cs:273-320`）。
fn deal_damage_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let ignores_block = node.bool_field("IgnoresBlock")?.unwrap_or(false);
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let source = ctx.source;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::DealDamage {
                target: Some(*target),
                amount,
                ignores_block,
                source,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// §231：`node.dealDamageAndHealByLoss` 的实体 —— 打伤害，然后按**实际掉的血**给来源回血。
///
/// `Reaper`：`Deal 4 (5) damage to ALL enemies. Heal unblocked damage dealt.`
///
/// 为什么必须是一个节点：参考用 `ResultKey` 把"这一击掉了多少血"传给下一个节点，而本内核
/// **明确不支持 ResultKey**。`resolve_damage` 返回 `(blocked, health_lost)`，所以节点自己算。
///
/// ⚠️ 代价是这一击**立刻生效**（而不是入队后再结算）。这一条是有意为之：格挡/易伤/力量的读取
/// 时点都在 `resolve_damage` 内部，与入队版一致；不同的只是它与**同一节目里后续节点**的相对顺序。
/// `Reaper` 需要的恰恰是"先掉血、再按掉的血回血"，那个顺序在入队模型里拿不到。
fn deal_damage_and_heal_by_loss_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let ignores_block = node.bool_field("IgnoresBlock")?.unwrap_or(false);
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let source = ctx.source;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    if count == 0 {
        return resume_later(ctx.state, frame, slot);
    }
    let mut lost_total = 0i32;
    for target in targets.iter().take(count) {
        let (_, lost) = resolve_damage(ctx, target, amount, ignores_block)?;
        stats.effects = stats.effects.saturating_add(1);
        lost_total = lost_total.saturating_add(lost);
    }
    // 回血走**请求**（不是同步写）：它要过与其它治疗同一条管线（上限钳制、`Healed` 事件）。
    if lost_total > 0 {
        if let Some(owner) = source {
            ctx.state.enqueue_effect_with_owner(
                EffectRequest::Heal {
                    target: Some(owner),
                    amount: lost_total,
                },
                Some(frame),
            )?;
            stats.effects = stats.effects.saturating_add(1);
        }
    }
    resume_later(ctx.state, frame, slot)
}

/// §230：`node.dealDamageWithTagBonus` 的实体 —— `Amount + Bonus × 带该 tag 的牌数`。
///
/// 数牌的范围是**手牌 + 抽牌堆 + 弃牌堆**，正好是 wiki 正文说的 "your deck when this card is played"
/// （消耗/放逐/暂存里的牌不再是"你的牌组"）。正在结算的那张牌**仍在手牌里**（参考的落区在
/// `onTerminal`，§225），所以它自己也数进去 —— 与 wiki 的 "increases not only the damage of other
/// copies, but also of itself" 一致，不需要为它开特例。
///
/// 没有内容 ⇒ **响亮失败**（`Missing("content")`）：没有内容就查不了 tag，而"数到 0 张"会让这张牌
/// 安静地只打基础伤害 —— 那正是"工具报成功、被测对象在失败"的形状。
fn deal_damage_with_tag_bonus_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let base = eval_amount(node, "Amount", ctx)?;
    let bonus = eval_amount(node, "Bonus", ctx)?;
    let tag = node.str_field("Tag")?.ok_or(IrError::Missing("Tag"))?;
    let ignores_block = node.bool_field("IgnoresBlock")?.unwrap_or(false);
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let source = ctx.source;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    if count == 0 {
        return resume_later(ctx.state, frame, slot);
    }
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };
    // ⚠️ **"谁的牌"与"打谁"是两个槽**（这条第一版写错了：拿 `TargetSelector` 解出来的敌人去数手牌，
    // 结果永远 0 张，牌只打基础伤害 —— 而"只打基础伤害"看起来完全正常）。数的是**出牌者**的牌堆。
    let Some(owner) = ctx.source else {
        return resume_later(ctx.state, frame, slot);
    };

    let mut tagged = 0i32;
    for zone in [CardZone::Hand, CardZone::DrawPile, CardZone::DiscardPile] {
        for card in ctx.state.zone_cards(&owner, zone) {
            if content
                .card_has_tag(card.definition_id.as_str(), tag)
                .unwrap_or(false)
            {
                tagged = tagged.saturating_add(1);
            }
        }
    }
    let amount = base.saturating_add(bonus.saturating_mul(tagged));
    for target in targets.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::DealDamage {
                target: Some(*target),
                amount,
                ignores_block,
                source,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// §229：`node.addCardCounter` 的实体 —— 给**一份副本**的某个 mark counter 加一个增量。
///
/// `{CardExpression, OwnerSelector, CounterId, Delta}`。`CardExpression` 通常是
/// `cardInstance.resolving`（"这张牌自己变强"），也可以是 `cardInstance.iterated`。
///
/// 三条纪律：
/// * 计数器**不存在**时按 0 起算（`set_mark_counter` 是字典语义）；
/// * `Delta` 是**相对**量 —— 绝对值写 0 会把"已经涨过"抹掉，那种 bug 只在第二张以后才看得出来；
/// * 计数器表满了 ⇒ `set_mark_counter` 自己报 `Capacity`（§161.4 那条预校验的反面：这里没有
///   "先搬后写"的顺序问题，写入失败就是整体失败）。
fn add_card_counter_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let card_expression = node
        .node_field("CardExpression")?
        .ok_or(IrError::Missing("CardExpression"))?;
    let counter = node.str_field("CounterId")?.ok_or(IrError::Missing("CounterId"))?;
    let delta = eval_amount(node, "Delta", ctx)?;
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    let card_id = {
        let expr_ctx = ctx.expr_context();
        expr::eval_card(card_expression, &expr_ctx)?
    };
    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let owner_count = resolve_targets(owner_selector, ctx, &mut owners)?;
    let Some(owner) = owners.first().copied().filter(|_| owner_count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };
    let Some((_, card_slot)) = ctx.state.find_card(&owner, &card_id) else {
        return Err(ExecError::Ir(IrError::Missing("CardExpression")));
    };
    let key = crate::state::CounterId::new(counter).map_err(|_| IrError::Missing("CounterId"))?;
    let current = ctx
        .state
        .card(card_slot)
        .and_then(|card| {
            card.mark_counters()
                .iter()
                .find(|entry| entry.key == key)
                .map(|entry| entry.value)
        })
        .unwrap_or(0);
    // §248：`Mode` —— `Add`（缺席，既有行为）/ `Set`（覆盖成绝对值）。
    // "按印刷费用降到至多 N"不走这里：印刷费用只有**费用管线**读得到，那条路是
    // `CostStage::CapCostAt`（见 `play.rs`），不是"往牌上写一个数"。
    let value = match node.str_field("Mode")? {
        None | Some("Add") => current.saturating_add(delta),
        Some("Set") => delta,
        Some(_) => return Err(ExecError::Ir(IrError::UnknownKind)),
    };
    if let Some(card) = ctx.state.card_mut(card_slot) {
        card.set_mark_counter(key, value)?;
    }
    resume_later(ctx.state, frame, slot)
}

/// §228：`node.dealDamageToRandomTarget` 的实体 —— `Times` 次命中，**每次**从候选池里重掷一个目标。
///
/// 三条语义（都能单独坏掉，所以各有一条判据）：
/// * **每一击各自抽签**：不是"抽一次、打 N 下"。抽签用
///   [`crate::rng::shuffled_pick_index`]（与洗牌同一个生成器），并且**每一击推进一格
///   `random_step`** —— 与 `shuffle_candidates` 同一本账，否则两次同种抽签会给出同一个结果；
/// * 候选池是**派发那一刻**解析出来的（`TargetSelector`），所以这一击抽到谁就是谁，中途死掉的目标
///   不会再被抽到（`resolve_effect` 对已离场目标是 no-op，见 §178）；
/// * 池子是空的 ⇒ **一击都没有**（不是错误）：一条对所有活敌的抽签，在没有活敌时本来就没有答案。
fn deal_damage_to_random_target_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    // 求值顺序与 `dealDamage` 一致：先 `Amount`，再解析目标。
    let amount = eval_amount(node, "Amount", ctx)?;
    let ignores_block = node.bool_field("IgnoresBlock")?.unwrap_or(false);
    let times = node.int_field("Times")?.ok_or(IrError::Missing("Times"))?;
    if !(1..=MAX_RANDOM_HITS as i32).contains(&times) {
        return Err(ExecError::Ir(IrError::Missing("Times")));
    }
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let source = ctx.source;

    let mut pool = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut pool)?;
    if count == 0 {
        return resume_later(ctx.state, frame, slot);
    }

    for _ in 0..times {
        let picked = crate::rng::shuffled_pick_index(
            count,
            ctx.state.random_seed,
            ctx.state.random_step,
        );
        // 一格 `random_step` 一次抽签（`shuffle_candidates` 同一条账）。
        ctx.state.random_step = ctx.state.random_step.saturating_add(1);
        let Some(target) = pool.get(picked).copied() else {
            // `shuffled_pick_index` 的返回值必在 `[0, count)`；走到这里说明那个不变量破了。
            return Err(ExecError::Ir(IrError::List));
        };
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::DealDamage {
                target: Some(target),
                amount,
                ignores_block,
                source,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// `GainBlock`：`Amount` → `TargetSelector` → **每个目标一条请求**（`:775`）。
///
/// 格挡修饰管线（灵巧/脆弱）在解析时读目标的状态（`DefensivePoolEffects.cs:11-105`）。
/// §233：`node.setDefensivePool` 的实体 —— `{TargetSelector, PoolId, Amount}`。
///
/// **每个目标直接写**（不入队）：这是一个"设"，不是"加"，所以没有修饰器要跑、也没有事件要发。
/// `max` 传 `None` ⇒ 保持那一格原有的上限（`set_defensive_pool` 的字典语义）。
///
/// 负值是**内容 bug**，借 [`ExecError::Modifier`] 响亮失败（与 `gainBlock` 的受理不变量同一条）。
fn set_defensive_pool_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let pool = node.str_field("PoolId")?.ok_or(IrError::Missing("PoolId"))?;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    if amount < 0 {
        return Err(ExecError::Modifier);
    }
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    let key = crate::state::DefensivePoolId::new(pool)?;
    for target in targets.iter().take(count) {
        let Some(combatant) = ctx.state.combatant_mut(target) else {
            continue;
        };
        combatant.set_defensive_pool(key, amount, None)?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

fn gain_block_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::GainBlock {
                target: Some(*target),
                amount,
                // §245：这是"牌给的格挡"吗 —— 只在**派发时**说得清。
                from_card: ctx.resolving_card.is_some(),
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// [`gain_block_node`] 的实体（`DefensivePoolEffects.cs:11-105`）：
/// * 修饰后为 0 ⇒ **空操作**，池子连建都不建；
/// * 没有池 ⇒ 建 `current = 量`（`max = None`）；
/// * 有池 ⇒ `newCurrent = min(int.MaxValue, current + 量)`，**`max` 原样保留**。
/// §245：`Panic Button` —— "You cannot gain Block **from cards** for 2 turns"。
///
/// 判据用 `ctx.resolving_card`："这一次格挡是不是一张牌给的"。它是内核里唯一回答这个问题的东西
/// （状态/遗物/敌人招式的节目里它是 `None`）。
///
/// 只归 0，**不报错**：`Panic Button` 那条牌自己的 `gainBlock` 也走这里，而它先给格挡、后挂状态
/// （队列顺序），所以正常出牌时这条规则不生效；只有"状态已经在身上"时才拦。
fn cards_cannot_give_block(ctx: &ExecContext<'_>, target: &CombatantId, from_card: bool) -> bool {
    if !from_card {
        return false;
    }
    ctx.state.combatant(target).is_some_and(|combatant| {
        combatant
            .statuses()
            .iter()
            .any(|instance| instance.definition_id.as_str() == NO_BLOCK_FROM_CARDS_STATUS)
    })
}

/// §245：`standard.no_block_from_cards`（`Panic Button`）。
const NO_BLOCK_FROM_CARDS_STATUS: &str = "standard.no_block_from_cards";

fn gain_block_for(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    amount: i32,
    from_card: bool,
) -> Result<(), ExecError> {
    // §245：`Panic Button` 的"2 回合内不能从牌里获得格挡"。放在**最前面**：早点返回，
    // 后面那串修饰器/容量记账一步都不该动（"拒绝 ⇒ 一个字节都不改"）。
    if cards_cannot_give_block(ctx, target, from_card) {
        return Ok(());
    }
    let snapshot = *ctx.state.combatant(target).ok_or(ExecError::MissingCombatant)?;
    let content = ctx.content;
    let modified = block_stage(amount, snapshot.statuses(), target, content)?;
    if modified != 0 {
        let (current, max, _) = block_pool(&snapshot);
        let total = i64::from(current) + i64::from(modified);
        let new_current = if total > i64::from(i32::MAX) {
            i32::MAX
        } else {
            total as i32
        };
        let key = DefensivePoolId::new(BLOCK_POOL_ID)?;
        let combatant = ctx
            .state
            .combatant_mut(target)
            .ok_or(ExecError::MissingCombatant)?;
        combatant.set_defensive_pool(key, new_current, max)?;
        // 动画日志（§142）：`a` 记**真的加了**多少（修饰后），不是请求额 ——
        // 页面上的数字必须与状态里的数字一致，否则"盾 12"旁边飘一个 +5。
        crate::beat::record(
            ctx.state,
            crate::beat::Beat {
                kind: crate::beat::BeatKind::Block,
                actor: crate::beat::ordinal_of(ctx.state, target),
                target: crate::beat::ordinal_of(ctx.state, target),
                def: crate::beat::NO_DEF,
                flags: 0,
                a: modified,
                b: 0,
                c: 0,
            },
        );
        // §237：`BlockGained` —— 与伤害事件同一形状（唯一出口处入队），Bearer 是**获得格挡的人**。
        // 只在 `modified != 0` 时发：`Juggernaut` 是"每当你获得格挡"，加 0 点不算获得。
        ctx.state
            .enqueue_event(crate::state::CombatEvent::BlockGained {
                combatant: *target,
                amount: modified,
            })
            .map_err(ExecError::Capacity)?;
    }
    Ok(())
}

/// `ApplyStatus`：`Stacks` → `TargetSelector` → **每个目标一条请求**（`:932-958`）。
///
/// 受理不变量（`StatusEffects.cs:55-62`）与合并规则都在解析时跑（[`apply_one_status`]）。
fn apply_status_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let stacks = eval_amount(node, "Stacks", ctx)?;
    let definition_text = node
        .str_field("StatusDefinitionId")?
        .ok_or(IrError::Missing("StatusDefinitionId"))?;
    let definition_id = StatusDefinitionId::new(definition_text)?;
    let duration_turns = node.int_field("DurationTurns")?.unwrap_or(0);
    let charges = node.int_field("Charges")?.unwrap_or(0);
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let source = ctx.source;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::ApplyStatus {
                target: Some(*target),
                definition: definition_id,
                stacks,
                duration: duration_turns,
                charges,
                source,
                source_card: None,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// `Heal`：`Amount` → `TargetSelector` → **每个目标一条请求**（`:658-680`）。
/// 分裂出来的战斗员在内容没给 `Health` 时用这个生命值。
pub const DEFAULT_SPLIT_HEALTH: i32 = 1;

/// `node.destroyCombatant`：**把一个战斗员移出战斗**（§178）。
///
/// 字段：`TargetSelector`（与其它节点同名同义）。解析出来的每个目标都会被移出；
/// 一个都解析不出来就是**响亮失败**（`ExecError::NoSource`），因为"分裂"少了一半会让
/// 内容以为自己成功了，而局面里什么都没变。
///
/// 立即生效，**不**入队 —— 与 [`create_combatant_node`] 对称。原因不是风格：
/// "移除"是`once only` 唯一能表达出来的形式（见 `ir.rs` 的注释）。
fn destroy_combatant_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let _ = &mut *stats;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    if count == 0 {
        return Err(ExecError::NoSource);
    }
    for target in targets.iter().take(count) {
        // A target that is already gone is **not** an error: a multi-hit card can name the same
        // combatant twice, and StS treats "damage/heal a corpse" as a no-op. Only the *selector*
        // producing nothing is a content bug.
        if ctx.state.combatant(target).is_none() {
            continue;
        }
        // Read everything the log needs **before** mutating: `ordinal_of` looks the id up in the
        // roster, and after removal there is nothing to find.
        let ordinal = crate::beat::ordinal_of(ctx.state, target);
        let actor = match ctx.source {
            Some(source) => crate::beat::ordinal_of(ctx.state, &source),
            None => crate::beat::NOBODY,
        };
        let removed = ctx.state.remove_combatant(target)?;
        // Animation log (§142/§178): the page fades this ordinal out.
        let def = crate::beat::intern_def(ctx.state, removed.definition_id.as_str());
        crate::beat::record(
            ctx.state,
            crate::beat::Beat {
                kind: crate::beat::BeatKind::Destroyed,
                actor,
                target: ordinal,
                def,
                flags: 0,
                a: 0,
                b: 0,
                c: 0,
            },
        );
    }
    resume_later(ctx.state, frame, slot)
}

/// `node.carryAwayStolenGold`：**带着偷来的钱离开战斗**（§201，Looter 的 `Escape`）。
///
/// 字段：`CounterId`（内容给的计数器名，例如 `stolen_gold`）、`TargetSelector`（逃跑的那个）。
///
/// 做两件事：把目标身上那一格的**当前值**加进 `state.gold_carried_away`，再把那一格清零。
/// 清零不是"顺手"：`Escape` 之后目标马上被 `destroyCombatant` 摘掉，但如果内容没删它（比如
/// 一个"只带走一半"的变体），留着原值就会在 `fight_end` 被算成**两次**丢失。
///
/// ⚠️ **只有逃走的钱算丢失**。活着的敌人身上的 `stolen_gold` 不算 —— wiki 的原话是
/// `Stolen gold is returned if this enemy is killed`，而"打赢时它还活着"这件事不存在
/// （打赢 = 全灭）。所以运行层不需要另一个"总共偷了多少"的字段。
fn carry_away_stolen_gold_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let _ = &mut *stats;
    let counter_text = node
        .str_field("CounterId")?
        .ok_or(IrError::Missing("CounterId"))?;
    let counter_id = CounterId::new(counter_text)?;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    // 一个都解析不出来 ⇒ 响亮失败：`Escape` 少了这一步会让玩家**白拿**钱，而局面看起来
    // 一切正常（`destroyCombatant` 照样把人摘掉）。
    if count == 0 {
        return Err(ExecError::NoSource);
    }
    for target in targets.iter().take(count) {
        let Some(combatant) = ctx.state.combatant_mut(target) else {
            continue; // 已经不在场：与 `destroyCombatant` 同一条"打尸体是 no-op"
        };
        let stolen = combatant
            .counters()
            .iter()
            .find(|entry| entry.key == counter_id)
            .map_or(0, |entry| entry.value);
        if stolen <= 0 {
            continue;
        }
        combatant.set_counter(counter_id, 0)?;
        ctx.state.gold_carried_away = ctx.state.gold_carried_away.saturating_add(stolen);
    }
    resume_later(ctx.state, frame, slot)
}

/// `node.createCombatant`：**造一个战斗员**（分裂 / 召唤）。
///
/// 字段：`DefinitionId`（内容里 `Monsters` 的 id）、`Health`（可选表达式，缺省取定义的最大生命）、
/// `TeamId`（可选字符串，缺省 `enemy`）。
///
/// 新实例的 id 由 `CombatState.next_combatant_number` 发号：
/// `<definition>#<n>` —— **确定性**（同一个 seed 同一条序列），并且一眼能看出它从哪来。
/// 容量满了走 `add_combatant` 的**响亮失败**，不截断。
fn create_combatant_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let definition = node
        .str_field("DefinitionId")?
        .ok_or(IrError::Missing("DefinitionId"))?;
    let team = node.str_field("TeamId")?.unwrap_or("enemy");

    // 生命：给了就求值，没给就用定义里的最大生命（`0` = 让 state 用默认）。
    let health = match node.node_field("Health")? {
        Some(expr) => {
            let context = ctx.expr_context();
            crate::expr::eval_int(expr, &context)?
        }
        None => 0,
    };

    let definition_id = crate::state::CombatantDefinitionId::new(definition)?;
    let team_id = crate::state::TeamId::new(team)?;

    let number = ctx.state.next_combatant_number;
    let mut buffer = [0u8; 96];
    let mut len = 0usize;
    for byte in definition.as_bytes() {
        if len < buffer.len() - 8 {
            buffer[len] = *byte;
            len += 1;
        }
    }
    buffer[len] = b'#';
    len += 1;
    {
        // The helper wants a [u8; INSTANCE_TEXT_CAP], so hand it its own buffer and copy.
        let mut scratch = [0u8; INSTANCE_TEXT_CAP];
        let text = numbered_instance_text(b"", number, &mut scratch)?;
        for byte in text.as_bytes() {
            if len < buffer.len() {
                buffer[len] = *byte;
                len += 1;
            }
        }
    }
    let id_text = core::str::from_utf8(&buffer[..len]).map_err(|_| ExecError::Modifier)?;
    let id = CombatantId::new(id_text)?;

    // **The summon cap** (`port-plan.md` §139): a fight never holds more than this many living
    // enemies, and asking for one more is a **loud** failure -- a summoner whose action cannot be
    // honoured is a content bug, not something to paper over by dropping the minion.
    let mut living = 0usize;
    for combatant in ctx.state.combatants() {
        if combatant.team_id == team_id
            && combatant.lifecycle_state == crate::state::CombatantLifecycleState::Alive
        {
            living += 1;
        }
    }
    if living >= crate::state::MAX_ENEMIES_IN_FIGHT {
        return Err(ExecError::Capacity(crate::state::CapacityError::Full(
            crate::state::Container::Combatants,
        )));
    }

    let max_health = if health > 0 { health } else { DEFAULT_SPLIT_HEALTH };
    let mut combatant =
        crate::state::Combatant::new(id, definition_id, team_id, max_health, max_health);
    // **Who called it.** `ctx.source` is the combatant whose program is running, so a summon from an
    // enemy action names the summoner; the minion flees when that one falls.
    combatant.owner = ctx.source;
    ctx.state.add_combatant(combatant)?;
    ctx.state.next_combatant_number = number.saturating_add(1);
    // 动画日志（§142）：`target` = 新人在 `combatants()` 里的 ordinal（`add_combatant` 刚
    // 追加过，所以就是最后一格）；`def` = 它的定义名，页面据此挑立绘。
    {
        let ordinal = (ctx.state.combatants().len().saturating_sub(1)).min(usize::from(
            crate::beat::NOBODY - 1,
        )) as u8;
        let def = crate::beat::intern_def(ctx.state, definition_id.as_str());
        crate::beat::record(
            ctx.state,
            crate::beat::Beat {
                kind: crate::beat::BeatKind::Summoned,
                actor: match ctx.source {
                    Some(source) => crate::beat::ordinal_of(ctx.state, &source),
                    None => crate::beat::NOBODY,
                },
                target: ordinal,
                def,
                flags: 0,
                a: i32::from(ordinal),
                b: max_health,
                c: 0,
            },
        );
    }
    stats.effects = stats.effects.saturating_add(1);
    resume_later(ctx.state, frame, slot)
}

/// `node.endTurn`：请求**结束当前回合**（本内核自己的节点，`port-plan.md` §125）。
///
/// 没有字段：谁去结束回合由战斗循环决定，节目只说"该结束了"。
/// `node.extraTurn`：让目标**再来一个回合**（本内核自己的节点，`port-plan.md` §127）。
///
/// 字段与 `applyStatus` 同形：一个 `TargetSelector`。
fn extra_turn_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::ExtraTurn {
                target: Some(*target),
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

fn end_turn_node(
    _node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    ctx.state
        .enqueue_effect_with_owner(EffectRequest::EndTurn, Some(frame))?;
    stats.effects = stats.effects.saturating_add(1);
    resume_later(ctx.state, frame, slot)
}

fn heal_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::Heal {
                target: Some(*target),
                amount,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// [`heal_node`] 的实体（`DamageEffects.cs:331-377`）：`long` 中间量防溢出，
/// **没有**任何修饰器/拦截器挂钩。
fn heal_for(ctx: &mut ExecContext<'_>, target: &CombatantId, amount: i32) -> Result<(), ExecError> {
    let snapshot = *ctx.state.combatant(target).ok_or(ExecError::MissingCombatant)?;
    let requested = i64::from(snapshot.health_current) + i64::from(amount);
    let capped = if requested > i64::from(snapshot.health_max) {
        snapshot.health_max
    } else {
        requested as i32
    };
    let combatant = ctx
        .state
        .combatant_mut(target)
        .ok_or(ExecError::MissingCombatant)?;
    combatant.health_current = capped;
    // 动画日志（§142）：`a` 是**真的回了**多少（上限之后），不是请求额。
    let healed = (capped - snapshot.health_current).max(0);
    if healed > 0 {
        let ordinal = crate::beat::ordinal_of(ctx.state, target);
        crate::beat::record(
            ctx.state,
            crate::beat::Beat {
                kind: crate::beat::BeatKind::Heal,
                actor: ordinal,
                target: ordinal,
                def: crate::beat::NO_DEF,
                flags: 0,
                a: healed,
                b: 0,
                c: 0,
            },
        );
    }
    Ok(())
}

// =============================================================================================
// W4e：另外 7 种节点（`setCombatantCounter` / `modifyStatusStacks` / `forEachTarget` /
// `drawCards` / `gainResource` / `loseResource` / `createCardInstance`）
//
// 每一个字段名都是从 **core 镜像实测**出来的（`tools/contentc` 的 opcode 表），不是从
// C# 属性名猜的。二者**确实不同名的地方**已在各函数上标明：
//   * `createCardInstance.ToZone` 是裸串（`"DiscardPile"`/`"Hand"`），flags=0；
//   * `*.CounterId` / `*.StatusDefinitionId` / `*.ResourceId` / `*.CardDefinitionId` 是
//     `FLAG_WRAP_LOWER`（JSON 里是 `{"value": …}`，但**包装对象根本不落盘**）；
//   * `createCardInstance.Count` 缺席 ⇒ 1（参考构造函数默认值），**镜像 9 条都写了 1**。
// =============================================================================================

/// `SetCombatantCounter`：`Amount` → `TargetSelector` → **每个目标一条请求**（`:990-994`）。
///
/// 绝对写 / 相对加的选择在解析时做（[`set_counter_for`]）。
/// `Relative` 缺席 ⇒ **true**（`EffectProgramNativeNodes.cs:670` 的构造默认值）。
fn set_combatant_counter_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    // 求值顺序照参考：`EvaluateAmount` 在解析目标之前（`EffectProgramNodeExecutors.cs:987-989`）。
    let amount = eval_amount(node, "Amount", ctx)?;
    let counter_text = node
        .str_field("CounterId")?
        .ok_or(IrError::Missing("CounterId"))?;
    let counter_id = CounterId::new(counter_text)?;
    let relative = node.bool_field("Relative")?.unwrap_or(true);
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::SetCombatantCounter {
                target: Some(*target),
                key: counter_id,
                amount,
                relative,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// [`set_combatant_counter_node`] 的实体（`CombatantCounterEffects.cs:13-35`）：
/// * `Relative == true` ⇒ `GetCounter(id) + amount`（`CombatantState.cs:66-71`，C# 默认
///   unchecked ⇒ 溢出**回绕**，这里用 `wrapping_add` 逐字对应）；
/// * `Relative == false` ⇒ `SetCounter(id, amount)`（`:30-34`，绝对值，覆盖任何旧值）。
/// * 缺席的计数器读作 **0**（`CombatantState.cs:64`）。
fn set_counter_for(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    counter_id: CounterId,
    amount: i32,
    relative: bool,
) -> Result<(), ExecError> {
    let current = counter_of(
        ctx.state.combatant(target).ok_or(ExecError::MissingCombatant)?,
        &counter_id,
    );
    let value = if relative {
        current.wrapping_add(amount)
    } else {
        amount
    };
    ctx.state
        .combatant_mut(target)
        .ok_or(ExecError::MissingCombatant)?
        .set_counter(counter_id, value)?;
    Ok(())
}

/// `ModifyStatusStacks`：`Delta` → `TargetSelector` → **每个目标一条请求**（`:1287-1308`）。
///
/// 四条受理/运算规则在解析时跑（[`modify_one_status_stacks`]）：
///
/// 1. **目标是"第一条匹配的实例"**（`StatusEffects.cs:858`），不是聚合、不是全部实例。
/// 2. **该状态不在身 ⇒ 静默无事发生**（`:860-865`）。
/// 3. 新层数 = `(int)Math.Max(0, Math.Min(int.MaxValue, (long)old + delta))`（`:823`）。
/// 4. **新层数为 0 且旧层数 > 0 ⇒ 删掉这条实例**（`:830-838`）；净变化 0 ⇒ 什么都不写（`:826-827`）。
fn modify_status_stacks_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let delta = eval_amount(node, "Delta", ctx)?;
    let definition_text = node
        .str_field("StatusDefinitionId")?
        .ok_or(IrError::Missing("StatusDefinitionId"))?;
    let definition_id = StatusDefinitionId::new(definition_text)?;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::ModifyStatusStacks {
                target: Some(*target),
                definition: definition_id,
                delta,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// 对一个目标执行 [`modify_status_stacks_node`] 的语义（见那里的四条）。
fn modify_one_status_stacks(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    definition_id: StatusDefinitionId,
    delta: i32,
) -> Result<(), ExecError> {
    let index = ctx
        .state
        .combatant(target)
        .ok_or(ExecError::MissingCombatant)?
        .statuses()
        .iter()
        .position(|status| status.definition_id == definition_id);
    // 2. 不在身 ⇒ 什么都不做（`:860-865`）。
    let Some(index) = index else {
        return Ok(());
    };

    let (old_stacks, new_stacks) = {
        let combatant = ctx
            .state
            .combatant_mut(target)
            .ok_or(ExecError::MissingCombatant)?;
        let Some(status) = combatant.statuses_mut().get_mut(index) else {
            // `position` 刚给的下标不可能越界；这一条只为"没有 panic 路径"存在。
            return Err(ExecError::Modifier);
        };
        let old_stacks = status.stacks;
        // 3. `max(0, min(i32::MAX, old + delta))`，中间量是 i64。
        let sum = i64::from(old_stacks) + i64::from(delta);
        let new_stacks = if sum < 0 {
            0
        } else if sum > i64::from(i32::MAX) {
            i32::MAX
        } else {
            sum as i32
        };
        if new_stacks != old_stacks {
            status.stacks = new_stacks;
        }
        (old_stacks, new_stacks)
    };

    // 4. 净变化为 0 ⇒ 不写、不删（`:826-827`）。
    if new_stacks == old_stacks {
        return Ok(());
    }
    // 层数真的变了 ⇒ `StatusStacksChanged`（`StatusEffects.cs:826` 的入队点）。
    ctx.state
        .enqueue_event(crate::state::CombatEvent::StatusStacksChanged { target: *target })
        .map_err(ExecError::Capacity)?;
    // 动画日志（§142）：`a` = **净变化**（可负）。写在这里、删实例之前，因为
    // "层数被减到 0"是"卸掉一层"之后的事 —— 顺序反过来页面会先看到图标消失再看到数字掉。
    let def = crate::beat::intern_def(ctx.state, definition_id.as_str());
    let ordinal = crate::beat::ordinal_of(ctx.state, target);
    crate::beat::record(
        ctx.state,
        crate::beat::Beat {
            kind: crate::beat::BeatKind::StatusChanged,
            actor: ordinal,
            target: ordinal,
            def,
            flags: 0,
            a: new_stacks - old_stacks,
            b: new_stacks,
            c: 0,
        },
    );
    if new_stacks == 0 && old_stacks > 0 {
        remove_status_at(ctx, target, index)?;
        // 实例被删 ⇒ 单独一条：页面据此把图标**收走**（而不是把它画成 0）。
        let def = crate::beat::intern_def(ctx.state, definition_id.as_str());
        let ordinal = crate::beat::ordinal_of(ctx.state, target);
        crate::beat::record(
            ctx.state,
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

/// 删掉目标的第 `index` 条状态实例（`StatusEffects.cs:834` 的 `target.RemoveStatus(status)`）。
///
/// 落点就是 [`Combatant::remove_status`]：左移一格再 `pop()`，所以**剩下的实例保持相对顺序**、
/// 每一个哈希可见字段原样不动。留一条 0 层实例不是等价物 —— 它会出现在 `statuses()`（≥1 条）、
/// 快照/哈希的 `st=` 行、以及 `MAX_STATUSES_PER_COMBATANT` 的余量里。
///
/// 这里曾经是**整条 `Combatant` 重建**（复制出来、跳过 index 重建、再写回），因为那时
/// `state.rs` 没有删除 API。那个写法有个不会自己暴露的毛病：`Combatant` 每加一个字段，
/// 重建就多丢一个字段，而且丢得**无声无息**（哈希照样算得出来，只是少一行）。现在删除动作
/// 回到容器自己身上，"新增字段要不要搬到重建里"这个问题就不存在了。
///
/// 越界是**静默 no-op**：调用点（`modifyStatusStacks`）的下标来自
/// [`position_of_status`]，不可能越界；`remove_status` 返回的 `false` 在这里不被当作错误，
/// 因为参考的 `RemoveStatus` 找不到元素时也只是返回 `false`。
fn remove_status_at(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    index: usize,
) -> Result<(), ExecError> {
    let combatant = ctx
        .state
        .combatant_mut(target)
        .ok_or(ExecError::MissingCombatant)?;
    combatant.remove_status(index);
    Ok(())
}

/// `ForEachTarget`：解析集合 → **快照** → 逐个体绑 `iteration_target` → 派发 `Body`。
///
/// 参考（`EffectProgramNodeExecutors.cs:379-431`）：
/// * 先 `CollectionSelector.ResolveTargetsTraced(ctx, combat).ToArray()`（`:386-388`）——
///   **快照**，之后迭代期间集合变化不影响这一趟；
/// * `allTargets.Length > MaxIterations` ⇒ 抛（`:390-393`）⇒ [`ExecError::Modifier`]；
/// * 每轮 `PushIterationTarget`（`:419`）后 `dispatch(Body)`，**body 完成后在续延里**
///   `PopIterationTarget()` 并在节目链里接着跑下一趟（`:423-427`）。
///
/// ⚠️ **一处与参考的偏差（如实记录）**：集合为空时参考是**同步**调用 `onComplete`
/// （`ExecuteIteration` 的 `index >= len` 分支在 `Execute` 的栈上跑），本层排一条续延。
/// 差别只在"终态落在哪条链里"那一刻可见；本内容里 `forEachTarget` 没有空集合的局面，
/// 所以今天不可观察。**内容一来空集合它就会出现**，到那时要按 `:410` 的分支补同步完成。
fn dispatch_for_each_target(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    depth: u32,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let body = node.node_field("Body")?.ok_or(IrError::Missing("Body"))?;
    let collection = node
        .node_field("CollectionSelector")?
        .ok_or(IrError::Missing("CollectionSelector"))?;
    let max_iterations = node
        .int_field("MaxIterations")?
        .unwrap_or(DEFAULT_MAX_ITERATIONS);

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(collection, ctx, &mut targets)?;
    // `:390-393`：超出上限**抛**（不截断）。用 i32 比较逐字对应 `int.Length > int`：
    // 上限被写成 0/负数时**任何**目标数（含 0）都算超限，与参考一致。
    if i32::try_from(count).unwrap_or(i32::MAX) > max_iterations {
        return Err(ExecError::Modifier);
    }
    let mut list = Bounded::new();
    for target in targets.iter().take(count) {
        list.push(*target, Container::ProgramLoops)?;
    }
    let loop_at = ctx.state.program_loops_mut().alloc(ProgramLoop {
        list: ProgramLoopList::Targets(list),
        saved_target: ctx.iteration_target,
        saved_card: ctx.iteration_card,
        saved_flags: ctx.event_flags,
        body: body.id(),
        live: true,
    })?;
    if let Some(cell) = ctx.state.program_nodes_mut().get_mut(slot) {
        cell.kind = ProgramNodeKind::Loop;
        cell.remaining = 0;
        cell.loop_at = loop_at;
    }
    let _ = depth;
    if count == 0 {
        return resume_later(ctx.state, frame, slot);
    }
    start_iteration(ctx, Some(node), frame, slot, stats)
}

/// `Repeat`：把 `Body` 跑 `Count` 遍（§146，参考 `EffectProgramNodeExecutors.cs:282-330`）。
///
/// 参考逐条（我读过那 50 行）：
/// * `count = Count.Evaluate(...)`；
/// * `count < 0` ⇒ **抛**（"Card definitions must not produce negative repeat counts"）；
/// * `count > MaxCount` ⇒ **抛**（默认 `RepeatEffectNode.DefaultMaxCount = 32`）；
/// * `ExecuteIteration(body, count, 0, ...)`：`index >= count` ⇒ `onComplete`；
///   否则 `dispatch(body)`，body 完成后**在节目链里**接着下一趟；
/// * 每一趟 `ctx.OpenScope()` / `CloseScope()` —— 本内核没有作用域栈，这一层的作用域里
///   也没有绑任何东西（没有 `iterationIndex` 之外的变量），所以那对调用在这里**没有对应物**。
///   ⚠️ 这是一处如实记录的偏差：内容若在 `repeat` 体里读 `iterationIndex`，本内核读到的是
///   **外层**的值。今天没有这样的内容，且这条偏差在 `dispatch_repeat` 的测试里钉住。
fn dispatch_repeat(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let body = node.node_field("Body")?.ok_or(IrError::Missing("Body"))?;
    let count = eval_amount(node, "Count", ctx)?;
    let max_count = node.int_field("MaxCount")?.unwrap_or(REPEAT_DEFAULT_MAX_COUNT);
    // 两条都是**响亮失败**，一条都不截断：静默 `min(count, max)` 会让"打 40 下"变成
    // "打 32 下"，而屏幕上只会少几下 —— X 费牌里这种错最容易当成"算错了"。
    if count < 0 {
        return Err(ExecError::Modifier);
    }
    if count > max_count {
        return Err(ExecError::Modifier);
    }
    let count = u16::try_from(count).map_err(|_| ExecError::Modifier)?;
    let loop_at = ctx.state.program_loops_mut().alloc(ProgramLoop {
        list: ProgramLoopList::Count(count),
        // `repeat` 不改变迭代绑定 —— 存下来的就是外层那对，`complete` 恢复它等于什么都不做
        // （写法与另外两种循环一致，免得"这一类不需要恢复"成为一条要记住的例外）。
        saved_target: ctx.iteration_target,
        saved_card: ctx.iteration_card,
        saved_flags: ctx.event_flags,
        body: body.id(),
        live: true,
    })?;
    if let Some(cell) = ctx.state.program_nodes_mut().get_mut(slot) {
        cell.kind = ProgramNodeKind::Loop;
        cell.remaining = 0;
        cell.loop_at = loop_at;
    }
    if count == 0 {
        return resume_later(ctx.state, frame, slot);
    }
    start_iteration(ctx, Some(node), frame, slot, stats)
}

/// 起一趟循环迭代（`ExecuteIteration`，`:405-428` / `:475-505`）。
/// 绑值 → 派发 `Body`。**绑值同时写进帧**：下一趟是在续延里派的，那时只能从帧恢复。
/// `remaining` 记"下一趟的下标"（参考的 `nextIndex = index + 1`，`:421`/`:496`）。
fn start_iteration(
    ctx: &mut ExecContext<'_>,
    anchor: Option<NodeRef<'_>>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    // `:410` / `:486-487`：战斗一结束就放弃剩余的迭代（先把帧取消留给 `complete`）。
    if ctx.state.result != CombatResult::Ongoing {
        return Ok(());
    }
    let Some(record) = ctx.state.program_nodes().get(slot).copied() else {
        return Err(ExecError::Modifier);
    };
    let Some(loop_entry) = ctx.state.program_loops().get(record.loop_at).copied() else {
        return Err(ExecError::Modifier);
    };
    let index = usize::from(record.remaining);
    // 推之前先记下"外层"的绑定：Body 如果在**派发**期就报错（例如 `cardExpression`
    // 求值失败），参考那边是整个帧被丢弃、外层上下文原样保留
    // （`EffectProgramNodeExecutors.cs:484-485` 的 scope 关闭写在 continuation 里）——
    // 所以这一支要当场还原，不能把迭代卡留在帧上（`e2e_19h` 的 (b) 半钉着它）。
    let outer_target = ctx.iteration_target;
    let outer_card = ctx.iteration_card;
    // §225：迭代卡也要**填 `event_flags` 的卡牌 tag 位** —— 与 `CardPlayed` 触发器同一条口径。
    // 这样"消耗所有**非攻击**牌"（Second Wind）就能用 `not(event.bool: card.hasTag.attack)` 表达，
    // 而表达式层**不需要**去读内容（那会给 `ExprContext` 开一条它不该有的通道）。
    let outer_flags = ctx.event_flags;
    match loop_entry.list {
        ProgramLoopList::Targets(list) => {
            let Some(target) = list.get(index).copied() else {
                return Err(ExecError::Ir(IrError::List));
            };
            ctx.iteration_target = Some(target);
        }
        ProgramLoopList::Cards(list) => {
            let Some(card_slot) = list.get(index).copied() else {
                return Err(ExecError::Ir(IrError::List));
            };
            let Some(card) = ctx.state.card(card_slot) else {
                // 快照时还在的槽位在循环里消失 —— 只可能来自"池被重写"，是坏状态。
                return Err(ExecError::Ir(IrError::Slot));
            };
            ctx.iteration_card = Some(card.id);
            ctx.event_flags = match ctx.content {
                Some(content) => content.card_tag_bits(card.definition_id.as_str()),
                // 没有内容 ⇒ 不知道这张牌有什么 tag。**不许**当成"没有 tag"：那会让
                // "非攻击牌"把攻击牌也算进去。响亮失败。
                None => return Err(ExecError::Ir(IrError::Missing("content"))),
            };
            // §226：这一趟的牌**是不是正在结算的那一张**。用槽位比（同一份身份），不用定义 id
            // 比 —— 手牌里可能有两张同名牌，而只有其中一张在结算。
            if ctx.resolving_card == Some(card_slot) {
                ctx.event_flags |= CARD_IS_RESOLVING;
            }
        }
        // §146：`repeat` 没有可绑的东西 —— 迭代目标/卡保持外层原样（这正是"不要在 X 费牌里
        // 造假目标"的理由：`sel.iterationTarget` 必须还是外层那个）。
        ProgramLoopList::Count(_) => {}
        ProgramLoopList::None => return Err(ExecError::Modifier),
    }
    if let Some(cell) = ctx.state.program_frames_mut().get_mut(frame) {
        cell.iteration_target = ctx.iteration_target;
        cell.iteration_card = ctx.iteration_card;
    }
    let next = u16::try_from(index + 1).map_err(|_| ExecError::Ir(IrError::List))?;
    if let Some(cell) = ctx.state.program_nodes_mut().get_mut(slot) {
        cell.remaining = next;
    }
    let Some(anchor) = anchor else {
        // 没有内容锚点就重派不了循环体 —— **响亮失败**，不许"少跑一趟"。
        return Err(ExecError::Ir(IrError::Missing("program body")));
    };
    let outcome = dispatch_node(anchor.child(loop_entry.body), ctx, frame, slot, 1, stats);
    if outcome.is_err() {
        ctx.iteration_target = outer_target;
        ctx.iteration_card = outer_card;
        ctx.event_flags = outer_flags;
        if let Some(cell) = ctx.state.program_frames_mut().get_mut(frame) {
            cell.iteration_target = outer_target;
            cell.iteration_card = outer_card;
        }
    }
    outcome.map(|_| ())
}

/// `ForEachCardInZone`：把牌区**快照**下来 → 逐张绑 `iteration_card` → 派发 `Body`。
///
/// 参考（`EffectProgramNodeExecutors.cs:432-506`，逐行核对过）：
/// * `owner = OwnerSelector.ResolveTargetsTraced(ctx, combat).FirstOrDefault()`（`:439`）；
///   `owner == default || !CardZonesByCombatant.ContainsKey(owner)` ⇒ **整节点 no-op**，
///   而且它走的是 `EnqueueContinuation(onComplete)`（`:440-445`）——**不是同步完成**，
///   这一笔在 `shredder_drawer` 那类局面上是会改变 `chain_num` 的；
/// * 取该区的卡（`:449`）→ 可选的 `DefinitionFilter`（`:450-451`，本层拒绝非空）→
///   可选的 `TagFilter`（`:452-458`，**定义**上的 tag）→ 可选的 `MarkFilter`（`:460-461`，
///   **实例**上的 mark）→ `TakeFirst`（`:463-464`）→ `ToArray()`（`:465`）**快照**；
/// * `ids.Length > MaxIterations` ⇒ **抛**（`:467-470`）；
/// * 每轮 `PushIterationCard(cards[index])`（`:495`）后 `dispatch(Body)`，body 完成后
///   `PopIterationCard()` 再**在节目链里**跑下一趟（`:496-504`）。
fn dispatch_for_each_card_in_zone(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    depth: u32,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let body = node.node_field("Body")?.ok_or(IrError::Missing("Body"))?;
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    // `Zone` 是**裸字符串枚举名**（实测 `"Hand"`，flags=0），不认识的串 ⇒ 响亮失败。
    let zone_name = node.str_field("Zone")?.ok_or(IrError::Missing("Zone"))?;
    let zone = zone_from_wire_name(zone_name).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    let max_iterations = node
        .int_field("MaxIterations")?
        .unwrap_or(DEFAULT_CARD_IN_ZONE_MAX_ITERATIONS);
    // `TakeFirst` 缺席（`NULL_INT`）⇒ 全部匹配；`Some(n)` ⇒ `Enumerable.Take(n)`。
    // §248：`SkipResolving` —— **把正在结算的那张牌从快照里去掉**。
    //
    // 为什么不是内容侧的 `event.bool: card.isResolving`：那一格是"这次派发里有没有正在结算的牌"，
    // 对快照里的**每一张**都是同一个值 —— 用它做过滤会把整个循环跳过（实测正是如此）。
    // "哪一张是自己"只有内核知道（§226 的 `cardInstance.resolving` 是值，不是事实位）。
    let skip_resolving = node.bool_field("SkipResolving")?.unwrap_or(false);
    let resolving_id = ctx
        .resolving_card
        .and_then(|slot| ctx.state.card(slot))
        .map(|card| card.id);

    let take_first = node.int_field("TakeFirst")?;
    // §248：`Order: "Random"` —— 洗一遍快照再取。`Madness` 要"手里**随机一张**"，
    // 而 `TakeFirst` 只按牌堆序取（那会让"随机"变成"总是第一张"，而且看起来完全正常）。
    let random_order = match node.str_field("Order")? {
        None => false,
        Some("Random") => true,
        Some(_) => return Err(ExecError::Ir(IrError::UnknownKind)),
    };
    let tag_filter = node.str_field("TagFilter")?;
    // `MarkFilter` 在本镜像的 opcode 字段表里**根本不存在**，所以这里恒 `None`。
    // 仍然读它：将来内容真用了 mark 过滤，本层**会照参考执行**而不是静默忽略一条过滤条件。
    let mark_filter = node.str_field("MarkFilter")?;

    // ── `:439-445`：owner 解不出来 / 没有牌区 ⇒ 完成（no-op，走续延）。
    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let owner_count = resolve_targets(owner_selector, ctx, &mut owners)?;
    let Some(owner) = owners.first().copied().filter(|_| owner_count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };
    if ctx.state.card_zones(&owner).is_none() {
        return resume_later(ctx.state, frame, slot);
    }

    // ── `:447-465`：过滤 + `TakeFirst` + **快照**。
    //
    // 快照的是**池槽位**而不是 `CardInstanceId`：`state.rs` 里槽位就是卡的稳定身份
    // （`push_card` 只追加、`remove_card` 退休不回收、`move_card` **复用**同一槽位），
    // 所以"Body 把卡搬走不影响这一趟"与参考的 id 快照等价；而
    // `[CardInstanceId; 96]` 是 96 × 17 B，裸机上不该为了存一遍身份付这个账。
    let mut slots = [CardSlot::from_index(0); MAX_CARDS_PER_ZONE];
    let mut count = 0usize;
    {
        let Some(zones) = ctx.state.card_zones(&owner) else {
            return resume_later(ctx.state, frame, slot);
        };
        let in_zone = zones.count(zone);
        for index in 0..in_zone {
            // 牌区里的槽位表与卡池必须一致；不一致是**状态坏了**，不是"跳过几张"。
            let Some(card_slot) = zones.slot_at(zone, index) else {
                return Err(ExecError::Ir(IrError::Slot));
            };
            // ⚠️ §225 记一笔**没做**的改动：这里曾试着跳过"正在结算的那张牌"，被既有测试
            // 挡回来了 —— `play::tests` 与 `CARD_DIFF` 的 `archive_the_evidence` 都依赖
            // **打出的牌在节目期间仍在手牌**（参考实现就是这样：`onTerminal` 才落区）。
            // 所以"消耗整手牌"（Second Wind / Fiend Fire）在本内核里会**多算自己一次** ——
            // 那是与 StS 的语义差，不是抄错；要修得先让参考的那条路径变（哈希契约）。
            let Some(card) = ctx.state.card(card_slot) else {
                return Err(ExecError::Ir(IrError::Slot));
            };
            let definition_id = card.definition_id;
            let mut matches = true;
            if let Some(tag) = tag_filter {
                // 参考 `:452-458` 读的是**定义**上的 tag。没有内容镜像就没有那张表 ——
                // 响亮拒绝，见模块头（绝不静默成"一张都不匹配"）。
                let Some(content) = ctx.content else {
                    return Err(ExecError::Ir(IrError::Missing("content")));
                };
                matches = card_definition_has_tag(content, &definition_id, tag)?;
            }
            if matches {
                // `:460-461`：mark 在**实例**上（`c.Marks.Contains(mark)`），不在定义上。
                if let Some(mark) = mark_filter {
                    matches = card.marks().iter().any(|m| m.as_str() == mark);
                }
            }
            if !matches {
                continue;
            }
            let Some(sink) = slots.get_mut(count) else {
                // 不可达：`in_zone <= MAX_CARDS_PER_ZONE` 就是快照缓冲的长度。
                return Err(ExecError::Ir(IrError::List));
            };
            if skip_resolving && Some(ctx.state.card(card_slot).map(|c| c.id)) == Some(resolving_id) {
                continue;
            }
            *sink = card_slot;
            count += 1;
        }
    }

    // §248：`Order: "Random"` ⇒ 先把候选洗一遍（一次抽签，与洗牌同一本 `random_step` 账）。
    //
    // 注意 `shuffle_candidates` 是"算出下标重排"，不是"原地洗" —— 这里要给 `[CardSlot]`
    // 洗，所以直接用 `rng::shuffle_slots`（同一本账、同一个帮手，不是第二套洗牌）。
    if random_order {
        crate::rng::shuffle_slots(
            &mut slots[..count],
            ctx.state.random_seed,
            ctx.state.random_step,
        );
        ctx.state.random_step = ctx.state.random_step.saturating_add(1);
    }

    // ── `:463-464`：`Enumerable.Take(n)`。`n <= 0` ⇒ 空序列（**不是**截成 1，**不是**错误）。
    if let Some(take_first) = take_first {
        let take = if take_first <= 0 {
            0
        } else {
            usize::try_from(take_first).unwrap_or(usize::MAX)
        };
        if count > take {
            count = take;
        }
    }

    // ── `:467-470`：超出上限**抛**（不截断）。比的是 `TakeFirst` **之后**的张数。
    if i32::try_from(count).unwrap_or(i32::MAX) > max_iterations {
        return Err(ExecError::Modifier);
    }

    let mut list = Bounded::new();
    for card_slot in slots.iter().take(count) {
        list.push(*card_slot, Container::ProgramLoops)?;
    }
    let loop_at = ctx.state.program_loops_mut().alloc(ProgramLoop {
        list: ProgramLoopList::Cards(list),
        saved_target: ctx.iteration_target,
        saved_card: ctx.iteration_card,
        saved_flags: ctx.event_flags,
        body: body.id(),
        live: true,
    })?;
    if let Some(cell) = ctx.state.program_nodes_mut().get_mut(slot) {
        cell.kind = ProgramNodeKind::Loop;
        cell.remaining = 0;
        cell.loop_at = loop_at;
    }
    let _ = depth;
    if count == 0 {
        // ⚠️ 与参考的一处偏差（同 `dispatch_for_each_target` 的那条）：空快照时参考同步完成。
        return resume_later(ctx.state, frame, slot);
    }
    start_iteration(ctx, Some(node), frame, slot, stats)
}

/// `DrawCards`：`Count` → `TargetSelector` → **每个目标一条请求**（`:1404-1424`）。
///
/// `Count < 0` ⇒ 抛（`CardZoneEffects.cs:16-17`）⇒ [`ExecError::Modifier`]；
/// `Count == 0` ⇒ 空操作（`:19-24`）。抽牌与重洗的实体在 [`draw_for`]。
/// ⚠️ **手牌上限没有实现**（模块头偏差）：参考还会问
/// `CombatDecrees.Ceiling(registry, drawer, CombatRule.MaxHandSize)`，命中就夹 `wanted`。
fn draw_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    // 求值顺序照参考：`EvaluateCount` 在解析目标之前（`EffectProgramNodeExecutors.cs:1397-1399`）。
    let count = eval_amount(node, "Count", ctx)?;
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let resolved = resolve_targets(selector, ctx, &mut targets)?;
    // §231: `standard.no_draw` is enforced in `resolve_request`, **not here** -- a draw is a draw
    // whether it came from this node or from a potion's `EffectRequest::DrawCards`.
    for target in targets.iter().take(resolved) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::DrawCards {
                owner: *target,
                count,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// 给**一个**战斗员抽 `count` 张牌（[`draw_cards_node`] 的实体）。
///
/// 循环形状逐字照 `turn.rs` 的 `draw_for_turn_start`（那里已经对过参考 `:49-82`）：
/// 内层抽到抽不满为止，然后看弃牌堆 —— 两堆都空就**抽不满但不是错误**（`:59-60` 的 `break`）。
/// `reshuffles` 那个计数器是**结构性兜底**：本循环体内没有任何东西往弃牌堆放牌，
/// 所以正常路径上每次调用最多重洗一次；它保证将来有人往循环里加动作时这里不会变成死循环。
fn draw_for(
    ctx: &mut ExecContext<'_>,
    owner: &CombatantId,
    count: i32,
) -> Result<(), ExecError> {
    // `CardZoneEffects.cs:16-17` / `:19-24`。
    if count < 0 {
        return Err(ExecError::Modifier);
    }
    if count == 0 {
        return Ok(());
    }

    let mut drawn: i32 = 0;
    let mut reshuffles = 0usize;
    while drawn < count {
        while drawn < count {
            let Some(slot) = ctx.state.draw_card(owner)? else {
                break;
            };
            // §220：抽到了 ⇒ 跑它的 `Drawn` 节目（没有节目就什么都不做，链号也不动）。
            if let Some(content) = ctx.content {
                if let Some(card) = ctx.state.card(slot) {
                    let definition = card.definition_id;
                    crate::host::run_card_lifecycle(
                        ctx.state,
                        content,
                        *owner,
                        definition,
                        crate::state::CardLifecycleEvent::Drawn,
                    )?;
                }
            }
            // §237：`CardsDrawn` 事件就在**同一个落点**发 —— 抽牌有两个入口（这条与
            // `Host::card_drawn` 的回合开始那一路），两边都发才不漏。`Evolve` 的单位是"张"，
            // 所以一张一条。
            if let Some(card) = ctx.state.card(slot) {
                let event = crate::state::CombatEvent::CardsDrawn {
                    combatant: *owner,
                    card: card.id,
                };
                ctx.state.enqueue_event(event).map_err(ExecError::Capacity)?;
            }
            drawn += 1;
        }
        if drawn >= count {
            break;
        }
        // `:59-60`：弃牌堆也空 ⇒ 抽不满，**不是**错误。
        if zone_count(ctx.state, owner, CardZone::DiscardPile) == 0 {
            break;
        }
        if reshuffles >= 1 {
            break;
        }
        // `:62-69`：洗牌顺序 + `AdvanceRandomStep()` 都在这个函数里。
        if ctx.state.reshuffle_discard_into_draw(owner)? == 0 {
            break;
        }
        reshuffles += 1;
    }
    Ok(())
}

/// `GainResource`：`Amount` / `DefaultMax` → `TargetSelector` → **每个目标一条请求**。
///
/// 加池/夹上限/溢出判定在解析时跑（[`gain_one_resource`]，语义见那里）。
/// `Amount < 0` 或 `DefaultMax < 0` ⇒ 抛（`ResourceEffects.cs:138-142`）⇒ [`ExecError::Modifier`]。
/// `DefaultMax` 在镜像里是 `F_TERM`（**不是** `F_INT`），实测 1 条 term 全是 `null`。
fn gain_resource_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let resource_text = node
        .str_field("ResourceId")?
        .ok_or(IrError::Missing("ResourceId"))?;
    let resource_id = ResourceId::new(resource_text)?;
    let default_max = match node.node_field("DefaultMax")? {
        None => None,
        Some(term) => {
            let expr_ctx = ctx.expr_context();
            Some(expr::eval_int(term, &expr_ctx)?)
        }
    };
    // `:138-142`：两个负数都让整个 program fault。
    if amount < 0 || matches!(default_max, Some(max) if max < 0) {
        return Err(ExecError::Modifier);
    }
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::GainResource {
                target: Some(*target),
                key: resource_id,
                amount,
                default_max,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// 给**一个**战斗员加资源（[`gain_resource_node`] 的实体，语义见那里）。
fn gain_one_resource(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    key: ResourceId,
    amount: i32,
    default_max: Option<i32>,
) -> Result<(), ExecError> {
    // `:144-153`：零额什么都不做（**不建池**）。
    if amount == 0 {
        return Ok(());
    }
    let existing = resource_pool(
        ctx.state.combatant(target).ok_or(ExecError::MissingCombatant)?,
        &key,
    );
    let Some(pool) = existing else {
        // `:157-168`：建池。`current = min(amount, DefaultMax)`，`max = DefaultMax`。
        let created = match default_max {
            Some(max) if amount > max => max,
            _ => amount,
        };
        ctx.state
            .combatant_mut(target)
            .ok_or(ExecError::MissingCombatant)?
            .set_resource(key, created, default_max)?;
        return Ok(());
    };

    // `:212-234`：`long` 中间量 → 夹 `max` → 溢出即抛 → 增量 ≤ 0 则不写。
    let mut requested = i64::from(pool.current) + i64::from(amount);
    if let Some(max) = pool.max {
        if requested > i64::from(max) {
            requested = i64::from(max);
        }
    }
    if requested > i64::from(i32::MAX) {
        return Err(ExecError::Modifier);
    }
    let new_current = requested as i32;
    let gained = i64::from(new_current) - i64::from(pool.current);
    if gained <= 0 {
        return Ok(());
    }
    ctx.state
        .combatant_mut(target)
        .ok_or(ExecError::MissingCombatant)?
        .set_resource(key, new_current, pool.max)?;
    Ok(())
}

/// `LoseResource`：`Amount` → `TargetSelector` → **每个目标一条请求**。
///
/// 参考（`ResourceEffects.cs:277-335`）：`Amount < 0` ⇒ 抛（`:284-285`）；
/// 池不在身 ⇒ `previous = 0`（`:289-290`，**不建池**）；`newCurrent = max(0, previous - Amount)`
/// （`:292-293`），**丢多少为 0 就什么都不写**（`:296-306`）。
fn lose_resource_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let amount = eval_amount(node, "Amount", ctx)?;
    let resource_text = node
        .str_field("ResourceId")?
        .ok_or(IrError::Missing("ResourceId"))?;
    let resource_id = ResourceId::new(resource_text)?;
    // `:284-285`。
    if amount < 0 {
        return Err(ExecError::Modifier);
    }
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::LoseResource {
                target: Some(*target),
                key: resource_id,
                amount,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// [`lose_resource_node`] 的实体（语义见那里）。
fn lose_resource_for(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    key: ResourceId,
    amount: i32,
) -> Result<(), ExecError> {
    let existing = resource_pool(
        ctx.state.combatant(target).ok_or(ExecError::MissingCombatant)?,
        &key,
    );
    let previous = existing.map_or(0, |pool| pool.current);
    let new_current = if i64::from(previous) <= i64::from(amount) {
        0
    } else {
        previous - amount
    };
    let lost = i64::from(previous) - i64::from(new_current);
    if lost > 0 {
        let max = existing.and_then(|pool| pool.max);
        ctx.state
            .combatant_mut(target)
            .ok_or(ExecError::MissingCombatant)?
            .set_resource(key, new_current, max)?;
    }
    Ok(())
}

/// `CreateCardInstance`：`Count` → `TargetSelector` → **每个目标一条请求**（`:1480-1502`）。
///
/// `Count < 0` ⇒ 抛（`CardCreationEffects.cs:18-19`）；`Count == 0` ⇒ 什么都不造（`:21-26`）；
/// 每张卡一个**新的** `CardInstanceId`（`CombatState.cs:689-696`），造出来**追加**到 `ToZone`。
/// ⚠️ 参考在造之前先 `registry.GetCard(id)`（`:28`，未注册即抛）；本层没有卡定义注册表，
/// 见模块头偏差。`ToZone` 是**裸串**，不认识的串 ⇒ [`IrError::UnknownKind`]。
fn create_card_instance_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let definition_text = node
        .str_field("CardDefinitionId")?
        .ok_or(IrError::Missing("CardDefinitionId"))?;
    let definition_id = CardDefinitionId::new(definition_text)?;
    let zone_text = node.str_field("ToZone")?.ok_or(IrError::Missing("ToZone"))?;
    let zone = zone_from_wire_name(zone_text).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    // `Count` 缺席 ⇒ 1（`EffectProgramNativeNodes.cs:911` 的 `count ?? ConstantExpression(1)`）。
    let count = match node.node_field("Count")? {
        None => DEFAULT_CARD_INSTANCE_COUNT,
        Some(term) => {
            let expr_ctx = ctx.expr_context();
            expr::eval_int(term, &expr_ctx)?
        }
    };
    // `:18-19`。
    if count < 0 {
        return Err(ExecError::Modifier);
    }
    // §255：可选的"造出来时写一个每副本计数器"（`Conjure Blade` 的 X 就是它花的能量）。
    // `MarkCounterId` 缺席 ⇒ `None` ⇒ 与以前逐字相同。
    let mark = match node.str_field("MarkCounterId")? {
        None => None,
        Some(key) => {
            let key = crate::state::CounterId::new(key)?;
            let value = match node.node_field("MarkValue")? {
                None => 0,
                Some(term) => {
                    let expr_ctx = ctx.expr_context();
                    expr::eval_int(term, &expr_ctx)?
                }
            };
            Some((key, value))
        }
    };
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;

    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let resolved = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(resolved) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::CreateCardInstance {
                owner: *target,
                definition: definition_id,
                count,
                to_zone: zone,
                mark,
            },
            Some(frame),
        )?;
        // 口径与其它产出型节点一致：**每张卡**记 1 次（一张卡一次写入，见 `ExecStats::effects`）。
        stats.effects = stats.effects.saturating_add(
            u32::try_from(count).unwrap_or(0),
        );
    }
    resume_later(ctx.state, frame, slot)
}

/// [`create_card_instance_node`] 的实体（语义见那里）。
fn create_card_for(
    ctx: &mut ExecContext<'_>,
    owner: &CombatantId,
    definition: CardDefinitionId,
    count: i32,
    zone: CardZone,
    mark: Option<(crate::state::CounterId, i32)>,
) -> Result<(), ExecError> {
    if count < 0 {
        return Err(ExecError::Modifier);
    }
    for _ in 0..count {
        // §161.5: 铸号搬到了 `state::CombatState::create_card_instance`（`Offered` 也要用它）。
        // 这里是**第二个调用方**，不是第二份实现 —— 两条铸号路径会给出两个"下一个是几"。
        let created = ctx.state.create_card_instance(owner, definition, zone)?;
        // §255：造出来那一步就写每副本计数器（`Conjure Blade` 的 X）—— 分成两步会留下
        // "造好了但 X 是 0"的中间态，而那与"造出打 0 次的 Expunger"不可区分。
        if let Some((key, value)) = mark {
            let card = ctx
                .state
                .card_mut(created)
                .ok_or(ExecError::MissingCombatant)?;
            card.set_mark_counter(key, value).map_err(ExecError::Capacity)?;
        }
    }
    Ok(())
}

/// §243：`node.shuffleDiscardIntoDraw` —— `{OwnerSelector}`，一条请求。
///
/// 只入队不直接洗：`sequence[shuffle, draw]` 靠**队列顺序**表达"先洗后抽"，
/// 在派发时就把牌洗了会让同一棵树里的抽牌请求读到一个"已经洗过"的牌堆 ——
/// 那在单测里看起来一样，但在"抽到刚洗回去的那张"这种局面里是另一个结果。
fn shuffle_discard_into_draw_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut owners)?;
    for owner in owners.iter().take(count) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::ShuffleDiscardIntoDraw { owner: *owner },
            Some(frame),
        )?;
    }
    resume_later(ctx.state, frame, slot)
}

/// §241：`node.playTopCardOfDrawPile` —— 零字段，一条请求。
///
/// 求值只到"入队"为止：**抽牌堆顶是哪张**在排空那一刻才读（派发时读会让同一张牌被打两次）。
fn play_top_card_of_draw_pile_node(
    _node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let owner = ctx.source.ok_or(ExecError::MissingCombatant)?;
    ctx.state
        .enqueue_effect_with_owner(EffectRequest::PlayTopCardOfDrawPile { owner }, Some(frame))?;
    resume_later(ctx.state, frame, slot)
}

/// §240：`node.createRandomCardInstance` —— `{Tag, ToZone, Count, CostZero}`。
///
/// 只求值 + 入队（与其它产出型节点同一条口径）；**抽签在排空那一刻**发生，所以一局里两次
/// `Infernal Blade` 拿到的牌由 `random_step` 的顺序决定，与洗牌/随机目标同一本账。
fn create_random_card_instance_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let tag_text = node.str_field("Tag")?.ok_or(IrError::Missing("Tag"))?;
    let tag = crate::state::TagId::new(tag_text)?;
    let zone_text = node.str_field("ToZone")?.ok_or(IrError::Missing("ToZone"))?;
    let zone = zone_from_wire_name(zone_text).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    let count = match node.node_field("Count")? {
        None => DEFAULT_CARD_INSTANCE_COUNT,
        Some(term) => {
            let expr_ctx = ctx.expr_context();
            expr::eval_int(term, &expr_ctx)?
        }
    };
    if count < 0 {
        return Err(ExecError::Modifier);
    }
    let cost_zero = node.bool_field("CostZero")?.unwrap_or(false);
    let owner = ctx.source.ok_or(ExecError::MissingCombatant)?;
    ctx.state.enqueue_effect_with_owner(
        EffectRequest::CreateRandomCard {
            owner,
            tag,
            count,
            to_zone: zone,
            cost_zero,
        },
        Some(frame),
    )?;
    resume_later(ctx.state, frame, slot)
}

/// §241：`PlayTopCardOfDrawPile` 的实体 —— `Havoc`。
///
/// 四步，每一步都有一个"为什么不能省"：
/// 1. **移到手牌**：`plan_play` 的受理校验要求实例在**手牌**里（`CardNotInHand`）。这不是绕过校验，
///    而是 StS 的等价物 —— 它那时在 in-play 区，反正不在牌堆里；
/// 2. **绝对价格 = 0**：`Havoc` 不付这张牌的费。复用 §240 那一格（`standard.card_cost_override`），
///    不给 `PlayRequest` 再加一个 `free` 布尔；
/// 3. **目标**：攻击牌需要目标 ⇒ 随机一个活着的敌人（StS 的 Havoc 就是随机挑）。用 `random_step`
///    抽签，与随机目标/洗牌同一本账；
/// 4. **落区 `ExhaustPile`**：`PlayRequest::to_zone` 强制 —— `Havoc` 的文字是 "and Exhaust it"，
///    而同一张 `Strike` 平时进弃牌堆。
///
/// 被拒（例如抽到一张 `unplayable` 的牌）⇒ **放回抽牌堆顶**、什么都不发生。这是最保守的一条：
/// 既不假装"打出去了"（那会少一张牌），也不报错（那是一张合法牌让整场战斗炸掉）。
fn play_top_card_for(
    ctx: &mut ExecContext<'_>,
    owner: &CombatantId,
) -> Result<(), ExecError> {
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };
    let Some(slot) = ctx
        .state
        .card_zones(owner)
        .and_then(|zones| zones.slot_at(CardZone::DrawPile, 0))
    else {
        return Ok(()); // 抽牌堆空 ⇒ 什么都不做（不是错误）
    };
    let Some(card) = ctx.state.card(slot) else {
        return Ok(());
    };
    let instance = card.id;
    let definition = card.definition_id;
    // 1. 抽牌堆顶 → 手牌。
    ctx.state
        .move_card(owner, CardZone::DrawPile, CardZone::Hand, slot, ZonePlacement::Bottom)?;
    // 2. 这一份的价格就是 0。
    let price = crate::state::CounterId::new(crate::state::CARD_COST_OVERRIDE_COUNTER)?;
    if let Some(card) = ctx.state.card_mut(slot) {
        card.set_mark_counter(price, 0).map_err(ExecError::Capacity)?;
    }
    // 3. 攻击牌 ⇒ 随机一个活着的敌人。
    let target = if content.card_has_tag(definition.as_str(), "attack") == Some(true) {
        random_living_opponent(ctx, owner)
    } else {
        None
    };
    // 4. 打出去（落区强制消耗堆）。
    let request = crate::play::PlayRequest::to_zone(*owner, instance, target, CardZone::ExhaustPile);
    match crate::play::play_card(ctx.state, Some(content), &request) {
        Ok(_) => Ok(()),
        Err(_) => {
            // 被拒 ⇒ 放回抽牌堆顶，并把价格标记撤掉（否则它下次被抽到就莫名 0 费）。
            if let Some(card) = ctx.state.card_mut(slot) {
                if let Ok(key) = crate::state::CounterId::new(
                    crate::state::CARD_COST_OVERRIDE_COUNTER,
                ) {
                    card.remove_mark_counter(key);
                }
            }
            let Some((_, slot)) = ctx.state.find_card(owner, &instance) else {
                return Ok(());
            };
            ctx.state.move_card(
                owner,
                CardZone::Hand,
                CardZone::DrawPile,
                slot,
                ZonePlacement::Top,
            )?;
            Ok(())
        }
    }
}

/// §241：随机一个**活着的对手**（`None` = 场上没有）。
fn random_living_opponent(ctx: &mut ExecContext<'_>, owner: &CombatantId) -> Option<CombatantId> {
    let mut pool = [CombatantId::EMPTY; MAX_COMBATANTS];
    let mut count = 0usize;
    for combatant in ctx.state.combatants() {
        if combatant.id == *owner {
            continue;
        }
        if combatant.health_current <= 0 {
            continue;
        }
        if let Some(cell) = pool.get_mut(count) {
            *cell = combatant.id;
            count += 1;
        }
    }
    if count == 0 {
        return None;
    }
    let picked =
        crate::rng::shuffled_pick_index(count, ctx.state.random_seed, ctx.state.random_step);
    ctx.state.random_step = ctx.state.random_step.saturating_add(1);
    pool.get(picked).copied()
}

/// §240：`CreateRandomCard` 的实体 —— 按 tag 从卡表里抽一个定义，造实例，必要时把费用压到 0。
///
/// 池子（**有原因的排除**，见 `port_state` 那条 §240 注）：
/// * 只收带该 tag 的；
/// * 不收 `+` 行（升级行是同一张牌的另一个定义，StS 的随机池是基础牌）；
/// * 不收 **X 费牌**（本内核的每副本价格对 X 费牌看不见 ⇒ 造出来会"说 0 费、实际仍是全部能量"）。
fn create_random_card_for(
    ctx: &mut ExecContext<'_>,
    owner: &CombatantId,
    tag: &crate::state::TagId,
    count: i32,
    zone: CardZone,
    cost_zero: bool,
) -> Result<(), ExecError> {
    if count < 0 {
        return Err(ExecError::Modifier);
    }
    if count == 0 {
        return Ok(());
    }
    let Some(content) = ctx.content else {
        return Err(ExecError::Ir(IrError::Missing("content")));
    };
    for _ in 0..count {
        let definition = pick_random_card_of_tag(ctx, content, tag)?;
        let Some(definition) = definition else {
            // 池子空 ⇒ 什么都不做（内容没给这个 tag 任何基础牌，这是内容的事，不是运行时错误）。
            return Ok(());
        };
        let slot = ctx
            .state
            .create_card_instance(owner, definition, zone)
            .map_err(ExecError::Capacity)?;
        if cost_zero {
            // §161.4：**绝对**每副本价格（`standard.card_cost_override`）—— 它在 delta 之前生效，
            // 正是"这一份的价格就是 0"要的那一格。出牌付款后计数器被清掉（同一条承诺）。
            let key = crate::state::CounterId::new(crate::state::CARD_COST_OVERRIDE_COUNTER)?;
            let card = ctx
                .state
                .card_mut(slot)
                .ok_or(ExecError::MissingCombatant)?;
            card.set_mark_counter(key, 0).map_err(ExecError::Capacity)?;
        }
    }
    Ok(())
}

/// 按 tag 抽一张（同一次调用里 `random_step` 前进一格）。
///
/// 扫两遍：第一遍数池子有多大，第二遍取第 `picked` 个 —— 这样不需要把候选表存下来
/// （定容缓冲 + 卡表行数会撞上限，而"数一遍再取"只用两个计数器）。
fn pick_random_card_of_tag(
    ctx: &mut ExecContext<'_>,
    content: &crate::content::Content<'_>,
    tag: &crate::state::TagId,
) -> Result<Option<CardDefinitionId>, ExecError> {
    let mut total = 0usize;
    for row in content.rows(crate::content::Table::Card) {
        let index = row.index();
        let Some(definition) = content.entity_id(crate::content::Table::Card, index) else {
            continue;
        };
        if !in_random_pool(content, definition, tag) {
            continue;
        }
        total += 1;
    }
    if total == 0 {
        return Ok(None);
    }
    let picked = crate::rng::shuffled_pick_index(
        total,
        ctx.state.random_seed,
        ctx.state.random_step,
    );
    ctx.state.random_step = ctx.state.random_step.saturating_add(1);
    let mut seen = 0usize;
    for row in content.rows(crate::content::Table::Card) {
        let index = row.index();
        let Some(definition) = content.entity_id(crate::content::Table::Card, index) else {
            continue;
        };
        if !in_random_pool(content, definition, tag) {
            continue;
        }
        if seen == picked {
            return Ok(Some(CardDefinitionId::new(definition)?));
        }
        seen += 1;
    }
    Ok(None)
}

/// §240：这张定义进不进"随机造牌"的池子。
fn in_random_pool(
    content: &crate::content::Content<'_>,
    definition: &str,
    tag: &crate::state::TagId,
) -> bool {
    // `+` 行是同一张牌的另一个定义（随机池只收基础牌）。
    if definition.contains('+') {
        return false;
    }
    if content.card_has_tag(definition, tag.as_str()) != Some(true) {
        return false;
    }
    // X 费牌没有"印刷费用"这个数（`printed_energy_cost` 返回 `None`），排除。
    content.card_has_tag(definition, crate::battle::X_COST_TAG) != Some(true)
}

/// `MoveCardToZone`：求卡实例表达式 → 解析 owner → **一条请求**（`:1936-1941`）。
///
/// 参考（`EffectProgramNodeExecutors.cs:1905-1958` + handler `CardZoneEffects.cs:165-213`）：
/// * 先 `EvaluateCardInstanceId(ctx, combat)`（`:1911`）；**卡 id 求不出来 ⇒ 整节点 no-op**
///   （`:1913-1920`）。本层 [`crate::expr::eval_card`] 在"没有绑定迭代卡"时报
///   [`ExprError::NoTarget`] —— **响亮失败，不返回空 id**（expr.rs 的冻结决定）。
/// * `OwnerSelector...FirstOrDefault()`（`:1922-1923`）；解不出 owner ⇒ **no-op 不是错误**
///   （`:1925-1932`）—— 那时**一条请求都不入队**。
/// * handler 里：卡不在这个战斗员的牌区 ⇒ 抛；同区 ⇒ 只有 `Top` 才重排。
///
/// `ToZone` / `Placement` 都是**裸字符串枚举名**，不认识的串 ⇒ [`IrError::UnknownKind`]。
/// §195.7：把 `OwnerSelector` 的牌堆里所有 `CardDefinitionId` 的实例升级成 `<id>+`。
///
/// **直接写**，不入队：一张牌的定义不是任何触发器看得见的东西（本内核的卡事件只有
/// `CardMovedToZone` / `CardInstanceCreated`），参考的升级路径也是直接改。
///
/// 没有 `+` 行的定义（例如 `dazed`）**平静跳过**：那是 StS 的 `canUpgrade() == false`，不是内容错。
fn upgrade_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    // §227: absent = "every definition in the zone" (Armaments+ upgrades the **whole hand**, and
    // the content cannot name the definitions because it does not know what the player holds).
    let definition = node.str_field("CardDefinitionId")?;
    let only_zone = match node.str_field("FromZone")? {
        Some(name) => Some(zone_from_wire_name(name).ok_or(ExecError::Ir(IrError::UnknownKind))?),
        None => None,
    };
    let limit = match node.int_field("Count")? {
        Some(count) if count >= 0 => count as usize,
        Some(_) => return Err(ExecError::Ir(IrError::Missing("Count"))),
        None => usize::MAX,
    };

    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let owner_count = resolve_targets(owner_selector, ctx, &mut owners)?;
    let Some(owner) = owners.first().copied().filter(|_| owner_count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };

    let Some(content) = ctx.content else {
        return resume_later(ctx.state, frame, slot);
    };
    let wanted = match definition {
        Some(text) => Some(crate::state::CardDefinitionId::new(text)?),
        None => None,
    };

    let mut changed = 0usize;
    // `CardZone::ALL` 一格一个牌区（7 个）；只点名一个区时只走那一个槽。
    let zones: [crate::state::CardZone; crate::state::CARD_ZONE_COUNT] = match only_zone {
        Some(zone) => [zone; crate::state::CARD_ZONE_COUNT],
        None => crate::state::CardZone::ALL,
    };
    let zone_count = if only_zone.is_some() { 1 } else { zones.len() };
    for zone in zones.iter().take(zone_count).copied() {
        if changed >= limit {
            break;
        }
        let mut slots = [0u16; crate::state::MAX_CARDS_PER_ZONE];
        let count = match ctx.state.card_zones(&owner) {
            Some(data) => {
                let listed = data.slots(zone);
                let count = listed.len().min(slots.len());
                slots[..count].copy_from_slice(&listed[..count]);
                count
            }
            None => break,
        };
        for raw in slots.iter().take(count).copied() {
            if changed >= limit {
                break;
            }
            let slot_ref = crate::state::CardSlot::from_index(raw);
            let Some(card) = ctx.state.card(slot_ref) else {
                continue;
            };
            if let Some(wanted) = wanted {
                if card.definition_id != wanted {
                    continue;
                }
            }
            // §227: **one** answer to "can this be upgraded" -- the same helper the player-facing
            // `chooseCards{Then: Upgrade}` uses to narrow its options.
            let Some(upgraded) = upgradable_definition(content, card.definition_id.as_str()) else {
                continue;
            };
            if let Some(card) = ctx.state.card_mut(slot_ref) {
                card.definition_id = upgraded;
                changed += 1;
                stats.effects = stats.effects.saturating_add(1);
            }
        }
    }
    resume_later(ctx.state, frame, slot)
}

/// §227：这张定义**升级版的样子**，只在内容真的有一行 `+` 时给出。
///
/// 两条路必须给出同一个答案：`upgrade_cards_node`（批量/整片牌区）与 `chooseCards` 的
/// `Upgrade`（玩家选中的那一张）。所以判定只写这一遍，拼法只写 `state::upgraded_id` 那一遍。
fn upgradable_definition(
    content: &crate::content::Content<'_>,
    definition: &str,
) -> Option<crate::state::CardDefinitionId> {
    let upgraded = crate::state::upgraded_id(definition)?;
    if content
        .lookup_in(upgraded.as_str(), crate::content::EK_CARD)
        .is_none()
    {
        return None;
    }
    Some(upgraded)
}

/// §195.4：**挑** `FromZone`（空则 `FallbackZone`）里按 `Order` 排好的前 `Count` 张，搬去 `ToZone`。
///
/// §195.5 补了可选的 `RequireTag`（只看带这个 tag 的卡）。
///
/// 搬卡走 `EffectRequest::MoveCardToZone`（与 `node.moveCardToZone` 同一个请求），所以触发器照样
/// 看得见、`ExecStats::effects` 的"一次请求一次效果"照样成立。
fn select_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    let from_name = node.str_field("FromZone")?.ok_or(IrError::Missing("FromZone"))?;
    let from_zone = zone_from_wire_name(from_name).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    let fallback = match node.str_field("FallbackZone")? {
        Some(name) => Some(zone_from_wire_name(name).ok_or(ExecError::Ir(IrError::UnknownKind))?),
        None => None,
    };
    let order_name = node.str_field("Order")?.ok_or(IrError::Missing("Order"))?;
    // §195.5：可选的 `RequireTag` —— "只看带这个 tag 的卡"（例如只偷 attack、只偷 curse）。
    // 缺席 = 不过滤；空串也当"不过滤"（`card_has_tag("", ..)` 恒 false，显式挡掉，免得空串
    // 悄悄变成"一张都挑不到"）。过滤发生在**排序之前**，否则 `Count` 会数到被滤掉的卡。
    let require_tag = node.str_field("RequireTag")?.filter(|tag| !tag.is_empty());
    let count = node.int_field("Count")?.ok_or(IrError::Missing("Count"))?;
    if !(1..=MAX_SELECTED_CARDS as i32).contains(&count) {
        return Err(ExecError::Ir(IrError::Missing("Count")));
    }
    let count = count as usize;
    let to_name = node.str_field("ToZone")?.ok_or(IrError::Missing("ToZone"))?;
    let to_zone = zone_from_wire_name(to_name).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    let placement = match node.str_field("Placement")? {
        None => ZonePlacement::Bottom,
        Some(name) => placement_from_wire_name(name).ok_or(ExecError::Ir(IrError::UnknownKind))?,
    };

    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let owner_count = resolve_targets(owner_selector, ctx, &mut owners)?;
    // 与 `moveCardToZone` 同一条：解不出 owner ⇒ no-op（没有卡可搬，也不是错误）。
    let Some(owner) = owners.first().copied().filter(|_| owner_count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };

    // Candidates: `(card instance id, rarity rank)` in **pile order**.
    //
    // §195.9: the buffer is the **zone capacity**, not an arbitrary 64. A pile can hold
    // `MAX_CARDS_PER_ZONE` (96) cards, and the old `MAX_SELECTED_CARDS * 8` = 64 silently dropped the
    // last 32 -- so "steal the best card" would miss a Rare sitting at the bottom of a big deck.
    let mut candidates = [CardInstanceId::EMPTY; MAX_CARD_CANDIDATES];
    let mut ranks = [0u8; MAX_CARD_CANDIDATES];
    let mut found = 0usize;
    for zone in core::iter::once(from_zone).chain(fallback.into_iter()) {
        for card in ctx.state.zone_cards(&owner, zone) {
            // Loud, not silent: overflow here can only mean "the pile grew past its container",
            // and truncating would silently change *which* card is picked.
            if found == candidates.len() {
                return Err(ExecError::Capacity(crate::state::CapacityError::Full(
                    crate::state::Container::CardInstances,
                )));
            }
            if let (Some(tag), Some(content)) = (require_tag, ctx.content) {
                if !content.card_has_tag(card.definition_id.as_str(), tag).unwrap_or(false) {
                    continue;
                }
            }
            candidates[found] = card.id;
            ranks[found] = card_rarity_rank(ctx.content, &card.definition_id);
            found += 1;
        }
        if found > 0 {
            // `FallbackZone` is a fallback, not a second batch: stop at the first pile that has a card.
            break;
        }
    }
    if found == 0 {
        // 没有卡可挑 ⇒ 空操作（不是错误）：一张空牌堆不是内容缺陷，它是战斗里最正常的一件事。
        return resume_later(ctx.state, frame, slot);
    }

    // `order[..found]` holds the candidate indices; nothing past `found` is ever read.
    // §195.9: the old code took `count` entries from here, so `Count: 4` with one candidate walked
    // three zeros and enqueued the **same** card four times (`stats.effects` counted it too).
    let mut order = [0usize; MAX_CARD_CANDIDATES];
    for index in 0..found {
        order[index] = index;
    }
    match order_name {
        "HighestRarity" => {
            // Ties are meant to be **random** (wiki: Stasis steals "a random card of the highest
            // rarity"), so shuffle first -- one draw for the batch -- then sort by rank with a
            // **stable** sort, which keeps the shuffled order inside a tie.
            shuffle_candidates(&mut order[..found], ctx);
            let ranks_slice = &ranks[..found];
            for index in 1..found {
                let mut cursor = index;
                while cursor > 0 && ranks_slice[order[cursor - 1]] < ranks_slice[order[cursor]] {
                    order.swap(cursor - 1, cursor);
                    cursor -= 1;
                }
            }
        }
        "First" => {}
        "Random" => shuffle_candidates(&mut order[..found], ctx),
        _ => return Err(ExecError::Ir(IrError::UnknownKind)),
    }

    // Never ask for more cards than exist.
    let take = count.min(found);
    for index in order.iter().take(take) {
        ctx.state.enqueue_effect_with_owner(
            EffectRequest::MoveCardToZone {
                owner,
                card: candidates[*index],
                to_zone,
                placement,
            },
            Some(frame),
        )?;
        stats.effects = stats.effects.saturating_add(1);
    }
    resume_later(ctx.state, frame, slot)
}

/// §226：`node.chooseCards` 的实体 —— **问玩家要哪几张牌，然后复制**。
///
/// 字段：`{OwnerSelector, FromZone, Min, Max, Copies, RequireAnyTag?}`。
///
/// 与 `selectCards` 的两条分工（别合并这两个节点）：
/// * 那个**内核挑**（`Order`: `First`/`Random`/`HighestRarity`）并且**搬**牌；
/// * 这个**问玩家**（`PendingChoice`，`then = Copy`）并且**造**牌 —— 原件留在原处。
///
/// `RequireAnyTag` 是**一个 tag 的集合**（"Attack 或 Power"）：过滤要读卡定义的 tag 表，而它
/// 只在内容镜像里，所以在这里算好、把**收窄后的实例清单**塞进问句（`PendingChoice::candidates`）
/// —— 状态层没有 `Content`，这样它也不必去读内容就能守住"哪些选项合法"。
///
/// 三条"不问"的情形都是**空操作**，不是错误（一个答不出来的问句会把这局钉死）：
/// 解不出 owner、没有候选、候选比 `Min` 还少。
///
/// ⚠️ `begin_choice` 的失败借 [`ExecError::Modifier`] 桶（冻结的 `ExecError` 没有"选牌"变体，
/// 理由同 `forEachCardInZone` 的 `MaxIterations`）。可达的只有"已经有一个待决问句"
/// （`AlreadyPending`）—— 那是**嵌套提问**，本内核明确不支持。
fn choose_cards_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;
    let from_name = node.str_field("FromZone")?.ok_or(IrError::Missing("FromZone"))?;
    let from_zone = zone_from_wire_name(from_name).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    // 今天只有手牌来源的问句（Dual Wield）。别的牌区需要一个"从那儿选牌"的 UI 语义，
    // 而那件事没被任何内容要求过 —— 响亮拒绝，不许悄悄当成手牌。
    let source = match from_zone {
        CardZone::Hand => crate::state::ChoiceSource::Hand,
        CardZone::DiscardPile => crate::state::ChoiceSource::DiscardPile,
        // §238：`Exhume`（"把消耗堆里一张拿回手牌"）—— 问句的来源牌区就是消耗堆，
        // 页面按 zone id 3 读它（§161.5 的契约），所以那边不用改。
        CardZone::ExhaustPile => crate::state::ChoiceSource::ExhaustPile,
        // §244：Secret Technique / Secret Weapon —— 从抽牌堆里挑一张。
        CardZone::DrawPile => crate::state::ChoiceSource::DrawPile,
        _ => return Err(ExecError::Ir(IrError::UnknownKind)),
    };
    let min = node.int_field("Min")?.ok_or(IrError::Missing("Min"))?;
    let max = node.int_field("Max")?.ok_or(IrError::Missing("Max"))?;
    // §227：`Then` 决定"选完做什么"，所以它先被解析，再决定**哪些字段是必须的** ——
    // "Copies 只在 Copy 上有意义"这条规则写在解析里，比写在注释里靠得住。
    let then_name = node.str_field("Then")?.ok_or(IrError::Missing("Then"))?;
    let then = match then_name {
        "Copy" => {
            let copies = node.int_field("Copies")?.ok_or(IrError::Missing("Copies"))?;
            if !(1..=MAX_COPIES_PER_CHOICE as i32).contains(&copies) {
                return Err(ExecError::Ir(IrError::Missing("Copies")));
            }
            // `ToZone` 缺席 ⇒ 手牌（Dual Wield 的语义）。副本进手牌是**最常见**的那一种，
            // 但 Nightmare 要的是"先放进一边、下一回合再拿进手牌"，所以这个字段必须存在。
            let into = match node.str_field("ToZone")? {
                Some(name) => zone_from_wire_name(name).ok_or(ExecError::Ir(IrError::UnknownKind))?,
                None => CardZone::Hand,
            };
            crate::state::ChoiceThen::Copy {
                copies: u8::try_from(copies).map_err(|_| ExecError::Ir(IrError::Missing("Copies")))?,
                into,
            }
        }
        // §227：Armaments —— 选一张原地升级。候选会被下面收窄到"有 `+` 行"的牌。
        "Upgrade" => crate::state::ChoiceThen::Upgrade,
        // §227：Warcry —— 选一张放到抽牌堆顶。
        "ToDrawPileTop" => crate::state::ChoiceThen::ToDrawPileTop,
        // §250: `Forethought` -- bottom of the draw pile, and free until played.
        "ToDrawPileBottomFree" => crate::state::ChoiceThen::ToDrawPileBottomFree,
        // §250: `Discovery` 那条问句由 `offerRandomCards` 自己造（`then` 写死），但字符串
        // 映射也登记上，免得将来有第二张牌想用同一条语义时只能在节点里再写一遍。
        "ToHandFree" => crate::state::ChoiceThen::ToHandFree,
        // §231：True Grit+ —— "选一张消耗掉"。内核的 `ChoiceThen::Exhaust` 一直存在（Elixir 那条药水
        // 就在用），只是内容没有入口说"我要这个 then"。
        "Exhaust" => crate::state::ChoiceThen::Exhaust,
        // §238：Exhume —— "把选中的那张**拿进手牌**"。`ChoiceThen::ToHand` 一直存在
        // （Liquid Memories 那条药水在用），这次是内容第一次点名它。
        "ToHand" => crate::state::ChoiceThen::ToHand,
        _ => return Err(ExecError::Ir(IrError::UnknownKind)),
    };
    if !(0..=MAX_SELECTED_CARDS as i32).contains(&min)
        || !(1..=MAX_SELECTED_CARDS as i32).contains(&max)
        || min > max
    {
        return Err(ExecError::Ir(IrError::Missing("Min")));
    }
    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let owner_count = resolve_targets(owner_selector, ctx, &mut owners)?;
    let Some(owner) = owners.first().copied().filter(|_| owner_count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };

    // §246：`DrawFirst: N` —— **先抽 N 张（同步），再快照候选**。`Warcry` / `Thinking Ahead`
    // 的原文都是"Draw N cards. Put a card from your hand on top…"，抽到的牌**必须**是候选。
    //
    // 为什么这里的抽牌是**同步**的（与 `node.drawCards` 的"只入队"不同）：整棵树是**先派发完**
    // 再让请求落地的（§238.1），所以 `sequence[drawCards, chooseCards]` 里的候选快照发生在
    // 抽牌落地**之前** —— 抽到的那张永远不在候选里，手牌本来就空时甚至连问句都不出现。
    // 把抽牌放进**问句节点内部**是唯一不动全局时序的修法（"节点之间排空队列"会动每一步的
    // 哈希与 beat 计数，四条对拍当场红）。
    let draw_first = node.int_field("DrawFirst")?.unwrap_or(0);
    if draw_first < 0 {
        return Err(ExecError::Modifier);
    }
    if draw_first > 0 {
        draw_for(ctx, &owner, draw_first)?;
    }

    // `RequireAnyTag` 缺席 ⇒ 不过滤。空数组也当"不过滤"（与 `selectCards` 的 `RequireTag`
    // 对空串的处理同一条理由：一个空集合当过滤条件，等于"一张都挑不到"）。
    let mut tag_cells = [0u16; MAX_SELECTED_CARDS];
    let tag_count = node.str_list_field("RequireAnyTag", &mut tag_cells)?;

    // §236：**正在结算的那张牌不算"手牌里的牌"**（与 §226 同一条洞见，这里是它的后果版）。
    //
    // 不加这一步会造出一个**零选项的死锁**：`Warcry` 的程序是"抽 1 张，然后问玩家把手里一张放回
    // 堆顶"。抽牌堆空时手牌只有它自己 ⇒ 候选 = 它 ⇒ 问句成立；但出牌一结束它就离开手牌，
    // 于是 `choice_legal` 过滤候选后变成 0 个 ⇒ 页面画出一个"确认键永久禁用"的弹窗（soak 抓到）。
    // 语义上也该排除：StS 里打出的牌当时在 in-play 区，不在手里。
    let resolving = ctx
        .resolving_card
        .and_then(|slot| ctx.state.card(slot))
        .map(|card| card.id);
    let mut candidates = crate::state::Bounded::new();
    for card in ctx.state.zone_cards(&owner, from_zone) {
        if Some(card.id) == resolving {
            continue;
        }
        // §227：`Upgrade` 的候选收窄是**自动**的，不是内容声明的：一张牌能不能升级，
        // 问的是"内容里有没有它的 `+` 行"（`upgrade_cards_node` 用的同一条规则、同一个
        // `state::upgraded_id` 拼法）。已经带 `+` 的牌与没有 `+` 行的牌都不进候选 ——
        // 于是页面根本不会给玩家一个"点了什么都不发生"的选项。
        if matches!(then, crate::state::ChoiceThen::Upgrade) {
            let Some(content) = ctx.content else {
                return Err(ExecError::Ir(IrError::Missing("content")));
            };
            // §227: same helper as `upgrade_cards_node` -- "can this be upgraded" has one answer.
            if upgradable_definition(content, card.definition_id.as_str()).is_none() {
                continue;
            }
        }
        if tag_count > 0 {
            // 没有内容 ⇒ 不知道这张牌有什么 tag。**不许**当成"没有 tag"（那会让
            // "只复制攻击牌"把技能牌也列出来）。响亮失败，与 `forEachCardInZone` 的
            // `TagFilter` 同一条线。
            let Some(content) = ctx.content else {
                return Err(ExecError::Ir(IrError::Missing("content")));
            };
            let mut matched = false;
            for cell in tag_cells.iter().take(tag_count) {
                let Some(tag) = content.string(*cell) else {
                    continue;
                };
                if content
                    .card_has_tag(card.definition_id.as_str(), tag)
                    .unwrap_or(false)
                {
                    matched = true;
                    break;
                }
            }
            if !matched {
                continue;
            }
        }
        if candidates
            .push(card.id, crate::state::Container::ChoiceOptions)
            .is_err()
        {
            return Err(ExecError::Capacity(crate::state::CapacityError::Full(
                crate::state::Container::ChoiceOptions,
            )));
        }
    }
    let available = candidates.len();
    // 候选不够 `Min` 张 ⇒ 这个问句永远答不出来。不问（空操作）。
    if available < min as usize {
        return resume_later(ctx.state, frame, slot);
    }
    let question = crate::state::PendingChoice {
        chooser: owner,
        source,
        min: u8::try_from(min).map_err(|_| ExecError::Ir(IrError::Missing("Min")))?,
        // 上限也要夹到实际候选数：问句承诺"最多 N 张"，而 N 比能选的还多时，
        // 页面的计数和内核的判据就会各说一套。
        max: u8::try_from(max as usize).map_err(|_| ExecError::Ir(IrError::Missing("Max")))?
            .min(u8::try_from(available).unwrap_or(u8::MAX)),
        then,
        offered: crate::state::Bounded::new(),
        candidates,
    };
    if ctx.state.begin_choice(question).is_err() {
        return Err(ExecError::Modifier);
    }
    resume_later(ctx.state, frame, slot)
}

/// 一次抽签 = 一次完整置换，然后推进 `random_step`（与洗牌/掷骰同一条账）。
fn shuffle_candidates(order: &mut [usize], ctx: &mut ExecContext<'_>) {
    let mut indexes = [0u8; MAX_CARD_CANDIDATES];
    let count = order.len().min(indexes.len());
    for (index, slot) in indexes.iter_mut().enumerate().take(count) {
        *slot = index as u8;
    }
    crate::rng::shuffle_indexes(&mut indexes[..count], ctx.state.random_seed, ctx.state.random_step);
    ctx.state.random_step = ctx.state.random_step.saturating_add(1);
    for index in 0..count {
        order[index] = usize::from(indexes[index]);
    }
}

/// §195.4：一张牌的**稀有度排名**（"最高稀有度"取哪一张）。
///
/// `Rare 4 > Uncommon 3 > Common 2 > Basic 1 > Status 0 = Curse 0`。
/// 卡表里的六种串是 `Basic/Common/Uncommon/Rare/Status/Curse`；排序按**价值**而不是枚举序号
/// —— Status/Curse 在 StS 的枚举里排在 Rare **之后**，照序号降序会变成"先偷诅咒"。
fn card_rarity_rank(content: Option<&Content<'_>>, definition: &crate::state::CardDefinitionId) -> u8 {
    let Some(content) = content else {
        return 0;
    };
    match content.card_rarity(definition.as_str()) {
        Some("Rare") => 4,
        Some("Uncommon") => 3,
        Some("Common") => 2,
        Some("Basic") => 1,
        _ => 0,
    }
}

fn move_card_to_zone_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    stats: &mut ExecStats,
) -> Result<(), ExecError> {
    // `:1911`：卡实例表达式**先于** owner 解析求值（顺序照参考）。
    let card_expression = node
        .node_field("CardExpression")?
        .ok_or(IrError::Missing("CardExpression"))?;
    let card_id = {
        let expr_ctx = ctx.expr_context();
        expr::eval_card(card_expression, &expr_ctx)?
    };
    let to_zone_name = node.str_field("ToZone")?.ok_or(IrError::Missing("ToZone"))?;
    let to_zone = zone_from_wire_name(to_zone_name).ok_or(ExecError::Ir(IrError::UnknownKind))?;
    // `Placement` 缺席 ⇒ `Bottom`（`EffectProgramNativeNodes.cs:1301`）。
    let placement = match node.str_field("Placement")? {
        None => ZonePlacement::Bottom,
        Some(name) => {
            placement_from_wire_name(name).ok_or(ExecError::Ir(IrError::UnknownKind))?
        }
    };
    let owner_selector = node
        .node_field("OwnerSelector")?
        .ok_or(IrError::Missing("OwnerSelector"))?;

    // `:1922-1932`：`FirstOrDefault()` 解不出 owner ⇒ no-op（不报错，也不动任何卡）。
    let mut owners = [CombatantId::EMPTY; MAX_COMBATANTS];
    let owner_count = resolve_targets(owner_selector, ctx, &mut owners)?;
    let Some(owner) = owners.first().copied().filter(|_| owner_count > 0) else {
        return resume_later(ctx.state, frame, slot);
    };

    ctx.state.enqueue_effect_with_owner(
        EffectRequest::MoveCardToZone {
            owner,
            card: card_id,
            to_zone,
            placement,
        },
        Some(frame),
    )?;
    // 口径与其它产出型节点一致：**入队过一次请求**就记 1 次，哪怕 handler 最后判定
    // "同区 + Bottom" 什么都没写（见 [`ExecStats::effects`]）。
    stats.effects = stats.effects.saturating_add(1);
    resume_later(ctx.state, frame, slot)
}

/// [`move_card_to_zone_node`] 的实体：`MoveCardToZoneEffectHandler`（`CardZoneEffects.cs:165-213`）。
///
/// 三处"参考里抛异常让整个 program 作废"的受理不变量，冻结的 `ExecError` 没有对应变体
/// （没有 `MissingCard` / `NotOwner`），所以都借 [`ExecError::Modifier`]：
/// * 这个战斗员没有牌区 ⇒ `combat.GetCardZones(owner)` 抛；
/// * 卡 id 在这个战斗员的牌区里找不到 ⇒ `zones.GetCard(id)` 抛（`CardZones.cs:196-197`）；
/// * 卡存在但那套牌区不是它的主人 ⇒ `:175-179` 抛。
///
/// 后两条在本模型里是**同一件事**（"主人"就是"哪套牌区装着它"），所以合成一条，
/// 但**都是响亮失败**：绝不把"找不到卡"当"什么都不用做"。
fn move_card_for(
    ctx: &mut ExecContext<'_>,
    owner: &CombatantId,
    card_id: &CardInstanceId,
    to_zone: CardZone,
    placement: ZonePlacement,
) -> Result<(), ExecError> {
    if ctx.state.card_zones(owner).is_none() {
        return Err(ExecError::MissingCombatant);
    }
    let Some((from_zone, slot)) = find_card_in_zones(ctx.state, owner, card_id) else {
        return Err(ExecError::Modifier);
    };

    // `:187-195`：同区 + `Bottom` ⇒ **完全不动**（`WasMoved: false`，"历史行为不变"）；
    // 同区 + `Top` ⇒ 重排到堆顶（"放到抽牌堆顶"是关于**位置**的请求，不是关于牌区的）。
    if from_zone == to_zone {
        if placement == ZonePlacement::Top {
            // ⚠️ 已知偏差：`state::CombatState::move_card` 在**动手之前**先验目的地容量，
            // 所以一个装满 `MAX_CARDS_PER_ZONE`（96）张的牌堆做同区 Top 重排会报
            // `Full(CardsInZone)`，而参考的 `Insert(0, …)` 不会。响亮失败，不静默
            // （96 张同堆在真实内容里够不到，池子 224 张里也装得下）。
            ctx.state
                .move_card(owner, from_zone, to_zone, slot, ZonePlacement::Top)?;
        }
        return Ok(());
    }

    // `CardZones.cs:212-223`：`RemoveFromCurrentZone` → `SetZone` → `Top ? Insert(0) : Add`。
    // 内核的 `move_card` **复用池槽位**（别自己拼 push/remove，那样 22 轮就吃光 224 个槽）。
    ctx.state.move_card(owner, from_zone, to_zone, slot, placement)?;
    // §220：这是**打出落区**与**内容自己搬牌**两条路的唯一实体 ⇒ `Exhausted` 节目在这里跑。
    // 只搬牌不入队：入队会推进链号，而参考没有这条请求（§220 的对拍回归就死在那一格）。
    if to_zone == CardZone::ExhaustPile {
        if let Some(content) = ctx.content {
            if let Some(card) = ctx.state.card(slot) {
                let definition = card.definition_id;
                crate::host::run_card_lifecycle(
                    ctx.state,
                    content,
                    *owner,
                    definition,
                    crate::state::CardLifecycleEvent::Exhausted,
                )?;
            }
        }
        // §237：`CardExhausted` 事件与上面那段节目**同一个落点**（抽牌那边 `CardsDrawn` 同理）：
        // 生命周期节目有几个入口，事件就有几个入口 —— 少一个就是"消耗了但没人被告知"。
        if let Some(card) = ctx.state.card(slot) {
            let event = crate::state::CombatEvent::CardExhausted {
                combatant: *owner,
                card: card.id,
            };
            ctx.state.enqueue_event(event).map_err(ExecError::Capacity)?;
        }
    }
    Ok(())
}

/// 在**一个战斗员**的七个牌区里按 id 找卡，返回 `(在哪个区, 池槽位)`。
///
/// 这是参考 `zones.GetCard(id)`（`CardZones.cs:192-200`，`AllCards.FirstOrDefault`）的等价物：
/// 只在这套牌区里找，所以"找不到"同时覆盖了"卡不存在"与"卡的主人不是这个战斗员"。
fn find_card_in_zones(
    state: &CombatState,
    owner: &CombatantId,
    card_id: &CardInstanceId,
) -> Option<(CardZone, CardSlot)> {
    let zones = state.card_zones(owner)?;
    for zone in CardZone::ALL {
        for index in 0..zones.count(zone) {
            // 牌区里的槽位表与卡池必须一致；不一致的槽位跳过（下一轮由
            // `state.card()` 的 `Option` 兜住，不 panic）。
            let Some(slot) = zones.slot_at(zone, index) else {
                continue;
            };
            if state.card(slot).map(|card| card.id == *card_id) == Some(true) {
                return Some((zone, slot));
            }
        }
    }
    None
}

/// C# 的 `ZonePlacement` 枚举名 → 内核的 [`ZonePlacement`]（`Cards/CardZones.cs:27-31`：只有两个值）。
///
/// 镜像里 `Placement` 是**裸字符串枚举名**（实测 `"Bottom"`，flags=0）。⚠️ `"Top"` 这个串在
/// 整份镜像的串池里**根本不存在**（实测 `reader.py` 查不到），所以本层今天没有任何路径能
/// 走到 `Top` —— 它照样实现，是因为它是参考的两个合法值之一，少了它就是"少一种语义"。
fn placement_from_wire_name(name: &str) -> Option<ZonePlacement> {
    match name {
        "Bottom" => Some(ZonePlacement::Bottom),
        "Top" => Some(ZonePlacement::Top),
        _ => None,
    }
}

/// 一张卡的**定义**上有没有这个 tag（参考 `EffectProgramNodeExecutors.cs:452-458`，我验证过）。
///
/// 参考读 `combat.DefinitionRegistry.CardDefinitions[definitionId].Tags`；本内核没有独立的卡定义
/// 注册表，**内容镜像的 `CARD` 表就是那份注册表**（每行有 `Id` 与 `Tags` 两格），按 definition id
/// 走 `IDX`（`lookup_in`，`EK_CARD`）查行。三个"不是错误"的分支：
/// * 定义不在 `CARD` 表里 ⇒ **没有 tag**（`:454` 注释原话：未注册的定义没有 tag）⇒ `false`；
/// * `Tags` 格是 `ABSENT16`/`NULL16` ⇒ 空列表 ⇒ `false`；
/// * 列表里没有这个串 ⇒ `false`。
///
/// ⚠️ **`Tags` 的线上形状**（我量过，而且第一版读错了）：格是 `F_TERM`，指向一个 `_arr`
/// （op 4，唯一字段是 **`F_TERMLIST`**），两个槽是 `(AUX 起址, 个数)`；而 AUX 里装的是
/// **term id，不是串号** —— 每个元素是一个 `_wrap_lower` term（op 6），tag 串在那个 term 的槽 0。
/// 第一版按 `F_STRLIST`（串号）读，于是把**另一个列表**（`Disclosure`/`Dividend`…）当成了 tag 集合，
/// 每条 `TagFilter` 都静默匹配 0 张 —— 是 `e2e_19k` 当场把它抓出来的，不是靠读注释读出来的。
///
/// 形状不对（格 kind 不是 `F_TERM`、不是 `_arr`、元素不是 `_wrap_lower`、term/aux 越界）
/// ⇒ 响亮失败（镜像被改坏，不是"这张卡没 tag"）。
fn card_definition_has_tag(
    content: &Content<'_>,
    definition_id: &CardDefinitionId,
    tag: &str,
) -> Result<bool, ExecError> {
    let Some(entry) = content.lookup_in(definition_id.as_str(), EK_CARD) else {
        return Ok(false);
    };
    let Some(row) = content.card(u32::from(entry.index)) else {
        return Err(ExecError::Ir(IrError::Missing("CARD row")));
    };
    let Some(cell) = row.row().cell_index("Tags") else {
        return Err(ExecError::Ir(IrError::Missing("Tags")));
    };
    if row.row().cell_kind(cell) != Some(F_TERM) {
        return Err(ExecError::Ir(IrError::WrongKind("F_TERM")));
    }
    let raw = row.tags();
    let tag_list = match raw {
        ABSENT16 | NULL16 => return Ok(false),
        id => id,
    };
    let list = content.term(tag_list).ok_or(IrError::Term(tag_list))?;
    if list.op != OP_ARR {
        return Err(ExecError::Ir(IrError::WrongKind("_arr")));
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
        if element_term.op != OP_WRAP_LOWER {
            return Err(ExecError::Ir(IrError::WrongKind("_wrap_lower")));
        }
        let string = element_term.slot(0).ok_or(IrError::Slot)?;
        if content.string(string) == Some(tag) {
            return Ok(true);
        }
    }
    Ok(false)
}

/// C# 的 `CardZone` 枚举名 → 内核的 [`CardZone`]（`Cards/CardZones.cs:3-22`）。
/// 镜像里 `ToZone` 存的是**枚举名原文**（实测 `"DiscardPile"` / `"Hand"`），flags 是 0（裸串）。
/// ⚠️ 不能用 `state::CardZone::wire_name()` 反查：那是**哈希的**短名（`disc`/`hand`），
/// 与内容里的枚举名是两套词。不认识的串返回 `None`，由调用方响亮拒绝。
pub(crate) fn zone_from_wire_name(name: &str) -> Option<CardZone> {
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

/// 某个战斗员的命名计数器读数（缺席 ⇒ 0，`CombatantState.cs:64` 的 `GetCounter`）。
fn counter_of(combatant: &Combatant, key: &CounterId) -> i32 {
    for counter in combatant.counters() {
        if counter.key == *key {
            return counter.value;
        }
    }
    0
}

/// 某个战斗员的资源池副本（缺席 ⇒ `None`）。
fn resource_pool(combatant: &Combatant, key: &ResourceId) -> Option<crate::state::Pool> {
    for pool in combatant.resources() {
        if pool.key == *key {
            return Some(pool.pool);
        }
    }
    None
}

/// 某个战斗员某个牌区的张数（牌区表缺席 ⇒ 0，与 `state::CombatState::card_zones` 的契约一致）。
fn zone_count(state: &CombatState, owner: &CombatantId, zone: CardZone) -> usize {
    state.card_zones(owner).map_or(0, |zones| zones.count(zone))
}

// =============================================================================================
// 状态施加：合并规则（`StatusEffects.cs:126-199`）
// =============================================================================================

/// The card tags the kernel reports as **event facts** (`event.bool`). One bit each.
///
/// These are the only tags any photographed content asks about; a new one is a one-line change
/// here plus a line in `expr::eval_bool`.
/// §208: `event.bool: damage.isAttack` —— 这次伤害是不是攻击（`Direct`）。
///
/// 与下面四个卡牌标签位**同一套仓位**：`event_flags` 是「这次事件的事实」的位图，谁来填由事件
/// 种类决定（`CardPlayed` 填卡牌标签，`DamageTaken` 填这一个）。受击侧此前一个事实都没有，
/// 于是 Flying 那种"只在被打时扣层"只能写成"受任何伤害都扣"。
pub const DAMAGE_IS_ATTACK: u16 = 1 << 4;

pub const CARD_HAS_TAG_ATTACK: u16 = 1 << 0;
pub const CARD_HAS_TAG_SKILL: u16 = 1 << 1;
pub const CARD_HAS_TAG_POWER: u16 = 1 << 2;
pub const CARD_HAS_TAG_STATUS: u16 = 1 << 3;

/// §237：`curse` 标签（`Fire Breathing` 要"Status **或** Curse"）。第 7 位是当时唯一空着的。
pub const CARD_HAS_TAG_CURSE: u16 = 1 << 7;

/// §249：刚落下的那条状态是 **debuff**（`Sadistic Nature`）。
pub const STATUS_IS_DEBUFF: u16 = 1 << 9;

/// §249：刚落下的那条状态**不是**施法者给自己的（`Sadistic Nature` 说 "to an **enemy**"）。
pub const STATUS_APPLIED_TO_OTHER: u16 = 1 << 10;

/// §239：**这次出牌时，手牌里每一张都是 Attack**（`Clash` 的 `PlayCondition` 问的就是它）。
///
/// 为什么是"一位、一个问题"，不是"每位一个 tag"：这个事实只有 `PlayCondition` 会问，而
/// `PlayCondition` 在**出牌校验**时求值 —— 那一刻有内容（能查卡牌 tag），所以由校验器算好这一位。
/// 位宽的其它 8 位都是"事件事实"，这一位是"出牌前提"，靠注释与命名分开（`playCondition.` 前缀）。
///
/// ⚠️ 它**只在出牌校验时**被填。别的地方问它会得到 0（= false），所以
/// `sts_content_check.py` 有一条判据：`playCondition.*` 这个键只许出现在卡的 `PlayCondition` 里。
pub const PLAY_CONDITION_HAND_ALL_ATTACKS: u16 = 1 << 8;

/// §226：这一趟迭代的牌**是不是正在结算的那一张**（`forEachCardInZone` 填，`event.bool` 读）。
///
/// 为什么需要它：StS 里"打出的牌已经不在手牌"是**结构性**的（它当时在 in-play 区），所以
/// `Second Wind` / `Fiend Fire` 这类"消耗手牌里的牌"天然**不含自己**。参考引擎把打出的牌留在
/// 手里直到终态回调（落区在 `onTerminal`），于是循环快照里会看到它 —— 那不是内容的错，是
/// 参考与本模型的共同形状。
///
/// 两条被否掉的做法，都留在这里当**反面证据**：
/// * 出牌时就把牌搬离手牌 ⇒ 改变每一步哈希里的牌区计数，`CARD_DIFF` / `FIGHT_DIFF` 当场红。
/// * `forEachCardInZone` 的快照里跳过它 ⇒ `archive_the_evidence`（参考契约里的那张 scenario 卡，
///   节目就是 `sequence[forEachCardInZone, gainBlock]`，靠"循环能看见自己"把**自己**搬进消耗堆）
///   立刻红，而且那是**参考**的行为，不是我们的 bug（§225 被挡回的那条修法）。
///
/// ⇒ 内核只提供**事实**，跳不跳过由内容说。没有正在结算的牌时这一位恒 0（状态/遗物/敌人招式
/// 的节目里"没有哪张牌是自己"）。
pub const CARD_IS_RESOLVING: u16 = 1 << 5;

/// §236：这次失去生命是不是**一张牌**付的代价（`Rupture` 只认这一种）。
pub const HP_LOSS_FROM_CARD: u16 = 1 << 6;

/// Apply one status by **id string** -- a test-only door into [`apply_one_status`], so tests can
/// exercise the Artifact gate without building a whole program (`port-plan.md` §117).
#[cfg(test)]
pub(crate) fn apply_status_for_test(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    definition: &str,
    stacks: i32,
) -> Result<(), ExecError> {
    let definition_id = StatusDefinitionId::new(definition)?;
    apply_one_status(ctx, target, definition_id, stacks, 0, 0)
}

/// 对**一个**目标施加一次状态。
fn apply_one_status(
    ctx: &mut ExecContext<'_>,
    target: &CombatantId,
    definition_id: StatusDefinitionId,
    stacks: i32,
    duration_turns: i32,
    charges: i32,
) -> Result<(), ExecError> {
    // 受理不变量（`StatusEffects.cs:55-62`）：三轴负数一律 fault（整个 program 作废）。
    // 放在**写入路径**里而不是节点里，是为了让"绕过节点直接调这个函数"也守住同一条线。
    if stacks < 0 || duration_turns < 0 || charges < 0 {
        return Err(ExecError::Modifier);
    }

    // **Artifact 先过一道**（wiki: "negate the next debuff"）。只挡 Debuff，也只挡真正要加的
    // 层数（`stacks == 0` 不算一次施加）。吃掉一层 Artifact 就返回 —— 目标一点状态都不沾。
    if stacks > 0 {
        let content = ctx.content;
        let polarity = status_polarity(definition_id.as_str(), content)?;
        if polarity == crate::state::StatusPolarity::Debuff {
            let artifact = ctx
                .state
                .combatant(target)
                .ok_or(ExecError::MissingCombatant)?
                .statuses()
                .iter()
                .position(|status| {
                    status.definition_id.as_str() == "standard.artifact" && status.stacks > 0
                });
            if let Some(index) = artifact {
                let combatant = ctx
                    .state
                    .combatant_mut(target)
                    .ok_or(ExecError::MissingCombatant)?;
                let Some(status) = combatant.statuses_mut().get_mut(index) else {
                    return Err(ExecError::Modifier);
                };
                status.stacks -= 1;
                if status.stacks <= 0 {
                    combatant.remove_status(index);
                }
                // Artifact 挡下了这一发 ⇒ 参考会报 `StatusApplicationPrevented`。
                ctx.state
                    .enqueue_event(crate::state::CombatEvent::StatusApplicationPrevented {
                        target: *target,
                    })
                    .map_err(ExecError::Capacity)?;
                // 动画日志（§142）：`def` 记**被挡下的那个状态**（页面要飘"免疫"），
                // 而不是 Artifact 本身 —— 玩家关心的是"我想上的 debuff 没上成"。
                let def = crate::beat::intern_def(ctx.state, definition_id.as_str());
                let target_ordinal = crate::beat::ordinal_of(ctx.state, target);
                crate::beat::record(
                    ctx.state,
                    crate::beat::Beat {
                        kind: crate::beat::BeatKind::StatusPrevented,
                        actor: match ctx.source {
                            Some(source) => crate::beat::ordinal_of(ctx.state, &source),
                            None => crate::beat::NOBODY,
                        },
                        target: target_ordinal,
                        def,
                        flags: 0,
                        a: stacks,
                        b: 0,
                        c: 0,
                    },
                );
                return Ok(());
            }
        }
    }

    // 同定义 id 的**第一个**实例（`FirstOrDefault(status => status.DefinitionId == …)`，`:128-130`）。
    let existing = ctx
        .state
        .combatant(target)
        .ok_or(ExecError::MissingCombatant)?
        .statuses()
        .iter()
        .position(|status| status.definition_id == definition_id);

    if let Some(index) = existing {
        // `StatusMerged` 要在借用结束之后入队（`ctx.state` 只能借一次）。
        let merged_target = *target;
        let combatant = ctx
            .state
            .combatant_mut(target)
            .ok_or(ExecError::MissingCombatant)?;
        let Some(status) = combatant.statuses_mut().get_mut(index) else {
            // `position` 刚给的下标不可能越界；这一条只为"没有 panic 路径"存在。
            return Err(ExecError::Modifier);
        };
        // `:135-139`：层数/充能相加（`Math.Min(int.MaxValue, (long)a + b)`），时长取 max。
        //
        // ⚠️ **`source_combatant_id` 不在这里改**：参考的合并分支只动这三样，并留了一段
        // 注释说清楚为什么（`StatusEffects.cs:159-165`：*"The instance keeps its own source,
        // untouched"* —— 合并事件报告的是**这一次施加**的来源，那是事件字段的事，不是实例的）。
        // 顺手改它会把"这条毒是谁下的"变成"最后一次有人碰它时是谁下的"。
        status.stacks = add_clamped(status.stacks, stacks);
        status.duration_turns = status.duration_turns.max(duration_turns);
        status.charges = add_clamped(status.charges, charges);
        ctx.state
            .enqueue_event(crate::state::CombatEvent::StatusMerged { target: merged_target })
            .map_err(ExecError::Capacity)?;
        // 动画日志（§142）：`a` = **这一次加了多少**（不是合并后的总数），
        // `flags` 不带 `FLAG_NEW_INSTANCE` ⇒ 页面知道图标已经在场，只是数字变大。
        let def = crate::beat::intern_def(ctx.state, definition_id.as_str());
        let ordinal = crate::beat::ordinal_of(ctx.state, &merged_target);
        crate::beat::record(
            ctx.state,
            crate::beat::Beat {
                kind: crate::beat::BeatKind::StatusChanged,
                actor: match ctx.source {
                    Some(source) => crate::beat::ordinal_of(ctx.state, &source),
                    None => crate::beat::NOBODY,
                },
                target: ordinal,
                def,
                flags: 0,
                a: stacks,
                b: 0,
                c: 0,
            },
        );
        return Ok(());
    }

    // 极性：有内容镜像时走 `STAT.Polarity`（参考实现的路），否则走标准包目录。
    let content = ctx.content;
    let polarity = status_polarity(definition_id.as_str(), content)?;
    // 新实例走**唯一入口**：`push_new_status` 负责取号、造实例、自增。
    ctx.state
        .enqueue_event(crate::state::CombatEvent::StatusApplied {
            target: *target,
            // §249：极性此刻才知道（`polarity` 就是上一行算出来的那个）。
            debuff: matches!(polarity, crate::state::StatusPolarity::Debuff),
            // §249："落在别人身上" —— 给自己挂 debuff 不该触发 `Sadistic Nature`。
            applied_to_other: ctx.source.map_or(true, |source| source != *target),
        })
        .map_err(ExecError::Capacity)?;
    push_new_status(
        ctx.state,
        target,
        definition_id,
        stacks,
        duration_turns,
        charges,
        polarity,
        ctx.source,
    )?;
    // 动画日志（§142）：新建实例 ⇒ 带 `FLAG_NEW_INSTANCE`，页面据此**先画图标再飘数字**。
    let def = crate::beat::intern_def(ctx.state, definition_id.as_str());
    let ordinal = crate::beat::ordinal_of(ctx.state, target);
    crate::beat::record(
        ctx.state,
        crate::beat::Beat {
            kind: crate::beat::BeatKind::StatusChanged,
            actor: match ctx.source {
                Some(source) => crate::beat::ordinal_of(ctx.state, &source),
                None => crate::beat::NOBODY,
            },
            target: ordinal,
            def,
            flags: crate::beat::FLAG_NEW_INSTANCE,
            a: stacks,
            b: duration_turns,
            c: charges,
        },
    );
    Ok(())
}

/// `(int)Math.Min(int.MaxValue, (long)a + b)`（`StatusEffects.cs:135-139`）；下界也夹住，只为不 panic。
fn add_clamped(current: i32, delta: i32) -> i32 {
    let sum = i64::from(current) + i64::from(delta);
    if sum > i64::from(i32::MAX) {
        i32::MAX
    } else if sum < i64::from(i32::MIN) {
        i32::MIN
    } else {
        sum as i32
    }
}

/// 新状态实例的极性 —— **偏差 A 的修复点**（见模块头假设 B）。
///
/// 三条优先级，顺序就是这个函数的代码顺序：
///
/// 1. **有内容镜像 ⇒ `status_bind::polarity`**（`STAT.Polarity` 格）。这是参考实现的路：
///    `ApplyStatusEffectHandler` 把内容定义里的 `definition.Polarity` 直接搬进新实例
///    （`StatusEffects.cs:195`，**我核对过这一行**）。
///    镜像实测 `doubt` = `Debuff` —— 旧实现在这里查目录、查不到就默认 `Buff`，
///    一旦 exec 接上会算哈希的战场，`pol=` 就与参考不同。
/// 2. 没有镜像 ⇒ `status_catalog::status_meta`（标准包 16 + 2 个 `standard.*` id）。
/// 3. **两边都查不到 ⇒ `Buff`。这是最后兜底**，不是一条策略：`Buff` 是 `StatusPolarity`
///    的零值，也是"内容什么都没说"时唯一不假装成结论的选择。它必须能被单独看见 ——
///    所以写成显式的 `match` 分支而不是 `unwrap_or`，并且这条路径有单测钉住它只在
///    "内容里根本没有这个 id"时才走。
///
/// 返回 `Result` 是因为**镜像里的数据坏了必须响亮失败**：`Polarity` 串不是
/// `Buff`/`Debuff`/`Neutral`（或这一格根本取不到串）⇒ [`ExecError::Bind`]。
/// 那种情况下猜一个默认值正是本模块最不该做的事。
fn status_polarity(
    definition_id: &str,
    content: Option<&Content<'_>>,
) -> Result<StatusPolarity, ExecError> {
    if let Some(content) = content {
        return match status_bind::polarity(content, definition_id)? {
            Some(polarity) => Ok(polarity),
            // 内容里没有这个状态定义 —— 最后兜底（见上面第 3 条）。
            None => Ok(StatusPolarity::Buff),
        };
    }
    Ok(
        match status_catalog::status_meta(definition_id).map(|meta| meta.polarity) {
            Some(status_catalog::StatusPolarity::Debuff) => StatusPolarity::Debuff,
            Some(status_catalog::StatusPolarity::Neutral) => StatusPolarity::Neutral,
            // 目录查不到（镜像独有的 `doubt`/`paperwork` 之类）或就是 `Buff` —— 同一个结果。
            Some(status_catalog::StatusPolarity::Buff) | None => StatusPolarity::Buff,
        },
    )
}

/// **The one way a new status instance is born.** Takes the next instance number, builds the
/// instance, pushes it, and advances the counter -- `CombatState.cs:680-687`.
///
/// Both the `applyStatus` opcode ([`apply_one_status`]) and the host's own steps (`Host`'s
/// `grant_ritual_strength`, for Ritual) go through here, so there is exactly one place that knows
/// about numbering. Getting that wrong corrupts instance ids for the whole fight.
#[allow(clippy::too_many_arguments)]
pub(crate) fn push_new_status(
    state: &mut CombatState,
    target: &CombatantId,
    definition_id: StatusDefinitionId,
    stacks: i32,
    duration_turns: i32,
    charges: i32,
    polarity: StatusPolarity,
    source: Option<CombatantId>,
) -> Result<StatusInstanceId, ExecError> {
    let number = state.next_status_instance_number;
    let instance_id = status_instance_id(number)?;
    let mut instance = StatusInstance::new(instance_id, definition_id, polarity)
        .with_stacks(stacks)
        .with_duration_turns(duration_turns)
        .with_charges(charges);
    // `:187`：`SourceCombatantId: applyStatus.SourceCombatantId` —— 新实例**原样收下**这一次
    // 施加的出手方。没有来源（`ctx.source == None`，例如一条没有 `sel.source` 的节目）⇒ `None`，
    // 不是"猜一个行动者"。
    if let Some(source) = source {
        instance = instance.with_source_combatant(source);
    }
    {
        let combatant = state.combatant_mut(target).ok_or(ExecError::MissingCombatant)?;
        combatant.push_status(instance)?;
    }
    state.next_status_instance_number = number.saturating_add(1);
    Ok(instance_id)
}

/// `status_%06d`（`CombatState.cs:680-687`：`$"status_{NextStatusInstanceNumber:000000}"`）。
fn status_instance_id(number: i32) -> Result<StatusInstanceId, ExecError> {
    let mut buffer = [0u8; INSTANCE_TEXT_CAP];
    let text = numbered_instance_text(b"status_", number, &mut buffer)?;
    Ok(StatusInstanceId::new(text)?)
}

/// 装一个 `<prefix>%06d` 的栈上缓冲要多大（§161.5：定义搬到了 `state.rs`）。
const INSTANCE_TEXT_CAP: usize = crate::state::INSTANCE_TEXT_CAP;

/// `<prefix>%06d` 的零分配版。**实现在 [`crate::state::numbered_text`]**（§161.5 搬过去，
/// 因为 `create_card_instance` 在 `state.rs` 里也要它）。这里只把 `Option` 换成 `ExecError`。
fn numbered_instance_text<'b>(
    prefix: &[u8],
    number: i32,
    buffer: &'b mut [u8; INSTANCE_TEXT_CAP],
) -> Result<&'b str, ExecError> {
    crate::state::numbered_text(prefix, number, buffer).ok_or(ExecError::Modifier)
}

// =============================================================================================
// 数值求值 / 目标解析
// =============================================================================================

/// 求一个数值字段（`Amount` / `Stacks`）—— **整个节点只求一次**（参考 `:608,651,771,906`）。
fn eval_amount(
    node: NodeRef<'_>,
    field: &'static str,
    ctx: &ExecContext<'_>,
) -> Result<i32, ExecError> {
    let expression = node.node_field(field)?.ok_or(IrError::Missing(field))?;
    let expr_ctx = ctx.expr_context();
    Ok(expr::eval_int(expression, &expr_ctx)?)
}

/// 解析一个 `TargetSelector` 字段，返回目标个数（写进 `out`）。
///
/// `out` 必须装得下 [`MAX_COMBATANTS`] 个：任何选择器的结果都是 `state.combatants` 的子集，
/// 所以**不会截断**（见 `targets::resolve` 关于 sink 容量的契约）。
fn resolve_targets(
    selector: NodeRef<'_>,
    ctx: &ExecContext<'_>,
    out: &mut [CombatantId],
) -> Result<usize, ExecError> {
    let compiled = CompiledSelector::compile(selector)?;
    let selection = ctx.selection_context();
    // `resolve` 的 `SelectorError` 只可能来自坏下标/坏 id 引用/环 —— 也就是"编译出来的表自己坏了"。
    // `sel.rs:216-221` 已经定下把它映射成 `TableFull`（编译期保证表是好的，这条分支不可达），
    // `expr.rs:561-566` 用的是同一条映射；这里照抄，重要的是**不是 unwrap**。
    compiled
        .resolve(&selection, out)
        .map_err(|_| ExecError::Sel(SelError::TableFull))
}

// =============================================================================================
// 修饰器管线：候选表从这里构造
//
// **两张权威表，按 `ctx.content` 二选一**（模块头那张表）：
//   * `None`  ⇒ `status_catalog` 的两张硬编码表（标准包 / oracle / env）；
//   * `Some`  ⇒ 每个在身状态**自己的** `STAT.PassiveModifiers`（镜像 = 参考实现的路，
//               `PassiveModifiers.cs:142-172`）。
// 本文件里**没有任何一处硬编码"力量 +1 / 虚弱 ×75 / 易伤 ×150"** —— 数值全部来自这两处。
// =============================================================================================

/// 一行的"扁平原型"，让伤害表与格挡表能走同一段折叠代码。
///
/// `status_id` 带生命周期：标准包的行 id 是 `&'static str`，镜像的行 id 借用镜像的串池
/// （`&'a str`）。两者都能塞进 `Row<'a>`，而 `status_key` 只关心字节。
#[derive(Clone, Copy, Debug)]
struct Row<'a> {
    /// `spec.Priority`（标准包 100/200/300；镜像实测全是 100）。
    priority: i32,
    /// 状态**定义** id —— 排序键第二级就是它的字节（`PassiveModifiers.cs:183` 的
    /// `string.CompareOrdinal`），也是"这个状态在不在身"的匹配键。
    status_id: &'a str,
    /// 运算。用 `modifiers::Operation` 而不是某一家的 `ModifierOp`：三值
    /// （`AddPerStack`/`AddFlat`/`ScalePercent`）正好是两张表的并集，
    /// 多一次中间映射就多一个错的机会。
    operation: Operation,
    /// `ScalePercent` 是百分比，`AddPerStack` 是每层幅值，`AddFlat` 是一次幅值。
    magnitude: i32,
    /// 该 spec 在**它那张表**里的下标（排序键第三级，`PassiveModifiers.cs:184`）。
    spec_index: u16,
}

/// [`Row`] 的空槽工厂。
///
/// 是**函数**而不是 `const`：`Row` 现在带生命周期，一个 `const EMPTY_ROW: Row<'static>`
/// 装不下镜像借来的 `&'a str`（`[EMPTY_ROW; N]` 会把元素类型钉死成 `Row<'static>`，
/// 之后往槽里写 `Row<'a>` 就编译不过）。`""` 是 `&'static str`，对任何 `'a` 都能收窄，
/// 所以这个工厂给出的是 `Row<'a>`。
fn empty_row<'a>() -> Row<'a> {
    Row {
        priority: 0,
        status_id: "",
        operation: Operation::AddFlat,
        magnitude: 0,
        spec_index: 0,
    }
}

/// 状态 id 与实例定义 id 怎么算"同一个状态"（模块头那张表的第三行）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum StatusMatch {
    /// **逐字节相等**。有 `content` 时唯一合法的口径：镜像的 id 就是参考的 `group.Key.value`。
    Exact,
    /// 逐字节相等 **或** [`modifier_applies_to`] 的命名空间桥。只有没有 `content` 时才有意义。
    Bridged,
}

impl StatusMatch {
    /// 由"有没有内容镜像"决定匹配口径 —— **这是桥开不开的唯一开关**。
    ///
    /// 一行代码，但它是本模块最重要的一行：`status_catalog` 的 5 个 id 与镜像的 23 个 id
    /// 是**两套命名空间**，桥是"猜它们同义"。有镜像时那个猜测必须失效，否则两个方向都错：
    /// 镜像自己的 `doubt` 会因为没有目录行而静默不生效（它确实是 Debuff 且该 ×75），
    /// 而标准包的 `standard.strength` 会被当成镜像的 `strength` 加上层数。
    fn for_content(content: Option<&Content<'_>>) -> Self {
        match content {
            Some(_) => StatusMatch::Exact,
            None => StatusMatch::Bridged,
        }
    }
}

/// 目录这一侧的运算映射：`AddStacks ⇒ AddPerStack`、`MulPercent ⇒ ScalePercent`
/// （`docs/spec/modifier-pipeline.md` §2 的两列就是这两对）。
fn catalog_operation(op: ModifierOp) -> Operation {
    match op {
        ModifierOp::AddStacks => Operation::AddPerStack,
        ModifierOp::MulPercent => Operation::ScalePercent,
    }
}

/// 镜像这一侧的运算映射（`status_bind::ModifierOp` → `modifiers::Operation`）。
fn image_operation(op: status_bind::ModifierOp) -> Operation {
    match op {
        status_bind::ModifierOp::AddPerStack => Operation::AddPerStack,
        status_bind::ModifierOp::AddFlat => Operation::AddFlat,
        status_bind::ModifierOp::ScalePercent => Operation::ScalePercent,
        // §198: our own operation -- the status pipeline carries it straight through.
        status_bind::ModifierOp::ScalePercentPerStack => Operation::ScalePercentPerStack,
        // §216: `Slow`'s "+10% per card played **this turn**" -- the factor reads the kernel's
        // own counter, not the status' stacks.
        status_bind::ModifierOp::ScalePercentPerCardPlayedThisTurn => {
            Operation::ScalePercentPerCardPlayedThisTurn
        }
        // §210: `Intangible`'s "all damage becomes 1" -- `min(current, max(0, 1))`.
        status_bind::ModifierOp::ClampMax => Operation::ClampMax,
    }
}

/// 伤害种类门（`PassiveModifiers.cs:155`）：
/// `if (damageKind is { } kind && spec.RestrictDamageKind is { } restrict && restrict != kind) continue;`
///
/// 两个方向都要对，缺一个就变成静默算错：
///
/// * `restrict == None`（镜像里 `panic` 的 `RestrictDamageKind` 就是 null）⇒ **放行一切种类**。
///   这是参考的门短路的第一半（`damageKind is { }` 之后才看 `restrict`，而 `restrict` 为 null
///   时整条 `continue` 不成立）。反过来写（"null 只用于 Direct"）会让一条不限种类的
///   `ScalePercent` 对 DoT 失效 —— 而参考里它生效。
/// * `Some(r)` ⇒ **只有 `r == kind` 才放行**。标准包三行与镜像 5 条 spec 的 `r` 都是 `Direct`
///   （`PassiveModifiers.cs:87` 的默认值就是这个），所以它们对 DoT/反伤整表不参与。
const fn damage_kind_passes(restrict: Option<BindDamageKind>, kind: BindDamageKind) -> bool {
    match (restrict, kind) {
        // `restrict` 为 null ⇒ 那条 `continue` 不成立（放行一切种类）。
        (None, _) => true,
        (Some(BindDamageKind::Direct), BindDamageKind::Direct) => true,
        (Some(BindDamageKind::Dot), BindDamageKind::Dot) => true,
        (Some(BindDamageKind::Reflected), BindDamageKind::Reflected) => true,
        (Some(_), _) => false,
    }
}

/// `PassiveModifier` 的空槽（`[T; N]` 的初始化要一个值；它不带生命周期，所以可以是 `const`）。
const EMPTY_PASSIVE_MODIFIER: PassiveModifier = PassiveModifier {
    pipeline: status_bind::Pipeline::DamageDealt,
    operation: status_bind::ModifierOp::AddFlat,
    magnitude: 0,
    priority: 0,
    restrict_damage_kind: None,
};

/// 伤害的一个阶段：从**读谁的状态**到候选表，再从候选表到新数值。
fn damage_stage<'a>(
    amount: i32,
    statuses: &[StatusInstance],
    stage: ModifierTarget,
    owner: &CombatantId,
    content: Option<&'a Content<'a>>,
    kind: BindDamageKind,
    turn_cards: i32,
) -> Result<i32, ExecError> {
    // **口径只在这里定一次**：有镜像 ⇒ `Exact`（桥关闭），没有 ⇒ `Bridged`。
    let matching = StatusMatch::for_content(content);
    if let Some(content) = content {
        return image_damage_stage(
            amount, statuses, stage, owner, content, matching, kind, turn_cards,
        );
    }

    // ── 标准包路径的种类门（`PassiveModifiers.cs:87,155`）。
    //
    // 标准包三行的 `RestrictDamageKind` **都是** `Direct`，而冻结的 `DamageModifierEntry` 里没有
    // 这一列 —— 它被提成了一个常量（`status_catalog.rs:119-124` 的
    // `DAMAGE_MODIFIER_DAMAGE_KINDS`），并在那里就写明了契约：
    // 「调用方**必须**先过这道门：`Kind != Direct` 时整表不参与」（`status_catalog.rs:168`）。
    // 这一行就是那个"必须"。
    //
    // 不写它的后果是**静默的**：`resolve_damage_of_kind(…, Dot)` 会照旧把力量/虚弱/易伤
    // 折进 DoT，而每一个数字都看起来合理 —— 这正是这条门存在的理由。
    if status_catalog::DAMAGE_MODIFIER_DAMAGE_KINDS & kind.bit() == 0 {
        return Ok(amount);
    }

    let mut rows = [empty_row(); MAX_CANDIDATES];
    let mut count = 0usize;
    for (index, entry) in status_catalog::damage_modifiers().iter().enumerate() {
        if entry.stage != stage {
            continue;
        }
        let Some(slot) = rows.get_mut(count) else {
            return Err(ExecError::Modifier);
        };
        *slot = damage_row(entry, index);
        count += 1;
    }
    fold(
        amount,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        matching,
        turn_cards,
    )
}

/// 镜像路径的一个伤害阶段：候选行来自每个在身状态**自己的** `PassiveModifiers`。
fn image_damage_stage<'a>(
    amount: i32,
    statuses: &[StatusInstance],
    stage: ModifierTarget,
    owner: &CombatantId,
    content: &'a Content<'a>,
    matching: StatusMatch,
    kind: BindDamageKind,
    turn_cards: i32,
) -> Result<i32, ExecError> {
    let pipeline = match stage {
        ModifierTarget::Source => status_bind::Pipeline::DamageDealt,
        ModifierTarget::Target => status_bind::Pipeline::DamageReceived,
    };
    let mut rows = [empty_row(); MAX_CANDIDATES];
    let count = image_rows(content, statuses, pipeline, Some(kind), &mut rows)?;
    fold(
        amount,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        matching,
        turn_cards,
    )
}

/// 把"这个战斗员身上的状态"摊成候选行：**每个在身定义**贡献它自己那些
/// `pipeline == 该管线` 的 spec。
///
/// 三条与参考对齐的细节：
///
/// 1. **按定义去重**（`PassiveModifiers.cs:142` 的 `GroupBy(DefinitionId)`）。
///    同一定义的第二条实例**不再产生第二份 spec** —— 否则 `AddPerStack` 会按两份层数各加一次，
///    而参考里层数是 `group.Sum(Stacks)` 的**一次**加法（`:148,208`）。去重就靠"行表里已经有
///    这个 id 了吗"，n ≤ 24 所以是极小的 n²。
/// 2. **`spec_index` 是 spec 在 `def.PassiveModifiers` 里的下标**，不是"过滤后的第几条"
///    （`:149-172` 里 `i` 从头到尾没被过滤打乱）。
/// 3. **`status_id` 用镜像里的定义 id 字节**：参考排的是 `group.Key.value`（`:183`），
///    也就是定义 id 的字符串，不是实例 id、不是注册序。
///
/// `damage_kind`：`Some(kind)` ⇒ 走 `:155` 的种类门；`None` ⇒ 门整段跳过
/// （`TurnStartDraw` / 格挡那两条管线在参考里传的就是 null，`:267`、`CardTurnLifecycleEventHandlers.cs:27`）。
///
/// # 查不到定义 ⇒ **响亮失败**（[`BindError::Missing`]`("STAT row")`）
///
/// 本轮之前这里是 `let Some(decoded) = … else { continue }`：一个**不在镜像 `STAT` 表里**的
/// 状态 id（自造 id、拼错、内容包没带这个定义）于是与"这个状态不参与这条管线"落进同一条静默分支。
/// 那是最坏的一档失败 —— 内容写了它、引擎不生效、而**每个数字看着都合理**。
/// 所以走 [`status_bind::decode_required`]：定义查不到就是拒绝。
/// 已知定义 + 空 `PassiveModifiers`（`paperwork` 那 18 个）仍然正常放行，那是纯声明式状态。
fn image_rows<'a>(
    content: &'a Content<'a>,
    statuses: &[StatusInstance],
    pipeline: status_bind::Pipeline,
    damage_kind: Option<BindDamageKind>,
    rows: &mut [Row<'a>],
) -> Result<usize, ExecError> {
    let mut buffer = [EMPTY_PASSIVE_MODIFIER; status_bind::MAX_MODIFIERS];
    let mut count = 0usize;

    for status in statuses {
        let id = status.definition_id.as_str();
        // 1. 这个定义已经摊过了 ⇒ 跳过（层数会在 `fold` 的 `total_stacks` 里求和）。
        if rows
            .get(..count)
            .unwrap_or(&[])
            .iter()
            .any(|row| row.status_id == id)
        {
            continue;
        }
        // 内容里没有这个定义 ⇒ **拒绝**（不是"猜一个标准包的同名行"，也不是"没意见"）。
        let decoded = status_bind::decode_required(content, id, &mut buffer)?;

        for index in 0..decoded.modifier_count {
            let spec = *buffer.get(index).ok_or(ExecError::Modifier)?;
            // `PassiveModifiers.cs:152` 的管线门。
            if spec.pipeline != pipeline {
                continue;
            }
            // `:155` 的伤害种类门（`damage_kind == None` 时整段跳过）。
            if let Some(kind) = damage_kind {
                if !damage_kind_passes(spec.restrict_damage_kind, kind) {
                    continue;
                }
            }
            let Some(slot) = rows.get_mut(count) else {
                return Err(ExecError::Modifier);
            };
            *slot = Row {
                priority: spec.priority,
                status_id: decoded.id,
                operation: image_operation(spec.operation),
                magnitude: spec.magnitude,
                spec_index: u16::try_from(index).map_err(|_| ExecError::Modifier)?,
            };
            count += 1;
        }
    }

    Ok(count)
}

/// `TurnStartDraw` 管线的折叠（`CardTurnLifecycleEventHandlers.cs:25-31`）——
/// `turn_start_draw_count` 钩子的**唯一**正确实现处。
///
/// ```text
/// cardsToDraw = DeclarativePassiveModifierEngine.Apply(
///     combat, registry, combatant, PassiveModifierPipeline.TurnStartDraw,
///     damageKind: null, _cardsToDraw);          // :27-29
/// if (cardsToDraw <= 0) return;                 // :30-31
/// combat.EnqueueEffect(new DrawCardsEffectRequest { Count = cardsToDraw });
/// ```
///
/// 三条与参考对齐的细节（每一条都会改变数字）：
///
/// 1. **`damageKind: null`** ⇒ `:155` 的种类门**整段跳过**（`damageKind is { } kind` 为假）。
///    所以 `RestrictDamageKind` 对这条管线毫无意义 —— 镜像里 `panic` 那条 spec 的
///    `RestrictDamageKind` 正是 `null`，两种口径在此同值，但原因不同：不是"null 当 Direct"，
///    而是"这条管线不问种类"。传 `Some(_)` 进来会是另一个函数。
/// 2. **`_cardsToDraw == 0` 时参考根本不入队**（`:20-21`）⇒ 结果是 0 还是负数都等于"不抽"；
///    而折叠器自己的末尾 `Math.Max(0, ·)`（`:216`）保证结果不下溢。本函数**原样**返回折叠值
///    （`base <= 0` 时就是 `base`，`:137-138` 的原值返回），由调用方按 `max(0, ·)` 用。
/// 3. **手牌上限的裁剪不在这里**（`CardZoneEffects.cs:31-46`，在抽牌入口），所以本函数
///    **不碰** `max_hand_size` —— `turn.rs` 的注释（`turn.rs:429-431`）明确要求过这一点。
///
/// 本函数读的是**抽牌者自己**身上的状态（`CardTurnLifecycleEventHandlers.cs:25` 的
/// `combatant` 就是事件里的那个战斗员）。
///
/// `content == None` ⇒ 标准包路径：`status_catalog` 的两张修饰表里**没有** `TurnStartDraw`
/// 这一条管线（`status_catalog.rs:34-45` 的 `Pipeline` 只有 4 条且不含它），所以这里
/// **原值返回**是"标准包在这条管线上什么都不做"的准确表达，不是省略。
pub fn fold_turn_start_draw(
    statuses: &[StatusInstance],
    owner: &CombatantId,
    base: i32,
    content: Option<&Content<'_>>,
) -> Result<i32, ExecError> {
    // `:137-138`：非正数原样返回，管线不跑（账本也因此一笔没动）。
    if base <= 0 {
        return Ok(base);
    }
    let Some(content) = content else {
        return Ok(base);
    };
    let mut rows = [empty_row(); MAX_CANDIDATES];
    // `damage_kind: None` = `damageKind: null`（见函数头第 1 条）。
    let count = image_rows(
        content,
        statuses,
        status_bind::Pipeline::TurnStartDraw,
        None,
        &mut rows,
    )?;
    // 有镜像 ⇒ `Exact`（桥关闭），与 `damage_stage` 里同一条口径。
    fold(
        base,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        StatusMatch::Exact,
        NO_TURN_CARDS,
    )
}

/// §199：回合开始**补给的资源**（能量）—— [`fold_turn_start_draw`] 的同形兄弟。
///
/// ⚠️ 与抽牌那条一样，"非正数原样返回"：`base <= 0` 时管线不跑，账本一笔不动（那条契约在
/// `modifiers::apply` 的第一句里，这里只是把"要不要跑"的门放在同一个位置）。
pub fn fold_turn_start_energy(
    statuses: &[StatusInstance],
    owner: &CombatantId,
    base: i32,
    content: Option<&Content<'_>>,
) -> Result<i32, ExecError> {
    if base <= 0 {
        return Ok(base);
    }
    let Some(content) = content else {
        return Ok(base);
    };
    let mut rows = [empty_row(); MAX_CANDIDATES];
    let count = image_rows(
        content,
        statuses,
        status_bind::Pipeline::TurnStartEnergy,
        None,
        &mut rows,
    )?;
    fold(
        base,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        StatusMatch::Exact,
        NO_TURN_CARDS,
    )
}

/// 格挡的单阶段（没有 stage 轴，`M:§3.2`）。
fn block_stage<'a>(
    amount: i32,
    statuses: &[StatusInstance],
    owner: &CombatantId,
    content: Option<&'a Content<'a>>,
) -> Result<i32, ExecError> {
    let matching = StatusMatch::for_content(content);
    if let Some(content) = content {
        return image_block_stage(amount, statuses, owner, content, matching);
    }

    let mut rows = [empty_row(); MAX_CANDIDATES];
    let mut count = 0usize;
    for (index, entry) in status_catalog::block_modifiers().iter().enumerate() {
        let Some(slot) = rows.get_mut(count) else {
            return Err(ExecError::Modifier);
        };
        *slot = Row {
            priority: entry.spec_priority,
            status_id: entry.status_id,
            operation: catalog_operation(entry.op),
            magnitude: entry.percent,
            spec_index: index as u16,
        };
        count += 1;
    }
    fold(
        amount,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        matching,
        NO_TURN_CARDS,
    )
}

/// 镜像路径的格挡阶段：真的走 `modifiers::apply` + `BlockGain` 管线的候选表。
///
/// # 参考的形状（`PassiveModifiers.cs:257-269` + `DefensivePoolEffects.cs:11-105`）
///
/// * **单阶段**：`DeclarativePassiveBlockModifier` 只实现 `IBlockAmountModifier`，没有 stage 轴，
///   它把 `context.TargetCombatant`（= **获得格挡的那一方**）交给折叠器，管线 `BlockGain`。
///   ⇒ 本函数是 `block_stage` 的镜像分支，**读的是目标自己的状态**（`gain_block_node` 传进来的
///   就是目标的快照），不读出手者 —— 与本文件里"伤害有两个阶段"的形状不同，别照着抄。
/// * `damageKind: null`（`:267`）⇒ `:155` 的种类门整段跳过，`RestrictDamageKind` 在这条管线上
///   无意义（`passive_modifiers` 里 `doubt` 那类 `Direct` 门不会挡掉格挡）。
/// * `Apply` 的入口守卫 `amount <= 0 ⇒ 原值`（`:137-138`）由 [`fold`] 的同一条守卫表达。
///
/// # 本轮之前这里是"恒返原值"
///
/// 那时 `status_bind::Pipeline` 只有 3 种，`Block` 不在里面 ⇒ 镜像里**不可能**有一条 spec 进
/// 格挡管线，于是"脆弱（格挡 ×75%）"这个参考里存在的东西（`StandardCombatPackage.cs:318-321`）
/// 在内容侧表达不出来：`standard.frail` 施加得上，**但没有任何效果**。
/// 现在 `Pipeline::Block`（wire 串 `"BlockGain"`）接上了，内容那条 spec 会照参考折叠。
fn image_block_stage<'a>(
    amount: i32,
    statuses: &[StatusInstance],
    owner: &CombatantId,
    content: &'a Content<'a>,
    matching: StatusMatch,
) -> Result<i32, ExecError> {
    let mut rows = [empty_row(); MAX_CANDIDATES];
    // `damage_kind: None` = 参考的 `damageKind: null`（见函数头）。
    let count = image_rows(
        content,
        statuses,
        status_bind::Pipeline::Block,
        None,
        &mut rows,
    )?;
    fold(
        amount,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        matching,
        NO_TURN_CARDS,
    )
}

/// `DamageModifierEntry` → [`Row`]。
///
/// `AddStacks ⇒ AddPerStack(magnitude = 1)`，`MulPercent ⇒ ScalePercent(magnitude = percent)`
/// —— 这就是"力量 +1/层、虚弱 ×75、易伤 ×150"的**唯一**出处
/// （`PassiveModifiers.cs:206-213` 的四种运算由 `modifiers::apply` 执行）。
fn damage_row(entry: &DamageModifierEntry, index: usize) -> Row<'static> {
    Row {
        priority: entry.spec_priority,
        status_id: entry.status_id,
        operation: catalog_operation(entry.op),
        magnitude: entry.percent,
        spec_index: index as u16,
    }
}

/// 折叠一段管线：`statuses × rows` → 候选表 → `modifiers::apply`。
///
/// 关键一步是**候选表怎么构造**（对应 `PassiveModifiers.cs:140-177`）：
///
/// 1. 按**行**（≈ 参考里"某个状态定义上的一条 spec"）遍历，而不是按实例遍历 ——
///    因为参考先按定义 id **分组**再取 `Sum(Stacks)`（`:142-148`）；
/// 2. 只有**该定义在身的实例存在**时这一行才参与；层数是**全部实例之和**
///    （0 层也参与：`ScalePercent` 不读层数，`:210` —— 虚弱/易伤只有时长轴，层数恒 0）；
/// 3. `status_key` 把该行 id 的字节拷进池（排序键第二级），`spec_index` 是该行在表里的下标
///    （第三级），`priority` 是 `spec.Priority`（第一级）—— 三级合起来就是 `:179-185`；
/// 4. `once_per_action` / `once_per_turn` 恒 `false`：目录两张表里没有这样的 spec，镜像里
///    `OncePer*` 为真的 spec 会让 `status_bind::decode` 直接报
///    [`crate::status_bind::BindError::Unsupported`]（所以走到这里的镜像 spec 一定是 false）。
///
/// `matching` 决定"行 id 与实例定义 id 怎么算同一个状态"：有 `content` 时是
/// [`StatusMatch::Exact`]（桥关闭），否则 [`StatusMatch::Bridged`]。
///
/// `amount <= 0` 直接原样返回（`modifiers::apply` 契约 1，`:137-138`）。
fn fold<'a>(
    amount: i32,
    statuses: &[StatusInstance],
    rows: &[Row<'a>],
    owner: &CombatantId,
    matching: StatusMatch,
    turn_cards: i32,
) -> Result<i32, ExecError> {
    if amount <= 0 || rows.is_empty() {
        return Ok(amount);
    }

    // §216：`NO_TURN_CARDS`（-1）表示"这条管线里没有本回合牌数"。见到要它的 spec ⇒ 拒绝。
    // 只写在这一个折叠器里：五条管线都从这里过，所以"挂错管线"只有这一条出口。
    if turn_cards < 0
        && rows
            .iter()
            .any(|row| row.operation == Operation::ScalePercentPerCardPlayedThisTurn)
    {
        return Err(ExecError::Modifier);
    }

    let mut pool = [0u8; STATUS_ID_POOL_CAP];
    let mut pool_len = 0usize;
    let mut candidates = [NO_CANDIDATE; MAX_CANDIDATES];
    // `once_*` 全 false ⇒ 账本一笔都不会记，键值因此无关；仍然给出等长的键表（契约要求）。
    let claim_keys = [0u32; MAX_CANDIDATES];
    let mut count = 0usize;

    for row in rows {
        // 参考：`combatant.Statuses.GroupBy(s => s.DefinitionId)` 里**存在这个定义**才谈得上 spec。
        let Some(stacks) = total_stacks(statuses, row.status_id, matching) else {
            continue;
        };
        let status_key = intern(&mut pool, &mut pool_len, row.status_id)?;
        let Some(slot) = candidates.get_mut(count) else {
            return Err(ExecError::Modifier);
        };
        *slot = Candidate {
            priority: row.priority,
            status_key,
            spec_index: row.spec_index,
            stacks,
            cards_played_this_turn: turn_cards,
            operation: row.operation,
            magnitude: row.magnitude,
            once_per_action: false,
            once_per_turn: false,
        };
        count += 1;
    }

    if count == 0 {
        return Ok(amount);
    }

    let mut ledger = ClaimLedger::new();
    let applied = modifiers::apply(
        amount,
        candidates.get_mut(..count).unwrap_or(&mut []),
        pool.get(..pool_len).unwrap_or(&[]),
        &mut ledger,
        owner_key(owner),
        claim_keys.get(..count).unwrap_or(&[]),
    );
    Ok(applied.amount)
}

/// 某个修饰行的状态在身实例的**层数总和**；该定义不在身 ⇒ `None`（这一行不参与）。
///
/// 0 层的实例仍然返回 `Some(0)`：`ScalePercent` 不读层数（`PassiveModifiers.cs:210`），
/// 所以"层数为 0 的易伤仍然放大伤害"是**参考行为**，不是 bug。
///
/// `matching == Exact` 时**只认逐字节相等**（桥一刀不用）—— 见 [`StatusMatch`]。
fn total_stacks(
    statuses: &[StatusInstance],
    definition_id: &str,
    matching: StatusMatch,
) -> Option<i32> {
    let mut total: i64 = 0;
    let mut present = false;
    for status in statuses {
        let instance_id = status.definition_id.as_str();
        let hit = match matching {
            StatusMatch::Exact => instance_id == definition_id,
            StatusMatch::Bridged => modifier_applies_to(instance_id, definition_id),
        };
        if hit {
            present = true;
            total += i64::from(status.stacks);
        }
    }
    if !present {
        return None;
    }
    Some(if total > i64::from(i32::MAX) {
        i32::MAX
    } else if total < i64::from(i32::MIN) {
        i32::MIN
    } else {
        total as i32
    })
}

/// 修饰表行 id 与**实例**定义 id 是否同一个状态 —— 见模块头假设 A。
///
/// 规则只有两条：**逐字相等**，或者"行 id 是标准包命名（`standard.` 开头）且实例 id 是它的裸名"。
/// 只对 [`NAMESPACE_BRIDGE`] 里那 5 条生效（**不做通用前缀剥离**：`my_strength`、`strengths`
/// 都不匹配，单测钉住）。
///
/// ⚠️ 这个函数**只被 [`StatusMatch::Bridged`] 调用**，也就是只在 `ctx.content == None` 时生效；
/// 有镜像时匹配口径是逐字节相等（[`StatusMatch::Exact`]），本函数一次都不会被调到。
fn modifier_applies_to(instance_status_id: &str, table_status_id: &str) -> bool {
    if instance_status_id == table_status_id {
        return true;
    }
    for (prefixed, bare) in NAMESPACE_BRIDGE {
        if table_status_id == prefixed && instance_status_id == bare {
            return true;
        }
    }
    false
}

/// 把一段 id 字节拷进池，返回它在池里的 `(offset, len)`。池满 ⇒ [`ExecError::Modifier`]
/// （**可证不可达**：候选 ≤ [`MAX_CANDIDATES`] = 24 条，每条一个状态定义 id，而内核的 id 类型
/// 上限就是 [`ID_CAP`] = 40 B ⇒ 最坏 24 × 40 = 960 B = [`STATUS_ID_POOL_CAP`]；
/// 仍然绝不 panic、绝不截断）。
fn intern(pool: &mut [u8], pool_len: &mut usize, text: &str) -> Result<StatusKey, ExecError> {
    let bytes = text.as_bytes();
    let start = *pool_len;
    let end = start.checked_add(bytes.len()).ok_or(ExecError::Modifier)?;
    let Some(dest) = pool.get_mut(start..end) else {
        return Err(ExecError::Modifier);
    };
    dest.copy_from_slice(bytes);
    *pool_len = end;
    Ok(StatusKey {
        offset: u16::try_from(start).map_err(|_| ExecError::Modifier)?,
        len: u16::try_from(bytes.len()).map_err(|_| ExecError::Modifier)?,
    })
}

/// 账本键里的 `owner_key`（参考用 `combatant.Id.value` 字符串，`:194`）。
///
/// 目录两张表的每一行都是 `once_per_action == false && once_per_turn == false`，
/// 所以这个键**当前一个数都不会影响**；给一个稳定、无分配、逐字节确定的哈希（FNV-1a 32），
/// 是为了将来表里出现 `once_*` 行时键仍然可复现。
fn owner_key(id: &CombatantId) -> u32 {
    let mut hash: u32 = 0x811c_9dc5;
    for byte in id.as_str().as_bytes() {
        hash ^= u32::from(*byte);
        hash = hash.wrapping_mul(0x0100_0193);
    }
    hash
}

/// `standard.block` 池的 `(current, max, 是否存在)`。
fn block_pool(combatant: &Combatant) -> (i32, Option<i32>, bool) {
    let Ok(key) = DefensivePoolId::new(BLOCK_POOL_ID) else {
        return (0, None, false);
    };
    for pool in combatant.defensive_pools() {
        if pool.key == key {
            return (pool.pool.current, pool.pool.max, true);
        }
    }
    (0, None, false)
}

// =============================================================================================
// 测试
//
// 这些测试**读真实镜像**（`tools/contentc/out/content.core.rdcf`）。镜像不在仓库里（它是构建
// 产物），所以找不到就 panic 并打印路径与生成命令 —— 产物缺席时安静通过的测试等于没有测试。
// 期望值全部是实测/手算出来的，每条断言旁边都写着算法与出处。
//
// 需要"镜像里根本不存在的那种形状"时（非空 `ResultKey`、负金额、空 `Children`），就地**补丁**
// 镜像字节，与 `expr.rs` / `sel.rs` 的补丁测试同一套做法。
// =============================================================================================

#[cfg(test)]
mod tests {
    use super::*;
    // §161.5：`CardInstance` 不再是本模块的生产依赖（铸号搬进了 `state`），但测试要手搓卡。
    use crate::state::CardInstance;
    use crate::content::{Content, S_STR, S_STRO, S_TRM, S_TRW};
    use crate::ir::Ir;
    use crate::state::{CombatId, CombatantDefinitionId, TeamId};

    const CORE_IMAGE_REL: &str = "../../tools/contentc/out/content.core.rdcf";

    #[test]
    fn every_error_is_distinguishable() {
        // 这个项目里"安静地少做一半事"是最坏的失败模式（见模块头的硬规则），
        // 所以每种拒绝都要有自己的变体，不能合并。
        let all = [
            ExecError::UnsupportedNode,
            ExecError::ResultKeyNotSupported,
            ExecError::NoSource,
            ExecError::MissingCombatant,
            ExecError::StepLimit,
            ExecError::Modifier,
            // 新加的那个：内容说了一件我们还不懂的事（`status_bind::BindError`）。
            ExecError::Bind(BindError::Polarity),
        ];
        for (i, a) in all.iter().enumerate() {
            for (j, b) in all.iter().enumerate() {
                assert_eq!(i == j, a == b, "{a:?} 与 {b:?} 必须可分");
            }
        }
    }

    #[test]
    fn exec_stats_default_is_zero_so_tests_can_assert_work_happened() {
        let s = ExecStats::default();
        assert_eq!(s.nodes, 0);
        assert_eq!(s.effects, 0);
    }

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

    fn root_of<'a>(ir: &Ir<'a>, index: u32) -> NodeRef<'a> {
        ir.card_program_root(index)
            .unwrap_or_else(|e| panic!("CARD[{index}] 取不到程序根节点：{e:?}"))
    }

    /// 遍历所有 term，挑出判别串等于 `kind` 的那些 id（升序）。
    fn terms_of_kind(content: &Content<'_>, kind: &str) -> Vec<u16> {
        let mut out = Vec::new();
        for tid in 0..content.term_count() {
            let Ok(tid) = u16::try_from(tid) else { continue };
            if NodeRef::new(content, tid).kind_str() == Ok(kind) {
                out.push(tid);
            }
        }
        out
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

    /// §216：`Slow` 的运算只在**有本回合牌数**的管线（伤害）里有意义。格挡/抽牌/补能那三条
    /// 管线传 [`NO_TURN_CARDS`]（-1）⇒ 见到这条 spec **拒绝**，而不是安静地按恒等算。
    ///
    /// 成对：同一个 spec 给一个真牌数就正常算（1 张牌 ⇒ 11 点），证明拒绝的是"缺这个量"，
    /// 不是"这条运算本身"。
    #[test]
    fn a_slow_spec_on_a_pipeline_without_a_card_count_is_refused() {
        let mut row = empty_row();
        row.status_id = "standard.slow";
        row.operation = Operation::ScalePercentPerCardPlayedThisTurn;
        row.magnitude = 10;
        let statuses = [status("st_slow", "standard.slow", 1)];
        let rows = [row];
        assert_eq!(
            fold(10, &statuses, &rows, &cid("hero"), StatusMatch::Bridged, NO_TURN_CARDS),
            Err(ExecError::Modifier),
            "no card count in this pipeline => refuse, do not silently apply identity"
        );
        assert_eq!(
            fold(10, &statuses, &rows, &cid("hero"), StatusMatch::Bridged, 1),
            Ok(11),
            "one card played this turn: 10 * 110 / 100"
        );
    }

    fn status(instance: &str, definition: &str, stacks: i32) -> StatusInstance {
        StatusInstance::new(
            StatusInstanceId::new(instance).unwrap(),
            StatusDefinitionId::new(definition).unwrap(),
            StatusPolarity::Buff,
        )
        .with_stacks(stacks)
    }

    /// 存储序 `[hero, enemy_a, enemy_b]`；hero 70/70（E2E 的基准血量），两个敌人在 `enemy` 队
    /// —— `sel.allEnemies` 于是可测。
    fn arena() -> CombatState {
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);
        state.add_combatant(unit("hero", "player", 70, 70)).unwrap();
        state.add_combatant(unit("enemy_a", "enemy", 20, 20)).unwrap();
        state.add_combatant(unit("enemy_b", "enemy", 10, 10)).unwrap();
        state
    }

    fn give(state: &mut CombatState, who: &str, instance: StatusInstance) {
        state
            .combatant_mut(&cid(who))
            .unwrap()
            .push_status(instance)
            .unwrap();
    }

    fn give_block(state: &mut CombatState, who: &str, current: i32) {
        state
            .combatant_mut(&cid(who))
            .unwrap()
            .set_defensive_pool(DefensivePoolId::new(BLOCK_POOL_ID).unwrap(), current, None)
            .unwrap();
    }

    fn health(state: &CombatState, who: &str) -> i32 {
        state.combatant(&cid(who)).unwrap().health_current
    }

    fn block_of(state: &CombatState, who: &str) -> i32 {
        block_pool(state.combatant(&cid(who)).unwrap()).0
    }

    fn lifecycle(state: &CombatState, who: &str) -> CombatantLifecycleState {
        state.combatant(&cid(who)).unwrap().lifecycle_state
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

    fn status_count(state: &CombatState, who: &str) -> usize {
        state.combatant(&cid(who)).unwrap().statuses().len()
    }

    fn run_program(
        state: &mut CombatState,
        root: NodeRef<'_>,
        source: Option<&str>,
        event_target: Option<&str>,
        max_steps: u32,
    ) -> Result<ExecStats, ExecError> {
        let mut ctx = ExecContext::new(
            state,
            source.map(cid),
            event_target.map(cid),
            None,
            max_steps,
        );
        execute(root, &mut ctx)
    }

    /// 接上内容镜像的版本（状态元数据与修饰器都从 `STAT` 表读、命名空间桥关闭）。
    fn run_program_bound<'c>(
        state: &mut CombatState,
        content: &'c Content<'c>,
        root: NodeRef<'_>,
        source: Option<&str>,
        event_target: Option<&str>,
        max_steps: u32,
    ) -> Result<ExecStats, ExecError> {
        let mut ctx = ExecContext::new(
            state,
            source.map(cid),
            event_target.map(cid),
            None,
            max_steps,
        )
        .with_content(content);
        execute(root, &mut ctx)
    }

    fn run_card(
        state: &mut CombatState,
        ir: &Ir<'_>,
        card: u32,
        source: Option<&str>,
        event_target: Option<&str>,
    ) -> Result<ExecStats, ExecError> {
        let root = root_of(ir, card);
        run_program(state, root, source, event_target, 1024)
    }

    /// 接上内容镜像打一张牌。
    fn run_card_bound<'c>(
        state: &mut CombatState,
        content: &'c Content<'c>,
        ir: &Ir<'_>,
        card: u32,
        source: Option<&str>,
        event_target: Option<&str>,
    ) -> Result<ExecStats, ExecError> {
        let root = root_of(ir, card);
        run_program_bound(state, content, root, source, event_target, 1024)
    }

    /// 三个目标槽都能给全的版本（`conditional` 的对拍测试要动 `iteration_target`）。
    fn run_full(
        state: &mut CombatState,
        root: NodeRef<'_>,
        source: Option<&str>,
        event_target: Option<&str>,
        iteration_target: Option<&str>,
        max_steps: u32,
    ) -> Result<ExecStats, ExecError> {
        let mut ctx = ExecContext::new(
            state,
            source.map(cid),
            event_target.map(cid),
            iteration_target.map(cid),
            max_steps,
        );
        execute(root, &mut ctx)
    }

    /// 只跑伤害管线（不经节点）。
    fn deal(state: &mut CombatState, target: &str, base: i32, ignores_block: bool) -> (i32, i32) {
        let mut ctx = ExecContext::new(
            state,
            Some(cid("hero")),
            Some(cid(target)),
            None,
            1024,
        );
        resolve_damage(&mut ctx, &cid(target), base, ignores_block).unwrap()
    }

    /// §210: damage **through the real path** -- fold, drain, and the host's event dispatch.
    ///
    /// The two hooks that used to be hardcoded inside `resolve_damage_of_kind` (Intangible's clamp and
    /// Plated Armor's decrement) are content now: the clamp runs in the modifier fold (so no host is
    /// needed), but the decrement is a `DamageTaken` trigger and only fires when the **event queue**
    /// is drained. A test that calls `deal` alone would still see the old synchronous behaviour --
    /// which is exactly the trap (`deal` has no content at all).
    fn deal_dispatched(
        state: &mut CombatState,
        content: &Content<'_>,
        target: &str,
        base: i32,
        ignores_block: bool,
        kind: crate::status_bind::DamageKind,
    ) {
        let mut ctx = ExecContext::new(
            state,
            Some(cid("hero")),
            Some(cid(target)),
            None,
            1024,
        )
        .with_content(content);
        resolve_damage_of_kind(&mut ctx, &cid(target), base, ignores_block, kind).unwrap();
        drain(state, Some(content), None).unwrap();
        let mut host = crate::host::Host::new(content);
        host.resolve_pending_queues_with(state, crate::host::QueueLimits::DEFAULT)
            .expect("the host dispatches DamageTaken");
    }

    /// 只跑伤害管线，但**接上内容镜像**（状态元数据走 `status_bind`、桥关闭）。
    fn deal_bound<'c>(
        state: &mut CombatState,
        content: &'c Content<'c>,
        target: &str,
        base: i32,
        ignores_block: bool,
    ) -> (i32, i32) {
        let mut ctx = ExecContext::new(
            state,
            Some(cid("hero")),
            Some(cid(target)),
            None,
            1024,
        )
        .with_content(content);
        resolve_damage(&mut ctx, &cid(target), base, ignores_block).unwrap()
    }

    // ---------------------------------------------------------------- 镜像补丁（2 字节）

    /// 往某个战斗员的某个牌区里放一张**有定义 id** 的卡（`forEachCardInZone` 的 `TagFilter`
    /// 查的是**定义**上的 tag，所以定义 id 必须是镜像 `CARD` 表里有的那 62 个之一）。
    fn give_card_def(
        state: &mut CombatState,
        who: &str,
        zone: CardZone,
        instance: &str,
        definition: &str,
    ) {
        let card = CardInstance::new(
            CardInstanceId::new(instance).unwrap(),
            CardDefinitionId::new(definition).unwrap(),
        );
        state.push_card(&cid(who), zone, card).unwrap();
    }

    /// 状态的**逐字节**指纹：`snapshot::write_hash_input` 写出来的就是哈希的输入文本
    /// （`snapshot.rs` 模块头）。用它断言"什么都没动"比挑几个字段看强得多 ——
    /// 牌区里的**堆内顺序**也在里面（`write_card_zones`）。
    fn state_text(state: &CombatState) -> Vec<u8> {
        let mut buf = [0u8; 1 << 16];
        let mut w = crate::writer::TextWriter::new(&mut buf);
        crate::snapshot::write_hash_input(&mut w, state);
        assert!(!w.overflowed(), "指纹缓冲装不下（本状态太大了，调大缓冲）");
        w.as_str().as_bytes().to_vec()
    }

    /// op 6 = `_wrap_lower`（实测 54 条）。用它当一个**真的**非空 `CardDefinitionId`
    /// 会编码成的形状（包装串），证明"非空 DefinitionFilter"那条拒绝是活的。
    fn wrap_lower_term(content: &Content<'_>) -> u16 {
        for tid in 0..content.term_count() {
            let Ok(tid) = u16::try_from(tid) else { continue };
            let Some(term) = content.term(tid) else { continue };
            if term.op == 6 {
                return tid;
            }
        }
        panic!("镜像里没有 `_wrap_lower`（op 6）term");
    }

    /// 一个 `const` 表达式 term（值类别是 int，喂给 `cardInstance` 位置必须被拒）。
    fn a_const_term(content: &Content<'_>) -> u16 {
        let mut ids = terms_of_kind(content, "const");
        assert!(!ids.is_empty(), "镜像里必须有 `const` term");
        ids.remove(0)
    }

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
        let slot = blob
            .get_mut(at..at + 2)
            .unwrap_or_else(|| panic!("patch16 越界：{at}"));
        slot.copy_from_slice(&value.to_le_bytes());
    }

    /// 把镜像串池里的一条串**就地改名**（只允许变短），返回它的串号。
    ///
    /// 串池的形状（`content.rs:211-228` 的 `string_at`，与 `tools/contentc/reader.py` 同规则）：
    /// `S_STR` 是一段 NUL 结尾的字节池，`S_STRO` 是一张 `u32` 偏移表，第 `i` 条串 =
    /// `[STRO[i-1], STRO[i]-1)` —— **长度是偏移表的差，不是 NUL**。所以"改名成更短的串"是两件事：
    /// 写前 `new.len()` 个字节、把**结束偏移**往前挪。
    ///
    /// ⚠️ 代价写在明处：紧跟在后面的那条串会吞掉剩下的字节（它的起点就是被挪走的那个偏移）。
    /// `DamageReceived` 后面是 `DamageTaken`，本文件**一个字节都不读它**；要读就得整池重排，
    /// 那已经超出"补丁测试"的份额。**只用它造镜像里不存在的形状**，别拿它当通用工具。
    fn rename_string(blob: &mut [u8], old: &str, new: &str) -> u16 {
        assert!(new.len() < old.len(), "只支持变短：{old} → {new}");
        let u32_at = |data: &[u8], at: usize| {
            u32::from_le_bytes([data[at], data[at + 1], data[at + 2], data[at + 3]])
        };
        let (id, start, end, pool_at, table_at) = {
            let content = parse(blob);
            let pool = content.section(S_STR).expect("STR 段（串字节池）");
            let table = content.section(S_STRO).expect("STRO 段（偏移表）");
            let id = (1..=content.string_count())
                .map(|i| i as u16)
                .find(|i| content.string(*i) == Some(old))
                .unwrap_or_else(|| panic!("镜像串池里没有 `{old}`"));
            let start = u32_at(table.data, (id as usize - 1) * 4) as usize;
            let end = u32_at(table.data, id as usize * 4) as usize;
            (
                id,
                start,
                end,
                pool.offset as usize,
                table.offset as usize,
            )
        };
        // 一条串在池里必须是 `old` + 恰好一个 NUL 字节（否则下面的算术就推不动了 ⇒ 响亮失败）。
        assert_eq!(
            end - start,
            old.len() + 1,
            "串池里的 `{old}` 应当是 {} 字节 + NUL，实际 [{} , {})",
            old.len(),
            start,
            end
        );
        blob[pool_at + start..pool_at + start + new.len()].copy_from_slice(new.as_bytes());
        blob[pool_at + start + new.len()] = 0;
        let new_end = (start + new.len() + 1) as u32;
        let at = table_at + id as usize * 4;
        let slot = blob
            .get_mut(at..at + 4)
            .unwrap_or_else(|| panic!("偏移表越界：{at}"));
        slot.copy_from_slice(&new_end.to_le_bytes());
        id
    }

    // =========================================================================================
    // 端到端 1：一张真牌打出真伤害
    // =========================================================================================

    #[test]
    fn e2e_1_paper_cut_deals_six_to_the_event_target() {
        // CARD[0] paper_cut = node.dealDamage{Amount: const 6, TargetSelector: sel.eventTarget}
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();

        let stats = run_card(&mut state, &ir, 0, Some("hero"), Some("hero"))
            .expect("paper_cut 必须跑得通");
        assert_eq!(health(&state, "hero"), 64, "70 - 6 = 64");
        assert_eq!(stats.effects, 1);
        assert_eq!(stats.nodes, 1, "paper_cut 的程序只有根这一个节点");
        assert_eq!(health(&state, "enemy_a"), 20, "别的单位一点都没掉");
        assert_eq!(health(&state, "enemy_b"), 10);
    }

    #[test]
    fn e2e_1b_paper_cut_on_an_enemy_uses_the_same_six() {
        // 同一个程序打到敌人身上也是 6 —— 证明那个 6 不是从 hero 身上凑出来的。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        let stats = run_card(&mut state, &ir, 0, Some("hero"), Some("enemy_a")).unwrap();
        assert_eq!(health(&state, "enemy_a"), 14);
        assert_eq!(stats.effects, 1);
    }

    // =========================================================================================
    // 端到端 2/3：vulnerable ×150 与 strength +3 —— **同值不同因**，分开钉
    // =========================================================================================

    #[test]
    fn e2e_2_vulnerable_two_stacks_multiplies_by_150() {
        // 6 * 150 / 100 = 9 ⇒ 70 - 9 = 61
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_v1", "vulnerable", 2));

        let stats = run_card(&mut state, &ir, 0, Some("hero"), Some("hero")).unwrap();
        assert_eq!(health(&state, "hero"), 61, "6*150/100 = 9");
        assert_eq!(stats.effects, 1);
        // 管线本身也报 9（与血量两条独立来源互证）。
        let mut state = arena();
        give(&mut state, "hero", status("st_v1", "vulnerable", 2));
        assert_eq!(deal(&mut state, "hero", 6, false), (0, 9));
    }

    #[test]
    fn e2e_3_strength_three_adds_three() {
        // 6 + 3 = 9 ⇒ 70 - 9 = 61（与 #2 的数值相同）
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_s1", "strength", 3));

        let stats = run_card(&mut state, &ir, 0, Some("hero"), Some("hero")).unwrap();
        assert_eq!(health(&state, "hero"), 61, "6+3 = 9");
        assert_eq!(stats.effects, 1);
        let mut state = arena();
        give(&mut state, "hero", status("st_s1", "strength", 3));
        assert_eq!(deal(&mut state, "hero", 6, false), (0, 9));
    }

    #[test]
    fn e2e_2_3_same_number_different_cause_the_stage_split_is_what_tells_them_apart() {
        // ★ "同值不同因"的分开钉法：把状态放到**错的那一侧**，数字必须回到 6。
        //
        // 易伤只在 Target 阶段被读（`DamageReceived`，`PassiveModifiers.cs:229-231`）：
        // 放在**出手者**身上 ⇒ Target 阶段读承受者，读不到 ⇒ 6 点。
        // 力量只在 Source 阶段被读（`DamageDealt`）：放在**承受者**身上 ⇒ Source 阶段读出手者，
        // 读不到 ⇒ 也是 6 点。
        //
        // 如果哪天有人把两个阶段合起来读"场上所有状态"，这两条会同时变成 9 —— 立刻红灯。
        // 这两条与 #2/#3 合起来，才是"9 这个数从哪来"的完整证据。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);

        let mut vulnerable_on_source = arena();
        give(
            &mut vulnerable_on_source,
            "hero",
            status("st_v2", "vulnerable", 2),
        );
        run_card(
            &mut vulnerable_on_source,
            &ir,
            0,
            Some("hero"),
            Some("enemy_a"),
        )
        .unwrap();
        assert_eq!(
            health(&vulnerable_on_source, "enemy_a"),
            14,
            "易伤在出手者身上 ⇒ 目标阶段读不到 ⇒ 6 点"
        );

        let mut strength_on_target = arena();
        give(&mut strength_on_target, "enemy_a", status("st_s2", "strength", 3));
        run_card(&mut strength_on_target, &ir, 0, Some("hero"), Some("enemy_a")).unwrap();
        assert_eq!(
            health(&strength_on_target, "enemy_a"),
            14,
            "力量在承受者身上 ⇒ 来源阶段读不到 ⇒ 6 点"
        );
    }

    #[test]
    fn damage_is_a_function_of_the_catalog_rows_only() {
        // 逐条走 `damage_modifiers()` 的公开数字，手算与管线对拍（含"层数为 0 也生效"）。
        for (definition, stacks, expected_lost) in [
            ("strength", 1, 7),
            ("strength", 2, 8),
            ("strength", 4, 10),
            // 易伤是 ScalePercent，**不读层数**（`:210`）：150 只有一档。
            ("vulnerable", 1, 9),
            ("vulnerable", 5, 9),
            ("vulnerable", 0, 9),
        ] {
            let mut state = arena();
            // 只有 Source 阶段读出手者、Target 阶段读承受者，所以两边各放一份，
            // 无论这次测的是力量还是易伤都恰好读到一份。
            give(&mut state, "hero", status("st_a", definition, stacks));
            give(&mut state, "enemy_a", status("st_b", definition, stacks));
            let mut ctx = ExecContext::new(
                &mut state,
                Some(cid("hero")),
                Some(cid("enemy_a")),
                None,
                1024,
            );
            let (_blocked, lost) = resolve_damage(&mut ctx, &cid("enemy_a"), 6, false).unwrap();
            assert_eq!(lost, expected_lost, "{definition} {stacks} 层");
        }
    }

    // =========================================================================================
    // 端到端 4：strength + weak 走的是乘法管线（截断回 6，不是 8）
    // =========================================================================================

    #[test]
    fn e2e_4_strength_two_and_weak_multiply_back_down_to_six() {
        // (6 + 2) * 75 / 100 = 6 ⇒ 70 - 6 = 64
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_s3", "strength", 2));
        // 标准包的虚弱只有时长轴 ⇒ 层数恒 0；实例在场就够（`ScalePercent` 不读层数）。
        give(&mut state, "hero", status("st_w1", "weak", 0));

        let stats = run_card(&mut state, &ir, 0, Some("hero"), Some("hero")).unwrap();
        assert_eq!(health(&state, "hero"), 64, "(6+2)*75/100 = 6");
        assert_eq!(stats.effects, 1);
    }

    #[test]
    fn weak_alone_truncates_to_four_so_the_multiplication_really_ran() {
        // 6 * 75 / 100 = 4（向零截断）⇒ 70 - 4 = 66。
        // 与上一条合起来才证明"乘法真的在跑"，而不是恰好回到 6 的巧合。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_w2", "weak", 0));
        run_card(&mut state, &ir, 0, Some("hero"), Some("hero")).unwrap();
        assert_eq!(health(&state, "hero"), 66, "6*75/100 = 4");
    }

    #[test]
    fn e2e_4b_three_piece_vector_from_the_spec_is_exact() {
        // 规格 §4.2 的权威向量：base 7 + 力量 3 + 虚弱 + 易伤 ⇒
        // (7+3)=10 → *75/100=7 → *150/100=10。**加法先于乘法**的判据：
        // 错序（先乘再加）会得 12。
        let mut state = arena();
        give(&mut state, "hero", status("st_s4", "strength", 3));
        give(&mut state, "hero", status("st_w4", "weak", 0));
        give(&mut state, "enemy_a", status("st_v4", "vulnerable", 1));
        let mut ctx = ExecContext::new(&mut state, Some(cid("hero")), Some(cid("enemy_a")), None, 1024);
        let (blocked, lost) = resolve_damage(&mut ctx, &cid("enemy_a"), 7, false).unwrap();
        assert_eq!((blocked, lost), (0, 10), "(7+3)=10 → 7 → 10");

        // 同一个向量换成 base 6 + 力量 2：8 → 6 → 9（与 `VulnerableStatusTests` 一致）。
        let mut state = arena();
        give(&mut state, "hero", status("st_s5", "strength", 2));
        give(&mut state, "hero", status("st_w5", "weak", 0));
        give(&mut state, "enemy_a", status("st_v5", "vulnerable", 1));
        let mut ctx = ExecContext::new(&mut state, Some(cid("hero")), Some(cid("enemy_a")), None, 1024);
        let (blocked, lost) = resolve_damage(&mut ctx, &cid("enemy_a"), 6, false).unwrap();
        assert_eq!((blocked, lost), (0, 9), "(6+2)=8 → 6 → 9");
    }

    // =========================================================================================
    // `DamageKind`：同一条管线、两套门（`PassiveModifiers.cs:154-156`）
    //
    // 这一段是 DoT 的**唯一**正确性依据：参考里"DoT 不吃力量/虚弱/易伤"不是另开一条管线，
    // 而是每条 spec 自己的 `RestrictDamageKind` 门把它们挡掉的。所以两个方向都要测：
    // 带 `Direct` 门的 spec **不得**作用于 Dot，不带门（null）的 spec **必须**作用于 Dot。
    // =========================================================================================

    /// 只跑伤害管线，但**指定种类**（[`resolve_damage_of_kind`]，DoT 的唯一入口）。
    fn deal_kind(
        state: &mut CombatState,
        source: &str,
        target: &str,
        base: i32,
        kind: BindDamageKind,
    ) -> (i32, i32) {
        let mut ctx = ExecContext::new(state, Some(cid(source)), Some(cid(target)), None, 1024);
        resolve_damage_of_kind(&mut ctx, &cid(target), base, false, kind).unwrap()
    }

    /// 同上，接内容镜像（状态元数据走 `status_bind`）。
    fn deal_kind_bound<'c>(
        state: &mut CombatState,
        content: &'c Content<'c>,
        source: &str,
        target: &str,
        base: i32,
        kind: BindDamageKind,
    ) -> (i32, i32) {
        let mut ctx = ExecContext::new(state, Some(cid(source)), Some(cid(target)), None, 1024)
            .with_content(content);
        resolve_damage_of_kind(&mut ctx, &cid(target), base, false, kind).unwrap()
    }

    #[test]
    fn the_damage_kind_gate_has_two_directions() {
        // 方向一：`RestrictDamageKind = Direct` 的 spec **不能**作用于别的种类。
        // 这是"标准包三行 / 镜像 5 条 spec 对 DoT 整表不参与"的全部机制。
        for kind in [BindDamageKind::Dot, BindDamageKind::Reflected] {
            assert!(
                !damage_kind_passes(Some(BindDamageKind::Direct), kind),
                "Direct 门的 spec 不许作用于 {kind:?}"
            );
        }
        // 方向二：**没有** restrict（null）的 spec **必须**仍然作用于 Dot。
        // 依据是参考那一行的形状：`damageKind is { } kind && spec.RestrictDamageKind is { } restrict
        // && restrict != kind`（`PassiveModifiers.cs:155`，【验证】：我读过那一行）——
        // 第一个合取项为假时整条 `continue` 不成立，所以 null 是"不限种类"，
        // 不是"默认 Direct"。写成后者的后果是：内容写一条不限种类的 `ScalePercent 50`，
        // 它对 Direct 生效却对 DoT 静默失效。
        for kind in [
            BindDamageKind::Direct,
            BindDamageKind::Dot,
            BindDamageKind::Reflected,
        ] {
            assert!(
                damage_kind_passes(None, kind),
                "null 门的 spec 必须作用于 {kind:?}"
            );
        }
        // 同类放行、异类拒绝 —— 三个种类逐个过一遍（只测 Direct 会漏掉"Dot 门自己也认 Dot"）。
        for restrict in [
            BindDamageKind::Direct,
            BindDamageKind::Dot,
            BindDamageKind::Reflected,
        ] {
            for kind in [
                BindDamageKind::Direct,
                BindDamageKind::Dot,
                BindDamageKind::Reflected,
            ] {
                assert_eq!(
                    damage_kind_passes(Some(restrict), kind),
                    restrict == kind,
                    "{restrict:?} 门的 spec 对 {kind:?}"
                );
            }
        }
    }

    #[test]
    fn dot_slips_past_the_standard_pack_rows_that_direct_hits_do_not() {
        // 标准包路径（`content == None`）：三行的 `RestrictDamageKind` 都是 `Direct`
        // （`status_catalog.rs:119-124` 的 `DAMAGE_MODIFIER_DAMAGE_KINDS`，`:168` 要求调用方先过门）。
        // 力量 3 在出手者身上、易伤在承受者身上 —— 同一个基数、同一条管线，只换种类。
        let setup = |state: &mut CombatState| {
            give(state, "hero", status("st_s", "standard.strength", 3));
            give(state, "enemy_a", status("st_v", "standard.vulnerable", 0));
        };

        let mut direct = arena();
        setup(&mut direct);
        // (5+3)=8 → *150/100=12
        assert_eq!(
            deal_kind(&mut direct, "hero", "enemy_a", 5, BindDamageKind::Direct),
            (0, 12),
            "Direct：力量与易伤都参与"
        );

        let mut dot = arena();
        setup(&mut dot);
        // 同样的两个状态在身，只是种类换成 Dot ⇒ 被各自的 `Direct` 门挡掉 ⇒ 原值 5。
        // ⚠️ **这条断言就是"复用 Direct 管线"会红的地方**（那里会给 12）。
        assert_eq!(
            deal_kind(&mut dot, "hero", "enemy_a", 5, BindDamageKind::Dot),
            (0, 5),
            "Dot：标准包三行整表不参与"
        );
    }

    #[test]
    fn dot_slips_past_the_image_direct_only_specs_too() {
        // 镜像路径（`content == Some`）：5 条 spec 带 `PassiveModifiers`，其中 4 条
        // `RestrictDamageKind = "Direct"`（`strength` / `doubt` / `signature_pending` / `seal_intact`），
        // `panic` 那条是 null（管线是 TurnStartDraw，与伤害无关）。
        // 这里用 `strength`（Source 阶段）与 `signature_pending`（Target 阶段，×75）。
        let blob = core_image();
        let content = parse(&blob);
        let setup = |state: &mut CombatState| {
            give(state, "hero", status("st_str", "strength", 3));
            give(state, "enemy_a", status("st_sig", "signature_pending", 0));
        };

        let mut direct = arena();
        setup(&mut direct);
        // (5+3)=8 → *75/100=6
        assert_eq!(
            deal_kind_bound(&mut direct, &content, "hero", "enemy_a", 5, BindDamageKind::Direct),
            (0, 6)
        );

        let mut dot = arena();
        setup(&mut dot);
        assert_eq!(
            deal_kind_bound(&mut dot, &content, "hero", "enemy_a", 5, BindDamageKind::Dot),
            (0, 5),
            "同一个镜像、同一个基数，Dot 只吃不带门（或门=Dot）的 spec"
        );
    }

    #[test]
    fn resolve_damage_is_exactly_resolve_damage_of_kind_direct() {
        // 老签名必须是新函数的一个**转发**，不是一个近似：同样的状态、同样的基数，
        // 两条路的掉血量逐位相同（老调用点因此一行不用改，老测试也仍然是有效的）。
        let blob = core_image();
        let content = parse(&blob);
        let setup = |state: &mut CombatState| {
            give(state, "hero", status("st_str", "strength", 3));
            give(state, "enemy_a", status("st_sig", "signature_pending", 0));
        };
        let mut legacy = arena();
        setup(&mut legacy);
        let old = deal_bound(&mut legacy, &content, "enemy_a", 5, false);

        let mut explicit = arena();
        setup(&mut explicit);
        let new = deal_kind_bound(&mut explicit, &content, "hero", "enemy_a", 5, BindDamageKind::Direct);

        assert_eq!(old, new);
        assert_eq!(old, (0, 6), "非平凡：管线真的跑了（5 → 8 → 6）");
    }

    // =========================================================================================
    // `TurnStartDraw` 管线（`panic` 的"每回合少抽 1"）
    // =========================================================================================

    #[test]
    fn panic_takes_cards_away_from_the_turn_start_draw() {
        let blob = core_image();
        let content = parse(&blob);

        // `panic 2` ⇒ 5 - 2 = 3（`PassiveModifiers.cs:206-213` 的 `AddPerStack -1`）。
        let panicked = [status("st_p2", "panic", 2)];
        assert_eq!(
            fold_turn_start_draw(&panicked, &cid("hero"), 5, Some(&content)),
            Ok(3)
        );

        // 每层 -1，逐层线性（不是"有就减 1"）。
        let one = [status("st_p1", "panic", 1)];
        assert_eq!(
            fold_turn_start_draw(&one, &cid("hero"), 5, Some(&content)),
            Ok(4)
        );

        // 减到负数 ⇒ 折叠器末尾 `Math.Max(0, ·)`（`:216`）兜住。
        let deep = [status("st_p7", "panic", 7)];
        assert_eq!(
            fold_turn_start_draw(&deep, &cid("hero"), 5, Some(&content)),
            Ok(0)
        );

        // 无事可做的那一面：没有 `panic` ⇒ 原值；`base = 0` ⇒ 原值且管线不跑
        // （`:137-138`）；`content == None` ⇒ 标准包没有 TurnStartDraw 管线 ⇒ 原值。
        let none: [StatusInstance; 0] = [];
        assert_eq!(
            fold_turn_start_draw(&none, &cid("hero"), 5, Some(&content)),
            Ok(5)
        );
        assert_eq!(
            fold_turn_start_draw(&panicked, &cid("hero"), 0, Some(&content)),
            Ok(0)
        );
        assert_eq!(fold_turn_start_draw(&panicked, &cid("hero"), 5, None), Ok(5));

        // `priority` 不参与（镜像里只有一条 spec）—— 但 `signature_pending` 之类
        // 别的管线上的 spec 必须被管线门挡掉，否则"少抽 2 张"会变成别的东西。
        let wrong_pipeline = [status("st_sig", "signature_pending", 4)];
        assert_eq!(
            fold_turn_start_draw(&wrong_pipeline, &cid("hero"), 5, Some(&content)),
            Ok(5),
            "DamageReceived 的 spec 不许影响抽牌数"
        );
    }

    // =========================================================================================
    // 端到端 5/6：格挡与真伤
    // =========================================================================================

    #[test]
    fn e2e_5_block_absorbs_five_and_the_rest_hits_health() {
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);

        // 直接走管线。
        let mut state = arena();
        give_block(&mut state, "hero", 5);
        assert_eq!(deal(&mut state, "hero", 6, false), (5, 1));
        assert_eq!(block_of(&state, "hero"), 0, "5 点格挡被吃光");
        assert_eq!(health(&state, "hero"), 69);

        // 同一张牌走完整执行路径：节点层不许再夹一次。
        let mut state = arena();
        give_block(&mut state, "hero", 5);
        run_card(&mut state, &ir, 0, Some("hero"), Some("hero")).unwrap();
        assert_eq!(block_of(&state, "hero"), 0);
        assert_eq!(health(&state, "hero"), 69);
    }

    #[test]
    fn e2e_6_ignores_block_deals_full_damage_and_leaves_the_pool_alone() {
        let mut state = arena();
        give_block(&mut state, "hero", 5);
        assert_eq!(deal(&mut state, "hero", 6, true), (0, 6), "真伤全额落地");
        assert_eq!(block_of(&state, "hero"), 5, "真伤**不动**格挡池（`DamageEffects.cs:80`）");
        assert_eq!(health(&state, "hero"), 64);
    }

    #[test]
    fn a_block_pool_keeps_its_max_and_overkill_is_capped() {
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);

        // `max` 保留：`GainBlock`/吸收只该改 current。
        let mut state = arena();
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .set_defensive_pool(DefensivePoolId::new(BLOCK_POOL_ID).unwrap(), 3, Some(10))
            .unwrap();
        run_card(&mut state, &ir, 0, Some("hero"), Some("hero")).unwrap();
        let pool = state
            .combatant(&cid("hero"))
            .unwrap()
            .defensive_pools()
            .iter()
            .find(|p| p.key.as_str() == BLOCK_POOL_ID)
            .copied()
            .expect("池必须还在");
        assert_eq!(pool.pool.current, 0, "3 点全被吃掉");
        assert_eq!(pool.pool.max, Some(10), "max 原样保留");
        assert_eq!(health(&state, "hero"), 67, "6-3 = 3 点掉血");

        // overkill：5 点血吃 6 点 ⇒ 血量 0、`health_lost = 5`（**不会**超过扣血前的血量）。
        let mut state = arena();
        state.combatant_mut(&cid("hero")).unwrap().health_current = 5;
        assert_eq!(deal(&mut state, "hero", 6, false), (0, 5), "overkill 不进 HealthLost");
        assert_eq!(health(&state, "hero"), 0, "血量不许为负");
        assert_eq!(
            lifecycle(&state, "hero"),
            CombatantLifecycleState::Downed,
            "扣到 0 的单位要转 Downed"
        );
    }

    // =========================================================================================
    // 端到端 7：格挡牌 + 格挡管线
    // =========================================================================================

    #[test]
    fn e2e_7_cower_behind_a_desk_gains_five_block() {
        // CARD[2] = node.gainBlock{Amount: const 5, TargetSelector: sel.source}
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();

        let stats = run_card(&mut state, &ir, 2, Some("hero"), None).unwrap();
        assert_eq!(block_of(&state, "hero"), 5);
        assert_eq!(stats.effects, 1);
        assert_eq!(stats.nodes, 1);
    }

    #[test]
    fn e2e_7b_dexterity_scales_the_gained_block_through_the_block_pipeline() {
        // `block_modifiers()` 的 `standard.dexterity` 行 = AddPerStack / 1 / 100 ⇒ 5+2 = 7
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_d1", "dexterity", 2));
        run_card(&mut state, &ir, 2, Some("hero"), None).unwrap();
        assert_eq!(block_of(&state, "hero"), 7, "5+2");
    }

    #[test]
    fn e2e_7c_frail_truncates_the_gained_block() {
        // `standard.frail` = MulPercent / 75 / 200 ⇒ 5*75/100 = 3（向零截断）
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_f1", "frail", 0));
        run_card(&mut state, &ir, 2, Some("hero"), None).unwrap();
        assert_eq!(block_of(&state, "hero"), 3, "5*75/100 = 3");
    }

    #[test]
    fn e2e_7d_block_stacking_adds_and_caps_at_int_max() {
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        give_block(&mut state, "hero", 10);
        run_card(&mut state, &ir, 2, Some("hero"), None).unwrap();
        assert_eq!(block_of(&state, "hero"), 15, "10 + 5");

        let mut state = arena();
        give_block(&mut state, "hero", i32::MAX);
        run_card(&mut state, &ir, 2, Some("hero"), None).unwrap();
        assert_eq!(block_of(&state, "hero"), i32::MAX, "夹到 int.MaxValue（`:82`）");
    }

    #[test]
    fn e2e_7e_a_block_gain_spec_in_the_image_truncates_the_block_like_frail() {
        // ★ `Pipeline::Block`（wire 串 `"BlockGain"`）的**真实镜像路径**测试。
        //
        // 参考的"脆弱"就是这条管线：`BlockGain / ScalePercent 75 / Priority 200`
        // （`StandardCombatPackage.cs:318-321`；数值对着 `BlockAmountModifierTests.cs:104-130`：
        // 基础 5 ⇒ **3**）。本内容镜像里**一格 `BlockGain` 都没有**（5 条 spec 全在别的管线上），
        // 所以这里按本文件的既定做法**就地补丁镜像字节**：把串池里的 `DamageReceived`
        // 改名成 `BlockGain`，于是 `signature_pending` 那条（`ScalePercent 75`）成为"脆弱"的等价物。
        //
        // 走的全是真东西：真 `STAT` 表 + 真串池 + 真 `image_rows` + 真 `modifiers::apply`
        // + 真 `gainBlock` 节点（CARD[2] = gainBlock 5 sel.source）。
        let mut blob = core_image();
        let id = rename_string(&mut blob, "DamageReceived", "BlockGain");
        let content = parse(&blob);
        assert_eq!(
            content.string(id),
            Some("BlockGain"),
            "补丁之后那条串必须解出参考的 wire 名"
        );
        let ir = Ir::new(&content);

        // 一、有"脆弱" ⇒ 5 × 75 / 100 = 3（**向零截断**，不是四舍五入）。
        let mut state = arena();
        give(&mut state, "hero", status("st_frail", "signature_pending", 0));
        run_card_bound(&mut state, &content, &ir, 2, Some("hero"), None).unwrap();
        assert_eq!(block_of(&state, "hero"), 3, "5*75/100 = 3.75 ⇒ 3");

        // 二、成对：同一个补丁镜像、同一张牌，**没有那条 spec** ⇒ 一点都不缩。
        let mut state = arena();
        run_card_bound(&mut state, &content, &ir, 2, Some("hero"), None).unwrap();
        assert_eq!(block_of(&state, "hero"), 5, "原值");

        // 三、管线门：别的管线上有 spec 也不许碰格挡
        //     （`panic` = TurnStartDraw / `doubt` = DamageDealt / `paperwork` = 空）。
        for other in ["panic", "doubt", "paperwork"] {
            let mut state = arena();
            give(&mut state, "hero", status("st_other", other, 3));
            run_card_bound(&mut state, &content, &ir, 2, Some("hero"), None).unwrap();
            assert_eq!(
                block_of(&state, "hero"),
                5,
                "{other} 不在 BlockGain 管线上 ⇒ 格挡不缩"
            );
        }

        // 四、"向下截断"要能从**非整数倍**上看出来（2.25 ⇒ 2、5.25 ⇒ 5），而不是只测 3.75 那一格。
        let statuses = [status("st_frail", "signature_pending", 0)];
        for (base, expect) in [(7, 5), (5, 3), (3, 2), (1, 0), (0, 0)] {
            assert_eq!(
                block_stage(base, &statuses, &cid("hero"), Some(&content)),
                Ok(expect),
                "{base}*75/100 向零截断"
            );
        }
        // 同一组基数、没有那条 spec ⇒ 原值（逐格成对，而不是"抽一个代表"）。
        let none: [StatusInstance; 0] = [];
        for base in [7, 5, 3, 1] {
            assert_eq!(
                block_stage(base, &none, &cid("hero"), Some(&content)),
                Ok(base)
            );
        }

        // 五、读者最关心的那一条：补丁没白打 —— 这条 spec 的管线**确实**解成了 `Block`。
        let mut buffer = [EMPTY_PASSIVE_MODIFIER; status_bind::MAX_MODIFIERS];
        let decoded =
            status_bind::decode_required(&content, "signature_pending", &mut buffer).unwrap();
        assert_eq!(decoded.modifier_count, 1);
        assert_eq!(buffer[0].pipeline, status_bind::Pipeline::Block);
        assert_eq!(buffer[0].operation, status_bind::ModifierOp::ScalePercent);
        assert_eq!(buffer[0].magnitude, 75);
    }

    // =========================================================================================
    // 端到端 8/9：sequence 与状态施加
    // =========================================================================================

    #[test]
    fn e2e_8_strong_binder_gains_seven_block_then_applies_one_doubt() {
        // CARD[4] = sequence[gainBlock{7, sel.source}, applyStatus{doubt, 1, sel.eventTarget}]
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();

        let stats = run_card(&mut state, &ir, 4, Some("hero"), Some("enemy_a")).unwrap();
        assert_eq!(block_of(&state, "hero"), 7, "先加 7 点格挡");
        assert_eq!(stacks_of(&state, "enemy_a", "doubt"), 1, "再给 eventTarget 上 1 层 doubt");
        assert_eq!(stacks_of(&state, "hero", "doubt"), 0, "状态只落在 eventTarget 上");
        assert_eq!(stats.effects, 2, "两个产出型节点各做了一次事");
        assert_eq!(stats.nodes, 3, "sequence + 两个叶子");
        assert_eq!(instances_of(&state, "enemy_a", "doubt"), 1, "新建了一条实例");
    }

    #[test]
    fn e2e_8b_reapplying_a_status_merges_into_the_existing_instance() {
        // `StatusEffects.cs:126-180`：层数 +=、时长取 max、充能 +=，而且**复用同一个实例**。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        give(
            &mut state,
            "enemy_a",
            status("st_doubt", "doubt", 2)
                .with_duration_turns(3)
                .with_charges(1),
        );

        run_card(&mut state, &ir, 4, Some("hero"), Some("enemy_a")).unwrap();

        assert_eq!(stacks_of(&state, "enemy_a", "doubt"), 3, "2 + 1");
        assert_eq!(instances_of(&state, "enemy_a", "doubt"), 1, "合并 ⇒ **没有**新实例");
        let merged = state
            .combatant(&cid("enemy_a"))
            .unwrap()
            .statuses()
            .iter()
            .find(|s| s.definition_id.as_str() == "doubt")
            .copied()
            .unwrap();
        assert_eq!(merged.duration_turns, 3, "时长取 max(3, 0) = 3");
        assert_eq!(merged.charges, 1, "充能 1 + 0");
        assert_eq!(merged.id.as_str(), "st_doubt", "合并**复用**原实例");
        assert_eq!(
            state.next_status_instance_number, 1,
            "合并**不**消耗生成器号（参考只在新建时取号）"
        );
    }

    #[test]
    fn e2e_8e_a_new_instance_records_its_source_and_a_merge_leaves_it_alone() {
        // 裁决 2 的 exec 半边：`applyStatus` 落盘时把**当前执行上下文的 `source`** 写进
        // `StatusInstance::source_combatant_id`。
        //
        // * 新建：`StatusEffects.cs:187` 的 `SourceCombatantId: applyStatus.SourceCombatantId`
        //   —— 原样收下，没有来源就是 `None`（**不猜**成"行动者"）。
        // * 合并：**不动它**（`:159-165` 的注释 *"The instance keeps its own source,
        //   untouched"*：合并事件报告的是"这一次是谁施加的"，那是事件字段的事）。
        //
        // 走真的节目（CARD[4] = 对 `sel.eventTarget` 上 `doubt`），所以这条链是
        // `execute` → `ExecContext::source` → `apply_one_status` → 实例，不是只测最后一步。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        run_card(&mut state, &ir, 4, Some("hero"), Some("enemy_a")).unwrap();
        assert_eq!(
            instance_of(&state, "enemy_a", "doubt").source_combatant_id,
            Some(cid("hero")),
            "出手方 = 节目的 source"
        );

        // 换一个出手方再施加一次 ⇒ **合并**进原实例，来源保持 hero。
        {
            let mut ctx =
                ExecContext::new(&mut state, Some(cid("enemy_b")), None, None, 1024)
                    .with_content(&content);
            apply_one_status(
                &mut ctx,
                &cid("enemy_a"),
                StatusDefinitionId::new("doubt").unwrap(),
                2,
                0,
                0,
            )
            .unwrap();
        }
        let merged = instance_of(&state, "enemy_a", "doubt");
        assert_eq!(merged.stacks, 3, "1 + 2：确实合并了");
        assert_eq!(
            merged.source_combatant_id,
            Some(cid("hero")),
            "合并**不**改写来源（`:159-165`）"
        );

        // 没有来源的上下文（`source = None`）⇒ 新实例的 `source_combatant_id` 是 `None`，
        // 不是"猜一个行动者"。
        let mut other = arena();
        {
            let mut ctx = ExecContext::new(&mut other, None, None, None, 1024)
                .with_content(&content);
            apply_one_status(
                &mut ctx,
                &cid("enemy_a"),
                StatusDefinitionId::new("doubt").unwrap(),
                1,
                0,
                0,
            )
            .unwrap();
        }
        assert_eq!(
            instance_of(&other, "enemy_a", "doubt").source_combatant_id,
            None
        );
    }

    #[test]
    fn e2e_8c_a_created_status_consumes_exactly_one_generator_number() {
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        assert_eq!(state.next_status_instance_number, 1);
        run_card(&mut state, &ir, 4, Some("hero"), Some("enemy_a")).unwrap();
        assert_eq!(state.next_status_instance_number, 2, "发了一个号");
        let created = state
            .combatant(&cid("enemy_a"))
            .unwrap()
            .statuses()
            .iter()
            .find(|s| s.definition_id.as_str() == "doubt")
            .copied()
            .unwrap();
        assert_eq!(created.id.as_str(), "status_000001");
    }

    #[test]
    fn e2e_8d_two_instances_of_the_same_definition_still_merge_into_the_first() {
        // 参考取的是 `FirstOrDefault(...)`：已经有两条实例时只往**第一条**上加。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_d1", "doubt", 1));
        give(&mut state, "enemy_a", status("st_d2", "doubt", 4));

        run_card(&mut state, &ir, 4, Some("hero"), Some("enemy_a")).unwrap();
        assert_eq!(stacks_of(&state, "enemy_a", "doubt"), 6, "1+1 + 4");
        let first = state
            .combatant(&cid("enemy_a"))
            .unwrap()
            .statuses()
            .iter()
            .find(|s| s.id.as_str() == "st_d1")
            .copied()
            .unwrap();
        assert_eq!(first.stacks, 2, "只有第一条被加");
        assert_eq!(instances_of(&state, "enemy_a", "doubt"), 2);
    }

    #[test]
    fn e2e_9_compliance_review_runs_damage_then_status() {
        // CARD[14] = sequence[dealDamage{5, sel.eventTarget}, applyStatus{paperwork, 2, sel.eventTarget}]
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();

        let stats = run_card(&mut state, &ir, 14, Some("hero"), Some("enemy_b")).unwrap();
        assert_eq!(health(&state, "enemy_b"), 5, "10 - 5");
        assert_eq!(stacks_of(&state, "enemy_b", "paperwork"), 2);
        assert_eq!(stats.effects, 2);
        assert_eq!(stats.nodes, 3);
    }

    #[test]
    fn e2e_9b_multi_target_nodes_hit_every_resolved_target() {
        // CARD[56] stamp_barrage = sequence[dealDamage{sel.allEnemies}, applyStatus{sel.allEnemies}]
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        let stats = run_card(&mut state, &ir, 56, Some("hero"), None).unwrap();
        assert_eq!(health(&state, "hero"), 70, "出手者自己不掉血");
        assert!(health(&state, "enemy_a") < 20, "两个敌人都挨了");
        assert!(health(&state, "enemy_b") < 10);
        assert_eq!(stats.effects, 4, "2 个目标 × 2 个产出型节点");
    }

    // =========================================================================================
    // 端到端 10/11/12：三种拒绝
    // =========================================================================================

    #[test]
    fn e2e_10_a_structural_refusal_happens_in_preflight_so_nothing_is_partially_executed() {
        // 这条测试原来钉的是"`forEachCardInZone` 不支持 ⇒ 整张牌被拒且**一个 effect 都不落地**"。
        // W4f 之后那两种节点都能跑了，所以**拒绝的载体换成了一条仍然存在的结构闸门**
        // （`DefinitionFilter` 非空，见模块头），但**要钉的东西一模一样**：
        // 预检（`ValidateNodeExecutors`，`EffectProgramExecution.cs:184-196`）在**任何** effect
        // 落地之前就拒绝，所以 `sequence[forEachCardInZone(坏), gainBlock 8]` 连那 8 点格挡都不许加。
        let pristine = core_image();
        let content = parse(&pristine);
        let ir = Ir::new(&content);
        let mut state = arena();
        give_card_def(&mut state, "hero", CardZone::Hand, "card_a", "red_tape");
        let before = state_text(&state);

        // `DefinitionFilter` 只有 `NULL16` 才是合法的（实测 2 条 term 全是 NULL）。
        let mut blob = pristine.clone();
        let at = field_slot_offset(&content, 154, "DefinitionFilter");
        assert_eq!(read16(&pristine, at), NULL16, "补丁前是 NULL16");
        patch16(&mut blob, at, 18); // 18 = sel.source：一个"非空但不是卡定义"的对象
        let blob = parse(&blob);
        let ir_patched = Ir::new(&blob);

        assert_eq!(
            run_card_bound(&mut state, &blob, &ir_patched, 36, Some("hero"), Some("hero")),
            Err(ExecError::Sel(SelError::UnsupportedKind))
        );
        assert_eq!(block_of(&state, "hero"), 0, "预检拒绝 ⇒ 那 8 点格挡一个都不许落地");
        assert_eq!(state_text(&state), before, "整个状态逐字节不变（含手牌顺序）");

        // 对照：**不补丁**的同一张牌现在跑得通（而且真搬了卡）—— 证明上面那条拒绝不是
        // "这两种节点本来就不支持"这种空断言。
        let stats = run_card_bound(&mut state, &content, &ir, 36, Some("hero"), Some("hero")).unwrap();
        assert_eq!(block_of(&state, "hero"), 8, "8 点格挡落地了");
        assert_eq!(zone_ids(&state, "hero", CardZone::ExhaustPile), vec!["card_a"]);
        assert_eq!(stats.effects, 2, "搬卡 1 次 + 格挡 1 次");

        // CARD[16] missing_attachment = sequence[applyStatus, drawCards] 也是**能跑**的 ——
        // 这正是"部分执行"的另一面：能跑的程序必须**整段**跑完（applyStatus 落地 + 抽牌发生），
        // 不能因为后面那个节点就把前面那个丢掉。
        let before_hero = status_count(&state, "hero");
        let stats = run_card_bound(&mut state, &content, &ir, 16, Some("hero"), Some("enemy_a")).unwrap();
        assert_eq!(stacks_of(&state, "enemy_a", "paperwork"), 2, "applyStatus 落地了");
        assert_eq!(status_count(&state, "hero"), before_hero, "出手者不长状态");
        assert_eq!(stats.nodes, 3, "sequence + 两个孩子都分派过");
    }

    #[test]
    fn e2e_11_a_non_empty_result_key_is_refused() {
        // 实测：整个镜像 `ResultKey != null` **0 处**（Cards/EnemyActions/Relics/Statuses/
        // Consumables/Events/Recipes/MetaRules 全扫过），所以这条只能靠补丁：
        // 把 CARD[0] 根节点（dealDamage）的 `ResultKey` 槽指到它自己（一个真实对象 term）。
        let pristine = core_image();
        let (root_id, at) = {
            let content = parse(&pristine);
            let ir = Ir::new(&content);
            let root = root_of(&ir, 0);
            (root.id(), field_slot_offset(&content, root.id(), "ResultKey"))
        };
        let mut blob = pristine.clone();
        patch16(&mut blob, at, root_id);

        let content = parse(&blob);
        let ir = Ir::new(&content);
        let root = root_of(&ir, 0);
        assert!(
            matches!(root.field("ResultKey"), Ok(Some(Value::Node(_)))),
            "补丁必须真的把 null 换成节点"
        );

        let mut state = arena();
        assert_eq!(
            run_program(&mut state, root, Some("hero"), Some("hero"), 1024),
            Err(ExecError::ResultKeyNotSupported)
        );
        assert_eq!(health(&state, "hero"), 70, "拒绝 ⇒ 一点血都不掉");
    }

    #[test]
    fn e2e_11b_a_result_key_deep_inside_the_program_also_blocks_the_whole_program() {
        // 预检的第二个用处：结果槽在第 2 个孩子上时，第 1 个孩子也不许先落地。
        let pristine = core_image();
        let (child_id, at) = {
            let content = parse(&pristine);
            let ir = Ir::new(&content);
            let root = root_of(&ir, 4); // strong_binder = sequence[…]
            let mut ids = [0u16; MAX_CHILDREN];
            let count = root.list_field("Children", &mut ids).unwrap();
            assert_eq!(count, 2);
            let second = root.child(ids[1]).id();
            (second, field_slot_offset(&content, second, "ResultKey"))
        };
        let mut blob = pristine.clone();
        patch16(&mut blob, at, child_id);

        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        assert_eq!(
            run_card(&mut state, &ir, 4, Some("hero"), Some("enemy_a")),
            Err(ExecError::ResultKeyNotSupported)
        );
        assert_eq!(block_of(&state, "hero"), 0, "第 1 个孩子的格挡也不许落地");
        assert_eq!(stacks_of(&state, "enemy_a", "doubt"), 0);
    }

    #[test]
    fn e2e_12_step_limit_stops_a_sequence_after_one_node() {
        // ⚠️ 批次 2 起这里的**第二半变了**（如实记录，这是请求/解析拆分的直接后果）：
        // 步数用完 ⇒ 节目 fault ⇒ `execute` 把错误还给调用方，而"把队列抽干"那一步
        // （参考 `Cards/CardPlay.cs:108` 的 `ResolvePendingQueues`）**根本没走到**。
        // 于是第 1 个孩子**已经入队的请求也不落地** —— 这一点与参考一致
        // （参考的异常一路抛出 `PlayCardCore`，`ResolvePendingQueues` 同样被跳过）。
        // 参考：`ctx.ProgramStepCount++; if > MaxProgramSteps: THROW`（`:109-114`）。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let root = root_of(&ir, 4);

        let mut state = arena();
        assert_eq!(
            run_program(&mut state, root, Some("hero"), Some("enemy_a"), 1),
            Err(ExecError::StepLimit)
        );
        assert_eq!(block_of(&state, "hero"), 0, "第一步都没走出去");

        // 预算 3（sequence + 两个孩子）刚好够。
        let mut state = arena();
        let stats = run_program(&mut state, root, Some("hero"), Some("enemy_a"), 3).unwrap();
        assert_eq!(stats.nodes, 3);
        assert_eq!(block_of(&state, "hero"), 7);

        // 预算 2 ⇒ 第 1 个孩子已经落地、第 2 个被预算挡住（这就是"预算"的语义）。
        let mut state = arena();
        assert_eq!(
            run_program(&mut state, root, Some("hero"), Some("enemy_a"), 2),
            Err(ExecError::StepLimit)
        );
        // ⚠️ **0，不是 7**（批次 2 的语义变化，如实钉住）：第 1 个孩子的请求
        // 确实**入队过**（`stats` 在派发那一刻数过它），但 fault 之后没有人排空
        // ⇒ 它不落地。参考一样：`PlayCardCore` 抛出之后 `ResolvePendingQueues` 就不再被调用。
        assert_eq!(
            block_of(&state, "hero"),
            0,
            "fault 之后入队的请求不再落地（排空点没走到）"
        );
        assert_eq!(stacks_of(&state, "enemy_a", "doubt"), 0);
    }

    #[test]
    fn a_zero_step_budget_refuses_everything() {
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let root = root_of(&ir, 0);

        let mut state = arena();
        assert_eq!(
            run_program(&mut state, root, Some("hero"), Some("hero"), 0),
            Err(ExecError::StepLimit)
        );
        assert_eq!(health(&state, "hero"), 70);
        // 预检自己的账也是同一个上限，所以 1 步对 paper_cut（1 个节点）刚好够。
        let mut state = arena();
        assert_eq!(
            run_program(&mut state, root, Some("hero"), Some("hero"), 1),
            Ok(ExecStats { nodes: 1, effects: 1 })
        );
    }

    // =========================================================================================
    // 危险性测试
    // =========================================================================================

    #[test]
    fn a_downed_target_is_filtered_out_by_the_selector() {
        // 参考的 `EventTargetCombatantTargetSelector` 只认活着的人
        // （`CombatantTargetSelectors.cs:118-130`）。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        state.combatant_mut(&cid("hero")).unwrap().lifecycle_state =
            CombatantLifecycleState::Downed;

        let stats = run_card(&mut state, &ir, 0, Some("hero"), Some("hero")).unwrap();
        assert_eq!(stats.effects, 0, "选择器滤掉倒下者 ⇒ 没有目标 ⇒ 0 次效果");
        assert_eq!(stats.nodes, 1, "节点本身还是执行了");
        assert_eq!(health(&state, "hero"), 70, "没有人挨打");
    }

    #[test]
    fn a_lethal_hit_downs_the_target_and_a_second_hit_finds_nobody() {
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        state.combatant_mut(&cid("enemy_b")).unwrap().health_current = 4;

        let first = run_card(&mut state, &ir, 0, Some("hero"), Some("enemy_b")).unwrap();
        assert_eq!(first.effects, 1);
        assert_eq!(health(&state, "enemy_b"), 0);
        assert_eq!(lifecycle(&state, "enemy_b"), CombatantLifecycleState::Downed);

        let second = run_card(&mut state, &ir, 0, Some("hero"), Some("enemy_b")).unwrap();
        assert_eq!(second.effects, 0, "倒下之后选择器不再给出它");
        assert_eq!(health(&state, "enemy_b"), 0);
    }

    #[test]
    fn a_target_the_state_does_not_know_is_missing_combatant() {
        // 选择器**不可能**给出不存在的 id（结果都是 `state.combatants` 的子集），
        // 所以这个错误只在直接调 `resolve_damage` 时可达 —— 那正是它的文档说的意思。
        let mut state = arena();
        let mut ctx = ExecContext::new(&mut state, Some(cid("hero")), None, None, 1024);
        assert_eq!(
            resolve_damage(&mut ctx, &cid("nobody"), 6, false),
            Err(ExecError::MissingCombatant)
        );
    }

    #[test]
    fn a_missing_source_skips_the_source_stage_instead_of_failing() {
        // 参考：`PassiveModifiers.cs:248-249` —— 没有出手者时声明式折叠**原样返回**。
        // 这就是 `ExecError::NoSource` 在 v1 里"没有任何构造路径"的原因（见它的 doc）。
        let mut state = arena();
        give(&mut state, "hero", status("st_s9", "strength", 3));
        let mut ctx = ExecContext::new(&mut state, None, Some(cid("hero")), None, 1024);
        let (blocked, lost) = resolve_damage(&mut ctx, &cid("hero"), 6, false).unwrap();
        assert_eq!((blocked, lost), (0, 6), "没有来源 ⇒ 力量读不到 ⇒ 6 点");
        assert_eq!(health(&state, "hero"), 64);
    }

    #[test]
    fn a_missing_source_makes_source_selectors_resolve_to_nothing_without_panicking() {
        // `sel.source` + 没有 source ⇒ 空集（`CombatantTargetSelectors.cs:84-85`），不是错误。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let root = root_of(&ir, 2); // cower_behind_a_desk：sel.source
        let mut state = arena();
        let stats = run_program(&mut state, root, None, None, 1024).unwrap();
        assert_eq!(stats.effects, 0);
        assert_eq!(block_of(&state, "hero"), 0);
    }

    #[test]
    fn an_empty_sequence_does_nothing_and_is_not_an_error() {
        // 补丁把 CARD[8]（根就是 sequence）的 `Children` 个数槽写成 0。
        let pristine = core_image();
        let (root_id, count_at) = {
            let content = parse(&pristine);
            let ir = Ir::new(&content);
            let root = root_of(&ir, 8);
            // `Children` 的两个槽是 `(起址, 个数)`（`content-binary-format.md` §2.3）。
            let at = field_slot_offset(&content, root.id(), "Children") + 2;
            (root.id(), at)
        };
        let mut blob = pristine.clone();
        patch16(&mut blob, count_at, 0);

        let content = parse(&blob);
        let root = NodeRef::new(&content, root_id);
        let mut ids = [0u16; MAX_CHILDREN];
        assert_eq!(root.list_field("Children", &mut ids), Ok(0), "补丁生效");

        let mut state = arena();
        let stats = run_program(&mut state, root, Some("hero"), Some("enemy_a"), 1024).unwrap();
        assert_eq!(stats, ExecStats { nodes: 1, effects: 0 });
        assert_eq!(health(&state, "enemy_a"), 20);
    }

    #[test]
    fn absent_or_null_lists_read_as_zero_children() {
        // `list_field` 对"字段缺席"与"值为 null"都回 0（`ir.rs` 的冻结取舍）；
        // `node.dealDamage` 的字段表里**有** `Children` 且值为缺席 ⇒ 0 个孩子。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let damage = root_of(&ir, 0);
        let mut ids = [0u16; MAX_CHILDREN];
        assert_eq!(damage.list_field("Children", &mut ids), Ok(0));
        // 一条真正有孩子的 sequence 作对照（否则上面的 0 可能是"读不到"而不是"没有"）。
        let sequence = root_of(&ir, 4);
        assert_eq!(sequence.list_field("Children", &mut ids), Ok(2));
    }

    #[test]
    fn negative_amounts_are_refused_through_the_modifier_bucket() {
        // 参考在这些位置抛 `ArgumentOutOfRangeException` 让整个 program fault
        // （`DamageEffects.cs:50-51,338-339`、`DefensivePoolEffects.cs:15-16`、`StatusEffects.cs:55-62`）；
        // 冻结的 `ExecError` 没有 `NegativeAmount` 变体，所以借 `Modifier`（见它的 doc）。
        let pristine = core_image();
        let (const_id, at) = {
            let content = parse(&pristine);
            let ir = Ir::new(&content);
            let root = root_of(&ir, 0);
            let amount = root.node_field("Amount").unwrap().unwrap();
            let at = field_slot_offset(&content, amount.id(), "Value");
            (amount.id(), at)
        };
        let mut blob = pristine.clone();
        patch16(&mut blob, at, (-1i16) as u16);

        let content = parse(&blob);
        let ir = Ir::new(&content);
        let constant = NodeRef::new(&content, const_id);
        assert_eq!(constant.int_field("Value"), Ok(Some(-1)), "补丁生效（i16 有符号）");

        let mut state = arena();
        assert_eq!(
            run_card(&mut state, &ir, 0, Some("hero"), Some("hero")),
            Err(ExecError::Modifier)
        );
        assert_eq!(health(&state, "hero"), 70, "拒绝 ⇒ 不掉血");

        // `applyStatus` 的三轴负数同理。
        let mut state = arena();
        let mut ctx = ExecContext::new(&mut state, Some(cid("hero")), None, None, 1024);
        assert_eq!(
            apply_one_status(
                &mut ctx,
                &cid("enemy_a"),
                StatusDefinitionId::new("doubt").unwrap(),
                -2,
                0,
                0,
            ),
            Err(ExecError::Modifier)
        );
        assert_eq!(status_count(&state, "enemy_a"), 0);
    }

    #[test]
    fn a_finished_combat_makes_the_whole_program_a_no_op() {
        // `CombatEventHandling.cs:99-111`：三队列循环带 `Result == Ongoing` 条件。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        state.result = CombatResult::Victory;
        let stats = run_card(&mut state, &ir, 0, Some("hero"), Some("hero")).unwrap();
        assert_eq!(stats, ExecStats { nodes: 0, effects: 0 });
        assert_eq!(health(&state, "hero"), 70);
    }

    // =========================================================================================
    // heal：镜像里只有 3 条（都在 relic 的 run 程序里），仍然是真的 `node.heal` term
    // =========================================================================================

    #[test]
    fn heal_heals_up_to_max_but_never_past_it() {
        let blob = core_image();
        let content = parse(&blob);
        let heals = terms_of_kind(&content, "node.heal");
        assert_eq!(heals.len(), 3, "实测镜像里 3 条 node.heal");

        for tid in heals {
            let node = NodeRef::new(&content, tid);
            let amount_expression = node.node_field("Amount").unwrap().expect("Amount");

            // 先把自己的 `Amount` 算出来（它只读状态，这一步不改状态）。
            let mut state = arena();
            let expected = {
                let expr_ctx = ExprContext {
                    content: None,
                    state: &state,
                    source: Some(cid("hero")),
                    event_target: None,
                    iteration_target: None,
                    iteration_card: None,
                    resolving_card: None,
                    event_flags: 0, event_amount: None,
                    x_cost: 0,
                };
                crate::expr::eval_int(amount_expression, &expr_ctx).expect("常量")
            };
            assert!(expected > 0, "镜像里 3 条 heal 的 Amount 都是正的常量");

            // 治疗量按参考是 `min(max, current + 量)`（`DamageEffects.cs:344`）。
            state.combatant_mut(&cid("hero")).unwrap().health_current = 10;
            let stats = run_program(&mut state, node, Some("hero"), None, 1024).unwrap();
            assert_eq!(stats.effects, 1);
            assert_eq!(health(&state, "hero"), 10 + expected, "10 + heal({expected})");

            // 上限：68/70 再加就只会到 70。
            let mut state = arena();
            state.combatant_mut(&cid("hero")).unwrap().health_current = 68;
            run_program(&mut state, node, Some("hero"), None, 1024).unwrap();
            assert_eq!(
                health(&state, "hero"),
                (68 + expected).min(70),
                "治疗不许超过 max"
            );
        }
    }

    // =========================================================================================
    // conditional：CARD 里一个都没有（563 个全在 ENCT/STATUS/REL 的触发程序里），
    // 所以拿镜像里真实的 `node.conditional` term 当根跑，并与"它自己选中的分支"对拍
    // =========================================================================================

    /// 只比较**可观察**的那几样（血量/格挡/状态层数）—— `CombatState` 没有 `PartialEq`。
    fn fingerprint(state: &CombatState) -> Vec<(i32, i32, i32)> {
        ["hero", "enemy_a", "enemy_b"]
            .iter()
            .map(|who| {
                let combatant = state.combatant(&cid(who)).unwrap();
                let stacks: i32 = combatant.statuses().iter().map(|s| s.stacks).sum();
                (
                    combatant.health_current,
                    block_pool(combatant).0,
                    stacks,
                )
            })
            .collect()
    }

    #[test]
    fn a_conditional_behaves_exactly_like_the_branch_it_chooses() {
        // 实测：`node.conditional` 在镜像里**出现** 563 次，但 term 是 interned 的
        // （相同子树只落一份），所以**不同的** conditional 只有 32 个。
        // 这里对每个都跑两种战斗状态 × 两种目标槽，把"条件真/假"两侧都覆盖到：
        // 断言 `conditional` 的可观察结果**等于它自己选中的那个分支**跑出来的结果。
        let blob = core_image();
        let content = parse(&blob);
        let conditionals = terms_of_kind(&content, "node.conditional");
        assert!(
            conditionals.len() >= 20,
            "实测 32 个不同的 conditional term，实际 {}",
            conditionals.len()
        );

        let bare = arena as fn() -> CombatState;
        let loaded = (|| {
            let mut state = arena();
            give(&mut state, "hero", status("c1", "paperwork", 3));
            give(&mut state, "hero", status("c2", "doubt", 2));
            give(&mut state, "hero", status("c3", "strength", 2));
            give(&mut state, "enemy_a", status("c4", "paperwork", 5));
            give(&mut state, "enemy_b", status("c5", "fatigue", 2));
            state
        }) as fn() -> CombatState;
        let arenas: [fn() -> CombatState; 2] = [bare, loaded];
        // 5 组目标槽：条件里最常见的读法（`combatantStatusStacks` / `combatantCounter`）都对
        // "选的是谁"敏感，所以这些组合既能把条件压到真、也能压到假。
        let slots: [(Option<&str>, Option<&str>, Option<&str>); 5] = [
            (Some("hero"), Some("hero"), Some("hero")),
            (Some("hero"), Some("enemy_a"), Some("enemy_b")),
            (Some("hero"), Some("enemy_b"), None),
            (Some("hero"), None, Some("enemy_a")),
            (None, Some("hero"), None),
        ];

        let mut true_cases = 0;
        let mut false_cases = 0;
        let mut compared = 0;

        for tid in conditionals.iter().copied() {
            let node = NodeRef::new(&content, tid);
            let Ok(Some(condition)) = node.node_field("Condition") else {
                continue;
            };

            for make in arenas {
                for (source, event_target, iteration_target) in slots {
                    let base = make();
                    let truth = {
                        let expr_ctx = ExprContext {
                            content: None,
                            state: &base,
                            source: source.map(cid),
                            event_target: event_target.map(cid),
                            iteration_target: iteration_target.map(cid),
                            iteration_card: None,
                            resolving_card: None,
                            event_flags: 0, event_amount: None,
                            x_cost: 0,
                        };
                        match crate::expr::eval_bool(condition, &expr_ctx) {
                            Ok(value) => value,
                            // 条件里可能是 v1 不支持的表达式 —— 跳过这个样本（不是失败）。
                            Err(_) => continue,
                        }
                    };
                    let branch = if truth {
                        node.node_field("Then").unwrap()
                    } else {
                        node.node_field("Else").unwrap()
                    };

                    let mut with_conditional = make();
                    let whole = run_full(
                        &mut with_conditional,
                        node,
                        source,
                        event_target,
                        iteration_target,
                        1024,
                    );

                    // **预检与条件无关**：参考的 `ValidateNodeExecutors` 沿
                    // `ConditionalEffectNode.Children = [Then, Else]` 递归，两条分支都要有
                    // executor，无论这次走哪一条。所以"结构性的拒绝"要先单独判一次，
                    // 否则会把"非选中分支里有不支持节点"误读成"条件跑错了"。
                    let structural = preflight(node, preflight_budget(1024), &mut Walk::default());
                    if let Err(err) = structural {
                        assert_eq!(
                            whole,
                            Err(err),
                            "term {tid}：结构性拒绝必须直接出现在整棵 conditional 上"
                        );
                        continue;
                    }

                    // 同一份起始状态上只跑被选中的分支（没有 `Else` ⇒ "什么都没做"）。
                    let mut with_branch = make();
                    let alone = match branch {
                        Some(branch) => run_full(
                            &mut with_branch,
                            branch,
                            source,
                            event_target,
                            iteration_target,
                            1024,
                        ),
                        None => Ok(ExecStats::default()),
                    };

                    match (whole, alone) {
                        (Ok(whole_stats), Ok(branch_stats)) => {
                            assert_eq!(
                                whole_stats.effects, branch_stats.effects,
                                "term {tid}：conditional 的 effects 必须等于被选中分支的 effects"
                            );
                            assert_eq!(
                                whole_stats.nodes,
                                branch_stats.nodes + 1,
                                "term {tid}：conditional 比分支多算自己这一个节点"
                            );
                            assert_eq!(
                                fingerprint(&with_conditional),
                                fingerprint(&with_branch),
                                "term {tid}：状态变更必须与被选中分支一致（truth={truth}）"
                            );
                            compared += 1;
                            if truth {
                                true_cases += 1;
                            } else {
                                false_cases += 1;
                            }
                        }
                        // 分支自己也报同样的错 ⇒ 不可比（例如分支含 v1 不支持的节点）。
                        (Err(whole_err), Err(branch_err)) => assert_eq!(
                            whole_err, branch_err,
                            "term {tid}：两边都必须报同一个错"
                        ),
                        (whole_result, branch_result) => panic!(
                            "term {tid}：conditional 与分支的结果不一致：\
                             {whole_result:?} vs {branch_result:?}"
                        ),
                    }
                }
            }
        }

        // 实测（32 个 term × 2 种战斗状态 × 5 组目标槽，去掉结构性拒绝与求值不出来的）：
        // **30 个样本可比，其中走 Then 26 个、走 Else/无 Else 4 个**。
        assert!(compared >= 25, "至少要对拍 25 个样本，实际 {compared}");
        assert!(true_cases > 0, "必须有走 Then 的样本");
        assert!(false_cases > 0, "必须有走 Else（或无 Else 什么都不做）的样本");
        assert_eq!(true_cases + false_cases, compared);
    }

    #[test]
    fn a_program_hands_back_the_chain_references_it_took() {
        // 链的引用计数是本模块唯一的"GC"。三条口都要平衡：
        // ① 帧建/借链（`open_frame`）—— 还于 `reap_frames`；
        // ② 效果条目持链（`enqueue_effect_with_owner`）—— 还于出队后；
        // ③ 事件条目持链（`enqueue_event_with_chain`）—— 还于分发出队后（本测试替宿主还）。
        //
        // 不平衡的表现**不是**"多一条链"，而是 128 个节目之后 `Full(Chains)` 到处炸。
        // 所以这条测试跑 200 个节目：任何一处漏还都会在 `MAX_LIVE_CHAINS` 上撞墙。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        for round in 0..200 {
            run_card_bound(&mut state, &content, &ir, 0, Some("hero"), Some("hero"))
                .expect("paper_cut 第 N 次也要跑得通");
            // 本层没有触发器分派器（`host.rs` 的事）：这里替它做"出队 + 还链"那一步。
            while let Some(item) = state.dequeue_event().unwrap() {
                state.release_chain(item.chain);
            }
            assert_eq!(
                state.live_chain_count(),
                0,
                "第 {round} 轮之后还有在用的链 ⇒ 有一处引用没还"
            );
        }
    }

    #[test]
    fn every_card_program_in_the_image_runs_because_no_kind_is_refused() {
        // 全镜像扫描：62 张牌**全部**必须跑通，一个 `panic`、一个拒绝都不许有。
        // 这条测试的意义与 `expr.rs` 的覆盖扫描相同：把"本层到底能跑多少张牌"变成可执行数字，
        // 而不是报告里的一句形容词。
        //
        // W4f 之后它的**结论变了**（58/62 → 62/62），但门槛**只许收紧、不许放松**：
        //   * 以前是"跑通 58 + 被拒的 4 张必须点名且理由是 `UnsupportedNode`"；
        //   * 现在是"62/62 跑通、拒绝集合必须**空**" —— 任何一张被拒都是硬失败，
        //     而且打印的是 `(卡号, 错误)` 而不是一句"有牌被拒了"。
        //
        // 两个升级让"跑通"不是空话：
        //   1. **接上内容镜像跑**（`run_card_bound`）。不接的话 `TagFilter` 会因为
        //      "没有卡定义表"响亮失败（见模块头），而且状态元数据会走标准包目录那条路 ——
        //      那是**另一条**路径，不是参考实现的路。
        //   2. **手里真的给两张废纸 + 一张普通牌**。于是 `archive_the_evidence` /
        //      `shredder_drawer` 的 `forEachCardInZone` 会真的走一遍"快照 → 过滤 → 搬卡"，
        //      而不是在空手牌上"跑通"（空手牌时那个循环体一次都不跑，等于没测）。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);

        let mut ran = 0usize;
        let mut refused: Vec<(u32, ExecError)> = Vec::new();
        let mut cards = 0u32;
        while ir.card_program_root(cards).is_ok() {
            let mut state = arena();
            give_card_def(&mut state, "hero", CardZone::Hand, "card_h1", "red_tape"); // junk
            give_card_def(&mut state, "hero", CardZone::Hand, "card_h2", "paper_cut"); // 不是 junk
            give_card_def(&mut state, "hero", CardZone::Hand, "card_h3", "misfiled_paper"); // junk
            match run_card_bound(&mut state, &content, &ir, cards, Some("hero"), Some("hero")) {
                Ok(_) => ran += 1,
                Err(error) => refused.push((cards, error)),
            }
            cards += 1;
        }

        assert_eq!(cards, 62, "实测 CARD 表 62 行");
        assert_eq!(ran + refused.len(), cards as usize);
        assert!(
            refused.is_empty(),
            "62 张必须**全部**跑得通；被拒的是 {refused:?}"
        );
        assert_eq!(ran, 62, "跑得通的牌数变了 ⇒ 报告里的能力表要跟着改");

        // 那 4 张曾经被拒的牌，拦路的节点就是这两种（不是"某种还没实现的东西"这种模糊说法）：
        // 结构性断言留着，因为它是"能力表"里最容易被悄悄改坏的一行。
        for index in [36u32, 37, 38, 39] {
            let root = root_of(&ir, index);
            let mut ids = [0u16; MAX_CHILDREN];
            let count = root.term_list_field("Children", &mut ids).expect("sequence");
            assert_eq!(count, 2, "CARD[{index}] 是 2 个孩子的 sequence");
            let first = root.child(ids[0]);
            assert_eq!(first.kind(), Ok(NodeKind::ForEachCardInZone), "CARD[{index}]");
            let body = first.node_field("Body").unwrap().unwrap();
            assert_eq!(body.kind(), Ok(NodeKind::MoveCardToZone), "CARD[{index}] 的循环体");
        }
    }

    #[test]
    fn a_conditional_without_a_then_branch_is_a_structural_error() {
        // 参考：`ArgumentNullException.ThrowIfNull(then)` —— `Then` 必填。
        // 把某条 conditional 的 `Then` 槽写成 `NULL16`，执行必须响亮失败。
        let pristine = core_image();
        let content = parse(&pristine);
        let conditionals = terms_of_kind(&content, "node.conditional");
        let Some(tid) = conditionals.first().copied() else {
            panic!("镜像里应当有 32 个不同的 conditional term");
        };
        let at = field_slot_offset(&content, tid, "Then");
        let mut blob = pristine.clone();
        patch16(&mut blob, at, crate::content::NULL16);

        let content = parse(&blob);
        let node = NodeRef::new(&content, tid);
        assert!(
            matches!(node.node_field("Then"), Ok(None)),
            "补丁生效：`Then` 读成 None"
        );
        let mut state = arena();
        assert_eq!(
            run_program(&mut state, node, Some("hero"), Some("hero"), 1024),
            Err(ExecError::Ir(IrError::Missing("Then")))
        );
    }

    // =========================================================================================
    // 修饰表 → 候选表：这一段是"不许硬编码"的可执行证据
    // =========================================================================================

    #[test]
    fn modifier_rows_match_exactly_and_through_the_documented_namespace_bridge() {
        // 逐字 + 桥（模块头假设 A）：两条正例 + 三条反例 + 桥上那 5 条逐条自证。
        assert!(modifier_applies_to("standard.strength", "standard.strength"));
        assert!(modifier_applies_to("strength", "standard.strength"));
        assert!(!modifier_applies_to("my_strength", "standard.strength"));
        assert!(!modifier_applies_to("strengths", "standard.strength"));
        assert!(!modifier_applies_to("doubt", "standard.strength"));
        for (prefixed, bare) in NAMESPACE_BRIDGE {
            assert!(modifier_applies_to(bare, prefixed), "{prefixed}");
            assert!(modifier_applies_to(prefixed, prefixed), "{prefixed}");
        }
        // 桥**只**覆盖这 5 条：目录里没有的状态不会被通用前缀规则"猜"中。
        assert!(!modifier_applies_to("poison", "standard.poison"));
        assert!(!modifier_applies_to("paperwork", "standard.paperwork"));
    }

    #[test]
    fn the_candidate_table_is_built_from_the_catalog_rows() {
        // 五件事都按行来：priority = spec_priority、operation 按 op、magnitude = percent、
        // stacks = 实例总和、spec_index = 行下标、status_key = 该行 id 的字节。
        let mut state = arena();
        give(&mut state, "hero", status("a1", "strength", 2));
        give(&mut state, "hero", status("a2", "strength", 3));
        give(&mut state, "hero", status("a3", "weak", 0));
        let statuses = state.combatant(&cid("hero")).unwrap().statuses().to_vec();

        let mut pool = [0u8; STATUS_ID_POOL_CAP];
        let mut pool_len = 0usize;
        let mut seen = Vec::new();
        for (index, entry) in status_catalog::damage_modifiers().iter().enumerate() {
            let Some(stacks) = total_stacks(&statuses, entry.status_id, StatusMatch::Bridged) else {
                continue;
            };
            let key = intern(&mut pool, &mut pool_len, entry.status_id).unwrap();
            seen.push((index, entry.status_id, stacks, *entry, key));
        }
        assert_eq!(seen.len(), 2, "hero 只有力量与虚弱；易伤是 Target 阶段，第 3 行不参与");

        let (index, id, stacks, entry, key) = &seen[0];
        assert_eq!(*index, 0, "力量是表里的第 0 行");
        assert_eq!(*id, "standard.strength");
        assert_eq!(*stacks, 5, "两条实例求和 2+3");
        assert_eq!(entry.spec_priority, 100);
        assert_eq!(entry.op, ModifierOp::AddStacks);
        assert_eq!(entry.percent, 1, "幅值 1/层");
        assert_eq!(*key, StatusKey { offset: 0, len: 17 });

        let (index, id, stacks, entry, _key) = &seen[1];
        assert_eq!(*index, 1, "虚弱是表里的第 1 行");
        assert_eq!(*id, "standard.weak");
        assert_eq!(*stacks, 0, "只有时长轴 ⇒ 层数 0，**照样参与**");
        assert_eq!(entry.spec_priority, 200);
        assert_eq!(entry.op, ModifierOp::MulPercent);
        assert_eq!(entry.percent, 75);
    }

    #[test]
    fn an_absent_status_contributes_nothing_while_a_zero_stack_one_does() {
        let mut without = arena();
        let statuses = without.combatant(&cid("hero")).unwrap().statuses().to_vec();
        assert_eq!(
            total_stacks(&statuses, "standard.strength", StatusMatch::Bridged),
            None
        );
        let row = [damage_row(&status_catalog::damage_modifiers()[0], 0)];
        assert_eq!(
            fold(6, &statuses, &row, &cid("hero"), StatusMatch::Bridged, 0),
            Ok(6),
            "没人在身 ⇒ 原样"
        );

        let mut with_zero = arena();
        give(&mut with_zero, "hero", status("z1", "strength", 0));
        let statuses = with_zero.combatant(&cid("hero")).unwrap().statuses().to_vec();
        assert_eq!(
            total_stacks(&statuses, "standard.strength", StatusMatch::Bridged),
            Some(0)
        );
        assert_eq!(
            fold(6, &statuses, &row, &cid("hero"), StatusMatch::Bridged, 0),
            Ok(6),
            "0 层的力量 +1/层 = 不加；但这一行**确实被算过**"
        );
        // 对照：同一条 0 层弱（乘法）会真的改数字 —— 证明"参与"与"层数"是两件事。
        let weak = [damage_row(&status_catalog::damage_modifiers()[1], 1)];
        let mut with_zero = arena();
        give(&mut with_zero, "hero", status("w1", "weak", 0));
        let statuses = with_zero.combatant(&cid("hero")).unwrap().statuses().to_vec();
        assert_eq!(
            fold(6, &statuses, &weak, &cid("hero"), StatusMatch::Bridged, 0),
            Ok(4),
            "6*75/100"
        );
        // **同一个 `weak` 行、`Exact` 口径 ⇒ 不生效**：桥是 `Bridged` 才有的东西。
        // `standard.weak` 与实例 id `weak` 逐字节不等 ⇒ 这一行不参与 ⇒ 原样 6。
        assert_eq!(
            fold(6, &statuses, &weak, &cid("hero"), StatusMatch::Exact, 0),
            Ok(6),
            "Exact 口径下 `standard.weak` 不等于 `weak`"
        );
        let _ = &mut without;
    }

    #[test]
    fn the_catalogs_fit_the_candidate_buffer() {
        // 防的是"表变长而缓冲区没变"：那时必须响亮失败，不能静默丢掉候选。
        assert!(status_catalog::damage_modifiers().len() <= MAX_CANDIDATES);
        assert!(status_catalog::block_modifiers().len() <= MAX_CANDIDATES);
        // 串池：状态 id 盒必须装得下"每一行都参与"时最坏的那一份。
        let longest = status_catalog::damage_modifiers()
            .iter()
            .map(|entry| entry.status_id.len())
            .chain(
                status_catalog::block_modifiers()
                    .iter()
                    .map(|entry| entry.status_id.len()),
            )
            .max()
            .unwrap_or(0);
        assert!(
            STATUS_ID_POOL_CAP >= longest * MAX_CANDIDATES,
            "最长 id {longest} B × {MAX_CANDIDATES} 行 > 池 {STATUS_ID_POOL_CAP} B"
        );
    }

    // =========================================================================================
    // 小件：生成器 / 池 / 账本键 / 深度
    // =========================================================================================

    #[test]
    fn status_instance_ids_follow_the_reference_format() {
        // `CombatState.cs:680-687`：`$"status_{NextStatusInstanceNumber:000000}"`，先取号再自增。
        assert_eq!(status_instance_id(1).unwrap().as_str(), "status_000001");
        assert_eq!(status_instance_id(42).unwrap().as_str(), "status_000042");
        assert_eq!(status_instance_id(999_999).unwrap().as_str(), "status_999999");
        assert_eq!(status_instance_id(1_000_000).unwrap().as_str(), "status_1000000");
        assert_eq!(status_instance_id(0).unwrap().as_str(), "status_000000");
    }

    #[test]
    fn the_intern_pool_reports_instead_of_truncating() {
        let mut pool = [0u8; 4];
        let mut len = 0usize;
        assert_eq!(intern(&mut pool, &mut len, "ab"), Ok(StatusKey { offset: 0, len: 2 }));
        assert_eq!(intern(&mut pool, &mut len, "cd"), Ok(StatusKey { offset: 2, len: 2 }));
        assert_eq!(intern(&mut pool, &mut len, "e"), Err(ExecError::Modifier));
        assert_eq!(len, 4, "失败之后池的长度不许变");
    }

    #[test]
    fn the_ledger_owner_key_is_stable_and_owner_specific() {
        assert_eq!(owner_key(&cid("hero")), owner_key(&cid("hero")));
        assert_ne!(owner_key(&cid("hero")), owner_key(&cid("hero ")));
        // 固定值：换实现时这条会红，提醒"键也是可观察量"（FNV-1a 32 of b"hero"）。
        assert_eq!(owner_key(&cid("hero")), 0x1b3b_5c59);
    }

    #[test]
    fn a_self_referential_node_hits_the_depth_gate_instead_of_blowing_the_stack() {
        // 镜像被改坏时最危险的形状：节点指回自己。`NodeRef` 是 term DAG 的视图，环**能**存在。
        // 补丁把某条 conditional 的 `Then` 指向它自己 ⇒ 递归每层 +1 节点，深度闸
        // （`MAX_NODE_DEPTH = 64`，参考的 `MaxNodeDepth`）必须先于栈溢出把它挡住。
        let pristine = core_image();
        let content = parse(&pristine);
        let conditionals = terms_of_kind(&content, "node.conditional");
        let Some(tid) = conditionals.first().copied() else {
            panic!("镜像里应当有 32 个不同的 conditional term");
        };
        let at = field_slot_offset(&content, tid, "Then");
        let mut blob = pristine.clone();
        patch16(&mut blob, at, tid);

        let content = parse(&blob);
        let node = NodeRef::new(&content, tid);
        assert_eq!(
            node.node_field("Then").map(|n| n.map(|n| n.id())),
            Ok(Some(tid)),
            "补丁生效：Then 指向自己"
        );

        let mut state = arena();
        assert_eq!(
            run_program(&mut state, node, Some("hero"), Some("hero"), 1024),
            Err(ExecError::StepLimit),
            "深度闸借 StepLimit 表达（冻结的枚举没有 DepthLimit）"
        );
        // 深度闸走的是**预检**，所以一个 effect 都没落地。
        assert_eq!(health(&state, "hero"), 70);
    }

    // =========================================================================================
    // 内容镜像路径：极性（偏差 A）与镜像修饰器（偏差 B）
    //
    // 这一节的期望值全部来自 `status_bind` 从真实镜像里量出来的那份表：
    //   doubt    Debuff  DamageDealt    ScalePercent  75
    //   panic    Debuff  TurnStartDraw  AddPerStack   -1
    //   strength Buff    DamageDealt    AddPerStack    1
    //   signature_pending Buff DamageReceived ScalePercent 75
    //   seal_intact       Buff DamageReceived AddFlat      -4
    // 其余 18 个状态 `PassiveModifiers = []`。
    // =========================================================================================

    /// `STAT` 行第 `cell` 格在 blob 里的字节偏移（补丁用）。
    fn status_cell_offset(content: &Content<'_>, status_id: &str, cell: usize) -> usize {
        let entry = content
            .lookup_in(status_id, crate::content::EK_STATUS)
            .unwrap_or_else(|| panic!("{status_id} 必须是镜像里的状态"));
        let stat = content
            .section(crate::content::S_STAT)
            .expect("STAT 段必须存在");
        stat.offset as usize + usize::from(entry.index) * 40 + cell * 2
    }

    /// 某条串在 `STR` 池里的串号（补丁用）。
    fn string_id_of(content: &Content<'_>, text: &str) -> u16 {
        let position = content
            .strings()
            .position(|s| s == Some(text))
            .unwrap_or_else(|| panic!("镜像里应当有 `{text}` 这条串"));
        u16::try_from(position + 1).expect("串号装得下 u16")
    }

    /// 找一条状态实例（测试里的"这条实例的极性是什么"）。
    fn instance_of(state: &CombatState, who: &str, definition: &str) -> StatusInstance {
        state
            .combatant(&cid(who))
            .unwrap()
            .statuses()
            .iter()
            .find(|s| s.definition_id.as_str() == definition)
            .copied()
            .unwrap_or_else(|| panic!("{who} 身上应当有一条 {definition}"))
    }

    #[test]
    fn bound_content_turns_doubt_into_a_debuff_instead_of_the_buff_default() {
        // ★ **偏差 A 的封条**。CARD[4] `strong_binder` = sequence[gainBlock 7, applyStatus doubt 1 → eventTarget]。
        //
        // 两个方向都钉：
        // * 有镜像 ⇒ 极性来自 `STAT.Polarity`，`doubt` 是 **Debuff**；
        // * 没有镜像 ⇒ 走目录，目录里没有 `doubt` ⇒ **Buff**（那个"最后兜底"是已知的旧行为，
        //   它在这里被保留成证据：一旦有人把镜像路径接回去，这一条会红）。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);

        let mut bound = arena();
        run_card_bound(&mut bound, &content, &ir, 4, Some("hero"), Some("enemy_a")).unwrap();
        assert_eq!(
            instance_of(&bound, "enemy_a", "doubt").polarity,
            StatusPolarity::Debuff,
            "镜像里 doubt 是 Debuff；旧实现默认 Buff 会让哈希的 pol= 与参考不同"
        );

        let mut unbound = arena();
        run_card(&mut unbound, &ir, 4, Some("hero"), Some("enemy_a")).unwrap();
        assert_eq!(
            instance_of(&unbound, "enemy_a", "doubt").polarity,
            StatusPolarity::Buff,
            "没有 content 时目录查不到 doubt ⇒ 最后兜底成 Buff（旧的已知偏差，未接镜像时仍是这样）"
        );
    }

    #[test]
    fn the_image_supplies_buff_and_debuff_polarities_for_two_more_statuses() {
        // `paperwork`（CARD[14] `compliance_review`）与 `strength`：
        // 实测 `paperwork` = **Debuff**（它有 `damage_over_time` 标签）、`strength` = **Buff**。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);

        let mut state = arena();
        run_card_bound(&mut state, &content, &ir, 14, Some("hero"), Some("enemy_b")).unwrap();
        assert_eq!(
            instance_of(&state, "enemy_b", "paperwork").polarity,
            StatusPolarity::Debuff,
            "镜像里 paperwork 是 Debuff（**不是** Neutral）"
        );

        // 镜像里**没有哪张牌**施加 `strength`（62 张牌的 applyStatus 全部查过），
        // 所以这一条直接走写入路径 —— 极性正是 `apply_one_status` 决定的东西。
        let mut state = arena();
        let mut ctx = ExecContext::new(&mut state, Some(cid("hero")), None, None, 1024)
            .with_content(&content);
        apply_one_status(
            &mut ctx,
            &cid("enemy_a"),
            StatusDefinitionId::new("strength").unwrap(),
            3,
            0,
            0,
        )
        .unwrap();
        assert_eq!(
            instance_of(&state, "enemy_a", "strength").polarity,
            StatusPolarity::Buff
        );
    }

    #[test]
    fn an_unreadable_polarity_in_the_image_is_refused_instead_of_defaulted() {
        // 把 `doubt` 的 `Polarity` 格改成指向 "scenario" ⇒ 必须 [`ExecError::Bind`]，
        // 而不是"猜一个 Buff"。
        let pristine = core_image();
        let content = parse(&pristine);
        let at = status_cell_offset(&content, "doubt", 4);
        let junk = string_id_of(&content, "scenario");
        let mut blob = pristine.clone();
        patch16(&mut blob, at, junk);

        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        assert_eq!(
            run_card_bound(&mut state, &content, &ir, 4, Some("hero"), Some("enemy_a")),
            Err(ExecError::Bind(BindError::Polarity))
        );
        // ⚠️ 如实记录：`Bind` 是**执行期**错误，不像 `UnsupportedNode` 那样在预检里就被拦下 ——
        // 所以同一个 `sequence` 里**前面**的 `gainBlock` 已经落地（7 点格挡），
        // 只有 `applyStatus` 与它后面的节点没跑。参考实现同样是执行到那一句才抛。
        assert_eq!(block_of(&state, "hero"), 7, "gainBlock 在前，已经落地");
        assert_eq!(status_count(&state, "enemy_a"), 0, "applyStatus 自己没落地");
    }

    #[test]
    fn doubt_on_the_source_scales_paper_cut_from_six_to_four() {
        // ★ **偏差 B 的第一条封条**：`doubt` = `DamageDealt / ScalePercent 75`，
        // 放在**出手者**身上 ⇒ 6 * 75 / 100 = 4（整数向零截断）。
        let blob = core_image();
        let content = parse(&blob);

        let mut state = arena();
        give(&mut state, "hero", status("st_d", "doubt", 1));
        assert_eq!(
            deal_bound(&mut state, &content, "enemy_a", 6, false),
            (0, 4),
            "6*75/100 = 4"
        );

        // 反例：放在**承受者**身上 ⇒ 来源阶段读出手者、读不到 ⇒ 6。
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_d", "doubt", 1));
        assert_eq!(deal_bound(&mut state, &content, "enemy_a", 6, false), (0, 6));

        // 当年这条**完全不生效**（`doubt` 不在目录里、桥也匹配不上）⇒ 6。
        // 用 `content = None` 把"修前"的数字也钉在同一处。
        let mut state = arena();
        give(&mut state, "hero", status("st_d", "doubt", 1));
        assert_eq!(
            deal(&mut state, "enemy_a", 6, false),
            (0, 6),
            "没有镜像时 doubt 这条 spec 根本不存在（修前的行为）"
        );
    }

    #[test]
    fn seal_intact_on_the_target_subtracts_four() {
        // ★ **偏差 B 的第二条封条**：`seal_intact` = `DamageReceived / AddFlat -4`。
        // 注意幅值是**负数**（i16 槽里的 65532），而且 `AddFlat` 在 `status_catalog::ModifierOp`
        // 里根本没有变体 —— 这就是"必须换枚举"的那条。
        let blob = core_image();
        let content = parse(&blob);

        let mut state = arena();
        give(&mut state, "enemy_a", status("st_seal", "seal_intact", 1));
        assert_eq!(
            deal_bound(&mut state, &content, "enemy_a", 6, false),
            (0, 2),
            "6 + (-4) = 2"
        );

        // 反例：放在出手者身上 ⇒ 承受者阶段读不到 ⇒ 6。
        let mut state = arena();
        give(&mut state, "hero", status("st_seal", "seal_intact", 1));
        assert_eq!(deal_bound(&mut state, &content, "enemy_a", 6, false), (0, 6));

        // 修前：`content = None` ⇒ 目录里没有 `seal_intact` ⇒ 6。
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_seal", "seal_intact", 1));
        assert_eq!(deal(&mut state, "enemy_a", 6, false), (0, 6));
    }

    #[test]
    fn strength_on_the_source_adds_its_stacks() {
        // ★ **偏差 B 的第三条封条**：镜像自己的 `strength` = `DamageDealt / AddPerStack 1`。
        // 修前它靠**命名空间桥**从标准包那一行拿到"同值"的加成（6+3=9），
        // 所以数字一样、**依据完全不同**；下一条测试证明那个依据在有镜像时已经关掉。
        let blob = core_image();
        let content = parse(&blob);

        for (stacks, expected) in [(1, 7), (2, 8), (3, 9), (0, 6)] {
            let mut state = arena();
            give(&mut state, "hero", status("st_s", "strength", stacks));
            assert_eq!(
                deal_bound(&mut state, &content, "enemy_a", 6, false),
                (0, expected),
                "6 + {stacks} 层"
            );
        }

        // 反例：放在承受者身上 ⇒ 来源阶段读不到 ⇒ 6。
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_s", "strength", 3));
        assert_eq!(deal_bound(&mut state, &content, "enemy_a", 6, false), (0, 6));
    }

    #[test]
    fn a_status_without_passive_modifiers_changes_nothing() {
        // `paperwork` 的 `PassiveModifiers` 是空 `_arr` ⇒ 一条候选都不贡献（两边都放一份）。
        let blob = core_image();
        let content = parse(&blob);

        let mut state = arena();
        give(&mut state, "hero", status("st_p", "paperwork", 5));
        give(&mut state, "enemy_a", status("st_p2", "paperwork", 5));
        assert_eq!(
            deal_bound(&mut state, &content, "enemy_a", 6, false),
            (0, 6),
            "空 PassiveModifiers ⇒ 6 点，一点不多一点不少"
        );

        // 逐条把 18 个空修饰器状态也走一遍（不是抽查）：每一个都必须是 6。
        let mut empty_ids = Vec::new();
        for row in content.rows(crate::content::Table::Status) {
            let Some(status) = content.status(row.index()) else {
                continue;
            };
            let id = content.string(status.id()).unwrap_or("").to_string();
            let mut buffer = [EMPTY_PASSIVE_MODIFIER; status_bind::MAX_MODIFIERS];
            let decoded = status_bind::decode(&content, &id, &mut buffer)
                .unwrap_or_else(|e| panic!("{id} 解码失败：{e:?}"))
                .unwrap_or_else(|| panic!("{id} 应当查得到"));
            if decoded.modifier_count == 0 {
                empty_ids.push(id);
            }
        }
        assert_eq!(empty_ids.len(), 18);
        for id in empty_ids {
            let mut state = arena();
            give(&mut state, "hero", status("st_e", &id, 4));
            give(&mut state, "enemy_a", status("st_e2", &id, 4));
            assert_eq!(
                deal_bound(&mut state, &content, "enemy_a", 6, false),
                (0, 6),
                "{id} 没有修饰器 ⇒ 伤害不变"
            );
        }
    }

    #[test]
    fn the_turn_start_draw_pipeline_never_touches_damage() {
        // `panic` = `TurnStartDraw / AddPerStack -1`。它**不是**伤害管线的一条 spec：
        // 放在出手者身上（层数还很大），伤害必须仍是 6。
        // 如果哪一天有人把"所有 spec 不分管线全折叠"，这一条会立刻变成 6 + 5*(-1) = 1。
        let blob = core_image();
        let content = parse(&blob);

        for stacks in [1, 5, 20] {
            let mut state = arena();
            give(&mut state, "hero", status("st_panic", "panic", stacks));
            assert_eq!(
                deal_bound(&mut state, &content, "enemy_a", 6, false),
                (0, 6),
                "panic 走 TurnStartDraw，不进 DamageDealt（{stacks} 层）"
            );
        }
        // 顺便：`panic` 的 spec 在 `status_bind` 里的管线确实是 TurnStartDraw。
        let mut buffer = [EMPTY_PASSIVE_MODIFIER; status_bind::MAX_MODIFIERS];
        let decoded = status_bind::decode(&content, "panic", &mut buffer)
            .unwrap()
            .unwrap();
        assert_eq!(decoded.modifier_count, 1);
        assert_eq!(buffer[0].pipeline, status_bind::Pipeline::TurnStartDraw);
        assert_eq!(buffer[0].magnitude, -1);
    }

    #[test]
    fn two_instances_of_one_definition_contribute_its_spec_once() {
        // 参考按定义 `GroupBy` 后再算 `Sum(Stacks)`（`PassiveModifiers.cs:142-148`）：
        // 两条 `doubt` 实例 ⇒ **一条** spec。`ScalePercent` 不读层数，所以结果仍然是 4；
        // 若按实例各折一次，会变成 6→4→3（第二条又乘 75%）。这条测试专门钉那个"第二次"。
        let blob = core_image();
        let content = parse(&blob);

        let mut state = arena();
        give(&mut state, "hero", status("st_d1", "doubt", 1));
        give(&mut state, "hero", status("st_d2", "doubt", 3));
        assert_eq!(
            deal_bound(&mut state, &content, "enemy_a", 6, false),
            (0, 4),
            "两条实例只折一次：6*75/100 = 4（再折一次会得 3）"
        );

        // 对照：`AddPerStack` 的那条按**层数之和**加一次。镜像里没有哪张牌给 strength 叠两层，
        // 所以直接摆两条实例：1+2 = 3 ⇒ 6+3 = 9（折两次会得 6+1+2 = 9，同值；
        // 所以这个用例的真正价值是"层数真的求和了"，与上一条的分工不同）。
        let mut state = arena();
        give(&mut state, "hero", status("st_s1", "strength", 1));
        give(&mut state, "hero", status("st_s2", "strength", 2));
        assert_eq!(deal_bound(&mut state, &content, "enemy_a", 6, false), (0, 9));
    }

    #[test]
    fn the_namespace_bridge_only_works_without_content() {
        // ★ 模块头假设 A 的分工，写成断言（两条）：
        //   1. 口径开关本身：`None ⇒ Bridged`、`Some ⇒ Exact`；
        //   2. 行为：`standard.strength` 这条**标准包** id 在有镜像时不再被当成镜像的 `strength`。
        let blob = core_image();
        let content = parse(&blob);

        assert_eq!(StatusMatch::for_content(None), StatusMatch::Bridged);
        assert_eq!(StatusMatch::for_content(Some(&content)), StatusMatch::Exact);

        // 状态里放的是**标准包 id**（oracle 场景会这么写），但敌人用的是镜像：
        // 镜像里没有这个定义 ⇒ **响亮拒绝**。
        //
        // ⚠️ 本轮改了这条断言的形状（原来钉的是"静默 6"）：从前 `image_rows` 写的是
        // `let Some(decoded) = … else { continue }`，于是"内容里根本没这个状态"与
        // "这个状态不参与这条管线"落进同一条静默分支 —— 而"桥关闭"的正确表达是**拒绝**，
        // 不是"一点贡献都没有"（后者连拼错的 id 都一起放过去了）。
        // 桥仍然关闭这一点由下面那半条断言（没有 content ⇒ 9）继续钉着。
        let mut state = arena();
        give(&mut state, "hero", status("st_std", "standard.strength", 3));
        let mut ctx = ExecContext::new(
            &mut state,
            Some(cid("hero")),
            Some(cid("enemy_a")),
            None,
            1024,
        )
        .with_content(&content);
        assert_eq!(
            resolve_damage(&mut ctx, &cid("enemy_a"), 6, false),
            Err(ExecError::Bind(BindError::Missing("STAT row"))),
            "桥关闭 ⇒ standard.strength 在镜像里查不到 ⇒ 拒绝，不是静默 6"
        );

        // 同一个状态、不接镜像 ⇒ 桥开着 ⇒ 6+3 = 9（标准包路径的老行为，不许回归）。
        let mut state = arena();
        give(&mut state, "hero", status("st_std", "standard.strength", 3));
        assert_eq!(
            deal(&mut state, "enemy_a", 6, false),
            (0, 9),
            "没有 content ⇒ 桥生效，标准包那一行 +1/层"
        );
    }

    #[test]
    fn an_unknown_status_is_loud_on_every_image_pipeline_while_an_empty_one_is_fine() {
        // ★ B：**"查不到这个 status 定义"一律响亮失败**，而"定义在、`PassiveModifiers` 为空"
        // 是合法的（很多状态就是纯声明式的）。
        //
        // 现状（动手前量过的）：两条路在**解码层**本来就已经分开（软 `decode` 给
        // `Ok(None)` / `Ok(Some{modifier_count:0})`），缺的只是"没有调用方利用这个区别" ——
        // `exec.rs` 的镜像折叠把它们都 `continue` 掉了。所以本轮改的是**管线调用方**这一侧。
        let blob = core_image();
        let content = parse(&blob);
        let loud = Err(ExecError::Bind(BindError::Missing("STAT row")));

        // 一、查不到定义 ⇒ 镜像的四条管线全部拒绝，而且是**同一个变体**
        //     （与 `has_tag` / `uses_duration` 的口径一致）。
        //     `dexterity` 是标准包 id，`sts_vulnerable` 是"内容自造 id" —— 后者正是最坏那一档：
        //     id 拼得挺像、数字看着都合理，引擎却一条都读不到。
        for unknown in ["dexterity", "sts_vulnerable"] {
            let statuses = [status("st_x", unknown, 2)];
            assert_eq!(
                damage_stage(
                    6,
                    &statuses,
                    ModifierTarget::Source,
                    &cid("hero"),
                    Some(&content),
                    BindDamageKind::Direct,
                    0
                ),
                loud,
                "{unknown}：伤害 Source 阶段"
            );
            assert_eq!(
                damage_stage(
                    6,
                    &statuses,
                    ModifierTarget::Target,
                    &cid("hero"),
                    Some(&content),
                    BindDamageKind::Direct,
                    0
                ),
                loud,
                "{unknown}：伤害 Target 阶段"
            );
            assert_eq!(
                block_stage(5, &statuses, &cid("hero"), Some(&content)),
                loud,
                "{unknown}：格挡管线"
            );
            assert_eq!(
                fold_turn_start_draw(&statuses, &cid("hero"), 5, Some(&content)),
                loud,
                "{unknown}：回合开始抽牌"
            );
        }

        // 二、成对：**已知 + 空 modifiers ⇒ 放行**（`paperwork` 那条纯声明式状态）。
        //     拦它就是把"很多状态就是没有修饰器"当成内容错误 —— 会把正确内容一起打死。
        let empty = [status("st_e", "paperwork", 3)];
        assert_eq!(
            damage_stage(
                6,
                &empty,
                ModifierTarget::Source,
                &cid("hero"),
                Some(&content),
                BindDamageKind::Direct,
                0
            ),
            Ok(6)
        );
        assert_eq!(
            damage_stage(
                6,
                &empty,
                ModifierTarget::Target,
                &cid("hero"),
                Some(&content),
                BindDamageKind::Direct,
                0
            ),
            Ok(6)
        );
        assert_eq!(
            block_stage(5, &empty, &cid("hero"), Some(&content)),
            Ok(5)
        );
        assert_eq!(
            fold_turn_start_draw(&empty, &cid("hero"), 5, Some(&content)),
            Ok(5)
        );

        // 三、没有镜像 ⇒ 标准包路径根本不查 `STAT` 表（候选行来自 `status_catalog`，
        //     实例 id 靠 5 条别名的桥匹配）⇒ "查不到"在那条路上不是问题，也不该报错。
        let none: [StatusInstance; 0] = [];
        assert_eq!(block_stage(5, &none, &cid("hero"), None), Ok(5));
        assert_eq!(fold_turn_start_draw(&none, &cid("hero"), 5, None), Ok(5));

        // 四、端到端：一个自造 id 在身时，真牌**打不出来**（而不是安静地少算一半）。
        let ir = Ir::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_bad", "sts_vulnerable", 1));
        assert_eq!(
            run_card_bound(&mut state, &content, &ir, 0, Some("hero"), Some("enemy_a")),
            Err(ExecError::Bind(BindError::Missing("STAT row"))),
            "paper_cut 的伤害走过 Source 阶段 ⇒ 撞上那条查不到的定义"
        );
    }

    #[test]
    fn the_image_path_reads_the_source_and_target_stages_from_the_right_side() {
        // 把"来源读出手者、承受读承受者"这条分成两半，用**镜像自己的** spec 各证一次：
        // `doubt`(DamageDealt) 只在出手者身上生效，`signature_pending`(DamageReceived)
        // 只在承受者身上生效。两边都放 ⇒ 6→(6*75/100=4)→(4*75/100=3)。
        let blob = core_image();
        let content = parse(&blob);

        let mut state = arena();
        give(&mut state, "hero", status("st_a", "doubt", 1));
        give(&mut state, "enemy_a", status("st_b", "signature_pending", 1));
        assert_eq!(
            deal_bound(&mut state, &content, "enemy_a", 6, false),
            (0, 3),
            "6*75/100 = 4，再 4*75/100 = 3"
        );

        // 交换两侧 ⇒ 两条 spec 都读不到 ⇒ 6（同值不同因的分开钉法）。
        let mut state = arena();
        give(&mut state, "hero", status("st_a", "signature_pending", 1));
        give(&mut state, "enemy_a", status("st_b", "doubt", 1));
        assert_eq!(deal_bound(&mut state, &content, "enemy_a", 6, false), (0, 6));
    }

    // =========================================================================================
    // W4e：7 种新节点 + 多防御池吸收
    //
    // 这一段的每条测试都**先量镜像**（字段名 / 具体 term / 具体数字），再拿真 term 打真状态。
    // 镜像里不存在的形状（`forEachTarget` 遍历 `sel.allEnemies`、`Count > 1` 的
    // `createCardInstance`、非 `DiscardPile`/`Hand` 的 `ToZone`）就地补丁 2 字节，
    // 与 `expr.rs` / `sel.rs` 的补丁测试同一套做法。
    // =========================================================================================

    // ---------------------------------------------------------------- W4e 脚手架

    fn give_resource(state: &mut CombatState, who: &str, id: &str, current: i32, max: Option<i32>) {
        state
            .combatant_mut(&cid(who))
            .unwrap()
            .set_resource(ResourceId::new(id).unwrap(), current, max)
            .unwrap();
    }

    fn resource_of(state: &CombatState, who: &str, id: &str) -> Option<(i32, Option<i32>)> {
        let key = ResourceId::new(id).unwrap();
        state
            .combatant(&cid(who))
            .unwrap()
            .resources()
            .iter()
            .find(|pool| pool.key == key)
            .map(|pool| (pool.pool.current, pool.pool.max))
    }

    fn give_counter(state: &mut CombatState, who: &str, id: &str, value: i32) {
        state
            .combatant_mut(&cid(who))
            .unwrap()
            .set_counter(CounterId::new(id).unwrap(), value)
            .unwrap();
    }

    /// 读一个计数器（缺席 ⇒ 0，与参考的 `GetCounter` 同一个口径）。
    fn counter_value(state: &CombatState, who: &str, id: &str) -> i32 {
        counter_of(
            state.combatant(&cid(who)).unwrap(),
            &CounterId::new(id).unwrap(),
        )
    }

    fn give_card(state: &mut CombatState, who: &str, zone: CardZone, instance: &str) {
        let card = CardInstance::new(
            CardInstanceId::new(instance).unwrap(),
            CardDefinitionId::new("fixture_card").unwrap(),
        );
        state.push_card(&cid(who), zone, card).unwrap();
    }

    fn zone_len(state: &CombatState, who: &str, zone: CardZone) -> usize {
        state
            .card_zones(&cid(who))
            .map_or(0, |zones| zones.count(zone))
    }

    fn zone_ids(state: &CombatState, who: &str, zone: CardZone) -> Vec<String> {
        state
            .zone_cards(&cid(who), zone)
            .map(|card| card.id.as_str().to_string())
            .collect()
    }

    fn pool_of(state: &CombatState, who: &str, id: &str) -> Option<(i32, Option<i32>)> {
        let key = DefensivePoolId::new(id).unwrap();
        state
            .combatant(&cid(who))
            .unwrap()
            .defensive_pools()
            .iter()
            .find(|pool| pool.key == key)
            .map(|pool| (pool.pool.current, pool.pool.max))
    }

    fn read16(blob: &[u8], at: usize) -> u16 {
        u16::from_le_bytes([blob[at], blob[at + 1]])
    }

    /// 按 `(term, 字段, 新值)` 列表就地改镜像的槽位，返回新 blob。
    ///
    /// 偏移量**从原镜像算**：补丁只改槽里的值、不改任何长度，所以两张 blob 的布局逐个字节相同。
    fn patched(pristine: &[u8], edits: &[(u16, &str, u16)]) -> Vec<u8> {
        let mut blob = pristine.to_vec();
        let content = parse(pristine);
        for (tid, field, value) in edits {
            let at = field_slot_offset(&content, *tid, field);
            patch16(&mut blob, at, *value);
        }
        blob
    }

    /// `F_TERMLIST` 字段第 `index` 个元素所在的 `AUX` 单元在 blob 里的字节偏移。
    fn aux_cell_offset(content: &Content<'_>, pristine: &[u8], tid: u16, field: &str, index: usize) -> usize {
        let at = field_slot_offset(content, tid, field);
        let start = usize::from(read16(pristine, at));
        let aux = content.section(crate::content::S_AUX).expect("AUX 段");
        aux.offset as usize + 2 * (start + index)
    }

    // ---------------------------------------------------------------- drawCards

    #[test]
    fn e2e_13_draw_cards_takes_the_top_of_the_pile_without_touching_the_rng() {
        // CARD[10] misfiled_paper 的根节点**就是一根** `node.drawCards{Count: 1, sel.source}`。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::DrawPile, "card_top");
        give_card(&mut state, "hero", CardZone::DrawPile, "card_second");
        let step_before = state.random_step;

        let stats = run_card(&mut state, &ir, 10, Some("hero"), None).unwrap();

        assert_eq!(
            zone_ids(&state, "hero", CardZone::Hand),
            vec!["card_top".to_string()],
            "抽牌堆的**堆顶**（index 0）进手牌，`CardZones.cs:251` 的 RemoveAt(0)"
        );
        assert_eq!(zone_len(&state, "hero", CardZone::DrawPile), 1);
        assert_eq!(
            state.random_step, step_before,
            "没有重洗 ⇒ random_step 一步都不许动"
        );
        assert_eq!(stats.effects, 1);
        assert_eq!(zone_len(&state, "enemy_a", CardZone::Hand), 0, "只有出手方抽");
    }

    #[test]
    fn e2e_13b_a_dry_pile_reshuffles_the_discard_and_pays_exactly_one_random_step() {
        // CARD[41] cross_reference+ = sequence[drawCards{3}, createCardInstance{duplicate_copy
        // → DiscardPile}]。抽 3 张而抽牌堆只有 1 张 ⇒ 必须重洗一次，`random_step` +1
        // （参考 `CardZoneEffects.cs:62-69`；内核把洗牌 + 推进收进
        // `reshuffle_discard_into_into_draw`… 即 `CombatState::reshuffle_discard_into_draw`）。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);

        let mut state = arena();
        give_card(&mut state, "hero", CardZone::DrawPile, "card_d1");
        give_card(&mut state, "hero", CardZone::DiscardPile, "card_x1");
        give_card(&mut state, "hero", CardZone::DiscardPile, "card_x2");
        let step_before = state.random_step;

        run_card(&mut state, &ir, 41, Some("hero"), None).unwrap();

        // 洗牌顺序是 `CreateShuffledIndexes(2, seed, step)` —— 测试自己算一遍，别靠"看着像"。
        let mut order = [0u8; 2];
        crate::rng::shuffle_indexes(&mut order[..2], state.random_seed, step_before);
        let discard = ["card_x1", "card_x2"];
        assert_eq!(
            zone_ids(&state, "hero", CardZone::Hand),
            vec![
                "card_d1".to_string(),
                discard[order[0] as usize].to_string(),
                discard[order[1] as usize].to_string(),
            ],
            "先抽堆顶，再按 RNG 顺序抽洗完的弃牌堆"
        );
        assert_eq!(state.random_step, step_before + 1, "重洗**恰好**付一步");
        assert_eq!(zone_len(&state, "hero", CardZone::DrawPile), 0);
        assert_eq!(
            zone_ids(&state, "hero", CardZone::DiscardPile),
            vec!["card_000001".to_string()],
            "后半段 createCardInstance 把新卡放进弃牌堆"
        );
        assert_eq!(state.next_card_instance_number, 2);
    }

    #[test]
    fn e2e_13c_two_identical_starts_produce_identical_zones() {
        // 确定性：同一份初始状态跑两次，三个牌区逐字节相同（含重洗后的牌序）。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);

        let mut first = arena();
        let mut second = arena();
        for state in [&mut first, &mut second] {
            give_card(state, "hero", CardZone::DrawPile, "card_d1");
            give_card(state, "hero", CardZone::DiscardPile, "card_x1");
            give_card(state, "hero", CardZone::DiscardPile, "card_x2");
        }
        run_card(&mut first, &ir, 41, Some("hero"), None).unwrap();
        run_card(&mut second, &ir, 41, Some("hero"), None).unwrap();

        for zone in [CardZone::DrawPile, CardZone::Hand, CardZone::DiscardPile] {
            assert_eq!(
                zone_ids(&first, "hero", zone),
                zone_ids(&second, "hero", zone),
                "{zone:?} 必须一致"
            );
        }
        assert_eq!(first.random_step, second.random_step);
    }

    #[test]
    fn e2e_13d_both_piles_dry_draws_short_without_an_error_and_without_a_step() {
        // CARD[33] internal_memo+ = sequence[drawCards{2}, createCardInstance]。
        // 抽牌堆 1 张、弃牌堆 0 张 ⇒ 抽 1 张就停（`CardZoneEffects.cs:59-60` 的 break），
        // **不是**错误，也**不**推进 `random_step`（空弃牌堆不算重洗）。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::DrawPile, "card_only");
        let step_before = state.random_step;

        let stats = run_card(&mut state, &ir, 33, Some("hero"), None).unwrap();

        assert_eq!(zone_ids(&state, "hero", CardZone::Hand), vec!["card_only".to_string()]);
        assert_eq!(state.random_step, step_before, "没洗牌 ⇒ 没有 step");
        assert_eq!(
            stats.effects, 2,
            "`drawCards` 一个目标记 1 次 + `createCardInstance` 造 1 张记 1 次"
        );
    }

    // ---------------------------------------------------------------- setCombatantCounter

    #[test]
    fn e2e_14_the_absolute_form_overwrites_and_the_relative_form_accumulates() {
        // 两条**真 term**：
        //   t335 = setCombatantCounter{Amount: const 1, CounterId: wax_sealed_this_turn,
        //                              Relative: **false**, sel.eventTarget}
        //   t1101 = setCombatantCounter{Amount: const 1, CounterId: stolen_sand,
        //                               Relative: **true**, sel.iterationTarget}
        let blob = core_image();
        let content = parse(&blob);
        let absolute = NodeRef::new(&content, 335);
        let relative = NodeRef::new(&content, 1101);
        assert_eq!(absolute.bool_field("Relative"), Ok(Some(false)));
        assert_eq!(relative.bool_field("Relative"), Ok(Some(true)));

        // 绝对：先摆 7，跑一次 ⇒ **1**（不是 8）。
        let mut state = arena();
        give_counter(&mut state, "enemy_a", "wax_sealed_this_turn", 7);
        run_program(&mut state, absolute, Some("hero"), Some("enemy_a"), 1024).unwrap();
        assert_eq!(counter_value(&state, "enemy_a", "wax_sealed_this_turn"), 1);
        // 再来一次还是 1（绝对写入覆盖旧值，不累加）。
        run_program(&mut state, absolute, Some("hero"), Some("enemy_a"), 1024).unwrap();
        assert_eq!(counter_value(&state, "enemy_a", "wax_sealed_this_turn"), 1);

        // 相对：先摆 4，跑一次 ⇒ 5，再跑 ⇒ 6（`ModifyCounter = GetCounter + delta`）。
        let mut state = arena();
        give_counter(&mut state, "hero", "stolen_sand", 4);
        run_full(
            &mut state,
            relative,
            Some("hero"),
            Some("hero"),
            Some("hero"),
            1024,
        )
        .unwrap();
        assert_eq!(counter_value(&state, "hero", "stolen_sand"), 5);
        run_full(
            &mut state,
            relative,
            Some("hero"),
            Some("hero"),
            Some("hero"),
            1024,
        )
        .unwrap();
        assert_eq!(counter_value(&state, "hero", "stolen_sand"), 6);
        // 缺席的计数器读作 0：另一个战斗员一次都没被这个节点碰过。
        assert_eq!(counter_value(&state, "enemy_a", "stolen_sand"), 0);
    }

    #[test]
    fn e2e_14b_the_relative_amount_comes_from_the_expression_layer() {
        // t309 = setCombatantCounter{Amount: min(add(combatantCounter{queue_position,
        //        sel.source}, const 1), const 3), CounterId: queue_position,
        //        Relative: **false**, sel.source} —— "队列位置 +1，但不超过 3"。
        // 它同时证明三件事：**真表达式**（`add`/`min`/`combatantCounter`）在本层跑得通、
        // 计数器读的是**同一个人**的当前值、`Relative: false` 写的是一次算好的绝对值。
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 309);

        let mut state = arena();
        give_counter(&mut state, "hero", "queue_position", 0);
        for expected in [1, 2, 3, 3] {
            run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();
            assert_eq!(counter_value(&state, "hero", "queue_position"), expected);
        }
        assert_eq!(
            counter_value(&state, "enemy_a", "queue_position"),
            0,
            "战士的选择器是 sel.source，敌人一个都没动"
        );
    }

    // ---------------------------------------------------------------- modifyStatusStacks

    #[test]
    fn e2e_15_modify_status_stacks_takes_two_doubt_down_to_one() {
        // t266 = modifyStatusStacks{Delta: const -1, StatusDefinitionId: doubt, sel.source}
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 266);
        let mut state = arena();
        give(&mut state, "hero", status("st_1", "doubt", 2));

        let stats = run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();

        assert_eq!(stacks_of(&state, "hero", "doubt"), 1);
        assert_eq!(instances_of(&state, "hero", "doubt"), 1, "还是那一条实例");
        assert_eq!(stats.effects, 1);
    }

    #[test]
    fn e2e_15b_the_last_stack_removes_the_instance_and_keeps_every_other_field() {
        // 参考 `StatusEffects.cs:830-838`：`newStacks == 0 && oldStacks > 0` ⇒ **删掉实例**
        // （不是留一条 0 层）。这条测试同时钉住"删一条不许碰到别的东西" ——
        // 删除落点是 `Combatant::remove_status`（见 [`remove_status_at`] 的文档），它只做
        // "左移 + pop"，所以其它每一个哈希可见字段都必须原样还在。
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 266);
        let mut state = arena();
        give(&mut state, "hero", status("st_doubt", "doubt", 1));
        give(&mut state, "hero", status("st_paper", "paperwork", 2));
        give(&mut state, "hero", status("st_str", "strength", 3));
        give_resource(&mut state, "hero", "standard.energy", 2, Some(3));
        give_resource(&mut state, "hero", "bones", 5, None);
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .set_defensive_pool(DefensivePoolId::new("standard.block").unwrap(), 4, None)
            .unwrap();
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .set_defensive_pool(DefensivePoolId::new("zzz.ward").unwrap(), 1, Some(2))
            .unwrap();
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .add_tag(crate::state::TagId::new("junk").unwrap())
            .unwrap();
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .add_tag(crate::state::TagId::new("redacted").unwrap())
            .unwrap();
        give_counter(&mut state, "hero", "queue_position", 3);
        give_counter(&mut state, "hero", "seen_doubt", 2);
        state.combatant_mut(&cid("hero")).unwrap().health_current = 55;

        let stats = run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();

        assert_eq!(instances_of(&state, "hero", "doubt"), 0, "0 层 ⇒ 实例消失");
        assert_eq!(stacks_of(&state, "hero", "doubt"), 0);
        assert_eq!(status_count(&state, "hero"), 2, "另外两条还在");
        assert_eq!(instances_of(&state, "hero", "paperwork"), 1);
        assert_eq!(stacks_of(&state, "hero", "paperwork"), 2);
        assert_eq!(stacks_of(&state, "hero", "strength"), 3);
        assert_eq!(
            state
                .combatant(&cid("hero"))
                .unwrap()
                .statuses()
                .iter()
                .map(|s| s.definition_id.as_str())
                .collect::<Vec<_>>(),
            vec!["paperwork", "strength"],
            "顺序也不许乱（参考是 List.Remove，后面的前移）"
        );
        // 下面这些就是"重建必须搬全"的那张表，逐项对。
        assert_eq!(resource_of(&state, "hero", "standard.energy"), Some((2, Some(3))));
        assert_eq!(resource_of(&state, "hero", "bones"), Some((5, None)));
        assert_eq!(pool_of(&state, "hero", "standard.block"), Some((4, None)));
        assert_eq!(pool_of(&state, "hero", "zzz.ward"), Some((1, Some(2))));
        assert_eq!(
            state
                .combatant(&cid("hero"))
                .unwrap()
                .tags()
                .iter()
                .map(|t| t.as_str())
                .collect::<Vec<_>>(),
            vec!["junk", "redacted"]
        );
        assert_eq!(counter_value(&state, "hero", "queue_position"), 3);
        assert_eq!(counter_value(&state, "hero", "seen_doubt"), 2);
        assert_eq!(health(&state, "hero"), 55);
        assert_eq!(lifecycle(&state, "hero"), CombatantLifecycleState::Alive);
        assert_eq!(stats.effects, 1);
    }

    #[test]
    fn e2e_15c_a_status_that_is_not_there_is_left_alone() {
        // 参考 `StatusEffects.cs:860-865`：`FirstOrDefault` 为 null ⇒ 只写 outcome、直接返回。
        // **不是**"对 0 层做加法"（那会凭空造出一条 0 层 doubt，实例个数与哈希都会变）。
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 266);
        let mut state = arena();
        give(&mut state, "hero", status("st_paper", "paperwork", 1));

        let stats = run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();

        assert_eq!(instances_of(&state, "hero", "doubt"), 0, "不许凭空造实例");
        assert_eq!(status_count(&state, "hero"), 1, "只留下原来那条 paperwork");
        assert_eq!(stacks_of(&state, "hero", "paperwork"), 1);
        // 节点还是"执行过"了（它确实分派了、也确实找到了目标），只是没有状态可改。
        assert_eq!(stats.nodes, 1);
    }

    #[test]
    fn e2e_15d_a_delta_that_changes_nothing_writes_nothing() {
        // 参考 `:823-827`：`actualDelta == 0` ⇒ 早退（既不改层数、也不删实例）。
        //
        // 实测这三条真 term（`Delta` 读的**定义**与它要改的**定义**不一定同一个）：
        //   t299 = modifyStatusStacks{target: paperwork, Delta: 0 - stacks(paperwork, sel.source)}
        //   t293 = modifyStatusStacks{target: paperwork, Delta: 0 - stacks(**bookworm**, sel.source)}
        //   t298 = modifyStatusStacks{target: **bookworm**, Delta: 0 - stacks(paperwork, …)}
        let blob = core_image();
        let content = parse(&blob);
        let drain_paperwork = NodeRef::new(&content, 299);
        let drain_by_bookworm = NodeRef::new(&content, 293);

        // (a) 目标身上没有 paperwork ⇒ 读到的栈数是 0 ⇒ delta = 0 ⇒ 不写、**不造实例**。
        let mut state = arena();
        run_program(&mut state, drain_paperwork, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(status_count(&state, "hero"), 0, "delta = 0-0 = 0 ⇒ 不造实例");

        // (b) 有 2 层 ⇒ delta = -2 ⇒ 掉到 0 ⇒ **整条删掉**。
        let mut state = arena();
        give(&mut state, "hero", status("st_paper", "paperwork", 2));
        run_program(&mut state, drain_paperwork, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(instances_of(&state, "hero", "paperwork"), 0, "0-2 = -2 ⇒ 掉到 0 ⇒ 删除");

        // (c) 读的是**另一个**定义：paperwork 5 层，bookworm 2 层 ⇒ 只掉 2 层（5 → 3）。
        let mut state = arena();
        give(&mut state, "hero", status("st_paper", "paperwork", 5));
        give(&mut state, "hero", status("st_book", "bookworm", 2));
        run_program(&mut state, drain_by_bookworm, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(stacks_of(&state, "hero", "paperwork"), 3, "5 - 2 = 3");
        assert_eq!(stacks_of(&state, "hero", "bookworm"), 2, "被读的那个定义一层都不掉");

        // (d) 负数下界：paperwork 1 层而 delta = -2 ⇒ 夹到 0 ⇒ 删除（不是 -1）。
        let mut state = arena();
        give(&mut state, "hero", status("st_paper", "paperwork", 1));
        give(&mut state, "hero", status("st_book", "bookworm", 2));
        run_program(&mut state, drain_by_bookworm, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(instances_of(&state, "hero", "paperwork"), 0, "下界是 0，不是负数");
    }

    // ---------------------------------------------------------------- forEachTarget

    /// 一棵镜像里**不存在**、但语义上必需的树（就地补丁出来的）：
    ///
    /// ```text
    /// node.forEachTarget{ Body: dealDamage{6, sel.iterationTarget},
    ///                     CollectionSelector: sel.allEnemies,
    ///                     MaxIterations: <max_iterations> }
    /// ```
    ///
    /// 用的是**三个真 term**：t962（forEachTarget，来自敌动作）、t3（dealDamage 6）、
    /// 182（`sel.allEnemies`）、952（`sel.iterationTarget`）。只改它们的槽位，
    /// 所以"节点形状"仍然是镜像自己的形状，不是我手搓的。
    fn for_each_all_enemies_blob(pristine: &[u8], max_iterations: u16) -> Vec<u8> {
        let content = parse(pristine);
        assert_eq!(terms_of_kind(&content, "sel.allEnemies"), vec![182]);
        assert_eq!(terms_of_kind(&content, "sel.iterationTarget"), vec![952]);
        assert_eq!(
            NodeRef::new(&content, 3).kind(),
            Ok(NodeKind::DealDamage),
            "t3 = dealDamage 6"
        );
        patched(
            pristine,
            &[
                (962, "CollectionSelector", 182),
                (962, "Body", 3),
                (962, "MaxIterations", max_iterations),
                (3, "TargetSelector", 952),
            ],
        )
    }

    #[test]
    fn e2e_16_for_each_target_binds_the_iteration_target_once_per_target() {
        let pristine = core_image();
        let blob = for_each_all_enemies_blob(&pristine, DEFAULT_MAX_ITERATIONS as u16);
        let content = parse(&blob);
        let mut state = arena();

        let root = NodeRef::new(&content, 962);
        // 先取 `ctx` 里唯一还需要的那个字段，再让这个作用域结束、放掉 `state` 的可变借用。
        let (stats, iteration_target_after) = {
            let mut ctx = ExecContext::new(
                &mut state,
                Some(cid("hero")),
                Some(cid("hero")),
                Some(cid("hero")),
                1024,
            );
            let stats = execute(root, &mut ctx).unwrap();
            (stats, ctx.iteration_target)
        };

        assert_eq!(health(&state, "enemy_a"), 14, "20 - 6：第一个敌人挨了 iteration 那一击");
        assert_eq!(health(&state, "enemy_b"), 4, "10 - 6：第二个也挨了");
        assert_eq!(health(&state, "hero"), 70, "出手者自己不掉血");
        assert_eq!(stats.nodes, 3, "forEachTarget + 两次 Body 分派");
        assert_eq!(stats.effects, 2);
        assert_eq!(
            iteration_target_after,
            Some(cid("hero")),
            "跑完必须**恢复**外层迭代目标（参考的 scope 在 continuation 里关闭）"
        );

        // 反例（成对写）：同一个 Body 节点直接跑、`iteration_target = None` ⇒
        // `sel.iterationTarget` 解出空集 ⇒ **一点伤害都不发生**。
        // 这证明上面那 6 点伤害确实来自"绑上了迭代目标"，而不是那句 `sel.` 恰好指向别人。
        let mut state = arena();
        run_full(&mut state, NodeRef::new(&content, 3), Some("hero"), Some("hero"), None, 1024)
            .unwrap();
        assert_eq!(health(&state, "enemy_a"), 20);
        assert_eq!(health(&state, "enemy_b"), 10);
    }

    #[test]
    fn e2e_16b_more_targets_than_max_iterations_is_refused_before_any_iteration() {
        // 参考 `EffectProgramNodeExecutors.cs:390-393`：`allTargets.Length > MaxIterations` ⇒
        // **抛**（不是截断到上限、也不是"跑前 N 个"）。冻结的 `ExecError` 没有"上限越界"变体，
        // 这里借 `Modifier`（同一条理由：参考里是抛异常让整个 program 作废）。
        let pristine = core_image();
        let blob = for_each_all_enemies_blob(&pristine, 1);
        let content = parse(&blob);
        let mut state = arena();

        assert_eq!(
            run_program(
                &mut state,
                NodeRef::new(&content, 962),
                Some("hero"),
                Some("hero"),
                1024
            ),
            Err(ExecError::Modifier)
        );
        assert_eq!(health(&state, "enemy_a"), 20, "一个 effect 都不许落地");
        assert_eq!(health(&state, "enemy_b"), 10);

        // 上限恰好等于目标数 ⇒ 放行（边界不是 `>=`）。
        let blob = for_each_all_enemies_blob(&pristine, 2);
        let content = parse(&blob);
        let mut state = arena();
        run_program(
            &mut state,
            NodeRef::new(&content, 962),
            Some("hero"),
            Some("hero"),
            1024,
        )
        .unwrap();
        assert_eq!(health(&state, "enemy_a"), 14);
        assert_eq!(health(&state, "enemy_b"), 4);
    }

    #[test]
    fn e2e_16c_a_refusal_inside_the_loop_body_is_found_by_preflight_before_the_sequence_runs() {
        // **预检必须走进 `Body`**（参考 `ForEachTargetEffectNode.Children => [Body]`，
        // `EffectProgramNodes.cs:255`；预检是 `ValidateNodeExecutors`，`:184-196`）。
        //
        // 树：`sequence[applyStatus(paperwork 2 → eventTarget), forEachTarget(Body =
        // forEachCardInZone)]`。第二根孩子的**循环体里**有一条硬规则被违反（`ResultKey` 非空）
        // ⇒ **第一根也不许落地**。
        //
        // W4f 之后 `forEachCardInZone` 本身已经能跑，所以这条测试的"拒绝载体"从
        // "节点不支持"换成了 `ResultKey` 这条**冻结的硬规则** —— 要钉的东西没变：
        // 预检必须沿 `Body` 走进去，而且循环体里的拒绝必须在**任何** effect 落地之前发生。
        let pristine = core_image();
        let content = parse(&pristine);
        // t81 = CARD[16] 的根 = sequence[applyStatus, drawCards]；把**第二根**换掉。
        assert_eq!(NodeRef::new(&content, 81).kind(), Ok(NodeKind::Sequence));
        let second = aux_cell_offset(&content, &pristine, 81, "Children", 1);
        assert_eq!(read16(&pristine, second), 61, "第二根孩子原本是 drawCards(t61)");

        let mut blob = for_each_all_enemies_blob(&pristine, DEFAULT_MAX_ITERATIONS as u16);
        patch16(&mut blob, second, 962); // 第二根 → forEachTarget
        let blob = {
            // 再把 forEachTarget 的 Body 换成真的 `node.forEachCardInZone`（t154），
            // 并把**它的**循环体（t153 moveCardToZone）的 `ResultKey` 写成非空。
            let content = parse(&blob);
            assert_eq!(NodeRef::new(&content, 154).kind(), Ok(NodeKind::ForEachCardInZone));
            let mut out = blob.clone();
            let at = field_slot_offset(&content, 962, "Body");
            patch16(&mut out, at, 154);
            let at = field_slot_offset(&content, 153, "ResultKey");
            assert_eq!(read16(&out, at), NULL16, "补丁前 ResultKey 是 NULL16");
            patch16(&mut out, at, 18); // 18 = sel.source：非空 ⇒ 违反硬规则
            out
        };

        let content = parse(&blob);
        let mut state = arena();
        assert_eq!(
            run_program(
                &mut state,
                NodeRef::new(&content, 81),
                Some("hero"),
                Some("enemy_a"),
                1024
            ),
            Err(ExecError::ResultKeyNotSupported)
        );
        assert_eq!(
            stacks_of(&state, "enemy_a", "paperwork"),
            0,
            "预检拒绝 ⇒ 它前面的 applyStatus 一个状态都不许落地"
        );
        assert_eq!(health(&state, "enemy_a"), 20, "Body 里那一击也不许发生");
    }

    // ---------------------------------------------------------------- gainResource / loseResource

    #[test]
    fn e2e_17_gain_resource_adds_clamps_and_creates() {
        // t143 = gainResource{Amount: const 1, DefaultMax: null, standard.energy, sel.source}
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 143);

        // 有池、没到上限 ⇒ +1，`max` 原样保留。
        let mut state = arena();
        give_resource(&mut state, "hero", "standard.energy", 2, Some(3));
        run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(resource_of(&state, "hero", "standard.energy"), Some((3, Some(3))));

        // 已经在上限 ⇒ 增量 0 ⇒ 不写（值不变，也不报错）。
        run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(resource_of(&state, "hero", "standard.energy"), Some((3, Some(3))));

        // 没有池 ⇒ 建一个 `current = min(Amount, DefaultMax) = 1`、`max = DefaultMax = null`。
        let mut state = arena();
        assert_eq!(resource_of(&state, "hero", "standard.energy"), None);
        run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(resource_of(&state, "hero", "standard.energy"), Some((1, None)));
        // 敌人没被碰过。
        assert_eq!(resource_of(&state, "enemy_a", "standard.energy"), None);
    }

    #[test]
    fn e2e_17b_lose_resource_floors_at_zero_and_never_creates_a_pool() {
        // t278 = loseResource{Amount: const 1, standard.energy, sel.source}
        // 参考 `ResourceEffects.cs:284-306`：不到 0、丢 0 就什么都不写，**不建池**。
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 278);

        let mut state = arena();
        give_resource(&mut state, "hero", "standard.energy", 2, Some(3));
        run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(resource_of(&state, "hero", "standard.energy"), Some((1, Some(3))));
        run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(resource_of(&state, "hero", "standard.energy"), Some((0, Some(3))));
        // 已经在 0 ⇒ 再扣一次也不许变成 -1。
        run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(resource_of(&state, "hero", "standard.energy"), Some((0, Some(3))));

        // 池**不存在** ⇒ 空操作，且**不会**造出一个 (0, null) 的池。
        let mut state = arena();
        run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(resource_of(&state, "hero", "standard.energy"), None);
    }

    // ---------------------------------------------------------------- createCardInstance

    #[test]
    fn e2e_18_create_card_instance_lands_in_the_named_zone_with_a_fresh_id() {
        // t128 = createCardInstance{duplicate_copy, Count: const 1, ToZone: "DiscardPile",
        //                            sel.source}
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 128);
        assert_eq!(node.str_field("ToZone"), Ok(Some("DiscardPile")));
        let mut state = arena();
        assert_eq!(state.next_card_instance_number, 1);

        run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(
            zone_ids(&state, "hero", CardZone::DiscardPile),
            vec!["card_000001".to_string()],
            "`card_%06d`（`CombatState.cs:689-696`）"
        );
        assert_eq!(state.next_card_instance_number, 2, "先取号再自增");
        assert_eq!(zone_len(&state, "hero", CardZone::Hand), 0, "没进错区");
        assert_eq!(
            state
                .zone_cards(&cid("hero"), CardZone::DiscardPile)
                .next()
                .unwrap()
                .definition_id
                .as_str(),
            "duplicate_copy"
        );

        // 再跑一次 ⇒ 第二张的 id 必须不同。
        run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(
            zone_ids(&state, "hero", CardZone::DiscardPile),
            vec!["card_000001".to_string(), "card_000002".to_string()]
        );
    }

    #[test]
    fn e2e_18b_a_count_above_one_creates_that_many_in_the_hand() {
        // 镜像里 9 条 `createCardInstance` 的 `Count` 全是 1，所以"多张"只能补丁：
        // t144 = createCardInstance{red_tape, Count: const 1, ToZone: **"Hand"**, sel.source}，
        // 把它的 `Count` 指向的那个 `const` 的 `Value` 改成 3。
        let pristine = core_image();
        let content = parse(&pristine);
        let count_term = NodeRef::new(&content, 144)
            .node_field("Count")
            .unwrap()
            .unwrap();
        assert_eq!(count_term.kind_str(), Ok("const"));
        let at = field_slot_offset(&content, count_term.id(), "Value");
        let mut blob = pristine.clone();
        patch16(&mut blob, at, 3);

        let content = parse(&blob);
        let node = NodeRef::new(&content, 144);
        let mut state = arena();
        let stats = run_program(&mut state, node, Some("hero"), Some("hero"), 1024).unwrap();

        assert_eq!(
            zone_ids(&state, "hero", CardZone::Hand),
            vec![
                "card_000001".to_string(),
                "card_000002".to_string(),
                "card_000003".to_string(),
            ],
            "三张、id 各不相同、都落在 Hand"
        );
        assert_eq!(state.next_card_instance_number, 4);
        assert_eq!(zone_len(&state, "hero", CardZone::DiscardPile), 0);
        assert_eq!(stats.effects, 3);
    }

    #[test]
    fn e2e_18c_an_unknown_to_zone_string_is_refused() {
        // `ToZone` 是**串枚举**。冻结的 `ExecError` 里没有"未知枚举名"，这里用
        // `IrError::UnknownKind`（本层唯一一个"判别串不认识"的变体）—— 见
        // `create_card_instance_node` 的文档。**绝不**落到某个默认区。
        let pristine = core_image();
        let content = parse(&pristine);
        let bogus = (1..content.string_count())
            .filter_map(|id| u16::try_from(id).ok())
            .find(|id| content.string(*id) == Some("doubt"))
            .expect("镜像里一定有 doubt 这个串");
        let at = field_slot_offset(&content, 128, "ToZone");
        let mut blob = pristine.clone();
        patch16(&mut blob, at, bogus);

        let content = parse(&blob);
        let mut state = arena();
        assert_eq!(
            run_program(
                &mut state,
                NodeRef::new(&content, 128),
                Some("hero"),
                Some("hero"),
                1024
            ),
            Err(ExecError::Ir(IrError::UnknownKind))
        );
        assert_eq!(state.next_card_instance_number, 1, "拒绝之前一个号都不许吃");
        for zone in [CardZone::DrawPile, CardZone::Hand, CardZone::DiscardPile] {
            assert_eq!(zone_len(&state, "hero", zone), 0, "任何区都不许长卡");
        }
    }

    // ---------------------------------------------------------------- 多防御池吸收

    #[test]
    fn two_pools_absorb_in_id_byte_order_not_in_insertion_order() {
        // ★ 参考按 `GetDefensivePoolsInAbsorbOrder()` = `(AbsorbPriority, Id.value)` 排
        //   （`CombatDefinitionRegistry.cs:68-71`）。本层没有池定义表，只剩第二级 —— 而
        //   `Combatant::defensive_pools()` 就是 key 字节序，所以顺序与参考相同（模块头偏差段）。
        //   这条测试故意**逆着** id 顺序插入，证明顺序来自排序而不是插入顺序。
        let mut state = arena();
        let zzz = DefensivePoolId::new("zzz.ward").unwrap();
        state
            .combatant_mut(&cid("enemy_a"))
            .unwrap()
            .set_defensive_pool(zzz, 5, Some(9))
            .unwrap();
        give_block(&mut state, "enemy_a", 3); // standard.block = 3，**后**插入

        let order: Vec<&str> = state
            .combatant(&cid("enemy_a"))
            .unwrap()
            .defensive_pools()
            .iter()
            .map(|pool| pool.key.as_str())
            .collect();
        assert_eq!(
            order,
            vec!["standard.block", "zzz.ward"],
            "\"s\" < \"z\" ⇒ block 排在前面，与插入顺序相反"
        );

        // 6 点伤害：block(3) 先被扣空，再扣 zzz 的 3 点（剩 2）。
        assert_eq!(deal(&mut state, "enemy_a", 6, false), (6, 0));
        assert_eq!(block_of(&state, "enemy_a"), 0, "先被扣空的是 standard.block");
        assert_eq!(
            pool_of(&state, "enemy_a", "zzz.ward"),
            Some((2, Some(9))),
            "第二个池只被扣掉 3 点，且 max 原样保留"
        );
        assert_eq!(health(&state, "enemy_a"), 20, "全被吸收 ⇒ 血量一点不动");
    }

    #[test]
    fn damage_beyond_every_pool_empties_them_all_and_the_rest_hits_health() {
        // 伤害大于所有池之和 ⇒ **每个**池都扣到 0、剩余进血量（`DamageEffects.cs:82-104`）。
        let mut state = arena();
        state
            .combatant_mut(&cid("enemy_a"))
            .unwrap()
            .set_defensive_pool(DefensivePoolId::new("zzz.ward").unwrap(), 5, Some(9))
            .unwrap();
        give_block(&mut state, "enemy_a", 3);

        // 3 + 5 = 8，打 12 ⇒ 8 点被吸收、4 点掉血。
        assert_eq!(deal(&mut state, "enemy_a", 12, false), (8, 4));
        assert_eq!(block_of(&state, "enemy_a"), 0);
        assert_eq!(pool_of(&state, "enemy_a", "zzz.ward"), Some((0, Some(9))));
        assert_eq!(health(&state, "enemy_a"), 16, "20 - 4");

        // `IgnoresBlock` 绕过**每一个**池：两池都还是 0，扣的是血（不掉负、不建池）。
        state
            .combatant_mut(&cid("enemy_a"))
            .unwrap()
            .set_defensive_pool(DefensivePoolId::new("zzz.ward").unwrap(), 5, Some(9))
            .unwrap();
        give_block(&mut state, "enemy_a", 3);
        assert_eq!(deal(&mut state, "enemy_a", 2, true), (0, 2));
        assert_eq!(block_of(&state, "enemy_a"), 3, "真伤不动池子");
        assert_eq!(pool_of(&state, "enemy_a", "zzz.ward"), Some((5, Some(9))));
        assert_eq!(health(&state, "enemy_a"), 14);
    }

    #[test]
    fn a_pool_that_is_already_empty_is_skipped_not_rewritten() {
        // `:86` 的 `pool.Current <= 0 ⇒ continue`：见底的池不许被"写一次 0"，
        // 也不许因为它存在就把伤害算错。这里只留一个见底池 + 血量。
        let mut state = arena();
        give_block(&mut state, "enemy_a", 0);
        assert_eq!(deal(&mut state, "enemy_a", 4, false), (0, 4));
        assert_eq!(health(&state, "enemy_a"), 16);
        assert_eq!(block_of(&state, "enemy_a"), 0);
    }

    // =========================================================================================
    // W4f：`forEachCardInZone` / `moveCardToZone`（卡实例这一层寻址）
    //
    // 每一条都成对：正例证明"该动的动了"，反例证明"正例不是空断言"（要么换一张卡就变红，
    // 要么同一段程序在**没有**条件下必须什么都不做）。
    // =========================================================================================

    /// 一张有废纸也有普通牌的手牌，**顺序即是搬卡顺序的依据**：
    /// `card_a`(junk) / `card_b`(不是 junk) / `card_c`(junk)。
    ///
    /// `paper_cut` 的 tag 里**没有** `junk`（实测 `CARD[0]` = attack/bureaucracy/action），
    /// 而 `red_tape`(CARD[8]) 与 `misfiled_paper`(CARD[10]) 都有。
    fn junk_hand(state: &mut CombatState) {
        give_card_def(state, "hero", CardZone::Hand, "card_a", "red_tape");
        give_card_def(state, "hero", CardZone::Hand, "card_b", "paper_cut");
        give_card_def(state, "hero", CardZone::Hand, "card_c", "misfiled_paper");
    }

    /// 手里两张废纸、没有别的（测"候选数 > 上限"要的就是这个）。
    fn two_junk_cards(state: &mut CombatState) {
        give_card_def(state, "hero", CardZone::Hand, "card_a", "red_tape");
        give_card_def(state, "hero", CardZone::Hand, "card_c", "misfiled_paper");
    }

    #[test]
    fn e2e_19_archive_the_evidence_exhausts_the_first_junk_card_to_the_pile_bottom() {
        // CARD[36] = `sequence[forEachCardInZone{t154}, gainBlock{8}]`，而
        // t154 = `{Body: moveCardToZone{t153 → ExhaustPile, Bottom}, Zone: Hand,
        //          TagFilter: "junk", TakeFirst: 1, MaxIterations: 64, DefinitionFilter: null}`
        // （`docs/spec/card-selection-recon.md:471-498` 逐字打印过这棵树）。
        let blob = core_image();
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let mut state = arena();
        // 先往**消耗堆**里放一张垫底的卡：`Placement = Bottom` 只有在"堆里已经有东西"时才可观察
        // —— 单独一张卡时"堆底"与"堆顶"一模一样，那是最典型的空断言。
        give_card_def(&mut state, "hero", CardZone::ExhaustPile, "card_seed", "form_12_b");
        junk_hand(&mut state);

        let stats =
            run_card_bound(&mut state, &content, &ir, 36, Some("hero"), Some("hero")).unwrap();

        // ① `TakeFirst = 1` ⇒ **手牌里第一张** junk（card_a）走，第二张（card_c）留在手里；
        //    `Bottom` ⇒ 追加到堆底（在 card_seed 之后），不是插到堆顶。
        assert_eq!(
            zone_ids(&state, "hero", CardZone::ExhaustPile),
            vec!["card_seed", "card_a"],
            "Bottom 必须追加到堆底（`CardZones.cs:219-222` 的 `destination.Add`）"
        );
        assert_eq!(
            zone_ids(&state, "hero", CardZone::Hand),
            vec!["card_b", "card_c"],
            "非 junk 不动；第二张 junk 也**不许**动（`TakeFirst = 1`）"
        );
        // ② 那 8 点格挡（第二个孩子照跑）。
        assert_eq!(block_of(&state, "hero"), 8);
        // ③ 计数：搬一次卡 + 一次格挡。
        assert_eq!(stats.effects, 2);
        assert_eq!(
            stats.nodes, 4,
            "sequence + forEachCardInZone + moveCardToZone + gainBlock"
        );
    }

    #[test]
    fn e2e_19b_shredder_drawer_exhausts_every_junk_card_and_leaves_the_rest() {
        // CARD[38] = `sequence[forEachCardInZone{t165}, dealDamage{9 → eventTarget}]`；
        // t165 与 t154 的**唯一**差别是 `TakeFirst = NULL`（`NULL_INT = 0x8001`，实测）。
        let pristine = core_image();
        let content = parse(&pristine);
        let ir = Ir::new(&content);
        assert_eq!(
            read16(&pristine, field_slot_offset(&content, 165, "TakeFirst")),
            crate::content::NULL_INT,
            "实测：t165 的 TakeFirst 是 NULL_INT（键存在、值是 null），不是缺席"
        );
        assert_eq!(NodeRef::new(&content, 165).int_field("TakeFirst"), Ok(None));

        let mut state = arena();
        junk_hand(&mut state);
        let stats =
            run_card_bound(&mut state, &content, &ir, 38, Some("hero"), Some("enemy_a")).unwrap();

        // 所有 junk 都走，**顺序 = 手牌顺序**；非 junk 留着。
        assert_eq!(
            zone_ids(&state, "hero", CardZone::ExhaustPile),
            vec!["card_a", "card_c"]
        );
        assert_eq!(zone_ids(&state, "hero", CardZone::Hand), vec!["card_b"]);
        // 第二个孩子照跑：9 点打到 eventTarget。
        assert_eq!(health(&state, "enemy_a"), 11, "20 - 9");
        assert_eq!(health(&state, "hero"), 70, "出手者没挨打");
        assert_eq!(stats.effects, 3, "搬卡 2 次 + 伤害 1 次");
        assert_eq!(
            stats.nodes, 5,
            "sequence + forEachCardInZone + 2×moveCardToZone + dealDamage"
        );
    }

    #[test]
    fn e2e_19c_no_junk_card_makes_the_loop_a_clean_no_op() {
        // 单独跑 t154（不跑整张牌，免得 `gainBlock` 把"什么都没动"搅浑）。
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 154);

        // (a) 手牌里一张 junk 都没有 ⇒ 不报错、`effects` 不涨、状态**逐字节**不变。
        let mut state = arena();
        give_card_def(&mut state, "hero", CardZone::Hand, "card_b", "paper_cut");
        let before = state_text(&state);
        let stats =
            run_program_bound(&mut state, &content, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(stats.effects, 0);
        assert_eq!(stats.nodes, 1, "只分派了 forEachCardInZone，循环体一次都没跑");
        assert_eq!(state_text(&state), before, "逐字节不变（含牌区的堆内顺序）");

        // (b) 空手牌也一样（`Take(1)` 在空序列上什么都不做）。
        let mut state = arena();
        let before = state_text(&state);
        let stats =
            run_program_bound(&mut state, &content, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(stats.effects, 0);
        assert_eq!(state_text(&state), before);

        // (c) **反例**：同一段程序、只把一张废纸放进手里 ⇒ 状态必须真的变。
        //     没有这条，(a)/(b) 的"不变"可能只是因为那段程序压根没跑。
        let mut state = arena();
        give_card_def(&mut state, "hero", CardZone::Hand, "card_a", "red_tape");
        let before = state_text(&state);
        let stats =
            run_program_bound(&mut state, &content, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(stats.effects, 1);
        assert_eq!(stats.nodes, 2, "forEachCardInZone + 一次循环体");
        assert_ne!(state_text(&state), before);
        assert_eq!(zone_ids(&state, "hero", CardZone::ExhaustPile), vec!["card_a"]);
        assert_eq!(zone_ids(&state, "hero", CardZone::Hand), Vec::<String>::new());
    }

    #[test]
    fn e2e_19d_max_iterations_over_the_candidates_throws_and_moves_nothing() {
        // 参考 `:467-470`：`ids.Length > MaxIterations` ⇒ **抛**（不截断；SEMANTICS-v1 O38）。
        // 用 t165（`TakeFirst = NULL`）—— 用 t154 的话 `TakeFirst = 1` 会先把候选截到 1，
        // 上限再小也撞不上，"上限被忽略"这个 bug 就永远测不出来。
        let pristine = core_image();
        let content_pristine = parse(&pristine);
        let at = field_slot_offset(&content_pristine, 165, "MaxIterations");
        assert_eq!(read16(&pristine, at), 64, "镜像里是默认值 64");

        // (a) 上限 1、候选 2 ⇒ 抛，且**一张卡都不许动**。
        let mut blob = pristine.clone();
        patch16(&mut blob, at, 1);
        let content = parse(&blob);
        let mut state = arena();
        two_junk_cards(&mut state);
        let before = state_text(&state);
        assert_eq!(
            run_program_bound(
                &mut state,
                &content,
                NodeRef::new(&content, 165),
                Some("hero"),
                Some("hero"),
                1024
            ),
            Err(ExecError::Modifier)
        );
        assert_eq!(state_text(&state), before, "抛之前一张卡都不许搬");

        // (b) 上限 0、候选 1 ⇒ **也抛**（`int 1 > int 0` 为真）：0 不是"无上限"的后门，
        //     也不会被夹成"什么都不做"。
        let mut blob = pristine.clone();
        patch16(&mut blob, at, 0);
        let content = parse(&blob);
        let mut state = arena();
        give_card_def(&mut state, "hero", CardZone::Hand, "card_a", "red_tape");
        let before = state_text(&state);
        assert_eq!(
            run_program_bound(
                &mut state,
                &content,
                NodeRef::new(&content, 165),
                Some("hero"),
                Some("hero"),
                1024
            ),
            Err(ExecError::Modifier)
        );
        assert_eq!(state_text(&state), before);

        // (c) 边界：上限**恰好等于**候选数 ⇒ 放行（比较是 `>` 而不是 `>=`）。
        let mut blob = pristine.clone();
        patch16(&mut blob, at, 2);
        let content = parse(&blob);
        let mut state = arena();
        two_junk_cards(&mut state);
        let stats = run_program_bound(
            &mut state,
            &content,
            NodeRef::new(&content, 165),
            Some("hero"),
            Some("hero"),
            1024,
        )
        .unwrap();
        assert_eq!(stats.effects, 2);
        assert_eq!(
            zone_ids(&state, "hero", CardZone::ExhaustPile),
            vec!["card_a", "card_c"]
        );
    }

    #[test]
    fn e2e_19e_a_non_null_definition_filter_is_refused_in_both_wire_shapes() {
        // 实测：这 2 条 term 的 `DefinitionFilter` **都是 `NULL16`**。非空时线上是一个
        // `_wrap_lower` 包装串（`CardDefinitionId` 的编码），而 `ir.rs::NodeRef::field`
        // 故意不收那种拼法 ⇒ `IrError::WrongKind("F_TERM")`；写成别的对象则由
        // [`reject_definition_filter`] 报 `SelError::UnsupportedKind`。
        // **两条都是响亮失败** —— 绝不许静默忽略一条过滤条件（那会让"只消耗某一种废纸"
        // 悄悄变成"消耗所有废纸"）。
        let pristine = core_image();
        let content_pristine = parse(&pristine);
        let at = field_slot_offset(&content_pristine, 154, "DefinitionFilter");
        assert_eq!(read16(&pristine, at), NULL16, "补丁前是 NULL16");

        // (a) 包装串（真的 `CardDefinitionId` 会编成的形状）
        let mut blob = pristine.clone();
        let wrapped = wrap_lower_term(&content_pristine);
        patch16(&mut blob, at, wrapped);
        let content = parse(&blob);
        let mut state = arena();
        junk_hand(&mut state);
        let before = state_text(&state);
        assert_eq!(
            run_program_bound(
                &mut state,
                &content,
                NodeRef::new(&content, 154),
                Some("hero"),
                Some("hero"),
                1024
            ),
            Err(ExecError::Ir(IrError::WrongKind("F_TERM")))
        );
        assert_eq!(state_text(&state), before);

        // (b) 别的对象（不是卡定义）
        let mut blob = pristine.clone();
        patch16(&mut blob, at, 18); // 18 = sel.source
        let content = parse(&blob);
        let mut state = arena();
        junk_hand(&mut state);
        assert_eq!(
            run_program_bound(
                &mut state,
                &content,
                NodeRef::new(&content, 154),
                Some("hero"),
                Some("hero"),
                1024
            ),
            Err(ExecError::Sel(SelError::UnsupportedKind))
        );
        assert_eq!(state_text(&state), before);

        // (c) 反例：**不补丁**的同一段程序会搬卡 ⇒ (a)/(b) 的"什么都没动"不是空断言。
        let content_ok = parse(&pristine);
        let mut state = arena();
        junk_hand(&mut state);
        run_program_bound(
            &mut state,
            &content_ok,
            NodeRef::new(&content_ok, 154),
            Some("hero"),
            Some("hero"),
            1024,
        )
        .unwrap();
        assert_eq!(zone_ids(&state, "hero", CardZone::ExhaustPile), vec!["card_a"]);
    }

    #[test]
    fn e2e_19f_move_card_to_zone_refuses_a_card_expression_of_the_wrong_value_kind() {
        // t153 的 `CardExpression` 是 `cardInstance.iterated`（值类别 = 卡）。换成 `const`
        // （值类别 = int）⇒ `ExprError::WrongValueKind`，**不许静默不动**。
        let pristine = core_image();
        let content_pristine = parse(&pristine);
        let at = field_slot_offset(&content_pristine, 153, "CardExpression");
        let const_term = a_const_term(&content_pristine);
        let mut blob = pristine.clone();
        patch16(&mut blob, at, const_term);
        let content = parse(&blob);

        let mut state = arena();
        junk_hand(&mut state);
        let before = state_text(&state);
        assert_eq!(
            run_program_bound(
                &mut state,
                &content,
                NodeRef::new(&content, 153),
                Some("hero"),
                Some("hero"),
                1024
            ),
            Err(ExecError::Expr(ExprError::WrongValueKind))
        );
        assert_eq!(state_text(&state), before);

        // 对照：**没有绑定迭代卡**时（不补丁的 t153 直接跑）是 `ExprError::NoTarget` ——
        // expr.rs 的冻结决定：绝不返回一个空 id 让本节点去"静默不动"（那是最坏的一种通过）。
        let content_ok = parse(&pristine);
        let mut state = arena();
        junk_hand(&mut state);
        let before = state_text(&state);
        assert_eq!(
            run_program_bound(
                &mut state,
                &content_ok,
                NodeRef::new(&content_ok, 153),
                Some("hero"),
                Some("hero"),
                1024
            ),
            Err(ExecError::Expr(ExprError::NoTarget))
        );
        assert_eq!(state_text(&state), before);
    }

    /// 直接跑一个节点、**显式**给出 `iteration_card`，并在跑完之后用**冻结的表达式入口**
    /// 再求值一次 `cardInstance.iterated`（t152）。
    ///
    /// 返回 `(执行结果, 退出时的迭代卡槽, 再求值的结果)` —— 第三项是"槽没被恢复"的唯一硬证据：
    /// 它必须报 [`ExprError::NoTarget`]，而不是"恰好等于刚才那张卡"。
    ///
    /// 借用必须在**函数里**结束：`drop(ctx)` 会被 clippy 判成 `drop_non_drop`
    /// （`ExecContext` 没有 `Drop`，`mem::drop` 只会延长它借走的 `&mut state`），
    /// 所以这里靠作用域把 `&mut state` 交还给调用方。
    fn run_with_iteration_card<'c>(
        state: &mut CombatState,
        content: &'c Content<'c>,
        root: NodeRef<'_>,
        source: Option<&str>,
        card: Option<&str>,
    ) -> (
        Result<ExecStats, ExecError>,
        Option<CardInstanceId>,
        Result<CardInstanceId, ExprError>,
    ) {
        let mut ctx =
            ExecContext::new(state, source.map(cid), Some(cid("hero")), None, 1024)
                .with_content(content);
        ctx.iteration_card = card.map(|name| CardInstanceId::new(name).unwrap());
        let outcome = execute(root, &mut ctx);
        let slot = ctx.iteration_card;
        let iterated = {
            let expr_ctx = ctx.expr_context();
            // t152 = `cardInstance.iterated`（实测全镜像只有这一条这种 kind）。
            expr::eval_card(NodeRef::new(content, 152), &expr_ctx)
        };
        (outcome, slot, iterated)
    }

    #[test]
    fn e2e_19g_a_card_the_owners_piles_do_not_hold_is_refused_not_ignored() {
        // 参考 `CardZones.cs:196-197`：`zones.GetCard(id)` 找不到 ⇒ **抛**（整个 program 作废）；
        // `CardZoneEffects.cs:175-179`：卡的主人不是这个战斗员 ⇒ 也**抛**。
        // 本层没有 `MissingCard`/`NotOwner` 变体，借 `ExecError::Modifier`
        // （与负金额、`MaxIterations` 越界同一条借法：参考抛 ⇒ program 整体作废）。
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 153); // moveCardToZone → ExhaustPile / Bottom

        // (a) 迭代卡指向一张**不存在**的卡 ⇒ 响亮失败，且一个字节都不动。
        let mut state = arena();
        give_card_def(&mut state, "hero", CardZone::Hand, "card_a", "red_tape");
        let before = state_text(&state);
        let (outcome, _, _) =
            run_with_iteration_card(&mut state, &content, node, Some("hero"), Some("card_ghost"));
        assert_eq!(outcome, Err(ExecError::Modifier));
        assert_eq!(state_text(&state), before);

        // (b) 卡**已经**在目的地 + `Bottom` ⇒ 是 no-op（不是错误），但效果请求确实发起过。
        let mut state = arena();
        give_card_def(&mut state, "hero", CardZone::ExhaustPile, "card_a", "red_tape");
        let before = state_text(&state);
        let (outcome, _, _) =
            run_with_iteration_card(&mut state, &content, node, Some("hero"), Some("card_a"));
        let stats = outcome.unwrap();
        assert_eq!(stats.effects, 1, "请求入队过（口径见 `ExecStats::effects`）");
        assert_eq!(
            state_text(&state),
            before,
            "同区 + Bottom ⇒ 一个字节都不动（`CardZoneEffects.cs:187-195`）"
        );

        // (c) 同区 + `Top` 才重排（`CardZoneEffects.cs:189-190`）。线上走不到：`"Top"`
        //     这个串**不在镜像的串池里**（`reader.py` 实测查不到），所以只能直接测实体函数。
        let mut state = arena();
        give_card_def(&mut state, "hero", CardZone::ExhaustPile, "card_a", "red_tape");
        give_card_def(&mut state, "hero", CardZone::ExhaustPile, "card_b", "misfiled_paper");
        assert_eq!(
            zone_ids(&state, "hero", CardZone::ExhaustPile),
            vec!["card_a", "card_b"]
        );
        {
            let mut ctx =
                ExecContext::new(&mut state, Some(cid("hero")), Some(cid("hero")), None, 1024)
                    .with_content(&content);
            move_card_for(
                &mut ctx,
                &cid("hero"),
                &CardInstanceId::new("card_b").unwrap(),
                CardZone::ExhaustPile,
                ZonePlacement::Top,
            )
            .unwrap();
        }
        assert_eq!(
            zone_ids(&state, "hero", CardZone::ExhaustPile),
            vec!["card_b", "card_a"],
            "Top = Insert(0)（`CardZones.cs:219-220`：the front is the draw top）"
        );
    }

    #[test]
    fn e2e_19h_a_body_error_never_leaves_the_iteration_card_bound() {
        // 参考把 scope 关闭写在 continuation 里（`:484-485`），异常路径上外层上下文原样保留
        // ⇒ 本层必须**无条件**恢复（含 Body 报错的路径）。
        //
        // 观察手段必须是**冻结的表达式入口**：循环结束后再求值一次 `cardInstance.iterated`，
        // 它必须报 `NoTarget` —— 而不是"恰好等于刚才那张卡"。
        let pristine = core_image();
        let content_ok = parse(&pristine);
        assert_eq!(
            NodeRef::new(&content_ok, 152).kind_str(),
            Ok("cardInstance.iterated")
        );

        // (a) 正常路径：Body 跑完、卡真的搬走了 ⇒ 之后迭代卡必须已被解绑。
        let mut state = arena();
        junk_hand(&mut state);
        let (outcome, slot, iterated) = run_with_iteration_card(
            &mut state,
            &content_ok,
            NodeRef::new(&content_ok, 154),
            Some("hero"),
            None,
        );
        assert_eq!(outcome.unwrap().effects, 1, "Body 真的跑了一轮");
        assert_eq!(slot, None, "循环退出后必须解绑");
        assert_eq!(
            iterated,
            Err(ExprError::NoTarget),
            "外层再求值必须拒绝，不许读到刚才那张卡"
        );
        assert_eq!(zone_ids(&state, "hero", CardZone::ExhaustPile), vec!["card_a"]);

        // (b) 报错路径：把循环体的 `CardExpression` 换成 `const` ⇒ 第一轮就报
        //     `WrongValueKind`，迭代卡**同样**必须解绑。
        let content_pristine = parse(&pristine);
        let at = field_slot_offset(&content_pristine, 153, "CardExpression");
        let mut blob = pristine.clone();
        patch16(&mut blob, at, a_const_term(&content_pristine));
        let content = parse(&blob);

        let mut state = arena();
        junk_hand(&mut state);
        let before = state_text(&state);
        let (outcome, slot, iterated) = run_with_iteration_card(
            &mut state,
            &content,
            NodeRef::new(&content, 154),
            Some("hero"),
            None,
        );
        assert_eq!(outcome, Err(ExecError::Expr(ExprError::WrongValueKind)));
        assert_eq!(slot, None, "报错路径也必须解绑");
        assert_eq!(iterated, Err(ExprError::NoTarget));
        assert_eq!(state_text(&state), before, "Body 报错 ⇒ 一张卡都没搬");
    }

    #[test]
    fn e2e_19i_no_owner_makes_the_loop_a_no_op_not_an_error() {
        // 参考 `:439-445`：`owner == default`（或它没有牌区）⇒ **完成**，不是错误。
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 154);

        let mut state = arena();
        junk_hand(&mut state);
        let before = state_text(&state);
        let stats = run_program_bound(&mut state, &content, node, None, Some("hero"), 1024).unwrap();
        assert_eq!(stats.effects, 0);
        assert_eq!(stats.nodes, 1);
        assert_eq!(state_text(&state), before);

        // 反例：同一个调用只要给上 `source`（`sel.source` 的唯一来源）就必须真的搬卡。
        let stats =
            run_program_bound(&mut state, &content, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(stats.effects, 1);
        assert_eq!(zone_ids(&state, "hero", CardZone::ExhaustPile), vec!["card_a"]);
    }

    #[test]
    fn e2e_19j_a_tag_filter_without_a_content_image_is_refused_not_matched_against_nothing() {
        // `TagFilter` 读的是**卡定义**的 tag，而那份表只在内容镜像里。没有镜像时
        // **响亮拒绝**，绝不静默成"一张都不匹配"（那会让"清空手牌里的废纸"安静地一张都不清）。
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 154);
        let mut state = arena();
        junk_hand(&mut state);
        let before = state_text(&state);
        assert_eq!(
            run_program(&mut state, node, Some("hero"), Some("hero"), 1024),
            Err(ExecError::Ir(IrError::Missing("content")))
        );
        assert_eq!(state_text(&state), before);

        // 反例：**同一份状态**接上镜像就搬得动。
        run_program_bound(&mut state, &content, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(zone_ids(&state, "hero", CardZone::ExhaustPile), vec!["card_a"]);
    }

    #[test]
    fn e2e_19k_a_card_whose_definition_is_not_in_the_image_has_no_tags() {
        // 参考 `:454` 的注释原话："an instance whose definition isn't registered has none"
        // ⇒ 未注册的定义**不匹配**任何 tag 过滤，但**不是错误**
        // （与"没有内容镜像"是两件事：那是"我们有表但表里没有这张卡"）。
        let blob = core_image();
        let content = parse(&blob);
        let node = NodeRef::new(&content, 165); // TakeFirst = NULL：全部匹配都搬
        let mut state = arena();
        give_card_def(&mut state, "hero", CardZone::Hand, "card_unknown", "fixture_card");
        give_card_def(&mut state, "hero", CardZone::Hand, "card_a", "red_tape");

        let stats =
            run_program_bound(&mut state, &content, node, Some("hero"), Some("hero"), 1024).unwrap();
        assert_eq!(stats.effects, 1, "只有那张**真的**带 junk 的卡被搬了");
        assert_eq!(zone_ids(&state, "hero", CardZone::ExhaustPile), vec!["card_a"]);
        assert_eq!(
            zone_ids(&state, "hero", CardZone::Hand),
            vec!["card_unknown"],
            "未注册的定义留在手里（不是错误、也不是'匹配上了'）"
        );
    }

    // =========================================================================================
    // 动画日志（§142）
    // =========================================================================================
    //
    // 这一组的形状**故意是数条数、对每一位**，而不是"有没有某条"：一次掉血记两遍、或者
    // 多段攻击塌成一条，都不会让"有没有"型断言变红。§142 的全部理由是"顺序与分段"，
    // 所以断言也必须是顺序与分段。

    /// 走**效果解析**这条路（不是节点），这样块/治疗/状态三条分支都能单独打。
    fn apply(state: &mut CombatState, request: EffectRequest) {
        let item = EffectItem {
            request,
            chain: ChainSlot::NONE,
            owner: None,
        };
        resolve_effect(state, &item, None).expect("效果必须解析成功");
    }

    #[test]
    fn a_three_hit_attack_is_three_beats_not_one_number() {
        // **这就是 §142 的全部理由。** `diffObservations` 对下面这三下只会说"掉了 12 血"；
        // 页面于是画不出"敌人挥了三下"。
        let mut state = arena();
        give_block(&mut state, "enemy_a", 3);
        for _ in 0..3 {
            deal(&mut state, "enemy_a", 5, false);
        }
        let beats = state.beats();
        assert_eq!(beats.len(), 3, "三下必须是三条：{beats:?}");
        // 第一下被 3 点格挡吃掉了大半 —— 请求 5、挡住 3、真掉 2。
        assert_eq!((beats[0].a, beats[0].b, beats[0].c), (2, 3, 5));
        // 后两下格挡已经见底，各掉 5。
        assert_eq!((beats[1].a, beats[1].b, beats[1].c), (5, 0, 5));
        assert_eq!((beats[2].a, beats[2].b, beats[2].c), (5, 0, 5));
        for beat in beats {
            assert_eq!(beat.kind, crate::beat::BeatKind::Damage);
            assert_eq!(beat.actor, 0, "出手方是存储序第 0 个（hero）");
            assert_eq!(beat.target, 1, "承受方是存储序第 1 个（enemy_a）");
        }
        assert_eq!(health(&state, "enemy_a"), 20 - 2 - 5 - 5);
        assert_eq!(state.beats_dropped(), 0);
    }

    #[test]
    fn block_heal_and_status_change_each_land_one_beat_in_order() {
        let mut state = arena();
        state.combatant_mut(&cid("hero")).unwrap().health_current = 50;

        apply(
            &mut state,
            EffectRequest::GainBlock {
                target: Some(cid("hero")),
                amount: 5,
                // §245: 测试辅助里的"格挡"没有来源 —— 当成不是牌给的。
                from_card: false,
            },
        );
        apply(
            &mut state,
            EffectRequest::Heal {
                target: Some(cid("hero")),
                amount: 8,
            },
        );
        apply(
            &mut state,
            EffectRequest::ApplyStatus {
                target: Some(cid("enemy_a")),
                definition: StatusDefinitionId::new("standard.vulnerable").unwrap(),
                stacks: 2,
                duration: 0,
                charges: 0,
                source: Some(cid("hero")),
                source_card: None,
            },
        );
        // 同名再来一次 ⇒ **并入**已有实例（不带 `FLAG_NEW_INSTANCE`）。
        apply(
            &mut state,
            EffectRequest::ApplyStatus {
                target: Some(cid("enemy_a")),
                definition: StatusDefinitionId::new("standard.vulnerable").unwrap(),
                stacks: 1,
                duration: 0,
                charges: 0,
                source: Some(cid("hero")),
                source_card: None,
            },
        );

        let kinds: Vec<crate::beat::BeatKind> =
            state.beats().iter().map(|beat| beat.kind).collect();
        assert_eq!(
            kinds,
            vec![
                crate::beat::BeatKind::Block,
                crate::beat::BeatKind::Heal,
                crate::beat::BeatKind::StatusChanged,
                crate::beat::BeatKind::StatusChanged,
            ],
            "四件事、四条、按发生顺序"
        );
        assert_eq!(state.beats()[0].a, 5, "格挡记的是真加了多少");
        assert_eq!(state.beats()[1].a, 8, "治疗记的是真回了多少");
        assert_eq!(stacks_of(&state, "enemy_a", "standard.vulnerable"), 3);
        assert_eq!(
            state.beats()[2].flags & crate::beat::FLAG_NEW_INSTANCE,
            crate::beat::FLAG_NEW_INSTANCE,
            "第一次是新建实例"
        );
        assert_eq!(
            state.beats()[3].flags & crate::beat::FLAG_NEW_INSTANCE,
            0,
            "第二次是并入，页面不该再画一个图标"
        );
        assert_eq!(state.beat_def_text(2), Some("standard.vulnerable"));
    }

    #[test]
    fn a_heal_at_full_health_is_no_beat() {
        // 满血治疗**不是**一条"回了 0 点"。页面据此不飘一个 +0，与 `gain_block_for`
        // 里 `modified != 0` 那道门是同一条纪律。
        let mut state = arena();
        apply(
            &mut state,
            EffectRequest::Heal {
                target: Some(cid("hero")),
                amount: 8,
            },
        );
        assert!(state.beats().is_empty(), "{:?}", state.beats());
    }

    #[test]
    fn a_status_reduced_to_zero_is_a_change_then_a_removal() {
        let mut state = arena();
        give(&mut state, "enemy_a", status("status_1", "standard.strength", 2));
        apply(
            &mut state,
            EffectRequest::ModifyStatusStacks {
                target: Some(cid("enemy_a")),
                definition: StatusDefinitionId::new("standard.strength").unwrap(),
                delta: -2,
            },
        );
        let kinds: Vec<crate::beat::BeatKind> =
            state.beats().iter().map(|beat| beat.kind).collect();
        assert_eq!(
            kinds,
            vec![
                crate::beat::BeatKind::StatusChanged,
                crate::beat::BeatKind::StatusRemoved,
            ],
            "先掉层、再收图标：顺序反了页面会先看见图标消失"
        );
        assert_eq!(state.beats()[0].a, -2, "净变化是负的");
        assert_eq!(state.beat_def_text(1), Some("standard.strength"));
        assert_eq!(instances_of(&state, "enemy_a", "standard.strength"), 0);
    }

    #[test]
    fn artifact_turns_a_debuff_into_a_prevented_beat_naming_the_blocked_status() {
        let mut state = arena();
        give(&mut state, "enemy_a", status("status_1", "standard.artifact", 1));
        apply(
            &mut state,
            EffectRequest::ApplyStatus {
                target: Some(cid("enemy_a")),
                definition: StatusDefinitionId::new("standard.vulnerable").unwrap(),
                stacks: 2,
                duration: 0,
                charges: 0,
                source: Some(cid("hero")),
                source_card: None,
            },
        );
        assert_eq!(state.beats().len(), 1);
        assert_eq!(state.beats()[0].kind, crate::beat::BeatKind::StatusPrevented);
        assert_eq!(
            state.beat_def_text(0),
            Some("standard.vulnerable"),
            "名字必须是**没上成**的那个 debuff，不是 Artifact"
        );
        assert_eq!(stacks_of(&state, "enemy_a", "standard.vulnerable"), 0);
    }

    #[test]
    fn a_kill_is_damage_then_downed_and_the_minions_flee_after_it() {
        let mut state = arena();
        state
            .add_combatant({
                let mut minion = unit("minion#1", "enemy", 5, 5);
                minion.owner = Some(cid("enemy_b"));
                minion
            })
            .unwrap();
        // enemy_b 只有 10 血：这一下打死它，随从该跟着跑。
        deal(&mut state, "enemy_b", 10, true);
        assert_eq!(lifecycle(&state, "enemy_b"), CombatantLifecycleState::Downed);
        assert_eq!(
            lifecycle(&state, "minion#1"),
            CombatantLifecycleState::Escaped,
            "主人倒下 ⇒ 随从逃跑（§139）"
        );
        let kinds: Vec<crate::beat::BeatKind> =
            state.beats().iter().map(|beat| beat.kind).collect();
        assert_eq!(
            kinds,
            vec![
                crate::beat::BeatKind::Damage,
                crate::beat::BeatKind::Downed,
                crate::beat::BeatKind::Escaped,
            ],
            "伤害 → 倒下 → 逃跑：三条、这个顺序"
        );
        // 逃跑的是第 3 个战斗员（存储序 [hero, enemy_a, enemy_b, minion#1]）。
        assert_eq!(state.beats()[2].target, 3);
        assert_eq!(state.beats()[1].target, 2, "倒下的是 enemy_b");
    }

    /// §149：`Plated Armor` 被削到 0 时**必须安静地消失**（不是报错，也不是留一条 0 层实例）。
    ///
    /// 这个函数在伤害管线里，`?` 会把它返回的错误一路抛成 `StepThrew` —— 而 soak 在 §152 的
    /// 长战斗里正是撞到那个（`Problem::StepThrew` 把具体错误吞掉了，只剩"这一步抛了"）。
    /// 所以这里逐层走一遍：4 → 3 → 2 → 1 → 消失，每一步都要 `Ok`。
    #[test]
    fn plated_armor_wears_down_to_nothing_without_an_error() {
        // §210: the decrement is the content's `DamageTaken` trigger now, so this goes through the
        // full path (content + host dispatch).
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_pa", "standard.plated_armor", 4));
        for expected in [3, 2, 1] {
            deal_dispatched(
                &mut state,
                &content,
                "enemy_a",
                1,
                false,
                crate::status_bind::DamageKind::Direct,
            );
            assert_eq!(
                stacks_of(&state, "enemy_a", "standard.plated_armor"),
                expected,
                "a hit wears one plate off"
            );
        }
        deal_dispatched(
            &mut state,
            &content,
            "enemy_a",
            1,
            false,
            crate::status_bind::DamageKind::Direct,
        );
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.plated_armor"),
            0,
            "the last plate is removed, not left at zero"
        );
        // 再挨一下：没有这条状态了，管线必须照常走完（不是"找不到就报错"）。
        deal_dispatched(
            &mut state,
            &content,
            "enemy_a",
            1,
            false,
            crate::status_bind::DamageKind::Direct,
        );
        assert_eq!(health(&state, "enemy_a"), 20 - 5, "every hit still lands");
    }

    /// §210: **毒不剥甲**。这是搬迁顺手修掉的偏差：旧的硬编码用 `health_lost > 0` 判，
    /// 一次 poison tick 也会剥一层，而 wiki 写的是 "unblocked **attack** damage"。
    ///
    /// 判据分两半，缺一半就退化成"任何伤害都剥"：攻击剥一层、DoT 一层都不剥。
    #[test]
    fn plated_armor_only_wears_off_for_attacks_not_for_poison() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_pa", "standard.plated_armor", 4));
        deal_dispatched(
            &mut state,
            &content,
            "enemy_a",
            3,
            false,
            crate::status_bind::DamageKind::Dot,
        );
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.plated_armor"),
            4,
            "a poison tick must not strip a plate (wiki: attack damage)"
        );
        deal_dispatched(
            &mut state,
            &content,
            "enemy_a",
            3,
            false,
            crate::status_bind::DamageKind::Direct,
        );
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.plated_armor"),
            3,
            "an attack does strip one"
        );
    }

    /// §149：三条**伤害管线**的状态。断言的是管线里的三个位置，各一条：
    /// Intangible 在**格挡之前**（压请求），Buffer 在**格挡之后**（只挡真的掉血），
    /// Plated Armor 在**掉血之后**（只认没挡住的伤）。
    #[test]
    fn the_damage_pipeline_honours_intangible_buffer_and_plated_armor() {
        // §210: two of the three hooks are content now (Intangible = `ClampMax 1`, Plated Armor =
        // a `DamageTaken` trigger; Buffer stays in the kernel because "cancel an HP loss" is an
        // interceptor, not a modifier). So the test runs the **real** path with the image loaded --
        // with `deal` alone the clamp would not run at all.
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let direct = crate::status_bind::DamageKind::Direct;

        // ---- Intangible: 30 点进来只剩 1 点，而且格挡最多挡那 1 点 ----
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_int", "standard.intangible", 1));
        give_block(&mut state, "enemy_a", 10);
        deal_dispatched(&mut state, &content, "enemy_a", 30, false, direct);
        assert_eq!(
            health(&state, "enemy_a"),
            20,
            "Intangible 把 30 压成 1，而 1 点被格挡吃干净 ⇒ 一点血都不掉"
        );
        assert_eq!(
            block_of(&state, "enemy_a"),
            9,
            "格挡只吸收那 1 点（10 → 9），不是被 30 点吃掉"
        );
        // 成对：没有 Intangible 时同样的 30 点会打穿 10 点格挡、掉 20 血（= 直接倒下）。
        let mut plain = arena();
        give_block(&mut plain, "enemy_a", 10);
        deal_dispatched(&mut plain, &content, "enemy_a", 30, false, direct);
        assert_eq!(health(&plain, "enemy_a"), 0, "没有 Intangible 就吃满 20 点");

        // ---- Buffer: 挡下**下一次**掉血，并消耗 1 层；第二下照打 ----
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_buf", "standard.buffer", 1));
        deal_dispatched(&mut state, &content, "enemy_a", 5, false, direct);
        assert_eq!(health(&state, "enemy_a"), 20, "第一下被 Buffer 挡住");
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.buffer"),
            0,
            "Buffer 用完了（0 层实例被删）"
        );
        deal_dispatched(&mut state, &content, "enemy_a", 5, false, direct);
        assert_eq!(health(&state, "enemy_a"), 15, "第二下照打");

        // 被格挡吃干净的一下**不**消耗 Buffer（判定在格挡之后）。
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_buf2", "standard.buffer", 1));
        give_block(&mut state, "enemy_a", 10);
        deal_dispatched(&mut state, &content, "enemy_a", 5, false, direct);
        assert_eq!(health(&state, "enemy_a"), 20);
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.buffer"),
            1,
            "全被挡住 ⇒ Buffer 不该消耗"
        );

        // ---- Plated Armor: 挨到没挡住的**攻击** ⇒ 掉 1 层；全挡住 ⇒ 不掉 ----
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_pa", "standard.plated_armor", 4));
        deal_dispatched(&mut state, &content, "enemy_a", 3, false, direct);
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.plated_armor"),
            3,
            "没挡住的伤掉 1 层"
        );
        let mut state = arena();
        give(&mut state, "enemy_a", status("st_pa2", "standard.plated_armor", 4));
        give_block(&mut state, "enemy_a", 10);
        deal_dispatched(&mut state, &content, "enemy_a", 3, false, direct);
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.plated_armor"),
            4,
            "全挡住 ⇒ 不掉层（wiki: unblocked damage）"
        );
    }

    #[test]
    fn the_whirlwind_program_hits_each_enemy_once_per_x() {
        // §146：`node.repeat { Count: x.cost, Body: dealDamage{5, sel.allEnemies} }`，跑在**真镜像**
        // 的那张卡上。断言 `effects` 而不是血量：`execute` 只**入队**请求，解析是宿主的事
        // （与 `a_three_hit_attack_is_three_beats_not_one_number` 用 `deal` 直接打的分工不同）。
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let ir = Ir::new(&content);
        let index = content
            .lookup_in("whirlwind", crate::content::EK_CARD)
            .expect("whirlwind is in the image")
            .index as u32;
        // `card_program_root` 直接给 `Result<NodeRef>`（信封缺失才是 `Missing("Program")`）。
        let root = ir.card_program_root(index).expect("a program");

        let mut state = arena();
        // `execute` 会**把效果也解析掉**（`a_three_hit...` 用 `deal` 是为了只测管线），所以
        // 10 血的 `enemy_b` 在两下之后倒下 ⇒ 第三遍只打 `enemy_a`。这正是这条测试要的语义：
        // "X 遍"不假，但**死了的敌人不再是目标**。
        let mut ctx = ExecContext::new(&mut state, Some(cid("hero")), None, None, 1024)
            .with_content(&content)
            .with_x_cost(3);
        let stats = execute(root, &mut ctx).expect("X = 3 是合法次数");
        assert_eq!(stats.nodes, 4, "repeat + 三遍 dealDamage");
        assert_eq!(stats.effects, 5, "2 + 2 + 1（第三遍只剩一个活着的敌人）");
        assert_eq!(health(&state, "enemy_a"), 20 - 15, "活下来那只吃满 3 × 5");
        assert_eq!(lifecycle(&state, "enemy_b"), CombatantLifecycleState::Downed);

        // X = 0 ⇒ 一遍都不跑，而且**不是错误**（0 能量打 X 费牌是合法的）。
        let mut state = arena();
        let mut ctx = ExecContext::new(&mut state, Some(cid("hero")), None, None, 1024)
            .with_content(&content)
            .with_x_cost(0);
        let stats = execute(root, &mut ctx).expect("X = 0 合法");
        assert_eq!(stats.effects, 0, "0 遍 ⇒ 0 次请求");
    }

    #[test]
    fn a_dot_tick_is_flagged_so_it_does_not_animate_like_a_sword() {
        let mut state = arena();
        let mut ctx = ExecContext::new(&mut state, Some(cid("hero")), None, None, 1024);
        let (_, lost) = resolve_damage_of_kind(
            &mut ctx,
            &cid("enemy_a"),
            4,
            true,
            BindDamageKind::Dot,
        )
        .unwrap();
        assert_eq!(lost, 4);
        assert_eq!(state.beats().len(), 1);
        assert_eq!(
            state.beats()[0].flags & crate::beat::FLAG_DOT,
            crate::beat::FLAG_DOT
        );
    }

    #[test]
    fn a_heavy_turn_fits_in_the_log() {
        // 模块头说 64 条"是量出来的"：这里量。五个敌人各打三段（15 条伤害）+ 英雄一块 +
        // 两个状态 ⇒ 一步 18 条，丢条计数必须还是 0。每一步都清空（与 ABI 同一条规则），
        // 所以量的是**一步**而不是三步的累计 —— 后者会让"够用"变成一句空话。
        let mut state = arena();
        for index in 0..3 {
            let enemy = unit(&std::format!("enemy_x{index}"), "enemy", 40, 40);
            state.add_combatant(enemy).unwrap();
        }
        let enemies = ["enemy_a", "enemy_b", "enemy_x0", "enemy_x1", "enemy_x2"];
        for _ in 0..3 {
            state.clear_beats();
            // 这里没有宿主，触发器本来也不会跑 —— 事件只会在队列里堆积，堆到 64 就
            // `Full(PendingEvents)`。本测试量的是**日志**容量，所以顺手把队列排空。
            while state.has_pending_events() {
                let _ = state.dequeue_event();
            }
            for _name in enemies {
                for _ in 0..3 {
                    // 每一下都落在**英雄**身上：被打的是 hero，出手方无所谓。
                    deal(&mut state, "hero", 1, false);
                }
            }
            apply(
                &mut state,
                EffectRequest::GainBlock {
                    target: Some(cid("hero")),
                    amount: 3,
                    from_card: false,
                },
            );
            for _ in 0..2 {
                apply(
                    &mut state,
                    EffectRequest::ApplyStatus {
                        target: Some(cid("enemy_a")),
                        definition: StatusDefinitionId::new("standard.weak").unwrap(),
                        stacks: 1,
                        duration: 0,
                        charges: 0,
                        source: Some(cid("hero")),
                        source_card: None,
                    },
                );
            }
            assert_eq!(state.beats().len(), 18, "一步 5x3 段 + 一块 + 两状态");
            assert_eq!(state.beats_dropped(), 0, "这一步不该有丢条");
        }
    }
}

