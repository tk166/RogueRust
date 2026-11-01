"""§161.10 P0: the archive gets its **own** buffer with a published capacity.

The bug: `rd_run_archive_into(ptr)` wrote up to 16 KB into whatever pointer it was handed, and the
page handed it `rd_env_scratch_buf()` -- **1024 bytes**. A late-game run's archive is 1628 bytes
(measured: `a_full_deck_archive_is_bigger_than_the_generic_scratch`), so the write ran ~600 bytes
past the end of `SCRATCH` into the statics that follow it in linear memory. Both directions were
open: the page also pasted user text into the same 1 KiB buffer.

The fix is not "make SCRATCH bigger" (it is shared with every other `*_into` export, and the
contract there is "as long as `*_len()` said"). It is: the archive owns a buffer, the buffer's
capacity is part of the ABI, and the page checks **UTF-8 byte length** against it before writing.

Also here: `rd_run_start` clears the combat session. That is the root of the "stale session blocks
archiving" problem -- the guard belongs in the ABI (the authoritative layer), and it is only
reliable if a new run cannot leave a previous fight's session behind.
"""
import io

LIB = "kernel/rd-wasm/src/lib.rs"
RUN = "kernel/rd-wasm/src/run.rs"


def main():
    run = io.open(RUN, encoding="utf-8").read()

    # ---- 1. replace the two unsafe exports with three that publish a capacity ---------------
    old_start = run.index("/// How many bytes `rd_run_archive_into` will write; `-1` when there is no run, `-2` in a fight.")
    old_end = run.index("/// Restore a run from the archive in `(ptr, len)`.", old_start)
    new_block = '''/// The archive buffer's capacity, in bytes (§161.10).
///
/// Published so the host can check **before** it writes: `rd_run_archive_buf()` is exactly this
/// long, and `rd_run_restore_from` refuses a longer input. Without this the page had to guess, and
/// it guessed a 1 KiB scratch buffer shared with every other `*_into` export.
#[no_mangle]
pub extern "C" fn rd_run_archive_capacity() -> i32 {
    rd_run::state::archive::MAX_ARCHIVE as i32
}

/// The address of the archive buffer (`rd_run_archive_capacity()` bytes, owned by this module).
#[no_mangle]
pub extern "C" fn rd_run_archive_buf() -> *mut u8 {
    std::ptr::addr_of_mut!(ARCHIVE) as *mut u8
}

/// Fill the archive buffer and return its length; `-1` no run, `-2` refused with text.
///
/// ⚠️ 存档**不含战斗**（`CombatState`，213 KB、每场重建）。所以"战斗中不许存"这条判断在这里 ——
/// 权威状态所在的层 —— 而不是在页面里。它可靠的前提是"有战斗会话"确实等于"正在打"：
/// `rd_run_start` 现在会清掉上一场的会话（见那里），于是这个判据没有第二种含义。
#[no_mangle]
pub extern "C" fn rd_run_archive_fill() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if crate::slot().is_some() {
        set_error("战斗中没有存档：这份档案只描述整局，回档会让敌人满血。先打完这一场。");
        return -2;
    }
    // The buffer is ours and `MAX_ARCHIVE` long, so `write` cannot overflow it: it encodes INTO
    // it and a longer payload is `ArchiveError::TooLong`.
    #[allow(static_mut_refs)]
    let buffer = unsafe { &mut *std::ptr::addr_of_mut!(ARCHIVE) };
    match rd_run::state::archive::write(&session.state, buffer) {
        Ok(len) => len as i32,
        Err(error) => {
            set_error(&std::format!("存档写不出来：{error}"));
            -2
        }
    }
}

'''
    run = run[:old_start] + new_block + run[old_end:]

    # ---- 2. the restore refuses anything longer than the buffer ------------------------------
    old = '''pub unsafe extern "C" fn rd_run_restore_from(ptr: *const u8, len: i32) -> i32 {
    if ptr.is_null() || len <= 0 {
        return -3;
    }'''
    new = '''pub unsafe extern "C" fn rd_run_restore_from(ptr: *const u8, len: i32) -> i32 {
    if ptr.is_null() || len <= 0 {
        return -3;
    }
    // The capacity contract, enforced rather than assumed (§161.10).
    if len as usize > rd_run::state::archive::MAX_ARCHIVE {
        set_error("档案太长：超过 THIS 实现的缓冲容量");
        return -3;
    }'''
    assert run.count(old) == 1, run.count(old)
    run = run.replace(old, new)

    # ---- 3. the restore is the authoritative "no fight" guard too --------------------------
    old = '''    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    let mut restored = *session.state;'''
    new = '''    if crate::slot().is_some() {
        set_error("战斗中没有回档：先打完这一场，或者重开一局。");
        return -2;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    let mut restored = *session.state;'''
    assert run.count(old) == 1, run.count(old)
    run = run.replace(old, new)

    # ---- 4. a new run clears the previous fight's session ---------------------------------
    old = '''pub extern "C" fn rd_run_start(seed: i32, ascension: i32) -> i32 {'''
    new = '''pub extern "C" fn rd_run_start(seed: i32, ascension: i32) -> i32 {
    // §161.10: a new run **ends** any fight the previous one left behind. This is what makes
    // "a combat session exists" mean "a fight is in progress" -- without it, a page that starts a
    // new run mid-fight leaves the session alive and every later "no archiving in a fight" check
    // refuses forever, for a reason that is no longer true.
    crate::take_session();'''
    assert run.count(old) == 1, run.count(old)
    run = run.replace(old, new)

    io.open(RUN, "w", encoding="utf-8", newline="").write(run)

    # ---- 5. the buffer itself, in lib.rs next to SCRATCH ----------------------------------
    lib = io.open(LIB, encoding="utf-8").read()
    old = '''static mut SCRATCH: [u8; 1024] = [0; 1024];'''
    new = '''static mut SCRATCH: [u8; 1024] = [0; 1024];

/// The **archive** buffer (§161.10). Not the scratch one: an archive is up to 16 KiB (a 60-card
/// run measures 1628 B) and `SCRATCH` is 1024 B by contract, so handing the scratch pointer to the
/// archive export wrote past the end of it. One buffer per contract, and this one's length is
/// published (`rd_run_archive_capacity`).
static mut ARCHIVE: [u8; rd_run::state::archive::MAX_ARCHIVE] = [0; rd_run::state::archive::MAX_ARCHIVE];'''
    assert lib.count(old) == 1, lib.count(old)
    io.open(LIB, "w", encoding="utf-8", newline="").write(lib.replace(old, new))
    print("archive buffer + lifecycle fix")


if __name__ == "__main__":
    main()
