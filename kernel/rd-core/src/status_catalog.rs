//! 状态与修饰器的**目录表**：有哪些状态、它们改什么、在哪个阶段、以什么次序。
//!
//! **规格**：`docs/spec/modifier-pipeline.md`（§2 数据结构、§3 管线阶段、§4 顺序契约）与
//! `docs/spec/SEMANTICS-v1.md`（§3 偏离、§4 顺序契约 O1–O53）。
//! 参考实现：`ref\RogueDeck-Core\src\RogueDeck.Core\Combat\Effects\{DamageAmountModifiers,BlockAmountModifiers,StatusEffects}.cs`。
//!
//! 关键事实（来自规格书，别凭直觉写）：
//! * **修饰器有两个独立的优先级轴**：修饰器对象的 Priority（标准包里两个声明式都是 1000）
//!   与 spec 的 Priority（**Strength 100 加法 / Weak 200 乘法 / Vulnerable 300**）。
//! * **Vulnerable 在 Target 阶段**，Strength / Weak 在 Source 阶段；标准公式 `((base+力量)*0.75)*1.5`。
//! * 加法先于乘法。
//! * 这个模块**是纯数据 + 纯谓词**，不依赖 `state.rs`，所以能独立开发与验收。
//!
//! # 这张表是怎么排出来的（O11 / O12 / O13）
//!
//! S2 的循环是**硬编码的阶段序** `Source → Target → Global`（`DamageEffects.cs:7-13`，O11），
//! 阶段内部才按修饰器自己的 `(Priority, ModifierId)` 走（`CombatDefinitionRegistryBuilder.cs:584-590`，O12）。
//! 标准包的每一条数值规则都已经被摊成**声明式 spec** 挂在状态定义上（`StandardCombatPackage.cs`），
//! 折叠器内部再按 `(spec.Priority, statusId 字符串序, specIndex)` 排（`PassiveModifiers.cs:179-185`，O13）。
//!
//! ⇒ 对本模块而言：**阶段与 spec 优先级就是全部排序信息**，下面两张表按 `(stage, spec_priority)` 排死，
//! 调用方顺序扫一遍即可，不需要在运行期排序（`M:§6.4`：这些表编译期固定、放 flash）。
//! 每一条的 `statusId` 都不同且优先级不同，所以次级键（字符串序，D9）在本表里不会决出胜负 ——
//! 但 `standard_status_ids_sorted()` 仍然按字符串序给出，因为别的排序点（触发器 O6、校验器 O49）
//! 要用同一套键。
//!
//! # 整数、取整点、种类门
//!
//! * 所有幅值都是整数：`ScalePercent` = `cur * magnitude / 100` 且**向下取整**（`PassiveModifiers.cs:210`），
//!   `AddPerStack` = `cur + magnitude * stacks`（`:208`）。每步之后 `max(0, ·)`（`:216`、`DamageEffects.cs:312`）。
//! * 伤害修饰**默认只对 `Direct` 生效**（`PassiveModifiers.cs:87` 的 `RestrictDamageKind = Direct`
//!   与 `:155` 的门），DoT 与反伤不吃 Strength/Weak/Vulnerable（O16、验收向量 #4）。这个门是**每 spec**
//!   的字段，标准包三行取值相同，所以在本模块里提成一个常量（[`DAMAGE_MODIFIER_DAMAGE_KINDS`]）。

// ---------------------------------------------------------------------------------------------
// 冻结接口（签名不改；实现见下方各表）
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModifierTarget {
    /// 攻击方身上的状态（力量 / 虚弱）。
    Source,
    /// 受方身上的状态（易伤）。
    Target,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModifierOp {
    /// 加常量：`v += stacks * 1`
    AddStacks,
    /// 乘常量：`v = v * pct / 100`（**整数百分比，禁止浮点**）
    MulPercent,
}

/// 填充约定（冻结结构体的字段语义，别另造一套）：
/// * `percent` 就是 spec 的 `Magnitude`：`MulPercent` 行是百分比（虚弱 75、易伤 150），
///   `AddStacks` 行是**每层幅值**（标准包恒为 1，`StandardCombatPackage.cs:430,362`）。
///   （下面 `percent` 字段的注释"仅 `MulPercent` 用"是冻结原文；`AddStacks` 行的幅值必须有地方放，
///   标准包里它恒为 1 —— 所以"加法只看层数"与"读 `percent` 当幅值"两种读法给出同一个数。）
/// * `spec_priority` 是 spec 的 `Priority`（100/200/300），**不是**修饰器对象的 Priority（1000）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DamageModifierEntry {
    /// 状态 id，ASCII（例：`standard.strength`）。
    pub status_id: &'static str,
    pub stage: ModifierTarget,
    pub op: ModifierOp,
    /// 仅 `MulPercent` 用；整数百分比（虚弱 75、易伤 150）。
    pub percent: i32,
    /// spec 优先级：加法 100、乘法 200、Vulnerable 300。
    pub spec_priority: i32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BlockModifierEntry {
    pub status_id: &'static str,
    pub op: ModifierOp,
    pub percent: i32,
    pub spec_priority: i32,
}

// ---------------------------------------------------------------------------------------------
// 阶段序（O11）
// ---------------------------------------------------------------------------------------------

/// 阶段的**契约序**：`Source(0) → Target(1) → Global(2)`（`DamageEffects.cs:7-13`）。
///
/// 本模块的 [`ModifierTarget`] 只有 `Source`/`Target` 两档 —— 与 `M:§1.4`「阶段数可砍到 2，
/// Global 在标准内容里是空的」一致：标准包两个折叠器分别绑 `Source`/`Target`，没有 `Global` 行。
/// 将来若内容需要 Global，先扩这个枚举（本函数是唯一一处把阶段映射成数的代码）。
#[must_use]
pub const fn stage_rank(stage: ModifierTarget) -> u8 {
    match stage {
        ModifierTarget::Source => 0,
        ModifierTarget::Target => 1,
    }
}

// ---------------------------------------------------------------------------------------------
// 伤害修饰表（S2 的 Source / Target 阶段）
// ---------------------------------------------------------------------------------------------

/// 参考实现里**修饰器对象**的优先级：两个声明式伤害折叠器与格挡折叠器都是 1000
/// （`PassiveModifiers.cs:239,260`），ModifierId 才是它们的次级键
/// （`standard.declarative_damage_dealt` / `_received` / `standard.declarative_block_gain`）。
///
/// 它**不是**下面两张表的排序键 —— 规格书 §2 特意把"两个独立的优先级轴"标出来：
/// 对象优先级决定"哪个折叠器对象先跑"（标准包里每个阶段恰好只有一个对象命中），
/// spec 优先级才决定"同一阶段里加法与乘法谁先"。本模块只固化后者。
pub const DAMAGE_MODIFIER_OBJECT_PRIORITY: i32 = 1000;

/// `DamageKind` 的位（`CombatPrimitives.cs:18-23`：`Direct=0, DamageOverTime=1, Reflected=2`）。
/// 内核还没有 `state.rs` 的 `DamageKind` 类型，所以这里用位表达；落地后直接 `1 << (kind as u32)`。
pub const DAMAGE_KIND_DIRECT: u32 = 1 << 0;
/// DoT（中毒一跳）。
pub const DAMAGE_KIND_DAMAGE_OVER_TIME: u32 = 1 << 1;
/// 反伤（荆棘）。
pub const DAMAGE_KIND_REFLECTED: u32 = 1 << 2;

/// 标准包三行伤害修饰**共用的种类门**：只对 `Direct` 生效（`PassiveModifiers.cs:87` 的默认值
/// `RestrictDamageKind = Direct` + `:155` 的门）。DoT 与反伤**整表不参与**（O16、验收向量 #4）。
///
/// 之所以是"一个常量而不是表里的一列"：门是逐 spec 的字段，而标准包三行取值完全相同，
/// 冻结的 `DamageModifierEntry` 里也没有这一列。内容侧的 spec 门是**逐条**的，属于内容表的事。
pub const DAMAGE_MODIFIER_DAMAGE_KINDS: u32 = DAMAGE_KIND_DIRECT;

/// `spec.Priority`：加法 100（`StandardCombatPackage.cs:430,362`）。
pub const SPEC_PRIORITY_ADD: i32 = 100;
/// `spec.Priority`：乘法 200（`StandardCombatPackage.cs:282,320`）。
pub const SPEC_PRIORITY_SCALE: i32 = 200;
/// `spec.Priority`：易伤 300（`StandardCombatPackage.cs:341`）。
pub const SPEC_PRIORITY_VULNERABLE: i32 = 300;

/// 三行伤害修饰，**已按 `(stage, spec_priority)` 排好**：Source/100 力量 → Source/200 虚弱 →
/// Target/300 易伤。这就是 `((base + 力量) * 75 / 100) * 150 / 100` 的全部真相。
const DAMAGE_MODIFIERS: [DamageModifierEntry; 3] = [
    // 力量：DamageDealt / AddPerStack / Magnitude 1 / Priority 100（`StandardCombatPackage.cs:428-431`）
    DamageModifierEntry {
        status_id: "standard.strength",
        stage: ModifierTarget::Source,
        op: ModifierOp::AddStacks,
        percent: 1,
        spec_priority: SPEC_PRIORITY_ADD,
    },
    // 虚弱：DamageDealt / ScalePercent / 75 / Priority 200（`:280-283`）
    DamageModifierEntry {
        status_id: "standard.weak",
        stage: ModifierTarget::Source,
        op: ModifierOp::MulPercent,
        percent: 75,
        spec_priority: SPEC_PRIORITY_SCALE,
    },
    // 易伤：**DamageReceived** / ScalePercent / 150 / Priority 300（`:339-342`）→ Target 阶段
    DamageModifierEntry {
        status_id: "standard.vulnerable",
        stage: ModifierTarget::Target,
        op: ModifierOp::MulPercent,
        percent: 150,
        spec_priority: SPEC_PRIORITY_VULNERABLE,
    },
];

/// 参与**伤害**计算的全部条目，**已按 `(stage, spec_priority)` 排好序** —— 调用方直接顺序扫。
///
/// S2 的用法（`DamageEffects.cs:305-317`）：外层按 `Source → Target` 走阶段，内层顺序扫本表，
/// 跳过不属于当前阶段的行，对命中的行做 `v = max(0, op(v))`；本表已保证**每阶段是一段连续区间**
/// （见 [`damage_modifiers_in_stage`]）。
///
/// 调用方**必须**先过 [`DAMAGE_MODIFIER_DAMAGE_KINDS`] 这道门：`Kind != Direct` 时整表不参与。
///
/// 两条折叠细则（都是 O13/O14，缺了就会算错）：
/// * 行里的层数是**该状态定义全部实例层数之和**（`PassiveModifiers.cs:142-148`：先按定义 id 分组、
///   `Sum(Stacks)`，再乘一次）—— 不是某一个实例的层数。
/// * 唯一早退是 `amount <= 0`（`:137-138`）；每步之后 `max(0, ·)`（`:216`）。负数永远不会出现。
#[must_use]
pub fn damage_modifiers() -> &'static [DamageModifierEntry] {
    &DAMAGE_MODIFIERS
}

