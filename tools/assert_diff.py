"""从 cargo test 日志里把 `assert_eq!` 的 left/right 字符串解出来并**逐字符定位差异**。

为什么需要：Rust 的断言输出是两整行很长的转义字符串，肉眼看不出差在哪 ——
上一条 W1 的失败我截取尾部一看"两边一样"，差点以为断言是假的。
差异定位必须交给程序：解转义、比长度、报第一个不同的下标与上下文。

用法:  C:\\Users\\TK11\\miniforge3\\python.exe assert_diff.py <cargo_test.log>
"""
import re
import sys


def unescape(s: str) -> str:
    # Rust 的 Debug 字符串里 \\n 是两字符，还原成真换行；其余转义按常见几种处理。
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def extract(line: str, tag: str):
    m = re.match(r'^\s*' + tag + r':\s*"(.*)"\s*$', line)
    return unescape(m.group(1)) if m else None


def first_diff(a: str, b: str):
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    if len(a) != len(b):
        return n
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    with open(sys.argv[1], encoding="utf-8", errors="ignore") as fh:
        lines = fh.read().splitlines()

    current = None
    left = right = None
    reports = []
    for line in lines:
        m = re.match(r"^---- (\S+) stdout ----", line.strip())
        if m:
            current = m.group(1)
            left = right = None
            continue
        if current:
            if left is None and (v := extract(line, "left")) is not None:
                left = v
            elif right is None and (v := extract(line, "right")) is not None:
                right = v
            if left is not None and right is not None:
                reports.append((current, left, right))
                left = right = None

    seen = set()
    uniq = []
    for name, l, r in reports:
        if name in seen:
            continue
        seen.add(name)
        uniq.append((name, l, r))

    if not uniq:
        print("没有找到成对的 left/right 断言输出。")
        return 1

    print("=" * 78)
    print(f"断言差异定位：{len(uniq)} 处")
    print("=" * 78)
    for name, l, r in uniq:
        print(f"\n── {name}")
        print(f"   长度  left={len(l)}  right={len(r)}")
        i = first_diff(l, r)
        if i is None:
            print("   !! 两条字符串完全相同 —— 那这个断言不该失败，检查是不是别处的断言")
            continue
        lo = max(0, i - 40)
        print(f"   首个差异在下标 {i}")
        print(f"     left [{lo}:{i+40}] = {l[lo:i+40]!r}")
        print(f"     right[{lo}:{i+40}] = {r[lo:i+40]!r}")
        # 逐行对齐，指出是第几行
        la, ra = l.split("\n"), r.split("\n")
        for k in range(max(len(la), len(ra))):
            a = la[k] if k < len(la) else "<缺失>"
            b = ra[k] if k < len(ra) else "<缺失>"
            if a != b:
                print(f"   第 {k+1} 行不同：")
                print(f"     left  = {a!r}")
                print(f"     right = {b!r}")
                break
    return 1 if uniq else 0


if __name__ == "__main__":
    sys.exit(main())
