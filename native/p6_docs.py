"""P6 文档：port-plan §366 + README + docs/ui-p6-devices.md（可复现的性能记录）。"""

import io


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


PLAN = 'docs/port-plan.md'
t = io.open(PLAN, encoding='utf-8').read()
assert '## §366' not in t

section = '''

---

## §366 P6 交付：移动端、性能与稳定性

plan P6 的退出条件：**提供可复现的设备/浏览器/尺寸/性能记录；主要操作在移动端可以完成；
无未解释的持续内存增长或输入失效**。这一节记的是测了什么、量到什么，以及**明确没测的**
（真机）。

完整记录在 `docs/ui-p6-devices.md`。

### 366.1 移动端（闸门 39 `ui-mobile`）

**触屏**用 CDP 真触摸事件（`Emulation.setTouchEmulationEnabled` + `Input.dispatchTouchEvent`），
不是鼠标点一下 —— 触摸才有长按详情、没有 hover、并且**会被祖先滚动容器抢走手势**。

| 项 | 实测 |
|---|---|
| 触控目标 | 窄屏下**所有** `button`/`input` ≥ 44×44（实测 5 个，最小边 44） |
| 横向溢出 | `scrollWidth - clientWidth == 0` |
| 触摸走完整流程 | 开始 → 祝福 → 地图 → 战斗 → **触摸拖牌**打中敌人（28→22）→ 奖励 → 地图 |
| 安全区 | `?safe=44,34` ⇒ 顶栏 `top = 44`、日志 `bottom = 810`（视口 844） |
| 弹窗 | 装得下或能滚到底（不会"超出但滚不动"） |

**三个实测坑**：

1. **触摸拖牌一开始完全无效**：祖先 `.run-main { overflow: auto }` 把触摸当成滚动，
   浏览器发 `pointercancel` ⇒ 状态机 `cancel` ⇒ 回弹（`illegal-target`）。
   修法是给战斗屏 `touch-action: none`（**在祖先上也要挡住**，不只是 canvas）。
2. **触控目标差 1px 就红**：逐个列选择器漏了标题页表单里的开始按钮（98×43）与两个输入框
   （40 / 16 高）。改成"窄屏下 `.scene` 里所有 button/input 都 ≥ 44"，规则从"我记得的那些"
   变成"全部"。
3. **DPR 上限的断言一开始恒真**：默认视口的 `deviceScaleFactor` 是 1，上限 1.5 根本没被触发。
   必须把 dsf 调成 3 才测得出（与 §4.23 "下限从没生效过"是同一类错误）。

### 366.2 性能（量出来的，不是估的）

| 项 | 数字 |
|---|---|
| 画布后备像素（390×601，dsf 3） | 上限 1.5 ⇒ **585×900 = 526,500**；不设上限会是 1,170,000（**-55%**） |
| 帧间隔（120 帧采样，战斗中） | 中位 **16.7ms** / p95 **16.8ms** / max 16.8（rAF 限速在 60fps） |
| wasm | 1,364,016 B |
| JS（战斗屏那块） | 1,483,329 B（three.js + `@react-three/uikit`） |
| uikit 的 Inter 字体图集 | 423,247 B（base64 WebP）—— **它没有中文字形**，所以 HUD 的中文靠 DOM 覆盖层 |
| 其它 chunk | run 61,078 / store 19,088 / worker 41,907 / p2 6,143 |

**做了一刀**：窄屏 DPR 上限 1.5（`stage/perf.ts` 的 `dprCapFor`，界面与探针读**同一份**规则）。
**记录但没做**：字体图集（423 KB）与 GLB —— 前者要改 HUD 的实现方式（plan P1 要求 uikit），
后者没有资产管线（§365.3）。

### 366.3 稳定性（闸门 40 `ui-soak-p6`）

| 项 | 实测 |
|---|---|
| 连开 8 局 | 每局都能走到地图、对账干净、`floor == 0` |
| 堆内存趋势 | 7,275 KB → 7,600 KB（+325 KB，判据是"后 4 次 ≤ 前 4 次 × 1.5 + 4 MB"） |
| 长局 | 26 步无对账失败、无死路 |
| 重新载入 | `location.reload()` ⇒ 回到标题、没有残留的局 |
| **WebGL 上下文丢失** | 真丢一次 ⇒ 诊断横幅 + "重新初始化" ⇒ 画布回来、**战斗还在**（局面在内核里）、还能出牌 |
| 动效偏好 | 设置里选"关" ⇒ `localStorage.rd.motion = off` ⇒ 重载后战斗屏仍关（0 条飘字） |

上下文丢失这条是 P6 最值得做的一条：真机上切后台/GPU 重置就会发生，而**什么都不做**的后果是
一片黑屏 —— 玩家会以为游戏卡死。现在 `preventDefault()` + 横幅 + 重挂 canvas，局面在内核里
所以不需要重打。

### 366.4 明确没测（本仓库的边界）

* **真机**（iOS Safari / Android Chrome）与真机安全区 inset —— 只有 CDP 仿真；
* **GPU 侧的性能**（draw call、显存）—— 无头软件光栅的数字没有意义，所以只记 rAF 帧间隔；
* **长时 soak**（小时级）与内存曲线 —— 只做了 8 次重开 + 26 步长局的趋势检查。
'''

io.open(PLAN, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + section)

