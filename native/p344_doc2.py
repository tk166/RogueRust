"""§344 的 port-plan 章节。"""

import io

PATH = 'docs/port-plan.md'

SECTION = """
## §344 四条 UI 内核缺口：G1 / G2 / G9 / G11

`docs/ui-state-model.md` §6 里剩下的四条"会静默出错"的缺口。它们共同的形状是
**"页面自己算 / 自己记"** —— 而页面的每一处赋值都靠"记得改"，那不是判据。

### G1：这一局结束了吗、为什么

页面前有一对**模块级变量** `runOver` / `runOverWhy`：战败时在 `endFight` 里置位、幕尽时在
`end_act` 里置位。两个变量、两个写者（与 `#nodePanel` 两个写者 §89/§90 同一个形状），
而代价是"局终"成了**历史**的函数 —— 回档之后、回放里、以及任何新写的渲染层都得重新发明它。

新枚举 `RunEnd`（判别值就是 ABI 值）：

| 值 | 名字 | 判据 |
|---:|---|---|
| 0 | `Ongoing` | 还能打 |
| 1 | `Defeat` | `health <= 0`（战斗收尾把血量折回运行层，战败就是 0） |
| 2 | `Victory` | `act >= MAX_ACT && boss_beaten`（最后一幕的 Boss 倒了） |
| 3 | `OutOfMap` | `end_act()` 被调用过（G2） |

**顺序有意义**：死就是死 —— 血量归零时即使这一幕的地图也走完了，答案仍是 `Defeat`。
前两幕的 `boss_beaten` **不是**通关：`mark_boss_beaten` 会换幕并把它清掉。

导出 `rd_run_over()`（`1/0/-1`）与 `rd_run_over_why()`（`0..3`）。分成两个是因为页面要说的话
完全不同（"第 N 层战败" vs "这一幕到此为止"），一个 `1/0` 说不出这件事。

页面那边把两个变量换成两个**函数**（`runOver()` / `runEndWhy()`）—— 派生值读取时从状态派生，
不缓存（R1）。于是 `startRun` / `endFight` / 回档 / 回放四处"手动清/手动置"全部消失。

### G2：幕尽是一个**动作**

`RunState::end_act()`：三条前提（没有待决问句 / 脚下节点已结算 / `reachable()` 为空），
任何一条不成立都**一个字节都不改**，并且拒绝要**分得清**：

* `WrongPhase` —— 还有待决问句，或者还没出发（`node < 0`）；
* `NodeNotSettled` —— 脚下这一格还没结算；
* `MapNotExhausted` —— 还有路可走（新变体：相位是对的，错的是"这一局还没到尽头"）。

它还进了回放脚本（`K_END_ACT = 21`）：它改变 `run_end()`，不进脚本的话回放会在最后一步分叉。

### ★ 顺带发现：SC-02b（幕尽头）在当前内容里**几乎不可达**

`reachable()` 在最后一排把 **Boss 哨兵**当成唯一前进方向（`inv:§7.2`：Boss 是 floor 16、
在地图之外）。所以"真的没事可做"只在 **Boss 已倒**时成立 —— 而那时要么换幕（act < 3）、
要么就是最后一幕（`Victory` 优先于 `OutOfMap`）。

⇒ `rd_run_end_act()` 仍然值得存在（它是 SC-02b 的内核落点，守卫是"真的没事可做"而不是
"页面觉得没事可做"），但 `ui-state-model.md` 的 §1 与 §6 已经**标注 SC-02b 当前不可达**，
而不是假装它在跑。这是"场景表里有一行没有状态能产生它"—— 只有把谓词写成内核事实才看得见。

### G9：篝火回复量

`RunState::rest_heal()` 早就在，而且算上了 `regal_pillow`（+15）与 `eternal_feather`
（每 5 张牌 +3）。页面却自己写 `Math.floor(hpMax * 30 / 100)` —— 于是持那两件遗物时
**显示的数字是错的**（显示 +24、实际 +39）。

⇒ 导出 `rd_run_rest_heal()`。这条不只是"分层不好看"：**规则外泄最终总会变成"两个数"**，
只是时间问题。

### G11：`BEAT_DESTROYED = 13`

`rd-core::beat::BeatKind::Destroyed` 会发 13，而 ABI 常量只认到 12 ⇒ 任何消费者只能把它当成
"未知种类"静默跳过。判据是**穷尽**的：`1..=13` 每个都有常量、常量等于码、`14` 不在闭集里。

⚠️ 复核时发现一件事：**页面根本不消费 beat**（动画走 `diffObservations`），所以
`ui-state-model.md` 当初写的"页面 `switch` 落空"是推断，真实缺口是"消费者无法命名它"。

### 判据与负控

| 判据 | 钉住什么 |
|---|---|
| `the_run_end_is_a_function_of_the_state`（rd-run） | 四态各自的触发 + **两条顺序**（死优先、前两幕的 boss_beaten 不是通关） |
| `ending_an_act_requires_that_there_is_nothing_left_to_do`（rd-run） | 三条前提各一次，拒绝**整局相等**；三条都满足才接受 |
| `the_run_end_and_rest_heal_come_from_the_kernel`（rd-wasm） | 三个导出的值 + 无局哨兵；`regal_pillow` 让回复量 +15（页面算不出来） |
| `every_beat_kind_has_an_abi_constant`（rd-wasm） | 13 个 beat 常量**穷尽**且等于码，14 不在闭集 |

负控 **5/5**（`native/p344_negative.py`）：`run_end` 不看血量 / 把前两幕的 `boss_beaten`
当成通关 / `end_act` 不检查 `reachable()` / `rest_heal` 丢掉遗物加成 / `BEAT_DESTROYED` 改回 12。

### 两个坑

1. **`#[derive]` 落在谁头上**：我把 `RunEnd` 插在 `pub enum Pending {` 之前，于是 `Pending`
   原有的 `#[derive(...)] #[repr(u8)]` 落到了新枚举上，而 `Pending` 变成裸枚举 ——
   报错是 `cannot find attribute 'default'` 与 `conflicting representation hints`，
   两句话都不提"属性被搬到隔壁了"。
2. **`node == -1` 时 `end_act` 报的是 `WrongPhase`**（前提 0），不是 `MapNotExhausted`。
   第一版判据直接 `mark_resolved()` 就调 `end_act`，游标还是 -1，于是红在
   "期望 `MapNotExhausted`、得到 `WrongPhase`" —— 而规则本身是对的。

### 数字

`rd-run 225`（223 + 2）、`rd-wasm 187`（185 + 2）、`rd-core 819`、units **1231**（下限 1227 → 1231）；
`state-fields` **69 fields**；导出 220 → **224**；四条对拍不动；`WEB_SMOKE PASS`；23/23 闸门。
"""

t = io.open(PATH, encoding='utf-8').read()
assert '## §344' not in t
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + '\n' + SECTION)
print('port-plan §344 added')
