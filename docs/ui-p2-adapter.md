# P2 第一步：WASM 适配器（`WasmHost` / `SnapshotReader` / `ActionDispatcher` / `GameStore`）

> 产物：`web-next/src/wasm/{host,snapshot,store}.ts` + `web-next/src/p2probe.ts`（接线探针页）
> 闸门：**[28/28] `ui-wasm`**（`native/ui_wasm_check.mjs`，驱动 `web-next/dist/p2.html`）
> 纯函数测试：闸门 27 的 `decode=8`
> 状态：**适配器通了，主页面还没换成真实数据源**（那是第二步）

---

## 0. 一句话

真的 wasm 装进来了：装载校验、观察解码、动作表、走一步、**拒绝逐字节不变**、一路打到终局，
全部在浏览器里对着 `web/rd_wasm.wasm` 跑通。**这一阶段没有改内核、没有改旧 `web/`。**

证据串：

```
UI_WASM PASS exports=234 content=0x54af44dd hand=5 enemies=2 steps=15 result=victory rejected-unchanged=1
```

---

## 1. 四个角色

| 文件 | 职责 | 纪律 |
|---|---|---|
| `wasm/host.ts` | **唯一**碰 `instance.exports` 的地方：装载校验、读文本、读观察、动作表、`step` | 校验失败抛 `WasmMismatch`（带诊断清单），不进入"半可用" |
| `wasm/snapshot.ts` | **纯函数**解码 148 格观察向量 → `CombatSnapshot` | 不碰 wasm，所以能拿合成向量穷举测（闸门 27） |
| `wasm/store.ts` | `GameStore` + 动作发起：`dispatch()` 前后各读一次向量并**比对** | 组件只读 `getSnapshot()`，不许自己调导出 |
| `p2probe.ts` | 接线探针页（`p2.html`）：只做 ABI，不画 3D | 与渲染分离，红了能一眼看出坏在哪一层 |

**"拒绝不产生成功演出"不是靠信任内核**：`dispatch()` 自己对比前后两条观察向量，
把 `unchanged` 一起返回（§纪律 8 的落地）。

---

## 2. 观察向量布局（148 格）

照 `kernel/rd-wasm/src/lib.rs` 的 `OFF_*` 常量。**长度由模块自己报**（`rd_env_observe_len()`），
本文件的下标表与 Rust 侧是"同一个词表两处认识"，护栏是装载校验 + 闸门 28 的真实战斗断言。

