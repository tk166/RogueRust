//! 目标选择器（`CombatantTargetSelectors`）—— 叶子模块 W3b。
//!
//! 参考实现：`RogueDeck.Core/Combat/Effects/CombatantTargetSelectors.cs`（约 600 行，31 个选择器）。
//! 上下文记录：`CombatantTargetSelectionContext(CombatState Combat, CombatantState? Source,
//! CombatantId? EventTargetId, CombatantId? IterationTarget)`。
//!
//! ## 为什么用 arena 而不是嵌套 Box
//!
//! 参考实现里有一半选择器是**复合**的（`DamagedCombatants(inner)`、`Union(lhs, rhs)`、
//! `CombatantsWithStatus(inner, status)`…）。内核**没有分配器**（`lib.rs` 规则 2），所以不能
//! 用 `Box` 表达递归。这里的做法与内容 IR 的 interning 同构：**选择器树摊平进一张定长表，
//! 复合节点用下标指向子节点**。下标 0 恒为根，`node()` 越界必须返回 `Err`，不许 panic。
//!
//! ## 冻结契约
//!
//! * `resolve` **只读** `CombatState`，绝不修改 —— 目标解析发生在效果执行之前，参考实现的
//!   `Select` 也是纯函数。
//! * 输出顺序 = **各选择器自己的枚举序**，不是统一归一化到 `state.combatants` 的存储序：
//!   叶子按存储序（`Combatants.Where(...)`）；`Union` 按"操作数依次、先见先出"（`:539-546`）；
//!   `Except` 保持**左集合**的序（`:565-567`）；`Damaged`/`With*`/`Without` 这类过滤保留
//!   **输入**的序（LINQ `Where` 不改序）；四个"挑一个"由 `OrderBy(...).ThenBy(id)` 决定；
//!   `First` 取 inner 的第一个（`:632-634`）。
//!
//!   ⚠️ 本文件第一版把这条写成"一律存储序" —— **那是错的**：`Union` 在队伍交错时给出的是
//!   `[hero, hero2, enemy_a]`（先友方操作数、后敌方操作数），存储序会是
//!   `[enemy_a, hero, hero2]`。多目标效果的结算顺序影响结果，这条线唯一的验收判据是
//!   "与引擎逐字节相同"，所以 W3c 按参考语义改正（连同数据表示）。
//! * 越界节点下标返回 `SelectorError::BadNode`，**不 panic、不截断**。
//! * `cardinality()` 是与 `resolve` 无关的**静态**声明，必须逐变体写死（参考实现是同名枚举）。
//!
//! ## 实现决定（写进注释，因为这些在签名里看不出来）
//!
//! * **中间结果 = 有序下标表**：一个节点解出的目标集合是 `[u8; MAX_COMBATANTS]`（存
//!   `state.combatants` 的存储下标）+ 长度，**表的顺序就是结果的顺序**。递归的中间结果每帧
//!   13 字节（等价的 `[CombatantId; 12]` 版本每帧 ~492 B），32 层最长合法路径约 420 B 栈。
//!   去重靠线性扫描：整个集合最多 12 个元素，为它上一个哈希表不划算。
//!   第一版用的是 `u16` 位集 + "一律存储序"：位集更省（2 B/帧）但**丢序**，表达不了
//!   `Union` 的"操作数先见先出"，所以 W3c 换成了有序表。
//! * **环检测 = 路径标记（DFS 染色）**：进节点置位、出节点清位。重复到达同一节点（菱形
//!   DAG，如 `Union(child, child)`）必须正常工作，只有**回边**报 [`SelectorError::Cycle`]；
//!   另有 `depth` 上限作为第二道独立闸门。递归深度不会超过表容量，不需要堆栈估算。
//! * **空集不是错**：`source`/`event_target`/`iteration_target` 为 `None`、或某个 id 不在本场
//!   单位表里，都解出 0 个目标并 `Ok(0)`。只有结构错误（坏下标、坏 id 引用、环）才是 `Err`。
//! * **根槽位缺失单独成错**：[`SelectorError::NoRoot`] 只在 `nodes[0]` 为空时返回；
//!   其它槽位（含递归过程中撞到的空槽/越界下标）是 [`SelectorError::BadNode`]。
//! * **`sink` 满 = 写满即停**，不是 `Err`，也不越界写、不覆盖调用方前缀（详见 `resolve` 文档）。
//! * **`cardinality` 不查子树**：参考实现的复合选择器从不按 `inner` 推导基数（`Damaged`/
//!   `Union`/`Except` 等一律是接口默认值 `ZeroOrMore`，"挑一个/取第一个"的写死 `ZeroOrOne`）。
//!   照抄写死的表而不是"聪明推导" —— `is_at_most_one` 是标量读的准入判据，推导会改变预检结果。
//!   W3c 补的四个变体逐条查过参考实现的行号，**没有一个是 `ExactlyOne`/`OneOrMore`**。

use crate::state::{Combatant, CombatantId, CombatantLifecycleState, CombatState, MAX_COMBATANTS};
use core::cmp::Ordering;

/// 一个选择器能解出几个目标（`TargetSelectorCardinality`，逐字对应）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Cardinality {
    /// 恒好一个：非空且不多于一个。
    ExactlyOne,
    /// 零个或一个。
    ZeroOrOne,
    /// 至少一个，可能多个。
    OneOrMore,
    /// 任意个，含零个。
    ZeroOrMore,
    /// 静态判不出。
    Unknown,
}

impl Cardinality {
    pub fn is_at_most_one(self) -> bool {
        matches!(self, Cardinality::ExactlyOne | Cardinality::ZeroOrOne)
    }
    pub fn is_guaranteed_non_empty(self) -> bool {
        matches!(self, Cardinality::ExactlyOne | Cardinality::OneOrMore)
    }
}

/// 叶子选择器：不含子节点的那些。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LeafSelector {
    /// `source`：事件的来源单位。
    Source,
    /// `source_including_downed`：来源，且**允许已倒下**。
    SourceIncludingDowned,
    /// `event_target`：事件的目标（无目标时为**空集**，不是错误）。
    EventTarget,
    /// `iteration_target`：`ForEach` 的当前迭代目标（不在迭代中时为空集）。
    IterationTarget,
    /// 来源方**存活**的同队单位（含来源自身）。
    AllAlliesOfSource,
    /// 来源方的敌方单位（存活）。`alive_only=false` 时含已倒下的。
    AllEnemiesOfSource { alive_only: bool },
    /// 场上全部单位。
    AllCombatants { alive_only: bool },
    /// 来源的敌方中血量最低的一个。
    LowestHealthEnemyOfSource,
    /// 来源的敌方中血量最高的一个。
    HighestHealthEnemyOfSource,
    /// 来源的同队中**受过伤**（血量 < 上限）的存活单位。
    AllDamagedAlliesOfSource,
    /// 来源的同队中血量最低的存活单位。
    LowestHealthAllyOfSource,
    /// 来源的同队中血量最高的存活单位。
    HighestHealthAllyOfSource,
    /// 明确指定的单位（唯一不依赖上下文的叶子）。
    Explicit(CombatantId),
}

/// 一元复合选择器。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UnaryOp {
    /// `DamagedCombatants(inner)`：inner 的结果里**受过伤**的那些。
    Damaged,
    /// `LowestHealthCombatant(inner)`：inner 里血量最低的一个。
    LowestHealth,
    /// `HighestHealthCombatant(inner)`：inner 里血量最高的一个。
    HighestHealth,
    // ── 下面四个是 W3b 交付后补的：参考实现里存在、但第一版冻结枚举漏掉了 ──────────────────────
    // 缺它们的时候 targets.rs 只能"如实报告做不了"，而不是假装做完了。补变体是**冻结方（我）**
    // 的责任，不是叶子的责任。
    /// `FirstTargetCombatantTargetSelector(inner)`：inner 里的**第一个**（参考 `:622`）。
    First,
    /// `DownedCombatantsTargetSelector(inner)`：inner 里**已倒下**的那些（参考 `:639`）。
    ///
    /// 判据是 `!IsAlive` —— **所有非存活生命周期状态**（`Downed`/`Dead`/`Removed`/`Escaped`/
    /// `Banished`），不是只挑 `Downed` 那一个状态。
    Downed,
    /// `LowestHealthPercentage(inner)` / `HighestHealthPercentage(inner)`（参考 `:573` / `:597`）。
    ///
    /// ⚠️ 它**不是** `LowestHealth` 的别名：键是三级排序 `(血量百分比升/降, 绝对血量升/降, id 升)`，
    /// 百分比用整数算（`100 * current / max`，参考实现只对 `max == 0` 特判成 0；`max < 0` **不特判**）。
    /// 单个 `LowestHealth` 变体表达不了它 —— 这就是它当初被漏掉的原因。
    LowestHealthPercentage,
    /// 同上的最高版本。
    HighestHealthPercentage,
}

/// 二元谓词式的复合选择器（带一个状态 id）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StatusFilter {
    /// inner 里**带有**该状态的那些（参考默认 `IncludeFallen: false`）。
    With,
    /// inner 里**不带**该状态的那些。
    Without,
    /// `WithStatus(inner, id, includeFallen: true)`（参考 `:306`）—— **含已倒下**的那一版。
    ///
    /// 复活机制要的就是它：`includeFallen: false` 会在筛选阶段就把倒下的单位丢掉，
    /// 而复活恰恰需要看见它们。
    WithIncludingFallen,
}

/// 一元复合选择器（带状态 id）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StatusPick {
    /// inner 里该状态**层数最低**的一个。
    LowestStacks,
    /// inner 里该状态**层数最高**的一个。
    HighestStacks,
}

/// 二元复合选择器。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BinaryOp {
    /// 并集。
    ///
    /// ⚠️ **序 = 按操作数依次、先见先出**（参考实现 `CombatantTargetSelectors.cs:539-546`），
    /// **不是** `state.combatants` 的存储序。
    ///
    /// 这一条是**我第一版冻结写错了**，W3b 的叶子按我写的错契约实现了存储序并用 `assert_ne!`
    /// 把"不是拼接序"钉住 —— 它没迁就，但也只能照冻结契约做。现在改回参考语义。
    ///
    /// 为什么必须改：多目标效果的**结算顺序**影响结果，而这条线唯一的验收判据是
    /// "与引擎逐字节相同"。存储序在队伍交错时会给出不同的序列，例如存储序
    /// `[enemy_a, hero, hero2, enemy_b]` 上 `Union(友方, 敌方)`：
    /// 参考 → `[hero, hero2, enemy_a]`，存储序 → `[enemy_a, hero, hero2]`。
    Union,
    /// 左集合减去右集合，**保持左集合的序**（参考 `:552`）。
    Except,
}

/// 选择器树的一个节点。子节点用**表内下标**引用。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SelectorNode {
    Leaf(LeafSelector),
    Unary { op: UnaryOp, inner: u16 },
    StatusFilter { op: StatusFilter, inner: u16, status_id: IdRef },
    /// §313：`DefinitionFilter { inner, definition_id }` —— inner 里**定义 id 等于它**的那些。
    ///
    /// 与 `StatusFilter` 同一类（先取子树、再筛一遍），所以不新造叶子选择器：那个位置
    /// 属于"从哪里开始选"，而"按定义筛"是在**已经选出来的集合**上做减法。
    DefinitionFilter { inner: u16, definition_id: IdRef },
    StatusPick { op: StatusPick, inner: u16, status_id: IdRef },
    Binary { op: BinaryOp, lhs: u16, rhs: u16 },
}

/// 表内字符串引用（下标 + 长度），指向调用方提供的 id 池。
///
/// 这里**不存 `&str`**：选择器表要放进 `const`/静态存储，而带生命周期的引用做不到。
/// 解析时由 `id_pool` 参数给出实际字节。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct IdRef {
    pub offset: u16,
    pub len: u16,
}

/// 摊平后的选择器树。`nodes[0]` 是根。
#[derive(Clone, Copy, Debug)]
pub struct SelectorTable {
    nodes: [Option<SelectorNode>; SelectorTable::MAX_NODES],
}

/// 解析用的只读上下文（对应 `CombatantTargetSelectionContext`）。
#[derive(Clone, Copy, Debug)]
pub struct SelectionContext<'a> {
    pub state: &'a CombatState,
    /// 事件来源。参考实现里可空 —— 无来源时依赖 source 的选择器解出空集。
    pub source: Option<CombatantId>,
    pub event_target: Option<CombatantId>,
    pub iteration_target: Option<CombatantId>,
}

/// 解析失败。**唯一来源是结构错误**（坏下标、坏 id 引用），不是"没选到目标"。
/// 空集是正常结果，走 `Ok(0)`。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SelectorError {
    /// 节点下标超出表长。
    BadNode(u16),
    /// 根节点缺失。
    NoRoot,
    /// `status_id` 的 `(offset, len)` 越过 id 池。
    BadId(IdRef),
    /// 表内出现自引用/环（必须检测，否则 resolve 会无限递归）。
    Cycle,
}

/// 结果写入处。定长、无分配。
#[derive(Debug)]
pub struct TargetSink<'a> {
    pub ids: &'a mut [CombatantId],
    pub len: usize,
}

/// 解析选择器表，把结果写进 `sink`，返回写入个数。
///
/// **写入顺序 = 选择器自己的序**（见模块头的冻结契约）：叶子是 `state.combatants` 存储序，
/// `Union` 是"按操作数依次、先见先出"，`Except` 是左集合的序，过滤类保留输入的序。
///
/// # sink 的语义（本实现选定，冻结签名里没有别的表达方式）
///
/// 进入时 `sink.len` 是**已经占用的槽位数**（调用方的前缀内容，例如跨多次解析累积的结果），
/// 新结果从 `sink.len` 起**追加**；返回的是本次追加的个数，退出时 `sink.len` 是新的游标。
///
/// 容量不够时的选择是**写满即停**，不是 `Err`：
/// * `SelectorError` 是冻结的，里面**没有**容量变体 —— 借用 `BadNode` 之类去表达"太满了"
///   等于对一个结构错误撒谎，而"目标太多"根本不是结构错误；
/// * 写入永不越界、永不覆盖调用方的前缀，返回的计数是**诚实的**（真的写了几个）；
/// * 调用方能无条件地避免截断：任何选择器的结果都是 `state.combatants` 的子集，
///   所以 `ids.len() >= MAX_COMBATANTS`（12）的 sink 永远装得下。
///
/// 空集是 `Ok(0)`，不是错误；`sink.ids` 长度为 0 也返回 `Ok(0)`。
pub fn resolve(
    table: &SelectorTable,
    ctx: &SelectionContext<'_>,
    id_pool: &[u8],
    sink: &mut TargetSink<'_>,
) -> Result<usize, SelectorError> {
    let mut on_path = [false; SelectorTable::MAX_NODES];
    let set = eval(table, ctx, id_pool, 0, &mut on_path, 0)?;

    // 按集合**自己的序**展开。这里刻意不遍历 `state.combatants` 再判包含 ——
    // 那等于把序抹平成存储序，而 `Union` 的序（操作数先见先出）正是要保住的东西。
    let capacity = sink.ids.len();
    let mut at = if sink.len < capacity { sink.len } else { capacity };
    let mut written = 0usize;
    for slot in set.slots() {
        if at >= capacity {
            break;
        }
        let Some(combatant) = ctx.state.combatants().get(*slot as usize) else {
            continue;
        };
        match sink.ids.get_mut(at) {
            Some(dest) => {
                *dest = combatant.id;
                at += 1;
                written += 1;
            }
            None => break,
        }
    }
    sink.len = at;
    Ok(written)
}

