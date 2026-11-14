# RogueRust 第十五轮代码审查：P2 闭环、P3–P7 集成与发布就绪性

- **审查提交范围**：`35bf81ac497dc885de7d2f58c92c575e030ace7f^..3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3`
- **终点**：[`3cc98cb`](https://github.com/tk166/RogueRust/commit/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3)
- **基线**：原 P1/P2 Review、`docs/ui-state-model.md`、此前 UI Architecture Plan v1.1；本轮终点的 `docs/port-plan.md` §361–367 和 `docs/ui-parity.md`。
- **方式与边界**：静态查阅 GitHub 固定提交的关键 TS/JS 源码与项目自报门禁；对部署路径前缀检查使用 Node `path` 做了独立构造性验证。没有获取整个 compare 的逐文件补丁、没有完整克隆仓库、没有独立执行 42 个门禁、也没有物理手机测试。因此不是“全量逐行审计”。以下明确区分**源码可证实**、**高置信度风险**、**已知有意延期**与**项目自报结果**。
- **最新产品需求**：横屏 **1–4 名敌人单排**、5 名 **3+2**、6 名 **3+3**；竖屏右侧单列。不要恢复旧“每行最多三名”的要求。

## 0. 结论与建议

**工程架构：通过，继续沿用 R3F + Three.js + uikit + DOM 辅助层。** P3–P4 已经形成真正的 Run UI；P5 动画数据流基本正确；P6/P7 的自动化基础有价值。**但不能将 P3–P7 不加限定地宣布为全部完成**。已确认的首要问题是错误冻结未闭合，正式切默认入口时新 UI 缺少存档/恢复/回放，P5 GLB 资产和 Boss 胜利至第二幕的真实端到端没有完成。后两项是项目文档主动披露的缺口，不是隐瞒。

建议次序：**P1 冻结语义 → P2 双弹窗/SC-02b/部署路径护栏 → P1 产品层存档恢复的发布判断 → P5 真正美术和真机测试**。保留新 UI 默认入口与旧版回退机制，可选择先按“预览/候选版”发布。

## 1. 审查结果概览

| 阶段 | 已有的证据/实现 | 尚未覆盖或要修复 |
|---|---|---|
| P2 修复 | 卡牌 `kind/targeting` 生成物、按内容语义归并无目标动作、`stateEpoch` 防旧 Action、拒绝异常分级、WASM manifest SHA 比对、X 费用的确定性夹具 | 目标类型来自内容程序中的 `sel.eventTarget` 推断；10/10 对照不足以证明所有复杂牌的目标语义；需要持续增补内容矩阵 |
| P3 | `RunStore`、类型化 Run 观察与地图、纯 `resolveScene()`、`RunApp` 路由；真实地图→战斗→奖励→地图测试 | 全屏失效冻结并未严格落实（见 P1） |
| P4 | Shop/Rest/Chest/Event/DeckSelect/Pickup 等，以及真实旅程门禁 | 遗物欠账重复渲染旧 fallback；SC-02b 路由名不匹配 |
| P5 | `planBeats`/`advance` 纯函数、13 种 kind/未知降级/dropped 统计、运动偏好 | GLB/AssetRegistry 未实现；实际主要是 DOM 飘字而非角色骨骼动作；Boss 胜利→下一幕未真验 |
| P6 | CDP 触控、竖屏布局、安全区模拟、DPR 上限、WebGL 丢失恢复、短 soak | 无 iOS/Android 真机；GPU 内存/draw calls 未测，短局不能说明长期无泄漏 |
| P7 | 单一 WASM、哈希/MIME/缓存核验、同内核两端检查点对照、独立默认入口 commit、旧入口保留 | 新入口无存档/回档/回放；对等检查是固定脚本 8×8 核心字段，不等于所有玩法/交互对等；静态服务器路径前缀漏洞 |

源码/记录：[`port-plan.md` §361–367](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/docs/port-plan.md)、[`ui-parity.md`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/docs/ui-parity.md)。

## 2. P1（必须优先修）：契约违约后仍可提交真实动作

**位置**：
- [`web-next/src/run/RunApp.tsx#L102-L109`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/RunApp.tsx#L102-L109)
- [`RunApp.tsx#L247-L319`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/RunApp.tsx#L247-L319)
- [`RunStore.ts#L405-L416`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/RunStore.ts#L405-L416)、[`#L479-L518`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/RunStore.ts#L479-L518)

`blocked = state.violations.length > 0` 仅作为一些组件的 `busy` 或 `inert` 属性使用，`RunStore` 动作方法没有统一保护。例如 `RewardScene`、`BlessingScene` 不传 busy，`CombatScreen` 通过独立 `GameStore.dispatch` 直接提交，连 P4 之前残留的 `settleDefault()` 也不会检查 `blocked`。因此“对账失败（界面已冻结）”与实际权限不一致。

**这是静态接线层面确定的缺口**；尚未构造实际业务环境触发对账失败并真人点击复现。它必须由**操作提交层**而非仅 React 按钮层解决。

**最小修法**：
1. 在 `RunStore` 建立统一 `canMutate()`/冻结错误检查，供所有 `RunStore` 权威动作入口调用。
2. `CombatScreen` 的 `GameStore` 路径必须共享冻结令牌或注入 `dispatchGuard`；只守 `RunStore` 代理无效，因为 `CombatScreen` 能直接 `GameStore.dispatch`。
3. `RunApp` 把 `blocked` 提供给各 UI 作为禁用和诊断提示（包括祝福、奖励、终局和覆盖层）；移除无保护 fallback。
4. 用故障注入给 `violations` 注入可控非空项，依次尝试奖励/祝福/战斗动作、药水、选择器、旧 fallback；确认 ABI 调用数与权威状态全不变；再恢复正常流程。

**切忌**：不要在 `GameStore.dispatch()` 内静默当作普通非法动作返回；契约失败应明确给出 fatal/blocked 原因，便于追踪。

## 3. P2（确定性 UX/维护问题）：遗物欠账同时存在两套模态 UI

**位置**：[`RunApp.tsx#L400-L411`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/RunApp.tsx#L400-L411) + [`#L440-L453`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/RunApp.tsx#L440-L453)；[`PickupOverlay.tsx`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/overlays/PickupOverlay.tsx)；[`run.css#L579-L586`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/run.css#L579-L586)。

只要 `pickup.picks>0 || pickup.add>0`，场景解析便包含 `SC-11a/11b`。`RunApp` 会首先渲染一个早期过渡用的“遗物要求你改牌/加牌，牌组选择器在 P4；用内核默认动作通过”覆盖层，随后渲染正式 `PickupOverlay`。两个 `.run-overlay` 均为 fixed 全屏，`z-index: 40`。后一个一般覆盖前一个，但**两个同时存在于 DOM、焦点树和逻辑中**；前一个的按钮还能尝试 `settleDefault()`，对应的正是需要显式选择而不是默认跳过的业务。

**修法**：删除 `scene.overlays.length > 0` 的旧通用 fallback；只保留 `PickupOverlay`。用 `data-run-overlay` 和 `data-pickup` 验证单一可交互模态；验证拾取后返回原基础场景、焦点不落到背景、不能误通过默认动作。不要为这一处引入复杂统一 Modal 框架。

## 4. P2（潜在软锁）：SC-02b 幕尽头不是独立可操作的终局视图

**位置**：[`RunApp.tsx#L321-L331`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/RunApp.tsx#L321-L331)、[`EndScene.tsx#L14-L21`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/scenes/EndScene.tsx#L14-L21)、[`#L36-L80`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/scenes/EndScene.tsx#L36-L80)。

`base === SC-02b` 被渲染为 `EndScene(kind="actCleared")`，DOM `data-scene` 固定为 `SC-12a`，但 `onContinue` 只有 `base === SC-12a` 才提供。因此如果以后 `SC-02b` 真的可达，画面会显示“这一幕打完了”，却没有继续按钮（也不匹配实际场景编号）。

**重要边界**：仓库已明确 `SC-02b` 在当前内容版本不可达，此问题不是目前实测到的正常路径软锁，而是**“18 场景全可操作”的语义夸大和未来潜在软锁**。建议在独立合成夹具中将 SC-02b 的预期行为钉住：真实可继续则传正确 `endAct`；不能继续则显示权威原因与可恢复选项；不要因同用一个 `EndScene` 而抹掉场景身份。

## 5. P2（部署边界）：静态服务器目录限制使用字符串前缀

**位置**：[`web-next/scripts/serve.mjs#L66-L79`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/scripts/serve.mjs#L66-L79)。

现状 `file.startsWith(DIST)` 或 `file.startsWith(WEB)` 并不构成目录边界检查。构造例如 `DIST=/repo/web-next/dist`、请求 `/../dist-backup/private.txt`，Node `normalize(join(DIST,clean))` 得到 `/repo/web-next/dist-backup/private.txt`，**依然**以 `/repo/web-next/dist` 开头。对同前缀相邻目录存在路径越界读取风险；我用本地 Node 路径模块对该字符串比较单独验证了结果，但未对运行中的 RogueRust HTTP 服务做网络渗透测试。

**修法**：`resolve` 后使用 `relative(root,target)`，只允许 `relative` 不为空的目录内路径或者根本身，拒绝首段 `..` 和绝对相对值；也可在根路径末尾添加 `sep` 做前缀判断，但 `path.relative` 更清晰。单测包含 `../dist-backup/x`、`%2e%2e/dist2/x`、`/legacy/../web-backup/x`、普通 assets、根入口，以及非法 `%` 转义的请求，不得抛未处理异常。

此外，`cacheControlFor()` 对**所有** `/assets/*` 无条件视为内容哈希 immutable，而代码注释所称“文件名含 hash”没有由函数自身验证。现在 Vite 正常产物基本满足该条件，但若未来加入不带 hash 的 assets，应改为对带内容 hash 的文件名启用 immutable，或由构建脚本严格限制资产命名。

## 6. P1（产品交付判断，而非代码回归）：默认切换后无法保存和继续当前 Run

**证据**：[`ui-parity.md` §2](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/docs/ui-parity.md#L193-L199) 明确承认新入口没有存档/回档/回放；[`RunApp.tsx#L74-L88`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/src/run/RunApp.tsx#L74-L88) 在页面装载时创建新的 `RunStore`；[`serve.mjs#L36-L37`](https://github.com/tk166/RogueRust/blob/3cc98cb19e0964c9df1a44b725eaf8b7dbef52a3/web-next/scripts/serve.mjs#L36-L37) 和最终提交已将默认入口设为 run。

用户在新入口的正常长局中刷新/关闭页面后，不能通过新 UI 恢复当前 Run；旧入口虽能访问，但**不能假定新入口内的活动 Run 会自动共享给旧入口**。对于“正在试用的新 UI”可作为已知限制；对“默认正式游戏入口”则是明显 UX/功能回退。它的优先级取决于发布定位：
- **仅作为技术预览**：文档与 UI 都清晰提示“无自动存档、刷新会丢局”，可暂不阻塞。
- **面向正常玩家的默认正式入口**：至少实现导出/导入当前 Run；理想情况下有带版本号与校验的本地自动保存和失败恢复。回放可放在次级优先级。

应把“入口切换”与“功能对等”列为两个独立里程碑，不能因为前者是一行代码就自动批准产品功能缺口。

## 7. P5–P7 的验证边界：哪些应该标记为 PARTIAL

1. **P5 原创 GLB 角色 + AssetRegistry**：`stage/assets.ts` 只实现 `enemyLook()` 对应的程序化形状、颜色和未知资产计数；项目自己声明没有 GLB、AnimationClip 与资源导出管线。`planBeats` 主要向 DOM 飘字映射事件，而不是完整的角色骨骼/3D 攻击演出。建议 P5 拆成 `P5a: Beat 演出与降级 DONE`、`P5b: 角色资产管线 TODO`，而非笼统“P5 DONE”。
2. **幕间真实流程**：闸门 38 验证的是 Boss 未击败时 `endAct` 被拒绝；记录明确没有成功击败 Boss 进入第二幕的 E2E。再补一条可控胜利路线，至少覆盖战斗结算/幕通关/继续到下一幕与新的地图。
3. **P6 设备**：CDP 使用真正触摸输入事件，值得肯定；但是 iOS Safari、Android Chrome 物理设备、GPU 负载和长时内存趋势未测试。headless rAF 16.7ms 是刷新节奏，不是 GPU 侧的性能证明。可将本轮验收标记 `P6 automated DONE / physical device NOT VERIFIED`。
4. **P7 对等**：`UI_PARITY PASS checkpoints=8 fields=64` 很好地证明核心固定脚本与 WASM 一致，但没有覆盖 18 场景所有动作、所有输入组合；应保留“同一核心脚本对等”这一精确说法。

## 8. 架构上值得保留的成果

- **一份真实权威**：`RunStore` 和 `GameStore` 收敛对 WASM 的操作，页面根据 `resolveScene(input)` 派生场景，没有“再维护一份 mode”。
- **纯粹的场景系统**：`SCENE_ORDER` 把战斗中与战斗前、幕尽头与地图兜底的顺序显式化；夹具验证 14976 组输入组合的穷尽性。注意穷尽 ≠ 合法性/可达性。
- **同一个 `CombatScreen`**：P1/P2 回归页和真实 Run 复用组件，避免“测试的是另一套 UI”。
- **真实端到端门禁**：第 34/36/39 门包含实际 DOM 点击、WebGL 拖动、触摸输入，不只是类型系统与纯函数。
- **Animation as Projection**：Beat 只驱动演出，不回写游戏事实；未知/丢失 beat 明示；prefers-reduced-motion 不影响状态。
- **可审计的部署**：唯一 WASM 字节、manifest SHA、静态服务的 MIME/缓存策略与旧版回退。路径护栏修复后非常适合长期保留。
- **已按新需求满足队形**：横屏 n≤4 单排、n=5 3+2、n=6 3+3；竖屏单列。不要把旧的“每排 3 个上限”重新引入测试。

## 9. 建议给本地 Agent 的最小行动清单

| 优先级 | 任务 | 验收/负控 |
|---|---|---|
| **P1** | Run 层及 Combat 层共享唯一冻结/授权边界 | 人为注入 violations，尝试全部操作入口；WASM 不变、UI 明确显示错误；正常路径不受影响 |
| **P2** | 删除旧的 `scene.overlays` 通用 fallback | SC-11a/b 只有一个真正可操作的 PickupOverlay，离开后仍回原场景 |
| **P2** | 修复 `serve.mjs` 的目录边界 | 构造同前缀相邻目录请求必须拒绝；合法路径、两个入口、wasm MIME 保持通过 |
| **P2** | 明确 SC-02b UI 的身份/继续能力 | 合成夹具不返回错误 `data-scene`；无按钮时有权威原因与动作路线 |
| **发布决策 P1** | 定义新 UI 无存档限制能否接受 | 若正式默认入口，补导出/导入与基本持久化；若预览版，明确警示且旧入口易达 |
| **功能里程碑** | P5b GLB+AssetRegistry / Boss 胜利 E2E | GLB 有原创可复用素材与 fallback，至少一条成功跨幕脚本 |
| **质量阶段** | 真机交互、帧耗和显存 | iOS/Android 至少各一个真实设备，长时场景/触摸/失焦恢复 |

## 10. 建议的完成标准与版本命名

建议将当前状态记录为：

- `P3 COMPLETE`：地图—战斗—奖励闭环已具备可重复验收；
- `P4 FUNCTIONAL`：可达经营/事件场景的关键操作已实现，待清除遗物弹窗重复路径；
- `P5a COMPLETE / P5b PENDING`：Beat 演出可用，但 3D 角色资产管线未交付；
- `P6 AUTOMATED VERIFIED / DEVICE UNVERIFIED`：仿真触屏与短 soak 有据，真机未验证；
- `P7 DEPLOY READY WITH FEATURE GAPS`：新入口部署就绪，尚不等同完整功能替代。

## 11. 审查限制和独立证据

- 固定终点版本源码包括 `RunApp.tsx`、`RunStore.ts`、`scene.ts`、`CombatScreen.tsx`、`wasm/store.ts`、`view/combatView.ts`、`combat/beats.ts`、`stage/assets.ts`、`run/scenes/*` 的部分文件、`serve.mjs`、`run.css`，并查阅 `docs/port-plan.md`、`docs/ui-parity.md`、`docs/ui-p6-devices.md`。
- 唯一独立可执行验证是**通过 Node 的 `path.join()` + `path.normalize()` 构造** `dist-backup` 同前缀路径绕过，证明“字符串前缀 != 目录归属”；没有对运行 HTTP 服务做完整越界测试。
- “门禁 42/42”“单测 1233”“导出 234”“8×8 同内核对账”来自仓库开发记录，未由本次审核在独立本地构建复现。
- 缺少当前 P3–P7 的物理设备实拍与手感测量；本轮对新屏 UX 的判断依赖组件语义、CSS 和门禁记录，而非真人可用性测试。请勿将报告写成已独立浏览器验收。

**总评：架构没有走偏，P3/P4 已有实质完成度。优先修好 P1 的真冻结、清理重复模态，并对 P5/P6/P7 的剩余范围诚实分级；不需要为此重写 R3F/uikit/WASM Adapter。**

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
| §5 前缀检查不是目录边界 | **成立**（已复现） | `DIST` 无尾分隔符 ⇒ `/../dist-backup/private.txt` → `…\web-next\dist-backup\private.txt`，`startsWith(DIST)` = **true**；`/legacy/../web-backup/x.txt` 同理 |
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

### 五、处置结果（本轮已落地）

| 序 | 任务 | 结果 | 守它的闸门 |
|---|---|---|---|
| 1 | 统一冻结边界（粘性） | **已修**：`RunStore` 31 个动作全过 `canMutate()`；`GameStore.setDispatchGuard()` 冻结时连 `rd_env_step` 都不调；`CombatScreen` 加 `frozen` prop；`RunApp` 把 `blocked` 传给所有场景 | 43 `ui-freeze`（24 个入口，全部"被拒 + 局面逐字段不变"；撤掉注入仍冻结；重开才解冻） |
| 2 | 删旧 `data-run-overlay` fallback | **已修**：遗物欠账只剩 `PickupOverlay` | 43（`settleDefault` 在冻结下被拒）+ 36（拾取流程） |
| 3 | `serve.mjs` 目录边界 + assets 缓存 | **已修**：`path.relative` 判归属；只对带 8 位哈希的 assets 用 immutable | 42（负控从 1 条扩到 6 条：同前缀兄弟目录 / `%2e%2e` / legacy 兄弟 / `%zz` / 无哈希 assets） |
| 4 | `SC-02b` 身份与继续能力 | **已修**：抽成纯函数 `endSceneFor()`；`SC-02b` 报自己的 id 且能继续 | 33（纯函数，不依赖"这条路径可达"） |
| 5 | 存档 / 导出 | **已实现**（按"正式入口"定位）：设置面板导出/导入，全有或全无，战斗中拒绝并说原因，回档成功解除冻结 | 44 `ui-archive`（导出→刷新→导入逐字段相同；乱码/篡改/截断全拒且局面不动） |

**未修（审阅 §7 的分级建议，已采纳到文档措辞）**：P5b GLB 资产管线、打赢 Boss → 第二幕的
真实 E2E、真机测试、回放界面。`docs/ui-parity.md` §2 与 `README` §10.4 已按"PARTIAL"措辞写清。

**同时修掉一个验收工具自身的坑**：证据数组的收尾 `)) {` 被两次插到数组中段（后面还有条目 ⇒
语法错误），而**陈旧输出让验收看起来还在跑**（`acc.txt` 的 mtime 没变，读到的是上一次的结果，
连"全绿"都是旧的）。已写成幂等脚本 `native/evidence_tail.py` 归位，并把这条教训记在
`port-plan.md` §4 那一类"工具骗人"的形态里。
