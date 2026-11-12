# P6 设备 / 性能 / 稳定性记录

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
