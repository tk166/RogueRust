"""§188 part 4: repair the comment the shell mangled + make the receiver `&'a self`."""
import io

PATH = "kernel/rd-core/src/content.rs"

MANGLED = '''            // 这里返回 （与  的其他读取一致），所以  要展开成
            // "读不出就 "。类型对不上在这里是**内容坏了**，不是"这个元素没有效果"。'''

FIXED = '''            // 这里返回 Option（与 `Content::event` 的其他读取一致），所以 `Result` 要展开成
            // `None`：**类型不对**说明镜像坏了，不是"这个元素没有效果"。'''

OLD_SIG = '''    fn effect_list(
        &self,
        cell: u16,'''

NEW_SIG = '''    fn effect_list(
        &'a self,
        cell: u16,'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    if MANGLED in text:
        text = text.replace(MANGLED, FIXED)
        print("comment repaired")
    if NEW_SIG not in text:
        assert text.count(OLD_SIG) == 1
        text = text.replace(OLD_SIG, NEW_SIG)
        print("receiver is now &'a self")
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)


if __name__ == "__main__":
    main()
