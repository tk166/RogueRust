"""量一个**已链接**的裸机 ELF：真实保留了多少、占 flash 多少、占 SRAM 多少。

## 为什么需要它（和 size_probe.py 的分工）

`size_probe.py` 量的是一个**静态库归档**，那是"编译产物"，不是"最终镜像"：
归档里躺着 `core` / `compiler_builtins` 的几百个目标文件，链接时大部分会被
`--gc-sections` 回收。所以归档的数字是**上界**，不是占用。

本工具量的是 `cargo rustc … -C link-arg=-Tlink.x` 产出的**真实 ELF**，答案是最终数字。

## 两条从上一轮学来的教训，这里当场就用上

1. **陈旧就拒绝报数**（`size_probe.py` 曾把一小时前的旧数字当成当前结果打印，一声不吭）。
2. **flash 与 SRAM 是两笔账，不许相加**（`.text`/`.rodata` 在闪存；只有 `.data`/`.bss` 吃 SRAM。
   上一版把三者相加报"占 SRAM 32%"，而实际上一个字节 SRAM 都还没用）。

用法：
  python tools\\firmware_size.py [--elf <path>] [--top N]
"""
from __future__ import annotations

import argparse
import glob
import os
import struct
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FW_DIR = os.path.join(ROOT, "kernel", "rd-firmware")
DEFAULT_ELF_GLOB = os.path.join(FW_DIR, "target", "riscv32imac-unknown-none-elf",
                                "release", "rd-firmware*")

SHF_WRITE = 0x1
SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4
SHT_NOBITS = 8
SHT_SYMTAB = 2

# ESP32-P4：可用 SRAM 见 docs/esp32-p4-hardware-facts.md（实测 boot log 的 min free heap）。
P4_SRAM_BYTES = 606208


