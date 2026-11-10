# UI 状态模型 —— 场景 × 层级 × 字段 × 接口

> **这份文档为谁写**：假定界面要**整个重写**（Live2D / Three.js），而不是继续用 `web/` 那套
> DOM。它回答三个问题：
>
> 1. 一共有哪些**场景**，每个场景里有哪些**层**，每层显示哪些**字段**；
> 2. 每个字段的**取值域**、**什么时候变**、**变了之后要不要重画**；
> 3. 每个字段今天**从哪个 wasm 导出**读，以及**读不到**的部分是什么。
>
> **判据：表里每一行都必须指到一个真实存在的导出。** 指不到的行写进 §6（缺口），
> 不许在渲染层里"顺手算一下" —— 那就是第二条 `restHeal`。
>
> 相关文档：`docs/spec/env-abi.md`（ABI 的**定义**）、`docs/spec/ui-plan.md`（页面**为什么**长这样）、
> `docs/sts-wiki-gap.md`（**内容**差什么）。这份文档只管"状态从哪来、长什么样"。

---

## 0. 三个词与五条硬规则

### 0.1 三个词

| 词 | 定义 | 例 |
|---|---|---|
| **场景 SCENE** | 玩家**一次只能看到一屏**的东西。切换靠一个离散事件（一次 `act`/`step`），没有中间态 | 地图、战斗、商店、奖励 |
| **层 LAYER** | 一个场景里**独立变化**的空间单位。层的边界 = "谁负责重画它" | 战斗 = 背景层 / 敌人站位层 / HUD 层 / 手牌层 / 浮字层 / 弹窗层 |
| **字段 FIELD** | 一个可观察量，**有一个唯一来源** | `enemy[2].hp` |

层的意义就是 `port-plan.md` §89/§90 的**一个元素一个写者**：`#nodePanel` 只由 `renderNode` 写，
`#msg` 只由 `say()` 写。3D 里这条规则不变，只是"元素"换成"节点/材质/骨骼"。

### 0.2 两条 ABI 通路

| 通路 | 前缀 | 用途 | 状态载体 |
|---|---|---|---|
| **运行层** run | `rd_run_` 前缀 | 地图、牌组、金币、遗物、商店、事件、奖励 | 19 格向量 `rd_run_observe(i)` + 大量文本/计数导出 |
| **战斗层** combat | `rd_env_` 前缀 | 一场战斗里的英雄/敌人/手牌/能量/状态/待决问句 | 148 格向量 `rd_env_observe(i)` + 文本导出 + **动画 beat 流** |

两层的边界是 `rd_run_fight_begin` / `rd_run_fight_end`：**战斗只有"结果"回到运行层**
（§163），所以"战斗中的血量"必须读 `E.obs(4)`，而"运行层的血量"在战斗结束前是**旧的**
（`renderTopBar` 里那条注释就是踩过的坑）。

### 0.3 记号

| 记号 | 含义 |
|---|---|
| `R.obs(i)` | `rd_run_observe(i)` |
| `E.obs(i)` | ⚠️ **没有 `rd_env_observe(i)` 这个导出**。走 `rd_env_observe_buf()` 拿地址 + `rd_env_observe_len()` 建 `Int32Array` 零拷贝，或 `rd_env_observe_into(ptr)` 复制到自己的缓冲区 |
| `R.txt(x)` | 一对 `<名>_len(...)` / `<名>_into(..., ptr)`（都是 `rd_run_` 前缀，如 `rd_run_deck_title_len`） |
| `E.txt(x)` | 同上，`rd_env_` 前缀（如 `rd_env_enemy_name_len`） |
| `i32::MIN` | "没有局"（run 侧向量越界/无会话的统一哨兵） |
| `-1` | "这一格不适用"（combat 侧；**不是 0**，0 是真实值） |

### 0.4 五条硬规则

| # | 规则 | 违反的后果（历史） |
|---|---|---|
| **R1** | **一个字段一个来源**。派生值**读取时**从状态派生，不缓存 | `#nodePanel` 两个写者 → 点地图把按钮擦掉，只能刷新 |
| **R2** | `-1` 是"没有/不适用"，**不是 0**。0 是"0 点格挡 / 0 层" | 把 `intent_damage = -1` 印成 "0 伤害" |
| **R3** | **"要不要画这个按钮"必须来自内核**（位掩码/计数/长度），不许页面推 | 篝火六个选项、"买"按钮、`+2 上限` 都曾画成死按钮 |
| **R4** | 槽号一律用**内核给的**那个数，不是数组下标 | §161.8 拿 `position` 当 `slot`，`take_card` 永远被拒 |
| **R5** | **状态改了没重渲染 = 玩家看不见**。3D 里对应"每帧从状态取，不是事件里改材质" | `givePotion` 只写状态，页面报"没有用按钮" |

**R5 是 Live2D/Three.js 重写时最容易翻的一条**：DOM 版本靠 `innerHTML` 整体重画，
3D 版本会想"只在 beat 里改"。规矩是：**beat 只驱动演出，不驱动事实**；每帧（或每次 act 之后）
从向量重新取事实。

---

## 1. 场景总表

判定式按**优先级从上到下**（`RD_PANELS.describe` 的顺序就是这张表）。同一时刻可能有多条成立，
**先成立的赢**。

**排序原则**：**强状态优先** —— 越"不可协商"的事实越靠前（没有局 → 正在打 → 欠账 → 终局 →
具体的 `pending` → 预备战斗 → 兜底）。判定式尽量**互斥**；每条都必须只用内核事实（§341 之前
SC-03/SC-03b 做不到，因为"未开始"是页面自己记的标志）。

| # | id | 场景 | 判定式 | 主层 | 唯一写者 | 主要出口 |
|---:|---|---|---|---|---|---|
| 1 | **SC-00** | 未开局 | `rd_run_seed() == i32::MIN`（`R.obs(0)` 也是 `i32::MIN`） | 节点面板 | `renderNode` | `rd_run_start(seed, asc)` → SC-01 |
| 2 | **SC-03b** | 战斗中 | `rd_run_in_fight() == 1`（§341） | 战斗层 | `render()` | `fight_end` → SC-04 / SC-12b |
| 3 | **SC-11a** | 遗物欠账·改牌 | `rd_run_pickup_picks() > 0` | 弹窗 | `renderNode` | 选完回到**原来那一屏** |
| 4 | **SC-11b** | 遗物欠账·加牌 | `rd_run_pickup_add() > 0` | 弹窗 | `renderNode` | 同上 |
| 5 | **SC-12b** | 局终 | `rd_run_over() == 1`（§344 已导出；`rd_run_over_why()` 说为什么） | 节点面板 | `renderNode` | 重开 / 换 seed |
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
| 17 | **SC-02b** | 幕尽头 | `rd_run_in_fight() == 0` 且 `pending == 0` 且 `rd_run_action_count() == 0` 且 `kind >= 0`。⚠️ **当前内容不可达**（§6 末尾） | 节点面板 | `renderNode` | `rd_run_end_act()`（§344 起是内核动作） |
| 18 | **SC-02** | 地图（兜底） | `rd_run_in_fight() == 0` 且 `pending == 0` | 地图层 + 顶栏 | `renderMap` + `renderTopBar` | `step(node)` → 进入某节点 |

> **为什么 SC-03b 排在第 2 位**：它是"正在打"，与"站在一个战斗节点上但还没开打"是**两个不同的
> 屏**。旧表把 SC-03 排在前面，而 SC-03 的"未开始"是页面自己记的 `mode` —— 纯函数判不出来，
> 于是 3D 重写必须重新发明这条判断。`rd_run_in_fight()`（§341）把这一格补上之后，两条判定式
> 才**互斥**。
>
> **为什么 SC-02b 排在 SC-02 之前**：两者都是 `pending == 0`，而 SC-02 是**兜底**。旧表把兜底
> 排在前面 ⇒ SC-02b **永远不可达**（八轮 Review 3.1 的第二处）。

> **`pending` 完整取值域**（`rd_run_pending`，`Pending` 判别值）：
> `0` 无待决 · `1` 篝火 · `2` 商店 · `3` 宝箱 · `4` 奖励 · `5` 事件 · `6` 祝福 ·
> `7` 祝福选牌 · `8` 事件选牌 · `9` 事件候选 · `-1` 没有局。
>
> ⚠️ **`pending == 0` 不等于"地图"**：战斗节点、`?` 房掷出怪物、事件引来的伏击都是 `pending == 0`
> 而**要打一场**。判定靠 `kind` + `unknownRoom` + `eventFight` 三格（§3.3）。

---

## 2. 全局层（任何场景都在）

### 2.1 顶栏 HUD

