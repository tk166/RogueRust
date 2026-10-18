# 聚合验收器：一条命令跑完所有闸门，用**真实退出码**下判定。
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
  [int]$UnitsFloor = 547
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
  foreach ($pat in @('(\d+) case\(s\)', '(\d+)/19', '(\d+) passed', '(\d+/\d+ images)',
                     '(\d+/\d+ tables)', '(\d+ monsters)')) {
    $m = [regex]::Match($out, $pat)
    if ($m.Success) { $evidence = $m.Value; break }
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

Write-Output "`n[1/9] 单元测试 + 语料逐字节回环（Rust 内核）"
$r = Invoke-Gate -Name 'rust-units' -Exe $CARGO `
  -ArgLine "test -p rd-core --release --target-dir `"$TARGET_DIR`"" -Workdir (Join-Path $ROOT 'kernel') `
  -MustMatch 'test result: ok\. \d+ passed; 0 failed' -MustNotMatch 'test result: FAILED'
$results += $r
$passed = [regex]::Match($r.Output, '(\d+) passed').Groups[1].Value
if ($r.Ok -and $passed -and [int]$passed -lt $UnitsFloor) {
  $r.Ok = $false; $r.Notes += "测试数 $passed < 下限 $UnitsFloor"
}
$results[-1] = $r

Write-Output "[2/9] 语料回环份数（确认不是空扫）"
$r = Invoke-Gate -Name 'corpus-roundtrip' -Exe $CARGO `
  -ArgLine "test -p rd-core --release --target-dir `"$TARGET_DIR`" corpus -- --nocapture" `
  -Workdir (Join-Path $ROOT 'kernel') -MustMatch 'case\(s\) reproduced byte-for-byte'
$results += $r

Write-Output "[3/9] 裸机目标编译（riscv32imac-unknown-none-elf）"
$results += Invoke-Gate -Name 'rust-baremetal' -Exe $CARGO `
  -ArgLine "check --target riscv32imac-unknown-none-elf -p rd-core --release --target-dir `"$TARGET_DIR`"" `
  -Workdir (Join-Path $ROOT 'kernel') -MustMatch 'Finished'

Write-Output "[4/9] clippy"
$results += Invoke-Gate -Name 'rust-clippy' -Exe $CARGO `
  -ArgLine "clippy --all-targets -p rd-core --target-dir `"$TARGET_DIR`"" -Workdir (Join-Path $ROOT 'kernel') `
  -MustMatch 'Finished'

Write-Output "[5/9] 真链接成裸机 ELF 镜像"
$fw = Join-Path $ROOT 'kernel\rd-firmware\link.x'
$results += Invoke-Gate -Name 'firmware-link' -Exe $CARGO `
  -ArgLine "rustc --release --target riscv32imac-unknown-none-elf --manifest-path rd-firmware/Cargo.toml -- -C link-arg=-T$fw" `
  -Workdir (Join-Path $ROOT 'kernel') -MustMatch 'Finished'

Write-Output "[6/9] 镜像占用（自带陈旧守卫）"
$results += Invoke-Gate -Name 'firmware-size' -Exe $PY `
  -ArgLine (Join-Path $ROOT 'tools\firmware_size.py') -Workdir $ROOT -MustMatch '非易失存储'

Write-Output "[7/9] 覆盖门禁"
$results += Invoke-Gate -Name 'coverage-gate' -Exe $PY `
  -ArgLine (Join-Path $ROOT 'native\coverage_check.py') -Workdir $ROOT -MustMatch '19/19'

Write-Output "[8/9] golden 基线逐字节一致"
$ga = Join-Path $ROOT 'corpus\golden_v1.jsonl'
$gb = Join-Path $ROOT 'corpus\baseline\golden_v1.jsonl'
$same = ((Get-FileHash $ga -Algorithm SHA256).Hash -eq (Get-FileHash $gb -Algorithm SHA256).Hash)
$results += [pscustomobject]@{
  Gate = 'golden-baseline'; Exit = $(if ($same) { 0 } else { 1 }); Ok = $same
  Evidence = "$((Get-Content $ga).Count) 行"; Notes = $(if ($same) { '' } else { 'SHA-256 不一致' }); Output = ''
}

Write-Output "[9/9] RL 环境冒烟（多开 + 确定性）"
$results += Invoke-Gate -Name 'env-smoke' -Exe $PY -ArgLine '-m roguedeck_env.bench' `
  -Workdir (Join-Path $ROOT 'py') -MustMatch '多开吞吐与可复现性均通过' `
  -ExtraEnv @{ PYTHONPATH = (Join-Path $ROOT 'py') } -TimeoutSec 1800

Write-Output "`n[+1] 内容镜像 byte-identity（用当前编译器重编源文档 == 钉死的 SHA）"
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

Write-Output "[+2] 内容镜像结构不变量（独立解读字节：段目录 + 5 张定长表的 count×stride）"
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
  -MustMatch 'RDCF_VERIFY PASS \(2/2 variants, 5/5 tables, 10 count×stride checks' -TimeoutSec 300

Write-Output "`n[+3] StS 内容包自洽（不变量表 + 两份镜像逐键回读 + 交叉引用）"
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
