"""P1-5: one way to read the script out, not two.

`rd_run_script_into(ptr)` writes `script_len()` bytes to a caller-supplied pointer with **no capacity
argument**: the `unsafe` contract says "you reserved enough", which is fine for a Rust caller and a
foot-gun for the wasm/JS boundary the ABI exists for. Its sibling `fill` / `buf` / `capacity` already
publishes the length before anything is written -- the pattern the archive learned in §161.10.

`into` and `len` are used by **nothing but the kernel's own tests**, and the page uses `fill`. So the
honest fix is not to add a capacity parameter to a test-only export: it is to delete both and let the
tests use the path the page uses. That also means the tests exercise the real ABI shape.

This patch: removes both exports, switches the three test call sites to `fill` + `buf`, and drops the
two names from `smoke.mjs`'s REQUIRED list (which is hand-copied twice by design).
"""
import io

RUN = "kernel/rd-wasm/src/run.rs"
SMOKE = "web/smoke.mjs"

OLD_EXPORTS = '''/// Length of the script as text (no buffer involved).
#[no_mangle]
pub extern "C" fn rd_run_script_len() -> i32 {
    match run_slot().as_mut() {
        Some(session) => {
            session.stamp();
            script_text(session).len() as i32
        }
        None => -1,
    }
}

/// # Safety
///
/// `ptr` must point at `rd_run_script_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_script_into(ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.stamp();
    let text = script_text(session);
    for (offset, &byte) in text.as_bytes().iter().enumerate() {
        *ptr.add(offset) = byte;
    }
    text.len() as i32
}

'''

NEW_EXPORTS = '''// §170 `P1-5`: 这里原来还有 `rd_run_script_len()` + `rd_run_script_into(ptr)` 一对 —— 和
// `fill`/`buf`/`capacity` 做的是同一件事，而 `into` 的 `unsafe` 契约是"你自己留够地方"：对 Rust
// 调用者成立，对 wasm/JS 那一侧就是一把对着脚的枪。它们唯一的用户是内核自己的测试，所以删掉它们、
// 让测试走页面走的那条路（`fill` + `buf` + `capacity`），而不是给一个只在测试里出现的导出加参数。
// 脚本接口现在只有一条路：**先问容量，再问长度，最后按长度读这个模块自己的缓冲区。**

'''

OLD_TEST_FIRST = '''        let script = {
            let len = rd_run_script_len();
            assert!(len > 0, "script_len said {len}");
            let mut buffer = vec![0u8; len as usize];
            unsafe { rd_run_script_into(buffer.as_mut_ptr()) };
            String::from_utf8(buffer).expect("ascii")
        };'''

NEW_TEST_FIRST = '''        let script = script_text_now();'''

OLD_TEST_OTHER = '''        let steps_after_restore = {
            let mut buffer = vec![0u8; rd_run_script_len() as usize];
            unsafe { rd_run_script_into(buffer.as_mut_ptr()) };
            String::from_utf8(buffer).expect("ascii")
        };'''

NEW_TEST_OTHER = '''        let steps_after_restore = script_text_now();'''

OLD_TEST_THIRD = '''        let script = {
            let mut buffer = vec![0u8; rd_run_script_len() as usize];
            unsafe { rd_run_script_into(buffer.as_mut_ptr()) };
            String::from_utf8(buffer).expect("ascii")
        };'''

NEW_TEST_THIRD = '''        let script = script_text_now();'''

OLD_TEST_FOURTH = '''        let after = {
            let mut buffer = vec![0u8; rd_run_script_len() as usize];
            unsafe { rd_run_script_into(buffer.as_mut_ptr()) };
            String::from_utf8(buffer).expect("ascii")
        };'''

NEW_TEST_FOURTH = '''        let after = script_text_now();'''

OLD_HELPER = '''    /// 头部按 `,` 切成字段，**去掉 `RDR1,` 前缀**'''

NEW_HELPER = '''    /// The script, read the way the **page** reads it: ask the capacity, fill the module's buffer, read
    /// `len` bytes. §170 `P1-5` deleted the `into(ptr)` variant that the tests used to call, so this
    /// helper keeps the tests on the one path that ships.
    fn script_text_now() -> String {
        let len = rd_run_script_fill();
        assert!(len > 0, "script_fill said {len}: {}", run_error_text());
        let capacity = rd_run_script_capacity();
        assert!(len <= capacity, "{len} > capacity {capacity}");
        let ptr = rd_run_script_buf();
        String::from_utf8(unsafe { std::slice::from_raw_parts(ptr, len as usize).to_vec() })
            .expect("ascii")
    }

    /// 头部按 `,` 切成字段，**去掉 `RDR1,` 前缀**'''

OLD_SMOKE = '''  "rd_run_script_len", "rd_run_script_into", "rd_run_script_fill",'''
NEW_SMOKE = '''  "rd_run_script_fill",'''


def main():
    for path, pairs in [
        (RUN, [
            (OLD_EXPORTS, NEW_EXPORTS),
            (OLD_TEST_FIRST, NEW_TEST_FIRST),
            (OLD_TEST_OTHER, NEW_TEST_OTHER),
            (OLD_TEST_THIRD, NEW_TEST_THIRD),
            (OLD_TEST_FOURTH, NEW_TEST_FOURTH),
            (OLD_HELPER, NEW_HELPER),
        ]),
        (SMOKE, [(OLD_SMOKE, NEW_SMOKE)]),
    ]:
        text = io.open(path, encoding="utf-8").read()
        for old, new in pairs:
            assert text.count(old) == 1, (path, text.count(old), old[:60])
            text = text.replace(old, new)
        io.open(path, "w", encoding="utf-8", newline="").write(text)
    print("P1-5: script_into / script_len removed; tests use fill+buf")


if __name__ == "__main__":
    main()
