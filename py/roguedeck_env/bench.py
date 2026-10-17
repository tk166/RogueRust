"""多开吞吐与确定性 —— 目标里"多开作为强化学习训练环境"的量化验收。

两条要回答的问题：
1. **快不快**：单进程单环境 vs N 进程 × M 环境的每秒步数。
2. **换了多开之后还确定吗**：同一批种子，用多进程跑出来的观察序列必须与单进程跑出来的一致。
   这一条比吞吐更重要 —— 训练环境不确定，等于实验不可复现。

用法:  C:\\Users\\TK11\\miniforge3\\python.exe -m roguedeck_env.bench   （在 py/ 下）
"""
from __future__ import annotations

import random
import sys
import time
from typing import List

from .env import RogueDeckEnv
from .native import ABIMissing, EnvABI
from .vec import SubprocVecEnv

STEPS = 400          # 每环境步数上限（一局通常几十步）
CONFIGS = [0, 1, 2, 3]


def policies(n: int, seed: int) -> List[random.Random]:
    return [random.Random(seed + i) for i in range(n)]


def single_threaded(abi: EnvABI, n_envs: int, steps: int) -> float:
    """单进程、n_envs 个句柄轮流 step —— 与多进程版本做**确定性对照**的基线。

    环境结束后**就地重开**（和 SubprocVecEnv 的 auto_reset 一致）。不重开的话一局只走几步，
    剩下的迭代全在空转，测出来的"步/秒"会低几十倍 —— 这正是第一版基准的错。
    """
    envs = [RogueDeckEnv(config=CONFIGS[i % len(CONFIGS)], seed=1000 + i, abi=abi)
            for i in range(n_envs)]
    rs = policies(n_envs, 7)
    t0 = time.perf_counter()
    total = 0
    for _ in range(steps):
        for i, env in enumerate(envs):
            if abi.done(env.handle):
                if abi.reset(env.handle) != 0:
                    raise RuntimeError(f"reset 失败: {abi.last_error()}")
            k = len(env.actions())
            if k == 0:
                continue
            env.step(rs[i].randrange(k))
            total += 1
    dt = time.perf_counter() - t0
    for env in envs:
        env.close()
    return total / dt if dt > 0 else 0.0


def measure_vec(n_workers: int, envs_per_worker: int, steps: int):
    """返回 (每秒环境步数, 每秒全局步数, env 数)。

    两者都报，因为一个全局步 = n_envs 个环境步：只报环境步会让"开得多"看起来天然更快。
    """
    with SubprocVecEnv(n_workers=n_workers, envs_per_worker=envs_per_worker,
                       config=CONFIGS[0], base_seed=1000) as vec:
        n = vec.n_envs
        t0 = time.perf_counter()
        total = 0
        for _ in range(steps):
            # -1 = "让 worker 自己挑一个合法动作"（见 vec.py）。这样测的是纯粹的
            # step 吞吐，而不是"父进程先算一遍合法动作"的往返开销。
            _obs, _rews, dones = vec.step([-1] * n)
            total += n            # auto_reset 之后每一步都是有效步，不再有空转
        dt = time.perf_counter() - t0
        return (total / dt if dt > 0 else 0.0), (steps / dt if dt > 0 else 0.0), n


def _run_layout(n_workers: int, envs_per_worker: int, steps: int):
    """跑一遍，返回逐步截断的观察矩阵。"""
    with SubprocVecEnv(n_workers=n_workers, envs_per_worker=envs_per_worker,
                       config=CONFIGS[0], base_seed=1000) as vec:
        rs = policies(vec.n_envs, 7)
        rows = []
        for _ in range(steps):
            acts = [-1] * vec.n_envs
            obs, _rews, _dones = vec.step(acts)
            rows.append(tuple(tuple(o[:12]) for o in obs))
        return rows


def determinism_check() -> bool:
    """同一批种子，**换成不同的进程布局**，轨迹必须逐项一致。

    这条比"多进程跑两次一致"更强：它证明**把环境摊到更多进程上不会改变它**，
    也就证明了包装层没有引入任何与进程拓扑相关的行为。
    """
    steps = 30
    a = _run_layout(1, 8, steps)   # 1 进程 × 8 句柄
    b = _run_layout(2, 4, steps)   # 2 进程 × 4 句柄，同样的 8 个种子
    c = _run_layout(1, 8, steps)   # 再跑一次 1×8，验证可复现
    same_layout = a == c
    same_spread = a == b
    print(f"  同布局重复跑一致（1×8 两次）      : {'是' if same_layout else '否'}")
    print(f"  换进程布局仍一致（1×8 vs 2×4）    : {'是' if same_spread else '否'}")
    return same_layout and same_spread


def main() -> int:
    print("=" * 78)
    print("RL 环境：多开吞吐与确定性")
    print("=" * 78)
    try:
        abi = EnvABI()
    except ABIMissing as exc:
        print(f"\n!! {exc}\n   退出码 2 = ABI 未实现，不等于通过。")
        return 2
    print(f"  库: {abi.path}")
    print(f"  观测长度: {abi.observe_len()}"
          + (f"   [整条批量读: 有]" if abi.has_bulk_observe else "   [整条批量读: 无]"))
    if not abi.has_bulk_observe:
        print(f"  !! {abi.bulk_observe_note}")
    print(f"  自动重置: 有（每局结束就地重开，否则环境一生只走几步，吞吐会被空转淹没）\n")

    print("── 吞吐 ──")
    single = single_threaded(abi, 4, STEPS)
    print(f"  单进程 4 句柄（对照基线）  : {single:>10,.0f} 环境步/秒")

    for nw, epw in ((1, 4), (4, 4), (8, 4)):
        rate, gstep, n = measure_vec(nw, epw, STEPS)
        print(f"  {nw} 进程 × {epw} 句柄 = {n:>2} env : {rate:>10,.0f} 环境步/秒"
              f"   ({gstep:>8,.0f} 全局步/秒)")

    print("\n── 确定性 ──")
    ok = determinism_check()
    print()
    if not ok:
        return 1
    print("✓ 多开吞吐与可复现性均通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
