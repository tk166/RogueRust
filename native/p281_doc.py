"""§281 文档：port-plan 新一节 + 更正分析文档里"预检也求值"的说法 + README。"""
import io

PLAN = 'D:/Vibe/sts-tui/docs/port-plan.md'
ANALYSIS = 'D:/Vibe/sts-tui/docs/mechanism-gaps-analysis.md'
GAP = 'D:/Vibe/sts-tui/docs/event-gaps.md'
README = 'D:/Vibe/sts-tui/README.md'

DOC = """
---

## §281 战斗随机：一个入口、一个值节点、一份账

§277 的分析文档把"战斗中没有值节点"列为缺口二，并给了方案 A（`randomInt` 表达式）。这一节
落地它，同时**更正了那份文档里的一个错判**（见 281.5）。

### 281.1 先说扫描结论：StS **没有**随机伤害

为了决定"要不要造内容来喂这个机制"，先按 wiki 查了真内容：`Slay the Spire` 里
**没有任何敌人或卡牌的伤害是一个随机值**（`Mad Gremlin` / `Gremlin Wizard` / `Snecko`
的招式都是定值；`Gremlin Wizard` 的 50/50 是**选招**，而选招由 `IntentRules.Choice` 的
加权表表达，早就有）。真正随机的东西只有四类：

1. **选招**（`Choice`，已有）；
2. **随机造牌**（`createRandomCardInstance`，已有）；
3. **随机价格**（`Confusion` / `Snecko Oil`）；
4. **事件的概率与区间**（`Scrap Ooze` 的 25%→35%…、`World of Goop` 的 20-50 金币）。

所以这一节**不造内容**：把机制做对，并把它接到**已经在掷骰**的那一处（`Snecko Oil`）。

### 281.2 ★ 缺口真正在哪：**三份账**

代码里原本有三种"战斗随机"：

| # | 谁 | 怎么掷 | 账 |
|---|---|---|---|
| 1 | 洗牌 | `rng::shuffle_indexes(seed, step)` | 只推 `random_step` |
| 2 | 随机造牌 | 同上 | 只推 `random_step` |
| 3 | **`Snecko Oil` 的价格** | `rd-wasm` 里手抄 `next_u32(&mut seed) % 4` | **同时改 `random_seed` 与 `random_step`** |

第 3 条不只是"抄了一份"：它把 `random_seed` 也改了，于是下一次抽取的
`initial_state(seed, step)` 与洗牌那条路**分家**。症状是"同一个种子两次跑出不同的牌序"，
而那是最难查的一类。所以：

* `rng::draw_u32(seed, step)` —— 纯函数，与洗牌同一份派生；
* `CombatState::draw_in_range(min, max)` —— **唯一入口**：派生、取模、`step += 1`，
  `random_seed` **不动**；`max <= min` 是常数、**不消耗**随机流（否则一句无害的内容改写
  会让整局偏移）；
* `exec::draw_random(state, min, max)` —— 再上一层薄壳，让**表达式节点与药水**共用同一个
  调用点（否则又是两份）。

### 281.3 `randomInt` 值节点：能取数的位置只有一个

`ExprContext.state` 是 `&CombatState`（只读）—— 求值器**不能**抽随机数（抽要写 `random_step`）。
所以：

* `expr::INT_KINDS += "randomInt"`（值类别是 int，于是 `eval_bool` 会说"问错了问题"）；
* `expr::eval_int` 的 `randomInt` 分支**只报错**（`ExprError::RandomNeedsADraw`）——
  走到这里说明它被**嵌套**在别的表达式里（`add{randomInt{1,3}, 1}`），而那是明确不做的形状：
  宁可响亮拒绝，也不猜一个数；
* 真正的取数在**派发点** `exec::eval_amount`（那里有 `&mut ExecContext`）：它先看
  `Amount` 子节点的 kind，是 `randomInt` 就求 `Min`/`Max` 再 `draw_random`。

为什么不做"先扫一遍节目、把随机值冻结成计划"：计划要跟着**节目帧**进续延才能跨挂起，
而"每个数值节点在派发时抽一次"天然只要一个 `&mut`。代价写在注释里（嵌套不支持），
收益是没有第二套状态。

**显示路径**不受影响：`program_damage` 只回答字面量，非字面量答 `-1`
（既有契约，见 `rd-wasm/src/lib.rs` 的模块头第 5 条）——所以意图面板**不会**为了画一个数字
而消耗随机流。这正是"预算与显示分家"该有的样子。

### 281.4 ★ 这一节顺手抓到两个真 bug

**① §179 的 Snecko Oil 判据一直是空的。** 它断言"每张牌的价格都在 `0..=3`"，而 `strike` 的
印刷价就是 **1**，落在 `0..=3` 里 —— 于是"价格根本没被随机化"也能通过。原因：显示侧的
`hand_costs` 只读 `CARD_COST_DELTA_COUNTER`，**没读** `CARD_COST_OVERRIDE_COUNTER`
（绝对覆盖），而 `play.rs` 的费用修饰器是**先看绝对覆盖、再看 delta**。于是"屏幕显示印刷价、
内核收掷出来的数"。补上之后价格真的随种子变了。

**② 我把 `match atom` 改成 `match atom_kind` 时打断了带 payload 的分支。**
`choice_offered:<tag>` 的 guard 原来写的是 `other.starts_with("choice_offered:")` ——
拿到的是**整串**；改成 kind 之后它永远匹配不上，于是 `Attack Potion` 掉进 `other =>` 报
"未知的药水效果"，而页面上只是"喝了没反应"。`ACT1_SLICE`（boss 场景 311 秒后报
"no seed can reach that node kind"）与 `browser_test` 的 6 条断言一起抓到。

教训与 §277 同形：**改"匹配的粒度"要顺着每一处用到整串的地方看一遍**。

### 281.5 更正分析文档里的一句错判

§277 的分析文档写："★ 一个陷阱：表达式在**预检阶段**也会被求值（`exec::resolve_damage`
的 S4 池要算数值），而'预检求值一次、执行再求值一次'会让随机数被吃掉两次。"

**检查之后：这句是错的。** `exec::preflight` 只做结构检查（`ValidateNodeExecutors` 的等价物），
**不求值**任何表达式；`resolve_damage` 拿到的是**已经算好的 `base`**，一次派发只求值一次。
真正的约束不是"预检"，而是两条别的：

* 求值器是**只读**的（上面 281.3），所以取数只能在派发点；
* **显示**路径（意图面板）会想算伤害 —— 而它已经按"非字面量答 `-1`"处理了。

分析文档已就地更正，并保留原文作为"当时为什么这么以为"的记录。

### 281.6 判据 + 负控

| 判据 | 钉住 |
|---|---|
| `a_draw_covers_its_whole_range_and_advances_one_step` | 64 次 `draw_in_range(0,3)` **四档都到过**（不是"总取下限"）、`step` 恰好 +64、`random_seed` 不动；`max <= min` **不消耗** |
| `a_draw_sequence_replays_from_its_seed` | 同种子 ⇒ 同序列；换种子 ⇒ 至少一处不同（两侧）；且与洗牌**同一份派生**（`draw_u32(seed,5)` 对齐） |
| `the_price_roll_is_reproducible_and_costs_one_step_per_card` | 真 ABI：同种子同价格、换种子价格不同、`step` 恰好 +手牌数、`random_seed` 不动、价格在内容给的 `0..=3` |
| 内容门 | `combat_randomize_costs` **必须**带 `min:max`（以前是"不许带 payload"） |
| `the_potions_are_readable`（rd-core） | 范围在内容里、且 `0..=9` |

**负控**（`native/p281_negative.py`，改**内核源码** → 跑判据 → 还原 → 断言还原后又是绿的）：

1. `draw_in_range` 永远返回下限 ⇒ 判据 1 红；
2. 不推 `step` ⇒ 判据 1 红；
3. 只读 seed、忽略 step ⇒ 判据 2 红（与洗牌分家）；
4. 显示侧不读绝对覆盖 ⇒ 判据 3 红。

四条全 RED ✓。第 4 条特别值：它证明"屏幕与内核必须显示同一个数"这件事**有判据**。

### 281.7 还没做的（诚实清单）

* **嵌套的 `randomInt`**（`add{randomInt{1,3}, const 1}`）不支持，会响亮报
  `RandomNeedsADraw`。原因见 281.3；真内容只需要 `Amount: randomInt{Min,Max}` 这一种形状。
* **`randomChoice`**（从一张列表里挑一个）没做：随机造牌已经走
  `createRandomCardInstance`，而"随机挑一条**效果**"今天没有内容要。
* **`Confusion` 状态本身**没做（Snecko 的 debuff：**每抽一张牌**重掷价格）。它有内容载体
  （`standard.confusion` 不存在）就绪后，最自然的做法是把 §281 的取数接到"抽牌钩子"上 ——
  那是 play 层的一节，不是这一节。
* **事件概率**（`Scrap Ooze` 的 25%→35%…）走**运行层**随机流（`RunStream::Event`），
  与战斗随机是两条流，属于事件那一节。

### 281.8 账

镜像 **152,592 B**（core 118,908 B，只差 `snecko_oil` 的 payload 4 字节）；
`rd-core` **797** / `rd-run` 152 / `rd-wasm` **126**；8/8 tables 16 checks；
`STS_CONTENT PASS`；`ACT1_SLICE` / `BROWSER_TEST` / `SOAK` / 五道页面门全过；
`COVERAGE_MATRIX` 807 行；21/21 绿。
"""


