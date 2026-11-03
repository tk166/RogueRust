"""§188 part 3: the effect-list reader, with the lifetimes and diagnostics right.

Two things went wrong the first time and are fixed here:

1. the `Result`s from `NodeRef::str_field` cannot be `?`-ed in an `Option` function -- a wrong *type*
   in that element is a broken image, not "this element has no effect", so it collapses to `None`;
2. `fn effect_list(&self, ..) -> Option<..>` inside `impl<'a> Content<'a>` builds `EffectSpec<'a>`
   from `&self`, which the borrow checker refuses: the specs must borrow for `'a`, so the receiver
   has to be `&'a self`.
"""
import io

PATH = "kernel/rd-core/src/content.rs"

OLD = '''    fn effect_list(
        &self,
        cell: u16,
        out: &mut [EffectSpec<'a>; MAX_EVENT_EFFECTS],
    ) -> Option<u8> {'''

NEW = '''    fn effect_list(
        &'a self,
        cell: u16,
        out: &mut [EffectSpec<'a>; MAX_EVENT_EFFECTS],
    ) -> Option<u8> {'''

# the two `?`s that do not apply, spelled out
OLD_BODY = '''            let effect = node.str_field("Effect")?.unwrap_or("nothing");
            let amount = node.int_field("Amount")?.unwrap_or(0);'''

NEW_BODY = '''            // 这里返回 Option（与 `Content::event` 的其他读取一致），所以 `Result` 要展开成
            // “读不出来就是 None”：**类型不对的内容**是坏镜像，不是“这个元素没有效果”。
            let effect = node.str_field("Effect").ok().flatten().unwrap_or("nothing");
            let amount = node.int_field("Amount").ok().flatten().unwrap_or(0);'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in ((OLD, NEW), (OLD_BODY, NEW_BODY)):
        if new in text:
            print("already applied")
            continue
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("reader fixed")


if __name__ == "__main__":
    main()
