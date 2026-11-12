"""把闸门 39（ui-mobile）与 40（ui-soak-p6）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[39/40] P6 移动端：390x844 触摸走完整流程 + 44px 触控目标 + 安全区 + DPR 上限"
# 触摸是**真事件链**（Emulation.setTouchEmulationEnabled + Input.dispatchTouchEvent）：
# 触摸才有长按详情、没有 hover、并且会被祖先滚动容器抢走手势（第一版触摸拖牌完全无效）。
$results += Invoke-Gate -Name 'ui-mobile' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_mobile_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_MOBILE PASS targets=\\d+ min=\\d+ dpr-cap=[\\d.]+ backing=\\d+ safe-top=\\d+ drag=[01]' `
  -TimeoutSec 600

Write-Output "`n[40/40] P6 稳定性：8 次重开 / 长局 / 重载 / WebGL 上下文丢失 / 动效偏好持久化"
$results += Invoke-Gate -Name 'ui-soak-p6' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_soak_p6_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_SOAK_P6 PASS restarts=\\d+ steps=\\d+ heap=\\d+KB->\\d+KB context-lost=\\d motion-persisted=\\d' `
  -TimeoutSec 900

'''

t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/40]' % match.group(1)


t = re.sub(r'(\[\d+)/38\]', bump, t)

MARKER = "                     '(UI_NEXT_P5 PASS kinds=[0-9,]+ skip=\\d+ motion-off=\\d act-refusal=-?\\d+)')) {"
assert t.count(MARKER) == 1, t.count(MARKER)
t = t.replace(
    MARKER,
    "'(UI_NEXT_P5 PASS kinds=[0-9,]+ skip=\\d+ motion-off=\\d act-refusal=-?\\d+)'," + chr(10) +
    "                     # P6：移动端 + 稳定性" + chr(10) +
    "                     '(UI_MOBILE PASS targets=\\d+ min=\\d+ dpr-cap=[\\d.]+ backing=\\d+ "
    "safe-top=\\d+ drag=[01])'," + chr(10) +
    "                     '(UI_SOAK_P6 PASS restarts=\\d+ steps=\\d+ heap=\\d+KB->\\d+KB "
    "context-lost=\\d motion-persisted=\\d)')) {",
)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000, '写出后大小异常'
os.replace(temp, PATH)
print('gates 39/40 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
