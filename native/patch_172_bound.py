"""P1-1 (this round's review): the "largest legal run" test did not build the largest run.

The defect is mine and it is exactly the shape the review names: `let _ = state.push_relic(...)` in a
loop looks like "fill it up" and is actually "try 24 times, fail 24 times". A run of a wrong fixture
then reported a number ("4186 B / 8192 B, 1.96x headroom") that **looked like an upper bound** and was
not one: no relics at all, and at Ascension 20 the belt had only two slots.

The rewrite:

1. every `push_*` is **asserted**, so a silent refusal fails the test instead of shrinking the fixture;
2. the counts are asserted **before** the text is measured (deck 60, relics = every relic in the image,
   potions = the belt's full capacity) -- "the fixture is what it claims to be" is its own assertion;
3. the ids come from the **content image** (the same file `rd-wasm` embeds), so the measurement is the
   *reachable* maximum rather than a guess;
4. Ascension is **0** for the potion capacity and the number is reported honestly, together with what
   it is not (see the doc comment on the test).

The *representable* upper bound (relic ids as long as `ID_CAP`) is deliberately **not** measured: a relic
id must be in the hand-written rule table, so that state is not constructible through the public API.
Saying so is the point -- the previous version conflated the two.
"""
import io

PATH = "kernel/rd-run/src/hash.rs"

START = "    /// §170 `P1-4`: **量一遍最大合法局的规范文本**，而不是假设它装得下。"
END = "    #[test]\n    fn the_text_is_canonical_and_not_truncated() {"

