//! The ported RogueDeck combat kernel.
//!
//! Ported from `RogueDeck-Core` at commit `fd43e68ab91f40b475b745725abb17134b951c51` (MIT).
//! Semantics are frozen in `docs/spec/SEMANTICS-v1.md`; anything this crate does differently
//! from the C# engine is recorded there as an intentional deviation.
//!
//! Three rules hold everywhere in this crate:
//!
//! 1. **Integer arithmetic only.** The C# core has zero `float` and ten `double`, and the only
//!    float on the combat path is in the not-in-scope positional system. Keeping it integer is
//!    what makes bit-exact agreement with the reference achievable, and it is what lets the
//!    ESP32-P4's single-precision FPU stay unused.
//! 2. **No allocator.** Nothing here allocates; callers pass in the storage. The target has
//!    592 KB of SRAM and the kernel must not depend on an allocator being present.
//! 3. **No hidden state.** Determinism is the product: every random draw comes from
//!    `(seed, step)` and nothing else.

#![cfg_attr(not(test), no_std)]
#![forbid(unsafe_code)]

pub mod battle;
pub mod beat;
pub mod content;
pub mod exec;
pub mod expr;
pub mod hash;
pub mod host;
pub mod intent;
pub mod ir;
pub mod modifiers;
pub mod play;
pub mod rng;
pub mod sel;
pub mod snapshot;
pub mod state;
pub mod status_bind;
pub mod status_catalog;
pub mod targets;
pub mod turn;
pub mod writer;
