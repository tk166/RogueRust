"""调用 NativeAOT 编出来的原生库，证明 .NET 引擎可以没有运行时、没有 IPC 地从 Python 直接驱动。

这是决定「RL 侧要不要花 4~7 周重写」的那个实验：
  * 能加载、能调用、语义正确      -> 边界问题解决
  * 吞吐量比进程模型高多少倍      -> 性能问题解决

用本机 base python 跑：
  C:\\Users\\TK11\\miniforge3\\python.exe aot_probe.py
"""
import ctypes
import glob
import os
import sys
import time

PUBLISH = r"D:\Vibe\sts-tui\native\RogueDeck.Native\bin\x64\Release\net10.0\win-x64\publish"


def load_library():
    """publish 目录里可能有多个 dll，挑出真正带 C ABI 导出的那个。"""
    candidates = sorted(glob.glob(os.path.join(PUBLISH, "*.dll")))
    if not candidates:
        print(f"!! {PUBLISH} 里没有 dll")
        sys.exit(1)
    for path in candidates:
        try:
            lib = ctypes.CDLL(path)
            getattr(lib, "rd_probe")
            return lib, path
        except (OSError, AttributeError) as exc:
            print(f"   (跳过 {os.path.basename(path)}: {exc})")
    print("!! 没有找到导出 rd_probe 的库")
    sys.exit(1)


def read_hash(lib):
    n = lib.rd_hash_len()
    return "".join(chr(lib.rd_hash_char(i)) for i in range(n))


def main():
    lib, path = load_library()
    print("=" * 74)
    print("NativeAOT + ctypes 桥接验证")
    print("=" * 74)
    print(f"  库        : {path}")
    print(f"  体积      : {os.path.getsize(path):,} B "
          f"({os.path.getsize(path) / 1048576:.2f} MB)")

    # ---- 语义正确性 ----
    for fn, restype, argtypes in [
        ("rd_probe", ctypes.c_int, [ctypes.c_int] * 3),
        ("rd_hash_len", ctypes.c_int, []),
        ("rd_hash_char", ctypes.c_int, [ctypes.c_int]),
        ("rd_determinism", ctypes.c_int, [ctypes.c_int] * 3),
        ("rd_seed_sensitivity", ctypes.c_int, [ctypes.c_int] * 4),
        ("rd_standard_definition_count", ctypes.c_int, []),
        ("rd_goblin_hp", ctypes.c_int, []),
        ("rd_hero_hp", ctypes.c_int, []),
        ("rd_energy", ctypes.c_int, []),
    ]:
        f = getattr(lib, fn)
        f.restype = restype
        f.argtypes = argtypes

    print("\n--- 1. 真引擎在跑吗 ---")
    cards = lib.rd_standard_definition_count()
    print(f"  StandardCombatPackage 注册的卡牌定义数 = {cards}")
    assert cards > 0, "标准包没注册出任何定义，引擎没真正初始化"

    print("\n--- 2. 一场战斗（英雄30血/3能量 vs 地精12血，打一张6伤牌）---")
    goblin_hp = lib.rd_probe(42, 6, 0)
    print(f"  地精剩余 HP      = {goblin_hp}   (期望 12-6 = 6)")
    print(f"  英雄剩余 HP      = {lib.rd_hero_hp()}   (期望 30)")
    print(f"  剩余能量         = {lib.rd_energy()}   (期望 3-1 = 2)")
    print(f"  状态哈希         = {read_hash(lib)}")
    assert goblin_hp == 6, f"伤害结算错误：{goblin_hp}"
    assert lib.rd_hero_hp() == 30
    assert lib.rd_energy() == 2

    print("\n--- 3. 状态管线上场（先给英雄叠 2 层中毒）---")
    lib.rd_probe(42, 6, 2)
    print(f"  地精剩余 HP      = {lib.rd_goblin_hp()}")
    print(f"  英雄剩余 HP      = {lib.rd_hero_hp()}   (中毒应该扣了点血)")
    print(f"  状态哈希         = {read_hash(lib)}")

    print("\n--- 4. 确定性 ---")
    print(f"  同 seed 两次跑哈希一致      : {'是' if lib.rd_determinism(42, 6, 0) else '否'}")
    print(f"  换 seed 哈希会变           : {'是' if lib.rd_seed_sensitivity(42, 43, 6, 0) else '否'}")
    assert lib.rd_determinism(42, 6, 0) == 1, "确定性不成立"
    assert lib.rd_seed_sensitivity(42, 43, 6, 0) == 1, "RNG 没接上"

    # ---- 吞吐量 ----
    print("\n--- 5. 吞吐量（对比 .NET 进程模型：1 局 = 8 房间 5 场战斗 = 0.4 秒 @Debug）---")

    n = 5000
    t0 = time.perf_counter()
    for _ in range(n):
        lib.rd_standard_definition_count()
    dt_reg = time.perf_counter() - t0
    print(f"  只建注册表  x{n}: {dt_reg:.3f}s  -> {n / dt_reg:,.0f} 次/秒")

    n = 5000
    t0 = time.perf_counter()
    for _ in range(n):
        lib.rd_probe(42, 6, 0)
    dt_fight = time.perf_counter() - t0
    print(f"  完整一场战斗 x{n}: {dt_fight:.3f}s  -> {n / dt_fight:,.0f} 场/秒")
    print(f"  单场耗时          : {dt_fight / n * 1e6:,.0f} µs（含建注册表 + ctypes 调用开销）")

    fights_per_run = 5
    runs_per_sec = (n / dt_fight) / fights_per_run
    print(f"\n  折算整局（按 5 场战斗/局）: ~{runs_per_sec:,.0f} 局/秒/进程")
    print(f"  .NET 进程模型实测        : ~2.5 局/秒/进程（0.4s/局，Debug，含进程启动与 JSON 解析）")
    print(f"  提升倍数                 : ~{runs_per_sec / 2.5:,.0f}x")

    print("\n全部断言通过。")


if __name__ == "__main__":
    main()
