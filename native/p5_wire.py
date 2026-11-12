"""把闸门 37（ui-beats）与 38（ui-next-p5）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[37/38] P5 Beat 演出导演 + 资源降级（纯函数：13 种 kind / 未知降级 / 关动画 / 跳过）"
$results += Invoke-Gate -Name 'ui-beats' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_beats_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_BEATS PASS kinds=\\d+ unknown=degraded dropped=counted skip=clears reduced=quiet assets=\\d+' `
  -TimeoutSec 300

Write-Output "`n[38/38] P5 端到端：飘字真的出现且不挡输入、关动画也能打完、幕间推进被内核把关"
$results += Invoke-Gate -Name 'ui-next-p5' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_next_p5_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_NEXT_P5 PASS kinds=[0-9,]+ skip=\\d+ motion-off=\\d act-refusal=-?\\d+' `
  -TimeoutSec 600

'''

t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/38]' % match.group(1)


t = re.sub(r'(\[\d+)/36\]', bump, t)

MARKER = "                     '(UI_NEXT_P4 PASS floors=\\d+ screens=[a-z,-]+ )')) {"
assert t.count(MARKER) == 1, t.count(MARKER)
t = t.replace(
    MARKER,
    "'(UI_NEXT_P4 PASS floors=\\d+ screens=[a-z,-]+ )'," + chr(10) +
    "                     # P5：Beat 演出 + 幕间推进" + chr(10) +
    "                     '(UI_BEATS PASS kinds=\\d+ unknown=degraded dropped=counted skip=clears "
    "reduced=quiet assets=\\d+)'," + chr(10) +
    "                     '(UI_NEXT_P5 PASS kinds=[0-9,]+ skip=\\d+ motion-off=\\d act-refusal=-?\\d+)')) {",
)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000, '写出后大小异常'
os.replace(temp, PATH)
print('gates 37/38 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
