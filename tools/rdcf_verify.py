"""独立校验 RDCF 内容二进制 —— 不读编译器的代码，只读它产出的字节。

为什么这么做：`tools/contentc/` 是子代理写的，它自己会说自己对。独立验证的价值在于
**用另一条路径重新解读同一份产物**，并检查它自述的 manifest 与磁盘上的字节是否一致。
走同一条代码路径"验证"是没有意义的。

我能独立验证的（不需要知道格式的语义）：
  * magic / 文件大小 / 段目录能否被解出来
  * 段目录里的 offset/count/bytes 是否与 manifest 自述一致
  * 每一段是否落在文件内、段之间是否重叠
  * 5 张定长表（CARD/STAT/EACT/ENCT/REL）的 count × stride 是否与段字节数自洽
  * 重建后 manifest 是否已过期（文件变了但 manifest 没更新）

我**不能**验证的（需要格式语义，属于另一路工作）：段内编码是否正确、语义是否等价于源 JSON。
那部分应该由编译器的 validate/reader 与 golden 回归来回答。

--------------------------------------------------------------------------------
2026-10-19：这个脚本自己腐烂过一次，两处**同时**坏了、并且互相掩盖。修法记在这里，
因为下一次把同样的写法抄回来是很容易的事。

  ① `tables` 在 manifest **顶层**（compile.py:1316），旧代码却写成 `info.get("tables")`
     —— `info` 是 `mf["variants"][name]`，那里根本没有 `tables`。结果是 5 张表的
     count×stride 检查**一次都没跑成**，而脚本只记一条"观察"，照旧 exit 0。
     现在：读顶层；并且**查不到就是失败**（"查不到就跳过"的检查比没有检查更糟，
     它会伪装成通过）。
  ② 旧代码在这里抄了一份 stride 常量 28/36/16/20/12，其中 **3 个错**
     （CARD 28→32、STAT 36→40、ENCT 20→16；EACT 16 与 REL 12 恰好是对的）。
     抄常量正是腐烂的根源，所以现在 `from rdcfmt import row_stride` —— 常量只允许有
     一个出处（`tools/contentc/rdcfmt.py` 的 ROW_SCHEMAS）。只修 ① 不修 ② 会立刻假红：
     ENCT 1744 B < 109×20。
     ⚠ 注意段名与 schema 名不同：段叫 `STAT`，schema 叫 `STATUS`；`row_stride()` 吃的是后者。

独立性没有因此丢失：count 与 bytes 来自"manifest 自述"与"我自己从字节里解出来的段目录"，
stride 是**格式定义**（schema 有几个 u16 槽）而不是编码器行为，不属于"相信生成器"的范畴。

用法:  C:\\Users\\TK11\\miniforge3\\python.exe rdcf_verify.py [manifest.json]
       （参数省略时用 tools/contentc/out/manifest.json；给参数是为了能做变异测试：
        喂它一份手改过的 manifest 副本，确认它真的会红。）
       设 PYTHONIOENCODING=utf-8，否则本机 PowerShell 会把中文输出解码成乱码。
"""
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "tools", "contentc", "out")
CONTENTC = os.path.join(HERE, "contentc")

# stride 只有一个出处：格式定义本身。**不要**在这里再抄一份常量。
sys.path.insert(0, CONTENTC)
try:
    from rdcfmt import row_stride, ROW_SCHEMAS
    # §184: the term-table walker lives in its own file -- it parses TRM/TRW/OPD/OPF independently of
    # `contentc/reader.py`, and it shares nothing with the compiler but the format constants above.
    from rdcf_terms import check_terms
except Exception as exc:                                  # pragma: no cover
    print(f"!! 无法从 {os.path.join(CONTENTC, 'rdcfmt.py')} 导入 row_stride: {exc}")
    print("   前缺失 ⇒ 定长表检查无法执行，本脚本不作判定（退出码 2，不等于通过）。")
    sys.exit(2)

