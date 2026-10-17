//! Allocation-free canonical text writing.
//!
//! The reference engine builds its state fingerprint by appending `key=value` lines to a
//! `StringBuilder` and hashing the UTF-8 bytes. Reproducing that byte-for-byte is the
//! cheapest possible way to prove a port agrees with the original - and it needs no
//! allocator, so the same code runs on the target.
//!
//! Everything here writes into a caller-provided slice. Running out of room is recorded
//! (`overflowed()`) rather than panicking: a fingerprint that silently truncates would be a
//! wonderful way to ship a false "the states match" result, so callers are expected to check.

/// Writes into a fixed `&mut [u8]` and can report whether it ran out of space.
///
/// Deliberately NOT `core::fmt`: the formatting machinery pulls in a lot of code for a
/// bare-metal target, and the reference format only needs decimal integers and raw strings.
pub struct TextWriter<'a> {
    buf: &'a mut [u8],
    len: usize,
    overflow: bool,
}

impl<'a> TextWriter<'a> {
    #[must_use]
    pub fn new(buf: &'a mut [u8]) -> Self {
        Self {
            buf,
            len: 0,
            overflow: false,
        }
    }

    /// Bytes written so far. Valid even after an overflow (it is then the capacity).
    #[must_use]
    pub fn len(&self) -> usize {
        self.len
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    /// True once some write did not fit. The tail of the buffer is then not meaningful.
    #[must_use]
    pub fn overflowed(&self) -> bool {
        self.overflow
    }

    /// The written prefix as `&str`. Always valid UTF-8 because only whole `str`/`char`
    /// writes happen; a truncated multi-byte sequence can never occur.
    #[must_use]
    pub fn as_str(&self) -> &str {
        // Only complete UTF-8 writes are performed below, so this cannot fail.
        core::str::from_utf8(&self.buf[..self.len]).unwrap_or("")
    }

    fn put(&mut self, bytes: &[u8]) {
        if self.overflow {
            return;
        }
        let end = self.len + bytes.len();
        if end > self.buf.len() {
            self.overflow = true;
            return;
        }
        self.buf[self.len..end].copy_from_slice(bytes);
        self.len = end;
    }

    pub fn str(&mut self, s: &str) -> &mut Self {
        self.put(s.as_bytes());
        self
    }

    pub fn char(&mut self, c: char) -> &mut Self {
        let mut tmp = [0u8; 4];
        self.put(c.encode_utf8(&mut tmp).as_bytes());
        self
    }

    pub fn u32(&mut self, v: u32) -> &mut Self {
        let mut tmp = [0u8; 10];
        let mut i = tmp.len();
        let mut n = v;
        loop {
            i -= 1;
            tmp[i] = b'0' + (n % 10) as u8;
            n /= 10;
            if n == 0 {
                break;
            }
        }
        self.put(&tmp[i..]);
        self
    }

    pub fn u64(&mut self, v: u64) -> &mut Self {
        let mut tmp = [0u8; 20];
        let mut i = tmp.len();
        let mut n = v;
        loop {
            i -= 1;
            tmp[i] = b'0' + (n % 10) as u8;
            n /= 10;
            if n == 0 {
                break;
            }
        }
        self.put(&tmp[i..]);
        self
    }

    pub fn i32(&mut self, v: i32) -> &mut Self {
        if v < 0 {
            self.put(b"-");
            // Negate in u32 space so i32::MIN does not overflow.
            self.put_u32_digits(v.unsigned_abs());
        } else {
            self.put_u32_digits(v as u32);
        }
        self
    }

    pub fn i64(&mut self, v: i64) -> &mut Self {
        if v < 0 {
            self.put(b"-");
            self.put_u64_digits(v.unsigned_abs());
        } else {
            self.put_u64_digits(v as u64);
        }
        self
    }

    fn put_u32_digits(&mut self, v: u32) {
        let mut tmp = [0u8; 10];
        let mut i = tmp.len();
        let mut n = v;
        loop {
            i -= 1;
            tmp[i] = b'0' + (n % 10) as u8;
            n /= 10;
            if n == 0 {
                break;
            }
        }
        self.put(&tmp[i..]);
    }

    fn put_u64_digits(&mut self, v: u64) {
        let mut tmp = [0u8; 20];
        let mut i = tmp.len();
        let mut n = v;
        loop {
            i -= 1;
            tmp[i] = b'0' + (n % 10) as u8;
            n /= 10;
            if n == 0 {
                break;
            }
        }
        self.put(&tmp[i..]);
    }

    /// `Some(v)` writes the number; `None` writes nothing. Mirrors the reference's
    /// `?.ToString() ?? ""` idiom, which is used for a nullable combatant id.
    pub fn opt_i32_blank(&mut self, v: Option<i32>) -> &mut Self {
        match v {
            Some(n) => self.i32(n),
            None => self,
        }
    }

    /// `Some(v)` writes the number; `None` writes `null`. Mirrors `?.ToString() ?? "null"`.
    pub fn opt_i32_null(&mut self, v: Option<i32>) -> &mut Self {
        match v {
            Some(n) => self.i32(n),
            None => self.str("null"),
        }
    }

    /// `Some(s)` writes the string; `None` writes `none`. Mirrors the reference's
    /// `rule.OwnerCombatantId ?? "none"`.
    pub fn opt_str_none(&mut self, v: Option<&str>) -> &mut Self {
        match v {
            Some(s) => self.str(s),
            None => self.str("none"),
        }
    }

    /// Writes a suffix token only when `cond` holds - the reference uses this for
    /// `pending`/`dead`/`ownerbound`, whose absence is itself part of the format.
    pub fn when(&mut self, cond: bool, text: &str) -> &mut Self {
        if cond {
            self.str(text);
        }
        self
    }

    /// A `bool` as the reference spells it in the `ExpiresWhenOwnerRemoved` case.
    pub fn when_str(&mut self, cond: bool, text: &str, _otherwise: &str) -> &mut Self {
        if cond {
            self.str(text);
        }
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn written(f: impl FnOnce(&mut TextWriter<'_>)) -> String {
        let mut buf = [0u8; 256];
        let mut w = TextWriter::new(&mut buf);
        f(&mut w);
        assert!(!w.overflowed(), "test buffer too small");
        w.as_str().to_string()
    }

    #[test]
    fn integers_match_the_reference_spelling() {
        assert_eq!(written(|w| { w.i32(0); }), "0");
        assert_eq!(written(|w| { w.i32(-1); }), "-1");
        assert_eq!(written(|w| { w.i32(42); }), "42");
        assert_eq!(written(|w| { w.i32(i32::MIN); }), "-2147483648");
        assert_eq!(written(|w| { w.i32(i32::MAX); }), "2147483647");
        assert_eq!(written(|w| { w.u64(u64::MAX); }), "18446744073709551615");
        assert_eq!(written(|w| { w.i64(i64::MIN); }), "-9223372036854775808");
    }

    #[test]
    fn nullable_spellings_differ() {
        // `active=` uses the blank idiom, `res=.../` uses the "null" idiom.
        assert_eq!(written(|w| { w.opt_i32_blank(None); }), "");
        assert_eq!(written(|w| { w.opt_i32_blank(Some(7)); }), "7");
        assert_eq!(written(|w| { w.opt_i32_null(None); }), "null");
        assert_eq!(written(|w| { w.opt_i32_null(Some(-3)); }), "-3");
        assert_eq!(written(|w| { w.opt_str_none(None); }), "none");
        assert_eq!(written(|w| { w.opt_str_none(Some("hero")); }), "hero");
    }

    #[test]
    fn suffix_tokens_appear_only_when_set() {
        assert_eq!(written(|w| { w.when(false, " dead"); }), "");
        assert_eq!(written(|w| { w.when(true, " dead"); }), " dead");
    }

    #[test]
    fn a_full_line_reads_like_the_reference() {
        // One line in the shape of AppendStatus.
        let s = written(|w| {
            w.str("s=s1 standard.poison stk=").i32(2)
                .str(" dur=").i32(0)
                .str(" chg=").i32(0)
                .str(" pol=").i32(1)
                .when(true, " pend=3")
                .char('\n');
        });
        assert_eq!(s, "s=s1 standard.poison stk=2 dur=0 chg=0 pol=1 pend=3\n");
    }

    #[test]
    fn overflow_is_reported_not_hidden() {
        // A write that does not fit is dropped WHOLE. Truncating would leave half a field in
        // the buffer, and half a field hashes as a plausible-but-wrong fingerprint - the one
        // failure mode a determinism harness must never have. So: never partial, always flagged.
        let mut buf = [0u8; 4];
        let mut w = TextWriter::new(&mut buf);
        w.str("abc");
        assert!(!w.overflowed());
        w.str("defgh"); // 5 bytes into 1 free byte
        assert!(w.overflowed());
        assert_eq!(w.as_str(), "abc");

        // A NUMBER must never be half-written either - "123456" must not become "12345612".
        let mut buf2 = [0u8; 8];
        let mut w2 = TextWriter::new(&mut buf2);
        w2.i32(123456); // 6 digits, fits exactly
        assert!(!w2.overflowed());
        assert_eq!(w2.as_str(), "123456");
        w2.i32(123456); // only 2 bytes left
        assert!(w2.overflowed());
        assert_eq!(w2.as_str(), "123456");
    }

    #[test]
    fn multibyte_chars_never_split() {
        let mut buf = [0u8; 3];
        let mut w = TextWriter::new(&mut buf);
        w.char('\u{4e2d}'); // 3 bytes, fits exactly
        assert!(!w.overflowed());
        assert_eq!(w.as_str(), "\u{4e2d}");
        w.char('\u{4e2d}'); // no room for another 3-byte char
        assert!(w.overflowed());
        assert_eq!(w.as_str(), "\u{4e2d}");
    }
}
