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

# 两层：整局流程（FIGHT_DIFF）与逐卡（CARD_DIFF）

上面那四局打的是**整局流程**，只覆盖 2 张卡。`CARD_DIFF` 是它的补充层：镜像里**每一张**卡
（今天 62 张）各一局固定形状的短战斗 —— 牌组里只有它自己、能量给足、敌人血量高到一张卡打不死、
脚本只有"打出它" —— 两侧比每步哈希与终局哈希，并逐键核对"两边打的是同一张卡"。

    一行一张卡：      card=<卡 id>  index=<行号>  steps=<n>  facts=<n>  hash=<12hex>..  OK|MISMATCH
    最后一层结论：    CARD_DIFF PASS (n/62)   或   CARD_DIFF FAIL (k/62) + 每张失败卡的原因

卡程序**不进哈希**（进哈希的是卡定义 id），所以逐卡这一层的前提是"两边 author 的是同一张卡"。
Rust 侧的程序来自镜像；C# 侧没有 RDCF 读取器，只能按 `native/card_specs.json`（由
`native/gen_card_specs.py` 从镜像派生）把它翻译成引擎的 typed node。三道闸门守这个前提：

* **陈旧闸门** —— 磁盘上的 `card_specs.json` 必须与"现在从镜像重新派生一遍"逐字节相同
  （镜像变了而 spec 没重生成 ⇒ 红）。顺带核对 oracle 读进来的就是这份字节。
* **顺序闸门** —— `card=<id>`、`index=<行号>` 与镜像的 `CARD` 行号必须一一对上
  （两边卡序不同 ⇒ 红；否则会拿 A 的哈希比 B 的哈希）。
* **内容闸门** —— C# 侧报出来的每一条事实（每张卡的费用/tags/落区/程序的规范文本、每个状态的
  极性/叠加/被动修饰/触发器程序、敌人动作、以及**战斗形状**）与镜像逐键比对；C# 侧多报一条
  "闸门不知道怎么核对"的事实也算失败。

逐张卡自己的失败（C# 侧 author 不出来、或哈希不同）不是闸门失败：它记成一行 `MISMATCH` 并计入
`k/62`。**"62/62" 必须是真数** —— 一张 author 不出来的卡也算在分母里。

# 第 1 层扩展：逐卡 × 跨回合（CARD_MULTI）

`CARD_DIFF` 每张卡只打一步 ⇒ 弃手牌 / 抽回来 / 重洗 / 补能 / DoT tick / 敌人出手全都照不到。
这一层每张卡跑 **2 个变体、每个变体 4 步**，比每步哈希（不是只比终局）：

    变体 play_again      打它 → 结束回合 → 转过一整轮 → 再打它      （牌组 2 张 ⇒ 必然重洗）
    变体 enemy_then_wrap 打它 → 结束回合 → 敌人动作 → 转回英雄回合   （牌组 1 张 ⇒ 重洗取决于落区）

    一行一个变体：    card=<卡 id>  index=<行号>  variant=<名字>  steps=<n>  hash=<12hex>..  OK|MISMATCH
                      …/NOT-COMPARABLE  内核缺钩子：<哪个状态的哪个触发器>
    结论：            CARD_MULTI PASS (n/m)   或   CARD_MULTI FAIL (k/m) + 每个失败变体的原因

`NOT-COMPARABLE` 是**明确的第三种结果**，不是跳过：它要求两个条件都成立 —— 卡的程序把带
**内核未建模触发器**的状态打到敌人身上，**并且**这一局的脚本里敌人真的出手。那时两侧必然不同，
原因逐行打出来并**计入分母**（`kernel_gap_for`；内核那一侧的依据是 `host.rs` 的 `not_handled=12`）。

# 第 2 层：逐敌人动作（ENEMY_DIFF）

镜像里每一条 `EACT` 各一局固定形状的短战斗：**它所属的敌人** + 英雄（牌组为空），脚本两步
（结束英雄回合、让它执行这条动作）。在那之前 394 条里只有 `desk_jab` 一条被执行过。

    一行一条：        enemy=<动作 id>  index=<行号>  steps=<n>  hash=<12hex>..  OK|MISMATCH
                      enemy=<动作 id>  index=<行号>  NOT-AUTHORED  <oracle 说为什么 author 不出来>
    结论：            ENEMY_DIFF PASS (n/394)   或   ENEMY_DIFF FAIL (k/394) + 每条的原因

`NOT-AUTHORED` 同样计入分母：C# 侧遇到本 build 不认识的节点/表达式/选择器时会**抛错并带上位置**，
本脚本把它记成一行而不是"这张跳过"。今天 394 条全部可 author（`setCombatantCounter`、
`add`/`min`/`divide`/`combatantCounter`、`sel.allAllies`、`conditional`+`compare`、
`loseResource`、三种触发器上下文都在这一轮补上了）。

一条命令重跑基线（四层全跑、每层数字都打、结论再汇总一遍）：

    $env:PYTHONIOENCODING='utf-8'; C:\\Users\\TK11\\miniforge3\\python.exe native\\fight_diff.py

    # 先决条件：`native/RogueDeck.Oracle/bin/x64/Release/native/*.dll` 存在（缺了会以 ABIMissing
    # 响亮失败并打印重建命令：`& tools\\dnaot.ps1 publish native/RogueDeck.Oracle/RogueDeck.Oracle.csproj
    # -c Release -r win-x64`）。C# 侧是**参考**，改内核不需要重建它。
    # 看结果用这一条：`Select-String -Path <日志> -Pattern '^# SUM '`

命令行开关：

* `--verbose` —— 把闸门逐键比对的内容也打出来（默认只打一行 `GATE ok: …`）；
* `--dump-text` —— 打印 C# 侧每个场景**终局**的规范文本（`rd_oracle_hash_input_*`，已由
  `rd_oracle_hash_input_ok` 自检过"这段文本确实哈希成那个哈希"）。哈希不一致而观测量一致时，
  把它和内核 `kernel/rd-core/src/snapshot.rs` 的 `write_hash_input` 逐行对差，就能定位到具体那一行。

