"""§164: a run restored from an archive can be replayed — the head carries the archive.

Why this needs its own test: the first head form was `RDR1,seed,asc`, and a restored run's state is
**not on that timeline**. Two things must therefore hold, and both are falsifiable:

1. `rd_run_restore_from` clears the journal — otherwise the exported script's first record is an
   action that happened to the *previous* run and the replay diverges immediately;
2. the head becomes `RDR1,A,<archive>`, and the replay restores from it instead of starting a run.

Without (2) the script of a restored run can never replay, and "0 steps verified" would look like
success — the exact shape of a lying gate.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// 把第 `n`（0 基）条记录的哈希换成垃圾，其余原样。"""

TEST = '''    /// §164: 回档之后接着打的那些步，靠**头部携带档案**回放。
    #[test]
    fn a_run_restored_from_an_archive_replays_from_its_archive() {
        // (1) 一局，走到有几步历史。
        assert_eq!(rd_run_start(5, 0), 0);
        assert_eq!(rd_run_choose_start(0), 0);
        while rd_run_pending() == 7 {
            assert_eq!(rd_run_pick_blessing_card(0), 0);
        }
        walk_calm_nodes(2);
        let archive = {
            let len = rd_run_archive_fill();
            assert!(len > 0, "archive: {}", run_error_text());
            let capacity = rd_run_archive_capacity();
            assert!(len <= capacity);
            let ptr = rd_run_archive_buf();
            String::from_utf8(unsafe {
                std::slice::from_raw_parts(ptr, len as usize).to_vec()
            })
            .expect("ascii")
        };
        assert!(archive.starts_with("RDA1-"), "head: {}", &archive[..12]);

        // (2) 换一局**完全不同**的（别的种子、别的几步），再回档到 (1)。日志里现在是一段与
        // 恢复出来的局面无关的历史 —— 不清掉它，下面第一步就会分叉。
        assert_eq!(rd_run_start(9, 0), 0);
        assert_eq!(rd_run_choose_start(0), 0);
        while rd_run_pending() == 7 {
            assert_eq!(rd_run_pick_blessing_card(0), 0);
        }
        walk_calm_nodes(1);
        assert!(
            unsafe { rd_run_restore_from(archive.as_ptr(), archive.len() as i32) } == 0,
            "restore: {}",
            run_error_text()
        );
        assert_eq!(rd_run_seed(), 5, "the restored run is the first one");
        let steps_after_restore = {
            let mut buffer = vec![0u8; rd_run_script_len() as usize];
            unsafe { rd_run_script_into(buffer.as_mut_ptr()) };
            String::from_utf8(buffer).expect("ascii")
        };
        assert_eq!(
            steps_after_restore.matches(';').count(),
            1,
            "a restore starts a new history: {}",
            &steps_after_restore[..steps_after_restore.len().min(40)]
        );

        // (3) 从恢复出来的局面接着打，然后导出：头部必须是那份档案。
        walk_calm_nodes(2);
        let script = {
            let mut buffer = vec![0u8; rd_run_script_len() as usize];
            unsafe { rd_run_script_into(buffer.as_mut_ptr()) };
            String::from_utf8(buffer).expect("ascii")
        };
        assert!(
            script.starts_with("RDR1,A,RDA1-"),
            "head: {}",
            &script[..script.len().min(24)]
        );
        let steps = script.matches(';').count() - 1;
        assert!(steps >= 3, "the continuation must be recorded, got {steps}");

        // (4) 回放：从档案恢复，再走这些步，每一步都要对上。
        assert_eq!(
            unsafe { rd_run_replay_from(script.as_ptr(), script.len() as i32) },
            0,
            "the continuation must replay: {}",
            run_error_text()
        );
        assert_eq!(rd_run_replay_checked() as usize, steps);
        assert_eq!(rd_run_seed(), 5);
        let after = {
            let mut buffer = vec![0u8; rd_run_script_len() as usize];
            unsafe { rd_run_script_into(buffer.as_mut_ptr()) };
            String::from_utf8(buffer).expect("ascii")
        };
        assert!(
            after.starts_with("RDR1,A,RDA1-"),
            "a replayed run still starts at its archive: {}",
            &after[..after.len().min(24)]
        );

        // (5) 判据的反面：篡改原始脚本 → 必须报出那一步。
        let broken = tamper_hash(&script, 1);
        assert_eq!(
            unsafe { rd_run_replay_from(broken.as_ptr(), broken.len() as i32) },
            2,
            "step 2 was tampered: {}",
            run_error_text()
        );
        assert_eq!(rd_run_replay_checked(), 1);
    }

    /// 走 `hop` 个**非战斗**节点（战斗要真打牌，而这条测试问的是历史与头部）。
    fn walk_calm_nodes(hop: usize) {
        for index in 0..hop {
            if rd_run_action_count() == 0 {
                return;
            }
            let reachable = rd_run_action_count();
            let mut chosen = 0;
            for probe in 0..reachable {
                // `rd_run_node_kind()` 只说**当前**节点的种类，所以先看目标：代价太高。
                // 这条测试不挑种类，只要求走得动 —— 所以直接取第 index 个可走项。
                chosen = probe.min(reachable - 1);
            }
            assert_eq!(rd_run_step(chosen), 0, "hop {index}: {}", run_error_text());
            let _ = rd_run_begin_node();
            if rd_run_pending() == 3 || rd_run_pending() == 5 || rd_run_pending() == 6 {
                let _ = rd_run_leave();
            }
            while rd_run_pending() == 4 {
                let _ = rd_run_skip_reward();
            }
            if rd_run_action_count() == 0 && rd_run_pending() != 0 {
                let _ = rd_run_leave();
            }
        }
    }

    /// 把第 `n`（0 基）条记录的哈希换成垃圾。
    fn tamper_hash(script: &str, n: usize) -> String {
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

    /// 把第 `n`（0 基）条记录的哈希换成垃圾，其余原样。'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn a_run_restored_from_an_archive" not in text, "already inserted"
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, TEST))
    print("archive-head replay test added")


if __name__ == "__main__":
    main()
