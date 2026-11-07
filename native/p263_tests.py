"""§263 判据：敌人死亡类两件 + 伤害管线数值改写三件。

这批的规则要么在**新事件**上（`FoeDowned`），要么在**伤害结算的中间那个数**上，所以判据必须
造出那两种局面：

* 敌人死亡：得真的把一个敌人打死（`gremlin_horn` 看能量/手牌，`the_specimen` 看毒搬去了谁）。
* 数值改写：得造出"未被格挡的伤害"恰好落在阈值里（`the_boot` 4→5、`torii` 5→1），
  以及"掉 1 点血"（`tungsten_rod`）。**格挡 0** 是这些格子的必要条件，所以先给敌人/自己
  设好血量与格挡，再打一拳。

⚠️ 上一批（§262）踩过"`PlayRequest` 的 target 传 None ⇒ 伤害静默不发生"，
这批的伤害判据全部**断言掉血量**，所以那一类错会立刻红。
"""
import io

WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

WASM_ANCHOR = '''    /// §262：七件"每第 N 张某类型牌"的遗物 —— 真的打牌。'''

WASM_TESTS = r'''    /// §263：**敌人死亡**两件 + **伤害管线数值改写**三件。
    ///
    /// 一条测试覆盖五件，因为它们的公共前提是同一个："造一场能被我方精确控制伤害的战斗"。
    #[test]
    fn the_enemy_death_and_damage_rewrite_relics_change_the_right_number() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        // 两个敌人的战斗：打死一个，看另一个/英雄侧的反应。
        let session_for = |carrier: &str, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "strike", count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(seed, "enc_louse_normal", 200, Some(deck), 0, 0)
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
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
        };
        let enemies = || -> Vec<(String, i32)> {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .filter(|c| c.team_id.as_str() == "enemy")
                .map(|c| (String::from(c.id.as_str()), c.health_current))
                .collect()
        };
        let energy = || -> i32 {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatant(&cid_in("hero"))
                .map_or(-1, |c| {
                    c.resources()
                        .iter()
                        .find(|p| p.key.as_str() == "standard.energy")
                        .map_or(-1, |p| p.pool.current)
                })
        };
        let hand_count = || -> usize {
            let session = slot().as_ref().expect("session");
            session.state.zone_cards(&cid_in("hero"), rd_core::state::CardZone::Hand).count()
        };
        let poison_of = |id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in(id)).map_or(0, |c| {
                c.statuses()
                    .iter()
                    .filter(|s| s.definition_id.as_str() == "standard.poison")
                    .map(|s| s.stacks)
                    .sum()
            })
        };
        let hero_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| c.health_current)
        };
        // 直接对某个战斗员打一拳（绕过出牌：伤害额精确可控）。
        let hit = |who: &str, amount: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::GainResource {
                    target: Some(cid_in("hero")),
                    key: rd_core::state::ResourceId::new("standard.energy").expect("energy"),
                    amount: 10,
                    default_max: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("energy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in(who)),
                    amount,
                    ignores_block: false,
                    element: None,
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

        // ---- Gremlin Horn：敌人死亡 ⇒ +1 能量、抽 1 张。
        session_for("standard.gremlin_horn", 71);
        let names = enemies();
        assert!(names.len() >= 2, "this fixture needs two enemies, got {names:?}");
        let target = names[0].0.clone();
        let energy_before = energy();
        let hand_before = hand_count();
        hit(&target, 999);
        assert_eq!(enemies()[0].1, 0, "the louse is down");
        assert_eq!(energy(), energy_before + 1, "Gremlin Horn: +1 Energy on a kill");
        assert_eq!(hand_count(), hand_before + 1, "Gremlin Horn: draw 1 on a kill");
        take_session();

        // ---- The Specimen：死者身上的毒搬给**另一个**敌人（不是英雄、不是死者自己）。
        session_for("standard.the_specimen", 72);
        {
            let session = slot().as_mut().expect("session");
            let first = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(first),
                    definition: rd_core::state::StatusDefinitionId::new("standard.poison")
                        .expect("poison"),
                    stacks: 4,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("poison the first louse");
        }
        let names = enemies();
        let dying = names[0].0.clone();
        let survivor = names[1].0.clone();
        hit(&dying, 999);
        assert_eq!(poison_of(&dying), 0, "the dead one is gone");
        assert_eq!(poison_of(&survivor), 4, "The Specimen: the Poison moves to the other enemy");
        assert_eq!(poison_of("hero"), 0, "…and not to the hero");
        take_session();

        // ---- The Boot：4 点未被格挡的攻击伤害 ⇒ 5。
        session_for("standard.the_boot", 73);
        let names = enemies();
        let who = names[0].0.clone();
        let before = names[0].1;
        hit(&who, 4);
        let after = enemies()[0].1;
        assert_eq!(before - after, 5, "The Boot: 4 unblocked damage becomes 5");
        take_session();

        // 反面：5 点不在阈值内，原样。
        session_for("standard.the_boot", 74);
        let names = enemies();
        let who = names[0].0.clone();
        let before = names[0].1;
        hit(&who, 5);
        assert_eq!(before - enemies()[0].1, 5, "The Boot: 5 is already above the threshold");
        take_session();

        // ---- Torii：5 点未被格挡的攻击伤害 ⇒ 1（承受侧，所以打的是英雄）。
        session_for("standard.torii", 75);
        let before = hero_hp();
        hit("hero", 5);
        assert_eq!(before - hero_hp(), 1, "Torii: 5 unblocked damage becomes 1");
        take_session();

        // 反面：6 点不在阈值内，原样。
        session_for("standard.torii", 76);
        let before = hero_hp();
        hit("hero", 6);
        assert_eq!(before - hero_hp(), 6, "Torii: 6 is above the threshold");
        take_session();

        // ---- Tungsten Rod：每次掉血少掉 1 点（**任何**来源：这里用"直接失去生命"那条路）。
        session_for("standard.tungsten_rod", 77);
        let before = hero_hp();
        {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::LoseHealth {
                    target: Some(cid_in("hero")),
                    amount: 3,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("lose 3");
        }
        assert_eq!(before - hero_hp(), 2, "Tungsten Rod: 3 HP loss becomes 2");
        take_session();

        // 伤害那条路也一样（被格挡吃干净的那一下**不该**再减 —— 它本来就没掉血）。
        session_for("standard.tungsten_rod", 78);
        let before = hero_hp();
        hit("hero", 5);
        assert_eq!(before - hero_hp(), 4, "Tungsten Rod: 5 damage becomes 4");
        take_session();
    }

'''

