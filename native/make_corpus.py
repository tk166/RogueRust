"""W0 核心交付物：golden 语料生成器 + 规格书验收向量的可执行对拍。

三件产出：
  1. corpus/golden_v1.jsonl —— 原有的 128 条（**逐字节不变**：rd_oracle_run 的签名与语义都没动）
  2. corpus/golden_v2.jsonl —— 用 rd_oracle_run_ex / 各 probe 造的"机制语料"：
     修饰器、多段伤害、多敌人、格挡、自定义防御池、队列卡、法令、触发式效果、
     洗牌/重洗、快照往返、控制流节点，每类至少一条真正把它跑起来的用例。
  3. corpus/hash_cases/case_01xx_*.txt —— **富状态语料**（`--rich-cases`；随完整流程一起跑）：
     旧那 48 份（hash_diff.py 从 rd_oracle_run 生成）的规范文本里从来没出现过
     dp= / s= / gs= / cnt= / tr= / queue= / aside= 与卡行后缀 m:/mc:/msrc:/qat:、状态行后缀
     pend=，所以那些行只是"照着 CombatStateHasher.cs 钉"的规格级验证。这一批把它们变成
     引擎真实产出的状态；rd-core 的 every_corpus_hash_case_round_trips 会直接吃掉它们。
  4. corpus/spec_vectors_v1.jsonl —— 三份规格书 §7 的验收向量，**逐条**记录
     规格书声称的期望值 vs 真实引擎实测值 vs 结论（一致 / 不一致 / 无法表达）。
  5. corpus/coverage.json —— 机制 -> 用例 id 的机器可读覆盖清单。

为什么这是整个重构计划的地基：
  * 规格书留的待办「验收向量的具体哈希值要在真实实现上跑出来」—— 就是这里产出的。
  * 规格书第 2 条发现「哈希器只覆盖快照子集」—— 所以除了 hash 之外，
    这里还记录了落在盲区里的观测量（尤其 random_step，它能直接抓
    「随机掷骰次数不一致」这个头号确定性 bug）。
  * 规格书 §7 的向量是**人写的**，可能抄错。本脚本不迁就任何一方：
    实测与声称不一致时如实记录，并在报告里指出是谁错了。

用法（本机 base python）：
  C:\\Users\\TK11\\miniforge3\\python.exe make_corpus.py            # 全量生成 + 对拍
  C:\\Users\\TK11\\miniforge3\\python.exe make_corpus.py --bench    # 只测吞吐
  C:\\Users\\TK11\\miniforge3\\python.exe make_corpus.py --vectors  # 只跑规格书向量
"""
import argparse
import ctypes
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time

PUBLISH = r"D:\Vibe\sts-tui\native\RogueDeck.Oracle\bin\x64\Release\net10.0\win-x64\publish"
CORPUS_DIR = r"D:\Vibe\sts-tui\corpus"
# The Rust port's own SHA-256 over a file's bytes. Used by the rich-state corpus to close the same loop
# hash_diff.py closes for the legacy 48: engine hash == the port's hash of the same canonical text.
HASHDUMP = os.path.join(os.path.dirname(CORPUS_DIR), "kernel", "target", "release", "rd-hashdump.exe")

INT_FUNCS = {
    "rd_oracle_run": 6,
    "rd_oracle_hash_len": 0, "rd_oracle_hash_char": 1,
    "rd_oracle_error_len": 0, "rd_oracle_error_char": 1,
    "rd_oracle_steps": 0, "rd_oracle_problems": 0,
    "rd_oracle_hero_hp": 0, "rd_oracle_enemy_hp": 0,
    "rd_oracle_round": 0, "rd_oracle_turn": 0, "rd_oracle_random_step": 0,
    "rd_oracle_pending": 0, "rd_oracle_log_count": 0,
    # ---- extended ABI (oracle-abi.md) ----
    "rd_oracle_run_ex": 27,
    "rd_oracle_shuffle": 4, "rd_oracle_shuffle_text": 3, "rd_oracle_shuffle_text_char": 1,
    "rd_oracle_hash_input_len": 0, "rd_oracle_hash_input_char": 1, "rd_oracle_hash_input_ok": 0,
    "rd_oracle_hero_block": 0, "rd_oracle_enemy_block": 0,
    "rd_oracle_hero_ward": 0, "rd_oracle_enemy_ward": 0,
    "rd_oracle_energy": 0, "rd_oracle_energy_max": 0,
    "rd_oracle_hand_count": 0, "rd_oracle_draw_count": 0, "rd_oracle_discard_count": 0,
    "rd_oracle_exhaust_count": 0, "rd_oracle_queue_count": 0,
    "rd_oracle_enemy_count": 0, "rd_oracle_phase": 0, "rd_oracle_result": 0,
    "rd_oracle_played": 0, "rd_oracle_enemy_hp_at": 1, "rd_oracle_enemy_block_at": 1,
    "rd_oracle_hero_stacks": 1, "rd_oracle_enemy_stacks": 1,
    "rd_oracle_text_len": 0, "rd_oracle_text_char": 1, "rd_oracle_probe_ok": 0,
    "rd_oracle_probe_shuffle_pile": 2, "rd_oracle_probe_expr": 4,
    "rd_oracle_probe_conditional": 3, "rd_oracle_probe_repeat": 3,
    "rd_oracle_probe_program_steps": 2, "rd_oracle_probe_for_each": 7,
    "rd_oracle_probe_decree": 10, "rd_oracle_probe_reshuffle": 3,
    "rd_oracle_probe_trigger_order": 4, "rd_oracle_probe_snapshot": 1,
    "rd_oracle_probe_turn": 6, "rd_oracle_probe_intercept": 2,
    "rd_oracle_probe_pre_down": 3,
    # ---- rich-state ABI (OracleExports.RichStates.cs) ----
    # 这一组是补「规范文本里从来没出现过的键」用的：m:/mc:/msrc:（卡牌标记）、cnt=（计数器）、
    # tr=（临时规则）、aside=/exh=/ban=（三个只有卡牌操作才能进的区）、pend=（延迟生效的状态）、
    # gs=（全局状态）。dp= / s= / queue= / qat: 不需要新导出 —— rd_oracle_run_ex 早就够得着，
    # 只是旧语料没用它。
    "rd_oracle_probe_card_marks": 6,
    "rd_oracle_probe_combatant_counter": 5,
    "rd_oracle_probe_temporary_rule": 6,
    "rd_oracle_probe_card_zone_move": 3,
    "rd_oracle_probe_pending_status": 5,
    "rd_oracle_probe_global_status": 4,
}

# 参数顺序 = OracleExports.Extended.cs 里 RunEx 的形参顺序。改一边必须改两边。
RUN_EX_ARGS = [
    "hero_hp", "card_damage", "card_hits", "card_damage_target", "card_kind",
    "card_block", "card_block_target", "card_ward", "card_cost", "queue_on_play",
    "enemy_hp", "enemy_damage", "enemy_count",
    "hero_strength", "hero_vulnerable", "hero_weak", "hero_dexterity", "hero_frail",
    "enemy_strength", "enemy_vulnerable", "enemy_weak", "enemy_dexterity", "enemy_frail",
    "draw_per_turn", "deck_size", "seed", "variant",
]

# 变体 = 脚本形状（BuildScriptEx）
V_PLAY = 0          # 出一张牌就停
V_PLAY_ENEMY = 1    # 出牌 -> 结束回合 -> 敌人出手
V_ROUND = 2         # 出牌 -> 结束回合 -> 走完一轮回到英雄
V_TWICE = 3         # 连出两张 -> 结束回合
V_CYCLE = 4         # 出牌 -> 走完一轮 -> 再出一张
V_CONTROL = 5       # 什么都不做，直接结束回合
V_ENDTURN = 6       # 出牌 -> 结束回合（队列卡的解析窗口）
V_BOOKKEEP = 7      # 只走回合/轮次

STATUS_AXIS = ["strength", "vulnerable", "weak", "dexterity", "frail"]


def load_library():
    for path in sorted(glob.glob(os.path.join(PUBLISH, "*.dll"))):
        try:
            lib = ctypes.CDLL(path)
            getattr(lib, "rd_oracle_run")
            getattr(lib, "rd_oracle_run_ex")
        except (OSError, AttributeError):
            continue
        for name, arity in INT_FUNCS.items():
            fn = getattr(lib, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int] * arity
        return lib, path
    print(f"!! {PUBLISH} 里没有可用的库（含 rd_oracle_run_ex 的版本）")
    sys.exit(1)


def _read(fn_len, fn_char):
    return "".join(chr(fn_char(i)) for i in range(fn_len()))


def hash_of(lib):
    return _read(lib.rd_oracle_hash_len, lib.rd_oracle_hash_char)


def error_of(lib):
    return _read(lib.rd_oracle_error_len, lib.rd_oracle_error_char)


def detail_of(lib):
    return _read(lib.rd_oracle_text_len, lib.rd_oracle_text_char)


def hash_input_of(lib):
    return _read(lib.rd_oracle_hash_input_len, lib.rd_oracle_hash_input_char)


# ── 观测 ─────────────────────────────────────────────────────────────────────

def parse_detail(raw):
    """detail 是 key=value 用 ';' 分隔；log 永远在最后且内部用 '\\n' 分隔。"""
    fields, log = {}, []
    head, _, tail = raw.partition(";log=")
    for part in head.split(";"):
        k, _, v = part.partition("=")
        fields[k] = v
    if tail:
        for entry in tail.split("\n"):
            if not entry:
                continue
            t, _, msg = entry.partition("@")
            log.append({"type": t, "message": msg})
    return fields, log


def parse_statuses(text):
    """'standard.vulnerable:1/2/0,standard.weak:0/2/0' -> {'standard.vulnerable': (1,2,0)}"""
    out = {}
    for item in filter(None, text.split(",")):
        name, _, rest = item.partition(":")
        parts = rest.split("/")
        stacks = int(parts[0]) if len(parts) > 0 and parts[0] else 0
        duration = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        charges = int(parts[2]) if len(parts) > 2 and parts[2] else 0
        out[name] = {"stacks": stacks, "duration": duration, "charges": charges}
    return out


def parse_party(text):
    """'protector:40/0' -> {'protector': {'hp': 40, 'block': 0}}  （玩家队里英雄以外的成员）"""
    out = {}
    for item in filter(None, text.split(",")):
        name, _, rest = item.partition(":")
        parts = rest.split("/")
        out[name] = {"hp": int(parts[0]) if parts and parts[0] else 0,
                     "block": int(parts[1]) if len(parts) > 1 and parts[1] else 0}
    return out


def obs(lib):
    raw = detail_of(lib)
    fields, log = parse_detail(raw)
    o = {
        "hash": hash_of(lib),
        "steps": lib.rd_oracle_steps(),
        "problems": lib.rd_oracle_problems(),
        "hero_hp": lib.rd_oracle_hero_hp(),
        "enemy_hp": lib.rd_oracle_enemy_hp(),
        "hero_block": lib.rd_oracle_hero_block(),
        "enemy_block": lib.rd_oracle_enemy_block(),
        "hero_ward": lib.rd_oracle_hero_ward(),
        "enemy_ward": lib.rd_oracle_enemy_ward(),
        "energy": lib.rd_oracle_energy(),
        "energy_max": lib.rd_oracle_energy_max(),
        "hand_count": lib.rd_oracle_hand_count(),
        "draw_count": lib.rd_oracle_draw_count(),
        "discard_count": lib.rd_oracle_discard_count(),
        "exhaust_count": lib.rd_oracle_exhaust_count(),
        "queue_count": lib.rd_oracle_queue_count(),
        "enemy_count": lib.rd_oracle_enemy_count(),
        "round": lib.rd_oracle_round(),
        "turn": lib.rd_oracle_turn(),
        "phase": lib.rd_oracle_phase(),
        "result": lib.rd_oracle_result(),
        "played": lib.rd_oracle_played(),
        "random_step": lib.rd_oracle_random_step(),
        "pending": lib.rd_oracle_pending(),
        "log_count": lib.rd_oracle_log_count(),
        "probe_ok": lib.rd_oracle_probe_ok(),
        "hash_input_ok": lib.rd_oracle_hash_input_ok(),
        "hero_stacks": [lib.rd_oracle_hero_stacks(i) for i in range(5)],
        "enemy_stacks": [lib.rd_oracle_enemy_stacks(i) for i in range(5)],
        "enemy_hp_all": [lib.rd_oracle_enemy_hp_at(i) for i in range(lib.rd_oracle_enemy_count())],
        "enemy_block_all": [lib.rd_oracle_enemy_block_at(i) for i in range(lib.rd_oracle_enemy_count())],
        "detail": raw,
        "fields": fields,
        "log": log,
        "log_types": [e["type"] for e in log],
        "hero_statuses": parse_statuses(fields.get("heroStatuses", "")),
        "enemy_statuses": parse_statuses(fields.get("enemyStatuses", "")),
        "party": parse_party(fields.get("party", "")),
    }
    return o


# ── 各入口的薄封装 ───────────────────────────────────────────────────────────

def run_case(lib, variant, seed, hero_hp, card_damage, enemy_hp, enemy_damage):
    """原有入口，签名与语义一个字都没改（golden_v1 靠它）。"""
    n = lib.rd_oracle_run(hero_hp, card_damage, enemy_hp, enemy_damage, seed, variant)
    if n < 0:
        return None, error_of(lib)
    return {
        "hash": hash_of(lib),
        "steps": lib.rd_oracle_steps(),
        "problems": lib.rd_oracle_problems(),
        "hero_hp": lib.rd_oracle_hero_hp(),
        "enemy_hp": lib.rd_oracle_enemy_hp(),
        "round": lib.rd_oracle_round(),
        "turn": lib.rd_oracle_turn(),
        "random_step": lib.rd_oracle_random_step(),
        "pending": lib.rd_oracle_pending(),
        "log_count": lib.rd_oracle_log_count(),
    }, None


def defaults(**kw):
    d = dict(hero_hp=30, card_damage=6, card_hits=1, card_damage_target=1, card_kind=0,
             card_block=0, card_block_target=1, card_ward=0, card_cost=1, queue_on_play=0,
             enemy_hp=12, enemy_damage=5, enemy_count=1,
             hero_strength=0, hero_vulnerable=0, hero_weak=0, hero_dexterity=0, hero_frail=0,
             enemy_strength=0, enemy_vulnerable=0, enemy_weak=0, enemy_dexterity=0, enemy_frail=0,
             draw_per_turn=5, deck_size=3, seed=12345, variant=V_PLAY)
    d.update(kw)
    return d


def call_run_ex(lib, inputs):
    args = [inputs[name] for name in RUN_EX_ARGS]
    n = lib.rd_oracle_run_ex(*args)
    if n < 0:
        return None, error_of(lib)
    return obs(lib), None


def call_probe(lib, name, args):
    n = getattr(lib, name)(*args)
    if n < 0:
        return None, error_of(lib)
    return obs(lib), None


# ── 规格书 §7 的验收向量 ─────────────────────────────────────────────────────
#
# 每条：来源（规格书条目 + 原始 文件:行号）、输入、规格书声称的期望值、实测值、结论。
# verdict:
#   match             实测 == 规格书声称
#   match_with_caveat 数值一致，但需要说明口径差异（写在 note 里）
#   mismatch          实测 != 规格书声称（**不改代码去迁就**，如实记录）
#   not_expressible   当前 ABI 无法表达（reason 里写清为什么、以及补上它需要什么）
#
# 「无法表达」的向量也照样落盘，只不过带 verdict=not_expressible —— 这样"哪些还没验"
# 是机器可读的，而不是靠报告里一句话。

def spec_vector(case, spec, item, source, claim, inputs, run, note="", caveat=None, reason=None):
    return dict(case=case, spec=spec, item=item, source=source, claim=claim,
                inputs=inputs, run=run, note=note, caveat=caveat, reason=reason)


