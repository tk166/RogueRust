"""port-plan §357 + ui-p2-adapter.md：P2 第二步（主页面接真 wasm）。"""

import io

PLAN = 'docs/port-plan.md'
DOC = 'docs/ui-p2-adapter.md'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


t = io.open(PLAN, encoding='utf-8').read()
anchor = '''### 残留

- **主页面换数据源**（`CombatView`）：`Stage`/`TextOverlay` 仍吃 `MockScene`；'''
assert t.count(anchor) == 1

addition = '''---

## §357 P2 第二步：主页面接真 wasm（`CombatView` 视图模型 + 双引擎）

主页面默认跑真内核。P1 的 Mock 局面保留在 `?mock` 下（它的 94 条断言建立在确定局面上）。

### `CombatView`：渲染层唯一认识的数据形状

`Stage` / `TextOverlay` 只认识"有几张牌、每张叫什么、敌人剩多少血"。两个生产者填它：

```
MockScene  ──┐
             ├──> CombatView ──> Stage / TextOverlay / HUD
wasm 快照  ──┘
```

字段名刻意与 P1 的 `MockScene` 一致（`hand` / `enemies` / `hero` / `turn`）⇒ 换数据源时渲染代码
**只改了类型与 import，一行渲染逻辑都没动**。

**落点表也进了视图**（`view.optionsFor(handSlot)`）：wasm 那边直接读内核动作表
（`actionIndex` 就是 `rd_env_step` 的入参），UI 不再自己算"能不能打这个敌人"。P1 的教训（§352）
就是 UI 自己猜落点。

### 双引擎

| 模式 | 触发 | 守什么 |
|---|---|---|
| mock | `?mock` | P1 的 94 条渲染/手势断言（确定局面） |
| wasm | 默认 | P2 的数据源断言（UI 必须与内核一致） |

### 一处"半可用"被闸门当场抓住

第一版写的是 `view = MOCK_MODE || !wasmView ? viewFromMock(scene) : wasmView` —— wasm 还没装载好
时**静默用 Mock**。闸门 29 前几条立刻绿了：`mode()` 说 `wasm`，视图里却是 10 张 `打击/防御`、
英雄 72 血 —— 一副能拖能打却与内核毫无关系的牌。这正是 plan 写的"失配时显示诊断，**不进入
半可用状态**"。

改成：默认路径 `view = wasmView ?? EMPTY_VIEW`（空局面），空局面时画布上盖一条状态条
（装载中 / 装载失败的原因）。

### 闸门 29 `ui-wasm-ui`（14 条断言）

| 断言 | 值 |
|---|---|
| 默认走 wasm、装载诊断通过 | `mode=wasm` |
| 手牌来自内核 | 5 张（`defend/defend/strike/strike+/strike`） |
| 每张牌可出（来自内核动作表） | 全 `true` |
| 敌人名字与血量来自内核 | `acid_slime_m 28/28`、`spike_slime_s 10/10` |
| **屏幕上的血量 == 内核里的血量** | `{"0":"28/28","1":"10/10"}` |
| 从 UI 拖一张攻击牌到敌人 | 手牌 5→4、能量 3→2、敌人 28→**22** |
| 其他敌人不动 | ✅ |
| **DOM 跟着内核变** | `{"0":"22/28","1":"10/10"}` |
| 结束回合走内核动作 | round 1→2、hp 80→68 |

证据串：`UI_WASM_UI PASS mode=wasm hand=4 energy=2 enemy0=28->22 dom-synced=1`

两处竞态（都是"读得太早"，会变成假红）：视图就绪 ≠ 布局就绪（`layout().cards` 由 `useFrame`
每帧写）；`endTurn()` 之后要等 React 重渲染再读 `view()`。

### 数字

闸门 28 → **29**；`web/` 的七道闸门复跑全绿（**旧页面仍可独立运行**）；units 1233、导出 234、
四条对拍不动。证据截图：`docs/ui-p2-real/1280x800-wasm.png`（真 wasm 的 UI，不是 Mock）。

### 残留

- **卡名是定义 id**（`bash` / `strike` / `defend`）：`rd_env_card_name_*` 返回的是定义 id
  （`ui-abi-audit.md` 早已注明"presentation only"），本地化是后续的事；
- **`PendingChoice`（`rd_env_choice_*`）没接**：出现选牌时动作表为空，闸门会停在那里（不假绿）；
- **Beat（1–13 类演出）没接**：UI 仍靠观察向量 diff；
- **同名卡 / X 费扣能量 / 0 能量 / 敌人槽位稳定性**的定向夹具还没写；
- 卡牌"种类"（配色）是按规则文本猜的（观察向量里没有），猜错只影响颜色。

### 残留

- **主页面换数据源**（`CombatView`）：`Stage`/`TextOverlay` 仍吃 `MockScene`；'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.replace(anchor, addition))

# ui-p2-adapter.md：把"第二步"从"还没做"改成"已做"
edit(
    DOC,
    '''## 5. 还没做的（第二步）''',
    '''## 5. 第二步（已完成）：主页面接真 wasm

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

## 6. 还没做的''',
    'doc step 2',
)

edit(
    DOC,
    '''- **主页面换成真实数据源**：`Stage`/`TextOverlay` 现在吃 `MockScene`，要改成吃
  `CombatSnapshot` + 名字查找（`rd_env_card_name_*` / `_enemy_name_*`）。计划里叫
  `CombatView` 这层 view model。
''',
    '''- **卡名是定义 id**（`bash` / `strike` / `defend`）：`rd_env_card_name_*` 返回定义 id，本地化是后续的事；
''',
    'doc residual 1',
)
print('docs updated')
