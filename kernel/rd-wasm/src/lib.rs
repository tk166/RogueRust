//! `rd-wasm` — the `rd-core` combat kernel behind the **env ABI** (`docs/spec/env-abi.md`),
//! compiled to `wasm32-unknown-unknown` and driven from a plain static HTML page.
//!
//! # What this crate is
//!
//! A **spike**: it answers "can the browser UI speak the same protocol as the future RL
//! environment?", not "is this the product". So:
//!
//! * the scenario is **hard-coded** (hero 70 HP, one `queue_imp` at 22 HP, 8 cards) — the task's
//!   "先写死一个最小场景";
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
//! 1. **No enemy intent.** `intent_kind` / `intent_damage` are always `-1`. The *reader* this gap
//!    was waiting on now exists (`content::Content::encounter_enemies`, which walks
//!    `ENCT[i].Enemies[j]` → `Actions` / `IntentRules` / `StartingStatuses`), and
//!    `intent::select_action` takes `(encounter, slot)` — so what is left is only the **wiring
//!    here**: find the slot whose `Id` matches the active combatant, call `select_action`, read the
//!    `EACT` program's damage. Until that is done the spike hard-codes `queue_imp.desk_jab`.
//! 2. **No handle.** See above.
//! 3. **No hero self-actions (ABI kind 2).** `FightPlan` has no `actions` field, so the driver
//!    layer cannot express one.
//! 4. **One enemy may act per end-turn step.** ⚠️ **The kernel side of this gap is closed**
//!    (`battle::Step::EndOneTurn`: end exactly one turn, stop at the next *living* combatant,
//!    stop early if the fight ends). This spike still calls `NextRound` in
//!    [`Session::step_end_turn`], so the behaviour below is unchanged — switching that call to
//!    `EndOneTurn` is the remaining work, and it is a one-line change plus a re-measure.
//! 5. **`upgraded` is always 0.** In this content "upgraded" is a *different card definition*
//!    (`paper_cut` vs `paper_cut+`), not a flag on an instance — `CardInstance` has no such bit.
//! 6. **`hero_ward` / `enemy.ward` are always `-1`.** No `ward` resource exists in the content
//!    image (the standard package's pool is `standard.block`); `-1` says "this implementation
//!    does not produce this quantity", which is the truth.

use rd_core::battle::{
    build_fight, run_fight, standard_turn_config, DeckEntry, FightOutcome, FightPlan, PlanCombatant,
    Step,
};
use rd_core::content::{Content, ABSENT16, EK_CARD, LIST_ABSENT, LIST_NULL, NULL16, OP_ARR};
use rd_core::host::Host;
use rd_core::ir::NodeRef;
use rd_core::play::can_play_card;
use rd_core::state::{
    CardZone, CombatId, CombatResult, CombatState, CombatTurnPhase, CombatantId,
    CombatantLifecycleState, ResourceId,
};

// =============================================================================================
// The hard-coded scenario
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
fn detail<T: core::fmt::Debug>(value: &T) -> String {
    format!("{value:?}")
}

/// See the sibling above.
#[cfg(rd_wasm_plain_errors)]
fn detail<T: core::fmt::Debug>(_value: &T) -> String {
    // `T`'s `Debug` impl is never instantiated on this path, which is exactly how its code
    // disappears from the module. The bound stays so the call sites do not have to change.
    "<detail off>".to_string()
}

/// The content image, embedded at compile time. 85,616 B — a browser has no filesystem, so the
/// image has to travel inside the module. It is the same `content.core.rdcf` every native binary
/// reads (`tools/contentc/compile.py` produces it); if it is missing the build fails loudly here
/// rather than producing a module that cannot start a fight.
static IMAGE: &[u8] = include_bytes!("../../../tools/contentc/out/content.core.rdcf");

/// RNG seed. `paper_cut` decks + `shuffle: true` makes this observable (`random_step` moves).
const SEED: i32 = 7;
const COMBAT_ID: &str = "rd_wasm_spike";
const HERO: &str = "hero";
const HERO_HP: i32 = 70;
const ENEMY: &str = "queue_imp";
const ENEMY_HP: i32 = 22;
/// `EACT` id of the one action this enemy is allowed to take. Hard-coded because enemy *action
/// selection* is not reachable (Gap 1). `queue_imp.desk_jab` = `dealDamage 8 -> sel.eventTarget`.
const ENEMY_ACTION: &str = "queue_imp.desk_jab";
/// Starting / per-turn energy (the standard package's `3`).
const ENERGY: i32 = 3;

