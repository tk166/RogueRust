//! Measures how much RISC-V code the kernel actually costs.
//!
//! The embedded brief is "runs on an ESP32-P4 with 592 KB of usable SRAM", and every later
//! decision leans on that. A number is worth more than a belief, so this crate exists to
//! produce one: it forces rng + hash + writer to be retained, compiles for
//! `riscv32imac-unknown-none-elf` (no F/D - the kernel is integer-only), and lets
//! `tools/size_probe.py` report the resulting `.text`.
//!
//! It is deliberately a staticlib rather than a binary. A bare-metal executable needs an
//! entry point, a linker script and a memory map; none of those exist yet, and none of them
//! are needed to answer "how big is this".

// Bare metal only - and BOTH halves of that matter.
//
// `no_std` + a `#[panic_handler]` is what the RISC-V measurement needs, and it is exactly what the
// host build cannot have: the test harness links std (which already defines `panic_impl`, E0152),
// and a host build with the default `panic = "unwind"` cannot carry a panic handler at all
// ("unwinding panics are not supported without std"). So both the attribute and the handler are
// gated on the bare-metal target, which is the only target this crate is ever built for in anger;
// on the host it is an ordinary std crate that `cargo test` and `cargo clippy` can chew on.
#![cfg_attr(all(not(test), target_os = "none"), no_std)]
#![forbid(unsafe_code)]

#[cfg(all(not(test), target_os = "none"))]
use core::panic::PanicInfo;

/// A bare crate still needs a panic handler to link.
///
/// `target_os = "none"` as well as `not(test)`, and the second half matters: a `no_std` crate that
/// defines `panic_impl` cannot be built for the host with the default `panic = "unwind"` ("unwinding
/// panics are not supported without std"), which is what `cargo clippy` on the workspace does. The
/// handler is only ever needed on the bare-metal target, so that is the only target that gets it.
#[cfg(all(not(test), target_os = "none"))]
#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    loop {}
}

/// `size_of::<CombatState>()` —— 一个战斗实例的 **RAM** 占用（不是 ROM）。
///
/// 这里特意做成 `const`：尺寸探针的 `.text` 只回答"代码多大"，而内存预算是另一半问题，
/// 而且是最容易悄悄超标的那一半。做成常量之后，宿主侧的测试可以直接断言它，
/// 于是"状态模型胖了"会**当场**变成一条红测试，而不是等到上板子才发现。
pub const COMBAT_STATE_BYTES: usize = core::mem::size_of::<rd_core::state::CombatState>();

