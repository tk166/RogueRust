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
  [int]$UnitsFloor = 813
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
                     '(\d+/\d+ tables)', '(\d+ monsters)', '(\d+) clicks',
                     '(\d+/\d+ card\(s\) painted)')) {
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

Write-Output "`n[1/20] 单元测试 + 语料逐字节回环（Rust 内核）"
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

Write-Output "[2/20] 语料回环份数（确认不是空扫）"
$r = Invoke-Gate -Name 'corpus-roundtrip' -Exe $CARGO `
  -ArgLine "test -p rd-core --release --target-dir `"$TARGET_DIR`" corpus -- --nocapture" `
  -Workdir (Join-Path $ROOT 'kernel') -MustMatch 'case\(s\) reproduced byte-for-byte'
$results += $r

Write-Output "[3/20] 裸机目标编译（riscv32imac-unknown-none-elf）"
$results += Invoke-Gate -Name 'rust-baremetal' -Exe $CARGO `
  -ArgLine "check --target riscv32imac-unknown-none-elf -p rd-core -p rd-run --release --target-dir `"$TARGET_DIR`"" `
  -Workdir (Join-Path $ROOT 'kernel') -MustMatch 'Finished'

Write-Output "[4/20] clippy"
$results += Invoke-Gate -Name 'rust-clippy' -Exe $CARGO `
  -ArgLine "clippy --all-targets -p rd-core -p rd-run -p rd-wasm --target-dir `"$TARGET_DIR`"" -Workdir (Join-Path $ROOT 'kernel') `
  -MustMatch 'Finished'

Write-Output "[5/20] 真链接成裸机 ELF 镜像"
$fw = Join-Path $ROOT 'kernel\rd-firmware\link.x'
$results += Invoke-Gate -Name 'firmware-link' -Exe $CARGO `
  -ArgLine "rustc --release --target riscv32imac-unknown-none-elf --manifest-path rd-firmware/Cargo.toml -- -C link-arg=-T$fw" `
  -Workdir (Join-Path $ROOT 'kernel') -MustMatch 'Finished'

Write-Output "[6/20] 镜像占用（自带陈旧守卫）"
$results += Invoke-Gate -Name 'firmware-size' -Exe $PY `
  -ArgLine (Join-Path $ROOT 'tools\firmware_size.py') -Workdir $ROOT -MustMatch '非易失存储'

Write-Output "[7/20] 覆盖门禁"
$results += Invoke-Gate -Name 'coverage-gate' -Exe $PY `
  -ArgLine (Join-Path $ROOT 'native\coverage_check.py') -Workdir $ROOT -MustMatch '19/19'

Write-Output "[8/20] golden 基线逐字节一致"
$ga = Join-Path $ROOT 'corpus\golden_v1.jsonl'
$gb = Join-Path $ROOT 'corpus\baseline\golden_v1.jsonl'
$same = ((Get-FileHash $ga -Algorithm SHA256).Hash -eq (Get-FileHash $gb -Algorithm SHA256).Hash)
$results += [pscustomobject]@{
  Gate = 'golden-baseline'; Exit = $(if ($same) { 0 } else { 1 }); Ok = $same
  Evidence = "$((Get-Content $ga).Count) 行"; Notes = $(if ($same) { '' } else { 'SHA-256 不一致' }); Output = ''
}

Write-Output "[9/20] RL 环境冒烟（多开 + 确定性）"
$results += Invoke-Gate -Name 'env-smoke' -Exe $PY -ArgLine '-m roguedeck_env.bench' `
  -Workdir (Join-Path $ROOT 'py') -MustMatch '多开吞吐与可复现性均通过' `
  -ExtraEnv @{ PYTHONPATH = (Join-Path $ROOT 'py') } -TimeoutSec 1800

Write-Output "`n[10/20] 内容镜像 byte-identity（用当前编译器重编源文档 == 钉死的 SHA）"
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

Write-Output "[11/20] 内容镜像结构不变量（独立解读字节：段目录 + 7 张定长表的 count×stride）"
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
  -MustMatch 'RDCF_VERIFY PASS \(2/2 variants, 7/7 tables, 14 count×stride checks' -TimeoutSec 300

Write-Output "`n[12/20] StS 内容包自洽（不变量表 + 两份镜像逐键回读 + 交叉引用）"
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

Write-Output "`n[13/20] 重编网页那一份 .wasm（web/** 是仓库里唯一被手工 Copy-Item 进来的二进制产物）"
# 为什么这条闸门必须存在：`web/rd_wasm.wasm` 被三方引用 —— index.html 硬编码的 122 格偏移、
# smoke.mjs 的导出手抄清单、README 里钉死的字节数 —— 而它**不在 cargo 的依赖图里**：
# 源码改了不重编，它照样绿。（真实测到的两种"时间说谎"：Copy-Item 恢复文件会把 mtime 一起
# 恢复；而只改一行注释又会让产物看起来比新源码更旧。所以 [+5] 的判据是**字节**，不是时间。）
$results += Invoke-Gate -Name 'wasm-rebuild' -Exe $CARGO `
  -ArgLine "build -p rd-wasm --release --target wasm32-unknown-unknown" -Workdir (Join-Path $ROOT 'kernel') `
  -MustMatch 'Finished' -TimeoutSec 600

Write-Output "[14/20] 页面 + 产物：字节同一 + 脚本能解析 + 只在真导出上调用 + 偏移仍铺满"
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

Write-Output "[15/20] 界面渲染的**语义**（不是语法）：每一格显示的数 == 观察向量里那一格"
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

Write-Output "[16/20] 地图页：画出来的东西**就是** rd-run 生成的那张图（逐节点、逐边、逐格光照）"
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
Write-Output "`n[17/20] 真浏览器：点下去，断言渲染出来的文字"
$results += Invoke-Gate -Name 'web-browser' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\browser_test.mjs') -Workdir $ROOT -MustMatch 'BROWSER_TEST PASS' -TimeoutSec 600

# 门 18：**整局随机 soak**（§151）。门 17 是一条**写死**的路径，而 §150 的药水 bug 在它后面活了三个
# 小节 —— 因为那条路径不点药水。这一道用带种子的 PRNG 随机点**每一个启用中的控件**，每点一次问一句
# "有东西变了吗"：死按钮违反的正是这一条，而它不关心是哪个按钮。另外断言"页面没抛异常"与"走过若干种
# 界面"（商店/篝火/宝箱/事件…），否则"随机点 300 次什么都没坏"可能只是没点到东西。
Write-Output "`n[18/20] 随机 soak：每个启用中的控件点一下都必须有反应"
$results += Invoke-Gate -Name 'web-soak' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\soak_test.mjs') -Workdir $ROOT -MustMatch 'SOAK_TEST PASS' -TimeoutSec 900

# 门 19：**一幕垂直切片**（§161.8，REVIEW §六 第 3 步）。
# 门 17 是一条写死的路，门 18 是随机点 —— 两者都不能证明
# "商店能买东西""精英会给遗物""篟火能打铁"。
# 这一道在固定种子上**自己算路线**走到每一种节点。
Write-Output "`n[19/20] 一幕垂直切片：自己算路线走遍每种节点"
$results += Invoke-Gate -Name 'web-slice' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\act1_slice.mjs') -Workdir $ROOT `
  -MustMatch 'ACT1_SLICE PASS' -TimeoutSec 900

# 门 20：**像素**（§168）。前面 19 道都在问"状态对不对 / 文字对不对"，没有一道问"**画出来是什么样**"——
# 一个把文字画成背景色的主题、一张 DOM 里有而屏幕上没有的牌、一行溢出面板的卡，都能让 19 道全绿。
# 这一道**不比基线图**（字体/缩放一变就红，而且人只会重录它），只断言可度量的性质：
# 棋盘上确实有墨、墨与底色**看得清**、每张牌自己的矩形在"藏起卡牌"前后**变过**、卡牌没有画到条带外面、
# 两次同状态截图**逐像素相同**。最后一段是**故障注入**：把 `--ink` 设成底色、藏掉一张牌、压扁手牌条带、
# 藏掉棋盘，逐个确认**同一批探测器会红** —— 否则"像素门通过"什么也没证明。
Write-Output "`n[20/20] 像素：画出来是什么样（不比基线，只断性质）"
$results += Invoke-Gate -Name 'web-pixel' -Exe 'C:\Program Files\nodejs\node.exe' `
  -ArgLine (Join-Path $ROOT 'web\pixel_test.mjs') -Workdir $ROOT `
  -MustMatch 'PIXEL_TEST PASS' -TimeoutSec 600

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
