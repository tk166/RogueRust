//! 修饰器管线（`DeclarativePassiveModifierEngine`）—— 叶子模块 W3b。
//!
//! 参考实现：`RogueDeck.Core/Combat/Effects/PassiveModifiers.cs:116-218`（`Apply`），
//! 规格：`docs/spec/modifier-pipeline.md`。状态**表**在 `crate::status_catalog`（已交付），
//! 本模块只负责**把表按序作用到一个数值上**。
//!
//! ## 冻结契约（照抄，不许"优化"）
//!
//! 1. `amount <= 0` **原样返回**，不进入管线（参考实现 `:137-138`，"legacy bespoke modifiers
//!    在非正数上全部 no-op"）。
//! 2. **门控**（`spec` 不满足任一条件即整条丢弃，不去 claim 它的"每次一次"）：
//!    pipeline 相符、数量种类相符、`applies_to_status` 相符、元素相符、
//!    来源卡标签相符、`onlyCardTagged` 隐含要求 spec 必须带来源卡标签。
//! 3. **排序**：`(priority, status_id 的 Ordinal 字节序, spec_index)`，三者依次比较
//!    （`:179-185`）。**不是**数字序、不是注册序。
//! 4. **四种运算**（`:206-213`），全部整数、全部按 C# 语义：
//!    * `AddPerStack`  → `current + magnitude * stacks`
//!    * `AddFlat`      → `current + magnitude`
//!    * `ScalePercent` → `current * magnitude / 100`（**向零截断**的整数除法）
//!    * `ClampMax`     → `min(current, max(0, magnitude))`
//! 5. **claim 发生在所有其它门控之后**（`:190-201`），这样"本来就不生效的 spec 不会白白烧掉
//!    它那一次机会"。
//! 6. 返回 `max(0, current)`（`:216`）。
//!
//! ## "加法先于乘法"为什么是本模块的规格
//!
//! 规格书 §4.2 点名的那条：base 7、力量 3、虚弱 + 易伤 —— 正确序得 **10**，错序得 **12**；
//! 而 `(5+2)*150/100` 正确得 **10**、错序得 **9**。**这两组反例必须写成断言**，
//! 否则"排序"只是一句注释而不是可执行的规格。

use crate::state::CombatState;
use core::cmp::Ordering;

/// 管线（`PassiveModifierPipeline`）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Pipeline {
    /// 造成的伤害（从**来源**读 spec）。
    DamageDealt,
    /// 受到的伤害（从**承受者**读 spec）。
    DamageReceived,
    /// 获得格挡（单阶段）。
    Block,
    /// 卡的代价（单阶段）。
    Cost,
}

/// 运算（`PassiveModifierOperation`）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Operation {
    /// 每层加一次幅值。
    AddPerStack,
    /// 只加一次幅值。
    AddFlat,
    /// 按百分比缩放，整数除法向零截断。
    ScalePercent,
    /// §198：`current * (100 + magnitude * stacks) / 100` —— **每层线性加百分比**。
    ///
    /// `ScalePercent` 是"乘一个固定百分比、**不读层数**"（虚弱/易伤那种只有时长轴的），而 `Slow`
    /// 是"每打一张牌 +10%"，需要 `1 + 0.1 × stacks` 这种**与层数线性**的因子。用 `AddPerStack`
    /// 会变成"每层 +10 点平伤害"，用 `ScalePercent` 会忽略层数 —— 两种都是看起来能跑、数值却错一档。
    ScalePercentPerStack,
    /// 上限钳制到 `max(0, magnitude)`。
    ClampMax,
}

/// 一条修饰器规格（`PassiveModifierSpec` 的战斗路径子集）。
///
/// 参考实现里还有 `MagnitudeExpression`（活状态求值）与 `RestrictElement` 的元素 id、
/// `RestrictSourceCardTag` 的标签 id —— 它们需要内容层的**表达式求值器**与 id 池，
/// 不属于本叶子。这里的 `magnitude` 只承载**常量**幅值；带表达式的 spec 由调用方预求值后传入。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ModifierSpec {
    pub pipeline: Pipeline,
    pub priority: i32,
    pub operation: Operation,
    pub magnitude: i32,
    /// `RestrictDamageKind`：有值且与本次伤害种类不符 ⇒ 丢弃（只看伤害管线）。
    pub restrict_damage_kind: Option<u8>,
    /// `AppliesToStatusId` 命中本 spec 且与本次施加的状态不符 ⇒ 丢弃。
    pub restrict_status_applies: bool,
    /// `RestrictElement` 有值且与本次元素不符 ⇒ 丢弃。
    pub restrict_element: bool,
    /// `RestrictSourceCardTag` 有值 ⇒ 来源卡必须带该标签才生效。
    pub restrict_source_card_tag: bool,
    /// 每个**动作**（一次出牌/一次敌人行动）最多贡献一次。
    pub once_per_action: bool,
    /// 每个**回合**最多贡献一次。
    pub once_per_turn: bool,
}

/// 一次 `apply` 的输入里与"谁在读表"有关的部分。
#[derive(Clone, Copy, Debug)]
pub struct FilterContext {
    pub pipeline: Pipeline,
    /// 本次伤害的种类；只看伤害管线。
    pub damage_kind: Option<u8>,
    /// 本次施加的状态是否**命中**了 spec 的 `AppliesToStatusId`。
    /// 调用方预先判定好（内核里状态用 `&str` id，不带生命周期进不来）。
    pub status_applies: bool,
    /// 本次元素是否与 spec 的 `RestrictElement` 相符。
    pub element_matches: bool,
    /// 本次来源卡是否带 spec 要求的标签。
    pub source_card_has_tag: bool,
    /// `onlyCardTagged`：只让**带来源卡标签**的 spec 生效。
    pub only_card_tagged: bool,
}

/// 一条"某状态第几个 spec、几层"的应用项，排序前先摊平。
#[derive(Clone, Copy, Debug)]
pub struct Candidate {
    pub priority: i32,
    /// 状态的字节序比较键（调用方给的 `&str` 的字节，存不下就用 intern 后的下标）。
    pub status_key: StatusKey,
    pub spec_index: u16,
    pub stacks: i32,
    pub operation: Operation,
    pub magnitude: i32,
    pub once_per_action: bool,
    pub once_per_turn: bool,
}

/// 状态排序键。内核里状态 id 是字符串；`Ordinal` 就是**字节序**。
/// 这里不存 `&str`，等价的字节在 `status_id_pool` 里由调用方给出。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct StatusKey {
    pub offset: u16,
    pub len: u16,
}

/// "每次动作/每回合最多一次"的账本。参考实现把这两笔账分别记在
/// `CombatState.TryClaimOnceThisAction`（按 `pipeline|statusId|specIndex|combatant` 的字符串键）
/// 与 `CardPlayTurnStats.TryClaimOnceThisTurn`（按 `pipeline|statusId|specIndex`）上。
///
/// 内核不用字符串键：调用方给每个候选一个**稳定的 u32 claim 键**（由内容层 intern 得到）。
/// 账本只负责"这个键见过没有"，不负责键怎么算。
#[derive(Debug)]
pub struct ClaimLedger {
    action_claims: [u32; ClaimLedger::CAPACITY],
    action_len: usize,
    turn_claims: [u32; ClaimLedger::CAPACITY],
    turn_len: usize,
}

// 手写而不是 derive：`[u32; 64]: Default` 不成立（标准库只为长度 <= 32 的数组实现了 Default）。
impl Default for ClaimLedger {
    fn default() -> Self {
        Self::new()
    }
}

/// 应用结果。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Applied {
    /// 管线走完之后的数值（恒 `>= 0`）。
    pub amount: i32,
    /// 真正生效（贡献过）的候选条数。用来在测试里断言"门控确实拦住了"。
    pub applied_count: u16,
}

