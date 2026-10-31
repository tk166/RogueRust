"""Add the lib.rs-local `refuse_with_text` helper and point the choice exports at it.

`run.rs` has a private `refuse` that writes to the **run** slot; the choice exports report through
the **fight** slot, so they need their own one-liner rather than a cross-module call.
"""
import io

PATH = "kernel/rd-wasm/src/lib.rs"

HELPER = """/// Report a refusal through the **fight** session's error buffer and return `-2`.
///
/// `run.rs` has an almost-identically-named `refuse`, which writes to the *run* slot instead: the
/// two slots are separate error surfaces on purpose (a fight can refuse while the run is fine), and
/// one helper for two sinks would put the message where the page does not look.
fn refuse_with_text(message: &str) -> i32 {
    if let Some(session) = slot().as_mut() {
        session.error = message.to_string();
    }
    -2
}

"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert "fn refuse_with_text" not in text, "already inserted"

    anchor = """/// Is the kernel waiting for a card choice? `1` yes, `0` no, `-1` no session."""
    assert text.count(anchor) == 1
    text = text.replace(anchor, HELPER + anchor)

    # the four call sites inside the choice exports
    for message in (
        'return refuse("待决选牌的战斗员没有牌区");',
        'return refuse("牌的槽位表与卡池不一致：选牌清单不完整");',
        'return refuse(&std::format!("选项 {index} 不存在"));',
        'Err(e) => refuse(&std::format!("选牌被拒：{e}")),',
    ):
        assert text.count(message) == 1, (text.count(message), message)
        text = text.replace(message, message.replace("refuse(", "refuse_with_text("))

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("refuse_with_text wired")


if __name__ == "__main__":
    main()
