"""§230 (part 3): 三条端到端判据（真内容 + 真 Host）。

* `Flex`：加 2(4) 层力量**并且**挂上 lose_strength；回合走完力量回到原值（"临时"是重点）。
* `Limit Break`：12 层 → 24 层；基础版进消耗堆、`+` 版不进（wiki 的括号是「基础;升级」）。
* `Perfected Strike`：6 + 2 × （手牌+抽牌堆+弃牌堆里带 `strike` tag 的牌数）。
"""
import io

HOST = 'kernel/rd-core/src/host.rs'
src = io.open(HOST, encoding='utf-8').read()

anchor = '''    /// §225：**消耗审计** —— 内核里把牌送进消耗堆的路径必须**都**跑 `LifecyclePrograms[Exhausted]`。'''
assert src.count(anchor) == 1

tests = '''    /// §230：`Flex` —— "Gain 2 (4) Strength. **At the end of this turn**, lose 2 (4) Strength."
    ///
    /// "临时"才是这张牌：判据必须走完一个回合，看力量**回到原值**（只断言"加了 2 层"的话，
    /// 一个把力量永久加上的实现也一样绿）。
    #[test]
    fn flex_gains_strength_that_the_turn_end_takes_back() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (card_id, gain) in [("flex", 2i32), ("flex+", 4)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("flex is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                strength_of(&state, "hero"),
                gain,
                "{card_id}: the Strength is there for this turn"
            );

            // 走完一个完整回合（英雄 → 敌人 → 英雄）。
            let mut hops = 0;
            while state.active_combatant_id.as_ref() != Some(&cid("hero")) || hops == 0 {
                turn::end_current_turn_and_start_next(&mut state, &config(), &mut host)
                    .expect("the turn passes");
                hops += 1;
                assert!(hops <= 4, "the turn never came back to the hero");
            }
            assert_eq!(
                strength_of(&state, "hero"),
                0,
                "{card_id}: the turn end took it back -- that is what \\"temporary\\" means"
            );
        }
    }

    /// §230：`Limit Break` —— "Double your Strength."
    ///
    /// 三条一起钉：翻倍（12 → 24，不是 +12 也不是 +2）、基础版**自消耗**、`+` 版**不消耗**
    /// （wiki 的括号是「基础;升级」：`Double your Strength.(<br>Exhaust.;)` —— 升级去掉 Exhaust）。
    #[test]
    fn limit_break_doubles_strength_and_only_the_base_copy_exhausts() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (card_id, exhausts) in [("limit_break", true), ("limit_break+", false)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            give(&mut state, "hero", status("st_str", "standard.strength", 12));
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("limit break is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                strength_of(&state, "hero"),
                24,
                "{card_id}: 12 doubled is 24 -- an extra `+12` is exactly what the card says"
            );
            let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile)
                .iter()
                .any(|id| id.as_str() == card_id);
            assert_eq!(
                exhausted, exhausts,
                "{card_id}: wiki is `Double your Strength.(<br>Exhaust.;)` -- base exhausts, `+` does not"
            );
        }
    }

    /// §230：`Perfected Strike` —— "Deal 6 damage. Deals 2 (3) additional damage for **ALL your cards
    /// containing \\"Strike\\"**"（wiki 正文：**in your deck when this card is played**）。
    ///
    /// 判据按**可数的场面**来：手牌里放已知数量的 `strike` tag 牌，伤害必须正好等于
    /// `6 + 2 × 数到的张数`；并且把那些牌换成**不带** tag 的牌之后，伤害回到 6 —— 否则
    /// "数到 0 张"与"根本没数"是同一件事。
    #[test]
    fn perfected_strike_counts_the_tagged_cards_in_hand() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // (手牌里另外放哪些牌, 这些牌里有几张带 `strike` tag)
        let cases: [(std::vec::Vec<&str>, i32); 2] = [
            (std::vec!["strike", "strike", "defend"], 2),
            (std::vec!["defend", "defend", "anger"], 0),
        ];
        for (extras, tagged) in cases {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            for (index, definition) in extras.iter().enumerate() {
                give_card(
                    &mut state,
                    "hero",
                    CardZone::Hand,
                    &std::format!("card_extra_{index}"),
                    definition,
                    None,
                );
            }
            let card = card_in_hand(&mut state, &content, "hero", "perfected_strike");
            let before = health(&state, "enemy_a");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("perfected strike is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            // ⚠️ 这张牌**自己**也数（它还在手牌里，参考的落区在 `onTerminal`），而且它自己的
            // tag 就是 `strike` —— 所以期望值是 `6 + 2 × (extras 里的张数 + 1)`。
            let expected = 6 + 2 * (tagged + 1);
            assert_eq!(
                before - health(&state, "enemy_a"),
                expected,
                "extras {extras:?}: 6 + 2 x ({tagged} tagged + itself)"
            );
        }
    }

''' + anchor

src = src.replace(anchor, tests)
io.open(HOST, 'w', encoding='utf-8', newline='\n').write(src)
print('ok tests')