/// 逐变体写死的静态基数声明。
///
/// **不查子树**：参考实现里每个选择器的 `Cardinality` 要么是接口默认值 `ZeroOrMore`
/// （`CombatantTargetSelectors.cs:59`），要么是该类自己写死的常量，`Union`/`Except`/
/// `Damaged(inner)`/`WithStatus(inner, id)` **一处都没有**按 `inner` 推导。`ThenBy` 式的
/// "聪明推导"会改变 `is_at_most_one` 的答案，而那是标量读的准入判据（预检会因此放行/拒绝
/// 不同的程序），所以这里照抄写死的表。
///
/// 因此本函数**不返回 `Result` 也不可能 panic**：坏表/环一律只影响"根自己的变体是什么"。
/// 根槽位缺失（空表）时静态判不出，返回 [`Cardinality::Unknown`]。
pub fn cardinality(table: &SelectorTable) -> Cardinality {
    match table.node(0) {
        Ok(node) => node_cardinality(node),
        Err(_) => Cardinality::Unknown,
    }
}

// ---------------------------------------------------------------------------------------------
// 解析内部：一个目标集合 = 一张有序下标表，路径标记的递归，零分配
// ---------------------------------------------------------------------------------------------

/// 一个**有序**目标集合：`state.combatants()` 的存储下标序列 + 长度。
///
/// 存下标而不是 `CombatantId`：一个 id 是 41 字节（`Ident<40>`），12 个就是 492 B，而递归最深
/// 32 层。中间结果每帧 13 字节（`[u8; 12]` + len）比它省 38 倍，而且**顺序不丢**。
///
/// 顺序为什么必须是数据结构的一部分：参考实现的输出序**不是**统一的存储序 —— `Union` 是
/// "按操作数依次、先见先出"（`:539-546`），`Except` 保持左集合的序（`:565-567`），
/// 过滤类保留输入序（LINQ `Where` 不重排）。第一版用的 `u16` 位集表达不了这个（位集只有集合，
/// 没有序），所以 W3c 换成有序表。叶子仍然从 `state.combatants()` 升序收集，于是
/// "叶子的序 = 存储序"自动成立。
#[derive(Clone, Copy)]
struct TargetSet {
    slots: [u8; MAX_COMBATANTS],
    len: u8,
}

impl TargetSet {
    const EMPTY: Self = Self {
        slots: [0; MAX_COMBATANTS],
        len: 0,
    };

    /// 用到的前缀 —— **就是结果的顺序**。
    fn slots(&self) -> &[u8] {
        self.slots.get(..self.len as usize).unwrap_or(&[])
    }

    /// `{index}`；`index` 不可能是战斗单位槽位时给空集（不 panic）。
    fn one(index: usize) -> Self {
        Self::EMPTY.push(index)
    }

    /// `index` 是否已在集合里（越界即不在，不 panic；先判上界，避免 `as u8` 截断出假命中）。
    fn contains(self, index: usize) -> bool {
        index < MAX_COMBATANTS && self.slots().contains(&(index as u8))
    }

    /// 追加 `index`。**已在集合里就原样返回**（参考实现 `seen.Add(...)` 的语义：去重但不挪动
    /// 已有元素的位置），满员也原样返回 —— 集合是单位表的子集，不可能真的满。
    fn push(mut self, index: usize) -> Self {
        if index >= MAX_COMBATANTS || self.contains(index) {
            return self;
        }
        if let Some(slot) = self.slots.get_mut(self.len as usize) {
            *slot = index as u8;
            self.len += 1;
        }
        self
    }

    /// 并集，序 = **按操作数依次、先见先出**（`UnionCombatantTargetSelector` `:536-548`）。
    ///
    /// 左操作数的顺序原样保留，右操作数只贡献"左边没见过"的那些，且按右操作数自己的相对顺序
    /// 追加 —— 这正是 `seen.Add` + `List.Add` 的行为。
    fn union(self, other: Self) -> Self {
        let mut out = self;
        for slot in other.slots() {
            out = out.push(*slot as usize);
        }
        out
    }

    /// `self \ other`，**保持 self 的序**（`ExceptCombatantTargetSelector` `:563-567`：
    /// 先物化 exclude 成集合，再对 include 做 `Where`）。
    fn except(self, other: Self) -> Self {
        let mut out = Self::EMPTY;
        for slot in self.slots() {
            if !other.contains(*slot as usize) {
                out = out.push(*slot as usize);
            }
        }
        out
    }

    /// `Take(1)`：只留**第一个**（`FirstCombatantTargetSelector` `:632-634`）。
    fn first(self) -> Self {
        self.slots()
            .first()
            .map_or(Self::EMPTY, |slot| Self::EMPTY.push(*slot as usize))
    }
}

/// `CombatantState.IsAlive`（`CombatantState.cs:79`）：恰为 `Alive` 这一个生命周期状态。
/// **倒下、死亡、移除、逃走、放逐全部不算活着** —— 绝大多数选择器都要这个谓词。
fn is_alive(combatant: &Combatant) -> bool {
    combatant.lifecycle_state == CombatantLifecycleState::Alive
}

/// `combatant.Health.Current < combatant.Health.Max`（`CombatantTargetSelectors.cs:294`）。
fn is_damaged(combatant: &Combatant) -> bool {
    combatant.health_current < combatant.health_max
}

/// 该单位是否带**至少一个**该状态的实例
/// （`combatant.Statuses.Any(status => status.DefinitionId == statusDefinitionId)`，`:323`）。
///
/// 比较是**逐字节**的：`status` 是一段 `id_pool` 里的字节，不需要（也不该）先构造成
/// `StatusDefinitionId`。好处是池内任意字节都只是"匹配不到"，不会多出一个失败模式
/// （见 [`id_bytes`]）。
fn has_status(combatant: &Combatant, status: &[u8]) -> bool {
    combatant
        .statuses()
        .iter()
        .any(|instance| instance.definition_id.as_str().as_bytes() == status)
}

/// 该单位身上这个状态的**总层数**，把所有同定义实例求和
/// （`Statuses.Where(...).Sum(status => status.Stacks)`，`:408-410`）。
///
/// 用 `i64` 累加：参考实现的 `Enumerable.Sum(int)` 是 **checked** 的，总和溢出会抛
/// `OverflowException`；`no_std` 内核里既没有异常、又不该有 panic（debug 构建的 i32 溢出就是
/// panic），而层数是内容说了算的外部数据。`i64` 在参考实现不抛的**所有**取值上都给出同一个
/// 数，代价只是极端值下"不抛"，而不是"算错"。
fn status_stacks(combatant: &Combatant, status: &[u8]) -> i64 {
    let mut total: i64 = 0;
    for instance in combatant.statuses() {
        if instance.definition_id.as_str().as_bytes() == status {
            total += i64::from(instance.stacks);
        }
    }
    total
}

/// 把 `state.combatants` 里所有满足 `keep` 的成员按**存储序**收进一个集合
/// （参考实现写的是 `Combatants.Where(...)`，枚举序就是存储序）。
fn collect(state: &CombatState, mut keep: impl FnMut(&Combatant) -> bool) -> TargetSet {
    let mut set = TargetSet::EMPTY;
    for (index, combatant) in state.combatants().iter().enumerate() {
        if keep(combatant) {
            set = set.push(index);
        }
    }
    set
}

/// 保留 `set` 里满足 `keep` 的成员，**保持输入的序**。
///
/// 参考实现的每个过滤类选择器都是 `inner.ResolveTargets(ctx).Where(...)`，而 LINQ `Where`
/// 不重排：输入是 `Union` 时，过滤后的序仍带着"操作数先见先出"的痕迹。所以这里必须跟着
/// **输入**走，不能重建存储序。
fn filter(
    state: &CombatState,
    set: TargetSet,
    mut keep: impl FnMut(&Combatant) -> bool,
) -> TargetSet {
    let mut out = TargetSet::EMPTY;
    for slot in set.slots() {
        let index = *slot as usize;
        let Some(combatant) = state.combatants().get(index) else {
            continue;
        };
        if keep(combatant) {
            out = out.push(index);
        }
    }
    out
}

/// 降序比较 = 升序比较取反。
fn orient(order: Ordering, descending: bool) -> Ordering {
    if descending {
        order.reverse()
    } else {
        order
    }
}

/// `set` 里排序最靠前的那**一个**（只含存活单位）。
///
/// 参考实现把这几类都写成 `OrderBy(...).ThenBy(...).ThenBy(c => c.Id.ToString(), Ordinal)`，
/// 所以本函数支持**两级键 + id**：
/// * `Lowest/HighestHealthCombatantTargetSelector`（`:344-345` / `:429-430`）：一级 = 绝对血量；
/// * `Lowest/HighestStatusStacksCombatantTargetSelector`（`:403-404`，经 `StatusStacksOrdering`）：
///   一级 = 该状态的总层数；
/// * `LowestHealthPercentage`（`:586-588`）：一级 = 百分比**升序**，二级 = 绝对血量**升序**；
/// * `HighestHealthPercentage`（`:610-612`）：一级 = 百分比**降序**，二级 = 绝对血量**降序**。
///
/// id 恒为**升序**（`OrderByDescending` 之后的 `ThenBy` 仍是升序，`:611-612` 就是这么写的），
/// 且 `CombatantId` 的 `Ord` 就是 ASCII 序数字符串序 —— `CombatIds.cs:8-11` 把 `ToString()`
/// 覆写成原始值，所以 `Id.ToString()` 的 `StringComparer.Ordinal` 与它逐位同义。
///
/// 只挑存活单位是这几个类的共同前提（`.Where(c => c.IsAlive)`）。
fn pick(
    state: &CombatState,
    set: TargetSet,
    key_of: impl Fn(&Combatant) -> (i64, i64),
    primary_desc: bool,
    secondary_desc: bool,
) -> TargetSet {
    let mut best: Option<(usize, i64, i64, CombatantId)> = None;
    for slot in set.slots() {
        let index = *slot as usize;
        let Some(combatant) = state.combatants().get(index) else {
            continue;
        };
        if !is_alive(combatant) {
            continue;
        }
        let (primary, secondary) = key_of(combatant);
        let better = match best {
            None => true,
            Some((_, best_primary, best_secondary, best_id)) => {
                match orient(primary.cmp(&best_primary), primary_desc) {
                    Ordering::Less => true,
                    Ordering::Greater => false,
                    Ordering::Equal => {
                        match orient(secondary.cmp(&best_secondary), secondary_desc) {
                            Ordering::Less => true,
                            Ordering::Greater => false,
                            Ordering::Equal => combatant.id < best_id,
                        }
                    }
                }
            }
        };
        if better {
            best = Some((index, primary, secondary, combatant.id));
        }
    }
    best.map_or(TargetSet::EMPTY, |(index, _, _, _)| TargetSet::one(index))
}

/// 按血量挑一个：`LowestHealthCombatantTargetSelector` / `HighestHealthCombatantTargetSelector`
/// （`:329-350` / `:414-435`）。这两类只有一级键 + id，二级键恒等。
fn pick_by_health(state: &CombatState, set: TargetSet, lowest: bool) -> TargetSet {
    pick(
        state,
        set,
        |combatant| (i64::from(combatant.health_current), 0),
        !lowest,
        false,
    )
}

/// 按某状态的总层数挑一个：`Lowest/HighestStatusStacksCombatantTargetSelector`（`:359-387`）。
fn pick_by_stacks(state: &CombatState, set: TargetSet, status: &[u8], lowest: bool) -> TargetSet {
    pick(
        state,
        set,
        |combatant| (status_stacks(combatant, status), 0),
        !lowest,
        false,
    )
}

/// 血量百分比：`Health.Max == 0 ? 0 : 100 * Health.Current / Health.Max`（`:586` / `:610`）。
///
/// 两处细节照抄参考实现：① 只有 `Max == 0` 被特判成 0，`Max < 0` **不特判**；② 乘法在除法
/// **之前**（`100 * Current / Max`，不是 `100 * (Current / Max)`），整数除法向零截断，Rust 同义。
/// 用 `i64` 算：C# 那行在 unchecked 上下文里 `100 * Current` 会以 i32 回绕，而内核里 i32 溢出
/// 在 debug 下是 panic —— 正常血量范围内两者逐位一致。
fn health_percentage(combatant: &Combatant) -> i64 {
    if combatant.health_max == 0 {
        0
    } else {
        100 * i64::from(combatant.health_current) / i64::from(combatant.health_max)
    }
}

/// 按血量百分比挑一个：`LowestHealthPercentage` / `HighestHealthPercentage`
/// （`:573-592` / `:597-616`）。这两个是**独立类**，不是 `LowestHealth` 的别名：一级键是百分比，
/// 二级键是绝对血量，而且最高版的二级键**也是降序**（`ThenByDescending`，`:611`）。
fn pick_by_percentage(state: &CombatState, set: TargetSet, highest: bool) -> TargetSet {
    pick(
        state,
        set,
        |combatant| {
            (
                health_percentage(combatant),
                i64::from(combatant.health_current),
            )
        },
        highest,
        highest,
    )
}

/// `{id}`：当且仅当该 id 在**这一场**里能查到单位、且（`alive_only` 时）它是活的。
///
/// `Explicit` 传 `alive_only = false`（`:501-503`："regardless of alive status"）。
/// 查不到的 id 给空集 —— 这是 id 版上下文与参考实现的结构性差别之一：参考实现的
/// `Source` 直接握着 `CombatantState` 对象（`:87`），不需要在 `Combat.Combatants` 里查，
/// 所以一个"不在本场里的 source"在那边会照常返回它的 id；而这里 `source` 是
/// `Option<CombatantId>`，只能靠查表变成下标，查不到就只能当"没有来源"（空集，不是错误）。
/// （`Explicit` 在两边的行为一致：它本来就要求 `TryGetCombatant` 查得到，`:501`。）
fn single(state: &CombatState, id: Option<CombatantId>, alive_only: bool) -> TargetSet {
    let Some(id) = id else {
        return TargetSet::EMPTY;
    };
    let Some((index, combatant)) = state.combatants().iter().enumerate().find(|(_, c)| c.id == id)
    else {
        return TargetSet::EMPTY;
    };
    if alive_only && !is_alive(combatant) {
        TargetSet::EMPTY
    } else {
        TargetSet::one(index)
    }
}

