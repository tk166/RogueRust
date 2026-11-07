//! Deterministic randomness, ported 1:1 from `src/RogueDeck.Core/Combat/CombatRandom.cs`.
//!
//! The reference engine's entire persistent random state is **eight bytes**: a 32-bit seed and
//! a 32-bit step counter. Nothing is carried between draws - the state is re-derived from
//! `(seed, step)` every time - which is why a snapshot only has to store the step, and why two
//! runs that draw a different NUMBER of values diverge visibly instead of silently.
//!
//! The generator is Mulberry32. The one property a port must not "optimise" away: the shuffle
//! returns the whole Fisher-Yates pass, and callers that want a single element still have to run
//! all of it. Index 0 is the outcome of the full pass, not of one draw.

/// The 32-bit golden-ratio increment shared by Mulberry32 and the state mixing below.
///
/// `pub` because the run layer (`rd-run`) derives its **stream seeds** with the same increment
/// (`docs/spec/run-layer.md` §3.3). Exporting it is the alternative to a second copy of the
/// number: two copies of a constant is where drift starts.
pub const GOLDEN32: u32 = 0x9E37_79B9;

/// Derives the initial state from the run seed and the step counter.
///
/// `state = seed ^ (step * GOLDEN) ^ 0xA5A5A5A5`, with zero remapped to a fixed non-zero value
/// (Mulberry32 degenerates if the state ever sits at zero).
#[inline]
#[must_use]
pub const fn initial_state(seed: i32, step: i32) -> u32 {
    let s = (seed as u32) ^ (step as u32).wrapping_mul(GOLDEN32) ^ 0xA5A5_A5A5;
    if s == 0 {
        0x6D2B_79F5
    } else {
        s
    }
}

/// Advances the state and returns the next 32-bit output.
#[inline]
pub fn next_u32(state: &mut u32) -> u32 {
    *state = state.wrapping_add(GOLDEN32);
    let mut v = *state;
    v = (v ^ (v >> 16)).wrapping_mul(0x85EB_CA6B);
    v = (v ^ (v >> 13)).wrapping_mul(0xC2B2_AE35);
    v ^ (v >> 16)
}

/// **一次抽取**：`(seed, step)` → 一个 32 位数。纯函数 —— 不碰任何状态。
///
/// 与 [`shuffle_indexes`] 用同一份 `(seed, step)` 派生（`initial_state` + `next_u32`），
/// 所以"同一个种子 ⇒ 同一个序列"这条性质对**两种**随机都成立，而不是只有洗牌有。
#[inline]
#[must_use]
pub fn draw_u32(seed: i32, step: i32) -> u32 {
    let mut state = initial_state(seed, step);
    next_u32(&mut state)
}

/// Fills `out` with `0..out.len()` shuffled by `(seed, step)`.
///
/// The reference signature returns a freshly allocated `int[]`; this one writes into caller
/// storage so the kernel stays allocator-free. The sequence produced is identical.
///
/// Indexes are `u8`: a card pile of more than 255 entries is not a thing this game has, and the
/// differential test asserts the bound rather than trusting that claim.
pub fn shuffle_indexes(out: &mut [u8], seed: i32, step: i32) {
    let n = out.len();
    for (i, slot) in out.iter_mut().enumerate() {
        *slot = i as u8;
    }
    if n <= 1 {
        return;
    }
    let mut state = initial_state(seed, step);
    // Same loop as the reference: i descends from n-1 to 1, swapping with a value in [0, i].
    for i in (1..n).rev() {
        let j = (next_u32(&mut state) % (i as u32 + 1)) as usize;
        out.swap(i, j);
    }
}

/// §248：把**一堆元素本身**原地洗一遍（同一套 Fisher–Yates，同一本 `(seed, step)` 账）。
///
/// `shuffle_indexes` 回答的是"下标怎么重排"（它的输出是下标）；这里回答的是"元素序列本身"。
/// 两者共用 `initial_state`/`next_u32`，所以**没有第二套洗牌算法** —— 只是元素类型不同。
pub fn shuffle_slots<T>(out: &mut [T], seed: i32, step: i32) {
    let n = out.len();
    if n <= 1 {
        return;
    }
    let mut state = initial_state(seed, step);
    for i in (1..n).rev() {
        let j = (next_u32(&mut state) % (i as u32 + 1)) as usize;
        out.swap(i, j);
    }
}

/// Convenience for the common "pick one element" case, spelled out so nobody short-circuits it.
#[must_use]
pub fn shuffled_pick_index(count: usize, seed: i32, step: i32) -> usize {
    // Capacity is fixed and small: a pile, not a deck library.
    let mut buf = [0u8; 255];
    let n = count.min(buf.len());
    shuffle_indexes(&mut buf[..n], seed, step);
    if n == 0 {
        0
    } else {
        buf[0] as usize
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn initial_state_matches_the_reference_formula() {
        // seed 0, step 0 -> 0 ^ 0 ^ 0xA5A5A5A5, not zero, so taken as-is.
        assert_eq!(initial_state(0, 0), 0xA5A5_A5A5);
        // A seed/step combination that lands on zero must be remapped, not returned.
        // 0xA5A5A5A5 = seed ^ (step * GOLDEN): pick seed = 0xA5A5A5A5, step = 0.
        assert_eq!(initial_state(0xA5A5_A5A5u32 as i32, 0), 0x6D2B_79F5);
    }

    #[test]
    fn identity_for_trivial_counts() {
        let mut one = [7u8; 1];
        shuffle_indexes(&mut one, 12345, 0);
        assert_eq!(one, [0]);

        let mut none: [u8; 0] = [];
        shuffle_indexes(&mut none, 1, 2); // must not panic
    }

    #[test]
    fn produces_a_permutation() {
        for &(n, seed, step) in &[(2usize, 1i32, 0i32), (10, 42, 3), (52, -7, 11), (255, 999, 1)] {
            let mut buf = [0u8; 255];
            shuffle_indexes(&mut buf[..n], seed, step);
            let mut seen = [false; 255];
            for &v in &buf[..n] {
                assert!(!seen[v as usize], "duplicate index {v} for n={n}");
                seen[v as usize] = true;
            }
        }
    }

    #[test]
    fn is_deterministic_and_step_sensitive() {
        let mut a = [0u8; 20];
        let mut b = [0u8; 20];
        shuffle_indexes(&mut a, 7, 4);
        shuffle_indexes(&mut b, 7, 4);
        assert_eq!(a, b, "same (seed, step) must give the same order");

        let mut c = [0u8; 20];
        shuffle_indexes(&mut c, 7, 5);
        assert_ne!(a, c, "a different step must give a different order");
    }
}
