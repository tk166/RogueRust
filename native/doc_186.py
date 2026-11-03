"""§186 docs pass: append dated "implementation supplement" sections to the frozen specs.

Each spec is a **design contract** written before the code; the honest way to keep them useful is to
append what was actually built (with `port-plan.md` section numbers) instead of rewriting the frozen
parts. Every insertion carries the date, so "the doc says X" and "the code does X since Y" stay
distinguishable.
"""
import io
import os

SPEC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "spec")
SPEC = os.path.normpath(SPEC)

DATE = "2026-11-03"


def append(name, text):
    path = os.path.join(SPEC, name)
    body = io.open(path, encoding="utf-8").read()
    assert text not in body, name + " already patched"
    io.open(path, "w", encoding="utf-8", newline="").write(body.rstrip("\n") + "\n" + text + "\n")
    print("appended:", name)


def insert_before(name, anchor, text):
    path = os.path.join(SPEC, name)
    body = io.open(path, encoding="utf-8").read()
    assert body.count(anchor) == 1, (name, body.count(anchor))
    assert text not in body, name + " already patched"
    io.open(path, "w", encoding="utf-8", newline="").write(body.replace(anchor, text + anchor))
    print("inserted:", name)


# ---------------------------------------------------------------- SEMANTICS-v1.md
SEMANTICS = '''### 2.3 实现期扩展（v1 契约之外，2026-11-03 补记）

v1 的范围（§2.1 IN）没有包含下面这些；它们是**内容逼出来的**机制，实现时按"最小、可拒绝、可指纹"
的原则加进来。**都不改 §2.1 的既有语义**：参考的三种 `CombatResult`、`hash_golden` 的规范文本、
队列与链的编号规则一个字都没动。

| 扩展 | 语义 | 为什么 v1 没有 | 出处 |
|---|---|---|---|
| `node.destroyCombatant` | 把一个战斗员**移出**战斗（名册 / 回合序 / 牌堆表三处一起移位）。被销毁者不再被 `collect_triggers` 收集。拒绝移除**当前行动者**（回合循环按 id 找它） | 参考没有这个词；StS 的"Boss 分裂"是"本体消失、两只顶替"，而"消失"无法用状态表达（状态写入是**入队请求**，同一批伤害里来不及落地） | §178 |
| `STAT.DeathPrevention`（PreDown 拦截） | 血量落到 0 之后、转 `Downed` **之前**拦截：生存血量 = `max(SurvivingHealth, maxHP × Percent / 100, 1)`；状态被消耗（`Repeating` 才留） | 参考有这个字段与拦截器，本内核一直只解析不执行 | §180 |
| `standard.card_cost_override` | 每副本**绝对价**，读在 `card_cost_delta` 之前，**不被出牌消费** | 参考的 delta 是"一次承诺、付款即清零"；"整场战斗随机费用"（Snecko Oil）在 delta 上表达不出来 | §179 |
| `standard.duplication` | 出牌节目跑**两遍**（只付一次费、只算一次出牌），跑完消耗一层 | 参考没有"打两次"的原语 | §181 |
| 运行层动词（不在内核） | `combat_upgrade_hand` / `combat_randomize_costs` / `combat_flee` / `combat_autoplay_top`；脱战是运行层 `result = 3`，不是第四种 `CombatResult` | 都是 StS 的药水语义，参考是引擎不是 StS | §179 / §182 |

**一条要记住的队列语义**（§177 的实测，比上面任何一行都重要）：

> 触发器程序里的每个效果都是**入队请求**。同一个伤害批次里，后续伤害的触发器在"移除"落地
> **之前**就被收进 batch ⇒ **"只触发一次"不能由内容表达**（自摘状态、计数器都不行）。
> 需要"一次性"的地方要么用 `node.destroyCombatant`（立即生效），要么在内核改排空顺序。

'''

# ---------------------------------------------------------------- play-card-flow.md
PLAY = '''## 11. 实现补充（2026-11-03）：两处出牌路径的新事实

### 11.1 §3 费用阶段多了一张"绝对价"

`CostStage::CardInstance` 现在先读 `standard.card_cost_override`（**绝对价**，不被出牌消费），
再读 `standard.card_cost_delta`（增量，**付款后清零**）。排序是语义：覆盖是对"这一份副本这一场
战斗的价格"的最终回答，delta 只是相对修饰。判据
`the_randomized_price_survives_the_play_but_the_delta_does_not` 钉住这个不对称（§179）。

⚠️ 显示侧（`rd-wasm` 的手牌代价列）是**第二份定价**：它也读同一个覆盖（`hand_costs`），
所以"显示 0 且真的收 0"这条浏览器判据才成立。

### 11.2 出牌节目的"跑两遍"

`apply_plan_in_chain` 在 `plan` 已经扣过费、`cards_played_this_turn` 已经加过之后，
按 `standard.duplication` 的层数决定 `exec::begin` 跑 1 遍还是 2 遍（跑之前**先花掉一层**，
否则第二遍的终态回调会再复制一次，就变成"打到死"）。

位置不是随手选的：那里是**唯一**同时满足"只付一次费、只算一次出牌"与"手里有 `Content` 借用"
的地方 —— 终态回调（`finish_frame` → `run_terminal_hook`）是纯数据驱动的，没有 content，
而 `NodeRef` 需要它（§181）。

**已知表示差异**：两遍的节目是**连续入队**的，所以第二遍读到的状态是第一遍的**效果落地之前**的
状态。对"固定伤害/格挡"的牌完全等价；对"读当前血量/状态层数"的牌会有可观察差异 ——
这一条写在这里，而不是假装等价。

'''

