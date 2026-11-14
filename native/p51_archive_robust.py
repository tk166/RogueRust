"""§396：存档的**抄写鲁棒性** —— 换行/空白/base64 变体都不该让存档回不来。

## 为什么要改（这次真的踩到了）

玩家把存档贴在聊天里，我人工转抄一遍 → CRC 不匹配（`archive checksum mismatch`）。
后来**原样落盘**再读就通过了 ⇒ 转抄丢了字符。这暴露了两件可以修的事：

1. **导入端太挑**：`restore` 只接受 `trim()` 之后**原封不动**的一行。现实里存档会被
   * 编辑器/终端**折行**（每 80 列插一个换行）；
   * 某些客户端把 `+` 变成空格、或把 `/` 加转义；
   * base64**url** 变体（`-_`）与标准变体（`+/`）混用。
   ⇒ 导入时先**规范化**：去掉所有空白，`-_` 归一成 `+/`（只在这两个位置等价，base64 里
   `-` 不可能是别的东西 —— 分隔符是**最后**那个 `-`，用 `rsplit` 找）。
2. **拒绝信息不说人话**：`archive checksum mismatch (edited or truncated?)` 不告诉你是哪一段、
   多长。⇒ 带上"期望/实际"的数字，让"被截断"与"抄错"能分开。

## 不改的东西

* **格式不变**（还是 `RDA1-<base64>-<crc32>`）：老存档继续能读；
* **CRC 不放宽**：规范化之后仍然逐字节校验 —— 抄错一个字符还是会被拒（这是对的）。
"""

import io

PATH = 'kernel/rd-run/src/state/archive.rs'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''pub fn restore(text: &str, expected_content: i32, state: &mut RunState) -> Result<(), ArchiveError> {
    let bytes = text.trim().as_bytes();
    let magic = MAGIC.as_bytes();'''

NEW = '''pub fn restore(text: &str, expected_content: i32, state: &mut RunState) -> Result<(), ArchiveError> {
    // §396：先把"抄写噪声"去掉 —— 折行/空白/`-_` 变体都不该让一份好存档回不来。
    //
    // ⚠️ 只做**等价变换**：去掉空白（base64 里不出现空白）、把 base64url 的 `-_` 归一成 `+/`。
    // CRC 与内容指纹照旧逐字节校验 —— 抄错一个字符仍然会被拒。
    let mut cleaned: [u8; MAX_ARCHIVE * 2] = [0u8; MAX_ARCHIVE * 2];
    let mut cleaned_len = 0usize;
    for &byte in text.as_bytes() {
        if byte.is_ascii_whitespace() {
            continue;
        }
        let mapped = match byte {
            b'-' => b'+',
            b'_' => b'/',
            other => other,
        };
        if cleaned_len == cleaned.len() {
            return Err(ArchiveError::TooLong);
        }
        cleaned[cleaned_len] = mapped;
        cleaned_len += 1;
    }
    // ⚠️ 归一之后，`-` 分隔符变成了 `+` —— 所以分隔符要按**原来的最后一个 `-`** 找。
    // 做法：在规范化之前先定位尾部的 `-<8 hex>`（这一段不含 `-`、也不含空白）。
    let bytes = text.trim().as_bytes();
    let magic = MAGIC.as_bytes();'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD2 = '''    let body = &bytes[magic.len() + 1..];
    // 尾部必须是 `-` + 8 位小写十六进制。
    if body.len() < 10 || body[body.len() - 9] != b'-' {
        return Err(ArchiveError::BadTail);
    }
    let tail_start = body.len() - 9;
    let encoded = &body[..tail_start];'''
NEW2 = '''    let body = &bytes[magic.len() + 1..];
    // 尾部必须是 `-` + 8 位小写十六进制。
    if body.len() < 10 || body[body.len() - 9] != b'-' {
        return Err(ArchiveError::BadTail);
    }
    let tail_start = body.len() - 9;
    // §396：编码段用**规范化之后**的那一段（去掉空白、`-_` → `+/`），长度从 magic 之后算起。
    let encoded = &cleaned[magic.len() + 1..cleaned_len - 9];'''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('restore: 规范化输入')
