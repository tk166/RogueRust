# 两个机制缺口的重构方案（§277 分析）

> 读者：**接手下一批的人**。这两条不是"还没做的内容"，而是**内核/内容表达不了**的规则，
> 所以它们挡住的是一整类实体（事件的剧情分支、战斗中每回合重掷的随机）。
> 本文只写"缺什么载体、怎么加、加完怎么证明"，不含实现。
>
> 出处：`docs/port-plan.md` §277；两个缺口的现状记在 `docs/sts-wiki-gap.md` §C / §D。

---

## 缺口一：**真实事件的剧情分支被合并**

### 现状（可查的事实）

我们的事件是"一张表 + 每张表两个选项"，每个选项是一串 `EventEffect`：

```
EV 行：Id | NameKey | DescriptionKey | Label0 | Effects0 | Effects0Asc | Label1 | Effects1 | Effects1Asc
```

`sts_content_check.py` 的 `INV_EVENTS` 逐事件钉住这两个选项。真实 StS 的事件是**一棵对话树**：
一段文本 → 若干选项 → 每个选项可能换来**另一段文本**（再给选项），并且有些分支要求
"你身上有 X 金币/某张牌/某个遗物"才出现。Golden Idol 的 Outrun / Smash / Hide 三选一
在我们这里只有两选项，就是被这套结构压掉的。

### 缺的是什么（一句话）

**缺"事件的第 N 段"这个实体**：`EV` 行的四个格是"两段文本 + 两串效果"，而树需要
"任意多个节点 + 边"。

### 重构方案（三档，按成本排）

**A. 最小扩展：`EV` 行变成"节点表"**（推荐先做这个）

* 新增一张表 `EVND`（事件节点）：`Id | TextKey | Label0 | Effects0 | Label1 | Effects1 | …`，
  每个选项多一格 `Next`（下一段的节点 id，空 = 结束）。
* `EV` 行退化成"入口节点 id"（一行一格），旧的两选项事件 = 一个节点 + 两个 `Next: 空`。
  这是**纯扩容**：既有 14 个事件机械迁移，行为不变。
* 运行层：`RunState.event` 从"事件 id"变成"事件 id + 当前节点 id"（一个 `RunId` 加一个 `RunId`，
  都进指纹）。`resolve_event` 只前进一段；`Pending::Event` 在多段里保持。
* 页面：`ui_panels.js::describeEvent` 已经是"一段文本 + 按钮"，**不用改**。

**B. 条件选项**（A 之后再做）

* 每个选项加一格 `Requires`（复用 `expr` 的布尔表达式 + `ExprContext::content`）。
* 表达式词汇表已经够（金币/牌组/遗物/HP 都读得到），缺的只是"事件层持有 `RunState`"这件事 ——
  现在事件效果是**闭集枚举** `EventEffect`，条件要先做成一个能读 `RunState` 的求值器。
* 判据：**同一事件在有钱/没钱两种局面下给出的选项数不同**（这条是唯一能证明"条件真的生效"的）。

**C. 剧本 DSL**（不建议）

把事件写成一段程序（像 `EACT` 那样）。收益是能表达任意剧情，代价是再造一个 IR、一个解释器、
一套内容和一套判据 —— 而 StS 的事件树**最深的也只有 3 段**（`docs/spec` 里 14 个事件的人工核对
记录），A + B 覆盖了全部。

### ✅ 状态：**方案 A 已落地**（`port-plan.md` §278）

`EVND` 段 + `EV.Entry` 已经做了，11 个旧事件机械迁移（语义快照逐字段比对），
`golden_idol` 补成真树（两段 + 三选一）。**方案 B（条件选项）仍未做** —— 见下面的清单。
下面保留当时的分析原文，作为"为什么这么加"的记录。

### A 的具体改动清单

| 位置 | 改什么 |
|---|---|
| `tools/contentc/rdcfmt.py` | 新段 `EVND` + `EVND_ROW`（`Id/TextKey/Label0/Effects0/…/Next0/Next1`）；`SEC_ORDER` 加一位 ⇒ **FORMAT_VERSION 动** |
| `tools/contentc/compile.py` | `("EVND", "EventNodes")` 映射；`strip_presentation` 加 `TextKey` 白名单 |
| `kernel/rd-core/src/content.rs` | `EventNode` 行读取器（照 `EvRow` 的形状，多一个 `Next` 格） |
| `kernel/rd-run/src/state.rs` | `event_node: RunId` 字段 + `resolve_event` 前进一段 + 指纹/存档各加一行 |
| `kernel/rd-wasm/src/run.rs` | `rd_run_event_text_*` / `rd_run_event_label_*` 读**当前节点**而不是行 |
| `native/sts_content_check.py` | `INV_EVENTS` 加"入口 + 节点可达"两张表（**穷尽**：每个节点都必须可达，否则是死剧情） |
| 判据 | ① 迁移后的 14 个事件**逐字节**行为不变（节点数=1 时等于旧行）；② 一个两段事件走完后 `pending` 清掉、`event_node` 归零 |

