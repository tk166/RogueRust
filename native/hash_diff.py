"""闭环验证：真实引擎的预哈希规范文本  ->  Rust 内核的 SHA-256  ->  与引擎自己的哈希比较。

为什么这一步值得单独做：NIST 向量只证明"这是个正确的 SHA-256"，**证明不了它和引擎一致**。
引擎的指纹是"把一段特定的规范文本按 UTF-8 做 SHA-256"，所以真正的风险在**拿到的是不是同一段字节**
（换行、尾随换行、编码、截断）。有了 `rd_oracle_hash_input_*`，这个问题今天就能回答，
不必等到状态模型写完。

链路：
    RogueDeck.Core --NativeAOT--> rd_oracle_run + rd_oracle_hash_input_*  -> 规范文本
    rd-core (Rust) --rd-hashdump--> sha256(text) -> 小写 hex
    两者必须逐字符相等。

用法:  C:\\Users\\TK11\\miniforge3\\python.exe hash_diff.py
"""
import ctypes
import glob
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PUB = os.path.join(ROOT, "native", "RogueDeck.Oracle", "bin", "x64", "Release",
                   "net10.0", "win-x64", "publish")
CASE_DIR = os.path.join(ROOT, "corpus", "hash_cases")
HASHDUMP = os.path.join(ROOT, "kernel", "target", "release", "rd-hashdump.exe")

# (variant, seed, hero_hp, card_damage, enemy_hp, enemy_damage)
CASES = []
for variant in (0, 1, 2, 3, 4, 5, 6, 7):
    for seed in (1, 42, 1234):
        for hp, cd, eh, ed in ((30, 6, 12, 5), (50, 9, 40, 12)):
            CASES.append((variant, seed, hp, cd, eh, ed))


def load():
    for path in sorted(glob.glob(os.path.join(PUB, "*.dll"))):
        try:
            lib = ctypes.CDLL(path)
            getattr(lib, "rd_oracle_run")
            getattr(lib, "rd_oracle_hash_input_len")
        except (OSError, AttributeError):
            continue
        for name, n in (("rd_oracle_run", 6), ("rd_oracle_hash_input_len", 0),
                        ("rd_oracle_hash_input_char", 1), ("rd_oracle_hash_input_ok", 0),
                        ("rd_oracle_hash_len", 0), ("rd_oracle_hash_char", 1),
                        ("rd_oracle_error_len", 0), ("rd_oracle_error_char", 1)):
            fn = getattr(lib, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int] * n
        return lib, path
    print("!! oracle dll 里找不到所需导出")
    sys.exit(1)


def read_str(lib, len_fn, char_fn):
    n = len_fn()
    return "".join(chr(char_fn(i)) for i in range(n))


