"""把闸门 35（ui-p4-models）与 36（ui-next-p4）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[35/36] P4 展示逻辑：篝火位掩码 / 效果判别值 / 商店定价 / 选择器 / 药水（纯函数）"
$results += Invoke-Gate -Name 'ui-p4-models' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_p4_models_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_P4_MODELS PASS campfire=\\d+ effects=\\d+ shelves=\\d+ picker=\\d+ potions=\\d+' `
  -TimeoutSec 300

Write-Output "`n[36/36] P4 端到端：一段真实旅程把商店/篝火/宝箱/事件/选择器/药水全用一遍"
# 地图生成有硬规则（第 1-5 层没有篝火、第 9 层全宝箱、第 15 层全篝火），所以"走到这些屏"本身
# 就是被测对象：闸门从第 1 层往上走，遇到什么测什么，走两段旅程覆盖全部屏。
$results += Invoke-Gate -Name 'ui-next-p4' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_next_p4_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_NEXT_P4 PASS floors=\\d+ screens=[a-z,-]+ ' `
  -TimeoutSec 900

'''

t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/36]' % match.group(1)


t = re.sub(r'(\[\d+)/34\]', bump, t)

MARKER = ("'(UI_NEXT_LOOP PASS nodes=\\d+ steps=\\d+ "
          "scene-chain=SC-00>SC-01>SC-02>SC-03>SC-03b>SC-04>SC-02)')) {")
assert t.count(MARKER) == 1, t.count(MARKER)
t = t.replace(
    MARKER,
    "'(UI_NEXT_LOOP PASS nodes=\\d+ steps=\\d+ "
    "scene-chain=SC-00>SC-01>SC-02>SC-03>SC-03b>SC-04>SC-02)'," + chr(10) +
    "                     # P4：展示逻辑 + 端到端旅程" + chr(10) +
    "                     '(UI_P4_MODELS PASS campfire=\\d+ effects=\\d+ shelves=\\d+ "
    "picker=\\d+ potions=\\d+)'," + chr(10) +
    "                     '(UI_NEXT_P4 PASS floors=\\d+ screens=[a-z,-]+ )')) {",
)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000, '写出后大小异常'
os.replace(temp, PATH)
print('gates 35/36 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