⚠️ 这一档最贵的不是代码，是**「同一份文本只存一次」**：现在 `EV` 行的 `DescriptionKey`
在文本池里，节点化之后每个节点的文本也要进同一个池（`STR`/`STRO`），否则镜像里会有两份
一样的句子。

---

## 缺口二：战斗中的**随机**（每回合重掷）没有值节点

### 现状（可查的事实）

`ir.rs` 的 41 个节点里**没有** `randomInt` / `randomChoice` 这一类。随机只存在于三处：
① 敌人 AI 的 `Choice`（`IntentRules` 的加权表，**引擎侧**，不是程序节点）；
② `createRandomCardInstance`（随机造牌，内部用 `CombatState` 的 RNG）；
③ 遗物/药水在运行层掷骰。

所以"每回合随机 X"这类规则写不出来。wiki 里属于这一类的有：`Gremlin Wizard` 的
"50/50 蓄力/攻击"（我们用固定首招绕开了，`AiNote` 写着）、`Snecko` 的"每回合随机费用"
（那是 `play.rs` 的费用阶段，不是敌人）、`Mad Gremlin` 的伤害浮动、以及事件/遗物里
"随机 1-3 张牌"。

### 缺的是什么（一句话）

**缺"从程序里问一个随机数"的表达式**，以及**一条明确的随机流**。

### 重构方案

**A. 一个表达式 `randomInt(range)` + 一个节点的取值**（推荐）

* `expr.rs`：`INT_KINDS` 加 `"randomInt"`，`value` 是 `{Min, Max}`（都是 int 表达式）。
* 求值：`ctx.state.rng` 走**战斗**那条流（`CombatState` 已有一条按 seed 派生的 RNG，
  `createRandomCardInstance` 用的就是它）—— **不新开流**：新开一条会让"同一场战斗的
  随机序列"多一个维度，而回放判据只认现有那条。
* 判据必须**两侧**：
  ① **分布**：把同一个动作跑 200 次，`randomInt(1,3)` 三个值都出现过（防"退化成常量"）；
  ② **可复现**：同一个 seed 跑两遍，序列**逐次相同**（这是 `hash_golden` 那一层的要求）。
* ⚠️ **一个陷阱**：表达式在**预检阶段**也会被求值（`exec::resolve_damage` 的 S4 池要算数值），
  而"预检求值一次、执行再求值一次"会让随机数被吃掉两次 —— 于是"同样的 seed"给出不同的结果。
  解法：随机节点的结果要**在计划里固化**（像 `x_cost_payment` 那样先算、后面读），
  而不是每次求值都掷。

**B. `randomChoice(list)`**（A 之后顺手做）

* 返回"列表里的第 k 个"，`k = randomInt(0, len-1)`；列表是 term 列表（同 `Choice` 的形状）。
* 用途：`Snecko Eye` 的"随机费用"（`play.rs` 的费用阶段读它）、"随机一张牌"的敌人动作。

**C. 让敌人 AI 的 `Choice` 也能被程序读**（不建议现在做）

`IntentRules.Choice` 现在由引擎选，程序读不到"这一次选了哪个"。真要做"选完之后按选择分支"，
需要把"选中的 action id"塞进 `event.resultKey` 之类的通道 —— 那是 `If Fatal` 那个坑的同类，
收益小，先不做。

### A 的改动清单

| 位置 | 改什么 |
|---|---|
| `kernel/rd-core/src/expr.rs` | `INT_KINDS` + `Class::Int` + 求值臂（`ctx.state` 的 RNG） |
| `kernel/rd-core/src/exec.rs` | **预检/执行**两条路径的"只掷一次"：把结果写进 `resultKey` 或一个 `planned` 槽 |
| `native/patch_*.py` | 内容侧：`Gremlin Wizard` 的 50/50、`Mad Gremlin` 的伤害浮动 |
| 判据 | 分布（200 次至少 3 种结果）+ 同 seed 可复现 + **预检一次执行一次**结果的断言（第 3 条才是真坑） |

---

## 两条缺口的共同点（值得记）

1. **都是"内容表达不了"，不是"内容没写"** —— 所以它们的成本不在条目数，而在**新段/新节点**。
   加段要动 `FORMAT_VERSION`、`SEC_ORDER`、`strip_presentation`、读取器、指纹、存档 **六处**；
   加节点要动 `ir.rs` 的三张表 + `exec.rs` 的预检/执行两条路径。
2. **判据都必须"两侧 + 防真空"**：事件要证明"有钱/没钱选项数不同"，随机要证明"分布 + 可复现"。
   只测一侧的话，一个退化成常量/退化成单段的实现照样全绿。
3. **都不该顺手做**：一个 `EVND` 段会把镜像格式推到 v5，一次 `randomInt` 会把"预检也求值"
   这个坑挖出来 —— 两次都要单独一节、单独的数字。