| 字段 | 域 | 何时变 | 接口 | 驱动 | 坑 |
|---|---|---|---|---|---|
| `act` | `0..3` | 走过 Boss | `rd_run_act()` | T1 | 变大 ⇒ 播幕间幕布。**不许把局部变量叫 `act`**（会盖掉执行助手 `act()`） |
| `floor` | `0..16` | 进节点 | `R.obs(0)` | T2 | `0` = 还没出发 |
| `hp` / `hpMax` | `0..hpMax` / `1..` | 战斗内每 beat | **战斗中** `E.obs(4)` / `E.obs(5)`；否则 `R.obs(2)` / `R.obs(3)` | T2/T3 | ★ 战斗里读 `R.obs(2)` 会一直满血（运行层只在 `fight_end` 折回） |
| `gold` | `0..999` | 买卖 / 事件 | `R.obs(4)` | T2 | |
| `deckCount` | `0..` | 加减牌 | `rd_run_deck_count()` | T2 | |
| `relicCount` | `0..` | 拾取 | `R.obs(6)` | T2 | |
| `ascension` | `0..20` | 开局定死 | `rd_run_ascension()` | T0 | 显示**这一局**的等级，不是输入框里的 |
| `seed` | 任意 i32 | 开局定死 | `rd_run_seed()` | T0 | |
| `wingBoots` | `0..3` | 每次飞行 | `rd_run_wing_boots()` | T2 | `0` 时整段不显示（既有判据比字符串） |
| `enemyOverflow` | `0/1` | 开战时定死 | `rd_env_enemy_overflow()` | T1 | `1` ⇒ 观察向量装不下，必须**说出来**，不许静默只画 6 个 |
| `forcedTurns` | `0..` | 回合被强行结束 | `rd_env_forced_turns()` | T2 | 变大 ⇒ 报"时间扭曲"。观察向量**故意不携带**这个事实 |
| `contentPin` | 8 位十六进制 | 构建时定死 | `rd_content_fingerprint()` | T0 | 与 `packages/sts/out/build.json` 的镜像 sha 同源 |
| `runOver` | `0/1` | 血量归零 / 幕尽 / 通关 | `rd_run_over()` | T2 | §344：**不要自己记**（曾经是页面的一对模块级变量） |
| `runEndWhy` | `0` 进行中 / `1` 战败 / `2` 通关 / `3` 地图走完了 | 同上 | `rd_run_over_why()` | T2 | 数值是 `RunEnd` 的判别值，**不要重排** |

**遗物条**（`relicCount` 个 chip）：

| 字段 | 接口 | 备注 |
|---|---|---|
| `relicName(i)` | `R.txt(relic_name, i)` | 显示名（`REL.DisplayName`，回退 id） |
| `relicId(i)` | `R.txt(relic_id, i)` | 规则键；**`singing_bowl` 的判据必须用它**（§6-G3） |

**药水腰带**（3 格，`rd_run_potion_count()` 个）：

| 字段 | 接口 | 备注 |
|---|---|---|
| `potionId(i)` | `R.txt(potion_id, i)` | ⚠️ **没有显示名导出**（§6-G4） |
| `effect(i)` | `rd_run_potion_effect(i)` | `0` 未知 / `1` 需要敌人目标 / `2` 作用于英雄或运行层 / `3` 全体敌人 / `-1` 没有这一格 |
| `needsFight(i)` | `rd_run_potion_needs_fight(i)` | `1` = 只在战斗中可用 |
| 使用 | `rd_env_use_potion(slot, targetSlot)` | `targetSlot = -1` = 不需要目标 |
| 丢弃 | `rd_run_drop_potion(slot)` | |

> ★ `effect == 1` **且** `E.obs(11) > 1` 时才进入"点敌人"的子状态；`effect == 2/3` 不需要目标。
> 这条判断今天在页面里，但它的两个输入都来自内核，所以是**数据**，不是规则（符合 R3）。

**牌堆计数**（只在战斗中有效）：`rd_env_pile_len(zone)`，`zone`：`0` 抽牌堆 / `1` 弃牌堆 / `2` 消耗堆。

| 字段 | 域 | 接口 | 备注 |
|---|---|---|---|
| `frozenEye` | `0/1` | `rd_env_frozen_eye()` | §305：抽牌堆视图要不要按**真实顺序**显示。`0` ⇒ 牌堆浏览器按名字排序，`1` ⇒ 按抽牌顺序。★ 它**只改视图**，不改牌堆 |

### 2.2 消息行（`#msg`）

一行富文本，唯一写者 `say()`。内容来源：动作被拒的原因 `R.txt(last_error)` / `E.txt(last_error)`、
地图可达数、战斗的 `verdict`/`reward`。**3D 里它是一条 toast 通道**，不是层。

### 2.3 幕间幕布（`#actCurtain`）

| 字段 | 域 | 接口 |
|---|---|---|
| `act` | `1..3` | `rd_run_act()` |

纯演出，1.6 秒自动淡出。触发条件是"`act` 变大"（T1），**不需要**任何新导出。

### 2.4 弹窗层（`#modal`）

牌组浏览、牌堆浏览、卡牌详情、选牌（祝福/事件/拾取/删卡/打铁/抽烟斗）。见 §3.14。
唯一关闭入口 `closeModal()`，且**有待决选牌时它直接返回**（§161.5）。

### 2.5 浮字 / 动画 / 音效

事实来自向量差分（`diffObservations`），**顺序**来自 beat 流（§4）。3D 里这一层的输入是
`animationPlan` 的等价物：`{effect, at, text, damage/heal}`，其中 `at ∈ {"hero", "enemy:slot"}`。

### 2.6 脚本与存档栏（`#scriptBar` / `#archiveBar`）

| 动作 | 接口 | 返回值 |
|---|---|---|
| 导出脚本 | `rd_run_script_capacity()` → `rd_run_script_fill()` → 读 `rd_run_script_buf()` | 长度；`-2` = 战斗中没有脚本 / 哈希算不出 / 超容 |
| 回放 | `rd_run_replay_from(ptr, len)` | `0` 全对 / `n` 第 n 步分叉 / `-2` 读不懂 |
| 回放证据 | `rd_run_replay_checked()` / `rd_run_replay_diverged()` | 步数 / 分叉步号 |
| 存档 | `rd_run_archive_capacity()` → `rd_run_archive_fill()` → `rd_run_archive_buf()` | 长度 |
| 读档 | `rd_run_restore_from(ptr, len)` | `0` / `-2` |

> 这一层是**调试/取证**，3D 重写时应当整层保留（它是唯一能证明"同一串动作 ⇒ 同一局"的东西），
> 但可以做成开发者面板。

### 2.7 驱动方式 T0–T4（给 3D 用）

| 记号 | 含义 | 3D 对应 |
|---|---|---|
| **T0** | 会话级：开局/构建时定死 | 进场景时读一次，存进场景上下文 |
| **T1** | 场景级：换屏一次 | 换场景时读一次 |
| **T2** | 动作级：每次 `act`/`step` 之后 | 每次动作后重建"事实快照"，再交给渲染 |
| **T3** | 演出级：每个 beat | 事件驱动，可在一帧里出现多个 |
| **T4** | 连续级：需要插值 | **今天没有**（§6-G10），3D 必须自己补间 |

---

## 3. 逐场景

### 3.0 运行层向量 `R.obs(i)`（19 格，`env-abi.md` §11.3）

| i | 字段 | 域 | 何时变 | 3D 用途 |
|---:|---|---|---|---|
| 0 | `floor` | `0..16`（0 = 未出发） | 进节点 | 顶栏、地图高亮 |
| 1 | `node` | 全局节点下标，`-1` = 未出发 | 进节点 | 地图"我在哪" |
| 2 | `health` | `0..health_max` | 战斗结束后折回、事件、篝火 | 顶栏（**非战斗**时） |
| 3 | `health_max` | `1..` | 事件/遗物 | 顶栏、血条分母 |
| 4 | `gold` | `0..999` | 买卖、事件、奖励 | 顶栏、商店按钮可用性 |
| 5 | `deck_size` | `0..` | 加减牌 | 顶栏 |
| 6 | `relic_count` | `0..` | 拾取 | 遗物条长度 |
| 7 | `potion_count` | `0..3` | 拿/用/丢 | 腰带长度 |
| 8 | `map_len` | `0..` | 开局定死 | 地图节点数 |
| 9..15 | 七条 RNG 流计数器 | `0..` | 每次抽取 | **调试用**；3D 不需要 |
| 16 | `reachable_count` | `0..3` | 进节点 | 地图"能走几个" |
| 17 | `removed_cards` | `0..` | 商店删牌 | 商店删卡涨价（也可用 `rd_run_remove_price`） |
| 18 | `unknown_room` | `0` 未掷/非 `?` 房 · `1` 事件 · `2` 怪物 · `3` 商人 · `4` 宝箱 | `?` 房 `begin_node` | ★ 决定 `?` 房画什么 |

