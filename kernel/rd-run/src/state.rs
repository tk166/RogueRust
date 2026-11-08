//! The run's state: where you are, what you carry, and the counters that decide what happens next.
//!
//! Frozen shape: `docs/spec/run-layer.md` §4. Two things about it are decisions rather than
//! transcription, and both are written down because they are the kind that becomes a hidden
//! assumption:
//!
//! 1. **It has no idea what content is.** Starting health, the starting deck, relic ids and potion
//!    ids all come from the content document, and this struct only stores what it is handed
//!    ([`RunState::new`] takes them as arguments). The alternative — teaching this crate to read a
//!    content image — would duplicate the content layer and give the run two places where a card's
//!    identity is decided.
//! 2. **Every capacity fails loudly.** `deck`, `relics` and `potions` are fixed arrays, and pushing
//!    past the end is [`RunError::Capacity`], never a dropped push. `run-layer.md` §4.4 spells out
//!    why: StS decks can exceed sixty cards in the late game, so the bound is a capacity and *not*
//!    a budget to be squeezed — it must only ever be visible as a red.
//!
//! Its size is checked against a **tripwire** (not a target) in
//! [`state_fits_the_tripwire`], for the same reason `CombatState` has one.

use rd_core::state::{Ident, ID_CAP};

use crate::map::{NodeKind, RunMap, NODES_PER_ROW, ROWS};
pub mod archive;

use crate::streams::{RunError, RunRng, RunStream};

/// §270：一件遗物的**第二半**。
///
/// [`RunState::relic_effect`] 只返回**一个**变体，而有两件遗物各自要做两件事：
///
/// | 遗物 | 第一半（在 `relic_effect` 里） | 第二半（在这张表里） |
/// |---|---|---|
/// | `busted_crown` | 每回合 +1 能量的载体 | 奖励卡数 -2 |
/// | `ectoplasm` | 不能再得到金币 | 每回合 +1 能量的载体 |
///
/// 两个消费者（[`RunState::combat_bonus_for`] / [`RunState::reward_card_count`]）各自挑自己认识的
/// 变体、忽略其余 —— 所以这张表**只有一处**，而不是"每个消费者一张"。
const RELIC_SECOND_HALVES: [(&str, RelicEffect); 4] = [
    ("busted_crown", RelicEffect::RewardCardDelta(-2, KindMask::ALL)),
    ("ectoplasm", RelicEffect::StartCombatStatus("standard.ectoplasm", 1)),
    // §271：`sozu` 的第一半是"不能再获得药水"（运行时判断），第二半是每回合 +1 能量。
    ("sozu", RelicEffect::StartCombatStatus("standard.sozu", 1)),
    // §273：`the_courier` 的第一半是 -20%（`ShopDiscountPercent`），第二半是"买完补货"。
    ("the_courier", RelicEffect::CourierRestock),
];

/// §269：一组"哪几类战斗"的位掩码（[`RelicEffect::StartCombatStatusInKinds`] 等使用）。
///
/// 用位而不是 `[bool; 3]`：遗物表里写成常量字面量（`NORMAL | ELITE`），读起来就是 wiki 那句话
/// （"精英与 Boss 战"）。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct KindMask(pub u8);

impl KindMask {
    pub const NORMAL: KindMask = KindMask(1);
    pub const ELITE: KindMask = KindMask(2);
    pub const BOSS: KindMask = KindMask(4);
    pub const ALL: KindMask = KindMask(7);

    /// 这张掩码是否覆盖 `kind`。
    #[must_use]
    pub const fn covers(self, kind: FightKind) -> bool {
        let bit = match kind {
            FightKind::Normal => 1,
            FightKind::Elite => 2,
            FightKind::Boss => 4,
        };
        self.0 & bit != 0
    }
}

/// The most cards a run's deck may hold. See the module docs: exceeding it is an error, never a
/// truncation.
pub const MAX_RUN_DECK: usize = 60;
/// The most relics a run may hold. `inv:§6` has 140 obtainable, but a single run sees on the order
/// of a dozen; **48** is "what a run needs", not "what a budget allows".
///
/// §260: it was **24**, and it was raised because the content passed it (30 relics, and the
/// "largest run" hash fixture pushes *every* relic in the image). A capacity that content growth
/// trips is fine -- it fails loudly (`Capacity`) instead of silently dropping a relic -- but 24 was
/// also too small for a real run (endgame runs hold 30+).
pub const MAX_RUN_RELICS: usize = 48;
/// The potion belt (`inv:§9.3`: hold at most 3).
/// How many acts a run has. Killing the boss of an act before the last one **advances**; killing the
/// last one wins the run.
pub const MAX_ACT: u8 = 3;

/// Belt **storage**: five slots, because `potion_belt` adds two (§157).
///
/// The *rule* is still "three slots" -- that is [`RunState::potion_slots`], and the difference between
/// storage and rule is what lets a relic raise the count without a second array.
pub const MAX_RUN_POTIONS: usize = 5;

/// The wiki's three starting potion slots (§157; Ascension 11 takes one away -- see
/// [`A_POTION_SLOT`]).
pub const BASE_POTION_SLOTS: u8 = 3;
/// `inv:§9.3`: a potion drops from 40% of fights (the act-1 reset value; the ±10% per act is not
/// modelled because there is one act).
/// The wiki's **starting** potion drop chance (§157). It moves: -10 after a drop, +10 after a
/// miss, reset at the start of each act. A flat 40% was wrong in the way that matters over a run.
pub const POTION_DROP_START: i32 = 40;

/// How much the chance moves per fight (`+10` on a miss, `-10` on a drop).
pub const POTION_DROP_STEP: i32 = 10;

/// `Burning Blood`: "At the end of combat, heal 6 HP" (`inv:§2`).
pub const BURNING_BLOOD_HEAL: i32 = 6;

// =============================================================================================
// Ascension (`port-plan.md` §159)
// =============================================================================================

/// The highest Ascension level the wiki defines (and the highest this build accepts).
pub const MAX_ASCENSION: u8 = 20;
/// 一局最多几幕（三幕 Boss 之后结束）。
pub const MAX_ACTS: u8 = 3;


/// The rule numbers, **named** so a call site reads as a rule instead of as a magic `>= 5`.
///
/// The wiki's list is cumulative: level N carries rules 1..=N. Eleven of the twenty have a rule
/// here; the nine that do not are listed in `port-plan.md` §159.6 with what each one needs, because
/// "Ascension up to 20" with eight silent no-ops would be exactly the kind of lie this project
/// keeps catching.
pub const A_BOSS_HEAL: u8 = 5;
/// Start each run damaged (lose 10% health).
pub const A_START_DAMAGED: u8 = 6;
/// Normal enemies are tougher (more max HP).
pub const A_NORMAL_HP: u8 = 7;
/// Elites are tougher.
pub const A_ELITE_HP: u8 = 8;
/// Bosses are tougher.
pub const A_BOSS_HP: u8 = 9;
/// One less potion slot.
pub const A_POTION_SLOT: u8 = 11;
/// Bosses drop 25% less gold.
pub const A_BOSS_GOLD: u8 = 13;
/// Lower max HP (`-5` for the Ironclad, which is the only character this content has).
pub const A_MAX_HP: u8 = 14;
/// The merchant charges 10% more.
pub const A_SHOP_PRICE: u8 = 16;
/// §188：事件变得更糟（wiki: *Unfavorable Events — many events have less positive outcomes
/// and more severe consequences*）。内容用 `Effects*Asc` 给出变体；没有变体的选项照旧。
pub const A_EVENTS_WORSE: u8 = 15;

// §280：`rd_core::run_expr::A15` 是同一个数的第二份（`rd-core` 不能依赖 `rd-run`）。
// `rd-wasm` 有一条判据钉住它们相等 —— 两个数字漂开会让"A15 的价目"与"A15 的条件"分家。
/// §189：精英更常见（wiki: *Elites are more common* — 8% → 16%）。
pub const A_ELITE_MORE: u8 = 1;
/// §189：开局带 Ascender's Bane（wiki: *Start with Ascender's Bane*）。
pub const A_START_CURSE: u8 = 10;
/// §189：升级牌更少（wiki: *Upgraded cards are less common*）—— 二三幕的升级概率减半。
pub const A_FEWER_UPGRADES: u8 = 12;
/// §189：第三幕两个 Boss（wiki: *Double Boss*）。
pub const A_DOUBLE_BOSS: u8 = 20;

/// A10 的诅咒。**不能被删** —— wiki 的卡面写着 "Cannot be removed"，而 StS 自己也是把这一条
/// 写在这张卡**自己**的代码里（它不是一个通用标签）。
pub const ASCENDERS_BANE: &str = "ascenders_bane";

/// `A14`: the Ironclad loses 5 maximum health (`-4` for the other three characters).
pub const ASCENDED_MAX_HEALTH_LOSS: i32 = 5;
/// `A6`: "lose 10% health at the start of each run" -- of the maximum, rounded down.
pub const ASCENDED_START_DAMAGE_PERCENT: i32 = 10;
/// `A7`/`A8`/`A9`: how much more max HP an enemy has.
///
/// ⚠️ **The wiki gives no number here**: it says "have more HP" and the real game hand-tunes each
/// monster's HP per ascension. A flat percentage is therefore our *model*, not StS's data. It lives
/// in one constant so that the day `ENCT` grows an ascension column, this constant is the only thing
/// to delete.
pub const ASCENDED_ENEMY_HEALTH_PERCENT: i32 = 10;
/// `A13`: bosses drop 25% less gold.
pub const ASCENDED_BOSS_GOLD_PERCENT: i32 = 75;
/// `A16`: "everything costs 10% more".
pub const ASCENDED_SHOP_PERCENT: i32 = 110;

/// What a relic does. **One table** (`RunState::relic_effect`) is the only place a relic's
/// behaviour is described, so "is this relic implemented?" and "what does this relic do?" cannot
/// disagree (`port-plan.md` §145).
///
/// The three hook points are modelled because they are the three the run layer can honour without
/// a program interpreter: **on grant** (a number changes once), **combat start** (the fight is
/// built by the caller, so the run hands out a bonus) and **combat end** (`end_of_combat`).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum RelicEffect {
    /// Heal this much when a fight ends, capped at the maximum. (`burning_blood`)
    EndOfCombatHeal(i32),
    /// Raise the maximum HP (and the current HP with it) **when the relic is granted**. (`pear`)
    MaxHealthUp(i32),
    /// Heal this much (capped at the maximum) **when the relic is granted**. (`blood_vial`)
    HealUp(i32),
    /// Start every fight with this much Block. (`anchor`)
    StartCombatBlock(i32),
    /// Start every fight with `stacks` of status `id`. (`vajra` = 1 Strength, `thread_and_needle`
    /// = 4 Plated Armor.)
    ///
    /// One generic arm instead of one per status: the run layer does not need to know what
    /// `standard.plated_armor` *means* -- the kernel does. A per-status arm here would be a second
    /// list to keep in step with the content.
    StartCombatStatus(&'static str, i32),
    /// §261: start every fight with `stacks` of status `id` **per Curse in the deck**
    /// (`du_vu_doll`: 1 Strength per Curse). The count comes from the content image, so it is
    /// resolved by the fight builder -- see [`CombatBonus::per_curse_statuses`].
    StartCombatStatusPerCurse(&'static str, i32),
    /// §269：**只在某几类战斗里**开战挂状态（`sling_of_courage`：精英战 +2 力量、
    /// `slavers_collar`：Boss/精英战每回合 +1 能量）。
    ///
    /// 为什么不是"再开一张表"：这条规则的两个参数（哪类战斗 + 哪条状态）都属于**运行层**
    /// （`FightKind` 是它自己的枚举），内容不知道"精英"是什么。
    StartCombatStatusInKinds(&'static str, i32, KindMask),
    /// §269：**只在某几类战斗里**开战治疗（`pantograph`：Boss 战回 25）。
    ///
    /// 上限由战斗构建方钳（血量是战斗状态的事），所以这里只给"想回多少"。
    StartCombatHealInKinds(i32, KindMask),
    /// §269：战斗奖励的**卡牌张数**修正（`question_card` +1、`busted_crown` -2、
    /// `prayer_wheel` 普通战 +1）。
    RewardCardDelta(i32, KindMask),
    /// §269：**药水必掉**（`white_beast_statue`）。
    PotionAlwaysDrops,
    /// §274：`old_coin` —— 拾取时 +300 金币。
    PickupGold(i32),
    /// §274：`lee's_waffle` —— 拾取时上限 +7、**回满血**。
    PickupMaxHealthAndHealAll(i32),
    /// §274：`war_paint`(Skill) / `whetstone`(Attack) —— 拾取时随机升级 2 张**该类型**的牌。
    PickupUpgradeRandom(CardKind, u8),
    /// §274：`pandoras_box` —— 拾取时把牌组里**所有** Strike / Defend 改造掉。
    PickupTransformStaples,
    /// §274：`astrolabe` —— 拾取时改造 3 张（玩家选），**然后**升级它们。
    PickupPick(DeckChange, u8),
    /// §273：`the_courier` —— 商人**补货**（买走一格就补一格）。
    CourierRestock,
    /// §272：`juzu_bracelet` —— `?` 房不再出**普通**战斗（wiki 原文：removes the 10% base chance）。
    NoUnknownMonster,
    /// §272：`tiny_chest` —— 每第 4 个 `?` 房是宝箱。
    TinyChestEveryFourth,
    /// §271：`meal_ticket` —— 进商店回 15 血。
    ShopEntryHeal(i32),
    /// §271：`ssserpent_head` —— 进 `?` 房 +50 金币。
    UnknownRoomGold(i32),
    /// §271：`ancient_tea_set` —— 进篝火 ⇒ **下一场**战斗开战 +`stacks` 能量（状态 id + 层数）。
    ///
    /// 带状态 id 而不是硬编码：能量是内容的事（`standard.ancient_tea_set` 的
    /// `TurnStarted` 触发器），运行层只负责"这一场要不要挂它"。
    RestEntryNextCombatEnergy(&'static str, i32),
    /// §271：`sozu` —— 不能再获得药水（第一半；"每回合 +1 能量"在 `RELIC_SECOND_HALVES`）。
    NoPotionGain,
    /// §271：`toy_ornithopter` —— 用一瓶药水回 5 血（血量在**战斗**里，所以这条只给数字，
    /// 由 `rd_env_use_potion` 在战斗员身上兑现）。
    PotionUseHeal(i32),
    /// §270：`omamori` —— 拾取时给 2 次"挡诅咒"。
    Omamori(u8),
    /// §270：`darkstone_periapt` —— 得到诅咒 ⇒ 上限 +6。
    CurseMaxHealthUp(i32),
    /// §270：`ceramic_fish` —— 每加一张牌 +9 金币。
    CardAddGold(i32),
    /// §270：`molten_egg`(Attack) / `toxic_egg`(Skill) / `frozen_egg`(Power) ——
    /// 加这个类型的牌时换成 `+` 行。
    UpgradeAddedCard(CardKind),
    /// §270：`bloody_idol` —— 每次**得到**金币回 5 血。
    GoldGainHeal(i32),
    /// §270：`ectoplasm` —— 不能再得到金币（正增量一律变 0）。
    NoGoldGain,
    /// §270：`maw_bank` —— 每爬一层 +12 金币；在商店花过钱之后失效。
    FloorClimbGold(i32),
    /// §270：`smiling_mask` —— 删牌服务**固定** 50 金币。
    RemovePriceFlat(i32),
    /// §270：`membership_card` —— 所有商品打折 `percent`（50 = 半价）。
    ShopDiscountPercent(i32),
    /// §269：精英战敌人血量百分比修正（`preserved_insect`：-25）。与升阶的
    /// `enemy_health_bonus_percent` 走**同一条通道**，所以两个修正自动叠加。
    EliteEnemyHealthPercent(i32),

    /// §269：精英多掉一件遗物（`black_star`）。
    ///
    /// ⚠️ 这件**直接塞进包**而不是进奖励屏：奖励屏只有一个遗物槽（`Reward::relic`），
    /// 加第二个槽要改 ABI 与页面。写在这里是为了让偏差**可查**，而不是让它悄悄消失。
    EliteExtraRelic,
    /// Resting heals this much more (`regal_pillow`, wiki: +15).
    RestHealBonus(i32),
    /// Heal `amount` at the end of a fight **only when HP is at or below `percent` of maximum**
    /// (`meat_on_the_bone`, wiki: 12 HP at or below 50%).
    EndOfCombatHealIfBelow { percent: i32, amount: i32 },
    /// Resting also heals `amount` per **five cards** in the deck (`eternal_feather`, wiki: 3 HP).
    RestHealPerFiveCards(i32),
    /// Fight gold is multiplied by `100 + percent` (`golden_idol`, wiki: +25%).
    FightGoldPercent(i32),
    /// Extra potion slots (`potion_belt`, wiki: +2). The wiki calls it the **only** way to raise the
    /// three slots, which is why the slot count is a method and not the array length (§157).
    ExtraPotionSlots(i32),
    /// §224: start every fight with `stacks` of status `id` on **all enemies** (`bag_of_marbles`:
    /// "At the start of each combat, apply 1 Vulnerable to ALL enemies").
    ///
    /// A separate variant rather than a `Target` on [`Self::StartCombatStatus`]: the two land on
    /// different combatants and are applied by different code, and §222 already proved what happens
    /// when the hero-shaped one is reused ("the hero became Vulnerable and the boss was
    /// unwinnable" -- caught by `ACT1_SLICE`, not by any unit test).
    StartCombatStatusOnEnemies(&'static str, i32),
    /// §259: this relic **adds** a rest-site option (`girya` → Lift, `peace_pipe` → Toke,
    /// `shovel` → Dig).
    ///
    /// One variant per option instead of `CampfireOption(u8)` with a bit: the option list is a
    /// closed set of six (Rest/Smith/Recall/Lift/Toke/Dig), and a bit field would let a typo pick
    /// the wrong bit silently. `campfire_options` matches on these three by name.
    CampfireLift,
    /// See [`Self::CampfireLift`].
    CampfireToke,
    /// See [`Self::CampfireLift`].
    CampfireDig,
    /// §259: this relic **removes** Rest (`coffee_dripper`, `mark_of_the_bloom`).
    NoRest,
    /// §259: this relic **removes** Smith (`fusion_hammer`).
    NoSmith,
    /// §259: resting also pays a card reward (`dream_catcher`).
    RestCardReward,
}

/// §259：篝火上有哪些选项（`RunState::campfire_options`）。
///
/// 六个布尔字段而不是位域：位域会让"选错一位"变成"另一个选项静默可用"，而这里是**界面唯一**
/// 的信息来源（页面按这些布尔渲染按钮），错了一位就是一个永远点不亮的按钮。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct CampfireOptions {
    /// 回 30% 最大生命（`Coffee Dripper` / `Mark of the Bloom` 关闭它；**满血也能用**）。
    pub rest: bool,
    /// 升级一张牌（`Fusion Hammer` 或全升完关闭它）。
    pub smith: bool,
    /// 拿红钥匙（拿到之后关闭）。
    pub recall: bool,
    /// `Girya`：力量 +1（最多 3 次）。
    pub lift: bool,
    /// `Peace Pipe`：删一张牌。
    pub toke: bool,
    /// `Shovel`：拿一件随机遗物（只 Common/Uncommon/Rare）。
    pub dig: bool,
}

/// `CombatBonus` 最多能带几种"开战时给的状态"（遗物数量远小于它）。
pub const MAX_COMBAT_STATUSES: usize = 4;

/// 开战时挂到英雄身上的一条状态。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct CombatStatus {
    /// 状态定义 id（内容的 `STAT` 行）。
    pub id: &'static str,
    /// 层数。
    pub stacks: i32,
}

/// What the relics do **at the start of a fight**.
///
/// A struct and not a list of effects, because the caller (the fight builder) has to apply them in
/// one place: "which relics fire" is the run's answer, "how a status is applied" is the kernel's.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct CombatBonus {
    /// Block the hero starts the fight with.
    pub block: i32,
    /// Statuses the hero starts the fight with (Strength from Vajra, Plated Armor from Thread and
    /// Needle, ...).
    ///
    /// A list rather than named fields: the run layer must not grow a field per status it happens
    /// to know about — `standard.vajra`-style relics are content, and content grows.
    pub statuses: [Option<CombatStatus>; MAX_COMBAT_STATUSES],
    /// How many of [`Self::statuses`] are set.
    pub status_count: usize,
    /// §224: statuses **the enemies** start the fight with (`bag_of_marbles` = 1 Vulnerable each).
    ///
    /// A second list instead of a `Target` field on [`CombatStatus`]: hero statuses and enemy
    /// statuses are applied by two different pieces of code (one combatant vs "every enemy slot"),
    /// and a target field would make every existing reader ask a question with exactly two answers.
    pub enemy_statuses: [Option<CombatStatus>; MAX_COMBAT_STATUSES],
    /// How many of [`Self::enemy_statuses`] are set.
    pub enemy_status_count: usize,
    /// §261: statuses whose stacks are a **count over the deck** rather than a number
    /// (`du_vu_doll`: 1 Strength per Curse). `stacks` here is the amount **per qualifying card**.
    ///
    /// A third list, for the same reason the second exists: the number is not the run layer's to
    /// compute. "Which cards are Curses" is a content question
    /// (`Content::card_has_tag(id, "curse")`), and `rd-run` deliberately reads no content -- it must
    /// work with only the image's *ids*. So the run says **what** (this status, this much per
    /// curse) and the fight builder, which owns the image, does the counting.
    pub per_curse_statuses: [Option<CombatStatus>; MAX_COMBAT_STATUSES],
    /// How many of [`Self::per_curse_statuses`] are set.
    pub per_curse_status_count: usize,
    /// §269：开战时**先回这么多血**（`pantograph`：Boss 战 +25）。上限由战斗构建方钳
    /// （血量归战斗状态管，运行层只表达"想回多少"）。
    pub start_heal: i32,
}

impl Default for CombatBonus {
    fn default() -> Self {
        Self {
            block: 0,
            statuses: [None; MAX_COMBAT_STATUSES],
            status_count: 0,
            enemy_statuses: [None; MAX_COMBAT_STATUSES],
            enemy_status_count: 0,
            per_curse_statuses: [None; MAX_COMBAT_STATUSES],
            per_curse_status_count: 0,
            start_heal: 0,
        }
    }
}

impl CombatBonus {
    /// True when nothing about this fight is different from a bare one — the common case, and the
    /// one the caller can skip every write for.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        // ⚠️ `enemy_status_count` 必须在这条里 —— 漏了它，"只给敌人挂状态"的遗物会被
        // `apply_combat_bonus` 的早退当成"这场战斗没有加成"，**静默不生效**。
        self.block == 0
            && self.status_count == 0
            && self.enemy_status_count == 0
            && self.per_curse_status_count == 0
            && self.start_heal == 0
    }

    /// Add `stacks` of status `id`. `false` = the list is full (a **loud** failure: the caller must
    /// not silently drop a relic's effect).
    pub fn push_status(&mut self, id: &'static str, stacks: i32) -> bool {
        if self.status_count >= MAX_COMBAT_STATUSES {
            return false;
        }
        self.statuses[self.status_count] = Some(CombatStatus { id, stacks });
        self.status_count += 1;
        true
    }

    /// §261：同 [`Self::push_status`]，但层数是"每张诅咒多少"（`du_vu_doll`）。
    /// `false` = 表满（响亮，不静默丢一件遗物）。
    pub fn push_per_curse_status(&mut self, id: &'static str, stacks: i32) -> bool {
        if self.per_curse_status_count >= MAX_COMBAT_STATUSES {
            return false;
        }
        self.per_curse_statuses[self.per_curse_status_count] = Some(CombatStatus { id, stacks });
        self.per_curse_status_count += 1;
        true
    }

    /// §224：同 [`Self::push_status`]，但**给敌人**。`false` = 表满（响亮，不静默丢一件遗物）。
    pub fn push_enemy_status(&mut self, id: &'static str, stacks: i32) -> bool {
        if self.enemy_status_count >= MAX_COMBAT_STATUSES {
            return false;
        }
        self.enemy_statuses[self.enemy_status_count] = Some(CombatStatus { id, stacks });
        self.enemy_status_count += 1;
        true
    }
}

/// Card slots a merchant shows (`inv:§8.2`: five coloured cards; the two colourless ones are not
/// modelled -- this content has no colourless pool).
pub const MAX_SHOP_CARDS: usize = 5;
/// Relic slots a merchant shows (`inv:§8.2`: three).
pub const MAX_SHOP_RELICS: usize = 3;
/// What a card costs by rarity (`inv:§8.2`): Common 45–55, Uncommon 68–82, Rare 135–165.
///
/// `Basic` / `Status` / `Curse` are not things a merchant sells; if one reaches the shelf it is
/// priced in the Common band, which is the closest thing to a documented answer.
#[must_use]
pub const fn card_price_band(rarity: Rarity) -> (i32, i32) {
    match rarity {
        // §160: `Event` joins this band for the same reason -- it is a **relic** rarity that no
        // card can carry, so reaching here at all means something upstream is confused. The Common
        // band is the "somebody has to get a number" answer, and a card is never Event.
        // §218: `Special` 是"事件专属的牌"（`apparition`）。商人**不卖**它 —— 真走到这里说明
        // 上游把一张事件牌放上了货架，那是内容/池子的错；与 `Event` 一样给 Common 价（"总得有个
        // 数字"），由调用方去挡。
        Rarity::Common
        | Rarity::Basic
        | Rarity::Status
        | Rarity::Curse
        | Rarity::Event
        | Rarity::Special
        // §259: `Starter`/`Boss` 是**遗物**的桶，牌不可能带着它 —— 与 `Event` 同一条理由：
        // 走到这里说明上游把遗物的稀有度用在了牌上，给 Common 价、由调用方去挡。
        | Rarity::Starter
        | Rarity::Boss => (45, 55),
        Rarity::Uncommon => (68, 82),
        Rarity::Rare => (135, 165),
    }
}

/// Card-removal price the first time (`inv:§8.2`).
pub const SHOP_REMOVE_BASE: i32 = 75;
/// ...and how much it grows per use, across shops in the same run (`inv:§8.2`).
/// §270：`omamori` 能给几次"挡诅咒"（wiki："Negate the next 2 Curses"）。
pub const OMAMORI_CHARGES: u8 = 2;

/// §270：`smiling_mask` 之后删牌服务的**固定**价格（wiki："always costs 50 Gold"）。
pub const SHOP_REMOVE_FLAT: i32 = 50;
pub const SHOP_REMOVE_STEP: i32 = 25;
/// `inv:§8.1`: a rest site heals 30% of maximum HP, rounded down.
pub const REST_HEAL_PERCENT: i32 = 30;

/// §259：`Girya` 的 `Lift` 最多用 3 次（wiki：`Lift` up to 3 times）。
///
/// 它是**容量**也是**语义**：存档读到 4 不是夹到 3，而是存档坏了（`ArchiveError::BadField`）。
/// 用满之后选项从 `campfire_options()` 里消失。
pub const GIRYA_MAX_LIFTS: u8 = 3;
/// `inv:§3.5`: a reward screen shows three cards, all different.
pub const MAX_REWARD_CARDS: usize = 4;
/// §269：**一屏默认给几张**（`inv:§3.5` 的三张）。与 [`MAX_REWARD_CARDS`]（**存储**上限）分开：
/// `question_card` 让一屏变 4 张，而"存储 4"与"默认给 3"是两个数 —— 混成一个的话，
/// 加一张牌就要动所有下标。
pub const BASE_REWARD_CARDS: usize = 3;
/// `inv:§5`: a normal fight pays 10–20 gold (elite 25–35, boss 95–105).
pub const NORMAL_FIGHT_GOLD: (i32, i32) = (10, 20);
/// `inv:§3.5`: the pity offset starts at −5%, ticks +1% per non-rare roll, resets on a rare.
pub const RARITY_OFFSET_START: i32 = -5;
/// ...and its ceiling.
pub const RARITY_OFFSET_CAP: i32 = 40;
/// The pools a shop or a chest draws from are caller-supplied (this crate knows no content), so the
/// walk below needs a bound. Exceeding it is [`RunError::EmptyPool`]'s sibling: a loud error.
/// 一个奖励/商店/宝箱池最多装多少条。
///
/// ⚠️ §221：这个数从 64 抬到 96，**理由是内容量，不是"躲开一条红测试"**。铁匠铺的池是
/// `full_pool(content)`：全部 `CARD` 行（基础 + `+` 升级行 + 状态/诅咒牌，因为升级要找得到目标、
/// 而"哪些能当奖励"由 `pick_of` 按稀有度过滤）。§221 加了 10 张牌（+10 个 `+` 行）之后是 **68 行**，
/// 于是 `PoolTooLarge { pool: 68, max: 64 }` —— 一个**走真实地图**的回放测试当场拒绝。
///
/// 为什么是 96 而不是"再大一点"：牌区的单区上限就是 96（`MAX_CARDS_PER_ZONE`），一个池子不该
/// 比"能装下这些牌的牌区"更大；而 `u8` 编码（`as u8`）在 256 以下都安全。
/// 内容继续长到超过 96 的那天，这条常量要跟着内容一起被重新论证 —— `pool_fits` 会**响亮拒绝**，
/// 而不是静默截断（§161.1 的教训：截断会让"池子看起来装得下"）。
///
/// §229：**那一天到了**。`Searing Blow` 的 "Can be Upgraded any number of times" 在本内容里是
/// "内容把行写够"（`searing_blow` / `+` / `++` … 共 8 行），于是 `CARD` 表到了 **101 行**，
/// 一条真实走图的回放当场被 `PoolTooLarge { pool: 101, max: 96 }` 拒绝。
///
/// §232 内容到 115 行时又抬了一次（112 → 128），理由同上：这条常量跟的是**目录行数**。
/// §235 到 145 行时第三次抬（128 → 160）；§237 到 165 行时第四次抬（160 → 192）；
/// §243 到 209 行时第五次抬（192 → 224）；§244 到 229 行时第六次抬（224 → 256）。
///
/// ⚠️ **五次都是"内容一变就红"**，说明形状确实不对。真正的杠杆仍是"让池子变成调用方给的切片"
/// （`&[PoolCard]` + `pool_fits` 校验）。本轮仍只抬数并记下 —— 但下一次因它报红时，
/// 应该做那个重构，而不是再抬一次。
///
/// ⚠️ **这个常量每加一批牌就要抬一次，说明形状不对**。真正的杠杆不是继续放大数字，而是让池子
/// 变成**调用方给的切片**（`&[PoolCard]`），由 `pool_fits` 做长度校验 —— 那样 `rd-run` 里那些
/// `[_; MAX_POOL]` 的定长缓冲会一起消失。这一轮只抬数并在 §235 记下，留作"内容再长一批就做"的
/// 重构项（它不影响正确性：超限是 `PoolTooLarge` 的**响亮**拒绝，不是截断）。
/// 抬到 112 而不是 128：上面那条"池子不该比牌区大"的推理错在**把池子当牌区**——这个池子是
/// **目录**（基础行 + `+` 行 + 状态/诅咒牌），它不装在同一张牌区里，`u8` 也只是编码而不是语义。
/// 真实约束是两条：`>= 内容行数`（`pool_fits` 会红，不许截断），以及"离 u8 远得很"。
/// §251：**加牌就要加池子上限，这是正常需求**（内容 277 行 → 320）。
///
/// 早先几版把每次抬数写成"欠一次 `&[PoolCard]` 重构"。那个说法已经撤销：池子是**目录**，
/// 它的容量本来就该跟着内容走，而"超限"这条路是 `pool_fits` 的**响亮拒绝**（不是截断），
/// 所以抬数不改变任何语义，也不欠任何东西。真约束只有两条：`>= 内容行数`，以及"离 `u8` 远得很"。
pub const MAX_POOL: usize = 320;

/// §272：`?` 房的结果（wiki `Unknown Location`）。
///
/// 结果是**运行期状态**：`Event` 由调用方去开事件、`Monster` 由调用方开一场普通战斗，
/// 而 `Shop` / `Treasure` 在 `begin_node` 里当场变成 `Pending::Shop` / `Pending::Chest`。
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
#[repr(u8)]
pub enum UnknownRoom {
    /// 还没掷过（一个 `?` 房在 `begin_node` 之前）。
    #[default]
    Unresolved = 0,
    /// 一个事件（`begin_event`，`inv:§7.3`）。
    Event = 1,
    /// 一场**普通**战斗（用本幕的 `Weak*` 池，与战斗节点同一条路）。
    Monster = 2,
    /// 商人（当场摆货架）。
    Shop = 3,
    /// 宝箱（`Pending::Chest`）。
    Treasure = 4,
}

/// §274：`pandoras_box` 认的两个"基础牌" id（内容的命名，不是运行层编的规则）。
pub const STAPLE_STRIKE: &str = "strike";
pub const STAPLE_DEFEND: &str = "defend";

/// §272：`?` 房三条基础概率（wiki 的 10 / 3 / 2，单位 percent）。
pub const UNKNOWN_MONSTER_BASE: i32 = 10;
pub const UNKNOWN_SHOP_BASE: i32 = 3;
pub const UNKNOWN_TREASURE_BASE: i32 = 2;

/// §272：`tiny_chest` —— 每到第几个 `?` 房强制宝箱（wiki："Every 4th ? room"）。
pub const TINY_CHEST_ROOMS: u8 = 4;

/// What the node under the cursor is waiting for.
///
/// A node is not settled by walking onto it (`env-abi.md` §11.5): walking sets the cursor, and
/// [`RunState::begin_node`] declares what the node then needs. Keeping the two apart is what lets
/// the map page walk a whole Act without pretending a fight happened.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
#[repr(u8)]
pub enum Pending {
    /// Nothing to settle: a fight the caller is running, or a node already dealt with.
    #[default]
    None = 0,
    /// [`RunState::rest`] or [`RunState::smith`].
    Rest = 1,
    /// [`RunState::buy_card`] / [`RunState::buy_relic`] / [`RunState::remove_card`] / [`RunState::leave`].
    Shop = 2,
    /// [`RunState::open_chest`].
    Chest = 3,
    /// [`RunState::take_card`] or [`RunState::skip_reward`] -- the screen after a won fight.
    Reward = 4,
    /// [`RunState::resolve_event`] -- a `?` room, waiting for a choice.
    Event = 5,
    /// [`RunState::choose_start`] -- the pre-run blessing, before floor 1.
    Start = 6,
    /// [`RunState::pick_blessing_card`] -- a blessing that needs a deck index.
    BlessingCard = 7,
    /// [`RunState::pick_event_card`] -- an **event** choice that needs a deck index (§143).
    ///
    /// Its own variant rather than a flag on `BlessingCard`: the two are finished by two different
    /// calls, and a shared variant would make "which picker is this?" a condition inside both.
    EventCard = 8,
}

/// The pre-run choice (StS's Neow, `inv:§7.1`): the player picks one blessing from a rolled pair.
///
/// A blessing is a **gain and a cost**, both from [`EventEffect`]'s closed vocabulary -- that is how
/// "swap 10% of your max HP for 100 gold" is expressible without a program interpreter.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct StartOffer {
    /// The id (`max_hp`, `gold`, ...), for the UI and for the run hash.
    pub id: &'static str,
    /// Whether the blessing needs a card pick after it is taken.
    pub follow_up: BlessingFollowUp,
    /// What the player gets.
    pub gain: EventEffect,
    /// What it costs. [`EventEffect::Nothing`] for the free blessings.
    pub cost: EventEffect,
}

/// Neow's pool for act 1. Four entries so a pair is always available and distinct.
///
/// ⚠️ **This is not the wiki's pool**: StS draws from eight or so blessings with rarity weights.
/// Four, unweighted, is what this content can honour -- recorded in `inv:§7.1` rather than implied.
/// What a blessing still needs after it is picked. `None` finishes immediately; the other two need
/// a **deck index**, which is why they leave the run in `Pending::BlessingCard`.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum BlessingFollowUp {
    /// Nothing: the gain and the cost were the whole blessing.
    None,
    /// A deck card has to be named (remove / upgrade / transform).
    Deck(DeckChange),
    /// Add three random cards, no pick needed -- it is finished the moment it is taken.
    GainThreeCards,
}

/// A deck edit that needs the player to **name a card**.
///
/// One enum for both callers (the pre-run blessing and the `?`-room events, `port-plan.md` §143):
/// before this there was one enum (`BlessingFollowUp`) and the "upgrade a card" logic lived inline
/// in `pick_blessing_card`, which meant the event path would have grown a **second copy** of it.
/// Two copies of "append a `+`" is exactly how `strike+` and `strike` end up meaning different
/// things in two places.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum DeckChange {
    /// Take the card out of the deck.
    Remove,
    /// Add `+` (idempotent: an already-upgraded card is left alone).
    Upgrade,
    /// Remove it and grant a random card from the pool.
    Transform,
    /// §274：`astrolabe` —— 改造，**然后**升级改造出来的那张（wiki："Transform 3 cards, then
    /// Upgrade them"）。一个变体而不是"两次编辑"：两次编辑之间那张牌可能已经不在原位。
    TransformAndUpgrade,
}

impl DeckChange {
    /// The three values, for `PartialEq`-driven UI code and for tests that want to enumerate.
    pub const ALL: [Self; 3] = [Self::Remove, Self::Upgrade, Self::Transform];
}

pub const START_OFFERS: [StartOffer; 8] = [
    StartOffer {
        id: "max_hp",
        gain: EventEffect::GainMaxHealth(8),
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::None,
    },
    StartOffer {
        id: "gold",
        gain: EventEffect::Gold(100),
        cost: EventEffect::LoseHealth(7),
        follow_up: BlessingFollowUp::None,
    },
    StartOffer {
        id: "heal",
        gain: EventEffect::Heal(25),
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::None,
    },
    StartOffer {
        id: "blood_money",
        gain: EventEffect::Gold(150),
        cost: EventEffect::LoseHealth(14),
        follow_up: BlessingFollowUp::None,
    },
    // The two blessings that are about the deck rather than a number (wiki `Neow`).
    StartOffer {
        id: "remove_card",
        gain: EventEffect::Nothing,
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::Deck(DeckChange::Remove),
    },
    StartOffer {
        id: "upgrade_card",
        gain: EventEffect::Nothing,
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::Deck(DeckChange::Upgrade),
    },
    StartOffer {
        id: "transform_card",
        gain: EventEffect::Nothing,
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::Deck(DeckChange::Transform),
    },
    StartOffer {
        id: "three_cards",
        gain: EventEffect::Nothing,
        cost: EventEffect::Nothing,
        follow_up: BlessingFollowUp::GainThreeCards,
    },
];

/// What an event's choice does. The vocabulary is **closed** and comes from the content
/// (`EV.Effect0` / `EV.Effect1`); anything else is [`RunError::UnsupportedEventEffect`].
///
/// # The vocabulary（`port-plan.md` §143）
///
/// | content says | means |
/// |---|---|
/// | `heal` / `gold` / `damage` / `max_hp` / `nothing` + `AmountN` | the five number effects |
/// | `remove_card` / `upgrade_card` / `transform_card` | a deck edit: the run enters [`Pending::EventCard`] and waits for an index |
/// | `damage_pct:<n>` | lose `floor(max HP × n / 100)` HP (the wiki's *Smash*, A15 rides in the `...Asc` list) |
/// | `max_hp_pct:<n>` | lose `max(1, floor(max HP × n / 100))` **max** HP (the wiki's *Hide*) |
/// | `gold_cost:<n>` | **pay** `n` gold; refused when short (the wiki's *Cleric*) |
/// | `gold_random:<min>:<max>` | gain `runif(min, max)` gold (the Goop's "lose 20-50 Gold") |
/// | `fight_gold_bonus` | the **next** fight pays `Amount` extra gold (`Dead Adventurer`'s 30) |
/// | `fight_no_relic` | the **next** fight pays no relic (that search already found one) |
/// | `relic_random` | grant a **random** relic (Scrap Ooze). 运行层只认 `relic:<id>` —— 抽样由
///   **有内容池的那一层**（`rd-wasm`）先解析成具体 id，理由同 `curse:` 的载荷 |
/// | `heal_pct:<n>` | heal `floor(max HP × n / 100)` HP (the Cleric's *Heal*) |
/// | `heal_full` | heal to the maximum (the Moai Head's *Jump Inside*) |
///
/// ⚠️ `damage_pct` / `max_hp_pct` / `heal_pct` 的 `<n>` **允许一位小数**（`12.5`），内部按
/// **千分**存。原因：真内容里就有 12.5%（`The Moai Head` 的 Jump Inside），而整数百分比
/// 表达不了它 —— 而"四舍五入到 12%"是**另一个规则**，不是同一个规则的近似。
/// | `curse:<card id>` | add that card to the deck (the id must be in the pool) |
/// | `relic:<relic id>` | grant that relic (the id must have an implemented effect) |
/// | `relic_lose:<relic id>` | **drop** that relic (the id must be held — the wiki's `Forgotten Altar` exchange) |
///
/// The two `kind:payload` forms ride in the **same string column** as the bare keywords on
/// purpose: widening the `EV` row would move a stride that is hand-copied into four readers
/// (`content.rs`'s `EV_SCHEMA`, the writer, `rdcf_verify` and the content gate), and a stride that
/// drifts is a *silent misread*. A payload that fails to parse is loud instead: the effect falls
/// outside the vocabulary and the run refuses it.
///
/// `GainCurse` / `GainRelic` carry no payload of their own — the id travels beside the effect
/// (`resolve_event`'s `named` argument), which keeps this enum `Copy` and usable in the
/// `START_OFFERS` constant table.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum EventEffect {
    /// Restore HP, capped at the maximum.
    Heal(i32),
    /// Add gold.
    Gold(i32),
    /// Lose HP -- an event can hurt.
    LoseHealth(i32),
    /// §278：按**最大 HP 的千分比**掉血（`damage_pct`）。`Golden Idol` 的 Smash 25%（A15 35%）。
    ///
    /// §280 起单位是**千分**（`250` = 25%），因为真内容里有 12.5%。
    LoseHealthPercent(i32),
    /// §278：按**最大 HP 的千分比**扣上限（`max_hp_pct`）。`Golden Idol` 的 Hide 8%（A15 10%）。
    LoseMaxHealthPercent(i32),
    /// §280：**付** `n` 金币（`gold_cost`）。不够就拒绝 —— 不是"扣到 0 为止"。
    GoldCost(i32),
    /// §287：**下一场战斗**多付 `n` 金币（`Dead Adventurer` 的"30 金币还没搜到"）。
    FightGoldBonus(i32),
    /// §287：**下一场战斗**不掉遗物（那一件已经在搜索里拿到过了）。
    FightNoRelic,
    /// §285：**随机一件遗物**（`relic_random`）。运行层**不**抽 —— 它没有遗物池。
    /// 由 `rd-wasm` 在调用前解析成 `GainRelic` + 具体 id（与 `curse:`/`relic:` 的载荷同一条路）。
    GainRandomRelic,
    /// §285：**区间金币**（`gold_random:<min>:<max>`）。负区间 = 扣钱，而
    /// `adjust_gold` 会把结果夹在 0（正好是 wiki 那句 "never more than the Gold you are
    /// carrying"），所以 `[Leave It]` 掉 20-50 金币不需要第二套规则。
    GoldRandom(i32, i32),
    /// §280：按**最大 HP 的千分比**回血（`heal_pct`）。`The Cleric` 的 Heal 25%。
    HealPercent(i32),
    /// §280：回满血（`heal_full`）。`The Moai Head` 的 Jump Inside。
    HealFull,
    /// Raise the maximum, and the current HP with it.
    GainMaxHealth(i32),
    /// Nothing at all -- a real, declared choice, not a missing one.
    Nothing,
    /// Take a named card out of the deck.
    RemoveCard,
    /// Upgrade a named deck card.
    UpgradeCard,
    /// Replace a named deck card with a random one.
    TransformCard,
    /// Add the card named beside this effect (a curse, in practice).
    GainCurse,
    /// Grant the relic named beside this effect.
    GainRelic,
    /// §279：**失去**旁边那件遗物（`relic_lose:<id>`）。`Forgotten Altar` 的
    /// `[Offer: Golden Idol]` 就是"失去金像、得到血像"。
    LoseRelic,
}

/// §280：`floor(base × tenths / 1000)`，用整数算（内核不碰浮点）。
///
/// 参数是**千分比**（`250` = 25%，`125` = 12.5%）。§278 时它是百分比；改成千分是因为真内容
/// 里就有 12.5%（`The Moai Head`）。名字一起改了 —— 留着 `percent_of` 而语义变成千分，
/// 是那种"看着对、算出来差十倍"的错。
fn permille_of(base: i32, tenths: i32) -> i32 {
    base.saturating_mul(tenths) / 1000
}

/// §280：把 `"25"` / `"12.5"` 这样的**百分字符串**解成千分值（`250` / `125`）。
///
/// 只接受：1..=100 的百分比、可选**一位**小数、没有符号。`None` = 词表外（调用方拒绝）。
/// 为什么不用 `f32`：内核 `no_std` 里不碰浮点（这条纪律让"同一个内容在任何平台算出同一个数"
/// 是**结构上**成立的，而不是靠约定）。
fn parse_permille(text: &str) -> Option<i32> {
    let (whole, fraction) = match text.split_once('.') {
        Some((whole, fraction)) => (whole, Some(fraction)),
        None => (text, None),
    };
    if whole.is_empty() || whole.len() > 2 {
        return None;
    }
    let whole: i32 = whole.parse().ok()?;
    let tenths = match fraction {
        None => 0,
        Some(fraction) => {
            // 恰好一位小数；`12.50` 与 `12.` 都是词表外（它们表达同一件事的不同拼法，
            // 而两套拼法迟早会有一处被忘掉）。
            if fraction.len() != 1 {
                return None;
            }
            fraction.parse::<i32>().ok()?
        }
    };
    if !(1..=100).contains(&whole) {
        return None;
    }
    if whole == 100 && tenths > 0 {
        return None;
    }
    let total = whole.checked_mul(10)?.checked_add(tenths)?;
    Some(total)
}

/// §286：**一次事件选择**的完整形状。传进 [`RunState::resolve_event_effects`]。
///
/// 五样东西各有名字，因为有两个是同样的切片类型（`effects` 与 `entry`），位置参数会让
/// "谁是谁"变成读代码时的猜谜。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventMove<'a> {
    /// 这一段**选项自己的**效果，按顺序应用（§188）。
    pub effects: &'a [(EventEffect, Option<&'a str>)],
    /// 不掷骰时要去的那一段（空 = 这个选项是终点）。
    pub next: Option<&'a str>,
    /// §286：**权重分支** —— `(权重, 目标段)`，权重和 = 100。空 = 不掷骰。
    ///
    /// 比 §285 的 `Chance`/`NextFail` 更宽：`Dead Adventurer` 的一次搜索是四选一。
    pub branches: &'a [(u8, &'a str)],
    /// §286：**目标段的进入效果** —— `(段 id, 效果列表)`。运行层只按最终落点查一次。
    /// 有了它，"赢了赌注"就在**到达**结果屏时兑现，不必再让玩家点一次 `[Leave]`。
    pub entry: &'a [(&'a str, &'a [(EventEffect, Option<&'a str>)])],
    /// §286：这个选项是**一场战斗**。`0` = 不是，`1` = 普通，`2` = 精英。
    ///
    /// 选了它事件就收尾：房间由那一场战斗结算（`event_fight` 记住档位，`fight_end` 才
    /// `mark_resolved`）。这样"节点只付一次"仍然成立 —— 反复按"开打"不会刷出第二场。
    pub fight: u8,
    /// §287：这一场战斗用哪个遭遇池（空 = 按档位用本幕标准池）。
    pub fight_pool: &'a str,
}

impl<'a> EventMove<'a> {
    /// 什么都不做的一次选择（绝大多数的测试与"只收尾"的选项）。
    #[must_use]
    pub const fn none() -> EventMove<'static> {
        EventMove {
            effects: &[],
            next: None,
            branches: &[],
            entry: &[],
            fight: 0,
            fight_pool: "",
        }
    }

    /// 只带一个后继段的一次选择。
    #[must_use]
    pub const fn to(next: &'a str) -> EventMove<'a> {
        EventMove {
            next: Some(next),
            ..EventMove::none()
        }
    }
}

impl EventEffect {
    /// Parse the content's closed vocabulary. `None` = **outside** it, and the caller must refuse
    /// rather than guess (see the table on [`Self`]).
    ///
    /// The returned `&str` is the payload (`curse:regret` → `"regret"`), borrowed from `text`.
    #[must_use]
    pub fn parse(text: &str, amount: i32) -> Option<(Self, Option<&str>)> {
        Some(match text {
            "heal" => (Self::Heal(amount), None),
            "gold" => (Self::Gold(amount), None),
            "damage" => (Self::LoseHealth(amount), None),
            "max_hp" => (Self::GainMaxHealth(amount), None),
            "nothing" => (Self::Nothing, None),
            // §287：**下一场战斗**的奖励修正（`Dead Adventurer` 的战后补偿）。
            // 为什么是"欠账"而不是当场给：wiki 说这些奖励由**那场战斗**补发。
            "fight_gold_bonus" => (Self::FightGoldBonus(amount), None),
            "fight_no_relic" => (Self::FightNoRelic, None),
            // §285/§286：`relic_random` **没有载荷**（抽哪件由内容池 + 稀有度权重决定，那在
            // `rd-wasm` 手里）。⚠️ 它必须在**裸词**这一支：写进下面 `split_once(':')` 那一支
            // 会让它永远解析不出来（没有冒号 ⇒ `?` 直接 `None`）—— §285 真踩了这个坑，
            // 由 §286 的"事件中途开战斗"走图判据抓到（页面只是少一个按钮，没人报错）。
            "relic_random" => (Self::GainRandomRelic, None),
            // §280：`The Moai Head` 的 `[Jump Inside]`："Heal to full HP".
            "heal_full" => (Self::HealFull, None),
            "remove_card" => (Self::RemoveCard, None),
            "upgrade_card" => (Self::UpgradeCard, None),
            "transform_card" => (Self::TransformCard, None),
            other => {
                // `kind:payload` -- split once, and refuse an empty or missing half. A bare
                // `curse` / `relic` with no id is **outside** the vocabulary: the id is the whole
                // point of those two, so accepting them without one would be a choice that
                // silently does nothing.
                let (kind, payload) = other.split_once(':')?;
                if payload.is_empty() {
                    return None;
                }
                match kind {
                    "curse" => (Self::GainCurse, Some(payload)),
                    "relic" => (Self::GainRelic, Some(payload)),
                    "relic_lose" => (Self::LoseRelic, Some(payload)),
                    // §278：`damage_pct:25` —— **数字在词里**（`Amount` 那一格与它无关），
                    // 因为 A15 的 35% 是另一条效果，而不是同一个数字换了值。
                    "damage_pct" => match parse_permille(payload) {
                        Some(tenths) => (Self::LoseHealthPercent(tenths), None),
                        None => return None,
                    },
                    "max_hp_pct" => match parse_permille(payload) {
                        Some(tenths) => (Self::LoseMaxHealthPercent(tenths), None),
                        None => return None,
                    },
                    // §280：**付钱**。与 `gold`（正增量）是两条不同的路：那一条随手就可能
                    // 把金币夹到 0，而"花 75 只有 50"必须响亮拒绝。
                    "gold_cost" => match parse_permille(payload) {
                        // 金币是整数，不能有小数；`parse_permille` 顺带把 `12.5` 变成 `125`，
                        // 所以这里只接受**整百分**（千分值是 10 的倍数）。
                        Some(tenths) if tenths % 10 == 0 && tenths > 0 => {
                            (Self::GoldCost(tenths / 10), None)
                        }
                        _ => return None,
                    },
                    // §285：`gold_random:20:50` —— 两端都是**整数金币**（区间不是百分比）。
                    "gold_random" => {
                        let mut parts = payload.split(':');
                        let (Some(low), Some(high), None) =
                            (parts.next(), parts.next(), parts.next())
                        else {
                            return None;
                        };
                        match (low.parse::<i32>(), high.parse::<i32>()) {
                            // 端点必须**同号、非零、按绝对值有序**。负区间是"扣钱"，内容写成
                            // `-20:-50`（先小后大，与 `20:50` 同一个读法）⇒ 比较的是绝对值。
                            // ⚠️ 内容门也按绝对值比 —— 两处只要一处用原值，另一边就会把
                            // `-20:-50` 判成"倒置"，而症状是"这条效果读不出来"（§286 踩过）。
                            (Ok(low), Ok(high))
                                if low != 0
                                    && high != 0
                                    && (low < 0) == (high < 0)
                                    && low.abs() <= high.abs() =>
                            {
                                (Self::GoldRandom(low, high), None)
                            }
                            _ => return None,
                        }
                    }
                    "heal_pct" => match parse_permille(payload) {
                        Some(tenths) => (Self::HealPercent(tenths), None),
                        None => return None,
                    },
                    _ => return None,
                }
            }
        })
    }

    /// The deck edit this effect asks for, if any. `None` = it needs no card index.
    #[must_use]
    pub fn deck_change(self) -> Option<DeckChange> {
        match self {
            Self::RemoveCard => Some(DeckChange::Remove),
            Self::UpgradeCard => Some(DeckChange::Upgrade),
            Self::TransformCard => Some(DeckChange::Transform),
            _ => None,
        }
    }

    /// Does this effect need a payload supplied beside it?
    #[must_use]
    pub fn needs_payload(self) -> bool {
        matches!(self, Self::GainCurse | Self::GainRelic)
    }
}

/// A card's rarity (`inv:§3.5`; the six buckets StS uses).
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
#[repr(u8)]
pub enum Rarity {
    /// The starting deck's cards. Never offered by StS as a reward, but this content has nothing
    /// else, so the reward screen does offer them (see the fall-through in `roll_reward`).
    Basic = 0,
    /// ...
    Common = 1,
    /// ...
    Uncommon = 2,
    /// ...
    Rare = 3,
    /// Junk cards (`slimed`).
    Status = 4,
    /// Not in this content.
    Curse = 5,
    /// **Not droppable** (§160): the wiki puts these relics in its `Event` bucket (`golden_idol`),
    /// or in `Shop`/`Boss`. They exist, they have an effect, and no reward/chest/shop pool may roll
    /// them -- `pick_relic_avoiding` filters them out before the weight draw.
    ///
    /// Without this bucket the only way to say "event-only" was to lie about the rarity, and the
    /// content said `Rare`, so 17% of every elite reward could be an event relic.
    Event = 6,
    /// §259：wiki 的遗物桶里还有 `Starter`（起手遗物）与 `Boss`（Boss 遗物）。
    ///
    /// 它们**不进掉落权重表**（`RELIC_RARITY_WEIGHTS` 只有三档），所以 `pick_relic` 永远抽不到
    /// —— 与 `Event` 同一条道理：桶存在的意义是"能说实话"（`Burning Blood` 是 Starter，
    /// 不是 Common；`Coffee Dripper` 是 Boss，不是 Rare），而不是让它们从宝箱里掉出来。
    Starter = 8,
    /// See [`Self::Starter`].
    Boss = 9,
    /// §218：wiki 把**事件专属**的卡牌放在 `Special` 桶里（`apparition`）。
    ///
    /// 与 `Event`（遗物）同一个道理：这个桶让"事件才有"成为**可说的**，而不是靠"谎报成 Uncommon"
    /// —— 谎报的后果是它进了普通奖励池（Apparition 是"获得 1 层无形"，不该每场奖励都能刷到）。
    /// 所有按稀有度抽牌的地方都要把它排除。
    Special = 7,
}

impl Rarity {
    /// The name the content carries in `CARD.Rarity`.
    #[must_use]
    pub fn from_name(name: &str) -> Option<Self> {
        match name {
            "Basic" => Some(Self::Basic),
            "Common" => Some(Self::Common),
            "Uncommon" => Some(Self::Uncommon),
            "Rare" => Some(Self::Rare),
            "Status" => Some(Self::Status),
            "Curse" => Some(Self::Curse),
            // §160: the wiki's `Event` bucket (and the shape `Shop`/`Boss` would take). Droppable
            // relics are the three weighted bands; this one exists so "event-only" is sayable.
            "Event" => Some(Self::Event),
            // §218: the wiki's bucket for event-only cards (`apparition`).
            "Special" => Some(Self::Special),
            // §259: the two relic buckets above.
            "Starter" => Some(Self::Starter),
            "Boss" => Some(Self::Boss),
            _ => None,
        }
    }

    fn index(self) -> usize {
        self as u8 as usize
    }
}

/// §270：**卡牌的类型**（内容里是 tag：`attack` / `skill` / `power` / `curse` / `status`）。
///
/// 三个蛋要它（按类型升级），`omamori` / `darkstone_periapt` 也要它（只认诅咒）。
/// 与 [`Rarity`] 是两件事：稀有度决定"多常出现"，类型决定"它是什么"。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum CardKind {
    Attack,
    Skill,
    Power,
    Status,
    Curse,
    /// 类型未知（开局牌组、测试里的裸 id）。**三个蛋与两条诅咒规则都不会对它生效** ——
    /// 这是刻意的：宁可"这件遗物对这张牌没反应"，也不要按名字猜类型。
    Other,
}

/// A card as the reward roll sees it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PoolCard<'a> {
    /// The definition id.
    pub id: &'a str,
    /// Its rarity, from the content.
    pub rarity: Rarity,
    /// §270：its **type** (the content's `attack`/`skill`/`power`/`curse` tag).
    pub kind: CardKind,
    /// §270：its `+` row, if the content has one. Resolved by [`upgraded_id`] in `full_pool`,
    /// **not** by string concatenation at the point of use.
    pub upgraded: Option<&'a str>,
}

impl<'a> PoolCard<'a> {
    /// A card known only by id: `Basic` rarity, unknown type, no `+` row.
    ///
    /// For the starting deck and for tests. The three eggs and the two curse relics stay inert on
    /// these -- and they must: a run's starting deck is Strikes and Defends, so nothing that looks
    /// at types can fire before the first relic is picked up.
    #[must_use]
    pub const fn plain(id: &'a str) -> Self {
        Self { id, rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None }
    }
}


/// A relic the content offers: what it is, and how rare (§156).
///
/// Same shape as [`PoolCard`] and for the same reason: the drop tables weight on rarity, so the run
/// layer has to see it. A parallel `&[Rarity]` beside a `&[&str]` is how the two get out of step.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PoolRelic<'a> {
    /// The definition id.
    pub id: &'a str,
    /// Its rarity, from the content's `REL.Rarity`.
    pub rarity: Rarity,
}

/// A potion the content offers: what it is, and how rare (§156). See [`PoolRelic`].
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PoolPotion<'a> {
    /// The definition id.
    pub id: &'a str,
    /// Its rarity, from the content's `POT.Rarity`.
    pub rarity: Rarity,
}

/// The wiki's relic drop weights: Common 50%, Uncommon 33%, Rare 17%.
pub const RELIC_RARITY_WEIGHTS: [(Rarity, u32); 3] = [
    (Rarity::Common, 50),
    (Rarity::Uncommon, 33),
    (Rarity::Rare, 17),
];

/// The wiki's potion drop weights: Common 65%, Uncommon 25%, Rare 10%.
pub const POTION_RARITY_WEIGHTS: [(Rarity, u32); 3] = [
    (Rarity::Common, 65),
    (Rarity::Uncommon, 25),
    (Rarity::Rare, 10),
];

/// Which fight paid. `inv:§5` / `inv:§3.5` differ per kind in **both** gold and rarity.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum FightKind {
    /// A normal fight: 10–20 gold, rare base 3%, uncommon band 37%.
    Normal,
    /// An elite: 25–35 gold, rare base 10%, uncommon band 40%.
    Elite,
    /// A boss: 95–105 gold, **always rare**.
    Boss,
}

impl FightKind {
    /// The gold range `inv:§5`.
    #[must_use]
    pub const fn gold(self) -> (i32, i32) {
        match self {
            Self::Normal => (10, 20),
            Self::Elite => (25, 35),
            Self::Boss => (95, 105),
        }
    }

    /// `base rare%` at offset 0 (`inv:§3.5`; wiki `Card Rewards`).
    #[must_use]
    pub const fn rare_base(self) -> i32 {
        match self {
            Self::Normal => 3,
            Self::Elite => 10,
            Self::Boss => 100,
        }
    }

    /// The uncommon band's **fixed width** (`inv:§3.5`: 37% normal, 40% elite).
    ///
    /// It is a width, not a probability: the band sits directly on top of the rare band, so it moves
    /// with it. See [`reward_bands`].
    #[must_use]
    pub const fn uncommon_width(self) -> i32 {
        match self {
            Self::Normal => 37,
            Self::Elite => 40,
            Self::Boss => 0,
        }
    }
}

/// The two band edges for one card roll, out of one 0–99 roll.
///
/// # This is the part a naive implementation gets wrong
///
/// The three rarities are **not** three independent chances. One number is rolled and checked
/// against bands stacked in order: rare first, then uncommon on top, then common gets the rest.
///
/// * the rare band is `base + offset`, **floored at 0**;
/// * the uncommon band is a fixed width that sits on top of it -- so when the rare band is
///   *negative*, the part of the uncommon band below 0 is clipped off and **goes to common**, not
///   to uncommon.
///
/// At a fresh normal-fight reset (`base 3 + offset -5 = -2`) that gives rare 0%, uncommon 35%,
/// common 65% -- the wiki states exactly that ("Actual at reset (offset -5%)"). An implementation
/// that clamps the rare band to 0 *and keeps uncommon at 37%* would quietly hand the 2% to uncommon.
#[must_use]
/// §189 `A12`：这张奖励牌有多大比例是**升级版**（百分比，整数）。
///
/// 基线（wiki `Card Rewards`）：第一幕 **0%**，第二幕 **12%**，第三幕 **25%**。
/// A12 是 "Upgraded cards are less common" ⇒ **减半**（6% / 12%）。
///
/// ⚠️ 基线这条规则以前**根本不存在** —— `inv:§3.5` 那句"第一幕不出现升级牌"被实现成了
/// "哪一幕都不出现"。所以 A12 是把两条一起做掉。
#[must_use]
pub const fn upgrade_chance_percent(act: u8, ascension: u8) -> i32 {
    let base = match act {
        1 => 0,
        2 => 12,
        3 => 25,
        _ => 0,
    };
    if ascension >= A_FEWER_UPGRADES {
        base / 2
    } else {
        base
    }
}

/// `id` 的 `+` 行，**如果池子里有**（§189）。
///
/// 不做字符串拼接再查表：id 是 `&'static str`，一次线性扫描比"拼一个 String 再比"更容易看出它
/// 到底在找什么（这个池子最多几十条）。
#[must_use]
/// §270：一张牌的 `+` 行（按命名约定，**在池子里找过**才算数）。
///
/// 公开是因为 `rd-wasm` 的 `full_pool` 要在**建池子那一趟**把 `PoolCard::upgraded` 填好 ——
/// 那个答案只有这里能给，别处再拼一次 `id + "+"` 就是第二份真相。
/// 一张牌的 `+` 行：**先**读 `PoolCard::upgraded`（§270 引入的字段，`full_pool` 在池子那一趟
/// 就把它解析好了），字段缺席时再按命名约定在池子里找。
///
/// ⚠️ 为什么要有两段：`upgraded` 是**新**的、唯一的"这张牌的 `+` 行"；按命名找是给
/// **只给基础行**的池子（老测试、以及"池子里同时有基础行与 `+` 行"的正式路径）。
/// 两段都留是妥协，所以顺序写死：字段优先。§274 的第一版只认命名，于是"池子里只有基础行、
/// `+` 行挂在字段上"那种池子会**静默升不动**（判据报"升级 0 张"）。
pub fn upgraded_id<'a>(pool: &[PoolCard<'a>], base: &str) -> Option<&'a str> {
    if let Some(card) = pool.iter().find(|card| card.id == base) {
        if let Some(upgraded) = card.upgraded {
            return Some(upgraded);
        }
    }
    pool.iter()
        .map(|card| card.id)
        .find(|id| id.len() == base.len() + 1 && id.starts_with(base) && id.ends_with('+'))
}

pub fn reward_bands(kind: FightKind, offset: i32) -> (i32, i32) {
    // A boss reward is rare at 100% and **does not read the offset** -- but it does *reset* it
    // (wiki `Card Rewards`, the "What doesn't update the pity counter" table: boss reads `no`,
    // updates `yes`). Applying the offset here would make a boss hand out a 95% rare roll.
    if kind == FightKind::Boss {
        return (100, 100);
    }
    let banded = kind.rare_base() + offset;
    let rare_top = banded.max(0);
    let uncommon_top = banded.max(0) + kind.uncommon_width() - (-banded).max(0);
    (rare_top, uncommon_top)
}

/// What a won fight pays (`inv:§5`): gold already granted, plus the cards on offer.
///
/// The three cards are **mutually distinct** (`inv:§3.5`: rolled one at a time, a later roll never
/// repeats an earlier one). The rarity weights of `inv:§3.5` are not applied: this content carries
/// no rarity, so every card in the pool is treated as one bucket -- the same `[推断]` the merchant's
/// prices carry, and it is recorded in `sts-act1-plan.md`'s downgrade table.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Reward {
    gold: i32,
    cards: [RunId; MAX_REWARD_CARDS],
    cards_len: u8,
    /// The potion this fight dropped, if any (`inv:§9.3`: 40% of fights, and a full belt simply
    /// means the offer cannot be taken).
    potion: RunId,
    /// The relic this fight pays (§155). **Only elites and bosses** have one; a normal fight clears
    /// it. StS's elite reward is "gold + cards + a relic", and ours paid the first two.
    relic: RunId,
}

impl Reward {
    /// Nothing on the table.
    #[must_use]
    pub const fn empty() -> Self {
        Self {
            gold: 0,
            cards: [RunId::EMPTY; MAX_REWARD_CARDS],
            cards_len: 0,
            potion: RunId::EMPTY,
            relic: RunId::EMPTY,
        }
    }

    /// The gold this fight paid (already added to the run).
    #[must_use]
    pub const fn gold(&self) -> i32 {
        self.gold
    }

    /// The cards on offer.
    #[must_use]
    pub fn cards(&self) -> &[RunId] {
        &self.cards[..self.cards_len as usize]
    }
}

/// One thing a merchant is selling. `price < 0` means "already sold".
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Offer {
    /// The card or relic id.
    pub id: RunId,
    /// Price in gold, or `-1` once bought.
    pub price: i32,
}

impl Offer {
    const EMPTY: Self = Self {
        id: RunId::EMPTY,
        price: -1,
    };
}

/// A merchant's stock. Fixed size: five cards and three relics (`inv:§8.2`).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct ShopStock {
    cards: [Offer; MAX_SHOP_CARDS],
    cards_len: u8,
    relics: [Offer; MAX_SHOP_RELICS],
    relics_len: u8,
}

impl ShopStock {
    /// An empty shelf.
    #[must_use]
    pub const fn empty() -> Self {
        Self {
            cards: [Offer::EMPTY; MAX_SHOP_CARDS],
            cards_len: 0,
            relics: [Offer::EMPTY; MAX_SHOP_RELICS],
            relics_len: 0,
        }
    }

    /// The card offers.
    #[must_use]
    pub fn cards(&self) -> &[Offer] {
        &self.cards[..self.cards_len as usize]
    }

    /// The relic offers.
    #[must_use]
    pub fn relics(&self) -> &[Offer] {
        &self.relics[..self.relics_len as usize]
    }
}

/// What opening a chest gave.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct ChestOutcome {
    /// 0 small, 1 medium, 2 large (`inv:§8.3`).
    pub chest: u8,
    /// Gold, or 0 when the roll declined to give any (`inv:§8.3` has a per-chest chance).
    pub gold: i32,
    /// The relic, if the pool had one.
    pub relic: Option<RunId>,
}
/// The most nodes one step can offer: the first floor is chosen freely among a whole row.
pub const MAX_STEP_TARGETS: usize = NODES_PER_ROW;

/// A tripwire, not a budget. Measured value lives in [`RunState::size_bytes`]; this bound is here so
/// that adding a field cannot quietly double the run's memory. `CombatState`'s equivalent has the
/// same job (`rd-core/src/state.rs::state_fits_the_sram_plan`).
///
/// §260: raised 8 KB -> **12 KB**. What the extra 4 KB buys: `MAX_RUN_RELICS` 24 -> 48
/// (48 × 41 B of belt + the bookkeeping), which is the difference between "a run that cannot hold
/// the endgame relic list" and one that can. The growth is a **capacity**, and per the discipline it
/// was checked for behaviour: `relics_len`/`relics` are written and read symmetrically, the archive
/// writes `relics_len` as one byte (48 < 256, so the format is unchanged), and
/// `MAX_RUN_RELICS > 255` would have been the only case that changes the wire format.
pub const RUN_STATE_TRIPWIRE_BYTES: usize = 12 * 1024;

/// A deck/relic/potion id. `Ident<ID_CAP>` is 41 bytes (`ID_CAP` 40 + a length byte).
pub type RunId = Ident<ID_CAP>;

/// §253：**跟着牌位走的一格每副本数据**（`key` = mark counter 的名字，`value` = 它的值）。
///
/// 存在的理由只有一条：`Ritual Dagger` 的 "permanently increase this card's damage by 3"
/// 里那个 *permanently* 是**跨战斗**的，而战斗层的一次性实例在 `fight_end` 就没了。
///
/// ⚠️ 它**不进 run hash**（`hash.rs` 逐字段写）：参考的运行层没有这个概念，而那个指纹要与
/// 参考对齐。与 §201 的 `CombatState.gold_carried_away` 同一条裁决。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct RunMark {
    /// mark counter 的名字；`RunId::EMPTY` = 这个牌位没有跨场数据。
    pub key: RunId,
    /// 它的值。
    pub value: i32,
}

impl RunMark {
    /// 没有跨场数据。
    pub const NONE: Self = Self {
        key: RunId::EMPTY,
        value: 0,
    };

    /// 这一格是不是空的。
    #[must_use]
    pub fn is_none(self) -> bool {
        self.key.as_str().is_empty()
    }
}

/// Where the cursor can legally go next. At most one row's worth of nodes.
///
/// Holds **global** node indices, because that is what every consumer wants: the internal storage
/// numbering (row, row-local index) is an implementation choice, and forcing each caller to
/// recompute the row offsets is how off-by-one bugs get shipped.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Reachable {
    slots: [u8; MAX_STEP_TARGETS],
    len: u8,
}

impl Reachable {
    /// How many nodes can be entered.
    #[must_use]
    pub const fn len(&self) -> usize {
        self.len as usize
    }

    /// Always false (a run always has somewhere to go until it is over); present so clippy's
    /// `len_without_is_empty` stays honest instead of suppressed.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.len == 0
    }

    /// The `index`-th reachable node's global index.
    #[must_use]
    pub fn get(&self, index: usize) -> Option<u8> {
        if index < self.len() {
            Some(self.slots[index])
        } else {
            None
        }
    }

    /// Whether `global` is reachable from here.
    #[must_use]
    pub fn contains(&self, global: u8) -> bool {
        self.slots[..self.len()].contains(&global)
    }

    fn push(&mut self, global: u8) {
        // The caller bounds this by construction (at most one row of nodes); the assert makes a
        // future caller that breaks that assumption loud instead of silently dropping a target.
        assert!(
            (self.len as usize) < MAX_STEP_TARGETS,
            "more than {MAX_STEP_TARGETS} reachable nodes: the caller is not a single row"
        );
        self.slots[self.len as usize] = global;
        self.len += 1;
    }
}

/// One run. `Copy`, POD, no allocation — the same discipline as `CombatState`, so it can be
/// snapshotted and (later) relocated.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct RunState {
    seed: i32,
    floor: i32,
    health: i32,
    health_max: i32,
    gold: i32,
    /// `-1` before the first step (`run-layer.md` §6.2 invariant 1).
    node: i32,
    removed_cards: i32,
    /// §259：`Girya` 用过几次 `Lift`（0..=`GIRYA_MAX_LIFTS`）。
    ///
    /// 它**不是**"力量层数"：力量是每场战斗开始时按这个数折算出来的（`combat_bonus`），
    /// 所以这个字段跨战斗留存、而战斗里的力量不留存。用满 3 次之后 `Lift` 选项消失。
    girya_lifts: u8,
    /// §259：`Recall` 拿到的红钥匙（Act 4 的门票）。一个布尔就够 —— wiki 只有"拿没拿"。
    ruby_key: bool,
    /// §270：`omamori` 还剩几次"挡诅咒"（0..=2）。**不是**"有几个诅咒"：这是遗物自己的计数器，
    /// 与牌组里有没有诅咒无关。
    omamori_charges: u8,
    /// §270：`maw_bank` 已经在商店花过钱 ⇒ 不再给爬层金币（wiki："No longer works when you spend
    /// any Gold at a shop"）。布尔就够 —— wiki 只有"失效没失效"，没有次数。
    maw_bank_broken: bool,
    /// §271：`ancient_tea_set` —— 刚进过篝火 ⇒ **下一场**战斗开战多 2 能量。
    ///
    /// 为什么是运行期字段、而不是"在篝火那一刻直接加能量"：那时没有战斗，能量无处可加
    /// （能量是战斗状态的资源）。所以只记"欠一场"，开战那一刻兑现、然后清掉。
    tea_set_pending: bool,
    /// §272：光标下那个 `?` 房**掷出了什么**（`begin_node` 之前是 `Unresolved`）。
    ///
    /// 为什么要有这个字段：`begin_node` 只能返回 `NodeKind`，而"事件"与"普通战斗"都是
    /// `NodeKind::Unknown` —— 调用方（`rd-wasm`）必须靠它区分"开事件"还是"开一场战斗"。
    unknown_room: UnknownRoom,
    /// §272：`tiny_chest` 已经数到第几个 `?` 房（0..`TINY_CHEST_ROOMS`）。只在这件遗物在
    /// 身上时增长；换幕归零（与三条概率同一个理由）。
    tiny_chest_rooms: u8,
    /// §274：拾取时**欠着**的牌组编辑（`empty_cage` = 移除 2 张、`astrolabe` = 改造 3 张）。
    ///
    /// 为什么不是 `Pending` 的一个变体：`pending` 是"**这个节点**要什么"，一个流程一个写者。
    /// 而拾取可能发生在**另一个屏开着的时候**（打完 Boss 的奖励屏、宝箱），把 `pending` 抢过来
    /// 会把那一屏顶掉 —— 玩家会丢掉还没拿的卡牌奖励。所以欠的这几步走自己的通道。
    pickup_change: Option<DeckChange>,
    pickup_picks: u8,
    deck: [RunId; MAX_RUN_DECK],
    /// §253：与 `deck` **同下标**的每副本数据（`RunMark::NONE` = 没有）。
    /// 牌组重排时必须跟着搬（`remove_card` 里那条 `deck[i] = deck[i+1]` 旁边的同一行）。
    marks: [RunMark; MAX_RUN_DECK],
    deck_len: u8,
    relics: [RunId; MAX_RUN_RELICS],
    relics_len: u8,
    potions: [RunId; MAX_RUN_POTIONS],
    potions_len: u8,
    /// The potion drop chance **right now** (§157): starts at 40, `-10` after a drop, `+10` after a
    /// miss, reset when an act starts.
    potion_chance: i32,
    map: RunMap,
    /// See [`RunState::map_generation_failed`].
    map_generation_failed: bool,
    rng: RunRng,
    /// `?` room cumulative odds (`inv:§7.5`), three counters, reset at the start of an act.
    unknown: [i32; 3],
    /// What the node under the cursor is waiting for.
    pending: Pending,
    /// The merchant's stock while standing in a shop.
    shop: ShopStock,
    /// The card choice after a won fight.
    reward: Reward,
    /// Has the act been **cleared**? Set when the boss dies (`inv:§7.2`: the boss is the end of the
    /// act). Until this existed a run could not be won, only lost.
    boss_beaten: bool,
    /// §189 `A20`: 这一幕已经倒下了几个 Boss（0 = 还没有，1 = 第一个已倒）。只有最后一幕 + A20
    /// 才会变成 1；换幕时归零。与 `boss_beaten` 同类：run 层状态，不进战斗指纹。
    bosses_fought: u8,
    /// Which nodes have paid out. A node settles **once** -- a second visit is an error, which is
    /// what stops a fight from being farmed and a campfire from healing on every click.
    resolved: [u64; 2],
    /// Which act this run is on (1-based). Killing an act's boss advances it.
    act: u8,
    /// The `?`-room event under the cursor, while `Pending::Event`.
    event: RunId,
    /// §278：这个事件**现在走到哪一段**（`EVND.Id`）。空 = 还没开事件。
    ///
    /// 为什么不把它放在 `rd-wasm`：页面要知道"现在显示哪段正文、有哪几个按钮"，而那是
    /// **局面**的一部分 —— 同一句 `event=golden_idol` 可以是两个完全不同的屏幕。
    event_step: RunId,
    /// §286：事件把房间变成了**一场战斗**（`Dead Adventurer` 的伏击）。`0` = 没有，
    /// `1` = 普通怪，`2` = 精英。它在 `fight_end` 收尾时清掉 —— 也就是"这个节点的账由那一场
    /// 战斗付"，所以它必须**留着**到战斗结束（`node_resolved` 才能一直是 false）。
    event_fight: u8,
    /// §287：这一场战斗用哪个**遭遇池**（空 = 按档位用本幕的标准池）。
    event_fight_pool: RunId,
    /// §287：下一场战斗的金币加成（`Dead Adventurer` 的 30；由 `roll_reward` 消费后清 0）。
    fight_gold_bonus: i16,
    /// §287：下一场战斗**不掉遗物**（那一件已经搜到过；消费后清）。
    fight_no_relic: bool,
    /// §278：这一段选完之后要去的那一段，**在等一次牌组编辑的时候**先记在这里。
    ///
    /// 与 `event_follow` 是两件事：一个是"欠哪次编辑"，一个是"编辑完了去哪儿"。
    event_next: RunId,
    /// The encounter the **previous** fight used (`port-plan.md` §153), so the next normal fight can
    /// avoid repeating it.
    ///
    /// StS does not hand out the same encounter group twice in a row, and without this the run above
    /// produced runs like `fungi, louse, louse, louse` -- see `docs/port-plan.md` §153 for the
    /// measurement (18 of ~100 fights were a repeat of the one before).
    last_encounter: RunId,
    /// Which two blessings were rolled, as indices into [`START_OFFERS`].
    start_offers: [u8; 2],
    /// The picked blessing's follow-up, while [`Pending::BlessingCard`] waits for a deck index.
    blessing_follow: Option<BlessingFollowUp>,
    /// The picked **event** choice's deck edit, while [`Pending::EventCard`] waits for an index
    /// (§143). Separate from `blessing_follow` so neither picker can be finished by the other.
    event_follow: Option<DeckChange>,
    /// The rare-card pity offset (`inv:§3.5`): starts at −5%, +1% per non-rare reward roll, reset to
    /// −5% on a rare, capped at +40%. Only **combat reward** rolls move it.
    rarity_offset: i32,
    /// The Ascension level, `0`..=[`MAX_ASCENSION`] (§159). Cumulative: level `N` carries rules
    /// `1..=N`, and every rule asks [`RunState::at_least`] for its own number.
    ascension: u8,
}

impl Pending {
    /// 这个问句只可能出现在哪种房间里？`None` = 不限定（战斗奖励可能在三种战斗节点之后）。
    #[must_use]
    pub const fn room(self) -> Option<NodeKind> {
        Some(match self {
            Self::Rest => NodeKind::Rest,
            Self::Shop => NodeKind::Shop,
            Self::Chest => NodeKind::Treasure,
            Self::Event | Self::EventCard => NodeKind::Unknown,
            Self::None | Self::Reward | Self::Start | Self::BlessingCard => return None,
        })
    }
}

impl RunState {
    /// The encounter the previous fight used; `RunId::EMPTY` before the first fight (§153).
    #[must_use]
    pub fn last_encounter(&self) -> RunId {
        self.last_encounter
    }

    /// Remember the encounter the fight that just started used (§153).
    pub fn set_last_encounter(&mut self, id: RunId) {
        self.last_encounter = id;
    }
    /// Start a run: generate the map from the `Map` stream, and take the content-derived starting
    /// facts as arguments (see the module docs).
    ///
    /// `starting_deck` is the deck **in order** — deck order is observable (`run-layer.md` §5.2),
    /// so it is not sorted here or anywhere else.
    ///
    /// Ascension 0 means "no rules"; [`Self::new_with_ascension`] is the real constructor and this
    /// one is the shortcut every test and every non-ascended call site uses.
    pub fn new(
        seed: i32,
        health_max: i32,
        gold: i32,
        starting_deck: &[&str],
    ) -> Result<Self, RunError> {
        Self::new_with_ascension(seed, health_max, gold, starting_deck, 0)
    }

    /// [`Self::new`], with an Ascension level (§159).
    ///
    /// `A14` changes the **maximum**, so it has to happen at construction. `A6` ("start each run
    /// damaged") is *not* applied here: the content declares its own `StartingHealth`, and the only
    /// place that knows it is the caller -- `rd-wasm`'s `rd_run_start`, which applies the damage
    /// after setting the health. Splitting them this way is what keeps "which of the two numbers
    /// wins" from depending on the order of two lines.
    pub fn new_with_ascension(
        seed: i32,
        health_max: i32,
        gold: i32,
        starting_deck: &[&str],
        ascension: u8,
    ) -> Result<Self, RunError> {
        let ascension = ascension.min(MAX_ASCENSION);
        let health_max = if ascension >= A_MAX_HP {
            (health_max - ASCENDED_MAX_HEALTH_LOSS).max(1)
        } else {
            health_max
        };
        let health = health_max;
        let mut rng = RunRng::new(seed);
        let map = RunMap::generate_at(&mut rng, ascension)?;
        let mut state = Self {
            seed,
            floor: 0,
            health,
            health_max,
            gold,
            node: -1,
            removed_cards: 0,
            girya_lifts: 0,
            ruby_key: false,
            omamori_charges: 0,
            maw_bank_broken: false,
            tea_set_pending: false,
            unknown_room: UnknownRoom::Unresolved,
            tiny_chest_rooms: 0,
            pickup_change: None,
            pickup_picks: 0,
            deck: [RunId::EMPTY; MAX_RUN_DECK],
            marks: [RunMark::NONE; MAX_RUN_DECK],
            deck_len: 0,
            relics: [RunId::EMPTY; MAX_RUN_RELICS],
            relics_len: 0,
            potions: [RunId::EMPTY; MAX_RUN_POTIONS],
            potions_len: 0,
            potion_chance: POTION_DROP_START,
            map,
            map_generation_failed: false,
            rng,
            unknown: [0; 3],
            pending: Pending::None,
            shop: ShopStock::empty(),
            reward: Reward::empty(),
            boss_beaten: false,
            bosses_fought: 0,
            act: 1,
            event: RunId::EMPTY,
            event_step: RunId::EMPTY,
            event_fight: 0,
            event_fight_pool: RunId::EMPTY,
            fight_gold_bonus: 0,
            fight_no_relic: false,
            event_next: RunId::EMPTY,
            last_encounter: RunId::EMPTY,
            // Rolled by `offer_start_choice`; until then the pair is not a choice anyone can take.
            start_offers: [0, 1],
            blessing_follow: None,
            event_follow: None,
            resolved: [0; 2],
            rarity_offset: RARITY_OFFSET_START,
            ascension,
        };
        for id in starting_deck {
            state.push_card(PoolCard::plain(id))?;
        }
        // §189 `A10`：开局牌组里塞一张 Ascender's Bane（在牌组末尾，与其他"开局牌"一致）。
        if ascension >= A_START_CURSE {
            // Ascender's Bane 是**诅咒**：类型要写对，否则 `omamori` 将来拦不住它。
            state.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain(ASCENDERS_BANE) })?;
        }
        state.check_invariants()?;
        Ok(state)
    }

    // ---- reads -----------------------------------------------------------------------------


    /// 当前的药水掉率（§157：40 起、每次战后 ±10、换幕重置）。
    #[must_use]
    pub const fn potion_chance(&self) -> i32 {
        self.potion_chance
    }

    /// `?` 房的三条累计计数（`inv:§7.5`），换幕重置。
    #[must_use]
    pub const fn unknown(&self) -> &[i32; 3] {
        &self.unknown
    }

    /// 已经选定的祝福后续动作（只在 `Pending::BlessingCard` 期间非空）。
    #[must_use]
    pub const fn blessing_follow(&self) -> Option<BlessingFollowUp> {
        self.blessing_follow
    }

    /// 已选定的事件后续动作（只在 `Pending::EventCard` 期间非空）。
    #[must_use]
    pub const fn event_follow(&self) -> Option<DeckChange> {
        self.event_follow
    }

    /// 已结算位图的两个字（节点的下标 → 位）。
    #[must_use]
    pub const fn resolved_words(&self) -> &[u64; 2] {
        &self.resolved
    }

    /// 商店的卡位（含已买走/未上架的行，`price < 0`）。
    #[must_use]
    pub fn shop_cards(&self) -> &[Offer] {
        &self.shop.cards
    }

    /// 商店的遗物位。
    #[must_use]
    pub fn shop_relics(&self) -> &[Offer] {
        &self.shop.relics
    }

    /// 商店卡位的有效行数（槽位下标必须稳定，所以它不随购买减少）。
    #[must_use]
    pub const fn shop_cards_len(&self) -> u8 {
        self.shop.cards_len
    }

    /// 商店遗物位的有效行数。
    #[must_use]
    pub const fn shop_relics_len(&self) -> u8 {
        self.shop.relics_len
    }

    /// 奖励屏的三张卡（空槽是 `EMPTY`）。
    #[must_use]
    pub fn reward_cards(&self) -> &[RunId] {
        &self.reward.cards[..self.reward.cards_len as usize]
    }

    /// The Ascension level this run is played at (`0` = none, §159).
    #[must_use]
    pub const fn ascension(&self) -> u8 {
        self.ascension
    }

    /// Is rule `level` in effect? The wiki's rules are **cumulative**, so this is the only
    /// comparison any rule needs -- and it keeps the numbers in [`A_BOSS_HEAL`] & co. instead of
    /// scattering `>= 5` through the file.
    #[must_use]
    pub const fn at_least(&self, level: u8) -> bool {
        self.ascension >= level
    }

    /// The run seed.
    #[must_use]
    pub const fn seed(&self) -> i32 {
        self.seed
    }

    /// `A16` (§159): a shop price after the Ascension markup.
    ///
    /// Applied **once, at stock time** -- the price the page shows and the price a purchase charges
    /// have to be the same number, and a markup applied at purchase time would need a second rule to
    /// keep them in step.
    const fn marked_up(&self, price: i32) -> i32 {
        if self.at_least(A_SHOP_PRICE) {
            price * ASCENDED_SHOP_PERCENT / 100
        } else {
            price
        }
    }

    /// `A7` / `A8` / `A9` (§159): how much extra maximum health this kind of fight's enemies get,
    /// in percent. `0` below the level that owns the kind, so the three rules stay three rules.
    #[must_use]
    /// §269：不再是 `const fn` —— `preserved_insect` 要看遗物表，而查表不是常量表达式。
    /// 调用点（`fight_begin`）本来就是普通函数，所以这条改动没有传播成本。
    pub fn enemy_health_bonus_percent(&self, kind: FightKind) -> i32 {
        // §269：`preserved_insect` —— 精英战敌人血量 -25%。与升阶的 +75% 走**同一条通道**
        // （战斗构建方只读这一个数），所以两个修正自动叠加、顺序无关（先升阶后遗物，
        // 整数加法可交换）。⚠️ 不能为它另开一条路径：那会让"精英血量"有两个来源。
        let preserved_insect = matches!(kind, FightKind::Elite)
            && self.holds_relic_effect(RelicEffect::EliteEnemyHealthPercent(-25));
        let level = match kind {
            FightKind::Normal => A_NORMAL_HP,
            FightKind::Elite => A_ELITE_HP,
            FightKind::Boss => A_BOSS_HP,
        };
        let ascension = if self.at_least(level) {
            ASCENDED_ENEMY_HEALTH_PERCENT
        } else {
            0
        };
        ascension - if preserved_insect { 25 } else { 0 }
    }
    /// 0 before the first step, then 1..=ROWS.
    #[must_use]
    pub const fn floor(&self) -> i32 {
        self.floor
    }
    /// Health, always in `0..=health_max`.
    #[must_use]
    pub const fn health(&self) -> i32 {
        self.health
    }
    /// Maximum health.
    #[must_use]
    pub const fn health_max(&self) -> i32 {
        self.health_max
    }
    /// Gold.
    #[must_use]
    pub const fn gold(&self) -> i32 {
        self.gold
    }
    /// The current node's global index, or `-1` before the first step.
    #[must_use]
    pub const fn node(&self) -> i32 {
        self.node
    }
    /// Cards removed by shops (`inv:§8.2`). Unused until M2b; carried so the field exists.
    #[must_use]
    pub const fn removed_cards(&self) -> i32 {
        self.removed_cards
    }

    /// §259：`Girya` 已经用过几次 `Lift`。
    #[must_use]
    pub const fn girya_lifts(&self) -> u8 {
        self.girya_lifts
    }

    /// §259：拿到红钥匙了吗（`Recall`）。
    #[must_use]
    pub const fn ruby_key(&self) -> bool {
        self.ruby_key
    }
    /// The map.
    #[must_use]
    pub const fn map(&self) -> &RunMap {
        &self.map
    }
    /// The random streams.
    #[must_use]
    pub const fn rng(&self) -> &RunRng {
        &self.rng
    }
    /// 换掉整组随机流（§163： 的测试要只推进一步再比哈希）。
    ///
    /// 收一个**完整的**  而不是某个计数：让调用方一次交代清楚全部七条流，比允许
    /// 逐条改更难写错 —— 而少写一条正是这类接口最容易犯的错。
    pub const fn replace_rng(&mut self, rng: RunRng) {
        self.rng = rng;
    }

    /// Mutable access to the streams, for the settlement code that lands next.
    pub fn rng_mut(&mut self) -> &mut RunRng {
        &mut self.rng
    }
    /// The deck, in acquisition order.
    #[must_use]
    pub fn deck(&self) -> &[RunId] {
        &self.deck[..self.deck_len as usize]
    }
    /// §253：第 `slot` 个牌位的跨场 mark（`None` = 那个牌位没有）。
    ///
    /// `slot` 越界 ⇒ `None`（查询不是写入，越界没有可报告的东西）。
    #[must_use]
    pub fn mark(&self, slot: usize) -> Option<RunMark> {
        if slot >= self.deck_len as usize {
            return None;
        }
        self.marks.get(slot).copied().filter(|mark| !mark.is_none())
    }

    /// §253：写一个牌位的跨场 mark（`key` 为空 ⇒ 清掉）。越界 ⇒ 拒绝。
    ///
    /// **拒绝而不是扩写**：牌位是牌组的，写一个不存在的牌位说明调用方算错了下标，
    /// 而"多出来的那一格"永远没有人读 —— 那是静默丢数据。
    pub fn set_mark(&mut self, slot: usize, key: &str, value: i32) -> Result<(), RunError> {
        if slot >= self.deck_len as usize {
            // 借用既有的 `Capacity`（"这个定容容器装不下"）：`RunError` 是冻结的枚举，
            // 而"写一个不存在的牌位"与"牌组装不下"是同一类事实 —— 都是"那一格不存在"。
            // 绝不悄悄忽略：忽略就是"长大丢了但没人知道"。
            return Err(RunError::Capacity);
        }
        if key.is_empty() {
            if let Some(cell) = self.marks.get_mut(slot) {
                *cell = RunMark::NONE;
            }
            return Ok(());
        }
        // 与 `push_card`/`add_relic` 同一条：id 装不下是 `BadId`，不是容量问题。
        let id = RunId::new(key).map_err(|_| RunError::BadId)?;
        if let Some(cell) = self.marks.get_mut(slot) {
            *cell = RunMark { key: id, value };
        }
        Ok(())
    }

    /// The relics, in acquisition order.
    #[must_use]
    pub fn relics(&self) -> &[RunId] {
        &self.relics[..self.relics_len as usize]
    }
    /// The potions, in belt order.
    #[must_use]
    pub fn potions(&self) -> &[RunId] {
        &self.potions[..self.potions_len as usize]
    }
    /// The `?` room **miss counters** (`inv:§7.5`)：连续"没出现"的次数。
    ///
    /// §272：它们是[`Self::unknown_room_odds`]的输入，不是概率本身 —— 概率 = 基础 × (1 + 这里)。
    #[must_use]
    pub const fn unknown_odds(&self) -> [i32; 3] {
        self.unknown
    }

    /// §272：掷一次 `?` 房的结果，并把三条计数器按规则推进。
    ///
    /// 参数全在本结构体里（三条 `unknown` 计数、遗物表、随机流），所以它是**唯一**决定
    /// "`?` 房变成什么"的地方 —— `begin_node` 只是按结果摆好状态，不是第二个裁决者。
    pub fn roll_unknown_room(&mut self) -> Result<UnknownRoom, RunError> {
        // 三条基础概率 × (1 + 连续没出现次数)。`juzu_bracelet` 把 Monster 那条按成 0。
        let [monster, shop, treasure] = self.unknown_room_odds();
        // **总是**掷一次（理由见 §272 的模块注释：随机流的位置不随遗物变化）。
        // ⚠️ 这一掷在下面所有写操作**之前**，所以 `Err` 时状态一个字节都没动。
        let roll = self.rng.roll(RunStream::Event, 100)? as i32;
        let mut outcome = if roll < monster {
            UnknownRoom::Monster
        } else if roll < monster + shop {
            UnknownRoom::Shop
        } else if roll < monster + shop + treasure {
            UnknownRoom::Treasure
        } else {
            UnknownRoom::Event
        };
        // §272：`tiny_chest` —— "Every 4th ? room is a Treasure room"。
        // 它**覆盖结果**而不是"再掷一次"：再掷一次会让"第 4 个"这个计数变得不可观察
        // （玩家看到的结果与计数对不上），而且要多烧一个随机数。
        if self.holds_relic_effect(RelicEffect::TinyChestEveryFourth) {
            self.tiny_chest_rooms += 1;
            if self.tiny_chest_rooms >= TINY_CHEST_ROOMS {
                self.tiny_chest_rooms = 0;
                outcome = UnknownRoom::Treasure;
            }
        } else {
            // 没有这件遗物时计数必须停在地上：否则"拿到它的那一刻"就凭空多出几次。
            self.tiny_chest_rooms = 0;
        }
        // 三条计数：命中的归零、其余 +1（wiki："increases whenever a `?` room does not contain
        // that type … If a shop is found, the shop chance will be reset back to 3%"）。
        match outcome {
            UnknownRoom::Monster => {
                self.unknown[0] = 0;
                self.unknown[1] += 1;
                self.unknown[2] += 1;
            }
            UnknownRoom::Shop => {
                self.unknown[1] = 0;
                self.unknown[0] += 1;
                self.unknown[2] += 1;
            }
            UnknownRoom::Treasure => {
                self.unknown[2] = 0;
                self.unknown[0] += 1;
                self.unknown[1] += 1;
            }
            UnknownRoom::Event => {
                self.unknown[0] += 1;
                self.unknown[1] += 1;
                self.unknown[2] += 1;
            }
            UnknownRoom::Unresolved => {}
        }
        self.unknown_room = outcome;
        Ok(outcome)
    }

    /// §272：三条概率**现在**是多少（percent），给页面与判据用。
    ///
    /// 与 [`Self::roll_unknown_room`] 用同一组常量与同一个公式 —— 页面上写的 10/3/2 必须与
    /// 真正掷骰的那三个数一致（否则玩家看到的是第三份定价）。
    #[must_use]
    pub fn unknown_room_odds(&self) -> [i32; 3] {
        let juzu = self.holds_relic_effect(RelicEffect::NoUnknownMonster);
        let monster = if juzu {
            0
        } else {
            (UNKNOWN_MONSTER_BASE * (1 + self.unknown[0])).min(100)
        };
        [
            monster,
            (UNKNOWN_SHOP_BASE * (1 + self.unknown[1])).min(100),
            (UNKNOWN_TREASURE_BASE * (1 + self.unknown[2])).min(100),
        ]
    }

    /// §272：`tiny_chest` 数到第几个 `?` 房了（给指纹与判据用）。
    #[must_use]
    pub const fn tiny_chest_rooms(&self) -> u8 {
        self.tiny_chest_rooms
    }

    /// §272：光标下那个 `?` 房掷出了什么（`Unresolved` = 还没掷 / 不是 `?` 房）。
    #[must_use]
    pub const fn unknown_room(&self) -> UnknownRoom {
        self.unknown_room
    }



    /// The measured size, for the tripwire and for anyone printing a memory table.
    #[must_use]
    pub const fn size_bytes() -> usize {
        core::mem::size_of::<Self>()
    }

    // ---- writes ----------------------------------------------------------------------------

    /// Add a card to the deck. Past [`MAX_RUN_DECK`] this is an **error**, never a dropped push.
    /// Add a card to the deck. Past [`MAX_RUN_DECK`] this is an error.
    ///
    /// **The single add point** (§270): every way a card can arrive -- a reward, the merchant, an
    /// event, `Dream Catcher` -- goes through here, so the add-card relics fire exactly once:
    ///
    /// | 遗物 | 规则 | 在这一步做什么 |
    /// |---|---|---|
    /// | `omamori` | 挡掉接下来 2 个诅咒 | 诅咒且还有次数 ⇒ **不加入**、次数 -1 |
    /// | `darkstone_periapt` | 得到诅咒 ⇒ 上限 +6 | 加入之后加上限 |
    /// | `molten_egg` / `toxic_egg` / `frozen_egg` | 加该类型的牌 ⇒ 升级 | 有 `+` 行就换成 `+` 行 |
    /// | `ceramic_fish` | 加任何牌 ⇒ +9 金币 | 加入之后走 `adjust_gold` |
    ///
    /// ⚠️ **顺序是规则的一部分**：`omamori` 在**最前**（被挡掉的诅咒不算"得到"，
    /// 所以 `darkstone_periapt` 不该加血、`ceramic_fish` 也不该给钱）。这条不是"顺手写前一点" ——
    /// 换一下顺序，`omamori` 就会变成一个**付 6 点上限加 9 金币**的遗物。
    pub fn push_card(&mut self, card: PoolCard<'_>) -> Result<(), RunError> {
        let id = RunId::new(card.id).map_err(|_| RunError::BadId)?;
        let slot = self.deck_len as usize;
        if slot >= MAX_RUN_DECK {
            return Err(RunError::Capacity);
        }
        // §270：`omamori` —— "Negate the next 2 Curses you obtain"。被挡掉 ⇒ **什么都不加**，
        // 但这是**成功**（玩家没有做错事，诅咒只是没进牌组）。
        if card.kind == CardKind::Curse && self.omamori_charges > 0 {
            self.omamori_charges -= 1;
            return Ok(());
        }
        // §270：三个蛋 —— 类型对上且有 `+` 行就换成升级版。没有 `+` 行的牌保持原样（内容的事）。
        let chosen = if self.upgrades_added_card(card.kind) {
            match card.upgraded {
                Some(upgraded) => RunId::new(upgraded).map_err(|_| RunError::BadId)?,
                None => id,
            }
        } else {
            id
        };
        self.deck[slot] = chosen;
        self.deck_len += 1;
        // §270：`darkstone_periapt` —— "Whenever you obtain a Curse, increase your Max HP by 6"。
        // 上限涨了，当前血量**不跟**（wiki 只说上限；`Pear` 那种"也回等量"是另一件遗物的写法）。
        if card.kind == CardKind::Curse {
            if let Some(RelicEffect::CurseMaxHealthUp(amount)) =
                self.first_relic_effect_of(RelicEffect::CurseMaxHealthUp(6))
            {
                self.health_max += amount;
            }
        }
        // §270：`ceramic_fish` —— "Whenever you add a card to your deck, gain 9 Gold"。
        // 走 `adjust_gold`：`ectoplasm` 该拦就拦、`bloody_idol` 该回血就回血 —— 那两条规则
        // 只认"金币真的变了"这一件事，不该在第二个地方再写一遍。
        if let Some(RelicEffect::CardAddGold(amount)) =
            self.first_relic_effect_of(RelicEffect::CardAddGold(9))
        {
            self.adjust_gold(amount);
        }
        Ok(())
    }

    /// §270：`omamori` 还剩几次挡诅咒（`0..=OMAMORI_CHARGES`）。给页面用。
    #[must_use]
    pub const fn omamori_charges(&self) -> u8 {
        self.omamori_charges
    }

    /// §271：欠下一场"开战 +2 能量"（`ancient_tea_set`）。
    ///
    /// 公开是给两个调用方：`begin_node` 的篝火分支（真实路径），以及判据里"直接欠上、
    /// 只看开战有没有消费"的那一段（它不该为了造局面去走一遍篝火）。
    pub fn owe_tea_set_for_the_next_fight(&mut self) {
        if self.holds_relic_effect(RelicEffect::RestEntryNextCombatEnergy(
            "standard.ancient_tea_set",
            1,
        )) {
            self.tea_set_pending = true;
        }
    }

    /// §271：`ancient_tea_set` 是否欠着一场"开战 +2 能量"。
    #[must_use]
    pub const fn tea_set_pending(&self) -> bool {
        self.tea_set_pending
    }

    /// §271：**兑现**那一场 —— 由战斗构建方在"开战加成已经应用"之后调用。
    ///
    /// ⚠️ 清理点只有这一个，而且它必须在**应用之后**：先清再算的话，`combat_bonus_for` 就
    /// 永远读不到它，`ancient_tea_set` 会变成一个什么都不做的遗物（而且所有判据都还是绿的，
    /// 因为没有任何东西"错"）。
    pub fn clear_tea_set(&mut self) {
        self.tea_set_pending = false;
    }

    /// §270：`maw_bank` 是否已经失效（在商店花过钱）。
    #[must_use]
    pub const fn maw_bank_broken(&self) -> bool {
        self.maw_bank_broken
    }

    /// §270：身上有没有**这一件**遗物（按 id）。
    ///
    /// 与 `holds_relic_effect` 的区别：那个按**效果值**找（"有没有哪件遗物给我 +10 格挡"），
    /// 这个按**名字**找。`RELIC_SECOND_HALVES` 的消费者必需后者 —— 表里的第二半**不是**那件
    /// 遗物的 `relic_effect`，按值永远匹配不上。
    #[must_use]
    fn holds_relic(&self, id: &str) -> bool {
        for slot in 0..self.relics_len as usize {
            if self.relics[slot].as_str() == id {
                return true;
            }
        }
        false
    }

    /// §270：这张牌进牌组时要不要换成 `+` 行（三个蛋）。
    ///
    /// 一条判据回答一个问题："有没有**哪个**蛋管这个类型"。所以它遍历遗物而不是匹配三条规则 ——
    /// 将来再加第四个蛋（StS 没有，但内容可以）时，这里不用动。
    fn upgrades_added_card(&self, kind: CardKind) -> bool {
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::UpgradeAddedCard(wanted)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                if wanted == kind {
                    return true;
                }
            }
        }
        false
    }

    /// §270：某件遗物给的某个变体，**取它带的参数**。
    ///
    /// `holds_relic_effect` 只能回答"有没有完全等于这个值的一条"，而 `push_card` 需要的是
    /// "**多少**"（+6 上限、+9 金币）。⚠️ 这里匹配的是**变体的形状**，所以参数必须与表里一致 ——
    /// 传错常量会得到一个"看起来没生效"的遗物。判据钉住了两条真实数字。
    fn first_relic_effect_of(&self, wanted: RelicEffect) -> Option<RelicEffect> {
        // ⚠️ 用 `discriminant` 而不是"逐个变体手写一个 `match` arm"：第一版手写了两个 arm 就漏掉
        // 第三个（`GoldGainHeal`），症状是 `bloody_idol` **完全不回血**而判据里那条"花钱不回血"
        // 照样绿 —— 典型的"断言写在了切口下游"。`discriminant` 自动覆盖所有变体。
        let want = core::mem::discriminant(&wanted);
        for slot in 0..self.relics_len as usize {
            if let Some(effect) = Self::relic_effect(self.relics[slot].as_str()) {
                if core::mem::discriminant(&effect) == want {
                    return Some(effect);
                }
            }
        }
        None
    }

    /// Add a relic. Past [`MAX_RUN_RELICS`] this is an error.
    ///
    /// **The single grant point** (§145): every way a relic can arrive -- chest, shop, elite reward,
    /// an event's `relic:<id>` -- goes through here, so three things happen exactly once:
    ///
    /// 1. an **unimplemented** relic is refused ([`RunError::UnsupportedRelic`]) while the player is
    ///    still looking at whatever handed it over, instead of at the end of the next fight;
    /// 2. the relic's **grant-time** effect fires (`MaxHealthUp` / `HealUp` / §274 的七件拾取类);
    /// 3. it enters the belt.
    ///
    /// Doing (2) at the call sites instead would mean four copies of "and then Pear's max HP goes
    /// up", which is how a relic comes to work in a chest but not in a shop.
    ///
    /// §274：`pool` 是**卡池**。四件拾取类遗物要看牌的类型（Attack/Skill）与 `+` 行，而运行层
    /// 只存牌 id —— 与 `push_card(PoolCard)` 同一条纪律：内容的事在有内容的那一层解析。
    /// §279：**失去**一件遗物（`relic_lose:<id>` / `Forgotten Altar` 的交换）。
    ///
    /// 三条约束：
    /// * 不持有 ⇒ [`RunError::NoSuchRelic`]（不是静默成功：那会让"条件写错"变成"按钮白点"）；
    /// * 拾取时给过一次性的东西（`omamori` 的 2 次、`girya` 的层数）**不回收** —— 参考实现
    ///   也没有"撤销拾取效果"的概念，而凭空发明一条回收规则会让"失去遗物"变成一次反向触发；
    /// * 后面的遗物**往前挪**（保持顺序 = 拿到的顺序），于是 `relics()` 的切片始终连续。
    pub fn remove_relic(&mut self, relic_id: &str) -> Result<(), RunError> {
        let id = RunId::new(relic_id).map_err(|_| RunError::BadId)?;
        let len = self.relics_len as usize;
        let Some(slot) = self.relics[..len].iter().position(|held| *held == id) else {
            return Err(RunError::NoSuchRelic);
        };
        for index in slot..len.saturating_sub(1) {
            self.relics[index] = self.relics[index + 1];
        }
        self.relics_len -= 1;
        self.relics[len - 1] = RunId::EMPTY;
        Ok(())
    }

    pub fn push_relic(
        &mut self,
        relic_id: &str,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        let Some(effect) = Self::relic_effect(relic_id) else {
            return Err(RunError::UnsupportedRelic {
                index: self.relics_len,
            });
        };
        let id = RunId::new(relic_id).map_err(|_| RunError::BadId)?;
        let slot = self.relics_len as usize;
        if slot >= MAX_RUN_RELICS {
            return Err(RunError::Capacity);
        }
        match effect {
            // §270：`omamori` —— 拾取时给 2 次"挡诅咒"。
            RelicEffect::Omamori(charges) => self.omamori_charges = charges,
            RelicEffect::MaxHealthUp(amount) => {
                self.health_max += amount;
                // The current HP follows the maximum up — StS's "raise your max HP" always heals
                // you by the same amount.
                self.adjust_health(amount);
            }
            // §274：`old_coin` —— +300 金币。走 `adjust_gold`，所以 `ectoplasm` 该拦就拦、
            // `bloody_idol` 该回血就回血。
            RelicEffect::PickupGold(amount) => self.adjust_gold(amount),
            // §274：`lee's_waffle` —— 上限 +7 **且**回满。两件事分开写：`MaxHealthUp` 只回
            // "和上限一样多"的那 7 点，而 wiki 说的是 "heal **all** of your HP"。
            RelicEffect::PickupMaxHealthAndHealAll(amount) => {
                self.health_max += amount;
                self.health = self.health_max;
            }
            // §274：`war_paint` / `whetstone` —— 随机升级 2 张**该类型**的牌。
            // 只动"有 `+` 行、且还没升级"的牌：升级一张已经升级的牌是空操作，
            // 而把它的名额用掉就等于"随机升级 2 张"却什么都没发生。
            RelicEffect::PickupUpgradeRandom(kind, count) => {
                let mut candidates = [0u8; MAX_RUN_DECK];
                let mut found = 0usize;
                for index in 0..self.deck_len as usize {
                    let card = self.deck[index].as_str();
                    let Some(facts) = pool.iter().find(|entry| entry.id == card) else {
                        continue;
                    };
                    if facts.kind == kind && facts.upgraded.is_some() {
                        candidates[found] = index as u8;
                        found += 1;
                    }
                }
                // 只升级 `count` 张，用**这个**随机流（拾取是奖励的一种）。
                // ⚠️ 升级目标取 `PoolCard::upgraded`（"这张牌的 `+` 行"），**不是**再调
                // `upgraded_id` 去池子里按命名找一遍 —— 那个函数要求池子里**同时**有基础行与
                // `+` 行，而这里传进来的池子只有基础行（`+` 行挂在字段上）。同一个事实两种查法
                // 必然漂：第一版就是这么写的，判据报"升级了 0 张"。
                let mut remaining = found;
                let mut picked = 0u8;
                let mut pool_indexes = [0u8; MAX_RUN_DECK];
                for slot in 0..found {
                    pool_indexes[slot] = candidates[slot];
                }
                while picked < count && remaining > 0 {
                    let roll = self.rng.roll(RunStream::Reward, remaining as u32)? as usize;
                    let index = pool_indexes[roll] as usize;
                    let card = self.deck[index].as_str();
                    if let Some(facts) = pool.iter().find(|entry| entry.id == card) {
                        if let Some(upgraded) = facts.upgraded {
                            self.deck[index] =
                                RunId::new(upgraded).map_err(|_| RunError::BadId)?;
                        }
                    }
                    // 把用掉的那个换到尾部，然后缩小窗口（不放回抽样）。
                    pool_indexes[roll] = pool_indexes[remaining - 1];
                    remaining -= 1;
                    picked += 1;
                }
            }
            // §274：`pandoras_box` —— 把**所有** Strike / Defend 改造掉。
            // "Strike / Defend" 按**内容 id 的前缀**认（`strike` / `defend`，含它们的 `+` 行）：
            // 这是内容自己的命名，不是我们在运行层编的规则 —— 所以两条 id 写在这里而不是猜。
            RelicEffect::PickupTransformStaples => {
                // ⚠️ **不要**在命中之后 `index += 1`：`remove_at` 会把后面的牌前移到这一格，
                // 于是前进一格就跳过了刚移过来的那张（第一版就是这样，5 张基础牌只改了 2 张）。
                // 命中时下标**不动**、重新看同一格；没命中才前进。
                let mut index = 0usize;
                while index < self.deck_len as usize {
                    let card = self.deck[index].as_str().trim_end_matches('+');
                    if card == STAPLE_STRIKE || card == STAPLE_DEFEND {
                        self.apply_deck_change(DeckChange::Transform, index, pool)?;
                    } else {
                        index += 1;
                    }
                }
            }
            // §274：`astrolabe` / `empty_cage` —— **欠着**几次牌组编辑，由页面来问。
            // ⚠️ 这里**不动** `pending`：它属于正在进行的那个流程（奖励屏/宝箱/事件），
            // 抢过来会把玩家正看着的那一屏顶掉。
            RelicEffect::PickupPick(change, picks) => {
                self.pickup_change = Some(change);
                self.pickup_picks = picks;
            }
                        RelicEffect::HealUp(amount) => self.heal_after_combat(amount),
            RelicEffect::EndOfCombatHeal(_)
            | RelicEffect::StartCombatBlock(_)
            | RelicEffect::StartCombatStatus(_, _)
            | RelicEffect::StartCombatStatusPerCurse(_, _)
            // §269：六个新变体都不是"拿到就生效"（两个按战斗类型、三个在奖励结算时、
            // 一个改精英血量）。
            | RelicEffect::StartCombatStatusInKinds(_, _, _)
            | RelicEffect::StartCombatHealInKinds(_, _)
            | RelicEffect::RewardCardDelta(_, _)
            | RelicEffect::PotionAlwaysDrops
            | RelicEffect::EliteExtraRelic
            | RelicEffect::EliteEnemyHealthPercent(_)
            // §224: 开战给敌人的状态也不是"拿到就生效"。
            | RelicEffect::StartCombatStatusOnEnemies(_, _)
            | RelicEffect::RestHealBonus(_)
            | RelicEffect::EndOfCombatHealIfBelow { .. }
            // §157: none of these fires on pickup either -- the belt slot, the gold rate and the
            // rest bonus are read where they are used.
            | RelicEffect::RestHealPerFiveCards(_)
            | RelicEffect::FightGoldPercent(_)
            | RelicEffect::ExtraPotionSlots(_)
            // §259: the campfire relics change **which options exist**, they do not pay out when
            // they arrive (`CampfireLift` pays at combat start, via `combat_bonus`).
            | RelicEffect::CampfireLift
            | RelicEffect::CampfireToke
            | RelicEffect::CampfireDig
            | RelicEffect::NoRest
            | RelicEffect::NoSmith
            | RelicEffect::CurseMaxHealthUp(_)
            | RelicEffect::CardAddGold(_)
            | RelicEffect::UpgradeAddedCard(_)
            | RelicEffect::GoldGainHeal(_)
            | RelicEffect::NoGoldGain
            | RelicEffect::FloorClimbGold(_)
            | RelicEffect::RemovePriceFlat(_)
            | RelicEffect::ShopDiscountPercent(_)
            | RelicEffect::ShopEntryHeal(_)
            | RelicEffect::UnknownRoomGold(_)
            | RelicEffect::RestEntryNextCombatEnergy(_, _)
            | RelicEffect::NoPotionGain
            | RelicEffect::PotionUseHeal(_)
            | RelicEffect::NoUnknownMonster
            | RelicEffect::TinyChestEveryFourth
            | RelicEffect::CourierRestock
            | RelicEffect::PickupGold(_)
            | RelicEffect::PickupMaxHealthAndHealAll(_)
            | RelicEffect::PickupUpgradeRandom(_, _)
            | RelicEffect::PickupTransformStaples
            | RelicEffect::PickupPick(_, _)
            | RelicEffect::RestCardReward => {}
        }
        self.relics[slot] = id;
        self.relics_len += 1;
        Ok(())
    }

    /// The potion drop chance right now (§157).
    #[must_use]
    pub const fn potion_drop_chance(&self) -> i32 {
        self.potion_chance
    }

    /// How many potion slots the run has: three, plus `potion_belt`'s two (§157).
    #[must_use]
    pub fn potion_slots(&self) -> u8 {
        // §159: Ascension 11 takes one slot away -- and the wiki says the *belt relic still adds
        // two*, so the reduction lands on the base, not on the total (5 → 4 with the belt, exactly
        // what the Potions page spells out).
        let mut slots = if self.at_least(A_POTION_SLOT) {
            BASE_POTION_SLOTS.saturating_sub(1)
        } else {
            BASE_POTION_SLOTS
        };
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::ExtraPotionSlots(extra)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                slots = slots.saturating_add(u8::try_from(extra).unwrap_or(0));
            }
        }
        slots
    }

    /// Is there room for one more potion?
    #[must_use]
    pub fn potion_room(&self) -> bool {
        self.potions_len < self.potion_slots()
    }

    /// Add a potion. Past [`Self::potion_slots`] this is an error (the belt is full).
    /// §271：`sozu` —— "You can no longer obtain Potions"。
    ///
    /// 拒绝而不是静默不加入：`push_potion` 的所有调用方（奖励屏、事件、商店、调试入口）
    /// 都刚把一瓶药水递到玩家手里，**悄悄收下又悄悄丢掉**正是这个仓库一直在禁的那种损失。
    /// 所以除了这里，`roll_reward` 还会**不再掷**药水 —— 奖励屏上根本不会出现那一格。
    pub fn push_potion(&mut self, potion_id: &str) -> Result<(), RunError> {
        if self.holds_relic_effect(RelicEffect::NoPotionGain) {
            return Err(RunError::PotionGainBlocked);
        }
        let id = RunId::new(potion_id).map_err(|_| RunError::BadId)?;
        let slot = self.potions_len as usize;
        if slot >= usize::from(self.potion_slots()) || slot >= MAX_RUN_POTIONS {
            return Err(RunError::Capacity);
        }
        self.potions[slot] = id;
        self.potions_len += 1;
        Ok(())
    }

    /// Throw away belt slot `index`. The survivors keep their order (the belt is a list, not a set).
    ///
    /// Dropping is how the player makes room when the belt is full and a fight offers another one --
    /// which is also what makes [`RunState::take_potion`]'s `Capacity` error actionable instead of a
    /// dead end.
    pub fn drop_potion(&mut self, index: usize) -> Result<(), RunError> {
        if index >= self.potions_len as usize {
            return Err(RunError::NoSuchPotion);
        }
        let last = self.potions_len as usize - 1;
        for slot in index..last {
            self.potions[slot] = self.potions[slot + 1];
        }
        self.potions[last] = RunId::EMPTY;
        self.potions_len -= 1;
        Ok(())
    }

    /// What a relic does when a fight ends.
    ///
    /// # The design, stated once
    ///
    /// A relic's effect is **not** data in this kernel: `REL.RunPrograms` and `REL.CombatRules` are
    /// never executed (there is no run-level program interpreter and no `CombatRules` registry), so
    /// every effect is an explicit rule in [`Self::relic_effect`], keyed on the id. That is a real
    /// limitation and it is made loud instead of quiet: an id that table does not know is
    /// [`RunError::UnsupportedRelic`], never "a relic that does nothing".
    ///
    /// Returns the health actually restored, so a caller can show "+6".
    pub fn end_of_combat(&mut self) -> Result<i32, RunError> {
        let mut healed = 0i32;
        for slot in 0..self.relics_len as usize {
            let id = self.relics[slot].as_str();
            match Self::relic_effect(id) {
                Some(RelicEffect::EndOfCombatHeal(amount)) => {
                    let before = self.health;
                    self.heal_after_combat(amount);
                    healed += self.health - before;
                }
                // §156: Meat on the Bone -- "if your HP is at or below 50%". The percentage is read
                // off the **current** maximum (Pear/Strawberry move it), same as the intent rules do.
                Some(RelicEffect::EndOfCombatHealIfBelow { percent, amount }) => {
                    let max = self.health_max.max(1);
                    if self.health * 100 <= max * percent {
                        let before = self.health;
                        self.heal_after_combat(amount);
                        healed += self.health - before;
                    }
                }
                // The other four are **not** end-of-combat effects: they fire when the relic is
                // granted (`push_relic`) or when a fight starts (`combat_bonus`). Listing them
                // explicitly instead of a `_` arm is what makes "a new effect variant" a compile
                // error here rather than a relic that quietly does nothing at this hook.
                Some(
                    RelicEffect::MaxHealthUp(_)
                    | RelicEffect::HealUp(_)
                    | RelicEffect::StartCombatBlock(_)
                    | RelicEffect::StartCombatStatus(_, _)
                    // §261: 数牌组算层数的那一支同样不是回合末效果。
                    | RelicEffect::StartCombatStatusPerCurse(_, _)
                    // §224: 开战给敌人的状态也不是回合末效果。
                    | RelicEffect::StartCombatStatusOnEnemies(_, _)
                    | RelicEffect::RestHealBonus(_)
                    | RelicEffect::RestHealPerFiveCards(_)
                    | RelicEffect::FightGoldPercent(_)
                    | RelicEffect::ExtraPotionSlots(_)
                    // §259: none of the campfire relics pays out at the end of a fight.
                    | RelicEffect::CampfireLift
                    | RelicEffect::CampfireToke
                    | RelicEffect::CampfireDig
                    | RelicEffect::NoRest
                    | RelicEffect::NoSmith
                    | RelicEffect::StartCombatStatusInKinds(_, _, _)
                    | RelicEffect::StartCombatHealInKinds(_, _)
                    | RelicEffect::RewardCardDelta(_, _)
                    | RelicEffect::PotionAlwaysDrops
                    | RelicEffect::EliteExtraRelic
                    | RelicEffect::EliteEnemyHealthPercent(_)
                    | RelicEffect::Omamori(_)
                    | RelicEffect::CurseMaxHealthUp(_)
                    | RelicEffect::CardAddGold(_)
                    | RelicEffect::UpgradeAddedCard(_)
                    | RelicEffect::GoldGainHeal(_)
                    | RelicEffect::NoGoldGain
                    | RelicEffect::FloorClimbGold(_)
                    | RelicEffect::RemovePriceFlat(_)
                    | RelicEffect::ShopDiscountPercent(_)
                    | RelicEffect::ShopEntryHeal(_)
                    | RelicEffect::UnknownRoomGold(_)
                    | RelicEffect::RestEntryNextCombatEnergy(_, _)
                    | RelicEffect::NoPotionGain
                    | RelicEffect::PotionUseHeal(_)
                    | RelicEffect::NoUnknownMonster
                    | RelicEffect::TinyChestEveryFourth
                    | RelicEffect::CourierRestock
                    | RelicEffect::PickupGold(_)
                    | RelicEffect::PickupMaxHealthAndHealAll(_)
                    | RelicEffect::PickupUpgradeRandom(_, _)
                    | RelicEffect::PickupTransformStaples
                    | RelicEffect::PickupPick(_, _)
                    | RelicEffect::RestCardReward,
                ) => {}
                None => {
                    return Err(RunError::UnsupportedRelic {
                        index: slot as u8,
                    })
                }
            }
        }
        Ok(healed)
    }

    /// The **one** table of relic effects (`port-plan.md` §143 moved it out of `end_of_combat`,
    /// §145 grew it into a pool).
    ///
    /// Three callers read it: `end_of_combat` (what happens), `push_relic` (whether a relic this
    /// kernel cannot run may enter the belt **and** what it does the moment it arrives), and
    /// `combat_bonus` (what it does when a fight starts). Keeping one table is what makes those
    /// three answers unable to disagree.
    #[must_use]
    pub fn relic_effect(id: &str) -> Option<RelicEffect> {
        match id {
            // `inv:§2`: "At the end of combat, heal 6 HP."
            "burning_blood" => Some(RelicEffect::EndOfCombatHeal(BURNING_BLOOD_HEAL)),
            // The wiki's numbers, not invented ones: Pear +10 max HP, Blood Vial +2 HP on pickup,
            // Anchor 10 Block at combat start, Vajra 1 Strength at combat start.
            "pear" => Some(RelicEffect::MaxHealthUp(10)),
            "blood_vial" => Some(RelicEffect::HealUp(2)),
            "anchor" => Some(RelicEffect::StartCombatBlock(10)),
            "vajra" => Some(RelicEffect::StartCombatStatus("standard.strength", 1)),
            // `inv` has no line for this one; the wiki's Thread and Needle is "start each combat
            // with 4 Plated Armor", and Plated Armor itself landed in §149.
            "thread_and_needle" => Some(RelicEffect::StartCombatStatus("standard.plated_armor", 4)),
            // §156 (wiki numbers): Strawberry +7 max HP, Bronze Scales 3 Thorns at combat start,
            // Regal Pillow +15 on rest, Meat on the Bone 12 HP at or below 50%.
            "strawberry" => Some(RelicEffect::MaxHealthUp(7)),
            "bronze_scales" => Some(RelicEffect::StartCombatStatus("standard.thorns", 3)),
            "regal_pillow" => Some(RelicEffect::RestHealBonus(15)),
            "meat_on_the_bone" => Some(RelicEffect::EndOfCombatHealIfBelow {
                percent: 50,
                amount: 12,
            }),
            // §157 (wiki numbers): Eternal Feather 3 HP per 5 cards on rest, Golden Idol +25% fight
            // gold, Potion Belt +2 slots.
            "eternal_feather" => Some(RelicEffect::RestHealPerFiveCards(3)),
            "golden_idol" => Some(RelicEffect::FightGoldPercent(25)),
            "potion_belt" => Some(RelicEffect::ExtraPotionSlots(2)),
            // §221/§224（wiki `Oddly Smooth Stone`）：开战给**英雄** 1 层敏捷。
            "oddly_smooth_stone" => Some(RelicEffect::StartCombatStatus("standard.dexterity", 1)),
            // §224（wiki `Bag of Marbles`）：开战给**所有敌人** 1 层易伤。§222 曾把它挂成
            // `StartCombatStatus`（加在英雄身上）⇒ 英雄自己变易伤、Boss 打不过，被 `ACT1_SLICE` 抓到。
            "bag_of_marbles" => Some(RelicEffect::StartCombatStatusOnEnemies(
                "standard.vulnerable",
                1,
            )),
            // §259（wiki `Rest Sites`）：三件**开选项**的遗物 + 三件**改选项**的遗物。
            // 六件的数字都在这一行里，因为 `Lift`/`Toke`/`Dig` 没有"数值"可言 —— 它们改的是
            // 选项集合，而选项集合是 `campfire_options` 现算的。
            "girya" => Some(RelicEffect::CampfireLift),
            "peace_pipe" => Some(RelicEffect::CampfireToke),
            "shovel" => Some(RelicEffect::CampfireDig),
            // 两件关闭 Rest：`Coffee Dripper`（Boss）/ `Mark of the Bloom`（事件）。
            "coffee_dripper" => Some(RelicEffect::NoRest),
            "mark_of_the_bloom" => Some(RelicEffect::NoRest),
            // §259：`Fusion Hammer` 关闭 Smith；`Dream Catcher` 让休息额外给一次卡牌奖励。
            "fusion_hammer" => Some(RelicEffect::NoSmith),
            "dream_catcher" => Some(RelicEffect::RestCardReward),
            // §260：**战斗开始类 / 回合末类**八件 —— 全部走 `StartCombatStatus`：遗物本身没有
            // 逻辑，它只是"开战时挂一条带触发器的状态"（`TurnStarted` / `TurnEnded` 由内核派发，
            // 规则全在内容里）。这条路能成立，是因为内容状态已经能读
            // `combatantDefensivePool` / `combatantZoneCount` / `cardsPlayedLastTurn`。
            "orichalcum" => Some(RelicEffect::StartCombatStatus("standard.orichalcum", 1)),
            "mercury_hourglass" => {
                Some(RelicEffect::StartCombatStatus("standard.mercury_hourglass", 1))
            }
            "horn_cleat" => Some(RelicEffect::StartCombatStatus("standard.horn_cleat", 1)),
            "captains_wheel" => Some(RelicEffect::StartCombatStatus("standard.captains_wheel", 1)),
            "stone_calendar" => Some(RelicEffect::StartCombatStatus("standard.stone_calendar", 1)),
            "cloak_clasp" => Some(RelicEffect::StartCombatStatus("standard.cloak_clasp", 1)),
            "incense_burner" => Some(RelicEffect::StartCombatStatus("standard.incense_burner", 1)),
            "pocketwatch" => Some(RelicEffect::StartCombatStatus("standard.pocketwatch", 1)),
            // §261：同样走 `StartCombatStatus`，但规则有两处不同：
            // * `lantern` / `bag_of_preparation` 只在**第 1 回合**生效（状态自己数回合）；
            // * `ice_cream` / `calipers` 没有触发器 —— 它们靠**标签**让内核的回合机改变行为
            //   （`unspent_energy_carries` / `block_loss_cap`）。内容是"内核读得懂的词汇"。
            "lantern" => Some(RelicEffect::StartCombatStatus("standard.lantern", 1)),
            "bag_of_preparation" => {
                Some(RelicEffect::StartCombatStatus("standard.bag_of_preparation", 1))
            }
            "ice_cream" => Some(RelicEffect::StartCombatStatus("standard.ice_cream", 1)),
            "calipers" => Some(RelicEffect::StartCombatStatus("standard.calipers", 15)),
            // `du_vu_doll`：1 力量 / 每张诅咒。层数由**战斗构建方**数牌组算出来（见
            // `per_curse_statuses`）—— `rd-run` 不读内容，所以它不可能自己数。
            "du_vu_doll" => Some(RelicEffect::StartCombatStatusPerCurse("standard.strength", 1)),
            // §262：**每第 N 张某类型牌**那一类 —— 计数据在状态自己的计数器上，
            // 只数哪种牌由内容问 `event.bool(card.hasTag.attack|skill)` 决定。
            "kunai" => Some(RelicEffect::StartCombatStatus("standard.kunai", 1)),
            "shuriken" => Some(RelicEffect::StartCombatStatus("standard.shuriken", 1)),
            "ornamental_fan" => Some(RelicEffect::StartCombatStatus("standard.ornamental_fan", 1)),
            "letter_opener" => Some(RelicEffect::StartCombatStatus("standard.letter_opener", 1)),
            "nunchaku" => Some(RelicEffect::StartCombatStatus("standard.nunchaku", 1)),
            "ink_bottle" => Some(RelicEffect::StartCombatStatus("standard.ink_bottle", 1)),
            // `pen_nib` 的状态在**第 9 张**攻击时挂 `standard.double_damage`（见内容脚本的注释）：
            // `CardPlayed` 触发器在卡牌节目**之后**派发，所以"第 10 张挂"会翻倍到第 11 张。
            "pen_nib" => Some(RelicEffect::StartCombatStatus("standard.pen_nib", 1)),
            // §263：**敌人死亡时**（第一条走新事件 `FoeDowned` 的内容触发器）+ **伤害管线改写**
            // 三件（规则在内核 `exec.rs::S6a`，这里只挂载体）。
            "gremlin_horn" => Some(RelicEffect::StartCombatStatus("standard.gremlin_horn", 1)),
            "the_specimen" => Some(RelicEffect::StartCombatStatus("standard.the_specimen", 1)),
            "the_boot" => Some(RelicEffect::StartCombatStatus("standard.the_boot", 1)),
            "torii" => Some(RelicEffect::StartCombatStatus("standard.torii", 1)),
            "tungsten_rod" => Some(RelicEffect::StartCombatStatus("standard.tungsten_rod", 1)),
            // §264：**改写别的状态幅值**（两条 `AppliesToStatusId`）+ 施加易伤时附带虚弱
            // （`event.statusIs`）。三件都是纯内容，内核只提供"参数"这两条基建。
            "paper_phrog" => Some(RelicEffect::StartCombatStatus("standard.paper_phrog", 1)),
            "paper_krane" => Some(RelicEffect::StartCombatStatus("standard.paper_krane", 1)),
            "champion_belt" => Some(RelicEffect::StartCombatStatus("standard.champion_belt", 1)),
            // §265：**改状态施加**三件（放大 / 免疫 / 免疫）+ 开战给敌人上毒一件。
            "snecko_skull" => Some(RelicEffect::StartCombatStatus("standard.snecko_skull", 1)),
            // §283：`snecko_eye`（Boss）—— 开战挂**一条状态**，它的两条规则全在内容里
            // （`standard.snecko_eye` 的 `TurnStarted` 触发器：首回合挂 Confused + 每回合抽 2）。
            "snecko_eye" => Some(RelicEffect::StartCombatStatus("standard.snecko_eye", 1)),
            "ginger" => Some(RelicEffect::StartCombatStatus("standard.ginger", 1)),
            "turnip" => Some(RelicEffect::StartCombatStatus("standard.turnip", 1)),
            // `twisted_funnel` 走**敌人**那张表（§224 的 `StartCombatStatusOnEnemies`）。
            // §266：条件修饰器（`red_skull`）+ 同侧改写（`odd_mushroom`）。
            "red_skull" => Some(RelicEffect::StartCombatStatus("standard.red_skull", 1)),
            "odd_mushroom" => Some(RelicEffect::StartCombatStatus("standard.odd_mushroom", 1)),
            // §267：零基建批次 —— 轮次轴 / 反应轴（全部 `StartCombatStatus` + 内容触发器）。
            "ring_of_the_snake" => Some(RelicEffect::StartCombatStatus("standard.ring_of_the_snake", 1)),
            "ring_of_the_serpent" => {
                Some(RelicEffect::StartCombatStatus("standard.ring_of_the_serpent", 1))
            }
            "philosophers_stone" => {
                Some(RelicEffect::StartCombatStatus("standard.philosophers_stone", 1))
            }
            "happy_flower" => Some(RelicEffect::StartCombatStatus("standard.happy_flower", 1)),
            "art_of_war" => Some(RelicEffect::StartCombatStatus("standard.art_of_war", 1)),
            "brimstone" => Some(RelicEffect::StartCombatStatus("standard.brimstone", 1)),
            "mark_of_pain" => Some(RelicEffect::StartCombatStatus("standard.mark_of_pain", 1)),
            "mutagenic_strength" => {
                Some(RelicEffect::StartCombatStatus("standard.mutagenic_strength", 1))
            }
            "centennial_puzzle" => {
                Some(RelicEffect::StartCombatStatus("standard.centennial_puzzle", 1))
            }
            "runic_cube" => Some(RelicEffect::StartCombatStatus("standard.runic_cube", 1)),
            "charons_ashes" => Some(RelicEffect::StartCombatStatus("standard.charons_ashes", 1)),
            "duality" => Some(RelicEffect::StartCombatStatus("standard.duality", 1)),
            "akabeko" => Some(RelicEffect::StartCombatStatus("standard.akabeko", 1)),
            // 开战载体：不需要自己的状态，直接把**那条**状态挂上去。
            "clockwork_souvenir" => Some(RelicEffect::StartCombatStatus("standard.artifact", 1)),
            "gremlin_visage" => Some(RelicEffect::StartCombatStatus("standard.weak", 1)),
            "fossilized_helix" => Some(RelicEffect::StartCombatStatus("standard.buffer", 1)),
            "red_mask" => Some(RelicEffect::StartCombatStatusOnEnemies("standard.weak", 1)),
            // 拾取即生效。
            "mango" => Some(RelicEffect::MaxHealthUp(14)),
            // §268：零基建档收尾 —— 掉血兑现 / Power 回血 / 保留手牌 / 死亡预防 / 手牌空抽牌。
            "self_forming_clay" => {
                Some(RelicEffect::StartCombatStatus("standard.self_forming_clay", 1))
            }
            "bird_faced_urn" => Some(RelicEffect::StartCombatStatus("standard.bird_faced_urn", 1)),
            "runic_pyramid" => Some(RelicEffect::StartCombatStatus("standard.runic_pyramid", 1)),
            "lizard_tail" => Some(RelicEffect::StartCombatStatus("standard.lizard_tail", 1)),
            "unceasing_top" => Some(RelicEffect::StartCombatStatus("standard.unceasing_top", 1)),
            // §269：**战斗类型**层（只在精英/Boss 战里生效的三件）。
            //   `sling_of_courage`：精英战 +2 力量；
            //   `slavers_collar`：Boss/精英战每回合 +1 能量（`TurnStartEnergy` 修饰器）；
            //   `pantograph`：Boss 战开战回 25。
            "sling_of_courage" => Some(RelicEffect::StartCombatStatusInKinds(
                "standard.strength",
                2,
                KindMask::ELITE,
            )),
            "slavers_collar" => Some(RelicEffect::StartCombatStatusInKinds(
                "standard.slavers_collar",
                1,
                KindMask(2 | 4),
            )),
            "pantograph" => {
                Some(RelicEffect::StartCombatHealInKinds(25, KindMask::BOSS))
            }
            // §269：**奖励层**五件。
            //   `question_card`：卡牌奖励 +1 张（任何战斗）；
            //   `busted_crown`：卡牌奖励 -2 张（能量那一半走 `busted_crown_energy` 状态）；
            //   `prayer_wheel`：**普通怪**多 1 张；
            //   `white_beast_statue`：药水必掉；
            //   `black_star`：精英多掉一件遗物（直接塞进包，理由见变体的文档）。
            "preserved_insect" => Some(RelicEffect::EliteEnemyHealthPercent(-25)),
            "question_card" => Some(RelicEffect::RewardCardDelta(1, KindMask::ALL)),
            "prayer_wheel" => Some(RelicEffect::RewardCardDelta(1, KindMask::NORMAL)),
            "white_beast_statue" => Some(RelicEffect::PotionAlwaysDrops),
            "black_star" => Some(RelicEffect::EliteExtraRelic),
            // §270：加牌类（全部落在 `push_card` 一个点上）。
            "omamori" => Some(RelicEffect::Omamori(OMAMORI_CHARGES)),
            "darkstone_periapt" => Some(RelicEffect::CurseMaxHealthUp(6)),
            "ceramic_fish" => Some(RelicEffect::CardAddGold(9)),
            "molten_egg" => Some(RelicEffect::UpgradeAddedCard(CardKind::Attack)),
            "toxic_egg" => Some(RelicEffect::UpgradeAddedCard(CardKind::Skill)),
            "frozen_egg" => Some(RelicEffect::UpgradeAddedCard(CardKind::Power)),
            // §270：金币/商店类。
            "bloody_idol" => Some(RelicEffect::GoldGainHeal(5)),
            "ectoplasm" => Some(RelicEffect::NoGoldGain),
            "maw_bank" => Some(RelicEffect::FloorClimbGold(12)),
            "smiling_mask" => Some(RelicEffect::RemovePriceFlat(50)),
            "membership_card" => Some(RelicEffect::ShopDiscountPercent(50)),
            // §271：**节点类**三件（都落在 `begin_node` 的 `NodeKind` 分支上）。
            "meal_ticket" => Some(RelicEffect::ShopEntryHeal(15)),
            "ssserpent_head" => Some(RelicEffect::UnknownRoomGold(50)),
            "ancient_tea_set" => Some(RelicEffect::RestEntryNextCombatEnergy(
                "standard.ancient_tea_set",
                1,
            )),
            // §271：药水类两件。
            "sozu" => Some(RelicEffect::NoPotionGain),
            "toy_ornithopter" => Some(RelicEffect::PotionUseHeal(5)),
            // §273：`the_courier` —— 两个半：-20% 折扣（`ShopDiscountPercent`）+ 买完补货。
            "the_courier" => Some(RelicEffect::ShopDiscountPercent(20)),
            // §272：`?` 房分流的两件（规则在 `roll_unknown_room` 里）。
            "juzu_bracelet" => Some(RelicEffect::NoUnknownMonster),
            "tiny_chest" => Some(RelicEffect::TinyChestEveryFourth),
            // §274：**拾取类**（全部落在 `push_relic` 的副作用区）。
            "old_coin" => Some(RelicEffect::PickupGold(300)),
            "lees_waffle" => Some(RelicEffect::PickupMaxHealthAndHealAll(7)),
            "war_paint" => Some(RelicEffect::PickupUpgradeRandom(CardKind::Skill, 2)),
            "whetstone" => Some(RelicEffect::PickupUpgradeRandom(CardKind::Attack, 2)),
            "pandoras_box" => Some(RelicEffect::PickupTransformStaples),
            "astrolabe" => Some(RelicEffect::PickupPick(DeckChange::TransformAndUpgrade, 3)),
            "empty_cage" => Some(RelicEffect::PickupPick(DeckChange::Remove, 2)),
            // `black_blood`：战后回 12（wiki 的 "Replaces Burning Blood" 那一半见 §268.3）。
            "black_blood" => Some(RelicEffect::EndOfCombatHeal(12)),
            // §269：`busted_crown` 的**能量**那一半（无条件挂）。它的另一半（奖励卡数 -2）在
            // `EXTRA_REWARD_CARD_DELTAS` 里 —— 一件遗物有两半，而 `relic_effect` 只能表达一个。
            "busted_crown" => Some(RelicEffect::StartCombatStatus("standard.busted_crown", 1)),
            "twisted_funnel" => {
                Some(RelicEffect::StartCombatStatusOnEnemies("standard.poison", 4))
            }
            _ => None,
        }
    }

    /// Does this kernel implement relic `id`'s effect? See [`Self::relic_effect`].
    #[must_use]
    pub fn relic_is_implemented(id: &str) -> bool {
        Self::relic_effect(id).is_some()
    }

    /// What the relics do **at the start of a fight** (§145).
    ///
    /// Summed, not "the first one wins": two relics that both give Block add up, which is what the
    /// player expects and what the belt's order must not silently decide.
    #[must_use]
    pub fn combat_bonus(&self) -> CombatBonus {
        self.combat_bonus_for(FightKind::Normal)
    }

    /// §269：**按战斗类型**算的开战加成 —— 有几件遗物只在精英/Boss 战里生效
    /// （`sling_of_courage` / `slavers_collar` / `pantograph`）。
    ///
    /// 旧入口 [`Self::combat_bonus`] 保留为 `Normal`：它的调用方（大量测试、`rd-wasm` 的
    /// 非战斗路径）没有"这一场是什么类型"这个概念，而 `Normal` 正是那些地方唯一说得通的答案。
    #[must_use]
    pub fn combat_bonus_for(&self, kind: FightKind) -> CombatBonus {
        let mut bonus = CombatBonus::default();
        for slot in 0..self.relics_len as usize {
            match Self::relic_effect(self.relics[slot].as_str()) {
                Some(RelicEffect::StartCombatBlock(amount)) => bonus.block += amount,
                Some(RelicEffect::StartCombatStatusOnEnemies(id, stacks)) => {
                    // §224: 给**敌人**的那张表。合并规则与英雄那张相同（两件遗物给同一条状态
                    // 要相加，不是覆盖）。
                    let mut merged = false;
                    for entry in bonus.enemy_statuses.iter_mut().take(bonus.enemy_status_count) {
                        if let Some(existing) = entry {
                            if existing.id == id {
                                existing.stacks += stacks;
                                merged = true;
                                break;
                            }
                        }
                    }
                    if !merged && !bonus.push_enemy_status(id, stacks) {
                        // 表满 = 内容的一次冲突，不能静默丢。
                        // `combat_bonus` 没有 Result 通道（它是纯读），所以这里的"响亮"是
                        // 一条断言级的事实：内容里最多 4 件这类遗物。
                        debug_assert!(false, "too many enemy combat-start statuses");
                    }
                }
                // §259：`Girya` 的力量**不是常量**，而是"用过几次 Lift"。
                // 这里把它折成与 `StartCombatStatus` 同一张表，于是后面的合并规则、去重规则、
                // 与 `Vajra` 相加的规则全都自动成立（用过 2 次 Lift + Vajra = 3 层）。
                Some(RelicEffect::CampfireLift) => {
                    if self.girya_lifts > 0 {
                        let stacks = i32::from(self.girya_lifts);
                        let mut merged = false;
                        for entry in bonus.statuses.iter_mut().take(bonus.status_count) {
                            if let Some(existing) = entry {
                                if existing.id == "standard.strength" {
                                    existing.stacks += stacks;
                                    merged = true;
                                    break;
                                }
                            }
                        }
                        if !merged {
                            let _ = bonus.push_status("standard.strength", stacks);
                        }
                    }
                }
                Some(RelicEffect::StartCombatStatusInKinds(id, stacks, kinds)) => {
                    // §269：掩码不覆盖这一场 ⇒ 这条遗物今天不存在。
                    if kinds.covers(kind) {
                        let mut merged = false;
                        for entry in bonus.statuses.iter_mut().take(bonus.status_count) {
                            if let Some(existing) = entry {
                                if existing.id == id {
                                    existing.stacks += stacks;
                                    merged = true;
                                    break;
                                }
                            }
                        }
                        if !merged {
                            let _ = bonus.push_status(id, stacks);
                        }
                    }
                }
                Some(RelicEffect::StartCombatHealInKinds(amount, kinds)) => {
                    if kinds.covers(kind) {
                        bonus.start_heal += amount;
                    }
                }
                Some(RelicEffect::StartCombatStatusPerCurse(id, stacks)) => {
                    // §261：与上一支同样的合并规则（两件遗物给同一条状态要相加）。
                    let mut merged = false;
                    for entry in bonus.per_curse_statuses.iter_mut().take(bonus.per_curse_status_count)
                    {
                        if let Some(existing) = entry {
                            if existing.id == id {
                                existing.stacks += stacks;
                                merged = true;
                                break;
                            }
                        }
                    }
                    if !merged {
                        let _ = bonus.push_per_curse_status(id, stacks);
                    }
                }
                Some(RelicEffect::StartCombatStatus(id, stacks)) => {
                    // Two relics granting the same status must **merge**, not overwrite: the same
                    // rule the kernel uses when a status is applied twice.
                    let mut merged = false;
                    for entry in bonus.statuses.iter_mut().take(bonus.status_count) {
                        if let Some(existing) = entry {
                            if existing.id == id {
                                existing.stacks += stacks;
                                merged = true;
                                break;
                            }
                        }
                    }
                    if !merged {
                        let _ = bonus.push_status(id, stacks);
                    }
                }
                Some(
                    RelicEffect::EndOfCombatHeal(_)
                    | RelicEffect::EndOfCombatHealIfBelow { .. }
                    | RelicEffect::MaxHealthUp(_)
                    | RelicEffect::HealUp(_)
                    | RelicEffect::RestHealBonus(_)
                    | RelicEffect::RestHealPerFiveCards(_)
                    | RelicEffect::FightGoldPercent(_)
                    | RelicEffect::ExtraPotionSlots(_)
                    // §259: the six campfire-shaped effects do nothing at combat start **except**
                    // `CampfireLift`, which is folded in explicitly just above (it is a run-time
                    // count, not a constant, so it cannot be a `StartCombatStatus`).
                    | RelicEffect::CampfireLift
                    | RelicEffect::CampfireToke
                    | RelicEffect::CampfireDig
                    | RelicEffect::NoRest
                    | RelicEffect::NoSmith
                    | RelicEffect::StartCombatStatusInKinds(_, _, _)
                    | RelicEffect::StartCombatHealInKinds(_, _)
                    | RelicEffect::RewardCardDelta(_, _)
                    | RelicEffect::PotionAlwaysDrops
                    | RelicEffect::EliteExtraRelic
                    | RelicEffect::EliteEnemyHealthPercent(_)
                    | RelicEffect::Omamori(_)
                    | RelicEffect::CurseMaxHealthUp(_)
                    | RelicEffect::CardAddGold(_)
                    | RelicEffect::UpgradeAddedCard(_)
                    | RelicEffect::GoldGainHeal(_)
                    | RelicEffect::NoGoldGain
                    | RelicEffect::FloorClimbGold(_)
                    | RelicEffect::RemovePriceFlat(_)
                    | RelicEffect::ShopDiscountPercent(_)
                    | RelicEffect::ShopEntryHeal(_)
                    | RelicEffect::UnknownRoomGold(_)
                    | RelicEffect::RestEntryNextCombatEnergy(_, _)
                    | RelicEffect::NoPotionGain
                    | RelicEffect::PotionUseHeal(_)
                    | RelicEffect::NoUnknownMonster
                    | RelicEffect::TinyChestEveryFourth
                    | RelicEffect::CourierRestock
                    | RelicEffect::PickupGold(_)
                    | RelicEffect::PickupMaxHealthAndHealAll(_)
                    | RelicEffect::PickupUpgradeRandom(_, _)
                    | RelicEffect::PickupTransformStaples
                    | RelicEffect::PickupPick(_, _)
                    | RelicEffect::RestCardReward,
                )
                | None => {}
            }
        }
        // §271：`ancient_tea_set` —— 篝火之后的那**一场**多 2 能量。挂的是内容状态
        // （`standard.ancient_tea_set` 自己的 `TurnStarted` 程序），运行层只说"挂哪一条"。
        if self.tea_set_pending {
            if let Some(RelicEffect::RestEntryNextCombatEnergy(id, stacks)) =
                self.first_relic_effect_of(RelicEffect::RestEntryNextCombatEnergy(
                    "standard.ancient_tea_set",
                    1,
                ))
            {
                let mut merged = false;
                for entry in bonus.statuses.iter_mut().take(bonus.status_count) {
                    if let Some(existing) = entry {
                        if existing.id == id {
                            existing.stacks += stacks;
                            merged = true;
                            break;
                        }
                    }
                }
                if !merged {
                    let _ = bonus.push_status(id, stacks);
                }
            }
        }
        // §270：`RELIC_SECOND_HALVES` 里属于"开战加成"的那一类（`ectoplasm` 的每回合 +1 能量）。
        // 合并规则与上面那张表一致（同一条状态相加）—— 它产出的就是同一件事。
        for (relic, effect) in RELIC_SECOND_HALVES.iter().copied() {
            let RelicEffect::StartCombatStatus(id, stacks) = effect else {
                continue;
            };
            if !self.holds_relic(relic) {
                continue;
            }
            let mut merged = false;
            for entry in bonus.statuses.iter_mut().take(bonus.status_count) {
                if let Some(existing) = entry {
                    if existing.id == id {
                        existing.stacks += stacks;
                        merged = true;
                        break;
                    }
                }
            }
            if !merged {
                let _ = bonus.push_status(id, stacks);
            }
        }
        bonus
    }

    /// Take the `Burning Blood` heal (`inv:§2`: +6 HP at the end of combat). **Capped at the
    /// maximum**, never above it. This is M1's only relic effect and it is deliberate: without it
    /// every fight would end with the wrong HP, and HP is the number the whole run walks on.
    pub fn heal_after_combat(&mut self, amount: i32) {
        self.health = (self.health + amount).min(self.health_max);
    }

    /// Adjust health (damage negative). Clamped to `0..=health_max`; the floor matters because a
    /// run at 0 HP is over, not negative.
    pub fn adjust_health(&mut self, delta: i32) {
        self.health = (self.health + delta).clamp(0, self.health_max);
    }

    /// Raise the maximum HP **and** heal by the same amount (§157: Fruit Juice, "Gain 5 Max HP").
    ///
    /// Same rule as a relic that raises the maximum (`push_relic`'s `MaxHealthUp`): StS's "+max HP"
    /// always comes with the health, so the two cannot drift apart.
    pub fn raise_max_health(&mut self, amount: i32) {
        self.health_max += amount;
        self.adjust_health(amount);
    }

    /// Add or spend gold, clamped at 0.
    /// §270：**唯一**改金币的地方 —— 所以两条"金币方向"的遗物都挂在这里。
    ///
    /// | 遗物 | 规则 | 落点 |
    /// |---|---|---|
    /// | `ectoplasm` | "You can no longer gain Gold" | 正增量变 0（**花出去**不受影响） |
    /// | `bloody_idol` | "Whenever you gain Gold, heal 5 HP" | 金币**真的**涨了才回血 |
    ///
    /// ⚠️ `bloody_idol` 判的是**实际涨了多少**（`self.gold` 前后的差），不是 `delta > 0`：
    /// 否则 `ectoplasm` 挡住的那一笔也会回血 —— 玩家没得到金币却回了 5 点血，
    /// 而这条在页面上完全看不出来（两个数字各自都"合理"）。
    pub fn adjust_gold(&mut self, delta: i32) {
        let delta = if delta > 0 && self.holds_relic_effect(RelicEffect::NoGoldGain) {
            0
        } else {
            delta
        };
        let before = self.gold;
        self.gold = (self.gold + delta).max(0);
        let gained = self.gold - before;
        if gained > 0 {
            if let Some(RelicEffect::GoldGainHeal(amount)) =
                self.first_relic_effect_of(RelicEffect::GoldGainHeal(5))
            {
                self.heal_after_combat(amount);
            }
        }
    }

    // ---- walking the map -------------------------------------------------------------------

    /// Where the cursor can go next.
    ///
    /// Before the first step, that is **every node on floor 1** (`inv:§7.2`: the player picks a
    /// start). Afterwards, it is the current node's out-edges.
    #[must_use]
    pub fn reachable(&self) -> Reachable {
        let mut out = Reachable::default();
        // **Nothing is legal while a choice is pending** -- the pre-run blessing (inv:§7.1), a won
        // fight's reward, a shop, a campfire, an event. Offering steps here is what let a map click
        // overwrite the choice panel with a refusal, which left the player with no way forward at
        // all (found by hand, 2026-10-22: "第一个节点就点不进去").
        if self.pending != Pending::None {
            return out;
        }
        if self.node < 0 {
            let Some(first) = self.map.row_first(0) else {
                return out;
            };
            let count = self.map.row(0).map_or(0, |row| row.len());
            for local in 0..count {
                out.push(first + local as u8);
            }
            return out;
        }
        let target_row = self.floor as usize; // 0-based row *after* the current one
        if target_row >= ROWS {
            // Floor 15 is the last row. `inv:§7.2` puts the boss at floor 16 -- off the map, so it
            // is offered as the sentinel rather than as an edge. It is the **only** way forward,
            // which is what makes an act completable.
            // Not while standing on it: the boss is the end of the walk, and offering it again
            // would let a caller walk into the fight it is already in.
            if !self.boss_beaten && self.node != i32::from(crate::map::BOSS_NODE) {
                out.push(crate::map::BOSS_NODE);
            }
            return out;
        }
        let Some(row) = self.map.row(target_row - 1) else {
            return out;
        };
        let Some((row_index, local)) = self.map.locate(self.node as u8) else {
            return out;
        };
        let Some(source) = row.node(local) else {
            return out;
        };
        for &edge in source.out_targets() {
            if let Some(global) = self.map.global_of(row_index + 1, edge as usize) {
                out.push(global);
            }
        }
        out
    }

    /// Move the cursor to `target`. **Walking only**: nothing is settled here (see
    /// `docs/spec/env-abi.md` §11.5), and a target that is not reachable is an error rather than a
    /// silent stay-put.
    pub fn enter_node(&mut self, target: u8) -> Result<(), RunError> {
        if !self.reachable().contains(target) {
            return Err(RunError::NotReachable);
        }
        // **You settle a node before you walk on.** A fight is settled by `mark_resolved()` when it
        // ends (the caller does that), an event by `resolve_event`, a rest/shop/chest by their own
        // actions -- so this one check covers all of them, and it is what stops "step onto a fight,
        // then step straight onto the next node" from being a legal move.
        if self.node >= 0 && !self.node_resolved() {
            return Err(RunError::NodeNotSettled);
        }
        // Nothing is legal before the pre-run blessing is chosen (`inv:§7.1`).
        if self.pending == Pending::Start {
            return Err(RunError::WrongPhase);
        }
        // ⚠️ **先验证再动**（§161.2(a)）：`check_invariants` 曾经在游标已经移动之后才跑，
        // 于是一条不变量失败会留下"页面说被拒、内核却已经站在那个节点上"的局面 —— 页面随后
        // 卡在一个它settle不了、也走不掉的节点里（soak 的 320 个死控件就是这么来的）。
        let mut probe = *self;
        if target == crate::map::BOSS_NODE {
            // `inv:§7.2`: the boss is floor 16, one row past the map's last.
            probe.node = i32::from(target);
            probe.floor = ROWS as i32 + 1;
        } else {
            let Some((row, _)) = self.map.locate(target) else {
                return Err(RunError::BadNode);
            };
            probe.node = i32::from(target);
            probe.floor = row as i32 + 1;
        }
        probe.check_invariants()?;
        let climbed = probe.floor > self.floor;
        self.node = probe.node;
        self.floor = probe.floor;
        // §270：`maw_bank` —— "Whenever you climb a floor, gain 12 Gold"。
        // 判据是**楼层涨了**（`climbed`），不是"进了一个节点"：Boss 节点（第 16 层）与普通节点
        // 走的是同一条路，而"重进当前层"是不可能的（`reachable` 只给下层）。
        if climbed && !self.maw_bank_broken {
            if let Some(RelicEffect::FloorClimbGold(amount)) =
                self.first_relic_effect_of(RelicEffect::FloorClimbGold(12))
            {
                self.adjust_gold(amount);
            }
        }
        self.check_invariants()
    }

    // ---- settling a node -------------------------------------------------------------------

    /// Which act this run is on (1-based).
    #[must_use]
    pub const fn act(&self) -> u8 {
        self.act
    }

    /// Has the **last** act been cleared (the run is won)?
    #[must_use]
    pub const fn boss_beaten(&self) -> bool {
        self.boss_beaten
    }

    /// Record the act clear. Called by the fight epilogue when the boss falls -- the fight is
    /// settled outside this crate, so the caller has to say so (same shape as `mark_resolved`).
    pub fn mark_boss_beaten(&mut self) {
        self.mark_resolved();
        // §159: StS heals you **to full** when an act's boss falls (that is what the missing-health
        // rule in `A5` is a fraction *of* -- before this the heal did not exist at all, so Ascension
        // 5 would have been a rule about nothing). Ascension 5 makes it 75% of the missing health.
        let missing = (self.health_max - self.health).max(0);
        let healed = if self.at_least(A_BOSS_HEAL) {
            missing * 3 / 4
        } else {
            missing
        };
        self.health = (self.health + healed).min(self.health_max);
        if self.act >= MAX_ACT {
            // §189 `A20`：最后一幕要**两个** Boss。第一个倒下后节点重新可打（清 `resolved`），
            // 直到第二个也倒下才算赢。奖励屏照旧给两次：每一个 Boss 都是一场真的战斗。
            if self.at_least(A_DOUBLE_BOSS) && self.bosses_fought == 0 {
                self.bosses_fought = 1;
                // 调用方唯一的入口是"游标在 Boss 上、且节点没结算过" ⇒ 把节点重新打开。
                self.resolved = [0; 2];
                // ⚠️ **不要动 `pending`**：`rd_run_fight_end` 的顺序是"先掷奖励（Pending::Reward）、
                // 再 mark_boss_beaten"，把 pending 清成 None 会把第一个 Boss 的奖励屏关掉 ——
                // 玩家白打一场。这条是写测试时发现的，判据见 `a20_…` 里的奖励屏断言。
                return;
            }
            // The last act's boss: the run is won.
            self.boss_beaten = true;
            return;
        }
        // **Advance to the next act**: the walk starts over from the first row, with the hero's
        // health, deck and relics carried across (the fight already folded the health back).
        self.act += 1;
        // §157: the wiki resets the potion chance "at the start of each Act".
        self.potion_chance = POTION_DROP_START;
        // §272：`?` 房的三条概率也换幕归零（wiki："The values for all types are reset in between
        // acts"）。⚠️ 这三条计数在 §272 之前**根本没有消费者**，所以"换幕归零"这条规则也一直
        // 没有实现 —— 现在它有了。
        self.unknown = [0; 3];
        self.tiny_chest_rooms = 0;
        self.unknown_room = UnknownRoom::Unresolved;
        self.node = -1;
        self.floor = 0;
        self.pending = Pending::None;
        self.resolved = [0; 2];
        self.boss_beaten = false;
        // §189：换幕重置"这一幕打了几个 Boss"。
        self.bosses_fought = 0;

        // **A new act gets a new map** (`port-plan.md` §131). The seed is derived from the run seed
        // and the act number, so the map is deterministic for a given run -- the same discipline the
        // opening map follows (`RunMap::generate` on the run's own RNG).
        //
        // ⚠️ A map that failed to generate here would be catastrophic (the run would have no walk),
        // so the old map is kept on failure and `map_generation_failed` is raised -- the caller sees
        // it instead of walking a stale map by accident.
        let previous = self.map;
        let seed = self.act_seed();
        let mut rng = RunRng::new(seed);
        match RunMap::generate_at(&mut rng, self.ascension()) {
            Ok(map) => {
                self.map = map;
                self.map_generation_failed = false;
            }
            Err(_) => {
                self.map = previous;
                self.map_generation_failed = true;
            }
        }
    }

    /// The map seed for the **current** act: the run seed folded with the act number.
    ///
    /// Act 1 keeps the original seed (so a run's first map is exactly what it always was); later acts
    /// get their own, and the fold is a fixed constant so the whole thing stays reproducible.
    #[must_use]
    pub const fn act_seed(&self) -> i32 {
        // ct - 1, so act 1 is **exactly** the opening seed and act 2 is the first fold.
        self.seed
            .wrapping_add(((self.act - 1) as i32).wrapping_mul(0x9E37_79B9u32 as i32))
    }

    /// Did the act-change map generation fail? (It cannot today -- `RunMap::generate` retries and the
    /// generator is total -- but a silent fallback would be exactly the kind of "quietly wrong" this
    /// project keeps banning, so the flag exists and the UI can say so.)
    #[must_use]
    pub const fn map_generation_failed(&self) -> bool {
        self.map_generation_failed
    }

    /// Has the node under the cursor already paid out?
    #[must_use]
    pub fn node_resolved(&self) -> bool {
        let node = self.node;
        if node < 0 {
            return false;
        }
        let bit = node as usize;
        self.resolved[bit / 64] & (1u64 << (bit % 64)) != 0
    }

    /// Mark the node under the cursor as settled. Called by every action that finishes one **and**
    /// by the fight's epilogue (`rd_run_fight_end`), because a fight is settled outside this crate.
    pub fn mark_resolved(&mut self) {
        // §286：节点结清 = "这一场事件战斗的账付过了" ⇒ 档位在这里清。**一个写者**：
        // 事件那条路只负责**置**它，只有这里清，所以"忘记清"不会变成第二场白给的战斗。
        self.event_fight = 0;
        self.event_fight_pool = RunId::EMPTY;
        let node = self.node;
        if node < 0 {
            return;
        }
        let bit = node as usize;
        if bit < 128 {
            self.resolved[bit / 64] |= 1u64 << (bit % 64);
        }
    }

    /// What the node under the cursor is waiting for.
    #[must_use]
    pub const fn pending(&self) -> Pending {
        self.pending
    }

    /// The merchant's stock (empty unless [`Pending::Shop`]).
    #[must_use]
    pub const fn shop(&self) -> &ShopStock {
        &self.shop
    }

    /// What a rest would restore: 30% of maximum HP, rounded down (`inv:§8.1`).
    ///
    /// §160: the Eternal Feather term is **not** here any more. The wiki says it heals on **entering**
    /// the rest site, so it fires in `begin_node` (see [`Self::rest_site_entry_heal`]) and a player
    /// who chooses Smith keeps it. `rest_heal` is what the `Rest` **button** does, and that is only
    /// the 30% plus Regal Pillow.
    #[must_use]
    pub fn rest_heal(&self) -> i32 {
        self.health_max * REST_HEAL_PERCENT / 100 + self.rest_heal_bonus()
    }

    /// The card-count part of the rest heal (`eternal_feather`, §157): 3 HP per **five** cards.
    ///
    /// §160: the multiplication used to come first (`amount * deck_len / 5`), which is a different
    /// function -- it pays pro rata instead of per whole group of five. With `amount = 3`:
    ///
    /// | 牌组 | 应回 | 旧实现 `(3 * n) / 5` |
    /// |---:|---:|---:|
    /// | 8 | 3 | **4** |
    /// | 9 | 3 | **5** |
    /// | 14 | 6 | **8** |
    /// | 10 | 6 | 6 |
    ///
    /// §157 的 `the_new_relics_pay_out` 用 10 张牌，两种写法都是 6 —— 一个分段函数只测了整档，
    /// 所以全绿。这不是"测试不够多"，是**边界没测**。
    #[must_use]
    pub fn rest_heal_per_cards(&self) -> i32 {
        let mut bonus = 0i32;
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::RestHealPerFiveCards(amount)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                bonus += amount * (i32::from(self.deck_len) / 5);
            }
        }
        bonus
    }

    /// The heal for **entering** a rest site (§160).
    ///
    /// The wiki's Eternal Feather page says it in one line: "Heal applies **on entering**, so you can
    /// Rest less often." So the trigger is the room, not the `Rest` choice -- a player who enters and
    /// chooses **Smith** keeps the heal. §157 had bound it to `rest_heal()`, which only `rest()`
    /// calls, so a smith at 8/10 cards silently lost 3 HP of value.
    ///
    /// `mark_rest_entered` is the one-shot guard: the room pays once, whichever button is pressed
    /// first, and `Rest`'s own 30% is a **second**, separate effect.
    #[must_use]
    pub fn rest_site_entry_heal(&self) -> i32 {
        self.rest_heal_per_cards()
    }

    /// The fight-gold multiplier in percent (`golden_idol` = 125, §157).
    #[must_use]
    pub fn fight_gold_percent(&self) -> i32 {
        let mut percent = 100i32;
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::FightGoldPercent(bonus)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                percent += bonus;
            }
        }
        percent
    }

    /// The flat rest bonus from relics (`regal_pillow` = 15, wiki).
    #[must_use]
    pub fn rest_heal_bonus(&self) -> i32 {
        let mut bonus = 0i32;
        let mut slot = 0usize;
        while slot < self.relics_len as usize {
            if let Some(RelicEffect::RestHealBonus(amount)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                bonus += amount;
            }
            slot += 1;
        }
        bonus
    }

    /// What removing a card costs right now: 75, then +25 per removal already made this run
    /// (`inv:§8.2` -- "此后每次使用时 +25，跨店累计").
    #[must_use]
    /// §270：删牌服务的价格**现算**（三项各自独立：升阶涨价、`smiling_mask` 固定价、商店折扣）。
    ///
    /// ⚠️ 不再是 `const fn`：`smiling_mask` 要看遗物表。调用点（商店页与 `remove_card`）都是普通
    /// 函数，所以没有传播成本。
    #[must_use]
    pub fn remove_card_price(&self) -> i32 {
        // §159 `A16`: the removal service is a shop price too, so it carries the same markup.
        let base = if self.holds_relic_effect(RelicEffect::RemovePriceFlat(50)) {
            // §270：`smiling_mask` —— "The merchant's card removal service now always costs 50
            // Gold"。**固定**：`removed_cards` 的 +25/次 对它失效（那是"服务涨价"，而它的原话是
            // "always costs 50"）。折扣仍然在（`Membership Card` 是另一件遗物）。
            SHOP_REMOVE_FLAT
        } else {
            SHOP_REMOVE_BASE + SHOP_REMOVE_STEP * self.removed_cards
        };
        self.shop_price(self.marked_up(base))
    }

    /// §270：商店的**实付价** —— 所有 `ShopDiscountPercent` 相加（`membership_card` 50%）。
    ///
    /// ⚠️ 货架上存的是**挂牌价**（`roll_shop` 在陈列时就把 A16 的涨价算进去了，见那里的注释）。
    /// 折扣**只在付款时**算，所以"页面显示的数"与"真的扣的数"必须是**同一个函数** ——
    /// `rd_run_shop_card_price` / `rd_run_shop_relic_price` / `buy_*` / `remove_card_price`
    /// 全部走这里。两条路各算一次，就会变成"显示 45 扣 90"。
    #[must_use]
    pub fn shop_price(&self, base: i32) -> i32 {
        let mut percent = 100i32;
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::ShopDiscountPercent(discount)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                percent -= discount;
            }
        }
        (base * percent / 100).max(0)
    }

    /// §259：篝火上有哪些选项（wiki `Rest Sites`）。
    ///
    /// 六个布尔**现算**，不缓存：它们各自依赖不同的运行期状态（持有哪些遗物、`Girya` 用了几次、
    /// 牌组里还有没有可升的牌、当前幕有没有拿过红钥匙）。存一份就会与真实状态漂移，而漂移在
    /// 界面上只表现为"一个本该灰掉的按钮能点"。
    ///
    /// | 选项 | 谁给的 | 灰掉的条件（wiki） |
    /// |---|---|---|
    /// | Rest | 默认 | `Coffee Dripper` / `Mark of the Bloom`；**满血也能用** |
    /// | Smith | 默认 | `Fusion Hammer`；**全升完** |
    /// | Recall | 默认 | 本幕已经拿过红钥匙（`ruby_key`） |
    /// | Lift | `Girya` | 已经用满 3 次 |
    /// | Toke | `Peace Pipe` | 牌组空 |
    /// | Dig | `Shovel` | 从不（总是可用） |
    #[must_use]
    pub fn campfire_options(&self) -> CampfireOptions {
        let mut options = CampfireOptions {
            rest: true,
            smith: true,
            // §259：红钥匙一局只有一把；拿到之后 Recall 就没了（wiki："if you have not already
            // obtained the Ruby Key this act"）。
            recall: !self.ruby_key,
            // `Lift` / `Toke` / `Dig` 默认**都没有**：它们由遗物开出来（下面那趟循环）。
            lift: false,
            toke: false,
            dig: false,
        };
        for slot in 0..self.relics_len as usize {
            match Self::relic_effect(self.relics[slot].as_str()) {
                Some(RelicEffect::NoRest) => options.rest = false,
                Some(RelicEffect::NoSmith) => options.smith = false,
                Some(RelicEffect::CampfireLift) => {
                    options.lift = self.girya_lifts < GIRYA_MAX_LIFTS;
                }
                // `Peace Pipe`：牌组非空才有意义（空牌组没有可删的）。
                Some(RelicEffect::CampfireToke) => options.toke = self.deck_len > 0,
                Some(RelicEffect::CampfireDig) => options.dig = true,
                // 其余遗物不改变选项集合 —— 列出来是为了让"新增一个变体"在这里编译报错。
                Some(
                    RelicEffect::EndOfCombatHeal(_)
                    | RelicEffect::EndOfCombatHealIfBelow { .. }
                    | RelicEffect::MaxHealthUp(_)
                    | RelicEffect::HealUp(_)
                    | RelicEffect::StartCombatBlock(_)
                    | RelicEffect::StartCombatStatus(_, _)
                    | RelicEffect::StartCombatStatusPerCurse(_, _)
                    | RelicEffect::StartCombatStatusOnEnemies(_, _)
                    | RelicEffect::RestHealBonus(_)
                    | RelicEffect::RestHealPerFiveCards(_)
                    | RelicEffect::FightGoldPercent(_)
                    | RelicEffect::ExtraPotionSlots(_)
                    | RelicEffect::StartCombatStatusInKinds(_, _, _)
                    | RelicEffect::StartCombatHealInKinds(_, _)
                    | RelicEffect::RewardCardDelta(_, _)
                    | RelicEffect::PotionAlwaysDrops
                    | RelicEffect::EliteExtraRelic
                    | RelicEffect::EliteEnemyHealthPercent(_)
                    | RelicEffect::Omamori(_)
                    | RelicEffect::CurseMaxHealthUp(_)
                    | RelicEffect::CardAddGold(_)
                    | RelicEffect::UpgradeAddedCard(_)
                    | RelicEffect::GoldGainHeal(_)
                    | RelicEffect::NoGoldGain
                    | RelicEffect::FloorClimbGold(_)
                    | RelicEffect::RemovePriceFlat(_)
                    | RelicEffect::ShopDiscountPercent(_)
                    | RelicEffect::ShopEntryHeal(_)
                    | RelicEffect::UnknownRoomGold(_)
                    | RelicEffect::RestEntryNextCombatEnergy(_, _)
                    | RelicEffect::NoPotionGain
                    | RelicEffect::PotionUseHeal(_)
                    | RelicEffect::NoUnknownMonster
                    | RelicEffect::TinyChestEveryFourth
                    | RelicEffect::CourierRestock
                    | RelicEffect::PickupGold(_)
                    | RelicEffect::PickupMaxHealthAndHealAll(_)
                    | RelicEffect::PickupUpgradeRandom(_, _)
                    | RelicEffect::PickupTransformStaples
                    | RelicEffect::PickupPick(_, _)
                    | RelicEffect::RestCardReward,
                )
                | None => {}
            }
        }
        // "全升完 ⇒ Smith 灰掉"：`+` 行在内容里是**另一张卡**，所以"能不能升"要看
        // "这张牌的 id 加上 `+` 之后是不是同一张卡" —— 但运行层不认识内容，所以判据只能是
        // "牌组里有没有一个不带 `+` 的 id"。这与 `upgraded_id` 的来路（调用方给的映射）一致。
        let mut upgradable = false;
        for slot in 0..self.deck_len as usize {
            if !self.deck[slot].as_str().ends_with('+') {
                upgradable = true;
                break;
            }
        }
        options.smith = options.smith && upgradable;
        options
    }

    /// §259：`Lift`（`Girya`）—— 力量 +1 的上限记一次，**当回合不回血、不给状态**。
    ///
    /// 力量从**下一场战斗开始**起生效，并且之后每场都带（`combat_bonus` 按 `girya_lifts` 折算）。
    /// 用满 3 次之后这一步是 `WrongPhase`（选项已经不在列表里了，走到这里说明调用方在猜）。
    pub fn lift(&mut self) -> Result<u8, RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        if self.girya_lifts >= GIRYA_MAX_LIFTS {
            return Err(RunError::WrongPhase);
        }
        if !self.holds_relic_effect(RelicEffect::CampfireLift) {
            return Err(RunError::UnsupportedRelic { index: 0 });
        }
        self.girya_lifts += 1;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(self.girya_lifts)
    }

    /// §259：`Toke`（`Peace Pipe`）—— 从牌组里删一张，**不收钱**。
    pub fn toke(&mut self, card: usize) -> Result<(), RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        if !self.holds_relic_effect(RelicEffect::CampfireToke) {
            return Err(RunError::UnsupportedRelic { index: 0 });
        }
        self.remove_deck_card(card)?;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// §259：`Dig`（`Shovel`）—— 抽一件遗物，**候选池只含 Common/Uncommon/Rare**。
    ///
    /// `relic_pool` 是调用方给的**全量**池（含 Boss/Shop/Event）；过滤在这里做，因为"哪些稀有度
    /// 能被抽到"是规则，而"内容里有哪些遗物"是内容。
    pub fn dig(&mut self, relic_pool: &[PoolRelic<'_>]) -> Result<RunId, RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        if !self.holds_relic_effect(RelicEffect::CampfireDig) {
            return Err(RunError::UnsupportedRelic { index: 0 });
        }
        let mut candidates = [PoolRelic {
            id: "",
            rarity: Rarity::Common,
        }; MAX_POOL];
        let mut count = 0usize;
        for entry in relic_pool {
            if matches!(entry.rarity, Rarity::Common | Rarity::Uncommon | Rarity::Rare) {
                if count >= candidates.len() {
                    return Err(RunError::Capacity);
                }
                candidates[count] = *entry;
                count += 1;
            }
        }
        // §259：用 `Chest` 这条流 —— 遗物抽取本来就跑在它上面（`open_chest`），而 `Dig`
        // 就是"从同一口井里再舀一次"。新开一条流会让**既有种子的洗牌序列整体平移**，
        // 那是 §233 那种"池子一变、某局能不能赢就翻面"的另一形态。
        let relic = self.pick_relic(RunStream::Chest, &candidates[..count])?;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(relic)
    }

    /// §259：`Recall` —— 拿红钥匙（Act 4 的门票）。
    pub fn recall(&mut self) -> Result<(), RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        if self.ruby_key {
            return Err(RunError::WrongPhase);
        }
        self.ruby_key = true;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// §259：这件遗物在不在腰上、以及它的效果是不是 `wanted`（`Copy` 比较，因为变体都是无载荷
    /// 的单元变体）。
    fn holds_relic_effect(&self, wanted: RelicEffect) -> bool {
        for slot in 0..self.relics_len as usize {
            if Self::relic_effect(self.relics[slot].as_str()) == Some(wanted) {
                return true;
            }
        }
        false
    }

    /// Declare what the node under the cursor needs. `card_pool` / `relic_pool` are the content's
    /// candidate ids -- this crate reads no content, so the caller supplies them.
    ///
    /// Returns the node's kind so a caller can branch without re-reading the map.
    pub fn begin_node(
        &mut self,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<crate::map::NodeKind, RunError> {
        if self.node < 0 {
            return Err(RunError::WrongPhase);
        }
        if self.node_resolved() {
            return Err(RunError::NodeResolved);
        }
        if self.node == i32::from(crate::map::BOSS_NODE) {
            // A fight like the others; the caller knows it must use the boss pool.
            self.pending = Pending::None;
            return Ok(crate::map::NodeKind::Boss);
        }
        let Some((row, local)) = self.map.locate(self.node as u8) else {
            return Err(RunError::BadNode);
        };
        let Some(kind) = self
            .map
            .row(row)
            .and_then(|line| line.node(local))
            .map(|node| node.kind)
        else {
            return Err(RunError::BadNode);
        };
        use crate::map::NodeKind;
        self.pending = match kind {
            // A fight is the caller's business: it runs the combat session and calls
            // `end_of_combat` when it is done. Nothing to settle here.
            NodeKind::Combat => Pending::None,
            // §160: **entering** a rest site is its own effect. The wiki's Eternal Feather page:
            // "Heal applies on entering, so you can Rest less often." So the room pays it here,
            // before the player chooses Rest or Smith -- a relic bound to the `rest()` call would
            // have paid nothing to a player who smithed.
            NodeKind::Rest => {
                let heal = self.rest_site_entry_heal();
                if heal > 0 {
                    self.heal_after_combat(heal);
                }
                // §271：`ancient_tea_set` —— "Whenever you enter a Rest Site, start the next
                // combat with 2 extra Energy"。**进门就欠上**（与上面那条 `Eternal Feather`
                // 同一个理由：wiki 说"on entering"，不是"on Rest"）。
                self.owe_tea_set_for_the_next_fight();
                Pending::Rest
            }
            NodeKind::Treasure => Pending::Chest,
            NodeKind::Shop => {
                // §273：与 `?` 房掷出商人时**同一条路**（摆货架 + `meal_ticket`）。
                self.enter_shop(card_pool, relic_pool)?;
                Pending::Shop
            }
            // An elite is a fight like any other: what differs is the pool it draws from and what
            // it pays (`inv:§5.3`), and both live in the caller -- nothing to settle here.
            NodeKind::Elite => Pending::None,
            // A `?` room is an **event** (`inv:§7.3`). The run layer reads no content, so the caller
            // picks which event (`EV`) and then calls `begin_event` -- nothing to settle here.
            NodeKind::Unknown => {
                // §271：`ssserpent_head` —— "Whenever you enter a ? room, gain 50 Gold"。
                // 走 `adjust_gold`，所以 `ectoplasm` 该拦就拦、`bloody_idol` 该回血就回血。
                // wiki 的原话是 "whatever it resolves to"，所以它在掷骰**之前**付。
                if let Some(RelicEffect::UnknownRoomGold(amount)) =
                    self.first_relic_effect_of(RelicEffect::UnknownRoomGold(50))
                {
                    self.adjust_gold(amount);
                }
                // §272：`?` 房分流（wiki `Unknown Location`）。四种结果各走各的既有通道：
                //   宝箱 → `Pending::Chest`（与宝藏节点同一条路）
                //   商人 → 当场摆货架 + `Pending::Shop`（与商店节点同一条路）
                //   战斗 / 事件 → `Pending::None`，由调用方按 `unknown_room()` 决定开哪一场
                match self.roll_unknown_room()? {
                    UnknownRoom::Treasure => Pending::Chest,
                    UnknownRoom::Shop => {
                        // §273：**同一个** `enter_shop` —— `?` 房变成商店也要触发 `meal_ticket`
                        // （wiki 的 Planisphere 页：*"a ? that turns into a shop triggers both"*）。
                        self.enter_shop(card_pool, relic_pool)?;
                        Pending::Shop
                    }
                    UnknownRoom::Monster | UnknownRoom::Event | UnknownRoom::Unresolved => {
                        Pending::None
                    }
                }
            }
            // Nothing is left that M1 refuses; the arm stays so a new kind cannot be silently
            // accepted.
            other => return Err(RunError::NodeNotSettleable(other as u8)),
        };
        Ok(kind)
    }

    /// Rest at a rest site: heal 30% of maximum HP and leave.
    ///
    /// Returns the health actually restored (a run at 79/80 gains 1, not 24).
    pub fn rest(&mut self) -> Result<i32, RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        let before = self.health;
        self.heal_after_combat(self.rest_heal());
        // §259：`Dream Catcher`（"Whenever you Rest, you may add a card to your deck"）—— 休息之后
        // 停在**奖励屏**：节点还没结算，等 `take_card`/`skip_reward` 收尾。
        // ⚠️ 这里**不**自己滚卡：卡池在内容里，运行层不认识它（调用方随后调
        // `roll_rest_card_reward`）。与 `roll_reward` 的分工一致。
        self.pending = if self.holds_relic_effect(RelicEffect::RestCardReward) {
            Pending::Reward
        } else {
            Pending::None
        };
        if self.pending == Pending::None {
            self.mark_resolved();
        }
        Ok(self.health - before)
    }

    /// Smith at a rest site: replace a deck card with its upgraded row.
    ///
    /// `upgraded_id` comes from the caller: in this content an upgrade is **another CARD row**
    /// (`sts-act1-plan.md` §6.5-2), and which row is the caller's mapping (`strike` → `strike+`).
    /// This crate owns no content, so it does not guess a `+` suffix.
    pub fn smith(&mut self, card: usize, upgraded_id: &str) -> Result<(), RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        if card >= self.deck_len as usize {
            return Err(RunError::BadCard(card as u8));
        }
        let id = RunId::new(upgraded_id).map_err(|_| RunError::BadId)?;
        // Already upgraded? Then the "upgrade" is a no-op the caller should not have asked for.
        if self.deck[card] == id {
            return Err(RunError::BadCard(card as u8));
        }
        self.deck[card] = id;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// Open the chest under the cursor.
    ///
    /// Chest type and gold follow `inv:§8.3` exactly (50/33/17 by type; a per-type chance of gold;
    /// the ranges 23–27 / 45–55 / 68–82). The relic is drawn from the caller's pool.
    /// §274：`card_pool` 是给 `push_relic` 的（拾取类遗物要看牌的类型与 `+` 行）。
    pub fn open_chest(
        &mut self,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<ChestOutcome, RunError> {
        if self.pending != Pending::Chest {
            return Err(RunError::WrongPhase);
        }
        let roll = self.rng.roll(RunStream::Chest, 100)?;
        let (chest, gold_chance, low, high) = match roll {
            0..=49 => (0u8, 50u32, 23, 27),   // 50%
            50..=82 => (1, 35, 45, 55),       // 33%
            _ => (2, 50, 68, 82),             // 17%
        };
        let mut gold = 0;
        if self.rng.roll(RunStream::Chest, 100)? < gold_chance {
            let span = (high - low + 1) as u32;
            gold = low + self.rng.roll(RunStream::Chest, span)? as i32;
        }
        self.adjust_gold(gold);
        // A chest always holds a relic in `inv:§8.3`; an empty pool is a content problem, not "an
        // empty chest".
        //
        // §145: **already-held relics are filtered out** — a chest that hands you a second
        // Burning Blood is a bug the player sees immediately, and before the pool had more than one
        // entry it was the *only* thing this could do.
        let relic = {
            // §156: the same weighted draw as an elite reward, and the same "not one you hold".
            let picked = self.pick_relic(RunStream::Chest, relic_pool)?;
            if picked.as_str().is_empty() {
                None
            } else {
                self.push_relic(picked.as_str(), card_pool)?;
                Some(picked)
            }
        };
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(ChestOutcome { chest, gold, relic })
    }

    /// Fill the merchant's shelves. Prices are `[推断]`: the content carries no rarity, so every
    /// card is priced in the Common band and every relic likewise (`inv:§8.2`'s ranges are by
    /// rarity, and this content does not have one to look at).
    /// Is this pool short enough for the fixed readers? (§161)
    ///
    /// Every reader below builds a `[_; MAX_POOL]` and used to iterate `len().min(MAX_POOL)`, which
    /// **silently dropped** everything past the cap: the pool said it had N entries, the draw only
    /// ever saw 64, and no gate, test or error could tell. This is the same shape as the
    /// `MAX_POOL_IDS = 8` potion truncation §158 removed, one layer down (that one was in `rd-core`,
    /// this one is the run layer's own buffers).
    ///
    /// The number stays a capacity -- replacing it with `Vec` would be the right answer for a
    /// server and the wrong one for a `no_std` kernel that already pays for fixed tables. What
    /// changes is that going over it is now **loud**.
    fn pool_fits(len: usize) -> Result<(), RunError> {
        if len > MAX_POOL {
            return Err(RunError::PoolTooLarge {
                pool: len,
                max: MAX_POOL,
            });
        }
        Ok(())
    }

    /// §273：**进一次商店** —— 摆货架 + `meal_ticket` 的 15 血。
    ///
    /// 为什么必须是一个函数：`?` 房掷出商人时走的是 `begin_node` 的 Unknown 分支，而商店节点走
    /// 的是 `NodeKind::Shop` 分支。§272 之前只有后者调用这里的效果，于是
    /// "`?` 房变成商店"**不回血** —— 而 wiki 明确说这两件事都要触发
    /// （Planisphere 页：*"a ? that turns into a shop triggers both"*）。
    /// 一处实现、两个调用方，才能让"进商店"只有一个意思。
    fn enter_shop(
        &mut self,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<(), RunError> {
        self.stock_shop(card_pool, relic_pool)?;
        // `meal_ticket` —— "Whenever you enter a shop, heal 15 HP"。与 `Eternal Feather`
        // 同一条规矩：**进门就付**，不是"买了东西才付"。
        if let Some(RelicEffect::ShopEntryHeal(amount)) =
            self.first_relic_effect_of(RelicEffect::ShopEntryHeal(15))
        {
            self.heal_after_combat(amount);
        }
        Ok(())
    }

    /// §273：`the_courier` 的**第二半** —— 买走一格就补一格（同价位的重新掷一次）。
    ///
    /// 只补被买走的那一格，不重摆整个货架：wiki 说的是 "The Merchant **restocks** cards,
    /// relics, and potions"，也就是"货架不会因为你买了就变少"。
    ///
    /// 池子里没货了（牌池就这么大 / 遗物已经全在手上）⇒ 那一格留空（`price = -1`），
    /// **不是**错误：那正是"商人的货卖完了"。
    fn restock_card_slot(&mut self, slot: usize, card_pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        // 货架上还活着的卡（含其它格子）都不能再被补进来：货架不该出现两张一样的牌。
        let mut used = [false; MAX_POOL];
        let mut eligible = [0usize; MAX_POOL];
        let mut eligible_len = 0usize;
        Self::pool_fits(card_pool.len())?;
        for index in 0..card_pool.len() {
            if matches!(
                card_pool[index].rarity,
                Rarity::Status | Rarity::Curse | Rarity::Special
            ) {
                continue;
            }
            let mut on_shelf = false;
            for other in 0..self.shop.cards_len as usize {
                if other != slot && self.shop.cards[other].price >= 0
                    && self.shop.cards[other].id == RunId::new(card_pool[index].id)
                        .unwrap_or(RunId::EMPTY)
                {
                    on_shelf = true;
                    break;
                }
            }
            if !on_shelf {
                eligible[eligible_len] = index;
                eligible_len += 1;
            }
        }
        if eligible_len == 0 {
            self.shop.cards[slot] = Offer {
                id: RunId::EMPTY,
                price: -1,
            };
            return Ok(());
        }
        let pick = self.rng.roll(RunStream::Shop, eligible_len as u32)? as usize;
        let card = card_pool[eligible[pick]];
        let (low, high) = card_price_band(card.rarity);
        let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
        self.shop.cards[slot] = Offer {
            id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
            // 与陈列时同一条规矩：涨价在**挂牌**那一刻算，折扣在付款时算（`shop_price`）。
            price: self.marked_up(price),
        };
        used[0] = false;
        Ok(())
    }

    /// §273：`the_courier` 的遗物那一半（同上）。
    fn restock_relic_slot(
        &mut self,
        slot: usize,
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<(), RunError> {
        let mut shelved: [RunId; MAX_SHOP_RELICS] = [RunId::EMPTY; MAX_SHOP_RELICS];
        let mut len = 0usize;
        for other in 0..self.shop.relics_len as usize {
            if other != slot && self.shop.relics[other].price >= 0 {
                shelved[len] = self.shop.relics[other].id;
                len += 1;
            }
        }
        let picked = self.pick_relic_avoiding(RunStream::Shop, relic_pool, &shelved[..len])?;
        if picked.as_str().is_empty() {
            self.shop.relics[slot] = Offer {
                id: RunId::EMPTY,
                price: -1,
            };
            return Ok(());
        }
        let price = 143 + self.rng.roll(RunStream::Shop, 15)? as i32;
        self.shop.relics[slot] = Offer {
            id: picked,
            price: self.marked_up(price),
        };
        Ok(())
    }

    fn stock_shop(&mut self, card_pool: &[PoolCard<'_>], relic_pool: &[PoolRelic<'_>]) -> Result<(), RunError> {
        if card_pool.is_empty() {
            return Err(RunError::EmptyPool("cards"));
        }
        Self::pool_fits(card_pool.len())?;
        self.shop = ShopStock::empty();
        let mut order = [0u8; MAX_POOL];
        let n = card_pool.len();
        for (index, slot) in order.iter_mut().take(n).enumerate() {
            *slot = index as u8;
        }
        self.rng.shuffle(RunStream::Shop, &mut order[..n]);
        let cards = MAX_SHOP_CARDS.min(n);
        for slot in 0..cards {
            let card = card_pool[order[slot] as usize];
            // `inv:§8.2`: the band follows the card's rarity.
            let (low, high) = card_price_band(card.rarity);
            let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
            self.shop.cards[slot] = Offer {
                id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
                // §159 `A16`: "everything costs 10% more". Applied **at stock time**, so the price
                // the page shows and the price the purchase charges are the same number -- a markup
                // applied at purchase time would need a second rule and the two would drift.
                price: self.marked_up(price),
            };
        }
        self.shop.cards_len = cards as u8;

        // §145/§156: the merchant refuses to sell what you already wear, and draws by rarity weight
        // (both via `pick_relic`, the one function the chest and the elite reward share).
        let mut shelved: [RunId; MAX_SHOP_RELICS] = [RunId::EMPTY; MAX_SHOP_RELICS];
        for slot in 0..MAX_SHOP_RELICS {
            let picked = self.pick_relic_avoiding(
                RunStream::Shop,
                relic_pool,
                &shelved[..slot],
            )?;
            if picked.as_str().is_empty() {
                break;
            }
            // Common 143–157.
            let price = 143 + self.rng.roll(RunStream::Shop, 15)? as i32;
            self.shop.relics[slot] = Offer {
                id: picked,
                price: self.marked_up(price),
            };
            shelved[slot] = picked;
            self.shop.relics_len = (slot + 1) as u8;
        }
        Ok(())
    }

    /// 从 `pool` 里**不重复**地抽 `count` 张，把 id 写进 `out`，返回实际抽出几张。
    ///
    /// §161.5：Attack / Skill Potion 要"从卡池随机三张**不同的**牌里选一张"。抽牌的人必须是
    /// **运行层**，因为它持有 RNG（`RunState.rng` 是私有的，正是为了让"谁推进了哪个流"只有一处）；
    /// 按标签过滤是**内容**的事，所以调用方传进来的 `pool` 已经滤过。
    ///
    /// 用 `RunStream::Reward`：参考把"从卡池取牌给你挑"记在**奖励**那个流上（卡奖励与这次抽三张
    /// 是同一件事的两半），而 `Potion` 那个流已经用来决定"掉不掉药水"了 —— 混用会让掉率与
    /// "抽到哪三张"互相干扰，那是确定性最贵的一种错。
    ///
    /// 池子比 `count` 短时**返回实际张数**（不是错误）：StS 里牌池不够就少给几张，
    /// 而"少于 3 张"要不要拒绝是**调用方**的决定（它知道该不该喝这瓶药）。
    pub fn draw_distinct(
        &mut self,
        pool: &[PoolCard<'_>],
        count: usize,
        out: &mut [RunId],
    ) -> Result<usize, RunError> {
        Self::pool_fits(pool.len())?;
        let wanted = count.min(out.len()).min(pool.len());
        if wanted == 0 {
            return Ok(0);
        }
        let mut order = [0u8; MAX_POOL];
        for (index, slot) in order.iter_mut().take(pool.len()).enumerate() {
            // `MAX_POOL` 是 64，所以 `as u8` 丢不掉信息（`pool_fits` 已经拦住更长的池子）。
            *slot = index as u8;
        }
        self.rng.shuffle(RunStream::Reward, &mut order[..pool.len()]);
        for (at, slot) in order.iter().take(wanted).enumerate() {
            out[at] = RunId::new(pool[*slot as usize].id).map_err(|_| RunError::BadId)?;
        }
        Ok(wanted)
    }

    /// Draw a potion from `pool` by **rarity weight** (65/25/10, §156).
    ///
    /// `RunId::EMPTY` when the pool is empty: that is what a run whose content declares no potions
    /// has to see, and it is why the caller treats "no id" and "no potion" as the same thing.
    ///
    /// §158 made this a function instead of a block inside [`Self::roll_reward`] so **Entropic
    /// Brew** asks the same question ("which potion is this bottle?") and gets the same answer --
    /// a second picker would be a second set of weights to forget.
    pub fn pick_potion(
        &mut self,
        stream: RunStream,
        pool: &[PoolPotion<'_>],
    ) -> Result<RunId, RunError> {
        if pool.is_empty() {
            return Ok(RunId::EMPTY);
        }
        Self::pool_fits(pool.len())?;
        let mut rarities = [Rarity::Common; MAX_POOL];
        for (slot, entry) in pool.iter().enumerate() {
            rarities[slot] = entry.rarity;
        }
        let present = &rarities[..pool.len()];
        let band = self.pick_rarity(stream, &POTION_RARITY_WEIGHTS, present)?;
        let band = band.unwrap_or(pool[0].rarity);
        let mut eligible = [0usize; MAX_POOL];
        let mut count = 0usize;
        for (slot, entry) in pool.iter().enumerate() {
            if entry.rarity == band {
                eligible[count] = slot;
                count += 1;
            }
        }
        let chosen = if count == 0 {
            0
        } else {
            let pick = self.rng.roll(stream, count as u32)? as usize;
            eligible[pick]
        };
        RunId::new(pool[chosen].id).map_err(|_| RunError::BadId)
    }

    /// Draw a rarity band by weight, re-normalised over the bands that still have entries
    /// (§156). `None` = no band has an entry.
    fn pick_rarity(
        &mut self,
        stream: RunStream,
        weights: &[(Rarity, u32)],
        present: &[Rarity],
    ) -> Result<Option<Rarity>, RunError> {
        let mut total = 0u32;
        for (rarity, weight) in weights {
            if present.contains(rarity) {
                total += *weight;
            }
        }
        if total == 0 {
            return Ok(None);
        }
        let mut roll = self.rng.roll(stream, total)?;
        for (rarity, weight) in weights {
            if !present.contains(rarity) {
                continue;
            }
            if roll < *weight {
                return Ok(Some(*rarity));
            }
            roll -= *weight;
        }
        Ok(None)
    }

    /// Is this rarity in a **drop** band? (§160)
    ///
    /// The weight table is the single answer: a rarity that is not in it (the wiki's `Event`,
    /// `Shop`, `Boss` buckets) can be held and can pay out, but no reward, chest or shelf will roll
    /// it. That is what makes "event-only" sayable without lying about the rarity.
    #[must_use]
    pub fn relic_rarity_is_droppable(rarity: Rarity) -> bool {
        RELIC_RARITY_WEIGHTS
            .iter()
            .any(|(band, _)| *band == rarity)
    }

    /// Draw a relic from `pool` by **rarity weight** (§156), skipping relics already held.
    ///
    /// One helper for the chest, the shop and the elite reward: before this each of them picked
    /// uniformly, so "an elite pays a rare more often than a chest" was not true even in principle.
    pub fn pick_relic(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
    ) -> Result<RunId, RunError> {
        self.pick_relic_avoiding(stream, pool, &[])
    }

    /// [`Self::pick_relic`], also skipping `reserved` -- the relics a caller has already put on a
    /// shelf but not yet sold (the shop stocks three, and a picked relic is not in the belt yet).
    pub fn pick_relic_avoiding(
        &mut self,
        stream: RunStream,
        pool: &[PoolRelic<'_>],
        reserved: &[RunId],
    ) -> Result<RunId, RunError> {
        // Never a second copy of a held relic (§145) -- the filter every source shares.
        // §160: **not-droppable rarities are not candidates at all.** `Event` (and `Shop`/`Boss`,
        // if this content ever has them) are not in `RELIC_RARITY_WEIGHTS`, so `pick_rarity` can
        // never return them -- but a pool made *only* of them would fall through to
        // `unwrap_or(pool[first].rarity)` and hand one out anyway. Filtering here means "the pool
        // has no droppable relic" arrives as `RunId::EMPTY`, which every caller already handles.
        let mut candidates = [0usize; MAX_POOL];
        let mut rarities = [Rarity::Common; MAX_POOL];
        let mut count = 0usize;
        Self::pool_fits(pool.len())?;
        for (slot, entry) in pool.iter().enumerate() {
            if !Self::relic_rarity_is_droppable(entry.rarity) {
                continue;
            }
            if self.relics().iter().any(|held| held.as_str() == entry.id)
                || reserved.iter().any(|taken| taken.as_str() == entry.id)
            {
                continue;
            }
            candidates[count] = slot;
            rarities[count] = entry.rarity;
            count += 1;
        }
        if count == 0 {
            return Ok(RunId::EMPTY);
        }
        let present = &rarities[..count];
        let band = self
            .pick_rarity(stream, &RELIC_RARITY_WEIGHTS, present)?
            .unwrap_or(pool[candidates[0]].rarity);
        let mut band_slots = [0usize; MAX_POOL];
        let mut band_count = 0usize;
        for slot in &candidates[..count] {
            if pool[*slot].rarity == band {
                band_slots[band_count] = *slot;
                band_count += 1;
            }
        }
        let chosen = if band_count == 0 {
            candidates[0]
        } else {
            let pick = self.rng.roll(stream, band_count as u32)? as usize;
            band_slots[pick]
        };
        RunId::new(pool[chosen].id).map_err(|_| RunError::BadId)
    }

    /// Buy the card in `slot`. The id stays readable through [`RunState::shop`].
    /// §273：`card_pool` 是**补货**用的（`the_courier`）—— 买走一格就补一格，而补什么只有池子
    /// 知道。没有这件遗物时它不被读到，但签名统一（一处规则、一个入口）。
    pub fn buy_card(
        &mut self,
        slot: usize,
        card: PoolCard<'_>,
        card_pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::Shop {
            return Err(RunError::WrongPhase);
        }
        let offer = *self
            .shop
            .cards()
            .get(slot)
            .ok_or(RunError::EmptyOffer(slot as u8))?;
        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        if self.gold < offer.price {
            return Err(RunError::NotEnoughGold {
                price: offer.price,
                gold: self.gold,
            });
        }
        // §160: **提交点只有一个，而且失败的那一半在前面。**
        // 原来的顺序是"先扣钱、再 `push_card?`"：牌组满（`MAX_RUN_DECK`）时 `push_card` 返回
        // `Capacity`，而金币已经扣掉、货架也还在 —— 一次**被拒绝的**操作改变了可观察状态。
        // `push_card` 自己先校验再写，失败时什么都不动，所以调换顺序就是完整修复（`adjust_gold`
        // 不会失败）。REVIEW 的 P0，判据是 `a_refused_purchase_leaves_the_run_untouched`。
        // §270：同上，调用方带来的牌必须**就是**货架上那一张。
        if card.id != offer.id.as_str() {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        self.push_card(card)?;
        self.adjust_gold(-self.shop_price(offer.price));
        self.maw_bank_broken = true;
        self.shop.cards[slot].price = -1;
        // §273：`the_courier` —— "The Merchant restocks cards, relics, and potions"：买走的那一格
        // **立刻补上**（而不是留空）。走 `RELIC_SECOND_HALVES` 的同一张表，所以"这件遗物有哪两半"
        // 仍然只有一处。
        if self.holds_relic("the_courier") {
            self.restock_card_slot(slot, card_pool)?;
        }
        Ok(())
    }

    /// Buy the relic in `slot`.
    /// §273：`relic_pool` 同上（`the_courier` 的补货）。
    pub fn buy_relic(
        &mut self,
        slot: usize,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::Shop {
            return Err(RunError::WrongPhase);
        }
        let offer = *self
            .shop
            .relics()
            .get(slot)
            .ok_or(RunError::EmptyOffer(slot as u8))?;
        if offer.price < 0 {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        if self.gold < offer.price {
            return Err(RunError::NotEnoughGold {
                price: offer.price,
                gold: self.gold,
            });
        }
        // §160: the same commit-point rule as `buy_card` -- the failing half must come first.
        self.push_relic(offer.id.as_str(), card_pool)?;
        self.adjust_gold(-self.shop_price(offer.price));
        // §270：`maw_bank` "No longer works when you spend any Gold at a shop"。
        self.maw_bank_broken = true;
        self.shop.relics[slot].price = -1;
        // §273：`the_courier` 补货（同上）。
        if self.holds_relic("the_courier") {
            self.restock_relic_slot(slot, relic_pool)?;
        }
        Ok(())
    }

    /// Pay to remove a card from the deck. Returns the price paid.
    pub fn remove_card(&mut self, card: usize) -> Result<i32, RunError> {
        if self.pending != Pending::Shop {
            return Err(RunError::WrongPhase);
        }
        let price = self.remove_card_price();
        if self.gold < price {
            return Err(RunError::NotEnoughGold {
                price,
                gold: self.gold,
            });
        }
        // §259：**先搬再扣钱之前先验**（`remove_deck_card` 里的两条拒绝：越界、Ascender's Bane）
        // 仍在扣钱之前 —— 顺序与原来一致，所以"拒绝 ⇒ 一个字节都不改"照旧成立。
        self.remove_deck_card(card)?;
        self.adjust_gold(-price);
        // §270：删牌也是"在商店花钱"。
        self.maw_bank_broken = true;
        // §259：`removed_cards` 是**商店服务的计价步数**（+25/次），不是"删过几张牌" ——
        // 所以它留在这里，而不是搬进共用的 `remove_deck_card`（`Toke` 不该让商店涨价）。
        self.removed_cards += 1;
        Ok(price)
    }

    /// §259：从牌组里删掉第 `card` 张（**不收钱、不改 `removed_cards`**）。
    ///
    /// 商店（`remove_card`）与篝火的 `Toke` 共用这一段。抽出来是因为**复制的那一份一定会漏
    /// `marks`**：§253 已经在同一个循环里踩过一次（"删掉一张牌，另一张继承了它的伤害"，
    /// 页面上完全看不出来）。
    fn remove_deck_card(&mut self, card: usize) -> Result<(), RunError> {
        if card >= self.deck_len as usize {
            return Err(RunError::BadCard(card as u8));
        }
        // §189 `A10`：Ascender's Bane 的卡面写着 "Cannot be removed"，StS 也把这一条写在这张卡
        // 自己的代码里。
        if self.deck[card].as_str() == ASCENDERS_BANE {
            return Err(RunError::CannotRemove);
        }
        // Shift the tail down; deck order is observable, so the order of the survivors is kept.
        for index in card..(self.deck_len as usize - 1) {
            self.deck[index] = self.deck[index + 1];
            // §253：**mark 跟着牌走**。
            self.marks[index] = self.marks[index + 1];
        }
        // **`len` 之后必须是 EMPTY**（REVIEW P1，§161.10）。
        self.deck[self.deck_len as usize - 1] = RunId::EMPTY;
        self.deck_len -= 1;
        Ok(())
    }

    /// Roll the pre-run pair and enter [`Pending::Start`].
    ///
    /// Called by the driver right after the run is created: **no move is legal until the blessing is
    /// chosen**, which is the same rule as `NodeNotSettled` one level up.
    pub fn offer_start_choice(&mut self) -> Result<(), RunError> {
        // **Only blessings that are choices.** Two rules, both from reading the panel:
        //   1. no `heal` while the hero is at full health (it would change nothing);
        //   2. at least one of the two offers must be free -- otherwise the opening move of the game
        //      is "lose HP", which is not a choice either.
        let mut pool = [0u8; START_OFFERS.len()];
        let mut pool_len = 0usize;
        for (index, offer) in START_OFFERS.iter().enumerate() {
            if self.blessing_is_meaningful(offer) {
                pool[pool_len] = index as u8;
                pool_len += 1;
            }
        }
        if pool_len < 2 {
            // The rule, not the content, would be wrong here; fail loudly rather than offer one.
            return Err(RunError::Invariant("fewer than two meaningful blessings"));
        }

        let first_slot = self.rng.roll(RunStream::Event, pool_len as u32)? as usize;
        let mut second_slot = self.rng.roll(RunStream::Event, pool_len as u32 - 1)? as usize;
        if second_slot >= first_slot {
            second_slot += 1;
        }
        let mut pair = [pool[first_slot], pool[second_slot]];

        // Rule 2: force one free offer in when the roll produced none.
        let is_free = |slot: u8| matches!(START_OFFERS[slot as usize].cost, EventEffect::Nothing);
        if !is_free(pair[0]) && !is_free(pair[1]) {
            for candidate in 0..pool_len {
                if is_free(pool[candidate]) {
                    pair[1] = pool[candidate];
                    break;
                }
            }
            if !is_free(pair[1]) {
                return Err(RunError::Invariant("no free blessing exists"));
            }
        }

        self.start_offers = pair;
        self.pending = Pending::Start;
        Ok(())
    }

    /// Would this blessing change anything **right now**? Today: healing a hero who is already at
    /// full health changes nothing. The list is deliberately short -- it grows only when a blessing
    /// is shown to be a non-choice.
    #[must_use]
    fn blessing_is_meaningful(&self, offer: &StartOffer) -> bool {
        let gain_does_something = match offer.gain {
            // Healing a hero already at full health changes nothing.
            EventEffect::Heal(_) => self.health < self.health_max,
            _ => true,
        };
        // A deck blessing on an empty deck has nothing to act on.
        let deck_does_something = match offer.follow_up {
            BlessingFollowUp::Deck(_) => self.deck_len > 0,
            BlessingFollowUp::None | BlessingFollowUp::GainThreeCards => true,
        };
        gain_does_something && deck_does_something
    }

    /// The two rolled blessings, or `None` when no choice is pending.
    #[must_use]
    pub fn start_offers(&self) -> Option<[StartOffer; 2]> {
        if self.pending != Pending::Start {
            return None;
        }
        Some([
            START_OFFERS[self.start_offers[0] as usize],
            START_OFFERS[self.start_offers[1] as usize],
        ])
    }

    /// Take blessing `slot` (`0` or `1`): its gain, then its cost.
    pub fn choose_start(
        &mut self,
        slot: usize,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::Start {
            return Err(RunError::WrongPhase);
        }
        let Some(offers) = self.start_offers() else {
            return Err(RunError::WrongPhase);
        };
        let Some(offer) = offers.get(slot) else {
            return Err(RunError::NoSuchOffer);
        };
        // `three_cards` is finished right here: it needs the pool, not a pick.
        if matches!(offer.follow_up, BlessingFollowUp::GainThreeCards) {
            self.grant_random_cards(3, pool)?;
            self.blessing_follow = None;
            self.pending = Pending::None;
            return Ok(());
        }
        self.apply_event_effect(offer.gain, None, pool)?;
        self.apply_event_effect(offer.cost, None, pool)?;
        // A blessing that names a card is not finished until the card is named.
        self.blessing_follow = match offer.follow_up {
            BlessingFollowUp::None => None,
            other => Some(other),
        };
        self.pending = if self.blessing_follow.is_some() {
            Pending::BlessingCard
        } else {
            Pending::None
        };
        Ok(())
    }

    /// What the pending blessing still needs, for a picker.
    #[must_use]
    pub const fn blessing_follow_up(&self) -> Option<BlessingFollowUp> {
        self.blessing_follow
    }

    /// What the pending **event** still needs, for a picker (§143).
    #[must_use]
    pub const fn event_follow_up(&self) -> Option<DeckChange> {
        self.event_follow
    }

    /// Splice deck entry `index` out. **Not** `remove_card`: that action belongs to the shop and
    /// refuses outside it; this is the same list move it performs.
    fn remove_at(&mut self, index: usize) {
        let last = self.deck_len as usize - 1;
        for slot in index..last {
            self.deck[slot] = self.deck[slot + 1];
        }
        self.deck[last] = RunId::EMPTY;
        self.deck_len -= 1;
    }

    /// Add `count` random non-Status/Curse cards from the pool, on the run's own stream.
    fn grant_random_cards(&mut self, count: usize, pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        let mut eligible = [0usize; MAX_POOL];
        let mut eligible_len = 0usize;
        Self::pool_fits(pool.len())?;
        for index in 0..pool.len() {
            if !matches!(
                pool[index].rarity,
                Rarity::Status | Rarity::Curse | Rarity::Special
            ) {
                eligible[eligible_len] = index;
                eligible_len += 1;
            }
        }
        if eligible_len == 0 {
            return Err(RunError::PoolTooSmall { pool: 0, need: 1 });
        }
        for _ in 0..count {
            let picked = self.rng.roll(RunStream::Event, eligible_len as u32)? as usize;
            let card = pool[eligible[picked]];
            self.push_card(card)?;
        }
        Ok(())
    }

    /// Finish a blessing that named a card: remove or upgrade deck entry `index`.
    pub fn pick_blessing_card(
        &mut self,
        index: usize,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::BlessingCard {
            return Err(RunError::WrongPhase);
        }
        let Some(follow_up) = self.blessing_follow else {
            return Err(RunError::WrongPhase);
        };
        let BlessingFollowUp::Deck(change) = follow_up else {
            return Err(RunError::WrongPhase);
        };
        self.apply_deck_change(change, index, pool)?;
        self.blessing_follow = None;
        self.pending = Pending::None;
        Ok(())
    }

    /// Finish an **event** that named a card (§143).
    ///
    /// Shares [`Self::apply_deck_change`] with the blessing path on purpose: "upgrade a card" is
    /// one behaviour, and a second copy of it is how `strike+` would come to mean one thing in a
    /// blessing and another in an event.
    /// §274：还欠几次"拾取时的牌组编辑"（0 = 不欠）。
    #[must_use]
    pub const fn pickup_picks(&self) -> u8 {
        self.pickup_picks
    }

    /// §274：欠的是哪一种编辑（`Remove` = 移除、`Transform` = 改造、`TransformAndUpgrade` = 改造并升级）。
    #[must_use]
    pub const fn pickup_change(&self) -> Option<DeckChange> {
        self.pickup_change
    }

    /// §274：**兑现一次**拾取时的牌组编辑。
    ///
    /// 与 `pick_event_card` 的区别：不走 `pending`、**不 `mark_resolved`** —— 节点是那个流程的事
    /// （宝箱要 `leave`、奖励屏要 `skip_reward`），这里只还欠着的那一步。
    pub fn pickup_card(&mut self, index: usize, pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        let Some(change) = self.pickup_change else {
            return Err(RunError::WrongPhase);
        };
        // ⚠️ 先验后改：`apply_deck_change` 里的拒绝（越界 / Ascender's Bane / 没有 `+` 行）
        // 必须发生在 `pickup_picks` 递减**之前**，否则一次被拒的点击会白白吃掉一次额度。
        self.apply_deck_change(change, index, pool)?;
        self.pickup_picks = self.pickup_picks.saturating_sub(1);
        if self.pickup_picks == 0 {
            self.pickup_change = None;
        }
        Ok(())
    }

    pub fn pick_event_card(
        &mut self,
        index: usize,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::EventCard {
            return Err(RunError::WrongPhase);
        }
        let Some(change) = self.event_follow else {
            return Err(RunError::WrongPhase);
        };
        self.apply_deck_change(change, index, pool)?;
        self.event_follow = None;
        // §278：这一段还可能把玩家带去下一段 —— 那么选牌只是它的**一件**事，房间不结算。
        if !self.event_next.as_str().is_empty() {
            self.event_step = self.event_next;
            self.event_next = RunId::EMPTY;
            self.pending = Pending::Event;
            return Ok(());
        }
        self.pending = Pending::None;
        self.event_step = RunId::EMPTY;
        // The room is settled **now**: picking a card is the last thing the choice asked for.
        self.mark_resolved();
        Ok(())
    }

    /// The one implementation of "edit the deck at `index`".
    fn apply_deck_change(
        &mut self,
        change: DeckChange,
        index: usize,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if index >= self.deck_len as usize {
            return Err(RunError::BadCard(index as u8));
        }
        match change {
            DeckChange::Remove => self.remove_at(index),
            // §229: the pool is already in hand here -- passing it down is what lets `upgrade_at`
            // **look up** the next row instead of guessing from a `+` suffix.
            DeckChange::Upgrade => self.upgrade_at(index, pool)?,
            DeckChange::Transform => {
                self.remove_at(index);
                self.grant_random_cards(1, pool)?;
            }
            // §274：`astrolabe` —— 改造**然后**升级。升级目标是"刚被塞进来的那一张"，
            // 而它一定在牌组**末尾**（`grant_random_cards` 是 append）—— 所以这里按下标取
            // 那个末尾格，而不是"再找一张同名的"（改造可能给出与别处重名的牌）。
            DeckChange::TransformAndUpgrade => {
                self.remove_at(index);
                self.grant_random_cards(1, pool)?;
                let last = self.deck_len as usize - 1;
                self.upgrade_at(last, pool)?;
            }
        }
        Ok(())
    }

    /// Replace the deck card with its upgraded row (`strike` → `strike+`), **looked up in the pool**.
    ///
    /// Already upgraded is **not** an error: the blessing (or the event) simply has nothing to do.
    /// That is the reference's behaviour too -- StS lets you upgrade a card you already upgraded and
    /// nothing happens.
    ///
    /// §229: "nothing to do" is decided by **the content**, not by a `+` suffix. `upgraded_id` asks the
    /// pool whether `<id>+` exists, so `Searing Blow` (whose id keeps growing `+`) upgrades again and
    /// `strike+` (no `strike++` row) still does nothing -- one rule for every card, and the run layer
    /// still owns no content.
    fn upgrade_at(&mut self, index: usize, pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        let id = self.deck[index].as_str();
        let Some(upgraded) = upgraded_id(pool, id) else {
            return Ok(());
        };
        self.deck[index] = RunId::new(upgraded).map_err(|_| RunError::BadId)?;
        Ok(())
    }

    /// Open event `id` in the `?` room under the cursor.
    /// 打开 `?` 房的事件。`entry` 是内容里这一段事件的**入口节点**（`EV.Entry`）。
    ///
    /// 为什么入口由调用方给：run 层**不读内容**（这条纪律从 §133 就在）。它只记住
    /// "这个事件从哪一段开始"，于是页面要显示哪一段正文是**状态**，不是每次重算的推导。
    pub fn begin_event(&mut self, id: &str, entry: &str) -> Result<(), RunError> {
        if self.node_resolved() {
            return Err(RunError::NodeResolved);
        }
        let id = RunId::new(id).map_err(|_| RunError::NoSuchEvent)?;
        let entry = RunId::new(entry).map_err(|_| RunError::NoSuchEvent)?;
        // §287：战斗奖励的"欠账"属于**一个**事件；开新事件就清掉（否则它会漏进下一场战斗）。
        self.fight_gold_bonus = 0;
        self.fight_no_relic = false;
        self.event = id;
        self.event_step = entry;
        self.event_next = RunId::EMPTY;
        self.pending = Pending::Event;
        Ok(())
    }

    /// The event under the cursor (empty until [`RunState::begin_event`]).
    #[must_use]
    pub fn event(&self) -> &str {
        self.event.as_str()
    }

    /// §286：事件把房间转成的那一场战斗的**档位**（`0` / `1` 普通 / `2` 精英）。
    ///
    /// 调用方（`rd-wasm`）靠它决定"要不要开打、按哪个池子开、战后按哪一档结算" ——
    /// 一件事的三个答案出自**同一个数**。
    #[must_use]
    pub fn event_fight(&self) -> u8 {
        self.event_fight
    }

    /// §287：事件引来的那一场战斗该用哪个**遭遇池**（空 = 按档位用本幕的标准池）。
    ///
    /// 存在的理由只有一个：`Dead Adventurer` 的 Lagavulin **不睡觉**，而"睡觉"写在遭遇里
    /// （`ENCT` 的 `StartingStatuses`）—— 改遭遇会连普通精英战一起改，所以改成"这一次用另一个池"。
    #[must_use]
    pub fn event_fight_pool(&self) -> &str {
        self.event_fight_pool.as_str()
    }

    /// §278：事件**当前所在的那一段**（`EVND.Id`）。空 = 这个事件只有一段（或还没开）。
    #[must_use]
    pub fn event_step(&self) -> &str {
        self.event_step.as_str()
    }

    /// Take one choice of the open event.
    ///
    /// `effect` is what the **content** declared for that choice (see [`EventEffect`]'s table);
    /// `named` is the payload a `curse:<id>` / `relic:<id>` choice carries. `pool` is the content's
    /// card list: the curse id is checked against it, and a `transform_card` later draws from it.
    ///
    /// A choice that needs a **deck index** does not finish here: the run enters
    /// [`Pending::EventCard`] and [`RunState::pick_event_card`] completes it. Before §143 the run
    /// layer had no such state, which is why "remove a card" was not expressible at all.
    pub fn resolve_event(
        &mut self,
        effect: EventEffect,
        named: Option<&str>,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pending != Pending::Event {
            return Err(RunError::WrongPhase);
        }
        // A deck edit is *not applied here*: it becomes a pending pick. What is applied below is
        // only the part that needs no name.
        if let Some(change) = effect.deck_change() {
            if self.deck_len == 0 {
                return Err(RunError::DeckEmpty);
            }
            self.event_follow = Some(change);
            self.pending = Pending::EventCard;
            return Ok(());
        }
        self.apply_event_effect(effect, named, pool)?;
        self.pending = Pending::None;
        self.event_step = RunId::EMPTY;
        self.mark_resolved();
        Ok(())
    }

    /// §188：**一串**效果，按顺序应用；任何一条失败 ⇒ 整个 `RunState` 回到调用前（逐字节）。
    ///
    /// 为什么不"循环调 `resolve_event`"：那样第二次调用会看到 `Pending::None`（第一次已经收尾），
    /// 于是"遗物 + 诅咒"变成"遗物，然后拒绝"；而如果第一次就成功收尾，第二半就丢了。
    ///
    /// 改牌类效果（`remove_card` / `upgrade_card` / `transform_card`）**最多一条**：它们变成一个
    /// 待答问题（`Pending::EventCard`），而队列里只有一个位置 ⇒ 两个就是内容错误。
    ///
    /// `next`（§278）是这一段选完之后要去的那一段：`Some` ⇒ 应用完效果**收在同一段事件的下一步**，
    /// `Pending` 仍是 `Event`、房间**不结算**；`None` ⇒ 照旧收尾。这就是"事件是一棵树"的全部
    /// 运行层实现 —— 没有第二套状态机，只有"这一段做完了"与"还有下一段"。
    pub fn resolve_event_effects(
        &mut self,
        event_move: &EventMove<'_>,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        let &EventMove {
            effects,
            next,
            branches,
            entry,
            fight,
            fight_pool,
        } = event_move;
        if self.pending != Pending::Event {
            return Err(RunError::WrongPhase);
        }
        // `next` 在动手之前就要验：一个坏 id 必须在**一个字节都没改**之前被拒。
        //
        // §286：有分支表时，先去**掷一次**（同样是"写之前"）—— 掷骰本身会推进随机流，
        // 所以它必须在所有 `self` 写入之前，和 `roll_unknown_room` 同一条纪律。
        //
        // 权重是**累积**读的：`rolled < 25` ⇒ 第一档，`< 50` ⇒ 第二档…… 最后一档吸收
        // "权重和没到 100"的零头 —— 内容门要求和恰好 100，但内核不靠内容正确才不越界。
        let target = if branches.is_empty() {
            next
        } else {
            let rolled = self
                .rng
                .roll(RunStream::Event, 100)
                .map_err(|_| RunError::Capacity)?;
            let mut edge = 0u32;
            let mut picked = branches[branches.len() - 1].1;
            for (weight, target) in branches {
                edge += u32::from(*weight);
                if rolled < edge {
                    picked = *target;
                    break;
                }
            }
            Some(picked)
        };
        let next_id = match target {
            Some(next) => RunId::new(next).map_err(|_| RunError::NoSuchEvent)?,
            None => RunId::EMPTY,
        };
        let before = *self;
        let mut follow: Option<DeckChange> = None;
        for (effect, named) in effects {
            if let Some(change) = effect.deck_change() {
                if follow.is_some() {
                    *self = before;
                    return Err(RunError::TwoDeckChanges);
                }
                if before.deck_len == 0 {
                    *self = before;
                    return Err(RunError::DeckEmpty);
                }
                follow = Some(change);
                continue;
            }
            if let Err(error) = self.apply_event_effect(*effect, *named, pool) {
                *self = before;
                return Err(error);
            }
        }
        // §286：**目标段的进入效果**（`(段 id, 效果)`）。同一个事务里应用 —— 失败就整个
        // 回滚，所以"金币到账了但改牌被拒"不会留下半截。
        //
        // 进入效果**不许改牌**（内容门拦）：改牌会变成待答问题，而问题队列只有一个位置，
        // 那个位置已经被这一段的选项用掉了。
        if let Some(effects) = entry
            .iter()
            .find(|(step, _)| *step == next_id.as_str())
            .map(|(_, effects)| *effects)
        {
            for (effect, named) in effects {
                if effect.deck_change().is_some() {
                    *self = before;
                    return Err(RunError::TwoDeckChanges);
                }
                if let Err(error) = self.apply_event_effect(*effect, *named, pool) {
                    *self = before;
                    return Err(error);
                }
            }
        }
        // §286：这一段的选项是**一场战斗** ⇒ 事件收尾、房间**不**结算（战斗结算它）。
        if fight != 0 {
            if follow.is_some() {
                // 改牌待答 + 战斗同时发生是不可能的：问句之后事件就收尾了，而收尾的
                // 责任在战斗。内容门也不许这样写。
                *self = before;
                return Err(RunError::TwoDeckChanges);
            }
            self.event = RunId::EMPTY;
            self.event_step = RunId::EMPTY;
            self.event_next = RunId::EMPTY;
            self.event_fight = fight;
            self.event_fight_pool = if fight_pool.is_empty() {
                RunId::EMPTY
            } else {
                RunId::new(fight_pool).map_err(|_| RunError::NoSuchEvent)?
            };
            self.pending = Pending::None;
            return Ok(());
        }
        match follow {
            Some(change) => {
                self.event_follow = Some(change);
                // 编辑完了还要去下一段：**先记下来**，等 `pick_event_card` 收尾时再走。
                self.event_next = next_id;
                self.pending = Pending::EventCard;
            }
            None if next_id.as_str().is_empty() => {
                self.pending = Pending::None;
                self.event_step = RunId::EMPTY;
                self.mark_resolved();
            }
            None => {
                self.event_step = next_id;
                self.event_next = RunId::EMPTY;
                // 还留在 `Pending::Event`：玩家面前换了一段正文/一组按钮，房间没结算。
                self.pending = Pending::Event;
            }
        }
        Ok(())
    }

    /// One closed-vocabulary effect. Shared by `?` rooms and by the pre-run blessing, so the two
    /// cannot drift.
    fn apply_event_effect(
        &mut self,
        effect: EventEffect,
        named: Option<&str>,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        match effect {
            EventEffect::Heal(n) => self.heal_after_combat(n),
            EventEffect::Gold(n) => self.adjust_gold(n),
            EventEffect::LoseHealth(n) => self.adjust_health(-n),
            // §278：百分比在**应用时**才乘最大 HP（内容里写 `25`，不是写死 "20"）。
            // `floor` 而不是四舍五入：wiki 的 Hide 明说 "the larger of 1 and Max HP × 8%",
            // 也就是下限 1 的**向下取整** —— Smash 用同一个取整，否则两处会给出不同的数。
            EventEffect::LoseHealthPercent(tenths) => {
                let loss = permille_of(self.health_max, tenths);
                self.adjust_health(-loss);
            }
            EventEffect::HealPercent(tenths) => {
                let amount = permille_of(self.health_max, tenths);
                self.heal_after_combat(amount);
            }
            // §280："Heal to full HP" —— 不是"回 999"，而是"回到上限"（上限是会变的）。
            EventEffect::HealFull => {
                let full = self.health_max;
                self.heal_after_combat(full);
            }
            EventEffect::GoldRandom(low, high) => {
                // §285：与战斗随机**同一个取模偏置形态**，但走运行层的流 —— 一局的
                // 金币掷骰不该消耗战斗的 `(seed, step)`。
                let span = i64::from(high) - i64::from(low) + 1;
                let roll = self
                    .rng
                    .roll(RunStream::Event, u32::try_from(span).unwrap_or(1))
                    .map_err(|_| RunError::Capacity)?;
                let delta = low.saturating_add(roll as i32);
                self.adjust_gold(delta);
            }
            EventEffect::GoldCost(cost) => {
                if self.gold < cost {
                    // **响亮**：夹到 0 会让"花 75 只有 50"变成"白拿服务"，而屏幕上一切正常。
                    return Err(RunError::NotEnoughGold {
                        price: cost,
                        gold: self.gold,
                    });
                }
                self.adjust_gold(-cost);
            }
            EventEffect::LoseMaxHealthPercent(tenths) => {
                let loss = permille_of(self.health_max, tenths).max(1);
                // 上限夹在 1：wiki 只说"损失至少 1"，没说上限可以变成 0 —— 而 0 会让下一次
                // 百分比计算除以 0（`percent_of` 用的是 base × pct / 100，base=0 ⇒ 永远 0），
                // 于是"下次 Hide 不掉血"这种荒唐事会安静地发生。
                self.health_max = (self.health_max - loss).max(1);
                if self.health > self.health_max {
                    self.health = self.health_max;
                }
            }
            EventEffect::GainMaxHealth(n) => {
                self.health_max += n;
                self.adjust_health(n);
            }
            EventEffect::Nothing => {}
            EventEffect::GainCurse => {
                // The id must name a card this run can actually hold. Without this check a typo in
                // the content puts a phantom id in the deck, and it stays invisible until that card
                // is drawn in a fight.
                let Some(id) = named else {
                    return Err(RunError::UnsupportedEventEffect);
                };
                if !pool.iter().any(|card| card.id == id) {
                    return Err(RunError::NoSuchCard);
                }
                let curse = Rarity::Curse;
                if !pool.iter().any(|card| card.id == id && card.rarity == curse) {
                    // A `curse:` payload that names a non-curse is a content bug with a very
                    // plausible-looking symptom (the deck just gets a card), so refuse it.
                    return Err(RunError::NoSuchCard);
                }
                // `curse:` 载荷按定义就是诅咒（上面刚验过池子里它是 `Rarity::Curse`）。
                self.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain(id) })?;
            }
            // §287：记在运行层，由 `roll_reward` 消费（一场战斗的账）。
            EventEffect::FightGoldBonus(n) => {
                self.fight_gold_bonus = self.fight_gold_bonus.saturating_add(n as i16);
            }
            EventEffect::FightNoRelic => {
                self.fight_no_relic = true;
            }
            EventEffect::GainRandomRelic => {
                // §285：运行层**没有遗物池**，所以这条必须已经被调用方解析成 `GainRelic` +
                // 具体 id。走到这里说明有人直接把它递了进来 —— 响亮拒绝，绝不静默给一件。
                return Err(RunError::UnsupportedEventEffect);
            }
            EventEffect::LoseRelic => {
                // §279：**必须真的持有**才允许"失去"。一条 `relic_lose:` 指向一件不在手上的
                // 遗物时，静默什么都不做就等于"这个选项白点了"；而它通常是内容里
                // 条件（`Requires`）写错的第一征兆 —— 让它在事件屏上就响亮。
                let Some(id) = named else {
                    return Err(RunError::UnsupportedEventEffect);
                };
                self.remove_relic(id)?;
            }
            EventEffect::GainRelic => {
                let Some(id) = named else {
                    return Err(RunError::UnsupportedEventEffect);
                };
                // **The loud boundary of the relic system**, moved forward: an event that hands out
                // a relic whose effect this kernel does not implement is refused *here*, while the
                // player is still looking at the event, instead of at the end of the next fight
                // (`RunError::UnsupportedRelic`).
                if !Self::relic_is_implemented(id) {
                    return Err(RunError::UnsupportedRelic {
                        index: self.relics_len,
                    });
                }
                self.push_relic(id, pool)?;
            }
            // Deck edits never reach here: `resolve_event` turns them into a pending pick.
            EventEffect::RemoveCard | EventEffect::UpgradeCard | EventEffect::TransformCard => {
                if named.is_some() {
                    return Err(RunError::UnsupportedEventEffect);
                }
                return Err(RunError::WrongPhase);
            }
        }
        Ok(())
    }

    /// What a won fight is offering.
    #[must_use]
    pub const fn reward(&self) -> &Reward {
        &self.reward
    }

    /// Roll the reward for a won fight: gold now (`inv:§5`: 10–20 for a normal fight), then three
    /// **distinct** cards from `card_pool` (`inv:§3.5`).
    ///
    /// Gold is granted here rather than on "take" because `inv:§5` gives it on victory -- there is
    /// no way to decline it, so a `take_gold` action would be a button that is always pressed.
    pub fn roll_reward(
        &mut self,
        card_pool: &[PoolCard<'_>],
        potion_pool: &[PoolPotion<'_>],
        relic_pool: &[PoolRelic<'_>],
        kind: FightKind,
    ) -> Result<(), RunError> {
        // Status and curse cards are never a reward (`inv:§3.5`; `slimed` is a Status).
        let mut eligible = [0usize; MAX_POOL];
        let mut eligible_len = 0usize;
        Self::pool_fits(card_pool.len())?;
        for index in 0..card_pool.len() {
            if !matches!(
                card_pool[index].rarity,
                Rarity::Status | Rarity::Curse | Rarity::Special
            ) {
                eligible[eligible_len] = index;
                eligible_len += 1;
            }
        }
        // §269：奖励的**卡数**是可变的（`question_card` +1、`busted_crown` -2、
        // `prayer_wheel` 普通战 +1）。`MAX_REWARD_CARDS` 是**存储**上限，与"这一屏给几张"
        // 是两个数 —— 把两者混成一个，加一张牌就要动所有下标。
        let wanted = self.reward_card_count(kind);
        if eligible_len < wanted {
            return Err(RunError::PoolTooSmall {
                pool: eligible_len,
                need: wanted,
            });
        }
        let eligible = &eligible[..eligible_len];
        let (low, high) = kind.gold();
        let span = (high - low + 1).max(1) as u32;
        let base_gold = low + self.rng.roll(RunStream::Reward, span)? as i32;
        // §157: Golden Idol pays 25% more. Applied to the rolled amount (integer, truncated), so the
        // reward's own `gold` is what the player was actually given.
        // §159: Ascension 13 makes a **boss** pay 25% less. Both multipliers are applied to the roll
        // and the order is fixed (idol first, then the ascension tax) so the number is reproducible.
        let mut paid = if matches!(kind, FightKind::Boss) && self.at_least(A_BOSS_GOLD) {
            base_gold * self.fight_gold_percent() / 100 * ASCENDED_BOSS_GOLD_PERCENT / 100
        } else {
            base_gold * self.fight_gold_percent() / 100
        };
        self.adjust_gold(paid);

        // §157: the wiki's **moving** chance -- 40% to start, -10 after a drop, +10 after a miss.
        // The roll happens even when the belt is full (the wiki's Colosseum note relies on that),
        // so the chance keeps moving; only the **offer** is suppressed below.
        let chance = self.potion_chance.clamp(0, 100) as u32;
        // §269：`white_beast_statue` —— "Potions always appear in combat rewards"。
        // 掷骰照旧（随机流的位置不动，回放才稳定），只把**结果** OR 成真。
        let always = self.holds_relic_effect(RelicEffect::PotionAlwaysDrops);
        let rolled = always || self.rng.roll(RunStream::Potion, 100)? < chance;
        self.potion_chance = if rolled {
            (self.potion_chance - POTION_DROP_STEP).max(0)
        } else {
            (self.potion_chance + POTION_DROP_STEP).min(100)
        };
        // §271：`sozu` —— 奖励屏上根本不该出现药水那一格。掷骰照旧（随机流的位置不动），
        // 只把"要不要给"按成 false。⚠️ 与 `push_potion` 的拒绝是**两件事**：这里是不发，
        // 那里是"别的路（事件/商店/调试）递过来的也收不了"。
        let drop = rolled && self.potion_room() && !self.holds_relic_effect(RelicEffect::NoPotionGain);

        let mut used = [false; MAX_POOL];
        let mut cards = [RunId::EMPTY; MAX_REWARD_CARDS];
        for slot in 0..wanted {
            // One roll, banded -- see `reward_bands`.
            let (rare_top, uncommon_top) = reward_bands(kind, self.rarity_offset);
            let roll = self.rng.roll(RunStream::Reward, 100)? as i32;
            let band = if roll < rare_top {
                Rarity::Rare
            } else if roll < uncommon_top {
                Rarity::Uncommon
            } else {
                Rarity::Common
            };
            // A band with no cards falls through: first to `Basic` (this image's only populated
            // bucket), then to anything left. It is a *documented* deviation -- StS would never
            // offer a Basic card -- and it disappears the moment the content has Common+ cards.
            let mut picked = self.pick_of(card_pool, eligible, &used, Some(band))?;
            if picked.is_none() {
                picked = self.pick_of(card_pool, eligible, &used, Some(Rarity::Basic))?;
            }
            if picked.is_none() {
                picked = self.pick_of(card_pool, eligible, &used, None)?;
            }
            let Some(index) = picked else {
                return Err(RunError::PoolTooSmall {
                    pool: eligible_len,
                    need: MAX_REWARD_CARDS,
                });
            };
            used[index] = true;
            // §189 `A12`：先拿基础牌，再按概率换成它的 `+` 行。概率由**幕 + 难度**决定
            // （`upgrade_chance_percent`）；没有 `+` 行的牌保持原样、**不报错**（那是内容的事，
            // 内容门另有一条"每张可升级牌都必须有 `+` 行"的判据）。
            let mut chosen = card_pool[index].id;
            let chance = upgrade_chance_percent(self.act, self.ascension());
            if chance > 0 && self.rng.roll(RunStream::Reward, 100)? < chance as u32 {
                if let Some(upgraded) = upgraded_id(card_pool, chosen) {
                    chosen = upgraded;
                }
            }
            cards[slot] = RunId::new(chosen).map_err(|_| RunError::BadId)?;
            // `inv:§3.5`: the pity offset moves after **every** roll -- reset on a rare, +1%
            // otherwise (the wiki says "otherwise", not "on a common": an uncommon also ticks it).
            if band == Rarity::Rare {
                self.rarity_offset = RARITY_OFFSET_START;
            } else {
                self.rarity_offset = (self.rarity_offset + 1).min(RARITY_OFFSET_CAP);
            }
        }
        // Which potion: the content's own list, **weighted by rarity** (§156) through the one
        // picker (§158). An empty pool offers nothing at all (roguedeck).
        let potion = if drop && !potion_pool.is_empty() {
            self.pick_potion(RunStream::Potion, potion_pool)?
        } else {
            RunId::EMPTY
        };
        // §155: an elite (and a boss) also pays a relic. The pool is the un-held relic list --
        // `relic_candidates` already de-dupes what the player owns, so a full set means "no relic"
        // rather than "the same relic again". Drawn on the `Reward` stream, after the cards: the
        // card rolls keep their sequence and only the relic's index moves.
        let mut relic = RunId::EMPTY;
        if matches!(kind, FightKind::Elite | FightKind::Boss) {
            relic = self.pick_relic(RunStream::Reward, relic_pool)?;
        }
        // §287：**这一场**战斗的奖励欠账（`Dead Adventurer`）：金币加成与"不掉遗物"。
        // 单消费点：读一次就清，所以它不可能漏进下一场战斗。
        let bonus = i32::from(self.fight_gold_bonus);
        let no_relic = self.fight_no_relic;
        self.fight_gold_bonus = 0;
        self.fight_no_relic = false;
        if bonus != 0 {
            paid = paid.saturating_add(bonus);
        }
        if no_relic {
            relic = RunId::EMPTY;
        }
        // §269：`black_star` —— "Elites now drop an additional relic when defeated"。
        // ⚠️ 第二件**直接进包**（奖励屏只有一个遗物槽）。这不是"更省事"，是**代价最小**：
        // 加第二个槽要改 `Reward` 结构、ABI 与页面三处。偏差写在这里，别让它悄悄消失。
        if matches!(kind, FightKind::Elite)
            && self.holds_relic_effect(RelicEffect::EliteExtraRelic)
        {
            let extra = self.pick_relic(RunStream::Reward, relic_pool)?;
            if extra.as_str() != "" {
                if let Ok(id) = RunId::new(extra.as_str()) {
                    let _ = self.push_relic(id.as_str(), card_pool);
                }
            }
        }
        self.reward = Reward {
            gold: paid,
            cards,
            cards_len: wanted as u8,
            potion,
            relic,
        };
        self.pending = Pending::Reward;
        Ok(())
    }

    /// §269：这一屏**给几张**卡牌奖励。
    ///
    /// 基数 3（`inv:§3.5`）加上所有遗物的 `RewardCardDelta`（掩码覆盖这一场才算），再钳到
    /// `1..=MAX_REWARD_CARDS`。**下限 1**：`busted_crown` 的 -2 不能把一屏变成 0 张
    /// （那就不是"少两张"，而是"没有奖励" —— 另一条规则）。
    #[must_use]
    pub fn reward_card_count(&self, kind: FightKind) -> usize {
        let mut count = BASE_REWARD_CARDS as i32;
        // §270：一件遗物有**两半**时（`busted_crown` = 每回合 +1 能量 **且** 奖励卡数 -2），
        // `relic_effect` 只能表达一个（它返回单个变体）。第二半在 `RELIC_SECOND_HALVES` 里，
        // 这里只挑自己认识的那一类，其余忽略。
        for (relic, effect) in RELIC_SECOND_HALVES.iter().copied() {
            let RelicEffect::RewardCardDelta(delta, kinds) = effect else {
                continue;
            };
            if kinds.covers(kind) && self.holds_relic(relic) {
                count += delta;
            }
        }
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::RewardCardDelta(delta, kinds)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                if kinds.covers(kind) {
                    count += delta;
                }
            }
        }
        count.clamp(1, MAX_REWARD_CARDS as i32) as usize
    }

    /// §259：`Dream Catcher` —— 休息之后给**一次卡牌奖励**（wiki："Whenever you Rest, you may add a
    /// card to your deck"）。
    ///
    /// 为什么不复用 [`Self::roll_reward`]：那条路会一并掷**金币 / 药水 / 精英遗物**，而这里
    /// wiki 只给卡。把三样都掷一遍会让"休息"变成"打了一场普通怪"，而且 `run_hash` 会跟着变
    /// —— 那是**另一种游戏规则**，不是省事。
    ///
    /// 前置：`pending == Pending::Reward` 表示"刚休息完、还没拿奖励"（`rest()` 在有这件遗物时
    /// 就停在这里）。池子里的 `Status` / `Curse` / `Special` 不是奖励，照 `roll_reward` 的规矩排除。
    pub fn roll_rest_card_reward(&mut self, card_pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let mut eligible = [0usize; MAX_POOL];
        let mut eligible_len = 0usize;
        Self::pool_fits(card_pool.len())?;
        for index in 0..card_pool.len() {
            if !matches!(
                card_pool[index].rarity,
                Rarity::Status | Rarity::Curse | Rarity::Special
            ) {
                eligible[eligible_len] = index;
                eligible_len += 1;
            }
        }
        // §269：`Dream Catcher` 那一屏固定 **3** 张（`BASE_REWARD_CARDS`）—— 它是"休息之后的
        // 一次卡牌奖励"，与战斗奖励屏的张数规则无关（`question_card` 说的是 "card rewards"，
        // 而这里给的是"一次奖励"；把它也算进来会让休息变成打一场怪）。存储仍是 4 张的容量。
        if eligible_len < BASE_REWARD_CARDS {
            return Err(RunError::PoolTooSmall {
                pool: eligible_len,
                need: BASE_REWARD_CARDS,
            });
        }
        let eligible = &eligible[..eligible_len];
        let mut used = [false; MAX_POOL];
        let mut cards = [RunId::EMPTY; MAX_REWARD_CARDS];
        for slot in 0..BASE_REWARD_CARDS {
            // `Dream Catcher` 的奖励是**普通怪**档位（wiki 没有单独的概率表）。
            let (rare_top, uncommon_top) = reward_bands(FightKind::Normal, self.rarity_offset);
            let roll = self.rng.roll(RunStream::Reward, 100)? as i32;
            let band = if roll < rare_top {
                Rarity::Rare
            } else if roll < uncommon_top {
                Rarity::Uncommon
            } else {
                Rarity::Common
            };
            let mut picked = self.pick_of(card_pool, eligible, &used, Some(band))?;
            if picked.is_none() {
                picked = self.pick_of(card_pool, eligible, &used, Some(Rarity::Basic))?;
            }
            if picked.is_none() {
                picked = self.pick_of(card_pool, eligible, &used, None)?;
            }
            let Some(index) = picked else {
                return Err(RunError::PoolTooSmall {
                    pool: eligible_len,
                    need: MAX_REWARD_CARDS,
                });
            };
            used[index] = true;
            cards[slot] = RunId::new(card_pool[index].id).map_err(|_| RunError::BadId)?;
            if band == Rarity::Rare {
                self.rarity_offset = RARITY_OFFSET_START;
            } else {
                self.rarity_offset = (self.rarity_offset + 1).min(RARITY_OFFSET_CAP);
            }
        }
        self.reward = Reward {
            gold: 0,
            cards,
            cards_len: BASE_REWARD_CARDS as u8,
            potion: RunId::EMPTY,
            relic: RunId::EMPTY,
        };
        Ok(())
    }

    /// The gold this fight paid (already added to the run; §157's idol multiplier is in it).
    #[must_use]
    pub fn reward_gold(&self) -> i32 {
        self.reward.gold()
    }

    /// The potion this fight dropped, or `None`.
    #[must_use]
    pub fn reward_potion(&self) -> Option<&str> {
        let id = self.reward.potion.as_str();
        if id.is_empty() {
            None
        } else {
            Some(id)
        }
    }

    /// The relic this fight pays, or `None` (§155: elites and bosses only).
    #[must_use]
    pub fn reward_relic(&self) -> Option<&str> {
        let id = self.reward.relic.as_str();
        if id.is_empty() {
            None
        } else {
            Some(id)
        }
    }

    /// Take the relic off the reward table.
    ///
    /// Goes through [`Self::push_relic`] -- the single grant point (§145) -- so a fight-won relic is
    /// validated and its run-level effects fire exactly like a chest's. A full relic list is an
    /// **error**, not a silent drop.
    /// §274：`pool` 给 `push_relic`（拾取类遗物要看牌的类型与 `+` 行）。
    pub fn take_relic(&mut self, pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let id = self.reward.relic;
        if id.as_str().is_empty() {
            return Err(RunError::NoSuchRelic);
        }
        self.push_relic(id.as_str(), pool)?;
        self.reward.relic = RunId::EMPTY;
        Ok(())
    }

    /// Take the potion off the reward table. A **full belt is an error**, not a silent discard:
    /// dropping what the player was just offered without telling them is the kind of quiet loss
    /// this project keeps banning.
    pub fn take_potion(&mut self) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let id = self.reward.potion;
        if id.as_str().is_empty() {
            return Err(RunError::NoSuchPotion);
        }
        self.push_potion(id.as_str())?;
        self.reward.potion = RunId::EMPTY;
        Ok(())
    }

    /// The current pity offset (`inv:§3.5`). Exposed because a UI may want to show it, and because a
    /// test that only checks the odds cannot see a counter that never moves.
    #[must_use]
    pub const fn rarity_offset(&self) -> i32 {
        self.rarity_offset
    }

    /// A uniformly chosen **unused** card of `wanted`, or `None` when that bucket has none left.
    fn pick_of(
        &mut self,
        pool: &[PoolCard<'_>],
        eligible: &[usize],
        used: &[bool; MAX_POOL],
        wanted: Option<Rarity>,
    ) -> Result<Option<usize>, RunError> {
        let mut count = 0u32;
        for index in eligible {
            if used[*index] {
                continue;
            }
            // §189 `A12`：`+` 行只能通过"升级抽取"进来。计数与定位是两次遍历，**两边都要跳过**，
            // 只跳一边会让第 i 张彩票落到不同的牌上（第一版就是这样，于是第一幕的奖励屏蹦出
            // 95 张升级牌 —— 比例比 100% 还高，因为位置全错）。
            if pool[*index].id.ends_with('+') {
                continue;
            }
            let rarity = pool[*index].rarity;
            let ok = match wanted {
                Some(rarity_wanted) => rarity == rarity_wanted,
                None => true,
            };
            if ok {
                count += 1;
            }
        }
        if count == 0 {
            return Ok(None);
        }
        let mut target = self.rng.roll(RunStream::Reward, count)? as u32;
        for index in eligible {
            if used[*index] {
                continue;
            }
            if pool[*index].id.ends_with('+') {
                continue;
            }
            let rarity = pool[*index].rarity;
            let ok = match wanted {
                Some(rarity_wanted) => rarity == rarity_wanted,
                None => true,
            };
            if !ok {
                continue;
            }
            if target == 0 {
                return Ok(Some(*index));
            }
            target -= 1;
        }
        Ok(None)
    }

    /// Take card `slot` from the reward screen. **The screen stays open** (§161.8).
    ///
    /// The card, the potion and the relic are three independent rows of one screen: taking the card
    /// must not take the other two with it. This used to set `pending = None; mark_resolved()`,
    /// which meant a player who took the card first **lost the elite's relic** -- and nothing said
    /// so, because the relic row simply vanished with the screen.
    ///
    /// §161.8's vertical slice found it the honest way: its elite scenario took the card (the first
    /// thing a player does) and then asked where the relic went. `take_relic` / `take_potion` were
    /// already correct, so the bug was the asymmetry inside this one function.
    ///
    /// The node is settled by `skip_reward` (or by `leave`), which is also the way out when every
    /// row has been taken.
    /// §270：`card` 是**这一屏那一张牌**（由调用方从内容里带过来 —— 运行层不存内容）。
    ///
    /// 两个来源必须对得上：调用方说"我拿的是 X"、屏幕上也写着 X。对不上就是调用方的错
    /// （拿了第 2 张的 id 去填第 1 个槽，页面上会变成"点了 1 拿走了 3"），所以这里**拒绝**。
    pub fn take_card(&mut self, slot: usize, card: PoolCard<'_>) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let Some(id) = self.reward.cards().get(slot).copied() else {
            return Err(RunError::EmptyOffer(slot as u8));
        };
        if id == RunId::EMPTY {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        if card.id != id.as_str() {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        self.push_card(card)?;
        // The **card choice** is one pick (`inv:§3.5`: "one of three"), so taking it spends the
        // whole row set -- but only that set: the potion and the relic are separate offers on the
        // same screen and stay (`inv:§9.3` already says the potion is its own offer).
        //
        // §161.8: this is the shape StS has. The first fix here blanked just the taken row, which
        // let a driver take **all three** cards from one reward -- the slice's own deck grew by 3.
        for row in self.reward.cards.iter_mut() {
            *row = RunId::EMPTY;
        }
        self.reward.cards_len = 0;
        Ok(())
    }

    /// Decline the card (gold is already in hand; `inv:§3.5` says a reward can be skipped).
    pub fn skip_reward(&mut self) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// Walk away from whatever is pending.
    pub fn leave(&mut self) -> Result<(), RunError> {
        if self.pending == Pending::None {
            return Err(RunError::WrongPhase);
        }
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// The per-step invariants from `run-layer.md` §6.2. A **real** check: the release build is what
    /// runs on the device, and a `debug_assert!` would leave the device unchecked.
    pub fn check_invariants(&self) -> Result<(), RunError> {
        self.map.check().map_err(|_| RunError::MapGeneration)?;
        // The boss lives at floor `ROWS + 1` (`inv:§7.2`: floor 16), off the map -- so the ceiling is
        // one higher when the cursor is on it.
        let at_boss = self.node == i32::from(crate::map::BOSS_NODE);
        let top_floor = if at_boss { ROWS as i32 + 1 } else { ROWS as i32 };
        if self.floor < 0 || self.floor > top_floor {
            return Err(RunError::Invariant("floor out of range"));
        }
        if self.health < 0 || self.health > self.health_max {
            return Err(RunError::Invariant("health outside 0..=max"));
        }
        if self.deck_len as usize > MAX_RUN_DECK
            || self.relics_len as usize > MAX_RUN_RELICS
            || self.potions_len as usize > MAX_RUN_POTIONS
        {
            return Err(RunError::Invariant("a container is over capacity"));
        }
        if self.node < 0 {
            if self.floor != 0 {
                return Err(RunError::Invariant("floor set before the first step"));
            }
        } else if at_boss {
            // The sentinel has no map row; its floor is fixed.
            if self.floor != ROWS as i32 + 1 {
                return Err(RunError::Invariant("the boss is floor ROWS + 1"));
            }
        } else {
            let Some((row, _)) = self.map.locate(self.node as u8) else {
                return Err(RunError::BadNode);
            };
            if row as i32 + 1 != self.floor {
                return Err(RunError::Invariant("floor does not match the node's row"));
            }
        }
        // ---- 标量 -------------------------------------------------------------------------
        if self.gold < 0 {
            return Err(RunError::Invariant("gold must not be negative"));
        }
        if self.removed_cards < 0 {
            return Err(RunError::Invariant("removed_cards must not be negative"));
        }
        if self.act == 0 || self.act > MAX_ACTS {
            return Err(RunError::Invariant("act must be in 1..=MAX_ACTS"));
        }
        if self.ascension > MAX_ASCENSION {
            return Err(RunError::Invariant("ascension must be in 0..=MAX_ASCENSION"));
        }
        if self.potion_chance < 0 || self.potion_chance > 100 {
            return Err(RunError::Invariant("potion_chance must be a percentage"));
        }
        if self.rarity_offset < RARITY_OFFSET_START || self.rarity_offset > RARITY_OFFSET_CAP {
            return Err(RunError::Invariant("rarity_offset is outside its pity band"));
        }

        // 已结算位图只许指向地图上的节点（哨兵与越界位都不算）。
        for word in 0..self.resolved.len() {
            let mut bits = self.resolved[word];
            while bits != 0 {
                let bit = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                let index = word * 64 + bit;
                if index >= self.map.node_count() {
                    return Err(RunError::Invariant("a resolved bit points off the map"));
                }
            }
        }

        // ---- `len` 之前有内容、之后是空的（§161.10 的 `remove_card` 尾槽就是这个漏的）----
        if self.deck_len as usize > MAX_RUN_DECK {
            return Err(RunError::Invariant("deck_len exceeds the deck capacity"));
        }
        for (index, card) in self.deck.iter().enumerate() {
            let used = index < self.deck_len as usize;
            if used && card.as_str().is_empty() {
                return Err(RunError::Invariant("a deck slot inside len is empty"));
            }
            if !used && !card.as_str().is_empty() {
                // §161.10：`remove_card` 曾经把被删的牌留在这里，而存档只写前 `len` 项。
                return Err(RunError::Invariant("a deck slot past len is not empty"));
            }
        }
        if self.relics_len as usize > MAX_RUN_RELICS {
            return Err(RunError::Invariant("relics_len exceeds the relic capacity"));
        }
        for (index, relic) in self.relics.iter().enumerate() {
            let used = index < self.relics_len as usize;
            if used && relic.as_str().is_empty() {
                return Err(RunError::Invariant("a relic slot inside len is empty"));
            }
            if !used && !relic.as_str().is_empty() {
                return Err(RunError::Invariant("a relic slot past len is not empty"));
            }
        }
        // 遗物不重复：重复的一件会付两次钱。
        for (index, relic) in self.relics.iter().take(self.relics_len as usize).enumerate() {
            if self.relics[..index].contains(relic) {
                return Err(RunError::Invariant("the same relic is held twice"));
            }
        }
        if self.potions_len > self.potion_slots() {
            // Potion Belt 才是格数的来源（§157）：没有它就装不下第 4、5 瓶。
            return Err(RunError::Invariant("more potions than the belt has slots"));
        }
        for (index, potion) in self.potions.iter().enumerate() {
            let used = index < self.potions_len as usize;
            if used && potion.as_str().is_empty() {
                return Err(RunError::Invariant("a potion slot inside len is empty"));
            }
            if !used && !potion.as_str().is_empty() {
                return Err(RunError::Invariant("a potion slot past len is not empty"));
            }
        }

        // ---- 问句必须与它站着的房间一致 ------------------------------------------------------
        if self.blessing_follow.is_some() && self.pending != Pending::BlessingCard {
            return Err(RunError::Invariant("a blessing follow-up without its question"));
        }
        if self.event_follow.is_some() && self.pending != Pending::EventCard {
            return Err(RunError::Invariant("an event follow-up without its question"));
        }
        if self.start_offers[0] as usize >= START_OFFERS.len()
            || self.start_offers[1] as usize >= START_OFFERS.len()
        {
            return Err(RunError::Invariant("a rolled blessing is not in the table"));
        }
        if self.pending == Pending::Start && self.floor != 0 {
            return Err(RunError::Invariant("the blessing screen exists only before floor 1"));
        }
        if self.pending == Pending::Event && self.event.as_str().is_empty() {
            return Err(RunError::Invariant("an event screen without an event"));
        }
        if let Some(room) = self.pending.room() {
            // Boss 是哨兵，它的"房间类型"由楼层决定（§161.8 的路由就是这么走的）。
            let here = self.node_at_cursor();
            if here != Some(room) {
                return Err(RunError::Invariant("the pending screen is not this room"));
            }
        }

        // ---- 商店与奖励屏 -------------------------------------------------------------------
        // ⚠️ 这条判据我写错过**两次**，两次都被闸门当场打红 —— 记在这里：
        //   1. "每一行都必须是活报价"：买过的行 price = -1 但 `count` 不减（槽位下标要稳定，
        //      页面靠它下 `buy_card(slot)`）⇒ 合法局面被拒；
        //   2. "有 id ⇔ 有价格"：`buy_card` **保留 id**、只把 price 设成 -1（`stock_shop` 才是
        //      "有 id + 有价"）⇒ 合法的"已买"被当成半死不活。
        // 真正的不变量只有两条：**活报价必须有 id**，以及**价格不会低于 -1**（-1 = 已经买走或
        // 从没上架，两种死法在数据上是一样的，不该分开猜）。
        for offer in self.shop.cards.iter().take(self.shop.cards_len as usize) {
            if offer.price < -1 || (offer.price >= 0 && offer.id.as_str().is_empty()) {
                return Err(RunError::Invariant("a live shop card row has no id"));
            }
        }
        for offer in self.shop.relics.iter().take(self.shop.relics_len as usize) {
            if offer.price < -1 || (offer.price >= 0 && offer.id.as_str().is_empty()) {
                return Err(RunError::Invariant("a live shop relic row has no id"));
            }
        }
        if self.reward.cards_len as usize > MAX_REWARD_CARDS || self.reward.gold < 0 {
            return Err(RunError::Invariant("the reward screen is malformed"));
        }
        Ok(())
    }

    /// 游标下这个节点的**类型**；哨兵按 Boss 算，还没出发就是 `None`。
    ///
    /// `NodeKind::Boss` 在生成器里从不赋值（Boss 是地图外的哨兵），所以"类型"必须由这里回答，
    /// 而不是去地图里找 —— 那是 §161.8 的路由器踩过的同一件事。
    #[must_use]
    pub fn node_at_cursor(&self) -> Option<NodeKind> {
        let node = u8::try_from(self.node).ok()?;
        if node == crate::map::BOSS_NODE {
            return Some(NodeKind::Boss);
        }
        let (row, local) = self.map.locate(node)?;
        self.map.row(row)?.node(local).map(|node| node.kind)
    }

}

/// The tripwire. Prints the measured size and its headroom so the number in a memory table never
/// has to be transcribed by hand (discipline: one source, and it points rather than copies).
#[must_use]
pub fn state_fits_the_tripwire() -> (usize, usize) {
    let bytes = RunState::size_bytes();
    assert!(
        bytes <= RUN_STATE_TRIPWIRE_BYTES,
        "RunState is {bytes} B, over the {RUN_STATE_TRIPWIRE_BYTES} B tripwire. \
         Raise the tripwire **in both places** and say in the commit what the extra bytes buy \
         -- and if the growth is a capacity, check first whether enlarging it changes behaviour, \
         because then it is semantics and not a budget (port-plan.md §45.4)."
    );
    (bytes, RUN_STATE_TRIPWIRE_BYTES - bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// §273：**比货架多**的一份池子（7 张 vs `MAX_SHOP_CARDS` = 5）—— 补货判据要它，否则
    /// "买走一格再补一格"根本补不出来（3 张的池子被 3 格货架一次用尽）。
    const SHOP_CARDS: [PoolCard<'static>; 7] = [
        PoolCard { id: "strike", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None },
        PoolCard { id: "defend", rarity: Rarity::Common, kind: CardKind::Skill, upgraded: None },
        PoolCard { id: "anger", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None },
        PoolCard { id: "bash", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None },
        PoolCard { id: "clash", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None },
        PoolCard { id: "flex", rarity: Rarity::Common, kind: CardKind::Skill, upgraded: None },
        PoolCard { id: "havoc", rarity: Rarity::Common, kind: CardKind::Skill, upgraded: None },
    ];

    /// §270：带**类型**的一份小卡池（几条判据要"加一张 Attack / Skill"）。
    /// 名字不叫 `CARDS`：那个已经是"七张 `&str`"的老常量。
    const TYPED_CARDS: [PoolCard<'static>; 3] = [
        PoolCard { id: "strike", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None },
        PoolCard { id: "defend", rarity: Rarity::Common, kind: CardKind::Skill, upgraded: None },
        PoolCard { id: "anger", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: None },
    ];

    /// §270：这次"拿牌"的**那一张**。`take_card` / `buy_card` 现在要把牌本身交进去
    /// （三个蛋与两条诅咒规则要看类型），所以测试里从 run 自己存的那一格造一张裸卡 ——
    /// 这正是运行层要的"两个来源对得上"（id 一样、其余字段运行层不看）。
    fn take_card_at(run: &mut RunState, slot: usize) -> Result<(), RunError> {
        // ⚠️ 没有那一格时给一个**空 id**，而不是在这里 panic：拒绝必须由**运行层**给出 ——
        // "拒绝"是这几条判据要看的东西，helper 抢先炸掉就等于把判据换成了"helper 越界"。
        let id = run.reward().cards().get(slot).copied().unwrap_or(RunId::EMPTY);
        run.take_card(slot, PoolCard::plain(id.as_str()))
    }

    /// 同上，货架那一格。
    fn buy_card_at(run: &mut RunState, slot: usize) -> Result<(), RunError> {
        let id = run
            .shop()
            .cards()
            .get(slot)
            .map_or(RunId::EMPTY, |offer| offer.id);
        run.buy_card(slot, PoolCard::plain(id.as_str()), &TYPED_CARDS)
    }

    /// §273：买**遗物**那一格（补货要池子，所以这里也带一份）。
    fn buy_relic_at(run: &mut RunState, slot: usize) -> Result<(), RunError> {
        run.buy_relic(slot, &TYPED_CARDS, &RELICS)
    }
    use crate::map::NodeKind;

    fn ironclad() -> RunState {
        let deck = [
            "strike", "strike", "strike", "strike", "strike",
            "defend", "defend", "defend", "defend",
            "bash",
        ];
        RunState::new(7, 80, 99, &deck).expect("a run must start")
    }

    /// **真人的局面必须通过校验器**（§162）。太严的校验器比没有更糟。
    ///
    /// 走一整幕：每个节点都结算，每一步都问一次。这条测试存在的理由是"我加的那些不变量是从代码
    /// 里读出来的，而代码里有我不知道的例外" —— 只有真跑一遍才知道有没有。
    #[test]
    fn a_real_run_validates_at_every_step() {
        let mut run = ironclad();
        run.check_invariants().expect("a fresh run");
        // 出发前：挑一个第一层的节点。
        let mut steps = 0;
        for _ in 0..40 {
            let mut moved = false;
            for target in 0..crate::map::BOSS_NODE {
                if run.enter_node(target).is_ok() {
                    moved = true;
                    break;
                }
            }
            if !moved {
                break;
            }
            run.check_invariants().unwrap_or_else(|e| panic!("step {steps}: {e:?}"));
            // 结算这个节点：`enter_node` 只挪游标，**开节点**是另一件事（`begin_node` 会给
            // 篝火/商店/宝箱摆好问句）。少了这一步，下面每个 `rest`/`leave` 都是 WrongPhase。
            let pool = [PoolCard {
                id: "strike",
                rarity: Rarity::Common,
                kind: CardKind::Other,
                upgraded: None,
            }];
            match run.node_at_cursor() {
                Some(NodeKind::Rest) => {
                    run.begin_node(&pool, &RELICS).expect("begin the campfire");
                    run.check_invariants().expect("a rest site is pending");
                    run.rest().expect("rest");
                }
                Some(NodeKind::Treasure) => {
                    run.begin_node(&pool, &RELICS).expect("begin the chest");
                    run.check_invariants().expect("a chest is pending");
                    // `open_chest` 自己结算这个节点（之后 `leave` 会是 WrongPhase）。
                    run.open_chest(&TYPED_CARDS, &RELICS).expect("open");
                    run.check_invariants().expect("after the chest");
                }
                Some(NodeKind::Shop) => {
                    run.begin_node(&pool, &RELICS).expect("stock the shop");
                    run.check_invariants().expect("a shop is pending");
                    run.leave().expect("leave");
                }
                _ => {}
            }
            run.mark_resolved();
            run.check_invariants().unwrap_or_else(|e| panic!("resolved {steps}: {e:?}"));
            steps += 1;
            if run.node() == i32::from(crate::map::BOSS_NODE) {
                break;
            }
        }
        assert!(steps >= 8, "the fixture must actually walk, it took {steps} steps");
    }

    /// 每条不变量各一条反例，而且都指名它自己。**一条断言一个原因** —— 否则"拒绝了"什么都证明不了。
    #[test]
    fn every_invariant_names_itself_when_violated() {
        let base = || ironclad();

        let mut run = base();
        run.health = run.health_max + 1;
        assert_eq!(
            run.check_invariants(),
            Err(RunError::Invariant("health outside 0..=max"))
        );

        let mut run = base();
        run.gold = -1;
        assert_eq!(
            run.check_invariants(),
            Err(RunError::Invariant("gold must not be negative"))
        );

        let mut run = base();
        run.act = 0;
        assert_eq!(run.check_invariants(), Err(RunError::Invariant("act must be in 1..=MAX_ACTS")));

        let mut run = base();
        run.floor = 3;
        assert_eq!(run.check_invariants(), Err(RunError::Invariant("floor set before the first step")));

        let mut run = base();
        run.node = 99;
        assert_eq!(run.check_invariants(), Err(RunError::BadNode));

        // 楼层与游标不一致：走到某一层，然后把楼层改掉。
        let mut run = base();
        assert!(run.enter_node(0).is_ok() || run.enter_node(1).is_ok() || run.enter_node(2).is_ok());
        run.floor += 1;
        assert_eq!(
            run.check_invariants(),
            Err(RunError::Invariant("floor does not match the node's row"))
        );

        // §161.10 的那个坑：`len` 之后不是空的。
        let mut run = base();
        let stale = run.deck[run.deck_len as usize - 1];
        run.deck[run.deck_len as usize] = stale;
        assert_eq!(
            run.check_invariants(),
            Err(RunError::Invariant("a deck slot past len is not empty"))
        );

        // 同一件遗物两份：先让手上真的有两件，再把第二件写成第一件。
        let mut run = base();
        // 先让手上真的有两件**不同的**遗物，再把第二件写成第一件 —— 否则会先撞上
        // "len 之后的槽位不是空的"，那一条不是这条测试要问的。
        run.push_relic("anchor", &TYPED_CARDS).expect("relic room");
        run.push_relic("vajra", &TYPED_CARDS).expect("relic room");
        run.relics[1] = run.relics[0];
        assert_eq!(
            run.check_invariants(),
            Err(RunError::Invariant("the same relic is held twice"))
        );

        // 药水比腰带格数多（没有 Potion Belt 就是 3 格）。
        let mut run = base();
        run.potions_len = run.potion_slots() + 1;
        assert_eq!(
            run.check_invariants(),
            Err(RunError::Invariant("more potions than the belt has slots"))
        );

        // 问句与房间不一致：把 pending 设成 Rest 而脚下是战斗。
        let mut run = base();
        assert!(run.enter_node(0).is_ok() || run.enter_node(1).is_ok() || run.enter_node(2).is_ok());
        run.pending = Pending::Rest;
        assert_eq!(
            run.check_invariants(),
            Err(RunError::Invariant("the pending screen is not this room"))
        );

        // 后续动作与问句脱钩。
        let mut run = base();
        run.event_follow = Some(DeckChange::Remove);
        assert_eq!(
            run.check_invariants(),
            Err(RunError::Invariant("an event follow-up without its question"))
        );

        // 祝福不在表里。
        let mut run = base();
        run.start_offers = [0, 200];
        assert_eq!(
            run.check_invariants(),
            Err(RunError::Invariant("a rolled blessing is not in the table"))
        );

        // 活报价却没有 id：价格在、货不在 —— 那才是坏局面。
        // （不设 `pending`：这条判据与问句无关，把 `pending` 硬设成 Shop 会让"问句与房间一致"
        // 先响，那是另一条测试的事。）
        let mut run = base();
        run.shop.cards_len = 1;
        run.shop.cards[0].id = RunId::EMPTY;
        run.shop.cards[0].price = 50;
        assert_eq!(
            run.check_invariants(),
            Err(RunError::Invariant("a live shop card row has no id"))
        );
        // price = -1 是**合法**的（买走或没上架），不算错。
        run.shop.cards[0].id = RunId::new("strike").expect("id");
        run.shop.cards[0].price = -1;
        assert_eq!(run.check_invariants(), Ok(()));
    }

    #[test]
    fn a_new_run_is_before_the_map_with_a_known_start() {
        let run = ironclad();
        assert_eq!(run.floor(), 0, "floor is 0 before the first step");
        assert_eq!(run.node(), -1, "the cursor starts off the map");
        assert_eq!(run.health(), 80);
        assert_eq!(run.health_max(), 80);
        assert_eq!(run.gold(), 99);
        assert_eq!(run.deck().len(), 10);
        // `inv:§2.1`: 5 strike + 4 defend + 1 bash, **in that order** (deck order is observable).
        let names: Vec<&str> = run.deck().iter().map(RunId::as_str).collect();
        assert_eq!(names[0], "strike");
        assert_eq!(names[9], "bash");
        assert_eq!(run.check_invariants(), Ok(()));
    }

    /// The first step is a **free choice among floor 1**, not a single entry point (`inv:§7.2`).
    #[test]
    fn the_first_step_may_enter_any_floor_one_node_and_nothing_else() {
        let run = ironclad();
        let reachable = run.reachable();
        let floor_one = run.map().row(0).unwrap().len();
        assert_eq!(reachable.len(), floor_one);
        assert!(reachable.len() >= 2, "floor 1 must offer a choice");
        for index in 0..reachable.len() {
            let node = reachable.get(index).unwrap();
            assert_eq!(run.map().locate(node).unwrap().0, 0);
        }
        // A floor-2 node is not reachable yet.
        if let Some(first_row_two) = run.map().row_first(1) {
            assert!(!reachable.contains(first_row_two));
        }
    }

    #[test]
    fn walking_follows_edges_and_never_teleports() {
        let mut run = ironclad();
        let start = run.reachable().get(0).unwrap();
        run.enter_node(start).unwrap();
        assert_eq!(run.floor(), 1);
        assert_eq!(run.node(), i32::from(start));
        assert_eq!(run.check_invariants(), Ok(()));

        // One legal step per floor, all the way down, always taking the first option.
        let mut steps = 1;
        while run.floor() < ROWS as i32 {
            let reachable = run.reachable();
            assert!(!reachable.is_empty(), "floor {} has no exit", run.floor());
            let next = reachable.get(0).unwrap();
            // **You settle before you walk on**, so this test settles the way a finished fight does.
            // (`the_cheat_of_skipping_a_node` below is what pins the rule itself.)
            run.mark_resolved();
            run.enter_node(next).unwrap();
            steps += 1;
            assert_eq!(run.floor() as usize, steps);
            assert_eq!(run.check_invariants(), Ok(()));
        }
        assert_eq!(run.floor(), ROWS as i32);
        // The last row leads to the boss (inv:§7.2: floor 16, off the map) and to nothing else.
        let tail = run.reachable();
        assert_eq!(tail.len(), 1, "the last row has exactly one exit");
        assert_eq!(tail.get(0), Some(crate::map::BOSS_NODE), "and it is the boss");
    }

    #[test]
    fn entering_a_node_that_is_not_an_edge_is_an_error_and_changes_nothing() {
        let mut run = ironclad();
        let mut ids: Vec<u8> = Vec::new();
        for row in 0..ROWS {
            if let Some(first) = run.map().row_first(row) {
                for local in 0..run.map().row(row).unwrap().len() {
                    ids.push(first + local as u8);
                }
            }
        }
        let before = run;
        // A node on floor 7 is not an edge out of "before the map".
        let far = ids.iter().copied().find(|id| run.map().locate(*id).unwrap().0 == 6).unwrap();
        assert_eq!(run.enter_node(far), Err(RunError::NotReachable));
        assert_eq!(run, before, "a rejected step must leave the run byte-identical");

        // And from a real node, a sibling that is not one of its targets is refused too.
        let start = run.reachable().get(0).unwrap();
        run.enter_node(start).unwrap();
        let snapshot = run;
        let sibling = (0..run.map().row(1).unwrap().len() as u8)
            .map(|local| run.map().global_of(1, local as usize).unwrap())
            .find(|id| !run.reachable().contains(*id))
            .expect("floor 2 has at least one node that is not an edge");
        assert_eq!(run.enter_node(sibling), Err(RunError::NotReachable));
        assert_eq!(run, snapshot);
    }

    #[test]
    fn capacity_is_an_error_not_a_truncation() {
        let mut run = ironclad();
        let mut pushed = 10;
        loop {
            match run.push_card(PoolCard::plain("strike")) {
                Ok(()) => pushed += 1,
                Err(e) => {
                    assert_eq!(e, RunError::Capacity);
                    break;
                }
            }
            assert!(pushed <= MAX_RUN_DECK, "the push must stop at the capacity");
        }
        assert_eq!(pushed, MAX_RUN_DECK, "a full deck must be reachable exactly");
        assert_eq!(run.deck().len(), MAX_RUN_DECK);
        // The same for relics, whose bound is smaller than the content pool.
        for _ in 0..MAX_RUN_RELICS {
            run.push_relic("burning_blood", &TYPED_CARDS).unwrap();
        }
        assert_eq!(run.push_relic("burning_blood", &TYPED_CARDS), Err(RunError::Capacity));
        // Potions, on a **fresh** run: this one's relic list is already full, so `potion_belt`
        // could not be granted here. The rule is three slots (`inv:§9.3`, §157) even though the
        // storage is five, so that the belt relic can hand out two more.
        let mut potion_run = ironclad();
        for _ in 0..BASE_POTION_SLOTS {
            potion_run.push_potion("fire_potion").unwrap();
        }
        assert_eq!(potion_run.push_potion("fire_potion"), Err(RunError::Capacity));
        potion_run.push_relic("potion_belt", &TYPED_CARDS).expect("the belt");
        for _ in 0..2 {
            potion_run.push_potion("fire_potion").expect("the belt's two slots");
        }
        assert_eq!(
            potion_run.push_potion("fire_potion"),
            Err(RunError::Capacity),
            "and the storage bound still holds"
        );
        // An id longer than the id capacity is refused, not silently shortened.
        assert_eq!(run.push_card(PoolCard::plain(&"x".repeat(ID_CAP + 1))), Err(RunError::BadId));
        assert_eq!(run.deck().len(), MAX_RUN_DECK);
    }

    #[test]
    fn health_and_gold_are_clamped_and_the_blood_heal_never_overheals() {
        let mut run = ironclad();
        run.adjust_health(-30);
        assert_eq!(run.health(), 50);
        run.heal_after_combat(6);
        assert_eq!(run.health(), 56);
        // At full health the heal does nothing rather than overflowing.
        run.adjust_health(1000);
        assert_eq!(run.health(), 80);
        run.heal_after_combat(6);
        assert_eq!(run.health(), 80);
        // Zero is the floor: a run at 0 is over, not negative.
        run.adjust_health(-1000);
        assert_eq!(run.health(), 0);
        run.adjust_gold(-1000);
        assert_eq!(run.gold(), 0);
        run.adjust_gold(25);
        assert_eq!(run.gold(), 25);
    }

    /// `Burning Blood` heals 6 at the end of a fight, capped at the maximum, and reports what it
    /// actually restored. The cap matters: a run at 78/80 gains 2, and a caller that prints "+6"
    /// there would be lying.
    #[test]
    fn burning_blood_heals_six_at_the_end_of_a_fight() {
        let mut run = ironclad();
        run.push_relic("burning_blood", &TYPED_CARDS).unwrap();
        run.adjust_health(-20);
        assert_eq!(run.health(), 60);
        assert_eq!(run.end_of_combat(), Ok(6));
        assert_eq!(run.health(), 66);
        // No second heal from one call, and none when the fight did not end.
        assert_eq!(run.health(), 66);
        // At the cap it restores only what fits, and still reports the truth.
        run.adjust_health(1000);
        assert_eq!(run.health(), 80);
        run.adjust_health(-1);
        assert_eq!(run.end_of_combat(), Ok(1));
        assert_eq!(run.health(), 80);
    }

    /// A relic whose effect this kernel cannot run is an **error**, not a no-op. This is the loud
    /// boundary of the whole relic system: `REL.RunPrograms`/`CombatRules` are not executed, so an
    /// unknown id must fail rather than quietly do nothing.
    ///
    /// ⚠️ §145 改了这条测试的**位置**，理由和测试本身一样：`vajra` 现在是**实现了**的（战力 +1），
    /// 所以它不再是反例。反例换成一件内核确实还没有的遗物（`golden_idol`），而且拒绝发生在
    /// **`push_relic` 那一刻** —— 玩家还看得见是谁要塞给他。
    #[test]
    fn a_relic_with_no_implemented_effect_is_an_error() {
        let mut run = ironclad();
        assert_eq!(
            run.push_relic("no_such_relic", &TYPED_CARDS),
            Err(RunError::UnsupportedRelic { index: 0 }),
            "一件内核跑不了的遗物必须在**授予那一刻**被拒"
        );
        assert_eq!(run.relics().len(), 0, "拒绝之后腰带上什么都没有");
        // And a run with no relics has nothing to do, which is not an error.
        let mut bare = ironclad();
        assert_eq!(bare.end_of_combat(), Ok(0));
        assert_eq!(bare.health(), 80);
    }

    /// §145：池子里**已经戴在身上的**那件不会再发一次 —— 宝箱和商店是同一条规则。
    #[test]
    fn a_relic_you_already_hold_is_not_offered_again() {
        let pool = [
        PoolRelic {
            id: "burning_blood",
            rarity: Rarity::Common,
        },
        PoolRelic {
            id: "anchor",
            rarity: Rarity::Common,
        },
        PoolRelic {
            id: "vajra",
            rarity: Rarity::Common,
        },
    ];
        let mut run = ironclad();
        run.push_relic("burning_blood", &TYPED_CARDS).expect("the starter relic");

        // The chest: with only one un-held relic in the pool, every chest must give that one.
        // Repeated because the draw is random -- one iteration would pass by luck.
        for round in 0..12 {
            let unheld = pool
                .iter()
                .filter(|entry| !run.relics().iter().any(|held| held.as_str() == entry.id))
                .count();
            run.pending = Pending::Chest;
            let outcome = run.open_chest(&TYPED_CARDS, &pool).expect("a chest");
            let got = outcome.relic.map(|id| id.as_str().to_string());
            if unheld == 0 {
                assert_eq!(got, None, "round {round}: nothing left to give ⇒ no relic, not a copy");
                break;
            }
            assert!(
                got.as_deref() != Some("burning_blood"),
                "round {round}: the chest handed back the relic the hero already wears"
            );
            assert!(got.is_some(), "round {round}: a chest with an un-held relic gave none");
        }

        // The merchant: same filter, and the shelves only hold un-held relics.
        let mut run = ironclad();
        run.push_relic("anchor", &TYPED_CARDS).expect("anchor");
        run.stock_shop(&basic_pool(), &pool).expect("a shop");
        for offer in run.shop().relics() {
            assert_ne!(
                offer.id.as_str(),
                "anchor",
                "the merchant offered a relic the hero already wears"
            );
        }
    }

    /// §145：遗物的三种派发点各自只算一次 —— 授予时（数值）、开战时（奖励）、结束战斗时。
    #[test]
    fn the_relic_pool_fires_at_the_three_hooks_it_has() {
        // 授予时：Pear +10 最大生命，并且**当前生命跟着涨**（StS 的"提升最大生命"一向如此）。
        let mut run = ironclad();
        let before_max = run.health_max();
        let before = run.health();
        run.push_relic("pear", &TYPED_CARDS).expect("pear is implemented");
        assert_eq!(run.health_max(), before_max + 10);
        assert_eq!(run.health(), before + 10);

        // 授予时：Blood Vial 回 2 血，受上限约束。
        let mut run = ironclad();
        run.adjust_health(-20);
        let low = run.health();
        run.push_relic("blood_vial", &TYPED_CARDS).expect("blood vial is implemented");
        assert_eq!(run.health(), low + 2);

        // 开战时：Anchor 10 Block、Vajra 1 力量，而且**两件一起**是相加不是覆盖。
        let mut run = ironclad();
        assert!(run.combat_bonus().is_empty(), "没有遗物就没有加成");
        run.push_relic("anchor", &TYPED_CARDS).expect("anchor");
        let block_only = run.combat_bonus();
        assert_eq!(block_only.block, 10);
        assert_eq!(block_only.status_count, 0);
        run.push_relic("vajra", &TYPED_CARDS).expect("vajra");
        let both = run.combat_bonus();
        assert_eq!(both.block, 10, "两件遗物的加成必须相加");
        assert_eq!(both.status_count, 1);
        assert_eq!(
            both.statuses[0],
            Some(CombatStatus {
                id: "standard.strength",
                stacks: 1
            })
        );

        // §149：`Thread and Needle` 是同一个通用口 —— 4 层 Plated Armor。
        let mut run = ironclad();
        run.push_relic("thread_and_needle", &TYPED_CARDS).expect("thread and needle");
        let bonus = run.combat_bonus();
        assert_eq!(
            bonus.statuses[0],
            Some(CombatStatus {
                id: "standard.plated_armor",
                stacks: 4
            }),
            "开局挂 4 层 Plated Armor"
        );

        // 两件给**同一条**状态的遗物必须合并（不是覆盖）：Vajra + 再一件 1 力量。
        let mut run = ironclad();
        run.push_relic("vajra", &TYPED_CARDS).expect("vajra");
        run.push_relic("vajra", &TYPED_CARDS).expect("vajra again");
        let merged = run.combat_bonus();
        assert_eq!(merged.status_count, 1, "同名状态只有一条");
        assert_eq!(merged.statuses[0].map(|s| s.stacks), Some(2));

        // 结束战斗时：只有 Burning Blood 在这条钩子上，其余四件**什么都不做**（不是"也回血"）。
        let mut run = ironclad();
        for id in ["anchor", "vajra", "pear", "blood_vial"] {
            run.push_relic(id, &TYPED_CARDS).expect("implemented");
        }
        run.adjust_health(-30);
        let wounded = run.health();
        assert_eq!(
            run.end_of_combat(),
            Ok(0),
            "这四件在战斗结束时不回血"
        );
        assert_eq!(run.health(), wounded);
        run.push_relic("burning_blood", &TYPED_CARDS).expect("burning blood");
        assert_eq!(
            run.end_of_combat(),
            Ok(BURNING_BLOOD_HEAL),
            "Burning Blood 是唯一一条战斗结束回血"
        );
        assert_eq!(run.health(), wounded + BURNING_BLOOD_HEAL);
    }

    // ================================================================ §259 篝火四选项

    /// 一个只有牌组的局，用来测篝火的选项集合（地图/战斗都不参与）。
    fn campfire_run() -> RunState {
        let mut run = ironclad();
        run.adjust_health(-20);
        run
    }

    /// `Pending::Rest` 需要一个真的篝火节点。
    ///
    /// ⚠️ `node` 必须是**非负**：`mark_resolved()` / `node_resolved()` 在 `node < 0` 时是
    /// 空操作（那不是"已结算"，是"还没开始"）。第一版忘了这一条，于是"节点已结算"的断言
    /// 在两种情形下都是 `false` —— 一个**永远成立**的断言什么也证明不了。
    fn at_campfire(run: &mut RunState) {
        run.pending = Pending::Rest;
        run.node = 5;
    }

    /// §259：**六件遗物各自改变哪个选项**，以及"满血也能休息 / 全升完则不能打铁"。
    #[test]
    fn campfire_options_follow_the_relics_the_wiki_names() {
        let mut run = campfire_run();
        let base = run.campfire_options();
        assert!(base.rest && base.smith && base.recall, "defaults: Rest / Smith / Recall");
        assert!(!base.lift && !base.toke && !base.dig, "no relic ⇒ no relic option");

        // Girya 开 Lift；用过 3 次之后消失（wiki：up to 3 times）。
        run.push_relic("girya", &TYPED_CARDS).expect("girya");
        assert!(run.campfire_options().lift, "Girya adds Lift");
        for expected in 1..=3u8 {
            at_campfire(&mut run);
            assert_eq!(run.lift(), Ok(expected), "Lift #{expected}");
        }
        assert!(!run.campfire_options().lift, "after three uses Lift is gone");
        at_campfire(&mut run);
        assert_eq!(run.lift(), Err(RunError::WrongPhase), "a fourth Lift is refused");

        // Peace Pipe 开 Toke（然后它还能删牌）；Shovel 开 Dig。
        let mut run = campfire_run();
        run.push_relic("peace_pipe", &TYPED_CARDS).expect("peace pipe");
        run.push_relic("shovel", &TYPED_CARDS).expect("shovel");
        let options = run.campfire_options();
        assert!(options.toke && options.dig, "Peace Pipe / Shovel add their options");

        // Coffee Dripper 与 Mark of the Bloom 关 Rest；Fusion Hammer 关 Smith。
        for relic in ["coffee_dripper", "mark_of_the_bloom"] {
            let mut run = campfire_run();
            run.push_relic(relic, &TYPED_CARDS).expect(relic);
            assert!(!run.campfire_options().rest, "{relic} removes Rest");
            assert!(run.campfire_options().smith, "{relic} does not touch Smith");
        }
        let mut run = campfire_run();
        run.push_relic("fusion_hammer", &TYPED_CARDS).expect("fusion hammer");
        assert!(!run.campfire_options().smith, "Fusion Hammer removes Smith");
        assert!(run.campfire_options().rest, "Fusion Hammer does not touch Rest");
    }

    /// §259：**满血也能休息**（wiki 明写），而"牌组全升完 ⇒ 打铁不可用"。
    ///
    /// 后半条是"选项是算出来的"的直接后果：`+` 行在内容里是另一张卡，所以判据只能是
    /// "牌组里还有没有不带 `+` 的 id"。
    #[test]
    fn resting_is_legal_at_full_health_and_smithing_is_not_legal_with_nothing_to_upgrade() {
        let mut run = campfire_run();
        run.health = run.health_max;
        at_campfire(&mut run);
        assert_eq!(run.rest(), Ok(0), "full health: Rest is still legal, it just heals 0");

        let mut run = campfire_run();
        assert!(run.campfire_options().smith, "an un-upgraded deck can Smith");
        for slot in 0..run.deck_len as usize {
            let upgraded = std::format!("{}+", run.deck[slot].as_str());
            run.deck[slot] = RunId::new(&upgraded).expect("an id");
        }
        assert!(
            !run.campfire_options().smith,
            "everything is upgraded ⇒ Smith is greyed out"
        );
    }

    /// §259：`Toke` 删牌**不收钱**，且与商店删牌共用同一段搬移（`marks` 跟着走）。
    #[test]
    fn toke_removes_a_card_without_charging_for_it() {
        let mut run = campfire_run();
        run.push_relic("peace_pipe", &TYPED_CARDS).expect("peace pipe");
        let gold = run.gold();
        let before = run.deck_len;
        let second_mark = run.marks[1];
        at_campfire(&mut run);
        assert_eq!(run.toke(0), Ok(()), "Toke removes deck[0]");
        assert_eq!(run.deck_len, before - 1, "one card fewer");
        assert_eq!(run.gold(), gold, "Toke is free (unlike the shop's `remove_card`)");
        // §253 的那条纪律：mark 跟着牌走 —— 删掉第一张之后，第二张的 mark 必须还在它身上。
        assert_eq!(run.marks[0], second_mark, "the per-copy mark moves with its card");
        assert_eq!(run.removed_cards(), 0, "Toke is not a paid removal (no price step)");
    }

    /// §259：`Dig` 只抽 **Common/Uncommon/Rare**（wiki 原话），Boss/Shop/Event 一件都不许出。
    #[test]
    fn dig_only_rolls_common_uncommon_or_rare() {
        let mut run = campfire_run();
        run.push_relic("shovel", &TYPED_CARDS).expect("shovel");
        let pool = [
            PoolRelic {
                id: "coffee_dripper",
                rarity: Rarity::Boss,
            },
            PoolRelic {
                id: "golden_idol",
                rarity: Rarity::Event,
            },
            PoolRelic {
                id: "anchor",
                rarity: Rarity::Common,
            },
            PoolRelic {
                id: "vajra",
                rarity: Rarity::Uncommon,
            },
            PoolRelic {
                id: "girya",
                rarity: Rarity::Rare,
            },
        ];
        for seed in 0..24 {
            let mut run = campfire_run();
            run.seed = seed;
            run.push_relic("shovel", &TYPED_CARDS).expect("shovel");
            at_campfire(&mut run);
            let dug = run.dig(&pool).expect("dig");
            assert!(
                ["anchor", "vajra", "girya"].contains(&dug.as_str()),
                "seed {seed}: Dig produced {dug} -- only Common/Uncommon/Rare are allowed"
            );
        }
        let _ = pool;
    }

    /// §259：`Lift` 的力量**每场战斗都带**（不是"只下一场"），而且与 `Vajra` **相加**。
    #[test]
    fn lift_strength_applies_to_every_later_fight_and_stacks_with_vajra() {
        let mut run = campfire_run();
        run.push_relic("girya", &TYPED_CARDS).expect("girya");
        for _ in 0..2 {
            at_campfire(&mut run);
            run.lift().expect("lift");
        }
        let bonus = run.combat_bonus();
        assert_eq!(bonus.status_count, 1, "strength is one merged entry");
        assert_eq!(bonus.statuses[0].map(|s| s.id), Some("standard.strength"));
        assert_eq!(bonus.statuses[0].map(|s| s.stacks), Some(2), "two Lifts ⇒ 2 Strength");

        // 第二场、第三场战斗都还是 2（它读的是 `girya_lifts`，不是"上一次的遗留"）。
        for _ in 0..2 {
            let again = run.combat_bonus();
            assert_eq!(again.statuses[0].map(|s| s.stacks), Some(2), "every fight carries it");
        }

        // 与 Vajra 相加，不是覆盖。
        run.push_relic("vajra", &TYPED_CARDS).expect("vajra");
        let merged = run.combat_bonus();
        assert_eq!(merged.status_count, 1, "one merged Strength entry");
        assert_eq!(merged.statuses[0].map(|s| s.stacks), Some(3), "2 from Girya + 1 from Vajra");
    }

    /// §259：`Dream Catcher`（wiki："Whenever you Rest, you may add a card to your deck"）。
    ///
    /// 两侧：**有**它 ⇒ 休息之后停在奖励屏（节点**还没**结算）；**没有**它 ⇒ 直接结算。
    /// 只测一侧的话，"所有人休息都进奖励屏"也会绿。
    #[test]
    fn dream_catcher_turns_rest_into_a_card_reward_and_only_with_the_relic() {
        let pool = [
            PoolCard { id: "anger", rarity: Rarity::Common, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "flex", rarity: Rarity::Common, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "uppercut", rarity: Rarity::Uncommon, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "bludgeon", rarity: Rarity::Rare, kind: CardKind::Other, upgraded: None },
        ];

        // 没有遗物：休息完就结束，节点已结算。
        let mut run = campfire_run();
        at_campfire(&mut run);
        assert!(run.rest().is_ok());
        assert_eq!(run.pending(), Pending::None, "no Dream Catcher ⇒ no reward screen");
        assert!(run.node_resolved(), "the node is settled right away");
        assert_eq!(
            run.roll_rest_card_reward(&pool),
            Err(RunError::WrongPhase),
            "and there is no reward to roll"
        );

        // 有遗物：停在奖励屏，三张卡，节点**未**结算。
        let mut run = campfire_run();
        run.push_relic("dream_catcher", &TYPED_CARDS).expect("dream catcher");
        at_campfire(&mut run);
        assert!(run.rest().is_ok());
        assert_eq!(run.pending(), Pending::Reward, "Dream Catcher ⇒ a reward screen");
        assert!(!run.node_resolved(), "the node waits for the card choice");
        run.roll_rest_card_reward(&pool).expect("a card reward");
        assert_eq!(run.reward_cards().len(), 3, "three cards, like any reward");
        assert_eq!(run.reward_gold(), 0, "Dream Catcher pays no gold");
        assert!(run.reward_potion().is_none(), "and no potion");
        // 拿走一张：卡那一排花掉，但**药水/遗物那两格还在**（与战斗奖励同一条规矩，
        // `take_card` 的注释写着为什么）⇒ 收尾要 `leave()`。
        assert!(take_card_at(&mut run, 0).is_ok());
        assert_eq!(run.reward_cards().len(), 0, "the card row is spent by one pick");
        assert_eq!(run.pending(), Pending::Reward, "the screen is still open for the rest");
        assert!(run.leave().is_ok());
        assert_eq!(run.pending(), Pending::None);
        assert!(run.node_resolved(), "leaving the reward screen settles the node");
    }

    /// §259：`Recall` 拿红钥匙，然后 Recall 就不再出现（wiki：一局只有一把）。
    #[test]
    fn recall_grants_the_ruby_key_once() {
        let mut run = campfire_run();
        assert!(run.campfire_options().recall, "Recall is offered by default");
        at_campfire(&mut run);
        assert_eq!(run.recall(), Ok(()));
        assert!(run.ruby_key(), "the key is in the run state");
        assert!(!run.campfire_options().recall, "a second Recall is not offered");
        at_campfire(&mut run);
        assert_eq!(run.recall(), Err(RunError::WrongPhase), "and it is refused");
    }

    /// §259：两个新字段**进存档与哈希**。
    ///
    /// 存档 `VERSION` 也跟着抬到 3 —— 这条判据不做"旧存档能不能读"的兼容（那是 `Version` 错误
    /// 该做的事），它钉的是"写出去、读回来，两个字段都在"。
    #[test]
    fn the_campfire_fields_survive_a_save_and_a_hash() {
        // ⚠️ 用**没有节点光标**的局：`archive::restore` 会核 "floor 与 node 的行号一致"，
        // 而 `at_campfire` 故意把 node 设成 5（测结算用），两者的前提不同。
        let mut run = ironclad();
        run.push_relic("girya", &TYPED_CARDS).expect("girya");
        run.push_relic("peace_pipe", &TYPED_CARDS).expect("peace pipe");
        for _ in 0..3 {
            run.pending = Pending::Rest;
            run.lift().expect("lift");
        }
        run.pending = Pending::Rest;
        run.recall().expect("recall");
        let baseline = crate::hash::run_hash(&run).expect("a hash");

        // 走**真实的公开入口**（`archive::write` / `restore`），不是测试专用包装 ——
        // 包装会绕过信封（MAGIC / base64 / RLE / CRC），而"字段进没进 payload"正是要测的东西。
        let mut buf = [0u8; crate::state::archive::MAX_ARCHIVE];
        let len = crate::state::archive::write(&run, 7, &mut buf).expect("write");
        let text = std::str::from_utf8(&buf[..len]).expect("ascii");
        let mut restored = ironclad();
        crate::state::archive::restore(text, 7, &mut restored).expect("read");
        assert_eq!(restored.girya_lifts(), 3, "girya_lifts round-trips");
        assert!(restored.ruby_key(), "ruby_key round-trips");
        assert_eq!(crate::hash::run_hash(&restored).expect("a hash"), baseline, "the hash round-trips too");

        // 反过来：只差一次 Lift 的两局，哈希必须不同（否则"忘了同步哈希"看不出来）。
        let mut other = restored.clone();
        other.girya_lifts = 2;
        assert_ne!(crate::hash::run_hash(&other).expect("a hash"), baseline, "girya_lifts is in the hash");
        let mut other = restored.clone();
        other.ruby_key = false;
        assert_ne!(crate::hash::run_hash(&other).expect("a hash"), baseline, "ruby_key is in the hash");
    }

    /// §274：`old_coin` / `lee's_waffle` —— 两件"改数字"的拾取。
    #[test]
    fn the_pickup_number_relics_change_only_their_own_number() {
        // ---- `old_coin`：+300 金币。
        let mut run = ironclad();
        let gold = run.gold();
        run.push_relic("old_coin", &TYPED_CARDS).expect("old_coin");
        assert_eq!(run.gold(), gold + 300, "old_coin: +300 gold on pickup");

        // 与 `ectoplasm` 一起：金币被拦 ⇒ 一分不给（"gain Gold" 那条规则只有一处）。
        let mut blocked = ironclad();
        blocked.push_relic("ectoplasm", &TYPED_CARDS).expect("ectoplasm");
        let gold = blocked.gold();
        blocked.push_relic("old_coin", &TYPED_CARDS).expect("old_coin");
        assert_eq!(blocked.gold(), gold, "ectoplasm blocks the coin's gold too");

        // ---- `lee's_waffle`：上限 +7 **且回满**（不是"回 7 点"）。
        let mut run = ironclad();
        run.adjust_health(-50);
        let max_before = run.health_max();
        assert!(run.health() < max_before - 20, "the hero must be hurt for this to mean anything");
        run.push_relic("lees_waffle", &TYPED_CARDS).expect("lees_waffle");
        assert_eq!(run.health_max(), max_before + 7, "lee's_waffle: +7 max HP");
        assert_eq!(run.health(), run.health_max(), "…and heal **all** of it");
    }

    /// §274：`war_paint` / `whetstone` —— 随机升级 2 张**自己那一类**的牌。
    #[test]
    fn the_upgrade_eggs_upgrade_two_of_their_own_kind() {
        // 池子里给足"可升的攻击/技能"，并让它们都有 `+` 行。
        const POOL: [PoolCard<'static>; 6] = [
            PoolCard { id: "strike", rarity: Rarity::Basic, kind: CardKind::Attack, upgraded: Some("strike+") },
            PoolCard { id: "bash", rarity: Rarity::Basic, kind: CardKind::Attack, upgraded: Some("bash+") },
            PoolCard { id: "anger", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: Some("anger+") },
            PoolCard { id: "defend", rarity: Rarity::Basic, kind: CardKind::Skill, upgraded: Some("defend+") },
            PoolCard { id: "flex", rarity: Rarity::Common, kind: CardKind::Skill, upgraded: Some("flex+") },
            PoolCard { id: "clash", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: Some("clash+") },
        ];
        let attacks = |run: &RunState| {
            run.deck()
                .iter()
                .filter(|id| {
                    let base = id.as_str().trim_end_matches('+');
                    POOL.iter().any(|c| c.id == base && c.kind == CardKind::Attack)
                })
                .filter(|id| id.as_str().ends_with('+'))
                .count()
        };
        let skills = |run: &RunState| {
            run.deck()
                .iter()
                .filter(|id| {
                    let base = id.as_str().trim_end_matches('+');
                    POOL.iter().any(|c| c.id == base && c.kind == CardKind::Skill)
                })
                .filter(|id| id.as_str().ends_with('+'))
                .count()
        };

        // ---- `whetstone`：攻击牌 +2，**技能一张都不动**。
        let mut run = RunState::new(11, 80, i32::MAX, &["strike", "strike", "strike", "defend", "defend"]).expect("a run");
        run.push_relic("whetstone", &POOL).expect("whetstone");
        assert_eq!(attacks(&run), 2, "whetstone upgrades exactly 2 Attacks");
        assert_eq!(skills(&run), 0, "…and no Skills (that is war_paint's job)");

        // ---- `war_paint`：技能牌 +2，攻击不动。
        let mut run = RunState::new(11, 80, i32::MAX, &["strike", "strike", "defend", "defend", "defend"]).expect("a run");
        run.push_relic("war_paint", &POOL).expect("war_paint");
        assert_eq!(skills(&run), 2, "war_paint upgrades exactly 2 Skills");
        assert_eq!(attacks(&run), 0, "…and no Attacks");

        // ---- 只有 1 张可升时只升 1 张（"2 张"不是硬指标）。
        let mut run = RunState::new(11, 80, i32::MAX, &["strike", "defend", "defend", "defend", "defend"]).expect("a run");
        run.push_relic("whetstone", &POOL).expect("whetstone");
        assert_eq!(attacks(&run), 1, "with one Attack the relic upgrades one");

        // ---- 已经升级过的牌**不吃名额**：牌组全是 `strike+` ⇒ 一张都不再加。
        let mut run = RunState::new(11, 80, i32::MAX, &["strike+", "strike+", "defend"]).expect("a run");
        let before: Vec<RunId> = run.deck().to_vec();
        run.push_relic("whetstone", &POOL).expect("whetstone");
        assert_eq!(run.deck(), &before[..], "nothing to upgrade ⇒ the deck is untouched");
    }

    /// §274：`pandoras_box` —— 把**所有** Strike / Defend 改造掉，**别的牌不动**。
    #[test]
    fn pandoras_box_transforms_every_staple_and_nothing_else() {
        const POOL: [PoolCard<'static>; 3] = [
            PoolCard { id: "strike", rarity: Rarity::Basic, kind: CardKind::Attack, upgraded: Some("strike+") },
            PoolCard { id: "defend", rarity: Rarity::Basic, kind: CardKind::Skill, upgraded: Some("defend+") },
            // 改造的**来源**：内容里能抽出什么。`bash` 不是 Strike/Defend，所以它只会**出现**
            // 在结果里，不会被当成目标。
            PoolCard { id: "bash", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: Some("bash+") },
        ];
        let mut run = RunState::new(7, 80, i32::MAX, &["strike", "strike", "defend", "bash", "clash"]).expect("a run");
        run.push_relic("pandoras_box", &POOL).expect("pandoras_box");
        let deck: Vec<&str> = run.deck().iter().map(RunId::as_str).collect();
        assert_eq!(deck.len(), 5, "transform replaces, it does not remove");
        assert!(
            !deck.iter().any(|id| *id == "strike" || *id == "defend"),
            "every Strike and Defend is gone: {deck:?}"
        );
        // 两张**非基础牌**（`bash` / `clash`）原样留着。`bash` 同时也是改造的来源，
        // 所以"留着的那张"与"改造出来的"会重名 —— 数**个数**而不是"存在"。
        assert_eq!(
            deck.iter().filter(|id| **id == "clash").count(),
            1,
            "a non-staple card is not transformed: {deck:?}"
        );
        assert!(
            deck.iter().filter(|id| **id == "bash").count() >= 1,
            "the original bash survives (the transforms may add more): {deck:?}"
        );
    }

    /// §274：`astrolabe` / `empty_cage` —— 它们**欠着**牌组编辑，而不抢 `pending`。
    ///
    /// 这条判据钉的正是"叠在奖励屏上"的能力：拾取发生在 `Pending::Reward` 里，
    /// 拿完遗物之后那一屏必须**还在**（否则玩家会丢掉还没拿的卡牌奖励）。
    #[test]
    fn the_pickup_picks_do_not_take_over_the_screen() {
        // ---- `empty_cage`：欠 2 次"移除"。
        let mut run = ironclad();
        run.pending = Pending::Reward;
        run.push_relic("empty_cage", &TYPED_CARDS).expect("empty_cage");
        assert_eq!(run.pending(), Pending::Reward, "the screen behind must survive");
        assert_eq!(run.pickup_picks(), 2, "empty_cage owes two removals");
        assert_eq!(run.pickup_change(), Some(DeckChange::Remove));

        let before = run.deck().len();
        run.pickup_card(0, &TYPED_CARDS).expect("first removal");
        assert_eq!(run.deck().len(), before - 1);
        assert_eq!(run.pickup_picks(), 1, "one left");
        assert_eq!(run.pending(), Pending::Reward, "still not touching the screen");
        run.pickup_card(0, &TYPED_CARDS).expect("second removal");
        assert_eq!(run.deck().len(), before - 2);
        assert_eq!(run.pickup_picks(), 0, "done");
        assert_eq!(run.pickup_change(), None, "and the debt is cleared");
        assert_eq!(run.pending(), Pending::Reward, "the reward screen is still there");

        // 拒绝不消耗额度：越界的下标不许把 `pickup_picks` 吃掉。
        let mut run = ironclad();
        run.push_relic("empty_cage", &TYPED_CARDS).expect("empty_cage");
        assert_eq!(
            run.pickup_card(99, &TYPED_CARDS),
            Err(RunError::BadCard(99u8)),
            "an out-of-range pick is refused"
        );
        assert_eq!(run.pickup_picks(), 2, "a refused pick must not spend the debt");

        // ---- `astrolabe`：欠 3 次"改造并升级"，而且**改造出来的那张被升级了**。
        const POOL: [PoolCard<'static>; 4] = [
            PoolCard { id: "strike", rarity: Rarity::Basic, kind: CardKind::Attack, upgraded: Some("strike+") },
            PoolCard { id: "defend", rarity: Rarity::Basic, kind: CardKind::Skill, upgraded: Some("defend+") },
            PoolCard { id: "bash", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: Some("bash+") },
            PoolCard { id: "flex", rarity: Rarity::Common, kind: CardKind::Skill, upgraded: Some("flex+") },
        ];
        let mut run = RunState::new(7, 80, i32::MAX, &["strike", "strike", "defend", "bash", "clash"]).expect("a run");
        run.push_relic("astrolabe", &POOL).expect("astrolabe");
        assert_eq!(run.pickup_picks(), 3, "astrolabe owes three transforms");
        assert_eq!(run.pickup_change(), Some(DeckChange::TransformAndUpgrade));
        for _ in 0..3 {
            run.pickup_card(0, &POOL).expect("transform and upgrade");
        }
        assert_eq!(run.pickup_picks(), 0);
        let deck: Vec<&str> = run.deck().iter().map(RunId::as_str).collect();
        assert_eq!(deck.len(), 5, "transform keeps the count");
        // 3 张被改造过 ⇒ 牌组里现在有 **3 张升级版**（改造出来的那些）。
        // ⚠️ 不按下标断言：`pickup_card(0)` 每次都改第 0 格，改造出来的牌可能落回同一格，
        // 所以"哪三张"是随机的 —— 只数**张数**才是这条规则说的话。
        assert_eq!(
            deck.iter().filter(|id| id.ends_with('+')).count(),
            3,
            "astrolabe upgrades what it transforms: {deck:?}"
        );
    }

    /// §273：`?` 房掷出商人 ⇒ 与商店节点**同一条**进门路径（`meal_ticket` 也要付）。
    ///
    /// ⚠️ 这条判据钉的正是 §272 留下的缺口：`begin_node` 的 Unknown 分支当时只 `stock_shop`，
    /// 于是 `?`→商店 不回血。wiki 的 Planisphere 页写过 *"a ? that turns into a shop triggers
    /// both"*。
    #[test]
    fn an_unknown_room_that_becomes_a_shop_pays_the_shop_entry_relics() {
        use crate::map::NodeKind;

        fn enter_unknown_shop(mut seed: i32) -> Option<(RunState, i32)> {
            // 走到一个 `?` 房并 `begin_node`，直到掷出**商人**（约 3% ⇒ 400 个种子足够）。
            for _ in 0..4000 {
                let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
                if !walk_to(&mut run, NodeKind::Unknown) {
                    seed += 1;
                    continue;
                }
                let ok = run.begin_node(&TYPED_CARDS, &RELICS).is_ok();
                if ok && run.unknown_room() == UnknownRoom::Shop {
                    let hp = run.health();
                    return Some((run, hp));
                }
                seed += 1;
            }
            None
        }

        let Some((run, hp)) = enter_unknown_shop(0) else {
            panic!("no seed produced a merchant ? room in 4000 tries");
        };
        assert_eq!(
            run.pending(),
            Pending::Shop,
            "a merchant ? room opens the shop flow"
        );
        assert!(
            !run.shop().cards().is_empty(),
            "…and the shelf is stocked by the same `enter_shop`"
        );
        // 反面对照：没有 `meal_ticket` 时血量不动（这个 run 没这件遗物）。
        let mut plain = run;
        assert_eq!(plain.health(), hp.min(plain.health_max()), "no relic ⇒ no heal");

        // 有了 `meal_ticket`：同一个 `?` 房要多 15 血。
        let mut with_relic = None;
        let mut seed = 0;
        while seed < 4000 {
            let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
            run.push_relic("meal_ticket", &TYPED_CARDS).expect("meal_ticket");
            run.adjust_health(-30);
            if !walk_to(&mut run, NodeKind::Unknown) {
                seed += 1;
                continue;
            }
            let before = run.health();
            let ok = run.begin_node(&TYPED_CARDS, &RELICS).is_ok();
            if ok && run.unknown_room() == UnknownRoom::Shop {
                with_relic = Some((before, run.health()));
                break;
            }
            seed += 1;
        }
        let (before, after) = with_relic.expect("no merchant ? room with the relic in 4000 tries");
        assert_eq!(
            after,
            (before + 15).min(80),
            "meal_ticket must pay on a `?` room that becomes a shop, not just on a shop node"
        );

        // 而普通商店节点仍然照旧（同一个 `enter_shop` 的另一个调用方）。
        let mut run = RunState::new(7, 80, i32::MAX, &["strike"; 10]).expect("a run");
        run.push_relic("meal_ticket", &TYPED_CARDS).expect("meal_ticket");
        run.adjust_health(-30);
        let before = run.health();
        run.pending = Pending::Shop;
        run.stock_shop(&TYPED_CARDS, &RELICS).expect("stock");
        // `stock_shop` 本身**不**回血（回血在 `enter_shop` 里）—— 这条断言把"两个函数的分工"
        // 钉住：想验 `enter_shop` 就得走 `begin_node`，而不是直接调它。
        assert_eq!(run.health(), before, "stocking alone does not pay the entry heal");
    }

    /// §273：`the_courier` —— 半价之外的"买完补货"。
    #[test]
    fn the_courier_restocks_the_slot_it_sells() {
        // ---- 折扣：20%（与 `membership_card` 的 50% 相加）。
        let mut run = ironclad();
        assert_eq!(run.shop_price(100), 100);
        run.push_relic("the_courier", &TYPED_CARDS).expect("the_courier");
        assert_eq!(run.shop_price(100), 80, "the_courier: 20% off");
        run.push_relic("membership_card", &TYPED_CARDS).expect("membership_card");
        assert_eq!(run.shop_price(100), 30, "the two discounts add up (50 + 20)");

        // ---- 补货：**货架不缩水**。这才是 wiki 那句 "The Merchant restocks …" 的意思 ——
        // 它没说"一定给你另一张"（同一张回来是允许的），所以判据不钉那件事。
        let mut run = ironclad();
        run.push_relic("the_courier", &TYPED_CARDS).expect("the_courier");
        run.adjust_gold(2000);
        run.pending = Pending::Shop;
        run.enter_shop(&SHOP_CARDS, &RELICS).expect("enter the shop");
        let live = |run: &RunState| {
            run.shop()
                .cards()
                .iter()
                .filter(|offer| offer.price >= 0)
                .count()
        };
        let mut cards_on_shelf = live(&run);
        assert_eq!(cards_on_shelf, MAX_SHOP_CARDS.min(SHOP_CARDS.len()));
        for slot in 0..2 {
            buy_card_at(&mut run, slot).expect("buy a card");
            assert_eq!(
                live(&run),
                cards_on_shelf,
                "the_courier: the shelf must not shrink (slot {slot})"
            );
            cards_on_shelf = live(&run);
        }
        // 而且货架上不出现两张一样的牌（补货也不能撞上别的活着的那一格）。
        let mut ids: Vec<RunId> = run
            .shop()
            .cards()
            .iter()
            .filter(|offer| offer.price >= 0)
            .map(|offer| offer.id)
            .collect();
        let total = ids.len();
        ids.sort_unstable();
        ids.dedup();
        assert_eq!(ids.len(), total, "the shelf must not hold duplicates");

        // 反面：没有 `the_courier` 时那一格留空（`price = -1`）。
        let mut plain = ironclad();
        plain.adjust_gold(2000);
        plain.pending = Pending::Shop;
        plain.enter_shop(&SHOP_CARDS, &RELICS).expect("enter the shop");
        buy_card_at(&mut plain, 0).expect("buy the first card");
        assert_eq!(
            plain.shop().cards()[0].price,
            -1,
            "without the_courier a bought slot stays empty"
        );

        // ---- 遗物那一半：买走之后那一格也补货（池子里还有 `burning_blood` 之外的就补）。
        let mut run = ironclad();
        run.push_relic("the_courier", &TYPED_CARDS).expect("the_courier");
        run.adjust_gold(2000);
        run.pending = Pending::Shop;
        run.enter_shop(&TYPED_CARDS, &RELICS).expect("enter the shop");
        if run.shop().relics().first().is_some_and(|o| o.price >= 0) {
            buy_relic_at(&mut run, 0).expect("buy the relic");
            let slot = run.shop().relics()[0];
            // 池子只有一件遗物（`RELICS`），买走之后**没有**可补的 ⇒ 那一格必须是空的。
            // 这条"反面"很重要：补货不能凭空造货。
            assert_eq!(slot.price, -1, "an exhausted relic pool cannot restock");
        }
    }

    /// §272：`?` 房的**概率公式**（wiki 的 10 / 3 / 2，每次"没出现"加一个基础值、命中归零）。
    #[test]
    fn the_unknown_room_odds_walk_the_wikis_base_values() {
        let mut run = ironclad();
        assert_eq!(
            run.unknown_room_odds(),
            [10, 3, 2],
            "an act starts at the wiki's base chances"
        );

        // 三次都没出商店 ⇒ 商店变成 3 × 4 = 12（wiki 的例子是"四个 ? 房没商店 ⇒ 15%"）。
        let mut run = ironclad();
        run.unknown = [0, 3, 0];
        assert_eq!(run.unknown_room_odds(), [10, 12, 2], "shop: 3 × (1 + 3 misses)");
        run.unknown = [0, 4, 0];
        assert_eq!(run.unknown_room_odds()[1], 15, "…and 15 after four, as the wiki says");

        // 三条各自独立推进：怪物连续 5 次没出现 ⇒ 60%。
        run.unknown = [5, 4, 0];
        assert_eq!(run.unknown_room_odds()[0], 60, "monster: 10 × (1 + 5)");

        // `juzu_bracelet` 把怪物那条按成 0（Event 因此变成 95% 的基础档）。
        run.push_relic("juzu_bracelet", &TYPED_CARDS).expect("juzu_bracelet");
        assert_eq!(run.unknown_room_odds()[0], 0, "juzu_bracelet removes the monster band");
        assert_eq!(run.unknown_room_odds()[1], 15, "…and leaves the shop band alone");
    }

    /// §272：掷骰**真的**用了那三个数。
    ///
    /// 2000 个种子：基础概率下怪物 10%、商人 3%、宝箱 2%。区间取得很宽（±4 个点），
    /// 因为要证明的是"量级对"，不是"随机数好看"。⚠️ 这条判据的价值在于它**会**红：
    /// 把三条基础值写反、或把前缀累加写成独立掷骰，它立刻偏离。
    #[test]
    fn the_unknown_room_roll_matches_the_odds() {
        const SEEDS: i32 = 2000;
        let mut counts = [0i32; 4]; // monster, shop, treasure, event
        for seed in 0..SEEDS {
            let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
            match run.roll_unknown_room().expect("a roll") {
                UnknownRoom::Monster => counts[0] += 1,
                UnknownRoom::Shop => counts[1] += 1,
                UnknownRoom::Treasure => counts[2] += 1,
                UnknownRoom::Event => counts[3] += 1,
                UnknownRoom::Unresolved => panic!("a roll must resolve"),
            }
        }
        let per_cent = |n: i32| n * 100 / SEEDS;
        assert!(
            (6..=14).contains(&per_cent(counts[0])),
            "monster {}% is not near 10% (counts {counts:?})",
            per_cent(counts[0])
        );
        assert!(
            (1..=6).contains(&per_cent(counts[1])),
            "shop {}% is not near 3% (counts {counts:?})",
            per_cent(counts[1])
        );
        assert!(
            (0..=5).contains(&per_cent(counts[2])),
            "treasure {}% is not near 2% (counts {counts:?})",
            per_cent(counts[2])
        );
        // 事件吃掉剩下的（基础 85%）。
        assert!(
            (78..=92).contains(&per_cent(counts[3])),
            "event {}% is not near 85% (counts {counts:?})",
            per_cent(counts[3])
        );
    }

    /// §272：`tiny_chest` 每第 4 个 `?` 房是宝箱；`juzu_bracelet` 永不出现怪物。
    #[test]
    fn tiny_chest_and_juzu_bracelet_change_the_roll() {
        // ---- `tiny_chest`：四次里**必有一次**宝箱，而且是第 4 次。
        let mut run = ironclad();
        run.push_relic("tiny_chest", &TYPED_CARDS).expect("tiny_chest");
        let mut treasure_at = None;
        for index in 1..=4u8 {
            let outcome = run.roll_unknown_room().expect("a roll");
            if outcome == UnknownRoom::Treasure {
                treasure_at = Some(index);
            }
        }
        assert_eq!(
            treasure_at,
            Some(TINY_CHEST_ROOMS),
            "the 4th ? room is forced to be a treasure room"
        );
        assert_eq!(run.tiny_chest_rooms(), 0, "the counter resets after it pays");
        // 宝箱出现 ⇒ treasure 的 miss 计数归零。
        assert_eq!(run.unknown_odds()[2], 0, "a treasure resets the treasure counter");

        // 反面：没有这件遗物时计数永远是 0（不增长）。
        let mut run = ironclad();
        for _ in 0..6 {
            run.roll_unknown_room().expect("a roll");
        }
        assert_eq!(run.tiny_chest_rooms(), 0, "without the relic the counter stays put");

        // ---- `juzu_bracelet`：怪物**永不**出现，哪怕怪物计数已经堆到必然会出的地步。
        let mut run = ironclad();
        run.push_relic("juzu_bracelet", &TYPED_CARDS).expect("juzu_bracelet");
        run.unknown = [9, 0, 0]; // 没有 juzu 时这里已经 100% 怪物
        for seed in 0..200 {
            run.unknown[0] = 9;
            let outcome = run.roll_unknown_room().expect("a roll");
            assert_ne!(
                outcome, UnknownRoom::Monster,
                "seed {seed}: juzu_bracelet must keep monsters out of ? rooms"
            );
        }
    }

    /// §272：`begin_node` 的**四种结果**各走既有通道（这也是 `?` 房与内核其余部分的接线判据）。
    #[test]
    fn an_unknown_room_settles_into_the_channel_its_result_names() {
        use crate::map::NodeKind;
        // 四种结果各造一次：直接对着 `?` 房节点反复 `begin_node`，直到四种都见到。
        // 判定标准是**可观察的三件事**：pending、unknown_room()、以及商人的货架。
        let mut seen_treasure = false;
        let mut seen_shop = false;
        let mut seen_monster = false;
        let mut seen_event = false;
        for seed in 0..400 {
            let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
            if !walk_to(&mut run, NodeKind::Unknown) {
                continue;
            }
            let kind = run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the ? room");
            assert_eq!(kind, NodeKind::Unknown, "a ? room stays a ? room on the map");
            match run.unknown_room() {
                UnknownRoom::Treasure => {
                    assert_eq!(run.pending(), Pending::Chest, "a treasure opens the chest flow");
                    seen_treasure = true;
                }
                UnknownRoom::Shop => {
                    assert_eq!(run.pending(), Pending::Shop, "a merchant opens the shop flow");
                    assert!(
                        !run.shop().cards().is_empty(),
                        "…and the shelf is stocked by `begin_node` itself"
                    );
                    seen_shop = true;
                }
                UnknownRoom::Monster => {
                    assert_eq!(run.pending(), Pending::None, "a fight is the caller's business");
                    seen_monster = true;
                }
                UnknownRoom::Event => {
                    assert_eq!(run.pending(), Pending::None, "an event is the caller's business");
                    seen_event = true;
                }
                UnknownRoom::Unresolved => panic!("begin_node must resolve the room"),
            }
        }
        assert!(seen_treasure, "no seed produced a treasure ? room");
        assert!(seen_shop, "no seed produced a merchant ? room");
        assert!(seen_monster, "no seed produced a fight ? room");
        assert!(seen_event, "no seed produced an event ? room");
    }

    /// §272：换幕把三条概率（与 `tiny_chest` 的计数）归零 —— wiki："reset in between acts"。
    ///
    /// ⚠️ 这三条计数在 §272 之前**根本没有消费者**，所以"换幕归零"这条规则也一直没有实现。
    #[test]
    fn an_act_change_resets_the_unknown_room_odds() {
        let mut run = ironclad();
        run.unknown = [7, 5, 3];
        run.tiny_chest_rooms = 2;
        run.unknown_room = UnknownRoom::Monster;
        // 走到 Boss 并结算它：那是唯一会换幕的路径。
        run.node = i32::from(crate::map::BOSS_NODE);
        run.floor = crate::map::ROWS as i32 + 1;
        let act = run.act();
        run.mark_boss_beaten();
        assert_ne!(run.act(), act, "the boss advances the act");
        assert_eq!(run.unknown_odds(), [0, 0, 0], "the three counters reset");
        assert_eq!(run.tiny_chest_rooms(), 0, "the tiny chest counter resets too");
        assert_eq!(
            run.unknown_room(),
            UnknownRoom::Unresolved,
            "the resolved room is not carried into the next act"
        );
        assert_eq!(run.unknown_room_odds(), [10, 3, 2], "back to the base chances");
    }

    /// §271：**节点类** —— 三个 `begin_node` 分支各管一件事。
    ///
    /// 走的是 `walk_to`（与 §268 那条"节点都能结算"的判据同一招）：它把游标真的挪到一个
    /// 指定类型的节点上，所以 `begin_node` 里的分支**真的**被执行到。
    #[test]
    fn the_node_relics_pay_on_the_right_kind_of_room() {
        // ---- `meal_ticket`：进商店回 15（**进门就付**，不是买了东西才付）。
        let mut run = ironclad();
        run.push_relic("meal_ticket", &TYPED_CARDS).expect("meal_ticket");
        if walk_to(&mut run, crate::map::NodeKind::Shop) {
            run.adjust_health(-30);
            let hp = run.health();
            run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the shop");
            assert_eq!(run.pending(), Pending::Shop);
            assert_eq!(run.health(), hp + 15, "meal_ticket: +15 on entering a shop");
        }

        // 反面：同一件遗物进**别的**房间不回血。
        let mut run = ironclad();
        run.push_relic("meal_ticket", &TYPED_CARDS).expect("meal_ticket");
        if walk_to(&mut run, crate::map::NodeKind::Rest) {
            run.adjust_health(-30);
            let hp = run.health();
            run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the campfire");
            assert_eq!(run.health(), hp, "meal_ticket must not pay on a rest site");
        }

        // ---- `ssserpent_head`：进 `?` 房 +50 金。
        let mut run = ironclad();
        run.push_relic("ssserpent_head", &TYPED_CARDS).expect("ssserpent_head");
        if walk_to(&mut run, crate::map::NodeKind::Unknown) {
            let gold = run.gold();
            let kind = run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the ? room");
            assert_eq!(kind, crate::map::NodeKind::Unknown);
            assert_eq!(run.gold(), gold + 50, "ssserpent_head: +50 per ? room");
        }

        // 反面：没有这件遗物时一分钱不多。
        let mut run = ironclad();
        if walk_to(&mut run, crate::map::NodeKind::Unknown) {
            let gold = run.gold();
            run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the ? room");
            assert_eq!(run.gold(), gold, "no ssserpent_head ⇒ no gold");
        }

        // ---- `ancient_tea_set`：进篝火 ⇒ **下一场**战斗开战 +2 能量；打完一场就没了。
        let mut run = ironclad();
        run.push_relic("ancient_tea_set", &TYPED_CARDS).expect("ancient_tea_set");
        assert_eq!(
            run.combat_bonus_for(FightKind::Normal).status_count,
            0,
            "before any rest site there is nothing pending"
        );
        if walk_to(&mut run, crate::map::NodeKind::Rest) {
            run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the campfire");
            assert!(run.tea_set_pending(), "a rest site owes the next fight 2 energy");
            let bonus = run.combat_bonus_for(FightKind::Normal);
            assert_eq!(bonus.status_count, 1, "the pending status is in the bonus");
            let entry = bonus.statuses[0].expect("an entry");
            assert_eq!(entry.id, "standard.ancient_tea_set", "its own status, not lantern's");
            assert_eq!(entry.stacks, 1, "one stack of a +2 status");

            // 兑现：清掉之后**下一场**就不该再有它（"the next combat" 只是一场）。
            run.clear_tea_set();
            assert_eq!(
                run.combat_bonus_for(FightKind::Normal).status_count,
                0,
                "the charge is for one combat only"
            );
        }

        // 反面：没有这件遗物时进篝火不欠任何东西。
        let mut run = ironclad();
        if walk_to(&mut run, crate::map::NodeKind::Rest) {
            run.begin_node(&TYPED_CARDS, &RELICS).expect("enter the campfire");
            assert!(!run.tea_set_pending(), "no relic ⇒ nothing pending");
            assert_eq!(run.combat_bonus_for(FightKind::Normal).status_count, 0);
        }
    }

    /// §271：**药水类** —— `sozu` 拦药水（两个入口），`toy_ornithopter` 的 5 由 wasm 兑现
    /// （这里只钉运行层那一半：遗物表里的数字）。
    #[test]
    fn sozu_refuses_potions_at_both_doors() {
        // ---- 门 1：`push_potion` 拒绝（事件/调试入口递过来的也收不了）。
        let mut run = ironclad();
        run.push_relic("sozu", &TYPED_CARDS).expect("sozu");
        let before = run;
        assert_eq!(
            run.push_potion("fire_potion"),
            Err(RunError::PotionGainBlocked),
            "sozu: you can no longer obtain potions"
        );
        assert_eq!(run.potions().len(), 0, "nothing entered the belt");
        assert!(run == before, "a refused potion must not change the run");

        // ---- 门 2：奖励屏上**根本不该出现**那一格（不发，而不是"发了再拒绝"）。
        // 用一条固定种子把"40% 掉率"的随机流走满：无论掷骰结果如何，`sozu` 之下都没有药水。
        for seed in 0..24 {
            let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
            run.push_relic("sozu", &TYPED_CARDS).expect("sozu");
            run.roll_reward(&TYPED_CARDS, &POTIONS, &RELICS, FightKind::Normal)
                .expect("a reward");
            assert_eq!(
                run.reward().potion.as_str(),
                "",
                "seed {seed}: sozu must not offer a potion"
            );
        }
        // 反面：没有 `sozu` 时 24 个种子里**至少有一个**掉药水（否则上一条什么也没证明）。
        let mut any = false;
        for seed in 0..24 {
            let mut run = RunState::new(seed, 80, i32::MAX, &["strike"; 10]).expect("a run");
            run.roll_reward(&TYPED_CARDS, &POTIONS, &RELICS, FightKind::Normal)
                .expect("a reward");
            if !run.reward().potion.as_str().is_empty() {
                any = true;
            }
        }
        assert!(any, "the control must actually drop a potion somewhere");

        // ---- `sozu` 的另一半：每回合 +1 能量的载体。
        let mut run = ironclad();
        run.push_relic("sozu", &TYPED_CARDS).expect("sozu");
        let bonus = run.combat_bonus_for(FightKind::Normal);
        assert_eq!(bonus.status_count, 1, "sozu's energy half is granted");
        assert_eq!(
            bonus.statuses[0].expect("an entry").id,
            "standard.sozu",
            "the carrier is sozu's own status"
        );
    }

    /// §271：`toy_ornithopter` 的参数只存在于遗物表里（wasm 通过
    /// `RunState::relic_effect` 读它，不在 wasm 里写第二个 5）。
    #[test]
    fn the_potion_relics_carry_their_own_numbers() {
        use crate::state::RelicEffect;
        let mut run = ironclad();
        run.push_relic("toy_ornithopter", &TYPED_CARDS).expect("toy_ornithopter");
        assert_eq!(
            RunState::relic_effect("toy_ornithopter"),
            Some(RelicEffect::PotionUseHeal(5)),
            "the heal amount lives in the relic table, not in the wasm layer"
        );
        // 反面：不是"任何遗物都给 +5"。
        assert_eq!(RunState::relic_effect("burning_blood"), Some(RelicEffect::EndOfCombatHeal(6)));
    }

    /// §270：**加牌类** —— 所有落点都在 `push_card` 一处。
    #[test]
    fn the_add_card_relics_fire_at_the_one_add_point() {
        // ---- `omamori`：挡掉接下来 2 个**诅咒**，第 3 个进牌组；非诅咒完全不挡。
        let mut run = ironclad();
        run.push_relic("omamori", &TYPED_CARDS).expect("omamori");
        assert_eq!(run.omamori_charges(), OMAMORI_CHARGES, "grant gives 2");

        let curse = PoolCard { kind: CardKind::Curse, ..PoolCard::plain("injury") };
        let deck_before = run.deck().len();
        run.push_card(curse).expect("a negated curse is not an error");
        assert_eq!(run.deck().len(), deck_before, "the first curse is negated");
        assert_eq!(run.omamori_charges(), 1);
        run.push_card(curse).expect("the second is negated too");
        assert_eq!(run.deck().len(), deck_before, "still nothing added");
        assert_eq!(run.omamori_charges(), 0, "both charges spent");
        run.push_card(curse).expect("the third arrives");
        assert_eq!(run.deck().len(), deck_before + 1, "out of charges ⇒ it lands");

        // 非诅咒：一次都不能被挡（这条是反面 —— 没有它，`omamori` 会挡住整副牌）。
        let mut run = ironclad();
        run.push_relic("omamori", &TYPED_CARDS).expect("omamori");
        let before = run.deck().len();
        run.push_card(PoolCard { kind: CardKind::Attack, ..PoolCard::plain("anger") })
            .expect("an attack");
        assert_eq!(run.deck().len(), before + 1, "attacks are never negated");
        assert_eq!(run.omamori_charges(), OMAMORI_CHARGES, "…and cost no charge");

        // ---- `darkstone_periapt`：诅咒 ⇒ 上限 +6。**被 `omamori` 挡掉的那个不算**（顺序即规则）。
        let mut run = ironclad();
        run.push_relic("darkstone_periapt", &TYPED_CARDS).expect("periapt");
        let max_before = run.health_max();
        run.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain("injury") })
            .expect("curse");
        assert_eq!(run.health_max(), max_before + 6, "a curse raises the max by 6");
        run.push_card(PoolCard { kind: CardKind::Attack, ..PoolCard::plain("anger") })
            .expect("attack");
        assert_eq!(run.health_max(), max_before + 6, "a non-curse does not");

        let mut both = ironclad();
        both.push_relic("omamori", &TYPED_CARDS).expect("omamori");
        both.push_relic("darkstone_periapt", &TYPED_CARDS).expect("periapt");
        let max_before = both.health_max();
        both.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain("injury") })
            .expect("negated curse");
        assert_eq!(both.deck().len(), 10, "omamori took it");
        assert_eq!(
            both.health_max(),
            max_before,
            "a **negated** curse is not 'obtained' ⇒ darkstone must stay quiet"
        );

        // ---- 三个蛋：类型对上就换成 `+` 行，对不上原样。
        for (relic, kind, other) in [
            ("molten_egg", CardKind::Attack, CardKind::Skill),
            ("toxic_egg", CardKind::Skill, CardKind::Attack),
            ("frozen_egg", CardKind::Power, CardKind::Attack),
        ] {
            let mut run = ironclad();
            run.push_relic(relic, &TYPED_CARDS).expect("an egg");
            let matching = PoolCard {
                id: "bash",
                rarity: Rarity::Common,
                kind,
                upgraded: Some("bash+"),
            };
            let before = run.deck().len();
            run.push_card(matching).expect("matching card");
            assert_eq!(
                run.deck()[before].as_str(),
                "bash+",
                "{relic} must upgrade a card of its own type"
            );

            let wrong = PoolCard {
                id: "bash",
                rarity: Rarity::Common,
                kind: other,
                upgraded: Some("bash+"),
            };
            run.push_card(wrong).expect("other type");
            assert_eq!(
                run.deck()[before + 1].as_str(),
                "bash",
                "{relic} must NOT touch another type"
            );
        }

        // 没有 `+` 行时保持原样（内容的事，不报错）。
        let mut run = ironclad();
        run.push_relic("molten_egg", &TYPED_CARDS).expect("egg");
        let before = run.deck().len();
        run.push_card(PoolCard {
            id: "bash",
            rarity: Rarity::Common,
            kind: CardKind::Attack,
            upgraded: None,
        })
        .expect("no `+` row");
        assert_eq!(run.deck()[before].as_str(), "bash");

        // ---- `ceramic_fish`：加任何牌 +9 金币。
        let mut run = ironclad();
        run.push_relic("ceramic_fish", &TYPED_CARDS).expect("fish");
        let gold_before = run.gold();
        run.push_card(PoolCard { kind: CardKind::Skill, ..PoolCard::plain("defend") })
            .expect("a skill");
        assert_eq!(run.gold(), gold_before + 9, "ceramic_fish: +9 per card");

        // `omamori` 挡掉的那一张**不给钱**（没进牌组 ⇒ 不算"add a card"）。
        let mut both = ironclad();
        both.push_relic("omamori", &TYPED_CARDS).expect("omamori");
        both.push_relic("ceramic_fish", &TYPED_CARDS).expect("fish");
        let gold_before = both.gold();
        both.push_card(PoolCard { kind: CardKind::Curse, ..PoolCard::plain("injury") })
            .expect("negated");
        assert_eq!(both.gold(), gold_before, "a negated curse pays no gold");
    }

    /// §270：**金币/商店类** —— 四个落点：`adjust_gold` / `enter_node` / 价格 / 删牌服务。
    #[test]
    fn the_gold_and_shop_relics_change_only_their_own_number() {
        // ---- `ectoplasm`：得金币变 0（**花出去**不受影响），且每回合 +1 能量的载体照旧。
        let mut run = ironclad();
        run.push_relic("ectoplasm", &TYPED_CARDS).expect("ectoplasm");
        let gold = run.gold();
        run.adjust_gold(100);
        assert_eq!(run.gold(), gold, "ectoplasm: you can no longer gain Gold");
        run.adjust_gold(-gold.min(10));
        assert!(run.gold() < gold, "spending still works");
        let bonus = run.combat_bonus_for(FightKind::Normal);
        assert_eq!(
            bonus.status_count, 1,
            "ectoplasm's second half (the energy carrier) must still be granted"
        );
        // ⚠️ 逐条比 **id**，不只数个数：§186 / §260 都栽在"抄了邻居的状态 id"上，
        // 而"有 1 条状态"对那条错完全无感。
        assert_eq!(
            bonus.statuses[0].expect("an entry").id,
            "standard.ectoplasm",
            "the carrier is ectoplasm's own status"
        );

        // ---- `bloody_idol`：**真的**得到金币才回 5 血。
        let mut run = ironclad();
        run.push_relic("bloody_idol", &TYPED_CARDS).expect("idol");
        run.adjust_health(-10);
        let hp = run.health();
        run.adjust_gold(12);
        assert_eq!(run.health(), hp + 5, "bloody_idol: +5 HP per gold gain");
        run.adjust_gold(-5);
        assert_eq!(run.health(), hp + 5, "spending heals nothing");

        // 与 `ectoplasm` 一起：金币没涨 ⇒ **不回血**（"gained" 判的是实际差，不是 `delta > 0`）。
        let mut both = ironclad();
        both.push_relic("bloody_idol", &TYPED_CARDS).expect("idol");
        both.push_relic("ectoplasm", &TYPED_CARDS).expect("ectoplasm");
        both.adjust_health(-10);
        let hp = both.health();
        both.adjust_gold(12);
        assert_eq!(
            both.health(),
            hp,
            "ectoplasm blocked the gold, so there was nothing to heal from"
        );

        // ---- `maw_bank`：爬一层 +12；在商店花过钱之后失效。
        let mut run = ironclad();
        run.push_relic("maw_bank", &TYPED_CARDS).expect("maw_bank");
        let gold = run.gold();
        let target = run.reachable().get(0).expect("a floor-1 node");
        run.enter_node(target).expect("climb");
        assert_eq!(run.gold(), gold + 12, "maw_bank: +12 per floor climbed");
        // **一个节点结算完才能走下一个** —— 这条判据只需要"楼层涨了"，所以直接标记结算，
        // 而不是真的打一场（那是 `ACT1_SLICE` 的事）。
        run.mark_resolved();
        let gold = run.gold();
        run.enter_node(run.reachable().get(0).expect("the next node"))
            .expect("climb again");
        assert_eq!(run.gold(), gold + 12, "…and again");

        // 没有这件遗物时一分钱都不多。
        let mut plain = ironclad();
        let gold = plain.gold();
        plain
            .enter_node(plain.reachable().get(0).expect("a node"))
            .expect("climb");
        assert_eq!(plain.gold(), gold, "no maw_bank ⇒ no climb gold");

        // ---- `smiling_mask`：删牌服务固定 50（`removed_cards` 的 +25/次 对它失效）。
        let mut run = ironclad();
        assert_eq!(run.remove_card_price(), SHOP_REMOVE_BASE, "the first removal");
        run.push_relic("smiling_mask", &TYPED_CARDS).expect("mask");
        assert_eq!(
            run.remove_card_price(),
            SHOP_REMOVE_FLAT,
            "smiling_mask: always 50"
        );

        // ---- `membership_card`：所有商品半价；**显示价与实付价是同一个函数**。
        let mut run = ironclad();
        assert_eq!(run.shop_price(100), 100, "no discount without the relic");
        run.push_relic("membership_card", &TYPED_CARDS).expect("membership_card");
        assert_eq!(run.shop_price(100), 50, "membership_card: 50% off");
        // ⚠️ `remove_card_price()` **本身已经**含折扣（它内部就调 `shop_price`），所以这里不能再
        // 套一层 —— 第一版套了，得到 18 而不是 37（"半价的半价"）。
        assert_eq!(
            run.remove_card_price(),
            SHOP_REMOVE_BASE / 2,
            "the removal service is a product too"
        );
    }

    /// §270：一次**真的**购买 —— 折扣后的钱扣掉、`maw_bank` 从此失效。
    ///
    /// 不走地图：判据住在本模块里，可以直接摆出"站在商店里"这个局面（`stock_shop` 是私有的，
    /// `A10` 那条删牌判据也用同一招）。⚠️ 不用"随机走到一个商店"—— 那让判据依赖种子。
    #[test]
    fn a_discounted_purchase_charges_the_discounted_price() {
        let mut run = ironclad();
        run.push_relic("membership_card", &TYPED_CARDS).expect("membership_card");
        run.push_relic("maw_bank", &TYPED_CARDS).expect("maw_bank");
        run.adjust_gold(2000);
        run.pending = Pending::Shop;
        run.stock_shop(&TYPED_CARDS, &RELICS).expect("stock the shop");
        assert!(!run.maw_bank_broken(), "nothing spent yet");

        let offer = run.shop().cards()[0];
        assert!(offer.price > 0, "the shelf is stocked");
        let gold = run.gold();
        buy_card_at(&mut run, 0).expect("buy the first card");
        assert_eq!(
            run.gold(),
            gold - run.shop_price(offer.price),
            "the price charged is `shop_price`, not the shelf price"
        );
        assert!(
            run.shop_price(offer.price) < offer.price,
            "with Membership Card the charge must be **less** than the shelf price"
        );
        assert!(run.maw_bank_broken(), "spending at a shop breaks maw_bank");

        // `maw_bank` 失效之后爬层不再给钱。
        let gold = run.gold();
        let target = run.reachable().get(0);
        if let Some(node) = target {
            // 商店还没结算 ⇒ 不能走。先 `leave`（商店的结算动作），再爬一层。
            run.leave().expect("leave the shop");
            if run.enter_node(node).is_ok() {
                assert_eq!(run.gold(), gold, "a broken maw_bank pays nothing");
            }
        }
    }

    /// §269：**战斗类型层** —— 同一个遗物在不同 `FightKind` 下给出不同的加成。
    #[test]
    fn the_kind_gated_relics_only_fire_in_their_own_kinds() {
        use crate::state::{FightKind, KindMask};

        // ---- Sling of Courage：**只有**精英战 +2 力量。
        let mut run = ironclad();
        run.push_relic("sling_of_courage", &TYPED_CARDS).expect("sling");
        for (kind, want) in [
            (FightKind::Normal, 0),
            (FightKind::Elite, 1),
            (FightKind::Boss, 0),
        ] {
            let bonus = run.combat_bonus_for(kind);
            assert_eq!(bonus.status_count, want, "sling_of_courage in {kind:?}");
            if want == 1 {
                let entry = bonus.statuses[0].expect("entry");
                assert_eq!(entry.id, "standard.strength");
                assert_eq!(entry.stacks, 2, "sling_of_courage: +2 Strength");
            }
        }

        // ---- Slaver's Collar：Boss 与精英战各 +1 能量的载体；普通战没有。
        let mut run = ironclad();
        run.push_relic("slavers_collar", &TYPED_CARDS).expect("collar");
        for (kind, want) in [
            (FightKind::Normal, 0),
            (FightKind::Elite, 1),
            (FightKind::Boss, 1),
        ] {
            let bonus = run.combat_bonus_for(kind);
            assert_eq!(bonus.status_count, want, "slavers_collar in {kind:?}");
            if want == 1 {
                assert_eq!(bonus.statuses[0].expect("entry").id, "standard.slavers_collar");
            }
        }

        // ---- Pantograph：**只有** Boss 战开战回 25。
        let mut run = ironclad();
        run.push_relic("pantograph", &TYPED_CARDS).expect("pantograph");
        assert_eq!(run.combat_bonus_for(FightKind::Normal).start_heal, 0);
        assert_eq!(run.combat_bonus_for(FightKind::Elite).start_heal, 0);
        assert_eq!(run.combat_bonus_for(FightKind::Boss).start_heal, 25);

        // ---- Preserved Insect：**只有**精英战的敌人血量 -25%。
        let mut run = ironclad();
        run.push_relic("preserved_insect", &TYPED_CARDS).expect("insect");
        assert_eq!(run.enemy_health_bonus_percent(FightKind::Normal), 0);
        assert_eq!(
            run.enemy_health_bonus_percent(FightKind::Elite),
            -25,
            "preserved_insect: elite enemies lose 25% HP"
        );
        assert_eq!(run.enemy_health_bonus_percent(FightKind::Boss), 0);

        // 与升阶的 +75% 叠加（同一条通道 ⇒ 加法）：A7 对精英给 +75，于是净 +50。
        let mut ascended = RunState::new_with_ascension(
            7,
            80,
            i32::MAX,
            &["strike"; 10],
            A_ELITE_HP,
        )
        .expect("an ascended run");
        ascended.push_relic("preserved_insect", &TYPED_CARDS).expect("insect");
        // ⚠️ 本内核的升阶血量增量是 `ASCENDED_ENEMY_HEALTH_PERCENT = 10`（不是 wiki 的 +75% 那套
        // 分数），所以 A8 精英是 +10，叠加 `preserved_insect` 的 -25 得 **-15**。
        // 断言写成"两半相加"而不是硬编码某个数：`10 + (-25)`。
        assert_eq!(
            ascended.enemy_health_bonus_percent(FightKind::Elite),
            ASCENDED_ENEMY_HEALTH_PERCENT - 25,
            "the ascension bonus and the relic share one channel"
        );
        assert!(
            KindMask::ELITE.covers(FightKind::Elite) && !KindMask::ELITE.covers(FightKind::Boss),
            "the mask itself"
        );
    }

    /// §269：**奖励层** —— 卡数 / 药水 / 额外遗物。
    #[test]
    fn the_reward_layer_relics_change_the_payout() {
        use crate::state::{FightKind, BASE_REWARD_CARDS, MAX_REWARD_CARDS};

        // 卡数：基线 3。
        let run = ironclad();
        assert_eq!(run.reward_card_count(FightKind::Normal), 3, "baseline");
        // 存储容量（4）与"默认给几张"（3）是**两个**常量；这里钉的是后者。
        assert_eq!(
            run.reward_card_count(FightKind::Normal),
            BASE_REWARD_CARDS + 0,
            "the default screen is BASE_REWARD_CARDS"
        );
        assert!(BASE_REWARD_CARDS < MAX_REWARD_CARDS, "storage must have room for +1");

        // Question Card：任何战斗 +1。
        let mut run = ironclad();
        run.push_relic("question_card", &TYPED_CARDS).expect("question_card");
        assert_eq!(run.reward_card_count(FightKind::Normal), 4, "question_card: +1");
        assert_eq!(run.reward_card_count(FightKind::Boss), 4, "…and on a boss too");

        // Prayer Wheel：**只有**普通怪 +1。
        let mut run = ironclad();
        run.push_relic("prayer_wheel", &TYPED_CARDS).expect("prayer_wheel");
        assert_eq!(run.reward_card_count(FightKind::Normal), 4, "prayer_wheel: normal +1");
        assert_eq!(run.reward_card_count(FightKind::Elite), 3, "…and not on an elite");

        // Busted Crown：-2（钳到下限 1）+ 每回合 +1 能量的载体。
        let mut run = ironclad();
        run.push_relic("busted_crown", &TYPED_CARDS).expect("busted_crown");
        assert_eq!(run.reward_card_count(FightKind::Normal), 1, "busted_crown: 3 - 2");
        assert_eq!(
            run.combat_bonus_for(FightKind::Normal).status_count,
            1,
            "busted_crown also grants its energy carrier"
        );
        assert_eq!(
            run.combat_bonus_for(FightKind::Normal).statuses[0].expect("entry").id,
            "standard.busted_crown"
        );

        // 两件一起：+1 -2 = 2。
        let mut run = ironclad();
        run.push_relic("question_card", &TYPED_CARDS).expect("q");
        run.push_relic("busted_crown", &TYPED_CARDS).expect("b");
        assert_eq!(run.reward_card_count(FightKind::Normal), 2, "+1 and -2 make 2");
    }

    /// §268：零基建档收尾的接线（5 条载体 + `black_blood` 的战后回血）。
    #[test]
    fn the_zero_infrastructure_tail_wires_its_carriers() {
        let carrier = [
            ("self_forming_clay", "standard.self_forming_clay"),
            ("bird_faced_urn", "standard.bird_faced_urn"),
            ("runic_pyramid", "standard.runic_pyramid"),
            ("lizard_tail", "standard.lizard_tail"),
            ("unceasing_top", "standard.unceasing_top"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic, &TYPED_CARDS).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
        }

        // `black_blood` 没有载体：它的效果是战后的 `EndOfCombatHeal(12)`。
        let mut run = ironclad();
        run.push_relic("black_blood", &TYPED_CARDS).expect("black_blood");
        run.adjust_health(-30);
        let before = run.health();
        assert_eq!(run.end_of_combat(), Ok(12), "Black Blood: heals 12 after a fight");
        assert_eq!(run.health(), before + 12);
    }

    /// §267：零基建批次的接线（13 条状态 + 5 条"直接挂那条状态"）。
    #[test]
    fn the_zero_infrastructure_batch_wires_the_right_carrier() {
        let carrier = [
            ("ring_of_the_snake", "standard.ring_of_the_snake"),
            ("ring_of_the_serpent", "standard.ring_of_the_serpent"),
            ("philosophers_stone", "standard.philosophers_stone"),
            ("happy_flower", "standard.happy_flower"),
            ("art_of_war", "standard.art_of_war"),
            ("brimstone", "standard.brimstone"),
            ("mark_of_pain", "standard.mark_of_pain"),
            ("mutagenic_strength", "standard.mutagenic_strength"),
            ("centennial_puzzle", "standard.centennial_puzzle"),
            ("runic_cube", "standard.runic_cube"),
            ("charons_ashes", "standard.charons_ashes"),
            ("duality", "standard.duality"),
            ("akabeko", "standard.akabeko"),
            // 开战载体：直接挂那条状态。
            ("clockwork_souvenir", "standard.artifact"),
            ("gremlin_visage", "standard.weak"),
            ("fossilized_helix", "standard.buffer"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic, &TYPED_CARDS).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
        }

        // `red_mask` 走**敌人**那张表。
        let mut run = ironclad();
        run.push_relic("red_mask", &TYPED_CARDS).expect("red_mask");
        let bonus = run.combat_bonus();
        assert_eq!(bonus.status_count, 0, "red_mask: nothing for the hero");
        assert_eq!(bonus.enemy_status_count, 1, "red_mask: one enemy status");
        assert_eq!(
            bonus.enemy_statuses[0].expect("entry").id,
            "standard.weak",
            "red_mask applies Weak to the enemies"
        );

        // `mango` 拾取即 +14 Max HP。
        let before = ironclad().health_max();
        let mut after = ironclad();
        after.push_relic("mango", &TYPED_CARDS).expect("mango");
        assert_eq!(after.health_max(), before + 14, "mango: +14 max HP on pickup");
    }

    /// §266：两件的接线。
    #[test]
    fn the_conditional_modifier_relics_wire_their_own_carrier() {
        let carrier = [
            ("red_skull", "standard.red_skull"),
            ("odd_mushroom", "standard.odd_mushroom"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic, &TYPED_CARDS).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
            assert_eq!(entry.stacks, 1, "{relic}: one stack");
        }
    }

    /// §265：四件的接线（三件挂英雄、一件挂敌人）。
    #[test]
    fn the_status_application_relics_wire_their_own_carrier() {
        let carrier = [
            ("snecko_skull", "standard.snecko_skull"),
            ("ginger", "standard.ginger"),
            ("turnip", "standard.turnip"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic, &TYPED_CARDS).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
            assert_eq!(entry.stacks, 1, "{relic}: one stack");
            assert_eq!(bonus.enemy_status_count, 0, "{relic}: nothing for the enemies");
        }

        // `twisted_funnel` 走**敌人**那张表（§224）。
        let mut run = ironclad();
        run.push_relic("twisted_funnel", &TYPED_CARDS).expect("twisted_funnel");
        let bonus = run.combat_bonus();
        assert_eq!(bonus.status_count, 0, "twisted_funnel: nothing for the hero");
        assert_eq!(bonus.enemy_status_count, 1, "twisted_funnel: one enemy status");
        let entry = bonus.enemy_statuses[0].expect("an entry");
        assert_eq!(entry.id, "standard.poison", "Poison for the enemies");
        assert_eq!(entry.stacks, 4, "4 stacks");
    }

    /// §264：三件的接线。
    #[test]
    fn the_status_parameter_relics_wire_their_own_carrier() {
        let carrier = [
            ("paper_phrog", "standard.paper_phrog"),
            ("paper_krane", "standard.paper_krane"),
            ("champion_belt", "standard.champion_belt"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic, &TYPED_CARDS).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
            assert_eq!(entry.stacks, 1, "{relic}: one stack");
        }
    }

    /// §263：五件（敌人死亡类 + 伤害改写类）的**接线**。
    #[test]
    fn the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier() {
        let carrier = [
            ("gremlin_horn", "standard.gremlin_horn"),
            ("the_specimen", "standard.the_specimen"),
            ("the_boot", "standard.the_boot"),
            ("torii", "standard.torii"),
            ("tungsten_rod", "standard.tungsten_rod"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic, &TYPED_CARDS).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
            assert_eq!(entry.stacks, 1, "{relic}: one stack");
        }
    }

    /// §262：七件"每第 N 张某类型牌"的**接线**。
    ///
    /// 逐条比状态 id：这七件全是 1 层、全走 `StartCombatStatus`，所以"抄了邻居的状态 id"
    /// 只有逐条比才看得出来（这个仓库已经踩过两次，§186 / §260）。
    #[test]
    fn the_every_nth_card_relics_wire_their_own_carrier() {
        let carrier = [
            ("kunai", "standard.kunai"),
            ("shuriken", "standard.shuriken"),
            ("ornamental_fan", "standard.ornamental_fan"),
            ("letter_opener", "standard.letter_opener"),
            ("nunchaku", "standard.nunchaku"),
            ("ink_bottle", "standard.ink_bottle"),
            ("pen_nib", "standard.pen_nib"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic, &TYPED_CARDS).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
            assert_eq!(entry.stacks, 1, "{relic}: one stack");
        }
    }

    /// §261：五件"战斗开始类"遗物的**接线**。
    ///
    /// 逐条比，而且 `calipers` 比的是**15 层**、`du_vu_doll` 比的是它落在 **per_curse 那张表**
    /// 上（不是 `statuses`）。抄错数字、抄错表，只有逐条比才看得出来（§186/§260 都踩过）。
    #[test]
    fn the_five_combat_start_relics_wire_their_own_carrier() {
        // (遗物, 状态 id, 层数)
        let carrier = [
            ("lantern", "standard.lantern", 1),
            ("bag_of_preparation", "standard.bag_of_preparation", 1),
            ("ice_cream", "standard.ice_cream", 1),
            ("calipers", "standard.calipers", 15),
        ];
        for (relic, status_id, stacks) in carrier {
            let mut run = ironclad();
            run.push_relic(relic, &TYPED_CARDS).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
            assert_eq!(entry.stacks, stacks, "{relic}: the stacks are the wiki's number");
            assert_eq!(bonus.per_curse_status_count, 0, "{relic}: not a per-curse relic");
        }

        // `du_vu_doll` 落在**另一张表**上：层数是"每张诅咒多少"，不是总数。
        let mut run = ironclad();
        run.push_relic("du_vu_doll", &TYPED_CARDS).expect("du_vu_doll");
        let bonus = run.combat_bonus();
        assert_eq!(bonus.status_count, 0, "du_vu_doll has no fixed-stack status");
        assert_eq!(bonus.per_curse_status_count, 1, "du_vu_doll uses the per-curse table");
        let entry = bonus.per_curse_statuses[0].expect("an entry");
        assert_eq!(entry.id, "standard.strength", "du_vu_doll grants Strength");
        assert_eq!(entry.stacks, 1, "1 Strength per Curse");
        assert!(!bonus.is_empty(), "a per-curse relic is not an empty bonus");
    }

    /// §260：八件遗物的**接线** —— 每件都必须把**它自己那条**状态挂到英雄身上。
    ///
    /// 一条表一个断言（不是"至少有一个"）：`StartCombatStatus` 的参数写错（抄了邻居的状态 id）
    /// 只有逐条比才看得出来，而抄邻居在这个仓库里已经发生过不止一次（§186）。
    #[test]
    fn the_eight_turn_shaped_relics_wire_their_own_status() {
        let expectations = [
            ("orichalcum", "standard.orichalcum"),
            ("mercury_hourglass", "standard.mercury_hourglass"),
            ("horn_cleat", "standard.horn_cleat"),
            ("captains_wheel", "standard.captains_wheel"),
            ("stone_calendar", "standard.stone_calendar"),
            ("cloak_clasp", "standard.cloak_clasp"),
            ("incense_burner", "standard.incense_burner"),
            ("pocketwatch", "standard.pocketwatch"),
        ];
        for (relic, status_id) in expectations {
            let mut run = ironclad();
            run.push_relic(relic, &TYPED_CARDS).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: exactly one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: wires its own status");
            assert_eq!(entry.stacks, 1, "{relic}: one stack");
            assert_eq!(bonus.block, 0, "{relic}: no start-of-combat Block");
        }
    }

    // ---- settling a node ---------------------------------------------------------------------

    /// Walk the cursor to some node of `want`, breadth-first over the map's upward edges.
    ///
    /// A test that wants to be *in* a shop has to actually walk there: `enter_node` only accepts
    /// edges, and the map's kinds are the generator's. This also proves the map is traversable to
    /// every kind a test needs.
    fn walk_to(run: &mut RunState, want: NodeKind) -> bool {
        const CAP: usize = 128;
        let n = run.map().node_count();
        assert!(n < CAP);
        let mut seen = [false; CAP];
        let mut parent = [usize::MAX; CAP];
        let mut queue = [0u8; CAP];
        let mut head = 0usize;
        let mut tail = 0usize;
        // Start where the cursor is; a fresh run has none, so start at floor 1.
        let cursor = run.node();
        if cursor >= 0 {
            seen[cursor as usize] = true;
            queue[tail] = cursor as u8;
            tail += 1;
        } else {
            for (index, is_seen) in seen.iter_mut().enumerate().take(n) {
                let (row, _) = run.map().locate(index as u8).unwrap();
                if row == 0 {
                    *is_seen = true;
                    queue[tail] = index as u8;
                    tail += 1;
                }
            }
        }
        let mut target = usize::MAX;
        while head < tail {
            let current = queue[head] as usize;
            head += 1;
            let (row, local) = run.map().locate(current as u8).unwrap();
            let node = run.map().rows()[row].nodes()[local];
            if node.kind == want {
                target = current;
                break;
            }
            for &edge in node.out_targets() {
                let next = run.map().global_of(row + 1, edge as usize).unwrap() as usize;
                if !seen[next] {
                    seen[next] = true;
                    parent[next] = current;
                    queue[tail] = next as u8;
                    tail += 1;
                }
            }
        }
        if target == usize::MAX {
            return false;
        }
        let mut path = [0u8; CAP];
        let mut len = 0usize;
        let mut at = target;
        while parent[at] != usize::MAX {
            path[len] = at as u8;
            len += 1;
            at = parent[at];
        }
        path[len] = at as u8;
        len += 1;
        // The node the cursor is on must be settled before the first hop (the new rule).
        if cursor >= 0 {
            run.mark_resolved();
        }
        for step in (0..len).rev() {
            // The last element is the seed, and the seed may be the node we are standing on --
            // entering that again is not an edge, so it is skipped.
            if cursor >= 0 && step == len - 1 {
                continue;
            }
            run.mark_resolved();
            run.enter_node(path[step]).unwrap();
        }
        true
    }

    // Seven, like the content after the three upgraded rows were added: a pool smaller than
    // MAX_SHOP_CARDS would leave the cap untested (the shop shows min(pool, 5)).
    const CARDS: [&str; 7] = [
        "strike", "defend", "bash", "slimed", "strike+", "defend+", "bash+",
    ];
    const RELICS: [PoolRelic<'static>; 1] = [PoolRelic {
        id: "burning_blood",
        rarity: Rarity::Common,
    }];
    /// §271：三瓶药水（`roll_reward` 的 `pick_potion` 要一个非空池子；`sozu` 那条判据
    /// 要证明"永远不发"，所以池子得**本来就会**发）。
    const POTIONS: [PoolPotion<'static>; 3] = [
        PoolPotion { id: "fire_potion", rarity: Rarity::Common },
        PoolPotion { id: "block_potion", rarity: Rarity::Common },
        PoolPotion { id: "energy_potion", rarity: Rarity::Uncommon },
    ];
    /// The starting deck (inv:§2.1), in order.
    const DECK: [&str; 10] = [
        "strike", "strike", "strike", "strike", "strike",
        "defend", "defend", "defend", "defend",
        "bash",
    ];

    #[test]
    fn a_rest_site_heals_thirty_percent_and_then_it_is_done() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Rest), "the map has no rest site");
        assert_eq!(run.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Rest));
        assert_eq!(run.pending(), Pending::Rest);
        // 30% of 80, rounded down (`inv:§8.1`).
        assert_eq!(run.rest_heal(), 24);
        run.adjust_health(-40);
        assert_eq!(run.health(), 40);
        assert_eq!(run.rest(), Ok(24));
        assert_eq!(run.health(), 64);
        assert_eq!(run.pending(), Pending::None);
        // A second rest from the same site is an out-of-order action, not a free heal.
        assert_eq!(run.rest(), Err(RunError::WrongPhase));
        assert_eq!(run.health(), 64);
    }

    #[test]
    fn smithing_replaces_the_card_with_its_upgraded_row() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Rest));
        run.begin_node(&basic_pool(), &RELICS).unwrap();
        // The deck's first card is a `strike`; the upgrade is another CARD row, and the mapping is
        // the caller's (`sts-act1-plan.md` §6.5-2 -- this crate owns no content).
        assert_eq!(run.deck()[0].as_str(), "strike");
        run.smith(0, "strike+").unwrap();
        assert_eq!(run.deck()[0].as_str(), "strike+");
        assert_eq!(run.pending(), Pending::None);
        // Bad index, and "upgrading" to what is already there.
        run.pending = Pending::Rest;
        assert_eq!(run.smith(99, "strike+"), Err(RunError::BadCard(99)));
        assert_eq!(run.smith(0, "strike+"), Err(RunError::BadCard(0)));
        assert_eq!(run.pending(), Pending::Rest, "a refused smith must not consume the node");
    }

    #[test]
    fn a_chest_gives_gold_in_range_and_a_relic() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Treasure), "the map has no treasure room");
        let gold_before = run.gold();
        assert_eq!(run.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Treasure));
        assert_eq!(run.pending(), Pending::Chest);
        let outcome = run.open_chest(&TYPED_CARDS, &RELICS).unwrap();
        // `inv:§8.3`: the three chest types and their gold ranges.
        let (low, high) = match outcome.chest {
            0 => (23, 27),
            1 => (45, 55),
            _ => (68, 82),
        };
        assert!(
            outcome.gold == 0 || (outcome.gold >= low && outcome.gold <= high),
            "chest {} gave {} gold, which is not in its range",
            outcome.chest,
            outcome.gold
        );
        assert_eq!(run.gold(), gold_before + outcome.gold);
        assert_eq!(
            outcome.relic.map(|id| id.as_str().to_string()),
            Some("burning_blood".to_string())
        );
        assert_eq!(run.relics().len(), 1);
        assert_eq!(run.pending(), Pending::None);
        assert_eq!(run.open_chest(&TYPED_CARDS, &RELICS), Err(RunError::WrongPhase));
    }

    #[test]
    fn a_shop_stocks_five_cards_and_three_relics_with_prices_in_range() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Shop), "the map has no merchant");
        run.adjust_gold(500);
        assert_eq!(run.begin_node(&common_pool(), &RELICS), Ok(NodeKind::Shop));
        assert_eq!(run.pending(), Pending::Shop);
        assert_eq!(run.shop().cards().len(), MAX_SHOP_CARDS);
        assert_eq!(run.shop().relics().len(), MAX_SHOP_RELICS.min(RELICS.len()));
        for offer in run.shop().cards() {
            // All five are Commons, so they sit in the Common band (`inv:§8.2`) -- no more
            // `[推断]`: the band now comes from the card's rarity.
            let (low, high) = card_price_band(Rarity::Common);
            assert!(
                (low..=high).contains(&offer.price),
                "card {} costs {}",
                offer.id.as_str(),
                offer.price
            );
            assert!(common_pool().iter().any(|card| card.id == offer.id.as_str()));
        }
        for offer in run.shop().relics() {
            assert!((143..=157).contains(&offer.price), "relic price {}", offer.price);
        }
    }

    #[test]
    fn buying_and_removing_are_paid_for_and_never_silent() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Shop));
        run.adjust_gold(120);
        run.begin_node(&basic_pool(), &RELICS).unwrap();

        // A purchase moves gold one way and a card the other.
        // Owned, not borrowed: the next call takes `&mut run`.
        let (id, price) = {
            let offer = run.shop().cards()[0];
            (offer.id.as_str().to_string(), offer.price)
        };
        let deck_before = run.deck().len();
        let gold_before = run.gold();
        assert_eq!(buy_card_at(&mut run, 0), Ok(()));
        assert_eq!(run.gold(), gold_before - price);
        assert_eq!(run.deck().len(), deck_before + 1);
        assert_eq!(run.deck()[deck_before].as_str(), id);
        // The same slot twice is an empty offer, not a second card.
        assert_eq!(buy_card_at(&mut run, 0), Err(RunError::EmptyOffer(0)));
        assert_eq!(run.deck().len(), deck_before + 1);

        // Removal: 75 the first time (`inv:§8.2`), and the deck keeps its order.
        let gold_before = run.gold();
        let second = run.deck()[1].as_str().to_string();
        assert_eq!(run.remove_card_price(), 75);
        assert_eq!(run.remove_card(0), Ok(75));
        assert_eq!(run.gold(), gold_before - 75);
        assert_eq!(run.deck().len(), deck_before);
        assert_eq!(run.deck()[0].as_str(), second, "the survivors keep their order");
        assert_eq!(run.remove_card_price(), 100, "+25 per use, across shops");

        // And the price has to be payable: an empty purse refuses and changes nothing.
        run.adjust_gold(-9999);
        assert_eq!(run.gold(), 0);
        let deck_now: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert!(matches!(
            run.remove_card(0).unwrap_err(),
            RunError::NotEnoughGold { price: 100, gold: 0 }
        ));
        let deck_after: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert_eq!(deck_now, deck_after, "a refused purchase must not change the deck");
    }

    #[test]
    fn the_nodes_m1_does_not_settle_are_loud() {
        // `Elite` and `Unknown` are named as "not in M1" (`sts-act1-plan.md` §4). Walking onto one
        // must be an error, not a silent no-op -- that is the promise `env-abi.md` §11.5 makes.
        // Elite settles as a fight since the sentries exist (inv:§4.2); only Unknown is left.
        // Every kind M1 knows settles: `Elite` since the sentries (`inv:§4.2`), `Unknown` since the events
        // (`inv:§7.3`). Nothing is refused for being the wrong *kind* any more -- what must stay loud
        // is an action in the wrong *phase*.
        let mut run = ironclad();
        if walk_to(&mut run, NodeKind::Unknown) {
            assert_eq!(
                run.begin_node(&basic_pool(), &RELICS),
                Ok(NodeKind::Unknown),
                "a `?` room settles as an event now"
            );
            assert_eq!(run.pending(), Pending::None, "the caller picks the event");
        }
                // A fight is the caller's business: no error, nothing pending.
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Combat));
        assert_eq!(run.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Combat));
        assert_eq!(run.pending(), Pending::None);
        // And every settling action refuses when nothing is pending.
        assert_eq!(run.rest(), Err(RunError::WrongPhase));
        assert_eq!(run.open_chest(&TYPED_CARDS, &RELICS), Err(RunError::WrongPhase));
        assert_eq!(buy_card_at(&mut run, 0), Err(RunError::WrongPhase));
        assert_eq!(run.leave(), Err(RunError::WrongPhase));
    }

    /// `inv:§5` + `inv:§3.5`: gold in range, three cards, **all different**.
    ///
    /// Distinctness is the property worth a test: rolling three cards from a pool with a duplicate
    /// is easy to write and hard to notice -- the screen would look fine and simply offer the same
    /// card twice.
    #[test]
    fn a_reward_pays_gold_in_range_and_three_different_cards() {
        for seed in 0..25 {
            let mut run = RunState::new(seed, 80, 0, &DECK).expect("a run");
            let gold_before = run.gold();
            run.roll_reward(&basic_pool(), &[], &[], FightKind::Normal).expect("a reward");
            let reward = run.reward();
            let (low, high) = FightKind::Normal.gold();
            assert!(
                reward.gold() >= low && reward.gold() <= high,
                "seed {seed}: {} gold is outside {low}..={high}",
                reward.gold()
            );
            assert_eq!(run.gold(), gold_before + reward.gold(), "seed {seed}");
            let cards: Vec<&str> = reward.cards().iter().map(RunId::as_str).collect();
            // §269：一屏的张数是 `BASE_REWARD_CARDS`（3），而 `MAX_REWARD_CARDS`（4）只是**存储**。
            assert_eq!(cards.len(), BASE_REWARD_CARDS);
            let mut sorted = cards.clone();
            sorted.sort_unstable();
            sorted.dedup();
            assert_eq!(sorted.len(), cards.len(), "seed {seed}: {cards:?} has a repeat");
            for card in &cards {
                assert!(CARDS.contains(card), "seed {seed}: {card} is not in the pool");
            }
            assert_eq!(run.pending(), Pending::Reward);
        }
    }

    /// Taking a card adds exactly one; **the screen stays open**; skipping adds none.
    ///
    /// §161.8 changed the first half of this test. `take_card` used to leave the phase, which meant
    /// the potion and the relic rows vanished with it -- an elite's relic was lost by any player who
    /// took the card first (i.e. by everyone). The three rows are independent in StS, and
    /// `take_relic`/`take_potion` already behaved that way; `take_card` was the odd one out.
    #[test]
    fn taking_and_skipping_a_reward() {
        let mut run = RunState::new(3, 80, 0, &DECK).expect("a run");
        run.roll_reward(&basic_pool(), &[], &[], FightKind::Normal).unwrap();
        let wanted = run.reward().cards()[1].as_str().to_string();
        let deck_before = run.deck().len();
        take_card_at(&mut run, 1).expect("take the second card");
        assert_eq!(run.deck().len(), deck_before + 1);
        assert_eq!(run.deck()[deck_before].as_str(), wanted);
        assert_eq!(
            run.pending(),
            Pending::Reward,
            "taking the card must leave the other rows on the table"
        );

        // The card choice is **one** pick: every card row is spent, so a second take is refused.
        assert_eq!(run.reward().cards().len(), 0, "the card choice was spent");
        assert_eq!(take_card_at(&mut run, 0), Err(RunError::EmptyOffer(0)));

        // …but the screen itself is still up, because the potion/relic rows are separate offers.
        assert_eq!(run.pending(), Pending::Reward);

        // Leaving is `skip_reward`, and it settles the node.
        run.skip_reward().expect("leave the screen");
        assert_eq!(run.pending(), Pending::None);
        assert_eq!(run.skip_reward(), Err(RunError::WrongPhase));

        // Skipping a fresh screen takes nothing.
        run.roll_reward(&basic_pool(), &[], &[], FightKind::Normal).unwrap();
        let deck_before = run.deck().len();
        run.skip_reward().expect("skip");
        assert_eq!(run.deck().len(), deck_before);
        assert_eq!(run.pending(), Pending::None);
    }

    /// A pool too small to fill three distinct slots is an **error**, not a short or repeating
    /// screen.
    #[test]
    fn a_pool_too_small_for_three_distinct_cards_is_loud() {
        let mut run = RunState::new(3, 80, 0, &DECK).expect("a run");
        let two: [PoolCard<'_>; 2] = [
            PoolCard { id: "strike", rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "defend", rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None },
        ];
        assert_eq!(
            run.roll_reward(&two, &[], &[], FightKind::Normal),
            Err(RunError::PoolTooSmall { pool: 2, need: 3 })
        );
        assert_eq!(run.pending(), Pending::None, "a refused roll leaves no phase behind");
        assert_eq!(run.gold(), 0, "and pays no gold");
    }

    /// This image's pool: three Basics plus the junk card (which must be filtered out).
    fn basic_pool() -> [PoolCard<'static>; 5] {
        [
            PoolCard { id: "strike", rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "defend", rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "bash", rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "slimed", rarity: Rarity::Status, kind: CardKind::Other, upgraded: None },
            // §229: `upgrade_at` now **looks up** the next row instead of appending `+` blindly, so a
            // fixture without `strike+` would make "upgrade" a silent no-op. That is the point of the
            // change -- and the pool below is what a real caller passes (the whole `CARD` table).
            PoolCard { id: "strike+", rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None },
        ]
    }

    /// Five Commons: a full shelf, all in one price band.
    fn common_pool() -> [PoolCard<'static>; 5] {
        [
            PoolCard { id: "c1", rarity: Rarity::Common, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "c2", rarity: Rarity::Common, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "c3", rarity: Rarity::Common, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "c4", rarity: Rarity::Common, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "c5", rarity: Rarity::Common, kind: CardKind::Other, upgraded: None },
        ]
    }

    /// A pool with all three rarities, for the band arithmetic the real content cannot exercise yet.
    fn mixed_pool() -> [PoolCard<'static>; 6] {
        [
            PoolCard { id: "c1", rarity: Rarity::Common, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "c2", rarity: Rarity::Common, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "u1", rarity: Rarity::Uncommon, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "u2", rarity: Rarity::Uncommon, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "r1", rarity: Rarity::Rare, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "r2", rarity: Rarity::Rare, kind: CardKind::Other, upgraded: None },
        ]
    }

    /// The band arithmetic, pinned to the table the wiki prints (`Card Rewards`, "Actual at reset"
    /// and the "next-slot rare chance after a rare hit" rows).
    ///
    /// The subtle one is `(0, 35)` for a normal fight at a fresh reset: the rare band is
    /// `3 + (−5) = −2`, so it floors to 0 **and the 2% it lost is taken off the bottom of the
    /// uncommon band**, not handed to it. An implementation that clamps rare to 0 and keeps
    /// uncommon at 37% would pass every "roughly 3/37/60" test and be wrong.
    #[test]
    fn the_reward_bands_are_the_wikis() {
        // Normal fight: rare base 3, uncommon width 37.
        assert_eq!(reward_bands(FightKind::Normal, -5), (0, 35), "fresh reset");
        assert_eq!(reward_bands(FightKind::Normal, 0), (3, 40), "offset back to 0");
        assert_eq!(reward_bands(FightKind::Normal, 40), (43, 80), "offset capped at +40");

        // Elite: rare base 10, uncommon width 40. After a rare resets to −5 the next slot's rare
        // chance is 10 − 5 = 5%, which is the wiki's "Elite reward, second/third slot: 5%" row.
        assert_eq!(reward_bands(FightKind::Elite, -5), (5, 45));
        assert_eq!(reward_bands(FightKind::Elite, 0), (10, 50));

        // Boss: always rare, whatever the offset says.
        for offset in [-5, 0, 40] {
            assert_eq!(reward_bands(FightKind::Boss, offset), (100, 100));
        }

        // `inv:§5` gold, all three tiers.
        assert_eq!(FightKind::Normal.gold(), (10, 20));
        assert_eq!(FightKind::Elite.gold(), (25, 35));
        assert_eq!(FightKind::Boss.gold(), (95, 105));
    }

    /// §157：药水掉率是 wiki 那条**会走**的 40%，不是常量。
    ///
    /// -10（掉了）/ +10（没掉），换幕重置。断言走的是**数字**而不是"某个种子恰好掉了几瓶"。
    /// §159: the Ascension rules that live in this crate, **each one its own level**.
    ///
    /// The wiki's list is cumulative, and the point of `at_least` is that a rule at level 14 does
    /// not fire at 13. That is the assertion here: every row is checked on both sides of its own
    /// threshold, because "A13 already has the A14 rule" is the bug a single `>=` written once in a
    /// hurry produces.
    #[test]
    fn the_ascension_rules_are_each_their_own_level() {
        let plain = RunState::new(11, 80, 0, &DECK).expect("a run");
        assert_eq!(plain.ascension(), 0);
        assert_eq!(plain.health_max(), 80, "A0 changes nothing");
        assert!(!plain.at_least(A_MAX_HP));
        assert_eq!(plain.potion_slots(), 3);
        assert_eq!(plain.remove_card_price(), SHOP_REMOVE_BASE);

        // A14: -5 maximum health for the Ironclad (the only character this content has).
        let a13 = RunState::new_with_ascension(11, 80, 0, &DECK, 13).expect("A13");
        let a14 = RunState::new_with_ascension(11, 80, 0, &DECK, 14).expect("A14");
        assert_eq!(a13.health_max(), 80, "A14 is level 14, not 13");
        assert_eq!(a14.health_max(), 75, "A14: -5");
        assert!(a14.at_least(A_MAX_HP));

        // A11: one less slot -- and the belt still adds its two, **on top of the base** (the wiki's
        // "5 with the belt, or 4 on ascension 11 and higher").
        let mut a11 = RunState::new_with_ascension(11, 80, 0, &DECK, 11).expect("A11");
        assert_eq!(a11.potion_slots(), 2);
        a11.push_relic("potion_belt", &TYPED_CARDS).expect("the belt");
        assert_eq!(a11.potion_slots(), 4);

        // A16: everything costs 10% more, including the removal service.
        let a16 = RunState::new_with_ascension(11, 80, 0, &DECK, 16).expect("A16");
        assert_eq!(a15_price(15), SHOP_REMOVE_BASE, "A15 is level 15, not 16");
        assert_eq!(
            a16.remove_card_price(),
            SHOP_REMOVE_BASE * ASCENDED_SHOP_PERCENT / 100
        );
    }

    /// The price at level `level`, for the "not yet" side of the A16 threshold.
    fn a15_price(level: u8) -> i32 {
        RunState::new_with_ascension(11, 80, 0, &DECK, level)
            .expect("a run")
            .remove_card_price()
    }

    /// §159 `A5`: an act's boss heals you to **full**, and Ascension 5 takes a quarter of it back.
    ///
    /// The base rule did not exist before this section -- which is worth saying out loud, because
    /// `A5`'s wiki text is "heal 75% of missing health **instead of 100%**", and a fraction of a heal
    /// that never happened would have been a rule about nothing.
    #[test]
    fn a_boss_heals_to_full_and_ascension_five_heals_three_quarters() {
        let mut plain = RunState::new(11, 80, 0, &DECK).expect("a run");
        plain.adjust_health(-40);
        assert_eq!(plain.health(), 40);
        plain.mark_boss_beaten();
        assert_eq!(plain.health(), 80, "a cleared act heals you to full");

        let mut a4 = RunState::new_with_ascension(11, 80, 0, &DECK, 4).expect("A4");
        a4.adjust_health(-40);
        a4.mark_boss_beaten();
        assert_eq!(a4.health(), 80, "A5 is level 5, not 4");

        let mut a5 = RunState::new_with_ascension(11, 80, 0, &DECK, 5).expect("A5");
        a5.adjust_health(-40);
        a5.mark_boss_beaten();
        assert_eq!(a5.health(), 40 + 30, "A5: 75% of the 40 that was missing");
    }

    /// §159 `A7`/`A8`/`A9`: the health bonus belongs to **its own** fight kind.
    #[test]
    fn the_enemy_health_bonus_belongs_to_its_own_fight_kind() {
        fn levels(run: &RunState) -> [i32; 3] {
            [
                run.enemy_health_bonus_percent(FightKind::Normal),
                run.enemy_health_bonus_percent(FightKind::Elite),
                run.enemy_health_bonus_percent(FightKind::Boss),
            ]
        }
        let plain = RunState::new(11, 80, 0, &DECK).expect("a run");
        assert_eq!(levels(&plain), [0, 0, 0]);
        let a7 = RunState::new_with_ascension(11, 80, 0, &DECK, 7).expect("A7");
        assert_eq!(
            levels(&a7),
            [ASCENDED_ENEMY_HEALTH_PERCENT, 0, 0],
            "A7 is normal fights only"
        );
        let a8 = RunState::new_with_ascension(11, 80, 0, &DECK, 8).expect("A8");
        assert_eq!(
            levels(&a8),
            [ASCENDED_ENEMY_HEALTH_PERCENT, ASCENDED_ENEMY_HEALTH_PERCENT, 0],
            "A8 adds elites, bosses still untouched"
        );
        let a9 = RunState::new_with_ascension(11, 80, 0, &DECK, 9).expect("A9");
        assert_eq!(levels(&a9), [ASCENDED_ENEMY_HEALTH_PERCENT; 3]);
        // A level above the ladder is clamped, not refused: an off-by-one from the page should not
        // be a dead button.
        let over = RunState::new_with_ascension(11, 80, 0, &DECK, 99).expect("A99");
        assert_eq!(over.ascension(), MAX_ASCENSION);
    }

    #[test]
    fn the_potion_chance_walks_the_wikis_ten_percent() {
        let pool = [
            PoolCard {
                id: "strike",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
            PoolCard {
                id: "defend",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
            PoolCard {
                id: "anger",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
        ];
        // A pool with one potion: with an **empty** pool a rolled drop cannot be offered, and then
        // "offered" stops meaning "rolled" (found the hard way).
        let potions = [PoolPotion {
            id: "fire_potion",
            rarity: Rarity::Common,
        }];
        let mut run = RunState::new(31, 80, 0, &DECK).expect("a run");
        assert_eq!(run.potion_drop_chance(), POTION_DROP_START, "starts at 40");
        let mut drops = 0;
        let mut misses = 0;
        for _ in 0..12 {
            run.skip_reward().ok();
            // Drain the belt first: a **full** belt suppresses the offer while the drop still counts
            // (the wiki's Colosseum note), and then "offered" would stop meaning "dropped". Dropping
            // needs `Pending::None`, which `skip_reward` just gave us.
            while !run.potions().is_empty() {
                let _ = run.drop_potion(0);
            }
            let before = run.potion_drop_chance();
            run.roll_reward(&pool, &potions, &[], FightKind::Normal)
                .expect("a reward");
            let offered = run.reward_potion().is_some();
            let after = run.potion_drop_chance();
            if offered {
                drops += 1;
                assert_eq!(after, (before - POTION_DROP_STEP).max(0), "a drop moves it down");
            } else {
                misses += 1;
                assert_eq!(after, (before + POTION_DROP_STEP).min(100), "a miss moves it up");
            }
            assert!((0..=100).contains(&after), "the chance stays a percentage");
        }
        assert!(drops > 0 && misses > 0, "12 rolls should contain both outcomes");
    }

    /// §157：**腰带满了照样摇**（wiki 的 Colosseum 注记就靠这一点），只是不摆出来。
    #[test]
    fn a_full_belt_still_rolls_the_chance() {
        let pool = [PoolPotion {
            id: "fire_potion",
            rarity: Rarity::Common,
        }];
        let cards = [
            PoolCard {
                id: "strike",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
            PoolCard {
                id: "defend",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
            PoolCard {
                id: "anger",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
        ];
        let mut run = RunState::new(41, 80, 0, &DECK).expect("a run");
        for _ in 0..BASE_POTION_SLOTS {
            run.push_potion("fire_potion").expect("room");
        }
        assert!(!run.potion_room(), "the belt is full");
        let mut moved = false;
        for _ in 0..8 {
            let before = run.potion_drop_chance();
            run.roll_reward(&cards, &pool, &[], FightKind::Normal)
                .expect("a reward");
            assert_eq!(run.reward_potion(), None, "a full belt gets no offer");
            if run.potion_drop_chance() != before {
                moved = true;
            }
            run.skip_reward().expect("skip");
        }
        assert!(moved, "the chance must keep moving even when nothing is offered");
    }

    /// §157：药水按稀有度权重抽（65/25/10）—— 和遗物那条同样是**宽松**的烟测。
    #[test]
    fn potions_are_drawn_by_rarity_weight() {
        let pool = [
            PoolPotion {
                id: "fire_potion",
                rarity: Rarity::Common,
            },
            PoolPotion {
                id: "energy_potion",
                rarity: Rarity::Uncommon,
            },
            PoolPotion {
                id: "regen_potion",
                rarity: Rarity::Rare,
            },
        ];
        let mut run = RunState::new(51, 80, 0, &DECK).expect("a run");
        let mut commons = 0;
        let mut uncommons = 0;
        let mut rares = 0;
        for _ in 0..40 {
            // A miss is possible; that is what the 40% is. Count only what came out.
            match run.pick_rarity(RunStream::Potion, &POTION_RARITY_WEIGHTS, &[Rarity::Common, Rarity::Uncommon, Rarity::Rare]).expect("a band") {
                Some(Rarity::Common) => commons += 1,
                Some(Rarity::Uncommon) => uncommons += 1,
                Some(Rarity::Rare) => rares += 1,
                other => panic!("unexpected band {other:?}"),
            }
        }
        assert_eq!(commons + uncommons + rares, 40);
        assert!(commons > uncommons, "common {commons} vs uncommon {uncommons}");
        assert!(
            uncommons >= rares,
            "uncommon {uncommons} vs rare {rares} (65/25/10)"
        );
        // A pool with only rares shifts the mass instead of returning nothing.
        for _ in 0..10 {
            assert_eq!(
                run.pick_rarity(RunStream::Potion, &POTION_RARITY_WEIGHTS, &[Rarity::Rare])
                    .expect("a band"),
                Some(Rarity::Rare)
            );
        }
        let _ = pool;
    }

    /// §157：Potion Belt 是唯一增加腰带格数的东西（wiki 原话），所以格数是**方法**而不是数组长度。
    #[test]
    fn potion_belt_raises_the_slot_count() {
        let mut run = RunState::new(61, 80, 0, &DECK).expect("a run");
        assert_eq!(run.potion_slots(), BASE_POTION_SLOTS, "three slots");
        for _ in 0..BASE_POTION_SLOTS {
            run.push_potion("fire_potion").expect("room");
        }
        assert_eq!(
            run.push_potion("fire_potion"),
            Err(RunError::Capacity),
            "the fourth is refused without the belt"
        );

        run.push_relic("potion_belt", &TYPED_CARDS).expect("the belt");
        assert_eq!(run.potion_slots(), BASE_POTION_SLOTS + 2, "two more slots");
        assert!(run.push_potion("fire_potion").is_ok(), "the fourth fits now");
        assert!(run.push_potion("fire_potion").is_ok(), "and the fifth");
        assert_eq!(
            run.push_potion("fire_potion"),
            Err(RunError::Capacity),
            "the sixth is still refused"
        );
        assert_eq!(
            run.potions().len(),
            usize::from(BASE_POTION_SLOTS) + 2,
            "the belt holds five"
        );
    }

    /// **检测**：被拒绝的购买不许改变可观察状态（REVIEW P0，§160）。
    ///
    /// `buy_card` / `buy_relic` 原本是"先扣钱、再 `push_*?`"。牌组或遗物栏满时 `push_*` 返回
    /// `Capacity`，而金币已经扣掉、货架也还在 —— 一次**被拒绝**的操作改了状态。契约是
    /// "拒绝 ⇒ 什么都没发生（包括 RNG）"，所以失败的半步必须在前。
    ///
    /// 故意把顺序改回去，这条必须红 —— 而且红在**金币**上，不是红在错误码上。
    #[test]
    fn a_refused_purchase_leaves_the_run_untouched() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Shop), "the map has no shop");
        run.adjust_gold(400);
        assert_eq!(run.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Shop));

        // Fill the deck to capacity, then try to buy a card.
        while (run.deck_len as usize) < MAX_RUN_DECK {
            run.push_card(PoolCard::plain("strike")).expect("room until the cap");
        }
        let gold = run.gold();
        let price = run.shop().cards()[0].price;
        assert!(price > 0, "the shelf has a price");
        assert_eq!(
            buy_card_at(&mut run, 0),
            Err(RunError::Capacity),
            "a full deck must refuse the card"
        );
        assert_eq!(run.gold(), gold, "and the gold must not move");
        assert_eq!(
            run.shop().cards()[0].price,
            price,
            "the offer is still on the shelf, at the same price"
        );

        // Same shape for relics: the array is smaller, so this one is easier to reach.
        while (run.relics_len as usize) < MAX_RUN_RELICS {
            run.push_relic("anchor", &TYPED_CARDS).expect("room until the cap");
        }
        let gold = run.gold();
        let price = run.shop().relics()[0].price;
        assert_eq!(
            buy_relic_at(&mut run, 0),
            Err(RunError::Capacity),
            "a full relic belt must refuse the relic"
        );
        assert_eq!(run.gold(), gold, "and the gold must not move");
        assert_eq!(run.shop().relics()[0].price, price, "the relic is still shelved");
    }

    /// **Eternal Feather 的三件事**（REVIEW P1，§160）：整除、触发点、边界。
    ///
    /// 旧实现 `amount * deck_len / 5` 是**按期摊**，不是"每满五张"：8 张给 4、9 张给 5（应为 3）。
    /// §157 只测了 10 张（两种写法都是 6），所以全绿 —— 分段函数只测了整档。
    /// 触发点也错：它被塞进 `rest_heal()`，而那只在 `rest()` 里被调用，wiki 说的是**进入**时回血
    /// （原文："Heal applies on entering, so you can Rest less often."），所以打铁也应吃到。
    #[test]
    fn the_eternal_feather_pays_per_whole_group_of_five_on_entering() {
        for (cards, want) in [(5usize, 3), (8, 3), (9, 3), (10, 6), (14, 6)] {
            let deck: Vec<&str> = vec!["strike"; cards];
            let mut run = RunState::new(71, 80, 0, &deck).expect("a run");
            run.push_relic("eternal_feather", &TYPED_CARDS).expect("the feather");
            assert_eq!(
                run.rest_site_entry_heal(),
                want,
                "a deck of {cards} cards pays {want}"
            );
        }

        // 触发点是**进入**：Rest 与 Smith 都吃到，而且只吃一次。
        let mut resting = RunState::new(71, 80, 0, &DECK).expect("a run");
        resting.push_relic("eternal_feather", &TYPED_CARDS).expect("the feather");
        assert!(walk_to(&mut resting, NodeKind::Rest));
        resting.adjust_health(-40);
        assert_eq!(resting.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Rest));
        let after_entry = resting.health();
        assert_eq!(after_entry, 46, "ten cards = two groups of five, on entering");
        // The Rest **button** then adds its own 30% on top, and the entry heal is not repeated.
        assert_eq!(resting.rest(), Ok(24), "30% of 80");
        assert_eq!(resting.health(), after_entry + 24);

        let mut smithing = RunState::new(71, 80, 0, &DECK).expect("a run");
        smithing.push_relic("eternal_feather", &TYPED_CARDS).expect("the feather");
        assert!(walk_to(&mut smithing, NodeKind::Rest));
        smithing.adjust_health(-40);
        assert_eq!(smithing.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Rest));
        assert_eq!(
            smithing.health(),
            46,
            "entering pays even if the player is about to smith"
        );
        smithing.smith(0, "strike+").expect("upgrade");
        assert_eq!(
            smithing.health(),
            46,
            "and smithing does not take the entry heal back"
        );
    }

    /// **`Event` 稀有度的遗物永远不进掉落池**（REVIEW P1，§160）。
    ///
    /// wiki 的遗物导航盒把 `golden_idol` 列在 **Event** 下：它能被持有、能生效，但宝箱/精英/商店
    /// 都不该抽到它。内容里原来写的是 `Rare`，于是每次精英奖励有 17% 概率给出一件事件遗物。
    ///
    /// 判据分两半：只有事件遗物的池子给 `EMPTY`（而不是"退回第一个"），混合池子 40 次里一次都不给。
    #[test]
    fn an_event_relic_is_never_drawn() {
        let mut run = RunState::new(31, 80, 0, &DECK).expect("a run");
        let only_event = [PoolRelic {
            id: "golden_idol",
            rarity: Rarity::Event,
        }];
        for _ in 0..20 {
            assert_eq!(
                run.pick_relic(RunStream::Reward, &only_event),
                Ok(RunId::EMPTY),
                "a pool of event-only relics offers nothing"
            );
        }
        let mixed = [
            PoolRelic {
                id: "golden_idol",
                rarity: Rarity::Event,
            },
            PoolRelic {
                id: "anchor",
                rarity: Rarity::Common,
            },
        ];
        for _ in 0..40 {
            assert_eq!(
                run.pick_relic(RunStream::Reward, &mixed),
                Ok(RunId::new("anchor").expect("id")),
                "the idol is never rolled, the anchor always is"
            );
        }
    }

    /// §218：wiki 的 `Special` 桶（事件专属的牌，`apparition`）—— 名字要能解析，**而且不进奖励**。
    ///
    /// 两半都是实战出来的：把 `apparition` 的稀有度从 Uncommon 改成 Special 时，
    /// `Rarity::from_name("Special")` 返回 `None` �� `full_pool()` 拒掉整张牌表 ⇒ **每一个**
    /// `rd_run_choose_start` 都以 -2 失败（6 条 wasm 测试同时红，报的是"taking blessing 0"）。
    /// 所以"能解析"要单独钉一次，否则下次有人加桶忘了 `from_name`，症状会出现在离得很远的地方。
    #[test]
    fn a_special_card_is_known_and_never_put_in_a_reward() {
        assert_eq!(Rarity::from_name("Special"), Some(Rarity::Special));
        let pool = [
            PoolCard { id: "apparition", rarity: Rarity::Special, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "anger", rarity: Rarity::Common, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "blur", rarity: Rarity::Uncommon, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "bash", rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None },
        ];
        for seed in 0..40 {
            let mut run = RunState::new(seed, 80, 0, &DECK).expect("a run");
            run.roll_reward(&pool, &[], &[], FightKind::Normal).expect("a reward");
            let cards: Vec<&str> = run.reward().cards().iter().map(RunId::as_str).collect();
            assert!(
                !cards.contains(&"apparition"),
                "seed {seed}: an event-only card showed up as a reward: {cards:?}"
            );
        }
    }

    /// §224：开战加成的**两张表** —— `oddly_smooth_stone` 给英雄，`bag_of_marbles` 给敌人。
    ///
    /// 判据的两半缺一不可：
    /// * 英雄那张表**不许**拿到易伤（那正是 §222 的错误：一件"给敌人易伤"的遗物把英雄自己变脆，
    ///   垂直切片里 Boss 直接打不过 —— 而单元测试一条都没红）；
    /// * 敌人那张表**必须**有易伤，且 `is_empty` 要看它（漏了它，`apply_combat_bonus` 会早退，
    ///   遗物静默不生效）。
    #[test]
    fn the_two_combat_start_carriers_land_on_the_right_side() {
        let mut run = RunState::new(3, 80, 0, &DECK).expect("a run");
        assert!(run.combat_bonus().is_empty(), "no relic, no bonus");
        run.push_relic("oddly_smooth_stone", &TYPED_CARDS).expect("the belt takes it");
        let hero_side = run.combat_bonus();
        assert_eq!(hero_side.status_count, 1, "the hero gets one status");
        assert_eq!(hero_side.statuses[0].expect("set").id, "standard.dexterity");
        assert_eq!(hero_side.enemy_status_count, 0, "and the enemies get none");

        run.push_relic("bag_of_marbles", &TYPED_CARDS).expect("the belt takes it");
        let both = run.combat_bonus();
        assert_eq!(
            both.status_count, 1,
            "the enemy-side relic must NOT add a hero status (that was §222's bug)"
        );
        assert_eq!(both.statuses[0].expect("set").id, "standard.dexterity");
        assert_eq!(both.enemy_status_count, 1, "the enemies get one status");
        assert_eq!(
            both.enemy_statuses[0].expect("set").id,
            "standard.vulnerable",
            "wiki: apply 1 Vulnerable to ALL enemies"
        );
        assert_eq!(both.enemy_statuses[0].expect("set").stacks, 1);
        assert!(!both.is_empty(), "`is_empty` must see the enemy list too");
    }

    /// §221：**内容里的卡行数不许超过池子上限** —— 否则每一条走真实地图的路径都会在第一次
    /// 奖励/商店处 `PoolTooLarge`（§221 加了 10 张牌之后就撞到过：68 > 64）。
    ///
    /// 这条判据的写法值得说一句：它不是"读一个常量比对另一个常量"，而是**从内容数行**。
    /// `MAX_POOL` 是内核的定容上限（`pool_fits` 会响亮拒绝），而内容是该装进去的东西
    /// —— 两者的关系必须由一条测试说出来，而不是靠"下次加卡时某条回放测试碰巧红"。
    #[test]
    fn the_card_pool_fits_the_constant() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = rd_core::content::Content::parse(&blob).expect("the image parses");
        let rows = content.rows(rd_core::content::Table::Card).count();
        assert!(
            rows <= MAX_POOL,
            "the content has {rows} card rows but a reward/shop pool holds at most              {MAX_POOL} -- every real map walk would fail at its first reward screen"
        );
    }

    /// **一条超长的内容池必须响亮失败，不许被截成 64**（REVIEW P1，§161.1）。
    ///
    /// 五个读取器（`stock_shop` / `pick_potion` / `pick_relic_avoiding` / `grant_random_cards` /
    /// `roll_reward`）各有 `[_; MAX_POOL]`，原来都走 `len().min(MAX_POOL)`。超出的条目**永远抽不到**，
    /// 而内容、内容门和任何断言都看不出来 —— 与 §158 删掉的 `MAX_POOL_IDS = 8` 同形。
    ///
    /// 判据分两半：**恰好 64 仍然能用**（容量不该被误伤），**65 立刻红**（并报出长度与上限）。
    #[test]
    fn a_pool_longer_than_the_capacity_is_loud_instead_of_cut() {
        let at_cap: Vec<PoolCard<'static>> = (0..MAX_POOL)
            .map(|_| PoolCard {
                id: "strike",
                rarity: Rarity::Common,
                kind: CardKind::Other,
                upgraded: None,
            })
            .collect();
        let over: Vec<PoolCard<'static>> = (0..MAX_POOL + 1)
            .map(|_| PoolCard {
                id: "strike",
                rarity: Rarity::Common,
                kind: CardKind::Other,
                upgraded: None,
            })
            .collect();

        // `roll_reward` is the reader every fight goes through, so it is the one worth pinning.
        let mut run = RunState::new(41, 80, 0, &DECK).expect("a run");
        assert_eq!(
            run.roll_reward(&at_cap, &[], &[], FightKind::Normal),
            Ok(()),
            "a pool of exactly MAX_POOL is fine"
        );

        let mut run = RunState::new(41, 80, 0, &DECK).expect("a run");
        assert_eq!(
            run.roll_reward(&over, &[], &[], FightKind::Normal),
            Err(RunError::PoolTooLarge {
                pool: MAX_POOL + 1,
                max: MAX_POOL,
            }),
            "one card over the cap must be a red, not a silently smaller pool"
        );

        // `pick_relic_avoiding` and `pick_potion` are the other two the review named.
        let relics_over: Vec<PoolRelic<'static>> = (0..MAX_POOL + 1)
            .map(|_| PoolRelic {
                id: "anchor",
                rarity: Rarity::Common,
            })
            .collect();
        let mut run = RunState::new(41, 80, 0, &DECK).expect("a run");
        assert_eq!(
            run.pick_relic(RunStream::Reward, &relics_over),
            Err(RunError::PoolTooLarge {
                pool: MAX_POOL + 1,
                max: MAX_POOL,
            })
        );

        let potions_over: Vec<PoolPotion<'static>> = (0..MAX_POOL + 1)
            .map(|_| PoolPotion {
                id: "fire_potion",
                rarity: Rarity::Common,
            })
            .collect();
        let mut run = RunState::new(41, 80, 0, &DECK).expect("a run");
        assert_eq!(
            run.pick_potion(RunStream::Potion, &potions_over),
            Err(RunError::PoolTooLarge {
                pool: MAX_POOL + 1,
                max: MAX_POOL,
            })
        );

        // The shop stocks through `begin_node`, so the failure has to come back out of a node.
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Shop));
        assert_eq!(
            run.begin_node(&over, &RELICS),
            Err(RunError::PoolTooLarge {
                pool: MAX_POOL + 1,
                max: MAX_POOL,
            }),
            "a too-long card pool must refuse the node, not stock a shorter shop"
        );
    }

    /// **拒绝不改任何东西，包括 RNG**（REVIEW §四.1 的 L2 层，§161.2）。
    ///
    /// `RunState` 派生 `Copy + PartialEq + Eq`，而且**没有藏在别处的可观察状态**：整局就是这一个
    /// 结构体，`rng` 是它的一个字段。所以判据能写成最硬的一句 —— 调用前后整个 `RunState` 相等。
    ///
    /// 这比"逐字段比较"强，因为漏比一个字段正是 §160 的 P0（金币变了、牌组没变、没人发现）。
    /// 逐字段的清单会过期，`==` 不会。
    ///
    /// 覆盖的拒绝种类：相位不对、目标不对、容量满、重复领取、重复购买。
    #[test]
    fn every_refused_action_leaves_the_run_byte_identical() {
        macro_rules! refused {
            ($run:expr, $call:expr, $why:expr) => {{
                let before = *$run;
                let outcome = $call;
                assert!(outcome.is_err(), "{}: the action was ACCEPTED ({:?})", $why, outcome);
                // `assert!` rather than `assert_eq!`: the diff would print two whole `RunState`s
                // (the map alone is ~40 lines), and the only thing worth reading is which action.
                assert!(
                    *$run == before,
                    "{}: a refused action changed the run ({:?})",
                    $why,
                    outcome
                );
            }};
        }

        // (a) 相位：还没进节点的每一种"结算"动作。
        let mut run = ironclad();
        refused!(&mut run, buy_card_at(&mut run, 0), "buy without a shop");
        refused!(&mut run, buy_relic_at(&mut run, 0), "buy a relic without a shop");
        refused!(&mut run, run.rest(), "rest without a rest site");
        refused!(&mut run, run.smith(0, "strike+"), "smith without a rest site");
        refused!(&mut run, run.remove_card(0), "remove without a shop");
        refused!(&mut run, take_card_at(&mut run, 0), "take a card without a reward");
        refused!(&mut run, run.skip_reward(), "skip without a reward");

        // (b) 目标：不在图上的节点、以及不相邻的节点。
        refused!(&mut run, run.enter_node(200), "a node that is not on the map");
        refused!(&mut run, run.enter_node(u8::MAX), "the largest node index");

        // (c) 容量：§160 的 P0 在这一层被抓住 —— 牌组满了还去买。
        let mut shop = ironclad();
        assert!(walk_to(&mut shop, NodeKind::Shop), "the map has no shop");
        shop.adjust_gold(400);
        assert_eq!(shop.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Shop));
        while (shop.deck_len as usize) < MAX_RUN_DECK {
            shop.push_card(PoolCard::plain("strike")).expect("room until the cap");
        }
        let gold = shop.gold();
        refused!(&mut shop, buy_card_at(&mut shop, 0), "a card the deck has no room for");
        assert_eq!(shop.gold(), gold, "and the gold is part of `before`, so this is belt and braces");
        // 重复购买同一个货位。
        let mut again = ironclad();
        assert!(walk_to(&mut again, NodeKind::Shop));
        again.adjust_gold(400);
        assert_eq!(again.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Shop));
        assert_eq!(buy_card_at(&mut again, 0), Ok(()), "the first buy works");
        refused!(&mut again, buy_card_at(&mut again, 0), "the same shelf slot twice");
    }

    /// **同一种子 + 同一动作序列 ⇒ 同一局**（REVIEW §四.1，§161.2）。
    ///
    /// 这是"可复现"在**运行层**的版本：`rd-core` 有逐字节的哈希序列对拍，地图有
    /// `same_seed_same_map`，但"整局走同一条路"此前只有浏览器 soak 在间接覆盖。判据直接比
    /// `RunState`（含 `rng` 计数），所以一次多的 RNG 抽取也会红。
    #[test]
    fn the_same_seed_and_the_same_actions_replay_to_the_same_run() {
        fn trace(seed: i32) -> Vec<RunState> {
            let mut run = RunState::new(seed, 80, 0, &DECK).expect("a run");
            let mut out = Vec::new();
            for _ in 0..6 {
                // A fixed policy: the **first** legal edge, then whatever the node asks for.
                // `enter_node` takes a **global node index** (not a per-row slot), so the scan has
                // to cover a range; a rejected index changes nothing (the test above pins that).
                let mut moved = false;
                for index in 0..32u8 {
                    if run.enter_node(index).is_ok() {
                        moved = true;
                        break;
                    }
                }
                if !moved {
                    break;
                }
                let kind = run.begin_node(&basic_pool(), &RELICS).expect("begin");
                match kind {
                    NodeKind::Rest => {
                        let _ = run.rest();
                    }
                    NodeKind::Treasure => {
                        let _ = run.open_chest(&TYPED_CARDS, &RELICS);
                    }
                    NodeKind::Shop => {
                        let _ = run.leave();
                    }
                    _ => run.mark_resolved(),
                }
                out.push(run);
            }
            out
        }
        let first = trace(101);
        assert!(first.len() >= 3, "the fixture must actually walk somewhere");
        assert_eq!(first, trace(101), "same seed, same actions, same run");
        assert_ne!(first, trace(102), "a different seed must be a different run");
    }

    /// §157 的两件新遗物真的付账（§160 把 Eternal Feather 那半搬到了进入时）。
    #[test]
    fn the_new_relics_pay_out() {
        // Ten cards = two groups of five.
        let mut run = RunState::new(71, 80, 0, &DECK).expect("a run");
        let base = run.rest_heal();
        run.push_relic("eternal_feather", &TYPED_CARDS).expect("the feather");
        assert_eq!(run.deck_len, 10, "the fixture deck is ten cards");
        // §160: the feather is **not** part of `rest_heal` any more -- it pays on entering the rest
        // site, so `rest_heal` (the Rest button) is unchanged and the entry heal is its own number.
        assert_eq!(
            run.rest_heal(),
            base,
            "the Rest button does not carry the feather any more"
        );
        assert_eq!(
            run.rest_site_entry_heal(),
            3 * 2,
            "3 HP per five cards, two groups, paid on entering"
        );
        assert_eq!(run.rest_heal_per_cards(), 6);

        // The idol multiplies the fight's gold; the reward's own number is what was paid.
        let cards = [
            PoolCard {
                id: "strike",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
            PoolCard {
                id: "defend",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
            PoolCard {
                id: "anger",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
        ];
        let mut plain = RunState::new(81, 80, 0, &DECK).expect("a run");
        plain
            .roll_reward(&cards, &[], &[], FightKind::Normal)
            .expect("a reward");
        let plain_gold = plain.reward_gold();
        assert_eq!(plain.fight_gold_percent(), 100);

        let mut idol = RunState::new(81, 80, 0, &DECK).expect("a run");
        idol.push_relic("golden_idol", &TYPED_CARDS).expect("the idol");
        assert_eq!(idol.fight_gold_percent(), 125);
        idol.roll_reward(&cards, &[], &[], FightKind::Normal)
            .expect("a reward");
        assert_eq!(
            idol.reward_gold(),
            plain_gold * 125 / 100,
            "the same roll, 25% more"
        );
        assert_eq!(idol.gold(), plain.gold() + (plain_gold * 125 / 100) - plain_gold);
    }

    /// §156：稀有度权重**按顺序**生效，且空档不会把抽取变空。
    ///
    /// 断言是**刻意宽松**的：单个种子证明不了 50/33/17，这只是一条"权重真的用上了"的烟测。
    /// 精确分布属于统计断言，得由多次运行去说，不该由一条测试假装。
    #[test]
    fn relic_rarity_weights_favour_commons_and_shift_when_a_band_is_empty() {
        let pool = [
            PoolRelic {
                id: "common_one",
                rarity: Rarity::Common,
            },
            PoolRelic {
                id: "uncommon_one",
                rarity: Rarity::Uncommon,
            },
            PoolRelic {
                id: "rare_one",
                rarity: Rarity::Rare,
            },
        ];
        let mut run = RunState::new(21, 80, 0, &DECK).expect("a run");
        let mut commons = 0;
        let mut uncommons = 0;
        let mut rares = 0;
        for _ in 0..300 {
            let picked = run
                .pick_relic(RunStream::Chest, &pool)
                .expect("a relic each time");
            match picked.as_str() {
                "common_one" => commons += 1,
                "uncommon_one" => uncommons += 1,
                "rare_one" => rares += 1,
                other => panic!("picked {other}, which is not in the pool"),
            }
        }
        assert_eq!(commons + uncommons + rares, 300);
        assert!(commons > uncommons, "common {commons} vs uncommon {uncommons}: the 50/33 order");
        assert!(
            uncommons > rares,
            "uncommon {uncommons} vs rare {rares}: the 33/17 order"
        );
        assert!(rares > 0, "the rare band must still be reachable");

        // A pool with only rares: the weights re-normalise, they do not return nothing.
        let only_rare = [PoolRelic {
            id: "rare_one",
            rarity: Rarity::Rare,
        }];
        for _ in 0..20 {
            assert_eq!(
                run.pick_relic(RunStream::Chest, &only_rare)
                    .expect("a relic")
                    .as_str(),
                "rare_one"
            );
        }

        // An empty pool is "no relic", which is what the chest treats as an empty chest.
        assert_eq!(
            run.pick_relic(RunStream::Chest, &[]).expect("no relic").as_str(),
            "",
            "an empty pool yields the empty id, not an error"
        );
    }

    /// §155：**精英和 Boss 给遗物，普通怪不给**，而且绝不会再给一件已经有的。
    ///
    /// StS 的精英奖励是"金币 + 三选一 + 一件遗物"，本内核之前只给前两样 —— 一条能走完的路，
    /// 但少了一整类反馈。这条测试盯的是**规则**（哪一档给、给的时候会不会重复）。
    #[test]
    fn an_elite_pays_a_relic_and_a_normal_fight_does_not() {
        let pool = [
            PoolCard {
                id: "strike",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
            PoolCard {
                id: "defend",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
            PoolCard {
                id: "anger",
                rarity: Rarity::Basic,
                kind: CardKind::Other,
                upgraded: None,
            },
        ];
        let relics = [
            PoolRelic {
                id: "burning_blood",
                rarity: Rarity::Common,
            },
            PoolRelic {
                id: "vajra",
                rarity: Rarity::Common,
            },
            PoolRelic {
                id: "thread_and_needle",
                rarity: Rarity::Rare,
            },
        ];

        // A normal fight: no relic row at all.
        let mut run = RunState::new(5, 80, 0, &DECK).expect("a run");
        run.roll_reward(&pool, &[], &relics, FightKind::Normal)
            .expect("a normal reward");
        assert_eq!(run.reward_relic(), None, "a normal fight pays no relic");
        assert_eq!(
            run.take_relic(&TYPED_CARDS),
            Err(RunError::NoSuchRelic),
            "and taking one says so instead of doing nothing"
        );

        // An elite: a relic, and taking it lands in the relic list.
        let mut run = RunState::new(5, 80, 0, &DECK).expect("a run");
        let before = run.relics().len();
        run.roll_reward(&pool, &[], &relics, FightKind::Elite)
            .expect("an elite reward");
        let offered = run.reward_relic().expect("an elite pays a relic").to_string();
        assert!(
            relics.iter().any(|entry| entry.id == offered),
            "{offered} is not in the pool"
        );
        run.take_relic(&TYPED_CARDS).expect("take it");
        assert_eq!(run.relics().len(), before + 1, "the relic list grew");
        assert_eq!(
            run.relics().last().map(|id| id.as_str()),
            Some(offered.as_str()),
            "and it is the one that was offered"
        );
        assert_eq!(run.reward_relic(), None, "the row is empty after taking it");
        assert_eq!(run.take_relic(&TYPED_CARDS), Err(RunError::NoSuchRelic), "taking twice fails");

        // A held relic is never offered again: hold all three and the elite pays nothing.
        let mut run = RunState::new(5, 80, 0, &DECK).expect("a run");
        for relic in relics.iter().map(|entry| entry.id) {
            run.push_relic(relic, &TYPED_CARDS).expect("grant");
        }
        run.roll_reward(&pool, &[], &relics, FightKind::Elite)
            .expect("an elite reward with every relic held");
        assert_eq!(
            run.reward_relic(),
            None,
            "a full set means no relic, not a duplicate"
        );

        // A boss pays one too.
        let mut run = RunState::new(9, 80, 0, &DECK).expect("a run");
        run.roll_reward(&pool, &[], &relics, FightKind::Boss)
            .expect("a boss reward");
        assert!(run.reward_relic().is_some(), "a boss pays a relic");
    }

    /// The pity offset ticks **once per card rolled** -- including the ones a player skips, because
    /// the screen is generated up front -- and a rare resets it.
    ///
    /// The wiki's wording is "otherwise +1%", not "on a common +1%": an uncommon ticks it too.
    #[test]
    fn the_pity_offset_ticks_every_card_and_resets_on_a_rare() {
        let mut run = RunState::new(11, 80, 0, &DECK).expect("a run");
        assert_eq!(run.rarity_offset(), RARITY_OFFSET_START);

        // Every bucket but `Basic` is empty in this pool, so no roll can come out Rare: three cards
        // therefore tick the offset three times.
        run.roll_reward(&basic_pool(), &[], &[], FightKind::Normal).unwrap();
        assert_eq!(run.rarity_offset(), -2, "three ticks from -5");

        // A boss reward is always Rare, so every card resets it back to the floor.
        let rare_pool: [PoolCard<'_>; 3] = [
            PoolCard { id: "a", rarity: Rarity::Rare, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "b", rarity: Rarity::Rare, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "c", rarity: Rarity::Rare, kind: CardKind::Other, upgraded: None },
        ];
        run.skip_reward().unwrap();
        run.roll_reward(&rare_pool, &[], &[], FightKind::Boss).unwrap();
        assert_eq!(run.rarity_offset(), RARITY_OFFSET_START, "a rare resets the pity");

        // The cap holds: 45 more non-rare cards cannot push it past +40.
        for _ in 0..20 {
            run.skip_reward().unwrap();
            run.roll_reward(&basic_pool(), &[], &[], FightKind::Normal).unwrap();
        }
        assert!(run.rarity_offset() <= RARITY_OFFSET_CAP, "offset {} escaped the cap", run.rarity_offset());
    }

    /// `inv:§8.2`: the merchant's prices follow the card's rarity -- 45–55 / 68–82 / 135–165.
    ///
    /// This is the row that used to say `[推断]`（"all cards priced as Common, because the content
    /// carries no rarity"）. The content carries one now, so the bands are the documented ones.
    #[test]
    fn the_merchants_prices_follow_the_rarity_bands() {
        assert_eq!(card_price_band(Rarity::Common), (45, 55));
        assert_eq!(card_price_band(Rarity::Uncommon), (68, 82));
        assert_eq!(card_price_band(Rarity::Rare), (135, 165));

        let mut run = RunState::new(5, 80, 0, &DECK).expect("a run");
        assert!(walk_to(&mut run, NodeKind::Shop), "the map has no merchant");
        run.begin_node(&mixed_pool(), &RELICS).expect("a shop");
        assert_eq!(run.shop().cards().len(), MAX_SHOP_CARDS.min(mixed_pool().len()));
        for offer in run.shop().cards() {
            let rarity = mixed_pool()
                .iter()
                .find(|card| card.id == offer.id.as_str())
                .map(|card| card.rarity)
                .expect("the offer came from the pool");
            let (low, high) = card_price_band(rarity);
            assert!(
                offer.price >= low && offer.price <= high,
                "{} ({rarity:?}) costs {}, outside {low}..={high}",
                offer.id.as_str(),
                offer.price
            );
        }
    }

    /// Smith and removal take an **index**, and the UI now passes the one the player clicked. The
    /// old page hard-wired index 0 ("the first card"), so an implementation that ignored the
    /// argument would have looked correct -- this pins that it does not.
    #[test]
    fn smithing_a_middle_card_leaves_the_others_alone() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Rest));
        run.begin_node(&basic_pool(), &RELICS).expect("a rest site");
        let before: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert_eq!(before[2], "strike");
        run.smith(2, "strike+").expect("smith the third card");
        let after: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert_eq!(after[2], "strike+");
        assert_eq!(after.len(), before.len());
        for index in 0..before.len() {
            if index != 2 {
                assert_eq!(after[index], before[index], "card {index} changed");
            }
        }
    }

    /// Removing a middle card keeps the order of the survivors (`run_hash` writes the deck in
    /// order, so this is observable).
    #[test]
    fn removing_a_middle_card_keeps_the_order_of_the_survivors() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Shop));
        run.adjust_gold(500);
        run.begin_node(&common_pool(), &RELICS).expect("a merchant");
        let before: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        let expected: Vec<String> = before
            .iter()
            .enumerate()
            .filter(|(index, _)| *index != 3)
            .map(|(_, id)| id.clone())
            .collect();
        run.remove_card(3).expect("remove the fourth card");
        let after: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert_eq!(after, expected);
    }

    /// A node pays **once**. Without this, a combat node could be fought again from where you stand
    /// and a campfire would heal on every click -- the page showed exactly that before the guard.
    /// The two deck blessings really touch the deck. Taking one leaves the run in
    /// `Pending::BlessingCard`; the deck index is what finishes it.
    #[test]
    fn a_blessing_can_remove_or_upgrade_a_card() {
        let index_of = |id: &str| -> u8 {
            START_OFFERS
                .iter()
                .position(|offer| offer.id == id)
                .expect("in the pool") as u8
        };

        // Remove: the deck shrinks by one.
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.start_offers = [index_of("remove_card"), index_of("max_hp")];
        run.pending = Pending::Start;
        run.choose_start(0, &basic_pool()).expect("taking remove_card");
        assert_eq!(run.pending, Pending::BlessingCard, "the card pick is still owed");
        assert_eq!(run.blessing_follow_up(), Some(BlessingFollowUp::Deck(DeckChange::Remove)));
        let before = run.deck_len as usize;
        run.pick_blessing_card(3, &basic_pool()).expect("removing the fourth card");
        assert_eq!(run.pending, Pending::None);
        assert_eq!(run.deck_len as usize, before - 1, "one card left the deck");
        assert_eq!(run.blessing_follow_up(), None);

        // Upgrade: the row becomes the `+` variant and the size does not change.
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.start_offers = [index_of("upgrade_card"), index_of("max_hp")];
        run.pending = Pending::Start;
        run.choose_start(0, &basic_pool()).expect("taking upgrade_card");
        assert_eq!(run.blessing_follow_up(), Some(BlessingFollowUp::Deck(DeckChange::Upgrade)));
        assert_eq!(run.deck[2].as_str(), "strike");
        run.pick_blessing_card(2, &basic_pool()).expect("upgrading the third card");
        assert_eq!(run.deck[2].as_str(), "strike+");
        assert_eq!(run.deck_len, 10, "upgrading does not change the deck size");

        // A deck index that is not there is an error, not a silent no-op.
        // ⚠️ §143 顺手改对了错误类型：这里原来报 `BadNode`（那是**地图节点**的下标错误），
        // 而 `BadCard` 就是为"牌组里没有这张"存在的变体。两者长得都像"下标不对"，所以一直
        // 没被注意到 —— 直到 blessing 与 event 共用了 `apply_deck_change`。
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.pending = Pending::BlessingCard;
        run.blessing_follow = Some(BlessingFollowUp::Deck(DeckChange::Remove));
        assert_eq!(
            run.pick_blessing_card(99, &basic_pool()),
            Err(RunError::BadCard(99))
        );
    }

    /// **`transform_card` and `three_cards` are real**: one swaps a deck entry for a random one from
    /// the pool, the other adds three.
    #[test]
    fn a_blessing_can_transform_or_add_cards() {
        let index_of = |id: &str| -> u8 {
            START_OFFERS
                .iter()
                .position(|offer| offer.id == id)
                .expect("in the pool") as u8
        };

        // Transform: same size, different card.
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.start_offers = [index_of("transform_card"), index_of("max_hp")];
        run.pending = Pending::Start;
        run.choose_start(0, &basic_pool()).expect("taking transform_card");
        assert_eq!(run.blessing_follow_up(), Some(BlessingFollowUp::Deck(DeckChange::Transform)));
        let before = run.deck_len as usize;
        run.pick_blessing_card(4, &basic_pool()).expect("transforming the fifth card");
        assert_eq!(run.deck_len as usize, before, "transform keeps the size");
        assert_eq!(run.pending, Pending::None);

        // Three cards: +3, straight away (no pick).
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.start_offers = [index_of("three_cards"), index_of("max_hp")];
        run.pending = Pending::Start;
        run.choose_start(0, &basic_pool()).expect("taking three_cards");
        assert_eq!(run.pending, Pending::None, "no pick is owed");
        assert_eq!(run.deck_len, 13, "three cards joined the deck");
    }

    /// A blessing offer must be a **choice**: no heal at full health, and always something free.
    #[test]
    fn blessing_offers_are_never_nonsense() {
        for seed in 1..=80 {
            let mut run = RunState::new(seed, 80, 0, &["strike"; 10]).expect("a run");
            run.offer_start_choice().expect("offers");
            let offers = run.start_offers().expect("a pending choice");
            for offer in offers {
                assert!(
                    !matches!(offer.gain, EventEffect::Heal(_)),
                    "seed {seed}: heal offered at full health"
                );
            }
            assert!(
                offers
                    .iter()
                    .any(|offer| matches!(offer.cost, EventEffect::Nothing)),
                "seed {seed}: neither blessing is free -- the run would have to start with a loss"
            );
        }

        // And a wounded hero *is* offered a heal again (the filter is about the state, not the pool).
        let mut run = RunState::new(7, 80, 0, &["strike"; 10]).expect("a run");
        run.adjust_health(-40);
        let mut seen = false;
        for _ in 0..16 {
            run.pending = Pending::None;
            run.offer_start_choice().expect("offers");
            if run
                .start_offers()
                .expect("a pending choice")
                .iter()
                .any(|offer| matches!(offer.gain, EventEffect::Heal(_)))
            {
                seen = true;
                break;
            }
        }
        assert!(seen, "a wounded hero must still be able to be offered a heal");
    }

    /// **Each act draws its own map** (`port-plan.md` §131): advancing the act regenerates the map
    /// from a seed folded with the act number, and act 1 keeps the opening seed.
    #[test]
    fn advancing_the_act_draws_a_new_map() {
        let mut run = ironclad();
        let act_one_seed = run.act_seed();
        assert_eq!(act_one_seed, run.seed(), "act 1 keeps the run seed");
        let act_one_map = *run.map();

        // The walk to the boss, then the act changes.
        let first = run.reachable().get(0).expect("floor 1");
        run.enter_node(first).expect("floor 1");
        run.mark_boss_beaten();

        assert_eq!(run.act(), 2);
        assert!(!run.map_generation_failed(), "the new map must generate");
        assert_ne!(run.act_seed(), act_one_seed, "act 2 folds the seed");
        let act_two_map = *run.map();
        assert_ne!(
            act_one_map, act_two_map,
            "act 2 must not replay act 1's map"
        );

        // ...and it is deterministic: a second run with the same seed draws the same act-2 map.
        let mut twin = ironclad();
        let first = twin.reachable().get(0).expect("floor 1");
        twin.enter_node(first).expect("floor 1");
        twin.mark_boss_beaten();
        assert_eq!(*twin.map(), act_two_map, "same seed, same act-2 map");
    }

    /// **Killing an act's boss advances the act** instead of ending the run; only the last act's
    /// boss wins. Health, deck and relics carry across; the walk starts over.
    #[test]
    fn the_boss_of_an_act_advances_instead_of_ending_the_run() {
        let mut run = ironclad();
        assert_eq!(run.act(), 1, "a run starts in act 1");
        let deck = run.deck_len;
        let hp = run.health();

        // Act 1's boss falls: act 2 begins at the first row.
        run.enter_node(run.reachable().get(0).unwrap()).expect("floor 1");
        run.mark_boss_beaten();
        assert_eq!(run.act(), 2, "the act advanced");
        assert!(!run.boss_beaten(), "the run is not won yet");
        assert_eq!(run.floor(), 0, "the walk starts over");
        assert_eq!(run.node(), -1, "and the cursor is off the map");
        assert_eq!(run.deck_len, deck, "the deck carries across");
        assert_eq!(run.health(), hp, "and so does the health");

        // Act 2's boss: act 3.
        run.mark_boss_beaten();
        assert_eq!(run.act(), 3);
        assert!(!run.boss_beaten());

        // The last act's boss wins the run.
        run.mark_boss_beaten();
        assert_eq!(run.act(), 3, "no act beyond the last");
        assert!(run.boss_beaten(), "the run is won");
    }

    /// **You cannot walk on before settling the node you are on.** Found by clicking: step onto a
    /// fight, then step onto the next node, and the fight never happens.
    /// `inv:§9.3`: a won fight drops a potion from 40% of fights, taking it lands it on the belt, and
    /// a **full belt refuses loudly** rather than quietly dropping what the player was offered.
    /// Dropping a potion keeps the order of the survivors, and dropping what is not there is an
    /// error rather than a no-op -- the same discipline as `remove_card`.
    #[test]
    fn dropping_a_potion_keeps_the_order_of_the_survivors() {
        let mut run = ironclad();
        for id in ["fire_potion", "block_potion", "energy_potion"] {
            run.push_potion(id).expect("space");
        }
        assert_eq!(run.potions().len(), 3);
        run.drop_potion(1).expect("drop the middle one");
        let left: Vec<&str> = run.potions().iter().map(|id| id.as_str()).collect();
        assert_eq!(left, vec!["fire_potion", "energy_potion"]);
        run.drop_potion(1).expect("drop the last one");
        let left: Vec<&str> = run.potions().iter().map(|id| id.as_str()).collect();
        assert_eq!(left, vec!["fire_potion"]);
        assert_eq!(
            run.drop_potion(1),
            Err(RunError::NoSuchPotion),
            "there is no slot 1 any more"
        );
        assert_eq!(
            run.drop_potion(0).is_ok(),
            true,
            "the last one can go too"
        );
        assert_eq!(run.potions().len(), 0);
        assert_eq!(run.drop_potion(0), Err(RunError::NoSuchPotion));
    }

    #[test]
    fn a_won_fight_drops_a_potion_and_the_belt_takes_it() {
        let pool = [
            PoolPotion {
                id: "fire_potion",
                rarity: Rarity::Common,
            },
            PoolPotion {
                id: "block_potion",
                rarity: Rarity::Common,
            },
            PoolPotion {
                id: "energy_potion",
                rarity: Rarity::Uncommon,
            },
        ];
        // §157: the chance **moves** (-10/+10), so "about 40% over 400 rolls" is no longer the
        // promise -- the promise is "at 100 it always drops, at 0 it never does". The rate walk has
        // its own test (`the_potion_chance_walks_the_wikis_ten_percent`).
        let mut run = ironclad();
        run.potion_chance = 100;
        run.roll_reward(&basic_pool(), &pool, &[], FightKind::Normal)
            .expect("a reward");
        let offered = run.reward_potion().expect("at 100% it must drop").to_string();
        assert!(
            ["fire_potion", "block_potion", "energy_potion"].contains(&offered.as_str()),
            "{offered} is not in the pool"
        );
        assert_eq!(run.potion_drop_chance(), 90, "a drop moves the chance down by 10");

        // Taking it lands on the belt and consumes the offer.
        let belt_before = run.potions().len();
        run.take_potion().expect("take it");
        assert_eq!(run.potions().len(), belt_before + 1, "the potion is on the belt");
        assert_eq!(run.reward_potion(), None, "the offer is consumed");
        assert_eq!(
            run.take_potion(),
            Err(RunError::NoSuchPotion),
            "taking it twice is refused"
        );

        // At 0% nothing drops, and the chance walks back up.
        let mut run = ironclad();
        run.potion_chance = 0;
        run.roll_reward(&basic_pool(), &pool, &[], FightKind::Normal)
            .expect("a reward");
        assert_eq!(run.reward_potion(), None, "at 0% nothing drops");
        assert_eq!(run.potion_drop_chance(), 10, "a miss moves the chance up by 10");
    }

    #[test]
    fn you_cannot_walk_on_before_settling() {
        let mut run = ironclad();
        let first = run.reachable().get(0).unwrap();
        run.enter_node(first).expect("step onto the first node");
        let next = run.reachable().get(0).unwrap();
        assert_eq!(
            run.enter_node(next),
            Err(RunError::NodeNotSettled),
            "walking away from an unsettled node must be refused"
        );
        assert_eq!(run.node(), i32::from(first), "and the cursor must not move");

        // Settle it the way a finished fight does, and now the step is legal.
        run.mark_resolved();
        assert_eq!(run.enter_node(next), Ok(()));
        assert_eq!(run.node(), i32::from(next));
    }

    #[test]
    fn a_node_pays_once() {
        let mut run = ironclad();
        assert!(walk_to(&mut run, NodeKind::Rest));
        assert!(!run.node_resolved(), "a fresh node is not resolved");
        run.begin_node(&basic_pool(), &RELICS).expect("a rest site");
        run.rest().expect("rest");
        assert!(run.node_resolved());

        // The second visit is refused rather than healed again.
        assert_eq!(
            run.begin_node(&basic_pool(), &RELICS),
            Err(RunError::NodeResolved)
        );
        assert_eq!(run.rest(), Err(RunError::WrongPhase));

        // A different node is still fine.
        assert!(walk_to(&mut run, NodeKind::Combat));
        assert!(!run.node_resolved());
        assert_eq!(run.begin_node(&basic_pool(), &RELICS), Ok(NodeKind::Combat));
    }

    #[test]
    fn the_size_tripwire_reports_its_headroom() {
        let (bytes, headroom) = state_fits_the_tripwire();
        // The exact number is printed by the caller, not duplicated here; what this test pins is
        // that the bound holds and that the two numbers agree.
        assert_eq!(bytes, RunState::size_bytes());
        assert_eq!(bytes + headroom, RUN_STATE_TRIPWIRE_BYTES);
        // A sanity floor: 60 cards + 24 relics are already 3.4 KiB, so a much smaller struct would
        // mean a container silently vanished.
        assert!(bytes > 3_500, "RunState is only {bytes} B -- did a container disappear?");
    }

    /// The map this state walks must be one the map validator accepts -- the run layer must not be
    /// able to hold a map the map layer would reject.
    #[test]
    fn the_map_inside_a_run_passes_the_map_validator() {
        let run = ironclad();
        assert_eq!(run.map().check(), Ok(()));
        for row in 0..ROWS {
            if let Some(first) = run.map().row_first(row) {
                for node in run.map().row(row).unwrap().nodes() {
                    let _ = node;
                }
                assert!(first < 90, "global indices must stay inside a u8");
            }
        }
        // Every reachable node really is on the map, and its kind is rolled (never `Unassigned`).
        let mut run = run;
        let start = run.reachable().get(0).unwrap();
        run.enter_node(start).unwrap();
        for index in 0..run.reachable().len() {
            let node = run.reachable().get(index).unwrap();
            let (row, local) = run.map().locate(node).unwrap();
            let kind = run.map().row(row).unwrap().node(local).unwrap().kind;
            assert_ne!(kind, NodeKind::Unassigned);
        }
    }

    // =============================================================================================
    // §143：事件的关闭词表
    // =============================================================================================

    /// A pool with one **Curse** and one **Status**: the two rarities a `curse:` payload could
    /// plausibly name, and the difference the check has to see.
    fn curse_pool() -> [PoolCard<'static>; 7] {
        [
            PoolCard { id: "strike", rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "defend", rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "bash", rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "injury", rarity: Rarity::Curse, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "slimed", rarity: Rarity::Status, kind: CardKind::Other, upgraded: None },
            PoolCard { id: "c1", rarity: Rarity::Common, kind: CardKind::Other, upgraded: None },
            // §229: an upgrade looks the next row up in the pool (no more blind `+` append).
            PoolCard { id: "strike+", rarity: Rarity::Basic, kind: CardKind::Other, upgraded: None },
        ]
    }

    #[test]
    fn the_event_vocabulary_parses_and_refuses_what_it_does_not_know() {
        use EventEffect as E;
        // The five number effects keep their amounts.
        assert_eq!(E::parse("heal", 15), Some((E::Heal(15), None)));
        assert_eq!(E::parse("gold", 45), Some((E::Gold(45), None)));
        assert_eq!(E::parse("damage", 7), Some((E::LoseHealth(7), None)));
        assert_eq!(E::parse("max_hp", 6), Some((E::GainMaxHealth(6), None)));
        assert_eq!(E::parse("nothing", 0), Some((E::Nothing, None)));
        // The three deck edits need no payload of their own.
        assert_eq!(E::parse("remove_card", 0), Some((E::RemoveCard, None)));
        assert_eq!(E::parse("upgrade_card", 0), Some((E::UpgradeCard, None)));
        assert_eq!(E::parse("transform_card", 0), Some((E::TransformCard, None)));
        // The two that name something.
        assert_eq!(
            E::parse("curse:injury", 0),
            Some((E::GainCurse, Some("injury")))
        );
        assert_eq!(
            E::parse("relic:burning_blood", 0),
            Some((E::GainRelic, Some("burning_blood")))
        );
        // Outside the vocabulary -- **all of these must be `None`**, not "a guess":
        for bad in [
            "curse",            // no id: the id is the whole point
            "relic",
            "curse:",           // empty payload
            "relic:",
            "card:injury",      // no such kind
            "curse:injury:x",   // the id itself contains ':' -- only the first ':' splits
            "blessing",         // a plausible-looking word that is not in the table
            "",
        ] {
            if bad == "curse:injury:x" {
                // Splitting once is deliberate: the payload is `injury:x`, which is a card id
                // nobody has. The *parse* accepts it; the pool check is what refuses it.
                assert_eq!(
                    E::parse(bad, 0),
                    Some((E::GainCurse, Some("injury:x"))),
                    "only the first ':' splits"
                );
                continue;
            }
            assert_eq!(E::parse(bad, 1), None, "{bad:?} must be outside the vocabulary");
        }
        // `deck_change` is the bridge to the shared editor.
        assert_eq!(E::RemoveCard.deck_change(), Some(DeckChange::Remove));
        assert_eq!(E::UpgradeCard.deck_change(), Some(DeckChange::Upgrade));
        assert_eq!(E::TransformCard.deck_change(), Some(DeckChange::Transform));
        assert_eq!(E::Heal(3).deck_change(), None);
    }

    #[test]
    fn an_event_that_edits_the_deck_owes_a_pick_first() {
        let pool = curse_pool();
        // Remove
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("ancient_forge", "ancient_forge").expect("opening the event");
        assert_eq!(run.pending(), Pending::Event);
        run.resolve_event(EventEffect::RemoveCard, None, &pool)
            .expect("taking 'remove a card'");
        assert_eq!(run.pending(), Pending::EventCard, "the pick is still owed");
        assert_eq!(run.event_follow_up(), Some(DeckChange::Remove));
        assert_eq!(run.deck_len, 5, "nothing leaves the deck until a card is named");
        run.pick_event_card(2, &pool).expect("removing the third card");
        assert_eq!(run.pending(), Pending::None);
        assert_eq!(run.deck_len, 4);
        assert_eq!(run.event_follow_up(), None);

        // Upgrade
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("ancient_forge", "ancient_forge").expect("opening the event");
        run.resolve_event(EventEffect::UpgradeCard, None, &pool)
            .expect("taking 'upgrade a card'");
        run.pick_event_card(1, &pool).expect("upgrading the second card");
        assert_eq!(run.deck[1].as_str(), "strike+");
        assert_eq!(run.deck_len, 5, "upgrading does not change the size");

        // Transform: same size, and every entry is a real pool card.
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("ancient_forge", "ancient_forge").expect("opening the event");
        run.resolve_event(EventEffect::TransformCard, None, &pool)
            .expect("taking 'transform a card'");
        run.pick_event_card(0, &pool).expect("transforming the first card");
        assert_eq!(run.deck_len, 5, "transform keeps the size");
        // ⚠️ **同一张牌回来是合法的**（池子抽到同一个 id）。所以这里断言的不是"变了"，
        // 而是"整副牌仍然都是池子里的真卡" —— 后者才是这条路径可能坏掉的地方
        // （抽到空 id / 抽到池子外的 id 都不会让尺寸变化）。
        for card in run.deck() {
            let id = card.as_str();
            assert!(
                pool.iter().any(|entry| entry.id == id),
                "transform put {id:?} in the deck, which is not in the pool"
            );
        }
    }

    /// §188: one option, two effects -- the "relic **and** curse" pair the gap doc named in §143.
    #[test]
    fn an_event_option_can_apply_several_effects_at_once() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol", "golden_idol").expect("opening the event");
        let gold_before = run.gold();
        let deck_before = run.deck_len;

        run.resolve_event_effects(
            &EventMove {
                effects: &[
                    (EventEffect::GainRelic, Some("golden_idol")),
                    (EventEffect::GainCurse, Some("injury")),
                    (EventEffect::Gold(7), None),
                ],
                ..EventMove::none()
            },
            &pool,
        )
        .expect("the list applies");

        assert_eq!(run.gold(), gold_before + 7, "the gold half landed");
        assert_eq!(run.deck_len, deck_before + 1, "the curse half landed");
        assert!(
            run.deck().iter().any(|card| card.as_str() == "injury"),
            "the deck holds the curse"
        );
        assert_eq!(run.pending(), Pending::None, "no pick is owed");
    }

    /// §285：**概率分支**的两侧 + 同种子可复现。
    ///
    /// `Chance = 1` ⇒ 永远失败；`Chance = 100` ⇒ 永远成功；中间的 50 ⇒ 扫 32 个种子必须
    /// **两侧都出现**（只测一侧的话，"永远成功"与"永远失败"都能通过）。
    #[test]
    fn an_event_roll_takes_both_branches() {
        let pool = curse_pool();
        // 事件的段 id 不需要真的存在于内容里：运行层只把它们当**名字**（§278 的纪律：
        // run 层不读内容）。所以这里能直接摆一个两段事件。
        let run_to = |seed: i32, chance: u8| -> std::string::String {
            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.begin_event("probe", "probe").expect("the event opens");
            run.resolve_event_effects(
                &EventMove {
                    branches: &[(chance, "probe.success"), (100 - chance, "probe.fail")],
                    ..EventMove::none()
                },
                &pool,
            )
            .expect("the roll resolves");
            std::string::String::from(run.event_step())
        };

        for seed in 0..8 {
            assert_eq!(run_to(seed, 1), "probe.fail", "1% never succeeds (seed {seed})");
            assert_eq!(run_to(seed, 100), "probe.success", "100% always succeeds (seed {seed})");
        }

        let mut successes = 0;
        let mut failures = 0;
        for seed in 0..32 {
            if run_to(seed, 50) == "probe.success" {
                successes += 1;
            } else {
                failures += 1;
            }
        }
        assert!(
            successes > 0 && failures > 0,
            "50% over 32 seeds must take **both** branches, got {successes} success / {failures} fail"
        );
        // 同种子 ⇒ 同结果（掷骰走的是 RunState 自己的流，跟着种子走）。
        assert_eq!(run_to(7, 50), run_to(7, 50), "the same seed must roll the same way");
    }

    /// §285：`gold_random:<min>:<max>` —— 区间**两端都到过**，且同种子同一个数。
    #[test]
    fn gold_random_stays_inside_its_range_and_covers_it() {
        let pool = curse_pool();
        let gained = |seed: i32| -> i32 {
            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.begin_event("probe", "probe").expect("the event opens");
            let before = run.gold();
            run.resolve_event_effects(
                &EventMove { effects: &[(EventEffect::GoldRandom(20, 50), None)], next: None, ..EventMove::none() },
                &pool,
            )
            .expect("the range resolves");
            run.gold() - before
        };
        let mut seen_low = false;
        let mut seen_high = false;
        for seed in 0..64 {
            let amount = gained(seed);
            assert!(
                (20..=50).contains(&amount),
                "seed {seed} gained {amount}, outside 20..=50"
            );
            if amount == 20 {
                seen_low = true;
            }
            if amount >= 48 {
                seen_high = true;
            }
        }
        assert!(seen_low, "the low end of the range never came up");
        assert!(seen_high, "the high end of the range never came up");
        assert_eq!(gained(7), gained(7), "the same seed must give the same amount");

        // 负区间 = 扣钱，且被 clamps 在 0（wiki: "never more than the Gold you are carrying"）。
        let mut run = RunState::new(7, 80, 10, &["strike"; 5]).expect("a run with 10 gold");
        run.begin_event("probe", "probe").expect("the event opens");
        run.resolve_event_effects(
            &EventMove { effects: &[(EventEffect::GoldRandom(-20, -50), None)], next: None, ..EventMove::none() },
            &pool,
        )
        .expect("the range resolves");
        assert_eq!(run.gold(), 0, "a 20-50 loss from 10 gold leaves zero, not negative");
    }

    /// §286：**进入效果**在**到达**目标段时兑，而且和选项效果同一个事务。
    #[test]
    fn entry_effects_land_on_arrival_and_roll_back_together() {
        let pool = curse_pool();
        let entry: [(EventEffect, Option<&str>); 1] = [(EventEffect::Gold(30), None)];
        let table: [(&str, &[(EventEffect, Option<&str>)]); 1] = [("probe.next", &entry)];
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("probe", "probe").expect("the event opens");
        let gold_before = run.gold();
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::Gold(5), None)],
                next: Some("probe.next"),
                entry: &table,
                ..EventMove::none()
            },
            &pool,
        )
        .expect("the move lands");
        assert_eq!(run.event_step(), "probe.next", "we are standing on the target step");
        assert_eq!(
            run.gold(),
            gold_before + 35,
            "the option's 5 and the step's 30 both landed on arrival"
        );

        // 进入效果里有一条付不起的钱 ⇒ **整个**事务回滚（选项那 5 也没了）。
        let mut poor = RunState::new(7, 80, 3, &["strike"; 5]).expect("a poor run");
        poor.begin_event("probe", "probe").expect("the event opens");
        let before = poor;
        let pricey: [(EventEffect, Option<&str>); 1] = [(EventEffect::GoldCost(10), None)];
        let table_pricey: [(&str, &[(EventEffect, Option<&str>)]); 1] = [("probe.next", &pricey)];
        let outcome = poor.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::Gold(5), None)],
                next: Some("probe.next"),
                entry: &table_pricey,
                ..EventMove::none()
            },
            &pool,
        );
        assert_eq!(outcome, Err(RunError::NotEnoughGold { price: 10, gold: 8 }),
                   "the entry effect is paid **after** the option's gold, then refused");
        assert!(poor == before, "not one byte moved: the +5 was rolled back too");
    }

    /// §286：**四选一**的权重表 —— 每一档都必须到过，同种子同结果。
    #[test]
    fn a_four_way_branch_reaches_every_branch() {
        let pool = curse_pool();
        let table = [
            (25u8, "probe.a"),
            (25, "probe.b"),
            (25, "probe.c"),
            (25, "probe.d"),
        ];
        let mut seen = [false; 4];
        for seed in 0..64 {
            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.begin_event("probe", "probe").expect("the event opens");
            run.resolve_event_effects(
                &EventMove { branches: &table, ..EventMove::none() },
                &pool,
            )
            .expect("the roll resolves");
            let slot = match run.event_step() {
                "probe.a" => 0,
                "probe.b" => 1,
                "probe.c" => 2,
                "probe.d" => 3,
                other => panic!("landed on {other}, which is not a branch"),
            };
            seen[slot] = true;
        }
        assert!(seen.iter().all(|hit| *hit), "64 seeds must reach all four: {seen:?}");
    }

    /// §286：**事件把房间变成一场战斗** —— 档位记下来、事件收尾、节点**不**结算；
    /// 而 `mark_resolved` 是唯一清它的地方。
    #[test]
    fn an_event_can_turn_the_room_into_a_fight() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        // 得先站在一个真实的 `?` 节点上：`node_resolved` 说的是**地图节点**，
        // 没有节点时它恒为 false，那样这条判据会空过。
        assert!(walk_to(&mut run, NodeKind::Unknown), "a `?` node must exist");
        run.begin_node(&pool, &[]).expect("the node opens");
        run.begin_event("dead_adventurer", "dead_adventurer")
            .expect("the event opens");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::Gold(30), None)],
                fight: 2,
                ..EventMove::none()
            },
            &pool,
        )
        .expect("the ambush resolves");

        assert_eq!(run.event_fight(), 2, "the band is recorded for the caller");
        assert_eq!(run.event(), "", "the event is over -- the fight is what happens now");
        assert_eq!(run.pending(), Pending::None, "nothing is waiting on a choice");
        assert!(!run.node_resolved(), "the node is **not** settled: the fight settles it");
        assert_eq!(run.gold(), 30, "the effects still landed");

        run.mark_resolved();
        assert_eq!(run.event_fight(), 0, "settling the node clears the band");
        assert!(run.node_resolved());
    }

    /// §287：**战后补偿**（`Dead Adventurer`）—— 金币欠账 +30、遗物欠账"不掉"，
    /// 而且**只消费一次**（第二场战斗不再受影响）。
    #[test]
    fn the_fight_reward_debt_is_paid_once() {
        let cards = curse_pool();
        let relics = [
            PoolRelic { id: "anchor", rarity: Rarity::Common },
            PoolRelic { id: "vajra", rarity: Rarity::Common },
        ];
        let mut run = RunState::new(7, 80, 100, &["strike"; 5]).expect("a run");
        run.begin_event("dead_adventurer", "dead_adventurer").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[
                    (EventEffect::FightGoldBonus(30), None),
                    (EventEffect::FightNoRelic, None),
                ],
                ..EventMove::none()
            },
            &cards,
        )
        .expect("the debt is recorded");

        let (low, high) = reward_bands(FightKind::Elite, run.rarity_offset());
        // 第一场：欠账**就在这一场**付掉。
        run.roll_reward(&cards, &[], &relics, FightKind::Elite)
            .expect("the elite pays out");
        let gold = run.reward_gold();
        assert!(
            gold >= low + 30 && gold <= high + 30,
            "the elite's {low}..={high} plus the 30-gold debt, got {gold}"
        );
        assert_eq!(run.reward_relic(), None, "the relic debt says `no relic`");

        // 第二场：欠账已经付过 ⇒ 一次正常结算（有遗物、没有 +30）。
        run.roll_reward(&cards, &[], &relics, FightKind::Elite)
            .expect("the second elite pays out");
        assert!(run.reward_relic().is_some(), "the second fight pays its relic");
        let (low2, high2) = reward_bands(FightKind::Elite, run.rarity_offset());
        assert!(
            run.reward_gold() >= low2 && run.reward_gold() <= high2,
            "no debt left: {} must be inside {low2}..={high2}",
            run.reward_gold()
        );
    }

    /// §287：**开一个事件就清掉欠账** —— 否则上一次事件的金币会漏进下一场战斗。
    #[test]
    fn opening_an_event_clears_the_debt() {
        let cards = curse_pool();
        let relics = [PoolRelic { id: "anchor", rarity: Rarity::Common }];
        let mut run = RunState::new(7, 80, 100, &["strike"; 5]).expect("a run");
        run.begin_event("dead_adventurer", "dead_adventurer").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::FightGoldBonus(30), None)],
                ..EventMove::none()
            },
            &cards,
        )
        .expect("the debt is recorded");
        // 另一个事件开始了：欠账属于**上一个**事件。
        run.begin_event("scrap_pile", "scrap_pile").expect("the next event");
        run
            .roll_reward(&cards, &[], &relics, FightKind::Elite)
            .expect("the elite pays out");
        let (low, high) = reward_bands(FightKind::Elite, run.rarity_offset());
        assert!(
            run.reward_gold() <= high,
            "the old debt must not leak: {} is above {high}",
            run.reward_gold()
        );
        assert!(run.reward_gold() >= low);
    }

    /// §278：事件是**一棵树** —— 走完一段不结算，走完最后一段才结算。
    #[test]
    fn an_event_tree_advances_one_step_at_a_time() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol", "golden_idol").expect("open the event");
        assert_eq!(run.event_step(), "golden_idol", "the run starts on the entry step");
        assert_eq!(run.pending(), Pending::Event);

        // ── 第一段：拿到遗物，**并且**被带去下一段。
        run.resolve_event_effects(
            &EventMove { effects: &[(EventEffect::GainRelic, Some("golden_idol"))], next: Some("golden_idol.boulder"), ..EventMove::none() },
            &pool,
        )
        .expect("taking the idol");
        assert_eq!(
            run.event_step(),
            "golden_idol.boulder",
            "the run must be standing on the **second** step now"
        );
        assert_eq!(
            run.pending(),
            Pending::Event,
            "the room is **not** settled: there is another step"
        );
        // 房间有没有"结算"在无节点的会话里问不出来（`node_resolved` 对 `node < 0` 恒 false），
        // 所以判据用**相位**：这一段还开着，就能再选一次。
        assert_eq!(run.pending(), Pending::Event, "still open for the next step");

        // ── 第二段：百分比扣血，然后收尾。
        let hp_max = run.health_max();
        let post_before = run.health_max;
        assert_eq!(post_before, hp_max);
        let hp_before = run.health();
        run.resolve_event_effects(
            &EventMove { effects: &[(EventEffect::LoseHealthPercent(250), None)], next: None, ..EventMove::none() },
            &pool,
        )
        .expect("smashing the boulder");
        assert_eq!(
            run.health(),
            hp_before - (hp_max * 25 / 100),
            "Smash takes floor(max HP × 25%)"
        );
        assert_eq!(run.health_max(), hp_max, "Smash does not touch the maximum");
        assert_eq!(run.event_step(), "", "the step is cleared when the tree ends");
        assert_eq!(run.pending(), Pending::None, "nothing is owed");
        // 「收尾了」的判据是**相位关了**：再选一次必须被拒（无节点的会话问不出 `node_resolved`）。
        assert_eq!(
            run.resolve_event_effects(&EventMove { effects: &[], next: None, ..EventMove::none() }, &pool),
            Err(RunError::WrongPhase),
            "a second choice after the tree ended is a phase error"
        );
    }

    /// §278：`max_hp_pct` 扣的是**上限**，并且当前 HP 跟着夹住；下限是 1。
    #[test]
    fn losing_max_health_by_percent_never_goes_below_one() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol", "golden_idol.boulder").expect("the boulder");
        let before = run.health_max();
        run.resolve_event_effects(&EventMove { effects: &[(EventEffect::LoseMaxHealthPercent(80), None)], next: None, ..EventMove::none() }, &pool)
            .expect("hiding");
        assert_eq!(run.health_max(), before - (before * 8 / 100), "8% of max, floored");
        assert!(
            run.health() <= run.health_max(),
            "the current HP must be clamped to the new maximum"
        );
        // 1 HP 的上限也只会掉 1（下限 1），不会掉到 0 或负数。
        let mut tiny = RunState::new(7, 1, 0, &["strike"; 5]).expect("a 1 HP run");
        tiny.begin_event("golden_idol", "golden_idol.boulder").expect("the boulder");
        tiny.resolve_event_effects(&EventMove { effects: &[(EventEffect::LoseMaxHealthPercent(500), None)], next: None, ..EventMove::none() }, &pool)
            .expect("hiding");
        // 损失 = max(1, floor(1 × 50%)) = 1，但上限**夹在 1**（0 上限会让下一次百分比
        // 永远算出 0 伤害）。
        assert_eq!(tiny.health_max(), 1, "max HP never reaches 0");
        assert!(tiny.health() >= 0, "HP never goes negative");
    }

    /// §280：**付不起就拒绝，不是扣到 0 为止**。
    ///
    /// `adjust_gold(-75)` 会把 50 金币夹成 0 —— 玩家**白拿了服务**，而屏幕上一切正常
    /// （这正是 `gold_cost` 存在的理由）。判据是"整份局面不动一个字节"。
    #[test]
    fn paying_more_gold_than_you_have_is_refused_not_clamped() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 20, &["strike"; 5]).expect("a run with 20 gold");
        run.begin_event("the_cleric", "the_cleric").expect("the event");
        let before = run;
        let outcome = run.resolve_event_effects(
            &EventMove { effects: &[(EventEffect::GoldCost(35), None), (EventEffect::HealPercent(250), None)], next: None, ..EventMove::none() },
            &pool,
        );
        assert_eq!(
            outcome,
            Err(RunError::NotEnoughGold { price: 35, gold: 20 }),
            "a cost you cannot pay is refused"
        );
        assert!(run == before, "and the heal does not land either");
        // 付得起的时候：金币真的少了、血真的回了 25%（`250` 千分 = 25%）。
        let mut rich = RunState::new(7, 80, 100, &["strike"; 5]).expect("a rich run");
        rich.begin_event("the_cleric", "the_cleric").expect("the event");
        rich.adjust_health(-40);                      // 40/80 = 50%
        rich.resolve_event_effects(
            &EventMove { effects: &[(EventEffect::GoldCost(35), None), (EventEffect::HealPercent(250), None)], next: None, ..EventMove::none() },
            &pool,
        )
        .expect("35 gold is affordable");
        assert_eq!(rich.gold(), 65, "35 gold left the purse");
        assert_eq!(rich.health(), 60, "40 + floor(80 × 25%)");
    }

    /// §280：`heal_full` 回的是**当前上限**（不是写死的 999），而且上限后来变了它还成立。
    #[test]
    fn heal_full_reaches_the_current_maximum() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.adjust_health(-50);                       // 30/80
        run.begin_event("the_moai_head", "the_moai_head").expect("the event");
        run.resolve_event_effects(&EventMove { effects: &[(EventEffect::HealFull, None)], next: None, ..EventMove::none() }, &pool)
            .expect("jump inside");
        assert_eq!(run.health(), run.health_max, "heal_full reaches the maximum");
    }

    /// §280：`max_hp_pct:12.5` —— 千分单位存在的理由。
    ///
    /// 80 上限的 12.5% = 10 HP。整数百分比会把它算成 9（12%）或 10（13%，那是另一个数），
    /// 所以这条判据钉的是"小数真的进了计算"，而不只是"解析接受 12.5"。
    #[test]
    fn a_fractional_percentage_reaches_the_arithmetic() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("the_moai_head", "the_moai_head").expect("the event");
        let before = run.health_max();
        run.resolve_event_effects(&EventMove { effects: &[(EventEffect::LoseMaxHealthPercent(125), None)], next: None, ..EventMove::none() }, &pool)
            .expect("the moai head");
        assert_eq!(run.health_max(), before - 10, "12.5% of 80 is exactly 10");
        // 解析层：`12.5` 与 `12` 必须是两个不同的数（一个拼写错误不该被悄悄接受成整数）。
        assert_eq!(EventEffect::parse("max_hp_pct:12.5", 0), Some((EventEffect::LoseMaxHealthPercent(125), None)));
        assert_eq!(EventEffect::parse("max_hp_pct:12", 0), Some((EventEffect::LoseMaxHealthPercent(120), None)));
        // 两位小数、`12.`、`100.5` 都是词表外。
        assert_eq!(EventEffect::parse("max_hp_pct:12.55", 0), None);
        assert_eq!(EventEffect::parse("max_hp_pct:12.", 0), None);
        assert_eq!(EventEffect::parse("max_hp_pct:100.5", 0), None);
        assert_eq!(EventEffect::parse("max_hp_pct:0", 0), None);
    }

    /// §278：`next` **形状不合法**时，整个事件不动一个字节（含 `event_step`）。
    ///
    /// ⚠️ 这一条只可能拒"形状"，不可能拒"这个段不存在" —— run 层**不读内容**（§133 的纪律）。
    /// "`Next` 指向一个不存在的段"由**内容门**拒（`sts_content_check` 的 `[6c]`：入口段必须
    /// 在表里、`Next` 必须在表里、而且每个段都要可达）。两层各拒各的，谁也不猜对方的。
    #[test]
    fn a_malformed_next_step_is_refused_before_anything_moves() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol", "golden_idol").expect("the event");
        let before = run;
        let outcome = run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::Gold(30), None)],
                // `Ident::new` 只拒两种东西：**非 ASCII** 与**超长**（空格、点、大写都合法的）。
                // 所以"形状不合法"这条判据只能用非 ASCII 的例子。
                next: Some("巨石"),
                ..EventMove::none()
            },
            &pool,
        );
        assert_eq!(outcome, Err(RunError::NoSuchEvent), "a malformed step id is refused");
        assert!(run == before, "not one byte moved (the gold did not land either)");
    }

    /// §188: a list that fails **in the middle** must not half-apply.
    ///
    /// The second entry is a curse naming a card the pool does not know, which `apply_event_effect`
    /// refuses; the gold from the first entry must be rolled back with it.
    #[test]
    fn a_failing_effect_rolls_the_whole_list_back() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol", "golden_idol").expect("the event");
        let before = run;

        let outcome = run.resolve_event_effects(
            &EventMove {
                effects: &[
                    (EventEffect::Gold(30), None),
                    (EventEffect::GainCurse, Some("no_such_curse")),
                ],
                ..EventMove::none()
            },
            &pool,
        );
        assert!(outcome.is_err(), "an unknown curse must be refused");
        // `RunState` is `Copy` and `PartialEq` precisely so this is one assertion, not a field list.
        assert!(run == before, "a refused list must not move a single byte");
    }

    /// §188: two deck edits cannot both be honoured (there is one pending pick), so they are refused
    /// rather than silently losing one.
    #[test]
    fn two_deck_edits_in_one_option_are_refused() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("ancient_forge", "ancient_forge").expect("the event");
        let before = run;
        let outcome = run.resolve_event_effects(
            &EventMove { effects: &[(EventEffect::RemoveCard, None), (EventEffect::UpgradeCard, None)], next: None, ..EventMove::none() },
            &pool,
        );
        assert_eq!(outcome, Err(RunError::TwoDeckChanges));
        assert!(run == before, "nothing was applied");
    }

    #[test]
    fn an_event_can_give_a_curse_but_only_a_real_one() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol", "golden_idol").expect("opening the event");
        run.resolve_event(EventEffect::GainCurse, Some("injury"), &pool)
            .expect("an event may hand you a curse");
        assert_eq!(run.deck_len, 6);
        assert_eq!(run.deck[5].as_str(), "injury");
        assert_eq!(run.pending(), Pending::None, "a curse needs no pick");

        // A payload that is not in the pool: **refused**, because a phantom id in the deck stays
        // invisible until the card is drawn.
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol", "golden_idol").expect("opening the event");
        assert_eq!(
            run.resolve_event(EventEffect::GainCurse, Some("regret"), &pool),
            Err(RunError::NoSuchCard)
        );
        assert_eq!(run.deck_len, 5, "a refused effect changes nothing");

        // A `curse:` payload naming a card that is **not** a curse: same refusal.
        assert_eq!(
            run.resolve_event(EventEffect::GainCurse, Some("strike"), &pool),
            Err(RunError::NoSuchCard)
        );
        // No payload at all: outside the vocabulary.
        assert_eq!(
            run.resolve_event(EventEffect::GainCurse, None, &pool),
            Err(RunError::UnsupportedEventEffect)
        );
    }

    #[test]
    fn an_event_can_give_a_relic_only_if_the_kernel_can_run_it() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("old_shrine", "old_shrine").expect("opening the event");
        run.resolve_event(EventEffect::GainRelic, Some("burning_blood"), &pool)
            .expect("Burning Blood is implemented");
        assert_eq!(run.relics().len(), 1);
        assert_eq!(run.relics()[0].as_str(), "burning_blood");

        // An unimplemented relic is refused **while the event is open**, not at the end of the
        // next fight (`RunError::UnsupportedRelic` used to be reachable only there).
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("old_shrine", "old_shrine").expect("opening the event");
        assert_eq!(
            run.resolve_event(EventEffect::GainRelic, Some("no_such_relic"), &pool),
            Err(RunError::UnsupportedRelic { index: 0 })
        );
        assert_eq!(run.relics().len(), 0);
    }

    /// §189 `A10`：Ascender's Bane 在 10 级进牌组、9 级不进，而且进了就**删不掉**
    /// （wiki 卡面写着 "Cannot be removed"，StS 也把这条写在这张卡自己的代码里）。
    #[test]
    fn a10_starts_with_a_curse_that_cannot_be_removed() {
        for (level, want) in [(0u8, false), (9, false), (10, true), (20, true)] {
            let run =
                RunState::new_with_ascension(7, 80, 0, &["strike"; 5], level).expect("a run");
            let has = run.deck().iter().any(|card| card.as_str() == ASCENDERS_BANE);
            assert_eq!(has, want, "A{level}: Ascender's Bane in the deck must be {want}");
            assert_eq!(
                run.deck_len,
                5 + u8::from(want),
                "A{level}: exactly one extra card"
            );
        }

        // Removing it is refused, and the refusal changes nothing -- the price is not charged.
        let mut run =
            RunState::new_with_ascension(7, 80, 500, &["strike"; 5], 10).expect("a run");
        // The test lives in this module, so it can put the run straight into the shop phase, which is
        // the only thing `remove_card` checks before refusing.
        run.pending = Pending::Shop;
        let index = run
            .deck()
            .iter()
            .position(|card| card.as_str() == ASCENDERS_BANE)
            .expect("the curse is in the deck");
        let before = run;
        assert_eq!(run.remove_card(index), Err(RunError::CannotRemove));
        assert!(run == before, "a refused removal must not spend gold");
    }

    /// §189 `A12`：基线规则（二三幕 12% / 25%）与 A12 的减半。
    ///
    /// 基线以前**不存在**（第一幕的 0% 被实现成了"哪一幕都 0%"），所以这条测试也是"基线在那儿"
    /// 的证明：64 个种子里第三幕必须出现升级牌，第一幕一张都不许有。
    #[test]
    fn a12_halves_the_upgrade_chance_in_acts_two_and_three() {
        for (act, ascension, want) in [
            (1u8, 0u8, 0),
            (1, 20, 0),
            (2, 0, 12),
            (2, 11, 12),
            (2, 12, 6),
            (3, 0, 25),
            (3, 12, 12),
            (3, 20, 12),
        ] {
            assert_eq!(
                upgrade_chance_percent(act, ascension),
                want,
                "act {act} at A{ascension}"
            );
        }

        // Six base cards plus their `+` rows: a reward screen needs three **distinct** base cards, so
        // a two-card pool would fail with `PoolTooSmall` before the rule could be observed.
        let mut pool = std::vec::Vec::new();
        for id in ["strike", "defend", "anger", "bash", "clash", "flex"] {
            pool.push(PoolCard {
                id,
                rarity: Rarity::Common,
                kind: CardKind::Attack,
                upgraded: None,
            });
            pool.push(PoolCard {
                id: std::boxed::Box::leak(std::format!("{id}+").into_boxed_str()),
                rarity: Rarity::Common,
                kind: CardKind::Attack,
                upgraded: None,
            });
        }

        let mut upgraded_in_act3 = 0;
        let mut upgraded_in_act1 = 0;
        for seed in 0..64 {
            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.act = 3;
            run.roll_reward(&pool, &[], &[], FightKind::Normal)
                .expect("reward");
            upgraded_in_act3 += run
                .reward_cards()
                .iter()
                .filter(|id| id.as_str().ends_with('+'))
                .count();

            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.roll_reward(&pool, &[], &[], FightKind::Normal)
                .expect("reward");
            upgraded_in_act1 += run
                .reward_cards()
                .iter()
                .filter(|id| id.as_str().ends_with('+'))
                .count();
        }
        assert_eq!(upgraded_in_act1, 0, "act 1 never offers an upgraded card");
        assert!(
            upgraded_in_act3 > 0,
            "act 3 must offer upgraded cards (25%), got none in 64 seeds"
        );
    }

    /// §189 `A20`：最后一幕的第一个 Boss 倒下后节点**重新可打**，只有第二个才算赢。
    #[test]
    fn a20_makes_the_last_act_have_two_bosses() {
        let finish = |level: u8| -> (bool, bool, u8) {
            let mut run =
                RunState::new_with_ascension(7, 80, 0, &["strike"; 5], level).expect("a run");
            run.act = MAX_ACT;
            run.node = i32::from(crate::map::BOSS_NODE);
            // The caller's order is "roll the reward, then mark the boss" -- so the reward screen is
            // already open when this runs, and it must stay open (see the branch's comment).
            run.pending = Pending::Reward;
            run.mark_boss_beaten();
            assert_eq!(
                run.pending(),
                Pending::Reward,
                "A{level}: the fight's reward screen must survive"
            );
            if level >= A_DOUBLE_BOSS {
                assert!(!run.boss_beaten(), "A20: the first boss must not win the run");
                assert!(!run.node_resolved(), "A20: the boss node must be open again");
                run.pending = Pending::None;
                run.mark_boss_beaten();
            }
            (run.boss_beaten(), run.node_resolved(), run.act)
        };

        for level in [0u8, 19] {
            let (won, resolved, act) = finish(level);
            assert!(won, "A{level}: the last boss wins the run");
            assert!(resolved, "A{level}: the node stays settled");
            assert_eq!(act, MAX_ACT, "A{level}: no act past the last");
        }
        let (won, resolved, act) = finish(20);
        assert!(won, "A20: the second boss wins the run");
        assert!(resolved, "A20: and then the node settles");
        assert_eq!(act, MAX_ACT, "A20: still the last act");
    }

    #[test]
    fn a_deck_edit_event_on_an_empty_deck_is_refused() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &[]).expect("a run with no cards");
        run.begin_event("ancient_forge", "ancient_forge").expect("opening the event");
        assert_eq!(
            run.resolve_event(EventEffect::RemoveCard, None, &pool),
            Err(RunError::DeckEmpty)
        );
        assert_eq!(run.pending(), Pending::Event, "the event is still open");
    }

    #[test]
    fn the_two_pickers_cannot_finish_each_other() {
        let pool = curse_pool();
        // In the event's pick phase, the blessing picker refuses.
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("ancient_forge", "ancient_forge").expect("opening the event");
        run.resolve_event(EventEffect::RemoveCard, None, &pool)
            .expect("taking 'remove a card'");
        assert_eq!(
            run.pick_blessing_card(0, &pool),
            Err(RunError::WrongPhase),
            "the blessing picker must not complete an event"
        );
        assert_eq!(run.pending(), Pending::EventCard);

        // ... and in the blessing's, the event picker refuses.
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.pending = Pending::BlessingCard;
        run.blessing_follow = Some(BlessingFollowUp::Deck(DeckChange::Remove));
        assert_eq!(
            run.pick_event_card(0, &pool),
            Err(RunError::WrongPhase),
            "the event picker must not complete a blessing"
        );
        assert_eq!(run.pending(), Pending::BlessingCard);
    }
}