/// 把候选表按契约作用到 `amount` 上。
///
/// `candidates` 由调用方填好（本模块**不**去遍历 `CombatState`：那需要内容层的状态定义表，
/// 属于 `status_catalog` / 内容镜像的职责）。这样本模块是**纯函数**，可以在没有引擎的情况下
/// 用规格书里的数字直接钉死。
///
/// # 门控的分工（契约 2 与 `apply` 的边界）
///
/// `Candidate` 里**没有** pipeline / 伤害种类 / 元素 / 来源卡标签这些字段，所以那五个门控的
/// 权威是 [`spec_passes_filters`]：调用方按契约**只把过了门的 spec 摊成候选**塞进 `candidates`。
/// `apply` 里逐条的门控只剩 claim（每动作/每回合一次），而且它发生在其它门控之后（契约 5）——
/// 把两件事分开，才能让"本来就不生效的 spec 不白烧掉它那一次机会"这条被单测直接钉住。
///
/// # 账本键：`(owner_key, claim_keys[i])` 到底怎么组合
///
/// 参考实现的两把键：
/// * 动作级（`PassiveModifiers.cs:194`）：`"{pipeline}|{statusId}|{specIndex}|{combatant.Id}"`；
/// * 回合级（`:200`）：`"{pipeline}|{statusId}|{specIndex}"`，但账本本身是**按战斗员**取的
///   （`combat.GetCardPlayTurnStats(combatant.Id)`，`:199`）—— 等效键里同样含单位。
///
/// 内核只有一本 u32 账，所以**两个作用域**用同一个混合函数：
///
/// ```text
/// ledger_key(i) = mix32(owner_key, claim_keys[i])
/// ```
///
/// `claim_keys[i]` 由调用方算好，承载 `(pipeline, statusId, specIndex)` 那一段（内容层 intern 成
/// u32）；`owner_key` 承载 `combatant.Id`。**回合级也混 `owner_key`**：不混的话 A 战斗员的
/// "每回合一次"会拦住 B 的同一条 spec，而参考实现给每个战斗员一本 turn stats 正是为了不互相拦。
/// 混合同样保证**不同 owner 不共享账本**（单测逐条钉住）。
///
/// 混合是 64 bit → 32 bit 的压窄，碰撞在数学上躲不掉（u32 账装不下两个 u32 的全空间）；
/// 用 splitmix32 风格的终结器把碰撞摊匀，内容层把 claim 键控制在小的 intern 区间里即可。
///
/// `claim_keys` 比 `candidates` 短时，缺失的键按 `0` 处理 —— 契约要求调用方给出**等长**的键表，
/// 这里只是不把违约升级成 panic（确定性降级，单测 `missing_or_extra_claim_keys_degrade_without_panicking`）。
///
/// # 排序：不就地置换、也没有候选数上限
///
/// `claim_keys` 是与 `candidates` **按下标平行**的只读切片：任何就地置换都会让候选与它自己的键
/// 错位（键搬不动）。所以本实现**不改动 `candidates`**，改用"按秩选择"：每一轮只在"键严格大于
/// 上一轮"的候选里取最小者，只用一个 `usize` 记住上一轮的位置 —— O(1) 额外空间、O(n²) 次比较
/// （n 是一次管线里的候选条数，标准包是 3）、**没有容量上限**，因此也不存在"超上限如何降级"
/// 的语义要交代（对比：定长插入排序必须挑一个上限并定义溢出行为）。
///
/// 比较键是 `(priority, status_id 的字节序, spec_index, 原始下标)`：前三项就是 `:179-185`，
/// 末项只用来给**完全重复**的候选定一个确定的次序（C# 的 `List.Sort` 不稳定，重复键的相对次序
/// 本来就没有契约；内核选择"按下标"，可复现）。
///
/// # 越界的 `StatusKey`
///
/// `StatusKey{offset,len}` 指向 `status_id_pool` 的 `[offset, offset+len)`。**任何越界**
/// （区间超出池子、`offset+len` 溢出）**一律当作空串**：空串在字节序里是最小值，所以越界键排在
/// 最前，结果确定、绝不 panic。这不是"猜一个 id"，而是"这个键不可用"的确定性降级（单测钉住）。
///
/// # `applied_count` 的口径
///
/// **走到操作那一步就计数**：过了门控、抢到了（若有）两个 claim。所以
/// * 被调用方按门控挡在 `candidates` 之外的 spec：不计（它根本不在这里）；
/// * claim 抢不到的：不计（`:193-201` 的 `continue`）；
/// * `AddPerStack` 碰上 `stacks == 0`：**计**。数值不变（`:208` 是 `current + magnitude * 0`），
///   但 C# 照样执行这一条、并**照样烧掉**它那一次 claim —— 计不计是"是否算贡献过"的定义问题，
///   这里取"管线真的作用过它"，与"数值有没有变"解耦（单测把这两件事分开钉住）。
///
/// # 无 panic
///
/// 切片一律 `get()`；算术一律 `wrapping_*`（C# 的 `int` 默认 unchecked ⇒ 溢出回绕，逐位一致），
/// 唯一的除法是常量 `100`（不会除以 0，也撞不上 `i32::MIN / -1`）；`applied_count` 用
/// `saturating_add`。
pub fn apply(
    amount: i32,
    candidates: &mut [Candidate],
    status_id_pool: &[u8],
    ledger: &mut ClaimLedger,
    owner_key: u32,
    claim_keys: &[u32],
) -> Applied {
    // 契约 1（`:137-138`）：非正数**原样**返回，管线根本没跑 —— 账本也因此一笔没动。
    if amount <= 0 {
        return Applied {
            amount,
            applied_count: 0,
        };
    }

    let mut current = amount;
    let mut applied_count: u16 = 0;
    let mut previous: Option<usize> = None;

    // 每轮取"下一个最小者"。上界就是候选条数，取不到就收尾（防御式：任何越界视角都只是提前结束）。
    for _ in 0..candidates.len() {
        let index = match next_rank(candidates, status_id_pool, previous) {
            Some(index) => index,
            None => break,
        };
        previous = Some(index);

        let candidate = match candidates.get(index) {
            Some(candidate) => *candidate,
            None => break,
        };

        // 契约 5（`:190-201`）：claim 发生在所有其它门控之后（调用方已经把门控做完了）。
        // 两个 claim 是**依次**做的，照抄 C#：动作级先占，回合级抢不到就 `continue`，
        // 此时动作级那笔账**已经记下了** —— 这是参考实现的可观察副作用，别"顺手"做成原子的。
        let claim_key = ledger_key(owner_key, claim_keys.get(index).copied().unwrap_or(0));
        if candidate.once_per_action && !ledger.claim_action(claim_key) {
            continue;
        }
        if candidate.once_per_turn && !ledger.claim_turn(claim_key) {
            continue;
        }

        // 契约 4（`:206-213`）。全部 `wrapping_*`：与 C# 的 unchecked `int` 溢出语义逐位一致，
        // 且天然无 panic。Rust 的整数 `/` 与 C# 一样**向零截断**（负数也一样，单测
        // `intermediate_values_may_go_negative_and_only_the_end_is_clamped` 钉住）。
        current = match candidate.operation {
            Operation::AddPerStack => {
                current.wrapping_add(candidate.magnitude.wrapping_mul(candidate.stacks))
            }
            Operation::AddFlat => current.wrapping_add(candidate.magnitude),
            // ScalePercent **不读 stacks**（`:210`），所以只有时长轴的状态（虚弱/易伤，层数恒 0）
            // 也能正常参与乘法。
            Operation::ScalePercent => current.wrapping_mul(candidate.magnitude) / 100,
            // `current * (100 + magnitude * stacks) / 100`，用 i64 中间量避免 `magnitude * stacks` 溢出。
            Operation::ScalePercentPerStack => {
                let factor = i64::from(candidate.magnitude)
                    .saturating_mul(i64::from(candidate.stacks))
                    .saturating_add(100);
                let scaled = i64::from(current).saturating_mul(factor) / 100;
                scaled.clamp(i64::from(i32::MIN), i64::from(i32::MAX)) as i32
            }
            // `Math.Min(current, Math.Max(0, magnitude))`（`:211`）：幅值为负时上限就是 0。
            Operation::ClampMax => {
                let cap = if candidate.magnitude > 0 {
                    candidate.magnitude
                } else {
                    0
                };
                if current < cap {
                    current
                } else {
                    cap
                }
            }
        };
        applied_count = applied_count.saturating_add(1);
    }

    // 契约 6（`:216`）：整条管线只在**末尾**夹一次 `max(0, ·)`（中间步可以为负 —— 例如
    // `AddFlat` 的幅值为负；参考实现也是这样，`DamageEffects.cs:312` 的那次夹取在折叠器外层）。
    Applied {
        amount: current.max(0),
        applied_count,
    }
}

