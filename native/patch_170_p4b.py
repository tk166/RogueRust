"""P1-4 (a): measure the bound nobody had measured -- without inventing APIs.

`run_hash` returns `None` when the canonical text exceeds `MAX_TEXT` (8192 B). Whether a **legal**
state can reach that was never checked: the existing "not truncated" test uses `run()`'s ten-card
deck. So "can a real run overflow and silently hash to 0?" had no answer, and the review was right to
call that out.

`rd-run`'s tests cannot read the content image (that fixture belongs to `rd-core`), so this measures
the **type's** limit rather than today's content: every deck slot holds an id of `ID_CAP` bytes, relics
and potions are filled with ids of the same length, gold is at `i32::MAX`, ascension is 20. Whatever
the content does next, the text cannot be longer than this -- which is the claim worth pinning.
"""
import io

PATH = "kernel/rd-run/src/hash.rs"

ANCHOR = """    #[test]
    fn the_text_is_canonical_and_not_truncated() {"""

TEST = '''    /// §170 `P1-4`: **量一遍最大合法局的规范文本**，而不是假设它装得下。
    ///
    /// 之前只有 `the_text_is_canonical_and_not_truncated`，用的是 `run()` 的 10 张牌 —— 那证明不了
    /// "一局真实的后盘会不会撑爆 8 KiB"。这里量的是**类型的上限**：每个牌位都放 `ID_CAP` 长的 id，
    /// 遗物/药水拉满、金币 `i32::MAX`、Ascension 20。内容以后怎么改都超不过这个数。
    ///
    /// 判据是**两倍余量**：余量本身就是"内容把 id 长度翻倍也还装得下"这句话。
    #[test]
    fn the_largest_legal_run_fits_the_hash_buffer_with_two_times_the_room() {
        let widest_card = "z".repeat(rd_core::state::ID_CAP);
        let widest_relic = "z".repeat(rd_core::state::ID_CAP);
        let widest_potion = "z".repeat(rd_core::state::ID_CAP);
        let deck: Vec<&str> = std::vec![widest_card.as_str(); crate::state::MAX_RUN_DECK];
        let state = big_run(&deck, &widest_relic, &widest_potion);

        let mut buffer = [0u8; MAX_TEXT];
        let mut writer = TextWriter::new(&mut buffer);
        write_run_input(&mut writer, &state);
        assert!(
            !writer.overflowed(),
            "the largest legal run did not fit {MAX_TEXT} B -- `run_hash` would return None"
        );
        let len = writer.as_str().len();
        println!("largest legal canonical text: {len} B of {MAX_TEXT} B");
        assert!(
            len * 2 < MAX_TEXT,
            "the largest legal run uses {len} of {MAX_TEXT} B: less than 2x headroom, so a slightly \
             longer id or a new field would push a real run past the hash buffer"
        );
    }

    /// 一局"尽可能大"的合法局面：满牌组、满遗物、满药水、金币拉满、Ascension 20。
    ///
    /// 商店/奖励屏在这个状态里是空的（它们由进入节点时生成，单测够不到），所以这个数字是**下界**；
    /// 两倍余量的判据就是替它们、以及替后续内容留的。
    fn big_run(deck: &[&str], relic: &str, potion: &str) -> RunState {
        let mut state = RunState::new_with_ascension(
            i32::MAX - 1,
            999,
            i32::MAX,
            deck,
            crate::state::MAX_ASCENSION,
        )
        .expect("a maximal run");
        state.adjust_gold(i32::MAX);
        for _ in 0..crate::state::MAX_RUN_RELICS {
            let _ = state.push_relic(relic);
        }
        for _ in 0..crate::state::MAX_RUN_POTIONS {
            let _ = state.push_potion(potion);
        }
        state
    }

    #[test]
    fn the_text_is_canonical_and_not_truncated() {'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn the_largest_legal_run_fits" not in text, "already inserted"
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, TEST))
    print("bound measurement added (type limit)")


if __name__ == "__main__":
    main()