/// 某个阶段的那一段（表已排序 ⇒ 每阶段是连续区间）。没有行时返回空切片。
#[must_use]
pub fn damage_modifiers_in_stage(stage: ModifierTarget) -> &'static [DamageModifierEntry] {
    let all = damage_modifiers();
    let rank = stage_rank(stage);
    let mut start = 0;
    while start < all.len() && stage_rank(all[start].stage) != rank {
        start += 1;
    }
    let mut end = start;
    while end < all.len() && stage_rank(all[end].stage) == rank {
        end += 1;
    }
    &all[start..end]
}

// ---------------------------------------------------------------------------------------------
// 格挡修饰表（`DefensivePoolEffects.cs` 的 GainBlock 单阶段折叠，无 stage）
// ---------------------------------------------------------------------------------------------

/// 两行格挡修饰，按 `spec_priority` 排好：100 敏捷（加法）→ 200 脆弱（乘 75）。
const BLOCK_MODIFIERS: [BlockModifierEntry; 2] = [
    // 敏捷：BlockGain / AddPerStack / Magnitude 1 / Priority 100（`StandardCombatPackage.cs:360-363`）
    BlockModifierEntry {
        status_id: "standard.dexterity",
        op: ModifierOp::AddStacks,
        percent: 1,
        spec_priority: SPEC_PRIORITY_ADD,
    },
    // 脆弱：BlockGain / ScalePercent / 75 / Priority 200（`:318-321`）
    BlockModifierEntry {
        status_id: "standard.frail",
        op: ModifierOp::MulPercent,
        percent: 75,
        spec_priority: SPEC_PRIORITY_SCALE,
    },
];

/// 参与**格挡**计算的条目，同样排好序。
///
/// GainBlock 管线**没有 stage**（`M:§3.2`），所以只有一条优先级轴。种类门对格挡不适用：
/// 折叠器给格挡传的是 `damageKind: null`（`PassiveModifiers.cs:267`），`:155` 的门因此整段跳过。
#[must_use]
pub fn block_modifiers() -> &'static [BlockModifierEntry] {
    &BLOCK_MODIFIERS
}

// ---------------------------------------------------------------------------------------------
// 状态元数据表
// ---------------------------------------------------------------------------------------------

/// 状态极性（`CombatPrimitives.cs:42-47`：`Buff=0, Debuff=1, Neutral=2`）。
///
/// **故意是本模块的局部镜像**（不是 `crate::state::StatusPolarity`）：本模块的契约是"纯数据 + 纯谓词，
/// 不依赖状态模型，可以独立开发与验收"，运行期代码里不出现 `state.rs` 的路径。两者必须一致，
/// 所以测试里有一条把这份镜像与 `state.rs` 的枚举逐个判别值对上的断言（哈希写的 `pol=<int>` 就是它）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum StatusPolarity {
    Buff = 0,
    Debuff = 1,
    Neutral = 2,
}

/// 状态用哪几根轴（`StatusDefinition.UsesStacks/UsesDuration/UsesCharges`，`StatusDefinition.cs:16-18`）。
///
/// 三轴独立、合并规则不同：层数 `+=`、时长 `max`、充能 `+=`（`StatusEffects.cs:135-139`，O25）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StatusAxes {
    pub stacks: bool,
    pub duration: bool,
    pub charges: bool,
}

impl StatusAxes {
    /// 一根轴都不用（纯标记状态，如 `standard.action_fails`）。
    pub const NONE: Self = Self {
        stacks: false,
        duration: false,
        charges: false,
    };
    pub const STACKS: Self = Self {
        stacks: true,
        duration: false,
        charges: false,
    };
    pub const DURATION: Self = Self {
        stacks: false,
        duration: true,
        charges: false,
    };
    pub const CHARGES: Self = Self {
        stacks: false,
        duration: false,
        charges: true,
    };
    pub const STACKS_AND_DURATION: Self = Self {
        stacks: true,
        duration: true,
        charges: false,
    };
}

// 标签位。**位号是内核自定的**（内容二进制里标签仍是字符串，见 `docs/spec/content-binary-spec`的 STR 池）：
// 用位掩码是因为嵌入式侧要拿它做"扫状态实例找 DoT / 找反伤"这种每回合都跑的热路径判断。
// 有运行期读取者的四个位注明了出处；其余是作者/内容侧的词汇（引擎不读，但注册表与内容编译器要用同一套拼写）。

/// `damage_over_time`：回合开始给它入队一跳（`StatusEffects.cs:462,498`）。
pub const TAG_DAMAGE_OVER_TIME: u16 = 1 << 0;
/// `triggered_damage`：被打到时给攻击者入队反伤（`StatusEffects.cs:537`，荆棘）。
pub const TAG_TRIGGERED_DAMAGE: u16 = 1 << 1;
/// `retain_hand`：拥有者回合结束**不弃手牌**（`CardTurnLifecycleEventHandlers.cs:49`）。
pub const TAG_RETAIN_HAND: u16 = 1 << 2;
/// `retain_block`：拥有者回合开始**不清防御池**（`DefensivePoolEffects.cs:297`）。
pub const TAG_RETAIN_BLOCK: u16 = 1 << 3;
/// `status_application_interceptor`：内容侧扫描"哪些状态参与施加拦截"。
pub const TAG_STATUS_APPLICATION_INTERCEPTOR: u16 = 1 << 4;
/// `damage_modifier`：这个状态的数值作用在伤害管线上（作者标记）。
pub const TAG_DAMAGE_MODIFIER: u16 = 1 << 5;
/// `block_modifier`：作用在格挡管线上（作者标记）。
pub const TAG_BLOCK_MODIFIER: u16 = 1 << 6;
/// `cost_modifier`：作用在卡费管线上（作者标记）。
pub const TAG_COST_MODIFIER: u16 = 1 << 7;
/// `control`：控制类（眩晕等）。
pub const TAG_CONTROL: u16 = 1 << 8;
/// `play_limit`：限制出牌（每回合一次攻击等）。
pub const TAG_PLAY_LIMIT: u16 = 1 << 9;
/// `combo`：连段（每 N 张技能抽牌）。
pub const TAG_COMBO: u16 = 1 << 10;
/// `card_played_trigger`：出牌触发（怒气）。
pub const TAG_CARD_PLAYED_TRIGGER: u16 = 1 << 11;

