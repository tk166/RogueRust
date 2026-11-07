"""§272 第四批：修正两条"假设 `?` 房永远是事件"的老判据。

这不是"给新功能让路"，而是老判据里**写死了一个已经不再成立的前提**：
`an_unknown_room_opens_an_event_and_resolves_it` 断言 `pending == 5`，
`a_recorded_run_replays…` 的 8 跳里按 **kind** 结算 —— 而 `?` 房现在会掷出
事件 / 战斗 / 商人 / 宝箱四种结局。

修法：
* 第一条：先确认这个房**真的**掷出了事件（否则它测的是另一条规则），然后照旧。
* 第二条：改按 **`pending`** 结算（`pending` 才是"这个节点要什么"），并把 `?` 房的四种
  结果都走完。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def main():
    src = io.open(P, encoding='utf-8').read()

    # ---- ① 事件那条判据：先确认掷出的是事件
    src = patch(src, '''        assert_eq!(rd_run_node_kind(), 5, "standing on an unknown room");
        assert_eq!(
            rd_run_begin_node(),
            0,
            "the unknown room must open an event; kernel said {:?}",
            run_error_text()
        );
        assert_eq!(rd_run_pending(), 5, "Pending::Event");''',
                '''        assert_eq!(rd_run_node_kind(), 5, "standing on an unknown room");
        assert_eq!(
            rd_run_begin_node(),
            0,
            "the unknown room must settle; kernel said {:?}",
            run_error_text()
        );
        // §272：`?` 房现在会**掷**结果（10/3/2，其余事件）。这条判据测的是**事件**那条路，
        // 所以它必须先证明这个房真的掷出了事件 —— 否则它测的就是另一条规则，而失败信息
        // 会变成一条看不懂的 `Pending` 断言。
        assert_eq!(
            run_slot().as_ref().expect("a run").state.unknown_room(),
            rd_run::state::UnknownRoom::Event,
            "this test is about the event path: the ? room must have rolled an event"
        );
        assert_eq!(rd_run_pending(), 5, "Pending::Event");''', 'event test')

    # ---- ② 回放判据：按 pending 结算，并处理 `?` 房四种结果
    src = patch(src, '''            match kind {
                1 | 2 | 7 => {
                    assert_eq!(rd_run_fight_begin(), 0, "hop {hop}: begin the fight");
                    assert!(rd_run_fight_end() >= 0, "hop {hop}: end the fight");
                }
                3 => {
                    let _ = rd_run_rest();
                }
                5 => {
                    let _ = rd_run_leave();
                }
                6 => {
                    let _ = rd_run_open_chest();
                    let _ = rd_run_leave();
                }
                _ => {}
            }''',
                '''            // §272：按 **`pending`** 结算，不再按 `kind`。`?` 房现在会掷出四种结果，
            // "kind == 5 ⇒ 走事件" 这条假设已经不成立（它会把 `?` 商人的货架留在那儿，
            // 下一步就是 `NodeNotSettled` —— 这条判据当初就是这么红的）。
            let pending = rd_run_pending();
            match pending {
                1 => {
                    let _ = rd_run_rest();
                }
                2 => {
                    let _ = rd_run_leave();
                }
                3 => {
                    let _ = rd_run_open_chest();
                    let _ = rd_run_leave();
                }
                _ => {
                    // 没有待决：要么是一场战斗（战斗节点，或 `?` 房掷出了怪物），要么什么都不用做。
                    let fight = kind == 1 || kind == 2 || kind == 7
                        || (kind == 5
                            && run_slot().as_ref().expect("a run").state.unknown_room()
                                == rd_run::state::UnknownRoom::Monster);
                    if fight {
                        assert_eq!(rd_run_fight_begin(), 0, "hop {hop}: begin the fight");
                        assert!(rd_run_fight_end() >= 0, "hop {hop}: end the fight");
                    }
                }
            }''', 'replay settle')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('two old tests corrected')


main()
