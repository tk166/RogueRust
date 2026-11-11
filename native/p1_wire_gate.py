"""把闸门 25（`ui-next`）接进 `tools/acceptance.ps1`。

## 为什么 P1 也需要一道闸门

P1 的退出条件不是"截个图看看"：它要求"选中具体卡牌 → 指向正确敌人 → 释放；取消/非法释放
回弹；移动端触摸完成同样操作"。这三条**只有**在真浏览器里用真指针事件跑才成立 —— 直接调
`reduce()` 会绕开射线、绕开 R3F 的事件派发、绕开 DOM 覆盖层，而那三处恰恰是 3D UI 最容易坏
的地方。所以 `native/ui_next_check.mjs` 用 CDP 派发 `Input.dispatchMouseEvent` /
`Input.dispatchTouchEvent`，判据一律读 `window.__p1` 探针。

## 这道闸门"骗过人"的地方（都已修）

* 第一版只看"提交数变没变" ⇒ "根本没抓住牌"与"抓住了但被拒绝"分不开，负控假绿。
  现在每条负控先断言 `phase === 'pressed' && handSlot === 期望值`。
* 第一版按**牌心**点 ⇒ 窄屏叠放时命中的是右邻那张。现在按布局给出的 `hitX`（露出那条的中点）。
* 第一版先释放再截图"选中态" ⇒ 牌早就回位了。现在 `mouseHold` 按住不放再截图。
* 第一版只查"卡牌中心在视口内" ⇒ 牌身被裁掉一半也报通过。现在断言**露出的宽度**与
  "每张牌要么标题可读、要么明确收起为紧凑态"的不变量。

## 依赖

`web-next/dist/` **入库**（构建产物，约 1.8 MB），这样闸门不需要 `npm install` 也不需要网络。
重建：`cd web-next && npm ci && npm run build`（`node_modules/` 不入库）。

## ⚠️ 写盘方式

先写 `.tmp` 再 `rename`：上一个版本的这条脚本把 `acceptance.ps1` **截断成 0 字节**
（`io.open(..., 'w')` 会先截断文件，然后才因为 `newline` 参数非法抛异常）。
"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
assert len(t) > 15000, 'acceptance.ps1 看起来不完整（%d 字节）' % len(t)

old = '''Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''

new = '''Write-Output "`n[25/25] UI P1（R3F PoC）：拖动/目标/回弹/触摸/模态隔离/中文可读性"
# 为什么这条必须是一道闸门：P1 的退出条件是"选中具体卡牌 → 指向正确敌人 → 释放；取消/非法释放
# 回弹；移动端触摸完成同样操作"，这三条只有在**真浏览器 + 真指针事件**里跑才成立 ——
# 直接调状态机函数会绕开射线、绕开 R3F 的事件派发、绕开 DOM 覆盖层，而那三处恰恰是 3D UI
# 最容易坏的地方（第十二轮 Review P1-C 的同一条教训）。
#
# `web-next/dist/` 入库，所以这道闸门**不需要 npm、不需要网络**；重建见 `docs/ui-next-p1.md`。
# 证据串里的四个数字是这道闸门的存在理由：commits（真提交）、rebound（真回弹）、
# touch（触摸走同一套状态机）、modal-isolation（模态吃掉了输入）。
$results += Invoke-Gate -Name 'ui-next' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_next_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_NEXT PASS cards=10 enemies=2 commits=\\d+ rebound=\\d+ touch=1 modal-isolation=1 minTitle=\\d+px' `
  -TimeoutSec 300

Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''

assert t.count(old) == 1, '锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/25]' % match.group(1)


t = re.sub(r'(\[\d+)/24\]', bump, t)
print('bumped %d gate headers to /25' % count)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 24000, '写出后大小异常'
os.replace(temp, PATH)
print('gate 25 wired, %d bytes' % os.path.getsize(PATH))