# ---------------------------------------------------------------- modifier-pipeline.md
MODIFIER = '''## 8. 实现补充（2026-11-03）：费用管线的两张"每副本"表

§3 讲的是**伤害**从卡面数字到扣血；费用侧有一条平行但更窄的管线，落地后有两个**每副本**
（per card instance）的 mark counter，语义刻意不同：

| 计数器 | 语义 | 生命周期 | 出处 |
|---|---|---|---|
| `standard.card_cost_delta` | 增量（"这张牌这次便宜 1"） | **出牌付款后清零**（参考 `CardPlay.cs:176-183`：一次承诺只兑现一次） | §161.4 |
| `standard.card_cost_override` | **绝对值**（"这张牌这一场战斗就是 0 费"） | **永不清零** | §179 |

读取顺序：override → delta → 其它阶段的结果。`mark_counter_opt`（不是 `mark_counter`）是必须的 ——
**"被随机成 0 费"与"没有覆盖"是两件事**，用 0 当"没有"会让那瓶药在第一次出牌后失效。

'''

# ---------------------------------------------------------------- run-layer.md
RUN = '''## 10. 实现补充（2026-11-03）：脱战与无色牌

### 10.1 脱战是**运行层**结局，不是第四种 `CombatResult`

Smoke Bomb（§179）落地时把"逃出非 Boss 战斗"表达成 `FightOutcome` 的 `result = 3`：
不跑 `end_of_combat`（遗物不触发）、不掷奖励、不给 Boss 记账，但节点**算用掉**（`mark_resolved`）。

为什么不动内核：`CombatState.result` 的三种值与参考**逐字节**一致，而且 `result=` 在
`hash_golden` 的规范文本里 —— 加第四种会动整个 85 份语料。Boss 战拒绝脱战（wiki: non-boss combat）。

### 10.2 无色牌不进任何牌组

滤网在 `full_pool`（**商人**与**奖励屏**都从它取样），不是在 `reward_pool`。这条位置是被数据逼出来的：
只滤奖励池时，三张无色牌会出现在**商店**，驱动器买了它们、牌组变弱、24 个种子里 11 个死得更早
（§185）。一个规则一个出处。

三张无色牌**没有 `+` 行**：不是"不能升级"（StS 里能），而是**没有任何牌组装得下它们**
（唯一入口是 Colorless Potion，在一次战斗内给），`+` 行会是没人能到达的内容。

'''

# ---------------------------------------------------------------- content-schema.md
SCHEMA = '''## 8. 实现补充（2026-11-03）：三个新节点/字段与两个方言陷阱

### 8.1 新增的节点与字段

| 名字 | 形状 | 说明 |
|---|---|---|
| `node.destroyCombatant` | `{TargetSelector}` | 把一个战斗员移出战斗（§178）。与 `node.createCombatant` 一样**立即生效**，不走效果队列 —— "立即"正是"只发生一次"唯一能表达的形式 |
| `STAT.DeathPrevention` | `{SurvivingHealth:int, Percent:int?, Repeating:bool?}` | PreDown 拦截（§180）。`Percent` 是**本移植的扩展**：参考的记录只有平值，表达不了 wiki 的 "30% of Max HP" |
| `sel.sourceIncludingDowned` | `{}` 或 `{Cardinality}` | 参考的 `SourceIncludingDownedCombatantTargetSelector`。`sel.source` 对**倒下的**战斗员解析为空集 ⇒ 挂在 `Downed` 上的分裂必须用这一个 |

### 8.2 ★★ 两个只在**内核**炸、内容门看不见的方言坑

1. **`node.applyStatus` 的 `DurationTurns` / `Charges` 是裸整数，不是 term。**
   写成 `{"kind":"const","value":{"Value":0}}` 时，只要**别的卡写的是裸整数**，编译器就会把该
   opcode 的这个字段**声明成 `F_JSON`**（"原始 JSON 逃生口"），而内核的 `NodeRef::field()`
   对 `F_JSON` **无条件**报错。症状极具误导性：**加一张卡，另一个不相关的测试红了**
   （`Ir(WrongKind("F_JSON"))`）。
2. **`sel.allEnemies` 的 `value` 是 `{}` 或 `{"Cardinality":"Any"}`。** 写 `"Many"` 是同一个症状。

⇒ 形状判据现在由第 11 道闸门（`tools/rdcf_terms.py`）在**镜像层面**检查（§184）：
除保留 opcode 5 自己，任何 opcode 的任何字段都不许声明成 `F_JSON`。

'''

