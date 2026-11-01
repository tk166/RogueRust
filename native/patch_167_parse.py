"""§167: `Content::parse` refuses a document whose schema this kernel cannot read.

Two checks, both "can I read this document at all" -- which is why they belong in `parse` rather
than in `validate` (nothing in the production path calls `validate`, and a check nobody calls is a
comment):

1. the header's `schema_version` must be the one this kernel was written against;
2. **every key table's byte length must be a whole number of rows of the shape in
   `Table::schema()`** -- `bytes == count * stride`, exactly.

(2) is the one that cannot be forgotten: the compiler only bumps `SchemaVersion` if somebody
remembers, and `Content::rows` clamps with `min(count, data.len() / stride)`, so a wider row would
otherwise read as *fewer rows* with no error at all.
"""
import io

PATH = "kernel/rd-core/src/content.rs"

OLD_ENUM = """pub enum ContentError {
    TooSmall,
    BadMagic(u32),
    UnsupportedVersion(u16),"""

NEW_ENUM = """pub enum ContentError {
    TooSmall,
    BadMagic(u32),
    UnsupportedVersion(u16),
    /// §167：文档声明的**行 schema 版本**（头部 offset 18）不是本内核认识的那一个。
    ///
    /// 与 `UnsupportedVersion` 分开：那一个是**容器**格式（怎么摆字节），这一个是**行形状**
    /// （每张表一行几格、每格什么类别）。前者变了连段目录都读不出，后者变了段目录照样读得出，
    /// 只有格子的含义变了 —— 而那才是静默错位的地方。
    UnsupportedSchema { found: u16, supported: u16 },
    /// §167：某张关键表的字节数不是"这张表已知行长"的整数倍。
    ///
    /// 响亮在这里，而不是在第一次 `row()` 上：`Content::rows` 用
    /// `min(count, data.len() / stride)` 收尾，行宽变了只会**少读几行**，一句话都不说。
    TableShape {
        table: &'static str,
        count: u32,
        bytes: u32,
        stride: u32,
    },"""

OLD_PARSE_DOC = """    /// 解析头部与段目录。**不校验段内语义** —— 那是 `validate` 与调用方的事。
    ///
    /// 这里只保证"拿得到段视图"这件事成立：头在、magic/版本对、`total_size` 真的在缓冲区里
    /// （`blob.len() >= total_size`，截断 → `TooSmall`）、目录区在声明的镜像内、
    /// 每个目录项都落在声明的镜像内（否则 `SectionOutOfRange`）。"""

NEW_PARSE_DOC = """    /// 解析头部与段目录。**不校验段内语义** —— 那是 `validate` 与调用方的事。
    ///
    /// 这里保证的是"**这个内核读得懂这份文档**"：
    ///
    /// * 头在、magic 对、**容器**版本对、`total_size` 真的在缓冲区里（截断 → `TooSmall`）；
    /// * 目录区在声明的镜像内、每个目录项都落在声明的镜像内（否则 `SectionOutOfRange`）；
    /// * §167 **行 schema 版本**是本内核认识的那一个（否则 `UnsupportedSchema`）；
    /// * §167 七张关键表里每一个非空段的字节数 = `count × stride`（否则 `TableShape`）。
    ///
    /// 后两条与"段内语义"的界线：它们只看**长度**，不看格里的值。判据是"这一行有多宽"，
    /// 而不是"这一行写了什么"。放在 `parse` 而不是 `validate`，是因为生产路径上**没有人调**
    /// `validate` —— 一个没人调用的检查等于一句注释。"""

OLD_VERSION_CHECK = """        let version = u16_at(blob, HDR_VERSION).ok_or(ContentError::TooSmall)?;
        if version != FORMAT_VERSION {
            return Err(ContentError::UnsupportedVersion(version));
        }"""

NEW_VERSION_CHECK = """        let version = u16_at(blob, HDR_VERSION).ok_or(ContentError::TooSmall)?;
        if version != FORMAT_VERSION {
            return Err(ContentError::UnsupportedVersion(version));
        }
        // §167：**行 schema** 版本。容器能读不代表里面的表能读 —— 见 `UnsupportedSchema`。
        let schema = u16_at(blob, HDR_SCHEMA_VERSION).ok_or(ContentError::TooSmall)?;
        if schema != SUPPORTED_SCHEMA_VERSION {
            return Err(ContentError::UnsupportedSchema {
                found: schema,
                supported: SUPPORTED_SCHEMA_VERSION,
            });
        }"""

OLD_TAIL = """        Ok(Self {
            blob,
            version,
            section_count: nsec,
        })"""

NEW_TAIL = """        // 5. §167：每张关键表都必须是"已知行长"的整数倍（只看长度，不看值）。
        for table in Table::ALL {
            let index = table.section_id();
            if index >= nsec {
                continue;
            }
            let base = dir_off + index * DIRECTORY_ENTRY_BYTES;
            let offset = u32_at(blob, base).ok_or(ContentError::DirectoryTruncated)? as usize;
            let bytes = u32_at(blob, base + 4).ok_or(ContentError::DirectoryTruncated)?;
            let count = u32_at(blob, base + 8).ok_or(ContentError::DirectoryTruncated)?;
            let stride = table.stride();
            // An empty section is `0, 0` and is always fine (an absent table is not a shape error).
            if bytes == 0 && count == 0 {
                continue;
            }
            // 精确相等，不是"至少装得下"：多出来的字节同样说明行宽不是我以为的那个。
            if u64::from(bytes) != u64::from(count) * u64::from(stride) {
                let _ = offset;
                return Err(ContentError::TableShape {
                    table: table.name(),
                    count,
                    bytes,
                    stride,
                });
            }
        }

        Ok(Self {
            blob,
            version,
            section_count: nsec,
        })"""

OLD_CONST = """const HDR_SCHEMA_VERSION: usize = 18;"""

NEW_CONST = """const HDR_SCHEMA_VERSION: usize = 18;
/// §167：本内核认得的**行 schema** 版本（头部 offset 18）。
///
/// 什么时候要改它：任何一张关键表增删一格、或换掉某一格的类别。改的时候两边一起改 ——
/// 编译器写进头部的那个数（源 JSON 的 `SchemaVersion`）与这里的这个数，否则文档在 `parse` 就被拒。
/// 只改内容、不改形状（加一张牌、改一句描述）**不必**改它：那种变化由 §166 的内容指纹管。
pub const SUPPORTED_SCHEMA_VERSION: u16 = 1;"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in [
        (OLD_ENUM, NEW_ENUM),
        (OLD_PARSE_DOC, NEW_PARSE_DOC),
        (OLD_VERSION_CHECK, NEW_VERSION_CHECK),
        (OLD_CONST, NEW_CONST),
        (OLD_TAIL, NEW_TAIL),
    ]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("parse refuses an unreadable schema and a mis-shaped key table")


if __name__ == "__main__":
    main()
