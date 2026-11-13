"""把闸门 49（ui-save）与 50（ui-distributable）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[49/50] 自动存档（§372）：写 / 继续上次逐字段相同 / 战斗中不写 / 坏档被丢"
# 默认入口已经是新 UI ⇒"刷新就丢一局"对正式入口不可接受。存档走内核的档案格式
# （MAGIC-base64-校验和 + 内容指纹），页面只做搬运；战斗中内核拒绝存档，所以刷新只会回到开战前。
$results += Invoke-Gate -Name 'ui-save' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_save_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_SAVE PASS bytes=\\d+ restored=1 corrupt=1' `
  -TimeoutSec 600

Write-Output "`n[50/50] 产物可得（§372）：dist 的 wasm 入库 + 一条命令能玩"
# 判据是 **git 跟踪**（`ls-files --error-unmatch`），不是"磁盘上有"——磁盘上有但没跟踪，
# clone 下来照样没有。这正是"代码全在、玩不了"的那种缺口。
$results += Invoke-Gate -Name 'ui-distributable' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_distributable_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_DISTRIBUTABLE PASS wasm=\\d+ tracked=2 assets=\\d+ play=ok' `
  -TimeoutSec 300

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/50]' % match.group(1)


t = re.sub(r'(\[\d+)/48\]', bump, t)

lines = t.split('\n')
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1, len(close)
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # §372 自动存档 + 产物可得")
lines.insert(at + 2, "                     '(UI_SAVE PASS bytes=\\d+ restored=1 corrupt=1)',")
lines.insert(at + 3, "                     '(UI_DISTRIBUTABLE PASS wasm=\\d+ tracked=2 assets=\\d+ play=ok)')) {")
t = '\n'.join(lines)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gates 49/50 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
