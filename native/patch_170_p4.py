"""P1-4: `run_hash`'s capacity failure must not look like a hash.

Three call sites collapsed `None` into `0` -- `log()`'s lazy stamp, `stamp()`, and the replay's
comparison. `0` is a **legitimate comparable value**, so two states whose canonical text overflows
`MAX_TEXT` would both read `0` and the replay would call them equal: a false "matched".

Two things are needed, and they are different claims:

1. **Prove the bound** (`rd-run/src/hash.rs` test): the largest state the type allows must fit with
   room to spare. Nobody had measured it; it is not reachable from today's content, which is exactly
   why it has to be measured rather than assumed.
2. **Propagate the failure** (this file): the session remembers that a hash was unavailable, every
   consumer refuses **loudly**, and the replay distinguishes "no hash" from "hash differs".

The sentinel question is settled the way the review asked: `0` is never used as an error. A record
whose hash could not be computed keeps `0` in its 16-hex cell (the format is unchanged) but the session
carries `hash_failed`, and both the export and the replay refuse while it is set.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

# (1) the session flag, next to the other replay bookkeeping.
OLD_FIELDS = """    /// Where the last replay diverged (`0` = it did not).
    replay_diverged: i32,"""

NEW_FIELDS = """    /// §170 `P1-4`: 有过一次**算不出指纹**（规范文本超出 `run_hash` 的 `MAX_TEXT`）。
    ///
    /// 这一格存在的理由：哈希不可用时曾经被写成 `0`，而 `0` 是一个**合法可比较的值** —— 两个都溢出的
    /// 状态于是"相等"。现在不可用就记在这里，导出与回放都**响亮拒绝**，绝不拿 0 顶替。
    hash_failed: bool,"""

# (2) `log()`'s lazy stamp.
OLD_LOG = """        if let Some(last) = self.journal.last() {
            if last.hash == 0 {
                let hash = hash_prefix(&self.state).unwrap_or(0);
                if let Some(last) = self.journal.last_mut() {
                    last.hash = hash;
                }
            }
        }"""

NEW_LOG = """        if let Some(last) = self.journal.last() {
            if last.hash == 0 {
                // §170 `P1-4`: 算不出来就**记下来**，不写 0 假装算过。
                let hash = self.state_hash();
                if let Some(last) = self.journal.last_mut() {
                    last.hash = hash.unwrap_or(0);
                }
            }
        }"""

# (3) `stamp()`.
OLD_STAMP = """    fn stamp(&mut self) {
        if self.replaying {
            return;
        }
        let Some(last) = self.journal.last_mut() else {
            return;
        };
        last.hash = hash_prefix(&self.state).unwrap_or(0);
    }"""

NEW_STAMP = """    fn stamp(&mut self) {
        if self.replaying {
            return;
        }
        let hash = self.state_hash();
        let Some(last) = self.journal.last_mut() else {
            return;
        };
        // §170 `P1-4`: `None` 不再是"0"，是"这一局的文本算不出指纹"—— 记进会话，导出/回放拒绝。
        last.hash = hash.unwrap_or(0);
    }

    /// 当前状态的哈希前缀，`None` = 规范文本超出 `run_hash` 的缓冲。
    ///
    /// 唯一的取哈希入口：失败时**置** `hash_failed`，于是"算不出"这件事跟着会话走到每个消费者，
    /// 而不是被某个 `unwrap_or(0)` 咽掉。
    fn state_hash(&mut self) -> Option<u64> {
        let hash = hash_prefix(&self.state);
        if hash.is_none() {
            self.hash_failed = true;
        }
        hash
    }"""

# (4) the replay's comparison.
OLD_COMPARE = """        let Some(session) = run_slot().as_ref() else {
            return -1;
        };
        let now = hash_prefix(&session.state).unwrap_or(0);
        if now != want {"""

NEW_COMPARE = """        // §170 `P1-4`: "算不出哈希" 与 "哈希不一致" 是两件事，不能都折成一次比较失败。
        let now = match run_slot().as_mut().and_then(RunSession::state_hash) {
            Some(hash) => hash,
            None => {
                session_clear_replay(checked, (index + 1) as i32);
                set_error(&std::format!(
                    "第 {} 步之后算不出指纹：这一局的状态文本超出了哈希缓冲，无法逐步对拍",
                    index + 1
                ));
                return -2;
            }
        };
        if now != want {"""

# (5) the export refuses while the flag is set.
OLD_FILL_GUARD = """    if session.in_fight {
        set_error("战斗中没有脚本：一场战斗只有**结果**进脚本，先打完这一场。");
        return -2;
    }
    session.stamp();"""

NEW_FILL_GUARD = """    if session.in_fight {
        set_error("战斗中没有脚本：一场战斗只有**结果**进脚本，先打完这一场。");
        return -2;
    }
    session.stamp();
    if session.hash_failed {
        // §170 `P1-4`: 有一格哈希算不出来，这份脚本就**不能**导出去当证据用。
        set_error("导不出脚本：这一局的状态文本超出了哈希缓冲，逐步哈希对不上");
        return -2;
    }"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in [
        (OLD_FIELDS, NEW_FIELDS),
        (OLD_LOG, NEW_LOG),
        (OLD_STAMP, NEW_STAMP),
        (OLD_COMPARE, NEW_COMPARE),
        (OLD_FILL_GUARD, NEW_FILL_GUARD),
    ]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("P1-4: hash unavailability is a session flag, never a 0")


if __name__ == "__main__":
    main()