/// 标签位 ↔ 参考实现里的标签字符串（`StandardCombatIds.cs:41-67`）。
/// `buff`/`debuff` 不占位：那是**极性**的事（[`StatusMeta::polarity`]），不是位。
pub const TAG_BITS: [(&str, u16); 12] = [
    ("damage_over_time", TAG_DAMAGE_OVER_TIME),
    ("triggered_damage", TAG_TRIGGERED_DAMAGE),
    ("retain_hand", TAG_RETAIN_HAND),
    ("retain_block", TAG_RETAIN_BLOCK),
    ("status_application_interceptor", TAG_STATUS_APPLICATION_INTERCEPTOR),
    ("damage_modifier", TAG_DAMAGE_MODIFIER),
    ("block_modifier", TAG_BLOCK_MODIFIER),
    ("cost_modifier", TAG_COST_MODIFIER),
    ("control", TAG_CONTROL),
    ("play_limit", TAG_PLAY_LIMIT),
    ("combo", TAG_COMBO),
    ("card_played_trigger", TAG_CARD_PLAYED_TRIGGER),
];

/// 把内容里的标签字符串翻成位。未知标签返回 `None`（内容侧的扩展标签不进内核的词汇表）。
#[must_use]
pub fn tag_bit(name: &str) -> Option<u16> {
    let mut index = 0;
    while index < TAG_BITS.len() {
        let (candidate, bit) = TAG_BITS[index];
        if candidate.as_bytes() == name.as_bytes() {
            return Some(bit);
        }
        index += 1;
    }
    None
}

/// 一个状态定义的元数据。
///
/// 为什么带这些字段（下游缺了它们就得出错数，且**不能靠特判 id** 补回来）：
/// * `polarity` —— 状态施加拦截器要问"这是不是负面"：Artifact 用 1 充能吃掉一次 **Debuff** 施加
///   （`StatusApplicationInterceptors.cs:64-100`），禁止令的 `UnwantedByBearer` 在玩家队拒 Debuff、
///   在敌方队拒 Buff（`StatusDefinition.cs:145-150`），`RemoveStatusesByPolarity` 按极性成批移除。
///   没有这一列，拦截器就只能硬编码 id 名单。
/// * `axes` —— 施加时的合并规则按轴走（层数 `+=`、时长 `max`、充能 `+=`），到 0 才移除实例。
/// * `decays_at_owner_turn_end` —— 回合结束的**减时长**遍历（见 [`decays_at_owner_turn_end`]）。
/// * `tags` —— 回合自动化按标签找状态（DoT 跳、反伤、保留手牌/格挡），见上面各 `TAG_*`。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct StatusMeta {
    pub id: &'static str,
    pub polarity: StatusPolarity,
    pub axes: StatusAxes,
    /// 拥有者回合结束时减 1（**标准包里恒等于 `axes.duration`** —— `StatusEffects.cs:394` 的
    /// `if (!definition.UsesDuration) continue;`；测试里对 16 行逐行钉住这条不变量）。
    pub decays_at_owner_turn_end: bool,
    /// 标签位掩码，位见 [`TAG_BITS`]。
    pub tags: u16,
}

impl StatusMeta {
    #[must_use]
    pub const fn has_tag(&self, tag: u16) -> bool {
        self.tags & tag != 0
    }

    #[must_use]
    pub const fn is_debuff(&self) -> bool {
        matches!(self.polarity, StatusPolarity::Debuff)
    }

    #[must_use]
    pub const fn is_buff(&self) -> bool {
        matches!(self.polarity, StatusPolarity::Buff)
    }

    #[must_use]
    pub const fn is_neutral(&self) -> bool {
        matches!(self.polarity, StatusPolarity::Neutral)
    }
}

/// 标准包 **16** 个状态定义（`StandardCombatPackage.cs:26-43`），**按 id 的 ASCII 字节序**。
///
/// 注册序（`RegisterStatus` 的调用序 = intern 发号器最自然会给出的数字序）见
/// [`STANDARD_STATUS_REGISTRATION_ORDER`] —— **两者不同**，这正是 SEMANTICS §3 D9 要防的坑。
///
/// 标准包 16 个状态的 `StackingBehavior` **全部**是 `MergeWithExistingInstance`；内容侧可以有
/// `CreateSeparateInstance`（引擎默认值），那属于内容表，不在本表里重复一遍。
const STANDARD_STATUSES: [StatusMeta; 16] = [
    StatusMeta {
        id: "standard.action_fails",
        polarity: StatusPolarity::Neutral,
        axes: StatusAxes::NONE,
        decays_at_owner_turn_end: false,
        tags: 0,
    },
    StatusMeta {
        id: "standard.artifact",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::CHARGES,
        decays_at_owner_turn_end: false,
        tags: TAG_STATUS_APPLICATION_INTERCEPTOR,
    },
    StatusMeta {
        id: "standard.dexterity",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: false,
        tags: TAG_BLOCK_MODIFIER,
    },
    StatusMeta {
        id: "standard.first_attack_each_turn_free",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::DURATION,
        decays_at_owner_turn_end: true,
        tags: TAG_COST_MODIFIER,
    },
    StatusMeta {
        id: "standard.frail",
        polarity: StatusPolarity::Debuff,
        axes: StatusAxes::DURATION,
        decays_at_owner_turn_end: true,
        tags: TAG_BLOCK_MODIFIER,
    },
    StatusMeta {
        id: "standard.free_next_card",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::CHARGES,
        decays_at_owner_turn_end: false,
        tags: TAG_COST_MODIFIER,
    },
    StatusMeta {
        id: "standard.one_attack_per_turn",
        polarity: StatusPolarity::Debuff,
        axes: StatusAxes::DURATION,
        decays_at_owner_turn_end: true,
        tags: TAG_CONTROL | TAG_PLAY_LIMIT,
    },
    StatusMeta {
        id: "standard.poison",
        polarity: StatusPolarity::Debuff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: false,
        tags: TAG_DAMAGE_OVER_TIME,
    },
    StatusMeta {
        id: "standard.rage",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: false,
        tags: TAG_CARD_PLAYED_TRIGGER,
    },
    StatusMeta {
        id: "standard.skill_combo_draw",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: false,
        tags: TAG_COMBO,
    },
    StatusMeta {
        id: "standard.skill_cost_reduction",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::STACKS_AND_DURATION,
        decays_at_owner_turn_end: true,
        tags: TAG_COST_MODIFIER,
    },
    StatusMeta {
        id: "standard.strength",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: false,
        tags: TAG_DAMAGE_MODIFIER,
    },
    StatusMeta {
        id: "standard.stun",
        polarity: StatusPolarity::Debuff,
        axes: StatusAxes::DURATION,
        decays_at_owner_turn_end: true,
        tags: TAG_CONTROL,
    },
    StatusMeta {
        id: "standard.thorns",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: false,
        tags: TAG_TRIGGERED_DAMAGE,
    },
    StatusMeta {
        id: "standard.vulnerable",
        polarity: StatusPolarity::Debuff,
        axes: StatusAxes::DURATION,
        decays_at_owner_turn_end: true,
        tags: TAG_DAMAGE_MODIFIER,
    },
    StatusMeta {
        id: "standard.weak",
        polarity: StatusPolarity::Debuff,
        axes: StatusAxes::DURATION,
        decays_at_owner_turn_end: true,
        tags: TAG_DAMAGE_MODIFIER,
    },
];

/// 16 个标准状态 id，按 ASCII 字节序 —— 与 [`STANDARD_STATUSES`] 同序（测试逐项对拍）。
const STANDARD_STATUS_IDS: [&str; 16] = [
    "standard.action_fails",
    "standard.artifact",
    "standard.dexterity",
    "standard.first_attack_each_turn_free",
    "standard.frail",
    "standard.free_next_card",
    "standard.one_attack_per_turn",
    "standard.poison",
    "standard.rage",
    "standard.skill_combo_draw",
    "standard.skill_cost_reduction",
    "standard.strength",
    "standard.stun",
    "standard.thorns",
    "standard.vulnerable",
    "standard.weak",
];