def build_spec_vectors(lib):
    V = []
    A = V.append

    # ── modifier-pipeline.md §7（数值修饰管线） ──────────────────────────────
    A(spec_vector(
        "modp-01", "modifier-pipeline.md", "§7 #1", "tests/.../ModifierPipelineTests.cs:102-122",
        {"enemy_hp": 90}, defaults(hero_hp=100, enemy_hp=100, card_damage=5, hero_strength=2,
                                   enemy_vulnerable=1, seed=42, variant=V_PLAY),
        ("run_ex",),
        note="100 HP 双方；Strength 2 是 Source 阶段，Vulnerable 是 Target 阶段，"
             "先 +2 (=7) 再 ×150/100 (=10)。实测顺序若反会得 9，因此本例真能钉住阶段顺序。"))
    A(spec_vector(
        "modp-02", "modifier-pipeline.md", "§7 #2", "tests/.../ModifierPipelineTests.cs:124-143",
        {"enemy_hp": 90}, defaults(hero_hp=100, enemy_hp=100, card_damage=10, hero_weak=1,
                                   enemy_vulnerable=1, seed=42, variant=V_PLAY),
        ("run_ex",),
        note="10 ×75/100=7，7 ×150/100=10；两步都是整数向下取整。"))
    A(spec_vector(
        "modp-03a", "modifier-pipeline.md", "§7 #3（Strength 变体）",
        "tests/.../DamageAmountModifierTests.cs:37-62",
        {"enemy_hp": 4}, defaults(enemy_hp=12, card_damage=6, hero_strength=2, seed=12345, variant=V_PLAY),
        ("run_ex",), note="6+2=8 → 12-8=4。"))
    A(spec_vector(
        "modp-03b", "modifier-pipeline.md", "§7 #3（+Weak 变体）",
        "tests/.../DamageAmountModifierTests.cs:91-124",
        {"enemy_hp": 6}, defaults(enemy_hp=12, card_damage=6, hero_strength=2, hero_weak=1,
                                  seed=12345, variant=V_PLAY),
        ("run_ex",), note="6+2=8 → ×75/100=6 → 12-6=6。"))
    A(spec_vector(
        "modp-04", "modifier-pipeline.md", "§7 #4", "tests/.../DamageAmountModifierTests.cs:126-151",
        {"enemy_hp": 7}, defaults(enemy_hp=12, card_damage=5, card_hits=1, card_kind=1,
                                  hero_strength=5, seed=12345, variant=V_PLAY),
        ("run_ex",),
        note="card_kind=1 = DamageKind.DamageOverTime。PassiveModifierSpec 默认 "
             "RestrictDamageKind=Direct，所以 Strength 5 一点不加：12-5=7。"))
    A(spec_vector(
        "modp-05", "modifier-pipeline.md", "§7 #5", "tests/.../VulnerableStatusTests.cs:52-85",
        {"enemy_hp": 8, "enemy_block": 0},
        defaults(enemy_hp=12, enemy_vulnerable=1, card_damage=6, card_block=5, card_block_target=1,
                 seed=12345, variant=V_PLAY),
        ("run_ex",),
        note="先修饰 6×1.5=9，再吃 5 点格挡 → 掉 4 血。同一张牌里 GainBlock 节点排在 "
             "DealDamage 之前（Sequence 子节点按序入队、队列 FIFO 排空），所以格挡在伤害结算时已经站在那里。",
        caveat="引用的 C# 测试用 AddDefensivePool 直接播种 5 点格挡；这里用同一张牌的 GainBlock 节点"
               "建立格挡（同一回合内、跨不过回合开始的清空格挡），吸收算式完全相同。"))
    A(spec_vector(
        "modp-05b", "modifier-pipeline.md", "§7 #5（日志断言）", "tests/.../VulnerableStatusTests.cs:52-85",
        {"log_contains": ["Dealt 4 damage to 'foe0'", "blocked 5 damage"]},
        defaults(enemy_hp=12, enemy_vulnerable=1, card_damage=6, card_block=5, card_block_target=1,
                 seed=12345, variant=V_PLAY),
        ("run_ex",), note="规格书顺带声称日志里是 'Dealt 4 damage' + 'blocked 5 damage'。"))
    A(spec_vector(
        "modp-06", "modifier-pipeline.md", "§7 #6", "tests/.../VulnerableStatusTests.cs:133-170",
        {"enemy_hp": 3}, defaults(enemy_hp=12, card_damage=6, hero_strength=2, hero_weak=1,
                                  enemy_vulnerable=1, seed=12345, variant=V_PLAY),
        ("run_ex",), note="(6+2)=8 → ×75/100=6 → ×150/100=9 → 12-9=3。"))
    A(spec_vector(
        "modp-07a", "modifier-pipeline.md", "§7 #7", "tests/.../DefensivePoolAbsorptionTests.cs:23-38",
        {"hero_hp": 20, "hero_block": 0, "hero_ward": 2},
        defaults(hero_hp=20, card_damage=6, card_damage_target=0, card_block=5, card_block_target=0,
                 card_ward=3, card_cost=0, seed=12345, variant=V_PLAY),
        ("run_ex",),
        note="oracle.ward 池以 AbsorbPriority=10 注册，严格排在 Block(0) 之后；"
             "Block 先吸 5，剩 1 落到 ward（3→2），HP 不动。"))
    A(spec_vector(
        "modp-07b", "modifier-pipeline.md", "§7 #7（真伤变体）",
        "tests/.../DefensivePoolAbsorptionTests.cs:57-72",
        {"hero_hp": 14, "hero_block": 5, "hero_ward": 3},
        defaults(hero_hp=20, card_damage=6, card_damage_target=0, card_kind=2, card_block=5,
                 card_block_target=0, card_ward=3, card_cost=0, seed=12345, variant=V_PLAY),
        ("run_ex",),
        note="card_kind=2 = Direct + IgnoresBlock（引擎里「真伤」就是 IgnoresBlock，"
             "没有 DamageKind.True 这个成员）。两个池都不动，6 点全落 HP。"))
    A(spec_vector(
        "modp-08a", "modifier-pipeline.md", "§7 #8（Phoenix：致命一击被挡下）",
        "tests/.../PreDownInterceptionTests.cs:64-88",
        {"hero_hp": 25, "phoenix_charges": 0},
        {"hero": "40/50", "marker": "oracle.phoenix 1 充能", "damage": 100},
        ("probe_pre_down", 0, 1, 12345),
        note="英雄 40/50 戴 1 充能标记，吃一发 100：S6 在「即将从活着变成 0」时问到拦截器，"
             "Prevent(Max/2)=25 且充能消耗掉（状态被移除）。",
        caveat="RogueDeck.Core **没有**任何公开的 IPreDownInterceptor 实现（唯一那个在 "
               "RogueDeck.Sandbox.Combat 且是 internal），所以拦截器是本工程自己写的 "
               "PhoenixStyleInterceptor（~15 行，语义与引用测试里的 PhoenixInterceptor 相同："
               "消耗标记充能 + Prevent(Max/2)）。"))
    A(spec_vector(
        "modp-08b", "modifier-pipeline.md", "§7 #8（第二次致命一击不再被挡）",
        "tests/.../PreDownInterceptionTests.cs:64-88",
        {"hero_hp": 0, "phoenix_charges": 0},
        {"hero": "40/50", "marks": 1, "damage": 100, "hits": 2},
        ("probe_pre_down", 0, 2, 12345),
        note="同一张牌两段 100：第一段被 Prevent 到 25 并花掉充能，第二段没有充能可花 ⇒ 12 血直接倒地。"
             "**「充能是一次性的」这条断言由此得到实证**（第二段完全没被拦）。",
        caveat="引用测试还断言状态实例被移除（`DoesNotContain(hero.Statuses, phoenix)`），"
               "实测**没有**被移除：它是 0 充能地留在身上（`hero_status_ids` 里仍在）。"
               "原因是拦截器必须**同步**改充能才能挡住同一张牌的第二段（引用测试也是这么做的），"
               "而引擎的「充能掉到 0 就移除状态」发生在它自己的扣充能路径上，不走那条路就不会清。"
               "行为部分（不再拦截）完全吻合，只有「实例是否消失」这一条存在差异 —— 这条差异对"
               "移植方是有价值的：状态清理是**引擎动作**的副作用，不是状态字段的性质。"))
    A(spec_vector(
        "modp-09", "modifier-pipeline.md", "§7 #9（Martyr：整笔重定向）",
        "tests/.../PreDownInterceptionTests.cs:90-114",
        {"hero_hp": 5, "party_protector_hp": 40},
        {"hero": "5/5", "protector": "50/50 + oracle.martyr 1 层", "damage": 10},
        ("probe_pre_down", 1, 1, 12345),
        note="5 血的英雄挨 10 点：戴着标记的 50 血盟友 Redirect 走**整笔**伤害 ⇒ 英雄一点没掉（5），"
             "保护者 50→40。",
        caveat="同样需要自带的 MartyrStyleInterceptor（Core 无公开实现）。"
               "另外引用测试里「盟友」就是 hero_001，这里用真正的 AllyBlueprint 出场。"))
    A(spec_vector(
        "modp-10", "modifier-pipeline.md", "§7 #10", "tests/.../PreventionPriorityTests.cs:24-34,51-62",
        {"oracle.fear.stacks": 1, "oracle.toll.stacks": 0},
        {"kind": 0}, ("probe_intercept", 0, 12345),
        note="用 StatusBlueprint.Prevention（StatusPreventionSpec(Debuffs, StacksPerStack=1)）声明"
             "「逐层吃掉」的禁令，引擎自带的 DeclarativeStatusPreventionInterceptor 干活。"))
    A(spec_vector(
        "modp-10b", "modifier-pipeline.md", "§7 #10（Charge 变体）",
        "tests/.../PreventionPriorityTests.cs:51-62",
        {"oracle.fear.stacks": 0, "oracle.charge.stacks": 0, "oracle.toll.stacks": 2},
        {"kind": 1}, ("probe_intercept", 1, 12345),
        note="再加一个 Priority=10、RefusesWholeApplication=true 的 Charge 1 层：优先级更高者先答，"
             "整笔申请被拒，Toll 一次都没轮到。"))
    A(spec_vector(
        "modp-11", "modifier-pipeline.md", "§7 #11", "tests/.../StatusAmplificationTests.cs:18-27",
        {"oracle.curse.stacks": 3, "oracle.register.stacks": 0},
        {"kind": 2}, ("probe_intercept", 2, 12345),
        note="StatusAmplificationSpec()（AddStacks=1, StacksSpent=1）：Register 1 层把 Curse 2 层"
             "放大成 3 层，并消耗掉自己那 1 层。"))
    A(spec_vector(
        "modp-11b", "modifier-pipeline.md", "§7 #11（多持只放大一次）",
        "tests/.../StatusAmplificationTests.cs:44-53",
        {"oracle.curse.stacks": 2, "oracle.register.stacks": 2},
        {"kind": 3}, ("probe_intercept", 3, 12345),
        note="Register 3 层 + Curse 1 层 → Curse 2、Register 2：一次申请只被放大一次。",
        caveat="规格书原文把这条写成「放大替换后重入链，只放大一次」，我按引擎的 "
               "StatusAmplificationSpec 语义（AddStacks/StacksSpent）验证的是「只放大一次」。"))
    A(spec_vector(
        "modp-12", "modifier-pipeline.md", "§7 #12", "tests/.../MechanicalChallengeTests.cs:353-385",
        {}, {}, None,
        reason="需要「每受一次伤害回 1 HP」的触发式程序 + 一张 3 段卡，并断言段间完整结算。"
               "多段卡已能表达（card_hits），但「受伤回血」的反应必须由触发式程序注册到 "
               "DamageReceived 事件上；oracle 目前只在 trigger_order 探针里注册过"
               "「加格挡」这一类触发（覆盖了触发机制本身），没有覆盖「段间结算」这条算术。"))
    A(spec_vector(
        "modp-13", "modifier-pipeline.md", "§7 #13", "tests/.../MechanicalChallengeTests.cs:62-93",
        {}, {}, None,
        reason="需要 CausalSequence + PreviousOutcomeFieldExpression 读 DamageOutcome.HealthLost "
               "（把「实际掉血量」喂给下游治疗）。表达式层能表达，但要把 ResultKey 数据流接起来还需要"
               "一支新的探针；本轮未做（V4 同族，见 eir-V4）。"))
    A(spec_vector(
        "modp-14", "modifier-pipeline.md", "§7 #14", "tests/.../BossEncounterScenarioTests.cs:159-170",
        {"enemy_hp": 54}, defaults(enemy_hp=70, card_damage=6, card_hits=2, hero_strength=2,
                                   enemy_block=0, seed=7777, variant=V_PLAY),
        ("run_ex",),
        note="Boss 70 血、无格挡；两段各 6 伤、每段 +2 → 70-2×8=54。本例用 Strength 2 提供"
             "「每段 +2」，与规格书里的「全局 Brittle Armor 每段 +2」是**不同机制、同一算术**。",
        caveat="规格书的 +2 来自一个注册的全局 IDamageAmountModifier（DamageModifierStage.Global，"
               "有格挡则不加）。本轮是用 Source 阶段的 Strength 复现同一算式，验证的是"
               "「修饰器对多段伤害逐段生效」，不是「全局修饰器与格挡的交互」。"))
    A(spec_vector(
        "modp-15a", "modifier-pipeline.md", "§7 #15（Dexterity）",
        "tests/.../BlockAmountModifierTests.cs:76-102",
        {"hero_block": 7}, defaults(hero_hp=20, card_damage=0, card_hits=0, card_block=5,
                                    card_block_target=0, card_cost=0, hero_dexterity=2,
                                    seed=12345, variant=V_PLAY),
        ("run_ex",), note="GainBlock(5) + Dexterity 2 = 5+2 = 7。"))
    A(spec_vector(
        "modp-15b", "modifier-pipeline.md", "§7 #15（Frail）",
        "tests/.../BlockAmountModifierTests.cs:104-130",
        {"hero_block": 3}, defaults(hero_hp=20, card_damage=0, card_hits=0, card_block=5,
                                    card_block_target=0, card_cost=0, hero_frail=1,
                                    seed=12345, variant=V_PLAY),
        ("run_ex",), note="5×75/100=3（整数向下取整）。"))
    A(spec_vector(
        "modp-15c", "modifier-pipeline.md", "§7 #15（Dexterity+Frail）",
        "tests/.../BlockAmountModifierTests.cs:132-166",
        {"hero_block": 5}, defaults(hero_hp=20, card_damage=0, card_hits=0, card_block=5,
                                    card_block_target=0, card_cost=0, hero_dexterity=2, hero_frail=1,
                                    seed=12345, variant=V_PLAY),
        ("run_ex",), note="(5+2)×75/100 = 5.25 → 5：先加后乘，且整数截断。"))
    A(spec_vector(
        "modp-16a", "modifier-pipeline.md", "§7 #16（同优先级按 Id 排）",
        "tests/.../TriggeredProgramParityTests.cs:334-353",
        {"trigger_order": ["test.aaa", "test.mmm", "test.zzz"]},
        {"priorities": (0, 0, 0)}, ("probe_trigger_order", 0, 0, 0, 12345),
        note="三个触发器按 zzz→aaa→mmm **逆序注册**（证明不是插入序），同优先级 ⇒ 按 Id 序数排。"
             "身份靠各自的格挡量编码：zzz=1、aaa=100、mmm=10000，从日志消息里解出来。"))
    A(spec_vector(
        "modp-16b", "modifier-pipeline.md", "§7 #16（priority 覆盖 Id）",
        "tests/.../TriggeredProgramParityTests.cs:355-373",
        {"trigger_order": ["test.zzz", "test.aaa", "test.mmm"]},
        {"priorities": (0, 5, None)}, ("probe_trigger_order", 0, 5, 9, 12345),
        note="zzz priority=0、aaa priority=5、mmm 被推到 priority=9（原测试只有两个触发器，"
             "这里把第三个停到最后，等价于原测试的两者顺序）。优先级数字小的先跑 ⇒ zzz 在 aaa 之前，"
             "mmm 最后。"))
    A(spec_vector(
        "modp-17", "modifier-pipeline.md", "§7 #17", "tests/.../CombatQueueProcessorTests.cs:56-80",
        {"log_types_head": ["TurnStarted", "TurnEnded", "BlockGained", "DamageDealt"]},
        {"kind": 2, "block": 6, "damage": 10}, ("probe_turn", 20, 12, 6, 10, 12345, 2),
        note="同一 cycle 内 effect 先于 event：TurnStarted/TurnEnded 是回合机写的，"
             "BlockGained/DamageDealt 是两个入队的效果按 FIFO 结算。"))

    # ── combat-state-and-turn.md §7 ──────────────────────────────────────────
    A(spec_vector(
        "cst-V1", "combat-state-and-turn.md", "§7 V1", "tests/.../CombatTurnProcessorTests.cs:50-67",
        {"active": "foe0", "round": 1, "turn": 2, "phase": 0,
         "log_types": ["TurnStarted", "TurnEnded"]},
        {"start": "hero", "script": "StartCurrentTurn -> EndCurrentTurn"},
        ("probe_turn", 20, 12, 0, 0, 12345, 0),
        note="phase 0 = WaitingToStartTurn（EndCurrentTurn 不启动下一位）。"
             "active/round/turn/phase 与日志类型序全部对上。"))
    A(spec_vector(
        "cst-V2", "combat-state-and-turn.md", "§7 V2", "tests/.../CombatTurnProcessorTests.cs:70-85",
        {"active": "knight", "round": 2, "turn": 1, "phase": 0,
         "log_types": ["TurnStarted", "TurnEnded"]},
        {"start": "foe0", "script": "StartCurrentTurn -> EndCurrentTurn"},
        ("probe_turn", 20, 12, 0, 0, 12345, 1),
        note="从敌人开始 ⇒ 轮次回绕，Round 变 2、Turn 回到 1。"))
    A(spec_vector(
        "cst-V3", "combat-state-and-turn.md", "§7 V3", "tests/.../CombatTurnProcessorTests.cs:136-173",
        {"hero_hp": 16, "hero_block": 0, "pending": 0, "active": "foe0",
         "log_types": ["TurnStarted", "TurnEnded", "BlockGained", "DamageDealt"]},
        {"block": 6, "damage": 10},
        ("probe_turn", 20, 12, 6, 10, 12345, 2),
        note="回合结束前先把挂起效果消化掉：6 点格挡吃掉 6 点伤害，剩 4 落 HP（20→16），格挡归零。"
             "探针用的是**只有**两个 handler + Block 池定义的最小注册表（和引用测试一样），"
             "所以日志里没有多余条目。"))
    A(spec_vector(
        "cst-V4", "combat-state-and-turn.md", "§7 V4", "tests/.../CombatQueueProcessorTests.cs:57-80",
        {"log_types_head": ["TurnStarted", "TurnEnded", "BlockGained", "DamageDealt"]},
        {"kind": 2}, ("probe_turn", 20, 12, 6, 10, 12345, 2),
        note="V4 断言「同轮内 effect 先于 event」（CombatLog[0]=BlockGained、[1]=TestEventHandled）。"
             "这里用探针 cst-V3 的同一段日志验证同类顺序：入队效果之间保持 FIFO 且不插队。",
        caveat="引用的测试要注册一个自定义 handler 写 'TestEventHandled' 日志条目；oracle 无法注入"
               "自定义 ICombatEventHandler，所以拿「两个入队效果的结算顺序」做等价观察，"
               "没有复刻那条自造日志。"))
    A(spec_vector(
        "cst-V5", "combat-state-and-turn.md", "§7 V5", "tests/.../CombatQueueProcessorTests.cs:83-103",
        {"throws": True}, {}, None,
        reason="需要一个「每次处理都把自己重新入队」的自定义 handler（EndlessEventHandler），"
               "以及把 CombatExecutionLimits(maxQueueCycles:3) 传给 ResolvePendingQueues。"
               "oracle 侧注入不了自定义 handler；而队列轮转上限（maxQueueCycles）本身"
               "RunFight/探针路径里没有入口。"))
    A(spec_vector(
        "cst-V6", "combat-state-and-turn.md", "§7 V6",
        "tests/.../CombatEffectReentryPolicyTests.cs:8-56",
        {}, {}, None, reason="同上：需要自定义触发的 + 自定义 effect handler + 过滤器实现。"))
    A(spec_vector(
        "cst-V7", "combat-state-and-turn.md", "§7 V7",
        "tests/.../CombatEffectChainDepthLimitTests.cs:50-136", {}, {}, None,
        reason="需要 4 个互相级联的 RoundStarted 触发定义 + 每层一个过滤器，以及 "
               "maximumTriggerDepth 的构造参数。前半段（注册级联触发）能做到；"
               "断言要的是异常消息内容与过滤器计数，oracle 读不到过滤器对象。"))
    A(spec_vector(
        "cst-V8", "combat-state-and-turn.md", "§7 V8",
        "tests/.../CombatEffectChainDepthLimitTests.cs:21-47", {}, {}, None,
        reason="需要捕获 combat.CurrentEffectChain 的自定义 handler（读 TriggerDepth/MaximumTriggerDepth）。"))
    A(spec_vector(
        "cst-V9a", "combat-state-and-turn.md", "§7 V9（重洗消耗随机步数）",
        "tests/.../RngDeterminismTests.cs:24-53",
        {"random_step_gt_zero": True, "hand_equals_engine_shuffle": True, "runs_identical": True},
        {"deck": 5, "draw": 5, "seed": 12345}, ("probe_reshuffle_twice", 5, 5, 12345),
        note="抽空抽牌堆 → 结束回合（手牌丢弃）→ 走完一轮，下一回合的开场抽牌必须重洗弃牌堆。"
             "实测 random_step=1（重洗正好消耗一步），手牌顺序与 "
             "CombatRandom.CreateShuffledIndexes(5,12345,0) 逐位相同，两次跑完全一致。"))
    A(spec_vector(
        "cst-V9b", "combat-state-and-turn.md", "§7 V9（不同 seed 洗出不同序）",
        "tests/.../RngDeterminismTests.cs:24-53",
        {"hand_equals_engine_shuffle": True, "differs_between_seeds": True},
        {"deck": 5, "draw": 5, "seed": 7}, ("probe_reshuffle_twice", 5, 5, 7),
        note="换 seed=7 手牌顺序随之改变，且仍等于引擎自己的洗牌序列（同一向量里还会跑一次 "
             "seed+1 确认「换种子就换顺序」，免得把「确定」误当成「恒定」）。"))
    A(spec_vector(
        "cst-V10a", "combat-state-and-turn.md", "§7 V10（Restore 后哈希恒等）",
        "tests/.../CombatStateRestoreTests.cs:15-34,36-69",
        {"probe_ok": 1}, {"seed": 12345}, ("probe_snapshot", 12345),
        note="state -> snapshot -> Restore -> snapshot 的哈希完全相同，且 RandomStep/Round/Energy "
             "都随快照带过去了（实测 rstep=2、round=2、energy=3）。"))
    A(spec_vector(
        "cst-V10b", "combat-state-and-turn.md", "§7 V10（JSON 存档往返）",
        "tests/.../CombatStateRestoreTests.cs:59-69",
        {}, {}, None,
        reason="CombatSaveJson 用的是 System.Text.Json 的**反射重载**。在 NativeAOT 下两个后果："
               "(1) 编译期冒出 IL2026/IL3050 警告，而本工程的验收线是 0 个 IL2xxx/IL3xxx；"
               "(2) 就算留着也是死路 —— 实测运行时抛 "
               "'Reflection-based serialization has been disabled for this application.'。"
               "所以存档格式这一条本轮**没有覆盖**，改由 W1 的 Rust 侧独立实现（并且这本身是"
               "一条重要的移植结论：引擎的存档路径不是 AOT 友好的）。"))
    A(spec_vector(
        "cst-V10c", "combat-state-and-turn.md", "§7 V10（带临时规则的快照必须拒绝 Restore）",
        "tests/.../CombatStateRestoreTests.cs:87-100", {}, {}, None,
        reason="需要把 TemporaryRules 塞进快照（`snapshot with {...}`）再造一个临时规则定义；"
               "oracle 侧可以构造快照记录，但会牵进 ScenarioBlueprint.OpeningTemporaryRules 的完整链路，"
               "本轮未做。"))
    A(spec_vector(
        "cst-V11a", "combat-state-and-turn.md", "§7 V11（免费卡：伤害 + 进弃牌堆）",
        "tests/.../PlayCardOperationTests.cs:16-65",
        {"enemy_hp": 7, "played": 1, "hand_count": 2, "discard_count": 1},
        defaults(hero_hp=20, enemy_hp=12, card_damage=5, card_cost=0, deck_size=3, draw_per_turn=5,
                 variant=V_PLAY, seed=12345),
        ("run_ex",),
        note="费用 0 ⇒ 白嫖；12-5=7；出的那张牌进弃牌堆、手牌剩 2 张（3 张牌组全抽进手里，"
             "打掉 1 张）。",
        caveat="引用的测试手里只有那一张牌，所以断言 Hand 为空；这里牌组 3 张、开局全抽进手里，"
               "打掉 1 张后剩 2 张。牌落在弃牌堆 + 手牌减少 1 这件事两边一致。"))
    A(spec_vector(
        "cst-V11b", "combat-state-and-turn.md", "§7 V11（付费）",
        "tests/.../PlayCardOperationTests.cs:46-65",
        {"energy": 1}, defaults(hero_hp=20, enemy_hp=12, card_damage=0, card_hits=0,
                                card_cost=2, variant=V_PLAY, seed=12345),
        ("run_ex",), note="3 点能量付 2 费 ⇒ 剩 1。"))
    # cst-V11c：**刻意保留一条"测不出来"的向量**。规格书说能量不足会被拒；本 ABI 的英雄能量
    # 写死 3/3，没法把前置条件摆出来，所以实测会成功出牌。这是一个 mismatch，不是 bug ——
    # 用它证明对拍表真的会报出不一致，而不是什么都"通过"。
    A(spec_vector(
        "cst-V11c", "combat-state-and-turn.md", "§7 V11（能量不足 ⇒ 拒绝）",
        "tests/.../PlayCardOperationTests.cs:114-135",
        {"enemy_hp": 12, "played": 0, "hand_count": 1, "discard_count": 0},
        defaults(hero_hp=20, enemy_hp=12, card_damage=5, card_cost=3, deck_size=3,
                 variant=V_PLAY, seed=12345),
        ("run_ex",),
        note="⚠ 这条**不能**用 run_ex 表达：它的英雄能量固定 3/3，付得起 3 费卡。"
             "所以这条在 run_ex 上会**成功出牌**（实测 enemy_hp=7、played=1），"
             "而不是规格书说的「被拒绝且敌人保持 12」。见下表实测列。",
        reason="本 ABI 没有「起始能量」参数 —— run_ex 把英雄能量写死 3/3，"
               "无法摆出「能量不足」这个前置条件。要么给 run_ex 加一个 energy 参数，"
               "要么写一支直接构造 CardZones/Resources 的探针。"))
    A(spec_vector(
        "cst-V11d", "combat-state-and-turn.md", "§7 V11（卡不在手牌 ⇒ 拒绝）",
        "tests/.../PlayCardOperationTests.cs:114-155", {}, {}, None,
        reason="要把卡放进 DrawPile 而不是 Hand；run_ex 的牌组开局都会抽进手里。"
               "真要做到需要一支直接构造 CardZones 的探针。"))
    A(spec_vector(
        "cst-V12a", "combat-state-and-turn.md", "§7 V12（入队付费即时、效果延后）",
        "RogueDeck.Sandbox.Tests/QueueTortureTests.cs:169-192",
        {"energy": 2, "enemy_hp": 200, "queue_count": 1},
        defaults(hero_hp=200, enemy_hp=200, card_damage=13, card_cost=1, queue_on_play=1,
                 enemy_damage=1, variant=V_PLAY, seed=1),
        ("run_ex",), note="QueueOnPlay 卡：出牌即付费（3→2）、卡进 Queue、**伤害一点没落**（敌方仍 200）。"))
    A(spec_vector(
        "cst-V12b", "combat-state-and-turn.md", "§7 V12（走完一轮后解析）",
        "RogueDeck.Sandbox.Tests/QueueTortureTests.cs:169-192",
        {"enemy_hp": 187, "queue_count": 0},
        defaults(hero_hp=200, enemy_hp=200, card_damage=13, card_cost=1, queue_on_play=1,
                 enemy_damage=1, variant=V_ROUND, seed=1),
        ("run_ex",),
        note="出牌 → 结束回合 → 走完一轮（回到英雄下一回合）：队列排空、13 点伤害落地（200→187）。"
             "**这条的解析时机是个坑**：见 cst-V12c —— 单单一次 EndTurn 是不够的。",
        caveat="引用的沙盒测试里英雄 200/200、能量 9/9、敌人 200；这里英雄 200、能量 3/3。"
               "它的 EndTurn 走完了整轮，所以队列在英雄的下一个回合开始时解析；"
               "规格书写「EndTurn 后敌方 -13、Queue 空」在「只结束一位战斗员的回合」这个口径下不成立。"))
    A(spec_vector(
        "cst-V12c", "combat-state-and-turn.md", "§7 V12（只 EndTurn 一次 ⇒ 还不解析）",
        "RogueDeck.Sandbox.Tests/QueueTortureTests.cs:169-192",
        {"enemy_hp": 200, "queue_count": 1},
        defaults(hero_hp=200, enemy_hp=200, card_damage=13, card_cost=1, queue_on_play=1,
                 enemy_damage=1, variant=V_ENDTURN, seed=1),
        ("run_ex",),
        note="**这是一条有意留下的反差行**：同样的局面，只调用一次 HeroEndsTurn（= 结束英雄回合、"
             "启动敌人回合），队列里那张牌**仍然在等**，敌人还是 200 血。"
             "引擎的解析窗口是「拥有者的下一个回合开始」，所以规格书/沙盒里那句"
             "「EndTurn 后 Queue 空」必须理解成「走完一整轮之后的回合开始」，而不是字面上的 EndTurn。"))
    A(spec_vector(
        "cst-V13a", "combat-state-and-turn.md", "§7 V13（法令：未花完带进明天）",
        "tests/.../CombatDecreeTests.cs:130-143",
        {"energy": 5, "energy_max": 3},
        {"rule": "UnspentResourceCarries", "start": 2, "max": 3},
        ("probe_decree", 1, 0, 2, 3, 5, 12, 0, 200, 12345, 0),
        note="戴着法令结束回合：回合开始的补充是**加**在剩下的 2 点上（2+3=5），"
             "而且池允许暂时超过自己的上限（Max 仍是 3）。"))
    A(spec_vector(
        "cst-V13b", "combat-state-and-turn.md", "§7 V13（不戴法令 ⇒ 覆盖）",
        "tests/.../CombatDecreeTests.cs:174-185",
        {"energy": 3, "energy_max": 3},
        {"rule": "none", "start": 2, "max": 3},
        ("probe_decree", 0, 0, 2, 3, 5, 12, 0, 200, 12345, 0),
        note="同样的局面但不戴法令 ⇒ 补充是**覆盖**：2 → 3。这一条是 V13 的反例，"
             "它和 V13a 只差一个法令，正好钉死「法令改变了规则而不是数字」。"))
    A(spec_vector(
        "cst-V13c", "combat-state-and-turn.md", "§7 V13（超上限的能量照样花得掉）",
        "tests/.../CombatDecreeTests.cs:145-172",
        {"energy": 2}, {"rule": "UnspentResourceCarries", "start": 3, "max": 3, "plays": 4},
        ("probe_decree", 1, 0, 3, 3, 5, 12, 1, 200, 12345, 1),
        note="补充后手上 6 点（上限 3），连出 4 张 1 费牌 ⇒ 6→5→4→3→2。"))
    A(spec_vector(
        "cst-V14", "combat-state-and-turn.md", "§7 V14（法令：手牌上限）",
        "tests/.../CombatDecreeTests.cs:203-214",
        {"drawn": 3, "draw_count": 7},
        {"rule": "MaxHandSize(3)", "deck": 10, "draw_per_turn": 5},
        ("probe_decree", 2, 3, 3, 3, 5, 10, 0, 200, 12345, 2),
        note="上限 3、牌堆 10 张、本该抽 5：实测**实抽 3 张**（手牌 2 + 本回合打出去 1 张）、"
             "抽牌堆留 7 张。抽牌堆 7 与规格书的断言一致，实抽 3 张也一致；"
             "手牌显示 2 是因为探针必须「出一张牌」才能在不结束回合的前提下把回合开起来。",
        caveat="规格书断言 Hand.Count==3。本探针读到的状态里那张开局牌已经在弃牌堆，"
               "所以手牌少 1；把「实抽张数」折算进去（2+1=3）与规格书一致。"))

    # ── effect-program-ir.md §7 ──────────────────────────────────────────────
    A(spec_vector(
        "eir-V1a", "effect-program-ir.md", "§7 V1（Abs）",
        "tests/.../EffectProgramConditionalTests.cs:10-15",
        {"value": 3}, {"expr": "Abs(-3)"}, ("probe_expr", 0, -3, 0, 0),
        note="把表达式当作一张牌的**伤害量**，敌人的剩余 HP 就反推出表达式的值（12 - HP）。"))
    A(spec_vector(
        "eir-V1b", "effect-program-ir.md", "§7 V1（Divide 10/3）",
        "tests/.../EffectProgramPhase3ExpressionTests.cs:24-31",
        {"value": 3}, {"expr": "Divide(10,3)"}, ("probe_expr", 1, 10, 3, 0)))
    A(spec_vector(
        "eir-V1c", "effect-program-ir.md", "§7 V1（Divide 10/0 默认返回 0）",
        "tests/.../EffectProgramPhase3ExpressionTests.cs:33-40",
        {"value": 0, "problems": 0}, {"expr": "Divide(10,0) 默认策略"},
        ("probe_expr", 1, 10, 0, 0)))
    A(spec_vector(
        "eir-V1d", "effect-program-ir.md", "§7 V1（Divide 10/0 + Fault 策略抛异常）",
        "tests/.../EffectProgramPhase3ExpressionTests.cs:42-50",
        {"throws": True}, {"expr": "Divide(10,0,DivideByZeroPolicy.Fault)"},
        ("probe_expr", 1, 10, 0, 1),
        note="抛异常 → ScenarioRunner 记成 problem，敌人血量不动（12）。"))
    A(spec_vector(
        "eir-V1e", "effect-program-ir.md", "§7 V1（Remainder）",
        "tests/.../EffectProgramPhase3ExpressionTests.cs:52-68",
        {"value": 1}, {"expr": "Remainder(10,3)"}, ("probe_expr", 2, 10, 3, 0)))
    A(spec_vector(
        "eir-V1f", "effect-program-ir.md", "§7 V1（Clamp）",
        "tests/.../EffectProgramPhase3ExpressionTests.cs:70-98",
        {"value_min": 0, "value_max": 10, "value_mid": 7},
        {"expr": "Clamp(-5,0,10) / Clamp(15,0,10) / Clamp(7,0,10)"},
        ("probe_expr_clamp", (3, -5, 0, 10), (3, 15, 0, 10), (3, 7, 0, 10))))
    A(spec_vector(
        "eir-V2", "effect-program-ir.md", "§7 V2",
        "tests/.../EffectProgramConditionalTests.cs:128-150", {}, {}, None,
        reason="断言的是「And/Or 的右侧 SideEffectExpression 没有被求值」。判定需要观察副作用，"
               "而 SideEffectNode/SideEffectExpression 是测试专用类型（还要 AllowUnsafeSideEffects）。"
               "从外部无法观测「没被求值」。"))
    A(spec_vector(
        "eir-V3a", "effect-program-ir.md", "§7 V3（条件真 → Then）",
        "tests/.../EffectProgramConditionalTests.cs:154-180",
        {"enemy_hp": 6}, {"cond": True, "then": 6},
        ("probe_conditional", 1, 6, -1)))
    A(spec_vector(
        "eir-V3b", "effect-program-ir.md", "§7 V3（条件假 → Else）",
        "tests/.../EffectProgramConditionalTests.cs:182-198",
        {"enemy_hp": 10}, {"cond": False, "then": 6, "else": 2},
        ("probe_conditional", 0, 6, 2)))
    A(spec_vector(
        "eir-V3c", "effect-program-ir.md", "§7 V3（条件假、无 Else）",
        "tests/.../EffectProgramConditionalTests.cs:200-210",
        {"enemy_hp": 12}, {"cond": False, "then": 6, "else": None},
        ("probe_conditional", 0, 6, -1)))
    A(spec_vector(
        "eir-V4", "effect-program-ir.md", "§7 V4（Shatter）",
        "tests/.../EffectProgramConditionalTests.cs:241-323", {}, {}, None,
        reason="需要 CausalSequence + ModifyDefensivePool 的 ResultKey + "
               "PreviousOutcomeFieldExpression 读 PoolChangeOutcome.AppliedDelta 的绝对值。"
               "整条数据流在引擎里是构造期类型检查的，能表达；但要把 ResultKey 接起来还需要一支"
               "新探针（本轮做了同族的表达式/控制流探针，没有做 ResultKey 数据流）。"))
    A(spec_vector(
        "eir-V5", "effect-program-ir.md", "§7 V5（Repeat 的计数只求值一次）",
        "tests/.../EffectProgramRepeatTests.cs:118-145",
        {"enemy_hp": 9, "problems": 0}, {"count": 3, "damage": 1},
        ("probe_repeat", 3, 32, 1),
        note="3 段各 1 点 ⇒ 12-3=9。「计数只求值一次」这一半需要一支副作用计数器表达式，"
             "本轮只验了「3 段真的打了 3 次、每次独立结算」。",
        caveat="规格书 V5 的主要断言是 callCount==1（计数表达式只算一次）。那个需要测试专用的 "
               "LambdaExpression<Ctx> 副作用计数器，无法从外部观察；这里验的是它的数值后果。"))
    A(spec_vector(
        "eir-V6a", "effect-program-ir.md", "§7 V6（负计数抛异常）",
        "tests/.../EffectProgramRepeatTests.cs:192-215",
        {"throws": True}, {"count": -1}, ("probe_repeat", -1, 32, 1),
        note="实测异常消息：'RepeatEffectNode evaluated a negative count (-1).'"))
    A(spec_vector(
        "eir-V6b", "effect-program-ir.md", "§7 V6（超 maxCount 抛异常）",
        "tests/.../EffectProgramRepeatTests.cs:217-228",
        {"throws": True}, {"count": 10, "maxCount": 5}, ("probe_repeat", 10, 5, 1),
        note="实测异常消息：'RepeatEffectNode evaluated count 10 which exceeds the configured maximum of 5.'"))
    A(spec_vector(
        "eir-V6c", "effect-program-ir.md", "§7 V6（正好等于 maxCount 不抛）",
        "tests/.../EffectProgramRepeatTests.cs:229-247",
        {"enemy_hp": 7, "problems": 0}, {"count": 5, "maxCount": 5, "damage": 1},
        ("probe_repeat", 5, 5, 1)))
    A(spec_vector(
        "eir-V7", "effect-program-ir.md", "§7 V7（ForEach：按各自中毒层数打伤害）",
        "tests/.../EffectProgramForEachTests.cs:173-194",
        {"enemy_hp_all": [9, 12, 7]}, {"poison": [3, 0, 5], "hp": [12, 12, 12]},
        ("probe_for_each", 3, 0, 5, 12, 12, 12, 1),
        note="ForEach(AllEnemiesOfSource) + IterationTargetHasStatus + "
             "IterationTargetStatusStacks：每只敌人被打掉**自己**的中毒层数。"))
    A(spec_vector(
        "eir-V8a", "effect-program-ir.md", "§7 V8（顺序稳定、各挨一次）",
        "tests/.../EffectProgramForEachTests.cs:196-224",
        {"enemy_hp_all": [8, 8, 8]}, {"poison": [2, 2, 2], "hp": [10, 10, 10]},
        ("probe_for_each", 2, 2, 2, 10, 10, 10, 1)))
    A(spec_vector(
        "eir-V8b", "effect-program-ir.md", "§7 V8（迭代中早死不停后续）",
        "tests/.../EffectProgramForEachTests.cs:226-249",
        {"enemy_hp_all": [0, 12, 8]}, {"poison": [3, 0, 4], "hp": [1, 12, 12]},
        ("probe_for_each", 3, 0, 4, 1, 12, 12, 1),
        note="A 只有 1 血、中毒 3 ⇒ 迭代 0 就死；B、C 照常处理。"))
    A(spec_vector(
        "eir-V9a", "effect-program-ir.md", "§7 V9a（全局步数上限）",
        "tests/.../EffectProgramExecutionLimitTests.cs:101-125",
        {"throws": True}, {"shape": "Repeat(4,Repeat(4,NoOp))", "maxProgramSteps": 10},
        ("probe_program_steps", 0, 10),
        note="实测异常：'Effect program 'card:strike:on-play' exceeded the maximum of 10 program steps (step 11).'"))
    A(spec_vector(
        "eir-V9b", "effect-program-ir.md", "§7 V9a（正好卡在上限内不抛）",
        "tests/.../EffectProgramExecutionLimitTests.cs:127-147",
        {"problems": 0}, {"shape": "Repeat(3,NoOp)", "maxProgramSteps": 4},
        ("probe_program_steps", 1, 4),
        note="规格书还断言 ProgramStepCount==4；步数计数器长在 EffectExecutionContext 上，"
             "而卡牌程序的上下文是引擎内部构造的，外部读不到 ⇒ 只验了「不抛」。",
        caveat="实测只覆盖「不抛」这一半。"))
    A(spec_vector(
        "eir-V9c", "effect-program-ir.md", "§7 V9b（MaxActiveScopes 上限）",
        "tests/.../EffectProgramExecutionLimitTests.cs:174-196", {}, {}, None,
        reason="MaxActiveScopes 是 EffectExecutionContext 上的可写属性（默认 32），"
               "卡牌程序路径下上下文由引擎内部构造，外部改不到它 ⇒ 本 ABI 无法表达。"))
    A(spec_vector(
        "eir-V10a", "effect-program-ir.md", "§7 V10（同优先级按 Id）",
        "tests/.../TriggeredProgramParityTests.cs:334-353",
        {"trigger_order": ["test.aaa", "test.mmm", "test.zzz"]},
        {"priorities": (0, 0, 0)}, ("probe_trigger_order", 0, 0, 0, 12345)))
    A(spec_vector(
        "eir-V10b", "effect-program-ir.md", "§7 V10（priority 覆盖 Id）",
        "tests/.../TriggeredProgramParityTests.cs:355-373",
        {"trigger_order": ["test.zzz", "test.aaa", "test.mmm"]},
        {"priorities": (0, 5, None)}, ("probe_trigger_order", 0, 5, 9, 12345)))
    A(spec_vector(
        "eir-V11", "effect-program-ir.md", "§7 V11（Causal vs 批量 Sequence）",
        "tests/.../EffectProgramCausalSequenceTests.cs:46-97", {}, {}, None,
        reason="需要「英雄受伤则获 10 格挡」的反应式触发（自定义 ICombatEventHandler 实现 "
               "DamageReceived 反应），并比较 Causal[5,10] 与 Sequence[5,10] 的差别。"
               "触发注册本身能做到（见 V10），但那条反应需要一支专门写 ICombatEventHandler 的探针。"))
    A(spec_vector(
        "eir-V12", "effect-program-ir.md", "§7 V12（Build→Classify 往返恒等）",
        "tests/.../CombatProgramModelTests.cs:43-69", {}, {}, None,
        reason="断言的是作者层模型对象的**结构相等**（CombatNodeModel 的 Equals），不是战斗数值。"
               "要用它就得把 CombatNodeModel 整体搬进 oracle 的 ABI，而它是个 49 个参数的记录；"
               "性价比不划算。规格书的结论（往返恒等）本身与内核移植无关。"))

    # 执行
    results = []
    for v in V:
        if v["run"] is None:
            results.append(dict(case=v["case"], spec=v["spec"], item=v["item"], source=v["source"],
                                claim=v["claim"] or None, inputs=v["inputs"] or None,
                                measured=None, verdict="not_expressible",
                                reason=v["reason"], note=v["note"]))
            continue
        args = v["run"]
        kind = args[0]
        try:
            measured = execute_vector(lib, kind, v["inputs"], args)
        except Exception as exc:                                  # noqa: BLE001
            measured = {"harness_error": f"{type(exc).__name__}: {exc}"}
        verdict, diffs = judge(v["claim"], measured)
        if verdict == "match" and v["caveat"]:
            verdict = "match_with_caveat"
        results.append(dict(case=v["case"], spec=v["spec"], item=v["item"], source=v["source"],
                            claim=v["claim"], inputs=v["inputs"], measured=measured,
                            verdict=verdict, diffs=diffs, note=v["note"], caveat=v["caveat"]))
    return results


