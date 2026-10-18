#!/usr/bin/env python3
"""fight_diff.py -- 跨语言整局对拍：Rust 内核 vs C# 参考实现，跑**同一局战斗**并比较。

# 这份脚本在验什么

两侧跑的是 `kernel/rd-fightdump` 里那四个写死的场景（`finish` / `enemy_hits` / `refusals` /
`dot_kill`）：

* **Rust 侧** —— `cargo run -p rd-fightdump --release`（经 `tools/cargo.ps1`），解析它打印的
  `scenario=… / step=… / final …` 行；
* **C# 侧** —— 加载 NativeAOT 产物（加载与错误处理照 `py/roguedeck_env/native.py`），调
  `rd_oracle_fight_run(variant, seed)`，再读 `rd_oracle_fight_steps_*` 与既有的 `rd_oracle_*` 观测量。

**卡定义 id 进哈希**，所以两边必须用同一个 id、同一段程序、同一个费用、同一个落区。C# 侧没有 RDCF
读取器，那张卡只能在 C# 里按镜像的事实手抄一遍 —— 手抄的东西会静默腐烂。所以本脚本第一件事不是对拍，
而是**闸门**：把 C# 侧实际 author 出来的内容（`rd_oracle_fight_facts_*`，从蓝图对象读出来的，不是第二份
抄写的数字）与 `tools/contentc/reader.py` 从镜像里读出来的事实**逐键比对**，并额外要求镜像里那些
"C# 侧没 author 的机制"（触发程序、被动修饰、死亡预防、拒绝施放、生命期程序……）**确实为空**。
镜像一变而 C# 侧没跟着变 ⇒ 闸门响亮失败；没有这道闸门，对拍会安静地变成"两边打的是不同的牌，而且都通过"。

# 两阶段比较（顺序不能倒）

* **阶段 A：观测量** —— 场景头（combat/seed/shuffle/hero/enemies/步数）、终局十二项
  （hero_hp / enemy_hp / round / turn / random_step / energy / hand / draw / discard / exhaust /
  steps / result / problems），以及**每步**的 (round, turn, problems, hero_hp, enemy_hp)。
  这一步先红说明**战斗进程本身**就不一样，此时去看哈希是浪费。
* **阶段 B：哈希** —— 每步之后的 SHA-256，加上终局哈希。

⚠️ `rd-fightdump` 的 `final` 行**不打终局哈希**；终局哈希就是**最后一步之后**那个哈希（最后一步不执行的
场景里，那一步不改变状态，所以仍然等于终局）。这里按这个事实比，不另造一个"终局哈希"。

# 输出格式

    一行一个观测量：  <name>  rust=<值>  csharp=<值>  OK|MISMATCH
    最后一行：       FIGHT_DIFF PASS (n/n)   或   FIGHT_DIFF FAIL (k/n)

命令行开关：

* `--verbose` —— 把闸门逐键比对的内容也打出来（默认只打一行 `GATE ok: …`）；
* `--dump-text` —— 打印 C# 侧每个场景**终局**的规范文本（`rd_oracle_hash_input_*`，已由
  `rd_oracle_hash_input_ok` 自检过"这段文本确实哈希成那个哈希"）。哈希不一致而观测量一致时，
  把它和内核 `kernel/rd-core/src/snapshot.rs` 的 `write_hash_input` 逐行对差，就能定位到具体那一行。

# 这份对拍覆盖不到的东西

* 脚本步的**内容**（不是条数）两侧没有机器可比的形式：Rust 只把每步的 (round, turn, problems) 印出来。
  步内容要是不一样，阶段 A/B 会红，但**红的位置不指向脚本**。
* 参考实现的 `problems` 是整句英文，内核是枚举；这里只比**条数**与"有没有"。
* C# 侧每步哈希来自**前缀重放**（`ScenarioRunner` 没有游标），见 `OracleExports.Fight.cs` 的类注释；
  导出里自带一条"最长前缀 == 整跑"的自检。
* 哈希只覆盖 `CombatState`；卡定义里的 tags / 费用 / 程序**不进哈希** —— 它们只能靠闸门与行为差异发现。
"""

from __future__ import annotations

import ctypes
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORACLE_PUB = os.path.join(ROOT, "native", "RogueDeck.Oracle", "bin", "x64", "Release",
                          "net10.0", "win-x64", "publish")
CARGO_PS1 = os.path.join(ROOT, "tools", "cargo.ps1")
IMAGE = os.path.join(ROOT, "tools", "contentc", "out", "content.core.rdcf")
CONTENTC = os.path.join(ROOT, "tools", "contentc")

