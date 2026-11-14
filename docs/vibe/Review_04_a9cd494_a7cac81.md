# RougeRust 增量 Code Review（§170–§171）

- **审查提交**：`a9cd494`、`a7cac81`（前置基线 `5c467b6`）
- **第一阶段目标**：WASM 玩法正确性、开发效率、可验证性；不为 MCU/极端内存预算扩大改动
- **审查类型**：GitHub 公开源码静态审查，**没有独立运行构建、测试或故障注入**
- **结论**：上轮六项 P0/P1 的修复方向总体正确；本轮发现一项 **P1 测试假阳性** 和两项 **P2 验证流程/运行寿命风险**。不建议由此展开新的全局重构。

## 1. 上轮问题闭环情况

| 上轮问题 | 本轮修改 | 静态审查结论 |
|---|---|---|
| P0：回放跨导出保留全局可变借用 | 回放每次短借用 Session；不在借用存活时重入其他导出 | 关键路径已按建议修改；未做 Miri 验证 |
| P1：战斗构造失败残留 `in_fight` 和部分状态 | 构造前快照，出错丢弃 Combat Session 并回滚，成功后才提交标记 | 主流程符合预期；晚期失败的真实故障注入仍未覆盖 |
| P1：允许重复开战 | 在 `fight_begin` 入口用 `in_fight` 拒绝 | 已确认 |
| P1：脚本导出 / 回放只靠 UI 守卫 | ABI 层 `script_fill` 与 `replay_from` 检查 `in_fight` | 已确认 |
| P1：`run_hash()` 失败变成有效值 0 | `state_hash() -> Option<u64>`，记录 `hash_failed` 并在输出/回放时报错 | 错误传播已改进；最大状态边界测试存在新问题（见 P1-1） |
| P1：`rd_run_script_into` 缺少调用方容量 | 删除冗余无容量 ABI，统一 `fill + buf + capacity` | 正确，优于保留第二条写入路径 |