# 这份对拍覆盖不到的东西（2026-10-19 更新：前两条原来的盲区已经被新加的两层部分覆盖）
#
# * 逐卡这一层（`CARD_DIFF`）只打一步 ⇒ 它不覆盖跨回合的东西。那一半现在归 `CARD_MULTI`
#   （每张卡 2 个 4 步变体：弃手牌 / 抽回来 / 重洗 / 补能 / 敌人出手）。
# * 敌人动作：`ENEMY_DIFF` 让镜像里**全部** `EACT` 各跑一局 —— 在那之前只有 `desk_jab` 一条被执行过。
#
# 仍然没覆盖的：
#
# * 脚本步的**内容**（不是条数）两侧没有机器可比的形式。每步会打 (round, turn, problems, chain, exec)，
#   步内容要是不一样，阶段 A/B 会红，但**红的位置不指向脚本**。
# * 参考实现的 `problems` 是整句英文，内核是枚举；这里只比**条数**与"有没有"。
# * C# 侧每步哈希来自**前缀重放**（`ScenarioRunner` 没有游标），见 `OracleExports.Fight.cs` 的类注释；
#   每个导出里都自带一条"最长前缀 == 整跑"的自检。
# * 哈希只覆盖 `CombatState`；卡定义里的 tags / 费用 / 程序**不进哈希** —— 它们只能靠闸门与行为差异发现。
# * **内核缺钩子**的触发器事件（`kernel/rd-core/src/host.rs:2299-2302`：6 种，`DamageDealt` 在里面；
#   同文件的测试把它钉成 `not_handled=12`）。内容里凡是"戴着这种状态去触发那个事件"的局面，两侧**必然**
#   不同 —— 那不是对拍能回答的问题。`CARD_MULTI` 把这类局面逐行打成 `NOT-COMPARABLE` 并**计入分母**
#   （不静默、也不算绿）；`ENEMY_DIFF` 今天 394/394 全一致，说明那 394 条动作没有一条真的让它发生。
# * `CombatState.TriggerActivity` 两侧都不进哈希文本（`CombatStateHasher.cs:26-71` 里没有它，
#   `snapshot.rs:144-205` 也没有），所以"哪个触发器跑过几次"**不在任何一条对拍里**。这是两侧的
#   **共同盲区**（不是偏差）：一侧多跑一次触发器，只要最终状态相同，哈希就相同。
# * `doubt` 的"伤害 ×75%"被动在 `ENEMY_DIFF` 里仍是惰性的：那 10 条施加它的动作把 doubt 打到**英雄**
#   身上，而这一局里英雄不再出手。`CARD_MULTI` 的变体 B 才真的让它在**敌人**身上生效 —— 但那里同时
#   撞上上面那条 `DamageDealt` 钩子缺口，所以"被动生效"与"触发器不 fire"今天混在同一格里，
#   只能整体记成不可对照（见 `kernel_gap_for`）。
"""

from __future__ import annotations

import ctypes
import glob
import json
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

# `native/gen_card_specs.py` 是 spec 的生成器，也是本脚本核对"磁盘上的 spec 是否陈旧"的那把尺子。
# 它就在本文件隔壁，所以不引入任何新依赖。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_card_specs  # noqa: E402

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

# 逐卡这一层要的导出（`native/RogueDeck.Oracle/OracleExports.Cards.cs`）。同样是一个都不许缺。
CARD_FUNCS = {
    "rd_oracle_card_specs_text_len": 0,
    "rd_oracle_card_specs_text_char": 1,
    "rd_oracle_card_count": 0,
    "rd_oracle_card_run": 2,
    "rd_oracle_card_steps_len": 0,
    "rd_oracle_card_steps_char": 1,
    "rd_oracle_card_facts_len": 0,
    "rd_oracle_card_facts_char": 1,
}

NAME_W = 34
VALUE_W = 66

# 逐卡多层（`CARD_MULTI`）与逐敌人动作（`ENEMY_DIFF`）要的导出
# （`native/RogueDeck.Oracle/OracleExports.Layers.cs`）。同样一个都不许缺。
MULTI_FUNCS = {
    "rd_oracle_card_multi_run": 2,
    "rd_oracle_card_multi_steps_len": 0,
    "rd_oracle_card_multi_steps_char": 1,
    "rd_oracle_card_multi_facts_len": 0,
    "rd_oracle_card_multi_facts_char": 1,
}
ENEMY_FUNCS = {
    "rd_oracle_enemy_action_count": 0,
    "rd_oracle_enemy_run": 2,
    "rd_oracle_enemy_steps_len": 0,
    "rd_oracle_enemy_steps_char": 1,
    "rd_oracle_enemy_facts_len": 0,
    "rd_oracle_enemy_facts_char": 1,
}
ALL_FUNCS = {}
for _table in (FIGHT_FUNCS, CARD_FUNCS, MULTI_FUNCS, ENEMY_FUNCS):
    ALL_FUNCS.update(_table)


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
        missing = [name for name in ALL_FUNCS if not hasattr(self.lib, name)]
        if not hasattr(self.lib, "rd_oracle_card_specs_load"):
            missing.append("rd_oracle_card_specs_load")
        if missing:
            raise ABIMissing(
                f"{os.path.basename(self.path)} 缺少对拍导出：{', '.join(sorted(set(missing)))}\n"
                f"  共缺 {len(set(missing))}/{len(ALL_FUNCS) + 1} 个。它们由 "
                f"native/RogueDeck.Oracle/OracleExports.Fight.cs / .Cards.cs / .Layers.cs 提供；重建 oracle 即可"
                f"（& tools\\dnaot.ps1 publish native/RogueDeck.Oracle/RogueDeck.Oracle.csproj "
                f"-c Release -r win-x64）。")
        for name, nargs in ALL_FUNCS.items():
            fn = getattr(self.lib, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_int] * nargs
        # 唯一一个指针参数：spec 的 UTF-8 路径。它显式传进来（而不是由 dll 猜自己的相对路径），
        # 是为了让"读的是哪份 spec"变成调用方的一句话，而不是一段运气。
        self.lib.rd_oracle_card_specs_load.restype = ctypes.c_int
        self.lib.rd_oracle_card_specs_load.argtypes = [ctypes.c_char_p]

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

    # ---- 逐卡这一层 ----

    def load_card_specs(self, path: str) -> int:
        return self.lib.rd_oracle_card_specs_load(path.encode("utf-8"))

    def card_specs_text(self) -> str:
        return self.text("rd_oracle_card_specs_text")

    def card_count(self) -> int:
        return self.lib.rd_oracle_card_count()

    def card_run(self, index: int, seed: int) -> int:
        return self.lib.rd_oracle_card_run(index, seed)

    def card_facts(self) -> dict:
        return parse_facts(self.text("rd_oracle_card_facts"))

    def card_steps(self) -> list:
        return [parse_kv(line) for line in self.text("rd_oracle_card_steps").splitlines() if line]

    # ---- 逐卡多层这一层 ----

    def card_multi_run(self, index: int, variant: int) -> int:
        return self.lib.rd_oracle_card_multi_run(index, variant)

    def card_multi_facts(self) -> dict:
        return parse_facts(self.text("rd_oracle_card_multi_facts"))

    def card_multi_steps(self) -> list:
        return [parse_kv(line) for line in self.text("rd_oracle_card_multi_steps").splitlines() if line]

    # ---- 逐敌人动作这一层 ----

    def enemy_action_count(self) -> int:
        return self.lib.rd_oracle_enemy_action_count()

    def enemy_run(self, index: int, seed: int) -> int:
        return self.lib.rd_oracle_enemy_run(index, seed)

    def enemy_facts(self) -> dict:
        return parse_facts(self.text("rd_oracle_enemy_facts"))

    def enemy_steps(self) -> list:
        return [parse_kv(line) for line in self.text("rd_oracle_enemy_steps").splitlines() if line]

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


def run_rust_dump(extra=()) -> list:
    """跑 `cargo run -p rd-fightdump --release`（经 tools/cargo.ps1，位置参数），返回输出行。

    `extra` 是喂给二进制的参数（`--cards`）；cargo 自己的 `--` 之后才轮到它。
    """
    if not os.path.isfile(CARGO_PS1):
        raise RuntimeError(f"找不到 {CARGO_PS1}")
    command = [powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", CARGO_PS1,
               "run", "-p", "rd-fightdump", "--release"]
    if extra:
        command.append("--")
        command.extend(extra)
    proc = subprocess.run(
        command,
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


def parse_rust(lines: list, block_key: str = "scenario") -> tuple:
    """→ (info, [block dict])。认不出来的行 = 失败（不静默忽略）。

    `cargo.ps1` 把 cargo 自己的 stderr（无害的 `unused config key http.no_proxy` 之类）接在
    `=== STDERR ===` 之后 —— 那不是 dump 的输出，解析到那里就停。

    `block_key` 是块头行的键名：整局场景是 `scenario=`，逐卡是 `card=`。另一个键名出现就是格式错了。
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
        if line.startswith(block_key + "="):
            current = {"header": parse_kv(line), "steps": [], "final": None}
            scenarios.append(current)
            continue
        if line.startswith("step="):
            if current is None:
                raise RuntimeError(f"step 行出现在任何 {block_key} 之前：{line!r}")
            current["steps"].append(parse_kv(line))
            continue
        if line.startswith("final "):
            if current is None:
                raise RuntimeError(f"final 行出现在任何 {block_key} 之前：{line!r}")
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
# 逐卡这一层（CARD_DIFF）
#
# 上面那四局打的是"整局流程"；这一层打的是**每一张卡自己的效果**：镜像里 62 张卡各一局，
# 牌组里只有它自己，脚本只有"打出它"。卡程序不进哈希（进哈希的是卡定义 id），所以两侧必须打
# 同一张卡、同一段程序 —— Rust 侧读镜像，C# 侧按 `native/card_specs.json` author，
# 本脚本把两边的东西逐键对差。
# ===========================================================================

