"""独立校验 RDCF 内容二进制 —— 不读编译器的代码，只读它产出的字节。

为什么这么做：`tools/contentc/` 是子代理写的，它自己会说自己对。独立验证的价值在于
**用另一条路径重新解读同一份产物**，并检查它自述的 manifest 与磁盘上的字节是否一致。
走同一条代码路径"验证"是没有意义的。

我能独立验证的（不需要知道格式的语义）：
  * magic / 文件大小 / 段目录能否被解出来
  * 段目录里的 offset/count/bytes 是否与 manifest 自述一致
  * 每一段是否落在文件内、段之间是否重叠
  * count × stride 是否与段字节数自洽（对定长表）
  * 重建后 manifest 是否已过期（文件变了但 manifest 没更新）

我**不能**验证的（需要格式语义，属于另一路工作）：段内编码是否正确、语义是否等价于源 JSON。
那部分应该由编译器的 validate/reader 与 golden 回归来回答。

用法:  C:\\Users\\TK11\\miniforge3\\python.exe rdcf_verify.py
"""
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tools", "contentc", "out")

# 定长表 -> (在 manifest 里声明的 stride 字段, 期望的条目数取处)
# 用来交叉检查 "段字节数 == count × stride"。
STRIDED = {
    "CARD": ("cards", 28),
    "STAT": ("statuses", 36),
    "EACT": ("enemy_actions", 16),
    "ENCT": ("encounters", 20),
    "REL": ("relics", 12),
}


def parse_directory(blob, header_bytes, n_entries):
    """解段目录。

    布局是**实测出来的**，不是从生成器的代码里抄的：按 16 字节步长解会得到
    (272, 76799, 3140, 77072) 而 manifest 说第 0 段是 (offset=272, bytes=76799, count=3140)——
    即条目其实是 **12 字节** 的 (offset, bytes, count)，逐个紧挨着排。
    manifest 的 directory_bytes=240 = 15×12（目录）+ 15×4（另一个数组，本函数不解它）。
    """
    entries = []
    for i in range(n_entries):
        base = header_bytes + i * 12
        if base + 12 > len(blob):
            return entries, False
        off, nbytes, count = struct.unpack_from("<III", blob, base)
        entries.append({"offset": off, "bytes": nbytes, "count": count})
    return entries, True


