"""Differential test: the ported Rust RNG vs the real C# engine.

This is the smallest possible end-to-end proof of the conformance mechanism that the whole
rewrite depends on:

    RogueDeck.Core  --NativeAOT-->  RogueDeck.Native.dll  --ctypes-->  expected
    rd-core (Rust)  --release---->  rd-rngdump.exe         --file---->  actual

If these two disagree on any (count, seed, step) the whole "port and diff" plan is broken, so
it is worth proving on eight bytes of RNG state before anything bigger is built on top of it.

Known-risk cases are in the grid on purpose:
  * seed = 0, step = 0        -> the reference remaps a zero state to 0x6D2B79F5
  * seed = 0xA5A5A5A5         -> the other way to land on a zero state
  * i32::MIN / i32::MAX       -> (uint) casts in C# vs `as u32` in Rust must agree
  * negative step             -> same
  * count = 255               -> the u8 index ceiling

Usage:  C:\\Users\\TK11\\miniforge3\\python.exe rng_diff.py
"""
import ctypes
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NATIVE_PUB = os.path.join(ROOT, "native", "RogueDeck.Native", "bin", "x64", "Release",
                          "net10.0", "win-x64", "publish")
RNGDUMP = os.path.join(ROOT, "kernel", "target", "release", "rd-rngdump.exe")
CASES = os.path.join(HERE, "rng_cases.txt")
RUST_OUT = os.path.join(HERE, "rng_rust_out.txt")

COUNTS = [2, 3, 4, 5, 8, 10, 13, 20, 52, 64, 100, 255]
SEEDS = [0, 1, 7, 42, -1, -7, 0x7FFFFFFF, -0x80000000, 0xA5A5A5A5 - (1 << 32)]
STEPS = [0, 1, 2, 3, 10, 100, -1]


def load_native():
    for path in sorted(glob.glob(os.path.join(NATIVE_PUB, "*.dll"))):
        try:
            lib = ctypes.CDLL(path)
            getattr(lib, "rd_rng_shuffle")
        except (OSError, AttributeError):
            continue
        for name, nargs in (("rd_rng_shuffle", 4), ("rd_rng_shuffle_len", 3)):
            fn = getattr(lib, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int] * nargs
        return lib, path
    print(f"!! no usable library in {NATIVE_PUB}")
    sys.exit(1)


def main():
    if not os.path.exists(RNGDUMP):
        print(f"!! {RNGDUMP} not built - run tools/cargo.ps1 build --release")
        sys.exit(1)

    lib, path = load_native()
    print("=" * 76)
    print("RNG 差分测试：Rust 内核  vs  C# 引擎（NativeAOT 原生库）")
    print("=" * 76)
    print(f"  参考库: {path}")
    print(f"  被测项: {RNGDUMP}")

    cases = [(c, s, t) for c in COUNTS for s in SEEDS for t in STEPS]
    with open(CASES, "w", encoding="utf-8", newline="\n") as fh:
        for c, s, t in cases:
            fh.write(f"{c} {s} {t}\n")
    print(f"\n  用例数: {len(cases):,}")

    r = subprocess.run([RNGDUMP, CASES, RUST_OUT], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"!! rd-rngdump 失败 ({r.returncode}): {r.stderr}")
        sys.exit(1)
    print(f"  {r.stdout.strip()}")

    mismatches = []
    checked = 0
    with open(RUST_OUT, "r", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 3:
                continue
            count, seed, step = int(parts[0]), int(parts[1]), int(parts[2])
            actual = [int(x) for x in parts[3:]]

            # The reference also has to agree on the LENGTH, not just the contents.
            ref_len = lib.rd_rng_shuffle_len(count, seed, step)
            if ref_len != len(actual):
                mismatches.append((count, seed, step, f"length {ref_len} != {len(actual)}"))
                continue

            for i in range(count):
                expected = lib.rd_rng_shuffle(count, seed, step, i)
                checked += 1
                if expected != actual[i]:
                    mismatches.append((count, seed, step,
                                       f"index {i}: C#={expected} rust={actual[i]}"))
                    break

    print(f"\n  逐位比较的索引数: {checked:,}")
    if mismatches:
        print(f"\n  !! 不一致 {len(mismatches)} 例（前 10）:")
        for c, s, t, why in mismatches[:10]:
            print(f"     count={c} seed={s} step={t}: {why}")
        print("\n结论：不一致 —— 移植有偏差，必须先修好再往下走。")
        sys.exit(1)

    print("\n  ✓ 全部一致。Rust 内核的洗牌与 C# 引擎逐位相同。")
    print("  ✓ 差分对拍链路（AOT 原生库 -> ctypes -> 逐位比较）端到端成立。")


if __name__ == "__main__":
    main()
