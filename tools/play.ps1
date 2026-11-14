#!/usr/bin/env pwsh
<#
.SYNOPSIS
    一条命令开始玩：确保 wasm 就位，然后起静态服务器。

.DESCRIPTION
    两种人都要能玩：

    * **没有 Rust 工具链**：`web-next/dist/rd_wasm.wasm` 是**入库**的，直接起服务器即可；
    * **有 Rust**：加 `-Rebuild` 重编内核、同步、重建前端产物，然后起服务器。

    为什么默认**不**重建：编译要几分钟，而"想玩一下"的人不该先等 cargo。

.PARAMETER Port
    监听端口（默认 8080）。

.PARAMETER Rebuild
    重编 wasm + 重建 web-next 产物（改了 `kernel/**` 或 `web-next/src/**` 才需要）。

.PARAMETER Entry
    `run`（默认，新 UI）或 `legacy`（旧 UI，回退用）。

.EXAMPLE
    pwsh tools/play.ps1
    pwsh tools/play.ps1 -Port 9000
    pwsh tools/play.ps1 -Rebuild
#>
param(
    [int]$Port = 8080,
    [switch]$Rebuild,
    [ValidateSet('run', 'legacy')]
    [string]$Entry = 'run'
)

$ErrorActionPreference = 'Stop'
# 本机 shell 的 PATHEXT 是坏的（只有 .CPL）⇒ 调外部 exe 前必须修好，否则什么都不打印。
$env:PATHEXT = '.COM;.EXE;.BAT;.CMD'
# 输出编码：PowerShell 5.1 默认按控制台代码页（中文机器上是 GBK）写，而 node 写 UTF-8
# ⇒ 两边的中文会一半乱码。统一成 UTF-8（失败也不影响运行，只是显示）。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Find-Node {
    foreach ($candidate in @(
        'C:\Program Files\nodejs\node.exe',
        (Join-Path $env:ProgramFiles 'nodejs\node.exe')
    )) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    $onPath = Get-Command node -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    throw '找不到 node.exe（装 Node 22+，或把 node 放进 PATH）'
}

function Find-Cargo {
    foreach ($candidate in @(
        (Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'),
        'C:\Users\TK11\.cargo\bin\cargo.exe'
    )) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    $onPath = Get-Command cargo -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    return $null
}

$node = Find-Node
$wasm = Join-Path $Root 'web-next\dist\rd_wasm.wasm'
$manifest = Join-Path $Root 'web-next\dist\wasm.json'

if ($Rebuild) {
    $cargo = Find-Cargo
    if (-not $cargo) {
        throw '-Rebuild 需要 Rust（cargo）。没有工具链就用默认模式：dist 里的 wasm 是入库的。'
    }
    Write-Host '[1/3] 重编 wasm …' -ForegroundColor Cyan
    Push-Location (Join-Path $Root 'kernel')
    try {
        & $cargo build -p rd-wasm --release --target wasm32-unknown-unknown
        if ($LASTEXITCODE -ne 0) { throw "cargo build 失败（$LASTEXITCODE）" }
    } finally { Pop-Location }
    Copy-Item 'kernel\target\wasm32-unknown-unknown\release\rd_wasm.wasm' 'web\rd_wasm.wasm' -Force

    Write-Host '[2/3] 同步 wasm + 重建前端 …' -ForegroundColor Cyan
    & $node 'web-next\scripts\sync-wasm.mjs'
    if ($LASTEXITCODE -ne 0) { throw "sync-wasm 失败（$LASTEXITCODE）" }
    Push-Location (Join-Path $Root 'web-next')
    try {
        & $node (Join-Path (Split-Path (Get-Command npm).Source -Parent) 'node_modules\npm\bin\npm-cli.js') run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build 失败（$LASTEXITCODE）" }
    } finally { Pop-Location }
} else {
    if (-not (Test-Path $wasm)) {
        Write-Host '⚠️  dist 里没有 wasm。' -ForegroundColor Yellow
        Write-Host '    正常情况下它是入库的 —— 你可能是从一份"只提交了源码"的副本里来的。' -ForegroundColor Yellow
        Write-Host '    有 Rust 的话跑： pwsh tools/play.ps1 -Rebuild' -ForegroundColor Yellow
        throw '缺少 web-next/dist/rd_wasm.wasm'
    }
    if (-not (Test-Path $manifest)) { throw '缺少 web-next/dist/wasm.json（装载时会比对 sha，缺了会拒绝启动）' }
    Write-Host '[1/1] 用入库的 wasm（不重编）' -ForegroundColor DarkGray
}

Write-Host ''
Write-Host "▶ 启动静态服务器（入口：$Entry，端口：$Port —— 被占用时会自动换）" -ForegroundColor Green
Write-Host '  ⚠️ Windows 上 8080/8081 常被 Steam 的 CEF 调试端口占着；真端口以服务器打印的那行为准。' -ForegroundColor DarkGray
Write-Host '  Ctrl+C 退出' -ForegroundColor DarkGray
# ⚠️ 不要在这里预打印 URL：端口可能被占用而自动换掉，预打印的地址会指向别人的服务
# （实测过：8080 上答的是 Steam）。真地址由 serve.mjs 在**自检通过之后**打印。
& $node 'web-next\scripts\serve.mjs' --port $Port --entry $Entry
