//! The run layer for StS Act 1: everything **above** a single fight.
//!
//! The combat kernel (`rd-core`) answers "given this fight, what happens next". This crate answers
//! "given this run, which fight is it, and what does the player carry into it": the map, the floor,
//! the deck, the gold, the relics, and the random streams that decide all of it.
//!
//! Three things it deliberately is not:
//!
//! * **Not part of `CombatState`.** That struct is `Copy`, 213,224 B, and rebuilt per fight; the run
//!   state lives for a whole run. Merging them would make "start the next fight" depend on clearing
//!   the previous fight's memory, and would turn one size bound into the sum of two unrelated ones.
//! * **Not comparable against the C# engine.** The reference has no run layer at all
//!   (`docs/spec/sts-act1-plan.md` §2 G6), so nothing here is differential-tested. The standard is
//!   `docs/spec/sts-act1-plan.md` §5.3: readable rules, per-rule unit tests, and step-wise
//!   `run_hash` determinism. **Nothing in this crate may claim to match StS's own RNG.**
//! * **Not allowed to lie quietly.** Every capacity that would change behaviour if enlarged fails
//!   loudly instead of truncating (`port-plan.md` §45.4's hard rule).
//!
//! Shape is frozen in `docs/spec/run-layer.md`. §3 of that document is executable today and lives
//! in [`streams`]; the map, `RunState` and `run_hash` land on top of it.

#![cfg_attr(not(test), no_std)]
#![forbid(unsafe_code)]

pub mod map;
pub mod streams;
