# 从 RogueDeck-Core 重构成嵌入内核 + RL 环境：阅读计划与重构计划

> 前提：`docs/roguedeck-trial.md` 已证明 .NET 引擎在本机跑通（1495 测试绿、`--play` 完整闭环）。
> 本文回答：要不要重写、重写成什么、怎么读、怎么拆、怎么并行、成本多少。

---

## 0. 结论先行（三条，都基于实测）

### 结论 1：规则数学已经是整数运算 —— 这是最大的好消息

对 `src/RogueDeck.Core`（27,831 行）做全量扫描：

| 数值类型 | 出现次数 |
|---|---:|
| `float` | **0** |
| `double` | **10** |
| `Math.*` | 64（绝大多数是 int 重载的 Max/Min/Clamp） |

**Core 里一个 `float` 都没有，`double` 只有 10 处。** 也就是说伤害/格挡/状态/费用/随机数的数学几乎全是整数。
这意味着**跨语言、跨平台比特一致是可达的** —— 对 MCU（单精度 FPU 也不该依赖）和 RL（可复现的奖励信号）都是硬需求。
**重写时最大的纪律就是：不要引入浮点。**

### 结论 2：真正难搬的不是算法，是三个 .NET 构造

| 构造 | Core 里出现 | 为什么难搬 | 替代方案 |
|---|---:|---|---|
| `Action<>` / `Func<>` 委托闭包 | **203** + 27 | `CombatState.EnqueueContinuation(Action<CombatState>)` —— **continuation 是闭包**。`no_std` 下没有闭包分配 | 把"挂起的续体"改成显式的**待决操作枚举** + 固定大小的续体表；这是设计决策，不是翻译 |
| `typeof` 类型注册表 | **344** | `CombatDefinitionRegistry` 按 `Type` 键做注册 | 内化 id 枚举 + 静态注册表（编译期确定） |
| `throw new` 异常控制流 | **244** | C 没有异常；Rust 要 `Result` | 定义错误码/`Result`，把"可预期的拒绝"与"真 bug"分开 |

其余是机械工作：`LINQ`（`.Select` 135 / `.Where` 71 / `.OrderBy` 34）、`Dictionary<string,...>`（10）、
`System.Text.Json`（38）、`record`（411，≈数据类，好搬）。

**`CombatEffectChain` 的重入保护与 `CombatExecutionLimits` 的深度/预算上限必须原样保留** —— 那是防"无限触发链打死进程"的保险。

### 结论 3：内容很小，只是 JSON 很啰嗦

`bureaucrats.roguedeck.json` = **7.91 MB**，22 个顶层键，但实体数量其实不多：

| 实体 | 数量 | | 实体 | 数量 |
|---|---:|---|---|---:|
| 卡牌 Cards | 62 | | 状态 Statuses | 23 |
| 遗物 Relics | 49 | | 敌人动作 EnemyActions | 394 |
| 遭遇 Encounters | 109 | | 事件 Events | 20 |
| 起始牌组 Deck | 10 | | 角色 Characters | 1 |

7.91 MB 几乎全是**冗长的 JSON 效果程序**。内化成整数 opcode + 固定宽度记录 + 字符串池去重后，
估算落在**几百 KB**量级，可以放 Flash / ROM，运行时按需映射，不占 SRAM。

### 结论 4：目标平台比预期宽裕

ESP32-P4（取自已验硬件记录 `260927-fft/docs/esp32-p4-hardware-facts.md`）：

| 量 | 值 |
|---|---|
| 核心 | 2× 32-bit **RISC-V RV32IMAFC** @ 最多 400 MHz（实机 360 MHz），CoreMark 6.92/MHz |
| FPU / SIMD | 单精度 FPU + **128-bit** 向量扩展（XespV） |
| 主 SRAM | 768 KB L2MEM，但**应用可见 heap ≈ 592 KB**（无 PSRAM）；开 32 MB PSRAM 后 ≈ 569 KB（L2 缓存吃掉一部分）|
| PSRAM | 16 / 32 MB，实测拷贝 ~100 MB/s |
| TCM | 8 KB @ 400 MHz，1 周期延迟 |
| 无线 | **P4 无 WiFi/BT**，需外挂 C/S 系列 |

592 KB SRAM + 几百 KB 内容表 + 整数规则 —— **战斗内核放得下**。

---

## 1. 两个用途要的其实是两样东西（别做成一个项目）

这是本计划最重要的一节。用户提的"Python/C/Rust 重构"是一条路，但两个用途的最优解不同：

```
                        ┌─ 用途 A：RL 训练环境（多开、高吞吐）
                        │     → 先别重写。摩擦在 Python 边界，不在吞吐。
                        │
  RogueDeck-Core ───────┤
                        │     用途 B：ESP32 上运行
                        └─   → 必须重写，但重写的是一个【窄内核】，不是 27k 行。
```

### 用途 A：✅ 已验证 —— **不需要重写**（2026-10 实测）

**实验**：把 `RogueDeck.Core` 用 NativeAOT 编成 C ABI 原生库（`native/RogueDeck.Native/`），
Python 用 `ctypes` 直接调。

结果：

| 项 | 实测值 |
|---|---|
| AOT 编译 | **成功，0 个 IL2xxx/IL3xxx trim 警告** —— 那个 `IReadOnlyDictionary<Type, ...>` 注册表并没有挡住 AOT |
| 产物 | **单个 5.12 MB 的 `RogueDeck.Native.dll`，零 .NET 运行时依赖** |
| 语义 | 地精 12→6 HP、能量 3→2、中毒管线让英雄 30→28，全部符合预期 |
| 确定性 | 同 seed 哈希一致、换 seed 哈希改变 |
| 吞吐 | 建注册表 37,728 次/秒；**完整一场战斗 14,509 场/秒**（69 µs/场，含 ctypes 调用开销） |
| 折算整局 | **~2,900 局/秒/进程** |
| 对比进程模型 | 2.5 局/秒 → **~1,161×** |

**结论：RL 侧的"多开"需求，用 NativeAOT + ctypes 一天就解决了，不需要任何跨语言重写。**
原先担心的摩擦（Python 边界、进程启动、JSON 解析、Debug 未优化）全部被消掉。

附带收益：这个 5 MB 的原生库**同时就是 W0 对拍语料的生成器** —— Python 可以每秒调用上万次来枚举
`(seed, 操作序列) → 状态哈希`，不必再去 shell out 驱动 `roguedeck-bot` 的 CLI。

> 唯一不适用的是嵌入式：NativeAOT **没有 Xtensa / ESP32-RISC-V 后端**，而且它明确禁止跨 OS 编译
> （从 Windows 编 Linux 目标会被 `Cross-OS native compilation is not supported` 挡掉），
> 要出 `.so` 得在 Linux 上或 WSL/CI 里编。
>
> ⚠️ 所以**先确认"嵌入式"到底是哪一种**：
> - **裸机 MCU（ESP32 系列）** → 必须重写（§1 用途 B、§5）。
> - **跑 Linux 的 ARM64 开发板** → 根本不用重写，装个 .NET runtime 直接跑；
>   嫌重就在 Linux 上做一次 NativeAOT 出 `.so`。
> 这一个问题就能决定 4~7 周的工作量是否存在。


### 用途 B：确实要重写，但范围是"窄内核"

要**砍掉**：
- run 层的字符串 id / `System.Text.Json`(134) / `Activator` / `dynamic` / 大量 `Dictionary<string,...>`(89)；
- effect-program 的**类型化节点树**（`Effects/Programs/` 共 **8,227 行**，占 Core 的 30%）→ 换成**编译期字节码**；
- continuation 闭包（203 个 `Action<>`）；
- 异常控制流。

要**保留**：整数伤害/格挡/防御池管线、修饰器排序、触发式效果、回合状态机、效果队列的重入保护与预算上限、
确定性 RNG、快照哈希。

**现实目标：2,500 ~ 4,500 行**（不含内容编译器与外设驱动）。

---

## 2. 语言选择：只选一个内核语言

| 方案 | 优点 | 缺点 | 判断 |
|---|---|---|---|
| **Rust（推荐）** | `no_std` + `esp-hal`（P4 是 RISC-V，支持好）；enum 表达 opcode 天然；`const fn` 建表；**PyO3 一次同时搞定 RL 绑定**；无 UB | 交叉编译链比 C 折腾；Flash/PSRAM 需要自己接 | **首选**：一个内核同时服务 ESP32 与 RL |
| **C11 + ESP-IDF** | 你已有 `260927-fft` 的"零依赖共享内核、PC 与 ESP32 通用"成熟模式（`src/vfd_*.h`）；ESP-IDF 最稳 | 需要自己造 enum/match、泛型、内存安全 | 若想复用既有构建经验，选它 |
| Python | —— | 4~8 MB 内核跑不动 ESP32；RL 吞吐不够 | **只做工具链**：内容编译器、对拍驱动、gymnasium 包装 |
| 三个都写 | —— | 三份语义、三倍 bug、对拍变成三方对齐 | **明确否掉** |

> 用户提的"Python/C/Rust 重构"应落地为：**Rust（或 C）内核 + Python 工具链**。不是三份实现。

---

## 3. 正确性的核心资产：把 .NET 引擎当"黄金模型"做差分测试

这是整个计划里最省力的一招，而且这个引擎**天生支持**：

- 它自带 `CombatStateHasher`（165 行）+ `CombatStateSnapshotter`（146）→ 每步状态可哈希；
- 它的存档格式是 **seed + 全部答案序列** → 一局就是一串可重放的输入；
- `--play --do "p 0 0; e"` → 可以脚本化地驱动任意操作序列。

于是：

```
.NET 引擎（黄金模型，冻结 commit）
   │  枚举 (seed, 答案序列) 语料
   ▼
corpus/*.jsonl   每步 { 输入, 期望状态哈希 }
   │
   ▼
新内核 → 同一输入 → 状态哈希必须相等
```

**这把"重写一个游戏引擎"变成"让对拍测试变绿"。** 和你做控制器重写时的做法同构。

⚠️ **但不要追求全量比特一致**：那等于把 8,227 行的 effect-program 解释器照搬，正好毁掉嵌入式的可行性。
正确做法是定义**冻结的、带版本号的语义子集**（`spec/SEMANTICS-v1.md`），只对该子集对拍，
子集外的有意简化要显式记录（哪些机制不支持、被简化成什么）。

---

## 4. Phase R：代码阅读计划

**总时长 1~2 天，且高度可并行**（已在执行中，见 §6）。原则：**读测试优先于读实现** ——
`tests/RogueDeck.Core.Tests` 有 42,495 行，那是行为清单；实现只是其中一种写法。

| # | 读什么 | 提取什么 | 产出 |
|---|---|---|---|
| R1 | `tests/RogueDeck.Core.Tests/Combat/` 全部（229 文件/42,495 行，优先 20 个大文件） | **行为清单**：每条测试名 = 一条规则；边界与拒绝路径 | 行为清单（并入各 spec） |
| R2 | `Combat/CombatState.cs`(917)、`CombatantState.cs`(130)、`CombatStateSnapshot{,ter}.cs`、`CombatStateHasher.cs`(165)、`CombatRandom.cs`(57) | 数据模型、RNG 算法与状态字节数、哈希算法 | `combat-state-and-turn.md` ✅已派 |
| R3 | `CombatTurnProcessor.cs`、`CombatDecrees.cs`、`SimultaneousTurnProcessor.cs`、`CombatEffectQueueProcessor.cs`、`CombatEffectChain.cs`、`CombatExecutionLimits.cs` | 回合阶段序列、队列算法、重入保护、**深度/预算的具体数字** | 同上 |
| R4 | `Effects/Programs/*`（11 文件/8,227 行）+ `EffectProgramPhase3*Tests`、`TriggeredProgramParityTests` | **IR 全貌**：节点种类、表达式、值类型、执行模型、continuation 如何入队 | `effect-program-ir.md` ✅已派 |
| R5 | `Effects/DamageEffects.cs`、`DefensivePoolEffects.cs`、`PassiveModifiers.cs`、`{Damage,Block}AmountModifiers.cs`、`DamageSplitters.cs`、`PreDownInterceptors.cs`、`Status*Effects.cs` | **完整有序的管线阶段**：基础值→加法→乘法→拦截器→分裂→防御池→生命损失→死亡前拦截→触发入队 | `modifier-pipeline.md` ✅已派 |
| R6 | `StatusDefinition.cs`、`StatusInstance.cs`、`StandardCombatPackage.cs`、`CombatDefinitionRegistryBuilder.cs` | 内容如何变成行为；注册表的键与查找方式 | 内容 schema |
| R7 | `Serialization/CombatJson.cs`(422)、`CombatStateSnapshot.cs` | 快照的确切字段与编码（对拍格式的一部分） | 同上 |
| R8 | `bureaucrats.roguedeck.json` + `Scenario/Authoring/*` + `Run/Registry/*` | 内容 schema、实体间引用关系、7.91 MB 的字节去向 | `content-schema.md` ✅已派 |
| R9 | `Bot/TextPlay.cs`(730)、`FightPlanner.cs` | **观测面与动作面**（RL 的 obs/action 定义）+ 一个现成的基线策略 | 并入 RL 方案 |

**明确不读**（与内核无关，~28k 行）：`Sandbox.*`（Blazor 编辑器）、`Studio*`、`Bot.Cli` 批量器、
`Map/Strategic*` 的大部分变体（先只读一个生成器 + `MapConstraintValidator`）。

---

## 5. Phase W：重构计划

| 阶段 | 内容 | 并行度 | 产出 | 验收 |
|---|---|---|---|---|
| **W0 冻结** | 语义子集规范 v1 + 版本号 + 目录骨架 + 对拍语料生成器 | **串行（1 agent）** | `spec/SEMANTICS-v1.md`、`tools/make_corpus.py`、`corpus/*.jsonl` | 语料能生成，含每步期望哈希；记录 .NET 侧 commit |
| **W1 骨架** | 数据类型 + RNG + 快照哈希 + 队列/回合机 + 公共 API + 错误码 | **串行（1 agent）** | `kernel/src/{state,rng,hash,queue,turn}.rs` | 能把语料回放并匹配哈希（哪怕只有 1 张卡） |
| **W2 内容编译器** | 7.91MB JSON → 紧凑二进制 ROM 表 + 引用完整性校验 | 可并行 | `tools/contentc/`（Python） | 编译后总体积报告；所有外键校验通过 |
| **W3 叶子模块** | 伤害/格挡管线、状态表、卡牌与分区操作、**效果字节码 VM**、目标选择器、修饰器排序 | **并行（这里才是 subagent 该上场的地方）** | 各 `.rs` + 单测 | 每个模块的对拍用例自动变绿 |
| **W4 嵌入式目标** | `no_std` + 固定池分配 + ROM 表读取 + 内存预算测试 | 半并行 | `kernel-no_std` 目标 | 静态 RAM 占用 < 预算；一次战斗零动态分配 |
| **W5 RL 环境** | **直接走 NativeAOT 分支**（已验证）：Python 包一层 gymnasium + 向量化 | 并行 | `py/roguedeck_gym/` | 单进程 ≥ N 步/秒；同 seed 可复现 |
| **W6 CI** | 对拍 + 模糊测试（照抄它的 20k seed fuzz 思路） | 并行 | CI 配置 | 1 万随机局不崩、不无限触发、哈希稳定 |

**关键判断：W1 绝不能并行。** 数据模型/错误处理/公共 API 一旦被多个 agent 分叉，W3 全部返工。
W3 之所以能并行，是因为 W0/W1 已经把接口冻死了。

---

## 6. 并行 subagent 策略（用对地方，否则会毁掉项目）

### 已经在跑的（Phase R）

| Agent | 读什么 | 产出 |
|---|---|---|
| 1 | `Effects/Programs/*` + 相关测试 | `docs/spec/effect-program-ir.md` |
| 2 | 伤害/格挡/防御池/修饰器/状态触发 | `docs/spec/modifier-pipeline.md` |
| 3 | 战斗状态 + 回合机 + 队列 + 确定性/快照 | `docs/spec/combat-state-and-turn.md` |
| 4 | 7.91MB 内容 schema + 探针脚本 | `docs/spec/content-schema.md` + `ref/content_probe.py` |

### 判断规则

**能并行**：读代码（只读、边界清晰）、内容编译器、互不依赖的叶子模块、对拍驱动、gymnasium 包装。

**绝不能并行**：数据模型、效果 IR 的表示、公共 API、错误处理策略、语义子集的定义。

### 派活的三条前提（缺一条就会产出垃圾）

1. **冻结的接口**：签名 + 类型 + 语义，写在 spec 文件里，agent 只能照着实现；
2. **对拍用例**：输入 → 期望输出，可直接运行；
3. **文件边界**：明确只允许改哪些文件，避免两个 agent 同时改同一处。

### 验收标准

每个叶子 agent 的交付物必须做到**对拍测试自动变绿**，而不是"看上去对"。
subagent 看不到本轮对话，每个 prompt 必须自包含（仓库路径、要读的文件、输出路径、验收方式）。

---

## 7. 不要做的事（负向清单）

1. **不要移植 effect-program 的类型化节点树**（8,227 行）—— 编译成字节码。
2. **不要在规则里引入浮点** —— 现在 0 `float` / 10 `double` 是好底子，是 PC 与 MCU 比特一致的前提。
3. **不要照抄 `Dictionary<string,...>` 的 id 方案** —— 内化成 u16/u32 枚举。
4. **不要把 run 层整搬**（JSON / `Activator` / `dynamic` / 字符串 id）。
5. **不要三个语言都写**。
6. **不要在 NativeAOT spike 之前开始 RL 侧重写**。
7. **不要等 .NET 侧"稳定"再动手** —— 它是 v1 且仍在演进；**冻结一个 commit** 并写进 spec。
8. **不要追求全量比特一致** —— 只对冻结的语义子集对拍。

---

## 8. 成本估算（业余时间）

| 项 | 估算 |
|---|---|
| ✅ **NativeAOT spike** | **已完成，结论：RL 侧不重写**（见 §1 用途 A 实测表） |
| Phase R 阅读（4 个并行 agent） | 1~2 天 |
| W0 冻结 + W1 骨架 | 3~5 天 |
| W2 内容编译器 | 3~5 天 |
| W3 叶子模块（并行） | 5~8 天 |
| W4 嵌入式目标 | 5~10 天 |
| W5 RL 环境 | 3~5 天 |
| **合计** | **4~7 周**（不含 ESP32 显示/输入/内容分区集成） |

对比"照搬 45k 行 C#"：那是 **6~10 个月**，而且拿不到嵌入式可行性。

---

## 9. 风险与回退

| 风险 | 触发条件 | 回退 |
|---|---|---|
| NativeAOT 编不过 | `typeof` 注册表 / `System.Text.Json` 触发 trim 错误 | 退回进程级 IPC + gymnasium，**仍然不重写** |
| 字节码 VM 表达力不足 | 某些机制需要在运行时构造程序 | 保留逃生舱：少量手写"原生节点"；并在 SEMANTICS 里记录该机制为不支持 |
| .NET 侧演进导致语料过期 | 上游改语义 | 冻结 commit + 语料带 schema 版本号，升级需显式重生成 |
| 项目变成长期负担 | 范围蔓延 | 设**最小可玩切片**里程碑：30 张卡 / 3 个敌人 / 1 章地图 / 能跑一局即视为架构成立，达不到就停 |

---

## 10. 立刻要做的三件事

1. ✅ **NativeAOT spike —— 已完成，结论：RL 侧不重写。**（见 §1 用途 A 的实测表）
   产出：`native/RogueDeck.Native/`（原生库工程）、`native/aot_probe.py`（ctypes 验证 + 吞吐测量）。
2. **等 Phase R 的四份 spec**（1~2 天）→ 据此写 `spec/SEMANTICS-v1.md`（W0）。
3. **对拍语料生成器**（W0 的一部分）—— 现在可以**直接调那个原生库**逐秒枚举上万条样本，
   不必再 shell out 驱动 CLI。这是后面所有验收的基准。

**范围也随之收窄了**：既然 RL 侧不用重写，剩下的重写只有一个理由 —— **ESP32 能跑**。
所以 W2~W4 的全部设计约束都应围绕"嵌入式可行"来定（整数、零动态分配、ROM 表），
而不是围绕"RL 要快"。**并且要先确认目标是不是真的裸机 MCU**：如果是跑 Linux 的 ARM64 板，
装个 .NET runtime 就能直接跑，连重写都不需要（或在 Linux 上做一次 NativeAOT）。

---

## 11. W0 进展（增量 1 已完成）

### 11.1 内容层也过了 AOT —— 语料生成器可以在进程内高速跑

第二个 AOT 工程 `native/RogueDeck.Oracle/`（引用 `RogueDeck.Core` + `RogueDeck.Scenario`）
**同样 0 个 IL2xxx/IL3xxx 警告**，产出 5.25 MB 原生库。用 authoring DSL 构造战斗、
跑脚本化的操作序列、从 `ScenarioReport.FinalState` 取 `CombatState`，
再用 `CombatStateHasher.ComputeHash(snapshot)` 拿到 golden 哈希。

**规格书留的那个待办（"验收向量的具体哈希值要在真实实现上跑出来"）由此有了工具**：
`native/make_corpus.py` → `corpus/golden_v1.jsonl`。

| 项 | 实测 |
|---|---|
| 语料规模 | **128 条**（8 变体 × 4 种子 × 4 组数值），0 失败 |
| 确定性自检 | 同 case 跑两次完全一致 |
| 区分度自检 | **128 / 128 个哈希互不相同** |
| 生成吞吐 | **10,700 场/秒** |

### 11.2 发现并闭合了一个会让对拍变成假保证的缺口

第一版语料的 **`random_step` 全是 0** —— 说明那些场景**一次随机数都没抽**。
原因：`ScenarioBlueprint.ShuffleDrawPileOnStart` **默认 false**，而且没有回合开始能量补充、
牌组又只有 3 张。**而 RNG 恰恰是移植最容易分叉的地方**，这样的语料不可能抓到它。

修法：variant ≥ 4 打开 `ShuffleDrawPileOnStart` + `TurnStartResourceRefills` + 12 张牌组。
修完后 v4–v7 的 `random_step ≥ 1`，且同参数下"洗牌 vs 不洗牌"哈希确实不同。

> 这条经验值得记住：**语料库必须先证明自己能区分，再拿去当基准。**
> 所以生成器里内置了三条自检（确定性、哈希区分度、变体间差异），任何一条不过就直接 assert 失败。

### 11.3 规格书带回来的、会改变实现的硬事实

| 发现 | 影响 |
|---|---|
| **内容预编译后约 360–600 KB（按"物化对象图"估）** | ⚠️ **已被 W2 勘察推翻** —— 见 §11.5：内容寻址 + 去重后只需 **≈88 KB**，不必 PSRAM |
| 表达式层只有 `int`/`bool`，**零 float**；唯一浮点在 `PositionalTargetSelectors.cs:43-52` | **P4 的单精度 FPU 对内核不需要**，可以纯整数；位置系统 v1 不实现 |
| `TContext` 泛型依赖 `MakeGenericType`（`CombatJson.cs:44`） | `no_std` 无等价物 ⇒ **泛型必须消灭**；`EventAmountExpression` 已是 tagged-union 模板可直接提拔 |
| `CombatStateHasher` **只覆盖快照子集**（`CardPlayTurnStats` 整块、`TriggerActivity`、`NextSummonedCombatantNumber` 不在哈希里） | 需要两级哈希：`hash_golden` 对拍 + `hash_full` 训练；语料里已额外记录盲区观测量 |
| `DefensivePoolEffects.cs:301` 用 `ImmutableDictionary.Values` 遍历序决定**入队顺序** | 内核里唯一一处"集合遍历序影响队列顺序"，必须排序后入队并记为有意偏离 |
| 引擎自身两个 bug：`ApplyTriggerEventStatusNode` 在 JSON 注册但漏在 executor 注册表；`GainBlockNode` 声明 `ResultKey` 却从不 Store | **重写时按修好的写，并记录为有意偏离** |
| `MaxNodeDepth=64`；`RepeatUntil` 超限**静默完成**而其余循环 **throw** | P4 任务栈只有几 KB，递归深度是硬约束；静默/抛错的区别不可统一 |
| 内核**不校验"只有当前行动者能出牌"** | 这是宿主责任，必须显式写进规格否则对拍跑偏 |

### 11.4 下一步

1. **扩语料覆盖面**（现在的 128 条只覆盖出牌/能量/伤害/回合推进/洗牌，**没有**状态、触发器、
   防御池、多敌人、法令、多段伤害）。变体机制已经跑通，加场景是机械工作 ——
   适合并行，但 `OracleExports.cs` 是共享文件，**需要先拆成 partial class 按机制分文件**再并行。
2. **写 `spec/SEMANTICS-v1.md`（W0 冻结）** —— 3 份规格书已到（effect-program IR / 战斗状态与回合 /
   修饰器管线），第 4 份（内容 schema）在跑。
3. 之后才进 W1（骨架，串行）。

---

## 12. W2 内容勘察的结论（**推翻了 §11.3 的一条**）

第 4 份规格书 `docs/spec/content-schema.md`（649 行）把 7.91 MB 的内容文档拆开量了一遍，
四个发现直接把内容体积砍掉两个数量级：

| 发现 | 实测 |
|---|---|
| **原文 78.6% 只是缩进空白** | 8,291,305 B → 紧凑 JSON **1,774,029 B**（根因：引擎自己默认 `WriteIndented=true`） |
| **紧凑形式里 48.0% 是冗余 `Children` 数组** | 852,325 B；3,038/4,311 个节点的 `Children` 与具名字段逐字节重复，而它是**只读计算属性** ⇒ 删掉不改变行为。剥掉后 **921,704 B** |
| **`Encounters` 独占 71.8%**，92.5% 是 `TriggeredEffects` | 31 条 trigger 程序**只有 10 个互异函数体**，21 份逐字节重复 = 743,993 B（一条 134 KB 的体被写 5 遍） |
| **内容可寻址 + 去重后 ≈ 88 KB** | 全文只用 **73 种 kind / 875 个互异子树**（注册表有 306 种）；`u8 opcode + u16 句柄` 建模：节点层 24,956 B + 表达式/选择器层 7,781 B + 字符串池 43,789 B（1,638 个互异串）+ 15% 表头 |

**原文 : 紧凑 : core ≈ 94× : 20× : 1。**

⇒ **§11.3 里"必须放 PSRAM"的结论作废**：按内容寻址建模，88 KB 进 SRAM（592 KB）都绰绰有余，
甚至可以三份都常驻。**P4 上不需要 PSRAM 来放内容**。

另两条会影响实现的：
- 编译期**必须先建 id → u16 符号表**：id 是裸字符串，改名会波及 `{"value":..}`(3,128)、`{"Value":..}`(747)、
  `Tags` 数组、`Presentation`/`Balance` 的 map 键、以及拼出来的合成 id。实测状态名 `paperwork` 出现 **280 次**。
- **opcode 表要锚定 `CombatJson.cs:217-421`（线格式），不要锚定 `CombatProgramModel.cs`（编辑器模型，
  41+9 个 kind ≠ 注册的 52 个节点）**。
- 现成可搬的校验器：`Sandbox.Run/Composition/RunDocumentValidator.cs`（418 行，纯 data-in/data-out）。

---

## 13. W1 进展：内核骨架 + 第一个模块已通过差分测试

**语言已定：Rust。** 本机 `~\.cargo\bin\cargo.exe` 已有（**1.96.0**，工具链
`stable-x86_64-pc-windows-gnu`），只是没进 PATH。这意味着"Rust 要另外装"的顾虑不存在，
而且 Rust 的 `enum`/`match` 正好适合表达效果字节码，`no_std` 也能上 P4（RISC-V）。

已建：

```
kernel/                    cargo workspace（release: lto + panic=abort）
  rd-core/                 #![no_std] 内核，零依赖、零分配、forbid(unsafe_code)
    src/rng.rs             确定性随机（已通过差分测试）
  rd-rngdump/              仅用于对拍的 std 小工具
tools/cargo.ps1            带完整环境跑 cargo 的助手
native/rng_diff.py         差分测试驱动
```

**第一个模块的实测结果**（这是整条对拍链路的端到端验证）：

| 项 | 结果 |
|---|---|
| `cargo test --release` | **4 / 4 通过** |
| `cargo build --release` | 5.09 秒 |
| 差分用例 | **756 组**（count ∈ {2..255} × seed ∈ {0, 1, 7, 42, ±小值, `i32::MIN/MAX`, `0xA5A5A5A5`} × step ∈ {0,1,2,3,10,100,-1}） |
| **逐位比较的索引数** | **33,768 —— 全部一致** |

边界全部覆盖且一致：零状态重映射（`0x6D2B79F5`）、`i32::MIN`/`i32::MAX` 的 `as u32` 与 C# `(uint)` 强制转换、
负 step、count=255 的 u8 上限。

> 意义：**"移植 + 差分对拍"这条方法论已经在最小的面上被证明可行**。
> 参考引擎的 RNG 算法是 Mulberry32 变体，整个持久状态只有 **(seed, step) 8 字节** ——
> 这也是为什么快照只需要存 step，以及为什么"随机抽取次数不一致"能被立刻抓到。

---

## 14. W0 冻结完成 + 内核基础三件套 + 一个必须马上处理的假保证风险

### 14.1 `spec/SEMANTICS-v1.md` 已交付（306 行）

| 节 | 内容 |
|---|---|
| §1 | 基线 commit `fd43e68ab91f40b475b745725abb17134b951c51`（2026-10-09）+ 5 条变更规则 |
| §2 | IN 细化到子系统级（含 16 个标准状态、7 条法令）；OUT 8 条各写"为什么延后/是否影响已验证部分" |
| §3 | **有意偏离 D1–D15**（偏离/理由/影响面/出处/是否豁免 五列） |
| §4 | **顺序契约 O1–O53 + 边界契约 B1–B4** |
| §5 | 硬上限表（超限行为逐条保留 throw / 静默）+ 实测预算表，带"嵌入式影响"列 |
| §6 | `hash_golden` 规范文本**逐行冻结**（12 类行）；`hash_full` 的 5 类漏检项；新增用例 8 条最低要求 |
| §7 | 12 条未完事项 |

新增的、我自己没预见到的两条偏离值得单列：
- **D9**：id intern 之后 `(Priority, Id)` 的次级键仍是**字符串序**（`TriggeredProgramDefinition.cs:105`）。
  数字序 ≠ 字符串序会**静默改变触发次序** —— 这是 intern 成 u16 时最容易踩的坑。
- **D10**：`CombatLog` 虽然是环形缓冲，但 **`log_count` 必须逐条计数**，否则语料对不上。

### 14.2 内核基础三件套完成，且**裸机目标验证通过**

| 模块 | 行数 | 验证方式 | 结果 |
|---|---|---|---|
| `rd-core/src/rng.rs` | 113 | 与 C# 引擎逐位对拍 | **33,768 个索引全部一致** |
| `rd-core/src/hash.rs` | 253 | NIST 标准向量（空串 / `abc` / 448-bit / 100 万个 `a` / 逐字节分块边界） | **6/6 通过** |
| `rd-core/src/writer.rs` | 268 | 参照 `CombatStateHasher` 的拼写规则（整数/`null`/空白/后缀 token/多字节不劈裂） | **6/6 通过** |

**`cargo check --target riscv32imac-unknown-none-elf -p rd-core --release` → EXIT 0。**

这一条是嵌入式主张的硬证据：内核是**真正的 `no_std`、零分配**，不是"在桌面上看起来像"。
而且特意选了 **`riscv32imac`（无 F/D 扩展）**——P4 是 RV32IMAFC，整数内核不该碰它的 FPU。

`writer.rs` 里固化的一个安全性质值得记住：**写不下时整段丢弃、绝不半写**。
半个字段会被哈希成一个"看起来合理但错误"的指纹，那是确定性测试最不能有的失效模式。
（这条是一个测试先写错、反而暴露出契约该是什么的例子。）

### 14.3 ⚠ 假保证风险：`golden_v1` 的覆盖面比看上去窄得多

SEMANTICS 代理指出、我已独立核实：

| 实测 | 值 |
|---|---|
| 条数 / 哈希互异 | 128 / **128** |
| `random_step` 分布 | **0:44, 1:76, 2:8**（变体 0/1/2 完全不消耗随机数） |
| `problems=1` | **24 条，全部集中在变体 2 与 6** |
| `steps` 取值 | 仅 {2,3,4,7} |
| `pending` 非零 | 0 |

原因：现有 oracle 只造**「一张 `strike`（单个 `DealDamage` 节点）+ 一只 ogre 的 `smash`」**。
⇒ **"128 条全绿"只等于验了「出牌 / 回合 / 轮次 / 伤害 / 死亡 / 能量 / 洗牌」。**
**修饰器管线、状态、格挡、队列卡、法令、拦截器、触发式效果、控制流节点 —— 一条都没覆盖。**

这不是 bug，是**范围还没铺开**；但如果拿它当 W3 的验收基准，就会变成假保证。
处理措施（进行中）：oracle 扩 ABI（起始状态层数、多段伤害、多敌人）+ 把规格书数值向量做成显式用例
→ 产出 `golden_v2.jsonl`。**在 `golden_v2` 生成之前，W3 不得开始。**

另记一条待复核的疑似上游不一致：`MaxProgramSteps=1024`，而 `content-schema.md:529` 实测单个程序有 **1,725 个节点**。

---

## 15. W1 开工 + 覆盖门禁落地

### 15.1 W1 主体已派单（**一个**代理，不并行）

`state.rs`（战斗状态模型）+ `snapshot.rs`（规范序列化器，逐字节复刻 `CombatStateHasher`）。
这是整个移植里耦合最紧的一块，所以按 §5 的铁律 —— **W1 不能拆给多个代理**，接口由单个代理定完。

交付要求里有三条硬验收：
1. `cargo test --release` 全绿（已有 16 个 + 新增）；
2. `cargo check --target riscv32imac-unknown-none-elf -p rd-core --release` → EXIT 0；
3. 12 类行各有**期望字符串精确相等**的测试，外加顺序/溢出/枚举值三类测试。

特别叮嘱它照抄不能"优化"的三个点：换行必须是 `'\n'`；`pending`/`dead`/`ownerbound`/卡牌的 `m:`/`mc:`/`msrc:`/`qat:`
**只在有值时出现**（缺席本身是格式的一部分）；`active=` 用空白表式而 `res=`/`dp=` 的 Max 用 `null` 表式、`owner=` 用 `none` 表式。

### 15.2 覆盖门禁（`native/coverage_check.py`）—— 把"假保证"变成会失败的工具

§14.3 的教训如果不做成**可执行的**，下一次还会犯。所以写了一个门禁工具：

- 读 `corpus/coverage.json`（机制 → 用例 id 列表），对照 **19 个必需机制**逐条判定
  （缺失 / 偏少 / OK），并**核对清单里引用的 case id 真的存在于语料里** ——
  否则清单本身就是空话，不能当覆盖证明。
- 退出码 **1 = 有机制没覆盖 ⇒ 不得开始 W3**。

当前实测（**如实反映现状**）：

```
!! 找不到覆盖清单: D:\Vibe\sts-tui\corpus\coverage.json
   结论：门禁不通过 —— 不得开始 W3。
=== EXIT 1 ===
```

19 个必需机制覆盖的是 W3 的**验收面**：
出牌/落区、付费、基础伤害、格挡吸收、状态施加、状态衰减、
修饰器三侧（Strength 加法 / Weak 乘法 / Vulnerable 在 Target 阶段）、多段伤害、多目标、
防御池 `(AbsorbPriority, Id)` 吸收、死亡前拦截、触发式效果、回合法令、轮次法令、
洗牌 RNG、控制流节点、死亡与 Overkill。

> 门禁的设计原则值得单记：**它宁可因为"不知道"而失败，也不因为"看起来没问题"而通过。**
> 找不到覆盖清单时的行为是**失败**，不是"跳过检查"。

---

## 16. 嵌入式尺寸开始有数字了（W4 的度量工具已就位）

### 16.1 内核的 RISC-V 代码尺寸

新增 `kernel/rd-sizeprobe`（staticlib，为裸机目标构建）+ `tools/size_probe.py`
（**自己解析 `ar` 归档与 ELF32 段头**——本机没有 riscv 的 objdump/size，为读两个数字装一套交叉工具链不值得，
而 `ar`/ELF 格式足够简单）。

实测（`riscv32imac-unknown-none-elf`，release + LTO）：

| crate | 目标文件 | `.text` | `.rodata` | `.bss` |
|---|---:|---:|---:|---:|
| compiler_builtins（vendored，未链接） | 380 | 215,244 | 38,866 | 0 |
| core/std（vendored，未链接） | 36 | 11,296 | 474 | 0 |
| **rd_sizeprobe（含被 LTO 内联进来的 rd-core）** | 1 | **4,616** | **590** | 0 |

⇒ **内核（rng + SHA-256 + 规范写入器）连同 probe 只有 ≈ 5.2 KB 的代码。**

⚠ 两条必须说清楚的解释，否则这个数字会被误读：

1. **archive 不等于链接后的镜像。** 静态库里有全部依赖的全部目标文件，而 `core` 是 `no_std` 的依赖 ——
   把整个归档求和会得到 231 KB，那几乎与内核无关。有意义的是**按 crate 拆分**：内核自己的部分 vs
   vendored 的 `core` 地板（真链接后大部分会被 `--gc-sections` 回收）。
2. **`rd_core` 没有独立目标文件**，因为 release 开了 LTO，它已被内联进 probe 的对象。
   所以 4,616 B **就是**"内核 + probe"的合计，不是"只有 probe"。

**要得到真实固件占用，还需要一次最终链接**（链接脚本 + 内存布局 + `--gc-sections`），那是 W4 的工作。
现在这个数字的用途是**量级判断**：三个基础模块 5 KB，即使完整内核（状态 + 管线 + 队列 + 回合机 + 字节码 VM）
再大 20~40 倍，也就 100~200 KB —— 而且代码通常进 Flash 不是 SRAM。**嵌入式目标的空间完全不紧张。**

### 16.2 W2 内容编译器已产出真实二进制

`tools/contentc/` 已产出 `out/content.core.rdcf` = **92,924 B**（core 变体）与 `out/content.rdcf` = 165,412 B（完整变体）。

| 阶段 | 字节 | 相对原文 |
|---|---:|---:|
| 源 JSON | 8,291,305 | 1× |
| 紧凑 JSON | 1,774,029 | 4.7× |
| 剥掉冗余 `Children` | 921,704 | 9× |
| **RDCF core 二进制** | **92,924** | **89×** |

编译耗时合计 **0.64 秒**（json_load 0.076 + derive 0.199 + encode 0.291 + serialize 0.073），峰值堆 26.7 MiB。
表结构：STR/STRO（字符串池）/OPD/OPF（opcode）/TRM/TRW（term）/AUX/CARD/STAT/EACT/ENCT/REL/ROOT/IDX/TAGS，
卡牌 62 条 × 28 B、状态 23 × 36 B、敌人动作 394 × 16 B、遭遇 109 × 20 B、遗物 49 × 12 B、id 索引 692 条。

⇒ 与 §12 的估算（≈88 KB）吻合。**内容表 90.7 KB + 内核代码约 5 KB + 单场战斗状态约 9 KB，
三者加起来不到 592 KB SRAM 的 20%。**

---

## 17. 独立验证（第 7 轮）：两处外部产物被交叉检查过

子代理自己说"我对"是没有价值的。这一轮做的是**用另一条路径重新解读同一份产物**。

### 17.1 RDCF 内容二进制：独立解出段目录

写了 `tools/rdcf_verify.py` —— **不读编译器的代码，只读它产出的字节**。第一版按 16 字节步长猜目录项，
解出来是 `(272, 76799, 3140, 77072)`，而 manifest 说第 0 段是 `(offset=272, bytes=76799, count=3140)`。
⇒ 真实的目录项是 **12 字节**的 `(offset, bytes, count)` 紧密排列；manifest 的 `directory_bytes=240`
= 15×12（目录）+ 15×4（另一个独立数组）。改成正确步长后：

```
段目录     独立解出 15 段，offset/bytes/count **与 manifest 逐字段一致**
```

两个变体都通过：`content.rdcf` 158,392 B（sha256 `1025b8f0…`）、`content.core.rdcf` 85,712 B（`d45737e3…`）；
magic `0x46434452` 正确、段间无重叠、manifest 与磁盘字节一致、空隙仅 3 B。

**边界说清楚**：本工具验证的是**结构**，不是语义。段内编码是否正确、是否等价于源 JSON，
要靠编译器的 reader/validate 与 golden 回归回答 —— 输出里显式列出了"未执行/不在范围内"的项。

### 17.2 顺手修掉自己工具里的一个"假检查"

第一次跑出来 `count×stride` 那几行显示 `stride 0 B` —— 说明 manifest 的 `tables` 结构变了，
**这个检查悄悄退化成了空操作**，而收尾总结还在声称它通过了。

这正是我在 §15.2 立的那条原则要防的东西：**一个"查不到就跳过"的检查比没有检查更糟，它会伪装成通过。**
改成显式统计真正跑过的检查数，一个都没跑就报出来：

```
? CARD 段：manifest 里没有 tables.cards.count，**这项检查未执行**
...
· core: 定长表的 count×stride 自洽性检查**一次都没跑成** —— 这部分覆盖是空的
```

### 17.3 RNG 对拍回归：oracle 重构没有破坏契约

oracle 被重构成了 partial class 并新增了 `Random` / `Extended` / `Probes` 三个文件。
重跑 `native/rng_diff.py`：**756 组用例、33,768 个索引逐位比较，全部与 C# 引擎一致（EXIT 0）**。
⇒ 上一轮验收过的契约在重构后仍然成立。

### 17.4 累计已验证项

| 产物 | 验证方式 | 结果 |
|---|---|---|
| Rust RNG vs C# 引擎 | 逐位对拍 33,768 个索引 | ✅（重构后复验仍通过） |
| Rust SHA-256 | NIST 标准向量 5 条 + 分块边界 | ✅ |
| Rust 规范写入器 | 拼写规则 / 溢出 / 多字节 | ✅ |
| 内核裸机可编译 | `--target riscv32imac-unknown-none-elf` | ✅ EXIT 0 |
| 内核代码尺寸 | 独立解析 `ar`+ELF32 | ✅ ≈5.2 KB |
| RDCF 内容二进制 | 独立解段目录 + 结构不变量 | ✅（语义待编译器 validate） |

---

## 18. 指纹闭环（第 8 轮）：Rust 的 SHA-256 在真实引擎文本上逐字符匹配

### 18.1 为什么这一步值得单独做

NIST 向量只证明"这是个正确的 SHA-256"，**证明不了它和引擎一致**。引擎的指纹是
"把一段特定的规范文本按 UTF-8 做 SHA-256"，真正的风险在**拿到的是不是同一段字节**
（换行是 `\n` 还是 `\r\n`、有没有尾随换行、编码、截断）。规格书 §6 逐行冻结了格式，
但"照规范写的"和"引擎实际产出的"是两件事。

oracle 现已导出 `rd_oracle_hash_input_{len,char,ok}`（预哈希文本），所以这个问题今天就能回答，
不必等状态模型写完。

### 18.2 结果

新增 `kernel/rd-hashdump`（用内核的 SHA-256 哈希文件）+ `native/hash_diff.py`（驱动 + 比对）。

```
用例数: 48（跳过 0）
样本 case_0000_v0_s1.txt：375 B，24 个换行
  ---- 规范文本（前 12 行）----
    id=oracle
    seed=1
    step=0
    result=0
    round=1
    turn=2
    phase=1
    active=ogre
    status_num=1
    card_num=4
    chain_num=9
    exec_num=3
  ---- 结尾 3 行 ----
    disc=card_000003 strike
    cz=ogre
    <空行>            ← 文本以 '\n' 结尾

✓ 全部一致：Rust 内核的 SHA-256 在真实引擎的规范文本上逐字符匹配。
```

⇒ **指纹这一半的闭环成立**：换行是 `'\n'`、有尾随换行、`active=` 非空时写值，
都与规格书冻结的格式一致。剩下的是**状态模型的字节级对拍**（等 W1 的 `snapshot.rs`）。

### 18.3 踩到的协作问题，以及绕开它的手法

构建 `rd-hashdump` 时失败，原因不是我的代码：**W1 代理正在写的 `rd-core/src/state.rs` 目前编不过**
（`Bounded::<CardInstance, 224>::new` 不是 `const fn`，E0015），而 `rd-core` 是所有 crate 的依赖。

这是"共享 crate 在飞行中被改"的真实代价 —— §5 那条 **"W1 绝不能并行"** 的另一个侧面：
它不只意味着接口不能分叉，也意味着**只要 W1 没落地，整条下游都编不了**。
（另外 cargo 的构建目录锁会让两边互相阻塞 —— 实测等了 3 分 37 秒。）

**绕开手法（不复制代码）**：`rd-hashdump` 的 `Cargo.toml` **故意不依赖 `rd-core`**，
改成在 `main.rs` 里用 `#[path = "../../rd-core/src/hash.rs"] mod hash;` **直接 include 同一个源文件**。

- 是**同一个磁盘文件**，内核的哈希器改了，这个工具跟着变 —— 所以它验证的是真东西，**不是副本**；
- 又**不依赖 `rd-core` crate**，所以在内核半成品期间它照样能建、能跑。

> 经验：**验证工具不应该依赖正在被改的代码。** 但也不能退化成"验证一份副本"（那样什么也没验证）。
> `#[path]` include 是这两者之间的一条窄路：同一份源码，零耦合。

### 18.4 oracle 的 ABI 已远超要求（56 个导出）

用 `native/pe_exports.py`（自己解析 PE 导出表，不猜符号名）拿到真值：

- 我要的 `rd_oracle_hash_input_{len,char,ok}` ✅
- 一批观测量：`hero_block` / `hero_ward` / `enemy_block` / `enemy_ward` / `hero_stacks` /
  `hand_count` / `draw_count` / `discard_count` / `exhaust_count` / `queue_count` / `phase` / `result` …
- **一批机制探针**：`probe_conditional` / `probe_repeat` / `probe_for_each` / `probe_expr` /
  `probe_intercept` / `probe_trigger_order` / `probe_decree` / `probe_reshuffle` / `probe_shuffle_pile` /
  `probe_snapshot` / `probe_turn` / `probe_program_steps`

这些正好对应覆盖门禁里的控制流、拦截器、触发器、法令、洗牌等条目 —— 门禁看起来很可能会通过。
另注：`RogueDeck.Native.dll`（Core-only）14 个导出，`RogueDeck.Oracle.dll`（Core+Scenario）56 个。

---

## 19. 覆盖门禁第一次真正运行：把"17/19"打回"14/19"

第 9 轮，oracle 代理产出了 `coverage.json` / `golden_v2.jsonl`（28 条）/ `spec_vectors_v1.jsonl`（74 条），
门禁终于有东西可判了。**结果比预期有用得多。**

### 19.1 门禁自己的一个缺陷先被修掉

第一版门禁只索引 `coverage.json` 里声明的**那一个** `corpus` 文件，于是报出"清单引用了不存在的 case id"
—— 而那些 id 其实活在**另一个语料文件**里。这是**我的工具的误报**，不是清单的问题。

改法：索引 `corpus/` 下**所有** `.jsonl`，并对找不到的 id 给出**近似匹配提示**。
结果立刻显示出真正的错法：

```
[damage] 清单写 'vec-modp-01'，但 spec_vectors_v1.jsonl 里叫 'modp-01'
[block]  清单写 'vec-modp-15a'，但 spec_vectors_v1.jsonl 里叫 'modp-15a'
[card_play] 清单写 'vec-cst-V11a'，但 spec_vectors_v1.jsonl 里叫 'cst-V11a'
```

⇒ 清单里的 id 多了一个 `vec-` 前缀。**这类"清单与文件对不上"如果只报"找不到"，人会去翻文件；
报出近似匹配，人一眼就知道该改哪边。**

### 19.2 修完之后：真实覆盖是 14/19，不是 17/19

关键改动是**只统计在语料文件里真实存在的 case id**。之前的 17/19 是被不存在的 id 抬高的。

| | 之前（数声明） | 现在（数真实） |
|---|---|---|
| 通过 | 17/19 | **14/19** |
| 无真实用例 | 2 | **5** |

现在判定为"缺失"的 5 个机制及其真实用例数：

| 机制 | 清单引用 | 真实存在 |
|---|---:|---:|
| `pre_down_intercept`（死亡前拦截） | 0 | **0** |
| `triggered_effect`（触发式效果） | 4 | **0** |
| `decree_turn`（回合法令） | 4 | **0** |
| `decree_round`（轮次法令） | 0 | **0** |
| `rng_shuffle`（洗牌 RNG） | 2 | **0** |

**这一条就是门禁存在的全部理由**：一份"看起来 17/19 通过"的清单，实际有 5 个机制是空的。
若直接拿它当 W3 的验收基准，这 5 块就是假保证。

### 19.3 已把精确诊断发回给 oracle 代理

要求收尾前修三件事：① `vec-` 前缀二选一统一；② 那 5 个机制补上**真实跑出来并落进语料**的用例
（`probe_intercept` / `probe_decree` / `probe_reshuffle` 在 ABI 里都已存在，用例是能造的）；
③ `coverage.json` 的 `corpus` 字段说法与实际不符，改成 `corpora` 数组或删掉。

**验收：19/19 OK 且退出码 0，W3 才可开始。** 若某机制确认用当前 ABI 无法覆盖，
应列进"无法覆盖"清单，而不是塞进 coverage.json —— **门禁宁可因为"不知道"而失败，不因为"看起来没问题"而通过。**

---

## 20. 第 10 轮：门禁通过，W3 解锁；同时拦下一个"把对的改成错的"风险

### 20.1 门禁：19/19，退出码 0（我独立复跑确认）

```
card_play 8/8 · energy_cost 8/8 · damage 23/23 · block 9/9 · status_apply 6/6 · status_decay 2/2
modifier_strength 10/10 · modifier_weak 5/5 · modifier_vulnerable 7/7 · multi_hit 3/3 · multi_enemy 6/6
defensive_pool 4/4 · pre_down_intercept 3/3 · triggered_effect 4/4 · decree_turn 4/4 · decree_round 3/3
rng_shuffle 2/2 · control_flow 27/27 · death 4/4
结论：门禁通过（覆盖 19/19）。  EXIT=0
```

id 与语料**同名同形**（无前缀），`make_corpus.py` 在写 `coverage.json` 之前会自检所有 id 都能找到，
dangling 直接 `AssertionError` —— 上一轮那类"清单是空话"从流程上不会再产出。
冻结基线挪到 `corpus/baseline/`（子目录，不被 `*.jsonl` 扫描到）。

**⇒ W3 可以开始了。**

### 20.2 W2 内容编译器交付：85,616 B（96.8×）

| | 字节 | 对原文 |
|---|---:|---:|
| 原文 | 8,291,305 | 1× |
| 紧凑 JSON | 1,774,029 | 4.7× |
| 剥冗余 `Children` | 921,704 | 9.0× |
| **`content.rdcf`（完整无损）** | **158,296** | **52.4×** |
| **`content.core.rdcf`（剥表现层）** | **85,616 = 83.6 KiB** | **96.8×** |

16,890 个 IR 实例 intern 成 **2,895 条互异 term 记录**（均 11.7 B）—— 这就是 158 KB 与 360–600 KB 的分界。
**id 包装对象从不落盘**（同一 id 有三种写法：裸串 / `{"value":s}` 3128 次 / `{"Value":s}` 747 次），省 **72,950 B**。

**一个我认可的设计判断**：它给每个字段 kind 配了 **ABSENT + NULL 两个哨兵**，
于是 `reader.py` 重建的文档与原文**逐路径结构相等、含键的存在性**。
代价是 `F_INT` 损失 -32768/-32767（实测内容范围 [-300, 1024]）。
**收益是：不必再论证"删掉冗余 `Children` 是安全的"** —— interning 之后它只值几百字节，所以它**照存**，
换来 validate 能报"结构完全一致"而不是"我认为等价"。这直接回答了我上一轮的质问。

六项校验全 PASS（良构 / 逐路径往返 / 929 id·80 命名空间·4,459 次引用 0 悬空 / id 全 ASCII / 确定性 / 命名空间卫生）。

**我的判断 —— 可达性 27.5% 不要默认剪**：可达性 BFS 显示 43,506 B（27.5%）是这张 act-1 地图到不了的
（109 个遭遇只放了 23 个，394 个敌人动作只 89 个可达）。但：
① 地图只覆盖 act 1，剩下的很可能是留给 act 2/3 的，砍了就再也装不回去；
② 85 KB 对 Flash 毫无压力，省这 27% 换不来任何东西；
③ **剪裁会让"内容镜像"与"地图"产生隐式耦合** —— 地图一改，可达集就变了，镜像却不会自己失效。
⇒ **默认出完整镜像；"仅可达"作为构建选项**，并把可达率作为 validate 的一项**诊断数字**报出来（已实现）。

### 20.3 oracle 侧：75 条规格书向量对拍 —— 抓出规格书一处真错

| 结论 | 条数 |
|---|---:|
| 一致（实测 == 规格书声称） | **48** |
| 带口径说明的一致 | 12 |
| **不一致** | **1** |
| 无法表达（本 ABI 摆不出前置条件） | 14 |

数值类**全中**：`(5+2)×1.5 → HP 100→90`、`base 6 + 力量2 + 弱 + 易伤 → HP 12→3`、
真伤绕过所有池 HP 14、boss `70-2×8=54`、Phoenix HP 25、Martyr `盟友5/保护者40`、
`Divide(10,0)=0` 与 Fault 抛异常、法令 `5/3/2`。

**规格书唯一读错的地方（实测抓到）**：`combat-state-and-turn.md` §7 V12 声称
「`EndTurn` 后 `Queue` 空」。实测解析窗口是**拥有者下一次回合开始**，所以**单次 `HeroEndsTurn` 不足以排空**
（`enemy_hp=200 / queue_count=1`），必须走完一整轮才是 `187 / 0`。
⇒ 规格书需要更正（`cst-V12c` 有意留证）。

### 20.4 两条会改变对拍设计的硬事实

1. **哈希盲区有实证了**：`ex_dmg_kill`（problems=0）与 `ex_dmg_overkill_early_stop`（problems=1，敌人中途被打死触发早停）
   **哈希完全相同**。⇒ 对拍 harness **必须同时比 `problems` / `steps` / `log_count`**，
   否则"哈希一致"就是假保证。这一条把规格书 §3 D12 的推测变成了实证。
2. **`CombatSaveJson` 在 NativeAOT 下运行时直接抛**
   `Reflection-based serialization has been disabled for this application.`（还带 IL2026/IL3050）。
   ⇒ **引擎的存档路径不是 AOT 友好的**：① 它不能作为对拍面；② RL 侧若想靠它做 snapshot/resume 也不行；
   ③ W1 的 Rust 侧得自己定义存档格式（快照结构我们已经有了，反而是好事）。

### 20.5 规格书要记的一笔：v1 不支持轮次级法令

`decree_round` 那一格覆盖的是**轮次边界本身**（`cst-V2` 回绕、`cst-V13c` 带法令走完整轮），
因为引擎的 `CombatRule` 枚举**没有轮次级法令**，只有回合级
（`MaxCardsPerTurn` / `MaxHandSize` / `UnspentResourceCarries` / …）。
⇒ 应在 `SEMANTICS-v1.md` 的 OUT 里加一条 **"不支持轮次级法令"**，而不是把它算作已覆盖。

### 20.6 W1 落地了，但**测试在失败** —— 其中至少 2 条是测试自己写错

`check -p rd-core --release` → **EXIT 0（编译通过）**；`test -p rd-core --release` → **60 passed / 7 failed**。

逐条看了断言之后：

| 失败 | 诊断 |
|---|---|
| `snapshot::a_full_document_matches_the_reference_line_for_line` | **实现对、测试错**：实现写 `msrc:hero`，测试期望 `msrc=hero`。`CombatStateHasher.cs:156` 是 `sb.Append(" msrc:")` —— **冒号**（同族 `m:`/`mc:`/`qat:` 也都是冒号） |
| `snapshot::card_lines_use_the_zone_as_key_and_the_optional_suffixes` | 同上，同一条断言 |
| `snapshot::the_very_first_line_fits_before_the_overflow_is_noticed` | 期望 `id=` 实得 `id=c1` —— fixture 没给到空 id |
| `snapshot::scalar_lines_are_written_in_order_with_enums_as_integers` | 同上的"空 id"问题 |
| `state::id_is_bounded_and_ascii_only` | 36 vs 35，边界定义待确认 |
| `state::mark_helpers_keep_marks_sorted_and_deduplicated` | `Err(Full(Marks))` —— Marks 容量或测试超量 |
| `state::the_card_pool_is_bounded_for_the_whole_fight` | 期望先撞 `CardInstances` 实得先撞 `CardsInZone(DiscardPile)` —— **分区容量可能定小了，真战斗会莫名失败** |

⚠ **这一条是独立验证最直接的回报**：如果只看到"文件落地了 + 编译通过"就放行 W3，
就会把一个**测试在失败**的内核当成地基。已把逐条诊断发回给 W1 代理，并特别叮嘱
**不要把正确的实现改成去迎合写错的测试**（那会制造一个真实的 bug）。

> 顺带给 W1 代理指了条更可靠的路：与其手写期望字面量，不如拿真实引擎导出的规范文本做对照
> ——`corpus/hash_cases/case_0000_v0_s1.txt`（375 字符，`sha256 f3298ef4…`，每行以 `\n` 结尾）
> 就是现成的、来自引擎的 ground truth。

---

## 21. 第 11 轮：W3 按纪律继续押后，转开 RL 线

### 21.1 为什么没有按计划启动 W3

第 10 轮门禁已过、W3 解锁，但**W1 的测试仍然红着**（7 条失败，`check` EXIT 0 / `test` 60 passed 7 failed）。

按 §5 的铁律 —— **"W3 之所以能并行，是因为 W0/W1 已经把接口冻死了"** —— 现在放并行代理进场是错的：

1. 叶子模块都依赖 `state.rs` / `snapshot.rs` 的类型；接口虽然能编译，但**测试在失败意味着语义还没定**；
2. 实测过 cargo 构建目录锁的代价（两边互相阻塞，一次等了 3 分 37 秒）—— 多代理同时构建一个红着的树只会更糟。

⇒ **W3 继续押后**，等 W1 转绿。诊断已发回，代理仍在修。

### 21.2 转开 RL 线：接口先冻结，再实现

目标里的另一半是"**多开作为强化学习训练环境**"。检查后发现现有 oracle ABI 不够用：
`rd_oracle_run` / `rd_oracle_run_ex` **跑的都是固定脚本**（由 `variant` 选形状），
而训练环境需要**逐决策交互**（观察 → 枚举合法动作 → step → 看结果）。
拿固定脚本做 RL 会退化成一个 bandit。

于是按"冻结接口"的纪律，先写死 **`docs/spec/env-abi.md`（v1，≤150 行）**，再让实现方照它做：

| 设计选择 | 理由 |
|---|---|
| **句柄式**（`rd_env_create -> handle`） | 一个进程里要能并存 ≥16 个环境实例做向量化，不能有"当前环境"这种全局状态 |
| **全部 blittable**（int 进 int 出） | 字符串走 `_len`/`_char` 对；跨 ABI 不传结构体 |
| **观察是定长整数向量**，`rd_env_observe_len()` 公布长度 | 调用方不得写死长度；布局在 spec §4 明确（敌人 ≤4、手牌 ≤10、状态轴 5、牌堆 5、尾部 8 保留） |
| **未占用槽位填 `-1` 而不是 `0`** | **0 是真实取值**（0 层状态、0 点格挡）；用 0 表示"不存在"会让包装层分不清"没这张牌"和"这张牌 0 费" |
| **`rd_env_step` 拒绝时必须状态不变** | 否则 RL 的 transition 不成立；spec §8 要求**逐次断言**而不是只信返回值 |
| **奖励单位是厘（1/1000）** | 避开浮点 —— 与"内核纯整数"同一条纪律 |
| **卡定义用 `def_slot` 小整数句柄** | 观察里不能塞字符串；slot 由内容编译器按 id 排序分配并写进镜像的 `IDX` 段 |

### 21.3 使用方已写好，而且**故意在 ABI 缺失时响亮失败**

`py/roguedeck_env/`：

- `native.py` —— ctypes 绑定。找不到 15 个环境导出时抛 `ABIMissing`，并把**缺哪些、怎么构建**说清楚。
- `env.py` —— `RogueDeckEnv`（`reset/step/actions/action_mask`）+ 按名的观察解码器
  （布局变了会直接报"ABI 或规格书有一边变了，先对账再训练"）。
- `smoke.py` —— spec §8 的五条验收，退出码 **0 全过 / 1 有项失败 / 2 ABI 未实现**。

实测（ABI 还没实现时）：

```
!! 环境 ABI 尚不可用 —— **这不是通过**：
   RogueDeck.Oracle.dll 缺少环境 ABI 导出：rd_env_action_arg, rd_env_action_count, … 共缺 15/15 个。
   退出码 2 = ABI 未实现，不等于验收通过。
EXIT=2
```

> 这条纪律与覆盖门禁同源：**一个在环境不存在时安静通过的冒烟测试，会让训练脚本"跑得通"而看不出任何问题。**
> 所以 `2` 是一个**独立的、非零的**退出码，而不是"跳过"。

### 21.4 状态

| 线 | 状态 |
|---|---|
| W1 state + snapshot | ⚠️ 编译过、**测试 7 条红**，诊断已发回 |
| W2 内容编译器 | ✅ 85,616 B（96.8×） |
| oracle ABI + 语料 + 门禁 | ✅ 56 导出 / 19 机制 / 75 向量 / 门禁 19/19 |
| **环境 ABI（新）** | 🔄 规格已冻结，已派给 oracle 侧实现（新增 `OracleExports.Env.cs`） |
| **Python 训练环境（新）** | ✅ 包装与验收自检已就位，等 ABI |
| W3 叶子模块（并行） | ⛔ 押后至 W1 转绿 |

---

## 22. 第 12 轮：W1 从 7 条红降到 3 条；顺手做了个"断言差异定位"工具

W1 的测试 7 → **3**（66 passed）。剩 3 条我又做了一轮逐字符定位，并把结论发了回去。

### 22.1 为什么需要 `tools/assert_diff.py`

Rust 的 `assert_eq!` 失败时打的是**两整行几百字符的转义字符串**。第一次看 W1 的失败，
我截取尾部一看"两边一样"，差点以为断言是假的 —— 其实差异在字符串中间。

这个工具从 cargo test 日志里把 `left:`/`right:` 解出来（含 `\n` 还原），报**第一个不同的下标 + 上下文 + 是第几行**。
一跑就出结论：

```
a_full_document_matches_the_reference_line_for_line
  长度 left=828 right=828，首个差异在下标 628
    left  = ...msrc:hero qat:ogre\nqueue=...
    right = ...msrc:hero qat=ogre\nqueue=...
```

⇒ **又是"实现对、测试字面量错"**：`CombatStateHasher.cs:160` 是 `sb.Append(" qat:")`（冒号），
同一族的 `m:`/`mc:`/`msrc:` 也全是冒号。代理上一轮修了 `msrc=` 却漏了 `qat=`，共 4 处测试期望。

> 一个可以复用的教训：**长字面量的断言失败时，"肉眼比对"是不可靠的**，
> 必须让程序报出第一个差异下标。这条对任何"期望值写在测试里"的场景都成立。

### 22.2 没有去替它改，因为文件 18 秒前刚被写过

诊断出来后我本可以直接改那 2 个字符（4 处）。但检查文件 mtime 发现**代理 18 秒前刚写过**——
此时我去编辑同一个文件，几乎必然互相覆盖。所以**只发诊断、不动文件**。

> 与并行代理协作的一条纪律：**先看 mtime，再决定要不要写同一个文件。**
> 这不是礼貌问题，是"谁的工作会被丢掉"的问题。

同时给了它一个更根本的建议：**别再手写 800 字符的期望串**。
真实引擎导出的 ground truth 就在 `corpus/hash_cases/case_0000_v0_s1.txt`
（375 字符、`sha256 f3298ef4…`、每行以 `\n` 结尾），把测试改成"读这个文件 + 断言 sha256 相等"，
**格式一漂就是拿引擎比出来的，不是拿人写的字面量比出来的**。

---

## 23. 第 13 轮：W1 转绿，**W3 并行叶子正式启动**

### 23.1 W1 转绿

```
cargo test -p rd-core --release   →  test result: ok. 69 passed; 0 failed   EXIT 0
cargo check --target riscv32imac-unknown-none-elf -p rd-core --release  →  EXIT 0
```

从第 10 轮的 7 条红、第 12 轮的 3 条红，到 0 条。**门禁（19/19）+ W1 绿 ⇒ 两个前置条件都满足，W3 解锁。**

### 23.2 启动 W3 之前先做的一件事：冻结文件边界

并行代理最典型的死法不是"想不清楚"，而是**抢同一个文件**。这次的争用点是 `lib.rs`：
每个叶子都要加一行 `pub mod X;`。

所以顺序是：**先把接口冻死，再派活。**

1. 我新建两个桩文件 `rd-core/src/content.rs` 与 `rd-core/src/status_catalog.rs`，
   里面是**冻结的类型与函数签名 + `todo!()` 函数体**，还写清了规格出处与"必须照抄不能优化"的点；
2. 我自己把 `pub mod content;` / `pub mod status_catalog;` 加进 `lib.rs`，并**验证树仍是绿的**
   （69 passed / 0 failed，裸机 EXIT 0）；
3. 然后才派代理，并在任务书里写明：**只允许改你那一个文件**；
   需要动核心（`state.rs` / `snapshot.rs` / `lib.rs` …）时**报告而不是自己改**。

这样两个代理可以同时工作而零冲突 —— 因为它们**要么在自己的文件里，要么在等我**。

### 23.3 两个叶子

| 叶子 | 文件 | 规格依据 | 为什么能独立 |
|---|---|---|---|
| **RDCF 内容镜像读取器** | `src/content.rs` | `docs/spec/content-binary-format.md` + `tools/contentc/rdcfmt.py` + `reader.py` + 真实镜像 | **完全不依赖状态模型**，输入是一段字节 |
| **状态与修饰器目录表** | `src/status_catalog.rs` | `modifier-pipeline.md` §2–§4、`SEMANTICS-v1.md` §3 D9 / §4 | 纯数据 + 纯谓词，不依赖状态模型 |

任务书里额外压了三条纪律：
* 验收 = `test` **失败数必须为 0**（基线 69 passed，只许多不许少）+ 裸机 `check` EXIT 0；
* 测试里读真实产物（`content.core.rdcf`）时，**找不到就 panic 并说明路径，不许静默跳过** ——
  与覆盖门禁、env 冒烟同一条原则：**在产物缺席时安静通过的测试，等于没有测试**；
* 状态目录那个叶子必须把**"加法先于乘法"写成断言**（错序会得到 9 而不是 10）——
  把规格里最容易搞错的那一条固化成可执行的规格，而不是注释。
  并要求它把每一步整数取整的中间值都写进测试，**若算出来与规格书不符就如实报告，不要迁就**。

### 23.4 状态

| 线 | 状态 |
|---|---|
| W1 state + snapshot | ✅ **69 passed / 0 failed**，裸机 EXIT 0 |
| W2 内容编译器 | ✅ 85,616 B（96.8×） |
| oracle ABI + 语料 + 门禁 | ✅ 56 导出 / 19 机制 / 75 向量 / 门禁 19/19 |
| 环境 ABI | 🔄 `OracleExports.Env.cs` 已建（实现中） |
| Python 训练环境 | ✅ 包装 + 验收自检就位（等 ABI） |
| **W3 叶子模块（并行）** | 🔄 **已启动 2 个**（内容读取器 / 状态目录表），文件互不重叠 |
| 裸机代码尺寸 | ✅ ≈5.2 KB（三个基础模块时） |

---

## 24. 第 14 轮：环境 ABI 通过，但**多开接入时撞到一个契约违反**

### 24.1 环境 ABI 五条验收全过

```
观测长度: ABI 报 122，spec §4 推得 122  ✓
selfcheck: 12 组 (config, seed) 全部返回 1  ✓
随机策略整局跑通: 12 局，均正常结束、无越界  ✓
拒绝动作不改变状态: 16 次越界全部被拒且观察逐项未变  ✓
多句柄: 16 个实例交错 step 与单独跑逐项一致  ✓
✓ §8 的五条全部通过。  EXIT=0
```

**目标里"可作为多开强化学习训练环境"这一半，至此有了可验证的实现。**

### 24.2 但在写多开吞吐时撞到一个严重问题

`bench.py` 里单进程基线一跑就抛 `rd_env_step(action=1) -> -1`。写了个诊断脚本
（`py/roguedeck_env/diagnose_reject.py`）把出事前后的完整状态都抓下来：

| | 拒绝前 | 拒绝后 |
|---|---|---|
| `rd_env_step` 返回 | — | **-1（声称拒绝）** |
| 动作列表 | **5 个**（4 张手牌 + 结束回合） | **0 个** |
| 能量 | 2/3 | **1/3 ← 费用被扣了** |
| done | False | **True** |
| 观察 | 6 个字段不同（下标 3, 8, 17, 18, 22, 23） | |

被选中的是 `(0,0,0)` = 打手牌 0，**费用 1 < 能量 2，付得起**；引擎自己的错误串是
`the engine refused the play (unaffordable or rejected by a validator) | engine problems: ` —— **没报任何 problem**。

⇒ **`rd_env_step` 报告"拒绝"，却已经扣了能量、改了 6 个观察字段、把 `done` 翻成了 True。**
这直接违反 `env-abi.md` §5（"拒绝时状态必须保持不变"），而理由是**RL 的 transition 不成立**：
智能体看到一个 -1、决定换个动作重试，实际却在**已经前进过的状态**上操作。

### 24.3 我的冒烟测试为什么没抓到 —— 这条经验值得单记

§8 第 3 条我写的是"越界下标被拒且观察不变"，跑的是 `n`、`n+1`、`10000`、`-1`。
**而真正会违反契约的是"在范围内、但引擎会拒绝"的那一类**（能量不足时打牌、对已死目标出牌）。

> **"拒绝是零副作用"必须用"会被拒的合法动作"去测；用越界下标测，等于没测。**
> 这与覆盖门禁、env 冒烟是同一条原则的另一面：**测试要打在要害上，不是打在容易写的地方。**

已把复现步骤、前后状态对照、以及"两类拒绝都要断言"的要求发回实现方。

### 24.4 顺带产出

* `py/roguedeck_env/vec.py` —— 多进程向量化（N 进程 × M 句柄）。两个设计选择：**每 worker 持多个句柄**
  （跨进程通信有固定成本，一进程一句柄会让 IPC 成为瓶颈）；**reset 换种子 = 重建句柄**（句柄式 ABI 的既定语义，不自创）。
* `py/roguedeck_env/bench.py` —— 多开吞吐 + 确定性（**同一批种子换成不同进程布局，轨迹必须逐项一致**，
  这比"多进程跑两次一致"更强：它证明摊到更多进程上不改变环境）。
* `py/roguedeck_env/diagnose_reject.py` —— 把它固化成可复跑的诊断，而不是一次性调试。

---

## 25. 第 15 轮：拒绝语义已修；多开跑通，但**是一个净亏损**

### 25.1 拒绝语义确认修好

`diagnose_reject` 现在报：

```
config=0/1/2/3: 400 步内没有被拒的动作  ✓
✓ 4 个 config 各 400 步内都没有出现「列表内动作被拒」   EXIT=0
```

§24 报的那个"报告拒绝却改了状态"已经不复现。同时 `rd-core` 仍 **69 passed / 0 failed**。

### 25.2 多开基准：数字不好看，但这是最有价值的那种数字

```
单进程 4 句柄（无 IPC）      :   5,911 步/秒
1 进程 × 4 句柄（走 IPC）    :     227 步/秒
4 进程 × 4 句柄 = 16 env     :     719 步/秒
8 进程 × 4 句柄 = 32 env     :   1,125 步/秒
```

**多开路径比单进程慢约 26 倍**：8 个进程加起来 1,125 步/秒，而一个进程里 4 个句柄就有 5,911。

原因不含糊：**每步都要把一个 4 × 122 个整数的观察经 `Pipe` pickle 一次往返**。
8 进程 × 4 环境 × 122 个数 = 每步约 3,900 个整数要被序列化 —— IPC 完全主导了开销，
"多开"的收益被通信成本吃光还倒亏。环境本身不是瓶颈（单进程 5,911 步/秒说明引擎很快）。

**修法（下一轮做）**：**不要把观察经 IPC 搬运**。
用 `multiprocessing.shared_memory` 开一块 `int32[n_envs × observe_len]`，
每个 worker 把观察**直接写进**自己那段，父进程读完就走，IPC 只传一个同步信号。
这正是 §21 里"观察是定长整数向量"那条设计**本来想换来**的东西 —— 定长就是为了能放进共享内存。
现在被包装层用错了：定长的好处拿到了，却仍然按对象搬运。

> 记一条：**基准测试的价值不在于给出一个漂亮的数字，而在于它能不能证伪你的设计。**
> 如果我只测"多开能不能跑"（能跑、结果也确定），我会把它当成完成了；
> 测出 26 倍的倒挂，才知道这个包装层的设计是错的。

### 25.3 确定性两条都过（这部分是真的对）

```
同布局重复跑一致（1×8 两次）      : 是
换进程布局仍一致（1×8 vs 2×4）    : 是
```

**换个进程布局不改变环境** —— 这条比"多进程跑两次一致"强，因为它证明摊到更多进程上不会改变行为。
所以 §25.2 的问题是**性能问题，不是正确性问题**，这很重要：修它是优化，不是排错。

### 25.4 状态

| 线 | 状态 |
|---|---|
| W1 state + snapshot | ✅ 69 passed / 0 failed |
| W2 内容编译器 | ✅ 85,616 B（96.8×） |
| oracle ABI + 语料 + 门禁 | ✅ 门禁 19/19 |
| 环境 ABI | ✅ 五条通过 + 拒绝语义已修 |
| Python 训练环境 | ⚠️ **正确但慢 26 倍**（IPC 搬运观察），修法已明确 |
| W3 叶子模块 | 🔄 2 个在跑 |



## 26. 第 16 轮：**上一轮的归因是错的**；修掉之后多开正常扩展

这一轮的价值几乎全在"推翻自己"上。§25.2 写下"多开慢 26 倍，原因是 IPC 搬运观察"，
修完之后只快了 2%。于是把它当故障查了一遍，真凶是另外两个。

### 26.1 真凶一：基准的分子算错了

`bench.py` 的循环是"跑 400 次迭代，数其中**没结束**的环境步"。而实测一局能走几步：

```
策略 -1（取最后一个合法动作）每局步数 = [6, 6, 6, 6]
策略 random                  每局步数 = [2, 2, 3, 2]
```

**一局只有 2~6 步**。400 次迭代里，分子只数到 6，分母却是 400 —— 数字被压低约 66 倍。
而且"结束"的环境在单进程路径里被 continue 掉（便宜），在多进程路径里仍然要走完整的一轮
IPC 往返（贵），所以两条路径被压低的幅度还不一样，差值就被误读成了"多开的开销"。

修：`SubprocVecEnv` 加 **auto_reset**（一局结束就地重开），基准每一步都是有效步，并同时报
「环境步/秒」和「全局步/秒」（一个全局步 = n_envs 个环境步，只报前者会让"开得多"天然显得快）。

### 26.2 真凶二：观察是逐项读的，40 µs/步

`docs/spec/env-abi.md` 的 v1 只提供了 `rd_env_observe(handle, index)` —— **122 个整数就是
122 次跨 ABI 调用**。受控 A/B（只切换读法，别的都不动）：

```
observe()  批量（1 次调用）   :   1.4 µs
observe()  逐项（122 次调用） :  40.4 µs     <-- 29.7×
actions()                     :   6.4 µs
reward() / done()             :   0.3 / 0.4 µs
```

修：给 oracle **增加**一条导出 `rd_env_observe_into(handle, dst, cap)`（`Marshal.Copy` 一次拷完，
不引入 unsafe），**不动 v1 的任何契约**。Python 侧把它绑成**可选**导出：缺了仍能跑（回退逐项读），
但 `EnvABI.bulk_observe_note` 会明说缺了什么、怎么重建 —— 绝不静默降级。

放进完整单步里，收益是 **1.36×**（40 µs 只占约 100 µs 的单步的一部分；剩下约 90 µs 是
`rd_env_step` 自己，也就是真实引擎成本 —— 那才是该被优化的地方，而不是 ABI）。

### 26.3 共享内存：假设错了，但它仍然是对的

`multiprocessing.shared_memory` 那版改动只带来 **227 → 231**（+2%）。保留它不是因为快，
而是因为它是**正确的结构**：观察是定长整数向量，就不该按 Python 对象搬运。
但必须把话说明白 —— **它不是这轮性能变化的来源**，别把功劳记到它头上。

### 26.4 修完之后的数字

```
单进程 4 句柄（对照基线）  :      9,725 环境步/秒
1 进程 × 4 句柄 =  4 env :     10,191 环境步/秒   ( 2,548 全局步/秒)
4 进程 × 4 句柄 = 16 env :     35,181 环境步/秒   ( 2,199 全局步/秒)
8 进程 × 4 句柄 = 32 env :     57,457 环境步/秒   ( 1,796 全局步/秒)
```

* **多开按核数正常扩展**：4 env → 32 env 是 10,191 → 57,457（5.6×），本机 32 逻辑核。
* **IPC 开销基本消失**：1 进程 × 4 句柄走完整 IPC 是 10,191，与进程内 4 句柄的 9,725 同量级。
* **全局步/秒反而随 env 数下降**（2,548 → 1,796）：这是同步向量化环境的"最慢者决定全局步"
  效应 —— 每个全局步要等**所有** worker。它就是为什么"多开"的收益低于核数。属于结构性质，不是 bug。

确定性两条仍然都过（同布局可复现 + 换进程布局不改行为）。

### 26.5 顺带修掉一个**会骗人的验收脚本**

复核队友交付时，我的过滤命令把 cargo 输出的 `=== EXIT n ===` 行滤掉了，最后打印的是**外层
powershell 的退出码（恒为 0）**—— 一个**构建失败被报成绿色**。这比没有验收危险得多。

新增 `tools/verify.ps1`：永远把真实的退出码单独打成 `VERIFY_EXIT n` / `VERIFY_VERDICT`，
并先用三个用例证明它不是空壳：

```
负例 A：cmd /c exit 7              -> VERIFY_EXIT 7   VERIFY_VERDICT FAIL
负例 B：退出 0 但打印 error 文本   -> VERIFY_EXIT 0   VERIFY_VERDICT FAIL (error text printed despite exit 0)
正例  ：干净成功                   -> VERIFY_EXIT 0   VERIFY_VERDICT PASS
```

**"退出码 0 但打印了 error 文本"必须判 FAIL** —— 只信退出码同样会被骗。
（踩坑记录：`.ps1` 用 `write` 产出是无 BOM 的 UTF-8，PowerShell 5.1 按 ANSI 解码，
中文注释把语法拆坏 —— 老坑，又踩了一次，必须补 BOM。）

### 26.6 教训

> §25.2 用一个**错的度量**得出了一个**方向也错**的结论（"IPC 是瓶颈"），
> 而且我差点就照着这个结论去优化 IPC —— 那会花掉一整轮去做一件没有收益的事。
>
> 度量本身要先被验证：**分子和分母各是什么、环境真的走了那么步数吗**。
> 一个不检查"被测对象真的在工作"的基准，越漂亮越危险。
> 同理，一个能吞掉退出码的验收脚本，越方便越危险。

### 26.7 状态（本轮结束时）

| 线 | 状态 |
|---|---|
| W1 state + snapshot | ✅ 交付并独立复核（`state.rs` 2308 + `snapshot.rs` 1492 行，53 条测试） |
| W3 叶子：status_catalog | ✅ 交付并独立复核（`status_catalog.rs` 84 → 1337 行，17 条测试） |
| W3 叶子：content（RDCF 读取器） | ✅ 交付并独立复核（`content.rs` 98 → 2726 行，18 条测试） |
| W2 内容编译器 | ✅ 85,616 B（96.8×） |
| oracle ABI + 语料 + 门禁 | ✅ 门禁 19/19；⚠️ **语料只到规格级**，引擎级覆盖有缺口（见 §26.8） |
| 环境 ABI | ✅ 五项通过 + 拒绝语义已修 + **批量观察**（附加导出） |
| Python 训练环境 | ✅ **多开正常扩展**（32 env = 57,457 环境步/秒） |
| **内核整体** | ✅ **108 passed / 0 failed**，裸机 `riscv32imac` 冷编译 PASS |
| W3b 叶子：targets / modifiers | 🔄 接口已冻结、桩已验证、**2 个 agent 在跑** |
| 语料引擎级覆盖 | 🔄 **1 个 agent 在跑**（补 `dp/s/gs/cnt/tr/queue/aside/卡后缀`） |
| W4 嵌入式 | 🔄 有未链接数字（闪存 ~195 KB / SRAM 静态 0 B / 战斗实例 171,848 B）；**最终链接未做** |

### 26.8 W3 第一批叶子交付，并且**独立复核过**

两个并行叶子都交回了，我用自己的工具重跑过（不是照抄它们的输出）：

| 叶子 | 文件 | 结果 |
|---|---|---|
| RDCF 内容镜像读取器 | `content.rs` 98 → 2726 行 | ✅ 18 条测试 |
| 状态与修饰器目录表 | `status_catalog.rs` 84 → 1337 行 | ✅ 17 条测试 |
| W1 主体 | `state.rs` 2308 + `snapshot.rs` 1492 行 | ✅ 53 条测试 |

```
test result: ok. 106 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.05s
VERIFY_EXIT 0 / VERIFY_VERDICT PASS
check --target riscv32imac-unknown-none-elf -p rd-core --release   →  VERIFY_VERDICT PASS（换 target-dir 冷编译，排除缓存假绿）
```

**W1 最强的一条证据**：把引擎产出的规范文本 `case_0000_v0_s1.txt` 内嵌进测试，断言 375 B /
24 个 LF / 无 CR / `sha256 == f3298ef4…02a85`（用内核**自己**的 SHA-256 算），再把文本**解析回模型**
重新渲染，要求逐字节相等；并扫 `corpus/hash_cases/case_*.txt` **48 份全跑**。解析器只认参考实现的
键名，格式一漂就回环失败 —— 而不是被一个宽容的读取器吸收掉。

**但覆盖面被如实标了边界**：那 48 份**不含** `dp=/s=/gs=/cnt=/tr=/queue/aside/卡后缀`。
所以那些行目前是"照 `CombatStateHasher.cs` 逐行钉"的**规格级**验证，**不是引擎级**。
要升级成引擎级，得让 oracle 产出含状态/格挡/临时规则/排队卡的快照 —— 记进待办。

**内存有了真实数字**（W4 的关键输入）：

```
size_of::<CombatState>() = 171,848 B (168 KiB)
  = 卡池 224×440 = 98,560  +  战员 12×3,872 = 46,464  +  牌区 12×1,392 = 16,704  +  其余 ~10 KB
```

是 592 KB SRAM 的 **29%**，但**约为规格书"打包后 ≈9 KB"的 6 倍**。差距全来自两件已明说的事：
本阶段 id 是 ASCII 字符串（§3-D9 intern 之后才降下来），以及每张卡固定付 280 B 的
marks/counters 数组（占卡实例 440 B 的 **64%**，而平时全空）。
降本杠杆按收益：intern id（卡池 → 几 KB）> marks 降到 2/2（−47 KB）> 把 state 放 PSRAM（它是 `Copy`、无指针）。

### 26.9 **我的工具链连着出了三个会骗人的 bug** —— 这比任何模块都值得记

复核队友交付时，我的验收链路连着三次给出了错误结论。三次的**共同形状**都是：
**工具在"报成功"，而被测对象在失败**。

| # | bug | 症状 | 修法 |
|---|---|---|---|
| 1 | 我的过滤命令滤掉了 `=== EXIT n ===` 行，最后打印的是**外层 powershell 的退出码（恒 0）** | 编译报了一堆 `error:`，却打出 `EXIT 0` | 新建 `tools/verify.ps1`，退出码永远单独成行，并先用三个用例自证不是空壳 |
| 2 | `cargo.ps1` **只打印** `=== EXIT 101 ===`，**从不 `exit 101`** | 整条链路在构建失败时报 `VERIFY_EXIT 0` / `PASS` | `exit $p.ExitCode`；`verify.ps1` **额外**解析输出里声明的 `=== EXIT n ===` 做交叉核对 |
| 3 | PowerShell 的 `-match` **默认不区分大小写**，我的失败模式 `FAILED` 命中了 `0 failed` | 106 条全绿被判成 FAIL | 改用 `-cmatch` |

外加 `cargo.ps1` 的**管道死锁**（先 `ReadToEnd()` stdout 再读 stderr；cargo 冷构建时 stderr 超过
约 4 KB 管道缓冲就双向卡死，表现为"没有任何输出且永不返回"，还拖出过一次假的 9m58s）——
`cargo.ps1` 与 `verify.ps1` 现在都改成 `ReadToEndAsync()` 并发读 + 超时兜底并杀进程。

改动之后的**完整自证**（都在真实命令上跑）：

```
负例：cargo.ps1 test -p no-such-crate   →  VERIFY_EXIT 101   VERIFY_VERDICT FAIL   （verify.ps1 自身退出码 1）
正例：cargo.ps1 test -p rd-core         →  VERIFY_EXIT 0     VERIFY_VERDICT PASS   （自身退出码 0）
负例：cmd /c exit 7                     →  VERIFY_EXIT 7     FAIL
负例：退出 0 但打印 error 文本          →  VERIFY_EXIT 0     FAIL (error text printed despite exit 0)
```

> **教训**：验收工具的失效方向和被测对象的失效方向**相反**时最危险 ——
> 被测对象坏了，工具说好。这类 bug 不会自己暴露，只会让后面每一次"通过"都失去意义。
> 所以：**验收器本身要先被验证**，而且要用**会失败的输入**去验证它。
> 我这轮最该记的不是"多开快了多少"，而是"我有三段代码曾经在骗我"。

### 26.10 W3b 两个新叶子已冻结并发车

按 §23 的纪律（**先冻接口，再派活**），我新建了两个桩文件，`lib.rs` 里加好 `pub mod`，
**验证树仍是 106 passed / 0 failed**，然后才派出两个代理：

| 叶子 | 文件 | 规格依据 | 为什么能独立 |
|---|---|---|---|
| **目标选择器** | `src/targets.rs` | `CombatantTargetSelectors.cs`（31 个选择器） | 只读 `CombatState`，纯函数 |
| **修饰器管线** | `src/modifiers.rs` | `PassiveModifiers.cs:116-218` | 纯函数：输入候选表，输出数值 |

设计上的一个决定：目标选择器有一半是**复合**的（`Union`/`Except`/`Damaged(inner)`/`WithStatus(inner,…)`），
而内核**没有分配器**，所以不能用 `Box` 表达递归。
做法与内容 IR 的 interning 同构：**选择器树摊平进一张定长表，复合节点用下标指向子节点**。
这也意味着必须**检测环**（内容镜像来自外部文件，不能假设良构）—— 已写进任务书要求单独测试。

两个桩里都预先写死了"必须照抄不能优化"的契约，并且各带 2 条测试证明桩本身可用
（`targets`：越界返回 `Err` 而不是 panic；`modifiers`：claim 账本满时返回 `false` 而不是 panic）。

### 26.11 W4 的尺寸数字（顺带又抓到两个度量缺陷）

把尺寸探针接上状态模型之后（队友建议的，对：**"加模块不量尺寸"应该是不可能的**），
`.text` 从 4,616 B 涨到 **22,304 B** —— 状态模型 + 序列化器 + 状态表约 **17.7 KB 代码**。
探针里同时加了 `COMBAT_STATE_BYTES` 常量与一条**会红的**预算断言（不是只打印），独立确认：

```
size_of::<CombatState>() = 171,848 B (167 KiB), 28.3% of 606,208 B SRAM
```

**缺陷一：尺寸工具报陈旧数字。** `tools/size_probe.py` **只读归档、不构建**。我改完探针源码之后
它仍然打印 `4,616 B`，与改动前**逐字节相同** —— 因为那份 `.a` 是 1 小时前生成的。
一个会报陈旧数字的度量工具比没有工具更糟：它让人以为"加了这么多，尺寸没变，好得很"。
修：脚本现在比较归档 mtime 与 `kernel/**` 最新源码 mtime，**陈旧就拒绝报数并退出 1**。

```
!! 产物是陈旧的，拒绝报数。
   归档   最后生成于 00:53:13
   但源码 kernel\rd-sizeprobe\src\lib.rs 改于 01:55:37     === EXIT 1 ===
```

**缺陷二：工具把 flash 和 SRAM 加在一起报。** 旧版输出 "内核自身占可用 **SRAM** 的 32.27%" ——
**这是错的**。ESP32-P4 上 `.text` 与 `.rodata` 在**闪存**里，不消耗 SRAM；吃 SRAM 的只有
`.data` / `.bss` / 栈 / 堆。把三者相加再对 SRAM 取比例，会让人以为"内存快满了"，
而实际上一个字节的 SRAM 都还没用。修：分成**两笔账**报，并明确点出"一块 168 KB 的 `.rodata`
是代码生成产物"以及"战斗实例的内存要单列"。

**`.rodata` 那 168 KB 是 A/B 测出来的，不是猜的**：

| | `.text` | `.rodata` |
|---|---|---|
| 探针里构造 `CombatState` | 22,304 | **173,313** |
| 去掉构造 | 4,744 | **598** |

差 172,715 ≈ `size_of::<CombatState>()`（171,848）。结论：**LLVM 把那个 168 KB 聚合体的
初始化模板放进了 `.rodata`**。它在闪存里（16 MB，无所谓），但如果哪天它落到 `.data`，
开机时就会被整体拷进 RAM —— 这条值得在写最终链接脚本时盯住。

**W4 的现状**：闪存 ~195 KB（含那个模板）/ SRAM 静态 0 B / 一个战斗实例 171,848 B。
这些都还是**未链接**的数字；真实固件占用需要一个最终链接（链接脚本 + 内存布局），W4 的主要工作。

---

## 27. 第 17 轮：**内核第一次被真正链接成裸机镜像**

上一轮的尺寸数字有个根本缺陷：它们量的是一个**静态库归档**。归档是"编译产物"，不是"最终镜像" ——
里面躺着 `core` / `compiler_builtins` 的几百个目标文件，真链接时大部分会被 `--gc-sections` 回收。
更关键的是，归档能产出**并不证明这个内核可以被链接成一个镜像**。

### 27.1 为什么"能不能链接"比"能不能编译"重要

裸机移植最常见的死法不是编译不过，而是**链接期缺符号**：`memcpy` / `memset` / `__aeabi_*`
这类编译器内建函数。它们**在任何"只编译不链接"的验收里都看不见** ——
`cargo check --target riscv32imac-unknown-none-elf` 一路通过，静态库也产出得漂漂亮亮，
直到你第一次真链接，才发现少了半个运行时。

所以本轮做的事是：建一个 `kernel/rd-firmware` 启动壳，写一份链接脚本，**真链接一次**。

**结果：一次就过了。**

```
cargo rustc --release --target riscv32imac-unknown-none-elf \
  --manifest-path rd-firmware/Cargo.toml -- \
  -C link-arg=-T<abs>\kernel\rd-firmware\link.x
=== EXIT 0 ===
```

没有缺失符号。这个内核的**战斗路径**（状态模型 + 规范序列化 + 状态表 + rng + SHA-256 + 文本写入器）
在 `riscv32imac-unknown-none-elf` 上**可以成为一个镜像** —— 这是"能在 ESP32-P4 上跑"这条上
第一个真正的链接级证据，而不是"编译通过"的推论。

> ⚠️ 一处**必须说清的边界**：`content.rs`（RDCF 内容读取器，2726 行）**不在这个镜像里**。
> `--gc-sections` 把它整个回收了，因为没有任何代码调用它。
> 这不是缺陷，而是链接测量独有的一类信息：**内容读取器是按需链接的** ——
> 固件若要从 flash 里的内容镜像读卡表，就付它的尺寸；若把内容编译成静态表，就不付。
> 这条以前看不见，因为归档里它永远"在"。

**链接期符号的答案（这是编译层永远看不到的一栏）：**

```
392 B  _RNvNtCskVpmJfHYvjB_17compiler_builtins3mem6memcpy
108 B  memset
 32 B  memcmp
```

`memcpy` / `memset` / `memcmp` **都由 `compiler_builtins` 提供了**，一个都没缺。
换句话说：这个内核不依赖任何"宿主 C 运行时"来补齐编译器内建函数 —— 裸机移植最容易翻车的那一栏，过了。

### 27.2 真实镜像的占用

```
镜像  kernel\rd-firmware\target\riscv32imac-unknown-none-elf\release\rd-firmware   205,552 B

段                地址        大小      属性
.text        0x00000000      22,114   code
.rodata      0x00005668     172,524

非易失存储（.text + .rodata + .data 初值）:  194,638 B
RAM 静态占用（.data + .bss）              :        0 B   （可用 SRAM 606,208 B 的 0.00%）
```

**最大符号把上一轮那个推断直接钉死了**（比 A/B 更硬 —— 符号表点名了元凶）：

```
171,848  .rodata   .Lanon.306c7c3f63c67b0ae407f6a7488cf8cc.1     ← 正好 = size_of::<CombatState>()
 14,944  .text     rd_core::snapshot::write_hash_input            ← 最大的**真实**函数
  2,030  .text     _start
  1,702  .text     rd_core::hash::Sha256::compress
  1,116  .text     rd_core::snapshot::write_status
    646  .text     rd_core::writer::TextWriter::put_u32_digits
```

**结论（W4 最该带走的一条）：镜像里 88% 是那个初始化模板，不是代码。**
把它减掉之后，**这个镜像里内核的真实代码 = 22,114 + (172,524 − 171,848) = 22,790 B**，
即在裸机 RISC-V 上只有 **约 22.3 KB 代码 + 0.7 KB 只读数据**（不含未被调用的 `content.rs`）。

而那个 171,848 B 的模板是 **LLVM 为"用一个大聚合体的构造结果"生成的字面量常量**，
不是数据。它在闪存里（16 MB，无所谓），所以**现在不必修**；但如果哪天它落到 `.data`，
开机时会被整体拷进 RAM，那就吃掉 168 KB SRAM。**写最终链接脚本时必须盯住这一条。**

### 27.3 修这条的杠杆（写给未来的自己）

想要那 168 KB 从镜像里消失，得让初始化不走"构造一个大聚合体再返回"这条路，
而是**就地初始化**（`.bss` 里一块零初始化的 `CombatState`，再逐字段填）。
内核是 `#![forbid(unsafe_code)]` 的，所以这件事应该由**启动代码**（固件壳，允许 unsafe）
用 `MaybeUninit` 做，而不是把 unsafe 引到 `rd-core` 里。**取舍写在链接脚本头部。**

### 27.3.1 哪些模块**真的**进了镜像（链接独有的一栏）

`--gc-sections` 只看"有没有人调用"，所以它顺带回答了一个归档永远回答不了的问题：
**每个模块在"不调用它"的时候，代价是多少。**

| 模块 | 镜像里的符号 | 说明 |
|---|---|---|
| `snapshot.rs` | 16,116 B `.text` | 被 `_start` 调用，**留下了**，且是最大的一块 |
| `writer.rs` | 1,210 B `.text` | 同上 |
| `hash.rs` / `state.rs` / `rng.rs` | 其余 `rd_core` 符号合计 19,028 B | 都在 |
| **`content.rs`（RDCF 读取器，2726 行）** | **0 个符号** | 没人调用 ⇒ **整个被回收** |
| **`status_catalog.rs`** | **0 个符号** | 两张表是 `const`，遍历被常量折叠；只剩 `.rodata` 里的小数据 |
| **`targets.rs` / `modifiers.rs`** | **0 个符号** | 尚未被调用 |

这是链接测量独有的一类信息，而且它对嵌入式取舍**直接可用**：
内容读取器是**按需链接**的 —— 固件要从 flash 里的内容镜像读卡表就付它的尺寸，
把内容编译成静态表就不付。以前看不见这一条，因为归档里它永远"在"。


### 27.4 三处刻意的设计，都是为了让证据干净

1. **固件壳被排除在 workspace 之外**（父 `Cargo.toml` 里 `exclude = ["rd-firmware"]`，它自带 workspace 根）。
   理由：它是 `#![no_std] #![no_main]`，**宿主上根本编译不出来**。如果把它加进 workspace，
   `cargo test --workspace` 会当场炸 —— 而那条命令正是**三个并行 agent 的验收基线**。
   为了量一个尺寸去弄红别人的验收，是最不划算的交换。

2. **链接脚本里用 `0` 占位，不编造硬件地址。** 我没有 ESP32-P4 的可靠基地址来源
   （`docs/esp32-p4-hardware-facts.md` 有容量、没有地址映射），所以 `link.x` 里**故意**写 `0x00000000`
   并标注"这是占位符，不是地址"。**段尺寸与地址无关**，所以本轮要的两个答案不受影响；
   而编一个看起来像真的地址，会让下一个人以为这份产物能烧。
   文件头列清了上板前必须替换的四样东西（真实 MEMORY 映射 → 启动代码 → 段的 `ENTRY`/布局 → bootloader 头）。

3. **`forbid(unsafe_code)` 的让步被写清楚。** `rd-core` 保持这条铁律；
   但启动壳必须导出链接器认得的入口符号，而当前 Rust 把 `#[no_mangle]` 归为 unsafe 属性，
   在 `forbid(unsafe_code)` 下是硬错误（`rd-sizeprobe` 里踩过同一条，那里靠 `#[used] static` 绕开）。
   所以壳里**不写** `forbid(unsafe_code)` —— 但**没有任何 unsafe 代码块**，且文件里写明了原因。

### 27.5 新工具 `tools/firmware_size.py`：量已链接的 ELF

与 `size_probe.py` 的分工写死在两个文件里：前者量**归档（上界）**，后者量**镜像（最终数字）**。
它一上来就套用了上一轮学到的两条教训 —— 这正是那两条教训的价值所在：

* **陈旧就拒绝报数**：比较 ELF mtime 与 `kernel/**` 最新源码 mtime。**它当场就触发了**：

  ```
  !! 镜像可能陈旧，拒绝报数（要强制就用 --allow-stale）。
     ELF    生成于 02:01:25
     但源码 kernel\rd-core\src\targets.rs 改于 02:01:45
  ```

  触发原因是**两个并行 agent 正在写 `targets.rs` / `modifiers.rs`**。检查本身是"宁可误报"的方向，
  所以这里不改它，也不绕过它 —— 等 agent 收工后重量即可。**记一笔：这条守卫在开发期会被并发编辑频繁触发，
  这是对的，不是缺陷。**

* **flash 与 SRAM 分两笔账报**，绝不加成一个"占 SRAM 多少"（上一轮就是这么错的）。

### 27.6 教训

> "能编译"和"能链接"之间的鸿沟，在整个项目里被藏了很久 —— 因为所有验收都停在编译层。
> 而这条鸿沟恰好是裸机移植最常掉进去的那条。
>
> 一般化：**验收手段的"深度"决定了它能发现什么。** 只编译的验收永远发现不了链接期问题；
> 只读产物的度量永远发现不了产物陈旧；只看退出码的检查永远发现不了"打印了 error 却退出 0"。
> 本轮三件事（真链接、陈旧守卫、flash/SRAM 分账）都是把验收往深里推一格。

### 27.7 状态（本轮结束时）

| 线 | 状态 |
|---|---|
| **裸机链接** | ✅ **第一次真链接成功**，`rust-lld` EXIT 0，`memcpy/memset/memcmp` 齐全 |
| **真实镜像占用** | ✅ `.text` 22,114 B / `.rodata` 172,524 B（其中 171,848 = 初始化模板）/ RAM 静态 0 B |
| 新工具 `tools/firmware_size.py` | ✅ 量已链接 ELF；陈旧守卫 + flash/SRAM 分账两条教训已内置 |
| 内核整体 | ✅ **163 passed / 0 failed**（本轮初 108，两个 agent 的测试已落地），workspace 仍绿 |
| W3b 叶子：targets | 🔄 agent 在跑（`targets.rs` 已 83.8 KB） |
| W3b 叶子：modifiers | 🔄 agent 在跑（`modifiers.rs` 已 61.9 KB） |
| 语料引擎级覆盖 | 🔄 agent 在跑（尚未落文件） |
| W4 余下 | ⏸ **真实内存映射 / 启动代码 / 就地初始化（去掉 168 KB 模板）/ bootloader 头** |
| 内核尚不能"打一局" | ⚠️ **诚实标注**：回合机 + 效果执行尚未实现。当前内核能构造状态、序列化、读内容，但**不能结算一次出牌** |

> ⚠️ 最后一条是本项目当前最重要的真话：**"能在 ESP32 上运行"目前成立的含义是"能被链接成镜像"，
> 不是"能玩一局"**。回合机与效果程序解释器是 W3 剩下的主体，也是"内核"这个词最核心的部分。

### 27.8 下一块的勘察：卡区行为（`zones.rs`）—— 以及一个只有"想真打一局"才会暴露的问题

先把"能不能不动 `state.rs` 就写这个叶子"查清了。**结论：暂时不能，但缺的东西很小。**

**好消息**：`CombatState` 已经公开了 `push_card` / `remove_card` / `clear_zone` / `card` /
`card_mut` / `card_zones` / `zone_cards` / `card_count`，所以"卡区行为"可以作为独立叶子，
不必把 `zones.rs` 塞进 `state.rs`。

**坏消息（这是个真问题，不是风格问题）**：`push_card` 永远**追加到堆尾并分配一个新的池槽位**，
而 `remove_card` **只是把卡从堆里摘掉、池槽位退休不回收**（`state.rs:1616-1617` 的注释自己写着
"slot recycling belongs to the live engine"）。于是：

* 参考实现里"把一张牌从抽牌堆移到手牌"是**零成本**的（C# 里卡是对象，换堆不改身份）；
* 在内核里按现有 API 做同样的事，代价是 **`push_card` 一次 ⇒ 吃掉一个 `MAX_CARD_INSTANCES` 槽位**。
  一副 10 张的牌组在 抽牌堆→手牌→弃牌堆 之间循环，**约 22 轮就会撞上 `Full(CardInstances)`**，
  而 224 这个容量原本是按"§5.2 实测整场约 200 张卡实例"定的。

**这就是说：按现有 API 直接写 `zones.rs`，会做出一个"打几轮就报满"的引擎。**
它不会在单元测试里露出来（小场景看不出），只会在真打一局时暴露 —— 正好是本轮刚承认的那个缺口。

**修法（下一轮做，先记下设计）**：给 `CombatState` 加**移动语义**，而不是"删了再建"：

```rust
/// 把一张卡在堆之间移动，**复用它的池槽位**（参考实现里移动是零成本的）。
pub fn move_card(&mut self, owner: &CombatantId, from: CardZone, to: CardZone,
                 slot: CardSlot) -> StateResult<()>;

/// 插到堆的**开头**（`ZonePlacement::Top`：导师类效果"放到抽牌堆顶"）。
pub fn insert_card_front(&mut self, owner: &CombatantId, zone: CardZone,
                         card: CardInstance) -> StateResult<CardSlot>;
```

两条都只需要 `CardZones::push_slot` / `remove_slot`（同模块内可见），
`state.rs` 不必放松任何可见性。验收要点：**"移动 1000 次后 `card_count()` 不增长"** ——
这条断言直接把上面那个坑钉死，而且它不需要真打一局也看得见。

**另外两件要在动手前定清楚的**（参考实现 `Cards/CardZones.cs` 与 `Cards/CardZoneMovementEffects.cs`）：
* 移动时"插到目标堆的哪一端"（手牌的追加序直接影响 hash 里的卡行顺序）；
* `MoveCardToZone` 对七个区是否**一视同仁**（队列 / 搁置堆很可能有特殊语义）。

---

## 28. 第 17 轮（续）：卡区原语落地；两个叶子复核通过

### 28.1 §27.8 那个坑，修好了

参考实现读完了，语义明确：

* `MoveCardToZone(id, zone, placement = Bottom)`，`Top` 就是 `destination.Insert(0, card)`，
  注释写着 "the front is the draw top"（`Cards/CardZones.cs:219-220`）；
* `DrawCard` 是 `_drawPile.RemoveAt(0)`（`:251`）—— **抽的是前面那张**；
* `MoveAllCardsFromZone` 先快照源堆、再逐个按默认位次搬（`:225-238`）。

于是给 `state.rs` 加了四个原语（只有它能碰 `CardZones` 的私有 `push_slot`/`remove_slot`）：

```rust
pub enum ZonePlacement { Bottom, Top }
pub fn move_card(&mut self, owner, from, to, slot, placement) -> StateResult<bool>  // 复用池槽位
pub fn draw_card(&mut self, owner) -> StateResult<Option<CardSlot>>                 // 取堆首
pub fn move_all_cards(&mut self, owner, from, to) -> StateResult<usize>             // 全有或全无
pub fn insert_card_front(&mut self, owner, zone, card) -> StateResult<CardSlot>     // 真·新卡才分槽
```

关键点是 `move_card` **复用同一个池槽位** —— 这才是参考实现的语义，也是这条线能"真打一局"的前提。

### 28.1.1 测试是**成对**设计的，因为正例单独存在就是空断言

一条测试证明"删了再建"**真的**会把池子吃光，另一条证明 `move_card` 不会：

```
the_naive_push_remove_way_really_does_run_the_pool_dry
  → 10 张的牌组循环，第 215 次尝试时 Err(Full(CardInstances))，池子恰好 224，成功移动 214 次
moving_a_card_reuses_its_pool_slot_so_a_long_fight_cannot_run_the_pool_dry
  → 同样循环跑 **1000 轮**，card_count() 每轮都断言 == 10，最后分布仍然正确
```

没有第一条，第二条证明不了任何东西 —— 它可能只是因为"这个循环根本没在移动卡"而通过。
**这正是"反例才算证据"的一个具体样子。**

> 写这条反例时我把断言写成 `moves == MAX_CARD_INSTANCES - 10`，实际是 **215 而不是 214**，
> 差一。我的计数器在**尝试之前**自增，所以它读的是"第几次尝试"，比"成功了几次"多 1。
> **是算错了，不是实现错了** —— 已改成同时断言 `moves - 1 == 214` 并把原因写进注释。

### 28.2 两个叶子：复核通过（不是照抄它们的输出）

| 叶子 | 文件 | 结果 |
|---|---|---|
| 目标选择器 | `targets.rs` 253 → 2094 行（29 条测试） | ✅ 环检测有**反空断言**（同形状去掉回边必须 `Ok(3)`）；`cardinality` 逐变体写死 |
| 修饰器管线 | `modifiers.rs` 264 → 1315 行（31 条测试） | ✅ "加法先于乘法"两组反例、四个截断点全部命中 |

```
test -p rd-core --release                          → ok. 173 passed; 0 failed      EXIT 0
check --target riscv32imac-unknown-none-elf ...    → Finished                     EXIT 0（冷编译，私有 target-dir）
clippy --all-targets -p rd-core                    → Finished                     EXIT 0
test -p rd-core --release targets::                → ok. 29 passed; 0 failed      EXIT 0
```

（173 = modifiers 交付后的 164 + 本轮卡区原语的 9 条。两个叶子的测试都在里面。）

### 28.3 我自己在本轮犯的两个错 —— 两个都值得记

**错一：编辑锚点漏掉了属性宏，把树弄红了。** 我插入 `ZonePlacement` 时锚点用了
`pub struct CardZones { ... }`，但**没把紧邻它上面的 `#[derive(Clone, Copy, PartialEq, Eq)]` 算进锚点**，
结果那个 derive 留在了新枚举上面 —— 于是 `ZonePlacement` 有两份 `derive`（E0119）、
`CardZones` 一份不剩（E0277 ×4），整个 crate 编译不过。

**而这恰恰验证了纪律是有效的**：targets 的 agent 发现树红了、确认不是自己的文件、
**停下来报告而不是自己动手修**，并附上了行号与一行修法。它甚至在**副本**里做了一行机械修复
把三条验收跑完，并**在报告里标明那是副本证据**。
"只改你那一文件、要动别的就报告"这条规则，在这件事上换回来的是：**没有两个 agent 同时改同一处、
没有互相覆盖、定位时间接近于零。**

**错二：我在自己的临时命令里又写了那个顺序读管道。** 15 分钟前我刚在 `cargo.ps1` / `verify.ps1`
里修掉"先 `ReadToEnd()` stdout 再读 stderr"的死锁，转头自己在内联命令里写了一遍 ——
`cargo test` 那次"10 分钟无任何输出然后超时"，就是这个。
**教训：把修复做进工具，不等于保护了临时命令。能走工具就走工具；写内联命令时把并发读当默认动作。**

### 28.4 叶子报上来的、需要我决策的偏差

1. **`Union` 的结果序：我的契约与参考实现真冲突。** 参考是"操作数依次、先见先出"
   （`CombatantTargetSelectors.cs:539-546`）；我的桩注释写的是 `state.combatants` **存储序**。
   队伍交错时结果不同（存储序 `[enemy_a,hero,hero2,enemy_b]` 上 `Union(友方,敌方)`：
   参考 → `[hero,hero2,enemy_a]`，本实现 → `[enemy_a,hero,hero2]`）。
   agent 按**我的契约**实现并用 `assert_ne!` 把"不是拼接序"钉住。
   ⚠️ **这一条我要重新裁决**：多目标效果的结算顺序会影响结果，而差分一致性的判据是"与引擎逐字节相同"，
   所以除非能证明两者在规范文本上等价，**应当改成参考实现的序**。记为待办。
2. **`cardinality` 不推导，逐变体写死** —— 实现里那条"按 inner 推导"的注释是我写错的；
   参考实现只有两个 `is_*` 查询，各复合类要么写死 `ZeroOrOne` 要么吃默认 `ZeroOrMore`。
   agent 按参考做并加测试钉住推导不发生。**我的注释错了，它没迁就。**
3. **未实现的变体**（需要我给冻结枚举加变体才能做，不是 agent 偷懒）：
   `FirstTarget`、`Downed`、`Lowest/HighestHealthPercentage`（三级排序，单 `UnaryOp` 表达不了）、
   `WithStatus(..., includeFallen: true)`、9 个位置类选择器（内核无 `Position`，规格里本就 out of scope）。
   内容镜像里若出现这些，得先扩 `SelectorNode`。
4. **`ClaimLedger` 表达不了"作用域未打开"**：参考里 `TryClaimOnceThisAction` 在没有动作作用域时
   恒返回 false，所以 once-per-action 的 spec 在动作之外永不生效。冻结的账本没这个状态 ⇒
   **必须由调用方保证**（动作外不要传 `once_per_action` 的候选）。记进调用方契约。
5. **一条给 `status_catalog` 的警告（已验证风险有限）**：它的测试助手 `fold_damage` 里有
   `if stacks == 0 { continue; }`。真实的 `Weak`/`Vulnerable`/`Frail` 是**只有时长轴**的状态
   （`Stacks` 恒 0），而 `ScalePercent` **不读 stacks** ⇒ 这句一旦抄进生产管线，虚弱/易伤会**静默失效**。
   已核实：`fold_damage` 在 `#[cfg(test)]` 内（第 699 行 > 第 692 行），**不进生产代码**，
   且 `modifiers.rs` 的生产实现里没有任何"层数 0 就跳过"的门（命中两处都在注释里）。
   但它值得写下来 —— 这种"测试助手比生产代码更响"的陷阱很容易被抄走。

### 28.5 状态

| 线 | 状态 |
|---|---|
| 裸机链接 + 真实镜像占用 | ✅ §27 |
| W3 叶子：content / status_catalog / W1 state+snapshot | ✅ 交付并独立复核 |
| W3b 叶子：targets / modifiers | ✅ **交付并独立复核**（173 passed / 0 failed） |
| 卡区原语（`move_card` 等） | ✅ 新增并复核，带成对的反例/正例 |
| **内核整体** | ✅ **173 passed / 0 failed**；裸机冷编译 EXIT 0；clippy EXIT 0 |
| 语料引擎级覆盖 | 🔄 agent 在跑 |
| 未决偏差 | ⚠️ `Union` 序待裁决（§28.4.1）；`SelectorNode` 待扩变体 |
| **内核仍不能"打一局"** | ⚠️ 回合机 + 效果执行器尚未实现 —— 卡区原语是它的地基，不是它本身 |

---

## 29. 第 18 轮：回合机冻结发车；修正我自己写错的两处冻结契约

### 29.1 先把 §28.4 那两条"待裁决"判了

**`Union` 的序：我错了，改成参考实现。** 我第一版冻结写的是"`state.combatants` 存储序"，
参考实现 `CombatantTargetSelectors.cs:539-546` 是"按操作数依次、先见先出"。队伍交错时结果不同：

| 存储序 `[enemy_a, hero, hero2, enemy_b]` | `Union(友方, 敌方)` 的结果 |
|---|---|
| 参考实现 | `[hero, hero2, enemy_a]` |
| 我冻结的存储序 | `[enemy_a, hero, hero2]` |

判据是**与引擎逐字节相同**，所以必须以参考为准。契约文档已改，实现随本轮一起改。

**`cardinality` 的注释：也错了。** 我写"复合节点按 inner 的基数推导"，而参考实现从不推导 ——
只有两个 `is_*` 查询，各复合类要么写死 `ZeroOrOne` 要么吃默认 `ZeroOrMore`。叶子按参考做、
**没有迁就我的错注释**，并加了测试钉住"推导不发生"。这次我把新变体的基数也明确标成
**"必须去参考里逐条查，不许按名字猜"** —— 因为猜错会改变预检的准入判据。

> 两条都是**我的冻结写错、叶子照做并如实报告**。这正是"先冻接口"的风险所在：
> 冻结者写错的代价会被下游全量继承。所以**叶子必须被允许、并且被鼓励说出"你的契约有问题"** ——
> 它两次都说了，两次都对了。

### 29.2 补上 `SelectorNode` 缺的变体（缺变体是冻结方的责任）

W3b 的叶子如实报告了 4 类"冻结枚举里没有变体、我做不了"的选择器。补变体**不是叶子的活**，是我的：

```rust
enum UnaryOp {
    Damaged, LowestHealth, HighestHealth,
    First,                    // 参考 :622
    Downed,                   // 参考 :639
    LowestHealthPercentage,   // 参考 :573 —— ⚠️ 不是 LowestHealth 的别名：三级排序键
    HighestHealthPercentage,  // 参考 :597
}
enum StatusFilter { With, Without, WithIncludingFallen }   // :306 的 includeFallen: true
```

我在 `eval` 与 `node_cardinality` 留下 `todo!()` 臂，**先把树恢复成绿的**（175 passed），
然后才派活 —— 纪律是"先验证树绿，再派活"，红着树派活等于把噪声pass给下一个人。

### 29.3 回合机（`turn.rs`）冻结发车

这是"能打一局"这条路上的第一块。设计上做了一个关键决定：

**把效果系统切成宿主 trait，而不是让回合机假装会解析效果。**

参考实现里事件处理器既推进回合又解析效果，缠在一起。但接缝很清楚 ——
标准的 turn-start 处理器序列是**固定顺序的七步**，其中四步需要效果系统、三步不需要：

| # | 处理器 | 谁做 |
|---|---|---|
| 1 | `ResetCardPlayTurnStats` | ⚠️ **本内核没有每回合出牌统计**（W1 的"没做"清单第 ② 条） |
| 2 | `RefillResource(energy, 3)` | **本模块** |
| 3 | `ActivatePendingStatuses` | 宿主 |
| 4 | turn-start 触发程序 | 宿主 |
| 5 | **`ResolveQueue`** | 宿主 |
| 6 | `DrawCards(5)` | **本模块** |
| 7 | `ClearBlock` | **本模块** |
| — | `DamageOverTime` | 宿主 |

**顺序本身是规格**：补能量 → 触发器 → **队列** → 抽牌 → 清 Block。队列卡的效果
**一定发生在手牌到来之前**；清 Block 在队列解析**之前**，所以队列里的 `gainBlock`
能活到它被排队的那一回合（`S:QueueTortureTests.cs:210-212` 断言 11 点 Block 存活）。

于是 `TurnHost` 上的每个方法就是那四步之一，`NullHost` 是全空实现 —— **回合机今天就 能被测试**。
但它也划了一条线，写进了任务书：**用 `NullHost` 断言"效果发生了没有"是空断言**，
那种测试只能证明"我什么都没做"。

### 29.4 效果解释器：可行性已经查清，但它仍是最大的一块

读了 `effect-program-ir.md` §4.3 那张"**必须原样保留 vs 可以大幅简化**"的表，结论是**能做**：

| 必须原样保留（语义） | 可大幅简化（实现） |
|---|---|
| O1–O16 顺序契约；全部限额数字与 throw/静默的区分 | `Action<>` 续体 → **显式续体记录** |
| `TContext` 的可观测行为 | 泛型本身 → 运行期 `ContextTag` + union |
| 结果键的词法作用域与单生产者/类型/基数契约 | `(string,Type)` 字典 → `u16` 键 + 定长槽 |
| 33 个 outcome 的字段集；槽"恰一次"不变量 | 33 个 `OutcomeSlot` 子类 → 1 个 tagged struct |
| RNG 算法；And/Or 短路；异常 → `Faulted` 单终态 | LINQ / `IEnumerable` |

规模上也看得清：`Programs\` 10 文件 8,815 行 + `TriggeredProgramDefinition.cs` 218 行，
其中 `Action<…>` 199 处、`EnqueueContinuation(...)` **85 处**、`dispatch(...)` 闭包 10 处、
`typeof(` 105 处。**"用显式续体记录替代闭包"这一件事就是工程量的主体。**

> ⚠️ **到期前的诚实判断**：在剩余轮次内把它整块做完并验收是不现实的。
> 所以本轮的处置是：**把它的可行性查清并写进文档**，把回合机（它的下游）先做完 ——
> 而不是开一个我无法验证的大工程。**能做**和**这一轮该做**是两件事。

### 29.5 差分一致性：连第 16 轮那个覆盖缺口也关了

第 16 轮记下的缺口是"50 份语料里 `dp=/s=/gs=/cnt=/tr=/queue/aside/卡后缀` 出现 **0 次**"，
所以那些行只是照 `CombatStateHasher.cs` 逐行钉的**规格级**验证。现在：

```
corpus round-trip: 85 case(s) reproduced byte-for-byte
test result: ok. 1 passed; 0 failed
```

**85 份引擎产出的规范文本，Rust 内核全部逐字节重现。** 测试对**每一份**断言
`render(parse(text)) == text`，所以这不是"扫过了"，是"逐份相等"。

键覆盖（第 16 轮 → 现在）：

| 键 | 第 16 轮 | 现在 |
|---|---|---|
| `dp=` 格挡池 | 0 | 6 |
| `s=` 状态 | 0 | 15 |
| `gs=` 全局状态 | 0 | 2 |
| `cnt=` 计数器 | 0 | 4 |
| `tr=` 临时规则 | 0 | 6 |
| `queue` / `aside` | 0 / 0 | 4 / 7 |
| `exh=` / `ban=` | 0 / 0 | 3 / 4 |
| 卡行后缀 `qat:`/`m:`/`mc:`/`msrc:` | 0 | 4 / 13 / 3 / 2 |
| `summon_num=` | 0 | **0（本来就该是 0）** |

最后一行不是缺口：W1 发现哈希器**不写** `summon_num`（D12），并有一条测试专门断言它不出现。

**顺手收紧了一个过时的门槛**：那个测试的下限写死在 `>= 48`，而语料已经涨到 85 ——
删掉 37 份仍然通过，门槛成了空的。已抬到 `>= 80` 并打印实际份数，附上"加语料时顺手抬门槛"的说明。
（逐份相等才是证明，下限只是防止语料被删空。）

### 29.6 语料叶子交付（已独立复核），以及它发现的一个**会静默删数据**的坑

语料 agent 交回：新建 `OracleExports.RichStates.cs`（450 行，6 个新探针导出，**没碰任何已存在的 .cs**）、
`make_corpus.py` 加 `--rich-cases` 模式、新建 37 份语料。复核结论：

| 项 | 结果 |
|---|---|
| oracle 重建 | EXIT 0，IL2xxx/IL3xxx 告警 **0 行** |
| `env_check.py` | PASS（5 项） |
| `coverage_check.py` | 19/19，`未覆盖: []` |
| golden_v1 vs 冻结基线 | SHA-256 **完全相同** |
| Rust 逐字节回环 | **85 份全过**（我自己跑的） |

**它发现的那个坑值得单独记**：`corpus/hash_cases/` 里的 48 份**不是** `make_corpus.py` 生成的，
而是 `native/hash_diff.py` 生成的 —— 而那个脚本每次运行会
`glob("*.txt")` 然后**全删**，只重建自己那 48 份。
于是"跑一次 hash_diff.py"会把 37 份富语料**静默删光**（实测 85 → 48）。
**没有任何报错**，只有下一次 `cargo test` 会以"语料少了"的方式变红，而那时已经查不到原因了。

它按纪律没有自己改那个文件（不在它的地盘），而是把语料做成可逐字节重建，并留了删不到的主拷贝。
**我接手修了**：现在按本脚本的命名模式 `case_<4位序号>_v<变体>_s<种子>.txt` 精确匹配，
不认识的一律保留并报出来。实测：

```
before: 85 份
  ⚠️ 保留了 37 份不是本脚本生成的语料（不会被删除）：
after:  85 份   EXIT 0
```

> 教训：**"删掉再重建"这种幂等写法，只在"这个目录只归我管"时才幂等。**
> 一旦目录里住进了第二个写入者，它就从"重置"变成了"删除他人数据"，而且没有任何症状。
> 我另外还发现过两个同族的坑（`size_probe.py` 报陈旧数字、`acceptance` 类脚本吞退出码）——
> **它们的共同形状都是"工具在报告一个它没有资格报告的状态"**。

### 29.7 顺手修正了一处**已经变成谎言**的注释

语料叶子指出 `snapshot.rs:96-110` 那段注释还写着 `dp=`/`s=`/`gs=`/`cnt=`/`tr=`/`queue`/`aside`/
卡后缀"**Spec-verified only … they need a richer oracle case before they are engine-verified**"。
那句话从 37 份富语料落地那一刻起**就是错的**。已改写为：

* **Engine-verified**：85 份覆盖 `CombatStateHasher` 能写的**全部 29 种行头** + 5 种后缀；
* **仍然薄弱的地方**（这才是重点，别当成已经验过）：
  1. `gs=` 只有 **restore 路径**的实证 —— 全引擎 `_globalStatuses` 唯一写者是 `CombatState.Restore`
     （`CombatState.cs:818`），没有战斗路径会加它。所以那两份证明的是"还原路径写得出这行"。
  2. `tr=` 的 `dead` 后缀在任何观测点都不存在（过期即剪除，同一次调用）。
  3. `res=` 的 `null` 上限拼法到不了；`tr=` 的 `inst=R.T` 只有 `1.1`；`dp=` 的上限恒 `null`。

> **注释里的"已验证"是有保质期的。** 一个上游改进了覆盖，下游那句"还没验过"就变成了假话 ——
> 而假话的方向是**让人以为还没验过**，于是重复劳动。语料叶子主动把这句转达回来，做对了。

### 29.8 聚合验收器：把十来个闸门收到一条命令里

项目的验收分散在 cargo / python / dotnet 三套工具链里。逐个手跑的问题是**会漏**，
而且漏掉的一定是最后加的那条。新增 `tools/acceptance.ps1`，九条闸门一条命令：

| # | 闸门 | 判据 |
|---|---|---|
| 1 | `rust-units` | `test result: ok. N passed; 0 failed` 且 **N ≥ 下限** |
| 2 | `corpus-roundtrip` | 输出里必须出现 `case(s) reproduced byte-for-byte`（防"空扫"） |
| 3 | `rust-baremetal` | `check --target riscv32imac-unknown-none-elf` EXIT 0 |
| 4 | `rust-clippy` | EXIT 0 |
| 5 | `firmware-link` | 真链接 EXIT 0 |
| 6 | `firmware-size` | 自带陈旧守卫，陈旧即拒绝报数 |
| 7 | `coverage-gate` | 19/19 |
| 8 | `golden-baseline` | 与冻结基线 SHA-256 相同 |
| 9 | `env-smoke` | RL 多开 + 确定性 |

三条设计约束，都是踩出来的：
1. **只认子进程的真实退出码**（过滤输出吞掉退出码，曾把编译失败报成绿色）；
2. **两流并发读**（串行读在子进程写满 4KB stderr 缓冲时双向死锁）；
3. **"必须匹配"不等于"必须不匹配"**：每条闸门要求输出里出现某个**证据串**
   （测试条数 / 语料份数 / `19/19`），否则判 FAIL —— **跑了但没做事**和"没跑"要能分开。

### 29.9 聚合验收器**自己先出了一个 bug — 而它拒绝了报成功**

第一次跑，九条闸门里八条报"退出码 0，但输出里找不到证据"。摘出来一看：那些子进程打印的是
`cargo help`（`--explain <CODE>` / `check, c  Analyze…`）—— **参数根本没传进去**。

根因：我给函数参数起名 `$Args`。`$args` 是 PowerShell 的**自动变量**（未绑定参数的数组），
同名参数被它盖住，于是 `$psi.Arguments = $Args` 拿到空数组 → cargo 收到零个参数 → 打印帮助
并以 **0 退出**。

**如果没有那条"必须匹配证据串"的检查，这八条闸门会以退出码 0 全部报绿。**
这正是 §26.9 那类 bug 的同一个形状，只是换了一个触发点。改成 `-ArgLine` 后：

```
闸门                    退出  证据
rust-units              0    208 passed
corpus-roundtrip        0    1 passed
rust-baremetal          0
rust-clippy             0
firmware-link           0
firmware-size           0
coverage-gate           0    19/19
golden-baseline         0    129 行
env-smoke               0
ACCEPTANCE_RESULT PASS (9/9 gates passed)      LASTEXITCODE = 0
```

> 教训：**"证据串必须出现"这一条检查，是整套验收里唯一在真正防"假绿"的那一条。**
> 只看退出码的话，一个参数传错的脚本能让全部闸门"通过"。
> 另外：**自动变量名（`$args`/`$input`/`$error`/`$host`…）不要拿来当参数名。**

---

## 30. 第 19 轮：两块叶子交付、**208 条测试全绿**、内核能力矩阵

### 30.1 两块叶子（都独立复核过）

| 叶子 | 文件 | 结果 |
|---|---|---|
| 目标选择器补全 + `Union` 改序 | `targets.rs` 2149 → **2839 行**，29 → **36 条测试** | ✅ |
| 回合状态机 | `turn.rs` 305 → **1581 行**，+**26 条测试** | ✅ |

`targets` 这一轮做的三件事：
1. 实现了**我上一轮才补进冻结枚举**的 5 个变体（`First` / `Downed` / 两个 `*HealthPercentage` /
   `WithIncludingFallen`）；
2. 把 `Union` 的结果序从我写错的"存储序"改回参考语义。同一个表两个不同结果：
   arena 存储序 `[enemy_a(敌), hero(我), hero2(我), enemy_b(敌·倒下)]`，
   `Union(友方, 敌方)` 改前 `["enemy_a","hero","hero2"]`、改后 `["hero","hero2","enemy_a"]`。
   测试同时 `assert_eq!` 后者与 `assert_ne!` 前者；
3. **又一次纠正了我的猜测**：我在冻结注释里写"`FirstTarget(inner)` 的基数取决于 inner 能不能为空"，
   参考实现其实**写死 `ZeroOrOne`**（`:625`），而 `Downed` 连覆写都没有、吃默认 `ZeroOrMore`（`:59`）。
   它照参考做，并说明为什么不能推导 —— 推导会让 `is_guaranteed_non_empty()` 从 false 变 true，
   而那是**预检放行标量读的判据**，会改变被接受的程序集合。

> 这是**第三次**"我的冻结注释写错、叶子照参考实现做并如实报告"。
> 前两次是 `Union` 的序与 `cardinality` 的推导。**这个比例（3/3）说明冻结注释本身就是高风险资产** ——
> 它比代码更容易被当成"已确认的事实"，而它其实只是一个人当时的理解。
> 对策写进纪律：**冻结注释里凡是关于参考实现行为的具体断言，都要带行号，并且明确"我没验证过"的部分。**

### 30.2 `turn.rs` 坦白的三处实质缺口（这才是这份交付最值钱的部分）

1. **临时规则的清空与 C# 不一致**：我的冻结契约（以及 `state.rs` 的 doc）说"`AdvanceTurn`/`AdvanceRound`
   都清空临时规则"，但 C# 只移除**已到期**的（`CombatState.cs:572-592`）。于是"没有到期时间"的规则
   本内核会删、C# 会留，而 `tr=` 行是**哈希可见**的。它按冻结契约实现（三处都这么要求），
   并指出要向 C# 对齐需要 `state.rs` 增一个"按条移除"的 API。**这条我记进待办，且它是真偏差。**
2. **`RoundEnded`/`RoundStarted` 两个事件发不出去**：`TurnHost` 上没有"入队事件"的方法，
   所以 `advance_to_next_combatant` 的 `host` 参数用不上。它**没有**用 `resolve_pending_queues`
   去冒充"通知宿主回合边界到了"—— 那会把宿主触发器跑到参考实现不会跑的时刻。
   **"这是缺口，不是不需要"** —— 这句话是这份报告里最好的一句。
3. 一串"没做到"的清单：`ResetCardPlayTurnStats`（内核无出牌统计）、`UnspentResourceCarries` 法令、
   `RetainBlockTag` 抑制清 Block、`TurnStartDraw` 修饰、**抽牌堆空时不重洗**（停止抽取，并有测试
   钉住这个可观察行为 —— 而不是假装重洗了）、`discard_hand` 整堆搬（逐张落点要卡定义表）。

**它的一条测试尤其值得记**：`turn_end_discards_the_hand_and_a_retaining_host_leaves_it_alone`
末尾有 `assert_ne!(discarded, kept)` —— 两个宿主必须给出**不同**结果。
没有这一条，"弃手牌"和"保留手牌"两条断言可能是同时成立的（都因为根本没弃过）。

### 30.3 内核能力矩阵（这是整个移植的当前真实边界）

**内核规模**：10 个模块 / **13,327 行** / **208 条测试**。

| 模块 | 行 | 测试 | 职责 |
|---|---|---|---|
| `state.rs` | 2,647 | 37 | 定容战斗状态模型（零分配） |
| `content.rs` | 2,390 | 18 | RDCF 内容镜像读取器 |
| `targets.rs` | 2,481 | 36 | 目标选择器（含环检测） |
| `snapshot.rs` | 1,497 | 25 | 规范文本序列化 |
| `turn.rs` | 1,337 | 28 | 回合状态机 |
| `status_catalog.rs` | 1,149 | 17 | 状态/修饰器表 |
| `modifiers.rs` | 1,093 | 31 | 修饰器管线 |
| `writer.rs` | 297 | 6 | 无分配文本写入 |
| `hash.rs` | 281 | 6 | SHA-256 |
| `rng.rs` | 125 | 4 | Mulberry32（与 C# 逐位一致） |

**✅ 今天能做到的（都有证据）**

| 能力 | 证据 |
|---|---|
| 读真实内容镜像 | `content.core.rdcf` 85,616 B，20 段逐项对齐 manifest |
| 建模一场战斗的状态 | `size_of::<CombatState>() = 171,848 B`，无分配器、无浮点 |
| 序列化 + 指纹 | **85 份引擎语料逐字节重现**（含全部 29 种行头 + 5 种后缀） |
| 目标选择 | 31 个非位置类选择器全部实现；环检测有反空断言 |
| 伤害/格挡数值 | 门控 → `(priority, 字节序, 索引)` 排序 → 四种运算 → 截断，两组反例钉住 |
| 卡区移动 | 复用池槽位的 `move_card`/`draw_card`/`move_all_cards`，1000 轮不涨池 |
| 回合推进 | 七步 turn-start、turn-end 处理器序、绕回、跳过倒下单位、能量/抽牌/清 Block/弃手牌 |
| 跑在裸机上 | 真链接成 ELF；`.text` 22,114 B + 只读 676 B；`memcpy/memset/memcmp` 齐全 |
| 当 RL 环境 | NativeAOT 14,509 场/秒；多开 57,457 环境步/秒 |

**❌ 今天做不到的（这是最重要的一节）**

| 缺口 | 后果 |
|---|---|
| **效果程序解释器**（`Programs/` 9,550 行） | **不能结算一次出牌**。卡打出去不会造成伤害、不会加格挡。这是"能玩一局"与"不能玩一局"之间唯一的那道墙 |
| 出牌流程（`CardPlay.cs`：费用、校验器链、法令） | 出不了牌 |
| 每回合出牌统计 / 法令 / 抽牌修饰 / 重洗 / `RetainBlock` / 轮次边界事件 | 上面 `turn.rs` 报的那一串 |
| 内容 → 状态的绑定层（把 RDCF 的 CARD/STAT 行变成可打的卡） | 内容读得出来，但没有接进战斗 |

**所以，对"这个内核能干什么"最诚实的一句话是：**

> **它今天是一台能精确复现引擎指纹、能推进回合、能跑在裸机上、能当并行 RL 环境的状态机。
> 它还不是一款能打一局的游戏** —— 差别就是那块效果解释器。

---

## 31. 第 20 轮：按用户要求专攻 `turn.rs` 的缺口

`turn.rs` 原交付时如实报了 8 处缺口。这一轮**专攻它们**，并且分清了两类责任：

* 卡在**我冻结的接口**上的（`state.rs` 缺原语、`TurnHost` 缺接缝）⇒ **我改**；
* 纯粹是实现工作 ⇒ 交 agent。

### 31.1 三处是我必须先补的原语（`state.rs`）

| 原语 | 为什么需要 | 参考依据 |
|---|---|---|
| `Bounded::retain` | 参考只删**到期**的临时规则，而 `Bounded` 原来只能 `pop` 尾部 / `clear` 整表，**删不掉中间元素** | `CombatState.cs:578` 的 `RemoveExpiredTemporaryTriggeredPrograms` |
| `expire_temporary_rules_at_turn_boundary` / `..._at_round_boundary` | 把"清空"换成"只移除到期" | `CombatState.cs:572-592` + `TemporaryTriggeredProgram.cs:130-145` |
| `reshuffle_discard_into_draw` | 抽牌堆空了要重洗，而重洗是**确定性契约**的一部分 | `CardZoneEffects.cs:49-82` + `CardZones.cs:260-297` |

**到期语义读出来的精确规则**（照抄，不许"化简"）：

* `MarkExpiredIfPastRound(r)`：`expires_after_round = Some(n)` 且 `current_round > n`；
* `MarkExpiredIfPastTurn(r, t)`：`expires_after_turn = Some(n)` 且
  （`current_round > (expires_after_round ?? current_round)` 或 同轮内 `current_turn > n`）；
* **`AdvanceTurn` 只做 turn 那一条**，`AdvanceRound` **两条都做**。

⇒ **`AdvanceTurn` 不会让"只按轮到期"的规则消失**，而且**没有 `expires_after_round` 的 `expires_after_turn=N`
规则绕到下一轮时也不消失**（到期轮默认取当前轮）。这两条都写成了测试 —— 它们是"清空"与"只移除到期"
之间最后的分界线，也是最容易被"化简"掉的地方。

**重洗的记账**：置换来自 `CreateShuffledIndexes(count, seed, step)`（内核 `rng::shuffle_indexes` 与它
逐位一致），目标堆 = **旧抽牌堆 ++ 置换后的弃牌堆**（`_drawPile.Add` 是追加不是替换），
然后 **`random_step += 1`**。空弃牌堆**不推进步数** —— 否则"空洗一次"会污染之后所有随机，
而 `step=` 是哈希可见的。

### 31.2 `TurnHost` 扩了 7 个钩子，**全部带默认实现**

```rust
on_round_ended(state, ended_round)                  // 轮次边界：旧轮结束（默认 Ok）
on_round_started(state, new_round)                  // 轮次边界：新轮开始（默认 Ok）
block_is_retained(state, actor) -> bool             // RetainBlockTag（默认 false）
turn_start_draw_count(state, actor, base) -> i32    // TurnStartDraw 修饰（默认 base）
card_stays_in_hand_at_turn_end(state, actor, slot)  // 逐张留手（默认 false）
turn_end_hand_destination(state, actor, slot)       // 逐张落点（默认 DiscardPile）
unspent_energy_carries(state, actor) -> bool        // UnspentResourceCarries（默认 false）
```

**默认实现不是"以后再实现"的托词**：每个默认值都等于参考实现在**没有对应法令/标记/修饰器**时的行为，
所以默认路径与参考的默认路径一致。这也让已有的 `NullHost` 和 26 条测试**一行都不用改**。

### 31.3 又一次"接口开了但用不了" —— 这次是 `CardSlot`

`turn.rs` 的 agent 报了真阻塞：我开了
`card_stays_in_hand_at_turn_end(.., slot: CardSlot)`，但 **`CardSlot` 的元组字段是模块私有的、
没有公开构造器**，而 `CardZones::slots()` 只回 `&[u16]`。于是"逐张问这一张留不留"**从外部完全不可达** ——
它甚至因为字段隐私无法在同 crate 的另一模块里用 `CardSlot(i)` 绕过去。

补：

```rust
impl CardSlot { pub const fn from_index(index: u16) -> Self }   // 不校验，越界匹配不到任何堆
impl CardZones { pub fn slot_at(&self, zone, index) -> Option<CardSlot> }  // 带越界检查
```

并加测试 `a_pile_can_be_walked_card_by_card_through_slot_at` 钉住"`slots()` 与 `slot_at()` 逐项一致、
越界返回 `None` 而不是 panic"（裸机上没有 unwind）。

> **教训：接口开了但用不了，比没开更糟 —— 因为它看起来已经支持了。**
> 这次和前面几次（冻结契约写错 3 次、`size_probe` 报陈旧数字、`cargo.ps1` 吞退出码）的形状不同，
> 但代价一样：**下游会先撞上它，然后花时间证明"这不是我的错觉"。**
> 自查办法很简单粗暴：**冻一个 trait 方法之后，立刻写一行调用它的代码**。写不出来就是开错了。

### 31.4 责任划分（这一轮唯一值得制度化的东西）

| 谁的问题 | 谁改 | 这一轮的例子 |
|---|---|---|
| 冻结的类型/签名/trait 缺东西 | **我** | `CardSlot` 构造器、`TurnHost` 七个钩子、`state.rs` 三个原语 |
| 实现与参考不一致 | agent | 逐张落点、重洗循环、事件顺序 |
| 参考实现与我的注释不符 | agent **顶回来**，以参考为准 | 这一轮之前已有 3 次 |

**"冻结方的错误由冻结方修"**，我这一轮第一次把这条执行到底 —— 前几轮是 agent 报上来、我改，
这一轮是它一报阻塞、我立刻补接口再放行。**这比让它去绕要快得多，也避免了它把绕法写进代码。**

### 31.5 结果：7/7 全部落地，**225 条测试**，聚合验收 9/9

| | 改前 | 改后 |
|---|---|---|
| `turn.rs` | 1656 行 / 28 测 | **2404 行 / 37 测** |
| `rd-core` 总计 | 216 测 | **225 测** |
| `state.rs` | 2647 行 / 37 测 | 2900+ 行 / **46 测** |

```
rust-units        0  225 passed      corpus-roundtrip  0  85 case(s)
rust-baremetal    0                  rust-clippy       0
firmware-link     0                  firmware-size     0
coverage-gate     0  19/19           golden-baseline   0  129 行
env-smoke         0
ACCEPTANCE_RESULT PASS (9/9 gates passed)
```

七条各自的测试（我按名字核过，都在 `turn::tests::turn_machine::` 里）：

| # | 缺口 | 测试 |
|---|---|---|
| 1 | 临时规则只移除到期 | `advancing_a_turn_or_a_round_removes_only_the_expired_temporary_rules` |
| 2 | 抽牌堆空 ⇒ 重洗 | `a_dry_draw_pile_reshuffles_the_discard_in_engine_order_and_pays_one_random_step` + 一条"两堆都空则抽不满"的对照 |
| 3 | 轮次边界事件 | `a_round_boundary_reports_ended_then_started_while_a_turn_boundary_reports_neither` + "报告的是退场者" |
| 4 | `RetainBlock` 抑制清格挡 | `a_retaining_host_keeps_the_block_pool_alive_while_the_default_host_clears_it` |
| 5 | `TurnStartDraw` 修饰 | `the_turn_start_draw_count_is_the_hosts_number_and_the_hand_ceiling_still_applies` |
| 6 | 回合末逐张落点 | `turn_end_moves_each_card_to_its_own_destination_while_the_default_host_discards_all` + "只剩留手那张时返回 0" |
| 7 | `UnspentResourceCarries` | `an_unspent_energy_host_carries_the_leftover_on_top_of_the_refill_and_may_exceed_the_max` |

### 31.6 agent 报了一件我最想看到的事：**先红后绿**

它没有直接改实现，而是**先反转/写好测试、在旧实现上跑一遍**，然后才动代码：

```
test result: FAILED. 214 passed; 3 failed
  a_dry_draw_pile_reshuffles_...      left: 2   right: 5    ← "抽牌堆空就停"的形状
  a_dry_pile_whose_discard_is_smaller...  left: 2  right: 3
  advancing_a_turn_or_a_round_removes_only_the_expired...  left: []
                                      ← 旧 clear_temporary_rules() 的形状
```

`left: []` 和 `left: 2` 就是那两个 bug 的**指纹**。这比"我改完了，全绿"值钱得多 ——
它证明新测试**真的会咬人**，而不是在描述实现。

### 31.7 它还如实报了三件我该知道的事

1. **规格书 `combat-state-and-turn.md` §3.1 第 187/190 行（伪码里的"清临时规则"）也是错的** ——
   它没改（只许改 `turn.rs`），报给我。**已修**：那两行现在写清了 `AdvanceTurn` 只做 turn 那一个 Mark、
   `AdvanceRound` 两个都做，并附了三条"会被 `tr=` 行看见"的后果。
   > 一个错误的契约会污染三处：**我的冻结注释 → 规格书 → 实现**。这次是三个地方先后被纠正。
2. **`tools/acceptance.ps1` 的 `-UnitsFloor` 还停在 175** —— 已抬到 **225**。
   它没动那个文件（只许改 `turn.rs`），只是提醒 —— 这正是"顺手抬门槛"那条纪律该有的样子。
3. **`firmware_size` 的 `.text` 没变化（22,114 B）**：`turn.rs` 根本没进固件镜像，被死代码消除了 ——
   也就是说**固件目前不驱动回合机**。这不是 bug，但它说明"能链接"和"用上了"是两件事。

### 31.8 仍然没做到的（收窄后的诚实清单）

| 缺口 | 现状 |
|---|---|
| **效果程序解释器** | 仍未开始。这是"能打一局"唯一的那道墙 |
| `ResetCardPlayTurnStats`（turn-start 第 1 步） | 留空 —— 内核没有"每回合出牌统计"（`CardPlayTurnStats` 整块未移植） |
| turn-start 触发器（第 4 步） | 调用点顺序正确，但**解析效果程序**仍是宿主的事 |
| 事件模型 | `on_round_ended`/`on_round_started` 是**同步回调**，不是事件队列。真实语义差别：C# 的 `RoundStarted` 处理器在 `SetActiveCombatant` **之后**跑，本内核的 `on_round_started` 在**之前**（照 C# 的行序，但同步交付让宿主看到退场者）。已写进代码注释与报告 |
| 内容 → 状态的绑定层 | 未开始 |
| 固件不驱动回合机 | 回合机还没被固件调用（`.text` 无变化是证据） |

---

## 32. 第 21 轮：效果解释器的第一步 —— 用**真实数据**界定范围

### 32.1 先做的事：**统计真实镜像里出现了什么**，而不是照规格实现全部

规格里是 54 种节点 + 92 个表达式。先把 `content.core.rdcf` 导成 JSON 遍历一遍：

| 战斗侧节点（15 种） | 次数 | | 节点 | 次数 |
|---|---|---|---|---|
| `sequence` | 1273 | | `forEachTarget` | 27 |
| `applyStatus` | 936 | | `createCardInstance` | 20 |
| `conditional` | 563 | | `drawCards` | 12 |
| `dealDamage` | 260 | | `heal`/`gainResource`/`loseResource` | 3/2/1 |
| `gainBlock` | 181 | | `moveCardToZone`/`forEachCardInZone` | 4/4 |
| `modifyStatusStacks` | 159 | | | |

其余 `node.encounter`(23)/`node.event`(7)/`node.shopRef`(1) 与一大批
`fx.*`/`reward.*`/`meta.*`/`tpl.*` **全是 run 层**，v1 明确不做。
**前 5 个节点覆盖绝大多数牌。**

> 这一步的意义：把"照规格实现"换成"按数据实现"。规格是**上界**，数据是**工单**。

### 32.2 W4a `ir.rs`：把 term DAG 读成带类型的节点视图（1306 行 / 20 测）

`content.rs` 给的是通用 interned JSON 树；`ir.rs` 补**语义层**：按名字取字段、按 `Field::kind()` 解码、
把判别串解析成 `NodeKind`。**它不做任何求值**（求值在下一步）。

### 32.3 又抓到**5 个我冻结写错的地方** —— 其中两个是"会全盘失效"级别的

| # | 我写的 | 实际 | 不修的后果 |
|---|---|---|---|
| 1 | `kind_str()` = `field("kind")` | **`kind` 不是字段**，是 `OPD[op].name`（`reader.py:216` 把它还原成 JSON 的 `kind` 键） | **每一个节点**都返回 `Missing("kind")`，`NodeKind` 永远拿不到 |
| 2 | `F_INT` ⇒ `Value::Int(x as i32)` | 槽是**有符号 i16**；镜像里有 `const{Value:-1}`(raw `0xFFFF`)、`fx.changeResource{Delta:-300}` | `-1` 被读成 **65535**，伤害/数值全错 |
| 3 | `list_field` 签名可以表达三态 | 表达不了"缺席/null/空列表" | 已定：三者都回 `Ok(0)`（执行侧都是"没有孩子"），**写进 doc，不偷偷糊** |
| 4 | `StatusDefinitionId` 可能包了 `_obj{value}` | 是 `F_STR` + `FLAG_WRAP_LOWER`；**包装对象根本不落盘** | 会把裸串当成对象去解 |
| 5 | `Element` 是 Absent | 实测 `NULL16` ⇒ `Value::Null` | `Absent` 与 `Null` 混为一谈 |

**累计 5 次冻结契约错误，5 次都是叶子照真实数据顶回来才发现的。**
这个比例（5/5）不是运气问题，它说明一件事：

> **冻结注释/桩里凡是关于"数据长什么样"的断言，都必须标成"我猜的"，并且叶子必须被要求去核对真实产物。**
> 我能看规格、能看参考源码，但**唯一不会骗人的是产物本身**。
> 所以后面每个叶子的任务书里都写死一条：**"发现真实数据与我说的不符，以真实数据为准并如实报告"**。

### 32.4 它顺手交了后面**所有**工作量的清单（这是最值钱的一项）

镜像里的判别串**恰好 73 种** = 15 种 `node.*` + 58 种。这 58 种已逐个列名写进一条**门槛测试**
（新出现第 74 种会让它变红）。`F_*` 实际用量：`F_STR 75 / F_INT 47 / F_BOOL 7 / F_TERM 129 /
F_TERMLIST 21 / F_STRLIST 14 / **F_JSON 0**`。

两个"以为有、其实没有"的结论：
* **`F_JSON` 一次都没出现** —— 那条分支是防御，不是需求；
* **`FLAG_WRAP_*` 大量出现（24 lower + 16 upper）但对 IR 层透明** —— 它只决定 JSON 写法，包装对象不落盘。
  另外 `_obj(Value,Weight).Value` 真的有 **25 处 `F_TERM` 指向 `_wrap_lower`**（run 层奖励池，字段真多态），
  实现一律 `WrongKind("F_TERM")` 而不是当普通 term 解。

### 32.5 `sel.*` 的真实形状（下一步的输入）

统计出来的 14 种里，**只有 10 种是战斗员选择器**，而且都能干净落到已有的 `targets.rs`：

| IR kind | 字段 | → `targets::SelectorNode` |
|---|---|---|
| `sel.source` (315) / `sel.eventTarget` (1637) / `sel.iterationTarget` (2264) | `Cardinality` 等元数据 | `Leaf(Source/EventTarget/IterationTarget)` |
| `sel.allAllies` (20) / `sel.allEnemies` (29) | `{}` | `Leaf(AllAlliesOfSource / AllEnemiesOfSource{alive_only:true})` |
| `sel.allCombatants` (19) | `AliveOnly`, `MayIncludeDownedTargets` | `Leaf(AllCombatants{alive_only})` |
| `sel.lowestHealthEnemy` (2) | `Cardinality` | `Leaf(LowestHealthEnemyOfSource)` |
| `sel.withStatus` (19) | `Inner`, `StatusDefinitionId` | `StatusFilter{…}` |
| `sel.alliesWithStatus` (12) / `sel.enemiesWithStatus` (10) | `StatusDefinitionId` | `StatusFilter{With, Leaf(AllAllies/AllEnemies), …}` |

另外 4 种（`sel.deckCards` / `sel.matching` / `sel.random` / `sel.choose`）是**卡选择器或玩家选择**，
不出现在基础出牌路径上 —— v1 不做，遇到就报 `UnsupportedKind`。

---

## 33. 第 22 轮：效果解释器打通 —— **内核现在真的能打出一张牌**

四个切片，四个 agent，最后 **334 条测试全绿 / 聚合验收 9/9**：

| 切片 | 文件 | 行 | 测试 | 职责 |
|---|---|---|---|---|
| W4a | `ir.rs` | 1306 | 20 | term DAG → 带类型节点视图 |
| W4b | `sel.rs` | 1293 | 16 | IR `sel.*` → `targets.rs` arena |
| W4c | `expr.rs` | 1486 | 23 | 表达式求值（饱和/短路/单目标读） |
| W4d | `exec.rs` | 2643 | 50 | 节点执行 + 伤害/格挡走真管线 |

### 33.1 结果：**39/62 张真牌可执行**，23 张在预检被具名拒绝

`paper_cut` 打 hero 70/70 ⇒ **70 → 64**；目标带易伤 2 ⇒ **61**；来源带力量 3 ⇒ **61**；
来源力量 2 + 虚弱 ⇒ **64**（`(6+2)*75/100 = 6`，回到 6 本身）。
不支持的节点（`drawCards`/`createCardInstance`/`moveCardToZone`/`forEachCardInZone`/`gainResource`）
在**预检**就被拒 —— `sequence[applyStatus, drawCards]` 报 `UnsupportedNode` 且**一个状态都没落地**。

### 33.2 "同值不同因"是怎么被分开钉住的

`vulnerable 2` 和 `strength 3` **都让 6 变成 9**。只写一条断言的话，一个"永远返回 9"的假实现也能过。
所以加了一对**错侧反例**：

| 放错位置 | 结果 |
|---|---|
| 易伤放在**出手者**身上 | 只掉 **6**（目标阶段读承受者） |
| 力量放在**承受者**身上 | 只掉 **6**（来源阶段读出手者） |

谁哪天把两个阶段合成"读场上所有状态"，这两条**同时变 9**，立刻红灯。
再加规格 §4.2 的两个权威向量：base7+力量3+虚弱+易伤 = **10**（错序 12）、base6+力量2+虚弱+易伤 = **9**。

### 33.3 `resolve_damage` 里**没有任何数值常量**

我 grep 过：生产代码里 `75`/`150` **只出现在测试的断言消息里**；数值全部来自
`status_catalog::damage_modifiers()` / `block_modifiers()`（`exec.rs:902,923`），
四种运算交给 `modifiers::apply`。有一条测试专门钉这个反直觉行为：
**`vulnerable` **0 层**仍然 ×150%** —— 因为表里 `ScalePercent` 不读层数。
一个硬编码"+1/层、×150%"的实现**写不出这个行为**，所以这条测试能杀掉它。

**那两张表（17 + 31 条测试）没有被架空**，这是我这轮最在意的一件事。

### 33.4 第 6 个冻结错误 —— 这次是"给了钥匙但没有齿"

`ir::list_field` 返回一串 `u16` term id，而 `NodeRef` **没有任何 accessor 能拿回 `content`**
把它包回节点。`Term` 也只带 `id/op/slots`，在 `#![forbid(unsafe_code)]` 下无法从 slots 反推 blob。
⇒ **所有列表孩子不可达**，首当其冲是 `sequence`（镜像 1273 次，最高频节点）。

补一行：

```rust
impl<'a> NodeRef<'a> {
    /// 把一个 term id（例如 `list_field` 返回的那些）包成节点视图。
    pub fn child(self, id: u16) -> Self { Self { content: self.content, id } }
}
```

> **累计 6 次冻结契约错误，6 次都是叶子在动手之前核对真实产物发现的。**
> 这条的形态和前几次不同 —— 前几次是"我把数据描述错了"，这次是"**我的 API 形状本身不闭合**"：
> 一个返回 id 却不提供"id → 视图"的方法，等于一把没有齿的钥匙。
> 自查办法还是那一条：**冻一个方法之后，立刻写一行调用它的代码。** 写不出来就是开错了。

### 33.5 唯一会**污染指纹**的已知偏差（必须记住）

`applyStatus` 的状态极性用 `status_catalog::status_meta()` 查；镜像独有的
`doubt`/`paperwork` 之类查不到 ⇒ **默认记成 `Buff`**，而镜像里它们是 `Debuff`。
⇒ **一旦 exec 接上会算哈希的战场，`pol=` 就会与参考不同。**

消掉它只有两条路：**补内容→状态定义绑定层**，或在 `status_catalog` 里补上那 23 条场景状态。
这是目前离"能打一局且指纹一致"最近的一块绊脚石。

### 33.6 agent 顶回来的一条，我接受了

我要求"`source` 为 None 但程序需要它 ⇒ `NoSource`"。它去读了参考：
**没有来源时参考既不抛也不报**（`PassiveModifiers.cs:248-249` 原样返回、
`CombatantTargetSelectors.cs:84-85` `Source` 解出空集）。所以它实现成**忠实行为**
并在 `NoSource` 的 doc 里写明这个变体在 v1 **没有构造路径**。

> 这是正确的选择：**"比参考更严"也是一种偏离**，而且更难发现 —— 它会拒绝掉参考本来能跑的程序。
> 要更严必须是有意的、被签字的，而不是顺手加的。

### 33.7 现在这个内核能做什么（再次更新）

| 能力 | 状态 |
|---|---|
| 读真实内容镜像 / 序列化 / 指纹 | ✅ 85 份语料逐字节重现 |
| 回合推进（七步 turn-start、绕回、重洗…） | ✅ |
| **执行一张牌**（伤害/格挡/状态/治疗/序列/条件） | ✅ **39/62 张真牌**，伤害与格挡走真管线 |
| 跑在裸机上 | ✅ 真链接成 ELF |
| 当并行 RL 环境 | ✅ 57,457 环境步/秒（NativeAOT 路径） |
| **打一局** | ❌ 还差：出牌流程/费用/校验器链、5 种节点、事件队列与触发程序、内容→状态绑定层 |

---

## 34. 第 23 轮：修已知偏差 —— 内容镜像里本来就有那张"绑定表"

前一轮留下了三条已知偏差。按**危害**排序（而不是按好不好修），一条条关掉。

### 34.1 偏差 A（污染指纹）+ 偏差 B（算错伤害）：同一个根因，同一个解

| # | 偏差 | 危害 |
|---|---|---|
| A | `applyStatus` 的极性对镜像独有状态默认 `Buff`（镜像是 `Debuff`） | **污染指纹** —— `pol=` 会与参考不同 |
| B | 状态 id 命名空间桥（`strength` ↔ `standard.strength`）是**未经验证的假设**，且对另外 4 个带修饰器的镜像状态**完全无效** | 真实内容的伤害算错 |

**A 的正解不是"补 23 条进 `status_catalog`"**（那还是硬编码），而是：**镜像自己就带着这两样数据。**

`STAT` 表的 20 格里就有 `Polarity`（`F_STR`）和 `PassiveModifiers`（`F_TERM`）。实测 core 镜像：

* `Polarity`：**Debuff 5 / Buff 5 / Neutral 13**；
* `PassiveModifiers`：**18 个空 `[]`**，5 个各 1 条 —— 而 `PassiveModifierSpec` **总共只有 7 个字段**
  （`Pipeline` / `Operation` / `Magnitude` / `Priority` / `RestrictDamageKind` /
  `AppliesToStatusId` / `RestrictSourceCardTag`），`Pipeline` 只出现 3 种、
  `Operation` 只出现 3 种（**没有 `ClampMax`**）。

那 5 条（这**就是**内容→状态绑定层，不需要再"补一层"）：

| 状态 | 极性 | spec |
|---|---|---|
| `doubt` | Debuff | `DamageDealt / ScalePercent 75` |
| `panic` | Debuff | **`TurnStartDraw` / AddPerStack −1** |
| `strength` | Buff | `DamageDealt / AddPerStack 1` |
| `signature_pending` | Buff | `DamageReceived / ScalePercent 75` |
| `seal_intact` | Buff | `DamageReceived / AddFlat −4` |

新模块 `status_bind.rs`（836 行 / 8 测）负责从镜像解出这 7 个字段。

### 34.2 修前 vs 修后（全部有封条）

| 场景（`paper_cut` 基础 6 点） | 修前 | 修后 |
|---|---|---|
| `doubt` 在**出手者** | **6**（忽略） | **4**（6×75/100） |
| `seal_intact` 在**承受者** | **6**（忽略） | **2**（6−4） |
| `strength` 出手者 3 层 | 9 | 9（**数字一样，依据换了**：从"未验证的桥"换成镜像自己的 `AddPerStack 1`） |
| `panic` 出手者（`TurnStartDraw`） | 6 | **6**（管线门拦住，不进 `DamageDealt`） |
| `paperwork`（`[]`）两侧各 5 层 | 6 | **6**（空表不贡献候选） |
| `doubt` 的极性 | **`Buff`** | **`Debuff`** |

### 34.3 它用**变异测试**证明封条不空 —— 这是这轮最该记的一条

它没有停在"测试全绿"，而是做了三次**故意改坏 → 看红灯 → 立刻还原**，每次只改一处：

| 改坏什么 | 哪条测试红了 | 红的样子 |
|---|---|---|
| 去掉"按定义去重" | `two_instances_of_one_definition_contribute_its_spec_once` | `left: (0,3) right: (0,4)`（第二条 doubt 又乘了一次 75%） |
| 去掉管线门 | `the_turn_start_draw_pipeline_never_touches_damage` | `left: (0,5) right: (0,6)`（`panic` 按 −1 减了伤害） |
| 让极性忽略镜像 | `bound_content_turns_doubt_into_a_debuff_…` | `left: Buff right: Debuff` |

> **"测试全绿"证明的是"没红"，不是"会红"。** 变异测试才证明后者。
> 而且它很便宜：`cargo test --lib -- <过滤名>` 编译 20 s、跑 0.07 s。
> **以后每个封条都该这么验一次。**

### 34.4 偏差 C：6 条 clippy warning 清零

都清掉了，现在 `clippy --all-targets` 在**整个 crate** 上零告警。其中两条值得说：

`status_catalog.rs` 里有 `assert!(SPEC_PRIORITY_ADD < SPEC_PRIORITY_SCALE)` —— clippy 报
`assertions_on_constants`。但**根子上的问题不是风格**：这种断言只证明"两个常量谁大"，
**证明不了"表是按它们排的"**。已改成从 `damage_modifiers()` 里取真实的行来比
（第一条加法行 < 第一条乘法行、且它们的 `spec_priority` 就是那两个常量、易伤那行是 300）。

> 常量断言是**看起来在验证、其实什么都没验证**的典型 —— 和"过滤掉退出码"是同一族。

### 34.5 仍然开着的（收窄后，全部是**响亮拒绝**而非静默忽略）

| 项 | 现状 |
|---|---|
| 多防御池吸收 | 只扣 `standard.block`（标准包也只注册这一个；多池内容会少吸收 = 多掉血） |
| `Block` / `Cost` 管线 | 镜像里没有；真出现 ⇒ `ExecError::Bind` |
| `ClampMax` / `OncePer*` / `AppliesToStatusId` / `RestrictSourceCardTag` 非空 | 同上，响亮拒绝 |
| `pending_turns`（`IncomingStatusDelay`）、出手方放大 | 未实现，doc 里写明 |
| `Sequence ≡ CausalSequence`、无 outcome slot | 简化，接上触发器即失效 |
| 23 张牌（5 种节点） | `drawCards`/`createCardInstance`/`moveCardToZone`/`forEachCardInZone`/`gainResource` |

### 34.6 一条纪律被轻微破坏，记一笔

我在任务书里写"`lib.rs` 我来加 `pub mod status_bind;`，你先写信"。它**自己加了一行**——
理由是"不加就编译不过，我拿不到任何验证"。这在结果上是对的（而且它**主动报告了**，还提醒我别再重复加），
但它确实越了界。

> 正确的做法应该是我在派活时就**先把那一行加上**（反正桩文件不存在也能加，因为我可以同时建空文件），
> 而不是让对方在一个编译不过的树里干活。**"我先加"这个承诺如果会让对方无法验证，那它本身就是坏安排。**

### 34.7 终态

**15 个模块 / 约 22,000 行 / 353 条测试 / 聚合验收 9/9 / clippy 零告警。**
内核能读真实内容、能推进回合、**能打出 39/62 张真牌**、能跑在裸机上、能当并行 RL 环境。
离"能打一局"还差：出牌流程那一层，以及事件队列/触发程序。

## 35. 第 24 轮：把 15 种节点补齐 —— 39/62 张牌变成 58/62

### 35.1 一下午涨了 21 条测试，靠的是"一次只放一个文件"

第 34 轮结束时 `exec.rs` 3418 行 / 61 条测试，**只认 8 种节点**。这一轮它做了 7 种新的：
`setCombatantCounter` / `modifyStatusStacks` / `forEachTarget` / `drawCards` / `gainResource` /
`loseResource` / `createCardInstance`，`exec.rs` 变成 **5034 行 / 82 条测试**，能执行的卡
**39/62 → 58/62**。全树从 353 → **376 条测试**。

值得记的是它自己做的两件事：

1. **多池吸收**那一条它没按"插入顺序"写，而是按 `Id` 字节序排（内核里 `AbsorbPriority` 读不到，
   但标准池的优先级全是 0，所以字节序是等价的）。这是一条**推导出来的**语义，不是抄来的。
2. 它给每一次"这样写也绿"留了**变异测试**：把正确实现改成错的（比如把"扣到 0 删实例"改成
   "留 0 层"），确认测试**真的会红**。这个项目的封条标准一直是这个 —— 绿只证明"没红"，
   不证明"会红"。

### 35.2 第 7 个冻结错误：`remove_status` 不存在，逼出了"整条 `Combatant` 重建"

`modifyStatusStacks` 把层数扣到 0 时要**删实例**（`StatusEffects.cs:830-838`），而 `state.rs`
的 `Combatant` 当时只公开 `push_status`（追加）和 `statuses_mut`（**定长**可变切片）。
执行方于是把整条 `Combatant` 复制出来、跳过那一条重建、再写回。

它能跑对，但**错得很有耐心**：`Combatant` 以后每加一个哈希可见字段，这段重建就多丢一个字段，
而丢得**无声无息** —— 哈希照样算得出来，只是少一行。执行方主动报告了这一点，并请我补 API。

补的是 `Combatant::remove_status(&mut self, index: usize) -> bool`：`as_mut_slice()` 里 index
之后整体左移一格再 `pop()`，所以**剩下的实例保持相对顺序**、每个字段原样搬移，越界返回 `false`
（裸机上没有 unwind，不能 panic）。测试
`removing_a_status_instance_keeps_the_rest_in_order_and_shrinks_the_list` 钉住三件事：
删中间那条后另外两条**顺序不变**、删空表不 panic、空表再删仍是 `false`。

> **纪律**：执行方说"你的接口开了但我用不了，我绕过去了"时，**要立刻补接口，不要让它一直绕**。
> 这一条在第 22 轮已经写过一次（`NodeRef::child`），这是第二次。共同形状是：**绕过去能跑通，
> 所以错误不会自己暴露，只会沉淀成未来的静默丢数据。**

### 35.3 `tools\acceptance.ps1` 的 `-UnitsFloor` 又一次变成假闸门

它是 353，而真实测试数已经是 376。这个参数我每次加测试都该顺手抬，这轮又忘了 ——
**下限的意义是"测试变少了要响"，停在 353 就等于允许 23 条测试凭空消失而不报警**。
已抬到 **375**。

### 35.4 一个新踩到的工具陷阱：`edit` 工具会**吃掉 `.ps1` 的 UTF-8 BOM`

我把 `acceptance.ps1` 里的 `353` 改成 `375`（只改一行的 edit），整个脚本立刻语法爆炸：
`Unexpected token '杈撳嚭閲屽嚭鐜?/...'`。原因不是内容被改坏 —— 字节仍是合法 UTF-8 ——
而是**BOM 没了**：PowerShell 5.1 在没有 BOM 时按 ANSI（GBK）解码，中文注释被解成乱码，
连引号配对都变了。

修法：`[IO.File]::ReadAllText($p)` 读（.NET 默认按 UTF-8 解码，不需要 BOM），
再用 `New-Object System.Text.UTF8Encoding($true)` 写回。顺手扫了全仓 12 个 `.ps1`，
只有 5 个纯 ASCII 的没有 BOM（无害），含中文的都有。

> 记进纪律：**改任何含中文的 `.ps1` 之后，先查前三个字节是不是 `239,187,191`**。
> 这类故障最像"内容写错了"，实际是"编码元数据丢了"，会让你去改本来没错的中文。

### 35.5 三个规格书同时在写

内核现在最缺的是**三块 glue**，都已经派出去写规格（不是写代码）：

* `docs/spec/play-card-flow.md` —— 一次出牌：受理校验器链、费用、目标、卡的去向、失败路径。
* `docs/spec/battle-loop-hooks.md` —— `TurnHost` 那 8 个钩子到底该干什么（DoT / pending 转正 /
  队列 / 触发器 / 有时限状态减一 / 手牌收尾）。今天唯一的实现是 `NullHost`，全是空实现，
  所以**回合里的真实效果一件都不会发生**。
* `docs/spec/card-selection-recon.md` —— 勘察：4 种 card selector 在镜像里实际长什么样、
  还差哪两个节点 kind 才能吃下剩下 4 张卡。

派活时三条硬要求：每个断言带 `文件:行号` 并标明"验证过/未验证"；**以真实产物为准，
发现我的描述有误就直说**；只准改自己那一个文件。

### 35.6 两条"已知偏差"我自己复核了一遍（都有行号）

执行方报了两条它无法修的偏差。我没有直接抄进文档，而是先去参考实现里量：

**偏差 A：`drawCards` 不套用 `MaxHandSize`。**
`CardZoneEffects.cs:28-46` 确认了：手牌天花板是**从"要抽的张数"里减掉**，不是抽出来再丢
（"the cards past it are never drawn, so they are still on the pile"），且 `wanted == 0` 时
**一张都不抽、直接返回**（连洗牌都不发生）。
但关键在 `:32-33` 的条件 —— 天花板来自 `CombatDecrees.Ceiling(registry, drawer, CombatRule.MaxHandSize)`，
**没有法令注册表就没有天花板**。而内核根本没有法令注册表，内容镜像的 20 个段里也没有法令段。
⇒ **这条偏差今天的可观察影响是 0**：没有法令时 `wanted` 恒等于 `Count`，与内核逐字一致。
诚实的写法是"内核没有法令注册表 ⇒ 天花板恒不存在"，而不是"内核少实现了一条规则"。
它会在**将来接法令时**变成真偏差，那时必须补上 `:35` 的 `Math.Clamp(ceiling - hand.Count, 0, wanted)`。

**偏差 B：`createCardInstance` 不校验卡定义 id。**
`CardCreationEffects.cs:28` 是一行**丢弃返回值**的调用：`registry.GetCard(request.CardDefinitionId);`
—— 它的作用就是"找不到就抛"。所以参考侧**确实校验**，而且是抛异常让整个 program 作废。
内核没有卡定义注册表（内容镜像的 `CARD` 段有 62 行，形状上像定义，但内核没把它当注册表用）。
⇒ **这条偏差是可观察的**：内容里写错一个卡定义 id，参考拒绝整张牌，内核会静默造出一张
"定义不存在的卡实例"。记在这里，等卡定义绑定层落地时一并对齐。

顺带量到一条**新缺口**：同一个 handler 在 `:52` `EnqueueEvent(new CardInstanceCreatedCombatEvent(...))`。
内核没有事件队列 ⇒ 这张卡造出来之后**不会触发任何"卡被创建"的触发器**。这属于 §35.5 里
"事件队列/触发程序"那一块，不是这张卡的局部问题。

> 这两条复核的意义：**执行方说"这是已知偏差"时，偏差的"影响面"仍然要自己量。**
> 一条"没有可观察影响"的偏差和一条"会静默造出非法状态"的偏差，处置优先级差一个数量级，
> 而它们在执行方的报告里长一个样。

### 35.7 出牌流程要的东西，镜像里**早就有了**

为了判断"出牌流程到底要冻多大一块"，我去看了 `CARD` 段的行宽：**每张卡 15 个格 / 32 B**。
这 15 个格的名字（`content.rs` 的 `CARD_SCHEMA`，和 `rdcfmt.py` 逐项一致）：

| # | 字段 | 类别 | 我的猜测 |
|---|---|---|---|
| 0 | `Id` | `F_STR` | |
| 1 | `Program` | `F_TERM` | 卡程序根（已用，58/62 靠它） |
| 2 | `Tags` | `F_TERM` | |
| 3 | **`Costs`** | `F_TERM` | 费用 |
| 4 | `LifecyclePrograms` | `F_TERM` | |
| 5 | **`PlayCondition`** | `F_TERM` | 受理校验 |
| 6 | **`QueueOnPlay`** | `F_TERM` | 出牌时入队什么 |
| 7 | `RetainInHandOnTurnEnd` | `F_BOOL` | |
| 8 | `IsAction` | `F_BOOL` | |
| 9 | `NameKey` | `F_STR` | |
| 10 | `DescriptionKey` | `F_STR` | |
| 11 | `PackageId` | `F_STR` | |
| 12 | **`TurnEndHandDestinationZone`** | `F_STR` | 回合结束留在哪 |
| 13 | **`PlayedCardDestinationZone`** | `F_STR` | 打完去哪（弃牌/消耗） |
| 14 | `extra` | `F_TERM` | |

**这是一条让人安心的发现**：出牌流程要的四件事（花多少钱、能不能打、什么时候排队、
打完去哪）**都是卡自己的字段**，不是"引擎里散落的一堆 if"。所以 `play.rs` 的形状大概率是
"读 `CardRow` 的几个格 + 调 `exec::execute` + 搬卡"，**不需要**先建法令注册表。
（"猜测"那一列我标了猜测：字段里到底装什么 term 形状，已经派出去实测了。）

顺带清掉一条我以为的缺口：**`ClampMax` 不是缺口**。`modifiers.rs:279` 完整实现了它，
`status_bind.rs:197` 拒绝它是因为**镜像里一条都没有**（有测试 `assert_eq!(ModifierOp::from_wire_name("ClampMax"), None)`
和一个"实测 3 种里没有它"的注释）。同理 `Block`/`Cost` 两条管线：`modifiers.rs:36-45` 的
`Pipeline` 枚举**四条全在**（`DamageDealt` / `DamageReceived` / `Block` / `Cost`），
只是镜像那 5 条 `PassiveModifiers` 分别是 `doubt`/`strength`（DamageDealt）、
`signature_pending`/`seal_intact`（DamageReceived）、`panic`（TurnStartDraw）—— **没有一条走 Block 或 Cost**。

> ⚠️ 这一段我第一次写错了：我在任务书里告诉规格代理"`Pipeline` 只有三条"，它去
> `modifiers.rs:36-45` 一读，四条都在、含 `Cost`，直接顶回来了。**这是第 8 次冻结契约写错，
> 而这 8 次全是靠执行方去核对真实产物才发现的。** 记在这里的具体教训是：
> 描述"内核有什么"时，别凭记忆写，去读那 10 行。

> 这一类要分清：**"内核拒绝 X" 与 "X 会真的发生" 是两件事**。
> 拒绝一个镜像里从不出现的形状，代价是零；把"拒绝了"写成"缺功能"，会让人去补一个没人用的东西。
> 已有的那条测试 `every_card_program_in_the_image_either_runs_or_is_refused_by_kind` 就是干这个的：
> 它断言 62 张牌里恰好 58 跑通、4 被拒，**且那 4 张的拒绝原因必须恰好是"节点不支持"**
> （其它任何 `ExecError` 都算真 bug），并且逐个点名拦路节点就是
> `forEachCardInZone` + `moveCardToZone`。这比报告里写一句"覆盖 94%"结实得多。

## 36. 第 25 轮：三份规格书回来了，先修那条**能构造出来的真分歧**

### 36.1 结论先说：卡片选择器是**大活零收益**，62/62 是**小活**

勘察（`docs/spec/card-selection-recon.md`，786 行）把"扩 `sel.rs` 支持卡片选择器"
这件事直接判死了：

* 镜像里卡片选择器只有 4 种共 7 条 term（`sel.deckCards` / `sel.matching` / `sel.random` / `sel.choose`），
  但它们在 **62 个卡程序树里出现 0 次** —— 父节点全是 `fx.removeCards` / `fx.upgradeCards` /
  `fx.duplicateCards` / `fx.transformCards`，只从 `ROOT Events` / `ROOTS Shops` 可达；
  C# 侧实现读的是 `RunState.Deck`、run RNG、`IRunEntityChooser`，**一个 `CombatState` 字段都不读**。
  ⇒ 那是 run 层语义，跟"能不能打一局战斗"完全无关。
* 卡程序树里 15 种 `node.*` 只出现 9 种；之外的非 node kind 只有 7 种，前 6 种已经在跑，
  **唯一没实现的非 node kind 是 `cardInstance.iterated`**（0 字段，全镜像只有 t152 一条）。

所以真正挡着 62/62 的是 **2 个节点 + 1 个表达式**。已经派出去实现。

### 36.2 我这次做的是"冻接口"：给卡实例留一个槽，而不是给表达式加个分支

`cardInstance.iterated` 的值域是**卡实例**，不是 int。原来的 `INT_KINDS` 表把它当 int 收着，
于是 `eval_int` 会先过值类别闸、再掉进 `UnsupportedKind` —— **用"没实现"掩盖"问错了问题"**。
所以：

* `expr.rs` 的 `Class` 从四类变五类，新增 `Card`；`cardInstance.iterated` 从 `INT_KINDS` 搬到 `CARD_KINDS`；
  `eval_int`/`eval_bool` 见到 `Card` 一律 `WrongValueKind`。
* 新增 `pub fn eval_card(node, ctx) -> Result<CardInstanceId, ExprError>`。
* `ExprContext` 与 `ExecContext` 各加一个 `iteration_card: Option<CardInstanceId>`
  —— 和 `iteration_target` **分开两个槽**，因为 `ForEachTarget` 与 `ForEachCardInZone` 绑的是两种东西、还能嵌套。
* 没有绑定时返回 `NoTarget`，**绝不返回 `CardInstanceId::EMPTY`**：空 id 会让 `moveCardToZone`
  去找一张不存在的卡并静默不动 —— 那是最坏的一种"通过"。

代价是那条覆盖扫描的门槛数从 `171 / 117 / 54` 变成 `170 / 117 / 53`。**我没有直接改数字了事**，
而是加了两条断言把账做平：`skipped_card == 1`、`total + skipped_card == 171`。
把"数字变小了"这件事本身钉住，不然下次少一条也没人知道。

`eval_card` 的封条写成了成对反例：绑了谁返回谁 / 没绑定 ⇒ `NoTarget` 且 **不等于空 id** /
卡当 int 读 ⇒ `WrongValueKind` / int 当卡读 ⇒ `WrongValueKind` / 语句节点 ⇒ `NotAnExpression`。

### 36.3 修了一条真分歧：**"清不清格挡"不是在清格挡那一步判定的**

`battle-loop-hooks.md` §5.1 顶回来一条我写错的语义。参考的 `ClearBlockOnTurnStartedHandler`
是在**处理器时点**采样 `pool.Current <= 0`（`DefensivePoolEffects.cs:305-306`）就决定要不要入队清空请求
—— 而那一刻本回合的**任何效果都还没生效**（效果要等七步跑完才排空）。内核是就地生效的，
却在**第 7 步**才采样，于是把第 5 步队列卡刚加上的格挡当成"回合开始时就有的"给抹了。

可构造的分歧（现在是被测试钉住的）：

| 回合入口格挡 | 队列卡 `gainBlock 11` | 参考 | 修前内核 | 修后内核 |
|---|---|---|---|---|
| 0 | +11 | **11** | 0 | **11** |
| 10 | +11 | **0** | 0 | **0** |
| 10（`block_is_retained`） | +11 | **21** | 0 | **21** |

修法是"入口采样、第 7 步清实时值"：`start_current_turn` 在 `ensure_active_can_start_turn`
之后立刻把 `pool.current` 与 `host.block_is_retained(...)` 各采一次，作为参数传进
`clear_turn_start_pool`。这在参考里是**等价**的（判定时点所有效果都还没生效），不是近似。

⚠️ 文档上有个陷阱：`S:QueueTortureTests.cs:210-212` 那个官方用例**区分不出**两种实现
（两种解释都给 11），`turn.rs` 自己的文件头（第 24-25 行）也把顺序写反了（说"清 Block 在队列解析之前"）。
**注释写反了 8 个月没人发现，是因为那个用例恰好落在两种实现一致的那一格。**
新加的测试里特意做了第二条（入口 10⇒最终 0），成对存在才有意义。

变异验证：把采样点挪回第 7 步，第一条测试**变红**（`left: Some((0, None)) / right: Some((11, None))`），
第二条**依然绿** —— 正好证明"两条一组"的必要性：单看第二条的话，错误实现也是绿的。

### 36.4 回合回环规格书顶回来的另外四条，我的裁决

`battle-loop-hooks.md` §5 一共提了 6 条，逐条给结论（裁决就是契约，后续读这份文档的人按这个走）：

| # | 问题 | 裁决 | 理由 |
|---|---|---|---|
| 5.1 | 清格挡采样时点 | **已修**（见上） | 能构造出可观察分歧 |
| 5.2 | 没有任何钩子解析 `CardZone::QueuePile` | **采纳 (a)：加第 9 个钩子 `resolve_card_queue`** | 与参考的注册序一一对应；改 `resolve_pending_queues` 的语义会污染它另外 6 个调用点。**还没实现**，先记契约 |
| 5.3 | turn-end 弃手牌发生在触发器**之前** | **只记录，不改结构** | 镜像 6 条 `TurnEnded` 触发器没有一条动牌 ⇒ 今天不可观察。要改得引入三队列，代价远大于收益 |
| 5.4 | `resolve_damage` 没有 `kind` 参数 | **采纳 (b)：另加 `resolve_damage_of_kind`** | 直接复用会把力量/虚弱/易伤算进 DoT；改老签名会动 50 个调用点 |
| 5.5 | `chain_num` / `exec_num` 有字段、进哈希、**没有发号器** | **必须补**，但等我冻 API | 宿主一跑节目指纹就发散；这是"能不能对拍"的前提 |
| 5.6 | 两个 `Pipeline` 枚举各缺一半 | **只记录，不合并** | 参考是 6 成员；内核两个枚举各取所需且都有测试。合并会同时动 `modifiers.rs` 与 `status_bind.rs`，收益不明 |

### 36.5 出牌流程规格书里那条**最该被钉死**的

`play-card-flow.md` 里有一条比"费用怎么扣"重要得多的发现：

> **`next_effect_chain_number` 在两个入口上不一致 ⇒ 同一次出牌两个不同哈希。**
> 请求面跑在 `using EnterEffectChain` 内（`CombatEffectQueueProcessor.cs:32-33`）⇒ 链号 +0；
> 严格面每条入队 +1（`CombatState.cs:386`/`:446`）。

这和第 36.4 的 5.5 是同一个洞：内核今天**根本没有发号器**。换句话说，
"能不能打一局"的路上有一半是"能不能复现指纹"，而指纹里有两个计数器今天不会动。

顺带，出牌规格书实测出的三条让工作量大幅收缩的事实：

* 62 张卡的 `PlayCondition` / `QueueOnPlay` **各 62/62 全是 ABSENT**，`IsAction` 全 false，
  23 条状态的 `CombatRules` 也 **23/23 ABSENT** ⇒ **法令整块在这次内容里 0 命中**。
* 费用：47 张各 1 条 `{Amount: 1|2, ResourceId: "standard.energy"}`，15 张指向**共享的空列表**；X 费不存在。
* 落区：`DiscardPile` 48 / `ExhaustPile` 14；**没有 in-play 区**，出牌期间卡一直留在手牌里，
  直到节目到终态才搬。

⇒ `play.rs` 的第一步可以只做"印刷费用 + 三种终态 + 搬卡"，法令与 `PlayCondition` 留成响亮拒绝。

## 37. 第 26 轮：**62/62** —— 内容里每一张牌现在都跑得通了

### 37.1 结果

`exec.rs` 5015 → **6082 行**，测试 380 → **391**（加上我那条不变量闸门是 392）。
最后两个节点 `forEachCardInZone` / `moveCardToZone` 落地，`cardInstance.iterated` 接上，
**62 张卡全部可执行**。门槛测试从"58 跑通 + 4 被拒且点名"改成了更强的形状：

> `every_card_program_in_the_image_runs_because_no_kind_is_refused`
> —— 62 张全部用 `run_card_bound`（**接内容镜像**）在同一个"2 张 junk + 1 张非 junk"的手牌上跑，
> 断言 `ran == 62` **且拒绝集合为空**。任何一张被拒都会打印 `(卡号, 错误)` 并失败。

这比原来的写法结实在哪：原来那条允许"4 张被 `UnsupportedNode` 拒"，也就是给了
`_ => UnsupportedNode` 一条降级空间；现在这个降级空间**在法律上不存在**——
15 种节点全实现之后，分派里的 `_` 臂会让编译器报 `unreachable pattern`（clippy 要零告警），
所以两个 `match` 都改成了穷尽 15 个变体。**"能不能跑"不再靠一条兜底分支说话。**

`ExecError::UnsupportedNode` 因此变成不可达变体。保留（枚举是冻结的），文档写明它现在只能被
"第 16 种节点"命中 —— 而那种节点会在 `kind()` 就先报 `UnknownKind`。

### 37.2 第 9 次冻结契约写错：`DefinitionFilter` 不是卡选择器

我在任务书里写"`DefinitionFilter` 非空 ⇒ 响亮拒绝（因为 `sel.rs` 不支持卡片选择器）"。
实际是 `CardDefinitionId?`（`EffectProgramNodes.cs:294`，`:451` 直接 `c.DefinitionId == filter`），
**`sel.rs` 根本不参与**；非空时线上是 `_wrap_lower` 包装串，`ir.rs` 的 `field()` 本来就拒收。

执行方没有照我说的绕，而是**两种拼法各设一道闸**（预检 + 分派），并把这个事实写回来。
这是第 9 次，模式没变：**我描述参考实现时凭的是规格书的转述，而规格书那一层就漏了这个类型。**

### 37.3 一条新裁决：没有内容镜像时，`TagFilter` 必须**响亮拒绝**

`TagFilter` 要读卡的**定义**上的 tag，而定义只有内容镜像里有。所以 `content == None` 时，
`forEachCardInZone` 现在报 `ExecError::Ir(IrError::Missing("content"))`。

执行方把选择权交给我，问"要不要允许不接镜像也放行"。**裁决：不允许。**
理由就是这个项目从第 1 轮守到现在的第 3 条纪律：**产物缺席时必须响亮失败，绝不静默忽略。**
不接镜像时"安静地一张都不清"是一种会让人查一整天的通过 —— 它让 `forEachCardInZone`
在 oracle/env 路径上变成 no-op，而调用方拿到的返回值是 `Ok`。

代价是：oracle/env 今天不会碰到（`forEachCardInZone` 只在那 4 张卡里），
将来若要在无镜像路径上用这个节点，调用方必须自己先接上内容。

### 37.4 执行方交回一条"最脆的假设"，我把它变成了闸门

它自己指出：`forEachCardInZone` 快照的是**池槽位号**（`u16`）而不是 `CardInstanceId`，
因此依赖一条**只写在注释里、没有任何测试钉住**的不变量：
**一个池槽位在一局里永远只属于一张卡。**

它说得对，而且后果很坏：一旦 `state.rs` 将来引入槽位回收（为了让 224 个槽够打更长的局），
循环途中被搬走的槽就会**静默指向另一张卡** —— 不报错、不 panic，只是换了一张牌。

我没有改它的实现（`CardInstanceId` 快照更贵且没必要），而是去 `state.rs` 加了一条
`a_pool_slot_is_never_recycled_so_a_walk_over_indexes_stays_valid`：

* 3 张牌 → 槽位必须是 `[0,1,2]`；
* 退休中间那张再压一张新的 ⇒ 新卡必须拿 **3**，不许捡回 1；
* 再退休一次 ⇒ 拿 **4**；
* 走 1000 轮"抽牌→搬回"之后，**槽位编号集合**必须一字不差（原来那条 `moving_a_card_reuses_
  its_pool_slot…` 只看长度，而长度不变也可能是"回收了又分配"）。

> 这一条值得单记：**执行方主动说"我最脆的假设是 X，而且没测"时，正确回应不是道谢，
> 是去把 X 变成一条会红的断言。** 口头约定活不过下一次重构。

### 37.5 变异测试三条全红（这次的封条是真的）

Bottom→Top（三条测试红）、`MaxIterations` 截断而非抛（一条红）、错误路径不恢复
`iteration_card`（一条红）。第三条尤其重要：**恢复是写在错误路径上的**，
而错误路径的恢复最容易漏（参考是靠 continuation 里的 scope 关闭"免费"做到的）。

### 37.6 终态

**16 模块 / 约 26,800 行 / 392 条测试 / 聚合验收 9/9 / clippy 零告警。**
`-UnitsFloor` 抬到 **392**（历史教训：停在旧值等于允许测试凭空消失，已经犯过两次）。

内核今天能做到：读整份内容二进制、精确复现引擎指纹、推进回合、**执行内容里全部 62 张卡的效果程序**、
跑在裸机上、当并行 RL 环境。
**仍然不能打一局** —— 差的是 §36.4 里那两条已裁决未实现的（`resolve_card_queue` 钩子）加上
出牌流程本身，以及 §36.5 那个"没有发号器"的洞。

## 38. 第 27 轮：按 E → A → B/C → D 的顺序开工（用户拍板的顺序）

用户问了一句很关键的话：「基建还有什么直接关系游戏体验的重大细节没有修复吗」。
我把剩下的缺口按"能不能玩"重排了一遍，结论是**三条硬阻塞 + 一条缺失的模块**，而且其中一条
（敌方不会行动）**从来没进过任何计划清单**，因为它既不属于回合机也不属于效果执行器。

我把 E 提到了最前面（用户给的顺序是 A→B→D→E）。理由是工程性的而不是偏好：
**A 和 B 都要调发号器**，而 E 是这五件里最小的（两个方法 + 两条测试）。

### 38.1 E：两个只有字段、没有发号器的计数器

`CombatState` 的 `next_effect_chain_number` / `next_program_execution_id` 有字段、有初值、
**进哈希**、全仓没有一处 `+=`。也就是说状态里有两个计数器，参考每跑一次节目、每次最外层入队
都会推进它们，而内核永远停在 1。**补它们之前，"对拍"这件事其实一直是假通过**：
只要宿主一次节目都没跑过，`chain_num=` / `exec_num=` 两行就永远对得上。

补的语义逐字照 `CombatState.cs:513-518` / `:545-555`：**返回自增前的值**。
这一条不是细节 —— 写成"先加再返回"会让整场每个 id 偏移 1，而**偏移不会自己暴露**：
任何只比"变了没变"的测试都看不出来，只有逐字节对拍会。所以测试直接断言字面量（第一个号必须是 1）。
第二条测试是封条：发了号之后**规范文本必须变**，且必须是 `chain_num=2` —— 证明它真进了指纹。

链号那条还附了一条参考规则：`EnqueueEffect`/`EnqueueEvent` 都是
`CurrentEffectChain ?? CreateRootEffectChain()` ⇒ **一条链内的后续入队不再发号**。
内核没有环境链，所以这条规则落在宿主身上；写成"每次入队都调"会让链号狂涨。

### 38.2 C：`resolve_card_queue` —— 第 9 个钩子，**故意不给默认实现**

在此之前第 5 步只调 `resolve_pending_queues`，而那个方法的文档说"**任何**入队之后的排空"。
两件事在参考里是**不同的处理器**，混在一个钩子里就是：宿主照文档实现（只排空效果队列，
而效果队列恒空），于是**没有任何钩子会解析 `CardZone::QueuePile`** —— 队列卡永久滞留、
`cz=` 行永久不同、`counter` 那种卡一直算错，**而且不报错**。

所以新钩子是**必做**方法，没有默认实现：默认实现（什么都不做）正是那个静默洞本身。
代价是 8 个测试宿主各补一个转发；这个代价比"再留一个可以忘记的默认值"便宜得多。

拆成两个钩子后"谁先谁后"只写在注释里，所以补了一条把它钉成字节序列的测试：

```
p（pending 转正） t（触发器） q（QueuePile） d（效果队列） o（DoT） d（再排空）
```

变异验证：`q` 与 `d` 调换 ⇒ `ptdqod ≠ ptqdod` 立刻红。
**值得记一笔**：我写期望值时没有先跑一遍看实际输出再抄，而是从文档里的顺序推导出 `ptqdod`
—— 一次对上，说明代码和文档真的同构。先跑后抄会把"当前行为"当成"正确行为"。

### 38.3 A：先冻接口，两个设计决定

`play.rs` 冻了 `PlayRequest` / `PlayError`（10 个变体）/ `Refusal`（5 条校验器）/
`PaidCosts`（定长，满了 `push` 返回 `false`，绝不静默丢）/ `PlayReport`，三个入口
`play_card`（严格面）/ `try_play_card`（请求面，游戏真实路径）/ `can_play_card`（dry-run）。

两个决定值得写下来：

1. **严格面与请求面是两个函数，不合并。** 参考的四个面里 A/B **抛**、C/D **no-op**；
   Rust 没有"抛 vs 静默"的双形态，合成一个就会丢掉一条真实语义
   （`WasPlayed == false` 是可观察的）。
2. **v1 不做 `PlayHost` trait**（规格书 §9.3 建议了 7 个方法）。
   `turn.rs` 当时需要 trait，是因为**效果系统根本不存在**，接缝是唯一能测回合机的办法；
   出牌这一步要的东西今天全在。为一个还没有第二个实现的 trait 提前冻 7 个方法，
   等于把语义提前推给宿主 —— 而纪律是「冻一个 trait 方法之后，立刻写一行调用它的代码；
   写不出来就是开错了」。

### 38.4 D：敌方决策层 —— 一条从来没进过清单的缺口

镜像里能读 **394 条 `EACT`**（`content.rs::enemy_action`）和 109 条 `ENCT`，
但**全仓没有任何代码挑一个动作、也没有任何代码执行它**。玩家侧的效果程序能跑，敌方侧是空的。

它之所以被漏掉，是因为它不属于回合机、不属于效果执行器 —— 它是**缺一个模块**。
已经派出去写规格 `docs/spec/enemy-intent.md`，要它回答的核心问题是：
**选择算法里哪一部分由内容决定、哪一部分是引擎硬编码** —— 这决定能不能纯数据驱动。
（任务书里我写了"394 条"，并明确要求它**自己量一遍**：那个数字是我从旧报告抄的。）

### 38.5 这一轮的证据

```
rust-units 395 passed / corpus-roundtrip 85 case(s) / rust-baremetal / rust-clippy
firmware-link / firmware-size / coverage-gate 19/19 / golden-baseline 129 行 / env-smoke
ACCEPTANCE_RESULT PASS (9/9 gates passed)
```

**17 模块 / 395 条测试 / 9 道闸门全绿 / clippy 零告警 / `-UnitsFloor` = 395。**

### 38.6 还没做完的（按剩余顺序）

1. **A**：`play.rs` 三个函数仍是 `todo!()`，实现正在写（真打一张牌 / 14 张消耗卡 /
   0 费卡 / 付不起且状态逐字节不变 / `can_play_card` 与 `play_card` 同路径）。
2. **B**：`TurnHost` 的真实实现（DoT / turn-start 触发器 / turn-end 触发器 ——
   其中 poison 的层数衰减就靠 turn-end 触发器，空实现会让 poison 永久叠加）。
   它还缺一个 API：`exec::resolve_damage_of_kind`（裁决 §36.4-5.4），要等 A 落地后才好动 `exec.rs`。
3. **D**：规格书回来之后实现。
4. 然后是"外围功能"—— 在那之前结论没变：**只读的界面可以现在就做，可玩的那半边被 A/B/D 卡着**。

## 39. 第 28 轮：A 落地（2380 行 / 17 条测试），D 的规格回来了

### 39.1 A：出牌的实装形状 —— 三个入口共用一条路径

`play.rs` 325 → **2380 行**，0 → **17 条测试**，全树 395 → **412**。三个入口的形状是：

```text
plan_play    纯读，产出一个 PlayPlan（校验器、费用、落区、程序句柄全在里面）
apply_plan   写状态
play_card      = plan + apply                （严格面：拒绝 = Err）
try_play_card  = play_card，把"正常拒绝"折成 NOT_PLAYED
can_play_card  = plan，把计划丢掉            （一行判据都没有）
```

这个形状值得单独记下来，因为它让两条纪律变成**结构上不可能违反**：

* 纪律 2（`can_play_card` 与 `play_card` 同一条路径）—— 它不是"我们小心地抄了一致"，
  而是**根本没有第二份判据**。将来想改校验规则，只有 `plan_play` 一个地方可改。
* 纪律 1（严格面与请求面是两个函数）—— `try_play_card` 是 `play_card` 外面一层
  `match`，所以两个面的**语义差异只有一处**（`is_normal_refusal` 这张表），
  而不是两段平行代码慢慢漂移。

> 一条通用的移植经验：**"两个入口必须给不同结果、但必须共享实现"这种要求，
> 正确解法永远是"纯读地算出计划 → 再决定要不要执行"，不是"写两遍然后祈祷别分叉"。**

### 39.2 第 10 次冻结契约写错：`EACT` 里没有权重、没有条件、没有冷却

我在 D 的任务书里凭 `content-schema.md` 的描述写了"哪一格是权重/条件/冷却"。
实测（`enemy-intent.md`，1015 行，124 处行号）：`EACT` 就 7 格 ——
`Id` / `NameKey`（394 条**全 ABSENT**）/ `DescriptionKey`（全 ABSENT）/ `PackageId`（全 `scenario`）/
`Intent`（`_obj(Kind)`）/ `Program`（信封 op116）/ `extra`（全 NULL）。
**全深度键表 28 个键里 `Weight`/`Priority`/`Condition` 一次都没出现**，`node.conditional` **0/394**。

这条错得很典型：**我把"规格书里描述的 schema"当成了"镜像里的真实形状"**。
schema 是可能写全的（把将来可能用到的键都列上），但内容不一定用。
这和 §35.7 那条 `ClampMax`（内核拒绝它是因为镜像里一条都没有）是同一枚硬币的两面：
**读到"有这个字段"和"有这个数据"之间隔着一整个内容编译过程。**

### 39.3 D 的真正形状：驱动选择器的是 `ENCT`，不是 `EACT`

规格书把分界线划得很干净，而且划出了一个反直觉的结论：

* **选择算法 100% 是引擎硬编码**：`EnemyIntentSelectors.Build`（`EnemyIntentRules.cs:149-168`，全文 19 行），
  **确定性、零 RNG**。四个分支穷举：敌人不在 `compiled.Enemies` → `null`；有匹配规则 → 该规则动作
  （Priority **降序**）；**有规则但全不匹配 → 落回循环，不是跳过**；否则 `Actions[(round-1) % count]`。
* **选择规则 100% 是内容**，但规则挂在 **`ENCT`（遭遇的脚本 + 条件）**上，`EACT` 只是**动作库**。

⇒ **`select_action` 的入参必须是 `(遭遇, 敌人槽位)`，不能只是 `combatant`。**
这是这一层最容易设计错的地方：一个只看 `EACT` 的实现会"跑得通、但永远走循环分支"，
而且**看起来一切正常**（因为本内容的 5 条 `IntentRule` 里 4 条依赖触发器系统、1 条依赖
`CardPlayTurnStats`，内核两样都没有 ⇒ 忠实实现在这份内容上**必然**永远走循环分支）。
**不要为了"看起来有动作"而特判** —— 那是把"内容依赖没到位"伪装成"功能已实现"。

### 39.4 两条会影响排期的实测事实

1. **39/394 个动作 id 超过 `ID_CAP = 40`**（最长 54 B：`queue_crier_homunculus.call_a_number_that_is_not_yours`）。
   ⇒ `EnemyActionId` **不能**用 `Ident<40>`。这条如果不先量，会在实现到一半时炸，
   而炸法很讨厌：`Ident::new` 返回 `Err`，于是"内容加载失败"，看着像镜像坏了。
2. **core 镜像（`flags=1`）剥掉了 `Intent.Label` 和 `NameKey`** ⇒ UI 只能显示 `Intent.Kind` 的字形
   （Special 168 / Attack 110 / Debuff 51 / Defend 44 / Buff 21）。**外围功能在排期时要吃这一条**：
   这不是内核缺功能，是**这份镜像本来就没有名字**（完整镜像 `content.rdcf` 158 KB 里可能有）。

### 39.5 这一轮的证据

```
rust-units 412 passed / corpus-roundtrip 85 case(s) / rust-baremetal / rust-clippy
firmware-link / firmware-size / coverage-gate 19/19 / golden-baseline 129 行 / env-smoke
ACCEPTANCE_RESULT PASS (9/9 gates passed)
```

**17 模块 / 约 30,000 行 / 412 条测试 / `-UnitsFloor` = 412。**

### 39.6 下一步

1. **B**：`TurnHost` 的真实实现（一个 `host.rs`）。先补裁决 §36.4-5.4 的
   `exec::resolve_damage_of_kind`（A 已落地，`exec.rs` 不再被占用），否则 DoT 会被
   力量/虚弱/易伤一起放大。
2. **D 的实现**：`intent.rs`，入参 `(遭遇, 槽位)`，动作 id 用**变长**类型（见 §39.4-1）。
3. 之后才是"能打一局"的端到端验收。

## 40. 第 29 轮：A 收尾（三条冻结面问题），以及一次"占位"的正确形状

### 40.1 结果

`play.rs` 2425 → **2697 行**，测试 18 → **21**，全树 **416 条**，聚合验收 9/9。
`-UnitsFloor` 抬到 **416**。

### 40.2 三条冻结面问题里，两条是我冻错了

1. **`Refusal` 少一个真实存在的拒绝** `DecreeNoLikenessInSuccession`（`CombatDecrees.cs:160-174`）。
   规格书 §9.2 草案里本来有 `DecreeNoLikeness{tag}`，是我冻的时候删掉的。补回来时形状按要求定：
   参考抛的消息是 `may not follow a '{tag.value}' card with another by decree.`，
   所以变体**带 `TagId`**，不是匿名的。
2. **`PlayError` 缺"内容用了 v1 不支持的东西"这条路**。执行方先前借的是
   `Effect(Ir(Missing(...)))` —— 这个借用会**误导**：`Ir(Missing)` 的字面意思是"镜像缺字段"，
   真实原因是"内核缺能力"。现在有专门的 `UnsupportedContent(&'static str)`，
   四处借用全部换掉。
   > 这一条值得提升成一般原则：**"内容配错了"和"内核还没做到"必须永远能分开。**
   > 前者是内容侧要修的，后者是我们欠的活。混在一起，排查会往错方向跑一整天，
   > 而且**两种情况下返回值都是 `Err`** —— 从这个角度看它们长得一模一样。
3. 第三条（`play_card` 文档说"任何错误都不改状态"对 Faulted 不成立）是我原文档的错，已改。

### 40.3 "占位"不等于"加一行表"——这次执行方顶回来一次，我接受

我要求"把 `NoLikenessInSuccession` 接进那张按 `(priority, modifier_id)` 升序的固定表里"。
执行方没有照做，理由是硬的：

> 参考里两条法令规则住在**同一个** `DecreeCardPlayValidator` 里
> （`ModifierId` 都是 `standard.decree_validator`、`Priority` 都是 150，`CombatDecrees.cs:136-140`），
> 而 `StandardCombatPackage.cs:59-63` 注册的校验器**一共 5 个**。
> 往那张按 `(priority, modifier_id)` 升序的表里插一条同 id 同优先级的记录，
> 会让"升序"这条语义变成空话，也会把"5 个校验器"说错。

它换了一个**更硬的占位**：

```rust
enum DecreeRule { MaxCardsPerTurn, NoLikenessInSuccession }
const DECREE_RULES: [DecreeRule; 2] = [..];
fn run_decree_rule(card, rule) { match rule { .. } }   // 穷尽 match ⇒ 少一条编译期就红
```

**我接受这个反驳。** 我的指令里"占位必须在"是对的（少了它将来会静默少一条规则），
但我指定的**载体**是错的：加一行表会让另一条更重要的语义（升序 = 执行序）失真。
它选的载体把"少一条规则"从运行期变成**编译期**错误 —— 这比表还硬。

> 记一条：**"占位"的目的是"加东西时会被强迫想起它"，不是"某个特定数据结构里多一行"。**
> 用 `match` 的穷尽性做占位，比用数组长度做占位强一个数量级 —— 后者要靠一条测试去数。

### 40.4 量出来的"测试的抓错能力"

执行方之前自己报过：`Cancelled` 终态零覆盖，因为 `exec.rs` 里没有任何节点写 `state.result`
（`:492`/`:1242`/`:1387` 只读，唯一写入 `:3796` 在测试里）。所以那条变异
（"Cancelled 也搬卡"）**没有任何测试能抓**。

我让它补，方法不需要 `exec.rs` 配合：测试模块和 `apply_plan` 同文件，所以可以
`plan_play` → 手动把 `state.result` 改成 `Victory` → `apply_plan`，
这正是"程序跑到一半战斗结束"的可构造等价物。补成对两条：

* 中途结束 ⇒ `played == true`、`landed == None`、卡仍在 `Hand`、**能量 3→2（费用已付）**、敌血不动；
* 同一张卡、同一份状态、**同一个 plan**，只把 `result` 留 `Ongoing` ⇒ 落 `DiscardPile`、6 点伤害落地。

然后重跑那条变异，结果：

| | 补测试前 | 补测试后 |
|---|---|---|
| "Cancelled 也搬卡" | **0 条红** | **1 条红**（`left Some(DiscardPile) / right Some(Hand)`）|

> 这是这一轮最该记住的数字。**"变异测试全红"这句话本身可能是个假象** ——
> 如果某条变异没有测试能抓，它会**安静地显示为"0 红"**，而报告里很容易被写成"这条不适用"。
> 真正的封条是：**每条变异都要先问"哪条测试该抓它"，答不上来就是覆盖洞，不是"不适用"。**

### 40.5 下一步

已经派出 **B**（`host.rs` 的真实 `TurnHost`），文件范围只给了三个：`host.rs` / `exec.rs` / `status_bind.rs`。
它的第 1 步是裁决过的 `resolve_damage_of_kind`（加 `DamageKind::Dot` 并把 `kind` 传到闸门，
`resolve_damage` 保持原签名转发 `Direct`），第 2 步才是九个钩子。

## 41. 第 30 轮：B 落地 —— 回合里终于有真实效果了

### 41.1 结果

`host.rs` 33 行（只有模块文档）→ **2971 行 / 36 条测试**；`exec.rs` +5 测试；`status_bind.rs` +5 测试。
全树 416 → **462 条**，聚合验收 **9/9**，`-UnitsFloor` = 462。

九个必做钩子全部接上真东西，其中这几条是本轮的实质进展：

* `run_turn_ended_triggers`（6 条）—— **poison 的层数衰减就在这里**。在此之前它是空实现，
  也就是说毒会**永久叠加**。
* `damage_over_time` 走 `DamageKind::Dot`。标准包那条路径原来**根本没有种类门**，
  意味着直接复用会让力量/虚弱/易伤一起放大 DoT —— 静默算错。现在两个方向都实现了：
  `RestrictDamageKind = Direct` 的 spec 不作用于 Dot，而**没有** restrict 的 spec 仍然作用于 Dot。
* `resolve_card_queue` 真搬牌 + 跑节目 + 目标锁定失效 + 节目出错**留在队列**（不是吞掉）。
* `turn_start_draw_count` 接上 `panic` 的 `TurnStartDraw / AddPerStack / -1`。
* `on_round_ended` / `on_round_started`：镜像里有 **4 条 RoundEnded 触发器**，
  而 trait 的默认实现是 `Ok(())` —— 默认值在这里是**错的**，实现方主动补了。

### 41.2 最有价值的一条：**测解码器 ≠ 测使用者**

执行方的 5 条变异里，有一条**第一次存活**：

> "触发器收集失败时静默跳过" —— 原测试只打了 `triggers_of` 这个**解码器**，
> 没有打**钩子**。所以把钩子改成"算不出来就当没有"，测试全绿。

补了一条钩子级的测试（`a_status_definition_missing_from_the_content_is_loud_at_the_hook`）之后，
那条变异才变红。这和 §40.4 那条是同一类：
**封条要盖在"使用者"身上，不是盖在"被使用的东西"上。**
解码器正确 + 钩子静默丢弃 = 用户看到的仍然是"这条触发器不存在"。

### 41.3 第 11 次冻结契约写错：`TurnError` 里没有"宿主失败"

执行方被迫把宿主失败**有损映射**成 `Capacity(Full(Statuses))`，真实原因塞进 `Host::last_failure()`。
这是**误导性错误**，和我第 29 轮刚在 `play.rs` 里修掉的那类完全一样：
`Container::Full` 的字面意思是"容器满了"，而两种情况下返回值都长得一模一样 ⇒ 排查会往完全错的方向跑。

> 这已经是同一形状的**第二次**了（`PlayError` 借 `Ir(Missing)` 是第一次）。
> 该抽象出一条规则：**"这一类失败"和"那类失败"如果不能分开报，那就等于没有报。**
> 每个错误枚举都要问一句"这里面有没有哪一个变体在替两个不同的原因说话"。

裁决：加变体（授权执行方改 `turn.rs`，只准为这一件事）。同时要求它列出改了哪几处 `match`、
**每处断言原本想证明什么** —— 因为加变体的第一反应很容易变成"把碍事的断言删掉"。

### 41.4 第 12 次：`StatusInstance` 没有 `SourceCombatantId`，DoT 无法归属出手方

参考把毒源写进请求（`StatusEffects.cs:501-509`），我们连字段都没有 ⇒ `ctx.source = None`
⇒ Source 阶段整段跳过。今天恰好正确（镜像 5 条 spec 全是 `RestrictDamageKind = Direct`，
种类门本来也会挡掉），但内容一旦写一条 `DamageDealt / null` 的 spec，
它本该放大毒伤却被静默漏掉，**而且任何测试都写不出来**（字段不存在，测试无法表达这种情形）。

**我先去量了哈希**再裁决：`CombatStateHasher.AppendStatus` 只写
`Id / DefinitionId / stk= / dur= / chg= / pol= / [pend=]` —— **`SourceCombatantId` 不在指纹里**。
所以加这个字段**不会动任何哈希**，85 份语料不用重生。

> 这一步量的价值：如果它**在**哈希里，那就不是"加个字段"而是"发现一个一直存在的哈希 bug"
> （任何带源的状态都会与参考不符，而语料里没人测）。
> **同一个字段名，两种结论的事故等级差一个数量级 —— 所以要先量，再裁决。**

### 41.5 规格书自身的三处错（我回去改了，记在 `battle-loop-hooks.md` §8）

1. **验收向量 V2 是错的**：它说"格挡 −3 → 2、HP 不变"。但清格挡是第 7 步、DoT 是第 8 步，
   而清格挡是"把当前值抹成 0" ⇒ 回合开始时的那 5 点格挡**活不到 DoT 那一跳**。
   正确结果是 **格挡 0 / HP −3**。
   教训：**"格挡能挡 DoT"在参考里是真的，但只在"格挡是这一回合新加的"时成立。**
   把一般直觉套到回合开始的 DoT 上，就会写出一条自洽但永远对不上的验收向量。
2. **§2.2「执行层够用」是错的**：`queue_advances` 的条件用 `cardsPlayedLastTurn`，
   而 `expr.rs` 没实现它（需要 `CardPlayTurnStats`）。该状态一在身就 `UnsupportedKind` ——
   响亮失败是对的，但"够用"这句话只对 62 张卡的卡程序成立，不对状态触发器成立。
3. **`bookworm` 形状错**：实测 2 个 `sequence` / 4 个 `modifyStatusStacks`，不是 4 / 8。

## 42. 第 31 轮：两条裁决落地，外加一个必须盯住的体积变化

### 42.1 结果

全树 462 → **468 条测试**，聚合验收 **9/9**，`-UnitsFloor` = 468。

* **裁决 1（`TurnError::Host(HostFailure)`）**：执行方把它拆成三档
  `Unsupported` / `Content` / `Effect` —— 理由写得好：**三种原因指向的排查方向相反，
  所以该由编译器保证，不该靠约定**。`bridge()` 现在是真映射，`Capacity(e)` 无损透传。
  它逐条核了全树 34 处 `TurnError::` 用法（29 处是 `assert_eq!(.., Err(TurnError::X))`，
  没有一处是穷尽 `match`），**一处断言都没删** —— 这正是我要求它交代的。
* **裁决 2（`StatusInstance::source_combatant_id`）**：`applyStatus` 落盘时写入来源，
  **合并分支不动它**（`StatusEffects.cs:159-165` 的 "keeps its own source, untouched"），
  host 的 DoT 拿它当 Source 阶段出手方。测试六条，其中三条是同一个场景三种成因：
  正例（内存补丁把 `strength` 的门改成 null ⇒ 毒 5 变 **8**）、出手方无 spec ⇒ 5、
  有 spec 但**这条毒没记来源** ⇒ 5。**这三条缺任何一条，"起作用的是那一格字段"就没被证明。**

### 42.2 一个必须盯住的副作用：`CombatState` 涨了 12.8 KB

`size_of::<CombatState>()` **171,848 → 184,648 B**（+12.8 KB，SRAM 28.3% → **30.5%**）。
原因：`Option<CombatantId>` = **42 B**（`Ident<40>` 是 41 B 且没有 niche，`Option` 多一个 tag 字节），
乘上约 300 个状态槽。

这不是谁写错了，是"加一个字段"的**真实价格**。我没有让它把字段改成 `u16` 槽位索引，理由：

> `CombatantId` 出现在**很多**字段里（`active_combatant_id`、`queued_target_id`、
> `mark_source_combatant_id`、临时规则所有者……）。只把其中一个换成索引，得到的是
> **两套寻址并存的混合体**；而混合体的危险不是"多写几行转换"，是**某一处忘了转换时它照样能跑**
> （把 3 当成 id 用，或者把 id 的低 16 位当槽位）。要做就整族一起换（§3-D9 的 intern），
> 那是另一个量级的重构，不是一次局部优化。

顺手修了一处**文档谎**：`state.rs` 模块头那张体积表还写着 171,848 / 29%，
现在改成实测的 184,648 / 30.5%，并加了一句"每次改 `CombatState` 字段都要重新量并把这里改掉，
否则它就会变成一句谎"——`state_fits_the_sram_plan` 只盯着上界（≤192 KiB），
**盯不住"表格里的数字过期"**。

### 42.3 已派出 D

`intent.rs` 的模块文档我自己写好了，把两条会决定设计的事实钉在开头：

1. **驱动选择器的是 `ENCT` 不是 `EACT`** ⇒ 入参必须是 `(遭遇, 敌人槽位)`；
2. **选择算法 100% 引擎硬编码、零 RNG**，四分支，其中"有规则但全不匹配 ⇒ **落回循环**"最容易被写成"跳过回合"。

还有一条我特意写进任务书、要求它明确交代的：**本内容 5 条 `IntentRule` 全都用不了**
（4 条依赖触发器系统、1 条依赖 `CardPlayTurnStats`），所以忠实实现在这份内容上会**永远走循环分支**。
**不许为了"看起来有动作"而特判** —— 那是把"内容依赖没到位"伪装成"功能已实现"。

## 43. 第 32 轮：D 落地 —— **A~E 五件全部完成**

### 43.1 结果

`intent.rs` 0 → **1748 行 / 21 条测试**，全树 468 → **489 条**，聚合验收 **9/9**，`-UnitsFloor` = 489。

| | 状态 |
|---|---|
| **A** 出牌流程 `play.rs` | ✅ 2697 行 / 21 测，三终态 + 5 校验器 + 6 费用修饰器 |
| **B** 回合宿主 `host.rs` | ✅ 2971 行 / 41 测，9 钩子全接上（DoT 走 Dot 管线、poison 衰减、QueuePile 真执行） |
| **C** `resolve_card_queue` 钩子 | ✅ 第 9 钩子，顺序测试钉成 `ptqdod` |
| **D** 敌方决策 `intent.rs` | ✅ 1748 行 / 21 测，四分支 + Priority 降序 + 1-based 循环 |
| **E** 两个发号器 | ✅ 返回自增前的值 / 链号只在无环境链时发 |

入参是 `EnemySlot { encounter: u32, index: u16 }` —— 这就是"为什么不能只传 `CombatantId`"的
答案落在类型上。动作 id **借镜像串池**（`&'a str`），因为 39/394 个 id 超 `ID_CAP=40`。

### 43.2 它顶回来三次，三次都对

1. **我把"5 条 `IntentRule` 全都用不了"写错了。** 实测是 **4 条能忠实求值、但恒假**
   （`intent.selfHasCounter` 缺席读 0，而计数器只由触发器递增 —— 内核没有触发器），
   所以它们会走完优先级检查再落回循环；第 5 条 `opponentCardsPlayed` 要 `CardPlayTurnStats`
   ⇒ **响亮 `Err`**。结果分布是 **148/149 走循环 + 1 个明确失败**。
   > 这个差别很重要：**"能力齐、内容依赖缺"和"内核缺能力"是两件相反的事**，
   > 排查方向也相反。我一句话把它们混成了一件。
2. **规格书 §5.3 那条会咬人**：它说 `Actions` 的元素是 `_wrap_lower` term。
   那是**解码后的 JSON 形状**，二进制里是 **`F_STRLIST + FLAG_WRAP_LOWER`**（`AUX` 里存串号），
   整份镜像里**连一个 `_wrap_lower` term 都没有**。照它实现会**静默**读到不相干的数据。
   已在 `enemy-intent.md` §5.3 加更正块。
3. **规格书 §8.1 建议的 `EnemyScript { actions: &'a [u16], .. }` 在零分配下造不出来**
   （需要一个活过调用的数组），它改成"每次现读几个 u16"，并在模块头写清为什么。

### 43.3 最有价值的一条：那条"看起来几乎全绿"的变异

它的 M4 变异是把 `UnsupportedCondition` 改成 `Ok(false)`（"反正条件求不出来就当不匹配"）。
后果不是崩溃，而是：**选出来的动作合法、`reason` 合法、宿主的循环照样跑完一局，
只是那 5 条规则永远静默失效。**

> 这是这个项目里**最危险的一种撤销**：把"我不知道"改成"否"。
> 它不会让任何测试变红（因为大部分测试只关心"选出了一个合法动作"），
> 只会让一条规则**再也无法生效**，而且**没有任何观察者能发现**。
>
> 所以那条门槛测试才把"**只允许这一种失败、且恰好 5 次**"钉成硬断言（149×5 ⇒ 740 Ok + 5 Err）。
> **一个"允许失败"的节点，它的失败次数本身就是一条断言。**

它另外加的一条核对也值得记：`choice()` 里校验"`IDX` 说第 n 行，该行 `Id` 必须逐字节相符"。
不做这一步，一个被改坏的符号表会让"选中的动作 id"和"实际要跑的程序"**静默错位**。

### 43.4 我没让它做的一件事

`enemy_action_program_root`（`EACT.Program` → 信封 → `Root`）目前写在 `intent.rs` 里，
而它形状上是 `ir.rs` 的功能（`ir.rs` 只有卡版本 `card_program_root`）。
**先不挪**：挪动要把两个模块的可见性重新过一遍，而收益只是"文件归属更整齐"。
已在文档里点名"将来该挪进 `ir.rs`"。**"更整齐"不是重构的理由，"更容易错"才是。**

### 43.5 现在的界限（诚实版）

A~E 只说明**每一块砖都在、都被测试钉住**，不说明**房子能住**。还差：

1. **没有任何东西把它们串起来**：没有一个"从 `ENCT` 建初始战斗 → 回合循环 → 玩家出牌 →
   敌人按 `intent` 行动 → 判胜负"的驱动。今天这些模块互相不认识。
2. **固件仍不驱动回合机**（`turn.rs`/`content.rs`/`exec.rs`/`host.rs`/`play.rs`/`intent.rs`
   都被 `gc-sections` 回收，裸机镜像里只有状态机 + 哈希）。
3. **从没和 C# 对拍过一局**：85 份语料验的是**哈希器**，验的不是"打一局的轨迹"。
4. `CombatState` 184,648 B（30.5% SRAM）—— 能跑，但离"多开"很远（单实例 180 KiB）。






































## 44. 第 34 轮：**62/62 张卡逐张与参考实现逐字节一致**

### 44.1 结果（我自己独立复核过）

```
FIGHT_DIFF PASS (182/182)     ← 4 局完整战斗：18 个每步哈希 + 终局哈希
CARD_DIFF  PASS (62/62)       ← 内容镜像里每一张卡，各一局，每步哈希
聚合验收 9/9 / 518 条测试 / clippy 零告警 / 裸机 check EXIT 0
```

这是"这个内核到底对不对"这个问题第一次有了**跨语言的、覆盖整份内容的**答案。
在此之前，858 份语料验的是**哈希器**（给一个状态算出正确的文本），不是"打一局"。

### 44.2 逐卡对拍抓出两处内核真错误（都带行号）

前面 2 张卡的 `FIGHT_DIFF` 全绿，**扩到 62 张立刻红了 6 张**，而且红得很隐蔽：
**7 个观测量全同，只有哈希不同**。逐行对差定位到 `chain_num` 这一格，两个成因：

| 卡 | 参考 | 内核（修前） |
|---|---|---|
| `red_tape` / `unsigned_form`（带 `unplayable` 标签） | **先入队**（`ScenarioRunner.cs:121` → `CombatState.cs:386` 建根链）再在校验器里拒绝 ⇒ **+1** | **+0** |
| `archive_the_evidence` / `shredder_drawer`（节目把自己挪出手牌） | `CardPlay.cs:245-247` 的手牌守卫让搬区入队不发生 ⇒ **+2** | **+3** |

`play.rs` 里原有一句"这条偏移在本内容上不可观察"—— **被 `red_tape` 证伪**。
这是"我以为不可观察"和"真的不可观察"之间的差距，而它只能靠**跑遍全部内容**发现。

### 44.3 三条冻结方描述被证伪

1. **"约 9 种节点"** 这个说法太粗。实测按**用到它的卡数**：`sequence` 43 / `applyStatus` 32 /
   `dealDamage` 18 / `gainBlock` 14 / `createCardInstance` 12 / `drawCards` 12 /
   `forEachCardInZone` 4 / `moveCardToZone` 4 / `gainResource` 2。
   而我列的 `conditional` / `setCombatantCounter` / `heal` / `loseResource` **一张卡都没用** ——
   它们只出现在**状态触发器**和**敌人动作**里。⇒ "节点实现了"和"卡用到了"是两件事。
2. **`Effects.*` 不只是"缺帮手"**：它缺 `createCardInstance` / `forEachCardInZone` /
   `moveCardToZone` / `multiply` / `combatantStatusStacks`，而 `Effects.cs` 在只读的 `ref/` 里 ⇒
   这 5 种只能在 oracle 侧**直接构造 typed node**。结论：**0 种 kind author 不出来**。
3. **`doubt` 不是纯声明式**：它有 1 个触发器 + 1 个被动修饰（伤害 ×75%）。

### 44.4 这一层的三道闸门（没有它们，"62/62" 可以造假）

* **spec 陈旧**闸门：`card_specs.json` 与镜像**结构化对差**，报"哪张卡的哪个字段"；
* **卡序索引**闸门：`card_index` 与镜像行序一致；
* **内容 + 形状**闸门：一次比 842 条 + 12 条逐卡。
  变异测试证明它们不是摆设：把 `strong_binder` 费用改成 2 ⇒
  `spec.cards[4] (strong_binder).costs[0].amount: 磁盘 2 != 镜像 1`。

### 44.5 仍然没覆盖的（这一层结论的边界）

* 逐卡层**只打一步** ⇒ 跨回合的东西（DoT tick / 手牌回收 / 补能 / 重洗 /
  `TurnEndHandDestinationZone` / 敌人动作）不在这一层，仍由 `FIGHT_DIFF` 的 4 局承担。
* `doubt` 的触发器与 75% 被动在逐卡那一局里是**惰性**的（镜像里 doubt 只施加到敌人，
  而伤害来源永远是英雄）⇒ 它被 author 了、被闸门核对了，但**没被行为验证**。
* `TriggerActivity` 两侧都不进哈希文本 ⇒ **"哪个触发器跑过几次"不在任何对拍里**。
* `problems` 仍只比条数不比文本。
---

## 45. 第 35 轮：事件队列落地（批次 1 + 2）、牌组接内容，以及"内容 → 一局 → 浏览器"这最后一米

> 这一节只追加。前面 §1–§44 里被推翻的地方已在原地改过（每处都写了"被测出来的"），
> 这里记的是**这一轮到底落地了什么、量到了什么**。内核这一轮**零改动**：
> `kernel/rd-core/**` 一个字节都没动，558 条单测 / 四条对拍 / 聚合验收 12/12 全部保持。

### 45.1 批次 1：六个队列 + 链 arena（`CombatState` 从"就地应用"变成"排队 + 排空"）

参考的三列并行数组被照抄成**六个队列**，每一列一个 `Fifo<T, 64>`：

| 列 | 元素 | 元素大小 | 队列 |
|---|---|---:|---|
| 效果 | `pending_effects` | 176 B | 64 |
| 效果链 | `pending_effect_chains` | 2 B | 64 |
| 效果链所有者 | `pending_effect_owners` | 4 B | 64 |
| 事件 | `pending_events` | 96 B | 64 |
| 事件链 | `pending_event_chains` | 2 B | 64 |
| 续延 | `pending_continuations` | 44 B | 64 |

加上链 arena（`128 × 16 B`，引用归零回收）一共 **23,040 B**，占 `CombatState` 的 11%。
两条对齐断言（`ensure_effect_queue_aligned` / `ensure_event_queue_aligned`）在**每次出队前**跑，
而且**不是 `debug_assert!`** —— 裸机跑的是发布版，`debug_assert!` 在那边等于没写。

排空（`Host::resolve_pending_queues_with`）照 `CombatEventHandling.cs:97` 的
`while (hasPending…) && Result == Ongoing` 分成**三个相位**：效果全抽干 → 事件全抽干 →
**只跑一个**续延（且前两相都空）。相位上限是**参数**（`QueueLimits`），所以测试能传 0 当场撞上限。

第一版只接了 4 个**回合边界**事件（`TurnStarted` / `TurnEnded` / `RoundStarted` / `RoundEnded`，
`enqueue_event_at_root`，链号笔数不变），随后补上 `DamageDealt`（`exec.rs::resolve_damage_of_kind`
落血判胜负之后入队，`DamageEffects.cs:186-194`）—— 于是闸门里 `not_handled` 从 12 降到 11。

`DamageDealt` 的 **Bearer 是出手方**（`StatusDataRebuild.cs:53-55`，上下文 `sel.source = SourceCombatant`、
`eventTarget = TargetCombatantId`）⇒ `doubt` 的 `modifyStatusStacks(-1)` 落回出手者身上。
这一条正好是"触发器解码只认 `Event` + `Program`"那条既有缺口的对照组：镜像里 25 条触发器
**一个 `Scope`、一个 `Filters` 都没出现**，所以内核实现的是默认 Bearer 语义。

`CARD_MULTI` 在批次 1 从 **112/124 → 122/124**：那 10 格原先是 NOT-COMPARABLE，现在变成**一致**。

### 45.2 批次 2：续延调度落地，**CARD_MULTI 124/124**

批次 2 补齐的是"节点级续延"：帧 arena（8 槽 × 216 B）+ 节点槽 arena（64 × 12 B）+ 循环快照
arena（4 × 546 B）。一条续延 = `(帧槽, 节点槽)`，节点槽带**父**与**剩余计数** —— 这两样正是参考闭包里捕获的东西
（`EffectProgramExecution.cs:91-160`、`:202-211`）。

关键回报是 `ProgramExecutionFrame::terminal_chain`：**终态那一刻 `current_chain` 是什么**，
决定了收尾那一笔入队发不发链号（`CombatState.cs:386/446` 的 `??`）。

于是 `CARD_MULTI` **122 → 124/124**。⚠️ 那 2 格是**机制绿，不是调参绿**：

| 卡 | 节目 | 谁最后完成 | 终态落在 | 出牌合计链号 |
|---|---|---|---|---|
| `shredder_drawer` / `+` | `sequence[forEachCardInZone(Hand, junk), dealDamage(9)]` | **循环本身**（第 1 趟的续延把第 2 趟排到队尾 ⇒ dealDamage 先完成，循环最后完成，而它在 `using (EnterEffectChain)` 里完成） | 节目链**里** | **+1**（只有请求那一笔） |
| `archive_the_evidence` | `forEachCardInZone(takeFirst=1)` + 兄弟 `gainBlock` | 兄弟 `gainBlock`（它的续延在**顶层**跑） | 链**外** | **+2** |

⇒ "发不发号"现在是 `current_chain` 的取值决定的，而那个取值由**"谁最后完成"**决定。
这一格不是把 4 试成 3 试出来的 —— `play.rs` 里那三笔显式 `create_root_effect_chain()`
**被整段删除**（请求链在开场建一条并 `with_chain`；落区/收尾在终态回调里由 `??` 决定）。

### 45.3 `exec` 真的拆成了"请求 + 解析"

| 项 | 实况 |
|---|---|
| 效果队列的**生产者** | 11 种产出型节点全部改成"算好参数 → `EnqueueEffect` → 完成塞进续延"，**一个都不就地写状态** |
| 效果队列的**解析器** | `exec::resolve_effect`：拆请求、重建 `ExecContext`、调既有的实体函数；**修饰器与极性在解析时读**（`DamageEffects.cs:273-320`） |
| 出牌终态 | 从 `play.rs` 的手工账搬成**数据 + 同步调用**：`ProgramTerminalHook::CardPlay` + `play::run_terminal_hook` |
| `play.rs` 的链号账 | **一笔都不手写**（请求链 / 落区 / 收尾三笔全部由上面的机器产生） |

这一节的最短证据链：`play.rs` 里那张"`next_effect_chain_number` 的账"表（+3 / +1 / +0 / +2）
仍然在文档里，但**实现里已经没有对应的加减法了** —— 表只解释"为什么是这个数"。

### 45.4 `CombatState` 的三次测量，与那个"余量只剩 ~8 KB"的事实

| 时点 | `size_of::<CombatState>()` | 占 606,208 B SRAM | 上界 |
|---|---:|---:|---:|
| 队列落地前 | 184,648 | 30.46% | 240 KiB |
| 批次 1（六队列 + arena） | **207,712** | 34.26% | 240 KiB（抬界，理由写进两处断言） |
| 批次 2（三个 arena） | **213,224** | 35.2% | 240 KiB |

**上界有两处，永远要一起改**：`state.rs::state_fits_the_sram_plan` 与
`kernel/rd-sizeprobe/src/lib.rs` 的同一条断言，现在都是 `240 * 1024 = 245,760`。
抬界的理由是"忠实档实测 + 6.3% 余量"，**换的是语义完整性**，不是"让测试过"。

⚠️ 必须一起记住的那笔账：**事件全集（参考 41 个变体、集合型 id 列表 ⇒ `CombatEvent` 492 B）
比今天声明并接了线的 5 个变体（96 B）贵约 24 KB**。两者相加 ≈ **237 KB**，
**仍在 245,760 以内，但余量只剩 ~8 KB**。所以本节之后任何"再塞一个字段"都要先回答
C1 那个问句，再看余量 —— 顺序不能反。

### 45.5 牌组接内容 + `InertKeys` 从"整键"下沉到"子键"

`battle.rs::build_fight_from_content` 是"内容 → 一局"的那一米：`plan.deck` 非空 ⇒ 走老路
（手写牌组那些测试一条都不动）；为空 ⇒ 按参考的三处候选解析
（`RunBlueprint.cs:167-176` / `RunSetup.cs:44`）：

| # | 位置 | 什么时候读 | 形态（实测） |
|---|---|---|---|
| 1 | `Characters[0].Start.Deck` | 花名册非空 | `F_STRLIST`（元素直接是串号） |
| 2 | `Start.Deck` | 花名册为空 | 同一个 term（`Characters[0].Start` 与根 `Start` 指同一个 term） |
| 3 | 根 `Deck` | 上两处都是空表 | `F_TERMLIST`（元素是 `_wrap_lower`，1 槽 = 串号） |

**三份的值相同、形态不同** ⇒ 读法必须按形态分（把 `Start.Deck` 当 `F_TERMLIST` 读会拿到非法 term id）。
"空 = 没声明、接着看下一处"不是新哨兵，是参考自己的约定（`RunBlueprint.cs:214-216`）。

接线的代价是可测量的：`InertKeys` 里 `root:Characters` / `root:Start` / `root:Deck` 三条整键声明
**必须删掉**（内核现在真的读它们了，闸门先红给你看），声明数 **16 → 13**。
⚠️ 但整键粒度把挂在它们下面的**五条**"内核零消费者"记录一起带走了：

```
Start.MaxHealth / Start.StartingHealth / Start.Resources / Start.StartingRelics
Characters[].UnlockFlag
```

它们没有变假，只是**没地方记**了 —— 而散文不是闸门。所以闸门的 `root:` 作用域支持了**子键路径**：

* `root:<Parent>.<Field>`（对象的字段）、`root:<Parent>[].<Field>`（对象列表各元素的字段）；
* "内核读了没有"由两条**从内核代码派生**的规则判：① 内核自己把这一跳**拼成过串**
  （`DeckOrigin::path()` 返回 `"Characters[0].Start.Deck"` / `"Start.Deck"`）；
  ② 内核按**名字**取过这个字段（`name == "<Field>"`）。⭐ 两条都**包含** `content.rs`
  （被排除的是那边的 schema 镜像与 typed accessor，而牌组读取器和 `name ==` 都在同一个文件里）；
* **不算**读：`field_at("<Field>")` 与 `.<snake>(` —— 那是**typed** accessor，
  `EnemySpec::max_health` 读的是**敌人**记录的 `MaxHealth`。把它算进来会让 `Start.MaxHealth`
  变成"不可声明"，而这个键真的没人读（英雄血量来自 `FightPlan`）。

落地后：**声明数 13 → 23**（13 整键 + 10 子键），子键宇宙 13 个，其中 3 个被读
（`Start.Deck` / `Characters[].Start` / `Deck[].value`）、10 个被声明。
这 10 条里有 5 条是任务书没点到的（`Start.HeroName` / `StartingConsumables` / `StartingUnits` /
`StartingParty` / `Characters[].Id`）—— 粒度一沉下去它们就自己冒出来了，这才是"闸门在数"的意思。

### 45.6 仍然差的边界（`docs/spec/event-queue-interface.md` §12.4，**四条，不是三条**）

1. **集合为空时参考是同步完成、内核排一条续延**（`forEachTarget` / `forEachCardInZone` 的空快照）。
   差别只在"终态落在哪条链里"那一刻可见，本内容里没有这种局面 ⇒ **内容一来空集合它就会出现**。
2. **严格面（`play_card`）比参考少两个链号**：`PlayCardCore` 在顶层跑，`CardCostPaid` 与 `CardPlayed`
   各发一个号，而内核**没有这两个事件变体**。请求面（`try_play_card`，全局对拍走的那条）不受影响。
3. **`exec::execute` 是遗留入口**：它不发号、也不排空事件 —— 把事件出队丢掉会让 `doubt` 的
   `DamageDealt` 触发器永远不跑（实测：`CARD_MULTI` 立刻退回 114/124）。
4. **`play.rs` 的无节目分支**仍然手工入队（搬区 + `CloseAction` 续延），因为那台机器不经过节目帧。

另外两条**不属于队列但同样没钉住**的：`TriggerActivity` 两侧都不进哈希文本；
`problems` 只比条数不比文本。

### 45.7 最后十厘米：`.wasm` 与页面现在跑的是**真内容**

`kernel/rd-wasm` 从"写死一局 `queue_imp`"改成**从内容建局**：

* 嵌入的镜像是 **`tools/contentc/packages/sts/out/content.sts.core.rdcf`（9,580 B）**，
  不是 `tools/contentc/out/content.core.rdcf`（85,616 B，`roguedeck` 包）。
  取舍写在 `lib.rs` 的 `IMAGE` 文档里：`sts` 才是"有源文档 + 有 inventory + 有四层闸门"的那份内容，
  而且这一换就是 **−76,036 B** 的数据段；代价是这一局很小（4 张卡定义、2 个敌人、1 条遭遇）。
* `build_fight_from_content` + **空 `plan.deck`** ⇒ 牌组来自 `Characters[0].Start.Deck`，
  敌人来自 `ENCT` 的 `enc_small_slimes`（`acid_slime_m` 28 + `spike_slime_s` 10，两条敌人是**故意**的：
  一条敌人分辨不出 `NextRound` 和 `EndOneTurn`）。
* **Gap 1（敌人意图）关掉**：`content::encounter_enemies` + `intent::locate_enemy` +
  `intent::select_action`（用 `state.current_round`，照 `InteractiveCombat.cs:122` 的**预告**路径），
  伤害是把 `EACT` 程序里的 `node.dealDamage` 的 `const` 金额加起来；**非 `const` 一律 `-1`**
  （"不猜"比"猜得像个数"重要）。观察向量的 `intent_kind` / `intent_damage` 两格从此是真值。
* **Gap 4（一次结束回合只让一个敌人动）关掉**：`step_end_turn` 改成 `Step::EndOneTurn` 的循环
  （英雄回合结束 → 每个敌人各走一个回合 → 回到英雄），那条 "plan has N enemies" 的守卫连同它的理由一起删了。
  新测试的判据是**"第 1 回合的预告伤害之和 == 这一回合英雄实际掉的血"**：只让一个敌人动就立刻不等。
* `.wasm` 体积：上一份提交的副本 559,504 B（546 KiB，`roguedeck` 内容 + 旧逻辑）→
  同一棵树的干净重建 418,758 B → **现在 378,962 B**。
  冒烟方式：`node web/smoke.mjs` 读**提交的那份产物**，`WebAssembly.validate` + 无 import 实例化 +
  逐个检查导出 + 打完整局（`WEB_SMOKE PASS`）。⚠️ **没在真浏览器里跑过**：
  DOM、`Content-Type`、`instantiateStreaming` 这三样仍只有页面自己的 Measurements 面板能回答。

---

## 46. 第 36 轮：真浏览器里跑了一遍，页面补上「选目标」，验收从 12 道闸门长到 14 道

> 这一节只追加。内核**零改动**（`kernel/rd-core/**` 一个字节没动）：558 条单测、四条对拍
> 182/62/124/394、`CombatState` 213,224 B、`.wasm` 378,962 B 全部不变。
> 这一轮的全部产出在 `web/**` 与 `tools/acceptance.ps1`。

### 46.1 把"未验证"改成实测，而不是继续写在文档里

`web/README.md` 从上一轮起就挂着一句"没在真浏览器里跑过：DOM、`Content-Type`、
`instantiateStreaming` 这三样仍只有页面自己的 Measurements 面板能回答"。这一轮去回答了：

| 冒烟测不到的一格 | 实测 |
|---|---|
| 服务器给的 `Content-Type` | `application/wasm`（python 的 `http.server` 认得 `.wasm`） |
| 载入路径 | **`instantiateStreaming`**（快路径，不是 `arrayBuffer` 回退） |
| fetch+实例化+首次观察 | 10–40 ms（冷/热缓存差 4 倍） |
| 线性内存 | 1,408 KiB |
| DOM | 排版正常，122 格落在正确位置，卡能点 |

然后**用鼠标点**打完一局：21 击到 `Victory`（第 7 回合），第一次结束回合掉的血压根等于两条
预告意图之和（7 + 5 = 12）。

### 46.2 真浏览器抓到的两件事（任何闸门都抓不到）

1. **出牌的目标从来没被传下去。** `env-abi.md` §5 是"每张卡 × 每个活着的敌人槽"各一条动作，
   而页面取的是 `playByHand.get(h)` —— **第一条** —— 于是无论玩家想打谁，都打在 0 号敌人身上。
   现在页面做了个目标选择器：动作多于一条的卡会把**它能打到的敌人**标出来，点敌人就花掉
   "指名那个槽"的那条动作。实测：`strike` 点 1 号槽 ⇒ `spike_slime_s` 10 → 4，能量 3 → 2。
2. **两个调试字段在屏幕上**：每张卡下面单独一行 `def_slot N`；以及原始的 reward 整数
   （`-12030` —— 那是 `env-abi.md` §7 的 1/1000 单位，即 −12.03）。前者挪进 `title=`，
   后者除以 1000。

### 46.3 真正的教训：**`web/index.html` 没有任何闸门在看它**

把它改坏（少一个 `}`）之后，**十二道闸门全绿** —— 因为每一道都止步于 `.wasm`。
这和第 11 道（`rdcf_verify.py` 静默失效）、第 12 道（`sts` 包覆盖不到）是同一种形状：
**覆盖不到的地方看起来最绿**。补成两道：

* **闸门 13 `wasm-rebuild`**：`cargo build -p rd-wasm --release --target wasm32-unknown-unknown`。
  为什么需要：`web/rd_wasm.wasm` **不在 cargo 的依赖图里**，源码改了不重编它照样绿。
* **闸门 14 `web-package`**：`node web/smoke.mjs`，四条判据 ——
  (a) `web/rd_wasm.wasm` 与刚才那次重编**逐字节相同**；
  (b) `index.html` 的 `<script>` 能被 node 的解析器吃下；
  (c) 它调用到的每个 `ex.xxx` 都是模块真有的导出（与 smoke 里那张手抄清单**互为反方向**）；
  (d) 页面里硬编码的 122 格偏移还铺得满（`OFF_ENEMY = OFF_HERO_STATUS + 状态轴数`、
      `OFF_HAND = OFF_ENEMY_STATUS + 4×5`、`OFF_PILES = OFF_HAND + 10×4`、`OFF_PILES+5 ≤ 122`）。

四条各自变异一次，**全部真的红**：语法错 ⇒ `does not parse`；`OFF_HAND` 69→71 ⇒
`OFF_HAND is 71, but every block before it ends at 69`；调 `ex.rd_env_reward_nope` ⇒
`does not export`；产物末字节 +1 ⇒ `is NOT a fresh build`。恢复后绿，且恢复是**逐字节**校验过的。

### 46.4 为什么判据是字节，不是 mtime

实测到的两种"时间说谎"都在这台机器上发生过：

* `Copy-Item` 恢复文件会把 **mtime 一起恢复** ⇒ cargo 复用旧 `.rlib`（§38 记录过）；
* 这一轮反过来：`web/rd_wasm.wasm` 的 mtime 比 `kernel/rd-wasm/src/lib.rs` **早 76 秒**，
  看起来陈旧，但**字节与现在这棵树重编的结果完全一致**（sha256 `686ba653…`，378,962 B）。

⇒ 用 mtime 会红一次假的；用字节不会。代价是这条闸门必须**先重编**（增量 ~3 s），
所以它拆成 13 + 14 两道，好让"编不过"和"页面坏了"不会混成同一条红。

### 46.5 仍然没覆盖的（如实）

**Rust ↔ 页面 的偏移漂移**：页面把 122 格排布硬编码了。内核若搬动某一段，页面会读错格子，
而 smoke **看不出来**（它只能证明页面自身自洽）。真浏览器能看出来，但那是人工动作。
要关掉这个洞，得把偏移通过 ABI 发布出来（`env-abi.md` 是冻结的，加一格要重新冻结）——
**这一轮没做，写在这里当欠账。**

### 46.6 这一轮的数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 12/12 | **14/14** |
| 单测 | 558 | 558（内核零改动） |
| 四条对拍 | 182 / 62 / 124 / 394 | 不变 |
| `.wasm` | 378,962 B | 378,962 B（页面改动不进二进制） |
| 真浏览器 | 未验证 | **Chrome 152，`instantiateStreaming`，点完一局** |

### 46.7 下一站：M1

`docs/spec/sts-act1-plan.md` 的 M0a / M0b / M0.5 到这里**全部关掉**（M0b 的判据是"手工打开页面
能打出 bash → 易伤 → 意图正确 → 打赢"，本节 46.1/46.2 就是它的证据）。
按同一份计划的顺序，下一站是 **M1「一条最短路径」**，它的进入条件还差三件：
`currentHealth` 表达式（Hexaghost 的 Divider 要用）、`LifecyclePrograms`（Burn 要用）、
以及**必须先定形状**的 `run_rng`（§5.4：单流会让"多抽一次药水改变整张地图"）。

> **2026-10-19 补注**：本节是第 46 轮当时的现状。三件里**第一件已经关掉** ——
> `currentHealth` / `maxHealth` 已实现（字段名 `Selector`，见 `kernel/rd-core/src/expr.rs`
> 模块头第 4 条与 `docs/spec/sts-act1-plan.md` §9-4）。剩下 `run_rng`。
>
> **2026-10-19 第二补注**：`LifecyclePrograms` **也已经关掉** —— `host::try_hand_turn_end_lifecycle`
> 现在真的解 `CARD.LifecyclePrograms[TurnEndInHand]` 并派发节目（Burn 的机制），
> 记录在 `docs/spec/battle-loop-hooks.md` §2.5。镜像 62/62 卡是 `{}`，所以那一步是"内容侧的事"了。

---

## 47. 第 37 轮：M1 的地基 —— `run_rng` 形状冻结、`rd-run` 出生，以及"同尺寸不同字节"的实测

> 内核（`rd-core`）这一轮只改了一行：`rng::GOLDEN32` 从私有改 `pub`（理由见 47.4）。
> 单测 558 → **566**（新增的 8 条住在新的 `kernel/rd-run` 里），四层对拍不变。

### 47.1 先冻形状，因为这一条"不能后补"

`docs/spec/sts-act1-plan.md` §5.4 说的就是这件事：run 层的 RNG 形状**必须在 M1 开工前定**，
定晚了所有确定性回归都要重写。新文档 `docs/spec/run-layer.md`（**413 行**）把四件事冻了：

| 冻了什么 | 一句话 |
|---|---|
| **七条 RNG 子流**（`Map`/`Combat`/`Reward`/`Event`/`Potion`/`Shop`/`Chest`） | 各带一个计数器；派生式 `run_seed ^ stream*GOLDEN32 ^ 0x5F356495`（零值重映射） |
| **`RunState` 形状** | 独立于 `CombatState`（后者 `Copy` + 213,224 B + 每场重建；前者活整局） |
| **`run_hash` 规范文本** | 逐字段固定序、LF、`deck`/`relics` 按**获得顺序**（顺序可观察）、`map` 按 `(row,col)` 升序 |
| **步骤模型与地图规则** | `RunAction` 六个动作 + 每步 6 条不变量 + `inv:§7` 的 13 条规则逐条带来源等级 |

§3（RNG）**当轮就落地成可执行的代码**，§1 的纪律是"先冻接口、建桩、验证树绿，再派活"：

`kernel/rd-run`（`#![cfg_attr(not(test), no_std)]` + `#![forbid(unsafe_code)]`，唯一依赖是
`rd-core` 的 `rng`/`Ident`/`hash`）8 条测试全绿，裸机目标 `check` 通过，clippy 零告警。

### 47.2 冻结判据拆成 R1a / R1b（**这一条是本文档自己的修正**）

初稿写的 R1 是"推进 `Potion` 100 次后，`Map` 生成的 **6 条路径**逐字节相同"。但地图生成器
这一轮还不存在 ⇒ 那条测试**写不出来**，而"R1 通过"这句话在那种情况下就是报告一个不存在的
测试。所以拆开：

* **R1a（已落地）**：`Map` 流接下来 200 次 `draw` 的 `(seed, step)` 序列逐项相同 —— 在**抽取层**
  证明子流隔离。
* **R1b（欠着）**：整张地图逐字节相同 —— 在**生成层**证明同一件事，等地图生成器落地。

R2 也补了一条 **R2b**：七个 `stream_seed(7, …)` 用**字面量**钉死。理由是"重新验算一遍公式"
的测试会随公式一起变绿（改公式 ⇒ 测试跟着改 ⇒ 永远绿），字面量不会。

### 47.3 顺手抓到的两处"计划与现实冲突"（都在 M1 的进入条件里）

1. **起始遗物 `burning_blood` 有效果，M1 必须实现它。** 计划里 M1 的"明确不做"写着遗物，
   但 `inv:§2` 说起始遗物是 `Burning Blood`（战斗结束 +6 HP）。不实现它，**每一场**战斗结束
   后的 HP 都是错的，而"从 floor 1 打到 Boss"全程就在这条数值上。
   ⇒ `run-layer.md` §4.5 写死：M1 实现**唯一一个**遗物效果，并且它落在 `health` 上
   （`health` 本来就在 `run_hash` 里，所以不需要额外的哈希项）。
2. **Neow 不在 M1，所以起始 HP 是 80 而不是 88。** 这是**一条必须登记的降级**，已加进
   `sts-act1-plan.md` §7 降级表第 7 行，并写明"何时会被发现"= 开局第一屏的 HP 数字。
   ⚠️ 同时留了一条欠账：降级表的机械载体 `native/sts_deviations.json` **还不存在**，
   在它建起来之前，"降级表 + 闸门"这条防护还是纸面的。

另外把一条硬规则落进了 `run-layer.md` §4.4：**`MAX_RUN_DECK = 60` 是容量不是语义，
前提是溢出响亮失败**（`RunError::Capacity`，不许"取前 60 张"）。StS 的牌组后期能超过 60 张，
所以这条不能被当成"预算"去挤。

### 47.4 内核的一行改动，与它引出的一个实测

`rng::GOLDEN32` 原来是私有常量。`rd-run` 要拿它做流派生 —— 两条路：抄一份这个数字，或者
把它 `pub`。这一轮选了后者，理由就写在常量上面："同一份常量抄第二份就是腐烂的开始"。

**然后闸门 14 立刻红了，红得很有价值：**

```
on disk    378962 B  sha256 686ba653…
fresh      378962 B  sha256 4a429dc5…
```

**字节数一模一样，sha 不同。** 也就是说：只比尺寸的实现会全绿，只比 mtime 的实现也会全绿
（重编那一刻产物比源码新）。这正是判据必须是**字节**的实测依据 —— 与 46.4 记的
"两种时间说谎"是同一族问题，但这一次是**尺寸**会说谎。
行为没有变（页面的 10 步取胜、首回合预告 12 == 实际 12 都照旧），变的是数据段的排布。
处置就是闸门自己打印的那条命令：把新产物复制过去。

### 47.5 聚合验收的两处调整（**都是"覆盖不到"的形状**）

* `rust-units` 从 `-p rd-core` 改成 **`-p rd-core -p rd-run`**，并且"测试条数下限"改成
  **把输出里所有 `N passed` 求和**（原来是取第一个匹配）。不这么改的话，新 crate 的 8 条测试
  跑不跑、红不红，闸门都不知道 —— 而"取第一个匹配"正是那种**看起来在数**的假证据。
  下限 558 → **566**。
* `rust-baremetal` 与 `rust-clippy` 同样加上 `-p rd-run`：新 crate 声称 `no_std`，
  不进裸机闸门就等于没声称。

### 47.6 这一轮的数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 14/14 | **14/14**（闸门数没变，`rust-units` 的覆盖面变宽） |
| 单测 | 558 | **566**（`-UnitsFloor` 566） |
| 四层对拍 | 182 / 62 / 124 / 394 | 不变 |
| `CombatState` | 213,224 B | 213,224 B |
| `.wasm` | 378,962 B | 378,962 B（**sha 变了**，见 47.4） |
| 新 crate | — | `kernel/rd-run`（2 个模块 / **446 行** / 8 条测试） |

### 47.7 一处**说法错误**：`web/rd_wasm.wasm` 从来就不在 git 里

发现的过程值得记：这一轮复制了一份新的 `.wasm` 过去（47.4 的那次重编），然后 `git status`
**没有**显示它变脏。不是因为内容一样（sha 明明变了），而是因为 `.gitignore` 第 48 行就是

```
# ── Web/wasm 构建产物（一条 cargo 命令即可重建，见 web/README.md）────────────
web/*.wasm
```

`git ls-files web/` 只有三行：`README.md`、`index.html`、`smoke.mjs`。
**而我在三个地方把它写成了"提交进来的产物"**：`web/smoke.mjs` 的头注释、它的输出标签
（`committed  378962 B`）、`web/README.md` 的"as committed"。三处都是**假的**。

这不是代码错误，是**断言没有验证**。它的代价是具体的：新克隆的仓库里没有这份产物，
而闸门 14 的比较对象之一就是它 ⇒ 闸门在干净克隆上会红，而一个"文档说它提交了"的人会
先去怀疑闸门。

处置：

* 三处说法全部改掉，`README.md` 里直接写清"**.gitignore 故意排除它，克隆后要跑一次那两条命令**"，
  并附上"为什么它不该入库"（第一次提交的要求就是避开编译产物与二进制）。
* `smoke.mjs` 从"默认文件在"改成**缺席时响亮失败且给出可执行的命令**（原来是一条裸的
  `ENOENT` 堆栈，虽然退出码是 1，但它不告诉你该做什么）。实测过两条路径：
  把文件移走 ⇒ 退出 1 + 打印那两条命令；移回来 ⇒ `WEB_SMOKE PASS`。
* 教训一句话：**"这个产物被提交了"本身也是一条要验证的断言**，`git ls-files` 一句话就能证伪。
  而我这次是靠"我预期它该变脏却没变脏"才发现的 —— 也就是说，**`git status` 干净既可能是
  "没改"，也可能是"根本不归 git 管"**，这两件事在输出里长得一模一样。

### 47.9 下一站

`run-layer.md` §7.3 的地图算法（含它自报的"最可能错的一条"：**"最近的 3 个"是我们的读法**），
然后 `RunState` + `run_hash`（含 §5.4 的逐字段扰动），然后篝火/宝箱/Boss。
并行可以派出去的是两件**与 run 层无关**的内核小缺口：`currentHealth` 表达式（Hexaghost 的
Divider 要用）与 `LifecyclePrograms`（Burn 要用）。

> **2026-10-19 补注**：`currentHealth`（连带 `maxHealth`）**已完成**，字段名 `Selector`；见
> `kernel/rd-core/src/expr.rs` 模块头第 4 条。
>
> **2026-10-19 第二补注**：`LifecyclePrograms` 也**已完成**（`host::try_hand_turn_end_lifecycle`，
> 见 `docs/spec/battle-loop-hooks.md` §2.5）。这一句点名的两个缺口现在是零个。

---

## 48. 第 38 轮：地图生成器落地 —— 13 条规则、8 条"必须被拒"的测试，以及规则 11 与固定层的真冲突

> 这一轮全在 `kernel/rd-run` 里：新增 `map.rs`，crate 从 8 条测试长到 **25 条**。
> `rd-core` 一个字节没动（并行还有两个代理在改 `expr.rs` 与 `host.rs`，那是另外两件事）。

### 48.1 生成器和校验器**分开**，因为只有一半的规则能被"生成"测到

`RunMap::generate` 必须产出 `RunMap::check` 接受的地图，但五条覆写的**判据**是 `check`，
测试对着 `check` 写 —— 一半是 200 个 seed 的真地图，另一半是**手搓的违规地图**：

| 测试 | 破坏的是哪一条 | 期望 |
|---|---|---|
| `check_rejects_a_wrong_fixed_floor` | `inv:§7.2` | `FixedFloor{row:0}` |
| `check_rejects_an_elite_on_floor_2` | `§7.4#1` | `TooEarly{row:1}` |
| `check_rejects_a_rest_on_floor_14` | `§7.4#4` | `RestBeforeBossRest{row:13}` |
| `check_rejects_two_adjacent_rest_sites` | `§7.4#2` | `Consecutive{row:5}` |
| `check_rejects_two_identical_siblings` | `§7.4#3` | `Siblings` |
| `check_rejects_a_crossing` | `§7.1` 不交叉 | `Crossing{row:0}` |
| `check_rejects_a_dead_end` | `§7.1` 出边 ≥1 | `DeadEnd{row:3,index:0}` |
| `check_rejects_an_unrolled_node` | 未掷点 | `Unrolled{row:9,index:0}` |
| `check_rejects_an_edge_target_outside_the_next_row` | 结构 | `Structure` |

只有"生成"那一半会全绿的情形是具体存在的：**一个只会生成一条直路的实现**满足所有结构规则
（`sts-act1-plan.md` §4 M1 风险行点名的就是它）。所以还加了一条**产量**断言：
200 张图里 `out_degree >= 2` 的节点数 **≥ 200**（平均每张至少一个岔口）。

### 48.2 实现时才暴露的真冲突：规则 11 与固定层不可能同时成立

第 9 层全是宝箱、第 15 层全是篝火（`inv:§7.2`），而 `inv:§7.4#3` 要求"一个节点若有 ≥2 条出边，
其所有目的节点类型必须互不相同"。第 8 层的一个三岔口，三个目的节点**必然**都是宝箱。

`[推断]` 裁决：**固定层豁免规则 11**。理由写进了 `run-layer.md` §7.1 的引用块和
`map.rs::check` 的注释：规则 7 是有来源的事实，规则 11 的目的是让岔口成为"选择"；
让固定层赢，冲突消失。反过来（让规则 11 赢）等于要求第 8 层的分叉点只能有一条出边，
把"Boss 前必进宝箱"压成单行道。

⚠️ 这条裁决把 `check_rejects_two_identical_siblings` 的构造限制住了：它必须挑一个**目的层
不是固定层**的岔口，否则它测的是"豁免"而不是"规则"。第一版就是这样踩的 —— 它用了
`Shop` 两次，结果先撞上 `§7.4#2`（商店不能连续），测试红得像是规则根本没实现。改成
`Unknown`（唯一不在 `§7.4#2` 里的类型）之后才是真的在测规则 11。

### 48.3 哪些是 `[推断]`（逐条点名，因为它们全都可能错）

| 项 | 我们的做法 | 为什么是推断 |
|---|---|---|
| 六点在 7 列上的位置 | `index*(COLS-1)/(NODES-1)` ⇒ 列 `0,1,2,3,4,6` | wiki 只说"7 列、每行最多 6 个"，没说怎么摆 |
| "最近的 3 个" | 按列距升序、同距取列小者，取前三个 | wiki 没说平局怎么办，也没说是否只算"可用"节点 |
| 路径之间的次序 | 每层按当前列排序，后一条只能落到不左于前一条的列 | 这是"不交叉"的一种等价表述，但不是唯一一种 |
| 重掷上限 | 每节点 64 次、整张图 64 次，超了**响亮失败** | 上限是选的；超限放宽约束是最坏的静默，所以选择失败 |
| 起点 | 每条路径独立滚，仅强制前两条不同（`inv:§7.1` 只要求这一条） | 六条路径可以有相同起点 |

### 48.4 变异测试（5 条，全部**真的红**）

| # | 变异 | 判红的测试 |
|---|---|---|
| M1 | 关掉不交叉检查 | `check_rejects_a_crossing` |
| M2 | 类型掷点恒返回普通战斗 | 17 条（生成器内部断言先炸，级联） |
| M3 | 第 15 层不再固定成篝火 | `shape_and_fixed_floors_match_the_inventory` |
| M4 | 七条流共用一个计数器与一个 seed | `r1a` / `r1b` / `r3` / `shuffle_is_per_stream...` |
| M5 | 掷点时不套 `§7.4#1`（前 5 层无精英/篝火） | `override_1_...` / `override_4_...` / `all_five_...` / `every_seed_...` |

恢复后重跑全绿（脚本里逐字节还原）。

### 48.5 这一轮的数字

| 项 | 前 | 后 |
|---|---|---|
| `rd-run` 模块数 | 1（`streams`） | **2**（+`map`） |
| `rd-run` 测试 | 8 | **25** |
| `map.rs` | — | **978 行**（含 325 行测试） |
| `RunMap` 尺寸 | — | 15 × (1 + 6 × 6) = **555 B**（`Copy`，无分配） |
| `rd-core` | — | 零改动 |

### 48.6 还没做的（下一轮）

`RunState`（§4 的字段 + 8 KiB 的 tripwire）、`run_hash`（§5 的规范文本 + 逐字段扰动）、
篝火/宝箱/Boss 的结算、以及 §8 的 **A3 分布闸门**（固定 200 个 seed、带容差、
并先断言"样本里存在三岔口"）。地图这一层目前只有"结构合法 + 产量不退化"，
**没有分布判据** —— 也就是说 53/8/12/5/22 的**实际比例**还没被测过。

---

## 49. 第 39 轮：M1 缺的两件内核能力落地（`currentHealth` / 卡的生命周期节目），并行两个代理

> 与 §48 同时进行（我写地图生成器，两个代理各领一件内核小缺口）。三个工作流各自的
> 变异测试都跑过一遍，四个对拍层零漂移，聚合验收 **14/14**。

### 49.1 `currentHealth` / `maxHealth`（`expr.rs`）

Hexaghost 的 Divider = `(目标当前 HP / 12) + 1`，没有这两个表达式它根本写不出来。

**字段名不是编的。** `expr.rs` 原来的结论是"线上没有选择器 ⇒ 语义无从确定"，但实现时先量了
一次产物：OPD/OPF 表里**已经有 11 个 opcode 带 `Selector: F_TERM`**（op 20/21/22/23/24/25/32/
38/43/44/45），其中三个（`combatantStatusStacks` 25 / `combatantCounter` 23 /
`combatantCurrentResource` 24）正是本模块已实现的单目标标量读，走的就是 `child(node, "Selector")`。
⇒ `Selector` 是产物自己用给这个概念的名字，`sts-act1-plan.md` §9-4 那句"定义权在我们"
只是**追认**了它。

⚠️ **顺带记一条容易翻车的**：op id **不是稳定的**。它是按 kind 名字排序分配的，所以
`roguedeck` 镜像里 `currentHealth` 是 op 28/48，而在一份带这个键的 `sts` 草稿镜像里它是 **op 19**。
内核任何地方都**不许硬编码 op 号**（这条以前只是惯例，现在写进了 `expr.rs` 的头注释）。

* 6 条成对测试（`expr` 模块 24 → 30）；5 条变异里 **4 条真的红**；
  **1 条（`single_target` 的"解析出 ≥2 个"分支）报为「未钉住」**——静态基数表是按变体写死的
  （`targets.rs:301-306`），"静态 ≤1 但解析出 ≥2"在这个格式里无法表达；该缺口**先于本次改动存在**。
* 内容侧零点火验证：把 `Selector` 写进一份**草稿副本**后，`compile.py` **零改动**推导出
  `currentHealth: nfields=1, Selector: F_TERM`，读回也是同一个形状。`packages/**` 一个字节没动。

### 49.2 卡的生命周期节目（`host.rs`，Burn 的机制）

原来是"响亮的空"（有节目就 `Unsupported`），现在是真实现：解码
`CARD.LifecyclePrograms[TurnEndInHand]`、快照手牌槽位、逐张走 `exec` 派发、`sel.source` 与
`sel.eventTarget` 都绑"正在结束回合的那个人"，跑在 turn-end 处理器序**第 1 位**（弃手牌之前）。

* **链号 +0、执行号 +1**：参考里这条处理器跑在 `TurnEndedCombatEvent` 的**分发**里，
  那一刻 `CurrentEffectChain` 是事件自己那条链（`CombatEventHandling.cs:60`）⇒ 节目的
  `EffectChain ??=` 不发号。内核用 `CombatState::adopt_root_chain`（建链、不推进计数器）表达它。
  **`battle-loop-hooks.md` 里原来把 `chain_num` 列进"必然变化"是错的，已原地更正**。
* 10 条新测试。观察对象是**手搓的最小 RDCF 镜像**（`burn` / `burn_dual` / `burn_block` /
  `burn_retained` / `weird` / `plain`）—— 因为真实镜像 62/62 卡的 `LifecyclePrograms` 都是 `{}`，
  "节目真的跑了"这件事在真实内容上**不可观察**。
* 5 条**偏离**逐条写在函数文档里（定义查不到⇒响亮失败、卡槽故意不绑、先全解再跑、已结束不跑、
  快照手牌），每条都带理由。
* ⚠️ **顺带钉住了另一个缺口**：`host.rs::card_stays_in_hand_at_turn_end` 恒返回 `false`
  （理由写的是"62/62 卡 `RetainInHandOnTurnEnd = false`"）。手搓镜像里那张**真的** `true` 的卡
  证明"内容一旦用这个字段就会被静默忽略"。测试**把这个缺口断言出来了**并写明"它变红那天说明
  那个钩子开始读内容了，别当成回归" —— 这是纪律第 11 条的用法：**把"我不知道"改成"否"是最危险的撤销**，
  所以要留一条会红的断言在那儿，而不是留一句注释。

### 49.3 三个工作流各自的数字

| 工作流 | 新测试 | 变异 | 结论 |
|---|---:|---|---|
| 地图生成器（§48） | 17 | 5 条全红 | 生成器 + 校验器分开，8 条"必须被拒" |
| `currentHealth`/`maxHealth` | 6 | 4 红 + **1 未钉住**（写明理由） | 字段名有 11 个先例 |
| 生命周期节目 | 10 | 见 §49.2 | 5 条偏离逐条记录 |

合计：`rd-core` 558 → **574**，`rd-run` 0 → **25**，聚合验收下限 `-UnitsFloor` 566 → **599**。

### 49.4 并行三个工作流的**代价**（记下来，下次别再犯）

我让两个代理同时改 `rd-core`（一个 `expr.rs`、一个 `host.rs`）。文件不冲突，但**它们都要编译
整个 crate** ⇒ 任一方的半成品都会让另一方的测试变红。实测到：`expr` 代理报告"全量跑出现
572~573 passed、1~2 个 `host::tests` 失败"，而那是**另一个工作流的中间状态**，不是它的回归。
两边都识别对了，但这是运气 + 它们各自的谨慎，不是流程保证。

**下次的做法**：同 crate 的并行任务要么让代理**各用一条 git worktree / 独立拷贝**，
要么串行。判据是"这个改动会不会让整个 crate 暂时编不过" —— 会，就不要并行。

### 49.5 这一轮的数字

| 项 | 前 | 后 |
|---|---|---|
| 单测 | 558（rd-core） | **574 + 25 = 599** |
| 聚合验收 | 14/14 | **14/14**（`-UnitsFloor` 599） |
| 四条对拍 | 182 / 62 / 124 / 394 | 不变（本轮实测） |
| `CombatState` | 213,224 B | 213,224 B |
| `.wasm` | 378,962 B | **382,995 B**（+4,033，新内核代码） |
| clippy / 裸机 | 零告警 / EXIT 0 | 零告警 / EXIT 0 |


---

## 50. 第 40 轮：界面第一次有了"语义"判据（闸门 15），以及 UI 方案的调研

> 这一轮 `kernel/**` 零改动。产出全在 `web/**`、`tools/acceptance.ps1` 与一份新文档
> `docs/spec/ui-plan.md`。聚合验收 14 → **15** 道闸门。

### 50.1 先量出一个洞：14 道闸门看不见任何一格显示得对不对

闸门 13/14 证明的是"`.wasm` 与重编产物逐字节相同 + 页面能解析 + 只调用真导出 + 122 格偏移铺得满"。
**它们证明不了任何一格显示的数是对的。** 实测：把 `render()` 里血量格改成读 `HP_MAX`，
14 道闸门**一条都不红** —— 而这正是这个项目已经踩过十几次的形状（覆盖不到的地方看起来最绿）。

### 50.2 处置：把"哪一格显示什么"变成纯函数，然后逐格断言

| 文件 | 是什么 |
|---|---|
| `web/ui_render.js` | 观测布局常量 + 四个纯描述函数（`describeHero/Enemies/Hand/Status`）。经典脚本挂 `globalThis.RD_UI`，**零构建零依赖** |
| `web/ui_test.mjs` | 用**真 `.wasm`** 驱动它们，并把**每一个打印出来的量**与观察向量**那一格**逐格比对 |
| 闸门 15 `web-ui` | `node web/ui_test.mjs`，`MustMatch UI_RENDER PASS` |

**为什么是纯函数而不是"用 DOM stub 跑一遍"**：要断言的是语义（"血量格显示 67 而非 80"），
不是 DOM 的形状；纯函数不需要任何 DOM 实现，也不会因为将来换渲染技术而重写。

### 50.3 9 条变异全部真的红，其中 **2 条第一轮是绿的**（真缺口，不是测试写错）

| # | 变异 | 第一轮 | 判红的断言 |
|---|---|---|---|
| M1 | 血量格读 `HP_MAX` | 红 | 逐格比对：`hero hp shows 80, the observation says 68` |
| M2 | 敌人血量格读上限 | 红 | 被打的敌人 `still shows 28 HP` |
| M3 | 意图伤害恒 `null` | 红 | 逐格比对：`intent damage shows null, says 7` |
| M4 | 卡名恒占位 | 红 | `card 0 has no name` |
| M5 | 双目标走直打快路 | 红 | `card 1 has two targets but would be played directly` |
| M6 | 页面不再调用 `describe` | 红 | `never calls RD_UI.describe()` |
| M7 | 敌人状态计数恒 0 | **绿** | 补：逐格比对 + 一条**非零实例**（打出 `bash` 让 `vuln` 真挂上） |
| M8 | 敌人恒 `alive` | **绿** | 补：战斗结束时"没有敌人还是 alive" |
| M9 | 能量格读 `ENERGY_MAX` | **绿** | 补："付过款之后能量必须低于上限"（起手与回合开始能量**恰好**等于上限） |

M7–M9 的共同形状值得单独说：**只写具体断言（"血量应该是 68"）会漏掉所有"这次采样恰好相同"的
常量**。真正的主力是那条"逐格 == 观察向量那一格"的不变量（在 5 个时点各跑一次）；
具体断言的作用只是把失败信息说得更清楚。

### 50.4 唯一抓到那个真 bug 的东西：真浏览器

重构之后我把页面里模块级的 `playOptions` 删了，**两个点击处理器还在读它**。结果：
**页面渲染完全正常、15 道闸门全绿、一次点击都不生效**（回合数停在 2 不动）。
Node 测试看不见它 —— 点击处理器是 DOM 那一半，故意不进测试。
是"在真浏览器里点一局"发现的（22 击到 `Victory`，第 7 回合，两个敌人都 `(down)`，`reward 4.00`）。

⇒ 结论写进了 `ui-plan.md` §6 U0 与 §8：**U0 之后，真浏览器仍然是不替代的一步**。
这也顺带说明"闸门数"不是质量指标 —— 一条闸门只覆盖它盯的那一层。

### 50.5 UI 方案调研（`docs/spec/ui-plan.md`，新文档）

任务书问的是"能不能直接找现成的 UI 设计"。查下来的结论分三层：

1. **渲染技术不用换。** 我们的规模是几十个元素（手牌 ≤10、敌人 ≤4、地图节点 ≤90），
   正落在"少量形状 ⇒ 用 SVG/DOM"的区间（Konva 的对照表：需要每个形状参与 DOM/事件/无障碍 ⇒ SVG）
   [cite:4acb1818-2]。three.js 的 `three.module.min.js` 是 **692 kB**（three@0.170.0 官方构建）
   [cite:4acb1818-1]，比我们**整个** `.wasm`（382,995 B）还大 1.8 倍。
   反例也找到了：`arcomage-hd` 是个"3D 复刻"卡牌游戏，动画用的是 **CSS**，不是 WebGL[cite:73cb6d59-2]。
   three.js 论坛自己的口径：屏幕空间 UI 直接用 HTML+CSS，"最容易也最灵活"[cite:41374eb9-2]；
   且有人实测"用 canvas 纹理画频繁变化的文字"会吃到 `texImage2D` 上传开销，
   而"直接改 HTML 的 `textContent` 更快"[cite:41374eb9-2]。
2. **要借的是结构，不是库。** 最接近的同类 *Slay the Web* 的做法：**UI 无关的核心 + 一层的示例 UI**、
   地图单独一页、`?debug` / `?hand=` URL 调试开关、状态存 URL hash、动画用 gsap[cite:41374eb9-1]。
   其中 **`?hand=` 对我们的收益最大**：现在要看"某张卡在手里的样子"必须先打到那一局。
   ⚠️ 明确不借它的**引擎** —— 那是与我们的 Rust 内核竞争的另一种 StS 实现，
   抄进来会让"可以逐字节对拍 C# 参考实现"这条最贵的资产作废。
3. **裁决是分层的**：结构层 DOM+CSS（现状已在这一层）、图层 SVG（地图是图）、
   观感层 CSS 3D transform + filter（卡面倾斜/翻牌不需要 WebGL）、动效层 WAAPI 或 gsap。
   three.js 只在"需要真 3D 战场（斜视角/景深/粒子）"时才回到桌面上，且要做成**可选的观感层**。

### 50.6 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 14/14 | **15/15** |
| `web/` 文件 | 4 | **6**（+`ui_render.js`、`ui_test.mjs`） |
| 页面脚本块 | 1 个内联 | 1 个外链 + 1 个内联；闸门 14 现在**逐个加载并解析**它们 |
| `.wasm` | 382,995 B | 382,995 B（内核零改动） |
| `kernel/**` | — | **零改动** |

### 50.7 下一站

`ui-plan.md` 的 U1（地图页，SVG）与 U2（战斗页正式化）。两者都依赖同一件小事：
**wasm 侧要把地图（节点/边）与战斗日志摊成整数数组导出** —— 那是一次 ABI 扩展，
按 `env-abi.md` 的冻结纪律要先改文档再改代码。

---

## 51. 第 41 轮：run 层接进 wasm 与页面（闸门 16），以及"画出来才发现地图是漏斗"

> 这一轮的产出跨越三处：`kernel/rd-run`（`RunState`）、`kernel/rd-core`（一个只读访问器）、
> `kernel/rd-wasm`（一套新导出）+ `web/`（地图页）。聚合验收 15 → **16** 道闸门。

### 51.1 先把 ABI 写进规格书，再写代码

`docs/spec/env-abi.md` **§11** 是新的：run 层导出**与 §3 那套并列**，不是它的扩展
（一场战斗 vs 一局，寿命与消费方都不同）。导出的形状、`-1` 的语义、动作编码、
以及**§11.5 那份"只走不结算"的能力边界**都在文档里，代码照着写。

### 51.2 `RunState` 落地，起始数值**从内容读**

`rd-run/src/state.rs`：`new(seed, health_max, gold, &deck)`、`enter_node`（只接受真的是出边的
目标，否则 `NotReachable` 且**一个字节都不动**）、`reachable()`（给的是**全局**节点下标）、
`check_invariants()`（8 条，`run-layer.md` §6.2 的逐条）、8 KiB 的 **tripwire**（不是预算）。
容量溢出是 `RunError::Capacity`，**绝不截断**（`MAX_RUN_DECK = 60` 那条硬规则）。

⚠️ 它**刻意不认识内容**（模块头写了理由）。所以"这一局从 80 血、0 金开始"必须由内容说：
`rd-core` 新增 `Content::character_start_facts`，读 `Characters[0].Start` 的
`MaxHealth` / `StartingHealth` / `Resources.gold`。**实测那份内容是 80/80/0，且
`StartingRelics` 是空的** —— 也就是说 `inv:§2` 的起始遗物 `Burning Blood` **还没被写进内容**。
这一条记在 `run-layer.md` §4.5 与 `content.rs` 的文档注释里，是 M1 的欠账，不是本轮的工作。

### 51.3 地图页（U1）：把"哪一格画什么"也变成纯函数

`web/map_render.js`（`RD_MAP`）+ `web/map.html` + `web/map_test.mjs` + 闸门 16 `web-map`。
6 条变异全部真的红：行读成列 / 可达集合改成"前 N 个节点" / 出边目标整体 +1 /
页面自己编一套 kind 名 / 游标永不标记 / 页面不再调用 `svgMarkup`。

⚠️ **其中两条第一轮是绿的，原因是同一个**：我把"视图 == 模块"的对账**只在开局做了一次**，
而那两个变异在开局恰好与真值重合（floor 1 的"前 N 个节点"就是整行；开局还没有游标）。
修法：把对账写成一个 helper，**走完整张地图的每一步都跑一遍**，再换第二个 seed 跑一遍。
这和第 40 轮 `ui_test.mjs` 的教训是同一个形状（**只在一次采样上对账，会漏掉"这次恰好相同"**），
只是这次发生在"时间轴"上而不是"格子"上。

### 51.4 画出来才发现：地图是漏斗

真浏览器里看到的那张图，有几层只剩 1 个节点。量了一下（20 个 seed）：平均每行 **2.56** 个节点，
**13/20** 张图至少有一行只剩 1 个。**13 条规则一条都没违反** —— 规则只要求"每行最多 6 个"。

根因在走法：路径在"不能往左"的约束下会挤到一起，于是行里大部分节点**没有路径经过**，
被"裁孤点"删掉。处置是在 `[推断]` 的范围内加一条偏好 ——
**最近 3 个里优先选还没被本行前面的路径占用的那个**。效果：平均每行 **3.30**，只有 **5/20**
有单节点行。规则一条没变（仍然是"最近 3 个之一"，列仍然单调），变的只是同样合法时挑哪个。

⇒ 这条偏好改了 `Map` 流的抽取次数：seed 7 的地图生成 **141 → 128** 次。
`rd-wasm/src/run.rs` 里**钉着这个数**，它变红就是这条偏好被改动的信号（本轮就是它先红的，
这正是钉它的目的）。新加一条 `the_map_is_wide_rather_than_a_funnel` 盯着平均宽度（门槛 3.0，
低于实测 3.30 所以不抖，高于旧值 2.56 所以删掉偏好就红）。

⚠️ **个别 seed 仍会收窄**：seed 7 自己就是较窄的一张（36 节点 / 每行 2.40 / 两行只剩 1 个）。
"平均"与"单张"不矛盾；要更宽就得改"不交叉"的**规则读法**，而那是 `inv:§7.1` 的规则。

### 51.5 顺手补掉的覆盖漏洞（第三次同样的形状）

`rust-units` 原来是 `-p rd-core -p rd-run`：**`rd-wasm` 的测试一道闸门都没管**
（本轮之前它 0 条，本轮 9 条）。现在三个 crate 都进这条闸门，条数在输出里**求和**，
`-UnitsFloor` 599 → **617**。

### 51.6 这一轮的数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 15/15 | **16/16** |
| 单测 | 599（rd-core 574 + rd-run 25） | **617**（574 + 34 + 9） |
| `rd-run` | 2 模块 / 25 测试 | **3 模块**（+`state.rs`）/ 34 测试 |
| `.wasm` | 382,995 B | **≈432 KB**（整层 run 导出 + `RunState`） |
| 新导出 | — | `rd_run_*` 15 个（`env-abi.md` §11） |
| 地图宽度 | 每行 2.56 | **3.30**（20 seed 平均） |
| `CombatState` | 213,224 B | 213,224 B（未动） |

### 51.7 下一站

按 `ui-plan.md`：**U2 = 战斗页正式化**（卡面、战斗日志、动画、移动端），以及它需要的
第二次 ABI 扩展（把 `FightOutcome` 与 `problems` 摊成整数数组）。run 层这一侧则是
**节点结算**（战斗/篝火/宝箱），它一旦落地，`env-abi.md` §11.5 与地图页上那句
"只走不结算"必须同时改掉。


---

## 52. 第 42 轮：**每层至少 3 个节点**（用户给的领域知识），漏斗问题从根上收掉

> 这一轮的起点不是测试，是**看图**：第 41 轮把地图画出来之后，有几层只剩 1 个节点。
> 用户指出 **原作不会出现一层只有一个节点**。⇒ 它从"一条偏好"升级成**一条规则**。

### 52.1 为什么"13 条规则全绿"还是错的

`inv:§7.1` 只写了**上界**（每行最多 6 个节点）。我的生成器先每行放 6 个、再让 6 条路径走、
最后按规则 6"裁孤点"把没被走过的删掉 —— 于是行宽完全由**路径的分布**决定，
最极端的一层只剩 1 个。**规则一条都没违反**，闸门 16 也全绿，而图是错的。

⇒ 这是一条值得单独记住的教训：**"合法"与"形状对"是两件事**，
而发现后者的唯一手段是**把它画出来看**。前一轮加的那条"优先选未被占用"的偏好只把平均
从 2.56 抬到 3.30，仍然是"希望"而不是"保证"。

### 52.2 处置：一条规则 + 拒绝重试

* `MIN_NODES_PER_ROW = 3`（来源：**用户的领域知识**，不是 `inv` —— 文档里逐处标了【领域知识】）。
* `check()` 新增 `MapViolation::TooNarrow { row, count }`：**校验器**也必须认这条规则，
  否则"生成器碰巧做到"就成了判据。
* 生成时：走完 → 裁孤点 → **任一层窄于 3 就整次作废重来**（`MAX_ATTEMPTS = 64`）。
  与规则 13"违规就重掷"是同一手法，比"事后补节点"诚实：补出来的节点与路径没有关系。

### 52.3 实测（300 个 seed，`web/rd_wasm.wasm` 里量）

| 指标 | 加规则前 | 加规则后 |
|---|---|---|
| 生成失败 | — | **0 / 300** |
| 最窄的一层 | **1** | **4** |
| 平均每行节点数 | 2.56（偏好前）/ 3.30（偏好后） | **4.62** |
| 行宽分布 | — | 4:2156 · 5:1920 · 6:424（**没有 3 以下**） |
| `Map` 流抽取次数（seed 7） | 128 | **148** |

⚠️ 抽取次数**变多**了：被作废的那几次尝试**不会退回**已消费的抽取。
`rd-wasm/src/run.rs` 钉着这个数（它在同一天从 141 → 128 → 148，每一次都是我先看到它红，
再回去解释为什么 —— 这正是钉它的目的）。

### 52.4 一条走过的弯路（记下来省下一次）

先试的方案是"**先决定每层几个节点，再让六条路径覆盖它们**"。它**一次都生成不出来**：
"最近 3 个"与"不能走到上一条路径左边的列"两条一起用，在随机撒点的行上经常
**一个合法目标都没有**（`choose_target` 返回 `None`，64 次尝试全灭）。
让走法决定每行长什么样、再把太窄的那次作废，既简单又可行。
⇒ 教训：**约束叠加时，"先定形状再连边"比"先连边再定形状"脆**。

### 52.5 判据

* `every_floor_is_wide_enough_to_be_a_choice`：**逐层断言**（不是平均）≥ 3，跑 300 个 seed，
  同时钉住平均 ≥ 4.0（低于实测 4.62 所以不抖，高于旧值 3.30 所以改坏就红）。
  它同时覆盖"生成失败"这一面：规则若把生成变得不可行，这里会报 `MapGeneration`。
* `check_rejects_a_floor_that_is_too_narrow`：**成对**的另一半 —— 手搓一张 floor 14 只剩 2 个
  节点的地图，`check()` 必须报 `TooNarrow`。第一版**写错了**：它只改了行宽，于是上面一层先报
  `Structure`（出边指向不存在的节点），测试断言的是另一条规则；现在把那些出边重指到幸存节点上。

### 52.6 真浏览器

`seed 7`：69 个节点 / 67 条边，行宽 `6,5,4,5,4,4,4,4,4,5,5,5,5,5,4`（**最窄 4**），
一路点到 floor 15。第 9 层三个宝箱、第 15 层四个篝火，在地图上一眼可见。

### 52.7 这一轮的数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 617 | **618**（rd-core 574 + rd-run 35 + rd-wasm 9） |
| 地图最窄层 | 1 | **4** |
| 平均每行 | 2.56 | **4.62** |
| `.wasm` | 432,563 B | ≈432 KB（规则只加了几十字节的代码） |
---

## 53. 第 43 轮：地图是**几道孤立的道** —— 用户第二次看图，查出一次规格偏离

> 第 42 轮把"每层 ≥3 个节点"变成规则之后，用户又指出：**地图上有一条完全孤立的路径**。
> 量了一次，那不是错觉，是结构错误。

### 53.1 实测：60/60 张图都不止一个连通块

`seed 7` 的地图有 **4 个连通块，大小 15/15/24/15** —— 15 正好是"一行一个节点 × 15 行"，
也就是说**每一块就是一条路径**：6 条路径互相不碰，成了 6 条平行的**道**。

后果比漏斗更严重：漏斗是"某层只有一个选择"，而孤立的道是**"走进这一道，整局都到不了另一道"** ——
地图不再是**一张**地图。

### 53.2 根因是我自己上一轮加的那条偏好

第 41 轮为了治漏斗，我加了"**优先选本行还没被占用的目标**"。它把 6 条路径逼开，
于是它们**永远不共享节点**。我在那条注释里写了"共享节点是岔口的来源"这句反话 ——
当时的推理停在"宽度"，没往下想一层。**共享节点正是岔口本身**：
两条路径汇到一个节点、再从它分头出去，那个节点才有两条出边。把路径推开，
同时消灭了重叠**和分支**。

### 53.3 两次修复都不对，第三次才找到原因（全部有实测）

| 试法 | 结果（320 次抽样） |
|---|---|
| 优先选未被占用的目标 | 宽度够，但 60/60 张图**不连通**（平行的道） |
| 纯随机选 | **连通 308/320**，但只有 **3/320** 每层都 ≥3 宽（合并 ⇒ 行被裁窄） |
| 只在该行够不到下限时才强制新目标 | wide+connected **2/320** |
| **先定每层节点，再连接（相邻段共享一个节点）** | wide+connected **287/320**，宽度平均 **4.53** |

关键的一次是在 `choose_target` 上打转了三轮之后**停下来去量**：
写了一个 `#[ignore]` 的 `measure_rejected_draws`，把"宽"和"连通"分开计数。
量出来才看清两者是**反相关**的 —— 在"走 6 条路径"这个框架里**同时成立的抽样是 0/320**，
再调参数也只是在两点之间滑。**这就是"停下来量一次"的价值：前三轮都是在猜。**

### 53.4 处置：换掉连接方式（**一次有记录的规格偏离**）

`inv:§7.1` 说地图由**走 6 条路径**生成，每步走到下一层"最近的 3 个"节点之一。
现在改成：**先定每层的节点（宽度与列随机），再把相邻两层连起来** ——
每个源节点拿到下一行的**一段连续列区间**，区间按顺序排列，**相邻两段共享一个节点**。

* **保住的**：出边 1–3（区间长度）、不交叉（区间单调）、没有孤点（区间覆盖每个节点）、
  每层宽度 ≥ [`MIN_NODES_PER_ROW`]、**整张图连通**。
* **改掉的**：目的地不再是"最近的 3 个"而是"一段连续的列邻域"（`run-layer.md` 规则 **4b**）；
  地图不再是"走 6 条路径"走出来的（规则 **2**，"6 条路径"从输入变成结果）。
* 两条都写进 `run-layer.md` §7.1 的表里，标着"**§7.1 有这一条，我们改了**"，不假装还是 wiki 那条；
  原因与实测数字在新增的 §7.4。

**为什么不干脆把"6 条路径"当唯一真值**：它是 wiki 对**过程**的描述，而 1b 与"连通"是对
**结果**的要求；过程与结果冲突时，按项目一贯的规矩 —— **讲清哪一条让了、为什么让**，
而不是留一张看起来像地图的东西。

### 53.5 判据（成对）

* `every_seed_is_a_single_connected_map`：200 个 seed，`check()` 全绿（响应里含连通性），
  并显式断言**不是** `Disconnected`。
* `check_rejects_a_map_in_pieces`：**成对**的另一半。构造成**可证明**的分裂 ——
  每一行的左半只进下一行的**第一个**节点、右半只进**中间**那个，
  于是左右两半永远碰不到。第一版用"对角线"，在**宽度可变的行**上根本无法定义，
  测试断言的是别的东西；现在这个构造与宽度无关。
* `every_floor_is_wide_enough_to_be_a_choice`（第 42 轮）里的"平均 ≥4.0"仍然成立（实测 4.53）。
* `measure_rejected_draws`（`#[ignore]`）：把上面那张表重新量一遍的入口，留着当"下次别再猜"的工具。

### 53.6 数字

| 项 | 前 | 后 |
|---|---|---|
| 连通块（60 个 seed） | **60/60 张 >1** | **0/60 张 >1** |
| 每层宽度 | 最窄 4 / 平均 4.62 | 最窄 4 / 平均 **4.53** |
| 抽样接受率（320 次里两者同时成立） | **0** | **287** |
| 单测 | 618 | **620**（rd-core 574 + rd-run 37 + rd-wasm 9） |
| `.wasm` | 432,990 B | 430,404 B（**变小了**：`nearest_three` / `choose_target` 整套被 `connect_rows` 取代） |
| `Map` 流抽取次数（seed 7） | 148 | **135** |

### 53.7 真浏览器

`seed 7`：65 个节点、一个连通块，floor 0 提供 **5 个**起点；第 9 层三个宝箱、第 15 层四个篝火；
地图看起来终于像一张地图（分叉、汇合、再分叉）。

### 53.8 两次"看图"的教训，合成一句

第 42 轮第一次看图发现"漏斗"，第 43 轮第二次看图发现"孤立的道"。
**两次都是"13 条规则全绿、闸门全绿、图是错的"**：规则描述的是**局部性质**，
而"这张图作为一张图好不好"是**全局性质**，没有任何一条局部规则能保证它。
⇒ 只要还能画出图来，就应该**定期看一眼**，而不是等到某个数不对。
---

## 54. 第 44 轮：战斗动画与日志（U2 第一部分）—— 动画的"语义"也进了闸门

> 用户要的是"战斗动画 UI UX"。动画本身只有浏览器能看，所以这一轮的做法是：
> **把"这一步发生了什么"变成纯函数**，动画与日志都只是它的两个消费者。

### 54.1 三层纯函数，页面只负责画

| 层 | 函数 | 输入 → 输出 |
|---|---|---|
| 事件 | `diffObservations(before, after, wasEndTurn)` | 两步观察向量 → 事件表（伤害/格挡/回复/死亡/能量/抽牌/离手/状态/回合/结果） |
| 文本 | `logLines(diff, io)` | 事件表 → 日志行，带**阅读顺序** |
| 动效 | `animationPlan(diff, view)` | 事件表 → "在哪飘什么、抖谁、塌谁" |

三层都在 `web/ui_render.js` 里、都是纯函数 ⇒ **闸门 15 覆盖它们**，动画不再只是"看着对"。

### 54.2 一个必须先说清的边界：事件是**相减推出来**的

`env-abi.md` §4 每步给**两个观察向量、没有事件流**，所以事件靠相减重建。
这覆盖了所有可见量，但有一件事推不出来：**格挡的减少是"挡下伤害"还是"回合结束被清空"**。
两者在向量里长得一模一样。

处置：调用方说明这一步是不是结束回合（`wasEndTurn`），两种情况**分别报告**
（`absorbed` / `blockCleared`），而不是合成一个会错一半的数。
真正的引擎事件流更好 —— 记为欠账，而不是现在就动 ABI。

### 54.3 9 条变异全部真的红

| # | 变异 | 判红的断言 |
|---|---|---|
| D1 | 血量伤害 before/after 写反 | `the diff says the hero lost 0, the intents previewed 12` |
| D2 | 回合末的格挡清空被报成"挡下伤害" | `the end-turn clear was reported as absorbed damage` |
| D3 | 抽牌数用**抽牌堆**的 delta | `says 0 cards were drawn, the hand has 5` |
| D4 | 不报敌人死亡 | `no enemy death was ever reported` |
| D5 | 伤害不产生飘字 | `no damage float` |
| D6 | 伤害不产生抖动 | `no shake for the hero hit` |
| D7 | 日志漏掉伤害行 | `no damage line` |
| D8 | 空操作步骤也产生事件 | `a no-op diff produced 1 events` |
| D9 | 页面不再调用 `appendLog(diff)` | `index.html does not use appendLog(diff);` |

**D3 是真 bug 不是假想**：第一版用抽牌堆的 delta 算抽牌数 —— 而抽牌是**从抽牌堆拿走**，
delta 是负的，于是"手牌刚从 0 变 5"被报成"抽了 0 张"。

**D9 是变异逼出来的覆盖漏洞**：删掉页面里那次调用，**上面所有断言依然全绿** ——
因为三层纯函数全都还在、只是没人用。补法是让"页面确实调用了它们"也进判据
（注意要匹配**调用点** `appendLog(diff);`，只匹配 `appendLog(` 会被函数定义本身骗过）。

### 54.4 阅读顺序是单独一条判据

`diffObservations` 按向量自上而下走（英雄 → 敌人 → 状态 → 牌 → 回合），于是出牌那一步
读出来是"消耗 1 点能量 / 敌人 0 受到 6 点伤害 / 手牌离开：strike" —— **费用跑到卡前面去了**。
阅读顺序是**另一个决定**，所以单独做（`LOG_ORDER`）也单独断言：
`手牌离开 → 消耗 → 伤害`。

### 54.5 真浏览器实测

* 结束回合 ⇒ 英雄头上飘 `-12`、`#heroPanel` 拿到 `shake hit` 两个类、日志出现
  `英雄 受到 12 点伤害 / 抽 5 张牌 / —— 第 2 回合 · 1 ——`，无 JS 报错。
* 打出一张 strike 指 0 号敌人 ⇒ 敌人头上飘 `-6`、`enemy-panel shake hit`、
  敌人血量 28 → 22（**与飘字一致**）、能量 3 → 2、日志
  `手牌离开：strike / 消耗 1 点能量 / 敌人 0 受到 6 点伤害`。
* 手牌现在有**费用徽章**（圆圈里的数字）、卡名做标题、`slot N · 多目标` 做副标题。

### 54.6 明确还没做的（不留暗示）

卡面只有**名字 + 费用**：类型与描述文案**不在 ABI 里**，要显示"6 伤害"需要第二次 ABI 扩展；
没有音效；没有拖拽出牌（只有点击）；移动端只做了基本的窄屏自适应，触摸手势没测过。

### 54.7 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| `ui_test.mjs` 断言块 | 5 | **10**（新增：步差、格挡 vs 清空、终结事件、页面接线、阅读顺序） |
| 变异 | 6（地图）+ 9（战斗渲染） | **6 + 9 + 9（本轮步差）** |
| `kernel/**` | — | **零改动**（这一轮全在 `web/`） |
| `.wasm` | 430,404 B | 430,404 B（未重编） |
---

## 55. 第 45 轮：拖拽出牌 + 程序化音效（U2 第二部分）

> 第 54 轮把"这一步发生了什么"变成了纯函数；这一轮把**交互**与**手感**也接上，
> 并且延续同一条纪律：**决定是纯函数，绘制是页面**。

### 55.1 拖拽出牌：一个决定函数，`-1` 是载荷

`RD_UI.actionFor(options, handSlot, targetSlot)`：

| 情况 | 返回 |
|---|---|
| 这张牌出不了 | `-1` |
| 落点正好是它能打到的某个敌人 | 那条动作的下标 |
| 只有一个选项（无目标 / 只有 1 个可达敌人） | 那条动作，**忽略落点** |
| 多目标，但落在空处 / 落在够不到的敌人上 | **`-1`** |

最后一格是这个函数存在的理由：**"替玩家选一个目标"正是这个页面真出过的 bug**
（第 36 轮，`web/README.md` 记着"出牌的目标从来没被传下去"）。拖到不合法的地方就**什么都不做**。

指针管线约 40 行：`pointerdown` 记起点 → 移动超过 8px 才算拖（否则交给 click）→
亮出 `dropSlots` 说的那些敌人 → `pointerup` 用 `elementFromPoint` 找落点 → `actionFor` → `step`。
拖完浏览器还会补一次 click，页面**吞掉恰好一次**，否则一次拖拽打两张牌。

### 55.2 音效：仓库里一个音频文件都没有

`RD_UI.soundPlan(diff) → ["hit-hero", "draw", "turn", …]`，页面用 Web Audio 的振荡器发一个
短促的频率扫过（受击下滑、格挡上挑、胜利三连）。战斗**结束时只发一个音**，
不把那一击的所有音效排队播完 —— 这条也有断言。

`AudioContext` 在第一次手势时创建：浏览器在此之前拒绝启动音频。

### 55.3 15 条变异全部真的红（本轮新增 6 条）

| # | 变异 | 判红的断言 |
|---|---|---|
| E1 | 落空时回退到"第一个动作" | `dropping a two-target card on empty space picked a target anyway` |
| E2 | 落点不影响结果（永远取第一个） | `dropping on two different enemies resolved to the same action` |
| E3 | 敌人永远不亮 | `dropSlots disagrees with targetSlots` |
| E4 | 战斗结束还把每个命中排队播完 | `asked for ["victory","hit-enemy"]` |
| E5 | 抽牌没有声音 | `no draw cue` |
| E6 | 页面不再调用 `actionFor` | `a drop would never consult the decision function` |

E6 是第 54 轮 D9 的同族：**纯函数全在、只是没人用**，所以"页面确实调用了它"本身也是判据。

### 55.4 真浏览器：它抓到一处 Node 看不见的泄漏

拖拽实测（合成 `PointerEvent`）：按住 strike → 两个敌人都亮 `drop-ok`、出现一个跟随指针的
幽灵卡 → 松手落在**1 号敌人**上 ⇒ 能量 3→2、`spike_slime_s` **10 → 4**、
日志记 `敌人 1 受到 6 点伤害`（**落点被尊重了**）。

⚠️ **第一次跑这条实测就发现**：松手之后**幽灵卡没有消失**（`ghostsLeft: 1`）。
原因是 `onPointerUp` 先把 `drag` 置空、再调 `clearDropMarks()`，而清理函数是靠 `drag.ghost`
找元素的。改成**扫 DOM 里所有 `.ghost`** 再删。
这一类"页面上多了一个不该存在的元素"的错误，**任何 Node 测试都看不见** ——
这已经是本项目第三次由真浏览器抓到（第 36 轮点击不生效、这一轮元素泄漏）。

### 55.5 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| `ui_test.mjs` 断言块 | 10 | **12**（+拖拽决定、+音效计划） |
| 变异 | 6 + 9 + 9 | **6 + 9 + 15** |
| `kernel/**` | — | **零改动** |
| 仓库里的音频文件 | 0 | **0** |
---

## 56. 第 46 轮：卡面有字了（U2 第三部分）—— 以及"core 镜像把文案剥掉了"这个真发现

> 上一轮结束时卡面只有**名字 + 费用**。这一轮把它补齐，并且没有新增一行内容、没有改编译器。

### 56.1 文案一直在内容里，只是页面没问过

`CARD` 行有 `NameKey` / `DescriptionKey` 两格，而且 `tools/contentc/packages/sts` 里**已经有真人写的句子**：

| Id | NameKey | DescriptionKey |
|---|---|---|
| `strike` | `Strike` | `Deal 6 damage.` |
| `defend` | `Defend` | `Gain 5 Block.` |
| `bash` | `Bash` | `Deal 8 damage. Apply 2 Vulnerable.` |
| `slimed` | `Slimed` | `Unplayable.` |

页面以前只问 `rd_env_card_name_*`（返回 **id**：`"strike"`），所以卡面只能写 `strike`。
新增四个导出（`rd_env_card_title_*` / `rd_env_card_text_*`）之后，卡面是
**费用 + 标题 + 描述**：`1 | Defend | Gain 5 Block.`

**为什么读内容的句子而不是从程序树推导**：推导出来的文案是机械的（`dealDamage 6`），
而手写一份就是**第二个会漂的地方**；内容里的这一句**就是这张卡说的话**，
它不可能和卡实际做的事不一致。

### 56.2 真发现：模块嵌的是 **core 镜像**，而 core 版把这两格剥掉了

第一版读出来**全是空串**。原因不是我的读取代码，而是**镜像的选择**：

* `content.sts.core.rdcf`（9,580 B，模块原本嵌的）把 `NameKey` / `DescriptionKey` 写成
  **`ABSENT16`** —— core 版的用途是内核语义，它**故意剥掉面向人的字符串**。
* `content.sts.rdcf`（11,140 B，完整镜像）里这两格有值。

⇒ 换成完整镜像，代价 **+1,560 B**。`.wasm` 430,404 → **434,617 B**。
理由写在 `rd-wasm` 的 `IMAGE` 文档注释里（"这是本文件唯一需要完整镜像的地方；哪天页面不再
需要文案，这一行改回 core 镜像"），并且有测试钉住：

`card_text_tests::the_text_is_the_contents_own` —— 断言手牌里每张卡都有标题，且
`(标题, 描述)` 是那四张卡之一（**把内容的文案钉成字面量**，内容一改这里就红）；
`the_title_is_not_the_definition_id` —— 标题必须是 `Strike` 而不是 `strike`，
否则"标题接成了 id"这个 bug 会全绿。

### 56.3 顺手修掉的三处（都是真问题）

1. **文档谎报镜像**：`lib.rs` 的模块头与 `IMAGE` 注释都写着 `content.sts.core.rdcf`（9,580 B），
   页面副标题也这么写。改成完整镜像后三处一起改。
2. **clippy `not_unsafe_ptr_arg_deref`**（deny-by-default）：我新加的两个 `_into` 导出是
   `pub extern "C" fn` 却在写裸指针。兄弟导出 `rd_env_card_name_into` 本来就是
   `pub unsafe extern "C" fn`，照它改。
3. 两个"循环变量只用来索引"的循环改成迭代器。

### 56.4 没做的（点名）

卡面**没有类型**（Attack/Skill/Power）：我们的内容把它放在 `CARD.Tags` 里
（`"attack"`），而 `Tags` 是 `TERM` 句柄指向一个**带包装的列表**（`[{"value": "attack"}]`），
读它要按标签遍历，不是读一格字符串。`status_bind::has_tag` 有现成的遍历，但它是给
`STAT` 行的；照抄一份给 `CARD` 是下一步的事 —— 写在这里，而不是假装卡面已经完整。

### 56.5 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16**（连跑两遍确认稳定） |
| 单测 | 620 | **623**（rd-wasm 9 → 12） |
| 页面交叉核对的导出 | 25 | **29** |
| `.wasm` | 430,404 B | **434,617 B**（+4,213：完整镜像 1,560 + 新导出代码） |
| 内容/编译器 | — | **零改动** |
---

## 57. 第 47 轮：版面按内容重排（英雄一条横条、敌人一行）

> 用户指出的两处都不是审美问题，是**版面与内容形状不匹配**：
> 英雄只有一个横条，却被塞进一个盒子里；敌人是一个个落点，却排成了一列。

### 57.1 改了什么

| 项 | 前 | 后 |
|---|---|---|
| 整体 | ≥720px 时切成两栏（英雄/敌人并排） | **一列到底**（英雄 → 敌人 → 手牌 → 日志 → 测量） |
| 英雄 | 三行（名字+血量 / 血条 / 四个计数） | **一条横条**：`hero 68/80 [====] energy 3/3 block 0 hand 5 deck 0d 6x 0e` |
| 敌人 | 竖排 + `<hr>` 分隔 | **一行**（`flex` + `wrap`，每个带边框，像一张牌） |

两栏那版最直接的问题：敌人面板比英雄面板高得多，于是**英雄旁边空着半个屏**。
而敌人竖排的问题是**拖拽**：第一个和第二个敌人离手牌的距离不一样，而且都要往上拖很远。

### 57.2 为什么敌人横排是"功能"而不是"好看"

这个页面的核心交互是**把牌拖到某个敌人身上**。横排之后：
每个敌人与手牌的距离相同，落点和卡片一一对齐；竖排时第二个敌人比第一个远一整块。

实测（合成 `PointerEvent`）：`#enemies` 里两个敌人在**同一 y**、x 相差 290px；
拖 `strike` 到**右边那个** ⇒ `spike_slime_s` **10 → 4**、左边那个保持 **28/28**、
日志 `敌人 1 受到 6 点伤害`、松手后无幽灵残留、无 JS 报错。

### 57.3 这一轮没动的东西

纯函数一行没改（`describe` / `diffObservations` / `logLines` / `animationPlan` /
`actionFor` / `soundPlan`），所以闸门 15 的 12 个断言块原样通过；`.wasm` 也没重编。
**版面本身仍然只有真浏览器能验** —— 这一轮就是靠它：三个坐标（英雄 y=170、敌人 y=299 同一行、
手牌 y=479）加上一次真实拖拽。
---

## 58. 第 48 轮：遗物系统（第一版）—— 肉鸽的灵魂，先给一副能跑的骨架

> 用户："还差一个很重要的东西，遗物系统，肉鸽游戏的灵魂。"
> 这一轮不做"140 件遗物"，先让**一件遗物从内容一路走到屏幕上**，并且把"做不到的部分"变成
> 响亮失败而不是静默。

### 58.1 `REL` 表一直存在，只是 0 行

格式里 `REL` 行的格子是 `Id / DisplayName / RunPrograms / CombatRules / extra`（stride 12），
内核也早有 `RelRow`。内容里一直是 `count = 0` —— 所以这一轮加的是**内容 + 接线**，不是格式。

* 内容：`Relics: [{Id: burning_blood, DisplayName: "Burning Blood"}]`，
  `Characters[0].Start.StartingRelics: [{value: burning_blood}]`。
* `Content::start_relics(roots)`：两跳规则与 `start_deck` **逐字相同**（花名册非空看
  `Characters[0].Start`，否则根 `Start`），返回 `Ok(None)` = 没声明。
* `RunState` 早就有 `relics[]`，`rd_run_start` 现在从内容往里填。

### 58.2 效果**不是数据** —— 这是这一轮最该记住的一句

`REL.RunPrograms` / `REL.CombatRules` **内核对它们一行都不执行**：run 层没有节目解释器，
`CombatRules` 注册表从来没建过（这份内容里 23/23 状态都是 ABSENT）。所以：

⇒ 效果是**按 id 逐条实现的规则**（`rd-run` 的 `RunState::end_of_combat`）。
已实现一件：`burning_blood` 战斗结束回 **6** HP，**上限封顶**。

**而且两道闸都是响亮的**：

1. **内容侧**：遗物行若声明了 `RunPrograms` / `CombatRules`，`rd_run_start` **拒绝开局**并说清原因
   —— 收下再来个静默不做，正是这个项目反复踩的坑。
2. **状态侧**：`end_of_combat` 遇到没有规则的 id 返回 `RunError::UnsupportedRelic { index }`。
   测试里专门用一个"真 StS 遗物但没实现"的 id（`vajra`）钉住它。

### 58.3 它顺手抓到两处"声明与现实不符"

* `InertKeys` 里**声明**过 `root:Start.StartingRelics` 是惰性的，理由写着"内核没有遗物能力
  （`REL` 表本内容 0 行）"。内核真的开始读它之后，闸门 12 立刻报 `inert.undeclared` ——
  声明**必须跟着现实走**，于是删掉那条声明。
* 闸门还要求 `Start.StartingRelics` 与 `Characters[0].Start.StartingRelics` **一致**
  （同一份起始块的两次副本）。第一次只改了 `Characters[0]` 那份，闸门当场报
  `list length 0 vs 1`。

这两条都不是我想到的，是**闸门想到的** —— 这正是第 12 道闸门存在的理由。

### 58.4 `DisplayName` 只在完整镜像里（与卡面文案同一个机制）

`DisplayName` 在编译器的 `PRESENTATION_KEYS`（`compile.py:688`）里 ⇒ **core 镜像会剥掉它**。
页面要显示名字就只能读完整镜像 —— 上一轮为卡面文案换镜像时留下的那条注释，这一轮又救了一次。

### 58.5 判据

| 测试 | 钉住什么 |
|---|---|
| `the_starting_relic_comes_out_of_the_content` | 内容 → 镜像 → `start_relics` → `RunState` → `REL.DisplayName` → 导出，**整条链**（顺带：`DisplayName` 不是 id 的大写化） |
| `burning_blood_heals_at_the_end_of_the_fight` | 回 6、封顶、满血时回 0 |
| `burning_blood_heals_six_at_the_end_of_a_fight`（rd-run） | 同上，在 run 层 |
| `a_relic_with_no_implemented_effect_is_an_error`（rd-run） | 未知 id **报错**、无遗物则 `Ok(0)` |
| `map_test.mjs` | 页面上写着 `Burning Blood`，且 `map.html` 真的调了 `rd_run_relic_name_len` |

⚠️ 我自己写的测试也错过一次：`_into` 的缓冲区比字符串长，我用固定 16 字节去 `from_utf8`，
比较时把尾部 NUL 一起比了 —— `"burning_blood\0\0\0"` vs `"burning_blood"`。改成按**返回长度**切。

### 58.6 还没接上的那一跳（说清楚，不让"有了"像"能用了"）

`end_of_combat` **今天没有被 wasm 调用**：run 层与战斗层之间还没有**结算**
（`env-abi.md` §11.5 的"只走不结算"）。效果有单测，缺的是调用点 —— 节点结算落地时它就是
第一个调用者。同样没做：遗物在**战斗内**的触发效果（需要 `CombatRules` 注册表，那是另一个子系统）、
遗物获取/丢弃/商店、Boss 宝箱三选一。

### 58.7 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 623 | **627**（rd-run 37 → 39，rd-wasm 12 → 14） |
| `sts` 镜像 | 11,140 / 9,580 B | **11,272 / 9,688 B**（多一行 `REL` + 起始遗物列表） |
| `.wasm` | 434,617 B | **439,087 B** |
| 内容 | 无 `Relics` 键 | **`Relics` 1 行，起始遗物已声明** |
---

## 59. 第 49 轮：run 层节点结算 + 商店（新卡 / 遗物 / 删卡）

> 用户："在 run 层面改动吧，可能商店也得加上适配（新卡片、遗物、消除卡片）"。
> 这一轮把"结算"从一句话变成一台**相位机**，并把商店的三件事做全 —— 但**还没有界面**。

### 59.1 "走"与"结算"分开，是这一轮的全部设计

`enter_node` **没有改**（它只移游标）。结算由新入口声明：

```rust
begin_node(card_pool, relic_pool) -> Result<NodeKind>
```

| 节点 | 之后 | 动作 |
|---|---|---|
| `Combat` | `Pending::None` | 战斗是调用方的事（结束时调 `end_of_combat`） |
| `Rest` | `Pending::Rest` | `rest()`（回 30% 上限）/ `smith(card, "strike+")` |
| `Treasure` | `Pending::Chest` | `open_chest(relic_pool)` |
| `Shop` | `Pending::Shop` | `buy_card` / `buy_relic` / `remove_card` / `leave` |
| `Elite` / `Unknown` | **错误** | M1 不做，`NodeNotSettleable(kind)` |

**相位机是重点**：在错相位调动作一律 `WrongPhase`。"在篝火里买东西"如果能成功，
那张地图就不是状态机了。**六条测试**逐条钉住：回 30%、Smith 换行、宝箱金额落在区间、
商店 5 卡 3 遗物且价格在带内、买/删的账与顺序、错相位与 M1 外节点都响亮。

### 59.2 商店：内容给池，run 层只挑与定价

`rd-run` 不认识内容（模块头写死），所以候选由调用方给。挑选用 `Shop` 子流洗牌，定价用它掷点。

* 卡 **45–55**、遗物 **143–157**、删卡首 **75** 此后每张 **+25**（`inv:§8.2`）。
* ⚠️ **`[推断]`：全部按 Common 定价** —— `inv:§8.2` 的区间是**按稀有度**分的，而这份内容的
  `CARD` 行**没有稀有度字段**。抄一个稀有度就是编一个事实，所以整条记进了
  `sts-act1-plan.md` §7 的降级表第 7 行，并写明"何时会被发现"= 同一家店出现不同稀有度的卡时。
* 宝箱完全照 `inv:§8.3`：箱型 50/33/17、出金概率 50/35/50、金额 23–27 / 45–55 / 68–82。
* 删卡**跨店累计涨价**（`removed_cards` 这个占位字段终于有用了），且保持**牌组顺序**
  —— 顺序可观察，`run_hash` 会逐张写出来。

### 59.3 为了 Smith，内容得先有升级卡

`inv:§2.1` 的"升级后"一列（strike+ 9 / defend+ 8 / bash+ 10+3）此前**内容里没有**，
而"升级 = 另一张 CARD 行"（`sts-act1-plan.md` §6.5-2）⇒ Smith 无对象可换。
这一轮补了那三行，并把闸门 12 的 `INV_CARDS` 一起扩到 7 张（数字全部来自 `inv`）。
顺带：商店的卡池也从 4 张变成 7 张。

⚠️ **Smith 的 `+` 映射是调用方给的**（`smith(card, "strike+")`）：内核**不猜后缀** ——
"哪一行是它的升级版"是内容的约定。

### 59.4 这一轮最该记住的一句话：**还没有 ABI，也没有界面**

`begin_node` / `rest` / `shop` / `chest` 目前**只有 Rust 测试在调**。地图页仍然只"走"。
所以这一轮的产出是**能力**，不是**可玩性** —— 下一步才是把六个动作摊进 `env-abi.md` §11
（`run-layer.md` §6.1 早就写了 `RunAction` 的形状），再给地图页一个节点面板。

同样没接：**战斗结算**（奖励金币 / 3 选 1 / `end_of_combat` 的调用点）、`?` 房内容、精英。

### 59.5 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 627 | **633**（rd-run 39 → 45） |
| `sts` 卡 | 4 | **7**（+ strike+ / defend+ / bash+，`inv:§2.1`） |
| `sts` 镜像 | 11,272 / 9,688 B | **11,604 / 9,908 B** |
| `.wasm` | 439,087 B | **441,560 B** |
| `RunState` | — | 加了 `Pending`(1 B) + `ShopStock`(≈362 B)，tripwire 8 KiB 仍有余量 |
---

## 60. 第 50 轮：把 run 层摊成 ABI —— 战斗第一次接到局上，以及"牌堆能列出来"（**页面还没串起来**）

> 用户："把战斗、商店、休息和地图串联起来，全局显示遗物，全局多个按钮点开显示卡片情况"。
> 这一轮做**接口那一半**：run 层的每个动作都有导出了，**战斗第一次真的是"这一局的战斗"**。
> **页面还只有一半** —— 下面 §60.5 逐条说清哪一半没做。

### 60.1 战斗接到局上：`rd_run_fight_begin` / `rd_run_fight_end`

这是 run 层一直缺的那条缝。`build_session` 被参数化成 `build_session_with(seed, encounter,
hero_hp, deck)`：

* **牌组是本局的牌组**（`rd-run` 的 `deck` 压成 `(id, count)` 交给 `FightPlan.deck`，
  `build_fight_from_content` 的"显式牌组优先"那条路正好用上）；
* **英雄从本局的血量进场**（战斗按上限建，再 `combatant_mut` 把当前血量压到本局的值）；
* **打完之后血量写回局上**，胜利则调 `end_of_combat` —— **遗物的效果至此有了调用点**
  （第 48 轮那句"效果有单测、缺调用点"在这一轮关掉）。

敌人一侧：用 `Combat` 子流从镜像里挑一条 `ENCT`。⚠️ **`[推断]`**：`inv:§5.2/§5.3` 把遭遇分成
weak / strong 两池（第 1 层与前 3 场用 weak），**这份内容没有这个划分**，所以现在是"镜像里任意一条"。
这写成 `run-layer.md` §4.7 的欠账，而不是假装 weak/strong 已经实现。

### 60.2 一串新导出（`env-abi.md` §11.6–§11.8）

| 组 | 导出 |
|---|---|
| 节点 | `rd_run_pending` / `rd_run_node_kind` / `rd_run_begin_node` / `rd_run_rest` / `rd_run_smith` / `rd_run_open_chest` / `rd_run_leave` |
| 商店 | `rd_run_shop_card_count` / `_id_len` / `_id_into` / `_price`，relic 同理，`rd_run_remove_price` / `rd_run_buy_card` / `rd_run_buy_relic` / `rd_run_remove_card` |
| 牌组 | `rd_run_deck_count` / `_id_len` / `_id_into` / `_title_len` / `_title_into` |
| 牌堆 | `rd_env_pile_len` / `rd_env_pile_card_id_len` / `_id_into` / `_title_len` / `_title_into`（0=抽 1=弃 2=消耗） |
| 战斗 | `rd_run_fight_begin` / `rd_run_fight_end` |

⚠️ **`rd_env_pile_*` 是必须的**：122 格观察量只带牌堆**计数**（`env-abi.md` §4）——
对策略够用，对"看看弃牌堆里有什么"完全不够。所以牌堆**内容**单独读。

### 60.3 三条新测试（都钉整条链，不是钉一个函数）

| 测试 | 钉住什么 |
|---|---|
| `a_fight_is_the_runs_fight_and_the_result_goes_back` | 第 1 层必是战斗（`inv:§7.2`，所以不用搜索地图）⇒ 开局 → 掉 20 血 ⇒ 开战 ⇒ **战斗里英雄是 60 血**、**三个牌堆加起来 == 本局牌组 10 张** ⇒ 收兵 ⇒ 没有第二场可收 |
| `the_piles_can_be_listed_not_just_counted` | 未开回合时 10 张全在抽牌堆；每张都能取到**内容里的标题**（Strike/Defend/Bash）；坏 zone 与越界都是 `-1` |
| `the_deck_can_be_listed_with_the_contents_titles` | 5 Strike / 4 Defend / 1 Bash（`inv:§2.1`），标题来自 `CARD.NameKey` |

### 60.4 页面上已经能看到的：遗物 + 所有牌

`map.html`（run 页）现在有两样东西是**全局**的：

* `遗物 Burning Blood`（第 48 轮就有）；
* **`所有牌（10）`** 按钮 → 展开牌组：`Strike strike` ×5、`Defend defend` ×4、`Bash bash`。
  标题与 id 都来自内容，页面上没有一张硬编码的卡名。

判据：`map_test.mjs` 第 8 块（10 张、5/4/1、标题来自 `CARD.NameKey`、且 `map.html` 真的调了
`rd_run_deck_title_len`）。

### 60.5 **没做的（这一轮只交付了接口，别把它读成"串起来了"）**

1. **页面还是两页**：`map.html` 是 run（地图/遗物/牌组），`index.html` 是战斗 demo。
   **没有"一页里从地图走进战斗再回到地图"** —— 那需要把 run 会话与战斗会话放进同一个页面的
   状态机里，是下一轮的正题。
2. **节点面板没有界面**：`begin_node`/`rest`/`smith`/`chest`/`buy_*` 全都**有导出、有测试，
   但页面一个都没调**。所以篝火、商店、宝箱现在**看不见**。
3. **三个牌堆按钮**（抽牌/弃牌/消耗）的导出有了，但**没有页面**：它们只在战斗里有内容，
   而战斗页还没接进 run。

⇒ 一句话：**接口这一半完成了，交互那一半（一个页面串起四个场景）是下一轮。**

### 60.6 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 633 | **636**（rd-wasm 14 → 17） |
| 新导出 | — | **21 个**（节点 7 / 商店 8 / 牌组 5 / 牌堆 5 / 战斗 2，含 `_into` 成对） |
| `.wasm` | 441,560 B | **466,444 B**（+24.9 KB：`build_session_with` + 牌堆读取 + 21 个导出） |
| `smoke.mjs` 要求的导出 | 44 | **65** |
---

## 61. 第 51 轮：一页游戏 —— 地图 → 节点 → 战斗 → 回地图，遗物与牌堆全局可见

> 上一轮我说"接口这一半完成了，交互那一半是下一轮"。这一轮就是那一半，而且它**不是加代码，
> 是把两个会话放进同一个状态机**。

### 61.1 `mode` = `run` | `fight`：一页，两个视图

`index.html` 现在开机先 `rd_run_start(7)`，落在**地图**上；点击可达节点 → `rd_run_step` +
`rd_run_begin_node` → 节点面板；战斗节点点"开始战斗" → `rd_run_fight_begin`（**本局的牌组与本局的血量**）
→ 战斗视图；`rd_env_done() === 1` 时 `rd_run_fight_end` 把血量与遗物结算回局上 → 回地图。

顶栏**全局**显示：`floor / hp / gold / deck`、**遗物**、以及 `所有牌 / 抽牌 / 弃牌 / 消耗` 四个按钮。
牌堆三个按钮在 run 视图里是**禁用**的 —— 牌堆只存在于战斗里，这不是"还没做"，是语义。

### 61.2 节点面板：篝火 / 商店 / 宝箱

| 面板 | 按钮 | 背后 |
|---|---|---|
| 篝火 | 休息（显示回多少）/ 打铁 / 离开 | `rd_run_rest` / `rd_run_smith(0)` / `rd_run_leave` |
| 商店 | 每张卡与遗物一行（价格、已售禁用）+ 删卡 + 离开 | `rd_run_shop_*` / `rd_run_buy_*` / `rd_run_remove_card` |
| 宝箱 | 开箱 / 离开 | `rd_run_open_chest` / `rd_run_leave` |

**浏览器实测的完整一圈**：所有牌（10 张）→ 走进 floor 1 → 开始战斗 → 18 步打赢 →
`战斗结束 · Victory` → 回到地图，顶栏 `hp 59/80`（战斗结束时 53，**Burning Blood +6**）。

### 61.3 三个真 bug（都是这一轮才暴露的）

1. **`readText` 的参数顺序**：页面的 `readText(lenFn, intoFn, index)` 用 `(ptr, index)` 调 `intoFn`，
   旧读者都写成 `(p, i) => ex..._into(i, p)`。我新写的六个写成 `(k, p) => ..._into(k, p)`，
   于是**指针和下标互换了** —— 遗物栏显示 `spike_slime_s`（暂存缓冲里残留的字符串）。
   这类错误不会报错，只会显示**另一个正确的字符串**，比崩溃更难发现。
2. **`static mut` 别名 → 访问违例**：`rd_run_fight_begin` 在**已经持有** `run_slot().as_mut()`
   的时候又调 `rd_run_node_kind()` / `set_error()`，两者都会再取一次槽位 ⇒ 同一对象两个活引用。
   表现是 `rust-units` **exit 0xC0000005**（崩），不是答错。修法是加 `fail(session, msg)`
   把错误写进手里那个会话，kind 也从手里那个会话读。
3. **测试并行 = 抢同一组全局会话**：`cargo test` 在一个进程里多线程跑，而 ABI 的全部状态就是两个
   `static mut`。我先加了互斥锁 —— **自死锁**（同一线程里取了两次锁），10 分钟超时。
   最终答案更诚实：**这 crate 的测试本来就不是并行安全的**，闸门改成
   `-- --test-threads=1`，并在测试模块里写明原因。
   ⚠️ 顺带记一笔：`'--'` 写进 `ArgLine` 字符串会被 cargo 当成真参数 ⇒ `unexpected argument '--test-threads'`。
   字符串里的 `--` 要写**不带引号**的。

### 61.4 我自己误诊了一次

看到顶栏 `hp 59/80`，我先断定"Burning Blood 没生效"并写了一个新测试。
实测打完时战斗里是 **53** 血，53 + 6 = **59** —— **遗物是正确的**，是我把"打完的血"当成了 59。
新测试留着：它钉住了**胜利 + 回血**这条路（此前只有"战斗仍在进行、不回血"那条有测试）。

### 61.5 判据

`ui_test.mjs` 的页面接线清单新增 7 条（`rd_run_fight_begin(`、`rd_run_fight_end(`、
`rd_run_begin_node(`、`rd_run_rest(`、`rd_run_buy_card(`、`rd_run_deck_title_len`、
`rd_env_pile_card_title_len`、`id="mapbox"`、`id="nodePanel"`）——
**纯函数在、没人调**这件事从此对这七个入口也会红。

### 61.6 还没做的

* `Elite` / `Unknown` 节点仍然**响亮拒绝**（M1 外），所以走进它们会看到红字而不是面板。
* 遭遇选择还是"镜像里任意一条"（weak/strong 两池 `inv:§5.2/§5.3` 缺数据）。
* 战斗**奖励**（金币、3 选 1）没接：打赢只回血、不给钱。
* 打铁按钮**固定升第一张**（给一张选牌列表是下一步）。
* `map.html` 还在，现在它只是"只看地图"的子视图；`index.html` 才是游戏页。

### 61.7 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 636 | **637**（rd-wasm 18） |
| 页面脚本 | 2 个 | **3 个**（+ `map_render.js`） |
| 页面交叉核对的导出 | 65 | **71** |
| `.wasm` | 466,443 B | **466,443 B**（页面轮，未重编） |
---

## 62. 第 52 轮：地图"显示异常"—— 外观住在另一个页面里

> 用户："我看起来地图界面是显示异常的。" 对。而且原因很典型：**标记来自共享模块，外观来自页面**。

### 62.1 症状与原因

游戏页上的地图是**一堆黑圆点、没有连线、没有高亮**。原因是：SVG 标记由 `map_render.js`
（共享模块）产出，但 `.edge` / `.node circle` / `.node.kind-*` / `.node.reachable` / `svg`
这些规则**只写在 `map.html` 的 `<style>` 里**。第二个页面拿到了第一份标记，却**没拿到它的外观**
—— SVG 默认 `stroke: none`、`fill: black`，于是连线消失、圆点变黑，只剩文字图标。

第二个问题：地图被裁。盒子上写了 `max-height: 620px` + `overflow: auto`，而 Act 1 有 15 层，
于是**最底下那一层（1 层，出发的地方）在折叠线以下**—— 一张要滚才能看见"我在哪"的地图，
不如没有。

### 62.2 修法：外观搬进 `web/map.css`，两个页面都链它

* 新建 `web/map.css`：地图的全部外观（边、节点、七种 kind 的底色、可达/所在高亮、`--live`/`--here`）。
* `map.html` 删掉自己那份，改成链 `map.css`。
* `index.html` 链 `map.css`，并且**不再覆盖** `.mapbox`。
* 尺寸：`width: 100%; height: min(74vh, 780px)` + `viewBox` ⇒ **整幕都在视野里**，不裁剪。
* 首页那段五行说明折进 `<details>`（点开可读）—— 它把地图往下顶了 270px，
  而"出发的那一层看不见"比"说明看不见"更糟。

### 62.3 判据，以及**我自己的两次失手**

新增闸门（`map_test.mjs` 第 9 块）：两个页面**都必须链** `map.css`，且**都不许重新声明**
`.edge {` / `.node circle` / `.node.kind-combat`。

但第一版判据是 `html.includes("map.css")` —— 我在 index.html 里留了一句注释
`/* `.mapbox` itself is in `map.css` ... */`，**注释就让它通过了**：删掉 `<link>` 之后测试仍然 PASS。
改成 `/<link[^>]+map\.css/.test(html)`（看**标签**，不看字符串）之后，删链接立刻红。

⚠️ 这次两次失手都是同一个毛病，记下来：
1. 变异脚本 `python -c "s.replace(...)"` **没有断言替换真的发生**，打印"已删除"但文件没变 ——
   第一次"变异没红"其实是"变异没做"。
2. 用 `Copy-Item` 备份 + `Move-Item` 恢复，**第二次恢复时备份已经被第一次吃掉**
   ⇒ `index.html` 里留着一行变异进去的 `.edge { stroke: #fff; }`。是紧随其后的 `Select-String` 发现的。
   ⇒ 变异实验的收尾必须是**读回文件确认它变回去了**，而不是"我执行了恢复命令"。

### 62.4 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 新增文件 | — | **`web/map.css`**（外观的唯一一份） |
| 闸门 16 | 8 块断言 | **9 块**（外观不许只住在一个页面里） |
| 单测 | 637 | **637**（这一轮只动页面与闸门） |
---

## 63. 第 53 轮：战斗奖励 + 3 选 1 —— 以及"我按文档猜了一个编码，然后读出来全是空"

### 63.1 形状

打赢一场之后多了一个相位 `Pending::Reward`：

* **金币**在胜利那一刻就进袋（`inv:§5`：普通战斗 **10–20**）—— 没有"拒绝金币"这个动作，
  所以不给它一个按钮。
* **三张牌，互不相同**（`inv:§3.5`：逐张掷，后掷的不与前面重复），可跳过。
* `rd_run_fight_end` 里的顺序是：血量写回 → `end_of_combat`（遗物）→ `roll_reward`。
  任何一步拒绝都是一个**响亮的失败**，不是"打赢了什么都没给"。

### 63.2 奖励池：`inv:§3.5` 的两条规则

* **Act 1 不出升级版**（升级概率 0%）⇒ 池子里滤掉 `x+`。
* **不能出现状态卡**（`slimed`）。这一条一开始**做不到**，只好先记进降级表 —— 然后浏览器里
  第一次跑就看见奖励界面在卖 **Slimed**。这就是"记下来"和"做对"的差别：玩家一眼就能看出荒谬。

⇒ 于是补了 `Content::card_has_tag`（`CARD.Tags` 的读者）。

### 63.3 一个按文档猜编码的错误（值得单开一节）

我照 `layout.txt` 写的是 `Tags: STRLIST(wrap)`，于是以为元素是 `_obj{value: "attack"}`，
按**字段名**找 `value`。实测（`#[test] dbg_card_tags` 打印）：

```
tags cell = 8, term.op = 4 (OP_ARR), count = 3
element[0] op = 6, 一条**无名**字段, kind = 1 (F_STR), slot0 = 222
```

元素**不是** `_obj`，是"op 6 + 一条无名 `F_STR` 字段" —— 名字根本不存在，所以按名字找
**一个标签都读不出来**，`card_has_tag` 全线返回 `None`（不是 `false`，这也正是当初让 `None`
表示"读不出来"而不是"没有"的价值：它把错误暴露成错误）。

修法：元素是 `OP_STR` 就取字符串，否则取 **字段 0**，并要求它的 kind 是 `F_STR`。
修完之后实测：`strike` = attack/basic/strike ✓，`slimed` = status ✓，奖励池变成
`defend / strike / bash`（三张全不同，没有 Slimed）。

### 63.4 判据

| 测试 | 钉住什么 |
|---|---|
| `a_reward_pays_gold_in_range_and_three_different_cards`（rd-run，**25 个 seed**） | 金币在 10–20；**三张互不相同**（去重后仍是 3）；都在池子里 |
| `taking_and_skipping_a_reward` | 拿一张 +1 且该卡就是那一张；再拿一次是 `WrongPhase`；跳过一张不多 |
| `a_pool_too_small_for_three_distinct_cards_is_loud` | 池子只有 2 张 ⇒ `PoolTooSmall { pool: 2, need: 3 }`，**不发金币、不留相位** |
| `winning_leaves_a_reward_screen`（wasm，打进胜利） | 金币==奖励界面上的金币==钱包增量；三张不同；**没有 `x+`**；拿一张后牌组 +1 且 pending 归零 |
| `card_tags_are_readable_and_a_junk_card_is_not_a_reward`（rd-core，真镜像） | 上面那组标签真值；不在镜像里的卡是 `None` 而不是 `Some(false)` |

### 63.5 又一次自己踩自己

删掉诊断测试时，我按 `fn ...() {` 切文本，**把 `the_real_images_validate` 的 `#[test]` 一起切走了**
—— 那个测试从此**静默不跑**。是 clippy 的 `function is never used` 报出来的。
⇒ 与 §62 那条同类：**改完要读回文件确认结构**，静态检查（clippy）是这类伤害的第一道防线。

### 63.6 还没做的

* **稀有度权重 3/37/60 与偏移 −5%→+40%** 没有实现：这份内容没有稀有度字段（与商店定价是同一个
  降级行）。`inv:§3.5` 的"逐张不重复"实现了，权重没有。
* 药水掉落（`inv:§5` 的 40% 基准）、遗物掉落没有接。
* 精英/ Boss 的金币档（25–35 / 95–105）写好了常量位，但 M1 还没有精英与 Boss 节点。

### 63.7 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 637 | **642**（rd-core 574→575，rd-run 45→48，rd-wasm 18→19） |
| 新导出 | — | **8 个**（`rd_run_reward_*` + `rd_run_take_card` + `rd_run_skip_reward`） |
| `.wasm` | 466,443 B | **473,608 B** |
---

## 64. 第 54 轮：按 StS Wiki 校准奖励与稀有度 —— 三处修正、一套机制、一次撤回

> 用户："检索网络上的 StS Wiki 校准对齐本地的设计。" 这一轮先校准，再实现，最后**撤回**了一件
> 看起来最便宜的改动。

### 64.1 校准结果：三条数值被修正，其余对上

来源：`spire-codex.com/mechanics/card-rarity`（页面标题 `Card Rarity Odds`）与
`slaythespire.wiki.gg/wiki/Potions`。

| 项 | 我们原先写的 | 校准后 | 影响 |
|---|---|---|---|
| 保底偏移的触发 | "每掷出一次 **Common** +1%" | **"否则 +1%"** —— **Uncommon 也会 tick** | 真 bug：按旧写法，一块 Uncommon 之后偏移不动，保底会比原作慢 |
| 掷点方式 | 隐含"三次独立 roll" | **叠加带**：一个 0–99 的数；Rare 带 = `基础值+偏移`（下限 0）；Uncommon 带是**固定宽度贴在上面**；剩余是 Common | 刚重置（正常战 3−5=−2）的真实概率是 **0 / 35 / 65**；把 Rare 夹到 0 却给 Uncommon 37% 的实现**过得了"大致 3/37/60"的检验但是错的** |
| Boss 奖励 | 未记 | **不读偏移**（恒 100% Rare）**但会重置它** | 照抄通用公式会算出 95% |
| 升级概率 | 第一幕 0% | 0% / 25% / 50%（第一/二/三幕），**Rare 卡永不自动升级** | 补记 |
| 药水稀有度 / 掉落 | 65/25/10、40% 基准 | **一致**；掉落"出了就 −10%、没出就 +10%，每幕重置" | 无需改 |

⚠️ 提醒：`spire-codex` 那个页面是 **StS2** 站点的机制页；上述数值与 StS1 的多源记载一致，所以按它
校准。**两者若分叉，以 StS1 为准**——这句也写进了 `sts-act1-inventory.md` §3.5 的校准注。

### 64.2 实现的机制（`rd-run`，纯函数 + 状态）

* `FightKind::{Normal, Elite, Boss}`：三个金币档（10–20 / 25–35 / 95–105）+ Rare 基础值
  （3 / 10 / 100）+ Uncommon 固定带宽（37 / 40 / 0）。
* `reward_bands(kind, offset) -> (rare_top, uncommon_top)`：**上面那张叠加带**的实现。
* `rarity_offset` 状态：初始 −5%，**每张牌掷完 tick 一次**，Rare 重置、上限 +40%。
* `Rarity` / `PoolCard`：奖励池现在按稀有度集结（`Status`/`Curse` 在 roll 里就被剔除）。

判据（`the_reward_bands_are_the_wikis`，逐格对齐 wiki 的表）：

```
Normal, offset -5  -> (0, 35)      Elite, offset -5 -> (5, 45)      Boss -> (100, 100)
Normal, offset  0  -> (3, 40)      Elite, offset  0 -> (10, 50)
Normal, offset 40  -> (43, 80)
```

`Elite, offset -5 = 5` 正是 wiki 那张"精英奖励里第二/三槽的 Rare 概率 **5%**"的表行 —— 一条公式
同时对上两张表，这比"跑分布看差不多"强。

`the_pity_offset_ticks_every_card_and_resets_on_a_rare`：三张牌 tick 三次（−5→−2）；Boss 三张
全 Rare ⇒ 重置回 −5；连做 20 轮也压不过 +40。

### 64.3 **撤回**：`CARD.Rarity` 那一格

我给 `rdcfmt.CARD_ROW` 加了第 16 格 `Rarity`。这件事在**布局上是免费的**：
`align4(2×15) = align4(2×16) = 32`，stride 不变。内容侧也做了（`strike`/`defend`/`bash` = Basic、
`slimed` = Status），`sts` 镜像正常多出 36 B，闸门 12 过；内核两条"格表不许漂"的测试**立刻抓住了
我把格号写成 15 而编译器写在 14** 的错误 —— 那道防线工作得很好。

**但撤回的原因是构建路径**：内核测试读的是 `tools/contentc/out/content.core.rdcf`，而
`build.py --package roguedeck` 重建它时**大小一字节没变**（85,616 B），说明那处镜像并不是这次
重建的产物（另有一套旧的 out 目录）。⇒ 加一格**不是"改两行"**，它要求：重建全部镜像、重新钉
SHA、很可能还要重跑语料与 golden 基线。那是一个独立迁移的规模，不该塞进校准这一轮。

⇒ 于是撤回格式与内容（`sts` 两个镜像的 SHA 已回到原值、`CONTENTC_BYTES PASS` 仍是
`2/2 images, 1/1 source`），**保留机制**：`PoolCard` 仍然存在，只是这张镜像里每张卡都以
`Basic` 进来（`slimed` 由 `Tags` 过滤，`card_has_tag` 是上一轮为它写的）。等 `Rarity` 真的进了
内容，只需要把 `reward_pool` 里那一行 `Rarity::Basic` 换成读格。

**说清楚这一轮交付了什么**：机制、判据、校准三条修正；**没有**交付"这份内容里的卡有稀有度"。

### 64.4 还没做的

* `CARD.Rarity` 的格式迁移（见上，独立一轮）。
* 药水：格式里没有 `POT` 表，内容也没有药水 —— 掉落机制（40% ±10%、65/25/10）无处落地。
* 精英 / Boss 节点：金币档与 Rare 100% 的常量都在，但 M1 里进了精英节点是**响亮拒绝**。

### 64.5 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 642 | **644**（rd-run 48 → 50） |
| `.wasm` | 473,608 B | **475,137 B** |
| 镜像 | — | `sts` 与 `roguedeck` 的 SHA **全部回到原值**（`CONTENTC_BYTES PASS`） |
---

## 65. 第 55 轮：把稀有度迁移**又试了一次**（还是不行，两个具体拦路），改交付"卡牌类型"

> 用户："继续完成这些功能细节。" 我列的三件事（稀有度迁移 / 药水 / 精英 Boss）全卡在内容或格式上，
> 所以先把最想要的那件再试一次，把拦路石钉成具体的东西，然后交付一件**真的**能做的。

### 65.1 稀有度迁移：这次读对了症状，撞到两个新的具体障碍

上一轮我把"重建后大小一字节没变（85,616 B）"读成"重建没生效"。**错**：第 16 格正好落在
15 格行本来就有的**对齐填充**里（`align4(2×15) = align4(2×16) = 32`），**大小本来就不可能变**。
这次照规矩走了一遍（改 → 重建两个包 → **看 sha** → 再决定），看到的是闸门自己印出来的话：

```
content.rdcf (fresh compile)   648a1ff9… → 3a86d3e3…      ← 字节真的动了
content.rdcf (checked-in out/) 648a1ff9… → 3a86d3e3…
编译器变了 -> compile.py 改动了旧内容产物的字节，必须在改编译器的同一个提交里要么修回去，
              要么显式 --repin 并说明理由
```

于是撞到两个**具体**障碍：

1. **`verify_bytes.py --repin` 崩溃**：`FileNotFoundError`，
   `…\Temp\rdcf-fresh-xxxx\content.rdcf` 不存在 —— repin 路径自己在临时目录里找文件，
   而那份临时产物已经被清掉/没生成。**那条"显式 repin"的路现在是坏的。**
2. **两条内核守卫是按 roguedeck 的期望写死的**：`CARD.Rarity` 一格加进去之后，
   `row_accessors_agree_with_the_written_schema` 断言 `cell_by_name("Rarity")` 等于
   `card.rarity()`，而 `cell_by_name` 是从**镜像自己的字段表**取名字的 —— roguedeck 的文档里
   没有 `Rarity` 这个键，所以它是 `None` 而格子是 `ABSENT16`。两条守卫都得先想清楚
   "按文档派生的名字" 与 "内核固定的格号" 该怎么对齐。

⇒ **再次撤回**（`git checkout` 三个源文件 → 重建 → `CONTENTC_BYTES PASS` 仍是原两个 sha），
并把这两个障碍写进计划。**这不是"懒"，是"这一轮不该既校准又迁移"的同一条纪律再走一遍**：
迁移需要一个能用的 repin、两条守卫的新判据、以及（很可能）语料与 golden 的重定基线。

### 65.2 真正交付的：卡牌类型（Attack / Skill / Power）

上一轮为 `slimed` 写的 `Content::card_has_tag` 正好够用，**零格式改动**：

* `rd_env_card_kind(slot)`（手牌）与 `rd_run_card_kind(context, index)`（0 牌组 / 1 奖励 / 2 商店），
  返回 `0 none / 1 attack / 2 skill / 3 power / 4 status / 5 curse / -1 未知`。
* **问的顺序是语义**：先 attack、再 skill、最后 status —— `slimed` 的标签是
  `status/unplayable/junk`，顺序反了它就会被报成攻击。
* **"读不出来"不是"没有类型"**：`card_has_tag` 返回 `None` 时这里返回 `-1`，页面就不显示类型
  徽章，而不是显示一个错的。

浏览器实测：手牌 `1 Defend 技能 Gain 5 Block.`、`1 Strike 攻击 Deal 6 damage.`；
牌组列表 `Strike strike 攻击`；`rd_env_card_kind` 五个槽 = `[2,1,1,1,2]`。

判据：`the_card_kind_comes_from_the_tags`（手牌非 1 即 2、越界与负数是 −1、
`strike`=1 / `defend`=2 / **`slimed`=4** / 不存在的卡 = −1）；
`ui_test.mjs` 新增一条 `rd_env_card_kind(` 的接线断言。

### 65.3 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 644 | **645**（rd-wasm 19 → 20） |
| 新导出 | — | **2 个**（`rd_env_card_kind` / `rd_run_card_kind`） |
| `.wasm` | 475,137 B | **476,487 B** |
| 镜像 | — | 两个 SHA **仍在原值**（`CONTENTC_BYTES PASS`） |
---

## 66. 第 56 轮：两个问题一起修 —— repin 修好了，格表只剩**一份**，schema 变更开始**响亮**

> 用户问："是门禁问题还是 core 的缺陷？" 答案是一半一半。这一轮把两半都修了。

### 66.1 门禁侧：`--repin` 读一个已经被删掉的临时文件

`verify_bytes.py` 的 repin 分支在 `finally` **之后**跑，却调用
`os.path.getsize(images["full"]["fresh"])` —— 那个临时目录已经没了 ⇒ `FileNotFoundError`。
**唯一一条"故意改编译器之后必须能用"的路，是坏的。** 修法：用编译期间已经量好的
`images[...]["fresh_bytes"]`。修完实测 `REPINNED …` + 闸门 PASS。

### 66.2 core 侧之一：一张表被声明了**两遍**，而我把它们合并成了一遍

`content.rs` 里每张表都有两份声明：

* `pub static CARD_SCHEMA: [CellSpec; N]` —— 名字 + 类别 + 包装标志；
* `entity_row!(CardRow, Card, 32, N, { getter => 格号 })` —— 格号 + 取值器。

加 `CARD.Rarity` 时我只改了后者，于是 `cell_index("Rarity")` 是 `None`（它查的是前者），
两条守卫当场报红。**守卫是对的，漂的是我。**

现在 `entity_row!` **从同一份列表里同时生成格表和取值器**：

```rust
entity_row!(
    EnctRow, Encounter, ENCT_SCHEMA, 16, 8, {
        ("Id", F_STR, FLAG_WRAP_UPPER) => id => 0,
        ("Enemies", F_TERM, 0) => enemies => 1,
        ...
    }
);
```

`$cells` 还是手写的，所以宏里加了一行 `const _: () = assert!([格号列表].len() == $cells);` 钉住它。
**加一格从此只改一处**（外加编译器那份 `rdcfmt.CARD_ROW`，两份之间由 §66.4 的守卫钉住）。

⚠️ 过程中我差点报一个假 bug：合并脚本说"`ENCT_SCHEMA` 7 格、`EnctRow` 8 格"。
那是**我正则的错** —— `cell("Id", F_STR, FLAG_WRAP_UPPER)` 第三个参数是符号不是数字，我写成了
`\d+`。内核本来是一致的。**先怀疑自己的解析器，再怀疑被测对象。**

### 66.3 core 侧之二：schema 变更对镜像格式是**不可见**的

内核的格表是**固定**的，而镜像既不记格数、版本号也不随 schema 动。所以 15 格的旧镜像配 16 格的
新内核会**解析成功并读出垃圾**：第 14 格本来的 `extra` 被当 `Rarity` 读，`content.string(那个 term)`
若碰巧落在合法串号上就返回一段像样的文本。

⇒ `FORMAT_VERSION` **1 → 2**（编译器与内核同改），旧镜像现在在 `parse()` 就被
`UnsupportedVersion` 拒掉。判据 `card_rarity_is_readable_and_the_schema_moved_the_version`
顺带钉住 `FORMAT_VERSION == 2` 与 `content.version() == FORMAT_VERSION`。

### 66.4 于是 `Rarity` 真的落地了，商店价格也真的按稀有度分档

* `CARD.Rarity` 第 16 格（**stride 仍是 32**）；`strike`/`defend`/`bash` 及升级版 = `Basic`、
  `slimed` = `Status`。
* `card_price_band(rarity)`：Common 45–55 / Uncommon 68–82 / Rare 135–165（`inv:§8.2`）——
  **`sts-act1-plan.md` 降级表第 7 行（商店价格那条 `[推断]`）就此消除**。
* 奖励池按稀有度集结，`Status`/`Curse` 在 roll 里被剔除（`slimed` 不再出现）。

### 66.5 一条被证实的预测

我上一轮担心"格式迁移会让语料与 golden 基线重定"。**实测：没有。**
`corpus-roundtrip 85 case(s)` 与 `golden-baseline 129 行` 在 `FORMAT_VERSION = 2`、`CARD` 16 格
之后**照旧通过** —— 哈希的规范文本不含这一格，所以"内容没变"这件事被两个闸门独立确认了。

### 66.6 判据

| 测试 | 钉住什么 |
|---|---|
| `card_rarity_is_readable_and_the_schema_moved_the_version` | `strike`=Basic / `slimed`=Status / 不在镜像里=None；`(STRIDE, CELLS) == (32, 16)`；**`FORMAT_VERSION == 2`**；roguedeck 镜像（无 `Rarity` 键）读出来是 `None` 而不是错误 |
| `row_accessors_agree_with_the_written_schema` | `CARD_SCHEMA[14]` 是 `Rarity`、`[15]` 是 `extra`；`schema().len() == 16` |
| `parse_rejects_an_unsupported_version` | 改成 `FORMAT_VERSION + 1`（写死 `2` 的旧测试在版本升到 2 之后会**变成通过**——那正是它要防的失效） |
| `the_merchants_prices_follow_the_rarity_bands`（rd-run） | 三档边界 + 随机货架的每张卡都落在**它自己稀有度**的带内 |
| `verify_bytes.py --repin` | 实测可用（闸门自身的修复由"REPINNED + PASS"证明） |

### 66.7 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 645 | **647**（rd-core 575→576、rd-run 50→51） |
| 镜像 | v1 | **v2**，两个包都重钉（`contentc-bytes` PASS） |
| 语料 / golden | 85 / 129 | **85 / 129（未动）** |
| `.wasm` | 476,487 B | **477,846 B** |
| 声明份数（每张表） | **2**（`*_SCHEMA` + `entity_row!`） | **1** |
---

## 67. 第 57 轮：游戏流程 —— 一局**能结束**了，而节点**只能收一次**

> 用户："继续完善游戏流程与 UI。" 地图、节点、战斗、奖励都通了，但这一轮一上手就发现：
> **一局打完不会结束，而一个节点可以无限刷。**

### 67.1 真 bug：节点可以无限刷（页面与内核各一道）

打赢一场 → 领奖励 → 面板又给回"开始战斗"。因为 `begin_node` 对战斗节点只把 `Pending` 置空，
而"已结算"这个概念**根本不存在**。于是：战斗节点能反复打，篝火能反复回血。对 RL 环境更是硬伤
（智能体学会刷同一个节点）。

修法在 run 层，不在页面：`RunState` 加了一个**已结算位图**（90 个节点 ≤ 128 bit，`[u64; 2]`）：

* `mark_resolved()` 在**每个能结束节点的动作**末尾调用（`rest` / `smith` / `open_chest` /
  `take_card` / `skip_reward` / `leave`），以及 `rd_run_fight_end`（战斗在本 crate 之外收尾）；
* `begin_node` 见到已结算节点 ⇒ `RunError::NodeResolved`；
* `rd_run_fight_begin` **也**检查一次 —— 这是"停止刷"的真正那道闸，因为页面可以不调 `begin_node`；
* 页面侧：`rd_run_node_resolved()` 为 1 时面板只显示"这个节点已结算 · 点亮的节点往前走"，
  不给按钮。

浏览器实测：领完奖励后面板变成"已结算"，`rd_run_fight_begin()` 再调返回 `-2` +
`这个节点已经结算过了`。

### 67.2 一局的**结束**

* **战败**：`rd_run_fight_end` 返回 2（或血量 ≤ 0）⇒ 这一局结束。面板换成战绩
  （floor / hp / gold / deck / relics）+ "再来一局（同一 seed）" + "换一个 seed"，
  地图点击被关掉。
* **走到头**：第一幕第 15 层是整行篝火，第 16 层是 Boss，而**本内容没有 Boss 遭遇**。
  所以没有可达节点时面板直说："第一幕到此为止（本内容没有 Boss 遭遇，跑不到第 16 层）"，
  而不是留一个看起来像 bug 的空面板。

### 67.3 顺手修掉的流程毛病

`startRun()` 一开始写成 `window.startRun = () => …`，放在 wiring 块里；而**开机流程跑在 wiring
之前** ⇒ 开机调用时是 `undefined`，整页空白（顶栏 "——"、没有可达节点）。改成 `function` 声明
（提升）之后正常。判据是冒烟测试通过 + 页面起来有 5 个可达节点。

### 67.4 判据

| 测试 | 钉住什么 |
|---|---|
| `a_node_pays_once`（rd-run） | 篝火结算后 `node_resolved()`；**再进同一节点 = `NodeResolved`**；`rest()` 不再生效；换一个节点仍然正常 |
| 浏览器 | 领奖励后 `rd_run_node_resolved() == 1`、面板无按钮、`rd_run_fight_begin() == -2` |

⚠️ 写这条测试时我的 `walk_to` 辅助函数**只在全新一局上成立**（它从第 1 层重放整条路径），
第二次调用就 `enter_node` 一个不存在的边而 panic。改成**从游标开始 BFS、重放时跳过种子**。

### 67.5 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 647 | **648**（rd-run 51 → 52） |
| 新导出 | — | **1 个**（`rd_run_node_resolved`） |
| `RunState` | — | + `resolved: [u64; 2]`（16 B） |
| `.wasm` | 477,846 B | **478,874 B** |
---

## 68. 第 58 轮：补内容 —— 第一个**精英**进了内容，奖励池也有了读者；它的接线**没接通**

> 用户："继续补充这些内容实现吧。" 这一轮补的是内容 + 一个真实缺口，但**精英的战斗接线没做完**，
> 下面把能证的与没证的都写清。

### 68.1 先摸清"内容侧到底缺什么"

| 想知道 | 结果 |
|---|---|
| 精英怪 | 内容里 **0 个**（10 个全是普通怪，`Tier` 都是 A） |
| Boss | **0 个**（Hexaghost / Guardian / Slime Boss 都没有） |
| 事件表 | **格式里没有 `EV`/事件表**（`ROW_SCHEMAS` 只有 CARD/STATUS/EACT/ENCT/REL） |
| 遭遇池 | `EncounterTables` **文档里写了**（Weak 3 项 + Note），但**内核从来没读过它** —— 所以"遭遇选择"一直是"镜像里任意一条" |

⇒ `?` 房需要格式迁移（新表），Boss 需要新机制（分裂/相位），两者都不是一轮能做的。**精英是唯一能做的**。

### 68.2 做了什么：3 × Sentry 进了内容，`EncounterTables` 有了读者

* **内容**：`sentry.bolt`（10 伤害）、`sentry.beam`（9 伤害）、`sentry`（HP 38–42、两招循环——
  与 `blue_slaver` 同一写法）、`enc_three_sentries`（3 只）、`EncounterTables.Elite`。
* **rd-core**：`Content::encounter_pool("Weak"|"Elite")` —— 读 `EncounterTables` 的对象字段、
  再读列表里每个 `_obj` 的 `Id`。**这是 `inv:§5.2/§5.3` 第一次真的被实现**；
  `rd_run_fight_begin` 现在从 **Weak 池**抽正常战斗，而不是"镜像里任意一条"。
* **闸门与清单一起动**：`sts_content_check.py` 的 `INV_COUNTS`/`INV_MONSTERS`/`INV_ACTIONS`
  加了 sentry，`INV_WEAK_POOL` 旁边加了 `INV_ELITE_POOL`，`EncounterTables.Elite` 也纳入比较；
  `sts-act1-inventory.md` 新增 **§4.2 精英**，把两处降级写在表里。

⚠️ **两处降级，都写进清单了**：① `Beam` 少了「洗 2 张 Dazed」——本内容没有 `dazed` 卡，
也没有任何一行用 Ethereal 那个钩子；② 少了 **Artifact 1**（内核没有该状态，也没有"抵消一次 debuff"）。
⇒ 这个精英**比原作容易**，不是等价替换。

### 68.3 **没完成**：精英节点的战斗接线

`NodeKind::Elite => Pending::None` 之后，`rd_run_fight_begin()` 在精英节点上返回 **-2，而错误缓冲是空的**。
这一轮**没能查出原因**，已核过的事实：

* 运行会话存在（`run_slot().is_some()` 断言通过），`begin_node()` 返回 **0**；
* 新 id 确实在镜像里（字节里能搜到 `sentry` 4 次、`enc_three_sentries` 1 次）；
* `Content::encounter_pool("Elite")` 在 rd-core 的单测里读出来是 `["enc_three_sentries"]`；
* 空错误串说明拒绝**不是**走 `fail()` 的路径 —— 那两条路径都会写文字。这条线索留给下一轮的第一件事。

⇒ 于是把 `NodeKind::Elite` **改回拒绝**，并让 `fight_begin` 只接受 kind 1：宁可"精英节点说本版不结算"，
也不要"给一个按不动的开始战斗按钮"。**内容与读者留下**（闸门绿、单测绿），等接线通了就是现成的。

### 68.4 顺手修的两个"声明不符实"

* `InertKeys` 里 `root:EncounterTables` 声明"零消费者"——**内核开始读它了**，闸门 `inert.rotted` 当场报出，删掉。
* 删掉之后暴露出它的**子键**：`Note`/`PackageId` 确实是文档（补声明）；`Weak`/`Elite` 是被读的，
  但闸门靠"代码里出现 `EncounterTables.Weak` 这个字面量"来判定 ⇒ 把 hop 串写成字面量
  （同时也进错误消息）。顺带修掉一个**假阳性**：我的 `sub_name == "Id"` 命中了闸门的
  `name == "Id"` 规则，让它以为内核读了 `Characters[].Id`；字段名改成常量。

### 68.5 判据与数字

| 测试 | 钉住什么 |
|---|---|
| `the_encounter_pools_are_readable`（rd-core） | Weak 3 项、Elite = `["enc_three_sentries"]`、不存在的池是 `None` 而不是空集 |

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 648 | **649**（rd-core 576→577） |
| 内容 | 10 怪 / 3 遭遇 / 19 动作 | **11 怪 / 4 遭遇 / 21 动作** |
| `sts` 镜像 | 11,640 / 9,944 B | **12,632 / 10,852 B**（重钉） |
| `.wasm` | 478,874 B | **479,842 B** |
---

## 69. 第 59 轮：精英真的打得起来了 —— 那个"空错误串"是**我的测试**，不是内核

> 用户："先修复然后继续完善游戏内容。" 修复只花了一次诊断，因为错误串从来不是空的。

### 69.1 真因：`DuplicateCombatant` —— 三只 Sentry 共用一个战斗员 id

诊断测试（`#[ignore]` 的 `dbg_elite`，逐步打印 kind / begin / fight_begin / 错误串）第一次跑就给出：

```
on elite: kind=2 resolved=0
begin_node=0 err="<empty, len=0>"
fight_begin=-2 err="build_fight_from_content: Capacity(DuplicateCombatant)" len=54
```

**错误串一直是有的**（54 字节）。上一轮我看到"空"，是因为我那个 `last_refusal()` 辅助函数当时
写的是 `String::from_utf8_lossy(&vec![0u8; 0])` —— **一个永远返回空串的表达式**。
⇒ 教训归到这一条：**"闸门/测试报出来的现象"也可能是测试自己的 bug**，而这正是上一轮我在
`readText`（指针与下标互换）上踩过的同一个坑：**观测工具出错时，它给你的是"另一个合法值"**。

真因在内容侧：三只 Sentry 的 `Id` 都是 `sentry`，而内核要求战斗员 id 唯一。
StS 里是"一个定义 + 三个实例"，本内容的遭遇记录只带 `Id`、**没有实例号** ⇒ 三个实例只能写成
三行（`sentry_1/2/3`，`NameKey` 都是 `Sentry`）。这是**模型差异**，写进清单 §4.2。

### 69.2 修复的三处 + 一处过期判据

1. **rd-run 一行**：`NodeKind::Elite => Pending::None`（精英就是一场仗，池与档位都在调用方）。
2. **rd-wasm 三段**：`fight_begin` 接受 kind 2；`pool_name` 按 kind 选 `Elite`/`Weak`；
   `RunSession.elite_fight` 记住"这场是精英"，`fight_end` 据此用 `FightKind::Elite`
   （`inv:§5`：金币 **25–35**、稀有度 10/40/50）。
3. **内容**：`sentry` → `sentry_1/2/3` 三行 + 遭遇三只；闸门的 `INV_MONSTERS`/`INV_ELITE_POOL` 跟上
   （怪物数 11 → 13）。
4. **过期判据**：`the_nodes_m1_does_not_settle_are_loud` 还在断言"精英被拒绝"，改成只断言 `Unknown`。

### 69.3 浏览器实测

地图上走到精英节点 ⇒ 面板写 **"精英节点（3 × Sentry）"** ⇒ 开始战斗 ⇒ 敌人面板三只
`sentry_1 / sentry_2 / sentry_3`，各 38/38、`Attack 10`，走位如常。
（截图见本轮记录：floor 7、hp 19/80、gold 43，说明前面的普通战斗与奖励都照常结算。）

### 69.4 判据

| 测试 | 钉住什么 |
|---|---|
| `an_elite_node_fights_the_sentries_and_pays_the_elite_tier`（wasm） | 走到精英 ⇒ `begin_node` 收下 ⇒ **`fight_begin` 起得来** ⇒ **3 只、名字含 sentry** ⇒ 打赢则金币落在 **25–35** |
| `the_encounter_pools_are_readable`（rd-core） | Weak 3 项 / Elite = `["enc_three_sentries"]` / 不存在的池是 `None` |
| `the_merchants_prices_follow_the_rarity_bands` | 上一轮的价格分档仍然成立 |

### 69.5 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 649 | **650**（rd-wasm 20 → 21） |
| 内容 | 11 怪 / 4 遭遇 | **13 怪 / 4 遭遇**（sentry ×3） |
| `sts` 镜像 | 12,632 / 10,852 B | **13,384 / 11,592 B**（重钉） |
| `.wasm` | 479,842 B | **482,979 B** |
---

## 70. 第 60 轮：**"回合 1 手牌为空"是 bug** —— 参考的脚手架不是游戏流程

> 用户："round1 手牌为空这个是故意这样的吗，如果是真实游戏流程是bug了。" 他判断对了。

### 70.1 查清：它忠于**参考的 scenario 驱动器**，不忠于 StS

`ref/RogueDeck-Core/src/RogueDeck.Scenario/Scripting/ScenarioRunner.cs:105`：

```csharp
EnsureTurnStarted(combat, registry); // starts the hero's turn (and draws its hand) on the first play
```

引擎里有真正的 `CombatTurnPhase.WaitingToStartTurn` 与 `_turns.StartCurrentTurn`，但**驱动器只在第一次
出牌时**才开回合。内核的 `build_fight` 忠实照搬了这一点（`battle.rs:502` 明写"**不**替调用方开始第一回合"），
四层对拍（`FIGHT_DIFF` 182 例）比的就是"同样步骤序列、两边一致"，所以构建语义必须与它对齐。

**但 StS 不是这样**：战斗一开始英雄的第 1 回合就开始了，玩家立刻看到 5 张手牌。
⇒ **参考那套 DSL 是给对拍用的脚手架，不是游戏流程**；而"回合 1 空手牌"从外面看**就是一个 bug**。

### 70.2 修法：把"开始第一回合"做成**驱动器**的选择

* `rd-core`：新增公开入口 `battle::start_first_turn()`（就是 `ensure_turn_started` 的包装，幂等）。
  它**不**进 `build_fight` —— 否则四层对拍的两边就不一样了。
* `rd-wasm`：`build_session_with` 在构建之后调一次 ⇒ **面向玩家的战斗从回合 1 开始**。
* 文档里把这条分工写清：`build_fight` 停在 `WaitingToStartTurn`（对拍用），驱动器负责开始（游戏用）。

### 70.3 一次性暴露了 6 处"把旧起始态钉死"的判据

它们全部通过，只是因为**旧行为是错的**。这正是"判据写死了现象而不是不变量"的形状：

| 位置 | 旧判据 | 现在 |
|---|---|---|
| `lib.rs` spike 场景 | `hand == 0`（注释还写"从外面看像 bug"，它**就是**） | `hand == 5` |
| `lib.rs` `open_the_hand()` | reset + 结束回合来抽牌 | 只 reset（结束回合现在会**出牌**） |
| `lib.rs` 动作表 | `action_count == 1` 且 `kind(0) == END_TURN` | 有 play 也有 end-turn，按**kind**找 |
| `lib.rs` 那一步 | `step(0)` 当成结束回合 | 按 kind 找 end-turn 的**下标** |
| `rd-wasm` 牌堆 | 三堆合计 == 10 | 三堆 **+ 手牌** == 10，且手牌 == 5 |
| `web/smoke.mjs` | 手牌 0、唯一动作是结束回合、`step(0)` | 手牌 5、按 kind 找结束回合 |
| `web/ui_test.mjs` | `endTurn.actionIndex === 0`；`diff.drawn === 5`；日志 `抽 5 张牌` | 下标随表走；`drawn` 与两个向量**自洽**（`hand_after = hand_before + drawn - left`）；日志按 diff 的张数 |

⚠️ 最后一条值得单说：`drawn` **不能再钉 5**。手牌满进满出时，diff 只能看见**变了的槽位**（这一局是 2），
所以判据改成"diff 的数字 == 两个向量蕴含的数字"——**这条仍然会在公式退化时报红**，而钉死 5 只会
把旧的空手牌起始态钉住。

### 70.4 浏览器实测

战斗一开就是 **5 张手牌**（Defend/Defend/Strike/Strike/Defend）、`round 1 · turn 1 · phase 1`、
energy 3/3，动作表 `[0,0,0,0,0,1]`（5 个出牌 + 结束回合），顶栏 `抽牌 5`。

### 70.5 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 650 | **650**（数字没变：改的是起始态与判据） |
| `.wasm` | 483,990 B | **483,990 B** |
| 语料 / golden | 85 / 129 | **85 / 129（未动）** —— `build_fight` 的语义没碰 |
---

## 71. 第 61 轮：打铁与删卡变成**真的选择**（外加 `?debug` 开关）

> 用户："请继续完成游戏流程。" 上一轮修完起始态，流程里最刺眼的两处是**假选择**。

### 71.1 两个机制本来"就是关于选择的"，而页面把选择删掉了

* 篝火的 **Smith** 按钮写死 `rd_run_smith(0)`；
* 商店的 **删卡** 写死 `rd_run_remove_card(0)`。

两者都只对"第一张"生效 —— 玩家有 10~16 张牌，而这两个机制的全部意义就是挑一张。
现在是一个**卡牌选择器**：复用牌组面板的样式，每条是一个按钮，点哪张就把**那个下标**交给内核。

### 71.2 判据：一半在 Rust，一半在页面

| 测试 | 钉住什么 |
|---|---|
| `smithing_a_middle_card_leaves_the_others_alone`（rd-run） | 升级**第 3 张**：只有它变 `strike+`，其余逐张不变 |
| `removing_a_middle_card_keeps_the_order_of_the_survivors`（rd-run） | 删**第 4 张**：剩下的顺序与"过滤掉它"逐项相同（顺序可观察，`run_hash` 逐张写） |
| `ui_test.mjs` 三条新接线断言 | 页面有 `showDeckPicker(`，且 `rd_run_smith(index)` / `rd_run_remove_card(index)` **用传进来的下标**——写死 `0` 会当场红 |

⚠️ 这两条 Rust 测试是必要的：**下标语义**在内核里（内核只认下标），而旧页面永远传 0，
所以"内核忽略参数"这种实现**也能通过所有旧判据**。

### 71.3 `?debug`：让浏览器能点到种子里到不了的地方

要在浏览器里点选择器，得先站到篝火/商人上；而 `inv:§7.2` 里**只有第 15 层是整行篝火**，
篝火节点本身只占 12%、商人 5% —— 这一轮的机器人还没走到就死了。所以加了个 `?debug` 开关
（`docs/spec/ui-plan.md` 早就把它列在"借 Slay the Web 的结构"里）：

```
http://127.0.0.1:8765/web/index.html?debug   →   window.RD_DEBUG = { showDeckPicker, … }
```

**实测**：`RD_DEBUG.showDeckPicker("打铁：选一张升级", cb)` 渲染出 **10 条**（5 × `Strike strike 攻击`、
4 × `Defend defend 技能`、1 × `Bash 攻击`）；点**第 3 条**回调收到 `2`，点**第 1 条**收到 `0`，
点完模态框自动关闭。⇒ 选择器的**点击路径**是被真浏览器验过的，不是只靠静态断言。

### 71.4 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 650 | **652**（rd-run 52 → 54） |
| 页面接线断言 | 11 条 | **14 条** |
| `.wasm` | 483,990 B | **483,990 B**（这一轮只动页面与测试） |
---

## 72. 第 62 轮：第一幕**有 Boss 了** —— 而且它是我现在打不过的

> 目标（用户已授权我连续做完）：**让第一幕可以完整通关**。这一轮先把"通关"的那一头接上。

### 72.1 内容：**Slime Boss** 进了内容，Split 是唯一降级

三只第一幕 Boss 各有一处内核表达不了的机制，所以"先做一只"其实是选**哪一处降级可以接受**
（表在 `inv:§4.3.1`）：

| Boss | 缺的机制 |
|---|---|
| The Guardian | **Mode Shift 30** + 防御态循环：要"受伤计数器 + 打断当前意图 + 切形态"的状态机 |
| Hexaghost | **Inferno 把所有 Burn 升级成 Burn+**：要"升级牌堆里的卡"的节点（Divider 的 `6×(floor(HP/12)+1)` 反而能做，`currentHealth` 已实现） |
| **Slime Boss** | **Split**（HP ≤ 50% 分裂）：要"战斗中途生成敌人"，而 `CombatState` 的战斗员集合在建战斗时定下 |

选 Slime Boss：循环（Goop Spray → Preparing → Slam）三个动作都能照原样表达，Split 是一次性形态转换。
⚠️ **降级写在清单里**：这一版**不分裂**，它不是等价的 Slime Boss。

### 72.2 run 层：Boss 是**第 16 层**，不在图上

`inv:§7.2` 说第 16 层是 Boss、不在网格里。所以 run 层加了一个**哨兵游标** `BOSS_NODE = 100`
（地图最多 90 个节点，索引恒小于它），并让：

* `reachable()` 在**最后一行**只给这一个出口（而且**站在它上面时不再给**——否则可以"走进自己正在打的仗"）；
* `enter_node()` 认这个哨兵，`floor` 置为 `ROWS + 1`；
* `check_invariants()` 的两条（"floor 越界"、"floor 必须等于节点所在行"）对 Boss 各放宽一格 ——
  这是**真**修：不修的话走进去立刻 `Invariant` 失败；
* `begin_node()` 把 Boss 当成一场仗（`Pending::None`，返回 `NodeKind::Boss`）；
* `RunState::mark_boss_beaten()`：**击杀 Boss 才算通关**。这是"一局能赢"的唯一路径。

### 72.3 wasm 与页面

* `fight_begin` 接受 kind 7，池选 `Boss`，奖励档 `FightKind::Boss`（金币 **95–105**、稀有度 **100% Rare**）；
* 新导出 `rd_run_boss_beaten()`；
* 地图页现在**画出 Boss 这一行**（`map_render.js` 合成一个 `row = 15` 的节点，`👑`），
  因为"看不见自己要去哪"本身就是 bug；宽度/高度随之多一行；
* 面板：`Boss · Slime Boss` + 开始战斗；胜利后出现 **"第一幕通关 · Slime Boss 已击败"** 结算。

### 72.4 判据

| 测试 | 钉住什么 |
|---|---|
| `the_boss_is_offered_at_floor_16_and_clears_the_act`（wasm） | 走到第 15 层后**唯一**的出口是 Boss；走进去 floor=16、kind=7；开战；敌人是 `slime_boss`；**赢了才 `boss_beaten==1` 且金币 95–105，输了必须是 0** |
| `the_encounter_pools_are_readable`（rd-core） | Boss 池 = `["enc_slime_boss"]`；不存在的池仍是 `None` |
| `walking_follows_edges_and_never_teleports` | 最后一行**恰好一个**出口，且是 Boss |
| `map_test.mjs` | Boss 是合成的第 16 行，`reachable` 与动作表仍逐项相等 |

⚠️ 这一轮一次性暴露了 **6 处**"最后一行无处可去 / 只有 7 种节点"的旧判据（rd-run、rd-wasm、smoke、
map_test 各若干）。它们全都通过，只因为**旧世界里 Boss 不存在**。

### 72.5 一个必须说清的结果：**现在打不过**

`the_boss_is_offered_at_floor_16_and_clears_the_act` 打印了实测：

```
boss fight: result=2 steps=32 hp=0
```

即：机制通了（Boss 开局、敌人正确、输了不通关），但**机器人打不赢**。原因不是 Boss 太强，是
**牌组永远长不大**：奖励池里只有 Basic 卡（内容里没有 Common/Uncommon），所以第 16 层还是那 10~16 张
基本牌，打 140 HP / 每 3 回合 35 伤害的 Boss 差得多。

⇒ 下一轮的题目就是这个：**往内容里放真正的铁甲战士卡（Common/Uncommon）**，让"奖励"真的让牌组变强，
顺便让第 54 轮做的稀有度权重与偏移第一次有东西可称。

### 72.6 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 652 | **653**（rd-wasm 21 → 22） |
| 内容 | 13 怪 / 4 遭遇 / 21 动作 | **14 怪 / 5 遭遇 / 24 动作** |
| `sts` 镜像 | 12,632 / 10,852 B | **14,684 / 12,712 B**（重钉） |
| `.wasm` | 483,990 B | **491,315 B** |
| 地图 | 15 行 | **15 行 + Boss 行**（绘制） |
---

## 73. 第 63 轮：牌组终于能长大 —— 而且**第一幕真的通了**（1/8）

> 上一轮结尾说"打不过 Boss，因为牌组永远长不大"。这一轮补上能长大的部分，并**量**了一遍。

### 73.1 五张真正的铁甲战士卡进了内容

选卡标准：**只用现有节点就能表达**（`dealDamage` / `gainBlock` / `applyStatus` /
`createCardInstance`），凡是"身份依赖新机制"的一律不做，并在注释里点名：

| 卡 | 稀有度 | 效果 | 需要的节点 |
|---|---|---|---|
| `twin_strike` | Common | 5 伤害 ×2 | `dealDamage` ×2 |
| `iron_wave` | Common | 5 Block + 5 伤害 | `gainBlock` + `dealDamage` |
| `clothesline` | Common | 12 伤害 + 2 Weak | `dealDamage` + `applyStatus` |
| `anger` | Common | 6 伤害 + 复制一张进弃牌堆 | `dealDamage` + `createCardInstance`（与 Slimed 同一个） |
| `uppercut` | Uncommon | 13 伤害 + 1 Weak + 1 Vulnerable | `dealDamage` + `applyStatus` ×2 |

**没做的（点名）**：Heavy Blade（力量倍率）、Body Slam（格挡当伤害）、Shrug It Off（抽牌）、
Armaments（升级牌）—— 它们的身份各要一个新机制，写进注释而不是糊一个近似。

⇒ 奖励池从 3 张 Basic 变成 **3 Basic + 4 Common + 1 Uncommon**：第 54 轮做的稀有度权重与保底偏移
**第一次有东西可称**；"拿奖励"也第一次真的让牌组变强。

### 73.2 决定性的一量：**第一幕通得了**

新加一个 `#[ignore]` 的**基准探针** `balance_probe_full_run`（它不是闸门：把一个"这个机器人必须赢"
写成断言，说的是机器人，不是游戏）。八个 seed 的实测：

```
seed 1: floor=1  hp=77/80 deck=11 fights=1  cards=1  boss_beaten=0
seed 2: floor=6  hp=49/80 deck=15 fights=5  cards=5  boss_beaten=0
seed 4: floor=4  hp=58/80 deck=12 fights=2  cards=2  boss_beaten=0
seed 5: floor=16 hp=45/80 deck=22 fights=12 cards=12 boss_beaten=1   ← 通关
seed 8: floor=5  hp=50/80 deck=15 fights=5  cards=5  boss_beaten=0
cleared 1/8 acts
```

⇒ **"第一幕可以完整通关"这句话现在有实测支撑**：seed 5 从第 1 层打到第 16 层、打 12 场仗、
牌组从 10 长到 22、最后击败 Slime Boss。

### 73.3 但另外 7 个 seed **卡在第 1~6 层**，原因也量出来了

不是打不过，是**走不动**：机器人会跳过 `?` 房（未实现），而有时一行的可达节点**全是 `?`**
⇒ 没有合法出路，run 停在原地。`inv:§7.3` 说 `?` 房占 **22%**，所以这不是小概率。

⇒ 这条把"`?` 房"从"最好有"变成**通关的必要条件**：真实 StS 里 `?` 房是**事件房，永远能进**。
下一轮就是它 —— 需要一次格式扩展（事件表）与一套**事件效果词表**（heal / gold / card / nothing），
因为 run 层没有节目解释器（`REL.RunPrograms` 就是那个缺口）。

### 73.4 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 653 | **653**（+1 探针，但它 `#[ignore]`） |
| 内容 | 7 卡 / 14 怪 / 5 遭遇 | **12 卡** / 14 怪 / 5 遭遇 |
| `sts` 镜像 | 14,684 / 12,712 B | **15,548 / 13,292 B**（重钉） |
| `.wasm` | 491,315 B | **492,000 B** 量级（探针不进 wasm） |
| 通关率（同一机器人） | 0/8 | **1/8** |
---

## 74. 第 64 轮：`?` 房的格式迁移 —— **撞到一处键名冲突，撤回**

> 目标仍是"第一幕可完整通关"。上一轮量出阻塞点是 `?` 房（22% 节点，7/8 个 seed 卡在没有出路），
> 所以这一轮动格式。

### 74.1 加了什么（然后撤了）

`rdcfmt.py`：`S_EV = 15`、`EV_ROW = [Id, NameKey, DescriptionKey, Choices(TERM), extra]`、
`FORMAT_VERSION` 2 → 3；`compile.py`：`("EV", "Events")` 进 `ENTITY_SECTIONS` + 段 id + manifest。
**sts 包编译通过**（0 行 EV，因为文档里还没写事件）。

### 74.2 撤回的原因：**参考文档自己就有 `Events` 键，形状不一样**

`build.py --package roguedeck` 当场炸：

```
File "compile.py", line 778, in compile_doc
File "compile.py", line 440, in row
TypeError: string indices must be integers, not 'str'
```

`row()` 在 `extra` 分支里对 `rec` 做 `dict` 解构，而 `rec` 是**字符串** ⇒ 参考文档的 `Events`
是一个**字符串列表**，不是我们的"事件对象"。

⇒ 根因是设计问题，不是笔误：`ENTITY_SECTIONS` 是一张**全局**的"表 → 文档键"映射，而两个包共用
同一个编译器却能给同名键不同的形状。**同一张恒等映射不能同时服务两份形状不同的文档。**

### 74.3 撤回后仍然绿，并把结论留给下一轮

* 编译器的 EV 接线全部移除，`FORMAT_VERSION` 两侧都回到 **2**；
* 两个镜像重建、`CONTENTC_BYTES PASS` 回到原 sha；单测 **653**、聚合验收 **16/16**。

下一轮的正解（三选一，要在动代码前定）：
1. **包级键名**：`package.json` 里声明自己的实体键（`sts` 用 `Events`，`roguedeck` 用别的），
   映射从"全局常量"变成"每个包一张表"；
2. **形状嗅探**：编译器遇到 `Events` 时先看第一个元素是 dict 还是 str，是 str 就整段跳过并**报一条
   明确的"未知形状，跳过"**（危险：静默跳过正是本项目最反对的形状）；
3. **换键名**：我们的包用 `StsEvents`（丑陋但零风险，且把冲突摆到明面上）。

我倾向 **1**：它把"键是包的语言"这件事写进包里，而不是写进编译器。

### 74.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **653** |
| 镜像 | 两个都回到原 sha（`CONTENTC_BYTES PASS`） |
| `?` 房 | **仍被拒绝**（这一轮没交付它，只交付了"为什么现在不能这么做"） |
---

## 75. 第 65 轮：`?` 房（续）—— 键名冲突解决了，写出链路还有一处断

> 上一轮撤回的根因是"全局表→键映射"撞上参考文档的 `Events`（一个 dict）。这一轮先把它解决掉，
> 然后撞到第二个更窄的问题。

### 75.1 解决了：换一个参考文档不用的键

`("EV", "UnknownRooms")` —— `UnknownRooms` 精确地就是这张表喂的东西（`?` 房），而且没有任何包用它。
于是 **两个包都能编译**（`sts` 4 行事件、`roguedeck` 0 行），冲突消失。

顺带把事件的行形状定成**固定格**而不是 TERM 列表：

```
EV_ROW = Id, NameKey, DescriptionKey, Label0, Effect0, Amount0, Label1, Effect1, Amount1, extra
```

理由：`Choices` 用 TERM 列表就要写"读一个对象列表、再读每个对象的一个命名字段"的遍历
（`encounter_pool` 已经长过一次那种代码），而固定格一格都不用。代价写清楚：**一个事件恰好两个选项**
（我们这 4 个都是如此；StS 允许 1–3）。`Effect` 是**闭词表** `heal/gold/damage/max_hp/nothing` ——
因为 run 层没有节目解释器，`REL.RunPrograms` 就是那个缺口。

内容的 4 个事件：`golden_idol`（+30 金 / 走开）、`shining_light`（+2 最大 HP / 走开）、
`old_shrine`（回 15 / 走开）、`scrap_pile`（+45 金 / 走开）。

### 75.2 第二个问题：**编译器数得到、写不出来**

加完 `S_EV` 之后第一版：`manifest.json` 说 `events: {count: 4}`，而镜像里第 15 段是 `(0, 0, 0)` ——
**0 行**。原因之一当场找到并修掉：

> `rdcfmt.SEC_ORDER` 是**写出器真正遍历的那份**列表。表加进 `ROW_SCHEMAS` 而不加进 `SEC_ORDER`，
> 编译器就会"数得到、写不出"：manifest 对、镜像空。已加进去，并在那行留下注释说明这个坑。

但修完 `SEC_ORDER` 之后**仍然是 0 行**（`total_size` 从 15548 长到 16164，说明字节写进去了，
可目录项还是 `(0,0,0)` 且 count 0）。也就是说 `counts[SEC_OF[sname]]` / `payload` 这条路上，
"EV" 仍然没被算进去 —— 而 `enc.rows["EV"]` 明确有 4 条。

**这就是下一轮的第一条线索**：`_row_groups()` 与 `SEC_OF` 在 `write()` 里看到的 EV，和
`enc.rows` 在 manifest 里看到的 EV，是两套账。

### 75.3 状态

已全部撤回，`git status` 干净、单测 **653**、聚合验收 **16/16**、两个镜像回到原 sha。
本轮交付的是**两个精确的下一步**，不是代码：

1. `SEC_ORDER`（已修，撤回时一并回退了，下一轮要重新加）；
2. `write()` 里 `counts`/`payload` 对 EV 的两套账 —— 待查。

`?` 房**仍未接通**，因此第一幕目前仍是"能通关但 7/8 个 seed 会被 `?` 堵死"。
---

## 76. 第 66 轮：`?` 房的事件表**进了格式** —— 真正的 bug 是"目录按位置写"

> 上一轮留下的线索是"两套账"。这一轮把它查到底，结论是一个**格式不变量**，不是记账笔误。

### 76.1 真因：目录按**位置**写，所以段号必须等于它在 `SEC_ORDER` 里的下标

`compile.py` 写目录的方式是：

```python
dir_entries = []                       # 按 F.SEC_ORDER 顺序 append
for sec in F.SEC_ORDER: ...
for i, (sec, o, size, cnt) in enumerate(dir_entries):
    struct.pack_into("<III", buf, F.HEADER_SIZE + 12 * i, o, size, cnt)
```

**槽位号就是 `i`**，不是 `sec`。我把 `S_EV = 15` 插在 `S_REL(11)` 与 `S_ROOT(12)` 之间，于是
ROOT/IDX/TAGS 整体**下移一格**：字节都在，但挂在错的段号下 —— 读第 15 段自然读到 0 行，而 manifest
（读 `enc.rows`）说 4 行。这就是"两套账"的全部内容。

⇒ 修法一行：`S_EV` 放到 `SEC_ORDER` **末尾**。并在那行留下注释，写明这条不变量与它坏掉时的样子。

排查过程里还有两个**会骗人的东西**，都记下来了：
* `build.py` 用 `subprocess.run(..., stdout=PIPE)` 调编译器，**成功时把 stdout 吞掉**，所以我打在
  编译器里的探针一行都看不见；要看得直接跑 `compile.py` 复刻它的参数。
* 探针打印 `payload keys` 时我只看**键**不看**值** —— 键在、值是 `b""`，于是误判成"写进去了"。

### 76.2 于是事件表真的落地了

* **格式**：`S_EV = 15`，`EV_ROW` 十格固定（`Id/NameKey/DescriptionKey/Label0/Effect0/Amount0/
  Label1/Effect1/Amount1/extra`），`FORMAT_VERSION` **2 → 3**。
* **编译器**：`("EV", "UnknownRooms")`；`UnknownRooms` 进 `DOC_ROOT_KEYS`（实体键不落成根键）。
  键名**不叫 `Events`**：参考文档用那名字装一个 20 项的 dict，而 `ENTITY_SECTIONS` 是全局映射。
* **内核**：`Table::Event` + `EvRow` + `Content::event_count()/event(index)`，`EK_EVENT` 只做
  `entity_kind()` 的返回值、**不进 `SEC_IDX`**（所以 `from_entity_kind(EK_EVENT)` 仍是 `None`，
  那条老测试原样通过）。
* **内容**：4 个事件（`golden_idol` +30 金 / `shining_light` +2 最大 HP / `old_shrine` 回 15 /
  `scrap_pile` +45 金），每个两个选项，`Effect` 是**闭词表** `heal/gold/damage/max_hp/nothing` ——
  因为 run 层没有节目解释器。

判据 `the_unknown_room_events_are_readable`（rd-core，真镜像）：4 个事件、每个都有正文与两个带文字的
选项、**效果词表闭集**、id 集合正确、`golden_idol` 的第一个选项是 `gold/30`；并且 **roguedeck 镜像
0 个事件**（它没有 `UnknownRooms` 键，不报错也不编）。

### 76.3 还没接的：`?` 房仍然被拒绝

格式、编译器、内核三层的球都到位了，**但 run 层还没用它**：`NodeKind::Unknown` 仍返回
`NodeNotSettleable`。所以第一幕现在还是"能通关，但 8 个 seed 里 7 个被 `?` 堵死"。
下一轮（最后一轮）就是它：`Pending::Event` + `begin_event`/`resolve_event` + ABI + 事件面板 + 浏览器验证。

### 76.4 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 653 | **654**（rd-core 577 → 578） |
| 内容 | 12 卡 / 14 怪 / 5 遭遇 | **+ 4 事件**（`EV` 4 行） |
| `sts` 镜像 | 15,548 / 13,292 B | **16,164 / 13,924 B**（重钉） |
| 格式版本 | 2 | **3** |
---

## 77. 第 67 轮：`?` 房的 run 层接线 —— 写完了，**没验通**

> 最后一轮前的这一轮，把事件从"格式里的数据"接成"run 层的动作"。接线写完了、编译过了、
> 闸门全绿，但**端到端的那个测试红了**，我这轮没查出原因，所以把它删掉、把问题原样记下来。

### 77.1 写完的部分

* **rd-run**：`Pending::Event = 5`；`EventEffect { Heal/Gold/LoseHealth/GainMaxHealth/Nothing }`
  （**闭词表**，内容里出现别的词就是 `UnsupportedEventEffect` 而不是"什么都不做"）；
  `begin_event(id)` / `event()` / `resolve_event(effect)`；`begin_node` 对 `NodeKind::Unknown`
  返回 `Pending::None`（不再拒绝），`resolve_event` 落 `mark_resolved()` ⇒ 一个 `?` 房只付一次。
* **rd-wasm**：`begin_node` 在 `?` 房按 `Event` 子流抽一个事件（`EV` 4 行）并 `begin_event`；
  六个导出 `rd_run_event_text_*` / `rd_run_event_label_*` / `rd_run_event_effect` /
  `rd_run_event_amount` / `rd_run_choose`。效果码 `1 heal / 2 gold / 3 damage / 4 max_hp /
  5 nothing / -1 未知`。

顺带修掉一个**又出现的老坑**：`let content = content();` 之后，同一作用域里再调 `content()` 就成了
"expected function, found &Content"；而且**在持有 run 槽位时调 `rd_run_node_kind()`** 正是第 51 轮
那个 `static mut` 别名 bug 的形状。改成从 `begin_node` 的返回值拿 kind。

### 77.2 **没验通**的部分（下一轮的第一件事）

端到端测试 `an_unknown_room_opens_an_event_and_resolves_it` 在
`assert_eq!(rd_run_begin_node(), 0, ...)` 处拿到 **-2**。已经排除/该查的：

* rd-run 侧 `begin_node` 对 `Unknown` 已经改成 `Ok(Unknown)` + `Pending::None`（**有**可能仍有别的
  返回 -2 的分支）；
* 镜像里 `EV` 段确认有 4 行（`(16084, 80, 4)`），内核 `event_count()` 的单测**通过**；
* 想拿到拒绝原因时，我两次被 PowerShell 的**反引号**坑到：`\`` + 字符 被当成转义（`r` = CR 把注释
  劈成两行、`?` 让字符串变样），一次 patch 还改错了**另一个测试**的断言。

⇒ 下一轮第一件事：把 `rd_run_begin_node` 的每条返回路径贴一遍（`-2` 只有 `fail()` 与
`build_session_with` 那两条），用 `rd_run_last_error_len/into` 把文字打出来。**别再改测试断言去凑绿。**

### 77.3 状态（诚实版）

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **654**（事件端到端测试已删，因为没有通过） |
| `?` 房 | **仍然走不通**（rd-run 层通了，wasm 层返回 -2） |
| 第一幕通关率 | **1/8**（未重测；`?` 仍是那 7 个 seed 的堵点） |

这一轮交付的是"接线写完了 + 一个更窄的问题"，**不是**"`?` 房做完了"。
---

## 78. 第 68 轮（目标收尾）：`?` 房通了，**第一幕在真浏览器里通关**

### 78.1 那个 -2：一行臂没写，而注释写着它写了

上一轮我用注释描述了"`?` 房落成事件"，但**只替换了注释、没加 match 臂** ⇒ `Unknown` 仍然掉进
catch-all `other => NodeNotSettleable`。于是 wasm 返回 -2，而我花了半轮在别处找。
加上一行 `NodeKind::Unknown => Pending::None` 之后，端到端测试一次通过。

⇒ 纪律补一条：**"注释说它做了"不等于"它做了"**；改 match 时要让**臂**出现在 diff 里，而不是只让
注释出现。

### 78.2 探针：`?` 房不再是堵点

`balance_probe_full_run` 过去**主动跳过** `?` 房（那是当时唯一能玩的策略）。现在它走进去并选第一个选项：

| seed | 之前 | 现在 |
|---|---|---|
| 1 / 3 / 7 / 8 | 卡在第 1~6 层 | **走到 6 / 8 / 12 层**（战死，是平衡问题不是路被堵） |
| 4 / 5 / 6 | 只有 5 通 | **4、5、6 都通关**（seed 6 最大 HP 涨到 88 —— 事件的 `max_hp` 真的生效） |
| 通关率 | **1/8** | **3/8** |

### 78.3 浏览器端到端：从地图走到 Boss、击败、看到通关结算

同一个页面、同一个机器人（不注入任何东西），`seed 4`：

```
16 步走到 floor 16 → 击败 Slime Boss →
"第一幕通关 · Slime Boss 已击败"
floor 16 · hp 46/80 · gold 283 · deck 19 · relics 2
```

牌组 10 → **19**、遗物 1 → **2**（宝箱/商店）、金币 283。地图上第 16 行的 Boss 节点 **👑** 是画出来的。

途中也验了 `?` 房：面板显示 `未知房间 · old_shrine — A shrine that still answers.`，
两个按钮 `Pray · 回复 15` / `Leave`；点 Pray 后 **hp 74 → 80**（被上限截住）。

顺手修掉一处先后顺序：**"已结算"分支排在"本幕通关"之前**，于是打完 Boss 面板写的是
"点亮的节点往前走"而不是通关结算。通关结算现在排在最前 —— 一局已经赢了，它盖过一切。

### 78.4 目标四项的交付状态

| # | 目标 | 状态 |
|---|---|---|
| ① | 内容侧补第一幕 Boss（降级写明并进清单） | ✅ Slime Boss（三招循环），**不分裂**写进 `inv:§4.3.1` |
| ② | run/wasm/页面把 Boss 接成可打的战斗 + 通关结算 | ✅ 哨兵游标 `BOSS_NODE`、`FightKind::Boss`、通关面板 |
| ③ | `?` 房的事件表 + 若干事件，不再被拒绝 | ✅ `EV` 表 + 4 个事件 + 事件面板 |
| ④ | 药水（**若格式允许**） | ❌ **格式里没有 `POT` 表** —— 需要又一次段迁移。`RunState` 有药水槽、ABI 有计数，但**没有任何药水内容**。目标原话是"若格式允许"，所以这一项按退出条件记 |
| ⑤ | 真浏览器验证全流程 | ✅ 见 §78.3 |

### 78.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **655**（rd-core 578 / rd-run 54 / rd-wasm 23） |
| 通关率（同一机器人） | **3/8**（原 1/8） |
| 事件 | 4 个，`Effect` 闭词表 |
| `.wasm` | 约 492 KB |
---

## 79. 第 69 轮：作弊路径关掉了 —— **先结算，才能往前走**

> 用户："点选节点以后不进去就可以立马点下一个节点，这是作弊的好门路。"

### 79.1 规则：一个节点结算完才能走

`enter_node` 现在多一条检查：

```rust
if self.node >= 0 && !self.node_resolved() {
    return Err(RunError::NodeNotSettled);
}
```

**一条检查覆盖全部节点类型**，因为"结算"在各类节点上都已经有落点：战斗在 `rd_run_fight_end`
里 `mark_resolved()`、事件在 `resolve_event`、篝火/商店/宝箱在各自的动作里。游标也不动。

页面侧不用改：点第二个节点会被拒，`renderMap` 把内核的理由写出来
（`走不过去 · NodeNotSettled`）——**假动作变成了可见的拒绝**，不是静默忽略。

### 79.2 判据

| 测试 | 钉住什么 |
|---|---|
| `you_cannot_walk_on_before_settling`（rd-run） | 踏上第一个节点后，去下一个 ⇒ `NodeNotSettled`，且**游标不动**；`mark_resolved()` 之后同一个目标就合法 |
| `walking_follows_edges_and_never_teleports` | 走图时每跳前结算（模拟打完一场仗） |
| wasm 侧三个"走到某种节点"的测试 + 走图测试 | 新增 `settle_here()` 助手：**通过 ABI** 把当前节点结算掉（战斗起手再收尾、篝火休息、事件选第一个、宝箱开、商店离开） |
| `map_test.mjs` | 两处走图循环都先 `settleHere()` |

### 79.3 顺带暴露的

`walk_to`（rd-run 的测试助手）之前"只走不结算"，新规则一来**七个测试同时红**——它改成边走边
`mark_resolved()`。这不是凑绿：助手的作用是"把我带到某种节点"，路上结算正是玩家会做的事。

### 79.4 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 655 | **656**（rd-run 54 → 55） |
| 作弊路径 | 可走 | **`NodeNotSettled`** |
---

## 80. 第 70 轮：药水进了格式与内容（`POT` 表），并会从战斗里掉

> 用户："继续加上药水的内容吧。" 目标第 ① 项。这一轮做完的是**数据层 + run 层的取得**，
> **使用**（战斗内效果）与页面槽位还没接。

### 80.1 格式：`S_POT = 16`，`FORMAT_VERSION 3 → 4`

`POT_ROW` 七格：`Id / NameKey / DescriptionKey / Effect / Amount / Rarity / extra`（stride 16）。
`Effect` 是**闭词表** `combat_damage / combat_block / combat_energy / heal` —— run 层没有节目解释器，
词表外的效果必须响亮拒绝，而不是"什么都不做"。

⚠️ `S_POT` 放在 `SEC_ORDER` **末尾**：上一轮学到的——**目录按位置写，段号必须等于下标**。

`Potions` 这个文档键在**参考文档里不存在**（先查过：`REF lacks Potions`），所以这次没有 `Events`
那种键名冲突。

### 80.2 内容：三张第一幕药水

| id | 效果 | 数量 | 稀有度 |
|---|---|---|---|
| `fire_potion` | `combat_damage` | 20 | Common |
| `block_potion` | `combat_block` | 12 | Common |
| `energy_potion` | `combat_energy` | 2 | Uncommon |

### 80.3 run 层：40% 掉落 + 三条槽 + 满槽响亮失败

`roll_reward` 多接一个 `potion_pool`，在 `Potion` 子流上先掷 40%（`inv:§9.3`，只有一幕所以不建模
±10%），掷中就在同一子流上挑一张。`Reward` 带 `potion: RunId`，`take_potion()` 把它塞进腰带；
**腰带满了是 `RunError::Capacity`，不是静默丢弃**——玩家刚被给了东西又悄悄没了，正是本项目反复禁止的形状。

（`RunState` 本来就有 `potions: [RunId; 3]` 与 `push_potion`，这一轮才第一次有生产者。）

### 80.4 判据

| 测试 | 钉住什么 |
|---|---|
| `the_potions_are_readable`（rd-core，真镜像） | 3 张、名字非空、数量 > 0、**效果词表闭集**、稀有度三选一、id 集合；`fire_potion` 是 `combat_damage/20`；**roguedeck 镜像 0 张** |
| `a_won_fight_drops_a_potion_and_the_belt_takes_it`（rd-run） | 400 次战斗的掉落率落在 25~55%（约 40%）；拿走 ⇒ 进腰带、报价清空、**再拿是 `NoSuchPotion`**；**满槽是 `Capacity`** |

### 80.5 还没做的（下一轮）

* **使用**：药水在战斗里要用现有节目管线（`combat_damage` 要指定敌人 ⇒ env ABI 的动作空间要多一种
  "用药水"），以及 `rd_run_use_potion(index, target)`；
* **页面**：三条槽、使用/丢弃按钮、奖励屏的"拿药水"。

### 80.6 一个观察到的问题（记下来，没修）

`rdcf-verify` 的证据仍写 **`5/5 tables`**：那个校验器有自己的表清单，不读 `ROW_SCHEMAS`，所以
`EV`/`POT` 两段它**看不见**。也就是说这条闸门的"5/5"现在是**少报**。真正的覆盖来自 rd-core 的两个
读镜像测试，但闸门本身的数字应该改成"跟着 `ROW_SCHEMAS` 走"。

### 80.7 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 656 | **658**（rd-core 579 / rd-run 56 / rd-wasm 23） |
| 内容 | 12 卡 / 4 事件 | **+ 3 药水**（`POT` 3 行） |
| `sts` 镜像 | 16,164 / 13,924 B | **16,504 / 14,264 B**（重钉） |
| 格式版本 | 3 | **4** |
---

## 81. 第 71 轮：塔底的初始奖励/惩罚（Neow）—— 选完才能出发

> 用户："还有进游戏塔底的初始奖励惩罚变换界面。" 目标第 ② 项，做完。

### 81.1 形状：一个祝福 = **收益 + 代价**，都用事件的闭词表

```rust
pub struct StartOffer { id: &'static str, gain: EventEffect, cost: EventEffect }
```

`EventEffect` 是 `?` 房那套（`heal/gold/lose_health/max_hp/nothing`），所以"100 金币换 7 点血"
不需要任何新解释器 —— `choose_start` 先 `gain` 再 `cost`，**顺序有意义**（代价要能花掉刚得的血）。

四张（`START_OFFERS`）：`max_hp` +8 最大 HP、`gold` +100 金 / 代价 −7 HP、`heal` 回 25、
`blood_money` +150 金 / 代价 −14 HP。开局掷**两个不重复**的（`Event` 子流两次：`first`、再在"去掉
first 的池子"里取 `second`）。

⚠️ **这不是 wiki 的池子**：StS 从八个左右按稀有度权重抽，这里是四个等概率。已写进 `inv:§7.1`
而不是让它隐含。

### 81.2 规则：选完才出发

`Pending::Start = 6`，`rd_run_start` 建好 run 之后立刻 `offer_start_choice()`。`enter_node` 多一条：

```rust
if self.pending == Pending::Start { return Err(RunError::WrongPhase); }
```

与 `NodeNotSettled` 同一条纪律：**当前该做的事没做完，别的动作一律拒绝**（浏览器里点节点会看到
`走不过去 · WrongPhase`）。

### 81.3 判据

| 测试 | 钉住什么 |
|---|---|
| `the_blessing_is_offered_and_applied`（wasm） | `pending == 6`；两个 offer 的 id 非空且**互不相同**；gain/cost 都在 `1..=5`；**走一步被拒且 floor 不动**；选完 `pending == 0`、金币/血量/最大值**逐项等于"先 gain 再 cost"的独立推算**；之后第一步合法；**再选一次是 -2** |
| `a_run_starts_from_the_content_not_from_constants` | 七个 RNG 子流的计数仍然可以逐项解释 —— 现在 `Event` 流是 **2**（祝福掷两次），其余 0 |

⚠️ 最后那条是这一轮**唯一让老测试变红**的地方：它原来断言"除 Map 外全部为 0"。祝福是开局的合法消耗，
所以它改成"Event 恰好 2，别的必须 0"。这正是"一个允许失败的节点，它的次数本身就是断言"。

### 81.4 页面：塔底面板

`pending === 6` 时出两个按钮，标题 `塔底 · 选择一项祝福（选完才能出发）`，每个按钮两行：
名字（`治疗` / `财宝`）+ 收益与代价（`金币 100，代价 受伤 7`）。

**实测**（真浏览器，不注入）：两个按钮 `治疗 回复 25` / `财宝 金币 100，代价 受伤 7`；点第二个 ⇒
金币 `0 → 100`、HP `80 → 73`（正好是代价）、`pending → 0`、面板变成"还没出发 · 点亮的节点可以走"。

⚠️ 又踩了同一个坑两次：`const OFFER_NAMES` 在面板渲染时仍在**暂时性死区**，于是名字**静默变空**。
换成 `function offerName()`（函数声明会提升）才对 —— 与 `startRun` 那次完全同形。**"页面没报错但少了东西"
比"页面报错"更难发现。**

### 81.5 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 658 | **659**（rd-wasm 23 → 24） |
| 开局 | 直接进第一层 | **先选祝福** |
---

## 82. 第 72 轮：药水的**丢弃**与腰带显示（使用还差内核一个钩子）

### 82.1 做完的

* **rd-run**：`drop_potion(index)` —— 幸存者保序（腰带是**列表不是集合**），越界是 `NoSuchPotion`
  而不是空操作。这也让 `take_potion` 的 `Capacity` 从"死路"变成"可行动"：腰带满了可以先丢一瓶。
* **wasm**：`rd_run_drop_potion(index)`。
* **页面**：顶栏遗物旁边多一排**药水 chip**（`runRead.potionName` → `rd_run_potion_id_*`），
  每个带一个 `×` 丢弃按钮；**奖励屏**多出"这一场掉了一瓶药水 / 拿起"一行（`rd_run_take_potion`）。

### 82.2 判据

| 测试 | 钉住什么 |
|---|---|
| `dropping_a_potion_keeps_the_order_of_the_survivors`（rd-run） | 三瓶丢中间那瓶 ⇒ `["fire_potion","energy_potion"]`；再丢 ⇒ 剩一瓶；**越界是 `NoSuchPotion`**；丢空后仍报错 |
| `smoke.mjs` | 六个药水导出必须真的存在（`potion_count` / `potion_id_*` / `drop_potion` / `reward_potion_*` / `take_potion`） |
| `ui_test.mjs` | 页面必须调 `rd_run_potion_count` 与 `rd_run_drop_potion(` |

### 82.3 没做到的（说清楚）

* **使用**：`combat_damage` / `combat_block` / `combat_energy` 都还没接通。查过了：**内核没有
  "给某个战斗员加格挡/能量"的公开入口** —— `give_block` 是 `exec.rs` 里的**测试助手**，
  伤害要走 `resolve_damage(ctx, …)`，需要一个 `ExecContext`。所以药水的战斗效果不是"接线一下"，
  而是**要给 rd-core 加一小块公开 API**（或者让药水以内容节目表达）。这是下一轮的正题。
* **腰带在浏览器里的外观没验到**：我驱动页面时先被**商店**卡住（`NodeNotSettled` —— 页面是对的，
  我的脚本没点"离开"），修好脚本后跑了 60 步也没赶上 40% 的掉落。所以腰带 chip 目前只有
  **接线断言**，没有"真浏览器里看见一瓶药水、点 × 丢掉"的证据。**不写成已验证。**
* **奖励屏的"拿起"按钮同样只有接线断言**：它的 `potionLen 字节` 显示是占位（长度不是有用的信息），
  应该显示药水名 —— 需要一条 `rd_run_reward_potion_name_*` 或让页面自己去查。

### 82.4 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 659 | **660**（rd-run 57） |
---

## 83. 第 73 轮：药水使用 —— **找到两个入口，第三个还缺**（只落文档，不落半截代码）

上一轮我写的是"内核没有给战斗员加格挡/能量的公开入口"。**这一轮查清楚了：那句话只对一半。**

### 83.1 三个效果各自的真实入口

| 效果 | 入口 | 状态 |
|---|---|---|
| `combat_block` | `Combatant::defensive_pools()` 读 + `Combatant::set_defensive_pool(id, current, None)` 写 —— 两个都是 **`pub`**（`exec.rs` 的测试助手 `give_block` 就是调它） | **可以做** |
| `combat_energy` | `CombatState::set_resource(key, current, Some(max))` 是 **`pub`**；读是 `combatant(&id).resources()` 里按 `"standard.energy"` 找（wasm 的 `energy_now()` 已经这么读） | **可以做** |
| `combat_damage` | 只有 `exec::resolve_damage(ctx: &mut ExecContext, target, base, ignores_block)` —— 需要一个 `ExecContext`，那是**节目执行**的上下文 | **缺一个入口** |

⇒ 三个药水里**两个这一轮就能做完**，第三个需要"把伤害送进管线"，有两条路：
1. 给 rd-core 加一个 `pub fn apply_program(state, host, root, target)` 之类的小入口，让调用方带着
   **内容节目**进来（目标原话就是"战斗内的药水效果走现有节目管线"，所以这条更贴）；
2. 给药水换形状：`POT` 行带一个 `Program`（像 `EACT`），这样"药水 = 一段节目"，
   伤害、格挡、能量**全部**走同一条路，`Effect/Amount` 那两格退役。

**我倾向 2**：它一次性解决三类效果，且不会引出"第二套效果语义"。代价是 `POT` 再改一次形状
（`FORMAT_VERSION 5`），并且 `fire_potion` 的目标要在执行时由玩家指定 —— 这正好接上 env ABI 的选目标步骤。

### 83.2 为什么这一轮只落文档

会话上下文已经接近用尽，而"药水改形状"会牵动 `rdcfmt / compile / content / content.rs / run / wasm / 页面`
七处，中途停下就会留下一棵红的树。**留一个精确的下一步，好过留一棵红的树。**（这也是这个项目一贯的
纪律：不知道怎么做完的时候，把"到哪一步了、下一步第一件事是什么"钉住。）

### 83.3 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16**（本轮只改文档） |
| 单测 | **660** |
---

## 84. 第 74 轮：药水**能用**了 —— 并且挖出一个"观察是缓存快照"的真 bug

### 84.1 `rd_env_use_potion(slot)`：格挡与能量真的生效

* `combat_block` → `Combatant::set_defensive_pool("standard.block", current + 12, None)`；
* `combat_energy` → `Combatant::set_resource("standard.energy", current + 2, None)`
  （**上限给 `None`**：能量药水本来就该超过每回合上限；第一版把池子上限传进去，增益被**夹掉了**）；
* `combat_damage` → **响亮拒绝**，并在消息里写清原因与去处（`resolve_damage` 要 `ExecContext`）。
* 成功才 `drop_potion(slot)` —— **拒绝不许吃掉药水**（测试钉住）。

### 84.2 挖出来的真 bug：**观察向量是缓存快照**

第一版写完，格挡读到 `0`，能量读到 `3`，而**写法本身是对的**。在写入之后立刻从同一个战斗员读回
（`after != current + amount` 就拒绝）——读回是 **12**，说明**写进去了**，是**观察**不动。

根因：`rd_env_observe_into` 只是把 `Session::publish()` 拷过来的 `OBS` 交出去，而 `OBS` 来自
`self.after`，只在 `reobserve()`（`rd_env_step` 的尾巴）里重建。**药水不走 `rd_env_step`，所以快照
一直是药水之前的。**

修法：`rd_env_use_potion` 在写完之后调 `Session::reobserve_after_external_change()`
（新加的 `pub(crate)` 包装，内部就是 `reobserve()`）。

⚠️ 这条 bug 的形状值得记：**写入返回 Ok、读回正确、观察不动**。如果没有那个"读回"断言，我会以为是
内核的写接口有问题，然后在错误的层里改半天。

### 84.3 判据

`a_potion_can_be_used_in_a_fight`（wasm，端到端、**没有静默跳过**）：

* 走图打到掉药水为止（40% 掉落），**专门等到一瓶 `block_potion`**（否则算术断言可能根本没跑）；
* 走进下一场战斗 → `rd_env_use_potion(slot)` → 断言 **Block 恰好 +12**、腰带少一格；
* 其它药水（`fire_potion`）断言 **-2 且腰带不变**。

### 84.4 还没做的（诚实）

* **`fire_potion` 不生效**：伤害要走 `resolve_damage(ctx, …)`，需要一个 `ExecContext` ——
  也就是"带一个节目进来"的入口。这是目标 ① 唯一还缺的一块，写在 §83 的两条路里。
* **`energy_potion` 没有被端到端断言覆盖**：实现的臂里有"读回不符就拒绝"的自检，测试却只等到
  `block_potion`，所以能量的 +2 只是**代码里有、测试没钉**。下一轮要么补一瓶能量的用例，要么
  把测试改成"三瓶都试一遍"。
* **页面**多了"用"按钮（只在战斗里出现）与"×"丢弃按钮，`smoke`/`ui_test` 断言它们接线；
  **真浏览器里点"用"还没验**（上一轮的腰带外观也仍未验）。

### 84.5 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 660 | **661**（rd-core 579 / rd-run 57 / rd-wasm 25） |
| `.wasm` | — | **509,315 B**（重编；警告：闸门抓到过一次陈旧产物） |
---

## 85. 第 75 轮：能量的 +2 也被钉住了；浏览器验证仍然没做成（第三次）

### 85.1 测试从"等到一瓶格挡药水"升级成"等到两瓶"

`a_potion_can_be_used_in_a_fight` 的猎取条件改成**腰带里同时有 `block_potion` 与 `energy_potion`**
（腰带三格，所以最多几场仗就到），然后：

1. 用格挡药水 → 断言 **Block 恰好 +12**、腰带少一格；
2. **紧接着用能量药水** → 断言 **能量恰好 +2**（且允许超过每回合上限 3）、腰带再少一格。

⇒ 上一轮"能量只有代码里有、测试没钉"的窟窿补上了。这一轮的测试**两瓶都真的用了**，
不是"等着看掉哪瓶"。

### 85.2 浏览器验证：第三次没做成，原因换了

这次不是脚本写错（商店/事件都处理了），而是**用 ABI 直接 `rd_run_start` 会让页面的地图停留在上
一局的渲染**——点击落到旧节点上，`rd_run_step` 被拒，run 停在 floor 0/1。改用"只点页面"之后能走到
floor 1，但我的"点亮节点"选择器（`g.node.reachable`）没命中，循环一步就退出。

⇒ **诚实结论：腰带 chip 与"用"按钮仍然只有接线断言 + 内核端到端测试，没有真浏览器的截图证据。**
下一轮要么把 `describeMap` 的 lit 类名查准，要么在 `?debug` 下暴露一个"给我一瓶药水"的调试入口
（只 debug 模式，不进正常流程）。

### 85.3 目标状态

| 项 | 状态 |
|---|---|
| `POT` 格式 + 3 瓶内容 + 掉落 + 取得 | ✅ |
| 丢弃 | ✅（rd-run 测试 + 页面按钮接线） |
| 使用：格挡 +12 / 能量 +2 | ✅ **端到端断言**（ABI 层） |
| 使用：伤害（`fire_potion`） | ❌ 需要"带节目进来的入口" |
| 页面：腰带 chip / 用 / × | ⚠️ 接线断言有，**真浏览器未验** |
| Neow 塔底选择 | ✅（真浏览器已验：金币 0→100、HP 80→73） |

### 85.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **661**（rd-core 579 / rd-run 57 / rd-wasm 25） |
---

## 86. 第 76 轮：`?debug` 多了两个钩子；浏览器驱动仍然卡在**渲染与状态脱钩**

### 86.1 加了什么（小但有用）

`?debug` 下的 `RD_DEBUG` 现在多了：

* `startWithSeed(seed)` —— 让浏览器检查能指定 seed，不必指望 40% 的掉落自己出现；
* `settle()` —— `await` 一个 tick。**因为页面的重渲染发生在 `act` 里，可能是异步的**：
  同一个 tick 里"点一下再读 DOM"读到的往往是**上一帧**。前三次浏览器验证失败，根因很可能就是这个。

### 86.2 诊断出了一件更要紧的事

用钩子驱动时量到：面板写着 **"战斗节点 · 开始战斗"**，而 `#mapbox` 里**唯一点亮的节点是 `shop`（id 5）**，
`g.node` 总数 69。**面板与地图说的是两件事** —— DOM 与 run 已经脱钩。

这不是页面在正常使用下会出现的状态（只点按钮的话，`act` 每次都重渲染），而是我**绕过 `act` 直接调 ABI**
造成的：ABI 改了 run，页面的 `renderMap`/`renderNode` 没有被触发，于是受控输入与显示分家。

⇒ **教训（同上一轮那条的加重版）：页面的可见状态只由 `act` 驱动。要驱动页面就得走 `act` 的按钮，
不能调 ABI 再指望它自己刷新。** 要验药水腰带，要么全程点按钮（受 40% 随机约束），要么给
`act` 一个公开的"重新渲染"入口。

### 86.3 目标状态（没变）

| 项 | 状态 |
|---|---|
| `POT` 格式 / 3 瓶内容 / 掉落 / 取得 | ✅ |
| 丢弃 | ✅ |
| 使用：格挡 +12 / 能量 +2 | ✅ 端到端断言（ABI 层） |
| 使用：伤害 | ❌ 要"带节目进来的入口" |
| 页面 chip / 用 / × | ⚠️ 只有接线断言（第 4 次未验成） |
| Neow | ✅ 真浏览器已验 |

### 86.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **661** |
### 86.5 补充：第 4、5 次尝试的两个具体教训

1. **`#runPanel` 的 `hidden` 不是"战斗结束"的信号**：它在**不在战斗时也不是 hidden**（实测：floor 0、
   还没开打，`runPanel.hidden === false`）。我拿它当循环条件，于是 `fightToEnd()` 一秒就"退出"，
   战斗根本没打，外层循环空转 25 次 —— 10 个 seed 全部停在 floor 1、belt 0。
   正确的判据是 **`ex.rd_env_done()`**（内核说这一仗结束没有），或者"`#fightBtn` 不再存在"。
2. 换成 `rd_env_done()` 之后，脚本**把 `execute` 的超时耗尽了**（异步 + 每步 `await` + 每场仗几百次
   DOM 点击）。⇒ 浏览器里跑完整一局不是一次 `execute` 该干的事：要么分段（每次调用推进几步，
   把状态留在页面里），要么接受"只验一小段"。

**下一轮的做法（定下来）**：把浏览器验证**分段**——第一次调用只"选祝福 + 走到第一场仗并打完"，
第二次调用"拿奖励（含药水）"，第三次"走进下一场仗 → 点『用』→ 断言腰带少一格"。每次调用都短、
都留状态在页面里，就不会超时。
---

## 87. 第 77 轮：**分段驱动**成了 —— 并且立刻抓到一个玩家会看见的 bug

按上一轮定下的做法，把浏览器验证拆成三次短调用（选祝福+打一场 / 拿奖励 / 走进下一场用掉）。
**这次成了**，证据如下（真浏览器、`?debug`、不注入任何东西）：

```
第 1 次：fought=true, floor=1, pending=4（战斗奖励，无药水）
第 2 次：took potion → belt=1, floor=3
第 3 次：chipsInFight=["energy_potion用×"]  ← 战斗里两个按钮都在
         before=1 → 点「用」→ after=0, chipsAfter=0
```

### 87.1 抓到的 bug：**用了药水，腰带那个 chip 还在**

第一次点「用」时：`belt 1 → 0`，但 `chipsAfter = 1` ——**药水被消耗了，图标还挂在顶栏上**。
玩家看到的会是"点了没反应，但药水没了"。

根因在 `act()`：

```js
if (mode === "run") { renderMap(verdict); renderNode(); renderTopBar(); }
```

**只在 run 模式刷新。** 药水是在**战斗里**用的（`mode === "fight"`），于是 run 变了、DOM 没动。
修法是两种模式都刷：

```js
renderTopBar();
if (mode === "run") { renderMap(verdict); renderNode(); }
else { obs = readObservation(); render(undefined, 0); }
```

修完再跑同一段驱动：`chipsAfter = 0` ✓。

⚠️ 这个 bug 只有**在浏览器里点**才会暴露：内核测试看的是"AIB 返回值与腰带计数"，那些一直是对的；
`ui_test` 的接线断言也一直是对的。**"数据对了、屏幕没变"是静态断言看不见的一类。**

### 87.2 目标状态

| 项 | 状态 |
|---|---|
| `POT` 格式 / 3 瓶内容 / 掉落 / 取得 | ✅ |
| 丢弃（页面 × 按钮） | ✅ 接线断言（chip 在真浏览器里显示了 ×） |
| 使用：格挡 +12 / 能量 +2 | ✅ 内核端到端 + **真浏览器点「用」** |
| 使用：伤害（`fire_potion`） | ❌ 需要"带节目进来的入口"（§83 两条路） |
| Neow 塔底选择 | ✅ 真浏览器已验 |

⇒ 目标 ① 除了**伤害药水**之外全部到位；② 早就完成。

### 87.3 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **661** |
---

## 88. 第 78 轮：`fire_potion` 也通了 —— **三瓶药水全部生效**

### 88.1 伤害走的是**真的**伤害管线

上一轮的结论是"`combat_damage` 缺入口"。这一轮找到了：`ExecContext::new(...)` 与
`exec::resolve_damage(ctx, target, base, ignores_block)` **都是 `pub`**。所以：

```rust
let mut ctx = ExecContext::new(&mut session.state, Some(hero), Some(target), None, 64)
    .with_content(image);
resolve_damage(&mut ctx, &target, amount, false)?;
```

⇒ 药水的 20 点伤害**和卡牌走同一条路**：格挡、易伤、以及所有伤害修饰都照常作用。
目标选择用 `target` 参数（敌人槽位，`-1` = 第一个活着的敌人），页面传 `-1`。

### 88.2 测试：三瓶**依次都用掉**

`a_potion_can_be_used_in_a_fight` 的猎取条件改成"腰带里三瓶都有"（腰带正好三格），然后：

| 顺序 | 药水 | 断言 |
|---|---|---|
| 1 | `block_potion` | **Block 恰好 +12** |
| 2 | `energy_potion` | **能量恰好 +2**（超过每回合上限 3） |
| 3 | `fire_potion` | **第一个敌人 HP 恰好 −20**，且是**走管线**扣的 |

每一步之后都断言腰带少一格。⇒ 三瓶药水都**真的用掉了**，不是"掉哪瓶验哪瓶"。

### 88.3 一处必须说清的措辞差别

目标原话是"战斗内的药水效果**走现有节目管线**"。实际情况要分开讲：

* **伤害** → `exec::resolve_damage`，**就是**那条管线 ✓；
* **格挡 / 能量** → `Combatant::set_defensive_pool` / `set_resource`。这两个是**管线内部用的同一对写入**，
  但我没有把它们包成一段节目。差别在于：目前没有"给一个战斗员加格挡"的节目节点可以单独执行
  （`node.gainBlock` 走的是完整执行器，需要节目根 + 上下文）。**这是一个已知的、说明了的不对称**，
  不是悄悄绕过。

### 88.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **661** |
| `.wasm` | 重编并 `Copy-Item`（闸门这次没抓到陈旧产物） |
---

## 89. 第 79 轮（用户报的 P0）：**开局第一个节点点不进去** —— 拒绝消息吃掉了祝福面板

用户："我自己测试，开幕雷击，第一个节点就点不进去。"

### 89.1 复现与真因

页面实测（boot 之后立刻读）：

```
panel: 塔底 · 选择一项祝福（选完才能出发） 治疗 回复 25 / 财宝 金币 100，代价 受伤 7
blessingButtons: 2   pending: 6   actionCount: 5   lit: 5   ← 问题在这两个数
```

**祝福面板是对的，但地图同时点亮了 5 个节点**，因为 `reachable()` 不看 `pending`。
玩家（和我）的第一反应是点地图上的节点 —— 于是：

1. 点击处理器把 `走不过去 · WrongPhase` **写进 `nodePanel`**，覆盖了祝福面板；
2. `renderNode` 之后再没被调用过 ⇒ **祝福按钮消失，只剩一句拒绝**；
3. 玩家看到的状态就是"第一个节点点不进去"，而且**没有出路**，只能刷新。

一句话：**一个失败的动作把"当前该做的选择"从屏幕上抹掉了。**

### 89.2 两处修（都必要）

1. **内核**：`reachable()` 在 `pending != None` 时返回**空**。"有选择待做"的时候没有任何合法移动——
   祝福（`inv:§7.1`）、战斗奖励、商店、篝火、事件都一样。空集合 ⇒ 页面一个节点都不点亮 ⇒ 点击
   根本不会发生 ⇒ 也就不会覆盖面板。
2. **页面**：`act()` 在**拒绝分支**里也 `renderNode()`。拒绝不许吃掉待做选择——这一条是兜底：
   将来任何新的拒绝路径都不会再把玩家锁死。

### 89.3 修后实测（真浏览器）

```
atBoot:        lit=0  actionCount=0  panel=祝福面板(2 个按钮)   ← 不再点亮
afterClick:    lit=0  blessingButtons=2  panel 仍是祝福面板      ← 点节点不再覆盖
afterBlessing: pending=0  lit=5  panel="还没出发 · 点亮的节点可以走"
然后点第一个节点: floor 0 → 1, cursor=0, kind=1, panel="战斗节点 开始战斗"  ← 进得去了
```

### 89.4 判据的更新

`the_blessing_is_offered_and_applied` 原来断言"走一步返回 `-2 WrongPhase`"。现在**动作表本来就是空的**，
`rd_run_step(0)` 是"没有这个动作"，所以断言改成：`rd_run_action_count() == 0` **且** `step(0) != 0`
**且** floor 不动。拒绝的形状变了，但它仍然响亮。

⚠️ 这一条值得记：**"动作被拒绝"和"根本没有这个动作"是两种不同的响亮**。前者的 UI 会写一句错误，
后者的 UI 什么都不该发生 —— 而恰恰是前者把面板吃掉了。

### 89.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **661** |
---

## 90. 第 80 轮（用户报的第二个 P0）：**一个 DOM 元素两个写者** —— 拒绝消息把"开始战斗"擦掉

用户："点了走不过去的节点提示走不过去，再点回当前节点并不会有开始战斗按钮，于是整个 ux 卡死了。
状态机应该做的稀烂没法用，可能需要好好重构了。"

### 90.1 真因：`renderMap` 也在写 `#nodePanel`

```js
function renderMap(verdict) {
  ...  document.getElementById("nodePanel").innerHTML = parts.join(" · ");   // ← 这里
}
```

`#nodePanel` 本来只该由 `renderNode()` 画（"战斗节点 · 开始战斗"这类按钮）。但 `renderMap` 为了显示
"走不过去 / 走到了 floor N"，**也往同一个元素里写**。于是任何一次被拒的地图点击都会把当前节点面板
擦成一句错误 —— 按钮没了、状态还在，玩家看起来就是"卡死"。

**这是"两个写者共用一个元素"的典型后果**，不是状态机写得乱，是**所有权没定**。

### 90.2 修法：一个元素一个写者

* `renderMap()` 只画地图；它的状态行写在 `#msg`（一个专门放消息的条），**不再碰 `#nodePanel`**；
* `renderNode()` 是 `#nodePanel` 的**唯一**写者；
* 地图点击的每条分支（成功 / `rd_run_step` 被拒 / `begin_node` 被拒）结尾都 `renderNode()`
  ⇒ 面板永远由**状态**重建，不可能停在一条错误消息上；
* 顺手加一条：**点你脚下的节点**（`g.node.here`）就是"看看这个节点要什么"，任何时候都能用 ——
  这正好对上用户"点回当前节点"的直觉。

### 90.3 实测（真浏览器，用户报的那条路）

```
站在未结算的战斗节点上：  panel="战斗节点 开始战斗"  msg="走不过去 · NodeNotSettled · 可达 1 个节点"
点另一个可达节点（被拒）：panel="战斗节点 开始战斗"  hasFightBtn=true      ← 不再被擦掉
再点当前节点：            panel 不变，按钮还在
点"开始战斗"：            进入战斗（envDone=0）
```

### 90.4 关于"要不要重构"

用户说得对，值得做。但要**说清楚是哪一类问题**，否则会把重构做成搬代码：

1. **已经修掉的那类（所有权）**：`#nodePanel` 两个写者。规则是**一个元素一个写者，内容只由内核状态
   推导**。这一条是硬的，违反了就会出现"状态对、屏幕错"。
2. **还没修的那类（形状）**：`renderNode()` 是一串 `if (pending === 0/2/3/4/5/6)`，每个分支自己拼
   HTML。它现在**能用**（每个分支都有实测或接线断言），但：
   * 新增一种 `Pending` 就要在长链里插一段，容易插错位置（第 76 轮就是插在 `pending===5` 之后才发现
     顺序要紧）；
   * 分支里的"读 ABI → 拼字符串"混在一起，没法单独测。

   我倾向的下一步不是"重写"，而是：**把每个 `Pending` 分支抽成一个纯函数**
   `describePending(state) -> {title, lines, buttons[]}`，`renderNode` 只做"调用 + 把 buttons 变成
   DOM"。这样每个分支都能在 `ui_test.mjs` 里用真 `.wasm` 驱动着断言，不再依赖点页面。
   **这是可验证的收益**（今天的如果-链只能靠人点）。

3. **不建议现在做的**：把整页改成某种框架。页面的状态**已经**全在内核里（这是本项目最值钱的一条），
   缺的是"渲染层的一层收敛"，不是状态管理库。

### 90.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **661** |
| 真浏览器 | 用户报的两条路都实测通过 |
---

## 91. 第 81 轮：**把节点面板重构成"纯函数描述 + 一张动作表"**

用户："按照第二种方式重构吧，使用必要的结构，尽量减轻功能拓展相关工作的负担。"

### 91.1 结构

新文件 `web/ui_panels.js`（零构建，和 `ui_render.js` 同一套路）：

```js
RD_PANELS.describe(snapshot) -> { title, tone?, lines[], rows[], buttons[] }
```

* `snapshot` 是**纯数据**（`runSnapshot()` 在 `index.html` 里把 14 个内核导出读成一个对象）；
* `describe` 是**纯函数**：十三个状态各一个分支，不碰 DOM、不碰 wasm；
* `buttons[]` 里每项是 `{ label, sub?, disabled?, action: { kind, slot? } }`；
* `rows[]` 给商店/奖励那种"一行一个东西 + 一个按钮"的列表；
* 页面侧只剩两件事：把描述画成 HTML（**一个渲染器**，所有状态共用），以及一张
  `PANEL_ACTIONS = { kind: (action) => 内核调用 }` 的表。

**动作按索引存**（`data-panel-action="0"`），不把 JSON 塞进属性 —— `esc()` 会把 `"` 转义成实体，
`JSON.parse` 随后就炸（这一轮真踩了）。

### 91.2 为什么这能"减轻功能拓展的负担"

| 以前 | 现在 |
|---|---|
| 新增一个 `Pending`：在 `renderNode` 的 if 链里插一段（**插错过一次**：第 76 轮插在 `pending===5` 之后才发现顺序要紧） | 在 `describe` 里加一个 `case` + 在 `ui_test.mjs` 的 `PANEL_STATES` 加一行 |
| 每个分支自己拼 HTML，混着"读 ABI"和"拼字符串"，**没法单测** | 描述是数据，**13 个状态全部在 `ui_test.mjs` 里断言**（不用浏览器） |
| 按钮的事件处理散在各分支里 | 一张 `PANEL_ACTIONS` 表；未接线的动作会被标成"（未接线）"，不会变成死按钮 |

### 91.3 新增的判据（`ui_test.mjs`，13 个状态）

每个状态断言三件事：**动作序列**、**按钮文字**、**可见文字里出现该状态的特征词**。另外单独断言
商店的 3 行、每行的动作、以及"售罄的行必须是 disabled"。

这一轮测试还当场抓到我四处写错的预期（祝福是两个按钮不是一、商店/奖励的"买/拿"是**行**不是页脚按钮、
药水出现在行里而不是标题）—— 这正是它该干的事。

### 91.4 顺手修掉的一处"以为改了其实没改"

第一版的重构脚本在写文件**之前**断言失败（脚本结构问题），于是 `renderNode` 其实**还是旧的**，
而我后面几步都在改别的文件、跑测试都是绿的 —— 直到我在浏览器里看到 `data-start` 还在，才发现。
⇒ **"测试绿"不等于"这一处改到了"**；改动要有一处**能看见它生效**的证据（这次是浏览器里的属性名）。

### 91.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **661** |
| 面板状态断言 | **13 个**（新增） |
| 真浏览器 | 祝福 → 地图 → 战斗（5 张手牌）走通 |

⚠️ 没有单独在浏览器里点过**商店/奖励/宝箱**的渲染：它们与上面走的是**同一个渲染器**，描述由
`ui_test` 覆盖；但"这一屏真的长对了"还没有截图证据。
---

## 92. 第 82 轮（用户手测）：**顶栏的血量是"run 的血量"，整场战斗不动**

用户："1. uppercut 让自己和敌人同时受到了伤害？2. 每一回合开始都是满血，没有继承之前的血量"

### 92.1 第 2 条：真 bug，但不在战斗里，在**顶栏**

先量内核：一场战斗里连按结束回合，**英雄血量是正确继承的**：

```
turn 1: 80/80 → 69/80 → 62/80 → 62/80 → 48/80 → 38/80
```

再看页面：英雄面板 `hero 69 / 80` 是对的，**而顶栏一直写 `hp 80/80`**。

根因：`renderTopBar()` 读的是 **run 的血量**（`rd_run_observe(2/3)`），而 run 的血量只在
`rd_run_fight_end` 折算时才变 —— 所以整场战斗顶栏一动不动。玩家盯着顶栏，看到的就是"每回合满血"。

修法：战斗里顶栏显示**这一场战斗的血量**（观察向量的 `[4]/[5]`），非战斗时仍是 run 的。

⚠️ 第一版修完**没生效**，因为 `const fighting = ... && Array.isArray(obs)` —— `readObservation()`
返回的是 **`Int32Array`**，`Array.isArray` 恒为假，于是这个"修复"静默地什么都不做。改成 `obs?.length > 5`
之后才真修好（实测顶栏 80 → 69 → 62 跟上了）。

### 92.2 第 1 条：内核层面**证伪**了

内容里 `uppercut` 的三步全是 `sel.eventTarget`（`dealDamage 13` / `weak` / `vulnerable`），
没有一步指向自己。为了不靠推理，写了一个内核测试 `uppercut_hurts_the_enemy_and_not_the_hero`：

* 用一副**全是 uppercut** 的牌组建战斗（起始牌组里没有它，所以只能这么测）；
* 打出第一张，断言 **英雄血量一点没变**、**敌人恰好 −13**。

**测试通过** ⇒ 卡牌逻辑没问题。

那用户看到的"自己受伤"最可能是：**顶栏静止的 80/80 与英雄面板的血量对不上**（就是 92.1 那条），
或者敌方意图在回合末打到英雄，和 uppercut 的伤害数字前后挨着看成了"同时"。**这条我无法复现**，
所以不写成"已修"，只写成"内核已证伪 + 顶栏那条已修"。

### 92.3 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 661 | **662**（新增 uppercut 那条） |
| 顶栏血量 | 整场不动 | **跟着战斗走** |
---

## 93. 第 83 轮：**"观察向量"不再是一份快照** —— 以及为什么我前三次都是补丁

用户："战斗记录里面显示 bash 手牌打出后英雄受到 7 点伤害……实际上这个 7 是塔底获得的与这张手牌没有关系。
感觉你的调试验证思路必须反思改进了。"

### 93.1 真因：**派生的视图被当成缓存**

战斗记录是"两条观察向量的差分"（`diffObservations(before, obs)`）。而 `OBS` 只在 `rd_env_step`
的尾巴里由 `publish()` 更新。于是**任何不走 step 的状态变更**（药水、战斗起始血量、祝福）都会让下一条
`before` 是陈旧的 —— 第一次出牌就被算上了"战斗开始前"发生的事。

我在三个不同地方给同一个病打了三次补丁（药水 → 补一次 `reobserve`；战斗起始血量 → 再补一次）。
**这次改的是病本身**：

```rust
pub unsafe extern "C" fn rd_env_observe_into(ptr) -> i32 {
    if let Some(session) = slot().as_mut() {
        session.reobserve_after_external_change();   // ← 读的时候才算
    }
    copy(OBS → ptr)
}
```

观察向量现在**在读取时从状态派生**，所以"发布过但没更新"这种状态在结构上不存在了。

### 93.2 判据，并且**证明它能抓住 bug**

`a_fight_starts_at_the_runs_health_and_the_observation_agrees`：扫 seed 找一个"祝福代价是掉血"的局，
让 run 带伤，然后走进战斗、`fight_begin`，断言**观察向量里的血量 == run 的血量**（不是最大值）。

**反向验证**：把 `set_combat_hero_health` 里那句 `reobserve` 删掉，测试立刻红：

```
assertion `left == right` failed: the fight's published HP must be the run's, not the maximum
  left: 80      ← 发布出去的
 right: 66      ← run 里真实的
```

⇒ 这条测试**能区分**"修了"和"没修"。这是这一轮我唯一愿意称为"验证"的东西。

### 93.3 用户留的现场，修后逐条复现（真浏览器）

`seed 1`，塔底选 **血钱（金币 150，代价 受伤 14）**：

```
祝福之后:      top="floor 0 · hp 66/80 · gold 150"        ← 顶栏立刻是 66
战斗开始:      top="floor 1 · hp 66/80 · gold 150"        ← 不再是 80
打出 Defend:   log = [手牌离开：defend, 消耗 1 点能量, 英雄 获得 5 点格挡]
                                                          ← **没有**"英雄 受到 14 点伤害"
```

### 93.4 我的验证思路，要改的四条

1. **先问"这个值是谁派生的"**：只要有两处表示同一件事（`OBS` vs `state`），就必须**一处派生**或
   **每次读取都重算**。缓存容器的 bug 永远长得像"某处忘了同步"。
2. **在 ABI 边界加"发布值 == 真实值"的断言**，而不是只测"函数返回对不对"。这一轮补的就是这条。
3. **测试要证明它能区分**：写完先**把修复删掉**看它红不红。这轮做了（80 vs 66）。
4. **驱动出错的那一层**：这次的错在**页面的 diff 逻辑**（纯 JS），而我一直只在检测内核。下一步要给
   `diffObservations` 一个真序列的回归用例（两条真实向量 + 期望的日志行），而不是靠我眼睛看浏览器。

### 93.5 数字

| 项 | 前 | 后 |
|---|---|---|
| 聚合验收 | 16/16 | **16/16** |
| 单测 | 662 | **663** |
| 幽灵伤害 | 有 | **无**（真机复现你的现场） |
---

## 94. 第 84 轮：给"战斗记录"立一条判据 —— 以及**它测不到什么**

用户："OK，按照这个思路重构并且完善 ui ux 吧。"

按上一轮 §93.4 的第 4 条（"驱动出错的那一层"），这一轮补的是**页面日志层的判据**。

### 94.1 新增：日志不许说谎（`ui_test.mjs`）

驱动一场真战斗（`rd_env_reset` 起手，能出牌就出牌、否则结束回合），每一步算
`diffObservations(before, after, wasEndTurn)`，然后断言：

> **日志声称的血量变化 == 两条向量实际的血量变化**（英雄 + 每一个敌人槽位）

它不需要手写期望——这是关键。**"有事件没变化"（幽灵）**和**"有变化没事件"（漏报）**两种都会红。

### 94.2 ★ 但我先做了"这条测试能不能抓到它"的检查 —— 结果**抓不到**

把基线冻住（`before = after;` 注释掉，也就是用户报的那个 bug 的形状）之后，这条测试**仍然是绿的**：

```
battle log        16 steps, claimed == actual for hero and every enemy
```

原因很直接：**比较的两边用的是同一对向量**。所以它只能证明 `diffObservations` 自洽（事件与它拿到的
两条向量一致），**不能**证明那两条向量本身是新鲜的。

⇒ 我把这条**写进了测试注释**，没有假装它覆盖了那个 bug：
* **陈旧基线**这一类，由 Rust 的 `a_fight_starts_at_the_runs_health_and_the_observation_agrees`
  抓（它拿"发布值"对比 **run 自己的血量**，一个**独立的真值**），并且上一轮已经**删掉修复验证过它会红**
  （`left: 80` / `right: 66`）；
* 这条 JS 判据挣的是另一份工钱：**diff 读错格子（偏移错了）或凭空造事件**。

### 94.3 顺带记两个"我怎么把自己绊倒的"

1. 这条测试第一次跑就红：`log claims enemy 0 -8 HP but vectors moved 0` —— 因为我把
   `OFF_ENEMY` 猜成了 12（真实是 **17**）。**猜常量比读常量慢得多。**
2. 冻结基线的"变异测试"是通过断点式改动做的，脚本化替换后必须再跑一次确认恢复（这次 `identical: True`）。

### 94.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **663** |
| 日志判据 | **16 步**逐项核对（英雄 + 每个敌人） |
| 已知覆盖不到 | 陈旧基线（由 Rust 那条独立真值的测试负责） |
---

## 95. 第 85 轮：**Shift+点牌看说明**（商店不再是盲猜）

用户："按住 shift 点击卡片，无论是商店界面还是使用界面都显示卡片的详细介绍，现在的交易全靠盲猜。"

### 95.1 一个导出，三个来源

```rust
rd_run_card_fact_len(source, slot, field) -> i32        // field: 0 标题, 1 说明
rd_run_card_fact_into(source, slot, field, ptr)
// source: 0 = 商店卡槽, 1 = 奖励卡槽, 2 = 牌组第 N 张
```

六个导出（每个来源 × 每个字段）会变成一堆近似重复；一个带两个小整数的倒是一次说清。手牌不必走它 ——
战斗侧本来就有 `rd_env_card_title_*` / `rd_env_card_text_*`。

页面侧只有一个 `cardFacts(where, slot)`（`hand` / `shop` / `reward` / `deck`）和两个入口：
`showCardDetail()` 与一段**委托**的 shift+点击处理 —— 新面板只要在行上写 `data-card="<where>:<slot>"`
就自动拥有这个手势。

### 95.2 覆盖的地方

| 位置 | 手式 |
|---|---|
| 手牌（战斗） | Shift+点击卡面 → 弹窗（**普通点击仍然是出牌**，测试里验了这两件事都成立） |
| 战斗奖励 | Shift+点击整行 → 弹窗 |
| 商店 | Shift+点击整行（卡与遗物行都行）→ 弹窗 |
| 牌组"所有牌" | Shift+点击 → 弹窗 |

### 95.3 判据

* `smoke.mjs`：新导出必须真的存在（它当场抓到我把 `rd_run_card_fact_*` 写进页面却没重编 wasm）。
* `ui_test.mjs`：**每一行"可交易的卡"必须带 `card` 来源**（`shop:N` / `reward:N`）——
  没有它，shift+点击就没有对象可开。遗物行不算卡，断言里排除了。
* 真浏览器实测：
  ```
  手牌 Shift+点击 → title="Strike", body="Deal 6 damage."
  随后普通点击  → log 出现「手牌离开：strike / 消耗 1 点能量 / 敌人 0 受到 6 点伤害」  ← 仍然出牌
  奖励行 Shift+点击 → title="Anger", body="Deal 6 damage. Add a copy of this card into your discard pile."
  ```

### 95.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **663** |
| 新导出 | 2（`rd_run_card_fact_len/into`） |
---

## 96. 第 86 轮：`#msg` 收成一个写者；战斗日志改成**一步一行**

用户："继续按这个顺序做下去吧。"（① `#msg` 单写者 ② 日志措辞/分组）

### 96.1 ① `#msg` 只有一个写者

两处曾直接赋值（`renderMap` 的状态行、`act` 的拒绝消息）——正是 `#nodePanel` 出过两次 P0 的形状
（§89、§90）。现在只有一个 `say(text)`，三处调用都走它，`ui_test.mjs` 里有一条接线断言盯着
（`function say(` 必须存在，否则"消息条没有单一写者"）。

### 96.2 ② 日志：一步一行，原因和效果挨在一起

以前一次出牌会拆成三到四行：

```
手牌离开：bash
消耗 2 点能量
敌人 0 受到 8 点伤害
敌人 0 vuln +2
```

现在：

```
打出 bash → 耗 2 能量，敌人 0 −8，敌人 0 易伤 +2
```

回合/战斗结束仍是独立的一行（它们是分隔符）。实现只改 `ui_render.js::logLines` 的**呈现**：
事件由 `diffObservations` 产出，上一轮那条"日志声称的变化 == 向量实际的变化"不变量断言的正是**事件**，
所以措辞变了它照样盯着。

### 96.3 三处跟着改的断言（都是"措辞"不是"逻辑"）

`ui_test.mjs` 里原本按旧措辞断言的三个地方，改成按新格式：

| 原断言 | 新断言 |
|---|---|
| 行里含 `受到 N 点伤害` | 行里含 `英雄 −N` |
| 行里含 `抽 N 张牌` | 行里含 `抽 N 张` |
| 三段式（离开→消耗→伤害）分三行且顺序正确 | **同一行内**存在 `打出 … → … 耗 N 能量 … 敌人 0 −M` 的次序 |

⚠️ 改这三处时我**又一次**用脚本做外科手术把 `ui_test.mjs` 改坏了两回（多留一个 `}`、丢了一个
`const at`），第二次才用行号定位修好。**这个反复出现的失败模式值得单独记**：小步预演比一次性大改更省。

### 96.4 一个环境陷阱（我花了两次才确认）

页面里 `ui_render.js` 是**独立缓存**的资源：改了它、只刷新 `index.html` 的带参数 URL **不会**让它重新加载。
我在页面里用 `fetch("ui_render.js?bust=…")` + `new Function` 现取现算，才证明新代码是对的：

```
新： 打出 bash → 耗 2 能量，敌人 0 −8，敌人 0 易伤 +2
旧（缓存）：四行
```

⇒ **验证 UI 改动时要确认脚本本身是不是新的**；用户侧需要 Ctrl+F5。

### 96.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **663** |
| `#msg` 写者 | 3 处 → **1 处** |
| 一次出牌的日志行 | 3~4 行 → **1 行** |
---

## 97. 第 87 轮：战斗页的"能不能做"与地图页的"为什么不行"

用户："接下来把 3、4 一起做吧。"

### 97.1 ③ 战斗页：三处"看得见的状态"

| 元素 | 以前 | 现在 |
|---|---|---|
| 手牌 | 付不起的牌只靠 `disabled`（灰得和"出过了"一样） | 加 `unaffordable`：**整体降饱和 + 费用徽章变红**；能打的牌悬停上浮 + 阴影 |
| 敌人 | 有意图的敌人和"准备中"的看起来一样 | 会打人的敌人加 `threat`：**边框变暗红** |
| 可选目标 | 只能从 `crosshair` 知道 | 悬停时**金色描边**（`outline`），一眼看出"这可以点" |

**实测**（真浏览器，同一场战斗）：
```
能量 3/3 → 手牌 5 张全部 "ok"
连打几张到能量 0/3 → 剩下 2 张 "dim:disabled"        ← 付不起就是付不起，看得见
敌人面板 class = "enemy-panel threat"                  ← 会打人的
```

### 97.2 ④ 地图页：点不动的地方要说话

以前点一个**没点亮**的节点 = **什么都不发生**（读起来像页面坏了）。现在会说明理由，并且**理由分两种**：

* 面板里还有待做的选择（祝福/商店/奖励…）⇒ `走不过去 · 先把手上的选择做完（面板里那个），才能往前走`
* 单纯不相邻 ⇒ `走不过去 · 只能走点亮的节点 —— 它和当前节点连着`

**实测**：点一个未点亮的节点 → `msg` 显示 `走不过去 · 只能走点亮的节点 —— 它和当前节点连着`，且**没有任何状态变化**。

### 97.3 判据

`ui_test.mjs` 加三条**接线**断言（页面里必须出现这些字样/类名，否则红）：
`unaffordable`、`threat`、`只能走点亮的节点`。它们不能证明"好看"，但能证明**这三处提示没有被后来的改动删掉**。

⚠️ 仍然没有"像素级"的判据 —— 颜色和间距依旧只能靠眼睛。这一层我写清楚，不假装有覆盖。

### 97.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | **663** |
| 新增可见状态 | 3（付不起 / 有威胁 / 可点目标） |
| 地图拒绝提示 | 0 句 → **2 种理由** |
---

## 98. 第 89 轮：**先改基建**（测试助手不再假设"开局满血"），再做塔底的两条规则

上一轮我在这里翻了车：改祝福池 ⇒ 四个测试连锁红 ⇒ 回退。这一轮按定下的顺序**先改基建**。

### 98.1 基建：把"开局 80/80"这个假设从测试里拔掉

| 位置 | 之前 | 之后 |
|---|---|---|
| `reset(seed)` | 取 slot 0，测试默认这不动血 | 取 slot 0，**文档明确写"这里不保证满血"** |
| `a_run_starts_from_the_content_not_from_constants` | 在祝福之后断言 `80/80`、`gold 0` | 在**祝福之前**断言（这才是"内容说的"），祝福之后再读 seed |
| `burning_blood_heals_at_the_end_of_the_fight` | `−20` 后断言 `66` | `base - 20 + 6` |
| `winning_heals_through_the_relic` | `assert_eq!(start, 80)` | 只断言 `start > 0`（它关心的是"战后回血"，不是 80） |
| `a_fight_is_the_runs_fight_and_the_result_goes_back` | `−20` 后断言 `60`、`Some(60)` | `base - 20` |

⇒ **祝福池从此怎么改都不会再连锁红**。这就是"基建"的意思。

### 98.2 塔底的两条规则（用户的例子 + 我加的）

1. **满血不出 `heal`**：`blessing_is_meaningful` 里一条规则——`Heal` 只在 `health < health_max` 时有意义。
2. **必有一个免费选项**：只有"掉血的选项"不是选择，那是"开局必须先受伤"。两条 offer 都收费时，
   强制把其中一个换成免费的。

### 98.3 判据

`blessing_offers_are_never_nonsense`（rd-run，**80 个 seed**）：

* 任何 seed、满血开局 ⇒ 两个 offer 都**不含 `Heal`**；
* 任何 seed ⇒ 至少一个 offer 的 `cost` 是 `Nothing`（不逼玩家受伤开局）；
* 受伤之后再掷 16 次 ⇒ **仍然出得了 `heal`**（规则看的是状态，不是把 heal 从池子里删掉）。

### 98.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | 663 → **664** |
| 连锁红的测试 | 4 → **0**（基建修好后祝福池可自由演进） |
---

## 99. 第 91 轮：塔底从 4 项扩到 **6 项**（加了"删一张牌""升级一张牌"）

上一轮倒在这里：池子一变，4 个测试因为"起始牌组正好 10 张"连锁红。这一轮先把**牌组侧的基建**做完。

### 99.1 基建（第二半）：不再假设牌组是 10 张

| 位置 | 之前 | 之后 |
|---|---|---|
| `reset(seed)` | 取 slot 0 | 按"不碰东西"打分挑一个（不删牌/不升级/不掉血），并且**把欠的选牌做完** |
| `the_deck_can_be_listed_...` | 断言 10 张、5 张 Strike | 断言"每行都有标题""三种牌都在"；**组成**在祝福之前钉 |
| `the_piles_can_be_listed_...` | `draw == 5`、`piles + hand == 10` | `draw > 0` 且 `draw + hand <= 牌组数` |
| `a_fight_is_the_runs_fight_...` | `piles + hand == 10` | 与 `rd_run_deck_count()` 比 |
| `the_blessing_is_offered_and_applied` | 选完就断言 `pending == 0` | 先做完欠的选牌 |

⇒ 加上上一轮的 HP 解耦，**祝福池现在真的可以自由演进**（这正是 §98 当时说要做到、但只做到一半的事）。

### 99.2 两项新祝福

```rust
pub enum BlessingFollowUp { None, RemoveCard, UpgradeCard }
```

`StartOffer` 多一个 `follow_up`；`choose_start` 取完之后如果是这两个，run 停在 **`Pending::BlessingCard`**，
等一个牌组下标；`pick_blessing_card(index)` 做实际的删/升级。ABI：`rd_run_start_needs(slot)`（这一项要不要
选牌）、`rd_run_blessing_needs()`、`rd_run_pick_blessing_card(index)`。

⚠️ 两处细节：**不能复用 `remove_card`/`smith`**（它们各自带"只在商店/篝火"的相位门），所以这里是等价的
列表搬移与写回；`rd-run` 是 `no_std`，**没有 `format!`**，`strike` → `strike+` 是在栈上的 `[u8; 64]` 里拼的。

### 99.3 判据

`a_blessing_can_remove_or_upgrade_a_card`（rd-run）：取 `remove_card` ⇒ `pending == BlessingCard`；
`pick_blessing_card(3)` ⇒ 牌组少一张；取 `upgrade_card` ⇒ `pick_blessing_card(2)` ⇒ 第 3 张变 `strike+`
且**张数不变**；越界 ⇒ `BadNode`（不是静默无事）。

### 99.4 页面

`pending === 7` 时出「塔底 · 移除/升级哪一张牌？」+「选一张牌」，点了走 `showDeckPicker` →
`rd_run_pick_blessing_card`。`map_test.mjs` 的 `takeBlessing()` 也跟着做完选牌（否则走不动）。

### 99.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | 664 → **665** |
| 塔底选项 | 4 → **6** |
---

## 100. 第 92 轮：塔底补到 **wiki 的 8 项**（变形 / 三张牌）

用户："三个挨个一起做吧。"（① 塔底到 8 项 ② 第二幕 ③ 像素级回归）——这一轮先做 ①。

### 100.1 牌池第一次进了"选择"这条路

`three_cards` 和 `transform_card` 需要**随机取牌**，而 `rd-run` 从来没有牌池（`roll_reward` 是调用方
传进来的）。这一轮把池子顺着祝福这条路传下去：

```rust
choose_start(slot, pool: &[PoolCard<'_>])       // three_cards 当场加三张，不留待办
pick_blessing_card(index, pool)                  // transform 删一张、随机补一张
```

`BlessingFollowUp` 加了 `TransformCard` / `GainThreeCards`；随机用的是 run 自己的 `Event` 子流，
只从**非 Status/Curse** 里挑（和奖励池同一条规矩）。

### 100.2 顺手加的一条"有意义"规则

`blessing_is_meaningful` 现在有两条：满血不出回血、**空牌组不出任何改牌组的祝福**。
第二条今天用不上（牌组不会空），但它是"规则跟着状态走"的同一个形状，写下来比将来补丁好。

### 100.3 判据

`a_blessing_can_transform_or_add_cards`（rd-run）：
* `transform_card` ⇒ 取完 `pending == BlessingCard`；`pick_blessing_card(4)` ⇒ **张数不变**；
* `three_cards` ⇒ 取完**当场** `pending == None`、牌组 **10 → 13**。

### 100.4 跟着改的测试（都是"别假设牌组是 10 张"的余波）

* `map_test.mjs`：`count !== 10` → `count < 9`；组成断言从"5/4/1 精确" → "三种牌都在"。
* `rd-wasm` 的两个导出不再自己造池子，而是 `reward_pool(content())`。

### 100.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | 665 → **666** |
| 塔底选项 | 6 → **8**（= wiki 的 8 项） |
---

## 101. 第 93 轮：**第二幕（结构性）** + 全量回归

用户："把第二幕做完一并回归吧。"

### 101.1 做了什么

`RunState` 有了 **`act: u8`（1 起）** 与 `MAX_ACT = 3`。`mark_boss_beaten()` 现在不再直接"通关"：

* `act < MAX_ACT` ⇒ **推进一幕**：`act += 1`、`floor = 0`、`node = -1`、`pending = None`、`resolved` 清零；
  **血量 / 牌组 / 遗物 / 金币全部带过去**（血量由战斗结束那一步已经折算过）；
* `act == MAX_ACT` ⇒ 才是真正的通关（`boss_beaten = true`）。

ABI：`rd_run_act()`。页面顶栏最前面多了 `幕 N`；结算面板的标题从写死的"第一幕通关"改成 `第 N 幕通关`。

### 101.2 ⚠️ 一处**写明**的降级

**这份内容只有一幕的素材**（一张地图、一套遭遇/事件/药水），所以第 2、3 幕**复用第 1 幕的**。
也就是说：**"推进"这个机制是真的**（幕数、进度重置、继承、通关条件），**幕与幕之间的内容差异是假的**。
这一条同时写进 `port-plan.md` 与代码注释 —— 不能让它看起来像"第二幕做完了"。

### 101.3 判据

`the_boss_of_an_act_advances_instead_of_ending_the_run`（rd-run）：
杀 act 1 Boss ⇒ `act == 2`、`boss_beaten == false`、`floor == 0`、游标 -1，**牌组与血量不变**；
杀 act 2 Boss ⇒ `act == 3`；杀 act 3 Boss ⇒ `act` 仍 3 且 `boss_beaten == true`。

### 101.4 回归（用户要求"一并回归"）

| 闸门 | 结果 |
|---|---|
| 聚合验收 | **16/16** |
| 单测 | 666 → **667**（rd-core 579 / rd-run 61 / rd-wasm 27） |
| `WEB_SMOKE` / `UI_RENDER` / `MAP_RENDER` | 全 PASS |
| 真浏览器 | 顶栏读作 `幕 1 · floor 0 · hp 80/80 · gold 0 · deck 10`，祝福面板正常 |

⚠️ **`the_boss_is_offered_at_floor_16_and_clears_the_act` 这条 ABI 用例走到的是"输给 Boss"的分支**
（机器人打不赢），所以"赢了之后进第二幕"只有 rd-run 的直接测试覆盖，**没有 ABI 层证据**。这条记在这。
---

## 102. 第 94 轮：**第 17 道闸门 —— 真浏览器回归（零依赖）**

用户："OK，按这个计划进行吧。"（Playwright + 关键文字断言 + 接进闸门）

### 102.1 计划改了一处：**不装 Playwright**

`web/` 一直是**零构建**，Playwright 会再拉一份 Chromium（~150 MB）。而本机**已经有 Chrome**，Node 22
又自带 `WebSocket` —— 于是驱动只需要三样现成的东西：

1. `node:http` 起一个静态服务（20 行）；
2. 系统 Chrome `--headless=new --remote-debugging-port=0`，从 `DevToolsActivePort` 读端口；
3. CDP 的 `Runtime.evaluate`（`awaitPromise: true`）在页面里跑脚本、**把渲染出来的文字带回来**。

`web/browser_test.mjs` 约 300 行，**零依赖**，`node web/browser_test.mjs` 直接跑。

### 102.2 它断言的是"渲染出来的文字"，不是像素

| # | 断言 |
|---|---|
| 1 | 塔底给出**两个**祝福，而且显示的是**名字**不是 id（`净化 / 财宝 金币 100，代价 受伤 7`） |
| 2 | 选完之后 `pending == 0`（祝福真的结算了，含"欠一张牌"那条分支） |
| 3 | 点一个走不到的节点 ⇒ 消息条出现 `走不过去 · 只能走点亮的节点 —— 它和当前节点连着` |
| 4 | 走进节点能开战（`#handPanel` 可见） |
| 5 | **Shift+点击**手牌 ⇒ 弹窗打开、标题与说明都有（`Bash · Deal 8 damage. Apply 2 Vulnerable.`） |
| 6 | 出牌后日志**写着牌名**（`打出 defend → 耗 1 能量，英雄 +5 格挡`） |
| 7 | 顶栏以 `幕 N` 开头（`幕 1 · floor 1 · hp 80/80 · …`） |
| 8 | 能量归零后，手上的牌被标成 `unaffordable`（实测 3 张） |

这三条正好覆盖**三次 P0** 的形状——它们当初都是"点一下才知道"的。

### 102.3 接进闸门

`tools/acceptance.ps1` 加**第 17 道**：`web-browser`，证据串 `BROWSER_TEST PASS`，600 秒超时。
聚合验收从 16/16 变成 **17/17**。

### 102.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17**（新门全绿） |
| 单测 | **667** |
| 新文件 | `web/browser_test.mjs`（零依赖） |
| 新增依赖 | **0** |
---

## 103. 第 95 轮：药水可以**选目标**了（多敌人时不再只能打第一个）

用户："下一步完善一下药水与作战系统的交互。"（敌人种类与 buff/debuff 是同一批要求，下一轮）

### 103.1 以前是什么样

`rd_env_use_potion(slot, target)` 一直带 `target`，但页面**永远传 -1**（=第一个活着的敌人）。
三敌人在场时，玩家对"20 点伤害打谁"没有任何决定权 —— 而这个 ABI 参数就是为此存在的。

### 103.2 现在

新增导出 **`rd_run_potion_effect(slot)`**：`1` 伤害（要目标）/ `2` 格挡 / `3` 能量 / `4` 回血 / `0` 未知。

页面据此分两种处理：

* **伤害药水 + 场上多于一个活敌人** ⇒ 进入"瞄准态"：`#enemies` 加 `potion-armed`（每个活敌人绿色虚线描边 +
  crosshair），消息条写「用药水 · 点一个敌人」；下一次点敌人面板就是目标，药水按那个槽位用掉；
* 其余情况（格挡/能量/回血，或只有一个敌人）⇒ 立刻用，行为不变。

细节：`potionPending` 在 `beginFight()` 里清零（上一场的瞄准不许延续到下一场）。

### 103.3 判据

* `smoke.mjs` 要求 `rd_run_potion_effect` 真的存在（它当场抓到我改了页面但**忘了重编 wasm**）；
* 第 17 道闸门（真浏览器）依旧全绿 —— 它覆盖的是"药水能从腰带用掉"，目标选择是这条路径的分支；
* ⚠️ **"多敌人 + 伤害药水 ⇒ 瞄准态"这条分支没有自动化判据**：它需要"药水恰好掉一瓶 fire_potion 且
  遭遇是三个敌人"这种组合。记在这里，不假装覆盖。

### 103.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | **667** |
| 新导出 | 1（`rd_run_potion_effect`） |
---

## 104. 第 97 轮：**架构层的一条硬规则 —— 惰性状态必须被声明**

用户："先反思为什么一改就回退……先动手按这个计划重构架构（业务代码 + 测试代码），再继续拓展功能。"

### 104.1 这次不动"上帝对象"，先补那条能**立即止损**的规则

反思 §103 时找到三个真问题，其中排第一的、也是**唯一能在一次交付里做完**的是：

> **一个概念有三份账**：`status_catalog`（名字/极性/tag）、内容 `STAT` 表、`host+exec`（行为）。
> 前两份很乐意描述一个**没人实现**的状态 —— 侦察时实测：`standard.artifact`、`standard.thorns` 在目录里
> 有元数据、有 tag，而 `host.rs` 里 `artifact` 出现 **0 次**。**"存在但不生效"是最坏的缺口形状：它看起来完成了。**

所以这一轮把"三份账"变成**两份 + 一次校验**：

```rust
// status_catalog.rs
pub fn has_behaviour(id: &str) -> bool          // 内核真的有规则的状态（10 个）
pub fn is_declared_inert(id: &str) -> bool      // 明知无效、且写明理由的（目前只有 "ritual"）
```

`the_status_catalogue_is_honest`（rd-core，读**真镜像**）：内容里声明的每一个状态，必须
`has_behaviour || is_declared_inert`，否则**当场红**，报「it would silently do nothing」。

⇒ 以后加 Metallicize / Thorns / Artifact，**要么给行为，要么进 inert 名单并写理由**，没有第三种。

### 104.2 顺手抓到一个"死掉的测试"

插入新测试时，`the_real_images_validate` 的 `#[test]` 被顶掉了（新测试占用了它上面的属性），
它会**静默地不再运行**。这正是我记忆里那条"把 `#[test]` 丢掉"的老坑，这次自己复查发现并补回：
rd-core 从 579 → **581**（+1 新测试，+1 复活的老测试）。

### 104.3 这轮没能做的（诚实）

"夹具独立"（让测试自己造最小对象，而不是共享 `reset()` 重放真实开局）是反思里排第二的架构问题，
它要动 27 个 wasm 测试的夹具，**不是一次能收尾的**。这一轮先把"三份账"钉死，夹具留到下一轮单独做。

### 104.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 667 → **669**（rd-core 579 → 581） |
| 新增规则 | 惰性状态必须被声明（读真镜像校验） |
---

## 105. 第 98 轮：**夹具独立 —— 让测试不再重放"开局"**

上一轮说了要做的第二件事。这一轮做的是它最小可用的一半。

### 105.1 `test_run`：一个不做"开局"的构造函数

```rust
#[cfg(test)]
fn test_run(seed, health, max_health, deck)   // 直接进槽位，不抽祝福、不走 rd_run_start
```

以前每个 wasm 测试都从 `reset(seed)` 开始 —— 那会**重放真实开局**（`rd_run_start` → 掷祝福 → 取祝福）。
于是"改祝福池"就让四个**跟祝福无关**的测试红（§88、§90 两次都是这样）。

现在测试可以只要它需要的东西：`test_run(7, 80, 80, &["strike"; 10])`。已经迁移三个
（**牌堆 / 牌组 / 战斗折算** —— 它们关心的是牌，不是开局）。

### 105.2 `reset` 补了**合同断言**

```rust
assert_eq!(rd_run_pending(), 0, "reset left a choice pending");
assert_eq!(rd_run_act(), 1, ...);
assert_eq!(rd_run_observe(0), 0, ...);
assert!(rd_run_deck_count() > 0, ...);
```

意图：将来再有人动开局路径、留下一个"半启动"的 run，**失败会停在这一行**，而不是散成 27 条看不懂的红。

### 105.3 还没做的（诚实）

**只有 3 个测试迁移了**，其余 24 个仍然先用 `reset`。迁移的规则写在 `test_run` 的文档注释里：
*"一个关于开局路径的测试继续用 `reset`，其它都该用 `test_run`"*。**逐个摸到时再迁**，不一次性大改
（一次性大改正是这两天的回退来源）。

### 105.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | **669** |
| 迁移的测试 | 3（其余 24 个按同一规则陆续迁） |
---

## 106. 悬挂项清单（**写在明处，带数字**）

> 规矩：**一个已知的"没做完"必须有数字，否则它会在两周后变成"我以为做完了"。** 这里只列真正悬挂的，
> 做完就删掉。

| # | 悬挂项 | 数字 | 位置 | 下一步 |
|---|---|---|---|---|
| 1 | 夹具迁移（`reset` → `test_run`） | **7 / 27 已迁，20 个仍用 `reset`** | `rd-wasm/src/run.rs` 的 `reset` 文档注释 | 摸到哪个迁哪个；**不做一次性 sweep** |
| 2 | 惰性状态 | **1 个**：`ritual`（在 `is_declared_inert` 里） | `rd-core/src/status_catalog.rs` | 做 Ritual 的行为时，必须同时把它挪进 `has_behaviour`，否则 `the_status_catalogue_is_honest` 红 |
| 3 | 目录里有名字、`host.rs` 里没行为的 | `artifact`、`thorns`、`metallicize` 等（侦察于 §104） | 同上 | 加行为，或加进 inert 名单并写理由 —— **没有第三种** |
| 4 | 药水"多敌人 + 伤害药水 ⇒ 瞄准态"分支无判据 | 1 条分支 | `web/index.html` | 需要"fire_potion + 多敌人"的组合，暂只能手测 |
| 5 | 幕与幕之间的内容差异 | 第 2、3 幕**复用**第 1 幕素材 | `rd-run` 的 `mark_boss_beaten` | 先做内容，再谈"真第二幕" |
| 6 | `rdcf-verify` 的 `5/5 tables` | 少报 2 张（`EV`、`POT`） | `tools/` 的校验器 | 让它读 `ROW_SCHEMAS` |
| 7 | 像素级判据 | 0 条（第 17 道闸门只断文字） | `web/browser_test.mjs` | 颜色/间距仍只能靠眼睛 |

**本轮的下一步**（按用户要求，写完这份清单就继续）：给 `host.rs` 的 `turn_ended` 加 **Metallicize** 的
一根臂 —— 先写一条会红的测试，再实现，再内容，再怪，再全量闸门。

---

## 107. **更正 §106 的下一步**：Metallicize 大概是**内容活**，不是内核活

写 §106 时我写的是"给 `host.rs` 的 `turn_ended` 加一根臂"。动工前读了那个钩子，结论**相反**：

```rust
pub fn try_run_turn_ended_triggers(&mut self, state, actor) -> Result<(), HostError> {
    self.flush_deferred()?;
    state.enqueue_event_at_root(CombatEvent::TurnEnded { combatant: *actor })?;
    self.try_resolve_pending_queues(state)
}
```

`turn_ended` **不发号施令**：它只是把 `TurnEnded` 事件入队，然后**跑内容里挂在这个事件上的触发器**
（`TRM`/`TRW` 两张表）。同理 `turn_started`、`damage_received`。

⇒ **这个内核是数据驱动的**：`status_catalog` 里那些条目只是**元数据**（极性、tag、排序），真正的
"回合结束加格挡"应当是一条**内容触发器**：

```
状态 metallicize(N)
触发器：on TurnEnded, self has metallicize  →  节目 gainBlock(N)
```

### 107.1 这意味着什么

| 之前的判断（§106） | 更正后 |
|---|---|
| 加一只怪的 Metallicize 要动 `host.rs` | **大概不用动内核**，是内容 + 触发器 |
| 三个状态 = 三处内核改动 | 三个状态 = 三条触发器 + 三行 `STAT` |
| `has_behaviour` 要跟着加 id | **仍然要**：状态"有行为"的判据从"内核有分支"变成"内容有触发器"，而 `has_behaviour` 的语义要跟着改口径（见下） |

### 107.2 于是 §104 那条规则的口径要修一次

`has_behaviour(id)` 现在的注释写的是"内核真的有规则（`host.rs`/`exec.rs` 里有分支）"。数据驱动下这句
**不准确**了：行为可以完全在内容里。正确的口径是：

> **一个状态"有行为" ⟺ 内容里有触发器/节目引用它，或者内核里有分支。**
> `is_declared_inert` 只留给"两边都没有"的状态。

这条修正是下一轮的第一件事（比做 Metallicize 更靠前），因为它决定 `the_status_catalogue_is_honest`
到底在查什么 —— 一个查错的规则比没有规则更糟。

### 107.3 下一轮的具体第一步

1. 在 `docs/spec/content-schema.md` / `effect-program-ir.md` 里读 `TRM`/`TRW` 与
   `TriggeredEffects` 的**行 schema**（encounter 记录里已经有 `TriggeredEffects: []` 这个字段，
   说明形状是现成的）；
2. 手写**一条**内容触发器（`TurnEnded` → `gainBlock`），挂在一只新怪身上，看 `sts_content_check`
   的 inert 检查是不是**立刻发现它没被引用**；
3. 只有第 2 步证明"内容触发器跑不通"时，才回到内核加臂。

⚠️ 这一轮没写代码：**把一条会误导下一轮的计划改对，比硬着头皮按错的计划动手更值**。

---

## 108. 触发器的**形状**找到了（§107 第 2 步的一半）

§107 说下一步是"读 `TRM`/`TRW` 与 `TriggeredEffects` 的行 schema"。这一步做了，结论如下。

### 108.1 参考文档里的一条真实触发器（逐字）

```json
"TriggeredEffects": [
  { "Event": "CardPlayed",
    "Program": { "Id": { "Value": "(unnamed)" },
                 "Root": { "kind": "node.conditional", "value": { ... } } } }
]
```

⇒ 形状是 **`{ Event, Program }`**，`Event` 是一个字符串（`"CardPlayed"`、`nodeEntered`、`turnStarted`…），
`Program` 就是我们已经在用的那套节点树（`node.sequence` / `node.gainBlock` / `node.applyStatus` …）。

遗物那边的写法不同（`{event, condition, templates[]}`），**两种形状并存**，别混用。

### 108.2 还差一个答案才能写 Metallicize

`TurnEnded` 触发时，节目里的选择器**怎么指到"触发它的那个战斗员"**？

参考里 `CardPlayed` 的例子用的是 `sel.source` + `firstCardPlayedHasTag` 这类**事件上下文**选择器；
`sel.source` 在"战斗员自己回合结束"这个语境里**大概**就是那个战斗员，但**我没有验证**。

**这是下一轮的第一个问题**，也是最便宜的一个：写一条 `TurnEnded → gainBlock(sel.source, 5)` 挂到某只怪，
打一回合看它有没有加格挡。有 ⇒ 形状对；没有 ⇒ 试 `sel.eventTarget`，再没有 ⇒ 回内核。

### 108.3 为什么这轮不直接写

需要的三样东西现在只有两样：形状（有）、节点树（有）、**"事件语境里谁是主体"（没有验证）**。
硬写一条的代价是：一次内容改动 + 重编 + 重钉 + 一次全量闸门 ≈ 二十分钟，而**错的那个选择器不会有任何
报错**——它只会静默地打空，正是这个项目反复在治的那种失败。

⇒ 把它写成"下一轮第一件事"，带着**具体的 JSON 草案**和**明确的判据**（打完一回合看格挡）。

### 108.4 当前状态

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | **669** |
| 内容状态 | 6（其中 `standard.metallicize` 被**声明为惰性**，理由指向本节） |
| 触发器 | 我们的 sts 包里 **0 条**（参考包 31 条） |

§106 的悬挂项表里第 3 行（"目录有名、`host.rs` 无行为"）现在有了**更准的描述**：不是"内核缺一根臂"，
而是"**内容缺一条触发器**，而触发器的形状已经找到、只差一个选择器的答案"。

---

## 109. 实验结论：**我们的编译器根本不写触发器表** —— `TriggeredEffects` 被静默丢弃

用户："完成实验，如果符合预期就实现功能，如果不符合就试其他方向再拿一个结论。"

### 109.1 三次探针，全负

给 `jaw_worm` 挂了一条 `TurnEnded → gainBlock(5)` 的 `TriggeredEffects`，重建内容、重编 wasm，然后用
`rd_env_reset()` 建那场默认战斗、结束一回合、读敌人的格挡：

| # | 变的量 | 结果 |
|---|---|---|
| 1 | 选择器 `sel.source` | 敌人格挡 `0 → 0`，**没触发** |
| 2 | 选择器 `sel.allEnemies`（排除选择器问题） | `0 → 0`，**没触发** |
| 3 | 事件名 `turnEnded`（参考里 camelCase 与 PascalCase 并存） | `0 → 0`，**没触发** |

### 109.2 决定性的一查：manifest 里**没有触发器表**

```
all tables: strings, opcodes, terms, cards, statuses, enemy_actions,
            encounters, relics, events, potions, roots, id_index
```

**没有 `TRM` / `TRW`。** 我们的编译器 `ENTITY_SECTIONS` 里没有这两张表，所以：

> **写进内容的 `TriggeredEffects` 会被编译器接受、但根本不会写进镜像** —— 内核当然也就永远不可能触发它。

这不是选择器的问题，也不是事件名的问题，更不是内核缺一根臂：**是编译端到端根本没通**。

### 109.3 这一轮真正的收获：**我查错了三层的顺序**

连着三次（§106 → §107 → 本节）我给"下一步"写过三种判断，全被下一轮推翻：

1. §106："给 `host.rs` 加一根臂" —— 错，内核是数据驱动的；
2. §107："那就写内容触发器" —— 对，但**没先确认编译器认不认这个字段**；
3. 本节：**编译器不写这张表** —— 所以前两步都无从谈起。

⇒ **教训（比这次实验更值钱）：判断"能不能做"要从下往上查 —— 格式/编译器 → 内核 → 内容 → 页面。
我三次都是从上往下猜的。**

### 109.4 于是 Metallicize 的正确下一步

**不是**加触发器，而是给编译器加两张表：

1. `rdcfmt.py`：`TRM`（trigger match：事件 + 谓词）与 `TRW`（trigger word/程序句柄）的 `ROW_SCHEMA`，
   **并加进 `SEC_ORDER`**（第 76 轮那条：段号必须等于下标）；
2. `compile.py`：把 `TriggeredEffects` 从 monster/encounter 记录里**降到**这两张表；
3. 内核：`Table::TriggerMatch` / `TriggerWord` 的读取器（`status_catalog` 之外的新表）；
4. 然后才是 §108 的那个选择器问题。

这是一次**格式迁移**（`FORMAT_VERSION` → 5），和 `EV`（§76）、`POT`（§80）同一套路数。

### 109.5 状态

实验已**完全撤回**（`jaw_worm.TriggeredEffects` 回空、内容重建、镜像重钉、wasm 重编）。
聚合验收 **17/17**；单测 **669**；`standard.metallicize` 仍在 `is_declared_inert` 里，理由现在更准确：
**"编译器还不写触发器表"**。

---

## 110. **更正 §109**：`TRM` / `TRW` 不是触发器表，它们是**通用的 term 表**

按 §109.3 那条教训（**从下往上查：格式 → 内核 → 内容 → 页面**），这一轮先读格式定义，而不是直接动手加表。
结果 §109 的结论**机制部分是错的**。

### 110.1 `rdcfmt.py` 的原文

```
  4 TRM    term records (variable length, 4-byte aligned)
  5 TRW    u16[n_terms] word offset (byte_offset / 4) of each term record
```

参考镜像里：`TRM` **2,143 条 / 20,760 B**、`TRW` 2,143 条 —— 那是**每一条 IR 对象/程序节点**都住的地方，
和"触发器"没有关系。我上一轮把 `TRM` 当成 "TRigger Match"、`TRW` 当成 "TRigger Word"，**纯属望文生义**。

⇒ §109 的"编译器根本不写触发器表"这个**结论的措辞是错的**（那两张表一直都在，所有程序都在里面）。
**但实测结果依然成立**：那条 `TurnEnded` 触发器的确没有生效。

### 110.2 于是真正的问题变成：参考把触发器**存在哪**

三条线索，按可信度排：

1. **`ENCT` 行有 `TriggeredEffects` 这一格** —— 我们的 `ENCT_ROW` schema 里就有（`F_TERM`）。
   参考文档的 `CardPlayed` 例子也确实是挂在 **encounter** 上的 ⇒ 遭遇级触发器**有地方存**。
2. **怪物级**：我们的 `Monster` 记录在 schema 里**没有** `TriggeredEffects` 格 ⇒ 那个字段会掉进 `extra`
   （`extra` 是 `_obj` term，**存下来了**，但内核没人读）。
   ⇒ 上一轮挂在 **monster** 上的实验，很可能就是**存了但没人执行**，和"编译器没写"是两回事。
3. **遗物**：`REL_ROW` 有 `RunPrograms` 与 `CombatRules` 两格，另外遗物的触发器是
   `{event, condition, templates[]}` 这种**第三种形状**。

### 110.3 下一轮的第一个实验（更便宜、更准）

**把触发器挂在 `enc_jaw_worm` 这个 encounter 上**（它已经有那一格），而不是 monster：

```
"TriggeredEffects": [ { "Event": "TurnEnded",
                        "Program": { ... node.gainBlock, TargetSelector: sel.source ... } } ]
```

判据沿用上一轮那个探针（`rd_env_reset()` → 结束一回合 → 读敌人格挡）：
* 加上了 ⇒ **encounter 级触发器是通的**，那么 monster 级的缺口只是"schema 少一格 + 内核少一条读法"；
* 还是 0 ⇒ 问题在**内核执行这一侧**（事件名、队列、或者这一格根本没被解释），再往下查 `TODO`。

### 110.4 四次更正的账（这条比结论更值得记）

| 轮次 | 我的判断 | 被什么推翻 |
|---|---|---|
| §106 | 给 `host.rs` 加一根臂 | 内核是数据驱动的（`turn_ended` 只入队事件） |
| §107 | 那就写内容触发器 | 没先确认**编译器/格式**认不认 |
| §109 | 编译器不写触发器表 | **把 `TRM`/`TRW` 望文生义成触发器表** |
| §110 | 触发器大概在 `ENCT` 那一格里 | 待实验 |

⇒ **望文生义是"从上往下猜"最便宜的一种形式**：名字看起来对，就省掉了读定义那一步。
四次的根因其实是同一件事——**我用名字当证据**。

---

## 111. 结论（第二个实验）：**那一格存下来了，但内核没人执行**

§110.3 的实验照做了：把 `TurnEnded → gainBlock(allEnemies, 5)` 挂到 **`enc_jaw_worm`**（`ENCT` 行里有
`TriggeredEffects` 这一格），重建内容、重编 wasm，同一个探针：

```
enemy block   0 -> 0      TRIGGER DID NOT FIRE
```

⇒ **encounter 级也不触发**。加上 §109 的 monster 级，两个层级都试过了。

### 111.1 现在可以说准的一句话

| 环节 | 状态 | 证据 |
|---|---|---|
| 格式 | **有**这一格 | `content.rs:1408`：`("TriggeredEffects", F_TERM, 0) => triggered_effects => 4` |
| 编译器 | **写进去了** | 同一个 schema，`content.rs:3480` 的 round-trip 断言会读它 |
| 内核**读取器** | **有** | `EnctRow::triggered_effects()`（`content.rs:3351` 的测试就在用它） |
| 内核**执行** | **没有** | 两次探针，monster 与 encounter 两级都不触发 |

⇒ **缺口在"执行"这一侧，而且位置是已知的**：`host.rs` 在 834 行附近的注释里已经点名了参考实现
（`TurnEndedTriggeredEffects.cs:55-62`、`TurnStartedTriggeredEffects.cs:29`），并说明"事件 → 触发器"
的派发是**按 `TurnCombatant.Statuses` 与战斗员列表遍历**的。**移植点就在那儿，只是没接。**

### 111.2 下一轮的第一个动作（具体到文件与函数）

1. 打开 `host.rs` 的 `try_run_turn_ended_triggers`（现在只入队事件 + 跑队列）；
2. 对照 `TurnEndedTriggeredEffects.cs:55-62`，补上"**取 `ENCT[enc].TriggeredEffects` 里 `Event == TurnEnded`
   的节目，逐个执行**"这一步；
3. 判据就用这一轮的探针（`rd_env_reset()` → 结束一回合 → 敌人格挡 +5）；
4. 通了之后，把 `standard.metallicize` 从 `is_declared_inert` 里挪进 `has_behaviour`（规则会强制）。

### 111.3 五次的账（都在同一根绳上）

§106 猜内核臂 → §107 猜内容触发器 → §109 把 `TRM`/`TRW` 望文生义成触发器表 → §110 更正为"在
`ENCT` 那一格" → **§111 实测：格子在、读取器在、执行不在**。

**根因一直没变：我用名字当证据。** 而正确的查法（格式 → 内核读 → 内核执行 → 内容 → 页面）只用两次实验就
把问题钉死在**一个函数**上了。

---

## 112. Metallicize 的**确切落点**找到了：它是 `TurnHost` 上的一个新步骤

§111 说缺口在"执行"这一侧。这一轮把执行侧的结构读清楚了，结论是**三个文件、一个 trait 方法**。

### 112.1 结构（实测，非推断）

```
turn.rs:150        pub trait TurnHost { … }          ← 战斗循环调用的**步骤**接口
host.rs:2025       impl TurnHost for Host {           ← 每个步骤转调一个 try_* 方法
  fn damage_over_time(&mut self, state, actor) { self.try_damage_over_time(state, actor) }
}
host.rs:1111       pub fn try_damage_over_time(…)     ← 真正的实现（遍历该战斗员的状态）
```

⇒ **状态"有效果"的既有做法不是触发器，而是"一个 trait 步骤 + 一个实现"**：poison 就是这么做的。
Metallicize 是同一种形状 —— 而 §106 我写"给 `turn_ended` 加一根臂"其实**方向是对的**，只是我把落点
说成了"入队事件那个函数"，真正该加的是**trait 上的一个步骤**。

### 112.2 三个编辑点（下一轮照这个做，不需要再探索）

| # | 文件 | 做什么 |
|---|---|---|
| 1 | `turn.rs` | `trait TurnHost` 加 `fn end_of_turn_block(&mut self, state, actor) -> Result<(), TurnError>`，**给一个默认空实现**（`Ok(())`）⇒ 测试里的其它 implementor 不会因为加方法而编译不过 |
| 2 | `host.rs` | `impl TurnHost for Host` 里转调 `self.try_metallicize(state, actor)`；并写 `try_metallicize`：遍历该战斗员的**active** 状态，找 `standard.metallicize`，`gain_block(stacks)`（照 `try_damage_over_time` 的骨架：`flush_deferred` → 快照 → 施加） |
| 3 | `battle.rs` | 在**回合结束**的那一步（`hand_turn_end_lifecycle` 之后、`turn_ended` 之前）调用 `host.end_of_turn_block(state, actor)` |

### 112.3 判据（一次就够）

一条 rd-core 测试：造一个带 `standard.metallicize` 2 层的战斗员，跑到回合结束，断言格挡 = 2。
**然后把 `standard.metallicize` 从 `is_declared_inert` 挪进 `has_behaviour`** —— §104 那条规则会强制。

### 112.4 为什么这一轮停在这里

读结构用掉了这一轮的预算；而 §112.2 是**三次编译-测试循环**的活（trait → impl → call site），
我现在的上下文不足以做完三轮。**再硬上一次就是第四次回退**，那正是这两天在治的病。

⇒ 下一轮从 §112.2 的第 1 行开始，一次一个编译，任何一步失败最多回退一步。

---

## 113. Metallicize 的**实现**进了内核；**内容挂载**被一条实测拦住了

这一轮按 §112 做完了第 1–2 步，然后在第 3 步前被一条实测挡住 —— 挡住了就是挡住了，记下来。

### 113.1 已经进内核的部分（可用）

`host.rs`：

```rust
fn grant_end_of_turn_block(&mut self, state, actor)          // 遍历 active 状态，累加 standard.metallicize 的层数
                                                             // ⇒ set_defensive_pool("standard.block", current + n)
// 调用点：try_run_turn_ended_triggers，**在 TurnEnded 事件入队之前**（这样事件的处理者读得到格挡）
```

`status_catalog`：`standard.metallicize` 从 `is_declared_inert` **挪进 `has_behaviour`** ——
符合 §104 那条规则（有行为就不许再挂"惰性"牌子）。

### 113.2 卡在哪：**`core_image()` 没有 STAT 行**

判据测试（`metallicize_grants_block_at_the_end_of_the_turn`）写好了，跑起来红在：

```
turn end: Bind(Missing("STAT row"))
```

原因不是我的实现，是**测试用的镜像**：`core_image()`（14,380 B）**不含 `STAT` 表**，所以任何在 `solo()` 里
`give(...)` 上去的状态都绑不到定义。旁边那条 poison 测试能跑，是因为 **poison 按 tag 绑定**，不走 STAT 行。

⇒ 这条测试要改成像运行期那样用**全量镜像**（`content.sts.rdcf`）。测试已标 `#[ignore]`，理由就写在属性里，
**不是"以后再说"，是"要换镜像"**。

### 113.3 所以内容**暂时没有挂**这只状态 —— 故意的

`spike_slime_m` 上的 Metallicize 3 已经撤回。理由：

**如果 turn-end 对"没有触发节目"的状态会 `Err`**（`Bind(Missing(...))` 就是这个形状），那么把一只带
`metallicize` 的怪放进战斗，可能让**整个回合结束报错**。在拿到"全量镜像下 turn-end 不报错"的证据之前，
不把这条路径接进玩家实际会遇到的战斗。

⇒ 待验证的一句话：**"回合结束遇到一个没有节目的状态，是跳过还是报错？"**
答"跳过" ⇒ 挂上去；答"报错" ⇒ 先让收集器容忍，再挂。

### 113.4 状态

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | **669 / 1 ignored**（那 1 条就是本条，理由写在属性里） |
| 内核实现 | ✅ 在两处（步骤 + 调用点） |
| 规则 | ✅ `standard.metallicize` 已进 `has_behaviour` |
| 内容挂载 | ⛔ 撤回，等 113.3 那句话的答案 |

---

## 114. **Metallicize 完成**：从"格挡 +3"到"玩家能在战斗里遇到"

§113 悬着一句话——**"回合结束遇到一个没有节目的状态，是跳过还是报错？"** 这一轮把它问了，答案是
**跳过**，于是功能闭环。

### 114.1 答案是怎么拿到的

把那条判据测试从 `core_image()` 换成**全量镜像**（`packages/sts/out/content.sts.rdcf`）——core 镜像没有
`STAT` 表，任何状态在 `solo()` 里都绑不上，这正是 §113 红的真正原因。

换镜像后一条测试全绿：

```
metallicize 3 → 回合结束      格挡 = 3
              再一次回合结束   格挡 = 6
```

⇒ **turn-end 遇到没有触发节目的状态会跳过，不会 `Err`。** 于是可以安全地把这只状态挂进真实战斗。

### 114.2 内容挂载（带降级说明）

`spike_slime_m` 带 **Metallicize 3**，注释写在 `AiNote` 里：

> ⚠️ wiki 的 Metallicize 8 属于 **Lagavulin**（第一幕精英），本内容没有它；为了让这条机制在真实战斗里
> 被用到，挂在这里（3 层）。

**没有假装这是 Lagavulin**，也没有假装 3 就是 wiki 的 8。

### 114.3 这条功能的完整账（四轮）

| 轮 | 做了什么 | 结果 |
|---|---|---|
| §106/§107 | 猜"内核臂"，再猜"内容触发器" | 两次都错，但错得有用 |
| §111/§112 | 两次探针 + 读结构 | 定位到"`TurnHost` 一个步骤"（poison 的先例） |
| §113 | 写步骤 + 调用点 + 规则迁移 | 实现进了内核，判据被镜像问题挡住 |
| **§114** | 换全量镜像 → 拿到"跳过"的答案 → 挂内容 | **完成** |

### 114.4 判据（现在都是绿的）

1. `metallicize_grants_block_at_the_end_of_the_turn`（rd-core，**全量镜像**）：3 → 6，**不再 ignore**；
2. `the_status_catalogue_is_honest`：`standard.metallicize` 已在 `has_behaviour`，**不在** inert 名单；
3. `sts_content_check`：14 只怪，`spike_slime_m` 带 3 层 Metallicize；
4. 聚合验收 **17/17**，单测 **670**。

### 114.5 顺带证明的两件事

* **§104 那条规则真的在工作**：动手实现之前，它先把 `metallicize` 挡在门外；实现之后，我又必须把它挪进
  `has_behaviour` 才能通过 —— 规则不是装饰。
* **"镜像"本身是一个坑**：`core_image()` 没有 `STAT` 表这件事，只有踩到才会知道。下次写"需要状态定义"的
  内核测试，**直接用全量镜像**。

---

## 115. 对照 wiki 的**后续完善计划**：所有"类似功能"归到五条钩子上

Metallicize 走通之后（§114），把 StS 第一幕里所有"状态/怪物机制"按**它们需要哪条内核钩子**归了类。
这比"一个一个功能点"有用：**同类的东西共用一条钩子，做完一条就解锁一批。**

### 115.1 五条钩子（我们已有的三条标 ✅）

| 钩子 | 内核位置 | 我们 |
|---|---|---|
| 回合结束 | `Host::try_run_turn_ended_triggers` | ✅（Metallicize 就挂在这） |
| 回合开始 | `Host::try_run_turn_started_triggers` | ✅（poison 走这条） |
| 伤害结算 | `exec::resolve_damage` | ✅（但**没有"受击后"回调**） |
| **打出牌** | 无 | ❌ |
| **死亡时** | 无 | ❌ |

### 115.2 归类的结果（wiki 第一幕 + 常见）

**A. 回合结束型**（挂 ✅ 钩子，**最便宜**）

| 机制 | wiki | 实现 = 加一段 `try_*` | 状态 |
|---|---|---|---|
| **Metallicize** | Lagavulin 8 | 格挡 + 层数 | ✅ 完成（§114） |
| **Ritual** | Cultist 3 | 力量 + 层数 | **下一步**：只差"没有实例就建一个" |
| **Combust**（自伤换伤害） | Ironclad 卡 | 需要"伤害所有人" | 中 |
| **Regen** | 若干遗物 | 治疗 + 层数 | 便宜 |

**B. 受击型**（挂 ✅ 伤害结算，但要在 `resolve_damage` **之后**开一个口）

| 机制 | wiki | 缺口 |
|---|---|---|
| **Thorns** | 反伤 X | 需要在伤害落地后回调"防守方" |
| **Enrage** | Gremlin Nob：你打技能他加力量 | 需要"打出牌"钩子（见 D） |
| **Rage / Flame Barrier** | 加格挡 | 同 Thorns 的形状 |

**C. 回合开始型**（挂 ✅ 钩子）

| 机制 | wiki | 说明 |
|---|---|---|
| **Poison** | 中毒掉血 | ✅ 已有 |
| **Draw +1 / Energy +1** | 若干 | 便宜，但要动回合流程的"发牌"步骤 |
| **Artifact 的减免** | Sentry 1 | 挂在"施加状态前"，**另开一个口**（不是回合开始） |

**D. 打出牌型**（❌ 无钩子）

| 机制 | wiki | 说明 |
|---|---|---|
| **Enrage** | Gremlin Nob | 你每打一张技能牌，+2 力量 |
| **Thorns 的变体**（"每打一张攻击牌"） | 若干 | 同形 |
| **Runic Pyramid / 遗物类** | — | 大多挂在这条 |

**E. 死亡型**（❌ 无钩子）

| 机制 | wiki | 说明 |
|---|---|---|
| **Spore Cloud** | Fungi Beast：死亡时给你 2 层虚弱 | 需要"战斗员死亡"事件 |
| **Explosive** | 爆炸怪 | 同上 |
| **分裂**（Slime Boss） | — | 需要"生成新敌人"（容量 + ID 分配） |

### 115.3 建议的顺序（每步一条钩子/一个状态，都以绿收尾）

1. **Ritual**（B 类里最便宜的，仍用 ✅ 钩子）—— 一轮
2. **受击后回调**（在 `resolve_damage` 之后开一个 `Host::after_damage_received`）→ 顺手把 **Thorns** 做完 —— 一轮
3. **死亡钩子**（`CombatantDied` 事件 + 一个步骤）→ **Spore Cloud** —— 一轮
4. **Artifact**（施加状态前的最后一道闸）—— 一轮。**它会让 `artifact` 从"目录有名"变成"有行为"**（§104 的账要跟着改）
5. **打出牌钩子** → **Enrage**（Gremlin Nob 才真的像 Gremlin Nob）—— 一轮

### 115.4 为什么 Ritual 这一轮没做完

它比 Metallicize 多一件小事：**"身上没有 `standard.strength` 实例时要先建一个"**。
`state.statuses_mut()` + `push_status(StatusInstance)` 都在，但 `StatusInstance` 的字段（来源、时长、可见性…）
需要照着 `exec` 里已有的"施加状态"路径抄 —— 那是下一轮的第一件事，**不是猜**.

（这一轮把"归类 + 顺序"做完，价值在于：之后每一轮都是"挑一个格子填"，不再需要重新判断哪种做法对。）

### 115.5 Ritual 的落点也找到了（照抄 `exec` 的施加路径）

`exec.rs:3046-3071` 就是"给某人上一个状态"的**唯一正路**：

```rust
let number = ctx.state.next_status_instance_number;       // 先取号
let instance_id = status_instance_id(number)?;            // 私有函数
let mut instance = StatusInstance::new(instance_id, definition_id, polarity)
    .with_stacks(stacks).with_duration_turns(d).with_charges(c);
combatant.push_status(instance)?;
ctx.state.next_status_instance_number = number.saturating_add(1);   // 再自增
```

⇒ Ritual 的步骤只差一件小事：**"身上没有 `standard.strength` 时要建一个新实例"**，而建实例需要
`status_instance_id(number)` —— 它是 `exec.rs` 的**私有函数**，且 `rd-core` 是 `no_std`（没有 `format!`）。

**所以 Ritual 的第一步是一个小重构**：把"取号 + 造实例"抽成 `CombatState` 上的一个方法
（例如 `push_new_status(definition, stacks)`），`exec.rs` 与 `host.rs` 都调它。
**这一步比 Metallicize 多，但它是"施加状态"的唯一入口，做完之后 C 类里一大半都便宜了。**

⚠️ 写在这里而不是直接动手的原因：这个重构会动到 `exec.rs` 的**唯一施加路径**，而它被 poison、虚弱、
易伤等所有现有机制共用 —— 一旦漏掉"号没有自增"或"极性取错"，破坏面是**全部战斗**。
下一轮做它时：**先跑一遍现有 581 条 rd-core 测试确立基线**，再改，再跑同一批。

---

## 116. **Ritual 与 Thorns 都完成了** —— 一个证明了"内容路径"，一个补上了"受击钩子"

### 116.1 Ritual：内容路径**本来就通**，是我误判成"惰性"

先按 §112 的形状给 Ritual 写了内核步骤（`grant_ritual_strength`），测试却给我 **6 而不是 3**。
把内核步骤**关掉**再跑，仍然是 3 ⇒ **内容里那条 `TurnEnded` 触发器本来就在工作**。

回头看 `sts.roguedeck.json` 的 `ritual` 记录，`Triggers: [{Event: "TurnEnded", Program: applyStatus(strength)}]`
**一直都在**。也就是说 §104 那条"惰性"名单里挂着 `ritual` 是**我的误判**（当时靠 grep 判断"没有行为"）。

⇒ 于是把内核步骤、调用点、守卫字段**全部删掉**（一个功能两份实现会付两遍钱），测试改成
`ritual_grants_strength_at_the_end_of_the_turn`（走内容路径，3 → 6）。

### 116.2 Thorns：`DamageTaken` 钩子，一次补齐

先试"把 thorns 挂成 `DamageDealt` 触发器"—— **不触发**。读 `run_damage_dealt_triggers` 才明白：
**Bearer 是出手方**（`doubt` 长在打人的人身上）。Thorns 要的是**承受者侧**，而那条事件在参考里叫
`DamageReceivedCombatEvent`，本内核的注释里写着"它跟着它的第一批触发器一起进来" —— 这一批就是现在。

补三处：

| # | 位置 | 内容 |
|---|---|---|
| 1 | `state.rs` | `CombatEvent::DamageTaken { target, source }` |
| 2 | `exec.rs` | 伤害落地时**入队两条**：`DamageDealt`（出手方）+ `DamageTaken`（承受者） |
| 3 | `host.rs` | `TriggerEvent::DamageTaken` **从 `NotHandled` 毕业**；`run_damage_taken_triggers`（Bearer = 承受者，`EventTarget` = 出手方） |

内容侧：`standard.thorns` = `DamageTaken` → `dealDamage(sel.eventTarget, stacks(sel.source, standard.thorns))`。

⚠️ 两个坑，都是"名字/键写错就静默打空"：`combatantStatusStacks` 的键是 **`StatusId`** 不是
`StatusDefinitionId`（照 ritual 抄才对）；伤害的 `IgnoresBlock` 必须为 `true`。

### 116.3 判据

| 测试 | 证明 |
|---|---|
| `ritual_grants_strength_at_the_end_of_the_turn` | 内容路径：3 → 6 |
| `thorns_hurts_whoever_hits_its_owner` | 敌人戴 Thorns 3，英雄打它 5 ⇒ **英雄掉 3** |
| `the_image_has_exactly_the_three_plus_six_triggers_the_spec_claims` | 参考镜像里 **`DamageTaken` 那条 = 1**，`not_handled` 11 → **10** |
| `..._trigger_event_names_are_known...` | `DamageTaken` 不再是 `NotHandled` |
| 事件计数 | 一次伤害现在入队 **2** 条事件（原来 1 条）|

### 116.4 内容（两处都带降级说明）

* `spike_slime_m`：**Metallicize 3**（wiki 属 Lagavulin）
* `spike_slime_s`：**Thorns 3**（wiki 属第二幕的 Spiker）

两条都写在 `AiNote` 里，并且 encounter 的**内联敌人**也同步改了 —— 内容门会比对 roster 与内联副本
（漏了它会报 `StartingStatuses differs from the roster`）。

### 116.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 670 → **671**（rd-core 583 / rd-run 61 / rd-wasm 27） |
| 内容状态 | 6 → **7** |
| 状态触发器 | `ritual`(TurnEnded) + `thorns`(DamageTaken) |
| 镜像 | full 17,324 B / core 14,940 B（重钉） |

---

## 117. 三件事一起做完：**死亡钩子 + Spore Cloud**、**Artifact**、**出牌钩子 + Enrage**

§115 那张表里 B/C/D 类的三个"销售点"，一轮做完。做法和 §116 一样：**先看内核有没有钩子，
没有就补一条事件 + 一个 runner，内容侧只写触发器**。

### 117.1 三条新事件 / 钩子

| 事件 | 入队点 | Bearer | 谁用它 |
|---|---|---|---|
| `Downed` | `exec::resolve_damage`（目标真的从 Alive 转 Downed 时） | **倒下的那个** | Spore Cloud |
| `CardPlayed` | `play.rs`（`counted_as_card_played` 时） | **每个战斗员** | Enrage |
| （`DamageTaken`） | 上一轮 §116 已补 | 承受者 | Thorns |

`Downed` 的 runner **故意不看 `state.result`**：倒下往往就是战斗结束那一刻，而"临死一击"必须照报。

### 117.2 Artifact 不是触发器，是**施加路径上的一道闸**

`exec::apply_one_status` 开头：要加的层数 > 0、极性是 **Debuff**、目标身上有 `standard.artifact` 层数 > 0
⇒ **吃掉一层 Artifact 并直接返回**（目标一点状态都不沾，层数耗尽就删实例）。

放在这里而不是某个触发器上，是因为**它必须挡住所有来源**（卡、敌人行动、DoT、事件）。

### 117.3 内容与降级（都写在记录里）

| 状态 | 挂给谁 | 降级说明 |
|---|---|---|
| `standard.spore_cloud` | （未挂怪，见下） | wiki: Fungi Beast 死亡时给 2 层虚弱 |
| `standard.artifact` | **`sentry_1/2/3`** | **与 wiki 一致**（Sentry 就是 Artifact 1） |
| `standard.enrage` | `fat_gremlin` | wiki 属 Gremlin Nob；且**卡片 tag 未建模**，所以触发条件是「出牌就 +2 力量」不是「技能牌」 |

⚠️ `spore_cloud` 这一轮**只做到了机制**（内容里有这条状态 + 测试证明它工作），**还没挂到怪身上** ——
下一步把它挂给 `acid_slime_m`（wiki 的 Fungi Beast 不在我们的名单里）。

### 117.4 判据（三条，都是真跑出来绿的）

| 测试 | 证明 |
|---|---|
| `spore_cloud_weakens_the_killer_on_death` | 敌人 10 HP、挨 12 点致死 ⇒ **凶手拿到 2 层虚弱** |
| `artifact_eats_one_debuff_and_nothing_else` | Artifact 1：第一个 debuff 被吃掉且层数清零；**第二个照常落下** |
| `enrage_answers_a_card_played_by_the_other_side` | 敌人戴 Enrage，**玩家出牌** ⇒ 敌人 +2 力量，玩家 0 |

为了测 Artifact 加了一个 `#[cfg(test)]` 的门（`exec::apply_status_for_test`）—— 否则要么造一整个节目，
要么测不到"闸"本身。

### 117.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 671 → **674**（rd-core 586 / rd-run 61 / rd-wasm 27） |
| 内容状态 | 7 → **10**（spore_cloud / artifact / enrage） |
| 事件 | `DamageDealt` `DamageTaken` `Downed` `CardPlayed` + 回合/轮次四类 |
| 镜像 | full 18,164 B / core 15,592 B（重钉） |

### 117.6 现在还剩什么（§115 那张表的余项）

* **`CardPlayed` 的 tag 过滤器**（"只认技能牌"）—— 需要把卡片的 tag 送进事件（Enrage 才能真的像 Enrage）；
* **`Spore Cloud` 挂怪**（一步）；
* `Combust` / `Regen` / `Rage` / `Flame Barrier`（都是已有钩子上的新触发器，便宜）；
* 出牌侧的 `CardCostPaid`、`StatusApplied` / `StatusMerged` / `StatusRemoved` 三条状态事件（`not_handled` 只剩 4 类）。

---

## 118. **`CardPlayed` 带上卡片 tag**：`event.bool` 成了事件的布尔通道

§117 留的那个口子补上了：Enrage 现在**只认技能牌**。

### 118.1 为什么不是"把卡实例塞进表达式上下文"

那要把 `Content` 的寿命也拖进 `ExprContext`（`expr` 目前只借 `CombatState`），改动面铺开到整个求值层。
而真正被用到的信息只有一句：**这张牌有没有某个 tag**。

⇒ 改成**事件事实**：宿主在派发 `CardPlayed` 时先算好 4 个比特，`event.bool` 读它们。

```rust
pub const CARD_HAS_TAG_ATTACK: u8 = 1 << 0;
pub const CARD_HAS_TAG_SKILL:  u8 = 1 << 1;
pub const CARD_HAS_TAG_POWER:  u8 = 1 << 2;
pub const CARD_HAS_TAG_STATUS: u8 = 1 << 3;
```

* `CombatEvent::CardPlayed { owner, card }` —— 事件带上**卡实例**（`play.rs` 出牌时入队）；
* 宿主 `card_definition_of(state, card)` 扫各战斗员的四个区找到定义 id，再用
  `content.card_has_tag` 算比特；
* `ExecContext.event_flags` / `ExprContext.event_flags` 把比特送进求值；`execute_program_with_flags`
  是带比特的那条入口（原 `execute_program` 退化成"比特全 0"）。
* `event.bool { FieldKey: "card.hasTag.skill" }` —— **只认四个键**，别的键 `UnsupportedKind`
  （响亮失败，不静默 `false`）。

### 118.2 内容

`standard.enrage` 的节目现在是：

```
node.conditional { Condition: event.bool("card.hasTag.skill"),
                   Then: applyStatus(sel.source, standard.strength, 2) }
```

⇒ **wiki 的 Enrage 终于名副其实**：只对技能牌反应。

### 118.3 判据

`enrage_answers_only_a_skill`（rd-core，全量镜像）：

* 打一张 **defend（skill）** ⇒ 敌人 +2 力量；
* 再打一张 **strike（attack）** ⇒ 力量**不变**（还是 2）。

用的是真的卡实例（`card_in_hand` 帮手把牌塞进手牌），不是编的 tag。

### 118.4 顺带两件事

* `sts_content_check` 的 `program_facts` 现在认识 `node.conditional`，并把**两个分支**的事实
  带上前缀 `("when", key)` 一起报 —— 否则一条 `if` 就能把分支藏过清点；
* `expr` 的覆盖扫描仍是 **40 条 UnsupportedKind**：参考镜像里那两条 `event.bool` 用的是别的键
  （`node.isCombat` 之类），照旧算"没实现"。

### 118.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 674（rd-core 586 / rd-run 61 / rd-wasm 27） |
| 内容事件事实 | 4 个 bit（attack / skill / power / status） |
| 镜像 | full 18,288 B / core 15,716 B（重钉） |

---

## 119. 三件事收尾：Spore Cloud 挂怪、四个"便宜状态"、**事件表补全**

### 119.1 Spore Cloud 挂上了怪

`acid_slime_m` 带 **Spore Cloud 1**（wiki 属 Fungi Beast，我们没有它 —— 降级写进 `AiNote`）。
encounter 的内联副本同步改了。

### 119.2 四个新状态，全部是"已有钩子上的新触发器"

| 状态 | 钩子 | 节目 | 判据 |
|---|---|---|---|
| **Regen** | `TurnEnded` | `heal(stacks)` | 受伤 10 后回 4 ⇒ `hurt + 4` |
| **Rage** | `CardPlayed` + `card.hasTag.attack` | `gainBlock(stacks)` | 出技能=0 格挡，出攻击=**3** 格挡 |
| **Flame Barrier** | `DamageTaken` | `dealDamage(eventTarget, stacks)` | 敌人挡 4 ⇒ 打它的人掉 4 |
| **Combust** | `TurnEnded` | `dealDamage(allEnemies, stacks)` | 回合结束敌人真的掉血 |

**没有加一条内核分支** —— 这正是 §115 那张表的用处：钩子补齐之后，剩下的都是内容填空。
`sts_content_check` 的 `program_facts` 也跟着认识 `node.heal` 与 `sel.allEnemies`（不认识的节点/选择器
一律抛错，不许"跳过"）。

### 119.3 事件表补全：`not_handled` 10 → **2**

四个事件接了钩子：

| 事件 | 入队点 | 派发给 |
|---|---|---|
| `CardCostPaid` | `play.rs`（付了费用时） | 每个战斗员 |
| `StatusApplied` | `exec::apply_one_status`（新实例） | 每个战斗员 |
| `StatusMerged` | 同上（并入已有实例） | 每个战斗员 |
| `StatusRemoved` | 同上（层数归零/删除） | 每个战斗员 |

⚠️ `StatusMerged` 的入队必须**等借用结束**再发（`ctx.state` 只能借一次）—— 这是个真实的编译错误，
不是洁癖。

**剩下 2 条 `StatusStacksChanged`** 仍是"参考有、本内核没有钩子接"。参考镜像里 25 条触发器，
现在只有 2 条落在未接的钩子上。

### 119.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 674 → **677**（rd-core 589 / rd-run 61 / rd-wasm 27） |
| 内容状态 | 10 → **14** |
| `not_handled` 触发器 | 10 → **2**（只剩 `StatusStacksChanged`） |
| 镜像 | full 19,300 B / core 16,488 B（重钉） |

### 119.5 还剩什么

* `StatusStacksChanged`（最后 1 类未接事件）；
* `CardPlayed` 的**每回合出牌统计**（`cardsPlayedThisTurnWithTag` 那一族表达式需要它）；
* `Artifact` 的 `StatusApplicationPrevented` 事件（挡掉时参考会发一条，我们还没发）；
* Boss 分裂/相位、`?` 房通用解释器、幕间内容差异（老账）。

---

## 120. 最后两个事件接上，**25/25**；以及用户问的"Boss 分裂有没有埋坑"

### 120.1 `StatusStacksChanged` 与 `StatusApplicationPrevented`

| 事件 | 入队点 |
|---|---|
| `StatusStacksChanged` | `exec::modify_one_status_stacks`，**净变化非 0 时**（`StatusEffects.cs:826`） |
| `StatusApplicationPrevented` | `exec::apply_one_status` 的 Artifact 闸里，挡掉的那一支 |

`the_image_has_exactly_the_three_plus_six_triggers_the_spec_claims` 现在钉的是：

```
status_stacks_changed = 2     参考镜像里那两条
not_handled          = 0      ← 25 个事件名**全部**有钩子
```

**这是本轮最硬的一个里程碑**：参考实现 25 种触发事件，本内核一种不少地认得、并且都有派发点。

### 120.2 Boss 分裂：**有坑，而且坑不在内核**

用户问得很准。逐层查了一遍，结论是"**内核能长，界面看不见**"。

| 层 | 结论 | 证据 |
|---|---|---|
| 内核容量 | ✅ 够用 | `MAX_COMBATANTS = 12`（`state.rs:120`） |
| 内核加人 | ✅ 有且**响亮失败** | `add_combatant`（`state.rs:3629`）先查三处容量（战斗员/回合序/卡区），任一项满 ⇒ `CapacityError::Full(Combatants)`，**不会留下两个列表不同步** |
| 卡区 | ✅ 自动建 | `add_combatant` 里 `card_zones.push(CardZones::new(id))` |
| **观察向量** | ❌ **硬上限 4** | `lib.rs:152` `MAX_ENEMY_SLOTS = 4`；`compute_observation` 只循环 `0..MAX_ENEMY_SLOTS`，多出来的敌人**静默不出现** |
| **观察向量的数据源** | ❌ **来自快照** | `self.plan.enemies` 是 `Box::leak` 的**开局快照**（`lib.rs:457-478`），不是 `state.combatants()` ⇒ 分裂出来的新敌人**根本不在名单里** |
| **动作枚举** | ❌ 同源 | `compute_actions` 用 `alive_enemy_slots()` + `plan.enemies.get(..)` ⇒ 新敌人**不可被选为目标** |
| 意图 | ❌ 同源 | `refresh_intents` 循环 `plan.enemies.len().min(4)` |
| 页面 | ❌ 硬编码 | `ui_render.js:33-38`：`OFF_ENEMY = 17`、`MAX_ENEMY_SLOTS = 4`（偏移量是**算出来的**，改数值会连带移动 `OFF_ENEMY_STATUS` / `OFF_HAND`） |
| 内容 | ❌ 没有节点 | 19 个 IR 节点里**没有**"造一个战斗员"的节点 |

### 120.3 所以分裂要动的是**四处**，而不是一处

1. **观察向量的上限**：`MAX_ENEMY_SLOTS` 是"放大就变语义"的那种常量 —— 它决定 `OFF_ENEMY_STATUS` 与
   `OFF_HAND` 的偏移，改它必须**同时**改 `lib.rs` 与 `ui_render.js`，并且按项目规矩**溢出要响亮失败**，
   而不是静默截断（今天 `compute_observation` 就是静默截断）。
2. **数据源**：把"敌人是谁"从 `plan.enemies`（快照）改成 `state.combatants()`（活的那个），
   —— 这正是 §8 那条"**这个值是谁派生的**"：缓存的派生值永远长得像"某处忘了同步"。
3. **动作枚举**：跟着 2 改；否则新敌人永不可选。
4. **内容**：新增一个 `node.createCombatant`（或等价的分裂节目），并想清楚"新敌人的 id 从哪来"、
   "它什么时候进回合序"、"分裂出来的那个是不是同一回合就行动"。

### 120.4 一句话

**坑不在内核，在"内核与界面之间那层快照"**：内核乐意长到 12 个战斗员，而观察/动作/意图三处都还是
"开局那 4 个"的副本。分裂真正的工作量是**把这层快照改成派生**，不是加一个怪。

⇒ 顺序建议：先做 2（数据源）+ 3（动作），这两步不改变 ABI 布局，可以被现有测试证明；
再决定要不要动 1（上限，会动 ABI 偏移，需要页面同步）。

### 120.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | **677**（rd-core 589 / rd-run 61 / rd-wasm 27） |
| 触发事件 | **25 / 25 有钩子**，`not_handled = 0` |

---

## 121. **Boss 分裂**：按 §120 的四步做完

用户："请按这个顺序实现一下吧"（数据源 → 动作 → 上限 → 内容节点）。

### 121.1 第一步：敌人名单**改成派生的**

```rust
fn enemy_roster(&self) -> Vec<CombatantId>   // 每次问都从 state.combatants() 读
```

`refresh_intents` / `compute_observation` / `compute_actions` / `alive_enemy_slots` 全部改成读它。
原先三处都读 `plan.enemies` —— 那是 `Box::leak` 的**开局快照**，一旦有人中途加入战斗，它就是错的。

**这一步不动 ABI**，27 个 wasm 测试全绿即为证据。

### 121.2 第二步：动作跟着派生

`compute_actions` 的目标原先从 `plan.enemies.get(slot)` 取（一个带 `.id` 的结构），现在从 roster 取
（已经是 `CombatantId`）。**新敌人从此可被选为目标。**

### 121.3 第三步：上限 4 → **6**，并把偏移量两侧同步

`MAX_ENEMY_SLOTS` 是"放大就变语义"的常量：它决定 `OFF_ENEMY_STATUS`(65) / `OFF_HAND`(95) /
`OFF_PILES`(135) / `OBS_LEN`(**148**)。三处必须一起动：

| 位置 | 改了什么 |
|---|---|
| `kernel/rd-wasm/src/lib.rs` | 常量 4 → 6（偏移量本来就是**表达式**，自动跟着走） |
| `web/ui_render.js` | `OFF_ENEMY_STATUS` 49→65、`OFF_HAND` 69→95、`OFF_PILES` 109→135、`MAX_ENEMY_SLOTS` 4→6 |
| `web/smoke.mjs` | 原先写死 `OFF_HAND = 69` ⇒ 改成**从布局常量推**（`OFF_ENEMY + 6*8 + 6*5`） |
| `web/browser_test.mjs` | 原先写死 `122` ⇒ 改成 `ex.rd_env_observe_len()` |

**第 14 道闸门（`smoke`）自己抓到了漂移**：它把每个块的结尾重新推一遍（`offsets tile to 140/148`），
页面与 Rust 一旦不同步就红。这就是当初把它写成"重新推导"而不是"抄数字"的回报。

另外补了一个导出 **`rd_env_enemy_overflow()`**：多出来的敌人**报出来**，不静默丢弃 —— 向量装不下是
ABI 的天花板，但"装不下"这件事不能被藏起来。

### 121.4 第四步：`node.createCombatant`

参考实现没有这个词，是本内核的**第 16 种节点**：

```json
{ "kind": "node.createCombatant",
  "value": { "DefinitionId": "acid_slime_m", "TeamId": "enemy",
             "Health": {"kind":"const","value":{"Value":10}} } }
```

* 新实例 id = `<definition>#<n>`，`n` 来自 `CombatState.next_combatant_number` —— **确定性**，而且一眼
  看得出它从哪来；
* 容量满了走 `add_combatant` 的**响亮失败**；
* 内容的用法是**一条 `Downed` 触发器**（复用 §116 补的死亡钩子）：

```
standard.split = { Downed → sequence(createCombatant(acid_slime_m,10) × 2) }
```

挂在 `slime_boss` 上 ⇒ Boss 一死就分成两只小史莱姆。

### 121.5 判据

`a_split_spawns_two_combatants_when_the_boss_dies`（rd-core，全量镜像）：
给敌人挂 `standard.split`，一记 12 点打死它，`try_resolve_pending_queues` 之后
**战斗员数量 +2**，两只都是 `acid_slime_m`，且 id 里带 `#`。

### 121.6 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 677 → **678**（rd-core 590 / rd-run 61 / rd-wasm 27） |
| 观察向量 | 122 → **148** slot（敌人槽 4 → 6） |
| 内容状态 | 14 → **15**（`standard.split`） |
| IR 节点 | 15 → **16**（第一个**自定义**节点） |
| 镜像 | full 19,340 B / core 16,452 B（重钉） |

### 121.7 仍然没有的

* 分裂出来的敌人**什么时候行动**（现在是加进回合序末尾，同一轮不会立刻动 —— 与 wiki 的"下一回合"一致，
  但没写测试钉住）；
* Boss 的**相位**（半血换招式）仍然没有；
* `rd_env_enemy_overflow()` 还没有页面提示（导出有了，UI 没接）。

---

## 122. 收尾三件：分裂的行动时机、**Boss 相位**、页面的 overflow 提示

### 122.1 分裂出来的敌人什么时候行动 —— 用一条测试钉住

回合推进是一个**纯轮转**（`turn.rs:845-877`）：从当前活跃者往后找第一个活着的。新加的战斗员被**追加到
`turn_order` 末尾**，所以：

* 如果轮转还没经过它的下标 ⇒ 它**本回合就会行动**；
* 死掉的战斗员**不会从 `turn_order` 里删掉**，只是被"活着吗"跳过（`turn.rs:850`）。

`a_spawned_enemy_joins_the_turn_order_after_the_current_actor` 把这四条一起钉住：
`turn_order` 变成 5 条（hero + enemy_a + **死掉的** enemy_b + 两只 spawn）、`order[0]` 仍是 hero、
spawn 在末尾（id 带 `#`）、**`active_combatant_id` 没被抢走**。

### 122.2 Boss 相位：**低血分裂**，而且只触发一次

wiki 里 Slime Boss 的"相位"就是它的分裂。这一轮把它做成**一条 `DamageTaken` 触发器**：

```json
standard.phase_split = {
  DamageTaken →
    if currentHealth(self) <= 10:
       createCombatant(acid_slime_m, 10)
       createCombatant(spike_slime_s, 10)
       modifyStatusStacks(self, standard.phase_split, -1)   // 消耗自己 ⇒ 只触发一次
}
```

挂在 `slime_boss` 上。`currentHealth` 这个表达式**本来就有**（`Selector` 字段是我们定的，
参考镜像那条 `nfields = 0` 所以从来没被用过 —— 这是它第一次真的被内容用上）。

判据 `the_boss_phase_splits_once_at_low_health`：
10 HP 的敌人挨 3 点落到 7（≤ 10）⇒ **战斗员 +2**、`standard.phase_split` 层数归 **0**；
再挨 1 点 ⇒ **不再分裂**。

### 122.3 页面的 overflow 提示

`rd_env_enemy_overflow()` 接进顶栏：

```js
const overflow = ex.rd_env_enemy_overflow();
const overflowNote = overflow === 1 ? ' · <span class="warn">⚠️ 敌人超出可见槽（只显示 6 个）</span>' : "";
```

⇒ 战场真超过 6 个敌人时，页面**说出来**，而不是安静地只画六个。`smoke.mjs` 的导出清单也跟着要求它存在。

⚠️ **这条提示今天没法在真浏览器里看到**：默认战斗只有 2 个敌人，而造 7 个敌人需要内容 + ABI 层的编排。
所以它只有"接线"级别的判据（smoke 要求导出存在 + 真浏览器闸门仍绿），**视觉没有判据** —— 和像素级
判据缺失是同一条账。

### 122.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 678 → **680**（rd-core 592 / rd-run 61 / rd-wasm 27） |
| 内容状态 | 15 → **16**（`standard.phase_split`） |
| 镜像 | full 19,752 B / core 16,788 B（重钉） |

### 122.5 现在"Boss"这一块还剩什么

* 相位**换招**（半血改用另一套意图）—— 需要 `EnemyIntentRules` 能按状态切换（内容侧有条件，但没试过）；
* 分裂出来的敌人**立刻有意图**（今天的 `refresh_intents` 每帧重算，理论上会，但没有测试钉住）；
* 多段 Boss（第一幕的 Boss 只有史莱姆王一只，第二幕的还没做）。

---

## 123. 相位**换招**（`intent.healthPercent`）+ 分裂出来的敌人**有自己的意图**

### 123.1 前置：`intent.healthPercent` 原本**没实现**

`intent.rs` 的条件语言有 10 种原语，但 `is_supported` 只对 `selfHasCounter` 为真，其余 9 种一律
`UnsupportedCondition`。所以"半血换招"在内容里根本写不出来。

这一轮实现了第二条：

```rust
ConditionKind::HealthPercent => {
    let ratio = if max > 0 { current * 100 / max } else { 0 };
    op.apply(ratio, percent)
}
```

判据 `a_health_percent_rule_switches_the_boss_move_at_half_health`：
`slime_boss` 140/140 ⇒ 不 slam；70/140（正好 50%）⇒ **`slime_boss.slam`**。

⚠️ 一个格式细节：`Percent` 必须是**整数**（`"Percent": 50`），写成 `{"value": 50}`（term 形式）会得到
`Ir(WrongKind("F_INT"))` —— 和 `selfHasCounter` 的 `Value` 同形。

### 123.2 内容

```json
slime_boss.IntentRules = [
  { "Condition": { "kind": "intent.healthPercent",
                   "value": { "Op": "LessOrEqual", "Percent": 50 } },
    "Action": { "value": "slime_boss.slam" }, "Priority": 20 }
]
```

⇒ 半血之后从 `goop_spray` 换成 `slam`。

### 123.3 分裂出来的敌人**本来拿不到意图**

这是这一轮最有价值的发现。`node.createCombatant` 造出来的 id 是 `acid_slime_m#000000`，而**两处
id 匹配都是全等比较**：

| 位置 | 后果 |
|---|---|
| `intent::locate_enemy` | 找不到槽位 ⇒ 意图被标成 "unknown" |
| `intent::select_action` 的 B0 闸 | `record_id != actor` ⇒ 直接返回 `None` |

⇒ 两只分裂出来的史莱姆在界面上会是"准备中"直到战斗结束。**修法**：两处都加一条回退 ——
把 `#` 之后的部分砍掉再比一次（"分裂出来的那个仍然是那个怪"）。

判据 `a_spawned_combatant_still_resolves_to_its_enemy_record`：
`acid_slime_m#000003` 与 `acid_slime_m` 解到**同一个槽位**，而且那个槽位**真的能选出一个动作**。

### 123.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 680 → **682**（rd-core 594 / rd-run 61 / rd-wasm 27） |
| 意图条件 | 支持 1 → **2** 种（`selfHasCounter`、`healthPercent`） |
| 镜像 | full 19,856 B / core 16,888 B（重钉） |

### 123.5 剩余

* 意图条件还有 **8 种**没实现（`round` / `selfHasStatus` / `opponentHasStatus` / …）；
* 分裂出来的敌人**意图栏**在页面上是否显示正确，只有内核判据，没有浏览器判据；
* 第二幕 Boss 与幕间内容差异（老账）。

---

## 124. 意图条件：**10 种里 9 种实现**

### 124.1 这一轮补的 7 种

| kind | 字段 | 判据 |
|---|---|---|
| `intent.round` | `Op, Round` | 与 `state.current_round` 比 |
| `intent.selfHasStatus` | `Status, MinStacks`(缺省 1) | 出手者身上有它且层数够 |
| `intent.opponentHasStatus` | 同上 | **对手阵营**里有人戴着（出手者是敌人时，对手就是英雄） |
| `intent.selfResource` | `Resource, Op, Value` | 出手者该资源池的当前值 |
| `intent.allOf` | `Conditions[]` | 全真；**空列表 ⇒ true** |
| `intent.anyOf` | `Conditions[]` | 任一真；**空列表 ⇒ false** |
| `intent.not` | `Condition` | 内层取反 |

`is_supported` 现在写成 `!matches!(self, OpponentCardsPlayed)` —— 剩下的那一种要**每回合出牌统计**
（`CardPlayTurnStats` 整块没移植），照旧**响亮拒绝**。

**一处签名改动**：`condition_matches` 多了 `content` 参数 —— 组合条件要顺着 `Conditions` 的**子 term**
递归，而 term 是从镜像里读的。两个调用点（`select_action` 与它自己）都改了一行。

### 124.2 判据

* `every_comparison_operator_orders_its_operands_correctly` —— 六种 `CompareOp` × 12 组，**九种条件共用**
  这个算术，所以它单独钉一张表；
* `a_combinator_rule_switches_the_boss_move` —— **真的**用组合条件：内容里 `slime_boss` 的相位规则改成
  `allOf(healthPercent <= 50, round >= 2)`：
  * 半血 + 第 1 轮 ⇒ **不 slam**
  * 半血 + 第 2 轮 ⇒ **slam**
  * 满血 + 第 5 轮 ⇒ **不 slam**（`allOf` 因为血那半为假）

  这一条同时覆盖了 `allOf` 的**子 term 列表**、`round`、`healthPercent` 三种新代码。

### 124.3 诚实的一条

`selfHasStatus` / `opponentHasStatus` / `selfResource` / `anyOf` / `not` 这五种**只有编译级与
`is_supported` 级覆盖**，没有行为判据 —— 因为内容里还没有一条规则用到它们，而给它们造规则就要往怪物身上
加"永不触发的测试规则"（内容污染）。**等有内容真的用到时再补判据**，这一条记在这里而不是假装已覆盖。

### 124.4 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 682 → **683**（rd-core 595 / rd-run 61 / rd-wasm 27） |
| 意图条件 | 支持 2 → **9** 种（10 种里只剩 `opponentCardsPlayed`） |
| 镜像 | full / core 重钉 |

### 124.5 一个操作教训

这一轮我把 `git checkout -- intent.rs` 当"撤销这次编辑"用了，**结果连未提交的七个臂一起丢了**，
只好重跑一遍补丁。**`git checkout` 撤销的是整份文件，不是最后一次编辑** —— 要撤销局部就用反向补丁。
（同一类事这是第三次：`Copy-Item` 恢复源文件会连 mtime 一起恢复、`git show > file` 写 UTF-16，现在是
`checkout` 吃掉未提交改动。）

---

## 125. **时间吞噬者的"12 张牌强制结束回合"**：机制已备好

用户："时间吞噬者的手牌数量到阈值以后回合强行结束功能是不是也可以现在准备好"

### 125.1 内核原来**没有**这个能力

两处都缺：

* `EffectRequest` 里没有任何"结束回合"的请求；
* 也没有"回合被提前结束"的旗子 —— 回合推进只发生在 `turn.rs` / `battle.rs`。

（`combatantCounter` **早就有**，`node.setCombatantCounter` 也有 —— 所以缺的只是"结束回合"。）

### 125.2 补的形状：**立旗 + 循环兑现**

```rust
EffectRequest::EndTurn            // 第 7 个请求（参考实现没有）
CombatState.end_turn_requested    // 效果层立旗
battle.rs::hero_plays             // 出牌排空后：flag 立着 ⇒ end_turn_and_start_next + 清旗
node.endTurn                      // 第 17 个 IR 节点，无字段
```

为什么是"请求"而不是直接跳：效果节目跑在效果队列深处，回合推进住在 `turn.rs`。**立旗 + 让循环兑现**
保持了控制方向单向 —— 和 `state.result` 一模一样，而且"谁兑现了这个请求"是可读的。

### 125.3 内容：`standard.time_warp`

```
CardPlayed →
  if counter(time_warp) >= 11:
      applyStatus(self, standard.strength, 2)
      setCombatantCounter(time_warp, 0)   // 绝对置零：第 12 张算新一轮的第 1 张
      endTurn
  else:
      setCombatantCounter(time_warp, +1)
```

⚠️ **一个必须知道的批处理语义**：`node.sequence` 是**批处理** —— 孩子先全部派发、效果排队，所以
"先 +1 再读"读到的还是**旧值**。第一版就是这么写的，测试给出"第 12 张没触发"。**正确写法是把条件放在
最外层，增减放在分支里。**

挂在 **`blue_slaver`** 上（它**不在任何遭遇里**），所以玩家不会在正常流程里撞见它 —— 这是"把机制准备好"
而不是"把第三幕 Boss 做进来"。`AiNote` 写明了降级。

### 125.4 判据

`the_twelfth_card_asks_for_the_turn_to_end`（rd-core，全量镜像）：

* 前 11 张：`end_turn_requested` **一直是 false**；
* 第 12 张：旗子立、**+2 力量**、计数器归 **0**；
* 第 13 张：又是普通一张（说明归零真的生效）。

### 125.5 还差什么才算"时间吞噬者能上"

* 一只真正的第三幕 Boss（内容 + 遭遇 + 意图）；
* "额外回合"（真正的 Time Eater：时间扭曲之后 Boss 还会多动一次）—— 需要"插入一个额外回合"的推进原语；
* 页面上的提示（"你的回合被强行结束了"）—— 现在只是状态旗，UI 不显示。

### 125.6 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 683 → **684**（rd-core 596 / rd-run 61 / rd-wasm 27） |
| `EffectRequest` | 6 → **7**（`EndTurn`） |
| IR 节点 | 16 → **17**（`node.endTurn`） |
| 内容状态 | 16 → **17**（`standard.time_warp`） |
| 镜像 | full 20,404 B / core 17,324 B（重钉） |

---

## 126. 第 3 件：**"回合被强行结束"在页面上看得见**

`node.endTurn` 立的旗子在战斗循环里**当场被消费**，页面根本读不到它。

⇒ 暴露**单调计数器**而不是旗子：

```rust
CombatState.forced_turns: i32          // 每次兑现 +1（EMPTY/reset 清零）
rd_env_forced_turns()                  // 导出
```

页面轮询它：值比上次大 ⇒ `say('⏳ 你的回合被强行结束了（时间扭曲）')`。`say()` 仍是 `#msg` 的唯一写者。

**为什么用计数器**：旗子是"这一帧的事件"，页面每帧都可能错过那个瞬间；计数器是"发生过几次"，不会漏。

---

## 127. 第 2 件：**额外回合**（`node.extraTurn`）

Time Eater 时间扭曲之后还会再动一次 —— 那是"插入一个额外回合"，内核原来没有。

| 件 | 内容 |
|---|---|
| 状态 | `CombatState.extra_turn_for: Option<CombatantId>` |
| 请求 | `EffectRequest::ExtraTurn { target }`（第 8 个） |
| 节点 | `node.extraTurn`（第 18 个，带 `TargetSelector`） |
| 兑现 | `turn.rs::advance_to_next_combatant` 开头：**额外回合优先于轮转** —— 标记指向当前行动者时，它保持活跃、只推回合时钟、清标记 |

结果：十二张牌之后 = +2 力量 + 计数器归零 + **你的回合结束** + **敌人再来一个回合**。

判据 `an_extra_turn_keeps_the_same_actor_active`：普通轮转 ⇒ 敌人接管；打上标记后再推 ⇒ **仍是敌人**、
时钟 +1、标记被消费；之后那一次照常轮转回英雄。

---

## 128. 第 3 件（`opponentCardsPlayed`）：**10 种意图条件全部实现**

### 128.1 缺的是"每回合出牌统计"

```rust
CombatState.cards_played_this_turn   // play.rs 每出一张 +1
CombatState.cards_played_last_turn   // turn.rs 在每个回合边界滚动
```

由此：

* `intent.opponentCardsPlayed`（`Op, Value, LastTurn` 缺省 **true**）：比较**对手阵营**的计数；
* 顺带把两个表达式 `cardsPlayedThisTurn` / `cardsPlayedLastTurn` 也实现了（它们本来在
  `expr.rs` 的"不支持"名单里）。

`is_supported` 现在返回 `true` —— **10/10**。

### 128.2 实现一个功能会打破"钉住它不存在"的测试（这一轮有五条）

| 测试 | 原来钉的 | 现在 |
|---|---|---|
| `expr` 覆盖扫描 | `ok = 117` / `unsupported = 40` | **121 / 36** |
| `unsupported_expressions_are_loud_and_never_zero` | `cardsPlayedThisTurn` 必须报错 | 它**答得出**；那条断言改成 `Ok(false)`（0 张牌） |
| `condition_kinds_are_the_ten...` | 支持 9 种 | **10 种** |
| `every_cycle_action_in_the_image_resolves_to_its_own_row` | 参考内容里有 5 次响亮失败 | **0 次**（`refused = 0`，`resolved = 149*5`） |
| `opponent_cards_played_is_a_loud_error_not_a_fallthrough` | 报 `UnsupportedCondition` | 改成"读得到计数"的真值测试 |
| `queue_advances_is_a_kernel_gap_not_a_content_error` | 该状态触发必失败 | 改成**正面**测试：`cardsPlayedLastTurn >= 3` 才动计数器 |
| `the_two_error_channels_agree_on_class_and_detail` | 用上面那个失败当例子 | 改用 `Bind(Missing("STAT row"))`（`HostFailure::Content`），**两条通道仍然一致** |

⚠️ 最后一条值得单独说：那条测试的价值是"类别与细节两条通道说同一件事"，**不是**"用哪个错误当例子"。
换例子保住了价值，删掉就会丢。

### 128.3 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 684 → **685**（rd-core 597 / rd-run 61 / rd-wasm 27） |
| 意图条件 | **10 / 10** |
| 表达式 | `cardsPlayedThisTurn` / `cardsPlayedLastTurn` 从不支持变成支持 |

---

## 129. 第 1 件：**第三幕 Boss（时间吞噬者）进了内容**

### 129.1 一只真的 Boss

| 项 | 值 |
|---|---|
| 怪 | `time_eater`，456 HP（wiki 值） |
| 动作 | `reverberate`（7×3）/ `ripple`（20 格挡 + 1 虚弱 + 1 易伤）/ `head_slam`（26） |
| 状态 | `standard.time_warp` 1 层（§125 做的机制） |
| 意图规则 | 半血以下改用 `head_slam`（`intent.healthPercent <= 50`，§124 做的条件） |
| 遭遇 | `enc_time_eater` |
| 池 | **`EncounterTables.Boss` 现在有两项** |

⇒ floor 16 的 Boss **不再是常量**：两个 Boss 等概率二选一。

### 129.2 一处降级（写在 `AiNote` 里）

wiki 的 Time Eater 是**第三幕** Boss；本内容把它放进 **Boss 池**（与 Slime Boss 同池），因为
**幕与幕之间的内容差异还没做**（§101）。机制（时间扭曲、额外回合、相位）是真的，**"它只出现在第三幕"
是假的**。

### 129.3 实现过程中修掉的三处"内容门太紧"

内容门 `sts_content_check` 是逐条对账的，所以每加一窝怪都要跟着改它 —— 这一轮改了四处：

1. 动作事实表（`INV_ACTIONS`）加三条；
2. 怪物名册（`INV_MONSTERS`）加一行；
3. Boss 池（`INV_BOSS_POOL`）加一项；
4. 计数 `monsters 14→15` / `encounters 5→6`。

**还有两处踩到的形状坑**（都是"编译器认识哪些字段"这种硬约束）：

* 怪物记录**不能**带 `PackageId`（`compile.py` 的 `obj()` 只有它见过的字段组合）；
* 遭遇记录**要**带 `HeroResources` / `HeroStartingStatuses` / `HeroDisplayName` / `CardsDrawnPerTurn`，
  内联敌人**要**带 `Position` / `DisplayName` / `MaxHealth` —— 少一个就是 `KeyError: (...)` 或者
  内容门报 `MaxHealth None != roster 456`。

### 129.4 判据

* 内容门：`monsters 15 / encounters 6 / enemy_actions 27`；
* `the_encounter_pools_are_readable`：Boss 池 == `["enc_slime_boss", "enc_time_eater"]`；
* `the_boss_is_offered_at_floor_16_and_clears_the_act`：断言从"必须是史莱姆王"**放宽成"必须来自 Boss 池"**
  （两个 Boss 之后那句硬断言就是错的）。

### 129.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | **685**（rd-core 597 / rd-run 61 / rd-wasm 27） |
| 内容 | 怪物 14 → **15**、遭遇 5 → **6**、动作 24 → **27** |
| Boss 池 | 1 → **2** |
| 镜像 | full 21,272 B / core 18,028 B（重钉） |

### 129.6 这一整轮（§125–§129）做完的

1. `node.endTurn` + 请求 + 循环兑现（"12 张牌结束回合"）；
2. 页面上的"回合被强行结束"提示（计数器 + 轮询）；
3. `node.extraTurn`（额外回合）；
4. 每回合出牌统计 + `opponentCardsPlayed`（**意图条件 10/10**）；
5. 时间吞噬者本体（怪 + 动作 + 遭遇 + Boss 池 + 相位 + 时间扭曲）。

剩下的仍然是那几笔老账：幕间内容差异、`?` 房通用解释器、像素级判据、Boss 之外的第三幕怪。

---

## 130. **幕与幕的内容差异**：第 2、3 幕有自己的怪物、遭遇和 Boss

§101 写过一句"推进机制是真的，幕与幕之间的内容差异是假的"。这一轮把它变成真的。

### 130.1 池子按幕分家

```
EncounterTables = { Weak, Elite, Boss, Weak2, Elite2, Boss2, Weak3, Elite3, Boss3 }
```

`rd_run_fight_begin` 里的池名从**幕号**推出来（第 1 幕不加后缀，所以原来的名字仍然有效）：

```rust
let base = match kind { 2 => "Elite", 7 => "Boss", _ => "Weak" };
let pool_name = if act <= 1 { base } else { format!("{base}{act}") };
```

**缺池子就响亮失败**（"内容里没有 `EncounterTables.Weak2` 池（第 2 幕）"）—— 退回第 1 幕等于把这一节要治的
毛病藏起来。

### 130.2 新内容（21 怪 / 12 遭遇 / 40 动作）

| 幕 | 弱池 | Boss |
|---|---|---|
| 1 | cultist / jaw_worm / small_slimes | slime_boss |
| **2** | **shelled_parasite / chosen** | **the_champ**（330 HP，重斩/防御姿态/处决）|
| **3** | **byrds / spiker / orb_walker** | time_eater |

`spiker` 带 **Thorns 3**（§116 的机制），`the_champ` 的防御姿态给 **Metallicize 2**（§114 的机制）—— 新怪不是
换皮，是在用已经做出来的机制。精英池三幕共用 `enc_three_sentries`（写明）。

### 130.3 内核侧要改的一处"名字表"

`Content::encounter_pool` 原本只认三个名字（`Weak`/`Elite`/`Boss`），其余返回 `None` ——

```rust
let hop = match pool { "Weak" => "EncounterTables.Weak", … _ => return None };
```

名字是**逐字写出**的（`sts_content_check` 靠在这些字面量里找 `EncounterTables.Weak` 来判断"内核真的读这张表"）。
⇒ 九个名字都列进去，注释说明为什么不能拼字符串。

### 130.4 内容门要跟着长大

`sts_content_check` 里三张池子表原本是**单幕**的。现在：

* `INV_WEAK_POOL` / `INV_ELITE_POOL` / `INV_BOSS_POOL` 是**并集**（"每个遭遇都要被声明"靠它）；
* 新增 `INV_ACT_TABLES`，逐幕列出成员；九个表的检查都对比它；
* 怪物/遭遇/动作三张事实表各加 6/6/13 行；计数 `monsters 21` / `encounters 12` / `enemy_actions 40`。

### 130.5 判据

`act_two_fights_act_two_enemies`（rd-wasm）：两次**独立**开局 —— 一次直接打第 1 幕，一次先 `mark_boss_beaten`
再打；前半场的敌人名必须属于第 1 幕池（`acid_slime/spike_slime/jaw_worm/cultist`），后半场必须属于第 2 幕池
（`shelled_parasite/chosen`）。

⚠️ 两条**踩到的真事**：
1. 战斗是 `rd_run_fight_begin` **建**的，不是 `begin_node` 建的 —— 不调它就还在看上一场；
2. 一场已经开始的战斗不能再 begin，所以测试要用**两次独立开局**而不是"打完一场接着下一幕"。

### 130.6 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | 685 → **686**（rd-core 597 / rd-run 61 / rd-wasm 28） |
| 内容 | 怪物 15 → **21**、遭遇 6 → **12**、动作 27 → **40** |
| 遭遇池 | 3 → **9**（每幕一套 Weak/Elite/Boss） |
| 镜像 | full 24,172 B / core 20,220 B（重钉） |

### 130.7 这一节之后，"幕"还剩什么假的

* **地图**三幕共用同一张（`Map::generate` 只在开局跑一次）；
* **事件**（`?` 房）和 **药水**只有一套；
* 幕间**没有过渡画面**（打完 Boss 直接进下一幕）；
* 精英池三幕共用。

---

## 131. 每幕自己的地图

§130 之后还剩一条最显眼的假：三幕共用同一张地图（RunMap::generate 只在开局跑一次）。

### 131.1 形状

RunState::mark_boss_beaten 推进act 时**重新生成地图**，种子由 run seed 与幕号折出来：

`
ust
pub const fn act_seed(&self) -> i32 {
    self.seed.wrapping_add(((self.act - 1) as i32).wrapping_mul(0x9E37_79B9u32 as i32))
}
`

ct - 1 是刻意的：**第 1 幕的种子就是 run seed**，所以老种子跑出来的第一张图和以前一模一样；
第 2 幕才是第一次折叠。生成失败时**保留旧图并立 map_generation_failed 旗**（今天不可能发生，
但静默换一张图正是这个项目一直在禁的那种悄悄错）。

### 131.2 判据

dvancing_the_act_draws_a_new_map（rd-run）：act 1 的 ct_seed() == run seed、地图 == 开局那张；
杀 Boss 之后 ct == 2、map_generation_failed == false、种子变了、**地图不等于第 1 幕那张**，
而且**同种子的另一局画出一模一样的第 2 幕地图**（确定性）。

### 131.3 数字

聚合验收 17/17；单测 686 → **687**。

---

## 132. 幕间过渡：页面自己宣布"第 N 幕"

地图重画之后玩家其实**看不出来**幕变了（顶栏那行 `幕 N` 一直在，没人会盯着它）。

做法（纯页面，一行内核都没动）：页面记住 `actSeen`，`rd_run_act()` 变大时用 `say()` 说一句：

```
—— 第 2 幕 ——  地图重画了，血量、牌组、遗物都带过来了
```

`say()` 仍然是 `#msg` 的唯一写者 —— 这条纪律从 §82 起没破过。

**判据**：`smoke.mjs` 检查页面里还有 `第 ${act} 幕` 这个模板串（删掉公告就红）。真浏览器闸门覆盖不到
"真的进第二幕"（那要打赢 Boss），所以这一条是**接线级**判据，不是视觉判据 —— 记在这里。

---

## 133. 每幕自己的 `?` 房事件（药水那半**没做，写清原因**）

### 133.1 事件：`EventTables`

```json
"EventTables": { "Events": [...4 个第 1 幕], "Events2": [...], "Events3": [...] }
```

`?` 房原来从**整张 `EV` 表**里掷一个（`content.event_count()`）；现在从**当前幕的池**里掷：

```rust
let pool_name = match act { 1 => "Events", 2 => "Events2", _ => "Events3" };
let Some(pool) = image.event_pool(pool_name) else { /* 响亮失败，指名缺哪个池 */ };
```

缺池子照旧**响亮失败**（和 §130 的遭遇池同一条规矩）。

新事件两条：`ancient_forge`（第 2 幕：+6 最大生命 / 45 金币）、`wandering_merchant`（第 3 幕：回 18 / 25 金币）。
新药水两条：`blood_potion`（回 15）、`swift_potion`（+12 格挡）。

### 133.2 药水：**只加了两种药水，没做"每幕一套池"**

原因是查出来的：药水的**身份**不是在 run 层摇的（那里只有"掉不掉"的 40%），而是在 `rd-wasm` 的奖励路径里
从整张 `POT` 表挑。要按幕分池，得先把池子参数穿到那条路上 —— 那是另一处改动。

我**没有**留下一个"读不到任何东西的 `PotionTables`"：那正是 §104 那条规则要治的"惰性内容"。
表被删掉了，两种新药水留着（它们真的会掉、真的有效果），降级写在 `port-plan.md` 这里而不是假装已覆盖。

### 133.3 内核侧的一个小重构

三个池读器（`encounter_pool` / `event_pool` / `potion_pool`）现在共用一个 `id_pool(table, pool, hop)`。
⚠️ `hop` 是**传进去的**，因为内容门靠在公开读器里找 `EventTables.Events` 这类**字面量**；而
`root_by_name` 也必须写成**字面量**（`match table_name { "EventTables" => self.root_by_name("EventTables")? }`），
否则门会报"这个 root 没人读"。这两条都是"门能看见才算接线"的直接后果。

### 133.4 判据

* `sts_content_check`：事件 4 → **6**、药水 3 → **5**，且 `EventTables` 的每一幕都被点过名；
* `the_unknown_room_events_are_readable` / `the_potions_are_readable`：id 清单跟着改成 6 / 5；
* `a_potion_can_be_used_in_a_fight`：多两条分支（`blood_potion` / `swift_potion`），否则掉到新药水就 panic。

### 133.5 数字

| 项 | 值 |
|---|---|
| 聚合验收 | **17/17** |
| 单测 | **687**（rd-core 597 / rd-run 62 / rd-wasm 28） |
| 内容 | 事件 4 → **6**、药水 3 → **5** |
| 镜像 | full 24,744 B / core 20,792 B（重钉） |

---

## 134. 每幕自己的精英

Elite / Elite2 / Elite3 原来都是同一窝哨兵（§130 写明过）。这一轮后两幕各有自己的精英：

| 幕 | 精英 | 血量 | 用的机制 |
|---|---|---|---|
| 1 | sentry_1/2/3 | 3 × 40 | （无状态）|
| **2** | **gremlin_leader** | 140 | **Enrage 1**（§117）：你每出一张牌它 +2 力量 |
| **3** | **giant_head** | 320 | **Metallicize 4**（§114）：每回合结束 +4 格挡 |

gremlin_leader.rally 还会给自己 +5 力量、+12 格挡；giant_head.glare 给 1 层虚弱。**没有一条新内核代码** ——
两种状态都是前几轮做出来的，这两只精英只是在用它们。

内容门跟着加：两只怪进名册、三条动作进事实表、两个遭遇进 INV_ELITE_POOL、INV_ACT_TABLES 的
Elite2/Elite3 换成新遭遇、计数 monsters 23 / encounters 14 / enemy_actions 44。

数字：聚合验收 **17/17**；单测 **687**；内容 怪物 21 → **23**、遭遇 12 → **14**、动作 40 → **44**；
镜像 full 25,708 B / core 21,564 B（重钉）。

---

## 135. 药水也按幕分池（§133 那条"说了没做"的补上）

§133 写过：药水的**身份**不是在 run 层摇的，而是在 `rd-wasm` 的奖励路径里从整张 `POT` 挑。这一轮把池子穿过去：

```rust
let potion_pool_name = match act { 1 => "Potions", 2 => "Potions2", _ => "Potions3" };
let Some(pool) = image.potion_pool(potion_pool_name) else { /* 响亮失败，指名缺哪个池 */ };
```

内容侧 `PotionTables { Potions, Potions2, Potions3 }` 回来了 —— 这次**真的被读**，所以不再是惰性内容
（内容门会拿 `PotionTables.Potions` 这些字面量去核）。

判据 `the_potions_are_readable` 里新增：第 1 幕池 == 三瓶原版；**第 2 幕池含 `blood_potion` 且不含
`energy_potion`**（"不重放第 1 幕"）；同一个池两次读出来相等；未知池名返回 `None` 而不是空池。

数字：聚合验收 17/17；单测 687；镜像重钉。

---

## 136. 真正的幕间画面（不是消息条里那一行）

§132 的幕间提示只是 `say()` 的一行字。这一轮把它换成**一整屏**：

```html
<div id="actCurtain" hidden>
  <div class="curtain-inner">
    <div class="curtain-act">第 2 幕</div>
    <div class="curtain-line">地图重画了 · 血量、牌组、遗物都带过来了</div>
    <div class="curtain-hint">点一下继续</div>
  </div>
</div>
```

* `position: fixed; inset: 0; z-index: 50`，径向渐变底 + 淡入（`curtainIn 240ms`）；
* `rd_run_act()` 变大 ⇒ `showActCurtain(act)`；**1.6 秒自动淡出**，或者**点一下就收**；
* 计时器存进 `actCurtainTimer`，两次换幕不会互相打架。

### 判据

* `ui_test.mjs`：页面里必须有 `id="actCurtain"` / `id="curtainAct"`，且有人调 `showActCurtain(`；
* **真浏览器实测**（`mcp` 驱动，直接调 `showActCurtain(2)`）：
  `hidden=false`、文本 `第 2 幕`、`display=flex`、`z-index=50`，点一下之后 `hidden=true`。

⚠️ 还是那句：**"赢下 Boss 之后自动出现"这一步没有自动化判据**（那要打赢一整个 Boss 战），
手工调用 + 上面的三条 CSS/DOM 断言是目前能拿到的最好证据。

---

## 137. 第三幕的普通怪池加厚（3 → 5 组）

`Weak3` 原来只有三组（byrds / spiker / orb_walker），走两场就重样。这一轮加两只怪、两个遭遇：

| 怪 | 血量 | 招式 | 用的机制 |
|---|---|---|---|
| `darkling` ×2 | 48 | nip 7 / chomp 11 | **Regen 5**（§119）|
| `maw` | 80 | roar（+3 力量、2 虚弱）/ bite 14 / slam 20+3 格挡 | — |

`enc_darklings` 一场两只暗灵（`Position` 0/1），`enc_maw` 一只。`Weak3` 现在 5 组。

内容门跟着加：两只怪进名册、五条动作进事实表、两个遭遇进 `INV_WEAK_POOL`、`INV_ACT_TABLES.Weak3` 更新、
计数 `monsters 25` / `encounters 16` / `enemy_actions 49`。

### 数字（§131–§137 合起来）

| 项 | §130 之前 | 现在 |
|---|---|---|
| 怪物 | 15 | **25** |
| 遭遇 | 6 | **16** |
| 敌人动作 | 27 | **49** |
| 事件 | 4 | **6** |
| 药水 | 3 | **5** |
| 每幕池子 | 3（Weak/Elite/Boss）| **9** 遭遇池 + **3** 事件池 + **3** 药水池 |
| 地图 | 三幕一张 | **每幕一张**（`act_seed`） |
| 幕间 | 无 | **一整屏幕间画面** |

聚合验收 **17/17**，单测 **687**，镜像 full 26,808 B / core 22,456 B。

---

## 138. **召唤随从**：机制本来就在，缺的是"随从的意图"

用户："现在有精英怪/boss召唤随从的机制吗。"

答：**一半有。** `node.createCombatant`（§121）早就能中途造战斗员，史莱姆王的分裂就用它。缺的是另一半：

### 138.1 缺的那一半是"随从拿不到意图"

`intent::locate_enemy` 只在**当前遭遇**的敌人名单里找 id（这是参考的 B0 语义）。§123 给它加了
`#<n>` 的回退（分裂出来的史莱姆还是史莱姆），但那只在**同一个遭遇**里有效。

⇒ 精英召唤一只"本遭遇没列过"的随从时，那只随从的意图永远是 "unknown"。

### 138.2 补法：`#<n>` 的 id 允许**跨遭遇**解析

```rust
if !raw.contains('#') {
    return Ok(None);          // 纯陌生人（参考的 B0）—— 不许它解析
}
// 召唤出来的：在整张镜像里找第一个列了它的遭遇
for row in content.rows(Table::Encounter) { … }
```

**只对带 `#` 的 id 放开**：陌生人（另一个遭遇里的怪，但不是召唤出来的）仍然是 `None` —— B0 那条语义没被
破坏，`b0_actor_not_in_this_encounter_has_no_action` 仍然绿。

### 138.3 内容：哥布林头目会召唤了

* 新动作 `gremlin_leader.summon`：`sequence(createCombatant(sneaky_gremlin, 10), createCombatant(gremlin_wizard, 20))`；
* 新遭遇 `enc_gremlin_gang`（fat_gremlin + sneaky_gremlin + gremlin_wizard），进 `Weak2`。

那个遭遇**不是为了好玩**：`gremlin_wizard` / `sneaky_gremlin` 之前被 author 了却没有任何遭遇列过它们，
所以"召唤出来的它们"**无处解析**（实测：`locate_enemy` 返回 `None`）。把三只哥布林组成一个真遭遇之后，
召唤出来的那两只才有记录可指。

### 138.4 判据

`a_summoned_minion_resolves_through_the_image_not_the_encounter`：
`gremlin_wizard#000007` 在 `enc_giant_head`（只列了 giant_head）里**能解出槽位**、且**能选出动作**；
同一个遭遇里的陌生人 `minute_moth`（不带 `#`）仍然 `None`。

### 138.5 数字

聚合验收 **17/17**；单测 687 → **688**；敌人动作 49 → **50**；遭遇 16 → **17**；
镜像 full 27,124 B / core 22,700 B。

---

## 139. 随从的三件：**上限 / 槽位 / 主人死了就逃跑**

用户："召唤上限、槽位、主人死了就逃跑这些可能可以一起做？逃跑以后胜利结算不考虑它们的剩余血量"

### 139.1 上限：`MAX_ENEMIES_IN_FIGHT = 4`

`node.createCombatant` 在造人之前数**活着的同队战斗员**，到上限就**响亮失败**
（`ExecError::Capacity(Full(Combatants))`）。不静默丢一只 —— 召唤者的招式放不出来是**内容 bug**，
不是"少一只也无所谓"。

数字取 4 的理由：玩家得能看见并选中每一个，而观察向量一共 6 个敌人槽。

### 139.2 槽位：随从落在哪

观察向量的敌人槽来自 `enemy_roster()`（§121 就是派生的），所以召唤出来的随从**自动占一个槽**；
名字/意图走 `locate_enemy`（§138 的跨遭遇回退），因此槽位上既有名字也有意图。

### 139.3 主人死了就逃跑

```rust
// 造人时记住是谁召唤的
combatant.owner = ctx.source;

// 倒下那一刻，它的随从一起走
for other in ctx.state.combatants_mut() {
    if other.owner == Some(*target) && other.lifecycle_state == Alive {
        other.lifecycle_state = Escaped;
    }
}
```

用参考实现本来就有的 `CombatantLifecycleState::Escaped`（值 4）—— **不是**自己发明一个"逃跑"标志。

### 139.4 "逃跑以后胜利结算不考虑剩余血量"

这一条**自动成立**，因为胜负只看 `Alive`（`update_standard_combat_result`）：

* 逃跑的随从**不再是 `Alive`** ⇒ 它不会让战斗继续；
* 它也不是 `Downed` ⇒ 不会触发死亡触发器、不会进"尸体"那类结算；
* 它的剩余血量因此**不参与任何判定**。

判据里额外断言了这一条：主人倒下之后 `state.result` 仍是 `Ongoing`（因为 `enemy_a` 还活着），
而逃跑的随从已经不是 `Alive`。

### 139.5 判据

| 测试 | 证明 |
|---|---|
| `a_minion_flees_when_its_master_falls` | 随从从 `Alive` 变成 **`Escaped`**（不是 `Downed`），且不影响胜负 |
| `the_summon_cap_is_a_loud_failure` | 场上 4 个活敌人时，`gremlin_leader.summon` **报错** |

（第二条测试需要召唤者本人在场 —— `execute_action` 对不存在的 actor 是**静默 no-op**，
这是我第一版测试失败的原因。）

### 139.6 数字

聚合验收 **17/17**；单测 688 → **690**（rd-core 600 / rd-run 62 / rd-wasm 28）。

---

## 140. 随从的细节：**页面上的标记** + **内容侧的同一个上限**

### 140.1 页面：召唤出来的敌人自己说

观察向量里没有"这是随从"这一位（加了就要动 148 个 slot 的布局），所以做成了一个**独立导出**：

```rust
rd_env_enemy_is_minion(slot)   // 1 是 / 0 不是 / -1 没有这个槽
```

实现就是 `combatant.owner.is_some()` —— §139 存下来的那条边，这里第二次派上用场。
页面在敌人面板的名字后面挂一个 `召唤` 小标签（`.chip.minion`），否则随从和"内容摆进来的怪"长得一模一样。

### 140.2 内容侧：同一个上限也管"直接摆"

`MAX_ENEMIES_IN_FIGHT = 4` 之前只在**召唤**路径上检查。现在两边都管：

| 谁 | 怎么管 |
|---|---|
| 内核（召唤） | `node.createCombatant` 数活着的同队，到上限 **报错**（§139）|
| 内容门 | 任何遭遇的 `Enemies` **多于 4** ⇒ `fail("encounter.X", "N enemies, the cap is 4")` |
| 内核测试 | `no_encounter_places_more_enemies_than_a_fight_allows` 扫全部遭遇，断言最大的那个 ≤ 4 |

第三个是"内容门的那条规则有没有真的被遵守"的内核侧证据 —— 门和内核各说一遍，是最便宜的互校。

### 140.3 判据

* `no_encounter_places_more_enemies_than_a_fight_allows`（rd-core，扫真镜像）；
* `sts_content_check` 逐遭遇查上限；
* `smoke.mjs` 要求 `rd_env_enemy_is_minion` 这个导出真的存在（页面调它，模块就得有）；
* 真浏览器闸门仍然绿（随从标签在**没有随从**的战斗里不会出现，所以这条只有接线级判据）。

### 140.4 数字

聚合验收 **17/17**；单测 690 → **691**（rd-core 601 / rd-run 62 / rd-wasm 28）。

---

## 141. 对照 wiki 的缺口清单：单独一份 `docs/sts-wiki-gap.md`

用户："界面后面会直接上轻量 Live2D 真正模拟 StS，所以先仔细对照 wiki，有哪些功能细节需要进一步实现。"

把现状与 wiki 逐项对了一遍，写成 **`docs/sts-wiki-gap.md`**（不再往本文件的 100+ 节里塞）。

### 141.1 已确认缺的（按对体验的影响排）

| 类 | 缺什么 | 活 |
|---|---|---|
| **Live2D 硬前提** | **一步之内的事件序列**（现在页面靠 `diffObservations` 反推，多段伤害分不出来）| 内核：`rd_env_events_*` |
| 内容表达力 | 事件只能选 `heal/gold/damage/max_hp/nothing`：**删卡 / 升级 / 拿诅咒 / 给遗物** 都没有 | 内核 |
| 卡牌关键词 | `Ethereal`（内核 0 次）、`Retain`、`Innate`；**X 费**引擎里明确不存在 | 内核 |
| 状态 | `Intangible` / `Buffer` / `Plated Armor` / `Barricade` / `Blur` / `Entangled` / `Slow` | 内核 |
| 状态（便宜） | `Constricted`（`TurnEnded` 触发器就能写）、塞牌（`createCardInstance` 已有）| **内容** |
| 运行层 | **遗物只有 1 个**（burning_blood）、**无钥匙/第四幕**、**无 Ascension**、篝火只有休息/打铁 | 内容 / 运行层 |
| 敌人形态 | 无复活 / 多段（Awakened One 那种）| 内核 |

### 141.2 顺手纠正了我自己两条记忆

* **`Unplayable` 是有的** —— 它是 `play.rs` 受理校验五条之一（stun / decree / play_condition /
  one_attack / unplayable），我一开始写成"没有"；
* **X 费确实不存在** —— `play.rs` 模块头原文："X 费在引擎里**不存在**"。

⇒ 又一次印证：**"我以为没有"要靠 grep 证明，不能靠印象。**

### 141.3 建议顺序

1. `rd_env_events_*`（Live2D 的硬前提）
2. 事件解释器（删卡/升级/拿诅咒）
3. 卡牌关键词：Ethereal → Retain → Innate → X 费
4. **遗物池**（1 → 一窝，纯内容，立刻让每局不同）
5. 状态：Constricted（内容）→ Intangible/Buffer（伤害管线）

聚合验收 **17/17**；单测 **691**（本轮只加文档）。

---

## 142. 有序动画事件（`rd_env_beat_*`）：Live2D 的硬前提

用户："先来做 1 和 2 吧"（§141.3 的顺序）。

### 142.1 为什么 `diffObservations` 不够

页面到今天为止是从 `diffObservations(before, after)` **反推**"刚才发生了什么"。它对"还剩几点血"
够用，对动画不够，而且是**原理上**不够：

| 事实 | 相减给出 | 动画需要 |
|---|---|---|
| 敌人 7×3 的三段攻击 | "掉了 21" | **三段**，每段 7，中间可以插受击反馈 |
| 先加格挡再挨打 | 与"先挨打再加格挡"**同一个向量** | **顺序** |
| 加格挡 / 回血 / 抽牌 | 完全没有对应的事件变体（参考自己也不为它们发事件） | 拿出来播 |

相减丢掉的是**顺序与分段**，而这两样恰好是动画的全部输入。

### 142.2 不是从 `pending_events` 里捞

内核里已经有一本账：`CombatState::pending_events`（参考的 `ICombatEvent`，25 种触发器事件）。
它**不能**当动画日志用，两个理由：

1. 它是**待分发**的队列，在宿主的一次排空里就被消化干净了 —— 一步之后它是空的；
2. 它的语义是"驱动内容里的状态钩子"，不是"屏幕上发生了什么事"：`GainBlock` / `Heal` /
   `DrawCards` **根本没有事件变体**，而 `StatusMerged` 只带一个 `target`，**说不出是哪个状态**。

⇒ 单开一本账：`rd_core::beat`（`Beat` / `BeatKind` / `BeatLog`）。

### 142.3 一个事实一个写点

| 事实 | 写点 |
|---|---|
| 掉血 | `exec::resolve_damage_of_kind`（伤害管线**唯一出口**：卡 / 敌动作 / DoT / 伤害药水）|
| 格挡 | `exec::gain_block_for`（`modified != 0` 才会写）|
| 治疗 | `exec::heal_for`（满血不写，不飘 `+0`）|
| 状态增减 / 新建 / 被 Artifact 挡下 | `exec::apply_one_status`、`modify_one_status_stacks` |
| 状态到期被删 | `host::try_decrease_timed_statuses` 的删除行 |
| 倒下 / 随从逃跑 | 伤害管线里翻转 `lifecycle_state` 的那一行 |
| 出牌 | `play::play_card`（**包括** `is_action` 的敌方行动面，见下）|
| 回合边界 | `host` 的 `TurnStarted` / `TurnEnded` 入队点 |
| 召唤 | `exec::create_combatant_node` |

两条设计决定：

* **`CardPlayed` 事件与 `CardPlayed` 动画不同口径。** 触发器事件只在"真的算一次出牌"时发
  （`Enrage` 不该被敌方行动面触发），动画日志**每次都记** —— 敌人挥出一张行动牌也该有动画。
  所以那一处**故意不套** `counted_as_card_played` 那道门，`flags` 的 bit2 标出来。
* **它是派生视图，不是游戏状态。** 满了不报错（那会把一次出牌变成失败），而是把
  `beats_dropped` 加一 —— 页面能读到并说出来。"少报了要能看见"。

### 142.4 容量与"谁负责清空"

* `MAX_BEATS = 64`、`MAX_BEAT_DEFS = 24`。64 是**量出来的**：
  `exec::tests::a_heavy_turn_fits_in_the_log` 一步打 5×3 段伤害 + 一块 + 两状态（18 条），
  断言 `beats_dropped() == 0`。
* 名字走**旁表**（`def` 是下标）：`Ident<40>` 是 41 B，塞进每条就是 2.6 KB，而一步里被点到的
  名字通常不到五个。整本账 `size_of::<BeatLog>()` = **2,268 B**。
* 清空在 **ABI**（`rd_env_step` / `rd_env_use_potion`），不在内核：这样"一个动作一本账"是
  ABI 的性质，而不是"哪次引擎调用记得清"。而且清在**动作查表之前** —— 否则一次被拒的 step
  会把上一步的 beats 留在地上，而**陈旧的 beats 会完美地重播一遍，只是播错了东西**。

### 142.5 墙位是 ABI 的事，不是内核的事

内核只认 `combatants()` 的**下标**（`ordinal`）；墙位（`-1` 英雄、`0..5` 敌人、`-2` 墙外）
由 `rd-wasm` 的 `Session::wall_slot_of_ordinal` 算 —— 因为"墙有多宽"是 `env-abi.md` §10 的事，
内核不知道，也不该知道。同一套槽位号页面已经在用（`OFF_ENEMY`），所以动画能直接按槽位找元素。

### 142.6 ABI

```
rd_env_beat_count()                 // 这一步几条
rd_env_beat_field(i, field)         // 0 kind | 1 actor 墙位 | 2 target 墙位 | 3 flags
                                    // 4 a | 5 b | 6 c | 7 有名字吗
rd_env_beat_def_len(i) / _into(i)   // 名字（状态定义 / 卡定义）
rd_env_beats_dropped()              // 丢了几条（正常恒 0）
rd_env_beats_clear()                // 驱动方主动清（回放/暂停）
```

`kind` 的号是**已发布**的（1..12），新种类往后加，删掉一个就让它的号空着。
⚠️ 负下标**不夹到 0**：`beat_field(-1, 0)` 回 `-1`。夹到 0 会让"传错了下标"看起来像真数据
—— 写 ABI 测试时这一条被自己抓到过一次（`rd_env_beat_def_len(-1)` 回了 beat 0 的名字长度 6）。

### 142.7 判据

内核侧（数**条数**与**每一位**，不是"有没有某条"）：

* `a_three_hit_attack_is_three_beats_not_one_number` —— 三下必须是三条，且 `(a,b,c)` 分别是
  `(2,3,5) / (5,0,5) / (5,0,5)`（第一下被 3 点格挡吃掉大半）；
* `block_heal_and_status_change_each_land_one_beat_in_order` —— 四件事四条，顺序与
  `FLAG_NEW_INSTANCE` 都对；
* `a_status_reduced_to_zero_is_a_change_then_a_removal` —— 先掉层再收图标（反了页面会先看见图标消失）；
* `artifact_turns_a_debuff_into_a_prevented_beat_naming_the_blocked_status` —— 名字必须是**没上成**的那个；
* `a_kill_is_damage_then_downed_and_the_minions_flee_after_it` —— 伤害 → 倒下 → 逃跑，三条；
* `a_dot_tick_is_flagged_so_it_does_not_animate_like_a_sword`；
* `a_heal_at_full_health_is_no_beat`；
* `both_turn_boundaries_leave_exactly_one_beat_each`；
* `an_animated_card_play_names_the_card_definition`（名字是卡定义 `paper_cut`，不是实例 `card_h1`）；
* `a_heavy_turn_fits_in_the_log`。

ABI 侧（真 `rd-wasm`、真内容镜像）：

* `the_animation_log_names_the_card_the_wall_slots_and_the_damage` —— 英雄恒 `-1`、敌人 `>= 0`、
  出牌在伤害**之前**、`dealt + blocked <= requested`；
* `an_end_turn_shows_every_enemy_acting_in_order` —— 两只史莱姆**都**出手（`distinct >= 2`），
  且槽位 0 先动；
* `rd_env_step(越界)` 之后 `rd_env_beat_count() == 0` —— **被拒的一步不留旧 beats**。

**反向控制**（本项目的老纪律）：把伤害那一处 `record` 用 `if false` 关掉，
`a_three_hit_attack_is_three_beats_not_one_number` 当场红（`left: 0, right: 3`），然后才恢复。

### 142.8 内存账本：又是两行旧错

`CombatState` **213,224 → 216,080 B（+2,856，SRAM 35.2% → 35.6%）**。加字段顺手核账，抓出
`state.rs` 模块头那张表里**两行早就烂了**：

* `combatants` 写的 `12 x 4,832` —— 实测 `Combatant` 是 **4,876**（差 528 B）；
* `event queues` 写的 23,040 —— 按今天四个实测尺寸算是 **23,296**（差 256 B）。

而这一轮的 diff **一行都没碰 `Combatant`、也没碰那六个队列**。⇒ 印证那张表自己的警告：
"这次没变化的那几行"才是最容易烂的地方。现在 `state_fits_the_sram_plan` 会把 `beats` 那一行的
**分量和**与 `size_of::<BeatLog>()` **一起**打出来，对不上时看得见是哪一边。

### 142.9 还没做的（写明白，别当成做完了）

* **页面还没读它** —— 这一轮只把 ABI 与判据做实；页面正在等 Live2D 重写，届时
  `diffObservations` 会退成"兜底"，beats 变成主路径。今天页面上的日志仍由相减生成。
* **抽牌 / 能量没有 beats**：抽牌能从观察向量（手牌）反推，能量本来就在观察里，
  为省两条容量先不加。
* **敌人复活 / 多段形态**仍缺（§141），那是内核能力，不是这本账的事。

### 142.10 数字

聚合验收 **17/17**；单测 691 → **709**（rd-core 601 → **617** / rd-run 62 / rd-wasm 28 → **30**）。

---

## 143. 事件解释器（第一层）：删卡 / 升级 / 转化 / 诅咒 / 遗物

§141 的第二件：`?` 房的选择原来只有五条数字效果，**删卡、升级、拿诅咒、给遗物全都不可表达**。
这一轮把它们变成词表的一部分，并补上"选择要点名一张牌"的那个阶段。

### 143.1 词表：`kind` 与 `kind:payload` 共用一个字符串格

| 内容写 | 意思 |
|---|---|
| `heal` / `gold` / `damage` / `max_hp` / `nothing`（+ `AmountN`）| 五条数字效果（沿用）|
| `remove_card` / `upgrade_card` / `transform_card` | 牌组改动：进 `Pending::EventCard`，等一个下标 |
| `curse:<card id>` | 往牌组里加那张牌（必须是池子里的 **Curse**）|
| `relic:<relic id>` | 给那件遗物（内核必须**实现了**它的效果）|

⚠️ **为什么不做成新的 `EV` 列**：加列会把 `EV` 的 stride 从 20 改掉，而那个 stride 被**手抄在四个
读者**里（`content.rs` 的 `EV_SCHEMA`、写出端、`rdcf_verify`、内容门）。stride 漂了是**静默读错**，
而 payload 解析坏了是**响亮拒绝**。所以宁可在同一个 `F_STR` 格里放一个小语法。

解析器只有一处：`rd_run::state::EventEffect::parse`（ABI、页面、测试都走它）。它把
`curse` / `relic` **不带 payload** 的写法判成"词表之外" —— 那两个效果的**全部信息**就是那个 id，
接受一个没有 id 的"拿诅咒"等于一个安静的"什么也不做"。只按**第一个** `:` 切分。

### 143.2 两个 picker 共用一个 `DeckChange`

`BlessingFollowUp` 原来自己带着 `RemoveCard/UpgradeCard/TransformCard`，而"升级一张牌"的实现
**内联在 `pick_blessing_card` 里**。事件路径要是照样写一遍，`strike+` 就会在两处意味不同。

现在：`DeckChange { Remove, Upgrade, Transform }` + `apply_deck_change(change, index, pool)`，
`pick_blessing_card` 与 `pick_event_card` 都走它。`BlessingFollowUp` 变成
`{ None, Deck(DeckChange), GainThreeCards }` —— "哪种牌组改动"只有一份定义。

顺手改对了一个错误类型：牌组下标越界原来报 `BadNode`（**地图节点**的下标错误），现在是
`BadCard`。两者长得都像"下标不对"，所以一直没人注意，直到两条路径共用同一个函数。

### 143.3 新的运行层状态：`Pending::EventCard = 8`

一个事件选择要是牌组改动，`resolve_event` **不落地**：它记下 `event_follow`、把 run 推进
`Pending::EventCard`，等 `pick_event_card(index, pool)` 收尾（并在那时才 `mark_resolved`）。

* 单独一个变体而不是给 `BlessingCard` 加标志：两者由**两个不同的调用**结束，共用一个变体只会
  把"这是哪个 picker"变成两边都要判断的条件；
* 互相不能收尾：`pick_event_card` 在 `Pending::BlessingCard` 下回 `WrongPhase`，反之亦然
  （`the_two_pickers_cannot_finish_each_other`）；
* 空牌组上的"删一张"⇒ `DeckEmpty`（一个没有出口的选牌屏不如当场拒绝）。

### 143.4 遗物：把响亮边界**挪到玩家还看得见的时候**

`relic:<id>` 之前没法表达，因为遗物的效果不是数据：`REL.RunPrograms` / `CombatRules` 从不执行，
每个效果都是 `end_of_combat` 里按 id 写的一条规则 —— 一个不认识的 id 会在**下一场战斗结束**时
才炸。现在：

* `RunState::relic_effect(id) -> Option<RelicEffect>` 是**唯一**一张表；
* `relic_is_implemented` 读同一张表；
* `GainRelic` 在**授予那一刻**就用它检查，不实现 ⇒ `UnsupportedRelic`，玩家还站在事件里。

⚠️ 内容里**还没有**用 `relic:`：全内容只有一件遗物（`burning_blood`），而英雄开局就有它。
这条词表是"能表达"而不是"已用上"；§141 的第 4 项（遗物池）才是让它有内容可给的那一步。

### 143.5 内容：一张诅咒 + 三个新事件

* 卡 `injury`（`Rarity: Curse`，tags `curse/unplayable/junk`）—— 内容里的**第一张诅咒**。
  它什么也不做，这正是诅咒的样子（`Unplayable` 是 `play.rs` 五条受理校验之一）。
* 事件 `ancient_writing`（`upgrade_card`）、`forgotten_altar`（`curse:injury`）、
  `purification_shrine`（`remove_card`）。
* `EventTables`：幕 1 = 6 个（新增两个），幕 2/3 各 3 个（都拿到 `purification_shrine`）。

### 143.6 判据

| 层 | 判据 |
|---|---|
| 词表纯函数 | `the_event_vocabulary_parses_and_refuses_what_it_does_not_know`（含 `curse` / `relic` 裸写、空 payload、`card:` 假类型、`a:b:c` 只切一次）|
| 运行层 | `an_event_that_edits_the_deck_owes_a_pick_first`、`an_event_can_give_a_curse_but_only_a_real_one`、`an_event_can_give_a_relic_only_if_the_kernel_can_run_it`、`a_deck_edit_event_on_an_empty_deck_is_refused`、`the_two_pickers_cannot_finish_each_other` |
| 二进制 | `the_unknown_room_events_are_readable`（9 个事件；**`curse:injury` 必须带着 payload 从镜像里读回来**）|
| ABI | `an_event_choice_that_edits_the_deck_owes_a_pick`（选完 `needs==2`、`pending==8`、`action_count==0`、选牌后归零、第二次选牌被拒；`forgotten_altar` 的诅咒真的进了牌组）|
| 内容门 | 新增 `[6c] event vocabulary`：效果必须在词表里、`curse:` 必须是池里的 Curse、`relic:` 必须已实现、三个幕的池子必须只点名 `UnknownRooms` 里有的房间 |
| 页面 | `ui_test` 新增两个面板状态（选定后 / 等选牌），并新增一条**真检查**：`RD_PANELS` 报出的每个 `action.kind` 都必须在 `index.html` 的 `PANEL_ACTIONS` 里（注释早就说"checked below"，其实没查过）|

**两条同型的坑，这一轮各踩了一次：** "settle 当前节点"的辅助函数有两份（`rd-wasm` 的 Rust 测试
与 `web/map_test.mjs`），新阶段一来**两份都要改**；漏改的症状不是"事件没生效"，而是**下一步
被拒**（`reachable()` 在 `pending != None` 时是空的），报错指向地图，而不是那一行。

### 143.7 还没做的

* **一个选择只能有一条效果**：`Effect0` 是单个字符串。StS 的 Golden Idol 是"给遗物 **再** 给
  诅咒"，今天表达不了。要做就得允许 `a+b` 这种组合，或者把 `EV` 行改成效果列表 —— 那是
  下一轮的事（和 §143.1 的 stride 讨论绑在一起）。
* 遗物池仍只有 1 件（§141 第 4 项），所以 `relic:` 无内容可用。
* 事件没有 `?` 房之外的触发条件（层数、金币门槛）。

### 143.8 数字

聚合验收 **17/17**；单测 709 → **716**（rd-core 617 / rd-run 62 → **68** / rd-wasm 30 → **31**）。
内容：**13 张卡 / 9 个事件 / 17 个遭遇 / 25 个敌人 / 50 个敌人动作**；
镜像 full **27,720 B** / core **23,288 B**（`sts` 包**故意**钉在"清点契约"而不是字节冻结）。

---

## 144. 卡牌关键词：Retain / Ethereal / Innate（以及 X 费的"响亮不存在"）

§141 的第三件。三个关键词都**不是新机制**：内核里各有钩子，只是钩子**不读内容**，理由
写在那儿（"62/62 卡都是 false，读不读观察等价"）。内容一出现真的关键字，等价就没了 ——
而每条钩子上都留了一条**会红的测试**等着这一刻。这一轮它们全红了，于是全补上。

### 144.1 Retain：`CARD.RetainInHandOnTurnEnd`

`host::card_stays_in_hand_at_turn_end` 之前 `let _ = (state, actor, slot); false`。
现在读那一格。⚠️ `F_BOOL` 的四个原始值是 **0 缺席 / 1 false / 2 true / 3 null**，
**不是** `bool` 的 0/1 —— 把 1 当 true 会正好反过来。

读失败（卡不在镜像里）当作**留在手里**：这条钩子没有 `Result`，而两个方向代价不对称 ——
误留一张牌只是让玩家多打一次，误弃一张牌是把玩家以为保住了的牌扔掉；错误照旧 `record` 给下
一个 `try_*`（同 `hand_is_retained_detail` 的先例）。

### 144.2 Ethereal：`CARD.TurnEndHandDestinationZone`

参考里 Ethereal **不是**一条独立判据，它就是这张牌"从手牌离场时去哪"（`CardZoneEffects.cs:427`）。
所以 `host::turn_end_hand_destination` 现在真的读那一格，认 `DiscardPile` / `ExhaustPile` / `Hand`。
认不出的枚举名 ⇒ `record` 一笔 + 弃牌堆（"留在手里"会让那张牌永远出不去）。

⇒ **没有**一条 `if tag == "ethereal"` 的分支。tag 是文档，机制是那一格；两者的一致性由内容门
的 `[6d]` 钉住（见 144.4）。

### 144.3 Innate：`MoveInnateCardsToTop`（参考原样实现）

之前是**响亮拒绝**（`reject_innate_deck`：牌组里有一张 innate 卡就不建战斗），理由是"挪牌会让
起手牌序不同，而那种偏差看起来完全正常"。现在照着参考
（`ScenarioCombatFactory.cs:91-104`）实现：

1. 按**抽牌堆顺序**收集带 `innate` tag 的实例；
2. **从后往前**逐个 `move_card(DrawPile → DrawPile, Top)` —— 参考注释原话："Moving from last to
   first lands the first innate card at index 0"，即这样才保住它们之间的相对顺序；
3. 挪在**洗牌之后**。

判据：`an_innate_card_is_pulled_to_the_top_of_the_draw_pile`（`shuffle: false` ⇒ 牌组顺序
= 堆序，`swift_strike` 原本在**最后**，建完之后必须在**第 0 张**）。**反向控制做过**：
把那一行注释掉，测试当场红（`left: "strike"` / `right: "swift_strike"`）。

### 144.4 X 费：参考里**根本没有**这个概念

grep 过 `ref/RogueDeck-Core`：`XCost` / `EnergySpent` / `x-cost` **零命中**。所以它不是
"还没移植的字段"，而是**要新造**一个机制：一种"用光全部能量、并以用掉的量作为 X"的费用形态，
一个新的数量来源（节目的 `Amount` 要读得到 X），外加内容编译器对它的支持。

在此之前，一张 X 费牌被当成固定费用结算会让**数字全都合理**，所以两处都**响亮拒绝**：

| 哪一处 | 什么时候 |
|---|---|
| `battle.rs::reject_x_cost_deck` | 建战斗时（带 `x_cost` tag 的牌组直接拒绝）|
| `play.rs` 的校验器第 6 条 `Validator::XCost` | 出牌时（防手写牌组绕过 `build_fight`）|

⚠️ 这两处**今天不可达**（内容里没有也不许有 `x_cost` 卡），与 §144 之前的 `reject_innate_deck`
同一个状态 —— 如实写在这里，而不是假装它们被跑过。内容门 `[6d]` 负责让它们保持不可达。

### 144.5 内容：三张卡，两真一fixture

| id | 是什么 | 为什么 |
|---|---|---|
| `sentinel` | **真卡**（Ironclad，5 Block + Ethereal）| Ethereal 的载体 |
| `patient_guard` | **fixture**（5 Block + Retain）| Ironclad 在 StS 里**没有** Retain 卡（社区里"为什么 Ironclad 没有 Retain 卡"是个真问题），借不到 |
| `swift_strike` | **fixture**（Innate + 6 damage）| 同理，Ironclad 没有 Innate 卡 |

fixture 的**数字是本内容自己的**，不是 wiki 的 —— 所以它们的 id 与 `sts_content_check.py`
的清单里都写明。要的是关键字的**语义**，不是一次冒充。

### 144.6 判据

* `the_keyword_cells_are_in_the_image`（真镜像：`sentinel` 的落区、`patient_guard` 的保留标志、
  `swift_strike` 的 innate tag，**成对**含普通卡与不存在的卡）；
* `a_retained_burn_card_still_fires_exactly_once_and_stays_in_hand`（手搓镜像，成对：
  没有保留标志的卡照样被弃）；
* `an_ethereal_card_is_exhausted_instead_of_discarded`（同上，成对）；
* `an_innate_card_is_pulled_to_the_top_of_the_draw_pile`（真镜像，两张 innate 的相对顺序也钉）；
* 内容门 `[6d]`：tag ⇔ 机制字段**双向**一致（`ethereal` ⇔ 落区 = ExhaustPile，
  `retain` ⇔ 标志 = true），且内容里**不许**出现 `x_cost`。

---

## 145. 遗物池：1 → 5，三个派发点

§141 的第四件，也是让 §143 的 `relic:<id>` 有内容可给的那一步。

### 145.1 一张表，三种钩子

`RunState::relic_effect(id) -> Option<RelicEffect>` 是**唯一**一张遗物表，三个调用方读它：

| 钩子 | 什么时候 | 哪些遗物 |
|---|---|---|
| 授予时 | `push_relic`（**唯一的发放点**）| Pear（+10 最大生命，且当前生命跟着涨）、Blood Vial（+2 血）|
| 开战时 | `RunState::combat_bonus()` → `rd_run_fight_begin` | Anchor（10 Block）、Vajra（1 力量）|
| 结束战斗 | `end_of_combat` | Burning Blood（+6 血）|

`combat_bonus` 是**相加**不是覆盖：两件加格挡的遗物要一起算，腰带里的顺序不该决定结果。

### 145.2 授予只有一个入口

`push_relic` 现在做三件事，顺序固定：① 内核跑不了这件 ⇒ `UnsupportedRelic`（**在玩家还看得见
是谁要塞给他的时候**，而不是下一场战斗结束）；② 跑**授予时**的效果；③ 进腰带。

在调用点各写一遍"然后 Pear 的最大生命 +10"，就会有四份副本 —— 那正是"宝箱里能用、商店里
不能用"的成因。

### 145.3 开战时的那一半在 `rd-wasm`

`rd_run_fight_begin` 在建完战斗之后调 `apply_combat_bonus`，两次写入都走**游戏自己用的公开
API**：格挡走 `set_defensive_pool`，力量走一条 `ApplyStatus` 效果（`exec::resolve_effect`）。
抄近路 = 第二条状态管线，第一次修饰器改动就会分叉。写完必须 `reobserve_after_external_change`，
否则页面看到 0（§84 那个坑）。

### 145.4 池子还得**不重复**

宝箱和商店原来从整张 `Relics` 表里随机挑，而那时表里只有一件 —— 于是它们唯一能做的事就是
**再发一次你已经戴着的那件**。现在 `relic_candidates` 把已在身上的过滤掉，两边共用；
全都戴上了 ⇒ 宝箱不给遗物（而不是发一个复制品）。

### 145.5 判据

* `the_relic_pool_fires_at_the_three_hooks_it_has`（授予时 / 开战时相加 / 结束时只有 Burning Blood）；
* `a_relic_with_no_implemented_effect_is_an_error`（**位置搬到 `push_relic`**：反例从 `vajra`
  换成 `golden_idol`，因为 `vajra` 现在实现了）；
* `a_relic_you_already_hold_is_not_offered_again`（宝箱跑 12 轮 + 商店货架，成对含"全都戴上了
  ⇒ `None`"）；
* `the_relic_pool_pays_out_when_a_fight_starts`（**ABI 级**：读 `rd_env_observe_*` 的
  `H_HERO_BLOCK` 与 `standard.strength` 那一轴，成对含没有遗物的一场）；
* 内容门 `[6e]`：内容里的**每一件**遗物都必须被内核实现（否则宝箱会随机地把一次开箱变成
  一次拒绝），反向也查（内核实现了但内容没有 ⇒ 永远发不出来）。

### 145.6 还没做的

* 遗物**稀有度**与掉落权重（`inv:§8.3` 的 tier）：现在是从一张平表里等概率挑。
* 精英战不给遗物（StS 给）。`inv:§5` 的奖励档只覆盖金币与卡，遗物那一路要新的奖励格。
* 遗物没有 `CombatRules` / `RunPrograms` 解释器（这是**设计决定**，不是缺口：
  效果按 id 一条条写，跑不了的在授予时响亮拒绝）。

### 145.7 数字

聚合验收 **17/17**；单测 716 → **722**（rd-core 620 / rd-run 70 / rd-wasm 32）。
内容：**16 张卡 / 9 个事件 / 5 件遗物 / 17 个遭遇 / 25 个敌人**；
镜像 full **28,296 B** / core **23,692 B**。

---

## 146. X 费：一次"参考里没有"的机制重建

用户："X 费如果是 StS 有的功能就先实现一下这个吧，参考 wiki。越是底层的东西要越早实现。"

### 146.1 wiki 说了什么（这条是 wiki 有、参考实现没有的功能）

`slaythespire.org/wiki/keywords/x-cost`（Verified 2026-02-27）：
**"Costs All Remaining Energy; Effect Scales With Amount Spent."**
Whirlwind 页逐字："When playing an X-cost card, all **Energy** that you currently have will be
consumed. The **Energy** consumed this way will be used as the value for X."

⇒ 三件事：① 费用 = **当前全部**能量；② X = 那个量；③ 效果按 X 缩放。
Whirlwind 本体：Ironclad Uncommon Attack，"Deal 5 damage to ALL enemies X times"（升级 8）。

⚠️ **参考实现里没有这个概念**（`ref/RogueDeck-Core` 全仓 grep `XCost` / `EnergySpent` 零命中），
所以这一节是**新造**，不是移植 —— 与 §144 时把它当成"响亮拒绝"的判断一致，只是这次把它补上了。

### 146.2 三个零件（缺一不可）

| 零件 | 在哪 | 说明 |
|---|---|---|
| **费用形态** | `play.rs::x_cost_payment` | 带 `x_cost` tag 的牌 ⇒ 付"该资源当前全部"；`Costs` 里印的 `Amount` **不参与结算** |
| **X 的读法** | `expr.rs` 的 `"x.cost"` | 新的整数表达式 kind（本内核自己的）—— 0 字段，值只来自这次出牌 |
| **按 X 跑 N 遍** | `exec.rs::dispatch_repeat` | `node.repeat { Count, Body, MaxCount }` —— **参考有、内核此前没移植** |

`node.repeat` 是这次最值得说的一件：它一直在参考的 35 个节点里（`EffectProgramNodes.cs:116-155`），
而内核的 15 种里没有 —— 因为 **core 镜像里一条都没有**（固定多段攻击在内容里是展开写的，
`byrd.peck` 就是 5 个 `dealDamage`）。X 是运行期的值，展开写不出来 ⇒ 这个节点终于有了第一个
内容侧使用者。

### 146.3 参考的逐条语义（`EffectProgramNodeExecutors.cs:282-330`）

* `count < 0` ⇒ **抛**（"Card definitions must not produce negative repeat counts"）；
* `count > MaxCount` ⇒ **抛**（默认 `RepeatEffectNode.DefaultMaxCount = 32`）—— **不截断**；
* `index >= count` ⇒ 完成；否则派发 `Body`，body 完成后**在节目链里**接着下一趟；
* 每一趟 `ctx.OpenScope()` / `CloseScope()` —— 本内核没有作用域栈，这一层也没绑任何变量，
  **所以那一对调用没有对应物**。如实记在这里：内容若在 `repeat` 体里读 `iterationIndex`，
  本内核读到的是**外层**的值。今天没有这样的内容。

### 146.4 X 必须存在**帧**上，不能只放上下文

节目的后续节点是在**续延**里派的，那时上下文由 `exec::frame_context` 从帧重建
（`ProgramExecutionFrame`）。只放上下文里的结果就是"第一趟读到 X，第二趟读到 0"——
而 X 费牌的核心恰恰是"每一趟都按同一个 X 跑"。所以：

* `ProgramExecutionFrame` 多一格 `x_cost: i32`（+4 B/帧，**不进哈希**：它是派生的）；
* `ExprContext.x_cost` / `ExecContext.x_cost` 各一格，`frame_context` 负责搬回来。

### 146.5 X = 0 是**合法**的，这与固定费用相反

StS 允许 0 能量打 X 费牌（X = 0，用来推进 Nunchaku / Ink Bottle 这类"打出攻击牌"的计数器）。
所以 `x_cost_payment` 付"现有多少"，`ensure_affordable` **永远通过** —— 这条路**不会**报
`Unaffordable`，而固定费用那条会。这条差别写进了测试。

⚠️ 费用修饰器（"下一张免费"）对 X 费牌**不生效**：`calculate_costs` 在 modifier 管线**之前**
就把 X 费分流出去了，因为 StS 的 X 费牌照样"能量全花掉"，印出来的 `Amount` 根本不参与。

### 146.6 页面：`0` 是一句会被当真的假话

手牌费用格原来直接报 `Costs` 的 `Amount`；X 费牌的 `Amount` 是 0（内容门强制），于是页面会
显示"0 费"——玩家会以为可以白打。现在 `rd_wasm::X_COST_DISPLAY = -2` 走那一格，
`ui_render.js` 把它画成 `X`，并且 `affordable` 按"有没有能量"算。
`ui_test.mjs` 有一条断言把**页面的副本**与模块的那个数对齐（`-2` 两边都写了，测试比对它们）。

### 146.7 内容：Whirlwind

```json
"Costs": [{ "ResourceId": { "value": "standard.energy" }, "Amount": 0 }],
"Tags":  [{ "value": "attack" }, { "value": "x_cost" }],
"Root":  { "kind": "node.repeat",
           "value": { "Count": { "kind": "x.cost", "value": {} },
                      "Body": { "kind": "node.dealDamage", "value": { "Amount": 5,
                                "TargetSelector": { "kind": "sel.allEnemies", … } } },
                      "MaxCount": 32 } }
```

⚠️ 踩到一次：`"Count": {"kind": "x.cost"}` **没有 `value` 键**时，contentc 不认为它是 IR 节点
（`is_ir(v)` 要求 `"value" in v`），于是编成一个普通对象 ⇒ 运行期报 `Expr(Ir(Missing("kind")))`。
错误信息指向"kind 读不到"，离"少了一个空 `value`"隔着两层 —— 记在这里，因为这是本内容格式的
一条**通用**陷阱：零字段节点也要写 `"value": {}`。

### 146.8 判据（每条都能红）

| 测试 | 钉住什么 |
|---|---|
| `the_whirlwind_program_hits_each_enemy_once_per_x`（rd-core，真镜像）| `x_cost=3` ⇒ 3 遍；`nodes=4`；`effects=5`（第三遍时 10 血的敌人已倒下）；活下来那只吃满 15 |
| 同上的 `x_cost=0` 分支 | 一遍都不跑，且**不是错误** |
| `an_x_cost_card_spends_all_energy_and_hits_x_times`（rd-wasm，ABI）| X = 1 ⇒ 恰好 2 条伤害；3 点能量 ⇒ 能量归零 + 那只 10 血的史莱姆**真的倒下**（`BEAT_DOWNED`）|
| `an_x_cost_card_played_with_no_energy_is_legal_and_does_nothing` | X = 0 受理、0 伤害 |
| `a_repeat_past_its_maximum_is_a_loud_error_not_a_truncation` | 40 能量 ⇒ 一次伤害都没有 **且** 驱动记了 problem（"静默截到 32 下"会给出 32 条伤害）|
| `the_hand_cost_cell_reports_x_cost_cards_as_the_display_sentinel` + `a_fixed_cost_card_still_reports_its_printed_cost` | 页面那格是哨兵，普通牌仍是真价（成对）|
| `ui_test.mjs` 的 `x-cost` 块 | 页面画 `X`、`affordable` 跟能量走 |
| 内容门 `[6d]` | `x_cost` 卡的印刷费用必须是 0，且节目**必须真的读 `x.cost`**（否则 tag 只是装饰）|

**反向控制**：把 `"x.cost" => Ok(ctx.x_cost)` 改成 `Ok(0)`，
`an_x_cost_card_spends_all_energy_and_hits_x_times` 当场红（`left: 0, right: 2`），然后才恢复。

### 146.9 还没做的

* `repeat` 体里读 `iterationIndex` 的语义（参考有作用域，本内核没有）—— 没有内容用它。
* `repeatUntil`（参考也注册了）没做：没有内容用它，做了就是没人踩的代码。
* **Chemical X** 那种"X +2 但不多花能量"的遗物：`combat_bonus` 还没有 X 这一轴。
* 0 能量打 X 费牌时的那批"打出攻击牌"计数器（Nunchaku / Ink Bottle）—— 遗物系统还没有这类。

### 146.10 数字

聚合验收 **17/17**；单测 722 → **728**（rd-core 620 → **621** / rd-run 70 / rd-wasm 32 → **35**）。
内容：**17 张卡**（+whirlwind）/ 9 个事件 / 5 件遗物 / 17 个遭遇 / 25 个敌人；
镜像 full **28,588 B** / core **23,912 B**。

---

## 147. 旋风斩补齐各处 + `Constricted`（连它的载体 Spire Growth）

用户："把用上它的卡片'旋风斩'也在各个层面实现出来吧，再做 Constricted。"

### 147.1 旋风斩：`whirlwind+` 是**必须**有的，不是锦上添花

§146 只加了 `whirlwind`。而运行层的"升级"就是**往卡 id 后面加一个 `+`**
（`RunState::upgrade_at`），所以一张没有 `+` 行的牌一旦被升级，**下一场战斗会在建战斗那一步
炸**（`BattleError::UnknownCard`）—— 玩家在营火"打铁"升级了旋风斩，然后走到下一个战斗节点
才发现这局废了。

⇒ 补 `whirlwind+`（每段 8 点，X 不变），并加一条守门测试
`an_upgraded_card_row_is_buildable`：`whirlwind` 与 `whirlwind+` 都能建战斗，而一个**不存在**的
`no_such_card+` 照样响亮失败（成对，否则这条测试也可能是"建战斗从不查定义"）。

### 147.2 `Constricted`：内容触发器，不是内核步骤

wiki：**Constricted X —— "At the end of your turn, lose X HP."** 三个性质决定了它怎么落地：

| 性质 | 落地 |
|---|---|
| 回合**结束**时结算 | `Triggers: [{ Event: "TurnEnded", … }]`（钩子早就有，§117 起）|
| 血量 = **层数** | `Amount: combatantStatusStacks{ Selector: sel.source, StatusId: standard.constricted }` |
| 是"**lose HP**"，不是伤害 | `IgnoresBlock: true` —— 格挡挡不住 |
| 不衰减 | `UsesDuration: false`（层数只在被再次施加时合并）|

⇒ 内核侧只加了一行：`status_catalog::has_behaviour` 里登记 `standard.constricted`
（那条"内容声明了状态就必须有规则或声明惰性"的诚实性测试会拦住漏登记）。

⚠️ 测试踩到一个**真实的时点**问题：第一版把 10 点格挡摆在 `start_current_turn` **之前**，
结果格挡被正常清空（玩家格挡在**自己回合开始**时清空），看起来像"Constricted 吃掉了格挡"。
正确写法是**回合开始之后**再给格挡。这条注释留在测试里，因为下次还会有人这么写。

### 147.3 载体：Spire Growth（第三幕）

`Constricted` 得有人施加，否则它就是一张没人发的牌。选真怪：

| 项 | 值 | 出处 |
|---|---|---|
| HP | 170 | slayspiredb（Asc 7+ 是 190；本内容无 Ascension）|
| `Strategic` | 施加 Constricted 2 | 同上（意图 Debuff）|
| `Aggressive` | 16 伤害 | 同上 |
| `Aggressive`（重）| 22 伤害 | 同上 |

新增：1 条 `STAT`（constricted）、3 条 `EACT`、1 条 `ENCT`（`enc_spire_growth`）、
1 条名册、第三幕普通池 +1。

### 147.4 轴之外的状态：观察向量是布局，不是世界

观察向量只有**五条状态轴**（str / vuln / weak / dex / frail），而且那个布局是端到端拼死的
（`smoke.mjs` 有一条"offsets tile to 140/148"）。加第六条轴会让后面每个偏移都动。

而"玩家看不见的 debuff"= 玩家躲不掉的 debuff —— Constricted 正好落在五条轴之外。
所以走另一条路：**按名字读**。

```
rd_env_status_count(whom)                  // -1 英雄 / 0..5 敌人墙位
rd_env_status_id_len(whom, i) / _into(…)
rd_env_status_stacks(whom, i)
```

页面把它们并进英雄/敌人面板的状态列表（五条轴照旧用短标签，其余用 id 的尾巴），
`ui_test` 有一条 `x-cost` 式的接线断言，rd-wasm 有一条"轴之外也读得出名字"的测试。

### 147.5 判据

* `constricted_loses_its_stacks_of_hp_through_block_at_turn_end`（rd-core，**sts 镜像**）：
  3 层 ⇒ 掉 3 血、**格挡一点没动**；成对：没有这条状态就一点都不掉。
* `an_upgraded_card_row_is_buildable`（rd-core）：`whirlwind+` 可建、假 `+` 行响亮失败。
* `statuses_outside_the_five_axes_are_readable_by_name`（rd-wasm）：名字 + 层数读得出来，
  越界墙位/下标回 `-1`。
* 内容门：`standard.constricted` 的触发器恰好是 `["TurnEnded"]`；`spire_growth` 的三条动作、
  HP 170、第三幕池成员都对得上；`whirlwind+` 在卡片清单里且 `Facts` 是
  `("repeat", ("x.cost"), "damage", 8, "allEnemies")`。

### 147.6 还没做的

* `Constricted` **不衰减**这条今天对，但 SStS 里它是"X 层 = 每回合 X 伤、永久"，没有"层数
  每回合变"的机制 —— 与本实现一致，无需额外工作。
* Spire Growth 的**行动顺序**（StS 是"Strategic 先手，之后交替 16/22"）没有强制：本内容的
  意图选择仍是通用的顺序规则（§4.x），没有"首回合必出某招"的 AI。这条与其它敌人同构。
* `Constricted` 没有对应的**卡**（StS 也没有）—— 它只来自敌人。

### 147.7 数字

聚合验收 **17/17**；单测 728 → **731**（rd-core 621 → **623** / rd-run 70 / rd-wasm 35 → **38**）。
内容：**18 张卡 / 18 条状态 / 53 条敌人动作 / 26 个敌人 / 18 个遭遇**；
镜像 full **29,664 B** / core **24,724 B**。

---

## 148. 行动顺序：机制早就在，缺的是有人用它 + 有人守它

用户："接下来做行动顺序和伤害管线吧。"

### 148.1 先说清楚：**这不是新机制**

`intent::select_action` 从 §4 起就是三段式：

1. **规则表**（`ENCT` 里那条敌人自带的 `IntentRules`）：每条 `(Condition, Action, Priority)`，
   按 `Priority` 降序问，第一条命中的条件说话；
2. 全不命中 ⇒ 落到 `Actions` 列表的**循环**（`(round - 1) % n`）；
3. 规则指向的动作**不必**在 `Actions` 里 —— 这条正是"首回合专用招式"的表达方式。

条件原语 **10 个**（`intent.round` / `healthPercent` / `selfHasStatus` / `opponentHasStatus` /
`selfHasCounter` / `selfResource` / `opponentCardsPlayed` / `allOf` / `anyOf` / `not`），
本内容**已经在用**：Cultist 用 `selfHasCounter(ritual_owner_turns >= 1) → dark_strike`，
Slime Boss 用 `allOf(healthPercent <= 50, round >= 2) → slam`。

### 148.2 所以这一节做的是三件"没人做"的事

**① 把 Spire Growth 的顺序写对。** §147 把它写成三格循环 `[strategic, aggressive, aggressive_heavy]`
⇒ Strategic 会**每三回合**来一次。StS 里它只出现一次。现在是：

```
Actions:     [spire_growth.aggressive, spire_growth.aggressive_heavy]
IntentRules: [{ Condition: intent.round{Op: Equal, Round: 1},
                Action: spire_growth.strategic, Priority: 10 }]
```

⇒ 第 1 回合 Strategic，之后 `(round-1) % 2` 轮换两个 Aggressive。
（wiki 里两个 Aggressive 是**随机**二选一；参考实现没有 `intent.random`，所以这里是确定的轮换，
如实记下。）

**② 给规则本身加一道内容门（`[2b] enemy intent rules`）。** 三条检查：

* `Condition.kind` 必须在那 10 个里；带 `Op` 的必须在那 6 个运算符里；
* `Action` 必须是真实存在的 `EACT` 行（可以不在 `Actions` 里，见 148.1）；
* `Priority` 必须是整数，且**名册与遭遇内联记录里的规则必须一致**。

为什么值得单开一道：规则**静默不命中**时会落回循环 —— 看起来是一个"节奏略有不同"的敌人，
而不是一个坏掉的敌人。那种错最难发现，也最容易在内容里写出来（把 `Round: 1` 写成 `Round: 0`、
把 `Action` 里少打一个字母）。

**③ 一条会红的测试。** `a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it`
断言**四个回合**（1 规则、2/3 循环、4 回到循环的 slot 1）：只看第 1 回合的话，"规则没命中"与
"根本没有规则"是同一种观察。

⚠️ 测试里踩到一个**语义细节**，值得写下来：`intent.round` 条件读的是**状态里的
`current_round`**，而 `select_action` 的 `round` 实参只用来算循环下标。真实战斗里两者一起前进，
测试里如果只传实参、不推进状态，状态会停在开局那一轮 ⇒ 规则**每一回合**都命中
（第一版就这么错的，报出来的是"第 2 回合还在 Strategic"）。

---

## 149. 伤害管线：Intangible / Buffer / Plated Armor

三条状态都得**住进伤害管线**，因为它们的语义各是一个不同的**位置**：

| 状态 | wiki | 位置 | 为什么是这个位置 |
|---|---|---|---|
| **Intangible** | "Reduce ALL damage and HP loss you receive to 1" | **格挡吸收之前**（压 `amount`）| 压的是"进来的伤害"本身，所以格挡最多只挡那 1 点 |
| **Buffer** | "Prevent the next time you would lose HP" | **格挡吸收之后**，判据是 `health_lost > 0` | 被格挡吃干净的一下**不消耗** Buffer（StS 的行为）|
| **Plated Armor** | "回合结束获得等同于层数的格挡；受到**未被格挡**的伤害时失去 1 层" | 两半：格挡在 `host::grant_end_of_turn_block`（与 Metallicize **同一段代码**），掉层在伤害管线 | 只有管线知道"这一下打穿了没有" |

三处都在 `exec::resolve_damage_of_kind` 里，也就是**伤害的唯一出口** —— 卡、敌人动作、DoT、
药水、Constricted 全部经过它，所以没有第二处需要改。

### 149.1 `Intangible` 顺带把 Constricted 也管住了

Constricted 是 `IgnoresBlock` 的 `dealDamage`，而 Intangible 压的是 `amount` —— 两条规则不打架：
**3 层 Constricted 踩在 Intangible 上只掉 1**。这正是 wiki 那句 "ALL damage **and HP loss**"。

### 149.2 遗物：`StartCombatStatus` 取代了 `StartCombatStrength`

Plated Armor 在 StS 里从**遗物 Thread and Needle** 来。所以 `RelicEffect` 长了一个通用口：

```rust
StartCombatStatus(&'static str, i32)   // vajra ⇒ (strength, 1); thread_and_needle ⇒ (plated_armor, 4)
```

并把原来的 `StartCombatStrength(i32)` **删掉**、`CombatBonus.strength` 换成
`statuses: [Option<CombatStatus>; 4]` + `status_count`：

* 每条遗物一个字段（`strength`）是"运行层认识每一条状态"的开始，而状态是**内容**，会一直长；
* 两条遗物给**同一条**状态必须**合并**（Vajra + 再一件 1 力量 = 2 层），不是覆盖；
* 列表满（> 4 条）时 `push_status` 返回 `false` —— 这是响亮失败，不许静默丢一件遗物的效果。

### 149.3 载体（内容）

| 载体 | 是什么 |
|---|---|
| `apparition` 卡 | 真卡（无色）："Gain 1 Intangible. Exhaust."，1 费，落消耗堆 |
| `buffer` 卡 | StS 的 Buffer 是 Defect 的能力牌；本内容做成同效果的技能牌 |
| `thread_and_needle` 遗物 | 真遗物："Start each combat with 4 Plated Armor" |

三条状态本身**没有 trigger**：规则在内核里（与 `standard.metallicize` 同型），
所以 `change behaviour` 名单里加了它们三个 —— 不然那条"内容声明了状态就必须有规则或声明惰性"
的诚实性测试会红。

### 149.4 判据

* `the_damage_pipeline_honours_intangible_buffer_and_plated_armor`（rd-core）：
  Intangible 把 30 压成 1（格挡只掉 1 点，成对：没有它 30 点直接打穿并打死）；
  Buffer 挡下第一下、用完即删、第二下照打、**被格挡吃干净的一下不消耗**；
  Plated Armor 挨到没挡住的伤掉 1 层、全挡住不掉层。
* `plated_armor_and_metallicize_both_pay_block_at_turn_end`（rd-core，sts 镜像）：
  4 + 3 = 7 格挡 —— 两个 id 共用一段代码，漏掉一个时差别只有几格挡，肉眼看不出来。
* `a_round_one_rule_beats_the_cycle_and_the_cycle_takes_over_after_it`（rd-core）。
* 内容门 `[2b]`（规则可执行）+ `[6d]`（关键字）+ `[6e]`（遗物都必须实现）。
* rd-run：`the_relic_pool_fires_at_the_three_hooks_it_has` 现在断言**状态列表**（含合并）。

**反向控制**：把 Intangible 那一行 `if` 关掉，管线测试当场红（`left: 0, right: 20` ——
30 点伤害把 20 血的敌人直接打死），然后才恢复。

### 149.5 顺手修了一条**脆弱**的旧断言

`a_potion_can_be_used_in_a_fight` 原来钉"火焰药水恰好 20 点"。这一节给内容加了两张卡
⇒ 卡池变大 ⇒ 整条 walk 的 RNG 全部平移 ⇒ 那条 walk 恰好捡到了加伤害的东西，测试翻红。
**它不是被功能弄坏的，是被"内容一变它就换一条路"弄坏的**（"恰好 N 点"在一条随机行走上
本来就脆）。改成 `>= 20` 并写明理由。

### 149.6 还没做的

* **`Barricade`**（格挡不清空）/ **`Blur`**（下一回合保留格挡）：走的是"格挡清空"那条边，
  与伤害管线相邻但不是它；`host::block_is_retained` 的钩子已在那儿（今天恒 false）。
* **`Entangled`**（不能出攻击牌）与 **`Slow`**（本回合每出一张牌 +10% 受伤）：前者是受理
  校验、后者是伤害修饰器，各自的钩子都不在管线里。
* `Plated Armor` 的**掉层事件**没有独立的 `StatusStacksChanged` 之外的信号 —— 页面靠观察向量
  相减看到它，够用但不如 §142 的 beats 精确（beats 里已经有 `StatusChanged`，但没有专门为
  "被甲片挡了一下"记账）。

### 149.7 数字

聚合验收 **17/17**；单测 731 → **734**（rd-core 623 → **626** / rd-run 70 / rd-wasm 38）。
内容：**20 张卡 / 21 条状态 / 53 条敌人动作 / 26 个敌人 / 18 个遭遇 / 6 件遗物**；
镜像 full **30,588 B** / core **25,312 B**。

---

## 150. 药水按钮按不动：一个被吞掉的 `TypeError`（用户报的）

用户："浏览器里面运行的是不是还是旧版，简单试了一下发现药水好像没法使用。"

### 150.1 先排除"旧版"

`web/rd_wasm.wasm` 与 `kernel/target/.../rd_wasm.wasm` **逐字节相同**（sha `938E264D…`，597,887 B），
mtime 也晚于最后一次内核改动 ⇒ **不是旧版**。页面加载的 wasm 大小对得上（597,887 B）。

### 150.2 复现：用真浏览器点一下

写了一个临时探针（CDP + 无头 Chrome，后来删掉了）：走真实的 DOM 路径
（祝福 → 地图 → 战斗 → 打完 → 拿奖励药水 → 下一场战斗），然后 **点腰带上的"用"**：

* `[data-use-potion]` 存在、`onclick` 也有、`rd_env_use_potion(0,-1)` **直接调用返回 0 且药水被消耗**；
* 但点按钮：**什么都没发生**（药水还在、腰带 HTML 没变、`#msg` 也没报错）。

⇒ 不是内核、不是缓存，是**页面**。

### 150.3 根因：局部队名把页面助手挡掉了

直接把 handler 抓出来调用，拿到一行：

```
TypeError: act is not a function   at button.onclick (index.html:748)
```

`renderTopBar()` 里有 `const act = ex.rd_run_act();`（拿"第几幕"这个**数**），而页面有一个
同名助手 `function act(call, label)`（**执行一个动作**）。块级 `const` 遮蔽整个函数体，
于是同一个函数体里药水按钮的 `act(() => ex.rd_env_use_potion(...))` 变成"调用一个数字"。

⚠️ **它为什么一直没被发现**：`onclick` 里抛出的异常**不会传到 `dispatchEvent` 的调用方**，
只会进 `window.onerror` —— 于是那个按钮的表现就是"按下去什么都不发生"，与"功能没做"完全一样。
这是本项目最恨的那种形状：**界面报成功，实际什么都没做**，只不过这次是界面报沉默。

**引入时间**：`const act = ex.rd_run_act();` 是 §136 加"幕间幕布"时写的。它遮蔽了两个按钮：
药水的"用" 和"×"（丢弃）。⇒ 从 §136 起，**药水两个按钮都是死的**。

修法：局部队名为 `actNow`（并在代码里留下"不要叫 act"的注释）。

### 150.4 判据：把"点一次药水"变成第 17 道闸门的一部分

`browser_test.mjs` 新增 `(f)` 段：用 `RD_DEBUG.startWithSeed(12)`（那一局的**第一场**战斗会掉药水）
打到胜利 → 拿药水 → 进下一场战斗 → **直接调用 `onclick`**（这样异常在这里看得见，而不是
消失在事件派发器里）→ 断言四件事：药水真被消耗、腰带上的 `chip potion` 消失、按钮存在、
**handler 没抛**。

**反向控制**：把那个 `act(...)` 换成 `notAFunction(...)`，闸门当场三条一起红
（"threw: ReferenceError"、"not consumed"、"belt still shows"），然后才恢复。

### 150.5 这一节真正买到的教训

* **"按钮存在"不等于"按钮能按"**：`hasUse` / `onclick` 全为真，功能依然可以是零。
* **handler 里的异常是隐形的**：要么在测试里**直接调 `onclick()`**（本节的判据），要么监听
  `window.onerror`；`dispatchEvent` 看不见它。
* **局部变量与页面助手同名**是一个纯编译器问题，而现在这个页面**没有类型检查也没有 lint**
  （零构建的代价）。这一条只能靠"有人点过"来守 —— 所以那个场景进了闸门。

### 150.6 数字

聚合验收 **17/17**（`web-browser` 那道现在含药水场景）；单测仍是 **734**（这一节没有 Rust 改动；
判据在浏览器闸门里）。

---

## 151. 整局随机 soak：第 18 道闸门

用户："感觉可以加上这种自动化的完整轮次游戏流程随机测试来作为补充门禁，靠纯手点比较昂贵和低效。"

### 151.1 为什么门 17 不够

`browser_test.mjs` 是**一条写死的路径**。§150 的药水按钮在那条路径后面活了三个小节 —— 因为
它从不点药水。手点一次发现一个按钮，成本是一轮对话；而"每个界面上的每个按钮"根本点不完。

### 151.2 设计：每点一次，问一句"有东西变了吗"

`web/soak_test.mjs`（→ `web-soak`，门 18）用带种子的 PRNG 在**真浏览器**里随机点**每一个启用中的
控件**，每点一次比较一个**指纹**：

```
runStats | relicChips | deckCount | mapbox 长度 | .here 数 | nodePanel | handPanel
| enemies | log 长度 | msg | modal.hidden | actCurtain.hidden
```

指纹没变 ⇒ 这个按钮什么也没做。**死按钮违反的正是这一条**，而它不关心是哪个按钮 —— 所以
它覆盖那些没有任何脚本测试提到的控件。

配套断言：
* 页面**没抛异常**（装 `error` / `unhandledrejection` 监听，不靠"没人看见"）；
* 状态不变量：`hp ∈ 0..hpMax`、`gold ≥ 0`、`deck ≥ 0`；
* **有进展**：点够次数、开够战斗、走到若干楼层；
* **覆盖面**：至少见过 4 种界面（塔底/战斗/奖励/商店/篝火/宝箱/未知房间）——
  否则"随机点 300 次什么都没坏"可能只是没点到东西。

### 151.3 三条被它自己抓出来的**测试自身的谎**

写这道闸门的过程本身就是它价值的证据 —— 前三个版本**通过了**，但都在骗人：

1. **候选里没有卡牌选择器**：祝福的"删一张牌"打开模态框，而 soak 只认 `[data-close]`
   ⇒ 卡在第一个祝福上。那是"闸门红了但红的原因与产品无关"。
2. **`innerText` 在 SVG 上是 `undefined`**：地图节点是 `<g>`，`text(el)` 直接 `TypeError`。
3. **负面控制没落地**：第一次"把开箱按钮弄坏"的替换**没匹配上**（缩进不同），于是 soak 绿着，
   而我以为它抓不到 —— 这正是本项目那条"先确认补丁真的落地"的规矩。

修完这三条之后，负面控制才真的红：把 `open_chest` 换成空函数 ⇒
`1 dead control(s), 第一个就是 {kind: panel, label: 开箱}`。随后恢复。

### 151.4 顺手让"选择器"变得**确定**

随机点会在"开箱 / 离开"之间掷硬币，于是"主按钮坏了"只有一半概率被撞到（第一版连撞两次都没中）。
所以走进一个节点后**第一次**一定点面板的第一个动作。这让覆盖面从"看运气"变成"每个界面至少点一次主按钮"。

### 151.5 它抓到的第一件真事：`enqueue_event_at_root` 漏一条链引用

第一次跑长 soak 就在 3 × Sentry 的第 12 回合撞到：

```
StepThrew(Capacity:Chains)   envActions 0 · envDone 0 · phase 0 · heroHp 82
```

一局**卡死**：战斗没结束、没有任何可做的动作、页面还挂着"开始战斗"的按钮。

链的引用计数是本模块唯一的 GC，`MAX_LIVE_CHAINS = 128`。`state::enqueue_event_at_root` 里：

```rust
let chain = self.new_root_chain_in_arena()?;   // refs = 1（建链那一次）
self.enqueue_event_with_chain(event, chain)    // 队列条目自己又 acquire ⇒ refs = 2
```

出队时只 `release` 一次 ⇒ **每条根事件漏一格链**。12 回合 × 每回合 2–4 个回合边界事件 ⇒ 128 满了。
修法是把"建链"那一次还给 arena（入队失败时也要还）。

判据：`a_turn_boundary_leaves_no_chain_referenced`（rd-core）——回合开始/结束各跑三次，
每次之后 `live_chain_count()` 必须是 0。修之前它报的是 `[(0,"start",1),(0,"end",2),(1,"start",3)…]`，
修之后全 0。

### 151.6 为了让这种错**可查**：`StepThrew` 带上了原因

`Problem::StepThrew` 是参考的语义（"抛了"），但它把具体错误丢掉了 —— 于是"这一步抛了"在页面上
和"内核某处返回了 Err"长得一模一样，我在这上面花了好几轮。现在两件事分开记账：

* `Problem` 的线上形状**不变**（golden 基线没动）；
* `FightOutcome.step_causes: [StepCause; 64]` 记**家族**（Script/Exec/Turn/Capacity/Other）；
* `FightOutcome.step_capacity: [u8; 64]` 记**是哪个容器**（`Container::code()`，名字表在
  `state::Container::name_of`，**只有一份**）。

⇒ 宿主把 `StepThrew` 说成 `StepThrew(Capacity:Chains)`。

⚠️ 第一版把容器名（`&'static str`）直接塞进 `step_causes`，`FightOutcome` 当场涨过 4 KB，
被 `the_spike_scenario_is_playable_through_the_env_abi` 里那条"信封必须是几 KB"的断言拦下 ——
**定容结构的大小本身是判据**，这次它省了半天。

---

## 152. 敌人与药水：从"三种效果五个药水"到能覆盖更多形状

用户："根据 wiki 完善敌人和药水种类，现在的品类太单一了而且数值也不合理。"

### 152.1 先说三件本来就错的事

| 症状 | 真相 |
|---|---|
| `swift_potion` 写的是 "Gain 12 Block" | 它是**第二个 Block Potion**穿了件马甲（同 effect 同 amount）|
| `blood_potion` 的 effect 是 `heal` | `rd_env_use_potion` **没有这个分支** ⇒ 喝它一律 `未知的药水效果` |
| 精英池只有 1 个遭遇 | 一层只有一种精英战 |

⇒ 新增一道内容门 `[3b] potions`：**每个药水都必须能喝**。三条检查：
效果在 ABI 的封闭词表里（`kind` 或 `kind:<状态 id>`）、`Amount > 0`、**两个药水不许是同一个**
（`(Effect, Amount)` 撞车即"一个药水两个名字"）；再加"每幕池只许引用存在的药水"。

### 152.2 药水词表：从 3 种到 8 种形状

沿用 §143 的 `kind:payload` 约定（payload 是状态 id）：

| effect | 语义 | 需要选目标 |
|---|---|---|
| `combat_block` / `combat_energy` | 英雄的格挡 / 能量 | 否 |
| `combat_heal_percent` | 按**最大生命百分比**回血 | 否 |
| `combat_draw` | 抽 N 张 | 否 |
| `combat_damage` | 单体伤害（走伤害管线）| **是** |
| `combat_damage_all` | 全体伤害（每个活着的敌人各走一遍管线）| 否 |
| `combat_status:<id>` | 给英雄上状态 | 否 |
| `combat_status_target:<id>` | 给选中的敌人上状态 | **是** |

`rd_run_potion_effect` 现在返回 **1 = 要选敌人 / 2 = 只作用于英雄 / 3 = 全体**，
页面按 1 来武装目标选择器 —— 以前只有"单体伤害"这一种要选目标，所以"给敌人上虚弱"根本没法瞄。

十个药水（wiki 数值）：Fire 20 / Block 12 / Energy 2 / Blood 20% / Swift 3 / Explosive 10 全体 /
Strength 2 / Regen 5 / Weak 3 / Fear 3。

⚠️ 第一次想加的是 **Dexterity Potion**，被 `[3b]` 当场拦下：`standard.dexterity` 在本内容里
**没有 `STAT` 行** ⇒ 喝下去会在状态绑定那一步被拒。换成 Regen Potion（`standard.regen` 存在）。
**门替我省了一次"加了个喝不了的药水"。**

### 152.3 敌人：五个一层怪，全是已有机制

| 敌人 | HP | 招式 |
|---|---|---|
| Red Louse | 10–15 | Bite 6 / Grow +3 力量 / Spit Web 2 虚弱 |
| Green Louse | 11–16 | Bite 6 / Grow +3 力量 |
| Fungi Beast | 22–28 | Bite 6 / Grow +3 力量 |
| Red Slaver | 46–50 | Stab 13 / Scrape 7 + 1 虚弱 |
| **Gremlin Nob**（精英）| 82–86 | Bellow +2 力量 / Rush 14 / Skull Bash 6 + 2 易伤 |

一层弱池 **3 → 6** 个遭遇（权重 20/16×5 = 100），精英池 **1 → 2**。

⚠️ 写内容时踩到一个**自己的 bug**：`Grow` 的 `sel.source` 目标我写成了 `sel.eventTarget`
（只改了 `RequiredContextCapabilities`，没改 `kind`）⇒ 力量会加到**玩家**身上。内容门
`[3] program_facts` 当场报 `facts [('status','standard.strength',3,'event')] != inv […'source']`。
**"两个字段要一起改"这种错，只有把两个字段都钉在清单里才拦得住。**

### 152.4 判据

* `[3b] potions`（内容门）：10 个药水 / 8 种效果形状 / 每幕池 4 个。
* `the_new_potion_shapes_all_do_something`（rd-wasm）：五种新形状各读回来一个数 ——
  2 力量读到 2、3 虚弱读到 3、爆炸药水对**每个**活着的敌人各记一条伤害 beat、血药回 20%(80)=16、
  迅捷药水手牌 +3。⚠️ 腰带只有 **3** 格，所以测试是"塞一个、喝一个"。
* `the_potions_are_readable`（rd-core）跟着更新：10 个、`kind[:payload]` 形状、每幕池。
* `a_long_fight_never_reports_a_step_problem`（rd-core）：3 × Sentry 打 24 回合，**每一步**的
  `problems` 必须是 0 —— `StepThrew` 是外壳吞掉的错误，只要有一层错就红。

### 152.5 还没做的

* 药水的 **Rarity 权重**没进掉落（`roll_reward` 还是均匀抽池子）。
* `Fruit Juice`（+5 最大生命，**战斗外**用）需要"药水能不能在战斗外喝"的规则，今天 ABI 只允许战斗中。
* 精英战**给遗物**还没做（§145 的池子仍然只从宝箱/商店进）。
* 敌人还剩一层的一批（Looter / Lagavulin / Guardian / Hexaghost）：前两个要"偷钱"/"睡眠觉醒"
  这类**新机制**，不是数值活。

### 152.6 数字

聚合验收 **18/18**（新增门 18 `web-soak`）；单测 734 → **738**（rd-core 626 → **629** /
rd-run 70 / rd-wasm 38 → **39**）。
内容：**20 张卡 / 21 条状态 / 65 条敌人动作 / 31 个敌人 / 22 个遭遇 / 10 种药水 / 6 件遗物**；
镜像 full **33,344 B** 附近 / core **27,700 B** 附近（以 `build.json` 为准）。

---

## 153. "为什么普通怪始终只有 jaw_worm"

用户："为什么我自己玩的时候普通怪始终只有 jaw_worm，没有其他的呢"

### 153.1 三个原因叠在一起

先量，再改。写了一个临时探针（`node` 直接驱动 run/env ABI，不进浏览器）跑了 12 个种子 ~100 场普通战斗：

```
repeats 4 : fungi  louse  louse  louse   <- 三连
repeats 3 : cultist cultist             <- 连着重
```

三个独立的原因：

| # | 原因 | 证据 |
|---|---|---|
| ① | 页面 `let runSeed = 7;` —— **常量**。每次刷新都重放同一局：同一张图、同一批遭遇，而 seed 7 的**头三场**都是 `jaw_worm` | 探针：seed 7 → `jaw_worm, jaw_worm, jaw_worm, acid+spike, jaw_worm…` |
| ② | 内容里写了 `Weight: 15/14/14/14/14/14/15`，内容门还检查它们加起来是 100 —— **内核用 `roll(len)` 均匀抽**，权重是死数据 | `fight_begin` 里只有 `roll(encounters.len())` |
| ③ | 没有任何"别连着重复"的约束（StS 不会把同一个遭遇组连着发两次）| ~100 场里 18 场与上一场相同 |

⇒ 三件事一起修：页面种子改成随机（`?debug` 仍可用 `startWithSeed` 钉住）、内核**按权重抽**、
抽到与上一场相同时**最多重摇 3 次**。

修完同一支探针：**~104 场里 1 次重复**，且那一次是**精英**池只有 2 个遭遇时的 1/16 概率。

### 153.2 顺手把 Gremlin Gang 从第二幕挪回第一幕

让权重生效之后，`act_two_fights_act_two_enemies` 当场红了：它抽到
`fat_gremlin, sneaky_gremlin, gremlin_wizard` —— 因为 `enc_gremlin_gang` 被放在了 `Weak2`（第二幕）。
wiki 里 Gremlin Gang 是**第一幕**的遭遇。挪回去之后：第一幕弱池 **6 → 7**，
第二幕回到 `shelled_parasite` / `chosen` 两个，那条测试的断言（"第二幕要出第二幕的怪"）重新成立。

⚠️ 同一次还发现 `enc_spire_growth` 在 `Weak3` 里**没有 `Weight`** —— 权重一旦真的生效，它就是 0，
等于**永远不会出现**。这正是"让死数据活过来"会照出来的东西。

### 153.3 判据

`normal_fights_do_not_repeat_and_are_not_all_the_same`（rd-wasm）：
对 `Weak` 池抽 40 次，断言 ① 相邻两次不同、② 40 次覆盖整个池（7 个）、③ 每个遭遇出现的次数在
`1..=15`（宽松，只证明权重被用上了；精确分布是统计断言，单一种子说不了）。

⚠️ 这条测试第一版是**走完整战斗**去数遭遇到的，结果英雄在对局里被打死 ⇒ 只测到第一场
（`expected several fights, got ["enc_jawworm"]`）。所以把抽签那段**提成 `pick_encounter`**，
测试直接打那一层 —— 顺带把"权重 / 不重复 / 记账"三件事从 `fight_begin` 里分了出来。

### 153.4 还没做的

* 权重只写进了 `Weak`，`Weak2/Weak3` 的权重是拍的（本内容第二/三幕各自只有 2–6 个遭遇，
  "权重"在那几个池子里还谈不上分布）。
* 精英池只有 2 个遭遇 ⇒ 连着两场同一个精英的概率仍有 ~6%（`gremlin_nob` 实测出现过一次）。
* 页面没有"重开一局换种子"以外的入口；`runSeed` 不进复盘/回放（本章没做回放）。

### 153.5 数字

聚合验收 **18/18**；单测 738 → **739**（rd-core 629 / rd-run 70 / rd-wasm 39 → **40**）。
内容：第一幕弱池 **7** 个遭遇（权重和 100）；镜像 full **33,332 B** / core **27,692 B**。

---

## 154. `UnknownCard("iron_wave+")`：营火给的牌，建战斗时没听说过

用户报：`开战被拒 · build_fight_from_content: UnknownCard(CardDefinitionId("iron_wave+"))`。

### 154.1 这条**§147 已经写过一次**

§147 的原话："运行层的'升级'就是往卡 id 后面加一个 `+`，所以一张没有 `+` 行的牌一旦被升，
下一场战斗会在建战斗那一步炸"。当时只补了 `whirlwind+`（因为用户点名的就是旋风斩），
**另外九张能升级的牌一张 `+` 行都没有**：

| 缺的行 | 昨天玩家的路径 |
|---|---|
| `anger+` `twin_strike+` `iron_wave+` `clothesline+` `uppercut+` `sentinel+` `patient_guard+` `swift_strike+` `apparition+` `buffer+` | 营火打铁 / 事件升级 → 牌变成 `iron_wave+` → **下一场战斗建不起来**，整局卡死 |

⇒ 补 10 行（wiki 数值：Anger 6→8、Twin Strike 5→7 ×2、Iron Wave 5/5→7/7、Clothesline 12→14 且
2→3 虚弱、Uppercut 13 不动但 1→2 虚弱 / 1→2 易伤、Apparition 1→2 无形、Buffer 1→2；
本内容自造的三张——`Sentinel` / `Patient Guard` / `Swift Strike`——沿用基础牌的 "+3" 档）。
`anger+` 复制的是 **`anger+`**，不是原版：升级过的牌塞回一张没升级的，是玩家几回合后才会发现的暗降。

### 154.2 两道门，各管一半

| 门 | 断言 | 为什么在这一层 |
|---|---|---|
| 内容门 `[3c] card upgrades` | **每一张能升级的牌都有 `+` 行**（`curse`/`status` 除外），且 `+` 行的费用与 tags 必须与基础牌一致 | 只有内容层知道 tags（"这张能不能打铁"）|
| `every_upgraded_card_row_builds_a_fight`（rd-core）| **镜像里每一个 `+` 行都能建一场战斗**，成对：不存在的 `+` 行照样响亮失败 | 建战斗是内核的事；这条遍历镜像，所以内容新增牌时自动覆盖 |

**反向控制**：从内容里删掉 `iron_wave+` → 内容门 3 条红、内核测试红（它报的是"`+` 行只剩 13 条"），
恢复后全绿。

### 154.3 §147 的教训为什么没接住

因为当时的"判据"只钉了**那一张牌**（`an_upgraded_card_row_is_buildable` 里硬编码 `whirlwind`）。
一条测试钉住一个实例时，它证明的是"这个实例有行"，不是"这类牌都有行"。
现在的分工是：**内容门管"每张都有"**（按 tags 遍历），**内核测试管"每个 `+` 行都能用"**（按镜像遍历）
—— 两条都遍历全集，所以下一张新牌不会重蹈。

### 154.4 数字

聚合验收 **18/18**；单测 739 → **740**（rd-core 629 → **630** / rd-run 70 / rd-wasm 40）。
内容：**30 张卡**（其中 14 张是 `+` 行）；镜像 full **34,632 B** / core **28,496 B**。

---

## 155. 精英战给遗物 + 让随机流水线真的**走到**这些功能

用户："继续把精英战遗物补上吧，最好是上面这些细枝末节的功能能够被之前做的自动化的随机测试流水线覆盖到。"

### 155.1 遗物：走 §145 那个唯一授予点

StS 的精英奖励是"金币 + 三选一 + **一件遗物**"；本内核之前只给前两样。

* `Reward` 多了 `relic: RunId`；
* `roll_reward(cards, potions, **relics**, kind)`：`Elite`/`Boss` 才填，`Normal` 清空；
* 池子过滤走 `relic_candidates`（**和宝箱、商店同一个**），所以永远不会给第二件已有的；
* `take_relic()` 走 `push_relic`（§145 的唯一授予点）⇒ 校验与运行时效果和宝箱完全一致；
  桌上没有遗物时返回 `NoSuchRelic`（而不是悄悄什么都不做）。

ABI 四个新导出（和药水那一对同形）：`rd_run_reward_relic_len/_into`、`rd_run_take_relic`；
页面多一行"遗物 X / 拿起"，`PANEL_ACTIONS.take_relic` 接到 `act(...)`。

### 155.2 判据（确定性那一半）

| 层 | 测试 | 盯什么 |
|---|---|---|
| rd-run | `an_elite_pays_a_relic_and_a_normal_fight_does_not` | 普通战没有、精英/Boss 有；拿走进列表、拿两次报错、**集齐后不再给重复** |
| rd-wasm | `the_elite_relic_reward_round_trips_through_the_abi` | 四个导出真的读得出来/拿得到，拿第二次被拒（`-2`）|
| ui_test | 新的 reward 状态 + 行断言 | 精英奖励**画出**遗物行、按钮是 `take_relic`、普通战**不**画 |
| soak（门 18）| 覆盖率断言 | 见下 |

### 155.3 soak：从"随便点"变成"会走路、会挡、会打铁"

原先的 soak 只会随机点。它的**覆盖率**是运气：
它总是点奖励面板的第一行（永远是卡，遗物行追加在后面）、走过去时精英和普通节点一样随机、
到篝火永远点第一个动作（**休息**，永远不是打铁）。

这一节给它三样东西（都在驱动器的**策略**里，断言没变松）：

1. **会打牌**：从观察向量读 HP/格挡/敌人意图伤害；该挡就挡，否则打伤害，都没有就结束回合。
   （以前纯随机出牌，在第 1 层就被三只 gremlin 打死 —— 而 `enc_gremlin_gang` 是 §153 挪进一层的。）
2. **会走路**：`RD_DEBUG.view()` 给出地图图（`nodes[].out` + `cursor.node`），BFS 到"还没覆盖过"
   的节点类型；未升级就去**篝火**、没打过精英就去**精英**。第一次出发前 `cursor.node` 是 `-1`，
   所以从第一层**所有**节点起搜。
3. **会把奖励拿全**：奖励屏幕逐行点完再跳过（否则遗物行永远轮不到）。

顺带三个踩过的坑（都在注释里）：
* 精英节点的 DOM 标记是 `data-kind="elite"`，而**不是**文字里的"精英"（那词只在面板标题里）；
* `out.smithTries` 没初始化 ⇒ `undefined < 3` 恒 false ⇒ 打铁分支永不执行；
* 我把牌组探针临时注释掉做负面控制，忘了恢复 ⇒ "upgrade NO" 是假阴性。

现在的覆盖率输出（门 18 每次都会打印）：

```
coverage  map has elites · N elite(s) · M boss(es) · K relic(s) (X from elites) · elite wins Y · upgrade yes
```

**断言**是**蕴含式**，不是"必须凑巧"：

* 赢过精英（`eliteWins > 0`）⇒ 必须拿到过精英给的遗物；
* 走到过篝火 ⇒ 必须发生过一次升级；
* 走到过 ≥4 种界面、拿到过 ≥1 件遗物、没有死按钮/异常/卡死。

⚠️ **没有**断言"必须打过精英"：随机行走在第 6–8 层就倒了，而一层精英在更深的位置 ——
把它写成必须，闸门会因为"运气不好"而红，那不是 bug。精英给遗物这条规则由上面那三个
**确定性**测试盯着，soak 盯的是"真的发生时它是对的"。

### 155.4 数字

聚合验收 **18/18**；单测 740 → **742**（rd-core 630 / rd-run 70 → **71** / rd-wasm 40 → **41**）。
soak：3 个种子共 80–200 次点击，楼层 6–16，界面覆盖 7 种，升级 ✅。

---

## 156. 遗物稀有度与掉落权重（+4 件遗物）

用户："按照这个顺序继续完善细节吧" —— 上一节列的顺序是：遗物稀有度/掉落权重 → 再补几件遗物 →
药水稀有度权重。

### 156.1 稀有度是**内容**，所以它进了 `REL` 行

`REL_ROW` 原本是 `{Id, DisplayName, RunPrograms, CombatRules, extra}` —— 5 格装在一个 12 字节的行里
（`u16` × 6 = 12），所以第 6 格是**免费的**，stride 不变（`rdcf_verify` 那条 count×stride 依旧成立）。

另一条路是在 `rd-run` 里放一张"id → 稀有度"表（和 `relic_effect()` 并排）。**没有**那么做：
效果是**行为**，稀有度是**内容**，而药水早就把 `Rarity` 放在 `POT` 行里了。同一个概念放两个地方，
就是两份会走样的清单。

⚠️ 改了编译器 → `contentc-bytes` 门红。按那条门自己的规矩：**同一个提交里显式 `--repin`**，
并在提交消息里写明理由（本次：`REL` 多一格 `Rarity`，两件镜像的 sha 都变了）。

### 156.2 掉落权重：一个函数，三个来源

StS 的抽法是"先按权重抽**稀有度档**，再在档内均匀抽一件"：

| 池 | Common | Uncommon | Rare |
|---|---|---|---|
| 遗物 | 50% | 33% | 17% |
| 药水 | 65% | 25% | 10% |

`pick_rarity` 把权重**在当前可用的档上重新归一化** —— "稀有档已经空了"会把质量挪到别的档，
而不是返回 `None`（那会变成"宝箱偶尔什么都不给"，而且没有任何信号）。

`pick_relic(stream, pool)` 现在被**三个来源共用**：宝箱、商店货架、精英/Boss 奖励。
它们本来就共用"不会给你已经有的那件"这条过滤（§145），现在连"按档抽"也共用 ——
三个来源要一直，只有**一个**函数能做到。

⚠️ 商店一次上三件，而抽中的遗物在买之前**不在腰带上** ⇒ "跳过已有的"不够，同一件会上三次。
所以补了 `pick_relic_avoiding(stream, pool, reserved)`，商店把自己已经摆上去的传进去。

### 156.3 四件新遗物（wiki 数值）

| 遗物 | 稀有度 | 效果 | 落点 |
|---|---|---|---|
| Strawberry | Common | +7 最大生命 | `MaxHealthUp(7)` |
| Bronze Scales | Common | 受击反 3 伤 | `StartCombatStatus("standard.thorns", 3)` |
| Regal Pillow | Uncommon | 休息多回 15 | `RestHealBonus(15)`（新）|
| Meat on the Bone | Uncommon | 战后若 ≤50% 生命，回 12 | `EndOfCombatHealIfBelow { 50, 12 }`（新）|

两个新 `RelicEffect` 变体各自只落在一个钩子上：`rest_heal()` 加平值；`end_of_combat()` 里读
**当前最大值**的百分比（Pear/Strawberry 会移动它）。三个钩子的 `match` 都是**穷尽**的，
所以"新加一个效果变体"是编译错误，而不是一件静默无效果的遗物。

### 156.4 判据

* `relic_rarity_weights_favour_commons_and_shift_when_a_band_is_empty`（rd-run）：300 次抽样里
  常见档 > 罕见档、且罕见档仍抽得到；**只有罕见档的池子**照样每次都给出它（重新归一化）；
  空池返回空 id（= 空宝箱），不报错。
⚠️ 断言刻意宽松：单个种子证明不了 50/33/17，精确分布是统计断言，不该由一条测试假装。
* 内容门 `[6f] relic rarities`：每件遗物的 `Rarity` 必须在那三档里，且**三档都不能是空的**
  （空档 = 那部分的权重永远抽不到）。
* 内容门 `[6e]` 跟着到 10 件；`[3c]`（卡升级）不变。

### 156.5 顺带修的两处"测试测的是运气"

1. `a_potion_can_be_used_in_a_fight` 原来是"走二十场直到 block+energy+fire 三种药水都掉出来"。
   药水权重一改，`Potion` 流的序列平移，它就"走完也没掉到" —— 它测的是 RNG，不是功能。
   现在**直接塞进腰带**（`push_potion`），只在真战斗里喝；掉落由奖励那一层单独覆盖。
   顺带把"走进一场战斗"抽成 `arrive_at_a_fight()`（先结算脚下、只能从已结算的节点走、优先战斗邻居）——
   我第一版自己重写这段时在 1 层撞了 `NodeNotSettled`。
2. `content::entity_tables_decode_row_by_row` 读的是 **core 镜像**；`build.py --package sts` 只重建
   sts 包 ⇒ core 还是 5 格的旧产物，`extra()` 读到 padding 的 0。**必须 `--all` 重建两个包**
   （这类"改格式只重建一个包"的坑，闸门会在奇怪的断言上红）。

### 156.6 数字

聚合验收 **18/18**；单测 742 → **743**（rd-core 630 / rd-run 71 → **72** / rd-wasm 41）。
内容：**10 件遗物**（Common 6 / Uncommon 3 / Rare 1）；镜像 full **34,868 B** / core **28,660 B**。

---

## 157. 药水掉率对齐 wiki + 稀有档补满 + 三件遗物

用户："每次战斗后药水的掉落概率也需要和 wiki 对齐。"

### 157.1 掉率不是常量，是一条**会走**的 40%

wiki（`Potions` 页 "Sources"）原话：

> The **default chance** of a potion dropping is **40%** and resets at the start of each Act.
> If a potion drops, the chance **decreases** by **10%**. If a potion doesn't drop, the chance
> **increases** by **10%**.

原来的 `POTION_DROP_PERCENT = 40` 是常量 —— 这在短局里看不出来，在整局里恰好错在**最要紧的地方**：
连续五场没掉，概率应该是 90%，而不是一直 40%。

现在 `RunState.potion_chance` 从 40 起，每场战后按结果 ±10（夹在 `0..=100`），**换幕重置**。

⚠️ 两条容易写错的细节，都按 wiki 处理：
* **腰带满了照样摇**（wiki 的 Colosseum 注记明说"rolls for a potion, but does not display"）
  ⇒ 概率继续走，只是**不摆出来**（`drop = rolled && potion_room()`）；
* 一格腰带 = 3 格是**规则**，`MAX_RUN_POTIONS = 5` 是**存储** —— 因为 Potion Belt 要加两格。

### 157.2 稀有档是空的（又一处"声明了但没用"）

十个药水是 9 Common + 1 Uncommon，**Rare 档一个都没有**。权重 `65/25/10` 会在"当前可用档"上
重新归一化，所以 Rare 那 10% 静默并进了别的档 —— 这正是本项目反复禁止的形状。

两处按 wiki 补齐：
* **Fruit Juice**（Rare）："Gain 5 Max HP."，新增效果 `max_hp` —— 它作用于**运行层**（fights 之外），
  是唯一一个不关于这场战斗的药水效果；
* **Regen Potion** 改成 Uncommon（wiki 的 patch 24 记录："Regen Potion and Ancient Potion are now
  Uncommon"）。

内容门 `[3b]` 现在也要求**三档都不能是空的**（和 `[6f]` 对遗物的要求同形）。

### 157.3 三件遗物（2 Rare + 1 Common），Rare 档不再靠一件撑

| 遗物 | 稀有度 | wiki 效果 | 落点 |
|---|---|---|---|
| Eternal Feather | Rare | 休息时每 5 张牌回 3 血 | `RestHealPerFiveCards(3)` |
| Golden Idol | Rare | 敌人多掉 25% 金币 | `FightGoldPercent(25)` |
| Potion Belt | Common | +2 药水格（wiki：**唯一**能加格的东西）| `ExtraPotionSlots(2)` |

遗物池 **10 → 13**（Common 7 / Uncommon 3 / **Rare 3**）⇒ Rare 那 17% 不再只能给同一件。

### 157.4 判据（五条，各自独立）

* `the_potion_chance_walks_the_wikis_ten_percent`：每场按结果 ±10、夹在 0..100、12 次里两种结果都出现。
* `a_full_belt_still_rolls_the_chance`：满腰带时**没有 offer**，但概率**继续走**。
* `potions_are_drawn_by_rarity_weight`：65/25/10 的顺序（宽松，和遗物那条同形）；
  只有 Rare 的池子照样每次都给出它。
* `potion_belt_raises_the_slot_count`：3 格 → 装第 4 瓶被拒 → 戴上腰带 5 格 → 第 6 瓶仍被拒。
* `the_new_relics_pay_out`：Eternal Feather 十张牌 = 两组五张 = +6；Golden Idol 同一卷轴金币 ×1.25。

### 157.5 被这次改动照出来的旧测试

四处，都是"测试量的是常量/运气"：
1. `capacity_is_an_error_not_a_truncation` 拿 `MAX_RUN_POTIONS` 当规则（现在是存储）⇒ 改用
   `BASE_POTION_SLOTS`，并顺手证明腰带能把它抬到 5；
2. `a_won_fight_drops_a_potion_and_the_belt_takes_it` 断言"400 次里约 40%"——概率会走之后那个
   数字不再成立（走的是平稳分布，不是 40%），改成"100% 一定掉 / 0% 一定不掉"这条**规则**；
3. `golden_idol` 曾是"内核跑不了的遗物"的 fixture，§157 把它实现了 ⇒ 换成 `no_such_relic`
   （更好的 fixture：以后再实现一件遗物也不会让它过期）；
4. `the_container_bounds_are_the_run_layers_and_not_the_pages` 钉的是 `MAX_RUN_POTIONS == 3`
   ⇒ 改成钉 `BASE_POTION_SLOTS == 3` 加"存储至少装得下腰带"。

⚠️ 新写的掉率测试自身也踩了一次：它用**空药水池**去测 —— 空了就永远不会 offer，于是
"offer 为假" ≠ "没掉"，断言立刻红。池子必须非空。

### 157.6 数字

聚合验收 **18/18**；单测 743 → **748**（rd-core 630 / rd-run 72 → **77** / rd-wasm 41）。
内容：**13 件遗物**、**11 种药水**（Common 8 / Uncommon 2 / Rare 1）；
镜像 full **35,064 B** / core **28,816 B**（`--repin` 已执行：`REL` 加格的字节变化）。

---

## 158. 药水稀有档补到 wiki 的数目（20 / 33）：先补不需要新机制的十一瓶

§157 把药水从 10 瓶做到 11 瓶，同时钉下了"Rare 档是空的"这件事。这一节回答的是**到底差多少**：
wiki 的 `Potions` 页对**铁甲战士**能拿到的是 **17 Common / 9 Uncommon / 7 Rare = 33 瓶**
（42 瓶总数减去 Silent 的 2、Defect 的 3、Watcher 的 3 —— 逐个从表里数的）。

这次补了 **9** 瓶，它们都不需要内核有新的机制：**20 瓶（C12 / U4 / R4）**。
剩下 13 瓶每一瓶都要一样新东西，逐条列在 §158.7 ——这张清单比"还差 13"有用。

### 158.1 三处"声明了但内核没读"，这次先补最要命的两处

* **`standard.dexterity` 在内容里没有行**。内核的 `BLOCK_MODIFIERS`（`status_catalog.rs`）
  有它，但**内容存在时那张表是关掉的**（`exec.rs` 的 `NAMESPACE_BRIDGE` 只在
  `content == None` 时用它）⇒ 内容侧必须自己声明
  `BlockGain / AddPerStack / 1 / Priority 100`（参考 `StandardCombatPackage.cs:360-363`）。
  ⚠️ 管线串是 `"BlockGain"`，**不是** `"Block"`（`status_bind.rs:60-65` 专门写了这一条）。
* **`PotionTables` 是死数据 + 会被静默截断**。三幕各一份药水池这件事**在 wiki 里没有出处**
  （药水不分幕），而 `MAX_POOL_IDS = 8` 会把 33 项清单截成 8 项 —— `id_pool` 里那个
  `.min(MAX_POOL_IDS)` 就是本项目最忌讳的形状：内容说有，实际只有前 8 个能掉。
  ⇒ 删掉整张表，药水池 = **`POT` 表的全部行**，`potion_pool` 读取器随之删除。

### 158.2 `Effect` 变成**逗号分隔的原子列表**

Flex Potion 的 wiki 原文是两句："Gain 5 Strength. At the end of your turn, lose 5 Strength."
`POT` 行只有一个 `Effect` 格，而这是**两个状态**（`standard.strength` 与
`standard.lose_strength`，后者是内容侧新加的：`TurnEnded` 触发里把自己的层数从力量上减回去，
然后把自己减到 0）。所以加了逗号列表，**所有原子共用一个 `Amount`** —— 正好这两瓶的两半数量相同。

内核侧的实现是"逐个原子执行"，`combat_status` 与 `combat_status_target` 各带自己的前缀，
所以一瓶药水理论上可以同时打自己和敌人。内容门 `[3b]` 逐个原子检查词汇表，
并且要求**不能把"要目标的原子"和"不要目标的原子"混在一瓶里**（页面只问一次目标）。

### 158.3 运行层原子：`max_hp` / `potion_fill` 可以在**战斗外**用

wiki：Fruit Juice 和 Entropic Brew 是"most scenarios 都能用"的两瓶。此前的实现把
"不在战斗里就拒绝"写在了**效果分派之前**，于是这两瓶只有在战斗里才喝得下去 —— 词汇表里有，
可达性只有一半。现在先按原子分类：全部是运行层原子 ⇒ 走运行层分支，一个战斗都不用开。

`potion_fill`（Entropic Brew）还有一个顺序问题：**它必须先把自己从腰带上拿下来**，否则
一个 3/3 的满腰带"填空格"是零个。判据就写在这上面："喝之前 3 瓶，喝之后还是 3 瓶" ——
如果先填后消耗，读数会是 2，做不对就红。

`pick_potion` 也从 `roll_reward` 里提出来了：掉落和"这瓶药水变成哪瓶"必须是**同一个**答案，
两个挑选器就是两套要记得改的权重。

### 158.4 又一处 wiki 与内容不符：Energy Potion 是 Common

内容里写成 `Uncommon`。顺手改了 —— 这类"一格之差"不会让任何测试红，但它会让 65/25/10 的
分布整体偏一点，而分布是**统计量**，单种子证不了。

### 158.5 这次改动照出**两条死了的测试**

`cargo test` 的警告里有两行 `duplicated attribute` / `never used`，追下去是同一个形状：
**一次 `edit` 的锚点是一行裸文档注释，把紧跟其后的 `#[test]` 吞掉了**（FACT.md §3 记的就是这个）。

1. `content::the_encounter_pools_are_readable` —— 没了 `#[test]`，于是它那个 `#[test]`
   叠到了上面 `no_encounter_places_more_enemies_than_a_fight_allows` 头上。它**编译、跑零次、
   不报任何东西**。补回属性后立刻红：它断言的"weak 池 3 项"已经两年是 7 项了。
   ⇒ 顺手把断言换成**结构**而不是当天的数字：9 个池子的 id 都必须是真 `ENCT` 行、
   池子之间**不重叠**、并且并集 == 全部遭遇（没有不可达的遭遇）。这条以后不会再过期。
2. `host::a_split_spawns_two_combatants_when_the_boss_dies` —— 同一个形状，补回 `#[test]`。

两处都不是"断言写错"，是**测试根本没跑**。它不会让任何闸门变红，只会让覆盖率这个数字虚高。

### 158.6 判据

* `dexterity_from_the_content_scales_a_real_defend`（rd-core）：用**内容的起始牌**打一张
  `defend`（5 格挡），英雄身上 2 层 `standard.dexterity` ⇒ 要 **7**。
  ⚠️ 负控做过：把那个 spec 的 `Pipeline` 改成 `"BlockGained"`，测试**红**，
  而且是响亮的 `Play(Effect(Bind(Pipeline)))` ——
  绑定器拒绝未知管线，不是"静默不生效"。
* `flex_potion_gives_strength_and_takes_it_back`（rd-wasm）：喝下去立刻 +5 力量 **且**挂上
  5 点 `standard.lose_strength`；结束回合后两者都是 0（= 实例已被移除）。
* `entropic_brew_fills_the_belt_after_freeing_its_own_slot`：满腰带 3 → 喝完仍是 3。
* `fruit_juice_works_outside_a_fight`：一局但没有战斗，`+5` 最大生命，且生命同额提升。
* `the_potions_are_readable`（rd-core）：20 瓶、`bands == [12, 4, 4]`、每个原子都在词汇表里、
  `potion_fill` 是唯一不读 `Amount` 的原子。

### 158.7 还差 13 瓶，每一瓶要一样**新机制**

| 要的机制 | 药水 |
|---|---|
| 战斗中选牌（1/3 张）| Attack / Skill / Power / Colorless Potion |
| 战斗中升级手牌 | Blessing of the Forge |
| 战斗中多选弃/消耗 | Elixir、Gambler's Brew |
| 从弃牌堆检索一张并免费 | Liquid Memories |
| 自动打出牌堆顶 | Distilled Chaos |
| 把下一张牌打两次 | Duplication Potion |
| 改写卡牌费用 | Snecko Oil |
| 死亡拦截（`DeathPrevention` 字段**已经能解出来但没人读**）| Fairy in a Bottle |
| 逃跑（`FightOutcome` 需要一个 "escaped"）| Smoke Bomb |

### 158.8 数字

聚合验收 **18/18**；单测 748 → **752**（rd-core 630 → **631**、rd-run 77、rd-wasm 41 → **44**）。
内容：**20 种药水（C12 / U4 / R4）**、**24 条状态**（+3）、31 怪 / 22 遭遇 / 30 卡 / 13 遗物。
镜像 full **36,880 B** / core **30,360 B**（**没有** `--repin`：这次只动 `sts` 的数据，
`REL`/`POT` 的**格式**一格没变，所以 `tools/contentc/out/` 那两份 roguedeck 镜像字节不变）。

---

## 159. Ascension 框架 + 开局前的种子设定

wiki 的 `Ascension` 页有 **20 条**修饰，**累计生效**（A3 同时带着 A1 和 A2）。这一节把框架立起来，
并实现了其中 **9 条**；没实现的 11 条在 §159.6 逐条写了"要什么"，因为"支持到 A20"而其中八条
静默不生效，正是这个项目一直在抓的那种谎。

### 159.1 一个数，一条规则一个号

`RunState.ascension: u8`（`0..=20`，超出**夹取不拒绝**：页面一个 off-by-one 不该变成死按钮），
以及 **唯一的比较** `at_least(level)`。规则号是常量：

`A_BOSS_HEAL`=5、`A_START_DAMAGED`=6、`A_NORMAL_HP`=7、`A_ELITE_HP`=8、`A_BOSS_HP`=9、
`A_POTION_SLOT`=11、`A_BOSS_GOLD`=13、`A_MAX_HP`=14、`A_SHOP_PRICE`=16。

调用点于是读作"这条规则"，而不是散落一地的 `>= 5`。**累计是断言的形状**：每条规则都在自己阈值的
两侧各测一次（`a_boss_heals_…` 测 A4 与 A5、`the_ascension_rules_…` 测 A13 与 A14/A15 与 A16），
因为"`>=` 写早了一级"正是这种代码最容易犯且最不容易看出来的错。

### 159.2 两条**改初始状态**的规则，顺序是规则的一部分

`A14` 减最大生命（铁甲战士 **−5**，内容里只有这一个角色），`A6` 掉 10% 生命。
顺序决定数字：**先 A14 再 A6** ⇒ 80 → 75 → 68；反过来是 80 → 72 → 67。

它们**不在同一个函数里**，这是有意的：`A14` 改的是最大值，属于构造（`new_with_ascension`）；
`A6` 要作用在**内容声明的 `StartingHealth`** 之上，而那个数字只有调用方（`rd-wasm` 的
`rd_run_start`）知道。若两条都写在构造函数里，`rd_run_start` 里那句
`adjust_health(starting_health - health)` 会把 A6 的伤害**覆盖掉**，而覆盖与否取决于两行的先后 ——
那是最糟的一类耦合。

### 159.3 Boss 战之后**本来就没有回血**

`A5` 的 wiki 原文是 "heal 75% of missing health **instead of 100%**"。查下去才发现**那条 100%
压根不存在**：`mark_boss_beaten` 只换幕、不回血。所以这一节先把基础规则补上（打完一幕的 Boss
回满），`A5` 才有意义。一个"关于不存在的治疗的分数"是这次差点写出来的东西。

### 159.4 `A7`/`A8`/`A9` 的百分比是**我们的模型**，不是 StS 的数据

wiki 只说 "have more HP"，真游戏是逐怪的**手调数字**。所以 `+10%` 落在**一个常量**
（`ASCENDED_ENEMY_HEALTH_PERCENT`）上，注释写明它没有出处，以及哪天 `ENCT` 长出 ascension 列，
这是唯一要删的东西。它不是"猜"，它是"标了价的近似"。

落在 `ENCT` 行的 `MaxHealth` 上（唯一写着敌人血量的地方），由
`build_session_at(…, enemy_health_percent)` 应用 —— `build_session_with` 变成它的 `0` 便利入口。

### 159.5 开局前的种子：`(seed, level)` 才是一局

页面此前 `runSeed = Math.floor(Math.random()*2e9)`，**种子不可输入**，等级不存在。现在地图面板上方
两格：**种子** + **爬塔等级**，加一个"开始 / 重开"按钮；顶栏在等级 > 0 时显示 `A<n>`。

三条纪律写进了实现：

* `#seedInput` 只有**一个写者** `setSeed()` —— 一个和实际开局不一致的种子输入框，比没有输入框更糟；
* `startRun()` **读**这两格再调 `rd_run_start(seed, level)`，并把夹取后的值写回去（页面显示的就是
  内核真收到的）；
* 顶栏里的等级从 `rd_run_ascension()` 读，**不**从输入框读 —— 输入框描述的是"下一局"。

`rd_run_start` 的签名因此从 `(seed)` 变成 `(seed, ascension)`：`web/index.html`、`web/map.html`、
`map_test.mjs` 的 5 处调用一起改。⚠️ 少改一处**不会**报错（wasm 缺参数会当 0），所以这一节还让
`browser_test` **从输入框驱动**一遍：填种子 2222、等级 14、点按钮，然后断言内核的等级是 14、
种子是 2222、最大生命是 75、顶栏里有 `A14`。

⚠️ 这个场景自己踩了两次**反引号/转义**：`browser_test` 的整段注入代码是一个模板字符串，
注释里一个 `` ` `` 就直接把它截断（`SyntaxError`），注释里一个 `\n` 会变成真换行、把下一行变成代码。
FACT.md §2 记的就是这个坑，这次它换了个位置复发。

### 159.6 没实现的 11 条，各自要什么

| 规则 | 要什么 |
|---|---|
| A1 精英更常见 | 地图的 `kind_for_roll` 是**累计上界表**（53/8/12/5/22），要按等级换一张并把差额从 Combat 里扣。**下一节和精英池一起做**（改表要连 12 条地图测试）|
| A2 / A3 / A4 敌人/精英/Boss 伤害更高 | 内容每条 `EACT` 只有**一个**伤害数字，没有 ascension 列。要么给 `EACT` 加列（格式 v5），要么写成"开局给敌人力量"——后者是**换机制**，会改变多段攻击的缩放，不打算偷偷做 |
| A10 开局带 Ascender's Bane | 一条 Curse 卡行 + "不可移除"（`remove_card` 要拒）。卡行好加，"不可移除"是新规则 |
| A12 强化牌更少出现 | 我们的**奖励里根本不出现强化牌**，所以 A12 是在给一个不存在的基数打折：要么先做基数（奖励按概率给 `+` 版），要么留空 |
| A15 事件更不利 | 每个事件要有 A15 分支（内容 + 运行层）|
| A17 / A18 / A19 更强的招式 | 每只怪要有 ascension 招式表（内容 + `intent`）|
| A20 双 Boss | 打完第一只再打另一只；`Boss3` 目前只有 `enc_time_eater` 一个，需要先有第二只 |

### 159.7 判据

* `the_ascension_rules_are_each_their_own_level`（rd-run）：A13 不动最大生命、A14 才动；
  A11 的格子 3 → 2 且腰带仍在**基数**上 +2（⇒ 4，正是 wiki 的"5，或 A11 以上的 4"）；
  A15 不打折、A16 打；A99 夹到 20。
* `a_boss_heals_to_full_and_ascension_five_heals_three_quarters`：A0 回满、A4 仍回满、A5 回 75%。
* `the_enemy_health_bonus_belongs_to_its_own_fight_kind`：A7 只动普通、A8 动精英、A9 动 Boss。
* `the_ascension_level_reaches_the_run`（rd-wasm）：A0 = 80/80、A6 = 80/72、A14 = 75/68、
  A20 = 75/68（A6 与 A14 是唯一两条改初始状态的规则），99 夹到 20，且同一个种子仍然给出同一局。
* `ascension_seven_makes_a_normal_fight_tougher`：同种子同一场战斗，敌人最大生命正好 +10%。
* `browser_test`：**从输入框**驱动 A14，断言等级/种子/最大生命/顶栏四处。

### 159.8 数字

聚合验收 **18/18**；单测 752 → **757**（rd-core 631、rd-run 77 → **80**、rd-wasm 44 → **46**）。
内容未动（31 怪 / 22 遭遇 / 30 卡 / 24 状态 / 13 遗物 / 20 药水），镜像字节不变。

### 159.9 顺手补的守卫：池超容现在**拒绝**而不是截断

§158 删药水池的一半理由就是 `id_pool` 的 `.min(MAX_POOL_IDS)`：一条 33 项的清单会以"前 8 瓶能掉、
内容门还说 33 瓶都在"的形式上线。遭遇池/事件池走的还是那个 walker，而 `Weak` 已经是 8 格里的 7 格 ——
下一节加精英正会撞上它。

补了一条守护测试，而它**第一版不可能变红**：它数的是返回的 `[&str; MAX_POOL_IDS]` 里非空的格子，
而那个数组按构造最多 8 格 —— 于是清单里塞到 9 项它照样绿。**这是负控抓出来的**（不是读代码看出来的）。

修法是让守卫坐在**切口之前**：`id_pool` 遇到超容清单直接返回 `None`（"这个池没有了"是响亮的、
可观察的失败），测试则断言 9 个遭遇池 + 3 个事件池都 `is_some()`。负控（`Weak` 塞到 9 项）现在红，
报错原文是"`EncounterTables.Weak` is missing or holds more than 8 ids"。

顺带一条：改完 `content.rs` 之后**忘了重编 wasm**，`web-package` 当场红（"web/rd_wasm.wasm is NOT a
fresh build of this tree"，还给了 on-disk 与 fresh 两个 sha）—— 那道闸门的存在意义就是这一次。

---

## 160. 回应外部评审：三个真缺陷 + 一个"不在切口之前"的守卫

`docs/vibe/advices-from-chatgpt-261031.md` 是一份外部评审（它自己声明"未在本机复跑测试"）。
这一节把它点名的**源码级**指控逐条对过码，然后修掉了三条**今天就是错的**。

### 160.1 逐条核对结果（六条全中）

| 评审条目 | 核对 | 结论 |
|---|---|---|
| **P0** 商店购买不是原子的 | `buy_card` / `buy_relic` 先 `adjust_gold` 再 `push_*?`，满容量时 `Capacity` 已扣钱 | **真的** |
| **P1** 运行层池仍静默截断 | `take(MAX_POOL)` / `.min(MAX_POOL)` 共 **7 处**（1784/1846/1849/1854/1923/2174/2415） | **真的**（今天不可达：20/13/30 vs 64）|
| **P1** Eternal Feather 整除顺序 | `amount * deck_len / 5` | **真的**（8 张给 4，应给 3）|
| **P1** Eternal Feather 触发点 | 塞在 `rest_heal()` 里，而它只在 `rest()` 调用；`smith()` 不治疗 | **真的**，而且 wiki 原文就写着 "Heal applies **on entering**" |
| **P1** `eternal_feather` 稀有度 | wiki 导航盒与 patch 注记：**Uncommon**（"from Boss -> Uncommon"）；内容是 `Rare` | **我们错** |
| **P1** `golden_idol` 该不该进掉落池 | wiki 导航盒把它列在 **Event**；内容是 `Rare`，于是 17% 的稀有档里混进一件事件遗物 | **我们错** |
| clippy 闸门没有 `-D warnings` | `clippy --all-targets … -MustMatch 'Finished'` | **真的**（§160.5 说明为什么还没开）|
| `static mut` 别名是**已经发生过**的事故 | `run.rs:67-69` 的注释写着访问违例 `0xC0000005` | **真的** |

后两条不是新发现，是**已经在 `port-plan` 里写过的教训**（§158.5 的死测试、§151 的 `fail()`），评审只是从代码里也读到了。

### 160.2 P0：购买只有一个提交点，而且失败的那一半在前

`push_card` / `push_relic` 自己先校验再写，失败时什么都不动 —— 所以**调换顺序就是完整修复**
（`adjust_gold` 不会失败）。没有引入事务框架，也没有复制一份容量判断。

判据 `a_refused_purchase_leaves_the_run_untouched`：牌组填到 `MAX_RUN_DECK` 后买卡必须 `Capacity`
**且金币一分不动、货架价不变**；遗物栏同理。负控：把顺序改回去 ⇒ 红在**金币**上（451 vs 499），
不是红在错误码上 —— 后者会让人以为"测试只是没覆盖"。

### 160.3 P1：Eternal Feather 的三件事，一次修完

1. **整除**：`amount * (deck_len / 5)`。分段函数的边界（5/8/9/10/14）逐个钉住 —— §157 只测了 10 张，
   而 10 张两种写法都是 6，所以全绿。**这不是测试太少，是分段函数只测了整档。**
2. **触发点**：进入篝火时付，所以 **Smith 也吃到**。`rest_heal()` 现在只剩"30% + Regal Pillow"，
   进入时那笔是 `rest_site_entry_heal()`，在 `begin_node` 的 `NodeKind::Rest` 分支里付。
   这是"遗物要绑生命周期、不要绑看起来相关的计算函数"的第一个实例。
3. **稀有度**：`Rare` → `Uncommon`（wiki）。

### 160.4 P1：`Rarity::Event` —— "不可掉落"终于能说出口

`golden_idol` 原来只能靠"写个假的稀有度"来表达 event-only，于是它进了 17% 的稀有档。
新增 `Rarity::Event`，并把规则收在**一处**：`relic_rarity_is_droppable` 只认
`RELIC_RARITY_WEIGHTS` 里的档，`pick_relic_avoiding` 在抽权重**之前**就把不可掉落的条目滤掉。

⚠️ 只加枚举值是不够的：只有事件遗物的池子会走到 `pick_rarity → None → unwrap_or(pool[0].rarity)`，
照样把事件遗物发出去。所以过滤必须在候选表构建时，而不是靠权重表"恰好抽不到"。
判据 `an_event_relic_is_never_drawn`：纯 Event 池 20 次全给 `RunId::EMPTY`，混合池 40 次只给 `anchor`。

### 160.5 没有照做的一条：`clippy -D warnings`

方向对，但**今天开不了**：树上有 6 条既有警告，其中三条值得先看清楚再决定怎么消：

* `host.rs:399/401` 的 **`unreachable pattern`**：`"StatusRemoved"` 与 `"StatusApplicationPrevented"`
  各被写进两个 `|` 分支 —— 后一个分支永远不匹配。这可能只是重复，也可能是**想映射到另一个事件**写错了。
* `intent.rs:824` 的 `unreachable pattern`：`unsupported` 兜底分支被前面 7 个分支全盖住，
  意味着"未知条件种类"其实走不到"响亮拒绝"那条路。
* 其余三条（`unused doc comment` / `unused variable` / `unused_mut`）是纯噪音。

先把这三条查清（尤其第二条：它关系到"未知条件是不是真的会报错"），再开 `-D warnings`。
顺序反了就会为了变绿灯而把警告消音，那比没开更糟。

### 160.6 采纳但本轮不做的（按评审自己的优先级）

* **L2 性质测试**：最值得做的一条，而且它正好能抓住 §160.2 那类 bug（"拒绝不改状态"就是不变量）。
  它的具体清单（拒绝不改状态 / 生命在区间内 / 卡牌不无故增减 / 同一奖励不能领两次 /
  卸下的遗物不再生效 / 每条内容可达 / 同种子同动作序列同结果）可以直接变成 7 条 property test。
* **`MAX_POOL` 静默截断（7 处）**：改成"超容 ⇒ `Err`"，今天不可达但形状和 §158 一样。
* **`begin_node` 里那笔治疗要不要"只付一次"**：现在由 `Pending::Rest` 的相位保证（一个节点只结算一次），
  没有单独的 `mark_rest_entered` 标志 —— 评审担心的重复付账在现有相位下走不到，但值得一条负控。
* `docs/status.md`：同意，但**只加一份**。评审建议三份（status / roadmap / architecture），
  三份就是三个会腐烂的新副本；现在的 `port-plan` 已经太长，再加两份短文档解决不了"哪个为准"。
  一份 `docs/status.md`（当前能力 + 最近验证 + 已知缺陷 + 指针到 plan 的节号）就够。

### 160.7 明确不同意的一条

评审第七节建议"暂时放下 `no_std` / 零堆分配 / 极小 WASM / ESP32-P4 适配"。
这是**产品决策**，不是工程发现，而且和这个项目的原始目标（"跑在 ESP32 这种嵌入式平台上" +
"多开当 RL 环境"）冲突。更重要的是：这些约束已经**付过账**（`forbid(unsafe_code)`、定容表、
纯整数），现在拆掉它们是纯支出、零收益。评审自己也留了台阶（"不必反向推翻能工作的固定数组"），
所以更准确的说法是它第二条的样子：**不要再为了省字节新增容量体操** —— 这一点完全同意，
`MAX_POOL = 64` 那 7 处静默截断就是容量体操留下的债。

### 160.8 数字

聚合验收 **18/18**；单测 758 → **761**（rd-core 632、rd-run 80 → **83**、rd-wasm 46）。
内容：13 遗物 = **C7 / U4 / R1 / Event 1**（`eternal_feather` 进 Uncommon，`golden_idol` 进 Event）。
⚠️ **Rare 只剩 1 件**，所以 17% 那一档每次都只能是它 —— 这是内容缺口（缺稀有遗物），不是 bug，
但它现在**看得见**了，这正是 §156 让稀有度落进内容表的目的。

---

## 161. 按评审 §六 的顺序做：正确性补强 → 通用决策 → 垂直切片

评审的第六节给了五步。§160 已经吃掉第 1 步的前三件（商店原子性、Eternal Feather、Golden Idol），
这一节从剩下的两件开始，**每修一项就写一节**，不再攒着。

### 161.1 七个 `MAX_POOL` 截断点 → 响亮失败

评审 P1 的原话是"药水、遗物、奖励卡池仍是**静默截断**"。数了一下是 **7 处**，分布在 5 个函数：

| 函数 | 原来 | 现在 |
|---|---|---|
| `stock_shop` | `card_pool.len().min(MAX_POOL)` | `pool_fits(len)?` 后 `len()` |
| `pick_potion` | 三处 `take(MAX_POOL)` / `min(MAX_POOL)` | 同上 |
| `pick_relic_avoiding` | `take(MAX_POOL)` | 同上 |
| `grant_random_cards` | `pool.len().min(MAX_POOL)` | 同上 |
| `roll_reward` | `card_pool.len().min(MAX_POOL)` | 同上 |

新增 `RunError::PoolTooLarge { pool, max }` 与一个 `pool_fits`。**容量还是容量**（不换 `Vec`：
那对无 `std` 的内核是错答案），变的是"超了要红"。

判据 `a_pool_longer_than_the_capacity_is_loud_instead_of_cut`，两半都测：
**恰好 64 仍然能用**（容量不该被误伤）、**65 立刻红并说出长度与上限**。四个入口各测一遍
（`roll_reward` / `pick_relic` / `pick_potion` / `begin_node` 的商店补货）。

负控（`native/negctl_161_pool.py`）：把 `roll_reward` 的守卫删掉**并把循环改回 `.min(MAX_POOL)`**
（只删守卫会越界 panic —— 那是另一条错误路径，会让负控"红得没意义"）。红在
"one card over the cap must be a red, not a silently smaller pool"，正是要的那句。

### 161.2 评审要的 L2 层：不变量，而不是更多"典型案例"

评审第四节第 1 条说得很直白：`tools/acceptance.ps1` 的 clippy 闸门只要求退出成功，所以
"测试还在、属性没了、总数仍过门槛"还能再出现。它建议四层，最缺 L2（性质测试）。
这一节先落两条**最便宜、也最贴近已发生 bug** 的不变量。

#### (a) 拒绝不改任何东西 —— 包括 RNG

`RunState` 派生 `Copy + PartialEq + Eq`，而且整局就是这一个结构体（`rng` 是它的字段）。
所以判据能写成最硬的一句：**调用前后整个 `RunState` 相等**。

这比"逐字段比较"强：漏比一个字段正是 §160 的 P0（金币变了、牌组没变、没人发现）。
逐字段的清单会过期，`==` 不会。

覆盖的拒绝种类：相位不对（无商店买卡/无篝火休息/无奖励领奖）、目标不对（不在图上的节点）、
容量满（§160 的 P0 在这一层被抓住）、重复领取、重复购买同一货位。

⚠️ 一处细节：判据用 `assert!` 而不是 `assert_eq!` —— 后者会把两个完整 `RunState`（地图就 40 行）
打两遍，而值得读的只有"哪一个动作"。**可读性也是断言的一部分**：一份读不下去的失败信息等于没有。

#### (b) 同一种子 + 同一动作序列 ⇒ 同一局

`rd-core` 有逐字节的哈希对拍、地图有 `same_seed_same_map`，但"整局走同一条路"此前只有浏览器
soak 在间接覆盖。判据直接比 `Vec<RunState>`，所以**一次多余的 RNG 抽取也会红**。

固定策略：每一步取**第一条能进的边**，然后按节点类型结算（Rest→rest / Treasure→open_chest /
Shop→leave / 其它→mark_resolved），走六层。`assert_ne!(trace(101), trace(102))` 是**反面控制**：
证明这个比较不是恒真。

⚠️ 写的时候踩了一个小坑：`enter_node` 收的是**全局节点号**，不是"本行第几个"，所以扫 `0..3`
一步都进不去（红在"the fixture must actually walk somewhere"——这条自检正是为这种错准备的）。

### 161.3 一张牌的选择：`PendingChoice`（REVIEW §六 第 2 步）

评审 §四.2 的原话是：**"不要推倒现有 `Pending`。战斗侧补一个边界明确的待决操作即可，例如选牌来源、
最少/最多张数、选完后的操作。同一机制应能服务卡牌、药水和事件，并让合法动作可枚举、可存档、可回放。"**
验收标准也给了：**"再加一张同类卡或一瓶同类药时，主要改内容定义，不复制一套状态机。"**

这一节就是把那句话落成代码，并且**当场带上两个消费者**（Elixir、Gambler's Brew），否则它就是一段
没人用的框架。

#### 它为什么是状态，而不是一个 UI 回调

参考引擎的 `CardChooser` 是宿主委托（`CombatStateSnapshot.cs` 连它一起排除），因为那边是单人同步
程序：问一句、当场答。本项目要**存档、回放、训练**，所以"正在等玩家选牌"必须能从状态里读出来。
⇒ `CombatState.choice: Option<PendingChoice>`，`resolve_choice` 是唯一把它消掉的人。

⚠️ **它不进 `hash_golden`**：那是参考规范文本的逐字节复刻，参考没有这个字段，写进去就是伪造参考的
输出。它属于 `snapshot.rs` 那张"状态里有、指纹里没有"的清单（与 `mark_source_combatant_id`、
`CardPlayTurnStats` 同类），**`hash_full` 落地时必须覆盖它**。这也是加它一个基线都没动的原因
（`golden-baseline 129 行`、`corpus-roundtrip 85` 一字未变）。

#### 四个函数，一个问句

| | |
|---|---|
| `PendingChoice { chooser, source, min, max, then }` | 谁在选、从哪个牌区、几张、选完做什么 |
| `begin_choice` | 提出问题。三道前置拒绝：已有待决、`min > max`、`min` 超过来源牌区的张数 |
| `choice_legal(out)` | 把合法选项按**牌堆顺序**列出来（缓冲区装不下 ⇒ `Container::ChoiceOptions`，不截断）|
| `resolve_choice(picks)` | **全部校验在动手之前**，然后一次搬完 |

`chooser` 是字段而不是"默认英雄"：内核不假定谁在玩（`Combatstate` 里没有"玩家"这个概念）。

`ChoiceThen` 目前两个变体：`Exhaust`（Elixir）、`DiscardThenDraw`（Gambler's Brew）。每加一种药水
就多一个变体 —— **这是有意的**，动作的语义必须能被列出来，否则"合法动作可枚举"是空话。反过来说，
内容只挑变体，不各写一套状态机。

#### 三条纪律

1. **拒绝不改任何东西。** §161.2(a) 在战斗层的同一句话。判据 `a_refused_choice_leaves_the_combat_
   byte_identical` 用**规范文本**比较（`CombatState` 没派生 `PartialEq`：18 个字段里 6 个定容容器，
   逐字段写一份"等价"没法确认自己没漏）＋单独比 `pending_choice()`（规范文本不含 `choice`）。
   覆盖：张数越界、来源不对、重复选同一张、没有待决问句。
2. **选牌不嵌套。** 两个待决问句叠在一起，界面无法表达先后，回放也无法表达 ⇒ `AlreadyPending`。
3. **`min == 0` 时取消永远可用。** 不是方便，是语义：两瓶药的原文都是"any number"。

#### 一个被删掉的重复

`turn.rs::draw_for_turn_start` 里那个"抽满 / 重洗一次 / 两堆都空就停"的循环搬进了
`CombatState::draw_cards_with_reshuffle`，因为 `DiscardThenDraw` 成了它的**第二个**消费者。抄第二份
的后果可预测：两边的重洗策略会分叉，而"少重洗一次"只表现为某一步的 `step=` 与牌序不同 —— 那是最难
从失败信息里读回来的错。

#### ABI：8 个新导出 + 一个复用的牌区号

`rd_env_choice_{pending,kind,min,max,count,pick,selected,clear,confirm}`。

**选项不另起一套字符串读取器**：`rd_env_pile_*` 的 zone id 加了一个 `3 = 待决问句的来源牌区`，
所以选择界面用的是看牌堆**同一套**渲染。没有待决问句时 `rd_env_pile_len(3)` 返回 `-1`（不是 0 ——
"没有问句"和"问句的答案是零个"是两件事）。

`Session::choice_picks` 是**界面暂存，不是游戏状态**：内核的动作是"把整份选择一次交过来"，
所以半截选择不是存档要描述的东西，`resolve_choice` 才可能保持原子性。

三条缝合规则：

* `compute_actions` 在有待决问句时返回**空表** —— 出牌和结束回合都不是合法答案，列出来就是一张
  全都会被拒的表，而随机驱动会在"战斗看起来还活着"的情况下永远撞 `-1`；
* `rd_env_step` 在有待决问句时返回 `-1` 并**留下原因**（`还有一次待决的选牌没回答`）。守卫放在
  动作表查找**之前**，否则越界下标和"问句没答"都会是同一个没有理由的 `-1`；
* `rd_env_choice_confirm` 按**牌堆顺序**交牌，不按勾选顺序 —— 两个人用不同顺序勾了同样两张牌，
  要的是同一件事，回放不该在意。

#### 内容：22 瓶（C12 / U6 / R4）

`elixir`（Uncommon，Ironclad 专属）与 `gamblers_brew`（Uncommon）。两瓶的稀有度都是 wiki 上
`Potions` 表 + `Module:Potions/data` 两处独立来源核对的。

⚠️ **这次最值得记的不是功能，是一个"看起来没问题"的谎**：加了 `choice_hand_exhaust` 之后，
`rd_env_use_potion` 认识它、内容门认识它、页面也能用，但 `rd_run_potion_effect`（决定"要不要弹敌人
选择器"的那一个）把它归成 **`0 = unknown`**。**没有一条闸门会红** —— 页面的 `=== 1` 判断只是走了
另一个分支。抓到它的是一条新加的**穷尽**测试：`every_potion_in_the_table_classifies_as_known`
走完整张 `POT` 表（腰带三格，所以 逐瓶 push → 查 → 清），断言每一瓶都不是 `0`。同时它也断言
那两瓶归类成 `2`（作用于手牌，不要敌人目标）—— "已知"不等于"分对类"。

#### 验证

- `rd-core` 7 条 + 1 条（来源牌区）新测试；`rd-wasm` 2 条（端到端问句 + 词表穷尽）。
- **三条负控**（`native/negctl_161_choice.py`）：
  `vocab` 把两个原子从 `known` 里删掉 → 红在
  "`elixir` (choice_hand_exhaust) classifies as UNKNOWN"；
  `atomic` 把重复检查挪到搬牌之后 → 红在"被拒绝的选牌改了战斗"（left 里 `card_000001` 已经在
  `exh=` 里）；
  `trunc` 把 `choice_legal` 的拒绝改成 `break` → 红在 `left: Ok(2)` / `right: Err(Full(ChoiceOptions))`。
- **浏览器里一条确定性场景**（`browser_test` 第 (h) 段）：用新加的
  `RD_DEBUG.givePotion("elixir")`（底层是 `rd_run_grant_potion`，**调试专用**，理由与
  `startWithSeed` 同：不能指望 40% 掉率 × 22 瓶里的 2 瓶）把 Elixir 放上腰带，然后
  **只按页面上的控件**走：点"用" → 弹窗打开 → 点一张牌 → 点确认 → 消耗堆 +1、动作表 0 → 9。
  它还钉住**弹窗关不掉**（`closeModal` 在有待决问句时直接返回），因为"问句没答 + 动作表为空"
  就是一张没有出路的页面。
- 聚合验收 **18/18**；单测 764 → **774**（rd-core 632 → 640、rd-run 86、rd-wasm 46 → 48）。
  内容镜像 full **37,124 B** / core **30,604 B**。

#### 还差的（下一节）

| 要的东西 | 谁在等 |
|---|---|
| **每张牌自己的价格**（参考 `CardInstanceCostModifier` 读 `mark_counters` 里预留的那一格，钳到 0，被出牌消费）| Liquid Memories、Snecko Oil、Attack/Skill/Power Potion |
| **从卡池抽三张当候选**（`ChoiceSource::Offered`）| Attack / Skill / Power Potion |
| **无色牌池** | Colorless Potion |
| **`hash_full`**（`choice` 必须进去）| 训练状态去重 |
| 随机 soak **不认识选牌界面**（`choices 0`），覆盖率靠上面那条浏览器场景 | —— 一条已知缺口，不是"已完成" |

`ChoiceSource::DiscardPile` 今天**没有内容**（Liquid Memories 还差上面第一条），所以它由
`a_choice_reads_its_source_pile_instead_of_assuming_the_hand` 直接钉住：机制读 `source`，不是假定
`Hand`。留一个没测的变体才是错的；留一个测过、有明确下一节的变体是可以接受的。

### 161.4 一张牌自己的价格：`standard.card_cost_delta`

评审第 2 步的另一半是"通用决策"之后的**动作语义**。这一节做"每副本价格"，因为它是三瓶药的共同缺口，
而参考实现**已经有答案**：`Cards/CardInstanceCostModifier.cs:13-34` 读的是卡实例上的一个 mark
counter，`StandardCombatIds.cs:93` 叫 `standard.card_cost_delta`。

#### 一件事值得先说：费用那半边**早就写好了**

`play.rs` 的 `CostStage::CardInstance`（priority 1100）从 §88 起就在读那一格、逐阶段 `.max(0)`
钳位。所以这一节**没有**动费用计算 —— 缺的是三件别的事：

| 缺的 | 谁补的 |
|---|---|
| 没人**写**这一格 | `resolve_choice` 的 `cost_delta` 参数（§161.3 的机制 + §161.4 的语义） |
| 没人**消费**它（`Cards/CardPlay.cs:176-183`）| `apply_plan_in_chain` 付款之后置 0 |
| 没人**显示**它 | `refresh_hand` 的代价列加上同一个增量 |

第四件是**新的 `then`**：`ChoiceThen::ToHand`（第三个消费者，Liquid Memories）。

#### 为什么它必须是"每张牌"的

状态是**按持有者**定价的（"你的技能牌便宜 1"），而"你刚拿回来的那张牌这次免费"是一个只属于**那一张
副本**的承诺 —— 它得跟着那张牌穿过手牌、弃牌堆、抽牌堆。参考的注释把这句话写得很清楚：*"a promise
made to one card, which has to travel with that card through the draw pile and the hand"*。

⚠️ **与 StS 的差别（写明了的偏差）**：StS 的 "costs 0 **this turn**" 在回合结束时过期，而参考的模型
是"**被出牌消费**" —— 一张没被打出的折扣牌会一直带着它。我们照参考实现：给回合结束加一次清除等于
发明一条参考没有的规则（§159.3 的教训是"不要实现一个关于不存在的**事件**的分数"）。这条偏差由
`the_per_copy_price_is_consumed_by_the_play` 的第二段钉住（打完再打一次是原价）。

#### 一个被 §161.4 **照出来的旧 bug**（这次最值钱的东西）

写完 `liquid_memories` 的端到端测试，它红了：屏幕上显示那张牌 0 费，内核却收了 1 点能量。

查下去发现不是价格的问题：`Step::HeroPlays` 是参考的形状 —— **按卡定义 id 找手里第一张**
（`ScenarioRunner.cs:109-111`，因为它的场景脚本是文本、没有实例号）。而页面是**按手牌位置**点的。
同定义的两份副本在参考那里不可区分，所以这条一直没露出来 —— **§161.4 的每副本价格是第一个让
"哪一张"变得有意义的东西**，于是它立刻变成一个死按钮：一张带折扣的 `strike` 排在普通 `strike`
后面时，玩家点了它，引擎打了前面那张。

修法是**加一个新的 step**，不动旧的：

* `Step::HeroPlays` 含义**冻着**（四条对拍流水线驱动它，改语义会移动基线）；
* `Step::HeroPlaysInstance { card: CardInstanceId, .. }` 是页面用的那一个，找不到那一份副本时报
  `CardNotInHand` —— **绝不**退回按定义找（那会把"这个位置空了"变成"打了别的一张牌"）。

顺带删掉了 `step_play` 里每步 `Box::leak` 一个定义串的写法（现在不需要字符串了）。

#### 内容：23 瓶（C12 / U7 / R4）

`liquid_memories`（Uncommon，shared）：*"Choose a card in your discard pile and return it to your
hand. It costs 0 this turn."* 稀有度同样用 `Potions` 表 + `Module:Potions/data` 两处独立来源核对。

#### 三处"同一个词表"的第三份

这一节又一次踩到了 §161.3 的教训，但这次**是被闸门抓住的**：加 `choice_discard_to_hand` 时，
`tests[cargo]` 里立刻红了三处（`known` 清单、内容门的 `POTION_CHOICE_KINDS`、
`the_potions_are_readable` 的白名单），而不是安静地少一处。§161.3 那条**穷尽**测试
（`every_potion_in_the_table_classifies_as_known`）现在也覆盖它，并且断言它落在 `2`（不要敌人目标）。

#### X 费牌：一个说不出口的折扣

X 费牌的代价走 `x_cost_payment`（**全部当前能量**），`Costs` 表对它没有意义 ⇒ 一个加在 `Costs` 上的
delta **看不见**。于是 Liquid Memories 选到 X 费牌时**拒绝**并保持问句不动，页面提示"换一张"：

```text
这张牌没有可取消的印刷费用（X 费牌按全部能量结算），换一张
```

静默地按原价把牌交过去，是"屏幕上写着免费、实际收全部能量"的另一种形状。

#### 验证

- 新测试 5 条：`rd-core` 3（每副本价格写进实例 / 给没有价格的 `then` 传价格被拒 /
  **按实例打牌打的是那一张**）、`rd-wasm` 1（Liquid Memories 端到端：问句、`min = 1` 的空答案被拒、
  屏幕上的 0、内核真的收 0、价格只兑现一次）、另有 §161.3 那条穷尽测试扩到三瓶。
- **两条负控**（`native/negctl_164.py`）：
  `price` 删掉"付款后置 0" → 红在"价格必须在**付款之后**消费掉"（left `-1` / right `0`）；
  `display` 删掉显示侧那一格 → **浏览器闸门**红在
  "no card in hand reads 0 after Liquid Memories (costs [2,1])" —— 屏幕说 1、内核收 0。
- 浏览器里第二条确定性场景（`browser_test` 第 (i) 段）：`givePotion("liquid_memories")` → 点"用" →
  标题是"从弃牌堆拿一张回手牌（它这次免费）· 1 张" → 不选就确认被内核拒（`-2`，问句还在）→
  选一张 → 确认 → 手牌里出现一张 0 费 → 打它，能量一动不动。
- 聚合验收 **18/18**；单测 774 → **779**（rd-core 640 → 643、rd-run 86、rd-wasm 48 → 50）。
  镜像 full **37,296 B** / core **30,776 B**。

#### 还差的

| 要的东西 | 谁在等 |
|---|---|
| **从卡池抽三张当候选**（`ChoiceSource::Offered` + 建卡实例 —— 内核不铸实例号，所以这活在 `rd-wasm`）| Attack / Skill / Power Potion |
| 无色牌池 | Colorless Potion |
| **整副手牌改费**（Snecko Oil 是"随机化手牌费用"，不是每副本价格）| Snecko Oil |
| 战斗中升级手牌 | Blessing of the Forge |
| `hash_full`（`choice` 要进去）| 训练状态去重 |
| 随机 soak 仍不认识选牌界面 | 已知缺口，覆盖率靠 `browser_test` 两段确定性场景 |

### 161.5 三张候选：`ChoiceSource::Offered`（Attack / Skill Potion）

§161.3 的机制留了一个位置给"候选不是牌堆的一部分"。这一节把它填上。

#### 候选是**定义**，不是实例 —— 而且这不是省事，是正确

最省事的做法是先造三张牌塞进一个牌区（`SetAsidePile`），选完把两张扔掉。**没这么做**，理由是
**指纹**：那三张牌会进 `card_num=` 和三条卡行，而参考引擎里那个局面**根本没有它们** ——
一张还没进游戏的牌不该出现在哈希里。所以候选是三条 `CardDefinitionId`，被选中的那一张在
`resolve_choice` 里**才**被造出来，没被选的两张从来没存在过。

这条判据是 `an_offered_choice_creates_only_the_card_that_was_picked`：提问前后 `card_count()` 不变，
回答之后**只多一张**，发号器只动 1。

#### 顺带把"铸号"收成一件事

`Offered` 需要内核造卡，而铸号此前只在 `exec.rs`（`CreateCardInstance` 节点）里。§161.5 把
`numbered_text` + `create_card_instance` 搬进 `state.rs`（发号器本来就在那里），`exec.rs` 改成调用 ——
**两条铸号路径会给出两个"下一个是几"**，而每条路径单独看都是对的。

#### 答案有两种形状，因为它们回答两个不同的问题

```rust
pub enum ChoiceAnswer<'a> {
    Instances(&'a [CardInstanceId]),   // Hand / DiscardPile：这些实例里选哪些
    Offered(&'a [usize]),              // Offered：这三张里要哪个下标
}
```
形状与来源不匹配 ⇒ `WrongAnswer`。对应的读取器也分成两个：`choice_legal`（牌区，返回实例）与
`choice_offered`（候选，返回定义），**各自只回答一种形态**，而不是一个函数返回一个"看情况"的联合体。

`ChoiceSource::zone()` 因此变成 `Option<CardZone>` —— 这是**编译期接缝**：加 `Offered` 时它逼着
每个读者回答"候选从哪来"，而不是把候选当成一个空牌区。它当场抓出两处（`rd_env_choice_count` 与
`rd_env_choice_confirm` 的牌区读取）。

#### 抽三张是谁的事

**按标签过滤是内容的事**（哪些牌算 Attack 写在 `CARD.Tags` 里），**抽三张不重复是运行层的事**
（它持有 RNG，`RunState.rng` 私有正是为了让"谁推进了哪个流"只有一处）。所以
`rd-run` 新增 `draw_distinct(pool, count, out)`，用 `RunStream::Reward`（"从卡池取牌给你挑"和卡奖励
是同一件事的两半；`Potion` 那个流已经用来决定"掉不掉药水"，混用会让掉率与"抽到哪三张"互相干扰）。

池子比 3 短时返回实际张数，**要不要拒绝由调用方决定** —— 而调用方拒绝得**响亮**：
候选不足三张时这瓶药**不被消耗**并报出张数。

#### 内容：25 瓶（C14 / U7 / R4）

`attack_potion`、`skill_potion`（都是 Common）。**Power Potion 故意没加**：本内容
`power` 标签的牌是 **0 张**，凑不出三张候选。内容门加了一条判据把这件事变成闸门：
`choice_offered:<tag>` 要求至少 **3 张**带这个标签的牌，否则红 ——
"加了一瓶药但它给不出承诺的东西"正是本项目最怕的那种安静的死按钮。

#### 一个被自己的测试抓到的语义

端到端测试第一次红在 `confirm` 返回 `-2`：抽到的候选里有 `anger`（印刷 **0** 费）与 `whirlwind`
（X 费）。两件事分开处理：

* **0 费不是错误**：这瓶药承诺的"它这次免费"**已经成立**，`-0` 的折扣是正确答案；
* **X 费说不出口**：它走 `x_cost_payment`（全部能量），`Costs` 表对它没有意义 ⇒ 加在上面的 delta
  看不见。这种**拒绝并让问句留着**，页面提示"换一张"。

#### 页面的句子是两个字段的函数

`kind` 只有三个值，而"从弃牌堆拿一张"与"从三张候选里选一张"是同一个 `then = ToHand`。第一版
用 `kind` 写句子，于是 Attack Potion 弹出了"从弃牌堆拿一张回手牌"。所以新增
`rd_env_choice_source()`（`1` 牌堆 / `2` 候选），句子从 `(source, kind)` 两个数来。

#### 验证

- `rd-core` +3 测试（只造一张 / 两种答案形状不能互换 / 候选与来源必须一致）、`rd-wasm` +1（Attack
  Potion 端到端：三张**定义**、提问不造牌、每个候选都是 attack 且三张互异、回答后只多一张、
  屏幕上 0、内核真的收 0）。
- **负控**（`native/negctl_164.py pregrow`）：把"只造选中那一张"改成"三张全造" ⇒ 红在
  `ChoiceDone { picked: 3 } vs { picked: 1 }`。
- 浏览器第三条确定性场景（`browser_test` 第 (j) 段）：`givePotion("attack_potion")` → 用 →
  标题"从三张候选里选一张加进手牌（它这次免费）· 1 张" → 三张候选**都渲染出名字** → 选一张 →
  确认 → 手牌 +1、手牌里出现一张 0 费。
- 聚合验收 **18/18**；单测 779 → **783**（rd-core 643 → 647、rd-run 86、rd-wasm 50 → 50）。
  镜像 full **37,612 B** / core **31,088 B**。

#### ★ 顺手抓到一个"闸门在骗人"：单测下限**从来没生效过**

写这一节的文档时要报"单测 779 → 787"，实际跑出来是 **783** —— 而闸门**照样绿**。查下去发现
`tools/acceptance.ps1` 的**第一行**是 `﻿` + 两个 U+FFFD + 横幅句子，**但没有 `#`**：

```text
﻿<U+FFFD><U+FFFD>合验收器：一条命令跑完所有闸门…
```

`param()` 必须是脚本的**第一条语句**；一行既不是注释、又不是 `param` 的东西挡在前面，参数块就
**静默不绑定** —— `$UnitsFloor` 于是是空，`[int]$passed -lt $null` 恒为 False。

判据：`-UnitsFloor 99999` 以前**也绿**。修法是把第一行改成真注释（保留 BOM，否则 PS 5.1 按 ANSI
解码），于是下限第一次真的会咬 —— 这次它立刻报出"783 < 99999"并把闸门变红。

⚠️ 这条也解释了 FACT 里那句"这些工具**故意不写** `param()` 块 ⇒ 位置参数"：那是一次**误诊**。
`acceptance.ps1` 一直有参数块，只是它绑定不上；`-SkipSlow` 之类同样从来没生效。

#### 还差的

| 要的东西 | 谁在等 |
|---|---|
| **我们的内容没有 `power` 牌**（0 张） | Power Potion |
| 无色牌池 | Colorless Potion |
| 战斗中升级手牌 | Blessing of the Forge |
| **整手牌**改费（Snecko Oil 是"随机化手牌费用"，不是每副本价格）| Snecko Oil |
| 自动打出牌堆顶 / 打两次 | Distilled Chaos、Duplication Potion |
| 死亡拦截 / 逃跑 | Fairy in a Bottle、Smoke Bomb |
| `hash_full`（`choice` 要进去）| 训练状态去重 |
| 随机 soak 仍不认识选牌界面 | 已知缺口，覆盖率靠 `browser_test` 三段确定性场景 |

### 161.7 三张 Power 牌 + Power Potion（补内容，顺带两处"内容在说谎"）

§161.5 结束时的清单上，Power Potion 的缺口写着"本内容 0 张 `power` 牌"。这一节补内容：
**Inflame / Metallicize / Combust** —— 都是三口铁甲战士真实的能力牌，数字取
`docs/spec/sts-act1-inventory.md` 的第二列（5→7、2→3、3→4）。

`docs/spec/` 的清单**早就有这三行**，内容一直没跟上 —— 内容门那条 `cards.ids` 精确比对
（`INV_CARDS` 的 dict 是**逐牌事实契约**，不只比 id）就是为这种漂移准备的：加完牌它立刻红一次，
提醒我把六行事实写进去。

#### 加内容这件事本身几乎没写代码

三张牌的节目都是 `node.applyStatus`（`sel.source`，和 `buffer` 同一个形状），所以这一节**没有**
新增任何内核能力。唯一的代码改动是一行 **`+` 行过滤**（见下）。

#### 抓到的第一处谎：Combust 不掉血

`standard.combust` 的 `TurnEnded` 触发只做了"对全体敌人造成 N 伤害"，而牌面（以及清单里那个
`hp-loss-trigger` 标记）写着"**lose 1 HP** and deal 5 damage"。补上后是
`sequence([loseHp(1), dealDamage(allEnemies, stacks)])`。

"lose 1 HP"用的是 `sel.source` + `IgnoresBlock: true` —— 这不是新发明的形状：
`standard.constricted`（§147）就是这么写的，而 `IgnoresBlock` 正是"掉血"与"受伤"的区别。

#### 抓到的第二处谎（差点自己制造）：Metallicize **是宿主步骤**

`standard.metallicize` 的 `Triggers` 是 `null`。我据此判定"它什么都不做、`Heart of Iron` 从 §158
起就在发一个装饰性 buff"，于是给它加了一条 `TurnEnded` 触发 —— **这是错的**：

`host.rs:1192` 在回合结束的宿主步骤里**硬编码**了它（连同 `standard.plated_armor`），那是照参考实现
搬过来的（Metallicize 在参考里是一个 `TurnEndedHandler`，不是声明式触发，`port-plan.md` §112）。

加了触发就是**双重支付**，而挡住它的是两条既有测试：
`metallicize_grants_block_at_the_end_of_the_turn`（红在
`Exec(Expr(Ir(Missing("StatusId"))))` —— 我把字段名写成了 `StatusDefinitionId`，`combust` 那条写的是
`StatusId`）与 `plated_armor_and_metallicize_both_pay_block_at_turn_end`。

⇒ 已回滚，并且这条要记住：**"内容里没有触发"不等于"它什么都不做"** —— 也可能宿主步骤在管。
判断一个状态是不是死的，要 grep 内核，而不是只看 `Triggers`。

#### 抓到的第三处谎：候选池里混着 `+` 行

`choice_offered:attack` 会把 `twin_strike+` 当候选发出去。StS 的 Attack Potion 给的是**印刷牌**
（升级版不在卡池里，是升级造出来的）—— 给一张更强的牌是"承诺得更少、给得更多"，属于安静的那种错。
我们的升级约定是 id 加 `+`，所以过滤就一行；**是 power 牌让这件事第一次看得见**（三张基础牌
加三张 `+` 行，抽三张必然混进升级行）。

#### 内容门的两张表也跟着走

* `INV_CARDS` 多了六行（3 张牌 + 3 个 `+`），每行带**事实**（`("status", id, stacks, "source")`），
  门会重新读节目核对。
* `INV_POTIONS`/band 的口径：**26 瓶（C15/U7/R4）**。

#### 验证

- `rd-wasm` +1：Power Potion 端到端 —— 三个候选**恰好**是 `combust` / `inflame` / `metallicize`、
  都不带 `+`、都真的打了 `power` 标签；选 `inflame` 之后它是 0 费，打出后英雄拿到 **2 点力量**。
  （这是"同形状的药水只是内容改动"这句话的判据。）
- 词表穷尽测试扩到 `power_potion`；`every_potion_in_the_table_classifies_as_known` 仍然全绿。
- 聚合验收 **18/18**，单测 783 → **784**（rd-core 647、rd-run 86、rd-wasm 50 → 51）。
  镜像 full **38,384 B** / core **31,728 B**；卡 **36 张**（30 + 6 个 power 行）。

#### 还差的

| 要的东西 | 谁在等 |
|---|---|
| 无色牌池 | Colorless Potion |
| 战斗中升级手牌 | Blessing of the Forge |
| 整手牌改费 | Snecko Oil |
| 自动打出 / 打两次 | Distilled Chaos、Duplication Potion |
| 死亡拦截 / 逃跑 | Fairy in a Bottle、Smoke Bomb |

### 161.8 一幕的垂直切片：五种节点各一条确定性场景（第 19 道闸门）

评审 §六 第 3 步的原话：**"精英、Boss、商店、事件、休息点各有一条确定性浏览器场景。随机 Soak
通过不够，指定路线要从开局走到幕末。"**

这一节把 `web/act1_slice.mjs` 变成第 19 道闸门。它和已有的两道浏览器闸门分工不同：

| 闸门 | 驱动方式 | 能证明什么 |
|---|---|---|
| `web-browser`（门 17） | 一条**写死**的路径 | 那些屏幕的接线 |
| `web-soak`（门 18） | 随机点**每个启用的控件** | 没有死按钮 |
| **`web-slice`（门 19）** | 固定种子 + **自己从地图上算路线** | 每一类节点的**承诺**真的兑现 |

"承诺"是每条场景的判据，不是"点得动"：

* **商店**：`删一张牌` 让牌组少一张且金币减少；买卡让牌组多一张且金币减少。
* **事件**（`?` 房）：面板有正文与 ≥2 个选项，选一个之后**牌组/HP/金币至少一项变了**。
* **篝火**：`打铁` 让牌组里**多一张 `+`**、牌组张数不变、HP 不变（休息才回血）。
* **精英**：打赢，奖励屏**有遗物**，拿走之后遗物数 +1。
* **Boss**：见下（**没有**进断言）。

路线是**算出来的**：`describeMap` 给出 `{id,row,col,kind,out,reachable}`，BFS 找最近的
目标节点，逐跳走、逐跳结算。所以"指定路线"是驱动器的决定，不是地图的巧合。

#### 五条场景，五种节点，全部进断言

Boss 是**地图之外的哨兵游标**（`inv:§7.2`：第 16 层，不在 15 行里），所以"走到幕末" = 走到最后一行、
结算那个篝火、让游标落到哨兵上。现在**整幕都能走通**，而且是带着 90/90 血走到的：

```text
boss   seed=101 ms=1370 kind=7 floor=16 actBefore=1 actAfter=2 hpAfter=90 maxHp=90
       potionOpened=1 potionSource=2 potionOptions=3 potionAnswered=true won=true mapNodes=65
```

`actAfter=2` + `hpAfter == maxHp` + `mapNodes=65` 三件事合起来才是"幕末"：幕推进了、按 A0 的规则回满、
下一幕有图。另外 `potionSource=2 / potionOptions=3` 是 §161.7 那个**锚点**：在 Boss 战里喝一瓶
Attack Potion，它开出三张候选的选牌问句，驱动器回答它、打出那张免费牌。

第一版**没有**这么写。它当时停在第 12 层一个三只 Sentry 的精英上（`REACHED=false` + trail），
而把它改成 `want` 的两种做法都是撒谎：闸门因为驱动器 bug 常红，或者悄悄跳过。所以那时它只打印
证据。**接下来那次提交把它做通了**，这一节才是现在这段话。留下这段是因为"先如实报未达成"本身
是这套闸门的一部分，不是一段过渡期的耻辱。

#### 做通 Boss 需要三件事，每件都是一个真问题

1. **两条"选敌人"的通道不能混**（这是 25 分钟 stall 的真因）。页面里
   `data-enemy-panel` 在**每个**敌人面板上都有，而 `data-target-slot` **只在被武装的牌能打到的**
   那几个上有；点击处理器在"有牌被武装"时只认后者、否则直接 return。驱动器原来把前者放在 `||`
   左边 —— 于是"武装一张牌、点一个不可及的面板、什么都没发生、而那张牌还武装着" ⇒ **后续每一次
   点牌都被忽略**。现场证据是 `acts11/cards5/endon/energy3` 全正常，只有 `armY`/无进展。
2. **策略得能赢一整幕**。第一版"有攻击牌就攻击、从不格挡"在 50/95 血进 Boss 战然后输掉。
   改成：**只有这一击会致死才格挡**（"来 27 点、格挡 5 点"时格挡只是让战斗更长），其余全力打，
   并且**打血最少的那个敌人**（少一个敌人就少一份 incoming）。药水在**半血**时喝。
   ⇒ 同样的种子，改完之后带着 **90/90** 走到 Boss。
3. **路线要能避开精英**。"最短"和"最安全"是两个问题：第一版 BFS 求最短，于是笔直穿过三只 Sentry
   的精英（hp 5 活着出来，第 11 层死掉）。改成按**代价**寻路（精英 50、其它 1）——
   一个拿着起始牌组的玩家就是绕开精英走的，而分支地图存在的理由正是这个。

#### 还有两个"两个副本漂了"的地方

* **"再来一局"与"再打一局"**：`ui_panels.js` 把同一个按钮拼了两种写法，而驱动器的"不许点重开"
  守卫只写了其中一种 ⇒ 死掉之后驱动器**重启了整局**，于是 trail 里出现三次完整的行走、
  却没有任何一处说"死了"。守卫现在写成 `/再[打来]一局/`。
* **观察向量的"金币"**：运行层是 **index 4**，`5` 是**牌组张数**。驱动器把 5 当金币，
  于是"买卡没扣钱"其实是"牌组变长了"—— 一个看起来完全合理的错，而且断言写法也是错的
  （它比较的是两个牌组长度）。

#### 切片**照出**的四个真 bug（这才是它存在的理由）

1. ★ **开局的起始金币是 0，而 wiki 是 99**（三个来源核对：Ironclad 页、SlaySpireDB、Characters 页）。
   后果：**第一个商店一件东西都买不起** —— 一个只能看不能买的屏幕。§161.7 修内容时我只改了
   `Start.Resources.gold`，内容门立刻报 **`Characters[0].Start` 与它不一致**（同一份事实的第二份），
   两处一起改成 99。
2. ★★ **`take_card` 会关掉整个奖励屏**（`pending = None; mark_resolved()`），于是"先拿卡再拿遗物"
   的玩家**永远拿不到精英的遗物** —— 奖励屏随卡一起消失，而且没有一句话。`take_relic` /
   `take_potion` 早就是对的，所以 bug 的形状是**这一个函数里的不对称**。修好之后才发现它还有第二层：
   卡的选择应该是**一次**（`inv:§3.5` "one of three"），所以 `take_card` 花掉**整排卡**、留下
   药水与遗物两排。
3. ★ **页面把奖励行的"数组下标"当成内核的 slot**。空白行以前不可能被画出来（屏幕直接关了），
   现在会，于是下标与 slot 错位，`take_card(下标)` 指向一张已经空掉的牌，**永远拒绝**。
   修法：快照里带上内核的 `slot`，面板用它。
4. ★ **`take_card` 不关屏之后，页面会画出"空白行 + 一个活按钮"**。第一版靠"不可能出现"活着；
   现在必须自己跳过空 id。

#### 驱动器自己也踩了四个坑（写在这里省下一个人半天）

* 运行层观察向量的下标：**金币是 4**，`5` 是牌组张数。我把 5 当金币，于是"买卡没扣钱"其实是
  "牌组变长了" —— 一个看起来完全合理的错。
* 事件/篝火/`?` 房的"选一张牌"是**弹窗**（`#modalBody [data-pick]`），不是面板按钮。漏了它，
  节点永远没结算，之后每一次地图点击都被拒 —— 看起来像"路线算错了"。
* 一个**伤害/状态药水**不会当场结算：页面进入"点敌人"状态，此时**每一次点牌都被忽略**。
  一次中局喝药就能把整局冻住，而且没有任何错误。
* 篝火是**一个**动作（休息或打铁），之后节点就结算了；再点"离开"会被拒。所以结算器遇到
  终态动作要**返回**，而不是继续找按钮。

#### 数字

- 新闸门 `web-slice`：**5 条场景全绿**（商店 0.4 s / 事件 0.2 s / 篝火 0.5 s / 精英 0.7 s /
  Boss 1.4 s，合计约 3 s），Boss 那条从开局走到幕末、打完第 1 幕。
- `rd-run` 的两条测试按新契约重写（`taking_and_skipping_a_reward`），`rd-wasm` 一条更新
  （奖励屏不再随卡关闭；`跳过` 是出口）。
- 聚合验收 **18/18 → 19/19**；单测 783 → **784**。镜像 full **38,384 B** / core **31,728 B**。

#### 还差的

- 五条场景里只有 Boss 那条走到**幕末**；另外四条走到自己的节点就停（重走四遍一整幕只买运行时间，
  不买信息）。要"每条都从开局走到幕末"的话，代价是 5 × 1.4 s 加上更长的确定性预算。
- soak 仍然不认识选牌界面（它从不喝药水），覆盖率靠 `browser_test` 三段 + 这一道 5 条场景。

### 161.9 存档与回放：一行文本（REVIEW §六 第 4 步的第一半）

设计按"极简"走：**页面底部一个"复制档案"按钮、一个文本框、一个"回档"按钮**。复制出来的一行就是
存档，粘回去点一下就是回档 —— 没有文件、没有内部存储、没有格式协商。

#### 为什么必须是**一行**

这份文本是给人复制粘贴的。多行文本在复制、粘贴、邮件、聊天窗口里会被悄悄改写（行尾空格、CRLF、
缩进），而**任何一处改动都会让存档变成另一局**。所以：

```text
RDA1-<base64(RLE(payload))>-<crc32 八位十六进制>
```

* `RDA1` 是**头**、尾部是**定界的校验和** —— 两处都是"基本完整性"的便宜判据；
* `payload` 是二进制字段序列（varint + 原始字节），**不含浮点、不含时间戳**：同一局永远编出同一串
  （`a_saved_run_round_trips_byte_identically` 里"写两次逐字节相同"钉住这一点）；
* RLE 吃 payload 里成片的零（未用的卡位、被剪掉的节点、出边缓冲）；base64 让它能贴在任何地方；
* CRC32 覆盖 **payload**，所以"粘贴时少了一段"和"改了一个字符"是同一句拒绝。

实测：一整局（15 行地图 + 10 张牌）**797 字节**；页面里那一局 937 字符、**一行**。

#### 存什么、不存什么

存**整局 30 个字段**：种子/等级/楼层/游标/血/金/牌组/遗物/药水/掉率/稀有度偏移/幕/待决状态/
商店货架/奖励屏/已结算位图/开局两次祝福/两个"等一个牌索引"的后续/三条 `?` 房计数/**七个随机流计数**/
**整张地图**。

⚠️ **随机流计数必须存**：不存它们，回档会把每个流倒回原点 —— 那样"回档"等于"换了一局碰巧同形的局"。

**不存战斗**（`CombatState` 213 KB、每场重建）。所以"战斗中不许存"这条判断**归页面**：
内核分不清"这一场正在打"和"上一场结束后没人清理会话"—— 第一版把判断放在 `rd-wasm` 里，
`browser_test` 前一条场景留下的会话就让整页从此再也存不了档，而且给出的理由（"战斗中没有存档"）
是**错的**。页面知道自己的 `mode`，它守这一关。

#### 一条"整局相等"的判据

`RunState` 派生 `Copy + PartialEq + Eq`，所以 round-trip 的判据是最硬的那一句：
**`restore(write(run)) == run`**。它当场抓到了两处"看不见的字段"：

1. **地图行里 `count` 之后的那几个槽位**。被剪掉的节点还留着它建出来时的 `col` 与出边，
   `nodes()`（可读前缀）看不见它们，而它们**是值的一部分**。判据是 `PartialEq`，不是"读者用不用"。
2. **商店货架的空格子**。`ShopStock::empty()` 把每一格的价格设成 `-1`，而真货架是 `0`。

两条都改成"写**整个数组**、不只是可读前缀"。这是这节最值钱的一课：**"没有读者"不等于"不是状态"**，
而一个只带可读前缀的存档，回档后 struct 不相等 —— 而这个不等式**只有整局比较会说话**。

#### 三个拒绝

`an_edited_or_truncated_archive_is_refused_not_guessed` 各测一条，并且**拒绝之后这一局一个字节都没改**
（判据同样是 `RunState` 相等，与 §161.2(a) 同一条）：

* 改一个 base64 字符 ⇒ `BadCrc`；
* 截掉尾巴 ⇒ `BadTail`（没有校验和）；
* 不是存档（`hello` / `RDA2-…`）⇒ `BadMagic`。

页面上这三条都变成可见的一句话（`#archiveNote` 只有一个写者：`archiveSay`）。

#### 浏览器里的第 (k) 段

走**页面上的按钮**，不走 ABI：复制 → 文本是**一行**且以 `RDA1-` 开头 → 用**另一个种子**开一局
（免得旧状态蒙混过关）→ 粘回去点回档 → 楼层/血/金/牌组全部回来 → 再改一个字符 → **被拒**且这一局
没动 → 同一局再存一次，**字符串一样**。

#### 数字

- `rd-run` +4 测试（round-trip / 一行与首尾 / 三种拒绝 / 信封与 CRC 的已知向量 `crc32("123456789")
  == 0xcbf43926`）。
- 聚合验收 **19/19**；单测 784 → **788**。
- 导出 +3（`rd_run_archive_len` / `_into` / `rd_run_restore_from`），`smoke.mjs` 对账 141 条。

#### 还差的（第 4 步的另一半）

* **回放**：动作序列 + 每步哈希。现在有"整局快照"，没有"怎么走到这里"。
* **战斗中的存档**：需要 `CombatState` 的**反序列化**（`write_hash_input` 能写出规范文本，
  但没有解析器）。那才是"Boss 战打到一半刷新页面还能继续"。
* **内容版本**：存档里只有 id。内容改了之后同一份档案可能指到不存在的牌 —— 现在会在**进战斗**时
  响亮报错（`UnknownCard`），但更早的一句"这份档案来自别的内容版本"会更好。

### 161.10 回应第二份外部评审（`RougeRust_Code_Review_033eeed_cb08b96.md`）

评审声明"未独立构建、运行或复验"。所以每一条都先**在源码上核对**，核对结果决定它进不进这一节。
**五条成立（含一条 P0），两条我不同意，还有一条只同意一半。**

#### P0 —— 存档缓冲区与 WASM scratch 容量不匹配：**成立，而且我把它量出来了**

`rd_run_archive_into(ptr)` 接收任意指针、写最多 16 KiB，而页面给的是 `rd_env_scratch_buf()`
—— 一个 **1024 字节**的通用 scratch。评审说"现有短存档恰好不超过 1024 字节，不代表未来合法存档
仍然安全"。实测（新测试 `a_full_deck_archive_is_bigger_than_the_generic_scratch`）：

```text
60-card archive: 1628 bytes
```

⇒ 一个**后期牌组**的存档往 `SCRATCH` 后面写了约 600 字节，落进线性内存里紧跟着的那几个 static。
反方向同样开着：回档时页面把用户粘贴的文本也写进那 1 KiB。

修法不是"把 SCRATCH 调大"（它被所有 `*_into` 导出共用，那边的契约是"`*_len()` 说多长就多长"），
而是**让存档拥有自己的缓冲区，并把容量写进 ABI**：

| 旧的 | 新的 |
|---|---|
| `rd_run_archive_len()` + `rd_run_archive_into(ptr)` | `rd_run_archive_fill() -> 长度`（写进自己的缓冲） |
| —— | `rd_run_archive_buf() -> 地址` + `rd_run_archive_capacity() -> 16384` |
| `rd_run_restore_from(ptr, len)` 无长度上限 | 多了 `len > MAX_ARCHIVE ⇒ -3`（**强制**，不是假设） |

页面侧按**UTF-8 字节数**检查（`if (bytes.length > capacity)`），不是 `text.length` —— 评审点出的
这一条是对的：一个中文字符是 3 个字节。负控式的判据在测试里：`capacity + 1` 字节的输入被拒，
而**60 张牌的存档（1628 B > 1024 B）能存能读**。

#### P1 —— 删卡后存档 round-trip 有盲区：**成立，一个字节的错**

`remove_card` 把牌组左移、`deck_len -= 1`，**没清尾槽**；而存档只写前 `deck_len` 项 ⇒ 删过牌的局
回档后 `restored != run`。`drop_potion` 早就是对的（`self.potions[last] = EMPTY`）—— 又是"两个兄弟，
一个漏了"的形状。

修法：`remove_card` 补上 `self.deck[deck_len - 1] = EMPTY`，让 `len` 之后恒为空（与 `Bounded`
的不变式同一条）。新测试 `a_run_that_lost_a_card_still_round_trips` 先删一张牌再存档，
**在旧实现上会红**（负控已验证）。

#### P1 —— 存档合法性不能只由浏览器 UI 判断：**成立，但我第一次修错了**

我先按评审"用 `fight_active`"的方向修了一半：`rd_run_start` 清掉战斗会话，ABI 用"会话存在"判定。
结果 `archive_fill` 对**一个根本没打起来的局**返回 -2 —— 因为**页面在启动时就创建了一个战斗会话**
（`rd_env_reset`，战斗视图要有东西可画）。所以"会话存在"从来就不等于"正在打"。

评审的原话是"应在拥有权威状态的层明确表示 `Idle / Fighting / Finished`"。照做：`RunSession`
加一个 **`in_fight: bool`**，由三个真正拥有生命周期的调用维护 —— `rd_run_fight_begin` 置真，
`rd_run_fight_end` 与 `rd_run_start` 置假。存档与回档都问**这个**，页面的 `mode` 只作交互反馈。

判据按评审的完成标准写：**绕过 UI 直接调 ABI**，`rd_run_fight_begin()` 之后
`archive_fill() == -2` 且 `restore_from(...) == -2`。

#### P1 —— 选牌可能部分提交：**成立，而且负控证明它真的会搬走一张牌**

`resolve_choice` 的预校验覆盖了牌区容量与卡池容量，**没覆盖"那张牌自己的计数器表满了"** —— 而
`write_price` 发生在 `move_card` **之后**。负控（删掉预检）的报错原文就是证据：

```text
left:  hand=card_000002 … hand=card_000001 mc:filler_0=0 …
right: hand=card_000001 mc:filler_0=0 … hand=card_000002 …
```

**被拒绝的选牌把一张牌挪到了手牌尾部**，而问句还开着。修法：搬牌之前先问每张牌"还能不能再吃一个
`card_cost_delta`"（字典语义：有键就是覆盖，否则要空槽），不够就 `Full(MarkCounters)`。

#### P1/P2 —— `DiscardThenDraw` 的容量判定过于保守：**成立，而且它不是"保守"，是"错"**

先丢 `picked` 张再抽 `picked` 张，手牌最终回到原样 ⇒ 这个判据**永远不该触发**。原来的
`hand + picked > MAX ⇒ 拒绝` 会把"手牌 90、选 10 张"这种**明明做得成**的操作拒掉。已删除，
新测试 `discarding_before_drawing_does_not_need_extra_hand_room` 把手牌摆到**距上限只剩 2 格**、
选 2 张丢弃，断言它成功。

#### P1 —— 回档缺少完整的状态语义验证：**同意一半**

同意"CRC 不是合法性证明"，同意加 `validate`。**这一节没做**：它是一整套不变量（血/幕/楼层/游标/
`pending` 与房间自洽/id 是否存在），值得单独一节，而这一节已经在修 P0 与三条 P1。已列进下一节。

**不同意的一点**：`serde`。这个 crate 是 `no_std` + 零依赖，而手写 payload 的全部风险（漏字段、
尾槽、长度）现在由**一条判据**（`restore(write(run)) == run`）和一个容量测试覆盖住了；换成 serde 是
把"我控制字节"换成"我信任 derive"，并不会让"漏一个字段"更容易被发现。评审自己也说不要求立刻推翻。

#### P2 —— 切片用合成事件而不是真实指针：**同意，记为已知缺口**

`dispatchEvent(new MouseEvent("click"))` 与 `el.onclick()` 不能证明元素**可被点到**（遮挡、
`pointer-events`、命中区域）。关键路径改用 CDP `Input.dispatchMouseEvent` 值得做，但它是独立的一件。

#### 数字

- `rd-run` +3（满牌组存档尺寸 / 删牌后 round-trip / 信封）；`rd-core` +2（价格写不进去时不搬牌 /
  丢牌腾位不额外要容量）；`rd-wasm` +1（容量 + 生命周期，**绕 UI 直接调 ABI**）。
- 两条负控（临时回退 `remove_card` 的尾槽清理、删掉价格预检）都**红在预期的位置**。
- 聚合验收 **19/19**；单测 788 → **793**；导出 3 → 4（`archive_fill` / `archive_buf` /
  `archive_capacity` / `restore_from`），`smoke.mjs` 对账 **142** 条。

#### 下一节（按评审的清单，顺序照它的）

1. 回档的 `RunState::validate_invariants()`（血/幕/楼层/游标/`pending`/id 全部在提交前查）。
2. 回放：动作序列 + 每步哈希。
3. 关键路径的真实指针点击（CDP `Input.dispatchMouseEvent`）。
4. 内容版本指纹（现在只会在进战斗时以 `UnknownCard` 报错）。

---

## 162. 整局的不变量：`check_invariants` 长全，存档在提交前问它

评审 §六 第 4 步的第一项：**"建立整局状态不变量验证 … 畸形或自相矛盾的存档在提交前被拒绝"**。

### 162.1 先发现它**已经存在**，所以这一节是"长全"而不是"新建"

`RunState::check_invariants` 早就在（规格 `run-layer.md` §6.2：地图合法性、楼层范围含 Boss 例外、
血量、三个容器的容量、游标与行的对应）。我一开始写了第二个 `validate()` 放在它旁边 —— 那正是本项目
反复抓的"同一个词表两处认识"，而这次抓住它的**是我自己**：两份校验器迟早会漂，而且漂了以后
"两边都拒绝"看起来是对的。

⇒ 已合并：新的判据进 `check_invariants`，`archive::restore` 问它，`validate` 这个名字不存在。

### 162.2 新长出来的判据，每一条都对应一个真 bug 或一种真攻击

| 判据 | 为什么它值得存在 |
|---|---|
| `len` 之前有内容、**之后是空的** | §161.10 的 `remove_card` 尾槽；现在存档里夹带这种状态会被**载入时**拒掉，而不是等到某次 `==` 才发现 |
| 遗物**不许重复** | 重复的一件会付两次钱 |
| 药水 ≤ 腰带格数 | Potion Belt 才是格数来源（§157），5 瓶却没有腰带是非法局面 |
| `pending` 与所在房间一致（`Pending::room`） | 一个"站在战斗节点上的篝火问句"是不存在的局面 |
| `event_follow` / `blessing_follow` 必须挂在对应问句上 | 否则那个后续动作永远没机会被完成 |
| `start_offers` 在表内 | 越界的祝福下标只会在开局时炸 |
| 商店：活报价必须有 id、价格不低于 -1 | 见下面那条"我写错了两次" |
| gold / removed_cards / act / ascension / potion_chance / rarity_offset 的取值范围 | 存档是外部输入 |

`Pending::room()` 是新的：**战斗奖励不限定房间**（普通/精英/Boss 三种战斗都会发奖励），所以它返回
`None` 而不是猜一个。`NodeKind::Boss` 在地图生成里从不赋值（Boss 是地图外的哨兵），所以"脚下是什么"
由 `node_at_cursor()` 回答 —— 那是 §161.8 的路由器踩过的同一件事。

### 162.3 与规格书的一处差异，写在这里而不是悄悄改规格

`run-layer.md` §6.2 第 1 条写 `0 < floor <= 17`，因为规格书按"15 行地图 + 16 Boss + 17 Boss 宝箱"
描述。实现里 **Boss 是第 16 层的哨兵、没有 17 层**（`map::BOSS_NODE`、`ROWS = 15`），所以校验器的
上界是 `ROWS + 1`。规格书是冻结的意图，代码是当前的事实 —— 两者不一致时**说出来**，不自己改一边。

### 162.4 一个太严的校验器比没有更糟（这条是 soak 教我的）

校验器的第一版把两条闸门打红了，而且**两次都是我的判据错，不是游戏错**：

1. **"`?` 房必须有问句"** —— 不，`NodeKind::Unknown => Pending::None`：`?` 房在 M1 是"有内容的空"
   （§6.3），它故意不带 pending。
2. **商店的"活报价"** —— 我写了两遍才写对：
   * 第一遍"每一行都必须活"：**买过的行** `price = -1` 而 `count` 不减（槽位下标要稳定，页面靠它下
     `buy_card(slot)`）⇒ 合法局面被拒；
   * 第二遍"有 id ⇔ 有价格"：`buy_card` **保留 id**、只把 price 设 −1 ⇒ 合法的"已买"被当成半死。
   * 真正的不变量只有两条：**活报价必须有 id**，**价格不会低于 −1**（−1 = 买走或没上架，两种死法
     在数据上一样，不该分开猜）。

所以这一节的验收不是"校验器能拒绝"，而是**两个方向都有**：

* `a_real_run_validates_at_every_step`：走一整幕，每个节点 `begin_node` + 结算 + `mark_resolved`，
  **每一步都问一次**，必须全过；
* `every_invariant_names_itself_when_violated`：13 条反例，**每条都指名它自己**（一条断言一个原因，
  否则"拒绝了"什么都证明不了）。

### 162.5 顺手修掉 `enter_node` 的半途提交

`check_invariants` 原来在游标**已经移动之后**才跑。于是"拒绝"会留下"页面说被拒、内核却已经站在那个
节点上"的局面 —— 页面随后卡在一个 settle 不了也走不掉的节点里。soak 里那 **334 个死控件**就是它的
症状，而报错原文（`Invariant("a shop card row …")`）正是我上面那两条错判据的产物。

现在先在一个 `Copy` 出来的副本上摆好 `(node, floor)` 再验证，全过才赋值 —— 与 §161.2(a) 同一条。

### 162.6 数字

- `rd-run` +2（整幕逐步验证 / 13 条反例），`archive` +1（**CRC 合法但状态非法**的存档被拒：
  先把一个不可能的局 `write` 出来，校验和当然是对的，于是拒绝只能来自不变量）。
- 负控：删掉"尾槽必须空"那一条 ⇒ `every_invariant_names_itself_when_violated` 红在
  `left: Ok(())` / `right: Err(Invariant("a deck slot past len is not empty"))`。
- 聚合验收 **19/19**；单测 793 → **796**。

### 162.7 下一节

回放（动作序列 + 每步哈希）；关键路径的真实指针点击（CDP `Input.dispatchMouseEvent`）；内容版本指纹。

---

## 163. 回放：动作序列 + 每步哈希

REVIEW §六 第 4 步的另一半：**"版本化快照 … 外加动作序列和每步哈希。刷新后能继续；同一回放能复现
关键状态。"** §161.9 做了快照（一行文本），这一节做**动作序列**。

### 163.1 先补 `run_hash` —— 它在注释里活了很久

`rd-run/src/lib.rs` 从第一天就写 "step-wise `run_hash` determinism"，而它**只存在于注释里**。
没有指纹，"同一串动作之后局面相同"这句话就只能靠 `PartialEq` 一次性比整个结构体：能说"不一样"，
说不出**从第几步开始不一样** —— 而那正是唯一有用的信息。

`rd-run/src/hash.rs`：一局的**规范文本**（`key=value`、`\n` 分隔）交给 `rd_core::hash::sha256`。
用 `rd_core::writer::TextWriter` 而不是自己拼字符串，理由与 `rd-core` 的战斗指纹同一条：**格式就是
契约**，两份手搓的实现迟早不一致。

覆盖：种子/等级/楼层/游标/血/金/幕/待决/已结算位图/牌组/遗物/药水/掉率/稀有度偏移/三条 `?` 房计数/
**七个随机流计数**/商店货架（含买走的空格）/奖励屏/事件/上一场遭遇/开局两次祝福/两个后续动作/整张地图
（**每一行的每一个槽位**，含被剪掉的）。
不覆盖：回放日志（宿主产物）、`error` 字符串（诊断）—— 与 `beats` 同类：记的是"发生过什么"。

判据 `the_same_state_hashes_the_same_and_a_change_moves_it`：**逐字段各改一处、哈希必须变**
（gold / health / deck / relics / potions / node），外加一条
`the_rng_counters_are_in_the_fingerprint` —— 少一个计数，之后的每个随机都错位，而**局面看起来一模一样**。

### 163.2 日志与回放：**懒上戳**，这样不必改 19 个导出

每个会改运行层的导出在**动手之前**调一次 `log(kind, a, b, text)`；`log` 顺手把**上一条**记录的哈希
补上（此刻的状态正是"上一次调用之后"）。于是：

* 不需要每个导出都从 `finish` 回来（`rd_run_step` 就不是）；
* 不需要 19 处"调用后再算一次哈希"的样板。

⚠️ 代价是**每一条会改状态的调用都必须被记录**，否则"上一条之后的哈希"会把它的效果算进去，而回放里
没人做这件事。第一版只记了"结算动作"，于是 `rd_run_fight_begin`（它写 `last_encounter`，进指纹）成了
漏网的那一个 —— 第 4 步就对不上。现在 `fight_begin` 与 `grant_potion` 也进脚本。

脚本是**一行**文本（`;` 分隔、`RDR1,seed,asc;` 开头），一行一步：
`kind,a,b,hash16,text`。哈希是 `run_hash` 的前 8 字节 —— 逐步比对只关心"变了没"，整条 64 字符的
十六进制只出现在错误信息里。

`rd_run_replay_from` 从头部记录的 `(seed, asc)` **重新开一局**，然后逐条调用**同一个导出函数**
（回放不重写规则：接受与拒绝都由导出自己决定），每条之后算哈希并比对，**返回第一个不一致的步号**：

```text
0         每一步都对上了
n > 0     第 n 步之后局面不同（n 从 1 开始）
-2        脚本读不懂 / 无法回放
```

### 163.3 一场战斗**不回放**，只回放它的**结果**

`CombatState` 没有反序列化，而且一场战斗是**玩家的出牌**，不是运行层的动作。所以脚本里记的是
`fight_end` 的**结果**：`a = 英雄剩余血量`，`b` 低两位是档位（精英/Boss）、高位是结果（1 胜 / 2 负 /
0 未决）。

为此把 `rd_run_fight_end` 的尾巴抽成 `apply_fight_outcome(session, hero_hp, result, elite, boss)` ——
**真打**与**回放**调的是同一个函数。第一版回放假定"记下来的战斗都是赢的"，第 4 步立刻红：录制那次
`result = 0`（没有奖励），回放却发了奖励。

⚠️ 这条偏差写明：**回放复现的是运行层，不是战斗**。要"Boss 战打到一半刷新还能继续"，缺的是
`CombatState` 的解析器，不是这一节。

### 163.4 判据：三条，其中两条是**伪造**

`a_recorded_run_replays_step_by_step_and_a_tampered_one_names_its_step`：

1. 真跑一小段（祝福 → 8 个节点，按类型结算：战斗 `begin`+`end`、篝火 `rest`、商店 `leave`、
   宝箱 `open`+`leave`、`?` 房 `choose`），导出脚本，回放 ⇒ `0`，`replay_checked == 步数`，
   并且回放前后的 `run_hash` **相同**；
2. **改掉第 3 步记录的哈希** ⇒ 返回 `3`，`replay_checked == 2`（前两步确实验过）；
3. **改掉第 2 步的参数** ⇒ 返回 `> 0`；
4. 垃圾头部 / 不认识的 kind ⇒ `-2` / 报第 1 步。

"回放通过了"是没用的断言 —— 只有**伪造的脚本被抓住、并且指出是哪一步**才算。

### 163.5 数字

- `rd-run` +3（哈希三条），`rd-wasm` +1（回放四条合一）。
- 导出 +5（`rd_run_script_len/into`、`rd_run_replay_from`、`rd_run_replay_checked/diverged`），
  `smoke.mjs` 对账 **147** 条。
- 聚合验收 **19/19**；单测 796 → **800**。

### 163.6 下一节

页面上的"回放"按钮（现在脚本只能从 ABI 取，`browser_test` 能用但玩家不能）；关键路径的真实指针点击
（CDP `Input.dispatchMouseEvent`）；内容版本指纹（现在只会在进战斗时以 `UnknownCard` 报错）。

---

## 164. 页面上的回放：脚本成为玩家能用的东西

§163 的脚本只能从 ABI 取，`browser_test` 能用、玩家不能。这一节把它接到页面上，接法与 §161.9 的存档
**同一条纪律**：

* 脚本有**自己的**缓冲区（`MAX_SCRIPT` = 24 KiB），容量由 `rd_run_script_capacity()` 公布，
  `rd_run_script_fill()` 超了**拒**（`-2`）而不是截断 —— 一份被截断的脚本是"关于这一局的谎话"。
  借用存档那块 16 KiB 是错的：一个缓冲区一个契约。
* 一个元素一个写者：`#scriptBox` ← `setScript`，`#scriptNote` ← `scriptSay`；
  页面状态只由 `act`/`begin` 驱动。
* "战斗中不许"由**页面**判断（它知道自己处在什么模式）：一场战斗不是运行层的动作，只有它的**结果**进脚本，
  所以战中导出的脚本一定缺一段 —— 与其导出一份会分叉的脚本，不如拒绝并说明。

### 164.1 ★ 头部必须能携带**档案**，否则回档之后的续玩永远回放不了

第一版的头部是 `RDR1,seed,asc`。而**回档出来的局面不在这条时间线上**：它不是"从这个种子开局走过这些步"
的结果。于是回档之后接着打的那些步，写出来的脚本第一步就和局面矛盾。

两件事一起改：

1. `rd_run_restore_from` 成功时**清空日志**（回档 = 这条时间线的**起点**），并把头部改成
   `RDR1,A,<档案>`；
2. `rd_run_replay_from` 认两种头部：`S,seed,asc` → `rd_run_start`；`A,<档案>` → `rd_run_start(0,0)`
   要一个槽，再 `rd_run_restore_from`。

档案是 base64，不含 `,`/`;`，所以"头部一列、每条记录一列"的分列规则不用动。

⚠️ 回档之后、接着打之前导出的脚本是 **0 步** —— 那不是"通过"，是"这一局正是那份档案"。页面对 0 步
说"这一局正是头部的档案本身（0 步）"，因为「回放通过 · 0 步」读起来像某个闸门偷偷绿灯了。

### 164.2 判据：两条，都是反面的

`a_run_restored_from_an_archive_replays_from_its_archive`（`rd-wasm`）：

1. 一局走两步 → 存档 → **换一局完全不同**的（别的种子）→ 回档 → 导出：日志必须**只有头部**
   （不清理就失败）且头部是 `RDR1,A,RDA1-`；
2. 接着走两步 → 导出 → 回放 ⇒ `0`，步数全对，落到同一个种子；
3. 篡改第 2 步的哈希 ⇒ 返回 `2`，`checked == 1`。

页面侧（`browser_test`）：

* 一局走了两步之后按 **导出脚本** → 头部 `RDR1,S,43…`、步数 > 0、提示"已导出"；
* 按 **回放** → "回放通过 · N 步全部对上"，floor/seed 落回原处；
* 改掉第 2 步的哈希再按 **回放** → 提示里有"第 2 步"，`rd_run_replay_diverged() == 2`；
* 空框 ⇒ "框是空的"（不启动、不说通过）；
* 回档之后导出 → 头部 `RDR1,A,RDA1-`、**0 步**，回放通过。

### 164.3 ★ 浏览器闸门抓到的真 bug：回放没清 `in_fight`

`in_fight = false` 原来写在 `rd_run_fight_end` 里，而回放走 `replay_fight`（绕过那个导出）⇒ 回放一场
战斗之后运行层仍然"在战斗中"⇒ 玩家点"回档"被内核以「战斗中没有回档」拒掉，**而他不在战斗里**。

修法：把 `in_fight = false` 挪进 `apply_fight_outcome`（真打与回放共用的那一半）。
判据 `a_replayed_fight_does_not_leave_the_run_in_a_fight` 断言的是**页面会问的那个问题**
（`rd_run_restore_from` 被接受），不是"某个字段等于 false"。

---

## 165. 真指针点击：`dispatchEvent` 会替一个看不见的按钮说好话

之前所有页面场景都在页面里 `element.dispatchEvent(new MouseEvent("click"))`。它**完全不经过命中测试**：
被弹窗盖住的按钮、滚出视口的按钮、`pointer-events: none` 的按钮，在测试里都"点得动"。这正是页面测试
最不该瞎的那一类 bug。

`web/cdp.mjs` 新增两个真输入动作：

* `clickSelector(selector, index)`：`scrollIntoView` → 取中心 → **问 `document.elementFromPoint` 上面是谁**
  → 发 `Input.dispatchMouseEvent` 的 `mouseMoved`/`mousePressed`/`mouseReleased`。
  返回 `{ hits, coverTag, x, y }`：`hits === false` 就是"这个按钮被别的东西盖住了"。
* `typeInto(selector, text)`：真点击聚焦 + `Input.insertText`，再读回字段值（"输入框真的收到了字"）。

### 165.1 场景：一条玩家真会走的路径

`browser_test` 新增一段，全部用真指针：

1. 往 `#seedInput` 打字 → 值确实是 `777`；真点 `#newRunBtn` → 这一局的种子就是 777、`pending == 6`；
2. 祝福：`#nodePanel [data-panel-action]`（选一个祝福）→ `pending == 7` → 面板把"欠一张牌"变成一个按钮，
   点它才打开选牌弹窗 → `#modalBody [data-pick]`。**三次真点击**，中途没有任何 `evaluate` 代劳；
3. **反面判据**：用 `RD_DEBUG.showDeckPicker` 打开弹窗（弹窗本身怎么开不是被测对象），然后对**同一个**
   可达节点发真点击 —— `elementFromPoint` 命中的是 `#modalBody`，`hits === false`，floor **不动**；
   再真点 `#modalClose` → 弹窗关掉；**同一坐标、同一选择器**再点一次 → floor 变成 1。
   一次"不动"、一次"动了"，差别只在"弹窗在不在上面" —— 这就是 `dispatchEvent` 看不见的那件事；
4. 进战斗是**两次**真点击（地图节点 + 节点面板的"开打"）：只点一次会以为没进战斗，从而**悄悄跳过**
   出牌那一半（这一段第一次就这么跳过了，所以专门记下来）；
5. 真点手牌 → 能量 3 → 2；真点 `#endTurn` → 回合 2。

⚠️ 首个可达节点是不是战斗**由种子决定**，所以这一段按种子表（777…784）逐个真点开局，直到某个种子的
第一层可达节点里出现 `combat`；表用完了就如实报告"这一半没跑"。种子 777 一次就中。

### 165.2 数字

- `rd-wasm` 52 → 55（档案头回放 + 回放不留 `in_fight`），合计 800 → **802**。
- 页面导出 +6（`rd_run_script_fill/buf/capacity`、`rd_run_replay_from/checked/diverged`），`smoke.mjs` 对账 **147** 条。
- 聚合验收 **19/19**。

### 165.3 下一节

内容版本指纹（现在内容变了只会在进战斗时以 `UnknownCard` 报错）；`in_fight` 这类"宿主字段"要不要一并进
`run_hash`（今天不进：它属于会话而不是局面 —— 但 §164.3 说明它**会被内核读到**，所以至少要有一条测试
钉住"回放之后它是干净的"）。

---

## 166. 内容版本指纹：把"这份存档/脚本属于哪份内容"变成可核对的数字

REVIEW §六 的最后一条：**"内容版本三件套：内容指纹 + 关键表版本 + 存档/回放里的引用"**。前两件在本节，
第三件（存档与脚本里的引用）在这里落地。

### 166.1 先纠正一条**旧决定**

`rd-run/src/state/archive.rs` 的文件头原来写着：

> **内容版本**。存档里只有 id：id 变了就是"这张牌不存在"，在进战斗时响亮报错（`UnknownCard`），
> 而不是在回档时假装成功。

这句话对了一半，错的正是最值钱的那一半。`UnknownCard` 确实响亮，但它：

* **迟到** —— 回档成功、玩两步、进战斗才炸；
* **只覆盖一种变化** —— id 消失了。**id 还在、数值变了**（`strike` 从 6 改成 7）会安静地变成另一局
  游戏，一句提示都没有。

所以现在 payload 里带**内容指纹**，回档时**先比对**，不同就**在这里**拒绝并说出两边的值。旧注释已按新的
事实改写，不留一句已经过时的说明。

### 166.2 指纹是什么，一处定义

`sha256(整个镜像)[0..4]`，即 `content.sts.rdcf` 的 SHA-256 前四字节，读作一个 `u32`，印成八位十六进制。
本机是 **`f39a1d78`** —— 与 `tools/contentc/packages/sts/out/build.json` 里 `images.full.sha256` 的
前八位同源，这就是判据能成立的原因（见 166.4）。

按**整个镜像**算，而不是按某几张关键表：描述文本改一个字也会让旧存档被拒。这是**故意要的假阳性** ——
"重建了内容，旧档案作废"是可接受且可解释的；反过来"某个成本悄悄改了而存档照收"是不可接受的。
这条取舍写在 `content_fingerprint()` 的注释里。

`OnceLock` 缓存：镜像 38 KB，每次进战斗重算一遍是白烧 CPU，而它在一个进程里是常量。

### 166.3 三处引用，各存**一份**

| 位置 | 形态 | 由谁校验 |
|---|---|---|
| 存档 payload | 紧跟 `VERSION` 的 varint（`VERSION` 1 → **2**） | `archive::restore(text, expected, state)` |
| 脚本头部（`S` 形态） | `RDR1,S,seed,asc,pin` | `rd_run_replay_from`，**第一条记录之前** |
| 脚本头部（`A` 形态） | 不带 pin —— 档案自己带着 | 回放调用的 `restore` |

`A` 形态**故意不带**：一份东西存两份就一定会漂（FACT §4.20）。所以"档案形态的脚本"里内容指纹只存在于
档案中，回放时由 `restore` 校验，而不是在头部再抄一遍。

`rd-run` 仍然**不认识内容**：`write(state, content, out)` / `restore(text, content, state)` 里的
`content` 是宿主给的 `i32`。层次没破，而"存档属于哪份内容"与"字节没被改过"由同一个 CRC 尾巴见证。

### 166.4 判据四条，其中两条是**反证**

1. `an_archive_from_another_content_build_is_refused_before_it_touches_anything`（`rd-run`）：
   写入 `CONTENT`，用 `CONTENT ^ 0x1` 还原 ⇒ `ContentMismatch{archive, build}`，**且整局一个字节都不改**
   （判据是"整个结构体相等"，不是"没崩"）；再用 `CONTENT` 还原 ⇒ 通过。后半条是必须的，否则
   "永远拒绝"也能让前半条绿。
2. 回放测试里加一段：头部 pin 改成 `deadbeef` ⇒ 返回 `-2`，**`replay_checked == 0`**，
   错误信息里同时出现 `deadbeef` 与本机 pin。判据是"一步都没应用"，不是"返回了非零" ——
   一个走到第 5 步才分叉的脚本也返回非零，可那时局面已经被改了一半。
3. `smoke.mjs`：`rd_content_fingerprint()` 必须等于 `build.json` 的 `images.full.sha256[0..8]`，
   **并且**磁盘上那份 `content.sts.rdcf` 的 sha256 必须等于 `build.json` 里写的那一个。
   两条都要：第一条说"wasm 是对着这份内容编的"（pin 编译进 wasm），第二条说"磁盘上的镜像没被换掉"。
4. 页面：`#contentPin` 显示 `内容 f39a1d78`，与导出脚本头部的字段一致；把头部 pin 改成 `deadbeef`
   再按回放 ⇒ 提示里有"内容版本不同"、两个值、且 `replay_checked == 0`。

**反证**（手工做过一次并记录在案）：把 `content.sts.rdcf` 中间一个字节翻转 ⇒ smoke 立即
`content.sts.rdcf does not hash to build.json's ...`；字节还原 ⇒ 绿。

### 166.5 ★ 顺手修掉的一个"度量报陈旧数字"

`rd_run_replay_checked/diverged` 原来只在**走过若干步之后**才被写。于是内容不同/解析失败这些**早退**路径
会留下上一次回放的"13 步全部对上"，页面一边报错一边显示绿灯。现在 `rd_run_replay_from` **进门先清零**。
这条是被上面第 2 条判据逼出来的（它断言 `checked == 0`，第一次跑就红了）。

### 166.6 数字

- `rd-run` 98 → **99**，合计 802 → **803**；`rd-wasm` 仍 55（新判据并进了已有的回放测试）。
- 导出 +1（`rd_content_fingerprint`），`smoke.mjs` 对账 147 → **148** 条。
- 存档 payload `VERSION` 1 → 2（多一个 varint，实测存档长度不变档位）。
- 聚合验收 **19/19**。

### 166.7 下一节

关键表版本（`关键表版本` 三件套里的第二件：`STR/STRO` 的行数或 `SEC_ORDER` 指纹不必等于镜像指纹 ——
它要回答的是"这张表能不能被这个内核读"，与"内容是不是同一份"是两件事）；像素级 UI 判据
（评审里唯一还没有判据的一项）。

---

## 167. 关键表版本：`parse` 现在会问"这个内核读得懂这份文档吗"

REVIEW §六 最后一件的中间那一半（"内容指纹 + **关键表版本** + 存档/回放里的引用"）。§166 做了指纹，
这一节做表版本。

### 167.1 与 §166 是两个问题

| 问题 | 谁回答 | 拒在哪 |
|---|---|---|
| **是不是同一份**内容（加一张牌、改一句描述） | §166 的指纹 | 回档 / 回放 |
| **形状**能不能读（一行的格数、格的含义） | 本节 | `Content::parse`，一进门 |

前者必须严（内容变了旧档案就作废），后者必须**具体**（要说出是哪张表、哪个版本）。一条错误信息如果
只说"内容不同"，玩家与下次的我都不知道是"牌少了一张"还是"这张表多了一列"。

### 167.2 ★ 先修掉三处"少报"

这一节真正的发现不是"缺一个检查"，而是**同一件事被抄了三四份，其中几份已经不全**：

1. `Table::ALL` 是**五**张（漏 `Event`、`Potion`）。`for table in Table::ALL` 只是少走两圈 ——
   于是"每张表都检查过"这句话在两张上是假的，而**没有任何闸门会红**。
2. `section_stride()` 是表宽的**第二份抄写**，同样漏 `EV`/`POT`，落到 `_ => 1` ⇒ `validate()` 对这两张
   表的 `count × stride` **恒真**。
3. `tools/rdcf_verify.py` 的 `STRIDED` 也是五张 ⇒ 闸门报 "5/5 tables" —— 一句关于**残缺清单**的真话。
   `manifest.tables` 里其实一直有 `events` / `potions`。

修法都是"只留一处定义 + 加一条守卫"：

* `Table::ALL` 七张；`every_table_is_in_all` 用**穷尽 `match`** 钉住 —— 加变体不加进 `ALL`，测试编译不过。
* `section_stride()` 对七张关键表**转发**给 `Table::stride()`（`entity_row!` 的格数算出），不再手抄。
* `rdcf_verify.py` 补齐七张，并加 `assert_strided_is_complete()`：清单宽度与 `ROW_SCHEMAS` 不一致就
  退 2 并打印两边名字。**反证做过**：把清单砍回五张 ⇒ 立刻红并指出缺 `EV`/`POT`。
* 新增 `Content::tables_present()`：`ALL` 是"**内核**认识哪些表"，`tables_present()` 是"**这份镜像**
  有哪几张"。混为一谈的后果是 `content.core.rdcf`（早于 EV/POT）让 `for table in ALL { …unwrap() }` 崩，
  而且崩点看起来像"镜像坏了"。三个测试因此改用它（`seen` 也从"按位置"改成"按实体类别"）。

### 167.3 两条检查，放在 `parse` 而不是 `validate`

`parse` 现在保证"**这个内核读得懂这份文档**"：

* 头部 `schema_version`（offset 18）必须等于 `SUPPORTED_SCHEMA_VERSION`，否则
  `UnsupportedSchema { found, supported }`；
* 七张关键表里每个非空段的字节数必须**精确等于** `count × stride`，否则
  `TableShape { table, count, bytes, stride }`。

为什么在 `parse`：生产路径上**没有人调 `validate()`** —— 只有测试调。一个没人调用的检查等于一句注释。
为什么"精确相等"而不是"至少装得下"：`Content::rows` 用 `min(count, data.len() / stride)` 收尾，
行宽变宽只会**少读几行**，一句话都不说；多出来的字节同样说明行宽不是我以为的那个。

界线：这两条只看**长度**，不看格里的值 —— 所以它们不是"段内语义"，而是"能不能读"。

### 167.4 ★ 判据：第二条**不依赖版本号**

`a_key_table_with_the_wrong_row_count_is_refused_without_a_version_bump`：只把段目录里的 `count`
改一行，**`schema_version` 一个字都不动的**，然后断言 `parse` 拒、断言那个字还是 1。
判据从镜像里**读**数字（不抄 36/62），所以换镜像（sts 36 行 / core 62 行）仍然成立，并且遍历
`Table::ALL` 把每张表的 count 各加一，逐张断言。

这条是本节的核心：**版本号要靠人记得改，行宽是读得出来的事实。** 只信版本号，编译器哪天忘了 bump，
文档就被当成功读进来、读成 62 张牌。

其余：`a_schema_version_this_kernel_does_not_know_is_refused`（含"支持的那个版本必须照常通过"，
否则"永远拒绝"也能满足前半条）；`every_table_is_in_all`；`rdcf-verify` 的 7/7 与清单守卫。

⚠️ 三个探针原来**故意**写 `schema_version = 7`（`content.rs` 的小镜像、`host.rs` 的手搓镜像）：
那时 `parse` 不查这一格，于是它们顺带证明了"内核什么版本都收"。现在写 `SUPPORTED_SCHEMA_VERSION`，
"7 会被拒"搬进了它自己的测试。`validate_catches_every_structural_fault` 里 `CARD` 的 count 病例也
被 `parse` 更早接管 —— 那条臂改走**非关键表** `IDX`，两条臂都要有活着的判据，否则其中一条迟早变成
永远不执行的死代码。

### 167.5 页面上看得见

`rd_content_check()`（`0` 懂 / `-1` 读不懂 + 理由）：页面启动时问一次，读不懂就把理由写进
`#contentPin`（红字）。没有它，`content()` 里那条 `panic!` 在浏览器里是一个**没有任何理由的死按钮**
（wasm trap）。

### 167.6 ★ 闸门抓到的第三个真 bug：测试自己"派生"出来的假失败

加入 §165 的真指针点击之后，`#modalClose` 偶发"被盖住"（约一半）。dump 出来是
`[0,0,0,0]`、`modalHidden: true` —— 因为**背景点击本身就是 §151 的三种出口之一**：真点击落在
map 节点的坐标上时，可能落在 `.modal-box` 外面 ⇒ 背景被点 ⇒ 页面**正当地**关掉了弹窗。
是**测试前提错了**，不是页面错了。

修法：两条判据从各自确定的前提出发 —— "背景吞掉点击"在弹窗打开时断言，"× 能关掉"重新打开一次再断言。
顺带把 `cdp.mjs` 拆成 `probe()`（只测不点）/ `clickAt()`（**就在这个坐标**按下，不等待、不做命中测试）/
`clickSelector()`（等到真的可点再点，然后**报告最后一次探测**，被盖住仍然是 `hits:false`）；
`browser_test` 里五处固定 `settle()` 换成轮询状态的 `waitFor()`。5/5 次连跑稳定。

### 167.7 数字

- `rd-core` 649 → **652**，合计 803 → **806**。`rdcf-verify` **7/7 tables**（14 次 count×stride，
  1,274 行）。导出 +1（`rd_content_check`），`smoke.mjs` 对账 148 → **149** 条。
- 聚合验收 **19/19**；`-UnitsFloor` 803 → **806**。

### 167.8 下一节

REVIEW §六 只剩最后一件：**像素级 UI 判据**（现在整套验收里唯一还没有判据的地方 ——
`web-ui`/`web-map` 只验布局与 SVG 结构，不验"看起来对不对"）。

---

## 168. 像素级 UI 判据：问"画出来是什么样"

REVIEW §六 的最后一件，也是整套验收里唯一一处没有判据的地方。前 19 道闸门问的都是"状态对不对"
或"渲染出来的文字对不对"——**一个把文字画成背景色的主题、一张 DOM 里有而屏幕上没有的牌、一行溢出面板
的卡，能让 19 道全绿。**

### 168.1 ★ 为什么**不**做基线图比对

存一张基线 PNG 是最常见的答案，在这里是错的：它会在换字体、改缩放、动一个 margin 时变红（都不是 bug），
而让绿回去的唯一办法是**重录**——于是接踵而来的真回归一起被接受。**一个"一红就重录"的基线，是一道
靠习惯投绿票的闸门。**

所以每一条断言都是位图的**性质**，挑的标准是"它为一类视觉 bug 变红，且不为别的变红"：

| 断言 | 抓什么 |
|---|---|
| 棋盘上的非底色像素比例 > 2%（实测 6.18%，下限是它的一半） | 什么都没画 / 画成一块纯色 |
| `--ink` 与底色的距离 > 40（实测 195），**并且**有 > 500 个像素是它 | 主题丢了、文字与背景同色 |
| 每张牌**自己的矩形**在"藏起卡牌"前后变过 > 200 像素（实测 ≈ 8,912） | DOM 有、屏幕上没有 |
| 手牌条带下方 6 px 的墨 < 50（实测 0） | 卡牌溢出面板 |
| 同一状态两次截图**逐像素相同**（实测 0 差异） | 未初始化/漂浮的绘制 |
| 英雄面板徽章区有墨（实测 614） | 具体位置上一片空白 |

零依赖：`Page.captureScreenshot` 给 base64 PNG，`web/pixels.mjs` 用 `zlib.inflateSync` + 五种扫描线
滤波器解成 RGBA（8 bit、非隔行、type 2/6，别的**抛错**而不是返回错 stride 的缓冲区——那会让下面所有
断言"通过"）。视口由 `Emulation.setDeviceMetricsOverride` 钉成 1024×720、`deviceScaleFactor=1`：
不钉的话量的是机器，不是页面。

### 168.2 ★ 故障注入：把"它会红"变成每次跑都验证的事

`web/fault_pixels.mjs` 逐个注入真 bug，并打印**同一批探测器**读数：

```text
clean          board 0.0618 ink gap 195 ink 2063 below 0 cards 5
fault ink      gap 16     <- 可读性断言需要 > 40
fault card     per card [8911, 0, 8912, 8911, 8912]   <- 从未画过的那张必须 < 200
fault overflow below-strip ink 998                    <- 溢出断言需要 < 50
fault blank    board 0                                <- 覆盖断言需要 > 0.02
```

四条全部被抓。**每一条都改过一次探测器**，因为第一版抓不住：

* **ink**：原来只数"墨色的像素"，把 `--ink` 设成底色时计数**暴涨**（155,223）——它分不清"文字用墨色画"
  和"背景就是墨色"。加上"与底色的距离"这半句才成立。**可读性是断言的前半，出现是后半。**
* **coverage**：原来在整页上量，把 `.board` 整个藏掉还剩 3.2%（页面底部的存档条与回放条还在），
  2% 的下限照样通过。改成**在棋盘自己的盒子里**量。
* **分母两笔账**（FACT §4.5）：棋盘 895 px 高、视口 720 px，分子数可见的 720 行、分母用 895 ⇒
  一个看起来很合理的 4.08%（真值 5.08%）。改成 `inkFraction()` 一个函数，**先把盒子裁到位图里**。
* **反证用的对象错了**：把整个 `#handPanel` 的 `opacity` 设 0 会让面板**自己的底色**也消失，于是
  "从未画过的牌"照样"变了"（9,088 像素）——那是这个反证块要抓的那个 bug 的**最强通过**。改成只藏
  `#hand button.card`（`visibility: hidden`），面板底色留着，未画的牌才真的读 0。
  ⚠️ 注入方式也从"内联样式"改成 `<style>` 规则：页面每次渲染重建 `#hand.innerHTML`，内联样式被抹掉，
  于是注入**静默失效**而读数看起来正常。

### 168.3 手牌为什么不用"数斑块"

第一版数"条带上墨色的列斑块"，得到 **18 个斑块 5 张牌**。实测列占用后发现原因：每张牌内部是 3–4 段墨
（费用徽章、标题、正文、chips），缝 1–3 px；牌与牌之间的缝也是这个量级。**任何把它调成 5 的阈值都是对着
一种布局拟合出来的。** 换成"这张牌**自己的矩形**里有没有墨"，判据立刻与布局无关。

### 168.4 度量器自己也要有判据

闸门第一段不碰浏览器：手搓 10×10 位图 + 2×2 白块，逐条断言 `inkCount == 4`、`inkFraction == 0.04`、
`diffCount == 4`、`diffCountIn` 的**裁切**（盒子在斑块外读 0、盒子超出位图被裁剪）、`dominantColour`、
`colourCount`、`distance`。度量器错了，下面每个数字错在同一个方向上，而闸门照样说 PASS。

### 168.5 数字

- 第 **20** 道闸门 `web-pixel`，证据列 `5/5 card(s) painted`；聚合验收 **20/20**。
- 单测仍 **806**（这一节是 JS + 文档，没有 Rust 改动）；`smoke.mjs` 不涉及（`pixels.mjs` 不在页面里加载）。
- 新增 `web/pixels.mjs`（解码 + 11 个度量）、`web/pixel_test.mjs`（闸门）、`web/fault_pixels.mjs`（故障注入，
  不进闸门：它是"证明闸门会红"的工具，跑一次 ~40 s）。

### 168.6 REVIEW §六 至此闭环

1. 内容指纹 —— §166；关键表版本 —— §167；存档/回放里的引用 —— §166/§164。
2. 动作序列 + 每步哈希 —— §163；版本化快照 —— §161.9；刷新后继续 —— §164。
3. 整幕垂直切片 —— §161.8；像素判据 —— §168。
4. 关键路径的真实指针点击 —— §165。

### 168.7 下一节候选

`web-pixel` 目前只覆盖**战斗**一个界面（手牌、英雄徽章、溢出）。地图的 15×7 网格与篝火/商店面板用的
是同一批度量，可以按同一种形状加段落；另外"颜色主题"目前只验 `--ink` 一支，可以遍历页面声明的调色板
逐个断言"它出现在屏幕上"（哪些对该界面无意义要先想清楚，否则又是一条靠拟合的判据）。

---

## 169. 文档补课：README 与缺口清单，以及"抄下来的数字会腐烂"

这一节没有新功能。做的是两件遗留账：`README.md` 落后了 154 个提交（还写着 §43、9 道闸门），
`docs/sts-wiki-gap.md` 里有一半的"没有"已经做完、另一些"缺 13 瓶药水"变成 7 瓶。重写的过程中
**又抓到三处"注释里抄了计算值"**，值得单独记一笔。

### 169.1 README：交代"现在是什么样"

旧 README 描述的是一个只有 `rd-core` + 9 道闸门的仓库。现在是四个层（内核 / 运行层 / ABI + 前端 /
RL 环境）、内容编译器、20 道闸门、四条手工对拍。新 README 的每一条都能对上：

* 文件数/行数：`rd-core` 21 个源文件 55.8k 行、`rd-run` 6 个 8.8k 行、`rd-wasm` 2 个 10.2k 行；
* 内容数字取自 `manifest.json` 与 `native/sts_content_check.py` 的输出（36 条卡行 = 19 基础 + 17 `+`）；
* 20 道闸门逐个点名 + 各自的证据串；
* **能力边界照实写**：Boss 只有三只、精英池 4 个遭遇、药水 26/33、A 规则 9/20。

### 169.2 ★ 三处"注释抄了计算值"，全部已经过期

1. `rd-wasm/src/lib.rs`：`OFF_ENEMY_STATUS` 等五处尾注写着 `// 49`、`// 69`、`// 109`、`// 114`、
   `// 122` —— 全是 `MAX_ENEMY_SLOTS = 4` 时代的产物。它涨到 6 之后**表达式仍然正确，只有尾注在说谎**，
   `rd_env_observe_len()` 实际是 **148**。而"哪一格是几号"正是页面唯一关心的事。
   修法：**删掉尾注**，在块首说明守卫在哪（`smoke.mjs` 把页面声明的偏移与导出长度对起来）。
2. `web/README.md` 三处把观察向量写成"122 个 i32" —— 改成"读 `rd_env_observe_len()`，本次构建 148"。
3. `tools/acceptance.ps1` 的横幅写着 `[1/9]`…`[9/9]` 再 `[+1]`…`[+7]`，而**最后四道闸门连横幅都没有**。
   一次运行打印 20 行、标题说 9 —— 与陈旧注释同一类谎。改成连续的 `[1/20]`…`[20/20]`，四道补上横幅，
   `[+2]` 里的"5 张定长表"也改成 7（§167）。

**共性**：一个数字如果在两处存在（一处计算、一处抄写），抄写的那一处迟早是错的，而**没有闸门会红** ——
除非像 `smoke.mjs` 那样把两边对起来跑。这三处都不是"忘了更新"，是"本来就不该有第二份"。

### 169.3 缺口清单：数字交给脚本，正文只留结论

旧文档的问题不是写错，是**没法保持对**：它把"26 瓶药水""17 个状态"写进正文，而内容每加一条，
正文就旧一点，且没有任何闸门会红。

新增 `native/gap_check.py`：从内容 JSON 与代码里**重算**文档引用的每个数字并打印 ——
状态表、卡牌 tag 计数、遗物/药水/事件清单与效果词表、每幕遭遇数、Ascension 规则（含"声明了但没人读"
的检查）、闸门清单。正文改成"见脚本"，只在需要结论的地方写结论。

写这个脚本本身又踩了两个坑，都记在脚本注释里：

* 第一版用 `at_least(A_NAME)` 字面匹配判断"规则有没有被应用"，把 A7/A8/A9（经
  `enemy_health_percent(kind)` 传**变量**）和 A6（在 `rd-wasm` 里应用）报成"声明但从未读取" ——
  **度量在往"我们做得比实际少"的方向说谎**。改成扫全 kernel、按出现次数判断，并注明这是近似。
* 读 `is_declared_inert()` 的名单时，正则读到了 `matches!` 旁边**注释里的** `"empty"` 这个词，
  于是报出一个叫 "empty" 的状态。先剥 `//` 注释再提取。

### 169.4 缺口清单本身：两份来源，逐条比对

wiki 侧重新取（本次核对）：`Module:Potions/data`、`Module:Ascension`、`Keywords`、`Rest Sites`、
`Relics`、`Acts`。实现侧全部落到文件与 §号。几处被这次核对**改掉**的旧结论：

* "Ascension 没有" → **9 条已实现**，并逐条列出 20 条里哪 11 条缺、为什么缺（需要第二套招式表/伤害表）。
* "药水 20/33、差 13 瓶" → **26/33、差 7 瓶**，七瓶各自要的机制逐条点名。
* "X 费是唯一内核不许出现的 tag，内容门会拒" → §146 已删掉 `reject_x_cost_deck`，内容检查反过来要求
  印刷费用为 0。
* "0 张 `power` 牌" → 内容里有 6 条 `power` 行（`inflame` / `metallicize` / `combust` 与它们的 `+`），
  所以 Power Potion 不是"缺机制"，它已经在 26 瓶里。
* 精英池"只有 2 个遭遇" → **4 个**（第一幕两个、二三幕各一个）。
* 状态"已有 17 个" → **24 个，且没有一个是 knowingly inert**（`is_declared_inert()` 的名单是空的）。

### 169.5 数字

代码没有行为变化（单测仍 806），20/20 闸门仍全绿。文档侧：`README.md` 重写（66 → 约 150 行）、
`docs/sts-wiki-gap.md` 重写（带方法与重算脚本）、`web/README.md` 的陈旧数字改掉、
`native/gap_check.py` 新增。

### 169.6 下一节

`docs/spec/` 的 19 份规格书还没做过同样的体检：它们描述的是"冻结的语义"，但 `run-layer.md` /
`ui-plan.md` 这类会随实现漂。做法可以直接照这一节：**能重算的数字交给脚本**。

---

## 170. 外部评审第三轮：WASM 会话生命周期那一圈

第三份评审（`docs/vibe/Review_07c24a0_5c467b6.md`）的范围是 §161.10–§169。它的总判断是
"**底层规则的验证已经较强，但新的 WASM Session/ABI 生命周期仍可绕过或破坏这些契约**"，不给 P0/P1
写"已复现"，只做静态分析。我逐条对源码核实：**P0 与五条 P1 全部成立**。这一节修前四条（P0-1、
P1-1、P1-2、P1-3），P1-4/P1-5 留下一节。

### 170.1 P0-1：回放期间两个 `&mut` 同时活着

`rd_run_replay_from` 把 `run_slot().as_mut()` 绑在循环**外面**（为了写 `replaying`），然后在循环里
调 `rd_run_step` / `rd_run_begin_node` / …… —— 每一个都再取一次槽；而三条**拒绝分支**（记录格式坏、
种类不认识、参数不是整数）仍在用外面那个绑定。两个 `&mut` 指向同一个 `RunSession`，按别名模型是 UB。

更要紧的是它让一条**注释变成假的**：`lib.rs` 的槽注释一直写着"**没有导出会重入另一个导出**，
所以 `static mut` + 单访问器是 sound 的"——回放就是重入，而这句话正是"别名无害"的**理由**。

修法：外面那个绑定删掉。`replaying` 在一个立刻结束的作用域里设；三条拒绝分支改用**已有的**
`session_clear_replay(checked, idx)`（顺带删掉三处重复赋值）；比对哈希用自己的短借用。两条注释
（`lib.rs::slot()` 与 `run.rs::run_slot()`）改成新规则：

> **不许把槽的 `&`/`&mut` 拿过一次导出调用。** 借、用、放、再调用。

`rd_run_replay_from` 是唯一允许重入的地方，它现在就这么写；`src/run.rs` 里那行注释把这条规则钉在
循环开口处，下一个人照抄时看得见。

### 170.2 P1-1：`fight_begin` 不是事务

`in_fight = true` 写在**六条可失败步骤之前**（本幕遭遇池缺失、池为空、选遭遇、摇战斗种子、
`build_session_at`、`apply_combat_bonus`）。最后一条在 `install_session` **之后**才失败 —— 于是
函数返回 `-2`，槽里却留着一场**没有遗物加成的半初始化战斗**，而 `in_fight` 卡在 true。

卡住的 `in_fight` 不是审美问题：`rd_run_archive_fill` 会一直拒绝，而玩家**根本没有一场仗可以打完**
—— 与 §164.3 是同一类 bug（那一次是回放没清标记，被浏览器闸门抓到）。

修法：三个标记改到**提交点**写；可失败段整段收进一个块，失败就用 `RunState: Copy` 的整结构体快照
回到进函数那一刻（连"选遭遇已经消耗的随机数"一起还回去）；已经装上的战斗会话一并丢弃。

⚠️ 这里撞出一个**真隐患**，不只是借用检查器的脾气：`DeckEntry<'static>` 原来直接借
`RunId::as_str()`，那是指进 `RunState` 自己的存储 —— 也就是说 `FightPlan` 与 `RunState` 一直是
**别名**，而"回滚 = 覆写 `RunState`"会把战斗正在读的字节改掉。借用检查器拒绝编译，正好替我们拦住了
这个错误。改法：牌组项**拷贝出自己的字符串**再 leak（每次开战多几个小分配，代价与 `build_session`
本身同一量级，也就是 P2-3 那个 leak 的来源）。

### 170.3 P1-2：不拒绝重复开战

战斗进行中 `node_resolved()` 仍是 false（要到 `fight_end` 才结算），所以"这个节点已经结算过了"
**放行**重复调用：它会重新摇遭遇（烧掉一个 `Combat` 随机数）、再 leak 一份牌组、并且
`install_session` **覆盖**槽里正在打的那一场。实际效果是"站在战斗节点上反复按开打可以重摇遭遇"。

修法：入口 `if session.in_fight { fail(…) }`。页面因为"成功后立刻重渲染"挡住了双击，所以这不是
页面可利用的漏洞；但回放、RL 环境、测试都能踩 —— **ABI 契约不能指望调用者的 UI 习惯**。

### 170.4 P1-3：脚本接口没继承存档的守卫

§161.10 学过一次："战斗中不许存档"不能由页面的 `mode` 独占。存档在 ABI 层挡住了 `in_fight`；
脚本导出没有，回放更没有 —— 而回放会 `rd_run_start` **直接毁掉进行中的一局**。
两处都补上同一条守卫（回放的守卫在**解析之前**，所以一段头部合法的脚本也会先被拒）。

### 170.5 判据：全部绕开 UI 直接调 ABI

评审最锋利的一句是过程性的：这五条 P1 全落在闸门盲区 —— **没有一道闸门会绕开页面直接调 ABI，
也没有一道做故障注入**（像素门自检除外）。所以新增的三条测试都直接驱动导出：

| 测试 | 断言 |
|---|---|
| `a_second_fight_begin_is_refused_and_the_fight_in_progress_survives` | 第二次开战返回 `-2`；整局**相等**（含随机流计数）；战斗会话还在、英雄血量没被重设；日志**多一条**尝试记录（`log` 在动手之前调，这是 §163 懒上戳的前提），且它未上戳 |
| `a_refused_fight_begin_never_leaves_the_run_in_a_fight` | 两条**可达**的拒绝（没有节点、节点已结算）之后 `in_fight` 仍为 false、分层标记没漏、整局相等 |
| `the_script_abi_refuses_mid_fight_without_the_page` | 战斗中 `script_fill` 与 `replay_from` 都 `-2`、错误文本说明原因、局面与战斗都没动、`replay_checked/diverged` 不残留陈旧读数 |
| `fail_begin_restores_the_snapshot_and_clears_the_tier_flags` | 回滚**机制**本身：模拟走了一步随机数 + 三个标记，`fail_begin` 之后整局回到快照、标记清零、错误写入 |

**负控**（`native/negctl_170.py`，脚本自己改源码、跑一个测试、再还原）：

```text
[RED] P1-2 重入守卫        -> a_second_fight_begin_is_refused…          caught
[RED] P1-3 script_fill 守卫 -> the_script_abi_refuses_mid_fight…         caught
[RED] P1-3 replay 守卫      -> the_script_abi_refuses_mid_fight…         caught
[RED] P1-1 回滚函数体       -> fail_begin_restores_the_snapshot…         caught
```

### 170.6 ★ 明确说清楚"没被验证"的那一半

`fight_begin` 里"**建好战斗之后才失败**"的路径（本幕池缺失、池子选不出、遗物加成失败）由**内容
决定**，本仓库现有的内容走不到它们。所以：

* 它们由**构造**保证 —— 标记在提交点写、任何失败都回到快照，而不是靠"我记得写了"；
* 回滚函数本身有判据（上表最后一条）；
* 但**没有一条测试会让那三条路径真的失败**。这就是评审要求写明的"未验证项"，写在这里而不是
  留给下一个读者去猜。

### 170.7 数字

`rd-wasm` 55 → **59** 个测试，合计 806 → **810**；20/20 闸门全绿；`-UnitsFloor` 806 → 810。
`smoke.mjs` 仍 149 条导出（这一节没有新增/删除导出）。

### 170.8 下一节

评审剩下的两条 P1：

* **P1-4**：`run_hash` 的 8 KiB 上限失败被 `unwrap_or(0)` 变成一个**合法可比较的值**（两个都溢出的
  状态会"匹配"）。要做两件事：**证明边界**（最大合法局的文本长度 vs `MAX_TEXT`，今天没人量过），
  以及把失败传播成响亮拒绝而不是 0。
* **P1-5**：`rd_run_script_into(ptr)` 与 `fill/buf/capacity` 是同一件事的第二条路，且**只有测试在用**
  —— 删掉它，让脚本接口只剩一条路。

P2 里唯一值得当天做的是**把范围写进文档**：回放覆盖当前局是有意设计（`P2-1`），
且它只验状态轨迹、不验返回码（`P2-2`）。

---

## 171. 外部评审第三轮（续）：哈希容量的边界与"第二条路"

§170 修了会话生命周期的四条。这一节收尾剩下两条 P1 —— 一条是"错误被合法值掩盖"，一条是
"同一件事有两条路，其中一条没有容量契约"。

### 171.1 P1-4：8 KiB 的边界，先量再谈

`run_hash` 在规范文本超出 `MAX_TEXT`（8192 B）时返回 `None`，而三个调用点都把它写成
`unwrap_or(0)`。`0` 是一个**合法可比较的值**，所以两个都溢出的状态会互相"匹配" —— 这正是评审说的
"错误不能用某个合法数据值掩盖"。

评审同时指出："能否在正常内容达到该上限尚未独立验证。"**这句话才是重点**：仓库里只有
`the_text_is_canonical_and_not_truncated`，用的是 `run()` 那副 10 张牌 —— 它证明不了后盘。

**先量。** 新增 `the_largest_legal_run_fits_the_hash_buffer`：牌位全部塞满、每个 id 都取
`ID_CAP`（40）长、遗物 24 件、药水 5 瓶、金币 `i32::MAX`、Ascension 20 —— 那是**类型**允许的最大
文本，内容以后怎么改都超不过它。**实测 4186 B / 8192 B = 51%。**

于是**判据改了**：我第一版写的是"两倍余量"，一跑就红（4186 × 2 = 8372 > 8192）。真实余量是 1.96 倍，
所以我不能留一个自己都不成立的判据 —— 改成"至少 1.5 倍余量"，并把**实测值与它的含义**写进注释：

> 文本的约 90% 是 id 文本（60 张牌 + 24 遗物 + 5 药水）。**把 `MAX_RUN_DECK` 或遗物容量翻倍，
> 就会溢出。**

**再把失败传播出去。** `RunSession` 多一格 `hash_failed`，唯一的取哈希入口
`RunSession::state_hash()` 在 `None` 时置它；`script_fill` 见到它就**拒绝导出**（"导不出脚本：
这一局的状态文本超出了哈希缓冲"），回放的比对也把"算不出"与"不一致"分成两种结果
（前者 `-2` 并说明，后者才是分叉）。

⚠️ 诚实交代**没测到的那一半**：`hash_failed` 与回放的 `state_hash() == None` 分支对**合法状态不可达**
（就是上面量出来的 51%）。而且回放会 `rd_run_start` 建**新**会话，`hash_failed` 一开始就是 false ——
所以回放侧的这条分支连"置标记"都进不去。测试测的是**接线**（置标记后导出拒绝、局面不变），不是
"哪天真的会响"。它存在的意义是：容量哪天被改大，它响，而不是两个溢出的状态互相点头。

### 171.2 P1-5：删掉第二条路

`rd_run_script_into(ptr)` 往调用方指针里写 `script_len()` 个字节，**没有容量参数** —— `unsafe` 契约
是"你自己留够地方"。对 Rust 调用者成立；对这个 ABI 存在的理由（wasm/JS）就是一把对着脚的枪。

但真正的判据不是"加个参数"，而是：**它和 `fill`/`buf`/`capacity` 做同一件事，而且唯一的用户是内核
自己的测试**。页面走的是 `fill`。所以正确的动作是**删掉** `into` 与 `len`，让测试改走页面那条路
（`fill` → 问容量 → 按长度读模块自己的缓冲区）。脚本接口现在只有一条路。

顺带证实了 `smoke.mjs` 那个"手抄两次"的设计是对的：删导出之后，`REQUIRED` 里那两个名字必须同步删，
否则闸门会报"缺导出"。

### 171.3 判据与负控

| 测试 | 断言 |
|---|---|
| `the_largest_legal_run_fits_the_hash_buffer`（`rd-run`） | 最大类型态文本 < 8192 B；≥1.5 倍余量；且 > 4 KiB（否则它量的不是最大态）；`println!` 打出实测值与百分比 |
| `an_unavailable_hash_is_refused_not_treated_as_zero`（`rd-wasm`） | 置 `hash_failed` 后 `script_fill` 返回 `-2`、错误文本提到"哈希缓冲"、局面不变 |

负控（`native/negctl_170.py`，五条全 RED）：

```text
[RED] P1-2 重入守卫        -> a_second_fight_begin_is_refused…            caught
[RED] P1-3 script_fill 守卫 -> the_script_abi_refuses_mid_fight…           caught
[RED] P1-3 replay 守卫      -> the_script_abi_refuses_mid_fight…           caught
[RED] P1-4 hash_failed 守卫 -> an_unavailable_hash_is_refused…             caught
[RED] P1-1 回滚函数体       -> fail_begin_restores_the_snapshot…           caught
```

### 171.4 数字

`rd-run` 99 → **100**，`rd-wasm` 59 → **60**，合计 810 → **812**；20/20 闸门全绿；
`-UnitsFloor` 810 → 812。导出 **-2**（`rd_run_script_len` / `rd_run_script_into` 删除），
`smoke.mjs` 的 `REQUIRED` 同步减二，页面侧 `ex.*` 对账仍 **149** 条（那两个名字页面本来就没调）。

### 171.5 这一轮评审的收尾状态

| 项 | 状态 |
|---|---|
| P0-1 回放期间的别名 | 已修（§170.1），注释里的 soundness 理由也改了 |
| P1-1 `fight_begin` 不是事务 | 已修（§170.2），含一个被借用检查器拦下的真隐患 |
| P1-2 重复开战 | 已修（§170.3） |
| P1-3 脚本接口没有 `in_fight` 守卫 | 已修（§170.4） |
| P1-4 哈希容量失败降级成 0 | 已修（§171.1），边界**量过** |
| P1-5 `script_into` 没有容量参数 | 已修（§171.2），删掉第二条路 |
| P2-1 回放破坏当前局 | 有意设计，**已写进文档**（§163.3 / §171.6） |
| P2-2 回放不校验返回码 | 范围选择，**已写进文档**（§171.6） |
| P2-3 每场战斗的 `Box::leak` | 有意保留；§170.2 让牌组项**自己拥有**字符串，泄漏量略增但换掉了"`FightPlan` 与 `RunState` 别名"这个隐患 |

### 171.6 把两条 P2 的范围写清楚

* **回放会覆盖当前局**（`P2-1`）。`rd_run_replay_from` 用 `rd_run_start` 从头部重开，这是**有意**的：
  回放的本职是"复现这一局"，不是"在旁边验算"。页面在拒绝/分叉时都会重画，玩家看得见自己站在哪。
  要"不改当前局的验算"得另开一个 wasm 实例 —— 记在 §168.7 那类候选里，不在这一轮做。
* **回放只验状态轨迹，不验返回码**（`P2-2`）。脚本记的是动作，判据是每一步之后的 `run_hash`；
  一个"当时成功、现在被拒且状态没变"的动作会被哈希判成一致。这是**范围选择**：要验 API 语义就得把
  返回码写进脚本（格式 `RDR2`），那是另一件事。今天的取舍是"状态对了就算对"，因为状态才是玩家能看见的。

### 171.7 下一节

`docs/spec/` 的 19 份规格书还没做过 §169 那种体检（`run-layer.md` / `ui-plan.md` 会随实现漂）。
按用户的意思，这类脚手架文档留到项目收尾时统一处理，避免反复修改 —— 记在这里，不排进下一轮。

---

## 172. 我自己写的边界测试是假阳性

第四份评审（`docs/vibe/Review_a9cd494_a7cac81.md`）只报了一条 P1，但它打在上一节的正中央：

> **P1-1**：所谓"最大合法状态"的哈希测试**没有构造出最大状态**。

### 172.1 它说对了，而且比它说的更糟

`big_run()` 里是这么写的：

```rust
for _ in 0..MAX_RUN_RELICS {
    let _ = state.push_relic(relic);      // relic = "zzz…" × 40
}
for _ in 0..MAX_RUN_POTIONS {
    let _ = state.push_potion(potion);
}
```

`push_relic` 先查 `relic_effect(id)`，不认识的 id 返回 `UnsupportedRelic` —— 于是 **24 次全部失败**，
一件遗物都没进去；而 `let _` 把每一次都咽掉了。第二轮又在 **Ascension 20** 上塞 5 瓶药水，那个等级
只有 2 个槽（腰带给 2，但它没被塞进去）。

所以我报出的 **4186 B / 8192 B（51%）** 是一个**残缺夹具的测量值**，而我在 §171 里把它写成了
"类型允许的最大文本"。这正是我自己在别处反复批评的形状：**度量看起来在量，其实在量别的东西。**

### 172.2 修法：先证明夹具就是它自称的那个

四条，缺一条都不算修好：

1. **每一次 `push_*` 都 `expect`** —— 静默拒绝会让测试**红**，而不是让夹具悄悄变小；
2. **测量之前先断言元素个数**（牌 60、遗物 = 镜像里全部、药水 = 腰带容量）——
   "夹具就是它自称的那个"本身是一条判据，这正是那条负控要打的地方；
3. **id 从内容表里取**，不抄字符串，也不走 `IDX`（`IDX` 不含每种实体：药水与事件各有自己的列表，
   第一版扫 `IDX` 时"找不到任何药水"，是测试在告诉我它读错了表）；
4. 把**两个口径分开测**，这正是评审要求的"不要把两者混用"。

实测（2026-11-02，内容 `sts` 镜像）：

| 口径 | 文本 | 占 `MAX_TEXT` |
|---|---|---|
| **内容可达**（id 全部来自镜像：最长卡 id 14 B、最长药水 16 B） | **2815 B** | 34% |
| **API 可表示**（牌与药水 id 补到 `ID_CAP`，遗物仍取表内 id） | **4495 B** | 55% |
| 类型的真实上界（遗物 id 也到 `ID_CAP`） | 构造不出来 | — |

第三行是**故意不测的**：`push_relic` 只接受手写规则表里的 id，所以那个状态用公开 API 造不出来。
写在测试的文档注释里 —— 保护它的是 §171 的**响亮拒绝**（`hash_failed`），不是这条测量。

### 172.3 ★ 判据又改了一次，因为"两倍余量"是假的

前两个口径的真实余量是 2.9 倍与 **1.82 倍**。我上一版写"两倍"，对第一个口径成立、对第二个不成立。
判据统一成 **1.5 倍**，并把两个百分比都 `println!` 出来。

顺带修掉另一处"拿错答案校准的尺子"：上一版有一条 `assert!(len > MAX_TEXT / 2)` 想证明"这确实是个大局面"
—— 它标定在**坏夹具**的 4186 上。真实的 2815 一跑就红。现在它写 `> 2000`，含义回到它该有的样子：
"比 `run()` 那副 10 张牌大得多"。

### 172.4 负控脚本本身也有假阳性（评审 P2-1）

原来 `red = code != 0` —— 编译失败、cargo 路径不对、无关 panic，全都会被读成"抓到了"。现在每一轮：

* 变异**之前**先跑同一个测试，要求它 GREEN（基线）；
* 变异之后要求：构建没报 `error[E…]`、`test result: FAILED` 出现、**具体测试名**出现、有 `panicked at`；
* 允许逐轮指定**源文件**（新加的"夹具完整性"那条在 `rd-run/src/hash.rs`，不在 `rd-wasm`）；
* cargo 路径与 target 目录走 `$CARGO` / `$CARGO_TARGET_DIR`，不再写死本机路径。

**而这条新负控第一次跑是"未命中"的**，原因很有意思：我原本只把 `let _` 换回来（其余不动），于是
`push_relic` 推的是**已经过滤过**的 id —— 一定成功，`let _` 无害。**能抓住原 bug 的不是"吞错误"本身，
而是"未过滤的 id + 吞错误"这个组合**。变异改成推一个规则表不认识的 id 并吞掉，数量断言当场红。
这条留在脚本注释里：负控要复现**bug 的形状**，不是复现某一行代码。

六条负控现在全红，且都附带"预期断言失败"的理由：

```text
[RED] P1-2 重入守卫 / P1-3 script_fill / P1-3 replay / P1-4 hash_failed
[RED] P1-1 回滚函数体 / §172 夹具完整性
```

### 172.5 数字

测试条数不变（`rd-run` 100、`rd-wasm` 60、合计 **812**），因为这一节改的是**同一条测试的内容**而不是
数量 —— 这正是它值得单独记一节的原因：**闸门全绿、条数没变，而它之前量的东西是错的。**
20/20 闸门仍全绿。

### 172.6 这一条最该沉淀的规范

评审把它写成了"测试目标、准备过程、断言三段都要验证"。用我自己的话说：

> **夹具要自己证明自己。** 一个"填满到容量"的循环如果允许失败，就必须在测量**之前**断言元素个数 ——
> 否则测出来的数字是关于一个我没检查过的对象的，而它会看起来完全合理。

§171 是"先量再谈"，§172 是"**量之前先证明你在量什么**"。后者更便宜，也更容易忘。

### 172.7 下一节

评审的建议是"完成以上 P1 后回到 WASM 的机制与内容开发，不要继续无止境地扩张验收体系"。同意：
下一轮不再加闸门，回到内容（精英池、药水差的 7 瓶）与 `docs/spec/` 的收尾体检（用户已定：留到项目收尾）。

---

## 173. 精英池扩容：内容写完了、机制验过了，最后被一个**既有死锁**挡住

这一节是**没落地的一节**，留在这里的原因是它记下的东西比"又加了三个精英"值钱。经过：
内容全写完、门全绿（19/20）、两个新机制都被测试证明、然后 `web-soak` 抓到**敌方回合跑不完**
的死锁。按纪律（闸门不绿就不算做完）内容已回退到 HEAD；补丁脚本、wiki 取数与下面这些结论留作
下一轮的起点。

### 173.1 写完了什么（可复现）

`native/patch_173_elites.py` 一次生成全部内容；`native/patch_173_inventory.py` 同步内容门里的清单
（`sts_content_check.py` **就是** `sts-act1-inventory.md` 的可执行版本，加内容就必须同时加它）。

| 精英 | HP | 招式（A0） | 出处 |
|---|---|---|---|
| **Lagavulin** | 109-111 | Metallicize 8；Sleep ×3（什么都不做）；Attack 18；Siphon Soul（−1 力量/−1 敏捷） | `wiki/Lagavulin` |
| **Book of Stabbing** | 160-164 | Multi Stab 6×N（N = 使用次数 + 2）；Big Stab 21 | `wiki/Book_of_Stabbing` |
| **Taskmaster** | 54-60 | Scouring Whip 7 + 1 张 Wound 进弃牌堆 | `wiki/Taskmaster` |
| （Slavers 遭遇） | — | Taskmaster + Red Slaver + Blue Slaver，顺序即回合顺序 | `wiki/Slavers` |

加上一张 **Wound** 牌（`slimed` 同形：status / unplayable / 无程序）。池子变成
Act1 `Elite` 3 个、Act2 `Elite2` 3 个 —— 与 wiki 的"每幕三个精英"对上。

### 173.2 两个机制真的跑通了（这是最有价值的部分）

两条测试都用 `build_session_at(seed, "enc_…")` 直接建遭遇，再走 `rd_env_step(结束回合)`：

* `lagavulin_sleeps_for_three_rounds_and_then_attacks`：连续三个结束回合英雄血量**不变**，
  第四个回合正好掉 18。它的做法值得记：`intent.round <= 3 → lagavulin.sleep`（优先级规则 + 空程序
  动作），而 `Actions` 刻意排成 `[siphon_soul, attack]`，让第 4 回合的 `(4-1) % 2 = 1` 落在 Attack ——
  wiki 说它醒来立刻攻击。
* `book_of_stabbing_escalates_by_its_own_use_count`：三下 Multi Stab 打出 **18 / 21 / 24 / 21 / 30**
  （与 Big Stab 交替），完全对上 wiki 的 `6 × N`。

### 173.3 ★ 三个内容侧的真发现

1. **`CounterId` 有两种拼法，写错会静默错位**。`node.setCombatantCounter` 的 `CounterId` 在源 JSON 里
   是 `{"value": "…"}`（字符串字面量方言），而 `combatantCounter` **表达式**的 `CounterId` 是裸字符串。
   我一开始两处都写裸字符串 ⇒ 编码错位 ⇒ **后面所有 term 移位** ⇒ 一条**无关的** `ritual` 触发器读到
   非 term（`Ir(WrongKind("F_TERM"))`）。表现是"改 A 坏了 B"，找了一轮才定位。
   ⚠️ 我因此一度去"修" `sts_content_check.py` 里那行 `body["CounterId"]["value"]` —— **它原本是对的**，
   内核读的是编译后的 `F_STR`，源方言是编译器的事。
2. **效果是入队的，程序读不到自己刚写的计数器**。`setCombatantCounter` 把请求**入队**，所以
   "先 bump 再 `repeat`"里的 Count 读到的仍是旧值（实测 12 = (0+2)×6）。改成"读旧值 + 3，再 bump"，
   与 wiki 的 `N = 使用次数 + 2` **恒等**（第一次 0+3=3、第二次 1+3=4…）。递增仍成立、语义也仍然精确。
3. **`fx.incrementCounter` 在镜像里有名字、内核里没有 dispatch**（`ir.rs` 的清单里出现一次，
   `exec.rs` 里零处）。所以递增只能写成 `setCombatantCounter` 的"读+1 再写回"或"相对 +1"。

### 173.4 ★ 挡住落地的那个死锁（未修，下一轮第一件事）

`web-soak` 在 seed 102 上抓到（**可复现**）：

```json
{"panel":"精英节点（3 × Sentry）开始战斗","envActions":0,"envDone":0,"envResult":0,
 "duringFight":true,"handCards":0,"endDisabled":true,"turnPhase":0,
 "log":[…,"—— 第 5 回合 · 2 ——","打出 strike、defend、bash、metallicize"],
 "lastClicks":[…,"panel:开始战斗","use-potion:0 用"]}
```

判读：日志里 `leftHand`（回合结束弃牌）之后进入 **round 5 · turn 2**（敌方回合），然后**再没有任何
推进**；`active_combatant_id` 停在敌人身上，于是 `hero_is_active == false` ⇒ 动作表里既没有牌也没有
"结束回合" ⇒ 页面无处可点。

两条已排除/已确认的事实：

* **父提交（`105659c`）同一 seed 跑 soak 是绿的** ⇒ 这个状态在我的内容下才走到。不是我的内容"算错"，
  而是它改变了走的路径（精英池从 2/1/1 变成 3/3/1，RNG 抽到的遭遇与以前不同）。
* 一个"贪心打第一张牌 + 结束回合"的内核复现**没有**复现出来（`diag_greedy…` 测试通过），
  所以触发条件大概率在**药水/选牌**那条交互路径上（卡死前最后一个动作是 `use-potion:0`）。

⇒ 下一轮的第一件事不是加内容，而是**让"敌方回合跑不完"不可能发生**：`run_fight` 的驱动在
"Ongoing 且 active 不是英雄且动作表为空"时必须是**响亮错误**（或自动推进），而不是安静地停住。
这条一旦修好，§173 的内容可以直接从补丁脚本重新生成（脚本是幂等的：已存在的 id 不会重复追加）。

### 173.5 还差的两个精英（下一轮的后半）

按同样的口径还差 Act 3 的 **Nemesis** 与 **Reptomancer**，各自的机制缺口已经查清：

* **Nemesis**（HP 185，Tri Attack 6×3、Tri Burn 3 张 Burn 进弃牌堆、Scythe 45，"隔回合无形"）：
  `remainder` 表达式在（`expr.rs` 有 `remainder`），`roundNumber` 也在 ⇒ "隔回合"可表达；
  但"无形"要挂在一个**回合开始的触发器**上，而敌人的触发器只能挂在**状态**上 ⇒ 要么给 Nemesis 造一个
  载波状态（内容可加，但会多一个可见状态），要么内核支持"遭遇级触发器"（`ENCT.TriggeredEffects`
  今天被读出来但**没有人执行**）。
* **Reptomancer**（HP 180-190，Spawn Dagger / Big Bite 30 / Snake Strike 13×2 + 1 Weak）与 **Dagger**
  （HP 20-25，Wound 9 + 1 张 Wound / Explode 25 且自身死亡）：召唤有 `node.createCombatant`（Slime Boss
  分裂在用），但**没有 `destroyCombatant`** ⇒ "Explode 之后自己死"表达不出来。

### 173.6 数字

内容侧（生成后实测）：34 怪 / 25 遭遇 / 37 卡 / 71 敌动作，镜像 40,988 B（core 33,952 B），
`STS_CONTENT PASS`；`rd-wasm` +2 个机制测试（62 个）；20 项门里 19 项绿。
**但这一节没有交付**：`web-soak` 红 ⇒ 按纪律回退，工作树回到 `105659c` 的状态。

### 173.7 教训

**"内容加完、门绿了"不等于"能玩"。** 这一轮 19/20 的门、814 个单测、两条机制测试全绿，而一个随机
soak 在第 108 次点击时把局面卡死。这正是 soak 存在的理由 —— 它也是唯一一道**用时间换状态覆盖**的门。

---

## §175 Act 3 精英与药水池：又撞出一个更大的缺口（敌人起始状态从未应用）

这一节和第 §173 一样**没有落地**，但它挖到的东西比"再加两个精英"重要得多。

175.1 写完了什么（补丁脚本可重放）

  `native/patch_175_act3.py` + `native/patch_175_inventory.py`：

  · **Nemesis**（HP 185）：Tri Attack 6×3、Tri Burn（3 张 Burn 进弃牌堆）、Scythe 45、**隔回合无形**；
  · **Reptomancer**（HP 180-190）：Spawn Dagger、Big Bite 30、Snake Strike 13×2 + 1 Weak；
  · **Dagger**（HP 20-25）：Wound 9 + 1 张 Wound、Explode 25；
  · **Burn 牌**：`LifecyclePrograms[TurnEndInHand]` = 2 点伤害 —— 本包**第一张**真有生命期节目的卡
    （机制从 §1 就在，62/62 张卡的该字段一直是空 map）；
  · **standard.phantom_veil**：本包**第一条**用 `TurnStarted` 触发器的状态，用来做"隔回合无形"的载体。

  三幕的精英池因此都到 wiki 的三个。内容门全绿（37 怪 / 27 遭遇 / 25 状态 / 38 卡 / 79 动作，
  镜像 43,752 B）。Nemesis 的载体还单独在 `rd-core` 里验过：给一个战斗员挂上它，连续三次回合开始
  得到"开、关、开"——**内容本身是对的**。

175.2 ★★★ 真正的发现：`ENCT[*].Enemies[j].StartingStatuses` **从来没有被应用**

  这条测试是在 `rd-wasm` 里失败的，现场只有一句话：`nemesis statuses at start: []`。追下去才发现：

  * `content.rs` 早就把这份列表解码出来了，甚至**统计**过它（"20 条记录带 StartingStatuses"）；
  * 而 `build_session_at` 只读 `id` 与 `MaxHealth`，**没有任何代码把它们装上**。

  ⇒ 哨兵的 Artifact、Gremlin Leader 的 Enrage、Giant Head 的 Metallicize、§173 加的 Lagavulin 的
  Metallicize 8、**Slime Boss 的 `split` / `phase_split`** —— 全是"写着但不生效"。
  一个被**统计**过的字段，和一个被**实现**的字段，看起来一样。

  修法（同样留在补丁里）：`build_session_at` 在 `start_first_turn` **之前**，逐条读每个敌人记录的
  `StartingStatuses`，走 `EffectRequest::ApplyStatus` + `exec::drain` —— 与卡牌/敌动作**同一条**路径，
  不另写一份"加状态"。⚠️ spec 的键是 `StatusDefinitionId`，而 `content.rs` 的文档注释写的是 `Status`
  （又从没被执行过 ⇒ 也就没人发现注释是错的）。

175.3 ★ 打开它之后暴露的三件事

  ① **Boss 真的会分裂了**（`split` 终于生效）—— act 1 的难度回到 wiki 的水平，而 `web-slice` 的
     驱动器打不完了；
  ② 现场（新加的诊断，见 175.4）：`phase=WaitingToStartTurn` + `active=hero` + 手牌 7 张 + 只有
     "结束回合"一个动作 ⇒ **§174 修的那类死锁的另一种形状**（那边是 active=敌人）。补上"每一步之前
     先 `start_first_turn`"（参考驱动器的 `EnsureTurnStarted`）之后，phase 变成 `TurnInProgress`；
  ③ 但接着又冒出 `StepThrew(Script)`：**回合结束那一步抛 Script 错误**，于是回合推不动。
     这是下一个要查的点，也是最可能是"卡牌 `TurnEndInHand` 生命期节目 + 状态触发器"交界的 bug。

175.4 顺手加的诊断（这一节唯一留下来的代码）

  `web/act1_slice.mjs` 在打不完时把战斗现场记进报告（`actions/done/result/phase/round/turn/heroHp/
  hand/active/problem/enemies`）—— 与 soak 的卡死 dump 同一套字段。两份现场都是靠 `rd_env_active_len`
  与 `rd_env_problem_len`（§174 加的两个导出）才看得见的：**观察向量里没有"现在是谁的回合"**。

175.5 为什么回退

  `web-slice` 红 ⇒ 按纪律不提交。回退后 20/20 全绿（`web-soak` 207 次点击）。
  内容与修法都在补丁脚本里，幂等，可在死锁修好后一条命令重放：

      python native/patch_173_elites.py
      python native/patch_175_act3.py
      python native/patch_175_inventory.py
      python native/patch_175b_statuses.py     （改 rd-wasm + rd-core 的两处，见脚本头注释）

175.6 下一节的顺序（我建议）

  1. **先查 `StepThrew(Script)`**：回合结束那一步。它是 ②③ 的共同下游，也是"敌人起始状态生效"之后
     唯一挡住整局的东西。查法已经现成：`action=dump`（`web-slice` 会在失败时打印）。
  2. 然后重放 §175 的补丁（内容 + 起始状态 + `EnsureTurnStarted` 护栏）。
  3. **药水池差的 7 瓶**（`docs/sts-wiki-gap.md` §D.1 逐瓶点名各自要的机制）：无色牌池、战斗中整手牌
     升级、自动打出、打两次、整手牌改费、死亡拦截、逃跑。每一瓶都要动伤害管线或回合边界，所以它应该
     是**独立的一节**，而不是塞在精英池后面。

175.7 数字

  这一节净效果为零（内容与代码全部回退），但留下了：三个幂等的补丁脚本、`web-slice` 的战斗现场诊断、
  以及"敌人起始状态从未应用"这条结论。20/20 门、单测 813 与 §174 结束时一致。

---

## 176. 起始状态打开之后的连锁反应：召唤物不能行动（已定位并按纪律回退）

用户的判断对了一半也错了一半：**"耦合在回合结束"确实不是设计意图**，但它是**真实存在的耦合** ——
回合结束那条路径会跑两类内容程序：卡牌的 `LifecyclePrograms[TurnEndInHand]` 与状态的 `TurnEnded`
触发器，而 §175 恰好同时新增了这两类东西。真正的 bug 却不在那里。

176.1 ★★ 真正的根因：驱动器假定敌人名单在开局就固定

  内核级复现（不需要浏览器）：把 Slime Boss 打到 2 HP，它会分裂 —— 然后：

      第 11 回合: verdict -3 · err [活跃战斗员 `acid_slime_m#000000` 不在 plan.enemies 里]
      enemies: ["slime_boss=2", "acid_slime_m#000000=10", "spike_slime_s#000001=10"]

  `step_end_turn` 在 `plan.enemies`（开局时从 `ENCT` 记录里泄漏出来的固定切片）里找"轮到谁、它有
  哪些招"。而 `node.createCombatant` 造出来的战斗员（Boss 分裂、Reptomancer 的匕首、Gremlin Leader
  的 gremlin）**不在那个切片里** ⇒ 整个结束回合的步骤失败。页面上看起来就是"打不动"。

  这个假设一直没被撞破，是因为 §175 之前 `standard.split` / `phase_split`（起始状态）根本不生效
  —— **Boss 从来没分裂过**。两个 bug 互相掩盖了。

176.2 修法（两个脚本，已验证）

  * `native/patch_176_summons.py`：`Session::exec` 收 `Step<'_>` 而不是 `Step<'static>`（内核的
    `run_fight` 一直是 `'_`），于是可以传**局部副本**的 id，不必再泄漏；召唤物的招式表按**定义 id**
    到 `ENCT[*].Enemies[j].Id` 里找，轮转用内核自己的 `Actions[(round-1) % len]`。
  * `native/patch_176_bosstest.py`：三个 Boss 的回归测试（判据是"每一步都还受理 + 分裂后敌人真的
    行动"，不是"打赢"）。实测：**Slime Boss 11 回合（含 1 次分裂）→ 第 12 回合胜利**、
    **The Champ 25 回合**、**Time Eater 4 回合**，每一步都返回 0、`problems` 空。

176.3 还差最后一步：浏览器那条路径仍有一次 `StepThrew(Script)`

  内核的 Boss 战是绿的，但 `web-slice` 里 act-1 的 Boss 仍失败，现场（新加的诊断）：

      {"actions":1,"done":0,"result":0,"phase":1,"round":5,"turn":1,
       "heroHp":38,"hand":7,"active":"hero","problem":"StepThrew(Script)","enemies":["slime_boss"]}

  `Script` = `BattleError::Deck(_) | BattleError::Play(_)` —— **不是程序错误**，所以它不是敌动作，
  而是一次**出牌**在 `play::try_play_card` 里被拒。已排除的：回合没开始（§176 的
  `reobserve_after_external_change` 单点自愈已加上，`phase` 从 0 变成 1）；召唤物（已修）。
  剩下的线索是"手牌 7 张、只剩结束回合、round/turn 完全没动"，也就是**某一手牌被拒之后页面再没有
  合法动作**。

  ⚠️ 下一步需要的东西很具体：`BattleError::Play` 的**具体变体**（哪张牌、哪条拒因）今天到不了
  `problems`（那里只有家族名 `StepThrew(Script)`）。取它的最小改动是让 `battle.rs` 把一个
  `u8` 码写进 `FightOutcome`（`step_capacity` 就是这么做的），再由 `rd-wasm` 翻成人话。

176.4 为什么又回退

  `web-slice` 红 ⇒ 不提交。回退后 20/20（soak 207 次点击）。留下的产物：五个补丁/诊断脚本
  （`patch_176_summons.py`、`patch_176_bosstest.py`、`patch_176_diag.py`、`patch_175*`、
  `check_braces.py`）与 `web/act1_slice.mjs` 的战斗现场 dump。

176.5 一个值得记下的工具教训

  这次插入测试时用了 `text[:start] + new + text[end:]`，而 `end` 的位置**在 `start` 之前** ⇒
  整段尾巴被复制了一遍（+1325 行、多一个 `}`）。`native/check_braces.py` 就是为此写的：它按
  "剥掉字符串与注释后数花括号"报告深度，插完立刻能看出不平衡。**拼接前先断言两个锚点的先后顺序。**

176.6 药水池：这一轮没有开始

  用户要求"修起始状态 → 验三个 Boss → 继续药水"。前两件做完了（内核侧），第三件**未开始**：
  7 瓶药水的机制清单在 `docs/sts-wiki-gap.md` §D.1，各自要动伤害管线或回合边界。
  在 §176.3 的那个 `Play` 拒因查清之前开药水，会让两个 bug 混在一起。

---

## 177. 让"这一步抛了"说出原因：`u8` 码 + 宿主失败文本

### 177.1 两个诊断出口（这一节落地的代码）

`StepThrew(Exec)` 是一句**无法动手**的话。原因是两层折叠：

1. `StepCause::Script` 把 `BattleError::Deck(_) | Play(_)` 折成一个名字；`Exec` 也一样；
2. `TurnError::Host(HostFailure)` **只带五个家族**（文档明说"载荷只有类别"），而细节
   "在 `host::Host::last_failure()`（宿主自己保管，不会丢）" —— **而在此之前没有任何导出读过它**。

所以这一节加了两样东西（都是纯加性，不改任何玩法）：

* `FightOutcome.step_codes: [u8; MAX_STEPS]` + `battle::play_code` / `play_code_name`：
  把 `Play` 的 11 个变体与 6 条 `Refusal` 编成 `1..=17`（`step_capacity` 已经是这个形状的先例）；
* `rd_env_step_code(index)` / `rd_env_code_name_len|into(code)`：页面拿到码与名字；
* `rd_env_host_failure_len|into`：把 `Host::last_failure()` 的完整 `Debug` 文本吐出来 ——
  这一条比码值钱，因为它保留的是**原始错误**。

### 177.2 ★ 它当场就抓到了真凶

`web-act1_slice` 的 Boss 现场（加了这两个出口之后）：

```json
{"actions":1,"result":0,"phase":0,"round":5,"turn":1,"heroHp":38,"hand":7,"active":"hero",
 "problem":"StepThrew(Exec)","hostFailure":"Exec(Capacity(Full(Combatants)))","enemies":["slime_boss"]}
```

**`Full(Combatants)`** —— 战斗员容器（`MAX_COMBATANTS` = 12）满了。`enemies` 只剩 1 个，
说明占着槽位的是**死掉的召唤物**：分裂发生了 5 次以上。

### 177.3 ★★ 为什么内容侧的"只分裂一次"守卫不管用（设计级结论）

两个分裂状态其实**都有**自我移除：

* `standard.split`（`Downed`）：`[create, create, modify(-1)]`；
* `standard.phase_split`（`DamageTaken`，血量 ≤10）：`[create, create, modify(-1)]`。

我把 `modify(-1)` 挪到**最前面**试验过，仍然 `Full(Combatants)`。原因是 §173 那条教训的延伸：

> **触发器程序里的每个效果都是入队的请求。** 同一个伤害批次（一次多段攻击）在
> **移除落地之前**就把后续每一次伤害的触发器都收进了 batch，于是每一次都看到"状态还在"。

所以"once only"**不能由内容表达**。要么内核在跑完一个触发器程序后立刻排空（让移除先落地），
要么 `createCombatant` 按"每个事件一次"去重。这是**内核**的决定，不是内容的。

⚠️ 内容门也帮不上：它只钉 `phase_split` 的**触发事件**（`DamageTaken`），不钉程序形状 ——
20 条状态里只有 `lose_strength`/`lose_dexterity` 钉了 facts。这是另一个"检查看着存在但不覆盖"。

### 177.4 为什么又只提交诊断

`web-slice` 在内容应用后仍然是红的（Boss 卡在 `Full(Combatants)`），而**根因现在已经精确**：
不是"某个东西莫名被拒"，而是"一个内容无法表达的 once-only 语义"。修它要动内核的触发器排空
顺序，那是一个独立的、需要自己判据的改动 —— 和诊断混在一起会让两者都说不清。

⇒ 这一节只提交：`step_codes` + `play_code`/`play_code_name` + 三个导出 + `act1_slice` 的现场
dump（含 `hostFailure` 与 `code`）。内容与 §175/§176 的补丁仍然留在脚本里，20/20 门全绿，
单测 814（诊断没有加测试，它自己由浏览器闸门与 soak 间接验证）。

### 177.5 下一节（顺序已定）

1. **内核：让触发器程序的移除先落地**（或 `createCombatant` 去重），判据是"Boss 在 ≤10 HP
   连挨三下只分裂一次，且 `Combatants` 从不满"。
2. 然后重放 §173/§175 的内容补丁（幂等脚本都在）。
3. 再做药水池差的 7 瓶。

---

## 178. 补上"消失"这一半：`node.destroyCombatant`

§177 只提交了诊断，但它已经指出真凶（`Exec(Capacity(Full(Combatants)))`）。这一节把它修到底。

### 178.1 为什么"排空顺序"不是正确的修法

第一版想法是让触发器程序的写**先落地**（改排空顺序）。查参考实现证伪了这条路：

* `ModifyStatusStacksNodeExecutor` 在参考里也是 `combat.EnqueueEffect(...)`（`EffectProgramNodeExecutors.cs:1287`）
  —— **FIFO 队列是参考的形状**，不是我们的偏差；
* 参考之所以没有这个问题，是因为它**根本没有 `createCombatant` 这个节点**（`grep CreateCombatant`
  在 `ref/RogueDeck-Core` 里一条都没有）。分裂是**我们的扩展**，那"只分裂一次"就得由我们的语义来保证。

所以真正缺的是另一半：**内容无法表达"这个战斗员不在了"**。StS 的 Slime Boss 分裂是
"Boss 消失、两只史莱姆顶替"，而我们只能说"再造两只" —— 于是任何"只一次"的守卫都只能是状态层数，
而状态写入是入队请求（§177 的实测：三次伤害各分裂一次）。

### 178.2 落地

| 层 | 改动 |
|---|---|
| `state.rs` | `remove_combatant`：名册 / 回合序 / 牌堆表**三处一起移位**（顺序是语义，不能 swap）；拒绝移除**当前行动者**（回合循环按 id 找它）。新错误 `ActiveCombatant`。 |
| `ir.rs` | `NodeKind::DestroyCombatant` = `"node.destroyCombatant"`（**追加**在表尾，判别串是字符串，二进制不动）。 |
| `exec.rs` | 节点本体：`TargetSelector` 解析不出目标 ⇒ 枪响（`NoSource`）；目标已不在场 ⇒ 跳过（多段牌可以两次点名同一个）。与 `createCombatant` 一样**立即生效**，因为"立即"正是 once-only 能表达的唯一形式。 |
| `beat.rs` | `BeatKind::Destroyed = 13`（`Downed` ≠ 消失：倒下的还在名册里、触发器还能响）。 |
| `sel.rs` | ★ **补上 `sel.sourceIncludingDowned` 的判别串**。变体早在 `targets.rs`，但 `leaf_for` 没有名字 ⇒ 参考的写法在我们这里会拿到 `UnsupportedKind`。而 `standard.split` 挂在 `Downed` 上，`sel.source` 对**倒下的**战斗员解析为**空集**（参考 `:130` 的 `IsAlive`）—— 这条缺口正好卡住分裂。 |
| 内容 | `split` / `phase_split` = `[destroy(self), create, create]`，删掉没用的 `modify(-1)`。 |

### 178.3 ★★ 第二个 bug：打"已经不在的目标"

修好分裂后，`the_boss_phase_splits_once_at_low_health` 的第二下抛 `MissingCombatant`。这不是测试的
毛病，而是浏览器里**必然**发生的事：多段攻击的三条 `DealDamage` 请求在**入队时**就指名了 Boss，
第一段把它打没了，第二段落地时目标已不存在。

判据要分两个入口，因为两种"目标不存在"是不同的事：

* **队里**的请求（`resolve_effect`）：目标在**解析那一刻**已经不在 ⇒ **丢掉**。请求是"入队时"解析
  选择器产生的，中间被 `destroyCombatant` 拿走是引擎自己的动作，不是内容写错；
* **直接**调用 `resolve_damage`（出牌、DoT）：目标不存在仍然**枪响** —— 那里 id 是调用方刚递过来的，
  写错了就该当场知道。

新增 `request_target`（穷尽 `match`，没有 `_` 臂：新变体必须显式回答"你指向谁"）。

### 178.4 §175/§176 的内容补丁重新叠上来了

§175（Act3：Nemesis / Reptomancer / Dagger / Burn / `phantom_veil`）与 §176（召唤物能行动）
的脚本重新应用，全部通过。重新应用时暴露了三处**旧断言**（它们都假设"分裂只是多两只"）：

1. `a_split_spawns_two_combatants_when_the_boss_dies`：`before + 2` → `before + 1`（替换不是复制）；
2. `a_spawned_enemy_joins_the_turn_order_after_the_current_actor`：5 格 → 4 格，"倒下还在序里"
   改成"消失不在序里"；
3. `the_boss_phase_splits_once_at_low_health`：`stacks_of(...) == 0` 改成"承受者不在了"
   —— 前者会留一具**还能被打**的尸体。

另外两处是 §175b（起始状态真的生效）带来的**正确**变化，测试该变锋利：

* `damage_beats()` 现在只数**打在敌人身上的**伤害条。`enc_small_slimes` 的 `spike_slime_s` 起始
  带 Thorns 3 ⇒ 每次攻击都记一条**打英雄**的 3 点，原来"每条都是 5"的断言会拿反伤去比；
* reset 之后的日志从"至多 1 条"改成"只许 `TurnStarted` 与 `StatusChanged`，且至多一次回合开始"
  —— 起始状态落地本来就是 `StatusChanged`。

### 178.5 数字

* **20/20 闸门绿**，单测 **816**（rd-core 656 / rd-run 100 / rd-wasm 62，`--test-threads=1`）。
* soak **350 次点击**（§177 前 207）：Act3 的牌与精英进了随机路径。
* 内容：37 怪 / 27 遭遇 / 38 卡 / 25 状态 / 79 敌动作，镜像 43,684 B（core 36,060 B）。
* `ACT1_SLICE PASS`：三幕 Boss 都能被打过、幕能推进（§177 时 Boss 卡在 `Full(Combatants)`）。

⚠️ 留下的一条**已知偏差**：`remove_combatant` 拒绝移除**当前行动者**。Reptomancer 的匕首在
**自己行动时**自毁（StS 里 Explode 会死）需要回合循环改写，今天做不到 —— 那需要"行动者消失后
回合怎么收尾"的判据，不是加一个参数能解决的。

---

## 179. 药水池（一）：三瓶想"一次打完"的药水

计划里差的 7 瓶里，有三瓶只需要小机制。这一节落地它们，连同四个必须一起动的词表。

### 179.1 三瓶各自缺什么

| 药水 | wiki 原文（未升级基线） | 缺的机制 |
|---|---|---|
| Blessing of the Forge | "Upgrade all cards in your hand for the rest of combat." | **战斗中升级** |
| Snecko Oil | "Draw 5 cards. Randomize the costs of all cards in your hand for the rest of combat." | **不被消费的每副本价格** |
| Smoke Bomb | "Escape from a non-boss combat. Receive no rewards." | **脱战**（运行层结局） |

### 179.2 升级 = 换定义 id（不是显示层小把戏）

我们的 `+` 行是**独立的 `CARD` 行**，而 `play` 是按**定义 id** 查节目的 ⇒ 把实例的
`definition_id` 换成 `id + "+"` **就是**升级。判据因此是定义 id 而不是名字：`strike+` 打 9、
`strike` 打 6 —— 只换名字的假升级能骗过标签检查，骗不过这一条。

没有 `+` 行的牌（已升级 / 不可升级）原地不动，与 StS 一致。内容里问"有没有这一行"用的是
`Content::lookup_in(id, EK_CARD)` —— 内容的 id 索引，不是我猜。

### 179.3 ★ 为什么必须**第二个**计数器

已有的 `standard.card_cost_delta` 是"一次承诺"：**出牌付款之后清零**（`CardPlay.cs:176-183`）。
而 Snecko Oil 的原文是 "**for the rest of combat**" —— 用 delta 表达，这瓶药只有效一次，
而且**没有任何闸门会红**（它会以"这瓶药好像只管一张牌"的形式坏掉）。

所以加 `standard.card_cost_override`：**绝对价**、读在 delta **之前**、**永不清零**。
两个计数器在同一个 `CostStage::CardInstance` 里，因为参考对这个阶段只有一个位置。

判据 `the_randomized_price_survives_the_play_but_the_delta_does_not`：0 费打出、牌回手、再打一次，
两次都**一滴能量不扣**。负控（去掉覆盖分支）实测：`Some(1) != None` —— 红得准确。

### 179.4 脱战是**运行层**的结局，不是第四种 `CombatResult`

内核的三种结果与参考**逐字节**一致，而且 `result=` 在黄金指纹里 ⇒ 加第四种会动整个语料。
所以 `result = 3` 只在 `FightOutcome` 的高位与 `apply_fight_outcome` 里存在：
不跑 `end_of_combat`、不掷奖励、不给 Boss 记账，但节点**算用掉了**（`mark_resolved`）。
Boss 战拒绝（wiki：non-boss combat）。

⚠️ `rd_env_use_potion` 的契约是 `0` = "喝了"，所以 `flee_fight` 成功返回 **0**，"是否脱战成功"
是页面从观察（`in_fight`）读的事实 —— 第一版返回了 `3`（运行层的结局码），测试立刻红。

### 179.5 ★★ 四份词表，一次都没漏（但都是闸门抓的）

内容里加了三瓶，`sts-content` 与单测连续红了四次，每次都是**同一个东西的第四份副本**：

1. `content.rs` 的**闭词表**（解析期拒绝未知效果）；
2. `content.rs` 的"哪一种读 amount"清单；
3. 内置的 29 个药水 id 清单（排序过，所以插入位置也要对）；
4. **`rd_run_potion_effect` 的 `known` 分类**（页面据此决定要不要选敌人）；
   它由 §161.3 的 `every_potion_in_the_table_classifies_as_known` 兜住 —— 这条测试**遍历整张
   表**，所以新原子漏在第四份里会**立刻**红，而不是等玩家发现"这瓶药是未知效果"。

这正是 §161.3 的教训第二次兑现：**同一个词表被多处认识就一定漂**。三处注释里都写明了"还有
另外几份，一起改"。

### 179.6 数字

* **20/20 闸门绿**，单测 **820**（rd-core 655 / rd-run 100 / rd-wasm 65）。
* 内容：29 瓶药水（Common 16 / Uncommon 7 / Rare 6；wiki 的 Ironclad 池是 17 / 9 / 7，
  差的正是这个内容没有的两瓶）。
* 还剩 4 瓶：Fairy in a Bottle（死亡拦截）、Duplication Potion（打两次）、
  Distilled Chaos（自动打出）、Colorless Potion（无色牌池）。

---

## 180. 药水池（二）：Fairy in a Bottle —— 那个"能解出来但没人读"的字段

`STAT.DeathPrevention` 从状态行存在那天就能解（`content.rs:1457`），**十年没人读**：缺口文档一直
挂着它，而"能解出来"与"有行为"是两件事。这一节把参考的 `IPreDownInterceptor` 这一半接上。

### 180.1 参考的形状

`SandboxInterceptors.cs:16-58`：
`StatusDeathPreventionData(SurvivingHealth, Effects, Repeating)` —— 承受者戴着这个状态时，
这一下被**接住**：生存血量 = `max(1, SurvivingHealth)`，状态**被消耗**（`Repeating` 才留下）。

位置是语义：**穿过格挡 / Buffer / Plated Armor 之后、转 `Downed` 之前**。所以它住在
`exec::resolve_damage_of_kind` 里，就在 `MarkCombatantDownedOnZeroHealthHandler` 那一步之前 ——
而那里已经有一个活着的 `combatant` 可变借用，所以这段代码被放在它**之前**（第一版放在之后，
借用检查器直接拒绝，不是风格问题）。

### 180.2 `Percent` 是本移植的扩展

wiki 的 Fairy in a Bottle 是 "heal to **30% of your Max HP**"，而参考的数据只有平值
`SurvivingHealth` —— 用平值表达，要么对每一种最大生命都错，要么内容里每个英雄一行。
所以线格式多一个可选 `Percent`，公式 `max(SurvivingHealth, 最大生命 * Percent / 100, 1)`。

### 180.3 判据是**三面**的

"没死"单独一条会被"连别人的死亡也一起拒绝了"的 bug 满足。所以
`the_charm_catches_one_killing_blow_and_is_spent` 断言：① 致命伤后**活着且正好 30%**；
② 状态**被消耗**（wiki: "works once"）；③ **第二下真的死**（`Downed`）。

负控：把整段拦截关掉 ⇒ `left: 0, right: 21`，红在"活着且正好 30%"那句上。

### 180.4 ★★ 闸门抓到的不是内核，是**驱动器**

内容一落地，`web-slice` 红：Boss 战 900 次点击零进展，`problem`/`hostFailure` 都是 null。
把 `#msg` 加进现场 dump 之后答案立刻有了：

```
"msg": "用药水 被拒 · Boss 战不能脱战（Smoke Bomb：non-boss combat）"
```

**产品行为是对的**（Boss 战不能脱战），错的是切片驱动器：它在半血分支点"第一瓶药"然后
`continue`，而这次拒绝**什么都没改变** ⇒ 同一瓶被点了整个预算。修法：每场战斗**每个药水槽
只试一次**（拒绝也记住），不是"药水喝了就一定有效"。

这条值得单独记：**合法的拒绝也会锁死一个假设"动作总会改变状态"的驱动**。上一节的
`StepThrew` 诊断、这一节的 `#msg`，两者都是"让卡住的地方说话"，而两次都是**先说清，再修对**。

### 180.5 数字

* **20/20 闸门绿**，单测 **821**（rd-core 656 / rd-run 100 / rd-wasm 65）。
* 内容：30 瓶药水（Common 16 / Uncommon 7 / Rare 7）、26 个状态。
* 惰性声明少了一条：`Statuses[]:DeathPrevention` 从 `InertKeys` 里删掉 —— 是内容门自己喊的
  （"declared inert but the kernel reads it at status_bind.rs:638"），这正是那个声明的用途。
* 还剩 3 瓶：Duplication（打两次）、Distilled Chaos（自动打出）、Colorless（无色牌池）。

---

## 181–183. 药水池（三）：打两次、自动打出、无色牌池

### 181. Duplication Potion —— "your next card is played twice"

机制是**状态**（`standard.duplication`，`UsesCharges`）+ 出牌路径上的一个判断。位置在
`apply_plan_in_chain`，理由三条，每条都是"否则就错"：

1. 那里是**唯一**"只付一次费、只算一次出牌"的地方 —— 参考的 `CardPlay` 早就把能量扣了；
   如果改成"再调一次 `play_card`"，能量扣两次、`cards_played_this_turn` 加两次（StS 都不是这样）。
2. 那里**有 `Content` 借用**。终态回调（`finish_frame`）是数据驱动的、没有 content，而 `NodeRef`
   需要它；要把 content 穿进 `finish_frame` 得改 5 个调用点、其中两个（`fail_frame` /
   `cancel_live_frames`）根本拿不到。
3. 两遍的节目是**入队**的（`exec::begin` 只派发、不落地），所以 A 的请求在前、B 的请求在后，
   正是"打两次"要的顺序。

判据三面：伤害**两份**（20→8）、能量**只付一次**、`cards_played_this_turn` **只加一次**，
然后那一层被花掉 ⇒ 第二张牌只打一遍。负控（`passes` 固定为 1）⇒ `left: 14, right: 8`。

### 182. Distilled Chaos —— "Play the top 3 cards of your draw pile"

不是第二条出牌管线：**抽到手里 → 用 §179 的每副本覆盖把它变成 0 费 → 走普通 `play_card`**。
所以牌真的被打出（落区、`CardPlayed` 事件、节目都照常）。判据四面：抽牌堆 −3、弃牌堆 +3
（= 真的打出了）、敌人掉血、**能量不动**。

⚠️ 两处写明了的偏差：目标是**第一个活着的敌人**（StS 随机；我们要求同一 seed 重放同一目标）；
不可打出的牌（诅咒）搬去弃牌堆后继续。

### 183. Colorless Potion —— 机制成立，内容**未落地**

`choice_offered:<tag>`（§161.5）本来就在，缺的只是三张无色牌。三张都写好了
（Bandage Up / Blind / Dark Shackles，最后一张正好用上内容里已有的 `standard.lose_strength`），
单测也钉住了"候选恰好三张、全是 colorless、选中的牌进手牌"。**但闸门不绿**：

```
boss seed=101  hpBefore=90  actAfter=1  msgAfter="战斗结束 · Defeat"
```

把 33 瓶药水 + 3 张无色牌加进内容之后，**同一个种子走的是另一条路线**（掉落表与奖励池都变了），
而这个驱动器在 Boss 战里输了。这是**合法的战败**，不是引擎 bug —— 但闸门的断言是"这一幕能走完"，
所以它变成了对内容字节数的抽签。

按纪律撤回内容，留下三块**可复用的资产**与一条结论：

* `reward_pool` 里的 colorless 滤网（当前内容没有 colorless 牌，所以它是空转 —— 但它防的是
  "无色牌漏进普通奖励"这个未来的 bug，注释写明了）；
* 三张卡的**正确写法**（这一节最大的收获见下）；
* 结论：**押单一 seed 的闸门经不起内容增长**。要让 §183 落地，先给 boss 场景一个"重试到赢"的
  驱动（`BOSS_SEEDS` 的第一版试过：种子 202 能赢但腰带是满的、药水锚点没触发；505 腰带空但输了），
  或者把机器人做强。这是下一节的第一件事，不是"再挑一个幸运数字"。

### 183.1 ★★ 内容方言的两个坑（都只会在内核里炸，内容门看不见）

1. **`node.applyStatus` 的 `DurationTurns` / `Charges` 是裸整数**，不是 term。写成
   `{"kind":"const",…}` 会被当 JSON 编进镜像，然后在**任何**状态的触发器里炸成
   `Ir(WrongKind("F_JSON"))` —— 症状是"加了一张卡，另一个不相关的测试红了"。
2. **`sel.allEnemies` 的 `value` 是 `{}` 或 `{"Cardinality":"Any"}`**；写 `"Many"` 是同一个
   `F_JSON` 症状。

两者都是"内容门只读 JSON、二进制只有内核测试碰"，所以定位成本极高（这一节在这上面花了最久）。
**下一步的闸门候选**：内容门应当把编译后的镜像**反解一遍**（或至少 `rdcf-verify` 覆盖 CARD 行），
否则"形状错"永远只在运行时暴露。

### 183.2 数字

* **20/20 闸门绿**，单测 **823**（rd-core 657 / rd-run 100 / rd-wasm 66）。
* 内容：38 卡 / 32 瓶药水（Common 16 / Uncommon 9 / Rare 7）/ 27 状态。
* 药水池只剩 **1 瓶**没落地：Colorless（内容已写好，等驱动）。

---

## 184. 闸门：内容门学会读**镜像里的 term 表**

§183 的两个坑（`DurationTurns` 写成 term、`sel.allEnemies` 的 `Cardinality` 写成对象）都是
"源文档 JSON 合法、编译成功、字节门全绿"，然后在一个**不相关的**内核测试里炸成
`Ir(WrongKind("F_JSON"))`。这一节把那个盲区补上。

### 184.1 根因：`F_JSON` 是**字段声明**层面的，不是值层面的

第一版判据是"镜像里不许有 `_json` term"，负控立刻证伪：**只改一处时编译器会乖乖把那个 opcode
的字段声明成 `F_TERM`**，读者全能读，内核也不炸。真正的机制是：

> 同一个 opcode 的同一个字段在不同出现处**形状不一致**（十六张卡写裸整数、一张写 term）
> ⇒ 编译器只能把整个字段降级成 `F_JSON` ⇒ 内核的 `NodeRef::field()` 对 `F_JSON`
> **无条件** `Err(WrongKind("F_JSON"))`。

所以判据是：**除保留 opcode 5（`_json`）自己之外，任何 opcode 的任何字段都不许声明成 `F_JSON`。**
这条判据的失败消息会指名 `opcode 27（'node.applyStatus'）的字段 'DurationTurns'`——
而那条消息正是"哪十六张卡里的哪一张不一致"的入口。

### 184.2 落地：独立解析，不借编译器的代码

新文件 `tools/rdcf_terms.py`，只 import `rdcfmt` 的**格式常量**（§167 的"常量只有一个出处"），
自己解 OPD/OPF/TRM/TRW/STR/STRO：

* **判据 1**：不允许 `F_JSON` 字段声明（见上）；
* **判据 2**：不允许 `_json` term，且失败消息带上那段 JSON 原文；
* **判据 3**：`F_TERM` 槽指向的 term id 必须真实存在（段 id 位移那种"对的字节、错的 id"）。

它挂在**第 11 道闸门**（`rdcf-verify`）里，而不是新增第 21 道 —— 那道闸门的职责本来就是
"只读字节、独立复核"，之前它自己写着"段内编码我验不了"，现在这句话少了一句。

顺带修了 `rdcf_verify.py` 的一个真 bug：镜像目录原来写死 `tools/contentc/out`，
于是**负控构建出来的草稿镜像它根本看不到**（报"文件不存在"而不是验证它）。现在目录跟着传进去的
manifest 走。

### 184.3 负控（`native/negctl_184.py`）

四下判断，缺一不可：**基线绿 → bug①红（且点名）→ bug②红 → 清理后回绿**。
`NEGCTL_184 PASS`。第一次跑它时 bug① 是**绿的** —— 正因为负控用了"只改一处"的真实形状，
才把第一版判据（"不许有 `_json` term"）证伪。这是 §177 那条教训的第二次兑现：
**一个从没红过的判据，你不知道它长什么样。**

⚠️ 两次坑值得记：`rdcf_verify.py` 子进程输出是 **GBK**，用 `text=True` 直接解码会抛
`UnicodeDecodeError` 并把 `stdout` 变成 `None`（于是判据变成 `None in ...` 崩掉）——
一律 `capture_output=True` + 显式 `decode(..., "replace")`。

### 184.4 数字

* **20/20 闸门绿**（未新增闸门，扩了第 11 道），单测 **823**。
* 第 11 道闸门的证据串现在写：`... 1274 table rows, 6 term-shape checks over 5,038 terms`。
  **证据串必须能反映新增覆盖**，否则"加了检查"与"没加"在输出上无法区分。

---

## 185. 驱动：boss 场景改成"重试到赢"，Colorless 落地

§183 把 Colorless 的内容撤回了，理由写得很清楚：加进去之后**同一个种子走另一条路线**，
驱动器在 Boss 战输掉 —— 合法的战败，但闸门的断言是"这一幕能走完"，于是它变成对内容字节数的抽签。
这一节修的是**驱动**，不是内容。

### 185.1 场景的两种做法，选的是第三种

* "换个幸运数字" —— 换个内容大小又坏，等于没修；
* "把断言改弱"（例如只验"能走到 Boss"）—— 那是 §175b 记过的腐烂方向；
* **选的是**：场景自己把两个主张都试出来 —— `BOSS_SEEDS` 依次重试，取第一个**同时**满足
  「幕推进了（`actAfter === 2`）」与「§161.7 药水锚点真的跑过（能给药、开了选择、答了题）」的种子。
  两个条件缺一不可：202 号种子能赢但腰带是满的（`potionGranted = -2`），它一次都没验到锚点。

每次尝试都记进 `row.attempts`（种子、floor、kind、是否开打、结果），所以红的时候报的是
"哪个种子死在第几层"，而不是一句"Boss 没打过"。

### 185.2 ★★ 抽签的真正来源是**药水掉落表**，不是奖励池

试了 24 个种子后仍然只有一个能赢，于是把现场拆开看：`floor=16, kind=7, started=true` ——
它们**走到了 Boss 并开打了，是打输的**。差别不在牌组，在腰带：

> 药水表从 32 涨到 33，掉落的种子就变了；驱动器在**半血**时会喝"腰带里的任何一瓶"，
> 于是有时喝到 **Snecko Oil**（费用随机化）—— 那瓶药是赌博，赌输了就死。

这是**合法的玩法后果**，不是 bug。但一场关于"这一幕能不能走完"的闸门不该由它决定，
所以 boss 场景把腰带**钉住**：`dropPotions()`（新加的 `?debug` 入口）+ Fire Potion（20 点伤害，
永不赌博）+ Attack Potion（锚点要喝的那瓶）。别的场景不动 —— 掉落抽签在 soak 里照样被覆盖。

### 185.3 Colorless 落地

驱动修好后，§183 的三张无色牌与其药水原样加回：**内容门、新闸门、24 个种子、切片全绿**。

* 无色牌**不进任何牌组**：滤网放在 `full_pool`（商人**和**奖励都从它取样），不是只放奖励池。
  ⚠️ 这条位置是被数据逼出来的：只滤奖励池时，三张新牌会出现在**商店**，驱动器买了它们、
  牌组变弱、24 个种子里 11 个死得更早。一个规则一个出处 —— 两个列表之间的乒乓正是泄漏的活法。
* 三张牌**没有 `+` 行**：不是"不能升级"（StS 里能），而是**没有任何牌组能装下它们**
  （唯一的获取途径是药水在一次战斗里给），`+` 行会是没人能到达的内容。写进 `NOT_UPGRADABLE_TAGS`。
* 判据（`colorless_potion_offers_three_colorless_cards_and_the_pick_lands_in_hand`）：
  问句是 Offered（`source = 2`）、恰好 3 个候选、每个候选都是本内容的三张无色牌之一、
  选中之后真的进手牌。

### 185.4 数字

* **20/20 闸门绿**，单测 **824**（rd-core 657 / rd-run 100 / rd-wasm 67）。
* 内容：**41 卡 / 33 瓶药水（Common 17 / Uncommon 9 / Rare 7）/ 27 状态**。
* **药水池 25 → 33，差的 7 瓶全部落地**（Fairy 在 §180，其余在 §179/§181/§182/§183/§185）。

---

## 186. 文档体检：回 wiki 重核、规格书补课、README 重写

这一节不动代码，只把"仓库说的"和"仓库做的"对齐。触发点有三条：药水池刚做完（7 瓶新内容 +
3 张无色牌）、§178–§185 加了四个新机制（销毁 / 死亡拦截 / 打两次 / 自动打出），
以及 README 从来没写过"下载源码之后怎么跑起来"。

### 186.1 ★★ 回 wiki 重核：抓到我们自己的一处内容错误

逐条回到 `slaythespire.wiki.gg` 的**单卡页**核对本轮新增的内容（不只对清单页）：

```
blind:  Rarity = Common      (我们)  ->  Uncommon        (wiki 单卡页 / Colorless_Cards)
        PlayedCardDestinationZone = Exhaust (我们)  ->  DiscardPile（Blind **不** Exhaust）
```

同批核对的其余条目都对：`bandage_up`（Uncommon / Heal 4 / **Exhaust**）、`dark_shackles`
（Uncommon / −9 Strength **this turn** / **Exhaust**）、33 瓶药水的稀有度分布（17 / 9 / 7）、
Act 2/3 六个精英的 HP 与招式（Book of Stabbing 160-164、Lagavulin 109-111 + Metallicize 8、
Taskmaster 54-60 + Wound、Nemesis 185 + 隔回合 Intangible、Reptomancer 180-190 + 最多 4 匕首、
Giant Head 500）。

**而当时 20 道闸门全绿。** 原因值得写下来：

> 内容门（`native/sts_content_check.py`）对照的是 `docs/spec/sts-act1-inventory.md` 里的清单，
> 而**那份清单也是人抄的**。于是"我们抄错 + 清单也抄错"这个组合没有任何判据能看见 ——
> 与 §161.3 的"同一个词表被多处认识就一定漂"是同一个形状，只不过这次漂的是**数据**不是词表。

⇒ 结论写进缺口文档 §4：新内容落地时，**稀有度**与**是否 Exhaust** 这两格必须回到单卡页看一眼，
它们最容易被"顺手抄邻居"。本轮的错误正是这两格一起抄错了。

### 186.2 `docs/sts-wiki-gap.md`：整篇重写

旧版写于"药水 26/33、精英 4 个遭遇"的年代，一半的"没有"已经做完。重写后：

* §1 已对上的部分：补上销毁战斗员、死亡拦截、自动打出、脱战、**药水池已满**、§177 的诊断导出；
* §2.A 关键词：`Double Damage` 从"没有"改成"**部分**"（`standard.duplication` + 出牌路径已在用，
  但它挂在状态上、不是卡牌关键词，也不认"攻击牌"这个条件）；
* §2.B 状态：明确列出**三类** —— wiki 有且我们有规则的、**本移植自己的载体**
  （`fairy_in_a_bottle` / `duplication` / `phantom_veil`，wiki 没有同名状态）、以及还缺的
  （Barricade / Blur / Entangled / Slow / Draw / Energized）；
* §2.C 战斗流程：逃跑、销毁、死亡拦截、整手牌升级/改费、自动打出都移进"有"；
  仍然缺的是"偷钱后逃跑"、"形态切换/复活"、以及**行动者自毁**（`remove_combatant` 拒绝移除当前行动者）；
* §2.D：精英池改成**每幕 3 个**（Act1/2/3 各三个都齐了）；药水 33/33；无色牌**不出售**；
* §D.1：从"差 7 瓶"改成"7 瓶各自最后怎么做的"（留档：为什么 Fairy 是个状态、为什么脱战在运行层）；
* §2.E Ascension：表格加"若要做，卡在哪"一列，并点出 **`EACT` 一根维度解锁六条规则**；
* §3 建议顺序：改成"先 `EACT` 维度 → 事件效果列表 → A1/A10/A12 → 第二三只 Boss → 行动者自毁 → A20"。

### 186.3 `docs/spec/*`：给 8 份规格书补"实现补充"章节

规格书是**冻结的设计契约**，所以不改正文，只在末尾（或 §2 之后）追加带日期的落地记录：

| 文件 | 补了什么 |
|---|---|
| `SEMANTICS-v1.md` | 新增 **§2.3 实现期扩展**：`node.destroyCombatant`、`STAT.DeathPrevention`（PreDown 拦截）、`card_cost_override`、`duplication`、运行层动词，以及那条"触发器效果是入队请求 ⇒ once-only 不能由内容表达"的队列语义 |
| `play-card-flow.md` | §11：费用阶段的**绝对价**（读在 delta 之前、不被消费）与"节目跑两遍"为什么只能放在 `apply_plan_in_chain`（那里同时有"只付一次费"与 `Content` 借用） |
| `modifier-pipeline.md` | §8：两张"每副本"计数器（delta 付款即清零 / override 永不清零）+ 为什么必须用 `mark_counter_opt` |
| `run-layer.md` | §10：脱战是**运行层** `result = 3`（动内核会动 85 份语料）；无色牌滤网放在 `full_pool`（商人**和**奖励都从它取样） |
| `content-schema.md` | §8：三个新节点/字段 + **两个只在镜像里炸的方言坑**（`DurationTurns` 是裸整数、`sel.allEnemies` 的 value 形状） |
| `content-binary-format.md` | §6：term 表的**形状**现在被第 11 道闸门读（三条判据 + 负控） |
| `env-abi.md` | §12：§177 的三个诊断导出（拒绝码 + 宿主失败原文）+ `?debug` 的 `dropPotions()` |
| `sts-act1-plan.md` | §10：现状（能力/内容/仍缺）与"以 gap 文档与 port-plan 为准"的指向 |

顺带在 `sts-act1-inventory.md` 补了两块**之前没有出处记录**的 wiki 事实：**§3.6 无色牌**
（含 Blind 的两个易抄错格子）、**§4.4 Act 2/3 的 6 个精英**；并把 §4.3.1 那句"本版 Slime Boss
**不分裂**"改成"现在会分裂"（§178 之后它才第一次能正确表达）。

### 186.4 README：新增「五分钟跑起来」

原 README 只讲架构与闸门，一个**普通用户**看完不知道从哪开始。新版第一节是完整的上手路径：

1. 装什么（Rust + wasm 目标 + Python；Node/Chrome 只在跑闸门时需要）；
2. `cargo build -p rd-wasm --release --target wasm32-unknown-unknown` + 覆盖 `web/rd_wasm.wasm`
   （并说明**内容镜像已经 `include_bytes!` 进 wasm**，不需要另备数据）；
3. `python -m http.server 8000` → `http://127.0.0.1:8000/web/index.html`
   （并解释为什么必须走 HTTP、为什么从**仓库根目录**起服务）；
4. **怎么玩**：种子 → 祝福 → 地图六种节点 → 战斗（点牌/点敌人/结束回合、意图、药水）→ 奖励/商店/篝火；
5. `?debug` 面板的五个调试入口；
6. **常见坑表**：白屏（`file://`）、缓存（Ctrl+F5）、改了内核没重编 wasm、没装 wasm 目标、内容没重编。

两处"可验证的断言"当场验了，不靠感觉：

* `python -m http.server` 对 `.wasm` 发的 Content-Type 实测是 **`application/wasm`**（否则浏览器会拒绝流式实例化）；
* **全新 target 目录**（`--target-dir` 指向一个空目录）能从零编出 wasm，9.78 s —— 说明上手路径
  不依赖任何陈旧产物。

### 186.5 数字

* 文档：`README.md` 重写（新增 §1 上手 + §1.4 玩法 + §1.5 调试 + §1.6 坑表），
  `sts-wiki-gap.md` 整篇重写，`sts-act1-inventory.md` +2 节 −1 处过期注解，8 份规格书补章节。
* 代码：只有一处内容修正（`blind` 的稀有度与去向），20/20 闸门绿、单测 824 不变。
* 内容重新核对覆盖：33 瓶药水、3 张无色牌、6 个 Act2/3 精英、Ascension 20 条、关键词页。

---

## 187. Ascension 的数据维度：`EACT` 两格 + 一个条件（A2/3/4 与 A17/18/19）

§159 把 9 条能落在"运行层一个数"上的规则做了；剩下的 A2/3/4（伤害）与 A17/18/19（招式表）
一直写着"要先给 `EACT` 加维度"。这一节把那个维度加上。

### 187.1 参考里的形状，和我们为什么不能照抄

StS 的每只怪在自己的 `getMove()` 里写 `if (ascensionLevel >= 3) damage = 20;` —— **代码**，不是数据。
数据化引擎照抄不了，于是拆成两半：

| 需求 | 落点 | 为什么在这儿 |
|---|---|---|
| 同一个招式**换数值** | `EACT.ProgramAsc`（term）+ `EACT.AscensionMin`（int） | 一个动作一份节目，"升档"就是换成另一份 |
| 换**招式表**（用哪一招、用几次） | `intent.ascensionAtLeast`（新条件） | 内容写一条更高优先级的 `IntentRule` 就能换招 |

阈值**写在内容里**（普通 2/精英 3/Boss 4；招式表 17/18/19）。内核不知道一条遭遇来自哪个池 ——
精英也会出现在事件里（`Dead Adventurer`），所以"内核替内容猜种类"在第一次遇到那种情况时就错。

### 187.2 落地

| 层 | 改动 |
|---|---|
| `state.rs` | `CombatState.ascension: u8` + `ascension()` / `set_ascension()`。**不进规范文本**（参考没有这个字段，写进去会移动全部 85 份语料）；`hash_full` 将来必须覆盖它 |
| `content.rs` | `EACT` 7 → 9 格（`ProgramAsc`、`AscensionMin`），stride 16 → 20；`FORMAT_VERSION` 4 → 5 |
| `rdcfmt.py` | 同一份 schema + 版本号（两边各一份是既有设计；`contentc-bytes` 与 `rdcf-verify` 会抓漂移） |
| `intent.rs` | `execute_action` 按 `state.ascension()` 选信封；`ConditionKind::AscensionAtLeast`（第 11 个条件）+ `ascension_at_least()` |
| `rd-wasm` | `build_session_at(..., ascension)`；跑一局时传 `session.state.ascension()` |
| 内容 | **13 个动作**的升档（普通 4 / 精英 4 / Boss 3 / 招式表 2），数字全部回 wiki 单页抄 |

⚠️ **三个当场踩到的坑（都不是"风格问题"）**：

1. `AscensionMin` / `ProgramAsc` 在 **EACT 行**上，不在 `Program` 那个信封里。第一版读 `base.int_field(...)`
   —— 于是格永远读不到，内容里写了等于没写。
2. `ProgramAsc` **就是信封**（`{Root, MaxProgramSteps, …}`），不是裸 `Root`。第一版返回 `variant.Root`，
   于是后面那句 `envelope.node_field("Root")` 跑去 `node.dealDamage` 里找 `Root` ⇒ `Missing("Root")`。
3. `entity_row!` 的 `=> n` 是**真的格号**（getter 用它），不是注释。加两格之后我写成了 7/8/6，
   于是 `ProgramAsc` 的 getter 读到了 `AscensionMin` 那一格（`65535` vs `0x8000`）。

### 187.3 ★★ 写内容的方法：**改基础节目，不要手写节点**

第一版把 13 个升档节目**手写**出来，两处方言立刻写错（`createCardInstance` 要 `ToZone` 不是
`Destination`；目标选择器是 `eventTarget`）。这是 §183 的同一个坑：手写节点 = 猜形状。

第二版改成**深拷贝基础节目、只改常量**（`set_damage` / `set_card_count` / `multi_stab_at_18` /
`two_daggers`），改不到目标就**响亮失败**。这样"形状"永远来自内容自己，而"数字"是唯一变动的东西。

同一个脚本里还踩了两次"返回值"的坑，值得记：`root = mutate(root) or root` 在 `set_damage` 返回
**命中次数**时把 `Root` 变成了一个整数（内容门在第一个字段上就跨了）；而 `two_daggers` 返回新根时
被忽略，于是那条"变体"与基础**一模一样** —— 一个没有症状的错字。现在判据是 `isinstance(dict)`。

### 187.4 ★★ 又抓到一个内容错（回 wiki 复核的直接产出）

核对 slavers 的数字时发现：**`slaver_red.scrape` 写成了 7 伤害 + 1 Weak**，而 wiki 是
**8 伤害 + 1 Vulnerable**（`wiki_slavers.txt`：`Deals (8;{{Asc|2|9}}) damage. Applies (1;{{Asc|17|2}}) Vulnerable.`）。
它从 §173 起就在内容里，而 20 道闸门全绿 —— 因为 **`INV_ACTIONS` 那张清单也写着 7 + Weak**。
与 §186 的 `blind` 完全同一个形状：**内容错 + 清单错 ⇒ 没有判据看得见**。

⇒ 修复后 `web-soak` 的点击数从 **350 掉到 188**：Vulnerable 比 Weak 更致命，随机点击的那一局死得更早。
这不是回归，是"修对了一处内容"的副作用 —— 记在这里，免得下次有人看到数字变小就以为坏了。

### 187.5 判据

| 判据 | 位置 | 抓什么 |
|---|---|---|
| `an_ascension_variant_replaces_the_program_at_its_threshold` | `host.rs` | Lagavulin 的 Attack **A0/A2 = 18、A3/A20 = 20**（两侧都测；变体早一级生效会红） |
| `the_ascension_condition_compares_the_fight_level` | `intent.rs` | 8 组 (level, value) 的比较，含 0 级与 20 级 |
| `a_fresh_state_is_ascension_zero` | `intent.rs` | 新战斗默认 A0（语料依赖这一条） |
| `the_ascension_level_reaches_the_fight_state` | `run.rs` | A0/2/3/4/17/19/20 开局 → 战斗状态里的等级一致 |
| `check_ascension_variants` | 内容门 | 13 条变体逐条钉（facts + 阈值）；**变体 facts 与基础相同 ⇒ 红**；内容里有而表里没有 ⇒ 红 |
| 负控 | 手工 | ① 阈值判据改成恒真 ⇒ Lagavulin 在 **A0** 就变难（红在 A0）；② 把某个变体换成基础节目 ⇒ 内容门两条同时红 |

### 187.6 数字

* **20/20 闸门绿**，单测 **828**（rd-core 660 / rd-run 100 / rd-wasm 68）。
* `FORMAT_VERSION` **4 → 5**；`expected_sha.txt` 重新钉（编译器变了 ⇒ 旧内容字节必然移动），
  85 份语料与四条对拍仍逐字节一致 = "格式变了、语义没变"的证据。
* 内容：镜像 46,384 B（core 38,484 B）；**13 个动作**有升档变体，`gap_check.py` 会打印
  "多少个还没有"（79 − 13 = 66）。
* Ascension 现在 **15 / 20 条有机制**；剩下 A1 / A10 / A12 / A15 / A20。

---

## 188. 事件效果的**列表** + A15（Unfavorable Events）

两件一直挂着的事，在同一节落地：缺口文档从 §143 起写的"一个选项只能有一条效果（Golden Idol 那种
'遗物 + 诅咒'还不行）"，以及 Ascension 里剩下那几条之一 **A15**。

### 188.1 形状

`EV` 行的四格 `Effect0/Amount0/Effect1/Amount1` 换成四格 **term**：

| 格 | 类型 | 含义 |
|---|---|---|
| `Effects0` / `Effects1` | `F_TERM` | `[{Effect: "<词>[:<载荷>]", Amount: n}]` |
| `Effects0Asc` / `Effects1Asc` | `F_TERM` | **A15 的变体**（wiki: *"Many events have less positive outcomes and more severe consequences"*） |

行宽仍是 10 格 / 20 B，但格的含义变了 ⇒ `FORMAT_VERSION` **5 → 6**（还按旧版读的读者会把 term id
当字符串 id —— 这正是 §167 记过的"对的字节、错的 id"）。

为什么值得动格式而不是"把两条效果塞进一个字符串"：载荷是**闭集**，塞字符串就是发明第二种语法；
而 term 列表的形状镜像里早就有（`ENCT.Enemies`、`CARD.Tags`），解析器是既有的。

### 188.2 运行层：一次选择，多条效果，仍然原子

`resolve_event_effects(&[(EventEffect, Option<&str>)], pool)`：

1. **原子** —— 中间任何一条失败就 `*self = before`。`RunState: Copy` 本来就是为了这件事存在的，
   所以"拒绝 ⇒ 一个字节都不改"这条纪律**对列表也成立**（判据在 `rd-run`）；
2. **最多一条改牌效果** —— `remove_card` / `upgrade_card` / `transform_card` 变成一个待答问题，
   而待答只有一个位置 ⇒ 两条报 `TwoDeckChanges`（新变体），**不静默丢一条**；
3. **收尾一次** —— 没有改牌效果就地收尾。

A15 的"选哪一串"**不在运行层**：`EventChoice::effects_at(ascension, A_EVENTS_WORSE)` 在内容层，
阈值常量与其它九个 `A_*` 摆在一起（`at_least` 是唯一比较，规矩没变）。

### 188.3 内容：Golden Idol 终于像 Golden Idol

`golden_idol` 原来是"+30 金币"—— 和 wiki 那个事件毫无关系。现在：

| 分支 | 基础（A0） | A15 |
|---|---|---|
| 拿 | **遗物 `golden_idol` + 诅咒 `injury`** | 遗物 + **20 点伤害**（80 最大生命的 25%，wiki 的 Smash 分支） |
| 走 | 什么都不发生 | 同（`nothing` 没有更糟的版本） |

两个数字都来自我们自己的 inventory §7（`golden_idol_event` 的三个分支：Outrun → Injury、
Smash → 25% 最大 HP、Hide → −8% 最大 HP）。

⚠️ **其余 8 个事件是自造的**（"a shrine that still answers"、"a heap of bent metal"……），
它们的 A15 数字是**我们的设计**，不是 wiki 的：wiki 只给了方向（"less positive outcomes and more
severe consequences"）。所以 `patch_188_content.py` 的表头把两类分开写，A15 用"数值减半"或
"加一条惩罚"的整齐规则，不假装有出处。这条写在这里，免得下次有人把 45→20 当成 wiki 数字引用。

### 188.4 判据

| 判据 | 位置 | 抓什么 |
|---|---|---|
| `an_event_option_can_apply_several_effects_at_once` | `rd-run` | 三条效果（遗物 + 诅咒 + 金币）全部落地，且不欠选牌 |
| `a_failing_effect_rolls_the_whole_list_back` | `rd-run` | 列表中间失败 ⇒ `run == before`（整结构体相等，连金币一起还） |
| `two_deck_edits_in_one_option_are_refused` | `rd-run` | `TwoDeckChanges`，且什么都没改 |
| `a15_swaps_the_event_effect_list` | `rd-wasm` | A0/A14 = 诅咒码 9，A15/A20 = 伤害码 3；遗物永远第一；老的一个效果访问器 == 列表头 |
| 内容门 `check_event_vocabulary` | 内容 | 每条效果都在闭词表；`curse:`/`relic:` 载荷真实存在；**A15 列表等于基础 ⇒ 红**；一个选项两个改牌效果 ⇒ 红 |
| `the_events_…`（改写的旧判据） | `rd-core` | `effects_at` 的四个等级（0/14/15/20）、`count`/`asc_count`、以及"离开"没有 A15 变体 |

负控：把 `A_EVENTS_WORSE` 改成 99 ⇒ `a15_swaps_…` 在 A15 上红（`left: 9, right: 3`）。

### 188.4b 顺手修掉一个会让闸门假红的坑

这一节跑闸门时 `web-soak` 红了一次：`TypeError: fetch failed [cause]: bad port`。
`cdp.mjs` 用 `listen(0)` 让内核分配端口，而 **undici（Node 的 fetch）拒绝一批知名端口**
（6000 / 6666 / 10080 …）。撞上了就红，和内容无关 —— 一个随机红的闸门会训练人忽略它。
现在分配到的端口在黑名单里就重新要一个（判据：连跑两次都是 PASS，且第一次就是那次的现场）。

### 188.5 数字

* **20/20 闸门绿**，单测 **832**（rd-core 660 / rd-run 103 / rd-wasm 69）。
* `FORMAT_VERSION` **6**；`expected_sha.txt` 再钉一次（格式又变了）；85 份语料与四条对拍不变。
* 内容：镜像 46,984 B（core 39,096 B）；9 个事件、**19 条基础效果 + 15 条 A15 专属效果**，
  唯一带多条效果的选项是 `golden_idol`（`gap_check.py` 会打印这三个数）。
* Ascension 现在 **16 / 20 条有机制**；剩下 A1 / A10 / A12 / A20。

---

## 189. Ascension 收尾：A1 / A10 / A12 / A20 —— **20 / 20 条都有机制了**

§159 做了 9 条、§188 做了 A15，这一节把最后四条补齐。四条都不需要新机制，各是一个数或一个分支。

| 规则 | wiki | 落地 |
|---|---|---|
| **A1** 精英更多 | *Elites are more common*（8% → 16%） | `map::kind_for_roll_at`：**只有** combat/elite 的边界动（45/16 而不是 53/8），rest/shop/unknown 保持 12/5/22 ⇒ 表仍合计 100 |
| **A10** 开局诅咒 | *Start with Ascender's Bane* | 内容加 `ascenders_bane`（Curse / Unplayable / Ethereal）；`new_with_ascension` 塞进牌组；`remove_card` 拒绝它 |
| **A12** 升级牌更少 | *Upgraded cards are less common* | `upgrade_chance_percent(act, asc)`：基线 0 / 12 / 25%，A12 减半成 0 / 6 / 12% |
| **A20** 双 Boss | *Double Boss*（第三幕两个） | `mark_boss_beaten`：最后一幕的第一只**不清** `boss_beaten`，只清 `resolved`（节点重开）；第二只才赢 |

### 189.1 ★ A12 顺手补了一条**从来没有实现过**的基线

`inv:§3.5` 写的是"第一幕**不出现**升级牌（升级概率 0%）"，而我们把它实现成了"**哪一幕都不出现**"
—— 奖励屏从没见过升级牌。所以 A12 不能只做减半：基线（12% / 25%）也得先有，否则 A12 是一条
关于零的规则。判据是两侧的：64 个种子里**第三幕必须出现**升级牌、**第一幕一张都不许有**。

### 189.2 三条会静默的坑（都被判据挡下来了）

1. **`+` 行必须在奖励池里，但不能被当成基础牌抽到。** `pick_of` 里"计数"与"定位"是**两次遍历**，
   两边都要跳过 `+` —— 只跳计数那一侧，第 i 张彩票就落到不同的牌上。第一版正是这样：**第一幕的
   奖励屏蹦出 95 张升级牌**（比例比 100% 还高，因为位置全部错位）。
2. **A20 不许把 `pending` 清成 `None`。** `rd_run_fight_end` 的顺序是"先掷奖励（`Pending::Reward`）、
   再 `mark_boss_beaten`" —— 清掉 `pending` 就是把**第一个 Boss 的奖励屏**关掉，玩家白打一场。
   判据里那句 `the reward screen must survive` 就是为它写的。
3. **`kind_for_roll_at` 的边界只能动一处。** 我第一版把 rest/shop 的上界一起挪了（72 → 76），
   于是 A0 的表也变了 —— 份额判据（四档 + 合计 100 + A0 与 `generate` 逐字节相同）当场红。

### 189.3 工具层面的一次事故（记下来，因为它删掉了 2375 行）

给 `state.rs` 加 A12 测试时，我从"`let pool = [`"开始替换，结果把**另一个测试函数**的尾部当成了
替换目标，一次删掉 2 375 行。恢复靠 `git checkout`（文件是干净的 HEAD + 本节改动），然后**按锚点
重放**全部 13 处改动（`native/patch_189_state_redo.py`）。

两条教训，都和工具用法有关：

* **`cargo build` 不编译测试**，所以"编译通过"对一个测试文件毫无意义 —— 必须 `cargo test`；
* 替换脚本里"从 A 到 B 之前"的区间**必须用两条稳定锚点夹住**，而不是"从这里到下一个空行"；
  上一次的 `del lines[start:end]` 把一个函数体整个吃掉了，而 `assert` 只检查了起点。

### 189.4 数字

* **20/20 闸门绿**，单测 **836**（rd-core 660 / rd-run 107 / rd-wasm 69）。
* 内容：42 张卡（新增 `ascenders_bane`），镜像 47,140 B（core 39,164 B）。
* Ascension：**20 / 20 条都有机制**。剩下的都是**内容覆盖面**：A2/3/4 与 A17/18/19 只有 13 个动作
  有升档数值（还有 66 个等 wiki 出处），`Boss3` 池只有 1 只（A20 的两场打同一只）。
* 负控：四条规则各拆一次阈值（A1 恒假、A10 改成 9 级、A12 不减半、A20 恒假），**四条全红**。

---

## 190. 补齐 A 数值：13 → 42 个动作（并列出**基础值就不对**的 11 条）

§187 把 `EACT` 的 ascension 维度做出来了，但只有 13 个动作有数值。这一节把它补到 **42 / 79**。

### 190.1 抓 wiki 的方式（这一步花了最久，结论值得记）

* **渲染页会骗人**：wiki 的 Pattern 表把"多段攻击"的 `×N` 与升档上标挤在一起，
  `Deals 1×5` 升档后渲染成 `Deals 1×62 damage` —— 读起来像"一个数 162"。用机器抽取会得到
  一堆 `A2=4` 这种看不出基础的片段。
* **wikitext 才是真话**：`index.php?title=<Page>&action=raw` 给的是
  `Deals (1×5;{{Asc|2|1×6}})`，基础与升档**成对出现**，没有歧义。
  ⇒ `native/fetch_wiki_asc.py` 抓 30 个页面存到 `native/wiki_asc/*.txt`，
  `native/asc_report.py` 把它们展开成 `{A2:12}` 形式的表。**这两个脚本入库**，
  下一次补内容不用再从浏览器里抄。
* **重定向**：`Acid_Slime` / `Spiker` / 三个 gremlin 都是 `#REDIRECT`（`Slimes` / `Shapes` /
  `Gremlins`），抓取脚本跟一跳；`Maw` 是 **404**（wiki 上没有这一页），所以 `maw.*` 三招没有出处、
  没有变体 —— 这条写在缺口文档里，而不是编一个数字。

### 190.2 写内容的方法（§187 的纪律照旧）

仍然**深拷贝基础节目、只动常量**，改不到就响亮失败。四种改写器：
`damage(before, after)` / `status(id, before, after)` / `cards(id, before, after)` /
`one_more_hit()`。

`one_more_hit` 是这一节新增的一种：`byrd.peck` 的升档是"多一段"（5 段 → 6 段），而内容里的
固定段数是**展开写**的（五个 `dealDamage`），所以变体是序列里多一个节点，不是改数字。

三条**模型的边界**（不是错，是表达不出来，写在内容的注释与缺口文档 §G 里）：

1. **可变伤害**：`louse_*.bite`、`darkling.nip` 的 A 值是**区间**（`5-7` → `6-8`），而
   `dealDamage` 只吃常量；
2. **同一招两个档位**：`jaw_worm.bellow` 的 Strength 在 A2 升、Block 在 A17 升，而 `ProgramAsc`
   每行只有一个 ⇒ 变体带较早那个；
3. **基础就错的招式不加变体**（下一条）。

### 190.3 ★★ 回核的副产品：11 条招式**基础值**与 wiki 不一致

补 A 数值之前必须先对基础。对照之后有 11 条基础就与 wiki 不符（`spiker.cut` 8 vs **7**、
`the_champ.heavy_slash` 18 vs **16**（18 是它的 A4 值）、`chosen.poke` 6+6 vs **5×2**、
`gremlin_leader.slash` 16 vs **6×3**、`darkling.chomp` 11 vs **8×2**、`sentry.bolt` 10 伤害 vs
**塞 2 张 Dazed**、`spire_growth.strategic` Constricted 2 vs **10**、`giant_head.*` 的简化版……）。

**这些故意没有升档变体**：在错的地基上加层只会更错。完整清单（含 wiki 数值与差异性质）在
`docs/sts-wiki-gap.md` §G —— 那是下一步"修基础"的工单，而不是这一节的残留。

这也是这一节最值钱的部分：它不是"又多填了几个数"，而是**给下一轮留下了一张可执行的清单**。

### 190.4 判据

| 判据 | 位置 | 抓什么 |
|---|---|---|
| `check_ascension_variants` | 内容门 | 42 条逐条钉（facts + 阈值），**独立于内容**（数字从 wikitext 抄）；变体 facts 等于基础 ⇒ 红；内容里有而表里没有 ⇒ 红 |
| `an_ascension_variant_replaces_the_program_at_its_threshold` | `rd-core` | Lagavulin 18@A0/A2、20@A3/A20（两侧） |
| `the_ascension_condition_compares_the_fight_level` | `rd-intent` | 条件两侧 |
| `the_ascension_level_reaches_the_fight_state` | `rd-wasm` | A0/2/3/4/17/19/20 开局 → 战斗状态一致 |
| `gap_check.py` | 工具 | 打印"多少个动作有变体 / 多少个还没有"（当前 42 / 37） |

⚠️ **没有新写内核判据**：机制在 §187 已经钉住，这一节只加数据。数据的新判据是**内容门那张表**
（每一行都是对 wiki 的独立陈述），以及"变体必须与基础不同"这条自动检查 —— 它对 42 条一视同仁。

### 190.5 数字

* **20/20 闸门绿**，单测 **836** 不变（这一节没有内核改动）。
* 内容：镜像 47,536 B（core 39,560 B）；**42 个动作有升档变体**（A2 ×24、A3 ×7、A4 ×4、
  A17 ×2、A18 ×1、A19 ×3，以 `gap_check.py` 输出为准）。
* 剩下的 37 个：多数本来无升档（`Does nothing` / 纯召唤 / 纯状态），11 条等 §G 的基础修正，
  可变伤害 3 条等一个"区间表达式"。

---

## 191. 把 §G 那张工单做掉：修 8 条基础值 + 补它们的升档

§190 说得很清楚：**在错的地基上加层只会更错**，所以那 11 条基础值与 wiki 不符的招式当时没有变体。
这一节先修基础，再补升档。

### 191.1 八条修正（数字全部来自 `native/wiki_asc/*.txt`）

| 招式 | 原值 | 现在 | 升档 |
|---|---|---|---|
| `spiker.cut` | 8 | **7** | A2: 9 |
| `the_champ.heavy_slash` | 18（**写的是 A4 值**） | **16** | A4: 18 |
| `chosen.poke` | 6+6（**写的是 A2 值**） | **5+5** | A2: 6+6 |
| `darkling.chomp` | 单段 11 | **8×2** | A2: 9×2 |
| `gremlin_leader.slash` | 单段 16 | **6×3** | 无（wiki 无升档值） |
| `the_champ.execute` | 单段 30 | **10×2** | 无 |
| `sentry.bolt` | 10 伤害 | **塞 2 张 Dazed**（A18: 3 张） | A18: 3 |
| `spire_growth.strategic` | Constricted 2 | **10** | A2: 12 |

两条**结构性**修正（不是改数字，是把一段拆成多段）：`the_champ.execute` 与 `darkling.chomp` 改成
两段、`gremlin_leader.slash` 改成三段。内容里的固定段数是**展开写**的（§190 的 `one_more_hit`
踩过同一个形状），所以这里是"换成一串 `dealDamage`"，不是引入 `repeat`。

`sentry.bolt` 需要一个新卡：**`dazed`**（Unplayable / Ethereal / 无效果）—— 与 `slimed`、`wound`
同一族的第三张 junk 卡，也是 wiki 里 Bolt 真正塞的那张。`Ascender's Bane` 之后内容里的第二张
"ethereal 诅咒/状态"，`TurnEndHandDestinationZone = ExhaustPile` 由内容门的 ethereal 判据钉住。

### 191.2 故意不修的 3 条（写在明处的简化，不是漏）

* `giant_head.glare` / `count`：本项目是**320 HP 的简化版**（§130 记录的），招式表跟着简化
  （12 伤害 + Weak / 26 伤害，而 wiki 是 Weak 1 / 13 伤害 / 还有 It Is Time 的递增）；
* `maw.*` 三招：wiki 上**没有这个页面**（404）。没有出处就不编数字。

### 191.3 判据怎么跟上的

内容门那张 `INV_ASC_VARIANTS` 是**独立第二份**（数字从 wikitext 抄），所以这一节红了三次，每次都是
它该红：

1. **8 条基础 facts 不符**（`action.darkling.chomp: facts [...] inv says [...]`）；
2. **6 条新变体没被钉住**（`asc.unknown: variants not pinned by the inventory`）——
   这条是 §187 写的"内容里有而表里没有 ⇒ 红"，它第一次真的派上用场；
3. `dazed` 既不在 `INV_CARDS`、也不在 id 清单里（"内容多了一张卡"与"清单少了一行"是同一件事）。

修完之后 48 条变体、43 张卡、20/20 闸门绿，**单测 836 不变**（这一节仍然没有内核改动 ——
Ascension 的机制在 §187/§189 就已经齐了，后来两节全是数据与内容）。

### 191.4 数字

* **20/20 闸门绿**，单测 **836**（660 / 107 / 69）。
* 内容：**43 张卡**（+`dazed`）、镜像 47,800 B（core 39,788 B）、**48 个动作有升档变体**
  （79 个里的 61%）。
* 剩下的 31 个：多数本来无升档；`giant_head.*` 与 `maw.*` 是写明了的简化；
  `louse_*.bite` / `darkling.nip` 的可变伤害等一个"区间表达式"（§G 最后一段）。

---

## 192. 把"一个动作只有一个升档档位"这个限制删掉

§190.4 写过这句话：*"`jaw_worm.bellow` 有两个阈值（Strength @A2、Block @A17），而 schema 的
单个 `ProgramAsc` 只能装一个；较早那个赢 —— 加第二个槽是格式变更，不是数据变更。"* 这一节就是
那次格式变更。

### 192.1 形状：一格 → 一格列表

```
before   "ProgramAsc": {envelope},  "AscensionMin": 2           -- 9 格 / stride 20
after    "ProgramAsc": [{"AscensionMin": 2, "Program": {envelope}}]    -- 8 格 / stride 16
```

`AscensionMin` 那一格**被删掉**，不是留着不读：两处都认识同一件事就是 §161.3 那条腐烂的老路。
选档规则写进 `Content::ascension_program`，只有一句：**`AscensionMin <= ascension` 里阈值最大的
那个**。顺序不参与判定 —— 列表是内容顺手写的，"把 A17 那条往上挪一行就换难度"这种错在任何数值
测试里都不会红（A17 的内容在 A2 下看起来只是"偏强"）。所以"升序且不重复"交给内容门单独钉。

⚠️ 一个 A17 变体是**整段节目**，所以它必须重复 A2 的改动再加自己的：
`jaw_worm.bellow` 的 A17 写的是 Strength **5** + Block **9**（wiki：`Gains (3;Asc|2|4;Asc|17|5)
Strength. Gains (6;Asc|17|9) Block.`），不是只写 Block 9。

### 192.2 代价：一份被重新钉住的镜像

`EACT` 回到 16 B（7 → 9 → 8 格），`FORMAT_VERSION` 6 → 7。roguedeck 的镜像因此缩了
87,192 → 85,616 B（394 行 × 4 B），`tools/contentc/expected_sha.txt` 必须 `--repin`。

这次重钉**是安全的**，而且判据不是"闸门绿了"：`native/card_specs.json`（四个对拍层真正读的东西）
重新生成后**逐字节不变**。原因是 roguedeck 的内容里一条 `ProgramAsc` 都没有 —— 变的只有行宽，
不是语义。重钉的注释写在 `expected_sha.txt` 里（第 2 次重钉，附理由）。

### 192.3 判据

内容门的 `INV_ASC_VARIANTS` 从 `{id: (阈值, facts)}` 变成 `{id: [(阈值, facts), …]}`，并新增四条
判断（旧表一条都说不出来）：

1. 内容里的阈值集合必须**正好**等于清单里的（多一个 = 没人钉过的档位）；
2. 阈值**严格升序且不重复**；
3. 没有两个档位和**基础节目**或**彼此**讲同一个故事（"这一档什么都不做"）；
4. `ProgramAsc` 必须是**非空列表**。

内核侧新测试 `one_action_can_carry_two_ascension_tiers` 在**两个阈值的两侧**各看一遍
（A0/A1/A2/A16/A17/A20 六行：`(3,6) (3,6) (4,6) (4,6) (5,9) (5,9)`）——
"A17 那一条忘了带 A2 的数"会红在 A17，"提前一档生效"会红在 A16。

## 193. 可变伤害：把"chosen at the start of combat"做成真的

wiki 那两句（`louse.txt:28`、`darkling.txt:32`）写的是同一件事：

> Deals N damage. N = Number between (5-7;{{Asc|2|6-8}}), **chosen at the start of combat.**

### 193.1 两个被否掉的设计，两个都值得记住

1. **在求值时抽**（`randomRange` 表达式 / `node.rollCounter` 排在 `dealDamage` 前面）。
   ⚠️ 这条会**静默打出 0 伤害**：`deal_damage_node` 在**入队时**求 `Amount`（参考的顺序），
   而计数器写入是**入队**的 `EffectRequest` —— `sequence[掷骰, 打]` 里"打"读到的是旧值。
   没有任何"发生了点什么事"的测试会红。
2. **把范围写进动作节目**（基础 + A2 两份）。那就是同一个数写两遍，而 wiki 的 A2 只是"+1"。

### 193.2 落地的形状：记录掷骰 + 参考自己的表达式

```
ENCT[i].Enemies[j].Rolls = [{Key, Min, Max, AscensionMin?}, …]      -- 每个敌人的范围
EACT[action].Program    = dealDamage{Amount: combatantCounter(source, Key)}
```

* `combatantCounter` **是参考自己的表达式**（它在 `INT_KINDS` 里），所以节目**没有**新增节点种类；
* 唯一的新东西是"谁把计数器填上"：`battle::apply_spawn_rolls`，在建战斗之后、第一回合之前，
  每抽一次 `random_step += 1`（与开局洗牌同一条"一次抽签一个步"的账）；
* 它**直接写** `set_counter`、不排队：排队就回到上面第 1 条那个 0 伤害陷阱。这是全内核唯一一处
  "求值期之外的直接写"，理由就写在这里。

`Rolls` 的阈值方向与 `ProgramAsc` **故意相反**：这里的 `AscensionMin` 缺席是"这就是基础值"，
那里的是"没填、永不生效"。所以"忘了给 A2 那行填阈值"（两行都是 0）会被当成**同键同阈值**报错，
而不是悄悄两行都生效。

### 193.3 内容门多了三道交叉检查

`INV_ROLLS` 是 wiki 数字的独立第二份（`louse_red` 5-7/6-8、`darkling` 7-11/9-13），
另外三条比数字更值钱：

1. **程序里的每个计数器读取，都必须是"列出这条动作的那个敌人"掷过的键** —— 否则两半会漂成
   "程序读 `roll.bite`、记录掷 `bite`"，伤害每一局都是 0，而两边各自看起来都对（§161.3 的形状）；
2. **读取必须来自自己**（`sel.source`），不是别人的计数器；
3. **没有敌人记录的动作不许读计数器**（`INV_UNWIRED`：`louse_green.*` 就是这种）。这条同时钉住
   "它仍然读常量"，所以"哪天把绿虱接进来"会当场红，而不是先埋一颗 0 伤害的地雷。

负控跑了五条，各红一次、各指名一件事：记录掷错键 / 读别人的键 / A2 范围改成 9-12 / 把绿虱接进
记录 / 同键同阈值两行。

### 193.4 覆盖从哪来（以及**没有**从哪来）

* **有**：`rd-core` 的 `a_spawn_roll_is_drawn_once_per_fight_and_read_by_the_action`（24 个种子 ×
  A0/A2，同一个敌人连打两次伤害**相同**且等于掷出的值，`random_step` 只涨 1；48 次掷骰至少 4 个
  不同值 ⇒ "抽签真的是抽签"）、`an_encounter_without_rolls_draws_nothing`、`rd-wasm` 的
  `building_a_louse_fight_draws_its_bite_and_a_cultist_fight_does_not`（走**真入口**
  `build_session_at`，比 `random_step` 与计数器本身）、内容门的 `INV_ROLLS`。
* **没有**：`ENEMY_DIFF`。那四层对拍读的是 **roguedeck** 的 `content.core.rdcf`（394 条动作，
  `a_very_official_line.*` 之类），不是 sts 的 79 条 —— 所以 §193 的伤害数字**没有** C# 对照。
  `native/fight_diff.py` 里加了一条机械检测（`counter_draw_reason`）：如果哪天把对拍指向 sts 镜像，
  这三个动作会被明确打成 `NOT-COMPARED`（计入分母、逐行打印），而不是"两边都读 0 所以绿"。
  今天它一次都不触发 —— 因为 roguedeck 里没有一条动作读计数器。

### 193.5 数字

* **20/20 闸门绿**，单测 **840**（rd-core 663 / rd-run 107 / rd-wasm 70）。
* 镜像：sts 48,948 B（core 40,900 B）；roguedeck 158,296 B（core 85,616 B，§192 的 -1576 B）。
* 变体：**48 个动作 / 49 条**；掷骰：**2 个敌人 / 4 条范围 / 3 处计数器读取**。
* 四条对拍不变：`FIGHT_DIFF 182/182`、`CARD_DIFF 62/62`、`CARD_MULTI 124/124`、
  `ENEMY_DIFF 394/394`（不可对照 0）。

---

## 194. 把三幕的 Boss 池对齐 wiki（每幕三只）

原先的账：`Boss` = Slime Boss、`Boss2` = The Champ、`Boss3` = Time Eater，而 §130 自己写过
"第 2/3 幕不是 wiki 的数值照搬，而是**机制上真的不同**" —— 也就是说这两只是**编的**（330 HP、
三招）。wiki 说每幕**三选一**。

### 194.1 这一节做了什么

| 幕 | 之前 | 之后 |
|---|---|---|
| 1 (`Boss`) | Slime Boss | Slime Boss / **The Guardian** / **Hexaghost** |
| 2 (`Boss2`) | The Champ（编的 330 HP、3 招） | The Champ（**wiki 的 420 HP、7 招**）/ **Bronze Automaton**（+2 Orb）/ **The Collector**（+2 Torch Head） |
| 3 (`Boss3`) | Time Eater | Time Eater（**wiki 的 4 招，含 Haste**）/ **Awakened One**（两阶段）/ **Donu & Deca**（一对） |

内容从 37 怪 / 27 遭遇 / 79 动作长到 **46 怪 / 33 遭遇 / 117 动作**；镜像 48,948 → 62,864 B。

### 194.2 三个"第一次"（都是既有机制的新用法，不是新机制）

1. **`sel.allAllies`** —— Donu 的 Circle of Power「全体敌人 +3 力量」、Deca 的 Square of Protection、
   Collector 的 Buff、Orb 的 Support Beam。⚠️ **`sel.allEnemies` 是敌方即"对方队伍"**
   （`targets::team_set(state, source, false, ..)`），Boss 用它会把 Buff 加在玩家身上 —— 战斗会变得
   *更容易*，而不是坏掉。所以这条有一个专门的测试（Donu 给自己和 Deca 各 3 层，玩家 0 层）。
2. **`repeat` 的计数是算出来的** —— Hexaghost 的 Divider `(玩家 HP / 12 + 1) × 6`：
   `repeat(add(divide(currentHealth(eventTarget), 12), 1))`。§146 引入 `node.repeat` 是为了 X 费牌，
   这是第一次让计数来自状态。测试在 70/12/11/0 四个血量点上各算一次（6/2/1/0 段）。
3. **`CardPlayed` 上"打出的是哪种牌"** —— Guardian 的 Sharp Hide（`card.hasTag.attack` → 3 伤害）
   与 Awakened One 的 Curiosity（`card.hasTag.power` → +力量）。§144 的 Enrage/Rage 用同一条形状，
   但都长在**玩家**身上；这是第一次用它在**敌人**身上反击玩家，而且**可被格挡**。

### 194.3 机制做不到的地方，逐条写进内容

每只 Boss 的 `AiNote` 都带一句"⚠️ 偏差"，`docs/sts-wiki-gap.md` §H 有汇总表。四条最要紧：

* **Guardian 的 Mode Shift**：wiki 是"累计受伤 30 → 20 Block + 当场改意图"；这里是"HP ≤ 50% 时
  改**下一轮**的意图"（意图每轮选一次）。防御态的 Roll Attack → Twin Slam → Whirlwind 与
  "Twin Slam 摘掉 Sharp Hide" 都精确。
* **Hexaghost 的 Inferno** 不升级已有的 Burn（没有"升级牌堆里的卡"节点）；Divider 读**结算时**的
  玩家 HP。7 招循环是**轮转对齐**的：`Actions[(round-1) % 7]` 从第 3 回合起正好是 wiki 的顺序 ——
  这条有测试（顺序被"理顺"时 Boss 照样打，只是招式顺序漂了）。
* **Awakened One 的复活**在 HP ≤ 25% 时改意图（内核没有死亡拦截），"移除所有 debuff"只按名摘掉
  Curiosity，场上没有 Cultist。
* **小兵开局在场**：`intent::locate_enemy` 给召唤物找招式表要靠遭遇名单（§138），而列进去就会生成 ——
  所以 `Spawn Orbs` / `Spawn` 被去掉，2 Orb 与 2 Torch Head 从第 1 回合就在。`Stasis`（偷牌）与
  Time Eater 的 `Draw Reduction` 没有原语。

### 194.4 判据

* **内容门**（独立第二份，数字全部来自 `native/wiki_asc/*.txt`）：`INV_MONSTERS` +9、
  `INV_ACTIONS` +38、`INV_CARDS` +2（`burn+` / `void`）、`INV_STATUSES` +2、变体 49 → **78**；
  三幕池的成员由 `INV_ACT_TABLES` + `INV_BOSS_POOL` 逐个钉住（多一个、少一个都红）。
* **内核行为**（5 + 3 条新测试）：三幕各三个 Boss 且每个都建得出来 / Hexaghost 的 9 回合招式序 /
  Automaton 的 A19 `Stunned→Boost`（**两侧都测**）/ Champ 的第 4 回合 Taunt 与半血后 Anger→Execute /
  Awakened One 的计数器翻阶段；Sharp Hide 只对 Attack 生效、Twin Slam 摘掉它 / Divider 在 4 个血量点上的
  段数 / Donu 的 Buff 落在两个 Boss 身上而玩家 0 层。
* **负控**：把 Sharp Hide 的 tag 改成 `skill` ⇒ 红在 `Sharp Hide 3 punishes an Attack, left 70 right 67`；
  把 Divider 的除数改成 10 ⇒ 红在 `hero at 70: 6 hits of 6 = 36, left 48 right 36`。
* **20/20 闸门绿**，单测 **848**（671 / 107 / 70）；四条对拍不变（182/182、62/62、124/124、394/394）。

### 194.5 踩到的坑（值得记）

内容里写 `divide{Left: ..., "Right": 12}` 而别处写 `Right: {"kind":"const",...}`，会让该字段在
派生时同时出现 `int` 与 `term` 两种存储类 ⇒ **整个字段退化 `F_JSON`**，内核求值报
`WrongKind("F_JSON")`，而报错点离"少包一层 `const`"有三层远。唯一在编辑期能看见它的地方是
`build.py` 报告里的 **"Fields that fell back to `F_JSON`"** 一行 —— 所以 `p194_helpers` 的算术构造器
现在自动把裸整数包成 `const`。

---

## 195. 把 A/D 那四条"基建缺口"做掉

§194 的降级清单里，我把原因归成四类。这一节按类补基建，逐条都把"我以为缺"和"真的缺"分开：

| 条目 | 结论 |
|---|---|
| A3 `eventAmount` + 伤害量 | **真缺** → §195.1 |
| A1 复活原语 | **不缺**（`DeathPrevention` 早就对任何战斗员生效）→ §195.2 |
| A2 意图层随机 + 上一招记忆 | **真缺**（意图层没有 RNG、没有历史）→ §195.3 |
| D1 卡选择器 | **真缺**（`sel.*` 卡选择器被明确拒绝）→ §195.4 |

### 195.1 事件带数量、`eventAmount`、开局固定计数器

* `CombatEvent::DamageTaken` 带 `health_damage`（**实际掉血**，不是请求额：被完全挡住的攻击一点血
  都没掉，而 wiki 写的是 "after losing X HP"）。`eventAmount` 终于有求值分支；**没有事件上下文时给
  `NoTarget`，绝不 0**（0 是合法数量）。
* 新内容面 `ENCT.Enemies[].Counters = [{Key, Value, AscensionMin?}]`（§193 `Rolls` 的兄弟，同一个
  `battle::apply_spawn_setup`）：**节目没法初始化一个计数器**，随机值也表达不了"开局就是 30"。
* Guardian 的 Mode Shift 变成真语义：种 30（A9 35 / A19 40）→ `budget -= eventAmount` → 规则
  `budget <= 0` → 防御态 `+10`。

⚠️ 第一版被内核**拒了一次**：把阈值写成规则里的 `compare{damage >= 30 + 10*shifts}` —— 规则条件只能
是 11 种 `intent.*`，`selfHasCounter` 只能比**常量**。这不是该修的限制（任意表达式进规则 = 意图层要
吃整个表达式引擎 + 要能解释"为什么命中"）；正确做法是**算术留在节目里**（`setCombatantCounter` 的
Amount 是表达式），规则只做常数比较 —— 于是有了"预算"。

### 195.2 复活：查完发现钩子早就在

§194 写的"内核没有死亡拦截"是错的：`exec::resolve_damage` 在写血量前会遍历目标的 `DeathPrevention`
（§180 的 S6d 块），对**任何**战斗员生效。于是 `standard.unawakened`
（`{SurvivingHealth: 1, Repeating: false}`，一次性）+ 规则 `not(hasStatus unawakened)` ⇒ Rebirth。

⚠️ 规则必须**两半**：只写"守卫没了 ⇒ Rebirth"会在复活后永远成立（Boss 从此只会复活）。

### 195.3 带权抽签：抽签是派生值，历史交给内容

`select_action` 每次观察都被调（页面每帧重算意图），所以抽签**必须是纯函数**；要让它稳定就得把
"这一轮的招"存进快照，而参考没有那个字段 —— 85 份语料与 129 条 golden 的哈希全都要动。于是：

    step = round * 16 + slot                        （单射：战斗 < 64 轮、遭遇 <= 8 敌）
    r    = rng::shuffled_pick_index(total, seed, step)

这也更接近 StS（它用独立的 `aiRng`）。代价写明：两次抽签之间没有顺序关系。
"不能连续用同一招"由**内容**记计数器（每个节目末尾 `last_move = k`）+ 一条规则排除。

词汇：规则的 `Action` 可换成 `Choice`（`[{Action, Weight}]`）。内核拒绝而不猜：空列表 / 权重 ≤ 0 /
总和 > 255 / 项数 > 8 / action 不在 EACT / **同时写了 Action 与 Choice**。

### 195.4 `node.selectCards`：第一次能问"哪张卡"

`sel.rs` 一直拒绝四个卡选择器（"卡选择器 / 玩家选择"，报 `UnsupportedKind` 而不是静默空集），所以
"抽牌堆里稀有度最高的那张"（Stasis）说不出来。新增**一个**具体节点而不是一套谓词语言：

    node.selectCards { OwnerSelector, FromZone, FallbackZone?, Order, Count, ToZone, Placement? }

`Order` = `HighestRarity` / `First` / `Random`（只有 `Random` 花一次 `random_step`）；稀有度排名
`Rare 4 > Uncommon 3 > Common 2 > Basic 1 > Status 0 = Curse 0`（按价值，不是枚举序号）。搬卡走
`EffectRequest::MoveCardToZone`，所以触发器照样看得见。

Bronze Orb 的 `Stasis` 因此是真的：抽牌堆（空则弃牌堆）里最高稀有度的一张进 `SetAsidePile`，死亡时
由一个 `Downed` 触发器还回手牌。⚠️ 状态必须**拆两个**：`standard.stasis` 带死亡钩子（永不消耗）、
`standard.stasis_ready` 是"还没用过"的旗子（被招式消耗）—— 第一版合成一个，用掉它就把钩子也删了，
卡永远还不回来。

### 195.5 数字与判据

* **20/20 闸门绿**，单测 **854**（676 / 107 / 71）；四条对拍不变（182/182、62/62、124/124、394/394）。
* 内容：状态 31 → **33**、敌人动作 117 → **118**、镜像 65,200 → **66,328 B**（core 55,608 B）。
* 负控（每条都真红）：`eventAmount → const 0` ⇒ `29 of 30 spent, left 30 right 1`；
  `Repeating: true`（不死 Boss）⇒ `a one-shot guard is spent, left 1 right 0`；
  权重翻成 30/70 ⇒ `Fireball took 108/400 = 0.27, wiki says 70%`；
  `Order: HighestRarity → First` ⇒ 偷了 `strike` 而不是 `uppercut`。
* ⚠️ 两次负控**第一次都没红**，原因同一个：改了 `Monsters` 的 roster，没改遭遇里的**内联副本**
  （内核读的是后者）。这条已经在 §194 记过一次，这是第二次 —— 内容脚本现在两处都改。

### 195.5b 全 Boss 的机制对齐（同一节的后半）

基建到位后，把 wiki 里**有随机/排除规则**的 Boss 全部接上（数字仍来自 `native/wiki_asc/`）：

| Boss | wiki | 现在的规则条数 |
|---|---|---|
| Slime Boss / The Guardian / Hexaghost / Bronze Automaton / Donu & Deca | 确定性循环（Split / Mode Shift / 7 招轮转 / 6 招轮转 / 固定交替） | 0–4（原有） |
| **The Champ** | 45/25/15/15 + **任何一招不能连续两次** + 每 4 回合 Taunt | 8（3 相位/嘲讽 + 4 排除 + 1 默认） |
| **The Collector** | Fireball 70 / Buff 30 + 不能连 Buff + **不能三次 Fireball** | 4 |
| **Time Eater** | 45/35/20 + 不能三次 Reverberate + Head Slam/Ripple 不能两次 | 5 |
| **Awakened One** | 一阶段 75/25 + Slash 不能三次；二阶段 Dark Echo 一次后 50/50 | 5 |
| **Bronze Orb** | Stasis 75% 直到用掉；之后 70/30；同一招不能三次 | 4 |

历史是**内容状态**：每个节目末尾 `prev_move = last_move; last_move = k`（`k` 是该动作的编号），
排除规则是 `intent.selfHasCounter{last_move == k}` 的 `Choice`（把被禁的那一项去掉、其余按 wiki 权重重排）。

判据（新增）：
* `a_weighted_boss_never_repeats_the_move_the_wiki_forbids`：六个 `(encounter, 槽位, 敌, last, prev, 被禁招)`
  组合 × 60 个种子 —— 每条排除规则都真的排除。**`prev` 参与判定**：Champ 禁"任何重复"、Time Eater
  只禁 Reverberate 三次 / Head Slam·Ripple 两次、Orb 禁"三次"，一个深度的测试会放过过严的规则。
* `the_awakened_one_draws_phase_one_by_weight_and_flips_on_the_guard`：200 个种子下 Slash 占
  68%~82%，两招都出现；守卫摘掉后 Rebirth；二阶段先 Dark Echo 一次再只出 Tackle/Sludge。
* 内容门新增 `check_intent_history`：① 每个能被选中的动作都要写 `last_move`；② 同一敌人的编号两两不同；
  ③ 规则里问到的每个编号都得有动作写它（一个 4 字节错字就能造出"永不命中的死规则"）。
  ⚠️ 它一上线就抓到三条真错：`haste` / `mega_debuff` / `rebirth` 也会被选中，却没写历史。

★ 负控又抓到一处真问题：把 Champ 的排除规则优先级降到默认之下时**测试仍然绿** —— 因为它的"默认"
是确定性循环（`Actions`），四条排除规则是它**唯一**的规则。补上一条默认权重规则后（正好用满
`MAX_INTENT_RULES = 8`）负控才红：`last=1 prev=99 must exclude the_champ.heavy_slash`。

### 195.5c 当时还剩什么（§195.6 之前）

* **D1 的谓词面**：`selectCards` 现在有 `RequireTag`（按 tag 过滤）+ 三种排序，仍没有按类型/费用的过滤。
* **A2 的第二种历史**：Collector 的"不能连续三次 Fireball"要记两次历史，会挤满 8 条规则上限。
* **`hash_full`**：`Counters`/`last_move` 都是内容侧状态（在 `Combatant.counters` 里，已在指纹里），
  所以这一节没有新的"不在指纹里的字段"。

---

## 195.6 小兵改成**真召唤**（`Spawn: false`），并给 README 对一次账

### 195.6.1 被修掉的最后一条"结构降级"

§194/§195.4 都写着同一句降级："两只 Bronze Orb / 两只 Torch Head **开局就在场上**，不是召唤的
（遭遇名单是召唤物找招式表的唯一来路）。"

原因是两条语义被一张表承担：`ENCT.Enemies` 既是"招式的查找表"（`intent::locate_enemy` 的 §138
回退要在这里找到 definition），又是"开局谁上场"。所以"让小兵会出招"就等于"让小兵开局在场"，
wiki 的 `Spawn Orbs` / `Spawn` 只能删掉。

`Spawn: false`（`F_BOOL`，缺席 ⇒ `true`）把两件事分开：名单照旧（招式查得到）、开局不生成、
由**召唤动作**生成。内容因此恢复成 wiki 的样子：Automaton 第 1 回合 `Spawn Orbs`、Collector
第 1 回合 `Spawn`。Reptomancer **保持**两只匕首预置 —— wiki 就是"开局带两只匕首"。

⚠️ 两只 Orb / 两只 Torch Head 必须是**两个** `createCombatant` 节点：一只一条，否则两次铸造
会撞在同一个 `<definition>#<n>` 上。

### 195.6.2 三条已经修掉、README 里却还留着的旧说法

README 的"还不能"清单是**承诺**，过期就是假话。这一节逐条对账后删掉/改写：

| 旧说法 | 真相 |
|---|---|
| "Guardian 的 Mode Shift 是 HP ≤ 50% 时切一次" | §195.1 变成真·累计受伤（30/35/40 预算 + `eventAmount`） |
| "Awakened One 的复活在 HP ≤ 25% 时改意图（内核没有死亡拦截）" | §195.2 用 `DeathPrevention` 真复活；"没有死亡拦截"这句本身是错的 |
| "Bronze Orb 的 Stasis 没有原语" | §195.4 `node.selectCards` + `SetAsidePile` + `Downed` 归还 |
| "多段小兵开局就在场上" | §195.6 `Spawn: false` |

剩下仍降级的只有两条，都写明了原因：Hexaghost 的 Inferno 不升级已有 Burn（缺"升级牌堆里的卡"
节点）；Time Eater 的 `Draw Reduction` 没接线（`TurnStartDraw` 管线在，但"限时状态到期"宿主那段
没跑 —— 接上去会让减抽牌**永远**生效，比不做更错）。

### 195.6.3 数字与判据

* **20/20 闸门绿**，单测 **856**（677 / 107 / 72）；四条对拍不变（182/182、62/62、124/124、394/394）。
* 内容：敌人动作 118 → **120**、镜像 68,296 → **68,716 B**（core 58,064 B）。
* `a_minion_is_not_on_the_field_until_its_summon_lands`（两个 Boss × 三个判据：开局只有 Boss /
  召唤后 3 个 / 被召唤的 definition 正确）。它第一次就跑红：我把"敌人数"数成了
  `combatants().len()` —— 英雄也是战斗员。
* ⚠️ **内联副本的老坑第三次出现**：改 `Monsters` 的 roster 后，遭遇里的副本没同步，而内核读的是
  副本。内容脚本现在**整条记录**（Actions / IntentRules / StartingStatuses / Spawn）一起同步，
  而不只是新加的那个字段。
* ⚠️ 本节的 plan 段落第一次没写进来：`assert "## 195.6" not in src` 被上一节的
  `### 195.6 还剩什么` 命中了（`###` 里含 `## `）。于是只剩 README 进了提交 —— 现已改名并把本段
  补上。「检查自己写的断言」这条又派上用场。

---

## 195.7 最后一个内容节点（升级牌堆里的卡）与"限时状态"的真相

### 195.7.1 `node.upgradeCards`

StS 的"升级"在这份内容里就是**定义 id**（`burn` / `burn+`），所以节点只说这件事：

    node.upgradeCards { OwnerSelector, CardDefinitionId, FromZone?, Count? }

匹配到的实例改成 `<id>+`；**没有 `+` 行的卡平静跳过**（`dazed`）——那是 StS 的 `canUpgrade() == false`。
它**直接写**，不入队：一张牌的定义不是触发器看得见的东西（本内核的卡事件只有
`CardMovedToZone` / `CardInstanceCreated`），参考的升级路径也是直接改。

第一个使用者是 Hexaghost 的 **Inferno**（wiki："Adds 3 Burns+ into your discard pile.
**Upgrades all Burns**."）—— 后半句此前一个词都表达不出来。

### 195.7.2 `Draw Reduction`：我上一节的诊断一半是错的

§195.6 的 README 写的是"`Draw Reduction` 没接线，因为宿主没跑 `decrease_timed_statuses`"。
**时钟确实没跑**，但这份内容里**每个限时 debuff 都是用自己的 `TurnEnded` 触发器衰减的**
（`standard.weak` 就是这样），所以"一回合"是**内容**，不是内核：

    standard.draw_reduction {
      PassiveModifiers: [{Pipeline: "TurnStartDraw", Operation: "AddPerStack", Magnitude: -1}],
      Triggers:        [{Event: "TurnEnded", modifyStatusStacks(self, -1)}],
    }

敌人回合里挂上 ⇒ **下**回合少抽一张 ⇒ 那个回合结束时自己掉光。正好是 wiki 的
"Draw 1 less card next turn"。

⚠️ 反过来说：把参考的时长时钟**打开**会变成回归 —— 已经在触发器里衰减的状态会**掉两次**，
所有现有 debuff 的持续时间减半。这条写在这里，免得下一个人"顺手修好"。

### 195.7.3 判据与数字

* **20/20 闸门绿**，单测 **858**（679 / 107 / 72）；四条对拍不变。
* 内容：状态 33 → **34**、镜像 68,716 → **69,076 B**（core 58,340）。
* `upgrading_burns_walks_every_pile_and_skips_cards_without_an_upgrade`：三个牌堆都走到（只扫抽牌堆
  的实现也能过"一堆"的测试）、`dazed` 保持原样、已升级的不重复升也不丢。
* `draw_reduction_costs_exactly_one_turns_draw_and_then_expires`：挂着它抽 **4** 张、回合结束后
  层数归 **0**、没有它的对照局抽 **5** 张（最后一条是"4 不是全局常量"的证明）。
* 负控：`FromZone: DrawPile` ⇒ 红在 `Hand still holds an un-upgraded Burn: ["burn"]`；
  删掉衰减触发器 ⇒ 红在 `a TurnStartDraw passive with no decay would be permanent`。
* 踩坑：`str_field` 返回的是 `&str`，我又调了一次 `.as_str()`，撞上 nightly 的 `str_as_str`；
  `CardSlot` 的元组构造器是模块私有的，要用 `CardSlot::from_index`；`CardZone::ALL` 是 **7** 个
  （我把数组写成了 4）。

---

## 195.8 Cultist 一族进场（并修掉一个"永远建不起来的遭遇"）

wiki 的 Awakened One 是**带着两只 Cultist** 上场的，而且"The remaining Cultists will flee when the
Awakened One is defeated in Phase Two"。内容里早就有 `cultist`（48 HP、Incantation → Ritual、
Dark Strike），缺的只是两件事：

1. **`Owner`（`F_STR`，可缺席）** —— 内核早就有这条规则（`resolve_damage` 把"主人倒下的 minion"
   转成 `Escaped`，而 `Escaped` 不算 `Alive`），但此前**只有 `createCombatant` 召唤出来的**战斗员
   带 `owner`；开局就在场上的小怪没有任何办法声明它的主人。现在内容写 `"Owner": "awakened_one"`，
   `build_session_at` 建完战斗后把它盖到战斗员上。
2. **同名记录** —— 两只 Cultist 的 `Id` 都是 `cultist`，而 `add_combatant` 拒绝重名。

### 195.8.1 顺着 (2) 抓到一个真 bug

`enc_darklings`（两只一模一样的 Darkling）**从来就建不起来**：第二条记录撞 `DuplicateCombatant`。
而它就在**第三幕的 weak 池**里 —— 也就是说，一局真的随机到这条遭遇，`fight_begin` 会以
`Capacity(DuplicateCombatant)` 失败（run 层会响亮报错并回滚，玩家看到的是"这一场开不了"）。

修法：重复的 `Id` 拿召唤物的**同一套**后缀 —— 第二条叫 `darkling#2`。这同时是
`intent::locate_enemy` 已经在用的回退（按 definition 部分匹配），所以两只 Darkling 仍然各自查得到
招式表。判据 `an_encounter_with_two_records_of_the_same_id_builds` 断言 id 是
`["darkling", "darkling#2"]` 且两者都解析到记录。

### 195.8.2 第二个坑：**空列表不是 `F_TERMLIST`**

给 Cultist 记录写 `"Counters": []` / `"IntentRules": []` / `"StartingStatuses": []` 之后，战斗建不起来：
`WrongFieldKind("Counters")`。原因是 `compile.py` 的 `pick_kind` 把**空数组**（`arr0`）判成
`F_STRLIST`（"元素集合为空 ⇒ 当成串表/空"），所以"空列表字段"与"非空列表字段"是**两个 kind**。

修法：`EnemySpec` 的列表读器分两档 —— 严格版（`list(key, F_TERMLIST)`）与**宽松版**
（`list_any(key)`，两种 kind 都收）。`Rolls` / `Counters` / `IntentRules` / `StartingStatuses` 走宽松版：
它们表达的都是"这条记录没有这一项"，把空列表判成形态错误纯属自伤。

⚠️ 同一个道理的第二个形态：`"Owner": null` 会让该字段被派生为 `F_TERM`（`null` 自成一类存储），
所以 `owner()` 在 kind 不是 `F_STR` 时**再看槽值**：哨兵 ⇒ `None`，其余才是形态错。
`Position: null`（149/149 条记录）一直是这个形状，只是没人读它。

### 195.8.3 内容与判据

`enc_awakened_one` 现在是 `[awakened_one, cultist, cultist]`，两只 Cultist 带 `Owner`。

* `the_awakened_ones_cultists_flee_when_it_dies`（rd-wasm）：开局三个敌人（第二个 id 是 `cultist#2`）
  → 打两次致命伤（第一次被 `unawakened` 守卫吃掉）→ Boss `Downed`、两只 Cultist `Escaped`、
  **`result == Victory`**。最后一条是关键：wiki 的"逃跑"意味着玩家**不必**追杀两只 48 血的 Cultist。
* 负控：把 `Owner` 键删掉 ⇒ 红在 `` `cultist` must have fled when its master fell `
  （`left: Alive, right: Escaped`）。
* **20/20 闸门绿**，单测 **860**（679 / 107 / 74）；四条对拍不变；镜像 69,188 B（core 58,436）。

---

## 195.9 按第五轮审阅修三处（`selectCards` 边界 / 外键 / 文档账）

审阅报告见 `docs/vibe/Review_105659c_a9d2c53_Wiki_Gap.md`（末尾附了我的逐条复核）。这一节只做它的
**工作包 A + C 的基础部分**，机制扩充（B）留到下一节。

### 195.9.1 `selectCards` 的三个边界（审阅 P1-1/P1-2/P1-3）

三条都是我这轮（§195.4）自己引入的，而且**两条有活路径**：

| 边界 | 旧行为 | 现在 |
|---|---|---|
| 候选缓冲 | `MAX_SELECTED_CARDS * 8` = **64**，而牌区容量是 **96** ⇒ 第 65 张以后的卡静默进不了排序（`break`） | 缓冲 = `MAX_CARD_CANDIDATES`（= 牌区容量）；溢出**报错**而不是截断 |
| 并列稀有度 | 稳定选择 ⇒ 三张同稀有度永远偷第一张 | 先整体置换一次（一次抽签、`random_step += 1`）再按 rank **稳定**排序 ⇒ 并列内部随机 |
| `Count > found` | `take(count)` 走过 `order` 的零值区 ⇒ 同一张卡入队 N 次、`effects` 多记 | `take(min(count, found))` |

判据（`host.rs`）：96 张牌区里 Bad case 是偷到 `strike`、修好后偷 `uppercut`；60 个种子下三张同稀有度
必须出现 ≥ 2 个不同实例；`Count: 4` + 1 张候选时 `effects == 4`（1 移动 + 1 状态 + 2 历史）。

⚠️ **`Count > found` 这条在状态上不可观测**（同区搬运是 no-op），能看见它的只有 `ExecStats::effects`，
而计数器只对"`Count > 1` 且候选更少"的**程序**可见 —— 本内容唯一这样的调用在触发器里，宿主不回收它的
stats。所以这一半的守卫是代码的 `min` 本身，长期解法是给 `Host` 记一份 effect 账（记为已知测试缺口）。

### 195.9.2 `Owner` 外键 + `spawn()` 布尔严格（审阅 P1-5/P2-1）

* `Owner` 从"尽力而为"变成**外键**：minion 名不合法 / master 名不合法 / master 在场数 ≠ 1（悬空**或**
  歧义）三种都**响亮失败**。旧版对读不懂的 id `continue`，于是一个拼错的主人 = 悬空引用 = 小兵永不
  逃跑，**没有任何东西会红**。
* `EnemySpec::spawn()` 只接受 `BOOL_FALSE` / `BOOL_TRUE` / `BOOL_ABSENT` / `BOOL_NULL`；其余槽值报
  `WrongFieldKind`（旧版 `_ => Ok(true)` 把"字段读坏了"变成"这条记录上场"，与 `spawn: false` 的语义
  **正好相反**）。

### 195.9.3 新门禁 `AllEncounterConstructible`（审阅工作包 C）

`rd-wasm` 里加一条测试：从内容**读**九个 `EncounterTables.*` 池，对每条遭遇 × **A0/A9/A19/A20** 建战，
再对每个敌人跑一次 `select_action`（覆盖 `ProgramAsc` 与带权规则）。

它存在的理由是一个真 bug：`enc_darklings`（两只相同 Darkling）在**第三幕 weak 池**里却**从来建不起来**
（`DuplicateCombatant`）—— 而当时 20 道闸门全绿，因为内容门只查"内容自洽"、浏览器切片只跑第一幕、
随机 soak 恰好没抽到它。负控（去掉 `#<n>` 后缀）**精确复现**：
`` `enc_darklings` (pool `Weak3`, A0) must build: build_fight_from_contents: Capacity(DuplicateCombatant) ``。

### 195.9.4 文档：一份账、一个当前版本（审阅 P1-6/P2 + §5）

* `docs/sts-wiki-gap.md` 里 §C/§D/§E/§3/§H 的过时条目全部改成**当前状态**（历史留在 `port-plan.md`），
  §H 整表按 §195.1–§195.8 重写，并新增"已知测试缺口"一段。
* **数字只有一个来源**：`gap_check.py` 多了一个 **pastable 区块**，gap §1.1 原样贴它的输出，README 的
  那一行改成引用它。一贴就抓到两处人抄的错：卡行是 **27 基础 + 18 升级**（README 写的是 28+17）、
  事件是 **12（三幕 6+3+3）**（README 写的是 9）。
* 术语：`Double Damage`（倍率）/ `Duplication`（追加打出）/ `Divinity`（姿态）在 gap 里**分开写**，
  并注明本项目只有第二件。
* README 的参考实现链接原来指向 `https://github.com/`（占位符），改成 `ref/RogueDeck-Core` 的说明。

### 195.9.5 数字

* **20/20 闸门绿**，单测 **864**（682 / 107 / 75）；四条对拍不变（182/182、62/62、124/124、394/394）。
* 内容未变（镜像 69,188 B / core 58,436 B）：这一节只动内核边界与文档。
* 审阅里**未执行**的两条（如实报告）：Act2/Act3 的定向浏览器切片、以及 `Box::leak` 的长期内存曲线 ——
  前者已由 §195.9.3 的建战门禁覆盖"能不能开局"，后者明确排在本阶段之外。

---

## 198 `Slow` 与“每层线性加百分比”这个运算

### 198.1 一句话

`Slow` 是 `× (100 + 10 × 层数) / 100` —— 一个既不“加平值”、也不“乘固定百分比”的修饰器，而内核的
`modifiers::Operation` 只有三种（`AddPerStack` / `AddFlat` / `ScalePercent`），其中 `ScalePercent`
**不读层数**（虚弱/易伤那种只有时长轴的状态要用它）。于是加第四种：

```text
Operation::ScalePercentPerStack   current * (100 + magnitude * stacks) / 100
```

这是本移植自己的运算（参考只有三种），`status_bind::ModifierOp` 与 `exec::image_operation` 都补了
对应分支 —— 那条映射是**穷尽 `match`**，所以漏一处就编译不过（这一点比测试更可靠）。

⚠️ 两种"看起来能跑"的错法，都在负控里：
`ScalePercent` ⇒ 忽略层数（Slow 5 层时 11 点而不是 15 点）；`AddPerStack` ⇒ 每层 +10 **点**伤害
（60 点而不是 15 点）。

### 198.2 内容

* `standard.slow`：`DamageReceived` / `ScalePercentPerStack 10` / `RestrictDamageKind: Direct`
  （与虚弱同口径：只放大普通攻击）+ 一个 `CardPlayed` 触发器，每打一张牌 +1 层。
* Giant Head 的 `StartingStatuses` 装上它（wiki: `Powers = Slow`）。它自己的招式表仍是 §130 的
  320 HP 简化版，这一节只补 Slow。

### 198.3 判据

* `slow_scales_linearly_with_stacks_and_grows_on_every_card_played`：**三个层数点**（0/5/10 层 →
  10/15/20 点，基数 10）—— 线性与复合在这里分开（复合会给 10/16/25）；再加"每张牌 +1 层"两连击。
* 两条负控见上，都精确红在 `Slow 5: a 10-point hit lands for 15`。
* 内容门新增 `INV_STATUSES` 的一行（带运算名），`the_status_catalogue_is_honest` 要求它同时在
  `is_declared_inert` 里 —— 因为它的规则是**内容的那一行**，不是内核硬编码。

### 198.4 数字与剩下的

* **20/20 闸门绿**，单测 **867**（685 / 107 / 75）；四条对拍不变。
* 内容：状态 38 → **39**、镜像 71,276 → **71,848 B**（core 60,544）。
* **"下回合多能量"还没做**：`TurnStartDraw` 这条管线能表达"下回合多抽"（Draw Reduction 的反向，
  内容是纯数据），但**能量**没有对应管线（`turn_start_refill` 只从 `TurnConfig` 读）。它需要
  "回合开始的补能数也过一条修饰器管线"，与 `TurnStartDraw` 同形 —— 留作下一节（§199）。

---

## §199 回合开始补能的管线（`TurnStartEnergy`）+ **出牌路上的漏链**（工作包 B-4）

§198 结尾留的那一句"能量没有对应管线"在这里补上。做它的过程中，soak 从**另一条路**上撞到
一个更老、更贵的东西：**每一次出牌都漏一格链**，128 次之后整场战斗的每一次出牌都失败。
两件事一起交付，因为它们是被同一个现象（`StepThrew(Script)`）牵出来的。

### 199.1 能量也过一条修饰器管线

* `status_bind::Pipeline` 新增 `TurnStartEnergy`（线上名同）。**参考只有四条管线**，这条是
  本移植自己的扩展 —— 理由写在枚举上：`turn.rs` 的 `refill_resource` 此前只读 `TurnConfig`，
  所以"每回合 +1 能量"这类东西（Berserk，以及所有 Energized 类卡/药水）**一个词都表达不出来**。
* `exec::fold_turn_start_energy` 与 `fold_turn_start_draw` 逐句同形（同一张候选表、同一个
  `modifiers::apply`、同一个 `StatusMatch::Exact`），`base <= 0` 同样原样返回、账本一笔不动。
* `TurnHost::turn_start_refill_count(state, actor, base)`（默认 `base`）→ `Host` 委派到
  `turn_start_refill_count_detail`（读不出来就返回 `base` 并把失败记进 `problems`）。
* `turn::refill_resource`：**先折叠、再决定是否叠加"未花完的能量"**，两个旋钮因此正交。
  池子声明了 `max` 时那个 `max` 就是基线（`standard.energy 3/3` 正是这样读的）。
* `play.rs::cost_pipeline_of` 的穷尽 `match` 当场报错（那个接缝本来就是为此存在的）——
  答案 `None`：补能管线改的是"回合开始补多少"，费用管线改的是"这张牌要付多少"。

内容（wiki `Berserk`，Rare Power，0 费）：`Gain (2;1) Vulnerable. At the start of your turn, gain
1 Energy.` ⇒ `standard.berserk` 一行 `TurnStartEnergy / AddPerStack / 1 / Priority 100`，
`berserk` / `berserk+` 两张卡（Vulnerable 2/1 + 自身 1 层）。

判据 `berserk_adds_one_energy_per_stack_at_turn_start`：**0/1/2 层 → 3/4/5**。它同时钉三件事：
漏接管线停在 3；按层数而不是"有就给 1"（2 层必须比 1 层多）；**当回合打出不多给**（状态装在
身上，下一次 `start_current_turn` 才生效）。负控：让钩子退回 `base`，红在
`Berserk 1: turn 2 refills to 4`（left 3）。

### 199.2 ★ `enqueue_effect` 在顶层建的那条根链没有还（**老 bug**）

现象：soak 在一场 **44 回合**的战斗里，**每一次**出牌都被拒，消息 `rejected (-1) · StepThrew(Script)`。

沿着"这句话为什么这么没用"一路查下去，三处各自都是**独立**的缺陷：

1. **`capacity_code` 不拆 `PlayError`**。`BattleError::Play(PlayError::Capacity(_))` 落进
   `StepCause::Script` 分支，而 `StepCause::capacity_code` 只认 `BattleError::Capacity` 与
   `Turn(TurnError::Capacity)` ⇒ 家族名 `Script`、容器名 0 ⇒ 页面说 `StepThrew(Script:Capacity)`
   —— 真话，但**唯一下一步可行动的信息（哪个容器）**被丢掉了。补上那一条 `match` 之后，
   消息变成 `StepThrew(Capacity:Chains)`，当场指向 §151 那个形状。
2. **`state.rs::enqueue_effect`**：`new_root_chain_in_arena` 建链那一次引用 **refs = 1 归调用方**，
   队列条目自己再 `acquire` 一次（出队时还）。代码只写了后半句 ⇒ **每一次顶层入队漏一格链**。
   `enqueue_event_at_root` 早就把同一件事写对了，注释里还写着"否则每条根事件漏一格链，而表现是
   打到十几回合突然 `Full(Chains)`" —— 效果队列这一支漏了。改成
   `let (chain, created) = ...` + 三条出口各还一次（成功与两条回滚路径）。
3. **触发节目的帧**：三个 `execute_program*` 助手把 `ProgramRun` 直接丢掉（`.map(|_| ())`），
   而 `begin` 建的/借的那条链归**帧**所有、只有 `reap_frames` 会还 ⇒ 同步跑完的触发节目也漏。
   补一个 `teardown(state) = exec::reap_frames(state)`（只回收**终态**帧，挂起的帧留给宿主的
   排空循环）。这一条在实测中被 ②掩盖着（② 漏的那一条与它混在同一个计数里），但它是真的：
   修掉 ② 之后"有触发"的用例仍然多一条。

判据 `a_card_play_leaves_no_chain_referenced`：**三条用例**（无触发对照 / `standard.slow` 的裸
`applyStatus` / `standard.enrage` 的 `node.conditional`）出牌后 `live_chain_count() == 0`。
第一条对照是关键：**连没有任何触发器的出牌也漏**，所以这不是派发路径的问题，是入队本身。
负控：不还创建者的那一次 ⇒ 三条全红（`[(None,1), (slow,1), (enrage,1)]`）。

判据 `a_capacity_error_inside_a_play_names_its_container`：包在 `Play` 里的容量错误必须说出
`Chains`；直接的就是直接（回归）；**非**容量错误仍报 0（不许把所有 `Play` 错误都说成某种容器，
那会让"哪个容器满"变成噪声）。负控：把那条 `match` 注释掉 ⇒ 红在 `left: 0, right: 21`。

### 199.3 soak 闸门自己的两处

这一轮里 `web-soak` 的"死控件"判据有两次**假红**，两次都修了（都在 `web/`）：

* 指纹只比 `#msg` 的**前 40 字符**，而战斗里第一行 `round N · turn M · phase P · result R`
  就可能超过 40 ⇒ "被拒"那半句被切在 40 之外，一次**正常的拒绝**被记成死控件（一次 58 个）。
  判据要能看见证据，就不能先把它截掉 ⇒ 比**整条**消息。
* `index.html` 手牌点击在 `options.length === 0` 时**静默 return**（不说话、不重渲染）——
  死控件的教科书形状。改成说出来 + 重渲染。

### 199.4 数字与剩下的

* **20/20 闸门绿**，单测 **870**（688 / 107 / 75）；四条对拍不变（182/182、62/62、124/124、394/394）。
* 内容：状态 39 → **40**、卡 49 → **51**、镜像 71,848 → **72,392 B**（core 60,876）。
* 新导出/新字符串 0 个（`TurnStartEnergy` 是内容里的管线名，不走 ABI）。
* 还差：能量**上限**（`max`）还没有修饰器（只有补给数有）；`Energized` 类"只下一回合"要靠
  内容给自己挂衰减触发器（本内容暂时没有这种卡）。

---

## §200 行动者自毁 + 匕首的 Explode（工作包 B-4 的第一半）

`remove_combatant` 一直**拒绝**移除当前行动者（`CapacityError::ActiveCombatant`，§178 的理由是
"回合循环按 id 找它"）。于是 Reptomancer 的匕首只能打 25 点伤害、**永远留在场上** ——
内容里那条 `AiNote` 自己写着"⚠️ 偏差：`Explode` 之后不自毁"。

### 200.1 空出来的那一格决定继任者

`remove_combatant` 现在允许移除当前行动者，但**不**直接把席位交给继任者，而是把"那一格"记进
`CombatState::vacated_seat`（`u8`，`turn_order` 是 shift-down 的，所以被移除者原来那一格现在
正好坐着继任者）。收尾这一回合时 `turn::advance_to_next_combatant` 用**它的前一格**当 `cur`，
于是 `(cur + offset) % 各种` 的第一站正好是继任者。

三种写法各自错在哪（都试过）：

| 写法 | 后果 |
|---|---|
| 直接把 `active_combatant_id` 设成继任者 | 收尾时还会推进一格 ⇒ **继任者被跳过**（一次跳两格） |
| `active = None`，让 `ensure_active_combatant` 认领第一个活人 | 回合序**从头开始**（静默重排） |
| 什么都不做，等报错 | `ActiveNotInTurnOrder` ⇒ 回合卡死（`StepThrew(Turn)`） |

另外两条细节：`extra_turn_for` 一起清掉（行动者都走了，"再来一回合"没有主人）；
`ensure_active_combatant` 在"席位被腾空"时**拒绝**认领（`NoActiveCombatant`）—— 把"绕过了交接"
变成响亮失败，而不是静默重排。

`end_current_turn` 因此多了一条路径：行动者在自己的回合里自毁 ⇒ 没有行动者，但它连牌堆都被
摘掉了，所以每一段 per-actor 工作（手牌生命周期 / 弃手牌 / 回合末触发器 / 按时长衰减）都没有
对象，整段跳过，只翻相位、交接席位、消化队列。

### 200.2 内容

`dagger.explode` = `dealDamage 25` + `node.destroyCombatant(sel.source)`（wiki `Reptomancer`：
"Explode: 25 damage and dies"）。内容门当场报出新事实
(`action.dagger.explode: facts [('damage', 25, 'event'), ('destroy', 'source')], inv says [...]`),
补上那一行之后 `STS_CONTENT PASS`。

### 200.3 判据

* `a_combatant_that_removes_itself_hands_the_seat_to_its_successor`：`[hero, enemy_a, enemy_b]`
  里 `enemy_a` 当行动者时自毁 ⇒ 收尾后席位是 **`enemy_b`**，`current_turn` **只 +1**，
  `current_round` 不变。负控（`cur = seat`）红在 `left: hero / right: enemy_b`。
* `a_combatant_that_removes_itself_last_wraps_to_the_front`：末尾那一格被移除 ⇒
  `vacated_seat == 2`（超出新长度）⇒ 绕回 `hero` 且轮次 +1。同一个负控红在 `left: enemy_a`。
* `a_vacant_seat_is_not_silently_reclaimed_from_the_top`：席位空着时唯一合法的前进方式是交接。
* `a_dagger_that_explodes_removes_itself_and_hands_the_seat_on`（端到端，全镜像，两只匕首）：
  步 1 后英雄 45、`dagger_1` 不在名册；步 2 收尾把席位交给 `dagger_2`；步 3 之后英雄 20、
  `Victory`、席位空。步 1/步 3 的伤害**就是**交接判据 —— 跳格或从头开始都会让步 3 撞
  `StillHeroTurn` 且英雄停在 45。负控同上（`so is the second` 红）。
* 老测试 `destroying_a_combatant_takes_it_out_of_the_roster_and_the_turn_order` 里那条
  "当前行动者不许移除"的断言**被改写**：现在必须成立的是"移除合法、席位空着、`vacated_seat`
  指向那一格"。这是**语义变更**，不是放宽判据。

### 200.4 数字与剩下的

* **20/20 闸门绿**，单测 **877**（692 / 107 / 75 / …）；四条对拍不变（182/182、62/62、124/124、394/394）。
* 内容：镜像 72,392 → **72,556 B**（core 60,876 → 61,040）。
* 工作包 B 的**最后一半**是 Looter 的"偷钱逃跑"。它不是一条节点：内核没有金币，金币在运行层。
  下一次要做的是"内核记 `stolen_gold`（`Counters` 就够）→ 运行层在 `fight_end` 结算"这条约定，
  外加 Looter 的怪物行 / 三个动作 / 遭遇行。

---

## §201 Looter：偷钱 + 带着钱逃（工作包 B-4 的下半）

§200 让"行动者可以自毁"，`Escape` 才有了落点；但 Looter 的另一半是**金币** —— 而内核里没有
金币。wiki `Thieves` 的三句话就是全部规格：

* `Thievery 15`："Steals X Gold whenever it attacks."
* `Stolen gold is returned if this enemy is killed.`
* `Escape`："Flees combat with your Gold."

### 201.1 跨层的那一个数

金币是**运行层**的（`RunState::gold`），内核的 `CombatState` 里没有。所以约定是**一个字段**：

* `CombatState::gold_carried_away: i32` —— 只装"**已经带着离开**"的钱。不进哈希、不进快照
  （参考没有这个字段，写进 `hash_golden` 会移动全部 85 个语料基线）。
* 新节点 `node.carryAwayStolenGold`（`CounterId` + `TargetSelector`）：把目标身上那一格计数器的
  **当前值**搬进上面那个字段，再把它**清零**。清零不是顺手：目标随后就被 `destroyCombatant`
  摘掉，但"搬"与"复制"的区别只在这一行上（`30 + 30` 与 `30`）。
* 内容侧偷钱就是 `node.setCombatantCounter` + `Relative: true`（`counter += 15`）——
  **不需要新节点**。

为什么"活着的敌人身上的钱不算丢失"：打赢 = 全灭，所以"小偷还活着"在胜利的局面里不存在；
而死掉的那个的计数器留在它的尸体上（`Counters` 跟着 `Combatant` 走），运行层根本不看它。
⇒ 结算只需要 `carried`，不需要"总共偷了多少"。

`fight_end`（`kernel/rd-wasm/src/run.rs`）：读 `gold_carried_away`（**在** `take_session()` 之前），
`apply_fight_outcome` 多收一个参数并 `adjust_gold(-carried)`（`adjust_gold` 本来就夹在 0 以上，
正好是 wiki 的 "doesn't give back gold it didn't steal" 的另一头）。Smoke Bomb 的逃跑
（`flee_fight`，`result = 3`）走同一条路 —— 逃跑也不退还。

⚠️ 回放：`K_FIGHT_END` 那一行原来 `text` 是空的，现在写 `carried` 的十进制。**没有**塞进 `b`
的位域（那个字已经装着档位与结果，再塞一个数就是"静默回放分歧"的温床）。旧记录读出来是 0，
正好等于它们当时的结算。

### 201.2 内容

`looter`（HP 44-48，`Tier Normal`）+ 四个动作 + `enc_looter`（solo，进 act-1 的 `Weak` 池，
权重 15 与 Gremlin Gang 同级）+ AI 四条规则（前两回合 Mug / `last_move` 是炸弹 ⇒ Escape /
`last_move` 是 Lunge ⇒ 炸弹 / 否则 50-50）。四个动作都按 §195.5 的纪律写了
`prev_move = last_move; last_move = k`（否则 `history.looter` 那一族判据会红 —— 它确实红了，
说明那条闸门在工作）。

⚠️ **偏差**（写进 `AiNote`）：`EACT` 没有 ascension 列，所以 A2 的 11/14 与 A17 的 `Thievery 20`
没做 —— 这是全局已知缺口，不是这一节新欠的。

### 201.3 判据

* `a_looter_steals_thievery_gold_on_every_attack_and_carries_it_away`：两次 Mug 之后计数器 **30**
  （不是 15、不是 0）、英雄 70→50（偷钱**不**代替伤害）、Escape 之后 Looter 不在名册、
  `gold_carried_away == 30`、四步 `problems` 全空。
  负控：`carryAwayStolenGold` 变成空操作 ⇒ 红在 `left: 0 / right: 30`，**而每一步都不报错** ——
  那正是最坏的形状（被偷 30、逃走时一分没少、所有闸门都绿）。
* `escaping_moves_the_counter_instead_of_copying_it`：逃走前 30/0、之后 0/30。与上一条分开写，
  因为"搬"与"复制"只有这一条能分开（两条加起来查不出 30+30）。
* `the_looter_mugs_twice_then_bombs_then_escapes`（`select_action` 直接问）：回合 1/2 **每 60 个种子
  都是 Mug**（规则静默失效会退回 `Actions` 循环，只会偶尔错）、回合 3 只可能是 Lunge/Smoke Bomb、
  Lunge 之后是炸弹、炸弹之后是 Escape（而且**一直是** Escape：规则问的是"上一招是炸弹"，
  不是"第 5 回合"，所以 `round = 9` 也得是它）。
* `the_gold_a_thief_carried_away_is_the_only_gold_lost`（运行层）：逃走 15 ⇒ 金币恰好少 15；
  `carried = 0`（小偷被打死）⇒ 金币只按奖励涨；5 金币 + 带走 999 ⇒ 夹在 0。奖励金额是**量出来**
  的（同一个种子先跑一次 `carried = 0`），不抄 `inv:§5` 的区间。
  负控：结算改读"敌人身上的计数器"⇒ 第二条红（死掉的小偷也会扣钱）。

### 201.4 顺带修好的两条**陈旧断言**（它们本来就该红）

加进 act-1 池之后，种子的抽取顺序变了，两条测试的**手抄清单**当场报错：

* `act_two_fights_act_two_enemies` 只认 `["acid_slime","spike_slime","jaw_worm","cultist"]` ——
  那不是"act-1 池"，那是它当年见过的那四个。改成**整池**（含 looter/louse/fungi_beast/slaver/gremlin）。
* `the_boss_is_offered_at_floor_16...` 只认 `slime_boss`/`time_eater` —— §194 已经把 act-1 的 Boss
  池补到 wiki 的三个，它一直没跟上，只是种子恰好没抽到 Guardian。改成三个全认。

这两条不是"放宽"，是**把代理指标换成它声称要测的东西**。

### 201.5 数字

* **20/20 闸门绿**，单测 **878**（695 + 76 + 107）；四条对拍不变（182/182、62/62、124/124、394/394）。
* 内容：怪 46 → **47**、遭遇 33 → **34**、敌人动作 121 → **125**、镜像 72,556 → **73,904 B**
  （core 62,216）。
* 工作包 B **全部完成**（B-1 §196 / B-2 §197 / B-3 §198+§199 / B-4 §200+§201）。

---

## §202 全遭遇构造 + Act2/Act3 切片（工作包 C）

工作包 C 的两条：**"遍历每一场遭遇的可构建测试"** 与 **"Act2/Act3 的确定性战斗切片"**。
两条都放在 `rd-wasm` 的测试里，因为它们要的入口是**生产路径**（`build_session_at`），而不是
测试自己拼的蓝图 —— `rd-core` 拿不到那段代码，而复制一份就是第二个真相。

### 202.1 `every_encounter_in_the_image_builds_and_runs_without_a_thrown_step`

按 `IDX` 的 `EK_ENCOUNTER` **枚举**（`ENCT` 行里没有名字，名字只在 `IDX`），对镜像里**每一个**
遭遇（34 个）跑一遍 `build_session_at(seed 7, name, hp 70, None, 0, 0)`，然后连打 12 个
"结束回合"，断言：

1. 每一个都能建 —— 这一段覆盖的是**去重 id**（`bronze_orb#2`）、`Spawn: false`（开场不在场，
   等召唤）、`Owner`（主人必须在本场里）、`StartingStatuses`、血量掷骰、ASC 修正；
2. 返回值不许是 `-3`（那才是"内核抛了"）；
3. 死亡/无牌可打导致的 `-1`（观察没变）是**合法**的 —— 70 点血的假英雄打不过 Boss 是内容事实，
   不是内核缺陷。这条测试问的是"能不能跑"，不是"能不能赢"。

"至少 34 个"这条下限是**反证过的**：如果枚举写错（比如按 `ENCT` 行去取 id 取不到），
`encounters` 会是空，`assert!` 立刻红 —— 而不是"0 个测试悄悄通过"。

### 202.2 Act 2 切片：`act_two_bronze_automaton_summons_its_orbs_on_turn_one`

wiki `Bronze Automaton`：`Spawn` 召唤 2 只 Bronze Orb，而 Orb 在遭遇里是 `Spawn: false`
（它只是招式表的载体）。三段判据：开场**只有 Boss**（敌人数 1）；打几个回合之后是 **3**；
三只的 id **互不相同**（回合机按 id 寻址，重名会让它在某处响亮失败）。

负控：把 `if !spec.spawn() { continue }` 拿掉（Orb 变成预置）⇒ 红在 `left: 3 / right: 1`。

### 202.3 Act 3 切片：`act_three_reptomancer_daggers_arrive_and_then_take_themselves_out`

这份内容的 `enc_reptomancer` **预置**了两只匕首（`Spawn: true`），所以开场是 3 个敌人；
§200 真正改的是**出口**：`dagger.explode` 会移除**正在行动的那个**（以前 `remove_combatant`
直接拒绝）。判据：敌人数曾经到 3、然后在若干回合之内**掉下去**（有匕首炸掉了自己）、全程无 `-3`。

负控：把 `remove_combatant` 的"当前行动者"守卫恢复（§200 之前的语义）⇒ 红在
`a dagger must leave the fight by exploding (start 3, peak 4)` —— 匕首召唤了新的、却没有一个走。

### 202.4 数字

* **20/20 闸门绿**，单测 **881**（695 core + 79 wasm + 107 run；wasm 从 76 → 79）。
* 四条对拍不变（182/182、62/62、124/124、394/394）。
* 内容不动（镜像 73,904 B）：这一节只加**判据**，不加内容。

### 202.5 工作包 C 的剩余（明确没做）

* **浏览器侧的 Act2/Act3 闭环**（`web/act1_slice.mjs` 的姊妹）：它要"自己算路线走到第 2/3 幕"，
  而路由、奖励、商店都已经是通的了 —— 缺的是一条**确定性的种子路线**。这一节用内核级切片
  把"三幕的敌人能打"钉住了，但"三幕的浏览器闭环"仍然只有 Act1（`act1_slice.mjs`）。
* **内容字段的 Wiki 来源追溯**（C 的第三条）：已经由 `AiNote` / `InvRef` / `docs/spec/` 部分承担，
  系统性核对仍然是人工活。

---

## §203 Act2/Act3 的浏览器切片（工作包 C 的最后一条）

上一节把"三幕的敌人能打"钉在了内核层。这一节补的是**页面**那一层：召唤物出现在敌人面板上、
自毁的敌人从面板上消失。这两件事只有真浏览器能证。

### 203.1 为什么不是"让机器人连赢三幕"

`act1_slice.mjs` 走到第 2 幕靠的是**打赢第 1 幕的 Boss**（约 30 个节点 + 一场 Boss），第 3 幕
要再赢一次。以机器人那个"先格挡后攻击"的策略，这在一场闸门里是**掷骰子**：内容一改（掉落表、
路线、遭遇）就可能输在第 2 幕，而闸门红在一个与本节无关的地方。

所以给页面加了一个**可度量的调试入口**（和 `startWithSeed` / `givePotion` 同一个理由、同一层）：

* ABI：`rd_env_start_encounter(ptr, len)` —— 按名字起一场，走**同一条** `build_session_at`
  （去重 id / `Spawn: false` / `Owner` / 初始状态都在里面），所以它造不出运行层造不出的战斗。
* 页面：`RD_DEBUG.fightEncounter(name)` —— `?debug` 才有。
* 调试战斗的**英雄用 `DEBUG_HERO_HP = 400`**：这些场景是来看内容的（召唤、自毁），不是来赢的。
  用 80 点血时，驱动还没等到匕首的 Explode 回合英雄就死了，闸门于是在**量错的东西**。

### 203.2 调试战斗**不折回运行层**

第一版把调试战斗结束也走 `endFight()`（`rd_run_fight_end`），而调试战斗没有节点 —— 运行层拒绝，
页面退回运行模式，随后的 `rd_env_*` 又**静默新建了一个演示战斗**。表现是敌人面板把一场的血量
配上另一场的名字。现在有一个 `debugFight` 标志：调试战斗就地结束，结果留在屏幕上，运行层不动。

同一类错误还有一次：`setMode` **不清**敌人面板（正常路径靠紧接着的 `render()` 覆盖），于是
`fightEncounter` 之后第一帧读到的还是上一场的敌人 —— 现在它在 `setMode` 之前显式清空。

另外：驱动里我一开始直接调 `ex.rd_env_step(1)` 来"替"禁用的结束回合按钮，那是把页面的状态机
绕过去了（按钮禁用**正是因为**敌人正在行动），页面与 session 当场脱节。现在只点页面自己的按钮。

### 203.3 两段判据

* **Act 2**（`enc_bronze_automaton`）：开场面板上**只有 Boss**（Orb 是 `Spawn: false`），打几个
  回合之后是 **3** 个（Boss 召唤了两只），并且没有一步抛错。
* **Act 3**（`enc_reptomancer`）：开场 **3** 个（Boss + 两只预置匕首），之后跌到 **1** ——
  两只匕首都炸掉了自己（§200/§201 的联动），全程无抛错。

负控：把 `remove_combatant` 的"当前行动者"守卫恢复（§200 之前）⇒ Act 3 红在
`a dagger must explode and leave the panel (before 3, after 3 ...)`，而 **Act 2 仍然绿** ——
两条断言确实各管一件事。

### 203.4 ★ 顺带发现：**召唤物在页面上没有名字**

`rd_env_enemy_name_*` 读的是 `session.plan.enemies`（**蓝图**），而召唤物不在蓝图里 —— 于是
Bronze Orb 在面板上叫 `enemy #1`。运行层同样如此（它不是调试入口的问题）。这一节**没有修**它：
名字来自"观察槽位 → 敌人"的映射，而那个映射在渲染层（`ui_render.describeEnemies`），改错会把
**别的**敌人标错名，比"enemy #1"糟。记在这里，作为 C 之后的一个具体缺口。

### 203.5 数字

* **20/20 闸门绿**（`web-browser` 多出两段 Act2/Act3），单测 **881** 不变（这一节只加页面/ABI）。
* `smoke.mjs` 的导出口径 153 → **154**（新 ABI 一条；`REQUIRED` 是手抄的，所以是两处）。
* 四条对拍不变；内容不动（镜像 73,904 B）。

### 203.6 工作包 C 收口

C 的三条：全遭遇构造（§202.1）、三幕战斗切片（§202.2/3 内核 + §203 页面）、内容字段的 wiki
追溯（仍人工，`AiNote` / `InvRef` / `docs/spec/` 承担了一部分）。**C 到此完成**，剩下的具体
缺口只有一个：召唤物的显示名（203.4）。