依据：
- [`rd-wasm/src/run.rs` @ a7cac81](https://github.com/tk166/RogueRust/blob/a7cac81/kernel/rd-wasm/src/run.rs)
- [`rd-run/src/hash.rs` @ a7cac81](https://github.com/tk166/RogueRust/blob/a7cac81/kernel/rd-run/src/hash.rs)
- [commit a9cd494](https://github.com/tk166/RogueRust/commit/a9cd494)、[commit a7cac81](https://github.com/tk166/RogueRust/commit/a7cac81)

## 2. 新发现

### P1-1：所谓“最大合法状态”的哈希测试没有构造出最大状态（确认）

**位置**：`kernel/rd-run/src/hash.rs`，`the_largest_legal_run_fits_the_hash_buffer()` / `big_run()`。

测试声称：60 张最大长度 ID 的卡牌、24 件遗物、5 瓶药水，总计规范文本 `4186 B / 8192 B`，并据此声称 1.96 倍安全余量。

实际辅助函数：

```rust
for _ in 0..MAX_RUN_RELICS {
    let _ = state.push_relic(relic);
}
for _ in 0..MAX_RUN_POTIONS {
    let _ = state.push_potion(potion);
}
```

两个问题：

1. `relic` 被传为 `"z".repeat(ID_CAP)`。`RunState::push_relic()` 首先检查 `relic_effect(relic_id)`，不支持的 ID 会返回 `UnsupportedRelic`；于是**24 次插入均失败**，但 `let _` 把失败吞掉了。
2. 测试运行于 **Ascension 20**。该等级在没有 `potion_belt` 时只有 **2** 个药水槽，故五次 `push_potion` 最多成功两次。由于遗物构造全部失败，也不会获得药水腰带。

因此 `4186 B` 不是类型上界，仅仅是本次不完整夹具的测量值。**不能据此认定 8192 B 必然安全或有 1.96 倍余量**；但也没有证据说明真实状态已发生溢出。

**最低修复**：

- 所有用于准备边界状态的 `push_*` 均用 `.expect()` 或断言明确检查结果，禁止 `let _ =`。
- 在计算文本长度之前显式断言 `deck().len()`、`relics().len()`、`potions().len()` 与目标一致。
- 区分“真实合法内容下可达的最大状态”和“结构可表示的最大状态”；两者应分别测量，不应混用。
- 对结构上界构造合法的测试专用状态夹具，并覆盖满商店、满奖励屏以及其他可变长字符串字段；必要时仅在 `#[cfg(test)]` 下提供构造接口。
- 不必急于扩张 `MAX_TEXT`；先获得有效测量，再决定是否调整。

**建议负控**：故意让最后一个遗物或药水插入失败，测试必须在测量文本长度之前失败；故意增大字段容量，应让上界测量结果/余量断言及时响应。

源码依据：
- [`hash.rs` 新测试](https://github.com/tk166/RogueRust/blob/a7cac81/kernel/rd-run/src/hash.rs#L290-L355)
- [`RunState::push_relic()`](https://github.com/tk166/RogueRust/blob/a7cac81/kernel/rd-run/src/state.rs)
- [`RunState::potion_slots()`](https://github.com/tk166/RogueRust/blob/a7cac81/kernel/rd-run/src/state.rs)

### P2-1：负向控制脚本将“任意非零退出”视为成功抓错（确认）

**位置**：`native/negctl_170.py`，`run_test()` 与 `main()`。

当前逻辑：

```python
code, out = run_test(test)
red = code != 0
```

这只能证明命令失败，不能证明**预期测试断言**捕获到了故意注入的逻辑回归。Rust 编译失败、Cargo 路径无效、环境配置损坏、无关 panic，都可能让负控显示 `[RED] ... caught`。

**建议**：

1. 同一测试在未变异前必须先通过（GREEN 基线）。
2. 变异后要求编译成功、测试实际被执行且因为预期断言失败；检查 `test result: FAILED`、具体测试名及预期失败标记，而不只检查进程退出码。
3. 如需保留脚本，尽量在临时工作树运行；目前它直接覆盖 `rd-wasm/src/run.rs`，虽有 `finally` 恢复，但强制结束进程仍可能留下修改。
4. 将本机绝对路径转为 PATH / 参数 / 环境变量，降低运行环境耦合。

源码：[`native/negctl_170.py` @ a7cac81](https://github.com/tk166/RogueRust/blob/a7cac81/native/negctl_170.py)

### P2-2：`Box::leak` 每场战斗永久保留卡牌字符串（已知风险，非本轮新回归）

**位置**：`rd-wasm/src/run.rs`，`rd_run_fight_begin()` 的 `DeckEntry<'static>` 构造。

这次修复使卡牌字符串拥有独立存储，避免把指向 `RunState` 的借用跨越回滚，这是正确方向；但逐条 `Box::leak(card.into_boxed_str())` + 泄漏 slice 的做法每场战斗都会永久留下数据，失败构造同样可能留下它们。

**建议**：第一阶段不需要为此重写战斗引擎，更不需要 MCU 内存预算；可保留为明确的 P2 技术债，并仅在可玩完整局之后测量多局连续运行的内存增长。未来如果确有必要，应让 Combat Session **拥有**这些 ID 和 `DeckEntry` 存储，或使用生命周期明确的 arena，而不是 `&'static` 泄漏。

源码：[`run.rs` `Box::leak` 区域](https://github.com/tk166/RogueRust/blob/a7cac81/kernel/rd-wasm/src/run.rs#L2850-L2875)

## 3. 值得沉淀的优秀实践

1. **错误路径在 ABI 层守卫**：调用者可以是浏览器，也可以是 Replay/RL；页面模式不是规则权威。
2. **战斗初始化有明确提交点**：`in_fight`/`elite_fight`/`boss_fight` 仅在全部成功后更新，前序失败回到快照。
3. **优先删掉重复的危险接口**：一条 `fill/buf/capacity` 路径优于维护两套功能重叠的 ABI。
4. **为不可达边界公开验证限制**：§170.6、§171.1 主动披露“防御分支未被真实触发”，做法正确；但必须确保测试夹具满足其宣称前提。
5. **让 Rust 借用检查器参与发现结构问题**：修正 `DeckEntry` 不应借用可回滚 `RunState` 的存储是有价值的收获；以后要进一步避免泄漏。
6. **测试目标、准备过程、断言三段都要验证**：这是本轮最应该新增的一条规范。

## 4. 是否曲解上轮建议？

整体没有。Agent 对 Session 生命周期、失败原子性和 API 去冗余的理解与建议一致，并清楚记录了没有执行的故障注入。

唯一需要纠正的是：**“最大状态测量”不等于“循环尝试填满容量”**。一旦循环允许插入失败且不检测结果，任何所谓的最大值都不能作为上界证明。这是测试质量问题，而非需要再次架构重构。

## 5. 下一轮最低任务清单

- [ ] **P1** 修正 `big_run` 的失败吞没；补充元素数量、状态合法性检查，并重新报告规范文本长度与余量。
- [ ] **P1** 若目标是结构上界，另外构造测试夹具覆盖满遗物、满药水、满商店/奖励等极值，不将部分状态说成理论最大值。
- [ ] **P2** 给负控添加 GREEN 基线、编译通过及预期测试断言失败的验证。
- [ ] **P2** 将 `Box::leak` 记录为长期会话寿命风险，暂时不开展全局所有权重构。
- [ ] 当前临时 UI 的像素测试无需扩展为正式视觉回归工程。

**完成以上 P1 后，建议回到 WASM 的机制与内容开发；不要继续无止境地扩张验收体系。**

## 6. 证据边界

项目日志声称 §171 后为 **812 个单元测试、20/20 闸门通过**。本文未独立运行，不能将此视为复验结果。`4186 B` 是仓库报告的测试值，审查证明其**不是上界测量**，但没有独立重算正确上界数值。
