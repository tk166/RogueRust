"""§219 tests: `Exhaust` on play is a zone, and the two cards that spelled it wrong are playable now."""
import io

H = 'kernel/rd-core/src/host.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


one(H, '''    /// §218（卡牌 wiki 对照抓到的真错）：`Blur` 一直**只给了状态、没给格挡**。''',
    '''    /// §219：`Exhaust` 是**落区**，而且要真的能用 —— `bandage_up` / `dark_shackles` 曾经把
    /// `PlayedCardDestinationZone` 写成 `"Exhaust"`（内核只认 `"ExhaustPile"`），于是**一打就
    /// `IrError::UnknownKind`**。没有任何测试打过它们，所以这个错从 §157 活到 §218 的卡牌对照。
    ///
    /// 判据：打出去之后 ①牌进了消耗堆（不是弃牌堆），②效果真的发生了
    /// （`bandage_up` 治疗 4；`dark_shackles` 给敌人 -9 力量）。
    /// `slimed` 走同一条路：wiki 说它"1 费、可出、Exhaust"，而内容把它做成了不可出的状态牌 ——
    /// 现在载体有了，它就该可出。
    #[test]
    fn exhaust_on_play_is_a_zone_and_the_cards_that_use_it_are_playable() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① `bandage_up`：治疗 4，然后进消耗堆。
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        {
            let hero = state.combatant_mut(&cid("hero")).expect("hero");
            hero.health_current = 40;               // 70 -> 40，好让治疗看得见
        }
        let card = card_in_hand(&mut state, &content, "hero", "bandage_up");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("hero"))),
        )
        .expect("bandage_up must be playable (it was `IrError::UnknownKind` with `\\"Exhaust\\"`)");
        assert_eq!(health(&state, "hero"), 44, "wiki: Heal 4 HP");
        assert_eq!(
            zone_ids(&state, "hero", CardZone::ExhaustPile),
            vec![card.instance_id.as_str()],
            "and it lands in the exhaust pile, not the discard pile"
        );

        // ② `slimed`：1 费、可出、进消耗堆（wiki 的 `Exhaust`）。
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "slimed");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("hero"))),
        )
        .expect("slimed is a playable 1-cost status card (wiki), not an unplayable one");
        assert_eq!(
            zone_ids(&state, "hero", CardZone::ExhaustPile),
            vec![card.instance_id.as_str()],
            "slimed exhausts"
        );
        assert_eq!(
            energy_of(&state, "hero"),
            2,
            "and it costs 1 energy like the wiki says"
        );

        // ③ `dark_shackles`：给敌人 -9 力量，然后进消耗堆。
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "dark_shackles");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("dark_shackles must be playable");
        assert_eq!(
            stacks_of(&state, "enemy_a", "standard.strength"),
            -9,
            "wiki: Enemy loses 9 Strength"
        );
        assert_eq!(
            zone_ids(&state, "hero", CardZone::ExhaustPile),
            vec![card.instance_id.as_str()],
            "dark_shackles exhausts"
        );
    }

    /// §218（卡牌 wiki 对照抓到的真错）：`Blur` 一直**只给了状态、没给格挡**。''',
    'exhaust test')
