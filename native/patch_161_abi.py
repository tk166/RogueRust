"""rd-wasm: the §161.3 choice exports + the two potion atoms that open a choice.

`rd_env_use_potion` is in `run.rs`; the exports are in `lib.rs`, next to the pile readers.
"""
import io

LIB = "kernel/rd-wasm/src/lib.rs"
RUN = "kernel/rd-wasm/src/run.rs"


def sub(path, text, old, new):
    assert text.count(old) == 1, (path, text.count(old), old[:70])
    return text.replace(old, new)


EXPORTS = """
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
        return refuse("待决选牌的战斗员没有牌区");
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
        return refuse("牌的槽位表与卡池不一致：选牌清单不完整");
    }
    let mut picks: Vec<rd_core::state::CardInstanceId> = Vec::with_capacity(session.choice_picks.len());
    let mut wanted = session.choice_picks.clone();
    wanted.sort_unstable();
    wanted.dedup();
    for index in wanted {
        let Some(id) = ids.get(index) else {
            return refuse(&std::format!("选项 {index} 不存在"));
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
        Err(e) => refuse(&std::format!("选牌被拒：{e}")),
    }
}
"""


def main():
    lib = io.open(LIB, encoding="utf-8").read()
    run = io.open(RUN, encoding="utf-8").read()

    assert "pub extern \"C\" fn rd_env_choice_pending" not in lib, "already inserted"

    anchor = """fn pile_card_id(zone: i32, index: i32) -> Option<&'static str> {"""
    lib = sub(LIB, lib, anchor, EXPORTS.strip() + "\n\n" + anchor)

    # ---- the import rd-core names the exports use ----
    anchor = "use rd_core::state::{"
    assert lib.count(anchor) == 1
    lib = sub(LIB, lib, anchor, anchor + "ChoiceThen, ")

    # ---- the two potion atoms -------------------------------------------------------------
    anchor = """        other if other.starts_with("combat_status") => {"""
    atoms = """        "choice_hand_exhaust" | "choice_hand_discard_draw" => {
            // §161.3: these two do not resolve here -- they **ask a question**. The bottle is
            // consumed by the tail below (the wiki's potion is drunk either way), and the fight
            // stays modal until `rd_env_choice_confirm`.
            let then = if atom == "choice_hand_exhaust" {
                rd_core::state::ChoiceThen::Exhaust
            } else {
                rd_core::state::ChoiceThen::DiscardThenDraw
            };
            let Some(zones) = session.state.card_zones(&hero) else {
                return refuse("英雄没有牌区");
            };
            let hand = zones.count(rd_core::state::CardZone::Hand);
            if hand == 0 {
                // An empty hand means the question has no answers. Asking it anyway would put an
                // empty picker on screen whose only option is "confirm nothing" -- a modal that
                // exists to say the potion did nothing.
                continue;
            }
            let question = rd_core::state::PendingChoice {
                chooser: hero.clone(),
                source: rd_core::state::ChoiceSource::Hand,
                min: 0,
                max: hand.min(u8::MAX as usize) as u8,
                then,
            };
            if let Err(e) = session.state.begin_choice(question) {
                return refuse(&std::format!("这次选牌问不出口：{e}"));
            }
            session.choice_picks.clear();
        }
        other if other.starts_with("combat_status") => {"""
    run = sub(RUN, run, anchor, atoms)

    io.open(LIB, "w", encoding="utf-8", newline="").write(lib)
    io.open(RUN, "w", encoding="utf-8", newline="").write(run)
    print("rd-wasm: choice exports + potion atoms")


if __name__ == "__main__":
    main()
