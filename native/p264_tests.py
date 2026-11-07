"""§264 判据：三条**基建** + 三件遗物。

基建不是"加了个字段"，判据必须落在**可观察的数字**上：

| 基建 | 怎么证明它真的通了 |
|---|---|
| `AppliesToStatusId` 改写 | 敌人有易伤时，10 点伤害吃 17 点（150→175）而不是 15；**没有** Paper Phrog 时仍是 15 |
| `RestrictSourceCardTag` | Pen Nib 的 ×2 **只对攻击牌**：同一次翻倍下，攻击牌 12、技能造成的直接伤害不翻 |
| `event.statusIs` | 施加**易伤**时附带 1 层虚弱；施加**别的 debuff**（如虚弱本身）时**不**附带 |

外加一条"参数确实被读到"的反面：如果 `AppliesToStatusId` 只是被解出来而被忽略，
第一部分会照样是 15（改写没生效）—— 那正是"解开了但没人用"的形状。
"""
import io

WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

WASM_ANCHOR = '''    /// §263：**敌人死亡**两件 + **伤害管线数值改写**三件。'''

WASM_TESTS = r'''    /// §264：三条基建（`AppliesToStatusId` / `RestrictSourceCardTag` / `event.statusIs`）+ 三件遗物。
    #[test]
    fn the_status_parameter_infrastructure_changes_the_right_number() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");

        let session_for = |carrier: Option<&str>, seed: i32| {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "strike", count: 1 }; 20].into_boxed_slice(),
            );
            let session = build_session_at_unstarted(seed, "enc_two_louses", 200, Some(deck), 0, 0)
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
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
            session.reobserve();
        };
        let first_enemy = || -> String {
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
        let stacks_of = |who: &str, status_id: &str| -> i32 {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in(who)).map_or(0, |c| {
                c.statuses()
                    .iter()
                    .filter(|s| s.definition_id.as_str() == status_id)
                    .map(|s| s.stacks)
                    .sum()
            })
        };
        let apply = |who: &str, status_id: &str, stacks: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in(who)),
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
        let hit = |who: &str, amount: i32| {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in(who)),
                    amount,
                    ignores_block: false,
                    source: Some(cid_in("hero")),
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        };

        // ---- 基线：敌人有易伤时 10 点伤害吃 15 点（150%）。基准错了后面全是误报。
        session_for(None, 81);
        let target = first_enemy();
        apply(&target, "standard.vulnerable", 1);
        let before = enemy_hp();
        hit(&target, 10);
        assert_eq!(before - enemy_hp(), 15, "baseline: Vulnerable = 150%");

        // ---- Paper Phrog：同样 10 点吃 17 点（175%）。
        session_for(Some("standard.paper_phrog"), 82);
        let target = first_enemy();
        apply(&target, "standard.vulnerable", 1);
        let before = enemy_hp();
        hit(&target, 10);
        assert_eq!(before - enemy_hp(), 17, "Paper Phrog: Vulnerable = 175%");
        take_session();

        // ---- Paper Krane：敌人有虚弱时打 10 点只吃 6 点（60%，基线 75%）。
        // 虚弱挂在**出手方**（敌人），所以这里让敌人打英雄。
        session_for(None, 83);
        {
            let session = slot().as_mut().expect("session");
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(enemy),
                    definition: rd_core::state::StatusDefinitionId::new("standard.weak")
                        .expect("weak"),
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
                .expect("weaken the enemy");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        let before = hero_hp();
        {
            // 敌人打英雄 10 点：出手方是敌人。
            let session = slot().as_mut().expect("session");
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("hero")),
                    amount: 10,
                    ignores_block: false,
                    source: Some(enemy),
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        assert_eq!(before - hero_hp(), 7, "baseline: Weak = 75% (10 -> 7)");
        take_session();

        session_for(Some("standard.paper_krane"), 84);
        {
            let session = slot().as_mut().expect("session");
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(enemy),
                    definition: rd_core::state::StatusDefinitionId::new("standard.weak")
                        .expect("weak"),
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
                .expect("weaken the enemy");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        let before = hero_hp();
        {
            let session = slot().as_mut().expect("session");
            let enemy = session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
                .expect("an enemy");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("hero")),
                    amount: 10,
                    ignores_block: false,
                    source: Some(enemy),
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("damage");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        // 60% of 10 = 6。
        assert_eq!(before - hero_hp(), 6, "Paper Krane: Weak = 60% (10 -> 6)");
        take_session();

        // ---- Champion Belt：施加易伤 ⇒ 那一方多 1 层虚弱；施加**别的** debuff ⇒ 不附带。
        session_for(Some("standard.champion_belt"), 85);
        let target = first_enemy();
        apply(&target, "standard.vulnerable", 1);
        assert_eq!(
            stacks_of(&target, "standard.weak"),
            1,
            "Champion Belt: applying Vulnerable also applies 1 Weak"
        );
        take_session();

        session_for(Some("standard.champion_belt"), 86);
        let target = first_enemy();
        // 施加**脆弱**（另一个 debuff）：不该附带虚弱。
        apply(&target, "standard.frail", 1);
        assert_eq!(
            stacks_of(&target, "standard.weak"),
            0,
            "Champion Belt: only Vulnerable triggers it (frail must not)"
        );
        take_session();

        // ---- RestrictSourceCardTag：Pen Nib 的翻倍**只对攻击牌**。
        //
        // 直接给英雄上 `standard.double_damage`，然后造一次"**没有来源卡**"的直接伤害：
        // §262 时它会被翻倍（那条偏差）；§264 起不翻 —— 因为 spec 要求来源卡带 `attack`。
        session_for(None, 87);
        {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new("standard.double_damage")
                        .expect("double damage"),
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
                .expect("arm the doubling");
        }
        let target = first_enemy();
        let before = enemy_hp();
        hit(&target, 5);
        assert_eq!(
            before - enemy_hp(),
            5,
            "RestrictSourceCardTag: damage with no source card is NOT doubled"
        );
        take_session();
    }

'''

RUN_TESTS = r'''    /// §264：三件的接线。
    #[test]
    fn the_status_parameter_relics_wire_their_own_carrier() {
        let carrier = [
            ("paper_phrog", "standard.paper_phrog"),
            ("paper_krane", "standard.paper_krane"),
            ("champion_belt", "standard.champion_belt"),
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
    assert 'the_status_parameter_infrastructure_changes_the_right_number' not in src
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(
        src.replace(WASM_ANCHOR, WASM_TESTS + WASM_ANCHOR))

    src = io.open(RUN, encoding='utf-8').read()
    anchor = '''    /// §263：五件（敌人死亡类 + 伤害改写类）的**接线**。'''
    assert src.count(anchor) == 1
    assert 'the_status_parameter_relics_wire_their_own_carrier' not in src
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(src.replace(anchor, RUN_TESTS + anchor))
    print('tests appended: rd-wasm 1, rd-run 1')


main()
