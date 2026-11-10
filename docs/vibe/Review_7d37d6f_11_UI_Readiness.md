# RogueRust 第十一轮 Review：7d37d6f 与下一代 UI 的接口就绪性

- **目标提交**：[`7d37d6f5f8d99c6547edaa5c709eeea95c939f9c`](https://github.com/tk166/RogueRust/commit/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c)
- **范围**：§348 修复、相关 WASM 查询、`web/ui_panels.js`、`web/index.html`、`docs/ui-state-model.md`、第 23 道门禁及负控。
- **评审类型**：针对性静态代码审查。通过该提交 SHA 读取版本固定的源码；未获得完整 Git diff，也没有在本环境独立构建、执行 Rust/WASM/浏览器测试。因此不得将仓库自报的 1233 个单测、23/23 道门禁视为独立复验。
- **结论**：**GO：可以开始新 UI 的架构设计和 Adapter/场景原型。NOT YET：不宜将全部现有 WASM 导出立即冻结为正式 UI v1。**

## 1. 上轮四项问题闭环

| 问题 | 版本固定源码中的修改 | 结论 |
| --- | --- | --- |
| Boss 查询始终使用候选池第一只 | `boss_enemy_id()` 现在只在 `last_encounter` 属于本幕 Boss 池时返回真正敌人 ID，否则 `None` | 对普通单 Boss 流程成立；A20 边界见 P1-1 |
| `rd_run_over` 仍在 `KNOWN_ABSENT` | 只剩 `rd_env_observe` 的特殊豁免；增加“移除真实导出必须报错”的负控 | 已闭环 |
| `i32::MIN` 被用作没有 Run 的判断 | 新增 `rd_run_exists() -> 0/1`，页面 `noRun` 改用该值 | 已闭环 |
| 未知 `Pending` 被无条件兜底吞没 | `SC-02` 只接受 `pending === 0`，未知值落到 `SC-??` 显式报告 | 已闭环 |

主要源码：
- [`run.rs#L1022-L1075`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/kernel/rd-wasm/src/run.rs#L1022-L1075)
- [`run.rs#L925-L936`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/kernel/rd-wasm/src/run.rs#L925-L936)
- [`ui_panels.js#L475-L505`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/web/ui_panels.js#L475-L505)
- [`ui_state_check.py#L50-L58`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/native/ui_state_check.py#L50-L58)
- [`port-plan.md §348`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/docs/port-plan.md)

### 设计上值得保留的实践

- **未知值保持未知**：没有实际选择的 Boss，不再使用池中第一只“猜答案”。
- **状态存在性与数据值分离**：合法 seed 不再与空状态哨兵冲突。
- **未知 Pending 显性失败**：协议增加值时，未适配 UI 不再装作仍然是地图。
- **检查器验证自身反例**：对真实导出实施删除变异，而不仅是制造一个不存在的名字。
- **诚实限定测试能力**：§7d 承认手写场景夹具并不能证明真实 WASM 状态可达、每个业务谓词正确。

## 2. P1：A20 连续 Boss 的身份存在残留语义错误

### 证据

当前 Boss ID 用：

```rust
boss_enemy_id(content(), session.state.act(), session.state.last_encounter().as_str())
```

而 A20 在第三幕击败第一只 Boss 后：

```rust
if self.at_least(A_DOUBLE_BOSS) && self.bosses_fought == 0 {
    self.bosses_fought = 1;
    self.resolved = [0; 2];
    return;
}
```

第一场结束后，本幕第二个 Boss 节点重新开放；`last_encounter` 仍可保存上一只 Boss，直到第二次 `fight_begin()` 才覆盖。因此在**第二场开打前**，`rd_run_boss_id_*` 仍可能返回第一只。

代码：[`rd-run/state.rs#L4375-L4386`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/kernel/rd-run/src/state.rs#L4375-L4386)、[`rd-wasm/run.rs#L1022-L1075`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/kernel/rd-wasm/src/run.rs#L1022-L1075)。

这是根据源码推导的高置信度缺陷路径，**尚未独立运行复现**。其本质是“上一只 Boss 身份”和“即将挑战的 Boss 身份”不同。

### 最小修复建议

- 明确 Boss 查询的时间语义：`lastBossId`、`activeBossId`、`nextBossId` 不应默认合并。
- 当前版本在“第二个 Boss 尚未选择/尚未开战”时应返回未知，不能把第一只当成第二只；可以通过 A20 `bosses_fought`、节点阶段和 `in_fight` 做受控判定。
- 为 A20 完整流程补一条定向测试：第一场前未知 → 战中 Boss A → 第一场奖励保留 A → 第二场前未知 → 第二场开始 Boss B；若原版规则要求 B != A，还要单独验证选取约束。
- 不要为了修显示问题提前调整选 Boss 的 RNG 时机（会牵动重放/存档黄金契约）；“进入幕时预选 Boss”作为独立玩法保真度项目。

## 3. P1：UI 状态文档尚未完全同步到真实接口

`docs/ui-state-model.md` 依然有旧描述：

1. §1 SC-00 判据仍写 `rd_run_seed() == i32::MIN`，真实 UI 已改为 `rd_run_exists()`。
2. §5 “有没有局”仍用 seed 哨兵举例。
3. §3.3 `bossName` 仍写“无导出 / Slime Boss 写死”，而 §6 G5 已声明有 Boss ID 接口。
4. `run.rs` 中 `boss_enemy_id` 函数上方注释仍描述“取池中第一条”，与函数实现相反；`ui_panels.js` SC-00 注释也残留 Seed 哨兵。

依据：[`ui-state-model.md#L97-L110`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/docs/ui-state-model.md#L97-L110)、[`ui-state-model.md#L283-L300`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/docs/ui-state-model.md#L283-L300)、[`ui-state-model.md#L694-L705`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/docs/ui-state-model.md#L694-L705)、[`run.rs#L1013-L1043`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/kernel/rd-wasm/src/run.rs#L1013-L1043)。

这些不是新的运行时 Bug，但该文件即将成为新 UI Agent 的规格，**优先修文档**是必要的。第 23 道门禁验证名字覆盖，不验证判据所述语义，不能指望它自动发现这些冲突。

## 4. UI 架构阶段应解决的两个表示问题（不是本次 Rust 回归）

### P2-A：`classifyScene()` 把基础场景与覆盖层合在一个 ID

`SC-11a/11b` 是模态覆盖层，但返回的 `classifyScene(snapshot)` 是第一个命中 ID。奖励屏 + 遗物选牌欠账时，返回 SC-11a，SC-04 只能从其他逻辑重新推导。当前 DOM 面板“用覆盖层暂时替换正文”是合理权衡，但 3D/Live2D 更需要复合状态：

```ts
type SceneResolution = {
  baseScene: SceneId;
  overlays: OverlayId[];
  unknownPending?: number;
};
```

建议 **保留原 `classifyScene()` 兼容旧页面**，在新 UI adapter 中，复用 `RAW/SCENES` 的判据生成结构化 `resolveScene()`；以“奖励 + 遗物选牌”真实快照测试两层可同时存在。

依据：[`ui_panels.js#L450-L511`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/web/ui_panels.js#L450-L511)。

### P2-B：页面快照把 Boss ID 过早变成了显示名

`runSnapshot()` 当前直接执行：

```js
bossName: RD_UI.displayName(
  readText(() => ex.rd_run_boss_id_len(), (ptr) => ex.rd_run_boss_id_into(ptr)),
  ""
)
```

这样下游只能得到格式化名称，不能可靠按内部 ID 绑定 3D 美术、声音和本地化内容；与 `ui-state-model.md` “内核给 ID，显示层给名字”的原则存在边界偏差。

建议新 Adapter 同时保留 `bossId: string | null` 和派生 `bossLabel`，不能以本地化文案反查身份。事件 ID、遭遇 ID、敌人 ID 也同理。旧 DOM 保持不变。

依据：[`web/index.html#L926-L931`](https://github.com/tk166/RogueRust/blob/7d37d6f5f8d99c6547edaa5c709eeea95c939f9c/web/index.html#L926-L931)。

## 5. 对 WASM–UI 契约的就绪性判断

| 领域 | 结论 | 是否阻塞 UI 架构设计 |
| --- | --- | --- |
| Run 是否存在 / 是否战斗中 / 终局 | 权威查询已具备 | 否 |
| 主要场景、Pending 与合法动作 | 已有可复用机制，未知态能显性失败 | 否 |
| 基础观察、身份、动态字段 | 已有接口，但未来新 Adapter 要统一解释哨兵/长度/字节生命周期 | 否 |
| Boss 预告和 A20 双 Boss | 仍有已知行为差异/查询歧义 | 不阻塞整体设计；阻塞准确 Boss 预告功能 |
| 文档语义一致性 | 本轮修代码未完全同步表格 | 开始架构前应先做小修 |
| 3D 场景 + 覆盖层组合 | 单值分类器无法直接表达复合层 | 在新 UI Adapter 层设计 |
| 真实 WASM 状态夹具 | §7d 明确承认仍缺 | 在新 UI 首轮原型时补 |
| 门禁 23 | 名称防腐有效，但不足以证明 ABI 语义 | 不阻塞；不要误标为完整 ABI 兼容验证 |

建议明确区分 **底层 WASM ABI**（现有多个底层导出）与 **新 UI 需要的上层适配契约**。后者应尽快形成一个 `GameSnapshot / SceneResolution / LegalAction / GameBeat` 模型，UI 只依赖该模型，不直接在 3D 组件中散布 `rd_*` 调用。

数据生命周期规范：先执行内核 Action，再采集一份一致的快照，再根据 Beat 驱动表现；Beat 不能代替最终事实。对 WASM memory 暴露的 `Int32Array` 视图，明确 `memory.grow`、重新开局或其他缓冲区复用之后是否需要重新绑定；在桥接层统一处理，不让渲染组件直接持有 WASM 内存指针。

## 6. 建议的极小后续任务

1. **P1：A20 两 Boss 身份**：对“上一场”和“下一场”建立清晰契约，补真实流程测试。
2. **P1：修正文档**：SC-00、§5 存在性判据、Boss 字段以及代码陈旧注释；更新 G5 的“开战前未知”限制。
3. **新 UI 架构：Adapter**：保留 ID + 本地化名称；分离底层场景和 overlays；统一类型、哨兵、字符串读取及缓冲区生命周期。
4. **新 UI 首轮测试**：采集真实 WASM 快照（无 Run、合法最小 Seed、开战前/中/后、奖励覆盖层、Boss、A20 双 Boss），而非只用手写夹具。
5. **暂缓**：修改全体 234 个 ABI、V2 内核重构、3D 像素级门禁；这些都不是当前架构设计的先决条件。

### 结论

**GO for new UI architecture / adapter / prototype; NOT YET for freezing the entire low-level WASM ABI as UI v1.**

这轮 Agent 的修复体现了较好的边界意识和负控意识，未从审查过的代码中发现新的 P0。最有价值的下一步不是继续为临时 DOM 页面打补丁，而是以权威状态与现有 ABI 为基础做一层薄 Adapter，借助真实状态夹具推动新的 UI 数据契约成熟。


---

# 附：本地复核意见（第十一轮，`7d37d6f` 上逐条核实）

> 记号：**✅ 成立** = 代码确认；**⚠️ 部分** = 现象真实但描述需修。

## A. 四条发现全部成立

| 报告项 | 复核 | 本地证据 | 处理 |
|---|---|---|---|
| **P1-1** A20 第二只 Boss 未选时仍报第一只 | **✅ 成立** | `mark_boss_beaten` 在 A20 第一只倒下后 `bosses_fought = 1` 并**不清** `last_encounter`；而 `boss_enemy_id` 只看"是否落在本幕池里" | 拆成三种时间语义，双 Boss 之间返回**未知**（§349） |
| **P1-2** 文档/注释未同步 | **✅ 成立（四处）** | `run.rs` 的 `boss_enemy_id` 文档仍写"第一条遭遇"；`ui_panels.js` SC-00 注释仍写 seed 哨兵；`ui-state-model` §1/§3.2/§5 三处；§3.3 `bossName` 仍写"无导出" | 全部改掉，并补上三种时间语义与"进幕即定"偏差 |
| **P2-A** `classifyScene` 把两层合成一个 id | **✅ 成立**（设计权衡，非缺陷） | 覆盖层按定义叠在底屏上 | 新增 `resolveScene()`，保留 `classifyScene` |
| **P2-B** 快照把 Boss id 过早变成名字 | **✅ 成立** | `runSnapshot()` 的 `bossName` 直接过 `displayName()` | 快照加 `bossId`，`bossName` 只作标签 |

## B. 我同意报告的两条"边界声明"

1. **门禁 23 不是 ABI 兼容验证** —— 它只做名字双向对账。报告没有把它误标成"完整验证"，
   这一点值得记：§7d 已经写了"这套夹具没证明什么"，同理"这道闸门没证明什么"也该写。
2. **"进幕即定 Boss"是独立的玩法保真度项目**，不该为了 UI 显示去改选 Boss 的 RNG 时机
   （会牵动 `corpus` / 存档 / 回放）。已记进 `docs/sts-wiki-gap.md` 的已知偏差。

## C. 关于"GO / NOT YET"的判断

同意。新 UI 的第一层不该是"直接在 3D 组件里散布 `rd_*` 调用"，而应是一层薄 Adapter：
`GameSnapshot / SceneResolution / LegalAction / GameBeat`。本轮的 `resolveScene` 与 `bossId`
就是这一层的第一块（都是**加**在现有结构上，没有动 DOM 版行为）。

## D. 顺带记一个自己造的事故

负控脚本末尾那行"把页面原样写回"（`open('w')` 先截断）把 `web/index.html` 清成了 0 字节。
恢复靠 `git checkout` + 重打补丁。**"为了保险"加的一行，恰好是唯一破坏数据的一行。**

> **一句话**：四条全部成立且已修；P1-1 是"上一只"与"下一只"被合并，P1-2 是"改了代码没改注释"。
> 同意报告的分期结论：可以开始新 UI 架构，但不要把 234 个导出立刻冻结成 UI v1。