/// `PlanCombatant` is `Copy` and holds only `&'static str`, so a `static` array is the clean way
/// to get the `&'static [PlanCombatant<'static>]` that `FightPlan` demands.
static ENEMIES: [PlanCombatant<'static>; 1] = [PlanCombatant {
    id: ENEMY,
    max_health: ENEMY_HP,
}];
static DECK: [DeckEntry<'static>; 3] = [
    // 5×6 damage: three per turn fits exactly the 3 starting energy, so the enemy dies on turn 2
    // and the page gets a real Victory without the player having to think.
    DeckEntry {
        card: "paper_cut",
        count: 5,
    },
    // A block card, so "hero block" is a number that actually moves.
    DeckEntry {
        card: "cower_behind_a_desk",
        count: 2,
    },
    // A 2-cost card, so the energy gate in the action list is observable.
    DeckEntry {
        card: "permit_a38",
        count: 1,
    },
];

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
fn slot() -> &'static mut Option<Session> {
    unsafe { &mut SESSION }
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
    let content: &'static Content<'static> =
        Box::leak(Box::new(Content::parse(IMAGE).map_err(|e| format!("RDCF 镜像解析失败: {}", detail(&e)))?));

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
            max_health: HERO_HP,
        },
        enemies: &ENEMIES,
        deck: &DECK,
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
    build_fight(&mut state, content, &plan).map_err(|e| format!("build_fight: {}", detail(&e)))?;

    let mut session = Session {
        content,
        state,
        host,
        plan,
        out: Box::new(FightOutcome::new()),
        hand_defs: Vec::new(),
        hand_costs: Vec::new(),
        actions: Vec::new(),
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
        self.after = self.compute_observation();
        self.publish();
        self.actions = self.compute_actions();
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
            obs[base + 5] = -1; // intent_kind: Gap 1
            obs[base + 6] = -1; // intent_damage: Gap 1
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

    /// kind 1. The driver exposes no "advance one combatant", so the whole enemy phase is driven
    /// here: end the hero turn → let the (single) enemy act → `NextRound` wraps back to the hero.
    /// Gap 4: with two enemies the second one is skipped, so this refuses instead.
    ///
    /// ⚠️ The kernel half of Gap 4 is **closed** (`battle::Step::EndOneTurn`); this spike still
    /// routes through `NextRound` at the bottom, which is why the guard below is still needed.
    /// Switching that one call to `EndOneTurn` (and dropping the guard) is the remaining work.
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
        if self.plan.enemies.len() > 1 {
            return Err(format!(
                "Gap 4: this driver can let at most one enemy act per end-turn step, plan has {}",
                self.plan.enemies.len()
            ));
        }

        self.exec(&[Step::HeroEndsTurn])?;
        if self.state.result != CombatResult::Ongoing {
            return Ok(());
        }

        // Whose turn is it now? Only `ENEMY` is expressible (see `Step::EnemyActs`'s `&'static`
        // requirement and Gap 1).
        let active_is_enemy = match self.state.active_combatant_id.as_ref() {
            Some(id) => id.as_str() != HERO,
            None => false,
        };
        if !active_is_enemy {
            return Ok(());
        }
        let active = self
            .state
            .active_combatant_id
            .as_ref()
            .map(|id| id.as_str().to_string())
            .unwrap_or_default();
        if active != ENEMY {
            return Err(format!(
                "Gap 1/4: enemy `{active}` has no authored action in this spike (only `{ENEMY}`)"
            ));
        }

        self.exec(&[Step::EnemyActs {
            enemy: ENEMY,
            action: ENEMY_ACTION,
            target: Some(HERO),
        }])?;
        if self.state.result != CombatResult::Ongoing {
            return Ok(());
        }
        self.exec(&[Step::NextRound])?;
        Ok(())
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

    /// The ABI works end to end on the host: the hand really gets drawn, a `paper_cut` really
    /// costs 1 energy, the enemy really dies, and a rejected step really changes nothing.
    #[test]
    fn the_spike_scenario_is_playable_through_the_env_abi() {
        assert_eq!(rd_env_reset(), 0);
        // Pin the size attribution the spike report makes, so it cannot rot silently:
        // the 184 KB is the *state*, and the driver's envelope is a few KB, not a data-section
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

        // Before the first step the hero has not started its turn, so the hand is empty — this is
        // `ScenarioRunner.cs:105`'s `EnsureTurnStarted` being *lazy*, and it is worth pinning
        // because "the hand is empty on load" looks like a bug from the outside.
        assert_eq!(observation()[H_HAND_COUNT], 0, "hand before the first turn");
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
        assert_eq!(exported_observation()[H_ROUND], 1, "round on a fresh fight");

        // A play action must exist even though the hand is empty? No — nothing to play yet, so the
        // only legal action is "end turn". That is the honest table, and it is why the page's end
        // turn button is what draws the first hand.
        assert_eq!(rd_env_action_count(), 1);
        assert_eq!(rd_env_action_kind(0), ACTION_END_TURN);

        // Ending the first turn must leave the hero holding a drawn hand: `NextRound` wraps to the
        // hero, and wrapping *starts* its turn, and starting it draws.
        assert_eq!(rd_env_step(0), 0);
        assert_eq!(
            exported_observation()[H_HAND_COUNT],
            5,
            "a full hand after wrapping back to the hero's turn"
        );
        // The drawn cards must carry real costs out of the image (not the `-1` "could not read").
        for hand_index in 0..5 {
            let base = OFF_HAND + hand_index * 4;
            let obs = exported_observation();
            assert_eq!(obs[base], 1, "hand slot {hand_index} occupied");
            assert!(obs[base + 1] >= 0, "hand slot {hand_index} cost is unreadable");
            assert!(obs[base + 2] >= 0, "hand slot {hand_index} def_slot is unreadable");
        }

        // Out-of-range actions are refused, and refusal must not move the state.
        let before = observation();
        assert_eq!(rd_env_step(7), -1, "out-of-range step");
        assert_eq!(observation(), before, "a rejected step moved the observation");

        // Now actually play. Greedy: first enumerated action each time, until the fight ends.
        let mut steps = 0;
        while rd_env_done() == 0 && steps < 200 {
            assert!(rd_env_action_count() > 0, "stuck with no legal actions");
            let verdict = rd_env_step(0);
            assert_eq!(verdict, 0, "step {steps} was refused");
            steps += 1;
        }
        assert!(steps > 0, "the fight never advanced");
        assert_eq!(rd_env_done(), 1, "the fight did not terminate");
        assert_eq!(rd_env_result(), 1, "the greedy policy should have won");

        // The enemy is at 0 and the hero is still standing.
        let obs = observation();
        assert_eq!(obs[H_RESULT], 1);
        assert_eq!(obs[OFF_ENEMY + 1], 0, "enemy hp");
        assert_eq!(obs[OFF_ENEMY], 0, "enemy should be down, not alive");
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

