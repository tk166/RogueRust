# RogueRust 第八轮增量 Review：内核规范 / StS 1 Wiki / V2 UI 状态契约

**审查范围**：`094d34e3959047b7775844bcc6f3cfbeda4ad2a3` → `c448ff03df7fb0eb0e25617bd672d8022532906e`

**审查对象**：仓库终点提交的 `rd-run`、`rd-core`/`rd-wasm` 关键路径、商店和事件内容、`README.md`、`docs/sts-wiki-gap.md`、`docs/ui-state-model.md`、`native/ui_state_check.py`、`tools/acceptance.ps1`，以及该范围内若干具体提交的说明与补丁页面；对照**Slay the Spire 1** Wiki。

**证据范围**：针对性静态检查；未取得完整的本地 Git compare 补丁，未独立构建运行 Cargo、WASM 或浏览器门禁。以下“代码确认”指可直接核实实现逻辑；“待复现”表示尚无动态运行证据。不要把项目自报的闸门通过数视为本报告的独立复验。

## 0. 结论速览

**方向正确、但尚不能认为所有新增语义已正确对齐。** §308 的 `RunState` 字段覆盖门禁、§329 的 Boss 阶段语义补丁、§332 的完整商店货架、§334/336 的双层战斗哈希与回放检查，以及 §337 的事实 / 动画分离，均有实际工程价值。

当前发现的重点：

| 优先级 | 范围 | 问题 | 证据级别 |
|---|---|---|---|
| P1 | 商店 | 余额校验使用原价而扣款使用折后价 | 代码确认 |
| P1 | 商店 | Membership Card + The Courier 被错误地按 70% 折扣叠加（原版为 60%） | 代码确认 + Wiki |
| P1 | 商店 | 购买 Membership Card 时，计算扣款价发生在授予该遗物之后 | 代码确认，后果待定向复现 |
| P1 | 商店 | The Courier 的补货可能在已扣款后失败，返回 Err 却改变状态 | 代码确认，具体错误分支待构造 |
| P1 | 商店 | 新增无色 / 药水货架不受 Courier 补货；补货货价仍施加 A16 涨价 | 代码确认 + Wiki |
| P1 | 事件 | The Moai Head 漏掉 Golden Idol 作为出现的替代资格 | 代码确认 + Wiki |
| P1 | 事件 | Tomb of Lord Red Mask 只让已持有 Red Mask 的玩家出现，反向挡掉事件本身的获取途径 | 代码确认 + Wiki |
| P1 | UI 状态模型 | SC-03（战斗待开始）在 SC-03b（战斗中）之前；SC-02（地图）在 SC-02b（幕尽头）之前，按先匹配先胜出可能遮蔽后者 | 文档逻辑确认 |
| P1 | UI 状态模型 | §5 称 pending 是唯一场景判别式，与 §1/§3 战斗、场景判定矛盾 | 文档确认 |
| P2 | UI 门禁 | 只核实导出名与提及，不校验签名/类型/参数/哨兵/向量布局、场景优先级 | 检查器源码确认 |
| P2 | UI ABI 文档 | 将 `rd_run_observe_len` 放在“文本 `_len/_into` 对”清单内，尽管它不是文本；观察向量旧注释仍写 122，而表达式现为 148 | 文档、源码确认 |

## 1. 增量代码规范审查

### 1.1 折后价格检查与扣款不一致 — P1

