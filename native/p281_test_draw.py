"""§281 判据：随机流的两侧 + 可复现 + step 恰好 +1 + 嵌套响亮拒绝。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/state.rs'

ANCHOR = '''    fn reshuffling_appends_the_whole_discard_pile_in_the_rng_order_and_advances_the_step() {'''

TESTS = r'''    /// §281：`draw_in_range` —— **每一档都到过**（不是"总是 min"），而且 `step` 每次恰好 +1。
    ///
    /// 两侧都要：只看"落在范围内"的话，一个**永远返回 min** 的实现也全绿（范围检查是它的
    /// 子集）。所以这里钉"跨度 4 的抽取里四个值都出现过"。
    #[test]
    fn a_draw_covers_its_whole_range_and_advances_one_step() {
        let mut state = CombatState::new(CombatId::new(9).unwrap(), 1234);
        let step_before = state.random_step;
        let seed_before = state.random_seed;
        let mut seen = [false; 4];
        for index in 0..64 {
            let value = state.draw_in_range(0, 3);
            assert!(
                (0..=3).contains(&value),
                "draw {index} gave {value}, outside 0..=3"
            );
            seen[value as usize] = true;
        }
        assert_eq!(seen, [true; 4], "64 draws over 0..=3 must hit every value");
        assert_eq!(
            state.random_step - step_before,
            64,
            "one draw = one step (the shuffle's convention)"
        );
        assert_eq!(
            state.random_seed, seed_before,
            "the seed must NOT move -- only `step` does (that is what makes a seed replayable)"
        );
        // `max <= min` 是常数，**不消耗**随机流。
        let step = state.random_step;
        assert_eq!(state.draw_in_range(7, 7), 7);
        assert_eq!(state.draw_in_range(9, 3), 9, "an inverted range is the low end");
        assert_eq!(state.random_step, step, "a constant range draws nothing");
    }

    /// §281：同一个种子 ⇒ 同一个序列；换一个种子 ⇒ 换一条序列（两侧）。
    #[test]
    fn a_draw_sequence_replays_from_its_seed() {
        let mut a = CombatState::new(CombatId::new(9).unwrap(), 4242);
        let mut b = CombatState::new(CombatId::new(9).unwrap(), 4242);
        let mut c = CombatState::new(CombatId::new(9).unwrap(), 4243);
        let mut same = 0;
        let mut differ = 0;
        for _ in 0..32 {
            let x = a.draw_in_range(0, 9);
            let y = b.draw_in_range(0, 9);
            let z = c.draw_in_range(0, 9);
            assert_eq!(x, y, "the same seed must replay the same sequence");
            if x != z {
                differ += 1;
            } else {
                same += 1;
            }
        }
        assert!(
            differ > 0,
            "a different seed produced the same 32 draws -- the seed is not being read"
        );
        assert!(same < 32, "and they must not agree on everything either");
        // 抽取与洗牌共用 `(seed, step)` 的派生：把 step 推到同一个值，两种随机的
        // "下一个数"必须一致（否则两条路对同一个种子的看法会分家）。
        let mut d = CombatState::new(CombatId::new(9).unwrap(), 77);
        d.random_step = 5;
        assert_eq!(
            d.draw_in_range(0, 1000),
            (crate::rng::draw_u32(77, 5) % 1001) as i32,
            "the draw must derive from (seed, step) exactly like the shuffle does"
        );
    }

'''

def main():
    s = io.open(P, encoding='utf-8').read()
    assert s.count(ANCHOR) == 1
    assert 'a_draw_covers_its_whole_range_and_advances_one_step' not in s
    s = s.replace(ANCHOR, TESTS + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('§281 state tests appended')


main()
