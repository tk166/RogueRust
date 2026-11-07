//! 效果程序 IR —— 把 RDCF 的内容寻址 term DAG 读成**带类型**的节点/表达式视图。
//!
//! ## 这一层为什么存在
//!
//! `content.rs` 给的是一棵**通用**的 interned JSON 树：term = `(opcode, slots…)`，
//! opcode 的字段表（`OPD`/`OPF`）说每个槽是 `F_INT` / `F_TERM` / `F_TERMLIST` / … 。
//! 它不知道 `node.dealDamage` 是什么，只知道"这个对象的 `Amount` 字段指向另一个 term"。
//!
//! 本模块补的就是那层语义：**按名字取字段、按 kind 判类型**。它不做任何求值 ——
//! 求值在 `expr`/`exec` 里，本模块只负责"把这棵树读对"。
//!
//! ## 真实形状（实测 core 镜像，不是推测）
//!
//! 每个程序是 `{Id, MaxNodeDepth, MaxProgramSteps, Root}`，`Root` 是一棵 tagged tree：
//!
//! ```text
//! paper_cut    → node.dealDamage { Amount: const{Value:6}, TargetSelector: sel.eventTarget,
//!                                  Element: null, IgnoresBlock: false, ResultKey: null }
//! strong_binder→ node.sequence   { Children: [ node.gainBlock{…}, node.applyStatus{…} ] }
//! ```
//!
//! ## 范围：按**数据**定，不按规格里的 54 种节点定
//!
//! 统计 core 镜像里实际出现的 kind 后（`tools/_core_dump.json` 的遍历结果）：
//! 战斗侧只有 **15 种节点**、表达式以 `const`/`sel.*`/算术/比较为主；
//! 其余（`node.encounter`/`node.event`/`node.shopRef`/`fx.*`/`reward.*`/`meta.*`/`tpl.*`）
//! 全属于 **run 层**，本内核 v1 明确不做。
//!
//! 所以 [`NodeKind`] 只列战斗侧的 15 种，遇到不认识的 kind 返回 `IrError::UnknownKind`
//! 并**如实带上是哪个字符串** —— 不许静默当成 NoOp（那会让一张牌悄悄什么都不做）。
//!
//! ## 四条**实测**出来的格式事实（写代码前用 `reader.py` 逐条核过）
//!
//! 1. **`kind` 不是字段，是 opcode 的名字串。** `node.dealDamage` 的字段表是
//!    `Amount/Children/Element/IgnoresBlock/ResultKey/TargetSelector` —— 里面**没有** `"kind"`。
//!    判别串躺在 `OPD[op].name` 里（`reader.py:216`：`return {"kind": d["name"], "value": body}`）。
//!    ⇒ [`NodeRef::kind_str`] 走 opcode 名，**不走** `field("kind")`。
//! 2. **`F_INT` 的槽是 i16。** 镜像里有 4 个负值（`const{Value:-1}` 的 raw 是 `65535`、
//!    `fx.changeResource{Delta:-300}` 的 raw 是 `65236`）。`raw as i32` 会得到 65535 —— 错。
//! 3. **null 对 `F_TERM` 有两种拼法**：`NULL16` 槽哨兵（镜像里 200+ 处，例如 `Element`/`ResultKey`
//!    都是 `0xFFFE`）；以及一个 `_null` term（`op == OP_NULL`）被 `F_TERM` 指到。两者解出来都是
//!    JSON `null`，所以本模块**都归成 [`Value::Null`]**（`reader.py:193` 把 `OP_NULL` 解成 `None`）。
//!    镜像里 `_null` term 有 1 条但**没人引用**，这条分支靠合成补丁测试覆盖。
//! 4. **`F_JSON` 一次都没出现**（130 个 opcode 的字段表里 0 个 `F_JSON`，2143 个 term 里 0 个
//!    `_json` term），所以 v1 直接拒绝是**如实报告**而不是省事。同理 `_wrap_lower`
//!    **确实出现了** 54 条 term，其中 25 条被 `_obj(Value,Weight).Value`（run 层奖励池权重）
//!    用 `F_TERM` 指到 —— 见 [`NodeRef::field`] 里那条分支。

use crate::content::{
    Content, Field, Table, Term, ABSENT16, ABSENT_INT, BOOL_ABSENT, BOOL_FALSE, BOOL_NULL,
    BOOL_TRUE, F_BOOL, F_INT, F_JSON, F_STR, F_STRLIST, F_TERM, F_TERMLIST, LIST_ABSENT, LIST_NULL,
    NULL16, NULL_INT, OP_FIRST_DYNAMIC, OP_NULL,
};

