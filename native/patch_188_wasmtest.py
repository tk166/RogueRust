"""§188 test: A15 swaps the list the ABI reports, and the *reason* is the run's ascension.

The judgment is the ABI the page reads, not a field: at A14 the Golden Idol's first option is
`[relic, curse]` (2 effects), at A15 it is `[relic, damage]` (2 effects) -- **the same count**, so a
test that only counted would pass with the wrong list. The codes are compared instead
(`9` = curse, `3` = damage), which is exactly what the page renders.
"""
import io

RUN = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// The hand's definition ids, in pile order (`hand_costs` has the prices)."""

NEW = r'''    /// §188: A15 ("Unfavorable Events") reaches the ABI -- a different list, not a different count.
    ///
    /// The event chosen here is `golden_idol`, the one real StS event in this content: base is
    /// **relic + Injury curse**, A15 is **relic + 25% max HP damage** (`wiki_slavers`-style branch,
    /// recorded in `docs/spec/sts-act1-inventory.md` §7).
    #[test]
    fn a15_swaps_the_event_effect_list() {
        const CURSE_CODE: i32 = 9;
        const DAMAGE_CODE: i32 = 3;
        for (level, want_second) in [(0i32, CURSE_CODE), (14, CURSE_CODE), (15, DAMAGE_CODE), (20, DAMAGE_CODE)] {
            assert_eq!(rd_run_start(7, level), 0, "start at A{level}");
            assert_eq!(rd_run_choose_start(0), 0, "take blessing 0");
            while rd_run_pending() == 7 {
                assert_eq!(rd_run_pick_blessing_card(0), 0, "the blessing owes a pick");
            }
            // Walk to the first `?` room on the map and open it. The map is seeded, so this is the
            // same node every time; a seed whose first row has no `?` would make the test vacuous,
            // so the count is asserted below.
            let mut opened = false;
            for node in 0..rd_run_node_count() {
                if rd_run_node_kind_of(node) != 6 {
                    continue;
                }
                if rd_run_step(node) != 0 {
                    continue;
                }
                if rd_run_pending() != 5 {
                    continue;
                }
                opened = true;
                break;
            }
            assert!(opened, "A{level}: the run has no openable event");
            assert_eq!(
                rd_run_event_effect_count(0),
                2,
                "A{level}: the first option has two effects"
            );
            assert_eq!(rd_run_event_effect_at(0, 0), 10, "the relic is first, at every level");
            assert_eq!(
                rd_run_event_effect_at(0, 1),
                want_second,
                "A{level}: the second effect must be {want_second}"
            );
            // The legacy single-effect accessors must agree with index 0.
            assert_eq!(rd_run_event_effect(0), rd_run_event_effect_at(0, 0));
        }
    }

    /// The hand's definition ids, in pile order (`hand_costs` has the prices).'''


def main():
    text = io.open(RUN, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    io.open(RUN, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, NEW))
    print("rd-wasm A15 test inserted")


if __name__ == "__main__":
    main()
