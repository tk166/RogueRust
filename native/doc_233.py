"""§233 docs."""
import io

ROOT = 'D:/Vibe/sts-tui/'

SECTION = '''
---

## §233 `Entrench` + 一次"闸门红了 13 条"的完整定位（真正的 bug 在页面和驱动里）

`Entrench` 的载体很小（一个新节点），但这一节真正的产出是**定位**：上一轮我把 §233 撤回，因为
`ACT1_SLICE` 红了 13 条断言。这一节把它查清了 —— 结论是**这张牌没有错**，错的是页面的一处显示
和闸门驱动的一条读法。

### 233.1 载体：`node.setDefensivePool`

`Entrench`：`Double your Block.`（2 费，`+` 1 费，Uncommon）。

内核原来只有 `GainBlock`（**加**），没有"**设**"。新节点 `setDefensivePool {TargetSelector, PoolId,
Amount}`：每个目标直接写（不入队），`max` 传 `None` 保持原上限，负值响亮失败。

**`set` 与 `gain` 不是同一条规则**，这不是洁癖：判据里给英雄挂 1 层 `standard.frail`（格挡 -25%），
格挡 8 打 `Entrench` 之后必须是 **16**；用 `GainBlock` 写成"再加一份"的实现会给出 `8 + 6 = 14`。
这条判据是这节唯一能真正分开两种实现的（两端数字 7→14、0→0 两种实现都对）。

### 233.2 定位：13 条断言、四个被证伪的假设

上一轮的症状是 `boss seed=null` + 12 条拿不完整记录的断言。这一轮把假设逐个用**实验**杀掉：

| 假设 | 实验 | 结论 |
|---|---|---|
| 内核对 `multiply`/池子读取有 bug | 内容门 + 单测（7→14、0→0、脆弱不吃翻倍） | **否**，全过 |
| 那两行内容的数据写错了 | `sts-content` 对比 wiki dump | **否** |
| 只是"多两行"扰动了确定性彩票 | 把两行以 `Rarity: Basic` 加回（永不进牌组） | **PASS** ⇒ 内容本身无害 |
| 牌被拿到并且被误用 | 把每个失败尝试的**牌组**记进报告 | **否**：44 个牌组里**没有** `entrench` |

倒数第二条是关键陷阱：`Basic` 变体 PASS 而 `Uncommon` 变体 FAIL，而牌组里又**从没有**这张牌 →
说明差别不在"用错这张牌"，而在**奖励池变了**：多两行 Uncommon ⇒ 抽牌分布变了 ⇒ 牌组里出现
`skewer` / `malaise+` / `nightmare` 这类牌，而闸门的**固定驱动**不会用它们。

还有一个更基础的坑：我第一次做隔离实验时**没有重建 wasm**，而内容镜像是**编进 wasm** 的
（`content pin` 那行），于是"删掉内容行"根本没有生效 —— 白跑一次。**改内容必须重建 wasm**。

### 233.3 两个真 bug（都在页面/驱动里，不在引擎里）

1. **X 费牌的手牌角标显示 `-2`**。`render()` 打的是 `card.cost`，而 X 费牌的 `cost` 是 ABI 的
   **哨兵** `X_COST_DISPLAY = -2`（`ui_render.js` 早就给了 `costText: "X"`，页面没用它）。
   ⇒ 玩家在手里看到「-2」，而内核按"全部能量"结算。改成打 `costText`，并把 `data-cost` 加到
   手牌按钮上（下面那条要用）。
2. **驱动把 X 费牌当普通攻击**。`act1_slice` 的固定驱动用 `/damage/` 找攻击牌，于是 `Skewer`
   （"Deal 7 damage X times"）被当成一张普通攻击随手打出 —— 它花掉**全部能量**打一次；
   `Malaise` 落进"垃圾牌"桶，同样烧光能量。这不是"牌错了"，是驱动对**收尾牌**没有概念。
   现在驱动认出 `data-cost === "-2"`，只在能量 ≥ 3 时才考虑它们。

顺带把两条对"翻倍/倍数牌"的读法也放进去：**"提到 Block" ≠ "提供格挡"**（`/gain[^.]*block|intangible/`，
否则 `Entrench`、`Body Slam` 都会被当成救援牌），以及**倍数牌只在格挡已经够大时值那笔费**
（`cell(6) >= 10`）。这三条都与 §223 修"无形不算防守牌"同一类：**驱动对卡面的读法错了**。

### 233.4 判据

* `entrench_doubles_the_block_it_already_has` —— 7→14、0→0，**外加脆弱不吃翻倍**（8→16，不是 14）；
* `skewer_hits_once_per_energy_spent` —— 能量 3 打 3 次、能量 1 打 1 次（§232 欠的判据）；
* `malaise_spends_the_energy_on_strength_loss_and_weak` —— X=2 ⇒ -2 力量 / 2 层 Weak，
  `malaise+` ⇒ **X+1**（wiki 的 `(X;X+1)`），且两只都自消耗（§232 欠的判据）。

### 233.5 数字

* 单测 **938**（733 core + 110 run + 95 wasm，+3）；四个对拍不变（`FIGHT_DIFF 182/182`、
  `CARD_DIFF 62/62`、`CARD_MULTI 124/124`、`ENEMY_DIFF 394/394`）。
* 内容：卡 **117 行**（+2）、镜像 **92,644 B**（core 76,448）。
* 矩阵 **433 行**（+2）、扫描到的具名测试 **940**、wiki 对照 **47** 张。
* `MAX_POOL` 112 → 128（§232 就抬过；这一节只跟着内容走）。
'''

path = ROOT + 'docs/port-plan.md'
text = io.open(path, encoding='utf-8').read()
assert '## §233' not in text, 'already there'
io.open(path, 'w', encoding='utf-8', newline='\n').write(text.rstrip('\n') + '\n' + SECTION)
print('doc_233: appended %d bytes' % len(SECTION))