/// 来源那一方（`same`）或对立一方的单位。**没有来源就整个空集**
/// （`AllAlliesOfSourceCombatantTargetSelector.cs:142-144`：`if (context.Source is null) return empty`）。
///
/// `alive_only = false` 只有 `AllEnemiesOfSource`（本移植的扩展位）会用；参考实现的
/// `AllAlliesOfSource`/`AllEnemiesOfSource` 都恒为存活过滤（`:148` / `:166`）。
fn team_set(
    state: &CombatState,
    source: Option<&Combatant>,
    same: bool,
    alive_only: bool,
) -> TargetSet {
    let Some(source) = source else {
        return TargetSet::EMPTY;
    };
    collect(state, |combatant| {
        let team_matches = if same {
            combatant.team_id == source.team_id
        } else {
            combatant.team_id != source.team_id
        };
        team_matches && (!alive_only || is_alive(combatant))
    })
}

/// 叶子选择器逐变体。每个分支对应参考实现的一个类，行号写在注释里。
fn resolve_leaf(leaf: LeafSelector, ctx: &SelectionContext<'_>) -> TargetSet {
    let state = ctx.state;
    let source = ctx.source.as_ref().and_then(|id| state.combatant(id));
    match leaf {
        // `SourceCombatantTargetSelector` `:80-90`。
        LeafSelector::Source => single(state, ctx.source, true),
        // `SourceIncludingDownedCombatantTargetSelector` `:103-110`。
        LeafSelector::SourceIncludingDowned => single(state, ctx.source, false),
        // `EventTargetCombatantTargetSelector` `:118-133`：查不到、或已倒下 ⇒ 空集。
        LeafSelector::EventTarget => single(state, ctx.event_target, true),
        // `IterationTargetCombatantTargetSelector` `:265-276`：同上。
        LeafSelector::IterationTarget => single(state, ctx.iteration_target, true),
        // `AllAlliesOfSourceCombatantTargetSelector` `:138-151`：存活 + 同队（**含来源自身**）。
        LeafSelector::AllAlliesOfSource => team_set(state, source, true, true),
        // `AllEnemiesOfSourceCombatantTargetSelector` `:154-169`：存活 + 异队。
        LeafSelector::AllEnemiesOfSource { alive_only } => team_set(state, source, false, alive_only),
        // `AllCombatantsTargetSelector(AliveOnly)` `:176-188`：不看来源。
        LeafSelector::AllCombatants { alive_only } => collect(state, |c| !alive_only || is_alive(c)),
        // 下面四个参考实现是**复合**写法（叶子是同一规则的别名）：
        // `LowestHealthEnemyOfSource` = `LowestHealth(AllEnemiesOfSource)` `:199-201`，
        // `HighestHealthEnemyOfSource` = `HighestHealth(AllEnemiesOfSource)` `:213-215`，
        // `LowestHealthAllyOfSource` = `LowestHealth(AllAlliesOfSource)` `:468-470`，
        // `HighestHealthAllyOfSource` = `HighestHealth(AllAlliesOfSource)` `:478-480`。
        LeafSelector::LowestHealthEnemyOfSource => {
            pick_by_health(state, team_set(state, source, false, true), true)
        }
        LeafSelector::HighestHealthEnemyOfSource => {
            pick_by_health(state, team_set(state, source, false, true), false)
        }
        LeafSelector::LowestHealthAllyOfSource => {
            pick_by_health(state, team_set(state, source, true, true), true)
        }
        LeafSelector::HighestHealthAllyOfSource => {
            pick_by_health(state, team_set(state, source, true, true), false)
        }
        // `AllDamagedAlliesOfSource` = `Damaged(AllAlliesOfSource)` `:225-227`。内层已经是存活过滤，
        // 外层只再加"血量 < 上限"。
        LeafSelector::AllDamagedAlliesOfSource => {
            filter(state, team_set(state, source, true, true), is_damaged)
        }
        // `ExplicitCombatantTargetSelector` `:495-504`：任何生命周期状态都返回。
        LeafSelector::Explicit(id) => single(state, Some(id), false),
    }
}

/// [`IdRef`] 在 id 池里指的那段字节。
///
/// **只有越界是错**（[`SelectorError::BadId`]，与冻结的错误文档一致）。池内但拼不出任何状态
/// 定义 id 的字节**不是错**：它只是"谁都不带这个状态"（比较是逐字节的，而状态实例的
/// `definition_id` 一定是 ASCII、长度 ≤ 40，所以超长/非 ASCII 的池内字节永远匹配不上）。
///
/// 用 `checked_add` + `get(..)`，绝不直接下标切。
fn id_bytes(id_pool: &[u8], id: IdRef) -> Result<&[u8], SelectorError> {
    let start = id.offset as usize;
    let end = start.checked_add(id.len as usize).ok_or(SelectorError::BadId(id))?;
    id_pool.get(start..end).ok_or(SelectorError::BadId(id))
}

/// 解一个节点，复合节点向下递归。
///
/// `on_path` 是**当前 DFS 路径**的标记，不是"见过"的集合：进节点置位、出节点清位。区别是
/// 关键的 —— 菱形（`Union(child, child)`，同一个子节点经两条边到达）必须正常解析，
/// 只有**回边**才报 [`SelectorError::Cycle`]；粘性标记会把前者误判成环。
///
/// 因为"路径上重复"直接报错，任何合法路径最多经过 `MAX_NODES` 个节点，递归深度天然有界；
/// `depth` 是**第二道独立闸门**，让"表再畸形也不可能递得比这更深"不依赖上面那句话成立。
fn eval(
    table: &SelectorTable,
    ctx: &SelectionContext<'_>,
    id_pool: &[u8],
    index: u16,
    on_path: &mut [bool; SelectorTable::MAX_NODES],
    depth: usize,
) -> Result<TargetSet, SelectorError> {
    if depth >= SelectorTable::MAX_NODES {
        // 标记在位时不可达（这么长的路径必然重复节点）；留着是"自带保险"而不是"预期路径"。
        return Err(SelectorError::Cycle);
    }
    // 下标 0 是根：它缺了是"没有根"，与别的槽位缺了不是一回事。
    let node = if index == 0 {
        table.node(0).map_err(|_| SelectorError::NoRoot)?
    } else {
        table.node(index)?
    };
    let marked = on_path
        .get_mut(index as usize)
        .ok_or(SelectorError::BadNode(index))?;
    if *marked {
        return Err(SelectorError::Cycle);
    }
    *marked = true;
    let result = eval_node(table, ctx, id_pool, node, on_path, depth);
    if let Some(marked) = on_path.get_mut(index as usize) {
        *marked = false;
    }
    result
}

/// 单个节点自己的规则 + 它对子节点的递归。
fn eval_node(
    table: &SelectorTable,
    ctx: &SelectionContext<'_>,
    id_pool: &[u8],
    node: SelectorNode,
    on_path: &mut [bool; SelectorTable::MAX_NODES],
    depth: usize,
) -> Result<TargetSet, SelectorError> {
    let state = ctx.state;
    match node {
        SelectorNode::Leaf(leaf) => Ok(resolve_leaf(leaf, ctx)),
        SelectorNode::Unary { op, inner } => {
            let set = eval(table, ctx, id_pool, inner, on_path, depth + 1)?;
            Ok(match op {
                // `DamagedCombatantsTargetSelector` `:287-296`：存活 **且** 血量 < 上限。
                UnaryOp::Damaged => filter(state, set, |c| is_alive(c) && is_damaged(c)),
                UnaryOp::LowestHealth => pick_by_health(state, set, true),
                UnaryOp::HighestHealth => pick_by_health(state, set, false),
                // `FirstCombatantTargetSelector` `:627-635`：`Take(1)`，**保留 inner 的序**
                //（所以它的结果取决于 inner 的序 —— inner 是 `Union` 时尤其明显）。
                UnaryOp::First => set.first(),
                // `DownedCombatantsTargetSelector` `:642-651`：`!IsAlive`。
                // 是**所有**非存活生命周期状态（`Downed`/`Dead`/`Removed`/`Escaped`/`Banished`），
                // 不是"只挑 `Downed` 这一个状态"。序仍跟输入走。
                UnaryOp::Downed => filter(state, set, |c| !is_alive(c)),
                // `LowestHealthPercentageCombatantTargetSelector` `:578-591`。
                UnaryOp::LowestHealthPercentage => pick_by_percentage(state, set, false),
                // `HighestHealthPercentageCombatantTargetSelector` `:602-615`。
                UnaryOp::HighestHealthPercentage => pick_by_percentage(state, set, true),
            })
        }
        SelectorNode::StatusFilter { op, inner, status_id } => {
            // 状态 id 在**进子树之前**校验：坏 id 是这张表自己的结构错误，与"选出来空不空"无关。
            let status = id_bytes(id_pool, status_id)?;
            let set = eval(table, ctx, id_pool, inner, on_path, depth + 1)?;
            Ok(match op {
                // `CombatantsWithStatusTargetSelector`，`IncludeFallen: false`（`:303-325`）：
                // 存活 **且** 带该状态。
                StatusFilter::With => filter(state, set, |c| is_alive(c) && has_status(c, status)),
                // `CombatantsWithoutStatusTargetSelector` `:442-456`：存活 **且** 不带该状态。
                StatusFilter::Without => {
                    filter(state, set, |c| is_alive(c) && !has_status(c, status))
                }
                // 同一个类的 `IncludeFallen: true` 那一半（`:320-325`）：谓词只剩
                // `c is not null && (true || c.IsAlive) && Statuses.Any(...)` —— **不筛存活**。
                // 复活机制要的正是它：倒下的单位还戴着那个标记，而 `With` 在筛选阶段就把它丢了。
                // 注意它只能看见 inner 给出的目标（`includeFallen` 不是"扩大候选集"）。
                StatusFilter::WithIncludingFallen => filter(state, set, |c| has_status(c, status)),
            })
        }
        SelectorNode::DefinitionFilter { inner, definition_id } => {
            // 定义 id 与状态 id 同样：**进子树之前**校验，坏 id 是表自己的结构错误。
            let definition = id_bytes(id_pool, definition_id)?;
            let set = eval(table, ctx, id_pool, inner, on_path, depth + 1)?;
            // 存活过滤放在这里是有意的：`Protect`/`Heal` 只认活着的友军；倒下的那只
            // 已经不在战场上（`AllAlliesOfSource` 自己也筛过一次，这里幂等）。
            Ok(filter(state, set, |c| {
                is_alive(c) && c.definition_id.as_str().as_bytes() == definition
            }))
        }
        SelectorNode::StatusPick { op, inner, status_id } => {
            let status = id_bytes(id_pool, status_id)?;
            let set = eval(table, ctx, id_pool, inner, on_path, depth + 1)?;
            Ok(pick_by_stacks(state, set, status, matches!(op, StatusPick::LowestStacks)))
        }
        SelectorNode::Binary { op, lhs, rhs } => {
            let left = eval(table, ctx, id_pool, lhs, on_path, depth + 1)?;
            let right = eval(table, ctx, id_pool, rhs, on_path, depth + 1)?;
            Ok(match op {
                // `UnionCombatantTargetSelector` `:532-549`：`seen.Add` + `List.Add` ——
                // 去重，序 = **按操作数依次、先见先出**（不是存储序）。
                // 具体例子（存储序 `[enemy_a, hero, hero2, enemy_b]`，左 = 友方、右 = 敌方）：
                // 参考 → `[hero, hero2, enemy_a]`；按存储序会是 `[enemy_a, hero, hero2]`。
                BinaryOp::Union => left.union(right),
                // `ExceptCombatantTargetSelector` `:557-568`：左减去右，保持左侧的序。
                BinaryOp::Except => left.except(right),
            })
        }
    }
}

/// 叶子的静态基数，逐变体写死（每个分支的行号 = 参考实现里 `Cardinality` 所在处）。
fn leaf_cardinality(leaf: LeafSelector) -> Cardinality {
    match leaf {
        // `:77` Source / `:99` SourceIncludingDowned / `:115` EventTarget /
        // `:263` IterationTarget / `:491` Explicit。
        LeafSelector::Source
        | LeafSelector::SourceIncludingDowned
        | LeafSelector::EventTarget
        | LeafSelector::IterationTarget
        | LeafSelector::Explicit(_) => Cardinality::ZeroOrOne,
        // `:193` LowestHealthEnemyOfSource / `:207` HighestHealthEnemyOfSource /
        // `:462` LowestHealthAllyOfSource / `:476` HighestHealthAllyOfSource。
        LeafSelector::LowestHealthEnemyOfSource
        | LeafSelector::HighestHealthEnemyOfSource
        | LeafSelector::LowestHealthAllyOfSource
        | LeafSelector::HighestHealthAllyOfSource => Cardinality::ZeroOrOne,
        // `:136` AllAlliesOfSource / `:154` AllEnemiesOfSource / `:172` AllCombatants /
        // `:219` AllDamagedAlliesOfSource —— 四个都没覆写，吃接口默认值 ZeroOrMore（`:59`）。
        LeafSelector::AllAlliesOfSource
        | LeafSelector::AllEnemiesOfSource { .. }
        | LeafSelector::AllCombatants { .. }
        | LeafSelector::AllDamagedAlliesOfSource => Cardinality::ZeroOrMore,
    }
}

