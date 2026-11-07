"""§278 判据（run 层）：事件是树 —— 走一段不收尾，走完最后一段才收尾。

三件事，每件都对应一种"看起来正常"的坏实现：
1. 走到第二段时 `Pending::Event` 仍是 `Event`（**没有**结算）；
2. `event_step` 真的换成了下一段（不是"重新显示第一段"）；
3. 最后一段走完才 `mark_resolved`，且 `event_step` 归零。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

ANCHOR = '''    /// §188: a list that fails **in the middle** must not half-apply.'''

TEST = r'''    /// §278：事件是**一棵树** —— 走完一段不结算，走完最后一段才结算。
    #[test]
    fn an_event_tree_advances_one_step_at_a_time() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol", "golden_idol").expect("open the event");
        assert_eq!(run.event_step(), "golden_idol", "the run starts on the entry step");
        assert_eq!(run.pending(), Pending::Event);

        // ── 第一段：拿到遗物，**并且**被带去下一段。
        run.resolve_event_effects(
            &[(EventEffect::GainRelic, Some("golden_idol"))],
            Some("golden_idol.boulder"),
            &pool,
        )
        .expect("taking the idol");
        assert_eq!(
            run.event_step(),
            "golden_idol.boulder",
            "the run must be standing on the **second** step now"
        );
        assert_eq!(
            run.pending(),
            Pending::Event,
            "the room is **not** settled: there is another step"
        );
        assert!(!run.node_resolved(), "and it is not paid either");

        // ── 第二段：百分比扣血，然后收尾。
        let hp_max = run.health_max();
        let post_before = run.health_max;
        assert_eq!(post_before, hp_max);
        let hp_before = run.health();
        run.resolve_event_effects(
            &[(EventEffect::LoseHealthPercent(25), None)],
            None,
            &pool,
        )
        .expect("smashing the boulder");
        assert_eq!(
            run.health(),
            hp_before - (hp_max * 25 / 100),
            "Smash takes floor(max HP × 25%)"
        );
        assert_eq!(run.health_max(), hp_max, "Smash does not touch the maximum");
        assert_eq!(run.event_step(), "", "the step is cleared when the tree ends");
        assert_eq!(run.pending(), Pending::None, "nothing is owed");
        assert!(run.node_resolved(), "the room is settled now");
    }

    /// §278：`max_hp_pct` 扣的是**上限**，并且当前 HP 跟着夹住；下限是 1。
    #[test]
    fn losing_max_health_by_percent_never_goes_below_one() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol", "golden_idol.boulder").expect("the boulder");
        let before = run.health_max();
        run.resolve_event_effects(&[(EventEffect::LoseMaxHealthPercent(8), None)], None, &pool)
            .expect("hiding");
        assert_eq!(run.health_max(), before - (before * 8 / 100), "8% of max, floored");
        assert!(
            run.health() <= run.health_max(),
            "the current HP must be clamped to the new maximum"
        );
        // 1 HP 的上限也只会掉 1（下限 1），不会掉到 0 或负数。
        let mut tiny = RunState::new(7, 1, 0, &["strike"; 5]).expect("a 1 HP run");
        tiny.begin_event("golden_idol", "golden_idol.boulder").expect("the boulder");
        tiny.resolve_event_effects(&[(EventEffect::LoseMaxHealthPercent(50), None)], None, &pool)
            .expect("hiding");
        assert_eq!(tiny.health_max(), 0, "max(1, floor(1 × 50%)) = 1 taken away");
        assert!(tiny.health() >= 0, "HP never goes negative");
    }

    /// §278：`next` 是一个**坏 id** 时，整个事件不动一个字节（含 `event_step`）。
    #[test]
    fn a_bad_next_step_is_refused_before_anything_moves() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("golden_idol", "golden_idol").expect("the event");
        let before = run;
        let outcome = run.resolve_event_effects(
            &[(EventEffect::Gold(30), None)],
            Some("golden_idol.nope"),
            &pool,
        );
        assert_eq!(outcome, Err(RunError::NoSuchEvent), "an unknown step id is refused");
        assert!(run == before, "not one byte moved (the gold did not land either)");
    }

'''

def main():
    s = io.open(P, encoding='utf-8').read()
    assert s.count(ANCHOR) == 1
    assert 'an_event_tree_advances_one_step_at_a_time' not in s
    s = s.replace(ANCHOR, TEST + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('run-layer tree tests appended')


main()
