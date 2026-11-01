"""§161.9 wasm: three exports for the archive, and a refusal while a fight is live.

`rd_run_archive_len()` / `rd_run_archive_into(ptr)` / `rd_run_restore_from(ptr, len)`.

The refusal matters as much as the feature: a fight is `CombatState`, which this archive does not
carry, so saving mid-fight would restore the *node* with the enemies at full health -- a save that
silently changes the fight is worse than no save. The page disables the button, and the ABI says
why.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """/// The relic the reward screen is offering (empty when none; §155: elites and bosses), for display."""

EXPORTS = '''/// How many bytes `rd_run_archive_into` will write; `-1` when there is no run, `-2` in a fight.
#[no_mangle]
pub extern "C" fn rd_run_archive_len() -> i32 {
    match archive_text() {
        Ok(text) => text.len() as i32,
        Err(code) => code,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_archive_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_archive_into(ptr: *mut u8) -> i32 {
    match archive_text() {
        Ok(text) => {
            for (offset, &byte) in text.as_bytes().iter().enumerate() {
                *ptr.add(offset) = byte;
            }
            text.len() as i32
        }
        Err(code) => code,
    }
}

/// The archive as one line, or the refusal code. `-2` = a fight is running.
///
/// ⚠️ 存档**不含战斗**（那是 `CombatState`，213 KB、每场重建）。战斗进行中写出来的东西只描述
/// 运行层，回档后敌人会满血 —— 那是一个**悄悄改掉战斗**的存档，比没有存档更糟。
fn archive_text() -> Result<std::string::String, i32> {
    let Some(session) = run_slot().as_ref() else {
        return Err(-1);
    };
    if crate::slot().is_some() {
        set_error("战斗中没有存档：这份档案只描述整局，回档会让敌人满血。先打完这一场。");
        return Err(-2);
    }
    let mut buffer = [0u8; rd_run::state::archive::MAX_ARCHIVE];
    match rd_run::state::archive::write(&session.state, &mut buffer) {
        Ok(len) => match std::str::from_utf8(&buffer[..len]) {
            Ok(text) => Ok(text.to_string()),
            Err(_) => Err(-3),
        },
        Err(_) => {
            set_error("存档写不出来（缓冲区不够）");
            Err(-3)
        }
    }
}

/// Restore a run from the archive in `(ptr, len)`. `0` ok, `-1` no run slot, `-2` refused, `-3` bad text.
///
/// **全有或全无**：`archive::restore` 先装到一个本地 `RunState` 上，最后一步才赋值，所以一份
/// 坏档案不会把当前这局改成半新半旧。
///
/// # Safety
///
/// `ptr` must point at `len` readable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_restore_from(ptr: *const u8, len: i32) -> i32 {
    if ptr.is_null() || len <= 0 {
        return -3;
    }
    let bytes = std::slice::from_raw_parts(ptr, len as usize);
    let Ok(text) = std::str::from_utf8(bytes) else {
        set_error("档案不是 UTF-8 文本");
        return -3;
    };
    // 战斗里回档会把"正在打的这一场"留在原地而整局换掉 —— 拒绝。
    if crate::slot().is_some() {
        set_error("战斗中没有回档：先打完这一场，或者重开一局。");
        return -2;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    let mut restored = session.state;
    match rd_run::state::archive::restore(text, &mut restored) {
        Ok(()) => {
            session.state = Box::new(restored);
            session.error.clear();
            0
        }
        Err(error) => {
            set_error(&std::format!("回档被拒：{error}"));
            -2
        }
    }
}

/// The relic the reward screen is offering (empty when none; §155: elites and bosses), for display.'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "rd_run_archive_len" not in text, "already inserted"
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, EXPORTS))
    print("rd-wasm: archive exports")


if __name__ == "__main__":
    main()