**位置**：[`kernel/rd-run/src/state.rs#L5636-L5779`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/kernel/rd-run/src/state.rs#L5636-L5779)

`buy_card` / `buy_relic` / `buy_colorless` / `buy_potion` 都用 `self.gold < offer.price` 拒绝购买，成功后却使用 `shop_price(offer.price)` 扣钱。

**真实反例**：原价 100、持有 Membership Card、金币 60；应可用 50 金币购买，但会被判断为不足。

**建议**：购买前计算 `due = self.shop_price(offer.price)` 并统一用于余额检查、错误消息和扣款。将价格快照置于 `push_relic` 之前（见下一项）。四类商品均做 `gold = due-1` / `due` / `list_price-1` 的边界测试。

### 1.2 两件折扣遗物叠加公式错误，且测试已固化错误 — P1

**位置**：[`state.rs#L4541-L4557`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/kernel/rd-run/src/state.rs#L4541-L4557)；[`state.rs#L8717-L8727`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/kernel/rd-run/src/state.rs#L8717-L8727)

当前 `percent -= discount`：100 - 50 - 20 = 30，且测试直接期望 `shop_price(100)==30`。**StS 1 规则乘法叠加**：`100 * 0.5 * 0.8 = 40`；总折扣 60%。

**建议**：按原版规定的顺序/取整计算每一种折扣，测试不通过调用生产 `shop_price()` 生成预期值；使用字面量的 Wiki 案例（100→50、100→80、100→40），另测 99 等奇数价格。确认卡牌移除服务与 Smiling Mask 的特殊叠加顺序。

**来源**：
- [StS 1 The Merchant](https://slaythespire.wiki.gg/wiki/The_Merchant)
- [StS 1 Membership Card](https://slay-the-spire.fandom.com/wiki/Membership_Card)
- [StS 1 The Courier](https://slay-the-spire.fandom.com/wiki/The_Courier)

### 1.3 购买新折扣遗物时发生折扣回溯 — P1

**位置**：[`state.rs#L5685-L5717`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/kernel/rd-run/src/state.rs#L5685-L5717)

`buy_relic` 先 `push_relic(offer.id)`，再 `adjust_gold(-self.shop_price(offer.price))`。购买 Membership Card 时，价格计算会看到**已经入库的 Membership Card**。原版应由购买前拥有的遗物决定该次交易价格，新遗物应影响**后续**购买。

**建议**：先冻结本次 `due`，后授予遗物；在交易同一作用域中处理补货与回滚。测试第一次购买 Membership Card 的成交价与随后另一件商品的成交价。

### 1.4 Courier 补货阶段仍可能导致部分提交 — P1

**位置**：[`state.rs#L5671-L5681`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/kernel/rd-run/src/state.rs#L5671-L5681)、[`#L5708-L5718`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/kernel/rd-run/src/state.rs#L5708-L5718)、[`#L5056-L5130`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/kernel/rd-run/src/state.rs#L5056-L5130)

先给商品、扣钱、货架置空，然后 `restock_*()?`。补货函数仍存在 `pool_fits`、RNG、ID 解析等可能失败的路径，可能出现 `Err` 与状态已更改并存。

**建议**：选择最小完整事务：在 `RunState` 副本上购买 + 补货，通过后一次提交；或设计一个不会再失败的补货提交阶段。在非法池子、超容量池子、可注入 RNG 错误下断言 `Err` 与整状态恒等（含随机数状态）。这不要求全局通用事务框架。

### 1.5 先前正确的实践已在这轮继续强化

- `RunState` 每新增字段都加入归档与哈希清单，`native/check_state_fields.py` 作为第 22 道门禁，解决“正常测试状态全是默认值导致漏字段不红”的问题。不过本质上是**字段被点名**检查，不证明每个字段的编码/恢复语义正确。
- `hash_golden` 不动参考对拍语义，`hash_full` 用扩展文本纳入模型自有字段；§336 在 `fight_begin` 回放记录中对战斗初始化状态增加独立 hash 校验。旧脚本此字段为空则跳过，属于明确的兼容策略。
- §329 补了 Awakened One / Time Eater 的 debuff 清除及 Collector 在 Torch Head 伤亡后的再次召唤，分别对应战斗生命周期和 AI 权重的实际 Wiki 缺口；负控更强调行为而不仅是内容字面量。
- §332 新增无色牌、药水货架，并把商店价目与货架组合做了 Wiki 数值型对照。剩余缺口在购买事务与遗物联动，**不需要推倒商店的结构**。

相关提交：[§329](https://github.com/tk166/RogueRust/commit/7b32823a1ab888f58a542615aaaf1095174fbe3a)、[§332](https://github.com/tk166/RogueRust/commit/be34846e5e055afece4d04010fa244bfa3f473e1)、[§334/335](https://github.com/tk166/RogueRust/commit/bbeab812f6abd7d2ac6c71c1662a09cea0f019af)、[§336](https://github.com/tk166/RogueRust/commit/171817024c7296b6e7ef3f75680619883de1ed7f)。

## 2. 本轮新增功能与 StS 1 Wiki

### 2.1 The Courier 补货覆盖不完整 — P1

[`buy_colorless`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/kernel/rd-run/src/state.rs#L5720-L5752) 与 [`buy_potion`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/kernel/rd-run/src/state.rs#L5753-L5779) 只把货架 `price` 设为 `-1`，没有 Courier 补货分支。StS 1 Wiki 明确包含 cards、relics、potions，因此无色卡和药水不能作为例外。

补货 `restock_relic_slot` 仍用 `marked_up` 施加 A16 的额外涨价，但 StS 1 Merchant Wiki 特别说明 Courier **补货商品不受 A16 涨价影响**。另需验证 Shop Relic 不能再次补出，卡牌补货仍遵守货架类型约束。

来源：[The Merchant](https://slaythespire.wiki.gg/wiki/The_Merchant)、[The Courier](https://slaythespire.wiki.gg/wiki/Courier)。

### 2.2 The Moai Head 的事件出现条件缺少 OR — P1

**位置**：[`sts.roguedeck.json#L81061-L81069`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/tools/contentc/packages/sts/sts.roguedeck.json#L81061-L81069)

当前只接受 `health_percent <= 50`；Wiki 要求 `health <= 50% OR 持有 golden_idol`。满血 + Golden Idol 时错误地无法遇到此事件。

推荐四格表驱动测试：（低血/高血）×（有/无 Golden Idol）。若当前 `Requires` 是 AND，不应为这一个需求重写通用 DSL；优先寻找最小的任一条件表达方式。

来源：[The Moai Head](https://slaythespire.wiki.gg/wiki/The_Moai_Head)。

### 2.3 Tomb of Lord Red Mask 事件级资格写反 — P1

**位置**：[`sts.roguedeck.json#L81083-L81091`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/tools/contentc/packages/sts/sts.roguedeck.json#L81083-L81091)，[事件选项 `#L83845-L83893`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/tools/contentc/packages/sts/sts.roguedeck.json#L83845-L83893)

当前 `Events3` 要求玩家**已经拥有** `red_mask`，但原版未持有该遗物的玩家本来就可通过献出全部金币**获得** Red Mask。结果这一分支被事件级过滤直接屏蔽。

**进一步偏差**：当前 Offer all Gold 选项只检验金币，不检查是否已经持有 Red Mask，因而持有者也可能同时看到两种本应互斥的选项。应分开定义事件出现资格与事件内选项资格。

测试要检验无面具 / 有面具 × 金币 0 / >0 下的事件可达性与可用选项，不以与现有实现相同的错误假设为基准。§331 的原测试恰好把这个错误假设固化为“无面具时事件不可见”。

来源：[Tomb of Lord Red Mask](https://slay-the-spire.fandom.com/wiki/Tomb_of_Lord_Red_Mask)、[Events List](https://slaythespire.wiki.gg/wiki/Events_List)。

### 2.4 其他主要新增项的判断

| 功能 | 现状与判断 | 进一步验证 |
|---|---|---|
| A17/18/19 动作差异 | §328 先抽离 Wiki 里真需要分支的条目，补 Cultist/Fungi Beast/Fat Gremlin 等，方向合理 | 确认 Wiki 文本解析器覆盖多怪同页、模板条件，不仅检查名单相等 |
| Boss 相位 | §329 清 Debuff 与 Collector 有条件召唤属于真实改进 | 验证数值、行动时序、队列数和概率与原版逐项吻合 |
| N'loth | §331 抽取两件已持有遗物作为候选，与原版基本行为一致 | 验证候选等概率、失去哪件、特殊遗物处理 |
| 下一回合抽牌 / 能量 | §333 引入一次性状态并跨回合消耗，抽象边界合理 | 在轮次开始次序中验证增量应用一次且过期，不应只验证状态存在 |
| 商店铺货 | §332 2 攻 / 2 技 / 1 能力、2 无色、3 药水、3 遗物与删牌服务，整体接近 StS 1 | 优先修复折扣、补货、交易时序，再核对概率分布与取整 |

**注意**：终点 README 中 61 怪 / 64 遭遇 / 295 卡行 / 152 遗物 / 36 事件是内容规模，不等于对应条目已完整通过 Wiki 行为比对。对照以 StS **第一代** Wiki 为准，避免使用 StS 2 的商店数值。

## 3. `c448ff0`：`docs/ui-state-model.md` 及第 23 道门禁

**总体评价**：作为下一代 UI 的事实契约与渲染系统设计输入，这份文档**方向正确且值得保留**。优点是明确分开：

- 游戏权威事实（来自 Core / Run）与动画 Beat（只驱动演出）；
- 场景（scene）、层（layer）、字段（field）的职责；
- 字段来源、更新时机 T0–T4、空值哨兵、槽位编号；
- 尚未拥有底层事实来源的 G1/G9 等问题，主动标记而不是由 UI 悄悄推断。

但是**它现在不可以直接作为无歧义的场景状态机规格**，必须先修几个局部问题。

### 3.1 场景优先级可能把有效场景遮蔽 — P1

**位置**：[`ui-state-model.md#L64-L91`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/docs/ui-state-model.md#L64-L91)

文档明确规定从上到下首先命中者胜出，然而：

1. **SC-03“战斗未开始”位于 SC-03b“战斗中”之前**。战斗开始后 `pending==0`、`kind` 仍是战斗房间时，SC-03 的前提仍可能成立，抢先匹配，阻止 SC-03b 显示。这是一个很强的设计风险，应通过实际状态夹具验证。
2. **SC-02“地图”位于 SC-02b“幕尽头”之前**，前者是 `pending==0 && 上面均不成立` 的兜底，必然覆盖具有 `pending==0` 的 SC-02b。后者按当前声明的优先级不可达。
3. SC-00“未开局”最后才判定；虽然多数上层 API 可能返回哨兵，不应该依赖无会话 API 的偶然返回值才能正确展示开始界面。

**建议**：先把明确的强状态依次判定（无会话 / 正在战斗 / 胜负结算 / 具体 Pending / 预备战斗 / 幕尽头 / 地图兜底），场景条件尽量互斥；为每个 SC 建一份**真实或模拟观察向量**，断言 `classifyScene(snapshot)` 返回正确结果，并对未命中、多重命中情况报错。不要据此大改整个 UI 架构。

### 3.2 §5 的“pending 唯一判别式”与前文冲突 — P1（规格准确性）

**位置**：[`ui-state-model.md#L642-L647`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/docs/ui-state-model.md#L642-L647)

此处宣称 `pending` 是唯一场景判别式，但 §1 自己明确列出 `kind` / `unknownRoom` / `eventFight` / `mode` / `action_count` 等条件，且说明 `pending==0` 不等于地图。

建议改为“**pending 是优先级高的重要场景输入，但需要与 Fight/Terminal/Node 几种权威事实共同判定**”；不要允许未来 UI 代码生成器把这句话理解为仅按 `pending` switch。

### 3.3 第 23 道门禁合理，但只是“名称清单防腐”，不是 ABI 契约验证 — P2

**位置**：[`native/ui_state_check.py`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/native/ui_state_check.py)；[`tools/acceptance.ps1#L287-L298`](https://github.com/tk166/RogueRust/blob/c448ff03df7fb0eb0e25617bd672d8022532906e/tools/acceptance.ps1#L287-L298)

可肯定之处：从 Rust 导出扫描名称，同时防止“文档引用不存在”和“导出未登记”；考虑 `unsafe extern`；排除 §6 未来 API 建议；对白名单写理由；用两个负控证明探测器不是永远报绿。

能力边界：

- 不检查 ABI 参数、返回值、指针单位、长度单位、哨兵值、缓存失效时机；
- 不检查文档的字段→导出映射是否**在正确的表格行**，只要导出名字在某处出现就算登记；
- 不检查场景谓词、优先级、可达性；
- 文档 §8 将 `rd_run_observe_len` 错放到“文本 `_len/_into` 对”清单中；检验名称无法发现这种**类型语义错配**。

建议保留现有门禁作为快速静态清单门禁，随后增加一个很小的**类型化 ABI manifest**（只覆盖下一代 UI 实际消费的关键接口），如 `name / arg-types / result-type / semantics / length-unit / sentinel / scene`。用 `wasm` 的真实导出 / 最小 JS-WASM 交互夹具核验，至少包括 `rd_env_observe_len` 的实际长度、`observe` 偏移、两条最常用字符串 `_len/_into` 的字节数，以及 SC-00 / SC-03 / SC-03b / SC-02b。

不要把所有 218 个导出都做成庞大的强类型协议生成系统。先覆盖关键 UI 契约，成熟后再扩展。

### 3.4 G1 / G9 / G11 的优先级判断正确 — 建议保持

- G1：“游戏已经结束”只在页面保存 `runOver`，应尽可能由底层提供权威可查询的终局状态。
- G9：Rest 可恢复多少生命值不应让 UI 自己写固定的 30% 公式；应由内核直接返回当前可执行动作和预期值（需考虑 Mark of the Bloom / Regal Pillow 等）。
- G11：存在 Destroyed beat 但页面无法识别，导致演出丢失；这属于表示层事件协议缺口，可以局部扩展常量与映射。

**建议先修 G1/G9/G11 与场景优先级，不必提前开发完整 3D/Live2D 动画框架。**

### 3.5 观察向量长度的文档细节 — P2

`rd-wasm/src/lib.rs` 由表达式计算 `12 + 5 + 6*8 + 6*5 + 10*4 + 5 + 8 = 148`，当前 `ui-state-model.md` 的 148 口径是对的。但 `lib.rs` 顶部旧注释还写着四个敌人槽 / 122，文档 §8 的 `_len` 表又把非文本长度混入文本类目。建议把真实 `rd_env_observe_len()` 当成唯一权威长度，通过运行时检查关联视图缓冲区；顺手清除过期注释。

## 4. 推荐下轮执行清单

| 顺序 | 最小工作包 | 不可缺少的验收 |
|---|---|---|
| 1 | 商店购买逻辑修复 | 实付价作为余额校验基准；第一次买 Membership Card 不自打折；双折扣 100→40；事务失败不部分提交 |
| 2 | Courier 规则闭环 | 有色卡、无色卡、药水、遗物各自补货；补货 A16 / Shop Relic 规则明确 |
| 3 | 事件资格改正 | Moai 2×2 表；Tomb 两种持有情况与选项互斥，独立 Wiki 断言 |
| 4 | UI 场景分类表纠正 | SC-00、SC-03b、SC-02b 不被遮蔽，所有声明场景可达 |
| 5 | 门禁从名称进阶到最小语义检查 | 核验关键 ABI 类型、长度单位、哨兵、典型转场 |
| 暂缓 | V2 内核重构、跨平台统一、像素级全覆盖 | 不阻塞 WASM 内容和 UI 原型 |

## 5. 建议沉淀的 Agent 规范

1. **原版事实必须独立于实现生成预期**：尤其是折扣叠加、事件资格和概率；负控应能让错误公式失败，而不只是让同一公式的字符串变化失败。
2. **每扩展一种同类货架 / 房间 / 状态，检查所有同类遗物和 ABI**：新货架需要继承 Courier、Membership Card、A16、满容量拒绝和失败原子性，不只是添加一个 `buy_*`。
3. **先冻结交易快照，再产生交易副作用**：价格、行动合法性和库存来自进入交易前的同一状态；提交不应重新计算改变后的价格。
4. **状态模型表要有可执行的反例**：一个场景谓词的正确性不能用“表里列了 19 行”证明；需要至少 19 组实际 snapshot / predicate fixtures。
5. **门禁应声明检测能力上限**：名字存在 != ABI 兼容；测试引用 ID != 验证行为；Wiki 页面存在 != 行为对齐。

---

### 复核边界

本报告基于指定终点版本的重点源码、部分中间提交记录以及 StS 1 Wiki 的静态对照。没有独立执行构建和测试，且未取得完整 Git compare 补丁，因此不能声称审计了范围内每一行代码；也不会把未构造的错误分支说成已发生的玩家故障。上述 P1 适合作为下轮 Agent 的**定向复现与最小修复列表**，不构成启动全面重构的理由。

---

# 附：本地复核意见（逐条核实，`c448ff0` 上）

> 由仓库维护方在终点提交上**逐条核对本报告**。报告自己声明"未独立构建运行"，这一节补的正是
> 代码级定位与两个独立来源的对照。**GitHub 行号与本地略有偏移**（本地 `state.rs` 的 `buy_*`
> 在 5855–6010），下表的行号以**本地**为准。
>
> 记号：**✅ 成立** = 代码确认 + （涉及规则时）两个独立来源一致；**⚠️ 部分** = 现象真实但触发条件
> 报告未说清；**❌ 不成立** = 复核后否定。

## A. 结论：8 条 P1 全部成立，其中两条后果比报告描述更重

| 报告项 | 复核 | 本地证据 | 备注 |
|---|---|---|---|
| 1.1 余额校验用原价、扣款用折后价 | **✅ 成立，且更重** | `state.rs:5874` `if self.gold < offer.price`；`state.rs:5890` `adjust_gold(-self.shop_price(offer.price))`（`buy_relic`/`buy_colorless`/`buy_potion` 同形：5920/5956/5989） | 见 B2：后果不是"少买一次"，而是**活按钮被拒 + 错误消息里的数与屏幕上的数不同** |
| 1.2 双折扣加法（30）应为乘法（40） | **✅ 成立** | `state.rs:4730-4740` `percent -= discount`；`state.rs:9082` `assert_eq!(shop_price(100), 30, "the two discounts add up (50 + 20)")` —— **测试把错公式固化了** | 两源：wiki "0.5 * 0.8 = 0.4 → 40%"[M] / fandom "0.5 X 0.8 = 0.4"[F] |
| 1.3 买 Membership Card 时给自己打折 | **✅ 成立** | `buy_relic`: `push_relic(offer.id)?`（5917）**先于** `shop_price`（5918） | wiki 原文是 "**the rest of** the items in the same Shop … will benefit"[M]，即自身不享受 |
| 1.4 补货失败时已扣款 | **⚠️ 成立但触发不到** | `buy_card` 末尾 `restock_card_slot(slot, card_pool)?`（5898）；`restock_card_slot` 的失败路径 = `pool_fits` / `rng.roll` / `RunId::new`（`state.rs:5252-5299`） | 真实内容里三条都不触发（池子 < `MAX_POOL`、RNG 计数器不溢出、id 由内容门保证）。**纪律违反是真的，严重度应降**：`RunState` 是 `Copy`，修法 3 行 |
| 2.1a 无色 / 药水不补货 | **✅ 成立** | `buy_colorless`（5939-5973）、`buy_potion`（5976-6003）**没有** Courier 分支；只有 `buy_card`/`buy_relic` 有 | fandom: "The Colorless cards may be replaced by a colorless card of a different rarity"[F] |
| 2.1b 补货仍施加 A16 涨价 | **✅ 成立** | `restock_relic_slot` → `price: self.marked_up(price)`（`state.rs:5326`） | wiki: "**Any item re-stocked** by The Courier will not be affected by the 10% price increased 16"[C] |
| 2.2 Moai Head 缺 `OR golden_idol` | **✅ 成立** | 内容 `EventTables.Events3` 的 `the_moai_head` 只有 `health_percent at_most 50` | wiki: "either has Golden Idol, **or** their HP is at or below 50%"[M]；2×2 表见 slayspiredb[D] |
| 2.3 Tomb of Lord Red Mask 资格写反 | **✅ 成立，且更重** | 事件级 `Requires: relic has red_mask` ⇒ 无面具玩家**永不可见**，而这条是 wiki 里唯一的"获得 Red Mask"途径之一 | 另外：选项 `Offer all Gold` 只查 `gold at_least 1`、不查"没有面具" ⇒ 持有者可刷第二个 `red_mask` |
| 3.1 场景优先级会遮蔽 | **✅ 成立** | `ui-state-model.md` §1 表：SC-03 在 SC-03b 前（"未开始"是**页面态**、无内核判据）；SC-02 是"兜底"却排在 SC-02b 前 ⇒ SC-02b 不可达 | 见 C3：根因是"有没有一场正在打的战斗"**没有内核判据** |
| 3.2 §5 与 §1 矛盾 | **✅ 成立** | §5 写"`pending` 是唯一的场景判别式"，§1 自己列了 `kind`/`unknownRoom`/`eventFight` | 措辞问题，但要改（会被未来的代码生成器当真） |
| 3.3 门禁只是名字清单 | **✅ 边界描述准确** | `native/ui_state_check.py` 只做名字双向对账 | 我们本来就只声称这一点；但它挡不住"名字对、语义错"（如 §8 的分类错位），见 3.5 |
| 3.5 `122` 旧注释 + §8 分类错位 | **✅ 成立** | `lib.rs:157` 与 `lib.rs:1630` 仍写 "= 122"（表达式已是 148）；§8.1/8.2 把 `rd_run_observe_len`/`rd_env_observe_len`/`rd_env_pile_len` 放进了"文本 `_len/_into`"表 | 分类错位是真实的：**非文本长度混进文本类目** |

## B. 报告未提、但同类的三处（复核时发现）

### B1. 取整方向：Membership Card 是**向上**取整，我们截断

wiki 原文：*"For prices which are an odd number before purchasing Membership Card, the new price will
round up … (`101 * 0.5 = 50.5` which then rounds up to cost 51 Gold instead of the expected 50)"*[M]。
我们 `(base * percent / 100)` 是**截断**（`101 → 50`）。

⇒ **只改乘法、不改取整，奇数价仍然错**。修法：把折扣算成有理数（分子/分母各自相乘），最后
`ceil` 一次 —— 这同时钉住 wiki 那句 `0.5 * 0.8 = 0.4`（一次性 40%，而不是先 50% 再 20% 各取整一次；
两种顺序在 `107` 上会差 1：`ceil(ceil(107*0.5)*0.8)=44` vs `ceil(107*0.4)=43`）。

### B2. 1.1 的真实后果：**活按钮被拒**，而且错误消息里的数与屏幕上的数不同

`rd_run_shop_card_price` 走的就是 `shop_price`（`run.rs:1664` 的 §270 注释明说"显示价 = 折扣价"），
而 `buy_*` 的余额校验用的是**挂牌价**。于是持有 Membership Card、金币 60、货架 100 时：

* 页面按 50 判断"买得起"⇒ **按钮是启用的**；
* 点下去被拒，回一句 `NotEnoughGold { price: 100, gold: 60 }`。

这不是"少买一次"，是**屏幕上写着 50、内核说 100 不够** —— 本项目最恨的那种"显示一个数、内核用另一个数"。
修 1.1 的判据因此必须包含一条：**页面显示价 == 扣款价**（同一个函数、同一个值）。

### B3. removal 的叠加规则**两源冲突**，不建议照单全收

* fandom：*"This stacks multiplicatively with Membership Card (for a combined 60% discount), **except
  for card removal (which takes the better discount)**"*[F]
* wiki.gg：*"The Courier's price reduction will still reduce the price of the card removal service
  **as normal**"*[C]

两条互斥（"更好的那一个"= 50%，"正常"= 40%）。**单源不足以定规则**，所以本次只把乘法与取整统一，
removal 的"取更好的折扣"**记成待核偏差**，不凭一条 fandom 改行为。

## C. 对报告"待验证"项的结论（不是缺陷）

1. **"Shop Relic 会不会被补出来"——我们已经是对的**：`restock_relic_slot` 走
   `pick_relic_avoiding`（`allow_shop = false`），而 wiki 正好规定 *"The Courier will not replace it
   with another Shop relic and instead replace it with a random Common, Uncommon, or Rare relic"*[C]。
2. **§331 那两个测试固化了错假设**（报告说对了，且这是本次最该改的一处）：
   `content.rs:6274` 断言 "above 50% the Moai Head must not appear"，`content.rs:6282-6285` 断言
   "without the Red Mask the tomb is not in the pool at all"。**它们不是"测试覆盖了错误行为"，
   是"测试把错误行为写成了规范"** —— 修内容时必须先重写它们，否则修完反而红。
3. **3.1 的根因是缺一个内核判据**（新缺口，本报告未列）：`rd_env_done()` 在**没有会话时返回 1**
   （`lib.rs:2172` `Err(_) => 1`），`rd_run_pending()` 在"战斗前"与"战斗中"都是 `0`，
   `rd_run_node_resolved()` 战斗中仍是 false。今天唯一能用的间接判据是
   `rd_env_beat_count() >= 0`（无会话返回 `-1`）。⇒ 建议补 `rd_run_in_fight()`（`0/1`），
   场景表才能变成纯函数。已作为 **G16** 记入 `docs/ui-state-model.md` §6。
4. **2.4 那几行是"待验证"而非缺陷**：我们的 `docs/coverage-matrix.md` 本来就按实体声明
   `Implemented / TestNamed / HarnessOnly / SourceTie / DeclaredDeviation / Evidence`，报告
   "内容规模 ≠ 行为已对齐"的提醒与该表的语义一致，无需新增机制。

## D. 修复顺序（本次按此执行）

| 顺序 | 工作包 | 不可缺少的判据 |
|---|---|---|
| 1 | 四类 `buy_*` 统一 `due = shop_price(挂牌价)`，用于**校验 + 错误消息 + 扣款**；`due` 在 `push_*` **之前**冻结 | `gold = due-1 / due / list-1` 三档 × 四类；**显示价 == 扣款价**；首次买 Membership Card 不打折 |
| 2 | `shop_price` 改**乘法 + 一次向上取整** | 字面量断言 `100→50`、`100→80`、`100→40`、`101→51`、`107→43`；**不许**用生产函数生成预期值 |
| 3 | 事件资格：`Requires` 是 **AND-only**（`run_expr.rs:137` 明文），加 `RequiresAny`（第二串原子、组内 OR），整体 = `AND(Requires) && OR(RequiresAny)` | Moai 2×2（低血/高血 × 有/无 Idol）；Tomb 4 格（有/无面具 × 金币 0/>0）+ 选项互斥 |
| 4 | 重写 §331 的两个测试（先改测试再改内容，否则修完反而红） | "无面具时事件**可见**且 `Offer` 可用" |
| 5 | Courier 补货闭环：无色/药水补货 + 补货**不**施加 A16 + 失败不部分提交 | 四排各测一次补货；注入超容量池断言整状态相等（`RunState: Copy`） |
| 6 | UI 文档：场景表重排（无会话 → 战斗中 → 终局 → `pending` → 预备战斗 → 幕尽头 → 地图兜底）、§5 改措辞、§8 移出非文本长度、清 `122` 注释、补 **G16** | 19 个场景各一份 snapshot 夹具，断言 `classifyScene` **唯一命中**；多重命中/未命中都要报错 |

## E. 证据来源

* [M] <https://slaythespire.wiki.gg/wiki/The_Moai_Head>、<https://slaythespire.wiki.gg/wiki/Membership_Card>、
  <https://slaythespire.wiki.gg/wiki/The_Merchant>
* [C] <https://slaythespire.wiki.gg/wiki/The_Courier>
* [F] <https://slay-the-spire.fandom.com/wiki/Membership_Card>、
  <https://slay-the-spire.fandom.com/wiki/Merchant>、<https://slay-the-spire.fandom.com/wiki/Tomb_of_Lord_Red_Mask>
* [D] <https://slayspiredb.com/guides/slay-the-spire-event-requirements-act-lists-and-curse-events>

> **一句话**：报告的 P1 全部成立，没有一条是误读；它把严重度估**低**的两处（1.1 的可见后果、2.3 的
> 测试固化）与它漏掉的取整方向，已在 B1/B2 与 C2 补上。修复按 D 的顺序走。
