"""§167: widen `Table::ALL` to seven in one place (it was five, missing Event/Potion)."""
import io

PATH = "kernel/rd-core/src/content.rs"

OLD_FIVE = """    /// 全部五张表，顺序 = 段号顺序。
    pub const ALL: [Table; 5] = [
        Table::Card,
        Table::Status,
        Table::EnemyAction,
        Table::Encounter,
        Table::Relic,
    ];
"""

NEW_SEVEN = """    /// 全部**七**张关键表，顺序 = 段号顺序。
    ///
    /// §167：原来是五张（漏了 `Event` 与 `Potion`）。少报不会报错 —— `for table in Table::ALL`
    /// 只是少走两圈，于是"每张表都检查过"这句话在两张表上是假的。
    /// 与枚举的一致性由 `every_table_is_in_all`（穷尽 `match`）钉住：加变体不加进 `ALL` 编译不过。
    pub const ALL: [Table; 7] = [
        Table::Card,
        Table::Status,
        Table::EnemyAction,
        Table::Encounter,
        Table::Relic,
        Table::Event,
        Table::Potion,
    ];
"""

# The 7-entry ALL that the previous (partly applied) edit inserted further down.
OLD_DUP = """
    /// 七张关键表，**一张不少**。`ALL` 与枚举的一致性由 `every_table_is_in_all` 用穷尽 `match` 钉住：
    /// 加一个变体而不加进 `ALL`，那个测试会编译失败。
    pub const ALL: [Table; 7] = [
        Table::Card,
        Table::Status,
        Table::EnemyAction,
        Table::Encounter,
        Table::Relic,
        Table::Event,
        Table::Potion,
    ];
"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(OLD_FIVE) == 1, text.count(OLD_FIVE)
    text = text.replace(OLD_FIVE, NEW_SEVEN)
    assert text.count(OLD_DUP) == 1, text.count(OLD_DUP)
    text = text.replace(OLD_DUP, "")
    assert text.count("pub const ALL: [Table; 7]") == 1
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("ALL: one definition, seven tables")


if __name__ == "__main__":
    main()
