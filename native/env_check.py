"""环境 ABI 的验收（docs/spec/env-abi.md §8）—— 五项全部自动断言，输出可直接贴进报告。

用法：
  C:\\Users\\TK11\\miniforge3\\python.exe env_check.py
  C:\\Users\\TK11\\miniforge3\\python.exe env_check.py --verbose   # 顺带打印观察向量样本

退出码 0 = 五项全过。
"""
import argparse
import ctypes
import glob
import os
import sys

PUBLISH = r"D:\Vibe\sts-tui\native\RogueDeck.Oracle\bin\x64\Release\net10.0\win-x64\publish"

# 名字 -> 参数个数；返回值约定见 spec §3
SIGS = {
    "rd_env_create": 2, "rd_env_reset": 1, "rd_env_observe_len": 0, "rd_env_observe": 2,
    "rd_env_done": 1, "rd_env_result": 1, "rd_env_action_count": 1, "rd_env_action_kind": 2,
    "rd_env_action_arg": 3, "rd_env_step": 2, "rd_env_reward": 1,
    "rd_env_last_error_len": 0, "rd_env_last_error_char": 1, "rd_env_selfcheck": 3,
    "rd_env_card_def_count": 0, "rd_env_card_def_slot": 2,
    "rd_env_card_def_name_len": 1, "rd_env_card_def_name_char": 1,
}
VOID = {"rd_env_destroy": 1}

CONFIG_NAMES = {
    0: "duel      hero 30/30 1x12hp 牌组5张strike(1费6伤) 敌人5伤",
    1: "elite2    hero 50/50 2x14hp 牌组+defend(1费5格挡)+heavy(2费12伤) 敌人6伤",
    2: "statuses  hero 40/40(+str2) 2x16hp(+vuln2) 牌组含focus(1费+2力量) 敌人7伤",
    3: "swarm4    hero 60/60 4x10hp 牌组含cleave(2费全体各4伤) 敌人4伤",
    4: "action    hero 30/30 1x24hp 含英雄动作blast(2费9伤,不用抽) 敌人6伤",
    5: "endurance hero 80/80 3x20hp 10张牌组(含recover回4血/jab 0费3伤) 敌人5伤",
    6: "locked    hero 30/30 1x12hp 牌组3xstrike+3xlocked(PlayCondition恒假) —— 实测 locked "
       "进不了动作表，用来证明动作掩码不会广告打不出去的牌",
    7: "costfloor hero 30/30 1x40hp 牌组2xstrike+1xheavy+3xjab(印刷0费)，起手戴「卡牌最低费用=1」法令 "
       "—— 专供「范围内但会被引擎拒绝」这类验收：能量 0 时 jab 仍被枚举，引擎却要 1 点能量",
}


def load():
    for path in sorted(glob.glob(os.path.join(PUBLISH, "*.dll"))):
        try:
            lib = ctypes.CDLL(path)
            getattr(lib, "rd_env_create")
        except (OSError, AttributeError):
            continue
        for name, arity in SIGS.items():
            fn = getattr(lib, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int] * arity
        for name, arity in VOID.items():
            fn = getattr(lib, name)
            fn.restype = None
            fn.argtypes = [ctypes.c_int] * arity
        return lib, path
    sys.exit(f"!! {PUBLISH} 里没有带 env ABI 的库")


class Env:
    def __init__(self, lib, config, seed):
        self.lib = lib
        self.handle = lib.rd_env_create(config, seed)
        if self.handle < 0:
            raise RuntimeError(f"create({config},{seed}) -> {self.handle}: {self.error()}")
        self.config = config
        self.seed = seed
        self.len = lib.rd_env_observe_len()

    def error(self):
        n = self.lib.rd_env_last_error_len()
        return "".join(chr(self.lib.rd_env_last_error_char(i)) for i in range(n))

    def obs(self):
        return [self.lib.rd_env_observe(self.handle, i) for i in range(self.len)]

    def done(self):
        return self.lib.rd_env_done(self.handle)

    def result(self):
        return self.lib.rd_env_result(self.handle)

    def n_actions(self):
        return self.lib.rd_env_action_count(self.handle)

    def action(self, i):
        return (self.lib.rd_env_action_kind(self.handle, i),
                self.lib.rd_env_action_arg(self.handle, i, 0),
                self.lib.rd_env_action_arg(self.handle, i, 1))

    def actions(self):
        return [self.action(i) for i in range(self.n_actions())]

    def step(self, i):
        return self.lib.rd_env_step(self.handle, i)

    def reward(self):
        return self.lib.rd_env_reward(self.handle)

    def close(self):
        self.lib.rd_env_destroy(self.handle)


