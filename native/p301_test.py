"""§301 判据：`neows_lament`（前 3 场敌人 1 血）。

两层：
* **运行层**（rd-run）：`enemy_health_override` 在"前 3 场"之内给 `Some(1)`、之后给 `None`；
  没有遗物时恒 `None`。**边界**必须两侧都验（第 3 场有、第 4 场没有）。
* **wasm**：真的开 4 场，第 1–3 场的敌人血量与上限都是 1，第 4 场不是。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
RUN = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

RUN_TEST = r'''
    /// §301：`neows_lament` —— 前 3 场覆盖成 1 血，第 4 场不再覆盖；没有遗物时从不覆盖。
    ///
    /// ⚠️ 边界两侧都要验：只验"前 3 场是 Some(1)"的话，一条"永远 Some(1)"的实现也全绿。
    #[test]
    fn neows_lament_covers_exactly_the_first_three_fights() {
        let deck = ["strike", "defend"];
        let mut run = RunState::new(11, 80, 99, &deck).expect("a run");
        assert_eq!(run.enemy_health_override(), None, "no relic, no override");
        run.push_relic("neows_lament", &[]).expect("pickup");
        assert_eq!(run.enemy_health_override(), None, "the fight has not started yet");
        for fight in 1..=3u8 {
            run.note_fight_started();
            assert_eq!(
                run.enemy_health_override(),
                Some(1),
                "fight {fight} is inside the first three"
            );
        }
        run.note_fight_started();
        assert_eq!(
            run.enemy_health_override(),
            None,
            "the 4th fight is outside the window"
        );
        // 计数本身也要对（它不是"剩下的场次"，是"已经打的场次"）。
        assert_eq!(run.fights(), 4);
    }
'''

WASM_TEST = r'''
    /// §301：`neows_lament` —— 真的开 4 场，前 3 场的敌人**血量与上限**都是 1。
    ///
    /// 判据读的是**战斗里的那份状态**（不是运行层的标志）：只验 `enemy_health_override()`
    /// 的话，"有人问了但没人写"这一跳断了也全绿。
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

        for fight in 1..=4 {
            assert_eq!(rd_run_step(0), 0, "walk onto a node (fight {fight})");
            assert_eq!(rd_run_fight_begin(), 0, "a fight begins (fight {fight})");
            let healths = enemy_health();
            assert!(!healths.is_empty(), "the fight has enemies");
            if fight <= 3 {
                assert!(
                    healths.iter().all(|(current, max)| *current == 1 && *max == 1),
                    "fight {fight} must have 1/1 enemies, got {healths:?}"
                );
            } else {
                assert!(
                    healths.iter().any(|(current, _)| *current > 1),
                    "the 4th fight is back to normal, got {healths:?}"
                );
            }
            // 打完这一场（血是 1 的话一击就死，所以直接结束战斗确认不炸）。
            let _ = rd_run_fight_end();
            // 结束之后回到地图：把光标推进一格（`rd_run_step` 从当前节点出发）。
            if rd_run_pending() != 0 {
                let _ = rd_run_leave();
            }
        }
    }
'''


def main():
    s = io.open(STATE, encoding='utf-8').read()
    cut = s.rstrip('\n').rfind('\n}')
    s = s[:cut] + RUN_TEST + s[cut:]
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('rd-run test')

    t = io.open(RUN, encoding='utf-8').read()
    cut = t.rstrip('\n').rfind('\n}')
    t = t[:cut] + WASM_TEST + t[cut:]
    io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)
    print('wasm test')


main()
