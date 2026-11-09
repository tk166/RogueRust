# RogueRust

一个 Slay the Spire 式的卡牌 Roguelike 工程：**战斗内核 + 运行层 + 内容编译器 + 浏览器前端 + 二十一道聚合闸门**。

参考实现是 `RogueDeck-Core`（C#，MIT；仓库 `ref/RogueDeck-Core` 是只读浅克隆），按 commit
`fd43e68ab91f40b475b745725abb17134b951c51` 冻结。
移植的硬约束是三条：**能在 ESP32-P4 裸机上跑**（`no_std`、零分配、纯整数、`forbid(unsafe_code)`）、
**能多开当强化学习训练环境**（确定性、可快照、可回放）、**与参考实现逐字节一致的状态指纹**（对拍可证）。

> 主计划在 `docs/port-plan.md`（§1–§306，每一轮都留数字、记下被推翻的结论）。
> 这份 README 只交代**仓库现在是什么样、以及怎么把它跑起来玩**；为什么变成这样，在计划里。

---

## 1. 五分钟跑起来（第一次玩请看这一节）

游戏本体是**一个静态网页 + 一个 `.wasm`**，没有服务端、没有数据库、没有 `npm install`。
你只需要：把 Rust 编成 wasm，然后用任意 HTTP 服务把仓库根目录服务出去。

### 1.1 需要装什么

| 工具 | 版本 | 用途 | 安装 |
|---|---|---|---|
| **Rust**（rustup） | stable | 编译内核 → wasm | <https://rustup.rs> |
| **wasm 目标** | `wasm32-unknown-unknown` | 同上 | `rustup target add wasm32-unknown-unknown` |
| **Python** | 3.10+ | 起静态服务（也用于内容编译/闸门） | <https://www.python.org> |
| *（可选）Node.js* | 18+ | 只有 22 道闸门里的浏览器测试需要 | <https://nodejs.org> |
| *（可选）Chrome / Edge* | 任意近期版本 | 同上 | 系统自带即可 |

> 只要**玩**，装 Rust + Python 就够；Node 与浏览器只在你要跑验收脚本时才需要。

### 1.2 编 wasm

```bash
# 仓库根目录
cd kernel
cargo build -p rd-wasm --release --target wasm32-unknown-unknown
cp target/wasm32-unknown-unknown/release/rd_wasm.wasm ../web/rd_wasm.wasm
```

PowerShell 写法：

```powershell
cd kernel
cargo build -p rd-wasm --release --target wasm32-unknown-unknown
Copy-Item .\target\wasm32-unknown-unknown\release\rd_wasm.wasm ..\web\rd_wasm.wasm -Force
```

> **内容镜像已经编进 wasm**（`include_bytes!` 指向 `tools/contentc/packages/sts/out/content.sts.rdcf`），
> 所以你**不需要**另外准备数据文件；只要镜像在仓库里（它在，且入库）。
> 改了 `kernel/**` 或内容 JSON 之后**必须重编 wasm 并覆盖 `web/rd_wasm.wasm`** ——
> 第 14 道闸门会比对它的 sha，陈旧就直接红。

### 1.3 起服务、打开浏览器

**必须走 HTTP**（`file://` 会被浏览器拦掉 `fetch` 与 wasm 的 MIME，页面会白屏）。

```bash
# 仓库根目录
python -m http.server 8000
```

然后打开：

<http://127.0.0.1:8000/web/index.html>

地图页（第 17 道闸门的对象，只走图、不结算）：<http://127.0.0.1:8000/web/map.html>

> 为什么从**仓库根目录**起服务：页面先找 `./rd_wasm.wasm`，找不到再退回
> `../kernel/target/wasm32-unknown-unknown/release/rd_wasm.wasm`。仓库根目录同时满足这两条，
> 也是 `web/cdp.mjs` 在闸门里用的路径。
>
> 也可以用别的静态服务器（`npx serve`、VS Code 的 Live Server、Caddy…），
> 只要保证 `.wasm` 的 Content-Type 是 `application/wasm` —— 大多数现代服务器默认就对。

### 1.4 怎么玩

1. **输入种子**（可选，留空则用默认种子），点 **「开始 / 重开」**。
   同一个种子 + 同一串操作 ⇒ 完全相同的局面（这是工程的硬约束，不是巧合）。