SPEC_JSON = os.path.join(ROOT, "native", "card_specs.json")

# 逐卡战斗的固定形状。**与 kernel/rd-fightdump 的 CARD_* 常量、OracleExports.Cards.cs 的
# Card* 常量是三份**，各处都钉住同一个数：改任意一处，这里就红。这不是冗余，是"三边必须一致"
# 这条要求的可执行形式。
CARD_SHAPE = {
    "combat": "card_diff",
    "seed": "1",
    "shuffle": "false",
    "hero": "hero/70",
    "enemies": "queue_imp/500",
    "energy": "standard.energy:10/10",
    "energy_refill": "3",
    "steps": "1",
}
CARD_ENEMY = "queue_imp"
CARD_ACTION = "queue_imp.desk_jab"

# 逐卡这一层**不** author 的东西（与整局那层同一套钉，唯独 triggered_programs 不同 ——
# 卡程序引用到的状态自带触发器，条数由镜像算出来，见 card_layer_expected）。
CARD_CONTENT_PINS = (
    ("content.allies", "0"),
    ("content.pre_down_interceptors", "0"),
    ("content.status_application_interceptors", "0"),
    ("content.defensive_pools", "0"),
    ("content.turn_start_refills", "0"),
    ("content.cards_drawn_per_turn", "5"),
    ("content.cell_exclusive", "false"),
    ("content.simultaneous_team_turns", "false"),
)


def card_layer_expected(spec: dict, mirror: "Mirror") -> dict:
    """从镜像派生的卡描述 → C# 侧应该报出来的每一条事实。"""
    expected = {}
    for card in spec["cards"]:
        index = card["index"]
        expected[f"cards.{index}.index"] = str(index)
        expected[f"cards.{index}.id"] = card["id"]

        prefix = "card." + card["id"]
        expected[prefix + ".package"] = card["package"]
        expected[prefix + ".costs"] = "+".join(
            cost["resource"] + ":" + str(cost["amount"]) for cost in card["costs"])
        expected[prefix + ".tags"] = ",".join(card["tags"])
        program = card["program"]
        expected[prefix + ".program"] = ("program(id=" + program["id"]
                                         + ";depth=" + str(program["depth"])
                                         + ";steps=" + str(program["steps"])
                                         + ";root=" + gen_card_specs.node_text(program["root"]) + ")")
        expected[prefix + ".played_zone"] = card["played_zone"]
        expected[prefix + ".turn_end_zone"] = card["turn_end_zone"]
        expected[prefix + ".retain"] = gen_card_specs.bool_text(card["retain"])
        expected[prefix + ".is_action"] = gen_card_specs.bool_text(card["is_action"])
        expected[prefix + ".queue_on_play"] = gen_card_specs.bool_text(card["queue_on_play"])
        expected[prefix + ".lifecycle"] = str(card["lifecycle"])
        expected[prefix + ".play_condition"] = ("none" if card["play_condition"] is None else "set")
    expected["card_count"] = str(len(spec["cards"]))

    trigger_count = 0
    for status in spec["statuses"]:
        # 逐卡这一层只 author 卡程序引用到的状态（spec 里 `used_by` 说得明白）；敌人动作那一侧
        # 需要的状态由那一层自己 author、自己核对。
        if "cards" not in status["used_by"]:
            continue
        prefix = "status." + status["id"]
        expected[prefix + ".package"] = status["package"]
        expected[prefix + ".polarity"] = status["polarity"]
        expected[prefix + ".stacking"] = status["stacking"]
        expected[prefix + ".tags"] = ",".join(status["tags"])
        expected[prefix + ".uses_stacks"] = gen_card_specs.bool_text(status["uses_stacks"])
        expected[prefix + ".uses_duration"] = gen_card_specs.bool_text(status["uses_duration"])
        expected[prefix + ".uses_charges"] = gen_card_specs.bool_text(status["uses_charges"])
        expected[prefix + ".passive_modifiers"] = str(len(status["passive_modifiers"]))
        for position, modifier in enumerate(status["passive_modifiers"]):
            expected["%s.modifier.%d" % (prefix, position)] = "%s:%s:%d:%d:%s" % (
                modifier["pipeline"], modifier["operation"], modifier["magnitude"],
                modifier["priority"], modifier["restrictDamageKind"])
        expected[prefix + ".incoming_delay"] = "none"
        expected[prefix + ".disclosure"] = "none"
        for position, trigger in enumerate(status["triggers"]):
            trigger_prefix = "%s.trigger.%d" % (prefix, position)
            expected[trigger_prefix + ".event"] = trigger["event"]
            # 触发器程序只比**根节点**的文本：C# 注册时会把程序 id 换成 `trigger:<id>`，
            # 而镜像里是 `(unnamed)` —— 拿整段 program(...) 去比，比到的是一个作者侧的细节。
            expected[trigger_prefix + ".program"] = gen_card_specs.node_text(trigger["program"]["root"])
            trigger_count += 1
    expected["content.triggered_programs"] = str(trigger_count)

    # 敌人动作：与整局那层同一个 id、同一段程序（它只是为了让敌人有动作，不是这一层的主角）。
    expected.update(mirror_enemy_action_facts(mirror, CARD_ACTION))
    return expected


def card_layer_shape(card_id: str) -> dict:
    """逐卡战斗的**形状事实**：C# 侧报告什么，本脚本就期望什么。"""
    return {
        "shape.combat": CARD_SHAPE["combat"],
        "shape.seed": CARD_SHAPE["seed"],
        "shape.shuffle": CARD_SHAPE["shuffle"],
        "shape.hero": CARD_SHAPE["hero"],
        "shape.enemies": CARD_SHAPE["enemies"],
        "shape.deck": card_id + ":1",
        "shape.energy": CARD_SHAPE["energy"],
        "shape.energy_refill": CARD_SHAPE["energy_refill"],
        "shape.steps": CARD_SHAPE["steps"],
        "shape.step.0": "play:" + card_id + ":" + CARD_ENEMY,
    }


def compare_facts(facts: dict, expected: dict, label: str, limit: int = 8) -> list:
    """逐键比对事实表。多一条、少一条、值不同 —— 三种都算不一致。

    "C# 侧声明了闸门不知道怎么核对的事实"单独成一条：那说明 authoring 又往前走了一步而闸门没跟上，
    比不一致更值得处理（它是未来静默偏差的入口）。
    """
    problems = []
    for key in sorted(expected):
        want = expected[key]
        if key not in facts:
            problems.append(f"{label}: `{key}` 镜像说 {want!r}，C# 侧没有这条事实")
        elif facts[key] != want:
            problems.append(f"{label}: `{key}` C# 侧 {facts[key]!r} != 镜像 {want!r}")
        if len(problems) >= limit:
            problems.append(f"{label}: ……（还有更多，先修上面这些）")
            return problems
    for key in sorted(facts):
        if key not in expected:
            problems.append(f"{label}: `{key}` 是 C# 侧声明、闸门不知道怎么核对的事实"
                            f"（值 {facts[key]!r}；先教会闸门，再让它通过）")
            if len(problems) >= limit:
                return problems
    return problems


