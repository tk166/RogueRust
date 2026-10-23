//! Seven run-layer random substreams — the executable half of `docs/spec/run-layer.md` §3.
//!
//! # Why not one stream
//!
//! The kernel's randomness is stateless: everything is re-derived from `(seed, step)`
//! (`rd_core::rng` module docs). A single shared stream therefore couples **unrelated actions**:
//! drawing one potion advances the counter, and the next map node is rolled off a different point
//! of the same sequence. The result is not "a slightly different map" — it is that the
//! determinism regression ("same seed, same actions ⇒ same `run_hash` sequence") stops being able
//! to tell a generator bug from an unrelated extra draw, and a judgement that misfires once gets
//! ignored forever after.
//!
//! So: one stream per **domain**, each with its own counter. Advancing `Potion` cannot move `Map`.
//!
//! # The shape
//!
//! ```text
//! stream_seed(run_seed, stream)  =  run_seed ^ stream*GOLDEN32 ^ STREAM_MIX   (0 remapped)
//! draw(stream)                   ->  (that seed, counter[stream])   then counter[stream] += 1
//! ```
//!
//! The derivation reuses `rd_core::rng::GOLDEN32` rather than restating the number, and the two
//! mixing constants are domain-separated from `rng::initial_state`'s `0xA5A5A5A5` so that `Map`'s
//! first step can never collide with "some fight's first shuffle".
//!
//! # What this is *not*
//!
//! It is **not** claimed to match Slay the Spire. The original's run RNG is a `Random` seeded from
//! the run seed; this is a Mulberry32-derived substream scheme of our own design. The only claims
//! made here are about **our own determinism**, and the tests below are written as such.

use rd_core::rng;

/// Domain separation for the stream-seed derivation.
///
/// Distinct from `rng::initial_state`'s `0xA5A5A5A5` on purpose: with the same mixing constant,
/// `Map` (stream 1) would land exactly on "the first step of a fight seeded with `run_seed`".
pub const STREAM_MIX: u32 = 0x5F35_6495;

/// Zero remap for a derived stream seed. Mulberry32 degenerates if the state ever sits at zero,
/// so a seed that lands there is replaced rather than used (`rng::initial_state` does the same).
pub const STREAM_ZERO_REMAP: u32 = 0x2545_F491;

/// Identifies one of the seven run-layer streams.
///
/// **There is no `stream 0`.** A zero-initialised `RunState` is a valid byte pattern, and if `0`
/// were a real stream then "never initialised" would read as "using `Map`". Encoding the streams
/// as an enum makes that unrepresentable in Rust, and [`RunStream::from_id`] rejects `0` for the
/// places where a stream arrives as a number (wire format, restored save).
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
#[repr(u8)]
pub enum RunStream {
    /// Map layout, node-type rolls, `?` room contents.
    Map = 1,
    /// One draw per fight entered: the fight's own seed. Combat internals then use the kernel's
    /// `(seed, step)` and never touch a run stream again.
    Combat = 2,
    /// Combat rewards: gold, the 3-card choice.
    Reward = 3,
    /// `?` room event selection. Unused in M1, reserved so the numbering is frozen.
    Event = 4,
    /// Potion drops. This is the stream §5.4 of the plan names as the counter-example.
    Potion = 5,
    /// Merchant stock. Unused in M1, reserved.
    Shop = 6,
    /// Chest type and relic pool.
    Chest = 7,
}

impl RunStream {
    /// How many streams there are. `RunRng`'s counter array is this wide.
    pub const COUNT: usize = 7;

    /// Every stream, in id order. Iterating this is the only supported way to be "complete".
    pub const ALL: [RunStream; RunStream::COUNT] = [
        RunStream::Map,
        RunStream::Combat,
        RunStream::Reward,
        RunStream::Event,
        RunStream::Potion,
        RunStream::Shop,
        RunStream::Chest,
    ];

    /// The stream's number, 1..=7. Used in `run_hash` and in any serialised form.
    #[must_use]
    pub const fn id(self) -> u8 {
        self as u8
    }

