"""§167: `rdcf_verify.py` checked five tables while the format has seven.

`STRIDED` was a hand-written list of five. The manifest has carried `events` and `potions` all along,
and `rdcfmt.ROW_SCHEMAS` has seven keys -- so "5/5 tables" was a true statement about a list that had
quietly stopped covering the format. Two changes:

1. `STRIDED` covers all seven (same numbers as `ROW_SCHEMAS`);
2. a guard: the number of strided entries must equal `len(ROW_SCHEMAS)`, so adding a table to the
   format without adding it here fails instead of silently narrowing the check again.

The guard compares **counts**, which is the thing that was wrong. It cannot verify the names line up
(section names and schema names differ on purpose: `STAT` vs `STATUS`), so it also prints both sets.
"""
import io

PATH = "tools/rdcf_verify.py"

OLD = '''# 段名 -> (manifest 顶层 tables 里的键, row_stride 用的 schema 名)
# 用来交叉检查 "段字节数 == count × stride"。
STRIDED = {
    "CARD": ("cards", "CARD"),
    "STAT": ("statuses", "STATUS"),
    "EACT": ("enemy_actions", "EACT"),
    "ENCT": ("encounters", "ENCT"),
    "REL": ("relics", "REL"),
}'''

NEW = '''# 段名 -> (manifest 顶层 tables 里的键, row_stride 用的 schema 名)
# 用来交叉检查 "段字节数 == count × stride"。
#
# §167：这里原来是**五**张（漏了 EV / POT），而 `rdcfmt.ROW_SCHEMAS` 有七张、`manifest.tables`
# 也一直写着 `events` / `potions`。于是 "5/5 tables" 是一句关于**残缺清单**的真话 ——
# 全绿的闸门只覆盖了它自己列出来的那部分。下面的 `assert_strided_is_complete()` 让"再漏一张"
# 变成响亮失败。
STRIDED = {
    "CARD": ("cards", "CARD"),
    "STAT": ("statuses", "STATUS"),
    "EACT": ("enemy_actions", "EACT"),
    "ENCT": ("encounters", "ENCT"),
    "REL": ("relics", "REL"),
    "EV": ("events", "EV"),
    "POT": ("potions", "POT"),
}


def assert_strided_is_complete():
    """清单必须与 `ROW_SCHEMAS` 一样宽 —— 数量不等就退，而不是少查几张。

    只比**数量**是不够的，所以两边的名字一起打印：名字对不上时人一眼能看出来，而数量相等
    这件事是脚本能判的。清单里多一个 `ROW_SCHEMAS` 没有的名字同样算错（`row_stride` 会 KeyError）。
    """
    schemas = set(ROW_SCHEMAS)
    listed = {schema for _, schema in STRIDED.values()}
    if len(STRIDED) != len(schemas) or listed != schemas:
        print("!! 定长表清单与 rdcfmt.ROW_SCHEMAS 不一致：")
        print(f"   清单 {len(STRIDED)} 张：{sorted(listed)}")
        print(f"   格式 {len(schemas)} 张：{sorted(schemas)}")
        print("   闸门不判通过（退出码 2）—— 少查一张表等于这条闸门从没覆盖过它。")
        sys.exit(2)
    print(f"   定长表 {len(STRIDED)} 张（{', '.join(sorted(listed))}）")'''

OLD_CALL = '''    tables = mf.get("tables")'''

NEW_CALL = '''    tables = mf.get("tables")
    if tables is not None:
        assert_strided_is_complete()'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(OLD) == 1
    text = text.replace(OLD, NEW)
    assert text.count(OLD_CALL) == 1, text.count(OLD_CALL)
    text = text.replace(OLD_CALL, NEW_CALL)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("rdcf_verify covers seven tables, and says so if it stops")


if __name__ == "__main__":
    main()
