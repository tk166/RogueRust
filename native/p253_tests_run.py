"""§253 判据：`ritual_dagger` 的跨场成长（运行层 ↔ 战斗两头接）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
ANCHOR = "    fn the_gold_a_thief_carried_away_is_the_only_gold_lost() {"

TESTS = r'''    /// §253：`Ritual Dagger` 的成长**跨战斗存活** —— 这才是 wiki 那个 "permanently"。
    ///
    /// 判据走真实的两场战斗，而不是"调一下 set_mark 再读回来"（那样只测了存取器）：
    /// ① 第一场：把那一条 counters 写成 3（模拟"致命击杀了一次"），`fight_end`；
    /// ② 运行层的牌位 0 上应当有 `standard.ritual_dagger_bonus = 3`；
    /// ③ 第二场：`fight_begin` 之后，**新的那一份实例**上应当带着 3 ——
    ///    于是它这一场打出的伤害是 15 + 3×3 = 24（而不是 15）。
    ///
    /// 第 ③ 段是整件事的意义：只测 ② 的话，"存进去了但没人读"也能过。
    #[test]
    fn ritual_dagger_growth_survives_the_fight() {
        let deck = ["ritual_dagger", "strike", "strike", "strike", "strike", "strike",
                    "defend", "defend", "defend", "defend"];
        test_run(11, 70, 80, &deck);
        // ① 第一场：把牌位 0 那一份的计数器写成 3，然后结算这场战斗。
        assert_eq!(rd_run_fight_begin(), 0, "the first fight starts");
        let instance = rd_core::state::CardInstanceId::new("card_000000").expect("id");
        crate::combat_set_mark(&instance, "standard.ritual_dagger_bonus", 3)
            .expect("the mark is writable");
        rd_run_fight_end();
        // ② 运行层记下了它。
        let session = run_slot().as_ref().expect("a run");
        let mark = session.state.mark(0).expect("slot 0 carries a mark");
        assert_eq!(mark.key.as_str(), "standard.ritual_dagger_bonus");
        assert_eq!(mark.value, 3, "the growth survived fight_end");

        // ③ 第二场：新的那一份实例带着同一个值。
        assert_eq!(rd_run_fight_begin(), 0, "the second fight starts");
        let fresh = crate::combat_card_by_instance(&instance).expect("the same slot exists");
        assert_eq!(fresh.definition_id.as_str(), "ritual_dagger");
        let carried = fresh
            .marks
            .iter()
            .find(|counter| counter.key.as_str() == "standard.ritual_dagger_bonus")
            .map(|counter| counter.value);
        assert_eq!(carried, Some(3), "the next fight's copy starts grown");
    }

    /// §253：**对号关系坏了要响亮**，不许静默丢弃。
    ///
    /// 反证：把牌组第 0 位换成另一张牌**但保留它的 mark**（直接写运行层），于是"牌位 0 的
    /// 实例"与"牌位 0 的定义"对不上 —— `apply_run_marks` 必须报错，而不是"跳过那个牌位"。
    /// 跳过就是这一节要消灭的那种错：成长没了，而页面上什么都看不出来。
    #[test]
    fn a_broken_slot_correspondence_is_an_error_not_a_silent_skip() {
        let deck = ["strike", "strike", "defend", "defend", "bash"];
        test_run(12, 70, 80, &deck);
        {
            let session = run_slot().as_mut().expect("a run");
            // 牌位 0 是 `strike`，但我们把它的 mark 指到 `ritual_dagger` 的计数器上 ——
            // 对号本身仍然成立（实例 0 就是 strike），所以这一条**不该**报错；它证明
            // "key 是谁"不影响对号。真正会报错的是下面那一步。
            session
                .state
                .set_mark(0, "standard.ritual_dagger_bonus", 3)
                .expect("the mark is writable");
        }
        assert_eq!(rd_run_fight_begin(), 0, "the fight starts");

        // 现在把战斗里那一份实例的**定义**换掉：模拟"牌位 ↔ 实例"漂了。
        {
            let session = slot().as_mut().expect("a fight");
            let hero = session.hero_id().expect("a hero");
            let instance = rd_core::state::CardInstanceId::new("card_000000").expect("id");
            let (_, index) = session.state.find_card(&hero, &instance).expect("it exists");
            let card = session.state.card_mut(index).expect("the card");
            card.definition_id =
                rd_core::state::CardDefinitionId::new("defend").expect("a definition");
        }
        let message = {
            let session = run_slot().as_mut().expect("a run");
            apply_run_marks(session).expect_err("a drifted correspondence must be loud")
        };
        assert!(
            message.contains("漂了"),
            "the message must name the drift, got {message:?}"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) >= 1, src.count(ANCHOR)
    assert 'ritual_dagger_growth_survives_the_fight' not in src, 'already patched'
    src = src.replace(ANCHOR, TESTS + ANCHOR, 1)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src)
    print('patched run.rs with 2 cross-fight tests')


main()
