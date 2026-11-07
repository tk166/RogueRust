"""§276 判据：L 史莱姆的 50% 分裂。

三件事必须同时成立，缺一个就不是 wiki 的那条规则：
1. **阈值是一半最大血**（不是固定的 10 —— 那两条是 Slime Boss 的）；
2. **血量继承当前血**（不是常量）；
3. **本体被替换**（净 +1），所以不可能触发两次。

第 2 条是它的"命门"：`destroyCombatant` 一旦写在 spawn **之前**，`currentHealth` 就没有了
（既有的 `phase_split` 能先删，是因为它 spawn 的是常量 10）—— 那会退化成"分裂出两只满血的"，
而**没有任何闸门会红**（数量对、类型对）。所以这里逐条比**血量**。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '''    #[test]
    fn a_spawned_enemy_joins_the_turn_order_after_the_current_actor() {'''

TEST = r'''    /// §276：L 史莱姆在 **≤50% 最大血**时分裂成两只 M，**继承当前血**，本体被替换。
    ///
    /// 与 `the_boss_phase_splits_once_at_low_health` 的区别就是这两条：阈值按**一半最大血**算、
    /// 血量**不是常量**。所以判据必须逐只比血量 —— 否则"分裂出两只满血的"照样能过。
    #[test]
    fn a_large_slime_splits_at_half_health_with_its_current_hp() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);

        for (status_id, form) in [
            ("standard.split_spike_l", "spike_slime_m"),
            ("standard.split_acid_l", "acid_slime_m"),
        ] {
            let mut state = arena();
            // `enemy_b` 在 arena() 里是 30 点血；15 就是它的一半。
            give(&mut state, "enemy_b", status("st_l", status_id, 1));
            let before = state.combatants().len();
            let hp_before = state
                .combatant(&cid("enemy_b"))
                .expect("the slime")
                .health_current;
            assert!(hp_before > 20, "the fixture must start well above half: {hp_before}");

            // 打到**刚好一半**（15）—— 这一步同时测"≤ 50% 触发"。
            {
                let mut ctx =
                    crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                        .with_content(&content);
                crate::exec::resolve_damage(&mut ctx, &cid("enemy_b"), hp_before / 2, false)
                    .expect("hit");
            }
            host.try_resolve_pending_queues(&mut state).expect("triggers");

            assert_eq!(
                state.combatants().len(),
                before + 1,
                "{status_id}: the bearer is replaced by two (net +1)"
            );
            assert!(
                state.combatant(&cid("enemy_b")).is_none(),
                "{status_id}: the bearer itself is gone"
            );
            // 两只新史莱姆：类型是 M，血量**等于分裂前那一刻的当前血**。
            let half = hp_before - hp_before / 2;
            let spawned: Vec<_> = state
                .combatants()
                .iter()
                .filter(|c| c.definition_id.as_str() == form)
                .collect();
            assert_eq!(spawned.len(), 2, "{status_id}: two {} appear", form);
            for slime in spawned {
                assert_eq!(
                    slime.health_current, half,
                    "{status_id}: the split inherits the **current** HP ({half}), \
                     not the maximum and not a constant"
                );
            }
        }
    }

    /// §276：**没到一半**就不分裂 —— 反面。没有这一条，"一碰就分裂"也能全绿。
    #[test]
    fn a_large_slime_above_half_health_does_not_split() {
        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);
        let mut state = arena();
        give(&mut state, "enemy_b", status("st_l", "standard.split_spike_l", 1));
        let before = state.combatants().len();
        {
            let mut ctx = crate::exec::ExecContext::new(&mut state, Some(cid("hero")), None, None, 64)
                .with_content(&content);
            crate::exec::resolve_damage(&mut ctx, &cid("enemy_b"), 1, false).expect("a scratch");
        }
        host.try_resolve_pending_queues(&mut state).expect("triggers");
        assert_eq!(
            state.combatants().len(),
            before,
            "a scratch above half health must not split it"
        );
        assert!(state.combatant(&cid("enemy_b")).is_some(), "the slime is still there");
    }

'''


def main():
    src = io.open(P, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'a_large_slime_splits_at_half_health_with_its_current_hp' not in src
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TEST + ANCHOR))
    print('§276 split tests appended')


main()