/// 读 IR 时的结构错误。**全部来自"数据与 schema 不符"，不是"游戏规则拒绝"**。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IrError {
    /// 该 term id 不存在。
    Term(u16),
    /// opcode id 不存在。
    Opcode(u16),
    /// 这个 term 的 opcode 是标量/列表（`op < 16`），不是对象。
    NotAnObject(u16),
    /// 字段表越界或字段 kind 坏。
    Field,
    /// 结构上必须有的字段缺失（`Absent`）。
    Missing(&'static str),
    /// 字段存在，但 kind 与调用者期望不符（例如把 `F_TERM` 当 `F_INT` 读）。
    WrongKind(&'static str),
    /// `F_TERMLIST`/`F_STRLIST` 的 aux 区间越界。
    List,
    /// 槽下标越界。
    Slot,
    /// `<kind>` 判别串不认识（**带上原字符串**，见模块头：不许静默当 NoOp）。
    UnknownKind,
}

/// 效果程序的**节点**种类 —— 只列 core 镜像战斗侧实际出现的 15 种。
///
/// 判别依据是 term 里的 `"kind"` 字段（一个 `F_STR`，例如 `"node.dealDamage"`）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NodeKind {
    /// `node.sequence`：**批处理**，全部孩子入队后才处理反应（`Nodes.cs:3-25`）。
    Sequence,
    /// `node.conditional`：`Condition` 为真走 `Then`，否则走 `Else`（可缺席）。
    Conditional,
    /// `node.forEachTarget`：对集合逐个跑 `Body`。
    ForEachTarget,
    /// `node.forEachCardInZone`：对某个牌区的卡逐张跑 `Body`。
    ForEachCardInZone,
    /// `node.dealDamage`。
    DealDamage,
    /// `node.gainBlock`。
    GainBlock,
    /// `node.heal`。
    Heal,
    /// `node.applyStatus`。
    ApplyStatus,
    /// `node.modifyStatusStacks`。
    ModifyStatusStacks,
    /// `node.setCombatantCounter`。
    SetCombatantCounter,
    /// `node.drawCards`。
    DrawCards,
    /// `node.createCardInstance`。
    CreateCardInstance,
    /// §240：**造一张随机牌**（`Infernal Blade`）。`{Tag, ToZone, Count, CostZero}`。
    ///
    /// 为什么要单独的节点：定义 id 不是内容写的，而是按 tag 从卡表里抽的 —— 那条"抽签"逻辑在
    /// 内核里（`exec::create_random_card`），内容只说"要什么样的牌、落到哪儿"。
    CreateRandomCardInstance,
    /// §241：**把抽牌堆顶那张打出去，然后消耗**（`Havoc`）。零字段。
    PlayTopCardOfDrawPile,
    /// §243：**把弃牌堆洗回抽牌堆**（`Deep Breath`）。`{OwnerSelector}`。
    ShuffleDiscardIntoDraw,
    /// `node.moveCardToZone`。
    MoveCardToZone,
    /// `node.gainResource`。
    GainResource,
    /// `node.loseResource`。
    LoseResource,
    /// `node.createCombatant` —— **造一个战斗员**（Boss 分裂、召唤）。
    ///
    /// 不是参考实现的节点（它没有这个词），是本内核为了"分裂"加的第一个**自定义**节点。
    /// `port-plan.md` §121 说明了为什么它必须存在：内核早就能加战斗员（`add_combatant`），
    /// 但内容没有任何办法说"加一个"。
    CreateCombatant,
    /// `node.endTurn` —— 请求结束当前回合（本内核自己的节点，`port-plan.md` §125）。
    EndTurn,
    /// `node.extraTurn` —— 目标再来一个回合（`port-plan.md` §127）。
    ExtraTurn,
    /// `node.destroyCombatant` —— **把一个战斗员移出战斗**（§178）。
    ///
    /// `createCombatant` 的另一半。StS 的 Slime Boss 是"Boss 消失、两只史莱姆顶替"，
    /// 而在此之前内容只能说"再造两只" —— 于是"只分裂一次"只能靠自摘状态，而状态写入是
    /// **入队请求**（§177 实测：同一回合三次伤害各分裂一次，直到容器满 12）。
    ///
    /// 移出是**结构性**的守卫：不再在名册里，`collect_triggers` 就收不到这个承受者，
    /// 触发器不可能再响第二次。
    DestroyCombatant,
    /// `node.upgradeCards` —— **把牌升级**（§195.7，本内核自己的节点）。
    ///
    /// StS 的"升级"在这份内容里是**定义 id**（`burn` / `burn+`），所以这个节点做的事就是把匹配到的
    /// 实例的定义改成 `<id>+`。没有 `+` 行的卡（`dazed`）**保持原样** —— 那是 StS 的
    /// `canUpgrade() == false`，不是错误。
    UpgradeCards,
    /// `node.carryAwayStolenGold` —— **带着偷来的钱离开战斗**（§201，本内核自己的节点）。
    ///
    /// StS 的 Looter 有一条 `Escape`：`Flees combat with your Gold`。偷钱在内核里只是一个
    /// **计数器**（内容用 `node.setCombatantCounter` + `Relative` 加），而"逃走时钱跟着消失"
    /// 需要一次跨层的记账 —— 那个战斗员马上就要被 `destroyCombatant` 摘掉，计数器会一起没。
    ///
    /// 所以这个节点做一件事：把目标身上 `CounterId` 那一格的**当前值**搬进战斗级的
    /// `gold_carried_away`，再把那一格清零（不重复计）。运行层在 `fight_end` 只看那一个数：
    /// 活着的/被打死的敌人身上的钱**不算**丢失（wiki：`Stolen gold is returned if this enemy is
    /// killed`），只有带走的才算。所以"总共偷了多少"不需要另一个字段。
    CarryAwayStolenGold,
    /// `node.setDefensivePool` —— 把某个防御池**设成**某个值（§233，`Entrench`）。
    ///
    /// 与 `node.gainBlock` 的分工是**设**与**加**：那个走格挡修饰管线（灵巧/脆弱），这个不走 ——
    /// "Double your Block" 翻倍的是当前格挡本身，不是"再获得等量格挡"。
    SetDefensivePool,
    /// `node.loseHp` —— **失去生命**（§236）。不是伤害：不吃格挡、不吃修饰器、不触发"被打"的钩子。
    LoseHp,
    /// §238：**抬高最大生命**（`Feed` 的 "If Fatal, raise your Max HP by 3"）。
    ///
    /// 与 `Heal` 分开：`Heal` 只动当前值（且被最大生命夹住），这条动的是**上限**，
    /// 并顺手把当前值一起抬高（StS 的 "raise your Max HP by N" 同时给你 N 点血）。
    GainMaxHealth,
    /// §250：**打伤害，如果打死了就跑一段子节目**（`Ritual Dagger` / `Hand of Greed`）。
    ///
    /// 与 §238 那条（`DealDamageAndGainMaxHealthIfFatal`）是同一个动机的**一般形态**：
    /// 整棵树先派发完请求、伤害才落地，所以"If Fatal"必须是**一个节点**。差别在于这条不把
    /// "致命之后做什么"写死：那段节目是内容给的（涨这份副本的计数器 / 加金币 / 以后的任何事）。
    ///
    /// `Amount` 在打伤害**之前**求值 —— 所以 `Ritual Dagger` 读到的是**这一次**该打的伤害，
    /// 子节目里涨的计数器只影响下一次。
    DealDamageAndIfFatal,
    /// §250：**在战斗里拿到金币**（`Hand of Greed` 的 "If Fatal, gain 20 Gold"）。
    ///
    /// 金币不是战斗资源（`gainResource` 只认 `ResourceId`），它是跨层的账：这里只累加
    /// `CombatState.gold_gained`，运行层在 `fight_end` 读一次。
    GainGold,
    /// §250：**造"这一张"的副本**（`Pride` / `Necronomicurse`）。
    ///
    /// `createCardInstance` 要一个定义 id 的**字面量**；这两张牌要的是"当前正在结算的这份"
    /// 的副本，而定义 id 只有 `cardInstance.resolving` 那类表达式拿得到、`createCardInstance`
    /// 却只收字面串。参考实现里的对应节点就叫 `createCardCopy`。
    ///
    /// 字段：`{ToZone, Count?, Placement?}`（`Count` 缺席 = 1，`Placement` 缺席 = `Bottom`）。
    CreateCardCopy,
    /// §254：**给一张固定的候选表，选中的那张被立刻打出**（`Wish`）。
    ///
    /// 字段：`{Definitions, Min?, Max?, Then?}`。`Definitions` 是**卡定义 id 的表**
    /// （`F_STRLIST`），按给定顺序成为三个候选。
    ///
    /// 与 `node.offerRandomCards`（`Discovery`）的分工：那个从**随机池**里抽，"抽到什么"是运行期
    /// 的事；这个的候选是**内容写死的** —— `Wish` 的三个选项永远是那三张。合并成一个节点会让
    /// "候选是固定的"这件事没有地方可写。
    ///
    /// `Then` 缺席 = `ToHandFree`（与 `Discovery` 同义）；`Wish` 写 `PlayChosen`。
    OfferCards,
    /// §253：**由别的牌把一张牌打出来**（`Wish` 的三个选项；参考的 `node.playCard`）。
    ///
    /// 字段：`{PlayerSelector, CardExpression, CardTargetSelector?, IgnoreUnplayable?}`。
    ///
    /// 与 `node.playTopCardOfDrawPile`（`Havoc`）的区别：那个"从抽牌堆顶拿一张、强制 Exhaust"，
    /// 这个"把**指定的**那一份按它自己的落区打出去"。两者共用底层的 `play_card` 管线，
    /// 所以费用、事件、触发器、修饰器都只有一份实现。
    ///
    /// `IgnoreUnplayable` 是本内核多出来的一格，理由写在 `play.rs::play_card_from_program`：
    /// StS 的 `Wish` **会**打出 `unplayable` 的牌，而参考的 `playCard` 对它是 no-op。
    /// 默认 `false` ⇒ 与参考逐字相同。
    PlayCard,
    /// §250：**问玩家三选一：从"职业牌池"里随机取 N 张**（`Discovery`）。
    ///
    /// 字段：`{Count, Min?, Max?}`。候选是**卡定义**（`ChoiceSource::Offered`），选完进手牌
    /// 并且**这一份免费**（`ChoiceThen::ToHandFree`）。
    ///
    /// 池子规则见 `exec.rs` 的 `in_offer_pool`：非 `+` 行、不带 `colorless`/`curse`/`status`/
    /// `junk`/`unplayable`、不是 X 费。**这是与 StS 的已知差别**（它是"你的职业牌池"，
    /// 我们的内容没有职业 tag），记在 `port-plan.md` §250。
    OfferRandomCards,
    /// §238：**打伤害，如果打死了就抬高自己的最大生命**（`Feed` 的 "If Fatal, raise your Max HP"）。
    ///
    /// 为什么必须是一个节点：整棵树**先派发完**再让请求落地，所以
    /// `sequence[dealDamage, conditional]` 里的条件求值时伤害还没落地（结构上做不到）。
    /// 同一个原因生出了 `DealDamageAndHealByLoss`（Reaper）—— 这里照那个形状办。
    DealDamageAndGainMaxHealthIfFatal,
    /// `node.dealDamageAndHealByLoss` —— 打伤害，然后按**实际掉的血**给来源回血（§231，`Reaper`）。
    ///
    /// 参考靠 `ResultKey` 把"这一击掉了多少血"传给下一个节点；本内核不支持 `ResultKey`，而
    /// `resolve_damage` 本来就返回 `(blocked, health_lost)` —— 所以这个节点自己当场算。
    DealDamageAndHealByLoss,
    /// `node.dealDamageWithTagBonus` —— **基础伤害 + 每张带某个 tag 的牌一份加成**（§230）。
    ///
    /// `Perfected Strike`：`Deal 6 damage. Deals (2;3) additional damage for ALL your cards containing
    /// "Strike".`（wiki 正文：**in your deck when this card is played**）
    /// ⇒ `Amount + Bonus × (手牌 + 抽牌堆 + 弃牌堆里带该 tag 的牌数)`。
    ///
    /// 为什么不是表达式：查 tag 要读**内容**，而 `ExprContext` 只拿 `&CombatState`；"整片牌区里有几张"
    /// 是节点层已经在做的事（`forEachCardInZone` 的 `TagFilter` 就在这一层读内容）。
    DealDamageWithTagBonus,
    /// `node.addCardCounter` —— 给**一份副本**的 mark counter 加一个增量（§229，`Rampage`）。
    ///
    /// 参考引擎里 `Rampage` 涨的是 `CardInstance.misc` 这类**每副本**数据；本内核里每副本数据的
    /// 唯一载体就是 mark counter（每副本价格 `standard.card_cost_delta` 已经在用）。所以这个节点
    /// 是"这张牌记住了一件事"的一般形态，而不是给 Rampage 写的特例。
    AddCardCounter,
    /// `node.dealDamageToRandomTarget` —— **每次命中从候选池里随机挑一个目标**（§228）。
    ///
    /// StS 的 `Sword Boomerang` 是 "Deal 3 damage to a random enemy 3 (4) times"：不是"打所有敌人"，
    /// 也不是"打同一个敌人"，而是**每一击各自重掷**。`TargetSelector` 给出的是**候选池**
    /// （内容写 `sel.allEnemies`），抽签在节点里做。
    ///
    /// 为什么不是"随机选择器"：选择器解析拿的是 `&CombatState`（只读），而随机要推进
    /// `random_step`（与洗牌/掷骰同一条账）—— 只有拿 `&mut ExecContext` 的节点能同时做这两件事。
    DealDamageToRandomTarget,
    /// `node.chooseCards` —— **问玩家要哪几张牌，然后复制它们**（§226，本内核自己的节点）。
    ///
    /// StS 的 `Dual Wield`（"选一张 Attack 或 Power 牌，造一份/两份副本"）此前**没有载体**：
    /// `selectCards` 是内核自己按稀有度/顺序挑（不问人，而且它**搬**牌），而 `PendingChoice`
    /// 只有药水那三条路（运行层发起，`then` 是消耗/弃抽/拿进手牌）。缺的是
    /// **"玩家的选择" × "复制"** 这个组合。
    ChooseCards,
    /// `node.selectCards` —— **挑卡并搬卡**（§195.4，本内核自己的节点）。
    ///
    /// 参考的词表里有四个 `sel.*` 卡选择器，`sel.rs` 明确拒绝了它们（"卡选择器 / 玩家选择"），
    /// 于是内容无法说"抽牌堆里稀有度最高的那张"。Stasis 需要它，所以这里只加**一个**具体节点，
    /// 而不是一套谓词语言：`{OwnerSelector, FromZone, FallbackZone?, Order, Count, ToZone, Placement?}`。
    SelectCards,
    /// `node.repeat` —— 把 `Body` 跑 `Count` 遍（**参考有、内核此前没移植**，§146）。
    ///
    /// 它一直是 `CombatJson` 注册的 35 个节点之一（`EffectProgramNodes.cs:116-155`），
    /// 但内核的 15 种里没有它 —— 因为 **core 镜像里一条都没有**（固定次数的多段攻击在内容里
    /// 是展开写的，例如 `byrd.peck` 是 5 个 `dealDamage`）。X 费需要"跑 X 遍"，X 是运行期的值，
    /// 展开写不出来 ⇒ 这个节点终于有了第一个内容侧的使用者。
    Repeat,
}

