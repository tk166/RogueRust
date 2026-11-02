"""§172: per-round source file, plus the review's P2-1 requirements.

Two things the review asked for, both about the negative control itself:

1. **"exit != 0" is not "the expected assertion fired"** -- a compile error, a bad cargo path or an
   unrelated panic all look identical to a caught regression. So each round now checks:
     * the *same* test passes **before** the mutation (GREEN baseline);
     * after the mutation the build succeeds, the test **ran** (`test result:` line present), the
       result is `FAILED`, and the output names the test and a panic;
2. **rounds may target different files** -- the fixture-completeness control lives in
   `rd-run/src/hash.rs`, not in `rd-wasm/src/run.rs`.

Also: the cargo path can be overridden with `$CARGO` and the target dir with `$CARGO_TARGET_DIR`, so a
different machine does not need edits to this file.
"""
import io
import os
import re
import subprocess
import sys

WASM = "kernel/rd-wasm/src/run.rs"
HASH = "kernel/rd-run/src/hash.rs"
CARGO = os.environ.get("CARGO") or os.path.join(
    os.environ.get("USERPROFILE", r"C:\Users\TK11"), ".cargo", "bin", "cargo.exe")
TARGET = os.environ.get("CARGO_TARGET_DIR") or "D:/Vibe/sts-tui/kernel/target-mine"

# (label, file, old, new, test-that-must-catch-it)
ROUNDS = [
    (
        "P1-2 re-entry guard",
        WASM,
        '''    if session.in_fight {
        return fail(session, "这一场已经开始了：先打完它，或者重开一局");
    }''',
        '''    // [negctl] if session.in_fight { return fail(session, "…"); }''',
        "a_second_fight_begin_is_refused",
    ),
    (
        "P1-3 script_fill guard",
        WASM,
        '''    if session.in_fight {
        set_error("战斗中没有脚本：一场战斗只有**结果**进脚本，先打完这一场。");
        return -2;
    }''',
        '''    // [negctl] script_fill in_fight guard removed''',
        "the_script_abi_refuses_mid_fight",
    ),
    (
        "P1-3 replay guard",
        WASM,
        '''    if run_slot().as_ref().is_some_and(|session| session.in_fight) {
        set_error("战斗中不能回放：回放会从开局重跑这一局，把这场战斗扔掉。");
        return -2;
    }''',
        '''    // [negctl] replay in_fight guard removed''',
        "the_script_abi_refuses_mid_fight",
    ),
    (
        "P1-4 hash_failed guard",
        WASM,
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
        WASM,
        '''    *session.state = before;
    session.elite_fight = false;
    session.boss_fight = false;
    session.in_fight = false;''',
        '''    // [negctl] rollback removed: keep the moved state and the flags''',
        "fail_begin_restores_the_snapshot",
    ),
    (
        # §172: the bug the review found in my own test -- a swallowed `push_relic`.
        "§172 fixture completeness",
        HASH,
        '''        for relic in relics {
            state
                .push_relic(relic)
                .unwrap_or_else(|error| panic!("pushing relic {relic} must work: {error:?}"));
        }''',
        '''        for relic in relics {
            // [negctl] the shape of the bug this replaced: an id the rule table refuses, swallowed.
            // 只把 `let _` 换回来是**抓不到**的 —— 新夹具的 id 已经过滤，所以那样推一定成功。
            // 能抓住原 bug 的是数量断言，所以变异要让"推动的部分比自称的少"。
            let _ = state.push_relic("relic_that_does_not_exist");
            let _ = relic;
        }''',
        "the_largest_run_reachable",
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


def run_hash_test(name):
    result = subprocess.run(
        [CARGO, "test", "-p", "rd-run", name, "--release", "--target-dir", TARGET, "--",
         "--test-threads=1"],
        cwd="kernel",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def look(path, name):
    """The right cargo invocation for the crate that owns the test."""
    return run_hash_test(name) if path == HASH else run_test(name)


def verdict(path, name, out):
    """`caught` only when the **expected assertion** failed -- not merely a non-zero exit."""
    if "test result:" not in out:
        return False, "the test never ran (compile error or a bad invocation?)"
    if not re.search(r"test result: FAILED", out):
        return False, "the test did not fail"
    if name not in out:
        return False, f"the failing test is not {name}"
    if "panicked at" not in out:
        return False, "no panic: the failure was not an assertion"
    if re.search(r"^error\[E\d+\]", out, re.M):
        return False, "the build failed"
    return True, "the expected assertion fired"


def main():
    files = {}
    failures = 0
    try:
        # 1) GREEN baseline: every round's test must pass **before** anything is mutated.
        for label, path, _, _, test in ROUNDS:
            if path not in files:
                files[path] = io.open(path, encoding="utf-8").read()
            code, out = look(path, test)
            if code != 0 or "test result: ok" not in out:
                print(f"[BASE ] {label}: {test} does not pass before the mutation -- cannot "
                      f"conclude anything from it")
                failures += 1

        # 2) mutate one guard at a time, demand the expected assertion fires.
        for label, path, old, new, test in ROUNDS:
            original = files[path]
            assert original.count(old) == 1, (label, original.count(old))
            io.open(path, "w", encoding="utf-8", newline="").write(original.replace(old, new))
            try:
                code, out = look(path, test)
            finally:
                io.open(path, "w", encoding="utf-8", newline="").write(original)
            caught, why = verdict(path, test, out)
            print(f"[{'RED  ' if caught else 'GREEN'}] {label}: {test} -> "
                  f"{'caught' if caught else 'NOT CAUGHT'} ({why})")
            if not caught:
                failures += 1
    finally:
        for path, body in files.items():
            io.open(path, "w", encoding="utf-8", newline="").write(body)
        print("restored", ", ".join(files))

    if failures:
        print(f"{failures} round(s) inconclusive -- the negative control proves nothing about them")
        sys.exit(1)
    print("all negative controls fired, with their expected assertion")


if __name__ == "__main__":
    main()
