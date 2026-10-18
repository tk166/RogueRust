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

use crate::map::{RunMap, NODES_PER_ROW, ROWS};
use crate::streams::{RunError, RunRng};

/// The most cards a run's deck may hold. See the module docs: exceeding it is an error, never a
/// truncation.
pub const MAX_RUN_DECK: usize = 60;
/// The most relics a run may hold. `inv:§6` has 140 obtainable, but a single run sees on the order
/// of a dozen; twenty-four is "what a run needs", not "what a budget allows".
pub const MAX_RUN_RELICS: usize = 24;
/// The potion belt (`inv:§9.3`: hold at most 3).
pub const MAX_RUN_POTIONS: usize = 3;
/// The most nodes one step can offer: the first floor is chosen freely among a whole row.
pub const MAX_STEP_TARGETS: usize = NODES_PER_ROW;

/// A tripwire, not a budget. Measured value lives in [`RunState::size_bytes`]; this bound is here so
/// that adding a field cannot quietly double the run's memory. `CombatState`'s equivalent has the
/// same job (`rd-core/src/state.rs::state_fits_the_sram_plan`).
pub const RUN_STATE_TRIPWIRE_BYTES: usize = 8 * 1024;

/// A deck/relic/potion id. `Ident<ID_CAP>` is 41 bytes (`ID_CAP` 40 + a length byte).
pub type RunId = Ident<ID_CAP>;

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
    deck: [RunId; MAX_RUN_DECK],
    deck_len: u8,
    relics: [RunId; MAX_RUN_RELICS],
    relics_len: u8,
    potions: [RunId; MAX_RUN_POTIONS],
    potions_len: u8,
    map: RunMap,
    rng: RunRng,
    /// `?` room cumulative odds (`inv:§7.5`), three counters, reset at the start of an act.
    unknown: [i32; 3],
}

impl RunState {
    /// Start a run: generate the map from the `Map` stream, and take the content-derived starting
    /// facts as arguments (see the module docs).
    ///
    /// `starting_deck` is the deck **in order** — deck order is observable (`run-layer.md` §5.2),
    /// so it is not sorted here or anywhere else.
    pub fn new(
        seed: i32,
        health_max: i32,
        gold: i32,
        starting_deck: &[&str],
    ) -> Result<Self, RunError> {
        let mut rng = RunRng::new(seed);
        let map = RunMap::generate(&mut rng)?;
        let mut state = Self {
            seed,
            floor: 0,
            health: health_max,
            health_max,
            gold,
            node: -1,
            removed_cards: 0,
            deck: [RunId::EMPTY; MAX_RUN_DECK],
            deck_len: 0,
            relics: [RunId::EMPTY; MAX_RUN_RELICS],
            relics_len: 0,
            potions: [RunId::EMPTY; MAX_RUN_POTIONS],
            potions_len: 0,
            map,
            rng,
            unknown: [0; 3],
        };
        for id in starting_deck {
            state.push_card(id)?;
        }
        state.check_invariants()?;
        Ok(state)
    }

    // ---- reads -----------------------------------------------------------------------------