impl NodeKind {
    /// `<kind>` 字段的原文字符串（与 RDCF 里的判别串逐字符相同）。
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            NodeKind::Sequence => "node.sequence",
            NodeKind::Conditional => "node.conditional",
            NodeKind::ForEachTarget => "node.forEachTarget",
            NodeKind::ForEachCardInZone => "node.forEachCardInZone",
            NodeKind::DealDamage => "node.dealDamage",
            NodeKind::GainBlock => "node.gainBlock",
            NodeKind::Heal => "node.heal",
            NodeKind::ApplyStatus => "node.applyStatus",
            NodeKind::ModifyStatusStacks => "node.modifyStatusStacks",
            NodeKind::SetCombatantCounter => "node.setCombatantCounter",
            NodeKind::DrawCards => "node.drawCards",
            NodeKind::CreateCardInstance => "node.createCardInstance",
            NodeKind::MoveCardToZone => "node.moveCardToZone",
            NodeKind::GainResource => "node.gainResource",
            NodeKind::LoseResource => "node.loseResource",
            NodeKind::CreateCombatant => "node.createCombatant",
            NodeKind::DestroyCombatant => "node.destroyCombatant",
            NodeKind::EndTurn => "node.endTurn",
            NodeKind::ExtraTurn => "node.extraTurn",
            NodeKind::UpgradeCards => "node.upgradeCards",
            NodeKind::CarryAwayStolenGold => "node.carryAwayStolenGold",
            NodeKind::SetDefensivePool => "node.setDefensivePool",
            NodeKind::LoseHp => "node.loseHp",
            NodeKind::GainMaxHealth => "node.gainMaxHealth",
            NodeKind::DealDamageAndGainMaxHealthIfFatal => "node.dealDamageAndGainMaxHealthIfFatal",
            NodeKind::DealDamageAndIfFatal => "node.dealDamageAndIfFatal",
            NodeKind::GainGold => "node.gainGold",
            NodeKind::PlayCard => "node.playCard",
            NodeKind::OfferCards => "node.offerCards",
            NodeKind::CreateCardCopy => "node.createCardCopy",
            NodeKind::OfferRandomCards => "node.offerRandomCards",
            NodeKind::CreateRandomCardInstance => "node.createRandomCardInstance",
            NodeKind::PlayTopCardOfDrawPile => "node.playTopCardOfDrawPile",
            NodeKind::ShuffleDiscardIntoDraw => "node.shuffleDiscardIntoDraw",
            NodeKind::DealDamageAndHealByLoss => "node.dealDamageAndHealByLoss",
            NodeKind::DealDamageWithTagBonus => "node.dealDamageWithTagBonus",
            NodeKind::AddCardCounter => "node.addCardCounter",
            NodeKind::DealDamageToRandomTarget => "node.dealDamageToRandomTarget",
            NodeKind::ChooseCards => "node.chooseCards",
            NodeKind::SelectCards => "node.selectCards",
            NodeKind::Repeat => "node.repeat",
        }
    }

    /// 从判别串解析。**不认识就返回 `None`**，由调用方转成 `IrError::UnknownKind`。
    #[must_use]
    pub fn from_wire_name(name: &str) -> Option<Self> {
        const ALL: [NodeKind; 41] = [
            NodeKind::Sequence,
            NodeKind::Conditional,
            NodeKind::ForEachTarget,
            NodeKind::ForEachCardInZone,
            NodeKind::DealDamage,
            NodeKind::GainBlock,
            NodeKind::Heal,
            NodeKind::ApplyStatus,
            NodeKind::ModifyStatusStacks,
            NodeKind::SetCombatantCounter,
            NodeKind::DrawCards,
            NodeKind::CreateCardInstance,
            NodeKind::MoveCardToZone,
            NodeKind::GainResource,
            NodeKind::LoseResource,
            // 本内核自己的第 16 种（分裂 / 召唤）。
            NodeKind::CreateCombatant,
            // §178：第 20 种（分裂的另一半 —— 把本体移出战斗）。
            NodeKind::DestroyCombatant,
            NodeKind::EndTurn,
            NodeKind::ExtraTurn,
            NodeKind::UpgradeCards,
            // §201：带着偷来的钱逃走（Looter 的 `Escape`）。
            NodeKind::CarryAwayStolenGold,
            NodeKind::SelectCards,
            // §226：问玩家要哪几张牌，然后复制（Dual Wield）。
            NodeKind::ChooseCards,
            // §228：每次命中随机挑一个目标（Sword Boomerang）。
            NodeKind::DealDamageToRandomTarget,
            // §229：给这份副本加一个计数器（Rampage）。
            NodeKind::AddCardCounter,
            // §230：按"带某个 tag 的牌数"加伤的伤害（Perfected Strike）。
            NodeKind::DealDamageWithTagBonus,
            // §231：打伤害并按实际掉血回血（Reaper）。
            NodeKind::DealDamageAndHealByLoss,
            // §236：失去生命（Hemokinesis / Offering / Bloodletting / Brutality）。
            NodeKind::LoseHp,
            // §238：抬高最大生命（Feed 的 "If Fatal"）。
            NodeKind::GainMaxHealth,
            NodeKind::DealDamageAndGainMaxHealthIfFatal,
            // §250：一般形态的 "If Fatal" + 金币 + 造这一张的副本 + 三选一候选。
            NodeKind::DealDamageAndIfFatal,
            NodeKind::GainGold,
            NodeKind::PlayCard,
            NodeKind::OfferCards,
            NodeKind::CreateCardCopy,
            NodeKind::OfferRandomCards,
            NodeKind::CreateRandomCardInstance,
            NodeKind::PlayTopCardOfDrawPile,
            NodeKind::ShuffleDiscardIntoDraw,
            // §233：把防御池设成某个值（Entrench）。
            NodeKind::SetDefensivePool,
            NodeKind::Repeat,
        ];
        let mut i = 0;
        while i < ALL.len() {
            if ALL[i].wire_name() == name {
                return Some(ALL[i]);
            }
            i += 1;
        }
        None
    }
}

/// 解析出来的一个**值**：字段按它的 kind 解出来之后的样子。
///
/// ⚠️ 不派生 `PartialEq`：`Value::Node` 里装的是 [`NodeRef`]，而它的身份是"镜像里的一个 term id"，
/// 直接比较两个 `Value` 会让人以为在比较**语义**。断言请 `match` 变体。
#[derive(Debug, Clone, Copy)]
pub enum Value<'a> {
    /// `F_INT` 且不是 NULL。
    Int(i32),
    /// `F_BOOL` 且不是 NULL。
    Bool(bool),
    /// `F_STR` 的串（指向镜像的字符串池）。
    Str(&'a str),
    /// `F_TERM` 指向的另一个对象。
    Node(NodeRef<'a>),
    /// 字段存在但值是**缺席**哨兵（键根本没写）。
    Absent,
    /// 字段存在但值是 **null** 哨兵（键写了、值是 null）。**与 `Absent` 不同**：
    /// 参考实现里 `Element: null` 与"没写 Element"是两种拼法。
    Null,
}

/// 对一个 term 的只读视图。`Copy`，可以随便传。
#[derive(Debug, Clone, Copy)]
pub struct NodeRef<'a> {
    content: &'a Content<'a>,
    id: u16,
}

impl<'a> NodeRef<'a> {
    /// 包一个 term id（不校验；取字段时才会报错）。
    #[must_use]
    pub fn new(content: &'a Content<'a>, id: u16) -> Self {
        Self { content, id }
    }

    /// 这个节点的 term id（调试与去重时有用）。
    #[must_use]
    pub fn id(self) -> u16 {
        self.id
    }

    /// 把一个 term id 包成节点视图 —— 例如 [`Self::list_field`] 返回的那些。
    ///
    /// **纯包装，不校验**（取字段时才报错），与 [`Self::new`] 同一条约定。
    ///
    /// ⚠️ 这个方法是**事后补的**，而且它缺位的代价很具体：`list_field` 只会给你一串 `u16`，
    /// 而 `NodeRef` 的 `content` 字段是模块私有的、`Term` 也只带 `id`/`op`/`slots`，
    /// 在 `#![forbid(unsafe_code)]` 下**没有任何办法**把 id 变回节点。
    /// 结果就是**所有列表孩子都不可达** —— 首当其冲是 `sequence`（core 镜像 1273 次，最高频节点）。
    ///
    /// 一个返回 id 却不提供"id → 视图"的方法，等于给了一把没有齿的钥匙。
    #[must_use]
    pub fn child(self, id: u16) -> Self {
        Self {
            content: self.content,
            id,
        }
    }