> ⚠️ `docs/spec/env-abi.md` §11.3 的表里第 18 格还写着"保留（置 0）"，代码从 §272 起就是
> `unknown_room`。这是**文档漂移**，本次一并修正。

**文本/计数导出（run 侧）**：全部是 `_len` / `_into` 成对，`_into` 写进**调用方**的缓冲区
（页面用 `readText()` 包一层）。返回 `-1` = 没有这个下标 / 没有局。

### 3.1 SC-02 地图

**层**：① 地图层（节点 + 边 + 游标 + 可达高亮）② 顶栏 ③ 节点面板 ④ 消息行。

| 字段 | 域 | 何时变 | 接口 | 驱动 |
|---|---|---|---|---|
| `mapLen` | `0..` | T0 | `rd_run_map_len()` | T1 |
| `rows` | `15` | T0 | `rd_run_map_rows()` | T1 |
| `rowFirst(r)` | 全局下标 / `-1` | T0 | `rd_run_map_row_first(r)` | T1 |
| `node(i).row` | `0..14` | T0 | `rd_run_map_node(i, 0)` | T1 |
| `node(i).col` | `0..6` | T0 | `rd_run_map_node(i, 1)` | T1 |
| `node(i).kind` | `0..7` | T0 | `rd_run_map_node(i, 2)` | T1 |
| `node(i).outDegree` | `0..3` | T0 | `rd_run_map_node(i, 3)` | T1 |
| `node(i).edge[0..2]` | 全局下标 / `-1` | T0 | `rd_run_map_node(i, 4..6)` | T1 |
| `node(i).reachable` | `0/1` | 每次进节点 | `rd_run_map_node(i, 7)` | T2 |
| `cursor` | 全局下标 / `-1` / `100`(Boss) | 进节点 | `R.obs(1)` | T2 |
| `kindName(k)` | 字符串 | T0 | `R.txt(kind_name, k)`（`rd_run_kind_name_len/into`） | T1 |

**`kind` 取值**（`NodeKind` 判别值，与 `rd_run_kind_name_len` / `rd_run_kind_name_into` 同一张表）：

| 值 | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| 名字 | `unassigned` | `combat` | `elite` | `rest` | `shop` | `unknown` | `treasure` | `boss` |

> `0 = unassigned` 出现就是 bug，不是状态（`map_render.js` 故意画得丑）。
> **Boss 是哨兵 `100`，不是地图下标**：地图 15 行，Boss 是 floor 16，在网格之外。

**迁移**：`cursor = -1`（未出发）→ 任意 `row 0` 节点（`reachable` 全 1）→ `row r` → `row r+1`。
判定只有内核的 `reachable` 位，页面**不许**自己算"能不能走"。

**动作**：

| 动作 | 接口 | 说明 |
|---|---|---|
| 走一步（进节点） | `rd_run_step(actionIndex)` | `actionIndex` 来自 `rd_run_action_count()` 与 `rd_run_action(i)`（kind `0` = 进入节点）/ `rd_run_action_arg(i, 0)` = 目标节点全局下标 |
| 结算当前节点 | `rd_run_begin_node()` | 站在节点上之后才有效；把 `pending` 从 `0` 推进到该节点的待决态（篝火 `1`、商店 `2`、事件 `5`…）或"要打一场" |

### 3.2 SC-00 未开局

全部 run 侧导出返回 `-1` / `i32::MIN`。**3D 里这是一个真实的场景**（标题画面），
不需要任何新接口；判据是 `rd_run_seed() == i32::MIN`。

**动作**：`rd_run_start(seed, ascension)` → `0` / `-2`（拒绝，原因在 `R.txt(last_error)`）。

### 3.3 SC-03 战斗入口（"这一格要不要打"）

三格联合判定，**顺序即优先级**：

| 条件 | 含义 | 依据 |
|---|---|---|
| `kind ∈ {1, 2, 7}` | 战斗 / 精英 / Boss 节点 | `rd_run_node_kind()` |
| `kind == 5 && unknownRoom == 2` | `?` 房掷出了怪物 | `R.obs(18)`（§272） |
| `eventFight > 0` | **事件把房间变成了一场战斗**（`Dead Adventurer` 的伏击） | `rd_run_event_fight()`：`0` 没有 / `1` 普通 / `2` 精英 |

| 字段 | 接口 | 备注 |
|---|---|---|
| `resolved` | `rd_run_node_resolved()` | `1` ⇒ 这一格已结算，面板只说"往前走" |
| `eventFight` | `rd_run_event_fight()` | ⚠️ 必须在 `rd_run_choose` **之后**读 |
| `kind` | `rd_run_node_kind()` | Boss 返回 `7`（哨兵 `100` 已折算） |
| `bossName` | **无导出** | 页面写死 `"Slime Boss"`（§6-G5） |

**动作**：`rd_run_fight_begin()` → `0` / `-2`。拒绝的三种：不是战斗节点、节点已结算、
已经有一场在打（`P1-2`）。

### 3.4 SC-03b 战斗中

**层**（从上到下即"谁压着谁"）：

```
┌─────────────────────────────────────────────┐
│ L5 弹窗层  选牌问句（E.choice_*） / 牌堆浏览   │  ← 压住 L1–L4 的输入
├─────────────────────────────────────────────┤
│ L4 浮字层  伤害/格挡/治疗/倒下（beats 驱动）   │
├─────────────────────────────────────────────┤
│ L3 手牌层  hand[0..9]（费用/可出/瞄准）        │
├─────────────────────────────────────────────┤
│ L2 HUD     round/turn/phase/result/energy/block│
├─────────────────────────────────────────────┤
│ L1 站位层  hero + enemy[0..5]（血量/格挡/意图/状态）│
├─────────────────────────────────────────────┤
│ L0 背景层  act + 遭遇（**今天读不到遭遇 id**，§6-G6）│
└─────────────────────────────────────────────┘
```

#### L2 HUD 层（`E.obs(0..11)`）

| i | 字段 | 域 | 何时变 | 3D 用途 |
|---:|---|---|---|---|
| 0 | `round` | `1..` | 一轮结束 | 回合计数器 |
| 1 | `turn` | `1..`（同一轮内的第几个回合，额外回合会加） | 回合切换 | 计数器 |
| 2 | `phase` | `0` WaitingToStartTurn / `1` TurnInProgress | 回合切换 | ★ 决定"现在能不能操作" |
| 3 | `result` | `0` 进行中 / `1` 胜利 / `2` 失败 / `3` 平局 / `4` 中止 | 一次性 | 结算演出 |
| 4 | `hp` | `0..hpMax` | 每 beat | 血条（战斗内唯一真相） |
| 5 | `hpMax` | `1..` | 开战时 | 血条分母 |
| 6 | `block` | `0..` | 加格挡 / 被打 / 回合末清零 | 护盾特效 |
| 7 | `ward` | **恒 `-1`** | 永不 | 本内容没有 ward 池；3D **不要画这一格** |
| 8 | `energy` | `0..` | 出牌 / 回合开始回满 | 能量球 |
| 9 | `energyMax` | `3`（= 回合补给量） | 开战时 | 分母。⚠️ 是 `TurnConfig::energy_refill`，**不是**池子上限 |
| 10 | `handCount` | `0..10` | 抽/出/弃 | 手牌数 |
| 11 | `enemyCount` | `0..6` | 召唤/分裂/死亡**不减少** | ★ 站位层要画的**槽数**（死亡槽仍占位） |

**迁移**：`phase 0→1`（回合开始）→ 出牌/结束回合 → `phase 1→0`（回合结束）→ 下一 `turn`
（或 `round+1, turn=1`）。`result 0→{1,2,3,4}` 单向，**不可逆**。

#### L1 站位层 —— 英雄

| 字段 | 域 | 接口 | 备注 |
|---|---|---|---|
| 状态五轴 `str/vuln/weak/dex/frail` | `0..` 层数 | `E.obs(12..16)` | **冻结布局**，只覆盖五个 |
| 其余状态（`constricted` 等） | `id + stacks` | `rd_env_status_count(-1)` → `rd_env_status_id_len(-1, i)` / `rd_env_status_stacks(-1, i)` | ★ 轴外的状态**必须**走这条，否则玩家看不到 |
| 状态 id 文本 | 字符串 | `E.txt(status_id, whom, i)` | 形如 `standard.constricted` |

