"""§265 判据：改状态施加（4 件）+ 两条新管线。

三条基建判据的落点都是"**施加那一刻**的层数"，所以每条都要两面：

| 遗物 | 正面 | 反面（证明它不该更宽） |
|---|---|---|
| `snecko_skull` | 你给敌人上 1 层毒 ⇒ 2 层 | 上**虚弱**仍是 1 层（`AppliesToStatusId` 是过滤器） |
| `ginger` | 虚弱撒不上（0 层） | **脆弱**照旧撒上（1 层） |
| `turnip` | 脆弱撒不上（0 层） | **虚弱**照旧撒上（1 层） |
| `twisted_funnel` | 开战时所有敌人 4 层毒 | —— |

再加一条"没有遗物时是 1 层"的基线：没有它，三条判据都可能因为别的原因为 0/2。
"""
import io

WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

WASM_ANCHOR = '''    /// §264：三条基建（`AppliesToStatusId` / `RestrictSourceCardTag` / `event.statusIs`）+ 三件遗物。'''

WASM_TESTS = r'''    /// §265：`StatusStacks` / `StatusImmunity` 两条管线 + 四件遗物。
    #[test]
    fn the_status_application_relics_change_what_lands_on_the_target() {
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
        // 由**英雄**施加（"你施加"里的"你"）。
        let apply_from_hero = |who: &str, status_id: &str, stacks: i32| {
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

        // ---- 基线：没有遗物时，1 层就是 1 层。
        session_for(None, 91);
        let target = enemy();
        apply_from_hero(&target, "standard.poison", 1);
        assert_eq!(stacks_of(&target, "standard.poison"), 1, "baseline: 1 Poison stays 1");

        // ---- Snecko Skull：你施加的中毒多 1 层。
        session_for(Some("standard.snecko_skull"), 92);
        let target = enemy();
        apply_from_hero(&target, "standard.poison", 1);
        assert_eq!(
            stacks_of(&target, "standard.poison"),
            2,
            "Snecko Skull: 1 Poison becomes 2"
        );
        // 反面：只对**中毒**。虚弱照旧 1 层（`AppliesToStatusId` 是过滤器）。
        apply_from_hero(&target, "standard.weak", 1);
        assert_eq!(
            stacks_of(&target, "standard.weak"),
            1,
            "Snecko Skull: Weak is untouched (the parameter filters by status)"
        );
        take_session();

        // ---- Ginger：虚弱撒不上，脆弱照旧。
        session_for(Some("standard.ginger"), 93);
        let target = enemy();
        apply_from_hero(&target, "standard.weak", 1);
        assert_eq!(stacks_of(&target, "standard.weak"), 0, "Ginger: Weak is refused");
        apply_from_hero(&target, "standard.frail", 1);
        assert_eq!(stacks_of(&target, "standard.frail"), 1, "Ginger: Frail still lands");
        take_session();

        // ---- Turnip：脆弱撒不上，虚弱照旧。
        session_for(Some("standard.turnip"), 94);
        let target = enemy();
        apply_from_hero(&target, "standard.frail", 1);
        assert_eq!(stacks_of(&target, "standard.frail"), 0, "Turnip: Frail is refused");
        apply_from_hero(&target, "standard.weak", 1);
        assert_eq!(stacks_of(&target, "standard.weak"), 1, "Turnip: Weak still lands");
        take_session();

        // ---- Twisted Funnel：开战时所有敌人 4 层中毒（走 `StartCombatStatusOnEnemies`）。
        {
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry { card: "strike", count: 1 }; 20].into_boxed_slice(),
            );
            let mut run_free = ();
            let _ = &mut run_free;
            let _ = deck;
            // 直接走运行层：把遗物塞进 run，再走 `combat_bonus()` 的敌人表。
            let mut run = rd_run::state::RunState::new(11, 80, i32::MAX, &["strike"; 10], 0)
                .expect("a run");
            run.push_relic("twisted_funnel").expect("twisted_funnel");
            let bonus = run.combat_bonus();
            assert_eq!(bonus.enemy_status_count, 1, "one enemy status");
            let entry = bonus.enemy_statuses[0].expect("an entry");
            assert_eq!(entry.id, "standard.poison", "Twisted Funnel applies Poison");
            assert_eq!(entry.stacks, 4, "…4 stacks");
        }
    }

'''

RUN_TESTS = r'''    /// §265：四件的接线（三件挂英雄、一件挂敌人）。
    #[test]
    fn the_status_application_relics_wire_their_own_carrier() {
        let carrier = [
            ("snecko_skull", "standard.snecko_skull"),
            ("ginger", "standard.ginger"),
            ("turnip", "standard.turnip"),
        ];
        for (relic, status_id) in carrier {
            let mut run = ironclad();
            run.push_relic(relic).unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            let bonus = run.combat_bonus();
            assert_eq!(bonus.status_count, 1, "{relic}: one combat-start status");
            let entry = bonus.statuses[0].unwrap_or_else(|| panic!("{relic}: an entry"));
            assert_eq!(entry.id, status_id, "{relic}: its own carrier");
            assert_eq!(entry.stacks, 1, "{relic}: one stack");
            assert_eq!(bonus.enemy_status_count, 0, "{relic}: nothing for the enemies");
        }

        // `twisted_funnel` 走**敌人**那张表（§224）。
        let mut run = ironclad();
        run.push_relic("twisted_funnel").expect("twisted_funnel");
        let bonus = run.combat_bonus();
        assert_eq!(bonus.status_count, 0, "twisted_funnel: nothing for the hero");
        assert_eq!(bonus.enemy_status_count, 1, "twisted_funnel: one enemy status");
        let entry = bonus.enemy_statuses[0].expect("an entry");
        assert_eq!(entry.id, "standard.poison", "Poison for the enemies");
        assert_eq!(entry.stacks, 4, "4 stacks");
    }

'''


def main():
    src = io.open(WASM, encoding='utf-8').read()
    assert src.count(WASM_ANCHOR) == 1
    assert 'the_status_application_relics_change_what_lands' not in src
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(
        src.replace(WASM_ANCHOR, WASM_TESTS + WASM_ANCHOR))

    src = io.open(RUN, encoding='utf-8').read()
    anchor = '''    /// §264：三件的接线。'''
    assert src.count(anchor) == 1
    assert 'the_status_application_relics_wire_their_own_carrier' not in src
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(src.replace(anchor, RUN_TESTS + anchor))
    print('tests appended: rd-wasm 1, rd-run 1')


main()
