# RogueRust 第十三轮 Review：P1 R3F UI PoC

> 审查范围：`9313c7331d141a54e08cea6027281c125ae126c8^..bf7c7f5107dad96f54d1dab95b0f7d728d661b76`  
> 审查对象：`web-next/`、`native/ui_next_check.mjs`、`docs/ui-next-p1.md` 与四张浏览器验收截图  
> 重点：架构边界、输入状态机、桌面/移动 UX、可测性，以及从 P1 Mock 切换到 P2 WASM 的风险  
> 方法：指定提交的源码/文档静态核对 + 仓库截图视觉检查；**未独立构建或浏览器交互复验**。

## 0. 总结与阶段建议

**结论：P1 技术路线成立；不需要推翻 R3F + Three.js + uikit + DOM 文字的混合渲染方案。**

但在把 Mock 的 `applyCommit` 替换成真实 `rd_env_step` 前，建议先修复两项功能正确性缺陷，补真实详情交互、指针取消语义，并建立布局安全区域。现有 25 道门禁具有较强的浏览器事件覆盖，但它不等于常规玩家手感、移动端可读性或真实 WASM 契约已经验证。

| 维度 | 结论 |
|---|---|
| 分层架构 | 良好，Stage 不直接提交游戏规则；输入状态机为纯 TS |
| 命中模型 | 优秀：静止的逻辑命中面与运动的视觉网格分离 |
| uikit 与 DOM 混用 | 合理，特别适用于小资产体积和中文字形约束 |
| 指针状态机 | 方向正确，存在两条可由代码推导的实际功能缺陷 |
| 移动 UX | 基础拖拽链路有测试；选牌识别、详情入口与取消机制待完善 |
| 桌面 UX | 空间分配不理想；手牌大部分位于视口底边外 |
| P2 接入 | 有条件推进；先关闭以下 P1 阻塞项 |

## 1. 已经值得复用的实践

1. **视觉对象与命中目标分离**：卡牌网格设置 `raycast={() => null}`，每张牌拥有固定扇形槽位命中面。避免动画位置改变射线命中，解决密集手牌中的相邻误选和拖起牌遮挡敌人的问题。
2. **一个输入状态机适配多个设备**：`pointerMachine.reduce` 无 DOM/Three 依赖；R3F 只交付卡牌、目标和动作事件，适合后续同一套逻辑接 WASM。
3. **一个布局写者**：`Stage.useFrame` 写投影数据，DOM 文字覆盖层只读布局；避免两种渲染器分别计算对象位置。注意这仍需要定义多场景实例隔离。
4. **真实事件门禁**：CDP `Input.dispatchMouseEvent` 和 `Input.dispatchTouchEvent` 测试 Raycast → Store → 结果，且对负控先断言确实抓到了目标。
5. **先实测中文，再选方案**：390px 手宽下十张牌只有约 33px 露出宽，不能通过缩小字号假装中文可读；DOM 文字是合理的折衷。
6. **冻结截图插值、保持逻辑测试真实**：`?still` 固定视觉动画以减少图片漂移，但不冻结触控/状态机；建议再保留至少一条普通模式动画测试。
7. **入库 dist 的新鲜度防护**：构建烘入 source SHA，测试前比较当前源码哈希，避免旧包假绿。

## 2. 必须优先修复的问题

### P1-A：连续相同动作被错误去重

