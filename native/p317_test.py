"""§317（二）：Transient 的三条判据 —— 伤害递增、`Shifting` 临时掉力量、`Fading` 到点消失。

三条各钉一处"只测一半就会静默错"的地方：
1. **伤害递增**：第 1 回合 30、第 2 回合 40（`20 + 10×roundNumber`）。只测一次会漏掉"随回合涨"。
2. **`Shifting`**：挨 7 点伤害 ⇒ 力量 -7；**回合末加回来**（用 §219 的 `regain_strength`）。
   只测"掉了"会漏掉"还回来"——那才是这条 power 的整个意思。
3. **`Fading`**：5 回合之后自己消失（`destroyCombatant`）。只测"层数在减"会漏掉"最后会死"。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

TESTS = '''
    /// §317：Transient 的三条规则 —— 伤害随回合涨、Shifting 临时掉力量、Fading 到点消失。
    ///
    /// 全部在**真战斗**里跑（`enc_transient`），因为这三条都靠触发器 + 表达式，单测内容形状
    /// 抓不到"它到底有没有生效"。
    #[test]
    fn the_transient_scales_its_attack_shifts_strength_and_fades_away() {
        use rd_core::status_bind::DamageKind;

        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let attack_row = u32::from(
            content
                .lookup_in("transient.attack", rd_core::content::EK_EACTION)
                .expect("the row")
                .index,
        );
        let stacks = |state: &rd_core::state::CombatState, status: &str| -> i32 {
            state
                .combatant(&cid_in("transient"))
                .map(|combatant| {
                    combatant
                        .statuses()
                        .iter()
                        .filter(|instance| instance.definition_id.as_str() == status)
                        .map(|instance| instance.stacks)
                        .sum()
                })
                .unwrap_or(0)
        };
        let hero_hp = |state: &rd_core::state::CombatState| -> i32 {
            state.combatant(&cid_in("hero")).map_or(-1, |hero| hero.health_current)
        };

        // ── 1. 伤害随回合涨：第 1 回合 30、第 2 回合 40。
        for (round, expected) in [(1i32, 30i32), (2, 40)] {
            let session = build_session_at(53, "enc_transient", 400, None, 0, 0)
                .expect("the transient fight builds");
            install_session(session);
            let before = {
                let session = slot().as_ref().expect("session");
                hero_hp(&session.state)
            };
            {
                let session = slot().as_mut().expect("session");
                session.state.current_round = round;
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("transient"),
                    attack_row,
                    Some(cid_in("hero")),
                )
                .expect("the attack");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let session = slot().as_ref().expect("session");
            assert_eq!(
                before - hero_hp(&session.state),
                expected,
                "round {round}: 20 + 10×round"
            );
            take_session();
        }

        // ── 2. Shifting：挨 7 点伤害 ⇒ 力量 -7，**回合末加回来**。
        {
            let session = build_session_at(59, "enc_transient", 400, None, 0, 0)
                .expect("the transient fight builds");
            install_session(session);
            let mut host = rd_core::host::Host::new(&content);
            {
                let session = slot().as_mut().expect("session");
                let mut ctx = rd_core::exec::ExecContext::new(
                    &mut session.state,
                    Some(cid_in("hero")),
                    Some(cid_in("transient")),
                    None,
                    1024,
                )
                .with_content(&content);
                rd_core::exec::resolve_damage_of_kind(
                    &mut ctx,
                    &cid_in("transient"),
                    7,
                    true,
                    DamageKind::Direct,
                )
                .expect("the hit lands");
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
                host.resolve_pending_queues_with(
                    &mut session.state,
                    rd_core::host::QueueLimits::DEFAULT,
                )
                .expect("shifting fires");
            }
            {
                let session = slot().as_ref().expect("session");
                assert_eq!(
                    stacks(&session.state, "standard.strength"),
                    -7,
                    "Shifting takes 7 Strength until the end of the turn"
                );
            }
            {
                let session = slot().as_mut().expect("session");
                host.try_run_turn_ended_triggers(&mut session.state, &cid_in("transient"))
                    .expect("turn ended");
                host.resolve_pending_queues_with(
                    &mut session.state,
                    rd_core::host::QueueLimits::DEFAULT,
                )
                .expect("drain");
            }
            let session = slot().as_ref().expect("session");
            assert_eq!(
                stacks(&session.state, "standard.strength"),
                0,
                "and gives it back at the end of the turn"
            );
            take_session();
        }

        // ── 3. Fading：5 回合之后自己消失（第 5 次回合结束时）。
        {
            let session = build_session_at(61, "enc_transient", 400, None, 0, 0)
                .expect("the transient fight builds");
            install_session(session);
            let mut host = rd_core::host::Host::new(&content);
            for turn in 1..=5 {
                {
                    let session = slot().as_mut().expect("session");
                    host.try_run_turn_ended_triggers(&mut session.state, &cid_in("transient"))
                        .expect("turn ended");
                    host.resolve_pending_queues_with(
                        &mut session.state,
                        rd_core::host::QueueLimits::DEFAULT,
                    )
                    .expect("drain");
                }
                let left = {
                    let session = slot().as_ref().expect("session");
                    stacks(&session.state, "standard.fading")
                };
                let alive = {
                    let session = slot().as_ref().expect("session");
                    session
                        .state
                        .combatant(&cid_in("transient"))
                        .is_some_and(|combatant| {
                            combatant.lifecycle_state
                                == rd_core::state::CombatantLifecycleState::Alive
                        })
                };
                if turn < 5 {
                    assert_eq!(left, 5 - turn, "turn {turn}: one turn closer to fading");
                    assert!(alive, "turn {turn}: still here");
                } else {
                    assert!(!alive, "turn 5 is the last one — it fades away");
                }
            }
            take_session();
        }
    }
'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    anchor = '''    /// §316：Exploder 的 `Explode` —— 30 点伤害之后**自己死**（wiki："Deals 30 damage. Dies."）。'''
    assert text.count(anchor) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(anchor, TESTS + '\n' + anchor))
    print('transient test added')


main()