2. **塔底祝福**：从几个选项里挑一个（可能是"删一张牌 / 升一张牌 / 换金币 / 加最大生命"等）。
3. **地图**：点亮的是当前可走的节点，点一个走过去。六种节点：
   **⚔ 普通战斗 / ☠ 精英 / 👑 Boss / 🔥 篝火 / 🛒 商店 / ❓ 事件 / 📦 宝箱**。
4. **战斗**：
   * 点手牌 → 需要目标时再点敌人 → 结算；
   * 右下 **「结束回合」**；
   * 敌人头顶的**意图**图标是它下一步要做什么（攻击数值、格挡、上状态…）；
   * 药水在顶部腰带里，点 **「用」**（有的药水要先点敌人选目标）。
5. **奖励屏**：赢下战斗后挑金币 / 卡 / 药水 / 遗物，然后继续走图。
6. **篝火**：休息（回 30% 血）或打铁（升一张牌）；**商店**：买卡/遗物/药水，或花钱删牌。
   （wiki 的篝火另有三件遗物开启的 **Lift / Toke / Dig** 与 **Recall**（红钥匙）—— 见 §2 的诚实清单）
7. 打穿第 16 层的 **Boss** 就进入下一幕（共三幕骨架）；中途死了可以「开始 / 重开」。

**顶部的几个按钮**：存档 / 回档（单行文本 + CRC）、导出 / 导入回放脚本（`RDR1` 格式，
动作序列 + 每步哈希，用来证明"同一串操作得到同一局面"）。

### 1.5 调试面板（`?debug`）

<http://127.0.0.1:8000/web/index.html?debug> 会在页面上暴露一个 `RD_DEBUG` 对象（**只在这个查询串下**）：

| 调用 | 作用 |
|---|---|
| `RD_DEBUG.startWithSeed(seed, ascension)` | 直接开局（跳过祝福流程），`ascension` 0–20 |
| `RD_DEBUG.settle()` | 把当前节点一次性结算掉（调试用） |
| `RD_DEBUG.view()` | 把页面看到的整份状态打成对象（对照观察向量） |
| `RD_DEBUG.givePotion("fire_potion")` | 往腰带里塞一瓶指定药水（测试掉落抽签太慢时的替代） |
| `RD_DEBUG.giveRelic("runic_pyramid")` | 按 id 塞一件遗物（有的遗物只在商人/事件里有，靠种子碰不到） |
| `RD_DEBUG.startAnEvent("forgotten_altar")` | 直接打开一条事件（同上；面板的写者是 `renderNode`） |
| `RD_DEBUG.dropPotions()` | 清空腰带 |

这些入口**只存在于 `?debug`**：它们是给闸门和排查用的，不是作弊命令。

### 1.6 常见坑

| 现象 | 原因 | 解决 |
|---|---|---|
| 白屏 / 控制台报 `WebAssembly` 或 MIME 错 | 用了 `file://` 或服务器没给 `.wasm` 正确的 Content-Type | 用 §1.3 的 HTTP 服务 |
| 页面还是旧逻辑 | `ui_render.js` / `ui_panels.js` 是独立缓存资源 | **Ctrl+F5** 强刷 |
| 改了内核但游戏没变 | `web/rd_wasm.wasm` 是构建产物，需要手动覆盖 | 重跑 §1.2 的两条命令 |
| `cargo build` 报 `can't find crate for core` | 没装 wasm 目标 | `rustup target add wasm32-unknown-unknown` |
| 内容改了但战斗还是旧的 | 镜像没重编 | `python tools/contentc/build.py --package sts`，再重编 wasm |

---

## 2. 现在能玩到什么

一局完整的路径是通的：**出发 → 塔底祝福 → 地图 → 战斗 / 篝火 / 商店 / `?` 房 / 宝箱 → Boss → 下一幕**，
三轮下来就是三幕骨架，靠网页前端驱动（`web/index.html`，零构建、零 CDN）。