/// Everything the kernel can currently do, called once from an exported symbol so the linker
/// cannot decide any of it is dead code and drop it.
///
/// ⚠ This is a SIZE probe, not an API. It exists so that adding a module to the kernel without
/// measuring it is impossible; it is expected to grow as the kernel does.
///
/// 覆盖顺序 = 一次真实战斗的必经之路：造状态 → 产生随机序 → 渲染规范文本 → 取指纹。
/// 每一项都必须被"喂进返回值"，否则优化器有权把它整段删掉，测出来的尺寸就是假的。
fn touch_the_kernel(seed: i32, step: i32) -> u32 {
    // rng: a full Fisher-Yates pass.
    let mut indexes = [0u8; 64];
    rd_core::rng::shuffle_indexes(&mut indexes, seed, step);

    // state: build a real (minimal) combat state, so the whole定容 state model is retained.
    // 不用 unwrap()：no_std 下 unwrap 需要错误的 Debug，而且会把 panic 路径的尺寸算进来，
    // 那不是我们要量的东西。
    let combat_id = match rd_core::state::CombatId::new("probe") {
        Ok(v) => v,
        Err(_) => return 0,
    };
    let state = rd_core::state::CombatState::new(combat_id, seed);

    // writer + snapshot: one canonical hash input, the artefact the whole conformance story rests on.
    let mut text = [0u8; 4096];
    {
        let mut w = rd_core::writer::TextWriter::new(&mut text);
        w.str("step=")
            .i32(step)
            .str(" first=")
            .u32(u32::from(indexes[0]))
            .str(" seed=")
            .i32(seed)
            .char('\n');
        if w.overflowed() || w.is_empty() {
            return 0;
        }
    }
    {
        let mut w = rd_core::writer::TextWriter::new(&mut text);
        rd_core::snapshot::write_hash_input(&mut w, &state);
        if w.overflowed() {
            return 0;
        }
    }

    // status_catalog: the tables are `const`/`static`, so touch one entry from each to retain them.
    let mut catalog_acc = 0u32;
    for entry in rd_core::status_catalog::damage_modifiers() {
        catalog_acc = catalog_acc
            .wrapping_mul(31)
            .wrapping_add(entry.percent as u32)
            .wrapping_add(entry.spec_priority as u32);
    }
    for entry in rd_core::status_catalog::block_modifiers() {
        catalog_acc = catalog_acc
            .wrapping_mul(31)
            .wrapping_add(entry.percent as u32)
            .wrapping_add(u32::from(rd_core::status_catalog::stage_rank(
                rd_core::status_catalog::ModifierTarget::Source,
            )));
    }

    // hash: the fingerprint the whole conformance story rests on.
    let text_len = text.iter().position(|&b| b == 0).unwrap_or(text.len());
    let digest = rd_core::hash::sha256(&text[..text_len]);
    let mut hex = [0u8; 64];
    rd_core::hash::to_hex_lower(&mut hex, &digest);

    // Fold everything into the return value so nothing above can be optimised away.
    let mut acc = catalog_acc;
    for b in hex.iter() {
        acc = acc.wrapping_mul(31).wrapping_add(u32::from(*b));
    }
    acc
}

/// Keeps `touch_the_kernel` in the object file.
///
/// `#[used]` makes the compiler emit this static, and the static holds the function's address,
/// so neither can be dropped as dead code.
///
/// Deliberately NOT `#[no_mangle]`: newer Rust treats that as an unsafe attribute, which this
/// crate's `#![forbid(unsafe_code)]` turns into a hard error - and a size probe has no business
/// opting out of the crate's safety rules to get itself linked.
#[used]
static KEEP_ALIVE: fn(i32, i32) -> u32 = touch_the_kernel;

#[cfg(test)]
mod tests {
    use super::*;

    /// 内存预算是 **592 KB**（ESP32-P4 的可用 SRAM）。状态模型单独占掉多少，必须能一眼看到，
    /// 而且超了要**红**，不能只是打印一句了事。
    #[test]
    fn the_state_model_fits_the_sram_budget_and_we_know_its_exact_size() {
        let bytes = COMBAT_STATE_BYTES;
        let sram = 592 * 1024;
        println!(
            "size_of::<CombatState>() = {bytes} B ({} KiB), {:.1}% of {sram} B SRAM",
            bytes / 1024,
            100.0 * bytes as f64 / sram as f64
        );
        // 上限取 192 KiB：留出余量，但足以在"又加了一个定容数组"时立刻报警。
        // 当前实测 171,848 B。这条断言故意贴着实际值，就是为了让下一次增长被看见。
        assert!(
            bytes <= 192 * 1024,
            "一个战斗实例要 {bytes} B，超过 192 KiB 上限 —— 内存预算被吃穿了；\
             降本杠杆按收益排序：id intern（卡池）、marks/counters 降到 2/2（−47 KB）、把 state 放 PSRAM"
        );
    }

    /// 探针本身必须真的能跑通，否则"它测出来的尺寸"没有任何意义。
    #[test]
    fn the_probe_path_returns_something_nonzero() {
        assert_ne!(touch_the_kernel(7, 3), 0);
        assert_ne!(touch_the_kernel(1, 1), 0);
    }
}

