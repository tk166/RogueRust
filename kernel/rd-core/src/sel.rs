//! 把 IR 的 `sel.*` 节点编译成 [`crate::targets`] 的 arena 形式。
//!
//! ## 为什么需要这一层
//!
//! `ir.rs` 只把 `sel.*` 认成"一个 kind + 一堆字段"，`targets.rs` 只认
//! `SelectorNode`（叶子/复合，子节点用表内下标记）。两边中间缺一个**翻译**：
//! 把 `sel.withStatus { Inner: <term>, StatusDefinitionId: "doubt" }` 变成
//! `StatusFilter { op: With, inner: 1, status_id: IdRef{…} }` + arena 里的一条叶子。
//!
//! 这一层**不做解析**（不查"谁带这个状态"），只做结构翻译。
//!
//! ## 范围：只做战斗员选择器
//!
//! 镜像里 14 种 `sel.*`，其中 **10 种是战斗员选择器**（都能落到 `targets.rs`），
//! 另 4 种是**卡选择器或玩家选择** —— `sel.deckCards` / `sel.matching` / `sel.random` / `sel.choose`。
//! 它们不出现在基础出牌路径上，v1 不做，遇到返回 [`SelError::UnsupportedKind`]。
//!
//! ⚠️ **不许把不支持的当成"空集"**：一张"选择你牌库里一张牌升级"的牌如果被当成"不选任何牌"，
//! 它会安静地什么都不做 —— 那比报错糟得多。
//!
//! ## 一个免费的交叉校验
//!
//! IR 里的 `sel.*` 自带 `Cardinality` 字段（字符串，引擎序列化出来的元数据），
//! 而 `targets.rs` 的 [`crate::targets::cardinality`] 是**静态写死**的（照参考实现逐变体查的）。
//! 两者对同一个选择器**必须永远一致** —— 不一致就说明有一边写错了。
//! [`CompiledSelector::declared_cardinality`] 让这件事可以被测试断言。

use crate::ir::{IrError, NodeRef};
use crate::state::CombatantId;
use crate::targets::{
    self, Cardinality, IdRef, LeafSelector, SelectorError, SelectorNode, SelectorTable,
    SelectionContext, StatusFilter, TargetSink,
};

/// 编译期的结构错误。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SelError {
    /// 底层 IR 读取失败。
    Ir(IrError),
    /// 这一种 `sel.*` 不在 v1 的战斗路径上（卡选择器 / 玩家选择）。
    UnsupportedKind,
    /// 判别串根本不是 `sel.*`。
    NotASelector,
    /// 子选择器不像选择器（例如 `StatusFilter.Inner` 指到一个表达式上）。
    InnerNotASelector,
    /// arena 满了（[`SelectorTable::MAX_NODES`]）。
    TableFull,
    /// 串池装不下状态 id。
    PoolFull,
    /// 缺少结构上必须有的字段（例如 `sel.withStatus` 没有 `Inner`）。
    MissingInner,
    /// 状态选择器没有 `StatusDefinitionId`。
    ///
    /// ⚠️ **不许把它当成空串 id**：空串永远匹配不到任何状态，于是"带某状态的那些"会安静地变成
    /// 空集 —— 那正是本模块最不该犯的错（见模块头）。真实镜像里 6 条状态选择器都带这个字段，
    /// 这一条只在镜像被改坏时可达。
    MissingStatusId,
    /// `Cardinality` 字段的串不是 [`crate::targets::Cardinality`] 的任何一个线名。
    ///
    /// [`crate::targets::Cardinality`] 是**别的模块**的冻结类型，不能为它加"未知"以外的兜底；
    /// 所以不认识的串只能在这里响亮失败（`Unknown` 是引擎自己序列化出来的一个合法取值，别混用）。
    BadCardinality,
}

impl From<IrError> for SelError {
    fn from(e: IrError) -> Self {
        SelError::Ir(e)
    }
}

/// 编译好的选择器：arena 表 + 它引用的字符串池，**一起拥有**。
///
/// 为什么要把池一起拿着：`IdRef` 只是 `(offset, len)`，池没了引用就悬空。
/// 这里做成自包含的，调用方不需要知道池的存在。
#[derive(Debug, Clone, Copy)]
pub struct CompiledSelector {
    table: SelectorTable,
    pool: [u8; CompiledSelector::POOL_CAP],
    pool_len: u16,
}

impl CompiledSelector {
    /// 串池容量。状态 id 最长 40 字节；v1 的选择器最多两层复合，256 足够。
    ///
    /// 实测（core 镜像）：一次编译的池里最多 **1** 个状态 id（16 B），256 B 是 16 倍余量；
    /// 理论上限是 6 个 40 B 的过滤器串起来，第 7 个就会 `PoolFull`。
    pub const POOL_CAP: usize = 256;

    /// 把一个 `sel.*` 节点（及其子树）编译进一张新的 arena。
    ///
    /// **根固定放 0 号槽**（[`crate::targets::resolve`] 与 [`crate::targets::cardinality`] 都从 0 起），
    /// 子选择器按前序分配后续槽位，父节点用下标引用它们。
    ///
    /// **全有或全无**：出错时返回 `Err`，调用方拿不到半张表（也不可能有悬空的 `IdRef`，
    /// 因为池和表是同一个值的两半，一起构造、一起交出）。
    pub fn compile(node: NodeRef<'_>) -> Result<Self, SelError> {
        let mut builder = Builder::new();
        builder.emit(ROOT_SLOT, node)?;
        Ok(Self {
            table: builder.table,
            pool: builder.pool,
            pool_len: builder.pool_len,
        })
    }

    #[must_use]
    pub fn table(&self) -> &SelectorTable {
        &self.table
    }

    #[must_use]
    pub fn pool(&self) -> &[u8] {
        &self.pool[..self.pool_len as usize]
    }

    /// 解析成目标列表，返回个数。
    ///
    /// 直接委托 [`targets::resolve`]：本模块不重复实现选择逻辑。
    pub fn resolve(
        &self,
        ctx: &SelectionContext<'_>,
        out: &mut [CombatantId],
    ) -> Result<usize, SelectorError> {
        let mut sink = TargetSink { ids: out, len: 0 };
        targets::resolve(&self.table, ctx, self.pool(), &mut sink)
    }

    /// IR 里**声明的**基数（`Cardinality` 字段）。
    ///
    /// `Ok(None)` = 这个选择器在 IR 里没带该字段（`sel.iterationTarget` 之类有些带了、有些没带）。
    /// 用来和 [`targets::cardinality`] 交叉校验 —— 见模块头。
    ///
    /// 实测（core 镜像）：24 条 `sel.*` 里只有 4 条带这个字段（`source`/`eventTarget`/
    /// `iterationTarget`/`lowestHealthEnemy`），值全是 `"ZeroOrOne"`；其余 20 条没带 ——
    /// 而参考实现里"没带"就是吃接口默认值 `ZeroOrMore`（`CombatantTargetSelectors.cs:59`），
    /// 于是"字段缺席 ⟺ 静态基数 = `ZeroOrMore`"本身也是一条可断言的一致性。
    pub fn declared_cardinality(node: NodeRef<'_>) -> Result<Option<Cardinality>, SelError> {
        let Some(text) = node.str_field("Cardinality")? else {
            return Ok(None);
        };
        cardinality_from_wire(text).map(Some).ok_or(SelError::BadCardinality)
    }
}

