"""§277 文档（port-plan）+ README + 缺口文档。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
README = 'D:/Vibe/sts-tui/README.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'

DOC = """
---

## §277 遭遇**组合槽**（`Exordium Thugs` / `Wildlife`）+ 两个机制缺口的分析

### 277.1 组合槽：一条遭遇记录可以是"从这里挑一只"

wiki 的 Act 1 硬池里有两条不是固定组合，而是**加权随机组合**：

* `Exordium Thugs`（1.5）：第一个 = Louse（任色）**或** Medium Slime（任型）；
  第二个 = Slaver（任色）**或** Cultist **或** Looter。
* `Exordium Wildlife`（1.5）：第一个 = Fungi Beast 或 Jaw Worm；第二个 = Louse 或 Medium Slime。

枚举所有组合要 28 条遭遇；旧内容的做法是"钉一种组合"（§275 的 `3 Louses` 就是这么写的，
并注明偏差）。这一节把它做成机制：

```
ENCT.Enemies[i] = { "Position": 0,
                    "Candidates": [ {Id, Weight, MaxHealth, MaxHealthAsc, Actions, IntentRules, …}, … ] }
```

**候选是完整的敌人记录**（不是"只有 Id 的引用"）—— 战斗是从**记录本身**读
`Actions`/`IntentRules`/`StartingStatuses` 的，只写 Id 会造出一只**没有招式**的怪，
而且**不会崩**（它每回合什么都不做）。第一版就是这么写的，判据里那条
"`select_action` 必须给出选择"就是为它写的。

掷骰在**建战斗**时、用这一场战斗的 `seed` 派生（`pick_candidate`，一个 splitmix 步）：
遭遇已经在 `RunStream::Combat` 上滚过一次，组合属于"把这场战斗搭出来"（`Rolls` 初始化计数器
也在同一层）。**不开新流** —— 新开一条只会让 `run_hash` 的随机流计数多一格，而那一格
不影响任何运行层状态。判据是"同一个 seed 永远同一场"。

### 277.2 ★ 一处"决策"被四个消费者读过

加进去之后红了一串，而它们的原因**完全相同**：凡是要"按槽位读敌人记录"的地方都假设
那条记录有 `Id`：

| # | 消费者 | 症状 |
|---|---|---|
| 1 | `rd-wasm` 构建方（`build_session_at_with`） | `MissingField("Id")` |
| 2 | `rd-wasm::apply_starting_statuses`（起始状态/格挡） | 同上 |
| 3 | `rd-core::battle::apply_spawn_setup`（`Rolls` 初始化计数器） | `apply_spawn_setup: Encounter(MissingField("Id"))` |
| 4 | `rd-core::intent::locate_enemy` / `enemy_record`（意图层） | 第 2 回合 `select_action: Missing("Id")` |
| 5 | 内容门 / 覆盖矩阵 | 各自 `KeyError: 'Id'` |

修法不是"四处各抄一遍解析"，而是把**决策只做一次**：

* 构建方挑完就把结果记进 `slot_ids`，`apply_spawn_setup` 与 `apply_starting_statuses` 都**读**它
  （"挑哪一只"只有一个决定点）；
* 意图层的**唯一入口** `enemy_record` 按"这个槽是不是组合槽"决定读候选还是读槽 —— 一处改，
  `select_action` / `intent_for` / 计数器全部跟着通；
* 闸门的两个脚本各加一个"展开组合槽"的助手（`encounter_enemy_records` / 同样的 5 行），
  于是固定记录与候选走**同一段检查**，不需要豁免。

⚠️ 这一条值得单独记：**新机制的成本不在它自己，而在"所有按旧 shape 读的地方"**。
数一下有几处：5 处。漏一处就是"某一层静默地看不见那只怪"。

### 277.3 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `the_composed_encounters_pick_from_their_candidates` | 64 个 seed 里两个槽**都**出现过 ≥2 种候选；挑中的那只 `select_action` **必须给出选择**（候选只写 Id 会在这里红）；血量**随候选变**（同 HP 表退化成固定也红） |

