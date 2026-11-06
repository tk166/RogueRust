"""§244 判据：无色 B 档（随机造牌 / 从抽牌堆取牌 / 触发器打顶牌）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '    /// §243：无色 A 档的**数字**'

TESTS = r'''    /// §244：`Chrysalis` / `Metamorphosis` / `Jack of All Trades` —— 随机造牌，**只按 tag 收窄**。
    ///
    /// 三段：① 张数对（3/5、1/2）；② 落的牌区对（抽牌堆 / 手牌）；③ **每一种都带对了 tag**
    /// （技能/攻击/无色）—— 第 ③ 段是这张判据的命门：`createRandomCardInstance` 只认一个 tag，
    /// 抄错了（比如给 Chrysalis 写 `attack`）内容门看不出来，只有这里会红。
    #[test]
    fn the_random_card_batch_picks_from_the_right_pool() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // (牌, 造几张, 该在哪个区, 每张必须带哪个 tag)
        let cases = [
            ("chrysalis", 3usize, CardZone::DrawPile, "skill"),
            ("chrysalis+", 5, CardZone::DrawPile, "skill"),
            ("metamorphosis", 3, CardZone::DrawPile, "attack"),
            ("metamorphosis+", 5, CardZone::DrawPile, "attack"),
            ("jack_of_all_trades", 1, CardZone::Hand, "colorless"),
            ("jack_of_all_trades+", 2, CardZone::Hand, "colorless"),
        ];
        for (card_id, expected, zone, tag) in cases {
            let mut host = Host::new(&content);
            let mut state = arena();
            give_energy(&mut state, "hero", 3);
            // 抽牌堆里先垫牌，这样“洗进去的牌”与“原有的牌”能分开数。
            for index in 0..2 {
                give_card(&mut state, "hero", CardZone::DrawPile,
                          &std::format!("card_d{index}"), "defend", None);
            }
            let produced_before = zone_count(&state, "hero", zone);
            give_card(&mut state, "hero", CardZone::Hand, "card_x", card_id, None);
            let instance = crate::state::CardInstanceId::new("card_x").expect("short id");
            crate::play::play_card(
                &mut state,
                Some(&content),
                &crate::play::PlayRequest::new(cid("hero"), instance, Some(cid("enemy_a"))),
            )
            .expect("the card is playable");
            host.try_resolve_pending_queues(&mut state).expect("drain");

            // ① 张数：目标牌区多出来的正好 `expected` 张
            //    （`chrysalis` 自己进消耗堆，不影响抽牌堆；`jack` 自己也不进手牌）。
            let produced_after = zone_count(&state, "hero", zone);
            assert_eq!(
                produced_after - produced_before,
                expected,
                "{card_id}: {expected} cards into {zone:?}"
            );
            // ③ 每一张都带对了 tag，而且**不是** `+` 行。
            let mut seen = 0usize;
            for card in state.zone_cards(&cid("hero"), zone) {
                if card.id.as_str().starts_with("card_d") || card.id.as_str() == "card_x" {
                    continue;
                }
                seen += 1;
                let definition = card.definition_id.as_str();
                assert!(
                    content.card_has_tag(definition, tag) == Some(true),
                    "{card_id} produced {definition}, which is not a `{tag}`"
                );
                assert!(
                    !definition.contains('+'),
                    "{card_id} produced an upgraded row ({definition})"
                );
                // ② 费用为 0（`CostZero`）：这批牌都是"cost 0 this combat/turn"。
                assert!(
                    content.card_has_tag(definition, "x_cost") != Some(true),
                    "{card_id} produced an X-cost card ({definition}) -- a per-copy price cannot make it free"
                );
            }
            assert_eq!(seen, expected, "{card_id}: counted the produced cards");
        }
    }

    /// §244：`Secret Technique` / `Secret Weapon` / `Violence` —— 从**抽牌堆**取牌。
    ///
    /// 三件事：① 问句/搬运的来源确实在抽牌堆；② `Secret *` 拿牌进手后，抽牌堆少一张；
    /// ③ `Violence` 拿**3 张攻击牌**（不是随机 3 张），且抽牌堆只少攻击牌。
    #[test]
    fn secret_technique_and_violence_reach_into_the_draw_pile() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        // ① Secret Technique：抽牌堆里一张技能 + 一张攻击 ⇒ 候选只有技能。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::DrawPile, "card_skill", "defend", None);
        give_card(&mut state, "hero", CardZone::DrawPile, "card_attack", "strike", None);
        give_card(&mut state, "hero", CardZone::Hand, "card_x", "secret_technique", None);
        let instance = crate::state::CardInstanceId::new("card_x").expect("short id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), instance, Some(cid("enemy_a"))),
        )
        .expect("secret technique is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let choice = state.pending_choice().expect("it asks which card");
        assert_eq!(
            choice.source.zone(),
            Some(CardZone::DrawPile),
            "the question's source zone is the draw pile"
        );
        let picks = [state
            .zone_cards(&cid("hero"), CardZone::DrawPile)
            .find(|card| card.id.as_str() == "card_skill")
            .expect("the skill is a candidate")
            .id];
        state
            .resolve_choice(crate::state::ChoiceAnswer::Instances(&picks), 0)
            .expect("the answer is accepted");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert!(
            zone_definitions(&state, "hero", CardZone::Hand)
                .iter()
                .any(|id| id == "defend"),
            "the chosen Skill is in hand"
        );
        assert_eq!(
            zone_count(&state, "hero", CardZone::DrawPile),
            1,
            "and the draw pile lost exactly one card"
        );

        // ② Violence：抽牌堆里 1 技能 + 3 攻击 ⇒ 拿 3 张，且**只**拿走攻击。
        let mut host = Host::new(&content);
        let mut state = arena();
        give_energy(&mut state, "hero", 3);
        give_card(&mut state, "hero", CardZone::DrawPile, "card_skill", "defend", None);
        for index in 0..3 {
            give_card(&mut state, "hero", CardZone::DrawPile,
                      &std::format!("card_a{index}"), "strike", None);
        }
        give_card(&mut state, "hero", CardZone::Hand, "card_x", "violence", None);
        let instance = crate::state::CardInstanceId::new("card_x").expect("short id");
        crate::play::play_card(
            &mut state,
            Some(&content),
            &crate::play::PlayRequest::new(cid("hero"), instance, Some(cid("enemy_a"))),
        )
        .expect("violence is playable");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        assert_eq!(
            zone_count(&state, "hero", CardZone::DrawPile),
            1,
            "three Attacks left the draw pile (the Skill stayed)"
        );
        assert_eq!(
            zone_definitions(&state, "hero", CardZone::DrawPile),
            [std::string::String::from("defend")],
            "and the one left behind is the Skill"
        );
        let strikes = zone_definitions(&state, "hero", CardZone::Hand)
            .iter()
            .filter(|id| id.as_str() == "strike")
            .count();
        assert_eq!(strikes, 3, "all three Attacks are in hand");
    }

    /// §244：`Magnetism` —— `TurnStarted` 触发器 + §240 随机造牌（"每回合开始加一张随机无色牌"）。
    ///
    /// 这条判据的价值在**跨回合**：`TurnStarted` 的节目跑在回合边界上，而随机造牌要走
    /// `random_step` —— 只要触发器那次调用拿不到内容（`ctx.content` 为 `None`），
    /// 它会 `Missing("content")` 而不是静默，这是 §242 那个决定的回报。
    #[test]
    fn magnetism_adds_a_colorless_card_every_turn() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);

        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "hero", status("st_mag", "standard.magnetism", 1));
        turn::start_current_turn(&mut state, &config(), &mut host).expect("turn starts");
        host.try_resolve_pending_queues(&mut state).expect("drain");
        let hand = zone_definitions(&state, "hero", CardZone::Hand);
        assert_eq!(hand.len(), 1, "one card arrived from Magnetism: {hand:?}");
        assert_eq!(
            content.card_has_tag(hand[0].as_str(), "colorless"),
            Some(true),
            "and it is a Colorless card ({:?})",
            hand[0]
        );
        assert_ne!(
            hand[0].as_str().contains('+'),
            true,
            "base rows only ({:?})",
            hand[0]
        );
    }

'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'the_random_card_batch_picks_from_the_right_pool' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('patched host.rs with 3 tests')


main()