> ⚠️ `E.obs(12..16)` 与 `status_count` 是**两个来源**：前者是冻结的 ABI 五格，后者是真实全表。
> 3D 里正确做法是**只信 `status_count` + `status_id`**，五格只用于"我确定这一格是哪个轴"的快路径。

#### L1 站位层 —— 敌人（`slot ∈ 0..5`，基址 `17 + slot*8`）

| 偏移 | 字段 | 域 | 接口 | 备注 |
|---:|---|---|---|---|
| +0 | `alive` | `0/1` | `E.obs(base)` | ★ **死亡不移除槽位**，`enemyCount` 不减少 |
| +1 | `hp` | `0..hpMax` | `E.obs(base+1)` | |
| +2 | `hpMax` | `1..` | `E.obs(base+2)` | |
| +3 | `block` | `0..` | `E.obs(base+3)` | |
| +4 | `ward` | 恒 `-1` | `E.obs(base+4)` | 不要画 |
| +5 | `intentKind` | `-1` 无 / `0` Unknown / `1` Attack / `2` Defend / `3` Buff / `4` Debuff / `5` Special | `E.obs(base+5)` | 图标类别 |
| +6 | `intentDamage` | `-1` 无数值 / `0..` | `E.obs(base+6)` | ★ `-1` **不是** 0 伤害（R2） |
| +7 | `statusCount` | `0..` | `E.obs(base+7)` | 与下面五轴列表长度**不是**同一个数 |

| 字段 | 接口 | 备注 |
|---|---|---|
| `name(slot)` | `E.txt(enemy_name, slot)` | 显示名 |
| `intentText(slot)` | `E.txt(intent, slot)` | 一行意图描述（`acid_slime_m.tackle \| Attack \| 10 dmg`） |
| `isMinion(slot)` | `rd_env_enemy_is_minion(slot)` | `1` = 召唤物。观察向量**没有**这一位 |
| 状态五轴 | `E.obs(65 + slot*5 + axis)` | 基址 `OFF_ENEMY_STATUS = 65` |
| 状态全表 | `rd_env_status_count(slot)` / `..._id_len(slot, i)` / `..._stacks(slot, i)` | 同英雄 |

> **死亡槽的意图**：参考实现对死掉的敌人也问选择器，所以 `+5/+6` 仍保留最后一次的值。
> 画不画是渲染层的决定（今天页面画 `—`），**但事实不能改**。

#### L3 手牌层（`slot ∈ 0..9`，基址 `95 + slot*4`）

| 偏移 | 字段 | 域 | 接口 | 备注 |
|---:|---|---|---|---|
| +0 | `present` | `1` 占用 / `-1` 空 | `E.obs(base)` | |
| +1 | `cost` | `-1` 读不出 / `-2` **X 费** / `0..` | `E.obs(base+1)` | ★ `-2` 要画成 `X`，不是数字（`X_COST_DISPLAY`） |
| +2 | `defSlot` | `0..`（内容行号） | `E.obs(base+2)` | 卡牌身份；3D 用它做图集索引 |
| +3 | `upgraded` | 恒 `0` | `E.obs(base+3)` | 本内容没有每副本升级位（Gap 5） |

| 字段 | 接口 | 备注 |
|---|---|---|
| `name(slot)` | `E.txt(card_name, slot)` | 显示名 |
| `title(slot)` | `E.txt(card_title, slot)` | `CARD.NameKey` |
| `text(slot)` | `E.txt(card_text, slot)` | 规则文本 |
| `kind(slot)` | `rd_env_card_kind(slot)` | `0` 无 / `1` 攻击 / `2` 技能 / `3` 能力 / `4` 状态 / `5` 诅咒 / `-1` |

**可出性**（R3：**必须**来自动作表，不许页面算）：

| 字段 | 接口 | 域 |
|---|---|---|
| `actionCount` | `rd_env_action_count()` | `0..` |
| `actionKind(i)` | `rd_env_action_kind(i)` | `0` 出牌 / `1` 结束回合 |
| `actionArg(i, 0)` | `rd_env_action_arg(i, 0)` | 手牌槽 |
| `actionArg(i, 1)` | `rd_env_action_arg(i, 1)` | 敌人槽 / `-1`（无目标） |

> 动作表对**每张牌 × 每个活着的敌人槽**发一条。所以"这张牌有 1 条动作"= 点击直接出；
> "多条"= 进入瞄准子状态；"0 条"= 出不了（灰）。**这条规则在 `playOptions()` 里，是纯函数**。
> ⚠️ 别用 `cost <= energy` 自己判断可出：每副本价格（`standard.card_cost_delta`）与
> X 费牌都让这个等式不成立。

**迁移**（手牌层）：`present 1→-1`（出牌/弃牌/消耗）→ 抽牌补位（`handCount` 变化）。
`cost` 会因每副本 delta 在**同一次出牌后**改变（出牌付款之后置 0）。

#### L5 弹窗层 —— 战斗内待决选牌（`rd_env_choice_pending` 起的一组）

| 字段 | 域 | 接口 |
|---|---|---|
| `pending` | `1` 有 / `0` 无 / `-1` 没有会话 | `rd_env_choice_pending()` |
| `source` | `1` 牌堆 / `2` 三张候选 / `0` 无 / `-1` | `rd_env_choice_source()` |
| `kind` | `1` 消耗 / `2` 丢弃并抽 / `0`/-1 无 | `rd_env_choice_kind()` |
| `copies` | `0` 不是复制问句 / `1..` 每张复制几份 / `-1` | `rd_env_choice_copies()` |
| `min` / `max` | `0..` / `-1` 无问句 | `rd_env_choice_min()` / `rd_env_choice_max()` |
| `count` | `0..`（= `rd_env_pile_len(3)`） | `rd_env_choice_count()` |
| `option(i)` | `id`/`title` | `rd_env_pile_card_id_len(3, i)` / `_title_len(3, i)` |
| 勾选 | `1/0` | `rd_env_choice_pick(i, on)` / `rd_env_choice_selected(i)` |
| 清空 | `0` | `rd_env_choice_clear()` |
| 确认 | `0` / `-1` / `-2` | `rd_env_choice_confirm()` |

> ★ **句子由 `(source, kind)` 两个数决定**，不是只由 `kind`：`kind` 只有三个值，而
> "从弃牌堆拿一张"与"从三张候选里选一张"是同一个 `then`。`min == max` 写 `n 张`，否则 `m–n 张`。
> **`closeModal` 在有待决问句时直接返回** —— 只有一个关闭入口，就只有一个"不许关"的判断点。

#### L6 驱动层（动作的返回值，不是"游戏状态"）

| 字段 | 域 | 接口 | 3D 用途 |
|---|---|---|---|
| `stepVerdict` | `0` 接受 / `-1` **拒绝且观察向量逐字节不变** / `-2` 已结束 / `-3` 驱动坏了 | `rd_env_step(actionIndex)` | 拒绝 ⇒ 不播任何动画（这就是"拒绝"的定义） |
| `reward` | 千分比整数（`1250` = 1.25） | `rd_env_reward()` | 训练信号；UI 只在调试面板显示 |
| `done` | `0/1` | `rd_env_done()` | "这场打完了"（与 `E.obs(3) != 0` 同义，但更快） |
| `result` | `0..4`（同 `E.obs(3)`） | `rd_env_result()` | 结算演出 |
| `stepCode(i)` | 拒绝码 | `rd_env_step_code(i)` | ★ `-1` 只说了"拒绝"，这个说了**为什么**（哪张牌、哪条拒因） |
| `problem` | 文本 | `E.txt(problem)` | 上一步没做完的原因 |
| `active` | 文本（`Exec(...)` 那种诊断串） | `E.txt(active)` | "现在是谁的回合"—— ⚠️ **只有文本**，§6-G12 |
| `hostFailure` | 文本 | `E.txt(host_failure)` | 宿主内部失败细节（容器满之类） |
| 重置一场战斗 | `0` / `-1` | `rd_env_reset()` | 驱动侧：把战斗会话重建成开战态 |

### 3.5 SC-01 塔底祝福（`pending == 6`）

| 字段 | 域 | 接口 | 备注 |
|---|---|---|---|
| `offerCount` | 恒 `2` | **无导出**（页面写 `0..1`） | §6-G7：内容若变 3 选 1，页面会静默少画一个 |
| `offerName(slot)` | 字符串 | `R.txt(start_offer, slot)` | 形如 `max_hp` / `gold` / `heal` |
| `gain(slot)` | `0..15` 效果码 | `rd_run_start_gain(slot)` | |
| `gainAmount(slot)` | `0..` | `rd_run_start_gain_amount(slot)` | |
| `cost(slot)` | `0..15` / `-1` 无代价 | `rd_run_start_cost(slot)` | |
| `costAmount(slot)` | `0..` | `rd_run_start_cost_amount(slot)` | |

