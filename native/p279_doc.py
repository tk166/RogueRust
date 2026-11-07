"""§279 文档：port-plan 新一节 + 分析文档"缺口一（B）已做" + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
ANALYSIS = 'D:/Vibe/sts-tui/docs/mechanism-gaps-analysis.md'
GAP = 'D:/Vibe/sts-tui/docs/sts-wiki-gap.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §279 事件选项的**条件**（`Requires`）+ `relic_lose` 原子

§277 的分析文档把"事件的条件选项"列为 §278（`EVND`）之后才可能做的一步，并且**写错了一句**：
它说"`expr` 的表达词汇表已经够（金币/牌组/遗物/HP 都读得到）"。检查之后是错的 ——
`expr` 的每一个 kind 都挂在**战斗状态**上（`currentHealth` 是某个战斗员的血、
`combatantZoneCount` 是战斗中的牌区、`hand.hasCardWithTag` 是手牌），`ExprContext` 拿的是
`&CombatState`。run 层没有 `CombatState`，也没有"回合"。所以本节实现的是**第二份、封闭的**
词汇表。那句错话在分析文档里已改成"检查之后是错的"，并写明了原因。

### 279.1 为什么需要它

wiki 的 `Forgotten Altar`（第二幕）第一个选项是 `[Offer: Golden Idol]`，并明写
"if the player does not have Golden Idol, this option is replaced with
`[Locked] Requires: Golden Idol`"。没有载体时，内容只能把它压成"一个按钮，点了什么也没有"，
或者干脆删掉 —— 两种都不对。（同一节还带出第二件事：这个选项是"**失去**金像、得到血像"，
而旧词表只有"得到遗物"，没有"失去"。）

### 279.2 形态：**一串原子**（AND），不是布尔树

```json
"Requires": [ {"Kind": "relic", "Op": "has", "Id": "golden_idol"} ]
"Requires": [ {"Kind": "gold",  "Op": "at_least", "Amount": 150} ]
```

| kind | 数值/存在 | 允许的 op |
|---|---|---|
| `gold` / `health` / `max_health` / `deck_count` / `ascension` | 数值 | `at_least` / `at_most` |
| `health_percent` | 数值（**百分比**） | `at_least` / `at_most` |
| `relic` / `card` | 存在（`Id`） | `has` / `lacks` |

为什么不是布尔树：真实内容里的条件**全都是单条**（wiki 的 `Requires:` 行只有一句）。
一棵树要一套解析器 + 一套求值器 + 一套"表里有但没实现"的判据；一串原子两个循环就够，
而且**闭集**意味着内容门能逐条判。缺 `or` 是**已知的表达力缺口**（真需要时再加）。

★ `health_percent` 是唯一把 `Amount` 当**百分比**读的 kind：阈值先用最大 HP 换算成血量
（`floor(max HP × n / 100)`，与 §278 的百分比效果**同一个取整**）。第一版把它写成
"`value = max 的 N%` 然后跟 N 比" —— 两个方向都错，而**只有"两侧"判据**才抓得住这种反向
（单侧永远看着对）。

### 279.3 ★ 求值器放在 `rd-core`，事实由 `rd-wasm` 摊

三层各做各的：

* `rd-core/src/run_expr.rs`：读 `Requires`（**`F_TERMLIST`**，与 §278 的 `Effects` 同一个形状）
  并求值。它**不知道 `RunState` 长什么样** —— 只认 [`RunFacts`]。
* `rd-wasm`：把 `RunState` 摊成 `RunFacts`（金币/HP/上限/等级/遗物 id/牌组 id）。
  条件是**内容**的一部分（它引用的都是内容里的 id），而 `rd-run` **不读内容**（§133），
  所以求值只能在同时握有内容与局面的这一层发生。
* `rd-run`：不知道"条件"这件事存在 —— 它只执行效果。

⚠️ `Requires` 又是 **`F_TERMLIST`**（§278 的第一次教训重演了一遍）：用 `field()` 读它会
拿到 `Malformed`，而错误在这里的**默认值**可能是"永远可选"或"永远不可选"，两种都是
"屏幕正常、行为全错"。改用 `term_list_field_or_empty`（它把**缺席**当空列表）。
"缺席 = 无条件 = 永远可选"是**故意**的：反过来会让每一条普通选项都要写 `"Requires": []`，
而"忘了写"就变成一个永远消失的按钮。

### 279.4 判的是**同一个**函数，两处都判

* `rd_run_event_option_available(slot)`：页面据此决定**画不画**。
* `rd_run_choose(slot)`：**自己**再判一次，不成立就 `-2` + 文本。

"藏起来"不等于"点不到"（页面可能是旧快照，或者有人直接调 ABI）。两处都调
`option_available`，所以"显示的按钮点下去没用"与"藏起来的按钮其实能点"不可能只在一侧出现。

页面侧还有一个坑：`describeEvent` 过滤掉不可选的选项后，按钮的 `slot` **必须用条目自己的
`slot`**，不能用过滤后的下标 —— 否则"第 2 个按钮"会打给内核第 1 个槽，而屏幕上完全正常。

### 279.5 `relic_lose:<id>`（顺带补的第一个缺口）

`Forgotten Altar` 的 `[Offer: Golden Idol]` 是"**失去**金像、得到血像"。
`RunState::remove_relic(id)` 三条约束：不持有 ⇒ `NoSuchRelic`（不是静默成功：那会让
"条件写错"变成"按钮白点"）；拾取时给过的一次性东西（`omamori` 的 2 次）**不回收**
（参考也没有"撤销拾取"的概念）；后面的遗物**往前挪**（`relics()` 的切片始终连续）。

### 279.6 内容：`forgotten_altar` 补成真事件（4 选项 + 3 个后续屏）

```
forgotten_altar      [Offer: Golden Idol]  Requires = relic has golden_idol
                       效果：relic_lose:golden_idol → relic:bloody_idol   → 自己的屏
                     [Sacrifice]  max_hp +5 然后 damage_pct 25 / A15 35   → 自己的屏
                     [Desecrate]  curse:decay                            → 自己的屏
                     [Leave]
```

⚠️ `Sacrifice` 的**顺序**是 wiki 的：patch 记录写着 "gives you the Max HP **before**
damaging you, this way you won't die if the damage hits you first" —— 效果列表的顺序就是执行顺序。

`the_ssssserpent` 顺手修了一条 wiki 偏差：`Agree` 的 A15 金币是 **150**（旧内容两处都写 175），
并且给了它两个后续屏（`[Continue]` / `[Leave]`）。

### 279.7 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `every_kind_answers_both_sides` | **每一种 kind/op 的两侧**（24 个用例）。镜像里只有一条真条件，另外七种 kind 没有内容在用 —— "某个 kind 永远返回 true"在真内容上**永远不会红** |
| `unknown_kinds_and_ops_are_errors_not_defaults` | 认不出的 kind / 不配套的 op / 缺 id / 百分比越界，**全部报错**（不默认成立） |
| `the_image_carries_a_real_requirement` | 镜像里那条 `relic has golden_idol` 两侧都对 |
| `an_option_without_requires_is_always_available` | 没有 `Requires` ⇒ 永远可选（"缺席 ≠ 不成立"） |
| `an_event_choice_that_edits_the_deck_owes_a_pick` | ABI：`available(0)==0` → `choose(0)` 被拒（-2）且事件还开着；塞进金像后同一槽变 1，交换真的发生了（金像没了、血像到手） |
| 内容门 `[6c]` | `Requires` 的闭词表 / op 配套 / 参数 / 引用存在性；**反真空**：整份内容一条条件都没有 ⇒ 红 |
| `browser_test` (l) | **DOM**：4 个选项、1 个锁着 ⇒ 画 **3** 个按钮，锁着的那个**不在** DOM 里；点它 `-2` 且事件还开着 |
| `ui_test` | 面板层：`available:false` 的条目被滤掉，而保留下来的按钮带**自己的**槽号 |

**负控**（`native/p279_negative.py`，改 JSON → 重编 → 跑门/跑 Rust → 还原）：
① 认不出的 kind；② `relic` 配 `at_least`；③ `health_percent:0`；④ 把那条真条件换成
"永远成立"（`gold at_least 0`）⇒ 内核的两侧判据必须红 —— 四条全 RED ✓。

### 279.8 顺手修的一个 walker 坑

`web/map_test.mjs` 的事件助手盲选 **槽 0** —— 它现在是条件选项，于是"点一条锁着的路 →
内核拒 → 屏幕没变 → 下一格报 `step refused`"，而失败指到**地图**。改成"选第一个可用的槽"，
并把它写成"一路点到收尾"（§278 起事件是多段的）。

### 279.9 新调试入口 `rd_run_begin_event`

理由与 `rd_run_grant_potion` 一样：**种子不会恰好给你想要的那一屏**（`?` 房要掷骰、
地图上未必有 `?`、还要按三幕池子抽中）。没有它，§279 的 DOM 半只能靠单元测试。
它**不是** `cfg` 门（发货的 `.wasm` 与测过的必须是同一个二进制），并且进回放脚本
（`begin_event` 记录）—— 它改运行层，与 `grant_potion` 同一条道理。

⚠️ 写这个入口时又踩了一次"面板写者"的坑：第一版调的是战斗侧的 `render()`，于是**内核
已经打开了事件、屏幕上还挂着祝福那两个按钮**。面板的写者是 `renderNode()`。

### 279.10 账

镜像 **150,752 B**（core 117,072 B）；事件 11 房间 → **17 段**、32 选项（**1 条条件**）、
53 效果；`rd-core` **795** / `rd-run` 149 / `rd-wasm` 124；8/8 tables 16 checks；
`STS_CONTENT PASS`；六道页面门（含 `browser_test`）全过；`COVERAGE_MATRIX` 805 行；21/21。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    a = io.open(ANALYSIS, encoding='utf-8').read()
    a = a.replace('''**B. 条件选项**（A 之后再做）''',
'''### ✅ 状态：**方案 B 已落地**（`port-plan.md` §279）

`Requires`（一串原子，AND）+ `relic_lose:<id>` 已经做了，`forgotten_altar` 补成 4 选项
（含一条条件）+ 3 个后续屏。

⚠️ **本节的原文有一句是错的**，保留并更正：它说"表达式词汇表已经够（金币/牌组/遗物/HP 都
读得到）"。**检查之后是错的** —— `expr` 的每一个 kind 都挂在战斗状态上（`currentHealth` 是
某个战斗员的血、`combatantZoneCount` 是战斗中的牌区、`hand.hasCardWithTag` 是手牌），
`ExprContext` 拿的是 `&CombatState`。所以落地时用的是**第二份、封闭的**词汇表
（`rd-core::run_expr` 的 6 个数值 kind + 2 个存在 kind），它读的是 `RunFacts`。

下面保留当时的分析原文（作为"为什么当时以为可以复用"的记录）。

**B. 条件选项**（A 之后再做）''')
    io.open(ANALYSIS, 'w', encoding='utf-8', newline='\n').write(a)

    g = io.open(GAP, encoding='utf-8').read()
    old_row = '''| ~~真实事件的**剧情分支**被合并~~ | **§278 已做**：`EVND` 段表（`Options` 是 term 列表 ⇒ 选项数不固定）+ `EV.Entry`；`golden_idol` 已补成两段三选一（含 `damage_pct`/`max_hp_pct` 两个百分比原子）。**条件选项（`Requires`）仍未做。** |'''
    new_row = '''| ~~真实事件的**剧情分支**被合并 + 条件选项~~ | **§278/§279 已做**：`EVND` 段表（选项数不固定）+ `EV.Entry` + `Requires`（闭词表，6 数值 kind / 2 存在 kind）+ `relic_lose`；`golden_idol` 补成两段三选一，`forgotten_altar` 补成 4 选项（1 条条件）+ 3 个后续屏。 |'''
    assert g.count(old_row) == 1
    g = g.replace(old_row, new_row)
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§278）', '（主计划 §1–§279）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§279 doc + analysis correction + gap row + README')


main()
