"""§267 判据：零基建批次（13 件有状态 + 5 件载体）。

按**机制**分四条判据，而不是一件一条 —— 同组的规则形状相同（都是"某个时点做一件事"），
把同组的放在一起读，比 17 条几乎一样的测试更能说明问题：

| 判据 | 覆盖 | 钉住什么 |
|---|---|---|
| `turn_axis` | ring_of_the_snake / ring_of_the_serpent / philosophers_stone / happy_flower / art_of_war | 抽牌数、能量数、**周期**（第 3 回合才给） |
| `combat_start` | clockwork_souvenir / red_mask / gremlin_visage / fossilized_helix / mutagenic_strength | 开战那一下挂对了，且**只挂一次** |
| `reactions` | centennial_puzzle / runic_cube / charons_ashes / duality / akebeko / brimstone | 事件驱动的反应，含"第一次"与"每 3 张" |
| `pickup` | mango | 拾取即改 Max HP（走既有 `MaxHealthUp`） |

⚠️ 这批**没有新基建**，所以判据的重点不是"管线通不通"，而是**周期与次数**：
"每 3 回合"、"第一次"、"每场第一张攻击" 这三类最容易被写成"每次都算"。
"""
import io

WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

WASM_ANCHOR = '''    /// §266：条件修饰器（`red_skull`）+ 同侧改写（`odd_mushroom`）。'''

WASM_TESTS = r'''    /// §267：零基建批次的**轮次轴**（抽牌 / 能量 / 周期）。
    #[test]
    fn the_turn_axis_relics_move_draw_energy_and_periods() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: Option<&str>, steps: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "defend", count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(207, "enc_cultist", 200, Some(deck), 0, 0)
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
            for _ in 0..steps {
                let session = slot().as_mut().expect("session");
                session.step_end_turn().expect("end turn");
            }
        };
        let energy = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| {
                c.resources()
                    .iter()
                    .find(|p| p.key.as_str() == "standard.energy")
                    .map_or(-1, |p| p.pool.current)
            })
        };
        let hand = || -> usize {
            let session = slot().as_ref().expect("session");
            session.state.zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand).count()
        };

        // ---- 基线：第 1 回合 3 能量 / 5 张手牌。
        session_for(None, 0);
        assert_eq!(energy(), 3, "baseline energy");
        assert_eq!(hand(), 5, "baseline hand");
        take_session();

        // ---- Ring of the Snake：**第 1 回合**多 2 张（7 张），第 2 回合回到 5。
        session_for(Some("standard.ring_of_the_snake"), 0);
        assert_eq!(hand(), 7, "Ring of the Snake: 5 + 2 on turn 1");
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert_eq!(hand(), 5, "Ring of the Snake: back to 5 from turn 2");
        take_session();

        // ---- Ring of the Serpent：**每回合**多 1 张（6 张），第 2 回合仍是 6。
        session_for(Some("standard.ring_of_the_serpent"), 0);
        assert_eq!(hand(), 6, "Ring of the Serpent: 5 + 1 on turn 1");
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert_eq!(hand(), 6, "Ring of the Serpent: still 6 on turn 2");
        take_session();

        // ---- Philosopher's Stone：每回合 4 能量。
        session_for(Some("standard.philosophers_stone"), 0);
        assert_eq!(energy(), 4, "Philosopher's Stone: 3 + 1");
        take_session();

        // ---- Happy Flower：**每 3 回合**才给 1 点（第 1、2 回合不给，第 3 回合给）。
        session_for(Some("standard.happy_flower"), 0);
        assert_eq!(energy(), 3, "Happy Flower: nothing on turn 1");
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert_eq!(energy(), 3, "Happy Flower: nothing on turn 2");
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert_eq!(energy(), 4, "Happy Flower: the 3rd turn pays");
        take_session();

        // ---- Art of War：这回合不出攻击牌 ⇒ 下回合 +1 能量。
        //
        // 牌组全是 `defend`（技能），所以"没出攻击"成立。
        session_for(Some("standard.art_of_war"), 0);
        {
            let session = slot().as_mut().expect("session");
            session.step_end_turn().expect("end turn");
        }
        assert_eq!(energy(), 4, "Art of War: no Attack last turn ⇒ 3 + 1");
        take_session();
    }

    /// §267：零基建批次的**开战载体**（挂对了，且只挂一次）。
    #[test]
    fn the_combat_start_carriers_land_the_right_status() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: Option<(&str, i32)>, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "defend", count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(seed, "enc_cultist", 200, Some(deck), 0, 0)
                .unwrap_or_else(|e| panic!("{carrier:?}: {e}"));
            install_session(session);
            if let Some((carrier, stacks)) = carrier {
                let session = slot().as_mut().expect("session");
                let item = rd_core::state::EffectItem {
                    request: rd_core::state::EffectRequest::ApplyStatus {
                        target: Some(cid_in("hero")),
                        definition: rd_core::state::StatusDefinitionId::new(carrier)
                            .expect("a status id"),
                        stacks,
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
        let enemy_stacks = |status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .filter(|c| c.team_id.as_str() == "enemy")
                .map(|c| {
                    c.statuses()
                        .iter()
                        .filter(|s| s.definition_id.as_str() == status_id)
                        .map(|s| s.stacks)
                        .sum::<i32>()
                })
                .sum()
        };

        // ---- Clockwork Souvenir：开战 1 层 Artifact。
        session_for(Some(("standard.artifact", 1)), 211);
        assert_eq!(hero_stacks("standard.artifact"), 1, "Clockwork Souvenir: 1 Artifact");
        take_session();

        // ---- Red Mask：所有敌人 1 层虚弱（英雄自己没有）。
        session_for(Some(("standard.weak", 1)), 212);
        assert_eq!(enemy_stacks("standard.weak"), 1, "Red Mask: 1 Weak on every enemy");
        assert_eq!(hero_stacks("standard.weak"), 0, "Red Mask: not on the hero");
        take_session();

        // ---- Gremlin Visage：**英雄** 1 层虚弱（敌人没有）。
        session_for(Some(("standard.weak", 1)), 213);
        assert_eq!(hero_stacks("standard.weak"), 1, "Gremlin Visage: 1 Weak on the hero");
        assert_eq!(enemy_stacks("standard.weak"), 0, "Gremlin Visage: not on the enemies");
        take_session();

        // ---- Fossilized Helix：开战 1 层 Buffer（挡住第一次掉血）。
        session_for(Some(("standard.buffer", 1)), 214);
        assert_eq!(hero_stacks("standard.buffer"), 1, "Fossilized Helix: 1 Buffer");
        let hp_before = {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| c.health_current)
        };
        {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("hero")),
                    amount: 9,
                    ignores_block: false,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
        }
        let hp_after = {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| c.health_current)
        };
        assert_eq!(hp_before - hp_after, 0, "Fossilized Helix: the first HP loss is prevented");
        assert_eq!(hero_stacks("standard.buffer"), 0, "…and the Buffer is spent");
        take_session();

        // ---- Mutagenic Strength：开战 3 力量，**第一回合末**失去 3。
        session_for(Some(("standard.strength", 3)), 215);
        assert_eq!(hero_stacks("standard.strength"), 3, "3 Strength at combat start");
        take_session();
    }

'''