**效果码表**（`0..15`，`port-plan.md` §80/§143/§278/§280）：

| 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 无 | 回复 | 金币 | 受伤 | 最大 HP | 什么也不做 | 删一张牌 | 升级一张牌 | 转化一张牌 | 获得诅咒 | 获得遗物 | 按上限%受伤 | 按上限%减最大HP | 花金币 | 按上限%回复 | 回满血 |

> ⚠️ `11/12/14` 的"数"是**千分比**（`250` = 25%，`125` = 12.5%），`6..10` 与 `13..15` 的数是 0
> （把 0 印出来就是"升级一张牌 0"）。

| 字段 | 域 | 接口 | 备注 |
|---|---|---|---|
| `needs` | `1` 移除 / `2` 升级 | `rd_run_blessing_needs()` | 只在 `pending == 7` 时有意义 |
| `slotNeeds(slot)` | `0` 无后续 / `1` 要移除一张 / `2` 要升级一张 / `-1` 没有这一格 | `rd_run_start_needs(slot)` | ★ 按**槽**问，而不是全局问：两个 offer 可以各自欠不同的后续 |

**动作**：`rd_run_choose_start(slot)` → `0`；要选牌时转 `pending = 7`，再由
`rd_run_pick_blessing_card(deckIndex)` 收尾。

### 3.6 SC-04 战斗奖励（`pending == 4`）

| 字段 | 域 | 接口 | 备注 |
|---|---|---|---|
| `gold` | `0..` | `rd_run_reward_gold()` | 已入账 |
| `cardCount` | `0..` | `rd_run_reward_card_count()` | ★ **被拿走的行被清空，不删除**（槽号必须稳定） |
| `cardId(slot)` | 字符串 / 空 | `R.txt(reward_card_id, slot)` | 空 = 这一行已被拿走，**跳过不画** |
| `cardTitle(slot)` | 字符串 | `R.txt(reward_card_title, slot)` | |
| `cardKind(slot)` | `0..5` | `rd_run_card_kind(1, slot)` | `context 1` = 奖励屏 |
| `potion` | 字符串 / `null` | `R.txt(reward_potion)` | 长度 0 = 没有 |
| `relic` | 字符串 / `null` | `R.txt(reward_relic)` | 精英/Boss 才有 |
| `singingBowl` | `0/1` | **无导出**：页面遍历 `relicId(i)` | §6-G3 |
| `maxHpInstead` 可用性 | `singingBowl && cardCount > 0` | 派生 | 牌拿完之后画出来就是死按钮 |

**动作**：`rd_run_take_card(slot)` / `rd_run_take_potion()` / `rd_run_take_relic()` /
`rd_run_take_max_hp_instead()` / `rd_run_skip_reward()`。

**迁移**：`pending 4` → 拿完/跳过 → `0`。**拿一张牌不会关屏**（`take_card` 只清那一行）。

### 3.7 SC-05 商店（`pending == 2`）

四排货架 + 一个删卡服务，**同一形状**：

| 排 | 计数 | id | 价格 | 购买 | 类型 chip |
|---|---|---|---|---|---|
| 卡牌 | `rd_run_shop_card_count()` | `R.txt(shop_card_id, slot)` | `rd_run_shop_card_price(slot)` | `rd_run_buy_card(slot)` | `rd_run_card_kind(2, slot)` |
| 无色 | `rd_run_shop_colorless_count()` | `R.txt(shop_colorless_id, slot)` | `rd_run_shop_colorless_price(slot)` | `rd_run_buy_colorless(slot)` | **无** |
| 药水 | `rd_run_shop_potion_count()` | `R.txt(shop_potion_id, slot)` | `rd_run_shop_potion_price(slot)` | `rd_run_buy_potion(slot)` | **无** |
| 遗物 | `rd_run_shop_relic_count()` | `R.txt(shop_relic_id, slot)` | `rd_run_shop_relic_price(slot)` | `rd_run_buy_relic(slot)` | **无** |
| 删卡 | — | — | `rd_run_remove_price()` | `rd_run_remove_card(deckIndex)` | — |

**删卡服务的两个数**（§343：wiki 的 *"Can only be used once per Shop"*）：

| 字段 | 域 | 接口 | 备注 |
|---|---|---|---|
| `removePrice` | `1..`（75 起、每用一次 +25，**跨店累计**） | `rd_run_remove_price()` | 显示用 |
| `removalAvailable` | `1` 这家店还能删 / `0` 已经删过 / `-1` 没有局 | `rd_run_removal_available()` | ★ 按钮可用性**只能**看它；用价格返回 `-1` 来表达"不可用"会让页面把 `-1` 印成价格 |
| 删除 | `>0` = 实付价 / `-2` 拒绝 | `rd_run_remove_card(deckIndex)` | ⚠️ 成功返回的是**价格**，不是 0（与 `buy_*` 不同） |

| 字段 | 域 | 备注 |
|---|---|---|
| `price` | `-1` = **已售** / `0..` | ★ `-1` 与"买不起"是两件事：前者画"已售"，后者画价格 + 禁用 |
| `title` | **恒空** | §6-G8：商店**没有**标题导出，页面回退到 id |
| 买得起 | `price >= 0 && price <= gold` | 派生（两个输入都来自内核，符合 R3） |

**动作**：`leave` 关屏。`remove_card` 进 SC-14 弹窗选牌（**一次买卖**，选完回商店）。

### 3.8 SC-06 篝火（`pending == 1`）

| 字段 | 域 | 接口 | 备注 |
|---|---|---|---|
| `options` | 位掩码 `0..63` | `rd_run_campfire_options()` | `Rest 1 \| Smith 2 \| Recall 4 \| Lift 8 \| Toke 16 \| Dig 32` |
| `giryaLifts` | `0..3` | `rd_run_girya_lifts()` | 只用于文案"已用 n/3" |
| `restHeal` | `1..` | `rd_run_rest_heal()` | §344：**已关闭 G9**。它含 `regal_pillow`（+15）与 `eternal_feather`（每 5 张 +3），页面自己算会显示错数 |
| `relics` | id 列表 | `R.txt(relic_id, i)` | 只用于"举铁已用满"的说明文字 |

> ★ **六个选项的存在与否是内核的答案**（位掩码）。页面自己判"我有 Girya 就显示举铁"是
> 第二份规则，`Coffee Dripper` 一出现就会漂。灰掉的选项要**说出为什么**（缺哪一位），
> 否则玩家以为页面漏了。

**动作**：`rd_run_rest()` / `rd_run_smith(deckIndex)` / `rd_run_lift()` / `rd_run_toke(deckIndex)` /
`rd_run_dig()` / `rd_run_recall()` / `rd_run_leave()`。

### 3.9 SC-07 宝箱（`pending == 3`）

无字段。**动作**：`rd_run_open_chest()` → 可能转 `pending = 4`（奖励屏）/ 拾取欠账；`rd_run_leave()`。

### 3.10 SC-08 事件（`pending == 5`）

| 字段 | 域 | 接口 | 备注 |
|---|---|---|---|
| `text` | 字符串 | `R.txt(event_text)` | 一行描述（3D 需要**事件 id** 才能选背景，§6-G6） |
| `optionCount` | `0..` | `rd_run_event_option_count()` | **由内容决定**，不假定 2 |
| `label(slot)` | 字符串 | `R.txt(event_label, slot)` | |
| `available(slot)` | `0/1` | `rd_run_event_option_available(slot)` | `0` ⇒ **不画**（没有锁标） |
| `effectCount(slot)` | `0..` | `rd_run_event_effect_count(slot)` | 一个选项是**效果列表** |
| `effect(slot, i)` | `0..15` | `rd_run_event_effect_at(slot, i)` | |
| `amount(slot, i)` | `0..` | `rd_run_event_amount_at(slot, i)` | |
| 单条旧字段 | `effect` / `amount` | `rd_run_event_effect(slot)` / `rd_run_event_amount(slot)` | 保留兼容；新代码用列表 |

> ★ **槽号必须用条目自己的 `slot`**，不是过滤掉不可用选项之后的下标 ——
> 否则"第二段的第 2 个按钮"会打给内核第 1 个槽，而屏幕上一切正常。

**迁移**（事件是**唯一**能把 `pending` 变成多种值的场景）：

| 选择的效果 | `pending` 去向 |
|---|---|
| 纯内容（回血/金币/诅咒/遗物/受伤…） | `0`（事件收尾） |
| 需要删/升级/转化牌 | `8`（SC-09） |
| 摊开一列新牌让玩家选 | `9`（SC-10） |
| 打一场（伏击） | `0` **且** `rd_run_event_fight() > 0` ⇒ 面板变成"开始战斗" |

