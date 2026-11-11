"""把 `native/ui_pure_check.mjs` 接成闸门 27（`ui-pure`）。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
assert len(t) > 15000, 'acceptance.ps1 不完整（%d 字符）' % len(t)

old = '''Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''

new = '''Write-Output "`n[27/27] UI 纯函数回归：队形 0–6 敌 / 屏幕命中 / 状态机（含 dismiss）"
# 为什么单独成闸门：合并参考包之后，队形与屏幕命中是**纯函数**，它们的最强证据是"0–6 个敌人、
# 横竖屏、业务 slot 不重编号、超过 6 个响亮失败"这种穷尽式断言 —— 在浏览器里跑同样的事要
# 几十秒且只能覆盖一两种组合。与闸门 25/26 分开：红了要能一眼看出坏在纯逻辑、接线还是渲染。
$results += Invoke-Gate -Name 'ui-pure' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_pure_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_PURE PASS formation=0\\.\\.6 hit=\\d+ machine=\\d+' `
  -TimeoutSec 180

Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''

assert t.count(old) == 1, '锚点命中 %d 次' % t.count(old)
t = t.replace(old, new)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/27]' % match.group(1)


t = re.sub(r'(\[\d+)/26\]', bump, t)
print('bumped %d gate headers to /27' % count)

marker = "P1_REVIEW13_REPRO PASS)'" + ")) {"
assert t.count(marker) == 1, 'pattern 锚点命中 %d 次' % t.count(marker)
t = t.replace(
    marker,
    "P1_REVIEW13_REPRO PASS)'," + chr(10) +
    "                     # 纯函数回归：队形/命中/状态机" + chr(10) +
    "                     '(UI_PURE PASS formation=0\\.\\.6 hit=\\d+ machine=\\d+)'" + ")) {",
)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 24000, '写出后大小异常'
os.replace(temp, PATH)
print('gate 27 wired, %d bytes' % os.path.getsize(PATH))
