"""§303 判据：用地图**自己**重算"真连着"的集合。

第一版拿 `reachable()` 当"相连集合" —— 拿到遗物之后它**包含整层**，于是每次都被判成
"这一行全通"，一行行走到地图尽头。测试侧从 `map()` 重算一遍（独立 oracle），
这样"内核说能点"与"图上真连着"是两个来源 —— 与 §2 的纪律一致。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

OLD_START = '        // 飞三次：每次扣一次。'
OLD_END = '        // Boss 那一步不是飞行'


def main():
    s = io.open(STATE, encoding='utf-8').read()
    start = s.index(OLD_START)
    end = s.index(OLD_END)
    new = '''        // 飞三次：每次扣一次。
        //
        // ⚠️ "哪些是**真的**连着的"不能问 `reachable()` —— 拿到遗物之后它包含**整层**，
        // 于是每一行都会被判成"全通"。这里从地图自己重算一遍（独立 oracle）：
        // 内核说"能点"、图说"真连着"，两个来源比对。
        fn free_edges(run: &RunState) -> Vec<u8> {
            let mut out = Vec::new();
            let target_row = run.floor as usize;
            if target_row >= ROWS {
                return out;
            }
            let Some((row_index, local)) = run.map().locate(run.node as u8) else {
                return out;
            };
            let Some(source) = run.map().row(row_index).and_then(|row| row.node(local)) else {
                return out;
            };
            for &edge in source.out_targets() {
                if let Some(global) = run.map().global_of(row_index + 1, edge as usize) {
                    out.push(global);
                }
            }
            out
        }

        let mut flights = 0u8;
        let mut expected_left = 3u8;
        let mut rows_walked = 0;
        while flights < 3 {
            rows_walked += 1;
            assert!(rows_walked < ROWS, "the map ran out of rows before three flights");
            let row = run.floor as usize;
            assert!(row < ROWS, "still on the map");
            let row_nodes: Vec<u8> = (0..run.map().row(row).map_or(0, |line| line.len()))
                .filter_map(|local| run.map().global_of(row, local))
                .collect();
            // 图上真连着的那些，按 **`reachable()` 的下标顺序**排好（免费的在前）。
            let free = free_edges(&run);
            match row_nodes.iter().copied().find(|node| !free.contains(node)) {
                Some(far) => {
                    run.enter_node(far).expect("a flight");
                    flights += 1;
                    expected_left -= 1;
                    assert_eq!(
                        run.wing_boots_left(),
                        expected_left,
                        "flight {flights} costs exactly one"
                    );
                }
                None => {
                    // 整行都通：走免费的路（这一步**不**扣次数）。
                    run.enter_node(free[0]).expect("a free walk");
                    assert_eq!(run.wing_boots_left(), expected_left, "a real edge is free");
                }
            }
            run.mark_resolved();
        }
        assert_eq!(run.wing_boots_left(), 0, "three flights, no charges left");

        // 用完：不相连的房间再次被拒（`reachable()` 缩回普通地图）。
        let row = run.floor as usize;
        if row < ROWS {
            let free = free_edges(&run);
            let row_nodes: Vec<u8> = (0..run.map().row(row).map_or(0, |line| line.len()))
                .filter_map(|local| run.map().global_of(row, local))
                .collect();
            if let Some(far) = row_nodes.iter().copied().find(|n| !free.contains(n)) {
                assert_eq!(
                    run.enter_node(far),
                    Err(RunError::NotReachable),
                    "spent charges mean the ordinary map again"
                );
            }
        }

'''
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s[:start] + new + s[end:])
    print('oracle-based loop')


main()