# 必需导出：缺一个就拒绝工作（一个"找不到就跳过"的包装层会让对拍在没有对拍的情况下"通过"）。
FIGHT_FUNCS = {
    "rd_oracle_fight_run": 2,
    "rd_oracle_fight_steps_len": 0,
    "rd_oracle_fight_steps_char": 1,
    "rd_oracle_fight_facts_len": 0,
    "rd_oracle_fight_facts_char": 1,
    "rd_oracle_hash_len": 0,
    "rd_oracle_hash_char": 1,
    "rd_oracle_hash_input_len": 0,
    "rd_oracle_hash_input_char": 1,
    "rd_oracle_error_len": 0,
    "rd_oracle_error_char": 1,
    "rd_oracle_steps": 0,
    "rd_oracle_problems": 0,
    "rd_oracle_hero_hp": 0,
    "rd_oracle_enemy_hp": 0,
    "rd_oracle_enemy_hp_at": 1,
    "rd_oracle_enemy_count": 0,
    "rd_oracle_round": 0,
    "rd_oracle_turn": 0,
    "rd_oracle_random_step": 0,
    "rd_oracle_energy": 0,
    "rd_oracle_hand_count": 0,
    "rd_oracle_draw_count": 0,
    "rd_oracle_discard_count": 0,
    "rd_oracle_exhaust_count": 0,
    "rd_oracle_result": 0,
}

RESULT_NAMES = ["Ongoing", "Victory", "Defeat", "Draw", "Aborted"]

NAME_W = 34
VALUE_W = 66


class ABIMissing(RuntimeError):
    """oracle 还没被构建出来（或构建出来的是旧版本）。这不是"跳过"的理由，是必须报的错。"""


class GateFailure(RuntimeError):
    """C# 侧 author 的内容与镜像不一致 —— 对拍的前提不成立。"""


# ===========================================================================
# C# oracle
# ===========================================================================

def _find_dll() -> str:
    candidates = sorted(glob.glob(os.path.join(ORACLE_PUB, "*.dll")))
    if not candidates:
        raise ABIMissing(
            f"{ORACLE_PUB} 下没有 dll。先构建：\n"
            f"  & {os.path.join(ROOT, 'tools', 'dnaot.ps1')} publish "
            f"native/RogueDeck.Oracle/RogueDeck.Oracle.csproj -c Release -r win-x64")
    for path in candidates:
        try:
            lib = ctypes.CDLL(path)
        except OSError:
            continue
        if hasattr(lib, "rd_oracle_fight_run"):
            return path
    # 有 dll 但都没有新导出：仍然用第一个，让下面的缺失检查把缺什么列出来。
    return candidates[0]


class Oracle(object):
    def __init__(self) -> None:
        self.path = _find_dll()
        self.lib = ctypes.CDLL(self.path)
        missing = [name for name in FIGHT_FUNCS if not hasattr(self.lib, name)]
        if missing:
            raise ABIMissing(
                f"{os.path.basename(self.path)} 缺少对拍导出：{', '.join(sorted(missing))}\n"
                f"  共缺 {len(missing)}/{len(FIGHT_FUNCS)} 个。它们由 "
                f"native/RogueDeck.Oracle/OracleExports.Fight.cs 提供；重建 oracle 即可"
                f"（& tools\\dnaot.ps1 publish native/RogueDeck.Oracle/RogueDeck.Oracle.csproj "
                f"-c Release -r win-x64）。")
        for name, nargs in FIGHT_FUNCS.items():
            fn = getattr(self.lib, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int] * nargs

    # ---- 薄封装 ----

    def run(self, variant: int, seed: int) -> int:
        return self.lib.rd_oracle_fight_run(variant, seed)

    def text(self, name: str) -> str:
        length = getattr(self.lib, name + "_len")()
        if length < 0:
            raise RuntimeError(f"{name}_len() -> {length}")
        return "".join(chr(getattr(self.lib, name + "_char")(i)) for i in range(length))

    def error(self) -> str:
        return self.text("rd_oracle_error")

    def hash(self) -> str:
        return self.text("rd_oracle_hash")

    def hash_input(self) -> str:
        """C# 侧喂给 SHA-256 的那段规范文本（终局状态）。--dump-text 用它来逐行对差。"""
        return self.text("rd_oracle_hash_input")

    def facts(self) -> dict:
        return parse_facts(self.text("rd_oracle_fight_facts"))

    def steps(self) -> list:
        return [parse_kv(line) for line in self.text("rd_oracle_fight_steps").splitlines() if line]

    def enemy_hps(self) -> str:
        count = self.lib.rd_oracle_enemy_count()
        return ",".join(str(self.lib.rd_oracle_enemy_hp_at(i)) for i in range(count))

    def observables(self) -> dict:
        result = self.lib.rd_oracle_result()
        return {
            "hero_hp": self.lib.rd_oracle_hero_hp(),
            "enemy_hp": self.enemy_hps(),
            "round": self.lib.rd_oracle_round(),
            "turn": self.lib.rd_oracle_turn(),
            "random_step": self.lib.rd_oracle_random_step(),
            "energy": self.lib.rd_oracle_energy(),
            "hand": self.lib.rd_oracle_hand_count(),
            "draw": self.lib.rd_oracle_draw_count(),
            "discard": self.lib.rd_oracle_discard_count(),
            "exhaust": self.lib.rd_oracle_exhaust_count(),
            "steps": self.lib.rd_oracle_steps(),
            "result": RESULT_NAMES[result] if 0 <= result < len(RESULT_NAMES) else f"<{result}>",
            "problems": self.lib.rd_oracle_problems(),
            "hash": self.hash(),
        }


