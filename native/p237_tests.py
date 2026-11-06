"""§237 判据：三个触发器钩子 + 5 张 Power。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §236：`Lose N HP` **不是伤害**'

TESTS = '''    /// §237：`BlockGained` 钩子 —— `Juggernaut` 按"加了几点格挡"次数结算。
    ///
    /// 两侧都测：**加格挡**会触发（每加一次一条），**没加**不触发（`block_stage` 修饰成 0，
    /// 或者根本没这个状态）。第二条容易忘，而忘了它就意味着"手上有 Juggernaut 时，任何
    /// 加 0 点格挡的东西都在打人"。
    #[test]
    fn juggernaut_punishes_every_block_gain() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 没有 Juggernaut：加 5 点格挡不该伤到人。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        let enemy_before = health(&state, "enemy_a");
        let card = card_in_hand(&mut state, &content, "hero", "defend");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("defend is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            health(&state, "enemy_a"),
            enemy_before,
            "without Juggernaut, Block does not hurt anybody"
        );

        // Juggernaut 5 层：每**加**一次格挡打随机敌人 5 点。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 6);
        give(&mut state, "hero", status("st_jug", "standard.juggernaut", 5));
        let enemy_before = health(&state, "enemy_a") + health(&state, "enemy_b");
        let card = card_in_hand(&mut state, &content, "hero", "defend");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("defend is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 5, "Defend still blocks");
        assert_eq!(
            enemy_before - (health(&state, "enemy_a") + health(&state, "enemy_b")),
            5,
            "one Block gain ⇒ one 5 damage hit on a random enemy"
        );

        // 两张牌各加一次 ⇒ 两次（次数单位是"获得格挡"，不是"回合"）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 6);
        give(&mut state, "hero", status("st_jug", "standard.juggernaut", 5));
        let enemy_before = health(&state, "enemy_a") + health(&state, "enemy_b");
        for _ in 0..2 {
            let card = card_in_hand(&mut state, &content, "hero", "defend");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("defend is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
        }
        let lost = enemy_before - (health(&state, "enemy_a") + health(&state, "enemy_b"));
        assert!(lost == 10, "two Block gains ⇒ two hits (lost {lost}, want 10)");
    }

    /// §237：`CardsDrawn` 钩子 —— `Evolve` 只认 **Status**，`Fire Breathing` 认 Status 或 Curse。
    ///
    /// 三张探针卡分别代表三个答案：`wound`（Status）⇒ 两个都响；`injury`（Curse）⇒ 只有
    /// Fire Breathing 响；`strike`（Attack）⇒ 两个都不响。**只测第一个会漏掉"Curse 忘了加"**，
    /// 只测第二个会漏掉"Status 被写成 Curse-only"。
    #[test]
    fn evolve_and_fire_breathing_only_answer_to_the_right_tags() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // 探针：`evolve`（抽 2）+ `fire_breathing`（打 6）。每场只放一张探针牌在抽牌堆顶。
        let probe = |card_id: &str| -> (i32, usize) {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 6);
            give(&mut state, "hero", status("st_evo", "standard.evolve", 2));
            give(&mut state, "hero", status("st_fb", "standard.fire_breathing", 6));
            give_card(&mut state, "hero", CardZone::DrawPile,
                      "card_probe", card_id, None);
            let enemy_before = health(&state, "enemy_a") + health(&state, "enemy_b");
            // 抽 1 张：探针牌进手。
            let card = card_in_hand(&mut state, &content, "hero", "battle_trance");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
            )
            .expect("battle trance is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");
            let lost = enemy_before - (health(&state, "enemy_a") + health(&state, "enemy_b"));
            (lost, zone_count(&state, "hero", CardZone::Hand) as usize)
        };

        // 基线：抽到一张非 Status/Curse（`strike`）⇒ 不额外抽、不打人。
        let (lost, hand) = probe("strike");
        assert_eq!(lost, 0, "an Attack card is neither Status nor Curse");
        assert_eq!(hand, 2, "Battle Trance draws 1 + nothing extra");

        // Status（wound）⇒ Fire Breathing 打 6 × 全体（2 个敌人 ⇒ 12），Evolve 抽 2。
        let (lost, hand) = probe("wound");
        assert_eq!(lost, 12, "Fire Breathing 6 to ALL enemies (2 enemies)");
        assert_eq!(hand, 1 + 1 + 2, "Battle Trance 1 + the probe + Evolve 2");

        // Curse（injury）⇒ 同样两项都响（`card.hasTag.curse` 就是为它加的位）。
        let (lost, hand) = probe("injury");
        assert_eq!(lost, 12, "Curse is Fire Breathing's other half");
        assert_eq!(hand, 1 + 1 + 2, "and Evolve is status-only, so only 2 extra");
    }

    /// §237：`CardExhausted` 钩子 —— `Feel No Pain` 给格挡、`Dark Embrace` 抽牌。
    ///
    /// 三条入堆路径（§225 的审计）都要响，所以用两个不同的载体各测一次：
    /// ① 打出即消耗（`offering`）；② 虚无（`carnage` 的回合末）。**内容搬牌**那条由 §225 的
    /// `every_way_into_the_exhaust_pile_runs_the_exhausted_program` 钉着触发器节目的落点，
    /// 而事件与节目同一处发 —— 所以这里不重复。
    #[test]
    fn exhausting_a_card_feeds_feel_no_pain_and_dark_embrace() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① 打出即消耗：Offering 自己进消耗堆 ⇒ 3 格挡 + 抽 1 张（在它自己的 3 张之后）。
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_fnp", "standard.feel_no_pain", 3));
        give(&mut state, "hero", status("st_de", "standard.dark_embrace", 1));
        for index in 0..6 {
            give_card(&mut state, "hero", CardZone::DrawPile,
                      &std::format!("card_d{index}"), "strike", None);
        }
        let card = card_in_hand(&mut state, &content, "hero", "offering");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("offering is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(block_of(&state, "hero"), 3, "Feel No Pain 3 for the exhausted Offering");
        // Offering 抽 3，Dark Embrace 再抽 1 ⇒ 手牌 4 张（Offering 自己已经离手）。
        assert_eq!(zone_count(&state, "hero", CardZone::Hand), 4, "3 + Dark Embrace's 1");

        // ② 虚无：Carnage 在回合末从手牌进消耗堆，同样要响。
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_fnp", "standard.feel_no_pain", 3));
        give_energy(&mut state, "hero", 3);
        let card = card_in_hand(&mut state, &content, "hero", "carnage");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a"))),
        )
        .expect("carnage is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let block_after_play = block_of(&state, "hero");
        let mut hops = 0;
        while state.active_combatant_id.as_ref() != Some(&cid("hero")) || hops == 0 {
            turn::end_current_turn_and_start_next(&mut state, &config(), &mut host)
                .expect("the turn passes");
            hops += 1;
            assert!(hops <= 4, "the turn never came back to the hero");
            if state.active_combatant_id.as_ref() == Some(&cid("hero")) {
                break;
            }
        }
        assert_eq!(
            block_of(&state, "hero"),
            block_after_play + 3,
            "the Ethereal Carnage exhausted at turn end ⇒ Feel No Pain again"
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'juggernaut_punishes_every_block_gain' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 3 tests')


main()
