# RogueRust

---

一个 Slay the Spire 式的卡牌 Roguelike 工程：**战斗内核 + 运行层 + 内容编译器 + 浏览器前端 + 二十道聚合闸门**。

参考实现是 [`RogueDeck-Core`](https://github.com/)（C#，MIT），按 commit `fd43e68ab91f40b475b745725abb17134b951c51` 冻结。
移植的硬约束是三条：**能在 ESP32-P4 裸机上跑**（`no_std`、零分配、纯整数、`forbid(unsafe_code)`）、
**能多开当强化学习训练环境**（确定性、可快照、可回放）、**与参考实现逐字节一致的状态指纹**（对拍可证）。

> 主计划在 `docs/port-plan.md`（§1–§179，每一轮都留数字、记下被推翻的结论）。
> 这份 README 只交代**仓库现在是什么样**；为什么变成这样，在计划里。

---

## 1. 现在能玩到什么

一局完整的路径是通的：**出发 → 塔底祝福 → 地图 → 战斗 / 篝火 / 商店 / `?` 房 / 宝箱 → Boss → 下一幕**，
靠网页前端驱动（`web/index.html`，零构建）。

| 层 | 现状 |
|---|---|
| **战斗内核** | 21 个源文件、约 55.8k 行。出牌/结算/状态/意图/修饰器管线/效果程序 IR（栈式，70 条 opcode）/选择与目标/金色指纹 |
| **运行层** | 6 个模块、约 8.8k 行。地图（15 行 × 7 列 + Boss）、幕、牌组、金币、遗物、药水、奖励屏、商店、事件、篝火、**Ascension 0–20（9 条规则）**、**存档（单行文本 + CRC）**、**回放（动作序列 + 每步哈希）** |
| **内容** | 31 怪 / 22 遭遇 / **36 条卡行（19 张基础 + 17 张 `+`）** / 24 状态 / 65 敌人动作 / 13 遗物 / 26 条药水 / 9 事件 / 10 张起始牌。编译成 38,384 B 的 `rdcf` 镜像（core 镜像 31,728 B） |
| **前端** | `index.html`（战斗 + 运行层 + 存档 + 回放）、`map.html`（地图页），`wasm32` + **148** 个 `i32` 的战斗观察向量（另有 19 个 slot 的运行层观察） |
| **RL 环境** | `rd_env_*` ABI（env-abi.md）+ Python `ctypes` 封装（多进程、批量观察） |
| **裸机** | `riscv32imac-unknown-none-elf` 真链接成 ELF，镜像占用有闸门 |

**还不能**（诚实清单，逐条与 wiki 比对过，见 `docs/sts-wiki-gap.md`）：

* **Boss**：每幕只有一个（Slime Boss / The Champ / Time Eater），Boss 分裂只有 Slime Boss 有；
* **Ascension**：20 条里实现了 9 条。缺的那 11 条里，A2/3/4（伤害）与 A17/18/19（招式表）都要先给
  `EACT` 加维度；A1（精英更多）、A10（开局诅咒）、A12（升级牌变少）、A15（事件更糟）、A20（双 Boss）各自
  是运行层的一条小规则；
* **药水 26 / 33**：差的 7 瓶各要一样机制 —— 无色牌池、战斗中整手牌升级、自动打出、打两次、整手牌改费、
  死亡拦截、逃跑；
* **精英池只有 4 个遭遇**（第一幕 2、二三幕各 1），缺 Lagavulin / Book of Stabbing / Slavers / Nemesis /
  Reptomancer；
* **状态**：缺 Barricade / Blur / Entangled / Slow，以及"下一回合多抽/多能量"。

---

## 2. 目录

| 路径 | 内容 |
|---|---|
| `kernel/rd-core/` | **战斗内核本体**（`no_std`，21 个源文件）。语义冻结在 `docs/spec/SEMANTICS-v1.md` |
| `kernel/rd-run/` | **运行层**：地图/幕/牌组/金币/遗物/药水/商店/事件/篝火/Ascension/存档/指纹 |
| `kernel/rd-wasm/` | **ABI 层**：把内核 + 运行层变成 `rd_env_*` / `rd_run_*` 导出，编到 `wasm32` |
| `kernel/rd-firmware/` | 裸机启动壳（独立的 `[workspace]`，只在 riscv 目标上存在）——**只为证明链接得过** |
| `kernel/rd-hashdump` `rd-rngdump` `rd-sizeprobe` `rd-fightdump` | 诊断二进制：哈希对拍、洗牌序列对拍、RISC-V 代码体积、把一局战斗逐步打出来 |
| `tools/contentc/` | **Python 内容编译器**：JSON 源 → `rdcf` 二进制镜像（段目录 + 字符串池 + 效果程序 IR） |
| `tools/acceptance.ps1` | **聚合验收**：20 道闸门，一道红就整体红 |
| `web/` | 前端（零构建、零 CDN）：`index.html` + `ui_render.js`（战斗语义）+ `ui_panels.js`（14 个节点状态）+ `map.html` + `pixels.mjs`（像素度量）+ 门 13–20 |
| `native/RogueDeck.Oracle` `RogueDeck.Native` | C# 侧：对拍导出（NativeAOT）与 RL 环境 ABI |
| `native/*.py` | 三类：**对拍/校验驱动**（`fight_diff.py`、`gap_check.py`、`sts_content_check.py`…）、**`doc_*.py`**（每一节往 `port-plan.md` 追加章节的脚本，与正文一一对应）、**`patch_*.py` / `negctl_*.py`**（那一节改动源码与**反证**的脚本，留作记录） |
| `py/roguedeck_env/` | RL 环境的 Python 封装（`ctypes`，多进程 + 批量观察 + 吞吐基准） |
| `corpus/` | 对拍语料：`golden_v1.jsonl`、`hash_cases/*.txt`、`coverage.json`（份数以闸门输出为准） |
| `docs/` | `port-plan.md`（主计划 §1–§169）、`spec/`（19 份规格书）、`sts-wiki-gap.md`（缺口清单，数字由 `native/gap_check.py` 重算）、`vibe/`（外部评审记录） |
| `ref/` | 参考实现的浅克隆位置（**不在本仓库**，见 §6） |
| `sts/` | **早期 Python 原型**，已被 Rust 内核取代，保留作参照（不参与任何闸门） |

---

## 3. 内核的三条不变量

`rd-core` 里每一条代码都要满足：

1. **零分配**：没有 `Vec`/`String`/`Box`，所有容器是定长数组 + 计数；容量溢出是**错误**，不是截断。
2. **纯整数**：没有浮点。伤害/格挡/百分比全部走定点（`mul_div` 一类），因为裸机上 F/D 单元不可用。
3. **确定性**：所有随机走**命名随机流**（`rng.rs` 的计数器），状态指纹（`hash.rs`）覆盖全部字段；
   `forbid(unsafe_code)`。

运行层（`rd-run`）是 `std` 的，但同样保持"拒绝 ⇒ 一个字节都不改"（判据是整个结构体相等）。

---

## 4. 构建与验收

本机 shell 环境被剥空（`LOCALAPPDATA` / `ProgramFiles(x86)` / `PATH` 都不完整，`PATHEXT` 只有 `.CPL`），
所以一律走 `tools/` 下的包装脚本（**位置参数**）：

```powershell
# 单元测试
& .\tools\cargo.ps1 test -p rd-core -p rd-run -p rd-wasm --release

# 零告警是硬要求
& .\tools\cargo.ps1 clippy --all-targets -p rd-core -p rd-run -p rd-wasm

# 裸机目标
& .\tools\cargo.ps1 check --target riscv32imac-unknown-none-elf -p rd-core -p rd-run --release

# 聚合验收（20 道闸门，约 5 分钟）
& .\tools\acceptance.ps1

# 只跑快的（跳过 soak / 浏览器）
& .\tools\acceptance.ps1 -SkipSlow

# 内容重新编译（改 JSON 之后）
python tools/contentc/compile.py
```

### 20 道闸门

下表写的是每道闸门**必须打印出来的证据串**（`Invoke-Gate -MustMatch`），不是某次运行的数字。
数字每次跑都不同，抄进文档就会过期（§169）；要看数字就自己跑一遍，或看 `acceptance.ps1` 的表格输出。

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
| 11 | `rdcf-verify` | `N/N tables`（定长表的 `count × stride`） |
| 12 | `sts-content` | 内容自洽（怪/遭遇/卡/…逐项） |
| 13 | `wasm-rebuild` | wasm 是当前树的新构建 |
| 14 | `web-package` | 产物字节同一 + 脚本能解析 + 只调真导出 + 偏移铺满 |
| 15 | `web-ui` | 界面上每个数字 == 观察向量里那一格 |
| 16 | `web-map` | 画出来的图 == `rd-run` 生成的那张图 |
| 17 | `web-browser` | `BROWSER_TEST PASS` |
| 18 | `web-soak` | `SOAK_TEST PASS`（随机点每个启用中的控件） |
| 19 | `web-slice` | `ACT1_SLICE PASS`（自己算路线走遍每种节点） |
| 20 | `web-pixel` | `PIXEL_TEST PASS`（像素判据 + 故障注入自检） |

闸门的共同要求是**拿到证据串**，而不是只看退出码 —— 一个 `exit 0` 的闸门可能什么都没跑。
每道闸门存在的理由写在 `tools/acceptance.ps1` 的注释里，逐条来历在 `docs/port-plan.md`。

### 四条对拍（不在验收里）

与 C# 参考实现逐字节比状态。它们不进 20 道闸门，因为需要那份 111 MB 的第三方克隆和一份 NativeAOT 构建：

```powershell
python native/fight_diff.py      # 一场一场比：FIGHT_DIFF n/n
python native/hash_diff.py       # 规范文本 + 哈希
python native/rng_diff.py        # 洗牌序列
python native/env_check.py       # RL ABI
```

---

## 5. 二进制镜像与行尾

`tools/contentc/out/content.rdcf` 与 `content.core.rdcf`、`tools/contentc/packages/sts/out/content.sts*.rdcf`
是内容编译器的**产物**，同时是**测试夹具**（`rd-core` 的测试直接读，缺了就 panic 并提示重编译），
所以它们入库。同目录的 `layout.txt` / `report.md` / `validate*.json` 是给人看的派生报告，**不入库**。

`.gitattributes` 里是 `* -text`：全部验收都是**逐字节**的（规范文本、哈希语料、内容镜像），
任何行尾转换都会让它们失去可比性。

---

## 6. `ref/` 不在仓库里

`ref/RogueDeck-Core` 是约 111 MB 的第三方浅克隆（带它自己的 `.git`），按 commit 冻结：

```powershell
& 'C:\Program Files\Git\cmd\git.exe' clone --filter=blob:none --no-checkout <上游地址> ref/RogueDeck-Core
& 'C:\Program Files\Git\cmd\git.exe' -C ref/RogueDeck-Core fetch --depth 1 origin fd43e68ab91f40b475b745725abb17134b951c51
& 'C:\Program Files\Git\cmd\git.exe' -C ref/RogueDeck-Core checkout fd43e68ab91f40b475b745725abb17134b951c51
```

**只读**，不要在里面跑 `dotnet`（它自己的构建会污染工作树）。