def parse_kv(line: str) -> dict:
    out = {}
    for token in line.split():
        if "=" not in token:
            raise ValueError(f"不是 key=value 片段：{token!r}（整行 {line!r}）")
        key, value = token.split("=", 1)
        out[key] = value
    return out


def parse_facts(text: str) -> dict:
    facts = {}
    for line in text.splitlines():
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"facts 里有一行不是 key=value：{line!r}")
        key, value = line.split("=", 1)
        facts[key] = value
    return facts


# ===========================================================================
# 镜像（tools/contentc/reader.py）
# ===========================================================================

# 每个实体种类**能**被 C# 侧声明、也**能**被本脚本从镜像复算的字段。
# 不在表里的字段说明闸门不知道该怎么核对它 —— 那是失败，不是跳过。
CARD_FIELDS = {"package", "costs", "tags", "program", "played_zone", "turn_end_zone",
               "retain", "is_action", "queue_on_play", "lifecycle", "play_condition"}
STATUS_FIELDS = {"package", "polarity", "stacking", "tags", "uses_stacks", "uses_duration",
                 "uses_charges", "passive_modifiers", "incoming_delay", "disclosure"}
EACTION_FIELDS = {"package", "intent", "program"}
FIELD_SETS = {"card": CARD_FIELDS, "status": STATUS_FIELDS, "enemy_action": EACTION_FIELDS}
ENTITY_TABLE = {"card": "CARD", "status": "STATUS", "enemy_action": "EACT"}
ENTITY_KIND = {"card": 1, "status": 2, "enemy_action": 3}


def unwrap(value):
    """`F_STR` 字段带一层 {value:|Value:} 包装（FLAG_WRAP_LOWER/UPPER）；剥掉它。"""
    if isinstance(value, dict):
        for key in ("value", "Value"):
            if key in value:
                return value[key]
    return value


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def selector_text(selector) -> str:
    if selector is None:
        return "none"
    kind = selector.get("kind")
    mapped = {
        "sel.eventTarget": "eventTarget",
        "sel.source": "source",
        "sel.allEnemies": "allEnemies",
    }.get(kind)
    return mapped if mapped is not None else "unsupported(" + str(kind) + ")"


def amount_text(expression) -> str:
    if expression is None:
        return "none"
    kind = expression.get("kind")
    if kind == "const":
        return "const(" + str((expression.get("value") or {}).get("Value")) + ")"
    return "unsupported(" + str(kind) + ")"


