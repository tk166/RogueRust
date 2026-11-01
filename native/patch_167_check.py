"""§167: `rd_content_check()` — ask "can this kernel read this document?" without running anything.

`content()` panics when the image does not parse, and a panic inside an export is a wasm trap: the
page sees nothing, or sees a generic failure. This export parses the same bytes and reports the
reason as text, so the page can say *why* instead of going quietly dead.
"""
import io

RUN = "kernel/rd-wasm/src/run.rs"

ANCHOR = """/// `§166`: 本机内容的指纹（八位十六进制，读作 u32）。"""

EXPORT = '''/// §167：**这份内容这个内核读得懂吗**（`0` 是懂，`-1` 是读不懂，理由在错误文本里）。
///
/// 与 `rd_content_fingerprint` 是两个问题，故意分成两个导出：
///
/// * 指纹答的是"**是不是同一份**内容"（+/- 一张牌都算不同）；
/// * 这一个答的是"**形状**能不能读"（行 schema 版本、每张关键表的行长）。
///
/// 页面在启动时问一次，于是"内容读不懂"是页面上的一句话，而不是第一次点按钮时的
/// wasm trap —— `content()` 里那条 `panic!` 在浏览器里看不出任何原因。
#[no_mangle]
pub extern "C" fn rd_content_check() -> i32 {
    match Content::parse(IMAGE) {
        Ok(_) => 0,
        Err(error) => {
            set_error(&std::format!("内容读不懂：{}", detail(&error)));
            -1
        }
    }
}

/// `§166`: 本机内容的指纹（八位十六进制，读作 u32）。'''


def main():
    text = io.open(RUN, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1
    assert "fn rd_content_check" not in text
    io.open(RUN, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, EXPORT))
    print("rd_content_check added")


if __name__ == "__main__":
    main()
