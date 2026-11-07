"""§280 判据（wasm）：`RequiresAsc` 两侧 —— 同一屏在 A0 与 A15 上可用性不同。

判据必须**两侧**：只测一档的话，"条件永远是 `Requires`"（忽略 A15）与"永远是 `RequiresAsc`"
都长得像对的。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'

ANCHOR = '''    /// The hand's definition ids, in pile order (`hand_costs` has the prices).'''

TEST = r'''    /// §280：`the_cleric` 的 `Purify` 价目在 A15 是 75 —— **条件**跟着换（`RequiresAsc`）。
    ///
    /// 判据两侧：同一个 60 金币的局，A0 可选、A15 不可选。只测一档的话，
    /// "忽略 A15"与"永远用 A15"都能通过。
    #[test]
    fn the_a15_requirement_variant_gates_the_cleric_price() {
        // `rd-core` 的 A15 是 `rd-run` 的同一个数的第二份 —— 漂开会让"价目"与"条件"分家。
        assert_eq!(
            rd_core::run_expr::A15,
            rd_run::state::A_EVENTS_WORSE,
            "the two A15 constants must be the same number"
        );
        for (level, want_available) in [(0u8, true), (14, true), (15, false), (20, false)] {
            reset(7);
            let session = run_slot().as_mut().expect("a run");
            // 60 金币：付得起 50（A0），付不起 75（A15）。
            session.state.adjust_gold(60 - session.state.gold());
            session
                .state
                .set_ascension(level)
                .expect("a legal ascension");
            assert!(
                session
                    .state
                    .begin_event("the_cleric", "the_cleric")
                    .is_ok()
            );
            assert_eq!(rd_run_observe(4), 60, "the purse is 60");
            // 槽 0 = Heal（35 金币，两档都一样）。
            assert_eq!(
                rd_run_event_option_available(0),
                1,
                "A{level}: 35 gold is affordable, so Heal is offered"
            );
            // 槽 1 = Purify（50 / A15 75）。
            assert_eq!(
                rd_run_event_option_available(1),
                i32::from(want_available),
                "A{level}: Purify needs {} gold",
                if level >= 15 { 75 } else { 50 }
            );
        }
        // 再验一次"付得起"的那一侧：A15 + 80 金币 ⇒ 可选。
        reset(7);
        let session = run_slot().as_mut().expect("a run");
        session.state.adjust_gold(80 - session.state.gold());
        session.state.set_ascension(15).expect("a legal ascension");
        assert!(session.state.begin_event("the_cleric", "the_cleric").is_ok());
        assert_eq!(
            rd_run_event_option_available(1),
            1,
            "A15 with 80 gold: the 75 gold Purify is offered"
        );
    }

'''

def main():
    s = io.open(P, encoding='utf-8').read()
    assert s.count(ANCHOR) == 1
    assert 'the_a15_requirement_variant_gates_the_cleric_price' not in s
    s = s.replace(ANCHOR, TEST + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('§280 wasm test appended')


main()
