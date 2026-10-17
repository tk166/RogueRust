# RogueDeck-Core 实测结论（2026-10，本机）

> 目的：验证"第一版直接用现成引擎 + TUI 库粘起来"这条路走不走得通。
> 结论：**走得通，而且比我先前估的强得多。自研/翻译这条路应当放弃。**

## 1. 结论

| 问题 | 实测答案 |
|---|---|
| 现成引擎能跑起来吗 | 能。`RogueDeck.Core.Tests` **1495 个测试全绿，430 ms** |
| 它是"只有战斗内核"吗 | **不是。** 有完整 run 层（地图/房间/遗物/奖励/事件/药水/元进度/存档/平衡） |
| 有现成 TUI 吗 | 有。`RogueDeck.Bot.Cli --play` 就是逐命令的文本版 run |
| 有自对弈框架吗 | 有。`--runs N --jobs M --immortal`，每局独立 RNG + watchdog |
| 内容从哪来 | 仓库自带 **8.29 MB** 的 `bureaucrats.roguedeck.json` |
| 许可 | **MIT**（Copyright 2026 Paranoidgrinch），可闭源商用 |
| 体量 | 743 个 `.cs` / **135,496 行**；其中测试 440 文件 / **77,434 行** |

代价：需要 .NET 10 SDK（本机原本只有 runtime 没有 SDK），装一次 20 分钟、免管理员。

## 2. 体量实测

| 模块 | 文件 | 行数 |
|---|---:|---:|
| `src/RogueDeck.Core`（战斗内核） | 125 | 27,713 |
| `tests/RogueDeck.Core.Tests` | 229 | 42,495 |
| `src/RogueDeck.Run`（run 层） | 102 | 17,342 |
| `tests/RogueDeck.Run.Tests` | 113 | 18,875 |
| `src/RogueDeck.Bot` + `Bot.Cli` | 16 | 3,407 |
| Sandbox(Blazor) + Scenario + Studio | ~164 | ~28,400 |

`src/RogueDeck.Run/` 的子系统：`Balance Cards Combat Consumables Effects Events Map
Meta Nodes Programs Registry Relics Rewards Save Selectors Serialization ShredEngine`。
光 `Map/` 就 34 个文件：`LayeredMapGenerator` `RuleBasedMapGenerator` `StrategicMapGenerator`
`StrategicTopologyGenerator` `MapConstraintValidator` `MapRepair` `MapSeedStreams`
`MapNodeRealizer` `StrategicRoomAllocator` `StrategicActSpecValidator` `EncounterDistribution`
`WeightedPathEvaluator` `StrategicPathPressure` `RunMapBuilder` `ChoiceSignature` …

**"我们需要的那部分"并不小**：让这个仓库值得用的正是 `Combat/Effects/`（101 个文件，含
`Programs/` 里 9,550 行的效果程序解释器）。砍掉它 → 退回手写 switch，失去唯一核心价值；
不砍 → 至少 12k 行 Python 加一套测试。所以"翻译成 Python"两头不靠。

## 3. 实测跑通的证据

```
$ roguedeck-bot --game SampleContent/bureaucrats.roguedeck.json --runs 1 --seed-from 7
seed 7  exit 0  sim-result: seed=7 maps=v0.0.1 result=Defeat acts=1 rooms=8
        fights=5 hp=0/70 problems=0 error=none seconds=0.4
```

`--play` 渲染出的屏幕（这就是"现成的 TUI"）：

```
== act 1 · combat · HP 70/70 · gold 0 · deck 10 · relics: none
FIGHT · round 1 · YOU HP 70/70 · energy 3/3 · block 0 · statuses: the_applicant 1
  piles: draw 5 · discard 0 · exhaust 0
  enemy [0] stamp_goblin HP 22/22 · block 0 · statuses: none · INTENT: Rubber Stamp Rush · 5 dmg
  hand:
  [0] Strong Binder (1) —
  [1] Paper Cut (1) —
  ...
> p <card> [enemy] · a <action> [enemy] · e · f (planner plays the fight)
```

地图屏（每条门直接给"到幕末的内容区间预测"）：