**动作**：`rd_run_choose(slot)`。

### 3.11 SC-09 事件选牌（`pending == 8`）

| 字段 | 域 | 接口 |
|---|---|---|
| `needs` | `1` 移除 / `2` 升级 / `3` 转化 | `rd_run_event_needs()` |
| 牌组列表 | `count` + `title` + `id` | `rd_run_deck_count()` / `R.txt(deck_title, i)` / `R.txt(deck_id, i)` |

**动作**：`rd_run_pick_event_card(deckIndex)` → `0`（回事件收尾）。

### 3.12 SC-10 事件候选（`pending == 9`）

| 字段 | 域 | 接口 |
|---|---|---|
| `count` | `0..`（`The Library` = 20，`Sensory Stone` = 3） | `rd_run_event_offer_len()` |
| `id(slot)` | 字符串 | `R.txt(event_offer_id, slot)` |
| `title(slot)` | 字符串 | `R.txt(event_offer_title, slot)` |

**动作**：`rd_run_event_offer_take(slot)`。**没有"跳过"**（wiki 是 "add N cards"）。

### 3.13 SC-11 遗物欠账（两个独立覆盖层）

| | SC-11a 改牌 | SC-11b 加牌 |
|---|---|---|
| 判据 | `rd_run_pickup_picks() > 0` | `rd_run_pickup_add() > 0` |
| 种类 | `rd_run_pickup_change()`：`1` 移除 / `2` 升级 / `3` 转化 / `4` 转化并升级 | — |
| 剩余 | `pickup_picks` | `pickup_add` |
| 候选 | 牌组（`deck_*`） | `rd_run_pickup_offer_count()` + `R.txt(pickup_offer_title, i)` |
| 动作 | `rd_run_pickup_card(deckIndex)` | `rd_run_pickup_add_card(slot)` / `rd_run_pickup_add_skip()` / `rd_run_pickup_add_max_hp()` |
| 额外按钮 | — | `+2 上限` **只在持有 `singing_bowl` 时画** |

> ★ 这两个覆盖层**独立于 `pending`**：它们能叠在奖励屏/宝箱屏上（打完 Boss 拿 Boss 遗物、
> 还想接着拿卡牌奖励）。所以它们在 `describe()` 的**最前面**，选完自然回到原来那一屏。
> 3D 里这是"压在最顶的模态层"，**不是**新场景。

### 3.14 SC-14 弹窗（牌组 / 牌堆 / 卡牌详情）

| 用途 | 数据来源 | 动作 |
|---|---|---|
| 牌组浏览 | `rd_run_deck_count()` + `R.txt(deck_title/id, i)` | 只读 |
| 牌堆浏览（战斗内） | `rd_env_pile_len(zone)` + `R.txt(pile_card_id/title, zone, i)` | 只读 |
| 卡牌详情 | `rd_run_card_fact_len(where, slot, field)`（`where` 选择上下文） | 只读 |
| 选牌（删/升级/转化） | 牌组列表 | 回调把 `deckIndex` 交回发起者 |

> 弹窗是**唯一**用 `deckIndex` 而不是"牌实例 id"的地方。原因是运行层的牌组就是
> `[id; MAX_RUN_DECK]` 的数组，下标即身份（`mark` 表也按它索引）。

### 3.15 SC-12 幕通关 / 局终

| 字段 | 接口 | 备注 |
|---|---|---|
| `cleared` | `rd_run_boss_beaten() == 1` | `1` = 本幕 Boss 已击败 |
| `act` | `rd_run_act()` | 标题里用 |
| `runOver` | **无导出** | §6-G1：页面在"战斗失败"时自己置位 |
| 统计行 | `floor/hp/hpMax/gold/deckCount/relicCount/wingBoots` | 全是已有导出 |

**动作**：重开（`rd_run_start`）/ 换 seed（页面侧 `seed+1` 再 `rd_run_start`）。

### 3.16 作者 / 驱动入口（**不是**玩家状态）

这些导出不走"游戏流程"，而是给测试、`?debug` 面板、以及未来的 3D 调试器用的。
3D 重写时它们应当活在一个**开发者面板**里，绝不进玩家界面。

| 接口 | 用途 | 备注 |
|---|---|---|
| `rd_env_start_encounter(ptr, len)` | 直接开一场**指定**遭遇 | 训练/回放夹具；绕过地图 |
| `rd_run_begin_event(ptr, len)` | 直接打开**指定**事件（按 id） | `?` 房的内容调试 |
| `rd_run_grant_potion(ptr, len)` | 直接塞一瓶药水 | §161 的调试入口；与"拿药水"同一个授予点 |
| `rd_run_grant_relic(ptr, len)` | 直接塞一件遗物 | 同上 |
| `rd_env_reset()` | 把战斗会话重建成开战态 | 见 §3.4 L6 |

> 为什么它们必须留在 ABI 里：**"能不能被直接构造成某个局面"决定了它能不能被测试**。
> 只靠"打十几步刚好撞上"的夹具，在内容一改就全红（§106 的教训）。

### 3.17 SC-02b 幕尽头

`pending == 0`、`kind >= 0`、`rd_run_action_count() == 0`、且不是战斗。含义：
"地图走到最后一排，没有可走的节点了"。页面给的按钮 `end_act` **只是本地置 `runOver`**，
内核没有对应动作（§6-G2）。

---

## 4. 动画事件流（beat）—— 唯一的事件流

**为什么必须有它**：`diffObservations`（相减两个观察向量）能回答"还剩几点血"，回答不了
"刚才发生了什么"。敌人 7×3 的多段攻击减完只有"掉了 21 血"；"先加格挡再挨打"与"先挨打再加格挡"
减出同一个向量。**顺序与分段**正是动画的全部输入。

**接口**：

| 导出 | 返回 |
|---|---|
| `rd_env_beat_count()` | 上一步产生了多少条；`-1` = 没有会话 |
| `rd_env_beat_field(i, field)` | 见下表；`-1` = 没有这一条/这一格 |
| `rd_env_beat_def_len(i)` + `..._def_into(i, ptr)` | 这一条的定义名（状态/卡牌），`-1` = 没有 |
| `rd_env_beats_dropped()` | 因为容量丢掉了几条。**`0` 是唯一好答案** |
| `rd_env_beats_clear()` | 清空（每个动作入口已经自动清一次） |

**字段**（`field`）：

| field | 含义 |
|---:|---|
| 0 | `kind`（下表） |
| 1 | `actor` 墙位：`-1` 英雄 / `0..5` 敌人槽 / `-2` 墙外 |
| 2 | `target` 墙位，同编码 |
| 3 | `flags` |
| 4 | `a` 主数 |
| 5 | `b` 第二数 |
| 6 | `c` 第三数 |
| 7 | 有没有定义名（`1`/`0`） |

**种类 × 数值语义**（`rd-core/src/beat.rs`，数值是 ABI 值，**不许重排**）：

| kind | 名字 | actor | target | a | b | c | def | flags |
|---:|---|---|---|---|---|---|---|---|
| 1 | `Damage` | 伤害来源 | 挨打的 | 实际掉血 | 被防御池吸收 | 请求额（修饰后） | — | bit0 = 痛伤（DoT） |
| 2 | `Block` | 得到的人 | — | 实际加的 | — | — | — | — |
| 3 | `Heal` | 被治的人 | — | 实际回的 | — | — | — | — |
| 4 | `StatusChanged` | 被改的人 | — | **净变化**（可负） | — | — | 状态定义 | bit1 = 新建实例 |
| 5 | `StatusRemoved` | 被删的人 | — | — | — | — | 状态定义 | — |
| 6 | `StatusPrevented` | — | — | — | — | — | 被挡下的状态 | — |
| 7 | `Downed` | 送他上路的人（可无） | 倒下的人 | — | — | — | — | — |
| 8 | `Escaped` | — | 逃跑的随从 | — | — | — | — | — |
| 9 | `CardPlayed` | 出牌人 | — | — | — | — | 卡牌定义 | bit2 = 行动侧打出（不触发 `CardPlayed`，仍要演） |
| 10 | `TurnStarted` | 轮到的人 | — | — | — | — | — | — |
| 11 | `TurnEnded` | 结束的人 | — | — | — | — | — | — |
| 12 | `Summoned` | — | 新人（**ordinal**） | — | 最大生命 | — | 定义 | — |
| 13 | `Destroyed` | — | 原 ordinal | — | — | — | 定义 | — |

> ⚠️ **kind 13（`Destroyed`，§178 `node.destroyCombatant`）在 `rd-wasm` 里没有对应的
> `BEAT_*` 常量，页面的 `switch` 也没有分支** —— 3D 重写必须处理它（§6-G11）。
> 与 `Downed` 的区别：倒下的人**还在名册里**（触发器还能响），被移出的人**不在了**。

