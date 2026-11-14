"""接闸门 55（ui-readout）。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
assert 'ui-readout' not in t, '闸门 55 已经接过了'

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[55/55] 看得见的信息（§378–§379）：状态 / 遗物 / 悬浮详情"
# 三件都是"数据在、界面没读"：状态（观察向量只有 5 条轴，完整那份走 rd_env_status_*）、
# 遗物（顶栏只有一个数字）、卡牌详情（奖励/商店只有名字，怎么选全靠猜）。
# 断言在 DOM 上，且用**真鼠标移动**触发详情（这条闸门守的就是鼠标路径）。
$results += Invoke-Gate -Name 'ui-readout' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_readout_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_READOUT PASS statuses=\\d+ relics=\\d+ tips=\\d+' `
  -TimeoutSec 420

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/55]' % match.group(1)


t = re.sub(r'(\[\d+)/54\]', bump, t)
assert count == 54, count

lines = t.split('\n')
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1, len(close)
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # §378/§379 状态 + 遗物 + 悬浮详情")
lines.insert(at + 2, "                     '(UI_READOUT PASS statuses=\\d+ relics=\\d+ tips=\\d+)')) {")
t = '\n'.join(lines)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gate 55 wired, %d bytes' % os.path.getsize(PATH))