# 段名 -> (manifest 顶层 tables 里的键, row_stride 用的 schema 名)
# 用来交叉检查 "段字节数 == count × stride"。
#
# §167：这里原来是**五**张（漏了 EV / POT），而 `rdcfmt.ROW_SCHEMAS` 有七张、`manifest.tables`
# 也一直写着 `events` / `potions`。于是 "5/5 tables" 是一句关于**残缺清单**的真话 ——
# 全绿的闸门只覆盖了它自己列出来的那部分。下面的 `assert_strided_is_complete()` 让"再漏一张"
# 变成响亮失败。
STRIDED = {
    "CARD": ("cards", "CARD"),
    "STAT": ("statuses", "STATUS"),
    "EACT": ("enemy_actions", "EACT"),
    "ENCT": ("encounters", "ENCT"),
    "REL": ("relics", "REL"),
    "EV": ("events", "EV"),
    "POT": ("potions", "POT"),
}


def assert_strided_is_complete():
    """清单必须与 `ROW_SCHEMAS` 一样宽 —— 数量不等就退，而不是少查几张。

    只比**数量**是不够的，所以两边的名字一起打印：名字对不上时人一眼能看出来，而数量相等
    这件事是脚本能判的。清单里多一个 `ROW_SCHEMAS` 没有的名字同样算错（`row_stride` 会 KeyError）。
    """
    schemas = set(ROW_SCHEMAS)
    listed = {schema for _, schema in STRIDED.values()}
    if len(STRIDED) != len(schemas) or listed != schemas:
        print("!! 定长表清单与 rdcfmt.ROW_SCHEMAS 不一致：")
        print(f"   清单 {len(STRIDED)} 张：{sorted(listed)}")
        print(f"   格式 {len(schemas)} 张：{sorted(schemas)}")
        print("   闸门不判通过（退出码 2）—— 少查一张表等于这条闸门从没覆盖过它。")
        sys.exit(2)
    print(f"   定长表 {len(STRIDED)} 张（{', '.join(sorted(listed))}）")


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


def check_strided_tables(name, declared, tables, failures):
    """5 张定长表：段字节数 == count × row_stride()，且段 count == manifest 的行数。

    返回 (真正跑成的检查项数, 覆盖的表行数)。跑成 0 项由调用方报失败。
    """
    ran = 0
    rows = 0
    for s in declared:
        if s["name"] not in STRIDED:
            continue
        key, schema = STRIDED[s["name"]]
        stride = row_stride(schema)                 # 唯一出处，见模块文档 ②
        entry = tables.get(key) if isinstance(tables, dict) else None
        if not isinstance(entry, dict) or "count" not in entry:
            # 不许静默跳过：manifest 结构一变，这项覆盖就悄悄变空 —— 这正是上次腐烂的形状。
            failures.append(
                f"{name}:{s['name']} 段：manifest 顶层没有 tables.{key}.count ⇒ "
                f"这张表的 count×stride 自洽检查**无法执行**（不许静默跳过）")
            print(f"   !! {s['name']} 段：manifest 顶层缺 tables.{key}.count，检查无法执行")
            continue

        ran += 1
        declared_count = entry["count"]
        rows += declared_count
        expect = declared_count * stride
        mf_stride = entry.get("stride")
        print(f"   · {s['name']} 段 {s['bytes']:,} B / {declared_count} 行 × stride {stride} B"
              f"（期待 {expect:,} B；manifest 自述 count={declared_count}"
              f" stride={mf_stride}）")
        if s["count"] != declared_count:
            failures.append(
                f"{name}:{s['name']} 段 count {s['count']} != tables.{key}.count {declared_count}")
        if mf_stride is not None and mf_stride != stride:
            failures.append(
                f"{name}:tables.{key}.stride {mf_stride} != rdcfmt.row_stride('{schema}') {stride}"
                f" —— manifest 与格式定义已经不一致")
        if s["bytes"] != expect:
            # 编译器逐行写 raw + 补零到 stride（compile.py:608-615），所以一个字节都不许余。
            kind = "小于" if s["bytes"] < expect else "大于"
            failures.append(
                f"{name}:{s['name']} 段 {s['bytes']} B {kind} {declared_count} 行 × stride {stride}"
                f" = {expect} B（差 {s['bytes'] - expect:+d} B）")
            print(f"   !! {s['name']} 段字节数 {kind} count×stride：{s['bytes']} vs {expect}")
    return ran, rows


