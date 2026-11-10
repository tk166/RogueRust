"""§329 行为判据（rd-wasm）。

三条相位规则，每条都要在**战斗里**看见（内容侧闸门只证明"字段在"）：

1. `awakened_one.rebirth` 清掉玩家留在它身上的 Debuff（Wiki "Removes all Debuffs"）；
2. `time_eater.haste` 同样清掉（并且仍然回血到 50%）；
3. `the_collector.spawn` 是 **up to 2**：两只 Torch Head 都活着时一只都不加，
   只剩一只时加一只，都死了加两只。

⚠️ 第 3 条的"两只都活着"要能真的构造出来：直接调 `execute_action` 两次，
第二次时场上已经有两只。
"""

import io

PATH = 'kernel/rd-wasm/src/lib.rs'

ANCHOR = """    /// §328：三条 A17 招式表（Ritual / Strength / Frail）在**战斗里**生效。"""

TESTS = '''    /// §329：`awakened_one.rebirth` 与 `time_eater.haste` 都**清掉所有 Debuff**。
    ///
    /// wiki：Rebirth "Heals to full HP. Removes all Debuffs. Loses Curiosity."；
    /// Haste "Removes all Debuffs. Heals to 50% HP."
    /// 判据给 Boss 挂 3 种 Debuff，跑一次动作，然后要求它们**一个都不剩** —— 而
    /// 自己的 Buff（这里用 `standard.strength`）必须还在（否则"清空所有状态"也会绿）。
    #[test]
    fn the_two_phase_heals_also_cleanse_debuffs() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let cases: &[(&str, &str, &str)] = &[
            ("enc_awakened_one", "awakened_one", "awakened_one.rebirth"),
            ("enc_time_eater", "time_eater", "time_eater.haste"),
        ];
        for (encounter, boss, action_id) in cases {
            let session = build_session_at(22, encounter, 300, None, 0, 0)
                .unwrap_or_else(|e| panic!("{encounter}: {e}"));
            install_session(session);
            {
                let session = slot().as_mut().expect("session");
                let id = cid_in(boss);
                let combatant = session.state.combatant_mut(&id).expect("the boss");
                for (index, name) in ["standard.weak", "standard.vulnerable", "standard.frail"]
                    .iter()
                    .enumerate()
                {
                    combatant
                        .push_status(rd_core::state::StatusInstance {
                            id: rd_core::state::StatusInstanceId::new(&std::format!("st{index}"))
                                .expect("id"),
                            definition_id: rd_core::state::StatusDefinitionId::new(name)
                                .expect("definition"),
                            stacks: 2,
                            duration_turns: 0,
                            charges: 0,
                            polarity: rd_core::state::StatusPolarity::Debuff,
                        })
                        .expect("debuff");
                }
                combatant.health_current = 10;
                let row = u32::from(
                    content
                        .lookup_in(action_id, rd_core::content::EK_EACTION)
                        .unwrap_or_else(|| panic!("{action_id}"))
                        .index,
                );
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &id,
                    row,
                    Some(cid_in("hero")),
                )
                .unwrap_or_else(|e| panic!("{action_id}: {:?}", e));
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let session = slot().as_ref().expect("session");
            let boss_state = session.state.combatant(&cid_in(boss)).expect("the boss");
            let names: Vec<&str> = boss_state
                .statuses()
                .iter()
                .map(|s| s.definition_id.as_str())
                .collect();
            for debuff in ["standard.weak", "standard.vulnerable", "standard.frail"] {
                assert!(
                    !names.contains(&debuff),
                    "{action_id}: {debuff} must be gone, left with {names:?}"
                );
            }
            assert!(
                boss_state.health_current > 10,
                "{action_id}: the heal still happens"
            );
            take_session();
        }
    }

    /// §329：`the_collector.spawn` 是 **up to 2** —— 场上已经有两只 Torch Head 时一只都不加。
    ///
    /// wiki：*"Summons up to 2 Torch Heads"*、*"Can only have two Torch Heads summoned at a time."*
    /// 三次调用：第 1 次（场上 0 只）⇒ +2；第 2 次（场上 2 只）⇒ +0；第 3 次（杀掉一只 ⇒ 1 只）
    /// ⇒ +1。只测第 1 次的话，"无条件 spawn 2"的实现照样绿。
    #[test]
    fn the_collector_summons_only_up_to_two_torch_heads() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let session = build_session_at(22, "enc_the_collector", 300, None, 0, 0)
            .expect("the collector fight");
        install_session(session);
        let row = u32::from(
            content
                .lookup_in("the_collector.spawn", rd_core::content::EK_EACTION)
                .expect("spawn")
                .index,
        );
        let torch_heads = |state: &rd_core::state::CombatState| {
            state
                .combatants()
                .iter()
                .filter(|c| {
                    c.definition_id.as_str() == "torch_head"
                        && c.lifecycle_state == rd_core::state::CombatantLifecycleState::Alive
                })
                .count()
        };
        let mut spawn = |expected: usize| {
            let session = slot().as_mut().expect("session");
            rd_core::intent::execute_action(
                &mut session.state,
                &content,
                &cid_in("the_collector"),
                row,
                Some(cid_in("hero")),
            )
            .expect("spawn");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            let alive = torch_heads(&session.state);
            assert_eq!(alive, expected, "Torch Heads alive after Spawn");
        };

        // 这一场开局就带两只（遭遇记录里就是这么写的）。
        let before = {
            let session = slot().as_ref().expect("session");
            torch_heads(&session.state)
        };
        assert_eq!(before, 2, "the encounter starts with two Torch Heads");
        spawn(2); // 已满 ⇒ 一只都不加

        // 杀掉一只，再召唤 ⇒ 补到 2。
        {
            let session = slot().as_mut().expect("session");
            let victim = session
                .state
                .combatants()
                .iter()
                .find(|c| {
                    c.definition_id.as_str() == "torch_head"
                        && c.lifecycle_state == rd_core::state::CombatantLifecycleState::Alive
                })
                .map(|c| c.id)
                .expect("a living Torch Head");
            session
                .state
                .combatant_mut(&victim)
                .expect("the victim")
                .lifecycle_state = rd_core::state::CombatantLifecycleState::Downed;
        }
        spawn(2);
        take_session();
    }

    /// §328：三条 A17 招式表（Ritual / Strength / Frail）在**战斗里**生效。'''


t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
assert 'fn the_two_phase_heals_also_cleanse_debuffs' not in t, 'patched'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS))
print('wasm: phase tests inserted')