def spec_drift(on_disk: dict, fresh: dict, limit: int = 8) -> list:
    """两份卡描述之间**具体差在哪**（路径 + 两边的值）。

    陈旧闸门如果只说"文件过时了"，读的人还得自己去比 64 KB 的 json。这里直接指到
    `cards[4] (strong_binder).costs[0].amount` 这一级 —— 变异测试就是靠它说出"是哪张卡"。
    """
    problems = []

    def label(path: str, root) -> str:
        """给路径加个名字：卡/状态的下标看不出是哪一张。"""
        for kind in ("cards", "statuses"):
            marker = kind + "["
            if marker in path:
                head, _, tail = path.partition(marker)
                index_text, _, rest = tail.partition("]")
                name = "?"
                try:
                    name = root[kind][int(index_text)]["id"]
                except (ValueError, IndexError, KeyError, TypeError):
                    pass
                return f"{head}{kind}[{index_text}] ({name}){rest}"
        return path

    def walk(left, right, path, where):
        if len(problems) >= limit:
            return
        if type(left) is not type(right):
            problems.append(f"{label(path, where)}: 磁盘 {left!r} != 镜像 {right!r}")
            return
        if isinstance(left, dict):
            for key in sorted(set(left) | set(right)):
                if key not in left:
                    problems.append(f"{label(path + '.' + key, where)}: 磁盘缺这条，镜像说 {right[key]!r}")
                elif key not in right:
                    problems.append(f"{label(path + '.' + key, where)}: 磁盘多这条（{left[key]!r}）")
                else:
                    walk(left[key], right[key], path + "." + key, where)
            return
        if isinstance(left, list):
            if len(left) != len(right):
                problems.append(f"{label(path, where)}: 长度 磁盘 {len(left)} != 镜像 {len(right)}")
                return
            for index, (a, b) in enumerate(zip(left, right)):
                walk(a, b, f"{path}[{index}]", where)
            return
        if left != right:
            problems.append(f"{label(path, where)}: 磁盘 {left!r} != 镜像 {right!r}")

    walk(on_disk, fresh, "spec", fresh if isinstance(fresh, dict) else {})
    return problems


def card_layer(oracle: Oracle, mirror: Mirror, verbose: bool) -> tuple:
    """逐卡对拍。返回 (通过张数, 总张数, [失败明细])。

    闸门（形状/内容/顺序）失败是**抛 GateFailure**：它意味着"两边打的不是同一张卡"，
    继续跑下去只会产出 62 个没有意义的哈希比较。逐张卡自己的失败（author 不出来、哈希不同）
    才记成一行 FAIL —— 那种时候**别的卡仍然可信**，而这正是"n/62"要表达的东西。
    """
    spec = load_spec(oracle, mirror)
    count = oracle.card_count()
    if count != len(spec["cards"]):
        raise GateFailure(f"oracle 说 spec 里有 {count} 张卡，镜像派生出来的是 {len(spec['cards'])} 张")

    expected = card_layer_expected(spec, mirror)
    for key, want in CARD_CONTENT_PINS:
        expected[key] = want
    if verbose:
        for key in sorted(expected):
            print(f"  gate-card {key} = {expected[key]}")

    # ── 内核这一侧：一次进程把 62 张卡全打出来
    info, blocks = parse_rust(run_rust_dump(["--cards"]), block_key="card")
    if info.get("cards") != str(len(spec["cards"])):
        raise GateFailure(f"rd-fightdump 说镜像里有 {info.get('cards')} 张卡，spec 里是 "
                          f"{len(spec['cards'])} 张 —— 两边读的不是同一份镜像")
    if len(blocks) != len(spec["cards"]):
        raise GateFailure(
            f"rd-fightdump 打了 {len(blocks)} 张卡，镜像里有 {len(spec['cards'])} 张 —— "
            f"少打就是跳过，这个脚本不接受")

    print()
    print(f"# 逐卡（CARD_DIFF）：{len(blocks)} 张卡，每张一局固定形状的短战斗"
          f"（combat={CARD_SHAPE['combat']} seed={CARD_SHAPE['seed']} "
          f"hero={CARD_SHAPE['hero']} enemies={CARD_SHAPE['enemies']} "
          f"energy={CARD_SHAPE['energy']}）")

    # ── 闸门 2：**内容**。62 张卡 author 的是同一份内容（全部 62 张卡 + 2 个状态 + 敌人动作），
    # 所以内容不对时"两边打的是同一张卡"这个前提已经不成立 —— 那是闸门失败，不是 62 条一样的
    # 卡片失败。跑一次就够：内容事实与选哪张卡无关。
    content_seed = int(blocks[0]["header"]["seed"])
    code = oracle.card_run(0, content_seed)
    if code <= 0:
        raise GateFailure(f"C# 侧连第 0 张卡都 author 不出来：{oracle.error()}")
    content_facts = {key: value for key, value in oracle.card_facts().items()
                     if not key.startswith(("selected.", "shape."))}
    problems = compare_facts(content_facts, expected, "内容闸门")
    if problems:
        raise GateFailure(
            f"C# 侧 author 的**内容**与镜像不一致（{len(problems)} 处以上）：\n  "
            + "\n  ".join(problems)
            + "\n  逐卡对拍的前提是两边打同一张卡、同一段程序；先修好 authoring，再谈哈希。")
    if verbose:
        print(f"  内容闸门 ok：{len(expected)} 条事实（{len(spec['cards'])} 卡 / "
              f"{len(spec['statuses'])} 状态 / 1 敌人动作）")

    passed = 0
    failures = []
    checked = len(expected)
    for index, block in enumerate(blocks):
        want_card = spec["cards"][index]
        header = block["header"]
        rust_card = header.get("card")
        if rust_card != want_card["id"]:
            raise GateFailure(
                f"第 {index} 张卡对不上：rd-fightdump 打的是 `{rust_card}`，"
                f"镜像的 CARD[{index}] 是 `{want_card['id']}` —— 两边的卡序不同，逐卡比较就没有意义")
        if header.get("index") != str(index):
            raise GateFailure(
                f"`{rust_card}` 的头行 index={header.get('index')}，但它在输出里是第 {index} 个 —— "
                f"顺序与索引不同，逐卡比较就没有意义")

        shape = card_layer_shape(want_card["id"])
        shape["selected.index"] = str(index)
        shape["selected.id"] = want_card["id"]
        seed = int(header["seed"])
        code = oracle.card_run(index, seed)
        if code <= 0:
            failures.append((want_card["id"], f"C# 侧 author 不出来：{oracle.error()}"))
            print(f"card={want_card['id']:<24} index={index:<2} {'':>28} FAIL  "
                  f"C# author 失败（{oracle.error()}）")
            continue

        facts = oracle.card_facts()
        # 每张卡只比**自己的**那几条（内容那 800 多条刚在闸门 2 比过）。
        # 但"键的集合"仍然整份比：C# 多报一条闸门不认识的事实必须被发现，
        # 而只看 shape.* 就会把它当成合法的形状事实漏过去。
        problems = []
        missing = (set(expected) | set(shape)) - set(facts)
        extra = set(facts) - (set(expected) | set(shape))
        if missing:
            problems.append(f"facts: C# 侧少了 {sorted(missing)[:4]}")
        if extra:
            problems.append(f"facts: C# 侧多报了闸门不知道怎么核对的事实 {sorted(extra)[:4]}")
        problems += compare_facts({key: facts[key] for key in shape if key in facts}, shape, "facts")

        # 头行：两边必须是同一局（同一个 combat id / seed / 血量 / 牌组 / 能量）
        for key in ("combat", "seed", "shuffle", "hero", "enemies", "deck", "energy"):
            want = shape.get("shape." + key)
            got = header.get(key)
            if got != want:
                problems.append(f"header: `{key}` rust={got!r} != 约定 {want!r}")

        side = oracle.observables()
        steps = oracle.card_steps()
        rust_steps = block["steps"]
        final = block["final"] or {}

        if len(rust_steps) != len(steps):
            problems.append(f"dump_steps: rust={len(rust_steps)} csharp={len(steps)}")
        for position, rust_step in enumerate(rust_steps):
            if position >= len(steps):
                problems.append(f"step{position}: rust 有、csharp 没有")
                continue
            step = steps[position]
            for key in STEP_OBSERVABLES:
                if rust_step.get(key) != step.get(key):
                    problems.append(f"step{position}.{key}: rust={rust_step.get(key)} "
                                    f"csharp={step.get(key)}")
            if rust_step.get("hash") != step.get("hash"):
                problems.append(f"step{position}.hash: rust={rust_step.get('hash')} "
                                f"csharp={step.get('hash')}")
        for key in FINAL_OBSERVABLES:
            if key == "enemy_hp":
                rust_value = rust_steps[-1].get("enemy_hp") if rust_steps else None
            else:
                rust_value = final.get(key)
            if str(rust_value) != str(side.get(key)):
                problems.append(f"final.{key}: rust={rust_value} csharp={side.get(key)}")
        rust_final_hash = rust_steps[-1].get("hash") if rust_steps else None
        if rust_final_hash != side.get("hash"):
            problems.append(f"final_hash: rust={rust_final_hash} csharp={side.get('hash')}")

        if problems:
            failures.append((want_card["id"], problems[0]))
            print(f"card={want_card['id']:<24} index={index:<2} steps={len(rust_steps)} "
                  f"facts={checked + len(shape):<4} MISMATCH")
            for problem in problems[:8]:
                print(f"    - {problem}")
        else:
            passed += 1
            print(f"card={want_card['id']:<24} index={index:<2} steps={len(rust_steps)} "
                  f"facts={checked + len(shape):<4} hash={str(rust_final_hash)[:12]}.. OK")

    return passed, len(blocks), failures

