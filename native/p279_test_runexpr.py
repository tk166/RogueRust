"""§279：`run_expr` 的逐条判据。

每条都钉一个**没有症状**的错误形态：条件"永远成立"与"永远不成立"在屏幕上都是正常画面，
只有行为不对。所以判据必须是**两侧**（成立 / 不成立各一次），而不是"求值没报错"。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/run_expr.rs'

TESTS = r'''
#[cfg(test)]
mod tests {
    use super::*;
    use crate::content::Content;

    const IMAGE: &str = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
    );

    fn image() -> std::vec::Vec<u8> {
        std::fs::read(IMAGE).expect("the sts image")
    }

    /// `forgotten_altar` 的第一个选项 —— 唯一一条**真的在镜像里**的条件。
    fn conditional_option(content: &Content<'_>) -> u16 {
        let index = (0..content.event_count())
            .find(|index| content.event(*index).map(|event| event.0) == Some("forgotten_altar"))
            .expect("forgotten_altar in the image");
        let (_, _, entry) = content.event(index).expect("the row");
        let step = content.event_step(entry).expect("its first step");
        step.options()[0].term
    }

    fn facts<'a>(relics: &'a [&'a str], deck: &'a [&'a str]) -> RunFacts<'a> {
        RunFacts {
            gold: 0,
            health: 80,
            health_max: 80,
            ascension: 0,
            relics,
            deck,
        }
    }

    /// 镜像里的那条 `Requires`（`relic has golden_idol`）**两侧**都要对。
    #[test]
    fn the_image_carries_a_real_requirement() {
        let bytes = image();
        let content = Content::parse(&bytes).expect("parses");
        let option = conditional_option(&content);
        let with = facts(&["golden_idol"], &["strike"]);
        let without = facts(&[], &["strike"]);
        assert_eq!(option_is_available(&content, option, &with), Ok(true));
        assert_eq!(option_is_available(&content, option, &without), Ok(false));
    }

    /// 没有 `Requires` 的选项**永远可选** —— 这是"缺席 ≠ 不成立"的判据。
    ///
    /// 反过来写（缺席 ⇒ `MissingKind` 错误）会让每一条普通选项都要写 `"Requires": []`，
    /// 而"忘了写"就会变成一个**永远不出现**的按钮：屏幕正常、玩家少一条路。
    #[test]
    fn an_option_without_requires_is_always_available() {
        let bytes = image();
        let content = Content::parse(&bytes).expect("parses");
        let index = (0..content.event_count())
            .find(|index| content.event(*index).map(|event| event.0) == Some("golden_idol"))
            .expect("golden_idol");
        let (_, _, entry) = content.event(index).expect("the row");
        let step = content.event_step(entry).expect("its first step");
        for option in step.options() {
            assert_eq!(
                option_is_available(&content, option.term, &facts(&[], &[])),
                Ok(true),
                "`{}` has no Requires -- it must be offered unconditionally",
                option.label
            );
        }
        // 哨兵：`ABSENT16`（没有 term）也是"无条件"，不是错误。
        assert_eq!(
            option_is_available(&content, crate::content::ABSENT16, &facts(&[], &[])),
            Ok(true)
        );
    }
}
'''

def main():
    s = io.open(P, encoding='utf-8').read()
    assert 'mod tests' not in s
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s.rstrip('\n') + '\n' + TESTS)
    print('run_expr tests appended')


main()
