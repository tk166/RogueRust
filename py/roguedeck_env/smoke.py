"""环境 ABI 的验收自检 —— 对应 `docs/spec/env-abi.md` §8 的五条。

写法上的一条纪律：**ABI 缺失要报错退出（码 2），不能报告"通过"。**
一个在环境不存在时安静通过的冒烟测试，会让训练脚本"跑得通"而看不出任何问题。
退出码：0 = 全过；1 = 有验收项失败；2 = ABI 还没实现/构建出来（**不是通过**）。

用法:  C:\\Users\\TK11\\miniforge3\\python.exe -m roguedeck_env.smoke   （在 py/ 下）
"""
from __future__ import annotations

import random
import sys
from typing import List

from .env import RogueDeckEnv, decode, expected_observe_len
from .native import ABIMissing, EnvABI

CONFIGS = [0, 1, 2, 3]
SEEDS = [1, 7, 42]
HANDLES = 16


def _fail(msg: str) -> None:
    raise AssertionError(msg)


def check_observe_len(abi: EnvABI) -> int:
    got = abi.observe_len()
    want = expected_observe_len()
    print(f"  观测长度: ABI 报 {got}，spec §4 推得 {want}", end="")
    if got != want:
        print("  ✗")
        _fail(f"观测长度不符：ABI {got} != spec {want}。先对账（ABI 变了还是 spec 变了？）再训练。")
    print("  ✓")
    return got


def check_selfcheck(abi: EnvABI) -> None:
    for config in CONFIGS:
        for seed in SEEDS:
            rc = abi.selfcheck(config, seed, 40)
            if rc != 1:
                _fail(f"rd_env_selfcheck(config={config}, seed={seed}, steps=40) -> {rc}；"
                      f"同种子同动作流没有产生相同观察流，确定性不成立。")
    print(f"  selfcheck: {len(CONFIGS) * len(SEEDS)} 组 (config, seed) 全部返回 1  ✓")


def check_rollout(abi: EnvABI, rng: random.Random) -> None:
    for config in CONFIGS:
        for seed in SEEDS:
            with RogueDeckEnv(config=config, seed=seed, abi=abi) as env:
                obs = env.reset()
                decode(obs)  # 解码必须能跑通，否则说明布局对不上
                steps = 0
                while not abi.done(env.handle) and steps < 2000:
                    acts = env.actions()
                    if not acts:
                        _fail(f"config={config} seed={seed} 未结束且没有合法动作 —— 环境卡死")
                    env.step(rng.randrange(len(acts)))
                    steps += 1
                if steps >= 2000:
                    _fail(f"config={config} seed={seed} {steps} 步仍未结束")
    print(f"  随机策略整局跑通: {len(CONFIGS) * len(SEEDS)} 局，均正常结束、无越界  ✓")


def check_rejection_is_a_noop(abi: EnvABI) -> None:
    """规格书 §5 的硬要求：拒绝一个动作时状态必须不变。逐个越界下标试。"""
    checked = 0
    for config in CONFIGS:
        with RogueDeckEnv(config=config, seed=7, abi=abi) as env:
            n = len(env.actions())
            before = abi.observe(env.handle)
            rejected = 0
            for bad in (n, n + 1, 10_000, -1):
                rc = abi.step(env.handle, bad)
                if rc >= 0:
                    _fail(f"越界动作下标 {bad} 竟被接受（返回 {rc}）—— 合法性检查有洞")
                rejected += 1
                after = abi.observe(env.handle)
                if after != before:
                    diff = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
                    _fail(f"config={config} 拒绝下标 {bad} 之后状态变了（观察下标 {diff[:6]} 不同）"
                          f"—— RL 的 transition 就不成立了")
            checked += rejected
    print(f"  拒绝动作不改变状态: {checked} 次越界全部被拒且观察逐项未变  ✓")


def check_many_handles(abi: EnvABI) -> None:
    """同进程多句柄交错 step，结果必须与单独跑一致（句柄式设计的意义所在）。"""
    # 单独跑一遍作为基线
    baseline = {}
    for i in range(HANDLES):
        with RogueDeckEnv(config=i % len(CONFIGS), seed=100 + i, abi=abi) as env:
            seq = []
            for _ in range(30):
                if abi.done(env.handle):
                    break
                n = len(env.actions())
                a = (i * 7 + len(seq) * 3) % max(n, 1)
                env.step(a)
                seq.append((a, abi.observe(env.handle)[:8]))
            baseline[i] = seq

    # 交错跑
    envs = [RogueDeckEnv(config=i % len(CONFIGS), seed=100 + i, abi=abi) for i in range(HANDLES)]
    try:
        inter = {i: [] for i in range(HANDLES)}
        for k in range(30):
            for i in range(HANDLES):
                env = envs[i]
                if abi.done(env.handle):
                    continue
                n = len(env.actions())
                a = (i * 7 + k * 3) % max(n, 1)
                env.step(a)
                inter[i].append((a, abi.observe(env.handle)[:8]))
    finally:
        for env in envs:
            env.close()

    for i in range(HANDLES):
        if baseline[i] != inter[i]:
            _fail(f"句柄 {i} 交错 step 与单独 step 结果不同 —— 存在跨实例的全局状态")
    print(f"  多句柄: {HANDLES} 个实例交错 step 与单独跑逐项一致  ✓")


def main() -> int:
    print("=" * 78)
    print("环境 ABI 验收（docs/spec/env-abi.md §8）")
    print("=" * 78)
    try:
        abi = EnvABI()
    except ABIMissing as exc:
        print("\n!! 环境 ABI 尚不可用 —— **这不是通过**：\n")
        for line in str(exc).splitlines():
            print(f"   {line}")
        print("\n   退出码 2 = ABI 未实现，不等于验收通过。")
        return 2

    print(f"  库: {abi.path}\n")
    rng = random.Random(20261017)
    try:
        check_observe_len(abi)
        check_selfcheck(abi)
        check_rollout(abi, rng)
        check_rejection_is_a_noop(abi)
        check_many_handles(abi)
    except AssertionError as exc:
        print(f"\n!! 验收失败: {exc}")
        return 1

    print("\n✓ §8 的五条全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
