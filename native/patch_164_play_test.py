"""rd-core play.rs: §161.4's third half — the price is **kept once**.

Without the consumption step a delta is a standing discount for the rest of the fight, and nothing
would notice: the card just reads "free" forever, which looks like a generous rule rather than a
bug. The negative control (`negctl_164.py price`) removes the step and this test goes red.
"""
import io

PATH = "kernel/rd-core/src/play.rs"

ANCHOR = """    #[test]
    fn a_real_deal_damage_card_is_paid_resolved_and_discarded() {"""

TEST = '''    /// 这张副本自己身上的 `standard.card_cost_delta` 读出来（没有 = 0）。
    fn cost_delta_of(state: &CombatState, who: &str, instance: &str) -> i32 {
        let id = CardInstanceId::new(instance).unwrap();
        let Some((_, slot)) = find_card_slot(state, &cid(who), &id) else {
            return 0;
        };
        state
            .card(slot)
            .map(|card| mark_counter(card, CARD_COST_DELTA_COUNTER))
            .unwrap_or(0)
    }

    #[test]
    fn the_per_copy_price_is_consumed_by_the_play() {
        // §161.4：一张牌**自己**的价格。参考 `Cards/CardPlay.cs:176-183`：*"A per-copy price is a
        // promise to ONE card and is kept once: the play has been paid for by now, so the mark is
        // spent here rather than lingering into the next time this card is drawn."*
        //
        // `paper_cut` 印刷 1 能量（`CARD[0]`），所以"这次免费"就是 `-1`。
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        assert_eq!(energy_of(&state, "hero"), 3);

        // 把价格写在那一张牌上（内容侧写它的是 Liquid Memories 那一路，§161.4 的 `resolve_choice`）。
        let (_, slot) = find_card_slot(&state, &cid("hero"), &CardInstanceId::new("card_h1").unwrap())
            .expect("card_h1 在手");
        state
            .card_mut(slot)
            .unwrap()
            .set_mark_counter(CounterId::new(CARD_COST_DELTA_COUNTER).unwrap(), -1)
            .unwrap();
        assert_eq!(cost_delta_of(&state, "hero", "card_h1"), -1);

        let report = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("折扣牌必须打得出去");
        assert!(report.played);
        // 印刷 1 + delta(-1) = 0 ⇒ 归零的条目**不进**费用表（`:488-489`），所以这一条**没付**。
        assert_eq!(
            report.paid.amount_for(&energy()),
            None,
            "免费就是真免费：一条 0 的费用不进表"
        );
        assert_eq!(energy_of(&state, "hero"), 3, "一滴能量都没扣");
        assert_eq!(health_of(&state, "enemy_a"), 14, "牌照常生效（6 点）");

        // ★ 承诺只兑现一次：打完就清零，哪怕这张牌已经进了弃牌堆。
        assert_eq!(
            cost_delta_of(&state, "hero", "card_h1"),
            0,
            "价格必须在**付款之后**消费掉 —— 否则它会跟着这张牌回到手牌，永久免费"
        );

        // 反面控制：把牌拿回手牌再打一次，这次要付满 1 点。
        let (zone, slot) = find_card_slot(&state, &cid("hero"), &CardInstanceId::new("card_h1").unwrap())
            .expect("还在牌区里");
        let from = zone;
        state
            .move_card(
                &cid("hero"),
                from,
                CardZone::Hand,
                slot,
                ZonePlacement::Bottom,
            )
            .unwrap();
        state
            .combatant_mut(&cid("hero"))
            .unwrap()
            .set_resource(energy(), 3, Some(3))
            .unwrap();
        let report = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("第二次也要打得出去");
        assert_eq!(
            report.paid.amount_for(&energy()),
            Some(1),
            "第二次是**原价**：折扣是一次性的，不是这张牌的新印刷价"
        );
        assert_eq!(energy_of(&state, "hero"), 2);
    }

    #[test]
    fn a_real_deal_damage_card_is_paid_resolved_and_discarded() {'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn the_per_copy_price_is_consumed_by_the_play" not in text, "already inserted"
    text = text.replace(ANCHOR, TEST)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("play.rs: the price is consumed by the play (test)")


if __name__ == "__main__":
    main()
