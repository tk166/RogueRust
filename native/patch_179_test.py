"""§179 test: `standard.card_cost_override` survives the play, `standard.card_cost_delta` does not."""
import io

PLAY = "kernel/rd-core/src/play.rs"

ANCHOR = """    #[test]
    fn the_per_copy_price_is_consumed_by_the_play() {"""

NEW = r'''    /// §179: `standard.card_cost_override` 与它旁边那个 delta 的**唯一**区别 ——
    /// delta 被出牌消费（"一次承诺"），override **不被消费**（Snecko Oil："for the rest of
    /// combat"）。两张牌打两次，第二次的价格是判据。
    ///
    /// 这条测试存在的理由：如果有人把两个计数器"简化"成一个，它会红 —— 而功能上那会以
    /// "这瓶药只有效一次"的形式坏掉，没有任何别的闸门看得见。
    #[test]
    fn the_randomized_price_survives_the_play_but_the_delta_does_not() {
        let blob = core_image();
        let content = parse(&blob);
        let mut state = arena();
        give_card(&mut state, "hero", CardZone::Hand, "card_h1", "paper_cut");
        let (_, slot) = find_card_slot(
            &state,
            &cid("hero"),
            &CardInstanceId::new("card_h1").unwrap(),
        )
        .expect("card_h1 在手");
        // 绝对价 0：随机成 0 费的那张牌，和"没有覆盖"是两件事（`mark_counter_opt` 的存在理由）。
        state
            .card_mut(slot)
            .unwrap()
            .set_mark_counter(
                CounterId::new(crate::state::CARD_COST_OVERRIDE_COUNTER).unwrap(),
                0,
            )
            .unwrap();

        let report = play_card(
            &mut state,
            Some(&content),
            &request("card_h1", Some("enemy_a")),
        )
        .expect("0 费的牌当然打得出去");
        assert!(report.played);
        assert_eq!(
            report.paid.amount_for(&energy()),
            None,
            "绝对价 0 ⇒ 一条 0 的费用都不进表"
        );
        assert_eq!(energy_of(&state, "hero"), 3, "一滴能量都没扣");
        assert_eq!(health_of(&state, "enemy_a"), 14, "牌照常生效（6 点）");

        // ★ 与 delta 相反：这个承诺**不是**一次性的。牌回到手里，价格还是 0。
        let (zone, slot) = find_card_slot(
            &state,
            &cid("hero"),
            &CardInstanceId::new("card_h1").unwrap(),
        )
        .expect("还在牌区里");
        state
            .move_card(
                &cid("hero"),
                zone,
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
        .expect("第二次也一样");
        assert_eq!(
            report.paid.amount_for(&energy()),
            None,
            "Snecko 的价是**这一场战斗**的价，不是一次性的折扣"
        );
        assert_eq!(energy_of(&state, "hero"), 3);
    }

    #[test]
    fn the_per_copy_price_is_consumed_by_the_play() {'''


def main():
    text = io.open(PLAY, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    io.open(PLAY, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("§179 pricing test inserted")


if __name__ == "__main__":
    main()