    /// 底层 term（越界 ⇒ `IrError::Term`）。
    pub fn term(self) -> Result<Term<'a>, IrError> {
        self.content.term(self.id).ok_or(IrError::Term(self.id))
    }

    /// `<kind>` 判别串 —— **来自 opcode 的名字，不是某个字段**。
    ///
    /// ⚠️ 这一条是实测纠正的（本模块原来的实现写的是 `field("kind")`，那是错的）：
    /// `RDCF` 把判别式编成了 **opcode 身份**（`OPD[op].name` + `OPD[op].opclass == OPCLASS_IR`），
    /// term 记录里只存 `op + slots`，**没有 `kind` 这个键**
    /// （`node.dealDamage` 的字段表 = `Amount/Children/Element/IgnoresBlock/ResultKey/TargetSelector`；
    /// `reader.py:216` 用它还原成 `{"kind": name, "value": body}`）。
    ///
    /// 三种不是 kind 的情况各给一个明确的错：
    /// * `op < 16`（`_null`/`_str`/`_int`/`_bool`/`_arr`/`_json`/`_wrap_*`）⇒ `NotAnObject(op)`；
    /// * 普通对象（`opclass == OPCLASS_GENERIC`，`_obj(…)` 那些形状，**没有判别式**）⇒ `Missing("kind")`；
    /// * opcode 名是空串（预保留块的空洞，镜像里没用到）⇒ `Missing("kind")`。
    pub fn kind_str(self) -> Result<&'a str, IrError> {
        let term = self.term()?;
        if term.op < OP_FIRST_DYNAMIC {
            return Err(IrError::NotAnObject(term.op));
        }
        let opcode = self.content.opcode(term.op).ok_or(IrError::Opcode(term.op))?;
        if !opcode.is_ir() {
            return Err(IrError::Missing("kind"));
        }
        match self.content.string(opcode.name_str) {
            Some(name) if !name.is_empty() => Ok(name),
            _ => Err(IrError::Missing("kind")),
        }
    }

    /// 解析成 [`NodeKind`]；不认识的 kind 返回 `UnknownKind`。
    pub fn kind(self) -> Result<NodeKind, IrError> {
        NodeKind::from_wire_name(self.kind_str()?).ok_or(IrError::UnknownKind)
    }

    /// 在字段表里定位一个键：返回 `(字段描述, 该字段首槽下标)`。
    ///
    /// 槽位是**按字段表顺序累加**出来的（第 `j` 个字段的首槽 = 前 `j` 个字段的 `slots()` 之和），
    /// 这就是 `content-binary-format.md` §5 说的"字段名 → 槽位"映射，没有别的索引可查。
    fn field_spec(self, key: &str) -> Result<Option<(Field<'a>, usize)>, IrError> {
        let term = self.term()?;
        if term.op < OP_FIRST_DYNAMIC {
            return Err(IrError::NotAnObject(term.op));
        }
        let opcode = self.content.opcode(term.op).ok_or(IrError::Opcode(term.op))?;
        let mut slot = 0usize;
        for j in 0..opcode.nfields() {
            let field = opcode.field(j).ok_or(IrError::Field)?;
            // `slots()` 在类别非法（0 / >7）时是 None —— 槽位算不下去，直接报 Field。
            let width = usize::from(field.slots().ok_or(IrError::Field)?);
            let name = self.content.string(field.name_str()).ok_or(IrError::Field)?;
            if name == key {
                return Ok(Some((field, slot)));
            }
            slot = slot.checked_add(width).ok_or(IrError::Field)?;
        }
        Ok(None)
    }

    /// 按名字取一个字段，解成 [`Value`]。
    ///
    /// 键不存在 ⇒ `Ok(None)`；键存在但值是缺席哨兵 ⇒ `Ok(Some(Value::Absent))`。
    /// 这两个**必须能区分** —— 参考实现里"没写"与"写了 null"是两种拼法。
    ///
    /// 几条**如实拒绝**的地方（宁可不读，也不编一个值出来）：
    /// * `F_JSON` ⇒ `WrongKind("F_JSON")`：JSON 载荷是一段串，解它要用户代码/分配器，
    ///   本 crate 两样都没有。镜像里 `F_JSON` **一次都没出现**，所以这条不是借口，是边界。
    /// * `F_TERMLIST`/`F_STRLIST` ⇒ `WrongKind("F_TERMLIST")`/`WrongKind("F_STRLIST")`：
    ///   列表得用 [`Self::list_field`]（两个槽 + 借用出去的缓冲区）。
    /// * `F_TERM` 槽指到 `op < 16` 的**标量 term**（`_str`/`_int`/`_bool`/`_arr`/`_wrap_lower`/
    ///   `_wrap_upper`）⇒ `WrongKind("F_TERM")`：字段声明成"指向对象"，实际装的是个标量。
    ///   **镜像里真的有**：`_obj(Value,Weight).Value` 有 25 条指着 `_wrap_lower`
    ///   （`{"value": …}` 包装对象回退成 term，`content-binary-format.md` §2.4）。
    ///   唯一例外是 `_null` —— 它**就是** JSON null，归成 `Value::Null`（与 `NULL16` 同义）。
    /// * `F_TERM` 槽悬空（term id 越界）⇒ `Term(id)`，不顺延成一个假节点。
    pub fn field(self, key: &str) -> Result<Option<Value<'a>>, IrError> {
        let Some((field, at)) = self.field_spec(key)? else {
            return Ok(None);
        };
        let term = self.term()?;
        let slot = |i: usize| -> Result<u16, IrError> {
            let i = at.checked_add(i).ok_or(IrError::Slot)?;
            term.slot(i).ok_or(IrError::Slot)
        };
        Ok(Some(match field.kind() {
            F_INT => match slot(0)? {
                ABSENT_INT => Value::Absent,
                NULL_INT => Value::Null,
                // 槽是 **i16**，不是 u16：`const{Value:-1}` 的 raw 是 0xFFFF。
                raw => Value::Int(i32::from(raw as i16)),
            },
            F_BOOL => match slot(0)? {
                BOOL_ABSENT => Value::Absent,
                BOOL_FALSE => Value::Bool(false),
                BOOL_TRUE => Value::Bool(true),
                BOOL_NULL => Value::Null,
                _ => return Err(IrError::Field),
            },
            F_STR => match slot(0)? {
                ABSENT16 => Value::Absent,
                NULL16 => Value::Null,
                id => Value::Str(self.content.string(id).ok_or(IrError::Field)?),
            },
            F_TERM => match slot(0)? {
                ABSENT16 => Value::Absent,
                NULL16 => Value::Null,
                id => {
                    let inner = self.content.term(id).ok_or(IrError::Term(id))?;
                    if inner.op >= OP_FIRST_DYNAMIC {
                        Value::Node(NodeRef::new(self.content, id))
                    } else if inner.op == OP_NULL {
                        // `_null` term：JSON null 的第二种拼法，见模块头事实 3。
                        Value::Null
                    } else {
                        return Err(IrError::WrongKind("F_TERM"));
                    }
                }
            },
            F_JSON => return Err(IrError::WrongKind("F_JSON")),
            F_TERMLIST => return Err(IrError::WrongKind("F_TERMLIST")),
            F_STRLIST => return Err(IrError::WrongKind("F_STRLIST")),
            _ => return Err(IrError::Field),
        }))
    }

    /// 取一个子节点字段（`F_TERM`）。
    pub fn node_field(self, key: &str) -> Result<Option<NodeRef<'a>>, IrError> {
        match self.field(key)? {
            None | Some(Value::Absent) | Some(Value::Null) => Ok(None),
            Some(Value::Node(n)) => Ok(Some(n)),
            Some(_) => Err(IrError::WrongKind("F_TERM")),
        }
    }

    /// 取一个子节点**列表**字段（`F_TERMLIST` 或 `F_STRLIST`），写进 `out`，返回个数。
    ///
    /// `out` 装不下时返回 `IrError::List`（**不截断**：少跑几个孩子比报错糟得多）。
    ///
    /// 编码是两个槽 `(AUX 起址, 个数)`，`content-binary-format.md` §2.3：
    /// 个数是 `LIST_ABSENT` 表示"键没写"、`LIST_NULL` 表示"键写了、值是 null"，
    /// 两种都 ⇒ `Ok(0)`（签名只能回个数，而执行侧对这两者都是"没有孩子"；
    /// 需要区分时说明这个签名不够用 —— 那要改冻结类型，不在这里偷偷糊）。
    ///
    /// ⚠️ **这是宽松版，新代码请用 [`Self::term_list_field`] 或 [`Self::str_list_field`]。**
    /// 它接受的两种 kind 返回的 `u16` **含义不同**（`F_TERMLIST` 是 term id、
    /// `F_STRLIST` 是**串号**），而签名无法区分 —— 一个把串号喂给 [`Self::child`] 的调用方
    /// 会拿到一串**看起来合法、其实毫不相干**的 term id，而且**不会报错**。
    pub fn list_field(self, key: &str, out: &mut [u16]) -> Result<usize, IrError> {
        self.list_field_of_kind(key, out, None)
    }

    /// 严格版：只接受 `F_TERMLIST`，返回 **term id**（可以喂给 [`Self::child`]）。
    ///
    /// 为什么这个区分是活的：`node.dealDamage`/`gainBlock`/`applyStatus` 等节点的
    /// `Children` 是 `F_STRLIST`（引擎那条只读派生属性，镜像里 30 条 `LIST_ABSENT`），
    /// 而 `node.sequence`/`node.conditional` 的 `Children` 才是 `F_TERMLIST`。
    /// **同一个键名、两种 kind、两种含义。**
    pub fn term_list_field(self, key: &str, out: &mut [u16]) -> Result<usize, IrError> {
        self.list_field_of_kind(key, out, Some(F_TERMLIST))
    }

    /// §206：**空列表宽容版**：`F_TERMLIST` 或 `F_STRLIST` 都收 —— 但只有当列表是**空**的时候。
    ///
    /// 为什么需要它：JSON 里的 `"IntentRules": []` 会被派生器写成 `F_STRLIST`（非空的一律
    /// `F_TERMLIST`），于是严格读取器会把"这条敌人没有规则"报成形状错误。`maw` 就是这种记录，
    /// 而它在**全遭遇遍历**里才第一次被跑到（§202 的 sweep）。
    ///
    /// ⚠️ 严格版**不动**：`ir::tests::the_two_list_kinds_are_told_apart_by_the_strict_readers`
    /// 钉的正是"两种 list 必须分得清"，而那条契约是对的 —— 放宽只能是一个**显式**的入口，
    /// 不能偷偷放宽 `term_list_field`。
    pub fn term_list_field_or_empty(self, key: &str, out: &mut [u16]) -> Result<usize, IrError> {
        let Some((field, _)) = self.field_spec(key)? else {
            return Ok(0);
        };
        let kind = field.kind();
        if kind == F_TERMLIST {
            return self.term_list_field(key, out);
        }
        if kind == F_STRLIST {
            // Empty is empty; a non-empty string list is still a shape error for this reader.
            let count = self.str_list_field(key, &mut [])?;
            if count == 0 {
                return Ok(0);
            }
        }
        Err(IrError::WrongKind("F_TERMLIST"))
    }

    /// 严格版：只接受 `F_STRLIST`，返回**串号**（用 `Content::string` 解成 `&str`）。
    pub fn str_list_field(self, key: &str, out: &mut [u16]) -> Result<usize, IrError> {
        self.list_field_of_kind(key, out, Some(F_STRLIST))
    }

    /// `want == None` ⇒ 两种 kind 都收（宽松版）；`Some(kind)` ⇒ 只要那一种。
    fn list_field_of_kind(
        self,
        key: &str,
        out: &mut [u16],
        want: Option<u8>,
    ) -> Result<usize, IrError> {
        let Some((field, at)) = self.field_spec(key)? else {
            return Ok(0);
        };
        let kind = field.kind();
        // ⚠️ 这里**不能**写成 `match want { Some(F_TERMLIST) if kind != F_TERMLIST => ..,
        // Some(_) if kind != F_STRLIST => .. }`：第一条臂的**守卫**不成立时，匹配会继续往下走，
        // 掉进 `Some(_)` 那条臂，把"想要 TERMLIST 且拿到了 TERMLIST"判成 "期望 STRLIST"。
        // 第一版就是这么写的，被我自己的测试当场抓到。
        if let Some(want_kind) = want {
            if kind != want_kind {
                return Err(IrError::WrongKind(if want_kind == F_TERMLIST {
                    "F_TERMLIST"
                } else {
                    "F_STRLIST"
                }));
            }
        } else if kind != F_TERMLIST && kind != F_STRLIST {
            return Err(IrError::WrongKind("F_TERMLIST"));
        }
        let term = self.term()?;
        let start = term.slot(at).ok_or(IrError::Slot)?;
        let count = term.slot(at.checked_add(1).ok_or(IrError::Slot)?).ok_or(IrError::Slot)?;
        if count == LIST_ABSENT || count == LIST_NULL {
            return Ok(0);
        }
        let count = usize::from(count);
        if count > out.len() {
            return Err(IrError::List);
        }
        for i in 0..count {
            let cell = usize::from(start).checked_add(i).ok_or(IrError::List)?;
            let cell = u16::try_from(cell).map_err(|_| IrError::List)?;
            let cell = self.content.aux(cell).ok_or(IrError::List)?;
            *out.get_mut(i).ok_or(IrError::List)? = cell;
        }
        Ok(count)
    }

    /// 取一个整数字段（`F_INT`）。缺席/为 null ⇒ `Ok(None)`。
    pub fn int_field(self, key: &str) -> Result<Option<i32>, IrError> {
        match self.field(key)? {
            None | Some(Value::Absent) | Some(Value::Null) => Ok(None),
            Some(Value::Int(v)) => Ok(Some(v)),
            Some(_) => Err(IrError::WrongKind("F_INT")),
        }
    }

    /// 取一个布尔字段（`F_BOOL`）。缺席/为 null ⇒ `Ok(None)`。
    pub fn bool_field(self, key: &str) -> Result<Option<bool>, IrError> {
        match self.field(key)? {
            None | Some(Value::Absent) | Some(Value::Null) => Ok(None),
            Some(Value::Bool(v)) => Ok(Some(v)),
            Some(_) => Err(IrError::WrongKind("F_BOOL")),
        }
    }

    /// 取一个字符串字段（`F_STR`）。缺席/为 null ⇒ `Ok(None)`。
    pub fn str_field(self, key: &str) -> Result<Option<&'a str>, IrError> {
        match self.field(key)? {
            None | Some(Value::Absent) | Some(Value::Null) => Ok(None),
            Some(Value::Str(s)) => Ok(Some(s)),
            Some(_) => Err(IrError::WrongKind("F_STR")),
        }
    }
}