/// `TargetSelectorCardinality` 的线名 → [`Cardinality`]（`CombatantTargetSelectors.cs:15-31`）。
///
/// 不认识的串给 `None`（由 [`CompiledSelector::declared_cardinality`] 转成
/// [`SelError::BadCardinality`]）—— **不许猜一个默认值**：`ZeroOrMore` 会让预检放行标量读，
/// `ExactlyOne` 会让它拒绝对空集合的读，两种都是会改变行为的谎。
#[must_use]
fn cardinality_from_wire(name: &str) -> Option<Cardinality> {
    match name {
        "ExactlyOne" => Some(Cardinality::ExactlyOne),
        "ZeroOrOne" => Some(Cardinality::ZeroOrOne),
        "OneOrMore" => Some(Cardinality::OneOrMore),
        "ZeroOrMore" => Some(Cardinality::ZeroOrMore),
        "Unknown" => Some(Cardinality::Unknown),
        _ => None,
    }
}

/// 根节点的槽位。`targets` 的两个入口都从这里起。
const ROOT_SLOT: u16 = 0;

/// `compile` 的构造器：一张表 + 一段串池 + "下一个空槽"游标。
///
/// 为什么需要它：`SelError` 里没有"部分成功"这种结果，递归到一半失败必须能让调用方
/// **什么都拿不到**。所以表与池先在这里长齐，成功才交给 [`CompiledSelector`]。
struct Builder {
    table: SelectorTable,
    pool: [u8; CompiledSelector::POOL_CAP],
    pool_len: u16,
    next_slot: u16,
}

impl Builder {
    /// 0 号槽留给根，所以下一个可用槽是 1。
    const fn new() -> Self {
        Self {
            table: SelectorTable::empty(),
            pool: [0u8; CompiledSelector::POOL_CAP],
            pool_len: 0,
            next_slot: 1,
        }
    }

    /// 发一个空槽。用完了 ⇒ [`SelError::TableFull`]（**不覆盖已有槽、不回绕**）。
    fn alloc(&mut self) -> Result<u16, SelError> {
        let slot = self.next_slot;
        if usize::from(slot) >= SelectorTable::MAX_NODES {
            return Err(SelError::TableFull);
        }
        self.next_slot = slot + 1;
        Ok(slot)
    }

    /// 把一段状态 id 拷进串池，得到它在这张表里的引用。
    ///
    /// **不去重**：真实镜像里一次编译的池里最多 1 个 id，省这点查找毫无收益；而去重会让
    /// [`SelError::PoolFull`] 的触发条件变成"这些 id 是否互不相同" —— 那是别人读这段代码时最
    /// 容易算错的一处，可这道闸门的全部价值就是"算错了会响亮失败"。容量按"每个过滤器各占一份"
    /// 算，所以 256 B 就是 6 个 40 B 的 id，一眼能验。
    fn intern(&mut self, text: &str) -> Result<IdRef, SelError> {
        let offset = usize::from(self.pool_len);
        let end = offset.checked_add(text.len()).ok_or(SelError::PoolFull)?;
        if end > CompiledSelector::POOL_CAP {
            return Err(SelError::PoolFull);
        }
        let len = u16::try_from(text.len()).map_err(|_| SelError::PoolFull)?;
        let dest = self.pool.get_mut(offset..end).ok_or(SelError::PoolFull)?;
        dest.copy_from_slice(text.as_bytes());
        self.pool_len = u16::try_from(end).map_err(|_| SelError::PoolFull)?;
        Ok(IdRef { offset: u16::try_from(offset).map_err(|_| SelError::PoolFull)?, len })
    }

    /// 写一个槽。槽号由 [`Self::alloc`] 发出，**永远 < `MAX_NODES`**，所以这里的
    /// `SelectorError` 只是 `targets` 的签名带来的（映射成 `TableFull` 而不是 `unwrap`，
    /// 是因为本 crate 禁止 panic 路径；这条分支不可达）。
    fn set(&mut self, slot: u16, node: SelectorNode) -> Result<(), SelError> {
        self.table.set(slot, node).map_err(|_| SelError::TableFull)
    }

    /// 把 `node` 编译进 `slot`，需要时给子选择器发新槽。
    fn emit(&mut self, slot: u16, node: NodeRef<'_>) -> Result<(), SelError> {
        // `kind` 是 opcode 的名字串（`ir.rs` 实测事实 1），不是字段。
        let kind = node.kind_str()?;

        // 10 种"叶子直通"的选择器：`Source`/`EventTarget`/`IterationTarget`/`AllAllies`/
        // `AllEnemies`/`LowestHealthEnemy`/…。它们的 `Cardinality`/`RequiredContextCapabilities`
        // 字段是**元数据**，不进 arena（arena 里没有放它的地方，也不需要：
        // `targets::cardinality` 按参考实现静态写死）。
        if let Some(leaf) = leaf_for(kind) {
            return self.set(slot, SelectorNode::Leaf(leaf));
        }

        match kind {
            // `AllCombatantsTargetSelector(bool AliveOnly = true)`（`:172-189`）：
            // 参数**默认 true**，所以字段缺席按 true 读。按 false 读会把倒下的单位塞进"全体"，
            // 那是另一种选择器（`MayIncludeDownedTargets` 只跟着 `AliveOnly` 反着走，`:174`，
            // 是派生元数据，不进 arena）。
            "sel.allCombatants" => {
                let alive_only = node.bool_field("AliveOnly")?.unwrap_or(true);
                self.set(slot, SelectorNode::Leaf(LeafSelector::AllCombatants { alive_only }))
            }
            // `CombatantsWithStatusTargetSelector(Inner, StatusDefinitionId, IncludeFallen: false)`
            // （`:303-327`）：`IncludeFallen` 默认 false ⇒ `targets::StatusFilter::With`
            // （含存活过滤，`WithIncludingFallen` 才是 true 那一半）。
            "sel.withStatus" => {
                let inner = node.node_field("Inner")?.ok_or(SelError::MissingInner)?;
                let status = node.str_field("StatusDefinitionId")?.ok_or(SelError::MissingStatusId)?;
                let child = self.alloc()?;
                let status_id = self.intern(status)?;
                // `Inner` 指到表达式上 ⇒ `InnerNotASelector`（不是 `NotASelector`：错的不是
                // 这个节点，是它的孩子）。**不许跳过一个读不懂的孩子继续编译** —— 那会安静地
                // 变成一个范围更大的过滤器。
                self.emit(child, inner).map_err(|e| match e {
                    SelError::NotASelector => SelError::InnerNotASelector,
                    other => other,
                })?;
                self.set(
                    slot,
                    SelectorNode::StatusFilter {
                        op: StatusFilter::With,
                        inner: child,
                        status_id,
                    },
                )
            }
            // 这两个是**固定**的复合选择器，没有 `Inner` 字段：
            // `AllAlliesOfSourceWithStatusCombatantTargetSelector`（`:231-244`）=
            //     `WithStatus(AllAlliesOfSource, id)`；
            // `AllEnemiesOfSourceWithStatusCombatantTargetSelector`（`:246-259`）=
            //     `WithStatus(AllEnemiesOfSource, id)`。
            // `AllEnemiesOfSource` 自己已经筛存活（`:166`），`With` 又筛一次 —— 幂等，不影响结果。
            "sel.alliesWithStatus" | "sel.enemiesWithStatus" => {
                let status = node.str_field("StatusDefinitionId")?.ok_or(SelError::MissingStatusId)?;
                let leaf = if kind == "sel.alliesWithStatus" {
                    LeafSelector::AllAlliesOfSource
                } else {
                    LeafSelector::AllEnemiesOfSource { alive_only: true }
                };
                let child = self.alloc()?;
                let status_id = self.intern(status)?;
                self.set(child, SelectorNode::Leaf(leaf))?;
                self.set(
                    slot,
                    SelectorNode::StatusFilter {
                        op: StatusFilter::With,
                        inner: child,
                        status_id,
                    },
                )
            }
            // §313：`AllAlliesOfSourceWithDefinitionCombatantTargetSelector` ——
            // "按**定义**挑一只友军"（`Centurion` 的 `Protect` 给 `Mystic`）。
            // 与 `alliesWithStatus` 同一形状：固定叶子 + 一层过滤，只是过滤键是**定义 id**。
            "sel.alliesWithDefinition" => {
                let definition = node
                    .str_field("CombatantDefinitionId")?
                    .ok_or(SelError::MissingStatusId)?;
                let child = self.alloc()?;
                self.set(child, SelectorNode::Leaf(LeafSelector::AllAlliesOfSource))?;
                let definition_id = self.intern(definition)?;
                self.set(
                    slot,
                    SelectorNode::DefinitionFilter {
                        inner: child,
                        definition_id,
                    },
                )
            }
            // 剩下两种下场，**没有第三种**（尤其没有"当成空集"）：
            // * 还是 `sel.*` ⇒ 卡选择器/玩家选择（`deckCards`/`matching`/`random`/`choose`），
            //   或者是我们没见过的选择器 —— 都报"这一类我们不做"，由调用方决定怎么收场；
            // * 根本不是 `sel.*` ⇒ 它不是选择器。
            //
            // `sel.matching` 走的就是第一条：它**带** `Inner` 和 `Predicate` 两个字段，
            // 只编译 `Inner` 会把谓词丢掉、把"牌库里攻击力大于 3 的那些"变成"牌库全体"。
            other => {
                if other.starts_with("sel.") {
                    Err(SelError::UnsupportedKind)
                } else {
                    Err(SelError::NotASelector)
                }
            }
        }
    }
}

