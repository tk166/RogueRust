# Runs cargo with the environment this shell is missing.
#
# Rust IS installed on this machine (~\.cargo\bin, toolchain stable-x86_64-pc-windows-gnu) but,
# like git and dotnet here, it is not on PATH and the shell has almost no environment at all:
# LOCALAPPDATA, APPDATA, ProgramFiles(x86), PROCESSOR_ARCHITECTURE and OS are all null.
#
# No param() block, for the same reason as dn.ps1: a leading "--"-style token would bind to the
# remaining-arguments parameter instead of reaching cargo.
#
# ── 管道死锁（2026-10-17 修）────────────────────────────────────────────────────────────────────
# 旧版先 `StandardOutput.ReadToEnd()` 再读 stderr。cargo 冷构建时**编译进度全在 stderr**，一旦
# 超过管道缓冲（约 4 KB）就写不下去；而父进程还在等 stdout 的 EOF —— 双向卡死，表现为"没有任何
# 输出且永不返回"（踩过两次，留下 0% CPU 的僵尸 cargo，还拖出一次假 9m58s）。
# 修法：两个流**并发**读（ReadToEndAsync），并加超时兜底，超时就杀进程并明确报 TIMEOUT。
# 注意：只读一个流、或串行读两个流，都是同一个 bug 的不同写法。

. "$PSScriptRoot\env.ps1"

$cargo = "C:\Users\TK11\.cargo\bin\cargo.exe"
if (-not (Test-Path $cargo)) {
  Write-Output "=== CARGO MISSING: $cargo ==="
  Write-Output "=== EXIT 9009 ==="
  # 必须**真的** exit：只打印 "=== EXIT n ===" 而不设置进程退出码，会让所有调用方看到 0。
  # 曾经就是这样：构建失败时打印 "=== EXIT 101 ===" 却以 0 退出，上层验收脚本报 PASS。
  exit 9009
}

$TimeoutSeconds = 1800
if ($env:CARGO_TIMEOUT_SECONDS) { $TimeoutSeconds = [int]$env:CARGO_TIMEOUT_SECONDS }

$quoted = $args | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }

$psi = [Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $cargo
$psi.Arguments = ($quoted -join ' ')
$psi.WorkingDirectory = "D:\Vibe\sts-tui\kernel"
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.StandardOutputEncoding = [Text.Encoding]::UTF8
$psi.StandardErrorEncoding = [Text.Encoding]::UTF8
foreach ($k in $StandardEnv.Keys) { $psi.EnvironmentVariables[$k] = $StandardEnv[$k] }
$psi.EnvironmentVariables["CARGO_HOME"] = "C:\Users\TK11\.cargo"
$psi.EnvironmentVariables["RUSTUP_HOME"] = "C:\Users\TK11\.rustup"
$psi.EnvironmentVariables["PATH"] = "C:\Users\TK11\.cargo\bin;C:\Windows\System32;C:\Windows"
$psi.EnvironmentVariables["CARGO_TERM_COLOR"] = "never"

$p = [Diagnostics.Process]::Start($psi)
# 两个流都必须**现在就**开始被抽走，否则下面的 WaitForExit 就是死锁点。
$outTask = $p.StandardOutput.ReadToEndAsync()
$errTask = $p.StandardError.ReadToEndAsync()
$finished = $p.WaitForExit($TimeoutSeconds * 1000)
if (-not $finished) {
  try { $p.Kill() } catch { }
  $p.WaitForExit(10000) | Out-Null
  Write-Output $outTask.Result
  Write-Output "=== STDERR ==="
  Write-Output $errTask.Result
  Write-Output "=== TIMEOUT after ${TimeoutSeconds}s: cargo was killed ==="
  Write-Output "=== EXIT 124 ==="
  exit 124
}

Write-Output $outTask.Result
$err = $errTask.Result
if ($err.Trim()) { Write-Output "=== STDERR ==="; Write-Output $err }
Write-Output "=== EXIT $($p.ExitCode) ==="
# 关键：把子进程的退出码**变成自己的**退出码。没有这一行，上面那行 EXIT 只是一句装饰，
# 调用方（verify.ps1 / CI / 我自己）看到的永远是 0 —— 构建失败会被报成绿色。
exit $p.ExitCode
