"""§170 negative controls: take each new guard away and confirm the test notices.

A fix without a negative control is a claim. This script comments out one guard at a time, runs the
one test that is supposed to catch it, and restores the file. It prints the outcome of each round so
the result can go into the plan verbatim.

Rounds:
  1. drop the `in_fight` re-entry guard in `rd_run_fight_begin`
     -> `a_second_fight_begin_is_refused_and_the_fight_in_progress_survives` must FAIL
  2. drop the `in_fight` guard in `rd_run_script_fill`
     -> `the_script_abi_refuses_mid_fight_without_the_page` must FAIL
  3. drop the `in_fight` guard in `rd_run_replay_from`
     -> the same test must FAIL
  4. make `fail_begin` a no-op rollback (keep the flags)
     -> `fail_begin_restores_the_snapshot_and_clears_the_tier_flags` must FAIL
"""
import io
import subprocess
import sys

RUN = "kernel/rd-wasm/src/run.rs"
CARGO = r"C:\Users\TK11\.cargo\bin\cargo.exe"
TARGET = "D:/Vibe/sts-tui/kernel/target-mine"

ROUNDS = [
    (
        "P1-2 re-entry guard",
        '''    if session.in_fight {
        return fail(session, "这一场已经开始了：先打完它，或者重开一局");
    }''',
        '''    // [negctl] if session.in_fight { return fail(session, "…"); }''',
        "a_second_fight_begin_is_refused",
    ),
    (
        "P1-3 script_fill guard",
        '''    if session.in_fight {
        set_error("战斗中没有脚本：一场战斗只有**结果**进脚本，先打完这一场。");
        return -2;
    }''',
        '''    // [negctl] script_fill in_fight guard removed''',
        "the_script_abi_refuses_mid_fight",
    ),
    (
        "P1-3 replay guard",
        '''    if run_slot().as_ref().is_some_and(|session| session.in_fight) {
        set_error("战斗中不能回放：回放会从开局重跑这一局，把这场战斗扔掉。");
        return -2;
    }''',
        '''    // [negctl] replay in_fight guard removed''',
        "the_script_abi_refuses_mid_fight",
    ),
    (
        "P1-4 hash_failed guard",
        '''    if session.hash_failed {
        // §170 `P1-4`: 有一格哈希算不出来，这份脚本就**不能**导出去当证据用。
        set_error("导不出脚本：这一局的状态文本超出了哈希缓冲，逐步哈希对不上");
        return -2;
    }''',
        '''    // [negctl] hash_failed guard removed''',
        "an_unavailable_hash_is_refused",
    ),
    (
        "P1-1 rollback body",
        '''    *session.state = before;
    session.elite_fight = false;
    session.boss_fight = false;
    session.in_fight = false;''',
        '''    // [negctl] rollback removed: keep the moved state and the flags''',
        "fail_begin_restores_the_snapshot",
    ),
]


def run_test(name):
    result = subprocess.run(
        [CARGO, "test", "-p", "rd-wasm", name, "--release", "--target-dir", TARGET, "--",
         "--test-threads=1"],
        cwd="kernel",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def main():
    original = io.open(RUN, encoding="utf-8").read()
    failures = 0
    try:
        for label, old, new, test in ROUNDS:
            assert original.count(old) == 1, (label, original.count(old))
            io.open(RUN, "w", encoding="utf-8", newline="").write(original.replace(old, new))
            code, out = run_test(test)
            red = code != 0
            print(f"[{'RED  ' if red else 'GREEN'}] {label}: {test} exited {code}"
                  f"  -> {'caught' if red else 'NOT CAUGHT'}")
            if not red:
                failures += 1
                for line in out.splitlines():
                    if "test result" in line:
                        print("        " + line.strip())
    finally:
        io.open(RUN, "w", encoding="utf-8", newline="").write(original)
        print("restored the source")

    if failures:
        print(f"{failures} negative control(s) did not fire -- the test is not measuring the fix")
        sys.exit(1)
    print("all negative controls fired")


if __name__ == "__main__":
    main()