def node_text(node) -> str:
    """IR 节点 → 与 OracleExports.Fight.cs 的 NodeText 逐字节相同的文本。

    缺失的键一律取**显式默认**（镜像在线上省略与默认值相等的键，所以"缺席"与"显式默认"必须不可区分）。
    """
    if node is None:
        return "none"
    kind = node.get("kind")
    body = node.get("value") or {}
    if kind == "node.noop":
        return "noop"
    if kind == "node.sequence":
        return "sequence(" + ",".join(node_text(child) for child in body.get("Children", [])) + ")"
    if kind == "node.dealDamage":
        return ("dealDamage(amount=" + amount_text(body.get("Amount"))
                + ";element=" + ("none" if body.get("Element") is None else str(unwrap(body["Element"])))
                + ";ignores_block=" + bool_text(body.get("IgnoresBlock", False))
                + ";kind=" + str(body.get("Kind", "Direct"))
                + ";result_key=" + ("none" if body.get("ResultKey") is None else "set")
                + ";target=" + selector_text(body.get("TargetSelector")) + ")")
    if kind == "node.applyStatus":
        return ("applyStatus(charges=" + str(body.get("Charges", 0))
                + ";duration=" + str(body.get("DurationTurns", 0))
                + ";result_key=" + ("none" if body.get("ResultKey") is None else "set")
                + ";source=" + ("none" if body.get("SourceSelector") is None
                                else selector_text(body["SourceSelector"]))
                + ";stacks=" + amount_text(body.get("Stacks"))
                + ";status=" + str(unwrap(body.get("StatusDefinitionId")))
                + ";target=" + selector_text(body.get("TargetSelector")) + ")")
    return "unsupported(" + str(kind) + ")"


def program_text(program) -> str:
    if program is None:
        return "none"
    return ("program(id=" + str(unwrap(program.get("Id")))
            + ";depth=" + str(program.get("MaxNodeDepth"))
            + ";steps=" + str(program.get("MaxProgramSteps"))
            + ";root=" + node_text(program.get("Root")) + ")")


class Mirror(object):
    def __init__(self, path: str) -> None:
        if not os.path.isfile(path):
            raise RuntimeError(
                f"RDCF 镜像缺失：{path}\n  它是 tools/contentc 的构建产物，生成命令：\n"
                f"    python tools/contentc/compile.py")
        if CONTENTC not in sys.path:
            sys.path.insert(0, CONTENTC)
        import reader  # noqa: E402  (路径要先就位)
        self.reader = reader
        with open(path, "rb") as handle:
            self.rom = reader.Rom(handle.read())

    def entity(self, kind: str, entity_id: str) -> dict:
        hit = self.rom.lookup(entity_id)
        if hit is None:
            raise GateFailure(f"镜像里没有 {kind} `{entity_id}`（SEC_IDX 查不到）")
        if hit[0] != ENTITY_KIND[kind]:
            raise GateFailure(
                f"`{entity_id}` 在镜像里是 {self.reader.F.EK_NAMES.get(hit[0], hit[0])}，不是 {kind}"
                f" —— C# 侧把它当 {kind} author 了")
        return self.rom.entity(ENTITY_TABLE[kind], hit[1])


def mirror_card_facts(mirror: Mirror, card_id: str) -> dict:
    rec = mirror.entity("card", card_id)
    prefix = "card." + card_id
    costs = rec.get("Costs") or []
    return {
        prefix + ".package": rec.get("PackageId", ""),
        prefix + ".costs": "+".join(
            str(unwrap(cost.get("ResourceId"))) + ":" + str(cost.get("Amount")) for cost in costs),
        prefix + ".tags": ",".join(str(unwrap(tag)) for tag in (rec.get("Tags") or [])),
        prefix + ".program": program_text(rec.get("Program")),
        prefix + ".played_zone": rec.get("PlayedCardDestinationZone", "DiscardPile"),
        prefix + ".turn_end_zone": rec.get("TurnEndHandDestinationZone", "DiscardPile"),
        prefix + ".retain": bool_text(rec.get("RetainInHandOnTurnEnd", False)),
        prefix + ".is_action": bool_text(rec.get("IsAction", False)),
        prefix + ".queue_on_play": bool_text(rec.get("QueueOnPlay", False)),
        prefix + ".lifecycle": str(len(rec.get("LifecyclePrograms") or {})),
        prefix + ".play_condition": "none" if rec.get("PlayCondition") is None else "set",
    }


def mirror_status_facts(mirror: Mirror, status_id: str) -> dict:
    rec = mirror.entity("status", status_id)
    prefix = "status." + status_id
    return {
        prefix + ".package": rec.get("PackageId", ""),
        prefix + ".polarity": str(rec.get("Polarity")),
        prefix + ".stacking": str(rec.get("StackingBehavior")),
        prefix + ".tags": ",".join(str(unwrap(tag)) for tag in (rec.get("Tags") or [])),
        prefix + ".uses_stacks": bool_text(rec.get("UsesStacks", False)),
        prefix + ".uses_duration": bool_text(rec.get("UsesDuration", False)),
        prefix + ".uses_charges": bool_text(rec.get("UsesCharges", False)),
        prefix + ".passive_modifiers": str(len(rec.get("PassiveModifiers") or [])),
        prefix + ".incoming_delay": "none" if rec.get("IncomingStatusDelay") is None else "set",
        prefix + ".disclosure": "none" if rec.get("Disclosure") is None else "set",
    }


