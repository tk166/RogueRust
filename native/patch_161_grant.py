"""rd-wasm: teach `rd_run_potion_effect` the two choice atoms, pin the vocabulary with a test,
and add the debug potion grant that makes a browser scenario possible at all.

Why the classifier test exists: adding `choice_hand_exhaust` produced a potion that the kernel
drinks and the page classifies as `0 = unknown`. Nothing would have gone red -- the page's
`=== 1` check simply took the other branch. The tripwire is "every POT row classifies non-zero",
not "the atom I added is in the list".
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"


def sub(text, old, new):
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)


def main():
    text = io.open(PATH, encoding="utf-8").read()

    # ---- 1. the classifier learns the two choice atoms ---------------------------------------
    text = sub(
        text,
        """        let known = kind == "combat_damage"
            || kind == "combat_damage_all"
            || kind == "heal"
            || matches!(kind, "max_hp" | "potion_fill")
            || ["combat_block", "combat_energy", "combat_heal_percent", "combat_draw"]
                .contains(&kind)
            || kind.starts_with("combat_status");""",
        """        // §161.3: the choice atoms act on the **hand**, so they need no enemy target (they fall
        // into the `2` branch below). Adding them here is not bookkeeping: without this line
        // `rd_run_potion_effect` answered `0` -- "unknown effect" -- for a potion the kernel drinks
        // happily, and the only reason nothing broke is that the page's `=== 1` check took the
        // other branch. `every_potion_in_the_table_classifies_as_known` is the tripwire for the
        // next atom that gets added to `rd_env_use_potion` and forgotten here.
        let known = kind == "combat_damage"
            || kind == "combat_damage_all"
            || kind == "heal"
            || matches!(
                kind,
                "max_hp"
                    | "potion_fill"
                    | "choice_hand_exhaust"
                    | "choice_hand_discard_draw"
            )
            || ["combat_block", "combat_energy", "combat_heal_percent", "combat_draw"]
                .contains(&kind)
            || kind.starts_with("combat_status");""",
    )

    # ---- 2. the debug grant -------------------------------------------------------------------
    anchor = """/// Can potion `slot` be used **outside** a fight? `-1` = no such slot, `0` = run-only (yes),"""
    grant = '''/// Put potion `id` on the belt. **For tests and the page's `?debug` surface only.**
///
/// There is no in-game caller: every real potion arrives through a drop (`roll_reward` ->
/// `take_potion`) or through `entropic_brew`. This exists for the same reason
/// `RD_DEBUG.startWithSeed` does -- a checker that has to hope for a 40% drop of one specific
/// potion out of **twenty-two** is not a checker, and the §161.3 card-choice picker is reachable
/// through exactly **two** of those twenty-two. Before this, the picker could only be exercised by
/// a unit test that stuffed the belt from inside the crate.
///
/// It is deliberately **not** behind a `cfg`: a debug gate would mean the shipped `.wasm` and the
/// tested one are different binaries, which is a worse problem than a cheat entry point.
///
/// `0` granted, `-1` no run / bad pointer, `-2` refused (unknown id, or the belt is full).
///
/// # Safety
///
/// `ptr` must point at `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_grant_potion(ptr: *const u8, len: i32) -> i32 {
    if ptr.is_null() || len <= 0 {
        return -1;
    }
    let bytes = std::slice::from_raw_parts(ptr, len as usize);
    let Ok(id) = std::str::from_utf8(bytes) else {
        return -2;
    };
    let image = content();
    // The id must be a real `POT` row: a typo has to fail here rather than sit in the belt until
    // somebody drinks it and the effect reader says "unknown".
    if !(0..image.potion_count())
        .filter_map(|index| image.potion(index))
        .any(|potion| potion.id == id)
    {
        return set_error(&std::format!("`{id}` 不是内容的 POT 行"));
        return -2;;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    match session.state.push_potion(id) {
        Ok(()) => {
            // The belt is what the top bar draws, so the observation is stale the moment this
            // returns -- same reason a used potion re-publishes.
            crate::rd_env_reobserve_after_external_change();
            0
        }
        Err(e) => {
            set_error(&std::format!("放不进腰带：{e:?}"));
            -2
        }
    }
}

'''
    text = sub(text, anchor, grant + anchor)

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("run.rs: classifier + debug grant")


if __name__ == "__main__":
    main()
