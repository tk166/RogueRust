"""覆盖门禁：在拿语料当验收基准之前，先证明它真的覆盖了该覆盖的机制。

为什么需要这个工具
------------------
`corpus/golden_v1.jsonl` 的 128 条用例**哈希两两互异、确定性自检通过、看起来一切正常** ——
但实测它的输入构造只用到「一张 strike（单个 DealDamage 节点）+ 一只 ogre 的 smash」，
于是修饰器管线、状态、格挡、队列卡、法令、拦截器、触发式效果、控制流节点**一条都没跑到**。
（证据：random_step 分布 0:44/1:76/2:8，steps 仅 {2,3,4,7}，pending 全 0。）

一份"全绿"的语料库如果根本没覆盖某个机制，那它对那个机制的验收就是**假保证**。
所以规则是：**语料库必须先证明自己能区分，再拿去当基准。** 本工具就是这个证明的执行者。

用法
----
    C:\\Users\\TK11\\miniforge3\\python.exe coverage_check.py
    C:\\Users\\TK11\\miniforge3\\python.exe coverage_check.py --corpus golden_v2.jsonl --min-cases 2

退出码 0 = 覆盖达标；1 = 有机制没覆盖（**此时不得开始 W3**）；2 = 环境/输入有问题。
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORPUS_DIR = os.path.join(ROOT, "corpus")

# 每个机制为什么必须被覆盖 —— 这是 W3 的验收面，少一个就等于那块没验。
REQUIRED = {
    "card_play":           "出牌与落区（最基本的通路）",
    "energy_cost":         "付费与资源池",
    "damage":              "基础伤害结算",
    "block":               "格挡吸收（在伤害与扣血之间）",
    "status_apply":        "状态施加",
    "status_decay":        "状态按回合衰减（易伤/虚弱/脆弱）",
    "modifier_strength":   "修饰器两轴的加法侧（Strength 100）",
    "modifier_weak":       "修饰器乘法侧（Weak 200）",
    "modifier_vulnerable": "Target 阶段的乘法侧（Vulnerable 300）",
    "multi_hit":           "多段伤害（段间结算走 continuation）",
    "multi_enemy":         "多目标 / AoE 的目标选择",
    "defensive_pool":      "防御池按 (AbsorbPriority, Id) 吸收",
    "pre_down_intercept":  "死亡前拦截（Prevent / Redirect，深度上限 4）",
    "triggered_effect":    "触发式效果（effect 先于 event、每 cycle 一条 continuation）",
    "decree_turn":         "回合法令（回合开始/结束的生命周期）",
    "decree_round":        "轮次法令（一轮的定义）",
    "rng_shuffle":         "确定性随机（洗牌消耗 random_step）",
    "control_flow":        "效果程序的控制流节点（conditional / repeat / for-each）",
    "death":               "死亡与 Overkill",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", default=os.path.join(CORPUS_DIR, "coverage.json"))
    ap.add_argument("--corpus", default=None, help="语料文件名（默认取 coverage.json 里声明的）")
    ap.add_argument("--min-cases", type=int, default=1,
                    help="每个机制至少需要几条用例（默认 1；建议重要机制用 2）")
    args = ap.parse_args()

    print("=" * 78)
    print("覆盖门禁：语料库必须先证明自己能区分，再拿去当验收基准")
    print("=" * 78)

    if not os.path.exists(args.coverage):
        print(f"\n!! 找不到覆盖清单: {args.coverage}\n")
        print("   这说明语料库还没有声明自己覆盖了什么，因此**无法证明它不是假保证**。")
        print("   处理：在生成语料时一并产出 coverage.json（机制 -> 用例 id 列表），")
        print("   或在无法覆盖某机制时把它明确列为不支持（写进 SEMANTICS 的未完事项）。")
        print("\n   结论：门禁不通过 —— 不得开始 W3。")
        return 1

    with open(args.coverage, encoding="utf-8") as fh:
        cov = json.load(fh)

    mechs = cov.get("mechanisms") or {}
    corpus_name = args.corpus or cov.get("corpus") or "golden_v2.jsonl"

    # 语料可能不止一个文件（golden_vN + 规格书向量）。把 corpus/ 下所有 .jsonl 都索引起来，
    # 并记住每个 id 出自哪个文件 —— 清单只声明一个 "corpus" 字段时，这是唯一诚实的做法。
    known = {}          # id -> 文件名
    per_file = {}       # 文件名 -> 条数
    for path in sorted(glob.glob(os.path.join(CORPUS_DIR, "*.jsonl"))):
        fname = os.path.basename(path)
        n = 0
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and "case" in rec:
                    known.setdefault(rec["case"], fname)
                    n += 1
        per_file[fname] = n

    # 前缀写错是这类清单最常见的错法（清单写 vec-modp-01，文件里叫 modp-01）。
    # 与其让人再去翻文件，不如把近似匹配直接指出来。
    def near_miss(case_id):
        tail = case_id.split("-", 1)[1] if "-" in case_id else None
        if tail and tail in known:
            return known[tail], tail
        for sep in ("_", "."):
            if sep in case_id:
                t = case_id.split(sep, 1)[1]
                if t in known:
                    return known[t], t
        return None

    print(f"\n  覆盖清单: {args.coverage}")
    print("  语料文件: " + ", ".join(f"{k}({v})" for k, v in sorted(per_file.items())))
    print(f"  清单声明的 corpus 字段: {corpus_name}")
    print(f"  要求下限: 每机制 ≥ {args.min_cases} 条\n")

    print(f"  {'机制':<22}{'用例数':>7}  {'状态':<10}说明")
    print("  " + "-" * 74)

    missing, thin, dangling, mismatched, ok = [], [], [], [], 0
    for mech, why in REQUIRED.items():
        ids = mechs.get(mech) or []
        real = [i for i in ids if i in known]
        bad = [i for i in ids if i not in known]
        if bad:
            dangling.append((mech, bad[:3]))
            for i in bad[:2]:
                nm = near_miss(i)
                if nm:
                    mismatched.append((mech, i, nm[1], nm[0]))
        if not real:
            status = "缺失"
            missing.append((mech, why))
        elif len(real) < args.min_cases:
            status = "偏少"
            thin.append((mech, len(real)))
        else:
            status = "OK"
            ok += 1
        print(f"  {mech:<22}{len(real):>4}/{len(ids):<3} {status:<8}{why}")

    extra = sorted(set(mechs) - set(REQUIRED))
    if extra:
        print(f"\n  清单里多出的机制（不视为错误）: {', '.join(extra)}")

    print()
    if mismatched:
        print("  !! 清单里的 id 与语料文件对不上（疑似命名不一致），例如：")
        for mech, written, actual, fname in mismatched[:8]:
            print(f"     [{mech}] 清单写 '{written}'，但 {fname} 里叫 '{actual}'")
        print("     -> 这是**清单的问题**，不是覆盖的问题；但清单对不上就无法作为覆盖证明。")

    if dangling:
        print(f"\n  !! 清单引用了语料里不存在的 case id（共 {len(dangling)} 个机制受影响），例如：")
        for mech, sample in dangling[:5]:
            print(f"     {mech}: {sample}")

    if missing:
        print(f"\n  !! 未覆盖的机制 {len(missing)} 个：")
        for mech, why in missing:
            print(f"     - {mech:<22} {why}")

    if thin:
        print(f"\n  ! 用例偏少的机制 {len(thin)} 个: " +
              ", ".join(f"{m}({n})" for m, n in thin))

    if missing or dangling:
        print(f"\n结论：门禁不通过（覆盖 {ok}/{len(REQUIRED)}）—— **不得开始 W3**。")
        return 1
    print(f"结论：门禁通过（覆盖 {ok}/{len(REQUIRED)}）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