| 区段 | 下标 | 内容 |
|---|---|---|
| 头部 | 0–11 | round, turn, phase(0 等待/1 进行), result(0 进行/1 胜/2 负/3 平/4 中止), hp, hpMax, block, **ward(-1 未产生)**, energy, energyMax, 手牌数, 敌人数 |
| 英雄状态 | 12–16 | strength / vulnerable / weak / dexterity / frail（**ABI 顺序**） |
| 敌人 ×6 | 17–64 | 每槽 8 格：alive(1/0/**-1 无此槽**), hp, hpMax, block, ward, intentKind, intentDamage, 状态数 |
| 敌人状态 ×6 | 65–94 | 每槽 5 格，同上五轴 |
| 手牌 ×10 | 95–134 | 每槽 4 格：occupied(1/**-1**), cost(**-2 = X 费**), def_slot, upgraded |
| 牌堆 | 135–139 | 抽牌堆 / 手牌 / 弃牌堆 / 消耗堆 / 队列 —— **这些是计数，0 有意义** |
| 保留 | 140–147 | 恒 `-1` |

### 两条"空槽 vs 0"的坑

1. **敌人槽 `-1` 才是"没有这个敌人"**；`alive = 0` 是"有这个敌人但它死了"。把两者混起来会渲染出
   血量 0 的幽灵敌人。解码器还额外校验"header 报的敌人数 == 扫出来的敌人数"，不符就 `RangeError`。
2. **没有战斗会话时整条向量是 0**（不是 -1）。所以 `WasmHost.snapshot()` 先问
   `rd_env_active_slot() !== -3`，没有会话就**拒绝解码**（否则 6 个槽全是 `alive=0`）。

---

## 3. 踩到的三个坑（都留了注释）

### ① `_into` 的参数顺序**每个函数都不一样**

| 导出 | 签名 |
|---|---|
| `rd_env_card_name_into` / `_card_text_into` / `_enemy_name_into` | `(index, ptr)` |
| `rd_run_boss_id_into` / `_event_id_into` / `_encounter_id_into` | `(ptr)` |
| `rd_run_deck_id_into` / `_event_label_into` | `(index, ptr)` |

我原来写了个 `readText(lenFn, intoFn, arg)` 固定按 `(ptr, arg)` 调 ⇒ 症状是 `_into` 返回 -1
（把槽位当成了指针）。改成**传两个闭包**（取长度 / 写进 ptr），顺序在调用点显式写出来。

### ② `memory` 是对象，不是函数

"导出必须存在"的检查按 `typeof === "function"` 过滤，于是对**每一份** wasm 都报缺 `memory`。
`memory` 单独检查（要有 `ArrayBuffer` 的 `buffer`）。

### ③ 走到战斗不能"看到节点就 `begin_node`"

`pending` 有九档（1 篝火 / 2 商店 / 3 宝箱 / 4 奖励 / 5 事件 / 6 起始祝福 / 7 祝福选牌 /
8 事件选牌 / 9 事件候选）。第一版直接循环 `begin_node`，卡在 `pending = 7`。
照 `native/ui_abi_dump.mjs` 的 `walkToFightNode` + `settleHere` 移植：**每跳顶部先看 pending**，
站在未结算的战斗节点上才 `fight_begin`。

---

## 4. 闸门 28 断言了什么

| 断言 | 为什么它值钱 |
|---|---|
| 装载校验通过（导出/长度/哨兵/指纹） | 失配时**拒绝**而不是半可用 |
| `manifest.sha256 === web/rd_wasm.wasm 的 sha256` | **单一构建产物**（第十二轮 Review §2.5）：不存在第二个来源不明的二进制 |
| 开局 → 走到战斗（`in_fight = 1`） | 走路逻辑对（含九档 pending 的结算） |
| 起手 5 张 / 80 血 / 3 能量 / 2 敌人 | 解码与内核一致 |
| 每张手牌费用是数字或 X（不是 -1） | "未产生"没有被当成数字 |
| **只有被指的敌人掉血**（28→22），另一个不动 | 目标不串位 |
| 能量按费用扣（3→2）、手牌数减一（5→4） | 动作真的生效 |
| 越界动作 `-1` 且**逐字节不变** | "拒绝不产生成功演出"的硬证据 |
| 结束回合后 round 1→2、hp 80→68 | 时间与局面真的前进 |
| 15 步打到 `victory`，终局动作表为空 | 一整场能打完 |

### 两条被我自己写错的断言（值得记）

- **"打出的那张牌离开了手牌"**：打出槽 0 后手牌是 `[0,1,2,3]` —— **槽位是位置、被压实**，
  不是身份。这正是第十三轮 Review P2-A 说的"`handSlot` 不是 `CardInstanceId`"。
  改成断言"手牌数减一"。
- **"回合数前进"**：`endTurn` 后敌人行动再回到英雄回合，实测 `turn 1→1` 而 `round 1→2`。
  改成断言"时间或局面动了"（turn/round/hp 任一）。

### 一条需要挑牌的断言

内核为"每张可出的牌 × 每个活敌人"都发一条动作（`env-abi.md` §5：过度指定目标无害），
所以 `(防御, 敌人0)` 也是合法动作 —— 但防御不碰敌人。第一版拿手牌槽 0 直接断言"掉血"，
那张恰好是 `defend`。现在按**卡牌文本里有 `damage`** 挑一张（内容是英文，够用），没有就跳过。

---

## 5. 第二步（已完成）：主页面接真 wasm

`CombatView` 是渲染层唯一认识的数据形状，两个生产者（`viewFromMock` / `viewFromWasm`）填它。
字段名刻意与 P1 的 `MockScene` 一致 ⇒ 换数据源只改了类型与 import，**一行渲染逻辑都没动**。

落点表也进了视图（`view.optionsFor`）：wasm 那边直接读内核动作表，`actionIndex` 就是
`rd_env_step` 的入参。UI 不再自己算"能不能打这个敌人"。

| 模式 | 触发 | 守什么 |
|---|---|---|
| mock | `?mock` | P1 的 94 条渲染/手势断言（确定局面） |
| wasm | 默认 | P2 的数据源断言 |

### 一处"半可用"被当场抓住

第一版 `view = MOCK_MODE || !wasmView ? viewFromMock(scene) : wasmView` —— wasm 没装载好时**静默
用 Mock**。闸门 29 前几条立刻绿了：`mode()` 说 `wasm`，视图里却是 10 张 `打击/防御`、72 血。
一副能拖能打却与内核无关的牌 = plan 明令禁止的"半可用"。改成空局面 + 状态条（装载中/失败原因）。

### 闸门 29 `ui-wasm-ui`

```
UI_WASM_UI PASS mode=wasm hand=4 energy=2 enemy0=28->22 dom-synced=1
```

从 UI 拖一张攻击牌：手牌 5→4、能量 3→2、**只有**被指的敌人 28→22，而且 **DOM 上的血量也变成
22/28**（不是只改了内存里的 view）。结束回合走内核动作：round 1→2、hp 80→68。

两处竞态（都是"读得太早"，会变成假红）：视图就绪 ≠ 布局就绪（`layout().cards` 由 `useFrame`
每帧写）；`endTurn()` 之后要等 React 重渲染再读 `view()`。

## 5b. 第三步（已完成）：待决选牌 + beat + 定向夹具

`rd_env_choice_kind` 有**十个**取值（1 消耗 / 2 弃抽 / 3 拿回手牌 / 4 复制 / 5 升级 / 6 放牌堆顶 /
7 拿进手牌免费 / 8 放牌堆底免费 / 9 立刻打出 / 10 按印刷价拿进手牌）。我第一版只写了 0/1/2 还用
`as` 强转 —— 夹具真喝了一瓶 Attack Potion，`kind` 返回 3 才暴露。现在十值联合 + 一张动词表，
闸门 27 断言"十种都能写出句子且互不相同"。

**真夹具用 Elixir 造问句**（会问句的牌都不在起手牌里，随机抽不算夹具）：
`rd_run_grant_potion` + `rd_env_use_potion` ⇒ `source=1 kind=1 min=0 max=5`，勾一张确认 ⇒
**消耗堆 0→1、手牌 5→4**。

**beat** 接了 13 种 kind，出牌后的提示条文案来自内核叙述（实测 `bash`：
`cardPlayed` → `damage 8` → `statusChanged vulnerable +2`），`beats_dropped > 0` 会明说。

**定向夹具**：同名卡（打最后一张、只少一张、槽位压实）、0 能量（动作表里没有买不起的牌）、
敌人槽位稳定（`[0,1]`→`[0,1]`，死掉的敌人仍在向量里 `alive=false`）。
**X 费扣能量当前不可达**（起手牌不含、药水候选不含），只覆盖解码层 —— 这条写进闸门输出，
不静默跳过。

## 5c. 中文映射表（§359）

`native/build_zh_i18n.py` 生成 `web-next/src/i18n/zh.ts`：内容 id → 中文名/介绍，494 条
（卡 267 / 遗物 138 / 药水 30 / 怪 46 / 状态 13）。

主来源是 **spire-archive**（从游戏文件解析的 13 语言库，`/api/sts1/...`）；仓库自己的
`sts/content/*.json` 用来**交叉核对**，两边有 8 处不一致 —— 都是仓库里的旧中文缩写
（`iron_wave` 铁斩 vs 官方铁斩波、`cleave` 顺劈 vs 顺劈斩…）。灰机中文 wiki 被 Cloudflare 挡，
只能靠 search snippet 抽查：`铁斩波` = Iron Wave 与 `打击` = Strike 都**站在 spire-archive 一边**，
所以采用官方名。

回退链三层：精确 → 剥掉所有 `+` 查基础（名字补回 `+`）→ **返回 id 本身并计数**。
第三层是为了让"没翻译"看得出来：静默回退成英文会假装翻译过。闸门 29 断言"这一局回退数 = 0"。

已知不精确：`+` 变体的介绍沿用基础文本（126 条，来源只给英文升级描述）；28 张特殊/衍生牌
（`insight` / `shiv` / `omega` …）不在来源里；状态 13/150（`powers` 端点只给英文）。

## 5d. 横屏队形的退化（§360）

截图里横屏两个怪上下叠着，看着像竖屏。查下来**不是迁移腐坏**：参考包横屏用 `ceil(n/2)` /
`floor(n/2)`，`n = 2` 时"每排各一名"，而每排只有一名时 `rowX` 返回同一个 `mid` ⇒ x 相同、y 不同
⇒ 竖着叠。这条公式在小数量下退化。

改成 `n ≤ 4` 只用一排（`n > 4` 才 `ceil/floor`），只有一排时竖直居中。闸门 27 原来断言的正是
`ceil/floor` —— 等于把错的规则验证了一遍；现在换成新规则并加了四条退化守卫（n=2 同排、x 分开、
y 相同；n=4 一排；n=5 是 3+2），证据串加 `rows=4`。

## 6. 还没做的

- **卡名是定义 id**（`bash` / `strike` / `defend`）：`rd_env_card_name_*` 返回定义 id，本地化是后续的事；
- **待决选牌（`PendingChoice`）**：`rd_env_choice_*` 一族没接。战斗中出现选牌时动作表为空，
  闸门 28 的循环会把这种情况标成 `stuck` 并停止（**不假绿**）。
- **Beat（1–13 类演出）**：`rd_env_beat_*` 没接。目前 UI 靠观察向量 diff（`diffObservations`）。
- **同名卡 / X 费 / 0 能量 / 敌人槽位稳定性**的定向夹具（plan P2 明确要求的那四条）——
  目前只覆盖了"X 费牌存在时解码正确"，没有覆盖"X 费牌打出去怎么扣能量"。
- **`web/` 仍可独立运行**：这一步没碰它，四道旧 web 闸门复跑全绿。
