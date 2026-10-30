"""§155: the ABI for the elite relic reward, plus the relic pool it draws from.

* `roll_reward` now wants a `relic_pool`; `run.rs` builds it from `relic_candidates` (un-held relics)
  at the fight's payout -- the same list the chest and the shop use (§145), so a fight can never hand
  out a duplicate.
* Four exports, mirroring the potion pair: `rd_run_reward_relic_len/into` (display) and
  `rd_run_take_relic` (act). The page gets one more reward row and one more panel action.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-wasm\src\run.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()


def replace_once(old, new, why):
    global source
    if old not in source:
        raise SystemExit("anchor missing: " + why)
    source = source.replace(old, new, 1)


# ---- 1. pass the relic pool to roll_reward -----------------------------------------------------
replace_once(
    """        if let Err(e) = session
            .state
            .roll_reward(&pool, &potion_ids, fight_kind)
        {""",
    """        // §155: an elite (or boss) also pays a relic. `relic_pool` is the content's whole relic table;
        // `roll_reward` filters out the ones the player already holds (the same rule the chest and the
        // shop use), so a fight can never hand out a duplicate.
        let relic_ids = relic_pool(image);
        if let Err(e) = session
            .state
            .roll_reward(&pool, &potion_ids, &relic_ids, fight_kind)
        {""",
    "roll_reward call",
)

# ---- 2. the four exports ----------------------------------------------------------------------
ANCHOR = "/// Which act the run is on (1-based), or `-1` with no run."

EXPORTS = '''/// The relic the reward screen is offering (empty when none; §155: elites and bosses), for display.
#[no_mangle]
pub extern "C" fn rd_run_reward_relic_len() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    match session.state.reward_relic() {
        Some(id) => id.len() as i32,
        None => 0,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_reward_relic_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_reward_relic_into(ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    match session.state.reward_relic() {
        Some(id) => write_out(id, ptr),
        None => 0,
    }
}

/// Take the offered relic. Refuses when the table has none (`NoSuchRelic`) instead of silently
/// doing nothing -- a button that lies is the §150 shape.
#[no_mangle]
pub extern "C" fn rd_run_take_relic() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    let outcome = session.state.take_relic().map(|_| 0i32);
    finish(session, outcome)
}

'''

if "rd_run_reward_relic_len" not in source:
    at = source.find(ANCHOR)
    if at < 0:
        raise SystemExit("act anchor missing")
    source = source[:at] + EXPORTS + source[at:]

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("run.rs patched")
