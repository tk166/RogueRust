"""环境单步成本分解 —— 用来把"慢"归因到具体的一行代码上。

存在的理由：基准曾经报出"多进程比单进程慢 26 倍"，我把原因写成"IPC 搬运观察代价太高"。
换成共享内存之后只快了 2% —— **归因是错的**。真正的原因要用分解测量找，不能靠直觉。
本工具就是那次分解的固化版：

  1. 逐项 vs 批量读观察，各自多少钱（`rd_env_observe` × 122 次 对比 `rd_env_observe_into` 一次）；
  2. 一局到底能走几步 —— 决定"auto_reset 是不是必需"，也解释基准的分子为什么曾经是错的；
  3. 受控 A/B：同一段循环，只切换批量/逐项，别的都不动。

用法（在 py/ 下）：
  C:\\Users\\TK11\\miniforge3\\python.exe ..\\tools\\env_cost_breakdown.py
"""
from __future__ import annotations

import random
import sys
import time

from roguedeck_env.env import RogueDeckEnv
from roguedeck_env.native import EnvABI

N = 2000


def timed(fn, n=N):
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) / n * 1e6      # µs


def episode_lengths(abi: EnvABI, policy: str, limit: int = 5000) -> list:
    """不加 auto_reset 时，一局能走多少步。"""
    out = []
    for i in range(4):
        e = RogueDeckEnv(config=0, seed=1000 + i, abi=abi)
        rng = random.Random(7 + i)
        n = 0
        while not abi.done(e.handle) and n < limit:
            k = len(abi.actions(e.handle))
            if k == 0:
                break
            a = (k - 1) if policy == "last" else rng.randrange(k)
            if abi.step(e.handle, a) != 0:
                break
            n += 1
        out.append(n)
        e.close()
    return out


def ab_loop(abi: EnvABI, bulk: bool, n_envs: int, steps: int) -> float:
    """受控 A/B：只切换观察的读法，循环结构、动作分布、auto_reset 全一样。"""
    saved = abi._observe_into
    if not bulk:
        abi._observe_into = None
    try:
        envs = [RogueDeckEnv(config=0, seed=1000 + i, abi=abi) for i in range(n_envs)]
        rng = [random.Random(7 + i) for i in range(n_envs)]
        t0 = time.perf_counter()
        total = 0
        for _ in range(steps):
            for i, e in enumerate(envs):
                if abi.done(e.handle):
                    abi.reset(e.handle)
                k = len(abi.actions(e.handle))
                if k == 0:
                    continue
                abi.step(e.handle, rng[i].randrange(k))
                abi.observe(e.handle)          # 观察：唯一被切换的东西
                abi.reward(e.handle)
                abi.done(e.handle)
                total += 1
        dt = time.perf_counter() - t0
        for e in envs:
            e.close()
        return total / dt if dt > 0 else 0.0
    finally:
        abi._observe_into = saved


def main() -> int:
    abi = EnvABI()
    n = abi.observe_len()
    print("=" * 78)
    print(f"环境单步成本分解   observe_len={n}   批量读={'有' if abi.has_bulk_observe else '无'}")
    print("=" * 78)

    if not abi.has_bulk_observe:
        print(f"\n!! {abi.bulk_observe_note}")
        return 2

    e = RogueDeckEnv(config=0, seed=1234, abi=abi)
    h = e.handle

    print("\n── 1. 单步里每一项各多少钱 ──")
    t_bulk = timed(lambda: abi.observe(h))
    saved, abi._observe_into = abi._observe_into, None
    t_item = timed(lambda: abi.observe(h))
    abi._observe_into = saved
    t_act = timed(lambda: abi.actions(h))
    t_rew = timed(lambda: abi.reward(h))
    t_done = timed(lambda: abi.done(h))
    print(f"  observe()  批量（1 次调用）          : {t_bulk:8.1f} µs")
    print(f"  observe()  逐项（{n} 次调用）           : {t_item:8.1f} µs   <-- 曾经的真瓶颈")
    print(f"  倍数                                  : {t_item / t_bulk:8.1f}×")
    print(f"  actions()（1 + 3k 次调用）           : {t_act:8.1f} µs")
    print(f"  reward() / done()                     : {t_rew:6.1f} / {t_done:.1f} µs")

    print("\n── 2. 一局能走几步（决定 auto_reset 是不是必需）──")
    for policy in ("last", "random"):
        print(f"  策略 {policy:6s} 每局步数 = {episode_lengths(abi, policy)}")
    print("  不自动重置的话，每一步之后剩下的迭代都在空转 —— 基准的分子就是这么被吃掉的。")
    e.close()

    print("\n── 3. 受控 A/B：只切换观察读法 ──")
    steps, n_envs = 400, 4
    a = ab_loop(abi, True, n_envs, steps)
    b = ab_loop(abi, False, n_envs, steps)
    print(f"  {n_envs} 句柄 + 批量读 : {a:>9,.0f} 环境步/秒")
    print(f"  {n_envs} 句柄 + 逐项读 : {b:>9,.0f} 环境步/秒")
    print(f"  批量读的收益         : {a / b:>9.2f}×")

    print("\n结论：瓶颈是「每步 122 次跨 ABI 调用」，不是 IPC。")
    print("      共享内存只快 2%，因为观察本来就不是通过 IPC 搬运的瓶颈所在。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
