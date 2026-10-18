"""变异测试驱动：改一处 → 跑指定测试 → 报红/绿 → 还原。

用法：python native/_mutate.py <名字>
不是构建的一部分。
"""
import io
import subprocess
import sys

ROOT = r"D:\Vibe\sts-tui"
CARGO = ROOT + r"\tools\cargo.ps1"


def patch(path, old, new):
    full = ROOT + "\\" + path
    text = io.open(full, encoding="utf-8").read()
    if text.count(old) != 1:
        raise SystemExit("marker %r appears %d times in %s" % (old[:60], text.count(old), path))
    io.open(full, "w", encoding="utf-8", newline="\n").write(text.replace(old, new, 1))


MUTATIONS = {
    # M1：两相位掉序（事件相位排到效果相位之前 ⇒ 等价于"入队即可见"）
    "m1_phases_swapped": (
        "kernel/rd-core/src/host.rs",
        """            // 相位 1：效果队列抽干。
            self.resolve_pending_effects(state, limits)?;
            // 相位 2：事件队列抽干。
            self.resolve_pending_events(state, limits)?;""",
        """            // 相位 2：事件队列抽干。（变异：相位掉序）
            self.resolve_pending_events(state, limits)?;
            // 相位 1：效果队列抽干。
            self.resolve_pending_effects(state, limits)?;""",
        ["-p", "rd-core", "--release", "the_effect_phase_runs_before_the_event_phase"],
    ),
    # M2：收尾无条件发号（批次 1 的做法）
    "m2_close_action_always": (
        "kernel/rd-core/src/play.rs",
        """    if state.current_chain().is_none() {
        let _wrap_up_chain = state.create_root_effect_chain();
    }""",
        """    let _wrap_up_chain = state.create_root_effect_chain();""",
        ["-p", "rd-core", "--release", "the_program_terminal_lands_in_the_chain"],
    ),
    # M3：循环走完那一刻**不重入**节目链（终态因此落在顶层）
    "m3_loop_without_chain": (
        "kernel/rd-core/src/exec.rs",
        """                let chain = frame_record.chain;
                return state.with_chain(chain, |state| {
                    complete_in_chain(state, content, anchor, frame, parent, stats)
                });""",
        """                return complete_in_chain(state, content, anchor, frame, parent, stats);""",
        ["-p", "rd-core", "--release", "the_program_terminal_lands_in_the_chain"],
    ),
    # M4：Sequence 不等孩子完成（把"还剩几个"直接记成 0）
    "m4_sequence_counts_wrong": (
        "kernel/rd-core/src/exec.rs",
        """        cell.kind = ProgramNodeKind::Sequence;
        cell.remaining = remaining;""",
        """        cell.kind = ProgramNodeKind::Sequence;
        cell.remaining = 0;""",
        ["-p", "rd-core", "--release", "the_program_terminal_lands_in_the_chain"],
    ),
    # M6：触发器入队的效果**当场**解析（"两相位塌成同步"的字面版本）
    "m6_trigger_effect_immediate": (
        "kernel/rd-core/src/host.rs",
        """            outcome.map_err(|e| self.record(HostError::Exec(e)))?;
        }
        Ok(())
    }

    /// 跑一条续延（`CombatEventHandling.cs:107-111` 的 `c(combat)`）。""",
        """            outcome.map_err(|e| self.record(HostError::Exec(e)))?;
            // 变异：把触发器入队的效果**当场**解析。
            self.resolve_pending_effects(state, QueueLimits::default())
                .map_err(|e| self.record(e))?;
        }
        Ok(())
    }

    /// 跑一条续延（`CombatEventHandling.cs:107-111` 的 `c(combat)`）。""",
        ["-p", "rd-core", "--release", "the_effect_phase_runs_before_the_event_phase"],
    ),
    # M5：帧回收时不还链引用（容量会静默漏）
    "m5_reap_leaks_chain": (
        "kernel/rd-core/src/exec.rs",
        """        if let Some(record) = state.program_frames().get(frame).copied() {
            state.release_chain(record.chain);
        }""",
        """        // 变异：不还引用""",
        ["-p", "rd-core", "--release", "a_program_hands_back_the_chain_references_it_took"],
    ),
}


def run(args):
    args = ["test"] + args
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "& '%s' %s" % (CARGO, " ".join(args))],
        cwd=ROOT,
        capture_output=True,
    )
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    return proc.returncode, out


def main():
    name = sys.argv[1]
    path, old, new, args = MUTATIONS[name]
    patch(path, old, new)
    try:
        code, out = run(args)
    finally:
        patch(path, new, old)
    lines = [
        ln
        for ln in out.split("\n")
        if "test result" in ln or "panicked" in ln or "FAILED" in ln or ln.startswith("error")
    ]
    print("MUTATION %s -> exit %d" % (name, code))
    for ln in lines[:12]:
        print("   " + ln.strip())


if __name__ == "__main__":
    main()