def mirror_enemy_action_facts(mirror: Mirror, action_id: str) -> dict:
    rec = mirror.entity("enemy_action", action_id)
    prefix = "enemy_action." + action_id
    return {
        prefix + ".package": rec.get("PackageId", ""),
        prefix + ".intent": str((rec.get("Intent") or {}).get("Kind")),
        prefix + ".program": program_text(rec.get("Program")),
    }


def mirror_emptiness_failures(mirror: Mirror, cards: list, statuses: list) -> list:
    """镜像里"存在、但 C# 侧一个字都没 author"的机制 —— 有就说明 author 得不够，行为会悄悄不一样。"""
    problems = []
    for status_id in statuses:
        rec = mirror.entity("status", status_id)
        for key in ("Triggers", "PassiveModifiers", "CombatRules"):
            if rec.get(key):
                problems.append(f"镜像的 status `{status_id}`.{key} 非空（{len(rec[key])} 条），"
                                f"C# 侧一条都没 author")
        for key in ("DeathPrevention", "DebuffBlock", "IncomingStatusDelay", "Disclosure"):
            if rec.get(key) is not None:
                problems.append(f"镜像的 status `{status_id}`.{key} 非空，C# 侧没 author")
    for card_id in cards:
        rec = mirror.entity("card", card_id)
        if rec.get("LifecyclePrograms"):
            problems.append(f"镜像的 card `{card_id}`.LifecyclePrograms 非空，C# 侧没 author")
        if rec.get("PlayCondition") is not None:
            problems.append(f"镜像的 card `{card_id}`.PlayCondition 非空，C# 侧没 author")
        if rec.get("IsAction"):
            problems.append(f"镜像的 card `{card_id}`.IsAction 为真，C# 侧 author 的是 false")
    return problems


def fact_entities(facts: dict) -> tuple:
    """从 facts 的键里认出 C# 侧到底 author 了哪些实体（自描述，不靠另一份名单）。"""
    found = {"card": [], "status": [], "enemy_action": []}
    for key in facts:
        parts = key.split(".")
        if len(parts) < 3:
            continue
        kind, field = parts[0], parts[-1]
        if kind not in FIELD_SETS or field not in FIELD_SETS[kind]:
            continue
        entity_id = ".".join(parts[1:-1])
        if entity_id not in found[kind]:
            found[kind].append(entity_id)
    return found["card"], found["status"], found["enemy_action"]


# C# 侧"这一局没用到这些机制"的自钉。镜像那一侧由 mirror_emptiness_failures 覆盖。
CONTENT_PINS = (
    ("content.allies", "0"),
    ("content.triggered_programs", "0"),
    ("content.pre_down_interceptors", "0"),
    ("content.status_application_interceptors", "0"),
    ("content.defensive_pools", "0"),
    ("content.turn_start_refills", "0"),      # 标准包自己就装了一条 energy 补能（StandardCombatPackage.cs:124）
    ("content.cards_drawn_per_turn", "5"),
    ("content.cell_exclusive", "false"),
    ("content.simultaneous_team_turns", "false"),
)


def gate(oracle: Oracle, mirror: Mirror, verbose: bool) -> tuple:
    """把 C# 侧 author 的内容与镜像逐键比对。返回 (比对键数, 实体计数)；不一致就抛 GateFailure。"""
    facts = oracle.facts()
    cards, statuses, actions = fact_entities(facts)
    if not (cards or statuses or actions):
        raise GateFailure("rd_oracle_fight_facts 里没有任何 card./status./enemy_action. 事实 —— "
                          "闸门无事可做，这比不一致更糟（它会是静默的全绿）")

    expected = {}
    for card_id in cards:
        expected.update(mirror_card_facts(mirror, card_id))
    for status_id in statuses:
        expected.update(mirror_status_facts(mirror, status_id))
    for action_id in actions:
        expected.update(mirror_enemy_action_facts(mirror, action_id))

    failures = []
    for key, mirror_value in sorted(expected.items()):
        if key not in facts:
            failures.append(f"{key}: 镜像说 {mirror_value!r}，C# 侧根本没有这条事实")
        elif facts[key] != mirror_value:
            failures.append(f"{key}: C# 侧 {facts[key]!r} != 镜像 {mirror_value!r}")
    for key in sorted(facts):
        parts = key.split(".")
        if len(parts) >= 3 and parts[0] in FIELD_SETS and key not in expected:
            failures.append(f"{key}: C# 侧声明了一条闸门不知道怎么核对的事实（先教它，再让它通过）")
    failures.extend(mirror_emptiness_failures(mirror, cards, statuses))
    for key, want in CONTENT_PINS:
        if key not in facts:
            failures.append(f"{key}: C# 侧没声明这条事实")
        elif facts[key] != want:
            failures.append(f"{key}: C# 侧 {facts[key]!r}，对拍约定的是 {want!r}")

    if failures:
        raise GateFailure(
            f"C# 侧 author 的内容与镜像不一致（{len(failures)} 处）：\n  "
            + "\n  ".join(failures)
            + "\n  对拍的前提是两边打同一张卡；先修好 authoring，再谈哈希。")

    if verbose:
        for key, value in sorted(expected.items()):
            print(f"  gate {key} = {value}")
    return len(expected) + len(CONTENT_PINS), (cards, statuses, actions)


