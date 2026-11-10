"""§336 判据：回放现在**也验战斗开局状态**（`hash_full`）。

三件事：

1. 一段含战斗的脚本，`fight_begin` 那一条的第 5 列**非空**（= 战斗指纹被记下来了）；
2. 把那一列改掉 ⇒ 回放必须报**那一步**的"战斗不同"（而不是"局面不同"）；
3. **旧脚本**（第 5 列为空）⇒ 不比对、照常通过 —— 否则"加判据把旧证据全废掉"。

第 3 条是这次改动最容易踩的：`payload.is_empty()` 必须跳过，而不是拿 0 去比。
"""

import io

PATH = 'kernel/rd-wasm/src/run.rs'

ANCHOR = """    fn replace_nth_hash(script: &str, n: usize) -> String {"""

TESTS = '''    /// §336：`fight_begin` 那一条记录的第 5 列是**战斗状态**的 `hash_full`。
    ///
    /// 为什么这一格值得单独一条判据：回放此前只比**运行层**哈希，而运行层只覆盖
    /// `last_encounter` 一格 —— 敌人 HP、起始状态、每副本 mark、`ascension` / `heal_blocked`
    /// 这些"同一串动作、不同一局"的来源**全看不见**（`hash_golden` 也看不见后两个，
    /// 那是 §334 做 `hash_full` 的理由）。
    #[test]
    fn the_replay_verifies_the_combat_that_fight_begin_rebuilds() {
        // 录一段**含战斗**的脚本。
        reset(7);
        let mut hops = 0;
        while hops < 14 {
            hops += 1;
            if rd_run_step(0) != 0 {
                break;
            }
            let kind = rd_run_node_kind();
            if kind < 0 {
                break;
            }
            if rd_run_begin_node() != 0 {
                break;
            }
            let fight = rd_run_pending() == 0
                && run_slot().as_ref().is_some_and(|s| {
                    s.state.unknown_room() == rd_run::state::UnknownRoom::Monster
                });
            if fight {
                assert_eq!(rd_run_fight_begin(), 0, "hop {hops}: begin");
                assert!(rd_run_fight_end() >= 0, "hop {hops}: end");
            }
            while rd_run_pending() == 4 {
                let _ = rd_run_skip_reward();
            }
            if rd_run_action_count() == 0 && rd_run_pending() != 0 {
                let _ = rd_run_leave();
            }
        }
        let script = script_text_now();
        // 找到 `fight_begin` 那一条，确认第 5 列非空（16 位十六进制）。
        let fight_records: Vec<&str> = script
            .split(';')
            .filter(|record| record.starts_with("fight_begin,"))
            .collect();
        assert!(
            !fight_records.is_empty(),
            "the fixture must record at least one fight: {}",
            &script[..script.len().min(200)]
        );
        for record in &fight_records {
            let cells: Vec<&str> = record.split(',').collect();
            let payload = cells.get(4).copied().unwrap_or("");
            assert_eq!(
                payload.len(),
                16,
                "fight_begin must carry the combat hash_full (16 hex): {record}"
            );
            assert!(
                u64::from_str_radix(payload, 16).is_ok(),
                "and it must be hex: {record}"
            );
        }

        // (1) 原样回放：通过。
        assert_eq!(
            unsafe { rd_run_replay_from(script.as_ptr(), script.len() as i32) },
            0,
            "the recorded script must replay: {}",
            run_error_text()
        );

        // (2) 把**战斗指纹**改掉 ⇒ 报那一步的"战斗不同"。
        let mut broken = String::new();
        let (head, body) = script.split_once(';').expect("a head");
        broken.push_str(head);
        broken.push(';');
        let mut fight_index = None;
        for (index, record) in body.split(';').filter(|r| !r.is_empty()).enumerate() {
            let mut cells: Vec<&str> = record.split(',').collect();
            if record.starts_with("fight_begin,") && fight_index.is_none() {
                fight_index = Some(index);
                if cells.len() > 4 {
                    cells[4] = "00000000deadbeef";
                }
            }
            broken.push_str(&cells.join(","));
            broken.push(';');
        }
        let fight_index = fight_index.expect("a fight record");
        assert!(
            unsafe { rd_run_replay_from(broken.as_ptr(), broken.len() as i32) } > 0,
            "a changed combat hash must diverge: {}",
            run_error_text()
        );
        assert_eq!(
            rd_run_replay_diverged() as usize,
            fight_index + 1,
            "and it must name the fight step ({}), not some later one: {}",
            fight_index + 1,
            run_error_text()
        );
        assert!(
            run_error_text().contains("战斗"),
            "the message must say the **fight** differed: {}",
            run_error_text()
        );

        // (3) 旧脚本（第 5 列为空）⇒ 不比对、照常通过。
        let mut legacy = String::new();
        legacy.push_str(head);
        legacy.push(';');
        for record in body.split(';').filter(|r| !r.is_empty()) {
            let mut cells: Vec<&str> = record.split(',').collect();
            if record.starts_with("fight_begin,") && cells.len() > 4 {
                cells[4] = "";
            }
            legacy.push_str(&cells.join(","));
            legacy.push(';');
        }
        assert_eq!(
            unsafe { rd_run_replay_from(legacy.as_ptr(), legacy.len() as i32) },
            0,
            "a record without the combat hash must still replay (no comparison, not a zero \\
             comparison): {}",
            run_error_text()
        );
    }

    fn replace_nth_hash(script: &str, n: usize) -> String {'''

t = io.open(PATH, encoding='utf-8').read()
assert t.count(ANCHOR) == 1, 'anchor'
assert 'fn the_replay_verifies_the_combat_that_fight_begin_rebuilds' not in t, 'patched'
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR, TESTS))
print('test inserted')
