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
use rd_core::state::{ChoiceThen, 
    CardZone, CombatId, CombatResult, CombatState, CombatTurnPhase, CombatantId,
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
/// Starting / per-turn energy (the standard package's `3`).
const ENERGY: i32 = 3;

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

const OFF_HEADER: usize = 0;
pub(crate) const OFF_HERO_STATUS: usize = OFF_HEADER + 12; // 12
const OFF_ENEMY: usize = OFF_HERO_STATUS + 5; // 17
const OFF_ENEMY_STATUS: usize = OFF_ENEMY + MAX_ENEMY_SLOTS * 8; // 49
pub(crate) const OFF_HAND: usize = OFF_ENEMY_STATUS + MAX_ENEMY_SLOTS * 5; // 69
const OFF_PILES: usize = OFF_HAND + MAX_HAND_SLOTS * 4; // 109
const OFF_RESERVED: usize = OFF_PILES + 5; // 114
/// `rd_env_observe_len()` — the caller must not hard-code this (`env-abi.md` §2.3), so it is
/// published as an export too. 122 is what this implementation happens to produce.
const OBS_LEN: usize = OFF_RESERVED + 8; // 122

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
    problems: Vec<&'static str>,
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

/// The session slot.
///
/// `wasm32-unknown-unknown` here is single-threaded, no export re-enters another export, and the
/// value lives in the module's BSS for the module's whole lifetime — so a `static mut` with one
/// accessor is sound. (This is the only `unsafe` in the crate besides the raw-pointer writes.)
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
pub(crate) fn combat_hero_health() -> Option<i32> {
    let session = slot().as_ref()?;
    let hero = session.hero_id()?;
    session
        .state
        .combatant(&hero)
        .map(|combatant| combatant.health_current)
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
    build_session_at(seed, encounter_name, hero_hp, deck, 0)
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
    let mut enemies: Vec<PlanCombatant<'static>> = Vec::new();
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
        enemies.push(PlanCombatant {
            id,
            max_health: max_health + max_health * enemy_health_percent / 100,
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
    let resources: &'static [(ResourceId, i32, Option<i32>)] =
        Box::leak(vec![(energy, ENERGY, Some(ENERGY))].into_boxed_slice());
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
    let host = Host::new(content);
    build_fight_from_content(&mut state, content, &plan)
        .map_err(|e| format!("build_fight_from_content: {}", detail(&e)))?;

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
    start_first_turn(&mut session.state, &standard, &mut session.host)
        .map_err(|e| format!("start_first_turn: {}", detail(&e)))?;
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
            let cost = self.printed_energy_cost(&def_id);
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
        obs[H_ENERGY_MAX] = self
            .hero_id()
            .and_then(|id| self.state.combatant(&id))
            .and_then(|c| {
                c.resources()
                    .iter()
                    .find(|p| p.key.as_str() == "standard.energy")
                    .and_then(|p| p.pool.max)
            })
            .unwrap_or(-1);
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
    fn exec(&mut self, steps: &[Step<'static>]) -> Result<(), String> {
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
                let name = if *problem == rd_core::battle::Problem::StepThrew && cause_name == "Capacity" {
                    let container = rd_core::state::Container::name_of(
                        out.step_capacity.get(index).copied().unwrap_or(0),
                    );
                    if container == "?" {
                        "StepThrew(Capacity)"
                    } else {
                        // The page reads this string; the container name is the actionable half.
                        capacity_problem_text(container)
                    }
                } else if *problem == rd_core::battle::Problem::StepThrew && !cause_name.is_empty() {
                    step_cause_text(cause_name)
                } else {
                    problem.wire_name()
                };                self.problems.push(name);
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
        let Some(def_id) = self.hand_defs.get(hand_index).cloned() else {
            self.error = format!("hand slot {hand_index} is empty");
            return Ok(());
        };
        // `Step` wants `&'static str`; the definition id came out of the content image, which is
        // itself `'static`, so this is a genuine promotion rather than a hidden leak.
        let card: &'static str = Box::leak(def_id.into_boxed_str());
        let target: Option<&'static str> = if target_slot < 0 {
            None
        } else {
            self.plan
                .enemies
                .get(target_slot as usize)
                .map(|enemy| &*Box::leak(enemy.id.to_string().into_boxed_str()))
        };
        self.exec(&[Step::HeroPlays { card, target }])
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
            let raw_id: &'static str = self
                .plan
                .enemies
                .iter()
                .map(|enemy| enemy.id)
                .find(|id| *id == active.as_str())
                .ok_or_else(|| format!("活跃战斗员 `{}` 不在 plan.enemies 里", active.as_str()))?;
            let action = self.action_for(&active)?;
            // `None` = this enemy has no authored action (`Actions` empty and no rule matched).
            // The reference has nothing to execute either; the turn still ends — it does not get
            // to act twice, and skipping the whole turn would be a different rule.
            if let Some(choice) = action {
                self.exec(&[Step::EnemyActs {
                    enemy: raw_id,
                    action: choice,
                    target: Some(HERO),
                }])?;
                if self.state.result != CombatResult::Ongoing {
                    return Ok(());
                }
            }
            self.exec(&[Step::EndOneTurn])?;
        }
        Ok(())
    }

    /// The `EACT` id this combatant will use **now** (nil = no authored action).
    fn action_for(&self, actor: &CombatantId) -> Result<Option<&'static str>, String> {
        let at = locate_enemy(self.content, self.encounter, actor)
            .map_err(|error| format!("locate_enemy: {}", detail(&error)))?
            .ok_or_else(|| format!("`{}` 不在这条遭遇的敌人名单里", actor.as_str()))?;
        let choice = select_action(&self.state, self.content, at, actor, self.state.current_round)
            .map_err(|error| format!("select_action: {}", detail(&error)))?;
        Ok(choice.map(|choice| choice.action_id))
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
fn pile_zone(session: &Session, zone: i32) -> Option<CardZone> {
    match zone {
        0 => Some(CardZone::DrawPile),
        1 => Some(CardZone::DiscardPile),
        2 => Some(CardZone::ExhaustPile),
        3 => session.state.pending_choice().map(|choice| choice.source.zone()),
        _ => None,
    }
}

/// How many cards are in `zone` (0 = draw, 1 = discard, 2 = exhaust); `-1` for a bad zone.
#[no_mangle]
pub extern "C" fn rd_env_pile_len(zone: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
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
        Some(id) => card_display_title(id).len() as i32,
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
            let title = card_display_title(id);
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
    session
        .state
        .card_zones(&choice.chooser)
        .map_or(-1, |zones| zones.count(choice.source.zone()) as i32)
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
    let Some(zones) = session.state.card_zones(&choice.chooser) else {
        return refuse_with_text("待决选牌的战斗员没有牌区");
    };
    let zone = choice.source.zone();
    let count = zones.count(zone);
    // Same enumeration the picker used (`rd_env_pile_len(3)`), and a loud cross-check that the slot
    // table and the card pool still line up. A silent `zip` over two lists of different lengths
    // would resolve a *different* question than the one that was asked.
    let ids: Vec<rd_core::state::CardInstanceId> = session
        .state
        .zone_cards(&choice.chooser, zone)
        .map(|card| card.id)
        .collect();
    if ids.len() != count {
        return refuse_with_text("牌的槽位表与卡池不一致：选牌清单不完整");
    }
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
    match session.state.resolve_choice(&picks) {
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

fn pile_card_id(zone: i32, index: i32) -> Option<&'static str> {
    if index < 0 {
        return None;
    }
    let session = ensure_session().ok()?;
    let zone = pile_zone(session, zone)?;
    let hero = session.hero_id()?;
    let (_, card) = session
        .state
        .zone_cards(&hero, zone)
        .enumerate()
        .find(|(position, _)| *position == index as usize)?;
    Some(card.definition_id.as_str())
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
fn card_display_title(id: &'static str) -> &'static str {
    let Ok(session) = ensure_session() else {
        return id;
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
        .unwrap_or(id)
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
#[no_mangle]
pub extern "C" fn rd_env_enemy_name_len(index: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    session
        .plan
        .enemies
        .get(index.max(0) as usize)
        .map_or(-1, |enemy| enemy.id.len() as i32)
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
    let Some(enemy) = session.plan.enemies.get(index.max(0) as usize) else {
        return -1;
    };
    std::ptr::copy_nonoverlapping(enemy.id.as_ptr(), ptr, enemy.id.len());
    enemy.id.len() as i32
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
        Ok(()) => i32::from(session.problems.first().copied() == Some("CardNotInHand")),
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
        let after_reset = rd_env_beat_count();
        assert!(
            (0..=1).contains(&after_reset),
            "reset produced {after_reset} beats"
        );
        if after_reset == 1 {
            assert_eq!(beat_field(0, 0), BEAT_TURN_STARTED, "the only thing reset may log");
            assert_eq!(beat_field(0, 1), -1, "…and it is the hero's");
        }

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

    /// `(伤害条数, 总伤害)`，只数真的掉血的 hit。
    fn damage_beats() -> (i32, i32) {
        let mut hits = 0;
        let mut total = 0;
        for index in 0..rd_env_beat_count() {
            if rd_env_beat_field(index, 0) != BEAT_DAMAGE {
                continue;
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
        assert_eq!(
            first_enemy_health(),
            enemy_before - 13,
            "Uppercut deals 13 to the enemy"
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

}