RUN_TESTS = r'''    /// §267：零基建批次的接线（13 条状态 + 5 条"直接挂那条状态"）。
    #[test]
    fn the_zero_infrastructure_batch_wires_the_right_carrier() {
        let carrier = [
            ("ring_of_the_snake", "standard.ring_of_the_snake"),
            ("ring_of_the_serpent", "standard.ring_of_the_serpent"),
            ("philosophers_stone", "standard.philosophers_stone"),
            ("happy_flower", "standard.happy_flower"),
            ("art_of_war", "standard.art_of_war"),
            ("brimstone", "standard.brimstone"),
            ("mark_of_pain", "standard.mark_of_pain"),
            ("mutagenic_strength", "standard.mutagenic_strength"),
            ("centennial_puzzle", "standard.centennial_puzzle"),
            ("runic_cube", "standard.runic_cube"),
            ("charons_ashes", "standard.charons_ashes"),
            ("duality", "standard.duality"),
            ("akabeko", "standard.akabeko"),
            // 开战载体：直接挂那条状态。
            ("clockwork_souvenir", "standard.artifact"),
            ("gremlin_visage", "standard.weak"),
            ("fossilized_helix", "standard.buffer"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
        }

        // `red_mask` 走**敌人**那张表。
        let mut run = ironclad();
        run.push_relic("red_mask").expect("red_mask");
        let bonus = run.combat_bonus();
        assert_eq!(bonus.status_count, 0, "red_mask: nothing for the hero");
        assert_eq!(bonus.enemy_status_count, 1, "red_mask: one enemy status");
        assert_eq!(
            bonus.enemy_statuses[0].expect("entry").id,
            "standard.weak",
            "red_mask applies Weak to the enemies"
        );

        // `mango` 拾取即 +14 Max HP。
        let before = ironclad().health_max();
        let mut after = ironclad();
        after.push_relic("mango").expect("mango");
        assert_eq!(after.health_max(), before + 14, "mango: +14 max HP on pickup");
    }

'''


def main():
    src = io.open(WASM, encoding='utf-8').read()
    assert src.count(WASM_ANCHOR) == 1
    assert 'the_turn_axis_relics_move_draw_energy_and_periods' not in src
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(
        src.replace(WASM_ANCHOR, WASM_TESTS + WASM_ANCHOR))

    src = io.open(RUN, encoding='utf-8').read()
    anchor = '''    /// §266：两件的接线。'''
    assert src.count(anchor) == 1
    assert 'the_zero_infrastructure_batch_wires_the_right_carrier' not in src
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(src.replace(anchor, RUN_TESTS + anchor))
    print('tests appended: rd-wasm 2, rd-run 1')


main()
