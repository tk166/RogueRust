"""§314（二）：Mugger 的判据 —— 偷钱、带着钱跑、以及"和 Looter 同一套出招"。

wiki 原话是 "Mugger has the same pattern as Looter"，所以这里**不重新设计**判据：
钉三件事就够，且每件都是这条规则的实质：
1. 第 1 回合用 `Mug`（Looter 的骨架：前两回合 Mug）；
2. `Mug` 打 10 点并把 `stolen_gold` 加到 15；
3. `Escape` 把 15 记进 `gold_carried_away`、把计数器清零、并把自己摘出战斗。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

TESTS = '''
    /// §314：Mugger —— 和 Looter **同一套出招**（wiki 原话），数字是 Act 2 的。
    ///
    /// 三件事缺一不可：**偷**（伤害 + `stolen_gold`）、**跑**（`gold_carried_away` + 计数器清零 +
    /// 摘出战斗）、以及**出招节奏**（第 1 回合 Mug —— 它就是从 Looter 抄来的那张规则表）。
    #[test]
    fn the_mugger_mugs_steals_fifteen_gold_and_escapes_with_it() {
        let session = build_session_at(37, "enc_two_thieves", 200, None, 0, 0)
            .expect("2 Thieves builds");
        install_session(session);
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let counter = |state: &rd_core::state::CombatState, who: &str| -> i32 {
            state
                .combatant(&cid_in(who))
                .and_then(|combatant| {
                    combatant
                        .counters()
                        .iter()
                        .find(|entry| entry.key.as_str() == "stolen_gold")
                        .map(|entry| entry.value)
                })
                .unwrap_or(0)
        };
        // 0: 两条贼都在场（wiki 的 Details 列：Looter 在左、Mugger 在右）。
        {
            let session = slot().as_ref().expect("session");
            for who in ["looter", "mugger"] {
                assert!(
                    session.state.combatant(&cid_in(who)).is_some(),
                    "{who} is on the field"
                );
            }
        }
        // 1: 第 1 回合是 Mug（与 Looter 同一个骨架）。
        {
            let session = slot().as_ref().expect("session");
            let row = u32::from(
                content
                    .lookup_in("enc_two_thieves", rd_core::content::EK_ENCOUNTER)
                    .expect("encounter")
                    .index,
            );
            let at = rd_core::intent::locate_enemy(&content, row, &cid_in("mugger"))
                .expect("locate")
                .expect("the mugger is here");
            let action = rd_core::intent::select_action(
                &session.state,
                &content,
                at,
                &cid_in("mugger"),
                1,
            )
            .expect("intent")
            .expect("an action")
            .action_id;
            assert_eq!(action, "mugger.mug", "round 1 is Mug (the Looter pattern)");
        }
        let hero_before = {
            let session = slot().as_ref().expect("session");
            session.state.combatant(&cid_in("hero")).expect("hero").health_current
        };
        // 2: Mug —— 10 点伤害 + 偷 15 块。
        {
            let session = slot().as_mut().expect("session");
            let row = u32::from(
                content
                    .lookup_in("mugger.mug", rd_core::content::EK_EACTION)
                    .expect("the row")
                    .index,
            );
            rd_core::intent::execute_action(
                &mut session.state,
                &content,
                &cid_in("mugger"),
                row,
                Some(cid_in("hero")),
            )
            .expect("Mug");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
        }
        {
            let session = slot().as_ref().expect("session");
            let hero_after = session.state.combatant(&cid_in("hero")).expect("hero").health_current;
            assert_eq!(hero_before - hero_after, 10, "Mug deals 10 damage");
            assert_eq!(counter(&session.state, "mugger"), 15, "Thievery 15 taken from the hero");
        }
        // 3: Escape —— 钱被带走、计数器清零、人摘出战斗。
        {
            let session = slot().as_mut().expect("session");
            let row = u32::from(
                content
                    .lookup_in("mugger.escape", rd_core::content::EK_EACTION)
                    .expect("the row")
                    .index,
            );
            rd_core::intent::execute_action(
                &mut session.state,
                &content,
                &cid_in("mugger"),
                row,
                Some(cid_in("hero")),
            )
            .expect("Escape");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
        }
        let session = slot().as_ref().expect("session");
        assert_eq!(
            session.state.gold_carried_away, 15,
            "the stolen gold leaves the fight with him"
        );
        assert_eq!(counter(&session.state, "mugger"), 0, "the counter is zeroed");
        let still_alive = session
            .state
            .combatant(&cid_in("mugger"))
            .is_some_and(|combatant| {
                combatant.lifecycle_state == rd_core::state::CombatantLifecycleState::Alive
            });
        assert!(!still_alive, "Escape removes him from the field");
        take_session();
    }
'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    anchor = '''    /// §313：`Protect` **按定义**点名 Mystic —— 即使 Centurion 自己血量更低。'''
    assert text.count(anchor) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(anchor, TESTS + '\n' + anchor))
    print('mugger test added')


main()
