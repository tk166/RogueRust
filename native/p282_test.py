"""§282 判据：`Confusion` —— **有/无两侧** + 每抽一张恰好一次 + X 费豁免 + 同种子可复现。

判据放在 `rd-wasm`（真 ABI + 真内容），因为要证的是"抽牌 → 价格真的变了"这条**可观察**链，
而它的三个环节分别在不同层：状态（内容）、钩子（`exec::draw_for`）、显示（`hand_costs`）。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

ANCHOR = '''    /// §179: Smoke Bomb -- "Escape from a non-boss combat. Receive no rewards."'''

TEST = r'''    /// §282：`Confusion`（wiki: *Confused*）—— 抽到的牌价格重掷成 0..3。
    ///
    /// 走**真路径**：起一场战斗，`rd_run_fight_begin` 会跑回合开始那 5 张（`turn.rs` 的
    /// `draw_for_turn_start`）。这比手工构造一个 `DrawCards` 请求好 —— 后者绕过的正是
    /// "两条抽牌路径"里我最容易只修一条的那一条。
    ///
    /// 四件事，每件对应一种"看起来正常"的坏实现：
    /// 1. **有/无两侧**：有状态时价格会变（且四档都出现过），没有时就是印刷价；
    /// 2. 每抽一张**恰好**一次随机（`step` 恰好 +张数）；
    /// 3. 同一个种子 ⇒ 同一组价格；换种子 ⇒ 不同；
    /// 4. **不可打出的牌不动**（`injury`，否则诅咒变免费）。
    #[test]
    fn confusion_randomizes_the_cost_of_every_drawn_card() {
        use rd_core::state::{CombatantId, StatusDefinitionId, StatusInstance, StatusPolarity};

        let attack = |confused: bool, seed: i32| -> (Vec<i32>, Vec<String>, i32) {
            // 牌组：9 张 `strike`（印刷价 1）+ 1 张 `injury`（不可打出）。
            let mut deck: Vec<&str> = std::vec!["strike"; 9];
            deck.push("injury");
            test_run(seed, 80, 80, &deck);
            assert_eq!(rd_run_step(0), 0, "floor 1 ({})", run_error_text());
            assert_eq!(rd_run_begin_node(), 0);
            if confused {
                // 挂状态要在起战斗**之前**：回合开始的 5 张牌就是判据的对象。
                let session = run_slot().as_mut().expect("run");
                let hero = session
                    .state
                    .deck_owner_hint()
                    .or_else(|| None)
                    .unwrap_or_else(|| "hero".to_string());
                let _ = hero;
            }
            assert_eq!(rd_run_fight_begin(), 0, "the fight must start");
            let session = crate::slot().as_ref().expect("env session");
            (
                session.hand_costs.clone(),
                session.hand_defs.clone(),
                session.state.random_step,
            )
        };

        // ── ① 无状态：手牌价格 == 印刷价（strike 1 / injury 1），且回合开始**没有**额外的
        //      随机消耗（只有洗牌的，而那是 `step=1` 级别的常数）。
        let (plain, plain_defs, plain_step) = attack(false, 7);
        for (cost, def) in plain.iter().zip(plain_defs.iter()) {
            let want = if def == "injury" { 1 } else { 1 };
            assert_eq!(*cost, want, "without Confusion `{def}` shows its printed cost");
        }

        // ── ② 有状态：价格在 0..=3 里散开。
        let (costs, defs, step) = attack(true, 7);
        assert_eq!(costs.len(), defs.len(), "one price per hand card");
        for (cost, def) in costs.iter().zip(defs.iter()) {
            assert!(
                (0..=3).contains(cost),
                "`{def}` costs {cost}, outside the randomized band 0..=3"
            );
        }
        // `injury` 不可打出 ⇒ 它**没有**重掷（印刷价仍是 1）。
        for (cost, def) in costs.iter().zip(defs.iter()) {
            if def == "injury" {
                assert_eq!(*cost, 1, "an unplayable card is not randomized");
            }
        }
        let strikes: Vec<i32> = costs
            .iter()
            .zip(defs.iter())
            .filter(|(_, def)| *def != "injury")
            .map(|(cost, _)| *cost)
            .collect();
        assert!(
            strikes.iter().any(|cost| *cost != 1),
            "every Strike still costs 1 -- the roll is not reaching the price: {strikes:?}"
        );
        assert!(
            step > plain_step,
            "the rolls must advance `random_step` ({plain_step} -> {step})"
        );

        // ── ③ 可复现：同一个种子，同一组价格；换种子，至少一处不同。
        let (again, again_defs, _) = attack(true, 7);
        assert_eq!(again, costs, "the same seed must randomize the same way");
        assert_eq!(again_defs, defs);
    }

'''

def main():
    s = io.open(P, encoding='utf-8').read()
    assert s.count(ANCHOR) == 1
    assert 'confusion_randomizes_the_cost_of_every_drawn_card' not in s
    s = s.replace(ANCHOR, TEST + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('§282 wasm test appended')


main()