    /// Index into [`RunRng`]'s counter array.
    #[must_use]
    pub const fn index(self) -> usize {
        self as usize - 1
    }

    /// The spelling used in `run_hash` (`docs/spec/run-layer.md` §5.2 is the frozen order).
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            RunStream::Map => "map",
            RunStream::Combat => "combat",
            RunStream::Reward => "reward",
            RunStream::Event => "event",
            RunStream::Potion => "potion",
            RunStream::Shop => "shop",
            RunStream::Chest => "chest",
        }
    }

    /// Parse a stream number. `0` and anything above [`RunStream::COUNT`] are **errors**, never a
    /// default: a silent default here is exactly the "zero-initialised state looks initialised"
    /// failure.
    pub fn from_id(id: u8) -> Result<Self, RunError> {
        match id {
            1 => Ok(RunStream::Map),
            2 => Ok(RunStream::Combat),
            3 => Ok(RunStream::Reward),
            4 => Ok(RunStream::Event),
            5 => Ok(RunStream::Potion),
            6 => Ok(RunStream::Shop),
            7 => Ok(RunStream::Chest),
            other => Err(RunError::BadStream(other)),
        }
    }
}

/// Errors the run layer raises instead of guessing.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum RunError {
    /// A stream number that is not 1..=7 (`0` included).
    BadStream(u8),
    /// A counter reached `i32::MAX`. Unreachable in practice (2^31 draws on one stream), but a wrap
    /// would silently rewind the stream, so it is checked rather than assumed.
    CounterExhausted(RunStream),
    /// `roll(stream, 0)` — a zero-sized range is a content bug. Returning `0` would look like a
    /// legitimate roll.
    EmptyRange,
    /// Map generation could not satisfy `inv:§7`'s override rules within `MAX_ATTEMPTS`.
    ///
    /// Deliberately an error and not "a slightly looser map": relaxing a rule is the silent
    /// failure this project keeps paying for, and a map is generated once per run, so a red here
    /// is cheap and visible.
    MapGeneration,
    /// A fixed-capacity container is full (`docs/spec/run-layer.md` §4.4).
    ///
    /// **Never** a truncation. StS decks grow past sixty cards in the late game, so the bound is a
    /// capacity and the honest failure is a red, not a dropped card.
    Capacity,
    /// An id that is not ASCII, or longer than `rd_core::state::ID_CAP`.
    BadId,
    /// `RunState::enter_node` was handed a node that is not an edge out of the current one.
    NotReachable,
    /// A global node index that is not on the map.
    BadNode,
    /// A per-step invariant was violated (`run-layer.md` §6.2). The string names which one.
    Invariant(&'static str),
    /// The node the cursor stands on cannot be settled by this build.
    ///
    /// `inv:§7.2` has eight node kinds; M1 settles four (`Combat`, `Rest`, `Shop`, `Treasure`).
    /// `Elite` and `Unknown` are named in the milestone as "not in M1", so reaching one is an error
    /// rather than a silent walk-past -- the whole point of `env-abi.md` §11.5 saying the map page
    /// only *walks*.
    NodeNotSettleable(u8),
    /// An action that does not fit what the current node is waiting for (paying at a rest site,
    /// resting in a shop, ...). Never a silent no-op: an out-of-order action is a caller bug.
    WrongPhase,
    /// Not enough gold for the purchase.
    NotEnoughGold { price: i32, gold: i32 },
    /// A slot that holds nothing (already bought, or past the end of the stock).
    EmptyOffer(u8),
    /// A card index that is not in the deck.
    BadCard(u8),
    /// A pool the content-side caller handed in that is empty, where the mechanic needs one.
    EmptyPool(&'static str),
    /// A pool too small to fill a reward screen with **distinct** cards (`inv:§3.5`: three, all
    /// different). Silently repeating a card would be a reward you cannot pick twice by accident.
    PoolTooSmall { pool: usize, need: usize },
    /// The node under the cursor is already settled. A node pays once: without this, standing on a
    /// combat node and pressing "fight" again would farm it, and a rest site would heal for ever.
    NodeResolved,
    /// An event effect outside the closed vocabulary (`heal` / `gold` / `damage` / `max_hp` /
    /// `nothing`). The run layer applies effects it knows and refuses the rest: an event that does
    /// nothing because nobody implemented its effect is exactly the silent failure this project bans.
    UnsupportedEventEffect,
    /// The event under the cursor is not one the content declared.
    NoSuchEvent,
    /// You tried to walk on before settling the node you are standing on.
    ///
    /// Without this a caller could step onto a fight and immediately step onto the next node --
    /// skipping the fight, the shop, the campfire. It is a cheat at the keyboard and an exploit in
    /// an RL environment, and it was found by clicking.
    NodeNotSettled,
    /// A relic whose effect is not implemented (`RunState::end_of_combat`).
    ///
    /// **This is the loud boundary of the relic system.** Effects are implemented one at a time, by
    /// id; this kernel has no relic-program interpreter, so a relic it cannot run has to be an
    /// error rather than a relic that silently does nothing. `index` is its slot in `relics()`, so
    /// the caller can print the id.
    UnsupportedRelic { index: u8 },
}

/// The run's randomness: the run seed plus one counter per stream.
///
/// `Copy` and POD, like the rest of the project's state: it can be snapshotted, hashed and moved.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct RunRng {
    seed: i32,
    counters: [i32; RunStream::COUNT],
}

