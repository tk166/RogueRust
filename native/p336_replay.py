"""§336：把 `hash_full` 接进**回放判据**。

## 现状（为什么这里有空洞）

回放逐步比的是**运行层**哈希（`run_hash` = `write_run_input` 的 SHA-256）。而 `K_FIGHT_BEGIN`
在回放里**真的会重搭一场战斗**（`rd_run_fight_begin` 选遭遇、建牌组、装会话），但那场战斗的
状态**从来没有被比对过** —— 运行层哈希只覆盖 `last_encounter` 那一格。

于是这些分叉全都看不见：

* 同一遭遇、但敌人的 HP/起始状态不同（升阶接线变了、`INV_ASC_HP` 改了）；
* 同一牌组、但每副本 mark 没被写进战斗（§253 `apply_run_marks` 漏一步）；
* `ascension` / `heal_blocked` / `encounter` 这些 **model-only 战斗事实**没接进战斗
  （它们不在 `hash_golden` 里 —— 那正是 §334 做 `hash_full` 的理由）。

## 做法

`K_FIGHT_BEGIN` 那条记录的第 5 列（`text`，本来空着）改成 **战斗状态的 `hash_full` 前 8 字节**：

* 记录时（`stamp`）：战斗刚建好，算一次 `write_full_hash_input` 的前缀；
* 回放时：`rd_run_fight_begin()` 之后算同一个前缀，**逐位比对**。

不比对 `hash_golden` 而是 `hash_full`：`hash_golden` 看不见 `ascension` / `heal_blocked` /
`encounter`，而这三件恰恰是"同一串动作、不同一局"的来源。

⚠️ 向后兼容：旧脚本的第 5 列是空串 ⇒ **不比对**（不是"比对 0"）。判据里两侧都测。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(RUN, encoding='utf-8').read()

# ── 1. 战斗状态的 `hash_full` 前缀 ────────────────────────────────────────────
t = sub(t, """fn hash_prefix(state: &rd_run::state::RunState) -> Option<u64> {""",
        """/// §336：**战斗状态**的 `hash_full` 前缀（`write_full_hash_input` 的 SHA-256 前 8 字节）。
///
/// 为什么不是 `write_hash_input`（`hash_golden`）：那一个看不见 `ascension` / `heal_blocked` /
/// `encounter` 这些 model-only 事实，而"同一串动作、不同一局"正是从这些地方来的（§334）。
///
/// `None` = 没有战斗会话，或者规范文本超出缓冲（**响亮**：不返回 0 假装算过）。
fn combat_full_hash_prefix() -> Option<u64> {
    let session = crate::slot().as_ref()?;
    // 战斗规范文本实测几 KB；给 64 KiB 留足（`hash_golden` 的测试用 1 MiB，那是 debug 构建的量级）。
    let mut buffer = std::vec![0u8; 1 << 16];
    let text_len = {
        let mut writer = rd_core::writer::TextWriter::new(&mut buffer);
        rd_core::snapshot::write_full_hash_input(&mut writer, &session.state);
        if writer.overflowed() {
            return None;
        }
        writer.len()
    };
    let digest = rd_core::hash::sha256(&buffer[..text_len]);
    Some(u64::from_be_bytes([
        digest[0], digest[1], digest[2], digest[3], digest[4], digest[5], digest[6], digest[7],
    ]))
}

fn hash_prefix(state: &rd_run::state::RunState) -> Option<u64> {""",
        'hash helper')

# ── 2. 记录时把战斗指纹写进 `K_FIGHT_BEGIN` 那一格的 text ──────────────────────
t = sub(t, """    fn stamp(&mut self) {
        if self.replaying {
            return;
        }
        let hash = self.state_hash();
        let Some(last) = self.journal.last_mut() else {
            return;
        };
        // §170 `P1-4`: `None` 不再是"0"，是"这一局的文本算不出指纹"—— 记进会话，导出/回放拒绝。
        last.hash = hash.unwrap_or(0);
    }""",
        """    fn stamp(&mut self) {
        if self.replaying {
            return;
        }
        let hash = self.state_hash();
        let Some(last) = self.journal.last_mut() else {
            return;
        };
        // §170 `P1-4`: `None` 不再是"0"，是"这一局的文本算不出指纹"—— 记进会话，导出/回放拒绝。
        last.hash = hash.unwrap_or(0);
        // §336：`fight_begin` 那一步额外记下**战斗状态**的 `hash_full`（第 5 列，本来是空的）。
        // 回放会重搭同一场战斗，于是这一格能证明"搭出来的那场与当初那场逐位相同" ——
        // 运行层哈希只覆盖 `last_encounter` 一格，看不见敌人 HP / 起始状态 / 每副本 mark。
        if last.kind == K_FIGHT_BEGIN {
            last.text = match combat_full_hash_prefix() {
                Some(prefix) => std::format!("{prefix:016x}"),
                None => {
                    // 算不出来 ⇒ 留空 = "这一格没有可比的东西"，回放那边据此跳过（不是比对 0）。
                    self.hash_failed = true;
                    std::string::String::new()
                }
            };
        }
    }""",
        'stamp')

# ── 3. 回放时比对 ─────────────────────────────────────────────────────────────
t = sub(t, """            K_FIGHT_BEGIN => {
                let _ = rd_run_fight_begin();
            }""",
        """            K_FIGHT_BEGIN => {
                let _ = rd_run_fight_begin();
                // §336：重搭出来的那场战斗必须与当初那场**逐位相同**。
                //
                // 旧脚本的第 5 列是空串 ⇒ 不比对（不是"比对 0"）：那些脚本录制时还没有这一格，
                // 拿 0 去比会让它们**全部**报分叉 —— 那是"加判据把旧证据全废掉"。
                if !payload.is_empty() {
                    let want_fight = u64::from_str_radix(payload, 16).ok();
                    let now_fight = combat_full_hash_prefix();
                    if want_fight != now_fight {
                        session_clear_replay(checked, (index + 1) as i32);
                        set_error(&std::format!(
                            "第 {} 步之后**战斗**不同（期望 {}，回放得到 {}）· 这一场是从运行层重搭的，\\
                             差别在敌人/起始状态/每副本 mark 或 model-only 事实（§336）",
                            index + 1,
                            payload,
                            now_fight.map_or(std::string::String::from("none"), |h| {
                                std::format!("{h:016x}")
                            })
                        ));
                        return (index + 1) as i32;
                    }
                }
            }""",
        'replay compare')

io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-wasm: fight_begin carries hash_full')