def load_spec(oracle: Oracle, mirror: Mirror) -> dict:
    """三道前置闸门里与"这份 spec 是不是镜像现在的样子"有关的那两道。

    返回从镜像派生出来的 spec（C# 侧读到的必须是它的**同一份字节**）。抽出来是因为三层都要它：
    多层与敌人层不能各自再写一遍"陈旧就报错"—— 那两份会漂。
    """
    spec = gen_card_specs.derive(mirror.rom)
    rendered = gen_card_specs.render(spec)

    # ── 闸门 0：磁盘上的 spec 不能陈旧。它是 C# 侧的输入，而它的真相是镜像。
    if not os.path.isfile(SPEC_JSON):
        raise GateFailure(f"{SPEC_JSON} 不存在 —— 它由镜像派生，生成命令：\n"
                          f"    python native/gen_card_specs.py")
    with open(SPEC_JSON, "r", encoding="utf-8", newline="") as handle:
        on_disk = handle.read()
    if on_disk != rendered:
        try:
            drift = spec_drift(json.loads(on_disk), spec)
        except ValueError as broken:
            drift = [f"磁盘上的 json 根本解析不了：{broken}"]
        raise GateFailure(
            f"{SPEC_JSON} 与镜像不一致（陈旧产物，{len(on_disk)} B vs {len(rendered)} B）。\n"
            + "".join(f"  {line}\n" for line in drift)
            + "  镜像变了就要重生成：\n    python native/gen_card_specs.py")

    # ── 闸门 1：oracle 读进来的必须就是这份字节（不是它旁边某个同名旧文件）
    code = oracle.load_card_specs(SPEC_JSON)
    if code <= 0:
        raise RuntimeError(f"rd_oracle_card_specs_load({SPEC_JSON}) -> {code}；{oracle.error()}")
    loaded = oracle.card_specs_text()
    if loaded != on_disk:
        raise GateFailure(
            f"oracle 读进来的 spec 与磁盘上的不是同一份字节（{len(loaded)} B vs {len(on_disk)} B）")
    return spec


def status_expected(status: dict) -> dict:
    """一个状态 → C# 侧该报出来的每一条事实（拼写与 `OracleExports.Fight.cs` 的 `StatusFacts` 逐字相同）。"""
    prefix = "status." + status["id"]
    out = {
        prefix + ".package": status["package"],
        prefix + ".polarity": status["polarity"],
        prefix + ".stacking": status["stacking"],
        prefix + ".tags": ",".join(status["tags"]),
        prefix + ".uses_stacks": gen_card_specs.bool_text(status["uses_stacks"]),
        prefix + ".uses_duration": gen_card_specs.bool_text(status["uses_duration"]),
        prefix + ".uses_charges": gen_card_specs.bool_text(status["uses_charges"]),
        prefix + ".passive_modifiers": str(len(status["passive_modifiers"])),
        prefix + ".incoming_delay": "none",
        prefix + ".disclosure": "none",
    }
    for index, modifier in enumerate(status["passive_modifiers"]):
        out["%s.modifier.%d" % (prefix, index)] = "%s:%s:%d:%d:%s" % (
            modifier["pipeline"], modifier["operation"], modifier["magnitude"], modifier["priority"],
            "none" if modifier["restrictDamageKind"] is None else modifier["restrictDamageKind"])
    for index, trigger in enumerate(status["triggers"]):
        out["%s.trigger.%d.event" % (prefix, index)] = trigger["event"]
        out["%s.trigger.%d.program" % (prefix, index)] = gen_card_specs.node_text(trigger["program"]["root"])
    return out


def compare_steps(problems: list, rust_steps: list, csharp_steps: list, final: dict, side: dict) -> None:
    """每步的 (round, turn, problems, 血量, 哈希) + 终局观测量 + 终局哈希。三层共用一份。

    `chain` / `exec` 只在**两侧都打**的时候比（逐卡那层的 C# 侧不打它们）：它们在哈希文本里，
    但"哪一步的哪一格开始偏"这件事，只有逐个步边界打出来才看得见 —— 光比哈希只能说"这步之后不同"。
    """
    if len(rust_steps) != len(csharp_steps):
        problems.append(f"dump_steps: rust={len(rust_steps)} csharp={len(csharp_steps)}")
    for position, rust_step in enumerate(rust_steps):
        if position >= len(csharp_steps):
            problems.append(f"step{position}: rust 有、csharp 没有")
            continue
        step = csharp_steps[position]
        for key in STEP_OBSERVABLES:
            if rust_step.get(key) != step.get(key):
                problems.append(f"step{position}.{key}: rust={rust_step.get(key)} "
                                f"csharp={step.get(key)}")
        for key in ("chain", "exec"):
            if key in step and key in rust_step and rust_step[key] != step[key]:
                problems.append(f"step{position}.{key}: rust={rust_step[key]} csharp={step[key]}")
        if rust_step.get("hash") != step.get("hash"):
            problems.append(f"step{position}.hash: rust={rust_step.get('hash')} "
                            f"csharp={step.get('hash')}")
    for key in FINAL_OBSERVABLES:
        if key == "enemy_hp":
            rust_value = rust_steps[-1].get("enemy_hp") if rust_steps else None
        else:
            rust_value = final.get(key)
        if str(rust_value) != str(side.get(key)):
            problems.append(f"final.{key}: rust={rust_value} csharp={side.get(key)}")
    rust_final_hash = rust_steps[-1].get("hash") if rust_steps else None
    if rust_final_hash != side.get("hash"):
        problems.append(f"final_hash: rust={rust_final_hash} csharp={side.get('hash')}")


