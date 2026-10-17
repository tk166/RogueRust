//! 裸机启动壳 —— **只为把内核链接成一个真实 ELF 镜像**，不是可运行的固件。
//!
//! 为什么需要它：`cargo check --target riscv32imac-unknown-none-elf` 能通过，
//! 静态库也能产出，但这两件事都**不证明这个内核能被链接成一个镜像**。裸机移植最常见的
//! 死法是链接期缺符号（`memcpy` / `memset` / `__aeabi_*` 这类编译器内建函数），
//! 它们在任何"只编译不链接"的验收里都看不见。
//!
//! 这里同样没有真实硬件初始化（时钟、栈指针、向量表、PSRAM 一概没有），
//! 所以这份产物**不能烧进 ESP32-P4**。它回答的是"链得起来吗、gc-sections 之后剩多少"。
//!
//! ── 关于 `forbid(unsafe_code)` ───────────────────────────────────────────────────────────────
//! `rd-core` 保持 `#![forbid(unsafe_code)]`，且这条铁律**没有**在本文件里被放松。
//! 但本 crate 是启动壳，它必须导出一个链接器认得的入口符号；而当前 Rust 把
//! `#[no_mangle]` 归类为 **unsafe 属性**，在 `forbid(unsafe_code)` 下会变成硬错误
//! （`rd-sizeprobe` 里也踩过同一条，那里是靠 `#[used] static` 绕开的）。
//! 所以这个壳**不写** `forbid(unsafe_code)` —— 这是它唯一的让步，且不涉及任何 unsafe 代码块。

#![no_std]
#![no_main]

use core::panic::PanicInfo;

/// 裸机镜像必须自带 panic 处理。真固件这里应当是复位或把现场写进 RTC 保留内存。
#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    loop {
        core::hint::spin_loop();
    }
}

/// 把内核走一遍：造状态 → 渲染规范文本 → 取指纹。
///
/// 与 `rd-sizeprobe::touch_the_kernel` 同一条路径，但这里是被**真实入口**调用的，
/// 所以链接器的 `--gc-sections` 会如实决定哪些代码留下。
fn probe(seed: i32, step: i32) -> u32 {
    let mut indexes = [0u8; 64];
    rd_core::rng::shuffle_indexes(&mut indexes, seed, step);

    let combat_id = match rd_core::state::CombatId::new("fw") {
        Ok(v) => v,
        Err(_) => return 0,
    };
    let state = rd_core::state::CombatState::new(combat_id, seed);

    let mut text = [0u8; 4096];
    {
        let mut w = rd_core::writer::TextWriter::new(&mut text);
        rd_core::snapshot::write_hash_input(&mut w, &state);
        if w.overflowed() {
            return 0;
        }
    }

    let mut catalog = 0u32;
    for entry in rd_core::status_catalog::damage_modifiers() {
        catalog = catalog.wrapping_add(entry.percent as u32);
    }
    for entry in rd_core::status_catalog::block_modifiers() {
        catalog = catalog.wrapping_add(entry.percent as u32);
    }

    let text_len = text.iter().position(|&b| b == 0).unwrap_or(text.len());
    let digest = rd_core::hash::sha256(&text[..text_len]);
    let mut hex = [0u8; 64];
    rd_core::hash::to_hex_lower(&mut hex, &digest);

    let mut acc = catalog.wrapping_add(u32::from(indexes[0]));
    for b in hex.iter() {
        acc = acc.wrapping_mul(31).wrapping_add(u32::from(*b));
    }
    acc
}

/// 链接器的入口点（`link.x` 里的 `ENTRY(_start)`）。
#[no_mangle]
pub extern "C" fn _start() -> ! {
    // black_box 是安全的，且足以让优化器无法把整条调用链删掉。
    let digest = core::hint::black_box(probe(7, 3));
    let _ = digest;
    loop {
        core::hint::spin_loop();
    }
}
