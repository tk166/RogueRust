"""§236 判据：`loseHp` 不是伤害、5 张牌、Rupture 的 from_card 区分。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §225：**消耗审计** —— 内核里把牌送进消耗堆的路径必须**都**跑 `LifecyclePrograms[Exhausted]`。'

TESTS = '''    /// §236：`Lose N HP` **不是伤害** —— 不吃格挡、不触发"被打"的钩子，但它**是**失去生命。
    ///
    /// 三件事分开测，因为它们的正确答案各不相同：
    /// ① 有 10 点格挡时 `Hemokinesis` 仍然掉 2 血（格挡一点不动）—— 这排除了"用 dealDamage 实现"；
    /// ② 掉血会响 `Rupture`（每层 +1 力量），而 Brutality 的每回合掉血**不响**（`hpLoss.fromCard`）；
    /// ③ `Lose 6 HP` 在 2 血时只掉 2 —— 而且**把英雄打死时战斗真的结束**（0 血转 Downed 的收尾）。
    #[test]
    fn losing_hp_is_not_damage_but_it_is_hp_loss() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 格挡不挡 `Lose HP`。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_block(&mut state, "hero", 10);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        let card = card_in_hand(&mut state, &content, "hero", "hemokinesis");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("hemokinesis is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "hero"), 68, "70 - 2 HP: Block does not stop `Lose HP`");
        assert_eq!(block_of(&state, "hero"), 10, "and the Block was not consumed");
        assert_eq!(100 - health(&state, "enemy_a"), 15, "the damage half still lands");

        // ② Rupture 只认"牌付的代价"。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 6);
        give(&mut state, "hero", status("st_rup", "standard.rupture", 2));
        turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
        let card = card_in_hand(&mut state, &content, "hero", "bloodletting");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("bloodletting is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            stacks_of(&state, "hero", "standard.strength"),
            2,
            "Bloodletting's 3 HP loss is `from a card` ⇒ Rupture 2 gains 2 Strength"
        );
        // Brutality 的每回合掉血**不算**"from a card"。
        give(&mut state, "hero", status("st_bru", "standard.brutality", 1));
        let strength_before = stacks_of(&state, "hero", "standard.strength");
        turn::end_current_turn(&mut state, &config(), &mut host).expect("turn ends");
        turn::start_current_turn(&mut state, &config(), &mut host).expect("next turn");
        assert_eq!(
            stacks_of(&state, "hero", "standard.strength"),
            strength_before,
            "Brutality's 1 HP per turn is not a card's cost ⇒ Rupture stays silent"
        );

        // ③ 血量不够时只掉剩下的，而且**能把自己打死**（0 血转 Downed、战斗判负）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        if let Some(hero) = state.combatant_mut(&cid("hero")) {
            hero.health_current = 2;
        }
        let card = card_in_hand(&mut state, &content, "hero", "offering");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("offering is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "hero"), 0, "6 HP from a 2 HP hero takes 2");
        assert_eq!(
            state.result,
            crate::state::CombatResult::Defeat,
            "losing the last HP must end the fight (the Downed bookkeeping is shared with damage)"
        );
    }

    /// §236：5 张"失去生命"的牌各自的牌面。
    #[test]
    fn the_lose_hp_cards_do_what_their_pages_say() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let energy_of = |state: &CombatState| -> i32 {
            state
                .combatant(&cid("hero"))
                .map_or(0, |combatant| {
                    combatant
                        .resources()
                        .iter()
                        .filter(|pool| pool.key.as_str() == "standard.energy")
                        .map(|pool| pool.pool.current)
                        .sum()
                })
        };

        // bloodletting：-3 HP，+2/+3 能量（0 费，所以能量净值就是加的那些）。
        for (card_id, gain) in [("bloodletting", 2i32), ("bloodletting+", 3)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("bloodletting is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(health(&state, "hero"), 67, "{card_id}: lose 3");
            assert_eq!(energy_of(&state), 1 + gain, "{card_id}: gain {gain} Energy");
        }

        // offering：-6 HP，+2 能量，抽 3/5 张，自消耗。
        for (card_id, draws) in [("offering", 3usize), ("offering+", 5)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            for index in 0..6 {
                give_card(&mut state, "hero", CardZone::DrawPile,
                          &std::format!("card_d{index}"), "defend", None);
            }
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("offering is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(health(&state, "hero"), 64, "{card_id}: lose 6");
            assert_eq!(energy_of(&state), 1 + 2, "{card_id}: gain 2 Energy");
            // 手牌：offer 自己离手，抽到 draws 张。
            assert_eq!(zone_count(&state, "hero", CardZone::Hand) as usize, draws, "{card_id}");
            assert!(
                zone_definitions(&state, "hero", CardZone::ExhaustPile)
                    .iter().any(|id| id.as_str() == card_id),
                "{card_id} exhausts itself"
            );
        }

        // brutality：挂上状态（每回合掉 1 血抽 1 张），`+` 版自带 Innate。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
        let card = card_in_hand(&mut state, &content, "hero", "brutality");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("brutality is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(stacks_of(&state, "hero", "standard.brutality"), 1);
        let hp_before = health(&state, "hero");
        turn::end_current_turn(&mut state, &config(), &mut host).expect("turn ends");
        turn::start_current_turn(&mut state, &config(), &mut host).expect("next turn");
        assert_eq!(
            health(&state, "hero"),
            hp_before - 1,
            "Brutality takes 1 HP at the start of the turn"
        );

        // rupture：1 层 ⇒ 每次因牌失去生命 +1 力量（见上一条测试的 ②），这里只钉"挂得上"。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "rupture+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("rupture is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(stacks_of(&state, "hero", "standard.rupture"), 2, "rupture+ is 2");
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'losing_hp_is_not_damage_but_it_is_hp_loss' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 2 tests')


main()
