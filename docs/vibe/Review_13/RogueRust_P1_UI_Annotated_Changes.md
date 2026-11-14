# RogueRust P1：左右战场布局 + 鼠标/触摸反馈（注释化示例）

**基线**：公开仓库 `bf7c7f5107dad96f54d1dab95b0f7d728d661b76` 的 `web-next/`。这是一组可应用的**局部示例修改**，不是已经提交到用户仓库的代码，也不是 V2 内核改造。

**改动范围**：`web-next/src` 下 5 个原文件、2 个新纯函数文件。不修改 Rust/WASM、P0 ABI、旧 `web/` 或构建依赖。

> 建议在新分支或临时 worktree 内使用。脚本默认只执行锚点检查，不写磁盘。所有锚点检查完毕后，才允许 `--apply`。若本地 Agent 已经更新这些函数，脚本会拒绝自动套用；应人工比较语义，不要为了套补丁覆盖已有功能。

## 应用方法

从自己的 RogueRust 工作目录执行（先提交或保存现有工作）：

```bash
python /path/to/this-bundle/apply_p1_ui_example.py .
# 全部锚点找到后，才执行下面这一行：
python /path/to/this-bundle/apply_p1_ui_example.py . --apply
cd web-next
npm ci                   # 已安装依赖可跳过；若无 lockfile 用 npm install
npm run build            # 必须在真实仓库中验证 TypeScript + R3F
npm run dev
```

运行纯函数测试：

```bash
bash /path/to/this-bundle/scripts/run-pure-tests.sh /path/to/RogueRust
```

视觉检查建议：启动 Vite 后访问默认场景、`?debug&enemies=1`、`?debug&enemies=3`、`?debug&enemies=6`。其中 `enemies=N` **只在同时存在 `debug` 查询参数时生效**，并且只修改 P1 Mock 局面。测试 390×844 和 1280×800 两种视口。

## 每个文件的改动与详细意图

| 文件 | 具体变更 | 为什么这样做 |
|---|---|---|
| `stage/formation.ts`（新增） | `computeCombatFormation(slots, viewport)`，横屏两排（ceil/floor、每排≤3），竖屏单列，我方固定在左 | 布局规则从 `useFrame` 中解耦，可以做纯函数回归测试；不使用数组下标替代业务敌人 slot |
| `stage/Stage.tsx` | 用阵型纯函数替代 `index===0 ? -enemyX : enemyX`，保留原有动画/命中分离 | 让 1–6 个敌人自动布局，角色 Mesh 可继续复用；不为队形改变游戏规则 |
| `stage/Stage.tsx` | 鼠标 hover 轻抬、选中卡固定预览、拖拽跟随、敌人可选/命中环、有效目标连线 | hover / press / target 是不同视觉语义；指针松开后预览不粘住手指；粒子系统不是当前 PoC 前提 |
| `stage/Stage.tsx` | `useFrame` 插值改为 `1-exp(-speed*deltaTime)` | 30/60/120Hz 接近相同的跟随手感；`?still` 仍允许确定性截图 |
| `input/hitTest.ts`（新增） | 屏幕坐标敌人命中、卡牌露出条命中 | 全局 pointerup 离开 R3F 命中对象仍能判定目标；只使用 Stage 的屏幕投影，不复制一份相机数学 |
| `input/pointerMachine.ts` | `resultSeq`，无目标牌提交映射统一到 `slot=-1`，新增 `dismiss` | 修复重复相同动作被 JSON 去重吞掉、无目标牌丢到敌人上回弹、长按开详情误出牌三个既有问题 |
| `App.tsx` | 维护唯一 activePointer、真实位移、450ms 长按、取消、失焦、第二指针隔离 | 鼠标和触摸走同一状态机，真实拖动阈值不再强制写 `999px`；不让手势状态进入 WASM |
| `App.tsx` | 右键详情、视觉提示、`?debug&enemies=N` | 详情可被真实用户打开；允许无代码改动测试 1–6 敌人布局，正式游戏路径不暴露调试造怪 |
| `overlay/TextOverlay.tsx` | 鼠标悬停标题可读，详情增加可见关闭按钮 | 不要求用户只会使用 Esc 或调试探针；DOM 字体仍保留可读性，不改成高成本卡面纹理 |
| `styles.css` | hover 描边/提示气泡/详情按钮焦点样式 | 信息提示不吞掉 3D 射线；模态层继续是唯一拦截输入的覆盖层 |