/// **注册序** = `StandardCombatPackage.cs:26-43` 里 `RegisterStatus(...)` 的调用序。
///
/// 这是 D9 的反例：一个按注册序发号的 intern 表会把数字序当成注册序，而 `(Priority, Id)` 的次级键
/// 是**字符串序**。两者在本表上确实不同（`standard.poison` 排头 vs `standard.action_fails` 排头），
/// [`sorting_key_is_byte_order`] 就用它当负例。
pub const STANDARD_STATUS_REGISTRATION_ORDER: [&str; 16] = [
    "standard.poison",
    "standard.weak",
    "standard.vulnerable",
    "standard.frail",
    "standard.artifact",
    "standard.strength",
    "standard.rage",
    "standard.dexterity",
    "standard.thorns",
    "standard.stun",
    "standard.action_fails",
    "standard.one_attack_per_turn",
    "standard.free_next_card",
    "standard.first_attack_each_turn_free",
    "standard.skill_combo_draw",
    "standard.skill_cost_reduction",
];

/// Python 原型（`sts/content/statuses.json`，plan B，已放弃）里的 8 个状态，按 id 字节序。
///
/// 为什么要收进来：冻结谓词 [`decays_at_owner_turn_end`] 对**金属化 / 仪式**也必须给真值，
/// 而这两个 id **既不在参考实现的标准包里，也不在样例内容里**（样例内容 23 个状态里没有它们）；
/// 它们只存在于原型的 `statuses.json`，那里有显式的 `decay` 标记。与其靠"未知 ⇒ false"蒙对，
/// 不如把这份**真实出处**列出来。
///
/// 注意两者的轴不同：参考实现的时钟是 `DurationTurns`，原型的时钟**就是层数**
/// （`sts/rules.py:138-146`：回合结束给 `decay` 的状态减 1 层）。所以这几行的 `axes` 记它的真实轴
/// （层数），`decays_at_owner_turn_end` 单独按 `statuses.json` 记 —— 冻结谓词问的是"回合结束减 1 吗"，
/// 与"减的是哪根轴"无关。
const STS_PROTOTYPE_STATUSES: [StatusMeta; 8] = [
    StatusMeta {
        id: "dexterity",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: false,
        tags: 0,
    },
    StatusMeta {
        id: "frail",
        polarity: StatusPolarity::Debuff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: true,
        tags: 0,
    },
    StatusMeta {
        id: "metallicize",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: false,
        tags: 0,
    },
    StatusMeta {
        id: "ritual",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: false,
        tags: 0,
    },
    StatusMeta {
        id: "strength",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: false,
        tags: 0,
    },
    StatusMeta {
        id: "thorns",
        polarity: StatusPolarity::Buff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: false,
        tags: 0,
    },
    StatusMeta {
        id: "vulnerable",
        polarity: StatusPolarity::Debuff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: true,
        tags: 0,
    },
    StatusMeta {
        id: "weak",
        polarity: StatusPolarity::Debuff,
        axes: StatusAxes::STACKS,
        decays_at_owner_turn_end: true,
        tags: 0,
    },
];

/// 标准包 16 个状态的元数据，按 id 字节序。
#[must_use]
pub fn standard_status_meta() -> &'static [StatusMeta] {
    &STANDARD_STATUSES
}

/// 原型命名空间（`sts/content/statuses.json`）的 8 个状态元数据，按 id 字节序。
#[must_use]
pub fn sts_prototype_status_meta() -> &'static [StatusMeta] {
    &STS_PROTOTYPE_STATUSES
}

/// 按 id 查元数据（先查标准包，再查原型命名空间）。表已排序 ⇒ 二分。未知 id 返回 `None`。
#[must_use]
pub fn status_meta(status_id: &str) -> Option<&'static StatusMeta> {
    lookup(&STANDARD_STATUSES, status_id).or_else(|| lookup(&STS_PROTOTYPE_STATUSES, status_id))
}

/// The statuses the **kernel actually executes**: each one has an arm somewhere in `host.rs` or
/// `exec.rs` that reads it. Everything else in [`StatusMeta`]-land is a *name*.
///
/// **Why this list exists.** A status can exist in three places at once -- the catalogue (name and
/// polarity), the content's `STAT` table, and the code that acts on it -- and the first two are
/// happy to describe a status nothing implements. That is the worst shape a gap can take: it looks
/// finished. `status_catalogue_is_honest` (in `content.rs`) refuses an image whose statuses are
/// neither implemented nor **declared inert**, so "silently does nothing" cannot happen again.
#[must_use]
pub fn has_behaviour(status_id: &str) -> bool {
    matches!(
        status_id,
        "standard.strength"
            | "standard.dexterity"
            | "standard.vulnerable"
            | "standard.weak"
            | "standard.frail"
            | "standard.poison"
            | "standard.stun"
            | "standard.artifact"
            // A **host step**, not a modifier: `Host::grant_end_of_turn_block` (see
            // `try_run_turn_ended_triggers`). Ported from the wiki's Lagavulin.
            | "standard.metallicize"
            // Ritual: a `TurnEnded` trigger in the CONTENT (wiki: Cultist 3).
            | "ritual"
            // Thorns: a `DamageTaken` trigger in the CONTENT; the hook is
            // `Host::run_damage_taken_triggers` (§116).
            | "standard.thorns"
            // The three that arrived with the Downed / artifact / CardPlayed hooks (§117).
            | "standard.spore_cloud"
            | "standard.enrage"
            // Content triggers on hooks that already existed (port-plan.md §119).
            | "standard.regen"
            | "standard.rage"
            | "standard.flame_barrier"
            | "standard.combust"
            // Boss split: a Downed trigger that spawns two (§121).
            | "standard.split"
            // Boss phase (half HP / low HP split, §122).
            | "standard.phase_split"
            // Time Warp: a CardPlayed trigger that ends the turn (§125).
            | "standard.time_warp"
            // Constricted: a `TurnEnded` trigger that deals its own stacks, **ignoring Block**
            // (§147). Content-side like the rest of this list -- the kernel only has to *run*
            // turn-ended triggers, which it already does.
            | "standard.constricted"
            // §149: the three that live **inside the damage pipeline** (`exec::resolve_damage_of_kind`).
            // Intangible caps incoming damage at 1, Buffer eats the next HP loss, Plated Armor loses a
            // stack on unblocked damage (its block half shares the Metallicize step).
            | "standard.intangible"
            | "standard.buffer"
            | "standard.plated_armor"
            // §158: the "give it back at the end of the turn" half of Flex Potion and Speed
            // Potion. Content-side like `standard.constricted`: a `TurnEnded` trigger that
            // subtracts its own stacks from Strength / Dexterity and then removes itself. The
            // kernel needs no new rule -- it already runs turn-ended triggers.
            | "standard.lose_strength"
            | "standard.lose_dexterity"
            // §178: Nemesis's "intangible every other turn" carrier -- the first content status
            // whose trigger is `TurnStarted`. It was in the §175 patch and was reverted with it.
            | "standard.phantom_veil"
            // §180: its whole rule is `DeathPrevention`, read in `exec::resolve_damage_of_kind`.
            // This is the **point** of `the_status_catalogue_is_honest`: a status with no trigger
            // and no modifier would otherwise look inert, and "inert" is exactly what it is not.
            | "standard.fairy_in_a_bottle"
            // §181: read in play.rs when a card program is about to start (played twice).
            | "standard.duplication"
    )
}

/// Statuses that are **knowingly inert**: present in the content, read by the kernel for its
/// display and its hash, but with no rule attached yet. Each one needs a reason, and the reason
/// lives next to the plan (`port-plan.md` §104).
#[must_use]
pub fn is_declared_inert(status_id: &str) -> bool {
    matches!(
        status_id,
        // Nothing yet: every status in the content has a rule now. The list stays because the rule
        // needs somewhere to put the next one -- and because "empty" must be *sayable*.
        "" |
        // §194: the Guardian's Sharp Hide and the Awakened One's Curiosity. Both are entirely a
        // **content** `CardPlayed` trigger filtered by a card tag (`card.hasTag.attack` /
        // `card.hasTag.power`), the same shape as `standard.enrage` -- so the kernel has no rule to
        // write and must not pretend it does. Declared here so `the_status_catalogue_is_honest`
        // keeps meaning what it says: every status is either implemented or on this list.
        "standard.sharp_hide" |
        "standard.curiosity" |
        // §195.1: The Guardian's Mode Shift -- also entirely a content trigger (`DamageTaken` ->
        // add `eventAmount` to a counter). The *threshold* lives in an intent rule
        // (`compare{counter >= 30 + 10 * shifts}`), not in the kernel.
        "standard.mode_shift" |
        // §195.2: Awakened One's phase-one guard. It has **no trigger**: the whole effect is its
        // `DeathPrevention` row, which `resolve_damage` reads for any combatant (§180). Declared here
        // because "the kernel has a rule for it" is exactly what this list is for -- and the rule is
        // a *row of data*, not code.
        "standard.unawakened" |
        // §195.4: Bronze Orb's Stasis. `standard.stasis` is a `Downed` trigger (return the stolen
        // card); `standard.stasis_ready` is a plain flag the move spends ("once per combat"). Neither
        // has a kernel rule -- the whole behaviour is the content's trigger plus `node.selectCards`,
        // which is a *node*, not a status rule.
        "standard.stasis" |
        "standard.stasis_ready" |
        // §198: Slow -- a `DamageReceived` row using the stack-linear scale, plus a `CardPlayed`
        // trigger. Like Draw Reduction, the kernel rule is the **content row** (the fold already
        // exists); `has_behaviour` only knows the hardcoded catalogue, so it goes on this list.
        "standard.slow" |
        // §197: Barricade / Blur -- both are "block is not cleared", declared by the **tag**
        // `retain_block` / `retain_block_once` that `Host::block_is_retained` already reads. No
        // trigger, no modifier: the rule is the tag, so `has_behaviour` cannot see it.
        "standard.barricade" |
        "standard.blur" |
        // §196: Entangled -- no trigger and no modifier: the whole rule is the kernel's play
        // validator (`play::Validator::Entangled`), which `has_behaviour` does not know about.
        // `standard.entangle_ready` is the once-per-combat flag Red Slaver spends.
        "standard.entangled" |
        "standard.entangle_ready" |
        // §195.7: Draw Reduction -- a `TurnStartDraw` passive row plus its own `TurnEnded` decay.
        // `has_behaviour` only knows the damage/block pipelines, so the reader-side rule lives in the
        // content's `PassiveModifiers`; the kernel rule that matters (`fold_turn_start_draw`) already
        // exists (§195.5's `Pipeline::TurnStartDraw`).
        "standard.draw_reduction"
    )
}