def main():
    plan = io.open(PLAN, encoding='utf-8').read()
    io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(plan.rstrip('\n') + '\n' + DOC)

    a = io.open(ANALYSIS, encoding='utf-8').read()
    old = '''### ✅ 状态：**方案 A 已落地**（`port-plan.md` §278）'''
    new = '''### ✅ 状态：§281 已落地（`randomInt` 值节点 + 统一的随机入口）

```
rng::draw_u32(seed, step)                   纯函数，与洗牌同一份派生
CombatState::draw_in_range(min, max)        唯一入口：派生 → 取模 → step+1（seed 不动）
exec::draw_random(state, min, max)          表达式节点与药水共用的那一层
expr::randomInt{Min, Max}                   值节点：**只能在派发点取数**，嵌套 ⇒ 响亮拒绝
```

⚠️ **本节原文有一个错判，已更正**：它说"表达式在**预检阶段**也会被求值（`resolve_damage`
的 S4 池要算数值），预检一次执行再算一次会让随机数被吃掉两次"。

**检查之后是错的**：`exec::preflight` 只做结构检查、不求值；`resolve_damage` 拿到的是算好的
`base`，一次派发只求值一次。真正的约束是另外两条 —— **求值器只读**（`&CombatState`，抽数要写
`random_step`），所以取数只能在派发点；**显示路径**（意图面板）想算伤害，而它已经按
"非字面量答 `-1`"处理。下面保留原文。

另：StS **没有**随机伤害值（wiki 扫描：`Mad Gremlin`/`Gremlin Wizard`/`Snecko` 的招式都是定值。
`Gremlin Wizard` 的 50/50 是**选招**，`IntentRules.Choice` 早就能表达）。所以 `randomInt`
今天没有内容消费者 —— 这一节把它接到**已经在掷骰**的 `Snecko Oil` 上，并把范围从 wasm 常数
搬进内容（`combat_randomize_costs:0:3`）。

### （原文）✅ 状态：**方案 A 已落地**（`port-plan.md` §278）'''
    assert a.count(old) == 1
    a = a.replace(old, new)
    io.open(ANALYSIS, 'w', encoding='utf-8', newline='\n').write(a)

    g = io.open(GAP, encoding='utf-8').read()
    old_g = '''### 3.2 随机结果（`The Joust` 的 70/30）

`mechanism-gaps-analysis.md` 缺口二的 `randomInt`。仍**未做** —— 那是它自己的 §281。'''
    new_g = '''### 3.2 随机结果（`The Joust` 的 70/30）

**战斗侧**已经做了（§281：`randomInt` + 统一入口），但 `The Joust` 要的是**运行层**的
概率（70/30 的胜负），走 `RunStream::Event` 那条流 —— 那是事件那一节的活，与战斗随机不同流。
同一类还缺：`Scrap Ooze` 的 25%→35%…（每次失败 +10% 且 HP 代价 +1）—— 它还要一个
"可重复的选项 + 递增状态"，属于事件机制的下一次改动。'''
    assert g.count(old_g) == 1
    g = g.replace(old_g, new_g)
    io.open(GAP, 'w', encoding='utf-8', newline='\n').write(g)

    r = io.open(README, encoding='utf-8').read()
    r = r.replace('（主计划 §1–§280）', '（主计划 §1–§281）')
    io.open(README, 'w', encoding='utf-8', newline='\n').write(r)
    print('§281 doc + analysis correction + gap update + README')


main()
