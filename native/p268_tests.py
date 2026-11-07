"""§268 判据：零基建档收尾（6 件）。

这里有两件是"内核早就有、内容第一次用"（`runic_pyramid` 的 `retain_hand` 标签、
`lizard_tail` 的 `DeathPrevention` 行），所以判据的重点不是"挂没挂"，而是**那条既有通道
真的被内容点亮了**：

* `runic_pyramid`：回合末手牌**不清**（没有它时手牌清空）；
* `lizard_tail`：致命伤之后血在 50%，而且**第二次**致命伤会真的死（"works once"）。
"""
import io

WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

ANCHOR = '''    /// §267：零基建批次的**反应轴**（掉血 / 消耗 / 出牌 / 回合初）。'''

TESTS = r'''    /// §268：零基建档收尾 —— 掉血兑现 / Power 回血 / 保留手牌 / 死亡预防 / 手牌空抽牌。
    #[test]
    fn the_zero_infrastructure_tail_lights_up_the_existing_channels() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: Option<&str>, card: &'static str, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card, count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(seed, "enc_cultist", 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier:?}: {e}"));
            install_session(session);
            if let Some(carrier) = carrier {
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
            }
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
        let block = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(_unused(), |c| {
                c.defensive_pools()
                    .iter()
                    .find(|p| p.key.as_str() == "standard.block")
                    .map_or(0, |p| p.pool.current)
            })
        };
        let hero_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| c.health_current)
        };
        let hero_max = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| c.health_max)
        };
        let damage_hero = |amount: i32| {
            let session = slot().as_mut().expect("session");
            let attacker = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("hero")),
                    amount,
                    ignores_block: true,
                    source: Some(attacker),
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

        // ---- Self-Forming Clay：**这次**掉血，**下回合开始**才给格挡。
        session_for(Some("standard.self_forming_clay"), "strike", 231);
        let before = block();
        damage_hero(3);
        assert_eq!(block(), before, "Self-Forming Clay: nothing yet (it is *next* turn)");
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        // 下一回合是**新回合**（格挡已被清空），所以这一刻的 3 点只可能来自遗物。
        assert_eq!(block(), 3, "Self-Forming Clay: 3 Block at the next turn start");
        take_session();

        // ---- Bird-Faced Urn：出一张 Power 牌 ⇒ 回 2 点（先掉 10 点好看见它）。
        session_for(Some("standard.bird_faced_urn"), "inflame", 232);
        damage_hero(10);
        let before = hero_hp();
        play_one("power");
        assert_eq!(hero_hp(), before + 2, "Bird-Faced Urn: +2 HP per Power card");
        take_session();

        // ---- Runic Pyramid：回合末**不清**手牌（基线：清了）。
        session_for(None, "defend", 233);
        assert!(hand() > 0, "the hero starts with a hand");
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert_eq!(hand(), 5, "baseline: the hand is discarded and 5 new cards are drawn");
        take_session();

        session_for(Some("standard.runic_pyramid"), "defend", 234);
        let kept = hand();
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert!(
            hand() > 5,
            "Runic Pyramid: the old hand is kept on top of the 5 new cards (got {})",
            hand()
        );
        assert!(kept > 0, "the hero starts with a hand");
        take_session();

        // ---- Lizard Tail：致命伤 ⇒ 回到 50% 上限血，而且**只用一次**。
        session_for(Some("standard.lizard_tail"), "strike", 235);
        let max = hero_max();
        damage_hero(max * 2);
        assert_eq!(
            hero_hp(),
            max / 2,
            "Lizard Tail: a lethal hit leaves you at 50% of max HP"
        );
        damage_hero(max * 2);
        assert_eq!(
            hero_hp(),
            0,
            "Lizard Tail: it works **once** — the second lethal hit kills"
        );
        take_session();

        // ---- Unceasing Top：打掉**最后一张**手牌 ⇒ 抽 1 张。
        session_for(Some("standard.unceasing_top"), "strike", 236);
        // 把手牌打到只剩一张。
        while hand() > 1 {
            play_one("attack");
        }
        assert_eq!(hand(), 1, "one card left in hand");
        let deck_left = {
            let session = slot().as_ref().expect("session");
            session
                .state
                .zone_cards(&cid_in("hero"), rd_core::state::CardZone::DrawPile)
                .count()
        };
        if deck_left > 0 {
            play_one("attack");
            assert_eq!(
                hand(),
                1,
                "Unceasing Top: playing the last card draws 1 back"
            );
        }
        take_session();
    }

'''

# `map_or` 需要一个占位值，直接写字面量更清楚
TESTS = TESTS.replace('map_or(_unused(), |c| {', 'map_or(-1, |c| {')


def main():
    src = io.open(WASM, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'the_zero_infrastructure_tail_lights_up' not in src
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('tests appended')


main()