**容量**：`MAX_BEATS = 64` / `MAX_BEAT_DEFS = 24`。满了**不报错**（日志是派生视图，不该把一次
出牌变成错误），但 `beats_dropped()` 会加一 —— 页面必须**说出来**，不许少播了还装作完整。

**它不覆盖什么**（3D 必须自己补）：

| 缺的东西 | 今天的替代 | 影响 |
|---|---|---|
| **时长/缓动** | 无 | 3D 自己定：一条 beat 给多少帧 |
| **位置/朝向** | 只有墙位 `slot` | 3D 自己把 slot 映射到锚点 |
| **同帧并发 vs 串行** | beat 是有序的，但没说"这几条同时发生" | 多段攻击要自己分段（这正是 beat 存在的理由，但"每段间隔"仍需自己定） |
| **被打断/取消** | 无 | 拒绝的动作不产生 beat（`rd_env_step` 返回 `-1` 时观察向量逐字节不变） |

---

## 5. 跨场景迁移总图

```
                        rd_run_start(seed, asc)
  SC-00 未开局 ─────────────────────────────────► SC-01 祝福 (pending 6)
                                                      │ choose_start
                        ┌─────────────────────────────┼──────────────┐
                        ▼                             ▼              │
              SC-01b 祝福选牌 (7) ──pick_blessing_card──► pending 0 ◄─┘ (无牌要选)
                                                             │
                                                             ▼
  ┌───────────────────────────────────────────────────► SC-02 地图
  │                                                          │ step(node) / begin_node
  │        ┌──────────┬──────────┬──────────┬────────────┬────┴─────┬──────────┐
  │        ▼          ▼          ▼          ▼            ▼          ▼          ▼
  │    SC-06 篝火  SC-05 商店  SC-07 宝箱  SC-08 事件   SC-03 战斗  SC-02b 幕尽头  (精英/Boss 同 SC-03)
  │      (1)        (2)        (3)        (5)          (0)         │
  │        │          │          │          │            │          │ end_act（本地）
  │        │          │          │          ├─► SC-09 事件选牌 (8)  ▼
  │        │          │          │          ├─► SC-10 事件候选 (9)  SC-12b 局终
  │        │          │          │          └─► 伏击：eventFight>0 ──► SC-03
  │        │          │          │                       │ fight_begin → SC-03b
  │        │          │          │                       │ fight_end
  │        │          │          │                       ▼
  │        │          │          │                  SC-04 奖励 (4)
  │        │          │          └─► open_chest ──► SC-04 / SC-11
  │        │          └─► buy_* / remove_card ──► (回商店)
  │        └─► rest / smith / lift / toke / dig / recall ──► 回 SC-02
  │                                                             │
  └───────────────────── leave / 结算完成 ◄──────────────────────┘

  覆盖层（任何场景之上，独立于 pending）：
    SC-11a 遗物改牌 (pickup_picks > 0)   SC-11b 遗物加牌 (pickup_add > 0)
    SC-14 弹窗（牌组/牌堆/详情/选牌）
```

**两条规则**：

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
2. **只有 `rd_run_step` 与各节点动作会推进 `pending`**。渲染层不许自己改场景。

---

## 6. 缺口清单（Live2D / Three.js 会立刻撞上的）

按"3D 重写时会不会被卡住"排序。每条给出：**今天怎么办** / **建议加什么** / **代价**。

| id | 缺口 | 今天怎么办 | 建议 | 代价 |
|---|---|---|---|---|
| ~~**G1**~~ | ~~"这一局结束了"没有内核判据~~ | — | **已关闭（§344）**：`rd_run_over()` → `1/0/-1`，`rd_run_over_why()` → `0` 进行中 / `1` 战败 / `2` 通关 / `3` 地图走完了 | 已完成 |
| ~~**G2**~~ | ~~幕尽头没有动作~~ | — | **已关闭（§344）**：`rd_run_end_act()`（`0` 接受 / `-2` 拒绝）。三条前提：没有待决问句 / 脚下节点已结算 / `reachable()` 为空 | 已完成。⚠️ 当前内容里**几乎不可达**（最后一排的唯一前进方向是 Boss 哨兵）—— 见 §6 末尾 |
| **G3** | **"我有没有某件遗物"要遍历 id** | `for i in 0..relic_count { relicId(i) }`（`singingBowl` 就这样） | `rd_run_has_relic(idPtr, len)` → `0/1`，或一个遗物**位掩码** | 小，但位掩码要随内容增长 ⇒ 用 id 查询更稳 |
| **G4** | **药水没有显示名/描述** | 只显示 id（`entropic_brew`） | `rd_run_potion_name_len/into`、`..._text_...` | 小：`POT` 段已有字段 |
| **G5** | **Boss 名字写死** | `snapshot.bossName = "Slime Boss"` | `R.txt(boss_name)` 或从 `ENCT` 读 | 小 |
| **G6** | **没有"事件 id / 遭遇 id"** | 事件只有一行文本；战斗只有敌人名 | `rd_run_event_id_len/into`、`rd_env_encounter_id_len/into` | 中：`EV`/`ENCT` 段有 id，只是没导出 |
| **G7** | **祝福只有 2 个 offer（写死）** | `for slot in 0..2` | `rd_run_start_offer_count()` | 很小 |
| **G8** | **商店四排都没有标题** | 回退到 id | 与 G4 同一个形状：`shop_*_title_len/into` | 小 |
| ~~**G9**~~ | ~~`restHeal` 的 30% 住在渲染层~~ | — | **已关闭（§344）**：`rd_run_rest_heal()` | 已完成。⚠️ 它不只是分层问题：`rest_heal()` 还含 `regal_pillow`（+15）与 `eternal_feather`（每 5 张 +3），页面自己算**显示的数字是错的** |
| **G10** | **没有连续量**（T4） | 没有时长/位置/缓动 | 不必加：3D 自己定，但要**记下来**这是渲染层的自由度 | 0（约定） |
| ~~**G11**~~ | ~~beat kind 13 无 ABI 常量~~ | — | **已关闭（§344）**：`BEAT_DESTROYED = 13`，并且有一条**穷尽**判据（`1..=13` 每个都有常量、`14` 不在闭集里） | 已完成。⚠️ 页面**根本不消费 beat**（动画走 `diffObservations`）—— 所以"页面 switch 落空"是本文档当初的推断，真实缺口是"消费者无法命名它" |
| **G12** | **"现在是谁的回合"只有文本** | `rd_env_active_len()` 返回 `Exec(...)` 那种诊断串 | `rd_env_active_slot()` → 墙位（`-1` 英雄 / `0..5`） | 小 |
| **G13** | **手牌没有 id 导出** | 只有 `def_slot` + 名字/标题/文本 | 3D 图集按 `def_slot` 建表即可 | 0（够用，但要知道 `def_slot` 是**内容行号**，跨版本会变） |
| **G14** | **费用的"未修饰 vs 修饰"不分离** | 只有最终价；每副本 delta 不可见 | 若要演"这张牌降价了"，需要 `rd_env_card_cost_printed(slot)` | 小 |
| **G15** | **`E.obs(140..147)` 恒 `-1`（保留）** | — | 3D **不要**读这 8 格 | 0（约定） |
| ~~**G16**~~ | ~~"有没有一场正在打的战斗"没有内核判据~~ | — | **已关闭（§341）**：`rd_run_in_fight()` → `1/0/-1` | 已完成 |

> **G16 为什么曾经是缺口**：`pending` 在"战斗前"与"战斗中"都是 `0`；`node_resolved()` 战斗中仍是
> false；`rd_env_done()` 在**没有会话**时返回 `1`（"结束了"），所以它不能反过来说"有没有战斗"。
> 于是"未开始"只能是页面自己记的 `mode` ⇒ 场景表不是状态的函数，而是**历史的函数**。
> `rd_run_in_fight()` 读的是 `fight_begin` 提交点写、`fight_end` 清的那一格 —— 与"战斗中不许
> 存档/回放"用的是同一个字段。

> **G9 / G1 / G11 是"会静默出错"的三条**，其余是"做不好看/做不了"。静默那三条优先。
>
> ### 四条关闭之后的两条观察（§344）
>
> 1. **G9 不只是"分层不好看"**：页面原来自己算 `Math.floor(hpMax*30/100)`，而
>    `RunState::rest_heal()` 还含 `regal_pillow`（+15）与 `eternal_feather`（每 5 张牌 +3）——
>    持那两件遗物时**显示的数字是错的**（显示 +24、实际 +39）。"规则外泄"最终总会变成
>    "两个数"，只是时间问题。
> 2. **SC-02b（幕尽头）在当前内容里几乎不可达**：`reachable()` 在最后一排把 **Boss 哨兵**
>    当成唯一前进方向（`inv:§7.2`：Boss 是 floor 16、在地图之外），所以"真的没事可做"只在
>    **Boss 已倒**时成立 —— 而那时要么换幕、要么就是最后一幕（`Victory` 优先）。
>    `rd_run_end_act()` 仍然值得存在（它是 SC-02b 的内核落点，守卫是"真的没事可做"），
>    但**场景表里那一行应当标成"当前内容不可达"**，而不是假装它在跑。

