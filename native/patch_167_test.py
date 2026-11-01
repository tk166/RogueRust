"""§167: the two new refusals, each falsifiable on its own.

The second one is the point of the whole section: the compiler only bumps `SchemaVersion` if somebody
remembers, so the kernel must *also* check the shape it can see. That test patches only the directory
(the row count) and leaves the declared schema version correct -- if the check were "trust the
version number", this document would be accepted and read as 62 cards instead of 63.
"""
import io

PATH = "kernel/rd-core/src/content.rs"

ANCHOR = """    #[test]
    fn a_synthetic_minimal_image_parses() {"""

TEST = '''    /// §167：文档声明的**行 schema 版本**不是本内核认识的那一个 ⇒ 在 `parse` 就拒。
    #[test]
    fn a_schema_version_this_kernel_does_not_know_is_refused() {
        let original = read_image(IMAGE);

        let mut blob = original.clone();
        patch16(&mut blob, HDR_SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSION + 1);
        assert_eq!(
            Content::parse(&blob).err(),
            Some(ContentError::UnsupportedSchema {
                found: SUPPORTED_SCHEMA_VERSION + 1,
                supported: SUPPORTED_SCHEMA_VERSION,
            })
        );

        // 而**支持的那个**版本必须照常通过 —— 否则上面那条可以被"永远拒绝"满足。
        assert!(Content::parse(&original).is_ok());
    }

    /// §167：关键表的字节数不是"已知行长"的整数倍 ⇒ 拒，**即使版本号一个字都没改**。
    ///
    /// 这一条是本节真正的判据：版本号要靠人记得改，行宽是**读得出来的**事实。
    /// 不改它的话，`Content::rows` 的 `min(count, bytes / stride)` 会把这个文档读成 62 张牌
    /// （而不是 63 张），一句提示都没有。
    #[test]
    fn a_key_table_with_the_wrong_row_count_is_refused_without_a_version_bump() {
        let original = read_image(IMAGE);
        // 真实镜像：CARD = 36 行 × 32 B = 1,152 B。
        let mut blob = original.clone();
        patch32(&mut blob, dir_base(S_CARD) + 8, 35);
        assert_eq!(
            Content::parse(&blob).err(),
            Some(ContentError::TableShape {
                table: "CARD",
                count: 35,
                bytes: 1_152,
                stride: 32,
            })
        );
        // 版本号仍然是对的：这条拒绝**不是**版本号抓到的。
        assert_eq!(
            u16::from_le_bytes([blob[HDR_SCHEMA_VERSION], blob[HDR_SCHEMA_VERSION + 1]]),
            SUPPORTED_SCHEMA_VERSION
        );

        // 每张关键表都要有这条保护，而不是只有 CARD：遍历 `ALL`，把每张表的 count 各加一。
        for table in Table::ALL {
            let mut blob = original.clone();
            let section = Content::parse(&original).expect("the real image");
            let present = section.section(table.section_id()).expect("a section");
            if present.count == 0 {
                continue;
            }
            patch32(&mut blob, dir_base(table.section_id()) + 8, present.count + 1);
            assert!(
                matches!(
                    Content::parse(&blob).err(),
                    Some(ContentError::TableShape { table: name, .. }) if name == table.name()
                ),
                "{} 的行数改了一行也要被拒",
                table.name()
            );
        }
    }

    /// §167：`Table::ALL` 与枚举必须同步。加一个变体不加进 `ALL`，这个 `match` 编译不过。
    #[test]
    fn every_table_is_in_all() {
        for table in Table::ALL {
            match table {
                Table::Card
                | Table::Status
                | Table::EnemyAction
                | Table::Encounter
                | Table::Relic
                | Table::Event
                | Table::Potion => {}
            }
            assert!(Table::ALL.contains(&table));
        }
        assert_eq!(Table::ALL.len(), 7, "七张关键表，一张不少");
        // 段号的往返：`from_section(section_id(t)) == t`。
        for table in Table::ALL {
            assert_eq!(Table::from_section(table.section_id()), Some(table));
        }
    }

    #[test]
    fn a_synthetic_minimal_image_parses() {'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn every_table_is_in_all" not in text, "already inserted"
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(ANCHOR, TEST))
    print("schema/shape/all tests added")


if __name__ == "__main__":
    main()
