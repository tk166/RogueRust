"""P0-1: no borrow of the session may span a call to another export.

The defect (found by external review, verified by reading the code): `rd_run_replay_from` bound
`let Some(session) = run_slot().as_mut()`, set `replaying`, and then **inside the loop** called
`rd_run_step` / `rd_run_begin_node` / ... -- each of which takes the slot again. The error branches
(bad record shape, unknown kind, bad arguments) still used the outer binding, so two `&mut` to the
same `RunSession` were live at once: UB on the aliasing model, and it falsified the soundness note on
the slot.

Fix: the outer binding is gone. `replaying` is set in a scope that ends immediately; every refusal
uses the existing `session_clear_replay()`; the hash comparison keeps its own short borrow.
"""
import io

LIB = "kernel/rd-wasm/src/lib.rs"
RUN = "kernel/rd-wasm/src/run.rs"

OLD_LIB_NOTE = """/// The session slot.
///
/// `wasm32-unknown-unknown` here is single-threaded, no export re-enters another export, and the
/// value lives in the module's BSS for the module's whole lifetime — so a `static mut` with one
/// accessor is sound. (This is the only `unsafe` in the crate besides the raw-pointer writes.)"""

NEW_LIB_NOTE = """/// The session slot.
///
/// `wasm32-unknown-unknown` here is single-threaded and the value lives in the module's BSS for the
/// module's whole lifetime, so a `static mut` with one accessor is sound — **provided no borrow is
/// held across a call**.
///
/// ⚠️ One export **does** re-enter others: `rd_run_replay_from` replays a script by calling the
/// ordinary exports. So the old phrasing of this note ("no export re-enters another export") was
/// false — and false in the worst place, as the stated reason the aliasing was fine. The rule that
/// replaces it:
///
/// > **Never hold a `&`/`&mut` from the slot across a call to another export.** Borrow, use, drop,
/// > call. `rd_run_replay_from` is where this matters, and it is written that way.
///
/// (Found by an external review of `5c467b6`: the code worked, but it was UB by the aliasing model.)"""

OLD_RUN_NOTE = """/// The run slot. Same argument as `lib.rs::slot()`: single-threaded wasm, no export re-enters
/// another export, the value lives in BSS for the module's lifetime."""

NEW_RUN_NOTE = """/// The run slot. Same argument as `lib.rs::slot()` — and the same rule: **no borrow may span a call
/// to another export**, because `rd_run_replay_from` re-enters this one on purpose."""

OLD_HEAD = """    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.replaying = true;

    let mut checked = 0usize;
    for (index, record) in rest.split(';').enumerate() {
        if record.is_empty() {
            continue;
        }
        let cells: std::vec::Vec<&str> = record.split(',').collect();
        if cells.len() < 4 {
            session.replaying = false;
            session.replay_checked = checked;
            session.replay_diverged = (index + 1) as i32;
            set_error(&std::format!("第 {} 步的格式不对", index + 1));
            return (index + 1) as i32;
        }
        let Some(kind) = rec_kind_from_name(cells[0]) else {
            session.replaying = false;
            session.replay_checked = checked;
            session.replay_diverged = (index + 1) as i32;
            set_error(&std::format!("第 {} 步的种类 `{}` 不认识", index + 1, cells[0]));
            return (index + 1) as i32;
        };
        let (Ok(a), Ok(b), Ok(want)) = (
            cells[1].parse::<i32>(),
            cells[2].parse::<i32>(),
            u64::from_str_radix(cells[3], 16),
        ) else {
            session.replaying = false;
            session.replay_checked = checked;
            session.replay_diverged = (index + 1) as i32;
            set_error(&std::format!("第 {} 步的参数不是整数", index + 1));
            return (index + 1) as i32;
        };"""

NEW_HEAD = """    // ⚠️ **No `let session = run_slot()` may live across the loop body.** It calls other exports,
    // and each of those takes the slot again (`lib.rs::slot()` states the rule). The flag is set in
    // a scope that ends here; every refusal borrows only for the length of one helper call.
    if let Some(session) = run_slot().as_mut() {
        session.replaying = true;
    } else {
        return -1;
    }

    let mut checked = 0usize;
    for (index, record) in rest.split(';').enumerate() {
        if record.is_empty() {
            continue;
        }
        let cells: std::vec::Vec<&str> = record.split(',').collect();
        if cells.len() < 4 {
            session_clear_replay(checked, (index + 1) as i32);
            set_error(&std::format!("第 {} 步的格式不对", index + 1));
            return (index + 1) as i32;
        }
        let Some(kind) = rec_kind_from_name(cells[0]) else {
            session_clear_replay(checked, (index + 1) as i32);
            set_error(&std::format!(
                "第 {} 步的种类 `{}` 不认识",
                index + 1,
                cells[0]
            ));
            return (index + 1) as i32;
        };
        let (Ok(a), Ok(b), Ok(want)) = (
            cells[1].parse::<i32>(),
            cells[2].parse::<i32>(),
            u64::from_str_radix(cells[3], 16),
        ) else {
            session_clear_replay(checked, (index + 1) as i32);
            set_error(&std::format!("第 {} 步的参数不是整数", index + 1));
            return (index + 1) as i32;
        };"""


def main():
    for path, old, new in [
        (LIB, OLD_LIB_NOTE, NEW_LIB_NOTE),
        (RUN, OLD_RUN_NOTE, NEW_RUN_NOTE),
        (RUN, OLD_HEAD, NEW_HEAD),
    ]:
        body = io.open(path, encoding="utf-8").read()
        assert body.count(old) == 1, (path, body.count(old), old[:60])
        io.open(path, "w", encoding="utf-8", newline="").write(body.replace(old, new))
    print("P0-1: no borrow spans an export call; both soundness notes corrected")


if __name__ == "__main__":
    main()