---

## 7. 防腐：怎么让这份文档不烂

文档烂掉的方式只有一种：**里面的导出名不再存在，或者新导出没人登记**。所以判据是
机械的 —— `native/ui_state_check.py`：

1. 从 `kernel/rd-wasm/src/*.rs` 抽出全部 `pub extern "C" fn rd_*`（今天 177 条）；
2. 从本文件抽出全部 `rd_[a-z0-9_]+` 提及；
3. **本文提到的每一个都必须存在**（防拼错、防删除后忘了改）；
4. **每一条导出都必须被提到，或在 `NOT_UI` 白名单里**（bench/selfcheck/内容自检这些不面向 UI）；
5. 表格行数、场景数、缺口数打出来，供人眼对账。

`NOT_UI` 白名单是**唯一**允许"存在但没写进本文"的地方，加一条就要写理由 ——
否则"漏登记"和"不该登记"会长得一模一样。

反证（必须能红）：往本文里塞一个**不存在**的名字（`rd_run_` + 随便几个字母），检查器必须报错；
从白名单里删一条、同时删掉本文对它的提及，检查器必须报"未登记"。

### 7b. 名字对了不等于场景对了（八轮 Review 3.3 的边界）

`ui_state_check.py` **只**证明"文档点名的导出都存在、每个导出都被登记"。它**不**证明：

* 参数/返回值/哨兵/长度单位对不对；
* 某个字段是否被写在**正确的表格行**里（只要名字在文中出现过就算登记 —— §8 的分类错位
  就是这么混过去的）；
* 场景谓词是否互斥、是否可达。

所以 §1 那张表还欠一份**可执行的**东西：19 个场景各一份 `snapshot` 夹具，断言
`classifyScene(snapshot)` **唯一命中**；多重命中或零命中都要**报错**，不是"取第一个"。
（`web/ui_panels.js` 的 `describe()` 已经是这张表的实现，`web/ui_test.mjs` 用字面量 snapshot
逐状态测 —— 但那是**页面**的版本，不是"这张表"的版本。3D 重写时应当先写 `classifyScene`，
再写渲染。）

---

## 8. 附录：文本导出的名字表（41 对 `_len` / `_into`）

文本一律是 UTF-8 字节，**没有 NUL 结尾**：先问 `_len`，再让 `_into` 写进**自己的**缓冲区
（`rd_env_scratch_buf()` / `rd_run_*` 的 `into` 都接受调用方指针）。`-1` = 没有这个下标 / 没有局。

### 8.1 运行层（26 对）

| `_len` 那一半（`_into` 同名前缀） | 参数 | 读什么 | 用在 |
|---|---|---|---|
| `rd_run_last_error_len` | — | 上一次拒绝的原因 | 消息行 |
| `rd_run_kind_name_len` | `kind` | 节点种类的名字（`combat`/`elite`/…） | 地图图例 |
| `rd_run_map_len` | — | （见 §3.1；地图走 `rd_run_map_node`，这一对是文本地图） | 调试 |
| `rd_run_deck_title_len` | `index` | 牌组第 i 张的显示名 | 牌组浏览、选牌 |
| `rd_run_deck_id_len` | `index` | 牌组第 i 张的定义 id | 选牌、`mark` 对账 |
| `rd_run_card_fact_len` | `where, slot, field` | 一张牌的**事实**（费用/类型/…），按上下文 | 卡牌详情 |
| `rd_run_relic_name_len` | `index` | 遗物显示名 | 遗物条 |
| `rd_run_relic_id_len` | `index` | 遗物 id | ★ `singing_bowl` 判据 |
| `rd_run_potion_id_len` | `index` | 药水 id（**没有显示名**，§6-G4） | 药水腰带 |
| `rd_run_start_offer_len` | `slot` | 祝福选项的 id（`max_hp`/`gold`/…） | SC-01 |
| `rd_run_event_text_len` | — | 事件描述（一行） | SC-08 |
| `rd_run_event_label_len` | `slot` | 事件选项的按钮文字 | SC-08 |
| `rd_run_event_offer_len` | — | 事件候选的**数量**（`_len` 无参） | SC-10 |
| `rd_run_event_offer_id_len` | `slot` | 候选牌的 id | SC-10 |
| `rd_run_event_offer_title_len` | `slot` | 候选牌的显示名 | SC-10 |
| `rd_run_reward_card_id_len` | `slot` | 奖励牌 id（空 = 已被拿走） | SC-04 |
| `rd_run_reward_card_title_len` | `slot` | 奖励牌显示名 | SC-04 |
| `rd_run_reward_potion_len` | — | 奖励药水 id（长度 0 = 没有） | SC-04 |
| `rd_run_reward_relic_len` | — | 奖励遗物 id（长度 0 = 没有） | SC-04 |
| `rd_run_shop_card_id_len` | `slot` | 商店卡牌 id（**没有 title**，§6-G8） | SC-05 |
| `rd_run_shop_colorless_id_len` | `slot` | 无色货架 id | SC-05 |
| `rd_run_shop_potion_id_len` | `slot` | 药水货架 id | SC-05 |
| `rd_run_shop_relic_id_len` | `slot` | 遗物货架 id | SC-05 |
| `rd_run_pickup_offer_title_len` | `slot` | 加牌候选的显示名 | SC-11b |

### 8.2 战斗层（15 对）

| `_len` 那一半（`_into` 同名前缀） | 参数 | 读什么 | 用在 |
|---|---|---|---|
| `rd_env_last_error_len` | — | 上一次失败的原因 | 消息行 |
| `rd_env_problem_len` | — | §174 上一步没做完的原因 | 调试 |
| `rd_env_active_len` | — | **谁在行动**（诊断串） | ⚠️ 只有文本，§6-G12 |
| `rd_env_host_failure_len` | — | 宿主内部失败细节（容器满之类） | 调试 |
| `rd_env_code_name_len` | `code` | 拒绝码的名字（与内核同一张表） | 调试 |
| `rd_env_card_name_len` | `handSlot` | 手牌名 | 手牌 |
| `rd_env_card_title_len` | `handSlot` | 手牌标题（`CARD.NameKey`） | 手牌 |
| `rd_env_card_text_len` | `handSlot` | 手牌规则文本 | 手牌 |
| `rd_env_enemy_name_len` | `slot` | 敌人显示名 | 站位层 |
| `rd_env_intent_len` | `slot` | 意图一行描述 | 站位层 |
| `rd_env_status_id_len` | `whom, i` | 第 i 条状态的**定义 id** | 状态 chip（轴外状态必走这条） |
| `rd_env_pile_card_id_len` | `zone, i` | 牌堆第 i 张的 id | 牌堆浏览 |
| `rd_env_pile_card_title_len` | `zone, i` | 牌堆第 i 张的显示名 | 牌堆浏览 |
| `rd_env_beat_def_len` | `beatIndex` | 这一条 beat 的定义名（状态/卡牌） | 浮字层 |

> **`zone` 编码**：`0` 抽牌堆 / `1` 弃牌堆 / `2` 消耗堆 / `3` **问句的来源牌区**
> （`Offered` 时是三条**定义**、没有牌堆）。`rd_env_choice_count()` 等于 `rd_env_pile_len(3)`
> —— 写两遍是故意的，让"选牌器"和"边界检查"不一致时最便宜的地方能发现。

### 8.3 非文本但同样"成对"的守卫

| 名字 | 用途 |
|---|---|
| `rd_run_observe_len()` | 运行层向量长度（19）。`rd_run_observe(i)` 按它越界 |
| `rd_env_observe_len()` | 战斗向量长度（148）。页面**必须**读它，不许写死 |
| `rd_env_pile_len(zone)` | **计数**（不是文本）：`zone` 的牌数。`zone 3` = 问句的来源牌区 |
| `rd_env_observe_buf()` | 向量地址（零拷贝） |
| `rd_env_observe_into(ptr)` | 复制到调用方缓冲区 |
| `rd_env_scratch_buf()` | 1 KiB 文本中转区 |
| `rd_run_script_capacity()` / `rd_run_archive_capacity()` | 导出前先问容量（溢出是"对局说谎"） |
