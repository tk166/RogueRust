"""可移植性体检：这个引擎若要搬到 C / Rust / 嵌入式，成本在哪。

只读，不改参考仓库。三个问题：
  1. 数值类型：战斗数学用 float/double 还是定点整数？（决定嵌入式可行性）
  2. 有没有反射 / LINQ / 字符串字典 / 动态分配这些"搬不动"的东西？
  3. 内容文档 8.29 MB 的结构是什么？（决定"内容预编译成二进制表"的工作量）
"""
import json
import os
import re
from collections import Counter, defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RogueDeck-Core")
SRC = os.path.join(ROOT, "src")

PATTERNS = {
    # 数值
    r"\bfloat\b": "float（嵌入式需确认是否有 FPU/是否用定点）",
    r"\bdouble\b": "double",
    r"\bdecimal\b": "decimal（嵌入式基本别想）",
    r"Math\.": "Math.*",
    r"MathF\.": "MathF.*",
    # 语言特性：越"高级"越难搬
    r"using System\.Linq": "LINQ",
    r"\.Where\(": ".Where()",
    r"\.Select\(": ".Select()",
    r"\.OrderBy": ".OrderBy",
    r"\.ToDictionary\(": ".ToDictionary",
    r"System\.Reflection": "反射",
    r"\btypeof\(": "typeof",
    r"\bActivator\.": "Activator",
    r"\bdynamic\b": "dynamic",
    r"\bunsafe\b": "unsafe",
    r"stackalloc": "stackalloc",
    r"Span<": "Span<>",
    r"ReadOnlySpan<": "ReadOnlySpan<>",
    # 分配
    r"new List<": "new List<>",
    r"new Dictionary<": "new Dictionary<>",
    r"new HashSet<": "new HashSet<>",
    r"Dictionary<string": "Dictionary<string,...>（字符串键，嵌入式内存杀手）",
    r"HashSet<string": "HashSet<string>",
    # 环境依赖
    r"System\.Text\.Json": "System.Text.Json",
    r"CultureInfo": "CultureInfo（文化相关，确定性风险）",
    r"DateTime": "DateTime",
    r"Environment\.": "Environment.*",
    r"Guid": "Guid",
    r"StackTrace": "StackTrace",
    r"Console\.": "Console.*（I/O 耦合）",
    r"\bFile\.": "File.*（I/O 耦合）",
    # 抽象
    r"delegate ": "delegate",
    r"Action<": "Action<>",
    r"Func<": "Func<>",
    r"interface ": "interface",
    r"abstract class ": "abstract class",
    r"record ": "record",
    r"throw new": "throw new（异常作为控制流？）",
}

SCOPE = {
    "Core(战斗内核)": os.path.join(SRC, "RogueDeck.Core"),
    "Run(run 层)": os.path.join(SRC, "RogueDeck.Run"),
    "Scenario": os.path.join(SRC, "RogueDeck.Scenario"),
}


def walk_cs(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "bin", "obj")]
        for fn in filenames:
            if fn.endswith(".cs"):
                out.append(os.path.join(dirpath, fn))
    return out


def scan():
    print("=" * 78)
    print("1) 语言特性 / 数值类型用量")
    print("=" * 78)
    for name, root in SCOPE.items():
        if not os.path.isdir(root):
            continue
        files = walk_cs(root)
        text = []
        for f in files:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                text.append(fh.read())
        blob = "\n".join(text)
        lines = blob.count("\n") + 1
        print(f"\n--- {name}: {len(files)} 文件 / {lines} 行 ---")
        rows = []
        for pat, label in PATTERNS.items():
            n = len(re.findall(pat, blob))
            if n:
                rows.append((n, label))
        for n, label in sorted(rows, reverse=True):
            print(f"   {n:>6}  {label}")

    print()
    print("=" * 78)
    print("2) Combat 核心的类型清单（按文件名，行数降序）= 需要搬运的【概念】清单")
    print("=" * 78)
    combat = os.path.join(SRC, "RogueDeck.Core", "Combat")
    rows = []
    for dirpath, dirnames, filenames in os.walk(combat):
        for fn in filenames:
            if fn.endswith(".cs"):
                p = os.path.join(dirpath, fn)
                with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                    n = sum(1 for _ in fh)
                rel = os.path.relpath(p, combat)
                rows.append((n, rel))
    total = sum(n for n, _ in rows)
    print(f"   Combat 合计 {len(rows)} 文件 / {total} 行")
    for n, rel in sorted(rows, reverse=True)[:25]:
        print(f"   {n:>6}  {rel}")

    print()
    print("=" * 78)
    print("3) 内容文档结构（决定【内容预编译成二进制表】的工作量）")
    print("=" * 78)
    doc = os.path.join(SRC, "RogueDeck.Sandbox.Run", "SampleContent", "bureaucrats.roguedeck.json")
    if os.path.exists(doc):
        size = os.path.getsize(doc)
        print(f"   文件: {size:,} B ({size/1048576:.2f} MB)")
        with open(doc, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            print(f"   顶层是对象，{len(data)} 个键：")
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"     {k:<28} list[{len(v)}]")
                elif isinstance(v, dict):
                    print(f"     {k:<28} object[{len(v)}]")
                else:
                    print(f"     {k:<28} {type(v).__name__}")
        else:
            print(f"   顶层是 {type(data).__name__}，长度 {len(data)}")
    else:
        print("   (没找到内容文档)")


if __name__ == "__main__":
    scan()
