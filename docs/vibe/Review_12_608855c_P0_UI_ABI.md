# RogueRust 第十二轮 Review：commit `608855c` 的 UI P0 与本地 Agent 复核

> 审查版本：[`608855c2e1d6c76ebb132e8e581e2fea01edffa9`](https://github.com/tk166/RogueRust/commit/608855c2e1d6c76ebb132e8e581e2fea01edffa9)（相对其父提交 `29500d4`）  
> 范围：`docs/vibe/RogueRust_UI_Architecture_and_Development_Plan_v1.1_29500d4.md` 末尾附录、`docs/ui-abi-audit.md`、`native/ui_abi_dump.mjs`、`native/ui_fixtures/p0-scenes.json`、第 24 道门禁以及相关辅助脚本。  
> 方法：对公开仓库固定 commit 的静态源码与文档审查。**没有独立运行项目本地的 Windows 验收链、Rust 构建或 WASM。**  
> 判定：**P0 作为 ABI 基线与实际场景采样已交付，允许进入 P1；但验收工具尚有需要修正的假阳性与快照陈旧检测问题。**

## 1. 一页总结

| 项目 | 结果 | 证据边界 |
|---|---|---|
| R3F + Three.js 低多边形角色 + uikit + HTML 覆盖层 | 保留 | 本次不涉及渲染实现 |
| 本地 Agent 追加的两项事实更正 | 赞同 | 敌人定义 ID 和卡牌定义 ID 已有导出 |
| 四项计划改进建议 | 基本赞同 | 复用旧纯逻辑、拆 P0/P2、中文可读性、WASM 单一来源 |
| `--check` | 有效的 P0 **smoke gate** | 验证 52 个导出存在、19/148、特定哨兵和场景 parity，不是完整 ABI 验证 |
| `--report` | 有效的真实场景采集工具 | 未采集的关键场景可能不使它报错 |
| `--check-fixtures` | 目前只能验证内容与形状的部分新鲜度 | 内容指纹不涵盖 Rust/WASM 代码行为变化 |
| `p0-scenes.json` | 有用的 P2 输入数据 | 真实/合成、原始/派生、预期场景应清楚标识 |
| 正式 UI P1 | **可以启动** | 先将以下 P1 工具问题列入补丁，不要求再重构内核 |

## 2. 对本地 Agent 意见的逐项判断

Agent 追加的意见在[计划文件附录 §A–E](https://github.com/tk166/RogueRust/blob/608855c2e1d6c76ebb132e8e581e2fea01edffa9/docs/vibe/RogueRust_UI_Architecture_and_Development_Plan_v1.1_29500d4.md#L828-L907)。

### 2.1 两项事实更正——同意

- `rd_env_enemy_name_*` 返回角色**定义 ID**，不应把它仅视为显示文本；AssetRegistry 可直接使用这个标识映射 GLB 资产。显示文字由另一个展示层处理。
- `rd_env_card_name_*` 返回卡牌**定义 ID**，不必先请求新增 ABI 才能绑定卡面资源。但 `definitionId` 不是可跨动作追踪的 `CardInstanceId`，不能误用来做永久实体身份。

应修订旧架构提案里的两处“候选 ABI 缺口”，不应要求本地 Agent 因此改 Rust。

### 2.2 `web/ui_render.js`——同意复用，但不要机械冻结旧视觉语义

这里的 `actionFor()`、`dropSlots()`、`diffObservations()`、`animationPlan()` 和 `soundPlan()` 具有较高参考价值。建议：

- P1/P2 直接复用其**合法动作匹配、槽位不重排、拒绝不擅自选目标**等业务语义。
- 旧 `animationPlan()` 的输出不必成为新 R3F 演出的永久格式；可以对共同语义做 parity，而不是要求未来所有视觉特效完全一致。
- `diffObservations()` 只能恢复**净状态变化**，不能还原多段伤害或中间事件顺序。正常路径优先 Beat；Beat 丢失时才用 Observation diff 做保守降级，不应伪造未观察到的历史动作。

**需要在 P1 PoC 前明确的交互细节：** 旧 `actionFor()` 中 `list.length===1` 时会无条件返回唯一 Action，即使用户拖到了无效区域。这把“没有目标的卡牌”和“需要目标、但现在只剩一个合法敌人”混为相同拖拽释放行为。老页面有意采用了这一行为，新 3D UI 未必应该照搬。请单独确定 StS 式定向卡的释放策略，并分别测试空白区域、单敌人与多敌人，不要让 parity 测试代替产品设计决策。

证据：[`web/ui_render.js#L491-L519`](https://github.com/tk166/RogueRust/blob/608855c2e1d6c76ebb132e8e581e2fea01edffa9/web/ui_render.js#L491-L519)；[`diffObservations()`](https://github.com/tk166/RogueRust/blob/608855c2e1d6c76ebb132e8e581e2fea01edffa9/web/ui_render.js#L242-L317)。

### 2.3 P0 / P2 循环依赖——同意，且已正确解决

P0 保留 WebAssembly 导出值及运行场景，P2 再负责类型化 `GameSnapshot`。`--check` / `--report` / `--check-fixtures` 三种模式拆分是合理的，不应把类型化 Adapter 的实现要求提前放到 P0。

### 2.4 中文可读性——强烈同意，但要具体化验收

建议 P1 至少验证：390×844 手机尺寸、10 张手牌扇形排布、选中卡牌可读、放大详情可读、触摸目标无遮挡。文字最小字号和字形图集的压缩体积都应实测。不要不合理地要求 10 张缩小卡牌在未展开时都能读完整描述；若测试不理想，优先尝试卡牌 3D Mesh + HTML/SVG 文字覆盖，而不是立即放弃全部 3D。

### 2.5 两份 WASM——同意单一构建来源

`web-next/` 不应再自行编译另一套来源不明的 WASM。建议 **单一构建产物 → 明确构建/复制步骤 → 记录 SHA-256 → 加载前比对版本和内容指纹**。开发与发布的文件路径可以不同，但不可以出现两个未受约束的二进制版本。第 15 道门禁约束旧 Web 版，新 UI 版要覆盖对应产物。

### 2.6 `beats_dropped > 0` 降级提前至 P2——同意

P2 只做**不丢事实、可见提示、动画可跳过、最终收敛快照**；P5 才开发 1–13 类 Beat 的丰富 VFX 演出。不要为修降级路径提前重建通用动画事件框架。

## 3. P0 的主要优点

1. **真 WASM 优先于手写文档**。读取 `web/rd_wasm.wasm`，用模块导出询问观察长度、哨兵和实际场景事实；不是把 TypeScript 接口提案当作代码事实。
2. **不混淆原始 dump 与类型化 Snapshot**。P0 和 P2 责任分明。
3. **允许显式合成场景**。SC-12a 真实幕通关未采到，就标成合成；没有把一条普通路演伪装成打通全幕。
4. **定位并保留了夹具自身缺陷的经验**。在没有真实战斗结果时调用 `fight_end()`、误把 `begin_node()` 当成战斗入口、进入商店立即离开，都曾使有效场景看上去不可达。问题记录有可复用价值。
5. **快检与昂贵采集分离**。实际场景数据依赖游戏内容，适合按需或集成阶段运行；P0 每提交的 smoke gate 不应因为商品价格变化而频繁变红。
6. **没有为了测试而修改内核或重写旧 DOM UI**。这是值得保留的范围控制。

## 4. 需要修正的缺陷/风险

### P1-A：`--report` 不保证所有要求的真实场景被采集

源：[`native/ui_abi_dump.mjs#L348-L469`](https://github.com/tk166/RogueRust/blob/608855c2e1d6c76ebb132e8e581e2fea01edffa9/native/ui_abi_dump.mjs#L348-L469)。

当 SC-03、SC-12b、商店/宝箱/事件无法到达时，程序可能写入 `raw: null` / `UNREACHED`。最终判据却只检测 `sceneMismatch`，而没有 `facts/raw` 的记录被跳过。即使有缺失，也可输出 `UI_ABI_REPORT PASS`。

**最小修复**：为场景设置 `requiredReal` / `allowSynthetic` 并统一 `REAL / SYNTHETIC / UNREACHED / INVALID` 状态；所有 requiredReal 的真实到达和场景 ID 断言必须成功后方可 PASS。`SC-11a` 还应检查 `resolveScene(facts).overlays` 包含 `SC-11a`，不能只检查 `pickupPicks > 0`。

### P1-B：`--check-fixtures` 不能检测“同内容、不同 WASM 行为”的陈旧快照

源：[`native/ui_abi_dump.mjs#L575-L585`](https://github.com/tk166/RogueRust/blob/608855c2e1d6c76ebb132e8e581e2fea01edffa9/native/ui_abi_dump.mjs#L575-L585)。

现有判断只对比 `contentFingerprint`、`runObserveLen`、`combatObserveLen`。如果内核改变了数值或流程而没有改变内容指纹，旧快照仍会被判有效。

**最小修复**：报告增加 WASM 二进制 SHA-256、ABI schema/version、内容指纹；快速检查检查这三者。需要严格确保真实结果一致时，固定种子重新采集并对比关键字段（或所有规范化字段），而不是只检查元数据。区分 `metadata current` 与 `semantic regression passed`。

### P1-C：第 24 门的语义范围不能被过度宣称

源：[`native/ui_abi_dump.mjs#L471-L571`](https://github.com/tk166/RogueRust/blob/608855c2e1d6c76ebb132e8e581e2fea01edffa9/native/ui_abi_dump.mjs#L471-L571)；[`docs/ui-abi-audit.md`](https://github.com/tk166/RogueRust/blob/608855c2e1d6c76ebb132e8e581e2fea01edffa9/docs/ui-abi-audit.md)。

第 24 道门禁验证 52 个导出是函数、长度值为 19/148、选定几个哨兵、`i32::MIN` seed 合法及 18 条场景与**旧分类器自身**的 parity。这是良好的 smoke contract，但并未全面验证 52 个函数的签名、范围、内存边界、返回码及副作用。`rd_env_step(i)` 拒绝不改变状态、文本 `_len/_into` 的严格契约等并没有在这道门中被完整证明。

**最小修复**：文档/门禁命名准确表达其覆盖边界。P2 再补针对关键动作、缓冲区、错误码的少量真实契约测试。避免把“旧新分类器 parity”误当作“所有场景规则正确”的独立证明。没有必要让 P0 立刻覆盖 234 个底层导出。

### P2-A：失败的采集可能污染最后一次有效 fixture

源：[`native/ui_abi_dump.mjs#L448-L469`](https://github.com/tk166/RogueRust/blob/608855c2e1d6c76ebb132e8e581e2fea01edffa9/native/ui_abi_dump.mjs#L448-L469)。

目前先 `writeFile(p0-scenes.json)`，随后检查 `sceneMismatch`。如果采集失败，已被认可的 fixture 可能已经被坏数据覆盖。

**最小修复**：先构造、验证，再写到临时文件并原子替换，或失败时只输出独立的诊断 artifact。

### P2-B：“raw dump 没有解释”这句话不够准确

`p0-scenes.json` 同时包含 `raw`（导出原值）、`facts`（转换过的布尔值与字段）、`scene`（旧分类器计算结果）。三者设计没有问题，但文档页首“所有值均未经解释”应限定为 `raw` 字段，不涵盖整个文件。建议标出 `provenance = { raw, derived, expected }` 以供 P2 的 typed reader 明确取用。

### P2-C：一次性修改脚本不应长期堆在 `native/`

本次新增的 `p0_fix.py`、`p0_fix2.py`、`p0_report.py`、`p0_gate.py`、`p0_doc.py` 属于开发过程的一次性文本替换器，不是日常需要运行的工具；其中若干脚本直接覆盖源文件，重跑也不具幂等性。开发历史保留在 `port-plan.md` 即可。建议未来单独提交清理，保留 `ui_abi_dump.mjs` 和正式 fixture，将一次性修补工具移动到 archive 或删除。不要为了这项清理改动已经验证的 UI 功能。

### P1 UX 决策：不要让旧 `actionFor()` parity 锁死 3D 拖拽行为

当前 `actionFor(options, handSlot, targetSlot)` 在 `list.length === 1` 时即使拖在空白处也返回唯一动作。这个行为**不是内核规则漏洞**，是旧页面明确选择的操作语义。但在 StS 触摸/鼠标拖拽中，一个目标技能即便只有一个可选敌人，是否允许放在空白处直接出牌，需要产品明确决定。建议对“无需目标”和“需目标但只有一个合法敌人”分开给出交互规则。若选择改变，更新的是新 UI 输入层，不是 Rust 规则层；Parity 测试只应锁住真正需要继承的行为。

## 5. P1/P2 实施建议

### 进入 P1 的最小条件

- 保留现有 24 道闸门与真实 WASM 基线。
- 将 P1-A/B 记录为具体修复任务，在 P1/P2 集成前完成；不需等待新一轮内核重构。
- 修改 UI 计划中的两处事实过时描述，引用 `ui-abi-audit.md` 并显式列出尚未采集的 SC-12a、A20、choice、beat loss。
- P1 开始使用 Mock Snapshot 和确定性输入夹具；代码放 `web-next/`，不修改旧 `web/` 或游戏规则。

### P1 的独立退出条件

- 单一 R3F Canvas：低多边形英雄、两个敌人、10 张 3D 卡牌及 uikit HUD 同屏。
- 指针按下/拖动/目标命中/有效释放/无效释放均可复现；鼠标和触摸分别验证。
- 390×844 中文卡牌概览、选中放大、详情三种状态可读，测量压缩字体体积和资源请求。
- 3D Card 渲染组件不直接调用 `ex.rd_env_step`；只有 `CommandDispatcher`/Adapter 发起权威动作。
- 单一 WASM 来源、构建版本指纹与资源清单设计，不引入第二份脱离闸门的过期二进制。

### P2 追加的契约测试

- `--report` 必达场景和 `SC-11a` overlay 断言；`--check-fixtures` 二进制 hash。
- 一条真实 `rd_env_choice_*` 状态；关键 Action 的拒绝不变性；Beat 丢失时按最终快照收敛。
- 真实 `start -> map -> fight -> reward`；A20 双 Boss 与幕通关在后续针对性测试完成。
- 旧 `actionFor` 与新输入映射：业务含义 parity + 明确的单敌目标交互差异（如决定调整）。

## 6. 整体结论

P0 成功把 UI 架构提案带入了真实 WASM/旧 UI 数据验证阶段。新增的第 24 道门禁、真实场景 dump 与不足项清单都是很好的工程资产。但工具存在两个需要明确修复的“报告看起来通过、实际上未证实”的路径：**真实场景未采集仍可 PASS，以及仅凭内容指纹就将旧快照视为新鲜**。二者都可以在现有工具范围内局部解决。

**开工裁决：P1 放行；P0/P2 的 ABI 语义验证仍需按上述清单继续补证据。** 继续坚持“V1 的权威游戏内核 + 类型化 Adapter + R3F 渲染层”的方案，不增加无依据的新 ABI，不转入 V2 内核重构。

---

# 附：本地复核意见（第十二轮，`608855c` 上逐条核实）

> 记号：**✅ 成立** = 代码确认并已修；**⚠️ 部分** = 现象真实但结论需限定；**❌ 不成立**。

## A. 结论：四条全部成立，其中两条正是"报告通过但没证实"

| 报告项 | 复核 | 本地证据 | 处理 |
|---|---|---|---|
| **P1-A** `--report` 不保证必达场景被采集 | **✅ 成立** | 判定只有 `scenes.filter(s => s.sceneMismatch)`，而 `raw: null` 的条目在 `if (!scene.raw) continue` 里被**跳过**；`SC-11a` 的 `expected` 写成 `null` ⇒ 根本没有断言 | 改为**计划驱动**：`SCENE_PLAN` 每条标 `real` / `synthetic`，`real` 没到达或不在预期场景上就 FAIL；`SC-11a` 改为断言 overlay 真的在 `overlays` 里 |
| **P1-B** `--check-fixtures` 看不出"同内容、不同 wasm" | **✅ 成立** | 只比 `contentFingerprint` + 两个长度；内核改数值/流程而内容不变时仍算新鲜 | 记录并比较 **wasm sha256**；报错区分"代码/镜像/形状"三种漂移，并明说"这只证明元数据新鲜" |
| **P1-C** 闸门 24 的语义范围不能过度宣称 | **✅ 成立** | 它只断言导出存在、19/148、几个哨兵、18 条 parity | **不修代码，只修宣称**：审计文档 §1 列出它**没有**证明的五件事 |
| **P2-A** 失败的采集会污染上一份 fixture | **✅ 成立** | `writeFile` 在 `fail(...)` **之前** | 先构造 + 验证，再写 `.tmp` + `rename`；失败时**不写盘** |
| **P2-B** "raw dump 未经解释"不准确 | **✅ 成立** | 文件里同时有 `raw` / `facts` / `scene` | 加 `provenance`，文档与 JSON 都写明三者来路 |
| **P2-C** 一次性修补脚本堆在 `native/` | **⚠️ 部分** | 仓库惯例**确实**保留 `patch_*.py` 作为"那一节改动源码的脚本"记录 | 删掉唯一真正**失败并被取代**的 `native/p0_fix.py`（它曾把 `fight helpers` 当替换文本写进源码）；其余按惯例保留 |
| **P1 UX** `actionFor` 的单敌行为不该被 parity 锁死 | **✅ 成立** | `if (list.length === 1) return list[0].actionIndex` —— 定向牌只剩一个敌人时拖到空白也打出去 | 写进审计文档 §5b 作为**产品决策**：P1 必须分别测空白/单敌/多敌，parity 只锁业务语义 |

## B. 对 P2-C 的一点保留

"把一次性脚本移出 `native/`"这条方向我同意，但**不能一刀切**：本仓库的惯例是
`native/patch_*.py` / `negctl_*.py` 与 `port-plan` 的每一节**一一对应**，它们记录了"那一节
到底改了哪些字节、怎么反证的"。删掉它们等于删掉证据链。

所以这次只删 `p0_fix.py` —— 它是**失败的**（参数顺序错，把 `fight helpers` 写进了源码），
随后被 `p0_fix2.py` 取代，没有任何记录价值。`p0_report.py` / `p0_gate.py` / `p0_doc.py`
是**成功应用**的那几次改动，保留。

## C. 两条修复的负控（都已跑过）

| 负控 | 结果 |
|---|---|
| 把"走到商店/宝箱/事件"短路（模拟场景不可达） | `UI_ABI_REPORT FAIL` 并列出 `SC-05-shop=UNREACHED, SC-07-treasure=UNREACHED, SC-08-event=UNREACHED`；**fixture 的 md5 未变**、无残留 `.tmp`（P1-A + P2-A 同时证明） |
| 篡改 fixture 的 `wasmSha256` | `UI_ABI FAIL: fixtures are stale: wasm sha256 000000000000 -> 4c343910bf68 (the kernel changed)`，并提示"这只证明元数据新鲜"（P1-B） |

## D. 我同意报告的三条判断

1. **P0 放行进入 P1** —— 契约基线 + 12/12 真实场景已经够开工。
2. **第 24 门是 smoke contract，不是 ABI 兼容验证** —— 已在审计文档与 port-plan §350b 写明。
3. **"旧新分类器 parity"不等于"场景规则正确"** —— 两边一起错时 parity 也绿。这条我在
   `ui-state-model.md` §7d 写过一次（"这套夹具没证明什么"），这里是同一个形状，值得重复。

## E. 一句话

四条全部成立：两条是"报告通过但没证实"（**P1-A 缺场景仍 PASS**、**P1-B 元数据新鲜 ≠ 语义一致**），
两条是卫生问题（失败污染 fixture、provenance 表述）。四条已修并各配负控；P1-C 只改宣称，
P1 UX 决策写进审计文档 §5b 留给 P1 决定。
