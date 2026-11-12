"""P3 文档：port-plan §363 + README + docs/ui-p3-loop.md。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── 1. port-plan：§363 ───────────────────────────────────────────────────────
PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
anchor = '''---

## §362 X 费夹具'''
assert t.count(anchor) == 1

section = '''---

## §363 P3 交付：地图 → 战斗 → 奖励的闭环（场景由内核事实**算**出来）

plan P3 的退出条件是"从标题页走地图、打一场普通遭遇、正确领取奖励、继续地图；无隐藏手工
刷新步骤；所有 Snapshot 对账通过"。这一节记的是它**怎么做到的**，以及一路上修掉的**十个真 bug**
—— 其中七个是 P3 之前一直存在、只是没人从"没有战斗会话"或"画布不在视口原点"这两条路上走过。

### 363.1 场景是**算**出来的，不是记出来的

`web-next/src/run/scene.ts` 把 `docs/ui-state-model.md` 的 18 行表实现成一个**纯函数**
`resolveScene(内核事实) → { base, overlays, unknownPending }`。UI **没有** mode 变量：
每一帧都是"读导出 → 重算 → 画那一屏"，所以"刷新一下回到地图"这类 bug 在结构上不存在。

两条**顺序陷阱**写成数据（`SCENE_ORDER`）而不是 if 链，闸门 33 直接断言顺序：

| 陷阱 | 为什么 |
|---|---|
| `SC-03b` 在 `SC-03` 之前 | 两者都是 `pending == 0`，只有 `in_fight` 不同；反过来永远看不到战斗屏 |
| `SC-02b` 在 `SC-02` 之前 | `SC-02` 是兜底；反过来 `SC-02b` **永远不可达**（八轮 Review 3.1 的第二处） |

**覆盖层**（`SC-11a`/`SC-11b` 遗物欠账）不占 `base`：它们弹在原来那一屏之上，两者共用同一份事实。

`unknownPending`：相位不在 0..9 时兜底到地图，但界面**必须**显示诊断 —— 静默画地图会让
"内核加了新相位而 UI 没跟上"看起来正常。

### 363.2 新增的屏（`web-next/src/run/scenes/`）

| 屏 | 场景 | 交互设计要点 |
|---|---|---|
| `TitleScene` | SC-00 | 种子是数字输入框（可复现是硬要求）、进阶滑杆 0–20；**没有"继续"**（没有存档，假按钮就是骗人） |
| `BlessingScene` | SC-01 | 条数由内核给（§346 不许写死 2）；收益/代价用 `gain/cost` **判别值**翻人话；8 个 id 是内核闭集，表在本地 |
| `MapScene` | SC-02 | 只高亮**可达**；不可点节点**不是**灰按钮（灰按钮像 bug）而是给一句"这一步到不了"；"你在这里"标记；Boss 哨兵单独一行；连线用 SVG，布局用归一化坐标 |
| `PreCombatScene` | SC-03 | 显式"进入战斗"：战斗开始由权威 API 决定，**不靠 UI mode**；没有"撤退"（内核没这条路） |
| `CombatScreen` | SC-03b | 直接复用 P1/P2 那一份（抽成组件，闸门与玩家打的是**同一份**） |
| `RewardScene` | SC-04 | 拿牌用**内核槽位**；拿完重读（实测候选会清空）；`skip_reward` 才关屏 |
| `EndScene` | SC-12a/12b/02b | 局终说清**为什么**（`RunEnd` 判别值），给"再来一局" |
| `UnsupportedScene` | SC-05..10 等 | P4 之前的**诚实**做法：明说没做，并给一个**确实会推进**的按钮（`settleDefault`），日志留痕 |

顶栏常驻 HP/金币/层数/牌组/遗物/药水，**HP 永远显示运行层那一份** —— 战斗里回血了但顶栏
没动会当场变成一条对账失败，而不是等玩家截图才发现。对账失败 ⇒ 红条 + **冻结推进**。

### 363.3 闸门 33 `ui-scene`（纯函数，不需要浏览器）

* `SCENE_ORDER` 16 条 + 覆盖层 2 条，无重复、覆盖层不在 base 表里；
* 两处顺序陷阱各一条断言；
* `PENDING_SCENE` 恰好覆盖 1..9（`0` 不是相位）；
* **18 行表逐行夹具**（20 条，含 `?` 房掷出怪物/事件、事件里的战斗、已结算节点）；
* **穷尽性**：14976 组内核事实组合，**0 次抛异常**，`unknownPending` 只在相位越界时非空；
* 地图解码：出边是**全局**下标、布局归一化、`out_degree > 3` **响亮失败**；
* 运行层观察向量：19 格逐字段、七条 RNG 流按序、太短响亮失败。

### 363.4 闸门 34 `ui-next-loop`（端到端）

一条真实的闭环，**几乎每一步都是真 DOM 点击**：

```
SC-00 开始 → SC-01 祝福 → SC-02 地图 → 点节点 → SC-03 战斗前 → 进入战斗
→ SC-03b 战斗（一次真实 3D 拖拽）→ 领取奖励 → SC-04 奖励（拿牌）→ 继续 → SC-02 地图
```

证据串：`UI_NEXT_LOOP PASS nodes=70 steps=18 scene-chain=SC-00>SC-01>SC-02>SC-03>SC-03b>SC-04>SC-02`

其中值得单独说的三条：

1. **真实 3D 目标拾取**：CDP 发真的 `Input.dispatchMouseEvent`（按下 → 6 步移动 → 抬起），
   断言"**只有被指的那个敌人**掉血、其余一点没掉"。坐标来自 `window.__p1.layout()`（P1 每帧
   投影的真值），不自己从 3D 推像素。
2. **不刷新页面场景判定仍然稳定**：把"没有隐藏的手工刷新步骤"钉在可观察层面。
3. **每个阶段都对账**：`violations()` 必须为空（HP/金币/牌组数/遗物数/药水数/会话存在性）。

### 363.5 这一路修掉的十个真 bug

| # | bug | 判据/教训 |
|---|---|---|
| 1 | `hasCombatSession()` 用 `rd_env_active_slot() !== -3`，而内核 `ensure_session()` 会**懒建**会话 | 装载后就被判成"在战斗"，解码出一条**幽灵战斗**（2 敌 5 牌）。P2 从没发现，因为它总是先 `fight_begin`。判据只能是 `rd_run_in_fight() == 1` |
| 2 | `SC-03` 没要求"这一格**还没结算**" | 领完奖励 `pending` 回到 0、`kind` 仍是 `Combat` ⇒ 判成"战斗前"，点下去内核拒绝。**判据是"这一格还在等我"而不是"这一格是战斗"** |
| 3 | `rd_run_fight_end()` 返回的是**战斗结果**（1=胜利），不是 `0=成功` | 每一场胜利都被记成"战斗结算失败（code 1）" |
| 4 | `rd_run_begin_node()` 返回 `0`/`-2`，**不是**节点 kind | 日志每一格都写"进入节点：未分配" |
| 5 | `buildMap` 先 `Math.min(3, out_degree)` 再比 `> 3` | 断言**永远不可能成立**（守卫装在切口**下游**，§4.19 的又一例）。闸门 33 一跑就红 |
| 6 | `layout()` 给的是**画布局部**坐标，而指针事件是**视口**坐标 | P1/P2 回归页画布铺满视口 ⇒ 一直没暴露；运行层顶栏占了 44px ⇒ 真玩家拖拽与闸门的 3D 拾取全偏 44px |
| 7 | `RunStore` 没订阅 `GameStore` | `CombatScreen` 直接调 `GameStore.dispatch`，于是出牌后顶栏能量/HP、对账用的 `state.combat` 全停在"战斗开始前"（闸门实测：beat 播了"敌人 0 −6 血"，但 `__run.hand()` 里敌人还是 28 血） |
| 8 | `.app { height: 100% }` 在 flex 容器里解析成 `auto` | 战斗画布只剩 **150px** 高，手牌被压成一条缝 |
| 9 | 奖励屏注释说"拿一张后候选不变" | 实测**会清空**（与 StS 一致）—— 注释错会诱导下一个人写"本地标记已拿"的漂移逻辑 |
| 10 | 没有 `rd_run_relic_count` 这个导出 | 遗物必须读到 `-1` 为止；第一版调了个不存在的函数，装载后第一次刷新就抛 |

### 363.6 数字

闸门 32 → **34**；`ui-scene` 14976 组穷尽 + 20 条夹具；`ui-next-loop` 70 节点 / 18 步战斗；
units 1233、导出 234、四条对拍不动。

### 363.7 还欠的（P4）

商店/篝火/宝箱/事件/事件选牌/祝福选牌六屏；运行层里**喝药水**；幕间切换（`end_act`）；
牌组弹窗目前**只读**（不能删/升级）；`SC-02b` 在当前内容下仍不可达（地图走完即 `RunEnd`）。

---

## §362 X 费夹具'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, section))

# ── 2. README ────────────────────────────────────────────────────────────────
edit(
    'README.md',
    '''**聚合验收**：32 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice`、`ui-wasm-fixtures` 与 `ui-wasm-xcost`），一道红就整体红''',
    '''**聚合验收**：34 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice`、`ui-wasm-fixtures`、`ui-wasm-xcost`、`ui-scene` 与 `ui-next-loop`），一道红就整体红''',
    'readme gates',
)

# ── 3. 新文档 ────────────────────────────────────────────────────────────────
doc = '''# P3 运行层：场景路由与交互设计

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
'''

io.open('docs/ui-p3-loop.md', 'w', encoding='utf-8', newline='\n').write(doc)
print('docs written')
