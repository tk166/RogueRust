"""§195.1: `DamageTaken` carries the damage, and `eventAmount` finally evaluates.

`eventAmount` has been in `INT_KINDS` since the beginning and **never** had an evaluation arm -- so
any content that wrote it got `UnsupportedKind`. And `DamageTaken { target, source }` carried no
number at all, so even with the arm there would be nothing to read. Together they blocked the one
thing the wiki describes as "after losing X HP" (The Guardian's Mode Shift 30).

This patch is the plumbing only; §195.1's content half (a real Mode Shift counter) is
`patch_195_content.py`.

Three decisions worth writing down:

* **`eventAmount` never returns 0 without an event.** `0` is a legal amount, so "no context" and
  "zero damage" must not look alike -- it is `ExprError::NoTarget`, the same bucket
  `cardInstance.iterated` uses for "no iteration card".
* **The amount is the HP actually lost** (`health_lost`), not the requested amount: the wiki's Mode
  Shift says "after losing X HP", and a fully blocked hit loses none. `DamageDealt` already carries
  three numbers (`health_damage` / `blocked_damage` / `requested`); `DamageTaken` was the event the
  receiver-side triggers hang off, and it only needs one.
* **The plumbing rides on the existing `event_flags` channel.** `ExecContext::event_flags` (a `u8`)
  already carries "which tags the played card has" to `ExprContext`; the amount is the second such
  scalar, so `execute_program_with_flags` grows one parameter instead of a new context struct.
"""
import io


def sub(path, pairs):
    src = io.open(path, encoding="utf-8").read()
    for old, new, what in pairs:
        assert src.count(old) == 1, "%s / %s: %d x %r" % (path, what, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(src)
    print("patched", path)


# ---------------------------------------------------------------- state.rs: the event
sub("kernel/rd-core/src/state.rs", [(
"""    DamageTaken {
        /// 承受者。
        target: CombatantId,
        /// 出手方（`None` = 无来源的伤害，触发器不跑 —— 参考的第一句就是 `SourceCombatant is not null`）。
        source: Option<CombatantId>,
    },""",
"""    DamageTaken {
        /// 承受者。
        target: CombatantId,
        /// 出手方（`None` = 无来源的伤害，触发器不跑 —— 参考的第一句就是 `SourceCombatant is not null`）。
        source: Option<CombatantId>,
        /// **实际掉的血**（`§195.1`：`eventAmount` 读的就是这个数）。
        ///
        /// 不是请求额、也不是被格挡吸收的那部分：wiki 把 Mode Shift 写成 "after losing X HP"，
        /// 而一次被完全挡住的攻击**一点血都没掉**。`DamageDealt` 三个数都有，这条只要一个。
        health_damage: i32,
    },""",
    "DamageTaken variant")])

# ---------------------------------------------------------------- exec.rs: enqueue + context
sub("kernel/rd-core/src/exec.rs", [(
"""        .enqueue_event(crate::state::CombatEvent::DamageTaken {
            target: *target,
            source: taken_source,
        })""",
"""        .enqueue_event(crate::state::CombatEvent::DamageTaken {
            target: *target,
            source: taken_source,
            health_damage: health_lost,
        })""", "DamageTaken enqueue"), (
"""    pub event_flags: u8,""",
"""    pub event_flags: u8,
    /// §195.1：当前事件带的**数量**（`eventAmount` 读它）。今天只有伤害事件会填，
    /// 其余是 `None` —— 与 `0` 严格区分，见 `expr::eval_int` 的 `eventAmount` 分支。
    pub event_amount: Option<i32>,""", "ExecContext field"), (
"""            event_flags: 0,""",
"""            event_flags: 0,
            event_amount: None,""", "ExecContext::new"), (
"""            event_flags: self.event_flags,""",
"""            event_flags: self.event_flags,
            event_amount: self.event_amount,""", "expr_context"), (
"""                    event_flags: 0,""",
"""                    event_flags: 0,
                    event_amount: None,""", "exec test ctx 1"), (
"""                            event_flags: 0,""",
"""                            event_flags: 0,
                            event_amount: None,""", "exec test ctx 2")])

# ---------------------------------------------------------------- expr.rs: the arm
sub("kernel/rd-core/src/expr.rs", [(
"""    pub event_flags: u8,""",
"""    pub event_flags: u8,
    /// §195.1：当前事件带的**数量**（`eventAmount` 专用）。`None` = 没有事件上下文。
    pub event_amount: Option<i32>,""", "ExprContext field"), (
"""        // 其余（`eventAmount` / `card.upgradeLevel` / `missingHealth` …）""",
"""        // §195.1：**事件带的数量**（伤害事件 = 实际掉血）。
        //
        // ⚠️ 不在事件里时**给错，不给 0**：0 是一个合法数量（被完全挡住的攻击就是 0），
        // 用它表示"没有上下文"会让"这张卡/这条触发器写错了"变成"这一次没有伤害"。
        "eventAmount" => ctx.event_amount.ok_or(ExprError::NoTarget),

        // 其余（`card.upgradeLevel` / `missingHealth` …）""", "eval arm")])

io.open("kernel/rd-core/src/expr.rs", "a", encoding="utf-8").close()
print("done -- now fix the remaining ExprContext literals (tests) and the host plumbing")
