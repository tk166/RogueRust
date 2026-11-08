"""§285 判据：事件概率的**两侧**、区间金币、同种子可复现、Scrap Ooze 的升级链。

判据放在 `rd-run`（事件机制在这一层，且**不需要内容**就能建一个"两段带概率"的事件）：
* 概率 1 ⇒ 永远走失败边；概率 100 ⇒ 永远走成功边（两侧，防"永远成功"或"永远失败"）；
* 中间概率 ⇒ **两侧都出现过**（扫一批种子），且同种子同结果；
* `gold_random:20:50` ⇒ 区间**两端都到过**，且同种子同一个数。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

ANCHOR = '''    /// §278：事件是**一棵树** —— 走完一段不结算，走完最后一段才结算。'''

TESTS = r'''    /// §285：**概率分支**的两侧 + 同种子可复现。
    ///
    /// `Chance = 1` ⇒ 永远失败；`Chance = 100` ⇒ 永远成功；中间的 50 ⇒ 扫 32 个种子必须
    /// **两侧都出现**（只测一侧的话，"永远成功"与"永远失败"都能通过）。
    #[test]
    fn an_event_roll_takes_both_branches() {
        let pool = curse_pool();
        // 事件的段 id 不需要真的存在于内容里：运行层只把它们当**名字**（§278 的纪律：
        // run 层不读内容）。所以这里能直接摆一个两段事件。
        let run_to = |seed: i32, chance: u8| -> std::string::String {
            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.begin_event("probe", "probe").expect("the event opens");
            run.resolve_event_effects(
                &[],
                Some("probe.success"),
                Some(EventRoll {
                    chance,
                    on_success: "probe.success",
                    on_fail: "probe.fail",
                }),
                &pool,
            )
            .expect("the roll resolves");
            std::string::String::from(run.event_step())
        };

        for seed in 0..8 {
            assert_eq!(run_to(seed, 1), "probe.fail", "1% never succeeds (seed {seed})");
            assert_eq!(run_to(seed, 100), "probe.success", "100% always succeeds (seed {seed})");
        }

        let mut successes = 0;
        let mut failures = 0;
        for seed in 0..32 {
            if run_to(seed, 50) == "probe.success" {
                successes += 1;
            } else {
                failures += 1;
            }
        }
        assert!(
            successes > 0 && failures > 0,
            "50% over 32 seeds must take **both** branches, got {successes} success / {failures} fail"
        );
        // 同种子 ⇒ 同结果（掷骰走的是 RunState 自己的流，跟着种子走）。
        assert_eq!(run_to(7, 50), run_to(7, 50), "the same seed must roll the same way");
    }

    /// §285：`gold_random:<min>:<max>` —— 区间**两端都到过**，且同种子同一个数。
    #[test]
    fn gold_random_stays_inside_its_range_and_covers_it() {
        let pool = curse_pool();
        let gained = |seed: i32| -> i32 {
            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.begin_event("probe", "probe").expect("the event opens");
            let before = run.gold();
            run.resolve_event_effects(
                &[(EventEffect::GoldRandom(20, 50), None)],
                None,
                None,
                &pool,
            )
            .expect("the range resolves");
            run.gold() - before
        };
        let mut seen_low = false;
        let mut seen_high = false;
        for seed in 0..64 {
            let amount = gained(seed);
            assert!(
                (20..=50).contains(&amount),
                "seed {seed} gained {amount}, outside 20..=50"
            );
            if amount == 20 {
                seen_low = true;
            }
            if amount >= 48 {
                seen_high = true;
            }
        }
        assert!(seen_low, "the low end of the range never came up");
        assert!(seen_high, "the high end of the range never came up");
        assert_eq!(gained(7), gained(7), "the same seed must give the same amount");

        // 负区间 = 扣钱，且被 clamps 在 0（wiki: "never more than the Gold you are carrying"）。
        let mut run = RunState::new(7, 80, 10, &["strike"; 5]).expect("a run with 10 gold");
        run.begin_event("probe", "probe").expect("the event opens");
        run.resolve_event_effects(
            &[(EventEffect::GoldRandom(-20, -50), None)],
            None,
            None,
            &pool,
        )
        .expect("the range resolves");
        assert_eq!(run.gold(), 0, "a 20-50 loss from 10 gold leaves zero, not negative");
    }

'''

def main():
    s = io.open(P, encoding='utf-8').read()
    assert s.count(ANCHOR) == 1
    assert 'an_event_roll_takes_both_branches' not in s
    s = s.replace(ANCHOR, TESTS + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('§285 run tests appended')


main()
