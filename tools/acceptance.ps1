# 合验收器：一条命令跑完所有闸门，用**真实退出码**下判定。
#
# 为什么需要它：这个项目的验收分散在 cargo / python / dotnet 三套工具链里，共十来个闸门。
# 逐个手跑的问题是**会漏**，而且漏掉的那个一定是最后加的那条。更早的教训是：
# 我的过滤命令曾把 cargo 的 `=== EXIT n ===` 行滤掉、打印了外层 shell 的退出码（恒 0），
# 于是**编译失败被报成绿色**。所以这里的每条闸门都只认子进程的真实退出码。
#
# 用法:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\acceptance.ps1
#   ... -SkipSlow           # 跳过 RL 吞吐基准（约 1-2 分钟）
#   ... -UnitsFloor 225     # 单元测试数量下限（加测试时顺手抬高它）
#
# 退出码：0 = 全过；1 = 有闸门失败；2 = 环境/前置缺失（**不等于通过**）。

param(
  [switch]$SkipSlow,
  [int]$UnitsFloor = 1233
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\env.ps1"

$ROOT = Split-Path $PSScriptRoot -Parent
$PS = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$PY = 'C:\Users\TK11\miniforge3\python.exe'
$CARGO = 'C:\Users\TK11\.cargo\bin\cargo.exe'
$TARGET_DIR = Join-Path $ROOT 'kernel\target\acceptance'

function Invoke-Gate {
  param(
    [string]$Name,
    [string]$Exe,
    # ⚠️ 这个参数**不能**叫 `$Args`：`$args` 是 PowerShell 的自动变量（未绑定参数的数组），
    # 声明同名参数会让 `$psi.Arguments = $Args` 拿到那个空数组 —— cargo 于是收到零个参数、
    # 打印 `cargo help` 并以 0 退出。八个闸门全"通过退出码"、全"找不到证据"，
    # 全靠下面那条 MustMatch 才没被报成绿色。**自动变量名不要拿来当参数名。**
    [string]$ArgLine,
    [string]$Workdir,
    [string]$MustMatch = '',       # 输出里必须出现的正则（证明它真的跑了，而不是空过）
    [string]$MustNotMatch = '',    # 输出里不许出现的正则
    [hashtable]$ExtraEnv = @{},
    [int]$TimeoutSec = 900
  )
  $psi = [Diagnostics.ProcessStartInfo]::new()
  $psi.FileName = $Exe
  $psi.Arguments = $ArgLine
  $psi.WorkingDirectory = $Workdir
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
  $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
  foreach ($k in $StandardEnv.Keys) { $psi.EnvironmentVariables[$k] = $StandardEnv[$k] }
  $psi.EnvironmentVariables['CARGO_HOME'] = 'C:\Users\TK11\.cargo'
  $psi.EnvironmentVariables['RUSTUP_HOME'] = 'C:\Users\TK11\.rustup'
  $psi.EnvironmentVariables['CARGO_TERM_COLOR'] = 'never'
  $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
  $psi.EnvironmentVariables['PATH'] = 'C:\Users\TK11\.cargo\bin;C:\Windows\System32;C:\Windows;' +
                                      'C:\Users\TK11\AppData\Local\Microsoft\dotnet'
  foreach ($k in $ExtraEnv.Keys) { $psi.EnvironmentVariables[$k] = $ExtraEnv[$k] }

  $p = [Diagnostics.Process]::Start($psi)
  # 两个流都必须**并发**读：串行读 stdout 再读 stderr，在子进程往 stderr 写超过约 4KB 管道缓冲
  # 时会双向死锁（cargo 冷构建的进度全在 stderr）。这个坑在 cargo.ps1 与 verify.ps1 里都踩过。
  $oT = $p.StandardOutput.ReadToEndAsync()
  $eT = $p.StandardError.ReadToEndAsync()
  $finished = $p.WaitForExit($TimeoutSec * 1000)
  if (-not $finished) { try { $p.Kill() } catch { } }
  $out = $oT.Result + "`n" + $eT.Result
  $code = if ($finished) { $p.ExitCode } else { 124 }

  $notes = @()
  $ok = ($code -eq 0)
  if (-not $finished) { $notes += '超时，已杀进程' }
  if ($MustMatch) {
    if ($out -notmatch $MustMatch) { $ok = $false; $notes += "输出里找不到 /$MustMatch/（跑了但没做事？）" }
  }
  if ($MustNotMatch -and $out -match $MustNotMatch) { $ok = $false; $notes += "输出里出现 /$MustNotMatch/" }

  # 从输出里抓一个数字当"证据"（比如测试条数 / 语料份数），让人一眼看到它真的做了事。
  $evidence = ''
  $matchLine = ''
  if ($MustMatch -and ($out -match $MustMatch)) { $matchLine = $matches[0] }
  foreach ($pat in @('(\d+) case\(s\)', '(\d+)/19', '(\d+) passed', '(\d+/\d+ images)',
                     '(\d+/\d+ tables)', '(\d+ monsters)', '(\d+) clicks',
                                          # P7：对等 + 部署（必须排在通用 '\d+ fields' 之前：循环 break-on-first-match）
                     '(UI_PARITY PASS checkpoints=\d+ cells=\d+ sha=match old=alive)',
                     '(UI_DEPLOY PASS entry=run assets=\d+ wasm=application/wasm cache=immutable-for-hashed version=match)',
                     # 第十五轮 Review §2：冻结边界
                     '(UI_FREEZE PASS entries=\d+ refused=\d+ sticky=1)',
                     # 第十五轮 Review §6：存档 / 回档
                     '(UI_ARCHIVE PASS bytes=\d+ refused=\d+ roundtrip=1)',
                     '(rows=\d+, tests=\d+)', '(\d+ fields)', '(exports=\d+ mentioned=\d+)', '(exports \d+, runObs 19)',
                     '(\d+/\d+ card\(s\) painted)',
                     # P1 的 R3F PoC：真提交数 / 真回弹数 / 触摸与模态隔离 / 最小字号
                     '(cards=10 enemies=2 commits=\d+ rebound=\d+ touch=1 modal-isolation=1 minTitle=\d+px)',
                     # 纯状态机回归：修复后的三条断言（判据是 PASS 串本身）
                     '(P1_REVIEW13_REPRO PASS)',
                     # 纯函数回归：队形/命中/状态机
                     '(UI_PURE PASS formation=0\.\.6 hit=\d+ machine=\d+ layout=\d+ decode=\d+ choice=\d+ i18n=\d+ rows=\d+)',
                     # P2：真 wasm 接线
                     '(UI_WASM PASS exports=\d+ content=0x[0-9a-f]{8} hand=\d+ enemies=\d+)',
                     # P2：主页面接真 wasm 之后 UI 与内核一致
                     '(UI_WASM_UI PASS mode=wasm hand=\d+ energy=\d+ enemy0=\d+->\d+)',
                     # P2：待决选牌与 beat
                     '(UI_WASM_CHOICE PASS source=\d+ kind=\d+ options=\d+)',
                     # P2：定向夹具
                     '(UI_WASM_FIXTURES PASS duplicate=\d+ zero-energy=1 slot-stable=1)',
                     # P2：X 费扣能量
                     '(UI_WASM_XCOST PASS seed=\d+ card=\w+ energy=\d+->0 damaged=\d+)',
                     # P3：场景判定（纯函数）与端到端闭环
                     '(UI_SCENE PASS order=\d+\+\d+ pending=\d+ exhaustive=\d+ rows=\d+)',
                     '(UI_NEXT_LOOP PASS nodes=\d+ steps=\d+ scene-chain=SC-00>SC-01>SC-02>SC-03>SC-03b>SC-04>SC-02)',
                     # P4：展示逻辑 + 端到端旅程
                     '(UI_P4_MODELS PASS campfire=\d+ effects=\d+ shelves=\d+ picker=\d+ potions=\d+)',
'(UI_NEXT_P4 PASS floors=\d+ screens=[a-z,-]+ )',
                     # P5：Beat 演出 + 幕间推进
                     '(UI_BEATS PASS kinds=\d+ unknown=degraded dropped=counted skip=clears reduced=quiet assets=\d+)',
'(UI_NEXT_P5 PASS kinds=[0-9,]+ skip=\d+ motion-off=\d act-refusal=-?\d+)',
                     # P6：移动端 + 稳定性
                     '(UI_MOBILE PASS targets=\d+ min=\d+ dpr-cap=[\d.]+ backing=\d+ safe-top=\d+ drag=[01])',
'(UI_SOAK_P6 PASS restarts=\d+ steps=\d+ heap=\d+KB->\d+KB context-lost=\d motion-persisted=\d)',
                     # 素材流水线：清单覆盖 + 渲染
                     '(UI_ASSETS PASS enemies=\d+ cards=\d+ relics=\d+ potions=\d+ statuses=\d+ archetypes=\d+ collisions=\d+)',
                     '(UI_ASSETS_RENDER PASS archetypes=\d+ enemies=\d+ cards=\d+ badges=4tables lit=\d+)',
                     # §370 幕间：幕数 + Boss 遗物三选一
                     '(UI_ACT PASS act=\d+ offer=\d+ taken=\w+)',
                     # §2.3 幕间幕布
                     '(UI_CURTAIN PASS cases=\d+ auto=1 click=1)',
                     # §372 自动存档 + 产物可得
                     '(UI_SAVE PASS bytes=\d+ restored=1 corrupt=1)',
                     '(UI_DISTRIBUTABLE PASS wasm=\d+ tracked=2 assets=\d+ play=ok)',
                     # §373 回放：导出 / 导入逐步对拍
                     '(UI_REPLAY PASS bytes=\d+ steps=\d+ diverged=\d+)',
                     # §374 卡面：样式化 + 位置 + 内容 id
                     '(UI_CARDFACE PASS cards=\d+ offset=\d+px letters=[A-Z,]+)',
                     # §375 端口占用：回退 + 自检
                     '(UI_SERVE_PORT PASS fallback=1 port=\d+ selfcheck=ok)')) {
    $m = [regex]::Match($out, $pat)
    if ($m.Success) { $evidence = $m.Value; break }
  }
  # 兜底：MustMatch 匹配上了但表里没有对应 pattern ⇒ 用匹配文本的首行顶上。
  # **证据列为空本身就是一个症状**（上一轮闸门 24 就是这么漏的），不能让它是默认状态。
  if (-not $evidence -and $matchLine) {
    $firstLine = ($matchLine -split "`r?`n")[0]
    if ($firstLine.Length -gt 26) { $firstLine = $firstLine.Substring(0, 26) }
    $evidence = $firstLine
  }

  [pscustomobject]@{
    Gate = $Name; Exit = $code; Ok = $ok; Evidence = $evidence
    Notes = ($notes -join '; ')
    Output = $out
  }
}

$results = @()

Write-Output ("=" * 78)
Write-Output "sts-tui 聚合验收"
Write-Output ("=" * 78)

Write-Output "`n[1/53] 单元测试 + 语料逐字节回环（Rust 内核）"
# `-p rd-core -p rd-run`：run 层是新 crate，它自己的 8 条测试若不加进这条闸门，就没人跑它们。
# 于是"条数下限"必须对**两个 crate 加起来**比 —— 只取第一个 `N passed` 会让新 crate 的测试
# 全绿或全红都对闸门没有影响（这就是"覆盖不到的地方看起来最绿"）。
$r = Invoke-Gate -Name 'rust-units' -Exe $CARGO `
  -ArgLine "test -p rd-core -p rd-run -p rd-wasm --release --target-dir `"$TARGET_DIR`" -- --test-threads=1" -Workdir (Join-Path $ROOT 'kernel') `
  -MustMatch 'test result: ok\. \d+ passed; 0 failed' -MustNotMatch 'test result: FAILED'
$results += $r
$passed = 0
foreach ($m in [regex]::Matches($r.Output, '(\d+) passed')) { $passed += [int]$m.Groups[1].Value }
$r.Evidence = "$passed passed"
if ($r.Ok -and [int]$passed -lt $UnitsFloor) {
  $r.Ok = $false; $r.Notes += "测试数 $passed < 下限 $UnitsFloor"
}
$results[-1] = $r

Write-Output "[2/53] 语料回环份数（确认不是空扫）"
$r = Invoke-Gate -Name 'corpus-roundtrip' -Exe $CARGO `
  -ArgLine "test -p rd-core --release --target-dir `"$TARGET_DIR`" corpus -- --nocapture" `
  -Workdir (Join-Path $ROOT 'kernel') -MustMatch 'case\(s\) reproduced byte-for-byte'
$results += $r

Write-Output "[3/53] 裸机目标编译（riscv32imac-unknown-none-elf）"
$results += Invoke-Gate -Name 'rust-baremetal' -Exe $CARGO `
  -ArgLine "check --target riscv32imac-unknown-none-elf -p rd-core -p rd-run --release --target-dir `"$TARGET_DIR`"" `
  -Workdir (Join-Path $ROOT 'kernel') -MustMatch 'Finished'

Write-Output "[4/53] clippy"
$results += Invoke-Gate -Name 'rust-clippy' -Exe $CARGO `
  -ArgLine "clippy --all-targets -p rd-core -p rd-run -p rd-wasm --target-dir `"$TARGET_DIR`"" -Workdir (Join-Path $ROOT 'kernel') `
  -MustMatch 'Finished'

Write-Output "[5/53] 真链接成裸机 ELF 镜像"
$fw = Join-Path $ROOT 'kernel\rd-firmware\link.x'
$results += Invoke-Gate -Name 'firmware-link' -Exe $CARGO `
  -ArgLine "rustc --release --target riscv32imac-unknown-none-elf --manifest-path rd-firmware/Cargo.toml -- -C link-arg=-T$fw" `
  -Workdir (Join-Path $ROOT 'kernel') -MustMatch 'Finished'

Write-Output "[6/53] 镜像占用（自带陈旧守卫）"
$results += Invoke-Gate -Name 'firmware-size' -Exe $PY `
  -ArgLine (Join-Path $ROOT 'tools\firmware_size.py') -Workdir $ROOT -MustMatch '非易失存储'

Write-Output "[7/53] 覆盖门禁"
$results += Invoke-Gate -Name 'coverage-gate' -Exe $PY `
  -ArgLine (Join-Path $ROOT 'native\coverage_check.py') -Workdir $ROOT -MustMatch '19/19'

Write-Output "[8/53] golden 基线逐字节一致"
$ga = Join-Path $ROOT 'corpus\golden_v1.jsonl'
$gb = Join-Path $ROOT 'corpus\baseline\golden_v1.jsonl'
$same = ((Get-FileHash $ga -Algorithm SHA256).Hash -eq (Get-FileHash $gb -Algorithm SHA256).Hash)
$results += [pscustomobject]@{
  Gate = 'golden-baseline'; Exit = $(if ($same) { 0 } else { 1 }); Ok = $same
  Evidence = "$((Get-Content $ga).Count) 行"; Notes = $(if ($same) { '' } else { 'SHA-256 不一致' }); Output = ''
}

Write-Output "[9/53] RL 环境冒烟（多开 + 确定性）"
$results += Invoke-Gate -Name 'env-smoke' -Exe $PY -ArgLine '-m roguedeck_env.bench' `
  -Workdir (Join-Path $ROOT 'py') -MustMatch '多开吞吐与可复现性均通过' `
  -ExtraEnv @{ PYTHONPATH = (Join-Path $ROOT 'py') } -TimeoutSec 1800

Write-Output "`n[10/53] 内容镜像 byte-identity（用当前编译器重编源文档 == 钉死的 SHA）"
# 为什么这条闸门必须存在：本文件上面的对拍闸门（CARD_DIFF / FIGHT_DIFF / ENEMY_DIFF /
# corpus / coverage / golden）全部钉在 `tools/contentc/out/content.core.rdcf` 这一份镜像上。
# 为了支持 StS 内容去改 compile.py，后果**不是**"某条测试变红"，而是所有对拍静默地改为
# 比另一份内容、并继续报绿。所以这里钉死两个镜像 + 源文档的 SHA-256：
#   源文档变了  -> 先说清楚是谁改的（ref/ 是只读镜像，本闸门不写它）
#   编译器变了  -> 必须在同一个提交里要么修回去，要么显式 `verify_bytes.py --repin` 并说明理由
#   只有 out/ 旧 -> python tools/contentc/build.py --package roguedeck
# 失败时 verify_bytes.py 自己打印"期望 vs 实际"与首个差异字节落在哪个 section，并以非零退出。
$results += Invoke-Gate -Name 'contentc-bytes' -Exe $PY `
  -ArgLine (Join-Path $ROOT 'tools\contentc\verify_bytes.py') -Workdir $ROOT `
  -MustMatch 'CONTENTC_BYTES PASS \(2/2 images, 1/1 source\)' -TimeoutSec 600

Write-Output "[11/53] 内容镜像结构不变量（独立解读字节：段目录 + 7 张定长表的 count×stride）"
# 为什么这条闸门必须存在：tools/rdcf_verify.py 曾经**静默失效** —— 它从 variants[name] 里取
# tables（tables 其实在 manifest 顶层），于是 5 张表的 count×stride 检查一次都没跑成，
# 脚本只记一条"观察"并 exit 0；而它自己抄的那份 stride 常量（28/36/16/20）也是错的。
# 修好之后"通过"有两条缺一不可的条件：
#   * 退出码 0；
#   * 输出里有 5/5 tables 与 10 count×stride checks —— 少一张表就是少一项检查，
#     不许用"跳过"换来绿色。喂它一份手改过的 manifest 副本（tables.cards.count=61 之类）
#     会以非零退出并指名是哪张表。
$results += Invoke-Gate -Name 'rdcf-verify' -Exe $PY `
  -ArgLine (Join-Path $ROOT 'tools\rdcf_verify.py') -Workdir $ROOT `
  -MustMatch 'RDCF_VERIFY PASS \(2/2 variants, 8/8 tables, 16 count×stride checks, [0-9]+ table rows, 6 term-shape checks' -TimeoutSec 300

Write-Output "`n[12/53] StS 内容包自洽（不变量表 + 两份镜像逐键回读 + 交叉引用）"
# 为什么这条闸门必须存在：第 10 道 verify_bytes.py **只钉 `packages/roguedeck/**`**。
# 于是 `packages/sts/**` 的源文档被改坏时，上面已知的 11 道闸门一条都不会红 ——
# 这正是"覆盖不到的地方看起来最绿"。三层各补一种假绿（native/sts_content_check.py
# 顶部写了完整理由，这里只重复结论）：
#   INV   源文档里每个数字对 `docs/spec/sts-act1-inventory.md`。改源文档 + 重编镜像
#         （两者互相一致、一起错）只有这一层能红 —— 所以下面的 MustMatch 除了 PASS
#         行还钉住 weak pool / full roots / core SEC_IDX：某个 check 被删掉时输出里
#         少一行 `ok`，光看退出码看不出来。
#   ROUND 两份镜像逐键读回源文档，键的存在性也算（镜像多出一个事实也是红）。
#   XREF  deck/encounter/roster/action/STAT/SEC_IDX 互相闭合。
# 退出码 2 = 前提缺失或镜像比源文档旧（陈旧镜像是最贵的一种绿色）。
$results += Invoke-Gate -Name 'sts-content' -Exe $PY `
  -ArgLine (Join-Path $ROOT 'native\sts_content_check.py') -Workdir $ROOT `
  -MustMatch 'weak pool[\s\S]*inert keys[\s\S]*full roots[\s\S]*core SEC_IDX[\s\S]*STS_CONTENT PASS \(monsters \d+, encounters \d+, deck \d+, statuses \d+, cards \d+, enemy_actions \d+' `
  -TimeoutSec 300

Write-Output "`n[13/53] 覆盖矩阵：每个实体被验证到哪一步（Implemented / RuntimeTested / WikiVerified / Deviation / Evidence）"
# 为什么这条闸门必须存在：这一页是**生成物**（`docs/coverage-matrix.md`），它回答"`chosen` 的 HP
# 错了很久、`spiker.spike` 根本不是 wiki 的那一招 —— 当时哪一道闸门能看出来？"。答案是都不能：
# 闸门看不见 wiki，但闸门**能**看见"某个实体没有任何来源、没有任何测试、也没有声明过偏差"。
# 三件必须红的事：
#   (a) 盘上的矩阵与重新生成的结果不一致（有人手改了，或内容变了没人重编这一页 —— 陈旧的绿）；
#   (b) 内容里长出一条**没人引用**的行（`orphan`）、或 gap 文档里的偏差指向一个不存在的 id
#       （偏差表漂了）、或某份 wiki dump 找不到对应怪物；
#   (c) 扫描器自己坏了：具名测试少于 500 条、或探针 id（`spiker` / `chosen` / `standard.hex` /
#       `bash`）扫不到测试。**(c) 是最要紧的一条** —— 扫描器一坏，整页会变成全 `harness`、
#       看起来照样"有证据"，而它其实什么都没读。实测过一次：`strip_rust` 删字符导致函数体被
#       切在很早的 `}` 上，33 瓶药水全报"没有任何证据"。
$results += Invoke-Gate -Name 'coverage-matrix' -Exe $PY `
  -ArgLine ((Join-Path $ROOT 'native\coverage_matrix.py') + ' --check --selftest') -Workdir $ROOT `
  -MustMatch 'COVERAGE_MATRIX PASS \(rows=\d+, tests=\d+, fresh\)' -TimeoutSec 300

Write-Output "`n[14/53] 重编网页那一份 .wasm（web/** 是仓库里唯一被手工 Copy-Item 进来的二进制产物）"
# 为什么这条闸门必须存在：`web/rd_wasm.wasm` 被三方引用 —— index.html 硬编码的 122 格偏移、
# smoke.mjs 的导出手抄清单、README 里钉死的字节数 —— 而它**不在 cargo 的依赖图里**：
# 源码改了不重编，它照样绿。（真实测到的两种"时间说谎"：Copy-Item 恢复文件会把 mtime 一起
# 恢复；而只改一行注释又会让产物看起来比新源码更旧。所以 [+5] 的判据是**字节**，不是时间。）
$results += Invoke-Gate -Name 'wasm-rebuild' -Exe $CARGO `
  -ArgLine "build -p rd-wasm --release --target wasm32-unknown-unknown" -Workdir (Join-Path $ROOT 'kernel') `
  -MustMatch 'Finished' -TimeoutSec 600

Write-Output "[15/53] 页面 + 产物：字节同一 + 脚本能解析 + 只在真导出上调用 + 偏移仍铺满"
# 为什么这条闸门必须存在：上面 13 道闸门**没有一道看 web/index.html**。实测过一次把页面改坏
# （语法错），十二道闸门全绿 —— 因为所有闸门都止步于 .wasm。这条补的就是那一段：
#   (a) web/rd_wasm.wasm 与刚才那次重编**逐字节相同**，不同就打印两边的 sha 与复制命令；
#   (b) index.html 的 <script> 能被 node 的解析器吃下；
#   (c) 它调用到的每个 ex.xxx 都是模块真有的导出（与 smoke.mjs 里那张手抄清单互为反方向）；
#   (d) 页面硬编码的 122 格偏移还铺得满（加一个状态轴就得挪后面每一个偏移）。
# 四条都各自变异过一遍并确认会红（语法错 / OFF_HAND 漂 2 / 调不存在的导出 / 产物改一个字节）。
# ⚠️ 它仍然**不**能证明 Rust 侧的排布没搬过家：那一层只有真浏览器能看出来（见 smoke.mjs 头）。
$results += Invoke-Gate -Name 'web-package' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\smoke.mjs') -Workdir $ROOT -MustMatch 'WEB_SMOKE PASS' -TimeoutSec 600

Write-Output "[16/53] 界面渲染的**语义**（不是语法）：每一格显示的数 == 观察向量里那一格"
# 为什么这条闸门必须存在：上面 14 道闸门里，闸门 14 只证明页面**能解析、只在真导出上调用、
# 偏移铺得满**。它证明不了任何一格显示得对 —— 把 `o[H.HP]` 写成 `o[H.HP_MAX]`，14 道闸门全绿。
# 实测过一次：把渲染里的血量格改成读上限，整套验收没有任何一条会红。
# 这一条把"哪一格显示什么"从 `web/index.html` 搬进 `web/ui_render.js`（纯函数），
# 再用真 `.wasm` 驱动它们，逐格与观察向量比对。9 条变异各红一次：
#   血量格读上限 / 敌人血量格读上限 / 意图伤害恒 null / 卡名恒占位 / 双目标走直打快路 /
#   页面不再调用 describe / 状态计数恒 0 / 敌人恒 alive / 能量格读上限。
# ⚠️ 它**不覆盖 DOM**：点击处理器、模板字符串、CSS 仍然只有真浏览器能验（见 web/README.md）。
$results += Invoke-Gate -Name 'web-ui' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\ui_test.mjs') -Workdir $ROOT -MustMatch 'UI_RENDER PASS' -TimeoutSec 600

Write-Output "[17/53] 地图页：画出来的东西**就是** rd-run 生成的那张图（逐节点、逐边、逐格光照）"
# 为什么这条闸门必须存在：闸门 15 盯的是**战斗**那一套导出（`rd_env_*`）。地图走的是
# `env-abi.md` §11 的另一套（`rd_run_*`），所以上面 15 道闸门里**没有一道**看它 ——
# 把"可达"改成"前 N 个节点"、把行读成列、把游标标记删掉，15 道闸门全绿。
# 这条闸门把「哪一格画什么」搬进 `web/map_render.js`（纯函数：访问器 → 视图 → SVG 字符串），
# 再用真 `.wasm` 驱动，并且**走完整张地图每一步都重新对账**（不是只在开局对一次）——
# 第一版就只在开局对了一次，于是上面那两个变异溜过去了。
# 6 条变异全部真的红：行读成列 / 可达集合改成"前 N 个" / 出边目标整体 +1 /
# 页面自己编了一套 kind 名 / 游标永不标记 / 页面不再调用 svgMarkup。
# ⚠️ 它**不覆盖 DOM**：SVG 上的点击处理器仍然只有真浏览器能验。
$results += Invoke-Gate -Name 'web-map' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\map_test.mjs') -Workdir $ROOT -MustMatch 'MAP_RENDER PASS' -TimeoutSec 600

# 门 17：**真浏览器**。前面那些 web 门都只跑纯模块，DOM 上的点击处理器只有真浏览器能验 —— 而三次 P0
# （祝福面板被吃掉、拒绝消息擦掉按钮、日志把祝福的伤害算在卡上）都是"点一下才知道"的。
# 零依赖：node:http 起静态服务 + 系统 Chrome 的 CDP（Node 22 自带 WebSocket），断言的是**渲染出来的文字**，
# 不做截图像素比对（那个在不同字体/缩放下太脆）。
Write-Output "`n[18/53] 真浏览器：点下去，断言渲染出来的文字"
$results += Invoke-Gate -Name 'web-browser' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\browser_test.mjs') -Workdir $ROOT -MustMatch 'BROWSER_TEST PASS' -TimeoutSec 600

# 门 18：**整局随机 soak**（§151）。门 17 是一条**写死**的路径，而 §150 的药水 bug 在它后面活了三个
# 小节 —— 因为那条路径不点药水。这一道用带种子的 PRNG 随机点**每一个启用中的控件**，每点一次问一句
# "有东西变了吗"：死按钮违反的正是这一条，而它不关心是哪个按钮。另外断言"页面没抛异常"与"走过若干种
# 界面"（商店/篝火/宝箱/事件…），否则"随机点 300 次什么都没坏"可能只是没点到东西。
Write-Output "`n[19/53] 随机 soak：每个启用中的控件点一下都必须有反应"
$results += Invoke-Gate -Name 'web-soak' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\soak_test.mjs') -Workdir $ROOT -MustMatch 'SOAK_TEST PASS' -TimeoutSec 900

# 门 19：**一幕垂直切片**（§161.8，REVIEW §六 第 3 步）。
# 门 17 是一条写死的路，门 18 是随机点 —— 两者都不能证明
# "商店能买东西""精英会给遗物""篟火能打铁"。
# 这一道在固定种子上**自己算路线**走到每一种节点。
Write-Output "`n[20/53] 一幕垂直切片：自己算路线走遍每种节点"
$results += Invoke-Gate -Name 'web-slice' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\act1_slice.mjs') -Workdir $ROOT `
  -MustMatch 'ACT1_SLICE PASS' -TimeoutSec 900

# 门 20：**像素**（§168）。前面 19 道都在问"状态对不对 / 文字对不对"，没有一道问"**画出来是什么样**"——
# 一个把文字画成背景色的主题、一张 DOM 里有而屏幕上没有的牌、一行溢出面板的卡，都能让 19 道全绿。
# 这一道**不比基线图**（字体/缩放一变就红，而且人只会重录它），只断言可度量的性质：
# 棋盘上确实有墨、墨与底色**看得清**、每张牌自己的矩形在"藏起卡牌"前后**变过**、卡牌没有画到条带外面、
# 两次同状态截图**逐像素相同**。最后一段是**故障注入**：把 `--ink` 设成底色、藏掉一张牌、压扁手牌条带、
# 藏掉棋盘，逐个确认**同一批探测器会红** —— 否则"像素门通过"什么也没证明。
Write-Output "`n[21/53] 像素：画出来是什么样（不比基线，只断性质）"
$results += Invoke-Gate -Name 'web-pixel' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\pixel_test.mjs') -Workdir $ROOT `
  -MustMatch 'PIXEL_TEST PASS' -TimeoutSec 600

# 门 22：**`RunState` 的字段必须同时进存档与指纹**（§308，审阅报告 §2）。
# 为什么这句必须是一道闸门而不是一条注释：`archive.rs` 的 round-trip 判据是
# `assert_eq!(restored, run)`，看着最硬，但它的夹具曾经只设了六个字段 —— 于是 18 个新字段
# 全在默认值，"漏还原一个字段就红"这句话是假的（实测：漏 18 个，它照样绿）。
# 这一道做两件机器能做的事：穷尽读 `pub struct RunState` 的字段表，逐个要求它出现在
# `write_payload` 与 `hash.rs` 里；豁免必须写下理由，且豁免表里的字段一旦被删就红。
# 它证明的只是"点过名"（编译才证明"打得开"），但"没点名"这一半正是漏的 18 个。
Write-Output "`n[22/53] RunState 字段清点：每一个字段都进存档、都进指纹"
$results += Invoke-Gate -Name 'state-fields' -Exe $PY `
  -ArgLine ((Join-Path $ROOT 'native\check_state_fields.py') + ' --check') -Workdir $ROOT `
  -MustMatch 'STATE_FIELDS PASS' -TimeoutSec 120

Write-Output "`n[23/53] UI 状态模型：文档点名的每个导出都存在，每个导出都被登记"
# 为什么这条必须是一道闸门：`docs/ui-state-model.md` 是"3D 重写要读什么"的现场清单，而它的
# 每一行都在声称"这个字段从 rd_xxx 读"。文档只有一种腐烂方式：名字不再存在，或者新导出
# 没人登记 —— 两种都长得像"文档看起来挺好"，没有任何编译器或测试会碰到它。
# 第一版按 `_len`/`_into` 前缀整片豁免，于是 **72 条导出**"存在但文档没写"却报绿；
# 现在只允许 `X_into` 在 `X_len` 已登记时才算登记（§8 的名字表把 41 对全列了出来）。
# 同一次运行里跑两条反证（塞一个假名字 / 删掉一个真名字的提及），两条都必须红 ——
# 没有反证过的下限等于没有下限（§161.5）。
$results += Invoke-Gate -Name 'ui-state' -Exe $PY `
  -ArgLine ((Join-Path $ROOT 'native\ui_state_check.py') + ' --negative') -Workdir $ROOT `
  -MustMatch 'NEGCTL1 RED[\s\S]*NEGCTL2 RED[\s\S]*UI_STATE_CHECK PASS' `
  -TimeoutSec 120

Write-Output "`n[24/53] UI ABI 契约：新 UI 依赖的导出/长度/哨兵/场景 parity（P0 基线）"
# 为什么这条必须是一道闸门：`docs/ui-abi-audit.md` 是新 UI 的**契约基线**，而它引用的每条
# 行为都只在一个地方被机器验证 —— `native/ui_abi_dump.mjs --check`。少了它，那些结论就只是
# 文档里的散文：删掉一个导出、改掉一个哨兵、把 `i32::MIN` 当成"没有局"，都不会有闸门红。
#
# 它**与内容无关**（不读具体价目/id），所以内容扩充不会让它变红；真实场景的 dump 走
# `--report`（手动/按需），那份产物与内容有关，改内容后必须重跑。
#
# 判据里包含三条"曾经搞错过"的哨兵：`i32::MIN` 是合法 seed（§348）、Boss 未定时给空串（§349）、
# 没有战斗会话时 `active_slot` 是 -3（查询不创建会话）。
$results += Invoke-Gate -Name 'ui-abi' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine ((Join-Path $ROOT 'native\ui_abi_dump.mjs') + ' --check') -Workdir $ROOT `
  -MustMatch 'UI_ABI_CHECK PASS \(exports \d+, runObs 19, combatObs 148, content 0x[0-9a-f]{8}, scenes 18\)' `
  -TimeoutSec 180

Write-Output "`n[25/53] UI P1（R3F PoC）：拖动/目标/回弹/触摸/模态隔离/中文可读性"
# 为什么这条必须是一道闸门：P1 的退出条件是"选中具体卡牌 → 指向正确敌人 → 释放；取消/非法释放
# 回弹；移动端触摸完成同样操作"，这三条只有在**真浏览器 + 真指针事件**里跑才成立 ——
# 直接调状态机函数会绕开射线、绕开 R3F 的事件派发、绕开 DOM 覆盖层，而那三处恰恰是 3D UI
# 最容易坏的地方（第十二轮 Review P1-C 的同一条教训）。
#
# `web-next/dist/` 入库，所以这道闸门**不需要 npm、不需要网络**；重建见 `docs/ui-next-p1.md`。
# 证据串里的四个数字是这道闸门的存在理由：commits（真提交）、rebound（真回弹）、
# touch（触摸走同一套状态机）、modal-isolation（模态吃掉了输入）。
$results += Invoke-Gate -Name 'ui-next' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_next_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_NEXT PASS cards=10 enemies=2 commits=\d+ rebound=\d+ touch=1 modal-isolation=1 minTitle=\d+px' `
  -TimeoutSec 300

Write-Output "`n[26/53] UI 纯状态机回归：同一动作做两次 / 物理落点 ≠ 业务目标"
# 为什么这条单独成闸门：第十三轮 Review 的 P1-A / P1-B 都是"从控制流能推出来、但 41 条浏览器
# 断言全都没覆盖"的缺陷 —— 那些断言里没有一条要求**同一件事做两次**。它们分别表现为
# "payload 相同的第二次操作被内容去重吞掉"与"无目标牌丢在敌人身上被判成回弹（判定与执行矛盾）"。
#
# 这条不需要浏览器（编译后直接跑状态机），所以与闸门 25 分开：红了能一眼看出坏在
# 状态机、接线还是渲染。脚本自带 `npx tsc`，测的是**当前源码**而不是陈旧产物。
$results += Invoke-Gate -Name 'ui-pointer' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\p1_review13_repro.mjs') -Workdir $ROOT `
  -MustMatch 'P1_REVIEW13_REPRO PASS: 三条都已修复' `
  -TimeoutSec 180

Write-Output "`n[27/53] UI 纯函数回归：队形 0–6 敌 / 屏幕命中 / 状态机（含 dismiss）"
# 为什么单独成闸门：合并参考包之后，队形与屏幕命中是**纯函数**，它们的最强证据是"0–6 个敌人、
# 横竖屏、业务 slot 不重编号、超过 6 个响亮失败"这种穷尽式断言 —— 在浏览器里跑同样的事要
# 几十秒且只能覆盖一两种组合。与闸门 25/26 分开：红了要能一眼看出坏在纯逻辑、接线还是渲染。
$results += Invoke-Gate -Name 'ui-pure' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_pure_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_PURE PASS formation=0\.\.6 hit=\d+ machine=\d+ layout=\d+ decode=\d+ choice=\d+ i18n=\d+ rows=\d+' `
  -TimeoutSec 180

Write-Output "`n[28/53] P2 WASM 接线：装载校验 / 观察解码 / 动作表 / 走一步 / 拒绝不变 / 打到终局"
# 为什么必须是一道闸门：plan P2 的两条退出条件（"相同输入得到正确动作与结果"、"拒绝操作不产生
# 成功演出"）只有对着**真 wasm** 跑才成立。这道闸门驱动 `web-next/dist/p2.html` 的探针：
# 装载校验（导出/长度/哨兵/指纹）、开局走到战斗、按 (手牌槽位,目标槽位) 找内核给的动作、
# 断言"只有被指的敌人掉血"、越界动作返回 -1 且观察向量**逐字节不变**、一路打到终局。
$results += Invoke-Gate -Name 'ui-wasm' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_wasm_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_WASM PASS exports=\d+ content=0x[0-9a-f]{8} hand=\d+ enemies=\d+ steps=\d+ result=(victory|defeat) rejected-unchanged=1' `
  -TimeoutSec 300

Write-Output "`n[29/53] P2 UI 与内核一致：主页面跑真 wasm，拖牌后 DOM 跟着内核变"
# 闸门 28 证明的是"适配器对"（对着 p2.html 的探针），这道证明的是"**渲染层**对"：
# 主页面默认走真 wasm，于是可以断言"屏幕上的敌人血量 == 内核观察向量里的血量"，
# 以及"从 UI 拖一张牌出去 ⇒ 内核接受 ⇒ **DOM 上的血量跟着变**"（不是只改了内存里的 view）。
# 这是 plan P2 退出条件"行动后 HP/能量/手牌与内核一致"的直接落地。
$results += Invoke-Gate -Name 'ui-wasm-ui' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_wasm_ui_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_WASM_UI PASS mode=wasm hand=\d+ energy=\d+ enemy0=\d+->\d+ dom-synced=1' `
  -TimeoutSec 300

Write-Output "`n[30/53] P2 待决选牌（PendingChoice）+ 演出 beat：真问句、真消耗、真 beat"
# 会问句的牌（armaments/warcry/headbutt/exhume/dual_wield/nightmare/true_grit+）都不在起手牌里，
# 而起手牌是随机的 ⇒ "打几把看看能不能碰到"不是夹具。所以用 rd_run_grant_potion + rd_env_use_potion：
# Elixir 一喝就问"要消耗哪几张"，局面确定、可复现，而且走的是真内核。
$results += Invoke-Gate -Name 'ui-wasm-choice' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_wasm_choice_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_WASM_CHOICE PASS source=\d+ kind=\d+ options=\d+ exhaust=\d+->\d+ beats=ok' `
  -TimeoutSec 300

Write-Output "`n[31/53] P2 定向夹具：同名卡 / 0 能量 / 敌人槽位稳定（X 费不可达，见文档）"
# 这三条是 plan P2 点名的夹具。同名卡那条尤其重要：手牌槽位是**位置**（打出后压实），
# 不是身份 —— UI 若把"第 3 张 strike"当成"strike"去查，就会打错副本（Review P2-A）。
$results += Invoke-Gate -Name 'ui-wasm-fixtures' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_wasm_fixtures_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_WASM_FIXTURES PASS duplicate=\d+ zero-energy=1 slot-stable=1' `
  -TimeoutSec 300

Write-Output "`n[32/53] P2 X 费：真牌、真能量、打出后能量归零（plan P2 最后一条定向夹具）"
# X 费牌不在起手牌、药水三选一也不给（扫过 14 个种子 × 2 种药水共 28 组），唯一确定性入口是
# 战斗奖励屏：开局 → 打赢 → fight_end（这一步才生成奖励屏）→ 挑一张 X 费牌 → 下一场抽到它 → 打出去。
# seed 58 的奖励含 whirlwind（seed 59 含 skewer），所以夹具是确定性的。
$results += Invoke-Gate -Name 'ui-wasm-xcost' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_wasm_xcost_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_WASM_XCOST PASS seed=\d+ card=\w+ energy=\d+->0 damaged=\d+' `
  -TimeoutSec 300

Write-Output "`n[33/53] P3 场景判定：18 行表的顺序陷阱 + 穷尽性（纯函数，不需要浏览器）"
# `SC-03b` 必须排在 `SC-03` 之前、`SC-02b` 必须排在 `SC-02` 之前；18 行表逐行有夹具；
# 任何内核事实的组合都能得到一个场景（`unknownPending` 只在相位越界时非空）。
$results += Invoke-Gate -Name 'ui-scene' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_scene_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_SCENE PASS order=\d+\+\d+ pending=\d+ exhaustive=\d+ rows=\d+' `
  -TimeoutSec 300

Write-Output "`n[34/53] P3 端到端：标题 → 祝福 → 地图 → 战斗（含真实 3D 拾取）→ 奖励 → 地图"
# 全程用真 DOM 点击（开始/祝福/地图节点/领奖励/继续），一次真实 3D 拖拽（CDP 鼠标事件），
# 每个阶段断言对账干净，最后断言"不刷新页面场景判定仍然稳定"。
$results += Invoke-Gate -Name 'ui-next-loop' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_next_loop_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_NEXT_LOOP PASS nodes=\d+ steps=\d+ scene-chain=SC-00>SC-01>SC-02>SC-03>SC-03b>SC-04>SC-02' `
  -TimeoutSec 600

Write-Output "`n[35/53] P4 展示逻辑：篝火位掩码 / 效果判别值 / 商店定价 / 选择器 / 药水（纯函数）"
$results += Invoke-Gate -Name 'ui-p4-models' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_p4_models_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_P4_MODELS PASS campfire=\d+ effects=\d+ shelves=\d+ picker=\d+ potions=\d+' `
  -TimeoutSec 300

Write-Output "`n[36/53] P4 端到端：一段真实旅程把商店/篝火/宝箱/事件/选择器/药水全用一遍"
# 地图生成有硬规则（第 1-5 层没有篝火、第 9 层全宝箱、第 15 层全篝火），所以"走到这些屏"本身
# 就是被测对象：闸门从第 1 层往上走，遇到什么测什么，走两段旅程覆盖全部屏。
$results += Invoke-Gate -Name 'ui-next-p4' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_next_p4_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_NEXT_P4 PASS floors=\d+ screens=[a-z,-]+ ' `
  -TimeoutSec 900

Write-Output "`n[37/53] P5 Beat 演出导演 + 资源降级（纯函数：13 种 kind / 未知降级 / 关动画 / 跳过）"
$results += Invoke-Gate -Name 'ui-beats' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_beats_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_BEATS PASS kinds=\d+ unknown=degraded dropped=counted skip=clears reduced=quiet assets=\d+' `
  -TimeoutSec 300

Write-Output "`n[38/53] P5 端到端：飘字真的出现且不挡输入、关动画也能打完、幕间推进被内核把关"
$results += Invoke-Gate -Name 'ui-next-p5' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_next_p5_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_NEXT_P5 PASS kinds=[0-9,]+ skip=\d+ motion-off=\d act-refusal=-?\d+' `
  -TimeoutSec 600

Write-Output "`n[39/53] P6 移动端：390x844 触摸走完整流程 + 44px 触控目标 + 安全区 + DPR 上限"
# 触摸是**真事件链**（Emulation.setTouchEmulationEnabled + Input.dispatchTouchEvent）：
# 触摸才有长按详情、没有 hover、并且会被祖先滚动容器抢走手势（第一版触摸拖牌完全无效）。
$results += Invoke-Gate -Name 'ui-mobile' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_mobile_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_MOBILE PASS targets=\d+ min=\d+ dpr-cap=[\d.]+ backing=\d+ safe-top=\d+ drag=[01]' `
  -TimeoutSec 600

Write-Output "`n[40/53] P6 稳定性：8 次重开 / 长局 / 重载 / WebGL 上下文丢失 / 动效偏好持久化"
$results += Invoke-Gate -Name 'ui-soak-p6' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_soak_p6_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_SOAK_P6 PASS restarts=\d+ steps=\d+ heap=\d+KB->\d+KB context-lost=\d motion-persisted=\d' `
  -TimeoutSec 900

Write-Output "`n[41/53] P7 对等：新旧入口同一个 wasm 字节 + 内核侧脚本与新入口逐字段一致"
# 参照物是 **wasm 本身**（Node 里直接跑原始导出），不是旧页面 —— 界面是"被验收的对象"，
# 拿它验另一个界面就是自己验自己。
$results += Invoke-Gate -Name 'ui-parity' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_parity_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_PARITY PASS checkpoints=\d+ cells=\d+ sha=match old=alive' `
  -TimeoutSec 600

Write-Output "`n[42/53] P7 部署：wasm MIME / 缓存策略 / 版本一致性 / 两个入口都可起"
$results += Invoke-Gate -Name 'ui-deploy' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_deploy_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_DEPLOY PASS entry=run assets=\d+ wasm=application/wasm cache=immutable-for-hashed version=match' `
  -TimeoutSec 300

Write-Output "`n[43/53] 冻结边界：契约违约之后**所有**操作入口都动不了（含战斗与旧 fallback）"
# 第十五轮 Review §2：横幅写着"界面已冻结"，而 CombatScreen 直接调 GameStore.dispatch
# 完全绕过；祝福/奖励屏连 busy 都没收到。现在判据只有一份（RunStore.frozenReason ->
# canMutate / GameStore.dispatchGuard），并且是**粘性**的（只有重开一局能解）。
$results += Invoke-Gate -Name 'ui-freeze' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_freeze_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_FREEZE PASS entries=\d+ refused=\d+ sticky=1' `
  -TimeoutSec 600

Write-Output "`n[44/53] 存档 / 回档：导出 → 刷新 → 导入逐字段相同；坏档案被拒且局面不动"
# 第十五轮 Review §6：默认入口切到新 UI 之后，"刷新就丢局"从"可以没有"变成"必须有"。
# 内核早有可信档案（MAGIC-base64-校验和，含内容指纹），这一版把它接到设置面板上。
$results += Invoke-Gate -Name 'ui-archive' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_archive_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_ARCHIVE PASS bytes=\d+ refused=\d+ roundtrip=1' `
  -TimeoutSec 600

Write-Output "`n[45/53] 素材清单：内容 id 逐个覆盖 / 字母规则 / 16 种几何原型（纯函数）"
# 清单是**生成**的（native/build_assets.py）：内容加了东西而美术没跟上，会在生成时就暴露。
# 这一道还量了"两位字母的碰撞数"——这一版接受碰撞，但必须是个**数字**而不是感觉。
$results += Invoke-Gate -Name 'ui-assets' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_assets_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_ASSETS PASS enemies=\d+ cards=\d+ relics=\d+ potions=\d+ statuses=\d+ archetypes=\d+ collisions=\d+' `
  -TimeoutSec 300

Write-Output "`n[46/53] 素材渲染：素材库页面真的画出来 + 产品界面（奖励/商店/牌组/药水）也用了徽章"
# 三维那一条用 CDP **截图**统计彩色像素（`gl.readPixels` 在合成之后读不到 —— 那是"读晚了"）。
$results += Invoke-Gate -Name 'ui-assets-render' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_assets_render_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_ASSETS_RENDER PASS archetypes=\d+ enemies=\d+ cards=\d+ badges=4tables lit=\d+' `
  -TimeoutSec 600

Write-Output "`n[47/53] 幕间（§370）：幕数显示 + Boss 遗物三选一（只从 Boss 池、互不重复、拿走进腰带）"
# 换幕之后 floor 归 0，只画层数会变成"第 0 层"；act 只能从 rd_run_act() 读。
# 三选一是**内核动作**（offer_boss_relics / take_boss_relic），闸门用 ?debug 夹具造 offer
# （打赢 Boss 没法按需制造），取走与拒绝都走真内核。
$results += Invoke-Gate -Name 'ui-act' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_act_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_ACT PASS act=\d+ offer=\d+ taken=\w+' `
  -TimeoutSec 600

Write-Output "`n[48/53] 幕间幕布（§2.3）：act 变大才播 / 不挡操作 / 1.6 秒自动淡出 / 关动画不播"
# 规格原文："纯演出，1.6 秒自动淡出。触发条件是 act 变大，**不需要**任何新导出。"
# 所以判定是纯函数（6 条边界），覆盖层 pointer-events: none（换幕后第一件事是点地图）。
$results += Invoke-Gate -Name 'ui-curtain' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_curtain_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_CURTAIN PASS cases=\d+ auto=1 click=1' `
  -TimeoutSec 300

Write-Output "`n[49/53] 自动存档（§372）：写 / 继续上次逐字段相同 / 战斗中不写 / 坏档被丢"
# 默认入口已经是新 UI ⇒"刷新就丢一局"对正式入口不可接受。存档走内核的档案格式
# （MAGIC-base64-校验和 + 内容指纹），页面只做搬运；战斗中内核拒绝存档，所以刷新只会回到开战前。
$results += Invoke-Gate -Name 'ui-save' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_save_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_SAVE PASS bytes=\d+ restored=1 corrupt=1' `
  -TimeoutSec 600

Write-Output "`n[50/53] 产物可得（§372）：dist 的 wasm 入库 + 一条命令能玩"
# 判据是 **git 跟踪**（`ls-files --error-unmatch`），不是"磁盘上有"——磁盘上有但没跟踪，
# clone 下来照样没有。这正是"代码全在、玩不了"的那种缺口。
$results += Invoke-Gate -Name 'ui-distributable' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_distributable_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_DISTRIBUTABLE PASS wasm=\d+ tracked=2 assets=\d+ play=ok' `
  -TimeoutSec 300

Write-Output "`n[51/53] 回放（§373）：导出到剪贴板 / 导入并逐步对拍 / 分叉报在第几步"
# 回放与存档是两件事：存档描述"现在这一局"，脚本描述"这一局是怎么走到现在的"（每步带指纹）。
# 导入时内核逐步比对 ⇒ 分叉在第几步是可说的。脚本头自带 seed/进阶/内容指纹，所以导入不用先开局。
$results += Invoke-Gate -Name 'ui-replay' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_replay_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_REPLAY PASS bytes=\d+ steps=\d+ diverged=\d+' `
  -TimeoutSec 600

Write-Output "`n[52/53] 卡面（§374）：文字层真的样式化 + 卡面落在牌心上 + 徽章用内容 id"
# 用户报"卡面是空的"。根因有两层：run.html 没加载 styles.css（文字层是 static，飘在屏幕外），
# 以及徽章从没接到手牌/详情；更深一层：ViewCard/ViewEnemy 的 id 是合成 id（hand-0-1 / enemy-0），
# 拿它查素材表会走降级（每只怪随机一个原型）。之前的闸门断言文本内容，抓不到几何与样式。
$results += Invoke-Gate -Name 'ui-cardface' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_cardface_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_CARDFACE PASS cards=\d+ offset=\d+px letters=[A-Z,]+' `
  -TimeoutSec 600

Write-Output "`n[53/53] 端口（§375）：被占用时换端口并说清 + 起来之后自检"
# 用户实测：play.ps1 打印 127.0.0.1:8080，浏览器打开却是 **Steam**（它的 CEF 调试端口就是 8080）。
# 根因：Node 的 listen(8080) 绑 ::（双栈），Steam 绑 127.0.0.1:8080，两者能同时绑成功，
# 而浏览器连 127.0.0.1 时命中更具体的那个。修法：绑 127.0.0.1 + 占用回退 + 自检 #root。
$results += Invoke-Gate -Name 'ui-serve-port' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\ui_serve_port_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_SERVE_PORT PASS fallback=1 port=\d+ selfcheck=ok' `
  -TimeoutSec 300

Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')
Write-Output ("-" * 78)
$failed = 0
foreach ($x in $results) {
  if (-not $x.Ok) { $failed++ }
  Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f $x.Gate, $x.Exit, $x.Evidence, $x.Notes)
}
Write-Output ("-" * 78)

if ($failed -gt 0) {
  Write-Output "`n!! $failed 个闸门未通过。失败闸门的输出摘录："
  foreach ($x in ($results | Where-Object { -not $_.Ok })) {
    Write-Output ("`n--- {0} (exit {1}) ---" -f $x.Gate, $x.Exit)
    ($x.Output -split "`r?`n" | Where-Object { $_ -match 'error|FAILED|panicked|不一致|!!' } |
      Select-Object -First 12) | ForEach-Object { Write-Output "  $_" }
  }
}

Write-Output ""
Write-Output ("ACCEPTANCE_RESULT {0} ({1}/{2} gates passed)" -f
  $(if ($failed -eq 0) { 'PASS' } else { 'FAIL' }), ($results.Count - $failed), $results.Count)

Remove-Item $TARGET_DIR -Recurse -Force -ErrorAction SilentlyContinue
exit $(if ($failed -eq 0) { 0 } else { 1 })
