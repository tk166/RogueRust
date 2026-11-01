"""§167: key `seen` by entity kind, not by position in `Table::ALL`.

The test used to rely on `Table::ALL`'s order matching `EK_CARD..EK_RELIC` (both 1..=5 and both in the
same order). That is exactly the kind of positional coupling that breaks silently when one side grows
-- which is what widening ALL to seven did. Keying by kind removes the coupling.
"""
import io

PATH = "kernel/rd-core/src/content.rs"

OLD_HEAD = """            let mut seen = [Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new()];"""
NEW_HEAD = """            // §167：按**实体类别**记，而不是按 `Table::ALL` 里的位置 —— 两边原来恰好同序，
            // 于是"位置"与"类别"看起来像一回事。`ALL` 长到七张时这个假设当场崩了。
            let mut seen = [Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new(),
                Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new()];"""

OLD_PUSH = """                seen[entry.entity_kind as usize - 1].push(entry.index);"""
NEW_PUSH = """                seen[entry.entity_kind as usize].push(entry.index);"""

OLD_LOOP = """            for (i, table) in Table::ALL.into_iter().enumerate() {
                // 这份镜像里没有的表（`content.core.rdcf` 没有 EV/POT）跳过 —— `seen` 是按
                // `Table::ALL` 的下标开的，所以这里两边都遍历 `ALL`，只是空表不进 `seen`。
                if content.section(table.section_id()).is_none() {
                    continue;
                }
                let mut indices = seen[i].clone();"""
NEW_LOOP = """            for table in content.tables_present() {
                // `EV`/`POT` 没有 `IDX` 条目（`Table::from_entity_kind` 只覆盖 1..=5），所以它们
                // 不参与"索引把表铺满"这条断言 —— 它们靠自己的列表找，不靠 `IDX`。
                if Table::from_entity_kind(table.entity_kind()).is_none() {
                    continue;
                }
                let mut indices = seen[table.entity_kind() as usize].clone();"""

OLD_IDX = """        patch32(&mut blob, dir_base(S_IDX) + 8, 163);
        let content = Content::parse(&blob).expect("IDX 不是关键表，parse 不管它的行数");
        assert_eq!(
            content.validate(),
            Err(ValidationError::CountExceedsBytes {
                index: S_IDX,
                count: 163,
                stride: 8,
                bytes: 1_296,
            })
        );"""
NEW_IDX = """        // 691 行 × 8 B = 5,528 B 正好；声明 692 行就要 5,536 B。
        patch32(&mut blob, dir_base(S_IDX) + 8, 692);
        let content = Content::parse(&blob).expect("IDX 不是关键表，parse 不管它的行数");
        assert_eq!(
            content.validate(),
            Err(ValidationError::CountExceedsBytes {
                index: S_IDX,
                count: 692,
                stride: 8,
                bytes: 5_528,
            })
        );"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in [
        (OLD_HEAD, NEW_HEAD),
        (OLD_PUSH, NEW_PUSH),
        (OLD_LOOP, NEW_LOOP),
        (OLD_IDX, NEW_IDX),
    ]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("seen keyed by entity kind; the IDX fault case is above capacity")


if __name__ == "__main__":
    main()
