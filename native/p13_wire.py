"""把闸门 51（ui-replay）接进验收。"""

import io
import os
import re

PATH = 'tools/acceptance.ps1'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = ('Write-Output "`n" + ("-" * 78)\n'
          'Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f \'闸门\', \'退出\', \'证据\', \'备注\')')
assert t.count(ANCHOR) == 1, t.count(ANCHOR)

BLOCK = '''Write-Output "`n[51/51] 回放（§373）：导出到剪贴板 / 导入并逐步对拍 / 分叉报在第几步"
# 回放与存档是两件事：存档描述"现在这一局"，脚本描述"这一局是怎么走到现在的"（每步带指纹）。
# 导入时内核逐步比对 ⇒ 分叉在第几步是可说的。脚本头自带 seed/进阶/内容指纹，所以导入不用先开局。
$results += Invoke-Gate -Name 'ui-replay' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_replay_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_REPLAY PASS bytes=\\d+ steps=\\d+ diverged=\\d+' `
  -TimeoutSec 600

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)

count = 0


def bump(match):
    global count
    count += 1
    return '%s/51]' % match.group(1)


t = re.sub(r'(\[\d+)/50\]', bump, t)

lines = t.split('\n')
start = next(i for i, line in enumerate(lines) if 'foreach ($pat in @(' in line)
end = next(i for i, line in enumerate(lines) if '[regex]::Match($out, $pat)' in line)
close = [i for i in range(start, end) if lines[i].rstrip().endswith(')) {')]
assert len(close) == 1, len(close)
at = close[0]
lines[at] = lines[at].rstrip()[:-len(')) {')].rstrip().rstrip(',') + ','
lines.insert(at + 1, "                     # §373 回放：导出 / 导入逐步对拍")
lines.insert(at + 2, "                     '(UI_REPLAY PASS bytes=\\d+ steps=\\d+ diverged=\\d+)')) {")
t = '\n'.join(lines)

temp = PATH + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 30000
os.replace(temp, PATH)
print('gate 51 wired, %d bytes, bumped %d' % (os.path.getsize(PATH), count))
