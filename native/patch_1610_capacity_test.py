"""§161.10: the capacity contract, tested at the edge that used to break.

`rd_run_archive_fill()` writes into the archive's own buffer; the page reads (capacity, len) from the
ABI. This pins: a normal run fits, a **60-card** run (1628 B, i.e. past the old 1 KiB scratch) also
fits and says so, and a restore longer than the capacity is refused *before* touching anything.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"

ANCHOR = """    /// §161.5: Attack Potion -- three **definitions**, one card created, and it is free."""

TEST = '''    /// §161.10 P0: 存档走**自己的**缓冲区，容量由 ABI 公布。
    ///
    /// 旧的 `rd_run_archive_into(ptr)` 接收任意指针，而页面给的是 1024 B 的通用 scratch —— 一个
    /// 60 张牌的存档是 **1628 B**（`a_full_deck_archive_is_bigger_than_the_generic_scratch`），
    /// 于是它往 `SCRATCH` 后面写了约 600 B。这条测试把"能装下"变成可观察的：容量、长度、
    /// 以及超长输入被拒。
    #[test]
    fn the_archive_buffer_is_sized_for_a_full_deck_and_refuses_more() {
        test_run(7, 80, 80, &["strike"; 10]);
        let capacity = crate::rd_run_archive_capacity();
        assert!(
            capacity as usize >= rd_run::state::archive::MAX_ARCHIVE,
            "the published capacity must be the real one"
        );

        // A normal run.
        let len = crate::rd_run_archive_fill();
        assert!(len > 0, "archive_fill said {len}");
        assert!(len <= capacity, "archive {len} does not fit {capacity}");

        // A **full deck**: the case that overflowed the old scratch (1024 B).
        {
            let session = run_slot().as_mut().expect("a run");
            while !session.state.deck().len() >= 1 && false {
                break;
            }
            for _ in 0..rd_run::state::MAX_RUN_DECK.saturating_sub(session.state.deck().len()) {
                let _ = session.state.push_card("strike");
            }
        }
        let big = crate::rd_run_archive_fill();
        assert!(big > 0, "a full-deck archive said {big}");
        assert!(
            big > 1024,
            "a full-deck archive measured {big} bytes; if it fits in 1 KiB the old bug would have \
             been masked by luck, which is not a contract"
        );
        assert!(
            big <= capacity,
            "a full-deck archive is {big} bytes but the buffer is {capacity}"
        );

        // Reading it back works at that size.
        let ptr = crate::rd_run_archive_buf();
        assert!(!ptr.is_null());
        let bytes = unsafe { std::slice::from_raw_parts(ptr, big as usize) }.to_vec();
        assert_eq!(crate::rd_run_restore_from(ptr, big), 0, "restore of a big archive");

        // …and **one byte past the capacity** is refused, not clamped.
        let over = capacity + 1;
        let mut padded = bytes.clone();
        padded.resize(over as usize, b'A');
        assert_eq!(
            crate::rd_run_restore_from(padded.as_ptr(), over),
            -3,
            "an input longer than the buffer must be refused before anything is read"
        );
    }

    /// §161.5: Attack Potion -- three **definitions**, one card created, and it is free.'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "the_archive_buffer_is_sized_for_a_full_deck" not in text, "already inserted"
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, TEST))
    print("capacity test added")


if __name__ == "__main__":
    main()
