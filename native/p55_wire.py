"""接闸门 57（ui-cues）。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()
assert 'ui-cues' not in t, '闸门 57 已经接过了'

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1

BLOCK = '''Write-Output "`n[57/57] 表现层契约（§399）：Beat → Cue（带来源）→ 视觉配方"
# 审阅 §6 的核心批评：`planBeats` 丢了 def/actor/flags，于是"Strike 的斩击"与"Bash 的重击"
# 在数据上一模一样，做动画只能靠数值反推。现在 Cue 带 origin/effectKey/冻结锚点，配方是纯数据
# —— 闸门穷尽断言 13 种 kind、逐卡可分、未知不静默。
$results += Invoke-Gate -Name 'ui-cues' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_cues_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_CUES PASS kinds=\\d+ recipes=\\d+ cards=\\d+' `
  -TimeoutSec 300

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/57]' % match.group(1)


t = re.sub(r'(\[\d+)/56\]', bump, t)
assert count == 56, count

lines = t.split('\n')
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # §399 表现层契约")
lines.insert(at + 2, "                     '(UI_CUES PASS kinds=\\d+ recipes=\\d+ cards=\\d+)')) {")
t = '\n'.join(lines)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gate 57 wired, %d bytes' % os.path.getsize(PATH))