def execute_vector(lib, kind, inputs, args):
    """把向量的输入翻译成一次 ABI 调用，并把结果整理成「可直接与 claim 比」的字典。"""
    if kind == "run_ex":
        o, err = call_run_ex(lib, inputs)
        if o is None:
            return {"error": err}
        return summarize(o)

    if kind == "probe_expr":
        o, err = call_probe(lib, "rd_oracle_probe_expr", [args[1], args[2], args[3], args[4]])
        if o is None:
            return {"error": err}
        s = summarize(o)
        s["value"] = (12 - o["enemy_hp"]) if o["problems"] == 0 else 0
        s["throws"] = o["problems"] != 0
        return s

    if kind == "probe_expr_clamp":
        out = {"throws": False}
        keys = ["value_min", "value_max", "value_mid"]
        for key, call in zip(keys, args[1:]):
            o, err = call_probe(lib, "rd_oracle_probe_expr", list(call))
            if o is None:
                return {"error": err}
            out[key] = 12 - o["enemy_hp"] if o["problems"] == 0 else None
            out["problems"] = o["problems"]
        return out

    if kind == "probe_conditional":
        o, err = call_probe(lib, "rd_oracle_probe_conditional", list(args[1:]))
        return {"error": err} if o is None else summarize(o)

    if kind == "probe_repeat":
        o, err = call_probe(lib, "rd_oracle_probe_repeat", list(args[1:]))
        if o is None:
            return {"error": err}
        s = summarize(o)
        s["throws"] = o["problems"] != 0
        return s

    if kind == "probe_program_steps":
        o, err = call_probe(lib, "rd_oracle_probe_program_steps", list(args[1:]))
        if o is None:
            return {"error": err}
        s = summarize(o)
        s["throws"] = o["problems"] != 0
        return s

    if kind == "probe_for_each":
        o, err = call_probe(lib, "rd_oracle_probe_for_each", list(args[1:]))
        return {"error": err} if o is None else summarize(o)

    if kind == "probe_decree":
        o, err = call_probe(lib, "rd_oracle_probe_decree", list(args[1:]))
        if o is None:
            return {"error": err}
        s = summarize(o)
        # variant 2 靠「出一张牌」来开启回合，那张牌已经离开手牌落到弃牌堆；
        # 手牌 + 弃牌堆 = 这一回合真正抽上来的张数。
        s["drawn"] = s["hand_count"] + s["discard_count"]
        return s

    if kind == "probe_reshuffle_twice":
        _, deck, draw, seed = args
        raws, runs = [], []
        for _ in range(2):
            o, err = call_probe(lib, "rd_oracle_probe_reshuffle", [deck, draw, seed])
            if o is None:
                return {"error": err}
            raws.append(o)
            runs.append(summarize(o))
        engine = [lib.rd_oracle_shuffle(deck, seed, 0, i) for i in range(deck)]
        hands = [[c for c in raw["fields"].get("hand", "").split(",") if c] for raw in raws]
        expected = ["c%d" % i for i in engine]
        # 再跑一次**换 seed** 的：手牌顺序必须随之改变（否则"确定性"其实是"常数"）。
        other, err = call_probe(lib, "rd_oracle_probe_reshuffle", [deck, draw, seed + 1])
        other_hand = [c for c in other["fields"].get("hand", "").split(",") if c] if other else None
        return {
            "random_step": runs[0]["random_step"],
            "random_step_gt_zero": runs[0]["random_step"] > 0,
            "hand": hands[0],
            "engine_shuffle": expected,
            "hand_equals_engine_shuffle": hands[0] == expected,
            "runs_identical": runs[0]["hash"] == runs[1]["hash"] and hands[0] == hands[1],
            "different_seed_hand": other_hand,
            "differs_between_seeds": other_hand is not None and other_hand != hands[0],
            "hash": runs[0]["hash"],
        }

    if kind == "probe_trigger_order":
        o, err = call_probe(lib, "rd_oracle_probe_trigger_order", list(args[1:]))
        if o is None:
            return {"error": err}
        amounts = {1: "test.zzz", 100: "test.aaa", 10000: "test.mmm"}
        order = []
        for entry in o["log"]:
            if entry["type"] != "BlockGained":
                continue
            # 只取 "Gained <N> block" 里的 N —— 整条消息里所有数字连起来是不行的，
            # 因为 "'foe0'" 里的 0 会被粘上（100 → 1000），第一版就是这么错的。
            found = re.search(r"Gained (\d+) block", entry["message"])
            if found and int(found.group(1)) in amounts:
                order.append(amounts[int(found.group(1))])
        s = summarize(o)
        s["trigger_order"] = order
        return s

    if kind == "probe_snapshot":
        o, err = call_probe(lib, "rd_oracle_probe_snapshot", list(args[1:]))
        if o is None:
            return {"error": err}
        s = summarize(o)
        fields = o["fields"]
        s["hash_direct"] = fields.get("snap_direct")
        s["hash_restored"] = fields.get("snap_restore")
        s["probe_ok"] = o["probe_ok"]
        return s

    if kind == "probe_turn":
        o, err = call_probe(lib, "rd_oracle_probe_turn", list(args[1:]))
        if o is None:
            return {"error": err}
        s = summarize(o)
        s["active"] = o["fields"].get("active")
        return s

    if kind == "probe_intercept":
        o, err = call_probe(lib, "rd_oracle_probe_intercept", list(args[1:]))
        if o is None:
            return {"error": err}
        s = summarize(o)
        # 层数掉到 0 的状态实例会被引擎整个移除，所以「看不见」就等于 0 层。
        for name in ("oracle.fear", "oracle.curse", "oracle.toll", "oracle.charge", "oracle.register"):
            s[name + ".stacks"] = 0
        for name, st in o["hero_statuses"].items():
            s[name + ".stacks"] = st["stacks"]
        return s

    if kind == "probe_pre_down":
        o, err = call_probe(lib, "rd_oracle_probe_pre_down", list(args[1:]))
        if o is None:
            return {"error": err}
        s = summarize(o)
        s["hero_status_ids"] = sorted(o["hero_statuses"].keys())
        s["phoenix_charges"] = o["hero_statuses"].get("oracle.phoenix", {}).get("charges", 0)
        for name, stats in o["party"].items():
            s["party_" + name + "_hp"] = stats["hp"]
        return s

    raise AssertionError(f"unknown vector kind {kind}")


