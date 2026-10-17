"""诊断：为什么"合法动作列表"里的动作会被引擎拒绝？

现象：策略从 `rd_env_action_count/kind/arg` 返回的列表里**在范围内**取一个下标，
`rd_env_step` 却返回 -1（"unaffordable or rejected by a validator"）。

这会同时破坏两件事：
* RL 侧每一步都在提无效动作（浪费样本、混淆 credit assignment）；
* `docs/spec/env-abi.md` §5 说"拒绝时状态不变" —— 状态确实不变，但**动作空间本身就没定义清楚**。

本脚本把出事那一刻的**完整动作列表**与**解码后的观察**并排打出来，让责任方一眼看出是
"枚举包含了付不起的牌"还是"列表过期"还是别的。

用法:  C:\\Users\\TK11\\miniforge3\\python.exe -m roguedeck_env.diagnose_reject   （在 py/ 下）
"""
from __future__ import annotations

import random
import sys

from .env import RogueDeckEnv, decode
from .native import ABIMissing, EnvABI

CONFIG, SEED = 0, 1000


def describe_actions(acts):
    kinds = {}
    for k, a0, a1 in acts:
        kinds.setdefault(k, []).append((a0, a1))
    parts = []
    for k in sorted(kinds):
        name = {0: "打手牌", 1: "结束回合", 2: "英雄动作"}.get(k, f"kind{k}")
        parts.append(f"{name}×{len(kinds[k])} {kinds[k][:8]}")
    return " | ".join(parts)


def main() -> int:
    print("=" * 78)
    print("诊断：合法动作列表 vs 引擎接受度")
    print("=" * 78)
    try:
        abi = EnvABI()
    except ABIMissing as exc:
        print(f"\n!! {exc}")
        return 2

    for config in (0, 1, 2, 3):
        with RogueDeckEnv(config=config, seed=SEED, abi=abi) as env:
            rng = random.Random(12345)
            refusals = []
            for step_i in range(400):
                if abi.done(env.handle):
                    break
                acts = env.actions()
                if not acts:
                    print(f"  config={config}: 第 {step_i} 步无动作且未结束 —— 环境卡死")
                    break
                idx = rng.randrange(len(acts))
                before_acts = acts
                before_obs = abi.observe(env.handle)
                rc = abi.step(env.handle, idx)
                if rc != 0:
                    refusals.append((step_i, idx, before_acts, before_obs, abi.last_error(),
                                     abi.observe(env.handle)))
                    if len(refusals) >= 1:
                        break

            if not refusals:
                print(f"  config={config}: 400 步内没有被拒的动作  ✓")
                continue

            step_i, idx, before_acts, before_obs, err, obs = refusals[0]
            d = decode(obs)
            db = decode(before_obs)
            post_acts = env.actions()
            print(f"\n  config={config} 第 {step_i} 步被拒：动作下标 {idx}")
            print(f"    引擎说: {err}")
            print(f"    ── 拒绝之前 ──")
            print(f"      动作列表 {len(before_acts)} 个: {describe_actions(before_acts)}")
            print(f"      被选中: {before_acts[idx] if idx < len(before_acts) else '<越界>'}")
            print(f"      能量 {db['energy']}/{db['energy_max']}  手牌 {db['hand_count']}  "
                  f"回合 {db['round']}.{db['turn']}  phase={db['phase']}")
            print(f"    ── 拒绝之后 ──")
            print(f"      动作列表 {len(post_acts)} 个: {describe_actions(post_acts)}")
            print(f"      能量 {d['energy']}/{d['energy_max']}  手牌 {d['hand_count']}  "
                  f"回合 {d['round']}.{d['turn']}  done={abi.done(env.handle)}")
            same = before_obs == obs
            print(f"      观察逐项未变: {'是' if same else '**否 —— 违反 env-abi.md §5**'}")
            if not same:
                diff = [i for i, (a, b) in enumerate(zip(before_obs, obs)) if a != b]
                print(f"        不同的观察下标（前 12 个）: {diff[:12]}（共 {len(diff)} 处）")
            print("    手牌（下标, 费用, 卡定义槽, 已升级）：")
            sel = before_acts[idx] if idx < len(before_acts) else None
            for i, c in enumerate(d["hand"]):
                mark = " ← 被选中的手牌" if sel and sel[0] == 0 and sel[1] == i else ""
                print(f"      [{i}] occupied={c['occupied']:>3} cost={c['cost']:>3} "
                      f"def_slot={c['def_slot']:>4} upgraded={c['upgraded']}{mark}")
            if sel and sel[0] == 0 and 0 <= sel[1] < len(d["hand"]):
                c = d["hand"][sel[1]]
                print(f"\n    判定: 被选手牌费用 {c['cost']}，拒绝前能量 {db['energy']} → "
                      + ("**枚举把付不起的牌当成了合法动作**"
                         if c["cost"] > db["energy"]
                         else "费用够 ⇒ 拒绝不是费用问题"))
            if not post_acts and not abi.done(env.handle):
                print("    ⚠ **动作列表为空但环境未结束** —— 策略在这里无路可走。"
                      "这是动作空间自相矛盾，不是「策略选错」。")
            return 1
    print("\n✓ 4 个 config 各 400 步内都没有出现「列表内动作被拒」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
