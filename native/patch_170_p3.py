"""P1-3: the script ABI inherits the archive's `in_fight` guard.

The archive learned this lesson in §161.10: "the page owns *don't archive mid-fight*" was wrong,
because the kernel is not the only caller and the page's `mode` is not a contract. `rd_run_archive_fill`
refuses while `in_fight`; `rd_run_script_fill` did not, and `rd_run_replay_from` did not either --
and a replay *restarts the run*, so an unguarded call destroys the fight in progress.

Both now refuse with the same rule, and the test below calls them with the fight running, i.e. the
way a page that forgot its own guard would.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

OLD_FILL = """pub extern "C" fn rd_run_script_fill() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.stamp();"""

NEW_FILL = """pub extern "C" fn rd_run_script_fill() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    // §170 `P1-3`: 与 `rd_run_archive_fill` 同一条规则，**在 ABI 里**，不是只在页面的 `mode` 里。
    // 一份战斗中导出的脚本一定缺一段（战斗只有结果进脚本），回放它必然分叉 —— 与其给出一份会
    // 分叉的脚本，不如在这里拒绝。
    if session.in_fight {
        set_error("战斗中没有脚本：一场战斗只有**结果**进脚本，先打完这一场。");
        return -2;
    }
    session.stamp();"""

OLD_REPLAY = """pub unsafe extern "C" fn rd_run_replay_from(ptr: *const u8, len: i32) -> i32 {
    // ⚠️ 先把两个读数清零，否则**拒绝路径**（解析失败、内容不同）会留下上一次回放的
    // "13 步全部对上"，页面于是一边报错一边显示绿灯 —— 度量报陈旧数字。
    session_clear_replay(0, 0);
    if ptr.is_null() || len <= 0 {
        return -2;
    }"""

NEW_REPLAY = """pub unsafe extern "C" fn rd_run_replay_from(ptr: *const u8, len: i32) -> i32 {
    // ⚠️ 先把两个读数清零，否则**拒绝路径**（解析失败、内容不同）会留下上一次回放的
    // "13 步全部对上"，页面于是一边报错一边显示绿灯 —— 度量报陈旧数字。
    session_clear_replay(0, 0);
    // §170 `P1-3`: 回放会**重新开一局**（`rd_run_start`），所以它会毁掉正在进行的战斗。
    // 这条守卫必须在 ABI 里 —— 调用者不只有那个记得住 `mode` 的页面。
    if run_slot().as_ref().is_some_and(|session| session.in_fight) {
        set_error("战斗中不能回放：回放会从开局重跑这一局，把这场战斗扔掉。");
        return -2;
    }
    if ptr.is_null() || len <= 0 {
        return -2;
    }"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in [(OLD_FILL, NEW_FILL), (OLD_REPLAY, NEW_REPLAY)]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("P1-3: script export and replay refuse mid-fight, at the ABI")


if __name__ == "__main__":
    main()