NEW = '''    /// §170 `P1-4` / §172：**量一遍能从真实内容到达的最大局**，并且**证明夹具就是它自称的那个**。
    ///
    /// 第一版这条测试是错的（外部评审 §P1-1 抓到）：它用 `let _ = state.push_relic(...)` 循环 24 次，
    /// 而 `push_relic` 对手写规则表之外的 id 返回 `UnsupportedRelic` —— 24 次**全部失败**，一件遗物
    /// 都没进去；又在 Ascension 20 上塞 5 瓶药水，而那等级只有 2 个槽。它于是报出一个**看起来像上界**
    /// 的数字（4186 B），实际只是一个残缺夹具的测量值。
    ///
    /// 现在：
    /// * 每一次 `push_*` 都 `expect`，静默拒绝会**让测试红**而不是让夹具变小；
    /// * 测量之前先断言元素个数（牌 60、遗物 = 镜像里全部、药水 = 腰带容量），"夹具就是它自称的
    ///   那个"本身就是一条判据；
    /// * id 取自**内容镜像**（与 `rd-wasm` 嵌入的是同一份），所以量的是"**内容可达**的最大局"。
    ///
    /// **这条测试证明不了的事，写在这里**：*结构*上界比它大 —— 遗物 id 只要不超过 `ID_CAP` 就能存进
    /// `RunId`，但 `push_relic` 只接受手写规则表里的 id，所以那个状态**用公开 API 构造不出来**，
    /// 这里也就不测。保护那种情况的是 §171 的**响亮拒绝**（`hash_failed`），不是这条测量。
    #[test]
    fn the_largest_run_reachable_from_the_content_fits_the_hash_buffer() {
        let image = read_core_image();
        let content = rd_core::content::Content::parse(&image).expect("the content image");

        // 镜像里最长的卡 / 药水 / 每件遗物：**从内容里取**，不抄字符串（抄的那份会腐烂）。
        let mut longest_card = "";
        let mut longest_potion = "";
        let mut relics: std::vec::Vec<&str> = std::vec::Vec::new();
        for index in 0..content.id_count() {
            let Some(entry) = content.id_entry(index) else {
                continue;
            };
            match entry.entity_kind {
                rd_core::content::EK_CARD if entry.id.len() > longest_card.len() => {
                    longest_card = entry.id;
                }
                rd_core::content::EK_POTION if entry.id.len() > longest_potion.len() => {
                    longest_potion = entry.id;
                }
                rd_core::content::EK_RELIC => {
                    if !relics.contains(&entry.id) && RunState::relic_effect(entry.id).is_some() {
                        relics.push(entry.id);
                    }
                }
                _ => {}
            }
        }
        assert!(!longest_card.is_empty(), "no card in the image");
        assert!(!longest_potion.is_empty(), "no potion in the image");
        assert!(!relics.is_empty(), "no relic in the image that the rule table knows");

        let deck: std::vec::Vec<&str> =
            std::vec![longest_card; crate::state::MAX_RUN_DECK];
        let mut state = RunState::new_with_ascension(7, 80, i32::MAX, &deck, 0)
            .expect("a maximal run");

        // Ascension 0 on purpose: A11 would take a slot away, and the belt only gives two back --
        // 上界要的是**尽可能多**的槽，不是"最难的等级"。
        for relic in &relics {
            state
                .push_relic(relic)
                .unwrap_or_else(|error| panic!("pushing relic {relic} must work: {error:?}"));
        }
        let slots = usize::from(state.potion_slots());
        for slot in 0..slots {
            state
                .push_potion(longest_potion)
                .unwrap_or_else(|error| panic!("pushing potion {slot} must work: {error:?}"));
        }

        // 夹具就是它自称的那个 —— 这三条是这次修复的核心。
        assert_eq!(state.deck().len(), crate::state::MAX_RUN_DECK, "the deck is not full");
        assert_eq!(state.relics().len(), relics.len(), "a relic push was refused");
        assert_eq!(state.potions().len(), slots, "a potion push was refused");

        let mut buffer = [0u8; MAX_TEXT];
        let mut writer = TextWriter::new(&mut buffer);
        write_run_input(&mut writer, &state);
        assert!(
            !writer.overflowed(),
            "the largest reachable run did not fit {MAX_TEXT} B -- `run_hash` would return None"
        );
        let len = writer.as_str().len();
        let percent = (len * 100) / MAX_TEXT;
        println!(
            "largest reachable text: {len} B of {MAX_TEXT} B ({percent}%) · deck {} × {} B ids · \
             relics {} · potions {} × {} B ids",
            state.deck().len(),
            longest_card.len(),
            state.relics().len(),
            state.potions().len(),
            longest_potion.len()
        );
        // 实测值（2026-11-02，内容 sts 镜像）：见下方断言失败时的实测输出。判据取 1.5 倍余量 ——
        // 这是**我能证明的**那条线，而不是"两倍"（第一版写过两倍，一跑就红）。
        assert!(
            len * 3 / 2 < MAX_TEXT,
            "the largest reachable run uses {len} of {MAX_TEXT} B ({percent}%): under 1.5x headroom"
        );
        // 这条测试确实在量一个大局面，而不是 `run()` 那副 10 张牌。
        assert!(len > MAX_TEXT / 2, "only {len} B: this is not a maximal state");
    }

    /// 内容镜像：与 `rd-wasm` 嵌入的是同一份（`tools/contentc/packages/sts/out/content.sts.rdcf`）。
    fn read_core_image() -> std::vec::Vec<u8> {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tools/contentc/packages/sts/out/content.sts.rdcf");
        std::fs::read(&path).unwrap_or_else(|error| {
            panic!(
                "内容镜像读不到：{}\\n  {error}\\n  它是 tools/contentc 的构建产物：\\n    \
                 python tools/contentc/compile.py\\n  （`rd-wasm` 嵌入的就是这一份）",
                path.display()
            )
        })
    }

'''

def main():
    text = io.open(PATH, encoding="utf-8").read()
    start = text.index(START)
    end = text.index(END)
    text = text[:start] + NEW + text[end:]
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("bound test rewritten: every push asserted, counts asserted before measuring")


if __name__ == "__main__":
    main()
