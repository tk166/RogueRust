"""§241 判据：`Havoc`（打出抽牌堆顶 + 不付费 + 进消耗堆 + 攻击随机选目标）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §240：`Infernal Blade` —— "Add a random Attack'

TESTS = r'''    /// §241：`Havoc` —— "Play the top card of your draw pile and Exhaust it."
    ///
    /// 四件事一起钉住，每一件都是"不做就看不出来"的那一类：
    /// ① 打出去的是**抽牌堆顶那张**（不是手牌里随便一张，也不是抽到的别的）；
    /// ② **不付费**：能量一点不掉（`Havoc` 只花自己的 1 费）；
    /// ③ 打完进**消耗堆**（同一张 `Strike` 平时进弃牌堆 —— 所以这一条只能靠强制落区）；
    /// ④ 攻击牌**自动选目标**：随机一个活着的敌人掉血（不选目标的话 `sel.eventTarget` 解出空集，
    ///    伤害会安静地一点不打）。
    #[test]
    fn havoc_plays_the_top_card_for_free_into_the_exhaust_pile() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 200;
            enemy.health_current = 200;
        }
        if let Some(enemy) = state.combatant_mut(&cid("enemy_b")) {
            enemy.health_max = 200;
            enemy.health_current = 200;
        }
        // 抽牌堆顶放一张 `strike`（2 费 —— 如果 Havoc 付费，能量会掉 2）。
        give_card(&mut state, "hero", CardZone::DrawPile, "card_top", "strike", None);
        give_card(&mut state, "hero", CardZone::DrawPile, "card_under", "defend", None);
        let energy_before = 2; // 预置 3，`Havoc` 自己花 1
        let health_before = health(&state, "enemy_a") + health(&state, "enemy_b");
        let card = card_in_hand(&mut state, &content, "hero", "havoc");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("havoc is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        // ② 只花了 Havoc 自己的 1 费：`strike` 的 2 费一分没动。
        let energy_after: i32 = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy_after, energy_before, "the forced play does not pay its own cost");

        // ④ 目标：随机一个敌人掉了 `strike` 的 6 点。
        assert_eq!(
            health_before - (health(&state, "enemy_a") + health(&state, "enemy_b")),
            6,
            "the forced Strike hit a random enemy for 6"
        );

        // ③ 那张 `strike` 在消耗堆里，而不是弃牌堆。
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile),
            [std::string::String::from("strike")],
            "the forced play lands in the Exhaust pile"
        );
        assert!(
            !zone_definitions(&state, "hero", CardZone::DiscardPile)
                .iter()
                .any(|id| id == "strike"),
            "and it is NOT in the discard pile"
        );
        // 底下的 `defend` 没被动过。
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DrawPile),
            [std::string::String::from("defend")],
            "only the TOP card is played"
        );

        // 抽牌堆空 ⇒ 什么都不做（不报错）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "havoc+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("havoc+ is playable");
        host.try_resolve_pending_queues(&mut state).expect("an empty draw pile is not an error");
        assert_eq!(health(&state, "enemy_a"), 20, "nobody was hit");
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'havoc_plays_the_top_card' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 1 test')


main()
