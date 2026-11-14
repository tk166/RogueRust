# RogueRust 第十轮增量代码审查

> **审查范围**：`857972bd723d6cb22479e53ec59b4fa7d369eec1^..4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2`  
> **审查重点**：第九轮问题闭环、内核契约、StS1 商店规则、WASM/UI 状态查询与场景门禁。  
> **证据边界**：通过指定提交版本公开源码及 `docs/port-plan.md` §342–§347 进行定向静态核查；没有取得完整 Git compare 补丁，也没有本地编译或执行测试。本文中“已修复”表示代码核对，“仓库报告通过”不是独立复验。

## 0. 结论

本轮的改动总体 **保持了 V1 既有分层和语义边界，没有必要重构整个引擎**。上一轮商店价格与删牌规则的主要问题已得到针对性处理；`RunEnd`、战斗运行标志和 `SCENES` 作为 UI 唯一判定入口的方向值得保留。

新发现的主要风险集中在 UI *查询值的真实性* 与 *门禁能否检测字段变更*：

| 优先级 | 发现 | 属性 |
|---|---|---|
| P1 | `rd_run_boss_id_*` 从本幕 Boss 池直接取第一条，不是本局实际 Boss | 新增功能语义错误 |
| P1 | `ui_state_check.py` 仍把已经存在的 `rd_run_over` 放在 `KNOWN_ABSENT`，删除导出时可能假绿 | 门禁契约缺口 |
| P2 | `noRun` 采用与合法 `i32` seed 冲突的 `i32::MIN` 哨兵 | UI 边界错误 |
| P2 | `SC-02` 无条件兜底使 `SC-??` 实际不可达，新 Pending 会静默落到地图 | 场景扩展风险 |
| P2 | `scenesMatching` 使用互斥包装后的谓词，自证“恰好一条基础场景” | 门禁证据强度限制 |

## 1. 上一轮问题的闭环情况

| 上轮关注项 | 本轮核对 | 证据与注意事项 |
|---|---|---|
| 四排货架折扣价格一致 | **源码已核实** | 有色卡/遗物/无色卡/药水价格 ABI 均以 `RunState::shop_price()` 计算；已售的负价哨兵保留不变。 |
| Courier 遗物补货按稀有度定价 | **计划与代码方向一致** | §342 记录补货定价修正，`restock_relic_slot()` 使用选出遗物自身的稀有度；未本机跑覆盖三种稀有度的测试。 |
| Smiling Mask 价格优先级 | **源码已核实** | `remove_card_price()` 在持有 Smiling Mask 时直接返回 50，而非再交给折扣函数；符合 StS1 Merchant Wiki。 |
| 每家店一次删牌 | **本轮新增且合理** | `remove_card()` 中守卫 `removed_this_shop`；实际牌组删除放在 `remove_deck_card()`，供非商店流程复用；进入新商店时复位标志。 |
| 删牌状态可存档、可回放 | **计划报告已接入** | §343 记录 archive 版本升级及全字段覆盖门禁更新；建议继续维护字段清单。 |
| UI 结算权威状态、休息回复量 | **源码已核实** | `rd_run_over/_why`、`rd_run_rest_heal` 来自 `RunState`；终局不需要网页历史变量重建。 |
| 场景互斥与可达性测试 | **已实现首轮夹具，但并非完整证明** | `web/ui_test.mjs` 18 个合成快照，负控 4/4（仓库记录）；需要追加真实状态快照和未知状态负控。 |

**有关 Courier 的说明**：上一轮建议“有色卡补货必须保留 Attack/Skill/Power 槽位类别”证据不足。§342 记录了 Agent 对 StS1 与 StS2 商店“same type”语义的区分。**不应将尚有歧义的推断继续当作 P1 修复要求**。如要追求更精确行为，应以 StS1 原版实测或明确的 StS1 参考实现裁决。

StS1 Merchant 参考：<https://slaythespire.wiki.gg/wiki/The_Merchant>。

## 2. 新发现 P1：Boss 名称查询不代表本局实际抽取结果

