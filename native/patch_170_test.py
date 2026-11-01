"""Tests for P1-1 / P1-2 / P1-3 -- the ones that must bypass the UI.

The review's sharpest point about process was that all five P1s sat in a blind spot: no gate called
the ABI out of the state the page happens to be in. So these tests drive the exports **directly**,
with a fight already running, which is exactly what a second caller (a replay, an RL env, a page that
forgot its own guard) would do.

Reachability note, stated plainly: the *post-build* failure paths of `fight_begin` (a missing act
pool, a pool that will not pick, a relic bonus the kernel cannot write) are content-dependent and
cannot be forced from the content this repository ships. Those are covered **by construction** -- the
flags are written at the commit point and the whole state is restored on any failure -- not by a test.
What is tested here is every refusal that is reachable: no node, a resolved node, and a fight already
in progress.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// §164: 回档之后接着打的那些步，靠**头部携带档案**回放。"""

TEST = '''    /// §170 `P1-2`: 一场没打完就不许再开一场 —— 否则它会重新摇遭遇、覆盖掉正在打的战斗。
    ///
    /// 判据是"**什么都没改** + 战斗还在"：整局相等（含随机流计数）、`in_fight` 仍为真、
    /// 战斗会话还在、英雄血量没被重设。
    #[test]
    fn a_second_fight_begin_is_refused_and_the_fight_in_progress_survives() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "the first begin must work: {}", run_error_text());
        assert!(
            run_slot().as_ref().expect("session").in_fight,
            "a successful begin commits `in_fight`"
        );

        let before = *run_slot().as_ref().expect("session").state;
        let hero_before = crate::combat_hero_health().expect("a fight");
        let journal_before = run_slot().as_ref().expect("session").journal.len();

        assert_eq!(
            rd_run_fight_begin(),
            -2,
            "a second begin while the fight runs must be refused"
        );
        assert!(
            run_error_text().contains("已经开始了"),
            "the refusal must say why: {}",
            run_error_text()
        );

        // The whole point: the encounter was not re-rolled and the fight was not replaced.
        assert!(
            *run_slot().as_ref().expect("session").state == before,
            "a refused begin changed the run"
        );
        assert_eq!(
            run_slot().as_ref().expect("session").journal.len(),
            journal_before,
            "a refused begin still appended a step to the script"
        );
        assert_eq!(
            crate::combat_hero_health().expect("the fight survives"),
            hero_before,
            "the fight in progress was replaced"
        );
    }

    /// §170 `P1-1`：可失败的 `fight_begin` 拒绝之后，`in_fight` **不许**留在 true。
    ///
    /// 卡住的 `in_fight` 不是审美问题：`rd_run_archive_fill` 会一直拒绝存档，而玩家根本没有一场仗
    /// 可以打完 —— 这与 §164.3 是同一类 bug。
    #[test]
    fn a_refused_fight_begin_never_leaves_the_run_in_a_fight() {
        // (a) 还没走到任何节点。
        test_run(7, 80, 80, &["strike"; 10]);
        let before = *run_slot().as_ref().expect("session").state;
        assert_eq!(rd_run_fight_begin(), -2, "no node, no fight");
        let session = run_slot().as_ref().expect("session");
        assert!(!session.in_fight, "a refused begin left `in_fight` set");
        assert!(!session.elite_fight && !session.boss_fight, "the tier flags leaked");
        assert!(*session.state == before, "a refused begin changed the run");

        // (b) 一个**已经结算**的战斗节点：打完再按一次。
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "{}", run_error_text());
        assert!(rd_run_fight_end() >= 0, "{}", run_error_text());
        assert!(
            !run_slot().as_ref().expect("session").in_fight,
            "ending the fight clears the flag"
        );
        let settled = *run_slot().as_ref().expect("session").state;
        assert_eq!(rd_run_fight_begin(), -2, "a settled node pays once");
        assert!(
            run_error_text().contains("已经结算"),
            "the refusal must name the reason: {}",
            run_error_text()
        );
        let session = run_slot().as_ref().expect("session");
        assert!(!session.in_fight, "a refused begin left `in_fight` set");
        assert!(*session.state == settled, "a refused begin changed the run");
    }

    /// §170 `P1-3`：脚本导出与回放在**ABI 层**就拒绝战斗中调用。
    ///
    /// 这条测试**故意绕开页面**：页面的 `mode === "fight"` 不是契约，内核才是。存档在 §161.10
    /// 学过一次，脚本接口没跟着学。
    #[test]
    fn the_script_abi_refuses_mid_fight_without_the_page() {
        test_run(7, 80, 80, &["strike"; 10]);
        assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
        assert_eq!(rd_run_begin_node(), 0);
        assert_eq!(rd_run_fight_begin(), 0, "{}", run_error_text());
        let before = *run_slot().as_ref().expect("session").state;
        let hero_before = crate::combat_hero_health().expect("a fight");

        // 导出：拒绝，且缓冲区不被写脏（判据是返回值 + 状态不变）。
        assert_eq!(rd_run_script_fill(), -2, "no script mid-fight");
        assert!(
            run_error_text().contains("战斗中没有脚本"),
            "the refusal must say why: {}",
            run_error_text()
        );

        // 回放：拒绝，而且必须在**解析之前** —— 这里给的是一段合法头部，守卫仍先响。
        let head = std::format!("RDR1,S,7,0,{};", super::content_pin_text());
        assert_eq!(
            unsafe { rd_run_replay_from(head.as_ptr(), head.len() as i32) },
            -2,
            "no replay mid-fight"
        );
        assert!(
            run_error_text().contains("战斗中不能回放"),
            "the refusal must say why: {}",
            run_error_text()
        );

        // 两次拒绝都不许动局面，也不许动那场战斗 —— 回放本来会 `rd_run_start` 毁掉它。
        let session = run_slot().as_ref().expect("session");
        assert!(*session.state == before, "a refused replay changed the run");
        assert!(session.in_fight, "a refused replay took the fight away");
        assert_eq!(
            crate::combat_hero_health().expect("the fight survives"),
            hero_before,
            "a refused replay replaced the fight"
        );
        // 而且没有留下"回放过几步"的陈旧读数。
        assert_eq!(rd_run_replay_checked(), 0);
        assert_eq!(rd_run_replay_diverged(), 0);
    }

    /// §164: 回档之后接着打的那些步，靠**头部携带档案**回放。'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn a_second_fight_begin_is_refused" not in text, "already inserted"
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, TEST))
    print("three ABI-level tests added")


if __name__ == "__main__":
    main()