def pick(actions):
    """确定性策略：优先打第一张手牌，否则结束回合，否则用英雄动作（与 C# 侧 selfcheck 同规则）。"""
    order = candidate_order(actions)
    return order[0] if order else -1


def candidate_order(actions):
    """候选顺序：先手牌（按手牌序），再结束回合，再英雄动作，最后兜底全扫一遍。"""
    order = [i for i, a in enumerate(actions) if a[0] == 0]
    order += [i for i, a in enumerate(actions) if a[0] == 1]
    order += [i for i, a in enumerate(actions) if a[0] == 2]
    order += [i for i in range(len(actions)) if i not in order]
    return order


def step_first_accepted(env):
    """按候选顺序试，取第一个被接受的动作。返回 (index, rc)。

    为什么需要它：动作表里**可能**含有引擎会拒的动作（config 6 的 locked 牌就是这个用途），
    所以"枚举出来的动作一定可执行"不能当成前提 —— 包装层也得这么容错。
    """
    acts = env.actions()
    for i in candidate_order(acts):
        rc = env.step(i)
        if rc == 0:
            return i, rc
        if rc != -1:                     # -2/-3 不该在正常对局里出现，交回调用方
            return i, rc
    return None, -1


def run_episode(lib, config, seed, max_steps=200, result=None):
    """跑完整局到 done。result 传 list 就顺便把观察流记进去（用于句柄隔离性对比）。"""
    env = Env(lib, config, seed)
    total = 0
    steps = 0
    refusals = 0
    while not env.done() and steps < max_steps:
        idx, rc = step_first_accepted(env)
        if idx is None:
            break
        if rc != 0:
            raise RuntimeError(f"step 异常 rc={rc} at {steps}: {env.error()}")
        total += env.reward()
        if result is not None:
            result.append((tuple(env.obs()), env.reward(), len(env.actions())))
        steps += 1
    snapshot = (env.done(), env.result(), total, steps, tuple(env.obs()), refusals)
    env.close()
    return snapshot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    lib, path = load()
    ok = True

    print("=" * 80)
    print("环境 ABI 验收（docs/spec/env-abi.md §8）")
    print("=" * 80)
    print(f"  库: {path}  ({os.path.getsize(path) / 1048576:.2f} MB)")
    print(f"  rd_env_observe_len() = {lib.rd_env_observe_len()}   "
          f"（12 头 + 5 英雄状态 + 4x8 敌人 + 4x5 敌人状态 + 10x4 手牌 + 5 牌堆 + 8 保留）")
    print(f"  rd_env_card_def_count() = {lib.rd_env_card_def_count()} 张卡定义（全局稳定 slot）")
    print("  config 清单：")
    for c, text in CONFIG_NAMES.items():
        print(f"    {c}: {text}")

    # ── §8.1 自检 ────────────────────────────────────────────────────────────────
    print("\n--- §8.1 rd_env_selfcheck：同 (config, seed) 两个独立句柄，观察流必须逐项相同 ---")
    selfcheck_cases = [(0, 1, 40), (0, 12345, 40), (2, 7, 60), (3, 42, 80), (4, 99, 60), (5, 1234, 120)]
    selfcheck_ok = True
    for config, seed, steps in selfcheck_cases:
        r = lib.rd_env_selfcheck(config, seed, steps)
        selfcheck_ok &= (r == 1)
        print(f"  config={config} seed={seed:<6} steps={steps:<4} -> {r}"
              + ("" if r == 1 else "   <<< 不一致！"))
    print(f"  => {'PASS' if selfcheck_ok else 'FAIL'}")
    ok &= selfcheck_ok

    # ── §8.2 demo 策略跑完整局 ───────────────────────────────────────────────────
    print("\n--- §8.2 demo 策略（总打第一张合法牌，没有牌就结束回合）跑完整局 ---")
    print(f"  {'config':<7}{'seed':>6}{'steps':>7}{'done':>6}{'result':>8}{'reward':>9}   最终HP(英雄/敌人)")
    demo_ok = True
    for config in range(8):
        snap = run_episode(lib, config, 12345)
        done, result, total, steps, obs, _ = snap
        hero_hp, enemy_hp = obs[4], [obs[17 + e * 8 + 1] for e in range(obs[11])]
        demo_ok &= (done == 1)
        print(f"  {config:<7}{12345:>6}{steps:>7}{done:>6}{result:>8}{total:>9}   {hero_hp}/{enemy_hp}")
        if args.verbose:
            print(f"           obs[0:12] = {obs[0:12]}")
            print(f"           obs[12:17](英雄状态) = {obs[12:17]}   "
                  f"牌堆[109:114] = {obs[109:114]}")
    print(f"  => {'PASS（每局 done=1）' if demo_ok else 'FAIL'}")
    ok &= demo_ok

    # ── §8.3 拒绝动作不改变状态（两类：越界下标 + 范围内但被引擎拒绝）────────────────
    print("\n--- §8.3 拒绝动作（-1）前后两次观察必须逐项相等，且 done 不得翻转 ---")
    print("    （spec §8 原文只点了越界；「拒绝是零副作用」必须用**会被拒的合法动作**去测，"
          "否则等于没测）")
    reject_ok = True
    stats = {"oor": 0, "inrange": 0, "stale": 0, "mismatch": 0, "accepted": 0, "locked_accepted": 0}
    locked_slots = set()
    for slot in range(lib.rd_env_card_def_count()):
        n = lib.rd_env_card_def_name_len(slot)
        name = "".join(chr(lib.rd_env_card_def_name_char(i)) for i in range(n))
        if name == "locked":
            locked_slots.add(slot)
    if not locked_slots:
        print("  !! 找不到 locked 牌的 slot，config 6 的「范围内被拒」用例无法生效")
    for config, seed in [(0, 1), (0, 1000), (2, 7), (3, 42), (4, 5), (6, 3), (6, 99)]:
        env = Env(lib, config, seed)
        prev_actions = None
        for step in range(40):
            if env.done():
                break
            before = env.obs()
            before_done = env.done()
            n = env.n_actions()

            # (a) 越界下标
            for bad in (n, n + 1, n + 5, 10000, -1):
                rc = env.step(bad)
                stats["oor"] += 1
                if rc != -1 or env.obs() != before or env.done() != before_done:
                    stats["mismatch"] += 1
                    reject_ok = False
                    print(f"  !! [越界] config={config} step={step} idx={bad} rc={rc} "
                          f"obs_eq={env.obs() == before} done={env.done()}(was {before_done})")
                if env.reward() != 0:
                    stats["mismatch"] += 1
                    reject_ok = False
                    print(f"  !! [越界] 被拒却给了 reward={env.reward()}")

            # (b) 上一个观察的动作表里的下标（RL 里最真实的失手：拿旧观察的下标来 step）
            if prev_actions is not None:
                for idx in range(len(prev_actions)):
                    rc = env.step(idx)
                    if rc == -1:
                        stats["stale"] += 1
                        if env.obs() != before or env.done() != before_done or env.reward() != 0:
                            stats["mismatch"] += 1
                            reject_ok = False
                            print(f"  !! [旧下标] config={config} step={step} idx={idx} rc=-1 "
                                  f"obs_eq={env.obs() == before} done={env.done()}(was {before_done})")
                    else:
                        stats["accepted"] += 1
                        break   # 接受了一个动作，状态已经前进，本轮检查到此为止

            # (c) 范围内但引擎会拒的动作：config 6 的 locked 牌（PlayCondition 恒假）
            if config == 6:
                for idx in range(env.n_actions()):
                    kind, a0, a1 = env.action(idx)
                    if kind != 0:
                        continue
                    slot = before[69 + a0 * 4 + 2]          # 观察里这张手牌的 def_slot
                    if slot not in locked_slots:
                        continue
                    rc = env.step(idx)
                    stats["inrange"] += 1
                    if rc == -1:
                        if env.obs() != before or env.done() != before_done or env.reward() != 0:
                            stats["mismatch"] += 1
                            reject_ok = False
                            print(f"  !! [范围内被拒] config={config} step={step} idx={idx} "
                                  f"obs_eq={env.obs() == before} done={env.done()}(was {before_done})")
                    else:
                        stats["locked_accepted"] += 1
                        print(f"  ** locked 牌被接受了 rc={rc} —— CanPlay 竟然检查了 PlayCondition；"
                              f"state advanced")
                    break

            prev_actions = env.actions()
            if env.done():                      # (b)/(c) 里那个被接受的动作可能已经结束了对局
                break
            idx, rc = step_first_accepted(env)
            if rc != 0:
                reject_ok = False
                print(f"  !! 没有任何合法动作被接受 rc={rc} nact={env.n_actions()} "
                      f"done={env.done()} result={env.result()} hero_hp={env.obs()[4]} "
                      f"turn={env.obs()[1]} phase={env.obs()[2]} err={env.error()[:70]!r}")
        # 结束后再 step 必须是 -2，且观察仍然不变
        if env.done():
            before, before_done = env.obs(), env.done()
            rc = env.step(0)
            if rc != -2 or env.obs() != before or env.done() != before_done:
                reject_ok = False
                print(f"  !! config={config} 结束后 step rc={rc}（期望 -2）")
        env.close()
    print(f"  越界下标 {stats['oor']} 次 / 范围内被拒 {stats['inrange']} 次"
          f"（其中 locked 牌被接受 {stats['locked_accepted']} 次）/ 旧观察下标被拒 "
          f"{stats['stale']} 次 / 旧下标被接受 {stats['accepted']} 次")
    print(f"  全部满足「-1 ⇒ 观察逐项不变 且 done 不变 且 reward=0」 => "
          f"{'PASS' if reject_ok and stats['mismatch'] == 0 else 'FAIL'}")
    ok &= (reject_ok and stats["mismatch"] == 0)

    # ── §8.3b 专门构造「在范围内、引擎却会拒绝」的动作（spec §8 原文没点这一类）────────────
    print("\n--- §8.3b 范围内但被引擎拒绝：config 7 的 0 费 jab vs「最低费用=1」法令 ---")
    env = Env(lib, 7, 2024)
    inrange_ok = True
    observed_refusal = 0
    for step in range(30):
        if env.done():
            break
        before, before_done = env.obs(), env.done()
        energy = env.obs()[8]
        # 先做一次越界拒绝，确认不变量（与 §8.3 同类，但这里是同一局里连续检查）
        rc = env.step(env.n_actions())
        if rc != -1 or env.obs() != before or env.done() != before_done or env.reward() != 0:
            inrange_ok = False
            print(f"  !! 越界拒绝不干净 rc={rc}")
        # 把 3 点能量花光（只挑印刷费用 ≤ 剩余能量的牌），然后就去找 0 费的 jab
        spent = False
        for idx in range(env.n_actions()):
            kind, a0, a1 = env.action(idx)
            if kind != 0:
                continue
            cost = env.obs()[69 + a0 * 4 + 1]
            if cost <= energy and (energy - cost) < energy:
                rc = env.step(idx)
                if rc == 0:
                    spent = True
                    break
        if not spent:
            # 能量已经花不动了：找印刷 0 费的 jab（我们的门控放行），看引擎会不会拒
            for idx in range(env.n_actions()):
                kind, a0, a1 = env.action(idx)
                if kind != 0:
                    continue
                cost = before[69 + a0 * 4 + 1]
                if cost != 0:
                    continue
                b, bd = env.obs(), env.done()
                rc = env.step(idx)
                if rc == -1:
                    observed_refusal += 1
                    if env.obs() != b or env.done() != bd or env.reward() != 0:
                        inrange_ok = False
                        print(f"  !! [范围内被拒] step={step} idx={idx} obs_eq={env.obs() == b} "
                              f"done={env.done()}(was {bd}) reward={env.reward()}")
                    elif observed_refusal <= 2:
                        print(f"  step={step} 能量={env.obs()[8]} 印刷 0 费牌 idx={idx} -> rc=-1  "
                              f"错误: {env.error()[:88]!r}")
                        print(f"     ⇒ 观察逐项不变、done 未翻转、reward=0  ✓")
                elif observed_refusal <= 2:
                    print(f"  step={step} 印刷 0 费牌 idx={idx} -> rc={rc}（被接受了）")
                break
    env.close()
    print(f"  构造到的「范围内被拒」次数 = {observed_refusal}  => "
          f"{'PASS' if inrange_ok and observed_refusal > 0 else 'FAIL'}")
    ok &= (inrange_ok and observed_refusal > 0)
    ok &= reject_ok

    # ── §8.4 ≥16 个句柄交错 step 与单独跑一致 ────────────────────────────────────
    print("\n--- §8.4 同进程 16 个句柄交错 step，结果与单独跑一致 ---")
    plan = [(c % 6, 1000 + 7 * c) for c in range(16)]
    solo = []
    for config, seed in plan:
        stream = []
        run_episode(lib, config, seed, result=stream)
        solo.append(stream)

    envs = [Env(lib, c, s) for c, s in plan]
    inter = [[] for _ in envs]
    done_flags = [False] * len(envs)
    for _ in range(400):
        if all(done_flags):
            break
        for i, env in enumerate(envs):
            if done_flags[i]:
                continue
            if env.done():
                done_flags[i] = True
                continue
            _, rc = step_first_accepted(env)
            if rc != 0:
                raise RuntimeError(f"handle {i} 交错 step 异常 rc={rc}: {env.error()}")
            inter[i].append((tuple(env.obs()), env.reward(), len(env.actions())))
    for env in envs:
        env.close()

    inter_ok = True
    for i, (config, seed) in enumerate(plan):
        same = solo[i] == inter[i][:len(solo[i])] and len(solo[i]) == len(inter[i])
        inter_ok &= same
        if not same:
            print(f"  !! 句柄 {i} (config={config} seed={seed}) 不一致: "
                  f"单独 {len(solo[i])} 步 vs 交错 {len(inter[i])} 步")
    print(f"  16 个句柄（config {sorted(set(c for c, _ in plan))}，不同 seed）交错执行 "
          f"{sum(len(s) for s in inter)} 步 ⇒ {'PASS（与单独跑逐项相同）' if inter_ok else 'FAIL'}")
    ok &= inter_ok

    # ── 附加：reset 幂等 + 卡定义 slot 稳定性 ────────────────────────────────────
    print("\n--- 附加：reset 复现初始状态 / def_slot 全局稳定 ---")
    env = Env(lib, 1, 4242)
    first = tuple(env.obs())
    for _ in range(3):
        env.step(pick(env.actions()))
    env.lib.rd_env_reset(env.handle)
    reset_ok = tuple(env.obs()) == first
    slots = [env.lib.rd_env_card_def_slot(env.handle, i)
             for i in range(env.lib.rd_env_card_def_count())]
    names = []
    for slot in slots:
        if slot < 0:
            names.append(None)
            continue
        n = lib.rd_env_card_def_name_len(slot)
        names.append("".join(chr(lib.rd_env_card_def_name_char(i)) for i in range(n)))
    env.close()
    print(f"  reset 后观察 == 初始观察: {reset_ok}")
    print(f"  handle 的卡定义表 -> 全局 slot: {list(zip(names, slots))}")
    print(f"  => {'PASS' if reset_ok else 'FAIL'}")
    ok &= reset_ok

    print("\n" + "=" * 80)
    print(f"总判定: {'PASS —— 5 项验收全部通过' if ok else 'FAIL'}")
    print("=" * 80)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
