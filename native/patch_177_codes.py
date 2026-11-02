"""§177: a `StepThrew(Script)` must say **which** refusal it was.

`StepCause::Script` folds `BattleError::Deck(_)` and `BattleError::Play(_)` into one name, and
`Problem::StepThrew` carries nothing else -- so the page (and the plan) could only say "a script step
threw". The two `Play` refusals that matter for diagnosis are *which* card rule said no
(`Refused(Unplayable)` vs `Unaffordable{need,have}` vs `CardNotInHand`), and today that distinction is
destroyed at the point it is created.

This adds `FightOutcome.step_codes: [u8; MAX_STEPS]`, filled exactly like `step_capacity` already is,
plus one name table in the kernel (`play_code_name`) so the page can print a word instead of a number.

Codes (0 = none):
     1 NotOngoing      2 SourceUnavailable  3 UnknownCard        4 CardNotInHand
     5 Stunned         6 Unplayable         7 PlayConditionFalse 8 DecreeMaxCardsPerTurn
     9 DecreeNoLikeness                    10 OneAttackPerTurn
    11 MissingResource 12 Unaffordable     13 NegativePrintedCost
    14 Effect         15 UnsupportedContent 16 Capacity
    17 Deck
"""
import io

BATTLE = "kernel/rd-core/src/battle.rs"
WASM = "kernel/rd-wasm/src/lib.rs"

# ---------------------------------------------------------------- rd-core: the field + the codes

OLD_OUTCOME = """    pub step_capacity: [u8; MAX_STEPS],"""
NEW_OUTCOME = """    pub step_capacity: [u8; MAX_STEPS],
    /// §177: **which** `Deck`/`Play` refusal a step hit (`0` = none). `step_causes` says only
    /// "Script", which is exactly the level of detail that cannot be acted on: `Refused(Unplayable)`
    /// and `Unaffordable { need: 2, have: 1 }` are different bugs with the same family name.
    pub step_codes: [u8; MAX_STEPS],"""

OLD_INIT = """        step_capacity: [0; MAX_STEPS],"""
NEW_INIT = """        step_capacity: [0; MAX_STEPS],
        step_codes: [0; MAX_STEPS],"""

OLD_RECORD = """                    if let Some(slot) = out.step_capacity.get_mut(index) {
                        *slot = StepCause::capacity_code(&error);
                    }"""
NEW_RECORD = """                    if let Some(slot) = out.step_capacity.get_mut(index) {
                        *slot = StepCause::capacity_code(&error);
                    }
                    if let Some(slot) = out.step_codes.get_mut(index) {
                        *slot = play_code(&error);
                    }"""

OLD_IMPL = """impl From<crate::state::CapacityError> for BattleError {"""
NEW_IMPL = '''/// §177: the `u8` code for a `Deck`/`Play` refusal (see [`play_code_name`]). `0` for everything else.
///
/// One table, in the kernel: the page prints `play_code_name(code)` and never owns a second copy of
/// these numbers.
#[must_use]
pub fn play_code(error: &BattleError) -> u8 {
    let BattleError::Play(play_error) = error else {
        return match error {
            BattleError::Deck(_) => 17,
            _ => 0,
        };
    };
    match play_error {
        PlayError::NotOngoing => 1,
        PlayError::SourceUnavailable => 2,
        PlayError::UnknownCard => 3,
        PlayError::CardNotInHand => 4,
        PlayError::Refused(refusal) => match refusal {
            crate::play::Refusal::Stunned => 5,
            crate::play::Refusal::Unplayable => 6,
            crate::play::Refusal::PlayConditionFalse => 7,
            crate::play::Refusal::DecreeMaxCardsPerTurn { .. } => 8,
            crate::play::Refusal::DecreeNoLikeness { .. } => 9,
            crate::play::Refusal::OneAttackPerTurn => 10,
        },
        PlayError::MissingResource { .. } => 11,
        PlayError::Unaffordable { .. } => 12,
        PlayError::NegativePrintedCost { .. } => 13,
        PlayError::Effect(_) => 14,
        PlayError::UnsupportedContent(_) => 15,
        PlayError::Capacity(_) => 16,
    }
}

/// The name of a [`play_code`] value (`"none"` for `0`).
#[must_use]
pub fn play_code_name(code: u8) -> &'static str {
    match code {
        1 => "NotOngoing",
        2 => "SourceUnavailable",
        3 => "UnknownCard",
        4 => "CardNotInHand",
        5 => "Refused(Stunned)",
        6 => "Refused(Unplayable)",
        7 => "Refused(PlayConditionFalse)",
        8 => "Refused(DecreeMaxCardsPerTurn)",
        9 => "Refused(DecreeNoLikeness)",
        10 => "Refused(OneAttackPerTurn)",
        11 => "MissingResource",
        12 => "Unaffordable",
        13 => "NegativePrintedCost",
        14 => "Effect",
        15 => "UnsupportedContent",
        16 => "Capacity",
        17 => "Deck",
        _ => "none",
    }
}

impl From<crate::state::CapacityError> for BattleError {'''

# ---------------------------------------------------------------- rd-wasm: two exports

OLD_WASM_ANCHOR = """/// §174：**谁在行动**（`active_combatant_id`），写进 scratch，返回长度。`-1` = 没有会话。"""
NEW_WASM = '''/// §177：第 `index` 步的 `Deck`/`Play` 拒绝码（`0` = 没有），`-1` = 越界或没有会话。
///
/// `StepThrew(Script)` 只说了家族，而"哪一张牌、哪一条拒因"才是能动手的信息。
#[no_mangle]
pub extern "C" fn rd_env_step_code(index: i32) -> i32 {
    let Some(session) = slot().as_ref() else {
        return -1;
    };
    if index < 0 {
        return -1;
    }
    session
        .out
        .step_codes
        .get(index as usize)
        .map_or(-1, |code| i32::from(*code))
}

/// §177：拒绝码的名字，写进 scratch，返回长度（`play_code_name` 的那张表，内核里只有一份）。
#[no_mangle]
pub extern "C" fn rd_env_code_name_len(code: i32) -> i32 {
    let name = rd_core::battle::play_code_name(u8::try_from(code).unwrap_or(0));
    write_scratch(name.as_bytes()) as i32
}

/// # Safety
///
/// `ptr` must point at `rd_env_code_name_len(code)` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_env_code_name_into(code: i32, ptr: *mut u8) -> i32 {
    let len = rd_env_code_name_len(code);
    if len < 0 {
        return len;
    }
    std::ptr::copy_nonoverlapping(crate::SCRATCH.as_ptr(), ptr, len as usize);
    len
}

''' + OLD_WASM_ANCHOR


def main():
    text = io.open(BATTLE, encoding="utf-8").read()
    for old, new in [
        (OLD_OUTCOME, NEW_OUTCOME),
        (OLD_INIT, NEW_INIT),
        (OLD_RECORD, NEW_RECORD),
        (OLD_IMPL, NEW_IMPL),
    ]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(BATTLE, "w", encoding="utf-8", newline="").write(text)

    wasm = io.open(WASM, encoding="utf-8").read()
    assert wasm.count(OLD_WASM_ANCHOR) == 1
    io.open(WASM, "w", encoding="utf-8", newline="").write(wasm.replace(OLD_WASM_ANCHOR, NEW_WASM))
    print("step codes added (kernel table + two exports)")


if __name__ == "__main__":
    main()
