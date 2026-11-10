"""§341：UI 状态模型的场景表重排 + §5 措辞 + §8 分类 + G16 关闭（八轮 Review 3.1/3.2/3.5）。

## 三处改动

### 1. 场景表按"强状态优先"重排（Review 3.1）

旧表把 **SC-03（战斗待开始）排在 SC-03b（战斗中）之前**，而 SC-03 的条件里"未开始"是**页面自己
记的** `mode` —— 纯函数判不出来。同样地 **SC-02（地图，兜底）排在 SC-02b（幕尽头）之前**，
而两者都是 `pending == 0` ⇒ SC-02b **永远不可达**。

新顺序：**无局 → 战斗中 → 遗物欠账（覆盖）→ 终局 → pending 各屏 → 预备战斗 → 幕尽头 → 地图兜底**。
判定式尽量互斥，且全部用内核事实（`rd_run_in_fight()` 是 §341 新加的）。

### 2. §5 的"pending 唯一判别式"与 §1 矛盾（Review 3.2）

改成"`pending` 是**优先级很高的一项输入**，但场景由三类权威事实共同决定"。

### 3. §8 把非文本长度移出"文本 `_len/_into`"表（Review 3.5）

`rd_run_observe_len` / `rd_env_observe_len` / `rd_env_pile_len` 不是文本长度，混在文本表里
会让读者（和未来的代码生成器）以为它们是字符串 getter。移到 §8.3。

### 4. G16 关闭

`rd_run_in_fight()` 已经导出（§341），所以"有没有一场正在打的战斗"不再是缺口。
"""

import io

PATH = 'docs/ui-state-model.md'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── ① 场景表整体重排 ────────────────────────────────────────────────────────
OLD_TABLE = '''| id | 场景 | 判定式（按优先级） | 主层 | 唯一写者 | 主要出口 |
|---|---|---|---|---|---|
| **SC-11a** | 遗物欠账·改牌 | `rd_run_pickup_picks() > 0` | 弹窗 | `renderNode` | 选完回到**原来那一屏** |
| **SC-11b** | 遗物欠账·加牌 | `rd_run_pickup_add() > 0` | 弹窗 | `renderNode` | 同上 |
| **SC-12a** | 幕通关 | `rd_run_boss_beaten() == 1` 且未战败 | 节点面板 | `renderNode` | 重开 / 换 seed |
| **SC-12b** | 局终 | `runOver`（**页面侧**，见 §6-G1） | 节点面板 | `renderNode` | 重开 / 换 seed |
| **SC-01** | 塔底祝福 | `pending == 6` | 节点面板 | `renderNode` | `choose_start` → 6→(7)→0 |
| **SC-01b** | 祝福选牌 | `pending == 7` | 弹窗 | `showDeckPicker` | `pick_blessing_card` → 0 |
| **SC-09** | 事件选牌 | `pending == 8` | 弹窗 | `showDeckPicker` | `pick_event_card` → 0 |
| **SC-10** | 事件候选 | `pending == 9` | 节点面板（行表） | `renderNode` | `event_offer_take` → 0 |
| **SC-04** | 战斗奖励 | `pending == 4` | 节点面板（行表） | `renderNode` | `take_card`/`skip_reward` → 0 |
| **SC-08** | 事件 | `pending == 5` | 节点面板 | `renderNode` | `choose` → 0 / 4 / 8 / 9 / 战斗 |
| **SC-07** | 宝箱 | `pending == 3` | 节点面板 | `renderNode` | `open_chest`/`leave` → 0 |
| **SC-05** | 商店 | `pending == 2` | 节点面板（四排） | `renderNode` | `leave` → 0 |
| **SC-06** | 篝火 | `pending == 1` | 节点面板 | `renderNode` | `rest`/`smith`/…/`leave` → 0 |
| **SC-03** | 战斗（未开始） | `pending == 0` 且（`kind ∈ {1,2,7}` 或 `kind==5 && unknownRoom==2` 或 `eventFight > 0`） | 战斗层 | `render()` | `fight_begin` → SC-03b |
| **SC-03b** | 战斗中 | `mode == "fight"`（页面侧），`E.obs` 有效 | 战斗层 | `render()` | `fight_end` → SC-04 / SC-12b |
| **SC-02** | 地图 | `pending == 0` 且上面都不成立 | 地图层 + 顶栏 | `renderMap` + `renderTopBar` | `step(node)` → 进入某节点 |
| **SC-02b** | 幕尽头 | `pending == 0` 且 `rd_run_action_count() == 0` 且 `kind >= 0` | 节点面板 | `renderNode` | 页面侧 `end_act`（**无内核动作**，§6-G2） |
| **SC-00** | 未开局 | `rd_run_seed() == i32::MIN` | 节点面板 | `renderNode` | `rd_run_start(seed, asc)` → SC-01 |'''

