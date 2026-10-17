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





































