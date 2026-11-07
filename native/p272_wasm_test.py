"""§272 wasm 判据（第二版）：走图到 `?` 房并检查 `fight_begin` 的闸门。

第一版失败在**判据自己**的走法上：它在 `begin_node` 之后再调 `mark_resolved`，而 `?` 房
`begin_node` 之后 `pending` 已经不是 `None`（事件/商店/宝箱），`mark_resolved` 不是那时该做的事。
正确走法是 `rd_run_step` → `mark_resolved` → `rd_run_step` …（不调 `begin_node`），
直到光标落在 `?` 房上。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

HELPER = '''    /// §272：把游标推到一个 `?` 房上（不 `begin_node`）—— 走一步、结算、再走一步。
    ///
    /// 为什么不做 `begin_node`：结算一个节点有它自己的动作（休息/离开/开宝箱），而这条判据只
    /// 关心"走到 `?` 房"这件事。`mark_resolved` 是那条最短路径（结算位是公开的）。
    fn walk_until_unknown(seed: i32) -> bool {
        test_run(seed, 80, 80, &["strike"; 10]);
        for _ in 0..10 {
            if rd_run_node_kind() == i32::from(rd_run::map::NodeKind::Unknown as u8) {
                return true;
            }
            if rd_run_step(0) != 0 {
                return false;
            }
            run_slot().as_mut().expect("a run").state.mark_resolved();
        }
        rd_run_node_kind() == i32::from(rd_run::map::NodeKind::Unknown as u8)
    }

'''

TEST = r'''    /// §272：`?` 房掷出怪物 ⇒ `fight_begin` 接受它（用本幕的**普通**池）；掷出事件则拒绝。
    ///
    /// ⚠️ 判据真的**走到一个 `?` 房、让它自己掷**（不是自己把 `unknown_room` 改成 Monster ——
    /// 那样会把"掷骰"这一段整个绕过去）。
    #[test]
    fn an_unknown_room_can_start_an_ordinary_fight() {
        let mut monster_seed = None;
        for seed in 0..2000 {
            if !walk_until_unknown(seed) {
                continue;
            }
            if rd_run_begin_node() != 0 {
                continue;
            }
            if run_slot().as_ref().expect("a run").state.unknown_room()
                == rd_run::state::UnknownRoom::Monster
            {
                monster_seed = Some(seed);
                break;
            }
        }
        let seed = monster_seed.expect("no seed produced a monster ? room in 2000 tries");
        // 地图上它仍然是 `?`（战斗**不**改节点的类型）。
        assert_eq!(
            rd_run_node_kind(),
            i32::from(rd_run::map::NodeKind::Unknown as u8),
            "seed {seed}: the map still says ?"
        );
        assert_eq!(rd_run_fight_begin(), 0, "seed {seed}: a ? fight begins");
        assert!(
            run_slot().as_ref().expect("a run").in_fight,
            "seed {seed}: the session is in a fight now"
        );

        // 反面：掷出**事件**的 `?` 房不许开战。
        for seed in 0..2000 {
            if !walk_until_unknown(seed) {
                continue;
            }
            if rd_run_begin_node() != 0 {
                continue;
            }
            if run_slot().as_ref().expect("a run").state.unknown_room()
                == rd_run::state::UnknownRoom::Event
            {
                assert!(
                    rd_run_fight_begin() < 0,
                    "seed {seed}: an event ? room must not start a fight"
                );
                return;
            }
        }
        panic!("no seed produced an event ? room in 2000 tries");
    }

'''


def main():
    src = io.open(P, encoding='utf-8').read()

    start = src.index('    /// §272：`?` 房掷出怪物 ⇒ `fight_begin` 接受它，用的是本幕的**普通**池。')
    end = src.index('    /// §271：`toy_ornithopter` —— 喝一瓶药水', start)
    src = src[:start] + TEST + src[end:]

    # 助手放在测试模块顶端（`exported_observation` 之后）
    anchor = '    /// **7 migrated / 20 to go**'
    assert src.count(anchor) == 1
    src = src.replace(anchor, HELPER + anchor)

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('wasm test rewritten')


main()
