"""把闸门 29（`ui-wasm-ui`）接进验收：UI 与内核一致。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
import os as _os
assert _os.path.getsize(PATH) > 28000, 'acceptance.ps1 不完整（%d 字节）' % _os.path.getsize(PATH)

old = '''Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''
new = '''Write-Output "`n[29/29] P2 UI 与内核一致：主页面跑真 wasm，拖牌后 DOM 跟着内核变"
# 闸门 28 证明的是"适配器对"（对着 p2.html 的探针），这道证明的是"**渲染层**对"：
# 主页面默认走真 wasm，于是可以断言"屏幕上的敌人血量 == 内核观察向量里的血量"，
# 以及"从 UI 拖一张牌出去 ⇒ 内核接受 ⇒ **DOM 上的血量跟着变**"（不是只改了内存里的 view）。
# 这是 plan P2 退出条件"行动后 HP/能量/手牌与内核一致"的直接落地。
$results += Invoke-Gate -Name 'ui-wasm-ui' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_wasm_ui_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_WASM_UI PASS mode=wasm hand=\\d+ energy=\\d+ enemy0=\\d+->\\d+ dom-synced=1' `
  -TimeoutSec 300

Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''
assert t.count(old) == 1, '锚点 %d' % t.count(old)
t = t.replace(old, new)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/29]' % match.group(1)


t = re.sub(r'(\[\d+)/28\]', bump, t)

marker = "'(UI_WASM PASS exports=\\d+ content=0x[0-9a-f]{8} hand=\\d+ enemies=\\d+)'" + ")) {"
assert t.count(marker) == 1, 'evidence 锚点 %d' % t.count(marker)
t = t.replace(
    marker,
    "'(UI_WASM PASS exports=\\d+ content=0x[0-9a-f]{8} hand=\\d+ enemies=\\d+)'," + chr(10) +
    "                     # P2：主页面接真 wasm 之后 UI 与内核一致" + chr(10) +
    "                     '(UI_WASM_UI PASS mode=wasm hand=\\d+ energy=\\d+ enemy0=\\d+->\\d+)'" + ")) {",
)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 28000, '写出后大小异常 %d' % os.path.getsize(temp)
os.replace(temp, PATH)
print('gate 29 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