| 层 | 现状 |
|---|---|
| **战斗内核** | `rd-core` **22** 个源文件、约 **75k** 行。出牌/结算/状态/意图/修饰器管线/效果程序 IR（栈式）/选择与目标/金色指纹；**零分配、纯整数、`forbid(unsafe_code)`** |
| **运行层** | `rd-run` 约 **16.3k** 行。地图（15 行 × 7 列 + Boss）、幕、牌组、金币、遗物、药水、奖励屏、商店、事件、篝火、**Ascension 0–20（20/20 条都有机制）**、**存档（单行文本 + CRC）**、**回放（动作序列 + 每步哈希）** |
| **内容** | **58 怪 / 61 遭遇 / 293 条卡行（154 张基础 + 139 条升级行）/ 148 状态 / 159 敌人动作 / 152 遗物 / 33 药水（满池）/ 19 个事件（三幕池 10+8+4 = 22 条，跨幕复用 3 条）/ 10 张起始牌**；**101 个动作有升阶变体**（117 个变体）。编译成 177,908 B 的 `rdcf` 镜像（core 镜像 140,968 B）。⚠️ 这些数字由 `native/gap_check.py` 的 pastable 区块生成，**别手抄**；"还差哪些**牌**"由 `native/audit_card_gap.py` 与 wiki 卡表逐张对账（见 `docs/sts-wiki-gap.md` §A.1） |
| **前端** | `index.html`（战斗 + 运行层 + 存档 + 回放）、`map.html`（地图页）；`wasm32` + **148** 个 `i32` 的战斗观察向量（另有 19 个 slot 的运行层观察）、一组 `rd_env_*` / `rd_run_*` 导出（`web/smoke.mjs` 有一张手抄的 `REQUIRED` 表**逐条**对账，加导出必须同时改两处） |
| **RL 环境** | `rd_env_*` ABI（`docs/spec/env-abi.md`）+ Python `ctypes` 封装（多进程、批量观察） |
| **裸机** | `riscv32imac-unknown-none-elf` 真链接成 ELF，镜像占用有闸门 |

**还不能**（诚实清单，逐条与 wiki 比对过；数字都由 `native/gap_check.py`、
`native/audit_card_gap.py` 与 `native/audit_asc_gap.py` 重算，见 `docs/sts-wiki-gap.md`）。

> 这一节只写**当前**的缺口。已经做完的条目**一律删掉** —— 留着会让人以为还得再做一次，
> 比漏写更坏（§233 / §257 / §258 各清过一批）。

* **卡牌数量**：口径内 **147 / 220**（`audit_card_gap.py --offline` 的 `in-scope missing: 73`）。
  铁甲战士 **75 / 75（齐）**、无色 **70 / 70（齐）**、诅咒与状态齐 —— **缺的 73 张全是观者（紫）**
  （攻击 27 / 技能 34 / 能力 12）。观者的缺口成堆地挂在**姿态系统**（`calm`/`wrath`/`divinity`，
  约 30 张）、**Mantra/Divinity**、**Scry**、**Retain + `Establishment`**、**`Alpha`→`Beta`→`Omega`** 上，
  所以下一批应该按"基建"聚类做，而不是一张张补。
* **篝火**：**六个选项全通**（§259）—— Rest / Smith / **Recall**（红钥匙）/ **Lift**（`Girya`，
  最多 3 次、之后每场战斗带这些力量）/ **Toke**（`Peace Pipe`，删牌免费）/ **Dig**（`Shovel`，
  只抽 Common/Uncommon/Rare）；`Coffee Dripper` / `Mark of the Bloom` 关 Rest、`Fusion Hammer` 关
  Smith、`Dream Catcher` 让休息额外给一次卡牌奖励。仍缺的是**第四幕本身**（红钥匙的用处）。
* **遗物**：**152 / 193**（`native/audit_relic_gap.py` 的账：`MISSING: 41`、
  `METADATA（两边都有但写错）: 0`、`IMPLEMENTED: … 内核不认识: 0`；逐条清单在
  `docs/relic-inventory.md`，193 行、标明"有/缺"）。**缺的 41 件里 18 件是别的角色的球/姿态/毒、
  13 件是无尽模式 `Blight`、2 件 `circlet`、1 件 `necronomicon`（明确不做）**，
  铁甲战士这条线上真正的缺口只剩 `tingsha` / `tough_bandages`（缺 `CardDiscarded` 事实）、
  `golden_eye`（缺 `Scry`）与三件 `bottled_*`（拾取时绑牌）。
  分档、载体决策树与已实现规则清单见 **`docs/sts-wiki-gap.md` §D.2**；
  方法论见 **`docs/function_scaling_up_for_relics.md`**。
* **事件**：**19 个**（三幕池 10+8+4 = 22 条；`golden_idol` / `ancient_forge` /
  `purification_shrine` 跨幕复用）。**剧情分支已经是真树**（`EVND` 段表 + `EV.Entry`，选项数不固定，
  `golden_idol` 的两段三选一、`dead_adventurer` 的 21 个分支屏都在），选项支持条件
  （`Requires` / `RequiresAsc`）与一串效果。**仍缺**：事件级条件（"这条事件出不出现"）、
  "从手上任选一件遗物失去"（`N'loth`）、以及 Act 2 的 5 条事件
  （`vampires` / `masked_bandits` / `knowing_skull` / `council_of_ghosts` / `cursed_tome`）——
  逐条见 `docs/event-gaps.md`。
