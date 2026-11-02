"""Set the margin to what is true: 1.5x, with the measured percentages printed.

Measured (content `sts` image, 2026-11-02):

    reachable      (every id from the image)                 2815 B of 8192 B (34%)
    representable  (deck + potions padded to ID_CAP)         4495 B of 8192 B (55%)

So 2x headroom is **false** (4495 x 2 > 8192; the real ratio is 1.82x). Writing "2x" would be trading a
true number for a nicer-sounding one, which is the habit §169 and §171 were both about.
"""
import io

PATH = "kernel/rd-run/src/hash.rs"

START = "        // 两个口径，分开量、分开断言"
END = '        assert!(reachable > 2_000, "only {reachable} B: this is not the large state");'

BODY = '''        // 两个口径，分开量、分开断言 —— 这正是评审要求的"不要把两者混用"。
        let padded_card = "z".repeat(rd_core::state::ID_CAP);
        let padded_potion = "z".repeat(rd_core::state::ID_CAP);
        let reachable = measure(&build(&relics, longest_card, longest_potion));
        let represented = measure(&build(&relics, &padded_card, &padded_potion));

        // 实测（2026-11-02，内容 sts 镜像）：reachable 2815 B（34%），representable 4495 B（55%）。
        // ⇒ **两倍余量不成立**（4495 × 2 > 8192），真实余量 1.82 倍，所以判据取 1.5 倍。
        // 把这条线写成"两倍"就是拿一个更好听的数字换掉一个真的数字。
        println!(
            "reachable (ids from the image): {reachable} B of {MAX_TEXT} B · \\
             representable (deck/potions padded to ID_CAP): {represented} B"
        );
        for (label, len) in [("reachable", reachable), ("representable", represented)] {
            let percent = (len * 100) / MAX_TEXT;
            assert!(
                len * 3 / 2 < MAX_TEXT,
                "the {label} maximum uses {len} of {MAX_TEXT} B ({percent}%): under 1.5x headroom"
            );
        }
        // 这两条是"测试真的在量大局面"的判据 —— 第一版把它标定在坏夹具的数字上（> 4096），
        // 那是拿错答案校准的尺子。现在它只说"比 `run()` 那副 10 张牌大得多"。
'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    start = text.index(START)
    end = text.index(END)
    text = text[:start] + BODY + text[end:]
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("margin = 1.5x, percentages printed")


if __name__ == "__main__":
    main()