**文件**：[`kernel/rd-wasm/src/run.rs#L1001-L1043`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/kernel/rd-wasm/src/run.rs#L1001-L1043)

当前 `boss_enemy_id(content, act)` 的逻辑：

```rust
let ids = content.encounter_pool(pool)?;
let encounter_id = ids.iter().find(|id| !id.is_empty())?;
// ... 再取该遭遇的首个敌人 ID
```

本次内容的 Boss 池每幕有三个等权遭遇，例如第二幕 `enc_the_champ / enc_bronze_automaton / enc_the_collector`，第三幕 `enc_time_eater / enc_awakened_one / enc_donu_and_deca`。因此上述逻辑只会为每幕返回第一只 Boss，而**实际战斗入口从 Boss 遭遇池中选择遭遇**。网页 `runSnapshot()` 将其作为 `bossName` 显示。

现有测试 `the_boss_id_follows_the_act()` 仅检查三个幕的名称不同，且默认断言 Act 1 = `slime_boss`，无法发现“同一幕中不同种子仍返回第一只”的错误。

**影响**：在游戏路线中可能预告错误 Boss；未来 UI 把图标/演出/工具提示绑定到 `bossName` 时会扩大影响。对于 StS1，地图上看到的 Boss 应是本局已经选定的那一只，而不是同一幕的候选列表第一项。

**建议的最小修复**：

1. 在运行层为每幕确定并保存**本局选定**的 Boss encounter ID；或，如果设计暂未承诺进入幕时就选 Boss，则至少在进入 Boss 节点后以实际 `last_encounter` 给出名称，不得冒充早已选定。
2. 名称 ABI 只转换已选定实体，显示层仍保留 ID → 名称映射职责。
3. 增加两种 seed 选到本幕不同 Boss 的测试，并核对 `rd_run_boss_id_*` 与真正开战的敌人 ID。
4. 在 A20 第三幕双 Boss 的情况下明确当前/下一只 Boss 的查询语义。

## 3. 新发现 P1：UI 门禁仍将 `rd_run_over` 视为“已知不存在”

**文件**：[`native/ui_state_check.py#L50-L57`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/native/ui_state_check.py#L50-L57)，[`#L96-L106`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/native/ui_state_check.py#L96-L106)。

本轮 `rd_run_over()` 已经是真正的 WASM 导出，但门禁的 `KNOWN_ABSENT` 仍然包含：

```python
'rd_run_over': '§1 / §6-G1：标注“尚未导出”，是待补项（G1）'
```

而缺失检查条件是 `name not in have and name not in KNOWN_ABSENT`。**如果未来误删 `rd_run_over` 导出，只要文档仍引用它，检查器仍可能报告通过**。这恰恰违背了该门禁“接口删除必须让文档检查失败”的主要目的。

**建议**：从 `KNOWN_ABSENT` 删除该项，修订旧注释；为本轮新导出的权威查询增加一次“删除导出签名 → MISSING 报错”的负控。注意不要将源代码语法/编译失败误报成预期语义失败。

## 4. P2：`noRun` 的值域与合法 seed 冲突

**文件**：[`web/index.html#L883-L890`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/web/index.html#L883-L890)，[`kernel/rd-wasm/src/run.rs#L1093-L1097`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/kernel/rd-wasm/src/run.rs#L1093-L1097)。

```js
noRun: ex.rd_run_seed() === -2147483648
```

ABI `rd_run_seed()` 在无局时返回 `i32::MIN`，有局时返回真正的 seed；而 `rd_run_start(seed: i32, ...)` 未显式排除这一 seed。**将数据域中的一个可能合法值兼作“无值”哨兵，导致该 seed 对应的真实 Run 可能被识别为 `SC-00` 未开局。**

建议使用显式 `rd_run_exists()`，或者复用一个不会与正常有效值冲突的会话存在性判断；若不增加 ABI，可先组合现有查询并做跨层测试。必须加入 `seed = i32::MIN` 的边界用例。

## 5. P2：场景兜底掩盖未来新增 Pending 的缺失

**文件**：[`web/ui_panels.js#L450-L508`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/web/ui_panels.js#L450-L508)。

`RAW` 最后一行：

```js
{ id: 'SC-02', overlay: false, test: () => true }
```

这样对任意输入，至少有一条基础场景命中；`classifyScene()` 最后的 `SC-??` 不可达。**若将来 Core 新增 `Pending=99`，UI 会静默把它显示成普通地图而不是“未知游戏状态”。**

建议地图兜底至少要求 `pending === 0`（并遵守已写明的终局、战斗优先级），对未知值返回显式 `SC-??` / 诊断面板。增加 `pending=99` 的负向夹具；不需要重写整套场景模型。

## 6. P2：场景“唯一命中”测试的证据含义

`SCENES` 对每条基础场景都自动附加 `!earlier.test(s)`；`scenesMatching()` 又检查这个**已经互斥化**的结果。因此“恰好命中一个基础场景”多数情况下是包装构造保证的数学性质，不是独立证明 `RAW` 业务条件正确。

这不是设计错误：自动互斥本身减少重复否定条件。**问题是测试结论不能提升为“所有业务场景条件已独立验证”。** 应保留现有夹具及负控，并增加少量从真实 WASM 状态采集的场景快照，重点覆盖：

- 未开局/合法最小 seed；
- 战斗前、战斗中、战斗后；
- 宝箱和遗物领取叠层；
- Boss 节点及第三幕 A20；
- 未知 Pending 的失败显性化。

无须为了临时 UI 制作像素级回归体系。

## 7. 做得好的设计与可复用实践

1. **角色职责分离**：删牌规则在 `RunState`；WASM `rd_run_removal_available` 只作为查询；页面只负责按钮是否可操作。非商店删牌走底层独立方法，避免“全局只允许删一次”的误伤。
2. **权威状态而非 UI 历史**：`RunEnd`、`in_fight`、事件与遭遇 ID 来自运行层；页面不用自行重建战斗或终局事实。
3. **轻量的“真实需求→最小接口”迭代**：名字映射、休息治疗、Boss ID 查询并不强迫内核理解展示语言；内容扩充阶段保持 V1 可维护性。
4. **测试主动变异**：每轮努力验证“会红”，尤其 UI 构造式分类和商店行为。但应进一步检查负控的**失败原因**是否与被宣称证明的规则相同。
5. **独立 Wiki 裁决**：Agent 对 STS1/STS2 补货语义提出证据异议是恰当的；审查者先前的推断不应自动升级为冻结需求。

## 8. 下一轮建议的最小工作包

| 优先级 | 工作包 | 通过条件 |
|---|---|---|
| P1 | Boss 身份改为实际本局选定值 | 同幕不同 seed 抽到不同 Boss，UI 名称与实际战斗一致 |
| P1 | 清理 UI 门禁的 `KNOWN_ABSENT` | 删除 `rd_run_over` 导出时 `UI_STATE_CHECK` 必须失败 |
| P2 | 消除 seed 哨兵碰撞 | `i32::MIN` 启动合法 Run 时不显示未开局 |
| P2 | 显性拒绝未知 Pending | `pending=99` 返回未知场景，不静默落地图 |
| P2 | 场景测试增加真实状态夹具 | 在宿主中采集少量真实状态，测试分类和合法动作 |

**不建议**：借此轮启动 V2 内核重构、统一替换所有 ABI、或为临时 UI 构建完整像素级门禁。

## 9. 固定版本源代码链接与验证边界

- [运行层状态与商店规则 `state.rs`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/kernel/rd-run/src/state.rs)
- [WASM 运行层 ABI `run.rs`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/kernel/rd-wasm/src/run.rs)
- [浏览器状态构造 `index.html`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/web/index.html)
- [场景纯函数 `ui_panels.js`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/web/ui_panels.js)
- [文档与导出检查 `ui_state_check.py`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/native/ui_state_check.py)
- [实际内容库 `sts.roguedeck.json`](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/tools/contentc/packages/sts/sts.roguedeck.json)
- [开发历史 §342–§347](https://github.com/tk166/RogueRust/blob/4a4ea004d1ec53eb912a314bd6b296d4f8ab8da2/docs/port-plan.md)
- [StS1 Merchant Wiki](https://slaythespire.wiki.gg/wiki/The_Merchant)

仓库记录的最近一轮统计是 rd-core 819 / rd-run 225 / rd-wasm 189，共 **1233** 个单元测试、**23/23** 道验收闸门通过。该数据未独立验证。尤其不能把绿灯视为已经覆盖“本幕三选一 Boss 的真实身份”和“未知 Pending 必须暴露错误”的证明。

---

# 附：本地复核意见（第十轮，`4a4ea00` 上逐条核实）

> 仓库维护方在终点提交上逐条核对本报告。行号以**本地**为准。
> 记号：**✅ 成立** = 代码确认；**⚠️ 部分** = 现象真实但描述需修；**❌ 不成立**。

## A. 结论：5 条全部成立，其中 P1-1 是我上一轮的**实现错误**

| 报告项 | 复核 | 本地证据 | 备注 |
|---|---|---|---|
| **P1-1** Boss 身份取池子第一条 | **✅ 成立** | `boss_enemy_id(content, act)` 取 `encounter_pool(pool)` 的第一条；而 `pick_encounter` 在**开战时**才掷（`RunStream::Combat`，`run.rs:3789-3841`） | 本内容每幕三个等权 Boss ⇒ 三分之二的局里页面**预告错的 Boss**。旧判据（"三幕互不相同" + 写死 act1）**必然通过** —— 审阅这一点抓得很准 |
| **P1-2** `KNOWN_ABSENT` 仍含已导出的 `rd_run_over` | **✅ 成立** | `ui_state_check.py:60`；缺失判据是 `name not in have and name not in KNOWN_ABSENT` | 那一行从"待补项"变成了**豁免** ⇒ 误删导出时闸门仍然绿 |
| **P2-1** `noRun` 用 `i32::MIN` 当哨兵 | **✅ 成立** | `index.html` 的 `noRun: ex.rd_run_seed() === -2147483648`；`rd_run_start` 不拒绝该 seed | 数据域里的合法值兼作"无值" |
| **P2-2** `SC-02` 无条件兜底使 `SC-??` 不可达 | **✅ 成立** | `ui_panels.js` 的 `{ id: "SC-02", test: () => true }` | 新增 `Pending` 会静默落地图 |
| **P2-3** "唯一命中"是构造性质 | **✅ 成立** | 包装层给每条基础场景加 `!earlier.test(s)`，而 `scenesMatching` 检查的正是这个结果 | 报告的分寸把握得好：**不是设计错误**，是**测试结论不能升级** |

## B. 对报告"Courier 补货保留类型"一段的确认

报告明确写"上一轮建议**证据不足**、不应继续当作 P1"。这与 §342 的复核一致：StS1 的两份 wiki
只说"同一**类别**的商品"，且明说无色牌的**稀有度会重掷**；唯一说"卡以同类型回来"的是 **StS 2**
的攻略，而 StS 2 的补丁记录写着 2025-10 才修 "respects the rarity/type constraints"。
⇒ 维持"不做"，记在 `docs/sts-wiki-gap.md` 的"与 StS 2 的差异"。

## C. 处理（`§348`）

| 发现 | 修法 |
|---|---|
| P1-1 | `boss_enemy_id` 只回答 `last_encounter` **落在本幕 Boss 池里**的那一只；否则空串（"还不知道"）。ABI 三态分清：`-1` 没有局 / `0` 有局但还没打 Boss / `>0` 长度 |
| P1-2 | 删掉 `KNOWN_ABSENT` 那条；负控改成**删掉一个真导出**（而不是塞假名字） |
| P2-1 | 新增 `rd_run_exists()`；页面 `noRun` 改用它。判据里钉住"用 `i32::MIN` 开局仍然是**有局**" |
| P2-2 | 兜底要求 `pending === 0`；`SC-??` 给一份**显式**面板（写出那个待决值） |
| P2-3 | 不改代码；`ui-state-model.md` 新增 §7d，写清"这套夹具**没有**证明什么" |

### 顺带发现的两条（报告未提，但同源）

1. **`map_or(-1, ..)` 把"还不知道"报成"没有局"** —— 写 P1-1 的判据时当场抓到；
   三态必须分开。
2. **原版在进幕时就定 Boss，我们是开战才掷**（`docs/sts-wiki-gap.md` 新增"已知偏差"）。
   把"进幕即定"搬过来会改 RNG 消耗顺序（`corpus` / 存档 / 回放都对它敏感）⇒ 不在 UI 这轮动。

## D. 关于 P2-3 的自评

报告说"`scenesMatching` 检查的是已经互斥化的结果"，完全正确。补一句我这边的认识：
**包装层减少的是重复的否定条件，不是验证**。所以 §7d 明确列出"没证明什么"，
并把"从宿主采集真实快照"列为真做 3D 时的下一步（**不为临时 DOM 版做像素级回归**，与报告一致）。

## E. 证据来源

* 本仓库源码与 `docs/port-plan.md` §342–§348（本地核实，含 `cargo test` / 23 道闸门实跑）
* [StS1 The Merchant](https://slaythespire.wiki.gg/wiki/The_Merchant)（上一轮已引，本轮未新增外部结论）

> **一句话**：报告 5 条全部成立，P1-1 是我上一轮把"池子第一条"当成了"本局那只"，而旧判据
> 恰好**必然通过**；P1-2 是"豁免变成漏洞"的典型。四条已修并各自配负控，P2-3 记成证据边界。
