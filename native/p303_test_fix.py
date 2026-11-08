"""§303 判据修正：某些行的每个房间都通（这张图上真的会发生），所以"飞行"要在**能飞的行**上做。

第一版 `.expect("每行都有不相连的房间")` 直接炸了 —— 那不是实现的问题，是判据假设了
"每行至少有一个不相连的房间"。改成：能飞就飞（并验扣次数），不能飞就走免费的路继续找。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

OLD_START = '        // 飞三次：每次扣一次；第三次之后不相连的房间重新被拒。'
OLD_END = '        // Boss 那一步不是飞行'


def main():
    s = io.open(STATE, encoding='utf-8').read()
    start = s.index(OLD_START)
    end = s.index(OLD_END)
    new = '''        // 飞三次：每次扣一次。⚠️ 不是每一行都有"不相连的房间"（这张图上真的有整行全通的行），
        // 所以不能假设"随便找一行就能飞" —— 不能飞的那一行走免费的路继续往前，直到飞满 3 次。
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
            let reachable: Vec<u8> = (0..run.reachable().len())
                .filter_map(|index| run.reachable().get(index))
                .collect();
            match row_nodes.iter().copied().find(|node| !reachable.contains(node)) {
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
                    run.enter_node(reachable[0]).expect("a free walk");
                    assert_eq!(
                        run.wing_boots_left(),
                        expected_left,
                        "a real edge is free"
                    );
                }
            }
            run.mark_resolved();
        }
        assert_eq!(run.wing_boots_left(), 0, "three flights, no charges left");

        // 用完：不相连的房间再次被拒（`reachable()` 缩回普通地图）。
        let row = run.floor as usize;
        if row < ROWS {
            let row_nodes: Vec<u8> = (0..run.map().row(row).map_or(0, |line| line.len()))
                .filter_map(|local| run.map().global_of(row, local))
                .collect();
            let reachable: Vec<u8> = (0..run.reachable().len())
                .filter_map(|index| run.reachable().get(index))
                .collect();
            if let Some(far) = row_nodes.iter().copied().find(|n| !reachable.contains(n)) {
                assert_eq!(
                    run.enter_node(far),
                    Err(RunError::NotReachable),
                    "spent charges mean the ordinary map again"
                );
            }
        }

'''
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s[:start] + new + s[end:])
    print('wing_boots loop rewritten')


main()
