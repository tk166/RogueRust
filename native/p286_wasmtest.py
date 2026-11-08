"""§286 wasm 端到端判据：事件 → 伏击 → 开打（精英）→ 结算。

判据要点：
* `rd_run_choose` 选了 `[Fight]` 之后，`rd_run_event_fight()` = 2（精英）；
* `rd_run_fight_begin()` **接受**（否则 Dead Adventurer 的伏击在页面上是死按钮）；
* 这一场按**精英**结算（`elite_fight`）；
* 再按一次 `fight_begin` 仍被拒（"节点只付一次"没被这条新路破坏）。

直接构造状态、不走整张地图：这条判据测的是**接线**，不是地图。走地图那条由
`an_unknown_room_can_start_an_ordinary_fight`（§272）钉着。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

ANCHOR = '''    /// §272：`?` 房掷出怪物 ⇒ `fight_begin` 接受它（用本幕的**普通**池）；掷出事件则拒绝。'''

TEST = r'''    /// §286：**事件把房间变成一场战斗** —— `[Fight]` 之后 `fight_begin` 必须接受，并且按
    /// **精英**结算。
    #[test]
    fn an_event_fight_begins_and_settles_as_an_elite() {
        // 站在一个 `?` 房上，开 `Dead Adventurer`，选 `[Fight]`。
        let mut seed_found = None;
        for seed in 0..2000 {
            if !walk_until_unknown(seed) {
                continue;
            }
            if rd_run_begin_node() != 0 {
                continue;
            }
            // 手动开事件（不掷"这一间是哪个事件"：那是 §277 的 `?` 分流，与本判据无关）。
            let opened = run_slot()
                .as_mut()
                .expect("a run")
                .state
                .begin_event("dead_adventurer", "dead_adventurer.ambush");
            if opened.is_err() {
                continue;
            }
            seed_found = Some(seed);
            break;
        }
        let seed = seed_found.expect("no seed produced a `?` room in 2000 tries");

        // 伏击那一段只有一个 `[Fight]`。
        assert_eq!(rd_run_choose_count(), 1, "seed {seed}: the ambush step offers one option");
        assert_eq!(rd_run_choose(0), 0, "seed {seed}: {}", run_error_text());
        assert_eq!(rd_run_event_fight(), 2, "seed {seed}: the band is `elite`");
        assert!(
            !run_slot().as_ref().expect("a run").state.node_resolved(),
            "seed {seed}: the fight settles the node, so it must still be open"
        );

        // 开工 —— 这就是"事件中途开战斗"的那一半。
        assert_eq!(rd_run_fight_begin(), 0, "seed {seed}: {}", run_error_text());
        let session = run_slot().as_ref().expect("a run");
        assert!(session.in_fight, "seed {seed}: a fight is installed");
        assert!(session.elite_fight, "seed {seed}: it settles as an **elite**");

        // 打完：节点结算，档位清空（`mark_resolved` 是唯一清它的地方）。
        assert_eq!(rd_run_fight_end(), 0, "seed {seed}: {}", run_error_text());
        let session = run_slot().as_ref().expect("a run");
        assert_eq!(session.state.event_fight(), 0, "seed {seed}: the band is cleared");
        assert!(session.state.node_resolved(), "seed {seed}: the node paid out");
    }

'''

def main():
    s = io.open(P, encoding='utf-8').read()
    assert s.count(ANCHOR) == 1
    assert 'an_event_fight_begins_and_settles_as_an_elite' not in s
    s = s.replace(ANCHOR, TEST + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('§286 wasm test appended')


main()
