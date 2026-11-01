"""§167: `Table::ALL` 是"内核认识哪些表"，不是"每份镜像都有哪些表"。

Widening ALL to seven made three tests panic: they iterate ALL over the RogueDeck core image, which
predates `EV`/`POT` and has no such sections. The fix is an honest API rather than a `unwrap_or`:
`Content::tables_present()` is the list this image actually has, and the tests that walk "every
table" use it. `parse`'s shape check keeps using `ALL` (an absent table is skipped there anyway),
because that check is about what the *kernel* knows.
"""
import io

CONTENT = "kernel/rd-core/src/content.rs"
HOST = "kernel/rd-core/src/host.rs"

PRESENT = '''    /// 迭代表内所有行（行数取 `count` 与"字节装得下的行数"的较小者）。'''

PRESENT_NEW = '''    /// 这份镜像里**存在**的关键表（`Table::ALL ∩ 非空段`）。
    ///
    /// §167：`Table::ALL` 回答的是"**这个内核**认识哪些表"，不是"**这份镜像**有哪几张" ——
    /// `content.core.rdcf`（RogueDeck 那份）就早于 `EV`/`POT`，两张表都不存在。把两者混为一谈，
    /// 一个 `for table in Table::ALL { content.section(...).unwrap() }` 就会在换镜像时崩，
    /// 而崩的位置看起来像"镜像坏了"。
    pub fn tables_present(&self) -> impl Iterator<Item = Table> + '_ {
        Table::ALL
            .into_iter()
            .filter(|table| self.section(table.section_id()).is_some_and(|s| !s.is_empty()))
    }

    /// 迭代表内所有行（行数取 `count` 与"字节装得下的行数"的较小者）。'''


def main():
    text = io.open(CONTENT, encoding="utf-8").read()
    assert text.count(PRESENT) == 1
    text = text.replace(PRESENT, PRESENT_NEW)

    # (a) the synthetic minimal image: 7 was incidental, and it is now a refusal.
    old = """        blob[HDR_SCHEMA_VERSION..HDR_SCHEMA_VERSION + 2].copy_from_slice(&7u16.to_le_bytes());"""
    new = """        // §167：探针里原来写的是 7 —— 那时 `parse` 不查行 schema，于是它顺带证明了"内核什么版本都收"。
        // 现在写本内核支持的那个，这条测试回到它自己的题目（目录与段视图）。
        blob[HDR_SCHEMA_VERSION..HDR_SCHEMA_VERSION + 2]
            .copy_from_slice(&SUPPORTED_SCHEMA_VERSION.to_le_bytes());"""
    assert text.count(old) == 1
    text = text.replace(old, new)
    old = """        assert_eq!(content.schema_version(), 7);"""
    new = """        assert_eq!(content.schema_version(), SUPPORTED_SCHEMA_VERSION);"""
    assert text.count(old) == 1
    text = text.replace(old, new)

    # (b) `validate` 的 count×stride 病例改用**非关键表**（IDX）：关键表那一条现在被 `parse` 更早拒掉，
    #     两种情况都要有判据，否则 `validate` 的那条臂就成了不可达的死代码。
    old = """        // count × stride > bytes（CARD 声明 63 行，只有 62 行的字节）。
        let mut blob = original.clone();
        patch32(&mut blob, dir_base(S_CARD) + 8, 63);
        let content = Content::parse(&blob).unwrap();
        assert_eq!(
            content.validate(),
            Err(ValidationError::CountExceedsBytes {
                index: S_CARD,
                count: 63,
                stride: 32,
                bytes: 1_984,
            })
        );
        // 但按字节取行仍然是安全的：第 63 行拿不到。
        assert!(content.card(62).is_none());
        assert_eq!(content.rows(Table::Card).count(), 62);"""
    new = """        // count × stride > bytes。**关键表由 `parse` 先拒**（§167），所以这里的病例走非关键表 IDX：
        // 两条臂都要有活着的判据，否则其中一条迟早变成永远不执行的死代码。
        let mut blob = original.clone();
        patch32(&mut blob, dir_base(S_CARD) + 8, 63);
        assert_eq!(
            Content::parse(&blob).err(),
            Some(ContentError::TableShape {
                table: "CARD",
                count: 63,
                bytes: 1_984,
                stride: 32,
            }),
            "a key table with the wrong row count must be refused by `parse`, before `validate`"
        );

        // 非关键表（IDX，stride 8）：`parse` 不看它，`validate` 负责。
        let mut blob = original.clone();
        patch32(&mut blob, dir_base(S_IDX) + 8, 163);
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
    assert text.count(old) == 1, "the validate case moved"
    text = text.replace(old, new)

    # (c) the two "every table" walkers iterate what this image has.
    old = """            for table in Table::ALL {
                assert_eq!(table.stride(), align4(2 * table.cells() as u32));"""
    new = """            for table in content.tables_present() {
                assert_eq!(table.stride(), align4(2 * table.cells() as u32));"""
    assert text.count(old) == 1
    text = text.replace(old, new)

    old = """            for (i, table) in Table::ALL.into_iter().enumerate() {
                let mut indices = seen[i].clone();"""
    new = """            for (i, table) in Table::ALL.into_iter().enumerate() {
                // 这份镜像里没有的表（`content.core.rdcf` 没有 EV/POT）跳过 —— `seen` 是按
                // `Table::ALL` 的下标开的，所以这里两边都遍历 `ALL`，只是空表不进 `seen`。
                if content.section(table.section_id()).is_none() {
                    continue;
                }
                let mut indices = seen[i].clone();"""
    assert text.count(old) == 1
    text = text.replace(old, new)

    io.open(CONTENT, "w", encoding="utf-8", newline="").write(text)

    # (d) the hand-built fixture in host.rs declares 7 too.
    host = io.open(HOST, encoding="utf-8").read()
    old = """        blob[18..20].copy_from_slice(&7u16.to_le_bytes()); // SchemaVersion"""
    new = """        // §167：`parse` 现在真的比对这一格；探针原来写 7（那时它只是"随便一个非零值"）。
        blob[18..20].copy_from_slice(&rd_core::content::SUPPORTED_SCHEMA_VERSION.to_le_bytes());"""
    assert host.count(old) == 1
    host = host.replace(old, new)
    io.open(HOST, "w", encoding="utf-8", newline="").write(host)
    print("tables_present added; fixtures declare the supported schema")


if __name__ == "__main__":
    main()
