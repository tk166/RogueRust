"""§313（六）：判据 —— `Protect` 按**定义**点名 Mystic，独自时自保；`Heal` 只在有人缺血时优先。

三条，每条都在钉一个**具体的承诺**：

1. `Protect` 在 Centurion 血量**低于** Mystic 时仍然给 Mystic 挂块 —— 这是"按定义"与
   "按最低血量"的分界线（`sel.lowestHealthAlly` 会给出反例）。
2. Mystic 倒下之后 `Protect` 给自己挂块（wiki 的 "If alone, instead gains 15 Block"）。
3. Mystic 在有盟友缺 ≥16 血时选 `Heal`（`intent.allyMissingHealth`），并**最多连两次**。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

TESTS = '''
    /// §313：`Protect` **按定义**点名 Mystic —— 即使 Centurion 自己血量更低。
    ///
    /// `sel.alliesWithDefinition` 与 `sel.lowestHealthAlly` 的分界线就在这里：后者在
    /// Centurion 掉到 10 血时会返回 Centurion（于是"给自己挂块"），那不是 `Protect`。
    #[test]
    fn protect_gives_the_block_to_the_mystic_even_when_the_centurion_is_hurt() {
        let session = build_session_at(23, "enc_centurion_and_mystic", 200, None, 0, 0)
            .expect("the pair builds");
        install_session(session);
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let block = |state: &rd_core::state::CombatState, who: &str| -> i32 {
            state
                .combatant(&cid_in(who))
                .map_or(-1, |combatant| {
                    combatant
                        .defensive_pools()
                        .iter()
                        .find(|pool| pool.key.as_str() == "standard.block")
                        .map_or(0, |pool| pool.pool.current)
                })
        };
        {
            let session = slot().as_mut().expect("session");
            // Centurion 掉到 10 血 —— **比 Mystic（48）低**，这正是"最低血量"会选错的那一侧。
            session.state.combatant_mut(&cid_in("centurion")).expect("centurion")
                .health_current = 10;
            let row = u32::from(
                content
                    .lookup_in("centurion.protect", rd_core::content::EK_EACTION)
                    .expect("the row")
                    .index,
            );
            rd_core::intent::execute_action(
                &mut session.state,
                &content,
                &cid_in("centurion"),
                row,
                Some(cid_in("hero")),
            )
            .expect("Protect");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
        }
        let session = slot().as_ref().expect("session");
        assert_eq!(block(&session.state, "mystic"), 15, "the Mystic gains 15 Block");
        assert_eq!(
            block(&session.state, "centurion"),
            0,
            "the Centurion does not block itself while the Mystic is alive"
        );
        take_session();
    }

    /// §313：Mystic 倒下之后，`Protect` 给自己挂块（wiki 的两半另一半）。
    #[test]
    fn protect_falls_back_to_the_centurion_when_the_mystic_is_downed() {
        let session = build_session_at(29, "enc_centurion_and_mystic", 200, None, 0, 0)
            .expect("the pair builds");
        install_session(session);
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        {
            let session = slot().as_mut().expect("session");
            // 把 Mystic 打死（1 点真伤 + 派发 Downed）。
            session.state.combatant_mut(&cid_in("mystic")).expect("mystic").health_current = 1;
            let mut host = rd_core::host::Host::new(&content);
            let mut ctx = rd_core::exec::ExecContext::new(
                &mut session.state,
                Some(cid_in("hero")),
                Some(cid_in("mystic")),
                None,
                1024,
            )
            .with_content(&content);
            rd_core::exec::resolve_damage_of_kind(
                &mut ctx,
                &cid_in("mystic"),
                1,
                true,
                rd_core::status_bind::DamageKind::Direct,
            )
            .expect("the killing blow");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch Downed");
            let row = u32::from(
                content
                    .lookup_in("centurion.protect", rd_core::content::EK_EACTION)
                    .expect("the row")
                    .index,
            );
            rd_core::intent::execute_action(
                &mut session.state,
                &content,
                &cid_in("centurion"),
                row,
                Some(cid_in("hero")),
            )
            .expect("Protect");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
        }
        let session = slot().as_ref().expect("session");
        let centurion_block = session
            .state
            .combatant(&cid_in("centurion"))
            .map_or(-1, |combatant| {
                combatant
                    .defensive_pools()
                    .iter()
                    .find(|pool| pool.key.as_str() == "standard.block")
                    .map_or(0, |pool| pool.pool.current)
            });
        assert_eq!(centurion_block, 15, "alone, the Centurion shields itself");
        take_session();
    }

    /// §313：`Heal` 的优先级来自 `intent.allyMissingHealth` —— **盟友**缺血也算，不是自己。
    ///
    /// 三侧：① 谁都没缺 16 血 ⇒ 不选 Heal（概率表里没有它）；② Centurion 掉了 20 血 ⇒ 选 Heal；
    /// ③ 连治两次之后 **不许** 再治（`intent.not(prev==Heal 且 last==Heal)`）。
    #[test]
    fn mystic_heals_when_a_ally_is_missing_sixteen_health_but_only_twice_in_a_row() {
        let session = build_session_at(31, "enc_centurion_and_mystic", 200, None, 0, 0)
            .expect("the pair builds");
        install_session(session);
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let choose = |round: i32| -> Option<&'static str> {
            let session = slot().as_ref().expect("session");
            let row = u32::from(
                content
                    .lookup_in("enc_centurion_and_mystic", rd_core::content::EK_ENCOUNTER)
                    .expect("encounter")
                    .index,
            );
            let at = rd_core::intent::locate_enemy(&content, row, &cid_in("mystic"))
                .expect("locate")
                .expect("the mystic is here");
            rd_core::intent::select_action(&session.state, &content, at, &cid_in("mystic"), round)
                .expect("intent")
                .map(|choice| choice.action_id)
        };
        // ① 满血：Heal 不在候选里。
        assert_ne!(choose(1), Some("mystic.heal"), "nobody is missing 16 HP yet");
        // ② Centurion 掉了 20 血 ⇒ 轮到 Heal。
        {
            let session = slot().as_mut().expect("session");
            session.state.combatant_mut(&cid_in("centurion")).expect("centurion")
                .health_current -= 20;
        }
        assert_eq!(choose(1), Some("mystic.heal"), "an ally is missing 20 HP");
        // ③ 连治两次之后：计数器说 prev/last 都是 Heal ⇒ 这条规则不再命中。
        {
            let session = slot().as_mut().expect("session");
            let combatant = session.state.combatant_mut(&cid_in("mystic")).expect("mystic");
            for (name, value) in (("prev_move", 3), ("last_move", 3)) {
                let key = rd_core::state::Ident::<32>::new(name).expect("counter id");
                combatant
                    .set_counter(rd_core::state::CounterId::new(name).expect("id"), value)
                    .ok();
                let _ = key;
            }
        }
        assert_ne!(
            choose(1),
            Some("mystic.heal"),
            "Heal is capped at two in a row"
        );
        take_session();
    }
'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    anchor = '''    /// §312：Snake Plant 的 `Malleable 3` —— 每次**掉血的攻击**多给 1 块，回合开始清零。'''
    assert text.count(anchor) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(anchor, TESTS + '\n' + anchor))
    print('tests added')


main()
