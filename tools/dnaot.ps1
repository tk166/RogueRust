# Runs dotnet inside a vcvars64 environment, for NativeAOT.
#
# NativeAOT needs the MSVC linker, which is not on PATH in this shell and is not
# something the standard Windows environment restore in env.ps1 can supply - it comes
# from VS's vcvars64.bat. So: cmd /c call vcvars64 && dotnet <args>.
#
# No param() block, for the same reason as dn.ps1: a leading "--do"-shaped token would
# bind to the remaining-arguments parameter instead of reaching dotnet.

. "$PSScriptRoot\env.ps1"

$vcvars = "F:\Distros\VisualStudio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path $vcvars)) {
  Write-Output "=== VCVARS MISSING: $vcvars ==="
  Write-Output "=== EXIT 9009 ==="
  exit
}

$quoted = $args | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }

$psi = [Diagnostics.ProcessStartInfo]::new()
$psi.FileName = "cmd.exe"
$psi.Arguments = "/c call $vcvars >nul 2>&1 && dotnet " + ($quoted -join ' ')
$psi.WorkingDirectory = "D:\Vibe\sts-tui"
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.StandardOutputEncoding = [Text.Encoding]::UTF8
$psi.StandardErrorEncoding = [Text.Encoding]::UTF8
foreach ($k in $StandardEnv.Keys) { $psi.EnvironmentVariables[$k] = $StandardEnv[$k] }

$p = [Diagnostics.Process]::Start($psi)
$out = $p.StandardOutput.ReadToEnd()
$err = $p.StandardError.ReadToEnd()
$p.WaitForExit()

Write-Output $out
if ($err.Trim()) { Write-Output "=== STDERR ==="; Write-Output $err }
Write-Output "=== EXIT $($p.ExitCode) ==="
