# Run a command line and report its REAL exit code without letting a filter swallow it.
#
# Why this exists: a verification pass once grepped cargo's output for "error" and "test result"
# and dropped the trailing "=== EXIT n ===" line, then printed the *outer* powershell's exit code
# (always 0). A build that had failed was reported as green. Any harness that can hide the exit
# code is worse than no harness, so this one always emits it last, tagged for machine reading:
#
#   VERIFY_EXIT <n>
#   VERIFY_VERDICT PASS | FAIL
#
# Usage:
#   powershell -NoProfile -File tools\verify.ps1 -Line "powershell -NoProfile -ExecutionPolicy Bypass -File tools\cargo.ps1 test -p rd-core --release"
#
# -Line takes the WHOLE command as one string and runs it through cmd /c. An earlier version took
# an array of arguments; nested powershell re-split it on commas and silently mangled the command.
#
# ── 两个必须同时存在的保护（都是踩出来的）────────────────────────────────────────────────────────
# 1. 两个流**并发**读。串行 `ReadToEnd()` stdout 再读 stderr，在子进程往 stderr 写超过管道缓冲
#    （约 4 KB）时会双向死锁 —— 验收脚本自己挂死，比报错更糟。
# 2. 超时兜底并**杀掉**子进程。没有它，一次卡死会吃掉整轮。
# 3. 退出码 0 但打印了 error 文本 ⇒ 判 FAIL。只信退出码同样会被骗。

param(
  [Parameter(Mandatory = $true)][string]$Line,
  [string]$Workdir = "D:\Vibe\sts-tui",
  [int]$MaxLines = 400,
  [int]$TimeoutSeconds = 1800,
  [string[]]$FailPatterns = @('^error', 'error\[', 'FAILED', 'panicked at', 'test result: FAILED'),
  [string]$ExpectLine = ''
)

. "$PSScriptRoot\env.ps1"

$psi = [Diagnostics.ProcessStartInfo]::new()
$psi.FileName = "$env:SystemRoot\System32\cmd.exe"
$psi.Arguments = '/c ' + $Line
$psi.WorkingDirectory = $Workdir
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.StandardOutputEncoding = [Text.Encoding]::UTF8
$psi.StandardErrorEncoding = [Text.Encoding]::UTF8
foreach ($k in $StandardEnv.Keys) { $psi.EnvironmentVariables[$k] = $StandardEnv[$k] }

$p = [Diagnostics.Process]::Start($psi)
$outTask = $p.StandardOutput.ReadToEndAsync()
$errTask = $p.StandardError.ReadToEndAsync()
$finished = $p.WaitForExit($TimeoutSeconds * 1000)
$timedOut = -not $finished
if ($timedOut) {
  try { $p.Kill() } catch { }
  $p.WaitForExit(10000) | Out-Null
}
$out = $outTask.Result
$err = $errTask.Result
$code = if ($timedOut) { 124 } else { $p.ExitCode }

$all = @()
$all += ($out -split "`r?`n")
if ($err.Trim()) { $all += '=== STDERR ==='; $all += ($err -split "`r?`n") }

# Body: keep the head and the tail, drop the middle -- "test result:" lives in the tail.
if ($all.Count -gt $MaxLines) {
  $half = [int]($MaxLines / 2)
  $body = @($all[0..($half - 1)]) + @("... [$($all.Count - $MaxLines) lines elided] ...") + @($all[($all.Count - $half)..($all.Count - 1)])
} else {
  $body = $all
}
$body -join "`n"

# Digest: the failure evidence must survive even when the body gets elided.
#
# `-cmatch`, NOT `-match`: PowerShell's -match is CASE-INSENSITIVE by default, so the pattern
# 'FAILED' matched the "0 failed" inside "test result: ok. 104 passed; 0 failed" and turned a
# completely green run into a FAIL verdict. Case matters for exactly this word.
$hits = @($all | Where-Object { $l = $_; @($FailPatterns | Where-Object { $l -cmatch $_ }).Count -gt 0 })
$hits = @($hits | Where-Object { $_ -notmatch '^\s*=+ (STDERR|stderr) =+$' })
Write-Output ""
Write-Output "---- failure evidence ($($hits.Count) lines) ----"
if ($hits.Count -eq 0) {
  Write-Output "(none)"
} else {
  ($hits | Select-Object -First 40) | ForEach-Object { Write-Output "  $_" }
  if ($hits.Count -gt 40) { Write-Output "  ... plus $($hits.Count - 40) more" }
}

if ($ExpectLine) {
  $found = @($all | Where-Object { $_ -cmatch $ExpectLine })
  Write-Output "---- expected line /$ExpectLine/ : $($found.Count) hit(s) ----"
  $found | Select-Object -First 10 | ForEach-Object { Write-Output "  $_" }
}

if ($timedOut) { Write-Output "---- TIMEOUT after ${TimeoutSeconds}s; the process was killed ----" }

# 交叉核对：被包裹的脚本可能**打印**了 "=== EXIT n ===" 却仍然以 0 退出（cargo.ps1 就这样干过，
# 于是构建失败一路被报成绿色）。所以除了看进程退出码，还要把输出里声明的退出码也捡起来对账。
$innerExits = @()
foreach ($l in $all) {
  $m = [regex]::Match($l, '^=+\s*EXIT\s+(-?\d+)\s*=+\s*$')
  if ($m.Success) { $innerExits += [int]$m.Groups[1].Value }
}
$innerBad = @($innerExits | Where-Object { $_ -ne 0 })
if ($innerExits.Count -gt 0) {
  Write-Output "---- declared exit codes in the output: $($innerExits -join ', ') ----"
}
if ($innerBad.Count -gt 0) {
  Write-Output "---- a wrapped command DECLARED failure ($($innerBad -join ', ')) even though the wrapper exited $code ----"
}

# The verdict is driven by the REAL exit code, by failure text, and by any declared non-zero exit.
$verdict = if ($timedOut) { 'FAIL (timeout)' }
           elseif ($code -ne 0) { 'FAIL' }
           elseif ($innerBad.Count -gt 0) { "FAIL (wrapped command declared exit $($innerBad -join '/'))" }
           elseif ($hits.Count -gt 0) { 'FAIL (error text printed despite exit 0)' }
           else { 'PASS' }
Write-Output ""
Write-Output "VERIFY_EXIT $code"
Write-Output "VERIFY_VERDICT $verdict"
exit $(if ($verdict -eq 'PASS') { 0 } else { 1 })