代码中 `// [P1-LAYOUT]`、`// [P1-UX]` 为设计说明锚点，Agent 可据此对照每项修改意图。

## 横竖屏编队规范

- **玩家始终在左**，不随着敌人数改变阵营方向。
- **portrait（高 > 宽）**：敌人在右侧从上到下排成一列，最多六名；密度增大时适当缩小模型，不隐藏实体。
- **landscape（宽 ≥ 高）**：敌人在右侧按上行 `ceil(N/2)`、下行 `floor(N/2)` 分布；每行 1–3 名（当 N=1 时自然只有一行）。例如 5 名对应 3+2，6 名对应 3+3。
- 槽位标识从 `scene.enemies[].slot` 获取，不用 `index` 代替游戏身份；两个同名敌人也有独立槽位。
- **超出 6 名**：显式 `RangeError`，不是静默截掉第 7 名。正式接入若真实玩法允许 >6，先扩展 UI 规则并添加验收再解除限制。
- 现有扇形手牌仍位于下方，**左右**要求指战场角色站位，不意味着把手牌改成左侧竖排。

## 手势语义与反馈

| 输入 | 行为 | 反馈 | 不改变什么 |
|---|---|---|---|
| 鼠标进入手牌 | 不直接出牌 | 轻抬、标题显示、grab 光标 | 不改游戏状态 |
| 鼠标左键点有目标牌 | 进入待目标状态 | 卡牌预览固定在战场偏左下，合法敌人蓝环 | 尚不执行 Action |
| 鼠标左键点击合法敌人 | 提交 | 绿环、瞄准线、状态提示 | 不由 UI 自行扣血（P2 交给 WASM） |
| 鼠标按住拖动目标牌 | 超过 8 CSS px 进入拖拽 | 卡牌跟随指针、敌人目标高亮、瞄准线 | 不依赖假 `distance=999` |
| 无目标牌拖到敌人上 | 释放可提交 | 明确操作反馈 | 业务目标仍为 `slot=-1` |
| 右键卡牌 | 打开详情 | 完整规则、关闭按钮、Esc | 不触发出牌 |
| 触摸点按有目标牌 | 选择卡牌 | 大卡预览，右侧敌人可被点按 | 不能在未选目标时扣血 |
| 触摸长按 ≥450ms | 详情 | 完整文字、可见关闭按钮 | 后续 pointerup 不触发 Action |
| 触摸拖动 | 按相同状态机执行 | 移动预览与命中反馈 | 其他手指不可接管第一指针 |
| pointercancel / blur / Esc | 中断操作 | 回弹提示、清除目标 | 不留下待提交的悬空动作 |

**提醒**：此示例保留既有 P1 Mock 的 `applyCommit()` 行为，用来演示操作链路。它**并未**接入真实 WASM Action，也没有替代下一阶段 `GameSnapshot / GameBeat / ActionDispatcher`。

## 验收矩阵（必须在真实浏览器运行）

1. 1280×800：单敌、2 敌、3 敌、5 敌、6 敌：英雄左、敌人右，分别为 1、1+1、2+1、3+2、3+3。所有敌人可见、标签可读。
2. 390×844：1–6 敌全部右侧纵向单列，角色不碰敌人、最下方敌人不压手牌。
3. 鼠标：hover 选中的是鼠标下那张卡；重复两次同样 Action 均提交；对空白释放需要目标牌时应回弹。
4. 触摸：点选后再点敌人；长按出现详情并在松开后不提交；拖动离开窗口、失焦、`pointercancel` 后不产生幽灵出牌。
5. 多指：第二个手指的按下/取消不能改变第一指针持有的卡；合法/非法目标的颜色和实际 Action 匹配。
6. 无目标卡：松在空白/敌人上均提交同一个 `slot=-1` 动作；无合法 Action 则回弹。
7. 模态：设置打开时全屏隔离输入，关闭后无遗留卡牌选中。
8. 纵向安全区域：在真实移动浏览器检查 `env(safe-area-inset-*)`、系统导航栏和虚拟键盘；截图只是初筛。