def summarize(o):
    """把 obs() 缩成对拍关心的那一层；log 只留类型序 + 前若干条消息。"""
    s = {
        "hash": o["hash"],
        "steps": o["steps"], "problems": o["problems"],
        "hero_hp": o["hero_hp"], "enemy_hp": o["enemy_hp"],
        "hero_block": o["hero_block"], "enemy_block": o["enemy_block"],
        "hero_ward": o["hero_ward"], "enemy_ward": o["enemy_ward"],
        "energy": o["energy"], "energy_max": o["energy_max"],
        "hand_count": o["hand_count"], "draw_count": o["draw_count"],
        "discard_count": o["discard_count"], "exhaust_count": o["exhaust_count"],
        "queue_count": o["queue_count"],
        "enemy_count": o["enemy_count"],
        "enemy_hp_all": o["enemy_hp_all"], "enemy_block_all": o["enemy_block_all"],
        "round": o["round"], "turn": o["turn"], "phase": o["phase"], "result": o["result"],
        "played": o["played"], "random_step": o["random_step"], "pending": o["pending"],
        "log_count": o["log_count"], "log_types": o["log_types"],
        "hero_statuses": o["hero_statuses"], "enemy_statuses": o["enemy_statuses"],
        "probe_ok": o["probe_ok"],
        "hash_input_ok": o["hash_input_ok"],
    }
    s["log_contains"] = [e["message"] for e in o["log"]]
    return s


