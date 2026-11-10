"""§324 判据 —— `augmenter` 的两件内核东西。

`rd-run` 四条：
1. `transform_choose:2` ⇒ `pickup_change = Transform`、`pickup_picks = 2`（**欠账**通道，不是问句）；
2. 取两次之后欠账清空；取一次时还剩一次（两侧）；
3. 牌组空 ⇒ `DeckEmpty`（一个字节不改）；**已经欠着**别的改牌 ⇒ `WrongPhase`（不覆盖别人的欠账）；
4. `mutagenic_strength` ⇒ 开战给**两条**状态（`strength 3` + `lose_strength 3`）。

`rd-wasm` 一条端到端：`?` 房开 `augmenter` → `[Become Test Subject]` → 欠 2 次，选两张各变一次。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'
ANCHOR = """    /// §188: a list that fails **in the middle** must not half-apply.
"""

TESTS = '''    /// §324：`transform_choose:2` 走的是**拾取欠账**通道（没有问句、与 `pending` 无关）。
    #[test]
    fn transform_choose_owes_two_transforms_through_the_pickup_channel() {
        let pool = basic_pool();
        let mut run = RunState::new(7, 80, 0, &["strike", "defend", "bash"])
            .expect("a run");
        run.begin_event("augmenter", "augmenter").expect("the event");
        run.resolve_event(
            EventEffect::parse("transform_choose:2", 2).expect("parses").0,
            None,
            &pool,
        )
        .expect("owing two transforms");
        assert_eq!(run.pickup_change(), Some(DeckChange::Transform), "the debt kind");
        assert_eq!(run.pickup_picks(), 2, "two of them");
        // 事件本身**已经收尾**：欠账与 `pending` 是两条通道。
        assert_eq!(run.pending(), Pending::None, "the room settled, the debt lives on");

        // 取一次 ⇒ 还剩一次；再取一次 ⇒ 清空（两侧）。
        run.pickup_card(0, &pool).expect("the first");
        assert_eq!(run.pickup_picks(), 1);
        assert_eq!(run.pickup_change(), Some(DeckChange::Transform));
        run.pickup_card(0, &pool).expect("the second");
        assert_eq!(run.pickup_picks(), 0);
        assert_eq!(run.pickup_change(), None, "the debt is gone");
        assert_eq!(run.deck_len, 3, "transform keeps the size");
    }

    /// §324：两条拒绝 —— 牌组空（没得选）与**已经欠着**（不覆盖别人的欠账）。
    #[test]
    fn transform_choose_refuses_an_empty_deck_and_an_existing_debt() {
        let pool = basic_pool();
        // ① 牌组空。
        let mut empty = RunState::new(7, 80, 0, &[]).expect("a run");
        empty.begin_event("augmenter", "augmenter").expect("the event");
        let before = empty;
        assert_eq!(
            empty.resolve_event(EventEffect::OwedTransforms(2), None, &pool),
            Err(RunError::DeckEmpty),
            "nothing to point at"
        );
        assert!(empty == before, "not one byte moved");

        // ② 已经欠着（`empty_cage` = 移除 2 张）。
        let mut run = RunState::new(7, 80, 0, &["strike", "defend", "bash"]).expect("a run");
        run.push_relic("empty_cage", &TYPED_CARDS).expect("empty cage");
        assert_eq!(run.pickup_change(), Some(DeckChange::Remove), "the cage owes removals");
        run.begin_event("augmenter", "augmenter").expect("the event");
        let before = run;
        assert_eq!(
            run.resolve_event(EventEffect::OwedTransforms(2), None, &pool),
            Err(RunError::WrongPhase),
            "another relic's debt must not be overwritten"
        );
        assert!(run == before, "not one byte moved");
        assert_eq!(run.pickup_change(), Some(DeckChange::Remove), "the cage's debt survives");
        assert_eq!(run.pickup_picks(), 2);
    }

    /// §324：`mutagenic_strength` —— 开战给**两条**状态（+3 力量与"回合末失 3 力量"）。
    ///
    /// 后半条不能只靠"力量是 3"证明：少了 `lose_strength` 的局在第一回合末**不会掉**力量，
    /// 而那正好是这件遗物"fleeting"的那一半（它是纯收益 vs 一次性加成的差别）。
    #[test]
    fn mutagenic_strength_grants_strength_plus_its_own_expiry() {
        let mut run = ironclad();
        run.push_relic("mutagenic_strength", &TYPED_CARDS).expect("mutagenic strength");
        let bonus = run.combat_bonus();
        let mut strength = None;
        let mut expiry = None;
        for index in 0..bonus.status_count {
            let entry = bonus.statuses[index];
            if entry.id == "standard.strength" {
                strength = Some(entry.stacks);
            }
            if entry.id == "standard.lose_strength" {
                expiry = Some(entry.stacks);
            }
        }
        assert_eq!(strength, Some(3), "3 Strength at combat start");
        assert_eq!(expiry, Some(3), "and the marker that takes it back at turn end");

        // 负向对照：没有这件遗物时两条都不在（否则上面那一半在"它给所有状态"时也会绿）。
        let plain = ironclad().combat_bonus();
        for index in 0..plain.status_count {
            let entry = plain.statuses[index];
            assert_ne!(entry.id, "standard.lose_strength", "a plain run has no expiry marker");
        }
    }

'''


def main():
    t = io.open(STATE, encoding='utf-8').read()
    assert t.count(ANCHOR) == 1, 'anchor'
    assert 'fn transform_choose_owes_two_transforms' not in t, 'already patched'
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS + ANCHOR))
    print('§324 tests inserted')


main()
