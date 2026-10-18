"""Measures the kernel's RISC-V code size, without any binutils for the target.

Why a hand-rolled parser: there is no riscv objdump/size on this machine, and installing a
cross toolchain to read two numbers out of an object file is not a good trade. `ar` archives
and ELF32 section headers are simple enough to read directly, and this way the measurement has
no dependencies at all.

What it answers: "the kernel must run on an ESP32-P4 with 592 KB of usable SRAM" - so how many
bytes of code does it actually cost today? Those numbers have to be produced by a command, not
believed.

Usage:  C:\\Users\\TK11\\miniforge3\\python.exe size_probe.py
"""
import glob
import os
import time
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TARGET = "riscv32imac-unknown-none-elf"
ART_DIR = os.path.join(ROOT, "kernel", "target", TARGET, "release")
CARGO = os.path.join(HERE, "cargo.ps1")

SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4
SHT_PROGBITS = 1
SHT_NOBITS = 8


def parse_ar(blob):
    """Yields (member_name, member_bytes) for a GNU `ar` archive."""
    if not blob.startswith(b"!<arch>\n"):
        raise ValueError("not an ar archive")
    off = 8
    long_names = b""
    while off + 60 <= len(blob):
        hdr = blob[off:off + 60]
        name = hdr[0:16].decode("ascii", "replace").strip()
        try:
            size = int(hdr[48:58].decode("ascii").strip())
        except ValueError:
            break
        data = blob[off + 60:off + 60 + size]
        off += 60 + size + (size & 1)  # members are padded to an even boundary

        if name == "//":
            long_names = data
            continue
        if name in ("/", "/SYM64/"):
            continue
        if name.startswith("/") and long_names:
            # GNU long-name reference: /<offset> into the // table, terminated by '/\n'
            idx = int(name[1:].rstrip("/") or "0")
            end = long_names.find(b"/\n", idx)
            name = long_names[idx:end].decode("ascii", "replace")
        yield name, data


def elf_sections(obj):
    """Returns [(name, flags, sh_type, size)] for an ELF32 little-endian object."""
    if obj[:4] != b"\x7fELF":
        return []
    if obj[4] != 1:  # EI_CLASS: 1 = 32-bit. RISC-V bare targets are ELF32.
        return []
    (e_shoff,) = struct.unpack_from("<I", obj, 0x20)
    (e_shentsize,) = struct.unpack_from("<H", obj, 0x2E)
    (e_shnum,) = struct.unpack_from("<H", obj, 0x30)
    (e_shstrndx,) = struct.unpack_from("<H", obj, 0x32)
    if e_shoff == 0 or e_shnum == 0:
        return []

    raw = []
    for i in range(e_shnum):
        base = e_shoff + i * e_shentsize
        name_off, sh_type, sh_flags, _addr, _off, sh_size = struct.unpack_from("<IIIIII", obj, base)
        raw.append((name_off, sh_type, sh_flags, sh_size))

    # Resolve names through the section-header string table.
    names = b""
    if e_shstrndx < len(raw):
        base = e_shoff + e_shstrndx * e_shentsize
        _n, _t, _f, _a, stroff, strsize = struct.unpack_from("<IIIIII", obj, base)
        names = obj[stroff:stroff + strsize]

    out = []
    for name_off, sh_type, sh_flags, sh_size in raw:
        end = names.find(b"\x00", name_off)
        nm = names[name_off:end].decode("ascii", "replace") if names else f"<{name_off}>"
        out.append((nm, sh_flags, sh_type, sh_size))
    return out


def newest_source_mtime():
    """kernel/*/src 下最新的源文件 mtime（含 Cargo.toml）。"""
    newest, newest_path = 0.0, None
    for pattern in ("*/src/**/*.rs", "*/Cargo.toml", "Cargo.toml"):
        for path in glob.glob(os.path.join(ROOT, "kernel", pattern), recursive=True):
            m = os.path.getmtime(path)
            if m > newest:
                newest, newest_path = m, path
    return newest, newest_path


