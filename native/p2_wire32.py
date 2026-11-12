"""把闸门 32（`ui-wasm-xcost`）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
assert os.path.getsize(PATH) > 30000, 'acceptance.ps1 不完整'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, '锚点命中 %d 次' % t.count(ANCHOR)

BLOCK = '''Write-Output "`n[32/32] P2 X 费：真牌、真能量、打出后能量归零（plan P2 最后一条定向夹具）"
# X 费牌不在起手牌、药水三选一也不给（扫过 14 个种子 × 2 种药水共 28 组），唯一确定性入口是
# 战斗奖励屏：开局 → 打赢 → fight_end（这一步才生成奖励屏）→ 挑一张 X 费牌 → 下一场抽到它 → 打出去。
# seed 58 的奖励含 whirlwind（seed 59 含 skewer），所以夹具是确定性的。
$results += Invoke-Gate -Name 'ui-wasm-xcost' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_wasm_xcost_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_WASM_XCOST PASS seed=\\d+ card=\\w+ energy=\\d+->0 damaged=\\d+' `
  -TimeoutSec 300

'''

t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/32]' % match.group(1)


t = re.sub(r'(\[\d+)/31\]', bump, t)

MARKER = "'(UI_WASM_FIXTURES PASS duplicate=\\d+ zero-energy=1 slot-stable=1)')) {"
assert t.count(MARKER) == 1, 'evidence 锚点命中 %d 次' % t.count(MARKER)
t = t.replace(
    MARKER,
    "'(UI_WASM_FIXTURES PASS duplicate=\\d+ zero-energy=1 slot-stable=1)'," + chr(10) +
    "                     # P2：X 费扣能量" + chr(10) +
    "                     '(UI_WASM_XCOST PASS seed=\\d+ card=\\w+ energy=\\d+->0 damaged=\\d+)')); {",
)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000, '写出后大小异常'
os.replace(temp, PATH)
print('gate 32 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