## 已验证 / 未验证

- **本环境执行通过**：`formation.ts`、`hitTest.ts` 的 TypeScript 单独编译与 Node 纯函数测试；按官方代码结构重建的 `pointerMachine` 纯函数回归；应用脚本的“锚点预检 → dry-run → 写入”合成夹具测试。
- **未验证**：实际 RogueRust checkout 的 `npm run build`、第 25 道 CDP 门禁、真实移动设备点按延迟及 FOV 下的所有极端位置（此运行环境无法从 GitHub 克隆源码）。应用脚本若遇到源码变化将**拒绝**自动修改。
- **还未实现**：键盘全量卡牌导航、无障碍替代出牌、游戏手柄、正式 GLB 人物、复杂粒子和真实 WASM Action。不要将其写成已完成。

## 回退与所有权

- 建议在独立分支试用，脚本不动 `web/` 和 Rust/WASM。
- 变更发生在 `web-next/src/`，`git diff -- web-next/src/` 可逐项复核。
- 要回退时，在自己的分支检查 `git diff` 后再使用常规 Git 回退流程；不要让 Agent 执行无法核对范围的全仓库 reset。
- 在 P2 接入真实 WASM 时，`formation.ts`、`hitTest.ts`、gesture UX 仍保持纯表现；**游戏状态是否改变只能由合法 Action 结算决定**。

---

# 附：本地 Agent 的复核（第十三轮，在 `bf7c7f5` 上逐条核实）

> 记号：**✅ 实证** = 跑代码复现了；**✅ 成立** = 读代码确认；**⚠️ 部分** = 现象真实但结论需限定。
> 复现脚本：`native/p1_review13_repro.mjs`（编 `src/input/pointerMachine.ts` 成 JS 再跑，不是静态推导）。
> 锚点探针：`native/p1_review13_anchor_probe.py`（逐条试，不抛异常，能一次列出全部失败锚点）。

## A. 两条阻塞项：都复现了

| 审阅项 | 复核 | 实测输出 |
|---|---|---|
| **P1-A** 连续相同动作被 JSON 去重 | **✅ 实证** | 同一动作做两次，`lastResult` 的 payload **完全相同** ⇒ `App.tsx` 的 `JSON.stringify` 去重会吞掉第二次 |
| **P1-B** 无目标牌丢在敌人身上 | **✅ 实证** | 丢敌人 → `{"kind":"rebound","why":"illegal-target"}`；丢空白 → `{"kind":"commit","targetSlot":-1}` |

`native/p1_review13_repro.mjs` 现在的输出（**修复前**）：

```
=== P1-A：同一动作连做两次，payload 是否相同 ===
FAIL 两次相同动作产生**不同**的 lastResult -- same=true
=== P1-B：无目标牌释放在敌人身上 ===
FAIL 丢在敌人上与丢在空白处结果一致 -- onEnemy=rebound onEmpty=commit
=== 附：8px 拖拽阈值有没有牙 ===
ok   小于阈值时不该产生结果（点按语义，留在 targeting）
```

第三条 `ok` 值得单独说：**状态机本身是对的，是接线把它废了** —— `App.tsx` 四处都送
`distance: 999`，于是 8px 阈值在真路径上从未生效。审阅把这条归在 P1-D 里，我确认成立，
但它的根因在 `App`，不在 `pointerMachine`。

## B. 其余各项

| 审阅项 | 复核 | 说明 |
|---|---|---|
| **P1-C** 详情没有用户入口 | **✅ 成立** | `onDetail` 唯一去处是 `installProbe`（`App.tsx:165`）。`390x844-detail.png` 是 `__p1.openDetail(9)` 造出来的，**没有任何玩家路径能到达那一屏** —— 与旧页面 `givePotion` 只写状态同一形状 |
| **P1-D** 无 `pointercancel`/失焦/`pointerId` | **✅ 成立** | 全局只有 `pointerup` + `keydown`，连 `pointermove` 都没有 |
| **UX-2** 文字锚点用 `screen.x` 而非 `hitX` | **✅ 成立** | `TextOverlay.tsx:57` 把文字放在牌心，露出条在 `hitX`。当前 33px 宽度下费用数字恰好还没被吃掉 |
| **P2-C** 固定 `k` 依赖刷新率 | **✅ 成立** | `k = 0.45 / 0.3` 每帧固定 |
| **P2-E** `CardEdge` 几何体没共享 | **✅ 成立** | 每个实例各自 `useMemo`。我原来那条注释"只创建一次"说法过宽（是"每次挂载一次"，不是全手牌一份） |
| **P2-A** 缺稳定卡实例 id | **✅ 成立，但非新发现** | 已在 `docs/ui-next-p1.md` §8 登记为已知缺口；优先级判断正确 |
| **UX-3** 桌面留白 / 手牌伸出底边 | **✅ 成立** | 截图可见 |
| **P2-D** 投影近似 | **✅ 成立** | 只投中心 + 一个相对世界轴的角，未算旋转后四角 |

