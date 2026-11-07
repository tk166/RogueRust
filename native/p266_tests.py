"""§266 判据：条件修饰器（`red_skull`）+ 同侧改写（`odd_mushroom`）。

两条都必须在**两个方向上**各测一次，否则"条件永远为真"和"条件永远为假"都能蒙过一条判据：

| 基建 | 正面 | 反面 |
|---|---|---|
| `Condition` | HP 45% ⇒ 10 点伤害变 **13** | HP 100% ⇒ 仍是 **10** |
| `OverrideScope: Self` | 自己戴着易伤 ⇒ 10 点吃 **12**（125%） | 没有遗物 ⇒ 吃 **15**（150%） |

再加一条"同侧改写**不越界**"：`odd_mushroom` 挂在英雄身上时，**敌人**的易伤仍按 150%
（如果它被当成 `Other`，敌人会吃 125%）。这一条是 `OverrideScope` 唯一的存在理由。
"""
import io

WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

WASM_ANCHOR = '''    /// §265：`StatusStacks` / `StatusImmunity` 两条管线 + 四件遗物。'''

WASM_TESTS = r'''    /// §266：条件修饰器（`red_skull`）+ 同侧改写（`odd_mushroom`）。
    #[test]
    fn the_conditional_and_self_scoped_modifiers_change_the_right_number() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: Option<&str>, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "strike", count: 1 }; 20].into_boxed_slice(),
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
        let enemy = || -> String {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| String::from(c.id.as_str()))
                .expect("an enemy")
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
        let hero_hp = || -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).map_or(-1, |c| c.health_current)
        };
        let set_hero_hp = |value: i32| {
            let session = slot().as_mut().expect("session");
            let hero = cid_in("hero");
            let combatant = session.state.combatant_mut(&hero).expect("hero");
            combatant.health_current = value;
        };
        let apply_to_hero = |status_id: &str, stacks: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(status_id)
                        .expect("a status id"),
                    stacks,
                    duration: 0,
                    charges: 0,
                    source: Some(cid_in("hero")),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };
        // 英雄打敌人 `amount` 点（走伤害管线，`source_card: None` ⇒ 只有无条件修饰器生效）。
        let hero_hits = |amount: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in(&enemy())),
                    amount,
                    ignores_block: false,
                    source: Some(cid_in("hero")),
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
        // 敌人打英雄 `amount` 点。
        let enemy_hits = |amount: i32| {
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
                    ignores_block: false,
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

        // ---- Red Skull：HP 满时**不给**力量（条件为假）。
        session_for(Some("standard.red_skull"), 101);
        let before = enemy_hp();
        hero_hits(10);
        assert_eq!(
            before - enemy_hp(),
            10,
            "Red Skull: at full HP the 3 Strength does not apply"
        );
        // 掉到 50% 以下（max 200 ⇒ 90 是 45%）⇒ +3。
        set_hero_hp(90);
        let before = enemy_hp();
        hero_hits(10);
        assert_eq!(
            before - enemy_hp(),
            13,
            "Red Skull: at or below 50% HP the Strength applies"
        );
        // 边界：正好 50%（100/200）也算 —— wiki 说的是 "at or below"。
        set_hero_hp(100);
        let before = enemy_hp();
        hero_hits(10);
        assert_eq!(before - enemy_hp(), 13, "Red Skull: exactly 50% still counts");
        take_session();

        // ---- Odd Mushroom：自己有易伤时吃 125%（10 ⇒ 12），基线是 150%（10 ⇒ 15）。
        session_for(None, 102);
        apply_to_hero("standard.vulnerable", 1);
        let before = hero_hp();
        enemy_hits(10);
        assert_eq!(before - hero_hp(), 15, "baseline: Vulnerable = 150%");
        take_session();

        session_for(Some("standard.odd_mushroom"), 103);
        apply_to_hero("standard.vulnerable", 1);
        let before = hero_hp();
        enemy_hits(10);
        assert_eq!(
            before - hero_hp(),
            12,
            "Odd Mushroom: your own Vulnerable multiplies by 125%, not 150%"
        );
        take_session();

        // ---- 不越界：`odd_mushroom` 是 `Self`，所以**敌人**的易伤仍是 150%。
        session_for(Some("standard.odd_mushroom"), 104);
        {
            let session = slot().as_mut().expect("session");
            let target = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(target),
                    definition: rd_core::state::StatusDefinitionId::new("standard.vulnerable")
                        .expect("vulnerable"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: Some(cid_in("hero")),
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("vulnerable on the enemy");
        }
        let before = enemy_hp();
        hero_hits(10);
        assert_eq!(
            before - enemy_hp(),
            15,
            "Odd Mushroom is `Self`: the enemy's Vulnerable is still 150%"
        );
        take_session();
    }

'''

RUN_TESTS = r'''    /// §266：两件的接线。
    #[test]
    fn the_conditional_modifier_relics_wire_their_own_carrier() {
        let carrier = [
            ("red_skull", "standard.red_skull"),
            ("odd_mushroom", "standard.odd_mushroom"),
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
    assert 'the_conditional_and_self_scoped_modifiers_change' not in src
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(
        src.replace(WASM_ANCHOR, WASM_TESTS + WASM_ANCHOR))

    src = io.open(RUN, encoding='utf-8').read()
    anchor = '''    /// §265：四件的接线（三件挂英雄、一件挂敌人）。'''
    assert src.count(anchor) == 1
    assert 'the_conditional_modifier_relics_wire_their_own_carrier' not in src
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(src.replace(anchor, RUN_TESTS + anchor))
    print('tests appended: rd-wasm 1, rd-run 1')


main()