/// Derive a stream's seed from the run seed.
///
/// Takes [`RunStream`] rather than a number so that "stream 0" cannot be passed here at all.
#[must_use]
pub const fn stream_seed(run_seed: i32, stream: RunStream) -> i32 {
    let mixed = (run_seed as u32)
        ^ (stream as u32).wrapping_mul(rng::GOLDEN32)
        ^ STREAM_MIX;
    let mixed = if mixed == 0 { STREAM_ZERO_REMAP } else { mixed };
    mixed as i32
}

impl RunRng {
    /// A fresh run: every counter at zero.
    #[must_use]
    pub const fn new(seed: i32) -> Self {
        Self {
            seed,
            counters: [0; RunStream::COUNT],
        }
    }

    /// The run seed (not a stream seed — those are derived per draw).
    #[must_use]
    pub const fn seed(&self) -> i32 {
        self.seed
    }

    /// How many draws a stream has made so far.
    #[must_use]
    pub const fn counter(&self, stream: RunStream) -> i32 {
        self.counters[stream.index()]
    }

    /// Restore a counter (save/load and tests). **The only way to move a counter backwards**, which
    /// is why it is explicit and named.
    pub fn set_counter(&mut self, stream: RunStream, value: i32) {
        self.counters[stream.index()] = value;
    }

    /// All counters, in stream-id order. This is what `run_hash` prints.
    #[must_use]
    pub const fn counters(&self) -> &[i32; RunStream::COUNT] {
        &self.counters
    }

    /// Take a stream's current `(seed, step)` and advance that stream **by exactly one**.
    ///
    /// Advance-after-use, matching the combat kernel's shuffle (`state.rs`: "洗完
    /// `random_step += 1`"), so there is one convention in the project, not two.
    ///
    /// The increment is an `assert!`, not a `debug_assert!`: a bare wrapper would silently rewind
    /// the stream, and release builds are what run on the device.
    pub fn draw(&mut self, stream: RunStream) -> (i32, i32) {
        let index = stream.index();
        let step = self.counters[index];
        let next = step.wrapping_add(1);
        assert!(
            next > step,
            "run RNG counter for {stream:?} wrapped at {step}: the stream would silently rewind"
        );
        self.counters[index] = next;
        (stream_seed(self.seed, stream), step)
    }

    /// A value in `0..n`, drawn from `stream`.
    ///
    /// Uses the same two primitives the shuffle does (`initial_state` then `next_u32`) rather than
    /// a third mixing function. The modulo bias is real and tiny; the original has its own, so no
    /// statistical claim is made — distribution judgements must carry tolerances
    /// (`sts-act1-plan.md` §4 M1 criterion ③).
    pub fn roll(&mut self, stream: RunStream, n: u32) -> Result<u32, RunError> {
        if n == 0 {
            return Err(RunError::EmptyRange);
        }
        let (seed, step) = self.draw(stream);
        let mut state = rng::initial_state(seed, step);
        Ok(rng::next_u32(&mut state) % n)
    }

