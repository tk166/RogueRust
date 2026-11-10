"""§344 判据：`run_end()` 四态、`end_act()` 三条前提、`BEAT_DESTROYED` 穷尽。

## 为什么 `run_end()` 值得四条

页面前有一对**自己记的**变量。它们能对，是因为页面的每一处赋值都记得改；而"记得"不是判据。
`run_end()` 把答案变成**状态的函数**，于是要钉的是"四个状态各自由什么触发"：

| 判据 | 触发方式 |
|---|---|
| `Ongoing` | 刚开局 |
| `Defeat` | 血量归零 |
| `Victory` | 最后一幕 + Boss 已倒 |
| `OutOfMap` | `end_act()` |

再加两条**顺序**判据：死在地图走完之后仍然是 `Defeat`；前两幕的 `boss_beaten` **不是**通关。

## `end_act()` 的三条前提各测一次

拒绝必须**响亮**且**不改一个字节**（`RunState: PartialEq`）。三条前提分别是
"有待决问句 / 节点没结算 / 还有路可走"，任何一条漏掉都会让"幕尽"变成一个可以随时点的按钮。

## `BEAT_DESTROYED` 要**穷尽**

`rd-core::beat::BeatKind` 是闭集（1..=13）。ABI 常量表漏一个，消费者就只能把那个 kind
当成"未知"静默跳过 —— 而"静默跳过一条动画"没有任何判据会红。所以这里断言
**每一个 code 都有常量、且常量等于 code**，并且 `14` 不在闭集里（加 kind 必须同时加常量）。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'
WASM = 'kernel/rd-wasm/src/run.rs'
LIB = 'kernel/rd-wasm/src/lib.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① rd-run：run_end 四态 + end_act 三条前提 ───────────────────────────────
t = io.open(STATE, encoding='utf-8').read()

ANCHOR = '''    /// §342（第九轮 Review P1-2）：补出来的遗物按**它自己的稀有度**定价。'''

TESTS = '''    /// §344（缺口 G1）：`run_end()` 的四个值各自由什么触发。
    ///
    /// 页面前有一对**自己记的**模块级变量（`runOver` / `runOverWhy`）—— 战败时置位、幕尽时置位。
    /// 它们能对，是因为页面的每一处赋值都记得改；而"记得"不是判据。这条把答案变成**状态的函数**。
    #[test]
    fn the_run_end_is_a_function_of_the_state() {
        use crate::state::RunEnd;

        // ① 刚开局：还能打。
        let mut run = ironclad();
        assert_eq!(run.run_end(), RunEnd::Ongoing, "a fresh run is ongoing");

        // ② 血量归零 ⇒ 战败（战斗收尾把血量折回运行层，战败就是 0）。
        run.adjust_health(-9999);
        assert_eq!(run.health(), 0);
        assert_eq!(run.run_end(), RunEnd::Defeat, "zero health is a defeat");

        // ③ 前两幕的 `boss_beaten` **不是**通关：`mark_boss_beaten` 会换幕并清掉它。
        let mut act1 = ironclad();
        act1.act = 1;
        act1.boss_beaten = true;
        assert_eq!(
            act1.run_end(),
            RunEnd::Ongoing,
            "clearing act 1 is not winning the run"
        );

        // ④ 最后一幕 + Boss 已倒 ⇒ 通关。
        let mut last = ironclad();
        last.act = MAX_ACT;
        last.boss_beaten = true;
        assert_eq!(last.run_end(), RunEnd::Victory, "the last act's boss ends the run");

        // ⑤ 顺序：**死就是死** —— 即使这一幕的地图也走完了。
        let mut both = ironclad();
        both.act = MAX_ACT;
        both.boss_beaten = true;
        both.ended_out_of_map = true;
        both.adjust_health(-9999);
        assert_eq!(
            both.run_end(),
            RunEnd::Defeat,
            "defeat outranks every other end state"
        );
    }

    /// §344（缺口 G2）：`end_act()` 的三条前提，各测一次 —— 而且拒绝**一个字节都不改**。
    ///
    /// 以前"幕尽"只是页面上的一句话（`runOver = true`），于是它不是内核事实：存档不存它、
    /// 指纹不算它、回放看不见它。现在它是一个动作，所以它必须**只在真的没事可做时**接受。
    #[test]
    fn ending_an_act_requires_that_there_is_nothing_left_to_do() {
        use crate::state::RunEnd;

        // 前提 1：还有待决问句 ⇒ 拒绝。
        let mut run = ironclad();
        run.pending = Pending::Shop;
        let before = run;
        assert_eq!(run.end_act(), Err(RunError::WrongPhase));
        assert!(run == before, "a refused end_act must change nothing");
        assert_eq!(run.run_end(), RunEnd::Ongoing);

        // 前提 2：脚下的节点还没结算 ⇒ 拒绝（`NodeNotSettled`）。
        let mut run = ironclad();
        run.pending = Pending::None;
        if run.node >= 0 {
            // 站在一个没结算的节点上。
            run.resolved = [0; 2];
            let before = run;
            assert_eq!(run.end_act(), Err(RunError::NodeNotSettled));
            assert!(run == before, "a refused end_act must change nothing");
        }

        // 前提 3：还有路可走 ⇒ 拒绝（`MapNotExhausted`）。
        let mut run = ironclad();
        assert!(!run.reachable().is_empty(), "a fresh run has somewhere to go");
        run.mark_resolved();
        let before = run;
        assert_eq!(run.end_act(), Err(RunError::MapNotExhausted));
        assert!(run == before, "a refused end_act must change nothing");

        // 三条都满足 ⇒ 接受，而且**只有它**能把 `OutOfMap` 打开。
        //
        // 构造"最后一排、已结算、没有出边"：直接把游标摆到最后一排的一个节点上并标记结算。
        // 不走地图 —— 这条判据问的是 `end_act` 的守卫，不是"能不能走到最后一排"。
        let mut run = ironclad();
        let mut placed = false;
        for index in 0..run.map().node_count() {
            if let Some((row, _)) = run.map().locate(index as u8) {
                if row as usize == ROWS - 1 {
                    run.node = index as i32;
                    run.floor = ROWS as i32;
                    run.pending = Pending::None;
                    run.mark_resolved();
                    placed = true;
                    break;
                }
            }
        }
        assert!(placed, "the map must have a last row");
        assert!(run.reachable().is_empty(), "the last row has no exits");
        assert_eq!(run.end_act(), Ok(()), "nothing left to do: accept");
        assert_eq!(run.run_end(), RunEnd::OutOfMap, "and now the act is over");
        assert!(!run.removal_available() || true, "（无意义断言，占位以免误读）");
    }

'''

t = sub(t, ANCHOR, TESTS + ANCHOR, 'run_end tests')
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② rd-wasm：四个导出 + beat 常量穷尽 ────────────────────────────────────
t = io.open(WASM, encoding='utf-8').read()
ANCHOR2 = '''    /// §343：`rd_run_removal_available()` —— 四态。'''

TESTS2 = '''    /// §344：缺口 G1 / G2 / G9 的三个导出各测一次（值 + 哨兵）。
    ///
    /// 这三个导出的存在理由都是同一个：**页面不该自己算/自己记**。
    #[test]
    fn the_run_end_and_rest_heal_come_from_the_kernel() {
        crate::take_session();
        *run_slot() = None;
        assert_eq!(rd_run_over(), -1, "no run");
        assert_eq!(rd_run_over_why(), -1, "no run");
        assert_eq!(rd_run_rest_heal(), -1, "no run");

        reset(7);
        assert_eq!(rd_run_over(), 0, "a fresh run is ongoing");
        assert_eq!(rd_run_over_why(), 0, "…and the reason is `Ongoing`");

        // G9：回复量 = 30% 上限 + 遗物加成。**页面算不出来**：`eternal_feather` 按张数算。
        let hp_max = rd_run_observe(3);
        assert_eq!(
            rd_run_rest_heal(),
            hp_max * 30 / 100,
            "no rest relic: 30% of max"
        );
        assert_eq!(
            unsafe { rd_run_grant_relic(b"regal_pillow".as_ptr(), 12) },
            0,
            "grant regal_pillow: {}",
            run_error_text()
        );
        assert_eq!(
            rd_run_rest_heal(),
            hp_max * 30 / 100 + 15,
            "regal_pillow adds 15 -- a page computing 30% would show the old number"
        );

        // G2：`end_act` 在地图还有路可走时必须被拒（`-2`），而且不改状态。
        assert_eq!(
            rd_run_end_act(),
            -2,
            "there is somewhere to go: {}",
            run_error_text()
        );
        assert_eq!(rd_run_over(), 0, "a refused end_act changes nothing");
    }

    /// §344（缺口 G11）：**每个 `BeatKind` 都有 ABI 常量，且常量等于它的码**。
    ///
    /// 这个常量表以前缺 13（`Destroyed`）：`rd-core` 会发它，ABI 只认到 12，于是任何消费者
    /// 只能把 13 当成"未知"静默跳过 —— 而"静默跳过一条动画"没有任何判据会红。
    ///
    /// 判据是**穷尽**的：1..=13 逐个有常量、常量等于码，14 不在闭集里。加一种 beat 却忘了
    /// 加常量，这条就会红（`FACT.md` §4.20：同一个词表被两处认识就一定漂）。
    #[test]
    fn every_beat_kind_has_an_abi_constant() {
        let table: [(i32, &str); 13] = [
            (crate::BEAT_DAMAGE, "Damage"),
            (crate::BEAT_BLOCK, "Block"),
            (crate::BEAT_HEAL, "Heal"),
            (crate::BEAT_STATUS_CHANGED, "StatusChanged"),
            (crate::BEAT_STATUS_REMOVED, "StatusRemoved"),
            (crate::BEAT_STATUS_PREVENTED, "StatusPrevented"),
            (crate::BEAT_DOWNED, "Downed"),
            (crate::BEAT_ESCAPED, "Escaped"),
            (crate::BEAT_CARD_PLAYED, "CardPlayed"),
            (crate::BEAT_TURN_STARTED, "TurnStarted"),
            (crate::BEAT_TURN_ENDED, "TurnEnded"),
            (crate::BEAT_SUMMONED, "Summoned"),
            (crate::BEAT_DESTROYED, "Destroyed"),
        ];
        for (index, (code, name)) in table.iter().enumerate() {
            assert_eq!(
                *code,
                index as i32 + 1,
                "{name}: the ABI value must be its position (1-based) -- the numbers are frozen"
            );
            assert!(
                rd_core::beat::BeatKind::from_code(*code).is_some(),
                "{name}: the core does not know code {code} -- the constant names nothing"
            );
        }
        // 闭集的另一侧：14 不存在。加一种 beat 就得同时加常量，否则上面那条 `from_code`
        // 仍会绿，而消费者会静默跳过。
        assert!(
            rd_core::beat::BeatKind::from_code(14).is_none(),
            "a 14th beat kind appeared -- add its ABI constant and this table together"
        );
    }

    /// §343：`rd_run_removal_available()` —— 四态。'''

t = sub(t, ANCHOR2, TESTS2, 'wasm tests')
io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t)
print('§344 tests: run_end/end_act (rd-run) + exports & beat table (rd-wasm)')