def check_variant(name, info, failures, notes):
    path = os.path.join(OUT, os.path.basename(info["file"]))
    print(f"\n── 变体 {name}: {os.path.basename(info['file'])} ──")
    if not os.path.exists(path):
        failures.append(f"{name}: 文件不存在 {path}")
        print("   !! 文件不存在")
        return

    with open(path, "rb") as fh:
        blob = fh.read()
    size = len(blob)
    print(f"   磁盘大小 {size:,} B / manifest 自述 {info['bytes']:,} B")
    if size != info["bytes"]:
        failures.append(f"{name}: 文件大小 {size} != manifest {info['bytes']}（manifest 已过期？）")
    print(f"   sha256   {hashlib.sha256(blob).hexdigest()[:32]}…")

    magic = struct.unpack_from("<I", blob, 0)[0]
    magic_ok = magic == 0x46434452
    print(f"   magic    0x{magic:08X} " + ("OK" if magic_ok else "!! 与 manifest 的 0x46434452 不符"))
    if not magic_ok:
        failures.append(f"{name}: magic 不符 0x{magic:08X}")

    version = struct.unpack_from("<H", blob, 4)[0]
    flags = struct.unpack_from("<H", blob, 6)[0]
    print(f"   version  {version}   flags(mf={info.get('flags')}) {flags}")

    declared = info["sections"]
    entries, ok = parse_directory(blob, 32, len(declared))
    if not ok:
        failures.append(f"{name}: 段目录解不出来")
        return

    # 目录解出来了吗？与 manifest 的段一一对齐比较（manifest 的段顺序 = 目录顺序）。
    mismatches = 0
    for d, s in zip(entries, declared):
        if not (d["offset"] == s["offset"] and d["bytes"] == s["bytes"]
                and d["count"] == s["count"]):
            mismatches += 1
    if mismatches == 0:
        print(f"   段目录     独立解出 {len(entries)} 段，offset/bytes/count **与 manifest 逐字段一致**")
    else:
        failures.append(f"{name}: 独立解出的段目录与 manifest 有 {mismatches}/{len(entries)} 段不一致")
        print(f"   !! 段目录   {mismatches}/{len(entries)} 段与 manifest 不一致")
        for d, s in list(zip(entries, declared))[:3]:
            print(f"       raw={d}")
            print(f"       mf ={ {k: s[k] for k in ('offset','bytes','count')} }")

    # 结构不变量：无论目录布局怎么猜，这些都必须成立。
    spans = []
    for s in declared:
        off, nb = s["offset"], s["bytes"]
        if nb == 0:
            continue
        if off < 32 + 240:
            failures.append(f"{name}:{s['name']} offset {off} 落在 header+directory 之内")
        if off + nb > size:
            failures.append(f"{name}:{s['name']} 段末端 {off+nb} 超出文件 {size}")
        spans.append((off, off + nb, s["name"], s["count"], nb))

    spans.sort()
    for (a0, a1, an, _, _), (b0, b1, bn, _, _) in zip(spans, spans[1:]):
        if a1 > b0:
            failures.append(f"{name}: 段 {an} 与 {bn} 重叠 ({a1} > {b0})")

    gaps = sum((b0 - a1) for (a0, a1, _, _, _), (b0, b1, _, _, _) in zip(spans, spans[1:]))
    print(f"   段数       {len(spans)}（其中 {len(declared)-len(spans)} 段为空），段间空隙合计 {gaps} B")

    # 段字节数 + header + directory 与文件大小的关系。
    used = 32 + 240 + sum(s["bytes"] for s in declared)
    print(f"   header32+dir240+段合计 = {used:,} B，文件 {size:,} B，差 {size - used:,} B")

    # 定长表的 count × stride 自洽性。
    # ⚠ 一个"查不到就跳过"的检查比没有检查更糟：它会伪装成通过。所以这里显式统计
    # 真正跑过的检查数，一个都没跑就报出来，而不是安静地什么也不做。
    tables = info.get("tables", {})
    strided_checks = 0
    for s in declared:
        if s["name"] not in STRIDED:
            continue
        key, stride = STRIDED[s["name"]]
        entry = tables.get(key)
        if not isinstance(entry, dict) or "count" not in entry:
            print(f"   ? {s['name']} 段：manifest 里没有 tables.{key}.count，**这项检查未执行**")
            continue
        strided_checks += 1
        declared_count = entry["count"]
        expect = declared_count * stride
        if s["count"] and s["bytes"] < expect:
            failures.append(
                f"{name}:{s['name']} 段 {s['bytes']} B < count {s['count']} × stride {stride} = {expect} B")
            print(f"   !! {s['name']} 段小于 count×stride（{s['bytes']} < {expect}）")
        else:
            extra = s["bytes"] - expect
            print(f"   · {s['name']} 段 {s['bytes']} B = count×stride {expect} B + 额外 {extra} B")
        if s["count"] != declared_count:
            failures.append(f"{name}:{s['name']} 段 count {s['count']} != tables.{key}.count {declared_count}")
    if strided_checks == 0:
        notes.append(f"{name}: 定长表的 count×stride 自洽性检查**一次都没跑成**"
                     "（manifest 的 tables 结构变了？）——这部分覆盖是空的")


def main():
    print("=" * 78)
    print("RDCF 独立校验（只读字节，不读生成它的代码）")
    print("=" * 78)

    mpath = os.path.join(OUT, "manifest.json")
    if not os.path.exists(mpath):
        print(f"!! 找不到 {mpath}")
        return 2
    with open(mpath, encoding="utf-8") as fh:
        mf = json.load(fh)
    print(f"  manifest: format={mf.get('format')} v{mf.get('format_version')} magic={mf.get('magic')}")
    print(f"  源: {mf['source']['raw_bytes']:,} B -> 紧凑 {mf['source']['compact_json_bytes']:,} B"
          f" -> 剥冗余 {mf['source']['compact_json_without_redundant_children']:,} B")

    failures, notes = [], []
    for name, info in mf.get("variants", {}).items():
        check_variant(name, info, failures, notes)

    print("\n" + "=" * 78)
    if notes:
        print("观察（不视为失败）:")
        for n in notes:
            print(f"  · {n}")
    if failures:
        print(f"\n!! 校验失败 {len(failures)} 项:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\n✓ 通过的结构不变量：magic 正确、段都落在文件内、段间无重叠、manifest 与磁盘字节一致、"
          "段目录可被独立解出且与 manifest 逐字段相符。")
    print("  未执行/不在范围内的：")
    print("    · 段内编码是否正确、语义是否等价于源 JSON —— 需由编译器的 reader/validate 回答；")
    print("    · 定长表 count×stride 自洽性 —— 见上方 '?' 行，本次一次都没跑成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