/// 内容镜像 + IR 读取的入口。
#[derive(Debug, Clone, Copy)]
pub struct Ir<'a> {
    content: &'a Content<'a>,
}

impl<'a> Ir<'a> {
    #[must_use]
    pub fn new(content: &'a Content<'a>) -> Self {
        Self { content }
    }

    /// 取 CARD 表第 `index` 行的**效果程序根节点**。
    ///
    /// 路径（实测）：行 → `Program` 格（`F_TERM`）→ 该对象（`_obj(Id,MaxNodeDepth,
    /// MaxProgramSteps,Root)`，opclass 是普通对象，**没有 kind**）→ 它的 `Root` 字段（`F_TERM`）。
    ///
    /// 每一条断链都报错而不是返回半个东西：行号越界 ⇒ `Missing("CARD row")`
    /// （`IrError` 冻结且没有 `Row` 变体），`Program`/`Root` 缺席或为 null ⇒ `Missing(…)`，
    /// `Program` 格声明成非 `F_TERM` ⇒ `WrongKind("F_TERM")`，悬空 term id ⇒ `Term(id)`。
    pub fn card_program_root(&self, index: u32) -> Result<NodeRef<'a>, IrError> {
        let row = self
            .content
            .row(Table::Card, index)
            .ok_or(IrError::Missing("CARD row"))?;
        let cell = row.cell_index("Program").ok_or(IrError::Missing("Program"))?;
        if row.cell_kind(cell) != Some(F_TERM) {
            return Err(IrError::WrongKind("F_TERM"));
        }
        let slot = row
            .cell(u32::try_from(cell).map_err(|_| IrError::Missing("Program"))?)
            .ok_or(IrError::Missing("Program"))?;
        let program = match slot {
            ABSENT16 | NULL16 => return Err(IrError::Missing("Program")),
            id => NodeRef::new(self.content, id),
        };
        program.node_field("Root")?.ok_or(IrError::Missing("Root"))
    }
}

#[cfg(test)]
mod tests {
    //! 这些测试**读真实镜像**（`tools/contentc/out/content.core.rdcf`，85,616 B）。
    //!
    //! 镜像不在仓库里（它是构建产物），所以找不到就 **panic 并打印路径与生成命令** ——
    //! 一个在产物缺席时安静通过的测试等于没有测试。期望值全部是 `reader.py` / `_core_dump.json`
    //! 量出来的实测形状，没有一条是"看着像"写上去的。

    use super::*;
    use crate::content::{OP_STR, OP_WRAP_LOWER, S_OPD, S_OPF, S_TRM, S_TRW};

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

