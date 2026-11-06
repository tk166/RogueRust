"""§240 判据：`Infernal Blade`（随机 Attack / 只收基础牌 / 0 费真的收 0）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §239：`Burning Pact` —— "Exhaust 1 card. Draw 2 cards."'

TESTS = r'''    /// §240：`Infernal Blade` —— "Add a random Attack into your hand. It costs 0 this turn."
    ///
    /// 四件事一起钉住，每一条都对应一个真会写错的地方：
    /// ① 进手的是**攻击牌**（不是技能/状态 —— 池子按 tag 过滤）；
    /// ② 是**基础牌**（不是 `strike+` 那种升级行：那会让"随机"变成"随机到升级版"）；
    /// ③ **不是 X 费牌**（每副本价格对 X 费牌看不见 ⇒ 会造出"说 0 费、实际全部能量"）；
    /// ④ 那张牌的**实际付款是 0**（不是"显示 0"）：`play_card` 之后能量一点没掉。
    ///
    /// 随机性本身不钉（种子由 `random_step` 决定，钉死了就是钉死洗牌顺序），钉的是**池子的性质**：
    /// 连造 40 次，每一次都必须是"基础、攻击、非 X 费"——这比"某一次等于某张牌"强得多。
    #[test]
    fn infernal_blade_adds_a_random_attack_that_really_costs_zero() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① ② ③：连造 40 次，检查每一次落进来的定义。
        let mut host = Host::new(&content);
        let mut state = arena();
        let mut seen = std::collections::BTreeSet::new();
        for _ in 0..40 {
            give_energy(&mut state, "hero", 3);
            let card = card_in_hand(&mut state, &content, "hero", "infernal_blade");
            let before: i32 = zone_count(&state, "hero", CardZone::Hand) as i32;
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("infernal blade is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            // 手牌：-1（打出自己）+ 1（造出来的那张）。
            assert_eq!(
                zone_count(&state, "hero", CardZone::Hand) as i32,
                before,
                "Infernal Blade itself leaves and one random card arrives"
            );
            let newest = state
                .zone_cards(&cid("hero"), CardZone::Hand)
                .last()
                .map(|card| crate::state::CardDefinitionId::new(card.definition_id.as_str()))
                .transpose()
                .expect("definition matches its own text")
                .expect("a card arrived");
            let definition = newest.as_str();
            assert!(
                definition != "infernal_blade" && definition != "infernal_blade+",
                "the created card must not be Infernal Blade itself ({definition})"
            );
            assert!(
                content.card_has_tag(definition, "attack") == Some(true),
                "{definition} is not an Attack"
            );
            assert!(
                !definition.contains('+'),
                "{definition} is an upgraded row -- the random pool is base cards only"
            );
            assert!(
                content.card_has_tag(definition, crate::battle::X_COST_TAG) != Some(true),
                "{definition} is an X-cost card -- a per-copy price cannot make it free"
            );
            seen.insert(std::string::String::from(definition));
        }
        assert!(
            seen.len() > 2,
            "the pool is supposed to be wide; 40 draws hit only {seen:?}"
        );

        // ④ 真的收 0：造出来之后立刻打它，能量一点不掉。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 200;
            enemy.health_current = 200;
        }
        let card = card_in_hand(&mut state, &content, "hero", "infernal_blade");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("infernal blade is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let made = state
            .zone_cards(&cid("hero"), CardZone::Hand)
            .last()
            .map(|card| card.id)
            .expect("a card arrived");
        let energy_before = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), made, Some(cid("enemy_a"))),
        )
        .expect("the created card is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy_after = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(
            energy_after, energy_before,
            "the created card costs 0 for real, not just on the label"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'infernal_blade_adds_a_random' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 1 test')


main()