RUN_TESTS = r'''    /// §263：五件（敌人死亡类 + 伤害改写类）的**接线**。
    #[test]
    fn the_enemy_death_and_damage_rewrite_relics_wire_their_own_carrier() {
        let carrier = [
            ("gremlin_horn", "standard.gremlin_horn"),
            ("the_specimen", "standard.the_specimen"),
            ("the_boot", "standard.the_boot"),
            ("torii", "standard.torii"),
            ("tungsten_rod", "standard.tungsten_rod"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
            assert_eq!(entry.stacks, 1, "{relic}: one stack");
        }
    }

'''


def main():
    src = io.open(WASM, encoding='utf-8').read()
    assert src.count(WASM_ANCHOR) == 1
    assert 'the_enemy_death_and_damage_rewrite_relics_change' not in src
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(
        src.replace(WASM_ANCHOR, WASM_TESTS + WASM_ANCHOR))

    src = io.open(RUN, encoding='utf-8').read()
    anchor = '''    /// §262：七件"每第 N 张某类型牌"的**接线**。'''
    assert src.count(anchor) == 1
    assert 'the_enemy_death_and_damage_rewrite_relics_wire' not in src
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(src.replace(anchor, RUN_TESTS + anchor))
    print('tests appended: rd-wasm 1, rd-run 1')


main()