def main():
    print("=" * 78)
    print("内核代码尺寸（裸机 RISC-V, riscv32imac-unknown-none-elf）")
    print("=" * 78)

    libs = glob.glob(os.path.join(ART_DIR, "*.a"))
    if not libs:
        print(f"\n!! 找不到静态库，先在 {ART_DIR}")
        print("   请先运行: tools/cargo.ps1 build --release --target "
              f"{TARGET} -p rd-sizeprobe")
        return 1

    # 陈旧检查。这一段是踩出来的：本脚本**只读归档、不构建**，所以源码改了而没重新 build 时，
    # 它会把上一次的数字当成当前结果打印出来 —— 一声不吭。一个会报陈旧数字的度量工具，
    # 比没有工具更糟：它让人以为"改了这么多，尺寸没变，好得很"。
    # 实测踩过：改完 rd-sizeprobe/src/lib.rs（加了整个状态模型 + 序列化器 + 状态表）之后，
    # 这里仍然报 4,616 B —— 和改动前逐字节相同。
    newest_src, newest_path = newest_source_mtime()
    newest_lib = max(os.path.getmtime(p) for p in libs)
    if newest_src > newest_lib:
        rel = os.path.relpath(newest_path, ROOT)
        print(f"\n!! 产物是陈旧的，拒绝报数。")
        print(f"   归档   最后生成于 {time.strftime('%H:%M:%S', time.localtime(newest_lib))}")
        print(f"   但源码 {rel} 改于 {time.strftime('%H:%M:%S', time.localtime(newest_src))}")
        print(f"   请先重新构建: tools/cargo.ps1 build --release --target {TARGET} -p rd-sizeprobe")
        return 1

    print(f"\n  产物: {', '.join(os.path.basename(p) for p in libs)}")
    print(f"  新鲜度: 归档 {time.strftime('%H:%M:%S', time.localtime(newest_lib))} "
          f">= 最新源码 {time.strftime('%H:%M:%S', time.localtime(newest_src))}  ✓")

    # ⚠ A staticlib ARCHIVE IS NOT A LINKED IMAGE. It holds every object file of every
    # dependency, and `core` is a dependency of a no_std crate - so summing the whole archive
    # reports something like 231 KB that has almost nothing to do with this kernel. What is
    # meaningful without a final link is the split: what the kernel crates compiled to, versus
    # the vendored `core`/`compiler_builtins` floor that a real link would mostly garbage-collect.
    KERNEL_CRATES = ("rd_core", "rd_sizeprobe")

    by_crate = {}       # crate -> {"code": n, "ro": n, "bss": n, "objs": n}
    for lib in libs:
        with open(lib, "rb") as fh:
            blob = fh.read()
        for name, data in parse_ar(blob):
            if not data.startswith(b"\x7fELF"):
                continue
            member = name.replace("\\", "/").split("/")[-1]
            crate = next((c for c in KERNEL_CRATES if c in member), None)
            if crate is None:
                crate = "compiler_builtins" if "compiler_builtins" in member else "core/std"
            bucket = by_crate.setdefault(crate, {"code": 0, "ro": 0, "bss": 0, "objs": 0})
            bucket["objs"] += 1
            for _nm, flags, sh_type, size in elf_sections(data):
                if size == 0:
                    continue
                if sh_type == SHT_NOBITS:
                    if flags & SHF_ALLOC:
                        bucket["bss"] += size
                    continue
                if not (flags & SHF_ALLOC):
                    continue
                if flags & SHF_EXECINSTR:
                    bucket["code"] += size
                elif sh_type == SHT_PROGBITS:
                    bucket["ro"] += size

    if not by_crate:
        print("  !! 归档里没有 ELF 目标文件（可能构建的是 host 目标）")
        return 1

    print(f"\n  {'crate':<22}{'目标文件':>8}{'.text':>10}{'.rodata':>10}{'.bss':>8}")
    print("  " + "-" * 58)
    for crate in sorted(by_crate, key=lambda c: -by_crate[c]["code"]):
        b = by_crate[crate]
        print(f"  {crate:<22}{b['objs']:>8}{b['code']:>10,}{b['ro']:>10,}{b['bss']:>8,}")

    kernel = sum(by_crate[c]["code"] for c in KERNEL_CRATES if c in by_crate)
    kernel_ro = sum(by_crate[c]["ro"] for c in KERNEL_CRATES if c in by_crate)
    kernel_bss = sum(by_crate[c]["bss"] for c in KERNEL_CRATES if c in by_crate)
    floor = sum(b["code"] for c, b in by_crate.items() if c not in KERNEL_CRATES)

    print("\n  —— 内核自身（状态模型 + 序列化器 + 状态表 + rng + sha256 + 规范写入器）——")
    print("  ⚠ release profile 开了 LTO，rd-core 没有独立目标文件：它的代码已被内联进")
    print("     rd_sizeprobe 的对象里，所以下面这一行就是「内核 + probe」的真实合计。")
    print(f"  .text        {kernel:>10,} B")
    print(f"  .rodata      {kernel_ro:>10,} B")
    print(f"  .bss         {kernel_bss:>10,} B")

    # ── flash 与 SRAM 是两笔不同的账，绝不能相加成一个"占 SRAM 多少" ────────────────────────
    #
    # 这一段是踩出来的：旧版把 `.text + .rodata + .bss` 加在一起，然后报"占可用 SRAM 的 32.27%"。
    # **那是错的**。ESP32-P4 上 `.text` 与 `.rodata` 放在**闪存**里，不消耗 SRAM；
    # 真正吃 SRAM 的是 `.data` + `.bss` + 栈 + 堆。把三者相加再对 SRAM 取比例，
    # 会让人以为"内存快满了"，而实际上一个字节的 SRAM 都还没用。
    # 一个把 flash 和 RAM 混起来的预算工具，比没有工具更糟。
    print("\n  —— 两笔不同的账（ESP32-P4 上 .text/.rodata 在**闪存**，不吃 SRAM）——")
    print(f"  闪存占用（代码 + 只读数据）  : {kernel + kernel_ro:>10,} B"
          f"   （闪存 16 MB，占比可忽略）")
    print(f"  SRAM 静态占用（.data+.bss）  : {kernel_bss:>10,} B")
    print("  ⚠ 上面这块 **不含** 一个战斗实例的内存：`size_of::<CombatState>()` 是要单列的，")
    print("     它随实例走（栈或堆），见 rd-sizeprobe 的 the_state_model_fits_the_sram_budget 测试。")

    print(f"\n  ⚠ `.rodata` 被一个坑放大了：`.text` 里若出现 `CombatState::new(...)` 这种构造，")
    print(f"     LLVM 会把那个 168 KB 聚合体的**初始化模板**放进 `.rodata`。")
    print(f"     实测 A/B：去掉构造后 `.rodata` 从 173,313 B 掉回 598 B，`.text` 从 22,304 掉到 4,744。")
    print(f"     也就是说这 168 KB 是**代码生成产物**，不是数据 —— 但真固件若也这么初始化，就同样要付。")
    print("     归因方法与数字见 docs/port-plan.md §26。")

    print(f"\n  ⚠ 归档里另有 {floor:,} B 来自 vendored `core`（未链接，真链接后大部分会被 --gc-sections 回收）。")
    print("     要得到真实固件占用，需要一个最终链接（链接脚本 + 内存布局），属于 W4 的工作。")
    print(f"\n  参考：内容表 core 版 85,616 B（应放**闪存**，不是 SRAM）")
    # 这里原来写着"一个战斗实例 171,848 B = 28.3%"，而真实值已经是 184,648 B —— 一句
    # 抄了第二份的数字，静静过期了一年。数字的**唯一出处**是 rd-core 的
    # `state_fits_the_sram_plan`（每次 `cargo test` 都打印实测值，并断言 ≤192 KiB），
    # rd-sizeprobe 的 `COMBAT_STATE_BYTES` 是同一个常量。所以这里不再抄数字，只指路。
    print("  参考：一个战斗实例的 SRAM 占用 = size_of::<CombatState>()，**唯一出处**是")
    print("     kernel/rd-core/src/state.rs 的 `state_fits_the_sram_plan`（打印实测值），")
    print("     以及 kernel/rd-sizeprobe 的 COMBAT_STATE_BYTES。本脚本不再复制这个数。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
