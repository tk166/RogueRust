"""把闸门 33（ui-scene，纯函数）与 34（ui-next-loop，端到端）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
assert os.path.getsize(PATH) > 30000, 'acceptance.ps1 不完整'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, '锚点命中 %d 次' % t.count(ANCHOR)

BLOCK = '''Write-Output "`n[33/34] P3 场景判定：18 行表的顺序陷阱 + 穷尽性（纯函数，不需要浏览器）"
# `SC-03b` 必须排在 `SC-03` 之前、`SC-02b` 必须排在 `SC-02` 之前；18 行表逐行有夹具；
# 任何内核事实的组合都能得到一个场景（`unknownPending` 只在相位越界时非空）。
$results += Invoke-Gate -Name 'ui-scene' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_scene_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_SCENE PASS order=\\d+\\+\\d+ pending=\\d+ exhaustive=\\d+ rows=\\d+' `
  -TimeoutSec 300

Write-Output "`n[34/34] P3 端到端：标题 → 祝福 → 地图 → 战斗（含真实 3D 拾取）→ 奖励 → 地图"
# 全程用真 DOM 点击（开始/祝福/地图节点/领奖励/继续），一次真实 3D 拖拽（CDP 鼠标事件），
# 每个阶段断言对账干净，最后断言"不刷新页面场景判定仍然稳定"。
$results += Invoke-Gate -Name 'ui-next-loop' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_next_loop_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_NEXT_LOOP PASS nodes=\\d+ steps=\\d+ scene-chain=SC-00>SC-01>SC-02>SC-03>SC-03b>SC-04>SC-02' `
  -TimeoutSec 600

'''

t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/34]' % match.group(1)


t = re.sub(r'(\[\d+)/32\]', bump, t)

MARKER = "'(UI_WASM_XCOST PASS seed=\\d+ card=\\w+ energy=\\d+->0 damaged=\\d+)')) {"
assert t.count(MARKER) == 1, 'evidence 锚点命中 %d 次' % t.count(MARKER)
t = t.replace(
    MARKER,
    "'(UI_WASM_XCOST PASS seed=\\d+ card=\\w+ energy=\\d+->0 damaged=\\d+)'," + chr(10) +
    "                     # P3：场景判定（纯函数）与端到端闭环" + chr(10) +
    "                     '(UI_SCENE PASS order=\\d+\\+\\d+ pending=\\d+ exhaustive=\\d+ rows=\\d+)'," + chr(10) +
    "                     '(UI_NEXT_LOOP PASS nodes=\\d+ steps=\\d+ scene-chain=SC-00>SC-01>SC-02>SC-03>SC-03b>SC-04>SC-02)')) {",
)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000, '写出后大小异常'
os.replace(temp, PATH)
print('gates 33/34 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