def main():
    if not os.path.exists(HASHDUMP):
        print(f"!! 先构建 rd-hashdump: tools/cargo.ps1 build --release -p rd-hashdump")
        sys.exit(1)

    lib, path = load()
    print("=" * 78)
    print("哈希闭环：引擎的规范文本 -> Rust 的 SHA-256 -> 与引擎哈希比较")
    print("=" * 78)
    print(f"  参考库: {os.path.basename(path)}")
    print(f"  被测项: {HASHDUMP}\n")

    os.makedirs(CASE_DIR, exist_ok=True)

    # ⚠️ 只删**本脚本自己生成**的那些语料。
    #
    # 这里从前是 `glob("*.txt")` 然后全删 —— 而这个目录同时住着别的来源的语料
    # （`make_corpus.py --rich-cases` 生成的 37 份富状态用例，名字形如
    # `case_0100_dp_one_s12345.txt`）。于是**跑一次 hash_diff.py 就把它们静默删光**
    # （实测 85 → 48）。删数据不留痕迹是最坏的一类副作用：没有任何报错，
    # 只有下一次 `cargo test` 会以"语料少了"的方式变红，而那时已经查不到原因了。
    #
    # 现在按本脚本的命名模式 `case_<4位序号>_v<变体>_s<种子>.txt` 精确匹配，
    # 不认识的一律**保留并报出来**。
    own = re.compile(r"^case_\d{4}_v\d+_s\d+\.txt$")
    removed, kept = 0, []
    for f in glob.glob(os.path.join(CASE_DIR, "*.txt")):
        name = os.path.basename(f)
        if own.match(name):
            os.remove(f)
            removed += 1
        elif not name.startswith("_"):
            # `_` 开头的是本脚本自己的旁路产物（`_list.txt` / `_rust_out.txt`），
            # 稍后会被覆盖写，不算"别人的语料"，不该出现在这条告警里。
            kept.append(name)
    if kept:
        print(f"  ⚠️ 保留了 {len(kept)} 份不是本脚本生成的语料（不会被删除）：")
        for name in sorted(kept)[:6]:
            print(f"       {name}")
        if len(kept) > 6:
            print(f"       ... 另有 {len(kept) - 6} 份")
        print("     要重建它们请跑：python native/make_corpus.py --rich-cases")
        print("     （`cargo test -p rd-core` 里的 every_corpus_hash_case_round_trips 会用到）\n")

    listfile = os.path.join(CASE_DIR, "_list.txt")
    outfile = os.path.join(CASE_DIR, "_rust_out.txt")
    expected = {}
    paths = []
    skipped = 0

    for i, (variant, seed, hp, cd, eh, ed) in enumerate(CASES):
        rc = lib.rd_oracle_run(hp, cd, eh, ed, seed, variant)
        if rc < 0:
            err = read_str(lib, lib.rd_oracle_error_len, lib.rd_oracle_error_char)
            print(f"  ! variant={variant} seed={seed} 运行失败: {err}")
            skipped += 1
            continue
        if not lib.rd_oracle_hash_input_ok():
            print(f"  ! variant={variant} seed={seed} 没有可用的预哈希文本")
            skipped += 1
            continue
        text = read_str(lib, lib.rd_oracle_hash_input_len, lib.rd_oracle_hash_input_char)
        want = read_str(lib, lib.rd_oracle_hash_len, lib.rd_oracle_hash_char)

        p = os.path.join(CASE_DIR, f"case_{i:04d}_v{variant}_s{seed}.txt")
        # 以 BINARY 写：字节完全相同才是重点，不能有换行转换。
        with open(p, "wb") as fh:
            fh.write(text.encode("utf-8"))
        paths.append(p)
        expected[p] = want

    if not paths:
        print("!! 一条用例都没拿到预哈希文本")
        return 1

    print(f"  用例数: {len(paths)}（跳过 {skipped}）")
    # 展示一条样本，让人能亲眼确认文本形状
    sample = paths[0]
    with open(sample, "rb") as fh:
        raw = fh.read()
    print(f"\n  样本 {os.path.basename(sample)}：{len(raw)} B，"
          f"{raw.count(chr(10).encode())} 个换行")
    print("  ---- 规范文本（前 12 行）----")
    for line in raw.decode("utf-8").split("\n")[:12]:
        print(f"    {line}")
    print("  ---- 结尾 3 行 ----")
    for line in raw.decode("utf-8").split("\n")[-3:]:
        print(f"    {line if line else '<空行>'}")

    with open(listfile, "w", encoding="utf-8", newline="\n") as fh:
        for p in paths:
            fh.write(p + "\n")

    r = subprocess.run([HASHDUMP, listfile, outfile], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"!! rd-hashdump 失败: {r.stderr}")
        return 1
    print(f"\n  {r.stdout.strip()}")

    bad = []
    with open(outfile, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) != 2:
                continue
            p, got = parts
            if expected.get(p) != got:
                bad.append((os.path.basename(p), expected.get(p), got))

    print(f"  比较的哈希数: {len(expected)}")
    if bad:
        print(f"\n!! 不一致 {len(bad)} 条（前 5）:")
        for name, want, got in bad[:5]:
            print(f"   {name}\n     引擎: {want}\n     rust: {got}")
        print("\n结论：不一致 —— 规范文本的字节或哈希实现有偏差。")
        return 1

    print("\n  ✓ 全部一致：Rust 内核的 SHA-256 在真实引擎的规范文本上逐字符匹配。")
    print("  ✓ 指纹这一半的闭环成立（文本形状见上方样本；状态模型的字节级对拍留待 W1 完成后）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
