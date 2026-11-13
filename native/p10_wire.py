"""把闸门 47（ui-act）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[47/47] 幕间（§370）：幕数显示 + Boss 遗物三选一（只从 Boss 池、互不重复、拿走进腰带）"
# 换幕之后 floor 归 0，只画层数会变成"第 0 层"；act 只能从 rd_run_act() 读。
# 三选一是**内核动作**（offer_boss_relics / take_boss_relic），闸门用 ?debug 夹具造 offer
# （打赢 Boss 没法按需制造），取走与拒绝都走真内核。
$results += Invoke-Gate -Name 'ui-act' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_act_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_ACT PASS act=\\d+ offer=\\d+ taken=\\w+' `
  -TimeoutSec 600

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/47]' % match.group(1)


t = re.sub(r'(\[\d+)/46\]', bump, t)

lines = t.split('\n')
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1, len(close)
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # §370 幕间：幕数 + Boss 遗物三选一")
lines.insert(at + 2, "                     '(UI_ACT PASS act=\\d+ offer=\\d+ taken=\\w+)')) {")
t = '\n'.join(lines)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gate 47 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