fn lookup(table: &'static [StatusMeta], status_id: &str) -> Option<&'static StatusMeta> {
    table
        .binary_search_by(|entry| entry.id.cmp(status_id))
        .ok()
        .map(|index| &table[index])
}

/// 该状态是否在**其拥有者的回合结束时**减 1 层（易伤/虚弱/脆弱为真；力量/敏捷/荆棘等为假）。
///
/// 参考实现的判据是**定义的 `UsesDuration` 标记**，不是 id 名单：
/// `DecreaseTimedStatusDurationsOnTurnEndedHandler` 遍历拥有者的全部状态，
/// `if (!definition.UsesDuration) continue;`（`StatusEffects.cs:390-404`）。
/// 标准包里满足它的有 **7 个**（弱/易伤/脆弱/眩晕/每回合一次攻击/每回合首次攻击免费/技能减费）——
/// 不是"只有易伤虚弱脆弱"三个。`standard.poison` **不衰减**（它只有层数轴，回合开始按层数跳一次，
/// 层数不掉），这与《杀戮尖塔》的毒不同，别照 StS 直觉写。
///
/// 未知 id 一律 `false`：内核不为内容侧的状态猜时钟 —— 内容的 `UsesDuration` 是**内容自己声明的**
/// 字段（内容二进制里就有 `UsesDuration` 列），到表里来查是查不到的。
/// （旁证：在参考实现里"猜错方向"的代价是不对称的 —— 回合结束的减时长循环会跳过
/// `DurationTurns <= 0` 的实例（`:397-398`），所以对"其实没有时长轴"的状态多减一次是无害的；
/// 反过来漏减则会让限时状态变成永久。内容侧落地时**必须**把它的 `UsesDuration` 喂进来。）
#[must_use]
pub fn decays_at_owner_turn_end(status_id: &str) -> bool {
    status_meta(status_id).is_some_and(|meta| meta.decays_at_owner_turn_end)
}

/// 标准包里全部状态的 id，**按 ASCII 字节序**。
/// 顺序必须稳定：`(Priority, Id)` 是触发器的次级排序键，而它是**字符串序**而不是 intern 后的数字序
/// （规格书 §3 D9 —— 数字序 ≠ 字符串序会静默改变触发次序）。
#[must_use]
pub fn standard_status_ids_sorted() -> &'static [&'static str] {
    &STANDARD_STATUS_IDS
}

/// 一串 id 是否**严格**按 ASCII 字节序递增（D9 的通用判据，别的排序点也能用）。
#[must_use]
pub fn ids_are_byte_sorted(ids: &[&str]) -> bool {
    ids.windows(2)
        .all(|pair| pair[0].as_bytes() < pair[1].as_bytes())
}

/// D9 的自证：`standard_status_ids_sorted()` 的次序**确实是 ASCII 字节序**，
/// 而且**不是**注册序（一个按注册序发号的 intern 表给出的数字序）。
///
/// 把这条偏离固化成可执行断言，而不是注释：只要有谁"顺手"把表按注册序摆回去、或按
/// `u16` 句柄排一遍，这个函数（以及它的测试）立刻变 `false`。
#[must_use]
pub fn sorting_key_is_byte_order() -> bool {
    let ids = standard_status_ids_sorted();
    ids_are_byte_sorted(ids) && ids != &STANDARD_STATUS_REGISTRATION_ORDER[..]
}

#[cfg(test)]
mod tests {
    use super::*;

    // ---- 用表复算数值（这就是调用方要写的那几行：顺序扫 + 整数运算） ----

    /// S2 的折叠：外层阶段序、内层顺序扫表，每步 `max(0, ·)`。
    fn fold_damage(base: i32, strength: i32, weak: bool, vulnerable: bool) -> i32 {
        let mut current = base;
        for stage in [ModifierTarget::Source, ModifierTarget::Target] {
            for entry in damage_modifiers_in_stage(stage) {
                let stacks = match entry.status_id {
                    "standard.strength" => strength,
                    "standard.weak" => i32::from(weak as u8),
                    "standard.vulnerable" => i32::from(vulnerable as u8),
                    other => panic!("unexpected damage modifier row: {other}"),
                };
                if stacks == 0 {
                    continue;
                }
                current = apply(entry.op, current, entry.percent, stacks).max(0);
            }
        }
        current
    }

    fn fold_block(base: i32, dexterity: i32, frail: bool) -> i32 {
        let mut current = base;
        for entry in block_modifiers() {
            let stacks = match entry.status_id {
                "standard.dexterity" => dexterity,
                "standard.frail" => i32::from(frail as u8),
                other => panic!("unexpected block modifier row: {other}"),
            };
            if stacks == 0 {
                continue;
            }
            current = apply(entry.op, current, entry.percent, stacks).max(0);
        }
        current
    }

    /// `PassiveModifiers.cs:206-213`：`AddPerStack = cur + mag*stacks`、`ScalePercent = cur*mag/100`。
    /// 除法对非负数是向下取整（`Cur*Mag` 恒非负 ⇒ 与 `:210` 的 C# 整数除法同号同向）。
    fn apply(op: ModifierOp, current: i32, magnitude: i32, stacks: i32) -> i32 {
        match op {
            ModifierOp::AddStacks => current + magnitude * stacks,
            ModifierOp::MulPercent => current * magnitude / 100,
        }
    }

    // ---- 表的形状与次序 ----

    #[test]
    fn damage_table_rows_are_the_frozen_shape() {
        let rows = damage_modifiers();
        assert_eq!(rows.len(), 3);
        assert_eq!(
            rows[0],
            DamageModifierEntry {
                status_id: "standard.strength",
                stage: ModifierTarget::Source,
                op: ModifierOp::AddStacks,
                percent: 1,
                spec_priority: 100,
            }
        );
        assert_eq!(
            rows[1],
            DamageModifierEntry {
                status_id: "standard.weak",
                stage: ModifierTarget::Source,
                op: ModifierOp::MulPercent,
                percent: 75,
                spec_priority: 200,
            }
        );
        assert_eq!(
            rows[2],
            DamageModifierEntry {
                status_id: "standard.vulnerable",
                stage: ModifierTarget::Target,
                op: ModifierOp::MulPercent,
                percent: 150,
                spec_priority: 300,
            }
        );

        let blocks = block_modifiers();
        assert_eq!(blocks.len(), 2);
        assert_eq!(
            blocks[0],
            BlockModifierEntry {
                status_id: "standard.dexterity",
                op: ModifierOp::AddStacks,
                percent: 1,
                spec_priority: 100,
            }
        );
        assert_eq!(
            blocks[1],
            BlockModifierEntry {
                status_id: "standard.frail",
                op: ModifierOp::MulPercent,
                percent: 75,
                spec_priority: 200,
            }
        );
    }