# ===========================================================================
# 逐卡多层（CARD_MULTI）
#
# `CARD_DIFF` 每张卡只打一步，所以它照不到跨回合的那一半：结束时弃手牌、下回合抽回来、
# 抽牌堆空时重洗（`random_step` 前进一格）、回合开始的补能、DoT 在回合开始的 tick、
# `TurnEndHandDestinationZone` / `RetainInHandOnTurnEnd`、以及敌人真的出手。
# 这一层每张卡跑两个变体、每个变体 4 步，两条路都跨过至少一个回合边界。
# ===========================================================================

# 与 `kernel/rd-fightdump` 的 `CARD_MULTI_*`、`OracleExports.Layers.cs` 的 `CardMulti*` 是三份常量。
MULTI_SHAPE = {
    "combat": "card_multi",
    "seed": "1",
    "shuffle": "false",
    "hero": "hero/70",
    "enemies": "queue_imp/500",
    "energy": "standard.energy:3/3",
    "energy_refill": "3",
}
MULTI_ENEMY = "queue_imp"
MULTI_ACTION = "queue_imp.desk_jab"

# 内核**没有钩子接**的触发器事件（`kernel/rd-core/src/host.rs:2299-2302`：25 条触发器里
# 12 条属于 6 种这类事件，同文件的测试把它钉成 `assert_eq!(not_handled, 12)`；`DamageDealt` 就在里面）。
# 内容里凡是有这类触发器的状态，只要**那一局真的让事件发生**，两侧就必然不同 —— 这不是对拍能回答
# 的问题，也不是 oracle author 错了。这种情况必须**逐行打印原因**并计入分母，不许算成"绿"。
KERNEL_UNMODELLED_TRIGGER_EVENTS = (
    "DamageTaken", "DamageDealt", "StatusApplied", "StatusMerged", "StatusStacksChanged", "StatusRemoved",
)


def applied_to_event_target(node, into: list) -> list:
    """程序树里 `applyStatus` 到 `sel.eventTarget` 的状态 id（= 打到**敌人**身上的那些）。"""
    if isinstance(node, dict):
        if node.get("kind") == "applyStatus" and (node.get("target") or {}).get("kind") == "eventTarget":
            into.append(node["status"])
        for key in sorted(node):
            applied_to_event_target(node[key], into)
    elif isinstance(node, list):
        for item in node:
            applied_to_event_target(item, into)
    return into


def kernel_gap_for(card: dict, variant_steps: list, spec: dict) -> list:
    """这一局里"内核缺钩子"能不能被触发 → 触发了就返回原因列表（空 = 这一局能照）。

    两个条件都要成立，缺一不可：
    1. 卡的程序把**带未建模触发器**的状态打到 `sel.eventTarget`（= 敌人）身上；
    2. 这一局的脚本里**有敌人出手**（那个动作会打出伤害 ⇒ `DamageDealt` 真的会发生）。
    只把"卡打了 doubt"当理由是不够的 —— 变体 A 里敌人根本不出手，那时两侧必须一致。
    """
    if not any(step.startswith("enemy_acts:") for step in variant_steps):
        return []
    statuses = {status["id"]: status for status in spec["statuses"]}
    reasons = []
    for status_id in applied_to_event_target(card["program"]["root"], []):
        for trigger in statuses.get(status_id, {}).get("triggers", []):
            if trigger["event"] in KERNEL_UNMODELLED_TRIGGER_EVENTS:
                reasons.append("%s 的 %s 触发器（内核 host.rs 的 not_handled 里有这一种）"
                               % (status_id, trigger["event"]))
    return reasons
# (变体号, 名字, 牌组张数, 4 步脚本)。步的拼写与 C# 的 `StepTextOf` 一致。
MULTI_VARIANTS = (
    (0, "play_again", 2, ["play:{card}:" + MULTI_ENEMY, "end_turn", "next_round",
                          "play:{card}:" + MULTI_ENEMY]),
    (1, "enemy_then_wrap", 1, ["play:{card}:" + MULTI_ENEMY, "end_turn",
                               "enemy_acts:%s:%s:hero" % (MULTI_ENEMY, MULTI_ACTION), "next_round"]),
)


def multi_layer_shape(card_id: str, variant: int, deck_count: int, steps: list) -> dict:
    """多层这一层的形状事实（C# 侧报告什么，本脚本就期望什么）。

    ⚠️ 这一层**不**重比内容事实：C# 侧的多层用的就是逐卡那层同一个 `AuthorBlueprint`（62 卡 + 卡程序
    引用到的状态 + `desk_jab`），内容闸门已经在 `CARD_DIFF` 里逐键跑过了。这里多一份内容期望表只会
    变成"第二份真相"。这一层比的是**形状 + 每步哈希**：形状不对（牌组张数、能量、脚本）就是两边不是
    同一局，那种绿是无意义的绿。
    """
    shape = {
        "shape.combat": MULTI_SHAPE["combat"],
        "shape.seed": MULTI_SHAPE["seed"],
        "shape.shuffle": MULTI_SHAPE["shuffle"],
        "shape.hero": MULTI_SHAPE["hero"],
        "shape.enemies": MULTI_SHAPE["enemies"],
        "shape.deck": card_id + ":" + str(deck_count),
        "shape.energy": MULTI_SHAPE["energy"],
        "shape.energy_refill": MULTI_SHAPE["energy_refill"],
        "shape.variant": str(variant),
        "shape.steps": str(len(steps)),
    }
    for index, step in enumerate(steps):
        shape["shape.step." + str(index)] = step.format(card=card_id)
    return shape


