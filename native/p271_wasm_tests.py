"""§271 wasm 判据（修正版）：不依赖不存在的导出，改成直接操作 `run_slot` 的 `state`。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
RUN_STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

ANCHOR = '''    #[test]
    fn the_container_bounds_are_the_run_layers_and_not_the_pages() {'''

TESTS = r'''    /// §271：`toy_ornithopter` —— 喝一瓶药水，**战斗里的英雄**回 5 血。
    ///
    /// ⚠️ 判据的关键是"回的是战斗里那一份"：改 `run.health` 也会"看起来回了 5"，
    /// 但战斗结束折回时会被覆盖 —— 所以这里读的是**战斗员**的血。
    #[test]
    fn drinking_a_potion_heals_five_with_the_toy_ornithopter() {
        for (relic, want_heal) in [(Some("toy_ornithopter"), true), (None, false)] {
            test_run(
                7, 80, 80,
                &["strike", "strike", "strike", "strike", "strike",
                  "defend", "defend", "defend", "defend", "bash"],
            );
            if let Some(relic) = relic {
                run_slot()
                    .as_mut()
                    .expect("a run")
                    .state
                    .push_relic(relic)
                    .unwrap_or_else(|e| panic!("{relic}: {e:?}"));
            }
            let node = run_slot()
                .as_ref()
                .and_then(|run| run.state.reachable().get(0))
                .expect("a floor-1 node");
            assert_eq!(rd_run_enter_node(i32::from(node)), 0);
            assert_eq!(rd_run_fight_begin(), 0, "a fight begins");

            let before = {
                let session = crate::slot().as_ref().expect("a fight");
                let hero = session.hero_id().expect("a hero");
                session.state.combatant(&hero).expect("the hero").health_current
            };
            let potion = b"block_potion";
            unsafe {
                assert_eq!(rd_run_grant_potion(potion.as_ptr(), potion.len() as i32), 0);
            }
            assert_eq!(rd_env_use_potion(0, 0), 0, "the potion is used");
            let after = {
                let session = crate::slot().as_ref().expect("still in the fight");
                let hero = session.hero_id().expect("a hero");
                session.state.combatant(&hero).expect("the hero").health_current
            };
            if want_heal {
                assert_eq!(after, (before + 5).min(80), "toy_ornithopter heals 5 in combat");
            } else {
                assert_eq!(after, before, "without the relic a potion heals nothing");
            }
        }
    }

    /// §271：`ancient_tea_set` —— "欠一场"在**真的开战**之后被清掉，而那一场真的拿到了状态。
    #[test]
    fn the_tea_set_charge_is_spent_by_the_next_fight() {
        test_run(
            7, 80, 80,
            &["strike", "strike", "strike", "strike", "strike",
              "defend", "defend", "defend", "defend", "bash"],
        );
        run_slot()
            .as_mut()
            .expect("a run")
            .state
            .push_relic("ancient_tea_set")
            .expect("ancient_tea_set");
        // 直接欠上：篝火那条路在 `rd-run` 的判据里逐条验过，这里只验"开战消费"。
        run_slot()
            .as_mut()
            .expect("a run")
            .state
            .owe_tea_set_for_the_next_fight();
        assert!(run_slot().as_ref().expect("a run").state.tea_set_pending());

        let node = run_slot()
            .as_ref()
            .and_then(|run| run.state.reachable().get(0))
            .expect("a floor-1 node");
        assert_eq!(rd_run_enter_node(i32::from(node)), 0);
        assert_eq!(rd_run_fight_begin(), 0, "a fight begins");

        assert!(
            !run_slot().as_ref().expect("a run").state.tea_set_pending(),
            "the charge is spent by the fight it was owed to"
        );
        // 而且那一场**真的**挂上了状态（否则"清掉了"这件事毫无意义）。
        let granted = {
            let session = crate::slot().as_ref().expect("a fight");
            let hero = session.hero_id().expect("a hero");
            let combatant = session.state.combatant(&hero).expect("the hero");
            combatant
                .statuses
                .iter()
                .flatten()
                .any(|status| status.id == "standard.ancient_tea_set")
        };
        assert!(granted, "the fight must have the tea set status on the hero");
    }

'''

OWE = '''    /// §271：欠下一场"开战 +2 能量"（`ancient_tea_set`）。
    ///
    /// 公开是给两个调用方：`begin_node` 的篝火分支（真实路径），以及判据里"直接欠上、
    /// 只看开战有没有消费"的那一段（它不该为了造局面去走一遍篝火）。
    pub fn owe_tea_set_for_the_next_fight(&mut self) {
        if self.holds_relic_effect(RelicEffect::RestEntryNextCombatEnergy(
            "standard.ancient_tea_set",
            1,
        )) {
            self.tea_set_pending = true;
        }
    }

'''


def main():
    src = io.open(P, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'drinking_a_potion_heals_five_with_the_toy_ornithopter' not in src
    src = src.replace(ANCHOR, TESTS + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)

    # 运行层：`owe_tea_set_for_the_next_fight`（并让篝火分支用它 —— 一条规则一个实现）
    s = io.open(RUN_STATE, encoding='utf-8').read()
    old = '''                if self.holds_relic_effect(RelicEffect::RestEntryNextCombatEnergy(
                    "standard.ancient_tea_set",
                    1,
                )) {
                    self.tea_set_pending = true;
                }
                Pending::Rest'''
    new = '''                self.owe_tea_set_for_the_next_fight();
                Pending::Rest'''
    assert s.count(old) == 1
    s = s.replace(old, new)
    anchor = '    /// §271：`ancient_tea_set` 是否欠着一场"开战 +2 能量"。'
    assert s.count(anchor) == 1
    s = s.replace(anchor, OWE + anchor)
    io.open(RUN_STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('wasm tests + owe_tea_set_for_the_next_fight')


main()
