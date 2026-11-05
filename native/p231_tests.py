"""§231 (part 3): 三条端到端判据。

* `True Grit`：格挡 + **正好一张**手牌进消耗堆（基础版随机、`+` 版问玩家）。
* `Battle Trance`：抽 3(4) 之后，**本回合**再抽一张的效果抽到 0 张；下一回合恢复正常。
* `Reaper`：打全体 + 按**实际掉的血**回血（有格挡的敌人身上回得少 —— 那才是 "unblocked"）。
"""
import io

HOST = 'kernel/rd-core/src/host.rs'
src = io.open(HOST, encoding='utf-8').read()

anchor = '''    /// §225：**消耗审计** —— 内核里把牌送进消耗堆的路径必须**都**跑 `LifecyclePrograms[Exhausted]`。'''
assert src.count(anchor) == 1

tests = '''    /// §231：`True Grit` —— "Gain 7 (9) Block. Exhaust 1 card(at random;)."
    ///
    /// wiki 的括号是「基础;升级」⇒ **基础版随机、`+` 版由玩家选**。两版各测一次：
    /// 格挡对、而且**正好一张**手牌进了消耗堆（不是"零张"也不是"整手牌"）。
    #[test]
    fn true_grit_gains_block_and_exhausts_exactly_one_card() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 基础版：不问人，随机消耗一张。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        for (index, definition) in ["strike", "defend", "bash"].iter().enumerate() {
            give_card(
                &mut state,
                "hero",
                CardZone::Hand,
                &std::format!("card_{index}"),
                definition,
                None,
            );
        }
        let card = card_in_hand(&mut state, &content, "hero", "true_grit");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("true grit is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 7, "wiki: Gain 7 Block");
        assert!(
            state.pending_choice().is_none(),
            "the base copy picks the card itself -- no question"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            2,
            "True Grit itself + exactly one random card"
        );
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 2, "two left in hand");

        // ② `+` 版：9 格挡 + 一个"选一张消耗"的问句（`ChoiceThen::Exhaust`）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_a", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_b", "defend", None);
        let card = card_in_hand(&mut state, &content, "hero", "true_grit+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("true grit+ is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 9, "wiki: Gain 9 Block");
        let choice = state.pending_choice().expect("the upgraded copy asks");
        assert_eq!(choice.then, crate::state::ChoiceThen::Exhaust);
        let mut legal = [CardInstanceId::EMPTY; 8];
        let count = state.choice_legal(&mut legal).expect("listable");
        assert_eq!(count, 2, "both hand cards are candidates");
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&legal[..1]), 0)
            .expect("the exhaust is taken");
        assert_eq!(
            zone_count(&state, "hero", CardZone::ExhaustPile),
            2,
            "True Grit itself + the card the player picked"
        );
    }

    /// §231：`Battle Trance` —— "Draw 3 (4) cards. You **cannot draw additional cards this turn**."
    ///
    /// 修掉的旧实现挂的是 `standard.draw_reduction`（"**下回合**起手少抽 1 张"），两处都错：
    /// 时机错、幅度错。判据必须两侧都问：本回合再抽 = 0 张；**下一回合**起手抽牌恢复正常。
    #[test]
    fn battle_trance_blocks_further_draws_only_this_turn() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 6);
        turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
        // 抽牌堆里留 5 张，供"再抽一张"用。
        for index in 0..5 {
            give_card(
                &mut state,
                "hero",
                CardZone::DrawPile,
                &std::format!("card_draw_{index}"),
                "strike",
                None,
            );
        }
        let hand_before = zone_count(&state, "hero", CardZone::Hand);
        let trance = card_in_hand(&mut state, &content, "hero", "battle_trance");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), trance, Some(cid("enemy_a"))),
        )
        .expect("battle trance is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        // 抽了 3 张（Battle Trance 自己离手不算在内）。
        let after_trance = zone_count(&state, "hero", CardZone::Hand);
        assert_eq!(after_trance, hand_before - 1 + 3, "wiki: Draw 3 cards");
        assert_eq!(
            stacks_of(&state, "hero", "standard.no_draw"),
            1,
            "the \\"cannot draw\\" marker is on the hero"
        );

        // 本回合再抽一张 ⇒ 一张都抽不到（**手牌不变**）。
        let hand_now = zone_count(&state, "hero", CardZone::Hand);
        let mut ctx = rd_core::exec::ExecContext::new(
            &mut state,
            Some(cid("hero")),
            Some(cid("enemy_a")),
            None,
            1024,
        )
        .with_content(&content);
        rd_core::exec::resolve_effect(
            &mut state,
            &rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DrawCards {
                    owner: cid("hero"),
                    count: 1,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            },
            Some(&content),
        )
        .expect("the draw resolves");
        let _ = &mut ctx;
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            zone_count(&state, "hero", CardZone::Hand),
            hand_now,
            "the marker is set in the kernel, but a drawn card arrived"
        );

        // 下一回合：标记自摘，起手抽牌恢复正常（5 张）。
        let mut hops = 0;
        while state.active_combatant_id.as_ref() != Some(&cid("hero")) || hops == 0 {
            turn::end_current_turn_and_start_next(&mut state, &config(), &mut host)
                .expect("the turn passes");
            hops += 1;
            assert!(hops <= 4, "the turn never came back to the hero");
        }
        assert_eq!(
            stacks_of(&state, "hero", "standard.no_draw"),
            0,
            "the marker removed itself at the turn end"
        );
        assert!(
            zone_count(&state, "hero", CardZone::Hand) >= 5,
            "next turn draws normally again, got {}",
            zone_count(&state, "hero", CardZone::Hand)
        );
    }

    /// §231：`Reaper` —— "Deal 4 (5) damage to ALL enemies. Heal HP equal to **unblocked** damage."
    ///
    /// "unblocked" 是这张牌的全部难点：给一个敌人 2 点格挡，它只掉 2 血，回血就只回"真掉的那些"。
    #[test]
    fn reaper_heals_only_the_unblocked_damage() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        // 英雄掉血，才有"回血"可观察；两个敌人一个没格挡、一个有 2 点。
        if let Some(hero) = state.combatant_mut(&cid("hero")) {
            hero.health_current = 40;
        }
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        if let Some(enemy) = state.combatant_mut(&cid("enemy_b")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        give_block(&mut state, "enemy_b", 2);

        let card = card_in_hand(&mut state, &content, "hero", "reaper");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("reaper is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");

        assert_eq!(100 - health(&state, "enemy_a"), 4, "4 damage, no block");
        assert_eq!(100 - health(&state, "enemy_b"), 2, "4 damage minus 2 block");
        assert_eq!(
            health(&state, "hero"),
            40 + 4 + 2,
            "heal = unblocked damage dealt (4 + 2), not 4 + 4"
        );
        assert!(
            zone_definitions(&state, "hero", CardZone::ExhaustPile)
                .iter()
                .any(|id| id.as_str() == "reaper"),
            "Reaper exhausts itself"
        );
    }

''' + anchor

src = src.replace(anchor, tests)
io.open(HOST, 'w', encoding='utf-8', newline='\n').write(src)
print('ok tests')
