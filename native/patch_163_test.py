"""§163: the replay test — a real script reproduces, and a tampered one names the step.

The falsifiable half is the point: "the replay passed" is worthless unless a **broken** script is
caught and reports **which** step broke. So this test runs it three ways:

1. a scripted few-node run → replay → `0` and every step verified;
2. the same script with one recorded hash overwritten → the replay returns that step's index;
3. the same script with one **argument** changed → it diverges (at that step or later).

The fights are `begin` + `end` with no cards played: the replay never re-simulates a fight (that is
`CombatState`, and a fight is the player's card play, not the run layer), it applies the recorded
outcome. Saying so here keeps the scope honest instead of implied.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// §161.10 P0: 存档走**自己的**缓冲区，容量由 ABI 公布。"""

TEST = '''    /// §163: 回放 —— 一串真实动作重放一遍必须逐步对上；篡改过的脚本必须**指出是哪一步**。
    #[test]
    fn a_recorded_run_replays_step_by_step_and_a_tampered_one_names_its_step() {
        test_run(7, 80, 80, &["strike"; 10]);
        // 开局：出门一条祝福（走完它，否则后面每一步都被 `Pending::Start` 挡住）。
        assert_eq!(rd_run_step(0), 0, "floor 1");
        assert_eq!(rd_run_choose_start(0), 0, "take blessing 0");
        while rd_run_pending() == 7 {
            assert_eq!(rd_run_pick_blessing_card(0), 0, "the blessing owes a pick");
        }

        // 走几个节点，按类型结算。战斗只 `begin` + `end`（不真打牌），因为回放不重演战斗。
        for hop in 0..5 {
            let reachable = rd_run_action_count();
            assert!(reachable > 0, "hop {hop}: nowhere to go");
            assert_eq!(rd_run_step(0), 0, "hop {hop}: enter");
            let kind = rd_run_node_kind();
            assert_eq!(rd_run_begin_node(), 0, "hop {hop}: begin a kind-{kind} node");
            match kind {
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
            }
            // 奖励屏（战斗之后）与其它待决问句都要走完，否则下一步进不去。
            while rd_run_pending() == 4 {
                let _ = rd_run_skip_reward();
            }
            while rd_run_pending() == 8 {
                let _ = rd_run_pick_event_card(0);
            }
        }

        let steps = run_slot().as_ref().expect("session").journal.len();
        assert!(steps >= 8, "the fixture must record a real script, it recorded {steps}");
        let before = {
            let session = run_slot().as_ref().expect("session");
            rd_run::hash::run_hash_hex(&session.state).expect("hash")
        };
        let script = {
            let len = rd_run_script_len();
            assert!(len > 0, "script_len said {len}");
            let mut buffer = vec![0u8; len as usize];
            unsafe { rd_run_script_into(buffer.as_mut_ptr()) };
            String::from_utf8(buffer).expect("ascii")
        };
        assert!(script.starts_with("RDR1,7,0;"), "head: {}", &script[..16.min(script.len())]);

        // (1) 重放：每一步都必须对上。
        assert_eq!(
            unsafe { rd_run_replay_from(script.as_ptr(), script.len() as i32) },
            0,
            "the recorded script must replay: {}",
            run_error_text()
        );
        assert_eq!(rd_run_replay_checked() as usize, steps, "every step verified");
        assert_eq!(rd_run_replay_diverged(), 0);
        let after = {
            let session = run_slot().as_ref().expect("session");
            rd_run::hash::run_hash_hex(&session.state).expect("hash")
        };
        assert_eq!(after, before, "the replay must land on the same run");

        // (2) 把一个哈希改掉：必须报**那一步**。
        let broken_hash = replace_nth_hash(&script, 2);
        assert_eq!(
            unsafe { rd_run_replay_from(broken_hash.as_ptr(), broken_hash.len() as i32) },
            3,
            "a bad hash at step 3 must be reported as step 3: {}",
            run_error_text()
        );
        assert_eq!(rd_run_replay_diverged(), 3);
        assert_eq!(rd_run_replay_checked(), 2, "the two steps before it did verify");

        // (3) 改一个**参数**（第 2 步的 arg0）：局面不同，必须红，而且不会悄悄通过。
        let broken_arg = replace_nth_arg(&script, 1, 999);
        assert!(
            unsafe { rd_run_replay_from(broken_arg.as_ptr(), broken_arg.len() as i32) } > 0,
            "a changed argument must diverge: {}",
            run_error_text()
        );

        // (4) 垃圾一律拒，且不留下半局。
        assert_eq!(
            unsafe { rd_run_replay_from(b"hello".as_ptr(), 5) },
            -2,
            "a script without a head is refused"
        );
        assert_eq!(
            unsafe { rd_run_replay_from(b"RDR1,7,0;nonsense,1,2,3,;".as_ptr(), 25) },
            1,
            "an unknown kind is reported as step 1"
        );
    }

    /// 把第 `n`（0 基）条记录的哈希换成垃圾，其余原样。
    fn replace_nth_hash(script: &str, n: usize) -> String {
        let (head, body) = script.split_once(';').expect("a head");
        let mut out = std::format!("{head};");
        for (index, record) in body.split(';').filter(|r| !r.is_empty()).enumerate() {
            let mut cells: Vec<&str> = record.split(',').collect();
            if index == n {
                cells[3] = "dead0000dead0000";
            }
            out.push_str(&cells.join(","));
            out.push(';');
        }
        out
    }

    /// 把第 `n` 条记录的 `arg{which}` 换掉。
    fn replace_nth_arg(script: &str, n: usize, value: i32) -> String {
        let (head, body) = script.split_once(';').expect("a head");
        let mut out = std::format!("{head};");
        for (index, record) in body.split(';').filter(|r| !r.is_empty()).enumerate() {
            let mut cells: Vec<&str> = record.split(',').collect();
            if index == n {
                let text = value.to_string();
                cells[1] = Box::leak(text.into_boxed_str());
            }
            out.push_str(&cells.join(","));
            out.push(';');
        }
        out
    }

    /// §161.10 P0: 存档走**自己的**缓冲区，容量由 ABI 公布。'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn a_recorded_run_replays_step_by_step" not in text, "already inserted"
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, TEST))
    print("replay test added")


if __name__ == "__main__":
    main()
