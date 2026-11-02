"""P1-1 (3), take 2: splice by markers instead of matching a long block.

The previous attempt failed because a line-continuation backslash in an earlier patch became a single
long line, so the anchor text no longer matched. Splicing between two unique markers is immune to that
kind of whitespace drift -- and when it is not, the assert tells me so instead of silently doing
nothing.
"""
import io

PATH = "kernel/rd-run/src/hash.rs"

START = "        let deck: std::vec::Vec<&str> ="
END = '        assert!(len > MAX_TEXT / 2, "only {len} B: this is not a maximal state");\n'

BODY = '''        // 两个口径，分开量、分开断言 —— 这正是评审要求的"不要把两者混用"。
        let padded_card = "z".repeat(rd_core::state::ID_CAP);
        let padded_potion = "z".repeat(rd_core::state::ID_CAP);
        let reachable = measure(&build(&relics, longest_card, longest_potion));
        let represented = measure(&build(&relics, &padded_card, &padded_potion));

        println!(
            "reachable (ids from the image): {reachable} B of {MAX_TEXT} B · \\
             representable (deck/potions padded to ID_CAP): {represented} B"
        );
        for (label, len) in [("reachable", reachable), ("representable", represented)] {
            assert!(
                len * 2 < MAX_TEXT,
                "the {label} maximum uses {len} of {MAX_TEXT} B: under 2x headroom"
            );
        }
        // 这两条是"测试真的在量大局面"的判据 —— 第一版把它标定在坏夹具的数字上（> 4096），
        // 那是拿错答案校准的尺子。现在它只说"比 `run()` 那副 10 张牌大得多"。
        assert!(reachable > 2_000, "only {reachable} B: this is not the large state");
        assert!(
            represented > reachable,
            "padding the ids to ID_CAP must make the text longer ({represented} vs {reachable})"
        );
'''

HELPER_ANCHOR = """    /// 内容镜像：与 `rd-wasm` 嵌入的是同一份"""

HELPERS = '''    /// 一局"尽可能满"的局面：满牌组、镜像里**每一件**遗物、药水塞到槽满。
    ///
    /// Ascension 0 on purpose: A11 takes a slot away and the belt only gives two back —— 上界要的是
    /// **尽可能多**的槽，不是"最难的等级"。每一次 push 都 `expect`：静默拒绝会**让测试红**，
    /// 而不是让夹具悄悄变小（这正是上一版出错的形状）。
    fn build(relics: &[&str], card: &str, potion: &str) -> RunState {
        let deck: std::vec::Vec<&str> = std::vec![card; crate::state::MAX_RUN_DECK];
        let mut state =
            RunState::new_with_ascension(7, 80, i32::MAX, &deck, 0).expect("a maximal run");
        for relic in relics {
            state
                .push_relic(relic)
                .unwrap_or_else(|error| panic!("pushing relic {relic} must work: {error:?}"));
        }
        let slots = usize::from(state.potion_slots());
        for slot in 0..slots {
            state
                .push_potion(potion)
                .unwrap_or_else(|error| panic!("pushing potion {slot} must work: {error:?}"));
        }
        // 夹具就是它自称的那个 —— 这三条是这次修复的核心。
        assert_eq!(state.deck().len(), crate::state::MAX_RUN_DECK, "the deck is not full");
        assert_eq!(state.relics().len(), relics.len(), "a relic push was refused");
        assert_eq!(state.potions().len(), slots, "a potion push was refused");
        state
    }

    /// 规范文本的长度（顺带断言没溢出）。
    fn measure(state: &RunState) -> usize {
        let mut buffer = [0u8; MAX_TEXT];
        let mut writer = TextWriter::new(&mut buffer);
        write_run_input(&mut writer, state);
        assert!(!writer.overflowed(), "the text did not fit {MAX_TEXT} B");
        writer.as_str().len()
    }

''' + HELPER_ANCHOR


def main():
    text = io.open(PATH, encoding="utf-8").read()
    start = text.index(START)
    end = text.index(END) + len(END)
    text = text[:start] + BODY + text[end:]
    assert text.count(HELPER_ANCHOR) == 1, text.count(HELPER_ANCHOR)
    text = text.replace(HELPER_ANCHOR, HELPERS)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("two grades spliced in")


if __name__ == "__main__":
    main()
