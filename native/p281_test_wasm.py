"""§281 判据（wasm）：Snecko Oil 的价格随机化 —— 两侧 + step 恰好 + 手牌数。

它现在走 `exec::draw_random`（战斗随机流的唯一入口）。要钉三件事：

1. **同种子 ⇒ 同一组价格**（换一个种子 ⇒ 至少有一张不同）—— 只钉一侧的话，
   "价格全等于 0"（永不抽取）与"每次抽都不一样"（不读种子）都能通过；
2. **step 恰好 + 手牌数**（每张牌抽一次）—— 老实现**同时**改 `random_seed` 与 step，
   于是"一次抽取"消耗两笔账；
3. 价格仍在 `0..=3`（范围现在来自内容的 `combat_randomize_costs:0:3`）。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

ANCHOR = '''    /// §179: Smoke Bomb -- "Escape from a non-boss combat. Receive no rewards."'''

TEST = r'''    /// §281：价格随机化**可复现**（同种子同序列），而且每张牌恰好消耗**一次**随机。
    ///
    /// 老实现（`next_u32(&mut seed) % 4` + 同时写回 `random_seed`）会让"一次抽取"变成两笔账：
    /// `random_seed` 动了、`random_step` 也动了。这条判据钉的是**只动 step、恰好 N 次**。
    #[test]
    fn the_price_roll_is_reproducible_and_costs_one_step_per_card() {
        let prices_with_seed = |seed: i32| -> (Vec<i32>, i32, i32) {
            test_run(seed, 80, 80, &["strike"; 10]);
            assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
            assert_eq!(rd_run_begin_node(), 0);
            assert_eq!(rd_run_fight_begin(), 0, "the fight must start");
            let (step_before, seed_before) = {
                let session = crate::slot().as_ref().expect("env session");
                (session.state.random_step, session.state.random_seed)
            };
            assert_eq!(drink("snecko_oil", -1), 0, "drinking it must work");
            let session = crate::slot().as_ref().expect("env session");
            let taken = session.hand_len() as i32;
            (
                session.hand_costs.clone(),
                session.state.random_step - step_before,
                session.state.random_seed - seed_before,
            )
        };

        let (first, steps, seed_delta) = prices_with_seed(7);
        assert_eq!(
            steps,
            first.len() as i32,
            "one draw per hand card: {} card(s) but {steps} step(s)",
            first.len()
        );
        assert_eq!(
            seed_delta, 0,
            "the seed must not move -- only `step` does (the shuffle's convention)"
        );
        // 两侧 ①：**同一个种子**再跑一遍，价格逐个相同。
        let (again, _, _) = prices_with_seed(7);
        assert_eq!(again, first, "the same seed must randomize the same way");
        // 两侧 ②：换一个种子，至少有一张不同（否则种子根本没被读）。
        let (other, _, _) = prices_with_seed(8);
        assert!(
            other.iter().zip(first.iter()).any(|(a, b)| a != b),
            "seed 8 produced the same prices as seed 7 -- the seed is not being read: {other:?}"
        );
        // 范围仍在 0..=3（来自内容，不是 wasm 的常数）。
        for (index, cost) in first.iter().enumerate() {
            assert!(
                (0..=3).contains(cost),
                "hand[{index}] costs {cost}, outside the content's 0..=3"
            );
        }
    }

'''

def main():
    s = io.open(P, encoding='utf-8').read()
    assert s.count(ANCHOR) == 1
    assert 'the_price_roll_is_reproducible_and_costs_one_step_per_card' not in s
    s = s.replace(ANCHOR, TEST + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('§281 wasm test appended')


main()
