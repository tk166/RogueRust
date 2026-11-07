"""§257 判据：五个精英的机制各一条（每条都两面测）。

放在 `rd-wasm` 是因为那里有 `build_session_at`（能按遭遇名 + 升阶建一场真战斗），
而 `Lagavulin` 的唤醒、`Reptomancer` 的匕首上限、`Nemesis` 的禁令都**必须**在真状态上才看得见。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'
ANCHOR = '''    /// §209：Curl Up —— **首次**掉血时按掷骰加格挡，之后自我摘除；被完全格挡的一击**不**消耗它。'''

TESTS = r'''    /// §257：`Lagavulin` 的**受伤即警醒**（wiki 的另一半）+ 醒来那一回合眩晕。
    ///
    /// 四段判据，每一段都能单独红：
    /// 1. 开局：`asleep` + `metallicize 8` 都在，第 1 回合的意图是 `Sleep`；
    /// 2. **掉血**的一击 ⇒ `asleep` 被摘掉、`metallicize` 被摘掉、`lagavulin_woken == 1`；
    /// 3. 那一回合的意图是 `Stunned`（不是 Attack）—— "被吵醒才眩晕"；
    /// 4. 眩晕那招把记号清掉之后**不再回去睡**（`Sleep` 只在前 3 回合**且**身上还有 asleep 时选）。
    #[test]
    fn lagavulin_wakes_when_it_loses_health_and_loses_a_turn() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let session = build_session_at(11, "enc_lagavulin", 200, None, 0, 0).expect("the fight");
        install_session(session);
        let row = u32::from(
            content
                .lookup_in("enc_lagavulin", rd_core::content::EK_ENCOUNTER)
                .expect("enc_lagavulin")
                .index,
        );

        let asleep = |state: &rd_core::state::CombatState| {
            let id = cid_in("lagavulin");
            state.combatant(&id).is_some_and(|c| {
                c.statuses()
                    .iter()
                    .any(|s| s.definition_id.as_str() == "standard.lagavulin_asleep")
            })
        };
        let metallicize = |state: &rd_core::state::CombatState| {
            let id = cid_in("lagavulin");
            state.combatant(&id).map_or(0, |c| {
                c.statuses()
                    .iter()
                    .filter(|s| s.definition_id.as_str() == "standard.metallicize")
                    .map(|s| s.stacks)
                    .sum::<i32>()
            })
        };
        let counter = |state: &rd_core::state::CombatState, key: &str| {
            let id = cid_in("lagavulin");
            state.combatant(&id).map_or(0, |c| {
                c.counters()
                    .iter()
                    .find(|e| e.key.as_str() == key)
                    .map_or(0, |e| e.value)
            })
        };
        let intent = |state: &rd_core::state::CombatState, round: i32| -> std::string::String {
            let id = cid_in("lagavulin");
            let at = rd_core::intent::locate_enemy(&content, row, &id)
                .expect("locate")
                .expect("lagavulin is in this encounter");
            rd_core::intent::select_action(state, &content, at, &id, round)
                .expect("intent")
                .expect("a move")
                .action_id
                .to_string()
        };

        // ① 开局：睡着，8 点 Metallicize，意图 Sleep。
        {
            let session = slot().as_ref().expect("session");
            assert!(asleep(&session.state), "it starts asleep");
            assert_eq!(metallicize(&session.state), 8, "Metallicize 8");
            assert_eq!(intent(&session.state, 1), "lagavulin.sleep");
        }

        // ②③ 掉血 ⇒ 醒、摘 Metallicize、下一步眩晕。
        {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::DealDamage {
                    target: Some(cid_in("lagavulin")),
                    amount: 5,
                    ignores_block: false,
                    source: Some(cid_in("hero")),
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("the hit");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        {
            let session = slot().as_ref().expect("session");
            assert!(!asleep(&session.state), "the hit wakes it (Asleep is gone)");
            assert_eq!(metallicize(&session.state), 0, "waking removes Metallicize");
            assert_eq!(counter(&session.state, "lagavulin_woken"), 1, "it just woke");
            assert_eq!(intent(&session.state, 2), "lagavulin.stunned", "woken by damage ⇒ a lost turn");
        }

        // ④ 眩晕那一招清掉记号；第 3 回合它**不再睡**，而是出招。
        {
            let session = slot().as_mut().expect("session");
            let action_row = u32::from(
                content
                    .lookup_in("lagavulin.stunned", rd_core::content::EK_EACTION)
                    .expect("stunned row")
                    .index,
            );
            rd_core::intent::execute_action(
                &mut session.state,
                &content,
                &cid_in("lagavulin"),
                action_row,
                Some(cid_in("hero")),
            )
            .expect("stunned");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            let session = slot().as_ref().expect("session");
            assert_eq!(counter(&session.state, "lagavulin_woken"), 0, "the stunned turn clears it");
            let next = intent(&session.state, 3);
            assert_ne!(next, "lagavulin.sleep", "a woken Lagavulin never goes back to sleep");
            assert_eq!(next, "lagavulin.attack", "and it starts its Attack / Attack / Siphon cycle");
        }
        take_session();
    }

    /// §257：`Lagavulin` 自己睡满三回合时**不眩晕**，直接开始 `Attack、Attack、Siphon Soul`。
    ///
    /// 这条与上一条是**同一份 wiki 的两半**（"If it takes any damage, it will be stunned for one
    /// turn … If three turns pass without any damage taken, it will awake and immediately begin
    /// attacking"）。只测其中一半，另一半写错也没有闸门会红。
    #[test]
    fn lagavulin_wakes_on_its_own_unstunned_and_cycles_attack_attack_siphon() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let session = build_session_at(12, "enc_lagavulin", 200, None, 0, 0).expect("the fight");
        install_session(session);
        let row = u32::from(
            content
                .lookup_in("enc_lagavulin", rd_core::content::EK_ENCOUNTER)
                .expect("enc_lagavulin")
                .index,
        );
        let at = {
            let session = slot().as_ref().expect("session");
            rd_core::intent::locate_enemy(&content, row, &cid_in("lagavulin"))
                .expect("locate")
                .expect("lagavulin")
        };
        let intent = |round: i32| -> std::string::String {
            let session = slot().as_ref().expect("session");
            rd_core::intent::select_action(&session.state, &content, at, &cid_in("lagavulin"), round)
                .expect("intent")
                .expect("a move")
                .action_id
                .to_string()
        };
        let run = |action_id: &str| {
            let session = slot().as_mut().expect("session");
            let action_row = u32::from(
                content
                    .lookup_in(action_id, rd_core::content::EK_EACTION)
                    .expect("the row")
                    .index,
            );
            rd_core::intent::execute_action(
                &mut session.state,
                &content,
                &cid_in("lagavulin"),
                action_row,
                Some(cid_in("hero")),
            )
            .expect("the move");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
        };

        // 第 1-3 回合睡；**自己醒**（没人打它）⇒ 一条 `TurnStarted` 触发器摘掉 asleep + Metallicize。
        for round in 1..=3 {
            assert_eq!(intent(round), "lagavulin.sleep", "round {round}: still asleep");
        }
        {
            let session = slot().as_mut().expect("session");
            // 第 4 回合开始 = `TurnStarted`，正是那条触发器的时间点。
            let mut host = rd_core::host::Host::new(&content);
            let _ = host.run_turn_started(&mut session.state, &cid_in("lagavulin"));
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        assert_eq!(
            intent(4),
            "lagavulin.attack",
            "waking on its own is NOT a lost turn: it attacks immediately"
        );
        // 然后严格 Attack、Attack、Siphon Soul。
        assert_eq!(intent(5), "lagavulin.attack", "second attack");
        run("lagavulin.attack");
        run("lagavulin.attack");
        assert_eq!(intent(6), "lagavulin.siphon_soul", "then Siphon Soul");
        run("lagavulin.siphon_soul");
        assert_eq!(intent(7), "lagavulin.attack", "and the cycle repeats");
        take_session();
    }

    /// §257：`Book of Stabbing` 的 N —— wiki 是 **2 + 已用次数**（内容原来是 3，多打一整下）。
    ///
    /// 判据读**英雄掉了多少血**而不是计数器：`6×2` 与 `6×3` 差 6，这个差在状态上是可观察的。
    /// 同时钉住 A3 的 `7×N`（阈值 3 而不是 4）。
    #[test]
    fn book_of_stabbing_multistab_starts_at_two_hits() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        for (ascension, expected) in [(0u8, vec![12, 18, 24]), (3u8, vec![14, 21, 28])] {
            let session = build_session_at(13, "enc_book_of_stabbing", 500, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            let mut dealt = Vec::new();
            for _ in 0..3 {
                let before = {
                    let session = slot().as_ref().expect("session");
                    session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current)
                };
                {
                    let session = slot().as_mut().expect("session");
                    let action_row = u32::from(
                        content
                            .lookup_in("book_of_stabbing.multi_stab", rd_core::content::EK_EACTION)
                            .expect("multi_stab")
                            .index,
                    );
                    rd_core::intent::execute_action(
                        &mut session.state,
                        &content,
                        &cid_in("book_of_stabbing"),
                        action_row,
                        Some(cid_in("hero")),
                    )
                    .expect("multi stab");
                    rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
                }
                let after = {
                    let session = slot().as_ref().expect("session");
                    session.state.combatant(&cid_in("hero")).map_or(0, |c| c.health_current)
                };
                dealt.push(before - after);
            }
            assert_eq!(dealt, expected, "A{ascension}: 2, 3, 4 hits of 6 (A3: 7)");
            take_session();
        }
    }

    /// §257：`Nemesis` 的三条禁令 + 首回合 50/50。
    ///
    /// 判据是**穷尽**的：对每一种 `(last, prev)` 组合、每个种子，选出的一招都不许是禁的那一招。
    /// 只测"能选出 Scythe"是不够的 —— 禁令失效时那句话仍然成立。
    #[test]
    fn nemesis_never_repeats_burn_or_scythe_and_never_triple_attacks() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_nemesis", rd_core::content::EK_ENCOUNTER)
                .expect("enc_nemesis")
                .index,
        );
        // 代号：1 = tri_attack、2 = tri_burn、3 = scythe（与动作节目里的 bookkeeping 一致）。
        let ask = |seed: i32, last: i32, prev: i32| -> std::string::String {
            let session = build_session_at(seed, "enc_nemesis", 300, None, 0, 0)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            session.state.current_round = 5;
            for (key, value) in [("last_move", last), ("prev_move", prev)] {
                let _ = session
                    .state
                    .combatant_mut(&cid_in("nemesis"))
                    .expect("nemesis")
                    .set_counter(rd_core::state::CounterId::new(key).expect("counter"), value);
            }
            let at = rd_core::intent::locate_enemy(&content, row, &cid_in("nemesis"))
                .expect("locate")
                .expect("nemesis");
            let pick = rd_core::intent::select_action(
                &session.state,
                &content,
                at,
                &cid_in("nemesis"),
                5,
            )
            .expect("intent")
            .expect("a move");
            let out = pick.action_id.to_string();
            take_session();
            out
        };
        for seed in 0..40 {
            // 不能连 Tri Burn 两次。
            assert_ne!(ask(seed, 2, 1), "nemesis.tri_burn", "seed {seed}: burn twice");
            // 不能连 Scythe 两次。
            assert_ne!(ask(seed, 3, 1), "nemesis.scythe", "seed {seed}: scythe twice");
            // 不能连 Tri Attack 三次。
            assert_ne!(
                ask(seed, 1, 1),
                "nemesis.tri_attack",
                "seed {seed}: three attacks in a row"
            );
        }
        // 首回合只有 Tri Burn / Tri Attack。
        for seed in 0..40 {
            let pick = ask(seed, 0, 0);
            assert_ne!(pick, "nemesis.scythe", "seed {seed}: no Scythe on turn 1");
        }
        let _ = content;
    }

    /// §257：`Reptomancer` 的匕首上限 —— **4 把在手就改打 Snake Strike**。
    ///
    /// 判据两侧：③4 把时必须改招；②2 把时**不许**改招（否则"永远打 Snake Strike"也会绿）。
    #[test]
    fn reptomancer_switches_to_snake_strike_when_four_daggers_are_out() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_reptomancer", rd_core::content::EK_ENCOUNTER)
                .expect("enc_reptomancer")
                .index,
        );
        let session = build_session_at(14, "enc_reptomancer", 300, None, 0, 0).expect("the fight");
        install_session(session);
        let ask = |round: i32| -> std::string::String {
            let session = slot().as_ref().expect("session");
            let at = rd_core::intent::locate_enemy(&content, row, &cid_in("reptomancer"))
                .expect("locate")
                .expect("reptomancer");
            rd_core::intent::select_action(
                &session.state,
                &content,
                at,
                &cid_in("reptomancer"),
                round,
            )
            .expect("intent")
            .expect("a move")
            .action_id
            .to_string()
        };
        let alive = |state: &rd_core::state::CombatState| {
            state
                .combatants()
                .iter()
                .filter(|c| {
                    c.team_id == rd_core::state::TeamId::new("enemy").expect("team")
                        && c.lifecycle_state == rd_core::state::CombatantLifecycleState::Alive
                })
                .count()
        };
        // 开局：Reptomancer + 2 Dagger = 3。第 1 回合永远是 Spawn Dagger。
        {
            let session = slot().as_ref().expect("session");
            assert_eq!(alive(&session.state), 3, "the encounter starts with two daggers");
            assert_eq!(ask(1), "reptomancer.spawn_dagger", "it always opens with Spawn Dagger");
        }
        // 再召两把 ⇒ 5 个活着的敌人（= 4 把匕首）⇒ 上限生效。
        {
            let session = slot().as_mut().expect("session");
            for index in 0..2 {
                session
                    .state
                    .add_combatant(
                        rd_core::state::CombatantId::new(
                            std::format!("dagger#cap{index}").as_str(),
                        )
                        .expect("id"),
                        rd_core::state::TeamId::new("enemy").expect("team"),
                        20,
                    )
                    .expect("summon");
            }
            assert_eq!(alive(&session.state), 5);
            assert_eq!(
                ask(5),
                "reptomancer.snake_strike",
                "four daggers in play ⇒ Spawn Dagger is replaced by Snake Strike"
            );
        }
        take_session();
    }

    /// §257：`Reptomancer` 在 **A18** 一次召两把；同一场在 A17 只召一把。
    ///
    /// 阈值（18）与数量（2）一起测 —— 只测数量会在 A0 就红，只测阈值会在"召了 1 把"上绿。
    #[test]
    fn reptomancer_spawns_two_daggers_at_a18_only() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        for (ascension, expected) in [(17u8, 1usize), (18u8, 2)] {
            let session = build_session_at(15, "enc_reptomancer", 300, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension}: {e}"));
            install_session(session);
            let before = {
                let session = slot().as_ref().expect("session");
                session.state.combatants().len()
            };
            {
                let session = slot().as_mut().expect("session");
                let action_row = u32::from(
                    content
                        .lookup_in("reptomancer.spawn_dagger", rd_core::content::EK_EACTION)
                        .expect("spawn_dagger")
                        .index,
                );
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("reptomancer"),
                    action_row,
                    Some(cid_in("hero")),
                )
                .expect("spawn");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let after = {
                let session = slot().as_ref().expect("session");
                session.state.combatants().len()
            };
            assert_eq!(after - before, expected, "A{ascension}: daggers summoned");
            take_session();
        }
    }

    /// §257：`Blue Slaver` 的 **A17** 规则 —— 绝不连用 Rake 两次；以及任何等级都"同招不连三次"。
    ///
    /// 三段判据，缺一段就会漏掉一种写错的方式：
    /// 1. @A17 且上一次是 Rake ⇒ 只能是 Stab（wiki 的 A17 规则）；
    /// 2. @A16 同一种输入**允许** Rake —— 否则"永远打 Stab"也会让第 1 段绿；
    /// 3. 上一次与上上次都是 Stab ⇒ 不能再 Stab（任何等级）。
    #[test]
    fn blue_slaver_never_rakes_twice_in_a_row_at_a17() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_slavers", rd_core::content::EK_ENCOUNTER)
                .expect("enc_slavers")
                .index,
        );
        let ask = |ascension: u8, seed: i32, last: i32, prev: i32| -> std::string::String {
            let session = build_session_at(seed, "enc_slavers", 300, None, 0, ascension)
                .unwrap_or_else(|e| panic!("A{ascension} seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            session.state.current_round = 6;
            for (key, value) in [("last_move", last), ("prev_move", prev)] {
                let _ = session
                    .state
                    .combatant_mut(&cid_in("blue_slaver"))
                    .expect("blue slaver")
                    .set_counter(rd_core::state::CounterId::new(key).expect("counter"), value);
            }
            let at = rd_core::intent::locate_enemy(&content, row, &cid_in("blue_slaver"))
                .expect("locate")
                .expect("the blue slaver");
            let pick = rd_core::intent::select_action(
                &session.state,
                &content,
                at,
                &cid_in("blue_slaver"),
                6,
            )
            .expect("intent")
            .expect("a move");
            let out = pick.action_id.to_string();
            take_session();
            out
        };
        // 代号：1 = Stab、2 = Rake。
        for seed in 0..40 {
            assert_ne!(
                ask(17, seed, 2, 1),
                "blue_slaver.rake",
                "seed {seed}: A17 forbids Rake twice in a row"
            );
            assert_ne!(
                ask(0, seed, 1, 1),
                "blue_slaver.stab",
                "seed {seed}: the same attack three times in a row is forbidden at any level"
            );
        }
        // @A16 同一种输入仍允许 Rake（否则"永远打 Stab"会让上面第一条白绿）。
        let mut rakes = 0;
        for seed in 0..40 {
            if ask(16, seed, 2, 1) == "blue_slaver.rake" {
                rakes += 1;
            }
        }
        assert!(rakes > 0, "below A17 a Rake after a Rake is legal (took {rakes}/40)");
    }


'''


def main():
    src = io.open(PATH, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, src.count(ANCHOR)
    assert 'lagavulin_wakes_when_it_loses_health' not in src, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TESTS + ANCHOR))
    print('rd-wasm: 7 elite tests appended')


main()