    // ------------------------------------------------------------ 小工具
    fn root_of<'a>(ir: &Ir<'a>, index: u32) -> NodeRef<'a> {
        ir.card_program_root(index)
            .unwrap_or_else(|e| panic!("CARD[{index}] 取不到程序根节点：{e:?}"))
    }

    fn value<'a>(node: NodeRef<'a>, key: &str) -> Value<'a> {
        node.field(key)
            .unwrap_or_else(|e| panic!("term {} 的字段 {key} 读失败：{e:?}", node.id()))
            .unwrap_or_else(|| panic!("term {} 缺字段 {key}", node.id()))
    }

    fn node_value<'a>(node: NodeRef<'a>, key: &str) -> NodeRef<'a> {
        match value(node, key) {
            Value::Node(n) => n,
            other => panic!("{key} 不是 Node 而是 {other:?}"),
        }
    }

    fn int_value(node: NodeRef<'_>, key: &str) -> i32 {
        match value(node, key) {
            Value::Int(v) => v,
            other => panic!("{key} 不是 Int 而是 {other:?}"),
        }
    }

    fn str_value<'a>(node: NodeRef<'a>, key: &str) -> &'a str {
        match value(node, key) {
            Value::Str(s) => s,
            other => panic!("{key} 不是 Str 而是 {other:?}"),
        }
    }

    /// 遍历所有 term，挑出判别串等于 `kind` 的那些 id。
    fn terms_of_kind(content: &Content<'_>, kind: &str) -> Vec<u16> {
        let mut out = Vec::new();
        for tid in 0..content.term_count() {
            let Ok(tid) = u16::try_from(tid) else { continue };
            let Some(term) = content.term(tid) else { continue };
            if NodeRef::new(content, tid).kind_str() == Ok(kind) {
                out.push(term.id);
            }
        }
        out
    }

    /// 遍历所有 term，挑出 opcode 等于 `op` 的那些 id（绕过 `kind_str`，用来找标量 term）。
    fn terms_with_op(content: &Content<'_>, op: u16) -> Vec<u16> {
        (0..content.term_count())
            .filter_map(|tid| u16::try_from(tid).ok())
            .filter(|tid| content.term(*tid).map(|t| t.op) == Some(op))
            .collect()
    }

    /// 镜像里所有判别串（去重、升序）。
    fn kind_inventory<'a>(content: &'a Content<'a>) -> Vec<&'a str> {
        let mut out: Vec<&str> = Vec::new();
        for tid in 0..content.term_count() {
            let Ok(tid) = u16::try_from(tid) else { continue };
            let Ok(kind) = NodeRef::new(content, tid).kind_str() else { continue };
            if !out.contains(&kind) {
                out.push(kind);
            }
        }
        out.sort_unstable();
        out
    }

    // ------------------------------------------------- 补丁用：字节定位
    // 这几个只给"用真实镜像改一个 u16、再看行为"的测试用。
    fn term_slot_offset(content: &Content<'_>, tid: u16, slot: usize) -> usize {
        let trw = content.section(S_TRW).expect("TRW 段");
        let word = usize::from(trw.u16_at(usize::from(tid)).expect("TRW 项越界"));
        let trm = content.section(S_TRM).expect("TRM 段");
        trm.offset as usize + word * 4 + 2 + slot * 2
    }

    fn field_kind_offset(content: &Content<'_>, op: u16, key: &str) -> usize {
        let opcode = content.opcode(op).expect("opcode 必须存在");
        let mut index = None;
        for j in 0..opcode.nfields() {
            let field = opcode.field(j).expect("字段描述越界");
            if content.string(field.name_str()) == Some(key) {
                index = Some(j);
                break;
            }
        }
        let index = index.unwrap_or_else(|| panic!("op {op} 没有字段 {key}"));
        let opd = content.section(S_OPD).expect("OPD 段");
        let field_off = opd.u32_at(usize::from(op) * 2).expect("OPD field_off 越界") as usize;
        let opf = content.section(S_OPF).expect("OPF 段");
        opf.offset as usize + field_off + index * 4 + 2
    }

    fn patch16(blob: &mut [u8], at: usize, value: u16) {
        let slot = blob
            .get_mut(at..at + 2)
            .unwrap_or_else(|| panic!("patch16 越界：{at}"));
        slot.copy_from_slice(&value.to_le_bytes());
    }

    #[test]
    fn the_two_list_kinds_are_told_apart_by_the_strict_readers() {
        // 这条测试存在的理由：`list_field` 对 F_TERMLIST 与 F_STRLIST 都返回 u16，
        // 而两者的含义不同（term id / 串号）。一个把串号喂给 `child()` 的调用方
        // 会拿到一串看起来合法、其实毫不相干的 term id，**而且不会报错**。
        // 严格版让这种误用在类型层面不可能。
        let blob = core_image();
        let content = crate::content::Content::parse(&blob).expect("镜像必须能解析");
        let ir = Ir::new(&content);

        // `node.dealDamage.Children` 是 F_STRLIST（引擎那条只读派生属性，镜像里是 LIST_ABSENT）。
        let deal = ir.card_program_root(0).expect("paper_cut 的根");
        assert_eq!(deal.kind(), Ok(NodeKind::DealDamage));
        let mut buf = [0u16; 8];
        assert_eq!(deal.str_list_field("Children", &mut buf), Ok(0), "STRLIST 且 ABSENT ⇒ 0 项");
        assert_eq!(
            deal.term_list_field("Children", &mut buf),
            Err(IrError::WrongKind("F_TERMLIST")),
            "把 STRLIST 当 TERMLIST 读必须报错，而不是把串号当 term id 交出去"
        );

        // `node.sequence.Children` 是 F_TERMLIST。
        let seq = ir.card_program_root(4).expect("strong_binder 的根");
        assert_eq!(seq.kind(), Ok(NodeKind::Sequence));
        let n = seq.term_list_field("Children", &mut buf).expect("TERMLIST 必须能读");
        assert_eq!(n, 2);
        assert_eq!(
            seq.str_list_field("Children", &mut buf),
            Err(IrError::WrongKind("F_STRLIST"))
        );
        // 宽松版两种都收 —— 这正是它危险的地方，也是它仍然存在的原因（既有调用点依赖它）。
        assert_eq!(seq.list_field("Children", &mut buf), Ok(2));
        assert_eq!(deal.list_field("Children", &mut buf), Ok(0));
    }

    #[test]
    fn node_kind_wire_names_round_trip_and_reject_unknown() {
        for k in [
            NodeKind::Sequence,
            NodeKind::Conditional,
            NodeKind::DealDamage,
            NodeKind::GainBlock,
            NodeKind::ApplyStatus,
            NodeKind::LoseResource,
        ] {
            assert_eq!(NodeKind::from_wire_name(k.wire_name()), Some(k));
        }
        // 不认识的串必须给 None，由调用方转成 UnknownKind —— **不许静默当 NoOp**。
        assert_eq!(NodeKind::from_wire_name("node.doesNotExist"), None);
        assert_eq!(NodeKind::from_wire_name(""), None);
        // run 层的那些明确不在本 v1 的范围里。
        assert_eq!(NodeKind::from_wire_name("node.encounter"), None);
        assert_eq!(NodeKind::from_wire_name("node.event"), None);
        // 大小写敏感（kind 串是逐字符比较的）。
        assert_eq!(NodeKind::from_wire_name("Node.DealDamage"), None);
    }

    #[test]
    fn the_run_layer_kinds_are_deliberately_out_of_scope() {
        // 这条测试是文档：core 镜像里 node.encounter(23) / node.event(7) / node.shopRef(1)
        // 是**真的有**，但它们属于 run 层。把它们排除在外是决定，不是遗漏。
        // 如果哪天有人把它们加进 NodeKind，这条会红，提醒他先想清楚 v1 的边界。
        let run_layer = ["node.encounter", "node.event", "node.shopRef"];
        for name in run_layer {
            assert_eq!(NodeKind::from_wire_name(name), None, "{name} 属于 run 层，v1 不做");
        }
    }

    // ===================================================================
    // 1. 三张卡的实测形状（paper_cut / cower_behind_a_desk / strong_binder）
    // ===================================================================

    #[test]
    fn paper_cut_root_is_a_typed_deal_damage() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let ir = Ir::new(&content);
        let root = root_of(&ir, 0);

        // CARD[0] = paper_cut（行号与 id 的对应由 IDX 表保证，这里只用行号）。
        assert_eq!(
            content.row(Table::Card, 0).map(|r| r.cell_index("Program")),
            Some(Some(1)),
            "CARD 行里 Program 是第 1 格"
        );
        assert_eq!(root.kind(), Ok(NodeKind::DealDamage));
        assert_eq!(root.kind_str(), Ok("node.dealDamage"));

        // Amount → const{Value: 6}
        let amount = node_value(root, "Amount");
        assert_eq!(amount.kind_str(), Ok("const"));
        assert_eq!(int_value(amount, "Value"), 6);

        // TargetSelector → sel.eventTarget{Cardinality: ZeroOrOne, …: EventTarget}
        let sel = node_value(root, "TargetSelector");
        assert_eq!(sel.kind_str(), Ok("sel.eventTarget"));
        assert_eq!(str_value(sel, "Cardinality"), "ZeroOrOne");
        assert_eq!(str_value(sel, "RequiredContextCapabilities"), "EventTarget");

        // Element / ResultKey：**键写了、值是 null**（槽是 NULL16 = 0xFFFE）。
        assert!(
            matches!(value(root, "Element"), Value::Null),
            "Element 必须是 Value::Null，实测槽位是 0xFFFE 而不是 0xFFFF"
        );
        assert!(matches!(value(root, "ResultKey"), Value::Null));
        // IgnoresBlock 是 BOOL_FALSE(1)，不是 BOOL_ABSENT(0)。
        assert!(matches!(value(root, "IgnoresBlock"), Value::Bool(false)));
    }

    #[test]
    fn cower_behind_a_desk_root_is_a_typed_gain_block() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let ir = Ir::new(&content);
        let root = root_of(&ir, 2);

        assert_eq!(root.kind(), Ok(NodeKind::GainBlock));
        assert_eq!(int_value(node_value(root, "Amount"), "Value"), 5);

        let sel = node_value(root, "TargetSelector");
        assert_eq!(sel.kind_str(), Ok("sel.source"));
        assert_eq!(str_value(sel, "Cardinality"), "ZeroOrOne");
        assert_eq!(str_value(sel, "RequiredContextCapabilities"), "Source");

        // gainBlock 上根本没有 "Amount" 之外的表达式字段：键存在性也要读对。
        assert!(matches!(value(root, "ResultKey"), Value::Null));
        assert!(matches!(root.field("Condition"), Ok(None)));
    }

    #[test]
    fn strong_binder_root_is_a_sequence_of_two_typed_children() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let ir = Ir::new(&content);
        let root = root_of(&ir, 4);

        assert_eq!(root.kind(), Ok(NodeKind::Sequence));
        let mut kids = [0u16; 8];
        let n = root.list_field("Children", &mut kids).expect("Children 必须能读");
        assert_eq!(n, 2, "strong_binder = gainBlock + applyStatus");

        let first = NodeRef::new(&content, kids[0]);
        assert_ne!(first.id(), root.id());
        assert_eq!(first.kind(), Ok(NodeKind::GainBlock));
        assert_eq!(int_value(node_value(first, "Amount"), "Value"), 7);
        assert_eq!(node_value(first, "TargetSelector").kind_str(), Ok("sel.source"));

        let second = NodeRef::new(&content, kids[1]);
        assert_ne!(second.id(), first.id());
        assert_eq!(second.kind(), Ok(NodeKind::ApplyStatus));
        assert_eq!(int_value(node_value(second, "Stacks"), "Value"), 1);
        // StatusDefinitionId 是 **F_STR**（FLAG_WRAP_LOWER），不是一层 `_obj{value}`
        // —— 包装对象根本不落盘（content-binary-format.md §2.4），
        // 所以这里读到的是裸串 "doubt"，JSON 里的 `{"value":"doubt"}` 是 reader 还原出来的写法。
        assert_eq!(str_value(second, "StatusDefinitionId"), "doubt");
        assert_eq!(int_value(second, "Charges"), 0);
        assert_eq!(int_value(second, "DurationTurns"), 0);
        assert_eq!(node_value(second, "TargetSelector").kind_str(), Ok("sel.eventTarget"));
        assert!(matches!(value(second, "ResultKey"), Value::Null));
    }

    // ===================================================================
    // 2. Absent / Null / 键不存在 —— 三者必须互相可分
    // ===================================================================

    #[test]
    fn absent_null_and_missing_key_are_three_different_answers() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let ir = Ir::new(&content);
        let paper_cut = root_of(&ir, 0);

        // (a) 键存在、值是 null（F_TERM 的 NULL16 槽）。
        assert!(matches!(paper_cut.field("Element"), Ok(Some(Value::Null))));
        // (b) 键不存在 —— 同一张卡上换个名字就是 None，不是 Absent。
        assert!(matches!(paper_cut.field("Element2"), Ok(None)));
        // (c) 键存在、值是**缺席哨兵**（ABSENT16 槽）：镜像里 divide 一个 kind 有两种写法，
        //     {Dividend,Divisor,ZeroPolicy} 与 {Left,Right}，缺的那两个键槽是 0xFFFF。
        //     这同时证明了"字段表是各实例键集的并集"这件事。
        let divides = terms_of_kind(&content, "divide");
        assert_eq!(divides.len(), 4, "镜像里 divide 有 4 条互异 term");
        let (mut absent, mut present) = (0, 0);
        for id in &divides {
            match NodeRef::new(&content, *id).field("Dividend") {
                Ok(Some(Value::Absent)) => absent += 1,
                Ok(Some(Value::Node(_))) => {
                    present += 1;
                    // 另一个写法下 Left/Right 才在场：缺席的键不能凭空解出值。
                    assert!(matches!(
                        NodeRef::new(&content, *id).field("Left"),
                        Ok(Some(Value::Absent))
                    ));
                }
                other => panic!("divide.Dividend 出现了未预期的值：{other:?}"),
            }
        }
        assert_eq!((absent, present), (2, 2), "两种写法各 2 条");
    }

    // ===================================================================
    // 3. 不认识的 kind 必须响亮失败，绝不当 NoOp
    // ===================================================================

    #[test]
    fn an_unknown_kind_is_never_silently_a_no_op() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");

        // node.encounter 在镜像里真的存在（23 条 term，全在 run 层的遭遇表里）。
        let encounters = terms_of_kind(&content, "node.encounter");
        assert_eq!(encounters.len(), 23, "node.encounter 实测 23 条");
        for id in &encounters {
            let node = NodeRef::new(&content, *id);
            assert_eq!(node.kind_str(), Ok("node.encounter"));
            assert_eq!(
                node.kind(),
                Err(IrError::UnknownKind),
                "term {id} 的 kind() 必须是 UnknownKind —— 返回 Ok(Sequence) 之类会让这张牌悄悄什么都不做"
            );
            // 字段还是读得出来的：拒绝的是"当成已知节点执行"，不是"整条记录不可读"。
            assert!(matches!(node.field("Id"), Ok(Some(Value::Str(_)))));
        }

        // 另外两个 run 层 kind 也确认一下数量（node.event 7 / node.shopRef 1）。
        assert_eq!(terms_of_kind(&content, "node.event").len(), 7);
        assert_eq!(terms_of_kind(&content, "node.shopRef").len(), 1);
    }

    // ===================================================================
    // 4. 15 种 NodeKind 全部有数据；镜像的判别串清单被钉死
    // ===================================================================

    const ALL_NODE_KINDS: [NodeKind; 15] = [
        NodeKind::Sequence,
        NodeKind::Conditional,
        NodeKind::ForEachTarget,
        NodeKind::ForEachCardInZone,
        NodeKind::DealDamage,
        NodeKind::GainBlock,
        NodeKind::Heal,
        NodeKind::ApplyStatus,
        NodeKind::ModifyStatusStacks,
        NodeKind::SetCombatantCounter,
        NodeKind::DrawCards,
        NodeKind::CreateCardInstance,
        NodeKind::MoveCardToZone,
        NodeKind::GainResource,
        NodeKind::LoseResource,
    ];

    #[test]
    fn all_fifteen_node_kinds_actually_occur_in_the_image() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        for kind in ALL_NODE_KINDS {
            assert!(
                !terms_of_kind(&content, kind.wire_name()).is_empty(),
                "{} 在镜像里一条都没有 —— NodeKind 长了死变体",
                kind.wire_name()
            );
        }
    }

    #[test]
    fn the_images_kind_inventory_is_15_nodes_plus_58_documented_others() {
        // 这是本层最重要的"还差什么"清单：镜像里一共 73 种判别串，
        // 15 种是本模块认识的节点，58 种是表达式 / run 层（下一步要逐条决定怎么处理）。
        // 新出现一种 ⇒ 这条红，逼人先决定它归哪边，而不是让它悄悄变成 UnknownKind。
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");

        const OTHERS: [&str; 58] = [
            "add",                                 // 8
            "and",                                 // 15
            "card.upgradeLevel",                   // 1
            "cardInstance.iterated",               // 1
            "cardsPlayedLastTurn",                 // 1
            "cardsPlayedThisTurn",                 // 1
            "cardsPlayedThisTurnWithTag",          // 3
            "combatantCounter",                    // 16
            "combatantCurrentResource",            // 1
            "combatantStatusStacks",               // 13
            "compare",                             // 41
            "const",                               // 25
            "currentHealth",                       // 1
            "divide",                              // 4
            "event.bool",                          // 2
            "eventAmount",                         // 1
            "firstCardPlayedHasTag",               // 4
            "fx.addCard",                          // 26
            "fx.addRelicById",                     // 49
            "fx.changeResource",                   // 22
            "fx.computedDamage",                   // 4
            "fx.computedHeal",                     // 2
            "fx.duplicateCards",                   // 1
            "fx.heal",                             // 3
            "fx.incrementCounter",                 // 1
            "fx.installNextCombatOpening",         // 38
            "fx.offerReward",                      // 39
            "fx.removeCards",                      // 2
            "fx.transformCards",                   // 1
            "fx.upgradeCards",                     // 2
            "intent.opponentCardsPlayed",          // 1
            "intent.selfHasCounter",               // 4
            "maxHealth",                           // 1
            "meta.setFlag",                        // 1
            "min",                                 // 8
            "multiply",                            // 12
            "node.encounter",                      // 23
            "node.event",                          // 7
            "node.shopRef",                        // 1
            "or",                                  // 4
            "reward.fixed",                        // 23
            "reward.pool",                         // 2
            "sel.allAllies",                       // 1
            "sel.allCombatants",                   // 1
            "sel.allEnemies",                      // 1
            "sel.alliesWithStatus",                // 3
            "sel.choose",                          // 4
            "sel.deckCards",                       // 1
            "sel.enemiesWithStatus",               // 2
            "sel.eventTarget",                     // 1
            "sel.iterationTarget",                 // 1
            "sel.lowestHealthEnemy",               // 1
            "sel.matching",                        // 1
            "sel.random",                          // 1
            "sel.source",                          // 1
            "sel.withStatus",                      // 5
            "subtract",                            // 3
            "tpl.literal",                         // 35
        ];

        let inventory = kind_inventory(&content);
        assert_eq!(inventory.len(), 73, "实测共 73 种判别串");
        let others: Vec<&str> = inventory
            .iter()
            .copied()
            .filter(|k| NodeKind::from_wire_name(k).is_none())
            .collect();
        assert_eq!(others, OTHERS.to_vec());
    }

    // ===================================================================
    // 5. 坏输入：越界 / 标量 term —— 报错，不 panic
    // ===================================================================

    #[test]
    fn a_dangling_term_id_reports_instead_of_panicking() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let bogus = NodeRef::new(&content, u16::MAX);
        assert_eq!(bogus.term(), Err(IrError::Term(u16::MAX)));
        assert!(matches!(bogus.field("Amount"), Err(IrError::Term(u16::MAX))));
        assert_eq!(bogus.kind_str(), Err(IrError::Term(u16::MAX)));
        assert_eq!(bogus.kind(), Err(IrError::Term(u16::MAX)));
        assert_eq!(bogus.list_field("Children", &mut [0u16; 4]), Err(IrError::Term(u16::MAX)));

        // 刚好越过末尾一个：term_count 之后的第一个 id。
        let past_end = u16::try_from(content.term_count()).expect("term_count 不超 u16");
        assert!(matches!(
            NodeRef::new(&content, past_end).field("Anything"),
            Err(IrError::Term(_))
        ));
    }

    #[test]
    fn scalar_terms_are_not_objects() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        // 镜像里 op<16 的 term 一共 5 类：_null(1) _str(1) _int(1) _arr(243) _wrap_lower(54)。
        let mut seen: Vec<u16> = Vec::new();
        for op in [OP_NULL, 1u16, 2, 4, OP_WRAP_LOWER] {
            let ids = terms_with_op(&content, op);
            assert!(!ids.is_empty(), "op {op} 的 term 缺失");
            seen.push(op);
            for id in ids {
                let node = NodeRef::new(&content, id);
                assert!(matches!(node.field("Value"), Err(IrError::NotAnObject(o)) if o == op));
                assert_eq!(node.kind_str(), Err(IrError::NotAnObject(op)));
                assert_eq!(node.list_field("Children", &mut [0u16; 2]), Err(IrError::NotAnObject(op)));
            }
        }
        assert_eq!(seen, vec![OP_NULL, 1, 2, 4, OP_WRAP_LOWER]);
        assert_eq!(terms_with_op(&content, 4).len(), 243, "_arr 243 条");
        assert_eq!(terms_with_op(&content, OP_WRAP_LOWER).len(), 54, "_wrap_lower 54 条");
        // _bool 一条都没有 —— 布尔值都落在 F_BOOL 字段/格里，不单独成 term。
        assert!(terms_with_op(&content, 3).is_empty());
    }

    // ===================================================================
    // 6. list_field：不截断、不越界、非列表要拒绝
    // ===================================================================

    #[test]
    fn list_field_refuses_to_truncate() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let ir = Ir::new(&content);
        let sequence = root_of(&ir, 4); // strong_binder

        // 装得下：2 个。
        let mut exact = [0u16; 2];
        assert_eq!(sequence.list_field("Children", &mut exact), Ok(2));
        // 再多一个位置也一样（不写多余项）。
        let mut roomy = [0u16; 4];
        assert_eq!(sequence.list_field("Children", &mut roomy), Ok(2));
        assert_eq!(roomy[..2], exact, "同样的两个孩子");

        // 装不下：Err(List)，**不截断成 1**。
        assert_eq!(sequence.list_field("Children", &mut [0u16; 1]), Err(IrError::List));
        assert_eq!(sequence.list_field("Children", &mut []), Err(IrError::List));

        // 键不存在 ⇒ Ok(0)（paper_cut 上没有 Children 之外的列表字段）。
        assert_eq!(sequence.list_field("Nope", &mut []), Ok(0));

        // 非列表字段 ⇒ WrongKind。
        let paper_cut = root_of(&ir, 0);
        assert_eq!(
            paper_cut.list_field("Amount", &mut [0u16; 4]),
            Err(IrError::WrongKind("F_TERMLIST"))
        );
    }

    #[test]
    fn an_absent_list_is_zero_items_not_an_error() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let ir = Ir::new(&content);
        // node.dealDamage / node.gainBlock 的 Children 是 **F_STRLIST 且 LIST_ABSENT**
        // （两个槽都是 0xFFFF）—— 这是"键没写"，不是空数组（空数组是 (起址, 0)）。
        let paper_cut = root_of(&ir, 0);
        assert_eq!(paper_cut.list_field("Children", &mut []), Ok(0));
        assert_eq!(paper_cut.list_field("Children", &mut [0u16; 4]), Ok(0));
        // field() 对列表字段明说"用 list_field"，不猜成 Absent/Null。
        assert!(matches!(
            paper_cut.field("Children"),
            Err(IrError::WrongKind("F_STRLIST"))
        ));
    }

    // ===================================================================
    // 7. 键名大小写敏感
    // ===================================================================

    #[test]
    fn field_lookup_is_case_sensitive() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let ir = Ir::new(&content);
        let root = root_of(&ir, 0);
        assert!(matches!(root.field("Amount"), Ok(Some(Value::Node(_)))));
        assert!(matches!(root.field("amount"), Ok(None)));
        assert!(matches!(root.field("AMOUNT"), Ok(None)));
        assert!(matches!(root.field(""), Ok(None)));
        // 同理：kind 不是字段，所以 field("kind") 永远是 None（见下一条测试）。
    }

    // ===================================================================
    // 8. kind 是 opcode 的名字，不是字段（本模块最初实现错的地方）
    // ===================================================================

    #[test]
    fn kind_comes_from_the_opcode_name_not_from_a_field() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let ir = Ir::new(&content);
        let root = root_of(&ir, 0);

        // node.dealDamage 的字段表：Amount Children Element IgnoresBlock ResultKey TargetSelector。
        // **里面没有 "kind"** —— 判别式是 opcode 身份（OPD[op].name）。
        assert!(
            matches!(root.field("kind"), Ok(None)),
            "镜像里不存在 kind 字段；kind 是 opcode 名"
        );
        assert_eq!(root.kind_str(), Ok("node.dealDamage"));

        // 程序信封 `_obj(Id,MaxNodeDepth,MaxProgramSteps,Root)` 是**普通对象**，没有判别式
        // ⇒ Missing("kind")，而不是 UnknownKind、更不是某个节点。
        let program_id = content
            .row(Table::Card, 0)
            .and_then(|r| r.cell_by_name("Program"))
            .expect("CARD[0].Program");
        let program = NodeRef::new(&content, program_id);
        assert_eq!(program.kind_str(), Err(IrError::Missing("kind")));
        assert_eq!(program.kind(), Err(IrError::Missing("kind")));
        // 但它的字段照读：Id 是被大写包装过的串（FLAG_WRAP_UPPER），根在 Root 里。
        assert_eq!(str_value(program, "Id"), "(unnamed)");
        assert_eq!(int_value(program, "MaxNodeDepth"), 64);
        assert_eq!(int_value(program, "MaxProgramSteps"), 1024);
        assert_eq!(node_value(program, "Root").id(), root.id());
    }

    // ===================================================================
    // 9. 整数是有符号的（F_INT 的槽是 i16，不是 u16）
    // ===================================================================

    #[test]
    fn int_fields_are_signed_i16_not_raw_u16() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let mut negatives: Vec<(String, i32)> = Vec::new();
        for tid in 0..content.term_count() {
            let Ok(tid) = u16::try_from(tid) else { continue };
            let node = NodeRef::new(&content, tid);
            let Ok(kind) = node.kind_str() else { continue };
            for key in ["Value", "Delta", "Magnitude", "TakeFirst"] {
                if let Ok(Some(Value::Int(v))) = node.field(key) {
                    if v < 0 {
                        negatives.push((format!("{kind}.{key}"), v));
                    }
                }
            }
        }
        // 实测 4 个负值：const.Value=-1、fx.changeResource.Delta=-300，另两个在 `_obj`
        // （普通对象没有判别串，`kind_str` 拒绝它们，所以这里只收得到前两个）。
        // 若把槽当 u16 读，这里会出现 65535 / 65236 这种数 —— 那就是 bug。
        assert_eq!(
            negatives,
            vec![
                ("const.Value".to_string(), -1),
                ("fx.changeResource.Delta".to_string(), -300),
            ],
            "实测的负整数（F_INT 的槽是 i16）"
        );
        assert!(negatives.iter().all(|(_, v)| *v > -32767), "没碰到 ABSENT_INT/NULL_INT");
    }

    // ===================================================================
    // 10. 62 张卡全部能解析出类型化的根
    // ===================================================================

    #[test]
    fn every_card_resolves_to_a_typed_root() {
        let blob = core_image();
        let content = Content::parse(&blob).expect("真实镜像必须能解析");
        let ir = Ir::new(&content);
        let cards = content.rows(Table::Card).count();
        assert_eq!(cards, 62, "镜像里 62 张卡");

        let mut tally = [0usize; 5];
        for index in 0..u32::try_from(cards).expect("行数不超 u32") {
            let root = root_of(&ir, index);
            let kind = root
                .kind()
                .unwrap_or_else(|e| panic!("CARD[{index}] 的根节点 kind 读不出来：{e:?}"));
            let slot = match kind {
                NodeKind::Sequence => 0,
                NodeKind::ApplyStatus => 1,
                NodeKind::DealDamage => 2,
                NodeKind::GainBlock => 3,
                NodeKind::DrawCards => 4,
                other => panic!("CARD[{index}] 的根节点是未预期的 {other:?}"),
            };
            tally[slot] += 1;
            // 每张卡的根都能继续读字段（这里挑每个节点都该有的两个键探一下）。
            assert!(root.field("kind").is_ok());
            assert!(root.field("ResultKey").is_ok());
        }
        // 实测分布（`reader.py --table CARD` 逐个核过）：
        assert_eq!(
            tally,
            [43usize, 8, 6, 4, 1],
            "sequence43 applyStatus8 dealDamage6 gainBlock4 drawCards1"
        );

        // 越界行号：报错，不 panic、不返回上一行。
        let past = u32::try_from(cards).expect("行数不超 u32");
        assert!(matches!(
            ir.card_program_root(past),
            Err(IrError::Missing("CARD row"))
        ));
        assert!(matches!(
            ir.card_program_root(9999),
            Err(IrError::Missing("CARD row"))
        ));
    }

    // ===================================================================
    // 11. 合成补丁：镜像里没出现、但格式允许 / 必须拒绝的拼法
    //     （真镜像只改一个 u16，其余全是真的）
    // ===================================================================

    #[test]
    fn a_field_declared_f_json_is_refused_not_guessed() {
        let mut blob = core_image();
        let (op, at) = {
            let content = Content::parse(&blob).expect("真实镜像必须能解析");
            let ir = Ir::new(&content);
            let root = root_of(&ir, 0);
            let op = root.term().expect("term").op;
            (op, field_kind_offset(&content, op, "Element"))
        };
        // 先把 Element 的字段类别从 F_TERM(4) 改成 F_JSON(7)（两者都是 1 槽，记录长度不变）。
        assert_eq!(blob.get(at), Some(&F_TERM), "Element 的类别字节位置");
        *blob.get_mut(at).expect("类别字节") = F_JSON;

        let content = Content::parse(&blob).expect("改一个类别字节后仍须能解析");
        let ir = Ir::new(&content);
        let root = root_of(&ir, 0);
        assert_eq!(root.term().expect("term").op, op, "改的是同一个 opcode");
        assert!(
            matches!(
                root.field("Element"),
                Err(IrError::WrongKind("F_JSON"))
            ),
            "F_JSON 载荷是 JSON 串，本 crate 没有分配器也没有 JSON 解析器 —— 明说做不到"
        );
        // 同一 opcode 的别的字段不受影响。
        assert_eq!(int_value(node_value(root, "Amount"), "Value"), 6);
    }

    #[test]
    fn a_null_term_and_a_wrapped_scalar_through_f_term_are_told_apart() {
        let blob = core_image();
        let (tid, at) = {
            let content = Content::parse(&blob).expect("真实镜像必须能解析");
            let root = root_of(&Ir::new(&content), 0);
            // Element 是 dealDamage 的第 3 个字段（Amount 1 + Children 2 = 3）。
            (root.id(), term_slot_offset(&content, root.id(), 3))
        };
        {
            let content = Content::parse(&blob).expect("真实镜像必须能解析");
            assert!(
                matches!(
                    NodeRef::new(&content, tid).field("Element"),
                    Ok(Some(Value::Null))
                ),
                "补丁前 Element 是 NULL16"
            );
        }

        // 先拿到三种"标量 term"的 id：只借一次 blob，后面全是 patch → 重新 parse。
        let (null_term, str_term, wrap_term) = {
            let content = Content::parse(&blob).expect("解析");
            let pick = |op: u16| -> u16 {
                *terms_with_op(&content, op)
                    .first()
                    .unwrap_or_else(|| panic!("op {op} 的 term 缺失"))
            };
            (pick(OP_NULL), pick(OP_STR), pick(OP_WRAP_LOWER))
        };

        let mut probe = blob.clone();

        // (a) 换成 `_null` term：**同样是 JSON null**，必须还是 Null（不是 Node、不是 Absent）。
        patch16(&mut probe, at, null_term);
        {
            let content = Content::parse(&probe).expect("解析");
            assert!(
                matches!(
                    NodeRef::new(&content, tid).field("Element"),
                    Ok(Some(Value::Null))
                ),
                "_null term 与 NULL16 槽都表示 JSON null"
            );
        }

        // (b) 换成 `_str` term：F_TERM 装了个标量 ⇒ WrongKind("F_TERM")，不许当节点返回。
        patch16(&mut probe, at, str_term);
        {
            let content = Content::parse(&probe).expect("解析");
            assert!(matches!(
                NodeRef::new(&content, tid).field("Element"),
                Err(IrError::WrongKind("F_TERM"))
            ));
        }

        // (c) 换成 `_wrap_lower` term：这就是 content-binary-format.md §2.4 说的
        //     "拼法不统一时退回 F_TERM + _wrap_lower"。镜像里真有 25 处
        //     （_obj(Value,Weight).Value，run 层奖励池），这里合成一处来钉住行为。
        patch16(&mut probe, at, wrap_term);
        {
            let content = Content::parse(&probe).expect("解析");
            assert!(
                matches!(
                    NodeRef::new(&content, tid).field("Element"),
                    Err(IrError::WrongKind("F_TERM"))
                ),
                "包装标量不许被默默当成普通 term"
            );
        }

        // (d) 换成一个悬空 term id：报 Term(id)，不顺延。
        //     注意 `0xFFFF` 在这一格里是 **ABSENT16 哨兵**、不是 term id（换成它测的是缺席，
        //     不是悬空）；真正的悬空要用 `term_count` 之后的号。
        let past_end = {
            let content = Content::parse(&blob).expect("解析");
            u16::try_from(content.term_count()).expect("term_count 不超 u16")
        };
        patch16(&mut probe, at, past_end);
        {
            let content = Content::parse(&probe).expect("解析");
            assert!(matches!(
                NodeRef::new(&content, tid).field("Element"),
                Err(IrError::Term(id)) if id == past_end
            ));
        }
    }

    #[test]
    fn bool_absent_is_not_bool_false() {
        let mut blob = core_image();
        let (tid, at) = {
            let content = Content::parse(&blob).expect("真实镜像必须能解析");
            let root = root_of(&Ir::new(&content), 0);
            // IgnoresBlock 是 dealDamage 的第 4 个字段（Amount 1 + Children 2 + Element 1）。
            (root.id(), term_slot_offset(&content, root.id(), 4))
        };
        {
            let content = Content::parse(&blob).expect("真实镜像必须能解析");
            assert!(matches!(
                NodeRef::new(&content, tid).field("IgnoresBlock"),
                Ok(Some(Value::Bool(false)))
            ));
        }
        // 镜像里 BOOL_ABSENT(0) 一次都没出现（所有布尔都是 1/2）。改成 0 看行为。
        patch16(&mut blob, at, BOOL_ABSENT);
        let content = Content::parse(&blob).expect("解析");
        assert!(
            matches!(
                NodeRef::new(&content, tid).field("IgnoresBlock"),
                Ok(Some(Value::Absent))
            ),
            "BOOL_ABSENT 是 Absent，不是 Bool(false) —— 打包位域就区分不了这个"
        );
        assert_eq!(NodeRef::new(&content, tid).bool_field("IgnoresBlock"), Ok(None));
    }
}
