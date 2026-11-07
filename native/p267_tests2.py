"""§267 反应轴判据（rd-wasm）。用 `write` 生成，避免 heredoc 吃掉源代码文本（FACTS §2）。"""
import io

WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
ANCHOR = '''    /// §267：零基建批次的**轮次轴**（抽牌 / 能量 / 周期）。'''

TESTS = r'''    /// §267：零基建批次的**反应轴**（掉血 / 消耗 / 出牌 / 回合初）。
    ///
    /// 这一组的关键是**次数**："第一次掉血"、"每出一张攻击牌"、"每次消耗" —— 写成"每次都算"
    /// 或"只算一次"都不会报错，只会让数字慢慢不对，所以每条都断言**两次事件之后**的值。
    #[test]
    fn the_reaction_relics_fire_the_right_number_of_times() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: &str, card: &'static str, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card, count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(seed, "enc_cultist", 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(carrier)
                        .expect("a status id"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply the carrier");
            let standard = standard_turn_config().expect("standard turn config");
            let session = slot().as_mut().expect("session");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
        };
        let hand = || -> usize {
            let session = slot().as_ref().expect("session");
            session.state.zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand).count()
        };
        let enemy_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map_or(-1, |c| c.health_current)
        };
        let hero_stacks = |status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(0, |c| {
                c.statuses()
                    .iter()
                    .filter(|s| s.definition_id.as_str() == status_id)
                    .map(|s| s.stacks)
                    .sum()
            })
        };
        // 让英雄失去 `amount` 点血（无视格挡，会发 `HpLost`）。
        let lose_hp = |amount: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("hero")),
                    amount,
                    ignores_block: true,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        // 打一张手牌（按 tag 挑）并排空队列。
        let play_one = |tag: &str| {
            let session = slot().as_mut().expect("session");
            let hero = cid_in("hero");
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let instance = session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::Hand)
                .find(|card| content.card_has_tag(card.definition_id.as_str(), tag) == Some(true))
                .map(|card| card.id)
                .unwrap_or_else(|| panic!("no `{tag}` card in hand"));
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::GainResource {
                    target: Some(hero),
                    key: rd_core::state::ResourceId::new("standard.energy").expect("energy"),
                    amount: 30,
                    default_max: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("energy");
            rd_core::play::play_card(
                &mut session.state,
                Some(&content),
                &rd_core::play::PlayRequest::new(hero, instance, Some(enemy)),
            )
            .expect("play the card");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };

        // ---- Centennial Puzzle：**只**第一次掉血抽 3 张。
        session_for("standard.centennial_puzzle", "strike", 221);
        let before = hand();
        lose_hp(3);
        assert_eq!(hand(), before + 3, "Centennial Puzzle: the first HP loss draws 3");
        let before = hand();
        lose_hp(3);
        assert_eq!(hand(), before, "…and the second one draws nothing");
        take_session();

        // ---- Runic Cube：**每次**掉血抽 1 张。
        session_for("standard.runic_cube", "strike", 222);
        let before = hand();
        lose_hp(3);
        assert_eq!(hand(), before + 1, "Runic Cube: 1 card per HP loss");
        let before = hand();
        lose_hp(3);
        assert_eq!(hand(), before + 1, "…and again");
        take_session();

        // ---- Charon's Ashes：每消耗一张牌 ⇒ 对敌人 3 点。
        // `offering` 出完就自消耗（牌组里全是它），所以"消耗"是真出牌造成的。
        session_for("standard.charons_ashes", "offering", 223);
        let before = enemy_hp();
        play_one("skill");
        assert!(
            before - enemy_hp() >= 3,
            "Charon's Ashes: exhausting a card deals at least 3 to the enemy"
        );
        take_session();

        // ---- Duality：每出一张攻击牌 +1 敏捷，并挂上"回合末归还"的孪生。
        session_for("standard.duality", "strike", 224);
        let before = hero_stacks("standard.dexterity");
        play_one("attack");
        assert_eq!(
            hero_stacks("standard.dexterity"),
            before + 1,
            "Duality: +1 Dexterity per Attack"
        );
        assert_eq!(
            hero_stacks("standard.lose_dexterity"),
            1,
            "…and the twin that gives it back at end of turn"
        );
        take_session();

        // ---- Akabeko：**第一张**攻击 +8，第二张不再加。
        session_for("standard.akabeko", "strike", 225);
        {
            let before = enemy_hp();
            play_one("attack");
            assert_eq!(before - enemy_hp(), 14, "Akabeko: the first Attack deals 6 + 8");
        }
        {
            let before = enemy_hp();
            play_one("attack");
            assert_eq!(before - enemy_hp(), 6, "Akabeko: the second Attack is back to 6");
        }
        take_session();

        // ---- Brimstone：回合初自己 +2 力量、敌人 +1 力量。
        session_for("standard.brimstone", "strike", 226);
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn 1");
        }
        assert_eq!(hero_stacks("standard.strength"), 2, "Brimstone: +2 Strength for you");
        let enemy_strength = {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .filter(|c| c.team_id.as_str() == "enemy")
                .map(|c| {
                    c.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == "standard.strength")
                        .map(|s| s.stacks)
                        .sum::<i32>()
                })
                .sum::<i32>()
        };
        assert_eq!(enemy_strength, 1, "Brimstone: +1 Strength for the enemies");
        take_session();
    }

'''


def main():
    src = io.open(WASM, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'the_reaction_relics_fire_the_right_number_of_times' not in src
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('reaction test appended')


main()
