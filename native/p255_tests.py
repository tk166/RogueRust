"""§255 判据：`Conjure Blade` —— 造出来的 `Expunger` 带着**这一次花的能量**当 X。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §248：`Enlightenment` —— **降到至多 1**'

TESTS = r'''    /// §255：`Conjure Blade` —— 造一张 `Expunger`，把 X 写进**它自己的**计数器。
    ///
    /// 判据四段（每一段都在钉一件不同的事）：
    /// ① 抽牌堆里多一张 `expunger`、`Conjure Blade` 自己进消耗堆；
    /// ② 那张 `Expunger` 的每副本计数器 == 这次花的能量（这里是 3）；
    /// ③ 下一回合把它打出来 ⇒ **27 点**（9 × 3）—— 这一段才是"X 真的接上了"的证据，
    ///    只看计数器会漏掉"计数器写了但 `Expunger` 的节目没读它"；
    /// ④ 升级版 `Conjure Blade+` ⇒ 计数器是 4（`X+1`），打出来 36 点。
    #[test]
    fn conjure_blade_stores_the_energy_as_the_expungers_x() {
        let content = sts_image();
        for (card_id, energy, want_mark, want_damage) in
            [("conjure_blade", 3i32, 3i32, 27i32), ("conjure_blade+", 3, 4, 36)]
        {
            let mut host = Host::new(&content);
            let mut state = arena();
            beefy(&mut state);
            // X 费牌吃**全部**能量 ⇒ 给 3 点，这次就花 3（升级版仍然花 3，只是 X+1）。
            fill_energy(&mut state, energy);
            give_card(&mut state, "hero", CardZone::Hand, "cb1", card_id, None);
            let card = crate::state::CardInstanceId::new("cb1").expect("id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, None),
            )
            .unwrap_or_else(|error| panic!("{card_id} is playable: {error:?}"));
            host.try_resolve_pending_queues(&mut state).expect("drain");

            // ① 抽牌堆里多了一张 expunger；Conjure Blade 自己消耗掉。
            assert_eq!(
                zone_count(&state, "hero", CardZone::DrawPile),
                1,
                "{card_id}: one Expunger"
            );
            assert_eq!(
                zone_count(&state, "hero", CardZone::ExhaustPile),
                1,
                "{card_id}: Conjure Blade exhausts"
            );

            // ② 那张 Expunger 的 X。
            let instance = {
                let Some(zones) = state.card_zones(&cid("hero")) else {
                    panic!("zones");
                };
                let slot = zones.slot_at(CardZone::DrawPile, 0).expect("the expunger");
                let card = state.card(slot).expect("card");
                assert_eq!(card.definition_id.as_str(), "expunger");
                card.id
            };
            let mark = {
                let Some(zones) = state.card_zones(&cid("hero")) else {
                    panic!("zones");
                };
                let slot = zones.slot_at(CardZone::DrawPile, 0).expect("the expunger");
                state
                    .card(slot)
                    .expect("card")
                    .mark_counters()
                    .iter()
                    .find(|counter| counter.key.as_str() == "standard.expunger_x")
                    .map(|counter| counter.value)
            };
            assert_eq!(mark, Some(want_mark), "{card_id}: X is the energy spent (+1 if upgraded)");

            // ③ 把它打出来 ⇒ 9 × X。
            state.move_card(
                &cid("hero"),
                CardZone::DrawPile,
                CardZone::Hand,
                {
                    let Some(zones) = state.card_zones(&cid("hero")) else {
                        panic!("zones");
                    };
                    zones.slot_at(CardZone::DrawPile, 0).expect("the expunger")
                },
                crate::state::ZonePlacement::Bottom,
            )
            .expect("it comes to hand");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), instance, Some(cid("enemy_a"))),
            )
            .expect("the expunger is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                health(&state, "enemy_a"),
                500 - want_damage,
                "{card_id}: 9 damage × X"
            );
        }
    }

    /// §255：**X = 0 是合法的**（wiki: "it is possible to generate an Expunger that deals damage
    /// 0 times"）。零能量打 `Conjure Blade` ⇒ 造出来的那张 X 是 0 ⇒ 打出来什么都**不**做。
    ///
    /// 这条与上一条互补：上一条证明"X 接上了"，这一条证明"X 可以是 0 而不是被当成 1"。
    #[test]
    fn conjure_blade_with_no_energy_makes_a_zero_x_expunger() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        beefy(&mut state);
        // 能量 0：X 费牌仍然可以打（`x_cost_payment` 收 0），X = 0。
        fill_energy(&mut state, 0);
        give_card(&mut state, "hero", CardZone::Hand, "cb0", "conjure_blade", None);
        let card = crate::state::CardInstanceId::new("cb0").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, None),
        )
        .expect("X-cost cards are playable with no energy");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let instance = {
            let Some(zones) = state.card_zones(&cid("hero")) else {
                panic!("zones");
            };
            let slot = zones.slot_at(CardZone::DrawPile, 0).expect("the expunger");
            let card = state.card(slot).expect("card");
            let mark = card
                .mark_counters()
                .iter()
                .find(|counter| counter.key.as_str() == "standard.expunger_x")
                .map(|counter| counter.value);
            assert_eq!(mark, Some(0), "X = 0");
            card.id
        };
        // 把它打出来：0 次 ⇒ 敌人一点血都不掉。
        let slot = {
            let Some(zones) = state.card_zones(&cid("hero")) else {
                panic!("zones");
            };
            zones.slot_at(CardZone::DrawPile, 0).expect("the expunger")
        };
        state
            .move_card(
                &cid("hero"),
                CardZone::DrawPile,
                CardZone::Hand,
                slot,
                crate::state::ZonePlacement::Bottom,
            )
            .expect("to hand");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), instance, Some(cid("enemy_a"))),
        )
        .expect("playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 500, "X = 0 deals nothing");
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'conjure_blade_stores_the_energy' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 2 Conjure Blade tests')


main()
