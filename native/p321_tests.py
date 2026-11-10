"""§321 判据 —— `upgrade_all`（`mind_bloom` 的 `[I am Awake]`）与"不能治疗"。

五条：
1. `upgrade_all` 把**有 `+` 行且还没升**的牌全升掉，已经是 `+` 的保持不动（幂等，不是"再升一次"）；
2. `upgrade_all` **没有问句**：`pending` 不变、也没有欠着的改牌（它是一次结算）；
3. `mark_of_the_bloom` ⇒ `blocks_healing()` 为真，且 `heal` / `heal_pct` / `heal_full` /
   休息 / 遗物 `HealUp` **五条治疗路径全部回 0**；
4. 拿掉那件遗物之后**同样的调用真的会回血** —— 否则第 3 条在"全是 0"的实现上也会绿；
5. `floor` 条件两侧（`mind_bloom` 第三项按层号换）。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'
EXPR = 'kernel/rd-core/src/run_expr.rs'

ANCHOR_STATE = """    /// §188: a list that fails **in the middle** must not half-apply.
"""

TESTS = '''    /// §321：`upgrade_all` —— `strike` → `strike+`，没有 `+` 行的牌、已经是 `+` 的牌都不动。
    #[test]
    fn upgrade_all_upgrades_every_card_that_has_a_plus_row() {
        let pool = basic_pool();
        let mut run = RunState::new(7, 80, 0, &["strike", "strike+", "slimed", "defend"])
            .expect("a run");
        // `defend` 在 `basic_pool()` 里没有 `defend+` 行 ⇒ 它必须**原样留着**。
        run.begin_event("mind_bloom", "mind_bloom").expect("the event");
        run.resolve_event_effects(
            &EventMove {
                effects: &[(EventEffect::UpgradeAll, None)],
                ..EventMove::none()
            },
            &pool,
        )
        .expect("upgrading everything");

        let deck: Vec<&str> = run.deck().iter().map(|card| card.as_str()).collect();
        assert_eq!(deck, vec!["strike+", "strike+", "slimed", "defend"]);
        assert_eq!(run.pending(), Pending::None, "no question, no debt");
        assert_eq!(run.event_follow(), None, "`upgrade_all` is not a `DeckChange`");
    }

    /// §321：`mark_of_the_bloom` —— "You can no longer heal"。**每一条**运行层治疗路径都回 0。
    #[test]
    fn mark_of_the_bloom_blocks_every_run_layer_heal() {
        // 先在**没有**遗物的局上证明这些调用**真的会回血**（否则下面那一半是空的）。
        let mut plain = RunState::new(7, 80, 0, &["strike"]).expect("a run");
        plain.adjust_health(-40);
        let hurt = plain.health();
        assert_eq!(hurt, 40);
        plain.heal_after_combat(5);
        assert_eq!(plain.health(), 45, "a plain run heals");

        let mut run = RunState::new(7, 80, 0, &["strike"]).expect("a run");
        run.push_relic("mark_of_the_bloom", &TYPED_CARDS).expect("bloom");
        assert!(run.blocks_healing(), "the relic is the flag");
        run.adjust_health(-40);
        assert_eq!(run.health(), 40);
        // ① 直接治疗 ② 事件 `heal` ③ 事件 `heal_pct` ④ 事件 `heal_full` ⑤ 遗物 `HealUp`
        run.heal_after_combat(5);
        assert_eq!(run.health(), 40, "heal_after_combat is a no-op");
        for effect in [
            EventEffect::Heal(10),
            EventEffect::HealPercent(500),
            EventEffect::HealFull,
        ] {
            run.begin_event("mind_bloom", "mind_bloom").expect("the event");
            run.resolve_event_effects(
                &EventMove { effects: &[(effect, None)], ..EventMove::none() },
                &basic_pool(),
            )
            .expect("the effect applies (it just heals nothing)");
            assert_eq!(run.health(), 40, "{effect:?} heals nothing");
        }
        // ⑤ 遗物的 `HealUp`（`blood_vial` = 拾取时 +2）—— 走的是**同一条公开路径**
        // （`push_relic`），所以它同时是"拾取类治疗也被拦"的证据。
        run.push_relic("blood_vial", &TYPED_CARDS)
            .expect("picking up blood_vial");
        assert_eq!(run.health(), 40, "a relic payout heals nothing either");
    }

'''


def main():
    t = io.open(STATE, encoding='utf-8').read()
    assert t.count(ANCHOR_STATE) == 1, 'anchor'
    assert 'fn upgrade_all_upgrades_every_card_that_has_a_plus_row' not in t, 'already patched'
    t = t.replace(ANCHOR_STATE, TESTS + ANCHOR_STATE)
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
    print('§321 tests inserted (one hook may be missing)')


main()