def judge(claim, measured):
    """逐键比对。log_contains / log_types_head 之类是子序列断言。
    键在实测里**缺失**一律算不一致 —— 否则 "expected is True" 这种断言会因为
    measured.get() 返回 None 而被悄悄放过（本文件第一版就踩过这个坑）。"""
    if not claim:
        return "match", {}
    diffs = {}
    for key, expected in claim.items():
        if key == "log_contains":
            haystack = measured.get("log_contains") or []
            joined = "\n".join(haystack)
            missing = [needle for needle in expected if needle not in joined]
            if missing:
                diffs[key] = {"missing": missing}
            continue
        if key == "log_types_head":
            got = (measured.get("log_types") or [])[:len(expected)]
            if got != list(expected):
                diffs[key] = {"expected": list(expected), "actual": got}
            continue
        if key not in measured:
            diffs[key] = {"expected": expected, "actual": "<键缺失>"}
            continue
        got = measured[key]
        if isinstance(expected, (list, dict)):
            if got != expected:
                diffs[key] = {"expected": expected, "actual": got}
            continue
        if expected is True:
            if not got:
                diffs[key] = {"expected": True, "actual": got}
            continue
        if got != expected:
            diffs[key] = {"expected": expected, "actual": got}
    return ("match" if not diffs else "mismatch"), diffs


# ── golden 语料 ──────────────────────────────────────────────────────────────

VARIANTS = [0, 1, 2, 3, 4, 5, 6, 7]
SEEDS = [1, 7, 42, 1234]
NUMERIC = [
    (30, 6, 12, 5),
    (30, 9, 20, 5),
    (50, 6, 40, 12),
    (20, 3, 8, 2),
]


def build_corpus(lib):
    """golden_v1：一条都不能变（rd_oracle_run 没动过）。"""
    os.makedirs(CORPUS_DIR, exist_ok=True)
    out = os.path.join(CORPUS_DIR, "golden_v1.jsonl")
    cases = []
    failures = []
    for variant in VARIANTS:
        for seed in SEEDS:
            for (hero_hp, card_dmg, enemy_hp, enemy_dmg) in NUMERIC:
                case_id = f"v{variant}_s{seed}_h{hero_hp}_c{card_dmg}_e{enemy_hp}_d{enemy_dmg}"
                expect, err = run_case(lib, variant, seed, hero_hp, card_dmg, enemy_hp, enemy_dmg)
                if expect is None:
                    failures.append({"case": case_id, "error": err})
                    continue
                cases.append({
                    "case": case_id,
                    "inputs": {
                        "variant": variant, "seed": seed,
                        "hero_hp": hero_hp, "card_damage": card_dmg,
                        "enemy_hp": enemy_hp, "enemy_damage": enemy_dmg,
                    },
                    "expect": expect,
                })

    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({
            "schema": "roguedeck-golden-v1",
            "source": "RogueDeck-Core via NativeAOT oracle (native/RogueDeck.Oracle)",
            "note": "hash 来自 CombatStateHasher；random_step/steps/log_count 覆盖哈希盲区",
        }, ensure_ascii=False) + "\n")
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    return cases, failures, out


# ── golden_v2：机制语料 ──────────────────────────────────────────────────────

def v2_case(case, mechanisms, note, **kw):
    return dict(case=case, mechanisms=mechanisms, note=note, inputs=defaults(**kw))


def build_v2_matrix():
    M = []
    A = M.append

    # 卡牌 / 能量 / 伤害 / 死亡
    A(v2_case("ex_dmg_plain", ["card_play", "energy_cost", "damage"],
              "最朴素的一张牌：1 费、6 伤、敌方 12 血",
              card_damage=6, card_cost=1, enemy_hp=12, variant=V_PLAY))
    A(v2_case("ex_dmg_free_card", ["card_play", "damage"],
              "0 费卡 = 不花能量的出牌路径",
              card_damage=5, card_cost=0, enemy_hp=12, variant=V_PLAY))
    A(v2_case("ex_dmg_kill", ["damage", "death"],
              "20 伤打死 12 血敌人：结算掉血、倒地、战斗结果",
              card_damage=20, enemy_hp=12, variant=V_PLAY))
    A(v2_case("ex_dmg_overkill_early_stop", ["death", "control_flow"],
              "敌人被中途打死触发 ScenarioRunner 的早停分支（problems=1）",
              card_damage=20, enemy_hp=12, variant=V_PLAY_ENEMY))
    A(v2_case("ex_energy_drain_twice", ["card_play", "energy_cost"],
              "同一回合连出两张 1 费牌：能量 3→2→1",
              card_damage=4, card_cost=1, enemy_hp=40, variant=V_TWICE))
    A(v2_case("ex_deck_cycle", ["card_play", "energy_cost", "control_flow"],
              "出牌→走完一轮→再出牌：牌堆循环 + 回合开始的能量补充",
              card_damage=4, card_cost=1, enemy_hp=40, deck_size=3, variant=V_CYCLE))
    A(v2_case("ex_control_noop", ["control_flow"],
              "对照：什么都不做，只走回合与轮次",
              card_hits=0, card_damage=0, enemy_hp=40, variant=V_CONTROL))
    A(v2_case("ex_bookkeeping", ["control_flow"],
              "只做回合/轮次记账（结束→下一轮→结束）",
              card_hits=0, card_damage=0, enemy_hp=40, variant=V_BOOKKEEP))

    # 修饰器
    A(v2_case("ex_mod_strength", ["modifier_strength", "damage"],
              "英雄 Strength 2 → 每段 +2", card_damage=6, hero_strength=2, enemy_hp=40, variant=V_PLAY))
    A(v2_case("ex_mod_weak", ["modifier_weak", "damage"],
              "英雄 Weak 1 → 造成伤害 ×75/100", card_damage=9, hero_weak=1, enemy_hp=40, variant=V_PLAY))
    A(v2_case("ex_mod_vulnerable", ["modifier_vulnerable", "damage"],
              "敌人 Vulnerable 1 → 承受伤害 ×150/100", card_damage=7, enemy_vulnerable=1,
              enemy_hp=40, variant=V_PLAY))
    A(v2_case("ex_mod_all_three", ["modifier_strength", "modifier_weak", "modifier_vulnerable"],
              "Source 阶段(+2, ×75) 先于 Target 阶段(×150)：三个阶段同场",
              card_damage=8, hero_strength=2, hero_weak=1, enemy_vulnerable=1,
              enemy_hp=40, variant=V_PLAY))
    A(v2_case("ex_mod_dexterity_frail", ["modifier_strength", "block"],
              "Dexterity 2 与 Frail 1 同时作用在 GainBlock 上（BlockGain 管线）",
              card_hits=0, card_damage=0, card_block=5, card_block_target=0, card_cost=0,
              hero_dexterity=2, hero_frail=1, enemy_hp=40, variant=V_PLAY))

    # 多段伤害 / 多敌人
    A(v2_case("ex_multihit_4", ["multi_hit", "damage"],
              "一张 4 段、每段 3 伤的牌：每段独立走修饰管线",
              card_damage=3, card_hits=4, enemy_hp=40, variant=V_PLAY))
    A(v2_case("ex_multihit_strength", ["multi_hit", "modifier_strength", "damage"],
              "4 段 × (3+2)：修饰器对每一段都生效",
              card_damage=3, card_hits=4, hero_strength=2, enemy_hp=40, variant=V_PLAY))
    A(v2_case("ex_multi_enemy_3", ["multi_enemy", "damage"],
              "3 个敌人；这一张牌只打 foe0（多敌人的状态/快照覆盖）",
              card_damage=5, enemy_hp=20, enemy_count=3, variant=V_PLAY))
    A(v2_case("ex_multi_enemy_status", ["multi_enemy", "modifier_vulnerable", "status_apply"],
              "3 个敌人**每个**都带 Vulnerable（起始状态走真实 ApplyStatus 管线）",
              card_damage=5, enemy_vulnerable=1, enemy_hp=20, enemy_count=3, variant=V_PLAY))
    A(v2_case("ex_multi_enemy_enemy_acts", ["multi_enemy", "damage"],
              "3 个敌人 + 敌人回合：轮到 foe0 出手打英雄",
              card_damage=5, enemy_hp=20, enemy_count=3, enemy_damage=4, variant=V_PLAY_ENEMY))

    # 格挡 / 防御池
    A(v2_case("ex_block_gain", ["block"],
              "一张 0 费牌给英雄 6 点格挡",
              card_hits=0, card_damage=0, card_block=6, card_block_target=0, card_cost=0,
              enemy_hp=40, variant=V_PLAY))
    A(v2_case("ex_block_absorbs", ["block", "damage"],
              "先铺 5 点格挡再吃 6 点伤害：格挡吃掉 5、掉 1 血",
              card_damage=6, card_damage_target=0, card_block=5, card_block_target=0,
              card_cost=0, enemy_hp=40, variant=V_PLAY))
    A(v2_case("ex_defensive_pool_ward", ["defensive_pool", "block", "damage"],
              "自定义池 oracle.ward（AbsorbPriority=10）排在 Block 之后吸收剩余伤害",
              card_damage=6, card_damage_target=0, card_block=5, card_block_target=0,
              card_ward=3, card_cost=0, enemy_hp=40, variant=V_PLAY))
    A(v2_case("ex_true_damage", ["defensive_pool", "block", "damage"],
              "IgnoresBlock 真伤：两个池一个都不动",
              card_damage=6, card_damage_target=0, card_kind=2, card_block=5,
              card_block_target=0, card_ward=3, card_cost=0, enemy_hp=40, variant=V_PLAY))

    # 状态的施加与递减
    A(v2_case("ex_status_apply_many", ["status_apply", "damage"],
              "双方各带多层起始状态（真实 ApplyStatus 管线，不是直接塞字段）",
              card_damage=5, hero_strength=3, hero_dexterity=2, hero_frail=1,
              enemy_vulnerable=2, enemy_weak=1, enemy_hp=40, variant=V_PLAY))
    A(v2_case("ex_status_decay", ["status_decay", "control_flow"],
              "限时状态跨越回合结束 ⇒ 持续时间递减（DecreaseTimedStatusDurationsOnTurnEnded）",
              card_damage=5, enemy_vulnerable=1, enemy_hp=40, variant=V_ROUND))
    A(v2_case("ex_status_decay_hero", ["status_decay", "control_flow"],
              "英雄自己的限时状态（Weak/Frail）随自己的回合结束递减",
              card_damage=5, hero_weak=1, hero_frail=1, enemy_hp=40, variant=V_CYCLE))

    # 队列卡
    A(v2_case("ex_queue_deferred", ["card_play", "energy_cost", "control_flow"],
              "QueueOnPlay：付费即时、效果等到解析窗口",
              card_damage=13, card_cost=1, queue_on_play=1, enemy_hp=200, variant=V_PLAY))
    A(v2_case("ex_queue_resolved", ["card_play", "energy_cost", "control_flow"],
              "结束回合后队列排空，13 点伤害落地",
              card_damage=13, card_cost=1, queue_on_play=1, enemy_hp=200, enemy_damage=1,
              variant=V_ENDTURN))

    # 伤害类型
    A(v2_case("ex_dot_kind", ["damage", "modifier_strength"],
              "DamageKind.DamageOverTime：Strength 这种 RestrictDamageKind=Direct 的修饰器看都不看它",
              card_damage=5, card_kind=1, hero_strength=5, enemy_hp=40, variant=V_PLAY))

    return M


