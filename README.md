# sts-tui —— 把 RogueDeck-Core 的战斗内核重构成可嵌入（no_std）+ 可并行（RL）的 Rust 内核

一个 Slay-the-Spire 式卡牌战斗内核的移植工程：参考实现是 `RogueDeck-Core`（C#，MIT），
目标是把它重写成**能在 ESP32-P4 裸机上跑**、**能多开当强化学习训练环境**的 Rust `no_std` 内核，
并保留与参考实现**逐字节一致**的状态指纹。

## 目录

| 目录 | 内容 |
|---|---|
| `kernel/` | Rust workspace。`rd-core` 是内核本体（`src/*.rs`）；`rd-firmware` 是裸机镜像（独立的 `[workspace]`）；`rd-hashdump` / `rd-rngdump` / `rd-sizeprobe` 是诊断二进制 |
| `docs/port-plan.md` | **主计划**，§1–§43 逐轮记录（每一轮做了什么、哪些结论被推翻、为什么） |
| `docs/spec/` | 规格书：`SEMANTICS-v1.md`（语义冻结）、`combat-state-and-turn.md`、`effect-program-ir.md`、`modifier-pipeline.md`、`content-schema.md`、`content-binary-format.md`、`play-card-flow.md`、`battle-loop-hooks.md`、`enemy-intent.md`、`oracle-abi.md`、`env-abi.md`、`card-selection-recon.md` |
| `tools/` | `contentc/`（Python 内容编译器，产出 `out/*.rdcf` 镜像）、`cargo.ps1` / `dn.ps1` / `acceptance.ps1` / `verify.ps1` 等本机包装脚本、若干度量脚本 |
| `corpus/` | 对拍语料：`golden_v1.jsonl`（129 条）、`hash_cases/*.txt`（85 份）、`coverage.json` |
| `native/` | C# 侧：`RogueDeck.Oracle`（差分对拍导出，NativeAOT）、`RogueDeck.Native`（RL 环境 ABI），以及语料生成/对拍脚本 |
| `py/roguedeck_env/` | RL 环境的 Python 封装（`ctypes`，支持多进程与批量观察） |
| `ref/` | 参考实现的浅克隆位置（**不在本仓库里**，见下） |

## 构建与验收

本机 shell 环境被剥空（`LOCALAPPDATA` / `ProgramFiles(x86)` / `PATH` 都不完整），
所以所有命令行工具都走 `tools/` 下的包装脚本（**位置参数**，不要写成 `-ArgLine`）：

```powershell
# 单元测试（内核）
& .\tools\cargo.ps1 test -p rd-core --release

# clippy（零告警是硬要求）
& .\tools\cargo.ps1 clippy -p rd-core --all-targets --release

# 裸机目标（riscv32imac-unknown-none-elf）
& .\tools\cargo.ps1 check -p rd-core --target riscv32imac-unknown-none-elf --release

# 聚合验收（9 道闸门：单测数下限 / 语料往返 / 裸机 / clippy / 固件链接 / 固件体积 /
#              覆盖 / 黄金基线 / RL 环境冒烟）
& .\tools\acceptance.ps1
```

## `ref/` 不在仓库里

`ref/RogueDeck-Core` 是一份约 111 MB 的第三方浅克隆（含它自己的 `.git`），按 commit 冻结：

```
fd43e68ab91f40b475b745725abb17134b951c51
```

需要它时自己取（**只读**，不要在里面跑 `dotnet`）：

```powershell
& 'C:\Program Files\Git\cmd\git.exe' clone --filter=blob:none --no-checkout <上游地址> ref/RogueDeck-Core
& 'C:\Program Files\Git\cmd\git.exe' -C ref/RogueDeck-Core fetch --depth 1 origin fd43e68ab91f40b475b745725abb17134b951c51
& 'C:\Program Files\Git\cmd\git.exe' -C ref/RogueDeck-Core checkout fd43e68ab91f40b475b745725abb17134b951c51
```

## 关于仓库里那两个二进制镜像

`tools/contentc/out/content.rdcf`（154 KB）与 `content.core.rdcf`（84 KB）是内容编译器的**产物**，
但它们同时是**测试夹具**：`rd-core` 的测试直接读它们（缺了就 panic 并提示重新编译），
所以它们是提交进来的。同一目录下的 `layout.txt` / `report.md` / `validate*.json|md`
是给人看的派生报告，**不入库**（可由 `python tools/contentc/compile.py` 重新生成）。

## 行尾

`.gitattributes` 里是 `* -text`：本项目的全部验收都是**逐字节**的（规范文本、哈希语料、内容镜像），
任何行尾转换都会让它们失去可比性，所以一律不做转换。
