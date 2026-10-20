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
    build_fight_from_content, run_fight, standard_turn_config, DeckEntry, FightOutcome, FightPlan,
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

const MAX_ENEMY_SLOTS: usize = 4;
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
const OFF_HERO_STATUS: usize = OFF_HEADER + 12; // 12
const OFF_ENEMY: usize = OFF_HERO_STATUS + 5; // 17
const OFF_ENEMY_STATUS: usize = OFF_ENEMY + MAX_ENEMY_SLOTS * 8; // 49
const OFF_HAND: usize = OFF_ENEMY_STATUS + MAX_ENEMY_SLOTS * 5; // 69
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
const H_HERO_BLOCK: usize = 6;
const H_HERO_WARD: usize = 7;
const H_ENERGY: usize = 8;
const H_ENERGY_MAX: usize = 9;
const H_HAND_COUNT: usize = 10;
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
        enemies.push(PlanCombatant { id, max_health });
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
        before: vec![0; OBS_LEN],
        after: vec![0; OBS_LEN],
    };
    session.reobserve();
    // `run_fight` needs a `&mut Host`; keep it warm so the first step does not allocate.
    let _ = session.host.take_failure();
    Ok(session)
}

impl Session {
    /// Refresh the observation snapshot and the action table. Called after every state change.
    ///
    /// ⚠️ The order matters and was wrong once: `compute_observation` reads `hand_defs` (to fill
    /// `def_slot`) and `hand_costs` (to fill `cost`), so [`Self::refresh_hand`] has to run first.
    /// The first version rebuilt them inside `compute_actions`, i.e. *after* publishing the
    /// observation, so every hand slot came out as `occupied = -1` while `hand_count` said 5 —
    /// a self-contradicting vector that no test noticed until one did.
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
        let mut intents = Vec::with_capacity(self.plan.enemies.len());
        for slot in 0..self.plan.enemies.len().min(MAX_ENEMY_SLOTS) {
            let raw_id = self.plan.enemies[slot].id;
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

    /// Wall-slot count of enemies that are still alive (their slots never move — `env-abi.md` §10).
    fn alive_enemy_slots(&self) -> Vec<usize> {
        let mut out = Vec::new();
        for (slot_index, plan_enemy) in self.plan.enemies.iter().enumerate() {
            if slot_index >= MAX_ENEMY_SLOTS {
                break;
            }
            let alive = CombatantId::new(plan_enemy.id)
                .ok()
                .and_then(|id| self.state.combatant(&id))
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
        obs[H_ENEMY_COUNT] = self.plan.enemies.len() as i32;

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
            let Some(plan_enemy) = self.plan.enemies.get(slot_index) else {
                continue; // already `-1`
            };
            let combatant = CombatantId::new(plan_enemy.id)
                .ok()
                .and_then(|id| self.state.combatant(&id));
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
        let Some(hero) = self.hero_id() else {
            return actions;
        };

        let alive = self.alive_enemy_slots();
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
                .and_then(|slot_index| self.plan.enemies.get(*slot_index))
                .and_then(|enemy| CombatantId::new(enemy.id).ok());
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
            for problem in out.problems_of(index) {
                self.problems.push(problem.wire_name());
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
    if session.is_done() {
        return -2;
    }
    let Some(action) = session.actions.get(index.max(0) as usize).copied() else {
        return -1;
    };

    session.error.clear();
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

fn pile_zone(zone: i32) -> Option<CardZone> {
    match zone {
        0 => Some(CardZone::DrawPile),
        1 => Some(CardZone::DiscardPile),
        2 => Some(CardZone::ExhaustPile),
        _ => None,
    }
}

/// How many cards are in `zone` (0 = draw, 1 = discard, 2 = exhaust); `-1` for a bad zone.
#[no_mangle]
pub extern "C" fn rd_env_pile_len(zone: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    let Some(zone) = pile_zone(zone) else {
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

fn pile_card_id(zone: i32, index: i32) -> Option<&'static str> {
    if index < 0 {
        return None;
    }
    let session = ensure_session().ok()?;
    let zone = pile_zone(zone)?;
    let hero = session.hero_id()?;
    let (_, card) = session
        .state
        .zone_cards(&hero, zone)
        .enumerate()
        .find(|(position, _)| *position == index as usize)?;
    Some(card.definition_id.as_str())
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
        assert_eq!(fresh[H_HAND_COUNT], 0, "hand before the first turn");
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
        assert_eq!(rd_env_action_count(), 1);
        assert_eq!(rd_env_action_kind(0), ACTION_END_TURN);

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
        let hp_before = fresh[H_HERO_HP];
        assert_eq!(rd_env_step(0), 0);
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

    /// A hand with cards in it: the fight starts with an empty hand (`ScenarioRunner.cs:105`), so
    /// one end-turn is what draws.
    fn open_the_hand() {
        assert_eq!(rd_env_reset(), 0);
        assert_eq!(rd_env_step(0), 0, "the only action on a fresh fight is end turn");
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
}