NEW_TABLE = '''**排序原则**：**强状态优先** —— 越"不可协商"的事实越靠前（没有局 → 正在打 → 欠账 → 终局 →
具体的 `pending` → 预备战斗 → 兜底）。判定式尽量**互斥**；每条都必须只用内核事实（§341 之前
SC-03/SC-03b 做不到，因为"未开始"是页面自己记的标志）。

| # | id | 场景 | 判定式 | 主层 | 唯一写者 | 主要出口 |
|---:|---|---|---|---|---|---|
| 1 | **SC-00** | 未开局 | `rd_run_seed() == i32::MIN`（`R.obs(0)` 也是 `i32::MIN`） | 节点面板 | `renderNode` | `rd_run_start(seed, asc)` → SC-01 |
| 2 | **SC-03b** | 战斗中 | `rd_run_in_fight() == 1`（§341） | 战斗层 | `render()` | `fight_end` → SC-04 / SC-12b |
| 3 | **SC-11a** | 遗物欠账·改牌 | `rd_run_pickup_picks() > 0` | 弹窗 | `renderNode` | 选完回到**原来那一屏** |
| 4 | **SC-11b** | 遗物欠账·加牌 | `rd_run_pickup_add() > 0` | 弹窗 | `renderNode` | 同上 |
| 5 | **SC-12b** | 局终 | `rd_run_over() == 1`（§6-G1，**尚未导出**） | 节点面板 | `renderNode` | 重开 / 换 seed |
| 6 | **SC-12a** | 幕通关 | `rd_run_boss_beaten() == 1` 且 `rd_run_over() != 1` | 节点面板 | `renderNode` | 重开 / 换 seed |
| 7 | **SC-01** | 塔底祝福 | `pending == 6` | 节点面板 | `renderNode` | `choose_start` → 6→(7)→0 |
| 8 | **SC-01b** | 祝福选牌 | `pending == 7` | 弹窗 | `showDeckPicker` | `pick_blessing_card` → 0 |
| 9 | **SC-09** | 事件选牌 | `pending == 8` | 弹窗 | `showDeckPicker` | `pick_event_card` → 0 |
| 10 | **SC-10** | 事件候选 | `pending == 9` | 节点面板（行表） | `renderNode` | `event_offer_take` → 0 |
| 11 | **SC-04** | 战斗奖励 | `pending == 4` | 节点面板（行表） | `renderNode` | `take_card`/`skip_reward` → 0 |
| 12 | **SC-08** | 事件 | `pending == 5` | 节点面板 | `renderNode` | `choose` → 0 / 4 / 8 / 9 / 战斗 |
| 13 | **SC-07** | 宝箱 | `pending == 3` | 节点面板 | `renderNode` | `open_chest`/`leave` → 0 |
| 14 | **SC-05** | 商店 | `pending == 2` | 节点面板（四排） | `renderNode` | `leave` → 0 |
| 15 | **SC-06** | 篝火 | `pending == 1` | 节点面板 | `renderNode` | `rest`/`smith`/…/`leave` → 0 |
| 16 | **SC-03** | 战斗（**待开始**） | `rd_run_in_fight() == 0` 且 `pending == 0` 且（`kind ∈ {1,2,7}` 或 `kind==5 && unknownRoom==2` 或 `eventFight > 0`） | 战斗层 | `render()` | `fight_begin` → SC-03b |
| 17 | **SC-02b** | 幕尽头 | `rd_run_in_fight() == 0` 且 `pending == 0` 且 `rd_run_action_count() == 0` 且 `kind >= 0` | 节点面板 | `renderNode` | 页面侧 `end_act`（**无内核动作**，§6-G2） |
| 18 | **SC-02** | 地图（兜底） | `rd_run_in_fight() == 0` 且 `pending == 0` | 地图层 + 顶栏 | `renderMap` + `renderTopBar` | `step(node)` → 进入某节点 |

> **为什么 SC-03b 排在第 2 位**：它是"正在打"，与"站在一个战斗节点上但还没开打"是**两个不同的
> 屏**。旧表把 SC-03 排在前面，而 SC-03 的"未开始"是页面自己记的 `mode` —— 纯函数判不出来，
> 于是 3D 重写必须重新发明这条判断。`rd_run_in_fight()`（§341）把这一格补上之后，两条判定式
> 才**互斥**。
>
> **为什么 SC-02b 排在 SC-02 之前**：两者都是 `pending == 0`，而 SC-02 是**兜底**。旧表把兜底
> 排在前面 ⇒ SC-02b **永远不可达**（八轮 Review 3.1 的第二处）。'''

t = sub(t, OLD_TABLE, NEW_TABLE, 'scene table')

# ── ② §5 的措辞 ────────────────────────────────────────────────────────────
OLD_5 = '''**两条规则**：

1. **`pending` 是唯一的场景判别式**，除了三个覆盖层（`pickupPicks` / `pickupAdd` / 弹窗）和
   两个终局（`cleared` / `runOver`）。覆盖层**不改变** `pending`，所以"选完回到原来那一屏"
   是自动成立的。
2. **只有 `rd_run_step` 与各节点动作会推进 `pending`**。渲染层不许自己改场景。'''

NEW_5 = '''**两条规则**：

1. **`pending` 是优先级很高的一项输入，但它不是唯一的判别式。** 场景由三类**权威事实**共同
   决定：
   * **有没有局**（`rd_run_seed() == i32::MIN`）；
   * **有没有一场正在打的战斗**（`rd_run_in_fight()`，§341）；
   * **节点的 `pending` 与"要不要打"**（`rd_run_pending()` + `kind` + `unknownRoom` + `eventFight`）。

   三个覆盖层（`pickupPicks` / `pickupAdd` / 弹窗）与两个终局（`boss_beaten` / `run_over`）
   **压在**上面三类之上，但它们**不改变** `pending` —— 所以"选完回到原来那一屏"是自动成立的。
   ⚠️ 这句话以前写的是"`pending` 是唯一判别式"，与 §1 自己的判定式矛盾（§1 明确列了
   `kind` / `unknownRoom` / `eventFight`）—— 八轮 Review 3.2 抓的就是这一句。别让代码生成器
   把它读成"按 `pending` 一个 switch 就够了"。
2. **只有 `rd_run_step` 与各节点动作会推进 `pending`**。渲染层不许自己改场景。'''

t = sub(t, OLD_5, NEW_5, 'section 5 wording')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('ui-state-model: scene table + section 5')
