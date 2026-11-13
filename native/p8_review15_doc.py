"""把第十五轮审阅的分析追加到审阅文档末尾。"""

import io

P = 'docs/vibe/Review_35bf81ac_3cc98cb_15_P3_P7.md'
t = io.open(P, encoding='utf-8').read()
assert '## 本地核实与处置' not in t

section = '''

---

## 本地核实与处置（第十五轮）

核实方式：对着 `3cc98cb` 的源码逐条读，**对 §5 的路径越界做了构造性复现**（Node `path.join`
+ `normalize`），其余靠代码接线判断。不重复审阅已经写对的推理，只记"成立 / 不成立 / 要补"。

### 一、逐条核实

| 审阅项 | 结论 | 证据 |
|---|---|---|
| §2 冻结只在按钮层 | **成立** | `blocked` 只喂给部分场景；`BlessingScene` / `RewardScene` / `EndScene` / `CombatScreen` **都没收到**；`RunStore.settleDefault()` 不检查；`CombatScreen` 走 `GameStore.dispatch` 完全绕过 |
| §3 两套遗物弹窗并存 | **成立**（且文案过期） | `RunApp.tsx` 仍渲染 `data-run-overlay`，写着"牌组选择器在 P4"（P4 早已完成），还带一个 `settleDefault()` 按钮；其下才是 `PickupOverlay`。两者都是 `.run-overlay` + `z-index:40` |
| §4 `SC-02b` 身份错 + 无继续 | **成立**（潜伏） | `EndScene` 的 `data-scene` 是 `over ? SC-12b : SC-12a`，`SC-02b` 走 `actCleared` 分支 ⇒ 报 `SC-12a`；`onContinue` 只在 `base === SC-12a` 时给 |
| §5 前缀检查不是目录边界 | **成立**（已复现） | `DIST` 无尾分隔符 ⇒ `/../dist-backup/private.txt` → `…\\web-next\\dist-backup\\private.txt`，`startsWith(DIST)` = **true**；`/legacy/../web-backup/x.txt` 同理 |
| §6 新入口无存档/回档/回放 | **事实成立** | `docs/ui-parity.md` §2 自己写了；内核导出齐全，缺的是界面 |
| §7 分级（P5a/P5b、P6 device、P7 gaps） | **同意** | 文档里写了，但 commit/README 的措辞确实比实际宽 |

### 二、审阅没点出、同样要记的一条

**闸门 34/36 都有 `domScene() == scene.base` 断言，却抓不到 §4** —— 因为 `SC-02b` 在当前内容下
不可达，那条断言**从未被执行过**。这是"断言存在 ≠ 断言生效"的又一例（与 §4.23"下限从没生效过"
同源）。修 §4 必须配一个**纯函数 + 单测**（把"哪一屏报哪个 `data-scene`"抽出来），而不是
只改 JSX —— 否则改完仍然没人守。

同样地：**闸门 42 测的是 `/../package.json`**，它恰好落在 `dist` 之外，所以"越界被拒绝"那条
一直绿着，而真正的失败模式（同前缀兄弟目录）没被测到。

### 三、同意 / 不同意

* **同意**：§2 是 P1（诊断说"已冻结"却不冻结，比没有诊断更坏）；§5 是 P2 但只需几行；
  §3/§4 是 P2；§6 是**发布判断**而不是代码回归。
* **补一条设计强化**：冻结必须是**粘性**的（第一次违约就置位，只能靠重开/刷新解除）。
  否则 `violations` 每帧重算、清空就自动解冻 ⇒ 玩家会在"半可信状态"里继续操作。
* **不同意一处措辞**：审阅说"不能把 P3–P7 不加限定地宣布为全部完成"—— 结论同意，但
  P3/P4 的**场景层**确实完成（18 屏可操作 + 闸门 33/34/36），缺的是"冻结语义"与"弹窗清理"
  这两条**横切**问题，不是场景没做完。

### 四、处置（按此顺序做）

| 序 | 任务 | 负控 |
|---|---|---|
| 1 | 统一冻结边界（`RunStore` 全部动作 + `GameStore` 注入 `dispatchGuard` + 粘性 `frozen`） | 注入一条 violations ⇒ 逐个入口尝试，观察向量逐字段不变、界面 fatal；清空注入后**仍然**冻结；重开才解冻 |
| 2 | 删掉旧 `data-run-overlay` fallback | 拾取态下只有 `[data-pickup]` 一个可交互模态，`data-overlay-settle` 不存在 |
| 3 | `serve.mjs` 用 `path.relative` 判目录边界 + 只对带 hash 的 assets 用 immutable | `../dist-backup/x`、`%2e%2e/dist2/x`、`/legacy/../web-backup/x` 全拒绝；正常路径仍通过 |
| 4 | `SC-02b` 独立身份 + 继续能力（抽成纯函数 `endSceneFor`） | 纯函数单测：`SC-02b` 报 `SC-02b`、能继续；`SC-12b` 不能继续 |
| 5 | 存档/导出（按"正式入口"发布定位） | 导出→刷新→导入，19 格逐字段相同；版本/校验不符**拒绝**并说明 |
'''

io.open(P, 'w', encoding='utf-8', newline='\n').write(t.rstrip('\n') + section)
print('appended')