```
DOORS (each: the ways behind it to the act's end, fewest–most of each kind of room)
  [0] combat · 13 way(s) · elite 0 · multi 0 · combat 6–8 · rest 0 · shop 0–1 · treasure 0 · event 2–3
  [1] combat ·  8 way(s) · elite 0 · multi 0 · combat 8–9 · rest 0 · shop 0 · treasure 0 · event 1–2
```

奖励屏（三选一，与 StS 同形）：`Permit Denied / Final Reminder / Stamp Barrage`。
选完之后牌组 10 → 11，金币 0 → 24，`g` 继续下一场。

**命令词汇**（来自 `RogueDeck.Bot/TextPlay.cs`）：

| 命令 | 含义 |
|---|---|
| `p <card> [enemy]` | 打出该手牌位（指向该敌人） |
| `e` | 结束回合 |
| `n <i>` | 走过那扇门 |
| `k [i,j]` | 取这些奖励（不填 = 跳过） |
| `x <i>` | 事件 / 商店 / 火堆里的那个选项 |
| `o <i,j>` / `c <i,j>` | 卡牌提问 / 选牌 |
| `a <action> [enemy]` | 用英雄自身动作 |
| `g` | 走到下一个真实决策 |
| `f` | FightPlanner 接管本场战斗（答案会被存成普通答案，回放时不重新规划） |

**存档格式 = seed + 全部答案序列**（`--do "p 0 0; e"`），纯函数式回放。
`RunPlayback` 的注释原话："A run is its seed and the answers given so far — the same thing
a recording is." 天然可做回归测试、bug 复现、RL 训练轨迹。

## 4. 本机踩到的三个坑（都是环境问题，不是项目问题）

本机 pwsh 启动的 shell 只保留 `USERPROFILE` / `TEMP` / `windir` / `NUMBER_OF_PROCESSORS` /
`USERDOMAIN`；**`LOCALAPPDATA`、`APPDATA`、`ProgramFiles`、`ProgramFiles(x86)`、
`PROCESSOR_ARCHITECTURE` 全部为空**。由此引发：

1. `dotnet-install.ps1` 探不到架构 → `Architecture '' not supported`。
   修：显式 `-Architecture x64 -InstallDir <绝对路径>`。
2. **NuGet restore 报 `Value cannot be null. (Parameter 'path1')`**。堆栈是
   `NuGet.Configuration.XPlatMachineWideSetting..ctor()` → `Path.Combine(ProgramFiles(x86), …)`。
   迷惑点：同一个项目**当唯一入口能还原、被别的项目引用时就炸**，看起来像并行还原竞态，
   其实不是。
3. **MSBuild 工作节点复用 15 分钟**：第一次在全空环境下启动的 worker 节点会一直活着，
   之后环境修好了、被路由到这些僵尸节点的项目仍然失败 → **错误恒定钉在同样几个项目上**
   （日志里的 `6:3>` / `7:4>` 就是节点 ID）。修：`MSBUILDDISABLENODEREUSE=1` +
   杀掉残留 `MSBuild` / `dotnet` / `VBCSCompiler` 进程。

工具：`tools/env.ps1`（补全标准环境的哈希表，dot-source）+ `tools/dn.ps1`
（用 `ProcessStartInfo` 起 dotnet，带全环境、自动给含空格的参数补引号）。
⚠️ `dn.ps1` **故意不写 `param()` 块**：一旦写了，PowerShell 会把命令行里的 `--do`
绑到 `-DotnetArgs`（前缀唯一匹配），后续位置参数全部报错。用 `$args` 才收得住 `--` 开头的 token。

## 5. 下一步

1. 用 `--oracle` / `--lanes` 普查地图（几秒钟扫一遍，比跑一批局快几个数量级）。
2. 换一层表现层（`--play` 是现成内核；想上 Godot 就照 `TextPlay.Render` 的信息组织写）。
3. 内容改 `bureaucrats.roguedeck.json`（8.29 MB，纯数据，不碰 C#）。
4. 平衡用 `--runs 1000 --jobs 12` 批量跑 + Python 分析日志。
