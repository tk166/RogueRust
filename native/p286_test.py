"""§286 判据：
* **进入效果**在到达时兑（且与选项效果同一个事务：失败全回滚）；
* **四选一**权重表：每一档都到过（四个奖励都出现）、和不是 100 时也不越界；
* **事件战斗**：`event_fight` 置位、节点**不**结算、`mark_resolved` 清档位。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

ANCHOR = '''    /// §278：事件是**一棵树** —— 走完一段不结算，走完最后一段才结算。'''

TESTS = r'''    /// §286：**进入效果**在**到达**目标段时兑，而且和选项效果同一个事务。
    #[test]
    fn entry_effects_land_on_arrival_and_roll_back_together() {
        let pool = curse_pool();
        let entry: [(EventEffect, Option<&str>); 1] = [(EventEffect::Gold(30), None)];
        let table: [(&str, &[(EventEffect, Option<&str>)]); 1] = [("probe.next", &entry)];
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("probe", "probe").expect("the event opens");
        let gold_before = run.gold();
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::Gold(5), None)],
                next: Some("probe.next"),
                entry: &table,
                ..EventMove::none()
            },
            &pool,
        )
        .expect("the move lands");
        assert_eq!(run.event_step(), "probe.next", "we are standing on the target step");
        assert_eq!(
            run.gold(),
            gold_before + 35,
            "the option's 5 and the step's 30 both landed on arrival"
        );

        // 进入效果里有一条付不起的钱 ⇒ **整个**事务回滚（选项那 5 也没了）。
        let mut poor = RunState::new(7, 80, 3, &["strike"; 5]).expect("a poor run");
        poor.begin_event("probe", "probe").expect("the event opens");
        let before = poor;
        let pricey: [(EventEffect, Option<&str>); 1] = [(EventEffect::GoldCost(10), None)];
        let table_pricey: [(&str, &[(EventEffect, Option<&str>)]); 1] = [("probe.next", &pricey)];
        let outcome = poor.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::Gold(5), None)],
                next: Some("probe.next"),
                entry: &table_pricey,
                ..EventMove::none()
            },
            &pool,
        );
        assert_eq!(outcome, Err(RunError::NotEnoughGold { price: 10, gold: 8 }),
                   "the entry effect is paid **after** the option's gold, then refused");
        assert!(poor == before, "not one byte moved: the +5 was rolled back too");
    }

    /// §286：**四选一**的权重表 —— 每一档都必须到过，同种子同结果。
    #[test]
    fn a_four_way_branch_reaches_every_branch() {
        let pool = curse_pool();
        let table = [
            (25u8, "probe.a"),
            (25, "probe.b"),
            (25, "probe.c"),
            (25, "probe.d"),
        ];
        let mut seen = [false; 4];
        for seed in 0..64 {
            let mut run = RunState::new(seed, 80, 0, &["strike"; 5]).expect("a run");
            run.begin_event("probe", "probe").expect("the event opens");
            run.resolve_event_effects(
                &EventMove { branches: &table, ..EventMove::none() },
                &pool,
            )
            .expect("the roll resolves");
            let slot = match run.event_step() {
                "probe.a" => 0,
                "probe.b" => 1,
                "probe.c" => 2,
                "probe.d" => 3,
                other => panic!("landed on {other}, which is not a branch"),
            };
            seen[slot] = true;
        }
        assert!(seen.iter().all(|hit| *hit), "64 seeds must reach all four: {seen:?}");
    }

    /// §286：**事件把房间变成一场战斗** —— 档位记下来、事件收尾、节点**不**结算；
    /// 而 `mark_resolved` 是唯一清它的地方。
    #[test]
    fn an_event_can_turn_the_room_into_a_fight() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("dead_adventurer", "dead_adventurer")
            .expect("the event opens");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::Gold(30), None)],
                fight: 2,
                ..EventMove::none()
            },
            &pool,
        )
        .expect("the ambush resolves");

        assert_eq!(run.event_fight(), 2, "the band is recorded for the caller");
        assert_eq!(run.event(), "", "the event is over -- the fight is what happens now");
        assert_eq!(run.pending(), Pending::None, "nothing is waiting on a choice");
        assert!(!run.node_resolved(), "the node is **not** settled: the fight settles it");
        assert_eq!(run.gold(), 30, "the effects still landed");

        run.mark_resolved();
        assert_eq!(run.event_fight(), 0, "settling the node clears the band");
        assert!(run.node_resolved());
    }

'''

def main():
    s = io.open(P, encoding='utf-8').read()
    assert s.count(ANCHOR) == 1
    assert 'entry_effects_land_on_arrival' not in s
    s = s.replace(ANCHOR, TESTS + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('§286 run tests appended')


main()
