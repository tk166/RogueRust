"""§173: pin the two mechanics the new elites actually rely on.

The content gate proves the *numbers*; it cannot prove that an enemy which "sleeps for three rounds"
really does nothing for three rounds, or that "6×N with N = uses + 2" really escalates. Those are the
two claims that make these fights the wiki's fights, so they get their own tests -- driven through the
real ABI, in a fight built from the named encounter.

| what | how |
|---|---|
| Lagavulin sleeps rounds 1-3, attacks on 4 | hero HP unchanged for three end-turns, then drops by 18 |
| Book of Stabbing escalates | three Multi Stabs cost 18, 24, 30 (6 × 3/4/5) |

Both use `build_session_at` (crate-internal) so the test does not have to hope the run's RNG picks the
right elite, and `rd_env_step(end turn)` so the enemy turn really runs.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// The end-turn action's index, or `-1`."""

TESTS = '''    /// §173：Lagavulin 睡三个回合，第四回合打 18。
    ///
    /// 这条测的是**内容**：`intent.round <= 3 → lagavulin.sleep`（决策规则）+ 一个空程序的动作。
    /// 内核里没有任何"睡觉"的概念 —— 若规则或动作写错，第一回合就会掉血。
    #[test]
    fn lagavulin_sleeps_for_three_rounds_and_then_attacks() {
        let session = crate::build_session_at(7, "enc_lagavulin", 80, None, 0)
            .expect("the lagavulin encounter");
        crate::install_session(session);

        let hero = || rd_env_observe(4);
        let start = hero();
        assert_eq!(start, 80, "a fresh fight starts at full health");

        // Rounds 1-3: the enemy takes its turn and does nothing.
        for round in 1..=3 {
            let end = rd_env_action_index_of_end_turn();
            assert!(end >= 0, "the hero can end the turn");
            assert_eq!(rd_env_step(end), 0, "round {round} ({})", run_error_text());
            assert_eq!(
                hero(),
                start,
                "round {round}: the sleep program must do nothing"
            );
        }

        // Round 4: awake, and the wiki's Attack is 18.
        let end = rd_env_action_index_of_end_turn();
        assert_eq!(rd_env_step(end), 0, "round 4 ({})", run_error_text());
        assert_eq!(
            hero(),
            start - 18,
            "round 4 must be the 18-damage Attack (Actions[1] = attack, (4-1) % 2 = 1)"
        );
    }

    /// §173：Book of Stabbing 的 Multi Stab 是 6×N，N = 使用次数 + 2 —— 所以是 18 / 24 / 30。
    ///
    /// 这条测的是**计数器 + `node.repeat`**：`setCombatantCounter` 把 `book_stab_uses` 加一，
    /// `repeat` 的 Count 读 `uses + 2`。内核里 `fx.incrementCounter` 没有 dispatch，所以递增是
    /// "读 + 1 再写回"；写错的话三下会是同一个数字。
    #[test]
    fn book_of_stabbing_escalates_by_its_own_use_count() {
        let session = crate::build_session_at(7, "enc_book_of_stabbing", 200, None, 0)
            .expect("the book of stabbing encounter");
        crate::install_session(session);

        let hero = || rd_env_observe(4);
        let mut last = hero();
        // `Actions = [multi_stab, big_stab]`, so round 1 is the Multi Stab; the enemy turn and the
        // hero turn alternate, so three Multi Stabs are rounds 1, 3 and 5.
        for (round, expected) in [(1, 18), (3, 24), (5, 30)] {
            // End turns until the enemy's `round` counter reaches this one.
            while crate::combat_round() < round {
                let end = rd_env_action_index_of_end_turn();
                assert!(end >= 0, "the hero can end the turn");
                assert_eq!(rd_env_step(end), 0, "round {round} ({})", run_error_text());
            }
            let taken = last - hero();
            assert_eq!(
                taken, expected,
                "round {round}: Multi Stab must deal 6 x (uses + 2) = {expected}, took {taken}"
            );
            last = hero();
        }
    }

    /// The end-turn action's index, or `-1`.'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn lagavulin_sleeps_for_three_rounds" not in text
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, TESTS))
    print("two mechanic tests added")


if __name__ == "__main__":
    main()
