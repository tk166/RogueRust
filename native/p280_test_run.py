"""§280 判据：付钱要响亮拒绝 / heal_full / 12.5% —— 都是"算错也不算崩"的形态。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

ANCHOR = '''    /// §278：`next` **形状不合法**时，整个事件不动一个字节（含 `event_step`）。'''

TESTS = r'''    /// §280：**付不起就拒绝，不是扣到 0 为止**。
    ///
    /// `adjust_gold(-75)` 会把 50 金币夹成 0 —— 玩家**白拿了服务**，而屏幕上一切正常
    /// （这正是 `gold_cost` 存在的理由）。判据是"整份局面不动一个字节"。
    #[test]
    fn paying_more_gold_than_you_have_is_refused_not_clamped() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 20, &["strike"; 5]).expect("a run with 20 gold");
        run.begin_event("the_cleric", "the_cleric").expect("the event");
        let before = run;
        let outcome = run.resolve_event_effects(
            &[(EventEffect::GoldCost(35), None), (EventEffect::HealPercent(250), None)],
            None,
            &pool,
        );
        assert_eq!(
            outcome,
            Err(RunError::NotEnoughGold { price: 35, gold: 20 }),
            "a cost you cannot pay is refused"
        );
        assert!(run == before, "and the heal does not land either");
        // 付得起的时候：金币真的少了、血真的回了 25%（`250` 千分 = 25%）。
        let mut rich = RunState::new(7, 80, 100, &["strike"; 5]).expect("a rich run");
        rich.begin_event("the_cleric", "the_cleric").expect("the event");
        rich.adjust_health(-40);                      // 40/80 = 50%
        rich.resolve_event_effects(
            &[(EventEffect::GoldCost(35), None), (EventEffect::HealPercent(250), None)],
            None,
            &pool,
        )
        .expect("35 gold is affordable");
        assert_eq!(rich.gold(), 65, "35 gold left the purse");
        assert_eq!(rich.health(), 60, "40 + floor(80 × 25%)");
    }

    /// §280：`heal_full` 回的是**当前上限**（不是写死的 999），而且上限后来变了它还成立。
    #[test]
    fn heal_full_reaches_the_current_maximum() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.adjust_health(-50);                       // 30/80
        run.begin_event("the_moai_head", "the_moai_head").expect("the event");
        run.resolve_event_effects(&[(EventEffect::HealFull, None)], None, &pool)
            .expect("jump inside");
        assert_eq!(run.health(), run.health_max, "heal_full reaches the maximum");
    }

    /// §280：`max_hp_pct:12.5` —— 千分单位存在的理由。
    ///
    /// 80 上限的 12.5% = 10 HP。整数百分比会把它算成 9（12%）或 10（13%，那是另一个数），
    /// 所以这条判据钉的是"小数真的进了计算"，而不只是"解析接受 12.5"。
    #[test]
    fn a_fractional_percentage_reaches_the_arithmetic() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"; 5]).expect("a run");
        run.begin_event("the_moai_head", "the_moai_head").expect("the event");
        let before = run.health_max();
        run.resolve_event_effects(&[(EventEffect::LoseMaxHealthPercent(125), None)], None, &pool)
            .expect("the moai head");
        assert_eq!(run.health_max(), before - 10, "12.5% of 80 is exactly 10");
        // 解析层：`12.5` 与 `12` 必须是两个不同的数（一个拼写错误不该被悄悄接受成整数）。
        assert_eq!(EventEffect::parse("max_hp_pct:12.5", 0), Some((EventEffect::LoseMaxHealthPercent(125), None)));
        assert_eq!(EventEffect::parse("max_hp_pct:12", 0), Some((EventEffect::LoseMaxHealthPercent(120), None)));
        // 两位小数、`12.`、`100.5` 都是词表外。
        assert_eq!(EventEffect::parse("max_hp_pct:12.55", 0), None);
        assert_eq!(EventEffect::parse("max_hp_pct:12.", 0), None);
        assert_eq!(EventEffect::parse("max_hp_pct:100.5", 0), None);
        assert_eq!(EventEffect::parse("max_hp_pct:0", 0), None);
    }

'''

def main():
    s = io.open(P, encoding='utf-8').read()
    assert s.count(ANCHOR) == 1
    assert 'paying_more_gold_than_you_have_is_refused_not_clamped' not in s
    s = s.replace(ANCHOR, TESTS + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('§280 run tests appended')


main()