**位置**：[App.tsx#L60-L80](https://github.com/tk166/RogueRust/blob/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/web-next/src/App.tsx#L60-L80)

```ts
const key = JSON.stringify(result);
if (key === lastResultRef.current) return;
lastResultRef.current = key;
```

该代码将“内容相同的两次玩家操作”视为同一事件。P1 Mock 手牌不移除，按相同槽位向相同敌人出牌两次，即可构造同一 `Result` 内容；即使真实 WASM 接入后，下一回合同槽位重新抽到相同卡牌仍然可能出现。

**建议**：为每次状态机决策附加单调 `eventSeq`，或直接由 Store 返回一次性的 Command Effect，再在唯一 ActionDispatcher 中消费。不要通过 JSON 字符串内容去重。

**验收**：同一槽位连续对同一目标操作两次，提交数增加 2；首次失败后重试有效；一次鼠标释放至多提交 1 次。

### P1-B：无目标牌释放在敌人身上时，决定和提交互相矛盾

**位置**：[pointerMachine.ts#L67-L131](https://github.com/tk166/RogueRust/blob/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/web-next/src/input/pointerMachine.ts#L67-L131)

`decide()` 对无目标卡返回 `commit`，但 `finish()` 用物理落点 `targetSlot` 查找动作。无目标牌仅有 `slot=-1`；释放在敌人 `slot=1` 时找不到对应选项，结果变成 `rebound`。

**建议**：对无目标动作统一把提交目标规范化为 `-1`；用于判定的物理命中位置与真正的动作目标分开。

**验收**：无目标牌拖至空白、敌人 0、敌人 1 都只提交一次，并均使用内核无目标动作；需要目标的牌在非法区域仍回弹。

### P1-C：详情视图没有面向真实用户的触发路径

**位置**：[App.tsx#L133-L151](https://github.com/tk166/RogueRust/blob/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/web-next/src/App.tsx#L133-L151)；[ui_next_check.mjs#L364-L387](https://github.com/tk166/RogueRust/blob/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/native/ui_next_check.mjs#L364-L387)

`onDetail` 仅被传入 `installProbe`；真实场景卡牌事件没有触发该回调。截图通过 `window.__p1.openDetail(9)` 直接设置，而非用户输入。

**建议**：桌面右键/明确详情控件，触摸长按查看详情，点击/按键关闭；操作和拖拽互斥，避免查看操作意外出牌。P1 最小实现可先支持右键 + 长按并完成真事件验收。

**验收**：未暴露 `window.__p1` 时用户也能打开/关闭详情；鼠标和移动触摸各有一条端到端测试。

### P1-D：`pointercancel`、失焦与指针归属缺失

**位置**：[App.tsx#L110-L132](https://github.com/tk166/RogueRust/blob/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/web-next/src/App.tsx#L110-L132)

全局仅监听 `pointerup` 与 `keydown`，状态机没有绑定 `pointerId`；没有处理 `pointercancel`、window blur、页面隐藏，也没有明确的 Pointer Capture 规则。触屏系统手势、来电/切 App、第二根手指都可能取消或干扰当前拖拽。

**建议**：存储 activePointerId；非活动指针事件忽略；统一 `cancel(reason)` 路径；使用指针捕获或全局监听，配套 capture release；在失焦/隐藏/系统取消时清除 lifted/hover/targeting。

**验收**：touchStart → touchCancel 后状态回 idle，不提交；拖到屏外释放不发生幽灵出牌；第二根手指不改变第一根手指的目标。

## 3. 架构与数据模型的下一阶段风险

### P2-A：`CardScreen.slot` 与 React key 缺乏稳定实例身份

[Stage.tsx#L291-L326](https://github.com/tk166/RogueRust/blob/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/web-next/src/stage/Stage.tsx#L291-L326) 使用 `key=card.id-index`，输入 State 存的是 `handSlot`，而 `options` 在按下时快照。P1 Mock 牌组固定，尚无问题。P2 WASM 的真实出牌会让同槽位变成另一张卡、动作索引变动。需要将 `CardInstanceId`/stable occurrence identity 与 `handSlot` 分开，并在提交前以 snapshotRevision 验证原动作仍有效。

### P2-B：模块级 `layout` 全局单例仅适合单场景

[layout.ts](https://github.com/tk166/RogueRust/blob/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/web-next/src/stage/layout.ts) 直接导出模块级可变单例。P1 一个 Canvas 合理；未来场景切换、多 Canvas、StrictMode 双挂载或测试并行时有读写交叉风险。建议逐步替换为 `CombatViewport` 实例持有、通过 Context/Ref 注入。无需新增全局状态库。

### P2-C：固定帧比例插值依赖刷新率

[Stage.tsx#L128-L136](https://github.com/tk166/RogueRust/blob/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/web-next/src/stage/Stage.tsx#L128-L136) 采用固定 `k=0.45/0.3`，120Hz、60Hz、30Hz 的回弹时间将不同。建议使用 `k=1-exp(-lambda*delta)`，让动效时间与实际帧率无关。`?still` 可以继续立即吸附。

### P2-D：3D 卡牌文字屏幕投影是近似矩形

目前只投影中心和一个相对于世界轴的右上角来估计宽高，未计入旋转后四角投影；文字永远正面朝屏幕是有意设计，但倾斜幅度增大时会与牌边脱离。正式 UI 可按四角投影得到屏幕外接矩形，或给卡牌分配独立的屏幕文字锚点；并增加旋转极值、缩放、触摸拖拽截图。

### P2-E：视觉组件数量与资源释放

`CardEdge()` 注释声称只有一次几何体创建，但它在 `map` 中为每张牌分别挂载，每个组件实例都有自己的 `useMemo`；并非全手牌共享几何体。P1 十张牌影响很小。正式实现应提升共享几何体/材质的作用域，卸载时正确 dispose。

### P2-F：渲染事实与游戏事实边界继续保持

`MockScene` 里有 `targeted`、`handSlot*10+slot` 这样的演示表达。P2 不可将它们当作真正的 Action 规则；合法动作必须来自 WASM Observation/Action 枚举。Stage 只消费已解析的 VisualCard、TargetEntity、LegalDrop 和 PresentationBeat。

## 4. 截图 UX 审查

截图链接（指定 commit，非图库示意）：

- [390×844 常规手牌](https://raw.githubusercontent.com/tk166/RogueRust/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/docs/ui-next-p1/390x844-hand.png)
- [390×844 抬起选中](https://raw.githubusercontent.com/tk166/RogueRust/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/docs/ui-next-p1/390x844-selected.png)
- [390×844 详情](https://raw.githubusercontent.com/tk166/RogueRust/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/docs/ui-next-p1/390x844-detail.png)
- [1280×800 桌面](https://raw.githubusercontent.com/tk166/RogueRust/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/docs/ui-next-p1/1280x800-desktop.png)

### UX-1：密集手牌的可辨识性（P1 产品体验）

390px 下十张牌有效露出约 33px，Agent 正确不在窄条上强行塞中文标题。但十张近似颜色的牌只能靠费用与少量轮廓辨认，**清晰文字被隐藏不等于玩家能识别并选对**。建议按卡种颜色 + 简化图标 + 选中预览的策略，必要时加手牌展开/滚动视图。独立验证“给玩家某张目标牌，能否在不试错的情况下找到”。

### UX-2：视觉文字锚点与真实可见条错位（P1）

[TextOverlay.tsx#L48-L59](https://github.com/tk166/RogueRust/blob/bf7c7f5107dad96f54d1dab95b0f7d728d661b76/web-next/src/overlay/TextOverlay.tsx#L48-L59) 将文字放在 `screen.x`（卡牌中心），但 `layout` 已计算 `hitX=card.x-(card.w-visibleW)/2`，即左侧真正可见带的中心。紧凑态的费用字可能没有落在真正露出的可见带。建议紧凑态使用可见带锚点，展开态才使用整张牌中心；并加入静态几何遮挡检查。

### UX-3：桌面与移动端的战场/手牌区域缺少布局约束（P1/P2）

1280×800 桌面截图中大面积上部留空，角色集中在中下区域，手牌底部伸出屏幕。390px 手中较多卡牌被屏幕底边和操作栏遮挡。这可以是 PoC 有意展示扇形，但不应直接固化为正式布局标准。

建议新建纯布局函数 `CombatLayout(viewport, safeArea, handCount)`，输出：top HUD safe region、combat region、hand region、bottom actions region、camera/framing；支持宽屏/竖屏与设备安全边界。测试不只看卡牌中心在屏幕内，还要检查可交互部分、详情和按钮区域是否重叠。

### UX-4：目标选择时要保留敌人可见性（P2）

抬起的卡牌在目标正前方可能视觉遮挡敌人，即使它不再挡 Raycast。建议在 targeting 中使用目标轮廓、箭头、伤害预览，或移动/半透明化卡牌显示层。暂不需要复杂 VFX。

### UX-5：主操作与详情需具备非拖拽路径（P1/P2）

WCAG 2.2 2.5.7 要求拖拽功能原则上有单指、无拖拽替代方式。现有状态机试图支持“点卡再点目标”，但门禁主要覆盖拖拽；还应为点选/取消/长按详情安排真事件用例，并为以后键盘/手柄留输入适配口。参考：[WCAG 2.2](https://www.w3.org/TR/WCAG22/#dragging-movements)；[Apple Hit Target Tips](https://developer.apple.com/design/tips/)。

### UX-6：卡牌数目与特殊情形

增加真实/模拟 1、3、5、10、12+ 张手牌，以及 1、2、3、4+ 个敌人、同名不同实例、无能量、X 费、死亡目标。尤其验证扇形露出宽、按中牌不误选、已死亡敌人不可选择、被选中的牌不移位错误。

## 5. 门禁设计：值得继续保留，但补上空白

`native/ui_next_check.mjs` 当前覆盖了鼠标实际命中、指向敌人、非法回弹、单敌不自动打出、触摸提交、模态隔离、窄屏字号及截屏；`?still` 用于生成确定性截图；source SHA 用于防止陈旧构建。整体显著强于仅检查 DOM 或调用纯状态机的测试。

建议按优先级补：

1. 两次连续相同提交，必须产生两个事务（P1-A）。
2. 无目标牌在敌人上释放，同样提交（P1-B）。
3. 用户真实鼠标/触摸打开详情，而非 `__p1.openDetail()`（P1-C）。
4. `pointercancel`、失焦、多指干扰、离开 Canvas 后释放；前后状态对拍。
5. 点击牌 → 点击敌人完成出牌的非拖拽路径；点外部空白取消。
6. 手宽布局的真实可见面积与目标区遮挡，不只测中心坐标。
7. 普通动画模式（不带 `still`）的基本交互正确性；截图保持静态冻结即可。
8. P2 开始时加入 WASM 指纹、动作合法性、拒绝不变性、实际能量和卡牌移除/重排一致性。

## 6. 最小执行顺序及验收表

| 顺序 | 范围 | 交付 | 验收 |
|---|---|---|---|
| 1 | P1 修正 | 动作事件唯一性、无目标落点规范化 | 两次相同动作都成功；释放到敌人/空白一致 |
| 2 | P1 交互 | 详情真实入口、指针取消、失焦 | 真鼠标与真触摸；取消不提交 |
| 3 | P1/P2 UX | 手牌可见带文字锚点、桌面/移动安全区域 | 390×844、1280×800 的交互和布局断言 |
| 4 | P2 接入 | TypeScript WasmHost/ABI/SnapshotReader/ActionDispatcher | 真实 WASM 合法动作与 UI 状态一致 |
| 5 | P2 扩展 | CardInstanceId、snapshotRevision、不同槽位变化 | 出牌重排、同名牌、X 费、死亡敌人不串位 |
| 6 | P3+ 美术 | 角色美术、动画演出、复杂粒子、性能调优 | 等真实战斗切片稳定后推进 |

## 7. 本轮结论的验证边界

- 已查看指定版本核心 P1 源码和四张仓库截图；已阅读闸门逻辑及 P1 项目记录。
- P1-A、P1-B 是根据控制流可以推导的确定性错误条件，**未独立跑浏览器复现**。
- 详情缺少玩家入口由当前组件接线可确认；屏幕布局与卡牌辨识性来自截图观察。
- 没有独立执行 `npm ci`、Vite build 或 Chrome CDP 门禁，也没有完整 Git compare 补丁；本报告是按指定终点源码和两项明确提交内容的针对性静态审查。
- 25 道门禁为仓库自身记录，不应替代这里新增的定向测试。

**最终评价：这是值得保留的 PoC，不是应该推翻的 UI 架构。关键是 P2 前修掉“操作事件身份”和“落点与动作目标混淆”，并让真正的玩家入口与截图状态一致。**
