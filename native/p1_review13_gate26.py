"""把纯状态机回归（`native/p1_review13_repro.mjs`）作为**闸门 26**接进验收。

## 为什么不塞进闸门 25

闸门 25 是**浏览器**闸门（CDP + 真指针事件 + 真 wasm 包），跑一次要几十秒。纯状态机回归不需要
浏览器，但它守的是另一件事：**"同一件事做两次"** 与 **"物理落点 ≠ 业务目标"**。

这两条缺陷之所以能活过 41 条浏览器断言，就是因为那些断言里没有一条要求同一动作做两次。
分开成一道闸门，红了能一眼看出是哪一层坏了（状态机 vs 接线 vs 渲染）。

## 它自带编译

脚本会先 `npx tsc` 把 `src/input/pointerMachine.ts` 编成 JS 再跑，所以它测的是**当前源码**，
不是某个陈旧的产物。
"""

import io
import os

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
assert len(t) > 15000, 'acceptance.ps1 不完整（%d 字符）' % len(t)

old = '''Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''

new = '''Write-Output "`n[26/26] UI 纯状态机回归：同一动作做两次 / 物理落点 ≠ 业务目标"
# 为什么这条单独成闸门：第十三轮 Review 的 P1-A / P1-B 都是"从控制流能推出来、但 41 条浏览器
# 断言全都没覆盖"的缺陷 —— 那些断言里没有一条要求**同一件事做两次**。它们分别表现为
# "payload 相同的第二次操作被内容去重吞掉"与"无目标牌丢在敌人身上被判成回弹（判定与执行矛盾）"。
#
# 这条不需要浏览器（编译后直接跑状态机），所以与闸门 25 分开：红了能一眼看出坏在
# 状态机、接线还是渲染。脚本自带 `npx tsc`，测的是**当前源码**而不是陈旧产物。
$results += Invoke-Gate -Name 'ui-pointer' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\p1_review13_repro.mjs') -Workdir $ROOT `
  -MustMatch 'P1_REVIEW13_REPRO PASS: 三条都已修复' `
  -TimeoutSec 180

Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''

assert t.count(old) == 1, '锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

import re
count = 0


def bump(match):
    global count
    count += 1
    return '%s/26]' % match.group(1)


t = re.sub(r'(\[\d+)/25\]', bump, t)
print('bumped %d gate headers to /26' % count)

# 证据列：加一条 pattern（否则会是空列 —— 上一轮就是这么漏的）
marker = "minTitle=" + chr(92) + "d+px)'" + ")) {"
assert t.count(marker) == 1, 'pattern 锚点命中 %d 次' % t.count(marker)
t = t.replace(marker, marker[:-3] + "," + chr(10) +
              "                     # 纯状态机回归：修复后的三条断言（判据是 PASS 串本身）" + chr(10) +
              "                     '(P1_REVIEW13_REPRO PASS)'" + ")) {")

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 24000, '写出后大小异常'
os.replace(temp, PATH)
print('gate 26 wired, %d bytes' % os.path.getsize(PATH))