**负控**（`native/p277_negative.py`，结构化改 JSON、跑完还原）：
① 候选削成只有 `Id`；② 权重全压在第一只上 —— 两处全 RED ✓。

### 277.4 两个机制缺口的分析（新文档）

用户还问了"事件剧情分支被合并"和"战斗中每回合重掷没有值节点"该怎么重构。这两条**不是内容没写，
而是表达不了**，所以单开一页：**`docs/mechanism-gaps-analysis.md`**。

要点：

* **事件树**：缺"事件的第 N 段"这个实体。方案是 `EVND` 节点表（每选项多一格 `Next`），
  `EV` 行退化成入口 —— 纯扩容，14 个旧事件机械迁移、行为不变；再做"条件选项"（`Requires`
  走 `expr` 的布尔表达式）；不建议做剧本 DSL（StS 的事件树最深 3 段）。
  代价：动 `FORMAT_VERSION` + `SEC_ORDER` + 读取器 + 指纹 + 存档 **六处**。
* **战斗中随机**：缺一个"从程序里问随机数"的表达式。方案是 `randomInt(Min,Max)`（走
  `CombatState` 现有那条 RNG，不新开流）+ 顺手做 `randomChoice`。
  ★ **真坑**：表达式在**预检**阶段也会求值，于是随机数会被吃掉两次 ⇒ 结果必须**在计划里固化**，
  而不是每次求值都掷。判据要三条：分布、同 seed 可复现、预检一次执行一次。

### 277.5 账

遭遇 **41 → 43**（两条组合槽）；Act 1 `Weak` 池 **15 → 17**；镜像 148,928 B（core 115,224 B）；
`rd-core` **791** / `rd-run` 146 / `rd-wasm` **124**；四条对拍全过；
`WEB_SMOKE` / `ACT1_SLICE` / `SOAK` / `MAP_RENDER` / `BROWSER_TEST` PASS；
`COVERAGE_MATRIX` 805 行；21/21。

⚠️ 两处容量常量这一节又动了：`MAX_POOL_IDS` **16 → 24**（弱池到 17，而 wiki 的 Act 1 池约 20 条，
这个数字还会咬人）；`soak_test.mjs` 的默认种子 **3 → 5**（弱池变大 ⇒ 随机游走命中宝箱/精英的
概率下降，"the walk never gained a relic" 那条**覆盖**断言红了 —— 按规矩加样本、不改断言形状）。
"""


def main():
    doc = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(doc.rstrip('\n') + '\n' + DOC)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('/ 41 遭遇 /', '/ 43 遭遇 /')
    r = r.replace('（主计划 §1–§276）', '（主计划 §1–§277）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)

    gap = io.open(GAP, encoding='utf-8').read()
    old = '''| Exordium Thugs / Wildlife | **动态组合规则**（"First enemy: Louse 或 Medium Slime…"），我们的遭遇是静态列表 |'''
    new = '''| ~~Exordium Thugs / Wildlife~~ | **§277 已做**：组合槽（`Candidates` 加权候选表）+ 两条遭遇。 |'''
    assert gap.count(old) == 1
    gap = gap.replace(old, new)
    # 机制缺口交叉引用
    gap = gap.replace('''### G. ★ 基础值偏差''', '''### D.4 两个**表达不了**的机制缺口（分析见 `docs/mechanism-gaps-analysis.md`）

| 缺口 | 缺什么载体 | 方案 |
|---|---|---|
| 真实事件的**剧情分支**被合并（Golden Idol 三选一只有两个） | "事件的第 N 段"这个实体（`EV` 行是"两段文本 + 两串效果"） | `EVND` 节点表（每选项多一格 `Next`），`EV` 行退化成入口；再做条件选项 |
| 战斗中**每回合重掷**的随机没有值节点 | 一个"从程序里问随机数"的表达式 | `randomInt(Min,Max)` 走 `CombatState` 现有 RNG；★ 结果要在计划里固化（预检也会求值） |

### G. ★ 基础值偏差''')
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(gap)
    print('§277 doc + README + gap D.4')


main()