def build_corpus_v2(lib):
    os.makedirs(CORPUS_DIR, exist_ok=True)
    out = os.path.join(CORPUS_DIR, "golden_v2.jsonl")
    matrix = build_v2_matrix()
    cases, failures = [], []
    for entry in matrix:
        inputs = entry["inputs"]
        meas, err = call_run_ex(lib, inputs)
        if meas is None:
            failures.append({"case": entry["case"], "error": err})
            continue
        s = summarize(meas)
        cases.append({
            "case": entry["case"],
            "mechanisms": entry["mechanisms"],
            "note": entry["note"],
            "inputs": inputs,
            "expect": {
                "hash": s["hash"],
                "steps": s["steps"], "problems": s["problems"],
                "hero_hp": s["hero_hp"], "enemy_hp": s["enemy_hp"],
                "hero_block": s["hero_block"], "enemy_block": s["enemy_block"],
                "hero_ward": s["hero_ward"], "enemy_ward": s["enemy_ward"],
                "energy": s["energy"],
                "hand_count": s["hand_count"], "draw_count": s["draw_count"],
                "discard_count": s["discard_count"], "queue_count": s["queue_count"],
                "enemy_count": s["enemy_count"], "enemy_hp_all": s["enemy_hp_all"],
                "round": s["round"], "turn": s["turn"], "phase": s["phase"],
                "result": s["result"], "played": s["played"],
                "random_step": s["random_step"], "pending": s["pending"],
                "log_count": s["log_count"],
                "log_types": s["log_types"],
                "hero_statuses": s["hero_statuses"],
                "enemy_statuses": s["enemy_statuses"],
            },
        })

    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({
            "schema": "roguedeck-golden-v2",
            "source": "RogueDeck-Core via NativeAOT oracle (native/RogueDeck.Oracle), rd_oracle_run_ex",
            "note": "机制语料：每条都真的把某个机制跑起来（见 mechanisms）；对比 golden_v1 的"
                    "「一张 strike + 一只 ogre」缺口。vector 类向量见 spec_vectors_v1.jsonl。",
        }, ensure_ascii=False) + "\n")
        for c in cases:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    return cases, failures, out


# ── 覆盖清单 ────────────────────────────────────────────────────────────────

COVERAGE_MECHANISMS = [
    "card_play", "energy_cost", "damage", "block", "status_apply", "status_decay",
    "modifier_strength", "modifier_weak", "modifier_vulnerable", "multi_hit", "multi_enemy",
    "defensive_pool", "pre_down_intercept", "triggered_effect", "decree_turn", "decree_round",
    "rng_shuffle", "control_flow", "death",
]


def build_coverage(lib, v1_cases, v2_cases, vectors):
    mech = {name: [] for name in COVERAGE_MECHANISMS}

    for c in v2_cases:
        for name in c["mechanisms"]:
            mech.setdefault(name, []).append(c["case"])

    # 探针类用例：它们的 case id 就在 spec_vectors_v1.jsonl 里（同一个 id，**不加前缀**）。
    def add(name, *case_ids):
        for cid in case_ids:
            mech.setdefault(name, []).append(cid)

    add("rng_shuffle", "cst-V9a", "cst-V9b")
    add("triggered_effect", "modp-16a", "modp-16b", "eir-V10a", "eir-V10b")
    add("decree_turn", "cst-V13a", "cst-V13b", "cst-V13c", "cst-V14")
    # 引擎的 CombatRule 枚举里没有"按轮次"的法令（只有回合级的），所以这一格覆盖的是**轮次边界本身**：
    # 回绕时 Round 1→2、Turn 回到 1，以及带着法令走完一整轮。见 coverage.json 的 decree_round_note。
    add("decree_round", "cst-V2", "ex_deck_cycle", "cst-V13c")
    add("control_flow", "eir-V3a", "eir-V3b", "eir-V3c", "eir-V5",
        "eir-V6a", "eir-V6b", "eir-V6c", "eir-V9a", "eir-V9b",
        "eir-V7", "eir-V8a", "eir-V8b", "modp-17", "cst-V1",
        "cst-V2", "cst-V3", "cst-V12a", "cst-V12b", "cst-V12c")
    add("defensive_pool", "modp-07a", "modp-07b")
    add("block", "modp-05", "modp-15a", "modp-15b", "modp-15c")
    add("multi_hit", "modp-14")
    add("multi_enemy", "eir-V7", "eir-V8a", "eir-V8b")
    add("status_apply", "modp-10", "modp-10b", "modp-11", "modp-11b")
    add("damage", "modp-01", "modp-02", "modp-03a", "modp-03b",
        "modp-04", "modp-05", "modp-06", "modp-14")
    add("modifier_strength", "modp-01", "modp-03a", "modp-03b",
        "modp-04", "modp-06")
    add("modifier_weak", "modp-02", "modp-03b", "modp-06")
    add("modifier_vulnerable", "modp-02", "modp-05", "modp-06", "modp-07a")
    add("card_play", "cst-V11a", "cst-V11b")
    add("energy_cost", "cst-V11a", "cst-V11b", "cst-V13c")
    add("death", "modp-14", "modp-08b")
    add("pre_down_intercept", "modp-08a", "modp-08b", "modp-09")

    # golden_v1 的对应关系（golden_v1 只覆盖了很窄的一层）
    v1_overlap = {
        "card_play": [c["case"] for c in v1_cases][:4],
        "energy_cost": [c["case"] for c in v1_cases if c["inputs"]["variant"] == 2][:4],
        "damage": [c["case"] for c in v1_cases][:4],
        "rng_shuffle": [c["case"] for c in v1_cases if c["inputs"]["variant"] >= 4][:4],
        "control_flow": [c["case"] for c in v1_cases if c["inputs"]["variant"] == 3][:4],
        "death": [c["case"] for c in v1_cases if c["expect"]["problems"] == 1][:4],
    }

    # 自检：清单里的每个 id 都必须真的在某个语料文件里存在（门禁就是这么判的）。
    known = {c["case"] for c in v1_cases} | {c["case"] for c in v2_cases}
    known |= {v["case"] for v in vectors}
    dangling = {m: [i for i in ids if i not in known] for m, ids in mech.items() if ids}
    dangling = {m: bad for m, bad in dangling.items() if bad}
    if dangling:
        raise AssertionError(f"coverage 清单里有不存在的 case id（门禁会判 dangling）: {dangling}")

    doc = {
        "schema": "roguedeck-coverage-v1",
        "corpora": ["golden_v1.jsonl", "golden_v2.jsonl", "spec_vectors_v1.jsonl"],
        "corpus": "golden_v1.jsonl + golden_v2.jsonl + spec_vectors_v1.jsonl"
                  "（id 跨三个文件；ex_* 在 v2，v*_* 在 v1，modp-/cst-/eir- 在 spec_vectors_v1）",
        "generated_by": "native/make_corpus.py",
        "note": "机制 -> 真的把它跑起来的用例 id（id 原样取自各 jsonl 的 case 字段，无前缀）。"
                "ex_* 在 golden_v2.jsonl，v*_* 在 golden_v1.jsonl，其余（modp-/cst-/eir-）在 "
                "spec_vectors_v1.jsonl。",
        "mechanisms": {k: v for k, v in mech.items() if v},
        "not_supported": [
            "decree_round: engine has no round-level decree — CombatRule has only turn-level rules "
            "(MaxCardsPerTurn / MaxHandSize / UnspentResourceCarries / ...). 这一格里列的用例覆盖的是"
            "“一轮的定义”本身（回绕计数），不是轮次级法令；W1 的 SEMANTICS 应记为本版本不支持轮次级法令。",
        ],
        "uncovered": [k for k in COVERAGE_MECHANISMS if not mech.get(k)],
        "decree_round_note": "引擎的 CombatRule 枚举里**没有**轮次级法令（只有回合级的 MaxCardsPerTurn / "
                             "MaxHandSize / UnspentResourceCarries / …）。这一格覆盖的是「一轮的定义」本身："
                             "回绕时 Round 1→2 且 Turn 回到 1（cst-V2），以及带法令走完整轮（cst-V13c / "
                             "ex_deck_cycle）。",
        "golden_v1_overlap": v1_overlap,
    }
    out = os.path.join(CORPUS_DIR, "coverage.json")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return doc, out


def write_vectors(results):
    os.makedirs(CORPUS_DIR, exist_ok=True)
    out = os.path.join(CORPUS_DIR, "spec_vectors_v1.jsonl")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({
            "schema": "roguedeck-spec-vectors-v1",
            "source": "docs/spec/{modifier-pipeline,combat-state-and-turn,effect-program-ir}.md §7",
            "method": "每条向量都用真实引擎（NativeAOT oracle）跑一遍，记录规格书声称值 vs 实测值。"
                      "实测与声称不一致时**不修改代码迁就**，如实记录差异。",
        }, ensure_ascii=False) + "\n")
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


def print_vector_table(results):
    W = 11
    print(f"\n  {'case':<{W}}{'来源':<22}{'声称':<34}{'实测':<34}结论")
    print("  " + "-" * 128)
    for r in results:
        claim = r["claim"] or {}
        claim_txt = ", ".join(f"{k}={v}" for k, v in claim.items()) or "—(无数值)"
        if r["verdict"] == "not_expressible":
            meas_txt = "（未执行）"
        else:
            m = r["measured"] or {}
            if "harness_error" in m:
                meas_txt = "HARNESS " + str(m["harness_error"])[:26]
            elif "error" in m:
                meas_txt = "ERROR " + str(m["error"])[:28]
            else:
                keys = list(claim.keys()) or ["hash"]
                parts = []
                for k in keys:
                    if k == "log_contains":
                        parts.append("log_ok=" + str("log_contains" not in (r.get("diffs") or {})))
                    elif k == "log_types_head":
                        parts.append("log=" + ",".join(m.get("log_types", [])[:4]))
                    else:
                        parts.append(f"{k}={m.get(k)}")
                meas_txt = ", ".join(parts)
        print(f"  {r['case']:<{W}}{r['item']:<22}{claim_txt[:33]:<34}{meas_txt[:33]:<34}{r['verdict']}")
    print()


# ── 富状态语料：把「规范文本里从来没出现过的键」真的塞进去 ────────────────────────────
#
# 为什么需要这一节
# ----------------
# corpus/hash_cases/*.txt 是 hash_diff.py 从 **rd_oracle_run** 生成的，而那个入口只造
# 「一张 strike + 一只 ogre」。实测那 48 份语料的规范文本里一共只出现过 20 个键：
#   id seed step result round turn phase active res tags cz draw hand disc
#   turn_order card_num chain_num exec_num status_num
# 而 CombatStateHasher.AppendSnapshot 还会写 dp=（防御池）、s=（单位状态）、gs=（全局状态）、
# cnt=（计数器）、tr=（临时规则）、queue=/aside= 两个卡区，以及卡行的 m:/mc:/msrc:/qat: 后缀和
# 状态行的 pend= 后缀 —— 这些**一次都没出现过**。于是那些行在移植侧只是「照着 CombatStateHasher.cs
# 逐行钉」的**规格级**验证：没有任何一份语料来自引擎真实产出的、含这些字段的状态。
# 这一节补的就是那段缺口，而且补得能被 rd-core 的 every_corpus_hash_case_round_trips 直接吃掉
# （那个测试 glob 的就是 corpus/hash_cases/case_*.txt）。
#
# 每条用例的来源逐条写在 note 里：
#   ex    = rd_oracle_run_ex（ABI 本来就有，只是旧语料没这么用）→ 覆盖 dp= / s= / queue= / qat=
#   probe = 本工程新加的 rd_oracle_probe_*（native/RogueDeck.Oracle/OracleExports.RichStates.cs）
#           → 覆盖 m:/mc:/msrc: / cnt= / tr= / aside=/exh=/ban= / pend= / gs=
#
# 唯一一条状态不是「战斗跑出来」的是 gs=：引擎里 CombatState._globalStatuses 只有一个写者
# （CombatState.Restore），没有任何运行时路径会添加全局状态。那条用例是一次真实战斗的
# CreateSnapshot() 经 CombatState.Restore 走回来的，理由逐字记在 OracleExports.RichStates.cs 里。
#
# ⚠ 与 hash_diff.py 的边界：hash_diff.py 每次运行都会 **删掉 corpus/hash_cases/*.txt**，再重新生成
#   它自己那 48 份（那个目录是它的生成物）。所以这一节写下的用例必须可重放：
#       python native/make_corpus.py --rich-cases
#   会按下面同一张 RICH_CASES 表逐字节重建它们，并在 corpus/hash_cases/rich/ 留一份主拷贝
#   （glob('*.txt') 不递归，hash_diff.py 动不到它）。跑完 hash_diff.py 之后重跑上面那条命令即可。

RICH_CASE_START = 100      # 旧语料是 hash_diff.py 的 0000..0047，从 0100 起，留出余量
RICH_STASH_NAME = "rich"   # corpus/hash_cases/rich/ —— 主拷贝，hash_diff.py 不会删