    #[test]
    fn tables_are_sorted_by_stage_then_spec_priority() {
        // O11 + O12：阶段是硬编码的外层序，阶段内按 spec.Priority 升序。
        let rows = damage_modifiers();
        for pair in rows.windows(2) {
            let (a, b) = (pair[0], pair[1]);
            assert!(
                stage_rank(a.stage) <= stage_rank(b.stage),
                "{} must not run before {}",
                b.status_id,
                a.status_id
            );
            if a.stage == b.stage {
                assert!(
                    a.spec_priority < b.spec_priority,
                    "within one stage the fold is by spec.Priority: {} then {}",
                    a.status_id,
                    b.status_id
                );
            }
        }

        let blocks = block_modifiers();
        for pair in blocks.windows(2) {
            assert!(pair[0].spec_priority < pair[1].spec_priority);
        }

        // 加法（100）必须先于乘法（200/300）—— 表里就是这么摆的。
        //
        // ⚠️ 这里**不写 `assert!(CONST_A < CONST_B)`**：那是常量之间的断言，clippy 报
        // `assertions_on_constants`，而且更根本的问题是**它证明不了表按它们排的** ——
        // 两个常量谁大谁小与表里行的顺序毫无关系。下面从**表里取真实的行**来比。
        let rows = damage_modifiers();
        let first_add = rows.iter().find(|r| r.op == ModifierOp::AddStacks);
        let first_scale = rows.iter().find(|r| r.op == ModifierOp::MulPercent);
        let (Some(add), Some(scale)) = (first_add, first_scale) else {
            panic!("伤害表里必须有加法行与乘法行各至少一条");
        };
        assert!(
            add.spec_priority < scale.spec_priority,
            "加法行（{}）必须排在乘法行（{}）之前",
            add.spec_priority,
            scale.spec_priority
        );
        assert_eq!(add.spec_priority, SPEC_PRIORITY_ADD);
        assert_eq!(scale.spec_priority, SPEC_PRIORITY_SCALE);
        // 易伤是**目标侧**的乘法，它的优先级最高。
        let vuln = rows.iter().find(|r| r.status_id == "standard.vulnerable");
        assert_eq!(vuln.map(|r| r.spec_priority), Some(SPEC_PRIORITY_VULNERABLE));
        assert!(SPEC_PRIORITY_VULNERABLE > scale.spec_priority);
        // 而"修饰器对象"的优先级是另一条轴，不与 spec 优先级混排。
        assert_eq!(DAMAGE_MODIFIER_OBJECT_PRIORITY, 1000);
    }

    #[test]
    fn stage_slices_are_contiguous_and_cover_the_table() {
        let source = damage_modifiers_in_stage(ModifierTarget::Source);
        let target = damage_modifiers_in_stage(ModifierTarget::Target);
        assert_eq!(source.len() + target.len(), damage_modifiers().len());
        assert_eq!(source.len(), 2);
        assert_eq!(target.len(), 1);
        assert!(source.iter().all(|row| row.stage == ModifierTarget::Source));
        assert!(target.iter().all(|row| row.stage == ModifierTarget::Target));
        assert_eq!(source[0].status_id, "standard.strength");
        assert_eq!(source[1].status_id, "standard.weak");
        assert_eq!(target[0].status_id, "standard.vulnerable");
        // 两个区段合起来就是整张表（顺序一致）。
        assert_eq!(&damage_modifiers()[..2], source);
        assert_eq!(&damage_modifiers()[2..], target);
    }

    #[test]
    fn tables_are_static_data_not_rebuilt_per_call() {
        // 「用 const 数组，不要每次构造」：同一个地址 + 同一段长度。
        assert!(core::ptr::eq(damage_modifiers(), damage_modifiers()));
        assert!(core::ptr::eq(block_modifiers(), block_modifiers()));
        assert!(core::ptr::eq(
            standard_status_ids_sorted(),
            standard_status_ids_sorted()
        ));
        assert!(core::ptr::eq(
            standard_status_meta(),
            standard_status_meta()
        ));
    }

    // ---- 验收向量（modifier-pipeline.md §7） ----

    #[test]
    fn strength_plus_vulnerable_is_ten_and_the_wrong_order_is_nine() {
        // 向量 1（`ModifierPipelineTests.cs:102-122`）：双方 HP 100，英雄力量 2，哥布林易伤，
        // DealDamage(5, Direct)。正确次序逐步复算：
        //   Source/100 力量：5 + 1*2            = 7
        //   Target/300 易伤：7 * 150 / 100 = 1050/100 = 10
        let correct = fold_damage(5, 2, false, true);
        assert_eq!(correct, 10);
        assert_eq!(100 - correct, 90); // 哥布林 HP 100 -> 90

        // 错序（把易伤当成 Source 阶段的乘法、抢在力量之前）会得到 9，而不是 10：
        //   5 * 150 / 100 = 750/100 = 7   （先乘；注意整数截断把 7.5 砍成 7）
        //   7 + 1*2                       = 9
        let wrong = apply(
            ModifierOp::AddStacks,
            apply(ModifierOp::MulPercent, 5, 150, 1),
            1,
            2,
        );
        assert_eq!(wrong, 9);
        assert_ne!(correct, wrong, "stage order decides this number");
        // 出处里写的注释就是这个 9（HP 100 -> 91），它是本模块的规格。
    }

    #[test]
    fn six_plus_strength_two_weak_and_vulnerable_leaves_three_hp() {
        // 向量 3 / 6（`DamageAmountModifierTests.cs:37-62,91-124`；`VulnerableStatusTests.cs:133-170`）:
        // 哥布林 HP 12，英雄力量 2，DealDamage(6, Direct)。
        //   6 + 1*2                          = 8
        assert_eq!(fold_damage(6, 2, false, false), 8);
        assert_eq!(12 - 8, 4); // 只有力量的变体：HP 4

        // 再加虚弱：
        //   8 * 75 / 100  = 600/100          = 6
        assert_eq!(fold_damage(6, 2, true, false), 6);
        assert_eq!(12 - 6, 6); // +虚弱的变体：HP 6

        // 三件套（虚弱 + 易伤）：
        //   8 * 75 / 100  = 600/100          = 6
        //   6 * 150 / 100 = 900/100          = 9
        //   12 - 9                           = 3
        assert_eq!(fold_damage(6, 2, true, true), 9);
        assert_eq!(12 - 9, 3); // 向量 6：HP 3
    }

    #[test]
    fn addition_must_precede_multiplication_or_the_number_changes() {
        // 规格书 §4.2 #2 第二例：base 7、力量 3、虚弱、易伤。
        // 正确（加法先）：7 + 3 = 10 -> 10*75/100 = 750/100 = 7 -> 7*150/100 = 1050/100 = 10
        let correct = fold_damage(7, 3, true, true);
        assert_eq!(correct, 10);

        // 错序（乘法先）：7*75/100 = 525/100 = 5 -> 5 + 3 = 8 -> 8*150/100 = 1200/100 = 12
        let wrong = apply(
            ModifierOp::MulPercent,
            apply(ModifierOp::AddStacks, apply(ModifierOp::MulPercent, 7, 75, 1), 1, 3),
            150,
            1,
        );
        assert_eq!(wrong, 12);
        assert_ne!(correct, wrong);
    }

    #[test]
    fn scale_percent_truncates_towards_zero_at_every_step() {
        // 每一步的截断点都必须与参考实现一致（`PassiveModifiers.cs:210` 是整数除法）。
        assert_eq!(5 * 75 / 100, 3); // 3.75 -> 3（`BlockAmountModifierTests.cs:104-130`）
        assert_eq!((5 + 2) * 75 / 100, 5); // 5.25 -> 5（`:132-166`）
        assert_eq!(10 * 75 / 100, 7); // 7.5 -> 7（向量 2）
        assert_eq!(7 * 150 / 100, 10); // 10.5 -> 10（向量 1）
        assert_eq!(7 * 75 % 100, 25); // 截断真的发生了（有余数）
        assert_eq!(6 * 150 % 100, 0); // 而这一步是整除，截断看不出来
    }

    #[test]
    fn block_pipeline_matches_vector_fifteen() {
        // 向量 15（`BlockAmountModifierTests.cs:76-166`）：请求 5 点格挡。
        //   +敏捷 2 ：5 + 1*2               = 7
        assert_eq!(fold_block(5, 2, false), 7);
        //   +脆弱   ：5 * 75 / 100 = 375/100 = 3
        assert_eq!(fold_block(5, 0, true), 3);
        //   两者    ：5 + 2 = 7 -> 7*75/100 = 525/100 = 5
        assert_eq!(fold_block(5, 2, true), 5);

        // 同一个"加法先于乘法"的规格，换成会看出差别的数：base 7、敏捷 3。
        //   正确：7 + 3 = 10 -> 10*75/100 = 7
        //   错序：7*75/100 = 5 -> 5 + 3 = 8
        let correct = fold_block(7, 3, true);
        assert_eq!(correct, 7);
        let wrong = apply(ModifierOp::AddStacks, apply(ModifierOp::MulPercent, 7, 75, 1), 1, 3);
        assert_eq!(wrong, 8);
        assert_ne!(correct, wrong);
    }