    /// The run seed.
    #[must_use]
    pub const fn seed(&self) -> i32 {
        self.seed
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
    /// Mutable access to the streams, for the settlement code that lands next.
    pub fn rng_mut(&mut self) -> &mut RunRng {
        &mut self.rng
    }
    /// The deck, in acquisition order.
    #[must_use]
    pub fn deck(&self) -> &[RunId] {
        &self.deck[..self.deck_len as usize]
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
    /// The `?` room odds (`inv:§7.5`).
    #[must_use]
    pub const fn unknown_odds(&self) -> [i32; 3] {
        self.unknown
    }

    /// The measured size, for the tripwire and for anyone printing a memory table.
    #[must_use]
    pub const fn size_bytes() -> usize {
        core::mem::size_of::<Self>()
    }

    // ---- writes ----------------------------------------------------------------------------

    /// Add a card to the deck. Past [`MAX_RUN_DECK`] this is an **error**, never a dropped push.
    pub fn push_card(&mut self, definition_id: &str) -> Result<(), RunError> {
        let id = RunId::new(definition_id).map_err(|_| RunError::BadId)?;
        let slot = self.deck_len as usize;
        if slot >= MAX_RUN_DECK {
            return Err(RunError::Capacity);
        }
        self.deck[slot] = id;
        self.deck_len += 1;
        Ok(())
    }

    /// Add a relic. Past [`MAX_RUN_RELICS`] this is an error.
    pub fn push_relic(&mut self, relic_id: &str) -> Result<(), RunError> {
        let id = RunId::new(relic_id).map_err(|_| RunError::BadId)?;
        let slot = self.relics_len as usize;
        if slot >= MAX_RUN_RELICS {
            return Err(RunError::Capacity);
        }
        self.relics[slot] = id;
        self.relics_len += 1;
        Ok(())
    }

    /// Add a potion. Past [`MAX_RUN_POTIONS`] this is an error (the belt has three slots).
    pub fn push_potion(&mut self, potion_id: &str) -> Result<(), RunError> {
        let id = RunId::new(potion_id).map_err(|_| RunError::BadId)?;
        let slot = self.potions_len as usize;
        if slot >= MAX_RUN_POTIONS {
            return Err(RunError::Capacity);
        }
        self.potions[slot] = id;
        self.potions_len += 1;
        Ok(())
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

    /// Add or spend gold, clamped at 0.
    pub fn adjust_gold(&mut self, delta: i32) {
        self.gold = (self.gold + delta).max(0);
    }

    // ---- walking the map -------------------------------------------------------------------

    /// Where the cursor can go next.
    ///
    /// Before the first step, that is **every node on floor 1** (`inv:§7.2`: the player picks a
    /// start). Afterwards, it is the current node's out-edges.
    #[must_use]
    pub fn reachable(&self) -> Reachable {
        let mut out = Reachable::default();
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
            return out; // floor 15 is the last row; there is nowhere to walk
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
        let Some((row, _)) = self.map.locate(target) else {
            return Err(RunError::BadNode);
        };
        self.node = i32::from(target);
        self.floor = row as i32 + 1;
        self.check_invariants()
    }

    /// The per-step invariants from `run-layer.md` §6.2. A **real** check: the release build is what
    /// runs on the device, and a `debug_assert!` would leave the device unchecked.
    pub fn check_invariants(&self) -> Result<(), RunError> {
        self.map.check().map_err(|_| RunError::MapGeneration)?;
        if self.floor < 0 || self.floor as usize > ROWS {
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
        } else {
            let Some((row, _)) = self.map.locate(self.node as u8) else {
                return Err(RunError::BadNode);
            };
            if row as i32 + 1 != self.floor {
                return Err(RunError::Invariant("floor does not match the node's row"));
            }
        }
        Ok(())
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
    use crate::map::NodeKind;

    fn ironclad() -> RunState {
        let deck = [
            "strike", "strike", "strike", "strike", "strike",
            "defend", "defend", "defend", "defend",
            "bash",
        ];
        RunState::new(7, 80, 99, &deck).expect("a run must start")
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
            run.enter_node(next).unwrap();
            steps += 1;
            assert_eq!(run.floor() as usize, steps);
            assert_eq!(run.check_invariants(), Ok(()));
        }
        assert_eq!(run.floor(), ROWS as i32);
        assert!(run.reachable().is_empty(), "the last row has nowhere to go");
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
            match run.push_card("strike") {
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
            run.push_relic("burning_blood").unwrap();
        }
        assert_eq!(run.push_relic("burning_blood"), Err(RunError::Capacity));
        // Potions: the belt is three slots (`inv:§9.3`).
        for _ in 0..MAX_RUN_POTIONS {
            run.push_potion("fire_potion").unwrap();
        }
        assert_eq!(run.push_potion("fire_potion"), Err(RunError::Capacity));
        // An id longer than the id capacity is refused, not silently shortened.
        assert_eq!(run.push_card(&"x".repeat(ID_CAP + 1)), Err(RunError::BadId));
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
}