# 每一类至少两条、且两条的哈希必须不同：一份「和别的都一样」的语料对差分测试毫无价值。
RICH_CASES = [
    # ── dp= 防御池（rd_oracle_run_ex 早就够得着，旧语料只是没用）────────────────────────
    dict(name="dp_block", group="dp", kind="ex", seed=12345,
         args=dict(card_hits=0, card_damage=0, card_block=6, card_block_target=0, card_cost=0,
                   enemy_hp=200),
         note="0 费牌给英雄 6 格挡 ⇒ dp=standard.block 6/null。标准格挡池就是一个防御池"),
    dict(name="dp_two_pools", group="dp", kind="ex", seed=12345,
         args=dict(card_block=5, card_block_target=0, card_ward=3, card_cost=0, enemy_hp=200),
         note="两个池同时存在：dp=oracle.ward（AbsorbPriority=10）与 dp=standard.block（0），"
              "按 key 排序写出"),
    dict(name="dp_ward_only", group="dp", kind="ex", seed=12345,
         args=dict(card_damage=1, card_ward=2, card_cost=0, enemy_hp=200),
         note="只有自定义池：dp=oracle.ward 2/null，没有 standard.block 那一行"),

    # ── s= 单位状态（同样早就够得着）────────────────────────────────────────────────────
    dict(name="s_hero_axis", group="s", kind="ex", seed=12345,
         args=dict(card_damage=5, hero_strength=2, hero_dexterity=1, hero_frail=1, enemy_hp=200),
         note="英雄身上三个状态 ⇒ 三行 s=，各自 stk/dur/chg/pol 不同"),
    dict(name="s_enemy_axis", group="s", kind="ex", seed=12345,
         args=dict(card_damage=5, enemy_hp=200, enemy_count=2, enemy_vulnerable=2, enemy_weak=1,
                   enemy_strength=3),
         note="两只敌人各带自己的状态 ⇒ s= 出现在两个 c= 块里（快照按 TurnOrder 逐单位写）"),

    # ── queue= / qat: 排队卡与锁定目标 ────────────────────────────────────────────────
    dict(name="queue_one", group="queue", kind="ex", seed=12345,
         args=dict(card_damage=13, queue_on_play=1, enemy_hp=200, variant=V_PLAY),
         note="打出即排队、效果还没结算 ⇒ queue= 区有卡，卡行带 qat:foe0（排队时锁定的目标）"),
    dict(name="queue_two_fifo", group="queue", kind="ex", seed=12345,
         args=dict(card_damage=13, queue_on_play=1, enemy_hp=200, enemy_damage=1, variant=V_TWICE),
         note="连打两张排队卡 ⇒ queue= 两行，顺序 = 入队顺序（队列 FIFO 结算，先等的最先写）"),
    dict(name="queue_survives_turn_end", group="queue", kind="ex", seed=12345,
         args=dict(card_damage=13, queue_on_play=1, enemy_hp=200, enemy_damage=1, variant=V_ENDTURN),
         note="结束回合后队列里的卡**还在**：排队卡的结算窗口是**自己**的下一个回合开始（回合开始→"
              "触发→**结算队列**→摸牌），所以跨过一个回合边界 queue= 与 qat: 都得原样保留"),
    dict(name="queue_emptied", group="queue", kind="ex", seed=12345,
         args=dict(card_damage=13, queue_on_play=1, enemy_hp=200, enemy_damage=1, variant=V_ROUND),
         note="结束回合 + 走完整轮回到英雄 ⇒ 队列在下个回合开始被排空，卡落到弃牌堆 ⇒ "
              "**queue= 一行都不写**（空队列不落文本，这是格式的一部分：缺席 != 空）"),

    # ── m:/mc:/msrc: 卡牌实例标记 ─────────────────────────────────────────────────────
    dict(name="marks_one", group="marks", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_marks", (1, 0, 0, 0, 0, 12345)),
         note="一张卡一个标记 ⇒ 卡行尾部 m:oracle.mark.a"),
    dict(name="marks_three_tags", group="marks", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_marks", (3, 0, 0, 0, 0, 12345)),
         note="同一张卡三个标记 ⇒ 一行里三个 m:，按 tag 值排序"),
    dict(name="marks_spread", group="marks", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_marks", (1, 3, 0, 0, 0, 12345)),
         note="四张卡各带一个标记 —— 其中一张正是被打出的那张：标记落在实例上，跟着它从手牌走到弃牌堆"),
    dict(name="marks_count_abs", group="marks", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_marks", (1, 0, 7, 0, 0, 12345)),
         note="标记计数器绝对写两次 7 ⇒ mc:oracle.charge=7"),
    dict(name="marks_count_rel", group="marks", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_marks", (1, 0, 7, 1, 0, 12345)),
         note="标记计数器相对写两次 7 ⇒ mc:oracle.charge=14（和绝对写只差 relative 一位）"),
    dict(name="marks_source", group="marks", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_marks", (2, 1, 5, 0, 1, 12345)),
         note="带来源的标记 ⇒ m: + mc: + msrc:knight 三种后缀同场"),

    # ── cnt= 单位计数器 ──────────────────────────────────────────────────────────────
    dict(name="cnt_hero", group="cnt", kind="probe", seed=12345,
         args=("rd_oracle_probe_combatant_counter", (3, 0, 0, 0, 12345)),
         note="英雄 counter oracle.heat=3 ⇒ c= 块末尾一行 cnt="),
    dict(name="cnt_both_rel", group="cnt", kind="probe", seed=12345,
         args=("rd_oracle_probe_combatant_counter", (3, 4, 1, 1, 12345)),
         note="双方各相对写两次 ⇒ 英雄 6 / 敌人 8，两个 c= 块各带自己的 cnt="),
    dict(name="cnt_foe_abs", group="cnt", kind="probe", seed=12345,
         args=("rd_oracle_probe_combatant_counter", (0, 5, 0, 0, 12345)),
         note="只有敌人有计数器，且是绝对写 ⇒ cnt= 只出现在敌人块里"),

    # ── tr= 临时规则 ────────────────────────────────────────────────────────────────
    dict(name="tr_unlimited", group="tr", kind="probe", seed=12345,
         args=("rd_oracle_probe_temporary_rule", (0, 0, 0, 0, 0, 12345)),
         note="无限期临时规则 ⇒ tr= … act=inf expR=none expT=none owner=none inst=1.1"),
    dict(name="tr_activations", group="tr", kind="probe", seed=12345,
         args=("rd_oracle_probe_temporary_rule", (2, 3, 0, 1, 0, 12345)),
         note="3 次激活预算、触发一次 ⇒ act=2（激活计数真的会走）"),
    dict(name="tr_end_of_round", group="tr", kind="probe", seed=12345,
         args=("rd_oracle_probe_temporary_rule", (3, 1, 0, 0, 0, 12345)),
         note="第 1 轮末过期 ⇒ expR=1 expT=none"),
    dict(name="tr_end_of_turn", group="tr", kind="probe", seed=12345,
         args=("rd_oracle_probe_temporary_rule", (4, 2, 0, 0, 1, 12345)),
         note="第 2 轮第 2 回合末过期 + 结束过回合 ⇒ expR=2 expT=2，而观察点是 turn=2"),
    dict(name="tr_owner_bound", group="tr", kind="probe", seed=12345,
         args=("rd_oracle_probe_temporary_rule", (5, 0, 1, 0, 0, 12345)),
         note="带 owner 且 owner 倒下即过期 ⇒ owner=knight ownerbound（ownerbound 只有这一条路径）"),
    dict(name="tr_owner_plain", group="tr", kind="probe", seed=12345,
         args=("rd_oracle_probe_temporary_rule", (0, 0, 1, 0, 0, 12345)),
         note="带 owner 但不绑定生命 ⇒ owner=knight（无 ownerbound 后缀）"),
    dict(name="tr_oneshot_gone", group="tr", kind="probe", seed=12345,
         args=("rd_oracle_probe_temporary_rule", (1, 1, 0, 1, 0, 12345)),
         note="一次性规则触发掉唯一一次激活 ⇒ **tr= 一行都不写**：过期与剪除发生在同一次调用里，"
              "所以 AppendSnapshot 的 ' dead' 后缀在运行时状态里根本到不了"),

    # ── aside= / exh= / ban= 三个只有卡牌操作能进的区 ──────────────────────────────────
    dict(name="aside_one", group="aside", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_zone_move", (0, 1, 12345)),
         note="搁置 1 张手牌 ⇒ aside= 区出现一行"),
    dict(name="aside_two", group="aside", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_zone_move", (0, 2, 12345)),
         note="搁置 2 张 ⇒ aside= 两行，顺序 = 放下的顺序"),
    dict(name="aside_four", group="aside", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_zone_move", (0, 4, 12345)),
         note="搁置 4 张 ⇒ 手牌只剩被打出的那张（手牌与 aside 此消彼长）"),
    dict(name="exh_one", group="exh", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_zone_move", (1, 1, 12345)),
         note="消耗掉 1 张手牌 ⇒ exh= 区一行（旧语料里 exh= 也一次都没出现过）"),
    dict(name="exh_two", group="exh", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_zone_move", (1, 2, 12345)),
         note="消耗掉 2 张 ⇒ exh= 两行"),
    dict(name="ban_one", group="ban", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_zone_move", (2, 1, 12345)),
         note="放逐 1 张手牌 ⇒ ban= 区一行（第三个只有卡牌操作才能进的区）"),
    dict(name="ban_two", group="ban", kind="probe", seed=12345,
         args=("rd_oracle_probe_card_zone_move", (2, 3, 12345)),
         note="放逐 3 张 ⇒ ban= 三行"),

    # ── pend= 延迟生效的状态 + dur/chg 非零 ───────────────────────────────────────────
    dict(name="pend_two", group="pend", kind="probe", seed=12345,
         args=("rd_oracle_probe_pending_status", (3, 2, 0, 0, 12345)),
         note="戴「迟延」状态时被施加 3 层恐惧 ⇒ s= 行里出现 pend=2（纯蓝图可表达的运行时路径）"),
    dict(name="pend_dur_chg", group="pend", kind="probe", seed=12345,
         args=("rd_oracle_probe_pending_status", (2, 1, 3, 4, 12345)),
         note="延迟 1 回合、2 层、**持续 3 回合、4 次充能** ⇒ s= 行里 dur= 与 chg= 同时非零。"
              "旧语料里这两个字段恒为 0（run_ex 只能给 stacks），所以「非零怎么拼」从来没有被验过"),
    dict(name="pend_one", group="pend", kind="probe", seed=12345,
         args=("rd_oracle_probe_pending_status", (1, 4, 0, 0, 12345)),
         note="延迟 4 回合、1 层 ⇒ pend=4"),

    # ── gs= 全局状态（⚠ 唯一一条不是战斗跑出来的状态）──────────────────────────────────
    dict(name="gs_full", group="gs", kind="probe", seed=12345,
         args=("rd_oracle_probe_global_status", (2, 3, 1, 12345)),
         note="全局状态 stk=2 dur=3 chg=1 ⇒ gs= 一行出现在 turn_order 之后、所有 c= 之前。"
              "**引擎当前没有任何运行时路径会添加全局状态**（_globalStatuses 只有 Restore 一个写者），"
              "所以这条状态是一次真实战斗的快照经 CombatState.Restore 走回来的（见 RichStates.cs）"),
    dict(name="gs_zero", group="gs", kind="probe", seed=12345,
         args=("rd_oracle_probe_global_status", (1, 0, 0, 12345)),
         note="全局状态 stk=1 dur=0 chg=0 ⇒ 同一行的另一个取值（dur/chg 为 0 时照样写出来）"),
]

RICH_KEY_HEAD_RE = re.compile(r"^\s*([a-z_]+)=", re.M)
RICH_KEY_SUFFIX_RE = re.compile(r" (m:|mc:|msrc:|qat:|pend=)")


def rich_keys(text):
    """规范文本里的键：行首 `key=` 的头，外加卡行/状态行内部的 `m:` / `mc:` / `msrc:` / `qat:` / `pend=`。"""
    keys = set(RICH_KEY_HEAD_RE.findall(text))
    for m in RICH_KEY_SUFFIX_RE.finditer(text):
        keys.add(m.group(1))
    return keys


def rich_manifest_path():
    return os.path.join(CORPUS_DIR, "hash_cases", RICH_STASH_NAME, "_manifest.json")


def rich_previous_files():
    """上一轮写下的富状态语料清单（用来清掉改名/改编号后的残留）。"""
    p = rich_manifest_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as fh:
            return [c["file"] for c in json.load(fh).get("cases", [])]
    except (OSError, ValueError):
        return []


def build_rich_cases(lib):
    """生成富状态语料：写 corpus/hash_cases/case_01xx_*.txt + 一份主拷贝，并做全部自检。

    返回 (rows, failures)。rows 里每条都带 keys / new_keys / hash，供报告与断言使用。
    """
    case_dir = os.path.join(CORPUS_DIR, "hash_cases")
    stash_dir = os.path.join(case_dir, RICH_STASH_NAME)
    os.makedirs(stash_dir, exist_ok=True)
    previous = set(rich_previous_files())

    # 旧语料的键集合 = 目录里所有 case_*.txt 减去上一轮富状态语料。
    legacy_files = [p for p in sorted(glob.glob(os.path.join(case_dir, "case_*.txt")))
                    if os.path.basename(p) not in previous]
    legacy_keys, legacy_hashes = set(), {}
    for p in legacy_files:
        with open(p, "rb") as fh:
            raw = fh.read()
        legacy_keys |= rich_keys(raw.decode("utf-8"))
        legacy_hashes[hashlib.sha256(raw).hexdigest()] = os.path.basename(p)

    rows, failures = [], []
    for i, spec in enumerate(RICH_CASES):
        index = RICH_CASE_START + i
        if spec["kind"] == "ex":
            inputs = defaults(**spec["args"])
            rc = lib.rd_oracle_run_ex(*[inputs[name] for name in RUN_EX_ARGS])
            source, call = "run_ex", "run_ex " + json.dumps(spec["args"], sort_keys=True)
        else:
            fn, params = spec["args"]
            rc = getattr(lib, fn)(*params)
            source, call = fn.replace("rd_oracle_probe_", "probe:"), f"{fn}{params}"
        if rc < 0:
            failures.append({"case": spec["name"], "error": error_of(lib)})
            continue
        if lib.rd_oracle_hash_input_ok() != 1:
            failures.append({"case": spec["name"],
                             "error": "rd_oracle_hash_input_ok != 1（导出的规范文本与引擎自己的哈希不符）"})
            continue

        text = hash_input_of(lib)
        raw = text.encode("utf-8")
        engine = hash_of(lib)
        # 与 hash_diff.py 完全同一条闭环：**引擎给的哈希 == 这段文本的 SHA-256**。自抄的
        # AppendSnapshot 一旦漂移，这里立刻炸，而不是安静地写出一份看着很像的语料。
        digest = hashlib.sha256(raw).hexdigest()
        if digest != engine:
            failures.append({"case": spec["name"],
                             "error": f"sha256(text) != 引擎哈希（{digest} vs {engine}）"})
            continue

        fname = f"case_{index:04d}_{spec['name']}_s{spec['seed']}.txt"
        path = os.path.join(case_dir, fname)
        # BINARY 写：字节完全相同才是重点，不能有换行转换（和 hash_diff.py 同一约定）。
        for target in (path, os.path.join(stash_dir, fname)):
            with open(target, "wb") as fh:
                fh.write(raw)

        keys = rich_keys(text)
        rows.append({"index": index, "case": spec["name"], "group": spec["group"],
                     "source": source, "call": call, "file": fname, "path": path,
                     "seed": spec["seed"], "hash": engine, "bytes": len(raw),
                     "lines": raw.count(b"\n"),
                     "keys": sorted(keys), "new_keys": sorted(keys - legacy_keys),
                     "note": spec["note"]})

    # 清掉上一轮留下、这一轮不再生成的富状态语料。
    keep = {r["file"] for r in rows}
    for stale in sorted(previous - keep):
        for d in (case_dir, stash_dir):
            p = os.path.join(d, stale)
            if os.path.exists(p):
                os.remove(p)

    return rows, failures, legacy_keys, legacy_hashes, legacy_files


