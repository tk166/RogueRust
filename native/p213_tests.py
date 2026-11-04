"""§213: the Chosen tests -- `standard.hex` fires only for non-Attack cards, and the A17 opener swap.

Both are end-to-end through the host's `CardPlayed` dispatch, because the whole point of Hex is that
it hangs off *other people's* card plays.
"""
import io

P = 'kernel/rd-wasm/src/lib.rs'
text = io.open(P, encoding='utf-8').read()

anchor = """    /// §212：`Nom Nom` = `5 × ceil(turn / 2)`"""
new = '''    /// §213：`Hex` —— **非攻击牌**才洗 Dazed 进抽牌堆，攻击牌一张都不塞。
    ///
    /// 两条判据就是这条规则的两半：只测"技能牌会塞"的话，一个"所有牌都塞"的实现也会绿；而
    /// `Hex` 的 wiki 原话是 "Whenever you play a **non-Attack** card"。这也顺带钉住 §213 新实现的
    /// `not` 值表达式（`not(card.hasTag.attack)`）。
    #[test]
    fn hex_shuffles_a_dazed_only_for_non_attack_cards() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let session = build_session_at(7, "enc_chosen", 200, None, 0, 0).expect("the chosen fight");
        install_session(session);
        let draw_count = |state: &rd_core::state::CombatState| {
            state
                .zone_cards(&cid_in("hero"), rd_core::state::CardZone::DrawPile)
                .iter()
                .filter(|card| card.definition_id.as_str() == "dazed")
                .count()
        };
        // The hero gets Hex (as if the Chosen had cast it).
        {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            session
                .state
                .enqueue_effect(rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new("standard.hex").expect("id"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: Some(cid_in("chosen")),
                    source_card: None,
                })
                .expect("enqueue");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch");
        }
        // A Skill first: one Dazed.
        {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            let card = session
                .state
                .zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand)
                .iter()
                .find(|card| content.card_has_tag(card.definition_id.as_str(), "skill") == Some(true))
                .map(|card| card.id)
                .expect("a skill in hand");
            session
                .state
                .enqueue_event(rd_core::state::CombatEvent::CardPlayed {
                    owner: cid_in("hero"),
                    card,
                })
                .expect("queue");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch");
        }
        let after_skill = {
            let session = slot().as_ref().expect("session");
            draw_count(&session.state)
        };
        assert_eq!(after_skill, 1, "a Skill shuffles one Dazed");
        // Then an Attack: no change.
        {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            let card = session
                .state
                .zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand)
                .iter()
                .find(|card| content.card_has_tag(card.definition_id.as_str(), "attack") == Some(true))
                .map(|card| card.id)
                .expect("an attack in hand");
            session
                .state
                .enqueue_event(rd_core::state::CombatEvent::CardPlayed {
                    owner: cid_in("hero"),
                    card,
                })
                .expect("queue");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch");
        }
        let after_attack = {
            let session = slot().as_ref().expect("session");
            draw_count(&session.state)
        };
        assert_eq!(
            after_attack, after_skill,
            "an Attack must not shuffle a Dazed (wiki: non-Attack cards)"
        );
        take_session();
    }

    /// §213：Chosen 的开局 与 HP —— A17 把 Poke→Hex 换成 Hex→Poke。
    ///
    /// wiki："Always starts with Poke followed by Hex." / "On A17, Chosen always starts with Hex
    /// instead of Poke." 判据问的是 `select_action` 在第 1 回合给出什么，两侧（A16 / A17）各一次。
    #[test]
    fn chosen_swaps_its_opener_at_a17() {
        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_chosen", rd_core::content::EK_ENCOUNTER)
                .expect("enc_chosen")
                .index,
        );
        let ask = |ascension: u8, round: i32, seed: i32| -> String {
            let session = build_session_at(seed, "enc_chosen", 200, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension} seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            session.state.current_round = round;
            let at = rd_core::intent::locate_enemy(&content, row, &cid_in("chosen"))
                .expect("locate")
                .expect("the chosen is in this encounter");
            rd_core::intent::select_action(&session.state, &content, at, &cid_in("chosen"), round)
                .expect("intent")
                .expect("an action")
                .action_id
                .to_string()
        };
        for seed in 0..40 {
            assert_eq!(ask(16, 1, seed), "chosen.poke", "below A17 the opener is Poke");
            assert_eq!(ask(17, 1, seed), "chosen.hex", "A17 opens with Hex");
            // The **second** move is the other one, which is what "Poke followed by Hex" means.
            assert_eq!(ask(16, 2, seed), "chosen.hex", "then Hex");
            assert_eq!(ask(17, 2, seed), "chosen.poke", "A17 then Poke");
        }
        // HP: 95 at A0, 98 from A7 (wiki 95-99 / 98-103).
        for (ascension, expected) in [(0u8, 95i32), (6, 95), (7, 98)] {
            let session = build_session_at(7, "enc_chosen", 200, None, 0, ascension)
                .expect("the chosen fight");
            install_session(session);
            let hp = {
                let session = slot().as_ref().expect("session");
                session
                    .state
                    .combatant(&cid_in("chosen"))
                    .map_or(0, |combatant| combatant.health_max)
            };
            assert_eq!(hp, expected, "Chosen max HP at A{ascension}");
        }
        take_session();
    }

''' + anchor
assert text.count(anchor) == 1
io.open(P, 'w', encoding='utf-8', newline='').write(text.replace(anchor, new, 1))
print("§213 tests added")