* **状态**：缺"下一回合**多**抽 / **多**能量"（`Draw` / `Energized`）—— 现在只有本回合的
  `combat_draw` / `combat_energy`，以及"下一回合**少**抽"的 `standard.draw_reduction`。
* **Ascension**：**20/20 条都有机制**（14 条运行层规则 + 6 条走 `EACT.ProgramAsc`）；A7/A8/A9 的
  生命值按 wiki 的 `AscHP` 逐条钉住（§206，`INV_ASC_HP`）。数据侧：**79 个动作有升档变体
  （91 个变体）**，其余 **51 个**动作没有 wiki 出处（`gap_check.py` 打印 `without a variant: 51`）；
  逐条对账用 `python -X utf8 native/audit_asc_gap.py`（§258 起有脚本，不再靠人眼）。
* **敌人**：**58 怪 / 61 遭遇**；三幕的**精英与 Boss 池**都是 wiki 的三选一（各 3 条），
  **Act 1 普通池 17 条**、**Act 2 普通池 13 条**（wiki 13/13）、**Act 3 普通池 10 条**
  （wiki 10/10）—— 我们**没有** Easy/Hard 的两段式，只用一个带权重的单池，
  这是与 wiki 的已知偏差。已知的**简化**（写明在
  `AiNote` 里，不是漏）：`giant_head` 是 320 HP 的简化版（招式表跟着简化）、`EncounterTables`
  的组成是**固定行**（wiki 的"红或绿虱子"这种随机组成靠多条同权行近似）、
  少数招式的 A17/A18 附加规则只做到"禁令"那一层；**Act 2 普通池 13 / 13**（含
  `Sentry and Spheric Guardian` —— 它带来了 `(monster, tier)` 的 HP 建模）。逐条见
  `docs/sts-wiki-gap.md` §D.3.1。
* **仍缺的机制**（不是内容行，是载体）：~~战斗中的随机~~（§281 已做：`expr::randomInt` +
  `CombatState::draw_in_range`，唯一入口）、~~事件剧情分支~~（§278/§279 已做）——
  剩下的是**事件级条件**（"这条事件出不出现"，会重掷 `?` 房每一次抽取，所以单独做）、
  **"任选一件遗物失去"**的问句（`N'loth`）、Boss 分裂/相位（除 Slime Boss）、
  A2/3/4 之外的招式表替换（A17/18/19 的动作级覆盖已是 `ProgramAsc`）、
  药水差 0 瓶但**整手牌改费 / 自动打出 / 死亡拦截**仍然只有部分路径、逃跑（见 `docs/sts-wiki-gap.md` §2）。
* **第四幕与钥匙**：没有。`Recall` 就挂在它上面。

---

## 3. 目录

