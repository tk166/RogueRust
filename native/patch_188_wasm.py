"""§188 part 4: A15 as a run-layer constant, and the wasm side picks the list.

`A_EVENTS_WORSE = 15` sits next to the other nine `A_*` constants -- the ascension ladder is one
number per rule, and `at_least` is the only comparison (a rule is a threshold, not a range).

The ABI keeps its two old exports (`rd_run_event_effect(slot)` / `amount(slot)`) meaning **the first
effect**, so the page's existing chip keeps working, and adds the three that let it show the rest:
`count`, `effect_at`, `amount_at`.
"""
import io

# ---------------------------------------------------------------- the constant

STATE = "kernel/rd-run/src/state.rs"
ANCHOR = """/// The merchant charges 10% more.
pub const A_SHOP_PRICE: u8 = 16;"""
ADD = ANCHOR + """
/// \u00a7188\uff1a\u4e8b\u4ef6\u53d8\u5f97\u66f4\u7cdf\uff08wiki: *Unfavorable Events \u2014 many events have less positive outcomes
/// and more severe consequences*\uff09\u3002\u5185\u5bb9\u7528 `Effects*Asc` \u7ed9\u51fa\u53d8\u4f53\uff1b\u6ca1\u6709\u53d8\u4f53\u7684\u9009\u9879\u7167\u65e7\u3002
pub const A_EVENTS_WORSE: u8 = 15;"""

# ---------------------------------------------------------------- wasm: choose + apply + ABI

RUN = "kernel/rd-wasm/src/run.rs"

OLD_CHOOSE = """    let Some((effect, payload)) = effect_from(choice.effect, i32::from(choice.amount)) else {
        return -1;
    };
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_CHOOSE, slot, -1, "");
    let pool = match reward_pool(content()) {
        Ok(pool) => pool,
        Err(message) => return fail(session, &message),
    };
    let outcome = session
        .state
        .resolve_event(effect, payload, &pool)
        .map(|_| 0i32);
    finish(session, outcome)"""

NEW_CHOOSE = """    // \u00a7188\uff1a\u9009\u9879\u662f**\u4e00\u4e32**\u6548\u679c\uff0c\u800c A15\uff08\u4e8b\u4ef6\u53d8\u7cdf\uff09\u7ed9\u7684\u662f**\u53e6\u4e00\u4e32**\u3002
    let level = run_slot().as_ref().map_or(0, |s| s.state.ascension());
    let specs = choice.effects_at(level, rd_run::state::A_EVENTS_WORSE);
    let mut parsed: [(rd_run::state::EventEffect, Option<&'static str>); 8] = [
        (rd_run::state::EventEffect::Nothing, None);
        8
    ];
    if specs.len() > parsed.len() {
        return -1;
    }
    for (index, spec) in specs.iter().enumerate() {
        let named = spec.effect.split_once(':').map(|(_, payload)| payload);
        let Some((effect, _payload)) = effect_from(spec.effect, i32::from(spec.amount)) else {
            return -1;
        };
        // \u8f7d\u8377\uff08`curse:<id>` \u91cc\u7684 id\uff09\u5fc5\u987b\u6307\u5411 `'static`\uff1a\u5b83\u6765\u81ea\u955c\u50cf\u7684\u5b57\u7b26\u4e32\u6c60\uff0c\u800c\u6c60\u672c\u8eab\u662f
        // `Box::leak` \u51fa\u6765\u7684\u9759\u6001\u5185\u5b58\uff08\u89c1 `content()`\uff09\u3002
        parsed[index] = (effect, named);
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_CHOOSE, slot, -1, "");
    let pool = match reward_pool(content()) {
        Ok(pool) => pool,
        Err(message) => return fail(session, &message),
    };
    let outcome = session
        .state
        .resolve_event_effects(&parsed[..specs.len()], &pool)
        .map(|_| 0i32);
    finish(session, outcome)"""

OLD_ABI = """/// Choice `slot`'s effect, as the ABI's small integer: 1 heal, 2 gold, 3 lose health, 4 max health,
/// 5 nothing, `-1` unknown. A caller that sees `-1` must not guess.
#[no_mangle]
pub extern "C" fn rd_run_event_effect(slot: i32) -> i32 {
    let Some(choice) = event_choice(slot) else {
        return -1;
    };
    effect_code(choice.effect)
}

/// Choice `slot`'s amount.
#[no_mangle]
pub extern "C" fn rd_run_event_amount(slot: i32) -> i32 {
    event_choice(slot).map_or(0, |choice| i32::from(choice.amount))
}"""

NEW_ABI = """/// Choice `slot`'s **first** effect, as the ABI's small integer: 1 heal, 2 gold, 3 lose health,
/// 4 max health, 5 nothing, `-1` unknown. \u00a7188: an option is a **list** now, so this is the head of
/// it -- kept for the pages that only draw one chip; `rd_run_event_effect_at` walks the rest.
#[no_mangle]
pub extern "C" fn rd_run_event_effect(slot: i32) -> i32 {
    rd_run_event_effect_at(slot, 0)
}

/// Choice `slot`'s first effect's amount.
#[no_mangle]
pub extern "C" fn rd_run_event_amount(slot: i32) -> i32 {
    rd_run_event_amount_at(slot, 0)
}

/// \u00a7188: how many effects choice `slot` has **at this run's ascension** (A15 swaps the list).
#[no_mangle]
pub extern "C" fn rd_run_event_effect_count(slot: i32) -> i32 {
    let Some(choice) = event_choice(slot) else {
        return -1;
    };
    let level = run_slot().as_ref().map_or(0, |s| s.state.ascension());
    i32::from(choice.effects_at(level, rd_run::state::A_EVENTS_WORSE).len() as u8)
}

/// \u00a7188: effect `index` of choice `slot`, as the same small integer as `rd_run_event_effect`.
#[no_mangle]
pub extern "C" fn rd_run_event_effect_at(slot: i32, index: i32) -> i32 {
    let Some(spec) = event_effect_spec(slot, index) else {
        return -1;
    };
    effect_code_with_payload(spec.effect)
}

/// \u00a7188: effect `index` of choice `slot`'s amount.
#[no_mangle]
pub extern "C" fn rd_run_event_amount_at(slot: i32, index: i32) -> i32 {
    event_effect_spec(slot, index).map_or(0, |spec| i32::from(spec.amount))
}

/// Effect `index` of choice `slot` **for this run's ascension**.
fn event_effect_spec(slot: i32, index: i32) -> Option<rd_core::content::EffectSpec<'static>> {
    let choice = event_choice(slot)?;
    if index < 0 {
        return None;
    }
    let level = run_slot().as_ref().map_or(0, |s| s.state.ascension());
    let specs = choice.effects_at(level, rd_run::state::A_EVENTS_WORSE);
    specs.get(index as usize).copied()
}"""


def main():
    state = io.open(STATE, encoding="utf-8").read()
    if "A_EVENTS_WORSE" not in state:
        assert state.count(ANCHOR) == 1
        io.open(STATE, "w", encoding="utf-8", newline="").write(state.replace(ANCHOR, ADD))
        print("A_EVENTS_WORSE added")

    run = io.open(RUN, encoding="utf-8").read()
    for old, new, label in ((OLD_CHOOSE, NEW_CHOOSE, "choose"), (OLD_ABI, NEW_ABI, "abi")):
        if new in run:
            print("already applied:", label)
            continue
        assert run.count(old) == 1, (label, run.count(old))
        run = run.replace(old, new)
    io.open(RUN, "w", encoding="utf-8", newline="").write(run)
    print("wasm choose + ABI updated")


if __name__ == "__main__":
    main()