def report_rich_cases(rows, failures, legacy_keys, legacy_hashes, legacy_files):
    """报告 + 断言。断言有任何一条不成立就抛 AssertionError（宁可不写语料，也不写假语料）。"""
    print("\n--- 富状态语料（引擎级覆盖：把缺失的键真的塞进规范文本）---")

    if failures:
        print(f"  !! 有 {len(failures)} 条没跑起来（**没有写入**）：")
        for f in failures[:10]:
            print(f"     {f['case']}: {f['error']}")
        raise AssertionError("富状态语料有用例执行失败，不写入")

    print(f"  旧语料 {len(legacy_files)} 份，键 {len(legacy_keys)} 个:")
    print("    " + " ".join(sorted(legacy_keys)))

    W = 22
    print(f"\n  {'case':<{W}}{'来源':<22}{'hash[0:12]':<14}{'字节':>5} 新增键")
    print("  " + "-" * 96)
    for r in rows:
        newk = " ".join(r["new_keys"]) or "—（无新键，但与其它所有用例的哈希都不同）"
        print(f"  {r['case']:<{W}}{r['source']:<22}{r['hash'][:12]:<14}{r['bytes']:>5} {newk}")

    covered = set()
    for r in rows:
        covered |= set(r["keys"])
    new_covered = covered - legacy_keys
    print(f"\n  富状态语料覆盖的键 {len(covered)} 个；其中旧语料从未出现过的 {len(new_covered)} 个:")
    print("    " + " ".join(sorted(new_covered)))
    print("  补全后的总键集合:")
    print("    " + " ".join(sorted(covered | legacy_keys)))

    # ── 区分性：每一类至少两条、且哈希互不相同 ──────────────────────────────────
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r)
    print("\n  每类的用例数与不同哈希数:")
    bad_groups = []
    for g, rs in sorted(groups.items()):
        distinct = len({r["hash"] for r in rs})
        flag = "OK " if (len(rs) >= 2 and distinct >= 2) else "!! "
        print(f"    {flag}{g:<8} 用例 {len(rs)}  不同哈希 {distinct}")
        if len(rs) < 2 or distinct < 2:
            bad_groups.append(g)
    assert not bad_groups, f"这些类别凑不出「两份哈希不同」的用例: {bad_groups}"

    # ── 每一条都必须带来新东西：新键，或者与**所有**已有用例都不同的哈希 ──────────
    hashes = {}
    for h, name in legacy_hashes.items():
        hashes.setdefault(h, []).append("legacy:" + name)
    for r in rows:
        hashes.setdefault(r["hash"], []).append("rich:" + r["case"])
    dupes = {h: ids for h, ids in hashes.items() if len(ids) > 1}
    for r in rows:
        if not r["new_keys"]:
            print(f"  ! {r['case']} 没有带来新键（但它与其它用例哈希不同，仍然有区分价值）")
    if dupes:
        print(f"  !! 哈希重复的用例组 {len(dupes)} 个（这些语料对差分测试没有价值）:")
        for h, ids in list(dupes.items())[:5]:
            print(f"     {h[:12]}  {', '.join(ids)}")
    assert not dupes, "富状态语料里出现了哈希完全相同的用例"

    print(f"\n  用例总数 {len(rows)}（case_{RICH_CASE_START:04d}.."
          f"case_{RICH_CASE_START + len(rows) - 1:04d}），"
          f"与旧 {len(legacy_files)} 份的哈希全部互不相同，且每类至少两份互不相同。")
    return new_covered


def rich_hash_closure(rows, stash_dir):
    """闭环：Rust 内核自己的 SHA-256 读同一批规范文本，必须给出引擎的哈希。

    这与 hash_diff.py 对旧 48 份做的事是同一条链，只是对象换成了新语料 —— 因为 hash_diff.py
    每次都会删掉 corpus/hash_cases/*.txt 并只重建它自己那 48 份，它的 --list 里塞不进新用例。
    """
    if not os.path.exists(HASHDUMP):
        print(f"\n  (跳过 Rust 闭环：找不到 {HASHDUMP})")
        return None
    listfile = os.path.join(stash_dir, "_rust_list.txt")
    outfile = os.path.join(stash_dir, "_rust_out.txt")
    with open(listfile, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(r["path"] + "\n")
    rr = subprocess.run([HASHDUMP, listfile, outfile], capture_output=True, text=True)
    if rr.returncode != 0:
        print(f"\n  !! rd-hashdump 失败: {rr.stderr.strip()}")
        return False
    print(f"\n  Rust 闭环（{os.path.basename(HASHDUMP)}）: {rr.stdout.strip()}")
    want = {r["path"]: r["hash"] for r in rows}
    got = {}
    with open(outfile, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 2:
                got[parts[0]] = parts[1]
    bad = [(os.path.basename(p), h, got.get(p)) for p, h in want.items() if got.get(p) != h]
    if bad:
        print(f"  !! Rust 与引擎不一致 {len(bad)} 条（前 5）:")
        for name, want_h, got_h in bad[:5]:
            print(f"     {name}\n       引擎: {want_h}\n       rust: {got_h}")
        return False
    print(f"  ✓ {len(want)} 份新语料：Rust 内核的 SHA-256 == 引擎的哈希（逐字节同一段文本）")
    return True


def run_rich_cases(lib):
    rows, failures, legacy_keys, legacy_hashes, legacy_files = build_rich_cases(lib)
    new_covered = report_rich_cases(rows, failures, legacy_keys, legacy_hashes, legacy_files)

    stash_dir = os.path.join(CORPUS_DIR, "hash_cases", RICH_STASH_NAME)
    doc = {
        "schema": "roguedeck-rich-hash-cases-v1",
        "generated_by": "native/make_corpus.py --rich-cases",
        "why": "corpus/hash_cases/*.txt 由 hash_diff.py 从 rd_oracle_run 生成，只覆盖 20 个键；"
               "dp=/s=/gs=/cnt=/tr=/queue=/aside= 与卡行后缀 m:/mc:/msrc:/qat:、状态行后缀 pend= "
               "从来没在语料里出现过。这一批用例把它们变成引擎真实产出的状态。",
        "regenerate": "python native/make_corpus.py --rich-cases",
        "hazard": "hash_diff.py 每次运行都会删掉 corpus/hash_cases/*.txt 并只重建它自己的 48 份"
                  "（case_0000..case_0047），本批用例会被一起删掉 —— 重跑上面的命令即可恢复；"
                  "本目录（corpus/hash_cases/rich/）是同字节的主拷贝，glob('*.txt') 不递归所以删不到。",
        "new_keys": sorted(new_covered),
        "legacy_keys": sorted(legacy_keys),
        "cases": rows,
    }
    with open(os.path.join(stash_dir, "_manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    ok = rich_hash_closure(rows, stash_dir)
    print(f"\n  主拷贝与清单: {stash_dir}")
    print(f"  语料目录:     {os.path.join(CORPUS_DIR, 'hash_cases')}")
    if ok is False:
        raise AssertionError("Rust 内核与引擎在富状态语料上不一致（见上）")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", action="store_true", help="只测吞吐，不写语料")
    ap.add_argument("--bench-n", type=int, default=20000)
    ap.add_argument("--vectors", action="store_true", help="只跑规格书向量对拍")
    ap.add_argument("--v2", action="store_true", help="只生成 golden_v2 + coverage")
    ap.add_argument("--rich-cases", action="store_true",
                    help="只生成富状态语料 corpus/hash_cases/case_01xx_*.txt"
                         "（dp=/s=/gs=/cnt=/tr=/queue=/aside=/exh=/ban=/m:/mc:/msrc:/qat:/pend=），"
                         "不碰 golden_v1/v2/coverage")
    args = ap.parse_args()

    lib, path = load_library()
    print("=" * 76)
    print("Golden 语料生成器（NativeAOT oracle）")
    print("=" * 76)
    print(f"  库: {path}  ({os.path.getsize(path) / 1048576:.2f} MB)")

    if args.bench:
        n = args.bench_n
        t0 = time.perf_counter()
        for i in range(n):
            lib.rd_oracle_run(30, 6, 12, 5, i % 1000, i % 4)
        dt = time.perf_counter() - t0
        print(f"\n  {n:,} 个战斗场景: {dt:.3f}s -> {n / dt:,.0f} 场/秒")
        print(f"  单场: {dt / n * 1e6:,.1f} µs")
        return

    # ---- 0. 哈希输入自检（导出的是 CombatStateHasher 真正喂给 SHA-256 的文本） ----
    print("\n--- 0. 规范文本自检 ---")
    run_case(lib, 0, 1, 30, 6, 12, 5)
    print(f"  rd_oracle_hash_input_ok = {lib.rd_oracle_hash_input_ok()} "
          f"(自抄的 AppendSnapshot 必须能复现引擎的哈希)")
    assert lib.rd_oracle_hash_input_ok() == 1, "导出的规范文本与引擎哈希不符"

    if args.vectors:
        results = build_spec_vectors(lib)
        out = write_vectors(results)
        print_vector_table(results)
        print(f"  向量已写入: {out}")
        return

    # ---- 0b. 富状态语料（只加 corpus/hash_cases/case_01xx_*.txt，不碰任何 golden 语料）----
    # 放在这里（而不是 ----3---- 之后）是因为它是一个**独立**的交付物：跑它不该重写
    # golden_v1/v2/spec_vectors/coverage，那四个文件由后面的完整流程负责，且 golden_v1 每次
    # 都要在 ----2---- 里跟冻结基线逐字节对账。
    if args.rich_cases:
        run_rich_cases(lib)
        return

    # ---- 1. 确定性自检（同一个 case 跑两次必须完全一致） ----
    print("\n--- 1. 确定性自检 ---")
    ok = True
    for variant, seed in [(0, 42), (2, 7), (3, 1234)]:
        a, ea = run_case(lib, variant, seed, 30, 6, 12, 5)
        b, eb = run_case(lib, variant, seed, 30, 6, 12, 5)
        same = (a == b) and a is not None
        ok &= same
        print(f"  variant={variant} seed={seed:<5} 两次一致: {'是' if same else '否'}"
              + (f"   err={ea}" if a is None else ""))
    for kw in [dict(hero_strength=2, enemy_vulnerable=1, seed=7),
               dict(card_hits=4, hero_strength=3, seed=11, variant=V_ROUND),
               dict(queue_on_play=1, seed=3, variant=V_ENDTURN)]:
        inputs = defaults(**kw)
        a, ea = call_run_ex(lib, inputs)
        b, eb = call_run_ex(lib, inputs)
        same = a is not None and a["hash"] == b["hash"] and a["detail"] == b["detail"]
        ok &= same
        print(f"  run_ex {kw} 两次一致: {'是' if same else '否'}")
    assert ok, "确定性不成立，语料不可用"

    # ---- 2. 生成 golden_v1 ----
    print("\n--- 2. golden_v1（原有 128 条，必须逐条不变）---")
    v1_cases, failures, out1 = build_corpus(lib)
    print(f"  成功 {len(v1_cases)} 条，失败 {len(failures)} 条")
    for f in failures[:5]:
        print(f"    !! {f['case']}: {f['error']}")
    hashes = [c["expect"]["hash"] for c in v1_cases]
    print(f"  不同哈希数: {len(set(hashes))} / {len(hashes)}")
    assert len(set(hashes)) > len(hashes) // 2, "语料哈希区分度太低"
    # 与冻结基线逐字节比：改了 rd_oracle_run 或引擎语义就会在这里炸，而不是悄悄换掉 128 条基准。
    # 基线放在 corpus/baseline/ 子目录里，这样 corpus/ 顶层的 *.jsonl 就正好是三个真语料，
    # 覆盖门禁扫到的文件列表不会被基线副本污染。
    baseline = os.path.join(CORPUS_DIR, "baseline", "golden_v1.jsonl")
    if os.path.exists(baseline):
        import hashlib
        digest = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()   # noqa: E731
        same = digest(out1) == digest(baseline)
        print(f"  与冻结基线(corpus/baseline/golden_v1.jsonl)逐字节一致: {'是' if same else '否'}")
        assert same, "golden_v1 变了！rd_oracle_run 的语义不能被这次改动影响"
    by_seed = {}
    for c in v1_cases:
        if c["inputs"]["seed"] == 42 and c["inputs"]["hero_hp"] == 30:
            by_seed[c["inputs"]["variant"]] = c["expect"]["hash"]
    print(f"  seed=42 下 8 个变体的哈希互不相同: "
          f"{'是' if len(set(by_seed.values())) == len(by_seed) else '否'}")

    # ---- 3. 生成 golden_v2（机制语料） ----
    print("\n--- 3. golden_v2（机制语料）---")
    v2_cases, v2_failures, out2 = build_corpus_v2(lib)
    print(f"  成功 {len(v2_cases)} 条，失败 {len(v2_failures)} 条")
    for f in v2_failures[:5]:
        print(f"    !! {f['case']}: {f['error']}")
    v2_hashes = [c["expect"]["hash"] for c in v2_cases]
    print(f"  不同哈希数: {len(set(v2_hashes))} / {len(v2_hashes)}")
    random_steps = {}
    pending = {}
    for c in v2_cases:
        random_steps[c["expect"]["random_step"]] = random_steps.get(c["expect"]["random_step"], 0) + 1
        pending[c["expect"]["pending"]] = pending.get(c["expect"]["pending"], 0) + 1
    print(f"  random_step 分布: {dict(sorted(random_steps.items()))}")
    print(f"  pending 分布: {dict(sorted(pending.items()))}")
    print("  注意：pending 数的是**待解析的效果请求**，脚本每次都会把三个队列排空，"
          "所以它恒为 0 不代表没有待办 —— 队列卡在等的是「卡牌队列」，那是 queue_count。")
    collisions = {}
    for c in v2_cases:
        collisions.setdefault(c["expect"]["hash"], []).append(
            (c["case"], c["expect"]["problems"]))
    dupes = {h: ids for h, ids in collisions.items() if len(ids) > 1}
    for h, ids in dupes.items():
        print(f"  ⚠ 哈希相同的用例组: {ids}")
        print(f"     -> 这正是「哈希只覆盖快照子集」的实证：problems 不同（早停被记录下来了）"
              f"而哈希一模一样，说明哈希盲区确实存在。")
    assert len(set(v2_hashes)) >= len(v2_hashes) * 0.9, "golden_v2 哈希区分度不足"

    # ---- 4. 规格书向量对拍 ----
    print("\n--- 4. 规格书 §7 验收向量对拍 ---")
    results = build_spec_vectors(lib)
    out3 = write_vectors(results)
    print_vector_table(results)
    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print(f"  一致 {counts.get('match', 0)} / 带口径说明的一致 {counts.get('match_with_caveat', 0)}"
          f" / 不一致 {counts.get('mismatch', 0)} / 无法表达 {counts.get('not_expressible', 0)}"
          f"   （共 {len(results)} 条）")
    print(f"  向量已写入: {out3}")

    # ---- 5. 覆盖清单 ----
    print("\n--- 5. 覆盖清单 ---")
    cov, out4 = build_coverage(lib, v1_cases, v2_cases, results)
    for name, ids in cov["mechanisms"].items():
        print(f"  {name:<22}{len(ids):>3} 条   e.g. {', '.join(ids[:3])}")
    print(f"  未覆盖: {cov['uncovered']}")
    print(f"  已写入: {out4}")

    # ---- 5b. 富状态语料（只增，不碰上面任何一个文件）----
    # 完整流程里也生成一次，这样一条命令就能恢复全部语料。失败**不**拖垮 golden 流程：
    # 这一批是加法交付物，它自己的严格断言由 `--rich-cases` 单独承担。
    try:
        run_rich_cases(lib)
    except AttributeError as ex:
        print(f"\n  (跳过富状态语料：这个 oracle 没有对应的导出 —— {ex})")
    except AssertionError as ex:
        print(f"\n  !! 富状态语料生成失败（完整流程的其余部分不受影响）：{ex}")

    # ---- 6. 抽样展示 ----
    print("\n--- 6. golden_v1 抽样（前 6 条）---")
    print(f"  {'case':<34}{'hash[0:16]':<18}{'rstep':>6}{'round':>6}{'hero':>6}{'enemy':>6}{'log':>5}")
    for c in v1_cases[:6]:
        e = c["expect"]
        print(f"  {c['case']:<34}{e['hash'][:16]:<18}{e['random_step']:>6}{e['round']:>6}"
              f"{e['hero_hp']:>6}{e['enemy_hp']:>6}{e['log_count']:>5}")

    # ---- 7. 吞吐 ----
    print("\n--- 7. 吞吐 ---")
    n = 5000
    t0 = time.perf_counter()
    for i in range(n):
        lib.rd_oracle_run(30, 6, 12, 5, i % 1000, i % 4)
    dt = time.perf_counter() - t0
    print(f"  rd_oracle_run   x{n:,}: {dt:.3f}s -> {n / dt:,.0f} 场/秒")
    t0 = time.perf_counter()
    for i in range(n):
        lib.rd_oracle_run_ex(*[v for v in defaults(seed=i % 1000, hero_strength=2).values()])
    dt = time.perf_counter() - t0
    print(f"  rd_oracle_run_ex x{n:,}: {dt:.3f}s -> {n / dt:,.0f} 场/秒")

    print(f"\n语料: {out1}\n      {out2}")
    print(f"向量: {out3}\n覆盖: {out4}")


if __name__ == "__main__":
    main()