| 路径 | 内容 |
|---|---|
| `kernel/rd-core/` | **战斗内核本体**（`no_std`，21 个源文件）。语义冻结在 `docs/spec/SEMANTICS-v1.md` |
| `kernel/rd-run/` | **运行层**：地图/幕/牌组/金币/遗物/药水/商店/事件/篝火/Ascension/存档/指纹 |
| `kernel/rd-wasm/` | **ABI 层**：把内核 + 运行层变成 `rd_env_*` / `rd_run_*` 导出，编到 `wasm32` |
| `kernel/rd-firmware/` | 裸机启动壳（独立的 `[workspace]`，只在 riscv 目标上存在）——**只为证明链接得过** |
| `kernel/rd-hashdump` `rd-rngdump` `rd-sizeprobe` `rd-fightdump` | 诊断二进制：哈希对拍、洗牌序列对拍、RISC-V 代码体积、把一局战斗逐步打出来 |
| `tools/contentc/` | **Python 内容编译器**：JSON 源 → `rdcf` 二进制镜像（段目录 + 字符串池 + 效果程序 IR） |
| `tools/acceptance.ps1` | **聚合验收**：22 道闸门（含 `coverage-matrix` 与 `state-fields`），一道红就整体红 |
| `tools/rdcf_verify.py` `rdcf_terms.py` | 内容镜像的**独立**字节级校验（段目录 / count×stride / term 表形状） |
| `web/` | 前端（零构建、零 CDN）：`index.html` + `ui_render.js`（战斗语义）+ `ui_panels.js`（14 个节点状态）+ `map.html` + `pixels.mjs`（像素度量）+ 门 13–20 的脚本 |
| `native/RogueDeck.Oracle` `RogueDeck.Native` | C# 侧：对拍导出（NativeAOT）与 RL 环境 ABI |
| `native/*.py` | 三类：**对拍/校验驱动**（`fight_diff.py`、`gap_check.py`、`sts_content_check.py`…）、**`doc_*.py`**（每一节往 `port-plan.md` 追加章节的脚本，与正文一一对应）、**`patch_*.py` / `negctl_*.py`**（那一节改动源码与**反证**的脚本，留作记录） |
| `py/roguedeck_env/` | RL 环境的 Python 封装（`ctypes`，多进程 + 批量观察 + 吞吐基准） |
| `corpus/` | 对拍语料：`golden_v1.jsonl`、`hash_cases/*.txt`、`coverage.json`（份数以闸门输出为准） |
| `docs/` | `port-plan.md`（主计划 §1–§306）、`spec/`（19 份规格书）、`sts-wiki-gap.md`（缺口清单；"我们有多少"由 `native/gap_check.py` 重算，"还差哪些牌"由 `native/audit_card_gap.py` 与 wiki 卡表对账）、`coverage-matrix.md`（**生成物**：每个实体的 Implemented / TestNamed / HarnessOnly / SourceTie / DeclaredDeviation / Evidence，闸门 21；带 `--selftest` 的五个对抗性夹具）、`event-gaps.md`（事件侧缺口，§306 全面核对）、`mechanism-gaps-analysis.md`（两个机制缺口的分析记录与**关闭状态**） |
| `ref/` | 参考实现的浅克隆位置（**不在本仓库**，见 §9） |
| `sts/` | **早期 Python 原型**，已被 Rust 内核取代，保留作参照（不参与任何闸门） |

---

## 4. 内核的三条不变量

`rd-core` 里每一条代码都要满足：

1. **零分配**：没有 `Vec`/`String`/`Box`，所有容器是定长数组 + 计数；容量溢出是**错误**，不是截断。
2. **纯整数**：没有浮点。伤害/格挡/百分比全部走定点，因为裸机上 F/D 单元不可用。
3. **确定性**：所有随机走**命名随机流**，状态指纹覆盖全部字段；`forbid(unsafe_code)`。

运行层是 `std` 的，但同样保持"拒绝 ⇒ 一个字节都不改"（判据是整个结构体相等）。

---

## 5. 构建与验收

### 5.1 两条路：自己的 shell，还是包装脚本

如果本机 shell 是完整的，直接 `cargo` / `python` 就行。**本仓库的开发者机器 shell 被剥空**
（`LOCALAPPDATA`/`ProgramFiles(x86)`/`PATH` 不完整，`PATHEXT` 只有 `.CPL`），所以仓库里备了包装脚本：

```powershell
& .\tools\cargo.ps1 test -p rd-core -p rd-run -p rd-wasm --release      # 单元测试
& .\tools\cargo.ps1 clippy --all-targets -p rd-core -p rd-run -p rd-wasm # 零告警是硬要求
& .\tools\acceptance.ps1                                               # 22 道闸门，约 5 分钟
& .\tools\acceptance.ps1 -SkipSlow                                     # 跳过 soak / 浏览器
python tools/contentc/build.py --package sts                           # 改内容 JSON 之后
```

`acceptance.ps1` 有**真参数块**（`-SkipSlow`、`-UnitsFloor`），不是位置参数。
`cargo test -p rd-wasm` **必须**带 `--test-threads=1`：它的测试共享一份全局 session（裸指针
写进去），并行跑会以 `STATUS_HEAP_CORRUPTION` / `STATUS_STACK_BUFFER_OVERRUN` 退出。
`acceptance.ps1` 就是这么跑的 —— 手工复现时别漏了它。

### 5.2 22 道闸门

下表写的是每道闸门**必须打印出来的证据串**（`Invoke-Gate -MustMatch`），不是某次运行的数字。
数字每次跑都不同，抄进文档就会过期（§169）；要看数字就自己跑一遍。

