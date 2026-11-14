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

**最快的一条路**（不需要 Rust、不需要 Node 依赖）：

```bash
pwsh tools/play.ps1          # 默认 8080；被占用会自动换端口并打印**真实**地址
pwsh tools/play.ps1 -Port 8090   # 想要固定地址就自己挑一个（避开 Steam 的 8080/8081）
```

> **地图**：第 1 层在**底部**，往上爬；开局会自动滚到你脚下那一排。
> **状态**：英雄头顶与敌人名牌上各有一排状态（力量/易伤/束缚…），层数写在名字后面。
> **遗物/药水**：顶栏下面那一排是**常驻**的（战斗里、商店里都看得见）。
> **卡牌详情**：奖励屏/商店里把鼠标移到牌上（触屏是按住）就显示 种类 · 费用 · 稀有度 · 规则。
>
> ⚠️ **Windows 上 8080/8081 常被 Steam 的 CEF 调试端口占着**。如果浏览器打开看到的是 Steam，
> 说明端口没抢到 —— 现在的服务器会自己换端口、并把真地址打印出来（§375）。
> 它还会**自检**"这个端口答的是不是我"，所以"启动成功但看到别人的页面"不会再发生。

`web-next/dist/` 是**入库的构建产物**（含 `rd_wasm.wasm` 与它的 sha 清单），所以 `git clone`
之后直接就能玩。改了 `kernel/**` 或 `web-next/src/**` 才需要 `-Rebuild`：

```bash
pwsh tools/play.ps1 -Rebuild   # 重编 wasm + 重建前端 + 起服务（要 Rust 与 npm ci）
```

### 1.1 需要装什么

