"""§251 判据：A 组 5 张（`bite` / `expunger` / `shiv` / `smite` / `beta`）。

纪律照 §249.4 / §250：
* **判据牌不许碰伤害** —— 这里要"打牌"的地方用 `defend`；
* **量差值不量绝对值** —— 回血、掉血都取前后差；
* **走显式入口**（`run_card_lifecycle` / `try_hand_turn_end_lifecycle`），不驱动整台回合机。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §248：`Enlightenment` —— **降到至多 1**'

TESTS = r'''    /// §251：`Bite` —— 打 7 掉 7、回 2（**固定**回血量，不是 Reaper 那种"按掉血回"）。
    ///
    /// 判据两侧：敌人掉 7；英雄回 2（先把英雄的血压到上限以下，否则回血被上限吃掉 ⇒ 看起来
    /// "没回"）。升级版 8/3 也测一次 —— 只测基础行会漏掉"两条行共用一份节目"的错。
    #[test]
    fn bite_deals_its_damage_and_heals_a_fixed_amount() {
        let content = sts_image();
        for (card_id, damage, healing) in [("bite", 7i32, 2i32), ("bite+", 8, 3)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            beefy(&mut state);
            fill_energy(&mut state, 99);
            // 把英雄压到"回得进去"的状态：`arena()` 里英雄是满血。
            let hero_before = {
                let Some(hero) = state.combatant_mut(&cid("hero")) else {
                    panic!("hero");
                };
                hero.health_current = hero.health_current.saturating_sub(5);
                hero.health_current
            };
            give_card(&mut state, "hero", CardZone::Hand, "bite1", card_id, None);
            let card = crate::state::CardInstanceId::new("bite1").expect("id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("bite is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(health(&state, "enemy_a"), 500 - damage, "{card_id}: damage");
            assert_eq!(health(&state, "hero"), hero_before + healing, "{card_id}: healing");
        }
    }

    /// §251：`Expunger` —— `Deal 9 damage **X** times`，而 X 是**每副本**的计数器。
    ///
    /// wiki 写得很明确：X 不是"打出它时的能量"，而是造它的那张牌被打出时的能量 ⇒ 它必须
    /// 存在副本上。我们没有任何内容会造它（`Conjure Blade` 是观者牌、不在范围），所以
    /// **X = 0 ⇒ 这张牌什么都不做**（wiki: "If X is 0, this card does nothing"）。
    ///
    /// 判据两段：① 计数器缺席 ⇒ 0 点伤害（防"把缺席当 1"）；② 手写一个 X = 3 ⇒ 27 点
    /// （9 × 3，且是**一次出牌**打完 —— 防"每回合打一次"那种错）。
    #[test]
    fn expunger_repeats_by_its_per_copy_x() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        beefy(&mut state);
        fill_energy(&mut state, 99);

        // ① X = 0（没有任何内容写这个计数器）⇒ 0 伤害。
        give_card(&mut state, "hero", CardZone::Hand, "exp0", "expunger", None);
        let card = crate::state::CardInstanceId::new("exp0").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("expunger is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 500, "X = 0 means it does nothing");

        // ② 手写 X = 3 ⇒ 27。
        give_card(&mut state, "hero", CardZone::Hand, "exp3", "expunger", None);
        {
            let Some(zones) = state.card_zones(&cid("hero")) else {
                panic!("zones");
            };
            let slot = zones.slot_at(CardZone::Hand, 0).expect("the card");
            let key = crate::state::CounterId::new("standard.expunger_x").expect("counter");
            let Some(instance) = state.card_mut(slot) else {
                panic!("card");
            };
            instance.set_mark_counter(key, 3).expect("it fits");
        }
        let card = crate::state::CardInstanceId::new("exp3").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("expunger is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 500 - 27, "9 damage × 3");
    }

    /// §251：`Shiv` / `Smite` —— 两张纯数字牌，但**它们的关键字不一样**。
    ///
    /// `Shiv` 0 费打 4、`Smite` 1 费打 12 且 **Retain**（回合末不弃）。判据看的是
    /// `TurnEndHandDestinationZone`：`Smite` 是 `Hand`（留着），`Shiv` 是 `DiscardPile`。
    /// 只测伤害会漏掉 Retain —— 那是这两张牌唯一的区别。
    #[test]
    fn shiv_and_smite_differ_in_retain_not_only_in_damage() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        beefy(&mut state);
        fill_energy(&mut state, 99);
        give_card(&mut state, "hero", CardZone::Hand, "shiv1", "shiv", None);
        give_card(&mut state, "hero", CardZone::Hand, "smite1", "smite", None);

        let shiv = crate::state::CardInstanceId::new("shiv1").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), shiv, Some(cid("enemy_a"))),
        )
        .expect("shiv is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 496, "shiv: 4 damage");
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            1,
            "shiv exhausts"
        );

        let smite = crate::state::CardInstanceId::new("smite1").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), smite, Some(cid("enemy_a"))),
        )
        .expect("smite is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 484, "smite: 12 damage");
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            2,
            "smite exhausts too"
        );

        // Retain 是**没打出的那一张**的属性：再塞一张 Smite 进手牌，回合末它该留在手上。
        give_card(&mut state, "hero", CardZone::Hand, "smite2", "smite", None);
        host.try_hand_turn_end_lifecycle(&mut state, &cid("hero"))
            .expect("the turn-end lifecycle runs");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            1,
            "`Retain` keeps it in hand (the end-of-turn discard moved the rest)"
        );
    }

    /// §251：`Beta` —— 把一张 **Omega** 放进抽牌堆（`§249` 的 Omega 现在有"来源"了）。
    ///
    /// 判据三点：① 抽牌堆多一张、定义是 `omega`；② `Beta` 自己进消耗堆；
    /// ③ 升级版只改费用（2 → 1），正文不变 —— 那是 wiki 唯一写的差别。
    #[test]
    fn beta_shuffles_an_omega_into_the_draw_pile() {
        let content = sts_image();
        let mut host = Host::new(&content);
        let mut state = arena();
        fill_energy(&mut state, 99);
        give_card(&mut state, "hero", CardZone::Hand, "beta1", "beta+", None);
        let card = crate::state::CardInstanceId::new("beta1").expect("id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, None),
        )
        .expect("beta is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        let Some(zones) = state.card_zones(&cid("hero")) else {
            panic!("zones");
        };
        assert_eq!(zone_count(&state, "hero", CardZone::DrawPile), 1, "an Omega landed");
        let slot = zones.slot_at(CardZone::DrawPile, 0).expect("the omega");
        assert_eq!(
            state.card(slot).expect("card").definition_id.as_str(),
            "omega",
            "it is Omega, not something else"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            1,
            "Beta exhausts itself"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'bite_deals_its_damage_and_heals_a_fixed_amount' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 5 tests')


main()
