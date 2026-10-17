"""列出 PE 动态库的导出符号 —— 直接解析导出表，不猜名字、不依赖任何工具。

为什么需要：NativeAOT 编出来的 dll 的 C ABI 就是 RL 集成面。用"猜名字然后 getattr"的方式
验证它是不可靠的 —— 猜不到不等于不存在，猜中一个也不等于没有别的。导出表就在文件里，
读它就是了。

用法:  C:\\Users\\TK11\\miniforge3\\python.exe pe_exports.py [dll路径 ...]
       不带参数则扫描 native/ 下所有已发布的 dll。
"""
import glob
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def rva_to_offset(sections, rva):
    for va, vsize, raw_off, raw_size in sections:
        if va <= rva < va + max(vsize, raw_size):
            return raw_off + (rva - va)
    return None


def exports_of(path):
    with open(path, "rb") as fh:
        blob = fh.read()

    if blob[:2] != b"MZ":
        return None, "not a PE (no MZ)"
    (e_lfanew,) = struct.unpack_from("<I", blob, 0x3C)
    if blob[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        return None, "no PE signature"

    coff = e_lfanew + 4
    (machine, n_sections, _ts, _psym, _nsym, size_opt) = struct.unpack_from("<HHIIIH", blob, coff)
    opt = coff + 20
    (magic,) = struct.unpack_from("<H", blob, opt)
    is_pe32_plus = magic == 0x20B

    # DataDirectory[0] = export table. Its offset inside the optional header differs by format.
    dd = opt + (112 if is_pe32_plus else 96)
    (exp_rva, exp_size) = struct.unpack_from("<II", blob, dd)
    if exp_rva == 0:
        return [], "no export directory"

    sec_off = opt + size_opt
    sections = []
    for i in range(n_sections):
        base = sec_off + i * 40
        _name = blob[base:base + 8].rstrip(b"\x00")
        vsize, va, raw_size, raw_off = struct.unpack_from("<IIII", blob, base + 8)
        sections.append((va, vsize, raw_off, raw_size))

    eo = rva_to_offset(sections, exp_rva)
    if eo is None:
        return None, "export RVA not mapped"
    n_names = struct.unpack_from("<I", blob, eo + 24)[0]
    names_rva = struct.unpack_from("<I", blob, eo + 32)[0]
    no = rva_to_offset(sections, names_rva)
    if no is None:
        return None, "name table not mapped"

    out = []
    for i in range(n_names):
        (nm_rva,) = struct.unpack_from("<I", blob, no + i * 4)
        p = rva_to_offset(sections, nm_rva)
        if p is None:
            continue
        end = blob.find(b"\x00", p)
        out.append(blob[p:end].decode("ascii", "replace"))
    return out, f"PE32{'+' if is_pe32_plus else ''}, machine 0x{machine:04X}, {n_sections} sections"


def main():
    targets = sys.argv[1:]
    if not targets:
        targets = glob.glob(os.path.join(ROOT, "native", "*", "bin", "*", "Release",
                                         "net10.0", "win-x64", "publish", "*.dll"))
    if not targets:
        print("!! 没找到 dll")
        return 2

    for path in sorted(targets):
        print("=" * 78)
        print(os.path.basename(path))
        print("=" * 78)
        names, note = exports_of(path)
        if names is None:
            print(f"  !! {note}")
            continue
        print(f"  {note}；导出 {len(names)} 个符号\n")
        for n in names:
            print(f"    {n}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