def check_variant(name, info, tables, failures, image_dir=None):
    """校验一个变体。返回 (定长表检查项数, 定长表覆盖行数, term 检查项数, term 条数)。"""
    # §184: the image directory follows the manifest that was passed in. Hard-coding `OUT` meant a
    # negative-control build (a scratch copy, see `native/negctl_184.py`) could not be verified at
    # all -- the script would report "file does not exist" for images it was never told to look at.
    path = os.path.join(image_dir or OUT, os.path.basename(info["file"]))
    print(f"\n── 变体 {name}: {os.path.basename(info['file'])} ──")
    if not os.path.exists(path):
        failures.append(f"{name}: 文件不存在 {path}")
        print("   !! 文件不存在")
        return 0, 0, 0, 0

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
        return 0, 0, 0, 0

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

    # 定长表的 count × stride 自洽性（tables 从 manifest **顶层**取，见模块文档 ①）。
    ran, rows = check_strided_tables(name, declared, tables, failures)
    if ran == 0:
        failures.append(f"{name}: 定长表的 count×stride 自洽性检查**一次都没跑成**"
                        "（manifest 顶层的 tables 结构变了？）—— 这部分覆盖是空的")
    else:
        print(f"   定长表     {ran}/{len(STRIDED)} 张表跑成 count×stride 检查，覆盖 {rows} 行")

    # §184: 段内**形状**（不是语义）。`_json` 是编译器的"源文档装不下"逃生口，存在即错。
    term_ran, terms = check_terms(blob, 32, len(declared), failures)
    print(f"   term 表    {terms:,} 条记录，{term_ran} 项形状检查"
          f"（`_json` 计数 + term 槽边界）")
    if term_ran == 0:
        failures.append(f"{name}: term 表检查**一次都没跑成** —— 这部分覆盖是空的")
    return ran, rows, term_ran, terms


def main(argv):
    print("=" * 78)
    print("RDCF 独立校验（只读字节，不读生成它的代码）")
    print("=" * 78)

    mpath = argv[1] if len(argv) > 1 else os.path.join(OUT, "manifest.json")
    mpath = os.path.abspath(mpath)
    if not os.path.exists(mpath):
        print(f"!! 找不到 {mpath}")
        return 2
    with open(mpath, encoding="utf-8") as fh:
        mf = json.load(fh)
    print(f"  manifest: {mpath}")
    print(f"  format={mf.get('format')} v{mf.get('format_version')} magic={mf.get('magic')}")
    print(f"  源: {mf['source']['raw_bytes']:,} B -> 紧凑 {mf['source']['compact_json_bytes']:,} B"
          f" -> 剥冗余 {mf['source']['compact_json_without_redundant_children']:,} B")

    failures = []
    tables = mf.get("tables")
    if tables is not None:
        assert_strided_is_complete()
    if not isinstance(tables, dict):
        failures.append("manifest 顶层没有 tables 段 —— 5 张定长表的 count×stride 检查无法执行"
                        "（不许静默跳过）")
        tables = {}

    print("\n  本次会检查的定长表（stride 来自 rdcfmt.row_stride，不是抄来的常量）：")
    for sname, (key, schema) in STRIDED.items():
        print(f"    {sname:<5} 段 <- tables.{key} 行数 × stride {row_stride(schema)} B"
              f"  (schema {schema}: {len(ROW_SCHEMAS[schema])} 个 u16 槽)")

    total_ran, total_rows, nvar = 0, 0, 0
    total_term_ran = 0
    total_terms = 0
    for name, info in mf.get("variants", {}).items():
        ran, rows, term_ran, terms = check_variant(
            name, info, tables, failures, os.path.dirname(mpath))
        total_ran += ran
        total_rows += rows
        total_term_ran += term_ran
        total_terms += terms
        nvar += 1

    print("\n" + "=" * 78)
    if failures:
        print(f"!! 校验失败 {len(failures)} 项:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"RDCF_VERIFY PASS ({nvar}/{len(mf.get('variants', {}))} variants, "
          f"{len(STRIDED)}/{len(STRIDED)} tables, {total_ran} count×stride checks, "
          f"{total_rows} table rows, {total_term_ran} term-shape checks over "
          f"{total_terms:,} terms)")
    print("\n✓ 通过的结构不变量：magic 正确、段都落在文件内、段间无重叠、manifest 与磁盘字节一致、"
          "段目录可被独立解出且与 manifest 逐字段相符、7 张定长表的段字节数恰为 行数 × stride。")
    print("  不在范围内的：段内编码是否正确、语义是否等价于源 JSON —— 需由编译器的 reader/validate 回答。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
