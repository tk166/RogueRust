"""§301：按 `walk_calm_nodes` 的正确驱动形状重写 wasm 那条判据。

第一版直接在循环里 `fight_begin` → `fight_end` → `step`，第 2 场就 `-1`：因为
**战斗不是唯一要结算的东西** —— 奖励屏（`pending == 4`）、事件、宝箱各有自己的收尾，
而 `rd_run_step` 要求"当前节点已结算"。抄 `walk_calm_nodes` 的那套动作。
"""
import io

RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

NEW = r'''    /// §301：`neows_lament` —— 真的开 4 场，前 3 场的敌人**血量与上限**都是 1。
    ///
    /// 判据读的是**战斗里的那份状态**（不是运行层的标志）：只验 `enemy_health_override()`
    /// 的话，"有人问了但没人写"这一跳断了也全绿。
    ///
    /// 驱动形状抄 `walk_calm_nodes`：`step` → `begin_node` → 按节点种类结算 → 清掉奖励屏。
    /// 少这两步，第 2 场 `step` 就会 `-1`（"当前节点没结算"），而那不是遗物的问题。
    #[test]
    fn neows_lament_gives_the_first_three_fights_one_hp_enemies() {
        let deck = ["strike", "strike", "defend", "defend", "bash"];
        test_run(7, 80, 80, &deck);
        run_slot()
            .as_mut()
            .expect("a run")
            .state
            .push_relic("neows_lament", &[])
            .expect("neows_lament");

        let enemy_health = || -> Vec<(i32, i32)> {
            let session = crate::slot().as_ref().expect("a fight");
            let hero = session.hero_id().expect("a hero");
            session
                .state
                .combatants()
                .iter()
                .filter(|combatant| combatant.id != hero)
                .map(|combatant| (combatant.health_current, combatant.health_max))
                .collect()
        };

        let mut fights = 0u32;
        for hop in 0..12 {
            if rd_run_action_count() == 0 {
                break;
            }
            assert_eq!(rd_run_step(0), 0, "hop {hop}: {}", run_error_text());
            let kind = rd_run_node_kind();
            assert_eq!(rd_run_begin_node(), 0, "hop {hop}: kind {kind}");
            match kind {
                1 | 2 | 7 => {
                    assert_eq!(rd_run_fight_begin(), 0, "hop {hop}: {}", run_error_text());
                    let healths = enemy_health();
                    assert!(!healths.is_empty(), "hop {hop}: the fight has enemies");
                    if fights < 3 {
                        assert!(
                            healths.iter().all(|(current, max)| *current == 1 && *max == 1),
                            "fight {} must have 1/1 enemies, got {healths:?}",
                            fights + 1
                        );
                    } else if fights == 3 {
                        assert!(
                            healths.iter().any(|(current, _)| *current > 1),
                            "the 4th fight is back to normal, got {healths:?}"
                        );
                    }
                    fights += 1;
                    assert!(rd_run_fight_end() >= 0, "hop {hop}: {}", run_error_text());
                }
                3 => {
                    let _ = rd_run_rest();
                }
                5 | 6 => {
                    if kind == 6 {
                        let _ = rd_run_open_chest();
                    }
                    let _ = rd_run_leave();
                }
                _ => {}
            }
            while rd_run_pending() == 4 {
                let _ = rd_run_skip_reward();
            }
            if rd_run_action_count() == 0 && rd_run_pending() != 0 {
                let _ = rd_run_leave();
            }
            if fights >= 4 {
                break;
            }
        }
        assert_eq!(fights, 4, "the map walk reached four fights");
    }
'''


def main():
    s = io.open(RUN, encoding='utf-8').read()
    start = s.index('    /// §301：`neows_lament` —— 真的开 4 场')
    end = s.rstrip('\n').rfind('\n}')
    s = s[:start] + NEW + s[end:]
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(s)
    print('wasm test rewritten')


main()
