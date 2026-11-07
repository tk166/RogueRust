//! `rd-wasm` — the `rd-core` combat kernel behind the **env ABI** (`docs/spec/env-abi.md`),
//! compiled to `wasm32-unknown-unknown` and driven from a plain static HTML page.
//!
//! # What this crate is
//!
//! A **spike**: it answers "can the browser UI speak the same protocol as the future RL
//! environment?", not "is this the product". So:
//!
//! * the **content** is real and comes out of the `sts` package (`content.sts.rdcf` -- the full
//!   image, not the core mirror: the card text lives in the cells the core build strips);
//!   the **fight** is built from it with `build_fight_from_content` — the deck is the content's
//!   own (`Characters[0].Start.Deck`) and the enemies are the content's own (`ENCT` encounter
//!   `enc_few_slimes`); the hero, the seed and "which encounter" are the only things this file
//!   picks. See [`IMAGE`] for why the `sts` mirror and not `roguedeck`'s.
//! * the exports are the ABI minus the handle parameter: one module instance = one environment.
//!   The frozen ABI is handle-based *because it wants 16+ environments in one process*; a
//!   browser page has exactly one fight on screen, so a single global session is the honest
//!   shape here. Turning it back into handles is mechanical (`Session` is already a struct).
//! * everything the kernel cannot answer is exported as `-1` and documented in §"Gaps" below,
//!   never filled with a plausible-looking zero.
//!
//! # Why `std` here and `no_std` there
//!
//! `rd-core` is `#![cfg_attr(not(test), no_std)]` and `#![forbid(unsafe_code)]`. This crate is
//! neither: `wasm32-unknown-unknown` has `std`, and something has to own the 184 KB
//! `CombatState` and the `&'static mut` session slot. The kernel is *not* modified — that
//! constraint is the whole point of the spike (if the ABI needed kernel changes, the spike
//! should say so rather than make them).
//!
//! # Gaps (what this ABI implementation does **not** do)
//!
//! 1. **No enemy *actions* chosen by the driver for heroes** (ABI kind 2): `FightPlan` has no
//!    `actions` field, so a hero self-action cannot be expressed.
//! 2. **No handle.** See above.
//! 3. **`upgraded` is always 0.** In this content "upgraded" is a *different card definition*,
//!    not a flag on an instance — `CardInstance` has no such bit.
//! 4. **`hero_ward` / `enemy.ward` are always `-1`.** No `ward` resource exists in the content
//!    image (the standard package's pool is `standard.block`); `-1` says "this implementation
//!    does not produce this quantity", which is the truth.
//! 5. **`intent_damage` is `-1` when the amount is not a literal.** The preview reads the
//!    `EACT` program and sums the `dealDamage` nodes whose `Amount` is `const`; an amount that
//!    depends on state (a `multiply`, a status modifier) is **not** guessed at.
//!
//! Two gaps closed in this round (they were gaps *here*, not in the kernel):
//! * **enemy intent** used to be `-1`; it is now `intent::locate_enemy` + `intent::select_action`
//!   over `content::Content::encounter_enemies`, with the damage read out of the `EACT` program.
//! * **one enemy per end-turn step**: `Session::step_end_turn` now drives
//!   `battle::Step::EndOneTurn` in a loop, so every enemy acts in its own turn before the hero
//!   gets the round back. The old "plan has N enemies" guard is gone because the reason for it
//!   is gone.

mod run;

use rd_core::battle::{
    build_fight_from_content, run_fight, standard_turn_config, start_first_turn, DeckEntry,
    FightOutcome, FightPlan,
    PlanCombatant, Step,
};
use rd_core::content::{
    Content, ABSENT16, EK_CARD, EK_ENCOUNTER, LIST_ABSENT, LIST_NULL, NULL16, OP_ARR,
};
use rd_core::host::Host;
use rd_core::intent::{enemy_action_program_root, locate_enemy, select_action, ActionChoice, IntentKind};
use rd_core::ir::NodeRef;
use rd_core::play::can_play_card;
use rd_core::state::{
    CardZone, ChoiceSource, ChoiceThen, CombatId, CombatResult, CombatState, CombatTurnPhase, CombatantId,
    CombatantLifecycleState, ResourceId,
};

// =============================================================================================
// The content image, and the little the spike still picks for itself
// =============================================================================================

/// Error-detail formatting, behind a build-time switch — and it is a **size lever**, not a taste
/// decision.
///
/// `{:?}` on the kernel's error types is the biggest single pull on `core::fmt` in this crate:
/// `BattleError` → `PlayError` → `exec::ExecError` → `ir::IrError` is a deep tree of variants, and
/// each one needs a `Debug` implementation instantiated and its formatting code linked. Build with
/// `--cfg rd_wasm_plain_errors` to drop the whole tree; the error channel still works (you get a
/// labelled reason and the message strings, minus the payload). The measured difference is in the
/// spike report — the point of the switch is that the number is reproducible rather than argued.
#[cfg(not(rd_wasm_plain_errors))]
pub(crate) fn detail<T: core::fmt::Debug>(value: &T) -> String {
    format!("{value:?}")
}

/// See the sibling above.
#[cfg(rd_wasm_plain_errors)]
pub(crate) fn detail<T: core::fmt::Debug>(_value: &T) -> String {
    // `T`'s `Debug` impl is never instantiated on this path, which is exactly how its code
    // disappears from the module. The bound stays so the call sites do not have to change.
    "<detail off>".to_string()
}

/// The content image, embedded at compile time: the **`sts` package's full image**, 11,140 B
/// (`tools/contentc/packages/sts/out/content.sts.rdcf`).
///
/// # Why the full image and not its core mirror (9,580 B)
///
/// The core mirror is the same content with the **human-facing strings stripped** — and those are
/// exactly what a card face needs. `CARD.NameKey` (cell 9) and `CARD.DescriptionKey` (cell 10) are
/// `ABSENT16` in the core build and carry `"Strike"` / `"Deal 6 damage."` in the full one, which
/// `card_text_tests::the_text_is_the_contents_own` pins. Measured: switching back to the core
/// mirror makes every card's title and description come back empty.
///
/// So this file pays **+1,560 B** for the card text, and it is the only reason it embeds the full
/// image. The kernel never reads those cells — the semantics are identical in both builds — so if a
/// day comes when the page stops needing the text, this one line goes back to the core mirror.
///
/// # Why this mirror and not `tools/contentc/out/content.core.rdcf` (85,616 B)
///
/// The two are different *content*, not two versions of one: `content.core.rdcf` is the
/// `roguedeck` package (188-ish cards, 109 encounters, 85,616 B), `content.sts.rdcf` is the
/// hand-authored Slay-the-Spire act-1 slice (4 cards, 3 encounters, 11,140 B). This crate is the
/// last metre of the pipeline "content → one fight → browser", and the content that has a
/// source document, an inventory and a four-layer gate behind it is the `sts` package. Embedding
/// it also removes **76,036 B** from the module: the `.wasm` is almost entirely the image plus
/// `CombatState`, so the image is the biggest single lever after the state itself.
///
/// What that costs: the fight is small (4 card definitions, 2 enemies, 1 act-1 encounter). What
/// it buys: every number on the page comes out of a document this repo can check, and the deck
/// is the document's own rather than a list typed here. If the demo ever needs the big content,
/// this is the one line to change — nothing else in the file knows which package it is looking at.
pub(crate) static IMAGE: &[u8] = include_bytes!("../../../tools/contentc/packages/sts/out/content.sts.rdcf");

/// Which `ENCT` encounter to fight. The id is looked up in the image's `SEC_IDX` (a missing id is
/// a loud [`rd_core::content::EncounterError`], not an empty field).
///
/// `enc_small_slimes` = `acid_slime_m` (28 HP) + `spike_slime_s` (10 HP). Two enemies on purpose:
/// one enemy cannot tell `NextRound` from `EndOneTurn`, so a one-enemy scenario cannot show that
/// the multi-enemy turn works.
const ENCOUNTER: &str = "enc_small_slimes";

/// RNG seed. The content deck + `shuffle: true` makes this observable (`random_step` moves).
const SEED: i32 = 7;
const COMBAT_ID: &str = "rd_wasm_spike";
const HERO: &str = "hero";
/// Hero max HP for the **plan**. ⚠️ Not read from the content: `Start.MaxHealth` has no kernel
/// consumer (`native/sts_content_check.py` declares it inert, and the gate fails if anybody
/// starts reading it). The content says 80; this constant says 80; that agreement is a
/// coincidence, not a wire — which is exactly why the declaration exists.
const HERO_HP: i32 = 80;
/// §203: the stand-in hero for `rd_env_start_encounter` (see its doc).
const DEBUG_HERO_HP: i32 = 400;
/// Starting / per-turn energy (the standard package's `3`).
const ENERGY: i32 = 3;
/// §261：观察向量里报的"能量上限" = **每回合补给量**（不是池子上的 max —— 池子故意没有天花板）。
///
/// ⚠️ 这个数字是"标准包的回合补给"，不是"能量的合法上限"：事件/状态/别的玩法模式可以把它抬到
/// 别的值（某些玩法回合开始就有 7 点）。等"改补给量"的内容真的出现时，这里要改成读
/// `TurnConfig::energy_refill` 那一侧的**派生值**，而不是继续用这个常量。
const HERO_ENERGY_REFILL: i32 = ENERGY;

// =============================================================================================
// The observation vector (`docs/spec/env-abi.md` §4) — 12 + 5 + 4×8 + 4×5 + 10×4 + 5 + 8 = 122
// =============================================================================================

// Six, not four: the Slime Boss splits (1 -> 2), and a split plus an add would overflow four.
// This is a **semantic** constant -- it moves `OFF_ENEMY_STATUS`, `OFF_HAND`, `OFF_PILES` and
// `OBS_LEN` with it, so `web/ui_render.js` has to move in step (`smoke.mjs` checks the tiling).
const MAX_ENEMY_SLOTS: usize = 6;

/// The team the hero is on; everything else is an enemy (`env-abi.md` §10).
const PLAYER_TEAM: &str = "player";
const MAX_HAND_SLOTS: usize = 10;
/// The five status axes the ABI fixes, in ABI order.
const STATUS_AXES: [&str; 5] = [
    "standard.strength",
    "standard.vulnerable",
    "standard.weak",
    "standard.dexterity",
    "standard.frail",
];

// §169: **不加"这一格是几号"的尾注**。这些数字原来是手写的（`// 49`、`// 69`、`// 122`），
// 而 `MAX_ENEMY_SLOTS` 从 4 涨到 6 之后它们全成了假的 —— 表达式仍然是对的，只有注释在说谎，
// 而"哪一格是几号"恰恰是页面唯一关心的事。真正的守卫是 `smoke.mjs`：它把 `web/ui_render.js`
// 声明的偏移与本模块导出的 `rd_env_observe_len()` 对起来，铺不满就红。
const OFF_HEADER: usize = 0;
pub(crate) const OFF_HERO_STATUS: usize = OFF_HEADER + 12;
const OFF_ENEMY: usize = OFF_HERO_STATUS + 5;
const OFF_ENEMY_STATUS: usize = OFF_ENEMY + MAX_ENEMY_SLOTS * 8;
pub(crate) const OFF_HAND: usize = OFF_ENEMY_STATUS + MAX_ENEMY_SLOTS * 5;
const OFF_PILES: usize = OFF_HAND + MAX_HAND_SLOTS * 4;
const OFF_RESERVED: usize = OFF_PILES + 5;
/// `rd_env_observe_len()` — the caller must not hard-code this (`env-abi.md` §2.3), so it is
/// published as an export too. The value is whatever the expression above produces (148 today);
/// the page reads it rather than repeating it.
const OBS_LEN: usize = OFF_RESERVED + 8;

/// Header slot indices.
const H_ROUND: usize = 0;
const H_TURN: usize = 1;
const H_PHASE: usize = 2;
const H_RESULT: usize = 3;
const H_HERO_HP: usize = 4;
const H_HERO_HP_MAX: usize = 5;
pub(crate) const H_HERO_BLOCK: usize = 6;
/// 手牌费用格里的"这不是数字费"（§146）：页面把它画成 `X`。
pub const X_COST_DISPLAY: i32 = -2;
/// X 费牌的 tag（与 `rd_core::battle::X_COST_TAG` 同一个字面量）。
const X_COST_TAG: &str = rd_core::battle::X_COST_TAG;
const H_HERO_WARD: usize = 7;
pub(crate) const H_ENERGY: usize = 8;
const H_ENERGY_MAX: usize = 9;
pub(crate) const H_HAND_COUNT: usize = 10;
const H_ENEMY_COUNT: usize = 11;

// =============================================================================================
// Actions (`env-abi.md` §5)
// =============================================================================================

const ACTION_PLAY: i32 = 0;
const ACTION_END_TURN: i32 = 1;

#[derive(Clone, Copy)]
struct Action {
    kind: i32,
    arg0: i32,
    arg1: i32,
}

// =============================================================================================
// Enemy intent (the "what is it about to do" column)
// =============================================================================================

/// How deep the damage preview walks a program. `EACT` programs in this content are 1–2 levels
/// (`dealDamage`, or `sequence([dealDamage, …])`); the cap is here so a cyclic/crazy tree in a
/// future image cannot hang the page.
const MAX_PREVIEW_DEPTH: usize = 8;
/// Same cap the kernel's own pre-check uses for `Children` (`exec.rs`'s `MAX_CHILDREN`).
const MAX_PREVIEW_CHILDREN: usize = 32;

/// `IntentKind` → the ABI's small integer, **in the reference enum's own order**
/// (`ActionIntent.cs:5-13`): `Unknown=0, Attack=1, Defend=2, Buff=3, Debuff=4, Special=5`.
/// `-1` = the cell is absent (`Intent.Kind` missing), which is the ABI's "not produced".
fn intent_kind_code(kind: Option<IntentKind>) -> i32 {
    match kind {
        None => -1,
        Some(kind) => IntentKind::ALL
            .iter()
            .position(|candidate| *candidate == kind)
            .map_or(-1, |index| index as i32),
    }
}

/// One enemy's telegraph, read back out of the content every time the observation is rebuilt.
///
/// Three separate things, and the page needs them separate:
/// * `kind` — `EACT.Intent.Kind`. The **core** mirror has no `Label`/`NameKey`
///   (`docs/spec/enemy-intent.md` §2.6), so the display cannot be "Rubber Stamp Rush · 5 dmg";
///   the category is all there is.
/// * `damage` — the sum of the program's `const` `dealDamage` amounts, or `-1` when an amount is
///   not a literal (then it is *not* guessed at).
/// * `text` — what the page prints, assembled here so the page owns no game knowledge.
#[derive(Clone, Debug)]
struct Intent {
    kind: i32,
    damage: i32,
    text: String,
}

impl Intent {
    fn unknown(note: &str) -> Self {
        Self {
            kind: -1,
            damage: -1,
            text: note.to_string(),
        }
    }
}

/// How much damage an `EACT` row's program deals, read out of the program itself.
///
/// The rule is narrow on purpose: sum the `const` amounts of the `dealDamage` nodes reachable
/// through `node.sequence.Children`, and answer `-1` for anything that would need the *state* to
/// evaluate (`multiply`, a status modifier) or that sits behind a branch
/// (`conditional`/`forEach*`). `-1` here means "this implementation does not produce this
/// quantity", which is the ABI's own vocabulary for it (`env-abi.md` §4) — a plausible-looking
/// guess would be worse than the hole.
fn program_damage(content: &'static Content<'static>, action_row: u32) -> i32 {
    let Ok(root) = enemy_action_program_root(content, action_row) else {
        return -1;
    };
    let mut total = 0i32;
    if !walk_damage(root, 0, &mut total) {
        return -1;
    }
    total
}

/// Depth-first walk behind [`program_damage`]; `false` = "cannot be answered statically".
fn walk_damage(node: NodeRef<'static>, depth: usize, total: &mut i32) -> bool {
    if depth > MAX_PREVIEW_DEPTH {
        return false;
    }
    let Ok(kind) = node.kind_str() else {
        return false;
    };
    match kind {
        "node.dealDamage" => {
            let Some(amount) = node.node_field("Amount").ok().flatten() else {
                return false;
            };
            if amount.kind_str() != Ok("const") {
                return false; // 依赖状态 ⇒ 不猜
            }
            let Ok(Some(value)) = amount.int_field("Value") else {
                return false;
            };
            *total = total.saturating_add(value);
            true
        }
        "node.sequence" => {
            let mut ids = [0u16; MAX_PREVIEW_CHILDREN];
            let Ok(count) = node.term_list_field("Children", &mut ids) else {
                return false;
            };
            for id in ids.iter().take(count) {
                if !walk_damage(node.child(*id), depth + 1, total) {
                    return false;
                }
            }
            true
        }
        // These three can hide damage behind a condition/target list ⇒ not statically answerable.
        "node.conditional" | "node.forEachTarget" | "node.forEachCardInZone" => false,
        // Everything else is a node that cannot deal damage (`applyStatus`, `gainBlock`,
        // `heal`, `drawCards`, `setCombatantCounter`, `gainResource`, …): contributes 0, and
        // saying so is exact rather than a guess.
        _ => true,
    }
}

// =============================================================================================
// The session
// =============================================================================================

struct Session {
    /// The content image, leaked once. `Host<'a>` wants `&'a Content<'a>`, so the `Content` must
    /// itself live somewhere `'static` — leaking a box is the cheapest honest answer.
    content: &'static Content<'static>,
    /// 184,648 B: boxed so no export ever materialises it on the wasm stack.
    state: Box<CombatState>,
    host: Host<'static>,
    plan: FightPlan<'static>,
    /// 74 KB (see `Problem`'s largest variant), so also boxed.
    out: Box<FightOutcome>,
    /// Hand slot → card definition id, captured by the last [`Session::reobserve`].
    hand_defs: Vec<String>,
    /// Hand slot → printed energy cost (`-1` = could not read it).
    hand_costs: Vec<i32>,
    /// The action table, rebuilt by the last [`Session::reobserve`].
    actions: Vec<Action>,
    /// `ENCT` row of the encounter being fought (`locate_enemy` wants the row, not the id).
    encounter: u32,
    /// Enemy slot (`plan.enemies` index) → this round's intent, as read back from the content.
    ///
    /// Rebuilt by [`Session::refresh_intents`] on every observation, because the reference's
    /// preview is a **pure function of (state, content) that is recomputed every time it is
    /// asked** (`docs/spec/enemy-intent.md` §2.3) — there is no "select once, store, consume"
    /// step to copy, and `CombatantState.IntentKey` is a dead field there.
    intents: Vec<Intent>,
    /// `run_fight`'s "problems" for the last step, by `wire_name`. Observations, not failures.
    /// §199: `String`, not `&'static str` -- `StepThrew(Script)` used to be the most a problem
    /// could say, and that is exactly the level of detail nobody can act on. The refusal **code**
    /// was already recorded in `FightOutcome::step_codes` (§177) and simply had nowhere to go. The
    /// name comes from `battle::play_code_name` -- the one table -- so the two cannot drift.
    problems: Vec<String>,
    /// Human-readable reason for the last non-`Ok` return.
    error: String,
    /// Reward for the last step, in 1/1000 (`env-abi.md` §7 + §10's "wasted energy" ruling).
    reward: i32,
    /// §161.3: which legal options the player has ticked in the pending card choice.
    ///
    /// **UI scratch, not game state.** The *action* is [`rd_env_choice_confirm`], which hands the
    /// whole selection to the kernel at once; the kernel's [`rd_core::state::resolve_choice`] either
    /// takes it entirely or refuses with nothing changed. Keeping the tick list here rather than in
    /// `CombatState` is what lets the kernel's answer stay atomic -- and it is why a half-finished
    /// selection is not something a save file has to describe.
    choice_picks: Vec<usize>,
    /// Observation snapshots either side of the last step: `-1` means "step rejected, state
    /// unchanged" is decided by comparing these, exactly as §10 requires.
    before: Vec<i32>,
    after: Vec<i32>,
}

static mut SESSION: Option<Session> = None;
/// The observation buffer whose address `rd_env_observe_buf()` hands to JS. Kept out of
/// `Session` so the pointer stays valid across `rd_env_reset()`.
static mut OBS: [i32; OBS_LEN] = [0; OBS_LEN];
/// Scratch for error / card-name bytes handed across the boundary.
static mut SCRATCH: [u8; 1024] = [0; 1024];

/// Capacity of the replay-script buffer. A three-act run's script is a few KB; 24 KiB is ~10x
/// headroom, and `rd_run_script_fill` refuses rather than truncating if it is ever not enough.
pub const MAX_SCRIPT: usize = 24 * 1024;

/// The **replay script** buffer (§164). Its own buffer for the same reason as `ARCHIVE`: a script
/// grows with the run (a 40-step walk measures ~1.6 KB, a three-act run several KB) and `SCRATCH`
/// is 1024 B by contract. Length is published (`rd_run_script_capacity`) and overflow is refused
/// **before** anything is written, not truncated.
static mut SCRIPT: [u8; MAX_SCRIPT] = [0; MAX_SCRIPT];

/// The **archive** buffer (§161.10). Not the scratch one: an archive is up to 16 KiB (a 60-card
/// run measures 1628 B) and `SCRATCH` is 1024 B by contract, so handing the scratch pointer to the
/// archive export wrote past the end of it. One buffer per contract, and this one's length is
/// published (`rd_run_archive_capacity`).
static mut ARCHIVE: [u8; rd_run::state::archive::MAX_ARCHIVE] = [0; rd_run::state::archive::MAX_ARCHIVE];

/// The session slot.
///
/// `wasm32-unknown-unknown` here is single-threaded and the value lives in the module's BSS for the
/// module's whole lifetime, so a `static mut` with one accessor is sound — **provided no borrow is
/// held across a call**.
///
/// ⚠️ One export **does** re-enter others: `rd_run_replay_from` replays a script by calling the
/// ordinary exports. So the old phrasing of this note ("no export re-enters another export") was
/// false — and false in the worst place, as the stated reason the aliasing was fine. The rule that
/// replaces it:
///
/// > **Never hold a `&`/`&mut` from the slot across a call to another export.** Borrow, use, drop,
/// > call. `rd_run_replay_from` is where this matters, and it is written that way.
///
/// (Found by an external review of `5c467b6`: the code worked, but it was UB by the aliasing model.)
#[allow(static_mut_refs)]
pub(crate) fn slot() -> &'static mut Option<Session> {
    unsafe { &mut SESSION }
}

/// Put a session in the combat slot (the run layer builds one from its own deck).
pub(crate) fn install_session(session: Session) {
    *slot() = Some(session);
}

/// Drop the combat session, returning nothing if there was none.
pub(crate) fn take_session() -> Option<Session> {
    slot().take()
}

/// The fight's result as the ABI's small integer (`env-abi.md` §3), or `None` with no fight.
pub(crate) fn combat_result() -> Option<i32> {
    slot().as_ref().map(|session| match session.state.result {
        CombatResult::Ongoing => 0,
        CombatResult::Victory => 1,
        CombatResult::Defeat => 2,
        CombatResult::Draw => 3,
        CombatResult::Aborted => 4,
    })
}

/// The hero's current health in the installed fight.
/// §201: how much gold an enemy **carried away** with it (`node.carryAwayStolenGold`).
///
/// The kernel has no gold; this is the one number the run needs at `fight_end`, and it is the only
/// thing that makes "the Looter escaped with your gold" visible outside the fight.
/// §201: how much gold an enemy **carried away** with it (`node.carryAwayStolenGold`).
///
/// The kernel has no gold; this is the one number the run needs at `fight_end`, and it is the only
/// thing that makes "the Looter escaped with your gold" visible outside the fight.
pub(crate) fn combat_gold_carried_away() -> i32 {
    slot()
        .as_ref()
        .map_or(0, |session| session.state.gold_carried_away)
}

/// §250：这一场战斗里**赚到**的金币（`node.gainGold` 累加）。
///
/// 与 [`combat_gold_carried_away`] 成对：那本是"被偷走、要减"，这本是"赚到手、要加"。
pub(crate) fn combat_gold_gained() -> i32 {
    slot()
        .as_ref()
        .map_or(0, |session| session.state.gold_gained)
}

pub(crate) fn combat_hero_health() -> Option<i32> {
    let session = slot().as_ref()?;
    let hero = session.hero_id()?;
    session
        .state
        .combatant(&hero)
        .map(|combatant| combatant.health_current)
}

/// §253：按**创建顺序**取英雄的第 `index` 张战斗卡（返回 `(实例 id, 定义 id)`）。
///
/// 为什么不是"把牌位号拼成 `card_{i:06}`"：那要依赖"实例号从几开始"这件事，而实测它是
/// **从 1 起**（`a_broken_slot` 那条判据的探针看到的是 `card_000001..card_000005`）。
/// 一个魔法偏移量迟早会漂，而**顺序**是稳定的：发牌按牌组顺序进行，实例 id 是零填充的
/// （`card_%06d`），所以"按 id 字符串排序" == "按创建顺序排序"。
///
/// 战斗中新造的牌 id 更大，永远排在后面 ⇒ 取前 `deck_len` 个就是发出去的那副牌组。
pub(crate) fn combat_card_in_creation_order(
    index: usize,
) -> Option<(
    rd_core::state::CardInstanceId,
    rd_core::state::CardDefinitionId,
)> {
    let session = slot().as_ref()?;
    let hero = session.hero_id()?;
    let zones = session.state.card_zones(&hero)?;
    let mut cards = std::vec::Vec::new();
    for zone in rd_core::state::CardZone::ALL {
        for at in 0..zones.count(zone) {
            let Some(slot) = zones.slot_at(zone, at) else {
                continue;
            };
            let Some(card) = session.state.card(slot) else {
                continue;
            };
            cards.push((card.id, card.definition_id));
        }
    }
    cards.sort_by(|left, right| left.0.as_str().cmp(right.0.as_str()));
    cards.get(index).copied()
}

/// §253：按**实例 id** 找那一份战斗卡（`None` = 不在这个牌区集合里）。
///
/// 用于"运行层的牌位 ↔ 战斗实例"的对号（`apply_run_marks` / `capture_run_marks`）。
/// 拷贝出 `definition_id` 而不是借出去：调用方马上要拿 `&mut` 去写状态。
pub(crate) fn combat_card_by_instance(
    instance: &rd_core::state::CardInstanceId,
) -> Option<CombatCardSummary> {
    let session = slot().as_ref()?;
    let hero = session.hero_id()?;
    let (_, slot) = session.state.find_card(&hero, instance)?;
    let card = session.state.card(slot)?;
    Some(CombatCardSummary {
        definition_id: card.definition_id,
        marks: card.mark_counters().iter().copied().collect(),
    })
}

/// 一份战斗卡在"跨场对号"时要看的东西（定义 + 每副本 mark）。
pub(crate) struct CombatCardSummary {
    /// 卡定义 id。
    pub(crate) definition_id: rd_core::state::CardDefinitionId,
    /// 它身上的 mark counter（每副本数据）。
    pub(crate) marks: std::vec::Vec<rd_core::state::Counter>,
}

/// §253：把一格每副本数据写到指定的那一份战斗卡上。
pub(crate) fn combat_set_mark(
    instance: &rd_core::state::CardInstanceId,
    key: &str,
    value: i32,
) -> Result<(), &'static str> {
    let session = slot().as_mut().ok_or("没有正在进行的战斗")?;
    let hero = session.hero_id().ok_or("找不到英雄")?;
    let (_, slot) = session.state.find_card(&hero, instance).ok_or("那一份牌不在牌区里")?;
    let key = rd_core::state::CounterId::new(key).map_err(|_| "mark counter 的名字装不下")?;
    let card = session.state.card_mut(slot).ok_or("那一份牌不存在")?;
    card.set_mark_counter(key, value).map_err(|_| "那张牌的计数器表满了")
}

/// Put the hero at `value` health.
///
/// Needed because the fight is built at the hero's **maximum** (`build_fight_from_content` uses
/// `PlanCombatant.max_health` and starts there), while a run's hero usually enters wounded.
pub(crate) fn set_combat_hero_health(value: i32) {
    if let Some(session) = slot().as_mut() {
        if let Ok(id) = CombatantId::new(HERO) {
            if let Some(combatant) = session.state.combatant_mut(&id) {
                combatant.health_current = value;
            }
        }
        // **Re-observe after the write.** The published vector is what the page reads, and the page's
        // battle log is a *diff of two observations* -- a stale baseline made the first card's log
        // entry claim a hit that happened before the fight ever started. Reported by hand: "bash 打出
        // 后英雄受到 7 点伤害", where the 7 was the tower blessing's cost.
        session.reobserve_after_external_change();
    }
}

fn ensure_session() -> Result<&'static mut Session, String> {
    let slot = slot();
    if slot.is_none() {
        *slot = Some(build_session(SEED)?);
    }
    slot.as_mut()
        .ok_or_else(|| "session vanished right after being built".to_string())
}

fn build_session(seed: i32) -> Result<Session, String> {
    build_session_with(seed, ENCOUNTER, HERO_HP, None)
}

/// Build a fight from explicit parameters instead of the constants, so the run layer can hand in
/// **its own deck and its own health**.
///
/// `deck` is `None` for "let the content decide" (`Characters[0].Start.Deck`), which is what the
/// standalone demo does; `Some` is the run's deck, compressed into `(card, count)` entries.
fn build_session_with(
    seed: i32,
    encounter_name: &str,
    hero_hp: i32,
    deck: Option<&'static [DeckEntry<'static>]>,
) -> Result<Session, String> {
    build_session_at(seed, encounter_name, hero_hp, deck, 0, 0)
}

/// Put every enemy's `StartingStatuses` onto it (§175b).
///
/// `ENCT[*].Enemies[j].StartingStatuses` is a list of `{Status, Stacks, DurationTurns, Charges}`
/// specs. Nothing applied them before this: Sentries had no Artifact, Gremlin Leader no Enrage,
/// Giant Head no Metallicize, Lagavulin no Metallicize 8. The content layer had been *counting* them
/// since §1 -- a number that was checked while the behaviour was missing.
///
/// §207: the `Asc` override for one `StartingStatuses` entry, or `Ok(None)` when it has none.
///
/// Absent column / empty list = "not pinned" (a record without the key is legal: 20 of 50 records
/// have `StartingStatuses` at all, and most of those never change with ascension). A malformed list
/// is a **loud** error: a silently ignored override is "the wiki's A19 number" turning into "the A0
/// number" with every gate green.
fn starting_status_asc(
    node: &rd_core::ir::NodeRef<'_>,
    ascension: i32,
) -> Result<Option<i32>, String> {
    let mut ids = [0u16; rd_core::content::MAX_ASC_VARIANTS];
    let count = match node.term_list_field_or_empty("Asc", &mut ids) {
        Ok(count) => count,
        Err(error) => return Err(std::format!("{error:?}")),
    };
    let mut best: Option<(i32, i32)> = None;
    for index in 0..count {
        let Some(id) = ids.get(index).copied() else {
            return Err("list longer than the buffer".to_string());
        };
        let entry = node.child(id);
        let threshold = entry
            .int_field("AscensionMin")
            .map_err(|e| std::format!("AscensionMin: {e:?}"))?
            .ok_or_else(|| "an entry without `AscensionMin`".to_string())?;
        if threshold <= 0 || threshold > ascension {
            continue;
        }
        let stacks = entry
            .int_field("Stacks")
            .map_err(|e| std::format!("Stacks: {e:?}"))?
            .ok_or_else(|| "an entry without `Stacks`".to_string())?;
        match best {
            Some((seen, _)) if seen >= threshold => {}
            _ => best = Some((threshold, stacks)),
        }
    }
    Ok(best.map(|(_, stacks)| stacks))
}

/// Applied through `EffectRequest::ApplyStatus` + `exec::drain`, i.e. the same path a card or an
/// enemy action takes, so there is no second implementation of "add a status".
fn apply_starting_statuses(
    session: &mut Session,
    content: &'static Content<'static>,
    encounter: u32,
) -> Result<(), String> {
    let enemies = content
        .encounter_enemies(encounter)
        .map_err(|e| format!("encounter_enemies: {}", detail(&e)))?;
    for spec in enemies.iter() {
        let spec = spec.map_err(|e| format!("ENCT enemy record: {}", detail(&e)))?;
        let id = spec.id().map_err(|e| format!("ENCT enemy id: {}", detail(&e)))?;
        let Ok(target) = rd_core::state::CombatantId::new(id) else {
            return Err(format!("`{id}` is not a usable combatant id"));
        };
        // §208: `StartingBlock` -- an enemy can **start with block on it**, and `StartingStatuses`
        // cannot say that (block is a defensive pool, not a status). The wiki states it as a power
        // (`Jaw Worm: Block 6 (A17 9)`), so the record grows one column plus the usual ascension
        // list. Applied through `EffectRequest::GainBlock` + `drain`, i.e. the same path a card
        // takes -- no second implementation of "add block".
        let level = i32::from(session.state.ascension());
        let starting_block = match spec
            .starting_block_asc(level)
            .map_err(|e| format!("ENCT enemy StartingBlock: {}", detail(&e)))?
        {
            Some(amount) => amount,
            None => spec
                .starting_block()
                .map_err(|e| format!("ENCT enemy StartingBlock: {}", detail(&e)))?
                .unwrap_or(0),
        };
        if starting_block > 0 {
            session
                .state
                .enqueue_effect(rd_core::state::EffectRequest::GainBlock {
                    target: Some(target),
                    amount: starting_block,
                    // §245: 不是牌给的格挡（这里是测试/调试入口）。
                    from_card: false,
                })
                .map_err(|e| format!("enqueue starting block: {}", detail(&e)))?;
            rd_core::exec::drain(&mut session.state, Some(&content), None)
                .map_err(|e| format!("drain starting block: {}", detail(&e)))?;
        }
        let statuses = spec
            .starting_statuses()
            .map_err(|e| format!("StartingStatuses: {}", detail(&e)))?;
        for index in 0..statuses.len() {
            let term = statuses
                .term(index)
                .ok_or_else(|| format!("StartingStatuses[{index}] has no term"))?;
            let node = rd_core::ir::NodeRef::new(content, term);
            // `StatusDefinitionId` is the key the **content** uses (`enc_three_sentries` and friends);
            // `content.rs`'s doc comment said `Status`, which was wrong -- that comment is fixed in the
            // same change. Both spellings are accepted so neither can bite again.
            let status_id = node
                .str_field("StatusDefinitionId")
                .ok()
                .flatten()
                .or_else(|| node.str_field("Status").ok().flatten());
            let Some(status_id) = status_id else {
                return Err(format!(
                    "StartingStatuses[{index}] has neither `StatusDefinitionId` nor `Status`"
                ));
            };
            let Ok(definition) = rd_core::state::StatusDefinitionId::new(status_id) else {
                return Err(format!("`{status_id}` is not a usable status id"));
            };
            // §208: **presence** is its own knob. `AscensionMin` on the entry means "this starting
            // status does not exist below that level" (wiki: Awakened One has `Strength 2` only from
            // A4). It is orthogonal to `Asc` below -- presence is not "0 stacks", because a status
            // with 0 stacks still occupies an instance slot and still answers `selfHasStatus`.
            let level = i32::from(session.state.ascension());
            let present_from = node
                .int_field("AscensionMin")
                .map_err(|e| format!("StartingStatuses[{index}].AscensionMin: {e:?}"))?
                .unwrap_or(0);
            if present_from > 0 && level < present_from {
                continue;
            }
            // §207: `Asc: [{AscensionMin, Stacks}, …]` overrides the stack count at (and above) a
            // level -- the third ascension list, next to `EACT.ProgramAsc` (§192) and
            // `ENCT.MaxHealthAsc` (§206), with the **same** rule: the largest threshold that is
            // still `<= ascension`, and the order in the list does not participate.
            let stacks = match starting_status_asc(&node, level) {
                Ok(Some(overridden)) => overridden,
                Ok(None) => node.int_field("Stacks").ok().flatten().unwrap_or(1),
                Err(message) => return Err(format!("StartingStatuses[{index}].Asc: {message}")),
            };
            let duration = node.int_field("DurationTurns").ok().flatten().unwrap_or(0);
            let charges = node.int_field("Charges").ok().flatten().unwrap_or(0);
            session
                .state
                .enqueue_effect_with_owner(
                    rd_core::state::EffectRequest::ApplyStatus {
                        target: Some(target),
                        definition,
                        stacks,
                        duration,
                        charges,
                        source: Some(target),
                        source_card: None,
                    },
                    None,
                )
                .map_err(|e| format!("enqueue starting status: {}", detail(&e)))?;
            rd_core::exec::drain(&mut session.state, Some(&content), None)
                .map_err(|e| format!("drain starting status: {}", detail(&e)))?;
        }
    }
    Ok(())
}

/// [`build_session_with`], plus the Ascension health bonus for the enemies (§159).
///
/// `enemy_health_percent` is `A7`/`A8`/`A9` read off the run (`0` below those levels). It is applied
/// to the `ENCT` row's `MaxHealth`, which is the only place an enemy's health is stated -- so the
/// rule lands on the number the content wrote, not on a second copy.
fn build_session_at(
    seed: i32,
    encounter_name: &str,
    hero_hp: i32,
    deck: Option<&'static [DeckEntry<'static>]>,
    enemy_health_percent: i32,
    ascension: u8,
) -> Result<Session, String> {
    build_session_at_with(seed, encounter_name, hero_hp, deck, enemy_health_percent, ascension, true)
}

/// §261: 同 [`build_session_at`]，但**停在英雄第 1 回合开始之前**（`WaitingToStartTurn`）。
///
/// 存在的理由只有一个：**遗物的"开战"效果必须在第 1 回合开始之前生效**，否则它们会错过
/// 第 1 回合的每一个时点：
///
/// * `bag_of_preparation`（开战多抽 2 张）的 `TurnStarted` 触发器在第 1 回合已经过去了；
/// * `lantern`（第 1 回合 +1 能量）同理；
/// * `mercury_hourglass`（每次回合初对所有敌人 3 点）会少打第 1 回合。
///
/// `build_session_at` 会把第 1 回合**立刻**开起来（那是给页面用的，玩家一进场就该看到 5 张手牌），
/// 于是 run 层的"先建、再挂遗物状态、再开打"这条顺序需要一个不开始的入口。
fn build_session_at_unstarted(
    seed: i32,
    encounter_name: &str,
    hero_hp: i32,
    deck: Option<&'static [DeckEntry<'static>]>,
    enemy_health_percent: i32,
    ascension: u8,
) -> Result<Session, String> {
    build_session_at_with(seed, encounter_name, hero_hp, deck, enemy_health_percent, ascension, false)
}

fn build_session_at_with(
    seed: i32,
    encounter_name: &str,
    hero_hp: i32,
    deck: Option<&'static [DeckEntry<'static>]>,
    enemy_health_percent: i32,
    ascension: u8,
    start_the_first_turn: bool,
) -> Result<Session, String> {
    let content: &'static Content<'static> =
        Box::leak(Box::new(Content::parse(IMAGE).map_err(|e| format!("RDCF 镜像解析失败: {}", detail(&e)))?));

    // ── The enemies come out of the encounter, not out of this file ──────────────────────────
    // `ENCT[enc].Enemies[j]` is the **only** place that says "these enemies, in this order"
    // (`Encounters.cs:211-220`; the flat `EACT` table is just the action library). The order is
    // also the turn order, and it is the order `intent::locate_enemy` indexes into.
    let entry = content
        .lookup_in(encounter_name, EK_ENCOUNTER)
        .ok_or_else(|| format!("内容镜像里没有遭遇 `{encounter_name}`"))?;
    let encounter: u32 = u32::from(entry.index);
    // §195.8: two records may share an `Id` (`enc_darklings` is two identical Darklings, and the
    // C# reference keys its roster by id, which is why the *content* keeps them distinct only by
    // position). `add_combatant` refuses a duplicate, so the second one gets the same `#<n>` suffix a
    // summon uses -- which is also what `intent::locate_enemy` already falls back to (definition part).
    //
    // ⚠️ Before this, `enc_darklings` could not be built at all: it sits in the act-3 weak pool, so a
    // real run that rolled it ended in `Capacity(DuplicateCombatant)`.
    let mut enemies: Vec<PlanCombatant<'static>> = Vec::new();
    let mut seen_ids: Vec<&'static str> = Vec::new();
    // (combatant id, its master's id) for the records that declare an `Owner`.
    let mut owners: Vec<(&'static str, &'static str)> = Vec::new();
    for spec in content
        .encounter_enemies(encounter)
        .map_err(|e| format!("encounter_enemies: {}", detail(&e)))?
        .iter()
    {
        let spec = spec.map_err(|e| format!("ENCT enemy record: {}", detail(&e)))?;
        let id: &'static str = spec.id().map_err(|e| format!("ENCT enemy id: {}", detail(&e)))?;
        // `MaxHealth` 缺席 ⇒ 响亮失败。参考在这里有默认值吗？没有可靠出处 ⇒ 不编一个。
        let max_health = spec
            .max_health()
            .map_err(|e| format!("ENCT enemy MaxHealth: {}", detail(&e)))?
            .ok_or_else(|| format!("`{id}` has no MaxHealth in the encounter"))?;
        // §195.6: `Spawn: false` = "this record is here so its moves can be looked up, not so it
        // starts on the field" (Bronze Orb / Torch Head / Dagger). The summon action creates it.
        if !spec.spawn().map_err(|e| format!("ENCT enemy Spawn: {}", detail(&e)))? {
            continue;
        }
        // The id this combatant will actually carry: `id` the first time, `id#2`, `id#3` after that.
        let unique: &'static str = if seen_ids.contains(&id) {
            let mut count = 2usize;
            let mut text = std::format!("{id}#{count}");
            while seen_ids.iter().any(|seen| *seen == text.as_str()) {
                count += 1;
                text = std::format!("{id}#{count}");
            }
            Box::leak(text.into_boxed_str())
        } else {
            id
        };
        seen_ids.push(unique);
        if let Some(master) = spec.owner().map_err(|e| format!("ENCT enemy Owner: {}", detail(&e)))? {
            owners.push((unique, Box::leak(std::string::String::from(master).into_boxed_str())));
        }
        // §206: an ENCT record that pins `MaxHealthAsc` names the **absolute** HP for this ascension
        // level (wiki gives ranges, e.g. Looter 44-48 -> 46-50 at A7). Only records with no pinned
        // row fall back to the `+10%` model (`ASCENDED_ENEMY_HEALTH_PERCENT`), which is what that
        // constant's own comment always said it was waiting for.
        let max_health = match spec
            .max_health_asc(i32::from(ascension))
            .map_err(|e| format!("ENCT enemy MaxHealthAsc: {}", detail(&e)))?
        {
            Some(pinned) => pinned,
            None => max_health + max_health * enemy_health_percent / 100,
        };
        enemies.push(PlanCombatant {
            id: unique,
            max_health,
        });
    }
    if enemies.is_empty() {
        return Err(format!("遭遇 `{encounter_name}` 里没有敌人"));
    }
    // `FightPlan` borrows the slice for the session's whole life; a browser page builds one
    // session per reset, so leaking two small slices is the cheapest honest answer (the alternative
    // is const-generic plumbing through `FightPlan`, which is frozen).
    let enemies: &'static [PlanCombatant<'static>] = Box::leak(enemies.into_boxed_slice());

    // The standard package's turn config is the authority for the resource id and the draw count
    // (`StandardCombatPackage.cs:7,124`); re-typing "standard.energy"/5/3 here would be a second
    // source of truth that can drift from the kernel's.
    let standard = standard_turn_config().map_err(|e| format!("standard_turn_config: {}", detail(&e)))?;
    let energy: ResourceId = standard.energy;

    // `FightPlan` borrows these, and the plan outlives the call that builds it ⇒ leak them. Two
    // tiny slices per `reset()`; a long-lived process would want a fixed-size buffer instead.
    //
    // §261: **能量的 `max` 是 `None`** —— 这不是"忘了写上限"，是参考的那个 `CanExceedMax` 字段
    // （`Blueprints.cs:153-157` 的原话：*a "gain 1 Energy" card played on a full pool still gives the
    // point; the turn-start refill sets it back to Max, so nothing carries over*）。
    //
    // ⚠️ 之前写的是 `Some(ENERGY)`，于是 `gainResource`（`ResourceEffects.cs:215` 的夹上限）
    // 把每一次**满池时的加能量都抹成 0**：`bloodletting` / `offering` / `seeing_red` /
    // `dropkick` / `sentinel` / `miracle` 六张牌在满能量时**静默无效**。之所以一直没人发现，
    // 是因为 rd-core 的 `arena()` 夹具从能量 **0** 起跑（`host.rs` 那句注释："0 费牌不需要预置"）——
    // 夹上限需要一个"满池"的起点才看得见。
    //
    // 上限的**规则**没有消失：它在回合开始那一步（`refill_resource` 把 current 设成 base=3，
    // 于是回合初永远是 3 点，上一回合的余额不留）。`max = None` 说的是"这个池没有硬天花板"，
    // 而那正是参考的表达。
    //
    // ⚠️ **"3" 只是本内容（标准包）的回合补给量，不是能量的固有上限**。事件的"加能量"、
    // 状态/遗物改补给量、以及别的玩法模式都会动它 —— 例如某些玩法里回合开始就能有 **7 点**。
    // 所以将来要"真正的上限"（显示、上限类规则、超上限的合法性判断）时，必须从
    // `TurnConfig::energy_refill` / 补给流水线（`turn_start_refill_count`）那一侧派生，
    // **不要**回头给这个池子塞一个 `Some(n)` —— 那会把"本回合能拿到多少"和"最多能有几"重新
    // 混成一个数，并重新引入 §261 查出的那个"满池加能量静默无效"。
    // §261：**建池时 current = 0**，3 点由第 1 回合的补给给。之前写的是 `ENERGY`，
    // 于是"带携带的补给"（Ice Cream）在第 1 回合会把 3 点算成 3 + 3 = 6 —— 一个只在
    // `unspent_energy_carries` 存在时才会暴露的重复计数（它是 `base + current`，不是 `base`）。
    let resources: &'static [(ResourceId, i32, Option<i32>)] =
        Box::leak(vec![(energy, 0, None)].into_boxed_slice());
    let refills: &'static [(ResourceId, i32)] = Box::leak(vec![(energy, ENERGY)].into_boxed_slice());

    let plan = FightPlan {
        combat_id: COMBAT_ID,
        seed,
        hero: PlanCombatant {
            id: HERO,
            max_health: hero_hp,
        },
        enemies,
        // **Empty means "let the content decide"**: `build_fight_from_content` then reads the deck
        // out of the document (`Characters[0].Start.Deck` → `Start.Deck` → root `Deck`; the
        // three-line table is in `content.rs`'s header). The run layer passes its own deck here
        // instead, which is what makes a fight in the run *the run's* fight.
        deck: deck.unwrap_or(&[]),
        cards_drawn_per_turn: standard.draw_per_turn,
        // `true` on purpose: shuffling is what advances `random_step`, and "the RNG really ran"
        // is worth being able to see from the page.
        shuffle_draw_pile_on_start: true,
        resources,
        turn_start_refills: refills,
    };

    let mut state = Box::new(CombatState::new(
        CombatId::new(COMBAT_ID).map_err(|e| format!("CombatId: {}", detail(&e)))?,
        seed,
    ));
    // §187：难度等级进战斗状态（意图条件 `intent.ascensionAtLeast` 与 `EACT.ProgramAsc` 都读它）。
    state.set_ascension(ascension);
    let host = Host::new(content);
    build_fight_from_content(&mut state, content, &plan)
        .map_err(|e| format!("build_fight_from_content: {}", detail(&e)))?;

    // §195.8/§195.9: content-declared masters. A placed minion (the Awakened One's two Cultists) has
    // no other way to say "when this one falls, I flee" -- `node.createCombatant` sets `owner` for
    // summons, and `resolve_damage` already turns a downed master's minions into `Escaped`.
    //
    // ⚠️ §195.9 起这里是**外键**，不再是"尽力而为"：上一版对读不懂的 id `continue`、也不检查主人
    // 是否在场，于是一个拼错的主人 = 悬空引用 = 小兵永远不逃，**没有任何东西会红**。
    // 现在三种情况全部响亮失败：minion 名不合法 / master 名不合法 / master 不在本场（含歧义）。
    let mut resolved: Vec<(rd_core::state::CombatantId, rd_core::state::CombatantId)> = Vec::new();
    for (minion, master) in owners {
        let minion_id = rd_core::state::CombatantId::new(minion)
            .map_err(|e| format!("`Owner` on `{minion}`: bad combatant id ({:?})", e))?;
        let master_id = rd_core::state::CombatantId::new(master)
            .map_err(|e| format!("`{minion}`.Owner = `{master}`: bad combatant id ({:?})", e))?;
        if state.combatant(&minion_id).is_none() {
            return Err(std::format!("`Owner` set on `{minion}`, which is not in this fight"));
        }
        // Present **exactly once**: a duplicate record would make the reference ambiguous
        // (`darkling` vs `darkling#2`), and a master that spawns later would be a forward reference
        // this content cannot express yet.
        let present = state
            .combatants()
            .iter()
            .filter(|combatant| {
                let raw = combatant.id.as_str();
                raw == master || raw.split('#').next() == Some(master)
            })
            .count();
        if present != 1 {
            return Err(std::format!(
                "`{minion}`.Owner = `{master}`: {} combatants match (must be exactly one)",
                present
            ));
        }
        resolved.push((minion_id, master_id));
    }
    for (minion_id, master_id) in resolved {
        if let Some(combatant) = state.combatant_mut(&minion_id) {
            combatant.owner = Some(master_id);
        }
    }

    let mut session = Session {
        content,
        state,
        host,
        plan,
        out: Box::new(FightOutcome::new()),
        hand_defs: Vec::new(),
        hand_costs: Vec::new(),
        actions: Vec::new(),
        encounter,
        intents: Vec::new(),
        problems: Vec::new(),
        error: String::new(),
        reward: 0,
        choice_picks: Vec::new(),
        before: vec![0; OBS_LEN],
        after: vec![0; OBS_LEN],
    };
    // **StS starts the hero's first turn when the combat starts**: the player sees five cards
    // immediately. `build_fight_from_content` deliberately stops at `WaitingToStartTurn` because the
    // reference's *scenario driver* starts the turn on the first play (`ScenarioRunner.cs:105`), and
    // the four-layer diff harness compares step sequences on that basis. The browser is a game
    // driver, not the harness, so it does what StS does.
    //
    // Without this, round 1 rendered as an empty hand -- faithful to the reference DSL, wrong for the
    // game, and it looked exactly like a bug.
    // §193: the wiki's variable damage is "chosen at the start of combat" (Louse Bite 5-7,
    // Darkling Nip 7-11), so the roll happens here -- after the combatants exist and before the
    // first turn -- and the action program reads it with the reference's own `combatantCounter`.
    // One draw per roll, `random_step += 1`, so the RNG ledger still says exactly what happened.
    // §195.1: the same call also writes the **fixed** spawn counters (`Counters`), which is how a
    // content status can find an initialised budget (The Guardian's Mode Shift 30/35/40).
    rd_core::battle::apply_spawn_setup(&mut session.state, content, encounter)
        .map_err(|e| format!("apply_spawn_setup: {:?}", e))?;
    // §175b: apply the encounter's `StartingStatuses` **before** the first turn starts.
    apply_starting_statuses(&mut session, content, encounter)?;
    if start_the_first_turn {
        start_first_turn(&mut session.state, &standard, &mut session.host)
            .map_err(|e| format!("start_first_turn: {}", detail(&e)))?;
    }
    session.reobserve();
    // `run_fight` needs a `&mut Host`; keep it warm so the first step does not allocate.
    let _ = session.host.take_failure();
    Ok(session)
}

/// A step whose error the shell swallowed, named by family (§152).
fn step_cause_text(cause: &str) -> &'static str {
    match cause {
        "Script" => "StepThrew(Script)",
        "Exec" => "StepThrew(Exec)",
        "Turn" => "StepThrew(Turn)",
        "Other" => "StepThrew(Other)",
        _ => "StepThrew",
    }
}

/// `StepThrew(Capacity)` plus **which** container filled up.
///
/// The names come from `state::Container::name_of` (one table, in the kernel); this function only
/// turns one into a `&'static str`, because `Session::problems` is a `Vec<&'static str>` and cannot
/// hold a formatted string.
fn capacity_problem_text(container: &str) -> &'static str {
    match container {
        "TurnOrder" => "StepThrew(Capacity:TurnOrder)",
        "Combatants" => "StepThrew(Capacity:Combatants)",
        "CardZones" => "StepThrew(Capacity:CardZones)",
        "CardInstances" => "StepThrew(Capacity:CardInstances)",
        "CardsInZone" => "StepThrew(Capacity:CardsInZone)",
        "GlobalStatuses" => "StepThrew(Capacity:GlobalStatuses)",
        "Statuses" => "StepThrew(Capacity:Statuses)",
        "Resources" => "StepThrew(Capacity:Resources)",
        "DefensivePools" => "StepThrew(Capacity:DefensivePools)",
        "Counters" => "StepThrew(Capacity:Counters)",
        "Tags" => "StepThrew(Capacity:Tags)",
        "Marks" => "StepThrew(Capacity:Marks)",
        "MarkCounters" => "StepThrew(Capacity:MarkCounters)",
        "TemporaryRules" => "StepThrew(Capacity:TemporaryRules)",
        "PendingEffects" => "StepThrew(Capacity:PendingEffects)",
        "PendingEffectChains" => "StepThrew(Capacity:PendingEffectChains)",
        "PendingEffectOwners" => "StepThrew(Capacity:PendingEffectOwners)",
        "PendingEvents" => "StepThrew(Capacity:PendingEvents)",
        "PendingEventChains" => "StepThrew(Capacity:PendingEventChains)",
        "PendingContinuations" => "StepThrew(Capacity:PendingContinuations)",
        "Chains" => "StepThrew(Capacity:Chains)",
        "EventIdList" => "StepThrew(Capacity:EventIdList)",
        "ProgramFrames" => "StepThrew(Capacity:ProgramFrames)",
        "ProgramNodeSlots" => "StepThrew(Capacity:ProgramNodeSlots)",
        "ProgramLoops" => "StepThrew(Capacity:ProgramLoops)",
        _ => "StepThrew(Capacity)",
    }
}

impl Session {
    /// Refresh the observation snapshot and the action table. Called after every state change.
    ///
    /// ⚠️ The order matters and was wrong once: `compute_observation` reads `hand_defs` (to fill
    /// `def_slot`) and `hand_costs` (to fill `cost`), so [`Self::refresh_hand`] has to run first.
    /// The first version rebuilt them inside `compute_actions`, i.e. *after* publishing the
    /// observation, so every hand slot came out as `occupied = -1` while `hand_count` said 5 —
    /// a self-contradicting vector that no test noticed until one did.
    /// The same refresh, for a mutation that did **not** go through rd_env_step.
    ///
    /// A potion is exactly that: it writes to the combat state from outside the action loop. Without
    /// this, rd_env_observe_into kept serving the snapshot taken *before* the potion --
    /// measured:
    /// the write landed (read back on the combatant) and the observation still said 0 Block.
    pub(crate) fn reobserve_after_external_change(&mut self) {
        self.reobserve();
    }

    fn reobserve(&mut self) {
        self.before.copy_from_slice(&self.after);
        self.refresh_hand();
        self.refresh_intents();
        self.after = self.compute_observation();
        self.publish();
        self.actions = self.compute_actions();
    }

    /// Re-ask every enemy slot what it intends to do, and how hard.
    ///
    /// The layout follows the reference's *preview* path, not its *execution* path:
    /// `InteractiveCombat.cs:122` asks the selector with `_combat.CurrentRound` **during the
    /// hero's turn**, so that is the round this uses. `docs/spec/enemy-intent.md` §2.4 fork 2 is
    /// the honest caveat: the state between the preview and the moment the enemy actually acts
    /// (hero turn-end, then the enemy's turn-start: block cleared, DoT eaten) can flip a
    /// condition, so a preview is a prediction and not a promise. Nothing here caches it — the
    /// reference recomputes on every ask, and so does this.
    fn refresh_intents(&mut self) {
        let content = self.content;
        let round = self.state.current_round;
        let roster = self.enemy_roster();
        let mut intents = Vec::with_capacity(roster.len());
        for slot in 0..roster.len().min(MAX_ENEMY_SLOTS) {
            let raw_id = roster[slot].as_str();
            let Ok(id) = CombatantId::new(raw_id) else {
                intents.push(Intent::unknown("combatant id 不合法"));
                continue;
            };
            // §2.4 fork 3: the reference asks the selector about dead enemies too (`EnemyIntentRules`
            // 的 lambda 不检查 IsAlive), so this does too. The page decides whether to show it.
            let choice: Result<Option<ActionChoice<'static>>, _> =
                match locate_enemy(content, self.encounter, &id) {
                    Ok(Some(at)) => select_action(&self.state, content, at, &id, round),
                    Ok(None) => {
                        intents.push(Intent::unknown("不在这条遭遇的敌人名单里"));
                        continue;
                    }
                    Err(error) => Err(error),
                };
            let intent = match choice {
                Ok(Some(choice)) => {
                    let damage = program_damage(content, choice.action_row);
                    let kind = intent_kind_code(choice.intent_kind);
                    let mut text = choice.action_id.to_string();
                    text.push_str(" | ");
                    text.push_str(match kind {
                        0 => "Unknown",
                        1 => "Attack",
                        2 => "Defend",
                        3 => "Buff",
                        4 => "Debuff",
                        5 => "Special",
                        _ => "(no kind)",
                    });
                    if damage >= 0 {
                        text.push_str(&format!(" | {damage} dmg"));
                    } else {
                        text.push_str(" | 伤害非字面量");
                    }
                    Intent { kind, damage, text }
                }
                Ok(None) => Intent::unknown("没有 authored 动作"),
                Err(error) => Intent::unknown(&format!("intent 读不出来: {}", detail(&error))),
            };
            intents.push(intent);
        }
        self.intents = intents;
    }

    /// Walk the hero's hand and remember each slot's definition id and printed cost.
    fn refresh_hand(&mut self) {
        self.hand_defs.clear();
        self.hand_costs.clear();
        let hand_count = self.hand_len();
        for hand_index in 0..hand_count {
            let Some(instance) = self
                .hand_zone()
                .and_then(|zones| zones.slot_at(CardZone::Hand, hand_index))
                .and_then(|slot| self.state.card(slot))
            else {
                continue;
            };
            let def_id = instance.definition_id.as_str().to_string();
            let mut cost = self.printed_energy_cost(&def_id);
            // §161.4: 一张带**每副本价格**的牌，屏幕上必须显示它真的要付的数字，否则玩家看到 2 而
            // 内核收 0 —— 那正是"视图不是状态的投影"那一类谎。钳到 0 与 `play.rs` 的每阶段钳位一致。
            //
            // ⚠️ 这是**显示侧**的第二份定价：`hand_costs` 本来就是"印刷价"的显示副本
            // （`printed_energy_cost` 也自己读了一遍 `Costs`）。它**不**覆盖别的费用修饰器（"下一张
            // 免费"之类），`the_discount_follows_the_copy...` 那条测试把这个差距钉在**可观察**的
            // 层面：显示 0 与真的收 0 必须同时成立。
            if cost > 0 {
                if let Ok(key) = rd_core::state::CounterId::new(
                    rd_core::state::CARD_COST_DELTA_COUNTER,
                ) {
                    let delta = instance
                        .mark_counters()
                        .iter()
                        .find(|counter| counter.key == key)
                        .map_or(0, |counter| counter.value);
                    if delta != 0 {
                        cost = (cost + delta).max(0);
                    }
                }
            }
            self.hand_costs.push(cost);
            self.hand_defs.push(def_id);
        }
    }

    /// Copy the live observation into the buffer `rd_env_observe_buf()` hands to JS.
    ///
    /// ⚠️ This exists because of a real bug: the first version returned `&OBS` from the export but
    /// never wrote `OBS` — the internal `after` vector was correct, every native test passed, and
    /// the page rendered 122 zeros. The native test now asserts the exported buffer agrees with
    /// the internal snapshot, because "the tests pass" was true and irrelevant at the same time.
    fn publish(&self) {
        #[allow(static_mut_refs)]
        unsafe {
            std::ptr::copy_nonoverlapping(
                self.after.as_ptr(),
                std::ptr::addr_of_mut!(OBS) as *mut i32,
                OBS_LEN,
            );
        }
    }

    fn hero_id(&self) -> Option<CombatantId> {
        CombatantId::new(HERO).ok()
    }

    fn is_done(&self) -> bool {
        if self.state.result != CombatResult::Ongoing {
            return true;
        }
        // `env-abi.md` §10: the hero being down is a separate terminal condition — with allies on
        // the field `CombatResult` stays `Ongoing` while nobody can act. v1 has no allies, but the
        // check costs nothing and the rule is the rule.
        match self.hero_id().and_then(|id| self.state.combatant(&id).map(|c| c.lifecycle_state)) {
            Some(CombatantLifecycleState::Alive) => false,
            Some(_) => true,
            None => true,
        }
    }

    fn energy_now(&self) -> i32 {
        self.hero_id()
            .and_then(|id| self.state.combatant(&id))
            .and_then(|c| {
                c.resources()
                    .iter()
                    .find(|p| p.key.as_str() == "standard.energy")
                    .map(|p| p.pool.current)
            })
            .unwrap_or(-1)
    }

    fn hand_zone(&self) -> Option<&rd_core::state::CardZones> {
        let id = self.hero_id()?;
        self.state.card_zones(&id)
    }

    fn hand_len(&self) -> usize {
        self.hand_zone().map_or(0, |z| z.count(CardZone::Hand))
    }

    /// Printed energy cost of a card **definition**, straight out of the image, the same way
    /// `play::calculate_costs` reads it (`Costs` → `_arr` → `{Amount, ResourceId}`).
    ///
    /// This is the *printed* cost, not the cost after modifiers. In this content there are no cost
    /// modifiers (`play.rs`'s `CostStage` pipeline needs `CombatRules`, and all 23 statuses have
    /// `CombatRules` ABSENT), so printed == payable. If that ever stops being true this function
    /// starts lying and the action gate below is still right, because the gate asks
    /// `can_play_card` rather than comparing against this number.
    fn printed_energy_cost(&self, def_id: &str) -> i32 {
        let Ok(def) = rd_core::state::CardDefinitionId::new(def_id) else {
            return -1;
        };
        let Some(entry) = self.content.lookup_in(def.as_str(), EK_CARD) else {
            return -1;
        };
        let Some(row) = self.content.card(u32::from(entry.index)) else {
            return -1;
        };
        // §146：X 费牌印的不是数字。报一个**显式**的哨兵而不是它 `Costs` 里那个 0 ——
        // 后者会让页面显示"0 费"，而那是一句假话（玩家会以为可以随便打）。
        if matches!(self.content.card_has_tag(def.as_str(), X_COST_TAG), Some(true)) {
            return X_COST_DISPLAY;
        }
        let handle = row.costs();
        if handle == ABSENT16 || handle == NULL16 {
            return 0;
        }
        let Some(list) = self.content.term(handle) else {
            return -1;
        };
        if list.op != OP_ARR {
            return -1;
        }
        let (Some(start), Some(count)) = (list.slot(0), list.slot(1)) else {
            return -1;
        };
        if count == LIST_ABSENT || count == LIST_NULL {
            return 0;
        }
        let mut total = 0i32;
        for index in 0..count {
            let Some(cell) = start.checked_add(index) else {
                return -1;
            };
            let Some(element_id) = self.content.aux(cell) else {
                return -1;
            };
            let element = NodeRef::new(self.content, element_id);
            let Ok(Some(resource)) = element.str_field("ResourceId") else {
                continue;
            };
            if resource != "standard.energy" {
                continue;
            }
            match element.int_field("Amount") {
                Ok(Some(amount)) => total = total.saturating_add(amount),
                _ => return -1,
            }
        }
        total
    }

    /// **The enemy roster, derived from the state on every ask.**
    ///
    /// Before this it was `plan.enemies` -- the encounter's opening list, `Box::leak`ed at setup.
    /// That is a *snapshot*, and it is wrong the moment something adds a combatant mid-fight (a
    /// split). The rule this project keeps relearning (`port-plan.md` §8): **a cached derivation
    /// always looks like "somewhere forgot to sync"**. So: read the fight, not the plan.
    ///
    /// Order = the order the state keeps them in (turn order), filtered to the enemy team and
    /// capped at what the ABI can express. The cap is **reported**, not hidden: see
    /// [`Self::enemy_roster_truncated`].
    fn enemy_roster(&self) -> Vec<CombatantId> {
        let mut out = Vec::new();
        for combatant in self.state.combatants() {
            if Some(combatant.id) == self.hero_id() {
                continue;
            }
            if combatant.team_id.as_str() == PLAYER_TEAM {
                continue;
            }
            out.push(combatant.id);
        }
        out
    }

    /// Did the fight have more enemies than the observation can show?
    ///
    /// `env-abi.md` §10 fixes four wall slots. Silently dropping the fifth would be exactly the
    /// "tool reports success" shape this project is trying to stamp out, so the overflow is
    /// observable (`rd_env_enemy_overflow`) even though the vector cannot carry it.
    fn enemy_roster_truncated(&self) -> bool {
        self.enemy_roster().len() > MAX_ENEMY_SLOTS
    }

    /// Kernel ordinal (`state.combatants()` index) → wall slot for the animation log.
    ///
    /// `-1` = the hero, `0..5` = the enemy wall slots the observation uses, `-2` = "not on the
    /// wall" (a combatant past `MAX_ENEMY_SLOTS`, a third team, or `NOBODY`). The wall is the ABI's
    /// business, which is why this lives here and not in the kernel (`port-plan.md` §142).
    fn wall_slot_of_ordinal(&self, ordinal: u8) -> i32 {
        if ordinal == rd_core::beat::NOBODY {
            return -2;
        }
        let Some(combatant) = self.state.combatants().get(usize::from(ordinal)) else {
            return -2;
        };
        if Some(combatant.id) == self.hero_id() {
            return -1;
        }
        for (slot, id) in self.enemy_roster().iter().take(MAX_ENEMY_SLOTS).enumerate() {
            if *id == combatant.id {
                return slot as i32;
            }
        }
        -2
    }

    /// The combatant `whom` names: `-1` = the hero, `0..5` = an enemy **wall slot**.
    ///
    /// `None` for "no such combatant" (an empty slot, a slot past the roster, or `whom < -1`).
    fn combatant_of_wall_slot(&self, whom: i32) -> Option<CombatantId> {
        if whom == -1 {
            return self.hero_id();
        }
        if whom < 0 {
            return None;
        }
        self.enemy_roster().get(whom as usize).copied()
    }

    /// Wall-slot indices of enemies that are still alive (their slots never move — `env-abi.md` §10).
    fn alive_enemy_slots(&self) -> Vec<usize> {
        let mut out = Vec::new();
        for (slot_index, id) in self.enemy_roster().iter().take(MAX_ENEMY_SLOTS).enumerate() {
            let alive = self
                .state
                .combatant(id)
                .map(|c| c.lifecycle_state == CombatantLifecycleState::Alive)
                .unwrap_or(false);
            if alive {
                out.push(slot_index);
            }
        }
        out
    }

    /// The full 122-slot vector. Unoccupied slots are `-1`, not `0` (`env-abi.md` §4: 0 is a real
    /// value — "0 block", "0 stacks" — so it cannot mean "absent").
    fn compute_observation(&self) -> Vec<i32> {
        let mut obs = vec![-1i32; OBS_LEN];
        let roster = self.enemy_roster();

        let hero = self.hero_id().and_then(|id| self.state.combatant(&id).copied());
        obs[H_ROUND] = self.state.current_round;
        obs[H_TURN] = self.state.current_turn;
        obs[H_PHASE] = match self.state.turn_phase {
            CombatTurnPhase::WaitingToStartTurn => 0,
            CombatTurnPhase::TurnInProgress => 1,
        };
        obs[H_RESULT] = match self.state.result {
            CombatResult::Ongoing => 0,
            CombatResult::Victory => 1,
            CombatResult::Defeat => 2,
            CombatResult::Draw => 3,
            CombatResult::Aborted => 4,
        };
        if let Some(hero) = hero.as_ref() {
            obs[H_HERO_HP] = hero.health_current;
            obs[H_HERO_HP_MAX] = hero.health_max;
            obs[H_HERO_BLOCK] = hero
                .defensive_pools()
                .iter()
                .find(|p| p.key.as_str() == "standard.block")
                .map_or(0, |p| p.pool.current);
        }
        // No `ward` pool exists in this content ⇒ "this implementation does not produce it".
        obs[H_HERO_WARD] = -1;
        obs[H_ENERGY] = self.energy_now();
        // §261: 能量的"上限"是**回合补给量**（标准包 3），不是池子上的字段 —— 池子故意没有
        // 天花板（满池加能量仍该给，见 `build_session_at_with` 的注释）。页面要的那个数字
        // 是"这一回合本来该有多少"，所以它来自 `TurnConfig`，与内核那一步的唯一出处相同。
        obs[H_ENERGY_MAX] = HERO_ENERGY_REFILL;
        obs[H_HAND_COUNT] = self.hand_len() as i32;
        obs[H_ENEMY_COUNT] = roster.len().min(MAX_ENEMY_SLOTS) as i32;

        // Hero status axes.
        if let Some(hero) = hero.as_ref() {
            for (axis, status_id) in STATUS_AXES.iter().enumerate() {
                obs[OFF_HERO_STATUS + axis] = hero
                    .statuses()
                    .iter()
                    .find(|s| s.definition_id.as_str() == *status_id)
                    .map_or(0, |s| s.stacks);
            }
        }

        // Enemies ×4, eight slots each.
        for slot_index in 0..MAX_ENEMY_SLOTS {
            let base = OFF_ENEMY + slot_index * 8;
            let Some(enemy_id) = roster.get(slot_index) else {
                continue; // already `-1`
            };
            let combatant = self.state.combatant(enemy_id);
            let Some(combatant) = combatant else {
                continue;
            };
            obs[base] = i32::from(combatant.lifecycle_state == CombatantLifecycleState::Alive);
            obs[base + 1] = combatant.health_current;
            obs[base + 2] = combatant.health_max;
            obs[base + 3] = combatant
                .defensive_pools()
                .iter()
                .find(|p| p.key.as_str() == "standard.block")
                .map_or(0, |p| p.pool.current);
            obs[base + 4] = -1; // ward: not produced (see header)
            // `intent_kind` / `intent_damage`: the content's own answer, recomputed by
            // `refresh_intents` (which `reobserve` runs **before** this).
            let intent = self.intents.get(slot_index);
            obs[base + 5] = intent.map_or(-1, |intent| intent.kind);
            obs[base + 6] = intent.map_or(-1, |intent| intent.damage);
            obs[base + 7] = combatant.statuses().len() as i32;
            for (axis, status_id) in STATUS_AXES.iter().enumerate() {
                obs[OFF_ENEMY_STATUS + slot_index * 5 + axis] = combatant
                    .statuses()
                    .iter()
                    .find(|s| s.definition_id.as_str() == *status_id)
                    .map_or(0, |s| s.stacks);
            }
        }

        // Hand ×10, four slots each: `occupied, cost, def_slot, upgraded`.
        let hand_count = self.hand_len();
        for hand_index in 0..MAX_HAND_SLOTS {
            let base = OFF_HAND + hand_index * 4;
            if hand_index >= hand_count {
                continue; // already `-1`
            }
            let Some(def_id) = self.hand_defs.get(hand_index) else {
                continue;
            };
            let def_slot = self
                .content
                .lookup_in(def_id, EK_CARD)
                .map_or(-1, |entry| i32::from(entry.index));
            obs[base] = 1;
            obs[base + 1] = self.hand_costs.get(hand_index).copied().unwrap_or(-1);
            obs[base + 2] = def_slot;
            obs[base + 3] = 0; // Gap 5: no per-instance upgrade bit in this content
        }

        // Pile counts: these *are* counts, so 0 is meaningful (no `-1` here).
        if let Some(zones) = self.hand_zone() {
            obs[OFF_PILES] = zones.count(CardZone::DrawPile) as i32;
            obs[OFF_PILES + 1] = zones.count(CardZone::Hand) as i32;
            obs[OFF_PILES + 2] = zones.count(CardZone::DiscardPile) as i32;
            obs[OFF_PILES + 3] = zones.count(CardZone::ExhaustPile) as i32;
            obs[OFF_PILES + 4] = zones.count(CardZone::QueuePile) as i32;
        } else {
            for index in 0..5 {
                obs[OFF_PILES + index] = 0;
            }
        }
        // `OFF_RESERVED..OBS_LEN` stays `-1` — "reserved, and this implementation puts nothing
        // there" rather than a 0 that reads like a quantity.

        obs
    }

    /// Enumerate actions from the **already-refreshed** hand (`refresh_hand` must have run).
    ///
    /// Action table (`env-abi.md` §5):
    /// * kind 0 = play hand card. The spec gives *one action per (card, live enemy slot)* with
    ///   `arg1` = the enemy slot, and `arg1 = -1` for cards that cannot target. This
    ///   implementation cannot cheaply classify "is this card targeted" (that needs a walk of the
    ///   program tree), so it emits one action per (playable card × live enemy slot) and passes
    ///   the target through. Over-specifying a target is harmless: a program that reads
    ///   `sel.source` / `sel.allEnemies` ignores `EventTargetId` entirely.
    /// * kind 1 = end turn, only while the hero is the active combatant and the fight is running.
    ///
    /// The gate on "can this card be played" is `play::can_play_card`, which is the **same** code
    /// path the real play takes (`play.rs:503-523` — "抄一份只读校验迟早会和真路径分叉"). That
    /// is why affordability is correctly excluded from the list even though the reference's own
    /// `CanPlay` does not check energy (`env-abi.md` §10).
    ///
    /// ⚠️ This is also the expensive part of a step: `can_play_card` runs the real plan (cost
    /// walk + the 5-validator chain) once per hand card, and `reobserve` runs this twice per step.
    /// Measured: ~20 µs of a ~47 µs step with 5 cards in hand — the bookkeeping costs more than
    /// the fight.
    fn compute_actions(&self) -> Vec<Action> {
        let mut actions = Vec::new();
        if self.is_done() {
            return actions;
        }
        // §161.3: a pending card choice is a **modal** state. Play/end-turn are not legal until it
        // is answered, so listing them would be a table of actions that all get refused -- and a
        // random driver would spin on `-1` forever while the fight looked alive. An empty table is
        // the honest answer ("nothing you can do until you choose"), and `rd_env_choice_pending`
        // is what tells a driver *why*.
        if self.state.pending_choice().is_some() {
            return actions;
        }
        let Some(hero) = self.hero_id() else {
            return actions;
        };

        let alive = self.alive_enemy_slots();
        let roster = self.enemy_roster();
        let hero_is_active = self.state.active_combatant_id.as_ref() == Some(&hero);
        for (hand_index, _def_id) in self.hand_defs.iter().enumerate() {
            let Some(instance_id) = self
                .hand_zone()
                .and_then(|zones| zones.slot_at(CardZone::Hand, hand_index))
                .and_then(|slot| self.state.card(slot))
                .map(|card| card.id)
            else {
                continue;
            };
            // Ask the real play path. Any target works for the question "is it playable", but
            // pass a real one so a target-requiring validator sees what the player would do.
            let target = alive
                .first()
                .and_then(|slot_index| roster.get(*slot_index))
                .copied();
            let request = rd_core::play::PlayRequest {
                source: hero,
                card: instance_id,
                target,
                // §241: a normal play lands where the card's `PlayedCardDestinationZone` says;
                // only a forced play (`Havoc`) overrides it.
                override_destination: None,
                // §253: the page never plays an `unplayable` card — that is the whole point of the
                // tag, and only `node.playCard` with `IgnoreUnplayable` (i.e. `Wish`) may do it.
                ignore_unplayable: false,
            };
            if can_play_card(&self.state, Some(self.content), &request).is_err() {
                continue;
            }
            if alive.is_empty() {
                actions.push(Action {
                    kind: ACTION_PLAY,
                    arg0: hand_index as i32,
                    arg1: -1,
                });
            } else {
                for slot_index in &alive {
                    actions.push(Action {
                        kind: ACTION_PLAY,
                        arg0: hand_index as i32,
                        arg1: *slot_index as i32,
                    });
                }
            }
        }

        // ---- end turn -------------------------------------------------------------------
        if hero_is_active && self.state.result == CombatResult::Ongoing {
            actions.push(Action {
                kind: ACTION_END_TURN,
                arg0: -1,
                arg1: -1,
            });
        }
        actions
    }

/// Run one driver step and fold its problems into `self.problems`.
    // §176: `Step<'_>`, not `Step<'static>` -- the acting enemy may be a **summoned** combatant whose
    // id lives in the state, so the caller has to be able to pass a borrowed id. `run_fight` in the
    // kernel has taken `Step<'_>` all along; only this wrapper was stricter.
    fn exec(&mut self, steps: &[Step<'_>]) -> Result<(), String> {
        self.problems.clear();
        *self.out = FightOutcome::new();
        let out = &mut *self.out;
        let state = &mut *self.state;
        run_fight(state, self.content, &self.plan, steps, &mut self.host, out)
            .map_err(|e| format!("run_fight: {}", detail(&e)))?;
        for index in 0..out.step_count {
            // §152: a swallowed error is only diagnosable if the cause travels with it. The wire
            // text stays `StepThrew` (the reference's word), with the family in parentheses.
            let cause = out.step_causes.get(index).copied().unwrap_or_default();
            for problem in out.problems_of(index) {
                // §152: the family, plus (for `Capacity`) **which** container. The name table
                // lives in `state::Container::name_of` -- one place, not a copy here.
                let cause_name = cause.wire_name();
                // §199: `cause_name == "Capacity"` was the only shape that could name the
                // container, but a **play** that fills one reports the family `Script` and the code
                // `Capacity` -- so the container name has to follow the *code*, not the family.
                let container_code = out.step_capacity.get(index).copied().unwrap_or(0);
                let name: String = if *problem == rd_core::battle::Problem::StepThrew
                    && container_code != 0
                {
                    let container = rd_core::state::Container::name_of(container_code);
                    if container == "?" {
                        "StepThrew(Capacity)".to_string()
                    } else {
                        // The page reads this string; the container name is the actionable half.
                        capacity_problem_text(container).to_string()
                    }
                } else if *problem == rd_core::battle::Problem::StepThrew && !cause_name.is_empty() {
                    // §199: `Script` means `BattleError::Play(_)`/`Deck(_)` -- and under one family
                    // name sit `Refused(Unplayable)` and `Unaffordable { need, have }`, which are
                    // different bugs. The code is already in `step_codes`; spending it here is what
                    // turns `StepThrew(Script)` into `StepThrew(Script:Entangled)`.
                    let code = out.step_codes.get(index).copied().unwrap_or(0);
                    if code == 0 {
                        step_cause_text(cause_name).to_string()
                    } else {
                        format!(
                            "{}({}:{})",
                            "StepThrew",
                            cause_name,
                            rd_core::battle::play_code_name(code)
                        )
                    }
                } else {
                    problem.wire_name().to_string()
                };
                self.problems.push(name);
            }
        }
        Ok(())
    }

    /// `env-abi.md` §5: kind 0 = play the card in hand slot `arg0` at enemy slot `arg1`.
    ///
    /// ⚠️ `Step::HeroPlays` selects the card **by definition id** ("first card in hand with this
    /// definition"), not by instance. That is observably identical here: two cards with the same
    /// definition are indistinguishable in the 122-slot vector (`def_slot`, `cost`, `upgraded` —
    /// no instance id), so "play hand[3]" and "play hand[1]" are the same transition whenever
    /// both are the same definition. Worth writing down because it stops being true the moment
    /// the ABI grows a per-instance quantity (marks, `mark_source_combatant_id`).
    fn step_play(&mut self, hand_index: usize, target_slot: i32) -> Result<(), String> {
        // §161.4: the step names the **instance**, not the definition. `HeroPlays` means "the first
        // card in hand with this definition" (the reference's scenario script is text and has no
        // instance number), so two copies of one definition were indistinguishable -- and the
        // player clicks a hand *position*. A discounted `strike` behind a plain `strike` was
        // unplayable: the button existed, the click played the other copy.
        let Some(instance) = self
            .hand_zone()
            .and_then(|zones| zones.slot_at(CardZone::Hand, hand_index))
            .and_then(|slot| self.state.card(slot))
            .map(|card| card.id)
        else {
            self.error = format!("hand slot {hand_index} is empty");
            return Ok(());
        };
        let target: Option<&'static str> = if target_slot < 0 {
            None
        } else {
            self.plan
                .enemies
                .get(target_slot as usize)
                .map(|enemy| &*Box::leak(enemy.id.to_string().into_boxed_str()))
        };
        self.exec(&[Step::HeroPlaysInstance {
            card: instance,
            target,
        }])
    }

    /// kind 1: end the hero's turn and let **every** enemy take its own turn, then give the round
    /// back to the hero.
    ///
    /// # Why a loop and not one call
    ///
    /// `Step::EndOneTurn` ends **exactly one** turn: the action seat moves to the next *living*
    /// combatant and stops there (its whole point — a multi-enemy fight where each enemy gets a
    /// turn instead of `NextRound` skipping over them). So one click is:
    ///
    /// ```text
    /// EndOneTurn                      hero's turn ends → enemy[0] is active
    /// loop while the active seat is not the hero:
    ///     EnemyActs{active, action, hero}   ← the action comes from the content, not from here
    ///     EndOneTurn                        that enemy's turn ends → enemy[1] … or the hero
    /// ```
    ///
    /// Two things are *not* done here on purpose:
    /// * the action is not chosen from `self.intents` (the preview) — it is asked again, now, with
    ///   the state the enemy actually starts its turn with. §2.4 fork 2 of
    ///   `docs/spec/enemy-intent.md`: the preview is computed during the hero's turn, and
    ///   turn-end/turn-start (block cleared, DoT eaten, statuses expiring) can change an answer.
    ///   Reusing the preview would make the page *look* consistent and be wrong.
    /// * no "plan has N enemies" refusal: the reason for it was `NextRound`, which is gone.
    fn step_end_turn(&mut self) -> Result<(), String> {
        let Some(hero) = self.hero_id() else {
            return Err("hero id is not constructible".to_string());
        };
        if self.state.active_combatant_id.as_ref() != Some(&hero)
            || self.state.result != CombatResult::Ongoing
        {
            self.error = "it is not the hero's turn".to_string();
            return Ok(());
        }

        self.exec(&[Step::EndOneTurn])?;
        // `plan.enemies.len() + 2` turns is the whole round plus the hero's own two hops; if the
        // seat is still not the hero after that, the turn order is not making progress and that
        // must be loud rather than a hang in the browser.
        let mut hops = 0usize;
        let limit = self.plan.enemies.len() + 2;
        while self.state.result == CombatResult::Ongoing {
            let Some(active) = self.state.active_combatant_id else {
                return Err("回合机没有活跃战斗员".to_string());
            };
            if active.as_str() == HERO {
                return Ok(());
            }
            hops += 1;
            if hops > limit {
                return Err(format!("结束回合在 {limit} 跳内没有回到英雄身上"));
            }
            // `active` is a **copy** (`CombatantId` is `Copy`), so borrowing its text here does not
            // borrow the state that `exec` mutates below.
            let raw_id: &str = active.as_str();
            let action = self.action_for(&active)?;
            // `None` = this enemy has no authored action (`Actions` empty and no rule matched).
            // The reference has nothing to execute either; the turn still ends — it does not get
            // to act twice, and skipping the whole turn would be a different rule.
            if let Some(choice) = action {
                // §174: a **thrown** enemy action is recorded as `StepThrew` by the driver (it does
                // not `Err`), so this cannot use `?` -- the loop has to keep going, or the fight is
                // left with that enemy as the active combatant and nobody able to advance it. That
                // was a real two-hour deadlock: Lagavulin's Siphon Soul applied *negative stacks*,
                // the program threw, and the run froze at "round 5 · turn 2" with no button to press.
                self.exec(&[Step::EnemyActs {
                    enemy: raw_id,
                    action: choice,
                    target: Some(HERO),
                }])?;
                if self.state.result != CombatResult::Ongoing {
                    return Ok(());
                }
            }
            // A throw can leave the phase at `WaitingToStartTurn` (the enemy's turn never legally
            // began). Ending a turn that has not started is refused by the turn machine, which would
            // spin this loop to its hop limit; starting it first makes the end legal. Idempotent.
            if self.state.turn_phase == rd_core::state::CombatTurnPhase::WaitingToStartTurn {
                let config = standard_turn_config()
                    .map_err(|e| format!("standard_turn_config: {}", detail(&e)))?;
                start_first_turn(&mut self.state, &config, &mut self.host)
                    .map_err(|e| format!("start_first_turn: {}", detail(&e)))?;
            }
            self.exec(&[Step::EndOneTurn])?;
        }
        Ok(())
    }

    /// The `EACT` id this combatant will use **now** (nil = no authored action).
    ///
    /// §176: a combatant created by `node.createCombatant` (split / summon) is not in this encounter's
    /// enemy list, so the encounter-indexed selector cannot answer for it. Its actions come from the
    /// content's enemy records by **definition id** (`ENCT[*].Enemies[j].Id`), and the rotation is the
    /// same `Actions[(round - 1) % len]` the kernel falls back to when no `IntentRule` matches.
    fn action_for(&self, actor: &CombatantId) -> Result<Option<&'static str>, String> {
        if let Some(at) = locate_enemy(self.content, self.encounter, actor)
            .map_err(|error| format!("locate_enemy: {}", detail(&error)))?
        {
            let choice =
                select_action(&self.state, self.content, at, actor, self.state.current_round)
                    .map_err(|error| format!("select_action: {}", detail(&error)))?;
            return Ok(choice.map(|choice| choice.action_id));
        }
        let actions = self.summoned_actions(actor)?;
        if actions.is_empty() {
            return Ok(None);
        }
        let round = self.state.current_round.max(1) as usize;
        Ok(actions.get((round - 1) % actions.len()).copied())
    }

    /// The action list an encounter record gives for this combatant's **definition id** (§176).
    ///
    /// Scanning every encounter is cheap (27 rows, each a handful of records) and it is the only place
    /// the content keeps "which actions does this monster have": the image has no monster table.
    fn summoned_actions(&self, actor: &CombatantId) -> Result<Vec<&'static str>, String> {
        let Some(combatant) = self.state.combatant(actor) else {
            return Ok(Vec::new());
        };
        let definition = combatant.definition_id.as_str();
        // `ENCT` is a fixed table: walk it with `Encounter` rows until one is absent.
        let encounters = self
            .content
            .section(rd_core::content::S_ENCT)
            .map_or(0, |section| section.count);
        for index in 0..encounters {
            let Ok(enemies) = self.content.encounter_enemies(index as u32) else {
                continue;
            };
            for spec in enemies.iter() {
                let Ok(spec) = spec else { continue };
                if spec.id().ok() != Some(definition) {
                    continue;
                }
                let Ok(list) = spec.actions() else { continue };
                let mut out = Vec::with_capacity(list.len());
                for slot in 0..list.len() {
                    if let Some(action) = list.string(slot) {
                        out.push(action);
                    }
                }
                if !out.is_empty() {
                    return Ok(out);
                }
            }
        }
        Ok(Vec::new())
    }

    /// `env-abi.md` §7 + §10: `1000*(enemy hp lost) - 1000*(hero hp lost) - 10*(wasted energy)`.
    /// "Wasted energy" is the hero's **remaining** energy on an end-turn step, 0 otherwise.
    fn compute_reward(&self, was_end_turn: bool) -> i32 {
        let enemy_total = |obs: &[i32]| -> i32 {
            let mut total = 0;
            for slot_index in 0..MAX_ENEMY_SLOTS {
                let base = OFF_ENEMY + slot_index * 8;
                if obs[base] < 0 {
                    continue; // unoccupied slot
                }
                total += obs[base + 1];
            }
            total
        };
        let enemy_lost = enemy_total(&self.before) - enemy_total(&self.after);
        // Clamped at 0: a *gain* in enemy HP is not a negative reward in this formula.
        let enemy_lost = enemy_lost.max(0);
        let hero_lost = self.before[H_HERO_HP].max(0) - self.after[H_HERO_HP].max(0);
        let hero_lost = hero_lost.max(0);
        let wasted = if was_end_turn {
            self.after[H_ENERGY].max(0)
        } else {
            0
        };
        1000 * (enemy_lost - hero_lost) - 10 * wasted
    }
}

// =============================================================================================
// The exported ABI
// =============================================================================================

/// `rd_env_observe_len()`.
#[no_mangle]
pub extern "C" fn rd_env_observe_len() -> i32 {
    OBS_LEN as i32
}

/// The address of the observation buffer.
///
/// Not in the frozen ABI — it is here so JS can avoid shipping a malloc: `new
/// Int32Array(memory.buffer, rd_env_observe_buf(), rd_env_observe_len())` reads the observation
/// with zero copies. `rd_env_observe_into` exists too, for callers that do own a buffer.
#[no_mangle]
pub extern "C" fn rd_env_observe_buf() -> *const i32 {
    // `addr_of!` is safe; it is the *dereference* that would not be.
    std::ptr::addr_of!(OBS) as *const i32
}

/// `rd_env_observe_into(ptr)` — copies `OBS_LEN` `i32`s to `ptr`. Returns the count written.
///
/// # Safety
///
/// `ptr` must point at `OBS_LEN * 4` writable bytes inside this module's linear memory.
#[no_mangle]
pub unsafe extern "C" fn rd_env_observe_into(ptr: *mut i32) -> i32 {
    if ptr.is_null() {
        return -1;
    }
    // **Recompute before copying.** `OBS` used to be a snapshot published only by `rd_env_step`, so
    // *any* mutation made outside that path left the vector stale -- a potion use, the fight's
    // starting health, and (the visible bug) the page's battle log, which is a diff of two
    // observations and therefore blamed the first card for damage that happened before the fight.
    // Patched three times at three call sites; this is the fix that makes the class impossible: the
    // observation is now derived at read time, so it cannot disagree with the state.
    if let Some(session) = slot().as_mut() {
        session.reobserve_after_external_change();
    }
    #[allow(static_mut_refs)]
    {
        std::ptr::copy_nonoverlapping(std::ptr::addr_of!(OBS) as *const i32, ptr, OBS_LEN);
    }
    OBS_LEN as i32
}

/// `rd_env_done()` — 1 when the fight is over or the hero is down.
#[no_mangle]
pub extern "C" fn rd_env_done() -> i32 {
    match ensure_session() {
        Ok(session) => i32::from(session.is_done()),
        Err(_) => 1,
    }
}

/// `rd_env_result()` — 0 undecided / 1 victory / 2 defeat (`CombatResult` order).
#[no_mangle]
pub extern "C" fn rd_env_result() -> i32 {
    let Ok(session) = ensure_session() else {
        return 0;
    };
    match session.state.result {
        CombatResult::Ongoing => 0,
        CombatResult::Victory => 1,
        CombatResult::Defeat | CombatResult::Draw | CombatResult::Aborted => 2,
    }
}

/// `rd_env_reset()` — rebuild the fight at the same seed. 0 on success, negative on failure.
#[no_mangle]
/// §203: **build a fight from an arbitrary encounter by name** (debug surface).
///
/// Why this exists: the browser gates can only fight what the run happens to roll, and the act-2 /
/// act-3 content (Bronze Automaton's summoned orbs, Reptomancer's daggers) is behind ~30 nodes of
/// walking plus a won act. A checker that has to *win two acts* to see an act-3 screen is not a
/// checker -- it is a coin toss that fails on unrelated content changes.
///
/// It is the same shape as `startWithSeed` / `givePotion`: a **measured affordance** behind
/// `?debug`, not a game action. It builds through `build_session_at`, i.e. the same path
/// `rd_env_reset` uses (dedupe ids, `Spawn: false`, `Owner`, starting statuses), so it cannot
/// invent a fight the run layer could not build.
///
/// Returns `0` on success, `-1` with `last_error` on a bad name.
///
/// # Safety
///
/// `ptr` must point at `len` readable bytes (UTF-8, the encounter id).
#[no_mangle]
pub unsafe extern "C" fn rd_env_start_encounter(ptr: *const u8, len: i32) -> i32 {
    if len < 0 || ptr.is_null() {
        return -1;
    }
    let bytes = core::slice::from_raw_parts(ptr, len as usize);
    let Ok(name) = core::str::from_utf8(bytes) else {
        return -1;
    };
    // The name has to outlive the `FightPlan` (it borrows it for the session's life), which is the
    // same `Box::leak` the run layer already pays for one fight.
    let leaked: &'static str = Box::leak(name.to_string().into_boxed_str());
    // A **heavy** hero on purpose: these fights exist so a gate can *watch* the content (a summon
    // arriving, a dagger removing itself), not so it can win. With `HERO_HP` the driver died to the
    // Reptomancer before either dagger reached its Explode turn, and the gate then measured the
    // wrong thing -- `DEBUG_HERO_HP` is the smallest fix that keeps the observation about content.
    match build_session_at(SEED, leaked, DEBUG_HERO_HP, None, 0, 0) {
        Ok(session) => {
            *slot() = Some(session);
            0
        }
        Err(message) => {
            if let Some(session) = slot().as_mut() {
                session.error.clear();
                session.error.push_str(&message);
            }
            -1
        }
    }
}

#[no_mangle]
pub extern "C" fn rd_env_reset() -> i32 {
    match build_session(SEED) {
        Ok(session) => {
            *slot() = Some(session);
            0
        }
        Err(message) => {
            if let Some(session) = slot().as_mut() {
                session.error = message;
            }
            -3
        }
    }
}

/// How many times a turn has been cut short so far (`node.endTurn`), or `-1` with no session.
///
/// The page polls this: a value bigger than the last one it saw means "your turn was ended by
/// something", which is information the observation vector deliberately does not carry.
/// §174：**上一步为什么没做完**（`run_fight` 的 `problems`，第一条），写进 scratch。
///
/// 驱动会把"这一步抛了"吞成 `StepThrew` 并继续 —— 于是`回合启动失败`这类错误在页面上只剩一个
/// 数字。这条出口让那次失败有话说。
#[no_mangle]
pub extern "C" fn rd_env_problem_len() -> i32 {
    let Some(session) = slot().as_ref() else {
        return -1;
    };
    let text = session.problems.first().map(String::as_str).unwrap_or("");
    write_scratch(text.as_bytes()) as i32
}

/// # Safety
///
/// `ptr` must point at `rd_env_problem_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_env_problem_into(ptr: *mut u8) -> i32 {
    let len = rd_env_problem_len();
    if len < 0 {
        return len;
    }
    std::ptr::copy_nonoverlapping(crate::SCRATCH.as_ptr(), ptr, len as usize);
    len
}

/// §177：第 `index` 步的 `Deck`/`Play` 拒绝码（`0` = 没有），`-1` = 越界或没有会话。
///
/// `StepThrew(Script)` 只说了家族，而"哪一张牌、哪一条拒因"才是能动手的信息。
#[no_mangle]
pub extern "C" fn rd_env_step_code(index: i32) -> i32 {
    let Some(session) = slot().as_ref() else {
        return -1;
    };
    if index < 0 {
        return -1;
    }
    session
        .out
        .step_codes
        .get(index as usize)
        .map_or(-1, |code| i32::from(*code))
}

/// §177：拒绝码的名字，写进 scratch，返回长度（`play_code_name` 的那张表，内核里只有一份）。
#[no_mangle]
pub extern "C" fn rd_env_code_name_len(code: i32) -> i32 {
    let name = rd_core::battle::play_code_name(u8::try_from(code).unwrap_or(0));
    write_scratch(name.as_bytes()) as i32
}

/// # Safety
///
/// `ptr` must point at `rd_env_code_name_len(code)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_env_code_name_into(code: i32, ptr: *mut u8) -> i32 {
    let len = rd_env_code_name_len(code);
    if len < 0 {
        return len;
    }
    std::ptr::copy_nonoverlapping(crate::SCRATCH.as_ptr(), ptr, len as usize);
    len
}

/// §177：宿主**上一次失败**的完整原因，写进 scratch，返回长度（`0` = 没有失败）。
///
/// `TurnError::Host` 只带五个**家族**之一，细节（哪个 `IrError`、哪个容器满了）留在
/// `Host::last_failure()`——`turn.rs` 的文档明说"细节在宿主自己保管，不会丢"，而在此之前
/// **没有任何导出读它**。实测它就写着 `Exec(Capacity(Full(Combatants)))`。
#[no_mangle]
pub extern "C" fn rd_env_host_failure_len() -> i32 {
    let Some(session) = slot().as_ref() else {
        return -1;
    };
    match session.host.last_failure() {
        Some(failure) => write_scratch(detail(&failure).as_bytes()) as i32,
        None => 0,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_env_host_failure_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_env_host_failure_into(ptr: *mut u8) -> i32 {
    let len = rd_env_host_failure_len();
    if len <= 0 {
        return len;
    }
    std::ptr::copy_nonoverlapping(crate::SCRATCH.as_ptr(), ptr, len as usize);
    len
}

/// §174：**谁在行动**（`active_combatant_id`），写进 scratch，返回长度。`-1` = 没有会话。
///
/// 这一格存在的理由是一个真实的两小时：soak 抓到"敌方回合跑不完"的死锁，而观察向量里没有
/// "现在是谁的回合"——只有 `round`/`turn`/`phase`，于是只能猜。诊断出口比再猜一轮便宜。
#[no_mangle]
pub extern "C" fn rd_env_active_len() -> i32 {
    let Some(session) = slot().as_ref() else {
        return -1;
    };
    let text = session
        .state
        .active_combatant_id
        .map(|id| id.as_str().to_string())
        .unwrap_or_default();
    write_scratch(text.as_bytes()) as i32
}

/// # Safety
///
/// `ptr` must point at `rd_env_active_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_env_active_into(ptr: *mut u8) -> i32 {
    let len = rd_env_active_len();
    if len < 0 {
        return len;
    }
    std::ptr::copy_nonoverlapping(crate::SCRATCH.as_ptr(), ptr, len as usize);
    len
}

/// 把字节写进 scratch，返回长度（`rd_env_active_len` 的实体）。
fn write_scratch(bytes: &[u8]) -> usize {
    #[allow(static_mut_refs)]
    unsafe {
        let len = bytes.len().min(crate::SCRATCH.len());
        crate::SCRATCH[..len].copy_from_slice(&bytes[..len]);
        len
    }
}

#[no_mangle]
pub extern "C" fn rd_env_forced_turns() -> i32 {
    match ensure_session() {
        Ok(session) => session.state.forced_turn_ends,
        Err(_) => -1,
    }
}

/// Was enemy slot `slot` **summoned** (rather than placed by the encounter)?
///
/// `1` yes, `0` no, `-1` no such slot. The observation has no bit for this, and the page needs it to
/// mark a minion as one (`port-plan.md` §140).
#[no_mangle]
pub extern "C" fn rd_env_enemy_is_minion(slot: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    if slot < 0 {
        return -1;
    }
    let roster = session.enemy_roster();
    let Some(id) = roster.get(slot as usize) else {
        return -1;
    };
    match session.state.combatant(id) {
        Some(combatant) => i32::from(combatant.owner.is_some()),
        None => -1,
    }
}

/// Did the fight hold more enemies than the observation can show?
///
/// `0` = no, `1` = yes, `-1` = no session. The vector cannot grow past `MAX_ENEMY_SLOTS` without
/// moving every offset after it, so the overflow is **reported** rather than silently dropped --
/// the same rule this project applies to every other capacity.
#[no_mangle]
pub extern "C" fn rd_env_enemy_overflow() -> i32 {
    match ensure_session() {
        Ok(session) => i32::from(session.enemy_roster_truncated()),
        Err(_) => -1,
    }
}

/// `rd_env_action_count()`.
#[no_mangle]
pub extern "C" fn rd_env_action_count() -> i32 {
    match ensure_session() {
        Ok(session) => session.actions.len() as i32,
        Err(_) => 0,
    }
}

/// `rd_env_action_kind(i)` — `-1` when out of range.
#[no_mangle]
pub extern "C" fn rd_env_action_kind(index: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    session
        .actions
        .get(index.max(0) as usize)
        .map_or(-1, |action| action.kind)
}

/// `rd_env_action_arg(i, which)` — `which` is 0 or 1; `-1` when out of range.
#[no_mangle]
pub extern "C" fn rd_env_action_arg(index: i32, which: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    let Some(action) = session.actions.get(index.max(0) as usize) else {
        return -1;
    };
    match which {
        0 => action.arg0,
        1 => action.arg1,
        _ => -1,
    }
}

/// `rd_env_step(i)` — `0` accepted, `-1` **rejected with the observation unchanged**, `-2`
/// already finished, `-3` the driver itself broke.
///
/// The `-1` test is the observation diff, not "did the engine report a problem" — that is
/// `env-abi.md` §10's ruling, and implementing it literally is what makes "rejected ⇒ unchanged"
/// a construction rather than a promise.
#[no_mangle]
pub extern "C" fn rd_env_step(index: i32) -> i32 {
    let session = match ensure_session() {
        Ok(session) => session,
        Err(_) => return -3,
    };
    // §142: the animation log describes **this action only**, so it is cleared *before* the
    // action is even looked up. Clearing it further down would leave the previous action's beats
    // in place after a refused step -- and stale beats replay perfectly, they just replay the
    // wrong thing. "Refused ⇒ nothing happened" has to hold for the log too.
    session.error.clear();
    session.state.clear_beats();
    if session.is_done() {
        return -2;
    }
    // §161.3: `compute_actions` is empty while a choice is pending, so this is unreachable through
    // the table -- which is exactly why it is written: a driver holding a **stale** action index
    // would otherwise play a card through the open question. It sits *before* the table lookup so
    // the refusal has a reason (an out-of-range index would otherwise return the same `-1` with
    // nothing said).
    if session.state.pending_choice().is_some() {
        session.error = "还有一次待决的选牌没回答".to_string();
        return -1;
    }
    let Some(action) = session.actions.get(index.max(0) as usize).copied() else {
        return -1;
    };

    session.reobserve();
    session.before.copy_from_slice(&session.after);
    let energy_before = session.energy_now();

    let outcome = match action.kind {
        ACTION_PLAY => session.step_play(action.arg0.max(0) as usize, action.arg1),
        ACTION_END_TURN => session.step_end_turn(),
        other => Err(format!("unknown action kind {other}")),
    };
    if let Err(message) = outcome {
        session.error = message;
        return -3;
    }

    session.reobserve();
    let was_end_turn = action.kind == ACTION_END_TURN;
    session.reward = session.compute_reward(was_end_turn);
    // `compute_reward` reads `before`/`after`; the energy it needs is the *pre-step* one.
    let _ = energy_before;

    if session.before == session.after {
        // The refusal reason is the driver's problem list when there is one — "CardNotPlayed" is
        // infinitely more useful than "rejected", and `env-abi.md` §10 explicitly says a problem
        // is an *observation*, so naming them is not inventing a failure.
        session.error = if session.problems.is_empty() {
            "步后观察逐项未变 ⇒ 按 env-abi §10 判为拒绝".to_string()
        } else {
            session.problems.join(",")
        };
        session.reward = 0;
        return -1;
    }
    0
}

/// `rd_env_reward()` — last step's reward in 1/1000.
#[no_mangle]
pub extern "C" fn rd_env_reward() -> i32 {
    match ensure_session() {
        Ok(session) => session.reward,
        Err(_) => 0,
    }
}

/// `rd_env_last_error_len()` — byte length of the human-readable reason for the last failure.
#[no_mangle]
pub extern "C" fn rd_env_last_error_len() -> i32 {
    let message = match ensure_session() {
        Ok(session) => session.error.clone(),
        // A build failure has no session to put the message in — hand it out of the scratch
        // buffer instead, and make the buffer size the only cap.
        Err(message) => message,
    };
    #[allow(static_mut_refs)]
    unsafe {
        let bytes = message.as_bytes();
        let len = bytes.len().min(SCRATCH.len());
        SCRATCH[..len].copy_from_slice(&bytes[..len]);
        len as i32
    }
}

/// The address of a 1 KiB scratch area, so JS can receive variable-length text without a malloc.
///
/// Not in the frozen ABI — it is the "caller owns the buffer" half of the `_len`/`_into` pair,
/// made usable from a language that has no allocator of ours.
#[no_mangle]
pub extern "C" fn rd_env_scratch_buf() -> *mut u8 {
    std::ptr::addr_of_mut!(SCRATCH) as *mut u8
}

/// `rd_env_last_error_into(ptr)` — copies the error text (UTF-8) to `ptr`. Returns bytes written.
///
/// # Safety
///
/// `ptr` must point at `rd_env_last_error_len()` writable bytes in linear memory.
#[no_mangle]
pub unsafe extern "C" fn rd_env_last_error_into(ptr: *mut u8) -> i32 {
    if ptr.is_null() {
        return -1;
    }
    let Ok(session) = ensure_session() else {
        return 0;
    };
    let bytes = session.error.as_bytes();
    // Capped at the scratch size so `len` and `into` can never disagree about how much text
    // exists — a `_len`/`_into` pair that disagrees is how a caller ends up reading stale bytes.
    let len = bytes.len().min(1024);
    std::ptr::copy_nonoverlapping(bytes.as_ptr(), ptr, len);
    len as i32
}

// =============================================================================================
// Card text -- the title and the description the content already carries
// =============================================================================================
//
// `CARD` has had `NameKey` (cell 9) and `DescriptionKey` (cell 10) all along; the page only ever
// asked for the *id* (`rd_env_card_name_*`), so a card face could say "strike" and nothing else.
// The content's own strings are the authoritative description -- `"Deal 6 damage."`,
// `"Gain 5 Block."` -- and reading them beats deriving the text from the program tree: a derived
// string is mechanical ("dealDamage 6") and a hand-written one is a second place to lie, while
// this one *is* what the card says.
//
// These are presentation exports like `rd_env_card_name_*`: the observation vector still carries
// `def_slot`, and nothing in the kernel's semantics depends on them.

/// The `CARD` row behind hand slot `index`, or `None` if the slot is empty or its definition is
/// not in the image.
fn card_row_at(session: &Session, index: usize) -> Option<rd_core::content::CardRow<'static>> {
    let definition = session.hand_defs.get(index)?;
    let entry = session.content.lookup_in(definition, rd_core::content::EK_CARD)?;
    let row = session.content.row(rd_core::content::Table::Card, entry.index as u32)?;
    rd_core::content::CardRow::new(row)
}

/// A string cell of a card row, resolved through the string pool. `None` when the cell is absent
/// (an absent cell is `ABSENT16`, which is not a valid string index).
fn card_cell(
    session: &Session,
    row: &rd_core::content::CardRow<'static>,
    cell: usize,
) -> Option<&'static str> {
    session.content.string(row.row().cell(cell as u32)?)
}

/// The card's **title** (`NameKey`). `None` when the content does not carry one -- the page falls
/// back to the definition id, which it already has, rather than this inventing a placeholder.
fn card_title(session: &Session, index: usize) -> Option<&'static str> {
    let row = card_row_at(session, index)?;
    card_cell(session, &row, 9)
}

/// The card's **description** (`DescriptionKey`). `None` when the card has none, which the page
/// shows as "no text" instead of inventing one.
fn card_text(session: &Session, index: usize) -> Option<&'static str> {
    let row = card_row_at(session, index)?;
    card_cell(session, &row, 10).filter(|text| !text.is_empty())
}

/// Copy `text` into `ptr`, returning the bytes written.
///
/// # Safety
///
/// `ptr` must point at `text.len()` writable bytes in linear memory; the JS side always passes the
/// buffer it sized from the matching `_len` call.
unsafe fn copy_text_out(text: &str, ptr: *mut u8) -> i32 {
    if ptr.is_null() {
        return 0;
    }
    let bytes = text.as_bytes();
    for (offset, &byte) in bytes.iter().enumerate() {
        *ptr.add(offset) = byte;
    }
    bytes.len() as i32
}

/// The title of the card in hand slot `index` — `rd_env_card_title_len(index)`.
#[no_mangle]
pub extern "C" fn rd_env_card_title_len(index: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    if index < 0 {
        return -1;
    }
    card_title(session, index as usize).map_or(-1, |text| text.len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_env_card_title_len(index)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_env_card_title_into(index: i32, ptr: *mut u8) -> i32 {
    let Ok(session) = ensure_session() else {
        return 0;
    };
    if index < 0 {
        return 0;
    }
    match card_title(session, index as usize) {
        Some(text) => unsafe { copy_text_out(text, ptr) },
        None => 0,
    }
}

/// The description of the card in hand slot `index` — `rd_env_card_text_len(index)`.
#[no_mangle]
pub extern "C" fn rd_env_card_text_len(index: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    if index < 0 {
        return -1;
    }
    card_text(session, index as usize).map_or(-1, |text| text.len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_env_card_text_len(index)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_env_card_text_into(index: i32, ptr: *mut u8) -> i32 {
    let Ok(session) = ensure_session() else {
        return 0;
    };
    if index < 0 {
        return 0;
    }
    match card_text(session, index as usize) {
        Some(text) => unsafe { copy_text_out(text, ptr) },
        None => 0,
    }
}

// =============================================================================================
// Pile contents (the page's "draw / discard / exhaust" panels)
// =============================================================================================
//
// The 122-slot observation carries pile **counts** only (`env-abi.md` §4), which is right for a
// policy and useless for a player who wants to know *what* is in the discard pile. These read the
// piles directly. Zone ids match `ui_render.js`: 0 = draw, 1 = discard, 2 = exhaust.

/// Zone ids, as `ui_render.js` spells them: 0 = draw, 1 = discard, 2 = exhaust, **3 = the
/// pending card choice's source pile** (§161.3).
///
/// Id 3 is dynamic on purpose: the picker renders the same card faces the pile viewer does, and a
/// fourth static pile would have to be kept in sync with "which pile is the question about". The
/// one thing a caller must know is that id 3 answers **nothing** when no choice is pending, which
/// is why it returns `None` instead of an empty pile.
///
/// §161.5: an `Offered` question has **no pile** -- its options are three card *definitions* that do
/// not exist as instances yet. So id 3 answers `None` for it here, and the readers below take the
/// offered branch **before** asking this function. Keeping the two apart is what stops "no pile"
/// from decaying into "an empty pile".
fn pile_zone(session: &Session, zone: i32) -> Option<CardZone> {
    match zone {
        0 => Some(CardZone::DrawPile),
        1 => Some(CardZone::DiscardPile),
        2 => Some(CardZone::ExhaustPile),
        3 => session.state.pending_choice().and_then(|choice| choice.source.zone()),
        _ => None,
    }
}

/// How many cards are in `zone` (0 = draw, 1 = discard, 2 = exhaust); `-1` for a bad zone.
#[no_mangle]
pub extern "C" fn rd_env_pile_len(zone: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    // §161.5: the offered question has no pile, so it is answered **before** `pile_zone` -- and
    // only when no pile question is pending (the two can never be pending at once).
    if zone == 3 {
        if let Ok(offered) = session.state.choice_offered() {
            return offered.len() as i32;
        }
    }
    let Some(zone) = pile_zone(session, zone) else {
        return -1;
    };
    let Some(hero) = session.hero_id() else {
        return -1;
    };
    session
        .state
        .card_zones(&hero)
        .map_or(-1, |zones| zones.count(zone) as i32)
}

/// The definition id of card `index` in `zone`.
#[no_mangle]
pub extern "C" fn rd_env_pile_card_id_len(zone: i32, index: i32) -> i32 {
    match pile_card_id(zone, index) {
        Some(id) => id.len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_env_pile_card_id_len(zone, index)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_env_pile_card_id_into(zone: i32, index: i32, ptr: *mut u8) -> i32 {
    match pile_card_id(zone, index) {
        Some(id) => {
            let bytes = id.as_bytes();
            for (offset, &byte) in bytes.iter().enumerate() {
                *ptr.add(offset) = byte;
            }
            bytes.len() as i32
        }
        None => 0,
    }
}

/// The **title** of card `index` in `zone` (`CARD.NameKey`, falling back to the id).
#[no_mangle]
pub extern "C" fn rd_env_pile_card_title_len(zone: i32, index: i32) -> i32 {
    match pile_card_id(zone, index) {
        Some(id) => card_display_title(id.as_str()).len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_env_pile_card_title_len(zone, index)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_env_pile_card_title_into(zone: i32, index: i32, ptr: *mut u8) -> i32 {
    match pile_card_id(zone, index) {
        Some(id) => {
            let title = card_display_title(id.as_str());
            let bytes = title.as_bytes();
            for (offset, &byte) in bytes.iter().enumerate() {
                *ptr.add(offset) = byte;
            }
            bytes.len() as i32
        }
        None => 0,
    }
}

// =============================================================================================
//
// §161.3: the pending card choice.
//
// Elixir and Gambler's Brew do not resolve inside `rd_env_use_potion` -- they **ask a question**:
// the potion returns `0` with `rd_env_choice_pending() == 1`, the action table goes empty, and the
// only way on is `rd_env_choice_confirm`. The options are the source pile, so the picker renders
// through the **existing** pile exports with zone id `3` instead of a parallel set of string
// getters (a fourth copy of "read a card's title" would be a fourth thing to keep in sync).
//
// The tick list lives in `Session::choice_picks`, deliberately **not** in `CombatState`: the
// kernel's action is the whole selection handed over at once, so a half-finished selection is not
// something a save file has to describe, and `resolve_choice` can stay atomic.

/// Report a refusal through the **fight** session's error buffer and return `-2`.
///
/// `run.rs` has an almost-identically-named `refuse`, which writes to the *run* slot instead: the
/// two slots are separate error surfaces on purpose (a fight can refuse while the run is fine), and
/// one helper for two sinks would put the message where the page does not look.
fn refuse_with_text(message: &str) -> i32 {
    if let Some(session) = slot().as_mut() {
        session.error = message.to_string();
    }
    -2
}

/// The per-copy price that makes one card free: `-printed`, or a **refusal** when that cannot be
/// said.
///
/// `X_COST_DISPLAY` is a **sentinel, not a price**: an X-cost card pays "all your energy" and never
/// touches the `Costs` table, so a delta on it is invisible -- the card would be handed over
/// advertised as free and then charge everything. Refusing keeps the question open (nothing
/// changes), so the page can say "pick another one".
fn priced_delta(session: &Session, definition: &str) -> Result<i32, std::string::String> {
    let printed = session.printed_energy_cost(definition);
    // §161.5: **0 费不是错误**。`anger` / `swift_strike` 印刷就是 0，那瓶药承诺的"它这次免费"
    // 已经成立 —— 给它一个 `-0` 的折扣是正确回答，而不是"没有可取消的费用"。
    if printed == 0 {
        return Ok(0);
    }
    if printed < 0 || printed == X_COST_DISPLAY {
        // `-1` = 印的代价读不出来；`X_COST_DISPLAY` = X 费牌（按全部能量结算，`Costs` 表对它
        // 没有意义 ⇒ 加在上面的 delta 看不见）。这两种都**说不出口**，所以拒绝并让问句留着。
        return Err(std::format!(
            "这张牌的费用说不出口（X 费牌按全部能量结算），换一张"
        ));
    }
    Ok(-printed)
}

/// Is the kernel waiting for a card choice? `1` yes, `0` no, `-1` no session.
#[no_mangle]
pub extern "C" fn rd_env_choice_pending() -> i32 {
    match ensure_session() {
        Ok(session) => i32::from(session.state.pending_choice().is_some()),
        Err(_) => -1,
    }
}

/// What answering does with the picked cards: `1` exhaust, `2` discard-then-draw, `0`/`-1` nothing.
///
/// The numbers are the kind the page needs to write the right sentence ("消耗" vs "丢弃并抽").
/// They are **not** `ChoiceThen as i32`: that enum is rd-core's internal numbering, and an ABI
/// number that silently follows a Rust enum is the same shape as an `as i32` cast over a
/// `#[repr(u8)]` that someone reorders.
#[no_mangle]
pub extern "C" fn rd_env_choice_kind() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    match session.state.pending_choice() {
        Some(choice) => match choice.then {
            ChoiceThen::Exhaust => 1,
            ChoiceThen::DiscardThenDraw => 2,
            // §161.4: "take it into your hand and make it free" (Liquid Memories). A **new number**
            // rather than reusing one, because the page writes the sentence from it.
            ChoiceThen::ToHand => 3,
            // §226: **copy** what was picked (Dual Wield). Again a new number: "复制" is a different
            // sentence from "拿进手牌", and the copies are printed-price (no `cost_delta`).
            ChoiceThen::Copy { .. } => 4,
            // §227: "upgrade the picked card in place" (Armaments) and "put it on top of the draw
            // pile" (Warcry) -- again new numbers, because each one gets its own sentence.
            ChoiceThen::Upgrade => 5,
            ChoiceThen::ToDrawPileTop => 6,
            // §250: `Discovery` -- "add it to your hand, it costs 0". A **new number**: the page
            // writes "免费" into the sentence from it, and reusing `ToHand` would silently promise
            // a price the kernel is not charging.
            ChoiceThen::ToHandFree => 7,
            // §250: `Forethought` -- "on the **bottom** of your draw pile, costs 0".
            ChoiceThen::ToDrawPileBottomFree => 8,
            // §254: `Wish` -- "pick one, and **it is played at once**". A new number because the
            // sentence is unlike every other one ("拿进手牌" vs "立刻打出").
            ChoiceThen::PlayChosen => 9,
        },
        None => 0,
    }
}

/// How many copies of each picked card a `Copy` question makes; `0` when it is not a copy
/// question, `-1` when nothing is pending.
///
/// §226: the page has to be able to say "各复制 2 份" -- the number is the **content's** (base row 1,
/// `+` row 2), so it must travel from the kernel instead of being inferred from the `+`.
#[no_mangle]
pub extern "C" fn rd_env_choice_copies() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    match session.state.pending_choice() {
        // §227: the count lives **in the variant**, so a non-copy question cannot report one.
        Some(choice) => match choice.then {
            ChoiceThen::Copy { copies, .. } => i32::from(copies),
            _ => 0,
        },
        None => -1,
    }
}

/// Where the options come from: `1` a pile of cards, `2` three offered card definitions,
/// `0` nothing pending, `-1` no session.
///
/// §161.5: the page's sentence depends on **both** halves -- "discard pile" vs "three random
/// attack cards" is the source, "exhaust" vs "take into hand" is the `then`. Writing the sentence
/// from `kind` alone forced the page to guess, and it guessed "discard pile" for an offered
/// question.
#[no_mangle]
pub extern "C" fn rd_env_choice_source() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    match session.state.pending_choice() {
        Some(choice) => match choice.source {
            rd_core::state::ChoiceSource::Hand
            // §238: `ExhaustPile` 也是"从牌区里选"（Exhume），页面按 zone id 3 读来源牌区，
            // 所以 ABI 这一格照旧是 1。
            | rd_core::state::ChoiceSource::DiscardPile
            | rd_core::state::ChoiceSource::ExhaustPile
            // §244: `DrawPile` 同样是"从牌区里选"（Secret Technique / Secret Weapon）。
            | rd_core::state::ChoiceSource::DrawPile => 1,
            rd_core::state::ChoiceSource::Offered => 2,
        },
        None => 0,
    }
}

/// Lower bound on how many cards may be picked; `-1` when nothing is pending.
#[no_mangle]
pub extern "C" fn rd_env_choice_min() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    session
        .state
        .pending_choice()
        .map_or(-1, |choice| i32::from(choice.min))
}

/// Upper bound on how many cards may be picked; `-1` when nothing is pending.
#[no_mangle]
pub extern "C" fn rd_env_choice_max() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    session
        .state
        .pending_choice()
        .map_or(-1, |choice| i32::from(choice.max))
}

/// How many legal options there are, i.e. how many cards are in the source pile.
///
/// Equal to `rd_env_pile_len(3)` -- it is written twice on purpose, because the page's picker and
/// its bounds check must agree and this is the cheapest place to notice if they stop agreeing.
#[no_mangle]
pub extern "C" fn rd_env_choice_count() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    let Some(choice) = session.state.pending_choice() else {
        return 0;
    };
    // §161.5: an `Offered` question counts **definitions**, not cards in a pile.
    if choice.source.zone().is_none() {
        return choice.offered.len() as i32;
    }
    // §226: a pile question can be **narrowed** ("an Attack or Power card"), so the count is the
    // kernel's `choice_legal`, not the pile size. Counting the pile would paint options that
    // `resolve_choice` then refuses -- and the page's tick indices would be off by the filter.
    let mut buffer = [rd_core::state::CardInstanceId::EMPTY; rd_core::state::MAX_CARDS_PER_ZONE];
    match session.state.choice_legal(&mut buffer) {
        Ok(count) => count as i32,
        Err(_) => -1,
    }
}

/// Tick (`on != 0`) or untick option `index`. `0` ok, `-1` no such option.
///
/// Ticking past the upper bound is allowed: the page lets the player change their mind, and the
/// kernel refuses at `confirm` time with the count it wanted. Refusing the *click* instead would
/// make the picker un-editable, which is the more common way to be wrong.
#[no_mangle]
pub extern "C" fn rd_env_choice_pick(index: i32, on: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    if index < 0 || index >= rd_env_choice_count() {
        return -1;
    }
    let slot = index as usize;
    let position = session.choice_picks.iter().position(|picked| *picked == slot);
    if on != 0 {
        if position.is_none() {
            session.choice_picks.push(slot);
        }
    } else if let Some(position) = position {
        session.choice_picks.remove(position);
    }
    0
}

/// Is option `index` ticked? `1`/`0`, `-1` no such option.
#[no_mangle]
pub extern "C" fn rd_env_choice_selected(index: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    if index < 0 || index >= rd_env_choice_count() {
        return -1;
    }
    i32::from(session.choice_picks.contains(&(index as usize)))
}

/// Forget the ticks. The question stays -- this is "clear the selection", not "cancel".
///
/// "Cancel" is `rd_env_choice_confirm` with nothing ticked, and that works because both consumers
/// declare `min == 0`: the wiki says "any number", and zero is a number.
#[no_mangle]
pub extern "C" fn rd_env_choice_clear() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    session.choice_picks.clear();
    0
}

/// Answer the question. `0` accepted, `-1` nothing pending, `-2` refused with text.
///
/// The picks are handed over in **pile order**, not tick order: two players who ticked the same two
/// cards in different sequences asked for the same thing, and the replay must not care.
#[no_mangle]
pub extern "C" fn rd_env_choice_confirm() -> i32 {
    let session = match ensure_session() {
        Ok(session) => session,
        Err(_) => return -1,
    };
    let Some(choice) = session.state.pending_choice() else {
        return -1;
    };
    // §161.5: an `Offered` question is answered by **index**, and the card it names does not exist
    // until `resolve_choice` makes it -- so the price has to come from the **definition**.
    if choice.source == ChoiceSource::Offered {
        let mut indices = session.choice_picks.clone();
        indices.sort_unstable();
        indices.dedup();
        let Ok(offered) = session.state.choice_offered() else {
            return refuse_with_text("候选清单读不出来");
        };
        let mut total = 0i32;
        for index in &indices {
            let Some(definition) = offered.get(*index) else {
                return refuse_with_text(&std::format!("候选 {index} 不存在"));
            };
            match priced_delta(session, definition.as_str()) {
                Ok(delta) => total = total.saturating_add(delta),
                Err(message) => return refuse_with_text(&message),
            }
        }
        return match session.state.resolve_choice(
            rd_core::state::ChoiceAnswer::Offered(&indices),
            total,
        ) {
            Ok(_) => {
                session.choice_picks.clear();
                session.reobserve_after_external_change();
                0
            }
            Err(e) => refuse_with_text(&std::format!("选牌被拒：{e}")),
        };
    }
    let Some(zones) = session.state.card_zones(&choice.chooser) else {
        return refuse_with_text("待决选牌的战斗员没有牌区");
    };
    // The offered branch returned above, so this question really does name a pile.
    let Some(zone) = choice.source.zone() else {
        return refuse_with_text("这个问句的选项不在牌区里");
    };
    // §226: **the same list the picker showed** -- `choice_legal`, not the pile. A narrowed
    // question (Dual Wield) has fewer legal cards than the pile has, and indexing into the pile
    // would resolve a different question than the one that was asked.
    let mut legal = [rd_core::state::CardInstanceId::EMPTY; rd_core::state::MAX_CARDS_PER_ZONE];
    let legal_count = match session.state.choice_legal(&mut legal) {
        Ok(count) => count,
        Err(_) => return refuse_with_text("这个问句的选项读不出来"),
    };
    if legal_count == 0 {
        return refuse_with_text("这个问句没有合法选项");
    }
    let ids: Vec<rd_core::state::CardInstanceId> = legal[..legal_count].to_vec();
    let mut picks: Vec<rd_core::state::CardInstanceId> = Vec::with_capacity(session.choice_picks.len());
    let mut wanted = session.choice_picks.clone();
    wanted.sort_unstable();
    wanted.dedup();
    for index in wanted {
        let Some(id) = ids.get(index) else {
            return refuse_with_text(&std::format!("选项 {index} 不存在"));
        };
        picks.push(*id);
    }
    // §161.4: "free this turn" is a **per-copy price** of `-printed`, and only the content can
    // say what "printed" is. Computed here, at answer time, because the delta depends on **which**
    // card was picked -- a question cannot carry it.
    let mut cost_delta = 0i32;
    if choice.then == ChoiceThen::ToHand {
        let mut total = 0i32;
        for id in &picks {
            let Some(card) = session.state.find_card(&choice.chooser, id).and_then(|(_, slot)| {
                session.state.card(slot)
            }) else {
                return refuse_with_text("选中的牌不在牌区里");
            };
            match priced_delta(session, card.definition_id.as_str()) {
                Ok(delta) => total = total.saturating_add(delta),
                Err(message) => return refuse_with_text(&message),
            }
        }
        cost_delta = total;
    }
    match session
        .state
        .resolve_choice(rd_core::state::ChoiceAnswer::Instances(&picks), cost_delta)
    {
        Ok(done) => {
            session.choice_picks.clear();
            // A choice does not go through `d_env_step`, exactly like a potion -- the observation is
            // a cached snapshot, so it has to be refreshed here or the page shows the pre-choice
            // hand for one frame (and the hand is what the player is looking at).
            session.reobserve_after_external_change();
            if done.drawn < done.picked {
                // Drawing fewer than dropped is legal (both piles empty) but it is **information**:
                // the page says so, and a gate that silently accepted it would hide a reshuffle bug.
                session.error = std::format!("弃了 {} 张只抽到 {}", done.picked, done.drawn);
            }
            0
        }
        Err(e) => refuse_with_text(&std::format!("选牌被拒：{e}")),
    }
}

/// The definition id of option `index` in pile `zone`.
///
/// §161.5: `zone == 3` answers the **pending question's** options, and those are two different
/// kinds of thing -- instances from a pile, or (for `Offered`) definitions that have no instance.
/// The returned `String` is what lets one function serve both without pretending a definition is a
/// pile entry.
fn pile_card_id(zone: i32, index: i32) -> Option<std::string::String> {
    if index < 0 {
        return None;
    }
    let session = ensure_session().ok()?;
    // The offered branch comes first: `pile_zone` legitimately answers `None` for it.
    if zone == 3 {
        if let Ok(offered) = session.state.choice_offered() {
            return offered
                .get(index as usize)
                .map(|definition| definition.as_str().to_string());
        }
        // §226: a pile question can be **narrowed**, so option `index` is the `index`-th element of
        // `choice_legal` -- **not** the `index`-th card of the pile. Reading the pile here is how
        // the picker would show card A while the kernel's count/answer meant card B.
        let choice = session.state.pending_choice()?;
        let mut legal = [rd_core::state::CardInstanceId::EMPTY; rd_core::state::MAX_CARDS_PER_ZONE];
        let count = session.state.choice_legal(&mut legal).ok()?;
        if index as usize >= count {
            return None;
        }
        let id = legal[index as usize];
        let slot = session.state.find_card(&choice.chooser, &id)?.1;
        return session
            .state
            .card(slot)
            .map(|card| card.definition_id.as_str().to_string());
    }
    let zone = pile_zone(session, zone)?;
    let hero = session.hero_id()?;
    let (_, card) = session
        .state
        .zone_cards(&hero, zone)
        .enumerate()
        .find(|(position, _)| *position == index as usize)?;
    Some(card.definition_id.as_str().to_string())
}

/// What kind of card this is, from its `Tags`: 0 none, 1 attack, 2 skill, 3 power, 4 status,
/// 5 curse; `-1` when the tags cannot be read.
///
/// The order matters: `slimed` is `status`/`unplayable`/`junk` and must not be reported as an
/// attack, so attack and skill are asked first and status only after both said no. A card that
/// answers "cannot tell" is **not** silently "no type" -- `-1` travels to the page, which shows the
/// card without a chip rather than with the wrong one.
pub(crate) fn card_kind(content: &'static Content<'static>, id: &str) -> i32 {
    for (tag, kind) in [("attack", 1), ("skill", 2), ("power", 3), ("status", 4), ("curse", 5)] {
        match content.card_has_tag(id, tag) {
            Some(true) => return kind,
            Some(false) => {}
            None => return -1,
        }
    }
    0
}

/// The **kind** of the card in hand slot `index` (`rd_env_card_kind`): 0 none, 1 attack, 2 skill,
/// 3 power, 4 status, 5 curse, `-1` unknown.
///
/// The observation vector carries a card's `def_slot` and nothing else, so a page that wants
/// "Attack"/"Skill" has to ask. This is presentation, like the name and text exports.
#[no_mangle]
pub extern "C" fn rd_env_card_kind(index: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    if index < 0 {
        return -1;
    }
    let Some(id) = session.hand_defs.get(index as usize) else {
        return -1;
    };
    card_kind(session.content, id.as_str())
}

/// A card's `NameKey` out of the content, or its id when the document has none.
/// 一张牌的**显示名**（`CARD.NameKey`，查不到就退回 id 本身）。
///
/// §161.5：返回 `String` 而不是 `&'static str`。标题本身来自内容（`'static`），但**输入**不再
/// 是 —— 候选来源的 id 是从状态里借出来的一个 `String`。
fn card_display_title(id: &str) -> std::string::String {
    let Ok(session) = ensure_session() else {
        return id.to_string();
    };
    session
        .content
        .lookup_in(id, EK_CARD)
        .and_then(|entry| {
            session
                .content
                .row(rd_core::content::Table::Card, entry.index as u32)
        })
        .and_then(rd_core::content::CardRow::new)
        .and_then(|row| session.content.string(row.name_key()))
        .filter(|title| !title.is_empty())
        .map_or_else(|| id.to_string(), std::string::ToString::to_string)
}

/// The name of the card in hand slot `index` — `rd_env_card_name_len(index)`.
///
/// Not in the frozen ABI (§6's `def_slot` → name mapping is optional). Present because a UI that
/// can only print `def_slot = 0` is untestable by a human; the *slot* is still what the
/// observation carries, this is presentation only.
#[no_mangle]
pub extern "C" fn rd_env_card_name_len(index: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    session
        .hand_defs
        .get(index.max(0) as usize)
        .map_or(-1, |name| name.len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_env_card_name_len(index)` writable bytes in linear memory.
#[no_mangle]
pub unsafe extern "C" fn rd_env_card_name_into(index: i32, ptr: *mut u8) -> i32 {
    if ptr.is_null() {
        return -1;
    }
    let Ok(session) = ensure_session() else {
        return -1;
    };
    let Some(name) = session.hand_defs.get(index.max(0) as usize) else {
        return -1;
    };
    std::ptr::copy_nonoverlapping(name.as_ptr(), ptr, name.len());
    name.len() as i32
}

/// The intent text of enemy slot `index` — `rd_env_intent_len(index)`.
///
/// Not in the frozen ABI, for the same reason as `rd_env_card_name_*`: the *numbers* are in the
/// observation (`intent_kind` / `intent_damage`), this is the presentation half a human needs to
/// see that they are real (`acid_slime_m.tackle | Attack | 10 dmg`).
#[no_mangle]
pub extern "C" fn rd_env_intent_len(index: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    session
        .intents
        .get(index.max(0) as usize)
        .map_or(-1, |intent| intent.text.len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_env_intent_len(index)` writable bytes in linear memory.
#[no_mangle]
pub unsafe extern "C" fn rd_env_intent_into(index: i32, ptr: *mut u8) -> i32 {
    if ptr.is_null() {
        return -1;
    }
    let Ok(session) = ensure_session() else {
        return -1;
    };
    let Some(intent) = session.intents.get(index.max(0) as usize) else {
        return -1;
    };
    std::ptr::copy_nonoverlapping(intent.text.as_ptr(), ptr, intent.text.len());
    intent.text.len() as i32
}

/// The id of the enemy in wall slot `index` — `rd_env_enemy_name_len(index)`.
///
/// Presentation only, like `rd_env_card_name_*`: the observation carries slots and numbers, and a
/// page that can only print "enemy #1" cannot show that the names came out of `ENCT`.
///
/// §205: the slot is resolved through `enemy_roster()` — **the same list the observation uses** —
/// and the name comes from the live combatant's `definition_id`. Reading `plan.enemies` instead was
/// the bug: a summoned combatant (Bronze Orb, Dagger, Torch Head) is not in the plan, so the page
/// called it `enemy #1` — and so did the *run* page, because this is the only name the ABI carries.
/// For a non-summoned enemy the two agree (`plan.enemies[i].id` is the definition id), so nothing
/// else moves.
fn enemy_slot_name(session: &Session, index: i32) -> Option<&str> {
    let slot = usize::try_from(index.max(0)).ok()?;
    let id = *session.enemy_roster().get(slot)?;
    session
        .state
        .combatant(&id)
        .map(|combatant| combatant.definition_id.as_str())
        // A wall slot whose combatant has already left the fight (a destroyed summon) keeps the plan
        // name when there is one, so a late read cannot turn a real name into `-1`.
        .or_else(|| session.plan.enemies.get(slot).map(|enemy| enemy.id))
}

#[no_mangle]
pub extern "C" fn rd_env_enemy_name_len(index: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    enemy_slot_name(session, index).map_or(-1, |name| name.len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_env_enemy_name_len(index)` writable bytes in linear memory.
#[no_mangle]
pub unsafe extern "C" fn rd_env_enemy_name_into(index: i32, ptr: *mut u8) -> i32 {
    if ptr.is_null() {
        return -1;
    }
    let Ok(session) = ensure_session() else {
        return -1;
    };
    let Some(name) = enemy_slot_name(session, index) else {
        return -1;
    };
    std::ptr::copy_nonoverlapping(name.as_ptr(), ptr, name.len());
    name.len() as i32
}

// =============================================================================================
// The animation log (`port-plan.md` §142)
// =============================================================================================
//
// The page used to reconstruct "what just happened" by subtracting two observation vectors. That
// answers "how much HP is left" and nothing else: a 7x3 multi-hit attack subtracts to "21 damage",
// and "block then take a hit" subtracts identically to "take a hit then block". Order and segmen-
// tation are exactly what an animation needs, and they are exactly what a difference throws away.
//
// So the kernel keeps an ordered log of **facts that landed** (`rd_core::beat`), cleared at every
// action entry point. `field 0` is the kind; the rest are the numbers, all of them already decoded
// by the kernel (no string parsing on the JS side).
//
// Wall slots: `-1` = the hero, `0..5` = the enemy wall slots **the observation uses**
// (`env-abi.md` §10 -- slots never move), `-2` = `beyond the wall` (a 7th enemy, or a combatant that
// is not on the field). The kernel only knows `combatants()` ordinals; the mapping to wall slots
// lives here because the kernel does not know how wide the wall is.

/// Kinds, as the numbers `rd_env_beat_field(index, 0)` hands out. Mirrors `rd_core::beat::BeatKind`.
pub const BEAT_DAMAGE: i32 = 1;
/// Gained block.
pub const BEAT_BLOCK: i32 = 2;
/// Healed.
pub const BEAT_HEAL: i32 = 3;
/// Status stacks changed (`a` = net change, `flags` bit1 = a new instance was created).
pub const BEAT_STATUS_CHANGED: i32 = 4;
/// A status instance was removed (stacks hit 0, or its duration ran out).
pub const BEAT_STATUS_REMOVED: i32 = 5;
/// A debuff was negated by Artifact. `def` is the status that did **not** land.
pub const BEAT_STATUS_PREVENTED: i32 = 6;
/// Someone went down.
pub const BEAT_DOWNED: i32 = 7;
/// A minion fled because its owner went down.
pub const BEAT_ESCAPED: i32 = 8;
/// A card was played. `def` is the card definition.
pub const BEAT_CARD_PLAYED: i32 = 9;
/// A turn started.
pub const BEAT_TURN_STARTED: i32 = 10;
/// A turn ended.
pub const BEAT_TURN_ENDED: i32 = 11;
/// A combatant was created (split / summon). `a` = its ordinal, `b` = its maximum health.
pub const BEAT_SUMMONED: i32 = 12;

/// `flags` bit: this Damage was damage-over-time, not a hit.
pub const BEAT_FLAG_DOT: i32 = 1;
/// `flags` bit: this status change created a **new** instance.
pub const BEAT_FLAG_NEW_INSTANCE: i32 = 2;
/// `flags` bit: this card play was an **action-side** play (no `CardPlayed` trigger, still animated).
pub const BEAT_FLAG_ACTION: i32 = 4;

/// How many animation beats the last action produced. `-1` = no session.
#[no_mangle]
pub extern "C" fn rd_env_beat_count() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    session.state.beats().len() as i32
}

/// How many beats the log had to drop (capacity). `0` is the only good answer, and the page can
/// print the other one instead of quietly animating less than happened.
#[no_mangle]
pub extern "C" fn rd_env_beats_dropped() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    i32::from(session.state.beats_dropped())
}

/// Clears the animation log. Called at every action entry point; exported so a driver that stops
/// mid-step (a browser pause, a replay scrubber) can start from an empty log on purpose.
#[no_mangle]
pub extern "C" fn rd_env_beats_clear() -> i32 {
    match slot().as_mut() {
        Some(session) => {
            session.state.clear_beats();
            0
        }
        None => -1,
    }
}

/// One field of beat `index`. `-1` = no session / no such beat.
///
/// | field | meaning |
/// |---|---|
/// | 0 | kind (see the `BEAT_*` constants) |
/// | 1 | actor **wall slot** (`-1` hero, `0..5` enemy, `-2` nobody/beyond the wall) |
/// | 2 | target wall slot, same encoding |
/// | 3 | extra flags (see the `BEAT_FLAG_*` constants) |
/// | 4 | `a` -- the main number (damage dealt / block gained / stacks changed / ...) |
/// | 5 | `b` -- the second number (damage blocked / duration turns / max HP / ...) |
/// | 6 | `c` -- the third number (damage requested / charges / ...) |
/// | 7 | has a definition name (`1` yes, `0` no) |
#[no_mangle]
pub extern "C" fn rd_env_beat_field(index: i32, field: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    // A negative index is a **caller bug**, not "beat 0": clamping it would answer for a real beat
    // and the mistake would look like data. (`-1` is already the "no such beat" answer, so this
    // also keeps the sentinel unambiguous.)
    if index < 0 {
        return -1;
    }
    let Some(beat) = session.state.beats().get(index as usize).copied() else {
        return -1;
    };
    match field {
        0 => i32::from(beat.kind as u8),
        1 => session.wall_slot_of_ordinal(beat.actor),
        2 => session.wall_slot_of_ordinal(beat.target),
        3 => i32::from(beat.flags),
        4 => beat.a,
        5 => beat.b,
        6 => beat.c,
        7 => i32::from(session.state.beat_def_text(index as usize).is_some()),
        _ => -1,
    }
}

/// Length of beat `index`'s definition name (status definition / card definition), or `-1`.
#[no_mangle]
pub extern "C" fn rd_env_beat_def_len(index: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    if index < 0 {
        return -1;
    }
    session
        .state
        .beat_def_text(index as usize)
        .map_or(-1, |text| text.len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_env_beat_def_len(index)` writable bytes in linear memory.
#[no_mangle]
pub unsafe extern "C" fn rd_env_beat_def_into(index: i32, ptr: *mut u8) -> i32 {
    if ptr.is_null() || index < 0 {
        return -1;
    }
    let Ok(session) = ensure_session() else {
        return -1;
    };
    let Some(text) = session.state.beat_def_text(index as usize) else {
        return -1;
    };
    std::ptr::copy_nonoverlapping(text.as_ptr(), ptr, text.len());
    text.len() as i32
}

// =============================================================================================
// Every status, by name (§147)
// =============================================================================================
//
// The observation carries **five fixed status axes** (`STATUS_AXES`: strength / vulnerable / weak /
// dexterity / frail) because that layout was frozen early and is tiled end to end. That is fine
// until a status outside the five matters -- `Constricted` (lose HP every turn) is exactly such a
// status: a debuff the player cannot see is a debuff the player cannot play around.
//
// Adding a sixth axis would move every offset after it, so instead: an id/stacks pair per slot, the
// same shape `rd_env_enemy_name_*` already uses for names.

/// How many status instances combatant `whom` carries (`-1` = hero, `0..5` = enemy wall slot),
/// or `-1` for no such combatant.
#[no_mangle]
pub extern "C" fn rd_env_status_count(whom: i32) -> i32 {
    match statuses_of(whom) {
        Some(statuses) => statuses.len() as i32,
        None => -1,
    }
}

/// Definition id length of status `index` on `whom`, or `-1`.
#[no_mangle]
pub extern "C" fn rd_env_status_id_len(whom: i32, index: i32) -> i32 {
    match status_at(whom, index) {
        Some(status) => status.definition_id.as_str().len() as i32,
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_env_status_id_len(whom, index)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_env_status_id_into(whom: i32, index: i32, ptr: *mut u8) -> i32 {
    if ptr.is_null() {
        return -1;
    }
    let Some(status) = status_at(whom, index) else {
        return -1;
    };
    let text = status.definition_id.as_str();
    std::ptr::copy_nonoverlapping(text.as_ptr(), ptr, text.len());
    text.len() as i32
}

/// How many stacks status `index` on `whom` carries, or `-1`.
#[no_mangle]
pub extern "C" fn rd_env_status_stacks(whom: i32, index: i32) -> i32 {
    match status_at(whom, index) {
        Some(status) => status.stacks,
        None => -1,
    }
}

/// The status instances of `whom` (§147), or `None` when there is no such combatant.
fn statuses_of(whom: i32) -> Option<Vec<rd_core::state::StatusInstance>> {
    let session = ensure_session().ok()?;
    let id = session.combatant_of_wall_slot(whom)?;
    let hero = session.state.combatant(&id)?;
    Some(hero.statuses().to_vec())
}

/// One status instance, by wall slot and index.
fn status_at(whom: i32, index: i32) -> Option<rd_core::state::StatusInstance> {
    if index < 0 {
        return None;
    }
    let statuses = statuses_of(whom)?;
    statuses.get(index as usize).copied()
}

/// Benchmark hook: rebuild the observation + action table **without** stepping the fight.
///
/// Not part of the ABI. It exists because "how long does one `rd_env_step` take" is not the same
/// question as "how long does the kernel take", and the difference is the whole story: a step
/// does one engine call *plus* two full bookkeeping refreshes (see `Session::reobserve`). Timing
/// this separately is what turns the step number into something you can act on.
#[no_mangle]
pub extern "C" fn rd_env_bench_bookkeeping() -> i32 {
    match ensure_session() {
        Ok(session) => {
            session.reobserve();
            OBS_LEN as i32
        }
        Err(_) => -1,
    }
}

/// Benchmark hook: `run_fight` envelope allocation only (74 KB `FightOutcome` + one `Step`).
///
/// A no-op hero step that the driver refuses *before* touching state (`CardNotInHand`), so what it
/// measures is the envelope, not a card's effects.
#[no_mangle]
pub extern "C" fn rd_env_bench_envelope() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    match session.exec(&[Step::HeroPlays {
        card: "__nonexistent__",
        target: None,
    }]) {
        Ok(()) => i32::from(session.problems.first().map(String::as_str) == Some("CardNotInHand")),
        Err(_) => -1,
    }
}

/// Benchmark hook: run action 0 **without** any bookkeeping refresh.
///
/// This is the "how much is the fight" half of the step/n fight split. `rd_env_step` refreshes the
/// observation twice (once to snapshot the "before", once after), and each refresh runs
/// `can_play_card` once per hand card — so the honest answer to "what does a step cost" is
/// *step = 2 × bookkeeping + this*. Returns 1 when it executed, 0 when it had nothing to do.
#[no_mangle]
pub extern "C" fn rd_env_bench_step_raw() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    if session.is_done() {
        return 0;
    }
    let Some(action) = session.actions.first().copied() else {
        return 0;
    };
    let outcome = match action.kind {
        ACTION_PLAY => session.step_play(action.arg0.max(0) as usize, action.arg1),
        ACTION_END_TURN => session.step_end_turn(),
        _ => return -1,
    };
    i32::from(outcome.is_ok())
}

/// Benchmark hook: `size_of` of the big kernel types, so a `.wasm` data-section number can be
/// attributed instead of guessed. `which`:
///
/// * 0 → `size_of::<CombatState>()` (the thing that must live in linear memory)
/// * 1 → `size_of::<FightOutcome>()` (the driver's envelope)
/// * 2 → `size_of::<Problem>()`
/// * 3 → `size_of::<Content<'static>>()`
/// * 4 → `OBS_LEN`
///
/// Returns `-1` for an unknown `which`.
///
/// Measured: `CombatState` 184,648, `FightOutcome` 2,832, `Problem` **1**, `Content` 32.
///
/// ⚠️ `Problem` is 1 byte because **every variant is fieldless** (`battle.rs:201-236`) — the
/// payload-carrying enums (`play::Refusal` with its `TagId`, `PlayError`) never reach
/// `FightOutcome`. The first version of this comment claimed `Problem` carried an `Ident<32>` and
/// predicted a 74 KB envelope; the measurement said 1 byte, and the prediction was about a
/// different type. That is why the size report is measured instead of reasoned about.
#[no_mangle]
pub extern "C" fn rd_env_bench_sizes(which: i32) -> i32 {
    match which {
        0 => std::mem::size_of::<CombatState>() as i32,
        1 => std::mem::size_of::<FightOutcome>() as i32,
        2 => std::mem::size_of::<rd_core::battle::Problem>() as i32,
        3 => std::mem::size_of::<Content<'static>>() as i32,
        4 => OBS_LEN as i32,
        _ => -1,
    }
}

/// `rd_env_selfcheck(config, seed, steps)` — replay the same fight twice and compare the two
/// observation streams (`env-abi.md` §8.1).
///
/// This implementation has one scenario, so `config` is ignored; `seed` and `steps` are honoured.
/// Returns 1 when both runs agreed on every observation of every step of a "play the first legal
/// action" policy, 0 otherwise, -1 if a fight could not be built.
#[no_mangle]
pub extern "C" fn rd_env_selfcheck(seed: i32, steps: i32) -> i32 {
    let run = |_once: ()| -> Option<Vec<i32>> {
        let mut session = build_session(seed).ok()?;
        let mut stream = Vec::new();
        for _ in 0..steps.max(0) {
            if session.is_done() {
                break;
            }
            stream.extend_from_slice(&session.after);
            if session.actions.is_empty() {
                break;
            }
            // Deterministic policy: always the first enumerated action.
            let action = session.actions[0];
            let outcome = match action.kind {
                ACTION_PLAY => session.step_play(action.arg0.max(0) as usize, action.arg1),
                ACTION_END_TURN => session.step_end_turn(),
                _ => break,
            };
            if outcome.is_err() {
                break;
            }
            session.reobserve();
        }
        stream.extend_from_slice(&session.after);
        Some(stream)
    };
    match (run(()), run(())) {
        (Some(left), Some(right)) => i32::from(left == right),
        _ => -1,
    }
}

// =============================================================================================
// Tests
// =============================================================================================

/// **One** test on purpose.
///
/// The exports share one `static mut SESSION` (single environment — see the module header), so two
/// tests running on different threads would race on it. `cargo test` also runs in a process where
/// `--test-threads` defaults to the core count, so "keep it in one `#[test]`" is the only way to
/// stay honest without adding a mutex to the export surface.
#[cfg(test)]
mod tests {
    use super::*;

    fn observation() -> Vec<i32> {
        let session = ensure_session().expect("session");
        session.after.clone()
    }

    /// **The buffer JS actually reads**, not the internal snapshot.
    ///
    /// These two drifted apart once (see `Session::publish`), and every other assertion in this
    /// file was happy about it. So the test reads through the ABI, the way the page does.
    fn exported_observation() -> Vec<i32> {
        let len = rd_env_observe_len() as usize;
        let mut out = vec![0i32; len];
        let written = unsafe { rd_env_observe_into(out.as_mut_ptr()) };
        assert_eq!(written as usize, len, "observe_into must write the whole vector");
        out
    }

    /// §193: the page's fight builder really draws the louse's `roll.bite`.
    ///
    /// The kernel test (`host::tests::a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action`)
    /// proves the roll is constant per fight and in the wiki's range, but it calls
    /// `apply_spawn_rolls` itself -- so "the browser goes through that path" was untested. Here two
    /// fights are built through the **real** entry point with the same seed and the same deck: the
    /// only difference between them is that one encounter names an enemy with a `Rolls` entry.
    ///
    /// What is compared: the RNG step (`+1`, and only one), and the counter itself -- read off the
    /// combatant, so a "rolled but not stored" build fails here rather than showing up as 0 damage
    /// in a fight nobody is staring at.
    #[test]
    fn building_a_louse_fight_draws_its_bite_and_a_cultist_fight_does_not() {
        let louse = build_session_at(11, "enc_louse", 70, None, 0, 0).expect("the louse fight builds");
        let cultist =
            build_session_at(11, "enc_cultist", 70, None, 0, 0).expect("the cultist fight builds");
        // §209: the louse declares two rolls now (`roll.bite` + `roll.curl_up`), so the difference is
        // **one per declared roll** -- the assertion is the difference, not an absolute count, because
        // "how many rolls a monster has" is content and will keep changing.
        assert_eq!(
            louse.state.random_step,
            cultist.state.random_step + 2,
            "one draw per louse roll; shuffle and the first draw are identical in both"
        );
        let id = rd_core::state::CombatantId::new("louse_red").expect("a usable id");
        let name = rd_core::state::CounterId::new("roll.bite").expect("a usable counter id");
        let value = louse
            .state
            .combatant(&id)
            .expect("the louse is in the fight")
            .counters()
            .iter()
            .find(|counter| counter.key == name)
            .map(|counter| counter.value);
        let value = value.expect("`roll.bite` must be on the combatant");
        assert!(
            (5..=7).contains(&value),
            "A0 louse bite is 5-7 (wiki), got {value}"
        );
        assert!(
            cultist
                .state
                .combatant(&rd_core::state::CombatantId::new("cultist").expect("a usable id"))
                .expect("the cultist is in the fight")
                .counters()
                .is_empty(),
            "the cultist declares `Rolls: []` -- no counter may appear"
        );
    }

    /// §195.9（审阅工作包 C）：**每一条能进入池的遭遇都必须建得起来** —— × A0/A9/A19/A20。
    ///
    /// 存在理由是一条真实的 bug：`enc_darklings`（两只相同 Darkling）在**第三幕 weak 池**里，却
    /// 从来建不起来（第二条记录撞 `DuplicateCombatant`）。所有既有闸门都是绿的 —— 内容门只查
    /// "内容里的 id 自洽"，浏览器切片只跑第一幕，随机 soak 恰好没抽到它。
    ///
    /// 这里把"能进入池"当成判据从内容里**读出来**（九个 `EncounterTables.*`），所以池子加一项就
    /// 自动进这道门；四个 Ascension 覆盖 `ProgramAsc`（A2/A3/A4、A17/18/19）与 A20 的双 Boss。
    ///
    /// 判据不止"能建"：还要**有敌人、首轮能选出意图**（`select_action` 对每个敌人都不报错），
    /// 因为"建起来但意图层炸"与"建不起来"对玩家是同一件事。
    #[test]
    fn every_pool_encounter_builds_and_can_pick_its_first_intents() {
        let pools = [
            "Weak", "Weak2", "Weak3", "Elite", "Elite2", "Elite3", "Boss", "Boss2", "Boss3",
        ];
        let mut seen: Vec<&'static str> = Vec::new();
        let mut builds = 0usize;
        for pool in pools {
            // Read the pool through the content: adding an encounter there must add it here too.
            let content = Box::leak(Box::new(
                rd_core::content::Content::parse(IMAGE).expect("the image parses"),
            ));
            let ids = content
                .encounter_pool(pool)
                .unwrap_or_else(|| panic!("`EncounterTables.{pool}` must be readable"));
            for name in ids.iter().copied().filter(|id| !id.is_empty()) {
                if seen.contains(&name) {
                    continue;
                }
                seen.push(name);
                for ascension in [0u8, 9, 19, 20] {
                    let mut session = build_session_at(11, name, 70, None, 0, ascension)
                        .unwrap_or_else(|e| {
                            panic!("`{name}` (pool `{pool}`, A{ascension}) must build: {e}")
                        });
                    builds += 1;
                    let enemies: Vec<rd_core::state::CombatantId> = session
                        .state
                        .combatants()
                        .iter()
                        .filter(|combatant| combatant.team_id.as_str() == "enemy")
                        .map(|combatant| combatant.id)
                        .collect();
                    assert!(
                        !enemies.is_empty(),
                        "`{name}` (A{ascension}) placed no enemy -- `Spawn: false` on everything?"
                    );
                    // The intent layer must answer for each enemy (this is where `ProgramAsc` and the
                    // weighted-choice rules are actually exercised).
                    for enemy in &enemies {
                        let at = rd_core::intent::locate_enemy(session.content, session.encounter, enemy)
                            .unwrap_or_else(|e| panic!("`{name}` locate {enemy:?}: {e:?}"))
                            .unwrap_or_else(|| panic!("`{name}`: `{enemy:?}` has no enemy record"));
                        rd_core::intent::select_action(
                            &session.state,
                            session.content,
                            at,
                            enemy,
                            session.state.current_round.max(1),
                        )
                        .unwrap_or_else(|e| {
                            panic!("`{name}` (A{ascension}) select_action for {enemy:?}: {e:?}")
                        });
                    }
                    session.host.take_failure();
                }
            }
        }
        assert!(seen.len() >= 20, "only {} encounters are reachable: {seen:?}", seen.len());
        assert!(builds >= 80, "only {builds} fights were built");
    }

    /// §195.8: the Awakened One comes with two Cultists, and they **flee** when it finally dies.
    ///
    /// Three judgements, and the second is the one that matters: the fight must be **won** by killing
    /// the boss, not by killing two 48-HP cultists afterwards. The kernel already converts a downed
    /// master's minions to `Escaped` (`resolve_damage`), and `Escaped` is not `Alive`, so the victory
    /// check ignores them -- the content only had to declare `Owner`.
    #[test]
    fn the_awakened_ones_cultists_flee_when_it_dies() {
        let mut session = build_session_at(5, "enc_awakened_one", 70, None, 0, 0)
            .expect("the fight builds");
        let enemies = |session: &Session| -> Vec<std::string::String> {
            session
                .state
                .combatants()
                .iter()
                .filter(|combatant| combatant.team_id.as_str() == "enemy")
                .map(|combatant| std::string::String::from(combatant.id.as_str()))
                .collect()
        };
        assert_eq!(
            enemies(&session),
            vec!["awakened_one", "cultist", "cultist#2"],
            "wiki: two Cultists -- and the duplicate id gets the `#2` suffix (§195.8)"
        );

        // Kill the boss outright. Its `standard.unawakened` guard means the *first* lethal blow only
        // leaves it at 1 HP; the second one really downs it.
        for _ in 0..2 {
            {
                let mut ctx = rd_core::exec::ExecContext::new(
                    &mut session.state,
                    Some(rd_core::state::CombatantId::new("hero").expect("hero")),
                    Some(rd_core::state::CombatantId::new("awakened_one").expect("the boss")),
                    None,
                    64,
                )
                .with_content(session.content);
                rd_core::exec::resolve_damage(
                    &mut ctx,
                    &rd_core::state::CombatantId::new("awakened_one").expect("the boss"),
                    9999,
                    false,
                )
                .expect("the blow lands");
            }
            session
                .host
                .try_resolve_pending_queues(&mut session.state)
                .expect("triggers settle");
        }

        let states: Vec<(&str, rd_core::state::CombatantLifecycleState)> = session
            .state
            .combatants()
            .iter()
            .filter(|combatant| combatant.team_id.as_str() == "enemy")
            .map(|combatant| (combatant.id.as_str(), combatant.lifecycle_state))
            .collect();
        assert!(
            states.iter().any(|(id, state)| *id == "awakened_one"
                && *state == rd_core::state::CombatantLifecycleState::Downed),
            "the boss is down: {states:?}"
        );
        for (id, state) in &states {
            if *id == "awakened_one" {
                continue;
            }
            assert_eq!(
                *state,
                rd_core::state::CombatantLifecycleState::Escaped,
                "`{id}` must have fled when its master fell"
            );
        }
        assert_eq!(
            session.state.result,
            rd_core::state::CombatResult::Victory,
            "killing the boss wins the fight -- the cultists do not have to be hunted down"
        );
    }

    /// §195.8: an encounter whose records share an `Id` still builds (`enc_darklings` = two identical
    /// Darklings, and it sits in the act-3 weak pool).
    ///
    /// This was a real bug: the second record hit `add_combatant`'s duplicate check, so a run that
    /// rolled that encounter ended in `Capacity(DuplicateCombatant)` -- a *content* row that could
    /// never be played. Duplicates now get the same `#<n>` suffix a summon uses, which is also what
    /// `intent::locate_enemy` already falls back to (the definition part).
    #[test]
    fn an_encounter_with_two_records_of_the_same_id_builds() {
        let session = build_session_at(5, "enc_darklings", 70, None, 0, 0)
            .expect("two identical Darklings must be placeable");
        let names: Vec<&str> = session
            .state
            .combatants()
            .iter()
            .filter(|combatant| combatant.team_id.as_str() == "enemy")
            .map(|combatant| combatant.id.as_str())
            .collect();
        assert_eq!(names, vec!["darkling", "darkling#2"], "the second one is suffixed");
        // And both still resolve to the record (through the definition part, §123).
        for name in names {
            let id = rd_core::state::CombatantId::new(name).expect("a usable id");
            let located = rd_core::intent::locate_enemy(
                session.content,
                session.encounter,
                &id,
            )
            .expect("lookup");
            assert!(located.is_some(), "`{name}` must resolve to its enemy record");
        }
    }

    /// §195.6: `Spawn: false` keeps a minion off the field until it is **summoned**.
    ///
    /// The wiki's Bronze Automaton opens with "Spawn Orbs" and *then* fights; The Collector opens with
    /// "Spawn". Before this flag the minions had to be pre-placed (the encounter roster is the only
    /// place their move sets can be looked up, §138), and both bosses' turn-1 move was deleted.
    ///
    /// Three judgements per boss: the fight **starts** with one enemy; the summon move brings the
    /// count to three; and the summoned minions are the right definitions (a `createCombatant` that
    /// named the wrong id would still make the count right).
    #[test]
    fn a_minion_is_not_on_the_field_until_its_summon_lands() {
        let cases = [
            ("enc_bronze_automaton", "bronze_automaton", "bronze_automaton.spawn_orbs",
             ["bronze_orb", "bronze_orb"]),
            ("enc_the_collector", "the_collector", "the_collector.spawn",
             ["torch_head", "torch_head"]),
        ];
        for (encounter, boss, spawn_move, minions) in cases {
            let mut session = build_session_at(9, encounter, 70, None, 0, 0)
                .expect("the fight builds");
            // Count the **enemies**: the hero is a combatant too.
            // (`definition_id` borrows the combatant, which borrows the session -- so this helper takes
            // the session and returns owned strings; a `&'static str` return would tie the two
            // lifetimes together and not compile.)
            let enemies = |session: &Session| -> Vec<std::string::String> {
                session
                    .state
                    .combatants()
                    .iter()
                    .filter(|combatant| combatant.team_id.as_str() == "enemy")
                    .map(|combatant| std::string::String::from(combatant.definition_id.as_str()))
                    .collect()
            };
            assert_eq!(
                enemies(&session),
                vec![std::string::String::from(boss)],
                "{encounter}: only the boss starts on the field"
            );

            let row = u32::from(
                session
                    .content
                    .lookup_in(spawn_move, rd_core::content::EK_EACTION)
                    .expect("the spawn move is in the image")
                    .index,
            );
            rd_core::intent::execute_action(
                &mut session.state,
                session.content,
                &rd_core::state::CombatantId::new(boss).expect("a usable id"),
                row,
                None,
            )
            .expect("the summon lands");

            let mut names = enemies(&session);
            assert_eq!(names.len(), 3, "{encounter}: the spawn move brings two minions");
            names.retain(|name| name.as_str() != boss);
            names.sort_unstable();
            let mut expected: Vec<std::string::String> =
                minions.iter().map(|name| std::string::String::from(*name)).collect();
            expected.sort_unstable();
            assert_eq!(names, expected, "{encounter}: the summoned definitions");
        }
    }

    /// §195.1: the browser's fight builder seeds the Guardian's Mode Shift **budget** at spawn.
    ///
    /// The kernel test proves the budget drains and refills; this one proves the *page's* path runs
    /// the seeding at all (a `Counters` entry that nobody reads is the "data in the image, nothing
    /// in the fight" shape). A0 seeds 30, A9 35, A19 40 -- all three are checked, because the tiering
    /// is the part that can silently pick the wrong row.
    #[test]
    fn building_a_guardian_fight_seeds_its_mode_shift_budget_by_ascension() {
        for (ascension, want) in [(0u8, 30), (9, 35), (19, 40)] {
            let session = build_session_at(3, "enc_the_guardian", 70, None, 0, ascension)
                .expect("the guardian fight builds");
            let id = rd_core::state::CombatantId::new("the_guardian").expect("a usable id");
            let key = rd_core::state::CounterId::new("mode_shift_budget").expect("a usable id");
            let got = session
                .state
                .combatant(&id)
                .expect("the guardian is in the fight")
                .counters()
                .iter()
                .find(|counter| counter.key == key)
                .map(|counter| counter.value);
            assert_eq!(got, Some(want), "A{ascension}: wiki says Mode Shift {want}");
        }
    }

    /// The intent text of an enemy slot, the way the page reads it.
    fn intent_text(slot: i32) -> String {
        let len = rd_env_intent_len(slot);
        if len <= 0 {
            return String::new();
        }
        let mut bytes = vec![0u8; len as usize];
        let written = unsafe { rd_env_intent_into(slot, bytes.as_mut_ptr()) };
        assert_eq!(written, len, "intent_len / intent_into disagree");
        String::from_utf8(bytes).expect("intent text is UTF-8")
    }

    /// "Play the first card that deals damage, otherwise end the turn" — the policy needs *some*
    /// opinion, because the content deck (`strike`×5, `defend`×4, `bash`×1) will happily let a
    /// "play whatever comes first" bot stack block forever.
    fn play_an_attack_or_end_turn() -> i32 {
        let session = ensure_session().expect("session");
        let actions = session.actions.clone();
        for (index, action) in actions.iter().enumerate() {
            if action.kind != ACTION_PLAY {
                continue;
            }
            let Some(name) = session.hand_defs.get(action.arg0.max(0) as usize) else {
                continue;
            };
            if name == "strike" || name == "bash" {
                return index as i32;
            }
        }
        actions
            .iter()
            .position(|action| action.kind == ACTION_END_TURN)
            .map_or(-1, |index| index as i32)
    }

    /// The ABI works end to end on the host, on **content**: the deck comes out of the image, the
    /// enemies come out of the encounter, the intent column is real, every enemy takes a turn per
    /// end-turn step, and a rejected step really changes nothing.
    #[test]
    fn the_spike_scenario_is_playable_through_the_env_abi() {
        assert_eq!(rd_env_reset(), 0);
        // Pin the size attribution the spike report makes, so it cannot rot silently:
        // the 213 KB is the *state*, and the driver's envelope is a few KB, not a data-section
        // blob. If `Problem` ever grows a payload variant this fires and whoever added it gets to
        // redo the numbers in the report.
        assert_eq!(rd_env_bench_sizes(2), 1, "`Problem` must stay fieldless (1 byte)");
        assert!(
            rd_env_bench_sizes(1) < 4096,
            "the FightOutcome envelope should be a few KB, not tens"
        );
        assert!(
            rd_env_bench_sizes(0) > 180_000,
            "CombatState is the 184 KB structure"
        );
        assert_eq!(rd_env_bench_sizes(4), OBS_LEN as i32, "observe_len is published");

        // The fight is built from the content: two enemies from `enc_small_slimes`, and a hero
        // whose HP comes from the *plan* (80 here) rather than from `Start.MaxHealth`.
        let fresh = exported_observation();
        assert_eq!(fresh[H_ENEMY_COUNT], 2, "the encounter's enemy count");
        assert_eq!(fresh[H_HERO_HP_MAX], HERO_HP, "hero HP is the plan's, not the content's");

        // Before the first step the hero has not started its turn, so the hand is empty — this is
        // `ScenarioRunner.cs:105`'s `EnsureTurnStarted` being *lazy*, and it is worth pinning
        // because "the hand is empty on load" looks like a bug from the outside.
        // The reference's *scenario driver* starts the turn on the first play (`ScenarioRunner.cs:105`)
        // and the diff harness still exercises that path, so `build_fight_from_content` stops at
        // `WaitingToStartTurn`. The **browser** driver starts it (`start_first_turn`), because StS
        // begins the hero's first turn with the combat -- and "the hand is empty on load" does look
        // like a bug from the outside, because for a game it was one.
        assert_eq!(fresh[H_HAND_COUNT], 5, "hand at combat start");
        assert_eq!(rd_env_done(), 0);

        // The exported buffer and the internal snapshot must be the same vector. This is the
        // assertion that would have caught the page-renders-zeros bug.
        assert_eq!(
            exported_observation(),
            observation(),
            "rd_env_observe_into does not reflect the live observation"
        );
        // ... and it is not accidentally all zeros, which would also satisfy `==` if both sides
        // were zero: `round` is 1 on a fresh fight.
        assert_eq!(fresh[H_ROUND], 1, "round on a fresh fight");

        // A play action must exist even though the hand is empty? No — nothing to play yet, so the
        // only legal action is "end turn". That is the honest table, and it is why the page's end
        // turn button is what draws the first hand.
        // The fight starts at turn 1, so the table leads with **play** actions and still offers
        // end-turn. (It used to be a single end-turn action, because the hand was empty until the
        // page pressed it -- faithful to the reference DSL, wrong for a game.)
        let kinds: Vec<i32> = (0..rd_env_action_count())
            .map(|index| rd_env_action_kind(index))
            .collect();
        assert!(
            kinds.iter().any(|kind| *kind == ACTION_END_TURN),
            "end turn must always be offered"
        );
        assert!(
            kinds.iter().any(|kind| *kind != ACTION_END_TURN),
            "five cards in hand means play actions: {kinds:?}"
        );

        // ── the intent column is content, not a constant ─────────────────────────────────────
        // Every living enemy answers with an `EACT` id, a kind and a literal damage amount
        // (`acid_slime_m.corrosive_spit` = 7, `spike_slime_s.tackle` = 5 in this content).
        let mut previewed_damage = 0;
        for slot in 0..2 {
            let base = OFF_ENEMY + slot * 8;
            assert_eq!(fresh[base], 1, "enemy {slot} alive");
            assert!(fresh[base + 5] > 0, "enemy {slot} intent_kind must be real");
            assert!(fresh[base + 6] > 0, "enemy {slot} intent_damage must be real");
            let text = intent_text(slot as i32);
            assert!(text.contains(" | "), "intent text for {slot}: {text:?}");
            assert!(text.contains("dmg"), "intent text for {slot}: {text:?}");
            previewed_damage += fresh[base + 6];
        }
        assert_eq!(rd_env_intent_len(9), -1, "no such enemy slot");

        // ── one end-turn step lets **every** enemy act ──────────────────────────────────────
        // The discriminator: with the old `NextRound` path only the first enemy would act, so the
        // hero would lose one enemy's worth of HP instead of both. Pinning the sum is what makes
        // this assertion about the turn machinery rather than about the number 12.
        // Ask for the end-turn action by **kind**, not by index: the table leads with play actions
        // once the hand is not empty, and step(0) would play a card.
        let end_turn = (0..rd_env_action_count())
            .find(|index| rd_env_action_kind(*index) == ACTION_END_TURN)
            .expect("end turn must be offered");
        let hp_before = fresh[H_HERO_HP];
        assert_eq!(rd_env_step(end_turn), 0);
        let after_end_turn = exported_observation();
        assert_eq!(
            hp_before - after_end_turn[H_HERO_HP],
            previewed_damage,
            "both enemies must act, and round 1's preview must equal the fact"
        );
        assert_eq!(
            after_end_turn[H_HAND_COUNT],
            5,
            "a full hand after the round comes back to the hero"
        );
        assert_eq!(after_end_turn[H_ROUND], 2, "the round advanced");
        // The drawn cards must carry real costs out of the image (not the `-1` "could not read").
        for hand_index in 0..5 {
            let base = OFF_HAND + hand_index * 4;
            assert_eq!(after_end_turn[base], 1, "hand slot {hand_index} occupied");
            assert!(after_end_turn[base + 1] >= 0, "hand slot {hand_index} cost is unreadable");
            assert!(after_end_turn[base + 2] >= 0, "hand slot {hand_index} def_slot is unreadable");
        }

        // Out-of-range actions are refused, and refusal must not move the state.
        let before = observation();
        let out_of_range = rd_env_action_count() + 5;
        assert_eq!(rd_env_step(out_of_range), -1, "out-of-range step");
        assert_eq!(observation(), before, "a rejected step moved the observation");
        assert_eq!(
            rd_env_beat_count(),
            0,
            "a refused step must not leave the previous step's beats lying around"
        );

        // ── play the fight out ──────────────────────────────────────────────────────────────
        let mut steps = 0;
        while rd_env_done() == 0 && steps < 200 {
            let action = play_an_attack_or_end_turn();
            assert!(action >= 0, "stuck with no legal action at step {steps}");
            assert_eq!(rd_env_step(action), 0, "step {steps} was refused");
            steps += 1;
        }
        assert!(steps > 0, "the fight never advanced");
        assert_eq!(rd_env_done(), 1, "the fight did not terminate");
        assert_eq!(
            rd_env_result(),
            1,
            "an attack-first policy must win the `enc_small_slimes` fight"
        );

        // Every enemy is down and the hero is still standing.
        let obs = observation();
        assert_eq!(obs[H_RESULT], 1);
        for slot in 0..2 {
            let base = OFF_ENEMY + slot * 8;
            assert_eq!(obs[base], 0, "enemy {slot} should be down, not alive");
            assert_eq!(obs[base + 1], 0, "enemy {slot} hp");
        }
        assert!(obs[H_HERO_HP] > 0, "hero hp");

        // Determinism (`env-abi.md` §8.1): same seed + same policy ⇒ same observation stream.
        assert_eq!(rd_env_selfcheck(SEED, 40), 1, "selfcheck must be 1");
        // ... and it is not vacuous: a different seed shuffles a different opening hand.
        let different = rd_env_selfcheck(SEED + 1, 40);
        assert!(
            different == 0 || different == 1,
            "selfcheck on another seed must be a real verdict"
        );
    }

    // =========================================================================================
    // The animation log ABI (`port-plan.md` §142)
    // =========================================================================================

    fn beat_field(index: i32, field: i32) -> i32 {
        rd_env_beat_field(index, field)
    }

    fn beat_def(index: i32) -> String {
        let len = rd_env_beat_def_len(index);
        if len <= 0 {
            return String::new();
        }
        let mut bytes = vec![0u8; len as usize];
        let written = unsafe { rd_env_beat_def_into(index, bytes.as_mut_ptr()) };
        assert_eq!(written, len, "beat_def_len / beat_def_into disagree");
        String::from_utf8(bytes).expect("definition ids are ASCII")
    }

    #[test]
    fn the_animation_log_names_the_card_the_wall_slots_and_the_damage() {
        // What the page needs and what `diffObservations` cannot give it: **who hit whom, with
        // what, and for how much**, as one ordered list. Wall slots are the ABI's own numbering
        // (`-1` hero, `0..5` enemies), so the page can look up the same element it renders.
        assert_eq!(rd_env_reset(), 0);
        // `rd_env_reset` builds the fight **and starts the hero's first turn** (the browser driver
        // needs the hand on load), so the log may already hold that one boundary event. Anything
        // else here would mean the reset itself animated something nobody asked for.
        // §178: the reset now also applies the encounter's `StartingStatuses` (`§175b`), and a
        // status that lands is a `StatusChanged` beat -- `spike_slime_s` starts with Thorns 3 and
        // `acid_slime_m` with Spore Cloud 1, so three beats is the honest count here. The judgment
        // tightens from "at most one beat" to "only these two kinds, exactly one turn start": a
        // reset that animated damage or a card would still fail.
        let after_reset = rd_env_beat_count();
        let mut turn_starts = 0;
        for index in 0..after_reset {
            let kind = beat_field(index, 0);
            match kind {
                BEAT_TURN_STARTED => {
                    turn_starts += 1;
                    assert_eq!(beat_field(index, 1), -1, "the turn that starts is the hero's");
                }
                BEAT_STATUS_CHANGED => {
                    assert!(beat_field(index, 2) >= 0, "a starting status lands on an enemy");
                }
                other => panic!("reset logged beat kind {other} at {index}, which nobody asked for"),
            }
        }
        assert!(
            turn_starts <= 1,
            "reset starts at most one turn, got {turn_starts} in {after_reset} beats"
        );

        let strike = (0..rd_env_action_count())
            .find(|index| {
                rd_env_action_kind(*index) == ACTION_PLAY
                    && ensure_session()
                        .expect("session")
                        .hand_defs
                        .get(rd_env_action_arg(*index, 0).max(0) as usize)
                        .map(String::as_str)
                        == Some("strike")
            })
            .expect("the starting hand holds a strike");
        assert_eq!(rd_env_step(strike), 0, "playing a strike must be accepted");

        let count = rd_env_beat_count();
        assert!(count >= 2, "a card play and its damage: {count} beats");

        // 0 = kind, 1 = actor wall slot, 2 = target wall slot, 4 = damage dealt, 7 = has a name.
        let mut saw_play = false;
        let mut saw_damage = false;
        for index in 0..count {
            let kind = beat_field(index, 0);
            if kind == BEAT_CARD_PLAYED {
                saw_play = true;
                assert_eq!(beat_field(index, 1), -1, "the hero is wall slot -1");
                assert_eq!(beat_field(index, 7), 1, "the played card must be named");
                assert_eq!(beat_def(index), "strike", "the card **definition**, not the instance");
            }
            if kind == BEAT_DAMAGE {
                saw_damage = true;
                assert_eq!(beat_field(index, 1), -1, "hero dealt it");
                assert!(beat_field(index, 2) >= 0, "an enemy wall slot took it");
                assert!(beat_field(index, 4) > 0, "damage dealt must be positive");
                assert!(
                    beat_field(index, 4) + beat_field(index, 5) <= beat_field(index, 6).max(0) + 1,
                    "dealt + blocked cannot exceed the requested amount"
                );
            }
        }
        assert!(saw_play, "no CardPlayed beat in {count} beats");
        assert!(saw_damage, "no Damage beat in {count} beats");

        // The card play comes **before** its damage: order is the whole point.
        let first_play = (0..count)
            .find(|index| beat_field(*index, 0) == BEAT_CARD_PLAYED)
            .expect("checked above");
        let first_damage = (0..count)
            .find(|index| beat_field(*index, 0) == BEAT_DAMAGE)
            .expect("checked above");
        assert!(first_play < first_damage, "the card is played before it lands");

        assert_eq!(rd_env_beats_dropped(), 0, "nothing may be dropped");
        assert_eq!(beat_field(count, 0), -1, "past the end is -1, not a stale beat");
        assert_eq!(rd_env_beat_def_len(-1), -1);
    }

    #[test]
    fn an_end_turn_shows_every_enemy_acting_in_order() {
        // The multi-enemy half: with two slimes, ending the turn must produce **two** attacking
        // actors, in wall-slot order, and the hero must be the one taking both hits.
        assert_eq!(rd_env_reset(), 0);
        let end_turn = (0..rd_env_action_count())
            .find(|index| rd_env_action_kind(*index) == ACTION_END_TURN)
            .expect("end turn must be offered");
        assert_eq!(rd_env_step(end_turn), 0);

        let count = rd_env_beat_count();
        let mut attackers: Vec<i32> = Vec::new();
        let mut hits_on_hero = 0;
        let mut turns: Vec<i32> = Vec::new();
        for index in 0..count {
            match beat_field(index, 0) {
                BEAT_DAMAGE if beat_field(index, 2) == -1 => {
                    hits_on_hero += 1;
                    attackers.push(beat_field(index, 1));
                }
                BEAT_TURN_ENDED => turns.push(beat_field(index, 1)),
                _ => {}
            }
        }
        assert!(hits_on_hero > 0, "the enemies must have hit the hero: {count} beats");
        assert!(
            attackers.iter().all(|slot| *slot >= 0),
            "every attacker is an enemy wall slot: {attackers:?}"
        );
        // Two slimes ⇒ at least two distinct attackers, and the first one listed is slot 0.
        let mut distinct = attackers.clone();
        distinct.sort_unstable();
        distinct.dedup();
        assert!(
            distinct.len() >= 2,
            "both slimes must act, not just the first: {attackers:?}"
        );
        assert_eq!(distinct.first().copied(), Some(0), "slot 0 acts first");
        assert!(!turns.is_empty(), "the hero's turn ended somewhere in there");
        assert_eq!(turns[0], -1, "the hero's turn is what ended");
    }

    // =========================================================================================
    // X 费（`port-plan.md` §146）
    // =========================================================================================

    /// Build a session whose deck is exactly `deck`, so a test can play one specific card.
    fn session_with_deck(deck: &'static [DeckEntry<'static>]) {
        let session = build_session_with(SEED, ENCOUNTER, HERO_HP, Some(deck)).expect("a fight");
        install_session(session);
    }

    fn hero_energy() -> i32 {
        let session = ensure_session().expect("session");
        session
            .state
            .combatant(&session.hero_id().expect("hero"))
            .and_then(|hero| {
                hero.resources()
                    .iter()
                    .find(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
            })
            .unwrap_or(-1)
    }

    fn set_hero_energy(current: i32, max: i32) {
        let session = ensure_session().expect("session");
        let hero = session.hero_id().expect("hero");
        let key = rd_core::state::ResourceId::new("standard.energy").expect("id");
        session
            .state
            .combatant_mut(&hero)
            .expect("hero")
            .set_resource(key, current, Some(max))
            .expect("energy");
        session.reobserve_after_external_change();
    }

    fn play_action_of(definition: &str) -> Option<i32> {
        let session = ensure_session().expect("session");
        for index in 0..session.actions.len() {
            if session.actions[index].kind != ACTION_PLAY {
                continue;
            }
            let hand = session.actions[index].arg0.max(0) as usize;
            if session.hand_defs.get(hand).map(String::as_str) == Some(definition) {
                return Some(index as i32);
            }
        }
        None
    }

    /// §146：X 费牌花掉**全部**能量，并且真的跑 X 遍。
    ///
    /// 判据走 §142 的 beats（而不是"敌人掉了多少血"）：后者在敌人血少时会因为**打死了**而
    /// 少掉几点，看起来像"X 算错了"。beats 数的是"打了几下"，那正是 X 的定义。
    #[test]
    fn an_x_cost_card_spends_all_energy_and_hits_x_times() {
        // 1 点能量 ⇒ 恰好一遍 ⇒ 两只敌人各挨 5 点。用 1 而不是 3 是有意的：3 遍会**打死**
        // 那只 10 血的史莱姆，而"死了的敌人不再是目标"会让伤害条数少于 X×敌人数 ——
        // 那是正确的语义，但它会把这条测试变成一条关于血量的测试。
        session_with_deck(&[DeckEntry {
            card: "whirlwind",
            count: 1,
        }]);
        assert_eq!(hero_energy(), 3, "the fight starts with 3 energy");
        assert_eq!(
            ensure_session().expect("session").enemy_roster().len(),
            2,
            "`enc_small_slimes` has two enemies"
        );
        set_hero_energy(1, 3);
        let play = play_action_of("whirlwind").expect("whirlwind is in hand");
        assert_eq!(rd_env_step(play), 0, "playing an X-cost card must be accepted");
        assert_eq!(hero_energy(), 0, "an X-cost card spends ALL the energy");
        let (hits, total) = damage_beats();
        assert_eq!(hits, 2, "X = 1 ⇒ one pass over both enemies");
        assert_eq!(total, 10, "5 per enemy");

        // 3 点能量 ⇒ 3 遍。第二只史莱姆只有 10 血，所以它在第二下之后倒下，**不再是目标** ——
        // 于是伤害条数少于 6，而活下来那只吃满 15。两条一起才说清"X 真的算对了"。
        session_with_deck(&[DeckEntry {
            card: "whirlwind",
            count: 1,
        }]);
        let play = play_action_of("whirlwind").expect("whirlwind is in hand");
        assert_eq!(rd_env_step(play), 0, "3 energy is a legal X = 3");
        let (hits, total) = damage_beats();
        assert!(
            hits > 2,
            "X = 3 must be more than one pass; got {hits} hits"
        );
        assert!(
            total > 10,
            "three passes deal more than one pass (total {total})"
        );
        let mut downed = false;
        for index in 0..rd_env_beat_count() {
            if rd_env_beat_field(index, 0) == BEAT_DOWNED {
                downed = true;
            }
        }
        assert!(downed, "the 10 HP slime dies during the third pass");
    }

    /// §147：状态**按名字**读得出来 —— 观察向量的五个状态轴之外的那些（`Constricted`）靠这一对。
    ///
    /// 断言的是"名字 + 层数"，因为那正是页面要画的东西；轴之外的 debuff 在页面上看不见，
    /// 就等于玩家没法躲。
    #[test]
    fn statuses_outside_the_five_axes_are_readable_by_name() {
        session_with_deck(&[DeckEntry {
            card: "strike",
            count: 1,
        }]);
        let hero = -1;
        let count = rd_env_status_count(hero);
        assert!(count >= 0, "the hero exists");
        for index in 0..count {
            let len = rd_env_status_id_len(hero, index);
            assert!(len > 0, "status {index} has an id");
        }
        assert_eq!(rd_env_status_count(9), -1, "no such wall slot");
        assert_eq!(rd_env_status_id_len(hero, 99), -1);
        assert_eq!(rd_env_status_stacks(hero, 99), -1);

        // 现在给英雄挂一条**轴之外**的状态（`Constricted`），它必须读得出来。
        {
            let session = ensure_session().expect("session");
            let hero_id = session.hero_id().expect("hero");
            let definition = rd_core::state::StatusDefinitionId::new("standard.constricted")
                .expect("id");
            let instance = rd_core::state::StatusInstance::new(
                rd_core::state::StatusInstanceId::new("st_con").expect("id"),
                definition,
                rd_core::state::StatusPolarity::Debuff,
            )
            .with_stacks(3);
            session
                .state
                .combatant_mut(&hero_id)
                .expect("hero")
                .push_status(instance)
                .expect("room");
            session.reobserve_after_external_change();
        }
        let count = rd_env_status_count(hero);
        assert_eq!(count, 1, "one status now");
        let len = rd_env_status_id_len(hero, 0);
        let mut buffer = vec![0u8; len as usize];
        let written = unsafe { rd_env_status_id_into(hero, 0, buffer.as_mut_ptr()) };
        assert_eq!(written, len);
        assert_eq!(
            String::from_utf8(buffer).expect("ascii"),
            "standard.constricted",
            "an axis-less status must still be named"
        );
        assert_eq!(rd_env_status_stacks(hero, 0), 3);
    }

    /// `(伤害条数, 总伤害)`，只数**打在敌人身上的** hit。
    ///
    /// §178: the filter on `target >= 0` is not decoration. `enc_small_slimes` now really applies
    /// its `StartingStatuses` (`§175b`), and `spike_slime_s` starts with **Thorns 3** -- so every
    /// hero attack also logs a 3-point damage beat **on the hero**. Counting those would make this
    /// helper assert "each hit is 5" against the recoil and call a correct fight wrong.
    fn damage_beats() -> (i32, i32) {
        let mut hits = 0;
        let mut total = 0;
        for index in 0..rd_env_beat_count() {
            if rd_env_beat_field(index, 0) != BEAT_DAMAGE {
                continue;
            }
            if rd_env_beat_field(index, 2) < 0 {
                continue; // the hero took this one (thorns, spore cloud, …)
            }
            hits += 1;
            total += rd_env_beat_field(index, 4);
            assert_eq!(rd_env_beat_field(index, 4), 5, "each hit is 5");
        }
        (hits, total)
    }

    /// 0 能量也能打（X = 0），而且**什么都打不到** —— 这是 StS 的真行为（用来推进计数器）。
    ///
    /// 用上 `beats` 才能区分"打了 0 下"与"根本没受理"：前者是合法的 0 下，后者会是 `-1`。
    #[test]
    fn an_x_cost_card_played_with_no_energy_is_legal_and_does_nothing() {
        session_with_deck(&[DeckEntry {
            card: "whirlwind",
            count: 1,
        }]);
        set_hero_energy(0, 3);
        let play = play_action_of("whirlwind").expect("still playable at 0 energy");
        assert_eq!(rd_env_step(play), 0, "X = 0 is a legal play, not a refusal");
        let (hits, _) = damage_beats();
        assert_eq!(hits, 0, "X = 0 ⇒ nothing was hit");
        assert_eq!(hero_energy(), 0);
    }

    /// §146：手牌费用格里，X 费牌报的是**哨兵** `X_COST_DISPLAY`，不是它 `Costs` 里那个 0。
    ///
    /// 这条是给页面用的："0 费"是一句会被玩家当真的假话（看起来可以白打）。数字在 Rust 侧只有
    /// `X_COST_DISPLAY` 一处；`ui_test.mjs` 那边有一条断言把页面的副本和它对齐。
    #[test]
    fn the_hand_cost_cell_reports_x_cost_cards_as_the_display_sentinel() {
        session_with_deck(&[DeckEntry {
            card: "whirlwind",
            count: 1,
        }]);
        let obs = exported_observation();
        let hand = obs[OFF_HAND + 1];
        assert_eq!(
            hand, X_COST_DISPLAY,
            "an X-cost card must not report a printed 0"
        );
    }

    /// 反过来：一张普通牌照样报它的印刷费用（否则上面那条也可能是"所有牌都报 -2"）。
    #[test]
    fn a_fixed_cost_card_still_reports_its_printed_cost() {
        session_with_deck(&[DeckEntry {
            card: "strike",
            count: 1,
        }]);
        let obs = exported_observation();
        assert!(obs[OFF_HAND + 1] >= 0, "strike reports a real cost");
        assert_ne!(obs[OFF_HAND + 1], X_COST_DISPLAY);
    }

    /// `node.repeat` 的 `MaxCount` 守卫**是能踩到的**：给英雄 40 点能量就超过了 32 的上限。
    ///
    /// 这条测试的价值不在于"40 点能量会发生"，而在于证明那道守卫**真的在**、而且报的是错而不是
    /// 静默截断（"打 32 下"看起来完全正常）。
    #[test]
    fn a_repeat_past_its_maximum_is_a_loud_error_not_a_truncation() {
        session_with_deck(&[DeckEntry {
            card: "whirlwind",
            count: 1,
        }]);
        set_hero_energy(40, 40);
        let play = play_action_of("whirlwind").expect("whirlwind is in hand");
        // 一次 **faulted** 节目不是"被拒的出牌"：参考里 Faulted ⇒ 卡照样落区、报告 played
        // （`Cards/CardPlay.cs` 的终态回调）。所以判据不是步的返回值，而是**伤害一下都没有**、
        // 而且驱动记下了一个 problem —— 静默截断到 32 下会给出 32 条伤害。
        assert_eq!(rd_env_step(play), 0, "a faulted program still plays the card");
        let (hits, _) = damage_beats();
        assert_eq!(hits, 0, "the repeat faulted before the first hit");
        let session = ensure_session().expect("session");
        assert!(
            !session.problems.is_empty(),
            "40 > MaxCount(32) must be reported, not swallowed"
        );
    }
}

#[cfg(test)]
mod card_text_tests {
    //! The card face's text comes from the **content**, not from a table in the page.
    //!
    //! Pinned on purpose: `"Deal 6 damage."` is what `tools/contentc/packages/sts` says, and a card
    //! whose description silently changes to something the card no longer does is exactly the kind
    //! of drift a UI cannot notice.

    use super::*;

    fn read_text(
        len: extern "C" fn(i32) -> i32,
        into: unsafe extern "C" fn(i32, *mut u8) -> i32,
        slot: i32,
    ) -> String {
        let n = len(slot);
        if n <= 0 {
            return String::new();
        }
        let mut buffer = vec![0u8; n as usize];
        unsafe { into(slot, buffer.as_mut_ptr()) };
        String::from_utf8(buffer).expect("the content's strings are UTF-8")
    }

    fn title(slot: i32) -> String {
        read_text(rd_env_card_title_len, rd_env_card_title_into, slot)
    }

    fn text(slot: i32) -> String {
        read_text(rd_env_card_text_len, rd_env_card_text_into, slot)
    }

    /// The hand size out of the observation vector (index 10 -- `H.HAND` in `env-abi.md` §4).
    fn hand_count() -> i32 {
        let len = rd_env_observe_len();
        assert!(len > 10);
        let ptr = rd_env_observe_buf();
        assert!(!ptr.is_null());
        unsafe { *ptr.add(10) }
    }

    /// A hand with cards in it. No step is needed any more: the fight starts with the hero's first
    /// turn already begun (`start_first_turn`), so the draw has happened. The old version ended a
    /// turn here -- which now *plays a card*, because the action table leads with play actions once
    /// the hand is not empty.
    fn open_the_hand() {
        assert_eq!(rd_env_reset(), 0);
    }

    /// The card **kind** is derived from `CARD.Tags`, and the order of the questions matters:
    /// `slimed` carries `status`/`unplayable`/`junk`, so asking "attack" first and "status" last is
    /// what keeps it from being reported as an attack.
    #[test]
    fn the_card_kind_comes_from_the_tags() {
        open_the_hand();
        let hand = hand_count();
        assert!(hand > 0);
        // Every card in the opening hand is a Strike or a Defend: attack (1) or skill (2).
        for slot in 0..hand {
            let kind = super::rd_env_card_kind(slot);
            assert!(kind == 1 || kind == 2, "hand slot {slot} has kind {kind}");
        }
        // Out of range and negative are `-1`, not "no type".
        assert_eq!(super::rd_env_card_kind(hand + 5), -1);
        assert_eq!(super::rd_env_card_kind(-1), -1);

        // The junk card is a status, not an attack -- the case that would go wrong if the order of
        // the tag questions were different.
        let content = ensure_session().expect("session").content;
        assert_eq!(super::card_kind(content, "strike"), 1);
        assert_eq!(super::card_kind(content, "defend"), 2);
        assert_eq!(super::card_kind(content, "slimed"), 4);
        assert_eq!(super::card_kind(content, "no_such_card"), -1);
    }

    #[test]
    fn the_text_is_the_contents_own() {
        open_the_hand();
        let hand = hand_count();
        assert_eq!(hand, 5, "the opening hand should be five cards");

        // Every card in the hand has a title and a description, and the pair is one of the three
        // definitions the starting deck holds. The exact strings are the content's, so a change to
        // `sts.roguedeck.json` shows up here rather than on screen.
        const EXPECTED: [(&str, &str); 4] = [
            ("Strike", "Deal 6 damage."),
            ("Defend", "Gain 5 Block."),
            ("Bash", "Deal 8 damage. Apply 2 Vulnerable."),
            ("Slimed", "Unplayable."),
        ];
        let mut seen = 0;
        for slot in 0..hand {
            let (t, d) = (title(slot), text(slot));
            assert!(!t.is_empty(), "slot {slot} has no title");
            if d.is_empty() {
                continue; // a card may legitimately describe itself with nothing
            }
            assert!(
                EXPECTED.iter().any(|(want_t, want_d)| *want_t == t && *want_d == d),
                "slot {slot} reads {t:?} / {d:?}, which is not one of the content's cards"
            );
            seen += 1;
        }
        assert!(seen >= 5, "only {seen} of {hand} cards had both a title and a description");
    }

    #[test]
    fn an_empty_or_bogus_slot_is_minus_one_not_an_empty_card() {
        open_the_hand();
        // Past the end of the hand, and negative: both are "no such card", and the page must be
        // able to tell that from "a card with no text".
        for slot in [hand_count() + 3, -1, 99] {
            assert_eq!(rd_env_card_title_len(slot), -1, "slot {slot} title length");
            assert_eq!(rd_env_card_text_len(slot), -1, "slot {slot} text length");
        }
    }

    #[test]
    fn the_title_is_not_the_definition_id() {
        open_the_hand();
        // `rd_env_card_name_*` returns the id (`"strike"`); the title is the content's `NameKey`
        // (`"Strike"`). A page that shows only ids is what this pair exists to fix, so the two must
        // be observably different -- otherwise the test would pass with the title wired to the id.
        let id = {
            let n = rd_env_card_name_len(0);
            assert!(n > 0);
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_env_card_name_into(0, buffer.as_mut_ptr()) };
            String::from_utf8(buffer).unwrap()
        };
        let t = title(0);
        assert_ne!(t, id, "the title is the id again");
        assert_eq!(t.to_lowercase(), id.to_lowercase(), "the title should name the same card");
    }
    /// **Uppercut hits the enemy, not the hero.** Reported by hand as "uppercut 让自己和敌人同时受到了
    /// 伤害"; the content says `dealDamage 13 @ eventTarget` + `weak` + `vulnerable` on the same target,
    /// so the only way the hero could be hurt is if the target selector resolved to the source.
    ///
    /// The starting deck has no Uppercut, so the fight is **built with a deck that is all Uppercut** --
    /// which is also why this is a kernel test and not a browser one.
    #[test]
    fn uppercut_hurts_the_enemy_and_not_the_hero() {
        let deck: &'static [rd_core::battle::DeckEntry<'static>] =
            Box::leak(vec![
                rd_core::battle::DeckEntry { card: "uppercut", count: 10 },
            ].into_boxed_slice());
        let mut session = build_session_with(7, "enc_jaw_worm", 80, Some(deck)).expect("a fight");
        let standard = standard_turn_config().expect("a turn config");
        start_first_turn(&mut session.state, &standard, &mut session.host).expect("turn 1");
        session.reobserve();
        *slot() = Some(session);

        let hero_before = combat_hero_health();
        let enemy_before = first_enemy_health();
        assert!(hero_before > 0 && enemy_before > 0, "both alive: {hero_before}/{enemy_before}");

        // Play the first Uppercut at the first living enemy.
        let action = (0..rd_env_action_count())
            .find(|i| rd_env_action_kind(*i) == 0)
            .expect("a card to play");
        assert_eq!(rd_env_step(action), 0, "playing Uppercut");
        let _ = action;

        assert_eq!(
            combat_hero_health(),
            hero_before,
            "Uppercut must not damage the hero"
        );
        // §208: this content's jaw worm now **starts with 6 block** (wiki `Jaw Worm`: Block 6), so a
        // 13-damage Uppercut takes 6 of it off the block and 7 off the health. The assertion is the
        // wiki's arithmetic, not "13 less health" -- which was true only while the block was missing.
        assert_eq!(
            first_enemy_health(),
            enemy_before - 7,
            "Uppercut eats the 6 starting block and deals 7 to the health"
        );
    }

    /// The hero's health, straight off the combat state.
    fn combat_hero_health() -> i32 {
        let Some(session) = slot().as_ref() else { return -1 };
        session
            .hero_id()
            .and_then(|id| session.state.combatant(&id))
            .map_or(-1, |c| c.health_current)
    }

    /// The first enemy's health, straight off the combat state.
    fn first_enemy_health() -> i32 {
        let Some(session) = slot().as_ref() else { return -1 };
        let Some(enemy) = session.plan.enemies.first() else { return -1 };
        CombatantId::new(enemy.id)
            .ok()
            .and_then(|id| session.state.combatant(&id))
            .map_or(-1, |c| c.health_current)
    }


    /// §202: hero + every live enemy (`turn_order` is exactly that list), so **enemies = this - 1**.
    fn combatant_count() -> usize {
        slot().as_ref().map_or(0, |session| session.state.turn_order().len())
    }

    /// §202: the enemy count alone (the sweep above counts the hero too).
    fn enemy_count() -> usize {
        combatant_count().saturating_sub(1)
    }

    /// §202: the last session-level error text, for a message that says *why*.
    fn session_error() -> String {
        slot().as_ref().map_or_else(String::new, |session| session.error.clone())
    }

    /// §202: **镜像里的每一个遭遇都必须能建、能打。**
    ///
    /// 这条是工作包 C 的"全遭遇构造"：它走的不是测试自己拼的蓝图，而是**生产路径**
    /// (`build_session_at`) —— 去重 id（`bronze_orb#2`）、`Spawn: false`（不在开场，等召唤）、
    /// `Owner`（主人必须在这一场里）、`StartingStatuses`、敌人的血量掷骰、ASC 修正，全在里面。
    ///
    /// 判据（每一条都对应一次真实踩坑）：
    /// 1. `build_session_at` 对**每一个** `ENCT` 行都成功 —— 镜像里 34 个，一个都不能少；
    /// 2. 之后连打 `TURNS` 个"结束回合"：返回值不许是 `-3`（那才是"内核抛了"）；
    /// 3. 每一步的 `problems` 必须是空的 —— `-1`（观察没变 = 拒绝）本身合法（英雄死了/没牌可打），
    ///    但如果那一步其实抛了，`problems` 里会带着 `StepThrew(...)`。
    ///
    /// 为什么不是"断言英雄活着"：这些遭遇里有一半是 Boss，70 点血的假英雄打不过 —— 那是内容
    /// 事实，不是内核缺陷。这条测试问的是"能不能跑"，不是"能不能赢"。
    #[test]
    fn every_encounter_in_the_image_builds_and_runs_without_a_thrown_step() {
        const TURNS: usize = 12;
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("the image parses");
        // `IDX` is the image's id index and the only place an encounter's **name** lives (the `ENCT`
        // row itself does not repeat it), so the sweep walks it by entity kind rather than by row.
        let mut encounters = Vec::new();
        for position in 0..content.id_count() {
            let Some(entry) = content.id_entry(position) else {
                continue;
            };
            if entry.entity_kind == EK_ENCOUNTER {
                encounters.push(entry.id.to_string());
            }
        }
        // Loud, not "0 tests ran": the sweep is only meaningful if it really walked the table.
        assert!(
            encounters.len() >= 34,
            "the image should hold every encounter; found {}",
            encounters.len()
        );
        let mut failures = Vec::new();
        for name in &encounters {
            let session = match build_session_at(7, name, 70, None, 0, 0) {
                Ok(session) => session,
                Err(message) => {
                    failures.push(std::format!("{name}: build failed: {message}"));
                    continue;
                }
            };
            install_session(session);
            for turn in 0..TURNS {
                let verdict = rd_env_step(0); // the only legal action on a fresh turn: END_TURN
                if verdict == -3 {
                    failures.push(std::format!("{name} turn {turn}: threw: {}", session_error()));
                    break;
                }
                if rd_env_done() != 0 {
                    break; // the fight is over; that is a legal ending, not a failure
                }
            }
            crate::take_session();
        }
        assert!(failures.is_empty(), "{failures:#?}");
    }

    /// §207: a `CombatantId` from a literal, for the tests below.
    fn cid_in(name: &str) -> rd_core::state::CombatantId {
        rd_core::state::CombatantId::new(name).expect("a short id")
    }

    /// §214：Spiker —— `Attack` 不能连两次；`Buff Thorns` **最多 6 次**，之后只能 `Attack`。
    ///
    /// wiki `Shapes#Spiker`: "Cannot use Attack twice in a row. Cannot use Buff Thorns once it has
    /// been used 6 times and will instead using Attack."
    ///
    /// 三段判据：①上次是 Attack ⇒ 这次只能是 Buff Thorns；②`thorns_buffs` 到 6 ⇒ 只能 Attack
    /// （哪怕上次也是 Attack —— 两条规则同时许可是不可能的，所以"次数上限"必须**压过**"不能连两次"）；
    /// ③没约束时两招都出得来（50/50 的另一半）。
    #[test]
    fn spiker_never_repeats_its_attack_and_buffs_thorns_at_most_six_times() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_spiker", rd_core::content::EK_ENCOUNTER)
                .expect("enc_spiker")
                .index,
        );
        let ask = |last: i32, buffs: i32, seed: i32| -> String {
            let session = build_session_at(seed, "enc_spiker", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let id = cid_in("spiker");
            for (key, value) in [("last_move", last), ("thorns_buffs", buffs)] {
                let _ = session
                    .state
                    .combatant_mut(&id)
                    .expect("spiker")
                    .set_counter(rd_core::state::CounterId::new(key).expect("counter"), value);
            }
            let at = rd_core::intent::locate_enemy(&content, row, &id)
                .expect("locate")
                .expect("the spiker is in this encounter");
            rd_core::intent::select_action(&session.state, &content, at, &id, 3)
                .expect("intent")
                .expect("an action")
                .action_id
                .to_string()
        };
        for seed in 0..40 {
            assert_eq!(ask(1, 0, seed), "spiker.spike", "no Attack twice in a row");
            assert_eq!(
                ask(1, 6, seed),
                "spiker.cut",
                "after six Buff Thorns it must Attack, even though it also attacked last turn"
            );
        }
        let mut free = std::collections::BTreeSet::new();
        for seed in 0..60 {
            free.insert(ask(2, 0, seed));
        }
        assert_eq!(
            free,
            ["spiker.cut".to_string(), "spiker.spike".to_string()]
                .into_iter()
                .collect::<std::collections::BTreeSet<_>>(),
            "with no constraint both moves are available"
        );
        take_session();
    }

    /// §214：Spire Growth —— 上回合 `Constrict` **或** 玩家已 Constricted ⇒ 必 `Smash`。
    ///
    /// wiki: "If Constrict was used last turn or the player already has Constricted, it uses Smash
    /// instead." 两半分开测，因为它们走的是**两条不同的条件**（`last_move` 与 `opponentHasStatus`）。
    #[test]
    fn spire_growth_smashes_instead_of_choosing() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_spire_growth", rd_core::content::EK_ENCOUNTER)
                .expect("enc_spire_growth")
                .index,
        );
        let ask = |last: i32, constricted: bool, seed: i32| -> String {
            let session = build_session_at(seed, "enc_spire_growth", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let id = cid_in("spire_growth");
            let _ = session
                .state
                .combatant_mut(&id)
                .expect("spire growth")
                .set_counter(rd_core::state::CounterId::new("last_move").expect("counter"), last);
            if constricted {
                session
                    .state
                    .combatant_mut(&cid_in("hero"))
                    .expect("hero")
                    .push_status(
                        rd_core::state::StatusInstance::new(
                            rd_core::state::StatusInstanceId::new("st_con").expect("id"),
                            rd_core::state::StatusDefinitionId::new("standard.constricted").expect("id"),
                            rd_core::state::StatusPolarity::Debuff,
                        )
                        .with_stacks(10),
                    )
                    .expect("push");
            }
            let at = rd_core::intent::locate_enemy(&content, row, &id)
                .expect("locate")
                .expect("the spire growth is in this encounter");
            rd_core::intent::select_action(&session.state, &content, at, &id, 4)
                .expect("intent")
                .expect("an action")
                .action_id
                .to_string()
        };
        for seed in 0..40 {
            assert_eq!(
                ask(1, false, seed),
                "spire_growth.aggressive_heavy",
                "after Constrict it smashes"
            );
            assert_eq!(
                ask(2, true, seed),
                "spire_growth.aggressive_heavy",
                "a Constricted player gets smashed"
            );
        }
        take_session();
    }

    /// §213：`Hex` —— **非攻击牌**才洗 Dazed 进抽牌堆，攻击牌一张都不塞。
    ///
    /// 两条判据就是这条规则的两半：只测"技能牌会塞"的话，一个"所有牌都塞"的实现也会绿；而
    /// `Hex` 的 wiki 原话是 "Whenever you play a **non-Attack** card"。这也顺带钉住 §213 新实现的
    /// `not` 值表达式（`not(card.hasTag.attack)`）。
    #[test]
    fn hex_shuffles_a_dazed_only_for_non_attack_cards() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let session = build_session_at(7, "enc_chosen", 200, None, 0, 0).expect("the chosen fight");
        install_session(session);
        let draw_count = |state: &rd_core::state::CombatState| {
            state
                .zone_cards(&cid_in("hero"), rd_core::state::CardZone::DrawPile)
                .filter(|card| card.definition_id.as_str() == "dazed")
                .count()
        };
        // The hero gets Hex (as if the Chosen had cast it).
        {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            session
                .state
                .enqueue_effect(rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new("standard.hex").expect("id"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: Some(cid_in("chosen")),
                    source_card: None,
                })
                .expect("enqueue");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch");
        }
        // A Skill first: one Dazed.
        {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            let card = session
                .state
                .zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand)
                .find(|card| content.card_has_tag(card.definition_id.as_str(), "skill") == Some(true))
                .map(|card| card.id)
                .expect("a skill in hand");
            session
                .state
                .enqueue_event(rd_core::state::CombatEvent::CardPlayed {
                    owner: cid_in("hero"),
                    card,
                })
                .expect("queue");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch");
        }
        let after_skill = {
            let session = slot().as_ref().expect("session");
            draw_count(&session.state)
        };
        assert_eq!(after_skill, 1, "a Skill shuffles one Dazed");
        // Then an Attack: no change.
        {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            let card = session
                .state
                .zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand)
                .find(|card| content.card_has_tag(card.definition_id.as_str(), "attack") == Some(true))
                .map(|card| card.id)
                .expect("an attack in hand");
            session
                .state
                .enqueue_event(rd_core::state::CombatEvent::CardPlayed {
                    owner: cid_in("hero"),
                    card,
                })
                .expect("queue");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch");
        }
        let after_attack = {
            let session = slot().as_ref().expect("session");
            draw_count(&session.state)
        };
        assert_eq!(
            after_attack, after_skill,
            "an Attack must not shuffle a Dazed (wiki: non-Attack cards)"
        );
        take_session();
    }

    /// §213：Chosen 的开局 与 HP —— A17 把 Poke→Hex 换成 Hex→Poke。
    ///
    /// wiki："Always starts with Poke followed by Hex." / "On A17, Chosen always starts with Hex
    /// instead of Poke." 判据问的是 `select_action` 在第 1 回合给出什么，两侧（A16 / A17）各一次。
    #[test]
    fn chosen_swaps_its_opener_at_a17() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_chosen", rd_core::content::EK_ENCOUNTER)
                .expect("enc_chosen")
                .index,
        );
        let ask = |ascension: u8, round: i32, seed: i32| -> String {
            let session = build_session_at(seed, "enc_chosen", 200, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension} seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            session.state.current_round = round;
            let at = rd_core::intent::locate_enemy(&content, row, &cid_in("chosen"))
                .expect("locate")
                .expect("the chosen is in this encounter");
            rd_core::intent::select_action(&session.state, &content, at, &cid_in("chosen"), round)
                .expect("intent")
                .expect("an action")
                .action_id
                .to_string()
        };
        for seed in 0..40 {
            assert_eq!(ask(16, 1, seed), "chosen.poke", "below A17 the opener is Poke");
            assert_eq!(ask(17, 1, seed), "chosen.hex", "A17 opens with Hex");
            // The **second** move is the other one, which is what "Poke followed by Hex" means.
            assert_eq!(ask(16, 2, seed), "chosen.hex", "then Hex");
            assert_eq!(ask(17, 2, seed), "chosen.poke", "A17 then Poke");
        }
        // HP: 95 at A0, 98 from A7 (wiki 95-99 / 98-103).
        for (ascension, expected) in [(0u8, 95i32), (6, 95), (7, 98)] {
            let session = build_session_at(7, "enc_chosen", 200, None, 0, ascension)
                .expect("the chosen fight");
            install_session(session);
            let hp = {
                let session = slot().as_ref().expect("session");
                session
                    .state
                    .combatant(&cid_in("chosen"))
                    .map_or(0, |combatant| combatant.health_max)
            };
            assert_eq!(hp, expected, "Chosen max HP at A{ascension}");
        }
        take_session();
    }

    /// §212：`Nom Nom` = `5 × ceil(turn / 2)` —— wiki 的公式，逐回合验。
    ///
    /// 用**第 1..6 轮**各打一次：N 必须是 `1,1,2,2,3,3`，也就是 5,5,10,10,15,15 点。
    ///
    /// ⚠️ §216 起这一条**真的推进轮次**（`Session::exec(EndOneTurn)` 走回合机），不再写
    /// `state.current_turn = turn`。旧写法测的是"一轮内行动者序号"—— 那个量在单怪场景里
    /// **恒为 2**（绕回时置 1，`turn.rs:970`），所以旧公式 `ceil(turn/2)` 在真实玩法里永远 1 击，
    /// 而测试却因为它伪造了 1..6 而全绿。这正是 review P1-B。
    ///
    /// 这条测试钉三个容易错的写法：
    /// * 向下取整（`round / 2`）⇒ 第 1 轮就是 0 点（`repeat` 跑 0 次，**静默无伤害**）；
    /// * 读成"用了几次"而不是"第几轮" ⇒ 序列会变成 5,10,15…；
    /// * 把 `repeat` 写成一次乘好的伤害 ⇒ 那就不是多段（格挡/荆棘的行为会不同）。
    #[test]
    fn nom_nom_hits_five_damage_ceil_round_over_two_times() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let session = build_session_at(7, "enc_maw", 3000, None, 0, 0).expect("the maw fight");
        install_session(session);
        let hero = cid_in("hero");
        let hp = |state: &rd_core::state::CombatState| {
            state.combatant(&hero).map_or(0, |c| c.health_current)
        };
        let action_row = u32::from(
            content
                .lookup_in("maw.nom_nom", rd_core::content::EK_EACTION)
                .expect("nom_nom is in the image")
                .index,
        );
        let mut dealt = Vec::new();
        for round in 1..=6 {
            let before = {
                let session = slot().as_ref().expect("session");
                assert_eq!(
                    session.state.current_round, round,
                    "round counter really advanced (no forging)"
                );
                hp(&session.state)
            };
            {
                let session = slot().as_mut().expect("session");
                // 英雄结束回合 ⇒ Maw 上场（这一步只走一格回合，不让 AI 出招）。
                session.exec(&[Step::EndOneTurn]).expect("the hero ends the turn");
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("maw"),
                    action_row,
                    Some(hero),
                )
                .unwrap_or_else(|e| panic!("round {round}: {e:?}"));
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
                // Maw 结束回合 ⇒ 下一轮、又轮到英雄。
                session.exec(&[Step::EndOneTurn]).expect("the maw ends its turn");
            }
            let after = {
                let session = slot().as_ref().expect("session");
                hp(&session.state)
            };
            dealt.push(before - after);
        }
        assert_eq!(dealt, vec![5, 5, 10, 10, 15, 15], "5 x ceil(round/2)");
        take_session();
    }

    /// §212：The Maw 的四条转移规则（wiki 的句子，一句一条）。
    ///
    /// * 开局必 `Roar`；
    /// * `Slam` 之后 50/50 `Nom Nom` / `Drool`；
    /// * `Nom Nom` 之后**必** `Drool`；
    /// * 其余（`Roar` 之后、`Drool` 之后）50/50 `Slam` / `Nom Nom`。
    ///
    /// 每一条都在 80 个种子上问，因为"规则写错"往往表现为"偶尔对"。
    #[test]
    fn the_maw_follows_the_wikis_transition_table() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_maw", rd_core::content::EK_ENCOUNTER)
                .expect("enc_maw")
                .index,
        );
        let ask = |round: i32, last: i32, seed: i32| -> String {
            let session = build_session_at(seed, "enc_maw", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let id = cid_in("maw");
            session.state.current_round = round;
            let _ = session
                .state
                .combatant_mut(&id)
                .expect("the maw")
                .set_counter(rd_core::state::CounterId::new("last_move").expect("counter"), last);
            let at = rd_core::intent::locate_enemy(&content, row, &id)
                .expect("locate")
                .expect("the maw is in this encounter");
            rd_core::intent::select_action(&session.state, &content, at, &id, round)
                .expect("intent")
                .expect("an action")
                .action_id
                .to_string()
        };
        // 1: "Always starts with Roar."
        for seed in 0..80 {
            assert_eq!(ask(1, 0, seed), "maw.roar", "round 1 is always Roar");
        }
        // 3: "After using Nom Nom: always uses Drool."
        for seed in 0..80 {
            assert_eq!(ask(4, 3, seed), "maw.drool", "after Nom Nom it always drools");
        }
        // 2: "After using Slam: 50/50 Nom Nom / Drool" -- both must appear, and nothing else.
        let mut after_slam = std::collections::BTreeSet::new();
        for seed in 0..80 {
            after_slam.insert(ask(5, 2, seed));
        }
        assert_eq!(
            after_slam,
            ["maw.drool".to_string(), "maw.nom_nom".to_string()]
                .into_iter()
                .collect::<std::collections::BTreeSet<_>>(),
            "after Slam only Nom Nom / Drool"
        );
        // 4: after Roar and after Drool: 50/50 Slam / Nom Nom.
        for last in [1, 4] {
            let mut picks = std::collections::BTreeSet::new();
            for seed in 0..80 {
                picks.insert(ask(6, last, seed));
            }
            assert_eq!(
                picks,
                ["maw.nom_nom".to_string(), "maw.slam".to_string()]
                    .into_iter()
                    .collect::<std::collections::BTreeSet<_>>(),
                "after last_move={last} only Slam / Nom Nom"
            );
        }
        take_session();
    }

    /// §211：Giant Head 的 AI（wiki `Giant Head`）—— 4 回合窗口（A18 3）、同一招不能连三次、
    /// 之后一直 `It Is Time`。
    ///
    /// wiki 原话："For the first 4 (A18: 3) turns, it has a 50/50 chance to use either Count or
    /// Glare. Cannot use either move three times in a row. Afterwards, it repeats It Is Time for the
    /// rest of combat."
    ///
    /// 四条判据：
    /// 1. 窗口内只有 Count / Glare（第 1 回合，80 个种子）；
    /// 2. 窗口之后只有 It Is Time（第 5 回合 @A0、第 4 回合 @A18）；
    /// 3. **连三次禁令**：上一次与上上次都是 Count ⇒ 只能 Glare（反之亦然）；
    /// 4. @A18 第 4 回合已经在 It Is Time —— 这是"窗口缩短"这一档的分界，A17 的第 4 回合仍在窗口内。
    #[test]
    fn giant_head_counts_down_then_only_its_time() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_giant_head", rd_core::content::EK_ENCOUNTER)
                .expect("enc_giant_head")
                .index,
        );
        let ask = |ascension: u8, round: i32, last: i32, prev: i32, seed: i32| -> String {
            let session = build_session_at(seed, "enc_giant_head", 200, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension} seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let id = cid_in("giant_head");
            // `intent.round` reads `state.current_round`, **not** the third argument of
            // `select_action` -- so the round has to be set on the state or the window rule never
            // sees anything but round 1.
            session.state.current_round = round;
            for (key, value) in [("last_move", last), ("prev_move", prev)] {
                let _ = session
                    .state
                    .combatant_mut(&id)
                    .expect("giant head")
                    .set_counter(
                        rd_core::state::CounterId::new(key).expect("counter"),
                        value,
                    );
            }
            let at = rd_core::intent::locate_enemy(&content, row, &id)
                .expect("locate")
                .expect("the giant head is in this encounter");
            let choice = rd_core::intent::select_action(&session.state, &content, at, &id, round)
                .expect("intent")
                .expect("an action");
            choice.action_id.to_string()
        };
        // 1: the window offers only Count / Glare.
        for seed in 0..80 {
            let pick = ask(0, 1, 0, 0, seed);
            assert!(
                pick == "giant_head.count" || pick == "giant_head.glare",
                "round 1 must be Count/Glare, got {pick}"
            );
        }
        // 2: after the window it is always It Is Time.
        for seed in 0..40 {
            assert_eq!(ask(0, 5, 1, 2, seed), "giant_head.it_is_time", "A0 round 5");
            assert_eq!(ask(18, 4, 1, 2, seed), "giant_head.it_is_time", "A18 round 4");
        }
        // 4: A17 round 4 is still inside the window; A18 round 4 is not.
        for seed in 0..40 {
            let a17 = ask(17, 4, 1, 2, seed);
            assert!(
                a17 == "giant_head.count" || a17 == "giant_head.glare",
                "A17 round 4 must still be in the window, got {a17}"
            );
        }
        // 3: two Counts in a row force Glare, and two Glares force Count.
        for seed in 0..40 {
            assert_eq!(ask(0, 3, 1, 1, seed), "giant_head.glare", "three Counts in a row");
            assert_eq!(ask(0, 3, 2, 2, seed), "giant_head.count", "three Glares in a row");
        }
        take_session();
    }

    /// §211：`It Is Time` 的伤害**逐次 +5、有上限**，而且 A3 的起点与上限各高 10。
    ///
    /// 数值全在 wiki：`(30; A3: 40)`，每次 +5，上限 `(60; A3: 70)`。判据用**真实动作**跑八次：
    ///
    /// * A0：30, 35, 40, 45, 50, 55, 60, **60**（第 7 次到顶，第 8 次不再涨）；
    /// * A3：40, 45, 50, 55, 60, 65, 70, **70**。
    ///
    /// 第二条是"上限真的钳住了"的唯一证据 —— 只测到第 7 次的话，一个没有上限的实现会在第 8 次
    /// 给 65/75，而前面每一次都对。
    #[test]
    fn it_is_time_escalates_by_five_and_respects_its_cap() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        for (ascension, expected) in [
            (0u8, vec![30, 35, 40, 45, 50, 55, 60, 60]),
            (3u8, vec![40, 45, 50, 55, 60, 65, 70, 70]),
        ] {
            // 2000 HP: eight uses at A3 total 490 damage, so a 400-HP hero would die on the seventh
            // and the eighth "hit" would read as the remainder (15) -- which is what the first
            // version of this test measured.
            let session = build_session_at(7, "enc_giant_head", 2000, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            let mut dealt = Vec::new();
            for _ in 0..expected.len() {
                let hero = cid_in("hero");
                let hp = |state: &rd_core::state::CombatState| {
                    state.combatant(&hero).map_or(0, |c| c.health_current)
                };
                let before = {
                    let session = slot().as_ref().expect("session");
                    hp(&session.state)
                };
                {
                    let session = slot().as_mut().expect("session");
                    let id = cid_in("giant_head");
                    // `execute_action` takes the **EACT row**, not the action id.
                    let action_row = u32::from(
                        content
                            .lookup_in("giant_head.it_is_time", rd_core::content::EK_EACTION)
                            .expect("it_is_time is in the image")
                            .index,
                    );
                    rd_core::intent::execute_action(
                        &mut session.state,
                        &content,
                        &id,
                        action_row,
                        Some(cid_in("hero")),
                    )
                    .expect("It Is Time");
                    rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
                }
                let after = {
                    let session = slot().as_ref().expect("session");
                    hp(&session.state)
                };
                dealt.push(before - after);
            }
            assert_eq!(dealt, expected, "A{ascension}: It Is Time damage per use");
        }
        take_session();
    }

    /// §257：`Lagavulin` 的**受伤即警醒**（wiki 的另一半）+ 醒来那一回合眩晕。
    ///
    /// 四段判据，每一段都能单独红：
    /// 1. 开局：`asleep` + `metallicize 8` 都在，第 1 回合的意图是 `Sleep`；
    /// 2. **掉血**的一击 ⇒ `asleep` 被摘掉、`metallicize` 被摘掉、`lagavulin_woken == 1`；
    /// 3. 那一回合的意图是 `Stunned`（不是 Attack）—— "被吵醒才眩晕"；
    /// 4. 眩晕那招把记号清掉之后**不再回去睡**（`Sleep` 只在前 3 回合**且**身上还有 asleep 时选）。
    #[test]
    fn lagavulin_wakes_when_it_loses_health_and_loses_a_turn() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let session = build_session_at(11, "enc_lagavulin", 200, None, 0, 0).expect("the fight");
        install_session(session);
        let row = u32::from(
            content
                .lookup_in("enc_lagavulin", rd_core::content::EK_ENCOUNTER)
                .expect("enc_lagavulin")
                .index,
        );

        let asleep = |state: &rd_core::state::CombatState| {
            let id = cid_in("lagavulin");
            state.combatant(&id).is_some_and(|c| {
                c.statuses()
                    .iter()
                    .any(|s| s.definition_id.as_str() == "standard.lagavulin_asleep")
            })
        };
        let metallicize = |state: &rd_core::state::CombatState| {
            let id = cid_in("lagavulin");
            state.combatant(&id).map_or(0, |c| {
                c.statuses()
                    .iter()
                    .filter(|s| s.definition_id.as_str() == "standard.metallicize")
                    .map(|s| s.stacks)
                    .sum::<i32>()
            })
        };
        let counter = |state: &rd_core::state::CombatState, key: &str| {
            let id = cid_in("lagavulin");
            state.combatant(&id).map_or(0, |c| {
                c.counters()
                    .iter()
                    .find(|e| e.key.as_str() == key)
                    .map_or(0, |e| e.value)
            })
        };
        let intent = |state: &rd_core::state::CombatState, round: i32| -> std::string::String {
            let id = cid_in("lagavulin");
            let at = rd_core::intent::locate_enemy(&content, row, &id)
                .expect("locate")
                .expect("lagavulin is in this encounter");
            rd_core::intent::select_action(state, &content, at, &id, round)
                .expect("intent")
                .expect("a move")
                .action_id
                .to_string()
        };

        // ① 开局：睡着，8 点 Metallicize，意图 Sleep。
        {
            let session = slot().as_ref().expect("session");
            assert!(asleep(&session.state), "it starts asleep");
            assert_eq!(metallicize(&session.state), 8, "Metallicize 8");
            assert_eq!(intent(&session.state, 1), "lagavulin.sleep");
        }

        // ②③ 掉血 ⇒ 醒、摘 Metallicize、下一步眩晕。
        {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("lagavulin")),
                    amount: 5,
                    ignores_block: false,
                    source: Some(cid_in("hero")),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("the hit");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        {
            let session = slot().as_ref().expect("session");
            assert!(!asleep(&session.state), "the hit wakes it (Asleep is gone)");
            assert_eq!(metallicize(&session.state), 0, "waking removes Metallicize");
            assert_eq!(counter(&session.state, "lagavulin_woken"), 1, "it just woke");
            assert_eq!(intent(&session.state, 2), "lagavulin.stunned", "woken by damage ⇒ a lost turn");
        }

        // ④ 眩晕那一招清掉记号；第 3 回合它**不再睡**，而是出招。
        {
            let session = slot().as_mut().expect("session");
            let action_row = u32::from(
                content
                    .lookup_in("lagavulin.stunned", rd_core::content::EK_EACTION)
                    .expect("stunned row")
                    .index,
            );
            rd_core::intent::execute_action(
                &mut session.state,
                &content,
                &cid_in("lagavulin"),
                action_row,
                Some(cid_in("hero")),
            )
            .expect("stunned");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            let session = slot().as_ref().expect("session");
            assert_eq!(counter(&session.state, "lagavulin_woken"), 0, "the stunned turn clears it");
            let next = intent(&session.state, 3);
            assert_ne!(next, "lagavulin.sleep", "a woken Lagavulin never goes back to sleep");
            assert_eq!(next, "lagavulin.attack", "and it starts its Attack / Attack / Siphon cycle");
        }
        take_session();
    }

    /// §257：`Lagavulin` 自己睡满三回合时**不眩晕**，直接开始 `Attack、Attack、Siphon Soul`。
    ///
    /// 这条与上一条是**同一份 wiki 的两半**（"If it takes any damage, it will be stunned for one
    /// turn … If three turns pass without any damage taken, it will awake and immediately begin
    /// attacking"）。只测其中一半，另一半写错也没有闸门会红。
    #[test]
    fn lagavulin_wakes_on_its_own_unstunned_and_cycles_attack_attack_siphon() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let session = build_session_at(12, "enc_lagavulin", 200, None, 0, 0).expect("the fight");
        install_session(session);
        let row = u32::from(
            content
                .lookup_in("enc_lagavulin", rd_core::content::EK_ENCOUNTER)
                .expect("enc_lagavulin")
                .index,
        );
        let at = {
            let session = slot().as_ref().expect("session");
            rd_core::intent::locate_enemy(&content, row, &cid_in("lagavulin"))
                .expect("locate")
                .expect("lagavulin")
        };
        let intent = |round: i32| -> std::string::String {
            let session = slot().as_ref().expect("session");
            rd_core::intent::select_action(&session.state, &content, at, &cid_in("lagavulin"), round)
                .expect("intent")
                .expect("a move")
                .action_id
                .to_string()
        };
        let run = |action_id: &str| {
            let session = slot().as_mut().expect("session");
            let action_row = u32::from(
                content
                    .lookup_in(action_id, rd_core::content::EK_EACTION)
                    .expect("the row")
                    .index,
            );
            rd_core::intent::execute_action(
                &mut session.state,
                &content,
                &cid_in("lagavulin"),
                action_row,
                Some(cid_in("hero")),
            )
            .expect("the move");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
        };

        // 第 1-3 回合睡；**自己醒**（没人打它）⇒ 一条 `TurnStarted` 触发器摘掉 asleep + Metallicize。
        for round in 1..=3 {
            assert_eq!(intent(round), "lagavulin.sleep", "round {round}: still asleep");
        }
        {
            let session = slot().as_mut().expect("session");
            // `intent.round` 与触发器的 `roundNumber` **都**读 `state.current_round`（不是
            // `select_action` 的第三个参数）⇒ 必须先把回合推进到 4，否则测的仍是第 1 回合。
            session.state.current_round = 4;
            let mut host = rd_core::host::Host::new(&content);
            host.try_run_turn_started_triggers(&mut session.state, &cid_in("lagavulin"))
                .expect("turn started");
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        assert_eq!(
            intent(4),
            "lagavulin.attack",
            "waking on its own is NOT a lost turn: it attacks immediately"
        );
        // 然后严格 Attack、Attack、Siphon Soul。
        assert_eq!(intent(5), "lagavulin.attack", "second attack");
        run("lagavulin.attack");
        run("lagavulin.attack");
        assert_eq!(intent(6), "lagavulin.siphon_soul", "then Siphon Soul");
        run("lagavulin.siphon_soul");
        assert_eq!(intent(7), "lagavulin.attack", "and the cycle repeats");
        take_session();
    }

    /// §257：`Book of Stabbing` 的 N —— wiki 是 **2 + 已用次数**（内容原来是 3，多打一整下）。
    ///
    /// 判据读**英雄掉了多少血**而不是计数器：`6×2` 与 `6×3` 差 6，这个差在状态上是可观察的。
    /// 同时钉住 A3 的 `7×N`（阈值 3 而不是 4）。
    #[test]
    fn book_of_stabbing_multistab_starts_at_two_hits() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        for (ascension, expected) in [(0u8, vec![12, 18, 24]), (3u8, vec![14, 21, 28])] {
            let session = build_session_at(13, "enc_book_of_stabbing", 500, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            let mut dealt = Vec::new();
            for _ in 0..3 {
                let before = {
                    let session = slot().as_ref().expect("session");
                    session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current)
                };
                {
                    let session = slot().as_mut().expect("session");
                    let action_row = u32::from(
                        content
                            .lookup_in("book_of_stabbing.multi_stab", rd_core::content::EK_EACTION)
                            .expect("multi_stab")
                            .index,
                    );
                    rd_core::intent::execute_action(
                        &mut session.state,
                        &content,
                        &cid_in("book_of_stabbing"),
                        action_row,
                        Some(cid_in("hero")),
                    )
                    .expect("multi stab");
                    rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
                }
                let after = {
                    let session = slot().as_ref().expect("session");
                    session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current)
                };
                dealt.push(before - after);
            }
            assert_eq!(dealt, expected, "A{ascension}: 2, 3, 4 hits of 6 (A3: 7)");
            take_session();
        }
    }

    /// §257：`Nemesis` 的三条禁令 + 首回合 50/50。
    ///
    /// 判据是**穷尽**的：对每一种 `(last, prev)` 组合、每个种子，选出的一招都不许是禁的那一招。
    /// 只测"能选出 Scythe"是不够的 —— 禁令失效时那句话仍然成立。
    #[test]
    fn nemesis_never_repeats_burn_or_scythe_and_never_triple_attacks() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_nemesis", rd_core::content::EK_ENCOUNTER)
                .expect("enc_nemesis")
                .index,
        );
        // 代号：1 = tri_attack、2 = tri_burn、3 = scythe（与动作节目里的 bookkeeping 一致）。
        let ask = |seed: i32, last: i32, prev: i32| -> std::string::String {
            let session = build_session_at(seed, "enc_nemesis", 300, None, 0, 0)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            session.state.current_round = 5;
            for (key, value) in [("last_move", last), ("prev_move", prev)] {
                let _ = session
                    .state
                    .combatant_mut(&cid_in("nemesis"))
                    .expect("nemesis")
                    .set_counter(rd_core::state::CounterId::new(key).expect("counter"), value);
            }
            let at = rd_core::intent::locate_enemy(&content, row, &cid_in("nemesis"))
                .expect("locate")
                .expect("nemesis");
            let pick = rd_core::intent::select_action(
                &session.state,
                &content,
                at,
                &cid_in("nemesis"),
                5,
            )
            .expect("intent")
            .expect("a move");
            let out = pick.action_id.to_string();
            take_session();
            out
        };
        for seed in 0..40 {
            // 不能连 Tri Burn 两次。
            assert_ne!(ask(seed, 2, 1), "nemesis.tri_burn", "seed {seed}: burn twice");
            // 不能连 Scythe 两次。
            assert_ne!(ask(seed, 3, 1), "nemesis.scythe", "seed {seed}: scythe twice");
            // 不能连 Tri Attack 三次。
            assert_ne!(
                ask(seed, 1, 1),
                "nemesis.tri_attack",
                "seed {seed}: three attacks in a row"
            );
        }
        // 首回合只有 Tri Burn / Tri Attack（`ask` 把回合钉在 5，所以这里单独走一遍回合 1）。
        for seed in 0..40 {
            let session = build_session_at(seed, "enc_nemesis", 300, None, 0, 0)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            session.state.current_round = 1;
            let at = rd_core::intent::locate_enemy(&content, row, &cid_in("nemesis"))
                .expect("locate")
                .expect("nemesis");
            let pick = rd_core::intent::select_action(
                &session.state,
                &content,
                at,
                &cid_in("nemesis"),
                1,
            )
            .expect("intent")
            .expect("a move")
            .action_id
            .to_string();
            take_session();
            assert_ne!(pick, "nemesis.scythe", "seed {seed}: no Scythe on turn 1");
            assert!(
                pick == "nemesis.tri_burn" || pick == "nemesis.tri_attack",
                "seed {seed}: turn 1 is Tri Burn or Tri Attack, got {pick}"
            );
        }
        let _ = content;
    }

    /// §257：`Reptomancer` 的匕首上限 —— **4 把在手就改打 Snake Strike**。
    ///
    /// 判据两侧：③4 把时必须改招；②2 把时**不许**改招（否则"永远打 Snake Strike"也会绿）。
    #[test]
    fn reptomancer_switches_to_snake_strike_when_four_daggers_are_out() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_reptomancer", rd_core::content::EK_ENCOUNTER)
                .expect("enc_reptomancer")
                .index,
        );
        let session = build_session_at(14, "enc_reptomancer", 300, None, 0, 0).expect("the fight");
        install_session(session);
        let ask = |round: i32| -> std::string::String {
            let session = slot().as_ref().expect("session");
            let at = rd_core::intent::locate_enemy(&content, row, &cid_in("reptomancer"))
                .expect("locate")
                .expect("reptomancer");
            rd_core::intent::select_action(
                &session.state,
                &content,
                at,
                &cid_in("reptomancer"),
                round,
            )
            .expect("intent")
            .expect("a move")
            .action_id
            .to_string()
        };
        let alive = |state: &rd_core::state::CombatState| {
            state
                .combatants()
                .iter()
                .filter(|c| {
                    c.team_id == rd_core::state::TeamId::new("enemy").expect("team")
                        && c.lifecycle_state == rd_core::state::CombatantLifecycleState::Alive
                })
                .count()
        };
        // 开局：Reptomancer + 2 Dagger = 3。第 1 回合永远是 Spawn Dagger。
        {
            let session = slot().as_ref().expect("session");
            assert_eq!(alive(&session.state), 3, "the encounter starts with two daggers");
            assert_eq!(ask(1), "reptomancer.spawn_dagger", "it always opens with Spawn Dagger");
        }
        // 再召两把 ⇒ 5 个活着的敌人（= 4 把匕首）⇒ 上限生效。
        {
            let session = slot().as_mut().expect("session");
            for index in 0..2 {
                let id = std::format!("dagger#cap{index}");
                session
                    .state
                    .add_combatant(rd_core::state::Combatant::new(
                        rd_core::state::CombatantId::new(&id).expect("id"),
                        rd_core::state::CombatantDefinitionId::new("dagger").expect("definition"),
                        rd_core::state::TeamId::new("enemy").expect("team"),
                        20,
                        20,
                    ))
                    .expect("summon");
            }
            assert_eq!(alive(&session.state), 5);
            assert_eq!(
                ask(5),
                "reptomancer.snake_strike",
                "four daggers in play ⇒ Spawn Dagger is replaced by Snake Strike"
            );
        }
        take_session();
    }

    /// §257：`Reptomancer` 在 **A18** 一次召两把；同一场在 A17 只召一把。
    ///
    /// 阈值（18）与数量（2）一起测 —— 只测数量会在 A0 就红，只测阈值会在"召了 1 把"上绿。
    #[test]
    fn reptomancer_spawns_two_daggers_at_a18_only() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        for (ascension, expected) in [(17u8, 1usize), (18u8, 2)] {
            let session = build_session_at(15, "enc_reptomancer", 300, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            let before = {
                let session = slot().as_ref().expect("session");
                session.state.combatants().len()
            };
            {
                let session = slot().as_mut().expect("session");
                let action_row = u32::from(
                    content
                        .lookup_in("reptomancer.spawn_dagger", rd_core::content::EK_EACTION)
                        .expect("spawn_dagger")
                        .index,
                );
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("reptomancer"),
                    action_row,
                    Some(cid_in("hero")),
                )
                .expect("spawn");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let after = {
                let session = slot().as_ref().expect("session");
                session.state.combatants().len()
            };
            assert_eq!(after - before, expected, "A{ascension}: daggers summoned");
            take_session();
        }
    }

    /// §257：`Blue Slaver` 的 **A17** 规则 —— 绝不连用 Rake 两次；以及任何等级都"同招不连三次"。
    ///
    /// 三段判据，缺一段就会漏掉一种写错的方式：
    /// 1. @A17 且上一次是 Rake ⇒ 只能是 Stab（wiki 的 A17 规则）；
    /// 2. @A16 同一种输入**允许** Rake —— 否则"永远打 Stab"也会让第 1 段绿；
    /// 3. 上一次与上上次都是 Stab ⇒ 不能再 Stab（任何等级）。
    #[test]
    fn blue_slaver_never_rakes_twice_in_a_row_at_a17() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_slavers", rd_core::content::EK_ENCOUNTER)
                .expect("enc_slavers")
                .index,
        );
        let ask = |ascension: u8, seed: i32, last: i32, prev: i32| -> std::string::String {
            let session = build_session_at(seed, "enc_slavers", 300, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension} seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            session.state.current_round = 6;
            for (key, value) in [("last_move", last), ("prev_move", prev)] {
                let _ = session
                    .state
                    .combatant_mut(&cid_in("blue_slaver"))
                    .expect("blue slaver")
                    .set_counter(rd_core::state::CounterId::new(key).expect("counter"), value);
            }
            let at = rd_core::intent::locate_enemy(&content, row, &cid_in("blue_slaver"))
                .expect("locate")
                .expect("the blue slaver");
            let pick = rd_core::intent::select_action(
                &session.state,
                &content,
                at,
                &cid_in("blue_slaver"),
                6,
            )
            .expect("intent")
            .expect("a move");
            let out = pick.action_id.to_string();
            take_session();
            out
        };
        // 代号：1 = Stab、2 = Rake。
        for seed in 0..40 {
            assert_ne!(
                ask(17, seed, 2, 1),
                "blue_slaver.rake",
                "seed {seed}: A17 forbids Rake twice in a row"
            );
            assert_ne!(
                ask(0, seed, 1, 1),
                "blue_slaver.stab",
                "seed {seed}: the same attack three times in a row is forbidden at any level"
            );
        }
        // @A16 同一种输入仍允许 Rake（否则"永远打 Stab"会让上面第一条白绿）。
        let mut rakes = 0;
        for seed in 0..40 {
            if ask(16, seed, 2, 1) == "blue_slaver.rake" {
                rakes += 1;
            }
        }
        assert!(rakes > 0, "below A17 a Rake after a Rake is legal (took {rakes}/40)");
    }


    /// §258：虱子的 Bite 是**开局掷的**（`roll.bite` 5-7，A2 起 6-8），而绿虱子曾经写死成 6。
    ///
    /// 三段判据：
    /// 1. 掷出来的值落在 A0 的 5-7 / A2 的 6-8 里（**且真的会变**：40 个种子不止一个值）；
    /// 2. 绿虱子的 Bite **打出的伤害就是那个掷值**（写死 6 的话第 1 段仍然绿，第 2 段才红）；
    /// 3. 绿虱子在遭遇里真的存在（`enc_two_louses`）—— 它以前是"有名册行、没有任何遭遇"的死内容。
    #[test]
    fn louse_bites_are_rolled_at_spawn_and_the_green_one_reads_its_roll() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let roll_of = |state: &rd_core::state::CombatState, who: &str| -> i32 {
            state
                .combatant(&cid_in(who))
                .map_or(-1, |c| {
                    c.counters()
                        .iter()
                        .find(|e| e.key.as_str() == "roll.bite")
                        .map_or(-1, |e| e.value)
                })
        };

        for (ascension, low, high) in [(0u8, 5, 7), (2u8, 6, 8)] {
            let mut seen = std::collections::BTreeSet::new();
            for seed in 0..40 {
                let session = build_session_at(seed, "enc_two_louses", 200, None, 0, ascension)
                    .unwrap_or_else(|e| panic!("A{ascension} seed {seed}: {e}"));
                install_session(session);
                let session = slot().as_ref().expect("session");
                let green = roll_of(&session.state, "louse_green");
                assert!(
                    (low..=high).contains(&green),
                    "A{ascension} seed {seed}: roll.bite = {green}, wiki says {low}-{high}"
                );
                seen.insert(green);
                take_session();
            }
            assert!(seen.len() > 1, "A{ascension}: the roll never varied ({seen:?})");
        }

        // 绿虱子打出的伤害 == 它自己的掷值。
        for seed in 0..8 {
            let session = build_session_at(seed, "enc_two_louses", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            install_session(session);
            let (rolled, before) = {
                let session = slot().as_ref().expect("session");
                (
                    roll_of(&session.state, "louse_green"),
                    session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current),
                )
            };
            {
                let session = slot().as_mut().expect("session");
                let row = u32::from(
                    content
                        .lookup_in("louse_green.bite", rd_core::content::EK_EACTION)
                        .expect("the green bite")
                        .index,
                );
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("louse_green"),
                    row,
                    Some(cid_in("hero")),
                )
                .expect("bite");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let after = {
                let session = slot().as_ref().expect("session");
                session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current)
            };
            assert_eq!(before - after, rolled, "seed {seed}: green Bite deals its roll");
            take_session();
        }
    }

    /// §258：`time_eater.head_slam` 的 **A4**（26 → 32）原来整档是缺的。
    ///
    /// A19 那一档本来就在（它加 2 张 Slimed），但它的伤害也停在 26 —— 也就是说从 A4 起
    /// 一直少 6 点。判据在**边界两侧**：A3 是 26，A4 是 32。
    #[test]
    fn time_eater_head_slam_reaches_32_at_a4() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        for (ascension, expected) in [(3u8, 26), (4u8, 32), (19u8, 32)] {
            let session = build_session_at(21, "enc_time_eater", 400, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            let before = {
                let session = slot().as_ref().expect("session");
                session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current)
            };
            {
                let session = slot().as_mut().expect("session");
                let row = u32::from(
                    content
                        .lookup_in("time_eater.head_slam", rd_core::content::EK_EACTION)
                        .expect("head slam")
                        .index,
                );
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("time_eater"),
                    row,
                    Some(cid_in("hero")),
                )
                .expect("head slam");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let after = {
                let session = slot().as_ref().expect("session");
                session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current)
            };
            assert_eq!(before - after, expected, "A{ascension}: Head Slam damage");
            take_session();
        }
    }

    /// §258：`slaver_red.scrape` 的 **A17**（Vulnerable 1 → 2）原来整档是缺的。
    #[test]
    fn slaver_red_scrape_applies_two_vulnerable_from_a17() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        for (ascension, expected) in [(16u8, 1), (17u8, 2)] {
            let session = build_session_at(22, "enc_slavers", 300, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            {
                let session = slot().as_mut().expect("session");
                let row = u32::from(
                    content
                        .lookup_in("slaver_red.scrape", rd_core::content::EK_EACTION)
                        .expect("scrape")
                        .index,
                );
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("slaver_red"),
                    row,
                    Some(cid_in("hero")),
                )
                .expect("scrape");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let stacks = {
                let session = slot().as_ref().expect("session");
                session
                    .state
                    .combatant(&cid_in("hero"))
                    .map_or(0, |c| {
                        c.statuses()
                            .iter()
                            .filter(|s| s.definition_id.as_str() == "standard.vulnerable")
                            .map(|s| s.stacks)
                            .sum::<i32>()
                    })
            };
            assert_eq!(stacks, expected, "A{ascension}: Vulnerable from Scrape");
            take_session();
        }
    }

    /// §258：两只虱子的**招式表**（wiki：红 = Bite + Grow，绿 = Bite + Spit Web）。
    ///
    /// 之前是反的：红虱子身上挂着 Spit Web，绿虱子有 Grow 而没有 Spit Web。这条判据直接读镜像的
    /// `ENCT.Enemies[].Actions`，所以"只改名册、没改遭遇"也会红（两者必须一致，内容门也查）。
    #[test]
    fn the_two_louses_have_the_moves_the_wiki_gives_them() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let entry = content
            .lookup_in("enc_two_louses", rd_core::content::EK_ENCOUNTER)
            .expect("the 2-louse encounter");
        let list = content
            .encounter_enemies(u32::from(entry.index))
            .expect("enemies");
        let mut red = std::vec::Vec::new();
        let mut green = std::vec::Vec::new();
        for index in 0..list.len() {
            let spec = list.get(index).expect("a record");
            let mut actions = std::vec::Vec::new();
            let slots = spec.actions().expect("an actions cell");
            for index in 0..slots.len() {
                let action = slots.string(index).expect("an action id");
                actions.push(std::string::String::from(action));
            }
            match spec.id().expect("an id") {
                "louse_red" => red = actions,
                "louse_green" => green = actions,
                other => panic!("unexpected enemy {other}"),
            }
        }
        assert_eq!(red, ["louse_red.bite", "louse_red.grow"], "wiki: Red Louse = Bite + Grow");
        assert_eq!(
            green,
            ["louse_green.bite", "louse_green.spit_web"],
            "wiki: Green Louse = Bite + Spit Web"
        );
    }

    /// §267：零基建批次的**反应轴**（掉血 / 消耗 / 出牌 / 回合初）。
    ///
    /// 这一组的关键是**次数**："第一次掉血"、"每出一张攻击牌"、"每次消耗" —— 写成"每次都算"
    /// 或"只算一次"都不会报错，只会让数字慢慢不对，所以每条都断言**两次事件之后**的值。
    #[test]
    fn the_reaction_relics_fire_the_right_number_of_times() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: &str, card: &'static str, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card, count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(seed, "enc_cultist", 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(carrier)
                        .expect("a status id"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply the carrier");
            let standard = standard_turn_config().expect("standard turn config");
            let session = slot().as_mut().expect("session");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
        };
        let hand = || -> usize {
            let session = slot().as_ref().expect("session");
            session.state.zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand).count()
        };
        let enemy_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map_or(-1, |c| c.health_current)
        };
        let hero_stacks = |status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(0, |c| {
                c.statuses()
                    .iter()
                    .filter(|s| s.definition_id.as_str() == status_id)
                    .map(|s| s.stacks)
                    .sum()
            })
        };
        // 让英雄失去 `amount` 点血。**必须带出手方**：`Host::run_damage_taken_triggers` 的第一句
        // 就是"没有出手方就跳过"（与参考同一条），所以 `source: None` 的伤害**不会**触发掉血类
        // 遗物 —— §267 的判据就是这么红的（"第一次掉血抽 3 张"得到 5）。
        let lose_hp = |amount: i32| {
            let session = slot().as_mut().expect("session");
            let attacker = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("hero")),
                    amount,
                    ignores_block: true,
                    source: Some(attacker),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        // 打一张手牌（按 tag 挑）并排空队列。
        let play_one = |tag: &str| {
            let session = slot().as_mut().expect("session");
            let hero = cid_in("hero");
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let instance = session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::Hand)
                .find(|card| content.card_has_tag(card.definition_id.as_str(), tag) == Some(true))
                .map(|card| card.id)
                .unwrap_or_else(|| panic!("no `{tag}` card in hand"));
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::GainResource {
                    target: Some(hero),
                    key: rd_core::state::ResourceId::new("standard.energy").expect("energy"),
                    amount: 30,
                    default_max: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("energy");
            rd_core::play::play_card(
                &mut session.state,
                Some(&content),
                &rd_core::play::PlayRequest::new(hero, instance, Some(enemy)),
            )
            .expect("play the card");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };

        // ---- Centennial Puzzle：**只**第一次掉血抽 3 张。
        session_for("standard.centennial_puzzle", "strike", 221);
        let before = hand();
        lose_hp(3);
        assert_eq!(hand(), before + 3, "Centennial Puzzle: the first HP loss draws 3");
        let before = hand();
        lose_hp(3);
        assert_eq!(hand(), before, "…and the second one draws nothing");
        take_session();

        // ---- Runic Cube：**每次**掉血抽 1 张。
        session_for("standard.runic_cube", "strike", 222);
        let before = hand();
        lose_hp(3);
        assert_eq!(hand(), before + 1, "Runic Cube: 1 card per HP loss");
        let before = hand();
        lose_hp(3);
        assert_eq!(hand(), before + 1, "…and again");
        take_session();

        // ---- Charon's Ashes：每消耗一张牌 ⇒ 对敌人 3 点。
        // `offering` 出完就自消耗（牌组里全是它），所以"消耗"是真出牌造成的。
        session_for("standard.charons_ashes", "offering", 223);
        let before = enemy_hp();
        play_one("skill");
        assert!(
            before - enemy_hp() >= 3,
            "Charon's Ashes: exhausting a card deals at least 3 to the enemy"
        );
        take_session();

        // ---- Duality：每出一张攻击牌 +1 敏捷，并挂上"回合末归还"的孪生。
        session_for("standard.duality", "strike", 224);
        let before = hero_stacks("standard.dexterity");
        play_one("attack");
        assert_eq!(
            hero_stacks("standard.dexterity"),
            before + 1,
            "Duality: +1 Dexterity per Attack"
        );
        assert_eq!(
            hero_stacks("standard.lose_dexterity"),
            1,
            "…and the twin that gives it back at end of turn"
        );
        take_session();

        // ---- Akabeko：**第一张**攻击 +8，第二张不再加。
        session_for("standard.akabeko", "strike", 225);
        {
            let before = enemy_hp();
            play_one("attack");
            assert_eq!(before - enemy_hp(), 14, "Akabeko: the first Attack deals 6 + 8");
        }
        {
            let before = enemy_hp();
            play_one("attack");
            assert_eq!(before - enemy_hp(), 6, "Akabeko: the second Attack is back to 6");
        }
        take_session();

        // ---- Brimstone：**每次**回合初自己 +2 力量、敌人 +1 力量。
        //
        // ⚠️ 第 1 回合的开始也算一次（`start_first_turn` 就在那一刻派的触发器），所以
        // "开局 2 力量、打完一回合 4 力量"才是对的 —— 第一版断言写成 2，是**夹具**算错回合数。
        session_for("standard.brimstone", "strike", 226);
        assert_eq!(
            hero_stacks("standard.strength"),
            2,
            "Brimstone: +2 Strength at the first turn start"
        );
        {
            // 这一刻 Cultist 的 `Ritual` 还没跑（它在**它的**回合末才给），所以这个数只可能
            // 来自 Brimstone。
            let session = slot().as_ref().expect("session");
            let only_brimstone: i32 = session
                .state
                .combatants()
                .iter()
                .filter(|c| c.team_id.as_str() == "enemy")
                .map(|c| {
                    c.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == "standard.strength")
                        .map(|s| s.stacks)
                        .sum::<i32>()
                })
                .sum();
            assert_eq!(
                only_brimstone, 1,
                "Brimstone: +1 Strength for the enemies at the first turn start"
            );
        }
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn 1");
        }
        assert_eq!(
            hero_stacks("standard.strength"),
            4,
            "Brimstone: another +2 at the second turn start"
        );
        let enemy_strength = {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .filter(|c| c.team_id.as_str() == "enemy")
                .map(|c| {
                    c.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == "standard.strength")
                        .map(|s| s.stacks)
                        .sum::<i32>()
                })
                .sum::<i32>()
        };
        // 敌人是 Cultist，它自己的 `Ritual` 在**它的回合末**给 3 点力量 ⇒ 数字里混着两件事。
        // 所以这里钉的是**两层**：Brimstone 那一层（第 1 回合开始就已经是 1）与合计
        // （1 + 3 仪式 + 1 第二回合开始 = 5）。写清楚来源，比断言一个"看起来该是 2"的数好。
        assert_eq!(
            enemy_strength, 5,
            "Brimstone: 1 + the Cultist's own Ritual 3 + another 1 at the second turn start"
        );
        take_session();
    }

    /// §267：零基建批次的**轮次轴**（抽牌 / 能量 / 周期）。
    #[test]
    fn the_turn_axis_relics_move_draw_energy_and_periods() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: Option<&str>, steps: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "defend", count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(207, "enc_cultist", 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier:?}: {e}"));
            install_session(session);
            if let Some(carrier) = carrier {
                let session = slot().as_mut().expect("session");
                let item = rd_core::state::EffectItem {
                    request: rd_core::state::EffectRequest::ApplyStatus {
                        target: Some(cid_in("hero")),
                        definition: rd_core::state::StatusDefinitionId::new(carrier)
                            .expect("a status id"),
                        stacks: 1,
                        duration: 0,
                        charges: 0,
                        source: None,
                        source_card: None,
                    },
                    chain: rd_core::state::ChainSlot::NONE,
                    owner: None,
                };
                rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                    .expect("apply the carrier");
            }
            let standard = standard_turn_config().expect("standard turn config");
            let session = slot().as_mut().expect("session");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
            for _ in 0..steps {
                let session = slot().as_mut().expect("session");
                session.step_end_turn().expect("end turn");
            }
        };
        let energy = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| {
                c.resources()
                    .iter()
                    .find(|p| p.key.as_str() == "standard.energy")
                    .map_or(-1, |p| p.pool.current)
            })
        };
        let hand = || -> usize {
            let session = slot().as_ref().expect("session");
            session.state.zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand).count()
        };

        // ---- 基线：第 1 回合 3 能量 / 5 张手牌。
        session_for(None, 0);
        assert_eq!(energy(), 3, "baseline energy");
        assert_eq!(hand(), 5, "baseline hand");
        take_session();

        // ---- Ring of the Snake：**第 1 回合**多 2 张（7 张），第 2 回合回到 5。
        session_for(Some("standard.ring_of_the_snake"), 0);
        assert_eq!(hand(), 7, "Ring of the Snake: 5 + 2 on turn 1");
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert_eq!(hand(), 5, "Ring of the Snake: back to 5 from turn 2");
        take_session();

        // ---- Ring of the Serpent：**每回合**多 1 张（6 张），第 2 回合仍是 6。
        session_for(Some("standard.ring_of_the_serpent"), 0);
        assert_eq!(hand(), 6, "Ring of the Serpent: 5 + 1 on turn 1");
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert_eq!(hand(), 6, "Ring of the Serpent: still 6 on turn 2");
        take_session();

        // ---- Philosopher's Stone：每回合 4 能量。
        session_for(Some("standard.philosophers_stone"), 0);
        assert_eq!(energy(), 4, "Philosopher's Stone: 3 + 1");
        take_session();

        // ---- Happy Flower：**每 3 回合**才给 1 点（第 1、2 回合不给，第 3 回合给）。
        session_for(Some("standard.happy_flower"), 0);
        assert_eq!(energy(), 3, "Happy Flower: nothing on turn 1");
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert_eq!(energy(), 3, "Happy Flower: nothing on turn 2");
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert_eq!(energy(), 4, "Happy Flower: the 3rd turn pays");
        take_session();

        // ---- Art of War：这回合不出攻击牌 ⇒ 下回合 +1 能量。
        //
        // 牌组全是 `defend`（技能），所以"没出攻击"成立。
        session_for(Some("standard.art_of_war"), 0);
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert_eq!(energy(), 4, "Art of War: no Attack last turn ⇒ 3 + 1");
        take_session();
    }

    /// §267：零基建批次的**开战载体**（挂对了，且只挂一次）。
    #[test]
    fn the_combat_start_carriers_land_the_right_status() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: Option<(&str, i32)>, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "defend", count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(seed, "enc_cultist", 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier:?}: {e}"));
            install_session(session);
            if let Some((carrier, stacks)) = carrier {
                let session = slot().as_mut().expect("session");
                let item = rd_core::state::EffectItem {
                    request: rd_core::state::EffectRequest::ApplyStatus {
                        target: Some(cid_in("hero")),
                        definition: rd_core::state::StatusDefinitionId::new(carrier)
                            .expect("a status id"),
                        stacks,
                        duration: 0,
                        charges: 0,
                        source: None,
                        source_card: None,
                    },
                    chain: rd_core::state::ChainSlot::NONE,
                    owner: None,
                };
                rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                    .expect("apply the carrier");
            }
            let standard = standard_turn_config().expect("standard turn config");
            let session = slot().as_mut().expect("session");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
        };
        let hero_stacks = |status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(0, |c| {
                c.statuses()
                    .iter()
                    .filter(|s| s.definition_id.as_str() == status_id)
                    .map(|s| s.stacks)
                    .sum()
            })
        };
        let enemy_stacks = |status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .filter(|c| c.team_id.as_str() == "enemy")
                .map(|c| {
                    c.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == status_id)
                        .map(|s| s.stacks)
                        .sum::<i32>()
                })
                .sum()
        };

        // ---- Clockwork Souvenir：开战 1 层 Artifact。
        session_for(Some(("standard.artifact", 1)), 211);
        assert_eq!(hero_stacks("standard.artifact"), 1, "Clockwork Souvenir: 1 Artifact");
        take_session();

        // ---- `red_mask` / `gremlin_visage` 的**落点**由 `combat_bonus` 决定（敌人表 /
        // 英雄表），而那是运行层的事 ⇒ 它们的判据在 rd-run 的接线测试里（`enemy_status_count`
        // vs `status_count`）。这条 wasm 判据只测"落下去之后有没有用"，所以这里不重复。

        // ---- Fossilized Helix：开战 1 层 Buffer（挡住第一次掉血）。
        session_for(Some(("standard.buffer", 1)), 214);
        assert_eq!(hero_stacks("standard.buffer"), 1, "Fossilized Helix: 1 Buffer");
        let hp_before = {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| c.health_current)
        };
        {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("hero")),
                    amount: 9,
                    ignores_block: false,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
        }
        let hp_after = {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| c.health_current)
        };
        assert_eq!(hp_before - hp_after, 0, "Fossilized Helix: the first HP loss is prevented");
        assert_eq!(hero_stacks("standard.buffer"), 0, "…and the Buffer is spent");
        take_session();

        // ---- Mutagenic Strength：开战 3 力量，**第一回合末**失去 3。
        //
        // 这条判据必须跑**一个真回合**（不是手工驱动触发器）："第一回合末"是 `TurnEnded` 的
        // 计数器口径，而计数器的第一跳只有真的结束过一回合才会发生。
        session_for(Some(("standard.mutagenic_strength", 1)), 215);
        assert_eq!(hero_stacks("standard.mutagenic_strength"), 1, "the carrier is on");
        // 载体本身给 3 力量是**开局**的事，这里手工补上（与遗物的 `combat_bonus` 等价）。
        {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new("standard.strength")
                        .expect("strength"),
                    stacks: 3,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("3 strength");
        }
        assert_eq!(hero_stacks("standard.strength"), 3, "3 Strength at combat start");
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn 1");
        }
        assert_eq!(
            hero_stacks("standard.strength"),
            0,
            "Mutagenic Strength: the 3 Strength is gone at the end of turn 1"
        );
        take_session();
    }

    /// §266：条件修饰器（`red_skull`）+ 同侧改写（`odd_mushroom`）。
    #[test]
    fn the_conditional_and_self_scoped_modifiers_change_the_right_number() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: Option<&str>, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "strike", count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(seed, "enc_cultist", 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier:?}: {e}"));
            install_session(session);
            if let Some(carrier) = carrier {
                let session = slot().as_mut().expect("session");
                let item = rd_core::state::EffectItem {
                    request: rd_core::state::EffectRequest::ApplyStatus {
                        target: Some(cid_in("hero")),
                        definition: rd_core::state::StatusDefinitionId::new(carrier)
                            .expect("a status id"),
                        stacks: 1,
                        duration: 0,
                        charges: 0,
                        source: None,
                        source_card: None,
                    },
                    chain: rd_core::state::ChainSlot::NONE,
                    owner: None,
                };
                rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                    .expect("apply the carrier");
            }
            let standard = standard_turn_config().expect("standard turn config");
            let session = slot().as_mut().expect("session");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
        };
        let enemy = || -> String {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| String::from(c.id.as_str()))
                .expect("an enemy")
        };
        let enemy_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map_or(-1, |c| c.health_current)
        };
        let hero_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| c.health_current)
        };
        let set_hero_hp = |value: i32| {
            let session = slot().as_mut().expect("session");
            let hero = cid_in("hero");
            let combatant = session.state.combatant_mut(&hero).expect("hero");
            combatant.health_current = value;
        };
        let apply_to_hero = |status_id: &str, stacks: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(status_id)
                        .expect("a status id"),
                    stacks,
                    duration: 0,
                    charges: 0,
                    source: Some(cid_in("hero")),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        // 英雄打敌人 `amount` 点（走伤害管线，`source_card: None` ⇒ 只有无条件修饰器生效）。
        let hero_hits = |amount: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in(&enemy())),
                    amount,
                    ignores_block: false,
                    source: Some(cid_in("hero")),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        // 敌人打英雄 `amount` 点。
        let enemy_hits = |amount: i32| {
            let session = slot().as_mut().expect("session");
            let attacker = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("hero")),
                    amount,
                    ignores_block: false,
                    source: Some(attacker),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };

        // ---- Red Skull：HP 满时**不给**力量（条件为假）。
        session_for(Some("standard.red_skull"), 101);
        let before = enemy_hp();
        hero_hits(10);
        assert_eq!(
            before - enemy_hp(),
            10,
            "Red Skull: at full HP the 3 Strength does not apply"
        );
        // 掉到 50% 以下（max 200 ⇒ 90 是 45%）⇒ +3。
        set_hero_hp(90);
        let before = enemy_hp();
        hero_hits(10);
        assert_eq!(
            before - enemy_hp(),
            13,
            "Red Skull: at or below 50% HP the Strength applies"
        );
        // 边界：正好 50%（100/200）也算 —— wiki 说的是 "at or below"。
        set_hero_hp(100);
        let before = enemy_hp();
        hero_hits(10);
        assert_eq!(before - enemy_hp(), 13, "Red Skull: exactly 50% still counts");
        take_session();

        // ---- Odd Mushroom：自己有易伤时吃 125%（10 ⇒ 12），基线是 150%（10 ⇒ 15）。
        session_for(None, 102);
        apply_to_hero("standard.vulnerable", 1);
        let before = hero_hp();
        enemy_hits(10);
        assert_eq!(before - hero_hp(), 15, "baseline: Vulnerable = 150%");
        take_session();

        session_for(Some("standard.odd_mushroom"), 103);
        apply_to_hero("standard.vulnerable", 1);
        let before = hero_hp();
        enemy_hits(10);
        assert_eq!(
            before - hero_hp(),
            12,
            "Odd Mushroom: your own Vulnerable multiplies by 125%, not 150%"
        );
        take_session();

        // ---- 不越界：`odd_mushroom` 是 `Self`，所以**敌人**的易伤仍是 150%。
        session_for(Some("standard.odd_mushroom"), 104);
        {
            let session = slot().as_mut().expect("session");
            let target = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(target),
                    definition: rd_core::state::StatusDefinitionId::new("standard.vulnerable")
                        .expect("vulnerable"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: Some(cid_in("hero")),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("vulnerable on the enemy");
        }
        let before = enemy_hp();
        hero_hits(10);
        assert_eq!(
            before - enemy_hp(),
            15,
            "Odd Mushroom is `Self`: the enemy's Vulnerable is still 150%"
        );
        take_session();
    }

    /// §265：`StatusStacks` / `StatusImmunity` 两条管线 + 四件遗物。
    #[test]
    fn the_status_application_relics_change_what_lands_on_the_target() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: Option<&str>, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "strike", count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(seed, "enc_cultist", 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier:?}: {e}"));
            install_session(session);
            if let Some(carrier) = carrier {
                let session = slot().as_mut().expect("session");
                let item = rd_core::state::EffectItem {
                    request: rd_core::state::EffectRequest::ApplyStatus {
                        target: Some(cid_in("hero")),
                        definition: rd_core::state::StatusDefinitionId::new(carrier)
                            .expect("a status id"),
                        stacks: 1,
                        duration: 0,
                        charges: 0,
                        source: None,
                        source_card: None,
                    },
                    chain: rd_core::state::ChainSlot::NONE,
                    owner: None,
                };
                rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                    .expect("apply the carrier");
            }
            let standard = standard_turn_config().expect("standard turn config");
            let session = slot().as_mut().expect("session");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
        };
        let enemy = || -> String {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| String::from(c.id.as_str()))
                .expect("an enemy")
        };
        let stacks_of = |who: &str, status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in(who)).map_or(0, |c| {
                c.statuses()
                    .iter()
                    .filter(|s| s.definition_id.as_str() == status_id)
                    .map(|s| s.stacks)
                    .sum()
            })
        };
        // 由**英雄**施加（"你施加"里的"你"）。
        let apply_from_hero = |who: &str, status_id: &str, stacks: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in(who)),
                    definition: rd_core::state::StatusDefinitionId::new(status_id)
                        .expect("a status id"),
                    stacks,
                    duration: 0,
                    charges: 0,
                    source: Some(cid_in("hero")),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };

        // ---- 基线：没有遗物时，1 层就是 1 层。
        session_for(None, 91);
        let target = enemy();
        apply_from_hero(&target, "standard.poison", 1);
        assert_eq!(stacks_of(&target, "standard.poison"), 1, "baseline: 1 Poison stays 1");

        // ---- Snecko Skull：你施加的中毒多 1 层。
        session_for(Some("standard.snecko_skull"), 92);
        let target = enemy();
        apply_from_hero(&target, "standard.poison", 1);
        assert_eq!(
            stacks_of(&target, "standard.poison"),
            2,
            "Snecko Skull: 1 Poison becomes 2"
        );
        // 反面：只对**中毒**。虚弱照旧 1 层（`AppliesToStatusId` 是过滤器）。
        apply_from_hero(&target, "standard.weak", 1);
        assert_eq!(
            stacks_of(&target, "standard.weak"),
            1,
            "Snecko Skull: Weak is untouched (the parameter filters by status)"
        );
        take_session();

        // ---- Ginger：**你自己**撒不上虚弱（免疫挂在承受者身上 ⇒ 这里打的是英雄）。
        session_for(Some("standard.ginger"), 93);
        apply_from_hero("hero", "standard.weak", 1);
        assert_eq!(stacks_of("hero", "standard.weak"), 0, "Ginger: Weak is refused");
        apply_from_hero("hero", "standard.frail", 1);
        assert_eq!(stacks_of("hero", "standard.frail"), 1, "Ginger: Frail still lands");
        take_session();

        // ---- Turnip：脆弱撒不上，虚弱照旧。
        session_for(Some("standard.turnip"), 94);
        apply_from_hero("hero", "standard.frail", 1);
        assert_eq!(stacks_of("hero", "standard.frail"), 0, "Turnip: Frail is refused");
        apply_from_hero("hero", "standard.weak", 1);
        assert_eq!(stacks_of("hero", "standard.weak"), 1, "Turnip: Weak still lands");
        take_session();

        // ---- Twisted Funnel：开战时所有敌人 4 层中毒（走 `StartCombatStatusOnEnemies`）。
        {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "strike", count: 1 }; 20].into_boxed_slice(),
            );
            // 直接走运行层：把遗物塞进 run，再走 `combat_bonus()` 的敌人表。
            let mut run = rd_run::state::RunState::new(11, 80, i32::MAX, &["strike"; 10])
                .expect("a run");
            run.push_relic("twisted_funnel").expect("twisted_funnel");
            let bonus = run.combat_bonus();
            assert_eq!(bonus.enemy_status_count, 1, "one enemy status");
            let entry = bonus.enemy_statuses[0].expect("an entry");
            assert_eq!(entry.id, "standard.poison", "Twisted Funnel applies Poison");
            assert_eq!(entry.stacks, 4, "…4 stacks");
        }
    }

    /// §264：三条基建（`AppliesToStatusId` / `RestrictSourceCardTag` / `event.statusIs`）+ 三件遗物。
    #[test]
    fn the_status_parameter_infrastructure_changes_the_right_number() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: Option<&str>, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "strike", count: 1 }; 20].into_boxed_slice(),
            );
            let mut session =
                build_session_at_unstarted(seed, "enc_cultist", 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier:?}: {e}"));
            install_session(session);
            if let Some(carrier) = carrier {
                let session = slot().as_mut().expect("session");
                let item = rd_core::state::EffectItem {
                    request: rd_core::state::EffectRequest::ApplyStatus {
                        target: Some(cid_in("hero")),
                        definition: rd_core::state::StatusDefinitionId::new(carrier)
                            .expect("a status id"),
                        stacks: 1,
                        duration: 0,
                        charges: 0,
                        source: None,
                        source_card: None,
                    },
                    chain: rd_core::state::ChainSlot::NONE,
                    owner: None,
                };
                rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                    .expect("apply the carrier");
            }
            let standard = standard_turn_config().expect("standard turn config");
            let session = slot().as_mut().expect("session");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .unwrap_or_else(|e| panic!("start({carrier:?}): {e:?} / {:?}", session.host.last_failure()));
            session.reobserve();
        };
        let first_enemy = || -> String {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| String::from(c.id.as_str()))
                .expect("an enemy")
        };
        let enemy_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map_or(-1, |c| c.health_current)
        };
        let hero_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| c.health_current)
        };
        let stacks_of = |who: &str, status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in(who)).map_or(0, |c| {
                c.statuses()
                    .iter()
                    .filter(|s| s.definition_id.as_str() == status_id)
                    .map(|s| s.stacks)
                    .sum()
            })
        };
        let apply = |who: &str, status_id: &str, stacks: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in(who)),
                    definition: rd_core::state::StatusDefinitionId::new(status_id)
                        .expect("a status id"),
                    stacks,
                    duration: 0,
                    charges: 0,
                    source: Some(cid_in("hero")),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        let hit = |who: &str, amount: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in(who)),
                    amount,
                    ignores_block: false,
                    source: Some(cid_in("hero")),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };

        // ---- 基线：敌人有易伤时 10 点伤害吃 15 点（150%）。基准错了后面全是误报。
        session_for(None, 81);
        let target = first_enemy();
        apply(&target, "standard.vulnerable", 1);
        let before = enemy_hp();
        hit(&target, 10);
        assert_eq!(before - enemy_hp(), 15, "baseline: Vulnerable = 150%");

        // ---- Paper Phrog：同样 10 点吃 17 点（175%）。
        session_for(Some("standard.paper_phrog"), 82);
        let target = first_enemy();
        apply(&target, "standard.vulnerable", 1);
        let before = enemy_hp();
        hit(&target, 10);
        assert_eq!(before - enemy_hp(), 17, "Paper Phrog: Vulnerable = 175%");
        take_session();

        // ---- Paper Krane：敌人有虚弱时打 10 点只吃 6 点（60%，基线 75%）。
        // 虚弱挂在**出手方**（敌人），所以这里让敌人打英雄。
        session_for(None, 83);
        {
            let session = slot().as_mut().expect("session");
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(enemy),
                    definition: rd_core::state::StatusDefinitionId::new("standard.weak")
                        .expect("weak"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: Some(cid_in("hero")),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("weaken the enemy");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        let before = hero_hp();
        {
            // 敌人打英雄 10 点：出手方是敌人。
            let session = slot().as_mut().expect("session");
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("hero")),
                    amount: 10,
                    ignores_block: false,
                    source: Some(enemy),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        assert_eq!(before - hero_hp(), 7, "baseline: Weak = 75% (10 -> 7)");
        take_session();

        session_for(Some("standard.paper_krane"), 84);
        {
            let session = slot().as_mut().expect("session");
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(enemy),
                    definition: rd_core::state::StatusDefinitionId::new("standard.weak")
                        .expect("weak"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: Some(cid_in("hero")),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("weaken the enemy");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        let before = hero_hp();
        {
            let session = slot().as_mut().expect("session");
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("hero")),
                    amount: 10,
                    ignores_block: false,
                    source: Some(enemy),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        // 60% of 10 = 6。
        assert_eq!(before - hero_hp(), 6, "Paper Krane: Weak = 60% (10 -> 6)");
        take_session();

        // ---- Champion Belt：施加易伤 ⇒ 那一方多 1 层虚弱；施加**别的** debuff ⇒ 不附带。
        session_for(Some("standard.champion_belt"), 85);
        let target = first_enemy();
        apply(&target, "standard.vulnerable", 1);
        assert_eq!(
            stacks_of(&target, "standard.weak"),
            1,
            "Champion Belt: applying Vulnerable also applies 1 Weak"
        );
        take_session();

        session_for(Some("standard.champion_belt"), 86);
        let target = first_enemy();
        // 施加**脆弱**（另一个 debuff）：不该附带虚弱。
        apply(&target, "standard.frail", 1);
        assert_eq!(
            stacks_of(&target, "standard.weak"),
            0,
            "Champion Belt: only Vulnerable triggers it (frail must not)"
        );
        take_session();

        // ---- RestrictSourceCardTag：Pen Nib 的翻倍**只对攻击牌**。
        //
        // 直接给英雄上 `standard.double_damage`，然后造一次"**没有来源卡**"的直接伤害：
        // §262 时它会被翻倍（那条偏差）；§264 起不翻 —— 因为 spec 要求来源卡带 `attack`。
        session_for(None, 87);
        {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new("standard.double_damage")
                        .expect("double damage"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("arm the doubling");
        }
        let target = first_enemy();
        let before = enemy_hp();
        hit(&target, 5);
        assert_eq!(
            before - enemy_hp(),
            5,
            "RestrictSourceCardTag: damage with no source card is NOT doubled"
        );
        take_session();
    }

    /// §263：**敌人死亡**两件 + **伤害管线数值改写**三件。
    ///
    /// 一条测试覆盖五件，因为它们的公共前提是同一个："造一场能被我方精确控制伤害的战斗"。
    #[test]
    fn the_enemy_death_and_damage_rewrite_relics_change_the_right_number() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        // 两个敌人的战斗：打死一个，看另一个/英雄侧的反应。
        let session_for = |carrier: &str, card: &'static str, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card, count: 1 }; 20].into_boxed_slice(),
            );
            // §263 的死亡类规则需要**两个敌人**（"敌人死了"要有另一个在场）。
            let session = build_session_at_unstarted(seed, "enc_two_louses", 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(carrier)
                        .expect("a status id"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply the carrier");
            let standard = standard_turn_config().expect("standard turn config");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
        };
        let enemies = || -> Vec<(String, i32)> {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .filter(|c| c.team_id.as_str() == "enemy")
                .map(|c| (String::from(c.id.as_str()), c.health_current))
                .collect()
        };
        let energy = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| {
                    c.resources()
                        .iter()
                        .find(|p| p.key.as_str() == "standard.energy")
                        .map_or(-1, |p| p.pool.current)
                })
        };
        let hand_count = || -> usize {
            let session = slot().as_ref().expect("session");
            session.state.zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand).count()
        };
        let poison_of = |id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in(id)).map_or(0, |c| {
                c.statuses()
                    .iter()
                    .filter(|s| s.definition_id.as_str() == "standard.poison")
                    .map(|s| s.stacks)
                    .sum()
            })
        };
        let hero_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| c.health_current)
        };
        // 直接对某个战斗员打一拳（绕过出牌：伤害额精确可控）。
        let hit = |who: &str, amount: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in(who)),
                    amount,
                    ignores_block: false,
                    // §263：出手方 = 英雄。**The Boot 是出手侧规则**，`source: None` 时
                    // 它读不到"谁在打"，整条规则静默不生效 —— 判据会报"4 点还是 4 点"。
                    source: Some(cid_in("hero")),
                    // §264：测试里没有来源卡（那是 `RestrictSourceCardTag` 的门要的东西）。
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };

        // ---- Gremlin Horn：敌人死亡 ⇒ +1 能量、抽 1 张。
        session_for("standard.gremlin_horn", "strike", 71);
        let names = enemies();
        assert!(names.len() >= 2, "this fixture needs two enemies, got {names:?}");
        let target = names[0].0.clone();
        let energy_before = energy();
        let hand_before = hand_count();
        hit(&target, 999);
        assert_eq!(enemies()[0].1, 0, "the louse is down");
        assert_eq!(energy(), energy_before + 1, "Gremlin Horn: +1 Energy on a kill");
        assert_eq!(hand_count(), hand_before + 1, "Gremlin Horn: draw 1 on a kill");
        take_session();

        // ---- The Specimen：死者身上的毒搬给**另一个**敌人（不是英雄、不是死者自己）。
        session_for("standard.the_specimen", "strike", 72);
        {
            let session = slot().as_mut().expect("session");
            let first = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(first),
                    definition: rd_core::state::StatusDefinitionId::new("standard.poison")
                        .expect("poison"),
                    stacks: 4,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("poison the first louse");
        }
        let names = enemies();
        let dying = names[0].0.clone();
        let survivor = names[1].0.clone();
        hit(&dying, 999);
        // ⚠️ 尸体上的层数**不会**被清掉（内核不清理倒下者的状态，也没有理由清）——
        // 要钉的是"搬过去了"，不是"搬空了"。
        assert_eq!(poison_of(&survivor), 4, "The Specimen: the Poison moves to the other enemy");
        assert_eq!(poison_of("hero"), 0, "…and not to the hero");
        take_session();

        // ---- The Boot：4 点未被格挡的攻击伤害 ⇒ 5。
        session_for("standard.the_boot", "strike", 73);
        let names = enemies();
        let who = names[0].0.clone();
        let before = names[0].1;
        hit(&who, 4);
        let after = enemies()[0].1;
        assert_eq!(before - after, 5, "The Boot: 4 unblocked damage becomes 5");
        take_session();

        // 反面：5 点不在阈值内，原样。
        session_for("standard.the_boot", "strike", 74);
        let names = enemies();
        let who = names[0].0.clone();
        let before = names[0].1;
        hit(&who, 5);
        assert_eq!(before - enemies()[0].1, 5, "The Boot: 5 is already above the threshold");
        take_session();

        // ---- Torii：5 点未被格挡的攻击伤害 ⇒ 1（承受侧，所以打的是英雄）。
        session_for("standard.torii", "strike", 75);
        let before = hero_hp();
        hit("hero", 5);
        assert_eq!(before - hero_hp(), 1, "Torii: 5 unblocked damage becomes 1");
        take_session();

        // 反面：6 点不在阈值内，原样。
        session_for("standard.torii", "strike", 76);
        let before = hero_hp();
        hit("hero", 6);
        assert_eq!(before - hero_hp(), 6, "Torii: 6 is above the threshold");
        take_session();

        // ---- Tungsten Rod：每次掉血少掉 1 点（**任何**来源：这里走"失去生命"那条路 ——
        // `bloodletting` 是 0 费、-3 HP，牌组的 20 张全是它，所以开局手里一定有）。
        session_for("standard.tungsten_rod", "bloodletting", 77);
        let before = hero_hp();
        {
            let session = slot().as_mut().expect("session");
            let hero = cid_in("hero");
            let instance = session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::Hand)
                .next()
                .map(|card| card.id)
                .expect("bloodletting in hand");
            rd_core::play::play_card(
                &mut session.state,
                Some(&content),
                &rd_core::play::PlayRequest::new(hero, instance, None),
            )
            .expect("bloodletting is playable");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        assert_eq!(before - hero_hp(), 2, "Tungsten Rod: 3 HP loss becomes 2");
        take_session();

        // 伤害那条路也一样（被格挡吃干净的那一下**不该**再减 —— 它本来就没掉血）。
        session_for("standard.tungsten_rod", "strike", 78);
        let before = hero_hp();
        hit("hero", 5);
        assert_eq!(before - hero_hp(), 4, "Tungsten Rod: 5 damage becomes 4");
        take_session();
    }

    /// §262：七件"每第 N 张某类型牌"的遗物 —— 真的打牌。
    ///
    /// 一条测试覆盖七件，因为它们的规则形状是**同一个**（`CardPlayed` + 自己的模 N 计数器），
    /// 而每条的内部判据不同：三条挂在"第 3 张攻击"上，一条挂"第 3 张技能"（tag 门的反面），
    /// 两条挂"第 10 张"，Pen Nib 还多一条"翻倍只持续一次"。
    #[test]
    fn the_every_nth_card_relics_count_the_right_kind_of_card() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        // 一场战斗：牌组全 `strike`（攻击，6 伤害）或全 `defend`（技能），对手取 Gremlin Nob
        // （82 HP ⇒ 挨得住 10 次攻击，不会中途被打死而改变后面的判据）。
        let session_for = |card: &'static str, carrier: &str, seed: i32, enemy: &str| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card, count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(seed, enemy, 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(carrier)
                        .expect("a status id"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply the carrier");
            let standard = standard_turn_config().expect("standard turn config");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
        };

        // 打一张手牌（按 tag 挑），然后**排空队列** —— 触发器就在排空时跑。
        // `zone_cards` 给的是**牌实例**（不是槽位），而 `PlayRequest` 要的是实例 id。
        let play_one = |tag: &str| {
            let session = slot().as_mut().expect("session");
            let hero = cid_in("hero");
            // ⚠️ **必须给目标**：`PlayRequest` 的 target 为 `None` 时，`strike` 的
            // `dealDamage(sel.target)` 解析不出人 ⇒ 一点伤害都不发生，而且**不报错**。
            // 判据只看"格挡/状态/手牌"的话，这个坑完全看不出来（§262：Pen Nib 的伤害判据抓到它）。
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let instance = session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::Hand)
                .find(|card| content.card_has_tag(card.definition_id.as_str(), tag) == Some(true))
                .map(|card| card.id)
                .unwrap_or_else(|| panic!("no `{tag}` card in hand"));
            rd_core::play::play_card(
                &mut session.state,
                Some(&content),
                &rd_core::play::PlayRequest::new(hero, instance, Some(enemy)),
            )
            .expect("play the card");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state)
                .unwrap_or_else(|e| {
                    panic!("drain after `{tag}`: {e:?} / last={:?}", host.last_failure())
                });
        };
        // 手牌空了就补 —— 判据关心的是"打了几张"，不是"一回合能不能打这么多"。
        let top_up = || {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DrawCards {
                    owner: cid_in("hero"),
                    count: 10,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("draw");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::GainResource {
                    target: Some(cid_in("hero")),
                    key: rd_core::state::ResourceId::new("standard.energy").expect("energy"),
                    amount: 50,
                    default_max: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("energy");
        };
        let hand_count = || -> usize {
            let session = slot().as_ref().expect("session");
            session.state.zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand).count()
        };
        let status_stacks = |status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(0, |c| {
                    c.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == status_id)
                        .map(|s| s.stacks)
                        .sum()
                })
        };
        let block = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| {
                c.defensive_pools()
                    .iter()
                    .find(|pool| pool.key.as_str() == "standard.block")
                    .map_or(0, |pool| pool.pool.current)
            })
        };
        let enemy_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map_or(-1, |c| c.health_current)
        };
        let hero_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| c.health_current)
        };

        // ---- Kunai：第 3 张攻击才 +1 敏捷（第 2 张不给）。
        session_for("strike", "standard.kunai", 61, "enc_gremlin_nob");
        top_up();
        play_one("attack");
        assert_eq!(status_stacks("standard.dexterity"), 0, "Kunai: after 1 attack");
        play_one("attack");
        assert_eq!(status_stacks("standard.dexterity"), 0, "Kunai: after 2 attacks");
        play_one("attack");
        assert_eq!(status_stacks("standard.dexterity"), 1, "Kunai: every 3rd attack");
        play_one("attack");
        assert_eq!(status_stacks("standard.dexterity"), 1, "Kunai: the 4th gives nothing");
        take_session();

        // ---- Shuriken：同上，但给力量。**技能的 3 张不算**（tag 门的反面）。
        session_for("defend", "standard.shuriken", 62, "enc_gremlin_nob");
        top_up();
        for n in 1..=3 {
            play_one("skill");
            assert_eq!(
                status_stacks("standard.strength"),
                0,
                "Shuriken: 3 skills still give nothing (it counts Attacks, #{n})"
            );
        }
        take_session();

        // ---- Ornamental Fan：第 3 张攻击 +4 格挡。
        session_for("strike", "standard.ornamental_fan", 63, "enc_gremlin_nob");
        top_up();
        let before = block();
        play_one("attack");
        play_one("attack");
        // 攻击牌自己能给格挡吗？`strike` 不能，所以这里的差值只可能来自遗物。
        assert_eq!(block(), before, "Ornamental Fan: no Block before the 3rd attack");
        play_one("attack");
        assert_eq!(block(), before + 4, "Ornamental Fan: 3rd attack ⇒ +4 Block");
        take_session();

        // ---- Letter Opener：第 3 张**技能**对所有敌人 5 伤害。
        session_for("defend", "standard.letter_opener", 64, "enc_gremlin_nob");
        top_up();
        let before = enemy_hp();
        play_one("skill");
        play_one("skill");
        assert_eq!(enemy_hp(), before, "Letter Opener: nothing before the 3rd Skill");
        play_one("skill");
        assert_eq!(enemy_hp(), before - 5, "Letter Opener: 3rd Skill ⇒ 5 damage to ALL");
        take_session();

        // ---- Nunchaku：第 10 张攻击 +1 能量。
        session_for("strike", "standard.nunchaku", 65, "enc_gremlin_nob");
        top_up();
        for _ in 1..=9 {
            play_one("attack");
        }
        let energy_before = {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| {
                    c.resources()
                        .iter()
                        .find(|p| p.key.as_str() == "standard.energy")
                        .map_or(-1, |p| p.pool.current)
                })
        };
        // 第 10 张：`strike` 花 1 点，遗物给 1 点 ⇒ 净 0。
        play_one("attack");
        let energy_after = {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| {
                    c.resources()
                        .iter()
                        .find(|p| p.key.as_str() == "standard.energy")
                        .map_or(-1, |p| p.pool.current)
                })
        };
        assert_eq!(
            energy_after, energy_before,
            "Nunchaku: the 10th attack's +1 Energy cancels its own 1-cost"
        );
        take_session();

        // ---- Ink Bottle：第 10 张**任何**牌抽 1 张（这里用技能牌，证明它不看类型）。
        session_for("defend", "standard.ink_bottle", 66, "enc_gremlin_nob");
        top_up();
        for _ in 1..=9 {
            play_one("skill");
        }
        let before = hand_count();
        play_one("skill");
        // 打掉 1 张、抽回 1 张 ⇒ 手牌数**不变**（前 9 张每次都少 1）。
        assert_eq!(hand_count(), before, "Ink Bottle: the 10th card draws 1 back");
        take_session();

        // ---- Pen Nib：第 10 张攻击**双倍伤害**，第 11 张回到单倍。
        session_for("strike", "standard.pen_nib", 67, "enc_gremlin_nob");
        top_up();
        for _ in 1..=9 {
            play_one("attack");
        }
        assert_eq!(
            status_stacks("standard.double_damage"),
            1,
            "Pen Nib: the doubling is armed after the 9th attack"
        );
        // ⚠️ §264：翻倍的 spec 现在带 `RestrictSourceCardTag: attack`，所以它**只对带来源卡的
        // 攻击**生效 —— 用"投一条 DealDamage 请求"来测会得到 6（没有来源卡 ⇒ 不翻）。
        // 这里改成真的打一张攻击牌（`strike` 6 点）。
        let before = enemy_hp();
        play_one("attack");
        assert_eq!(
            before - enemy_hp(),
            12,
            "Pen Nib: the 10th attack deals 12, not 6"
        );
        assert_eq!(
            status_stacks("standard.double_damage"),
            0,
            "Pen Nib: the doubling is spent by that same attack"
        );
        let before = enemy_hp();
        play_one("attack");
        assert_eq!(
            before - enemy_hp(),
            6,
            "Pen Nib: the 11th attack is back to single damage"
        );
        let _ = hero_hp();
        take_session();
    }

    /// §261：**满能量时"加能量"必须真的加**（参考的 `CanExceedMax`）。
    ///
    /// 这条钉的是一个**在这次改动之前就存在**的缺口：能量池曾经硬写 `max = 3`，而
    /// `gainResource` 会夹到上限（`ResourceEffects.cs:215`），于是六张加能量的牌
    /// （`bloodletting` / `offering` / `seeing_red` / `dropkick` / `sentinel` / `miracle`）
    /// 在满能量时**静默无效**。
    ///
    /// ⚠️ 为什么一直没红：rd-core 的 `arena()` 夹具从能量 **0** 起跑（那句注释还写着
    /// "0 费牌不需要预置"）—— 夹上限需要一个**满池**的起点才看得见。夹具的起点掩盖了一条规则，
    /// 这是它最贵的形状。
    ///
    /// 这里直接走 `resolve_effect(GainResource)`：它就是 `node.gainResource` 的实体
    /// （`exec.rs::gain_one_resource`），而"夹不夹"正是那个函数的唯一判据。
    #[test]
    fn gaining_energy_on_a_full_pool_actually_gains() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        install_session(build_session_at(51, "enc_cultist", 200, None, 0, 0).expect("a fight"));
        let energy = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| {
                    c.resources()
                        .iter()
                        .find(|pool| pool.key.as_str() == "standard.energy")
                        .map_or(-1, |pool| pool.pool.current)
                })
        };
        assert_eq!(energy(), 3, "turn 1 starts full");
        let session = slot().as_mut().expect("session");
        let item = rd_core::state::EffectItem {
            request: rd_core::state::EffectRequest::GainResource {
                target: Some(cid_in("hero")),
                key: rd_core::state::ResourceId::new("standard.energy").expect("energy"),
                amount: 2,
                default_max: None,
            },
            chain: rd_core::state::ChainSlot::NONE,
            owner: None,
        };
        rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
            .expect("gain 2");
        assert_eq!(energy(), 5, "gain 2 on a full pool ⇒ 5, not clamped back to 3");
        // 反面：回合开始把它**收回** 3（"nothing carries over"），所以上一个断言不是靠"没有上限"
        // 侥幸成立的 —— 余额真的会在回合边界消失。
        let session = slot().as_mut().expect("session");
        session.step_end_turn().expect("end turn");
        assert_eq!(energy(), 3, "the refill takes it back to 3 next turn");
        take_session();
    }

    /// §261：五件"战斗开始类"遗物 —— **跑真回合**。
    ///
    /// 用 `step_end_turn()`（完整一轮）而不是手工调触发器：`lantern` / `bag_of_preparation`
    /// 的正确性依附于 turn-start 七步的**顺序**；`ice_cream` / `calipers` 是那七步里的两个分支。
    /// 只调触发器的话，`lantern` 会"看起来生效"（能量确实 +1），却测不到它是否在补能量之后。
    #[test]
    fn the_combat_start_relics_change_the_right_step_of_the_turn() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        // 一个辅助：建一场对 Cultist 的战斗，并给英雄挂上某条载体状态（layer = 层数）。
        //
        // ⚠️ **必须用 `build_session_at_unstarted`**：这批遗物里有三条的规则绑在第 1 回合的
        // 具体时点上。用 `build_session_at`（它会立刻把第 1 回合开起来）测的话，状态是**事后**
        // 挂上去的，`lantern` / `bag_of_preparation` 根本不会生效 —— §261 的第一版测试就是这么
        // 红的，而它红的形状（"能量还是 3"）看起来像内核没实现。
        let setup = |status_id: &str, stacks: i32, seed: i32| {
            let session = build_session_at_unstarted(seed, "enc_cultist", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("{status_id}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(status_id)
                        .expect("a status id"),
                    stacks,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply the carrier");
            // 挂好状态、再开第 1 回合 —— 这正是 run 层 `fight_begin` 现在的顺序。
            let standard = standard_turn_config().expect("standard turn config");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
        };
        let energy = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| {
                    c.resources()
                        .iter()
                        .find(|pool| pool.key.as_str() == "standard.energy")
                        .map_or(-1, |pool| pool.pool.current)
                })
        };
        let hand = || -> usize {
            let session = slot().as_ref().expect("session");
            session.state.zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand).count()
        };
        let block = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| {
                c.defensive_pools()
                    .iter()
                    .find(|pool| pool.key.as_str() == "standard.block")
                    .map_or(0, |pool| pool.pool.current)
            })
        };
        let end_turn = || {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        };
        let give_block = |amount: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::GainBlock {
                    target: Some(cid_in("hero")),
                    amount,
                    from_card: false,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("block");
        };

        // ---- 基准：不带遗物时第 1 回合 3 能量 / 5 张手牌。基准错了后面全是误报。
        {
            install_session(
                build_session_at(41, "enc_cultist", 200, None, 0, 0).expect("baseline"),
            );
            assert_eq!(energy(), 3, "baseline: 3 energy on turn 1");
            assert_eq!(hand(), 5, "baseline: 5 cards on turn 1");
            take_session();
        }

        // ---- Lantern：第 1 回合 4 点（3 + 1），第 2 回合回到 3 点。
        setup("standard.lantern", 1, 42);
        assert_eq!(energy(), 4, "Lantern: 3 + 1 on the first turn");
        end_turn();
        // ⚠️ 第 2 回合是 3 —— 而且这一条才是真正的判据：如果 +1 发生在补能量**之前**，
        // 第 1 回合照样是 4，只有"第 2 回合回到 3"和"能量不是 3+1+…"能区分。
        assert_eq!(energy(), 3, "Lantern: back to 3 from turn 2 on");
        take_session();

        // ---- Bag of Preparation：第 1 回合 7 张（5 + 2），第 2 回合回到 5 张。
        setup("standard.bag_of_preparation", 1, 43);
        assert_eq!(hand(), 7, "Bag of Preparation: 5 + 2 on the first turn");
        end_turn();
        assert_eq!(hand(), 5, "Bag of Preparation: back to 5 from turn 2 on");
        take_session();

        // ---- Ice Cream：没用掉的能量跨回合累积。
        setup("standard.ice_cream", 1, 44);
        assert_eq!(energy(), 3, "Ice Cream: still 3 at the start");
        // 花掉 1 点：剩 2。下一回合应当是 2 + 3 = 5（而不是 3）。
        {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::LoseResource {
                    target: Some(cid_in("hero")),
                    key: rd_core::state::ResourceId::new("standard.energy").expect("energy"),
                    amount: 1,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("spend 1");
        }
        assert_eq!(energy(), 2, "Ice Cream: 2 left after spending 1");
        end_turn();
        assert_eq!(energy(), 5, "Ice Cream: 2 carried + 3 refilled");
        take_session();

        // ---- Calipers：回合开始只失去 15 点，而不是全部。
        setup("standard.calipers", 15, 45);
        give_block(40);
        assert_eq!(block(), 40, "Calipers: 40 Block in place");
        end_turn();
        // 回合开始那一刻是 40 —— 防御方（Cultist）的回合里英雄不掉格挡，所以下一回合开始
        // 还是 40 ⇒ 失去 15 ⇒ 25。
        assert_eq!(block(), 25, "Calipers: 40 - 15 = 25, not 0");
        take_session();

        // 少于 15 点 ⇒ 全没（`max(0, live - 15)`）。
        setup("standard.calipers", 15, 46);
        give_block(6);
        end_turn();
        assert_eq!(block(), 0, "Calipers: 6 - 15 clamps to 0");
        take_session();

        // 不带 Calipers ⇒ 全清（默认路径没被这次改动破坏）。
        install_session(build_session_at(47, "enc_cultist", 200, None, 0, 0).expect("plain"));
        give_block(40);
        end_turn();
        assert_eq!(block(), 0, "without Calipers the block is cleared as before");
        take_session();
    }

    /// §260：回合末/回合初那八条状态**真的按回合生效**。
    ///
    /// 每条都两面测（"该给的时候给了"＋"不该给的时候没给"），因为"每回合都给"这种错法
    /// 只测正面是看不出来的。
    #[test]
    fn the_turn_shaped_relic_statuses_fire_on_the_turn_the_wiki_names() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        // 一个辅助：建一场对 Cultist 的战斗，并把某条状态挂到英雄身上。
        let setup = |status_id: &str, seed: i32| {
            let session = build_session_at(seed, "enc_cultist", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("{status_id}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(status_id)
                        .expect("a status id"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply the carrier status");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        // Block 是**一口命名池**（`defensive_pools` 里 key = "block"），不是一个字段 ——
        // 这正是"一个结构体一个用途"的代价，也让这条判据顺带覆盖了读法。
        let hero_block = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| {
                c.defensive_pools()
                    .iter()
                    .find(|pool| pool.key.as_str() == "standard.block")
                    .map_or(0, |pool| pool.pool.current)
            })
        };
        let hero_hand = || -> usize {
            let session = slot().as_ref().expect("session");
            session.state.zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand).count()
        };
        let enemy_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("cultist")).map_or(-1, |c| c.health_current)
        };
        let hero_status = |status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(0, |c| {
                    c.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == status_id)
                        .map(|s| s.stacks)
                        .sum::<i32>()
                })
        };
        let start_turn = || {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            host.try_run_turn_started_triggers(&mut session.state, &cid_in("hero"))
                .expect("turn started");
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        let end_turn = || {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            host.try_run_turn_ended_triggers(&mut session.state, &cid_in("hero"))
                .expect("turn ended");
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        let set_block = |amount: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::GainBlock {
                    target: Some(cid_in("hero")),
                    amount,
                    from_card: false,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("block");
        };

        // ---- Orichalcum：回合末**没有格挡**才给 6。两面。
        setup("standard.orichalcum", 31);
        set_block(5);
        end_turn();
        assert_eq!(hero_block(), 5, "Orichalcum leaves you alone when you already have Block");
        {
            // 把格挡清掉（模拟"这回合没攒格挡"）。
            let session = slot().as_mut().expect("session");
            let hero = cid_in("hero");
            let key = rd_core::state::DefensivePoolId::new("standard.block").expect("block pool");
            let combatant = session.state.combatant_mut(&hero).expect("hero");
            combatant.set_defensive_pool(key, 0, None).expect("clear block");
        }
        end_turn();
        assert_eq!(hero_block(), 6, "no Block at end of turn ⇒ +6");
        take_session();

        // ---- Mercury Hourglass：每次回合初对所有敌人 3 点。
        setup("standard.mercury_hourglass", 32);
        let before = enemy_hp();
        start_turn();
        assert_eq!(enemy_hp(), before - 3, "3 damage to ALL enemies at the start of your turn");
        take_session();

        // ---- Horn Cleat：**第 2 回合**才给 14（第 1 回合不给）。
        setup("standard.horn_cleat", 33);
        start_turn();
        assert_eq!(hero_block(), 0, "turn 1: nothing yet");
        start_turn();
        assert_eq!(hero_block(), 14, "turn 2: +14 Block");
        start_turn();
        assert_eq!(hero_block(), 14, "turn 3: nothing more");
        take_session();

        // ---- Captain's Wheel：**第 3 回合**才给 18。
        setup("standard.captains_wheel", 34);
        start_turn();
        start_turn();
        assert_eq!(hero_block(), 0, "turns 1-2: nothing yet");
        start_turn();
        assert_eq!(hero_block(), 18, "turn 3: +18 Block");
        take_session();

        // ---- Stone Calendar：第 7 回合末才 52 伤害。
        setup("standard.stone_calendar", 35);
        let before = enemy_hp();
        for turn in 1..=6 {
            end_turn();
            assert_eq!(enemy_hp(), before, "turn {turn}: not yet");
        }
        end_turn();
        // ⚠️ 52 点足以把 Cultist 打死 ⇒ 断言写成 `max(0, …)`：血量不下溢是内核的事，
        // 而"这一击打了 52"用**掉血量**证明（见下一行），比 hp 相等更能说明问题。
        assert_eq!(enemy_hp(), (before - 52).max(0), "turn 7: 52 damage to ALL enemies");
        take_session();

        // ---- Cloak Clasp：回合末按**手牌张数**给格挡。
        setup("standard.cloak_clasp", 36);
        let hand = hero_hand();
        assert!(hand > 0, "the hero starts with a hand");
        end_turn();
        assert_eq!(hero_block(), hand as i32, "1 Block per card in hand");
        take_session();

        // ---- Incense Burner：每 6 回合 1 层无形。
        setup("standard.incense_burner", 37);
        for turn in 1..=5 {
            start_turn();
            assert_eq!(hero_status("standard.intangible"), 0, "turn {turn}: not yet");
        }
        start_turn();
        assert_eq!(hero_status("standard.intangible"), 1, "turn 6: 1 Intangible");
        take_session();

        // ---- Pocketwatch：上回合 ≤3 张 ⇒ 这回合初抽 3。
        setup("standard.pocketwatch", 38);
        {
            // 上回合打了 4 张：**不该**抽。
            let session = slot().as_mut().expect("session");
            session.state.cards_played_last_turn = 4;
        }
        let before = hero_hand();
        start_turn();
        assert_eq!(hero_hand(), before, "4 cards last turn ⇒ no extra draw");
        {
            let session = slot().as_mut().expect("session");
            session.state.cards_played_last_turn = 3;
        }
        let before = hero_hand();
        start_turn();
        assert_eq!(hero_hand(), before + 3, "3 or fewer ⇒ draw 3");
        take_session();
    }

    /// §209：Curl Up —— **首次**掉血时按掷骰加格挡，之后自我摘除；被完全格挡的一击**不**消耗它。
    ///
    /// 三段判据：
    /// 1. 掉血的一击 ⇒ 加 N 点格挡（N = 开局掷的 `roll.curl_up`，判据直接读那只计数器，不写死数字）；
    /// 2. 状态**没了** —— 所以第二次挨打不会再给一次（"first time" 是这个机制的全部要点）；
    /// 3. 一次**被格挡吸收**的攻击（掉 0 血）照样**不**触发：`eventAmount > 0` 那道门。
    #[test]
    fn curl_up_pays_out_once_and_only_for_a_hit_that_draws_blood() {
        let session = build_session_at(7, "enc_louse", 200, None, 0, 0).expect("the louse fight");
        install_session(session);
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let louse = cid_in("louse_red");
        let counter = |state: &rd_core::state::CombatState, key: &str| {
            state
                .combatant(&louse)
                .and_then(|c| c.counters().iter().find(|e| e.key.as_str() == key).map(|e| e.value))
                .unwrap_or(0)
        };
        let block = |state: &rd_core::state::CombatState| {
            state
                .combatant(&louse)
                .and_then(|c| {
                    c.defensive_pools()
                        .iter()
                        .find(|p| p.key.as_str() == "standard.block")
                        .map(|p| p.pool.current)
                })
                .unwrap_or(0)
        };
        let has_curl = |state: &rd_core::state::CombatState| {
            state
                .combatant(&louse)
                .map(|c| c.statuses().iter().any(|s| s.definition_id.as_str() == "standard.curl_up"))
                .unwrap_or(false)
        };
        let rolled = {
            let session = slot().as_ref().expect("session");
            counter(&session.state, "roll.curl_up")
        };
        assert!(rolled >= 3, "the louse rolls Curl Up at combat start (got {rolled})");

        // 3 first: a fully blocked hit (no HP lost) must leave the power alone.
        {
            let mut host = rd_core::host::Host::new(&content);
            let session = slot().as_mut().expect("session");
            let mut ctx = rd_core::exec::ExecContext::new(
                &mut session.state,
                Some(cid_in("hero")),
                Some(louse),
                None,
                1024,
            )
            .with_content(&content);
            rd_core::exec::resolve_damage(&mut ctx, &louse, 0, false).expect("a blocked hit");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch");
            assert!(
                has_curl(&session.state),
                "a hit that draws no blood must not spend Curl Up"
            );
            assert_eq!(block(&session.state), 0, "and it grants nothing");
        }

        // 1 + 2: one real hit.
        {
            let mut host = rd_core::host::Host::new(&content);
            let session = slot().as_mut().expect("session");
            let mut ctx = rd_core::exec::ExecContext::new(
                &mut session.state,
                Some(cid_in("hero")),
                Some(louse),
                None,
                1024,
            )
            .with_content(&content);
            rd_core::exec::resolve_damage(&mut ctx, &louse, 1, false).expect("an attack lands");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch");
            assert_eq!(block(&session.state), rolled, "Curl Up grants the rolled block");
            assert!(!has_curl(&session.state), "and it is spent");
        }

        // …and the second hit grants nothing more.
        {
            let mut host = rd_core::host::Host::new(&content);
            let session = slot().as_mut().expect("session");
            let before = block(&session.state);
            let mut ctx = rd_core::exec::ExecContext::new(
                &mut session.state,
                Some(cid_in("hero")),
                Some(louse),
                None,
                1024,
            )
            .with_content(&content);
            rd_core::exec::resolve_damage(&mut ctx, &louse, 1, false).expect("a second attack");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch");
            // The second hit is **absorbed** by the block Curl Up just granted (1 damage), so the
            // number goes down by exactly that; what must not happen is another Curl Up payout
            // (which would add `rolled` on top).
            assert_eq!(
                block(&session.state),
                before - 1,
                "the second hit must not add block again (it already curled up)"
            );
        }
        take_session();
    }

    /// §209：**A19 把 15% 的 Gloat 槽位换成 Defensive Stance**（wiki `The Champ`）。
    ///
    /// 这一条钉的是"招式表按等级换"这条内容能力（`intent.ascensionAtLeast`，§187）：A18 时
    /// Gloat **必须出现过**，A19 时**一次都不许出现**。只测 A19 的话，一个"根本没写 Gloat"的
    /// 内容也会绿 —— 所以两侧都测。
    #[test]
    fn the_champ_swaps_gloat_for_defensive_stance_at_a19() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let row = content
            .lookup_in("enc_the_champ", rd_core::content::EK_ENCOUNTER)
            .expect("enc_the_champ")
            .index;
        let mut seen = Vec::new();
        for ascension in [18u8, 19u8] {
            let mut gloat = 0usize;
            let mut stance = 0usize;
            for seed in 0..80 {
                let session = build_session_at(seed, "enc_the_champ", 200, None, 0, ascension)
                    .unwrap_or_else(|e| panic!("A{ascension} seed {seed}: {e}"));
                install_session(session);
                let choice = {
                    let session = slot().as_ref().expect("session");
                    let at = rd_core::intent::locate_enemy(
                        &content,
                        u32::from(row),
                        &cid_in("the_champ"),
                    )
                    .expect("locate")
                    .expect("the champ is in this encounter");
                    rd_core::intent::select_action(&session.state, &content, at, &cid_in("the_champ"), 1)
                        .expect("intent")
                        .expect("an action")
                };
                if choice.action_id == "the_champ.gloat" {
                    gloat += 1;
                }
                if choice.action_id == "the_champ.defensive_stance" {
                    stance += 1;
                }
            }
            seen.push((ascension, gloat, stance));
        }
        let (_, gloat18, _) = seen[0];
        let (_, gloat19, stance19) = seen[1];
        assert!(gloat18 > 0, "A18 must still be able to choose Gloat (got {gloat18})");
        assert_eq!(gloat19, 0, "A19 must never choose Gloat");
        assert!(stance19 > 0, "A19 turns that slot into Defensive Stance (got {stance19})");
        take_session();
    }

    /// §208：Byrd 的 Flying —— **攻击**伤害减半，每被打一次掉一层；DoT 不算"被打"。
    ///
    /// 三段判据（缺一段就会静默错一档）：
    /// 1. 3 层 Flying 吃一次 10 点攻击 ⇒ 掉 **5** 点血（`ScalePercent -50` 是"乘 50%、**不读层数**"；
    ///    用 `ScalePercentPerStack` 会变成 10 × 0.5³ = 1，看起来也能跑）；
    /// 2. 那一次之后 Flying 只剩 **2** 层（`damage.isAttack` 这个事件事实）；
    /// 3. 毒（`resolve_damage_of_kind(Dot)`）**不减层**：`damage.isAttack` 为假，触发器不动。
    #[test]
    fn flying_halves_attack_damage_and_loses_a_stack_per_hit() {
        use rd_core::status_bind::DamageKind;
        let session = build_session_at(7, "enc_byrds", 200, None, 0, 0)
            .expect("the byrd fight builds");
        install_session(session);
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let stacks = |state: &rd_core::state::CombatState| {
            state
                .combatant(&cid_in("byrd"))
                .and_then(|combatant| {
                    combatant
                        .statuses()
                        .iter()
                        .find(|instance| instance.definition_id.as_str() == "standard.flying")
                        .map(|instance| instance.stacks)
                })
                .unwrap_or(0)
        };
        // 1 + 2: one 10-point attack. The **host** has to run too: `DamageTaken` is an event, and the
        // Flying trigger lives on the receiving side -- a bare `resolve_damage` halves the damage but
        // never dispatches the event, which is exactly how the first version of this test failed.
        {
            let mut host = rd_core::host::Host::new(&content);
            let session = slot().as_mut().expect("session");
            let mut ctx = rd_core::exec::ExecContext::new(
                &mut session.state,
                Some(cid_in("hero")),
                Some(cid_in("byrd")),
                None,
                1024,
            )
            .with_content(&content);
            rd_core::exec::resolve_damage(&mut ctx, &cid_in("byrd"), 10, false)
                .expect("an attack lands");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("the host dispatches DamageTaken");
        }
        let (hp, left) = {
            let session = slot().as_ref().expect("session");
            let combatant = session.state.combatant(&cid_in("byrd")).expect("byrd");
            (combatant.health_current, stacks(&session.state))
        };
        let max = {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("byrd")).expect("byrd").health_max
        };
        assert_eq!(max - hp, 5, "Flying halves the 10-point attack");
        assert_eq!(left, 2, "and the hit costs one Flying stack");
        // 3: a DoT tick does **not** touch it.
        {
            let session = slot().as_mut().expect("session");
            let before = session.state.combatant(&cid_in("byrd")).expect("byrd").health_current;
            let mut ctx = rd_core::exec::ExecContext::new(
                &mut session.state,
                Some(cid_in("hero")),
                Some(cid_in("byrd")),
                None,
                1024,
            )
            .with_content(&content);
            rd_core::exec::resolve_damage_of_kind(&mut ctx, &cid_in("byrd"), 10, false, DamageKind::Dot)
                .expect("a DoT tick lands");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            let after = session.state.combatant(&cid_in("byrd")).expect("byrd").health_current;
            assert_eq!(before - after, 10, "DoT is not halved (it is not an attack)");
        }
        assert_eq!(
            {
                let session = slot().as_ref().expect("session");
                stacks(&session.state)
            },
            2,
            "a DoT tick must not consume a Flying stack (damage.isAttack)"
        );
        take_session();
    }

    /// §226：`Dual Wield` 在 **run/页面层**的那三个数：`kind = 4`、`copies = 1`、`count = 收窄后`。
    ///
    /// 这条判据存在的理由很具体：`rd_env_choice_count` / `rd_env_choice_confirm` /
    /// `pile_card_id(3, i)` 原来各读一次**牌区**。收窄过的问句里合法选项比牌区少，三处只要有一处
    /// 忘了改，页面就会画出内核随后要拒绝的那一项 —— 而"点了没反应"正是最难从日志里认出来的形态。
    #[test]
    fn a_dual_wield_question_reads_the_same_three_numbers_in_the_page_layer() {
        let session = build_session_at(7, "enc_jaw_worm", 200, None, 0, 0)
            .expect("the jaw worm fight builds");
        install_session(session);
        let hero = cid_in("hero");
        // 手牌：一张攻击（唯一合法答案）+ 一张技能（必须被过滤掉）+ 那张牌自己。
        let mut hand_index = None;
        {
            let session = slot().as_mut().expect("session");
            for (index, definition) in ["strike", "defend", "dual_wield"].iter().enumerate() {
                let definition = rd_core::state::CardDefinitionId::new(definition)
                    .expect("short definition id");
                session
                    .state
                    .create_card_instance(&hero, definition, rd_core::state::CardZone::Hand)
                    .expect("the hand has room");
                let _ = index;
            }
            session.reobserve();
            // §161.4: the step names a **hand position**, so find the position of `dual_wield`.
            hand_index = session.hand_zone().and_then(|zones| {
                (0..zones.count(rd_core::state::CardZone::Hand)).find(|index| {
                    zones
                        .slot_at(rd_core::state::CardZone::Hand, *index)
                        .and_then(|slot| session.state.card(slot))
                        .is_some_and(|card| card.definition_id.as_str() == "dual_wield")
                })
            });
        }
        let hand_index = hand_index.expect("dual wield is in the hand");
        let verdict = rd_env_step(i32::try_from(hand_index).unwrap());
        assert_ne!(verdict, -3, "the play was refused: {}", session_error());
        assert_eq!(rd_env_choice_pending(), 1, "playing it asks a question");
        assert_eq!(rd_env_choice_kind(), 4, "4 = copy (the page writes the sentence from this)");
        assert_eq!(rd_env_choice_copies(), 1, "the printed card makes one copy");
        // ③ 收窄是**属性**，不是一个数字：手里本来就有起手牌，所以数"有几张"会把这条判据变
        //    "照抄一遍过滤逻辑"。这里问的是：每一项都是 Attack/Power 吗？那张**技能**牌在不在？
        let count = rd_env_choice_count();
        assert!(count >= 1, "there is at least one Attack in hand, got {count}");
        let mut options = Vec::new();
        for index in 0..count {
            options.push(pile_card_id(3, index).expect("every option is readable"));
        }
        // 起手牌组里带 Attack 标签的只有 `strike` / `bash`；技能牌一张都不许进选项。
        for option in &options {
            assert!(
                option == "strike" || option == "bash",
                "an option is not an Attack: {options:?}"
            );
        }
        assert!(
            !options.iter().any(|id| id == "defend"),
            "the Skill we injected must not be an option: {options:?}"
        );
        assert!(
            !options.iter().any(|id| id == "dual_wield"),
            "the card being played must not be its own option: {options:?}"
        );
        // ④ 回答：挑出来的那一张的**同名牌**多一张（起手牌里本来就有同名副本，所以比的是增量）。
        let picked = options[0].clone();
        let count_in_hand = |definition: &str| -> usize {
            let session = slot().as_ref().expect("session");
            session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::Hand)
                .filter(|card| card.definition_id.as_str() == definition)
                .count()
        };
        let before_copies = count_in_hand(&picked);
        assert_eq!(rd_env_choice_pick(0, 1), 0);
        assert_eq!(rd_env_choice_confirm(), 0, "{}", session_error());
        assert_eq!(rd_env_choice_pending(), 0, "the question is answered");
        assert_eq!(
            count_in_hand(&picked),
            before_copies + 1,
            "one copy of `{picked}` landed in the hand"
        );
        let hand: Vec<String> = {
            let session = slot().as_ref().expect("session");
            session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::Hand)
                .map(|card| card.definition_id.as_str().to_string())
                .collect()
        };
        assert!(hand.iter().any(|id| id == "defend"), "{hand:?}");
        assert!(!hand.iter().any(|id| id == "dual_wield"), "{hand:?}");
        take_session();
    }

    /// §227：一张牌在**页面层**提出的问句长什么样（`Armaments`）。
    ///
    /// 这一条是 soak 逼出来的：随机走图第一次打出 `Armaments` 时，战斗卡在"动作表空、没有问句"
    /// 的形状上。要分清是内核没提问句、还是页面没把问句画出来，得先钉住内核这一侧：
    /// 打出之后**必须**是"pending = 1 且动作表为空"（§161.3 的模态定义），而不是"两样都没有"。
    #[test]
    fn an_armaments_question_makes_the_page_layer_modal() {
        let session = build_session_at(7, "enc_jaw_worm", 200, None, 0, 0)
            .expect("the jaw worm fight builds");
        install_session(session);
        let hero = cid_in("hero");
        let mut hand_index = None;
        {
            let session = slot().as_mut().expect("session");
            let definition = rd_core::state::CardDefinitionId::new("armaments").expect("short id");
            session
                .state
                .create_card_instance(&hero, definition, rd_core::state::CardZone::Hand)
                .expect("the hand has room");
            session.reobserve();
            hand_index = session.hand_zone().and_then(|zones| {
                (0..zones.count(rd_core::state::CardZone::Hand)).find(|index| {
                    zones
                        .slot_at(rd_core::state::CardZone::Hand, *index)
                        .and_then(|slot| session.state.card(slot))
                        .is_some_and(|card| card.definition_id.as_str() == "armaments")
                })
            });
        }
        let hand_index = hand_index.expect("armaments is in the hand");
        let verdict = rd_env_step(i32::try_from(hand_index).unwrap());
        assert_ne!(verdict, -3, "the play was refused: {}", session_error());
        assert_eq!(
            rd_env_choice_pending(),
            1,
            "playing it asks a question (soak 卡住的那一局：`pending = 1` 与 `动作表空` 必须同时成立)"
        );
        assert_eq!(rd_env_choice_kind(), 5, "5 = upgrade the picked card");
        assert_eq!(rd_env_action_count(), 0, "a modal fight offers no other action");
        assert!(rd_env_choice_count() >= 1, "the hand has upgradable cards");
        // 页面上的勾选必须真的落进内核（`rd_env_choice_pick` → `choice_picks` → `selected`），
        // 否则"确认"会永远停在 disabled 上：随机走图里 tick 了六次都没变灰的按钮就是这个形状。
        assert_eq!(rd_env_choice_pick(0, 1), 0, "the tick is accepted");
        assert_eq!(rd_env_choice_selected(0), 1, "the tick stuck");
        assert_eq!(rd_env_choice_confirm(), 0, "{}", session_error());
        assert_eq!(rd_env_choice_pending(), 0, "the question is answered");
        take_session();
    }

    /// §208：`StartingBlock` —— Jaw Worm 开局就带 6 格挡（A17: 9）。
    ///
    /// 这一条是**基建**判据：`StartingStatuses` 只能挂状态，Block 是防御池，所以记录上多了
    /// `StartingBlock` / `StartingBlockAsc` 两列。判据问的是"建战之后它身上真的有格挡"，
    /// 并且 A16（6）与 A17（9）两侧各问一次。
    #[test]
    fn a_jaw_worm_starts_with_block_and_a17_makes_it_bigger() {
        for (ascension, expected) in [(0u8, 6i32), (16, 6), (17, 9)] {
            let session = build_session_at(7, "enc_jaw_worm", 200, None, 0, ascension)
                .unwrap_or_else(|e| panic!("jaw worm at A{ascension}: {e}"));
            install_session(session);
            let block = {
                let session = slot().as_ref().expect("session");
                session
                    .state
                    .combatant(&cid_in("jaw_worm"))
                    .and_then(|combatant| {
                        combatant
                            .defensive_pools()
                            .iter()
                            .find(|pool| pool.key.as_str() == "standard.block")
                            .map(|pool| pool.pool.current)
                    })
                    .unwrap_or(0)
            };
            assert_eq!(block, expected, "jaw worm block at A{ascension}");
        }
        take_session();
    }

    /// §208：`StartingStatuses[].AscensionMin` —— Awakened One 的 `Strength 2` **只在 A4 起存在**。
    ///
    /// 与 `Asc`（换层数）是两件事：0 层仍会占一个状态实例，`selfHasStatus` 也仍然为真，所以
    /// "A4 之前没有这个状态"必须由**presence** 表达，不能写成 `Stacks: 0`。
    #[test]
    fn a_starting_status_can_start_existing_later() {
        for (ascension, expected) in [(0u8, 0i32), (3, 0), (4, 2), (19, 2)] {
            let session = build_session_at(7, "enc_awakened_one", 200, None, 0, ascension)
                .unwrap_or_else(|e| panic!("awakened one at A{ascension}: {e}"));
            install_session(session);
            let strength = {
                let session = slot().as_ref().expect("session");
                session
                    .state
                    .combatant(&cid_in("awakened_one"))
                    .map(|combatant| {
                        combatant
                            .statuses()
                            .iter()
                            .find(|instance| instance.definition_id.as_str() == "standard.strength")
                            .map_or(0, |instance| instance.stacks)
                    })
                    .unwrap_or(-1)
            };
            assert_eq!(strength, expected, "awakened one Strength at A{ascension}");
        }
        take_session();
    }

    /// §207：起始状态的 A 级升档 —— 同一场遭遇，只有 `ascension` 不同，层数就是 wiki 的数。
    ///
    /// 三行覆盖「A2 升一次、A17 再升一次」（Spiker 的 Thorns 3→4→7）与「只有 A19 升」
    /// （Awakened One 的 Regenerate 10→15、Curiosity 1→2）。**每一档都在阈值两侧**测：
    /// 3 是 A0/A1 的值、4 是 A2..A16 的值、7 是 A17+ 的值 —— 只测两头会漏掉"中间那一档没生效"。
    ///
    /// 判据读的是**战斗里真的挂上去的状态**（`combatant.statuses()`），不是内容里的 `Asc` 列表：
    /// 内容门已经比过列表了，这里问的是"它有没有真的被应用"。
    #[test]
    fn starting_statuses_follow_their_ascension_rows() {
        // (encounter, combatant, status, [(ascension, stacks), …])
        let cases: [(&str, &str, &str, [(u8, i32); 4]); 2] = [
            ("enc_spiker", "spiker", "standard.thorns", [(0, 3), (2, 4), (16, 4), (17, 7)]),
            ("enc_awakened_one", "awakened_one", "standard.regen",
             [(0, 10), (2, 10), (18, 10), (19, 15)]),
        ];
        for (encounter, who, status, points) in cases {
            for (ascension, expected) in points {
                let session = build_session_at(7, encounter, 200, None, 0, ascension)
                    .unwrap_or_else(|e| panic!("{encounter} at A{ascension}: {e}"));
                install_session(session);
                let stacks = slot()
                    .as_ref()
                    .expect("session")
                    .state
                    .combatant(&cid_in(who))
                    .map(|combatant| {
                        combatant
                            .statuses()
                            .iter()
                            .find(|instance| instance.definition_id.as_str() == status)
                            .map_or(0, |instance| instance.stacks)
                    })
                    .unwrap_or(-1);
                assert_eq!(
                    stacks, expected,
                    "{who} {status} at A{ascension}: wiki says {expected}"
                );
            }
        }
        take_session();
    }

    /// §202: **Act 2 的代表战** —— Bronze Automaton 第 1 回合真召唤两只 Orb。
    ///
    /// wiki `Bronze Automaton`：`Spawn` 召唤 2 个 Bronze Orb；Orb 在遭遇里是 `Spawn: false`
    /// （它只是**招式表**的载体，不在开场）。这条同时钉住三件事：
    /// 1. 开场只有 Boss（1 个战斗员），Orb **不在**场；
    /// 2. 打一个回合之后场上是 3 个（`node.createCombatant` 真的加了两个）；
    /// 3. 新来的那两只有各自唯一的 id（`bronze_orb` / `bronze_orb#2`），并且**能行动**
    ///    （第 2 回合起 `problems` 仍为空 —— 一个没有 id 的小兵会让回合机在某处响亮失败）。
    #[test]
    fn act_two_bronze_automaton_summons_its_orbs_on_turn_one() {
        let session = build_session_at(7, "enc_bronze_automaton", 200, None, 0, 0)
            .expect("the automat on fight builds");
        install_session(session);
        assert_eq!(enemy_count(), 1, "the boss alone: the orbs are `Spawn: false`");
        // Turn 1: the hero ends their turn, the boss takes its turn (Spawn) and the orbs join.
        for turn in 0..6 {
            let verdict = rd_env_step(0);
            assert_ne!(verdict, -3, "turn {turn}: {}", session_error());
            if rd_env_done() != 0 {
                break;
            }
            if enemy_count() == 3 {
                break;
            }
        }
        assert_eq!(
            enemy_count(),
            3,
            "the boss summoned two orbs (enemies now {})",
            enemy_count()
        );
        // The summons must be distinct **combatants**, or the turn loop cannot address them. This
        // reads the roster (turn order) rather than the display names: §205 made the name come from
        // the *definition*, so two orbs legitimately share `bronze_orb` -- the id is what must be
        // unique, and the name export is a presentation detail, not an identity.
        let roster: Vec<String> = slot()
            .as_ref()
            .expect("session")
            .enemy_roster()
            .iter()
            .map(|id| id.as_str().to_string())
            .collect();
        let mut unique = roster.clone();
        unique.sort();
        unique.dedup();
        assert_eq!(unique.len(), roster.len(), "duplicate combatant ids: {roster:?}");
        // …and the **names** must be the definitions (that is the §205 claim), two identical orbs
        // included, so a page printing "enemy #1" fails here.
        let mut names = Vec::new();
        let mut index = 0;
        while crate::rd_env_enemy_name_len(index) >= 0 {
            let len = crate::rd_env_enemy_name_len(index) as usize;
            let mut buffer = vec![0u8; len];
            unsafe { crate::rd_env_enemy_name_into(index, buffer.as_mut_ptr()) };
            names.push(String::from_utf8_lossy(&buffer).to_string());
            index += 1;
        }
        assert_eq!(
            names,
            vec!["bronze_automaton".to_string(), "bronze_orb".to_string(), "bronze_orb".to_string()],
            "a summoned orb must be named from its definition (§205)"
        );
        crate::take_session();
    }

    /// §202: **Act 3 的代表战** —— Reptomancer 召唤匕首，匕首炸完自己走（§200 的实战）。
    ///
    /// 这条把三个特性串起来：`createCombatant`（召唤）、§200 的"行动者自毁"、以及"敌人变多/变少
    /// 之后回合机仍然对"。判据：匕首出现在场上（战斗员数上升），并且**在若干回合之后消失**
    /// （`dagger.explode` 的 `destroyCombatant`），全程没有一步 `-3`。
    #[test]
    fn act_three_reptomancer_daggers_arrive_and_then_take_themselves_out() {
        let session = build_session_at(7, "enc_reptomancer", 200, None, 0, 0)
            .expect("the reptomancer fight builds");
        install_session(session);
        // This content's `enc_reptomancer` presets the two daggers (`Spawn: true`), so the fight
        // opens with boss + 2 daggers. What §200 changed is the **exit**: `dagger.explode` removes
        // its own actor, which used to be refused by `remove_combatant`.
        let start = enemy_count();
        assert_eq!(start, 3, "boss + the two preset daggers");
        let mut peak = start;
        let mut settled_after_peak = false;
        for turn in 0..40 {
            let verdict = rd_env_step(0);
            assert_ne!(verdict, -3, "turn {turn}: {}", session_error());
            if rd_env_done() != 0 {
                break;
            }
            let now = enemy_count();
            if now > peak {
                peak = now;
            } else if now < peak {
                // A dagger left the fight (`dagger.explode` removes its own actor, §200).
                settled_after_peak = true;
                break;
            }
        }
        assert!(peak >= start, "the daggers are on the field (peak {peak})");
        assert!(
            settled_after_peak,
            "a dagger must leave the fight by exploding (start {start}, peak {peak})"
        );
        crate::take_session();
    }

}