/// 便利：把 `FilterContext` + `ModifierSpec` 的门控判定单独暴露出来，
/// 这样"哪一条被拦掉了、为什么"可以被单测直接钉住（不经过整个管线）。
///
/// 逐条对应参考实现的五行门（`PassiveModifiers.cs:152-171`），顺序无关（全是合取）：
/// `Pipeline` → 数量种类 → 施加目标 → 元素 → 来源卡标签 → `onlyCardTagged`。
pub fn spec_passes_filters(spec: &ModifierSpec, f: &FilterContext) -> bool {
    // `:152`
    if spec.pipeline != f.pipeline {
        return false;
    }

    // `:155`（**只照抄这一行的字面语义**：两边都有值且不等才拦）。
    //
    // C# 里**没有**"仅伤害管线"这个额外条件 —— 那是调用方的约定：非伤害管线（格挡/卡费）
    // 传 `damageKind: null`（标准包给格挡折叠器传的就是 null，`PassiveModifiers.cs:267`），
    // 这一门于是整段跳过。`FilterContext::damage_kind` 的"只看伤害管线"说的也是这件事：
    // 它是**调用方**该守的约定，不是这里能判的（这里只拿到一个 `Option`，判不出它是否可信）。
    // 若在这里补一个 pipeline 判断，反而会让"调用方按约定传 null"之外的合法组合被多拦一次。
    let damage_kind_mismatch = matches!(
        (f.damage_kind, spec.restrict_damage_kind),
        (Some(kind), Some(restrict)) if restrict != kind
    );
    if damage_kind_mismatch {
        return false;
    }

    // `:158`：spec 绑定了 `AppliesToStatusId`，而本次施加的不是它 ⇒ 丢弃。
    // 门开着（`status_applies == true`）的两种情形都由调用方折进那个布尔：spec 没绑状态，
    // 或本次施加的状态正好命中。
    if spec.restrict_status_applies && !f.status_applies {
        return false;
    }

    // `:162`：spec 限制了元素，而本次元素不是它（含"本次没有元素"）⇒ 丢弃。
    if spec.restrict_element && !f.element_matches {
        return false;
    }

    // `:168`：spec 要求来源卡带某标签，而来源卡没带（含"没有来源卡"—— 敌人行动/状态跳伤）⇒ 丢弃。
    if spec.restrict_source_card_tag && !f.source_card_has_tag {
        return false;
    }

    // `:170`：`onlyCardTagged` 隐含要求 spec **自己**必须带来源卡标签。放在最后是为了让
    // "被这条拦掉"与"被上面那条拦掉"在注释里一眼可分（语义上它们都是合取项）。
    if f.only_card_tagged && !spec.restrict_source_card_tag {
        return false;
    }

    true
}

// ---------------------------------------------------------------------------------------------
// 私有辅助：排序键的比较、按秩选择、状态字节、账本键混合
// ---------------------------------------------------------------------------------------------

/// 排序键的三级比较，末尾再用原始下标把**完全重复**的候选定序（见 `apply` 的文档）。
///
/// 前三级就是 `PassiveModifiers.cs:179-185`：`priority` 升序 → `statusId` 的
/// `string.CompareOrdinal` → `specIndex` 升序。对 ASCII id（内核对 id 的要求，D9）
/// 序数比较就是**字节序**比较，所以这里直接比 `status_id_pool` 里的字节。
fn compare(a: &Candidate, a_index: usize, b: &Candidate, b_index: usize, pool: &[u8]) -> Ordering {
    a.priority
        .cmp(&b.priority)
        .then_with(|| status_bytes(pool, a.status_key).cmp(status_bytes(pool, b.status_key)))
        .then_with(|| a.spec_index.cmp(&b.spec_index))
        .then_with(|| a_index.cmp(&b_index))
}

/// 取"按序排在 `previous` 之后的最小候选"的下标；没有下一个（或 `previous` 越界）时返回 `None`。
///
/// 这是"按秩选择"的内核：调用方每轮拿到的下标序列就是排好序的次序，而**不需要**任何缓冲区、
/// 也不需要改动 `candidates`（它的平行切片 `claim_keys` 搬不动，见 `apply` 的文档）。
/// 时间复杂度 O(n)（对 n 个候选扫两遍：一遍筛"大于下界"，一遍取最小），整体 O(n²)；
/// n 是一次管线里的候选条数，小到不值得引入上限或缓冲。
fn next_rank(candidates: &[Candidate], pool: &[u8], previous: Option<usize>) -> Option<usize> {
    // 上一轮处理过的那个（本轮的下界）。它一定来自同一个切片；取不到就当作"没有下一个"，
    // 让上层循环安全收尾，而不是 panic。
    let floor = match previous {
        Some(index) => match candidates.get(index) {
            Some(candidate) => Some((index, candidate)),
            None => return None,
        },
        None => None,
    };

    let mut best: Option<(usize, &Candidate)> = None;
    for (index, candidate) in candidates.iter().enumerate() {
        if let Some((floor_index, floor_candidate)) = floor {
            if compare(candidate, index, floor_candidate, floor_index, pool) != Ordering::Greater {
                continue;
            }
        }
        let better = match best {
            Some((best_index, best_candidate)) => {
                compare(candidate, index, best_candidate, best_index, pool) == Ordering::Less
            }
            None => true,
        };
        if better {
            best = Some((index, candidate));
        }
    }
    best.map(|(index, _)| index)
}

/// `StatusKey{offset,len}` 指向 `status_id_pool` 的区间 `[offset, offset + len)`。
///
/// **越界一律视为空串**（见 `apply` 的文档）：空串在字节序里是最小值 ⇒ 越界键排在最前，
/// 且绝不 panic。用 `get()` + `checked_add` 而不是切片下标。
fn status_bytes(pool: &[u8], key: StatusKey) -> &[u8] {
    let start = key.offset as usize;
    let end = match start.checked_add(key.len as usize) {
        Some(end) => end,
        None => return &[],
    };
    match pool.get(start..end) {
        Some(bytes) => bytes,
        None => &[],
    }
}

/// 把 `(owner_key, claim_key)` 压成一个 u32 账本键。见 `apply` 的"账本键"一节。
///
/// splitmix32 风格的终结器（xorshift + 两次乘加）：确定性、纯整数、无分配。
/// 64 bit 输入压到 32 bit 必然有碰撞，但把 owner 先乘一个大奇数再混进 claim 键，
/// 使"同一 claim 键、不同 owner"落在互不相关的槽位上（单测逐对验证）。
const fn ledger_key(owner_key: u32, claim_key: u32) -> u32 {
    let mut hash = claim_key ^ owner_key.wrapping_mul(0x9E37_79B9);
    hash ^= hash >> 16;
    hash = hash.wrapping_mul(0x85EB_CA6B);
    hash ^= hash >> 13;
    hash = hash.wrapping_mul(0xC2B2_AE35);
    hash ^ (hash >> 16)
}

impl ClaimLedger {
    /// 账本容量。参考实现用字符串键的无界 `HashSet`；内核定长，取 64：
    /// 单次动作内"每动作一次"的 spec 数远低于此，且**满了必须返回 false 而不是 panic**。
    pub const CAPACITY: usize = 64;

    pub const fn new() -> Self {
        Self {
            action_claims: [0; Self::CAPACITY],
            action_len: 0,
            turn_claims: [0; Self::CAPACITY],
            turn_len: 0,
        }
    }

    /// 尝试占用一次"本动作"的名额。已占用或表满 ⇒ `false`。
    pub fn claim_action(&mut self, key: u32) -> bool {
        if self.action_claims[..self.action_len].contains(&key) {
            return false;
        }
        if self.action_len >= Self::CAPACITY {
            return false;
        }
        self.action_claims[self.action_len] = key;
        self.action_len += 1;
        true
    }

    /// 尝试占用一次"本回合"的名额。已占用或表满 ⇒ `false`。
    pub fn claim_turn(&mut self, key: u32) -> bool {
        if self.turn_claims[..self.turn_len].contains(&key) {
            return false;
        }
        if self.turn_len >= Self::CAPACITY {
            return false;
        }
        self.turn_claims[self.turn_len] = key;
        self.turn_len += 1;
        true
    }

    /// 回合开始时清空**只有**"本回合"那一半（参考实现：turn stats 在回合开始重置）。
    pub fn end_of_action(&mut self) {
        self.action_len = 0;
    }