# ---------------------------------------------------------------- content-binary-format.md
BINARY = '''## 6. 实现补充（2026-11-03）：term 表的**形状**也会被闸门读

§4 的校验原本只到"段字节数 == count × stride"。§183 的两个内容事故（`DurationTurns` 写成 term、
`sel.allEnemies` 的 `Cardinality` 写成对象）证明那层不够：**源 JSON 合法、编译成功、字节门全绿**，
而镜像里同一个字段在不同出现处形状不一致 ⇒ 编译器把整个字段降级成 `F_JSON` ⇒ 内核读到就报错。

现在第 11 道闸门（`tools/rdcf_verify.py` + `tools/rdcf_terms.py`）**独立解析** OPD/OPF/TRM/TRW/STR/STRO，
检查三条：

1. 除保留 opcode 5（`_json`）自己之外，任何 opcode 的任何字段都不许声明成 `F_JSON`；
2. 不允许存在 `_json` term（失败消息带那段 JSON 原文）；
3. `F_TERM` 槽指向的 term id 必须真实存在（段 id 位移那种"对的字节、错的 id"）。

负控在 `native/negctl_184.py`：**基线绿 → bug①红（且点名 opcode 与字段）→ bug②红 → 清理回绿**。
证据串因此多了一段：`... 1274 table rows, 6 term-shape checks over 5,038 terms`。

'''

# ---------------------------------------------------------------- env-abi.md
ABI = '''## 12. 诊断导出（2026-11-03 追加，v1 契约的**纯增量**）

§3 那套是"可玩"所需的；这一组是"卡住时能说清为什么"所需的。它们都不改观察向量的布局，
也不参与指纹。

| 导出 | 返回 | 用途 |
|---|---|---|
| `rd_env_step_code(index)` | 第 `index` 步的 `Deck`/`Play` 拒绝码（`0` = 没有，`-1` = 越界/无会话） | `StepThrew(Script)` 只说了家族；这个说**哪一条**拒因（`Refused(Unplayable)` / `Unaffordable` / `CardNotInHand` / …） |
| `rd_env_code_name_len(code)` / `rd_env_code_name_into(code, ptr)` | 码的**名字**（内核里只有一份表） | 页面把数字印成人话 |
| `rd_env_host_failure_len()` / `rd_env_host_failure_into(ptr)` | 宿主**上一次失败的原始文本**（`0` = 没有） | `TurnError::Host` 只带五个家族；细节一直在 `Host::last_failure()`，**在此之前没有任何导出读它**。实测它就写着 `Exec(Capacity(Full(Combatants)))` |

它们抓到过的第一个真凶：Boss 分裂在同一回合多次触发、战斗员容器溢出（§177 → §178）。
`?debug` 侧另有 `dropPotions()`（空腰带）与 `givePotion(id)`，理由与 `startWithSeed` 相同：
一个必须"祈祷掉落抽到某一瓶"的检查器不是检查器（§185）。

'''

# ---------------------------------------------------------------- sts-act1-plan.md
PLAN = '''
---

## 10. 现状（2026-11-03）

§1 的 17 条现状锚点写于实现之前；这份表**不再逐行改**（改历史没有意义），当前状态以
`docs/sts-wiki-gap.md` 与 `docs/port-plan.md` 的 §161.x–§186 为准。三句话：

* **能力**：三幕可从开局走到幕末；战斗内核与参考逐字节对拍（`FIGHT_DIFF 182/182`、
  `CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）；20 道闸门全绿。
* **内容**：卡 / 状态 / 药水 / 遗物 / 事件 / 每幕遭遇池的数字都由 `native/gap_check.py` 重算，
  **药水池已满**（33/33），三幕精英每幕 3 个。
* **仍然缺的**：`EACT` 的 ascension 维度（一根维度解锁 A2/3/4 + A17/18/19 六条）、事件效果的
  **列表**、每幕的第二三只 Boss、A1/A10/A12/A15/A20。逐条见 `sts-wiki-gap.md` §2–§3。

'''


def main():
    insert_before("SEMANTICS-v1.md", "## 3. 有意偏离清单", SEMANTICS)
    append("play-card-flow.md", PLAY)
    append("modifier-pipeline.md", MODIFIER)
    append("run-layer.md", RUN)
    append("content-schema.md", SCHEMA)
    append("content-binary-format.md", BINARY)
    append("env-abi.md", ABI)
    append("sts-act1-plan.md", PLAN)


if __name__ == "__main__":
    main()