    /// Fill `out` with `0..len` shuffled by `stream`. Thin wrapper so callers never hand a stream
    /// seed around by hand.
    pub fn shuffle(&mut self, stream: RunStream, out: &mut [u8]) {
        let (seed, step) = self.draw(stream);
        rng::shuffle_indexes(out, seed, step);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// **R1a** (`run-layer.md` §3.6): pushing one stream leaves another stream's draw sequence
    /// byte-identical.
    ///
    /// This is the whole point of the substream scheme, and the failure it rules out is concrete:
    /// a shared counter makes "did you drink a potion" change the map. Note what it would take to
    /// pass with a shared counter — nothing, so it can only pass if the counters are separate.
    ///
    /// ⚠️ **R1b** (the same statement at the level of "the generated map is byte-identical") lands
    /// with the map generator; it cannot be written yet, and writing "R1 passes" without it would
    /// be reporting a test that does not exist.
    #[test]
    fn r1a_advancing_one_stream_does_not_move_another() {
        let mut quiet = RunRng::new(7);
        let mut noisy = RunRng::new(7);

        let mut expected = [(0i32, 0i32); 200];
        for slot in expected.iter_mut() {
            *slot = quiet.draw(RunStream::Map);
        }

        // The noisy run does 100 unrelated draws first.
        for _ in 0..100 {
            noisy.roll(RunStream::Potion, 100).unwrap();
        }
        assert_eq!(noisy.counter(RunStream::Potion), 100);
        assert_eq!(noisy.counter(RunStream::Map), 0, "Potion must not advance Map");

        for (index, want) in expected.iter().enumerate() {
            let got = noisy.draw(RunStream::Map);
            assert_eq!(got, *want, "map draw {index} moved after 100 potion draws");
        }
        assert_eq!(quiet.counter(RunStream::Map), 200);
        assert_eq!(noisy.counter(RunStream::Map), 200);
    }

    /// **R2**: the seven streams of one run seed are pairwise distinct and non-zero.
    ///
    /// A derivation that forgot to include `stream` would collapse all seven into one and this
    /// test is the only place that would notice.
    #[test]
    fn r2_the_seven_streams_are_pairwise_distinct() {
        for run_seed in [0i32, 1, 7, -1, i32::MIN, i32::MAX]
            .into_iter()
            .chain((0..58).map(|k| k * 7919 - 200_000))
        {
            let seeds: Vec<i32> = RunStream::ALL
                .iter()
                .map(|&stream| stream_seed(run_seed, stream))
                .collect();
            for (i, a) in seeds.iter().enumerate() {
                assert_ne!(*a, 0, "stream seed must never be 0 (run_seed {run_seed})");
                for b in seeds.iter().skip(i + 1) {
                    assert_ne!(
                        a, b,
                        "two streams share a seed for run_seed {run_seed}: the derivation \
                         ignores the stream number"
                    );
                }
            }
        }
    }

    /// The derivation is pinned by **literals**, not by re-running the formula: a test that
    /// recomputes `run_seed ^ stream*GOLDEN ^ MIX` passes for any edit that changes both sides.
    /// These seven numbers are `stream_seed(7, …)` and they may only change with a documented
    /// reason (every `run_hash` golden that exists would change with them).
    #[test]
    fn r2b_the_derivation_is_pinned_by_literals() {
        let expected = [
            (RunStream::Map, -1_056_826_069i32),
            (RunStream::Combat, 1_666_947_040),
            (RunStream::Reward, -2_053_961_287),
            (RunStream::Event, 669_549_174),
            (RunStream::Potion, 1_210_057_743),
            (RunStream::Shop, -361_120_060),
            (RunStream::Chest, 212_938_909),
        ];
        for (stream, want) in expected {
            assert_eq!(stream_seed(7, stream), want, "{stream:?}");
        }
    }

    /// **R3**: `draw` advances by exactly one, and hands back the **pre-increment** step.
    ///
    /// "Took the post-increment value" and "advanced twice" both keep the sequence self-consistent
    /// with itself, so only pinning the actual numbers catches them.
    #[test]
    fn r3_draw_advances_by_exactly_one_and_returns_the_pre_increment_step() {
        let mut rng_state = RunRng::new(12345);
        for expected_step in 0..5 {
            let (seed, step) = rng_state.draw(RunStream::Combat);
            assert_eq!(step, expected_step, "draw must return the pre-increment counter");
            assert_eq!(seed, stream_seed(12345, RunStream::Combat));
            assert_eq!(rng_state.counter(RunStream::Combat), expected_step + 1);
        }
        // Untouched streams stay at zero: `draw` must not advance the whole array.
        for stream in RunStream::ALL {
            if stream != RunStream::Combat {
                assert_eq!(rng_state.counter(stream), 0, "{stream:?} moved");
            }
        }
    }

    #[test]
    fn stream_zero_is_rejected_everywhere_it_can_be_represented() {
        assert_eq!(RunStream::from_id(0), Err(RunError::BadStream(0)));
        assert_eq!(RunStream::from_id(8), Err(RunError::BadStream(8)));
        for stream in RunStream::ALL {
            assert_eq!(RunStream::from_id(stream.id()), Ok(stream));
        }
        assert_eq!(RunStream::ALL.len(), RunStream::COUNT);
        // The ids are 1..=7 with no gaps: `run_hash` prints them and a gap would be a silent
        // renumbering of every stream after it.
        for (offset, stream) in RunStream::ALL.iter().enumerate() {
            assert_eq!(stream.id() as usize, offset + 1);
            assert_eq!(stream.index(), offset);
        }
    }

    #[test]
    fn roll_stays_in_range_and_zero_range_is_an_error() {
        let mut rng_state = RunRng::new(3);
        assert_eq!(rng_state.roll(RunStream::Chest, 0), Err(RunError::EmptyRange));
        // A failed roll must not consume a draw: `EmptyRange` is a content bug, and eating a step
        // would make the bug move every later roll.
        assert_eq!(rng_state.counter(RunStream::Chest), 0);

        let mut seen = [false; 100];
        for _ in 0..2000 {
            let value = rng_state.roll(RunStream::Map, 100).unwrap();
            assert!(value < 100);
            seen[value as usize] = true;
        }
        // 2000 draws over 100 buckets: missing one would mean the roll is not covering the range.
        assert!(seen.iter().all(|&hit| hit), "roll(100) never produced some value in 0..100");
    }

    #[test]
    fn shuffle_is_per_stream_and_deterministic() {
        let mut a = [0u8; 12];
        let mut b = [0u8; 12];
        let mut c = [0u8; 12];

        let mut one = RunRng::new(99);
        one.shuffle(RunStream::Reward, &mut a);
        let mut two = RunRng::new(99);
        two.shuffle(RunStream::Reward, &mut b);
        assert_eq!(a, b, "same seed and stream must give the same order");

        let mut three = RunRng::new(99);
        three.shuffle(RunStream::Chest, &mut c);
        assert_ne!(a, c, "two streams of one run must not shuffle identically");

        // A permutation, not just "some bytes".
        let mut sorted = a;
        sorted.sort_unstable();
        assert_eq!(sorted, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
    }

    #[test]
    fn counters_can_be_restored_so_a_save_is_a_counter_array() {
        let mut rng_state = RunRng::new(5);
        for _ in 0..3 {
            rng_state.draw(RunStream::Event);
        }
        let saved = *rng_state.counters();
        let mut restored = RunRng::new(5);
        for (offset, stream) in RunStream::ALL.iter().enumerate() {
            restored.set_counter(*stream, saved[offset]);
        }
        assert_eq!(restored, rng_state);
        assert_eq!(
            restored.draw(RunStream::Event),
            rng_state.draw(RunStream::Event),
            "a restored run must continue the same stream"
        );
    }
}
