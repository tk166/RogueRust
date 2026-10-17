"""量一下参考实现的真实体量（只读，不改仓库）。"""
import os
import sys
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RogueDeck-Core")


def count_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def main():
    by_dir = defaultdict(lambda: [0, 0])   # dir -> [files, lines]
    total = [0, 0]
    test_files = []
    cs_files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".git", "bin", "obj")]
        for fn in filenames:
            if not fn.endswith(".cs"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT)
            parts = rel.split(os.sep)
            key = os.sep.join(parts[:2]) if len(parts) > 1 else parts[0]
            n = count_lines(full)
            by_dir[key][0] += 1
            by_dir[key][1] += n
            total[0] += 1
            total[1] += n
            cs_files.append((rel, n))
            if "Tests" in rel or rel.endswith("Test.cs"):
                test_files.append((rel, n))

    print(f"== 仓库根: {ROOT}")
    print(f"== .cs 文件合计: {total[0]} 个, {total[1]} 行\n")
    print(f"{'目录':<42}{'文件':>6}{'行数':>9}")
    for k in sorted(by_dir, key=lambda x: -by_dir[x][1]):
        f, n = by_dir[k]
        print(f"{k:<42}{f:>6}{n:>9}")

    print(f"\n== 测试文件 {len(test_files)} 个, {sum(n for _, n in test_files)} 行")
    for rel, n in sorted(test_files, key=lambda t: -t[1])[:25]:
        print(f"   {n:>6}  {rel}")

    print("\n== 最大的 15 个生产文件")
    prod = [(r, n) for r, n in cs_files if "Tests" not in r]
    for rel, n in sorted(prod, key=lambda t: -t[1])[:15]:
        print(f"   {n:>6}  {rel}")

    print("\n== Combat 目录树")
    combat = os.path.join(ROOT, "src", "RogueDeck.Core", "Combat")
    if os.path.isdir(combat):
        for dirpath, dirnames, filenames in os.walk(combat):
            dirnames.sort()
            rel = os.path.relpath(dirpath, combat)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            print("  " * depth + f"[{os.path.basename(dirpath)}]")
            for fn in sorted(f for f in filenames if f.endswith(".cs")):
                n = count_lines(os.path.join(dirpath, fn))
                print("  " * (depth + 1) + f"{fn}  ({n})")
    else:
        print("   (没有 src/RogueDeck.Core/Combat)")


if __name__ == "__main__":
    main()