    #[test]
    fn damage_rows_are_direct_only_so_dot_and_reflected_are_untouched() {
        // O16 与向量 4：伤害修饰默认只对 `Kind == Direct` 生效。
        assert_ne!(DAMAGE_MODIFIER_DAMAGE_KINDS & DAMAGE_KIND_DIRECT, 0);
        assert_eq!(DAMAGE_MODIFIER_DAMAGE_KINDS & DAMAGE_KIND_DAMAGE_OVER_TIME, 0);
        assert_eq!(DAMAGE_MODIFIER_DAMAGE_KINDS & DAMAGE_KIND_REFLECTED, 0);

        // 向量 4（`DamageAmountModifierTests.cs:126-151`）：哥布林 HP 12，英雄力量 5，
        // DealDamage(5, DamageOverTime) ⇒ **HP 7**：这一跳根本没进修饰管线。
        assert_eq!(12 - 5, 7);
        // 如果门开错了（把 DoT 也当 Direct），同一张表会算出 5 + 1*5 = 10 ⇒ HP 2。
        assert_eq!(fold_damage(5, 5, false, false), 10);
    }

    // ---- D9：字节序 ----

    #[test]
    fn standard_status_ids_are_byte_ordered_not_registration_ordered() {
        let ids = standard_status_ids_sorted();
        assert_eq!(ids.len(), 16);

        let expected = [
            "standard.action_fails",
            "standard.artifact",
            "standard.dexterity",
            "standard.first_attack_each_turn_free",
            "standard.frail",
            "standard.free_next_card",
            "standard.one_attack_per_turn",
            "standard.poison",
            "standard.rage",
            "standard.skill_combo_draw",
            "standard.skill_cost_reduction",
            "standard.strength",
            "standard.stun",
            "standard.thorns",
            "standard.vulnerable",
            "standard.weak",
        ];
        assert_eq!(ids, &expected[..]);

        // ① 逐对严格递增（字节序）
        for pair in ids.windows(2) {
            assert!(
                pair[0].as_bytes() < pair[1].as_bytes(),
                "{} must sort before {}",
                pair[0],
                pair[1]
            );
        }
        // ② 与"把同一集合重新按字节排一遍"的结果相同
        let mut resorted = ids.to_vec();
        resorted.sort_unstable_by(|a, b| a.as_bytes().cmp(b.as_bytes()));
        assert_eq!(ids, resorted.as_slice());
        // ③ 两张元数据表自身的合法性（ASCII、严格字节序、可按 id 查回、标签位合法），
        //    并顺带确认 id 表与元数据表同序。
        status_meta_table_is_valid();

        // ④ 前缀不同的几对，把"为什么是这个序"写出来（16 个 id 共用 `standard.` 前缀，
        //    所以次序完全由后缀决定；这几对的 ASCII 序正是"数字序会搞错"的地方）。
        let pos = |id: &str| ids.iter().position(|x| *x == id).expect("id missing");
        assert!(pos("standard.strength") < pos("standard.stun")); // 'r'(0x72) < 'u'(0x75)
        assert!(pos("standard.frail") < pos("standard.free_next_card")); // 'a'(0x61) < 'e'(0x65)
        assert!(pos("standard.skill_combo_draw") < pos("standard.skill_cost_reduction")); // 'm' < 's'
        assert!(pos("standard.action_fails") < pos("standard.artifact")); // 'c'(0x63) < 'r'(0x72)
        assert!(pos("standard.one_attack_per_turn") < pos("standard.poison")); // 'o' < 'p'
        assert!(pos("standard.thorns") < pos("standard.vulnerable")); // 't' < 'v'
        assert!(pos("standard.artifact") < pos("standard.dexterity")); // 'a' < 'd'
        assert!(pos("standard.weak") > pos("standard.vulnerable")); // 'w' 最大，排尾

        // ⑤ D9 的反例：注册序（intern 发到的数字序）与字节序**不同**。
        assert_eq!(STANDARD_STATUS_REGISTRATION_ORDER[0], "standard.poison");
        assert_eq!(ids[0], "standard.action_fails");
        assert_ne!(ids, &STANDARD_STATUS_REGISTRATION_ORDER[..]);
    }

    #[test]
    fn the_byte_order_self_check_is_not_vacuous() {
        assert!(sorting_key_is_byte_order());

        // 反序、重复、非严格递增都要被判 false（否则这个自证就是空断言）。
        assert!(!ids_are_byte_sorted(&[
            "standard.stun",
            "standard.skill_combo_draw"
        ]));
        assert!(!ids_are_byte_sorted(&[
            "standard.strength",
            "standard.strength"
        ]));
        assert!(ids_are_byte_sorted(&[]));
        assert!(ids_are_byte_sorted(&["standard.weak"]));
        // ASCII 序里 'Z' < 'a'，所以这条是"有序"的；反过来才是乱序。
        assert!(ids_are_byte_sorted(&["standard.Zeta", "standard.alpha"]));
        assert!(!ids_are_byte_sorted(&["standard.alpha", "standard.Zeta"]));
    }

    /// 两张表自身的合法性：ASCII、严格字节序、可按 id 查回、标签位都在词汇表里；
    /// 并钉住"元数据表与 id 表的次序一致"（两个平行数组不许漂移）。
    fn status_meta_table_is_valid() {
        let mut known = 0;
        for (_, bit) in TAG_BITS {
            known |= bit;
        }
        for table in [standard_status_meta(), sts_prototype_status_meta()] {
            for (index, entry) in table.iter().enumerate() {
                assert!(entry.id.is_ascii(), "{} must be ASCII (D13)", entry.id);
                if index > 0 {
                    assert!(
                        table[index - 1].id.as_bytes() < entry.id.as_bytes(),
                        "{} must sort after {}",
                        entry.id,
                        table[index - 1].id
                    );
                }
                // 每个状态 id 都能按 id 查回来（二分查找与表序一致，D9 的字节序也是它的前提）。
                assert_eq!(status_meta(entry.id).map(|meta| meta.id), Some(entry.id));
                assert_eq!(entry.tags & !known, 0, "{} uses an unknown tag bit", entry.id);
            }
        }
        let from_meta: Vec<&str> = standard_status_meta().iter().map(|meta| meta.id).collect();
        assert_eq!(from_meta.as_slice(), standard_status_ids_sorted());
    }

    // ---- 元数据：decay / 极性 / 标签 ----

    #[test]
    fn decay_predicate_splits_the_two_groups() {
        // 真组：易伤 / 虚弱 / 脆弱（两个命名空间各一套）
        for id in [
            "standard.vulnerable",
            "standard.weak",
            "standard.frail",
            "vulnerable",
            "weak",
            "frail",
        ] {
            assert!(decays_at_owner_turn_end(id), "{id} must decay");
        }

        // 假组：力量 / 敏捷 / 荆棘 / 金属化 / 仪式（以及其它没有时长轴的状态）
        for id in [
            "standard.strength",
            "standard.dexterity",
            "standard.thorns",
            "standard.artifact",
            "standard.poison",
            "standard.free_next_card",
            "standard.action_fails",
            "standard.rage",
            "strength",
            "dexterity",
            "thorns",
            "metallicize",
            "ritual",
            "not.a.status",
        ] {
            assert!(!decays_at_owner_turn_end(id), "{id} must not decay");
        }

        // 标准包里"回合结束减 1"的一共 7 个 —— 不是 3 个（`StatusEffects.cs:390-404` 只认
        // `UsesDuration`）。测试把整个集合钉住，免得以后有人把 stun / cost reduction 漏掉。
        let ticking: Vec<&str> = standard_status_meta()
            .iter()
            .filter(|meta| meta.decays_at_owner_turn_end)
            .map(|meta| meta.id)
            .collect();
        assert_eq!(
            ticking,
            [
                "standard.first_attack_each_turn_free",
                "standard.frail",
                "standard.one_attack_per_turn",
                "standard.skill_cost_reduction",
                "standard.stun",
                "standard.vulnerable",
                "standard.weak",
            ]
        );

        // 不变量：标准包里 decays == UsesDuration。
        for meta in standard_status_meta() {
            assert_eq!(
                meta.decays_at_owner_turn_end, meta.axes.duration,
                "{}: turn-end decay is exactly the reference's UsesDuration",
                meta.id
            );
        }
        // 原型命名空间的时钟跑在层数上，所以那 8 行**不**适用上面这条不变量：
        // 只有 3 个 decay 状态，而它们的真实轴是层数。
        assert_eq!(
            sts_prototype_status_meta()
                .iter()
                .filter(|meta| meta.decays_at_owner_turn_end)
                .count(),
            3
        );
        assert!(sts_prototype_status_meta()
            .iter()
            .all(|meta| meta.axes.stacks));
    }