def read_elf32(path):
    with open(path, "rb") as fh:
        blob = fh.read()
    if blob[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    if blob[4] != 1:
        raise ValueError("not ELF32")
    if blob[5] != 1:
        raise ValueError("not little-endian")
    e_shoff, = struct.unpack_from("<I", blob, 0x20)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", blob, 0x2E)
    if e_shoff == 0 or e_shnum == 0:
        raise ValueError("no section headers")

    raw = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        (name, sh_type, flags, addr, sh_off, size, link, info,
         align, entsize) = struct.unpack_from("<IIIIIIIIII", blob, off)
        raw.append(dict(name_off=name, type=sh_type, flags=flags, addr=addr,
                        offset=sh_off, size=size, link=link, entsize=entsize))

    strtab_off = raw[e_shstrndx]["offset"]
    for s in raw:
        end = blob.index(b"\x00", strtab_off + s["name_off"])
        s["name"] = blob[strtab_off + s["name_off"]:end].decode("ascii", "replace")

    # 符号表：用来回答"到底是哪些函数占了这些字节"。
    symbols = []
    for s in raw:
        if s["type"] != SHT_SYMTAB or s["entsize"] == 0:
            continue
        sym_str_off = raw[s["link"]]["offset"]
        for i in range(s["size"] // s["entsize"]):
            off = s["offset"] + i * s["entsize"]
            st_name, st_value, st_size, st_info, st_other, st_shndx = \
                struct.unpack_from("<IIIBBH", blob, off)
            if st_size == 0 or st_shndx == 0:
                continue
            end = blob.index(b"\x00", sym_str_off + st_name)
            symbols.append(dict(
                name=blob[sym_str_off + st_name:end].decode("ascii", "replace"),
                size=st_size, value=st_value, shndx=st_shndx,
                typ=st_info & 0xF))
    return raw, symbols


def newest_source_mtime():
    newest, path = 0.0, None
    for pat in ("*/src/**/*.rs", "*/Cargo.toml", "Cargo.toml", "*/link.x"):
        for p in glob.glob(os.path.join(ROOT, "kernel", pat), recursive=True):
            m = os.path.getmtime(p)
            if m > newest:
                newest, path = m, p
    return newest, path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default=None)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--allow-stale", action="store_true")
    args = ap.parse_args()

    print("=" * 78)
    print("裸机固件镜像占用（已链接的 ELF，riscv32imac-unknown-none-elf）")
    print("=" * 78)

    path = args.elf
    if path is None:
        cands = [p for p in glob.glob(DEFAULT_ELF_GLOB) if os.path.isfile(p)
                 and not p.endswith(".d")]
        if not cands:
            print(f"\n!! 找不到 ELF（{DEFAULT_ELF_GLOB}）")
            print("   请先链接：")
            print("   tools\\cargo.ps1 rustc --release --target riscv32imac-unknown-none-elf"
                  " --manifest-path rd-firmware/Cargo.toml -- "
                  f"-C link-arg=-T{os.path.join(FW_DIR, 'link.x')}")
            return 1
        path = max(cands, key=os.path.getmtime)

    # 教训 1：只读产物的工具必须先证明产物是新鲜的。
    elf_mtime = os.path.getmtime(path)
    src_mtime, src_path = newest_source_mtime()
    if src_mtime > elf_mtime and not args.allow_stale:
        print(f"\n!! 镜像可能陈旧，拒绝报数（要强制就用 --allow-stale）。")
        print(f"   ELF    生成于 {time.strftime('%H:%M:%S', time.localtime(elf_mtime))}")
        print(f"   源码 {os.path.relpath(src_path, ROOT)} 改于 "
              f"{time.strftime('%H:%M:%S', time.localtime(src_mtime))}")
        return 1

    sections, symbols = read_elf32(path)
    print(f"\n  镜像: {os.path.relpath(path, ROOT)}")
    print(f"  大小: {os.path.getsize(path):,} B   生成于 "
          f"{time.strftime('%H:%M:%S', time.localtime(elf_mtime))}")

    print(f"\n  {'段':<22}{'地址':>12}{'大小':>12}  属性")
    print("  " + "-" * 62)
    flash = 0      # 需要待在非易失存储里的
    ram = 0        # 需要待在 RAM 里的
    for s in sorted(sections, key=lambda x: x["addr"]):
        if s["name"] in ("", ".shstrtab", ".symtab", ".strtab") or s["size"] == 0:
            continue
        if not (s["flags"] & SHF_ALLOC):
            continue
        attrs = []
        if s["flags"] & SHF_EXECINSTR:
            attrs.append("code")
        if s["flags"] & SHF_WRITE:
            attrs.append("writable")
        if s["type"] == SHT_NOBITS:
            attrs.append("nobits")
        print(f"  {s['name']:<22}0x{s['addr']:08X}{s['size']:>12,}  {' '.join(attrs)}")
        if s["type"] == SHT_NOBITS:
            ram += s["size"]                     # .bss：不占 flash，占 RAM
        elif s["flags"] & SHF_WRITE:
            flash += s["size"]                   # .data：初值在 flash，运行时拷进 RAM
            ram += s["size"]
        else:
            flash += s["size"]                   # .text/.rodata

    # 教训 2：两笔账分开报，绝不相加成一个"占 SRAM 多少"。
    print(f"\n  ── 两笔不同的账 ──")
    print(f"  非易失存储（.text + .rodata + .data 初值）: {flash:>10,} B")
    print(f"  RAM 静态占用（.data + .bss）              : {ram:>10,} B"
          f"   （ESP32-P4 可用 SRAM {P4_SRAM_BYTES:,} B 的 {100.0 * ram / P4_SRAM_BYTES:.2f}%）")
    print(f"  ⚠ 上面**不含**一个战斗实例：`size_of::<CombatState>()` = 171,848 B，随实例走")
    print(f"     （栈或堆），是真实 SRAM 占用的主要来源。固件若开 N 个战斗，要按 N 倍算。")

    if symbols and args.top > 0:
        sym_shndx = {i: s["name"] for i, s in enumerate(sections)}
        biggest = sorted(symbols, key=lambda x: -x["size"])[:args.top]
        print(f"\n  ── 最大的 {args.top} 个符号（回答「到底是谁占的」）──")
        print(f"  {'大小':>10}  {'段':<14} 名字")
        print("  " + "-" * 62)
        for s in biggest:
            print(f"  {s['size']:>10,}  {sym_shndx.get(s['shndx'], '?'):<14} {s['name']}")

    print(f"\n  ⚠ 这不是可启动镜像：link.x 里用 0 占位地址（没有真实 P4 内存映射），")
    print(f"     也没有 bootloader 头与时钟/栈指针/PSRAM 初始化。见 kernel/rd-firmware/link.x 顶部。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