def card_multi_layer(oracle: Oracle, mirror: Mirror, spec: dict) -> tuple:
    """逐卡 × 多层对拍。返回 (通过, 总数, [失败明细])。"""
    info, blocks = parse_rust(run_rust_dump(["--cards-multi"]), block_key="cardmulti")
    if info.get("cards") != str(len(spec["cards"])):
        raise GateFailure(f"rd-fightdump 说镜像里有 {info.get('cards')} 张卡，spec 里是 "
                          f"{len(spec['cards'])} 张 —— 两边读的不是同一份镜像")
    want_blocks = len(spec["cards"]) * len(MULTI_VARIANTS)
    if len(blocks) != want_blocks:
        raise GateFailure(
            f"rd-fightdump 打了 {len(blocks)} 个多层块，而 {len(spec['cards'])} 张卡 × "
            f"{len(MULTI_VARIANTS)} 个变体 = {want_blocks} —— 少打就是跳过，这个脚本不接受")

    print()
    print(f"# 逐卡多层（CARD_MULTI）：{len(spec['cards'])} 张卡 × {len(MULTI_VARIANTS)} 个变体，"
          f"每变体 4 步（跨回合：弃手牌 / 抽回来 / 重洗 / 补能{' / 敌人出手' if len(MULTI_VARIANTS) > 1 else ''}）")

    passed = 0
    failures = []
    not_comparable = []
    for position, block in enumerate(blocks):
        card = spec["cards"][position // len(MULTI_VARIANTS)]
        variant, name, deck_count, steps = MULTI_VARIANTS[position % len(MULTI_VARIANTS)]
        header = block["header"]
        if header.get("cardmulti") != card["id"]:
            raise GateFailure(f"第 {position} 个多层块打的是 `{header.get('cardmulti')}`，"
                              f"按顺序该是 `{card['id']}`（{name}）—— 两边的卡序不同")
        if header.get("index") != str(card["index"]):
            raise GateFailure(f"`{card['id']}` 的多层块 index={header.get('index')}，该是 {card['index']}")
        if header.get("variant") != str(variant):
            raise GateFailure(f"`{card['id']}` 的多层块 variant={header.get('variant')}，该是 {variant}")

        shape = multi_layer_shape(card["id"], variant, deck_count, steps)
        seed = int(header["seed"])
        code = oracle.card_multi_run(card["index"], variant)
        if code <= 0:
            failures.append((f"{card['id']}/{name}", f"C# 侧 author 不出来：{oracle.error()}"))
            print(f"card={card['id']:<24} index={card['index']:<2} variant={name:<16} "
                  f"FAIL  C# author 失败（{oracle.error()}）")
            continue

        facts = oracle.card_multi_facts()
        expected = dict(shape)
        expected["selected.index"] = str(card["index"])
        expected["selected.id"] = card["id"]
        problems = compare_facts(facts, expected, "facts")

        for key in ("combat", "seed", "shuffle", "hero", "enemies", "deck", "energy"):
            want = shape.get("shape." + key)
            got = header.get(key)
            if got != want:
                problems.append(f"header: `{key}` rust={got!r} != 约定 {want!r}")
        if header.get("variant") != shape["shape.variant"]:
            problems.append(f"header: `variant` rust={header.get('variant')!r} != 约定 {shape['shape.variant']!r}")

        side = oracle.observables()
        compare_steps(problems, block["steps"], oracle.card_multi_steps(), block["final"] or {}, side)
        if len(block["steps"]) != len(steps):
            problems.append(f"steps: rust 打了 {len(block['steps'])} 步，约定 {len(steps)} 步")

        if problems:
            gap = kernel_gap_for(card, steps, spec) if problems else []
            if gap:
                not_comparable.append((f"{card['id']}/{name}", "; ".join(gap)))
                print(f"card={card['id']:<24} index={card['index']:<2} variant={name:<16} "
                      f"steps={len(block['steps'])} NOT-COMPARABLE  内核缺钩子："
                      + "; ".join(gap))
                # ⚠️ 这条分类只说"**有**一个已知原因可以让两侧不同"，不等于"差异**只**由它造成"。
                # 所以首个差异仍然打出来（人要看一眼），别把它当成"这格不用管"。
                for problem in problems[:3]:
                    print(f"    - 差异：{problem}")
            else:
                failures.append((f"{card['id']}/{name}", problems[0]))
                print(f"card={card['id']:<24} index={card['index']:<2} variant={name:<16} "
                      f"steps={len(block['steps'])} MISMATCH")
                for problem in problems[:8]:
                    print(f"    - {problem}")
        else:
            passed += 1
            last_hash = block["steps"][-1].get("hash") if block["steps"] else None
            print(f"card={card['id']:<24} index={card['index']:<2} variant={name:<16} "
                  f"steps={len(block['steps'])} hash={str(last_hash)[:12]}.. OK")
    return passed, len(blocks), failures, not_comparable


# ===========================================================================
# 逐敌人动作（ENEMY_DIFF）
#
# 镜像里 394 条 `EACT`，在这一层之前**一条都没被执行过**（`FIGHT_DIFF` 那四局只用 `desk_jab`）。
# 每条一局：它所属的敌人 + 英雄（牌组为空）、脚本两步（结束英雄回合、让它执行这条动作）。
# 一条都**不许跳过**：C# 侧 author 不出来（本 build 不支持那个节点/表达式/选择器）也算在分母里，
# 并打印一行带原因的 `NOT-AUTHORED`。
# ===========================================================================

ENEMY_SHAPE = {
    "combat": "enemy_diff",
    "seed": "1",
    "shuffle": "false",
    "hero": "hero/70",
    "energy": "standard.energy:3/3",
    "energy_refill": "3",
}
ENEMY_HERO = "hero"
ENEMY_HP = 60
ENEMY_CONTENT_PINS = (
    ("content.allies", "0"),
    ("content.pre_down_interceptors", "0"),
    ("content.status_application_interceptors", "0"),
    ("content.defensive_pools", "0"),
    ("content.turn_start_refills", "0"),
    ("content.cards_drawn_per_turn", "5"),
    ("content.cell_exclusive", "false"),
    ("content.simultaneous_team_turns", "false"),
)


def spec_program_text(program: dict) -> str:
    """canonical 程序文本（`gen_card_specs.node_text` 那一套，与 C# 的泛型 `NodeTextOf` 逐字节相同）。

    ⚠️ 不要用本文件上面那几个手写的 `program_text` / `node_text`：它们是给**整局那四局**的两个手抄卡
    准备的，只认得 3 种节点（多一种就打成 `unsupported(...)`）。敌人动作里出现了 5 种节点、7 种表达式，
    拿那套去比会得到"两边都是 unsupported 但字面不同"的假红（或者更糟：两个 unsupported 恰好相同 ⇒ 假绿）。
    """
    return ("program(id=" + program["id"]
            + ";depth=" + str(program["depth"])
            + ";steps=" + str(program["steps"])
            + ";root=" + gen_card_specs.node_text(program["root"]) + ")")


def enemy_layer_expected(action: dict, spec: dict, mirror: Mirror) -> dict:
    """一条敌人动作 → C# 侧该报出来的每一条事实。状态与形状都从 spec（= 镜像）派生。"""
    statuses = {status["id"]: status for status in spec["statuses"]}
    trigger_count = 0
    expected = {
        "selected.index": str(action["index"]),
        "selected.id": action["id"],
        "selected.enemy": action["enemy"],
        "selected.listed": gen_card_specs.bool_text(action["listed"]),
        "enemy_action." + action["id"] + ".package": action["package"],
        "enemy_action." + action["id"] + ".intent": action["intent"],
        "enemy_action." + action["id"] + ".program": spec_program_text(action["program"]),
    }
    for status_id in action["statuses"]:
        if status_id not in statuses:
            raise GateFailure(f"动作 `{action['id']}` 需要状态 `{status_id}`，但 spec 里没有它")
        expected.update(status_expected(statuses[status_id]))
        trigger_count += len(statuses[status_id]["triggers"])
    for key, value in ENEMY_CONTENT_PINS:
        expected[key] = value
    expected["content.triggered_programs"] = str(trigger_count)
    expected.update({
        "shape.combat": ENEMY_SHAPE["combat"],
        "shape.seed": ENEMY_SHAPE["seed"],
        "shape.shuffle": ENEMY_SHAPE["shuffle"],
        "shape.hero": ENEMY_SHAPE["hero"],
        "shape.enemies": "%s/%d" % (action["enemy"], ENEMY_HP),
        "shape.deck": "",           # 空牌组：这一层问的是动作本身
        "shape.energy": ENEMY_SHAPE["energy"],
        "shape.energy_refill": ENEMY_SHAPE["energy_refill"],
        "shape.steps": "2",
        "shape.step.0": "end_turn",
        "shape.step.1": "enemy_acts:%s:%s:%s" % (action["enemy"], action["id"], ENEMY_HERO),
    })
    return expected


def enemy_layer(oracle: Oracle, mirror: Mirror, spec: dict) -> tuple:
    """逐敌人动作对拍。返回 (通过, 总数, [MISMATCH], [不可对照])。"""
    actions = spec["enemy_actions"]
    info, blocks = parse_rust(run_rust_dump(["--enemies"]), block_key="enemy")
    if len(blocks) != len(actions):
        raise GateFailure(
            f"rd-fightdump 打了 {len(blocks)} 条敌人动作，镜像里有 {len(actions)} 条 —— "
            f"少打就是跳过，这个脚本不接受")
    if info.get("enemy_actions") != str(len(actions)):
        raise GateFailure(f"rd-fightdump 说镜像里有 {info.get('enemy_actions')} 条敌人动作，"
                          f"spec 里是 {len(actions)} 条 —— 两边读的不是同一份镜像")

    count = oracle.enemy_action_count()
    if count != len(actions):
        raise GateFailure(f"oracle 说 spec 里有 {count} 条敌人动作，镜像派生出来的是 {len(actions)} 条")

    print()
    print(f"# 逐敌人动作（ENEMY_DIFF）：{len(actions)} 条 EACT 各一局（该动作所属敌人 + 英雄，牌组为空）")

    passed = 0
    failures = []
    unavailable = []
    for position, block in enumerate(blocks):
        action = actions[position]
        header = block["header"]
        if header.get("enemy") != action["id"]:
            raise GateFailure(f"第 {position} 条敌人动作打的是 `{header.get('enemy')}`，"
                              f"按顺序该是 `{action['id']}` —— 两边的动作序不同")
        if header.get("index") != str(action["index"]):
            raise GateFailure(f"`{action['id']}` 的头行 index={header.get('index')}，该是 {action['index']}")
        seed = int(header["seed"])
        code = oracle.enemy_run(action["index"], seed)
        if code <= 0:
            reason = oracle.error()
            unavailable.append((action["id"], reason))
            print(f"enemy={action['id']:<56} index={action['index']:<3} NOT-AUTHORED  {reason}")
            continue

        expected = enemy_layer_expected(action, spec, mirror)
        problems = compare_facts(oracle.enemy_facts(), expected, "facts")
        for key in ("combat", "seed", "shuffle", "hero", "enemies", "deck", "energy"):
            want = expected.get("shape." + key)
            got = header.get(key)
            if got != want:
                problems.append(f"header: `{key}` rust={got!r} != 约定 {want!r}")

        side = oracle.observables()
        compare_steps(problems, block["steps"], oracle.enemy_steps(), block["final"] or {}, side)

        if problems:
            failures.append((action["id"], problems[0]))
            print(f"enemy={action['id']:<56} index={action['index']:<3} MISMATCH")
            for problem in problems[:8]:
                print(f"    - {problem}")
        else:
            passed += 1
            last_hash = block["steps"][-1].get("hash") if block["steps"] else None
            print(f"enemy={action['id']:<56} index={action['index']:<3} "
                  f"steps={len(block['steps'])} hash={str(last_hash)[:12]}.. OK")
    return passed, len(actions), failures, unavailable


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
    fight_ok = table.bad == 0
    if fight_ok:
        print(f"FIGHT_DIFF PASS ({table.total}/{table.total})")
    else:
        print(f"FIGHT_DIFF FAIL ({table.bad}/{table.total})")

    # ── 逐卡这一层（保留上面那层：它打的是整局流程，这一层打的是每一张卡自己的效果）──────────
    card_passed, card_total, card_failures = card_layer(oracle, mirror, verbose)
    # 后面两层要用同一份 spec（卡层已经把它读进来、也核对过字节了）。
    spec = load_spec(oracle, mirror)

    print()
    if card_passed == card_total:
        print(f"CARD_DIFF PASS ({card_passed}/{card_total})")
    else:
        print(f"CARD_DIFF FAIL ({card_total - card_passed}/{card_total})")
        for card_id, reason in card_failures:
            print(f"  - {card_id}: {reason}")

    # ── 第 1 层扩展：逐卡 × 跨回合 ─────────────────────────────────────────────────────────────
    multi_passed, multi_total, multi_failures, multi_gaps = card_multi_layer(oracle, mirror, spec)
    print()
    print(f"# CARD_MULTI 汇总：一致 {multi_passed}/{multi_total}，不可对照 {len(multi_gaps)}"
          f"（内核缺钩子，逐行原因见上，计入分母），MISMATCH {len(multi_failures)}")
    if multi_passed + len(multi_gaps) == multi_total and not multi_failures:
        print(f"CARD_MULTI PASS ({multi_passed}/{multi_total})")
    else:
        print(f"CARD_MULTI FAIL ({multi_total - multi_passed - len(multi_gaps)}/{multi_total})")
        for label, reason in multi_failures:
            print(f"  - {label}: {reason}")

    # ── 第 2 层：每一条敌人动作 ────────────────────────────────────────────────────────────────
    enemy_passed, enemy_total, enemy_failures, enemy_unavailable = enemy_layer(oracle, mirror, spec)
    print()
    if enemy_passed + len(enemy_unavailable) == enemy_total and not enemy_failures:
        print(f"ENEMY_DIFF PASS ({enemy_passed}/{enemy_total})"
              + (f"  不可对照 {len(enemy_unavailable)} 条（逐行原因见上，计入分母）"
                 if enemy_unavailable else ""))
    else:
        matched = enemy_passed
        print(f"ENEMY_DIFF FAIL ({enemy_total - matched - len(enemy_unavailable)}/{enemy_total})")
        for action_id, reason in enemy_failures:
            print(f"  - {action_id}: {reason}")

    multi_ok = multi_passed + len(multi_gaps) == multi_total and not multi_failures
    enemy_ok = enemy_passed + len(enemy_unavailable) == enemy_total and not enemy_failures

    # 四层结论再汇总一遍。**为什么要有这一段**：上面每个 PASS 行之间隔着 100~1000 行明细，
    # 一条 grep（`^# SUM `）拿全四个数比"翻日志找 PASS"稳 —— 而且汇总里的 PASS/FAIL 是
    # **同一批布尔**算出来的，不是第二份判据（"抄第二份"是这份项目腐烂的老路）。
    print()
    print("# ---- 四层汇总（`^# SUM ` 一条 grep 拿全；明细见上）----")
    print(f"# SUM FIGHT_DIFF  {'PASS' if fight_ok else 'FAIL'} ({table.total - table.bad}/{table.total})")
    print(f"# SUM CARD_DIFF   {'PASS' if card_passed == card_total else 'FAIL'} "
          f"({card_passed}/{card_total})")
    print(f"# SUM CARD_MULTI  {'PASS' if multi_ok else 'FAIL'} (一致 {multi_passed}/{multi_total}, "
          f"不可对照 {len(multi_gaps)}, MISMATCH {len(multi_failures)})")
    print(f"# SUM ENEMY_DIFF  {'PASS' if enemy_ok else 'FAIL'} ({enemy_passed}/{enemy_total}, "
          f"不可对照 {len(enemy_unavailable)})")

    return 0 if (fight_ok and card_passed == card_total
                 and multi_ok and enemy_ok) else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except GateFailure as failure:
        print()
        print("GATE FAIL")
        print(str(failure))
        print()
        # 闸门可能是在后面几层砸下来的（那时前面的层已经跑完了），但那一层都没拿到 PASS ——
        # 一行 PASS 都没打出来才是机器能可靠读到的东西。
        print("FIGHT_DIFF FAIL (gate)")
        print("CARD_DIFF FAIL (gate)")
        print("CARD_MULTI FAIL (gate)")
        print("ENEMY_DIFF FAIL (gate)")
        sys.exit(1)
    except ABIMissing as failure:
        print()
        print("ABI MISSING")
        print(str(failure))
        print()
        print("FIGHT_DIFF FAIL (abi)")
        print("CARD_DIFF FAIL (abi)")
        print("CARD_MULTI FAIL (abi)")
        print("ENEMY_DIFF FAIL (abi)")
        sys.exit(1)
    except RuntimeError as failure:
        print()
        print("ERROR")
        print(str(failure))
        print()
        print("FIGHT_DIFF FAIL (error)")
        print("CARD_DIFF FAIL (error)")
        print("CARD_MULTI FAIL (error)")
        print("ENEMY_DIFF FAIL (error)")
        sys.exit(1)