/// 复合节点的静态基数，同上：不看 `inner`，只看自己是哪一类。
fn node_cardinality(node: SelectorNode) -> Cardinality {
    match node {
        SelectorNode::Leaf(leaf) => leaf_cardinality(leaf),
        // `:279` Damaged（默认 ZeroOrMore）/ `:332` LowestHealth / `:417` HighestHealth /
        // `:576` LowestHealthPercentage / `:600` HighestHealthPercentage / `:625` FirstTarget /
        // `:639` Downed。
        SelectorNode::Unary { op, .. } => match op {
            UnaryOp::Damaged => Cardinality::ZeroOrMore,
            // 五个"至多一个"的类都**写死了** `ZeroOrOne`，与 inner 是否可能为空**无关**：
            // `:332` / `:417` / `:576` / `:600` / `:625`。
            //
            // ⚠️ 冻结方在留话里猜"`FirstTarget(inner)` 的基数取决于 inner 能不能为空" ——
            // 逐条查过参考实现，**不是**：`FirstCombatantTargetSelector` 把 `ZeroOrOne` 写死
            // （`:625`，`Take(1)` 天然至多一个，而"空不空"静态判不出 ⇒ 不是 `ExactlyOne`）。
            // 按"inner 非空就 ExactlyOne"来推导会改变 `is_guaranteed_non_empty`，
            // 而那是预检放行/拒绝标量读的判据。
            UnaryOp::LowestHealth
            | UnaryOp::HighestHealth
            | UnaryOp::LowestHealthPercentage
            | UnaryOp::HighestHealthPercentage
            | UnaryOp::First => Cardinality::ZeroOrOne,
            // `DownedCombatantsTargetSelector` `:642-651` **没有** `Cardinality` 覆写
            // ⇒ 吃接口默认值 `ZeroOrMore`（`:59`）。内层是 `AllCombatants` 时它可能解出多个；
            // 内层只有存活单位时它恒为空集 —— 静态判不出，所以既不是 ZeroOrOne 也不是 OneOrMore。
            UnaryOp::Downed => Cardinality::ZeroOrMore,
        },
        // `:303` WithStatus（含 `IncludeFallen: true` 的那一半，同一个类、同一个默认值）/
        // `:437` WithoutStatus —— 都吃默认值 ZeroOrMore。
        SelectorNode::StatusFilter { .. } => Cardinality::ZeroOrMore,
        // §313：按定义筛是"筛"不是"选" —— 基数只会变小，所以与 `StatusFilter` 同一个默认值。
        SelectorNode::DefinitionFilter { .. } => Cardinality::ZeroOrMore,
        // `:363` LowestStatusStacks / `:378` HighestStatusStacks —— 都 ZeroOrOne。
        SelectorNode::StatusPick { .. } => Cardinality::ZeroOrOne,
        // `:507` Union / `:552` Except —— 都吃默认值 ZeroOrMore。
        SelectorNode::Binary { .. } => Cardinality::ZeroOrMore,
    }
}

impl SelectorTable {
    /// 表容量。取 32：标准包最深的选择器是 2 层复合，内容镜像实测远低于此。
    pub const MAX_NODES: usize = 32;

    pub const fn empty() -> Self {
        Self { nodes: [None; Self::MAX_NODES] }
    }

    pub fn set(&mut self, index: u16, node: SelectorNode) -> Result<(), SelectorError> {
        let slot = self.nodes.get_mut(index as usize).ok_or(SelectorError::BadNode(index))?;
        *slot = Some(node);
        Ok(())
    }

    pub fn node(&self, index: u16) -> Result<SelectorNode, SelectorError> {
        self.nodes
            .get(index as usize)
            .copied()
            .flatten()
            .ok_or(SelectorError::BadNode(index))
    }

    pub fn len(&self) -> usize {
        self.nodes.iter().filter(|n| n.is_some()).count()
    }

    pub fn is_empty(&self) -> bool {
        self.nodes.iter().all(|n| n.is_none())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn table_rejects_out_of_range_indexes_instead_of_panicking() {
        let mut t = SelectorTable::empty();
        assert_eq!(t.set(0, SelectorNode::Leaf(LeafSelector::Source)), Ok(()));
        assert_eq!(t.set(99, SelectorNode::Leaf(LeafSelector::Source)),
                   Err(SelectorError::BadNode(99)));
        assert_eq!(t.node(99), Err(SelectorError::BadNode(99)));
        // 空槽位也是 BadNode，不是 panic、不是默认值。
        assert_eq!(t.node(5), Err(SelectorError::BadNode(5)));
        assert_eq!(t.len(), 1);
    }

    #[test]
    fn cardinality_helpers_split_the_four_cases() {
        assert!(Cardinality::ExactlyOne.is_at_most_one());
        assert!(Cardinality::ZeroOrOne.is_at_most_one());
        assert!(!Cardinality::OneOrMore.is_at_most_one());
        assert!(!Cardinality::ZeroOrMore.is_at_most_one());
        assert!(!Cardinality::Unknown.is_at_most_one());

        assert!(Cardinality::ExactlyOne.is_guaranteed_non_empty());
        assert!(Cardinality::OneOrMore.is_guaranteed_non_empty());
        assert!(!Cardinality::ZeroOrOne.is_guaranteed_non_empty());
        assert!(!Cardinality::ZeroOrMore.is_guaranteed_non_empty());
        assert!(!Cardinality::Unknown.is_guaranteed_non_empty());
    }

    // -----------------------------------------------------------------------------------------
    // W3b：`resolve` / `cardinality` 的测试
    //
    // 这些测试瞄的是"危险的那一面"：环、坏表、空集 vs 错误、输出序、差一个的容量边界。
    // 每条断言都写在"错实现会给出什么"的对立面，避免出现永远为真的空断言。
    // -----------------------------------------------------------------------------------------

    use crate::state::{
        CombatId, CombatantDefinitionId, StatusDefinitionId, StatusInstance, StatusInstanceId,
        StatusPolarity, TeamId,
    };
    // 注意：`MAX_COMBATANTS` 由 `use super::*` 带进来（实现里现在要按它开有序表），
    // 这里**不要**再显式 import 一次，否则是重复导入。

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

    /// 一个状态实例。实例 id 与选择无关（选择只按 `definition_id` 比较、按 `stacks` 求和），
    /// 所以这里五个实例共用一个 id 是安全的。
    fn status(definition: &str, stacks: i32) -> StatusInstance {
        StatusInstance::new(
            StatusInstanceId::new("status_000001").unwrap(),
            StatusDefinitionId::new(definition).unwrap(),
            StatusPolarity::Buff,
        )
        .with_stacks(stacks)
    }

    /// 一份固定的小战斗，**存储序**是 `[enemy_a, hero, hero2, enemy_b]` —— 队伍是**交错**的，
    /// 所以"存储序"与"按队伍拼接的序"才会不同（输出序那条测试靠它）。
    ///
    /// | 下标 | id | 队伍 | 血量 | 生命周期 | 状态 |
    /// |---|---|---|---|---|---|
    /// | 0 | enemy_a | enemy | 30/30 | 活着 | — |
    /// | 1 | hero（默认来源） | player | 70/70 | 活着 | poison 5 |
    /// | 2 | hero2 | player | 40/50 | 活着（受过伤） | poison 3 + poison 3 + block 9 |
    /// | 3 | enemy_b | enemy | 0/10 | **已倒下** | poison 9 |
    fn arena() -> CombatState {
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);

        state.add_combatant(unit("enemy_a", "enemy", 30, 30)).unwrap();

        let mut hero = unit("hero", "player", 70, 70);
        hero.push_status(status("standard.poison", 5)).unwrap();
        state.add_combatant(hero).unwrap();

        let mut hero2 = unit("hero2", "player", 40, 50);
        hero2.push_status(status("standard.poison", 3)).unwrap();
        hero2.push_status(status("standard.poison", 3)).unwrap();
        hero2.push_status(status("standard.block", 9)).unwrap();
        state.add_combatant(hero2).unwrap();

        let mut fallen =
            unit("enemy_b", "enemy", 0, 10).with_lifecycle_state(CombatantLifecycleState::Downed);
        fallen.push_status(status("standard.poison", 9)).unwrap();
        state.add_combatant(fallen).unwrap();

        state
    }

