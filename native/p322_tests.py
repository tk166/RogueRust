"""§322 判据：`card:` / `curse:` 的 `Amount` 真的生效（1 张 vs 3 张），以及 `remove_all:<id>`。

为什么必须有：这条修复之前，`card:madness` Amount 2 与 `curse:normality` Amount 2 都只给
**一张**，而内容门与所有判据都绿 —— "屏幕上写 2、牌组里 1"是那种只在数牌时才发现的错。
所以这一条判的是**张数**，而且 1 与 3 两侧都测（常量 1 的实现在 3 那一侧会红）。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'
ANCHOR = """    /// §188: a list that fails **in the middle** must not half-apply.
"""

TESTS = '''    /// §322：`curse:<id>` 的 `Amount` 是**张数**（1 与 3 两侧）。
    #[test]
    fn a_curse_payload_is_granted_as_many_times_as_its_amount() {
        let pool = curse_pool();
        for (amount, expect) in [(1i32, 1u8), (3, 3)] {
            // `Amount` 0 读作 1（内容里大多数 `curse:` 不写 Amount）。
            let parsed = EventEffect::parse("curse:injury", amount).expect("parses");
            assert_eq!(parsed, (EventEffect::GainCurse(expect), Some("injury")));
            let mut run = RunState::new(7, 80, 0, &["strike"]).expect("a run");
            run.begin_event("mind_bloom", "mind_bloom").expect("the event");
            run.resolve_event(
                EventEffect::GainCurse(expect),
                Some("injury"),
                &pool,
            )
            .expect("cursed");
            let injuries = run.deck().iter().filter(|card| card.as_str() == "injury").count();
            assert_eq!(injuries, usize::from(expect), "Amount {amount} ⇒ {expect} curse(s)");
        }
        // 0 与 > 5 以外的数字是**内容错误**：解析失败（不截断，也不当 1）。
        assert_eq!(EventEffect::parse("curse:injury", 6), None);
        assert_eq!(EventEffect::parse("curse:injury", -1), None);
        assert_eq!(EventEffect::parse("card:madness", 6), None);
    }

    /// §322：`card:<id>` 的张数同理（`vampires` 的 5 张 Bite、`council_of_ghosts` 的 5 张 Apparition）。
    #[test]
    fn a_card_payload_is_granted_as_many_times_as_its_amount() {
        let pool = curse_pool();
        let mut run = RunState::new(7, 80, 0, &["strike"]).expect("a run");
        run.begin_event("council_of_ghosts", "council_of_ghosts").expect("the event");
        let before = run.deck_len;
        run.resolve_event(EventEffect::GainCard(3), Some("defend"), &pool)
            .expect("three cards");
        assert_eq!(run.deck_len, before + 3, "three copies, not one");
        let defends = run.deck().iter().filter(|card| card.as_str() == "defend").count();
        assert_eq!(defends, 3, "and they are the named card");
    }

    /// §322：`remove_all:<id>` —— 把**这一种**牌全删掉，`+` 行算同一张（`vampires` 的
    /// "Remove all Strikes"）。
    ///
    /// 两侧：`strike` 与 `strike+` 都被删，而 `defend` / `bash` 一张不动。
    /// ⚠️ 相邻的两张 Strike 必须都删掉 —— 正着遍历会跳过第二张（`remove_at` 前移），
    /// 所以牌组里**故意**放两张相邻的。
    #[test]
    fn remove_all_deletes_every_copy_including_plus_rows() {
        let pool = basic_pool();
        let mut run = RunState::new(7, 80, 0, &["strike", "strike", "defend", "bash", "strike+"])
            .expect("a run");
        run.begin_event("vampires", "vampires").expect("the event");
        run.resolve_event(EventEffect::RemoveAllCards, Some("strike"), &pool)
            .expect("removing every Strike");
        let deck: Vec<&str> = run.deck().iter().map(|card| card.as_str()).collect();
        assert_eq!(deck, vec!["defend", "bash"], "three Strikes (one of them `+`) are gone");
        assert_eq!(run.deck_len, 2);

        // 一种都没有 ⇒ 成功（没有可删的），不是错误：`vampires` 在"牌组里没有打击"时仍然给 Bite。
        run.resolve_event(EventEffect::RemoveAllCards, Some("strike"), &pool)
            .expect("nothing left to remove");
        assert_eq!(run.deck_len, 2);
    }

'''


def main():
    t = io.open(STATE, encoding='utf-8').read()
    assert t.count(ANCHOR) == 1, 'anchor'
    assert 'fn a_curse_payload_is_granted_as_many_times_as_its_amount' not in t, 'already patched'
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS + ANCHOR))
    print('§322 tests inserted')


main()