/// IR 的 `sel.*` 判别串 → `targets` 的叶子选择器。
///
/// `None` = 这个 `sel.*` 不是战斗员选择器（卡选择器/玩家选择），调用方应报 [`SelError::UnsupportedKind`]。
///
/// ⚠️ `sel.allEnemies` 在镜像里**没有字段**，而 `targets::LeafSelector::AllEnemiesOfSource`
/// 有个 `alive_only` 开关 —— 参考实现这个选择器**恒为存活过滤**（`CombatantTargetSelectors.cs:166`），
/// 所以这里给 `alive_only: true`。`sel.allCombatants` 相反，它**带** `AliveOnly` 字段，照它读。
#[must_use]
pub fn leaf_for(kind: &str) -> Option<LeafSelector> {
    match kind {
        "sel.source" => Some(LeafSelector::Source),
        // §178：`SourceIncludingDownedCombatantTargetSelector`（`CombatJson.cs:319`）。变体
        // 早就在 `targets.rs`，**判别串却没人注册** —— 于是内容只要用参考的写法就会拿到
        // `SelError::UnsupportedKind`，而"分裂"（`Downed` 触发器上的自我移除）恰恰必须用它：
        // 倒下的战斗员用 `sel.source` 解析出来是**空集**（参考 `:130` 的 `IsAlive` 检查）。
        "sel.sourceIncludingDowned" => Some(LeafSelector::SourceIncludingDowned),
        "sel.eventTarget" => Some(LeafSelector::EventTarget),
        "sel.iterationTarget" => Some(LeafSelector::IterationTarget),
        "sel.allAllies" => Some(LeafSelector::AllAlliesOfSource),
        "sel.allEnemies" => Some(LeafSelector::AllEnemiesOfSource { alive_only: true }),
        "sel.allDamagedAllies" => Some(LeafSelector::AllDamagedAlliesOfSource),
        "sel.lowestHealthEnemy" => Some(LeafSelector::LowestHealthEnemyOfSource),
        "sel.highestHealthEnemy" => Some(LeafSelector::HighestHealthEnemyOfSource),
        "sel.lowestHealthAlly" => Some(LeafSelector::LowestHealthAllyOfSource),
        "sel.highestHealthAlly" => Some(LeafSelector::HighestHealthAllyOfSource),
        // 这 4 种是卡选择器 / 玩家选择，不是战斗员选择器。
        "sel.deckCards" | "sel.matching" | "sel.random" | "sel.choose" => None,
        // `allCombatants` 需要读 `AliveOnly` 字段，所以走 `compile` 的专门分支，不在这个表里。
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const ALL_LEAF_KINDS: [&str; 11] = [
        "sel.source",
        "sel.sourceIncludingDowned",
        "sel.eventTarget",
        "sel.iterationTarget",
        "sel.allAllies",
        "sel.allEnemies",
        "sel.allCombatants",
        "sel.lowestHealthEnemy",
        "sel.alliesWithStatus",
        "sel.enemiesWithStatus",
        "sel.withStatus",
    ];

    #[test]
    fn the_four_card_selectors_are_deliberately_out_of_scope() {
        // 这四个出现在镜像里，但它们是**卡选择器/玩家选择**，不是战斗员选择器。
        // 把它们报成"空集"是错的（一张"选一张牌升级"的牌会安静地什么都不做），
        // 所以 leaf_for 必须给 None，由 compile 报 UnsupportedKind。
        for k in ["sel.deckCards", "sel.matching", "sel.random", "sel.choose"] {
            assert_eq!(leaf_for(k), None, "{k} 不是战斗员选择器");
        }
    }

    #[test]
    fn combatant_selectors_map_to_leaves_and_unknown_strings_do_not() {
        assert_eq!(leaf_for("sel.source"), Some(LeafSelector::Source));
        assert_eq!(leaf_for("sel.eventTarget"), Some(LeafSelector::EventTarget));
        assert_eq!(leaf_for("sel.iterationTarget"), Some(LeafSelector::IterationTarget));
        // `sel.allEnemies` 恒为存活过滤（参考 `:166`），没有开关。
        assert_eq!(
            leaf_for("sel.allEnemies"),
            Some(LeafSelector::AllEnemiesOfSource { alive_only: true })
        );
        // 不认识的串必须给 None，不许猜一个默认值。
        assert_eq!(leaf_for("sel.doesNotExist"), None);
        assert_eq!(leaf_for(""), None);
        // 大小写敏感。
        assert_eq!(leaf_for("Sel.Source"), None);
    }

    #[test]
    fn all_combatant_selector_kinds_are_accounted_for_by_one_of_the_two_lists() {
        // 这条测试的价值：`ALL_LEAF_KINDS` 里的每一种，要么走 leaf_for、要么是 allCombatants
        // 那条需要读字段的专门分支 —— **不能有第三种下场**（静默变成空集）。
        for k in ALL_LEAF_KINDS {
            let via_leaf = leaf_for(k).is_some();
            let is_all_combatants = k == "sel.allCombatants";
            let is_status_filter = matches!(k, "sel.alliesWithStatus" | "sel.enemiesWithStatus" | "sel.withStatus");
            assert!(
                via_leaf || is_all_combatants || is_status_filter,
                "{k} 既不在 leaf_for 里，也不是 allCombatants/状态过滤 —— 它会静默变成空集"
            );
        }
    }

    // =============================================================================================
    // W4b：`compile` / `declared_cardinality`
    //
    // 这些测试**读真实镜像**（`tools/contentc/out/content.core.rdcf`）。镜像不在仓库里（它是构建
    // 产物），所以找不到就 panic 并打印路径与生成命令 —— 产物缺席时安静通过的测试等于没有测试。
    //
    // 期望值全部是实测出来的（`reader.py` 遍历 24 条 `sel.*` term 得到），没有一条是"看着像"写的；
    // 每条的实测值写在断言旁边。
    // =============================================================================================

    use crate::content::{Content, S_TRM, S_TRW};
    use crate::ir::Ir;
    use crate::state::{
        CombatId, CombatState, Combatant, CombatantDefinitionId, CombatantLifecycleState,
        StatusDefinitionId, StatusInstance, StatusInstanceId, StatusPolarity, TeamId,
        MAX_COMBATANTS,
    };

    /// 编译失败时的错误。
    ///
    /// `CompiledSelector` 只有 `Debug/Clone/Copy`（它装着 `SelectorTable`，那个类型没有
    /// `PartialEq`），所以 `assert_eq!` 只能看 `Result` 的 `Err` 那一半。
    fn compile_error(node: NodeRef<'_>) -> Option<SelError> {
        CompiledSelector::compile(node).err()
    }

    const CORE_IMAGE_REL: &str = "../../tools/contentc/out/content.core.rdcf";

    fn core_image_path() -> std::path::PathBuf {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(CORE_IMAGE_REL)
    }

    fn core_image() -> Vec<u8> {
        let path = core_image_path();
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

    fn root_of<'a>(ir: &Ir<'a>, index: u32) -> NodeRef<'a> {
        ir.card_program_root(index)
            .unwrap_or_else(|e| panic!("CARD[{index}] 取不到程序根节点：{e:?}"))
    }

    /// 遍历所有 term，挑出判别串等于 `kind` 的那些 id（升序，因为扫描就是升序）。
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

    fn only_term_of_kind<'a>(content: &'a Content<'a>, kind: &str) -> NodeRef<'a> {
        let ids = terms_of_kind(content, kind);
        assert_eq!(ids.len(), 1, "{kind} 实测只有 1 条 term，实际 {}", ids.len());
        NodeRef::new(content, ids[0])
    }

    /// 一个 term 某个字段**首槽**在镜像 blob 里的字节偏移（只给补丁测试用）。
    ///
    /// term 记录地址 = `TRM.offset + TRW[tid] * 4`，前 2 字节是 opcode，之后每槽 2 字节；
    /// 字段首槽 = 字段表顺序累加的槽数之和（与 `ir::NodeRef::field_spec` 同一套映射）。
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

    fn read16(blob: &[u8], at: usize) -> u16 {
        let bytes = blob.get(at..at + 2).unwrap_or_else(|| panic!("read16 越界：{at}"));
        u16::from_le_bytes([bytes[0], bytes[1]])
    }

    fn patch16(blob: &mut [u8], at: usize, value: u16) {
        let slot = blob.get_mut(at..at + 2).unwrap_or_else(|| panic!("patch16 越界：{at}"));
        slot.copy_from_slice(&value.to_le_bytes());
    }

    /// 镜像里最长的几个串（`(串号, 字节长)`，按长度降序）。
    /// 串号 = 迭代下标 + 1（`Strings` 从串号 1 开始），串号 0 是空串。
    fn longest_strings(content: &Content<'_>, min_len: usize) -> Vec<(u16, usize)> {
        let mut all: Vec<(u16, usize)> = Vec::new();
        for (i, s) in content.strings().enumerate() {
            let Some(s) = s else { continue };
            if s.len() >= min_len {
                all.push((u16::try_from(i + 1).expect("串号不超 u16"), s.len()));
            }
        }
        all.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
        all
    }

    /// 根节点（0 号槽）是什么。
    fn root_node(sel: &CompiledSelector) -> SelectorNode {
        sel.table().node(0).expect("0 号槽必须存在（根固定放这里）")
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

    fn status(definition: &str, stacks: i32) -> StatusInstance {
        StatusInstance::new(
            StatusInstanceId::new("status_000001").unwrap(),
            StatusDefinitionId::new(definition).unwrap(),
            StatusPolarity::Buff,
        )
        .with_stacks(stacks)
    }

    /// 存储序 `[enemy_a, hero, hero2, enemy_b(倒下), enemy_c]`，队伍**交错**：
    ///
    /// | 下标 | id | 队伍 | 血量 | 生命周期 | 状态 |
    /// |---|---|---|---|---|---|
    /// | 0 | enemy_a | enemy | 30/30 | 活着 | `witness_the_seal` + `both_directions_mandatory` |
    /// | 1 | hero（来源） | player | 70/70 | 活着 | — |
    /// | 2 | hero2（事件目标） | player | 40/50 | 活着 | `witness_the_seal` |
    /// | 3 | enemy_b | enemy | 0/10 | **已倒下** | `witness_the_seal` |
    /// | 4 | enemy_c | enemy | 5/20 | 活着 | — |
    ///
    /// 两个状态 id 是**镜像里的真 status**（STATUS 表 `:13` 与 `:14`），不是编的。
    fn battle_arena() -> CombatState {
        let mut state = CombatState::new(CombatId::new("c1").unwrap(), 42);

        let mut enemy_a = unit("enemy_a", "enemy", 30, 30);
        enemy_a.push_status(status("witness_the_seal", 1)).unwrap();
        enemy_a.push_status(status("both_directions_mandatory", 2)).unwrap();
        state.add_combatant(enemy_a).unwrap();

        state.add_combatant(unit("hero", "player", 70, 70)).unwrap();

        let mut hero2 = unit("hero2", "player", 40, 50);
        hero2.push_status(status("witness_the_seal", 3)).unwrap();
        state.add_combatant(hero2).unwrap();

        let mut fallen =
            unit("enemy_b", "enemy", 0, 10).with_lifecycle_state(CombatantLifecycleState::Downed);
        fallen.push_status(status("witness_the_seal", 9)).unwrap();
        state.add_combatant(fallen).unwrap();

        state.add_combatant(unit("enemy_c", "enemy", 5, 20)).unwrap();

        state
    }

    fn resolve_names(
        sel: &CompiledSelector,
        state: &CombatState,
        source: Option<CombatantId>,
        event_target: Option<CombatantId>,
    ) -> Vec<String> {
        let ctx = SelectionContext {
            state,
            source,
            event_target,
            iteration_target: None,
        };
        let mut buf = [CombatantId::EMPTY; MAX_COMBATANTS];
        let n = sel
            .resolve(&ctx, &mut buf)
            .unwrap_or_else(|e| panic!("resolve 不该报结构错：{e:?}"));
        buf.get(..n)
            .expect("n 不超 sink 容量")
            .iter()
            .map(|id| id.as_str().to_string())
            .collect()
    }

    // =============================================================================================
    // 1. 形状：三张卡的选择器编译成什么
    // =============================================================================================

    #[test]
    fn the_three_named_cards_compile_to_the_expected_shapes() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let ir = Ir::new(&content);

        // ── paper_cut(CARD 0) = dealDamage{TargetSelector: sel.eventTarget{Cardinality: ZeroOrOne,
        //    RequiredContextCapabilities: EventTarget}} ──────────────────────────────────────────
        let paper = root_of(&ir, 0);
        assert_eq!(paper.kind_str(), Ok("node.dealDamage"));
        let sel = paper.node_field("TargetSelector").unwrap().expect("TargetSelector");
        let compiled = CompiledSelector::compile(sel).expect("sel.eventTarget 必须能编译");
        assert_eq!(root_node(&compiled), SelectorNode::Leaf(LeafSelector::EventTarget));
        assert_eq!(compiled.table().len(), 1, "叶子只占 0 号槽");
        assert!(compiled.pool().is_empty(), "元数据字段不进串池");
        // `Cardinality` 是**元数据**：读得出来，但不进 arena。
        assert_eq!(
            CompiledSelector::declared_cardinality(sel),
            Ok(Some(Cardinality::ZeroOrOne))
        );

        // ── cower_behind_a_desk(CARD 2) = gainBlock{TargetSelector: sel.source} ────────────────
        let cower = root_of(&ir, 2);
        assert_eq!(cower.kind_str(), Ok("node.gainBlock"));
        let sel = cower.node_field("TargetSelector").unwrap().expect("TargetSelector");
        let compiled = CompiledSelector::compile(sel).expect("sel.source 必须能编译");
        assert_eq!(root_node(&compiled), SelectorNode::Leaf(LeafSelector::Source));
        assert_eq!(compiled.table().len(), 1);
        assert_eq!(
            CompiledSelector::declared_cardinality(sel),
            Ok(Some(Cardinality::ZeroOrOne))
        );

        // ── strong_binder(CARD 4) = sequence[gainBlock, applyStatus]；
        //    第二个孩子（applyStatus）的 TargetSelector 也是 sel.eventTarget ──────────────────────
        let binder = root_of(&ir, 4);
        assert_eq!(binder.kind_str(), Ok("node.sequence"));
        let mut kids = [0u16; 8];
        let n = binder.list_field("Children", &mut kids).expect("Children");
        assert_eq!(n, 2, "strong_binder = gainBlock + applyStatus");
        let apply_status = NodeRef::new(&content, kids[1]);
        assert_eq!(apply_status.kind_str(), Ok("node.applyStatus"));
        assert_eq!(
            apply_status.str_field("StatusDefinitionId"),
            Ok(Some("doubt")),
            "这条是 ir.rs 的实测值，写在这里是为了证明 term {} 确实是那条 applyStatus",
            kids[1]
        );
        let sel = apply_status.node_field("TargetSelector").unwrap().expect("TargetSelector");
        let compiled = CompiledSelector::compile(sel).expect("sel.eventTarget 必须能编译");
        assert_eq!(root_node(&compiled), SelectorNode::Leaf(LeafSelector::EventTarget));
        assert_eq!(
            CompiledSelector::declared_cardinality(sel),
            Ok(Some(Cardinality::ZeroOrOne))
        );
    }

    // =============================================================================================
    // 2. ★ 交叉校验：IR 声明的基数 vs `targets::cardinality` 的静态表
    // =============================================================================================

    #[test]
    fn every_compilable_selector_agrees_with_the_static_cardinality_table() {
        // 两边**独立**得出：一边是引擎序列化的元数据，一边是照参考实现逐变体写死的表。
        // 任何一个不一致都说明有一边写错了 —— 这是本任务最有价值的断言。
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");

        let mut compiled_kinds: Vec<&str> = Vec::new();
        let mut unsupported_kinds: Vec<&str> = Vec::new();
        let mut unsupported_terms = 0usize;
        let mut total_terms = 0usize;
        let (mut declared, mut undeclared) = (0usize, 0usize);

        for tid in 0..content.term_count() {
            let Ok(tid) = u16::try_from(tid) else { continue };
            let node = NodeRef::new(&content, tid);
            let Ok(kind) = node.kind_str() else { continue };
            if !kind.starts_with("sel.") {
                continue;
            }
            total_terms += 1;

            let compiled = match CompiledSelector::compile(node) {
                Ok(compiled) => compiled,
                Err(e) => {
                    assert_eq!(
                        e,
                        SelError::UnsupportedKind,
                        "term {tid} ({kind}) 编译失败但不是 UnsupportedKind：{e:?}"
                    );
                    unsupported_terms += 1;
                    if !unsupported_kinds.contains(&kind) {
                        unsupported_kinds.push(kind);
                    }
                    continue;
                }
            };
            if !compiled_kinds.contains(&kind) {
                compiled_kinds.push(kind);
            }

            let declared_cardinality = CompiledSelector::declared_cardinality(node)
                .unwrap_or_else(|e| panic!("term {tid} ({kind}) 读 Cardinality 失败：{e:?}"));
            let static_cardinality = targets::cardinality(compiled.table());
            match declared_cardinality {
                Some(d) => {
                    declared += 1;
                    assert_eq!(
                        d, static_cardinality,
                        "term {tid} ({kind})：IR 声明 {d:?}，静态表 {static_cardinality:?} —— 有一边错了"
                    );
                }
                None => {
                    undeclared += 1;
                    // IR 没声明 ⟺ 参考实现在吃接口默认值 `ZeroOrMore`
                    // （`CombatantTargetSelectors.cs:59`）。这条把"缺席"本身也钉住：
                    // 若哪天某个至多一个的选择器忘了写 Cardinality，这里会红。
                    assert_eq!(
                        static_cardinality,
                        Cardinality::ZeroOrMore,
                        "term {tid} ({kind}) 没声明 Cardinality，静态表却给了 {static_cardinality:?}"
                    );
                }
            }

            // 结构自检：引用不悬空，池里那段字节就是 IR 里那个串。
            for index in 0..u16::try_from(SelectorTable::MAX_NODES).expect("32 不超 u16") {
                match compiled.table().node(index) {
                    Ok(SelectorNode::Leaf(_)) => {}
                    Ok(SelectorNode::StatusFilter { inner, status_id, op }) => {
                        assert_eq!(op, StatusFilter::With, "W4b 只产生 IncludeFallen:false 那一种");
                        assert!(
                            compiled.table().node(inner).is_ok(),
                            "term {tid} ({kind})：inner 下标 {inner} 悬空"
                        );
                        let start = usize::from(status_id.offset);
                        let end = start + usize::from(status_id.len);
                        let bytes = compiled.pool().get(start..end).expect("IdRef 必须在池内");
                        let text = node
                            .str_field("StatusDefinitionId")
                            .expect("读字段")
                            .expect("状态选择器必须有 StatusDefinitionId");
                        assert_eq!(
                            bytes,
                            text.as_bytes(),
                            "term {tid} ({kind})：池里的字节与 IR 的串不一致"
                        );
                    }
                    Ok(other) => panic!("term {tid} ({kind})：W4b 不该产生 {other:?}"),
                    Err(_) => {}
                }
            }
        }

        // 实测计数（`reader.py` 遍历 2143 条 term 得到）：24 条 `sel.*`、14 种 kind。
        assert_eq!(total_terms, 24, "镜像里 24 条 sel.* term");
        assert_eq!(compiled_kinds.len(), 10, "10 种战斗员选择器全部编译成功");
        assert_eq!(unsupported_terms, 7, "4 种卡选择器共 7 条 term");
        assert_eq!((declared, undeclared), (4, 13), "带 Cardinality 的 4 条 / 不带的 13 条");

        compiled_kinds.sort_unstable();
        assert_eq!(
            compiled_kinds,
            vec![
                "sel.allAllies",
                "sel.allCombatants",
                "sel.allEnemies",
                "sel.alliesWithStatus",
                "sel.enemiesWithStatus",
                "sel.eventTarget",
                "sel.iterationTarget",
                "sel.lowestHealthEnemy",
                "sel.source",
                "sel.withStatus",
            ],
            "编译成功的 10 种，逐字对照任务给的表"
        );
        unsupported_kinds.sort_unstable();
        assert_eq!(
            unsupported_kinds,
            vec!["sel.choose", "sel.deckCards", "sel.matching", "sel.random"]
        );
    }

    // =============================================================================================
    // 3. 端到端 resolve：编译出来的那条表在真场上选出什么
    // =============================================================================================

    #[test]
    fn the_compiled_selectors_resolve_end_to_end_on_a_real_battle() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let state = battle_arena();
        let hero = cid("hero");
        let hero2 = cid("hero2");

        // `sel.source` → 来源自己。
        let node = only_term_of_kind(&content, "sel.source");
        let sel = CompiledSelector::compile(node).expect("sel.source");
        assert_eq!(resolve_names(&sel, &state, Some(hero), Some(hero2)), vec!["hero"]);
        // 没有来源 ⇒ 空集（不是错）。
        assert!(resolve_names(&sel, &state, None, Some(hero2)).is_empty());

        // `sel.eventTarget` → 事件目标。
        let node = only_term_of_kind(&content, "sel.eventTarget");
        let sel = CompiledSelector::compile(node).expect("sel.eventTarget");
        assert_eq!(resolve_names(&sel, &state, Some(hero), Some(hero2)), vec!["hero2"]);
        // 目标已倒下 ⇒ 空集（参考 `:130`：`target!.IsAlive`）。
        assert!(resolve_names(&sel, &state, Some(hero), Some(cid("enemy_b"))).is_empty());

        // `sel.allEnemies` → 敌方**存活**者，存储序（`enemy_b` 倒下被排除）。
        let node = only_term_of_kind(&content, "sel.allEnemies");
        let sel = CompiledSelector::compile(node).expect("sel.allEnemies");
        assert_eq!(
            resolve_names(&sel, &state, Some(hero), None),
            vec!["enemy_a", "enemy_c"],
            "存活过滤 + 存储序"
        );

        // `sel.lowestHealthEnemy` → 敌方存活里血量最低的一个（enemy_c 5 < enemy_a 30）。
        let node = only_term_of_kind(&content, "sel.lowestHealthEnemy");
        let sel = CompiledSelector::compile(node).expect("sel.lowestHealthEnemy");
        assert_eq!(resolve_names(&sel, &state, Some(hero), None), vec!["enemy_c"]);
        assert_eq!(
            CompiledSelector::declared_cardinality(node),
            Ok(Some(Cardinality::ZeroOrOne)),
            "IR 声明"
        );
        assert_eq!(targets::cardinality(sel.table()), Cardinality::ZeroOrOne, "静态表");

        // `sel.alliesWithStatus`（真实 id = `witness_the_seal`）→ 友方里带它的存活者。
        let ids = terms_of_kind(&content, "sel.alliesWithStatus");
        assert_eq!(ids.len(), 3, "实测 3 条：term 961 / 1027 / 1168");
        let node = NodeRef::new(&content, ids[0]);
        assert_eq!(
            node.str_field("StatusDefinitionId"),
            Ok(Some("witness_the_seal")),
            "实测 term 961 的 id"
        );
        let sel = CompiledSelector::compile(node).expect("sel.alliesWithStatus");
        assert_eq!(
            resolve_names(&sel, &state, Some(hero), None),
            vec!["hero2"],
            "hero 自己不带这个状态"
        );

        // `sel.enemiesWithStatus`（真实 id = `both_directions_mandatory`）→ 敌方里带它、且存活的。
        let ids = terms_of_kind(&content, "sel.enemiesWithStatus");
        assert_eq!(ids.len(), 2, "实测 2 条：term 981 / 1129");
        let node = NodeRef::new(&content, ids[0]);
        assert_eq!(node.str_field("StatusDefinitionId"), Ok(Some("both_directions_mandatory")));
        let sel = CompiledSelector::compile(node).expect("sel.enemiesWithStatus");
        assert_eq!(resolve_names(&sel, &state, Some(hero), None), vec!["enemy_a"]);

        // `sel.withStatus`（真实 id = `witness_the_seal`，Inner = `sel.allCombatants{AliveOnly:false}`）
        // → 场上带它的**存活**者：enemy_b 带着但它倒下了，被 `With` 的存活过滤丢掉。
        let with_status = terms_of_kind(&content, "sel.withStatus");
        assert_eq!(with_status.len(), 5, "实测 5 条（term 379/384/389/417/1109）");
        for tid in &with_status {
            let inner = NodeRef::new(&content, *tid).node_field("Inner").unwrap().expect("Inner");
            assert_eq!(inner.kind_str(), Ok("sel.allCombatants"), "term {tid} 的 Inner");
            assert_eq!(inner.bool_field("AliveOnly"), Ok(Some(false)), "term {tid} 的 Inner");
        }
        let node = NodeRef::new(&content, with_status[0]);
        assert_eq!(node.str_field("StatusDefinitionId"), Ok(Some("witness_the_seal")));
        let sel = CompiledSelector::compile(node).expect("sel.withStatus");
        assert_eq!(
            resolve_names(&sel, &state, Some(hero), None),
            vec!["enemy_a", "hero2"],
            "enemy_b 带着状态但已倒下 ⇒ 被丢掉；hero/enemy_c 不带"
        );

        // `sel.allCombatants{AliveOnly:false}` → 全 5 个（含倒下的）。
        let node = only_term_of_kind(&content, "sel.allCombatants");
        assert_eq!(node.bool_field("AliveOnly"), Ok(Some(false)), "实测 term 378");
        // `MayIncludeDownedTargets` 在参考实现里是**派生**的（`=> !AliveOnly`，`:174`），
        // 镜像里的这一对正好自洽 —— 所以"只读 AliveOnly、丢掉另一个"不是信息损失。
        assert_eq!(
            node.bool_field("MayIncludeDownedTargets"),
            Ok(Some(true)),
            "实测 (AliveOnly:false, MayIncludeDownedTargets:true) = 参考 `:174` 的 !AliveOnly"
        );
        let everything = CompiledSelector::compile(node).expect("sel.allCombatants");
        let all = resolve_names(&everything, &state, Some(hero), None);
        assert_eq!(all, vec!["enemy_a", "hero", "hero2", "enemy_b", "enemy_c"]);

        // 同一个选择器、只把 `AliveOnly` 加成 true ⇒ 结果**必须不同**。
        let mut patched = blob.clone();
        let alive_at = {
            let content = Content::parse(&patched).expect("解析");
            field_slot_offset(&content, 378, "AliveOnly")
        };
        assert_eq!(read16(&patched, alive_at), 1, "补丁前 AliveOnly = BOOL_FALSE");
        patch16(&mut patched, alive_at, 2); // BOOL_TRUE
        let content = Content::parse(&patched).expect("改一个布尔后仍须能解析");
        let node = NodeRef::new(&content, 378);
        assert_eq!(node.bool_field("AliveOnly"), Ok(Some(true)));
        let alive_only = CompiledSelector::compile(node).expect("sel.allCombatants{true}");
        assert_eq!(root_node(&alive_only), SelectorNode::Leaf(LeafSelector::AllCombatants {
            alive_only: true
        }));
        let living = resolve_names(&alive_only, &state, Some(hero), None);
        assert_eq!(living, vec!["enemy_a", "hero", "hero2", "enemy_c"]);
        assert_ne!(
            all, living,
            "`AliveOnly` 读错的话这两个会给同一串 —— 这条断言就是它的对偶面"
        );
    }

    // =============================================================================================
    // 4. 不支持的必须报错，绝不静默变成空集
    // =============================================================================================

    #[test]
    fn the_card_selectors_report_unsupported_kind_and_never_an_empty_set() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let state = battle_arena();

        let mut seen = 0usize;
        for kind in ["sel.deckCards", "sel.matching", "sel.random", "sel.choose"] {
            for tid in terms_of_kind(&content, kind) {
                let node = NodeRef::new(&content, tid);
                assert_eq!(
                    compile_error(node),
                    Some(SelError::UnsupportedKind),
                    "term {tid} ({kind}) 必须报 UnsupportedKind"
                );
                seen += 1;
            }
        }
        assert_eq!(seen, 7, "实测 1+1+1+4 = 7 条卡选择器 term");

        // `SelError` 不是一处空集：不同的错必须彼此可分，而且**能编译的选择器不会误报** ——
        // 否则"报错"和"没事"就分不出来了。
        assert_ne!(SelError::UnsupportedKind, SelError::NotASelector);
        assert_ne!(SelError::UnsupportedKind, SelError::TableFull);
        assert_ne!(SelError::PoolFull, SelError::TableFull);
        assert_ne!(SelError::MissingInner, SelError::MissingStatusId);
        assert_ne!(SelError::BadCardinality, SelError::UnsupportedKind);
        let source = only_term_of_kind(&content, "sel.source");
        let compiled = CompiledSelector::compile(source).expect("sel.source 必须成功");
        assert_eq!(
            resolve_names(&compiled, &state, Some(cid("hero")), None),
            vec!["hero"],
            "能编译的选择器在注意上真的能选出东西（不是空集）"
        );
    }

    #[test]
    fn sel_matching_is_refused_whole_instead_of_just_compiling_its_inner() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");

        let matching = only_term_of_kind(&content, "sel.matching");
        // 它**带**一个 `Inner`（`sel.deckCards`）和一个 `Predicate`（`compare`）：
        // 只编译 Inner 会把谓词丢掉，把"牌库里满足条件的那些"变成"牌库全体"。
        assert_eq!(
            matching.node_field("Inner").unwrap().expect("Inner").kind_str(),
            Ok("sel.deckCards")
        );
        let predicate = matching.node_field("Predicate").unwrap().expect("Predicate");
        assert_eq!(
            predicate.kind_str(),
            Ok("compare"),
            "谓词是 compare —— 丢掉它 = 结果集变大"
        );
        assert_eq!(
            compile_error(matching),
            Some(SelError::UnsupportedKind),
            "整条拒绝，不许只编译 Inner 就放行"
        );

        // `sel.choose{Count, Inner, Purpose}`：`Count` 是"玩家要挑几张"，内核根本没有这条路
        // （没有玩家输入），编译它只能靠猜。
        for tid in terms_of_kind(&content, "sel.choose") {
            let choose = NodeRef::new(&content, tid);
            assert!(choose.int_field("Count").unwrap().is_some(), "choose 带 Count");
            assert!(choose.str_field("Purpose").unwrap().is_some(), "choose 带 Purpose");
            assert_eq!(compile_error(choose), Some(SelError::UnsupportedKind));
        }

        // `sel.random{Count, Inner}`：`Count` 相同，但"随机挑"要 RNG，这一层不做；
        // 就算做了也不该在这里做（编译期没有 (seed, step)）。
        let random = only_term_of_kind(&content, "sel.random");
        assert!(random.int_field("Count").unwrap().is_some());
        assert_eq!(compile_error(random), Some(SelError::UnsupportedKind));
    }

    // =============================================================================================
    // 5. 非选择器 / 越界 term
    // =============================================================================================

    #[test]
    fn a_plain_expression_is_not_a_selector() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let ir = Ir::new(&content);

        // paper_cut 的 `Amount` 是 `const{Value: 6}` —— 它是表达式，不是选择器。
        let paper = root_of(&ir, 0);
        let amount = paper.node_field("Amount").unwrap().expect("Amount");
        assert_eq!(amount.kind_str(), Ok("const"));
        assert_eq!(
            compile_error(amount),
            Some(SelError::NotASelector),
            "非选择器要报 NotASelector，不是 panic、也不是 UnsupportedKind"
        );
        // `const` 没有 `Cardinality` 字段 ⇒ `Ok(None)`（不是错）。
        assert_eq!(CompiledSelector::declared_cardinality(amount), Ok(None));

        // run 层的节点也一样（`node.encounter` 是 IR 对象但显然不是选择器）。
        let encounters = terms_of_kind(&content, "node.encounter");
        assert_eq!(encounters.len(), 23);
        assert_eq!(
            compile_error(NodeRef::new(&content, encounters[0])),
            Some(SelError::NotASelector)
        );
    }

    #[test]
    fn an_out_of_range_term_id_reports_instead_of_panicking() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let bogus = NodeRef::new(&content, u16::MAX);
        assert_eq!(
            compile_error(bogus),
            Some(SelError::Ir(IrError::Term(u16::MAX)))
        );
        assert_eq!(
            CompiledSelector::declared_cardinality(bogus),
            Err(SelError::Ir(IrError::Term(u16::MAX)))
        );
        // 刚好越过末尾一个：同一个错。
        let past_end = u16::try_from(content.term_count()).expect("term_count 不超 u16");
        assert_eq!(
            compile_error(NodeRef::new(&content, past_end)),
            Some(SelError::Ir(IrError::Term(past_end)))
        );
    }

    // =============================================================================================
    // 6. 池 / 表溢出：响亮失败、全有或全无
    // =============================================================================================

    #[test]
    fn a_pool_that_runs_out_fails_loudly_and_leaves_nothing_behind() {
        // 状态 id 上限 40 B，所以**单条**过滤器永远填不满 256 B 的池；真实镜像里一次编译最多
        // 带 1 个 id。要按到这条闸门，只能造一条**嵌套**过滤器链 —— 用真镜像的 5 条
        // `sel.withStatus` 串起来，并把 id 指到镜像里最长的几个串上（最长的 83 B，实测串号 641）。
        //
        // 这样造出来的结构在真实内容里不存在（真实数据最深两层），但它用的每个字节都是真的：
        // 真 opcode、真 term、真字符串池，只改了槽值。标得很清楚。
        let blob = core_image();
        let mut patched = blob.clone();

        let (chain, strings) = {
            let content = Content::parse(&patched).expect("解析");
            let chain = terms_of_kind(&content, "sel.withStatus");
            assert_eq!(chain.len(), 5, "实测 5 条 sel.withStatus");
            let strings = longest_strings(&content, 52);
            (chain, strings)
        };
        assert!(strings.len() >= 4, "实测镜像里 ≥52 B 的串有 13 个");
        assert_eq!(strings[0], (641, 83), "实测最长的串：串号 641、83 B");

        let three: usize = strings[..3].iter().map(|(_, len)| *len).sum();
        let four = three + strings[3].1;
        assert!(
            three <= CompiledSelector::POOL_CAP && four > CompiledSelector::POOL_CAP,
            "这条测试要卡在边界上：前 3 个 id {three} B 装得下，前 4 个 {four} B 装不下"
        );

        let offsets: Vec<(usize, usize)> = {
            let content = Content::parse(&patched).expect("解析");
            (0..4)
                .map(|i| {
                    (
                        field_slot_offset(&content, chain[i], "Inner"),
                        field_slot_offset(&content, chain[i], "StatusDefinitionId"),
                    )
                })
                .collect()
        };
        for (i, (inner_at, status_at)) in offsets.iter().enumerate() {
            patch16(&mut patched, *inner_at, chain[i + 1]);
            patch16(&mut patched, *status_at, strings[i].0);
        }

        let content = Content::parse(&patched).expect("改槽值后仍须能解析");
        let node = NodeRef::new(&content, chain[0]);
        assert_eq!(
            node.str_field("StatusDefinitionId"),
            Ok(Some(string_of(&content, strings[0].0)))
        );
        assert_eq!(
            compile_error(node),
            Some(SelError::PoolFull),
            "第 4 个 id 装不下 ⇒ PoolFull（**不是** TableFull，也不是 Ok）"
        );
        // 重复调用给同一个结果：编译没有隐藏状态、也不"部分写入"（成功才交出 CompiledSelector，
        // 出错时调用方什么都拿不到 —— 这是类型层面保证的"全有或全无"）。
        assert_eq!(compile_error(node), Some(SelError::PoolFull));

        // 同一次运行里，未经补丁的那条 `sel.withStatus` 照样能编译、池里是它自己的 id：
        // 上面那次失败没有污染任何共享状态。
        {
            let pristine = Content::parse(&blob).expect("解析");
            let node = NodeRef::new(&pristine, chain[0]);
            let compiled =
                CompiledSelector::compile(node).expect("原样的 sel.withStatus 必须能编译");
            assert_eq!(compiled.pool(), b"witness_the_seal");
            assert_eq!(compiled.table().len(), 2, "过滤器 + 一条 allCombatants 叶子");
            assert_eq!(
                root_node(&compiled),
                SelectorNode::StatusFilter {
                    op: StatusFilter::With,
                    inner: 1,
                    status_id: IdRef { offset: 0, len: 16 },
                },
                "父节点在 0、孩子在 1，状态 id 从池首开始"
            );
        }
    }

    /// 串号 → 串（`longest_strings` 记的是号，断言时要拿回内容）。
    fn string_of<'a>(content: &Content<'a>, id: u16) -> &'a str {
        content.string(id).expect("串号来自本镜像的扫描，必须有效")
    }

    #[test]
    fn a_self_referential_inner_exhausts_the_arena_instead_of_the_stack() {
        // `compile` 没有环检测（IR 是 DAG，真实内容最深两层），但 arena 是**定量**的：
        // 每一层都要一个新槽，32 个槽用完就 `TableFull`。这条测试钉住"自环不会把栈打爆"。
        //
        // 为了让失败点单独落在 arena 上，把状态 id 补丁成**空串**（串号 0）：否则 16 B × 32 层
        // 会先在池上失败，测到的就不是 TableFull 了。
        let blob = core_image();
        let mut patched = blob.clone();
        let tid = {
            let content = Content::parse(&patched).expect("解析");
            *terms_of_kind(&content, "sel.withStatus").first().expect("sel.withStatus")
        };
        let (inner_at, status_at) = {
            let content = Content::parse(&patched).expect("解析");
            (
                field_slot_offset(&content, tid, "Inner"),
                field_slot_offset(&content, tid, "StatusDefinitionId"),
            )
        };
        patch16(&mut patched, inner_at, tid); // 自指
        patch16(&mut patched, status_at, 0); // 串号 0 = 空串
        let content = Content::parse(&patched).expect("解析");
        let node = NodeRef::new(&content, tid);
        assert_eq!(
            node.node_field("Inner").unwrap().expect("Inner").id(),
            tid,
            "补丁生效：Inner 指向自己"
        );
        assert_eq!(node.str_field("StatusDefinitionId"), Ok(Some("")));
        assert_eq!(
            compile_error(node),
            Some(SelError::TableFull),
            "{} 个槽用完后必须报 TableFull，而不是递归到栈溢出",
            SelectorTable::MAX_NODES
        );
    }

    // =============================================================================================
    // 7. 缺字段 / 坏孩子 / 坏基数：都不许被"猜一个默认值"
    // =============================================================================================

    #[test]
    fn a_missing_inner_or_status_id_is_reported_and_never_defaulted() {
        let blob = core_image();
        let tid = {
            let content = Content::parse(&blob).expect("解析");
            *terms_of_kind(&content, "sel.withStatus").first().expect("sel.withStatus")
        };

        // (a) `Inner` 是缺席哨兵（ABSENT16）⇒ MissingInner。绝不能退化成"空集"。
        let mut probe = blob.clone();
        let inner_at = {
            let content = Content::parse(&probe).expect("解析");
            field_slot_offset(&content, tid, "Inner")
        };
        patch16(&mut probe, inner_at, crate::content::ABSENT16);
        {
            let content = Content::parse(&probe).expect("解析");
            let node = NodeRef::new(&content, tid);
            assert!(node.node_field("Inner").unwrap().is_none());
            assert_eq!(compile_error(node), Some(SelError::MissingInner));
        }

        // (b) `StatusDefinitionId` 缺席 ⇒ MissingStatusId。**不许**当成空串 id ——
        //     空串永远匹配不到状态，于是"带某状态的那些"会安静地变成空集。
        let mut probe = blob.clone();
        let status_at = {
            let content = Content::parse(&probe).expect("解析");
            field_slot_offset(&content, tid, "StatusDefinitionId")
        };
        patch16(&mut probe, status_at, crate::content::ABSENT16);
        {
            let content = Content::parse(&probe).expect("解析");
            let node = NodeRef::new(&content, tid);
            assert!(node.str_field("StatusDefinitionId").unwrap().is_none());
            assert_eq!(compile_error(node), Some(SelError::MissingStatusId));
        }
    }

    #[test]
    fn an_inner_that_points_at_an_expression_is_not_a_selector() {
        let blob = core_image();
        let mut patched = blob.clone();
        let (tid, compare) = {
            let content = Content::parse(&patched).expect("解析");
            let tid = *terms_of_kind(&content, "sel.withStatus").first().expect("sel.withStatus");
            let compare = *terms_of_kind(&content, "compare").first().expect("compare");
            (tid, compare)
        };
        let inner_at = {
            let content = Content::parse(&patched).expect("解析");
            field_slot_offset(&content, tid, "Inner")
        };
        patch16(&mut patched, inner_at, compare);
        let content = Content::parse(&patched).expect("解析");
        let node = NodeRef::new(&content, tid);
        assert_eq!(
            node.node_field("Inner").unwrap().expect("Inner").kind_str(),
            Ok("compare")
        );
        assert_eq!(
            compile_error(node),
            Some(SelError::InnerNotASelector),
            "孩子读不懂要报 InnerNotASelector（不是 NotASelector：错的不是这个节点）；\
             跳过孩子继续编译会变成一个范围更大的过滤器"
        );
    }

    #[test]
    fn cardinality_wire_names_round_trip_and_nothing_else_does() {
        // 五个线名来自 `TargetSelectorCardinality`（`CombatantTargetSelectors.cs:15-31`）。
        assert_eq!(cardinality_from_wire("ExactlyOne"), Some(Cardinality::ExactlyOne));
        assert_eq!(cardinality_from_wire("ZeroOrOne"), Some(Cardinality::ZeroOrOne));
        assert_eq!(cardinality_from_wire("OneOrMore"), Some(Cardinality::OneOrMore));
        assert_eq!(cardinality_from_wire("ZeroOrMore"), Some(Cardinality::ZeroOrMore));
        assert_eq!(cardinality_from_wire("Unknown"), Some(Cardinality::Unknown));
        // `Unknown` 是引擎自己序列化出来的合法值，别和"不认识"混用。
        assert_ne!(cardinality_from_wire("Unknown"), cardinality_from_wire("Nonsense"));
        // 不认识/大小写不对 ⇒ None（由 declared_cardinality 转成 BadCardinality），不许猜。
        assert_eq!(cardinality_from_wire("zeroOrOne"), None);
        assert_eq!(cardinality_from_wire(""), None);
        assert_eq!(cardinality_from_wire("ZeroOrOne "), None);
        assert_eq!(cardinality_from_wire("Exactly One"), None);
    }

    #[test]
    fn an_unknown_cardinality_string_in_the_image_is_rejected_not_guessed() {
        let blob = core_image();
        let mut patched = blob.clone();
        // 把 `sel.source` 的 `Cardinality` 槽指到 `sel.withStatus` 的 `StatusDefinitionId` 用的
        // 那个串（`witness_the_seal`）—— 它是镜像里真实存在的 F_STR 串，只是不是基数名。
        let (source_tid, status_slot) = {
            let content = Content::parse(&patched).expect("解析");
            let source_tid = *terms_of_kind(&content, "sel.source").first().expect("sel.source");
            let with_status = *terms_of_kind(&content, "sel.withStatus").first().expect("withStatus");
            (source_tid, field_slot_offset(&content, with_status, "StatusDefinitionId"))
        };
        let foreign = read16(&patched, status_slot);
        {
            let content = Content::parse(&patched).expect("解析");
            let at = field_slot_offset(&content, source_tid, "Cardinality");
            patch16(&mut patched, at, foreign);
        }
        let content = Content::parse(&patched).expect("解析");
        let node = NodeRef::new(&content, source_tid);
        let text = node.str_field("Cardinality").unwrap().expect("Cardinality 仍是 F_STR");
        assert_eq!(text, "witness_the_seal");
        assert_eq!(cardinality_from_wire(text), None);
        assert_eq!(
            CompiledSelector::declared_cardinality(node),
            Err(SelError::BadCardinality),
            "不认识的基数串必须报错 —— 猜一个 ZeroOrMore 会让标量读的预检放行错误的程序"
        );
        // 但 `Cardinality` 只是元数据：arena 照编不误（编译不看它）。
        let compiled = CompiledSelector::compile(node).expect("sel.source 仍然能编译");
        assert_eq!(root_node(&compiled), SelectorNode::Leaf(LeafSelector::Source));
    }
}
