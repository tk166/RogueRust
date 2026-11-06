"""§235 第一批红卡的判据（3 条测试覆盖 14 张）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §225：**消耗审计** —— 内核里把牌送进消耗堆的路径必须**都**跑 `LifecyclePrograms[Exhausted]`。'

ATTACKS = '''    /// §235：第一批红卡的**攻击**（6 张）—— 每张的判据都是"牌面上的那句话"。
    ///
    /// 为什么合在一条测试里：它们共享同一套夹具（1 英雄 + 2 敌人的战斗、出牌、排空）。拆成六条
    /// 会把同一段准备抄六遍；矩阵按 id 认领测试名，所以一条测试覆盖多张牌是允许的。
    #[test]
    fn the_new_red_attacks_do_what_their_pages_say() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① carnage：Ethereal + 20/28 伤害（Ethereal 是落区的事，这里只钉伤害）。
        for (card_id, damage) in [("carnage", 20i32), ("carnage+", 28)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            let before = health(&state, "enemy_a");
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("carnage is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(before - health(&state, "enemy_a"), damage, "{card_id}");
        }

        // ② immolate：全体 21/28 + 一张 Burn 进**弃牌堆**。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "immolate");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("immolate is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(health(&state, "enemy_a"), 0, "21 kills the 20 HP enemy");
        assert_eq!(health(&state, "enemy_b"), 0, "and the 10 HP one");
        let discards = zone_definitions(&state, "hero", CardZone::DiscardPile);
        assert!(discards.iter().any(|id| id.as_str() == "burn"), "{discards:?}");

        // ③ reckless_charge：7/10 伤害 + 一张 Dazed 进**抽牌堆**。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "reckless_charge");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("reckless charge is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(20 - health(&state, "enemy_a"), 7, "deal 7");
        let draw = zone_definitions(&state, "hero", CardZone::DrawPile);
        assert!(draw.iter().any(|id| id.as_str() == "dazed"), "{draw:?}");

        // ④ sever_soul：非攻击牌全进消耗堆，**牌本身不消耗**，然后打 16。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::Hand, "card_defend", "defend", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_strike", "strike", None);
        if let Some(enemy) = state.combatant_mut(&cid("enemy_a")) {
            enemy.health_max = 100;
            enemy.health_current = 100;
        }
        let card = card_in_hand(&mut state, &content, "hero", "sever_soul");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("sever soul is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(100 - health(&state, "enemy_a"), 16, "deal 16");
        let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile);
        assert!(exhausted.iter().any(|id| id.as_str() == "defend"), "{exhausted:?}");
        assert!(
            !exhausted.iter().any(|id| id.as_str() == "sever_soul"),
            "Sever Soul does not exhaust itself: {exhausted:?}"
        );
        let hand = zone_definitions(&state, "hero", CardZone::Hand);
        assert!(hand.iter().any(|id| id.as_str() == "strike"), "the Attack stays: {hand:?}");

        // ⑤ dropkick：有易伤 ⇒ +1 能量 + 抽 1 张；没有 ⇒ 什么都不多给。
        for (vulnerable, expect_extra) in [(true, true), (false, false)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            give_card(&mut state, "hero", CardZone::DrawPile, "card_draw", "defend", None);
            if vulnerable {
                give(&mut state, "enemy_a", status("st_vuln", "standard.vulnerable", 2));
            }
            let hand_before = zone_count(&state, "hero", CardZone::Hand);
            let card = card_in_hand(&mut state, &content, "hero", "dropkick");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("dropkick is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            let drawn = zone_count(&state, "hero", CardZone::Hand) + 1 - hand_before;
            assert_eq!(
                drawn,
                i32::from(expect_extra),
                "vulnerable={vulnerable}: the draw is conditional"
            );
            let energy: i32 = state
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
                energy,
                if expect_extra { 1 } else { 0 },
                "vulnerable={vulnerable}: 3 - 1 (paid) + refund"
            );
        }

        // ⑥ headbutt：9 伤害 + 一个"从弃牌堆挑一张放回抽牌堆顶"的问句。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::DiscardPile, "card_bash", "bash", None);
        let card = card_in_hand(&mut state, &content, "hero", "headbutt");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("headbutt is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(20 - health(&state, "enemy_a"), 9, "deal 9");
        let choice = state.pending_choice().expect("Headbutt asks which card");
        assert_eq!(choice.then, crate::state::ChoiceThen::ToDrawPileTop);
        let mut legal = [CardInstanceId::EMPTY; 8];
        let count = state.choice_legal(&mut legal).expect("listable");
        assert_eq!(count, 1, "only the discard pile's bash");
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&legal[..1]), 0)
            .expect("the move is taken");
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DrawPile)
                .first()
                .map(|id| id.as_str()),
            Some("bash"),
            "the picked card is on top of the draw pile"
        );
    }

'''

SKILLS = '''    /// §235：第一批红卡的**技能**（7 张）。
    #[test]
    fn the_new_red_skills_do_what_their_pages_say() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① disarm：敌人 -2/-3 力量，自己进消耗堆。
        for (card_id, loss) in [("disarm", 2i32), ("disarm+", 3)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            give(&mut state, "enemy_a", status("st_str", "standard.strength", 5));
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("disarm is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                stacks_of(&state, "enemy_a", "standard.strength"),
                5 - loss,
                "{card_id}"
            );
            let exhausted = zone_definitions(&state, "hero", CardZone::ExhaustPile);
            assert!(exhausted.iter().any(|id| id.as_str() == card_id), "{card_id} exhausts");
        }

        // ② shockwave：全体 Weak + Vulnerable 各 3/5。
        for (card_id, stacks) in [("shockwave", 3i32), ("shockwave+", 5)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("shockwave is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            for who in ["enemy_a", "enemy_b"] {
                assert_eq!(stacks_of(&state, who, "standard.weak"), stacks, "{who} weak");
                assert_eq!(
                    stacks_of(&state, who, "standard.vulnerable"),
                    stacks,
                    "{who} vulnerable"
                );
            }
        }

        // ③ intimidate：全体 1/2 层 Weak，自消耗。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "intimidate+");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("intimidate is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        for who in ["enemy_a", "enemy_b"] {
            assert_eq!(stacks_of(&state, who, "standard.weak"), 2, "{who} weak");
        }

        // ④ seeing_red：+2 能量（1 - 1 + 2 = 2），自消耗。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 1);
        let card = card_in_hand(&mut state, &content, "hero", "seeing_red");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("seeing red is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let energy: i32 = state
            .combatant(&cid("hero"))
            .map_or(0, |combatant| {
                combatant
                    .resources()
                    .iter()
                    .filter(|pool| pool.key.as_str() == "standard.energy")
                    .map(|pool| pool.pool.current)
                    .sum()
            });
        assert_eq!(energy, 2, "1 - 1 (paid) + 2");

        // ⑤ power_through：两张 Wound 进手牌 + 15/20 格挡。
        for (card_id, block) in [("power_through", 15i32), ("power_through+", 20)] {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            let card = card_in_hand(&mut state, &content, "hero", card_id);
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("power through is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(block_of(&state, "hero"), block, "{card_id} block");
            let wounds = zone_definitions(&state, "hero", CardZone::Hand)
                .iter()
                .filter(|id| id.as_str() == "wound")
                .count();
            assert_eq!(wounds, 2, "{card_id}: exactly two Wounds");
        }

        // ⑥ flame_barrier：12 格挡 **并且**挂上同名反伤状态（层数 = 反伤值）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "flame_barrier");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("flame barrier is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 12, "Gain 12 Block");
        assert_eq!(
            stacks_of(&state, "hero", "standard.flame_barrier"),
            4,
            "4 damage back"
        );

        // ⑦ rage：本回合打攻击牌给格挡（3 层）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 6);
        let card = card_in_hand(&mut state, &content, "hero", "rage");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("rage is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(stacks_of(&state, "hero", "standard.rage"), 3);
        let strike = card_in_hand(&mut state, &content, "hero", "strike");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), strike, Some(cid("enemy_a"))),
        )
        .expect("strike is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 3, "an Attack pays 3 Block through Rage");
    }

'''

DEMON = '''    /// §235：`demon_form` —— "At the start of your turn, gain 2(3) Strength."（**每**回合都加）
    #[test]
    fn demon_form_grows_strength_at_every_turn_start() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        for (card_id, per_turn) in [("demon_form", 2i32), ("demon_form+", 3)] {
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
            .expect("demon form is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            assert_eq!(
                stacks_of(&state, "hero", "standard.strength"),
                0,
                "{card_id}: nothing until the next turn starts"
            );
            for turn_index in 1..=2 {
                let mut hops = 0;
                while state.active_combatant_id.as_ref() != Some(&cid("hero")) || hops == 0 {
                    turn::end_current_turn_and_start_next(&mut state, &config(), &mut host)
                        .expect("the turn passes");
                    hops += 1;
                    assert!(hops <= 4, "the turn never came back to the hero");
                }
                assert_eq!(
                    stacks_of(&state, "hero", "standard.strength"),
                    per_turn * turn_index,
                    "{card_id}: after {turn_index} turn start(s)"
                );
            }
        }
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'the_new_red_attacks_do_what_their_pages_say' not in src, 'already patched'
    src = src.replace(ANCHOR, ATTACKS + SKILLS + DEMON + ANCHOR)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src)
    print('patched host.rs with 3 tests')


main()
