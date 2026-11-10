//! SHA-256, allocation-free.
//!
//! The reference engine fingerprints a combat by hashing the UTF-8 bytes of a canonical
//! `key=value` text dump and returning lowercase hex. SHA-256 itself is the easy half of that
//! contract - the format is the half that can actually diverge - but it has to be exact, and
//! it has to run without an allocator.
//!
//! Written from FIPS 180-4 and checked against the published NIST vectors in the tests below,
//! because "probably right" is not a thing a fingerprint can be.

/// Round constants: the first 32 bits of the fractional parts of the cube roots of the first
/// 64 primes.
const K: [u32; 64] = [
    0x428a_2f98, 0x7137_4491, 0xb5c0_fbcf, 0xe9b5_dba5, 0x3956_c25b, 0x59f1_11f1, 0x923f_82a4,
    0xab1c_5ed5, 0xd807_aa98, 0x1283_5b01, 0x2431_85be, 0x550c_7dc3, 0x72be_5d74, 0x80de_b1fe,
    0x9bdc_06a7, 0xc19b_f174, 0xe49b_69c1, 0xefbe_4786, 0x0fc1_9dc6, 0x240c_a1cc, 0x2de9_2c6f,
    0x4a74_84aa, 0x5cb0_a9dc, 0x76f9_88da, 0x983e_5152, 0xa831_c66d, 0xb003_27c8, 0xbf59_7fc7,
    0xc6e0_0bf3, 0xd5a7_9147, 0x06ca_6351, 0x1429_2967, 0x27b7_0a85, 0x2e1b_2138,
    0x4d2c_6dfc, 0x5338_0d13, 0x650a_7354, 0x766a_0abb, 0x81c2_c92e, 0x9272_2c85,
    0xa2bf_e8a1, 0xa81a_664b, 0xc24b_8b70, 0xc76c_51a3, 0xd192_e819, 0xd699_0624,
    0xf40e_3585, 0x106a_a070, 0x19a4_c116, 0x1e37_6c08, 0x2748_774c, 0x34b0_bcb5,
    0x391c_0cb3, 0x4ed8_aa4a, 0x5b9c_ca4f, 0x682e_6ff3, 0x748f_82ee, 0x78a5_636f,
    0x84c8_7814, 0x8cc7_0208, 0x90be_fffa, 0xa450_6ceb, 0xbef9_a3f7, 0xc671_78f2,
];

/// Initial hash value: the first 32 bits of the fractional parts of the square roots of the
/// first 8 primes.
const H0: [u32; 8] = [
    0x6a09_e667, 0xbb67_ae85, 0x3c6e_f372, 0xa54f_f53a,
    0x510e_527f, 0x9b05_688c, 0x1f83_d9ab, 0x5be0_cd19,
];

/// Streaming SHA-256. No allocation: one 64-byte block buffer lives inline.
pub struct Sha256 {
    h: [u32; 8],
    buf: [u8; 64],
    buf_len: usize,
    total_len: u64,
}

impl Default for Sha256 {
    fn default() -> Self {
        Self::new()
    }
}

impl Sha256 {
    #[must_use]
    pub const fn new() -> Self {
        Self {
            h: H0,
            buf: [0u8; 64],
            buf_len: 0,
            total_len: 0,
        }
    }

    pub fn update(&mut self, mut data: &[u8]) {
        self.total_len = self.total_len.wrapping_add(data.len() as u64);

        if self.buf_len > 0 {
            let space = 64 - self.buf_len;
            let take = space.min(data.len());
            self.buf[self.buf_len..self.buf_len + take].copy_from_slice(&data[..take]);
            self.buf_len += take;
            data = &data[take..];
            if self.buf_len == 64 {
                let block = self.buf;
                self.compress(&block);
                self.buf_len = 0;
            }
        }

        while data.len() >= 64 {
            let mut block = [0u8; 64];
            block.copy_from_slice(&data[..64]);
            self.compress(&block);
            data = &data[64..];
        }

        if !data.is_empty() {
            self.buf[..data.len()].copy_from_slice(data);
            self.buf_len = data.len();
        }
    }

    fn compress(&mut self, block: &[u8; 64]) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                block[4 * i],
                block[4 * i + 1],
                block[4 * i + 2],
                block[4 * i + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }

        let mut a = self.h[0];
        let mut b = self.h[1];
        let mut c = self.h[2];
        let mut d = self.h[3];
        let mut e = self.h[4];
        let mut f = self.h[5];
        let mut g = self.h[6];
        let mut h = self.h[7];

        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = h
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);

            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }

        self.h[0] = self.h[0].wrapping_add(a);
        self.h[1] = self.h[1].wrapping_add(b);
        self.h[2] = self.h[2].wrapping_add(c);
        self.h[3] = self.h[3].wrapping_add(d);
        self.h[4] = self.h[4].wrapping_add(e);
        self.h[5] = self.h[5].wrapping_add(f);
        self.h[6] = self.h[6].wrapping_add(g);
        self.h[7] = self.h[7].wrapping_add(h);
    }

    #[must_use]
    pub fn finalize(mut self) -> [u8; 32] {
        let bit_len = self.total_len.wrapping_mul(8);

        // 0x80, then zeros, then the 64-bit big-endian bit length, padded to a block boundary.
        let mut pad = [0u8; 128];
        pad[0] = 0x80;
        let pad_len = if self.buf_len < 56 {
            56 - self.buf_len
        } else {
            120 - self.buf_len
        };
        pad[pad_len..pad_len + 8].copy_from_slice(&bit_len.to_be_bytes());
        let total_pad = pad_len + 8;

        let mut off = 0usize;
        while off < total_pad {
            let space = 64 - self.buf_len;
            let take = space.min(total_pad - off);
            self.buf[self.buf_len..self.buf_len + take].copy_from_slice(&pad[off..off + take]);
            self.buf_len += take;
            off += take;
            if self.buf_len == 64 {
                let block = self.buf;
                self.compress(&block);
                self.buf_len = 0;
            }
        }
        debug_assert_eq!(self.buf_len, 0, "padding must land on a block boundary");

        let mut out = [0u8; 32];
        for i in 0..8 {
            out[4 * i..4 * i + 4].copy_from_slice(&self.h[i].to_be_bytes());
        }
        out
    }
}

/// One-shot convenience.
#[must_use]
pub fn sha256(data: &[u8]) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(data);
    h.finalize()
}

/// §334：**完整**指纹（`write_full_hash_input` 的 SHA-256）—— `hash_golden` 的严格超集。
///
/// 为什么单独一个入口而不是给 `write_hash_input` 加参数：`hash_golden` 是参考规范文本的
/// 逐字节复刻（85 份语料 + `golden-baseline` 闸门都建在它上面）。两个入口让"这条改动该不该
/// 动基线"可以分开回答：`write_hash_input` 动 = 基线动；只有 `write_full_hash_input` 动 =
/// 只影响"这一局是否相同"的判定。
///
/// ⚠️ `rd-core` 是 `no_std`：所以写进调用方给的 `[u8; 64]`，不返回 `String`
/// （与 [`to_hex_lower`] 同一个形状）。
pub fn full_hash_hex(out: &mut [u8; 64], text: &str) {
    to_hex_lower(out, &sha256(text.as_bytes()));
}

/// Lowercase hex, 64 characters. Matches `Convert.ToHexString(...).ToLowerInvariant()`.
pub fn to_hex_lower(out: &mut [u8; 64], digest: &[u8; 32]) {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for (i, b) in digest.iter().enumerate() {
        out[2 * i] = HEX[(b >> 4) as usize];
        out[2 * i + 1] = HEX[(b & 0x0f) as usize];
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex_of(data: &[u8]) -> String {
        let mut buf = [0u8; 64];
        to_hex_lower(&mut buf, &sha256(data));
        String::from_utf8(buf.to_vec()).unwrap()
    }

    #[test]
    fn nist_vector_empty() {
        assert_eq!(
            hex_of(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }

    #[test]
    fn nist_vector_abc() {
        assert_eq!(
            hex_of(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn nist_vector_448_bit_message() {
        // The two-block vector: exercises the padding path where 0x80 does NOT fit before
        // the length field, so a whole extra block is required.
        assert_eq!(
            hex_of(b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
        );
    }

    #[test]
    fn nist_vector_one_million_a() {
        let mut h = Sha256::new();
        let chunk = [b'a'; 1000];
        for _ in 0..1000 {
            h.update(&chunk);
        }
        let mut buf = [0u8; 64];
        to_hex_lower(&mut buf, &h.finalize());
        assert_eq!(
            String::from_utf8(buf.to_vec()).unwrap(),
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"
        );
    }

    #[test]
    fn block_boundaries_are_exact() {
        // 55, 56, 63 and 64 bytes are where the padding logic changes shape. Each is compared
        // against a streaming run split at an awkward place, so update() cannot be "mostly right".
        for n in [0usize, 1, 55, 56, 57, 63, 64, 65, 119, 120, 128] {
            let data: Vec<u8> = (0..n).map(|i| (i * 7 % 251) as u8).collect();
            let one_shot = hex_of(&data);
            let mut h = Sha256::new();
            for b in &data {
                h.update(core::slice::from_ref(b));
            }
            let mut buf = [0u8; 64];
            to_hex_lower(&mut buf, &h.finalize());
            assert_eq!(
                String::from_utf8(buf.to_vec()).unwrap(),
                one_shot,
                "byte-at-a-time differs at n={n}"
            );
        }
    }

    #[test]
    fn hex_is_lowercase() {
        let mut buf = [0u8; 64];
        to_hex_lower(&mut buf, &[0xAB; 32]);
        let s = String::from_utf8(buf.to_vec()).unwrap();
        assert_eq!(s, "ab".repeat(32));
    }
}
