# Runs dotnet with the standard Windows environment restored, and forwards
# the arguments through without losing the ones that contain spaces.
#
# NO param() BLOCK ON PURPOSE. With one, PowerShell binds a leading "--do" to
# the remaining-arguments parameter (-do is a unique prefix of -DotnetArgs),
# and the rest of the command line becomes an unbound positional that fails.
# Without a param block every token, dashes and all, lands in $args intact.
#
# Arguments that contain a space are re-quoted on the way out: PowerShell
# strips the quotes when it fills $args, and joining with spaces alone would
# hand "--do n 0" to dotnet as three separate arguments.

. "$PSScriptRoot\env.ps1"

$dotnet = Join-Path $StandardEnv["DOTNET_ROOT"] "dotnet.exe"

$quoted = $args | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }

$psi = [Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $dotnet
$psi.Arguments = ($quoted -join ' ')
$psi.WorkingDirectory = "D:\Vibe\sts-tui\ref\RogueDeck-Core"
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
