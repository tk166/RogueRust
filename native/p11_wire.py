"""把闸门 48（ui-curtain）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[48/48] 幕间幕布（§2.3）：act 变大才播 / 不挡操作 / 1.6 秒自动淡出 / 关动画不播"
# 规格原文："纯演出，1.6 秒自动淡出。触发条件是 act 变大，**不需要**任何新导出。"
# 所以判定是纯函数（6 条边界），覆盖层 pointer-events: none（换幕后第一件事是点地图）。
$results += Invoke-Gate -Name 'ui-curtain' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_curtain_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_CURTAIN PASS cases=\\d+ auto=1 click=1' `
  -TimeoutSec 300

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/48]' % match.group(1)


t = re.sub(r'(\[\d+)/47\]', bump, t)

lines = t.split('\n')
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1, len(close)
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # §2.3 幕间幕布")
lines.insert(at + 2, "                     '(UI_CURTAIN PASS cases=\\d+ auto=1 click=1)')) {")
t = '\n'.join(lines)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gate 48 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
