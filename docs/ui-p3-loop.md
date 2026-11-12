# P3 运行层：场景路由与交互设计

> 代码在 `web-next/src/run/`，闸门 33（纯函数）与 34（端到端）。
> 场景语义的**权威**是 `docs/ui-state-model.md` 的 18 行表；这一份讲**实现与交互**。

## 1. 一条纪律：屏幕是算出来的

```
内核导出 ──► RunStore.refresh() ──► resolveScene(事实) ──► 画那一屏
                    ▲
            玩家的每个动作（enter_node / fight_begin / take_card …）
```

**没有 `mode` 变量。** 所以"刷新页面回到地图""战斗结束了但界面没跟上"在结构上不存在。
`RunStore` 是运行层的**唯一写入者**；组件只读 `getState()` 与 `subscribe()`。

## 2. 场景表（实现）

| 场景 | 判据（全部来自内核） | 组件 |
|---|---|---|
| `SC-00` | `!rd_run_exists()` | `TitleScene` |
| `SC-01` | `pending == 6` | `BlessingScene` |
| `SC-02` | 兜底（`pending == 0`） | `MapScene` |
| `SC-02b` | `pending == 0 && actionCount == 0 && nodeKind >= 0` | `EndScene` |
| `SC-03` | `pending == 0 && !in_fight && !node_resolved && 这一格会开战` | `PreCombatScene` |
| `SC-03b` | `in_fight && 战斗会话在` | `CombatScreen`（P1/P2 同一份） |
| `SC-04` | `pending == 4` | `RewardScene` |
| `SC-05..10` | `pending == 2/1/3/5/8/9` | `UnsupportedScene`（P4） |
| `SC-11a/b` | `pickup_picks > 0` / `pickup_add > 0` | 覆盖层 |
| `SC-12a/b` | `boss_beaten` / `over == 1` | `EndScene` |

`SC-03` 的 `!node_resolved` 是**必须**的一半：打完的格子 `kind` 仍然是 `Combat`，少了它会
把"已经打完的格子"又画成"进入战斗"（§363.5 的第 2 条）。

## 3. 交互设计（为什么这样）

### 3.1 地图

* **只高亮可达**，其余不可点。不可点**不是**灰按钮（灰按钮看起来像 bug），点了给一句
  "这一步到不了"，并在日志里留一行。
* **单击就走**：可点集合只有 2–6 个，内核还会再校验一次；多一次确认只让每一步变慢。
* **"你在这里"**：打完一场回来必须一眼找到自己。
* **向上滚动**（第 1 行在底部）、**Boss 哨兵单独一行**。
* **高亮边 = 从当前节点出发、且目标可达**的那条（"你现在能走的这一步"）。开局还没出发时
  没有当前节点 ⇒ 0 条高亮边，靠可达节点自身的呼吸环提示。

### 3.2 顶栏

常驻 HP / 金币 / 层数 / 牌组 / 遗物 / 药水。**HP 永远显示运行层那一份**：战斗里的 148 格向量
是战斗内权威，但顶栏与对账都用运行层 —— 两边不一致会**当场**变成一条对账失败。

### 3.3 对账与"响亮失败"

`RunStore.reconcile()` 只比**能独立读两次**的东西：

* 战斗上限 == 运行层上限（**战斗中**不比起 HP：战斗结算才写回，§363.5）；
* 牌组数 / 遗物数 / 药水数 == 各自列表的实际长度；
* 场景说"在战斗"就必须真有会话，反之亦然；
* 场景说"战斗前"，这一格就必须真的会开战；
* `unknownPending !== null` 本身就是一条违约。

非空 ⇒ 顶部红条 + **冻结推进**（地图不可点、按钮禁用）。这不是"显示小错"，是 ABI 违约。

### 3.4 P4 之前怎么不卡住

商店/篝火/宝箱/事件都还没有界面。做法是**明说**，并给一个**确实会推进**的按钮
（"用内核的默认动作通过" → `settleDefault()`），日志留一行。空白页与静默自动跳过都不行：
前者像卡死，后者等于 UI 偷偷替玩家做决定。

## 4. 探针（闸门读这里）

`window.__run`：`scene()` / `run()` / `map()` / `inventory()` / `reward()` / `blessings()` /
`violations()` / `combat()` / `hand()` / `log()` / `debug()`，以及每个动作一份（`start` /
`choose` / `enter` / `fightBegin` / `fightEnd` / `takeCard` / `skipReward` / `settleDefault` /
`play` / `endTurn`），外加 `click(selector)`（**真 DOM 点击**）与 `domScene()`（画出来的那一屏）。

⚠️ 探针里**没有** `setScene` 这类钩子：P3 的退出条件正是"没有隐藏的手工刷新步骤"，
一个能直接改场景的钩子会让闸门绕过整个路由。

## 5. 两个页面

| 页面 | 用途 | 谁在打 |
|---|---|---|
| `index.html`（`src/App.tsx`） | P1/P2 **回归页**：装载 → 自动走到第一场战斗 | 闸门 25–32 |
| `run.html`（`src/run/RunApp.tsx`） | **产品路径**：标题 → 祝福 → 地图 → 战斗 → 奖励 → 地图 | 闸门 33/34 与玩家 |

战斗屏是**同一个组件**（`src/combat/CombatScreen.tsx`），参数化成 `mode: "auto" | "mock" | "wasm"`。
分开写两份手势接线会让"闸门测的那份"和"玩家用的那份"漂开 —— 那是假绿最坏的一种。
