# run.ps1 -- run a python script with full env + captured output (this box's shell is stripped)
# Usage: pwsh -File run.ps1 <script.py> [args...]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
$py = 'C:\Users\TK11\miniforge3\python.exe'
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $py
$argline = ($Rest | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' '
$psi.Arguments = $argline
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.WorkingDirectory = (Get-Location).Path
$psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
$psi.EnvironmentVariables['PYTHONUTF8'] = '1'
$p = [Diagnostics.Process]::Start($psi)
$so = $p.StandardOutput.ReadToEnd()
$se = $p.StandardError.ReadToEnd()
$p.WaitForExit()
Write-Output $so
if ($se) { Write-Output "--- STDERR ---"; Write-Output $se }
Write-Output "=== EXIT $($p.ExitCode) ==="