# ===========================================================================
# Rust 侧
# ===========================================================================

def powershell() -> str:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    candidate = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return candidate if os.path.isfile(candidate) else "powershell.exe"


def run_rust_dump() -> list:
    """跑 `cargo run -p rd-fightdump --release`（经 tools/cargo.ps1，位置参数），返回输出行。"""
    if not os.path.isfile(CARGO_PS1):
        raise RuntimeError(f"找不到 {CARGO_PS1}")
    proc = subprocess.run(
        [powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", CARGO_PS1,
         "run", "-p", "rd-fightdump", "--release"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    lines = out.splitlines()
    verdict = [line for line in lines if line.startswith("=== EXIT")]
    if not verdict:
        raise RuntimeError(
            "cargo.ps1 没有打印 `=== EXIT n ===` —— 无法判断内核到底跑没跑（它的退出码是承重的）。\n"
            f"stdout:\n{out}\nstderr:\n{err}")
    code = int(verdict[-1].split()[-2])
    if code != 0:
        raise RuntimeError(f"rd-fightdump 退出码 {code}（这不是『跑完了』）：\n"
                           f"stdout:\n{out}\nstderr:\n{err}")
    return lines


def parse_rust(lines: list) -> tuple:
    """→ (info, [scenario dict])。认不出来的行 = 失败（不静默忽略）。

    `cargo.ps1` 把 cargo 自己的 stderr（无害的 `unused config key http.no_proxy` 之类）接在
    `=== STDERR ===` 之后 —— 那不是 dump 的输出，解析到那里就停。
    """
    info = {}
    scenarios = []
    current = None
    for line in lines:
        if line.startswith("=== STDERR"):
            break
        if line.startswith("===") or not line.strip():
            continue
        if line.startswith("image="):
            # 路径可能带空格：从 "image=" 取到 " bytes=" 为止。
            match = re.match(r"^image=(.*) bytes=(\d+) cards=(\d+) enemy_actions=(\d+) encounters=(\d+)$",
                             line)
            if match is None:
                raise RuntimeError(f"image 行的形状变了：{line!r}")
            info.update({"image": match.group(1), "bytes": match.group(2), "cards": match.group(3),
                         "enemy_actions": match.group(4), "encounters": match.group(5)})
            continue
        if line.startswith("deviations="):
            info["deviations"] = line[len("deviations="):]
            continue
        if line.startswith("scenario="):
            current = {"header": parse_kv(line), "steps": [], "final": None}
            scenarios.append(current)
            continue
        if line.startswith("step="):
            if current is None:
                raise RuntimeError(f"step 行出现在任何 scenario 之前：{line!r}")
            current["steps"].append(parse_kv(line))
            continue
        if line.startswith("final "):
            if current is None:
                raise RuntimeError(f"final 行出现在任何 scenario 之前：{line!r}")
            current["final"] = parse_kv(line[len("final "):])
            continue
        raise RuntimeError(f"rd-fightdump 打了一行本脚本不认识的东西：{line!r}")
    return info, scenarios


# ===========================================================================
# 比较
# ===========================================================================

class Table(object):
    def __init__(self) -> None:
        self.total = 0
        self.bad = 0
        self.first = None

    def row(self, name: str, rust, csharp) -> bool:
        left, right = str(rust), str(csharp)
        ok = left == right
        self.total += 1
        if not ok:
            self.bad += 1
            if self.first is None:
                self.first = (name, left, right)
        print(f"{name:<{NAME_W}} rust={left:<{VALUE_W}} csharp={right:<{VALUE_W}} "
              f"{'OK' if ok else 'MISMATCH'}")
        return ok


FINAL_OBSERVABLES = ("hero_hp", "enemy_hp", "round", "turn", "random_step", "energy",
                     "hand", "draw", "discard", "exhaust", "steps", "result")
STEP_OBSERVABLES = ("round", "turn", "problems", "hero_hp", "enemy_hp")


def collect(oracle: Oracle, facts: dict, by_name: dict, scenarios: list) -> list:
    """把四个场景都跑一遍，把两侧的结果收进一个结构（先收齐，再分两阶段打印）。"""
    collected = []
    for rust in scenarios:
        name = rust["header"].get("scenario")
        if name not in by_name:
            raise GateFailure(
                f"rd-fightdump 打了场景 `{name}`，但 C# 侧的场景表里没有这个名字"
                f"（有：{', '.join(sorted(by_name))}）—— 两边的脚本表不一致，先对齐脚本")
        variant = by_name[name]
        seed = int(rust["header"]["seed"])
        code = oracle.run(variant, seed)
        if code <= 0:
            raise RuntimeError(
                f"rd_oracle_fight_run(variant={variant}, seed={seed}) -> {code}；{oracle.error()}")
        collected.append({
            "name": name,
            "variant": variant,
            "seed": seed,
            "rust": rust,
            "facts": facts,
            "observables": oracle.observables(),
            "steps": oracle.steps(),
            # 终局状态的规范文本（C# 侧）。只在 --dump-text 时打印/使用，但它必须**在此时**取：
            # `_hashInput` 是"最后一次 run"的，下一次 run 就会覆盖它。
            "hash_input": oracle.hash_input(),
        })
    return collected


def stage_a(table: Table, item: list) -> None:
    """阶段 A：场景头 + 终局观测量 + 每步的 (round, turn, problems, 血量)。"""
    rust = item["rust"]
    header = rust["header"]
    final = rust["final"] or {}
    facts = item["facts"]
    variant = item["variant"]
    side = item["observables"]
    steps = item["steps"]
    prefix = item["name"] + "."

    # 场景头：C# 侧的 authoring 与内核的蓝图是同一份吗（不是哈希，但一样要一致）
    table.row(prefix + "combat", header.get("combat"), facts.get(f"scenario.{variant}.combat"))
    table.row(prefix + "seed", header.get("seed"), facts.get(f"scenario.{variant}.seed"))
    table.row(prefix + "shuffle", header.get("shuffle"), facts.get(f"scenario.{variant}.shuffle"))
    table.row(prefix + "hero", header.get("hero"), facts.get(f"scenario.{variant}.hero"))
    table.row(prefix + "enemies", header.get("enemies"), facts.get(f"scenario.{variant}.enemies"))
    table.row(prefix + "step_count", len(rust["steps"]),
              facts.get(f"scenario.{variant}.steps"))

    for key in FINAL_OBSERVABLES:
        if key == "enemy_hp":
            # ⚠️ `rd-fightdump` 的 `final` 行**不打 enemy_hp**（它逐步骤打过）。终局的敌人血量 =
            # 最后一步之后那一行里的值；这里就按这个事实比，不假装 final 行里有它。
            table.row(prefix + key, rust["steps"][-1].get("enemy_hp") if rust["steps"] else None,
                      side.get(key))
            continue
        table.row(prefix + key, final.get(key), side.get(key))
    # 参考的 problems 是整句英文、内核是枚举 ⇒ 只比"有没有"（`rd_oracle_problems` 就是这个 0/1）。
    table.row(prefix + "problems", 1 if any(int(step.get("problems", 0)) > 0
                                            for step in rust["steps"]) else 0, side.get("problems"))

    table.row(prefix + "dump_steps", len(rust["steps"]), len(steps))
    for index, rust_step in enumerate(rust["steps"]):
        if index >= len(steps):
            table.row(f"{prefix}step{index}.present", "yes", "no")
            continue
        step = steps[index]
        table.row(f"{prefix}step{index}.index", rust_step.get("step"), step.get("step"))
        for key in STEP_OBSERVABLES:
            table.row(f"{prefix}step{index}.{key}", rust_step.get(key), step.get(key))


def stage_b(table: Table, item: list) -> None:
    """阶段 B：每步之后的哈希 + 终局哈希（== 最后一步之后那个哈希）。"""
    rust = item["rust"]
    steps = item["steps"]
    prefix = item["name"] + "."
    for index, rust_step in enumerate(rust["steps"]):
        if index >= len(steps):
            table.row(f"{prefix}step{index}.hash", rust_step.get("hash"), "<missing>")
            continue
        table.row(f"{prefix}step{index}.hash", rust_step.get("hash"), steps[index].get("hash"))
    # `final` 行不打终局哈希：终局状态就是最后一步之后的状态。
    final_hash = rust["steps"][-1].get("hash") if rust["steps"] else None
    table.row(prefix + "final_hash", final_hash, item["observables"].get("hash"))


# ===========================================================================
# main
# ===========================================================================

def main(argv: list) -> int:
    verbose = "--verbose" in argv or "-v" in argv
    dump_text = "--dump-text" in argv

    oracle = Oracle()
    print(f"oracle   {oracle.path}")
    mirror = Mirror(IMAGE)
    print(f"image    {IMAGE} ({os.path.getsize(IMAGE)} B)")

    # 闸门。facts 是 FightRun 的产物（而且描述的是整张场景表），所以先跑一次 variant 0 把它取出来。
    probe = oracle.run(0, 0)
    if probe <= 0:
        raise RuntimeError(f"rd_oracle_fight_run(0, 0) -> {probe}；{oracle.error()}")
    checked, entities = gate(oracle, mirror, verbose)
    cards, statuses, actions = entities
    print(f"GATE     ok: C# 侧 author 的 {len(cards)} 卡（{', '.join(cards)}）/ "
          f"{len(statuses)} 状态（{', '.join(statuses)}）/ "
          f"{len(actions)} 敌人动作（{', '.join(actions)}）与镜像逐键一致，"
          f"{checked} 条事实")
    facts = oracle.facts()
    by_name = {}
    for key, value in facts.items():
        match = re.fullmatch(r"scenario\.(\d+)\.name", key)
        if match:
            by_name[value] = int(match.group(1))

    lines = run_rust_dump()
    info, scenarios = parse_rust(lines)
    print(f"rust     image={info.get('image')} bytes={info.get('bytes')} "
          f"cards={info.get('cards')} enemy_actions={info.get('enemy_actions')}")
    print(f"         deviations={info.get('deviations')}")
    if not scenarios:
        raise RuntimeError("rd-fightdump 一个场景都没打印")

    collected = collect(oracle, facts, by_name, scenarios)

    table = Table()
    print()
    print("# 阶段 A：观测量（这一阶段先红 ⇒ 战斗进程本身不同，去看哈希是浪费）")
    for item in collected:
        print(f"# scenario {item['name']} (csharp variant {item['variant']}, seed {item['seed']})")
        stage_a(table, item)

    print()
    print("# 阶段 B：每步之后的 SHA-256 与终局哈希")
    for item in collected:
        print(f"# scenario {item['name']} (csharp variant {item['variant']})")
        stage_b(table, item)

    if table.first is not None:
        name, left, right = table.first
        print()
        print(f"# 第一个分叉：{name}")
        print(f"#   rust   {left}")
        print(f"#   csharp {right}")

    if dump_text:
        # 哈希不一致但观测量一致时，唯一能定位的东西就是这段文本：它是 C# 真正喂给 SHA-256 的字节
        # （`rd_oracle_hash_input_ok` 自检过），和内核 `snapshot.rs` 的写法逐行对差即可。
        for item in collected:
            print()
            print(f"# ---- C# 规范文本：{item['name']} 终局（csharp_hash {item['observables'].get('hash')}）----")
            print(item["hash_input"], end="")
            print("# ---- 文本结束 ----")

    print()
    if table.bad == 0:
        print(f"FIGHT_DIFF PASS ({table.total}/{table.total})")
        return 0
    print(f"FIGHT_DIFF FAIL ({table.bad}/{table.total})")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except GateFailure as failure:
        print()
        print("GATE FAIL")
        print(str(failure))
        print()
        print("FIGHT_DIFF FAIL (gate)")
        sys.exit(1)
    except ABIMissing as failure:
        print()
        print("ABI MISSING")
        print(str(failure))
        print()
        print("FIGHT_DIFF FAIL (abi)")
        sys.exit(1)
    except RuntimeError as failure:
        print()
        print("ERROR")
        print(str(failure))
        print()
        print("FIGHT_DIFF FAIL (error)")
        sys.exit(1)