edit(
    'README.md',
    '''**聚合验收**：38 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice`、`ui-wasm-fixtures`、`ui-wasm-xcost`、`ui-scene`、`ui-next-loop`、`ui-p4-models`、`ui-next-p4`、`ui-beats` 与 `ui-next-p5`），一道红就整体红''',
    '''**聚合验收**：40 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice`、`ui-wasm-fixtures`、`ui-wasm-xcost`、`ui-scene`、`ui-next-loop`、`ui-p4-models`、`ui-next-p4`、`ui-beats`、`ui-next-p5`、`ui-mobile` 与 `ui-soak-p6`），一道红就整体红''',
    'readme gates',
)

doc = '''# P6 设备 / 性能 / 稳定性记录

> 闸门 39 `ui-mobile`、40 `ui-soak-p6`。所有数字都可以用文末的命令重跑。

## 1. 环境（可复现的前提）

| 项 | 值 |
|---|---|
| 浏览器 | 仓库自带的 headless Chrome（`web/cdp.mjs` 启动，静态服务器同源） |
| 视口 | 390×844（手机竖屏）/ 834×1112（平板）/ 1280×800（桌面） |
| 设备像素比 | 3（手机，真机量级）/ 1（其余） |
| 触摸 | `Emulation.setTouchEmulationEnabled` + `Input.dispatchTouchEvent`（真触摸事件链） |
| 页面 | `web-next/dist/run.html`（产品路径） |

⚠️ **没有真机**。这一版的所有移动端结论都来自 CDP 仿真：触摸事件链是真的，但 GPU、真机安全区
inset、iOS Safari 的行为都没有覆盖。

## 2. 触控与排版（闸门 39）

| 项 | 实测 | 判据 |
|---|---|---|
| 触控目标 | 5 个可点元素，**最小边 44px** | 窄屏下 `.scene` 里所有 `button`/`input` ≥ 44×44 |
| 横向溢出 | 0 | `scrollWidth - clientWidth <= 1` |
| 触摸完整流程 | 开始 → 祝福 → 地图 → 战斗 → 奖励 → 地图 | 每步都用真触摸事件 |
| 触摸拖牌 | 敌人 28 → 22，只打中被指的那个 | 与闸门 29（鼠标）同一条语义 |
| 安全区 | `?safe=44,34` ⇒ 顶栏 `top=44`、日志 `bottom=810` | 内容真的让开，不是"我写了 env()" |
| 弹窗 | 装得下或能滚到底 | 不出现"超出但滚不动" |

## 3. 性能（量出来的）

```
视口 390×844，dsf 3，战斗中：

CSS 画布            390 × 601
后备像素（上限 1.5） 585 × 900   = 526,500 px
不设上限（dsf 3）    1170 × 1803 = 2,109,510 px   ⇒ 上限省 75%
上限 2（旧行为）     780 × 1202  =   937,560 px   ⇒ 上限 1.5 再省 44%

帧间隔（120 帧）     中位 16.7ms · p95 16.8ms · max 16.8ms（rAF 限速 60fps）
```

| 产物 | 字节 |
|---|---|
| `rd_wasm.wasm` | 1,364,016 |
| `CombatScreen-*.js`（three.js + uikit） | 1,483,329 |
| `inter-*.js`（uikit 的 Inter 字体图集，base64 WebP） | 423,247 |
| `run-*.js` | 61,078 |
| `store-*.js` | 19,088 |
| `worker-*.js` | 41,907 |

### 做了的优化

**窄屏 DPR 上限 1.5**（`web-next/src/stage/perf.ts` 的 `dprCapFor`）：手机 GPU 上最直接的一刀，
肉眼看不出差别（390 CSS px 宽、1.5 倍已比 1080p 的横向采样更密）。界面与探针读**同一份**规则
（第一版两处各写一份，闸门量的可能是另一份）。

### 记录但没做

| 机会 | 量级 | 为什么没做 |
|---|---|---|
| 字体图集 | 423 KB | uikit 的默认字体（Inter，**无中文字形**）；换掉它要改 HUD 的实现方式（plan P1 要求 uikit） |
| GLB 角色与共享材质 | 未知 | 没有资产管线（见 `docs/ui-p5-beats.md` §6） |
| three.js 按需引入 | 未知 | 战斗屏依赖 uikit + drei，拆包要重做 HUD |

## 4. 稳定性（闸门 40）

| 项 | 实测 |
|---|---|
| 连开 8 局 | 全部走到地图、对账干净、`floor == 0` |
| 堆内存 | 7,275 KB → 7,600 KB（+325 KB） |
| 长局 | 26 步，无对账失败、无"被拒绝的死路" |
| 重新载入 | 回到标题（`SC-00`），没有残留的局 |
| WebGL 上下文丢失 | 真丢一次 ⇒ 横幅 + "重新初始化" ⇒ 画布回来、战斗还在、还能出牌 |
| 动效偏好 | 选"关" ⇒ `localStorage.rd.motion=off` ⇒ 重载后仍关（0 条飘字） |

## 5. 怎么重跑

```
node native/ui_mobile_check.mjs      # UI_MOBILE PASS ...
node native/ui_soak_p6_check.mjs     # UI_SOAK_P6 PASS ...
powershell -File tools/acceptance.ps1  # 40 道闸门
```

单看性能数字：`node native/_dbg_perf.mjs`（一次性探针，不进闸门）。
'''
io.open('docs/ui-p6-devices.md', 'w', encoding='utf-8', newline='\n').write(doc)
print('docs written')