**总评**：这轮审阅质量很高。P1-A / P1-B 正是 P2 接 WASM 之后**必然**会炸的那类 bug
（下一回合同一槽位抽到同名牌是合法局面），而且它们在我原有的 41 条断言里完全不可见 ——
我的四次提交恰好都是不同的牌与目标。

## C. 补丁包的实际可用性：46/47

```
input/pointerMachine.ts    锚点失败 0
stage/Stage.tsx            锚点失败 1
overlay/TextOverlay.tsx    锚点失败 0
App.tsx                    锚点失败 0
styles.css                 锚点失败 0
命中 46 条，失败 1 条 → Stage.props（count=0）
```

唯一失败的是 `Stage.props`：本仓库的 `}` 与 `export function Stage` 之间**有一个空行**，
补丁锚点里没有。所以：

* 补丁**基本贴合** `bf7c7f5`（46/47），改一行容差即可套；
* 但它**不可能**在这个 commit 上真跑过 dry-run（否则会报同一条错）。这与它自述
  "未验证实际 checkout" 一致 —— 值得记住的是：**"锚点全命中"这句话本身需要复验**，
  和"闸门绿"一样不能只看声明。

## D. 采纳哪些、不采纳哪些

**直接采用**（纯函数、带原作者测试、与我的实现无冲突）：
`stage/formation.ts`、`input/hitTest.ts`。

**照意图自己实现**（不照单套 46 条锚点）：

| 原因 | 具体 |
|---|---|
| 互相耦合 | `App.tsx` 的 `onCardDown` / `onHover` / `onRelease` / 全局监听四处互相引用，套完再改（见下两条）等于二次手术 |
| 有死代码 | `patch_app` 里有一行 `src = replace_once(...) if False else src`，永不执行 |
| 我要改它的两处设计 | ① `followPointer` / `cursor` 在 **render 里读 ref** ⇒ 值陈旧，应改成 state；② 拖拽中"哪个敌人被指向"有**两个来源**（R3F `onPointerMove` 写 `hoveredEnemySlot`，`hitTest` 写 `state.hoverSlot`），命中半径不同（`r+14` vs 真 mesh），边缘会出现"绿环亮着但没有 hover 高亮" —— 统一到 `hitTest` |

**补丁包没修、但审阅提了的**（记在案，后续做）：

- UX-2 文字锚点（`TextOverlay` 仍用 `screen.x`）；
- P2-D 投影四角；
- P2-E 几何体共享；
- UX-3 完整版：`formation` 只算英雄与敌人，**没有** HUD / 手牌 / 操作栏的安全区，
  也没有 `env(safe-area-inset-*)` 的布局函数；
- UX-6 手牌数量（1/3/5/10/12+）没有夹具，只有敌人 1–6 有。

## E. 执行顺序（已确认）

1. **P1-A / P1-B**（纯状态机，`native/p1_review13_repro.mjs` 是现成回归测试：现在红，修完必须绿）；
2. 交互层：详情真实入口、`pointercancel`/失焦/`pointerId`、真实 `distance`；
3. UX-2 文字锚点、`CardEdge` 共享几何体与注释、hover 双源统一；
4. 扩闸门 25：两次相同动作、无目标牌丢敌人、真右键/真长按开详情、取消/失焦/二指、
   点选路径、`enemies=1/3/6` 队形、以及一条**不带 `still`** 的冒烟；
5. 重跑验收 + 重拍截图（队形会变，`docs/ui-next-p1.md` 与 `port-plan` §351 都要跟着改）。