    /// 回合结束：清空本动作 + 本回合两半。
    pub fn end_of_turn(&mut self) {
        self.action_len = 0;
        self.turn_len = 0;
    }
}

/// 本模块是纯函数，`CombatState` 只在文档里出现（调用方持有状态）。
/// 这个别名保证 `use` 与冻结签名一致，且不会因为未使用而告警。
pub type StateRef<'a> = &'a CombatState;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn claims_are_one_shot_per_scope() {
        let mut l = ClaimLedger::new();
        assert!(l.claim_action(7));
        assert!(!l.claim_action(7));      // 同一动作内第二次不给
        assert!(l.claim_turn(7));         // 但回合级是另一本账
        assert!(!l.claim_turn(7));

        l.end_of_action();
        assert!(l.claim_action(7));       // 新动作 ⇒ 重新可占
        assert!(!l.claim_turn(7));        // 回合级仍然占着

        l.end_of_turn();
        assert!(l.claim_turn(7));
    }

    #[test]
    fn a_full_ledger_refuses_instead_of_panicking() {
        let mut l = ClaimLedger::new();
        for i in 0..ClaimLedger::CAPACITY as u32 {
            assert!(l.claim_action(i), "第 {i} 个应当能占到");
        }
        // 满了：必须返回 false，绝不 panic、绝不覆盖已有的账。
        assert!(!l.claim_action(9999));
        assert!(!l.claim_action(0));
        assert!(!l.claim_action(ClaimLedger::CAPACITY as u32));
    }

    // =========================================================================================
    // 测试脚手架
    // =========================================================================================

    /// `status_id_pool` 的样例：四个标准状态 id，**池内的偏移序与字节序故意不一致**
    /// （偏移序 strength < weak < vulnerable，字节序 strength < vulnerable < weak），
    /// 这样"次级键是字节序、不是键的编号"才有反例可钉。
    const POOL: &[u8] = b"standard.strength|standard.weak|standard.vulnerable|standard.dexterity";

    /// 在池子里找出某个 id 的 `StatusKey`（测试用；内核侧不该这么找，键由内容层 intern 好）。
    fn key_of(id: &str) -> StatusKey {
        let needle = id.as_bytes();
        let mut offset = 0usize;
        while offset < POOL.len() {
            if POOL.get(offset..offset + needle.len()) == Some(needle) {
                return StatusKey {
                    offset: offset as u16,
                    len: needle.len() as u16,
                };
            }
            offset += 1;
        }
        panic!("{id} 不在测试池子里");
    }

    /// 造一条候选（两个 claim 位默认关，需要时单独开）。
    fn cand(
        priority: i32,
        id: &str,
        spec_index: u16,
        stacks: i32,
        operation: Operation,
        magnitude: i32,
    ) -> Candidate {
        Candidate {
            priority,
            status_key: key_of(id),
            spec_index,
            stacks,
            operation,
            magnitude,
            once_per_action: false,
            once_per_turn: false,
        }
    }

    /// 一条"所有门都开着"的 spec（逐条门控测试只改一个字段）。
    fn spec(pipeline: Pipeline) -> ModifierSpec {
        ModifierSpec {
            pipeline,
            priority: 100,
            operation: Operation::AddFlat,
            magnitude: 1,
            restrict_damage_kind: None,
            restrict_status_applies: false,
            restrict_element: false,
            restrict_source_card_tag: false,
            once_per_action: false,
            once_per_turn: false,
        }
    }

    /// 一个"所有门都开着"的 `FilterContext`。
    fn ctx(pipeline: Pipeline) -> FilterContext {
        FilterContext {
            pipeline,
            damage_kind: Some(0),
            status_applies: true,
            element_matches: true,
            source_card_has_tag: true,
            only_card_tagged: false,
        }
    }

    /// 跑一次 `apply`，用一本新账（单次调用语义的测试用）。
    fn run(amount: i32, candidates: &mut [Candidate], claim_keys: &[u32]) -> Applied {
        apply(
            amount,
            candidates,
            POOL,
            &mut ClaimLedger::new(),
            1,
            claim_keys,
        )
    }

    /// 门控测试的公共骨架。`apply` 看不到 spec，所以"门是否生效"的权威是
    /// [`spec_passes_filters`]；这里同时钉住它的**可观察后果**：过了门的 spec 被摊成候选后
    /// 真的贡献一条并改变数值，被拦掉的 spec 按契约不进候选表 ⇒ `applied_count` 不动、数值不变。
    fn gate_is_observable(
        open_spec: &ModifierSpec,
        open_ctx: &FilterContext,
        closed_spec: &ModifierSpec,
        closed_ctx: &FilterContext,
    ) {
        assert!(
            spec_passes_filters(open_spec, open_ctx),
            "门开着时这条 spec 必须通过"
        );
        assert!(
            !spec_passes_filters(closed_spec, closed_ctx),
            "门关上时这条 spec 必须被拦掉"
        );

        // 通过 ⇒ 摊成候选 ⇒ 真的 +5（7 → 12），并且只有 1 条贡献过。
        let mut admitted = [cand(100, "standard.strength", 0, 1, Operation::AddFlat, 5)];
        let with = run(7, &mut admitted, &[1]);
        assert_eq!(with.amount, 12);
        assert_eq!(with.applied_count, 1);

        // 被拦掉 ⇒ 候选表里没有这条 spec ⇒ 数值原样、applied_count 为 0。
        let mut omitted: [Candidate; 0] = [];
        let without = run(7, &mut omitted, &[]);
        assert_eq!(without.amount, 7);
        assert_eq!(without.applied_count, 0);
    }

    // =========================================================================================
    // 排序：加法先于乘法（规格书 §4.2 点名的反例）—— 两组都必须是可执行断言
    // =========================================================================================

    #[test]
    fn adds_before_multiplies_and_the_inverted_order_gives_a_different_number() {
        // 规格书 §4.2 #1（`ModifierPipelineTests.cs:102-122`）：base 5、力量 2、易伤。
        let strength = cand(100, "standard.strength", 0, 2, Operation::AddPerStack, 1);
        let vulnerable = cand(300, "standard.vulnerable", 0, 1, Operation::ScalePercent, 150);

        // 正确序（按 priority 折叠）：5 + 1*2 = 7 → 7*150/100 = 1050/100 = 10
        let mut correct = [strength, vulnerable];
        let good = run(5, &mut correct, &[1, 2]);
        assert_eq!(good.amount, 10);
        assert_eq!(good.applied_count, 2);

        // 输入序反过来**不影响结果**：排序看的是 priority，不是调用方摆的次序。
        let mut reversed = [vulnerable, strength];
        assert_eq!(run(5, &mut reversed, &[1, 2]).amount, 10);

        // 错序（把易伤做成抢在力量之前的乘法）：5*150/100 = 750/100 = 7 → 7 + 2 = 9
        let vulnerable_first = cand(50, "standard.vulnerable", 0, 1, Operation::ScalePercent, 150);
        let mut wrong = [vulnerable_first, strength];
        let bad = run(5, &mut wrong, &[1, 2]);
        assert_eq!(bad.amount, 9);
        assert_ne!(good.amount, bad.amount, "次序决定这个数");
    }

    #[test]
    fn base_seven_strength_three_weak_and_vulnerable_is_ten_not_twelve() {
        // 规格书 §4.2 #2 第二例：base 7、力量 3、虚弱、易伤。
        let strength = cand(100, "standard.strength", 0, 3, Operation::AddPerStack, 1);
        let weak = cand(200, "standard.weak", 0, 1, Operation::ScalePercent, 75);
        let vulnerable = cand(300, "standard.vulnerable", 0, 1, Operation::ScalePercent, 150);

        // 正确序：7 + 1*3 = 10 → 10*75/100 = 750/100 = 7 → 7*150/100 = 1050/100 = 10
        let mut right = [weak, vulnerable, strength];
        let correct = run(7, &mut right, &[1, 2, 3]);
        assert_eq!(correct.amount, 10);
        assert_eq!(correct.applied_count, 3);

        // 错序（虚弱抢在力量之前）：7*75/100 = 525/100 = 5 → 5 + 3 = 8 → 8*150/100 = 1200/100 = 12
        let weak_first = cand(50, "standard.weak", 0, 1, Operation::ScalePercent, 75);
        let mut wrong = [weak_first, strength, vulnerable];
        let wrong_applied = run(7, &mut wrong, &[1, 2, 3]);
        assert_eq!(wrong_applied.amount, 12);
        assert_ne!(correct.amount, wrong_applied.amount);
    }

    #[test]
    fn every_truncation_point_matches_the_reference() {
        // 每一步都是整数除法（`PassiveModifiers.cs:210`），四个截断点逐个钉住
        // （`BlockAmountModifierTests.cs:104-130,132-166` 与向量 1/2）。
        let weak = cand(200, "standard.weak", 0, 1, Operation::ScalePercent, 75);
        let strength = cand(100, "standard.strength", 0, 2, Operation::AddPerStack, 1);
        let vulnerable = cand(300, "standard.vulnerable", 0, 1, Operation::ScalePercent, 150);

        // 5*75/100 = 375/100 = 3（3.75 截到 3）
        assert_eq!(run(5, &mut [weak], &[1]).amount, 3);
        assert_eq!(5 * 75, 375);
        assert_eq!(5 * 75 % 100, 75, "375 = 3*100 + 75 ⇒ 真的截断了");

        // (5+2)*75/100 = 525/100 = 5（5.25 截到 5）
        assert_eq!(run(5, &mut [strength, weak], &[1, 2]).amount, 5);
        assert_eq!((5 + 2) * 75, 525);
        assert_eq!((5 + 2) * 75 % 100, 25);

        // 10*75/100 = 750/100 = 7（7.5 截到 7）
        assert_eq!(run(10, &mut [weak], &[1]).amount, 7);
        assert_eq!(10 * 75 % 100, 50);

        // 7*150/100 = 1050/100 = 10（10.5 截到 10）
        assert_eq!(run(7, &mut [vulnerable], &[1]).amount, 10);
        assert_eq!(7 * 150 % 100, 50);
    }

    #[test]
    fn scale_percent_ignores_stacks_so_duration_only_statuses_still_apply() {
        // 参考实现里 `Weak`/`Vulnerable`/`Frail` 只有**时长轴**（`UsesDuration`），实例的 `Stacks` 恒为 0；
        // 而 `:210` 的 `ScalePercent` **不读 stacks** —— 所以"层数 0 的乘法 spec"是**正常情况**，
        // 照样生效。谁若"顺手"照抄 `status_catalog.rs` 测试助手里的那句
        // `if stacks == 0 { continue; }`（那里用 0 表示"这个状态不存在"），
        // 虚弱/易伤就会在真实管线里静默失效。这条测试把这条界线钉死。
        let weak = cand(200, "standard.weak", 0, 0, Operation::ScalePercent, 75);
        let vulnerable = cand(300, "standard.vulnerable", 0, 0, Operation::ScalePercent, 150);
        let applied = run(7, &mut [weak], &[1]);
        assert_eq!(applied.amount, 5, "7*75/100 = 525/100 = 5，层数 0 不影响乘法");
        assert_eq!(applied.applied_count, 1);
        assert_eq!(run(7, &mut [vulnerable], &[1]).amount, 10, "7*150/100 = 1050/100 = 10");

        // 规格书 §4.2 那条 10 的真实形态：力量 3 + 层数 0 的虚弱 + 层数 0 的易伤。
        let strength = cand(100, "standard.strength", 0, 3, Operation::AddPerStack, 1);
        assert_eq!(run(7, &mut [vulnerable, weak, strength], &[1, 2, 3]).amount, 10);
    }

    #[test]
    fn the_secondary_key_is_byte_order_not_key_number_or_pool_offset() {
        // 同一个优先级、两个不同状态、都是 ScalePercent —— 乘法的**整数截断**让次序可观察。
        // 字节序（`string.CompareOrdinal`）：'v'(0x76) < 'w'(0x77) ⇒ vulnerable 先。
        // 池内偏移序恰好相反（weak@18 < vulnerable@32）⇒ 按"键的编号"排会得到另一个数。
        let weak = cand(200, "standard.weak", 0, 1, Operation::ScalePercent, 75);
        let vulnerable = cand(200, "standard.vulnerable", 0, 1, Operation::ScalePercent, 150);
        assert!(
            key_of("standard.vulnerable").offset > key_of("standard.weak").offset,
            "样例池的偏移序必须与字节序相反，否则这条测试是空的"
        );

        // 按字节序：5*150/100 = 750/100 = 7 → 7*75/100 = 525/100 = 5
        let mut by_bytes = [weak, vulnerable];
        let applied = run(5, &mut by_bytes, &[1, 2]);
        assert_eq!(applied.amount, 5);
        assert_eq!(applied.applied_count, 2);

        // 按偏移/编号序会得到：5*75/100 = 3 → 3*150/100 = 450/100 = 4
        assert_eq!(5 * 75 / 100, 3);
        assert_eq!(3 * 150 / 100, 4);
        assert_ne!(5, 4, "字节序与编号序必须能被区分开");
    }

    #[test]
    fn priority_dominates_the_status_bytes() {
        // 次级键只在 priority 相等时才轮到。base 4：
        //   按 priority：weak(p100) 先 +10 ⇒ 14 → 14*50/100 = 700/100 = 7
        //   按字节序：strength 的字节比 weak 小 ⇒ 4*50/100 = 2 → 2+10 = 12
        let weak_low_priority = cand(100, "standard.weak", 0, 1, Operation::AddFlat, 10);
        let strength_high_priority = cand(300, "standard.strength", 0, 1, Operation::ScalePercent, 50);
        let mut list = [strength_high_priority, weak_low_priority];
        let applied = run(4, &mut list, &[1, 2]);
        assert_eq!(applied.amount, 7);
        assert_ne!(applied.amount, 12);
    }

    #[test]
    fn spec_index_breaks_ties_after_the_status_bytes() {
        // 同一个状态、同一个 priority、两条 spec ⇒ `specIndex` 决定次序（`:184`）。
        let add_0 = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 2);
        let scale_1 = cand(100, "standard.strength", 1, 1, Operation::ScalePercent, 50);
        // specIndex 小的先：5 + 2 = 7 → 7*50/100 = 350/100 = 3
        let mut one_way = [scale_1, add_0];
        assert_eq!(run(5, &mut one_way, &[1, 2]).amount, 3);

        let scale_0 = cand(100, "standard.strength", 0, 1, Operation::ScalePercent, 50);
        let add_1 = cand(100, "standard.strength", 1, 1, Operation::AddFlat, 2);
        // 换过来：5*50/100 = 250/100 = 2 → 2 + 2 = 4
        let mut other_way = [add_1, scale_0];
        assert_eq!(run(5, &mut other_way, &[1, 2]).amount, 4);
    }

    #[test]
    fn there_is_no_candidate_capacity_limit() {
        // 131 条候选（远超任何"定长缓冲区"的规模）。排序用按秩选择 ⇒ 无上限、无降级。
        // 130 条 priority 100 的 AddFlat(1) 必须先全部跑完，再轮到 priority 200 的 ScalePercent(50)：
        //   2 + 130 = 132 → 132*50/100 = 6600/100 = 66
        // 若没有排序（Scale 抢在前面）：2*50/100 = 1 → 1 + 130 = 131。
        let add = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 1);
        let mut many = [add; 131];
        many[0] = cand(200, "standard.weak", 0, 1, Operation::ScalePercent, 50);

        let applied = run(2, &mut many, &[]);
        assert_eq!(applied.amount, 66);
        assert_eq!(applied.applied_count, 131);
        assert_ne!(applied.amount, 131);
    }

    #[test]
    fn candidates_are_not_permuted_in_place() {
        // `claim_keys` 与 `candidates` 按下标平行；就地置换会让候选与自己的键错位。
        // 所以 `apply` 只读 `candidates` —— 这条测试把该设计决定变成可执行断言。
        let scale = cand(200, "standard.weak", 0, 1, Operation::ScalePercent, 75);
        let add = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 2);
        let mut list = [scale, add];
        let _ = run(5, &mut list, &[11, 22]);
        assert_eq!(list[0].operation, Operation::ScalePercent);
        assert_eq!(list[0].priority, 200);
        assert_eq!(list[1].operation, Operation::AddFlat);
        assert_eq!(list[1].priority, 100);
    }

    #[test]
    fn duplicate_keys_fall_back_to_the_original_index_deterministically() {
        // 完全重复的排序键（同 priority、同状态、同 specIndex）在 C# 里次序无契约
        // （`List.Sort` 不稳定）；内核选"按原始下标"，至少是确定的。
        let scale = cand(100, "standard.strength", 0, 1, Operation::ScalePercent, 50);
        let add = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 1);
        // 下标 0（Scale）先：10*50/100 = 500/100 = 5 → 5 + 1 = 6
        let mut list = [scale, add];
        let applied = run(10, &mut list, &[1, 2]);
        assert_eq!(applied.amount, 6);
        assert_eq!(applied.applied_count, 2);
        // 下标 1（Add）先：10 + 1 = 11 → 11*50/100 = 550/100 = 5
        let mut swapped = [add, scale];
        assert_eq!(run(10, &mut swapped, &[1, 2]).amount, 5);
    }

    // =========================================================================================
    // 四种运算
    // =========================================================================================

    #[test]
    fn add_per_stack_with_zero_stacks_changes_nothing_but_still_counts_and_burns_the_claim() {
        // C# `:208`：`current + magnitude * stacks`；0 层 ⇒ 加 0 ⇒ 数值不变，但**照样执行**。
        let mut zero_stacks = cand(100, "standard.strength", 0, 0, Operation::AddPerStack, 1);
        zero_stacks.once_per_action = true;
        let mut list = [zero_stacks];
        let mut ledger = ClaimLedger::new();

        let first = apply(7, &mut list, POOL, &mut ledger, 1, &[7]);
        assert_eq!(first.amount, 7, "7 + 1*0 = 7：数值不变");
        assert_eq!(first.applied_count, 1, "但它照样走到了操作那一步");

        // 数值不变的**代价**是真实存在的：那一次 claim 被烧掉了（与 C# 一致），
        // 所以同一动作内第二次连"什么都不做"都不再被算作贡献。
        let second = apply(7, &mut list, POOL, &mut ledger, 1, &[7]);
        assert_eq!(second.amount, 7);
        assert_eq!(second.applied_count, 0, "claim 已占 ⇒ 整条被跳过");

        // 换一个 owner ⇒ 另一本账（回合级/动作级都按 owner 分账）。
        let other_owner = apply(7, &mut list, POOL, &mut ledger, 2, &[7]);
        assert_eq!(other_owner.applied_count, 1);

        // 层数非 0 时逐层乘：3 层 × 幅值 2 ⇒ 7 + 6 = 13。
        let mut three = cand(100, "standard.strength", 0, 3, Operation::AddPerStack, 2);
        three.once_per_action = false;
        assert_eq!(run(7, &mut [three], &[1]).amount, 13);
        // 负层数（模型里不该出现，但门开着就照 C# 算）：7 + 1*(-2) = 5。
        let negative = cand(100, "standard.strength", 0, -2, Operation::AddPerStack, 1);
        assert_eq!(run(7, &mut [negative], &[1]).amount, 5);
    }

    #[test]
    fn clamp_max_caps_at_zero_when_the_magnitude_is_negative() {
        // C# `:211`：`Math.Min(current, Math.Max(0, magnitude))`。幅值为负 ⇒ 上限是 0。
        let negative_cap = cand(100, "standard.strength", 0, 1, Operation::ClampMax, -5);
        let applied = run(9, &mut [negative_cap], &[1]);
        assert_eq!(applied.amount, 0, "min(9, max(0,-5)=0) = 0");
        assert_eq!(applied.applied_count, 1, "抹平也算贡献（管线走到了这一步）");

        // 正幅值照常当上限。
        let cap_four = cand(100, "standard.strength", 0, 1, Operation::ClampMax, 4);
        assert_eq!(run(9, &mut [cap_four], &[1]).amount, 4, "min(9, 4) = 4");
        assert_eq!(run(3, &mut [cap_four], &[1]).amount, 3, "min(3, 4) = 3");

        // 幅值 0 是合法的"完全抹掉"（规格书 §3 S2：把数值降到 0 是唯一的否决方式）。
        let cap_zero = cand(100, "standard.strength", 0, 1, Operation::ClampMax, 0);
        assert_eq!(run(42, &mut [cap_zero], &[1]).amount, 0);
    }

    #[test]
    fn intermediate_values_may_go_negative_and_only_the_end_is_clamped() {
        // 契约 6：整个折叠只在**末尾**夹一次 `max(0, ·)`（`:216`；折叠器外层 `DamageEffects.cs:312`
        // 还有一次，但那不属于本函数）。中间的负数是允许的，且会影响后续的除法方向。
        let subtract = cand(100, "standard.strength", 0, 1, Operation::AddFlat, -10);
        let halve = cand(200, "standard.weak", 0, 1, Operation::ScalePercent, 50);
        // 5 - 10 = -5 → -5*50/100 = -250/100 = -2（向零截断，不是 -3）→ 末尾 max(0,-2) = 0。
        let applied = run(5, &mut [subtract, halve], &[1, 2]);
        assert_eq!(applied.amount, 0);
        assert_eq!(applied.applied_count, 2);
        // 单看中间量：C# 的 `-250 / 100` 也是 -2（C# 的整数除法同样向零截断）。
        assert_eq!(-250 / 100, -2);
        assert_eq!(-250 % 100, -50);
    }

    // =========================================================================================
    // 契约 1：非正数原样返回
    // =========================================================================================

    #[test]
    fn non_positive_amounts_return_unchanged_and_never_touch_the_ledger() {
        let mut claimable = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 5);
        claimable.once_per_action = true;
        let mut list = [claimable];
        let mut ledger = ClaimLedger::new();

        // 负数：原样（-3 保持 -3，不是 0 —— 管线根本没跑）。
        assert_eq!(
            apply(-3, &mut list, POOL, &mut ledger, 1, &[1]),
            Applied {
                amount: -3,
                applied_count: 0
            }
        );
        // 0：原样，也不贡献。
        assert_eq!(
            apply(0, &mut list, POOL, &mut ledger, 1, &[1]),
            Applied {
                amount: 0,
                applied_count: 0
            }
        );

        // 两次早退都**没动账本** ⇒ 紧接着的一次正常调用照样能占到那一次 claim。
        let live = apply(4, &mut list, POOL, &mut ledger, 1, &[1]);
        assert_eq!(live.amount, 9);
        assert_eq!(live.applied_count, 1);
    }

    // =========================================================================================
    // 契约 2：逐条门控（每一条都要有一个"被拦掉"的例子）
    // =========================================================================================

    #[test]
    fn pipeline_gate_rejects_specs_of_another_pipeline() {
        let open = spec(Pipeline::DamageDealt);
        let closed = spec(Pipeline::Block);
        gate_is_observable(&open, &ctx(Pipeline::DamageDealt), &closed, &ctx(Pipeline::DamageDealt));
        // 反向也成立：Block 的 spec 在 Block 管线里通过、在伤害管线里被拦。
        gate_is_observable(&closed, &ctx(Pipeline::Block), &open, &ctx(Pipeline::Block));
    }

    #[test]
    fn damage_kind_gate_rejects_a_different_kind_only_when_both_sides_are_present() {
        let mut restricted = spec(Pipeline::DamageDealt);
        restricted.restrict_damage_kind = Some(0); // Direct

        // spec 限制 Direct、本次是 DoT ⇒ 拦掉。
        let mut dot = ctx(Pipeline::DamageDealt);
        dot.damage_kind = Some(1);
        gate_is_observable(&restricted, &ctx(Pipeline::DamageDealt), &restricted, &dot);

        // spec 没限制种类 ⇒ 任何种类都通过（`restrict_damage_kind: None`）。
        let unrestricted = spec(Pipeline::DamageDealt);
        assert!(spec_passes_filters(&unrestricted, &dot));

        // 本次没有种类 ⇒ 这一门整段跳过（`:155` 的字面语义：`damageKind is {} kind` 不成立）。
        let mut no_kind = ctx(Pipeline::DamageDealt);
        no_kind.damage_kind = None;
        assert!(spec_passes_filters(&restricted, &no_kind));

        // 非伤害管线的调用方约定就是传 `None`（规格书 §2.2：格挡折叠器传 `damageKind: null`，
        // `PassiveModifiers.cs:267`）—— 换成 Block 管线的 spec、Block 管线的上下文，结论一样：
        // 这一门在"没有种类"时完全不参与，而不是"非伤害管线就该拦"。
        let mut block_spec = spec(Pipeline::Block);
        block_spec.restrict_damage_kind = Some(1);
        let mut block_ctx = ctx(Pipeline::Block);
        block_ctx.damage_kind = None;
        assert!(spec_passes_filters(&block_spec, &block_ctx));
        // 而同一对（spec 限制 DoT、上下文给 Direct）在 Block 管线里也会被这一门拦掉 ——
        // 因为 `:155` 没有 pipeline 条件，它是纯粹的"两边都有值且不等"。调用方的约定是
        // 别在非伤害管线上传种类，不是指望这一门自己认得管线（这是与 C# 一致的口径）。
        block_ctx.damage_kind = Some(0);
        assert!(!spec_passes_filters(&block_spec, &block_ctx));
    }

    #[test]
    fn status_applies_gate_rejects_a_spec_bound_to_another_status() {
        let mut bound = spec(Pipeline::DamageDealt);
        bound.restrict_status_applies = true;

        // spec 绑了某个状态、而本次施加的不是它（调用方把 `status_applies` 折成 false）⇒ 拦掉。
        let mut mismatch = ctx(Pipeline::DamageDealt);
        mismatch.status_applies = false;
        gate_is_observable(&bound, &ctx(Pipeline::DamageDealt), &bound, &mismatch);

        // spec 没绑状态（`AppliesToStatusId` 为 null）⇒ 这一门永不生效，与 `status_applies` 无关。
        let unbound = spec(Pipeline::DamageDealt);
        assert!(spec_passes_filters(&unbound, &mismatch));
    }

    #[test]
    fn element_gate_rejects_a_spec_restricted_to_another_element() {
        let mut fire_only = spec(Pipeline::DamageDealt);
        fire_only.restrict_element = true;

        // 本次元素不是它（含"本次无元素"）⇒ 拦掉。
        let mut mismatch = ctx(Pipeline::DamageDealt);
        mismatch.element_matches = false;
        gate_is_observable(&fire_only, &ctx(Pipeline::DamageDealt), &fire_only, &mismatch);

        // 没限制元素的 spec 不受影响。
        let any_element = spec(Pipeline::DamageDealt);
        assert!(spec_passes_filters(&any_element, &mismatch));
    }

    #[test]
    fn source_card_tag_gate_rejects_when_the_source_card_lacks_the_tag() {
        let mut needs_tag = spec(Pipeline::DamageDealt);
        needs_tag.restrict_source_card_tag = true;

        // 来源卡没带那个标签（"没有来源卡"—— 敌人行动、状态跳伤 —— 也算没带）⇒ 拦掉。
        let mut untagged = ctx(Pipeline::DamageDealt);
        untagged.source_card_has_tag = false;
        gate_is_observable(&needs_tag, &ctx(Pipeline::DamageDealt), &needs_tag, &untagged);

        // 不要求标签的 spec 不受影响。
        let agnostic = spec(Pipeline::DamageDealt);
        assert!(spec_passes_filters(&agnostic, &untagged));
    }

    #[test]
    fn only_card_tagged_gate_implies_the_spec_itself_must_carry_a_card_tag() {
        // `:170`：`onlyCardTagged && spec.RestrictSourceCardTag is null ⇒ continue`。
        // 注意这一门与"来源卡带没带标签"无关：调用方即便说来源卡有标签，
        // spec 自己没有 RestrictSourceCardTag 一样要被丢掉。
        let mut only = ctx(Pipeline::DamageDealt);
        only.only_card_tagged = true;
        assert!(only.source_card_has_tag, "来源卡本身是带标签的");

        let untagged_spec = spec(Pipeline::DamageDealt);
        assert!(
            !spec_passes_filters(&untagged_spec, &only),
            "onlyCardTagged 隐含要求 spec 自己带来源卡标签"
        );

        // 带标签的 spec 在同一个上下文里通过 —— 这才是"被拦掉"的反例对照。
        let mut tagged_spec = spec(Pipeline::DamageDealt);
        tagged_spec.restrict_source_card_tag = true;
        gate_is_observable(&tagged_spec, &only, &untagged_spec, &only);
    }

    #[test]
    fn every_gate_open_passes_and_all_of_them_are_checked() {
        let mut everything = spec(Pipeline::DamageDealt);
        everything.restrict_damage_kind = Some(0);
        everything.restrict_status_applies = true;
        everything.restrict_element = true;
        everything.restrict_source_card_tag = true;
        assert!(spec_passes_filters(&everything, &ctx(Pipeline::DamageDealt)));

        // 逐条单独关门，每次都必须被拦掉（说明六个合取项一个都没漏）。
        let mut closed = everything;
        closed.pipeline = Pipeline::Block;
        assert!(!spec_passes_filters(&closed, &ctx(Pipeline::DamageDealt)));

        let mut closed = everything;
        closed.restrict_damage_kind = Some(1);
        assert!(!spec_passes_filters(&closed, &ctx(Pipeline::DamageDealt)));

        let mut c = ctx(Pipeline::DamageDealt);
        c.status_applies = false;
        assert!(!spec_passes_filters(&everything, &c));

        let mut c = ctx(Pipeline::DamageDealt);
        c.element_matches = false;
        assert!(!spec_passes_filters(&everything, &c));

        let mut c = ctx(Pipeline::DamageDealt);
        c.source_card_has_tag = false;
        assert!(!spec_passes_filters(&everything, &c));

        let mut c = ctx(Pipeline::DamageDealt);
        c.only_card_tagged = true;
        assert!(spec_passes_filters(&everything, &c), "带标签的 spec 仍通过");
    }

    // =========================================================================================
    // 契约 5：claim 的两个作用域（claim 必须在所有门控之后）
    // =========================================================================================

    #[test]
    fn once_per_action_recovers_at_the_next_action_but_once_per_turn_does_not() {
        let mut per_action = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 2);
        per_action.once_per_action = true;
        let mut per_turn = cand(200, "standard.weak", 0, 1, Operation::AddFlat, 3);
        per_turn.once_per_turn = true;
        let mut list = [per_action, per_turn];
        let mut ledger = ClaimLedger::new();

        // 同一动作内第一次：两条都贡献（+2、+3）。
        let first = apply(10, &mut list, POOL, &mut ledger, 1, &[11, 22]);
        assert_eq!(first.amount, 15);
        assert_eq!(first.applied_count, 2);

        // 同一动作内第二次：两条都抢不到 ⇒ 不贡献。
        let second = apply(10, &mut list, POOL, &mut ledger, 1, &[11, 22]);
        assert_eq!(second.amount, 10);
        assert_eq!(second.applied_count, 0);

        // `end_of_action()`：动作级恢复，回合级仍占着（这是两个作用域的分界）。
        ledger.end_of_action();
        let next_action = apply(10, &mut list, POOL, &mut ledger, 1, &[11, 22]);
        assert_eq!(next_action.amount, 12, "动作级恢复了（+2）");
        assert_eq!(next_action.applied_count, 1, "回合级还占着 ⇒ 只有一条贡献");

        // `end_of_turn()`：两半都清空 ⇒ 两条都恢复。
        ledger.end_of_turn();
        let next_turn = apply(10, &mut list, POOL, &mut ledger, 1, &[11, 22]);
        assert_eq!(next_turn.amount, 15);
        assert_eq!(next_turn.applied_count, 2);
    }

    #[test]
    fn a_spec_with_both_scopes_burns_its_action_claim_even_when_the_turn_claim_fails() {
        // 照抄 C#（`:193-201`）：动作级 claim 先占，回合级抢不到就 `continue` ——
        // 那笔动作级的账**已经记下了**。这个"半烧"的副作用是可观察的。
        let mut both = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 4);
        both.once_per_action = true;
        both.once_per_turn = true;
        let mut list = [both];
        let mut ledger = ClaimLedger::new();

        let first = apply(1, &mut list, POOL, &mut ledger, 1, &[5]);
        assert_eq!(first.amount, 5);
        assert_eq!(first.applied_count, 1);

        // 动作级 claim 已被同一动作的第二次调用"占过"（第一次），这里直接失败。
        assert_eq!(apply(1, &mut list, POOL, &mut ledger, 1, &[5]).applied_count, 0);

        // 新动作：动作级恢复 ⇒ 占下；回合级仍占着 ⇒ 被跳过。动作级那笔账在这一刻被烧掉。
        ledger.end_of_action();
        let next_action = apply(1, &mut list, POOL, &mut ledger, 1, &[5]);
        assert_eq!(next_action.amount, 1);
        assert_eq!(next_action.applied_count, 0);

        // 于是**同一个动作里的第二次**也贡献不了：不是被回合级拦的，是上一刻已经烧掉了动作级名额。
        assert_eq!(apply(1, &mut list, POOL, &mut ledger, 1, &[5]).applied_count, 0);

        // 回合结束：两半都清 ⇒ 又贡献一次。
        ledger.end_of_turn();
        let after_turn = apply(1, &mut list, POOL, &mut ledger, 1, &[5]);
        assert_eq!(after_turn.amount, 5);
        assert_eq!(after_turn.applied_count, 1);
    }

    #[test]
    fn different_owners_do_not_share_the_ledger_in_either_scope() {
        // 动作级：C# 的键里含 `combatant.Id`（`:194`）。
        let mut per_action = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 2);
        per_action.once_per_action = true;
        let mut list = [per_action];
        let mut ledger = ClaimLedger::new();
        assert_eq!(apply(1, &mut list, POOL, &mut ledger, 1, &[7]).applied_count, 1);
        assert_eq!(apply(1, &mut list, POOL, &mut ledger, 1, &[7]).applied_count, 0);
        assert_eq!(apply(1, &mut list, POOL, &mut ledger, 2, &[7]).applied_count, 1);
        assert_eq!(apply(1, &mut list, POOL, &mut ledger, 2, &[7]).applied_count, 0);
        // 同一个 owner 换个候选键 ⇒ 当然是另一笔账。
        assert_eq!(apply(1, &mut list, POOL, &mut ledger, 1, &[8]).applied_count, 1);

        // 回合级：C# 的字符串里没有单位，但账本**每个战斗员一本**
        // （`combat.GetCardPlayTurnStats(combatant.Id)`，`:199`）⇒ 内核必须把 owner 混进键里，
        // 否则 A 的"每回合一次"会拦住 B 的同一条 spec。
        let mut per_turn = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 2);
        per_turn.once_per_turn = true;
        let mut turn_list = [per_turn];
        let mut turn_ledger = ClaimLedger::new();
        assert_eq!(
            apply(1, &mut turn_list, POOL, &mut turn_ledger, 1, &[7]).applied_count,
            1
        );
        assert_eq!(
            apply(1, &mut turn_list, POOL, &mut turn_ledger, 1, &[7]).applied_count,
            0
        );
        assert_eq!(
            apply(1, &mut turn_list, POOL, &mut turn_ledger, 2, &[7]).applied_count,
            1,
            "另一个战斗员有自己的回合账本"
        );
    }

    #[test]
    fn ledger_key_is_deterministic_and_splits_owner_from_claim_key() {
        // 混合必须是纯函数（同样的输入给同样的键）。
        assert_eq!(ledger_key(3, 9), ledger_key(3, 9));

        // 64 个 claim 键 × 4 个 owner 两两不同 —— owner 与 claim 都真的参与了。
        let owners = [0u32, 1, 2, u32::MAX];
        let mut pairs: [u32; 4 * 64] = [0; 256];
        let mut count = 0usize;
        for owner in owners {
            for claim in 0..64u32 {
                pairs[count] = ledger_key(owner, claim);
                count += 1;
            }
        }
        assert_eq!(count, pairs.len());
        for (left, left_key) in pairs.iter().enumerate() {
            for right_key in pairs.iter().skip(left + 1) {
                assert_ne!(
                    left_key, right_key,
                    "混合后第 {left} 个键与它后面的某个键撞了（owner/claim 没有真正参与混合）"
                );
            }
        }
    }

    #[test]
    fn a_full_ledger_refuses_the_extra_candidates_without_panicking() {
        // 候选数（70）**超过**账本容量（64）：前面 64 条按序占到位，后面 6 条被拒 ——
        // 返回 false 而不是 panic，也不覆盖已有的账（契约与既有测试一致）。
        let add = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 1);
        let mut many = [add; 70];
        for (index, slot) in many.iter_mut().enumerate() {
            slot.once_per_action = true;
            slot.spec_index = index as u16;
        }
        let keys: [u32; 70] = core::array::from_fn(|index| index as u32);

        let applied = apply(1, &mut many, POOL, &mut ClaimLedger::new(), 1, &keys);
        assert_eq!(applied.applied_count, ClaimLedger::CAPACITY as u16);
        assert_eq!(applied.amount, 1 + ClaimLedger::CAPACITY as i32);
    }

    #[test]
    fn missing_or_extra_claim_keys_degrade_without_panicking() {
        // 键表短于候选表：缺失的按 0 处理（确定性降级）。两条候选于是共享一个键：
        // 第一条占下、第二条被拒 —— 不 panic，也不静默地把账记到别人头上。
        let mut first = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 2);
        first.once_per_action = true;
        let mut second = cand(200, "standard.weak", 0, 1, Operation::AddFlat, 3);
        second.once_per_action = true;
        let mut list = [first, second];

        let applied = run(1, &mut list, &[]);
        assert_eq!(applied.applied_count, 1);
        assert_eq!(applied.amount, 3, "只有第一条（+2）拿到了那个缺省的键");

        // 键表更长也无所谓：多出来的被忽略。
        let mut list = [first, second];
        let applied = run(1, &mut list, &[1, 2, 3, 4, 5]);
        assert_eq!(applied.applied_count, 2);
        assert_eq!(applied.amount, 6);
    }

    // =========================================================================================
    // 越界的 StatusKey
    // =========================================================================================

    #[test]
    fn status_bytes_reads_the_interval_and_degrades_to_empty() {
        // `[offset, offset+len)` 的语义：前缀截断也照读。
        assert_eq!(status_bytes(POOL, key_of("standard.weak")), b"standard.weak");
        assert_eq!(
            status_bytes(POOL, StatusKey { offset: 0, len: 8 }),
            b"standard"
        );
        assert_eq!(status_bytes(POOL, StatusKey { offset: 0, len: 0 }), b"");
        // 三种越界都降级成空串，绝不 panic。
        assert_eq!(status_bytes(POOL, StatusKey { offset: 1000, len: 5 }), b"");
        assert_eq!(status_bytes(POOL, StatusKey { offset: 60, len: 100 }), b"");
        assert_eq!(
            status_bytes(POOL, StatusKey { offset: u16::MAX, len: u16::MAX }),
            b""
        );
    }

    #[test]
    fn out_of_range_status_keys_sort_first_and_never_panic() {
        // 空串在字节序里最小 ⇒ 越界键排在**所有**合法键之前。用同一优先级下的
        // ScalePercent / AddFlat 把这件"看不见的事"变成可观察的数字：
        let mut broken = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 1);
        broken.status_key = StatusKey {
            offset: 4096,
            len: 3,
        };
        let valid = cand(100, "standard.strength", 1, 1, Operation::ScalePercent, 50);
        // 越界键先：10 + 1 = 11 → 11*50/100 = 550/100 = 5
        let applied = run(10, &mut [valid, broken], &[1, 2]);
        assert_eq!(applied.amount, 5);
        assert_eq!(applied.applied_count, 2);
        // 若合法键先：10*50/100 = 5 → 5 + 1 = 6（两者不同 ⇒ 这条断言不是空的）。
        assert_ne!(applied.amount, 6);

        // 溢出 u16 的 offset+len 同样降级成空串，不 panic。
        let mut overflowing = cand(100, "standard.strength", 0, 1, Operation::AddFlat, 1);
        overflowing.status_key = StatusKey {
            offset: u16::MAX,
            len: u16::MAX,
        };
        let applied = run(10, &mut [valid, overflowing], &[1, 2]);
        assert_eq!(applied.amount, 5);
        assert_eq!(applied.applied_count, 2);

        // 多条越界键之间：空串相等 ⇒ 落到 spec_index / 原始下标（确定性次序）。
        let mut broken_scale = cand(100, "standard.strength", 0, 1, Operation::ScalePercent, 50);
        broken_scale.status_key = StatusKey { offset: 999, len: 9 };
        let mut broken_add = cand(100, "standard.strength", 2, 1, Operation::AddFlat, 1);
        broken_add.status_key = StatusKey { offset: 999, len: 9 };
        // specIndex 0 先：10*50/100 = 5 → 5 + 1 = 6
        assert_eq!(run(10, &mut [broken_add, broken_scale], &[1, 2]).amount, 6);
    }
}