    #[test]
    fn polarity_mirrors_the_state_model_and_marks_debuffs() {
        // 镜像的判别值必须与参考实现的 `StatusPolarity`（`CombatPrimitives.cs:42-47`）一致：
        // `state.rs` 的枚举把它们写进 `pol=<int>`，所以两边不许分叉。
        assert_eq!(StatusPolarity::Buff as i32, 0);
        assert_eq!(StatusPolarity::Debuff as i32, 1);
        assert_eq!(StatusPolarity::Neutral as i32, 2);
        // 这是本模块唯一一处碰 state.rs，而且只在测试里 —— 库代码不依赖状态模型。
        assert_eq!(
            StatusPolarity::Buff as i32,
            crate::state::StatusPolarity::Buff as i32
        );
        assert_eq!(
            StatusPolarity::Debuff as i32,
            crate::state::StatusPolarity::Debuff as i32
        );
        assert_eq!(
            StatusPolarity::Neutral as i32,
            crate::state::StatusPolarity::Neutral as i32
        );

        // 状态施加拦截器要问的那个问题：这是不是负面？
        assert!(status_meta("standard.vulnerable").unwrap().is_debuff());
        assert!(status_meta("standard.weak").unwrap().is_debuff());
        assert!(status_meta("standard.frail").unwrap().is_debuff());
        assert!(status_meta("standard.stun").unwrap().is_debuff());
        assert!(status_meta("standard.artifact").unwrap().is_buff());
        assert!(status_meta("standard.strength").unwrap().is_buff());
        assert!(status_meta("standard.thorns").unwrap().is_buff());
        // `standard.action_fails` 是 Neutral：禁止令的 `UnwantedByBearer` 两向都不拒它
        // （`StatusDefinition.cs:145-150`）。
        assert!(status_meta("standard.action_fails").unwrap().is_neutral());

        // 标准包的负面状态恰好这 6 个（其余 9 buff + 1 neutral）。
        let debuffs = standard_status_meta()
            .iter()
            .filter(|meta| meta.is_debuff())
            .count();
        assert_eq!(debuffs, 6);
        assert_eq!(
            standard_status_meta()
                .iter()
                .filter(|meta| meta.is_buff())
                .count(),
            9
        );
        assert_eq!(
            standard_status_meta()
                .iter()
                .filter(|meta| meta.is_neutral())
                .count(),
            1
        );
    }

    #[test]
    fn tag_bits_match_the_reference_tag_strings() {
        assert_eq!(tag_bit("damage_over_time"), Some(TAG_DAMAGE_OVER_TIME));
        assert_eq!(tag_bit("triggered_damage"), Some(TAG_TRIGGERED_DAMAGE));
        assert_eq!(tag_bit("retain_hand"), Some(TAG_RETAIN_HAND));
        assert_eq!(tag_bit("retain_block"), Some(TAG_RETAIN_BLOCK));
        assert_eq!(
            tag_bit("status_application_interceptor"),
            Some(TAG_STATUS_APPLICATION_INTERCEPTOR)
        );
        assert_eq!(tag_bit("buff"), None); // 极性不是标签位
        assert_eq!(tag_bit("debuff"), None);
        assert_eq!(tag_bit("no_such_tag"), None);

        // 12 个位两两不同。
        for (index, (_, bit)) in TAG_BITS.iter().enumerate() {
            assert_eq!(bit.count_ones(), 1);
            for (_, other) in TAG_BITS.iter().skip(index + 1) {
                assert_ne!(bit, other);
            }
        }

        // 三个"有运行期读取者"的标签挂在对的状态上。
        let has = |id: &str, tag: &str| {
            status_meta(id)
                .expect("catalogued")
                .has_tag(tag_bit(tag).expect("known tag"))
        };
        assert!(has("standard.poison", "damage_over_time")); // 回合开始跳一次（StatusEffects.cs:462）
        assert!(has("standard.thorns", "triggered_damage")); // 被打到时反伤（:537）
        assert!(has("standard.artifact", "status_application_interceptor"));
        assert!(has("standard.dexterity", "block_modifier"));
        assert!(has("standard.strength", "damage_modifier"));
        assert!(has("standard.rage", "card_played_trigger"));

        // 标准包 16 个状态里没有 `retain_hand` / `retain_block`：那是内容侧的保留标记
        // （`CardTurnLifecycleEventHandlers.cs:49`、`DefensivePoolEffects.cs:297`）。
        for meta in standard_status_meta() {
            assert!(!meta.has_tag(TAG_RETAIN_HAND), "{}", meta.id);
            assert!(!meta.has_tag(TAG_RETAIN_BLOCK), "{}", meta.id);
            assert!(!meta.has_tag(TAG_DAMAGE_OVER_TIME) || meta.id == "standard.poison");
            assert!(!meta.has_tag(TAG_TRIGGERED_DAMAGE) || meta.id == "standard.thorns");
        }
    }

    #[test]
    fn catalog_covers_every_modifier_row_and_every_axis_is_spelled_out() {
        for row in damage_modifiers() {
            let meta = status_meta(row.status_id).expect("modifier row must name a catalogued status");
            assert!(
                meta.has_tag(TAG_DAMAGE_MODIFIER),
                "{} must be tagged as a damage modifier",
                row.status_id
            );
            match row.op {
                ModifierOp::AddStacks => assert_eq!(row.percent, 1, "{}", row.status_id),
                ModifierOp::MulPercent => assert!((1..1000).contains(&row.percent), "{}", row.status_id),
            }
            assert!(row.spec_priority > 0);
        }
        for row in block_modifiers() {
            let meta = status_meta(row.status_id).expect("modifier row must name a catalogued status");
            assert!(meta.has_tag(TAG_BLOCK_MODIFIER), "{}", row.status_id);
            match row.op {
                ModifierOp::AddStacks => assert_eq!(row.percent, 1, "{}", row.status_id),
                ModifierOp::MulPercent => assert_eq!(row.percent, 75, "{}", row.status_id),
            }
        }

        // 三轴的取值分布（标准包）：层数 8 / 时长 6 / 充能 2 / 两轴 1 / 无轴 1 … 逐项点清楚，
        // 免得以后有人把 `standard.free_next_card` 写成有时长轴。
        let axes_of = |id: &str| status_meta(id).expect("catalogued").axes;
        assert_eq!(axes_of("standard.poison"), StatusAxes::STACKS);
        assert_eq!(axes_of("standard.artifact"), StatusAxes::CHARGES);
        assert_eq!(axes_of("standard.free_next_card"), StatusAxes::CHARGES);
        assert_eq!(axes_of("standard.vulnerable"), StatusAxes::DURATION);
        assert_eq!(axes_of("standard.weak"), StatusAxes::DURATION);
        assert_eq!(axes_of("standard.frail"), StatusAxes::DURATION);
        assert_eq!(axes_of("standard.stun"), StatusAxes::DURATION);
        assert_eq!(axes_of("standard.one_attack_per_turn"), StatusAxes::DURATION);
        assert_eq!(
            axes_of("standard.first_attack_each_turn_free"),
            StatusAxes::DURATION
        );
        assert_eq!(
            axes_of("standard.skill_cost_reduction"),
            StatusAxes::STACKS_AND_DURATION
        );
        assert_eq!(axes_of("standard.action_fails"), StatusAxes::NONE);
    }

    #[test]
    fn the_prototype_namespace_supplies_metallicize_and_ritual() {
        // 这两个 id 只有原型有（参考实现标准包与样例内容都没有），所以它们的 decay 真值
        // 来自 `sts/content/statuses.json`，不是"未知 ⇒ false"蒙出来的。
        assert_eq!(
            status_meta("metallicize").map(|meta| meta.decays_at_owner_turn_end),
            Some(false)
        );
        assert_eq!(
            status_meta("ritual").map(|meta| meta.decays_at_owner_turn_end),
            Some(false)
        );
        assert_eq!(
            status_meta("metallicize").map(|meta| meta.polarity),
            Some(StatusPolarity::Buff)
        );
        // 原型里有 8 个，两个命名空间的 id 不重名（`weak` vs `standard.weak` 是两条）。
        assert_eq!(sts_prototype_status_meta().len(), 8);
        assert!(status_meta("weak").is_some());
        assert!(status_meta("standard.weak").is_some());
        assert_ne!(
            status_meta("weak").map(|meta| meta.id),
            status_meta("standard.weak").map(|meta| meta.id)
        );
        assert_eq!(status_meta("nothing_here"), None);
    }
}