    fn ctx_of(state: &CombatState, source: Option<CombatantId>) -> SelectionContext<'_> {
        SelectionContext {
            state,
            source,
            event_target: None,
            iteration_target: None,
        }
    }

    fn table_of(root: SelectorNode) -> SelectorTable {
        let mut table = SelectorTable::empty();
        table.set(0, root).unwrap();
        table
    }

    fn table_of2(root: SelectorNode, child: SelectorNode) -> SelectorTable {
        let mut table = table_of(root);
        table.set(1, child).unwrap();
        table
    }

    /// 指向池里"整整一段 id"的引用（本文件测试用的池都是一个 id 一整段）。
    fn whole(pool: &str) -> IdRef {
        IdRef {
            offset: 0,
            len: pool.len() as u16,
        }
    }

    fn names(ids: &[CombatantId]) -> Vec<String> {
        ids.iter().map(|id| id.as_str().to_string()).collect()
    }

    /// 跑一遍 `resolve`，把结果拍成 id 字符串便于断言；sink 固定 `MAX_COMBATANTS` 大。
    fn resolve_ids(
        table: &SelectorTable,
        ctx: &SelectionContext<'_>,
        id_pool: &[u8],
    ) -> Result<Vec<String>, SelectorError> {
        let mut buf = [CombatantId::EMPTY; MAX_COMBATANTS];
        let mut sink = TargetSink {
            ids: &mut buf,
            len: 0,
        };
        let written = resolve(table, ctx, id_pool, &mut sink)?;
        Ok(names(buf.get(..written).unwrap_or(&[])))
    }

    /// 用调用方给的容量与游标跑一次 `resolve`，返回 `(返回的个数, 退出时的游标)`。
    /// 把 `sink` 关在这个函数里，测试里才能在事后读缓冲区。
    fn run_with_sink(
        table: &SelectorTable,
        ctx: &SelectionContext<'_>,
        ids: &mut [CombatantId],
        len: usize,
    ) -> (usize, usize) {
        let mut sink = TargetSink { ids, len };
        let written = resolve(table, ctx, &[], &mut sink).unwrap();
        (written, sink.len)
    }

    // ---- 环：内容镜像来自外部文件，不能假设它良构 ----

    #[test]
    fn a_cycle_between_two_nodes_is_reported_and_never_followed() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));

        // 0 → 1 → 0。这是**直接**打环的那条：实现若不做路径标记（或只在"见过"上打标记却漏了
        // 回边判定），这里不是返回 Err 而是无限递归 —— 测试会以栈溢出/abort 失败，不会静默通过。
        let mut two = SelectorTable::empty();
        two.set(
            0,
            SelectorNode::Unary {
                op: UnaryOp::LowestHealth,
                inner: 1,
            },
        )
        .unwrap();
        two.set(
            1,
            SelectorNode::Unary {
                op: UnaryOp::HighestHealth,
                inner: 0,
            },
        )
        .unwrap();
        assert_eq!(resolve_ids(&two, &ctx, &[]), Err(SelectorError::Cycle));

        // 自环 0 → 0。
        let mut self_loop = SelectorTable::empty();
        self_loop
            .set(
                0,
                SelectorNode::Unary {
                    op: UnaryOp::Damaged,
                    inner: 0,
                },
            )
            .unwrap();
        assert_eq!(resolve_ids(&self_loop, &ctx, &[]), Err(SelectorError::Cycle));

        // 经过 Binary 的环：0 =(Union)⇒ 1 ⇒ 0。
        let mut via_binary = SelectorTable::empty();
        via_binary
            .set(
                0,
                SelectorNode::Binary {
                    op: BinaryOp::Union,
                    lhs: 1,
                    rhs: 2,
                },
            )
            .unwrap();
        via_binary
            .set(
                1,
                SelectorNode::Unary {
                    op: UnaryOp::HighestHealth,
                    inner: 0,
                },
            )
            .unwrap();
        via_binary
            .set(
                2,
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true }),
            )
            .unwrap();
        assert_eq!(resolve_ids(&via_binary, &ctx, &[]), Err(SelectorError::Cycle));

        // 对照：同样的形状**去掉那条回边** ⇒ Ok。没有这条，"任何复合都报 Cycle"的实现
        // 也能让上面三条断言通过 —— 那就是空断言。
        let mut acyclic = SelectorTable::empty();
        acyclic
            .set(
                0,
                SelectorNode::Binary {
                    op: BinaryOp::Union,
                    lhs: 1,
                    rhs: 2,
                },
            )
            .unwrap();
        acyclic
            .set(
                1,
                SelectorNode::Unary {
                    op: UnaryOp::HighestHealth,
                    inner: 2,
                },
            )
            .unwrap();
        acyclic
            .set(
                2,
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true }),
            )
            .unwrap();
        assert_eq!(
            resolve_ids(&acyclic, &ctx, &[]).map(|ids| ids.len()),
            Ok(3)
        );
    }

    #[test]
    fn reaching_the_same_child_twice_is_not_a_cycle() {
        // 菱形 DAG：根的两个操作数指向**同一个**子节点。这条专打"粘性标记"那个 bug ——
        // 退出时不清位的话，右操作数会看到左操作数留下的标记，把合法 DAG 误报成环。
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let mut table = table_of2(
            SelectorNode::Binary {
                op: BinaryOp::Union,
                lhs: 1,
                rhs: 1,
            },
            SelectorNode::Leaf(LeafSelector::AllAlliesOfSource),
        );
        assert_eq!(
            resolve_ids(&table, &ctx, &[]),
            Ok(vec!["hero".to_string(), "hero2".to_string()])
        );

        // 换一种汇合方式：两条边各经一个不同的节点，再汇到同一个节点。
        table
            .set(
                2,
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true }),
            )
            .unwrap();
        table
            .set(
                3,
                SelectorNode::Unary {
                    op: UnaryOp::HighestHealth,
                    inner: 2,
                },
            )
            .unwrap();
        table
            .set(
                4,
                SelectorNode::Unary {
                    op: UnaryOp::LowestHealth,
                    inner: 2,
                },
            )
            .unwrap();
        table
            .set(
                0,
                SelectorNode::Binary {
                    op: BinaryOp::Union,
                    lhs: 3,
                    rhs: 4,
                },
            )
            .unwrap();
        // 最高血的 hero(70) 并最低血的 enemy_a(30)。序是**操作数序**：lhs(最高) 在前 ⇒
        // [hero, enemy_a]。这条断言原先写的是存储序 [enemy_a, hero] —— 那是按第一版写错的
        // 契约写的，W3c 改回参考语义后一并改正（实现是对的，错的是它）。
        assert_eq!(
            resolve_ids(&table, &ctx, &[]),
            Ok(vec!["hero".to_string(), "enemy_a".to_string()])
        );
    }

    #[test]
    fn the_deepest_legal_chain_resolves_without_tripping_the_depth_cap() {
        // 把 32 个节点全用上：0..=30 是 Unary(Damaged)，31 是叶子。合法路径最长就是 32 个节点，
        // 深度闸门不能在这里误伤（它只该在"必然重复节点"时才触发）。
        let mut table = SelectorTable::empty();
        for i in 0..SelectorTable::MAX_NODES - 1 {
            table
                .set(
                    i as u16,
                    SelectorNode::Unary {
                        op: UnaryOp::Damaged,
                        inner: (i + 1) as u16,
                    },
                )
                .unwrap();
        }
        table
            .set(
                (SelectorTable::MAX_NODES - 1) as u16,
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true }),
            )
            .unwrap();
        assert_eq!(table.len(), SelectorTable::MAX_NODES);

        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        // 活着且受过伤的只有 hero2（hero 满血、enemy_a 满血、enemy_b 已倒下）。
        assert_eq!(resolve_ids(&table, &ctx, &[]), Ok(vec!["hero2".to_string()]));
    }

    // ---- 坏表：越界、空槽、坏 id ----

    #[test]
    fn a_missing_root_is_no_root_and_a_dead_child_is_bad_node() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));

        // 空表：根不存在。这正是 `NoRoot` 存在的理由 —— 别报成 `BadNode(0)`。
        assert_eq!(
            resolve_ids(&SelectorTable::empty(), &ctx, &[]),
            Err(SelectorError::NoRoot)
        );

        // 根在、子槽位从没被写过（下标 7 是空的）：必须指出是**哪个**下标，且不 panic。
        let dead_child = table_of(SelectorNode::Unary {
            op: UnaryOp::LowestHealth,
            inner: 7,
        });
        assert_eq!(
            resolve_ids(&dead_child, &ctx, &[]),
            Err(SelectorError::BadNode(7))
        );

        // 越界子下标。
        let oob = table_of2(
            SelectorNode::Binary {
                op: BinaryOp::Except,
                lhs: 1,
                rhs: 99,
            },
            SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true }),
        );
        assert_eq!(
            resolve_ids(&oob, &ctx, &[]),
            Err(SelectorError::BadNode(99))
        );

        // u16 上界同样只能得到 Err（一切下标访问都走 `get()`/`node()`）。
        let huge = table_of(SelectorNode::Unary {
            op: UnaryOp::Damaged,
            inner: u16::MAX,
        });
        assert_eq!(
            resolve_ids(&huge, &ctx, &[]),
            Err(SelectorError::BadNode(u16::MAX))
        );
    }

    #[test]
    fn a_status_id_that_runs_past_the_pool_is_bad_id() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let bad = IdRef { offset: 4, len: 8 };
        let mut table = table_of2(
            SelectorNode::StatusFilter {
                op: StatusFilter::With,
                inner: 1,
                status_id: bad,
            },
            SelectorNode::Leaf(LeafSelector::AllAlliesOfSource),
        );
        // 池只有 4 字节，"4..12" 越界。
        assert_eq!(resolve_ids(&table, &ctx, b"pois"), Err(SelectorError::BadId(bad)));

        // 同一个坏引用在 StatusPick 上也是 BadId（两个带 id 的变体都要查）。
        table
            .set(
                0,
                SelectorNode::StatusPick {
                    op: StatusPick::LowestStacks,
                    inner: 1,
                    status_id: bad,
                },
            )
            .unwrap();
        assert_eq!(resolve_ids(&table, &ctx, b"pois"), Err(SelectorError::BadId(bad)));

        // u16 上界的 offset+len 不能把检查变成 panic。
        let huge = IdRef {
            offset: u16::MAX,
            len: u16::MAX,
        };
        table
            .set(
                0,
                SelectorNode::StatusFilter {
                    op: StatusFilter::Without,
                    inner: 1,
                    status_id: huge,
                },
            )
            .unwrap();
        assert_eq!(resolve_ids(&table, &ctx, b"pois"), Err(SelectorError::BadId(huge)));

        // 空池 + 零长度引用是**合法**的（0..0），不是 BadId。
        table
            .set(
                0,
                SelectorNode::StatusFilter {
                    op: StatusFilter::Without,
                    inner: 1,
                    status_id: IdRef { offset: 0, len: 0 },
                },
            )
            .unwrap();
        assert_eq!(
            resolve_ids(&table, &ctx, b""),
            Ok(vec!["hero".to_string(), "hero2".to_string()])
        );
    }

    #[test]
    fn a_status_id_inside_the_pool_that_names_nothing_matches_nothing() {
        // 池内字节**不是**结构错误，只表示"谁都不带这个状态"。三种写法都要走这条路而不是 BadId；
        // 尤其 41 字节那条：`StatusDefinitionId` 容量是 40，若实现先去 `StatusDefinitionId::new`
        // 就会多出一个失败模式 —— 本实现要求它不存在（比较是逐字节的）。
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let non_ascii_pool: &[u8] = b"h\xc3\xa9";
        let too_long_pool: &[u8] = &[b'x'; 41];

        let cases: [(&str, IdRef, &[u8]); 3] = [
            ("non-ascii", IdRef { offset: 0, len: 2 }, non_ascii_pool),
            ("too-long", IdRef { offset: 0, len: 41 }, too_long_pool),
            ("empty", IdRef { offset: 0, len: 0 }, b"standard.poison"),
        ];
        for (label, id, pool) in cases {
            let with = table_of2(
                SelectorNode::StatusFilter {
                    op: StatusFilter::With,
                    inner: 1,
                    status_id: id,
                },
                SelectorNode::Leaf(LeafSelector::AllAlliesOfSource),
            );
            assert_eq!(resolve_ids(&with, &ctx, pool), Ok(vec![]), "{label}: With 应为空集");
            let without = table_of2(
                SelectorNode::StatusFilter {
                    op: StatusFilter::Without,
                    inner: 1,
                    status_id: id,
                },
                SelectorNode::Leaf(LeafSelector::AllAlliesOfSource),
            );
            assert_eq!(
                resolve_ids(&without, &ctx, pool),
                Ok(vec!["hero".to_string(), "hero2".to_string()]),
                "{label}: Without 应原样留下内层"
            );
        }
    }

    #[test]
    fn slots_the_root_never_reaches_are_never_visited() {
        // 内容镜像里可以有根用不到的节点（旧版本残留、重复编译）。它们不该参与解析：
        // 坏下标/坏 id 只有在**可达**时才是错误。
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let mut table = SelectorTable::empty();
        table.set(0, SelectorNode::Leaf(LeafSelector::Source)).unwrap();
        table
            .set(
                5,
                SelectorNode::Unary {
                    op: UnaryOp::Damaged,
                    inner: 999,
                },
            )
            .unwrap();
        table
            .set(
                6,
                SelectorNode::StatusFilter {
                    op: StatusFilter::With,
                    inner: 5,
                    status_id: IdRef {
                        offset: 900,
                        len: 900,
                    },
                },
            )
            .unwrap();
        assert_eq!(resolve_ids(&table, &ctx, b""), Ok(vec!["hero".to_string()]));
    }

    // ---- 空集 vs 错误 ----

    #[test]
    fn a_missing_source_is_an_empty_set_not_an_error() {
        let state = arena();
        let leaves = [
            LeafSelector::Source,
            LeafSelector::SourceIncludingDowned,
            LeafSelector::AllAlliesOfSource,
            LeafSelector::AllEnemiesOfSource { alive_only: true },
            LeafSelector::AllEnemiesOfSource { alive_only: false },
            LeafSelector::AllDamagedAlliesOfSource,
            LeafSelector::LowestHealthEnemyOfSource,
            LeafSelector::HighestHealthEnemyOfSource,
            LeafSelector::LowestHealthAllyOfSource,
            LeafSelector::HighestHealthAllyOfSource,
        ];
        // 两种"没有来源"：上下文里就是 None；以及给了一个不在本场单位表里的 id。
        for ctx in [ctx_of(&state, None), ctx_of(&state, Some(cid("ghost")))] {
            for leaf in leaves {
                assert_eq!(
                    resolve_ids(&table_of(SelectorNode::Leaf(leaf)), &ctx, &[]),
                    Ok(vec![]),
                    "{leaf:?} 无来源时必须是 Ok(0)（空集不是错误）"
                );
            }
            // 不依赖来源的叶子照常出结果 —— "空集不是错"不等于"什么都解不出来"。
            assert_eq!(
                resolve_ids(
                    &table_of(SelectorNode::Leaf(LeafSelector::AllCombatants {
                        alive_only: true
                    })),
                    &ctx,
                    &[]
                ),
                Ok(vec![
                    "enemy_a".to_string(),
                    "hero".to_string(),
                    "hero2".to_string()
                ])
            );
            assert_eq!(
                resolve_ids(
                    &table_of(SelectorNode::Leaf(LeafSelector::Explicit(cid("enemy_b")))),
                    &ctx,
                    &[]
                ),
                Ok(vec!["enemy_b".to_string()])
            );
        }

        // 没有事件目标 / 没有迭代目标：那两个叶子同样是空集而不是错误。
        let ctx = ctx_of(&state, Some(cid("hero")));
        for leaf in [LeafSelector::EventTarget, LeafSelector::IterationTarget] {
            assert_eq!(
                resolve_ids(&table_of(SelectorNode::Leaf(leaf)), &ctx, &[]),
                Ok(vec![]),
                "{leaf:?}"
            );
        }
    }

    #[test]
    fn all_combatants_alive_only_really_excludes_the_downed_unit() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let alive = resolve_ids(
            &table_of(SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true })),
            &ctx,
            &[],
        )
        .unwrap();
        let everyone = resolve_ids(
            &table_of(SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: false })),
            &ctx,
            &[],
        )
        .unwrap();
        assert_eq!(alive, ["enemy_a", "hero", "hero2"]);
        assert_eq!(everyone, ["enemy_a", "hero", "hero2", "enemy_b"]);
        // 这条才是靶心：两者必须**真的不同**，否则上面两条可能只是"场上根本没有倒下者"。
        assert_ne!(alive, everyone);
        assert_eq!(everyone.len(), alive.len() + 1);
    }

    #[test]
    fn all_enemies_alive_only_flag_includes_the_downed_enemy() {
        // `AllEnemiesOfSource{alive_only}` 的 false 位是本移植的扩展（参考实现的
        // `AllEnemiesOfSourceCombatantTargetSelector` 恒为存活过滤，`:166`）。
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        assert_eq!(
            resolve_ids(
                &table_of(SelectorNode::Leaf(LeafSelector::AllEnemiesOfSource {
                    alive_only: true
                })),
                &ctx,
                &[]
            ),
            Ok(vec!["enemy_a".to_string()])
        );
        assert_eq!(
            resolve_ids(
                &table_of(SelectorNode::Leaf(LeafSelector::AllEnemiesOfSource {
                    alive_only: false
                })),
                &ctx,
                &[]
            ),
            Ok(vec!["enemy_a".to_string(), "enemy_b".to_string()])
        );
    }

    // ---- 输出序 ----

    #[test]
    fn a_union_comes_out_in_operand_order_not_in_storage_order() {
        // 存储序 [enemy_a(敌), hero(我), hero2(我), enemy_b(敌)] 是**交错**的：
        // 左操作数（友方）= [hero, hero2]，右操作数（敌方）= [enemy_a]。
        // 参考实现是 `seen.Add` + `List.Add`（`CombatantTargetSelectors.cs:536-548`）：
        // 按操作数依次、先见先出 ⇒ [hero, hero2, enemy_a]。
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let mut table = SelectorTable::empty();
        table
            .set(
                0,
                SelectorNode::Binary {
                    op: BinaryOp::Union,
                    lhs: 1,
                    rhs: 2,
                },
            )
            .unwrap();
        table
            .set(1, SelectorNode::Leaf(LeafSelector::AllAlliesOfSource))
            .unwrap();
        table
            .set(
                2,
                SelectorNode::Leaf(LeafSelector::AllEnemiesOfSource { alive_only: true }),
            )
            .unwrap();

        assert_eq!(
            resolve_ids(&table, &ctx, &[]),
            Ok(vec![
                "hero".to_string(),
                "hero2".to_string(),
                "enemy_a".to_string()
            ])
        );
        // 明确写出"**不是**存储序"（这正是第一版冻结契约写错的那条，改回来要钉住）。
        assert_ne!(
            resolve_ids(&table, &ctx, &[]),
            Ok(vec![
                "enemy_a".to_string(),
                "hero".to_string(),
                "hero2".to_string()
            ])
        );

        // 嵌套（三操作数）也按同一规则复合：Union(Union(友方, 敌方), 全体) ——
        // 左 = [hero, hero2, enemy_a]，右 = [enemy_a, hero, hero2, enemy_b]，
        // 只有 enemy_b 是新的 ⇒ [hero, hero2, enemy_a, enemy_b]。
        table
            .set(
                0,
                SelectorNode::Binary {
                    op: BinaryOp::Union,
                    lhs: 1,
                    rhs: 4,
                },
            )
            .unwrap();
        table
            .set(1, SelectorNode::Binary { op: BinaryOp::Union, lhs: 2, rhs: 3 })
            .unwrap();
        table
            .set(2, SelectorNode::Leaf(LeafSelector::AllAlliesOfSource))
            .unwrap();
        table
            .set(
                3,
                SelectorNode::Leaf(LeafSelector::AllEnemiesOfSource { alive_only: true }),
            )
            .unwrap();
        table
            .set(
                4,
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: false }),
            )
            .unwrap();
        assert_eq!(
            resolve_ids(&table, &ctx, &[]),
            Ok(vec![
                "hero".to_string(),
                "hero2".to_string(),
                "enemy_a".to_string(),
                "enemy_b".to_string()
            ])
        );
    }

    #[test]
    fn except_subtracts_and_keeps_the_left_side_order() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let mut table = SelectorTable::empty();
        table
            .set(
                0,
                SelectorNode::Binary {
                    op: BinaryOp::Except,
                    lhs: 1,
                    rhs: 2,
                },
            )
            .unwrap();
        table
            .set(
                1,
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: false }),
            )
            .unwrap();
        table
            .set(
                2,
                SelectorNode::Leaf(LeafSelector::AllEnemiesOfSource { alive_only: false }),
            )
            .unwrap();
        // 全体（含倒下）减去敌方 = 两个友方；左操作数是叶子 ⇒ 序就是存储序。
        assert_eq!(
            resolve_ids(&table, &ctx, &[]),
            Ok(vec!["hero".to_string(), "hero2".to_string()])
        );

        // 反向：敌方减全体 = 空集（Ok(0)，不是 Err）。
        table
            .set(
                0,
                SelectorNode::Binary {
                    op: BinaryOp::Except,
                    lhs: 2,
                    rhs: 1,
                },
            )
            .unwrap();
        assert_eq!(resolve_ids(&table, &ctx, &[]), Ok(vec![]));

        // 关键：左操作数自己是有序的（这里是 Union）时，`Except` 保留的是**左集合的序**，
        // 不是存储序。左 = Union(友方, 敌方) = [hero, hero2, enemy_a]，排掉 hero2 ⇒
        // [hero, enemy_a]；按存储序会是 [enemy_a, hero]。参考 `:565-567` 只对 include 做 `Where`。
        let mut left_union = SelectorTable::empty();
        left_union
            .set(
                0,
                SelectorNode::Binary {
                    op: BinaryOp::Except,
                    lhs: 1,
                    rhs: 4,
                },
            )
            .unwrap();
        left_union
            .set(1, SelectorNode::Binary { op: BinaryOp::Union, lhs: 2, rhs: 3 })
            .unwrap();
        left_union
            .set(2, SelectorNode::Leaf(LeafSelector::AllAlliesOfSource))
            .unwrap();
        left_union
            .set(
                3,
                SelectorNode::Leaf(LeafSelector::AllEnemiesOfSource { alive_only: true }),
            )
            .unwrap();
        left_union
            .set(
                4,
                SelectorNode::Leaf(LeafSelector::Explicit(cid("hero2"))),
            )
            .unwrap();
        assert_eq!(
            resolve_ids(&left_union, &ctx, &[]),
            Ok(vec!["hero".to_string(), "enemy_a".to_string()])
        );
        assert_ne!(
            resolve_ids(&left_union, &ctx, &[]),
            Ok(vec!["enemy_a".to_string(), "hero".to_string()])
        );
    }

    // -----------------------------------------------------------------------------------------
    // W3c：冻结方补齐的五个变体（First / Downed / 两个 Percentage / WithIncludingFallen）
    // -----------------------------------------------------------------------------------------

    #[test]
    fn first_takes_the_first_of_the_inner_order() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let pick_of = |inner: u16| {
            table_of2(
                SelectorNode::Unary {
                    op: UnaryOp::First,
                    inner,
                },
                SelectorNode::Leaf(LeafSelector::AllAlliesOfSource),
            )
        };
        // 内层是叶子（存储序）：友方 = [hero, hero2] ⇒ First = hero。
        assert_eq!(
            resolve_ids(&pick_of(1), &ctx, &[]),
            Ok(vec!["hero".to_string()])
        );

        // 内层是 Union：序 = 操作数先见先出 ⇒ [hero, hero2, enemy_a] ⇒ First = hero。
        // 按存储序（[enemy_a, hero, hero2]）会得到 enemy_a —— 这条断言同时钉住 `First` 与 `Union`。
        let mut union_first = SelectorTable::empty();
        union_first
            .set(
                0,
                SelectorNode::Unary {
                    op: UnaryOp::First,
                    inner: 1,
                },
            )
            .unwrap();
        union_first
            .set(1, SelectorNode::Binary { op: BinaryOp::Union, lhs: 2, rhs: 3 })
            .unwrap();
        union_first
            .set(2, SelectorNode::Leaf(LeafSelector::AllAlliesOfSource))
            .unwrap();
        union_first
            .set(
                3,
                SelectorNode::Leaf(LeafSelector::AllEnemiesOfSource { alive_only: true }),
            )
            .unwrap();
        assert_eq!(
            resolve_ids(&union_first, &ctx, &[]),
            Ok(vec!["hero".to_string()])
        );
        assert_ne!(
            resolve_ids(&union_first, &ctx, &[]),
            Ok(vec!["enemy_a".to_string()])
        );

        // 空集上取第一个 = 空集（Ok(0)），不是错误。
        assert_eq!(
            resolve_ids(&pick_of(1), &ctx_of(&state, None), &[]),
            Ok(vec![])
        );
    }

    #[test]
    fn downed_keeps_every_non_alive_lifecycle_state_not_just_downed() {
        // `DownedCombatantsTargetSelector` 的判据是 `!c.IsAlive`（`:649`），**不是**
        // `LifecycleState == Downed`。死亡 / 移除 / 逃走 / 放逐都算 —— 这条测试专打这个区别，
        // 把 `== Downed` 写成判据的实现只会返回 1 个，这里要求 5 个。
        let mut state = CombatState::new(CombatId::new("c4").unwrap(), 3);
        state
            .add_combatant(unit("alive_one", "player", 10, 10))
            .unwrap();
        for (id, lifecycle) in [
            ("downed_one", CombatantLifecycleState::Downed),
            ("dead_one", CombatantLifecycleState::Dead),
            ("removed_one", CombatantLifecycleState::Removed),
            ("escaped_one", CombatantLifecycleState::Escaped),
            ("banished_one", CombatantLifecycleState::Banished),
        ] {
            state
                .add_combatant(unit(id, "player", 0, 10).with_lifecycle_state(lifecycle))
                .unwrap();
        }
        let ctx = ctx_of(&state, Some(cid("alive_one")));

        let all_downed = table_of2(
            SelectorNode::Unary {
                op: UnaryOp::Downed,
                inner: 1,
            },
            SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: false }),
        );
        assert_eq!(
            resolve_ids(&all_downed, &ctx, &[]),
            Ok(vec![
                "downed_one".to_string(),
                "dead_one".to_string(),
                "removed_one".to_string(),
                "escaped_one".to_string(),
                "banished_one".to_string()
            ])
        );

        // 它**只能看见 inner 给的东西**：存活过滤的内层 ⇒ `Downed` 恒空。
        let alive_inner = table_of2(
            SelectorNode::Unary {
                op: UnaryOp::Downed,
                inner: 1,
            },
            SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true }),
        );
        assert_eq!(resolve_ids(&alive_inner, &ctx, &[]), Ok(vec![]));

        // `Explicit` 允许点名非存活单位 ⇒ `Downed(Explicit(...))` 有效；点名活着的 ⇒ 空集。
        let explicit_dead = table_of2(
            SelectorNode::Unary {
                op: UnaryOp::Downed,
                inner: 1,
            },
            SelectorNode::Leaf(LeafSelector::Explicit(cid("dead_one"))),
        );
        assert_eq!(
            resolve_ids(&explicit_dead, &ctx, &[]),
            Ok(vec!["dead_one".to_string()])
        );
        let explicit_alive = table_of2(
            SelectorNode::Unary {
                op: UnaryOp::Downed,
                inner: 1,
            },
            SelectorNode::Leaf(LeafSelector::Explicit(cid("alive_one"))),
        );
        assert_eq!(resolve_ids(&explicit_alive, &ctx, &[]), Ok(vec![]));
    }

    #[test]
    fn health_percentage_is_not_lowest_health() {
        // 百分比与绝对血量**故意指向不同的人**：a 血少但百分比高，b 血多但百分比低。
        //   a: 10/100 = 10%，b: 5/10 = 50%
        // `LowestHealth` 选**绝对**最低 = b(5)；`LowestHealthPercentage` 选百分比最低 = a(10%)。
        // 四个方向两两不同 —— 这就是"百分比版是独立类、不是 LowestHealth 别名"的证据。
        let mut state = CombatState::new(CombatId::new("c5").unwrap(), 5);
        state.add_combatant(unit("a", "player", 10, 100)).unwrap();
        state.add_combatant(unit("b", "player", 5, 10)).unwrap();
        let ctx = ctx_of(&state, None);
        let pick_of = |op: UnaryOp| {
            table_of2(
                SelectorNode::Unary { op, inner: 1 },
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true }),
            )
        };
        assert_eq!(
            resolve_ids(&pick_of(UnaryOp::LowestHealth), &ctx, &[]),
            Ok(vec!["b".to_string()])
        );
        assert_eq!(
            resolve_ids(&pick_of(UnaryOp::HighestHealth), &ctx, &[]),
            Ok(vec!["a".to_string()])
        );
        assert_eq!(
            resolve_ids(&pick_of(UnaryOp::LowestHealthPercentage), &ctx, &[]),
            Ok(vec!["a".to_string()])
        );
        assert_eq!(
            resolve_ids(&pick_of(UnaryOp::HighestHealthPercentage), &ctx, &[]),
            Ok(vec!["b".to_string()])
        );
    }

    #[test]
    fn health_percentage_breaks_ties_on_absolute_health_in_both_directions() {
        // 百分比相同、绝对血量不同：c = 5/50 = 10%，d = 10/100 = 10%。
        // 参考实现：最低版 `OrderBy(pct).ThenBy(Current)`（`:587`，两个键都升序）⇒ 血少的 c；
        //          最高版 `OrderByDescending(pct).ThenByDescending(Current)`（`:611`，都降序）⇒ 血多的 d。
        // 两个方向**相反**，所以这条能抓住"二级键方向写错"或"两个方向写成同一个"的实现。
        let mut state = CombatState::new(CombatId::new("c6").unwrap(), 6);
        state.add_combatant(unit("c", "player", 5, 50)).unwrap();
        state.add_combatant(unit("d", "player", 10, 100)).unwrap();
        let ctx = ctx_of(&state, None);
        let pick_of = |op: UnaryOp| {
            table_of2(
                SelectorNode::Unary { op, inner: 1 },
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true }),
            )
        };
        assert_eq!(
            resolve_ids(&pick_of(UnaryOp::LowestHealthPercentage), &ctx, &[]),
            Ok(vec!["c".to_string()])
        );
        assert_eq!(
            resolve_ids(&pick_of(UnaryOp::HighestHealthPercentage), &ctx, &[]),
            Ok(vec!["d".to_string()])
        );
    }

    #[test]
    fn health_percentage_pins_the_zero_max_branch_the_tie_break_and_the_alive_filter() {
        let pick_of = |op: UnaryOp| {
            table_of2(
                SelectorNode::Unary { op, inner: 1 },
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true }),
            )
        };

        // `Max == 0` ⇒ 参考实现把百分比定成 **0**（`:586` / `:610`），而不是除零、也不是"当满血"。
        // e 的 max=0 ⇒ 0%；f 是 1/10 = 10% ⇒ 最低版选 e、最高版选 f。
        let mut zero_max = CombatState::new(CombatId::new("c7").unwrap(), 7);
        zero_max.add_combatant(unit("e", "player", 7, 0)).unwrap();
        zero_max.add_combatant(unit("f", "player", 1, 10)).unwrap();
        let zero_max_ctx = ctx_of(&zero_max, None);
        assert_eq!(
            resolve_ids(&pick_of(UnaryOp::LowestHealthPercentage), &zero_max_ctx, &[]),
            Ok(vec!["e".to_string()])
        );
        assert_eq!(
            resolve_ids(&pick_of(UnaryOp::HighestHealthPercentage), &zero_max_ctx, &[]),
            Ok(vec!["f".to_string()])
        );

        // 两个键全平 ⇒ 按 id **升序**取最小者，两个方向一致（`ThenBy(Id.ToString())`，`:588` / `:612`）。
        let mut tied = CombatState::new(CombatId::new("c8").unwrap(), 8);
        tied.add_combatant(unit("zz", "player", 20, 40)).unwrap();
        tied.add_combatant(unit("aa", "player", 20, 40)).unwrap();
        let tied_ctx = ctx_of(&tied, None);
        assert_eq!(
            resolve_ids(&pick_of(UnaryOp::LowestHealthPercentage), &tied_ctx, &[]),
            Ok(vec!["aa".to_string()])
        );
        assert_eq!(
            resolve_ids(&pick_of(UnaryOp::HighestHealthPercentage), &tied_ctx, &[]),
            Ok(vec!["aa".to_string()])
        );

        // 倒下的单位不参与（`.Where(c => c.IsAlive)`，`:585` / `:609`）：g 的百分比最低（0/100 = 0%）
        // 但它已倒下 ⇒ 最低版仍然选 f。
        let mut with_downed = CombatState::new(CombatId::new("c9").unwrap(), 9);
        with_downed
            .add_combatant(unit("f", "player", 1, 10))
            .unwrap();
        with_downed
            .add_combatant(
                unit("g", "player", 0, 100).with_lifecycle_state(CombatantLifecycleState::Downed),
            )
            .unwrap();
        let downed_ctx = ctx_of(&with_downed, None);
        assert_eq!(
            resolve_ids(&pick_of(UnaryOp::LowestHealthPercentage), &downed_ctx, &[]),
            Ok(vec!["f".to_string()])
        );
    }

    #[test]
    fn with_including_fallen_sees_the_units_that_with_drops() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let poison = whole("standard.poison");
        // enemy_b 已倒下，但带着 poison 9 层：`With` 在筛选阶段就把它丢了，
        // `WithIncludingFallen`（参考 `:306` 的 `includeFallen: true`）看得见它。
        let with = table_of2(
            SelectorNode::StatusFilter {
                op: StatusFilter::With,
                inner: 1,
                status_id: poison,
            },
            SelectorNode::Leaf(LeafSelector::Explicit(cid("enemy_b"))),
        );
        let with_fallen = table_of2(
            SelectorNode::StatusFilter {
                op: StatusFilter::WithIncludingFallen,
                inner: 1,
                status_id: poison,
            },
            SelectorNode::Leaf(LeafSelector::Explicit(cid("enemy_b"))),
        );
        assert_eq!(resolve_ids(&with, &ctx, b"standard.poison"), Ok(vec![]));
        assert_eq!(
            resolve_ids(&with_fallen, &ctx, b"standard.poison"),
            Ok(vec!["enemy_b".to_string()])
        );

        // 它**不扩大候选集**：只能看见 inner 给出的目标。存活过滤的内层 ⇒ 照样没有 enemy_b。
        let alive_inner = table_of2(
            SelectorNode::StatusFilter {
                op: StatusFilter::WithIncludingFallen,
                inner: 1,
                status_id: poison,
            },
            SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true }),
        );
        assert_eq!(
            resolve_ids(&alive_inner, &ctx, b"standard.poison"),
            Ok(vec!["hero".to_string(), "hero2".to_string()])
        );

        // 全体（含倒下）：序 = inner 的序（存储序）；enemy_a 不带 poison 所以不在里面。
        let all_inner = table_of2(
            SelectorNode::StatusFilter {
                op: StatusFilter::WithIncludingFallen,
                inner: 1,
                status_id: poison,
            },
            SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: false }),
        );
        assert_eq!(
            resolve_ids(&all_inner, &ctx, b"standard.poison"),
            Ok(vec![
                "hero".to_string(),
                "hero2".to_string(),
                "enemy_b".to_string()
            ])
        );

        // 坏 id 仍然是 `BadId`：这个变体与 With/Without 共用同一处校验。
        let bad = table_of2(
            SelectorNode::StatusFilter {
                op: StatusFilter::WithIncludingFallen,
                inner: 1,
                status_id: IdRef { offset: 4, len: 8 },
            },
            SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: false }),
        );
        assert_eq!(
            resolve_ids(&bad, &ctx, b"pois"),
            Err(SelectorError::BadId(IdRef { offset: 4, len: 8 }))
        );
    }

    #[test]
    fn filters_keep_the_input_order_not_the_storage_order() {
        // 过滤类选择器在参考实现里是 `inner.ResolveTargets(ctx).Where(...)`，LINQ `Where` 不重排。
        // 内层是 Union 时"输入序"与"存储序"不同：Union(友方, 敌方) = [hero, hero2, enemy_a]，
        // 去掉带 block 的 hero2 ⇒ [hero, enemy_a]；按存储序会是 [enemy_a, hero]。
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let mut table = SelectorTable::empty();
        table
            .set(
                0,
                SelectorNode::StatusFilter {
                    op: StatusFilter::Without,
                    inner: 1,
                    status_id: whole("standard.block"),
                },
            )
            .unwrap();
        table
            .set(1, SelectorNode::Binary { op: BinaryOp::Union, lhs: 2, rhs: 3 })
            .unwrap();
        table
            .set(2, SelectorNode::Leaf(LeafSelector::AllAlliesOfSource))
            .unwrap();
        table
            .set(
                3,
                SelectorNode::Leaf(LeafSelector::AllEnemiesOfSource { alive_only: true }),
            )
            .unwrap();
        assert_eq!(
            resolve_ids(&table, &ctx, b"standard.block"),
            Ok(vec!["hero".to_string(), "enemy_a".to_string()])
        );
        assert_ne!(
            resolve_ids(&table, &ctx, b"standard.block"),
            Ok(vec!["enemy_a".to_string(), "hero".to_string()])
        );
    }

    #[test]
    fn resolve_is_a_pure_read_of_the_combat_state() {
        // 目标解析发生在效果执行**之前**，参考实现的 `Select` 也是纯函数。
        let state = arena();
        let before: Vec<Combatant> = state.combatants().to_vec();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let mut table = SelectorTable::empty();
        table
            .set(
                0,
                SelectorNode::Binary {
                    op: BinaryOp::Except,
                    lhs: 1,
                    rhs: 2,
                },
            )
            .unwrap();
        table
            .set(
                1,
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: false }),
            )
            .unwrap();
        table
            .set(
                2,
                SelectorNode::StatusFilter {
                    op: StatusFilter::With,
                    inner: 3,
                    status_id: whole("standard.poison"),
                },
            )
            .unwrap();
        table
            .set(3, SelectorNode::Leaf(LeafSelector::AllAlliesOfSource))
            .unwrap();

        // 全体 \ 带毒友方 = [enemy_a, enemy_b]。
        assert_eq!(
            resolve_ids(&table, &ctx, b"standard.poison"),
            Ok(vec!["enemy_a".to_string(), "enemy_b".to_string()])
        );
        assert_eq!(state.combatants(), before.as_slice());
    }

    // ---- 各变体的语义 ----

    #[test]
    fn health_extremes_pick_the_extreme_and_break_ties_by_id() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let leaf_of = |leaf: LeafSelector| table_of(SelectorNode::Leaf(leaf));

        // 友方：hero 70/70、hero2 40/50 ⇒ 最低 hero2、最高 hero。
        assert_eq!(
            resolve_ids(&leaf_of(LeafSelector::LowestHealthAllyOfSource), &ctx, &[]),
            Ok(vec!["hero2".to_string()])
        );
        assert_eq!(
            resolve_ids(&leaf_of(LeafSelector::HighestHealthAllyOfSource), &ctx, &[]),
            Ok(vec!["hero".to_string()])
        );
        // 敌方只有一个活着的（enemy_a 30/30）；倒下的 enemy_b 不参与，即便它"看起来更惨"。
        assert_eq!(
            resolve_ids(&leaf_of(LeafSelector::LowestHealthEnemyOfSource), &ctx, &[]),
            Ok(vec!["enemy_a".to_string()])
        );
        assert_eq!(
            resolve_ids(&leaf_of(LeafSelector::HighestHealthEnemyOfSource), &ctx, &[]),
            Ok(vec!["enemy_a".to_string()])
        );

        // 复合版本 `LowestHealth(AllEnemiesOfSource)` 必须与叶子别名一致（`:199-201`）。
        let composite = table_of2(
            SelectorNode::Unary {
                op: UnaryOp::LowestHealth,
                inner: 1,
            },
            SelectorNode::Leaf(LeafSelector::AllEnemiesOfSource { alive_only: true }),
        );
        assert_eq!(
            resolve_ids(&composite, &ctx, &[]),
            resolve_ids(&leaf_of(LeafSelector::LowestHealthEnemyOfSource), &ctx, &[])
        );

        // 平手：两个敌人血量完全相同 ⇒ 两个方向都该按 id 序取最小者
        //（`OrderByDescending` 后面的 `ThenBy` **仍然是升序**，`:429-430`）。
        // 存储序里 enemy_b 在前、id 序里 enemy_a 在前 —— "取存储序第一个"的错实现会给出
        // enemy_b，所以这两条断言能抓住它。
        let mut tied = CombatState::new(CombatId::new("c2").unwrap(), 7);
        tied.add_combatant(unit("enemy_b", "enemy", 20, 20)).unwrap();
        tied.add_combatant(unit("hero", "player", 20, 20)).unwrap();
        tied.add_combatant(unit("enemy_a", "enemy", 20, 20)).unwrap();
        let tied_ctx = ctx_of(&tied, Some(cid("hero")));
        assert_eq!(
            resolve_ids(
                &leaf_of(LeafSelector::LowestHealthEnemyOfSource),
                &tied_ctx,
                &[]
            ),
            Ok(vec!["enemy_a".to_string()])
        );
        assert_eq!(
            resolve_ids(
                &leaf_of(LeafSelector::HighestHealthEnemyOfSource),
                &tied_ctx,
                &[]
            ),
            Ok(vec!["enemy_a".to_string()])
        );
    }

    #[test]
    fn status_picks_sum_every_instance_of_the_named_status() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        // poison 总层数：hero = 5（一个实例）、hero2 = 3 + 3 = 6（两个实例）、
        // enemy_b = 9（**不参与**，挑一个的选择器只挑活的）；block 9 是干扰项，不能算进来。
        let pool = "standard.poison";
        let mut table = SelectorTable::empty();
        table
            .set(
                0,
                SelectorNode::StatusPick {
                    op: StatusPick::LowestStacks,
                    inner: 1,
                    status_id: whole(pool),
                },
            )
            .unwrap();
        table
            .set(1, SelectorNode::Leaf(LeafSelector::AllAlliesOfSource))
            .unwrap();
        assert_eq!(
            resolve_ids(&table, &ctx, pool.as_bytes()),
            Ok(vec!["hero".to_string()])
        );

        // 最高：hero2(6) > hero(5)。若实现只看每个单位的**第一个实例**（hero2 的 3），
        // 这里会错给出 hero —— 这条断言就是"求和"的证据。
        table
            .set(
                0,
                SelectorNode::StatusPick {
                    op: StatusPick::HighestStacks,
                    inner: 1,
                    status_id: whole(pool),
                },
            )
            .unwrap();
        assert_eq!(
            resolve_ids(&table, &ctx, pool.as_bytes()),
            Ok(vec!["hero2".to_string()])
        );

        // 全体（含倒下）里 enemy_b 的 9 层最多，但它已倒下 ⇒ 仍然只能选 hero2。
        table
            .set(
                1,
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: false }),
            )
            .unwrap();
        assert_eq!(
            resolve_ids(&table, &ctx, pool.as_bytes()),
            Ok(vec!["hero2".to_string()])
        );
    }

    #[test]
    fn status_picks_ignore_other_definitions() {
        // a：poison 1 + block 9；b：poison 3。按 poison 最低应选 a；
        // "把所有状态一起求和"的错实现会算出 a=10 > b=3 从而选 b —— 这条能抓住它。
        let mut state = CombatState::new(CombatId::new("c3").unwrap(), 1);
        let mut a = unit("a", "player", 10, 10);
        a.push_status(status("standard.poison", 1)).unwrap();
        a.push_status(status("standard.block", 9)).unwrap();
        state.add_combatant(a).unwrap();
        let mut b = unit("b", "player", 10, 10);
        b.push_status(status("standard.poison", 3)).unwrap();
        state.add_combatant(b).unwrap();

        let ctx = ctx_of(&state, None);
        let pool = "standard.poison";
        let mut table = SelectorTable::empty();
        table
            .set(
                1,
                SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true }),
            )
            .unwrap();
        table
            .set(
                0,
                SelectorNode::StatusPick {
                    op: StatusPick::LowestStacks,
                    inner: 1,
                    status_id: whole(pool),
                },
            )
            .unwrap();
        assert_eq!(
            resolve_ids(&table, &ctx, pool.as_bytes()),
            Ok(vec!["a".to_string()])
        );
        table
            .set(
                0,
                SelectorNode::StatusPick {
                    op: StatusPick::HighestStacks,
                    inner: 1,
                    status_id: whole(pool),
                },
            )
            .unwrap();
        assert_eq!(
            resolve_ids(&table, &ctx, pool.as_bytes()),
            Ok(vec!["b".to_string()])
        );
    }

    #[test]
    fn status_filters_are_alive_only_and_definition_exact() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let poison = "standard.poison";
        let block = "standard.block";

        // 友方：hero 带 poison，hero2 带 poison + block。
        let with_poison = table_of2(
            SelectorNode::StatusFilter {
                op: StatusFilter::With,
                inner: 1,
                status_id: whole(poison),
            },
            SelectorNode::Leaf(LeafSelector::AllAlliesOfSource),
        );
        assert_eq!(
            resolve_ids(&with_poison, &ctx, poison.as_bytes()),
            Ok(vec!["hero".to_string(), "hero2".to_string()])
        );
        let without_poison = table_of2(
            SelectorNode::StatusFilter {
                op: StatusFilter::Without,
                inner: 1,
                status_id: whole(poison),
            },
            SelectorNode::Leaf(LeafSelector::AllAlliesOfSource),
        );
        assert_eq!(resolve_ids(&without_poison, &ctx, poison.as_bytes()), Ok(vec![]));

        // 定义必须精确匹配：hero 身上没有 block。
        let with_block = table_of2(
            SelectorNode::StatusFilter {
                op: StatusFilter::With,
                inner: 1,
                status_id: whole(block),
            },
            SelectorNode::Leaf(LeafSelector::AllAlliesOfSource),
        );
        assert_eq!(
            resolve_ids(&with_block, &ctx, block.as_bytes()),
            Ok(vec!["hero2".to_string()])
        );

        // 倒下者即使带着这个状态也要被两个过滤器的存活检查挡掉 —— 这是参考实现
        // `IncludeFallen: false`（`:306`）的那一半；枚举里没有 include_fallen 位（见顶部偏差说明）。
        let downed = table_of2(
            SelectorNode::StatusFilter {
                op: StatusFilter::With,
                inner: 1,
                status_id: whole(poison),
            },
            SelectorNode::Leaf(LeafSelector::Explicit(cid("enemy_b"))),
        );
        assert_eq!(resolve_ids(&downed, &ctx, poison.as_bytes()), Ok(vec![]));
        let downed_without = table_of2(
            SelectorNode::StatusFilter {
                op: StatusFilter::Without,
                inner: 1,
                status_id: whole(poison),
            },
            SelectorNode::Leaf(LeafSelector::Explicit(cid("enemy_b"))),
        );
        assert_eq!(
            resolve_ids(&downed_without, &ctx, poison.as_bytes()),
            Ok(vec![])
        );
    }

    #[test]
    fn damaged_requires_alive_and_below_full_health() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        // 叶子 `AllDamagedAlliesOfSource`（`:225`）与复合 `Damaged(AllAlliesOfSource)`（`:287`）
        // 在参考实现里是同一件事，必须给出一致结果。
        let leaf = table_of(SelectorNode::Leaf(LeafSelector::AllDamagedAlliesOfSource));
        let composite = table_of2(
            SelectorNode::Unary {
                op: UnaryOp::Damaged,
                inner: 1,
            },
            SelectorNode::Leaf(LeafSelector::AllAlliesOfSource),
        );
        assert_eq!(resolve_ids(&leaf, &ctx, &[]), Ok(vec!["hero2".to_string()]));
        assert_eq!(
            resolve_ids(&composite, &ctx, &[]),
            resolve_ids(&leaf, &ctx, &[])
        );

        // 满血的 hero 不算"受过伤"；倒下的 enemy_b（0/10）更不算，它必须先过存活检查。
        let everyone = table_of2(
            SelectorNode::Unary {
                op: UnaryOp::Damaged,
                inner: 1,
            },
            SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: false }),
        );
        assert_eq!(
            resolve_ids(&everyone, &ctx, &[]),
            Ok(vec!["hero2".to_string()])
        );
    }

    #[test]
    fn source_variants_differ_exactly_on_a_downed_source() {
        let state = arena();
        // 来源换成倒下的 enemy_b。
        let downed_ctx = ctx_of(&state, Some(cid("enemy_b")));
        let source = table_of(SelectorNode::Leaf(LeafSelector::Source));
        let including = table_of(SelectorNode::Leaf(LeafSelector::SourceIncludingDowned));
        assert_eq!(resolve_ids(&source, &downed_ctx, &[]), Ok(vec![]));
        assert_eq!(
            resolve_ids(&including, &downed_ctx, &[]),
            Ok(vec!["enemy_b".to_string()])
        );

        // 活着的来源：两者一致（`SourceIncludingDowned` 只是放宽，不是换一套语义）。
        let alive_ctx = ctx_of(&state, Some(cid("hero")));
        assert_eq!(
            resolve_ids(&source, &alive_ctx, &[]),
            Ok(vec!["hero".to_string()])
        );
        assert_eq!(
            resolve_ids(&including, &alive_ctx, &[]),
            resolve_ids(&source, &alive_ctx, &[])
        );

        // 队伍比较仍按 TeamId 走，但"含来源自身"只在来源活着时成立：
        // 倒下的 enemy_b 的自己算敌方那一队，且**不是自己的盟友**。
        assert_eq!(
            resolve_ids(
                &table_of(SelectorNode::Leaf(LeafSelector::AllAlliesOfSource)),
                &downed_ctx,
                &[]
            ),
            Ok(vec!["enemy_a".to_string()])
        );
        assert_eq!(
            resolve_ids(
                &table_of(SelectorNode::Leaf(LeafSelector::AllEnemiesOfSource {
                    alive_only: false
                })),
                &downed_ctx,
                &[]
            ),
            Ok(vec!["hero".to_string(), "hero2".to_string()])
        );
    }

    #[test]
    fn event_and_iteration_targets_require_a_living_unit_in_this_fight() {
        let state = arena();
        let mut ctx = ctx_of(&state, Some(cid("hero")));
        let event = table_of(SelectorNode::Leaf(LeafSelector::EventTarget));
        let iteration = table_of(SelectorNode::Leaf(LeafSelector::IterationTarget));

        ctx.event_target = Some(cid("hero2"));
        ctx.iteration_target = Some(cid("enemy_a"));
        assert_eq!(
            resolve_ids(&event, &ctx, &[]),
            Ok(vec!["hero2".to_string()])
        );
        assert_eq!(
            resolve_ids(&iteration, &ctx, &[]),
            Ok(vec!["enemy_a".to_string()])
        );

        // 倒下的目标 ⇒ 空集（`:130-132` / `:272-275`）。
        ctx.event_target = Some(cid("enemy_b"));
        ctx.iteration_target = Some(cid("enemy_b"));
        assert_eq!(resolve_ids(&event, &ctx, &[]), Ok(vec![]));
        assert_eq!(resolve_ids(&iteration, &ctx, &[]), Ok(vec![]));

        // 不在本场里的 id ⇒ 空集，不是 Err。
        ctx.event_target = Some(cid("ghost"));
        assert_eq!(resolve_ids(&event, &ctx, &[]), Ok(vec![]));
    }

    #[test]
    fn explicit_naming_ignores_lifecycle_but_not_membership() {
        let state = arena();
        let ctx = ctx_of(&state, None);
        // `:499-503`：明确点名时任何生命周期状态都返回（复活类机制要的"还戴着标记的那具身体"）。
        assert_eq!(
            resolve_ids(
                &table_of(SelectorNode::Leaf(LeafSelector::Explicit(cid("enemy_b")))),
                &ctx,
                &[]
            ),
            Ok(vec!["enemy_b".to_string()])
        );
        // 查不到 ⇒ 空集（Ok(0)），不是 Err。
        assert_eq!(
            resolve_ids(
                &table_of(SelectorNode::Leaf(LeafSelector::Explicit(cid("ghost")))),
                &ctx,
                &[]
            ),
            Ok(vec![])
        );
    }

    // ---- sink 容量边界 ----

    #[test]
    fn a_sink_one_slot_short_stops_at_capacity_and_reports_the_honest_count() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let table = table_of(SelectorNode::Leaf(LeafSelector::AllCombatants {
            alive_only: false,
        }));

        // 4 个目标、容量 3 —— 正好差一个。返回的计数是诚实的：真的只写了 3 个。
        let mut buf = [CombatantId::EMPTY; 3];
        let (written, cursor) = run_with_sink(&table, &ctx, &mut buf, 0);
        assert_eq!((written, cursor), (3, 3));
        // 写进去的是**结果序的前缀**（这里的根是叶子 ⇒ 结果序就是存储序）：不越界、不乱序。
        assert_eq!(names(&buf), ["enemy_a", "hero", "hero2"]);

        // 容量刚好：4 个全进去，返回值与游标都对得上。
        let mut exact = [CombatantId::EMPTY; 4];
        let (written, cursor) = run_with_sink(&table, &ctx, &mut exact, 0);
        assert_eq!((written, cursor), (4, 4));
        assert_eq!(names(&exact), ["enemy_a", "hero", "hero2", "enemy_b"]);
    }

    #[test]
    fn a_sink_appends_after_the_callers_prefix_and_a_tiny_sink_is_still_ok() {
        let state = arena();
        let ctx = ctx_of(&state, Some(cid("hero")));
        let allies = table_of(SelectorNode::Leaf(LeafSelector::AllAlliesOfSource));

        // 调用方已经写了 1 个（跨多次解析累积的场景）：结果从下标 1 起追加，前缀不被覆盖。
        let mut buf = [CombatantId::EMPTY; 4];
        buf[0] = cid("sentinel");
        let (written, cursor) = run_with_sink(&allies, &ctx, &mut buf, 1);
        assert_eq!((written, cursor), (2, 3));
        assert_eq!(names(buf.get(..cursor).unwrap_or(&[])), ["sentinel", "hero", "hero2"]);
        assert_eq!(buf[3].as_str(), ""); // 没写的槽位保持原样，没被塞垃圾

        // 已经满了的 sink：一个也写不进去，但**不是 Err**（装不下不是结构错误）。
        let mut full = [CombatantId::EMPTY; 1];
        let (written, cursor) = run_with_sink(&allies, &ctx, &mut full, 1);
        assert_eq!((written, cursor), (0, 1));
        assert_eq!(full[0].as_str(), "");

        // 零容量 sink：同样只是 Ok(0)。
        let mut none: [CombatantId; 0] = [];
        let (written, cursor) = run_with_sink(&allies, &ctx, &mut none, 0);
        assert_eq!((written, cursor), (0, 0));

        // 更荒谬的入参（游标超过容量）也只能被夹住，不能越界写。
        let mut tiny = [CombatantId::EMPTY; 2];
        let (written, cursor) = run_with_sink(&allies, &ctx, &mut tiny, 99);
        assert_eq!((written, cursor), (0, 2));
    }

    // ---- cardinality：逐变体 ----

    #[test]
    fn cardinality_of_every_leaf_variant_matches_the_reference() {
        // 每个期望值都来自参考实现里那一行的 `Cardinality`（行号见 `leaf_cardinality` 的注释）。
        let cases: [(LeafSelector, Cardinality); 15] = [
            (LeafSelector::Source, Cardinality::ZeroOrOne),
            (LeafSelector::SourceIncludingDowned, Cardinality::ZeroOrOne),
            (LeafSelector::EventTarget, Cardinality::ZeroOrOne),
            (LeafSelector::IterationTarget, Cardinality::ZeroOrOne),
            (LeafSelector::Explicit(cid("whoever")), Cardinality::ZeroOrOne),
            (LeafSelector::LowestHealthEnemyOfSource, Cardinality::ZeroOrOne),
            (LeafSelector::HighestHealthEnemyOfSource, Cardinality::ZeroOrOne),
            (LeafSelector::LowestHealthAllyOfSource, Cardinality::ZeroOrOne),
            (LeafSelector::HighestHealthAllyOfSource, Cardinality::ZeroOrOne),
            (LeafSelector::AllAlliesOfSource, Cardinality::ZeroOrMore),
            (
                LeafSelector::AllEnemiesOfSource { alive_only: true },
                Cardinality::ZeroOrMore,
            ),
            (
                LeafSelector::AllEnemiesOfSource { alive_only: false },
                Cardinality::ZeroOrMore,
            ),
            (
                LeafSelector::AllCombatants { alive_only: true },
                Cardinality::ZeroOrMore,
            ),
            (
                LeafSelector::AllCombatants { alive_only: false },
                Cardinality::ZeroOrMore,
            ),
            (LeafSelector::AllDamagedAlliesOfSource, Cardinality::ZeroOrMore),
        ];
        for (leaf, expected) in cases {
            let got = cardinality(&table_of(SelectorNode::Leaf(leaf)));
            assert_eq!(got, expected, "{leaf:?}");
        }
        // 注意：`ExactlyOne`/`OneOrMore` 在这张表里**永远不出现** —— 参考实现的选择器集合里
        // 也没有任何一个声明了它们（`grep 'Cardinality =>' CombatantTargetSelectors.cs` 只有
        // ZeroOrOne 与默认的 ZeroOrMore）。枚举留着这两个变体是给未来内容用的。
    }

    #[test]
    fn cardinality_of_every_composite_variant_matches_the_reference() {
        let child = SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: true });
        let id = IdRef { offset: 0, len: 0 };
        let cases = [
            (
                SelectorNode::Unary {
                    op: UnaryOp::Damaged,
                    inner: 1,
                },
                Cardinality::ZeroOrMore,
            ),
            (
                SelectorNode::Unary {
                    op: UnaryOp::LowestHealth,
                    inner: 1,
                },
                Cardinality::ZeroOrOne,
            ),
            (
                SelectorNode::Unary {
                    op: UnaryOp::HighestHealth,
                    inner: 1,
                },
                Cardinality::ZeroOrOne,
            ),
            // ── W3c 补的四个 UnaryOp：逐条从参考实现查出来的，**不是**按名字猜的 ──────────────
            // `:625` `FirstCombatantTargetSelector`：写死 ZeroOrOne。
            // （冻结方的留话猜"取决于 inner 能不能为空" —— 参考实现不这么做。）
            (
                SelectorNode::Unary {
                    op: UnaryOp::First,
                    inner: 1,
                },
                Cardinality::ZeroOrOne,
            ),
            // `:576` `LowestHealthPercentageCombatantTargetSelector`：写死 ZeroOrOne。
            (
                SelectorNode::Unary {
                    op: UnaryOp::LowestHealthPercentage,
                    inner: 1,
                },
                Cardinality::ZeroOrOne,
            ),
            // `:600` `HighestHealthPercentageCombatantTargetSelector`：写死 ZeroOrOne。
            (
                SelectorNode::Unary {
                    op: UnaryOp::HighestHealthPercentage,
                    inner: 1,
                },
                Cardinality::ZeroOrOne,
            ),
            // `:639-653` `DownedCombatantsTargetSelector`：**没有任何 `Cardinality` 覆写**，
            // 所以是接口默认值 ZeroOrMore（`:59`）—— 内层是全体时它可能解出多个。
            (
                SelectorNode::Unary {
                    op: UnaryOp::Downed,
                    inner: 1,
                },
                Cardinality::ZeroOrMore,
            ),
            (
                SelectorNode::StatusFilter {
                    op: StatusFilter::With,
                    inner: 1,
                    status_id: id,
                },
                Cardinality::ZeroOrMore,
            ),
            (
                SelectorNode::StatusFilter {
                    op: StatusFilter::Without,
                    inner: 1,
                    status_id: id,
                },
                Cardinality::ZeroOrMore,
            ),
            // `includeFallen: true` 是**同一个类**的另一个开关（`:303`），`Cardinality` 没覆写 ⇒
            // 默认 ZeroOrMore。它不改变基数（改的是"筛不筛存活"），所以与 With/Without 同值。
            (
                SelectorNode::StatusFilter {
                    op: StatusFilter::WithIncludingFallen,
                    inner: 1,
                    status_id: id,
                },
                Cardinality::ZeroOrMore,
            ),
            (
                SelectorNode::StatusPick {
                    op: StatusPick::LowestStacks,
                    inner: 1,
                    status_id: id,
                },
                Cardinality::ZeroOrOne,
            ),
            (
                SelectorNode::StatusPick {
                    op: StatusPick::HighestStacks,
                    inner: 1,
                    status_id: id,
                },
                Cardinality::ZeroOrOne,
            ),
            (
                SelectorNode::Binary {
                    op: BinaryOp::Union,
                    lhs: 1,
                    rhs: 1,
                },
                Cardinality::ZeroOrMore,
            ),
            (
                SelectorNode::Binary {
                    op: BinaryOp::Except,
                    lhs: 1,
                    rhs: 1,
                },
                Cardinality::ZeroOrMore,
            ),
        ];
        for (node, expected) in cases {
            let mut table = table_of(node);
            table.set(1, child).unwrap();
            assert_eq!(cardinality(&table), expected, "{node:?}");
        }
    }

    #[test]
    fn cardinality_never_looks_at_the_children() {
        // 参考实现的复合选择器**从不**按 inner 推导基数：`LowestHealth(Source)` 仍然是 ZeroOrOne，
        // 不是 ExactlyOne。这条断言就是"别自作聪明推导"的守卫 —— `is_at_most_one` 是标量读的
        // 准入判据，推导会改变预检放行/拒绝的程序集合。
        let mut narrowed = table_of2(
            SelectorNode::Unary {
                op: UnaryOp::LowestHealth,
                inner: 1,
            },
            SelectorNode::Leaf(LeafSelector::Source),
        );
        assert_eq!(cardinality(&narrowed), Cardinality::ZeroOrOne);
        assert!(cardinality(&narrowed).is_at_most_one());
        assert!(!cardinality(&narrowed).is_guaranteed_non_empty());

        // `Damaged(Source)`（内层至多一个）也还是 ZeroOrMore —— 参考实现 `:279` 没有覆写。
        narrowed
            .set(
                0,
                SelectorNode::Unary {
                    op: UnaryOp::Damaged,
                    inner: 1,
                },
            )
            .unwrap();
        assert_eq!(cardinality(&narrowed), Cardinality::ZeroOrMore);
        assert!(!cardinality(&narrowed).is_at_most_one());

        // `First(Source)`：`Take(1)` 天然至多一个 ⇒ ZeroOrOne（**不是**按 inner 推出来的
        // ZeroOrOne），而且**不是** ExactlyOne —— "inner 非空"与否静态判不出，`:625` 也只写
        // ZeroOrOne。这一条就是冲着"按 inner 推导"那句留话写的。
        narrowed
            .set(
                0,
                SelectorNode::Unary {
                    op: UnaryOp::First,
                    inner: 1,
                },
            )
            .unwrap();
        assert_eq!(cardinality(&narrowed), Cardinality::ZeroOrOne);
        assert!(cardinality(&narrowed).is_at_most_one());
        assert!(!cardinality(&narrowed).is_guaranteed_non_empty());

        // `First(AllCombatants)`：inner 是 ZeroOrMore ⇒ 结果仍是 ZeroOrOne（至多一个），
        // 反过来 `Downed(AllCombatants)` 仍是 ZeroOrMore（可能多个）。两个方向都不看 inner。
        narrowed
            .set(1, SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only: false }))
            .unwrap();
        assert_eq!(cardinality(&narrowed), Cardinality::ZeroOrOne);
        narrowed
            .set(
                0,
                SelectorNode::Unary {
                    op: UnaryOp::Downed,
                    inner: 1,
                },
            )
            .unwrap();
        assert_eq!(cardinality(&narrowed), Cardinality::ZeroOrMore);
    }

    #[test]
    fn cardinality_of_a_bad_table_is_unknown_and_never_panics() {
        // 空表：根不存在 ⇒ 静态判不出（这个函数**不返回 Result**，所以它绝不能 panic）。
        assert_eq!(cardinality(&SelectorTable::empty()), Cardinality::Unknown);

        // 根合法、子下标是坏的：基数是根自己的静态声明，与子树无关 ⇒ 常量，不是 Unknown。
        let bad_child = table_of(SelectorNode::Unary {
            op: UnaryOp::LowestHealth,
            inner: 999,
        });
        assert_eq!(cardinality(&bad_child), Cardinality::ZeroOrOne);

        // 环：既不 panic 也不无限递归（`cardinality` 根本不进子树）。
        let mut cyclic = SelectorTable::empty();
        cyclic
            .set(
                0,
                SelectorNode::Unary {
                    op: UnaryOp::Damaged,
                    inner: 0,
                },
            )
            .unwrap();
        assert_eq!(cardinality(&cyclic), Cardinality::ZeroOrMore);
    }
}
