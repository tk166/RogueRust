"""§292：wasm 侧判据 —— 拾取欠账**真的**被兑现，`sacred_bark` 真的把药水翻倍。

这两件事都只能在 wasm 判：欠账要用**遗物池/药水池**（只有这一层有），药水倍率在
`rd_env_use_potion` 那一处。
"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

TESTS = r'''
    // =============================================================================================
    // §292：拾取欠账的兑现 + 药水倍率
    // =============================================================================================

    /// `calling_bell` / `cauldron` 的欠账**在 wasm 兑现**（`settle_pickup_debts`）。
    ///
    /// 判据的三段，每一段都必须有：① 拾取那一刻欠账被记下；② 兑现之后腰带/药水真的多了；
    /// ③ 欠账被清掉（否则下一次入口会重复付）。缺任何一段，"欠账"就只是两个字段。
    #[test]
    fn the_pickup_debts_are_paid_and_cleared() {
        let deck = ["strike", "strike", "strike", "strike", "strike",
                    "defend", "defend", "defend", "defend", "bash"];
        test_run(7, 80, 80, &deck);
        let pool = crate::run::full_pool(content(), false).expect("the card pool");
        // ① `calling_bell`：诅咒当场进牌组，三件遗物记成欠账。
        let deck_before = run_slot().as_ref().expect("a run").state.deck().len();
        run_slot()
            .as_mut()
            .expect("a run")
            .state
            .push_relic("calling_bell", &pool)
            .expect("calling_bell");
        let owed_relics = run_slot().as_ref().expect("a run").state.pickup_relics();
        assert_eq!(owed_relics, 3, "three relics are owed");
        assert_eq!(
            run_slot().as_ref().expect("a run").state.deck().len(),
            deck_before + 1,
            "and the curse is already in the deck"
        );
        // ② 兑现。
        let relics_before = run_slot().as_ref().expect("a run").state.relics().len();
        settle_pickup_debts();
        let relics_after = run_slot().as_ref().expect("a run").state.relics().len();
        assert_eq!(relics_after, relics_before + 3, "three relics arrived");
        // ③ 欠账清掉。
        assert_eq!(
            run_slot().as_ref().expect("a run").state.pickup_relics(),
            0,
            "and the debt is gone"
        );

        // `cauldron`：5 瓶欠账，腰带 3 格 ⇒ 装 3 瓶、欠 2 瓶（文档记的偏差）。
        run_slot()
            .as_mut()
            .expect("a run")
            .state
            .push_relic("cauldron", &pool)
            .expect("cauldron");
        assert_eq!(
            run_slot().as_ref().expect("a run").state.pickup_potions(),
            5,
            "five brews are owed"
        );
        settle_pickup_debts();
        let run = run_slot().as_ref().expect("a run");
        assert_eq!(run.state.potions().len(), 3, "the belt holds three");
        assert_eq!(run.state.pickup_potions(), 2, "two brews stay owed (documented)");
        // 腰带满了之后**不再**兑现（不能无限循环）。
        settle_pickup_debts();
        assert_eq!(
            run_slot().as_ref().expect("a run").state.potion_slots(),
            3,
            "the rule is still three slots"
        );
    }

    /// §292：`sacred_bark` 把药水的**数值**翻倍，而 `POT` 行本身不动。
    ///
    /// 口径：`rd_env_use_potion` 里那个 `amount`（`run_atoms` 与战斗层原子共用同一个数）。
    #[test]
    fn sacred_bark_doubles_the_potion_amount_the_abi_reads() {
        let deck = ["strike", "strike", "strike", "strike", "strike",
                    "defend", "defend", "defend", "defend", "bash"];
        for (relic, expected_percent) in [("sacred_bark", 200), ("", 100)] {
            test_run(7, 80, 80, &deck);
            if !relic.is_empty() {
                run_slot()
                    .as_mut()
                    .expect("a run")
                    .state
                    .push_relic(relic, &[])
                    .expect("sacred_bark");
            }
            let percent = run_slot().as_ref().expect("a run").state.potion_effect_percent();
            assert_eq!(percent, expected_percent, "`{relic}` -> {expected_percent}%");
        }
        // 内容里那条 `POT` 行没被改：倍率只在**用**的那一刻乘。
        let image = content();
        let row = (0..image.potion_count())
            .filter_map(|index| image.potion(index))
            .find(|potion| potion.id == "fire_potion")
            .expect("fire_potion is in the image");
        assert_eq!(row.amount, 15, "the row still says 15 (engine does not edit content)");
    }
'''

TESTS = TESTS.rstrip('\n')


def main():
    s = io.open(RUN, encoding='utf-8').read()
    marker = '\n#[cfg(test)]\nmod tests {'
    assert s.count(marker) == 1, s.count(marker)
    # 模块的收尾 `}` 是文件最后一个 `\n}`。
    assert s.rstrip('\n').endswith('}')
    cut = s.rstrip('\n').rfind('\n}')
    s = s[:cut] + TESTS + s[cut:]
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(s)
    print('wasm tests appended')


main()
