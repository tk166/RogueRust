"""P5 文档：port-plan §365 + README + docs/ui-p5-beats.md + i18n 事件表说明。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── port-plan §365 ─────────────────────────────────────────────────────────
PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
assert '## §365' not in t

section = '''

---

## §365 P5 交付：Beat 演出、事件 i18n 对照表与幕间推进

plan P5 的退出条件：**关闭动画也能完整游戏；播放动画的最终状态与内核完全一致；没有因动画丢失
而卡住待决流程**。这一节记的是它怎么做到的，以及**明确没做的**（GLB 资产）。

### 365.1 演出层：导演是**纯函数**

`web-next/src/combat/beats.ts`：

```
Beat[]（内核的 1–13 类）─► planBeats(beats, dropped) ─► BeatEffect[]
                                                          │
             advance(state, dtMs) ◄── 每帧 ─────────────────┘
                     │
                     ▼
             BeatLayer（DOM 飘字，坐标来自 layout）
```

三条结构性保证：

1. **演出不持有状态**：这一层只读 beat、只产出"屏幕上要飘什么"。局面永远来自内核观察向量 ⇒
   "最终状态与内核一致"不是因为小心同步，而是因为**演出层根本没有第二个状态**。
2. **未知 kind 不中断**：内核加了新 kind 而 UI 没跟上时降级成中性 `?N` 并**计数**
   （`BEAT_DESTROYED = 13` 曾经就是这么被静默吞掉的）。
3. **`dropped > 0` 要能看见**：内核因容量丢了 beat 时，界面必须说出来（"动画不全"），
   而不是安静地少播几下。

关掉动画（`?motion=off` 或系统 `prefers-reduced-motion`）只是"一条都不播" —— **不是另一条
代码路径**，所以"关动画也能完整游戏"同样成立。

⚠️ **实测坑**：无头 Chrome 的 `prefers-reduced-motion` 是 `reduce`，所以"动画开着"必须由
`?motion=on` **显式**要求。第一版没有这个开关，闸门里 `reducedMotion` 一直是 `true`，
一条都没播却"看起来通过了"。

另外两个实测坑（都是"看起来像动画没跑"）：
* rAF 的 `last` 时间戳写在 effect 闭包里 ⇒ 依赖是 `director`，每帧重建 effect 就把它重置成
  "现在"，`dt` 恒 0、`elapsed` 恒 0（动画卡在第一帧）。必须放 **ref**。
* 探针的 `beats()` 闭包捕获的是 `installProbe` 那一刻的 `director` ⇒ 永远返回旧快照
  （`elapsed: 0`）。必须读 **ref**。

### 365.2 演出来源下移到 `GameStore`

`dispatch` 有**两条**调用路径（界面拖拽提交、探针/驱动的 `dispatchCombat`）。第一版把
"规划演出"放在界面提交路径里，于是"探针打出来的战斗没有演出"。现在 `GameStore` 记住
最近一次的 `beats` + 自增 `seq`，消费方只看 `seq` 变没变 —— 谁 dispatch 谁就有演出。

### 365.3 资源降级（`stage/assets.ts`）

`enemyLook(id)`：内容 id → `{shape, tint, scale, boss}`（程序化外观）；**未知 id 降级成
`placeholder` 并计数**（`unknownEnemyAssets()`），闸门断言它为空。

⚠️ **明确没做**：plan P5 要的"首批原创低多边形 GLB 角色 + AssetRegistry"。这一版**没有资产
管线**（没有美术、没有导出工具）。写一个假的 GLB 加载器只会让"资产缺失"看起来像"资产有了"，
所以这一版只做**表 + 降级**，把 GLB 留给有资产的那一轮。

### 365.4 幕间推进是内核动作

`rd_run_end_act` 是内核动作（§344 之前它只是页面上的 `runOver` 布尔）。`EndScene` 的"继续"
接的是它，**不是** `settleDefault`。闸门 38 断言：Boss 之前调用必须被**拒绝**（`-2`）、场景
不变、日志写清原因 —— 而不是"点了没反应"。

⚠️ **未覆盖**：真正的"打赢 Boss → 幕间 → 第二幕"需要一场能赢的 Boss 战。当前旅程的自动
出牌策略打不过第 16 层，所以这一段只有**拒绝路径**与**路由**（闸门 33 的合成夹具）在守。

### 365.5 事件 i18n 对照表（`native/zh_events.py`）

内容的 `EventNodes` 只有英文正文（`TextKey`），**没有事件名**；名字只能来自官方数据。
所以：

| 项 | 来源 | 判据 |
|---|---|---|
| 事件名（36 个根 id） | `spire-archive.com/api/sts1/events`（13 种语言） | 36/36 有名字 |
| 事件正文 | 同上（官方中文 `description`） | 35/36（`wandering_merchant` 不在 API） |
| id 对照 | **显式别名表** `EVENT_ALIASES` | `scrap_pile` ↔ `SCRAP_OOZE`、`ancient_writing` ↔ `BACK_TO_BASICS`… |
| 选项标签（32 条） | API 官方中文 + 人工确认 | 能对上的用官方译法，其余手译标 `[推断]` |
| 子节点正文 | **没有**官方来源 | 回退英文并**计数**（`eventI18nFallbacks()`） |

别名的判据：脚本按**英文正文的词重叠**给候选（`forgotten_altar` 16 分、`nloth` 22 分…），
再人工确认；弱重叠的 5 条（`old_shrine`/`ancient_forge`/`purification_shrine`/
`council_of_ghosts`/`the_ssssserpent`）在文件里标了 `[推断]`。

闸门 27 断言的不是"有多少条"，而是三件具体的事：**每一个**根 id 都有中文名、选项标签能翻、
**子节点回退必须被计数**（静默显示英文会让"没翻译"看起来像"本来就这样"）。

### 365.6 数字

闸门 36 → **38**；`ui-beats` 覆盖 13 种 kind + 未知降级 + dropped + skip + 关动画 + 资源降级；
`ui-next-p5` 三组端到端（动画开 / 动画关 / 幕间拒绝）；事件 i18n 36 名 / 32 标签；
units 1233、导出 234、四条对拍不动。新增 `docs/ui-p5-beats.md`。

### 365.7 还欠的

* **GLB 资产与动画命名**（见 365.3，需要美术与导出管线）；
* **完整幕间**（打赢 Boss 的 E2E，见 365.4）；
* 事件的**子节点正文**仍是英文（没有官方中文来源；已计数）；
* `SC-02b`（幕尽头）在当前内容下仍不可达（地图走完即 `RunEnd`）。
'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + section)

# ── README ─────────────────────────────────────────────────────────────────
edit(
    'README.md',
    '''**聚合验收**：36 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice`、`ui-wasm-fixtures`、`ui-wasm-xcost`、`ui-scene`、`ui-next-loop`、`ui-p4-models` 与 `ui-next-p4`），一道红就整体红''',
    '''**聚合验收**：38 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice`、`ui-wasm-fixtures`、`ui-wasm-xcost`、`ui-scene`、`ui-next-loop`、`ui-p4-models`、`ui-next-p4`、`ui-beats` 与 `ui-next-p5`），一道红就整体红''',
    'readme gates',
)

# ── 新文档 ─────────────────────────────────────────────────────────────────
doc = '''# P5 Beat 演出与资源降级

> 代码：`web-next/src/combat/beats.ts`（纯导演）、`BeatLayer.tsx`（DOM 飘字）、
> `web-next/src/stage/assets.ts`（外观表 + 降级）。闸门 37（纯函数）与 38（端到端）。

## 1. 数据流

```
内核 rd_env_beat_*（kind 1–13）
        │  GameStore.dispatch 记住 lastBeats + seq（两条 dispatch 路径共用）
        ▼
planBeats(beats, dropped) ──► BeatEffect[]（tone / text / at / duration）
        │
        ▼  enqueue（不打断正在播的那条）
advance(state, dtMs) ◄── rAF（`last` 在 ref 里）
        │
        ▼
BeatLayer：DOM 飘字，坐标来自 layout（与 3D 同一套投影）
```

## 2. 三条结构性保证

| 保证 | 为什么成立 |
|---|---|
| 播放动画的**最终状态与内核一致** | 演出层**不持有状态**：它只读 beat、只产出飘字。局面永远来自内核观察向量 |
| **关闭动画也能完整游戏** | 关动画 = `reducedMotion` ⇒ 队列一条都不入，不是另一条代码路径 |
| **动画不卡住待决流程** | 演出是 `pointer-events: none` 的覆盖层；下一条动作与动画播放无关 |

## 3. 降级（plan 明确要求的三条）

| 情况 | 行为 |
|---|---|
| 未知 beat kind | 降级成中性 `?N` 飘字 + **计数**（`unknownKinds`），永不抛 |
| 内核丢 beat（`dropped > 0`） | 界面上挂一条"动画不全（丢了 N 条）" |
| 未知 enemyId | `enemyLook()` 返回 `placeholder` + 计数（`unknownEnemyAssets()`） |

## 4. 跳过与快进

* 队列非空时右下角有"跳过（Esc）"按钮；Esc 也走同一个 `skipAll`。
* `skipAll` **不清账**：`dropped`/`unknownKinds` 仍然保留（跳过的是动画，不是事实）。
* 快进 = 一次 `advance(state, 很大的 dt)`：余量会**结转**给下一条（慢帧率下动画不会拖长）。

## 5. 三个实测坑（都是"看起来像动画没跑"）

1. **无头 Chrome 的 `prefers-reduced-motion` 是 `reduce`** ⇒ 闸门里默认不播。
   "动画开着"必须 `?motion=on` 显式要求。
2. **rAF 的 `last` 写在 effect 闭包里**：依赖是 `director`、每帧重建 effect，于是它被重置成
   "现在"、`dt` 恒 0、`elapsed` 恒 0（卡在第一帧）。必须放 **ref**。
3. **探针闭包捕获旧 state**：`beats()` 若捕获 `installProbe` 那一刻的 `director`，会永远返回
   旧快照。必须读 **ref**。

## 6. 明确没做

**GLB 角色与 AssetRegistry**（plan P5 的第二条）。这一版没有资产管线，所以只做了
"表 + 降级"：写一个假加载器会让"资产缺失"看起来像"资产有了"。
'''
io.open('docs/ui-p5-beats.md', 'w', encoding='utf-8', newline='\n').write(doc)
print('docs written')