| 工具 | 版本 | 用途 | 安装 |
|---|---|---|---|
| *（可选）PowerShell 7 / 5.1* | 任意 | 跑 `tools/play.ps1` | 系统自带 |
| **Rust**（rustup） | stable | **只在改内核时**需要（`-Rebuild`） | <https://rustup.rs> |
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
| **战斗内核** | `rd-core` **22** 个源文件、约 **75k** 行。出牌/结算/状态/意图/修饰器管线/效果程序 IR（栈式）/选择与目标/**两个指纹**（`hash_golden` 逐字节复刻参考 + `hash_full` 覆盖 model-only 字段）；**零分配、纯整数、`forbid(unsafe_code)`** |
| **运行层** | `rd-run` 约 **16.3k** 行。地图（15 行 × 7 列 + Boss）、幕、牌组、金币、遗物、药水、奖励屏、商店、事件、篝火、**Ascension 0–20（20/20 条都有机制）**、**存档（单行文本 + CRC）**、**回放（动作序列 + 每步哈希）** |
| **内容** | **61 怪 / 64 遭遇 / 295 条卡行（155 张基础 + 140 条升级行）/ 148 状态 / 166 敌人动作 / 152 遗物 / 33 药水（满池）/ **36 个事件**（三幕池 13+16+10 = 39 条，跨幕复用 3 条；111 个 `EVND` 段）/ 10 张起始牌**；**107 个动作有升阶变体**（128 个变体）。编译成 189,024 B 的 `rdcf` 镜像（core 镜像 151,460 B）。⚠️ 这些数字由 `native/gap_check.py` 的 pastable 区块生成，**别手抄**；"还差哪些**牌**"由 `native/audit_card_gap.py` 与 wiki 卡表逐张对账（见 `docs/sts-wiki-gap.md` §A.1） |
| **前端** | `index.html`（战斗 + 运行层 + 存档 + 回放）、`map.html`（地图页）；`wasm32` + **122** 个 `i32` 的战斗观察向量（另有 19 个 slot 的运行层观察）、一组 `rd_env_*` / `rd_run_*` 导出（`web/smoke.mjs` 有一张手抄的 `REQUIRED` 表**逐条**对账，加导出必须同时改两处） |
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
  `docs/relic-inventory.md`，193 行、标明"有/缺"）。**缺的 41 件按稀有度分**：
  Common 2 / Uncommon 7 / Rare 4 / Boss 7 / Shop 3 / Starter 2 / Event 1 / Special 2 /
  **Blight 13**（无尽模式，不做）。其中 **20 件是别的角色的球/姿态/Scry**（Defect 9 / Silent 4 /
  Watcher 7）、3 件是 `bottled_*`（拾取时绑牌）、`necronomicon` 明确不做、`circlet` 两件是无尽模式；
  铁甲战士这条线上真正的缺口只剩 `tingsha` / `tough_bandages`（缺 `CardDiscarded` 事实）与
  `golden_eye`（缺 `Scry`）。
  分档、载体决策树与已实现规则清单见 **`docs/sts-wiki-gap.md` §D.2**；
  方法论见 **`docs/function_scaling_up_for_relics.md`**。
* **事件**：**36 条**（三幕池 13+16+10 = 39 条；`golden_idol` / `ancient_forge` /
  `purification_shrine` 跨幕复用，111 个 `EVND` 段）。**剧情分支是真树**（`EVND` 段表 + `EV.Entry`，
  选项数不固定），选项支持条件（`Requires` / `RequiresAsc`）、按类型的选牌问句
  （`the_library` 20 选 1、`sensory_stone`、`falling` 的按类型删牌）、事件中途开战斗
  （`dead_adventurer` / `mysterious_sphere` / `colosseum`）、以及 A15 的糟化分支。
  **与 wiki 的 31 条相比是 29 条**：Act 1 **11/11**、Act 2 **13/13**、Act 3 **7/7** ——
  唯一明确不做的是 `cursed_tome`（`necronomicon` 不在范围）。**事件级条件**（"这条事件出不出
  现"）与 `N'loth` 的两件**随机候选遗物**都已做（§331）。逐条见 `docs/event-gaps.md`。
* **状态**：缺"下一回合**多**抽 / **多**能量"（`Draw` / `Energized`）—— 现在只有本回合的
  `combat_draw` / `combat_energy`，以及"下一回合**少**抽"的 `standard.draw_reduction`。
* **Ascension**：**20/20 条都有机制**（14 条运行层规则 + 6 条走 `EACT.ProgramAsc`）；A7/A8/A9 的
  生命值按 wiki 的 `AscHP` 逐条钉住（§206，`INV_ASC_HP`），**档位属于怪物、不属于池子**
  （§315/§327：`Sentry` 钉 A8，两只 Slaver 钉 A7）。数据侧：**107 个动作有升档变体
  （128 个变体）**，其余 **59 个**动作 wiki 没有出处（`gap_check.py` 打印 `without a variant: 59`）。
  **wiki 写了 `{{Asc|N|` 而内容缺档的动作是 0 条** —— 这条由验收闸门 `[7b]`
  （`sts_content_check.py` 的 `check_wiki_asc_levels`）每次重比一遍；人跑的对账是
  `python -X utf8 native/audit_asc_gap.py`（§330 修好了它"只读第一个档位"的解析 bug，
  现在 MISSING/MISMATCH 都是 0，剩下的 4 条 EXTRA 是 `Thievery` 的 A17 写在招式计数器里）。
* **敌人**：**61 怪 / 64 遭遇**；三幕的**精英与 Boss 池**都是 wiki 的三选一（各 3 条），
  **Act 1 普通池 17 条**、**Act 2 普通池 13 条**（wiki 13/13）、**Act 3 普通池 10 条**
  （wiki 10/10）—— 我们**没有** Easy/Hard 的两段式，只用一个带权重的单池，
  这是与 wiki 的已知偏差。已知的**简化**（写明在
  `AiNote` 里，不是漏）：`giant_head` 是 320 HP 的简化版（招式表跟着简化）、`EncounterTables`
  的组成是**固定行**（wiki 的"红或绿虱子"这种随机组成靠多条同权行近似）；A17/A18 的附加效果
  （多一层 Frail / 多 1 张 Wound / 多 1 力量）已经逐条落地并由闸门 `[7b]` 钉住。逐条见
  `docs/sts-wiki-gap.md` §D.3。
* **仍缺的机制**（不是内容行，是载体）：~~战斗中的随机~~（§281 已做：`expr::randomInt` +
  `CombatState::draw_in_range`，唯一入口）、~~事件剧情分支~~（§278/§279 已做）——
  剩下的是**事件级条件**（"这条事件出不出现"，会重掷 `?` 房每一次抽取，所以单独做）、
  **"任选一件遗物失去"**的问句（`N'loth`）、**"下一回合多抽 / 多能量"**（只有
  `draw_reduction` / `no_draw`，没有反向的两条）、以及敌人侧的**逃跑**（运行层的脱战已有）。
  Boss 分裂/相位与 A17/18/19 的招式表**已收口**（§327–§329：六个 Boss 的相位规则逐条对过 wiki，
  `[7b]` 每次验收重比档位）。见 `docs/sts-wiki-gap.md` §2。
* **第四幕与钥匙**：没有。`Recall` 就挂在它上面。

### 2.1 最近这一轮改了什么（§308–§330，`094d34e^..7b32823`）

这一轮是**流程与保真**，不是新内容层：

* **运行层**：`RunState` 的 18 个漏网字段补齐 + 一条 `state-fields` 闸门（§308）；
  拾取类遗物的原子性（§309）；`orange_pellets` 的"清负面状态"（§310）。
* **遭遇与怪物**：Act 2 普通池 3 → **13/13**（§311–§314）、Act 3 **10/10**（§316–§317）、
  Act 1 硬池三场（§275）、组合槽（§277）、`(monster, tier)` 的 HP 建模（§315）。
* **事件**：`EVND` 段表 + 概率 + 条件 + 按类型的选牌问句 + 事件中途开战斗，
  三幕 **28/31**（§318–§325，逐条见 `docs/event-gaps.md`）。
* **战斗语义的三处偏差收口**（§326）：`parasite` 的移除惩罚、`mark_of_the_bloom` 的**战斗内**
  治疗拦截、`Doubt` 的回合末时序（顺序改成 ③④①②，Weak 留到下一回合）。
* **敌人保真**：四条精英组合遭遇的升档数值（§327）、A17/18/19 招式表（§328，
  现在有闸门 `[7b]` 每次重比 wiki 的 `{{Asc|N|`）、六个 Boss 的相位规则（§329–§330）。
* **这一轮挖出的两个真 bug**：`The Champ` 二阶段**每回合都 Execute**（`champ_exec` 从没被程序
  回写过，判据手设了它 —— §330）；`Relics` 里 `mutagenic_strength` **重复一行**（§330，
  顺带加了一道"段内 id 不许重复"的闸门 `[7g]`）。

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
| `tools/acceptance.ps1` | **聚合验收**：56 道闸门（含 `coverage-matrix`、`state-fields`、`ui-state`、`ui-abi`、`ui-next`、`ui-pointer`、`ui-pure`、`ui-wasm`、`ui-wasm-ui`、`ui-wasm-choice`、`ui-wasm-fixtures`、`ui-wasm-xcost`、`ui-scene`、`ui-next-loop`、`ui-p4-models`、`ui-next-p4`、`ui-beats`、`ui-next-p5`、`ui-mobile` 与 `ui-soak-p6`），一道红就整体红 |
| `tools/rdcf_verify.py` `rdcf_terms.py` | 内容镜像的**独立**字节级校验（段目录 / count×stride / term 表形状） |
| `web/` | 前端（零构建、零 CDN）：`index.html` + `ui_render.js`（战斗语义）+ `ui_panels.js`（14 个节点状态）+ `map.html` + `pixels.mjs`（像素度量）+ 门 13–20 的脚本 |
| `native/RogueDeck.Oracle` `RogueDeck.Native` | C# 侧：对拍导出（NativeAOT）与 RL 环境 ABI |
| `native/*.py` | 三类：**对拍/校验驱动**（`fight_diff.py`、`gap_check.py`、`sts_content_check.py`…）、**`doc_*.py`**（每一节往 `port-plan.md` 追加章节的脚本，与正文一一对应）、**`patch_*.py` / `negctl_*.py`**（那一节改动源码与**反证**的脚本，留作记录） |
| `py/roguedeck_env/` | RL 环境的 Python 封装（`ctypes`，多进程 + 批量观察 + 吞吐基准） |
| `corpus/` | 对拍语料：`golden_v1.jsonl`、`hash_cases/*.txt`、`coverage.json`（份数以闸门输出为准） |
| `docs/` | `port-plan.md`（主计划 §1–§306）、`spec/`（19 份规格书）、`sts-wiki-gap.md`（缺口清单；"我们有多少"由 `native/gap_check.py` 重算，"还差哪些牌"由 `native/audit_card_gap.py` 与 wiki 卡表对账）、`coverage-matrix.md`（**生成物**：每个实体的 Implemented / TestNamed / HarnessOnly / SourceTie / DeclaredDeviation / Evidence，闸门 21；带 `--selftest` 的五个对抗性夹具）、`event-gaps.md`（事件侧缺口，§306 全面核对）、`mechanism-gaps-analysis.md`（两个机制缺口的分析记录与**关闭状态**）、**`ui-abi-audit.md`**（**新 UI 的 P0 契约基线**：52 个导出的实测行为、11 个真实场景的原始 dump、未验证清单；闸门 24 由 `native/ui_abi_dump.mjs --check` 守）、**`ui-p2-adapter.md`**（**P2 第一步：WASM 适配器**：四个角色的职责边界、148 格观察向量布局、"空槽 -1 vs 计数 0"两条坑、`_into` 参数顺序不统一等三个坑、闸门 28 的 10 条断言；单一构建产物由 `scripts/sync-wasm.mjs` 复制并记 sha256）、**`ui-next-p1.md`**（**P1 的 R3F PoC 实测**（§353 起为左右阵营布局 + 完整手势反馈）：中文可读性三档与不变量、字形图集体积（156 字形 / 微软雅黑 64 KB woff2 / DOM 覆盖层 0 字节）、1.85 MB→692 KB gzip 的体积账、闸门 25 抓到的五处"看起来对"与三处假绿；闸门 25 由 `native/ui_next_check.mjs` 守，`web-next/dist/` 入库所以不需要 npm）、**`ui-state-model.md`**（**场景 × 层 × 字段 × 接口**：每个 UI 字段的取值域、何时变、从哪个导出读，以及 15 条"3D 重写会撞上"的缺口；闸门 23 钉住"文档点名的导出都存在、每个导出都被登记"） |
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

---

## 10. 新前端 `web-next/`（P1–P7 的产物）

旧入口 `web/` 仍然保留（它是回归夹具，也是**存档/回放**的落点），但产品路径在 `web-next/`。

### 10.1 构建

```bash
cd web-next
npm ci                      # 只装前端依赖（three / r3f / vite / typescript）
node scripts/sync-wasm.mjs  # 把 web/rd_wasm.wasm 复制进 public/ 并记 sha256（**不重编**）
npm run build               # → dist/（产物入库，闸门不需要 npm 也能跑）
```

### 10.2 运行

```bash
node web-next/scripts/serve.mjs --port 8080                 # 新 UI（默认）
node web-next/scripts/serve.mjs --port 8080 --entry legacy   # 旧 UI（回退）
```

* `/`            → **新 UI**（`DEFAULT_ENTRY = "run"`；改成 `"legacy"` 即回退，单行 revert）
* `/legacy/*`    → 旧入口（永远可达）
* 这台服务器会校验 `wasm.json` 的 sha256 与磁盘 wasm 一致，不一致**拒绝启动**；
  `.wasm` 的 MIME 是 `application/wasm`（`instantiateStreaming` 的前提）。

### 10.3 测试

```bash
powershell -File tools/acceptance.ps1     # 42 道闸门（约 10 分钟）
node native/ui_parity_check.mjs           # 新旧入口同一内核（8 检查点 × 8 字段）
node native/ui_deploy_check.mjs           # MIME / 缓存 / 版本一致性 / 入口可切换
node native/ui_mobile_check.mjs           # 390×844 触控 + 安全区 + DPR 上限
node native/ui_soak_p6_check.mjs          # 重开/长局/重载/context lost/动效偏好
```

### 10.3b 素材库（`assets.html`）

```bash
python native/build_assets.py     # 内容变了就重跑：生成 web-next/src/assets/manifest.ts
npm run build && node web-next/scripts/serve.mjs --port 8080
# 打开 http://127.0.0.1:8080/assets.html
```

* **三维敌人**：16 种立体几何排列组合（`assets/geometry.ts`，纯数据），61 个敌人按清单分配原型；
* **二维元素**：卡/遗物/药水/状态各两位大写字母 + 调色板（`assets/registry.ts`）；
* 产品界面（奖励/商店/牌组/药水）已经在用这些徽章；三维敌人也已经在战斗里用上了。

### 10.4 已知缺口

* **回放**（§373 已补）：设置面板里"导出回放（至剪贴板）" + "导入回放（逐步对拍）"，
  分叉会报在第几步。仍是"只验不播"（导入后直接跳到脚本末尾，没有逐步重放演出）。
  **存档/回档**（闸门 44）与**自动存档**（闸门 49）都已补。
* **GLB 角色资产**：没有资产管线，只有程序化外观表 + 降级（`docs/ui-p5-beats.md` §6）。
* **幕间**（§370 已补）：幕数显示（顶栏 + 地图标题）+ **Boss 遗物三选一**（内核
  `offer_boss_relics` / `take_boss_relic`，`SC-13`）+ **幕间幕布**（§371，换幕时 1.6 秒的演出，
  点击穿透、不挡操作）。仍欠：真路径 E2E（要打赢 Boss，自动策略打不过第 16 层）。
* **真机**：移动端结论全部来自 CDP 仿真（`docs/ui-p6-devices.md` §1）。
* 事件的**子节点正文**仍是英文（没有官方中文来源，已计数）。

### 10.5 许可证

* 本仓库的参考实现是 `RogueDeck-Core`（C#，**MIT**），按 commit `fd43e68…` 冻结，
  `ref/` 是只读浅克隆且**不入库**。
* 前端依赖：`three`（MIT）、`@react-three/fiber`（MIT）、`@react-three/uikit`（MIT）、
  `vite`（MIT）、`typescript`（Apache-2.0）。
* 中文文案来自 `spire-archive.com/api/sts1`（从游戏文件解析的社区数据）与
  `slaythespire.wiki.gg`；**游戏内容本身的版权属于 Mega Crit**，本仓库只用于学习与研究。