| # | 闸门 | 证据串的形状 |
|---|---|---|
| 1 | `rust-units` | `N passed`，且不低于 `-UnitsFloor` |
| 2 | `corpus-roundtrip` | `N case(s) reproduced byte-for-byte` |
| 3 | `rust-baremetal` | `Finished`（riscv32imac-unknown-none-elf） |
| 4 | `rust-clippy` | `Finished`，零告警 |
| 5 | `firmware-link` | `Finished`（真链接成 ELF） |
| 6 | `firmware-size` | 镜像占用 + 陈旧守卫 |
| 7 | `coverage-gate` | `19/19`（规格书每条都有判据） |
| 8 | `golden-baseline` | golden 与基线逐字节（SHA-256 相等） |
| 9 | `env-smoke` | RL 多开吞吐 + 可复现 |
| 10 | `contentc-bytes` | `N/N images` |
| 11 | `rdcf-verify` | `7/7 tables` + `count×stride` + **`6 term-shape checks over N terms`**（§184） |
| 12 | `sts-content` | 内容自洽（怪/遭遇/卡/药水/状态…逐项 + 交叉引用） |
| 13 | `wasm-rebuild` | wasm 是当前树的新构建 |
| 14 | `web-package` | 产物字节同一 + 脚本能解析 + 只调真导出 + 偏移铺满 |
| 15 | `web-ui` | 界面上每个数字 == 观察向量里那一格 |
| 16 | `web-map` | 画出来的图 == `rd-run` 生成的那张图 |
| 17 | `web-browser` | `BROWSER_TEST PASS`（真指针点击） |
| 18 | `web-soak` | `SOAK_TEST PASS`（随机点每个启用中的控件） |
| 19 | `web-slice` | `ACT1_SLICE PASS`（自己算路线走遍每种节点，Boss 场景**重试到赢**） |
| 20 | `web-pixel` | `PIXEL_TEST PASS`（像素判据 + 故障注入自检） |
| 21 | `coverage-matrix` | `COVERAGE_MATRIX PASS (rows=N, tests=N, fresh)` + `SELFTEST PASS (5 fixtures)`（生成物必须与盘上一致；孤儿行 / 偏差表漂移 / 扫描器自坏都是红） |
| 22 | `state-fields` | `STATE_FIELDS PASS (63 fields, …)`（穷尽读 `RunState` 的字段表：每个字段必须出现在存档的写侧与指纹里；豁免必须带理由，豁免的字段被删也是红） |

闸门的共同要求是**拿到证据串**，而不是只看退出码 —— 一个 `exit 0` 的闸门可能什么都没跑。
每道闸门存在的理由写在 `tools/acceptance.ps1` 的注释里，逐条来历在 `docs/port-plan.md`。

---

## 6. 四条对拍（不在验收里）

与 C# 参考实现逐字节比状态。它们**不进那 22 道闸门**，因为需要那份约 111 MB 的第三方克隆和一份 NativeAOT 构建：

```powershell
python native/fight_diff.py      # 一场一场比：FIGHT_DIFF n/n
python native/hash_diff.py       # 规范文本 + 哈希
python native/rng_diff.py        # 洗牌序列
python native/env_check.py       # RL ABI
```

---

## 7. 二进制镜像与行尾

`tools/contentc/out/content.rdcf` 与 `tools/contentc/packages/sts/out/content.sts*.rdcf`
是内容编译器的**产物**，同时是**测试夹具**（`rd-core` 的测试直接读，缺了就 panic 并提示重编译），
所以它们入库。同目录的 `layout.txt` / `report.md` / `validate*.json` 是给人看的派生报告，**不入库**。

`.gitattributes` 里是 `* -text`：全部验收都是**逐字节**的（规范文本、哈希语料、内容镜像），
任何行尾转换都会让它们失去可比性。

---

## 8. 关于 `web/rd_wasm.wasm`

它是**构建产物**，但 `web-package` 闸门要它"就是当前树的新构建"（比对 sha256），所以工作区里它必须存在；
`.gitignore` 里忽略它、由 §1.2 的命令生成。忘了重编的症状是第 13 道闸门红，
而游戏里表现为"改了内核但行为没变"。

---

## 9. `ref/` 不在仓库里

`ref/RogueDeck-Core` 是约 111 MB 的第三方浅克隆（带它自己的 `.git`），按 commit 冻结：

```powershell
& 'C:\Program Files\Git\cmd\git.exe' clone --filter=blob:none --no-checkout <上游地址> ref/RogueDeck-Core
& 'C:\Program Files\Git\cmd\git.exe' -C ref/RogueDeck-Core fetch --depth 1 origin fd43e68ab91f40b475b745725abb17134b951c51
& 'C:\Program Files\Git\cmd\git.exe' -C ref/RogueDeck-Core checkout fd43e68ab91f40b475b745725abb17134b951c51
```

**只读**，不要在里面跑 `dotnet`（它自己的构建会污染工作树）。
